"""Write a self-contained graph.html that runs the workbench graph modules offline.

The page inlines the vendored vis-network, the workbench stylesheet, the graph
panel markup sliced from ``static/index.html``, the four ``/api/...`` payloads
as a JSON data island, a small ``fetch`` shim that answers from that island, and
the unmodified workbench ES modules bundled into one inline module script. The
workbench and the static page therefore share one renderer.
"""

from __future__ import annotations

import html
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from core.domain_resolver import load_domain_schema
from core.graph_display import entity_type_key, is_source_edge, resolve_display
from core.graph_groups import build_groups
from core.graph_payloads import (
    claims_payload,
    entity_types_payload,
    json_for_script,
    subset_graph,
)
from examples.workbench.data_loader import WorkbenchData
from examples.workbench.template_loader import load_template, resolve_domain

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

STATIC_DIR = Path(__file__).parent / "static"
PANEL_START = "<!-- graph-panel:start -->"
PANEL_END = "<!-- graph-panel:end -->"
FALLBACK_TITLE = "Knowledge graph"
NAME_CAP = 40
FILTER_HINT = "Run /epistract:view without filters to see the whole graph."

# Module syntax the bundler understands. Every line that starts with `import` or
# `export` (after optional indentation) must match one of these at column 0, or
# bundling fails with the file and line: nothing is ever dropped silently.
# `import { a, b } from './x.js';` (braces may span lines), either quote style.
NAMED_IMPORT = re.compile(
    r"import[ \t]*\{([^}]*)\}[ \t]*from[ \t]*(['\"])(\./[^'\"\n]+\.js)\2[ \t]*;?[ \t]*(?:\n|\Z)"
)
# `export { a, b };` with nothing after it on the line (no `from`).
EXPORT_LIST = re.compile(r"export[ \t]*\{([^}]*)\}[ \t]*;?[ \t]*(?:\n|\Z)")
EXPORT_DECL = re.compile(
    r"export[ \t]+(async[ \t]+function\*?|function\*?|const|let|var|class)(?![\w$])"
)
MODULE_STMT = re.compile(r"^[ \t]*(?:import|export)(?![\w$])", re.M)
IDENT = re.compile(r"[A-Za-z_$][\w$]*")
# A top-level declaration: column 0 (the modules indent nested code), optionally
# exported. Group 1 is the declared name, or None for destructuring.
TOP_DECL = re.compile(
    r"^(?:export[ \t]+)?(?:async[ \t]+function\*?|function\*?|const|let|var|class)"
    r"[ \t]*(?:([A-Za-z_$][\w$]*)|[\[{])",
    re.M,
)
SCRIPT_CLOSE = re.compile(r"</(script)", re.I)
STYLE_CLOSE = re.compile(r"</(style)", re.I)

# Answers the workbench's fetch() calls from the embedded data island. A literal
# string with no interpolation: graph data only ever reaches the page through
# the JSON island, never through script source.
FETCH_SHIM = """(function () {
  var data = {};
  try {
    data = JSON.parse(document.getElementById('epistract-data').textContent);
  } catch (e) {
    data = {};
  }
  var has = Object.prototype.hasOwnProperty;
  // The embedded URL keys, so the page can tell a missing payload from a damaged
  // one without reading the data itself. Empty when the island cannot be parsed.
  window.__epistractKeys = Object.keys(data);
  window.fetch = function (url) {
    var key = String(url);
    if (has.call(data, key)) {
      return Promise.resolve({ ok: true, status: 200, statusText: 'OK',
        json: function () { return Promise.resolve(data[key]); } });
    }
    return Promise.resolve({ ok: false, status: 404, statusText: 'Not embedded',
      json: function () { return Promise.resolve({}); } });
  };
})();"""

# Classic script that runs before the module. It owns the failure card (so the
# copy lives in one place) and shows it when the module script cannot run. Literal
# text, createElement and textContent only; nothing from the data reaches it.
FAILURE_FALLBACK = """(function () {
  var shown = false;
  window.__epistractReady = false;
  window.__epistractShowCard = function (body) {
    if (shown) return;
    shown = true;
    var main = document.getElementById('static-main');
    if (!main) return;
    var card = document.createElement('div');
    card.className = 'static-card';
    card.setAttribute('role', 'alert');
    var heading = document.createElement('h2');
    heading.textContent = "This graph couldn't be loaded";
    var text = document.createElement('p');
    text.textContent = body;
    card.appendChild(heading);
    card.appendChild(text);
    main.replaceChildren(card);
  };
  function onFailure() {
    if (window.__epistractReady === true) return;
    window.__epistractShowCard(
      'Your browser could not run the graph script. Try a current version of Chrome, ' +
      'Edge, Firefox or Safari, or regenerate the file with /epistract:view.');
  }
  window.addEventListener('error', onFailure);
  window.addEventListener('unhandledrejection', onFailure);
})();"""

