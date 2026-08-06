"""Incremental analysis of local bulk ThermoML ``.tar``/``.tgz`` archives."""

from __future__ import annotations

import hashlib
import tarfile
from collections import Counter, defaultdict
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .analysis import CollectionSummary, RankedCount, _SummaryAccumulator
from .bibliography import publication_citation
from .classification import classify_property, normalize_term
from .collection import ComponentMatch, ThermoMLCollection
from .errors import ThermoMLArchiveError, ThermoMLError, ThermoMLParseError
from .identity import (
    ComponentIdentity,
    ComponentIndex,
    ComponentQuery,
    component_query_label,
    explicit_component_identity,
)
from .models import DataSet, SourceRecovery, ThermoMLDocument
from .parser import parse_thermoml, parse_thermoml_json
from .table import (
    Cell,
    ExperimentalTable,
    TableFormat,
    build_analysis_table,
    build_property_table,
)
from .upstream import fetch_thermoml_archive

JsonFallback = Literal["never", "on_xml_error"]


@dataclass(frozen=True, slots=True)
class RankedDataset:
    """Lightweight description of one dense experimental dataset."""

    doi: str | None
    citation_title: str | None
    dataset_number: int
    system: str
    system_type: str
    observation_count: int
    data_types: tuple[str, ...]
    source_locator: str | None


@dataclass(frozen=True, slots=True)
class ArchiveParseFailure:
    """Explicit record of one archive member that could not be decoded."""

    member_name: str
    source_locator: str
    error_type: str
    message: str


@dataclass(frozen=True, slots=True)
class ArchiveRecovery:
    """One XML member recovered from its paired official NIST JSON member."""

    xml_member_name: str
    json_member_name: str
    xml_sha256: str
    json_sha256: str
    error_type: str
    error_message: str
    lexical_numeric_representation_preserved: bool = False


@dataclass(frozen=True, slots=True)
class ArchiveComponentIndex:
    """Component identities discovered during one complete archive scan."""

    archive_path: str
    xml_document_count: int
    parsed_document_count: int
    index: ComponentIndex
    failures: tuple[ArchiveParseFailure, ...]
    recoveries: tuple[ArchiveRecovery, ...]

    @property
    def identities(self) -> tuple[ComponentIdentity, ...]:
        """Return resolved archive-wide component identities."""
        return self.index.identities

    def resolve_component(self, query: ComponentQuery) -> ComponentIdentity:
        """Resolve one friendly or namespaced query against this snapshot."""
        return self.index.resolve(query)


@dataclass(frozen=True, slots=True)
class ArchiveAnalysis:
    """Streaming summary and dense-dataset ranking for a bulk archive."""

    archive_path: str
    xml_document_count: int
    parsed_document_count: int
    matched_document_count: int
    component_query: str | None
    resolved_component: ComponentIdentity | None
    serialized_prefilter: str | None
    summary: CollectionSummary
    top_datasets: tuple[RankedDataset, ...]
    failures: tuple[ArchiveParseFailure, ...]
    recoveries: tuple[ArchiveRecovery, ...]


@dataclass(frozen=True, slots=True)
class CatalogEntry:
    """One observed category/property/independent-variable combination."""

    data_category: str
    property_name: str
    independent_variable: str | None
    relationship_count: int
    dataset_count: int
    publication_count: int


@dataclass(frozen=True, slots=True)
class ArchiveCatalog:
    """Catalog of queryable property relationships in an archive snapshot."""

    archive_path: str
    xml_document_count: int
    parsed_document_count: int
    entries: tuple[CatalogEntry, ...]
    component_identities: tuple[ComponentIdentity, ...]
    failures: tuple[ArchiveParseFailure, ...]
    recoveries: tuple[ArchiveRecovery, ...]

    @property
    def component_index(self) -> ComponentIndex:
        """Return the component index collected during the catalog scan."""
        return ComponentIndex(self.component_identities)

    def resolve_component(self, query: ComponentQuery) -> ComponentIdentity:
        """Resolve one component without rescanning the archive."""
        return self.component_index.resolve(query)

    def categories(self) -> tuple[RankedCount, ...]:
        """Rank package data categories by property-variable relationships."""
        counts: Counter[str] = Counter()
        for entry in self.entries:
            counts[entry.data_category] += entry.relationship_count
        return tuple(
            RankedCount(label, count)
            for label, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        )

    def properties(self, data_category: str) -> tuple[RankedCount, ...]:
        """List exact reported properties available within a category."""
        normalized = normalize_term(data_category)
        counts: Counter[str] = Counter()
        for entry in self.entries:
            if normalize_term(entry.data_category) == normalized:
                counts[entry.property_name] += entry.relationship_count
        return tuple(
            RankedCount(label, count)
            for label, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        )

    def independent_variables(
        self, data_category: str, property_name: str
    ) -> tuple[RankedCount, ...]:
        """List independent variables for a category and property substring."""
        normalized_category = normalize_term(data_category)
        normalized_property = normalize_term(property_name)
        counts: Counter[str] = Counter()
        for entry in self.entries:
            variable = entry.independent_variable
            if (
                variable is not None
                and normalize_term(entry.data_category) == normalized_category
                and normalized_property in normalize_term(entry.property_name)
            ):
                counts[variable] += entry.relationship_count
        return tuple(
            RankedCount(label, count)
            for label, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        )


