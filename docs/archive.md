# Bulk archive analysis

The NIST/TRC bulk snapshot can contain millions of property observations. It
should not be loaded into one `ThermoMLCollection`. `analyze_thermoml_archive`
instead parses one XML member at a time, retains bounded aggregate counters,
and applies top-dataset truncation only after scanning the complete archive.

```python
from thermoml_io import analyze_thermoml_archive, fetch_thermoml_archive

archive = fetch_thermoml_archive()
analysis = analyze_thermoml_archive(
    archive,
    component="CURLTUGMZLYLDI-UHFFFAOYSA-N",
    serialized_prefilter="CURLTUGMZLYLDI-UHFFFAOYSA-N",
    top_datasets=10,
    on_error="collect",
)
```

Here the stable InChIKey byte sequence is only a performance prefilter. The
parsed component references decide whether a dataset belongs to the result.
This includes pure and multicomponent systems containing carbon dioxide.

## Failure semantics

XML is attempted first. With the default `json_fallback="on_xml_error"`, a
malformed XML is recovered only from its same-path official JSON member.
`analysis.recoveries` records the XML and JSON member names and hashes, the XML
exception, and the lexical-numeric limitation. A valid XML never uses JSON.

If the paired JSON is missing or invalid, strict mode raises
`ThermoMLArchiveError` with the member name. `on_error="collect"` records every
unrecovered failure in `analysis.failures`; there is no ignore mode. Use
`json_fallback="never"` to request XML-only behavior explicitly.

## Counts and rankings

`analysis.summary` distinguishes XML documents, datasets, `NumValues` points,
and individual property observations. Rankings for property groups, derived
data categories, properties, systems, components, methods, and publications
are observation-weighted. `dataset_system_types` separately counts datasets by
system order.

The archive is never extracted. Paired JSON is read only after an XML parsing
failure. The function does not distribute or copy the source snapshot. Keep
downloads under an ignored local-only path and record their DOI, version,
cutoff, and checksum.

## Catalog and property queries

`catalog_thermoml_archive()` scans the complete snapshot and lists every
observed category, exact property name, and independent-variable name. A query
can then return a property-versus-condition table with full citation metadata:

```python
from thermoml_io import (
    catalog_thermoml_archive,
    query_thermoml_archive,
)

catalog = catalog_thermoml_archive()
catalog.properties("transport")
catalog.independent_variables("transport", "viscosity")

components = catalog.component_index
h2 = components.resolve("hydrogen")

result = query_thermoml_archive(
    catalog.archive_path,
    components=h2,
    component_index=components,
    component_match="contains",
    data_category="transport",
    property_name="viscosity",
    independent_variable="pressure",
    publication_limit=10,
)
result.write_csv("h2-viscosity-pressure.csv")
```

Run one query per property-condition relation and write each result table to a
separate CSV. This keeps, for example, density-versus-pressure distinct from
density-versus-temperature. `write_csv()` creates one row per property
observation with physical columns such as `Temperature, K`, `Pressure, kPa`,
and the selected property, followed by DOI, authors/year, system, method,
dataset, and compact metadata. Every complementary point variable and fixed
constraint is promoted to a value column and also retained with its origin and
metrological details in `metadata.conditions`.

The complete structural representation is available as `result.table` or via
`result.write_lossless(...)`; it is not the default model-fitting CSV.

The publication limit is applied after the complete matching scan and is
ranked by returned property-variable rows. Byte prefilters are optional
performance hints; parsed component identity remains authoritative.

Friendly string queries are resolved by an archive-wide preliminary scan when
no index is supplied. Reuse `index_thermoml_archive()` or
`catalog.component_index` for multiple queries. Passing an already resolved
`ComponentIdentity` also avoids automatic indexing. None of these local paths
contacts an external chemical database.
