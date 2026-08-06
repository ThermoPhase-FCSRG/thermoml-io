# Contributing

Contributions must preserve scientific meaning, metrological metadata, source
provenance, and explicit failure behavior. The pinned IUPAC ThermoML XSD is the
normative reference when it conflicts with descriptive prose. Never infer
missing experimental metadata or silently discard unsupported scientific
content.

## Development workflow

Install [Pixi](https://pixi.sh), then create the default environment:

```bash
pixi install
```

Before opening a pull request, run the applicable quality gates:

```bash
pixi run lint
pixi run format-check
pixi run typecheck
pixi run test-cov
pixi run sync-deps-check
pixi run check-data-rights
pixi run -e docs docs-check
pixi run build
pixi run -e default twine check dist/*
pixi run check-dist
```

Tests must retain at least 99% branch-aware coverage. A new schema
interpretation needs a project-generated synthetic regression that
distinguishes the selected behavior. Tests should cover unresolved references,
significant digits, uncertainty linkage, system classification, deterministic
ranking, truncation, and any affected export formats.

## Scientific model and provenance

Use `Decimal` at the ingestion boundary and preserve the original lexical
numeric representation. Keep document-local component numbers separate from
global chemical identifiers. Search and ranking changes must state whether
counts refer to documents, datasets, data points, or property observations;
apply `limit` only after deterministic ranking.

Every parsed network source must retain its locator, SHA-256 checksum, and
retrieval timestamp. External enrichment must remain optional and separate
from immutable source metadata.

## Data rights

Do not commit publisher ThermoML XML, archive snapshots, journal articles, or
extracted experimental tables. Tests may use only project-generated synthetic
fixtures or sources whose redistribution license is recorded in
`tests/data/rights.yaml`.

Network downloads and exports belong under the ignored
`notebooks/local-only/` directory or another user-controlled path. A scientific
citation establishes provenance but does not grant redistribution rights.

## Dependency metadata

Declare dependency constraints in `pixi.toml`; do not maintain a second set of
constraints manually in `pyproject.toml`. After changing a dependency, run:

```bash
pixi run sync-deps
pixi run sync-deps-check
pixi lock --check
```

The Pixi `core` feature becomes the ordinary `pip install thermoml-io`
dependency set. Only package capabilities are exported as pip extras:

| Capability | Pip installation | Pixi feature |
| --- | --- | --- |
| YAML export | `pip install "thermoml-io[yaml]"` | `yaml` |
| Parquet export | `pip install "thermoml-io[parquet]"` | `parquet` |
| pandas integration | `pip install "thermoml-io[pandas]"` | `pandas` |
| YAML and Parquet export | `pip install "thermoml-io[export]"` | `export` |

Test, development, notebook, and documentation features remain Pixi-only.
Conda-to-PyPI name, version, or platform-marker translations belong in
`scripts/sync_deps.py`.

## Version and release metadata

Use the version task instead of editing version strings individually:

```bash
pixi run bump-version 0.1.1 --dry-run
pixi run bump-version 0.1.1
pixi lock
```

The task updates `pyproject.toml`, `pixi.toml`,
`src/thermoml_io/__init__.py`, and `CITATION.cff` together. It refuses to
proceed if their current versions disagree, so resolve any inconsistency
deliberately before a new bump.

Before creating the matching `v<version>` tag, rerun the quality, test,
documentation, data-rights, build, metadata, and distribution-content checks
listed above. Wheels and source distributions must exclude notebooks, tests,
scripts, caches, and experimental data.

## Notebooks and documentation

Notebook pairs use Jupytext `ipynb,py:percent`. Edit only the percent-format
`.py` source, then synchronize and execute the notebook from a fresh kernel:

```bash
pixi run -e notebooks notebooks-sync
pixi run -e notebooks notebooks-run
```

Reusable parsing, search, aggregation, or ranking logic belongs under
`src/thermoml_io/`; notebooks must consume public package APIs. Public APIs
need NumPy-style docstrings that state semantics, units, failure behavior,
assumptions, and relevant standards. Build documentation with `--strict`
through `pixi run -e docs docs-check`.

## Pull requests

Keep changes focused and describe:

- the normative schema or primary scientific source;
- preserved metadata and any deliberate interpretation;
- failure behavior and unresolved limitations;
- tests and independent validation performed; and
- the redistribution basis for every new fixture or data-derived artifact.

By contributing, you agree that your work is distributed under the
BSD-3-Clause license.
