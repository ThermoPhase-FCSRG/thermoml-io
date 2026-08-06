"""Tests for versioned NIST discovery and verified archive fetching."""

from __future__ import annotations

import hashlib
import io
import json
from dataclasses import replace
from pathlib import Path
from urllib.error import URLError

import pytest

import thermoml_io.upstream as upstream
from thermoml_io import (
    ArchiveSource,
    CordraSnapshot,
    ThermoMLDownloadError,
    ThermoMLSourceError,
    archive_source_record,
    cordra_snapshot_record,
    default_cache_dir,
    discover_archive_source,
    discover_cordra_snapshot,
    fetch_thermoml_archive,
    get_archive_source,
    get_cordra_snapshot,
)


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


def _source(content: bytes = b"synthetic archive") -> ArchiveSource:
    return ArchiveSource(
        source_name="nist",
        metadata_url="https://example.test/metadata",
        record_id="mds2-test",
        record_version="1.0",
        record_modified="2026-01-01",
        doi="10.0000/example",
        filename="ThermoML.v2026-01-01.tgz",
        download_url="https://example.test/archive.tgz",
        media_type="application/gzip",
        size_bytes=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        snapshot_date="2026-01-01",
        description="Synthetic archive",
    )


def _metadata(*components: dict[str, object]) -> bytes:
    return json.dumps(
        {
            "ediid": "ark:/88434/mds2-test",
            "version": "2.0",
            "modified": "2026-02-01",
            "doi": "doi:10.0000/example",
            "components": list(components),
        }
    ).encode()


def _component(
    filename: str = "ThermoML.v2026-02-01.tgz",
    *,
    checksum: object | None = None,
) -> dict[str, object]:
    return {
        "filepath": filename,
        "downloadURL": f"https://example.test/{filename}",
        "mediaType": "application/gzip",
        "size": 123,
        "checksum": checksum
        or {
            "hash": "a" * 64,
            "algorithm": {"tag": "sha256", "@type": "Thing"},
        },
        "description": "Newest snapshot",
    }


def test_packaged_registry_and_deterministic_record() -> None:
    source = get_archive_source()
    assert source.filename == "ThermoML.v2020-09-30.tgz"
    assert source.size_bytes == 189433115
    assert len(source.sha256) == 64
    record = archive_source_record(source)
    assert record["schema_version"] == 1
    assert record["sources"]["nist"]["archive"]["sha256"] == source.sha256
    with pytest.raises(ThermoMLSourceError, match="Unknown"):
        get_archive_source("unknown")

    cordra = get_cordra_snapshot()
    assert cordra.object_count == 11922
    assert len(cordra.identifiers_sha256) == 64
    assert cordra_snapshot_record(cordra)["snapshot"]["query"] == "type:TRCTml4"


def test_cordra_discovery_hashes_complete_sorted_identifier_census(monkeypatch) -> None:
    configured = CordraSnapshot(
        api_url="https://example.test/objects",
        query="type:TRCTml4",
        object_type="TRCTml4",
        object_count=1,
        identifiers_sha256="a" * 64,
        first_identifier="old",
        last_identifier="old",
    )
    payload = json.dumps({"size": 2, "results": ["trc/z", "trc/a"]}).encode()
    monkeypatch.setattr(upstream, "get_cordra_snapshot", lambda: configured)
    monkeypatch.setattr(upstream, "urlopen", lambda *_args, **_kwargs: _Response(payload))
    discovered = discover_cordra_snapshot(timeout=1)
    expected = hashlib.sha256(b"trc/a\ntrc/z\n").hexdigest()
    assert discovered.object_count == 2
    assert discovered.identifiers_sha256 == expected
    assert discovered.first_identifier == "trc/a"
    assert discovered.last_identifier == "trc/z"


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"size": 1, "results": [1]}, "string results"),
        ({"size": 2, "results": ["same", "same"]}, "duplicate"),
        ({"size": 2, "results": ["one"]}, "incomplete"),
        ({"size": 0, "results": []}, "no identifiers"),
    ],
)
def test_cordra_discovery_rejects_incomplete_census(
    payload: dict[str, object], message: str, monkeypatch
) -> None:
    configured = CordraSnapshot(
        api_url="https://example.test/objects",
        query="type:TRCTml4",
        object_type="TRCTml4",
        object_count=1,
        identifiers_sha256="a" * 64,
        first_identifier="old",
        last_identifier="old",
    )
    monkeypatch.setattr(upstream, "get_cordra_snapshot", lambda: configured)
    monkeypatch.setattr(
        upstream,
        "urlopen",
        lambda *_args, **_kwargs: _Response(json.dumps(payload).encode()),
    )
    with pytest.raises(ThermoMLSourceError, match=message):
        discover_cordra_snapshot()


