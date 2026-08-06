# Getting started

## Install

```bash
pip install thermoml-io
```

For every exporter and pandas integration:

```bash
pip install "thermoml-io[export,pandas]"
```

## Load one source

```python
from thermoml_io import load_thermoml_url

document = load_thermoml_url(
    "https://trc.nist.gov/ThermoML/10.1016/j.fluid.2015.07.026.xml"
)

print(document.citation.normalized_doi)
print(document.schema_version)
print(document.provenance.sha256)
```

The loader accepts HTTPS only, applies a configurable size limit, and records
the source URL, checksum, and UTC retrieval time. It does not persist the XML.

Local files and in-memory bytes use `parse_thermoml`:

```python
from thermoml_io import parse_thermoml

document = parse_thermoml("path/to/user-supplied.xml")
```

## Validate against a pinned schema

Pass an explicit local schema to `parse_thermoml(..., schema=...)`. The package
does not silently fetch the live NIST XSD because that URL can change over
time. Record the schema checksum in the surrounding research workflow.

## Build a collection

```python
from thermoml_io import ThermoMLCollection

collection = ThermoMLCollection((document,))
```

The collection can search multiple publications while preserving the source
document for every result.
