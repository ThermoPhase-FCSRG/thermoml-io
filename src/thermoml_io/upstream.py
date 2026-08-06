"""Versioned upstream discovery and verified ThermoML archive downloads."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass
from importlib.resources import files
from pathlib import Path
from typing import Any, BinaryIO, cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from .errors import ThermoMLDownloadError, ThermoMLSourceError

_REGISTRY_RESOURCE = "data/archive_sources.json"
_CORDRA_RESOURCE = "data/cordra_snapshot.json"
_SNAPSHOT_DATE = re.compile(r"\.v(\d{4}-\d{2}-\d{2})\.")
_ARCHIVE_SUFFIXES = (".tgz", ".tar.gz")


@dataclass(frozen=True, slots=True)
class ArchiveSource:
    """Immutable description of one checksum-pinned upstream archive."""

    source_name: str
    metadata_url: str
    record_id: str
    record_version: str
    record_modified: str
    doi: str
    filename: str
    download_url: str
    media_type: str
    size_bytes: int
    sha256: str
    snapshot_date: str | None
    description: str


@dataclass(frozen=True, slots=True)
class CordraSnapshot:
    """Deterministic identity census of the live NIST ThermoML Cordra API."""

    api_url: str
    query: str
    object_type: str
    object_count: int
    identifiers_sha256: str
    first_identifier: str
    last_identifier: str


def _validate_https(url: str, *, field: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ThermoMLSourceError(f"{field} must be an absolute HTTPS URL.")


def _validate_source(source: ArchiveSource) -> ArchiveSource:
    _validate_https(source.metadata_url, field="metadata_url")
    _validate_https(source.download_url, field="download_url")
    if not source.filename.endswith(_ARCHIVE_SUFFIXES):
        raise ThermoMLSourceError("The configured archive is not tar-compatible.")
    if source.size_bytes <= 0:
        raise ThermoMLSourceError("Configured archive size must be positive.")
    if not re.fullmatch(r"[0-9a-f]{64}", source.sha256):
        raise ThermoMLSourceError("Configured archive SHA-256 is invalid.")
    return source


def _registry_path() -> Any:
    return files("thermoml_io").joinpath(*_REGISTRY_RESOURCE.split("/"))


def _cordra_path() -> Any:
    return files("thermoml_io").joinpath(*_CORDRA_RESOURCE.split("/"))


def _source_from_mapping(source_name: str, value: dict[str, Any]) -> ArchiveSource:
    archive = cast(dict[str, Any], value["archive"])
    return _validate_source(
        ArchiveSource(
            source_name=source_name,
            metadata_url=str(value["metadata_url"]),
            record_id=str(value["record_id"]),
            record_version=str(value["record_version"]),
            record_modified=str(value["record_modified"]),
            doi=str(value["doi"]),
            filename=str(archive["filename"]),
            download_url=str(archive["download_url"]),
            media_type=str(archive["media_type"]),
            size_bytes=int(archive["size_bytes"]),
            sha256=str(archive["sha256"]).casefold(),
            snapshot_date=(
                str(archive["snapshot_date"]) if archive.get("snapshot_date") is not None else None
            ),
            description=str(archive.get("description", "")),
        )
    )


def get_archive_source(source: str = "nist") -> ArchiveSource:
    """Load a checksum-pinned archive source shipped with the package."""
    try:
        registry = json.loads(_registry_path().read_text(encoding="utf-8"))
        if registry["schema_version"] != 1:
            raise ThermoMLSourceError("Unsupported archive-source registry schema.")
        value = registry["sources"][source]
    except KeyError as exc:
        raise ThermoMLSourceError(f"Unknown ThermoML archive source {source!r}.") from exc
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ThermoMLSourceError(f"Invalid archive-source registry: {exc}") from exc
    return _source_from_mapping(source, value)


def _validate_cordra_snapshot(snapshot: CordraSnapshot) -> CordraSnapshot:
    _validate_https(snapshot.api_url, field="api_url")
    if snapshot.object_count <= 0:
        raise ThermoMLSourceError("Cordra object count must be positive.")
    if not re.fullmatch(r"[0-9a-f]{64}", snapshot.identifiers_sha256):
        raise ThermoMLSourceError("Cordra identifier SHA-256 is invalid.")
    if not snapshot.first_identifier or not snapshot.last_identifier:
        raise ThermoMLSourceError("Cordra identifier bounds must not be empty.")
    return snapshot


def get_cordra_snapshot() -> CordraSnapshot:
    """Load the packaged identity census for the live NIST Cordra API."""
    try:
        registry = json.loads(_cordra_path().read_text(encoding="utf-8"))
        if registry["schema_version"] != 1:
            raise ThermoMLSourceError("Unsupported Cordra registry schema.")
        value = cast(dict[str, Any], registry["snapshot"])
        snapshot = CordraSnapshot(
            api_url=str(value["api_url"]),
            query=str(value["query"]),
            object_type=str(value["object_type"]),
            object_count=int(value["object_count"]),
            identifiers_sha256=str(value["identifiers_sha256"]).casefold(),
            first_identifier=str(value["first_identifier"]),
            last_identifier=str(value["last_identifier"]),
        )
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ThermoMLSourceError(f"Invalid Cordra snapshot registry: {exc}") from exc
    return _validate_cordra_snapshot(snapshot)


def _download_json(url: str, *, timeout: float) -> dict[str, Any]:
    _validate_https(url, field="metadata_url")
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "thermoml-io upstream discovery",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = response.read(10 * 1024 * 1024 + 1)
    except (HTTPError, URLError, OSError) as exc:
        raise ThermoMLDownloadError(f"Could not read NIST metadata: {exc}") from exc
    if len(payload) > 10 * 1024 * 1024:
        raise ThermoMLDownloadError("NIST metadata exceeded the 10 MiB safety limit.")
    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ThermoMLSourceError("NIST metadata is not valid JSON.") from exc
    if not isinstance(value, dict):
        raise ThermoMLSourceError("NIST metadata root must be an object.")
    return cast(dict[str, Any], value)


def discover_archive_source(source: str = "nist", *, timeout: float = 30.0) -> ArchiveSource:
    """Discover the newest tar-compatible ThermoML snapshot in NIST NERDm."""
    configured = get_archive_source(source)
    metadata = _download_json(configured.metadata_url, timeout=timeout)
    candidates: list[tuple[str, dict[str, Any]]] = []
    for raw_component in metadata.get("components", []):
        if not isinstance(raw_component, dict):
            continue
        component = cast(dict[str, Any], raw_component)
        filename = component.get("filepath")
        if not isinstance(filename, str) or not filename.endswith(_ARCHIVE_SUFFIXES):
            continue
        match = _SNAPSHOT_DATE.search(filename)
        candidates.append((match.group(1) if match else "", component))
    if not candidates:
        raise ThermoMLSourceError("NIST metadata contains no tar-compatible archive.")
    _, selected = max(candidates, key=lambda item: (item[0], str(item[1]["filepath"])))
    checksum = selected.get("checksum")
    if not isinstance(checksum, dict):
        raise ThermoMLSourceError("Selected NIST archive has no checksum metadata.")
    algorithm = checksum.get("algorithm")
    tag = algorithm.get("tag") if isinstance(algorithm, dict) else None
    if str(tag).casefold() != "sha256":
        raise ThermoMLSourceError("Selected NIST archive has no SHA-256 checksum.")
    filename = str(selected["filepath"])
    match = _SNAPSHOT_DATE.search(filename)
    return _validate_source(
        ArchiveSource(
            source_name=source,
            metadata_url=configured.metadata_url,
            record_id=str(metadata.get("ediid", configured.record_id)),
            record_version=str(metadata.get("version", "")),
            record_modified=str(metadata.get("modified", "")),
            doi=str(metadata.get("doi", configured.doi)),
            filename=filename,
            download_url=str(selected["downloadURL"]),
            media_type=str(selected.get("mediaType", "application/octet-stream")),
            size_bytes=int(selected["size"]),
            sha256=str(checksum["hash"]).casefold(),
            snapshot_date=match.group(1) if match else None,
            description=str(selected.get("description", "")).strip(),
        )
    )


def discover_cordra_snapshot(*, timeout: float = 180.0) -> CordraSnapshot:
    """Census all live Cordra ThermoML IDs independently of the bulk archive.

    The Cordra API intentionally exposes metadata and data-point counts, not
    the numerical observations. This census detects additions or removals even
    when the checksum-pinned NERDm ``.tgz`` snapshot has not changed.
    """
    configured = get_cordra_snapshot()
    parameters = urlencode({"query": configured.query})
    payload = _download_json(f"{configured.api_url}?{parameters}&ids", timeout=timeout)
    results = payload.get("results")
    reported_size = payload.get("size")
    if not isinstance(results, list) or any(not isinstance(item, str) for item in results):
        raise ThermoMLSourceError("Cordra ID response must contain a string results list.")
    identifiers = sorted(cast(list[str], results))
    if len(set(identifiers)) != len(identifiers):
        raise ThermoMLSourceError("Cordra ID response contains duplicate identifiers.")
    if not isinstance(reported_size, int) or reported_size != len(identifiers):
        raise ThermoMLSourceError(
            "Cordra ID response is incomplete: reported size does not match results."
        )
    if not identifiers:
        raise ThermoMLSourceError("Cordra ID response contains no identifiers.")
    digest = hashlib.sha256(("\n".join(identifiers) + "\n").encode("utf-8")).hexdigest()
    return _validate_cordra_snapshot(
        CordraSnapshot(
            api_url=configured.api_url,
            query=configured.query,
            object_type=configured.object_type,
            object_count=len(identifiers),
            identifiers_sha256=digest,
            first_identifier=identifiers[0],
            last_identifier=identifiers[-1],
        )
    )


def default_cache_dir() -> Path:
    """Return the platform-neutral user cache directory for archive bytes."""
    explicit = os.environ.get("THERMOML_IO_CACHE")
    if explicit:
        return Path(explicit).expanduser()
    xdg = os.environ.get("XDG_CACHE_HOME")
    if xdg:
        return Path(xdg).expanduser() / "thermoml-io"
    return Path.home() / ".cache" / "thermoml-io"


def _sha256_and_size(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _verified(path: Path, source: ArchiveSource) -> bool:
    if not path.is_file() or path.stat().st_size != source.size_bytes:
        return False
    digest, size = _sha256_and_size(path)
    return size == source.size_bytes and digest == source.sha256


def _stream_archive(
    source: ArchiveSource,
    stream: BinaryIO,
    *,
    timeout: float,
) -> tuple[str, int]:
    request = Request(
        source.download_url,
        headers={"User-Agent": "thermoml-io verified archive fetch"},
    )
    digest = hashlib.sha256()
    size = 0
    try:
        with urlopen(request, timeout=timeout) as response:
            while chunk := response.read(1024 * 1024):
                size += len(chunk)
                if size > source.size_bytes:
                    raise ThermoMLDownloadError("Downloaded archive exceeded the registered size.")
                digest.update(chunk)
                stream.write(chunk)
    except ThermoMLDownloadError:
        raise
    except (HTTPError, URLError, OSError) as exc:
        raise ThermoMLDownloadError(f"Could not download ThermoML archive: {exc}") from exc
    return digest.hexdigest(), size


def fetch_thermoml_archive(
    *,
    cache_dir: str | Path | None = None,
    source: str = "nist",
    force: bool = False,
    timeout: float = 120.0,
) -> Path:
    """Return a locally cached, size- and SHA-256-verified archive.

    No URL, filename, or checksum is required from the caller. A temporary
    sibling file is downloaded and verified before atomically replacing an
    invalid or explicitly refreshed cache entry.
    """
    selected = get_archive_source(source)
    directory = Path(cache_dir) if cache_dir is not None else default_cache_dir()
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / selected.filename
    if not force and _verified(destination, selected):
        return destination
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w+b", prefix=f".{selected.filename}.", dir=directory, delete=False
        ) as stream:
            temporary = Path(stream.name)
            digest, size = _stream_archive(selected, cast(BinaryIO, stream), timeout=timeout)
        if size != selected.size_bytes or digest != selected.sha256:
            raise ThermoMLDownloadError(
                "Downloaded archive failed the registered size or SHA-256 check."
            )
        temporary.replace(destination)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    return destination


def archive_source_record(source: ArchiveSource) -> dict[str, Any]:
    """Return the deterministic registry representation used by maintenance CI."""
    value = asdict(source)
    source_name = str(value.pop("source_name"))
    archive_keys = (
        "filename",
        "download_url",
        "media_type",
        "size_bytes",
        "sha256",
        "snapshot_date",
        "description",
    )
    archive = {key: value.pop(key) for key in archive_keys}
    return {"schema_version": 1, "sources": {source_name: {**value, "archive": archive}}}


def cordra_snapshot_record(snapshot: CordraSnapshot) -> dict[str, Any]:
    """Return the deterministic registry representation used by monthly CI."""
    return {"schema_version": 1, "snapshot": asdict(snapshot)}
