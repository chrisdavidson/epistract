"""Tests for the self-contained graph.html written by ``core.run_sift.cmd_view``.

``cmd_view`` renders the workbench graph modules into one offline file. These
tests cover the page contract (data island, bundle, escaping), parity of the
embedded payloads with the workbench routes, and a headless-browser smoke test.
"""

from __future__ import annotations

import html as html_lib
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from core import run_sift

pytestmark = pytest.mark.unit

NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node not installed")

CHROMIUM = shutil.which("chromium") or shutil.which("chromium-browser")
needs_chromium = pytest.mark.skipif(CHROMIUM is None, reason="chromium not installed")

ROOT = Path(__file__).resolve().parent.parent
GLP1 = ROOT / "tests" / "corpora" / "06_glp1_landscape" / "output-v3"
GLP1_FILES = ("graph_data.json", "communities.json", "claims_layer.json")

HOSTILE_TYPE = "</script><script>window.PWN=1</script>"

PAYLOAD_URLS = {
    "/api/graph",
    "/api/graph/claims",
    "/api/graph/groups",
    "/api/graph/entity-types",
}

ISLAND_RE = re.compile(
    r'<script type="application/json" id="epistract-data">(.*?)</script>', re.DOTALL
)
MODULE_RE = re.compile(r'<script type="module">(.*?)</script>', re.DOTALL)


def _write_graph(output_dir: Path, entity_types: list[str]) -> None:
    nodes = [
        {"id": f"n{i}", "name": f"Node {i}", "entity_type": t}
        for i, t in enumerate(entity_types)
    ]
    (output_dir / "graph_data.json").write_text(
        json.dumps({"metadata": {}, "nodes": nodes, "links": []}), encoding="utf-8"
    )


def _write_hostile_graph(output_dir: Path) -> None:
    nodes = [
        {"id": "n0", "name": "Aspirin", "entity_type": "COMPOUND"},
        {"id": "n1", "name": HOSTILE_TYPE, "entity_type": HOSTILE_TYPE},
    ]
    links = [
        {
            "source": "n0",
            "target": "n1",
            "relation_type": "TREATS",
            "evidence": HOSTILE_TYPE,
            "confidence": 0.9,
        }
    ]
    (output_dir / "graph_data.json").write_text(
        json.dumps({"metadata": {}, "nodes": nodes, "links": links}), encoding="utf-8"
    )


def _glp1_copy(tmp_path: Path) -> Path:
    """Copy the committed GLP-1 outputs into tmp_path; the corpus is never written."""
    work = tmp_path / "glp1"
    work.mkdir()
    for name in GLP1_FILES:
        shutil.copy2(GLP1 / name, work / name)
    return work


def _view(output_dir: Path) -> str:
    run_sift.cmd_view(str(output_dir), open_browser=False)
    return (output_dir / "graph.html").read_text(encoding="utf-8")


def _island(page: str) -> dict:
    matches = ISLAND_RE.findall(page)
    assert len(matches) == 1, f"expected exactly one data island, found {len(matches)}"
    return json.loads(matches[0])


def _bundle(page: str) -> str:
    matches = MODULE_RE.findall(page)
    assert len(matches) == 1, f"expected exactly one module script, found {len(matches)}"
    return matches[0]


@pytest.fixture
def glp1_page(tmp_path):
    work = _glp1_copy(tmp_path)
    return work, _view(work)


def test_json_for_script_escapes_html_breakout():
    encoded = run_sift._json_for_script({HOSTILE_TYPE: "#123456", "a&b ": "#abcdef"})
    for ch in ("<", ">", "&", " ", " "):
        assert ch not in encoded, f"{ch!r} left unescaped in {encoded}"
    assert json.loads(encoded) == {HOSTILE_TYPE: "#123456", "a&b ": "#abcdef"}


def test_cmd_view_writes_single_file_without_opening_browser(monkeypatch, tmp_path):
    work = _glp1_copy(tmp_path)
    import webbrowser

    def _fail(*_a, **_k):
        raise AssertionError("browser must not be opened with open_browser=False")

    monkeypatch.setattr(webbrowser, "open", _fail)
    run_sift.cmd_view(str(work), open_browser=False)

    dest = work / "graph.html"
    assert dest.is_file(), "cmd_view should write graph.html into the output dir"
    assert 1_200_000 < dest.stat().st_size < 2_500_000, (
        f"graph.html size {dest.stat().st_size} outside the expected single-file range"
    )


def test_island_has_exactly_the_four_payloads(glp1_page):
    _work, page = glp1_page
    assert set(_island(page)) == PAYLOAD_URLS, "data island keys differ from the four fetch URLs"


def test_embedded_payloads_equal_workbench_routes(glp1_page):
    from examples.workbench.server import create_app

    work, page = glp1_page
    island = _island(page)
    client = TestClient(create_app(work))
    for url in sorted(PAYLOAD_URLS):
        routed = client.get(url).json()
        assert island[url] == routed, f"embedded {url} differs from the workbench route"
    # Byte-for-byte as JSON: same key order and values.
    for url in ("/api/graph/entity-types", "/api/graph/groups"):
        assert json.dumps(island[url]) == json.dumps(client.get(url).json()), (
            f"embedded {url} serializes differently from the route"
        )


