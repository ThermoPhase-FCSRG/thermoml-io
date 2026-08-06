"""Metadata-only registry of external ThermoML conformance material."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from importlib.resources import files
from typing import Any, cast
from urllib.parse import urlparse

from .errors import ThermoMLSourceError

_RESOURCE = "data/conformance_sources.json"


@dataclass(frozen=True, slots=True)
class ConformanceSource:
    """External specification or example corpus, never an experimental source."""

    source_id: str
    title: str
    organization: str
    project_url: str
    publication_doi: str
    artifact_url: str
    media_type: str
    size_bytes: int
    sha256: str
    thermoml_version: str
    use_case_count: int
    purpose: str
    included_by_default: bool
    experimental_query_eligible: bool


def _registry_path() -> Any:
    return files("thermoml_io").joinpath(*_RESOURCE.split("/"))


def _validate(source: ConformanceSource) -> ConformanceSource:
    for field, url in (
        ("project_url", source.project_url),
        ("artifact_url", source.artifact_url),
    ):
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ThermoMLSourceError(f"{field} must be an absolute HTTPS URL.")
    if source.size_bytes <= 0 or source.use_case_count <= 0:
        raise ThermoMLSourceError("Conformance sizes and counts must be positive.")
    if re.fullmatch(r"[0-9a-f]{64}", source.sha256) is None:
        raise ThermoMLSourceError("Conformance-source SHA-256 is invalid.")
    if source.included_by_default or source.experimental_query_eligible:
        raise ThermoMLSourceError(
            "Conformance material must remain separate from experimental queries."
        )
    return source


def _integer(value: object, *, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ThermoMLSourceError(f"{field} must be an integer.")
    return value


def _boolean(value: object, *, field: str) -> bool:
    if not isinstance(value, bool):
        raise ThermoMLSourceError(f"{field} must be a boolean.")
    return value


def list_conformance_sources() -> tuple[ConformanceSource, ...]:
    """List registered external examples without downloading or redistributing them."""
    try:
        registry = json.loads(_registry_path().read_text(encoding="utf-8"))
        if registry["schema_version"] != 1:
            raise ThermoMLSourceError("Unsupported conformance registry schema.")
        mappings = cast(dict[str, dict[str, object]], registry["sources"])
        sources = tuple(
            _validate(
                ConformanceSource(
                    source_id=source_id,
                    title=str(value["title"]),
                    organization=str(value["organization"]),
                    project_url=str(value["project_url"]),
                    publication_doi=str(value["publication_doi"]),
                    artifact_url=str(value["artifact_url"]),
                    media_type=str(value["media_type"]),
                    size_bytes=_integer(value["size_bytes"], field="size_bytes"),
                    sha256=str(value["sha256"]),
                    thermoml_version=str(value["thermoml_version"]),
                    use_case_count=_integer(value["use_case_count"], field="use_case_count"),
                    purpose=str(value["purpose"]),
                    included_by_default=_boolean(
                        value["included_by_default"], field="included_by_default"
                    ),
                    experimental_query_eligible=_boolean(
                        value["experimental_query_eligible"],
                        field="experimental_query_eligible",
                    ),
                )
            )
            for source_id, value in mappings.items()
        )
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ThermoMLSourceError(f"Invalid conformance-source registry: {exc}") from exc
    return sources


def get_conformance_source(source_id: str) -> ConformanceSource:
    """Return one registered conformance source by stable package identifier."""
    for source in list_conformance_sources():
        if source.source_id == source_id:
            return source
    raise ThermoMLSourceError(f"Unknown ThermoML conformance source {source_id!r}.")
