"""Opt-in integration check: build a crosswalk spine over the three real,
independently-built epistract graphs and assert the measured join floors.

Driven entirely by the EPISTRACT_CROSSWALK_GRAPHS environment variable, a
platform-path-separator-delimited list of graph project directories. When
unset, or when any listed directory lacks a graph_data.json, this module
skips cleanly -- it never references the developer's home directory,
constructs a path from the current user's account, or embeds an absolute
path. Every graph path arrives through the environment variable.

Run against the real graphs with, e.g.:

    EPISTRACT_CROSSWALK_GRAPHS="$HOME/epistract-product-labels:$HOME/epistract-pharmacovigilance:$HOME/epistract-clinicaltrials" \\
        python3 -m pytest tests/test_crosswalk_realgraph.py -m integration -q
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from core.crosswalk import build_spine, load_axis_spec, load_graphs, resolve_domain_configs

_ENV_VAR = "EPISTRACT_CROSSWALK_GRAPHS"

_NAMED_EIGHT = {
    "dapagliflozin",
    "dulaglutide",
    "empagliflozin",
    "exenatide",
    "liraglutide",
    "semaglutide",
    "sitagliptin",
    "tirzepatide",
}


def _resolve_graph_dirs() -> list[str] | None:
    raw = os.environ.get(_ENV_VAR)
    if not raw:
        return None
    dirs = raw.split(os.pathsep)
    for d in dirs:
        if not (Path(d) / "graph_data.json").is_file():
            return None
    return dirs


@pytest.fixture(scope="module")
def real_spine():
    graph_dirs = _resolve_graph_dirs()
    if graph_dirs is None:
        pytest.skip(
            f"{_ENV_VAR} is unset, or one of its graph directories lacks a "
            f"graph_data.json -- set {_ENV_VAR} to a "
            f"{os.pathsep!r}-separated list of built epistract project "
            "directories to run this integration check."
        )
    graphs = load_graphs(graph_dirs)
    axis_spec = load_axis_spec("crosswalks/pharma.yaml")
    graphs = resolve_domain_configs(graphs, axis_spec)
    return build_spine(graphs, axis_spec)


def _all_graph_intersection(spine: dict, axis_name: str) -> set[str]:
    declared = set(spine["stats"][axis_name]["declared_by"])
    return {
        key
        for key, entry in spine["axes"][axis_name].items()
        if set(entry["graphs"]) == declared
    }


@pytest.mark.integration
def test_trial_axis_shares_at_least_twenty_keys(real_spine):
    pair_key = "clinicaltrials|fda-product-labels"
    observed = real_spine["stats"]["trial"]["pairwise"].get(pair_key, 0)
    assert observed >= 20, (
        f"trial axis: labels<->clinicaltrials shared {observed} keys, "
        "expected >= 20. If this regresses, the fix is to widen "
        "entity_types in domains/fda-product-labels/crosswalk.yaml's trial "
        "axis (registry IDs live in node names outside CLINICAL_STUDY too) "
        "-- never to lower this floor."
    )


@pytest.mark.integration
def test_trial_axis_declare_pair_joins_on_shared_key(real_spine):
    trial_axis = real_spine["axes"]["trial"]
    matches = [
        entry
        for entry in trial_axis.values()
        if "clinical_study:declare" in entry["graphs"].get("fda-product-labels", [])
        and "trial:nct01730534" in entry["graphs"].get("clinicaltrials", [])
    ]
    assert matches, (
        "expected clinical_study:declare (fda-product-labels) and "
        "trial:nct01730534 (clinicaltrials) to land under one shared "
        f"canonical key; trial axis has {len(trial_axis)} keys total"
    )


@pytest.mark.integration
def test_drug_axis_all_graph_intersection_is_superset_of_named_eight(real_spine):
    intersection = _all_graph_intersection(real_spine, "drug")
    missing = _NAMED_EIGHT - intersection
    assert not missing, (
        f"drug axis all-graph intersection ({len(intersection)} keys: "
        f"{sorted(intersection)}) is missing {sorted(missing)} of the eight "
        "molecules the assessment names"
    )


@pytest.mark.integration
def test_adverse_event_axis_shares_at_least_forty_keys(real_spine):
    pair_key = "fda-product-labels|pharmacovigilance"
    observed = real_spine["stats"]["adverse_event"]["pairwise"].get(pair_key, 0)
    assert observed >= 40, (
        f"adverse_event axis: labels<->pharmacovigilance shared {observed} "
        "keys, expected >= 40"
    )


@pytest.mark.integration
def test_every_axis_reports_nonempty_declared_by_and_per_graph_counts(real_spine):
    for axis_name, stats in real_spine["stats"].items():
        assert stats["declared_by"], f"{axis_name}: declared_by is empty"
        for graph in stats["declared_by"]:
            assert graph in stats["keys_per_graph"], (
                f"{axis_name}: keys_per_graph missing entry for declaring "
                f"graph {graph!r}"
            )
