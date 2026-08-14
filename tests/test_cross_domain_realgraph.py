"""Opt-in integration check: run the cross-domain rules engine over a spine
built from the three real, independently-built epistract graphs and assert
the measured finding floors.

Driven entirely by the EPISTRACT_CROSSWALK_GRAPHS environment variable --
the same one tests/test_crosswalk_realgraph.py uses, a platform-path-
separator-delimited list of graph project directories. When unset, or when
any listed directory lacks a graph_data.json, this module skips cleanly --
it never references the developer's home directory, constructs a path from
the current user's account, or embeds an absolute path. Every graph path
arrives through the environment variable.

The spine is built in a module-scoped fixture by calling the crosswalk
builder directly -- never by reading a spine file from disk, and never by
reading the reference spine kept beside the plan (that spine was built with
a NAME= graph-name override and records a different key for the labels
graph than metadata.domain would).

Run against the real graphs with, e.g.:

    EPISTRACT_CROSSWALK_GRAPHS="$HOME/epistract-product-labels:$HOME/epistract-pharmacovigilance:$HOME/epistract-clinicaltrials" \\
        python3 -m pytest tests/test_cross_domain_realgraph.py -m integration -q
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from core.cross_domain import load_rules_spec, run_rules
from core.crosswalk import build_spine, load_axis_spec, load_graphs, resolve_domain_configs

_ENV_VAR = "EPISTRACT_CROSSWALK_GRAPHS"
_RULES_PATH = "crosswalks/pharma-rules.yaml"
_AXES_PATH = "crosswalks/pharma.yaml"


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
def real_run():
    """Build the spine directly from the real graphs (never from a spine
    file on disk) and run every rule, with the advisory rule opted in, so
    a single fixture serves both the default-run and opted-in floors."""
    graph_dirs = _resolve_graph_dirs()
    if graph_dirs is None:
        pytest.skip(
            f"{_ENV_VAR} is unset, or one of its graph directories lacks a "
            f"graph_data.json -- set {_ENV_VAR} to a "
            f"{os.pathsep!r}-separated list of built epistract project "
            "directories to run this integration check."
        )
    graphs = load_graphs(graph_dirs)
    axis_spec = load_axis_spec(_AXES_PATH)
    graphs = resolve_domain_configs(graphs, axis_spec)
    spine_result = build_spine(graphs, axis_spec)
    spine = {
        "spine_version": "1.0",
        "generated_at": "2026-08-13T00:00:00+00:00",
        "graphs": {key: str(g["dir"]) for key, g in graphs.items()},
        "axes": spine_result["axes"],
        "stats": spine_result["stats"],
    }
    rules_spec = load_rules_spec(_RULES_PATH, spine)

    default_run = run_rules(rules_spec, spine, graphs, include_advisory=False)
    advisory_run = run_rules(rules_spec, spine, graphs, include_advisory=True)
    return {"spine": spine, "graphs": graphs, "default": default_run, "advisory": advisory_run}


# ---------------------------------------------------------------------------
# unlabeled_adverse_event -- safety signal
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_safety_signal_findings_floor(real_run):
    stats = real_run["default"]["stats"]["unlabeled_adverse_event"]
    observed = stats["findings"]
    assert observed >= 90, (
        f"unlabeled_adverse_event: {observed} findings, expected >= 90. If "
        "this regresses, the fix is to widen the drug/adverse_event edges: "
        "config -- never to lower this floor."
    )


@pytest.mark.integration
def test_safety_signal_subjects_with_findings_floor(real_run):
    stats = real_run["default"]["stats"]["unlabeled_adverse_event"]
    observed = stats["subjects_with_findings"]
    assert observed >= 8, (
        f"unlabeled_adverse_event: {observed} distinct subjects with "
        "findings, expected >= 8."
    )


@pytest.mark.integration
def test_safety_signal_subtype_floors(real_run):
    by_subtype = real_run["default"]["stats"]["unlabeled_adverse_event"]["by_subtype"]
    assert by_subtype.get("absent", 0) >= 75, (
        f"unlabeled_adverse_event: {by_subtype.get('absent', 0)} absent-subtype "
        "findings, expected >= 75."
    )
    assert by_subtype.get("attributed_elsewhere", 0) >= 8, (
        f"unlabeled_adverse_event: {by_subtype.get('attributed_elsewhere', 0)} "
        "attributed_elsewhere-subtype findings, expected >= 8."
    )
    assert by_subtype.get("granularity_variant", 0) >= 2, (
        f"unlabeled_adverse_event: {by_subtype.get('granularity_variant', 0)} "
        "granularity_variant-subtype findings, expected >= 2. This is the "
        "classification-order regression canary -- if it drops to zero, "
        "check that the granularity test still runs BEFORE the "
        "attributed_elsewhere test in classify_miss."
    )


# ---------------------------------------------------------------------------
# coverage_gap -- evidence gap (non-degeneracy gate)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_coverage_gap_subjects_compared_floor(real_run):
    stats = real_run["default"]["stats"]["coverage_gap"]
    observed = stats["subjects_compared"]
    assert observed >= 18, (
        f"coverage_gap: {observed} shared trial subjects compared, expected "
        ">= 18. If this regresses, the fix is to widen the trial axis "
        "join -- never to lower this floor."
    )


@pytest.mark.integration
def test_coverage_gap_findings_floor(real_run):
    stats = real_run["default"]["stats"]["coverage_gap"]
    observed = stats["findings"]
    assert observed >= 140, f"coverage_gap: {observed} findings, expected >= 140."


@pytest.mark.integration
def test_coverage_gap_non_degeneracy_gate(real_run):
    """The covered floor is the non-degeneracy gate: a findings floor alone
    still passes when the rule collapses into reporting everything, which
    is the failure mode this design was measured against and rejected."""
    stats = real_run["default"]["stats"]["coverage_gap"]
    observed = stats["objects_covered"]
    assert observed >= 12, (
        f"coverage_gap: {observed} objects covered (and therefore not "
        "reported), expected >= 12. A findings count alone cannot prove "
        "the rule distinguishes signal from a blanket miss -- if this "
        "drops, the stopword list or report_below threshold has likely "
        "collapsed into reporting every outcome. The fix is to widen the "
        "stopword list or text sources -- never to lower this floor."
    )


@pytest.mark.integration
def test_coverage_gap_top_band_floor(real_run):
    findings = real_run["default"]["custom_findings"]["coverage_gap"]
    top_band = sum(1 for f in findings if f["severity"] == "high")
    assert top_band >= 100, f"coverage_gap: {top_band} top-grade-band findings, expected >= 100."


# ---------------------------------------------------------------------------
# off_label_exposure -- advisory-only exposure rule
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_exposure_rule_skipped_and_zero_findings_without_opt_in(real_run):
    default_stats = real_run["default"]["stats"]["off_label_exposure"]
    assert default_stats == {"status": "skipped-advisory"}
    assert "off_label_exposure" not in real_run["default"]["custom_findings"]


@pytest.mark.integration
def test_exposure_rule_advisory_findings_floor_when_opted_in(real_run):
    findings = real_run["advisory"]["custom_findings"]["off_label_exposure"]
    assert len(findings) >= 25, (
        f"off_label_exposure: {len(findings)} findings with --include-advisory, "
        "expected >= 25."
    )
    for finding in findings:
        assert finding["severity"] == "advisory", (
            f"off_label_exposure finding graded {finding['severity']!r}, "
            "expected every finding to be forced to 'advisory' regardless "
            "of subtype."
        )
        assert finding["evidence"].get("caveat"), (
            "off_label_exposure finding is missing its non-empty caveat "
            "string."
        )
