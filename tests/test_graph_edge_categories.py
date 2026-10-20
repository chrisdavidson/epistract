"""Relation category colors, dashes and the edge key: resolver, API and browser harnesses."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from itertools import combinations
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
GLP1 = ROOT / "tests" / "corpora" / "06_glp1_landscape" / "output-v3"
DRUG_YAML = ROOT / "domains" / "drug-discovery" / "domain.yaml"
JS = Path(__file__).resolve().parent / "js"
STYLE_HARNESS = JS / "edge_style_harness.mjs"
FILTER_HARNESS = JS / "graph_filter_harness.mjs"
NEUTRAL = "#8b8f99"


# ---------------------------------------------------------------------------
# Color math: WCAG contrast and CIELAB deltaE76
# ---------------------------------------------------------------------------


def _rgb(hex_color: str) -> tuple[float, float, float]:
    return tuple(int(hex_color[i : i + 2], 16) / 255 for i in (1, 3, 5))


def _linear(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _luminance(hex_color: str) -> float:
    r, g, b = (_linear(c) for c in _rgb(hex_color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(a: str, b: str) -> float:
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _srgb_to_lab(hex_color: str) -> tuple[float, float, float]:
    r, g, b = (_linear(c) for c in _rgb(hex_color))
    x = 0.4124564 * r + 0.3575761 * g + 0.1804375 * b
    y = 0.2126729 * r + 0.7151522 * g + 0.0721750 * b
    z = 0.0193339 * r + 0.1191920 * g + 0.9503041 * b
    xn, yn, zn = 0.95047, 1.0, 1.08883

    def f(t: float) -> float:
        return t ** (1 / 3) if t > (6 / 29) ** 3 else t / (3 * (6 / 29) ** 2) + 4 / 29

    fx, fy, fz = f(x / xn), f(y / yn), f(z / zn)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def _delta_e76(a: str, b: str) -> float:
    la, lb = _srgb_to_lab(a), _srgb_to_lab(b)
    return sum((p - q) ** 2 for p, q in zip(la, lb, strict=True)) ** 0.5


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _graph() -> dict:
    return json.loads((GLP1 / "graph_data.json").read_text())


def _display() -> dict:
    from core.graph_display import resolve_display

    observed = {n["entity_type"] for n in _graph()["nodes"]}
    return resolve_display(yaml.safe_load(DRUG_YAML.read_text()), observed, None)


def _payload(tmp_path: Path) -> dict:
    from examples.workbench.server import create_app
    from starlette.testclient import TestClient

    shutil.copy(GLP1 / "graph_data.json", tmp_path / "graph_data.json")
    resp = TestClient(create_app(tmp_path)).get("/api/graph/entity-types")
    assert resp.status_code == 200, resp.text
    return resp.json()


def _need_node() -> None:
    if shutil.which("node") is None:
        pytest.skip("node not available")


# ---------------------------------------------------------------------------
# Palette and resolver
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_category_palette_gates():
    from core.graph_display import RELATION_CATEGORIES, RELATION_CATEGORY_COLORS

    assert set(RELATION_CATEGORY_COLORS) == set(RELATION_CATEGORIES)
    colors = list(RELATION_CATEGORY_COLORS.values())
    assert len(colors) == 9
    assert all(re.fullmatch(r"#[0-9a-f]{6}", c) for c in colors), colors
    assert len(set(colors)) == 9, "duplicate category colors"
    for name, color in RELATION_CATEGORY_COLORS.items():
        ratio = _contrast(color, "#ffffff")
        assert ratio >= 3.0, f"{name} {color} contrast {ratio:.2f} on white"
    pairs = [(a, b, _delta_e76(a, b)) for a, b in combinations(colors, 2)]
    worst = min(pairs, key=lambda p: p[2])
    assert worst[2] >= 10, f"closest pair {worst[0]} / {worst[1]} deltaE76 {worst[2]:.1f}"


@pytest.mark.unit
def test_resolver_serves_categories_and_relation_colors():
    from core.graph_display import RELATION_CATEGORIES

    display = _display()
    cats = display["categories"]
    assert tuple(cats) == RELATION_CATEGORIES
    for name, spec in cats.items():
        assert set(spec) == {"label", "color"}, spec
        assert spec["label"], name
    for rel, spec in display["relations"].items():
        assert spec["color"] == cats[spec["category"]]["color"], (rel, spec)


@pytest.mark.unit
def test_relation_category_defaults_to_other():
    from core.graph_display import RELATION_CATEGORY_COLORS, relation_category, resolve_display

    display = _display()
    other = RELATION_CATEGORY_COLORS["other"]
    assert relation_category(display, "NOT_IN_SCHEMA") == ("other", other)
    assert relation_category(display, None) == ("other", other)
    assert relation_category({}, "X") == ("other", other)
    assert relation_category(display, "MENTIONED_IN")[0] == "provenance"
    bare = resolve_display(None)
    for spec in bare["relations"].values():
        assert re.fullmatch(r"#[0-9a-f]{6}", spec["color"]), spec
    assert set(bare["categories"]) >= {"provenance", "other"}


@pytest.mark.unit
def test_api_serves_categories_for_glp1(tmp_path):
    body = _payload(tmp_path)
    assert set(body["categories"]) >= {"mechanism", "therapeutic", "other"}
    for rel, spec in body["relations"].items():
        assert spec["color"] == body["categories"][spec["category"]]["color"], rel
    from core.graph_display import relation_category

    display = _display()
    for link in _graph()["links"]:
        category, color = relation_category(display, link["relation_type"])
        assert category in body["categories"], link["relation_type"]
        assert re.fullmatch(r"#[0-9a-f]{6}", color), link["relation_type"]


# ---------------------------------------------------------------------------
# Browser harnesses
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_js_edge_style_harness(tmp_path):
    _need_node()
    path = tmp_path / "payload.json"
    path.write_text(json.dumps(_payload(tmp_path)))
    result = subprocess.run(
        ["node", str(STYLE_HARNESS), str(path)], timeout=30, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stdout + result.stderr
    out = json.loads(result.stdout.strip().splitlines()[-1])
    assert out["failed"] == [], out["failed"]
    assert out["passed"], out


@pytest.mark.unit
def test_js_edges_mode_colors_dashes_and_highlight_restore():
    _need_node()
    result = subprocess.run(
        ["node", str(FILTER_HARNESS), "edges"], timeout=30, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stdout + result.stderr
    out = json.loads(result.stdout.strip().splitlines()[-1])
    assert out["failed"] == [], out["failed"]
    assert out["passed"], out


@pytest.mark.unit
def test_js_edges_mode_display_failure_uses_neutral_edges():
    _need_node()
    result = subprocess.run(
        ["node", str(FILTER_HARNESS), "edges-fail"], timeout=30, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stdout + result.stderr
    out = json.loads(result.stdout.strip().splitlines()[-1])
    assert out["failed"] == [], out["failed"]
    assert out["passed"], out


@pytest.mark.unit
def test_graph_js_has_no_palette_or_svg_construction():
    text = re.sub(r"//[^\n]*", "", (ROOT / "examples/workbench/static/graph.js").read_text())
    assert "createElementNS" not in text
    assert "opacity: 1.0" not in text
