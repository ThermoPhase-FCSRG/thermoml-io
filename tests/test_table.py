"""Tests for long-form table construction and all export formats."""

from __future__ import annotations

import csv
import json
from dataclasses import replace
from pathlib import Path

import pyarrow.parquet as pq
import pytest
import yaml

import thermoml_io.table as table_module
from thermoml_io import (
    ExperimentalTable,
    OptionalDependencyError,
    ThermoMLCollection,
    build_analysis_table,
    build_experimental_table,
    build_property_table,
)


def test_build_complete_and_filtered_table(collection) -> None:
    table = build_experimental_table(collection)
    assert len(table.rows) == 6
    records = table.to_records()
    assert records[0]["doi"] == "10.0000/thermoml-io.synthetic"
    assert records[0]["source_media_type"] == "application/xml"
    assert records[0]["source_retrieved_at"] is None
    assert records[0]["source_warnings_json"] == "[]"
    assert records[0]["citation_authors"] == "Example, A. | Tester, B."
    assert records[0]["citation_authors_year"] == "Example & Tester (2026)"
    assert "Synthetic ThermoML fixture" in records[0]["citation_apa"]
    assert records[0]["citation_bibtex"].startswith("@article{example2026_")
    assert records[0]["publication_name"] == "Synthetic Thermodynamics"
    assert records[0]["dataset_purpose"] == "Principal objective of the work"
    assert records[0]["dataset_phases"] == "Liquid | Gas"
    assert records[0]["data_type"] == "VLE"
    assert records[0]["value"] == "0.10"
    assert records[0]["property_component"] == "carbon dioxide"
    assert "0.005" in records[0]["uncertainties_json"]
    assert "Pressure, kPa" in records[0]["variables_json"]
    assert "Temperature, K" in records[0]["constraints_json"]
    assert "Commercial source" in records[0]["samples_json"]
    assert "Synthetic analyzer" in records[0]["property_device_specifications_json"]
    assert "Standard deviation of the mean" in records[0]["property_repeatability_json"]

    matches = collection.search(system=("H2O", "CO2"), data_type="VLE")
    filtered = build_experimental_table(collection, matches=matches)
    assert len(filtered.rows) == 3


def test_csv_json_yaml_and_parquet_exports(collection, tmp_path: Path) -> None:
    table = build_experimental_table(collection)
    csv_path = table.write(tmp_path / "table.csv")
    with csv_path.open(encoding="utf-8", newline="") as stream:
        csv_rows = list(csv.DictReader(stream))
    assert len(csv_rows) == 6
    assert csv_rows[0]["value"] == "0.10"

    json_path = table.write(tmp_path / "table.json")
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["schema"] == "thermoml-io.experimental-table.v1"
    assert len(payload["rows"]) == 6

    yaml_path = table.write(tmp_path / "table.yml")
    yaml_payload = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    assert yaml_payload["rows"][0]["value"] == "0.10"

    parquet_path = table.write(tmp_path / "table.parquet")
    parquet = pq.read_table(parquet_path)
    assert parquet.num_rows == 6
    assert parquet.schema.metadata[b"thermoml_io_schema"] == b"experimental-table.v1"


def test_explicit_format_and_invalid_format(collection, tmp_path: Path) -> None:
    table = build_experimental_table(collection)
    output = table.write(tmp_path / "table.data", format="json")
    assert output.exists()
    with pytest.raises(ValueError, match="Unsupported table format"):
        table.write(tmp_path / "table.bad")


def test_to_pandas(collection) -> None:
    table = build_experimental_table(collection)
    frame = table.to_pandas()
    assert frame.shape == (6, len(table.columns))


def test_property_relation_table_flattens_selected_condition(collection) -> None:
    matches = collection.search(
        components=("CO2", "H2O"),
        component_match="exact",
        data_type="VLE",
        property_name="mole fraction",
        independent_variable="pressure",
    )
    table = build_property_table(collection, matches=matches)
    records = table.to_records()
    assert len(records) == 3
    assert records[0]["independent_variable_name"] == "Pressure, kPa"
    assert records[0]["independent_variable_value"] == "1000"
    assert records[0]["doi"] == "10.0000/thermoml-io.synthetic"
    assert "Temperature, K" in records[0]["constraints_json"]
    assert '"number": 1' in records[0]["variables_json"]
    complementary = json.loads(records[0]["complementary_conditions_json"])
    assert complementary[0]["source"] == "constraint"
    assert complementary[0]["name"] == "Temperature, K"

    with pytest.raises(ValueError, match="independent_variable"):
        build_property_table(collection, matches=collection.search(data_type="VLE"))


