"""Fit-view legibility: screen-constant labels, node sizes and edge widths."""

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


def test_style_helpers_hold_screen_floors():
    out = _run("graph_style_harness.mjs")
    assert out["failed"] == [], out["failed"][:10]


def test_fit_view_controller_runs_at_fit_scale():
    out = _run("graph_filter_harness.mjs", "fit")
    assert out["fitBeforeFont"] is True, out
    assert out["minLabelPx"] >= 10, out
    assert out["minNodePx"] >= 3.5, out
    assert out["minEdgePx"] >= 1.4, out
    assert out["edgeIdsAreStrings"] is True, out
