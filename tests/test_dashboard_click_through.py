"""Dashboard click-through: node harnesses for dashboard.js and the graph-show-types handler."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

JS_DIR = Path(__file__).resolve().parent / "js"
DASHBOARD_HARNESS = JS_DIR / "dashboard_harness.mjs"
GRAPH_HARNESS = JS_DIR / "graph_filter_harness.mjs"

SHOW_MODES = [
    "show-solo",
    "show-repeat",
    "show-source",
    "show-reset",
    "show-unknown",
    "show-resets",
    "show-queued",
    "show-nodisplay",
    "show-during-relayout",
    "show-focus",
    "show-focus-stale",
    "show-focus-unknown",
    "show-focus-queued",
    "show-focus-queued-edit",
    "show-focus-source",
    "show-focus-edge-filter",
    "show-focus-isolated",
]


def _run(harness: Path, *args: str) -> dict:
    if shutil.which("node") is None:
        pytest.skip("node not available")
    result = subprocess.run(
        ["node", str(harness), *args], timeout=30, capture_output=True, text=True
    )
    assert result.stdout.strip(), result.stderr
    out = json.loads(result.stdout.strip().splitlines()[-1])
    assert result.returncode == 0, f"failed: {out.get('failed')}\n{result.stderr}"
    return out


@pytest.mark.unit
def test_dashboard_harness():
    out = _run(DASHBOARD_HARNESS)
    assert out["failed"] == [], out["failed"]
    assert out["passed"], "harness ran no checks"


@pytest.mark.unit
def test_dashboard_epistemic_harness():
    out = _run(DASHBOARD_HARNESS, "epistemic")
    assert out["failed"] == [], out["failed"]
    assert out["passed"], "harness ran no checks"


@pytest.mark.unit
@pytest.mark.parametrize("mode", SHOW_MODES)
def test_graph_show_types(mode):
    out = _run(GRAPH_HARNESS, mode)
    assert out["failed"] == [], out["failed"]
    assert out["passed"], "harness ran no checks"
