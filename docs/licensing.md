# Provenance, licensing, and data rights

The `thermoml-io` source code is BSD-3-Clause. That license applies only to the
software created in this repository.

LNCC and UDESC names and logos identify the institutions where the project is
developed. They remain the property of their respective owners and are not
covered by the software license; see `THIRD_PARTY_NOTICES.md` for source and
usage links.

## Experimental data

The package does not redistribute:

- NIST ThermoML Archive XML or JSON;
- journal articles or supplements;
- extracted experimental tables;
- cached downloads;
- user-generated CSV, YAML, JSON, or Parquet exports.

Public availability and a citation request do not automatically grant general
redistribution permission. Users must determine the terms of every processed
source. The NIST ThermoML page states that archive files are available with
permission from cooperating journal publishers; this project does not extend
or reinterpret that permission.

## Required provenance

Each parsed document records its source locator when available, SHA-256 digest,
media type, and retrieval timestamp for network inputs. Official JSON also
records the related XML MD5 supplied by NIST. When JSON is used to recover a
malformed XML, exported metadata repeats both serializations' locators and
SHA-256 digests plus the original parsing exception. Exported tables repeat
the document DOI and publication title on every observation row.

Scientific work should cite:

1. the original publication represented by the ThermoML document;
2. the ThermoML Archive and IUPAC standard as requested by NIST; and
3. the exact `thermoml-io` release used for ingestion.

## Repository fixtures

`tests/data/rights.yaml` is the machine-readable rights ledger. The only
versioned XML fixture is a project-generated synthetic document containing no
published experimental measurements.

The IUPAC supplementary schema and use cases are represented only by an
external URL and checksum in `conformance_sources.json`. The PDF and its
examples are not packaged, and conformance sources cannot enter experimental
queries.