def test_page_is_fully_offline(glp1_page):
    _work, page = glp1_page
    assert "<script src=" not in page and "<script\nsrc=" not in page, "external script found"
    assert "<link " not in page, "external stylesheet link found"
    remote = re.findall(r'(?:src|href)\s*=\s*["\']\s*(?:https?:)?//[^"\']*', page)
    assert remote == [], f"remote src/href attributes found: {remote[:3]}"
    assert "@version 9.1.2" in page, "vis-network license banner missing"
    assert page.startswith("<!DOCTYPE html>"), "page should start with a doctype"


@needs_node
def test_bundle_is_valid_js_and_ids_resolve(glp1_page, tmp_path):
    _work, page = glp1_page
    bundle = _bundle(page)
    assert not re.search(r"^\s*(import|export)\b", bundle, re.M), "bundle left an import/export line"

    mjs = tmp_path / "bundle.mjs"
    mjs.write_text(bundle, encoding="utf-8")
    result = subprocess.run([NODE, "--check", str(mjs)], capture_output=True, text=True)
    assert result.returncode == 0, f"bundle is not valid JS: {result.stderr}"

    html_ids = set(re.findall(r'\bid="([^"]+)"', page))
    for ident in re.findall(r"getElementById\('([^']+)'\)", bundle):
        assert ident in html_ids, f"getElementById('{ident}') names an id missing from the page"

    for url in re.findall(r"fetch\('(/api/[^']+)'", bundle):
        assert url in PAYLOAD_URLS, f"bundle fetches {url}, which is not embedded"


def test_hostile_values_cannot_break_out_of_script_blocks(tmp_path):
    from examples.workbench import static_export

    _write_hostile_graph(tmp_path)
    page = _view(tmp_path)

    assert "<script>window.PWN" not in page, "hostile script tag appears raw in the page"
    assert page.count("</script") == len(re.findall(r"<script\b", page)), (
        "script open/close counts differ, so a block was broken out of"
    )
    island = json.dumps(_island(page))
    assert "window.PWN" in island, "hostile value should survive as data in the island"
    assert _island(page)["/api/graph"]["nodes"][1]["name"] == HOSTILE_TYPE
    assert _island(page)["/api/graph"]["edges"][0]["evidence"] == HOSTILE_TYPE

    titled = static_export.build_static_html(
        title=HOSTILE_TYPE, payload={url: {} for url in PAYLOAD_URLS}
    )
    escaped = html_lib.escape(HOSTILE_TYPE, quote=True)
    assert f"<title>{escaped} - Epistract</title>" in titled, "title must be html-escaped"
    assert "<h1" in titled and f">{escaped}</h1>" in titled, "h1 must be html-escaped"
    assert "<script>window.PWN" not in titled, "hostile title leaked a raw script tag"


def test_embedded_display_equals_resolver_including_hostile_type(tmp_path):
    _write_hostile_graph(tmp_path)
    page = _view(tmp_path)
    expected = run_sift._resolved_entity_display(tmp_path, None, {})
    types = {t["type"]: t for t in _island(page)["/api/graph/entity-types"]["types"]}

    assert set(types) == set(expected), f"types {set(types)} != resolver {set(expected)}"
    for name, spec in expected.items():
        assert types[name]["color"] == spec["color"], f"{name}: color differs"
        assert types[name]["shape"] == spec["shape"], f"{name}: shape differs"


def test_missing_graph_raises(tmp_path):
    from examples.workbench import static_export

    with pytest.raises(FileNotFoundError):
        static_export.write_static_graph(tmp_path)


@needs_chromium
def test_chromium_renders_grouped_graph_offline(glp1_page, tmp_path):
    work, _page = glp1_page
    result = subprocess.run(
        [
            CHROMIUM,
            "--headless=new",
            "--no-sandbox",
            "--disable-gpu",
            f"--user-data-dir={tmp_path / 'profile'}",
            "--virtual-time-budget=8000",
            "--dump-dom",
            (work / "graph.html").resolve().as_uri(),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    dom = result.stdout
    assert "<canvas" in dom, f"no canvas rendered; stderr tail: {result.stderr[-300:]}"
    chips = len(re.findall(r'class="legend-chip"', dom))
    assert chips >= 13, f"expected at least 13 legend chips, found {chips}"
    assert re.search(r'<button[^>]*aria-checked="true"[^>]*data-mode="cluster"', dom) or re.search(
        r'<button[^>]*data-mode="cluster"[^>]*aria-checked="true"', dom
    ), "Topic cluster should be the checked grouping mode"


@pytest.mark.parametrize(
    "content",
    [
        b"entity_types: [unclosed\n",  # yaml.YAMLError
        b"- just\n- a list\n",  # valid YAML, not a mapping
        b"\xff\xfe\x00bad utf-8",  # UnicodeDecodeError (ValueError)
    ],
)
def test_malformed_domain_yaml_does_not_crash_consumers(monkeypatch, tmp_path, content):
    """WR-04: both schema consumers tolerate the same malformed-schema failures."""
    from core import domain_resolver
    from examples.workbench import server

    domains = tmp_path / "domains"
    (domains / "broken").mkdir(parents=True)
    (domains / "broken" / "domain.yaml").write_bytes(content)
    monkeypatch.setattr(domain_resolver, "DOMAINS_DIR", domains)

    assert domain_resolver.load_domain_schema("broken") is None
    assert domain_resolver.load_domain_schema(None) is None
    assert domain_resolver.load_domain_schema("missing") is None
    assert server._load_domain_schema("broken") is None

    out = tmp_path / "out"
    out.mkdir()
    _write_graph(out, ["COMPOUND"])
    display = run_sift._resolved_entity_display(out, "broken", {})
    assert set(display) == {"COMPOUND"}
