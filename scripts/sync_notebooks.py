"""Synchronize paired Jupytext notebooks and percent-format sources."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
NOTEBOOKS_DIR = REPO_ROOT / "notebooks"


def main() -> int:
    """Synchronize every tracked notebook in deterministic order."""
    notebooks = sorted(NOTEBOOKS_DIR.glob("*.ipynb"))
    if not notebooks:
        print("No notebooks found to synchronize.")
        return 0
    result = subprocess.run(
        ["jupytext", "--sync", *(str(path) for path in notebooks)],
        cwd=REPO_ROOT,
        check=False,
    )
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
