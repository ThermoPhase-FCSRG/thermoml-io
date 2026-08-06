"""Immutable scientific data model for ThermoML documents.

The model preserves publication, sample, experimental, phase, and uncertainty
metadata without forcing heterogeneous ThermoML properties into a single
rectangular representation. Tabular views are constructed separately.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Literal

SystemType = Literal["pure", "binary", "ternary", "quaternary", "other"]


@dataclass(frozen=True, slots=True)
class SourceRecovery:
    """Audit record for recovery from an unreadable primary serialization.

    The successful replacement remains the source described by
    :class:`SourceProvenance`. These fields retain the failed source so a
    downstream table never hides that recovery occurred.
    """

    strategy: str
    failed_locator: str | None
    failed_sha256: str
    failed_media_type: str
    failure_type: str
    failure_message: str
    lexical_numeric_representation_preserved: bool = False


@dataclass(frozen=True, slots=True)
class SourceProvenance:
    """Provenance of the exact serialized source parsed by the library.

    Parameters
    ----------
    locator:
        Local path, URL, persistent identifier, or user-supplied label. It may
        be absent for in-memory documents.
    sha256:
        SHA-256 digest of the original source bytes.
    retrieved_at:
        UTC timestamp recorded by the network loader, when applicable.
    media_type:
        Media type of the original serialization.
    related_xml_md5:
        NIST-provided MD5 checksum of the related XML representation, when
        reported by an official JSON document. This is a relationship field,
        not the integrity digest used for the parsed JSON bytes.
    recovery:
        Explicit audit record when this source replaced an unreadable primary
        serialization.
    """

    locator: str | None
    sha256: str
    retrieved_at: datetime | None = None
    media_type: str = "application/xml"
    related_xml_md5: str | None = None
    recovery: SourceRecovery | None = None


@dataclass(frozen=True, slots=True)
class Citation:
    """Bibliographic metadata reported in a ThermoML document."""

    authors: tuple[str, ...] = ()
    title: str | None = None
    publication_name: str | None = None
    year: int | None = None
    date: str | None = None
    volume: str | None = None
    pages: str | None = None
    doi: str | None = None
    url: str | None = None
    document_type: str | None = None
    source_type: str | None = None
    document_origin: str | None = None
    abstract: str | None = None
    keywords: tuple[str, ...] = ()
    language: str | None = None
    trc_reference_id: str | None = None

    @property
    def normalized_doi(self) -> str | None:
        """Return a lower-case DOI without a resolver URL prefix."""
        if self.doi is None:
            return None
        doi = self.doi.strip()
        for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
            if doi.lower().startswith(prefix):
                doi = doi[len(prefix) :]
                break
        return doi.lower()


@dataclass(frozen=True, slots=True)
class PurityAssessment:
    """One reported purification or purity-assessment step for a sample."""

    step: int | None = None
    purification_methods: tuple[str, ...] = ()
    analysis_methods: tuple[str, ...] = ()
    mole_percent: Decimal | None = None
    mole_percent_digits: int | None = None
    mass_percent: Decimal | None = None
    mass_percent_digits: int | None = None
    volume_percent: Decimal | None = None
    volume_percent_digits: int | None = None
    unspecified_percent: Decimal | None = None


@dataclass(frozen=True, slots=True)
class Sample:
    """Metadata for one material sample used by an experiment."""

    number: int
    source: str | None = None
    status: str | None = None
    purity: tuple[PurityAssessment, ...] = ()


@dataclass(frozen=True, slots=True)
class Compound:
    """Chemical identity and associated sample metadata.

    The ``local_id`` is scoped to one ThermoML document and must never be used
    as a global chemical identifier.
    """

    local_id: int
    common_names: tuple[str, ...] = ()
    iupac_name: str | None = None
    cas_name: str | None = None
    formula: str | None = None
    standard_inchi: str | None = None
    standard_inchi_key: str | None = None
    cas_registry_number: str | None = None
    samples: tuple[Sample, ...] = ()

    @property
    def preferred_name(self) -> str:
        """Return the best available human-readable component label."""
        if self.common_names:
            return self.common_names[0]
        if self.iupac_name:
            return self.iupac_name
        if self.formula:
            return self.formula
        if self.standard_inchi_key:
            return self.standard_inchi_key
        return f"component-{self.local_id}"

    @property
    def stable_identifier(self) -> str:
        """Return the most stable reported identifier available."""
        if self.standard_inchi_key:
            return f"inchikey:{self.standard_inchi_key.upper()}"
        if self.standard_inchi:
            return f"inchi:{self.standard_inchi}"
        if self.cas_registry_number:
            return f"cas:{self.cas_registry_number}"
        return f"name:{self.preferred_name.casefold()}"

    def matches(self, query: str) -> bool:
        """Return whether ``query`` identifies this compound.

        Matching is case-insensitive and considers names, formula, CAS,
        standard InChI, and InChIKey. It is intentionally exact after trimming
        whitespace to avoid accidental chemical matches.
        """
        normalized = query.strip().casefold()
        identifiers = {
            self.preferred_name.casefold(),
            *(name.strip().casefold() for name in self.common_names),
        }
        for candidate in (
            self.iupac_name,
            self.cas_name,
            self.formula,
            self.standard_inchi,
            self.standard_inchi_key,
            self.cas_registry_number,
        ):
            if candidate:
                identifiers.add(candidate.strip().casefold())
        return normalized in identifiers


@dataclass(frozen=True, slots=True)
class Uncertainty:
    """One uncertainty assessment associated with a reported quantity.

    Values are retained in the same units as the corresponding ThermoML
    quantity. ``coverage_factor`` and ``confidence_level`` are dimensionless.
    """

    kind: str
    assessment_number: int | None = None
    evaluator: str | None = None
    method: str | None = None
    standard_value: Decimal | None = None
    expanded_value: Decimal | None = None
    positive_standard_value: Decimal | None = None
    negative_standard_value: Decimal | None = None
    positive_expanded_value: Decimal | None = None
    negative_expanded_value: Decimal | None = None
    coverage_factor: Decimal | None = None
    confidence_level: Decimal | None = None


@dataclass(frozen=True, slots=True)
class Repeatability:
    """Repeatability metadata attached to a quantity definition or value."""

    evaluator: str | None = None
    method: str | None = None
    standard_value: Decimal | None = None


@dataclass(frozen=True, slots=True)
class DeviceSpecification:
    """Instrument or device specification reported by the source."""

    evaluator: str | None = None
    method: str | None = None
    description: str | None = None
    value: Decimal | None = None
    confidence_level: Decimal | None = None


@dataclass(frozen=True, slots=True)
class QuantityDefinition:
    """Definition shared by properties, variables, and constraints."""

    number: int
    name: str
    phase: str | None = None
    component_id: int | None = None
    solvent_component_ids: tuple[int, ...] = ()
    uncertainties: tuple[Uncertainty, ...] = ()
    repeatability: tuple[Repeatability, ...] = ()
    device_specifications: tuple[DeviceSpecification, ...] = ()


@dataclass(frozen=True, slots=True)
class PropertyDefinition(QuantityDefinition):
    """Definition of one experimentally reported property."""

    group: str = "Unknown"
    method: str | None = None
    presentation: str | None = None
    reference_phase: str | None = None
    standard_state: str | None = None


@dataclass(frozen=True, slots=True)
class VariableDefinition(QuantityDefinition):
    """Definition of one independent variable varied between data points."""


@dataclass(frozen=True, slots=True)
class ConstraintDefinition(QuantityDefinition):
    """Definition and fixed value of one experimental constraint."""

    value: Decimal | None = None
    significant_digits: int | None = None


@dataclass(frozen=True, slots=True)
class MeasuredValue:
    """Reported numeric value linked to a quantity definition."""

    number: int
    value: Decimal
    lexical_value: str
    significant_digits: int | None = None
    uncertainties: tuple[Uncertainty, ...] = ()
    repeatability: tuple[Repeatability, ...] = ()


@dataclass(frozen=True, slots=True)
class DataPoint:
    """One ThermoML ``NumValues`` record."""

    index: int
    variable_values: tuple[MeasuredValue, ...] = ()
    property_values: tuple[MeasuredValue, ...] = ()


@dataclass(frozen=True, slots=True)
class DataSet:
    """One pure-compound or mixture experimental dataset."""

    number: int
    component_ids: tuple[int, ...]
    component_sample_numbers: tuple[tuple[int, int | None], ...] = ()
    purpose: str | None = None
    compiler: str | None = None
    contributor: str | None = None
    date_added: str | None = None
    phases: tuple[str, ...] = ()
    properties: tuple[PropertyDefinition, ...] = ()
    variables: tuple[VariableDefinition, ...] = ()
    constraints: tuple[ConstraintDefinition, ...] = ()
    points: tuple[DataPoint, ...] = ()

    @property
    def system_type(self) -> SystemType:
        """Classify the system by its number of distinct components."""
        order = len(set(self.component_ids))
        names: dict[int, SystemType] = {
            1: "pure",
            2: "binary",
            3: "ternary",
            4: "quaternary",
        }
        return names.get(order, "other")

    @property
    def observation_count(self) -> int:
        """Return the number of individual property values in the dataset."""
        return sum(len(point.property_values) for point in self.points)


@dataclass(frozen=True, slots=True)
class ThermoMLDocument:
    """Complete parsed ThermoML document and its source provenance."""

    version_major: int
    version_minor: int
    citation: Citation
    compounds: tuple[Compound, ...]
    datasets: tuple[DataSet, ...]
    provenance: SourceProvenance
    warnings: tuple[str, ...] = ()
    reaction_dataset_count: int = 0
    _compound_by_id: dict[int, Compound] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        mapping = {compound.local_id: compound for compound in self.compounds}
        object.__setattr__(self, "_compound_by_id", mapping)

    @property
    def schema_version(self) -> str:
        """Return the document-declared ThermoML version."""
        return f"{self.version_major}.{self.version_minor}"

    def compound(self, local_id: int) -> Compound:
        """Resolve a document-local component identifier."""
        return self._compound_by_id[local_id]

    def system_compounds(self, dataset: DataSet) -> tuple[Compound, ...]:
        """Resolve all components in ``dataset`` in document order."""
        return tuple(self.compound(local_id) for local_id in dataset.component_ids)

    def system_key(self, dataset: DataSet) -> str:
        """Return an order-independent, chemically stable system key."""
        identifiers = sorted(
            self.compound(local_id).stable_identifier for local_id in set(dataset.component_ids)
        )
        return " | ".join(identifiers)

    def dataset_key(self, dataset: DataSet) -> str:
        """Return a stable key for a dataset within a source publication."""
        source = self.citation.normalized_doi or self.provenance.sha256
        return f"{source}#pure-or-mixture-{dataset.number}"
