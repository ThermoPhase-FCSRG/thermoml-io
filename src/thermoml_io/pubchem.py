"""Explicit, optional PubChem PUG REST component resolution."""

from __future__ import annotations

import json
from json import JSONDecodeError
from typing import Any, Literal
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from .errors import (
    AmbiguousComponentError,
    ComponentNotFoundError,
    PubChemResolutionError,
)
from .identity import ComponentIdentity, ComponentIndex

PubChemNamespace = Literal["name", "cid", "smiles", "inchikey", "formula"]
_NAMESPACES: frozenset[str] = frozenset({"name", "cid", "smiles", "inchikey", "formula"})
_PROPERTIES = "Title,IUPACName,MolecularFormula,InChI,InChIKey"
_BASE_URL = "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound"


def _read_response(response: Any, max_bytes: int) -> bytes:
    headers = getattr(response, "headers", {})
    declared = headers.get("Content-Length") if hasattr(headers, "get") else None
    if declared is not None:
        try:
            declared_size = int(declared)
        except ValueError as exc:
            raise PubChemResolutionError(
                f"PubChem returned an invalid Content-Length {declared!r}."
            ) from exc
        if declared_size > max_bytes:
            raise PubChemResolutionError(
                f"PubChem response declares {declared_size} bytes; limit is {max_bytes}."
            )
    data = response.read(max_bytes + 1)
    if not isinstance(data, bytes | bytearray):
        raise PubChemResolutionError("PubChem returned a non-binary response body.")
    if len(data) > max_bytes:
        raise PubChemResolutionError(
            f"PubChem response exceeded the {max_bytes}-byte download limit."
        )
    return bytes(data)


def _identity_from_property(
    record: dict[str, object], *, query: str, namespace: PubChemNamespace
) -> ComponentIdentity:
    title = record.get("Title")
    iupac = record.get("IUPACName")
    formula = record.get("MolecularFormula")
    inchi = record.get("InChI")
    inchikey = record.get("InChIKey")
    cid = record.get("CID")
    names = tuple(
        value
        for value in (
            query if namespace == "name" else None,
            title if isinstance(title, str) else None,
        )
        if value
    )
    preferred = next(
        (
            value
            for value in (
                title,
                iupac,
                formula,
                inchikey,
                query,
            )
            if isinstance(value, str) and value.strip()
        ),
        query,
    )
    return ComponentIdentity(
        preferred_name=preferred,
        common_names=names,
        iupac_names=(iupac,) if isinstance(iupac, str) else (),
        formulas=(formula,) if isinstance(formula, str) else (),
        standard_inchis=(inchi,) if isinstance(inchi, str) else (),
        standard_inchi_keys=(inchikey,) if isinstance(inchikey, str) else (),
        pubchem_cids=(cid,) if isinstance(cid, int) else (),
    )


def resolve_pubchem_component(
    query: str,
    *,
    namespace: PubChemNamespace = "name",
    timeout: float = 30.0,
    max_bytes: int = 2 * 1024 * 1024,
) -> ComponentIdentity:
    """Resolve one component through the official PubChem PUG REST service.

    Parameters
    ----------
    query:
        Exact PubChem input in the selected namespace, commonly a familiar
        chemical name such as ``"hydrogen"``.
    namespace:
        PubChem input namespace. Network resolution is always explicit; this
        function is never called implicitly by ThermoML search operations.
    timeout:
        Network timeout in seconds.
    max_bytes:
        Maximum accepted JSON response size.

    Returns
    -------
    ComponentIdentity
        Detached identity metadata suitable for a collection or archive query.

    Raises
    ------
    ComponentNotFoundError
        If PubChem reports no matching compound.
    AmbiguousComponentError
        If the input maps to more than one distinct chemical identity.
    PubChemResolutionError
        If the request or response cannot be processed safely.
    """
    cleaned = query.strip()
    if not cleaned:
        raise ValueError("PubChem component query must not be empty.")
    if namespace not in _NAMESPACES:
        raise ValueError(f"Unsupported PubChem namespace {namespace!r}.")
    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive.")
    encoded = quote(cleaned, safe="")
    url = f"{_BASE_URL}/{namespace}/{encoded}/property/{_PROPERTIES}/JSON"
    request = Request(url, headers={"User-Agent": "thermoml-io/0.1"})
    try:
        with urlopen(request, timeout=timeout) as response:
            data = _read_response(response, max_bytes)
    except HTTPError as exc:
        if exc.code == 404:
            raise ComponentNotFoundError(
                f"PubChem has no {namespace} match for {cleaned!r}."
            ) from exc
        raise PubChemResolutionError(
            f"PubChem request failed with HTTP status {exc.code}."
        ) from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise PubChemResolutionError(f"Could not query PubChem: {exc}") from exc

    try:
        payload = json.loads(data)
    except (JSONDecodeError, UnicodeDecodeError) as exc:
        raise PubChemResolutionError("PubChem returned invalid JSON.") from exc
    if not isinstance(payload, dict):
        raise PubChemResolutionError("PubChem returned an unexpected JSON document.")
    table = payload.get("PropertyTable")
    properties = table.get("Properties") if isinstance(table, dict) else None
    if not isinstance(properties, list) or not properties:
        raise ComponentNotFoundError(f"PubChem has no {namespace} match for {cleaned!r}.")
    records = [item for item in properties if isinstance(item, dict)]
    if len(records) != len(properties):
        raise PubChemResolutionError("PubChem returned malformed property records.")
    index = ComponentIndex.from_identities(
        _identity_from_property(item, query=cleaned, namespace=namespace) for item in records
    )
    if len(index.identities) > 1:
        labels = ", ".join(
            f"{item.preferred_name} [{item.stable_identifier}]" for item in index.identities
        )
        raise AmbiguousComponentError(
            f"PubChem {namespace} query {cleaned!r} is ambiguous: {labels}."
        )
    if not index.identities:  # pragma: no cover - records guarantee one identity
        raise ComponentNotFoundError(f"PubChem has no {namespace} match for {cleaned!r}.")
    return index.identities[0]
