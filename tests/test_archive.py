"""Tests for bounded-memory bulk archive traversal and ranking."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import tarfile
from dataclasses import replace
from pathlib import Path

import pyarrow.parquet as pq
import pytest
import yaml
from defusedxml import ElementTree

from thermoml_io import (
    AmbiguousComponentError,
    ComponentIdentity,
    ThermoMLArchiveError,
    analyze_thermoml_archive,
    catalog_thermoml_archive,
    index_thermoml_archive,
    iter_thermoml_archive,
    query_thermoml_archive,
    summarize_documents,
)

CO2_INCHIKEY = "CURLTUGMZLYLDI-UHFFFAOYSA-N"
CO2_INCHI = "InChI=1S/CO2/c2-1-3"


def _add_bytes(archive: tarfile.TarFile, name: str, content: bytes) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(content)
    archive.addfile(info, io.BytesIO(content))


def _nist_json_bytes(raw: bytes, *, related_xml: bytes | None = None) -> bytes:
    def encode(element):
        children = list(element)
        if not children:
            return (element.text or "").strip() or None
        value = {"tml_elements": []}
        for child in children:
            name = child.tag.rsplit("}", 1)[-1]
            encoded = encode(child)
            if name not in value:
                value["tml_elements"].append(name)
                value[name] = encoded
            elif isinstance(value[name], list):
                value[name].append(encoded)
            else:
                value[name] = [value[name], encoded]
        return value

    result = encode(ElementTree.fromstring(raw))
    result["THERMOML_MD5_CHECKSUM"] = hashlib.md5(
        related_xml if related_xml is not None else raw,
        usedforsecurity=False,
    ).hexdigest()
    return json.dumps(result).encode()


@pytest.fixture
def synthetic_archive(tmp_path: Path, fixture_path: Path) -> Path:
    raw = fixture_path.read_bytes()
    without_co2 = raw.replace(CO2_INCHIKEY.encode(), b"AAAAAAAAAAAAAAAAAAAAAAAAAAA").replace(
        CO2_INCHI.encode(), b"InChI=1S/XY2/c2-1-3"
    )
    path = tmp_path / "synthetic.tgz"
    with tarfile.open(path, "w:gz") as archive:
        directory = tarfile.TarInfo("nested")
        directory.type = tarfile.DIRTYPE
        archive.addfile(directory)
        _add_bytes(archive, "nested/with-co2.xml", raw)
        _add_bytes(archive, "nested/without-co2.XML", without_co2)
        _add_bytes(archive, "nested/metadata.json", b"{}")
    return path


def test_iter_archive_and_serialized_prefilter(synthetic_archive: Path) -> None:
    documents = tuple(iter_thermoml_archive(synthetic_archive))
    assert len(documents) == 2
    assert documents[0].provenance.locator.endswith("!nested/with-co2.xml")
    selected = tuple(
        iter_thermoml_archive(
            synthetic_archive,
            serialized_prefilter=CO2_INCHIKEY,
        )
    )
    assert len(selected) == 1
    selected_bytes = tuple(
        iter_thermoml_archive(
            synthetic_archive,
            serialized_prefilter=CO2_INCHIKEY.encode(),
        )
    )
    assert selected_bytes == selected


def test_general_archive_analysis_ranks_before_truncation(
    synthetic_archive: Path,
) -> None:
    result = analyze_thermoml_archive(synthetic_archive, top_datasets=1)
    assert result.xml_document_count == 2
    assert result.parsed_document_count == 2
    assert result.matched_document_count == 2
    assert result.component_query is None
    assert result.resolved_component is None
    assert result.failures == ()
    assert result.summary.document_count == 2
    assert result.summary.dataset_count == 6
    assert result.summary.observation_count == 12
    assert len(result.top_datasets) == 1
    assert result.top_datasets[0].observation_count == 3
    assert result.top_datasets[0].system_type == "binary"
    assert result.top_datasets[0].data_types == ("VLE",)


def test_component_archive_analysis_filters_datasets_semantically(
    synthetic_archive: Path,
) -> None:
    result = analyze_thermoml_archive(
        synthetic_archive,
        component=CO2_INCHIKEY,
        serialized_prefilter=CO2_INCHIKEY.encode(),
        top_datasets=10,
    )
    assert result.xml_document_count == 2
    assert result.parsed_document_count == 1
    assert result.matched_document_count == 1
    assert result.serialized_prefilter == CO2_INCHIKEY
    assert result.resolved_component is not None
    assert result.resolved_component.standard_inchi_keys == (CO2_INCHIKEY,)
    assert result.summary.document_count == 1
    assert result.summary.dataset_count == 2
    assert result.summary.observation_count == 4
    assert result.summary.reaction_dataset_count == 0
    assert [item.observation_count for item in result.top_datasets] == [3, 1]
    assert "carbon dioxide" in result.top_datasets[0].system

    semantic_check = analyze_thermoml_archive(
        synthetic_archive,
        component=CO2_INCHIKEY,
        serialized_prefilter="Synthetic ThermoML fixture",
        top_datasets=0,
    )
    assert semantic_check.parsed_document_count == 2
    assert semantic_check.matched_document_count == 1
    assert semantic_check.top_datasets == ()


def test_archive_validation_and_empty_document(
    monkeypatch, document, synthetic_archive: Path
) -> None:
    with pytest.raises(ValueError, match="non-negative"):
        analyze_thermoml_archive(synthetic_archive, top_datasets=-1)

    def reject_archive(*_args, **_kwargs):
        raise tarfile.ReadError("synthetic invalid archive")

    monkeypatch.setattr(tarfile, "open", reject_archive)
    with pytest.raises(ThermoMLArchiveError, match="Could not read"):
        tuple(iter_thermoml_archive("invalid.tgz"))

    empty = replace(document, datasets=())
    summary = summarize_documents(iter((empty,)))
    assert summary.document_count == 0
    assert summary.observation_count == 0


def test_member_parse_failures_are_strict_or_explicit(tmp_path: Path, fixture_path: Path) -> None:
    path = tmp_path / "partly-invalid.tgz"
    with tarfile.open(path, "w:gz") as archive:
        _add_bytes(archive, "valid.xml", fixture_path.read_bytes())
        _add_bytes(archive, "broken.xml", b"<DataReport>\xff</DataReport>")

    with pytest.raises(ThermoMLArchiveError, match=r"broken\.xml"):
        analyze_thermoml_archive(path)
    with pytest.raises(ThermoMLArchiveError, match=r"broken\.xml"):
        tuple(iter_thermoml_archive(path))

    result = analyze_thermoml_archive(path, on_error="collect")
    assert result.xml_document_count == 2
    assert result.parsed_document_count == 1
    assert result.matched_document_count == 1
    assert len(result.failures) == 1
    assert result.failures[0].member_name == "broken.xml"
    assert result.failures[0].error_type == "ThermoMLParseError"
    assert "Invalid or unsafe" in result.failures[0].message

    with pytest.raises(ValueError, match="on_error"):
        analyze_thermoml_archive(path, on_error="ignore")  # type: ignore[arg-type]


def test_malformed_xml_recovers_only_from_paired_official_json(
    tmp_path: Path, fixture_path: Path
) -> None:
    raw = fixture_path.read_bytes()
    malformed = b"<DataReport>\xff</DataReport>"
    path = tmp_path / "recoverable.tgz"
    with tarfile.open(path, "w:gz") as archive:
        _add_bytes(archive, "nested/recovered.xml", malformed)
        _add_bytes(
            archive,
            "nested/recovered.json",
            _nist_json_bytes(raw, related_xml=malformed),
        )

    documents = tuple(iter_thermoml_archive(path))
    assert len(documents) == 1
    document = documents[0]
    assert document.provenance.locator.endswith("!nested/recovered.json")
    assert document.provenance.recovery is not None
    assert document.provenance.recovery.failed_locator.endswith("recovered.xml")
    assert document.provenance.recovery.strategy == "paired-nist-json"
    assert document.provenance.recovery.lexical_numeric_representation_preserved is False

    analysis = analyze_thermoml_archive(path)
    assert analysis.parsed_document_count == 1
    assert analysis.failures == ()
    assert len(analysis.recoveries) == 1
    assert analysis.recoveries[0].json_member_name == "nested/recovered.json"

    catalog = catalog_thermoml_archive(path)
    indexed = index_thermoml_archive(path)
    assert len(catalog.recoveries) == len(indexed.recoveries) == 1

    result = query_thermoml_archive(
        path,
        components="H2O",
        component_match="contains",
        property_name="density",
        independent_variable="temperature",
    )
    assert len(result.recoveries) == 1
    record = result.table.to_records()[0]
    recovery = json.loads(record["source_recovery_json"])
    assert recovery["failed_media_type"] == "application/xml"
    metadata = json.loads(result.analysis_table.to_records()[0]["metadata"])
    assert metadata["source"]["recovery"]["strategy"] == "paired-nist-json"
    assert "lexical decimal spelling" in metadata["source"]["warnings"][0]

    with pytest.raises(ThermoMLArchiveError, match=r"recovered\.xml"):
        tuple(iter_thermoml_archive(path, json_fallback="never"))
    strict_xml = analyze_thermoml_archive(path, on_error="collect", json_fallback="never")
    assert len(strict_xml.failures) == 1
    assert strict_xml.recoveries == ()
    with pytest.raises(ValueError, match="json_fallback"):
        tuple(iter_thermoml_archive(path, json_fallback="bad"))  # type: ignore[arg-type]

    mismatch = tmp_path / "mismatched-pair.tgz"
    with tarfile.open(mismatch, "w:gz") as archive:
        _add_bytes(archive, "record.xml", malformed)
        _add_bytes(archive, "record.json", _nist_json_bytes(raw))
    with pytest.raises(ThermoMLArchiveError, match="paired official JSON also failed"):
        tuple(iter_thermoml_archive(mismatch))


def test_archive_catalog_lists_properties_and_conditions(
    synthetic_archive: Path,
) -> None:
    catalog = catalog_thermoml_archive(synthetic_archive)
    assert catalog.xml_document_count == 2
    assert catalog.parsed_document_count == 2
    assert catalog.failures == ()
    assert catalog.resolve_component(CO2_INCHIKEY).preferred_name == "carbon dioxide"
    assert catalog.categories()[0].label == "VLE"
    density = catalog.properties("volumetric")
    assert density[0].label == "Mass density, kg/m3"
    assert density[0].count == 4
    conditions = catalog.independent_variables("volumetric", "density")
    assert conditions[0].label == "Temperature, K"
    assert conditions[0].count == 4
    assert catalog.properties("does-not-exist") == ()
    assert catalog.independent_variables("volumetric", "viscosity") == ()


def test_archive_property_query_ranks_publications_after_full_scan(
    synthetic_archive: Path, tmp_path: Path
) -> None:
    result = query_thermoml_archive(
        synthetic_archive,
        components=(CO2_INCHIKEY, "H2O"),
        component_match="exact",
        data_category="VLE",
        property_name="mole fraction",
        independent_variable="pressure",
        publication_limit=1,
        serialized_prefilters=(CO2_INCHIKEY,),
    )
    assert result.xml_document_count == 2
    assert result.parsed_document_count == 1
    assert result.available_publication_count == 1
    assert result.matched_dataset_count == 1
    assert result.components == (CO2_INCHIKEY, "H2O")
    assert len(result.resolved_components) == 2
    assert len(result.publications) == 1
    assert result.publications[0].relationship_count == 3
    assert result.publications[0].authors_year == "Example & Tester (2026)"
    assert "Synthetic ThermoML fixture" in result.publications[0].citation_apa
    assert result.publications[0].citation_bibtex.startswith("@article{example2026_")
    assert len(result.table.rows) == 3
    first_record = result.table.to_records()[0]
    assert first_record["citation_title"] == "Synthetic ThermoML fixture for parser verification"
    assert "Temperature, K" in first_record["complementary_conditions_json"]
    csv_path = result.write_csv(tmp_path / "query.data")
    with csv_path.open(encoding="utf-8", newline="") as stream:
        csv_rows = list(csv.DictReader(stream))
    assert tuple(csv_rows[0]) == result.analysis_table.columns
    assert csv_rows[0]["Temperature, K"] == "298.15"
    assert csv_rows[0]["Pressure, kPa"] == "1000"
    assert csv_rows[0]["Mole fraction"] == "0.10"
    assert csv_rows[0]["DOI"] == "10.0000/thermoml-io.synthetic"
    assert json.loads(csv_rows[0]["metadata"])["property"]["name"] == "Mole fraction"

    json_path = result.write_json(tmp_path / "query.json")
    assert json.loads(json_path.read_text(encoding="utf-8"))["schema"] == (
        "thermoml-io.analysis-table.v1"
    )
    yaml_path = result.write_yaml(tmp_path / "query.yaml")
    assert (
        yaml.safe_load(yaml_path.read_text(encoding="utf-8"))["rows"][0]["Pressure, kPa"] == "1000"
    )
    parquet_path = result.write_parquet(tmp_path / "query.parquet")
    assert pq.read_table(parquet_path).schema.metadata[b"thermoml_io_schema"] == (
        b"analysis-table.v1"
    )
    lossless_path = result.write_lossless(tmp_path / "query-lossless.csv")
    assert lossless_path.read_text(encoding="utf-8").startswith("source_locator,")
    assert result.write(tmp_path / "query.csv") == tmp_path / "query.csv"
    with pytest.raises(ValueError, match="layout"):
        result.write(tmp_path / "invalid.csv", layout="bad")  # type: ignore[arg-type]

    empty = query_thermoml_archive(
        synthetic_archive,
        components="H2O",
        component_match="exact",
        data_category="transport",
        property_name="viscosity",
        independent_variable="pressure",
        publication_limit=0,
    )
    assert empty.publications == ()
    assert empty.table.rows == ()


def test_archive_component_index_is_reusable_and_ambiguity_safe(
    synthetic_archive: Path,
) -> None:
    indexed = index_thermoml_archive(synthetic_archive)
    assert indexed.xml_document_count == 2
    assert indexed.parsed_document_count == 2
    assert indexed.failures == ()
    assert indexed.identities == indexed.index.identities
    co2 = indexed.resolve_component(CO2_INCHIKEY)
    assert co2.preferred_name == "carbon dioxide"
    with pytest.raises(AmbiguousComponentError, match="CO2"):
        indexed.resolve_component("formula:CO2")

    result = query_thermoml_archive(
        synthetic_archive,
        components=(co2, indexed.resolve_component("water")),
        component_index=indexed,
        component_match="exact",
        data_category="VLE",
        property_name="mole fraction",
        independent_variable="pressure",
    )
    assert result.resolved_components[0] is co2
    assert result.available_publication_count == 1

    direct_analysis = analyze_thermoml_archive(
        synthetic_archive,
        component=co2,
        serialized_prefilter=CO2_INCHIKEY,
    )
    assert direct_analysis.resolved_component is co2
    reused_analysis = analyze_thermoml_archive(
        synthetic_archive,
        component=CO2_INCHIKEY,
        component_index=indexed,
        serialized_prefilter=CO2_INCHIKEY,
    )
    assert reused_analysis.resolved_component == co2
    friendly_analysis = analyze_thermoml_archive(
        synthetic_archive,
        component="water",
        top_datasets=0,
    )
    assert friendly_analysis.resolved_component == indexed.resolve_component("water")


def test_archive_component_query_validation(
    synthetic_archive: Path,
) -> None:
    indexed = index_thermoml_archive(synthetic_archive)
    with pytest.raises(ValueError, match="component_match"):
        query_thermoml_archive(
            synthetic_archive,
            components="H2O",
            component_match="bad",  # type: ignore[arg-type]
            independent_variable="temperature",
        )
    with pytest.raises(ValueError, match="at least one"):
        query_thermoml_archive(
            synthetic_archive,
            components=[],
            independent_variable="temperature",
        )
    with pytest.raises(ValueError, match="only valid"):
        query_thermoml_archive(
            synthetic_archive,
            components="H2O",
            required_components=("H2O",),
            independent_variable="temperature",
        )
    with pytest.raises(ValueError, match="subset"):
        query_thermoml_archive(
            synthetic_archive,
            components=(indexed.resolve_component("H2O"),),
            required_components=(indexed.resolve_component(CO2_INCHIKEY),),
            component_match="within",
            component_index=indexed,
            independent_variable="temperature",
        )
    with pytest.raises(ValueError, match="on_error"):
        index_thermoml_archive(synthetic_archive, on_error="bad")  # type: ignore[arg-type]


def test_archive_query_accepts_external_resolved_identity(
    synthetic_archive: Path,
) -> None:
    external = ComponentIdentity(
        preferred_name="water",
        common_names=("water",),
        standard_inchi_keys=("XLYOFNOQVPJJNP-UHFFFAOYSA-N",),
    )
    result = query_thermoml_archive(
        synthetic_archive,
        components=external,
        component_match="exact",
        data_category="volumetric",
        property_name="density",
        independent_variable="temperature",
    )
    assert result.components == (external.stable_identifier,)
    assert result.available_publication_count == 1


def test_catalog_and_query_validation_and_failures(tmp_path: Path, fixture_path: Path) -> None:
    path = tmp_path / "partly-invalid.tgz"
    with tarfile.open(path, "w:gz") as archive:
        _add_bytes(archive, "valid.xml", fixture_path.read_bytes())
        _add_bytes(archive, "broken.xml", b"<DataReport>\xff</DataReport>")

    catalog = catalog_thermoml_archive(path)
    assert len(catalog.failures) == 1
    with pytest.raises(ThermoMLArchiveError, match="broken"):
        catalog_thermoml_archive(path, on_error="raise")
    with pytest.raises(ValueError, match="on_error"):
        catalog_thermoml_archive(path, on_error="bad")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="publication_limit"):
        query_thermoml_archive(
            path,
            components="H2O",
            independent_variable="temperature",
            publication_limit=-1,
        )
    with pytest.raises(ValueError, match="on_error"):
        query_thermoml_archive(
            path,
            components="H2O",
            independent_variable="temperature",
            on_error="bad",  # type: ignore[arg-type]
        )
    with pytest.raises(ThermoMLArchiveError, match="broken"):
        query_thermoml_archive(
            path,
            components="H2O",
            independent_variable="temperature",
            on_error="raise",
        )
    collected = query_thermoml_archive(
        path,
        components="H2O",
        independent_variable="temperature",
    )
    assert len(collected.failures) == 1

    indexed = index_thermoml_archive(path)
    assert len(indexed.failures) == 1
    with pytest.raises(ThermoMLArchiveError, match="broken"):
        index_thermoml_archive(path, on_error="raise")
    water = indexed.resolve_component("H2O")
    with pytest.raises(ThermoMLArchiveError, match="broken"):
        query_thermoml_archive(
            path,
            components=water,
            independent_variable="temperature",
            on_error="raise",
        )
