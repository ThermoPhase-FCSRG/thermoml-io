"""Component alias aggregation and ambiguity-safety tests."""

from __future__ import annotations

import pytest

from thermoml_io import (
    AmbiguousComponentError,
    ComponentIdentity,
    ComponentIndex,
    ComponentNotFoundError,
    Compound,
)
from thermoml_io.identity import explicit_component_identity


def _identity(
    name: str,
    *,
    formula: str | None = None,
    inchikey: str | None = None,
    inchi: str | None = None,
    cas: str | None = None,
) -> ComponentIdentity:
    return ComponentIdentity(
        preferred_name=name,
        common_names=(name,),
        formulas=(formula,) if formula else (),
        standard_inchis=(inchi,) if inchi else (),
        standard_inchi_keys=(inchikey,) if inchikey else (),
        cas_registry_numbers=(cas,) if cas else (),
    )


def test_collection_index_resolves_friendly_and_namespaced_queries(collection) -> None:
    water = collection.resolve_component("  WATER ")
    assert water.preferred_name == "water"
    assert collection.resolve_component("formula:H2O") == water
    assert collection.resolve_component("common-name:water") == water
    assert collection.resolve_component("inchi-key:XLYOFNOQVPJJNP-UHFFFAOYSA-N") == water

    carbon_dioxide = collection.resolve_component("iupac:carbon dioxide")
    assert collection.resolve_component("cas-name:carbon dioxide") == carbon_dioxide
    assert collection.resolve_component("name:CO2 gas") == carbon_dioxide
    assert carbon_dioxide.stable_identifier.startswith("inchikey:")


def test_identity_from_compound_and_identifier_fallbacks() -> None:
    compound = Compound(
        local_id=1,
        common_names=("  example   compound ", "Example Compound"),
        iupac_name="systematic name",
        cas_name="CAS name",
        formula="C2H6O",
        standard_inchi="InChI=1S/C2H6O",
        standard_inchi_key="KEY",
        cas_registry_number="1-23-4",
    )
    identity = ComponentIdentity.from_compound(compound)
    assert identity.common_names == ("example compound",)
    assert identity.iupac_names == ("systematic name",)
    assert identity.cas_names == ("CAS name",)
    assert identity.formulas == ("C2H6O",)
    assert identity.standard_inchis == ("InChI=1S/C2H6O",)
    assert identity.standard_inchi_keys == ("KEY",)
    assert identity.cas_registry_numbers == ("1-23-4",)
    blank_alias = ComponentIdentity.from_compound(
        Compound(local_id=2, common_names=("   ",), formula="X")
    )
    assert blank_alias.common_names == ()

    assert _identity("inchi", inchi="InChI=1S/X").stable_identifier.startswith("inchi:")
    assert _identity("cas", cas="1-23-4").stable_identifier == "cas:1-23-4"
    assert _identity("name").stable_identifier == "name:name"


def test_shared_identifiers_merge_aliases_but_conflicts_do_not() -> None:
    first = ComponentIdentity(
        preferred_name="water",
        common_names=("water",),
        standard_inchi_keys=("WATER-KEY",),
        cas_registry_numbers=("7732-18-5",),
        pubchem_cids=(962,),
    )
    bridged = ComponentIdentity(
        preferred_name="oxidane",
        iupac_names=("oxidane",),
        cas_registry_numbers=("7732-18-5",),
        pubchem_cids=(962, 123),
    )
    weak = ComponentIdentity(preferred_name="water", common_names=("water",))
    index = ComponentIndex.from_identities((first, bridged, weak))
    assert len(index.identities) == 1
    water = index.resolve("oxidane")
    assert water.common_names == ("water",)
    assert water.iupac_names == ("oxidane",)
    assert water.pubchem_cids == (123, 962)
    assert index.resolve("cid:962") == water

    normal = _identity("butane", formula="C4H10", inchikey="NORMAL")
    branched = _identity("isobutane", formula="C4H10", inchikey="BRANCHED")
    ambiguous = ComponentIndex.from_identities((normal, branched))
    with pytest.raises(AmbiguousComponentError, match=r"C4H10.*NORMAL"):
        ambiguous.resolve("formula:C4H10")
    assert ambiguous.resolve("name:butane") == normal


def test_identity_matching_prefers_strong_identifiers() -> None:
    water = _identity("water", formula="H2O", inchikey="WATER")
    alias = _identity("oxidane", inchikey="WATER")
    conflicting = _identity("water", formula="H2O", inchikey="OTHER")
    weak_alias = ComponentIdentity(preferred_name="water", common_names=("water",))
    unrelated = ComponentIdentity(preferred_name="methane", common_names=("methane",))
    assert water.matches(alias)
    assert not water.matches(conflicting)
    assert water.matches(weak_alias)
    assert not water.matches(unrelated)


def test_resolution_failures_and_duplicate_queries(collection) -> None:
    with pytest.raises(ComponentNotFoundError, match="No indexed component"):
        collection.resolve_component("does-not-exist")
    with pytest.raises(ComponentNotFoundError):
        collection.resolve_component("unknown-prefix:water")
    with pytest.raises(ValueError, match="must not be empty"):
        collection.resolve_component("  ")
    with pytest.raises(ValueError, match="no identifier value"):
        collection.resolve_component("cas:")
    with pytest.raises(ValueError, match="duplicate"):
        collection.component_index.resolve_many(("water", "formula:H2O"))

    detached = _identity("external", inchikey="EXTERNAL")
    assert ComponentIndex(()).resolve(detached) is detached


def test_explicit_strong_identifiers_do_not_require_an_alias_index() -> None:
    raw_key = explicit_component_identity("AAAAAAAAAAAAAA-BBBBBBBBBB-C")
    prefixed_key = explicit_component_identity("inchikey:AAAAAAAAAAAAAA-BBBBBBBBBB-C")
    inchi = explicit_component_identity("InChI=1S/H2O/h1H2")
    prefixed_inchi = explicit_component_identity("inchi:InChI=1S/H2O/h1H2")
    cas = explicit_component_identity("7732-18-5")
    prefixed_cas = explicit_component_identity("cas:7732-18-5")
    assert raw_key == prefixed_key
    assert raw_key is not None and raw_key.standard_inchi_keys
    assert inchi == prefixed_inchi
    assert inchi is not None and inchi.standard_inchis
    assert cas == prefixed_cas
    assert cas is not None and cas.cas_registry_numbers == ("7732-18-5",)
    assert explicit_component_identity("formula:H2O") is None
    assert explicit_component_identity("water") is None
    assert explicit_component_identity("cid:962") is None


def test_preferred_name_fallbacks_are_deterministic() -> None:
    iupac = ComponentIdentity(preferred_name="z", iupac_names=("IUPAC",))
    cas_name = ComponentIdentity(preferred_name="z", cas_names=("CAS name",))
    formula = ComponentIdentity(preferred_name="z", formulas=("CH4",))
    anonymous = ComponentIdentity(preferred_name="z")
    assert ComponentIndex.from_identities((iupac,)).identities[0].preferred_name == "IUPAC"
    assert ComponentIndex.from_identities((cas_name,)).identities[0].preferred_name == "CAS name"
    assert ComponentIndex.from_identities((formula,)).identities[0].preferred_name == "CH4"
    assert ComponentIndex.from_identities((anonymous,)).identities[0].preferred_name == "z"
    assert ComponentIndex.from_identities(()).identities == ()