def test_analysis_table_promotes_physical_columns_and_keeps_metadata(collection) -> None:
    matches = collection.search(
        components=("CO2", "H2O"),
        component_match="exact",
        data_type="VLE",
        property_name="mole fraction",
        independent_variable="pressure",
    )
    lossless = build_property_table(collection, matches=matches)
    analysis = build_analysis_table(lossless)
    assert analysis.schema == "thermoml-io.analysis-table.v1"
    assert analysis.columns == (
        "Temperature, K",
        "Pressure, kPa",
        "Mole fraction",
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
    first = analysis.to_records()[0]
    assert first["Temperature, K"] == "298.15"
    assert first["Pressure, kPa"] == "1000"
    assert first["Mole fraction"] == "0.10"
    assert first["DOI"] == "10.0000/thermoml-io.synthetic"
    assert first["Authors/Year"] == "Example & Tester (2026)"
    assert first["System"] == "carbon dioxide + water"
    assert first["Method"] == "Synthetic static method"
    metadata = json.loads(str(first["metadata"]))
    assert metadata["publication"]["apa"].startswith("Example, A.")
    assert metadata["publication"]["bibtex"].startswith("@article{")
    assert metadata["publication"]["doi"] == "10.0000/thermoml-io.synthetic"
    assert metadata["source"]["media_type"] == "application/xml"
    assert metadata["property"]["uncertainties"][0]["standard_value"] == "0.005"
    assert metadata["conditions"][0]["role"] == "independent"
    assert metadata["conditions"][1]["source"] == "constraint"


def test_analysis_table_qualifies_ambiguous_conditions(document) -> None:
    dataset = document.datasets[0]
    pressure = dataset.variables[0]
    temperature = replace(pressure, number=2, name="Temperature, K")
    points = tuple(
        replace(
            point,
            variable_values=(
                *point.variable_values,
                replace(point.variable_values[0], number=2),
            ),
        )
        for point in dataset.points
    )
    expanded = replace(dataset, variables=(pressure, temperature), points=points)
    selected = ThermoMLCollection((replace(document, datasets=(expanded,)),))
    matches = selected.search(data_type="VLE", independent_variable="pressure")
    analysis = build_analysis_table(build_property_table(selected, matches=matches))
    assert "Temperature, K [variable; phase=Liquid]" in analysis.columns
    assert "Temperature, K [constraint; phase=Liquid]" in analysis.columns


def test_analysis_table_rejects_non_relation_table_and_invalid_json(collection) -> None:
    with pytest.raises(ValueError, match="property-condition"):
        build_analysis_table(build_experimental_table(collection))

    matches = collection.search(data_type="VLE", independent_variable="pressure")
    relation = build_property_table(collection, matches=matches)
    records = relation.to_records()
    records[0]["complementary_conditions_json"] = "{}"
    malformed = ExperimentalTable(
        relation.columns,
        tuple(tuple(record[column] for column in relation.columns) for record in records),
    )
    with pytest.raises(ValueError, match="JSON list"):
        build_analysis_table(malformed)

    records[0]["complementary_conditions_json"] = None
    non_text = ExperimentalTable(
        relation.columns,
        tuple(tuple(record[column] for column in relation.columns) for record in records),
    )
    with pytest.raises(ValueError, match="serialized JSON text"):
        build_analysis_table(non_text)

    assert table_module._decoded_object_or_none({"x": None}, "x") is None
    with pytest.raises(ValueError, match="text or null"):
        table_module._decoded_object_or_none({"x": 1}, "x")
    with pytest.raises(ValueError, match="JSON object"):
        table_module._decoded_object_or_none({"x": "[]"}, "x")
    assert table_module._decoded_string_list({"x": '["warning"]'}, "x") == ["warning"]
    with pytest.raises(ValueError, match="JSON list of strings"):
        table_module._decoded_string_list({"x": "[1]"}, "x")


def test_analysis_table_labels_and_explicit_semantic_failures(collection) -> None:
    assert table_module._condition_sort_key("Mole fraction, 1")[0] == 2
    assert table_module._condition_sort_key("Electric field, V/m")[0] == 3

    condition_signatures = {
        "Mole fraction, 1": {
            ("variable", "unspecified", "water"),
            ("variable", "unspecified", "carbon dioxide"),
        }
    }
    assert (
        table_module._condition_label(
            "Mole fraction, 1",
            ("variable", "unspecified", "water"),
            condition_signatures,
        )
        == "Mole fraction, 1 [variable; component=water]"
    )
    property_signatures = {"Density, kg/m3": {("Liquid", "unspecified"), ("Gas", "unspecified")}}
    assert (
        table_module._property_label("Density, kg/m3", ("Gas", "unspecified"), property_signatures)
        == "Density, kg/m3 [phase=Gas; component=unspecified]"
    )

    matches = collection.search(data_type="VLE", independent_variable="pressure")
    relation = build_property_table(collection, matches=matches)

    def modified_table(**updates) -> ExperimentalTable:
        records = relation.to_records()
        records[0].update(updates)
        return ExperimentalTable(
            relation.columns,
            tuple(tuple(record[column] for column in relation.columns) for record in records),
        )

    with pytest.raises(ValueError, match="Independent-variable names"):
        build_analysis_table(modified_table(independent_variable_name=None))
    with pytest.raises(ValueError, match="Condition names"):
        build_analysis_table(modified_table(complementary_conditions_json='[{"name": null}]'))
    with pytest.raises(ValueError, match="Property names"):
        build_analysis_table(modified_table(property_name=None))

    first = relation.to_records()[0]
    duplicate = {
        "source": "variable",
        "name": first["independent_variable_name"],
        "phase": first["independent_variable_phase"],
        "component": first["independent_variable_component"],
        "value": "different",
    }
    with pytest.raises(ValueError, match="duplicate indistinguishable condition"):
        build_analysis_table(modified_table(complementary_conditions_json=json.dumps([duplicate])))


def test_analysis_table_keeps_cross_row_phase_differences_in_metadata(collection) -> None:
    matches = collection.search(data_type="VLE", independent_variable="pressure")
    relation = build_property_table(collection, matches=matches)
    records = relation.to_records()
    records[0]["independent_variable_phase"] = "Gas"
    records[0]["property_phase"] = "Gas"
    records[1]["independent_variable_phase"] = "Liquid"
    records[1]["property_phase"] = "Liquid"
    varied = ExperimentalTable(
        relation.columns,
        tuple(tuple(record[column] for column in relation.columns) for record in records),
    )
    analysis = build_analysis_table(varied)
    assert "Pressure, kPa" in analysis.columns
    assert "Mole fraction" in analysis.columns
    assert not any(column.startswith("Pressure, kPa [") for column in analysis.columns)
    assert not any(column.startswith("Mole fraction [") for column in analysis.columns)


def test_property_relation_skips_other_point_variables(document) -> None:
    dataset = document.datasets[0]
    pressure = dataset.variables[0]
    temperature = replace(pressure, number=2, name="Temperature, K")
    points = tuple(
        replace(
            point,
            variable_values=(
                *point.variable_values,
                replace(point.variable_values[0], number=2),
            ),
        )
        for point in dataset.points
    )
    expanded = replace(dataset, variables=(pressure, temperature), points=points)
    modified = replace(document, datasets=(expanded,))
    selected = ThermoMLCollection((modified,))
    matches = selected.search(data_type="VLE", independent_variable="pressure")
    records = build_property_table(selected, matches=matches).to_records()
    assert len(records) == 3
    complementary = json.loads(records[0]["complementary_conditions_json"])
    assert [item["source"] for item in complementary] == [
        "variable",
        "constraint",
    ]
    assert [item["name"] for item in complementary] == [
        "Temperature, K",
        "Temperature, K",
    ]


def test_table_concatenation_preserves_schema(collection) -> None:
    table = build_experimental_table(collection)
    combined = ExperimentalTable.concatenate(table, table)
    assert combined.columns == table.columns
    assert len(combined.rows) == 2 * len(table.rows)
    assert ExperimentalTable.concatenate() == ExperimentalTable((), ())
    with pytest.raises(ValueError, match="different schemas"):
        ExperimentalTable.concatenate(table, ExperimentalTable(("other",), ()))
    with pytest.raises(ValueError, match="different schemas"):
        ExperimentalTable.concatenate(
            table,
            ExperimentalTable(table.columns, (), schema="thermoml-io.other.v1"),
        )


def test_optional_dependency_errors(collection, tmp_path: Path, monkeypatch) -> None:
    table = build_experimental_table(collection)
    real_import = __import__

    def blocked_import(name, *args, **kwargs):
        if name in {"pandas", "yaml", "pyarrow"}:
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", blocked_import)
    with pytest.raises(OptionalDependencyError, match="pandas"):
        table.to_pandas()
    with pytest.raises(OptionalDependencyError, match="PyYAML"):
        table.write(tmp_path / "table.yaml")
    with pytest.raises(OptionalDependencyError, match="PyArrow"):
        table.write(tmp_path / "table.parquet")


def test_table_skips_nonmatching_properties_and_rejects_unknown_json(collection) -> None:
    match = collection.search(data_type="VLE")[0]
    empty_match = type(match)(
        document=match.document,
        dataset=match.dataset,
        matching_property_numbers=(),
        observation_count=0,
        data_types=match.data_types,
    )
    assert build_experimental_table(collection, matches=(empty_match,)).rows == ()
    with pytest.raises(TypeError, match="not JSON serializable"):
        table_module._json_default(object())