def test_registry_validation_errors(tmp_path: Path, monkeypatch) -> None:
    registry = tmp_path / "registry.json"
    monkeypatch.setattr(upstream, "_registry_path", lambda: registry)

    registry.write_text('{"schema_version": 2, "sources": {}}')
    with pytest.raises(ThermoMLSourceError, match="schema"):
        get_archive_source()

    registry.write_text("not-json")
    with pytest.raises(ThermoMLSourceError, match="Invalid"):
        get_archive_source()

    value = archive_source_record(_source())
    value["sources"]["nist"]["archive"]["download_url"] = "file:///unsafe"
    registry.write_text(json.dumps(value))
    with pytest.raises(ThermoMLSourceError, match="HTTPS"):
        get_archive_source()

    with pytest.raises(ThermoMLSourceError, match="tar-compatible"):
        upstream._validate_source(replace(_source(), filename="archive.zip"))
    with pytest.raises(ThermoMLSourceError, match="positive"):
        upstream._validate_source(replace(_source(), size_bytes=0))
    with pytest.raises(ThermoMLSourceError, match="SHA-256"):
        upstream._validate_source(replace(_source(), sha256="invalid"))


def test_cordra_registry_validation_errors(tmp_path: Path, monkeypatch) -> None:
    snapshot = get_cordra_snapshot()
    with pytest.raises(ThermoMLSourceError, match="positive"):
        upstream._validate_cordra_snapshot(replace(snapshot, object_count=0))
    with pytest.raises(ThermoMLSourceError, match="SHA-256"):
        upstream._validate_cordra_snapshot(replace(snapshot, identifiers_sha256="invalid"))
    with pytest.raises(ThermoMLSourceError, match="bounds"):
        upstream._validate_cordra_snapshot(replace(snapshot, first_identifier=""))

    registry = tmp_path / "cordra.json"
    monkeypatch.setattr(upstream, "_cordra_path", lambda: registry)
    registry.write_text('{"schema_version":2}', encoding="utf-8")
    with pytest.raises(ThermoMLSourceError, match="schema"):
        get_cordra_snapshot()
    registry.write_text("not-json", encoding="utf-8")
    with pytest.raises(ThermoMLSourceError, match="Invalid"):
        get_cordra_snapshot()


def test_discover_selects_newest_snapshot(monkeypatch) -> None:
    configured = _source()
    payload = _metadata(
        _component("ThermoML.v2025-01-01.tgz"),
        {"filepath": "ignored.json"},
        _component("ThermoML.v2026-02-01.tgz"),
    )
    monkeypatch.setattr(upstream, "get_archive_source", lambda _source="nist": configured)
    monkeypatch.setattr(upstream, "urlopen", lambda *_args, **_kwargs: _Response(payload))
    discovered = discover_archive_source(timeout=1)
    assert discovered.filename == "ThermoML.v2026-02-01.tgz"
    assert discovered.snapshot_date == "2026-02-01"
    assert discovered.record_version == "2.0"

    payload_without_date = _metadata("ignored component", _component("ThermoML.current.tgz"))
    monkeypatch.setattr(
        upstream,
        "urlopen",
        lambda *_args, **_kwargs: _Response(payload_without_date),
    )
    assert discover_archive_source().snapshot_date is None


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (_metadata({"filepath": "only.json"}), "no tar-compatible"),
        (_metadata(_component(checksum="missing")), "checksum"),
        (
            _metadata(
                _component(
                    checksum={
                        "hash": "a" * 64,
                        "algorithm": {"tag": "md5"},
                    }
                )
            ),
            "SHA-256",
        ),
    ],
)
def test_discovery_rejects_incomplete_metadata(payload: bytes, message: str, monkeypatch) -> None:
    configured = _source()
    monkeypatch.setattr(upstream, "get_archive_source", lambda _source_name="nist": configured)
    monkeypatch.setattr(upstream, "urlopen", lambda *_args, **_kwargs: _Response(payload))
    with pytest.raises(ThermoMLSourceError, match=message):
        discover_archive_source()


