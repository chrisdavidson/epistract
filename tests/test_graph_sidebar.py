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


@pytest.mark.unit
def test_sidebar_relations_and_source_counts():
    if shutil.which("node") is None:
        pytest.skip("node not available")
    result = subprocess.run(
        ["node", str(HARNESS), str(GLP1 / "graph_data.json")],
        timeout=60,
        capture_output=True,
        text=True,
    )
    try:
        report = json.loads(result.stdout.strip().splitlines()[-1])
    except (IndexError, ValueError):
        report = {"failed": ["unparseable harness output"]}
    assert result.returncode == 0 and report["failed"] == [], (
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
