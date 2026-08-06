"""Parser, validation, security, and network-boundary tests."""

from __future__ import annotations

import hashlib
import io
import json
from datetime import UTC
from pathlib import Path
from urllib.error import URLError

import pytest
from defusedxml import ElementTree

import thermoml_io.parser as parser_module
from thermoml_io import (
    ThermoMLDownloadError,
    ThermoMLParseError,
    ThermoMLReferenceError,
    ThermoMLValidationError,
    load_thermoml_json_url,
    load_thermoml_url,
    parse_thermoml,
    parse_thermoml_json,
    validate_xml_schema,
)


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

    root = ElementTree.fromstring(raw)
    result = encode(root)
    result["THERMOML_MD5_CHECKSUM"] = hashlib.md5(
        related_xml if related_xml is not None else raw,
        usedforsecurity=False,
    ).hexdigest()
    return json.dumps(result).encode()


def test_parse_bytes_text_and_file_object(fixture_path: Path) -> None:
    raw = fixture_path.read_bytes()
    assert parse_thermoml(raw).provenance.locator is None
    assert parse_thermoml(raw.decode()).citation.year == 2026
    assert parse_thermoml(io.BytesIO(raw)).datasets[0].number == 1
    assert parse_thermoml(io.StringIO(raw.decode())).compounds[0].formula == "CO2"
    assert parse_thermoml(bytearray(raw)).citation.year == 2026
    assert parse_thermoml(str(fixture_path)).provenance.locator == str(fixture_path)
    assert parse_thermoml(raw).compounds[0].cas_name == "carbon dioxide"


def test_official_json_uses_same_semantic_decoder(fixture_path: Path, tmp_path: Path) -> None:
    raw = fixture_path.read_bytes()
    payload = _nist_json_bytes(raw)
    xml = parse_thermoml(raw)
    document = parse_thermoml_json(payload, source_label="official.json")
    assert document.citation == xml.citation
    assert document.compounds == xml.compounds
    assert document.datasets == xml.datasets
    assert document.provenance.locator == "official.json"
    assert document.provenance.media_type == "application/json"
    assert (
        document.provenance.related_xml_md5 == hashlib.md5(raw, usedforsecurity=False).hexdigest()
    )
    assert "lexical decimal spelling" in document.warnings[0]

    path = tmp_path / "document.json"
    path.write_bytes(payload)
    assert parse_thermoml_json(path).provenance.locator == str(path)
    assert parse_thermoml_json(payload.decode()).citation == xml.citation


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (b"[1]", "root must be an object"),
        (b"{", "Invalid official"),
        (b'{"tml_elements":"bad"}', "ordering list"),
        (b'{"tml_elements":["bad name"],"bad name":1}', "element name"),
        (b'{"tml_elements":["Version"]}', "requires Version and Citation"),
        (
            b'{"tml_elements":["Version"],"Version":[[]]}',
            "Nested array",
        ),
        (
            b'{"tml_elements":[],"THERMOML_MD5_CHECKSUM":"bad"}',
            "MD5_CHECKSUM",
        ),
        (b'{"tml_elements":["Version"],"Version":NaN}', "non-finite"),
    ],
)
def test_official_json_validation(payload: bytes, message: str) -> None:
    with pytest.raises(ThermoMLParseError, match=message):
        parse_thermoml_json(payload)


def test_json_scalar_conversion_is_explicit() -> None:
    assert parser_module._json_scalar_text(None, context="x") is None
    assert parser_module._json_scalar_text(True, context="x") == "true"
    assert parser_module._json_scalar_text(False, context="x") == "false"
    with pytest.raises(ThermoMLParseError, match="unsupported scalar"):
        parser_module._json_scalar_text(object(), context="x")


def test_parse_rejects_invalid_sources() -> None:
    with pytest.raises(TypeError, match="Unsupported"):
        parse_thermoml(42)  # type: ignore[arg-type]
    with pytest.raises(ThermoMLParseError, match="DataReport root"):
        parse_thermoml("<Other/>")
    with pytest.raises(ThermoMLParseError, match="requires Version and Citation"):
        parse_thermoml("<DataReport/>")
    with pytest.raises(ThermoMLParseError, match="Unexpected ThermoML namespace"):
        parse_thermoml('<DataReport xmlns="urn:other"><Version/><Citation/></DataReport>')
    with pytest.raises(ThermoMLParseError, match="Invalid or unsafe"):
        parse_thermoml("<DataReport>")


