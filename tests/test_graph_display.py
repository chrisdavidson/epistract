"""Tests for the graph display resolver, its API, and the single JS color source."""

from __future__ import annotations

import copy
import json
import math
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
GLP1 = ROOT / "tests" / "corpora" / "06_glp1_landscape" / "output-v3"
STATIC = ROOT / "examples" / "workbench" / "static"
HARNESS = Path(__file__).resolve().parent / "js" / "display_harness.mjs"
DRUG_YAML = ROOT / "domains" / "drug-discovery" / "domain.yaml"

SURFACE_LIGHT = "#ffffff"
SURFACE_DARK = "#1a1a2e"


# ---------------------------------------------------------------------------
# Color math helpers (sRGB -> linear -> OKLab, WCAG contrast)
# ---------------------------------------------------------------------------


def _rgb(hex_color: str) -> tuple[float, float, float]:
    return tuple(int(hex_color[i : i + 2], 16) / 255 for i in (1, 3, 5))


def _linear(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _luminance(hex_color: str) -> float:
    r, g, b = (_linear(c) for c in _rgb(hex_color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(a: str, b: str) -> float:
    la, lb = _luminance(a), _luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _oklab(hex_color: str) -> tuple[float, float, float]:
    r, g, b = (_linear(c) for c in _rgb(hex_color))
    lng = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b
    mid = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b
    s = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b
    lng, mid, s = lng ** (1 / 3), mid ** (1 / 3), s ** (1 / 3)
    return (
        0.2104542553 * lng + 0.7936177850 * mid - 0.0040720468 * s,
        1.9779984951 * lng - 2.4285922050 * mid + 0.4505937099 * s,
        0.0259040371 * lng + 0.7827717662 * mid - 0.8086757660 * s,
    )


def _delta_e(a: str, b: str) -> float:
    return 100 * math.dist(_oklab(a), _oklab(b))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _glp1_nodes() -> list[dict]:
    return json.loads((GLP1 / "graph_data.json").read_text())["nodes"]


def _glp1_observed() -> set[str]:
    return {n["entity_type"] for n in _glp1_nodes()}


def _drug_schema() -> dict:
    return yaml.safe_load(DRUG_YAML.read_text())


def _glp1_payload(tmp_path: Path) -> dict:
    from examples.workbench.server import create_app
    from starlette.testclient import TestClient

    shutil.copy(GLP1 / "graph_data.json", tmp_path / "graph_data.json")
    client = TestClient(create_app(tmp_path))
    resp = client.get("/api/graph/entity-types")
    assert resp.status_code == 200
    return resp.json()


def _strip_js_comments(text: str) -> str:
    return re.sub(r"//[^\n]*", "", text)


# ---------------------------------------------------------------------------
# Palette
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_palette_invariants():
    from core.graph_display import PALETTE, PIPELINE_TYPES

    assert len(PALETTE) == 24
    assert all(re.fullmatch(r"#[0-9a-f]{6}", c) for c in PALETTE)
    assert len(set(PALETTE)) == 24
    for c in PALETTE:
        assert _contrast(c, SURFACE_LIGHT) >= 3.0, f"{c} too light on white"
        assert _contrast(c, SURFACE_DARK) >= 3.0, f"{c} too dark on nav"
    for i, a in enumerate(PALETTE):
        for b in PALETTE[i + 1 :]:
            assert _delta_e(a, b) >= 6, f"{a} and {b} too close"
    for name, spec in PIPELINE_TYPES.items():
        assert spec["color"] not in PALETTE, f"{name} grey collides with palette"


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_resolve_schema_none_unique():
    from core.graph_display import PALETTE, resolve_display

    result = resolve_display(None, ["ZED", "ALPHA", "MID"])
    types = result["types"]
    assert set(types) == {"ZED", "ALPHA", "MID"}
    assert len({t["color"] for t in types.values()}) == 3
    for t in types.values():
        assert t["origin"] == "auto"
        assert t["family"] == "Other"
        assert t["shape"] == "dot"
    assert types["ALPHA"]["color"] == PALETTE[0]
    assert types["MID"]["color"] == PALETTE[1]
    assert types["ZED"]["color"] == PALETTE[2]


@pytest.mark.unit
def test_resolve_glp1_unique_colors():
    from core.graph_display import resolve_display

    observed = _glp1_observed()
    assert len(observed) == 13
    result = resolve_display(_drug_schema(), observed, None)
    types = result["types"]
    for t in observed:
        assert t in types
    colors = [v["color"] for v in types.values()]
    assert len(colors) == len(set(colors)), "duplicate colors in resolved types"
    assert types["DOCUMENT"]["color"] == "#6b7280"
    assert types["PUBLICATION"]["color"] == "#a8a29e"
    for t in ("DOCUMENT", "PUBLICATION"):
        assert types[t]["family"] == "Sources"
        assert types[t]["shape"] == "dot"


@pytest.mark.unit
def test_exhaustion_60_types():
    from core.graph_display import resolve_display

    schema = {"entity_types": {f"T{i:02d}": f"desc {i}" for i in range(60)}}
    first = resolve_display(schema, ())
    second = resolve_display(schema, ())
    colors = [v["color"] for v in first["types"].values()]
    assert len(colors) == 60
    assert len(set(colors)) == 60
    assert all(re.fullmatch(r"#[0-9a-f]{6}", c) for c in colors)
    assert first["types"] == second["types"]


@pytest.mark.unit
def test_declared_display_wins_and_is_claimed():
    from core.graph_display import resolve_display

    schema = {
        "entity_types": {
            "A": {
                "description": "a",
                "display": {"family": "Interventions", "color": "#5F66ED"},
            },
            "B": {"description": "b"},
        }
    }
    types = resolve_display(schema, ())["types"]
    assert types["A"]["color"] == "#5f66ed"
    assert types["A"]["origin"] == "declared"
    assert types["A"]["shape"] == "hexagon"
    assert types["B"]["color"] != "#5f66ed"


@pytest.mark.unit
def test_override_wins_and_collision_warns():
    from core.graph_display import resolve_display

    schema = {
        "entity_types": {
            "A": {"description": "a", "display": {"color": "#5f66ed"}},
            "B": {"description": "b"},
        }
    }
    result = resolve_display(schema, (), {"A": "#123456"})
    assert result["types"]["A"]["color"] == "#123456"
    assert result["types"]["A"]["origin"] == "override"

    result = resolve_display(schema, (), {"B": "#5f66ed"})
    assert result["types"]["A"]["color"] == "#5f66ed"
    assert result["types"]["B"]["color"] == "#5f66ed"
    assert any("A" in w and "B" in w for w in result["warnings"]), result["warnings"]


@pytest.mark.unit
def test_invalid_display_warns_not_raises():
    from core.graph_display import (
        ALLOWED_SHAPES,
        PALETTE,
        resolve_display,
        validate_display,
    )

    schema = {
        "entity_types": {
            "RED": {"description": "", "display": {"color": "red"}},
            "SHORT": {"description": "", "display": {"color": "#12"}},
            "JS": {"description": "", "display": {"color": "javascript:x"}},
            "ELL": {"description": "", "display": {"shape": "ellipse"}},
            "SCR": {"description": "", "display": {"shape": "script"}},
            "TRI": {"description": "", "display": {"color": "#abc"}},
        }
    }
    warnings = validate_display(schema)
    for name in ("RED", "SHORT", "JS", "ELL", "SCR"):
        assert any(name in w for w in warnings), f"no warning for {name}: {warnings}"
    result = resolve_display(schema, ())
    types = result["types"]
    for name in ("RED", "SHORT", "JS"):
        assert types[name]["color"] in PALETTE
    for name in ("ELL", "SCR"):
        assert types[name]["shape"] in ALLOWED_SHAPES
        assert types[name]["shape"] == "dot"
    assert types["TRI"]["color"] == "#aabbcc"


@pytest.mark.unit
def test_family_shapes():
    from core.graph_display import CUSTOM_SHAPE_ORDER, resolve_display

    schema = {
        "entity_types": {
            "M1": {"description": "", "display": {"family": "Molecular"}},
            "M2": {"description": "", "display": {"family": "Molecular", "shape": "star"}},
            "W1": {"description": "", "display": {"family": "Widgets"}},
            "S1": {"description": "", "display": {"family": "Sources"}},
        }
    }
    result = resolve_display(schema, ())
    types = result["types"]
    assert types["M1"]["shape"] == "triangle"
    assert types["M2"]["shape"] == "triangle"
    assert any("M2" in w for w in result["warnings"]), result["warnings"]
    used = {"triangle", "dot"}
    expected = next(s for s in CUSTOM_SHAPE_ORDER if s not in used)
    assert types["W1"]["shape"] in CUSTOM_SHAPE_ORDER
    assert types["W1"]["shape"] not in used or types["W1"]["shape"] == expected
    assert result["families"][-1]["name"] == "Sources"
    assert {f["name"] for f in result["families"]} == {"Molecular", "Widgets", "Sources"}


@pytest.mark.unit
def test_humanize_type():
    from core.graph_display import humanize_type

    assert humanize_type("AdverseEvent") == "Adverse event"
    assert humanize_type("MECHANISM_OF_ACTION") == "Mechanism of action"
    assert humanize_type("TrialPhase") == "Trial phase"
    assert humanize_type("DOCUMENT") == "Document"
    assert humanize_type("CLINICAL_TRIAL") == "Clinical trial"


@pytest.mark.unit
def test_relations():
    from core.graph_display import resolve_display

    schema = {
        "relation_types": {
            "R1": {"description": "one", "category": "mechanism"},
            "R2": "desc",
            "R3": {"description": "three", "category": "zzz"},
            "R4": {"description": "four"},
        }
    }
    result = resolve_display(schema, ())
    rel = result["relations"]
    assert rel["R1"]["category"] == "mechanism"
    assert rel["R2"]["description"] == "desc"
    assert rel["R2"]["category"] == "other"
    assert rel["R3"]["category"] == "other"
    assert any("R3" in w for w in result["warnings"])
    assert rel["R4"]["category"] == "other"
    assert rel["MENTIONED_IN"]["category"] == "provenance"


@pytest.mark.unit
def test_fill_display_defaults_pure():
    from core.graph_display import fill_display_defaults

    entity_types = {
        "A": {"description": "a", "display": {"color": "#123456"}},
        "B": {"description": "b"},
        "C": "plain",
    }
    before = copy.deepcopy(entity_types)
    families = {"B": {"family": "Interventions"}, "C": {"family": "Molecular"}}
    out1 = fill_display_defaults(entity_types, families)
    out2 = fill_display_defaults(entity_types, families)
    assert entity_types == before
    assert out1 == out2
    assert set(out1) == {"A", "B", "C"}
    for spec in out1.values():
        assert {"family", "shape", "color"} <= set(spec)
    assert out1["A"]["color"] == "#123456"
    assert out1["B"]["family"] == "Interventions"
    assert out1["B"]["shape"] == "hexagon"
    assert out1["C"]["shape"] == "triangle"
    assert len({s["color"] for s in out1.values()}) == 3


@pytest.mark.unit
def test_graph_display_import_light():
    text = (ROOT / "core" / "graph_display.py").read_text()
    for line in text.splitlines():
        stripped = line.strip()
        assert not stripped.startswith("import examples"), line
        assert not stripped.startswith("from examples"), line
        assert not stripped.startswith("from core"), line


@pytest.mark.unit
def test_sift_kg_accepts_display_keys(tmp_path):
    sift_kg = pytest.importorskip("sift_kg")
    schema = _drug_schema()
    schema["entity_types"]["COMPOUND"]["display"] = {
        "family": "Interventions",
        "shape": "hexagon",
        "color": "#5f66ed",
    }
    schema["relation_types"]["TARGETS"]["category"] = "therapeutic"
    tmp_yaml = tmp_path / "domain.yaml"
    tmp_yaml.write_text(yaml.safe_dump(schema))
    loaded = sift_kg.load_domain(domain_path=tmp_yaml)
    assert len(loaded.entity_types) == 17


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_api_entity_types_glp1(tmp_path):
    from core.graph_display import resolve_display
    from examples.workbench.template_loader import load_template

    nodes = _glp1_nodes()
    counts: dict[str, int] = {}
    for n in nodes:
        counts[n["entity_type"]] = counts.get(n["entity_type"], 0) + 1
    body = _glp1_payload(tmp_path)

    assert body["entity_types"] == counts
    assert len(body["entity_types"]) == 13
    assert {t["type"] for t in body["types"]} == set(counts)
    keys = {"type", "label", "count", "description", "family", "shape", "color"}
    overrides = load_template("drug-discovery").get("entity_colors")
    expected = resolve_display(_drug_schema(), set(counts), overrides)["types"]
    for entry in body["types"]:
        assert keys <= set(entry)
        assert entry["count"] == counts[entry["type"]]
        assert entry["color"] == expected[entry["type"]]["color"]
    api_colors = [t["color"] for t in body["types"]]
    assert len(set(api_colors)) == 13
    assert isinstance(body["families"], list)
    assert all({"name", "shape"} <= set(f) for f in body["families"])
    assert isinstance(body["relations"], dict)
    assert "TARGETS" in body["relations"]


@pytest.mark.unit
def test_api_entity_types_sample_fixture(tmp_path):
    from examples.workbench.server import create_app
    from starlette.testclient import TestClient

    shutil.copy(
        ROOT / "tests" / "fixtures" / "sample_graph_data.json", tmp_path / "graph_data.json"
    )
    client = TestClient(create_app(tmp_path, domain="contracts"))
    body = client.get("/api/graph/entity-types").json()
    assert "PARTY" in body["entity_types"]
    assert "PARTY" in {t["type"] for t in body["types"]}
    colors = [t["color"] for t in body["types"]]
    assert len(colors) == len(set(colors))


# ---------------------------------------------------------------------------
# Frontend single source
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_js_single_source():
    hex_array = re.compile(
        r"\[\s*['\"]#[0-9a-fA-F]{6}['\"]\s*,\s*['\"]#[0-9a-fA-F]{6}['\"]\s*,\s*['\"]#"
    )
    for name in ("graph.js", "app.js"):
        js = _strip_js_comments((STATIC / name).read_text())
        assert "PALETTE" not in js, f"{name} still has PALETTE"
        assert "ENTITY_COLORS" not in js, f"{name} still has ENTITY_COLORS"
        assert "entity_colors" not in js, f"{name} still reads entity_colors"
        assert not hex_array.search(js), f"{name} has a hex color array"
        assert "from './display.js'" in js, f"{name} does not import display.js"
        assert "charAt(0) + type" not in js, f"{name} has its own label formatter"
    graph = _strip_js_comments((STATIC / "graph.js").read_text())
    assert "shape: 'dot'" not in graph
    sidebar = _strip_js_comments((STATIC / "sidebar.js").read_text())
    assert "PALETTE" not in sidebar
    assert "entity_colors" not in sidebar


@pytest.mark.unit
def test_js_display_harness(tmp_path):
    if shutil.which("node") is None:
        pytest.skip("node not available")
    payload = _glp1_payload(tmp_path)
    payload_path = tmp_path / "payload.json"
    payload_path.write_text(json.dumps(payload))
    result = subprocess.run(
        ["node", str(HARNESS), str(payload_path)],
        timeout=30,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"harness failed\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )


@pytest.mark.unit
def test_api_entity_types_null_and_non_string_types(tmp_path):
    """WR-01: null, missing, empty and non-string entity types must not 500."""
    from examples.workbench.server import create_app
    from starlette.testclient import TestClient

    nodes = [
        {"id": "a", "name": "A", "entity_type": "COMPOUND"},
        {"id": "b", "name": "B", "entity_type": None},
        {"id": "c", "name": "C"},
        {"id": "d", "name": "D", "entity_type": ""},
        {"id": "e", "name": "E", "entity_type": 123},
    ]
    (tmp_path / "graph_data.json").write_text(
        json.dumps({"metadata": {}, "nodes": nodes, "links": []})
    )
    resp = TestClient(create_app(tmp_path)).get("/api/graph/entity-types")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["entity_types"] == {"COMPOUND": 1, "UNKNOWN": 3, "123": 1}
    by_type = {t["type"]: t for t in body["types"]}
    assert set(by_type) == {"COMPOUND", "UNKNOWN", "123"}
    colors = [t["color"] for t in body["types"]]
    assert len(colors) == len(set(colors)), "resolved colors must stay unique"


@pytest.mark.unit
def test_js_type_key_matches_python():
    """WR-01: display.js typeKey mirrors core.graph_display.entity_type_key."""
    if shutil.which("node") is None:
        pytest.skip("node not available")
    from core.graph_display import entity_type_key

    url = (STATIC / "display.js").resolve().as_uri()
    script = (
        f"const m = await import({json.dumps(url)});\n"
        "process.stdout.write(JSON.stringify("
        "[null, undefined, '', 123, 'COMPOUND'].map(m.typeKey)));\n"
    )
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        timeout=30,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    expected = [entity_type_key(v) for v in (None, None, "", 123, "COMPOUND")]
    assert json.loads(result.stdout) == expected


@pytest.mark.unit
@pytest.mark.parametrize("mode", ["ok", "fail"])
def test_js_filter_keeps_nodes_when_display_missing(mode):
    """WR-02: a failed display load must not make filters hide every node.

    With the display loaded, every type starts active (null types included,
    via typeKey); with it missing, the type filter is disabled.
    """
    if shutil.which("node") is None:
        pytest.skip("node not available")
    harness = Path(__file__).resolve().parent / "js" / "graph_filter_harness.mjs"
    result = subprocess.run(
        ["node", str(harness), mode], timeout=30, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout.strip().splitlines()[-1])
    assert out["total"] == 3, out
    assert out["hidden"] == [], f"filter hid nodes in {mode} mode: {out}"


@pytest.mark.unit
def test_family_spelling_is_canonical_per_family():
    """WR-03: case variants of one family share one spelling everywhere."""
    from core.graph_display import resolve_display

    schema = {
        "entity_types": {
            "A": {"display": {"family": "molecular"}},
            "B": {"display": {"family": "Molecular"}},
            "C": {"display": {"family": "sources"}},
            "D": {"display": {"family": "OTHER"}},
        }
    }
    display = resolve_display(schema, ())
    types = display["types"]
    assert types["A"]["family"] == types["B"]["family"] == "molecular"
    assert types["C"]["family"] == "Sources"
    assert types["D"]["family"] == "Other"
    family_names = [f["name"] for f in display["families"]]
    assert family_names == ["molecular", "Other", "Sources"]
    for t in types.values():
        assert t["family"] in family_names