@dataclass(frozen=True, slots=True)
class PublicationRank:
    """A publication ranked by returned property-variable relationships."""

    publication_key: str
    doi: str | None
    title: str | None
    year: int | None
    authors_year: str
    citation_apa: str
    citation_bibtex: str
    relationship_count: int


@dataclass(frozen=True, slots=True)
class ArchiveQueryResult:
    """Property relationships and publication ranking from a complete scan."""

    archive_path: str
    components: tuple[str, ...]
    required_components: tuple[str, ...]
    resolved_components: tuple[ComponentIdentity, ...]
    resolved_required_components: tuple[ComponentIdentity, ...]
    component_match: ComponentMatch
    data_category: str | None
    property_name: str | None
    independent_variable: str
    xml_document_count: int
    parsed_document_count: int
    available_publication_count: int
    matched_dataset_count: int
    publications: tuple[PublicationRank, ...]
    table: ExperimentalTable
    failures: tuple[ArchiveParseFailure, ...]
    recoveries: tuple[ArchiveRecovery, ...]

    @property
    def analysis_table(self) -> ExperimentalTable:
        """Return one analysis-ready row per reported property observation."""
        return build_analysis_table(self.table)

    def write(
        self,
        path: str | Path,
        *,
        format: TableFormat | None = None,
        layout: Literal["analysis", "lossless"] = "analysis",
    ) -> Path:
        """Write an analysis-ready result, or explicitly request lossless layout.

        The default layout promotes physical quantities to ordinary columns
        named with their ThermoML-reported units. ``layout="lossless"`` writes
        the complete internal representation with structured JSON columns.
        """
        if layout == "analysis":
            selected = self.analysis_table
        elif layout == "lossless":
            selected = self.table
        else:
            raise ValueError("layout must be 'analysis' or 'lossless'.")
        return selected.write(path, format=format)

    def write_csv(self, path: str | Path) -> Path:
        """Write this query as an analysis-ready CSV file."""
        return self.write(path, format="csv")

    def write_json(self, path: str | Path) -> Path:
        """Write this query as an analysis-ready JSON table."""
        return self.write(path, format="json")

    def write_yaml(self, path: str | Path) -> Path:
        """Write this query as an analysis-ready YAML table."""
        return self.write(path, format="yaml")

    def write_parquet(self, path: str | Path) -> Path:
        """Write this query as an analysis-ready Parquet table."""
        return self.write(path, format="parquet")

    def write_lossless(self, path: str | Path, *, format: TableFormat | None = None) -> Path:
        """Write the complete provenance-oriented internal table explicitly."""
        return self.write(path, format=format, layout="lossless")


def _archive_xml_members(
    archive_path: Path,
) -> Iterator[tuple[str, bytes]]:
    try:
        with tarfile.open(archive_path, mode="r:*") as archive:
            for member in archive:
                if not member.isfile() or not member.name.casefold().endswith(".xml"):
                    continue
                stream = archive.extractfile(member)
                if stream is None:  # pragma: no cover - defensive tarfile behavior
                    raise ThermoMLArchiveError(
                        f"Could not read XML member {member.name!r} from {archive_path}."
                    )
                yield member.name, stream.read()
    except (OSError, tarfile.TarError) as exc:
        raise ThermoMLArchiveError(
            f"Could not read ThermoML archive {archive_path}: {exc}"
        ) from exc


