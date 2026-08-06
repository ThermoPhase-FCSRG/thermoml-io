# Search and ranking

Search operates on parsed documents and never contacts a service implicitly.
Before dataset selection, a collection-wide component index connects aliases
through shared InChIKey, standard InChI, or CAS identifiers. Components accept
exact reported common, IUPAC, and CAS names, formulas, CAS numbers, InChI, or
InChIKey, case-insensitively.

```python
water = collection.resolve_component("water")
assert water == collection.resolve_component("formula:H2O")
```

The supported prefixes are `name:`, `common:`, `iupac:`, `cas-name:`,
`formula:`, `cas:`, `inchi:`, and `inchikey:`. An unprefixed string searches
all reported identifier types.

If a query maps to more than one strong identity, resolution raises
`AmbiguousComponentError`. Formula `C4H10`, for example, must not silently
combine n-butane and isobutane. A query with no exact indexed match raises
`ComponentNotFoundError` rather than returning a misleading empty result.

## Exact system search

```python
matches = collection.search(
    system=("H2O", "CO2"),
    data_type="VLE",
    limit=10,
)
```

Component order does not matter. Exact matching rejects ternary datasets that
merely contain water and carbon dioxide.

## Component policies

```python
matches = collection.search(
    components="CO2",
    component_match="contains",
    property_name="solubility",
    limit=20,
)
```

The explicit modes are:

- `exact`: the dataset system is exactly the supplied component set;
- `contains`: all supplied components are mandatory and extras are allowed;
- `within`: every dataset component must belong to the supplied pool, while
  `required_components` identifies the mandatory subset.

For example, this accepts H2O + CO2 and H2O + CO2 + CH4, but rejects systems
containing a component outside the pool:

```python
matches = collection.search(
    components=("H2O", "CO2", "CH4"),
    required_components=("H2O", "CO2"),
    component_match="within",
)
```

## Property versus an independent variable

```python
matches = collection.search(
    components="H2",
    component_match="contains",
    data_type="transport",
    property_name="viscosity",
    independent_variable="pressure",
)
```

`independent_variable` matches a reported ThermoML variable, not a fixed
constraint. The property table flattens the selected x value while preserving
all other variables and constraints as metadata.

## Ranking semantics

Each result reports `observation_count`, defined as the number of individual
property-variable relationships satisfying the filters when an independent
variable is requested, otherwise matching property values. Results are sorted
by descending count and deterministic identifiers. `limit` is applied only
after sorting. Thus `limit=10` selects the ten densest matching experimental
datasets.

The friendly `VLE`, `LLE`, and `SLE` categories are conservative derived views
based on the ThermoML property group and explicitly reported phases. The
original property group remains available in every result and table.

## Explicit PubChem resolution

External enrichment is separate from source-reported ThermoML metadata:

```python
from thermoml_io import resolve_pubchem_component

hydrogen = resolve_pubchem_component("molecular hydrogen")
matches = collection.search(
    components=hydrogen,
    data_type="transport",
    property_name="viscosity",
)
```

`resolve_pubchem_component()` uses the official PUG REST service only when
called directly. It accepts the `name`, `cid`, `smiles`, `inchikey`, and
`formula` namespaces. Multiple PubChem records sharing the same structural
identity are merged; distinct identities raise `AmbiguousComponentError`.