def test_parse_rejects_entity_expansion() -> None:
    malicious = b"""<?xml version='1.0'?>
    <!DOCTYPE x [<!ENTITY boom 'boom'>]>
    <DataReport><Version><nVersionMajor>2</nVersionMajor><nVersionMinor>0</nVersionMinor></Version>
    <Citation><sTitle>&boom;</sTitle></Citation></DataReport>"""
    with pytest.raises(ThermoMLParseError, match="unsafe"):
        parse_thermoml(malicious)


def test_invalid_numbers_and_required_structure(fixture_path: Path) -> None:
    text = fixture_path.read_text(encoding="utf-8")
    with pytest.raises(ThermoMLParseError, match="Invalid integer"):
        parse_thermoml(text.replace("<nVersionMajor>2", "<nVersionMajor>bad", 1))
    with pytest.raises(ThermoMLParseError, match="Invalid decimal"):
        parse_thermoml(text.replace("<nVarValue>1000", "<nVarValue>bad", 1))
    with pytest.raises(ThermoMLParseError, match="Missing integer"):
        parse_thermoml(text.replace("<nVersionMajor>2</nVersionMajor>", "", 1))
    with pytest.raises(ThermoMLParseError, match="Missing numeric"):
        parse_thermoml(text.replace("<nVarValue>1000</nVarValue>", "", 1))
    with pytest.raises(ThermoMLParseError, match="missing its document-local"):
        parse_thermoml(text.replace("<nOrgNum>1</nOrgNum>", "", 1))
    with pytest.raises(ThermoMLParseError, match="has no Property-MethodID"):
        parse_thermoml(
            text.replace("<Property-MethodID>", "<Other>", 1).replace(
                "</Property-MethodID>", "</Other>", 1
            )
        )


@pytest.mark.parametrize(
    "opening,closing,replacement_opening,replacement_closing,message",
    [
        (
            "<PropertyGroup>",
            "</PropertyGroup>",
            "<PropertyGroup/><!--",
            "-->",
            "has no PropertyGroup",
        ),
        ("<VariableID>", "</VariableID>", "<Other>", "</Other>", "has no VariableID"),
        (
            "<VariableType>",
            "</VariableType>",
            "<Other>",
            "</Other>",
            "has no VariableType",
        ),
        (
            "<ConstraintID>",
            "</ConstraintID>",
            "<Other>",
            "</Other>",
            "has no ConstraintID",
        ),
        (
            "<ConstraintType>",
            "</ConstraintType>",
            "<Other>",
            "</Other>",
            "has no ConstraintType",
        ),
    ],
)
def test_required_quantity_containers(
    fixture_path: Path,
    opening: str,
    closing: str,
    replacement_opening: str,
    replacement_closing: str,
    message: str,
) -> None:
    text = fixture_path.read_text(encoding="utf-8")
    text = text.replace(opening, replacement_opening, 1).replace(closing, replacement_closing, 1)
    with pytest.raises(ThermoMLParseError, match=message):
        parse_thermoml(text)


def test_missing_quantity_names_and_unreferenced_dataset_component(
    fixture_path: Path,
) -> None:
    text = fixture_path.read_text(encoding="utf-8")
    unnamed = text.replace(
        "<VariableType><ePressure>Pressure, kPa</ePressure></VariableType>",
        "<VariableType><Other/></VariableType>",
        1,
    )
    with pytest.raises(ThermoMLParseError, match="Missing ThermoML quantity name"):
        parse_thermoml(unnamed)

    unreferenced = text.replace(
        "<Component><RegNum><nOrgNum>1</nOrgNum></RegNum><nSampleNm>1</nSampleNm></Component>",
        "<Component/>",
        1,
    )
    with pytest.raises(ThermoMLParseError, match="unreferenced component"):
        parse_thermoml(unreferenced)


def test_reference_validation(fixture_path: Path) -> None:
    text = fixture_path.read_text(encoding="utf-8")
    missing_component = text.replace(
        "<Component><RegNum><nOrgNum>1</nOrgNum></RegNum><nSampleNm>1</nSampleNm></Component>",
        "<Component><RegNum><nOrgNum>99</nOrgNum></RegNum><nSampleNm>1</nSampleNm></Component>",
        1,
    )
    with pytest.raises(ThermoMLReferenceError, match="missing component 99"):
        parse_thermoml(missing_component)

    missing_property = text.replace(
        "<nPropNumber>1</nPropNumber><nPropValue>0.10",
        "<nPropNumber>9</nPropNumber><nPropValue>0.10",
        1,
    )
    with pytest.raises(ThermoMLReferenceError, match="unresolved properties"):
        parse_thermoml(missing_property)

    start = text.index("    <Property>")
    end = text.index("    </Property>", start) + len("    </Property>\n")
    property_block = text[start:end]
    duplicate = text[:end] + property_block + text[end:]
    with pytest.raises(ThermoMLValidationError):
        parse_thermoml(duplicate)

    first_compound_start = text.index("  <Compound>")
    first_compound_end = text.index("  </Compound>", first_compound_start) + len("  </Compound>\n")
    compound_block = text[first_compound_start:first_compound_end]
    duplicate_compound = text[:first_compound_end] + compound_block + text[first_compound_end:]
    with pytest.raises(ThermoMLValidationError, match="not unique"):
        parse_thermoml(duplicate_compound)

    missing_quantity_component = text.replace(
        "<RegNum><nOrgNum>1</nOrgNum></RegNum>\n      </Property-MethodID>",
        "<RegNum><nOrgNum>99</nOrgNum></RegNum>\n      </Property-MethodID>",
        1,
    )
    with pytest.raises(ThermoMLReferenceError, match="quantity metadata"):
        parse_thermoml(missing_quantity_component)