def _paired_json_member(archive_path: Path, xml_member_name: str) -> tuple[str, bytes] | None:
    json_member_name = f"{xml_member_name[:-4]}.json"
    try:
        with tarfile.open(archive_path, mode="r:*") as archive:
            try:
                member = archive.getmember(json_member_name)
            except KeyError:
                return None
            if not member.isfile():
                return None
            stream = archive.extractfile(member)
            if stream is None:  # pragma: no cover - defensive tarfile behavior
                return None
            return json_member_name, stream.read()
    except (OSError, tarfile.TarError) as exc:
        raise ThermoMLArchiveError(
            f"Could not read paired JSON member from {archive_path}: {exc}"
        ) from exc


def _validate_json_fallback(value: JsonFallback) -> None:
    if value not in {"never", "on_xml_error"}:
        raise ValueError("json_fallback must be 'never' or 'on_xml_error'.")


def _parse_archive_document(
    path: Path,
    member_name: str,
    raw: bytes,
    *,
    json_fallback: JsonFallback,
) -> tuple[ThermoMLDocument, ArchiveRecovery | None]:
    locator = f"{path.resolve()}!{member_name}"
    try:
        return parse_thermoml(raw, source_label=locator), None
    except ThermoMLParseError as xml_error:
        if json_fallback == "never":
            raise
        paired = _paired_json_member(path, member_name)
        if paired is None:
            raise
        json_member_name, json_raw = paired
        json_locator = f"{path.resolve()}!{json_member_name}"
        recovery = SourceRecovery(
            strategy="paired-nist-json",
            failed_locator=locator,
            failed_sha256=hashlib.sha256(raw).hexdigest(),
            failed_media_type="application/xml",
            failure_type=type(xml_error).__name__,
            failure_message=str(xml_error),
        )
        try:
            document = parse_thermoml_json(
                json_raw,
                source_label=json_locator,
                recovery=recovery,
            )
            xml_md5 = hashlib.md5(raw, usedforsecurity=False).hexdigest()
            if document.provenance.related_xml_md5 != xml_md5:
                raise ThermoMLParseError(
                    "Paired official JSON does not report the MD5 checksum of the failed XML bytes."
                )
        except ThermoMLError as json_error:
            raise ThermoMLParseError(
                f"XML failed ({xml_error}); paired official JSON also failed ({json_error})."
            ) from json_error
        return document, ArchiveRecovery(
            xml_member_name=member_name,
            json_member_name=json_member_name,
            xml_sha256=recovery.failed_sha256,
            json_sha256=document.provenance.sha256,
            error_type=recovery.failure_type,
            error_message=recovery.failure_message,
        )


def iter_thermoml_archive(
    archive_path: str | Path,
    *,
    serialized_prefilter: str | bytes | None = None,
    json_fallback: JsonFallback = "on_xml_error",
) -> Iterator[ThermoMLDocument]:
    """Yield ThermoML documents from a local bulk archive.

    Parameters
    ----------
    archive_path:
        Local tar-compatible archive. Members are read in archive order and are
        never extracted to the filesystem.
    serialized_prefilter:
        Optional exact byte sequence that must occur in a serialized XML member
        before parsing. This is only a performance prefilter; callers must still
        apply semantic component/system matching to the parsed document.

    Yields
    ------
    ThermoMLDocument
        One provenance-labelled document at a time.

    Notes
    -----
    Bulk archive bytes remain subject to their source terms. This function does
    not persist, redistribute, or silently skip malformed matching documents.
    """
    _validate_json_fallback(json_fallback)
    path = Path(archive_path)
    needle = (
        serialized_prefilter.encode("utf-8")
        if isinstance(serialized_prefilter, str)
        else serialized_prefilter
    )
    for member_name, raw in _archive_xml_members(path):
        if needle is not None and needle not in raw:
            continue
        try:
            document, _ = _parse_archive_document(
                path, member_name, raw, json_fallback=json_fallback
            )
            yield document
        except ThermoMLError as exc:
            raise ThermoMLArchiveError(
                f"Failed to parse archive member {member_name!r}: {exc}"
            ) from exc


def _component_datasets(
    document: ThermoMLDocument,
    component_query: ComponentIdentity,
) -> tuple[DataSet, ...]:
    return tuple(
        dataset
        for dataset in document.datasets
        if any(
            component_query.matches(ComponentIdentity.from_compound(compound))
            for compound in document.system_compounds(dataset)
        )
    )


