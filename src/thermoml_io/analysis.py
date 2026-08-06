"""Descriptive metadata and coverage summaries for ThermoML collections."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass

from .classification import classify_property
from .collection import ThermoMLCollection
from .models import DataSet, ThermoMLDocument


@dataclass(frozen=True, slots=True)
class RankedCount:
    """One deterministic label/count pair in a collection ranking."""

    label: str
    count: int


@dataclass(frozen=True, slots=True)
class CollectionSummary:
    """Counts and ranked coverage of a ThermoML collection."""

    document_count: int
    dataset_count: int
    data_point_count: int
    observation_count: int
    reaction_dataset_count: int
    system_types: tuple[RankedCount, ...]
    dataset_system_types: tuple[RankedCount, ...]
    data_types: tuple[RankedCount, ...]
    property_groups: tuple[RankedCount, ...]
    properties: tuple[RankedCount, ...]
    systems: tuple[RankedCount, ...]
    components: tuple[RankedCount, ...]
    methods: tuple[RankedCount, ...]
    publications: tuple[RankedCount, ...]

    def top(self, field: str, limit: int = 10) -> tuple[RankedCount, ...]:
        """Return the first ``limit`` entries from one ranking field."""
        if limit < 0:
            raise ValueError("limit must be non-negative.")
        ranking = getattr(self, field)
        if not isinstance(ranking, tuple):
            raise ValueError(f"{field!r} is not a ranking field.")
        return ranking[:limit]


def _rank(counter: Counter[str]) -> tuple[RankedCount, ...]:
    return tuple(
        RankedCount(label=label, count=count)
        for label, count in sorted(counter.items(), key=lambda item: (-item[1], item[0]))
    )


@dataclass(slots=True)
class _SummaryAccumulator:
    system_types: Counter[str]
    dataset_system_types: Counter[str]
    data_types: Counter[str]
    property_groups: Counter[str]
    properties: Counter[str]
    systems: Counter[str]
    components: Counter[str]
    methods: Counter[str]
    publications: Counter[str]
    document_count: int = 0
    dataset_count: int = 0
    point_count: int = 0
    observation_count: int = 0
    reaction_dataset_count: int = 0

    @classmethod
    def create(cls) -> _SummaryAccumulator:
        return cls(
            system_types=Counter(),
            dataset_system_types=Counter(),
            data_types=Counter(),
            property_groups=Counter(),
            properties=Counter(),
            systems=Counter(),
            components=Counter(),
            methods=Counter(),
            publications=Counter(),
        )

    def add_document(
        self,
        document: ThermoMLDocument,
        datasets: Iterable[DataSet] | None = None,
        *,
        include_reactions: bool = True,
    ) -> None:
        selected = tuple(document.datasets if datasets is None else datasets)
        if not selected and not (include_reactions and document.reaction_dataset_count):
            return
        self.document_count += 1
        if include_reactions:
            self.reaction_dataset_count += document.reaction_dataset_count
        publication = (
            document.citation.normalized_doi
            or document.citation.title
            or document.provenance.sha256
        )
        for dataset in selected:
            self.dataset_count += 1
            self.dataset_system_types[dataset.system_type] += 1
            self.point_count += len(dataset.points)
            counts = Counter(
                measured.number for point in dataset.points for measured in point.property_values
            )
            system = " + ".join(
                sorted(item.preferred_name for item in document.system_compounds(dataset))
            )
            component_names = tuple(
                item.preferred_name for item in document.system_compounds(dataset)
            )
            for definition in dataset.properties:
                count = counts[definition.number]
                if not count:
                    continue
                self.observation_count += count
                self.system_types[dataset.system_type] += count
                self.data_types[classify_property(definition, dataset)] += count
                self.property_groups[definition.group] += count
                self.properties[definition.name] += count
                self.systems[system] += count
                self.publications[publication] += count
                if definition.method:
                    self.methods[definition.method] += count
                for component in component_names:
                    self.components[component] += count

    def finish(self) -> CollectionSummary:
        return CollectionSummary(
            document_count=self.document_count,
            dataset_count=self.dataset_count,
            data_point_count=self.point_count,
            observation_count=self.observation_count,
            reaction_dataset_count=self.reaction_dataset_count,
            system_types=_rank(self.system_types),
            dataset_system_types=_rank(self.dataset_system_types),
            data_types=_rank(self.data_types),
            property_groups=_rank(self.property_groups),
            properties=_rank(self.properties),
            systems=_rank(self.systems),
            components=_rank(self.components),
            methods=_rank(self.methods),
            publications=_rank(self.publications),
        )


def summarize_documents(
    documents: Iterable[ThermoMLDocument],
) -> CollectionSummary:
    """Summarize a document stream without retaining the complete collection.

    This is the scalable entry point for bulk archives. Every document is
    consumed exactly once, allowing callers to process millions of observations
    while retaining only aggregate counters.
    """
    accumulator = _SummaryAccumulator.create()
    for document in documents:
        accumulator.add_document(document)
    return accumulator.finish()


def summarize_collection(collection: ThermoMLCollection) -> CollectionSummary:
    """Summarize all parsed experimental observations in ``collection``.

    Component and system counts are weighted by individual property
    observations. A dataset with 100 property values therefore contributes
    more than a dataset with 10 values, matching the ranking semantics of the
    search API.
    """
    return summarize_documents(collection.documents)
