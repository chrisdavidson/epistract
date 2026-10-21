"""Source viewer: node harness for source_viewer.js (states, Back/Esc, origin, SEC-01)."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

JS_DIR = Path(__file__).resolve().parent / "js"
VIEWER_HARNESS = JS_DIR / "source_viewer_harness.mjs"

pytestmark = pytest.mark.unit


def _run(harness: Path) -> dict:
    if shutil.which("node") is None:
        pytest.skip("node not available")
    result = subprocess.run(["node", str(harness)], timeout=60, capture_output=True, text=True)
    assert result.stdout.strip(), result.stderr
    out = json.loads(result.stdout.strip().splitlines()[-1])
    assert result.returncode == 0, f"failed: {out.get('failed')}\n{result.stderr}"
    return out


def test_source_viewer_harness():
    out = _run(VIEWER_HARNESS)
    assert out["failed"] == [], out["failed"]
    assert out["passed"], "harness ran no checks"
