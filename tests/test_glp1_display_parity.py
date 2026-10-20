"""Real-data parity checks: GLP-1 graph colors, API payload and single-source frontend."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
GLP1 = ROOT / "tests" / "corpora" / "06_glp1_landscape" / "output-v3"
STATIC = ROOT / "examples" / "workbench" / "static"
HARNESS = Path(__file__).resolve().parent / "js" / "display_parity_harness.mjs"
DRUG_YAML = ROOT / "domains" / "drug-discovery" / "domain.yaml"

EXPECTED_COUNTS = {
    "DISEASE": 48,
    "DOCUMENT": 34,
    "COMPOUND": 33,
    "MECHANISM_OF_ACTION": 28,
    "PHENOTYPE": 27,
    "PUBLICATION": 26,
    "BIOMARKER": 23,
    "CLINICAL_TRIAL": 20,
    "PROTEIN": 14,
    "ADVERSE_EVENT": 13,
    "ORGANIZATION": 8,
    "PATHWAY": 3,
    "REGULATORY_ACTION": 1,
}


def _counts() -> dict[str, int]:
    data = json.loads((GLP1 / "graph_data.json").read_text())
    counts: dict[str, int] = {}
    for n in data["nodes"]:
        counts[n["entity_type"]] = counts.get(n["entity_type"], 0) + 1
    return counts


def _schema() -> dict:
    return yaml.safe_load(DRUG_YAML.read_text())


def _resolved() -> dict:
    from core.graph_display import resolve_display
    from examples.workbench.template_loader import load_template

    overrides = load_template("drug-discovery").get("entity_colors")
    return resolve_display(_schema(), set(_counts()), overrides)


def _payload(tmp_path: Path) -> dict:
    from examples.workbench.server import create_app
    from starlette.testclient import TestClient

    shutil.copy(GLP1 / "graph_data.json", tmp_path / "graph_data.json")
    client = TestClient(create_app(tmp_path))
    resp = client.get("/api/graph/entity-types")
    assert resp.status_code == 200
    return resp.json()


def _strip(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"//[^\n]*", "", text)


@pytest.mark.unit
def test_glp1_resolved_unique_and_declared():
    assert _counts() == EXPECTED_COUNTS
    result = _resolved()
    types = result["types"]
    assert len(types) == 18
    colors = [v["color"] for v in types.values()]
    assert len(set(colors)) == 18, "duplicate colors among resolvable types"
    assert result["warnings"] == []
    for t, v in types.items():
        assert v["origin"] in {"declared", "pipeline"}, f"{t} origin {v['origin']}"
    assert types["DOCUMENT"]["color"] == "#6b7280"
    assert types["PUBLICATION"]["color"] == "#a8a29e"
    assert types["DOCUMENT"]["shape"] == "dot"
    assert types["PUBLICATION"]["shape"] == "dot"
    observed = set(EXPECTED_COUNTS)
    assert len({types[t]["shape"] for t in observed}) >= 6
    by_family: dict[str, set[str]] = {}
    for v in types.values():
        by_family.setdefault(v["family"], set()).add(v["shape"])
    for fam, shapes in by_family.items():
        assert len(shapes) == 1, f"family {fam} has shapes {shapes}"


@pytest.mark.unit
def test_glp1_api_matches_resolver(tmp_path):
    body = _payload(tmp_path)
    expected = _resolved()["types"]
    schema_types = _schema()["entity_types"]
    assert {t["type"] for t in body["types"]} == set(EXPECTED_COUNTS)
    for entry in body["types"]:
        exp = expected[entry["type"]]
        for key in ("color", "shape", "family", "label"):
            assert entry[key] == exp[key], f"{entry['type']}.{key}"
        assert entry["count"] == body["entity_types"][entry["type"]]
        if entry["type"] in schema_types:
            assert entry["description"] == schema_types[entry["type"]]["description"]


@pytest.mark.unit
def test_single_resolved_map_static_guard():
    hex_array = re.compile(r"\[\s*['\"]#[0-9a-fA-F]{6}['\"]\s*,\s*['\"]#[0-9a-fA-F]{6}['\"]")
    code = {n: _strip((STATIC / n).read_text()) for n in ("graph.js", "app.js", "sidebar.js")}
    for name, js in code.items():
        assert "from './display.js'" in js, f"{name} does not import display.js"
        for banned in ("PALETTE", "ENTITY_COLORS", "entity_colors", "getEntityColor"):
            assert banned not in js, f"{name} contains {banned}"
        assert not hex_array.search(js), f"{name} has a hex color array"
        assert "Math.random" not in js, f"{name} calls Math.random"
        assert not re.search(r"%\s*PALETTE|#[0-9a-fA-F]{6}[^\n]*\.length\]", js)
    for name in ("graph_style.js", "hovercard.js"):
        js = _strip((STATIC / name).read_text())
        for banned in ("PALETTE", "ENTITY_COLORS", "entity_colors", "getEntityColor"):
            assert banned not in js, f"{name} contains {banned}"
        assert not hex_array.search(js), f"{name} has a hex color array"
        assert "Math.random" not in js, f"{name} calls Math.random"
        assert "createElementNS" not in js, f"{name} builds SVG itself"
        assert "SWATCH_GEOMETRY" not in js, f"{name} references swatch geometry"
        assert not re.search(r"\.innerHTML\s*=", js), f"{name} assigns innerHTML"
        if name == "hovercard.js":
            assert "from './display.js'" in js, "hovercard.js does not import display.js"
    graph = code["graph.js"]
    assert re.search(r"shape:\s*d\.shape", graph) or "typeDisplay(" in graph
    assert "shape: 'dot'" not in graph
    assert "nodeColor" in graph or "typeDisplay(" in graph
    assert "makeSwatch(" in code["app.js"]
    assert "makeSwatch(" in code["sidebar.js"]
    assert "buildLegendChip(" in graph
    holders = {
        p.name
        for p in STATIC.glob("*.js")
        if p.name != "vis-network.min.js"
        and "createElementNS" in _strip(p.read_text())
        and "SWATCH_GEOMETRY" in _strip(p.read_text())
    }
    assert holders == {"display.js"}
    for p in STATIC.glob("*.js"):
        if p.name in ("vis-network.min.js", "display.js"):
            continue
        text = _strip(p.read_text())
        assert "createElementNS" not in text, f"{p.name} builds SVG itself"
        assert "SWATCH_GEOMETRY" not in text, f"{p.name} references swatch geometry"
    for name in ("display.js", "sidebar.js"):
        text = _strip((STATIC / name).read_text())
        assert "innerHTML" not in text, f"{name} uses innerHTML"


@pytest.mark.unit
def test_glp1_swatch_parity_harness(tmp_path):
    if shutil.which("node") is None:
        pytest.skip("node not available")
    payload_path = tmp_path / "payload.json"
    payload_path.write_text(json.dumps(_payload(tmp_path)))
    result = subprocess.run(
        ["node", str(HARNESS), str(payload_path)],
        timeout=30,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"