def test_metadata_download_failures(monkeypatch) -> None:
    configured = _source()
    monkeypatch.setattr(upstream, "get_archive_source", lambda _source_name="nist": configured)
    monkeypatch.setattr(upstream, "urlopen", lambda *_args, **_kwargs: _Response(b"{"))
    with pytest.raises(ThermoMLSourceError, match="valid JSON"):
        discover_archive_source()

    monkeypatch.setattr(upstream, "urlopen", lambda *_args, **_kwargs: _Response(b"[]"))
    with pytest.raises(ThermoMLSourceError, match="root"):
        discover_archive_source()

    monkeypatch.setattr(
        upstream,
        "urlopen",
        lambda *_args, **_kwargs: _Response(b"x" * (10 * 1024 * 1024 + 1)),
    )
    with pytest.raises(ThermoMLDownloadError, match="10 MiB"):
        discover_archive_source()

    def unavailable(*_args, **_kwargs):
        raise URLError("offline")

    monkeypatch.setattr(upstream, "urlopen", unavailable)
    with pytest.raises(ThermoMLDownloadError, match="metadata"):
        discover_archive_source()


def test_default_cache_directory_precedence(tmp_path: Path, monkeypatch) -> None:
    explicit = tmp_path / "explicit"
    monkeypatch.setenv("THERMOML_IO_CACHE", str(explicit))
    assert default_cache_dir() == explicit
    monkeypatch.delenv("THERMOML_IO_CACHE")
    xdg = tmp_path / "xdg"
    monkeypatch.setenv("XDG_CACHE_HOME", str(xdg))
    assert default_cache_dir() == xdg / "thermoml-io"
    monkeypatch.delenv("XDG_CACHE_HOME")
    monkeypatch.setattr(upstream.Path, "home", classmethod(lambda _cls: tmp_path))
    assert default_cache_dir() == tmp_path / ".cache/thermoml-io"


def test_fetch_reuses_and_atomically_refreshes_verified_cache(tmp_path: Path, monkeypatch) -> None:
    content = b"synthetic archive"
    source = _source(content)
    monkeypatch.setattr(upstream, "get_archive_source", lambda _source="nist": source)
    destination = tmp_path / source.filename
    destination.write_bytes(content)

    def should_not_download(*_args, **_kwargs):
        raise AssertionError("verified cache should be reused")

    monkeypatch.setattr(upstream, "urlopen", should_not_download)
    assert fetch_thermoml_archive(cache_dir=tmp_path) == destination

    monkeypatch.setattr(upstream, "urlopen", lambda *_args, **_kwargs: _Response(content))
    assert fetch_thermoml_archive(cache_dir=tmp_path, force=True) == destination
    assert destination.read_bytes() == content
    assert not tuple(tmp_path.glob(f".{source.filename}.*"))


def test_fetch_rejects_corrupt_or_oversized_download(tmp_path: Path, monkeypatch) -> None:
    content = b"synthetic archive"
    source = _source(content)
    monkeypatch.setattr(upstream, "get_archive_source", lambda _source="nist": source)

    monkeypatch.setattr(upstream, "urlopen", lambda *_args, **_kwargs: _Response(b"corrupt"))
    with pytest.raises(ThermoMLDownloadError, match="failed"):
        fetch_thermoml_archive(cache_dir=tmp_path)

    monkeypatch.setattr(
        upstream, "urlopen", lambda *_args, **_kwargs: _Response(content + b"extra")
    )
    with pytest.raises(ThermoMLDownloadError, match="exceeded"):
        fetch_thermoml_archive(cache_dir=tmp_path)

    def unavailable(*_args, **_kwargs):
        raise URLError("offline")

    monkeypatch.setattr(upstream, "urlopen", unavailable)
    with pytest.raises(ThermoMLDownloadError, match="archive"):
        fetch_thermoml_archive(cache_dir=tmp_path)
    assert not tuple(tmp_path.glob(f".{source.filename}.*"))


def test_fetch_uses_default_cache(tmp_path: Path, monkeypatch) -> None:
    content = b"synthetic archive"
    source = _source(content)
    monkeypatch.setattr(upstream, "get_archive_source", lambda _name="nist": source)
    monkeypatch.setattr(upstream, "default_cache_dir", lambda: tmp_path)
    monkeypatch.setattr(upstream, "urlopen", lambda *_args, **_kwargs: _Response(content))
    assert fetch_thermoml_archive() == tmp_path / source.filename