def _ranked_dataset(
    document: ThermoMLDocument,
    dataset: DataSet,
) -> RankedDataset:
    return RankedDataset(
        doi=document.citation.normalized_doi,
        citation_title=document.citation.title,
        dataset_number=dataset.number,
        system=" + ".join(
            sorted(compound.preferred_name for compound in document.system_compounds(dataset))
        ),
        system_type=dataset.system_type,
        observation_count=dataset.observation_count,
        data_types=tuple(
            dict.fromkeys(
                classify_property(definition, dataset) for definition in dataset.properties
            )
        ),
        source_locator=document.provenance.locator,
    )


def analyze_thermoml_archive(
    archive_path: str | Path,
    *,
    component: ComponentQuery | None = None,
    component_index: ComponentIndex | ArchiveComponentIndex | None = None,
    serialized_prefilter: str | bytes | None = None,
    top_datasets: int = 10,
    on_error: Literal["raise", "collect"] = "raise",
    json_fallback: JsonFallback = "on_xml_error",
) -> ArchiveAnalysis:
    """Analyze an entire ThermoML archive with bounded aggregate memory.

    ``component`` includes every pure or mixture dataset matching an
    archive-resolved identity. Friendly strings are resolved in a preliminary
    complete scan unless a reusable ``component_index`` is supplied. A
    :class:`ComponentIdentity` returned by an explicit resolver avoids that
    scan. ``serialized_prefilter`` can accelerate stable-identifier queries,
    but semantic matching remains the deciding filter. Dataset truncation
    occurs only after the complete archive has been scanned and ranked.
    ``on_error="collect"`` records every known ThermoML decoding failure in the
    result; the default strict mode raises at the first failure.
    """
    if top_datasets < 0:
        raise ValueError("top_datasets must be non-negative.")
    if on_error not in {"raise", "collect"}:
        raise ValueError("on_error must be 'raise' or 'collect'.")
    _validate_json_fallback(json_fallback)
    path = Path(archive_path)
    resolved_component: ComponentIdentity | None = None
    if component is not None:
        if isinstance(component, ComponentIdentity):
            resolved_component = component
        else:
            reusable_index = (
                component_index.index
                if isinstance(component_index, ArchiveComponentIndex)
                else component_index
            )
            resolved_component = (
                reusable_index.resolve(component)
                if reusable_index is not None
                else explicit_component_identity(component)
            )
            if resolved_component is None:
                if reusable_index is None:
                    reusable_index = index_thermoml_archive(
                        path, on_error=on_error, json_fallback=json_fallback
                    ).index
                resolved_component = reusable_index.resolve(component)
    needle = (
        serialized_prefilter.encode("utf-8")
        if isinstance(serialized_prefilter, str)
        else serialized_prefilter
    )
    accumulator = _SummaryAccumulator.create()
    candidates: list[RankedDataset] = []
    xml_document_count = 0
    parsed_document_count = 0
    matched_document_count = 0
    failures: list[ArchiveParseFailure] = []
    recoveries: list[ArchiveRecovery] = []

    for member_name, raw in _archive_xml_members(path):
        xml_document_count += 1
        if needle is not None and needle not in raw:
            continue
        try:
            document, recovery = _parse_archive_document(
                path, member_name, raw, json_fallback=json_fallback
            )
        except ThermoMLError as exc:
            if on_error == "raise":
                raise ThermoMLArchiveError(
                    f"Failed to parse archive member {member_name!r}: {exc}"
                ) from exc
            failures.append(
                ArchiveParseFailure(
                    member_name=member_name,
                    source_locator=f"{path.resolve()}!{member_name}",
                    error_type=type(exc).__name__,
                    message=str(exc),
                )
            )
            continue
        if recovery is not None:
            recoveries.append(recovery)
        parsed_document_count += 1
        datasets = (
            document.datasets
            if resolved_component is None
            else _component_datasets(document, resolved_component)
        )
        if not datasets and component is not None:
            continue
        matched_document_count += 1
        accumulator.add_document(
            document,
            datasets,
            include_reactions=component is None,
        )
        candidates.extend(_ranked_dataset(document, dataset) for dataset in datasets)

    candidates.sort(
        key=lambda item: (
            -item.observation_count,
            item.doi or item.source_locator or "",
            item.dataset_number,
        )
    )
    selected = candidates[:top_datasets] if top_datasets else []
    return ArchiveAnalysis(
        archive_path=str(path),
        xml_document_count=xml_document_count,
        parsed_document_count=parsed_document_count,
        matched_document_count=matched_document_count,
        component_query=(component_query_label(component) if component is not None else None),
        resolved_component=resolved_component,
        serialized_prefilter=(
            serialized_prefilter.decode("utf-8")
            if isinstance(serialized_prefilter, bytes)
            else serialized_prefilter
        ),
        summary=accumulator.finish(),
        top_datasets=tuple(selected),
        failures=tuple(failures),
        recoveries=tuple(recoveries),
    )


