"""Explicit PubChem resolver tests with no live network access."""

from __future__ import annotations

import io
import json
from urllib.error import HTTPError, URLError

import pytest

import thermoml_io.pubchem as pubchem_module
from thermoml_io import (
    AmbiguousComponentError,
    ComponentNotFoundError,
    PubChemResolutionError,
    resolve_pubchem_component,
)


class _Response:
    def __init__(
        self,
        data: bytes | str,
        *,
        content_length: str | None = None,
        headers: object | None = None,
    ) -> None:
        self.data = data
        self.headers = headers if headers is not None else {}
        if content_length is not None and isinstance(self.headers, dict):
            self.headers["Content-Length"] = content_length

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, size: int):
        return self.data[:size]


def _payload(*records: dict[str, object]) -> bytes:
    return json.dumps({"PropertyTable": {"Properties": records}}).encode()


def test_pubchem_resolution_merges_duplicate_structure_records(monkeypatch) -> None:
    data = _payload(
        {
            "CID": 783,
            "Title": "Hydrogen",
            "IUPACName": "molecular hydrogen",
            "MolecularFormula": "H2",
            "InChI": "InChI=1S/H2/h1H",
            "InChIKey": "UFHFLCQGNIYNRP-UHFFFAOYSA-N",
        },
        {
            "CID": 58838673,
            "IUPACName": "hydrogen monohydride",
            "MolecularFormula": "H2",
            "InChI": "InChI=1S/H2/h1H",
            "InChIKey": "UFHFLCQGNIYNRP-UHFFFAOYSA-N",
        },
    )
    seen = []

    def respond(request, *, timeout):
        seen.append((request.full_url, timeout, request.headers["User-agent"]))
        return _Response(data, content_length=str(len(data)))

    monkeypatch.setattr(pubchem_module, "urlopen", respond)
    identity = resolve_pubchem_component(" molecular hydrogen ", timeout=4)
    assert identity.preferred_name == "Hydrogen"
    assert identity.formulas == ("H2",)
    assert identity.pubchem_cids == (783, 58838673)
    assert seen[0][1:] == (4, "thermoml-io/0.1")
    assert "/name/molecular%20hydrogen/" in seen[0][0]


def test_pubchem_ambiguous_and_sparse_results(monkeypatch) -> None:
    ambiguous = _payload(
        {"CID": 1, "Title": "candidate", "InChIKey": "ONE"},
        {"CID": 2, "Title": "candidate", "InChIKey": "TWO"},
    )
    monkeypatch.setattr(pubchem_module, "urlopen", lambda *_args, **_kwargs: _Response(ambiguous))
    with pytest.raises(AmbiguousComponentError, match="ambiguous"):
        resolve_pubchem_component("candidate")

    sparse = _payload({"CID": 3})
    monkeypatch.setattr(pubchem_module, "urlopen", lambda *_args, **_kwargs: _Response(sparse))
    identity = resolve_pubchem_component("3", namespace="cid")
    assert identity.preferred_name == "3"
    assert identity.pubchem_cids == (3,)


@pytest.mark.parametrize(
    "payload",
    [
        b"[]",
        b"{}",
        b'{"PropertyTable": {"Properties": []}}',
    ],
)
def test_pubchem_missing_or_unexpected_payload(monkeypatch, payload: bytes) -> None:
    monkeypatch.setattr(pubchem_module, "urlopen", lambda *_args, **_kwargs: _Response(payload))
    error = PubChemResolutionError if payload == b"[]" else ComponentNotFoundError
    with pytest.raises(error):
        resolve_pubchem_component("missing")


def test_pubchem_malformed_json_and_records(monkeypatch) -> None:
    monkeypatch.setattr(pubchem_module, "urlopen", lambda *_args, **_kwargs: _Response(b"\xff"))
    with pytest.raises(PubChemResolutionError, match="invalid JSON"):
        resolve_pubchem_component("bad")

    malformed = json.dumps({"PropertyTable": {"Properties": ["bad"]}}).encode()
    monkeypatch.setattr(pubchem_module, "urlopen", lambda *_args, **_kwargs: _Response(malformed))
    with pytest.raises(PubChemResolutionError, match="malformed"):
        resolve_pubchem_component("bad")


def test_pubchem_response_limits_and_types(monkeypatch) -> None:
    responses = iter(
        (
            _Response(b"{}", content_length="invalid"),
            _Response(b"{}", content_length="100"),
            _Response(b"12345"),
            _Response("not bytes"),
            _Response(b"{}", headers=object()),
        )
    )
    monkeypatch.setattr(pubchem_module, "urlopen", lambda *_args, **_kwargs: next(responses))
    with pytest.raises(PubChemResolutionError, match="invalid Content-Length"):
        resolve_pubchem_component("x", max_bytes=10)
    with pytest.raises(PubChemResolutionError, match="declares"):
        resolve_pubchem_component("x", max_bytes=10)
    with pytest.raises(PubChemResolutionError, match="exceeded"):
        resolve_pubchem_component("x", max_bytes=4)
    with pytest.raises(PubChemResolutionError, match="non-binary"):
        resolve_pubchem_component("x")
    with pytest.raises(ComponentNotFoundError):
        resolve_pubchem_component("x")


def test_pubchem_http_and_network_failures(monkeypatch) -> None:
    failures = iter(
        (
            HTTPError("https://example.invalid", 404, "missing", {}, io.BytesIO()),
            HTTPError("https://example.invalid", 500, "failure", {}, io.BytesIO()),
            URLError("offline"),
        )
    )

    def fail(*_args, **_kwargs):
        raise next(failures)

    monkeypatch.setattr(pubchem_module, "urlopen", fail)
    with pytest.raises(ComponentNotFoundError):
        resolve_pubchem_component("missing")
    with pytest.raises(PubChemResolutionError, match="HTTP status 500"):
        resolve_pubchem_component("broken")
    with pytest.raises(PubChemResolutionError, match="Could not query"):
        resolve_pubchem_component("offline")


def test_pubchem_input_validation() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        resolve_pubchem_component(" ")
    with pytest.raises(ValueError, match="Unsupported"):
        resolve_pubchem_component("x", namespace="bad")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="positive"):
        resolve_pubchem_component("x", max_bytes=0)
