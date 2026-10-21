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
    # Our blocks open at line start; vis-network also holds the text "<script>"
    # inside a JS string literal, which is not a tag.
    assert page.count("</script") == len(re.findall(r"^<script\b", page, re.M)), (
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


# ---------------------------------------------------------------------------
# Subset views, notice, metadata line and CLI errors
# ---------------------------------------------------------------------------

import sys  # noqa: E402

NOTICE_RE = re.compile(r'<p class="static-notice" role="note">(.*?)</p>', re.DOTALL)
META_RE = re.compile(r'<p class="static-meta">(.*?)</p>', re.DOTALL)
FILTER_HINT = "Run /epistract:view without filters to see the whole graph."


def _text(fragment: str) -> str:
    return html_lib.unescape(re.sub(r"<[^>]+>", "", fragment))


def _subset_view(output_dir: Path, **kwargs) -> str:
    run_sift.cmd_view(str(output_dir), open_browser=False, **kwargs)
    return (output_dir / "graph.html").read_text(encoding="utf-8")


def _cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "core/run_sift.py", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_neighborhood_page_has_notice_and_consistent_payloads(tmp_path):
    work = _glp1_copy(tmp_path)
    page = _subset_view(work, neighborhood="semaglutide")
    notices = NOTICE_RE.findall(page)
    assert len(notices) == 1
    assert _text(notices[0]) == f"Showing 120 of 278 nodes around semaglutide. {FILTER_HINT}"
    island = _island(page)
    graph = island["/api/graph"]
    kept = {n["id"] for n in graph["nodes"]}
    assert len(kept) == 120
    for e in graph["edges"]:
        assert e["source"] in kept and e["target"] in kept
    assert set(island["/api/graph/groups"]["modes"]["cluster"]["assignment"]) <= kept
    sub_types = island["/api/graph/entity-types"]["types"]

    full_work = tmp_path / "full"
    full_work.mkdir()
    for name in GLP1_FILES:
        shutil.copy2(GLP1 / name, full_work / name)
    full_types = _island(_subset_view(full_work))["/api/graph/entity-types"]["types"]
    full_color = {t["type"]: t["color"] for t in full_types}
    assert sub_types
    for t in sub_types:
        assert t["color"] == full_color[t["type"]], f"{t['type']} recoloured in the subset"


def test_neighborhood_keeps_sources_for_show_sources(tmp_path):
    work = _glp1_copy(tmp_path)
    island = _island(_subset_view(work, neighborhood="semaglutide"))
    types = {t["type"]: t for t in island["/api/graph/entity-types"]["types"]}
    assert any(t.get("is_source") for t in types.values()), "kept sources must be present"


def test_top_page_notice_copy(tmp_path):
    work = _glp1_copy(tmp_path)
    page = _subset_view(work, top_n=10)
    (notice,) = NOTICE_RE.findall(page)
    shown = len(_island(page)["/api/graph"]["nodes"])
    # The count itself is pinned against an independent computation in
    # test_graph_payloads; here the notice must agree with the embedded data.
    assert 10 < shown < 278
    assert _text(notice) == (
        f"Showing {shown} of 278 nodes: the 10 most connected entities and their neighbors. "
        + FILTER_HINT
    )


def test_neighborhood_depth_two_notice_copy(tmp_path):
    work = _glp1_copy(tmp_path)
    page = _subset_view(work, neighborhood="semaglutide", depth=2)
    (notice,) = NOTICE_RE.findall(page)
    assert "within 2 hops of semaglutide." in _text(notice)


def test_full_graph_has_metadata_line_and_no_notice(tmp_path):
    work = _glp1_copy(tmp_path)
    page = _subset_view(work)
    assert not NOTICE_RE.search(page)
    (meta,) = META_RE.findall(page)
    text = _text(meta)
    assert re.fullmatch(
        r"218 entities · \d+ relations · 60 sources hidden · Generated \d{4}-\d{2}-\d{2}", text
    ), text
    graph = _island(page)["/api/graph"]
    from core.graph_display import entity_type_key, is_source_edge, resolve_display

    display = resolve_display(
        None, {entity_type_key(n.get("entity_type")) for n in graph["nodes"]}, None
    )
    sources = {
        n["id"] for n in graph["nodes"] if display["types"][entity_type_key(n["entity_type"])]["is_source"]
    }
    expected = sum(1 for e in graph["edges"] if not is_source_edge(e, sources, display["relations"]))
    assert f" {expected:,} relations" in text or f" {expected} relations" in text


def test_graph_without_sources_omits_sources_hidden(tmp_path):
    _write_graph(tmp_path, ["COMPOUND", "DISEASE"])
    page = _subset_view(tmp_path)
    (meta,) = META_RE.findall(page)
    assert "sources hidden" not in _text(meta)
    assert _text(meta).startswith("2 entities · 0 relations · Generated ")


def test_hostile_neighborhood_name_is_escaped_and_capped(tmp_path):
    hostile = "<img src=x onerror=alert(1)>" + "A" * 60
    nodes = [
        {"id": "n0", "name": hostile, "entity_type": "COMPOUND"},
        {"id": "n1", "name": "Other", "entity_type": "DISEASE"},
        {"id": "n2", "name": "Third", "entity_type": "DISEASE"},
    ]
    links = [
        {"source": "n0", "target": "n1", "relation_type": "TREATS"},
        {"source": "n1", "target": "n2", "relation_type": "TREATS"},
    ]
    (tmp_path / "graph_data.json").write_text(
        json.dumps({"metadata": {}, "nodes": nodes, "links": links}), encoding="utf-8"
    )
    page = _subset_view(tmp_path, neighborhood="n0")
    (notice,) = NOTICE_RE.findall(page)
    assert "<img" not in notice
    assert "&lt;img" in notice
    capped = hostile[:39] + "…"
    assert html_lib.escape(capped) in notice
    assert f'title="{html_lib.escape(hostile, quote=True)}"' in notice


def test_cli_unknown_neighborhood_exits_1_without_writing(tmp_path):
    work = _glp1_copy(tmp_path)
    proc = _cli("view", str(work), "--neighborhood", "no-such-entity", "--no-open")
    assert proc.returncode == 1
    assert proc.stderr.strip().endswith("Pass the exact entity id or name.")
    assert "Traceback" not in proc.stderr
    assert not (work / "graph.html").exists()


def test_cli_top_and_depth_succeed(tmp_path):
    work = _glp1_copy(tmp_path)
    assert _cli("view", str(work), "--top", "10", "--no-open").returncode == 0
    assert _cli(
        "view", str(work), "--neighborhood", "semaglutide", "--depth", "2", "--no-open"
    ).returncode == 0


@pytest.mark.parametrize("flag", ["--top", "--depth"])
def test_cli_non_integer_flag_reports_integer_error(tmp_path, flag):
    work = _glp1_copy(tmp_path)
    args = ["view", str(work), "--neighborhood", "semaglutide", flag, "abc", "--no-open"]
    proc = _cli(*args)
    assert proc.returncode == 1
    assert f"Error: {flag} expects an integer" in proc.stderr
    assert "Pass the exact entity id" not in proc.stderr
    assert "Traceback" not in proc.stderr
    assert not (work / "graph.html").exists()


def test_workbench_index_does_not_load_standalone_glue():
    index = (ROOT / "examples" / "workbench" / "static" / "index.html").read_text(encoding="utf-8")
    assert "static_view" not in index


def test_skip_link_is_first_element_in_body(glp1_page):
    _work, page = glp1_page
    body = page.split("<body", 1)[1].split(">", 1)[1].lstrip()
    assert body.startswith('<a class="static-skip" href="#graph-container">Skip to graph</a>'), body[:120]


def test_cli_corrupt_graph_json_reports_read_error_not_entity_hint(tmp_path):
    (tmp_path / "graph_data.json").write_text("{bad", encoding="utf-8")
    proc = _cli("view", str(tmp_path), "--no-open")
    assert proc.returncode == 1
    assert "Error: could not read the graph files in" in proc.stderr, proc.stderr
    assert "Pass the exact entity id" not in proc.stderr, proc.stderr
    assert "Traceback" not in proc.stderr
    assert not (tmp_path / "graph.html").exists()


def test_cli_bundler_error_reports_build_error_not_entity_hint(tmp_path, monkeypatch, capsys):
    import runpy

    from examples.workbench import static_export

    def broken(*_a, **_k):
        raise ValueError("static bundle: import cycle through x.js")

    _write_graph(tmp_path, ["COMPOUND"])
    monkeypatch.setattr(static_export, "bundle_modules", broken)
    monkeypatch.setattr(sys, "argv", ["run_sift.py", "view", str(tmp_path), "--no-open"])
    with pytest.raises(SystemExit) as exc:
        runpy.run_path(str(ROOT / "core" / "run_sift.py"), run_name="__main__")
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "Error: could not build graph.html: static bundle: import cycle" in err, err
    assert "Pass the exact entity id" not in err, err
    assert not (tmp_path / "graph.html").exists()


@pytest.mark.parametrize(
    "flag,value", [("--top", "0"), ("--top", "-1"), ("--depth", "0"), ("--depth", "-3")]
)
def test_cli_non_positive_top_or_depth_is_rejected(tmp_path, flag, value):
    _write_graph(tmp_path, ["COMPOUND", "DISEASE"])
    args = ["view", str(tmp_path), "--neighborhood", "n0", flag, value, "--no-open"]
    proc = _cli(*args)
    assert proc.returncode == 1
    assert f"Error: {flag} must be a positive integer" in proc.stderr, proc.stderr
    assert "Traceback" not in proc.stderr
    assert not (tmp_path / "graph.html").exists()


def test_graph_html_is_written_atomically(tmp_path, monkeypatch):
    from examples.workbench import static_export

    _write_graph(tmp_path, ["COMPOUND"])
    dest = tmp_path / "graph.html"
    dest.write_text("OLD PAGE", encoding="utf-8")

    def interrupted(self, target):
        raise OSError("disk full")

    monkeypatch.setattr(Path, "replace", interrupted)
    with pytest.raises(OSError, match="disk full"):
        static_export.write_static_graph(tmp_path)
    assert dest.read_text(encoding="utf-8") == "OLD PAGE", "old page must survive a failed write"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["graph.html", "graph_data.json"]

    monkeypatch.undo()
    static_export.write_static_graph(tmp_path)
    assert dest.read_text(encoding="utf-8").startswith("<!DOCTYPE html>")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["graph.html", "graph_data.json"]


def test_cli_warns_on_unknown_view_arguments(tmp_path):
    _write_graph(tmp_path, ["COMPOUND", "DISEASE"])
    proc = _cli("view", str(tmp_path), "--nieghborhood", "n0", "--top", "1", "--no-open")
    assert proc.returncode == 0, proc.stderr
    assert "Warning: ignoring unknown view argument(s): --nieghborhood n0" in proc.stderr, (
        proc.stderr
    )
    assert (tmp_path / "graph.html").exists()
    clean = _cli("view", str(tmp_path), "--neighborhood", "n0", "--depth", "2", "--no-open")
    assert clean.returncode == 0 and "unknown view argument" not in clean.stderr