def _archive_path_or_fetch(archive_path: str | Path | None) -> Path:
    return Path(archive_path) if archive_path is not None else fetch_thermoml_archive()


def _parse_failure(path: Path, member_name: str, error: ThermoMLError) -> ArchiveParseFailure:
    return ArchiveParseFailure(
        member_name=member_name,
        source_locator=f"{path.resolve()}!{member_name}",
        error_type=type(error).__name__,
        message=str(error),
    )


def index_thermoml_archive(
    archive_path: str | Path | None = None,
    *,
    on_error: Literal["raise", "collect"] = "collect",
    json_fallback: JsonFallback = "on_xml_error",
) -> ArchiveComponentIndex:
    """Build a reusable archive-wide index of component aliases.

    Parameters
    ----------
    archive_path:
        Local archive path. The configured upstream snapshot is fetched when
        omitted.
    on_error:
        ``"raise"`` stops at the first malformed member; ``"collect"``
        records failures in the returned index.

    Returns
    -------
    ArchiveComponentIndex
        Detached identities connected through reported InChIKey, InChI, and
        CAS identifiers. No external chemical service is contacted.
    """
    if on_error not in {"raise", "collect"}:
        raise ValueError("on_error must be 'raise' or 'collect'.")
    _validate_json_fallback(json_fallback)
    path = _archive_path_or_fetch(archive_path)
    identities: list[ComponentIdentity] = []
    failures: list[ArchiveParseFailure] = []
    recoveries: list[ArchiveRecovery] = []
    xml_document_count = 0
    parsed_document_count = 0
    for member_name, raw in _archive_xml_members(path):
        xml_document_count += 1
        try:
            document, recovery = _parse_archive_document(
                path, member_name, raw, json_fallback=json_fallback
            )
        except ThermoMLError as exc:
            if on_error == "raise":
                raise ThermoMLArchiveError(
                    f"Failed to parse archive member {member_name!r}: {exc}"
                ) from exc
            failures.append(_parse_failure(path, member_name, exc))
            continue
        if recovery is not None:
            recoveries.append(recovery)
        parsed_document_count += 1
        identities.extend(
            ComponentIdentity.from_compound(compound) for compound in document.compounds
        )
    return ArchiveComponentIndex(
        archive_path=str(path),
        xml_document_count=xml_document_count,
        parsed_document_count=parsed_document_count,
        index=ComponentIndex.from_identities(identities),
        failures=tuple(failures),
        recoveries=tuple(recoveries),
    )