def test_optional_citation_phase_solvent_and_expanded_uncertainty(
    fixture_path: Path,
) -> None:
    text = fixture_path.read_text(encoding="utf-8")
    trc_start = text.index("    <TRCRefID>")
    trc_end = text.index("    </TRCRefID>", trc_start) + len("    </TRCRefID>\n")
    without_trc = text[:trc_start] + text[trc_end:]
    assert parse_thermoml(without_trc).citation.trc_reference_id is None

    with_solvent = text.replace(
        "<PropPhaseID><ePropPhase>Gas</ePropPhase></PropPhaseID>",
        "<PropPhaseID><ePropPhase>Gas</ePropPhase><Solvent>"
        "<RegNum><nOrgNum>2</nOrgNum></RegNum></Solvent></PropPhaseID>",
        1,
    )
    assert parse_thermoml(with_solvent).datasets[0].properties[0].solvent_component_ids == (2,)

    asymmetric_expanded = text.replace(
        "<nCombExpandUncertValue>0.012</nCombExpandUncertValue>",
        "<AsymExpandUncert><nPositiveValue>0.014</nPositiveValue>"
        "<nNegativeValue>0.011</nNegativeValue></AsymExpandUncert>",
        1,
    )
    uncertainty = (
        parse_thermoml(asymmetric_expanded)
        .datasets[0]
        .points[2]
        .property_values[0]
        .uncertainties[0]
    )
    assert str(uncertainty.positive_expanded_value) == "0.014"
    assert str(uncertainty.negative_expanded_value) == "0.011"


def test_reaction_data_is_explicitly_reported(fixture_path: Path) -> None:
    text = fixture_path.read_text(encoding="utf-8").replace(
        "</DataReport>", "<ReactionData/><ReactionData/></DataReport>"
    )
    document = parse_thermoml(text)
    assert document.reaction_dataset_count == 2
    assert "does not decode" in document.warnings[0]


def test_validate_against_explicit_xsd(tmp_path: Path) -> None:
    xsd = tmp_path / "simple.xsd"
    xsd.write_text(
        """<xsd:schema xmlns:xsd="http://www.w3.org/2001/XMLSchema">
        <xsd:element name="DataReport"><xsd:complexType><xsd:sequence>
        <xsd:element name="Version"/><xsd:element name="Citation"/>
        </xsd:sequence></xsd:complexType></xsd:element></xsd:schema>""",
        encoding="utf-8",
    )
    valid = "<DataReport><Version/><Citation/></DataReport>"
    validate_xml_schema(valid, xsd)
    with pytest.raises(ThermoMLValidationError, match="does not validate"):
        validate_xml_schema("<Other/>", xsd)


def test_parse_with_explicit_permissive_schema(tmp_path: Path, fixture_path: Path) -> None:
    xsd = tmp_path / "thermoml-permissive.xsd"
    xsd.write_text(
        """<xsd:schema xmlns:xsd="http://www.w3.org/2001/XMLSchema"
        targetNamespace="http://www.iupac.org/namespaces/ThermoML"
        elementFormDefault="qualified"><xsd:element name="DataReport">
        <xsd:complexType><xsd:sequence><xsd:any minOccurs="0" maxOccurs="unbounded"
        processContents="lax"/></xsd:sequence></xsd:complexType></xsd:element>
        </xsd:schema>""",
        encoding="utf-8",
    )
    assert parse_thermoml(fixture_path, schema=xsd).schema_version == "2.0"


class _Headers(dict[str, str]):
    pass


class _Response:
    def __init__(self, data: bytes, content_length: str | None = None) -> None:
        self._data = data
        self.headers = _Headers()
        if content_length is not None:
            self.headers["Content-Length"] = content_length

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, size: int) -> bytes:
        return self._data[:size]


