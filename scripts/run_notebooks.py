"""Execute public notebooks from a fresh kernel and save compact outputs."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
NOTEBOOKS_DIR = REPO_ROOT / "notebooks"


def main() -> int:
    """Execute all public notebooks in deterministic filename order."""
    notebooks = sorted(NOTEBOOKS_DIR.glob("*.ipynb"))
    if not notebooks:
        print("No notebooks found to execute.")
        return 0
    for notebook in notebooks:
        result = subprocess.run(
            [
                "jupyter",
                "nbconvert",
                "--to",
                "notebook",
                "--execute",
                "--inplace",
                "--ExecutePreprocessor.timeout=600",
                str(notebook),
            ],
            cwd=REPO_ROOT,
            check=False,
        )
        if result.returncode:
            return result.returncode
    return 0


if __name__ == "__main__":
    sys.exit(main())
