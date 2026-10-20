"""Hover card model, DOM safety, wiring and latency (node harness)."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.synthetic_graph import make_synthetic_graph, write_synthetic_graph

ROOT = Path(__file__).resolve().parent.parent
GLP1 = ROOT / "tests" / "corpora" / "06_glp1_landscape" / "output-v3"
HARNESS = Path(__file__).resolve().parent / "js" / "hover_harness.mjs"


def _need_node() -> None:
    if shutil.which("node") is None:
        pytest.skip("node not available")


def _display_payload(tmp_path: Path) -> Path:
    from examples.workbench.server import create_app
    from starlette.testclient import TestClient

    work = tmp_path / "glp1"
    work.mkdir()
    shutil.copy(GLP1 / "graph_data.json", work / "graph_data.json")
    resp = TestClient(create_app(work)).get("/api/graph/entity-types")
    assert resp.status_code == 200
    out = tmp_path / "display.json"
    out.write_text(json.dumps(resp.json(), indent=2))
    return out


def _run(graph: Path, display: Path, mode: str) -> dict:
    result = subprocess.run(
        ["node", str(HARNESS), str(graph), str(display), mode],
        timeout=120,
        capture_output=True,
        text=True,
    )
    try:
        report = json.loads(result.stdout.strip().splitlines()[-1])
    except (IndexError, ValueError):
        report = {"passed": [], "failed": ["unparseable harness output"], "timings": {}}
    assert result.returncode == 0 and report["failed"] == [], (
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert report["passed"], report
    return report


@pytest.mark.unit
def test_synthetic_graph_is_deterministic_and_sized():
    a = make_synthetic_graph(1738, 2500, 7)
    b = make_synthetic_graph(1738, 2500, 7)
    assert len(a["nodes"]) == 1738
    assert len(a["links"]) == 2500
    assert a == b


@pytest.mark.unit
def test_hover_card_model_and_dom_on_glp1(tmp_path):
    _need_node()
    display = _display_payload(tmp_path)
    _run(GLP1 / "graph_data.json", display, "model")


@pytest.mark.unit
def test_hover_wiring_in_graph_js(tmp_path):
    _need_node()
    display = _display_payload(tmp_path)
    _run(GLP1 / "graph_data.json", display, "wiring")


@pytest.mark.unit
def test_hover_card_latency_on_synthetic_hub(tmp_path):
    _need_node()
    display = _display_payload(tmp_path)
    graph = write_synthetic_graph(tmp_path / "synthetic.json")
    report = _run(graph, display, "perf")
    timings = report["timings"]
    assert timings["nodes"] == 1738 and timings["edges"] == 2500
    assert timings["median_ms"] < 16, timings