NOSCRIPT_HEAD = "<noscript><style>#side-panel{display:none}</style></noscript>\n"
NOSCRIPT_CARD = (
    "<noscript>"
    '<div class="static-card">'
    "<h2>JavaScript is required</h2>"
    "<p>This graph viewer draws the graph in your browser. Turn on JavaScript for "
    "this file and reload. Nothing is sent over the network.</p>"
    "</div>"
    "</noscript>\n"
)

SKIP_LINK = '<a class="static-skip" href="#graph-container">Skip to graph</a>\n'


# ---------------------------------------------------------------------------
# Module bundling
# ---------------------------------------------------------------------------


def _plain_names(specifiers: str) -> bool:
    """True when ``specifiers`` is a comma list of bare identifiers (no ``as``)."""
    names = [part.strip() for part in specifiers.split(",")]
    if names and names[-1] == "":
        names.pop()  # trailing comma
    return bool(names) and all(IDENT.fullmatch(n) for n in names)


def _parse_module(source: str, name: str) -> tuple[str, list[str]]:
    """Strip module syntax from one ES module and list its relative imports.

    Supported: named imports of relative ``./x.js`` modules, ``export { a, b };``
    and ``export`` before ``function``/``async function``/``const``/``let``/
    ``var``/``class``. Any other statement that starts with ``import`` or
    ``export`` raises, so code is never removed or left undefined silently.

    Args:
        source: Module source text.
        name: File name used in error messages.

    Returns:
        ``(body, deps)``: the source with imports and export keywords removed,
        and the imported module names (without ``./``) in source order.

    Raises:
        ValueError: ``static bundle: <name>:<line>: ...`` for unsupported syntax.
    """
    out: list[str] = []
    deps: list[str] = []
    pos = 0
    for stmt in MODULE_STMT.finditer(source):
        start = stmt.start()
        if start < pos:
            continue  # inside a statement already consumed (multi-line import)

        def fail(why: str, start: int = start) -> None:
            line_no = source.count("\n", 0, start) + 1
            line = source[start:].split("\n", 1)[0].strip()
            raise ValueError(f"static bundle: {name}:{line_no}: {why}: {line!r}")

        if source[start] in " \t":
            fail("indented import/export (or dynamic import()) is not supported")
        out.append(source[pos:start])
        if source.startswith("import", start):
            m = NAMED_IMPORT.match(source, start)
            if not m:
                fail("only `import { a, b } from './x.js';` is supported")
            if not _plain_names(m.group(1)):
                fail("aliased (`as`) or empty import lists are not supported")
            deps.append(m.group(3).removeprefix("./"))
            pos = m.end()
            continue
        m = EXPORT_LIST.match(source, start)
        if m:
            if not _plain_names(m.group(1)):
                fail("aliased (`as`) or empty export lists are not supported")
            pos = m.end()
            continue
        m = EXPORT_DECL.match(source, start)
        if not m:
            fail("only `export { a };` and exported declarations are supported")
        out.append(m.group(1))
        pos = m.end()
    out.append(source[pos:])
    return "".join(out), deps


def _top_level_names(source: str, name: str) -> list[tuple[str, int]]:
    """Return ``(identifier, line)`` for each top-level declaration in a module.

    Raises:
        ValueError: On a top-level destructuring declaration, whose names this
            check cannot see.
    """
    found = []
    for m in TOP_DECL.finditer(source):
        line_no = source.count("\n", 0, m.start()) + 1
        if m.group(1) is None:
            raise ValueError(
                f"static bundle: {name}:{line_no}: top-level destructuring is not "
                "supported (names cannot be checked for collisions)"
            )
        found.append((m.group(1), line_no))
    return found


