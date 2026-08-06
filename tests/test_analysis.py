"""Tests for collection-level descriptive rankings."""

from __future__ import annotations

from dataclasses import replace

import pytest

from thermoml_io import ThermoMLCollection, summarize_collection, summarize_documents


def test_summary_counts_and_rankings(collection) -> None:
    summary = summarize_collection(collection)
    assert summary.document_count == 1
    assert summary.dataset_count == 3
    assert summary.data_point_count == 6
    assert summary.observation_count == 6
    assert summary.reaction_dataset_count == 0
    assert summary.system_types[0].label == "binary"
    assert summary.system_types[0].count == 3
    assert summary.dataset_system_types[0].label == "binary"
    assert summary.dataset_system_types[0].count == 1
    assert summary.data_types[0].label == "VLE"
    assert summary.property_groups[0].label == "CompositionAtPhaseEquilibrium"
    assert summary.properties[0].label == "Mole fraction"
    assert summary.components[0].label == "water"
    assert summary.components[0].count == 6
    assert summary.methods[0].label == "Synthetic static method"
    assert summary.publications[0].count == 6
    assert len(summary.top("systems", 2)) == 2
    assert summarize_documents(iter(collection.documents)) == summary


def test_summary_top_validation(collection) -> None:
    summary = summarize_collection(collection)
    with pytest.raises(ValueError, match="non-negative"):
        summary.top("systems", -1)
    with pytest.raises(ValueError, match="not a ranking"):
        summary.top("document_count")


def test_summary_allows_unreported_method(document) -> None:
    dataset = document.datasets[0]
    property_definition = replace(dataset.properties[0], method=None)
    modified = replace(
        document,
        datasets=(replace(dataset, properties=(property_definition,)),),
    )
    summary = summarize_collection(ThermoMLCollection((modified,)))
    assert summary.methods == ()


def test_summary_allows_property_definition_without_observations(document) -> None:
    dataset = replace(document.datasets[0], points=())
    modified = replace(document, datasets=(dataset,))
    summary = summarize_collection(ThermoMLCollection((modified,)))
    assert summary.document_count == 1
    assert summary.dataset_count == 1
    assert summary.observation_count == 0