def catalog_thermoml_archive(
    archive_path: str | Path | None = None,
    *,
    on_error: Literal["raise", "collect"] = "collect",
    json_fallback: JsonFallback = "on_xml_error",
) -> ArchiveCatalog:
    """Scan a complete snapshot and catalog queryable property relationships.

    A relationship is one reported property value paired with one independent
    variable value in the same ThermoML ``NumValues`` record. Properties with
    no reported independent variable are retained with ``None`` as the
    independent-variable name.
    """
    if on_error not in {"raise", "collect"}:
        raise ValueError("on_error must be 'raise' or 'collect'.")
    _validate_json_fallback(json_fallback)
    path = _archive_path_or_fetch(archive_path)
    relationships: Counter[tuple[str, str, str | None]] = Counter()
    dataset_counts: Counter[tuple[str, str, str | None]] = Counter()
    publication_keys: defaultdict[tuple[str, str, str | None], set[str]] = defaultdict(set)
    failures: list[ArchiveParseFailure] = []
    recoveries: list[ArchiveRecovery] = []
    component_identities: list[ComponentIdentity] = []
    xml_document_count = 0
    parsed_document_count = 0

    for member_name, raw in _archive_xml_members(path):
        xml_document_count += 1
        try:
            document, recovery = _parse_archive_document(
                path, member_name, raw, json_fallback=json_fallback
            )
        except ThermoMLError as exc:
            if on_error == "raise":
                raise ThermoMLArchiveError(
                    f"Failed to parse archive member {member_name!r}: {exc}"
                ) from exc
            failures.append(_parse_failure(path, member_name, exc))
            continue
        if recovery is not None:
            recoveries.append(recovery)
        parsed_document_count += 1
        component_identities.extend(
            ComponentIdentity.from_compound(compound) for compound in document.compounds
        )
        publication_key = document.citation.normalized_doi or document.provenance.sha256
        for dataset in document.datasets:
            properties = {item.number: item for item in dataset.properties}
            variables = {item.number: item for item in dataset.variables}
            dataset_entries: set[tuple[str, str, str | None]] = set()
            for point in dataset.points:
                point_variables = [
                    variables[value.number]
                    for value in point.variable_values
                    if value.number in variables
                ]
                for measured in point.property_values:
                    definition = properties.get(measured.number)
                    if definition is None:  # pragma: no cover - parser validates references
                        continue
                    category = classify_property(definition, dataset)
                    variable_names: tuple[str | None, ...] = (
                        tuple(item.name for item in point_variables) if point_variables else (None,)
                    )
                    for variable_name in variable_names:
                        key = (category, definition.name, variable_name)
                        relationships[key] += 1
                        dataset_entries.add(key)
            for key in dataset_entries:
                dataset_counts[key] += 1
                publication_keys[key].add(publication_key)

    entries = tuple(
        CatalogEntry(
            data_category=key[0],
            property_name=key[1],
            independent_variable=key[2],
            relationship_count=count,
            dataset_count=dataset_counts[key],
            publication_count=len(publication_keys[key]),
        )
        for key, count in sorted(
            relationships.items(),
            key=lambda item: (
                normalize_term(item[0][0]),
                normalize_term(item[0][1]),
                normalize_term(item[0][2] or ""),
            ),
        )
    )
    return ArchiveCatalog(
        archive_path=str(path),
        xml_document_count=xml_document_count,
        parsed_document_count=parsed_document_count,
        entries=entries,
        component_identities=ComponentIndex.from_identities(component_identities).identities,
        failures=tuple(failures),
        recoveries=tuple(recoveries),
    )


