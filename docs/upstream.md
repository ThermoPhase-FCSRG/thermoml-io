# Upstream registry and verified fetch

`thermoml-io` ships metadata, not experimental archive bytes. The packaged
`archive_sources.json` records the NIST PDR metadata endpoint, snapshot name,
size, SHA-256, snapshot date, and data DOI.

```python
from thermoml_io import fetch_thermoml_archive, get_archive_source

source = get_archive_source()
archive = fetch_thermoml_archive()
```

No archive URL or checksum is required. Existing cache files are reused only
after size and SHA-256 verification. Downloads use a temporary sibling and are
atomically moved into place after verification.

The default cache follows this precedence:

1. `THERMOML_IO_CACHE`;
2. `$XDG_CACHE_HOME/thermoml-io`;
3. `~/.cache/thermoml-io`.

An explicit `cache_dir` can be supplied without changing source identity.

## Monthly upstream maintenance

The `Monthly ThermoML Upstream Refresh` GitHub Actions workflow reads the
official NIST NERDm JSON endpoint and the live ThermoML Cordra API on the
second day of every month. The two checks are independent:

- NERDm detects a new bulk tar-compatible snapshot, checksum, or record
  revision;
- Cordra retrieves every `TRCTml4` ID and hashes the sorted set, detecting
  additions, removals, or replacements even when no new bulk file exists.

`get_cordra_snapshot()` exposes the packaged census metadata. Cordra contains
search metadata and summarized point counts, not the numerical observations;
numerical ingestion still uses the official XML/JSON documents. If either
registry differs, CI updates metadata only and opens a pull request. Tests and
the data-rights check run before that pull request is created.

The current packaged baseline has 11,922 Cordra IDs, whereas the pinned bulk
archive has 11,923 document pairs. The library deliberately does not infer a
cause or force one-to-one equivalence between independently published access
surfaces; it records and monitors each census separately.

Maintainers can run the same comparison locally:

```bash
pixi run -e default update-upstream --check
pixi run -e default update-upstream
```

## IUPAC conformance material

`list_conformance_sources()` exposes metadata for the external IUPAC ThermoML
4.0 schema and 14 supplementary use cases. The PDF is checksum-described but
is not packaged or downloaded automatically. These examples are parser
conformance material, not NIST experimental records, and are structurally
ineligible for archive queries.
