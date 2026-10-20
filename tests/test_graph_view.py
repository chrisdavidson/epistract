"""Tests for the graph.html post-processing done by ``core.run_sift.cmd_view``.

``run_view`` (sift-kg) is stubbed so these tests need neither sift-kg nor a
browser: the stub writes a minimal pyvis-like page and the tests inspect the
script that ``cmd_view`` injects into it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from core import run_sift

STUB_HTML = (
    "<html><head></head><body>\n"
    "<center><h1></h1></center>\n"
    "<center><h1></h1></center>\n"
    "<div id='mynetwork'></div>\n"
    "</body></html>\n"
)

HOSTILE_TYPE = "</script><script>window.PWN=1</script>"


def _write_graph(output_dir: Path, entity_types: list[str]) -> None:
    nodes = [
        {"id": f"n{i}", "name": f"Node {i}", "entity_type": t}
        for i, t in enumerate(entity_types)
    ]
    (output_dir / "graph_data.json").write_text(
        json.dumps({"metadata": {}, "nodes": nodes, "links": []}), encoding="utf-8"
    )


def _run_cmd_view(monkeypatch, output_dir: Path) -> str:
    def fake_run_view(out_dir, **_kwargs):
        (Path(out_dir) / "graph.html").write_text(STUB_HTML, encoding="utf-8")

    monkeypatch.setattr(run_sift, "_import_sift", lambda names: (fake_run_view,))
    run_sift.cmd_view(str(output_dir))
    return (output_dir / "graph.html").read_text(encoding="utf-8")


def _overlay_script(html: str) -> str:
    match = re.search(r"<script>\n(// FIDL-06 D-05.*?)</script>", html, re.DOTALL)
    assert match, "cmd_view did not inject the color overlay script"
    return match.group(1)


def test_json_for_script_escapes_html_breakout():
    encoded = run_sift._json_for_script({HOSTILE_TYPE: "#123456", "a&b ": "#abcdef"})
    for ch in ("<", ">", "&", " ", " "):
        assert ch not in encoded, f"{ch!r} left unescaped in {encoded}"
    assert json.loads(encoded) == {HOSTILE_TYPE: "#123456", "a&b ": "#abcdef"}


def test_cmd_view_hostile_entity_type_cannot_break_out_of_script(monkeypatch, tmp_path):
    _write_graph(tmp_path, ["COMPOUND", HOSTILE_TYPE])
    html = _run_cmd_view(monkeypatch, tmp_path)

    assert "window.PWN" in html, "hostile type should still be present as escaped data"
    assert HOSTILE_TYPE not in html
    assert "<script>window.PWN=1" not in html
    # Exactly one <script> open and one </script> close: the overlay itself.
    assert html.count("<script>") == 1, html
    assert html.count("</script>") == 1, html
