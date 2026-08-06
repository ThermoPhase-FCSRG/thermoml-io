"""Shared fixtures for the thermoml-io test suite."""

from __future__ import annotations

from pathlib import Path

import pytest

from thermoml_io import ThermoMLCollection, parse_thermoml


@pytest.fixture
def fixture_path() -> Path:
    """Return the project-generated ThermoML fixture path."""
    return Path(__file__).parent / "fixtures" / "synthetic_thermoml.xml"


@pytest.fixture
def document(fixture_path: Path):
    """Return the parsed synthetic ThermoML document."""
    return parse_thermoml(fixture_path)


@pytest.fixture
def collection(document):
    """Return a one-document ThermoML collection."""
    return ThermoMLCollection((document,))
