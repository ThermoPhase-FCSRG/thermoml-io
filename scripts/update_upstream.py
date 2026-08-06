"""Refresh both NERDm bulk and live Cordra ThermoML source registries."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from thermoml_io import (
    archive_source_record,
    cordra_snapshot_record,
    discover_archive_source,
    discover_cordra_snapshot,
)

ARCHIVE_REGISTRY = Path("src/thermoml_io/data/archive_sources.json")
CORDRA_REGISTRY = Path("src/thermoml_io/data/cordra_snapshot.json")


def _render(value: dict[str, object]) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False, sort_keys=False) + "\n"


def main() -> int:
    """Update the source registry, or report whether it is current."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--archive-registry", type=Path, default=ARCHIVE_REGISTRY)
    parser.add_argument("--cordra-registry", type=Path, default=CORDRA_REGISTRY)
    arguments = parser.parse_args()

    archive = discover_archive_source()
    cordra = discover_cordra_snapshot()
    updates = (
        (
            arguments.archive_registry,
            _render(archive_source_record(archive)),
            f"bulk archive {archive.filename}",
        ),
        (
            arguments.cordra_registry,
            _render(cordra_snapshot_record(cordra)),
            f"Cordra census {cordra.object_count} IDs",
        ),
    )
    changed = [
        (path, rendered, label)
        for path, rendered, label in updates
        if not path.exists() or path.read_text(encoding="utf-8") != rendered
    ]
    if not changed:
        print(
            f"ThermoML upstream registries are current: {archive.filename}; "
            f"Cordra has {cordra.object_count} IDs."
        )
        return 0
    if arguments.check:
        print("ThermoML upstream metadata changed: " + "; ".join(x[2] for x in changed))
        return 1
    for path, rendered, _label in changed:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered, encoding="utf-8")
    print("Updated ThermoML upstream metadata: " + "; ".join(x[2] for x in changed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
