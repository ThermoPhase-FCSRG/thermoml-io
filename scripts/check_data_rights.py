"""Check that every tracked test-data artifact has an explicit rights entry."""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
LEDGER = REPO_ROOT / "tests" / "data" / "rights.yaml"
DATA_SUFFIXES = {".csv", ".json", ".parquet", ".xml", ".yaml", ".yml"}


def main() -> int:
    """Validate the repository research-data boundary and rights ledger."""
    payload = yaml.safe_load(LEDGER.read_text(encoding="utf-8"))
    entries = payload.get("artifacts", [])
    recorded = {entry["path"]: entry for entry in entries}
    tracked_data = {
        path.relative_to(REPO_ROOT).as_posix()
        for directory in (REPO_ROOT / "tests" / "fixtures",)
        for path in directory.rglob("*")
        if path.is_file() and path.suffix.lower() in DATA_SUFFIXES
    }
    missing = sorted(tracked_data - recorded.keys())
    invalid = sorted(
        path for path, entry in recorded.items() if entry.get("status") not in {"generated", "open"}
    )
    forbidden = sorted(
        path.relative_to(REPO_ROOT).as_posix()
        for path in (REPO_ROOT / "notebooks").rglob("*")
        if path.is_file()
        and "local-only" not in path.parts
        and path.suffix.lower() in {".csv", ".json", ".parquet", ".xml", ".yaml"}
    )
    if missing or invalid or forbidden:
        if missing:
            print(f"Missing rights entries: {missing}", file=sys.stderr)
        if invalid:
            print(f"Non-redistributable tracked fixtures: {invalid}", file=sys.stderr)
        if forbidden:
            print(f"Tracked notebook data files are forbidden: {forbidden}", file=sys.stderr)
        return 1
    print(f"Data-rights boundary passed for {len(tracked_data)} tracked fixture(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
