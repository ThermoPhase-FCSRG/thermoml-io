# Tables and export

Property queries have two complementary tabular views:

- `result.analysis_table` is the default user-facing table. It has one row per
  reported property observation and ordinary physical columns such as
  `Temperature, K`, `Pressure, kPa`, and `Viscosity, Pa*s`.
- `result.table` is the lossless internal view. It preserves the decoded
  ThermoML structure for audits and custom transformations.

## Analysis-ready table

```python
result.write_csv("notebooks/local-only/viscosity-pressure.csv")
frame = result.analysis_table.to_pandas()
```

A representative CSV has the following shape:

```text
"Temperature, K","Pressure, kPa","Viscosity, Pa*s",DOI,Authors/Year,System,System Type,Phases,Method,Data Category,Dataset,metadata
298.15,5000,0.0000142,10.xxxx/example,"Author et al. (2020)",hydrogen,pure,Gas,...
```

Quantity names and units are not guessed or converted: the column label is the
exact name reported by ThermoML, and the value retains its original decimal
text. Consumers should perform unit conversion and binary floating-point
conversion explicitly.

Temperature columns are ordered before pressure, followed by composition and
other conditions, the measured property, and identification metadata. A query
that returns more than one exact property creates one value column for each
reported property name; unrelated cells remain empty.

If an identical quantity label has more than one meaning within the same
observation, `thermoml-io` qualifies the columns by source, phase, or component.
Phase or component differences that occur only between rows remain in
`metadata`, keeping the main physical columns compact. The library never
silently merges two distinct conditions. An indistinguishable duplicate in one
observation is rejected because choosing one value would lose scientific
meaning.

The scalar columns include:

- `DOI` and `Authors/Year` for identification and plot legends;
- `System`, `System Type`, and `Phases`;
- `Method`, `Data Category`, and the stable `Dataset` key; and
- `metadata`, a compact JSON object containing the remaining traceability and
  metrology information.

The `metadata` object retains the full APA citation and BibTeX entry, title,
authors, journal fields, TRC reference, source locator and SHA-256 digest,
dataset compiler/contributor fields, compound identifiers, sample and purity
records, property definition, significant digits, all reported uncertainty and
repeatability assessments, device specifications, and complete condition
descriptors. JSON newlines are escaped, so every observation remains one CSV
record.

## Formats

All result-level exporters use the analysis-ready layout:

```python
result.write("results.csv")
result.write_json("results.json")
result.write_yaml("results.yaml")
result.write_parquet("results.parquet")
```

CSV and JSON require no exporter dependency. YAML requires PyYAML and Parquet
requires PyArrow. The package raises `OptionalDependencyError` when a requested
optional exporter is unavailable. JSON, YAML, and Parquet record the
`thermoml-io.analysis-table.v1` schema identifier.

## Lossless representation

Use the detailed structural view only when it is needed explicitly:

```python
result.write_lossless("results-lossless.parquet")
lossless_frame = result.table.to_pandas()
```

`build_experimental_table()` and `build_property_table()` also return this
lossless representation. Its stable scalar columns contain the publication,
source, dataset, system, property, phase, method, value, and significant-digit
fields. Samples, variables, constraints, uncertainties, repeatability, and
device specifications are complete JSON structures. This is intentionally an
audit/interchange layer, not the default CSV for model fitting.

`build_analysis_table(result.table)` performs the public, deterministic
transformation when a derived query table is being handled directly.

## Property-condition semantics

The independent variable and every complementary point variable or fixed
constraint are promoted to physical columns in the analysis-ready table. Their
role, source (`variable` or `constraint`), phase, component link, significant
digits, uncertainty, repeatability, and device metadata remain in
`metadata.conditions`.

Plotting and regression code should group data using the complete complementary
condition signature. For example, viscosity versus temperature points measured
at different pressures must not be connected as one series merely because they
come from the same publication.

Each property-condition query should be exported separately, rather than
combining different x-axis semantics in one CSV.

## Data boundary

Export paths are user-controlled. Repository examples use the ignored
`notebooks/local-only/` directory. Generated tables are not part of the Python
distribution.
