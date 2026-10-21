"""Sidebar relation direction and source counts on real GLP-1 data (node harness)."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
GLP1 = ROOT / "tests" / "corpora" / "06_glp1_landscape" / "output-v3"
HARNESS = Path(__file__).resolve().parent / "js" / "sidebar_harness.mjs"


def _run_report():
    if shutil.which("node") is None:
        pytest.skip("node not available")
    result = subprocess.run(
        ["node", str(HARNESS), str(GLP1 / "graph_data.json")],
        timeout=60,
        capture_output=True,
        text=True,
    )
    try:
        return json.loads(result.stdout.strip().splitlines()[-1])
    except (IndexError, ValueError):
        return {"passed": [], "failed": [{"name": "unparseable harness output"}]}


def _focus_failures(report, *needles):
    return [
        f
        for f in report["failed"]
        if f["name"] == "f: harness error"
        or (f["name"].startswith("f: ") and any(n in f["name"] for n in needles))
    ]


def _assert_focus(*needles):
    report = _run_report()
    ran = [p for p in report["passed"] if p.startswith("f: ")]
    failed = _focus_failures(report, *needles)
    assert not failed and ran, f"focus checks failed: {failed}; passed {len(ran)}"


@pytest.mark.unit
def test_sidebar_focus_row():
    _assert_focus(
        "focus row",
        "button",
        "segment",
        "radiogroup",
        "tabindex",
        "click",
        "arrow",
        "edge detail",
        "Attributes",
        "no focusInfo",
        "hostile",
    )


@pytest.mark.unit
def test_sidebar_focus_center():
    _assert_focus("center", "changed event", "another centre")


@pytest.mark.unit
def test_sidebar_focus_disabled():
    _assert_focus("linkless", "disabled")


@pytest.mark.unit
def test_sidebar_relations_and_source_counts():
    report = _run_report()
    failed = [f for f in report["failed"] if not f["name"].startswith("f: ")]
    assert not failed and report["passed"], f"failed: {failed}"
