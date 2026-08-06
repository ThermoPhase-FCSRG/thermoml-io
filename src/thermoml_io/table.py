"""Loss-aware tabular views and CSV, JSON, YAML, and Parquet exporters."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from .bibliography import publication_citation
from .classification import classify_property
from .collection import DatasetMatch, ThermoMLCollection
from .errors import OptionalDependencyError
from .models import (
    ConstraintDefinition,
    MeasuredValue,
    QuantityDefinition,
    ThermoMLDocument,
    Uncertainty,
)

TableFormat = Literal["csv", "json", "yaml", "parquet"]
Cell = str | int | float | bool | None

EXPERIMENTAL_TABLE_SCHEMA = "thermoml-io.experimental-table.v1"
ANALYSIS_TABLE_SCHEMA = "thermoml-io.analysis-table.v1"


def _json_default(value: object) -> object:
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _uncertainty_records(values: tuple[Uncertainty, ...]) -> list[dict[str, object]]:
    return [asdict(item) for item in values]


def _quantity_record(
    definition: QuantityDefinition,
    measured: MeasuredValue,
    document: ThermoMLDocument,
) -> dict[str, object]:
    component = (
        document.compound(definition.component_id).preferred_name
        if definition.component_id is not None
        else None
    )
    return {
        "number": definition.number,
        "name": definition.name,
        "phase": definition.phase,
        "component": component,
        "solvent_components": [
            document.compound(local_id).preferred_name
            for local_id in definition.solvent_component_ids
        ],
        "value": measured.lexical_value,
        "significant_digits": measured.significant_digits,
        "uncertainties": _uncertainty_records(measured.uncertainties),
        "value_repeatability": [asdict(item) for item in measured.repeatability],
        "definition_uncertainties": _uncertainty_records(definition.uncertainties),
        "definition_repeatability": [asdict(item) for item in definition.repeatability],
        "device_specifications": [asdict(item) for item in definition.device_specifications],
    }


def _constraint_record(
    definition: ConstraintDefinition,
    document: ThermoMLDocument,
) -> dict[str, object]:
    component = (
        document.compound(definition.component_id).preferred_name
        if definition.component_id is not None
        else None
    )
    return {
        "name": definition.name,
        "phase": definition.phase,
        "component": component,
        "solvent_components": [
            document.compound(local_id).preferred_name
            for local_id in definition.solvent_component_ids
        ],
        "value": str(definition.value) if definition.value is not None else None,
        "significant_digits": definition.significant_digits,
        "uncertainties": _uncertainty_records(definition.uncertainties),
        "repeatability": [asdict(item) for item in definition.repeatability],
        "device_specifications": [asdict(item) for item in definition.device_specifications],
    }


@dataclass(frozen=True, slots=True)
class ExperimentalTable:
    """Rectangular long-form view of heterogeneous experimental observations.

    Each row represents one property value. Variables, constraints, and the
    full uncertainty list are encoded as JSON text in scalar columns so the
    same schema can be exported consistently to CSV and Parquet.
    """

    columns: tuple[str, ...]
    rows: tuple[tuple[Cell, ...], ...]
    schema: str = EXPERIMENTAL_TABLE_SCHEMA

    @classmethod
    def concatenate(cls, *tables: ExperimentalTable) -> ExperimentalTable:
        """Concatenate compatible tables without dropping metadata columns."""
        if not tables:
            return cls(columns=(), rows=())
        columns = tables[0].columns
        schema = tables[0].schema
        if any(table.columns != columns or table.schema != schema for table in tables[1:]):
            raise ValueError("Cannot concatenate tables with different schemas.")
        return cls(
            columns=columns,
            rows=tuple(row for table in tables for row in table.rows),
            schema=schema,
        )

    def to_records(self) -> list[dict[str, Cell]]:
        """Return independent dictionaries suitable for dataframe creation."""
        return [dict(zip(self.columns, row, strict=True)) for row in self.rows]

    def to_pandas(self) -> Any:
        """Return a pandas DataFrame when the optional dependency is installed."""
        try:
            import pandas as pd  # type: ignore[import-untyped]
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise OptionalDependencyError(
                "pandas is required for to_pandas(); install thermoml-io[pandas]."
            ) from exc
        return pd.DataFrame.from_records(self.to_records(), columns=self.columns)

    def write(self, path: str | Path, *, format: TableFormat | None = None) -> Path:
        """Write the table using a format inferred from the path by default."""
        output = Path(path)
        selected = format or output.suffix.lower().removeprefix(".")
        if selected == "yml":
            selected = "yaml"
        if selected not in {"csv", "json", "yaml", "parquet"}:
            raise ValueError(f"Unsupported table format {selected!r}.")
        output.parent.mkdir(parents=True, exist_ok=True)
        if selected == "csv":
            with output.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=self.columns)
                writer.writeheader()
                writer.writerows(self.to_records())
        elif selected == "json":
            payload = {
                "schema": self.schema,
                "columns": self.columns,
                "rows": self.to_records(),
            }
            output.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
        elif selected == "yaml":
            try:
                import yaml  # type: ignore[import-untyped]
            except ImportError as exc:  # pragma: no cover - environment dependent
                raise OptionalDependencyError(
                    "PyYAML is required for YAML export; install thermoml-io[yaml]."
                ) from exc
            payload = {
                "schema": self.schema,
                "columns": list(self.columns),
                "rows": self.to_records(),
            }
            output.write_text(
                yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
        else:
            try:
                import pyarrow as pa
                import pyarrow.parquet as pq
            except ImportError as exc:  # pragma: no cover - environment dependent
                raise OptionalDependencyError(
                    "PyArrow is required for Parquet export; install thermoml-io[parquet]."
                ) from exc
            arrow_table = pa.Table.from_pylist(self.to_records())
            metadata = dict(arrow_table.schema.metadata or {})
            metadata[b"thermoml_io_schema"] = self.schema.removeprefix("thermoml-io.").encode(
                "utf-8"
            )
            arrow_table = arrow_table.replace_schema_metadata(metadata)
            pq.write_table(arrow_table, output)
        return output


_COLUMNS = (
    "source_locator",
    "source_sha256",
    "source_retrieved_at",
    "source_media_type",
    "source_related_xml_md5",
    "source_recovery_json",
    "source_warnings_json",
    "thermoml_version",
    "doi",
    "publication_year",
    "publication_date",
    "publication_document_type",
    "citation_title",
    "citation_authors",
    "citation_authors_year",
    "citation_apa",
    "citation_bibtex",
    "publication_name",
    "publication_volume",
    "publication_pages",
    "citation_url",
    "trc_reference_id",
    "dataset_key",
    "dataset_number",
    "dataset_purpose",
    "dataset_compiler",
    "dataset_contributor",
    "dataset_date_added",
    "dataset_phases",
    "system_key",
    "system_type",
    "components",
    "component_identifiers",
    "samples_json",
    "data_type",
    "property_number",
    "property_group",
    "property_name",
    "property_method",
    "property_phase",
    "property_component",
    "property_solvent_components",
    "property_presentation",
    "property_reference_phase",
    "property_standard_state",
    "property_definition_uncertainties_json",
    "property_repeatability_json",
    "property_device_specifications_json",
    "value",
    "significant_digits",
    "uncertainties_json",
    "value_repeatability_json",
    "variables_json",
    "constraints_json",
)


def build_experimental_table(
    collection: ThermoMLCollection,
    *,
    matches: tuple[DatasetMatch, ...] | None = None,
) -> ExperimentalTable:
    """Build a stable long-form table from all or selected datasets."""
    selected_matches = matches if matches is not None else collection.all_matches()
    rows: list[tuple[Cell, ...]] = []
    for match in selected_matches:
        document = match.document
        dataset = match.dataset
        citation = publication_citation(document.citation)
        properties = {item.number: item for item in dataset.properties}
        variables = {item.number: item for item in dataset.variables}
        compounds = document.system_compounds(dataset)
        samples_json = json.dumps(
            [
                {
                    "component": compound.preferred_name,
                    "stable_identifier": compound.stable_identifier,
                    "common_names": compound.common_names,
                    "iupac_name": compound.iupac_name,
                    "cas_name": compound.cas_name,
                    "formula": compound.formula,
                    "standard_inchi": compound.standard_inchi,
                    "standard_inchi_key": compound.standard_inchi_key,
                    "cas_registry_number": compound.cas_registry_number,
                    "samples": [asdict(sample) for sample in compound.samples],
                }
                for compound in compounds
            ],
            default=_json_default,
            ensure_ascii=False,
            sort_keys=True,
        )
        constraints_json = json.dumps(
            [_constraint_record(item, document) for item in dataset.constraints],
            default=_json_default,
            ensure_ascii=False,
            sort_keys=True,
        )
        for point in dataset.points:
            variables_json = json.dumps(
                [
                    _quantity_record(variables[value.number], value, document)
                    for value in point.variable_values
                ],
                default=_json_default,
                ensure_ascii=False,
                sort_keys=True,
            )
            for measured in point.property_values:
                if measured.number not in match.matching_property_numbers:
                    continue
                definition = properties[measured.number]
                component = (
                    document.compound(definition.component_id).preferred_name
                    if definition.component_id is not None
                    else None
                )
                record: dict[str, Cell] = {
                    "source_locator": document.provenance.locator,
                    "source_sha256": document.provenance.sha256,
                    "source_retrieved_at": (
                        document.provenance.retrieved_at.isoformat()
                        if document.provenance.retrieved_at is not None
                        else None
                    ),
                    "source_media_type": document.provenance.media_type,
                    "source_related_xml_md5": document.provenance.related_xml_md5,
                    "source_recovery_json": (
                        json.dumps(
                            asdict(document.provenance.recovery),
                            ensure_ascii=False,
                            sort_keys=True,
                        )
                        if document.provenance.recovery is not None
                        else None
                    ),
                    "source_warnings_json": json.dumps(
                        document.warnings,
                        ensure_ascii=False,
                    ),
                    "thermoml_version": document.schema_version,
                    "doi": document.citation.normalized_doi,
                    "publication_year": document.citation.year,
                    "publication_date": document.citation.date,
                    "publication_document_type": document.citation.document_type,
                    "citation_title": document.citation.title,
                    "citation_authors": " | ".join(document.citation.authors),
                    "citation_authors_year": citation.authors_year,
                    "citation_apa": citation.apa,
                    "citation_bibtex": citation.bibtex,
                    "publication_name": document.citation.publication_name,
                    "publication_volume": document.citation.volume,
                    "publication_pages": document.citation.pages,
                    "citation_url": document.citation.url,
                    "trc_reference_id": document.citation.trc_reference_id,
                    "dataset_key": match.dataset_key,
                    "dataset_number": dataset.number,
                    "dataset_purpose": dataset.purpose,
                    "dataset_compiler": dataset.compiler,
                    "dataset_contributor": dataset.contributor,
                    "dataset_date_added": dataset.date_added,
                    "dataset_phases": " | ".join(dataset.phases),
                    "system_key": match.system_key,
                    "system_type": dataset.system_type,
                    "components": " | ".join(item.preferred_name for item in compounds),
                    "component_identifiers": " | ".join(
                        item.stable_identifier for item in compounds
                    ),
                    "samples_json": samples_json,
                    "data_type": classify_property(definition, dataset),
                    "property_number": definition.number,
                    "property_group": definition.group,
                    "property_name": definition.name,
                    "property_method": definition.method,
                    "property_phase": definition.phase,
                    "property_component": component,
                    "property_solvent_components": " | ".join(
                        document.compound(local_id).preferred_name
                        for local_id in definition.solvent_component_ids
                    ),
                    "property_presentation": definition.presentation,
                    "property_reference_phase": definition.reference_phase,
                    "property_standard_state": definition.standard_state,
                    "property_definition_uncertainties_json": json.dumps(
                        _uncertainty_records(definition.uncertainties),
                        default=_json_default,
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    "property_repeatability_json": json.dumps(
                        [asdict(item) for item in definition.repeatability],
                        default=_json_default,
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    "property_device_specifications_json": json.dumps(
                        [asdict(item) for item in definition.device_specifications],
                        default=_json_default,
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    "value": measured.lexical_value,
                    "significant_digits": measured.significant_digits,
                    "uncertainties_json": json.dumps(
                        _uncertainty_records(measured.uncertainties),
                        default=_json_default,
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    "value_repeatability_json": json.dumps(
                        [asdict(item) for item in measured.repeatability],
                        default=_json_default,
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    "variables_json": variables_json,
                    "constraints_json": constraints_json,
                }
                rows.append(tuple(record[column] for column in _COLUMNS))
    return ExperimentalTable(columns=_COLUMNS, rows=tuple(rows))


_PROPERTY_RELATION_COLUMNS = (
    *_COLUMNS,
    "independent_variable_number",
    "independent_variable_name",
    "independent_variable_phase",
    "independent_variable_component",
    "independent_variable_solvent_components",
    "independent_variable_value",
    "independent_variable_significant_digits",
    "independent_variable_uncertainties_json",
    "independent_variable_definition_uncertainties_json",
    "independent_variable_repeatability_json",
    "independent_variable_definition_repeatability_json",
    "independent_variable_device_specifications_json",
    "complementary_conditions_json",
)


def build_property_table(
    collection: ThermoMLCollection,
    *,
    matches: tuple[DatasetMatch, ...],
) -> ExperimentalTable:
    """Build property-versus-independent-variable rows with full provenance.

    ``matches`` must come from :meth:`ThermoMLCollection.search` with an
    ``independent_variable`` filter. One output row represents one reported
    property value paired with one matching variable value from the same
    ThermoML ``NumValues`` record. Fixed experimental conditions remain in
    ``constraints_json``. ``complementary_conditions_json`` combines every
    other point variable with every fixed constraint, preserving their source
    so plots and regressions can distinguish isobars, isotherms, compositions,
    and other parameterizations. Every publication field from
    :func:`build_experimental_table` is retained.
    """
    if any(not match.matching_variable_numbers for match in matches):
        raise ValueError(
            "build_property_table requires matches selected with independent_variable."
        )
    selected_variables = {
        match.dataset_key: set(match.matching_variable_numbers) for match in matches
    }
    base = build_experimental_table(collection, matches=matches)
    rows: list[tuple[Cell, ...]] = []
    for record in base.to_records():
        dataset_key = record["dataset_key"]
        if not isinstance(dataset_key, str):  # pragma: no cover - stable schema
            continue
        variables_json = record["variables_json"]
        if not isinstance(variables_json, str):  # pragma: no cover - stable schema
            continue
        variables = json.loads(variables_json)
        for variable in variables:
            if variable["number"] not in selected_variables[dataset_key]:
                continue
            constraints_json = record["constraints_json"]
            if not isinstance(constraints_json, str):  # pragma: no cover - stable schema
                continue
            complementary_conditions = [
                {"source": "variable", **item}
                for item in variables
                if item["number"] != variable["number"]
            ]
            complementary_conditions.extend(
                {"source": "constraint", **item} for item in json.loads(constraints_json)
            )
            relation = {
                **record,
                "independent_variable_number": variable["number"],
                "independent_variable_name": variable["name"],
                "independent_variable_phase": variable["phase"],
                "independent_variable_component": variable["component"],
                "independent_variable_solvent_components": " | ".join(
                    variable["solvent_components"]
                ),
                "independent_variable_value": variable["value"],
                "independent_variable_significant_digits": variable["significant_digits"],
                "independent_variable_uncertainties_json": json.dumps(
                    variable["uncertainties"], ensure_ascii=False, sort_keys=True
                ),
                "independent_variable_definition_uncertainties_json": json.dumps(
                    variable["definition_uncertainties"],
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                "independent_variable_repeatability_json": json.dumps(
                    variable["value_repeatability"],
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                "independent_variable_definition_repeatability_json": json.dumps(
                    variable["definition_repeatability"],
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                "independent_variable_device_specifications_json": json.dumps(
                    variable["device_specifications"],
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                "complementary_conditions_json": json.dumps(
                    complementary_conditions,
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            }
            rows.append(tuple(relation[column] for column in _PROPERTY_RELATION_COLUMNS))
    return ExperimentalTable(columns=_PROPERTY_RELATION_COLUMNS, rows=tuple(rows))


_ANALYSIS_METADATA_COLUMNS = (
    "DOI",
    "Authors/Year",
    "System",
    "System Type",
    "Phases",
    "Method",
    "Data Category",
    "Dataset",
    "metadata",
)


def _decoded_list(record: dict[str, Cell], column: str) -> list[dict[str, Any]]:
    serialized = record[column]
    if not isinstance(serialized, str):
        raise ValueError(f"Expected serialized JSON text in {column!r}.")
    decoded = json.loads(serialized)
    if not isinstance(decoded, list) or any(not isinstance(item, dict) for item in decoded):
        raise ValueError(f"Expected a JSON list of objects in {column!r}.")
    return decoded


def _decoded_object_or_none(record: dict[str, Cell], column: str) -> dict[str, Any] | None:
    serialized = record[column]
    if serialized is None:
        return None
    if not isinstance(serialized, str):
        raise ValueError(f"Expected serialized JSON text or null in {column!r}.")
    decoded = json.loads(serialized)
    if not isinstance(decoded, dict):
        raise ValueError(f"Expected a JSON object in {column!r}.")
    return decoded


def _decoded_string_list(record: dict[str, Cell], column: str) -> list[str]:
    serialized = record[column]
    if not isinstance(serialized, str):
        raise ValueError(f"Expected serialized JSON text in {column!r}.")
    decoded = json.loads(serialized)
    if not isinstance(decoded, list) or any(not isinstance(item, str) for item in decoded):
        raise ValueError(f"Expected a JSON list of strings in {column!r}.")
    return decoded


def _condition_sort_key(label: str) -> tuple[int, str]:
    normalized = label.casefold()
    if "temperature" in normalized:
        priority = 0
    elif "pressure" in normalized:
        priority = 1
    elif any(term in normalized for term in ("fraction", "composition", "molality")):
        priority = 2
    else:
        priority = 3
    return priority, normalized


def _condition_signature(item: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(item.get("source") or "unspecified"),
        str(item.get("phase") or "unspecified"),
        str(item.get("component") or "unspecified"),
    )


def _property_signature(record: dict[str, Cell]) -> tuple[str, str]:
    return (
        str(record["property_phase"] or "unspecified"),
        str(record["property_component"] or "unspecified"),
    )


def _condition_label(
    name: str,
    signature: tuple[str, str, str],
    signatures: dict[str, set[tuple[str, str, str]]],
) -> str:
    if len(signatures[name]) == 1:
        return name
    source, phase, component = signature
    qualifiers = [source]
    if phase != "unspecified":
        qualifiers.append(f"phase={phase}")
    if component != "unspecified":
        qualifiers.append(f"component={component}")
    return f"{name} [{'; '.join(qualifiers)}]"


def _property_label(
    name: str,
    signature: tuple[str, str],
    signatures: dict[str, set[tuple[str, str]]],
) -> str:
    if len(signatures[name]) == 1:
        return name
    phase, component = signature
    return f"{name} [phase={phase}; component={component}]"


def _analysis_metadata(
    record: dict[str, Cell],
    conditions: list[dict[str, Any]],
) -> str:
    publication = {
        "doi": record["doi"],
        "title": record["citation_title"],
        "authors": (
            str(record["citation_authors"]).split(" | ") if record["citation_authors"] else []
        ),
        "year": record["publication_year"],
        "date": record["publication_date"],
        "document_type": record["publication_document_type"],
        "authors_year": record["citation_authors_year"],
        "journal": record["publication_name"],
        "volume": record["publication_volume"],
        "pages": record["publication_pages"],
        "url": record["citation_url"],
        "trc_reference_id": record["trc_reference_id"],
        "apa": record["citation_apa"],
        "bibtex": record["citation_bibtex"],
    }
    source = {
        "locator": record["source_locator"],
        "sha256": record["source_sha256"],
        "retrieved_at": record["source_retrieved_at"],
        "media_type": record["source_media_type"],
        "related_xml_md5": record["source_related_xml_md5"],
        "recovery": _decoded_object_or_none(record, "source_recovery_json"),
        "warnings": _decoded_string_list(record, "source_warnings_json"),
        "thermoml_version": record["thermoml_version"],
    }
    dataset = {
        "key": record["dataset_key"],
        "number": record["dataset_number"],
        "system_key": record["system_key"],
        "purpose": record["dataset_purpose"],
        "compiler": record["dataset_compiler"],
        "contributor": record["dataset_contributor"],
        "date_added": record["dataset_date_added"],
    }
    system = {
        "component_identifiers": str(record["component_identifiers"] or "").split(" | "),
        "samples": _decoded_list(record, "samples_json"),
    }
    property_metadata = {
        "number": record["property_number"],
        "group": record["property_group"],
        "name": record["property_name"],
        "phase": record["property_phase"],
        "component": record["property_component"],
        "solvent_components": record["property_solvent_components"],
        "presentation": record["property_presentation"],
        "reference_phase": record["property_reference_phase"],
        "standard_state": record["property_standard_state"],
        "significant_digits": record["significant_digits"],
        "uncertainties": _decoded_list(record, "uncertainties_json"),
        "definition_uncertainties": _decoded_list(record, "property_definition_uncertainties_json"),
        "repeatability": _decoded_list(record, "value_repeatability_json"),
        "definition_repeatability": _decoded_list(record, "property_repeatability_json"),
        "device_specifications": _decoded_list(record, "property_device_specifications_json"),
    }
    payload = {
        "schema": "thermoml-io.analysis-row-metadata.v1",
        "publication": publication,
        "source": source,
        "dataset": dataset,
        "system": system,
        "property": property_metadata,
        "conditions": conditions,
    }
    return json.dumps(
        payload,
        default=_json_default,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def build_analysis_table(table: ExperimentalTable) -> ExperimentalTable:
    """Pivot a property-condition table into an analysis-ready wide table.

    Physical quantities become ordinary columns named exactly as reported by
    ThermoML, including their units (for example ``Temperature, K`` and
    ``Viscosity, Pa*s``). Each row remains one reported property observation.
    DOI, authors/year, system, phases, method, category, and dataset identity
    are repeated as scalar columns. Less frequently used metrological and
    provenance details are retained as compact JSON in ``metadata``.

    If the same reported quantity name has multiple semantic meanings within
    one observation, its columns are explicitly qualified by source, phase, or
    component. Differences that occur only between rows remain in metadata so
    the main physical columns stay compact. Duplicate indistinguishable
    conditions in one observation raise rather than silently overwriting a
    value.

    Parameters
    ----------
    table:
        Lossless table returned by :func:`build_property_table`.

    Returns
    -------
    ExperimentalTable
        Analysis-ready table with schema ``thermoml-io.analysis-table.v1``.

    Raises
    ------
    ValueError
        If ``table`` is not a property-condition table or contains ambiguous
        duplicate conditions that cannot be represented safely in one row.
    """
    missing = set(_PROPERTY_RELATION_COLUMNS).difference(table.columns)
    if missing:
        raise ValueError(
            "build_analysis_table requires a property-condition table; "
            f"missing columns: {', '.join(sorted(missing))}."
        )

    prepared: list[tuple[dict[str, Cell], list[dict[str, Any]]]] = []
    condition_signatures: dict[str, set[tuple[str, str, str]]] = {}
    condition_names_ambiguous_within_row: set[str] = set()
    property_signatures: dict[str, set[tuple[str, str]]] = {}
    for record in table.to_records():
        independent_name = record["independent_variable_name"]
        if not isinstance(independent_name, str):
            raise ValueError("Independent-variable names must be strings.")
        independent = {
            "role": "independent",
            "source": "variable",
            "number": record["independent_variable_number"],
            "name": independent_name,
            "phase": record["independent_variable_phase"],
            "component": record["independent_variable_component"],
            "solvent_components": record["independent_variable_solvent_components"],
            "value": record["independent_variable_value"],
            "significant_digits": record["independent_variable_significant_digits"],
            "uncertainties": _decoded_list(record, "independent_variable_uncertainties_json"),
            "definition_uncertainties": _decoded_list(
                record, "independent_variable_definition_uncertainties_json"
            ),
            "repeatability": _decoded_list(record, "independent_variable_repeatability_json"),
            "definition_repeatability": _decoded_list(
                record, "independent_variable_definition_repeatability_json"
            ),
            "device_specifications": _decoded_list(
                record, "independent_variable_device_specifications_json"
            ),
        }
        complementary = _decoded_list(record, "complementary_conditions_json")
        for item in complementary:
            item["role"] = "complementary"
        conditions = [independent, *complementary]
        row_condition_signatures: dict[str, set[tuple[str, str, str]]] = {}
        for condition in conditions:
            name = condition.get("name")
            if not isinstance(name, str):
                raise ValueError("Condition names must be strings.")
            signature = _condition_signature(condition)
            condition_signatures.setdefault(name, set()).add(signature)
            row_condition_signatures.setdefault(name, set()).add(signature)
        condition_names_ambiguous_within_row.update(
            name for name, signatures in row_condition_signatures.items() if len(signatures) > 1
        )
        property_name = record["property_name"]
        if not isinstance(property_name, str):
            raise ValueError("Property names must be strings.")
        property_signatures.setdefault(property_name, set()).add(_property_signature(record))
        prepared.append((record, conditions))

    condition_signatures = {
        name: (
            signatures if name in condition_names_ambiguous_within_row else {next(iter(signatures))}
        )
        for name, signatures in condition_signatures.items()
    }
    property_signatures = {
        name: {next(iter(signatures))} for name, signatures in property_signatures.items()
    }
    condition_columns = sorted(
        {
            _condition_label(name, signature, condition_signatures)
            for name, signatures in condition_signatures.items()
            for signature in signatures
        },
        key=_condition_sort_key,
    )
    property_columns = sorted(
        {
            _property_label(name, signature, property_signatures)
            for name, signatures in property_signatures.items()
            for signature in signatures
        },
        key=str.casefold,
    )
    columns = (*condition_columns, *property_columns, *_ANALYSIS_METADATA_COLUMNS)
    rows: list[tuple[Cell, ...]] = []
    for record, conditions in prepared:
        output: dict[str, Cell] = dict.fromkeys(columns)
        for condition in conditions:
            name = str(condition["name"])
            label = _condition_label(name, _condition_signature(condition), condition_signatures)
            if output[label] is not None:
                raise ValueError(
                    "Cannot represent duplicate indistinguishable condition "
                    f"{label!r} in one analysis row."
                )
            output[label] = condition.get("value")
        property_name = str(record["property_name"])
        property_label = _property_label(
            property_name, _property_signature(record), property_signatures
        )
        output[property_label] = record["value"]
        components = str(record["components"] or "")
        output.update(
            {
                "DOI": record["doi"],
                "Authors/Year": record["citation_authors_year"],
                "System": " + ".join(components.split(" | ")),
                "System Type": record["system_type"],
                "Phases": record["dataset_phases"],
                "Method": record["property_method"],
                "Data Category": record["data_type"],
                "Dataset": record["dataset_key"],
                "metadata": _analysis_metadata(record, conditions),
            }
        )
        rows.append(tuple(output[column] for column in columns))
    return ExperimentalTable(
        columns=columns,
        rows=tuple(rows),
        schema=ANALYSIS_TABLE_SCHEMA,
    )
