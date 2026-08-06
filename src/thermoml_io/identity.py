"""Chemical-identity aggregation and explicit component resolution.

ThermoML compound metadata remain immutable. This module builds a separate
index that connects reported aliases through shared structural or registry
identifiers and refuses to choose silently when a query remains ambiguous.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Literal, TypeAlias

from .errors import AmbiguousComponentError, ComponentNotFoundError
from .models import Compound, ThermoMLDocument

IdentifierKind = Literal[
    "auto",
    "name",
    "common",
    "iupac",
    "cas-name",
    "formula",
    "cas",
    "inchi",
    "inchikey",
    "cid",
]

_PREFIXES: dict[str, IdentifierKind] = {
    "name": "name",
    "common": "common",
    "common-name": "common",
    "iupac": "iupac",
    "iupac-name": "iupac",
    "cas-name": "cas-name",
    "formula": "formula",
    "cas": "cas",
    "inchi": "inchi",
    "inchikey": "inchikey",
    "inchi-key": "inchikey",
    "cid": "cid",
    "pubchem-cid": "cid",
}


def _normalize(value: str) -> str:
    return " ".join(value.strip().casefold().split())


def _unique(values: Iterable[str]) -> tuple[str, ...]:
    by_normalized: dict[str, str] = {}
    for value in values:
        cleaned = " ".join(value.strip().split())
        if cleaned:
            by_normalized.setdefault(_normalize(cleaned), cleaned)
    return tuple(by_normalized[key] for key in sorted(by_normalized))


def _parse_query(query: str) -> tuple[IdentifierKind, str]:
    cleaned = query.strip()
    if not cleaned:
        raise ValueError("Component queries must not be empty.")
    prefix, separator, value = cleaned.partition(":")
    kind = _PREFIXES.get(prefix.casefold()) if separator else None
    if kind is None:
        return "auto", cleaned
    if not value.strip():
        raise ValueError(f"Component query {query!r} has no identifier value.")
    return kind, value.strip()


def explicit_component_identity(query: str) -> ComponentIdentity | None:
    """Return a detached identity for a self-identifying strong query.

    This helper avoids an archive-wide alias scan for explicit CAS, InChI, or
    InChIKey queries. Names and formulas return ``None`` because they require
    ambiguity checks against the indexed source.
    """
    kind, value = _parse_query(query)
    if kind == "auto":
        if value.casefold().startswith("inchi="):
            kind = "inchi"
        elif re.fullmatch(r"[A-Za-z]{14}-[A-Za-z]{10}-[A-Za-z]", value):
            kind = "inchikey"
        elif re.fullmatch(r"\d{2,7}-\d{2}-\d", value):
            kind = "cas"
    if kind == "inchi":
        return ComponentIdentity(preferred_name=value, standard_inchis=(value,))
    if kind == "inchikey":
        return ComponentIdentity(preferred_name=value, standard_inchi_keys=(value,))
    if kind == "cas":
        return ComponentIdentity(preferred_name=value, cas_registry_numbers=(value,))
    return None


@dataclass(frozen=True, slots=True)
class ComponentIdentity:
    """One resolved chemical identity with all known exact aliases.

    Parameters
    ----------
    preferred_name:
        Human-readable label selected from the reported names or formula.
    common_names, iupac_names, cas_names:
        Exact names observed in ThermoML or returned by an explicit resolver.
    formulas:
        Reported molecular formulas. Formulas are aliases, not assumed unique.
    standard_inchis, standard_inchi_keys, cas_registry_numbers:
        Strong identifiers used to connect aliases across documents.
    pubchem_cids:
        Optional PubChem compound identifiers supplied only by explicit
        PubChem resolution.

    Notes
    -----
    This object is separate from :class:`~thermoml_io.models.Compound`; it does
    not mutate or replace source-reported ThermoML metadata.
    """

    preferred_name: str
    common_names: tuple[str, ...] = ()
    iupac_names: tuple[str, ...] = ()
    cas_names: tuple[str, ...] = ()
    formulas: tuple[str, ...] = ()
    standard_inchis: tuple[str, ...] = ()
    standard_inchi_keys: tuple[str, ...] = ()
    cas_registry_numbers: tuple[str, ...] = ()
    pubchem_cids: tuple[int, ...] = ()

    @classmethod
    def from_compound(cls, compound: Compound) -> ComponentIdentity:
        """Create a detached identity from one source-reported compound."""
        return cls(
            preferred_name=compound.preferred_name,
            common_names=_unique(compound.common_names),
            iupac_names=_unique((compound.iupac_name,) if compound.iupac_name else ()),
            cas_names=_unique((compound.cas_name,) if compound.cas_name else ()),
            formulas=_unique((compound.formula,) if compound.formula else ()),
            standard_inchis=_unique((compound.standard_inchi,) if compound.standard_inchi else ()),
            standard_inchi_keys=_unique(
                (compound.standard_inchi_key,) if compound.standard_inchi_key else ()
            ),
            cas_registry_numbers=_unique(
                (compound.cas_registry_number,) if compound.cas_registry_number else ()
            ),
        )

    @property
    def stable_identifier(self) -> str:
        """Return the strongest deterministic identifier available."""
        if self.standard_inchi_keys:
            return f"inchikey:{self.standard_inchi_keys[0].upper()}"
        if self.standard_inchis:
            return f"inchi:{self.standard_inchis[0]}"
        if self.cas_registry_numbers:
            return f"cas:{self.cas_registry_numbers[0]}"
        return f"name:{_normalize(self.preferred_name)}"

    def values(self, kind: IdentifierKind = "auto") -> tuple[str, ...]:
        """Return exact identifier values considered for one query kind."""
        names = (*self.common_names, *self.iupac_names, *self.cas_names)
        mapping: dict[IdentifierKind, tuple[str, ...]] = {
            "name": names,
            "common": self.common_names,
            "iupac": self.iupac_names,
            "cas-name": self.cas_names,
            "formula": self.formulas,
            "cas": self.cas_registry_numbers,
            "inchi": self.standard_inchis,
            "inchikey": self.standard_inchi_keys,
            "cid": tuple(str(value) for value in self.pubchem_cids),
            "auto": (
                *names,
                *self.formulas,
                *self.cas_registry_numbers,
                *self.standard_inchis,
                *self.standard_inchi_keys,
                *(str(value) for value in self.pubchem_cids),
            ),
        }
        return mapping[kind]

    def matches(self, other: ComponentIdentity) -> bool:
        """Return whether ``other`` is compatible with this resolved identity.

        Shared strong identifiers decide first. If both sides report strong
        identifiers and none agree, aliases are not allowed to override that
        chemical conflict. Exact aliases are used only when at least one side
        lacks strong identity metadata.
        """
        strong_self = self._strong_tokens()
        strong_other = other._strong_tokens()
        if strong_self & strong_other:
            return True
        if strong_self and strong_other:
            return False
        aliases_self = {_normalize(value) for value in self.values("auto")}
        aliases_other = {_normalize(value) for value in other.values("auto")}
        return bool(aliases_self & aliases_other)

    def _strong_tokens(self) -> frozenset[tuple[str, str]]:
        return frozenset(
            (
                *(("inchikey", _normalize(value)) for value in self.standard_inchi_keys),
                *(("inchi", _normalize(value)) for value in self.standard_inchis),
                *(("cas", _normalize(value)) for value in self.cas_registry_numbers),
            )
        )


ComponentQuery: TypeAlias = str | ComponentIdentity


def _merge_identities(identities: Iterable[ComponentIdentity]) -> ComponentIdentity:
    values = tuple(identities)
    common_names = _unique(value for item in values for value in item.common_names)
    iupac_names = _unique(value for item in values for value in item.iupac_names)
    cas_names = _unique(value for item in values for value in item.cas_names)
    formulas = _unique(value for item in values for value in item.formulas)
    inchis = _unique(value for item in values for value in item.standard_inchis)
    inchikeys = _unique(value for item in values for value in item.standard_inchi_keys)
    cas_numbers = _unique(value for item in values for value in item.cas_registry_numbers)
    cids = tuple(sorted({value for item in values for value in item.pubchem_cids}))
    if common_names:
        preferred = common_names[0]
    elif iupac_names:
        preferred = iupac_names[0]
    elif cas_names:
        preferred = cas_names[0]
    elif formulas:
        preferred = formulas[0]
    else:
        preferred = min(
            (item.preferred_name for item in values), key=lambda value: _normalize(value)
        )
    return ComponentIdentity(
        preferred_name=preferred,
        common_names=common_names,
        iupac_names=iupac_names,
        cas_names=cas_names,
        formulas=formulas,
        standard_inchis=inchis,
        standard_inchi_keys=inchikeys,
        cas_registry_numbers=cas_numbers,
        pubchem_cids=cids,
    )


@dataclass(frozen=True, slots=True)
class ComponentIndex:
    """Immutable alias index for resolving components without guessing."""

    identities: tuple[ComponentIdentity, ...]
    _lookup: dict[tuple[IdentifierKind, str], tuple[ComponentIdentity, ...]] = field(
        init=False, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        lookup: defaultdict[tuple[IdentifierKind, str], list[ComponentIdentity]] = defaultdict(list)
        kinds: tuple[IdentifierKind, ...] = (
            "auto",
            "name",
            "common",
            "iupac",
            "cas-name",
            "formula",
            "cas",
            "inchi",
            "inchikey",
            "cid",
        )
        for identity in self.identities:
            for kind in kinds:
                for value in identity.values(kind):
                    key = (kind, _normalize(value))
                    if identity not in lookup[key]:
                        lookup[key].append(identity)
        object.__setattr__(
            self,
            "_lookup",
            {
                key: tuple(sorted(values, key=lambda item: item.stable_identifier))
                for key, values in lookup.items()
            },
        )

    @classmethod
    def from_documents(cls, documents: Iterable[ThermoMLDocument]) -> ComponentIndex:
        """Build an index from source compounds across several documents."""
        return cls.from_identities(
            ComponentIdentity.from_compound(compound)
            for document in documents
            for compound in document.compounds
        )

    @classmethod
    def from_identities(cls, identities: Iterable[ComponentIdentity]) -> ComponentIndex:
        """Connect aliases only through shared strong identifiers.

        Records without InChIKey, InChI, or CAS number may join a strong group
        when their aliases identify exactly one such group. If two strong
        identities share a name or formula, they remain separate so resolution
        reports the ambiguity.
        """
        records = tuple(identities)
        if not records:
            return cls(())
        parent = list(range(len(records)))

        def find(index: int) -> int:
            while parent[index] != index:
                parent[index] = parent[parent[index]]
                index = parent[index]
            return index

        def union(left: int, right: int) -> None:
            left_root = find(left)
            right_root = find(right)
            if left_root != right_root:
                parent[right_root] = left_root

        strong_owner: dict[tuple[str, str], int] = {}
        weak_owner: dict[str, int] = {}
        for index, identity in enumerate(records):
            strong = identity._strong_tokens()
            for token in strong:
                owner = strong_owner.setdefault(token, index)
                union(index, owner)
            if not strong:
                owner = weak_owner.setdefault(identity.stable_identifier, index)
                union(index, owner)

        initial_groups: defaultdict[int, list[int]] = defaultdict(list)
        for index in range(len(records)):
            initial_groups[find(index)].append(index)
        strong_groups = {
            root: _merge_identities(records[index] for index in members)
            for root, members in initial_groups.items()
            if any(records[index]._strong_tokens() for index in members)
        }
        strong_aliases = {
            root: {_normalize(value) for value in identity.values("auto")}
            for root, identity in strong_groups.items()
        }
        for root, members in initial_groups.items():
            if root in strong_groups:
                continue
            aliases = {
                _normalize(value) for index in members for value in records[index].values("auto")
            }
            candidates = [
                strong_root
                for strong_root, candidate_aliases in strong_aliases.items()
                if aliases & candidate_aliases
            ]
            if len(candidates) == 1:
                union(root, candidates[0])

        groups: defaultdict[int, list[ComponentIdentity]] = defaultdict(list)
        for index, identity in enumerate(records):
            groups[find(index)].append(identity)
        merged = tuple(
            sorted(
                (_merge_identities(group) for group in groups.values()),
                key=lambda item: item.stable_identifier,
            )
        )
        return cls(merged)

    def resolve(self, query: ComponentQuery) -> ComponentIdentity:
        """Resolve one query or raise an explicit not-found/ambiguity error."""
        if isinstance(query, ComponentIdentity):
            return query
        kind, value = _parse_query(query)
        candidates = self._lookup.get((kind, _normalize(value)), ())
        if not candidates:
            raise ComponentNotFoundError(
                f"No indexed component matches {query!r}. Use an exact reported name, "
                "formula, CAS number, InChI, or InChIKey."
            )
        if len(candidates) > 1:
            labels = ", ".join(
                f"{item.preferred_name} [{item.stable_identifier}]" for item in candidates
            )
            raise AmbiguousComponentError(
                f"Component query {query!r} is ambiguous: {labels}. "
                "Use a CAS number, InChI, or InChIKey."
            )
        return candidates[0]

    def resolve_many(self, queries: Iterable[ComponentQuery]) -> tuple[ComponentIdentity, ...]:
        """Resolve several queries and reject duplicate chemical identities."""
        resolved = tuple(self.resolve(query) for query in queries)
        stable = [item.stable_identifier for item in resolved]
        if len(set(stable)) != len(stable):
            raise ValueError("Component queries resolve to duplicate chemical identities.")
        return resolved


def component_query_label(query: ComponentQuery) -> str:
    """Return a stable user-facing representation of a component query."""
    return query if isinstance(query, str) else query.stable_identifier
