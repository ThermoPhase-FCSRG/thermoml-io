"""Validate the public wheel and source-distribution file boundary."""

from __future__ import annotations

import sys
import tarfile
import zipfile
from pathlib import Path

FORBIDDEN_PARTS = {"tests", "notebooks", "scripts", "__pycache__", "local-only"}
FORBIDDEN_SUFFIXES = {".csv", ".ipynb", ".parquet", ".xml"}


def _members(path: Path) -> tuple[str, ...]:
    if path.suffix == ".whl" or path.suffix == ".zip":
        with zipfile.ZipFile(path) as archive:
            return tuple(archive.namelist())
    if path.name.endswith((".tar.gz", ".tgz")):
        with tarfile.open(path, "r:gz") as archive:
            return tuple(member.name for member in archive.getmembers())
    raise ValueError(f"Unsupported distribution archive: {path}")


def _violations(path: Path) -> tuple[str, ...]:
    violations = []
    for member in _members(path):
        parts = set(Path(member).parts)
        if parts & FORBIDDEN_PARTS or Path(member).suffix.lower() in FORBIDDEN_SUFFIXES:
            violations.append(member)
    return tuple(violations)


def main(arguments: list[str]) -> int:
    """Check all paths supplied on the command line."""
    if not arguments:
        print("Usage: check_distribution.py DIST [DIST ...]", file=sys.stderr)
        return 2
    failed = False
    for argument in arguments:
        path = Path(argument)
        violations = _violations(path)
        if violations:
            failed = True
            print(f"{path}: forbidden distribution members:", file=sys.stderr)
            for member in violations:
                print(f"  {member}", file=sys.stderr)
        else:
            print(f"{path}: distribution boundary passed")
    return int(failed)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