def bundle_modules(static_dir: Path, entry: str = "graph.js") -> str:
    """Concatenate ``entry`` and its relative imports into one module body.

    Modules are emitted dependencies first, derived from the import statements
    themselves. Import/export forms the bundler does not support raise with the
    file and line (see ``_parse_module``), so a new import in a module cannot
    silently break the bundle.

    Args:
        static_dir: Directory holding the workbench ``*.js`` modules.
        entry: Module whose import graph is bundled.

    Returns:
        JavaScript source with imports and ``export`` keywords removed and
        ``</script`` escaped so it can sit inside an inline module script.

    Raises:
        ValueError: On an import cycle, import/export syntax this bundler
            does not understand, or a top-level name declared in two modules.
    """
    order: list[str] = []
    visiting: list[str] = []

    def visit(name: str) -> None:
        if name in order:
            return
        if name in visiting:
            raise ValueError(f"static bundle: import cycle through {name}")
        visiting.append(name)
        source = (static_dir / name).read_text(encoding="utf-8")
        body, deps = _parse_module(source, name)
        bodies[name] = body
        names[name] = _top_level_names(source, name)
        for dep in deps:
            visit(dep)
        visiting.pop()
        order.append(name)

    bodies: dict[str, str] = {}
    names: dict[str, list[tuple[str, int]]] = {}
    visit(entry)
    # All modules share one scope in the bundle, so a name declared twice would
    # be a SyntaxError at page load; fail here with both locations instead.
    declared: dict[str, str] = {}
    for module in order:
        for ident, line_no in names[module]:
            where = f"{module}:{line_no}"
            if ident in declared:
                raise ValueError(
                    f"static bundle: {ident!r} declared in {declared[ident]} and {where}"
                )
            declared[ident] = where
    bundle = "\n".join(f"// ---- {name} ----\n" + bodies[name] for name in order)
    return SCRIPT_CLOSE.sub(r"<\\/\1", bundle)


def slice_graph_panel(index_html: str) -> str:
    """Return the graph panel markup between the panel marker comments.

    Raises:
        ValueError: When a marker comment is missing from ``index_html``.
    """
    start = index_html.find(PANEL_START)
    if start < 0:
        raise ValueError(f"index.html is missing the marker {PANEL_START}")
    end = index_html.find(PANEL_END, start)
    if end < 0:
        raise ValueError(f"index.html is missing the marker {PANEL_END}")
    return index_html[start + len(PANEL_START) : end]


# ---------------------------------------------------------------------------
# Data assembly
# ---------------------------------------------------------------------------


def build_view_data(
    output_dir: Path,
    *,
    neighborhood: str | None = None,
    top_n: int | None = None,
    depth: int = 1,
) -> dict:
    """Assemble the four payloads the graph modules fetch, from ``output_dir``.

    Mirrors ``examples.workbench.server.create_app`` so the static page and the
    workbench resolve domain, display and groups identically. Display (colors,
    shapes) is resolved over the full graph; a subset filter is applied after,
    so a subset keeps the workbench colors, and groups are built on the subset.

    Args:
        output_dir: Directory holding graph_data.json.
        neighborhood: Entity id or name to center a subset on.
        top_n: Keep the N best-connected entities and their neighbors.
        depth: Hop radius for ``neighborhood``.

    Returns:
        ``{"title", "payload": {url: obj}, "stats", "subset"}``; ``subset`` is
        None for the full graph.

    Raises:
        EntityLookupError: When ``neighborhood`` matches no node or several nodes.
        json.JSONDecodeError: When an output JSON file is corrupt.
    """
    output_dir = Path(output_dir)
    resolved_domain, _source = resolve_domain(output_dir, None)
    template = load_template(resolved_domain)
    data = WorkbenchData(output_dir)
    nodes = data.get_nodes()
    edges = data.get_edges()

    observed_types = {entity_type_key(n.get("entity_type")) for n in nodes}
    display = resolve_display(
        load_domain_schema(resolved_domain),
        observed_types,
        template.get("entity_colors"),
    )
    for warning in display["warnings"]:
        print(f"Warning: display: {warning}", file=sys.stderr)

    nodes, edges, subset = subset_graph(
        nodes, edges, display, neighborhood=neighborhood, top_n=top_n, depth=depth
    )

    source_ids = {
        n.get("id")
        for n in nodes
        if display["types"].get(entity_type_key(n.get("entity_type")), {}).get("is_source")
    }
    relations = display["relations"]
    stats = {
        "entities": len(nodes) - len(source_ids),
        "relations": sum(1 for e in edges if not is_source_edge(e, source_ids, relations)),
        "sources": len(source_ids),
    }
    payload = {
        "/api/graph": {"nodes": nodes, "edges": edges},
        "/api/graph/claims": claims_payload(data.claims_layer),
        "/api/graph/groups": build_groups(nodes, edges, data.communities, display),
        "/api/graph/entity-types": entity_types_payload(nodes, display),
    }
    return {
        "title": template.get("title") or FALLBACK_TITLE,
        "payload": payload,
        "stats": stats,
        "subset": subset,
    }


# ---------------------------------------------------------------------------
# HTML assembly
# ---------------------------------------------------------------------------


def _inline_css() -> str:
    css = (STATIC_DIR / "style.css").read_text(encoding="utf-8")
    css += "\n" + (STATIC_DIR / "static_view.css").read_text(encoding="utf-8")
    return STYLE_CLOSE.sub(r"<\\/\1", css)


def _num(value: int) -> str:
    return f'<span class="static-num">{int(value):,}</span>'


