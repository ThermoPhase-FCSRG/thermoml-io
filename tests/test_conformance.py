"""Tests for isolated metadata-only conformance sources."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

import thermoml_io.conformance as conformance
from thermoml_io import (
    ThermoMLSourceError,
    get_conformance_source,
    list_conformance_sources,
)


def test_packaged_iupac_corpus_is_not_experimental_data() -> None:
    sources = list_conformance_sources()
    assert len(sources) == 1
    source = get_conformance_source("iupac-thermoml-v4-use-cases")
    assert source.organization.endswith("(IUPAC)")
    assert source.thermoml_version == "4.0"
    assert source.use_case_count == 14
    assert source.included_by_default is False
    assert source.experimental_query_eligible is False
    with pytest.raises(ThermoMLSourceError, match="Unknown"):
        get_conformance_source("missing")


def test_conformance_registry_rejects_unsafe_or_mixed_sources(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "sources.json"
    monkeypatch.setattr(conformance, "_registry_path", lambda: path)
    path.write_text('{"schema_version":2}', encoding="utf-8")
    with pytest.raises(ThermoMLSourceError, match="schema"):
        list_conformance_sources()

    packaged = Path("src/thermoml_io/data/conformance_sources.json")
    value = json.loads(packaged.read_text(encoding="utf-8"))
    source = value["sources"]["iupac-thermoml-v4-use-cases"]
    source["artifact_url"] = "file:///unsafe.pdf"
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ThermoMLSourceError, match="HTTPS"):
        list_conformance_sources()

    source["artifact_url"] = "https://example.test/source.pdf"
    source["experimental_query_eligible"] = True
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ThermoMLSourceError, match="separate"):
        list_conformance_sources()


def test_conformance_field_validation() -> None:
    source = list_conformance_sources()[0]
    with pytest.raises(ThermoMLSourceError, match="positive"):
        conformance._validate(replace(source, size_bytes=0))
    with pytest.raises(ThermoMLSourceError, match="SHA-256"):
        conformance._validate(replace(source, sha256="bad"))
    with pytest.raises(ThermoMLSourceError, match="integer"):
        conformance._integer(True, field="count")
    with pytest.raises(ThermoMLSourceError, match="boolean"):
        conformance._boolean("false", field="included")