def query_thermoml_archive(
    archive_path: str | Path | None = None,
    *,
    components: (ComponentQuery | tuple[ComponentQuery, ...] | list[ComponentQuery]),
    required_components: (tuple[ComponentQuery, ...] | list[ComponentQuery] | None) = None,
    component_match: ComponentMatch = "contains",
    component_index: ComponentIndex | ArchiveComponentIndex | None = None,
    data_category: str | None = None,
    property_name: str | None = None,
    independent_variable: str,
    publication_limit: int | None = None,
    serialized_prefilters: tuple[str | bytes, ...] | list[str | bytes] = (),
    on_error: Literal["raise", "collect"] = "collect",
    json_fallback: JsonFallback = "on_xml_error",
) -> ArchiveQueryResult:
    """Return property-versus-condition rows from a complete archive scan.

    Friendly strings are resolved against the complete archive before the data
    scan. Pass a reusable ``component_index`` from
    :func:`index_thermoml_archive`, or pass already resolved
    :class:`ComponentIdentity` objects, to avoid repeating the identity scan.
    Publications are ranked by the number of returned property-variable rows.
    ``publication_limit`` is applied only after every matching archive member
    has been scanned. The resulting table repeats full citation, provenance,
    system, method, phase, constraint, and uncertainty metadata on every row.
    """
    if publication_limit is not None and publication_limit < 0:
        raise ValueError("publication_limit must be non-negative or None.")
    if on_error not in {"raise", "collect"}:
        raise ValueError("on_error must be 'raise' or 'collect'.")
    _validate_json_fallback(json_fallback)
    if component_match not in {"exact", "contains", "within"}:
        raise ValueError("component_match must be 'exact', 'contains', or 'within'.")
    path = _archive_path_or_fetch(archive_path)
    component_queries = (
        (components,) if isinstance(components, str | ComponentIdentity) else tuple(components)
    )
    required_queries = tuple(required_components or ())
    if not component_queries:
        raise ValueError("components must contain at least one component query.")
    if required_queries and component_match != "within":
        raise ValueError("required_components is only valid with component_match='within'.")
    reusable_index = (
        component_index.index
        if isinstance(component_index, ArchiveComponentIndex)
        else component_index
    )
    prepared_queries: tuple[ComponentQuery, ...]
    if reusable_index is not None:
        prepared_queries = (*component_queries, *required_queries)
    else:
        prepared_queries = tuple(
            explicit_component_identity(query) or query if isinstance(query, str) else query
            for query in (*component_queries, *required_queries)
        )
    prepared_components = prepared_queries[: len(component_queries)]
    prepared_required = prepared_queries[len(component_queries) :]
    needs_resolution = any(isinstance(query, str) for query in prepared_queries)
    if reusable_index is None and needs_resolution:
        reusable_index = index_thermoml_archive(
            path, on_error=on_error, json_fallback=json_fallback
        ).index
    resolver = reusable_index or ComponentIndex(())
    resolved_components = resolver.resolve_many(prepared_components)
    resolved_required = resolver.resolve_many(prepared_required)
    available = {item.stable_identifier for item in resolved_components}
    if any(item.stable_identifier not in available for item in resolved_required):
        raise ValueError("required_components must be a subset of components.")
    needles = tuple(
        item.encode("utf-8") if isinstance(item, str) else item for item in serialized_prefilters
    )
    failures: list[ArchiveParseFailure] = []
    recoveries: list[ArchiveRecovery] = []
    rows_by_publication: defaultdict[str, list[tuple[Cell, ...]]] = defaultdict(list)
    publications: dict[str, PublicationRank] = {}
    columns: tuple[str, ...] | None = None
    xml_document_count = 0
    parsed_document_count = 0
    matched_dataset_count = 0

    for member_name, raw in _archive_xml_members(path):
        xml_document_count += 1
        if needles and not all(needle in raw for needle in needles):
            continue
        try:
            document, recovery = _parse_archive_document(
                path, member_name, raw, json_fallback=json_fallback
            )
        except ThermoMLError as exc:
            if on_error == "raise":
                raise ThermoMLArchiveError(
                    f"Failed to parse archive member {member_name!r}: {exc}"
                ) from exc
            failures.append(_parse_failure(path, member_name, exc))
            continue
        if recovery is not None:
            recoveries.append(recovery)
        parsed_document_count += 1
        collection = ThermoMLCollection((document,))
        matches = collection.search(
            components=resolved_components,
            required_components=resolved_required,
            component_match=component_match,
            property_name=property_name,
            data_type=data_category,
            independent_variable=independent_variable,
        )
        if not matches:
            continue
        matched_dataset_count += len(matches)
        table = build_property_table(collection, matches=matches)
        columns = table.columns
        publication_key = document.citation.normalized_doi or document.provenance.sha256
        rows_by_publication[publication_key].extend(table.rows)
        formatted_citation = publication_citation(document.citation)
        publications[publication_key] = PublicationRank(
            publication_key=publication_key,
            doi=document.citation.normalized_doi,
            title=document.citation.title,
            year=document.citation.year,
            authors_year=formatted_citation.authors_year,
            citation_apa=formatted_citation.apa,
            citation_bibtex=formatted_citation.bibtex,
            relationship_count=len(rows_by_publication[publication_key]),
        )

    ranking = sorted(
        publications.values(),
        key=lambda item: (-item.relationship_count, item.publication_key),
    )
    selected = ranking if publication_limit is None else ranking[:publication_limit]
    empty = build_property_table(ThermoMLCollection(()), matches=())
    selected_rows = tuple(
        row for publication in selected for row in rows_by_publication[publication.publication_key]
    )
    return ArchiveQueryResult(
        archive_path=str(path),
        components=tuple(component_query_label(query) for query in component_queries),
        required_components=tuple(component_query_label(query) for query in required_queries),
        resolved_components=resolved_components,
        resolved_required_components=resolved_required,
        component_match=component_match,
        data_category=data_category,
        property_name=property_name,
        independent_variable=independent_variable,
        xml_document_count=xml_document_count,
        parsed_document_count=parsed_document_count,
        available_publication_count=len(ranking),
        matched_dataset_count=matched_dataset_count,
        publications=tuple(selected),
        table=ExperimentalTable(columns=columns or empty.columns, rows=selected_rows),
        failures=tuple(failures),
        recoveries=tuple(recoveries),
    )
