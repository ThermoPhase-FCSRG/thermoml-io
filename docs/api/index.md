# API overview

The public API is intentionally small:

- parse local or in-memory XML/official NIST JSON with `parse_thermoml` and
  `parse_thermoml_json`;
- retrieve HTTPS inputs with `load_thermoml_url` or
  `load_thermoml_json_url`;
- aggregate and search with `ThermoMLCollection`;
- rank metadata coverage with `summarize_collection`;
- stream and rank bulk snapshots with `analyze_thermoml_archive`;
- build portable tables with `build_experimental_table`.

All public names are exported explicitly from `thermoml_io`.
