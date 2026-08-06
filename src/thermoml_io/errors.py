"""Domain-specific exceptions raised by :mod:`thermoml_io`."""

from __future__ import annotations


class ThermoMLError(Exception):
    """Base class for all package-specific errors."""


class ThermoMLParseError(ThermoMLError):
    """Raised when an input cannot be interpreted as a ThermoML document."""


class ThermoMLValidationError(ThermoMLError):
    """Raised when XML or semantic validation fails."""


class ThermoMLReferenceError(ThermoMLValidationError):
    """Raised when a local ThermoML reference cannot be resolved."""


class ThermoMLDownloadError(ThermoMLError):
    """Raised when a remote ThermoML resource cannot be downloaded safely."""


class ThermoMLSourceError(ThermoMLError):
    """Raised when an upstream archive registry or metadata record is invalid."""


class ThermoMLArchiveError(ThermoMLError):
    """Raised when a bulk archive cannot be read as a ThermoML source."""


class ComponentResolutionError(ThermoMLError):
    """Base class for explicit chemical-identity resolution failures."""


class ComponentNotFoundError(ComponentResolutionError, LookupError):
    """Raised when no indexed chemical identity matches a component query."""


class AmbiguousComponentError(ComponentResolutionError, ValueError):
    """Raised when a component query maps to multiple chemical identities."""


class PubChemResolutionError(ComponentResolutionError):
    """Raised when an explicitly requested PubChem resolution fails."""


class OptionalDependencyError(ThermoMLError, ImportError):
    """Raised when an explicitly requested exporter is not installed."""
