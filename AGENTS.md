# Repository instructions for AI coding agents

## Scope and purpose

This file applies to the entire `thermoml-io` repository. The package provides
a faithful, provenance-aware Python representation of ThermoML experimental
data. Scientific meaning, metrological metadata, traceability, and explicit
failure are product requirements.

The current checkout is the source of truth. Inspect implementation, tests,
notebooks, standards references, and documentation before changing behavior.

## Original implementation and sources

- Preserve an original implementation derived from the normative IUPAC
  ThermoML schema, primary ThermoML recommendations, and this project's
  documented requirements.
- When prose and the XSD disagree, treat the explicitly pinned XSD as
  normative and add a regression documenting the selected interpretation.
- Never silently infer missing experimental metadata.

## Scientific data model

- Preserve original values, units, lexical numeric representation, significant
  digits, phases, component links, solvent links, constraints, methods,
  repeatability, device specifications, and uncertainty assessments.
- Use `Decimal` at the ingestion boundary. Conversion to binary floating point
  is an explicit downstream operation.
- Document-local numbers are references, not global chemical identifiers.
- Keep source metadata immutable and separate from optional external
  enrichment.
- Search and ranking metrics must state whether counts refer to documents,
  datasets, data points, or individual property observations.
- `limit` is applied after deterministic ranking, never before.
- Never catch broad exceptions in a way that drops scientific content.

## Data rights and provenance

- Do not vendor or commit publisher ThermoML XML, archive snapshots, articles,
  or extracted experimental tables.
- Tests use project-generated synthetic fixtures or sources with an explicit
  redistribution license recorded in `tests/data/rights.yaml`.
- Network-downloaded and exported data belong under ignored
  `notebooks/local-only/` or another user-selected external path.
- Wheels and source distributions exclude notebooks, tests, scripts, caches,
  and experimental data.
- Every parsed source records a locator when available, SHA-256 checksum, and
  retrieval timestamp for network inputs.

## API and dependencies

- Prefer frozen dataclasses and typed free functions.
- Public APIs require NumPy-style docstrings documenting semantics, units,
  failure behavior, assumptions, and relevant standards.
- Keep runtime dependencies purposeful. pandas, PyArrow, PyYAML, plotting, and
  notebook tooling remain optional.
- Do not add `torch-flash` or PyTorch as a dependency. Downstream adapters own
  tensor conversion.
- Maintain Python 3.11+ and Linux, macOS, and Windows compatibility.

## Tests, notebooks, and documentation

- Maintain at least 99% branch-aware coverage.
- Test XSD/semantic failures, unresolved references, significant digits,
  uncertainty linkage, system classification, search ranking, truncation, and
  every export format.
- Notebook pairs use Jupytext `ipynb,py:percent`. Edit `.py`, synchronize, then
  execute `.ipynb` from a fresh kernel.
- Notebooks consume public package APIs; reusable parsing, search, aggregation,
  or ranking logic belongs under `src/thermoml_io/`.
- Build MkDocs with `--strict` and validate wheel/sdist boundaries before
  release.

## Definition of done

Run the applicable Pixi tasks for lint, format, typing, 99% branch coverage,
data rights, notebook synchronization/execution, strict docs, build metadata,
and distribution contents. Report exactly what passed and any unexecuted or
uncertain checks.
