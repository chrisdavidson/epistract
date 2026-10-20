"""Sources-hidden-by-default: resolver flags, API pass-through and browser harness."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
GLP1 = ROOT / "tests" / "corpora" / "06_glp1_landscape" / "output-v3"
DRUG_YAML = ROOT / "domains" / "drug-discovery" / "domain.yaml"
HARNESS = Path(__file__).resolve().parent / "js" / "graph_filter_harness.mjs"


def _graph() -> dict:
    return json.loads((GLP1 / "graph_data.json").read_text())


def _observed() -> set[str]:
    return {n["entity_type"] for n in _graph()["nodes"]}


def _display() -> dict:
    from core.graph_display import resolve_display

    return resolve_display(yaml.safe_load(DRUG_YAML.read_text()), _observed(), None)


@pytest.mark.unit
def test_resolver_flags_sources():
    display = _display()
    for name, spec in display["types"].items():
        expected = name in ("DOCUMENT", "PUBLICATION")
        assert spec["is_source"] is expected, f"{name}.is_source={spec['is_source']}"
    rel = display["relations"]
    for name in ("MENTIONED_IN", "PUBLISHED_IN"):
        assert rel[name]["category"] == "provenance", f"{name}: {rel[name]}"
    assert rel["MENTIONED_IN"]["source_edge"] is True, rel["MENTIONED_IN"]
    assert rel["TARGETS"]["source_edge"] is False, rel["TARGETS"]


@pytest.mark.unit
def test_resolver_without_schema_keeps_pipeline_relations():
    from core.graph_display import resolve_display

    display = resolve_display(None, ["FOO"])
    assert display["types"]["FOO"]["is_source"] is False
    for name in ("MENTIONED_IN", "PUBLISHED_IN"):
        assert display["relations"][name]["category"] == "provenance", display["relations"]


@pytest.mark.unit
def test_is_source_edge_glp1_counts():
    from core.graph_display import is_source_edge

    data = _graph()
    display = _display()
    source_ids = {
        n["id"] for n in data["nodes"] if display["types"][n["entity_type"]]["is_source"]
    }
    assert len(source_ids) == 60, len(source_ids)
    flags = [is_source_edge(e, source_ids, display["relations"]) for e in data["links"]]
    assert sum(flags) == 487, f"source edges: {sum(flags)}"
    assert flags.count(False) == 368, f"knowledge edges: {flags.count(False)}"
    assert is_source_edge({}, source_ids, display["relations"]) is False


@pytest.mark.unit
def test_api_entity_types_serves_source_flags(tmp_path):
    from examples.workbench.server import create_app
    from starlette.testclient import TestClient

    shutil.copy(GLP1 / "graph_data.json", tmp_path / "graph_data.json")
    client = TestClient(create_app(tmp_path))
    resp = client.get("/api/graph/entity-types")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    for entry in body["types"]:
        assert isinstance(entry.get("is_source"), bool), entry
        assert entry["is_source"] is (entry["type"] in ("DOCUMENT", "PUBLICATION")), entry
    assert body["relations"]["MENTIONED_IN"]["source_edge"] is True, body["relations"]


@pytest.mark.unit
@pytest.mark.parametrize("mode", ["sources", "nosources"])
def test_js_sources_toggle(mode):
    if shutil.which("node") is None:
        pytest.skip("node not available")
    result = subprocess.run(
        ["node", str(HARNESS), mode], timeout=30, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout.strip().splitlines()[-1])
    if mode == "sources":
        assert out["initialHidden"] == ["d1"], out
        assert out["initialHiddenEdges"] == 1, out
        assert out["afterShow"] == [], out
        assert out["pressed"] == "true", out
        assert out["label"] == "Hide sources", out
        assert out["afterHide"] == ["d1"], out
        assert out["disabled"] is False, out
    else:
        assert out["disabled"] is True, out
        assert out["initialHidden"] == [], out
        assert out["initialHiddenEdges"] == 0, out
