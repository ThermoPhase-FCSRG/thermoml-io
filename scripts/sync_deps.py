"""Synchronize Pixi dependencies into PyPI optional-dependency metadata."""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT_PATH = REPO_ROOT / "pyproject.toml"
PIXI_PATH = REPO_ROOT / "pixi.toml"


TARGET_MARKERS = {
    "linux-64": "sys_platform == 'linux'",
    "linux-64-cuda": "sys_platform == 'linux'",
    "osx-64": "sys_platform == 'darwin'",
    "osx-arm64": "sys_platform == 'darwin'",
    "win-64": "sys_platform == 'win32'",
    "win-64-cuda": "sys_platform == 'win32'",
}

CORE_EXCLUDED_PACKAGE_NAMES = frozenset(
    {
        "python",
        "thermoml-io",
    }
)
CORE_FEATURE_NAME = "core"
PYPROJECT_OPTIONAL_FEATURE_NAMES = frozenset({"yaml", "parquet", "pandas", "export"})
FEATURE_EXCLUDED_PACKAGE_NAMES: dict[str, frozenset[str]] = {}
PYPI_NAME_OVERRIDES: dict[str, str] = {}
PYPI_SPECIFIER_OVERRIDES: dict[str, str] = {}


@dataclass(frozen=True)
class PixiRequirement:
    """One Pixi dependency entry converted to a PyPI-facing candidate."""

    name: str
    specifier: str
    extras: tuple[str, ...] = ()
    marker: str | None = None


@dataclass(frozen=True)
class SyncTarget:
    """Describe one dependency list in ``pyproject.toml`` to synchronize."""

    section: str
    key: str
    requirements: tuple[str, ...]


