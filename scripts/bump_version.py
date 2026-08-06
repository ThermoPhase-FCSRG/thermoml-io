"""Synchronize the thermoml-io package version across release metadata."""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class VersionTarget:
    """Describe one file location that stores the package version."""

    path: Path
    kind: str
    section: str | None = None


TARGETS = (
    VersionTarget(REPO_ROOT / "pyproject.toml", kind="toml-section", section="project"),
    VersionTarget(REPO_ROOT / "pixi.toml", kind="toml-section", section="workspace"),
    VersionTarget(REPO_ROOT / "src" / "thermoml_io" / "__init__.py", kind="python-version"),
    VersionTarget(REPO_ROOT / "CITATION.cff", kind="yaml-version"),
)


def _replace_toml_section_version(text: str, *, section: str, new_version: str) -> tuple[str, str]:
    """Replace the version string inside a specific TOML section."""
    lines = text.splitlines(keepends=True)
    in_section = False

    for idx, line in enumerate(lines):
        if line.endswith("\r\n"):
            body, line_ending = line[:-2], "\r\n"
        elif line.endswith("\n") or line.endswith("\r"):
            body, line_ending = line[:-1], line[-1]
        else:
            body, line_ending = line, ""

        stripped = body.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_section = stripped == f"[{section}]"
            continue

        if not in_section:
            continue

        match = re.match(r'(\s*version\s*=\s*")([^"]+)(".*)$', body)
        if match is None:
            continue

        current_version = match.group(2)
        lines[idx] = f"{match.group(1)}{new_version}{match.group(3)}{line_ending}"
        return "".join(lines), current_version

    raise RuntimeError(f"Could not find a version entry in TOML section [{section}]")


def _replace_python_version(text: str, *, new_version: str) -> tuple[str, str]:
    """Replace the ``__version__`` assignment in a Python source file."""
    match = re.search(r'(?m)^(__version__\s*=\s*")([^"]+)(")$', text)
    if match is None:
        raise RuntimeError("Could not find __version__ assignment in src/thermoml_io/__init__.py")
    current_version = match.group(2)
    updated = re.sub(
        r'(?m)^(__version__\s*=\s*")([^"]+)(")$', rf"\g<1>{new_version}\g<3>", text, count=1
    )
    return updated, current_version


def _replace_yaml_version(text: str, *, new_version: str) -> tuple[str, str]:
    """Replace the top-level ``version`` field in a YAML-like metadata file."""
    match = re.search(r"(?m)^(version:\s*)(\S+)(.*)$", text)
    if match is None:
        raise RuntimeError("Could not find version field in CITATION.cff")
    current_version = match.group(2).strip("\"'")
    updated = re.sub(r"(?m)^(version:\s*)(\S+)(.*)$", rf"\g<1>{new_version}\g<3>", text, count=1)
    return updated, current_version


def _update_target(target: VersionTarget, *, new_version: str) -> tuple[str, str]:
    """Apply the appropriate version-replacement strategy for one target."""
    text = target.path.read_text(encoding="utf-8")
    if target.kind == "toml-section":
        if target.section is None:
            raise RuntimeError(f"Missing TOML section name for {target.path}")
        return _replace_toml_section_version(text, section=target.section, new_version=new_version)
    if target.kind == "python-version":
        return _replace_python_version(text, new_version=new_version)
    if target.kind == "yaml-version":
        return _replace_yaml_version(text, new_version=new_version)
    raise RuntimeError(f"Unsupported target kind: {target.kind}")


def _parse_args() -> argparse.Namespace:
    """Parse command-line arguments for the version bump script."""
    parser = argparse.ArgumentParser(
        description="Update the package version consistently across project metadata files."
    )
    parser.add_argument("version", help="New PEP 440 version string, for example: 0.1.2")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show the planned updates without writing any files.",
    )
    return parser.parse_args()


def main() -> int:
    """Update all authoritative project version declarations consistently."""
    args = _parse_args()
    new_version = args.version.strip()
    if not new_version or any(ch.isspace() for ch in new_version):
        raise SystemExit("Version must be a non-empty string without whitespace")

    current_versions: dict[Path, str] = {}
    updated_text: dict[Path, str] = {}

    for target in TARGETS:
        new_text, current_version = _update_target(target, new_version=new_version)
        current_versions[target.path] = current_version
        updated_text[target.path] = new_text

    unique_versions = sorted(set(current_versions.values()))
    if len(unique_versions) != 1:
        details = "\n".join(
            f"  - {path.relative_to(REPO_ROOT)}: {version}"
            for path, version in current_versions.items()
        )
        raise SystemExit(
            "Refusing to bump version because the project metadata is already "
            "inconsistent:\n"
            f"{details}"
        )

    current_version = unique_versions[0]
    if current_version == new_version:
        print(f"Version is already {new_version}; nothing to do.")
        return 0

    action = "Would update" if args.dry_run else "Updated"
    for path in TARGETS:
        rel_path = path.path.relative_to(REPO_ROOT)
        print(f"{action} {rel_path}: {current_version} -> {new_version}")

    if args.dry_run:
        return 0

    for path, new_text in updated_text.items():
        path.write_text(new_text, encoding="utf-8")

    return 0


if __name__ == "__main__":
    sys.exit(main())
