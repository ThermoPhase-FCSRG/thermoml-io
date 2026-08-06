"""Search, ranking, and multi-document aggregation for ThermoML data."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from .classification import classify_property, normalize_term
from .identity import ComponentIdentity, ComponentIndex, ComponentQuery
from .models import DataSet, PropertyDefinition, ThermoMLDocument
from .parser import load_thermoml_url

SystemMatch = Literal["exact", "contains"]
ComponentMatch = Literal["exact", "contains", "within"]


@dataclass(frozen=True, slots=True)
class DatasetMatch:
    """A ranked dataset returned by :meth:`ThermoMLCollection.search`.

    ``observation_count`` counts only property values matching the requested
    property/category filters. It is therefore the ranking metric used before
    ``limit`` is applied.
    """

    document: ThermoMLDocument
    dataset: DataSet
    matching_property_numbers: tuple[int, ...]
    observation_count: int
    data_types: tuple[str, ...]
    matching_variable_numbers: tuple[int, ...] = ()

    @property
    def dataset_key(self) -> str:
        """Return the stable publication-scoped key of the matched dataset."""
        return self.document.dataset_key(self.dataset)

    @property
    def system_key(self) -> str:
        """Return the order-independent chemical system key."""
        return self.document.system_key(self.dataset)


@dataclass(frozen=True, slots=True)
class ThermoMLCollection:
    """An immutable collection of independently sourced ThermoML documents."""

    documents: tuple[ThermoMLDocument, ...]
    _component_index: ComponentIndex = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_component_index", ComponentIndex.from_documents(self.documents))

    @property
    def component_index(self) -> ComponentIndex:
        """Return the collection-wide exact-alias component index."""
        return self._component_index

    def resolve_component(self, query: ComponentQuery) -> ComponentIdentity:
        """Resolve one friendly or namespaced component query.

        Raises
        ------
        ComponentNotFoundError
            If no compound in the collection reports the requested identity.
        AmbiguousComponentError
            If the query matches more than one chemically distinct identity.
        """
        return self._component_index.resolve(query)

    @classmethod
    def from_urls(
        cls,
        urls: tuple[str, ...] | list[str],
        *,
        timeout: float = 30.0,
        max_bytes: int = 100 * 1024 * 1024,
    ) -> ThermoMLCollection:
        """Download several ThermoML documents without persisting their bytes."""
        return cls(
            tuple(load_thermoml_url(url, timeout=timeout, max_bytes=max_bytes) for url in urls)
        )

    def search(
        self,
        *,
        components: (
            ComponentQuery | tuple[ComponentQuery, ...] | list[ComponentQuery] | None
        ) = None,
        required_components: (tuple[ComponentQuery, ...] | list[ComponentQuery] | None) = None,
        component_match: ComponentMatch = "contains",
        system: tuple[ComponentQuery, ...] | list[ComponentQuery] | None = None,
        system_match: SystemMatch = "exact",
        property_name: str | None = None,
        data_type: str | None = None,
        independent_variable: str | None = None,
        limit: int | None = None,
    ) -> tuple[DatasetMatch, ...]:
        """Search and rank experimental datasets.

        Parameters
        ----------
        components:
            One component or a list defining the component query. Queries match
            exact reported names, formulas, CAS numbers, InChI, or InChIKey,
            case-insensitively. Prefixes such as ``"formula:H2"``,
            ``"cas:1333-74-0"``, and ``"inchikey:..."`` restrict the
            identifier type. Friendly aliases are resolved across the complete
            collection before dataset matching.
        required_components:
            Mandatory subset of ``components`` when ``component_match`` is
            ``"within"``. Other listed components are optional, while unlisted
            components are rejected.
        component_match:
            ``"exact"`` requires exactly ``components``; ``"contains"``
            requires every listed component and allows extras; ``"within"``
            restricts systems to subsets of ``components`` and requires
            ``required_components``.
        system:
            Component identities describing a chemical system. By default the
            match is order-independent and exact.
        system_match:
            ``"exact"`` requires the complete system; ``"contains"`` allows
            additional components.
        property_name:
            Case-insensitive substring of the reported ThermoML property name.
        data_type:
            Package classification such as ``"VLE"``, ``"volumetric"``, or
            ``"transport"``. The original ThermoML property group is also
            accepted.
        independent_variable:
            Case-insensitive normalized substring of a reported ThermoML
            variable name, for example ``"pressure"`` or ``"temperature"``.
            Fixed constraints are retained as metadata but do not satisfy this
            filter.
        limit:
            Maximum number of datasets returned. Ranking by the number of
            matching property observations occurs before truncation.

        Returns
        -------
        tuple[DatasetMatch, ...]
            Matches sorted by descending matching observation count, followed
            by deterministic publication and dataset identifiers.

        Examples
        --------
        Search for the ten densest water/carbon-dioxide VLE datasets::

            collection.search(
                system=("H2O", "CO2"), data_type="VLE", limit=10
            )
        """
        if components is not None and system is not None:
            raise ValueError("Specify either components or system, not both.")
        if component_match not in {"exact", "contains", "within"}:
            raise ValueError("component_match must be 'exact', 'contains', or 'within'.")
        if system_match not in {"exact", "contains"}:
            raise ValueError("system_match must be 'exact' or 'contains'.")
        if limit is not None and limit < 0:
            raise ValueError("limit must be non-negative or None.")
        component_queries = (
            (components,)
            if isinstance(components, str | ComponentIdentity)
            else tuple(components or ())
        )
        system_queries = tuple(system or ())
        required_queries = tuple(required_components or ())
        if required_queries and component_match != "within":
            raise ValueError("required_components is only valid with component_match='within'.")
        if component_match == "within" and not component_queries:
            raise ValueError("component_match='within' requires components.")
        resolved_components = self._component_index.resolve_many(component_queries)
        resolved_system = self._component_index.resolve_many(system_queries)
        resolved_required = self._component_index.resolve_many(required_queries)
        queries = resolved_components or resolved_system
        component_identifiers = {item.stable_identifier for item in resolved_components}
        if any(item.stable_identifier not in component_identifiers for item in resolved_required):
            raise ValueError("required_components must be a subset of components.")
        exact = (system is not None and system_match == "exact") or (
            components is not None and component_match == "exact"
        )
        normalized_property = property_name.casefold() if property_name else None
        normalized_type = normalize_term(data_type) if data_type else None
        normalized_variable = normalize_term(independent_variable) if independent_variable else None

        matches: list[DatasetMatch] = []
        for document in self.documents:
            for dataset in document.datasets:
                compounds = document.system_compounds(dataset)
                identities = tuple(
                    ComponentIdentity.from_compound(compound) for compound in compounds
                )
                if component_match == "within" and components is not None:
                    if not all(
                        any(query.matches(identity) for query in resolved_components)
                        for identity in identities
                    ):
                        continue
                    if not all(
                        any(query.matches(identity) for identity in identities)
                        for query in resolved_required
                    ):
                        continue
                elif queries and not all(
                    any(query.matches(identity) for identity in identities) for query in queries
                ):
                    continue
                if exact and len(set(dataset.component_ids)) != len(queries):
                    continue

                selected_variables = tuple(
                    item
                    for item in dataset.variables
                    if normalized_variable and normalized_variable in normalize_term(item.name)
                )
                if independent_variable and not selected_variables:
                    continue

                selected: list[PropertyDefinition] = []
                categories: list[str] = []
                for property_definition in dataset.properties:
                    category = classify_property(property_definition, dataset)
                    if normalized_property and normalized_property not in (
                        property_definition.name.casefold()
                    ):
                        continue
                    if normalized_type and normalized_type not in {
                        normalize_term(category),
                        normalize_term(property_definition.group),
                    }:
                        continue
                    selected.append(property_definition)
                    categories.append(category)
                if (property_name or data_type) and not selected:
                    continue
                selected_numbers = tuple(item.number for item in selected)
                if not property_name and not data_type:
                    selected_numbers = tuple(item.number for item in dataset.properties)
                    categories = [classify_property(item, dataset) for item in dataset.properties]
                selected_variable_numbers = tuple(item.number for item in selected_variables)
                count = 0
                for point in dataset.points:
                    property_count = sum(
                        value.number in selected_numbers for value in point.property_values
                    )
                    if independent_variable:
                        variable_count = sum(
                            value.number in selected_variable_numbers
                            for value in point.variable_values
                        )
                        count += property_count * variable_count
                    else:
                        count += property_count
                if count == 0:
                    continue
                matches.append(
                    DatasetMatch(
                        document=document,
                        dataset=dataset,
                        matching_property_numbers=selected_numbers,
                        observation_count=count,
                        data_types=tuple(dict.fromkeys(categories)),
                        matching_variable_numbers=selected_variable_numbers,
                    )
                )
        matches.sort(
            key=lambda match: (
                -match.observation_count,
                match.document.citation.normalized_doi or match.document.provenance.sha256,
                match.dataset.number,
            )
        )
        if limit is not None:
            matches = matches[:limit]
        return tuple(matches)

    def all_matches(self) -> tuple[DatasetMatch, ...]:
        """Return every non-empty dataset ranked by observation count."""
        return self.search()