def _meta_line(stats: dict | None, generated: str) -> str:
    """Return the metadata paragraph (counts are ints, the date is escaped)."""
    parts = []
    if stats:
        parts.append(f"{_num(stats['entities'])} entities")
        parts.append(f"{_num(stats['relations'])} relations")
        if int(stats["sources"]) > 0:
            parts.append(f"{_num(stats['sources'])} sources hidden")
    parts.append(f"Generated {html.escape(generated, quote=True)}")
    return f'<p class="static-meta">{" · ".join(parts)}</p>'


def _notice(subset: dict | None) -> str:
    """Return the subset notice paragraph, or "" for a full-graph page."""
    if not subset or subset["shown"] >= subset["total"]:
        return ""
    counts = f"Showing {_num(subset['shown'])} of {_num(subset['total'])} nodes"
    if subset["mode"] == "neighborhood":
        full = str(subset["name"])
        shown_name = full if len(full) <= NAME_CAP else full[: NAME_CAP - 1] + "…"
        name = (
            f'<strong title="{html.escape(full, quote=True)}">'
            f"{html.escape(shown_name, quote=False)}</strong>"
        )
        depth = int(subset["depth"])
        where = f"around {name}" if depth <= 1 else f"within {_num(depth)} hops of {name}"
        lead = f"{counts} {where}."
    else:
        lead = f"{counts}: the {_num(subset['top_n'])} most connected entities and their neighbors."
    return (
        f'<p class="static-notice" role="note">{lead}'
        f' <span class="static-notice__hint">{html.escape(FILTER_HINT)}</span></p>\n'
    )


def build_static_html(
    *,
    title: str,
    payload: dict,
    stats: dict | None = None,
    generated: str | None = None,
    subset: dict | None = None,
) -> str:
    """Return the complete self-contained page.

    Args:
        title: Page title (escaped before use).
        payload: ``{url: object}`` for the four ``/api/...`` URLs.
        stats: Optional ``{"entities", "relations", "sources"}`` for the header.
        generated: ``YYYY-MM-DD`` date; defaults to today (UTC).
        subset: ``info`` from ``subset_graph``; renders the notice when it
            shows fewer nodes than the full graph.

    Returns:
        The HTML document text.
    """
    generated = generated or datetime.now(timezone.utc).date().isoformat()
    safe_title = html.escape(title, quote=True)
    index_html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    panel = slice_graph_panel(index_html)
    vis = SCRIPT_CLOSE.sub(
        r"<\\/\1", (STATIC_DIR / "vis-network.min.js").read_text(encoding="utf-8")
    )
    bundle = bundle_modules(STATIC_DIR, entry="static_view.js")

    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{safe_title} - Epistract</title>\n"
        f"<style>\n{_inline_css()}\n</style>\n"
        f"{NOSCRIPT_HEAD}"
        "</head>\n"
        '<body class="static-view">\n'
        f"{SKIP_LINK}"
        '<header class="static-header">'
        f'<h1 title="{safe_title}">{safe_title}</h1>'
        f"{_meta_line(stats, generated)}</header>\n"
        f"{_notice(subset)}"
        '<main id="static-main" class="static-main">\n'
        f'<aside class="side-panel open" id="side-panel">{panel}</aside>\n'
        f"{NOSCRIPT_CARD}"
        "</main>\n"
        f'<script type="application/json" id="epistract-data">{json_for_script(payload)}</script>\n'
        f"<script>\n{FETCH_SHIM}\n</script>\n"
        f"<script>\n{FAILURE_FALLBACK}\n</script>\n"
        f"<script>\n{vis}\n</script>\n"
        f'<script type="module">\n{bundle}\n</script>\n'
        "</body>\n"
        "</html>\n"
    )


def write_static_graph(
    output_dir: Path,
    *,
    neighborhood: str | None = None,
    top_n: int | None = None,
    depth: int = 1,
) -> Path:
    """Write ``output_dir/graph.html`` and return its path.

    Raises:
        FileNotFoundError: When ``graph_data.json`` is missing from ``output_dir``.
        EntityLookupError: When ``neighborhood`` is unknown or ambiguous;
            nothing is written in that case.
        ValueError: When the page cannot be assembled (bundler, panel markers).
    """
    output_dir = Path(output_dir)
    if not (output_dir / "graph_data.json").is_file():
        raise FileNotFoundError(f"No graph found: {output_dir / 'graph_data.json'} does not exist")
    view = build_view_data(output_dir, neighborhood=neighborhood, top_n=top_n, depth=depth)
    page = build_static_html(
        title=view["title"],
        payload=view["payload"],
        stats=view["stats"],
        subset=view["subset"],
    )
    dest = output_dir / "graph.html"
    dest.write_text(page, encoding="utf-8")
    return dest
