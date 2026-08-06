"""Search, ranking, truncation, and classification tests."""

from __future__ import annotations

from dataclasses import replace

import pytest

import thermoml_io.collection as collection_module
from thermoml_io import ThermoMLCollection, classify_property


def test_classification(document) -> None:
    binary, pure, ternary = document.datasets
    assert classify_property(binary.properties[0], binary) == "VLE"
    assert classify_property(pure.properties[0], pure) == "volumetric"
    assert classify_property(ternary.properties[0], ternary) == "interfacial, optical, and acoustic"


def test_phase_equilibrium_classification_variants(document) -> None:
    dataset = document.datasets[0]
    prop = replace(dataset.properties[0], phase=None)
    assert classify_property(prop, replace(dataset, phases=("Solid", "Liquid"))) == "SLE"
    assert classify_property(prop, replace(dataset, phases=("Liquid 1", "Liquid 2"))) == "LLE"
    assert (
        classify_property(prop, replace(dataset, phases=("Supercritical",))) == "phase equilibrium"
    )
    assert classify_property(replace(prop, group="UnmappedGroup"), dataset) == "UnmappedGroup"


def test_exact_system_search_is_order_independent_and_ranked(collection) -> None:
    forward = collection.search(system=("H2O", "CO2"), data_type="VLE")
    reverse = collection.search(system=("carbon dioxide", "water"), data_type="VLE")
    assert tuple(item.dataset_key for item in forward) == tuple(
        item.dataset_key for item in reverse
    )
    assert len(forward) == 1
    assert forward[0].observation_count == 3
    assert forward[0].data_types == ("VLE",)


def test_component_and_contains_search(collection) -> None:
    by_component = collection.search(components=("H2O",))
    assert [match.dataset.number for match in by_component] == [1, 2, 3]
    assert [match.observation_count for match in by_component] == [3, 2, 1]
    contains = collection.search(system=("H2O", "CO2"), system_match="contains", limit=2)
    assert [match.dataset.number for match in contains] == [1, 3]


def test_component_match_modes_and_required_subset(collection) -> None:
    exact_pure = collection.search(components="H2O", component_match="exact")
    assert [match.dataset.number for match in exact_pure] == [2]

    within = collection.search(
        components=("H2O", "CO2"),
        required_components=("H2O",),
        component_match="within",
    )
    assert [match.dataset.number for match in within] == [1, 2]

    optional_methanol = collection.search(
        components=("H2O", "CO2", "methanol"),
        required_components=("H2O", "CO2"),
        component_match="within",
    )
    assert [match.dataset.number for match in optional_methanol] == [1, 3]


def test_independent_variable_filter_builds_relationship_count(collection) -> None:
    pressure = collection.search(
        components=("H2O", "CO2"),
        component_match="exact",
        data_type="VLE",
        property_name="mole fraction",
        independent_variable="pressure",
    )
    assert len(pressure) == 1
    assert pressure[0].matching_variable_numbers == (1,)
    assert pressure[0].observation_count == 3
    assert (
        collection.search(
            components=("H2O", "CO2"),
            component_match="exact",
            independent_variable="temperature",
        )
        == ()
    )


def test_property_and_group_search(collection) -> None:
    density = collection.search(property_name="DENSITY")
    assert len(density) == 1
    assert density[0].matching_property_numbers == (1,)
    assert density[0].observation_count == 2
    assert collection.search(data_type="VolumetricProp") == density
    assert collection.search(data_type="transport") == ()


def test_limit_is_applied_after_density_ranking(collection) -> None:
    assert collection.search(components=("H2O",), limit=0) == ()
    top = collection.search(components=("H2O",), limit=1)
    assert len(top) == 1
    assert top[0].dataset.number == 1
    assert top[0].observation_count == 3


def test_search_validation(collection) -> None:
    with pytest.raises(ValueError, match="either components or system"):
        collection.search(components=("H2O",), system=("H2O",))
    with pytest.raises(ValueError, match="system_match"):
        collection.search(system=("H2O",), system_match="bad")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="non-negative"):
        collection.search(limit=-1)
    with pytest.raises(ValueError, match="component_match"):
        collection.search(components="H2O", component_match="bad")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="only valid"):
        collection.search(components="H2O", required_components=("H2O",))
    with pytest.raises(ValueError, match="requires components"):
        collection.search(component_match="within")
    with pytest.raises(ValueError, match="subset"):
        collection.search(
            components=("H2O", "CO2"),
            required_components=("methanol",),
            component_match="within",
        )


def test_from_urls_delegates_to_loader(monkeypatch, document) -> None:
    seen = []

    def fake_loader(url, *, timeout, max_bytes):
        seen.append((url, timeout, max_bytes))
        return document

    monkeypatch.setattr(collection_module, "load_thermoml_url", fake_loader)
    collection = ThermoMLCollection.from_urls(
        ["https://one.invalid", "https://two.invalid"], timeout=5, max_bytes=123
    )
    assert len(collection.documents) == 2
    assert seen == [
        ("https://one.invalid", 5, 123),
        ("https://two.invalid", 5, 123),
    ]


def test_search_skips_selected_properties_without_observations(document) -> None:
    dataset = replace(document.datasets[0], points=())
    empty = ThermoMLCollection((replace(document, datasets=(dataset,)),))
    assert empty.search(data_type="VLE") == ()
