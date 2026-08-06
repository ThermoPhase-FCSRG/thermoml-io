<section class="tp-hero">
  <div class="tp-hero__copy">
    <span class="tp-kicker">Scientific data · ThermoML</span>
    <h1>Experimental thermodynamics, with provenance intact</h1>
    <p class="tp-hero__lead">
      <code>thermoml-io</code> reads, searches, and exports ThermoML without
      flattening away the scientific and metrological context needed to
      interpret each reported value.
    </p>
    <p class="tp-hero__actions">
      <a href="getting-started/" class="md-button md-button--primary">Get started</a>
      <a href="data-model/" class="md-button">Explore the data model</a>
    </p>
  </div>
  <div class="tp-hero__identity">
    <div class="tp-logo-plate">
      <a href="https://github.com/ThermoPhase-FCSRG" class="tp-logo-plate__brand">
        <img
          src="assets/branding/thermophase-horizontal.png"
          alt="ThermoPhase — Fluid and Complex Systems Research Group"
        />
      </a>
      <div class="tp-affiliation">
        <span>Developed at</span>
        <div class="tp-affiliation__logos">
          <a href="https://www.gov.br/lncc/pt-br">
            <img
              src="assets/branding/lncc.svg"
              alt="Laboratório Nacional de Computação Científica — LNCC"
            />
          </a>
          <a href="https://www.udesc.br/">
            <img
              src="assets/branding/udesc-horizontal.jpg"
              alt="Universidade do Estado de Santa Catarina — UDESC"
            />
          </a>
        </div>
      </div>
    </div>
  </div>
</section>

<div class="tp-feature-grid">
  <div class="tp-feature">
    <strong>Faithful ingestion</strong>
    <span>Original decimal values, units, significant digits, phases, methods, and uncertainties remain explicit.</span>
  </div>
  <div class="tp-feature">
    <strong>Deterministic discovery</strong>
    <span>Systems and properties are ranked by stated observation counts before any result limit is applied.</span>
  </div>
  <div class="tp-feature">
    <strong>Auditable provenance</strong>
    <span>Source locators, checksums, retrieval metadata, citations, and recovery events travel with the data.</span>
  </div>
</div>

`thermoml-io` is developed by the
[ThermoPhase — Fluid and Complex Systems Research Group](https://github.com/ThermoPhase-FCSRG)
at the [Laboratório Nacional de Computação Científica (LNCC)](https://www.gov.br/lncc/pt-br)
and the [Universidade do Estado de Santa Catarina (UDESC)](https://www.udesc.br/).

The initial release provides:

- safe XML parsing, official NIST JSON parsing, and optional XML validation
  against an explicit XSD;
- immutable Python models for `PureOrMixtureData`;
- deterministic system/property search and density-based ranking;
- aggregation across publications without confusing document-local IDs;
- bounded-memory analysis of local bulk `.tgz` archives;
- automatic checksum-verified archive fetching and a live-updated source
  registry;
- XML-first recovery through paired official JSON with explicit provenance;
- independent monthly monitoring of bulk metadata and live Cordra IDs;
- property-versus-condition queries ranked by publication, with one table per
  query;
- descriptive rankings for systems, components, data types, properties,
  methods, and publications;
- analysis-ready CSV, JSON, YAML, and Parquet export, with a separate lossless
  provenance view.

!!! important "No experimental data is distributed"

    The package contains no NIST archive snapshot, publisher XML, extracted
    experimental table, or journal content. Network inputs and exports remain
    under user control and retain their original terms.

The repository notebooks download a checksum-pinned NIST snapshot only into
the ignored `notebooks/local-only/` directory. The snapshot is not part of the
repository, documentation site, wheel, or source distribution.

## Design boundary

The parsed scientific model is the source of truth. Tables are derived views,
not a replacement for the hierarchical ThermoML record. Downstream numerical
packages such as `torch-flash` should perform unit conversion and tensor
construction explicitly.

## Current scope

Version 0.1 decodes pure-compound and mixture datasets. Reaction datasets are
detected and counted, but their typed representation is planned for a later
release. This limitation is reported explicitly on each document.

## How to cite

If you use `thermoml-io` in research, please cite its all-versions Zenodo
record:

> Volpatto, Diego; Marinho, Antonio; Ribeiro, Gustavo (2026). *thermoml-io*.
> Zenodo. [https://doi.org/10.5281/zenodo.21825084](https://doi.org/10.5281/zenodo.21825084)

```bibtex
@software{volpatto_thermoml_io_2026,
  author = {Volpatto, Diego and Marinho, Antonio and Ribeiro, Gustavo},
  title = {thermoml-io},
  year = {2026},
  publisher = {Zenodo},
  doi = {10.5281/zenodo.21825084},
  url = {https://doi.org/10.5281/zenodo.21825084}
}
```

This concept DOI always refers to the project as a whole and resolves to its
latest archived release. For exact reproducibility, cite the version-specific
DOI shown on the corresponding Zenodo release instead.