def test_https_loader_records_provenance(monkeypatch, fixture_path: Path) -> None:
    raw = fixture_path.read_bytes()
    monkeypatch.setattr(parser_module, "urlopen", lambda *_args, **_kwargs: _Response(raw))
    document = load_thermoml_url("https://example.invalid/data.xml")
    assert document.provenance.locator == "https://example.invalid/data.xml"
    assert document.provenance.retrieved_at is not None
    assert document.provenance.retrieved_at.tzinfo == UTC

    payload = _nist_json_bytes(raw)
    monkeypatch.setattr(parser_module, "urlopen", lambda *_args, **_kwargs: _Response(payload))
    json_document = load_thermoml_json_url("https://example.invalid/data.json")
    assert json_document.provenance.locator.endswith("data.json")
    assert json_document.provenance.retrieved_at is not None


def test_https_xml_loader_uses_audited_paired_json_fallback(
    monkeypatch, fixture_path: Path
) -> None:
    malformed = b"<DataReport>\xff</DataReport>"
    responses = iter(
        (
            _Response(malformed),
            _Response(_nist_json_bytes(fixture_path.read_bytes(), related_xml=malformed)),
        )
    )
    monkeypatch.setattr(parser_module, "urlopen", lambda *_args, **_kwargs: next(responses))
    document = load_thermoml_url("https://trc.nist.gov/ThermoML/10.0000/example.xml?download=1")
    assert document.provenance.locator == (
        "https://trc.nist.gov/ThermoML/10.0000/example.json?download=1"
    )
    assert document.provenance.recovery is not None
    assert document.provenance.recovery.failed_sha256 == hashlib.sha256(malformed).hexdigest()

    monkeypatch.setattr(parser_module, "urlopen", lambda *_args, **_kwargs: _Response(malformed))
    with pytest.raises(ThermoMLParseError, match="Invalid or unsafe"):
        load_thermoml_url("https://example.invalid/data.xml", json_fallback="never")
    with pytest.raises(ValueError, match="json_fallback"):
        load_thermoml_url(
            "https://example.invalid/data.xml",
            json_fallback="bad",  # type: ignore[arg-type]
        )


def test_https_loader_limits_and_failures(monkeypatch, fixture_path: Path) -> None:
    raw = fixture_path.read_bytes()

    def fail(*_args, **_kwargs):
        raise URLError("offline")

    with pytest.raises(ThermoMLDownloadError, match="Only HTTPS"):
        load_thermoml_url("http://example.invalid/data.xml")

    monkeypatch.setattr(
        parser_module,
        "urlopen",
        lambda *_args, **_kwargs: _Response(raw, str(len(raw))),
    )
    with pytest.raises(ThermoMLDownloadError, match="declares"):
        load_thermoml_url("https://example.invalid/data.xml", max_bytes=10)

    monkeypatch.setattr(
        parser_module,
        "urlopen",
        lambda *_args, **_kwargs: _Response(raw, "not-an-integer"),
    )
    with pytest.raises(ThermoMLDownloadError, match="Could not download"):
        load_thermoml_url("https://example.invalid/data.xml")

    with pytest.raises(ThermoMLDownloadError, match="Only HTTPS"):
        load_thermoml_json_url("http://example.invalid/data.json")
    monkeypatch.setattr(
        parser_module,
        "urlopen",
        lambda *_args, **_kwargs: _Response(_nist_json_bytes(raw), str(len(raw))),
    )
    with pytest.raises(ThermoMLDownloadError, match="declares"):
        load_thermoml_json_url("https://example.invalid/data.json", max_bytes=10)

    monkeypatch.setattr(
        parser_module,
        "urlopen",
        lambda *_args, **_kwargs: _Response(_nist_json_bytes(raw)),
    )
    with pytest.raises(ThermoMLDownloadError, match="exceeded"):
        load_thermoml_json_url("https://example.invalid/data.json", max_bytes=10)
    monkeypatch.setattr(parser_module, "urlopen", fail)
    with pytest.raises(ThermoMLDownloadError, match="Could not download"):
        load_thermoml_json_url("https://example.invalid/data.json")

    monkeypatch.setattr(parser_module, "urlopen", lambda *_args, **_kwargs: _Response(raw))
    with pytest.raises(ThermoMLDownloadError, match="exceeded"):
        load_thermoml_url("https://example.invalid/data.xml", max_bytes=10)

    monkeypatch.setattr(parser_module, "urlopen", fail)
    with pytest.raises(ThermoMLDownloadError, match="Could not download"):
        load_thermoml_url("https://example.invalid/data.xml")
