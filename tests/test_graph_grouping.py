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
