"""Tests for the regex ES-module bundler in ``examples.workbench.static_export``.

The bundler must either bundle an import/export form correctly or raise with
the file and line; it must never drop source lines silently.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from examples.workbench.static_export import STATIC_DIR, bundle_modules

pytestmark = pytest.mark.unit

DEP = "export function a() { return 1; }\nexport const b = 2;\n"


def _bundle(tmp_path: Path, entry_source: str, dep: str = DEP) -> str:
    (tmp_path / "entry.js").write_text(entry_source, encoding="utf-8")
    (tmp_path / "a.js").write_text(dep, encoding="utf-8")
    (tmp_path / "side.js").write_text("const side = 1;\n", encoding="utf-8")
    return bundle_modules(tmp_path, entry="entry.js")


@pytest.mark.parametrize(
    "statement",
    [
        "import './side.js';",
        'import "./side.js";',
        "import { a as b2 } from './a.js';",
        "import * as G from './a.js';",
        "import a from './a.js';",
        "import a, { b } from './a.js';",
        "import { a } from 'vis-network';",
        "import { a } from '../a.js';",
        "import { a } from './a.mjs';",
        "export default function main() {}",
        "export * from './a.js';",
        "export { a } from './a.js';",
        "export { keep as renamed };",
        "    import('./a.js');",
    ],
)
def test_unsupported_form_raises_with_file_and_line(tmp_path, statement):
    source = f"const keep = 1;\n{statement}\nfunction important() {{}}\n"
    with pytest.raises(ValueError, match=r"entry\.js:2"):
        _bundle(tmp_path, source)


def test_side_effect_import_before_named_import_never_drops_lines(tmp_path):
    # The old lazy regex ran from the side-effect import to the next
    # `from './x.js';`, deleting every line in between.
    source = (
        "import './side.js';\n"
        "const keep = 1;\n"
        "function important() {}\n"
        "import { a } from './a.js';\n"
        "important(a, keep);\n"
    )
    with pytest.raises(ValueError, match=r"entry\.js:1"):
        _bundle(tmp_path, source)


def test_named_imports_single_double_quoted_and_multiline_bundle(tmp_path):
    source = (
        "import {\n    a,\n} from './a.js';\n"
        'import { b } from "./a.js";\n'
        "const keep = a() + b;\n"
        "export { keep };\n"
        "export async function run() { return keep; }\n"
        "export let counter = 0;\n"
        "export var legacy = 1;\n"
        "export class Box {}\n"
    )
    bundle = _bundle(tmp_path, source)
    assert bundle.index("// ---- a.js ----") < bundle.index("// ---- entry.js ----")
    for line in (
        "function a() { return 1; }",
        "const b = 2;",
        "const keep = a() + b;",
        "async function run() { return keep; }",
        "let counter = 0;",
        "var legacy = 1;",
        "class Box {}",
    ):
        assert line in bundle, line
    assert "import" not in bundle and "export" not in bundle, bundle


def test_workbench_static_bundle_still_builds():
    bundle = bundle_modules(STATIC_DIR, entry="static_view.js")
    for name in (
        "display.js",
        "graph_style.js",
        "grouping.js",
        "hovercard.js",
        "sidebar.js",
        "graph.js",
        "static_view.js",
    ):
        assert f"// ---- {name} ----" in bundle, name


@pytest.mark.parametrize(
    "dep,entry_decl",
    [
        ("export function a() {}\nfunction byId(x) { return x; }\n", "function byId(y) {}"),
        ("export function a() {}\nconst DEBOUNCE_MS = 100;\n", "let DEBOUNCE_MS = 5;"),
        ("export function a() {}\nexport class Box {}\n", "async function Box() {}"),
    ],
)
def test_duplicate_top_level_names_across_modules_raise_with_both_locations(
    tmp_path, dep, entry_decl
):
    source = f"import {{ a }} from './a.js';\n\n{entry_decl}\n"
    with pytest.raises(ValueError, match=r"declared in a\.js:2 and entry\.js:3"):
        _bundle(tmp_path, source, dep=dep)


def test_nested_declarations_with_same_name_are_allowed(tmp_path):
    source = (
        "import { a } from './a.js';\n"
        "function outer() {\n    const b = 3;\n    function a2() {}\n    return b + a2;\n}\n"
    )
    assert "function outer()" in _bundle(tmp_path, source)


def test_top_level_destructuring_is_rejected(tmp_path):
    source = "import { a } from './a.js';\nconst { x, y } = a();\n"
    with pytest.raises(ValueError, match=r"entry\.js:2"):
        _bundle(tmp_path, source)


def test_bundle_neutralises_html_comment_open_and_script_close(tmp_path):
    # `<!--` followed by `<script` would switch the HTML parser into the
    # double-escaped state, where `</script>` no longer ends the element.
    source = "export const s = '<!-- <script>x</script>';\n"
    bundle = _bundle(tmp_path, source)
    assert "<!--" not in bundle and "</script" not in bundle, bundle
    assert "<\\!-- <script>x<\\/script>" in bundle, bundle


def test_inline_script_helper_covers_vis_and_bundle():
    from examples.workbench import static_export

    assert static_export.script_safe("a<!--b</SCRIPT>") == "a<\\!--b<\\/SCRIPT>"
    page = static_export.build_static_html(
        title="t", payload={}, stats=None, generated="2026-01-01"
    )
    scripts = re.findall(r"<script[^>]*>(.*?)</script>", page, re.S)
    assert scripts and all("<!--" not in body for body in scripts)
