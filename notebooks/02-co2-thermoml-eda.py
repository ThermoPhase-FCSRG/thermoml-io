# ---
# jupyter:
#   jupytext:
#     cell_metadata_filter: -all
#     formats: ipynb,py:percent
#     notebook_metadata_filter: kernelspec,jupytext
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#       jupytext_version: 1.19.5
#   kernelspec:
#     display_name: Python 3 (thermoml-io)
#     language: python
#     name: python3
# ---

# %% [markdown]
# # Complete carbon-dioxide coverage in the ThermoML snapshot
#
# **Question.** Which experimental records in the versioned NIST/TRC ThermoML
# snapshot involve carbon dioxide as a component, including pure CO₂ and every
# multicomponent system containing CO₂?
#
# **Success criteria.** Identify CO₂ by its standard InChIKey; verify the
# snapshot checksum; include every semantically matching dataset; report the
# same top-10 rankings used in the general archive analysis; and rank datasets
# only after the complete snapshot has been scanned.

# %%
from __future__ import annotations

import platform
from dataclasses import asdict
from importlib.metadata import version
from pathlib import Path
from time import perf_counter

import matplotlib.pyplot as plt
import pandas as pd
from IPython.display import display

from thermoml_io import (
    analyze_thermoml_archive,
    fetch_thermoml_archive,
    get_archive_source,
)

pd.set_option("display.max_colwidth", 120)


def find_project_root(start: Path) -> Path:
    for candidate in (start, *start.parents):
        if (candidate / "pyproject.toml").is_file():
            return candidate
    raise RuntimeError("Could not locate the thermoml-io project root.")


PROJECT_ROOT = find_project_root(Path.cwd().resolve())
print(
    {
        "python": platform.python_version(),
        "thermoml-io": version("thermoml-io"),
        "pandas": version("pandas"),
        "platform": platform.platform(),
    }
)

# %% [markdown]
# ## Chemical identity and source
#
# Formula/name searches can be ambiguous. The analysis uses the standard
# InChIKey for carbon dioxide and then confirms component membership through
# parsed ThermoML references. A serialized-key check is used only as a fast
# prefilter.

# %%
COMPONENT_LABEL = "carbon dioxide"
COMPONENT_FORMULA = "CO2"
COMPONENT_INCHIKEY = "CURLTUGMZLYLDI-UHFFFAOYSA-N"
archive_source = get_archive_source()
ARCHIVE_PATH = fetch_thermoml_archive(cache_dir=PROJECT_ROOT / "notebooks/local-only/archive")
display(
    pd.DataFrame(
        [
            {
                "component": COMPONENT_LABEL,
                "formula": COMPONENT_FORMULA,
                "standard InChIKey": COMPONENT_INCHIKEY,
                "snapshot DOI": archive_source.doi.removeprefix("doi:"),
                "cutoff": "entries published through 2019",
                "SHA-256": archive_source.sha256,
            }
        ]
    )
)

# %% [markdown]
# ## All datasets containing CO₂
#
# `component=` means inclusion: binary, ternary, quaternary, and higher-order
# systems remain eligible. It does not require CO₂ to be the measured property
# target, only a referenced component of the experimental system.

# %%
started = perf_counter()
analysis = analyze_thermoml_archive(
    ARCHIVE_PATH,
    component=COMPONENT_INCHIKEY,
    serialized_prefilter=COMPONENT_INCHIKEY,
    top_datasets=10,
    on_error="collect",
)
elapsed_seconds = perf_counter() - started
summary = analysis.summary

overview = pd.DataFrame(
    {
        "metric": [
            "XML members in snapshot",
            "XML members passing InChIKey prefilter",
            "publications with matching datasets",
            "datasets containing CO2",
            "NumValues data points",
            "property observations",
            "official JSON recoveries after prefilter",
            "unrecovered failures after prefilter",
            "elapsed seconds",
        ],
        "count": [
            analysis.xml_document_count,
            analysis.parsed_document_count,
            analysis.matched_document_count,
            summary.dataset_count,
            summary.data_point_count,
            summary.observation_count,
            len(analysis.recoveries),
            len(analysis.failures),
            round(elapsed_seconds, 2),
        ],
    }
)
display(overview)

