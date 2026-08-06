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
# # Complete ThermoML snapshot exploratory analysis
#
# **Question.** What publications, property types, properties, system orders,
# chemical systems, components, methods, and dense datasets occur in the full
# versioned NIST/TRC ThermoML snapshot?
#
# **Success criteria.** Verify the official snapshot checksum; scan every XML
# member; report the top 10 for every requested ranking; distinguish datasets,
# data points, and property observations; and explicitly list any member that
# cannot be decoded.
#
# This notebook analyzes the NIST snapshot published under DOI
# `10.18434/mds2-2422`. The snapshot covers archive entries through the 2019
# publication year. It is a reproducible census of that version, not a claim
# about records added to the live service later.

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
    """Locate the repository root independently of the kernel directory."""
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
# ## Source, checksum, and local-only boundary
#
# Automated archive studies should use the bulk snapshot instead of issuing
# thousands of requests to the live search service. The 189 MB compressed file
# is cached under the ignored `notebooks/local-only/` directory and is never
# included in the Python distributions.

# %%
archive_source = get_archive_source()
ARCHIVE_PATH = fetch_thermoml_archive(cache_dir=PROJECT_ROOT / "notebooks/local-only/archive")
display(
    pd.DataFrame(
        [
            {
                "dataset DOI": archive_source.doi.removeprefix("doi:"),
                "snapshot": ARCHIVE_PATH.name,
                "cutoff": "entries published through 2019",
                "compressed bytes": ARCHIVE_PATH.stat().st_size,
                "SHA-256": archive_source.sha256,
                "local path": str(ARCHIVE_PATH.relative_to(PROJECT_ROOT)),
            }
        ]
    )
)

# %% [markdown]
# ## Complete streaming scan
#
# `on_error="collect"` retains unrecovered failures explicitly. XML is always
# attempted first; the paired official NIST JSON is used only after an XML
# parsing failure, and every such event is listed in `analysis.recoveries`.

# %%
started = perf_counter()
analysis = analyze_thermoml_archive(
    ARCHIVE_PATH,
    top_datasets=10,
    on_error="collect",
)
elapsed_seconds = perf_counter() - started
summary = analysis.summary

overview = pd.DataFrame(
    {
        "metric": [
            "XML members in snapshot",
            "documents decoded",
            "pure/mixture datasets decoded",
            "NumValues data points",
            "property observations",
            "reaction datasets detected",
            "official JSON recoveries",
            "unrecovered decoding failures",
            "elapsed seconds",
        ],
        "count": [
            analysis.xml_document_count,
            analysis.parsed_document_count,
            summary.dataset_count,
            summary.data_point_count,
            summary.observation_count,
            summary.reaction_dataset_count,
            len(analysis.recoveries),
            len(analysis.failures),
            round(elapsed_seconds, 2),
        ],
    }
)
display(overview)

# %% [markdown]
# ## Top-10 rankings
#
# Except for “system orders by dataset”, counts are weighted by individual
# property observations. This makes the ranking consistent with the search API
# and prevents a publication containing many tiny datasets from appearing
# denser than one containing more measured values.

# %%
RANKINGS = (
    ("data_types", "Derived data categories"),
    ("property_groups", "Original ThermoML property groups"),
    ("properties", "Reported properties"),
    ("dataset_system_types", "System orders — datasets"),
    ("system_types", "System orders — observations"),
    ("systems", "Chemical systems"),
    ("components", "Components"),
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
# ## Ten densest datasets
#
# Dataset ranking uses all property observations in each supported
# `PureOrMixtureData` entry and is truncated only after the entire snapshot has
# been processed.

# %%
dense_records = []
for rank, item in enumerate(analysis.top_datasets, start=1):
    record = asdict(item)
    locator = record.pop("source_locator")
    record["archive_member"] = locator.rsplit("!", maxsplit=1)[-1] if locator else None
    dense_records.append({"rank": rank, **record})
dense_datasets = pd.DataFrame(dense_records)
display(dense_datasets)

# %% [markdown]
# ## Visual comparison

# %%
figure, axes = plt.subplots(2, 2, figsize=(15, 11), constrained_layout=True)
for axis, field, title in (
    (axes[0, 0], "data_types", "Derived data categories"),
    (axes[0, 1], "properties", "Reported properties"),
    (axes[1, 0], "components", "Components"),
    (axes[1, 1], "systems", "Chemical systems"),
):
    frame = ranking_frames[field].sort_values("count")
    axis.barh(frame["label"], frame["count"])
    axis.set_title(title)
    axis.set_xlabel("Property observations")
    axis.grid(axis="x", alpha=0.25)
plt.show()

# %% [markdown]
# ## Explicit source recoveries and failures
#
# Recovery never edits the XML. It preserves the rejected XML locator, hash,
# and exception, then parses the same-path official JSON as a distinct source.

# %%
recovery_frame = pd.DataFrame(
    [
        {
            "XML member": item.xml_member_name,
            "JSON member": item.json_member_name,
            "XML SHA-256": item.xml_sha256,
            "JSON SHA-256": item.json_sha256,
            "XML error": item.error_message,
            "XML lexical decimals preserved": (item.lexical_numeric_representation_preserved),
        }
        for item in analysis.recoveries
    ]
)
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
    print("All members were decoded directly or by explicit paired-JSON recovery.")
else:
    display(failure_frame)

# %% [markdown]
# ## Interpretation and limitations
#
# - The snapshot is complete only through its stated 2019 publication cutoff.
# - Rankings describe archive coverage, not data quality or independent
#   experimental information content.
# - Friendly categories such as VLE/LLE/SLE are conservative derived views;
#   the original ThermoML property-group ranking is shown separately.
# - `ReactionData` entries are counted but are not yet decoded into the v0.1
#   typed reaction model, so reaction observations do not enter the rankings.
# - NIST/TRC representation checks are not a critical evaluation of the
#   underlying experiments. Applied use requires consultation of the original
#   publications and domain-specific consistency checks.
