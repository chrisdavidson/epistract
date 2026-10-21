"""Grouped default layout: pure grouping.js helpers and the graph.js grouped build."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

JS = Path(__file__).resolve().parent / "js"

pytestmark = [
    pytest.mark.unit,
    pytest.mark.skipif(shutil.which("node") is None, reason="node not installed"),
]


def _run(harness: str, *args: str) -> dict:
    proc = subprocess.run(
        ["node", str(JS / harness), *args],
        capture_output=True,
        text=True,
        timeout=60,
    )
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    assert lines, f"no output from {harness}: {proc.stderr[-500:]}"
    return json.loads(lines[-1])


def test_grouping_pure_helpers():
    out = _run("grouping_harness.mjs")
    assert out["failed"] == [], out["failed"][:10]
    assert out["passed"] > 30, out


def test_grouped_default_build():
    out = _run("graph_filter_harness.mjs", "groups")
    assert out["debugMode"] == "cluster", out
    assert out["debugGroupCount"] == out["groupCount"] == 3, out
    assert out["anchorCount"] == out["groupCount"], out
    assert out["debugAnchorCount"] == out["anchorCount"], out
    assert out["debugDataNodes"] == 5, out
    assert out["anchorsHiddenFixed"] is True, out
    assert out["anchorEdgeCount"] == 3 * 4, out
    assert out["anchorEdgesHidden"] is True, out
    assert out["sourceHidden"] is True and out["sourcePhysicsOff"] is True, out
    assert out["iterations"] == 200, out
    assert out["stabilizationFit"] is False, out
    assert out["fitNodesHaveNoAnchorOrHidden"] is True, out


def test_anchors_never_drawn_after_filter():
    out = _run("graph_filter_harness.mjs", "groups")
    assert out["anchorEdgesHiddenAfterFilter"] is True, out
    assert out["anchorNodesHiddenAfterFilter"] is True, out
    assert out["labelledExcludesAnchors"] is True, out


def test_ungrouped_when_groups_missing():
    out = _run("graph_filter_harness.mjs", "ok")
    assert out["anchorCount"] == 0, out
    assert out["iterations"] == 400, out


def test_regions_and_groups_list():
    out = _run("graph_filter_harness.mjs", "regions")
    assert out["failed"] == [], out["failed"][:10]
    assert len(out["passed"]) > 25, out


def test_groups_button_disabled_without_groups():
    out = _run("graph_filter_harness.mjs", "nogroups")
    assert out.get("failed") == [], out
    assert out["passed"], out


def _passed(out: dict, minimum: int) -> None:
    assert out["failed"] == [], out["failed"][:10]
    assert len(out["passed"]) >= minimum, out


def test_group_control_relayout():
    _passed(_run("graph_filter_harness.mjs", "control"), 45)


def test_group_control_fallback():
    _passed(_run("graph_filter_harness.mjs", "control-nocomm"), 11)


def test_group_control_load_failure():
    out = _run("graph_filter_harness.mjs", "ok")
    ctl = out["groupControl"]
    reason = "Grouping data didn't load. Reload the page to try again."
    assert ctl["checked"] == {"cluster": "false", "family": "false", "none": "true"}, ctl
    assert ctl["disabled"]["cluster"] == "true" and ctl["disabled"]["family"] == "true", ctl
    assert ctl["disabled"]["none"] is None, ctl
    assert ctl["titles"]["cluster"] == reason and ctl["titles"]["family"] == reason, ctl
    assert ctl["hint"] == f"Topic cluster: {reason} Entity family: {reason}", ctl
    assert ctl["stabilizeCalls"] == 0, ctl
    assert ctl["after"]["none"] == "true", ctl


def test_group_relayout_failure():
    _passed(_run("graph_filter_harness.mjs", "control-fail"), 12)


def test_sources_join_assigned_group():
    _passed(_run("graph_filter_harness.mjs", "control-sources"), 8)


def test_focus_pure_helpers():
    out = _run("grouping_harness.mjs")
    assert out["failed"] == [], out["failed"][:10]
    assert out["passed"] > 100, out


def test_focus_mode_flow():
    _passed(_run("graph_filter_harness.mjs", "focus"), 70)


def test_focus_filter_composition():
    _passed(_run("graph_filter_harness.mjs", "focus-filters"), 25)


def test_focus_escape_order(tmp_path):
    from tests.test_graph_hover import GLP1, HARNESS, _display_payload

    display = _display_payload(tmp_path)
    proc = subprocess.run(
        ["node", str(HARNESS), str(GLP1 / "graph_data.json"), str(display), "wiring"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    report = json.loads(proc.stdout.strip().splitlines()[-1])
    assert report["failed"] == [], report["failed"]
    esc = [name for name in report["passed"] if name.startswith("esc: ")]
    assert len(esc) >= 9, esc
