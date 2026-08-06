"""Safe, namespace-aware parsing of ThermoML XML documents.

The implementation follows the public IUPAC ThermoML schema directly. It is
independent of third-party ThermoML Python implementations.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
from collections.abc import Iterable
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, BinaryIO, Literal, cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from xml.etree.ElementTree import Element

from defusedxml import ElementTree as SafeElementTree
from defusedxml.common import DefusedXmlException

from .errors import (
    ThermoMLDownloadError,
    ThermoMLError,
    ThermoMLParseError,
    ThermoMLReferenceError,
    ThermoMLValidationError,
)
from .models import (
    Citation,
    Compound,
    ConstraintDefinition,
    DataPoint,
    DataSet,
    DeviceSpecification,
    MeasuredValue,
    PropertyDefinition,
    PurityAssessment,
    QuantityDefinition,
    Repeatability,
    Sample,
    SourceProvenance,
    SourceRecovery,
    ThermoMLDocument,
    Uncertainty,
    VariableDefinition,
)

THERMOML_NAMESPACE = "http://www.iupac.org/namespaces/ThermoML"
DEFAULT_MAX_DOWNLOAD_BYTES = 100 * 1024 * 1024

XMLSource = str | bytes | bytearray | Path | BinaryIO
JSONSource = str | bytes | bytearray | Path | BinaryIO

_JSON_ELEMENT_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_.-]*\Z")
_JSON_LEXICAL_WARNING = (
    "Parsed the official NIST JSON representation. Numeric values are retained "
    "exactly as Decimal values from JSON, but JSON may not preserve the original "
    "XML lexical decimal spelling."
)


def _local_name(tag: str) -> str:
    return tag.rsplit("}", maxsplit=1)[-1]


def _children(element: Element, name: str) -> tuple[Element, ...]:
    return tuple(child for child in element if _local_name(child.tag) == name)


def _child(element: Element, name: str) -> Element | None:
    return next((child for child in element if _local_name(child.tag) == name), None)


def _descendants(element: Element, name: str) -> tuple[Element, ...]:
    return tuple(node for node in element.iter() if _local_name(node.tag) == name)


def _text(element: Element | None) -> str | None:
    if element is None or element.text is None:
        return None
    value = element.text.strip()
    return value or None


def _child_text(element: Element, name: str) -> str | None:
    return _text(_child(element, name))


def _desc_text(element: Element, *names: str) -> str | None:
    selected = set(names)
    for node in element.iter():
        if _local_name(node.tag) in selected:
            value = _text(node)
            if value is not None:
                return value
    return None


def _integer(value: str | None, *, context: str, required: bool = False) -> int | None:
    if value is None:
        if required:
            raise ThermoMLParseError(f"Missing integer value for {context}.")
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise ThermoMLParseError(f"Invalid integer {value!r} for {context}.") from exc


def _decimal(
    value: str | None,
    *,
    context: str,
    required: bool = False,
) -> Decimal | None:
    if value is None:
        if required:
            raise ThermoMLParseError(f"Missing numeric value for {context}.")
        return None
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise ThermoMLParseError(f"Invalid decimal {value!r} for {context}.") from exc


def _read_source(source: XMLSource) -> tuple[bytes, str | None]:
    if isinstance(source, Path):
        return source.read_bytes(), str(source)
    if isinstance(source, bytes | bytearray):
        return bytes(source), None
    if hasattr(source, "read"):
        raw = source.read()
        return (raw.encode("utf-8") if isinstance(raw, str) else bytes(raw)), None
    if isinstance(source, str):
        if source.lstrip().startswith("<"):
            return source.encode("utf-8"), None
        path = Path(source)
        return path.read_bytes(), str(path)
    raise TypeError(f"Unsupported ThermoML source type: {type(source)!r}")


def _read_json_source(source: JSONSource) -> tuple[bytes, str | None]:
    if isinstance(source, str) and source.lstrip().startswith(("{", "[")):
        return source.encode("utf-8"), None
    return _read_source(source)


def _parse_citation(element: Element) -> Citation:
    trc = _child(element, "TRCRefID")
    trc_id = None
    if trc is not None:
        parts = [_text(child) for child in trc]
        trc_id = "-".join(part for part in parts if part)
    year = _integer(_child_text(element, "yrPubYr"), context="citation year")
    return Citation(
        authors=tuple(
            value
            for author in _children(element, "sAuthor")
            if (value := _text(author)) is not None
        ),
        title=_child_text(element, "sTitle"),
        publication_name=_child_text(element, "sPubName"),
        year=year,
        date=_child_text(element, "dateCit"),
        volume=_child_text(element, "sVol"),
        pages=_child_text(element, "sPage"),
        doi=_child_text(element, "sDOI"),
        url=_child_text(element, "urlCit"),
        document_type=_child_text(element, "eType"),
        source_type=_child_text(element, "eSourceType"),
        document_origin=_child_text(element, "sDocumentOrigin"),
        abstract=_child_text(element, "sAbstract"),
        keywords=tuple(
            value
            for keyword in _children(element, "sKeyword")
            if (value := _text(keyword)) is not None
        ),
        language=_child_text(element, "eLanguage"),
        trc_reference_id=trc_id,
    )


def _parse_purity(element: Element) -> PurityAssessment:
    return PurityAssessment(
        step=_integer(_child_text(element, "nStep"), context="purity step"),
        purification_methods=tuple(
            value
            for child in element
            if _local_name(child.tag) in {"ePurifMethod", "sPurifMethod"}
            and (value := _text(child)) is not None
        ),
        analysis_methods=tuple(
            value
            for child in _children(element, "eAnalMeth")
            if (value := _text(child)) is not None
        ),
        mole_percent=_decimal(_child_text(element, "nPurityMol"), context="mole-percent purity"),
        mole_percent_digits=_integer(
            _child_text(element, "nPurityMolDigits"), context="mole-percent digits"
        ),
        mass_percent=_decimal(_child_text(element, "nPurityMass"), context="mass-percent purity"),
        mass_percent_digits=_integer(
            _child_text(element, "nPurityMassDigits"), context="mass-percent digits"
        ),
        volume_percent=_decimal(
            _child_text(element, "nPurityVol"), context="volume-percent purity"
        ),
        volume_percent_digits=_integer(
            _child_text(element, "nPurityVolDigits"), context="volume-percent digits"
        ),
        unspecified_percent=_decimal(
            _child_text(element, "nUnknownPerCent"), context="unspecified-percent purity"
        ),
    )


def _parse_sample(element: Element) -> Sample:
    number = _integer(_child_text(element, "nSampleNm"), context="sample number", required=True)
    assert number is not None
    return Sample(
        number=number,
        source=_child_text(element, "eSource"),
        status=_child_text(element, "eStatus"),
        purity=tuple(_parse_purity(item) for item in _children(element, "purity")),
    )


def _component_id(element: Element) -> int | None:
    value = _desc_text(element, "nCompIndex", "nOrgNum")
    return _integer(value, context="component reference")


def _parse_compound(element: Element) -> Compound:
    reg_num = _child(element, "RegNum")
    local_id = _component_id(reg_num) if reg_num is not None else None
    if local_id is None:
        raise ThermoMLParseError("Compound is missing its document-local identifier.")
    common_names = tuple(
        value for child in _children(element, "sCommonName") if (value := _text(child)) is not None
    )
    return Compound(
        local_id=local_id,
        common_names=common_names,
        iupac_name=_child_text(element, "sIUPACName"),
        cas_name=_child_text(element, "sCASName"),
        formula=_child_text(element, "sFormulaMolec"),
        standard_inchi=(_child_text(element, "sStandardInChI") or _child_text(element, "sInChI")),
        standard_inchi_key=(
            _child_text(element, "sStandardInChIKey") or _child_text(element, "sInChIKey")
        ),
        cas_registry_number=(
            _child_text(element, "sCAS") or _child_text(element, "sCASRegistryNumber")
        ),
        samples=tuple(_parse_sample(item) for item in _children(element, "Sample")),
    )


def _parse_asymmetric(
    element: Element, names: tuple[str, ...], *, context: str
) -> tuple[Decimal | None, Decimal | None]:
    container = next((child for child in element if _local_name(child.tag) in names), None)
    if container is None:
        return None, None
    return (
        _decimal(_child_text(container, "nPositiveValue"), context=f"{context} positive"),
        _decimal(_child_text(container, "nNegativeValue"), context=f"{context} negative"),
    )


def _parse_uncertainty(element: Element, kind: str) -> Uncertainty:
    positive_standard, negative_standard = _parse_asymmetric(
        element,
        ("AsymCombStdUncert", "AsymStdUncert"),
        context="asymmetric standard uncertainty",
    )
    positive_expanded, negative_expanded = _parse_asymmetric(
        element,
        ("AsymCombExpandUncert", "AsymExpandUncert"),
        context="asymmetric expanded uncertainty",
    )
    return Uncertainty(
        kind=kind,
        assessment_number=_integer(
            _desc_text(element, "nCombUncertAssessNum", "nUncertAssessNum"),
            context=f"{kind} uncertainty assessment number",
        ),
        evaluator=_desc_text(element, "sCombUncertEvaluator", "sUncertEvaluator"),
        method=_desc_text(
            element,
            "eCombUncertEvalMethod",
            "sCombUncertEvalMethod",
            "sUncertEvalMethod",
        ),
        standard_value=_decimal(
            _desc_text(element, "nCombStdUncertValue", "nStdUncertValue"),
            context=f"{kind} standard uncertainty",
        ),
        expanded_value=_decimal(
            _desc_text(element, "nCombExpandUncertValue", "nExpandUncertValue"),
            context=f"{kind} expanded uncertainty",
        ),
        positive_standard_value=positive_standard,
        negative_standard_value=negative_standard,
        positive_expanded_value=positive_expanded,
        negative_expanded_value=negative_expanded,
        coverage_factor=_decimal(
            _desc_text(element, "nCombCoverageFactor", "nCoverageFactor"),
            context=f"{kind} uncertainty coverage factor",
        ),
        confidence_level=_decimal(
            _desc_text(element, "nCombUncertLevOfConfid", "nUncertLevOfConfid"),
            context=f"{kind} uncertainty confidence level",
        ),
    )


def _merge_uncertainty(
    value: Uncertainty,
    definitions: Iterable[Uncertainty],
) -> Uncertainty:
    definition = next(
        (
            candidate
            for candidate in definitions
            if candidate.kind == value.kind
            and candidate.assessment_number == value.assessment_number
        ),
        None,
    )
    if definition is None:
        return value
    fields = (
        "evaluator",
        "method",
        "standard_value",
        "expanded_value",
        "positive_standard_value",
        "negative_standard_value",
        "positive_expanded_value",
        "negative_expanded_value",
        "coverage_factor",
        "confidence_level",
    )
    updates = {
        name: getattr(value, name)
        if getattr(value, name) is not None
        else getattr(definition, name)
        for name in fields
    }
    return replace(value, **updates)


def _uncertainties(element: Element) -> tuple[Uncertainty, ...]:
    values: list[Uncertainty] = []
    for child in element:
        tag = _local_name(child.tag)
        if tag == "CombinedUncertainty":
            values.append(_parse_uncertainty(child, "combined"))
        elif tag in {"PropUncertainty", "VarUncertainty", "ConstrUncertainty"}:
            values.append(_parse_uncertainty(child, tag.removesuffix("Uncertainty").lower()))
    return tuple(values)


def _parse_repeatability(element: Element) -> tuple[Repeatability, ...]:
    values = []
    for child in element:
        if not _local_name(child.tag).endswith("Repeatability"):
            continue
        values.append(
            Repeatability(
                evaluator=_desc_text(child, "sRepeatEvaluator"),
                method=_desc_text(child, "eRepeatMethod", "sRepeatMethod"),
                standard_value=_decimal(
                    _desc_text(child, "nRepeatValue", "nStdDevValue"),
                    context="repeatability",
                ),
            )
        )
    return tuple(values)


def _parse_device_specifications(element: Element) -> tuple[DeviceSpecification, ...]:
    values = []
    for child in element:
        if not _local_name(child.tag).endswith("DeviceSpec"):
            continue
        values.append(
            DeviceSpecification(
                evaluator=_desc_text(child, "sDeviceSpecEvaluator"),
                method=_desc_text(child, "eDeviceSpecMethod"),
                description=_desc_text(child, "sDeviceSpecMethod"),
                value=_decimal(
                    _desc_text(child, "nDeviceSpecValue"), context="device specification"
                ),
                confidence_level=_decimal(
                    _desc_text(child, "nDeviceSpecLevOfConfid"),
                    context="device confidence level",
                ),
            )
        )
    return tuple(values)


def _quantity_name(container: Element, *, context: str) -> str:
    for node in container.iter():
        if node is container:
            continue
        if _local_name(node.tag).startswith(("e", "s")) and (value := _text(node)):
            return value
    raise ThermoMLParseError(f"Missing ThermoML quantity name for {context}.")


def _phase(element: Element, *container_names: str) -> str | None:
    for container_name in container_names:
        container = _child(element, container_name)
        if container is not None:
            value = _desc_text(
                container,
                "ePropPhase",
                "eVarPhase",
                "eConstraintPhase",
                "eRefPhase",
                "ePhase",
            )
            if value:
                return value
    return None


def _solvent_component_ids(element: Element) -> tuple[int, ...]:
    values = []
    for solvent in _descendants(element, "Solvent"):
        if (local_id := _component_id(solvent)) is not None:
            values.append(local_id)
    return tuple(dict.fromkeys(values))


def _parse_property(element: Element) -> PropertyDefinition:
    number = _integer(_child_text(element, "nPropNumber"), context="property number", required=True)
    assert number is not None
    method_id = _child(element, "Property-MethodID")
    if method_id is None:
        raise ThermoMLParseError(f"Property {number} has no Property-MethodID.")
    property_group = _child(method_id, "PropertyGroup")
    if property_group is None or not tuple(property_group):
        raise ThermoMLParseError(f"Property {number} has no PropertyGroup.")
    group_element = next(iter(property_group))
    group = _local_name(group_element.tag)
    method = _desc_text(group_element, "eMethodName", "sMethodName")
    target = _component_id(method_id)
    if target is None:
        phase_id = _child(element, "PropPhaseID")
        target = _component_id(phase_id) if phase_id is not None else None
    return PropertyDefinition(
        number=number,
        name=_desc_text(group_element, "ePropName", "sPropName")
        or _quantity_name(group_element, context=f"property {number}"),
        group=group,
        method=method,
        phase=_phase(element, "PropPhaseID"),
        component_id=target,
        solvent_component_ids=_solvent_component_ids(element),
        uncertainties=_uncertainties(element),
        repeatability=_parse_repeatability(element),
        device_specifications=_parse_device_specifications(element),
        presentation=_child_text(element, "ePresentation"),
        reference_phase=_phase(element, "RefPhaseID"),
        standard_state=_child_text(element, "eStandardState"),
    )


def _parse_variable(element: Element) -> VariableDefinition:
    number = _integer(_child_text(element, "nVarNumber"), context="variable number", required=True)
    assert number is not None
    variable_id = _child(element, "VariableID")
    if variable_id is None:
        raise ThermoMLParseError(f"Variable {number} has no VariableID.")
    variable_type = _child(variable_id, "VariableType")
    if variable_type is None:
        raise ThermoMLParseError(f"Variable {number} has no VariableType.")
    return VariableDefinition(
        number=number,
        name=_quantity_name(variable_type, context=f"variable {number}"),
        phase=_phase(element, "VarPhaseID"),
        component_id=_component_id(variable_id),
        solvent_component_ids=_solvent_component_ids(element),
        uncertainties=_uncertainties(element),
        repeatability=_parse_repeatability(element),
        device_specifications=_parse_device_specifications(element),
    )


def _parse_constraint(element: Element, fallback_number: int) -> ConstraintDefinition:
    number = (
        _integer(_child_text(element, "nConstraintNumber"), context="constraint number")
        or fallback_number
    )
    constraint_id = _child(element, "ConstraintID")
    if constraint_id is None:
        raise ThermoMLParseError(f"Constraint {number} has no ConstraintID.")
    constraint_type = _child(constraint_id, "ConstraintType")
    if constraint_type is None:
        raise ThermoMLParseError(f"Constraint {number} has no ConstraintType.")
    return ConstraintDefinition(
        number=number,
        name=_quantity_name(constraint_type, context=f"constraint {number}"),
        phase=_phase(element, "ConstraintPhaseID"),
        component_id=_component_id(constraint_id),
        solvent_component_ids=_solvent_component_ids(element),
        uncertainties=_uncertainties(element),
        repeatability=_parse_repeatability(element),
        device_specifications=_parse_device_specifications(element),
        value=_decimal(
            _child_text(element, "nConstraintValue"),
            context=f"constraint {number} value",
            required=True,
        ),
        significant_digits=_integer(
            _child_text(element, "nConstrDigits"),
            context=f"constraint {number} significant digits",
        ),
    )


def _parse_measured_value(
    element: Element,
    *,
    quantity: str,
    definitions: dict[int, tuple[Uncertainty, ...]],
) -> MeasuredValue:
    is_property = quantity == "property"
    number_tag = "nPropNumber" if is_property else "nVarNumber"
    value_tag = "nPropValue" if is_property else "nVarValue"
    digits_tag = "nPropDigits" if is_property else "nVarDigits"
    number = _integer(
        _child_text(element, number_tag), context=f"{quantity} value number", required=True
    )
    lexical = _child_text(element, value_tag)
    value = _decimal(lexical, context=f"{quantity} value", required=True)
    assert number is not None and value is not None and lexical is not None
    uncertainties = tuple(
        _merge_uncertainty(item, definitions.get(number, ())) for item in _uncertainties(element)
    )
    return MeasuredValue(
        number=number,
        value=value,
        lexical_value=lexical,
        significant_digits=_integer(
            _child_text(element, digits_tag), context=f"{quantity} significant digits"
        ),
        uncertainties=uncertainties,
        repeatability=_parse_repeatability(element),
    )


def _check_unique_numbers(
    items: Iterable[QuantityDefinition], label: str, dataset_number: int
) -> None:
    numbers = [item.number for item in items]
    if len(numbers) != len(set(numbers)):
        raise ThermoMLValidationError(
            f"Dataset {dataset_number} contains duplicate {label} numbers: {numbers}."
        )


def _parse_dataset(element: Element, fallback_number: int) -> DataSet:
    number = (
        _integer(_child_text(element, "nPureOrMixtureDataNumber"), context="dataset number")
        or fallback_number
    )
    component_samples = []
    for component in _children(element, "Component"):
        local_id = _component_id(component)
        if local_id is None:
            raise ThermoMLParseError(f"Dataset {number} contains an unreferenced component.")
        sample = _integer(_child_text(component, "nSampleNm"), context="sample reference")
        component_samples.append((local_id, sample))
    properties = tuple(_parse_property(item) for item in _children(element, "Property"))
    variables = tuple(_parse_variable(item) for item in _children(element, "Variable"))
    constraints = tuple(
        _parse_constraint(item, index)
        for index, item in enumerate(_children(element, "Constraint"), start=1)
    )
    _check_unique_numbers(properties, "property", number)
    _check_unique_numbers(variables, "variable", number)
    property_uncertainties = {item.number: item.uncertainties for item in properties}
    variable_uncertainties = {item.number: item.uncertainties for item in variables}
    points = []
    for index, num_values in enumerate(_children(element, "NumValues"), start=1):
        points.append(
            DataPoint(
                index=index,
                variable_values=tuple(
                    _parse_measured_value(
                        item,
                        quantity="variable",
                        definitions=variable_uncertainties,
                    )
                    for item in _children(num_values, "VariableValue")
                ),
                property_values=tuple(
                    _parse_measured_value(
                        item,
                        quantity="property",
                        definitions=property_uncertainties,
                    )
                    for item in _children(num_values, "PropertyValue")
                ),
            )
        )
    phases = tuple(
        value
        for phase in _children(element, "PhaseID")
        if (value := _desc_text(phase, "ePhase")) is not None
    )
    return DataSet(
        number=number,
        component_ids=tuple(local_id for local_id, _ in component_samples),
        component_sample_numbers=tuple(component_samples),
        purpose=_child_text(element, "eExpPurpose"),
        compiler=_child_text(element, "sCompiler"),
        contributor=_child_text(element, "sContributor"),
        date_added=_child_text(element, "dateDateAdded"),
        phases=phases,
        properties=properties,
        variables=variables,
        constraints=constraints,
        points=tuple(points),
    )


def _validate_references(compounds: tuple[Compound, ...], datasets: tuple[DataSet, ...]) -> None:
    compound_ids = {compound.local_id for compound in compounds}
    if len(compound_ids) != len(compounds):
        raise ThermoMLValidationError("Compound identifiers are not unique.")
    for dataset in datasets:
        for local_id in dataset.component_ids:
            if local_id not in compound_ids:
                raise ThermoMLReferenceError(
                    f"Dataset {dataset.number} references missing component {local_id}."
                )
        property_numbers = {item.number for item in dataset.properties}
        variable_numbers = {item.number for item in dataset.variables}
        referenced_components = {
            item.component_id
            for item in (*dataset.properties, *dataset.variables, *dataset.constraints)
            if item.component_id is not None
        }
        missing_components = referenced_components - compound_ids
        if missing_components:
            raise ThermoMLReferenceError(
                f"Dataset {dataset.number} references missing component(s) "
                f"{sorted(missing_components)} in quantity metadata."
            )
        for point in dataset.points:
            missing_properties = {
                value.number for value in point.property_values
            } - property_numbers
            missing_variables = {value.number for value in point.variable_values} - variable_numbers
            if missing_properties or missing_variables:
                raise ThermoMLReferenceError(
                    f"Dataset {dataset.number}, point {point.index} has unresolved "
                    f"properties {sorted(missing_properties)} or variables "
                    f"{sorted(missing_variables)}."
                )


def validate_xml_schema(source: XMLSource, schema: str | Path) -> None:
    """Validate a ThermoML XML source against an explicit local XSD.

    The package intentionally does not fetch a mutable schema URL implicitly.
    Callers should pin and checksum the schema used by their workflow.
    """
    data, _ = _read_source(source)
    try:
        import xmlschema

        validator = xmlschema.XMLSchema(str(schema))
        validator.validate(io.BytesIO(data))
    except Exception as exc:
        raise ThermoMLValidationError(
            f"ThermoML document does not validate against {schema!s}: {exc}"
        ) from exc


def _document_from_root(
    root: Element,
    *,
    provenance: SourceProvenance,
    extra_warnings: tuple[str, ...] = (),
) -> ThermoMLDocument:
    """Decode one already constructed ThermoML element tree."""
    if _local_name(root.tag) != "DataReport":
        raise ThermoMLParseError(
            f"Expected ThermoML DataReport root, found {_local_name(root.tag)!r}."
        )
    if root.tag.startswith("{"):
        namespace = root.tag[1:].split("}", maxsplit=1)[0]
        if namespace != THERMOML_NAMESPACE:
            raise ThermoMLParseError(f"Unexpected ThermoML namespace {namespace!r}.")
    version = _child(root, "Version")
    citation_element = _child(root, "Citation")
    if version is None or citation_element is None:
        raise ThermoMLParseError("ThermoML DataReport requires Version and Citation.")
    major = _integer(
        _child_text(version, "nVersionMajor"),
        context="ThermoML major version",
        required=True,
    )
    minor = _integer(
        _child_text(version, "nVersionMinor"),
        context="ThermoML minor version",
        required=True,
    )
    assert major is not None and minor is not None
    compounds = tuple(_parse_compound(item) for item in _children(root, "Compound"))
    datasets = tuple(
        _parse_dataset(item, index)
        for index, item in enumerate(_children(root, "PureOrMixtureData"), start=1)
    )
    _validate_references(compounds, datasets)
    reaction_count = len(_children(root, "ReactionData"))
    warnings = list(extra_warnings)
    if reaction_count:
        warnings.append(
            f"Document contains {reaction_count} ReactionData entries; the initial "
            "release records their presence but does not decode reaction datasets."
        )
    return ThermoMLDocument(
        version_major=major,
        version_minor=minor,
        citation=_parse_citation(citation_element),
        compounds=compounds,
        datasets=datasets,
        provenance=provenance,
        warnings=tuple(warnings),
        reaction_dataset_count=reaction_count,
    )


def _json_scalar_text(value: object, *, context: str) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str | int | Decimal):
        return str(value)
    raise ThermoMLParseError(
        f"Official ThermoML JSON field {context!r} has unsupported scalar type "
        f"{type(value).__name__!r}."
    )


def _json_object_children(parent: Element, value: dict[str, Any], *, context: str) -> None:
    ordering = value.get("tml_elements")
    if not isinstance(ordering, list) or any(not isinstance(item, str) for item in ordering):
        raise ThermoMLParseError(
            f"Official ThermoML JSON object {context!r} requires a string "
            "tml_elements ordering list."
        )
    for name in cast(list[str], ordering):
        if not _JSON_ELEMENT_NAME.fullmatch(name):
            raise ThermoMLParseError(f"Invalid ThermoML JSON element name {name!r}.")
        if name not in value:
            # NIST JSON sometimes uses this list as schema ordering and names
            # optional elements that are absent from the object. Absence must
            # not be converted into a semantically different empty XML node.
            continue
        raw_children = value[name]
        children = raw_children if isinstance(raw_children, list) else [raw_children]
        for index, child_value in enumerate(children):
            child = Element(f"{{{THERMOML_NAMESPACE}}}{name}")
            parent.append(child)
            child_context = f"{context}.{name}[{index}]"
            if isinstance(child_value, dict):
                _json_object_children(child, child_value, context=child_context)
            elif isinstance(child_value, list):
                raise ThermoMLParseError(
                    f"Nested array without an element name at {child_context!r}."
                )
            else:
                child.text = _json_scalar_text(child_value, context=child_context)


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite numeric constant {value}")


def parse_thermoml(
    source: XMLSource,
    *,
    source_label: str | None = None,
    retrieved_at: datetime | None = None,
    schema: str | Path | None = None,
) -> ThermoMLDocument:
    """Parse a ThermoML XML document into immutable scientific objects.

    Parameters
    ----------
    source:
        XML bytes, XML text, a local path, or a binary file object.
    source_label:
        Provenance locator overriding an inferred local path.
    retrieved_at:
        Retrieval timestamp for network-originated bytes.
    schema:
        Optional explicit XSD path. The parser never downloads a mutable schema
        implicitly.

    Returns
    -------
    ThermoMLDocument
        Parsed document with SHA-256 provenance and resolved local references.

    Raises
    ------
    ThermoMLParseError
        If required XML structure or numeric fields are malformed.
    ThermoMLValidationError
        If XSD or semantic reference validation fails.

    Notes
    -----
    This parser is an original implementation of the IUPAC ThermoML schema.
    It currently decodes ``PureOrMixtureData`` fully. ``ReactionData`` entries
    are counted and reported as unsupported warnings rather than silently
    represented as mixture data.

    References
    ----------
    M. Frenkel et al., "XML-based IUPAC standard for experimental, predicted,
    and critically evaluated thermodynamic property data storage and capture",
    Pure Appl. Chem. 78 (2006) 541-612. DOI: 10.1351/pac200678030541.
    """
    data, inferred_label = _read_source(source)
    if schema is not None:
        validate_xml_schema(data, schema)
    try:
        root = SafeElementTree.fromstring(data)
    except (SafeElementTree.ParseError, DefusedXmlException) as exc:
        raise ThermoMLParseError(f"Invalid or unsafe ThermoML XML: {exc}") from exc
    return _document_from_root(
        root,
        provenance=SourceProvenance(
            locator=source_label or inferred_label,
            sha256=hashlib.sha256(data).hexdigest(),
            retrieved_at=retrieved_at,
        ),
    )


def parse_thermoml_json(
    source: JSONSource,
    *,
    source_label: str | None = None,
    retrieved_at: datetime | None = None,
    recovery: SourceRecovery | None = None,
) -> ThermoMLDocument:
    """Parse the official NIST JSON representation of a ThermoML document.

    NIST JSON objects carry ``tml_elements`` lists that preserve XML element
    ordering. The parser reconstructs an in-memory ThermoML tree and sends it
    through the same semantic decoder and reference validation used for XML.
    The source SHA-256 always describes the exact JSON bytes parsed.

    Notes
    -----
    JSON numbers are loaded directly as :class:`~decimal.Decimal`, without a
    binary floating-point round trip. Nevertheless, the JSON representation
    may not preserve the exact lexical decimal spelling used in related XML.
    This limitation is also recorded in ``ThermoMLDocument.warnings``.
    """
    data, inferred_label = _read_json_source(source)
    try:
        decoded = json.loads(
            data,
            parse_float=Decimal,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ThermoMLParseError(f"Invalid official ThermoML JSON: {exc}") from exc
    if not isinstance(decoded, dict):
        raise ThermoMLParseError("Official ThermoML JSON root must be an object.")
    value = cast(dict[str, Any], decoded)
    root = Element(f"{{{THERMOML_NAMESPACE}}}DataReport")
    _json_object_children(root, value, context="DataReport")
    related_md5 = value.get("THERMOML_MD5_CHECKSUM")
    if related_md5 is not None and (
        not isinstance(related_md5, str) or re.fullmatch(r"[0-9a-fA-F]{32}", related_md5) is None
    ):
        raise ThermoMLParseError("THERMOML_MD5_CHECKSUM must be a 32-digit hex value.")
    return _document_from_root(
        root,
        provenance=SourceProvenance(
            locator=source_label or inferred_label,
            sha256=hashlib.sha256(data).hexdigest(),
            retrieved_at=retrieved_at,
            media_type="application/json",
            related_xml_md5=related_md5.casefold() if related_md5 else None,
            recovery=recovery,
        ),
        extra_warnings=(_JSON_LEXICAL_WARNING,),
    )


def load_thermoml_url(
    url: str,
    *,
    timeout: float = 30.0,
    max_bytes: int = DEFAULT_MAX_DOWNLOAD_BYTES,
    schema: str | Path | None = None,
    json_fallback: Literal["never", "on_xml_error"] = "on_xml_error",
) -> ThermoMLDocument:
    """Download and parse one HTTPS ThermoML document with size limits.

    Remote bytes are held in memory and are not persisted by this function.
    The source URL, checksum, and UTC retrieval time are stored as provenance.
    """
    if json_fallback not in {"never", "on_xml_error"}:
        raise ValueError("json_fallback must be 'never' or 'on_xml_error'.")
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ThermoMLDownloadError("Only HTTPS ThermoML URLs are accepted.")
    request = Request(url, headers={"User-Agent": "thermoml-io/0.1"})
    try:
        with urlopen(request, timeout=timeout) as response:
            declared_length = response.headers.get("Content-Length")
            if declared_length and int(declared_length) > max_bytes:
                raise ThermoMLDownloadError(
                    f"Remote document declares {declared_length} bytes; limit is {max_bytes}."
                )
            data = response.read(max_bytes + 1)
    except (HTTPError, URLError, TimeoutError, ValueError) as exc:
        raise ThermoMLDownloadError(f"Could not download {url!r}: {exc}") from exc
    if len(data) > max_bytes:
        raise ThermoMLDownloadError(
            f"Remote document exceeded the {max_bytes}-byte download limit."
        )
    retrieved_at = datetime.now(UTC)
    try:
        return parse_thermoml(
            data,
            source_label=url,
            retrieved_at=retrieved_at,
            schema=schema,
        )
    except ThermoMLParseError as xml_error:
        if json_fallback == "never" or not parsed.path.casefold().endswith(".xml"):
            raise
        json_url = parsed._replace(path=f"{parsed.path[:-4]}.json").geturl()
        recovery = SourceRecovery(
            strategy="paired-nist-json",
            failed_locator=url,
            failed_sha256=hashlib.sha256(data).hexdigest(),
            failed_media_type="application/xml",
            failure_type=type(xml_error).__name__,
            failure_message=str(xml_error),
        )
        try:
            document = load_thermoml_json_url(
                json_url,
                timeout=timeout,
                max_bytes=max_bytes,
                recovery=recovery,
            )
            xml_md5 = hashlib.md5(data, usedforsecurity=False).hexdigest()
            if document.provenance.related_xml_md5 != xml_md5:
                raise ThermoMLParseError(
                    "Paired official JSON does not report the MD5 checksum of the failed XML bytes."
                )
            return document
        except ThermoMLError as json_error:
            raise ThermoMLParseError(
                f"XML failed ({xml_error}); paired official JSON also failed ({json_error})."
            ) from json_error


def load_thermoml_json_url(
    url: str,
    *,
    timeout: float = 30.0,
    max_bytes: int = DEFAULT_MAX_DOWNLOAD_BYTES,
    recovery: SourceRecovery | None = None,
) -> ThermoMLDocument:
    """Download and parse one official NIST ThermoML JSON document safely."""
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ThermoMLDownloadError("Only HTTPS ThermoML URLs are accepted.")
    request = Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "thermoml-io/0.1"},
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            declared_length = response.headers.get("Content-Length")
            if declared_length and int(declared_length) > max_bytes:
                raise ThermoMLDownloadError(
                    f"Remote document declares {declared_length} bytes; limit is {max_bytes}."
                )
            data = response.read(max_bytes + 1)
    except (HTTPError, URLError, TimeoutError, ValueError) as exc:
        raise ThermoMLDownloadError(f"Could not download {url!r}: {exc}") from exc
    if len(data) > max_bytes:
        raise ThermoMLDownloadError(
            f"Remote document exceeded the {max_bytes}-byte download limit."
        )
    return parse_thermoml_json(
        data,
        source_label=url,
        retrieved_at=datetime.now(UTC),
        recovery=recovery,
    )
