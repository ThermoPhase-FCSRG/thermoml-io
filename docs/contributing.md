# Contributing

The complete repository contribution policy is available in
[CONTRIBUTING.md](https://github.com/ThermoPhase-FCSRG/thermoml-io/blob/main/CONTRIBUTING.md).

Scientific additions must preserve source values, units, lexical decimal
representation, significant digits, phases, component and uncertainty links,
and provenance. Pull requests must retain the 99% branch-aware coverage gate
and the package's explicit-failure behavior.

## Development environment

Install [Pixi](https://pixi.sh), clone the repository, and run:

```bash
pixi install
```

Use repository tasks instead of an ad hoc Python environment:

```bash
pixi run -e default lint
pixi run -e default format-check
pixi run -e default typecheck
pixi run -e default test-cov
pixi run -e default sync-deps-check
pixi run -e default check-data-rights
pixi run -e docs docs-check
```

## Notebooks

Notebooks use paired Jupytext files. Edit the percent-format `.py` source,
synchronize, then execute the `.ipynb` from a fresh kernel:

```bash
pixi run -e notebooks notebooks-sync
pixi run -e notebooks notebooks-run
```

Downloaded XML and generated tables must remain under the ignored
`notebooks/local-only/` directory or another user-controlled path.

## Scientific changes

New XML interpretations must cite the normative schema or primary ThermoML
recommendation and include a synthetic regression that distinguishes the
behavior. Never make missing metadata appear present and never discard an
unsupported element silently.

## Dependency and release metadata

`pixi.toml` is the source of truth for dependency constraints. Synchronize the
pip-facing metadata after changing it:

```bash
pixi run sync-deps
pixi run sync-deps-check
pixi lock --check
```

The `core` feature becomes the ordinary package dependency set. The `yaml`,
`parquet`, `pandas`, and `export` features are the only public pip extras;
development, test, notebook, and documentation features remain Pixi-only.

Synchronize a release version with:

```bash
pixi run bump-version 0.1.1 --dry-run
pixi run bump-version 0.1.1
pixi lock
```

This updates `pyproject.toml`, `pixi.toml`,
`src/thermoml_io/__init__.py`, and `CITATION.cff` together after verifying that
their current versions agree.

## Distribution

```bash
pixi run -e default build
pixi run -e default twine check dist/*
pixi run -e default check-dist
```

Wheels and source distributions must exclude tests, notebooks, scripts,
caches, and experimental data.
