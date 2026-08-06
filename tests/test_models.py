"""Tests for immutable scientific model behavior."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace

import pytest

from thermoml_io import Citation, Compound


def test_citation_and_provenance(document) -> None:
    assert document.schema_version == "2.0"
    assert document.citation.normalized_doi == "10.0000/thermoml-io.synthetic"
    assert document.citation.authors == ("Example, A.", "Tester, B.")
    assert document.citation.title == "Synthetic ThermoML fixture for parser verification"
    assert document.citation.publication_name == "Synthetic Thermodynamics"
    assert document.citation.year == 2026
    assert document.citation.trc_reference_id == "2026-exa-tes-0"
    assert len(document.provenance.sha256) == 64
    assert document.provenance.locator.endswith("synthetic_thermoml.xml")
    assert document.provenance.retrieved_at is None


def test_compound_identifiers_samples_and_immutability(document) -> None:
    carbon_dioxide = document.compound(1)
    water = document.compound(2)
    methanol = document.compound(3)

    assert carbon_dioxide.preferred_name == "carbon dioxide"
    assert carbon_dioxide.stable_identifier.startswith("inchikey:")
    assert carbon_dioxide.matches("CO2")
    assert carbon_dioxide.matches("co2 GAS")
    assert carbon_dioxide.matches("CURLTUGMZLYLDI-UHFFFAOYSA-N")
    assert not carbon_dioxide.matches("methane")
    assert water.matches("H2O")
    assert methanol.stable_identifier == "name:methanol"
    assert methanol.preferred_name == "methanol"

    sample = carbon_dioxide.samples[0]
    assert sample.source == "Commercial source"
    assert sample.purity[0].mole_percent_digits == 4
    assert sample.purity[0].volume_percent_digits == 3
    assert sample.purity[0].purification_methods == (
        "Other",
        "Synthetic purification",
    )
    with pytest.raises(FrozenInstanceError):
        sample.source = "changed"


def test_dataset_keys_system_types_and_counts(document) -> None:
    binary, pure, ternary = document.datasets
    assert binary.system_type == "binary"
    assert pure.system_type == "pure"
    assert ternary.system_type == "ternary"
    assert binary.observation_count == 3
    assert pure.observation_count == 2
    assert ternary.observation_count == 1
    assert document.dataset_key(binary).endswith("#pure-or-mixture-1")
    assert document.system_key(binary) == " | ".join(
        sorted((document.compound(1).stable_identifier, document.compound(2).stable_identifier))
    )
    assert tuple(item.preferred_name for item in document.system_compounds(binary)) == (
        "carbon dioxide",
        "water",
    )


def test_quantity_and_uncertainty_metadata(document) -> None:
    dataset = document.datasets[0]
    prop = dataset.properties[0]
    variable = dataset.variables[0]
    constraint = dataset.constraints[0]
    first = dataset.points[0]

    assert prop.name == "Mole fraction"
    assert prop.group == "CompositionAtPhaseEquilibrium"
    assert prop.method == "Synthetic static method"
    assert prop.phase == "Gas"
    assert prop.component_id == 1
    assert prop.repeatability[0].method == "Standard deviation of the mean"
    assert prop.device_specifications[0].description == "Synthetic analyzer"
    assert variable.name == "Pressure, kPa"
    assert variable.phase == "Liquid"
    assert constraint.name == "Temperature, K"
    assert str(constraint.value) == "298.15"
    assert constraint.significant_digits == 5
    assert str(constraint.uncertainties[0].standard_value) == "0.01"

    property_value = first.property_values[0]
    uncertainty = property_value.uncertainties[0]
    assert property_value.lexical_value == "0.10"
    assert str(property_value.value) == "0.10"
    assert property_value.significant_digits == 2
    assert str(uncertainty.standard_value) == "0.005"
    assert str(uncertainty.expanded_value) == "0.010"
    assert str(uncertainty.coverage_factor) == "2"
    assert str(uncertainty.confidence_level) == "95"
    assert uncertainty.evaluator == "Fixture author"

    variable_uncertainty = first.variable_values[0].uncertainties[0]
    assert str(variable_uncertainty.standard_value) == "1"
    assert variable_uncertainty.method == "Calibration certificate"


def test_asymmetric_uncertainty_is_retained(document) -> None:
    uncertainty = document.datasets[0].points[1].property_values[0].uncertainties[0]
    assert str(uncertainty.positive_standard_value) == "0.006"
    assert str(uncertainty.negative_standard_value) == "0.004"


def test_identifier_fallbacks_and_doi_normalization() -> None:
    assert Citation().normalized_doi is None
    assert Citation(doi="http://doi.org/10.1/ABC").normalized_doi == "10.1/abc"
    assert Citation(doi="doi:10.2/ABC").normalized_doi == "10.2/abc"
    assert Citation(doi=" 10.3/ABC ").normalized_doi == "10.3/abc"

    iupac = Compound(local_id=1, iupac_name="oxidane", standard_inchi="InChI=1S/H2O/h1H2")
    formula = Compound(local_id=2, formula="CO2", cas_registry_number="124-38-9")
    inchikey = Compound(local_id=3, standard_inchi_key="AAAA")
    anonymous = Compound(local_id=4)
    assert iupac.preferred_name == "oxidane"
    assert iupac.stable_identifier.startswith("inchi:")
    assert formula.preferred_name == "CO2"
    assert formula.stable_identifier == "cas:124-38-9"
    assert inchikey.preferred_name == "AAAA"
    assert anonymous.preferred_name == "component-4"
    assert not anonymous.matches("unreported")


def test_higher_order_system_types(document) -> None:
    dataset = document.datasets[2]
    assert replace(dataset, component_ids=(1, 2, 3, 4)).system_type == "quaternary"
    assert replace(dataset, component_ids=(1, 2, 3, 4, 5)).system_type == "other"
