"""Thermodynamic classification helpers for ThermoML datasets."""

from __future__ import annotations

import re

from .models import DataSet, PropertyDefinition

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def normalize_term(value: str) -> str:
    """Normalize a user-facing search term for deterministic matching."""
    return _NON_ALNUM.sub("_", value.casefold()).strip("_")


def classify_property(
    property_definition: PropertyDefinition,
    dataset: DataSet,
) -> str:
    """Return a stable, human-readable category for a ThermoML property.

    The classification is a package-level view, not an IUPAC term. The source
    ``group`` and property name remain available and are never overwritten.
    Phase-equilibrium subtypes are inferred conservatively from the phases
    explicitly reported in the dataset.
    """
    group = normalize_term(property_definition.group)
    phases = {
        normalize_term(phase)
        for phase in (*dataset.phases, property_definition.phase or "")
        if phase
    }
    has_gas = bool(phases & {"gas", "vapor", "vapour"})
    has_liquid = any(phase.startswith("liquid") for phase in phases)
    has_solid = any(phase.startswith("solid") or phase == "crystal" for phase in phases)

    if group == "compositionatphaseequilibrium":
        if has_gas and has_liquid:
            return "VLE"
        if has_solid and has_liquid:
            return "SLE"
        liquid_phases = [phase for phase in phases if phase.startswith("liquid")]
        if len(liquid_phases) >= 2:
            return "LLE"
        return "phase equilibrium"

    categories = {
        "criticals": "critical property",
        "vaporpboilingtazeotroptandp": "vapor pressure and boiling",
        "phasetransition": "phase transition",
        "activityfugacityosmoticprop": "activity, fugacity, and osmotic",
        "volumetricprop": "volumetric",
        "heatcapacityandderivedprop": "caloric",
        "transportprop": "transport",
        "refractionsurfacetensionsoundspeed": "interfacial, optical, and acoustic",
        "excesspartialapparentenergyprop": "excess and partial energy",
        "reactionequilibriumprop": "reaction equilibrium",
        "reactionstatechangeprop": "reaction state change",
        "bioproperties": "biomaterial",
    }
    return categories.get(group, property_definition.group)