def _canonicalize_name(name: str) -> str:
    """Normalize a package name using PEP 503 normalization rules."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _read_toml(path: Path) -> dict[str, object]:
    with path.open("rb") as fh:
        return tomllib.load(fh)


def _pixi_value_parts(raw_value: object) -> tuple[str, tuple[str, ...]] | None:
    """Return the version and extras parts of one Pixi dependency value."""
    if isinstance(raw_value, str):
        return raw_value.strip(), ()
    if not isinstance(raw_value, dict):
        return None

    # Ignore local path/editable entries, e.g. thermoml-io = { path = "." }.
    version = raw_value.get("version")
    if not isinstance(version, str):
        return None

    raw_extras = raw_value.get("extras", ())
    extras: tuple[str, ...]
    if isinstance(raw_extras, list) and all(isinstance(item, str) for item in raw_extras):
        extras = tuple(raw_extras)
    else:
        extras = ()
    return version.strip(), extras


def _iter_table_requirements(
    raw: object, *, marker: str | None = None
) -> Iterable[PixiRequirement]:
    if not isinstance(raw, dict):
        return
    for raw_name, raw_value in raw.items():
        if not isinstance(raw_name, str):
            continue
        parts = _pixi_value_parts(raw_value)
        if parts is None:
            continue
        specifier, extras = parts
        yield PixiRequirement(
            name=raw_name,
            specifier=specifier,
            extras=extras,
            marker=marker,
        )


def _iter_target_requirements(raw_targets: object) -> Iterable[PixiRequirement]:
    if not isinstance(raw_targets, dict):
        return
    for platform, target_data in raw_targets.items():
        if not isinstance(platform, str) or not isinstance(target_data, dict):
            continue
        marker = TARGET_MARKERS.get(platform)
        yield from _iter_table_requirements(target_data.get("dependencies"), marker=marker)
        yield from _iter_table_requirements(target_data.get("pypi-dependencies"), marker=marker)


def _marker_from_platforms(raw_platforms: object) -> str | None:
    if not isinstance(raw_platforms, list):
        return None

    markers: list[str] = []
    for platform in raw_platforms:
        if not isinstance(platform, str):
            continue
        marker = TARGET_MARKERS.get(platform)
        if marker is None or marker in markers:
            continue
        markers.append(marker)

    if not markers:
        return None
    return " or ".join(markers)


def _iter_project_requirements(pixi_data: dict[str, object]) -> Iterable[PixiRequirement]:
    """Yield package runtime requirements from Pixi's core feature.

    The root Pixi dependency tables are intentionally kept small so auxiliary
    environments such as ``docs`` can solve without inheriting the full package
    runtime stack. PyPI package metadata is generated from ``feature.core`` plus
    root platform-specific runtime dependencies.
    """
    yield from _iter_feature_requirements(pixi_data, CORE_FEATURE_NAME)
    yield from _iter_target_requirements(pixi_data.get("target"))


def _feature_data(pixi_data: dict[str, object]) -> dict[str, object]:
    features = pixi_data.get("feature")
    return features if isinstance(features, dict) else {}


def _iter_feature_requirements(
    pixi_data: dict[str, object], feature_name: str
) -> Iterable[PixiRequirement]:
    feature = _feature_data(pixi_data).get(feature_name)
    if not isinstance(feature, dict):
        return
    marker = _marker_from_platforms(feature.get("platforms"))
    yield from _iter_table_requirements(feature.get("dependencies"), marker=marker)
    yield from _iter_table_requirements(feature.get("pypi-dependencies"), marker=marker)
    yield from _iter_target_requirements(feature.get("target"))


def _pep508_specifier_from_pixi_specifier(specifier: str) -> str:
    """Convert simple Pixi version specs to PEP 508 requirement suffixes."""
    normalized = specifier.strip()
    if normalized in {"", "*"}:
        return ""
    if normalized[0].isdigit():
        return f"=={normalized}"
    return normalized


def _pyproject_name(requirement: PixiRequirement) -> str:
    canonical = _canonicalize_name(requirement.name)
    return PYPI_NAME_OVERRIDES.get(canonical, requirement.name)


def _pyproject_specifier(requirement: PixiRequirement) -> str:
    canonical = _canonicalize_name(requirement.name)
    override = PYPI_SPECIFIER_OVERRIDES.get(canonical)
    if override is not None:
        return override
    return _pep508_specifier_from_pixi_specifier(requirement.specifier)


def _is_excluded_requirement(requirement: PixiRequirement, *, feature_name: str | None) -> bool:
    canonical = _canonicalize_name(requirement.name)
    if feature_name is None:
        return canonical in CORE_EXCLUDED_PACKAGE_NAMES
    return canonical in FEATURE_EXCLUDED_PACKAGE_NAMES.get(feature_name, frozenset())


def _format_requirement(requirement: PixiRequirement) -> str:
    extras = f"[{','.join(requirement.extras)}]" if requirement.extras else ""
    formatted = f"{_pyproject_name(requirement)}{extras}{_pyproject_specifier(requirement)}"
    if requirement.marker:
        formatted = f"{formatted}; {requirement.marker}"
    return formatted


def _render_requirements(
    requirements: Iterable[PixiRequirement], *, feature_name: str | None = None
) -> list[str]:
    rendered: list[str] = []
    seen: set[tuple[str, str | None]] = set()
    for requirement in requirements:
        if _is_excluded_requirement(requirement, feature_name=feature_name):
            continue
        formatted = _format_requirement(requirement)
        key = (_canonicalize_name(formatted.split(";", maxsplit=1)[0]), requirement.marker)
        if key in seen:
            continue
        seen.add(key)
        rendered.append(formatted)
    return rendered


def _sync_targets_from_pixi(
    pixi_data: dict[str, object],
) -> tuple[list[SyncTarget], list[str]]:
    """Create the intentionally public PyPI dependency targets from Pixi.

    The core feature becomes ``project.dependencies`` (the ordinary/default
    installation). Only features that are meaningful package capabilities are
    exported as extras. Pixi-only development environments such as ``docs``,
    ``test``, and ``benchmarks`` must not leak into the wheel metadata.
    """
    targets = [
        SyncTarget(
            section="project",
            key="dependencies",
            requirements=tuple(_render_requirements(_iter_project_requirements(pixi_data))),
        )
    ]
    empty_feature_names: list[str] = []
    for feature_name in _feature_data(pixi_data):
        if feature_name not in PYPROJECT_OPTIONAL_FEATURE_NAMES:
            empty_feature_names.append(feature_name)
            continue
        rendered = _render_requirements(
            _iter_feature_requirements(pixi_data, feature_name),
            feature_name=feature_name,
        )
        if not rendered:
            empty_feature_names.append(feature_name)
            continue
        targets.append(
            SyncTarget(
                section="project.optional-dependencies",
                key=feature_name,
                requirements=tuple(rendered),
            )
        )
    return targets, empty_feature_names


def _is_section_header(line_body: str) -> bool:
    stripped = line_body.strip()
    return stripped.startswith("[") and stripped.endswith("]")


def _bracket_delta_outside_quotes(text: str) -> int:
    """Return net square-bracket delta, ignoring brackets inside strings."""
    delta = 0
    in_string = False
    escaped = False
    for ch in text:
        if in_string:
            if escaped:
                escaped = False
                continue
            if ch == "\\":
                escaped = True
                continue
            if ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            continue
        if ch == "[":
            delta += 1
        elif ch == "]":
            delta -= 1
    return delta


def _line_body_and_ending(line: str) -> tuple[str, str]:
    if line.endswith("\r\n"):
        return line[:-2], "\r\n"
    if line.endswith("\n") or line.endswith("\r"):
        return line[:-1], line[-1]
    return line, ""


def _format_toml_array_key(
    *, key: str, new_items: list[str] | tuple[str, ...], indent: str, line_ending: str
) -> list[str]:
    if not new_items:
        return [f"{indent}{key} = []{line_ending}"]

    item_indent = f"{indent}  "
    replacement = [f"{indent}{key} = [{line_ending}"]
    replacement.extend(f'{item_indent}"{item}",{line_ending}' for item in new_items)
    replacement.append(f"{indent}]{line_ending}")
    return replacement


def _replace_toml_array_section_key(
    text: str,
    *,
    section: str,
    key: str,
    new_items: list[str] | tuple[str, ...],
) -> str:
    """Replace or add a TOML array value in the selected section."""
    lines = text.splitlines(keepends=True)
    in_section = False
    section_start: int | None = None
    section_end: int | None = None
    line_ending = "\n"

    for idx, line in enumerate(lines):
        body, current_line_ending = _line_body_and_ending(line)
        if current_line_ending:
            line_ending = current_line_ending

        stripped = body.strip()
        if _is_section_header(body):
            if in_section and section_end is None:
                section_end = idx
                break
            in_section = stripped == f"[{section}]"
            if in_section:
                section_start = idx
            continue

        if not in_section:
            continue

        match = re.match(rf"^(\s*{re.escape(key)}\s*=\s*\[)(.*)$", body)
        if match is None:
            continue

        indent_match = re.match(r"^(\s*)", body)
        indent = indent_match.group(1) if indent_match else ""
        start_idx = idx
        bracket_balance = _bracket_delta_outside_quotes(body)
        end_idx = idx
        while bracket_balance > 0:
            end_idx += 1
            if end_idx >= len(lines):
                raise RuntimeError(f"Unterminated array for [{section}].{key}")
            next_body, _ = _line_body_and_ending(lines[end_idx])
            bracket_balance += _bracket_delta_outside_quotes(next_body)

        lines[start_idx : end_idx + 1] = _format_toml_array_key(
            key=key,
            new_items=new_items,
            indent=indent,
            line_ending=line_ending,
        )
        return "".join(lines)

    if in_section and section_end is None:
        section_end = len(lines)
    if section_start is None or section_end is None:
        raise RuntimeError(f"Could not find section [{section}]")

    insertion = _format_toml_array_key(
        key=key,
        new_items=new_items,
        indent="",
        line_ending=line_ending,
    )
    lines[section_end:section_end] = insertion
    return "".join(lines)


def _remove_toml_array_section_key(
    text: str,
    *,
    section: str,
    key: str,
) -> str:
    """Remove a TOML array value in the selected section, if present."""
    lines = text.splitlines(keepends=True)
    in_section = False

    for idx, line in enumerate(lines):
        body, _ = _line_body_and_ending(line)
        stripped = body.strip()
        if _is_section_header(body):
            if in_section:
                break
            in_section = stripped == f"[{section}]"
            continue

        if not in_section:
            continue

        match = re.match(rf"^(\s*{re.escape(key)}\s*=\s*\[)(.*)$", body)
        if match is None:
            continue

        start_idx = idx
        bracket_balance = _bracket_delta_outside_quotes(body)
        end_idx = idx
        while bracket_balance > 0:
            end_idx += 1
            if end_idx >= len(lines):
                raise RuntimeError(f"Unterminated array for [{section}].{key}")
            next_body, _ = _line_body_and_ending(lines[end_idx])
            bracket_balance += _bracket_delta_outside_quotes(next_body)

        del lines[start_idx : end_idx + 1]
        return "".join(lines)

    return text


def _sync_pyproject_text(pixi_data: dict[str, object], pyproject_text: str) -> str:
    """Return synchronized ``pyproject.toml`` text."""
    targets, empty_feature_names = _sync_targets_from_pixi(pixi_data)
    pyproject_data = tomllib.loads(pyproject_text)
    project = pyproject_data.get("project")
    optional_dependencies = (
        project.get("optional-dependencies") if isinstance(project, dict) else None
    )
    existing_optional_names = (
        set(optional_dependencies) if isinstance(optional_dependencies, dict) else set()
    )
    names_to_remove = (existing_optional_names - PYPROJECT_OPTIONAL_FEATURE_NAMES).union(
        empty_feature_names
    )

    updated_text = pyproject_text
    for target in targets:
        updated_text = _replace_toml_array_section_key(
            updated_text,
            section=target.section,
            key=target.key,
            new_items=target.requirements,
        )
    for key in sorted(names_to_remove):
        updated_text = _remove_toml_array_section_key(
            updated_text,
            section="project.optional-dependencies",
            key=key,
        )
    return updated_text


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Synchronize PyPI-facing dependency metadata in pyproject.toml from "
            "Pixi dependency declarations in pixi.toml."
        )
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show whether pyproject.toml would change without writing it.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit nonzero if pyproject.toml is not synchronized.",
    )
    return parser.parse_args()


def main() -> int:
    """Run the dependency synchronization command-line interface."""
    args = _parse_args()

    pixi_data = _read_toml(PIXI_PATH)
    pyproject_text = PYPROJECT_PATH.read_text(encoding="utf-8")
    synced_text = _sync_pyproject_text(pixi_data, pyproject_text)
    changed = synced_text != pyproject_text

    if args.check:
        if changed:
            print("pyproject.toml dependency metadata is not synchronized with pixi.toml")
            return 1
        print("pyproject.toml dependency metadata is synchronized with pixi.toml")
        return 0

    if args.dry_run:
        if changed:
            print("Would update pyproject.toml dependency metadata from pixi.toml")
        else:
            print("pyproject.toml dependency metadata is already synchronized with pixi.toml")
        return 0

    if changed:
        PYPROJECT_PATH.write_text(synced_text, encoding="utf-8")
        print("Updated pyproject.toml dependency metadata from pixi.toml")
    else:
        print("pyproject.toml dependency metadata is already synchronized with pixi.toml")
    return 0


if __name__ == "__main__":
    sys.exit(main())