# %% [markdown]
# ## Top-10 rankings for CO₂-containing systems
#
# Counts are observation-weighted except for the explicitly labelled dataset
# system-order ranking.

# %%
RANKINGS = (
    ("data_types", "Derived data categories"),
    ("property_groups", "Original ThermoML property groups"),
    ("properties", "Reported properties"),
    ("dataset_system_types", "System orders — datasets"),
    ("system_types", "System orders — observations"),
    ("systems", "Chemical systems containing CO2"),
    ("components", "Components in CO2-containing systems"),
    ("methods", "Experimental methods"),
    ("publications", "Publications"),
)

ranking_frames: dict[str, pd.DataFrame] = {}
for field, title in RANKINGS:
    frame = pd.DataFrame(
        [
            {"rank": rank, "label": item.label, "count": item.count}
            for rank, item in enumerate(summary.top(field, 10), start=1)
        ]
    )
    ranking_frames[field] = frame
    print(f"\n{title} — top 10")
    display(frame)

# %% [markdown]
# ## CO₂ as component and its most frequent co-components
#
# Every retained observation belongs to a system containing CO₂. The target
# component count therefore provides a useful internal accounting check.

# %%
component_counts = pd.DataFrame(
    [{"component": item.label, "observations": item.count} for item in summary.components]
)
target_count = int(
    component_counts.loc[
        component_counts["component"].str.casefold() == COMPONENT_LABEL,
        "observations",
    ].sum()
)
assert target_count == summary.observation_count
co_components = component_counts[
    component_counts["component"].str.casefold() != COMPONENT_LABEL
].head(10)
display(
    pd.DataFrame(
        [
            {
                "accounting check": "CO2 component observations",
                "count": target_count,
                "expected": summary.observation_count,
            }
        ]
    )
)
display(co_components)

# %% [markdown]
# ## Ten densest CO₂-containing datasets

# %%
dense_records = []
for rank, item in enumerate(analysis.top_datasets, start=1):
    record = asdict(item)
    locator = record.pop("source_locator")
    record["archive_member"] = locator.rsplit("!", maxsplit=1)[-1] if locator else None
    dense_records.append({"rank": rank, **record})
display(pd.DataFrame(dense_records))

# %% [markdown]
# ## Visual comparison

# %%
figure, axes = plt.subplots(2, 2, figsize=(15, 11), constrained_layout=True)
for axis, field, title in (
    (axes[0, 0], "data_types", "Derived data categories"),
    (axes[0, 1], "properties", "Reported properties"),
    (axes[1, 0], "systems", "CO2-containing systems"),
    (axes[1, 1], "publications", "Publications"),
):
    frame = ranking_frames[field].sort_values("count")
    axis.barh(frame["label"], frame["count"])
    axis.set_title(title)
    axis.set_xlabel("Property observations")
    axis.grid(axis="x", alpha=0.25)
plt.show()

# %% [markdown]
# ## Recoveries, failures, and limitations

# %%
recovery_frame = pd.DataFrame(
    [
        {
            "XML member": item.xml_member_name,
            "JSON member": item.json_member_name,
            "XML error": item.error_message,
        }
        for item in analysis.recoveries
    ]
)
if recovery_frame.empty:
    print("No CO2-prefiltered XML member required paired-JSON recovery.")
else:
    display(recovery_frame)

# %%
failure_frame = pd.DataFrame(
    [
        {
            "archive_member": item.member_name,
            "error_type": item.error_type,
            "message": item.message,
        }
        for item in analysis.failures
    ]
)
if failure_frame.empty:
    print("No CO2-prefiltered member remained undecodable.")
else:
    display(failure_frame)

# %% [markdown]
# - “All” means every matching supported `PureOrMixtureData` dataset in the
#   pinned snapshot, whose publication cutoff is 2019.
# - `ReactionData` is not associated with components in the v0.1 typed model
#   and is therefore outside this component-specific census.
# - Counts measure stored property observations, not independent experiments or
#   critically evaluated recommended values.
# - NIST/TRC checks representation completeness but does not critically
#   evaluate the underlying measurements; consult the original publications
#   before calibration or validation work.
