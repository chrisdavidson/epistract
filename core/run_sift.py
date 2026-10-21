#!/usr/bin/env python3
"""sift-kg Python API wrapper.

Usage:
    python run_sift.py --list-domains
    python run_sift.py build <output_dir> [--domain <name>]
    python run_sift.py view <output_dir> [--neighborhood <entity>] [--top <n>] [--no-open]
    python run_sift.py export <output_dir> <format>
    python run_sift.py info <output_dir>
    python run_sift.py search <output_dir> <query> [--type TYPE]

The --domain flag accepts a domain name (e.g. "drug-discovery", "contract"),
not a file path. Use --list-domains to see available domains.
"""

import json
import sys
import webbrowser
from pathlib import Path

# Allow running as a plain script (python3 core/run_sift.py ...) in addition to
# module import. commands/ingest.md invokes this by absolute path, so the package
# root must be on sys.path for the `core.domain_resolver` import below — running a
# script by path puts core/ on sys.path[0], not the project root. The insert in
# cmd_dashboard() is far too late: this import runs at module load.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from core.domain_resolver import (  # noqa: E402
    DOMAINS_DIR,
    list_domains,
    load_domain_schema,
    resolve_domain,
)
from core.graph_payloads import json_for_script  # noqa: E402


def resolve_domain_arg(value: str) -> str:
    """Shim for --domain CLI arg: accepts a name OR a path to domains/<name>/domain.yaml.

    FIDL-08 D-07, D-08:
      - Bare name (no '/' and not ending in '.yaml') → return unchanged. The
        bare-name branch never touches the filesystem (D-08 explicit
        non-ambiguity).
      - Path inside DOMAINS_DIR matching `<DOMAINS_DIR>/<name>/domain.yaml`
        → return `<name>`.
      - Path outside DOMAINS_DIR → print error to stderr and sys.exit(1) with
        a clear "use --domain <inferred_name>" message.
    """
    # D-08: bare-name path never touches the filesystem
    if "/" not in value and not value.endswith(".yaml"):
        return value

    path = Path(value).resolve()
    domains_root = DOMAINS_DIR.resolve()

    try:
        rel = path.relative_to(domains_root)
    except ValueError:
        # Path is outside DOMAINS_DIR — clear error
        inferred = path.parent.name if path.name == "domain.yaml" else path.stem
        print(
            f"Error: --domain expects a name registered under domains/, "
            f"not an arbitrary path. Try --domain {inferred} after registering the domain.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Path inside DOMAINS_DIR — must be <name>/domain.yaml to be valid
    parts = rel.parts
    if len(parts) >= 2 and parts[-1] == "domain.yaml":
        return parts[0]

    # Inside DOMAINS_DIR but not a valid <name>/domain.yaml location
    print(
        f"Error: --domain expects a name registered under domains/, "
        f"not an arbitrary path. Try --domain "
        f"{parts[0] if parts else 'unknown'} after registering the domain.",
        file=sys.stderr,
    )
    sys.exit(1)


def _import_sift(names: list[str]):
    """Import sift-kg components with user-friendly error on missing install."""
    try:
        import sift_kg
    except ImportError:
        print(
            "Error: sift-kg is not installed.\n"
            "Run /epistract-setup or: uv pip install sift-kg",
            file=sys.stderr,
        )
        sys.exit(1)
    return tuple(getattr(sift_kg, n) for n in names)


def _load_validation_module(validation_dir: Path):
    """Dynamically load validation/run_validation.py (FIDL-07 D-04).

    Mirrors core.label_epistemic._load_domain_epistemic — uses
    importlib.util.spec_from_file_location so the module loads regardless
    of Python's package context.

    Args:
        validation_dir: Path to the domain's validation/ directory.

    Returns:
        The loaded module, or None if ``run_validation.py`` is absent or the
        spec fails to load.
    """
    import importlib.util
    module_path = validation_dir / "run_validation.py"
    if not module_path.is_file():
        return None
    spec = importlib.util.spec_from_file_location(
        f"domains.{validation_dir.parent.name}.validation.run_validation",
        module_path,
    )
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def cmd_build(output_dir: str, domain_name: str | None = None):
    run_build, load_domain = _import_sift(["run_build", "load_domain"])

    if domain_name:
        domain_info = resolve_domain(domain_name)
        domain = load_domain(domain_path=Path(domain_info["yaml_path"]))
    else:
        domain = load_domain(domain_path=Path(__file__).parent.parent / "domains" / "drug-discovery" / "domain.yaml")
    kg = run_build(Path(output_dir), domain)

    # FIDL-06 (D-01, D-02): persist the build-time domain into graph_data.json
    # metadata so every downstream consumer (workbench, graph.html, chat system
    # prompt) has a single source of truth for "what domain is this graph?"
    # Post-process pattern rather than monkey-patching sift-kg — keeps us
    # decoupled from sift_kg.graph.knowledge_graph.save().
    graph_path = Path(output_dir) / "graph_data.json"
    if graph_path.exists():
        try:
            graph_json = json.loads(graph_path.read_text(encoding="utf-8"))
            metadata = graph_json.setdefault("metadata", {})
            metadata["domain"] = domain_name  # str or None; JSON null on None
            graph_path.write_text(
                json.dumps(graph_json, indent=2, default=str),
                encoding="utf-8",
            )
        except (OSError, ValueError, json.JSONDecodeError) as e:
            # Non-fatal: graph still usable, just missing the domain field.
            # Consumers fall back via resolve_domain's D-08 legacy path.
            print(
                f"Warning: failed to persist domain into graph_data.json: {e}",
                file=sys.stderr,
            )

    # Auto-label communities with descriptive names
    try:
        from core.label_communities import label_communities  # noqa: E402
        label_communities(Path(output_dir))
    except Exception as e:
        print(f"Warning: community labeling failed: {e}", file=sys.stderr)

    # FIDL-07 (D-04, D-08): post-build validation dispatch.
    # If the domain ships a validation/run_validation.py convention entry
    # point, call it with the output_dir and write its return dict to
    # validation_report.json. Non-fatal: exceptions write an error-status
    # report but do NOT abort cmd_build. Domains without a validation/ dir
    # (e.g. contracts) silently skip — no warning, no report.
    if domain_name:
        try:
            domain_info = resolve_domain(domain_name)
        except FileNotFoundError:
            domain_info = {"validation_dir": None}
    else:
        # Default-domain path — mirror the load_domain default above so a
        # `cmd_build <out>` (no --domain flag) still triggers drug-discovery
        # validation.
        try:
            domain_info = resolve_domain("drug-discovery")
        except FileNotFoundError:
            domain_info = {"validation_dir": None}

    validation_dir_str = domain_info.get("validation_dir")
    if validation_dir_str:
        validation_dir = Path(validation_dir_str)
        report_path = Path(output_dir) / "validation_report.json"
        try:
            val_mod = _load_validation_module(validation_dir)
            if val_mod is None or not hasattr(val_mod, "run_validation"):
                report = {
                    "status": "error",
                    "error": "run_validation callable not found",
                    "domain": domain_name,
                }
            else:
                report = val_mod.run_validation(Path(output_dir))
                if not isinstance(report, dict):
                    report = {
                        "status": "error",
                        "error": f"run_validation returned non-dict: {type(report).__name__}",
                        "domain": domain_name,
                    }
        except Exception as e:  # noqa: BLE001 — validator failures are non-fatal
            report = {
                "status": "error",
                "error": str(e),
                "domain": domain_name,
            }
            print(
                f"Warning: validation dispatch for {domain_name!r} failed: {e}",
                file=sys.stderr,
            )

        try:
            report_path.write_text(
                json.dumps(report, indent=2, default=str),
                encoding="utf-8",
            )
        except OSError as e:
            print(
                f"Warning: could not write {report_path}: {e}",
                file=sys.stderr,
            )

    print(json.dumps({
        "entities": kg.entity_count,
        "relations": kg.relation_count,
        "graph_path": str(Path(output_dir) / "graph_data.json"),
    }))


# Kept under its old name for callers and tests that import it from here.
_json_for_script = json_for_script


def _resolved_entity_display(
    output_dir: Path, resolved_domain: str | None, template: dict
) -> dict[str, dict[str, str]]:
    """Return ``{entity_type: {"color": "#rrggbb", "shape": str}}`` for every type.

    Values come from ``core.graph_display.resolve_display``: the domain schema's
    declared display, with any template ``entity_colors`` applied as overrides,
    and palette colors for observed types the schema does not declare.
    """
    from core.graph_display import resolve_display

    observed: set[str] = set()
    try:
        graph = json.loads((Path(output_dir) / "graph_data.json").read_text(encoding="utf-8"))
        for node in graph.get("nodes", []):
            entity_type = node.get("entity_type")
            if entity_type:
                observed.add(str(entity_type))
    except (OSError, ValueError, AttributeError):
        observed = set()

    schema = load_domain_schema(resolved_domain)

    display = resolve_display(schema, observed, template.get("entity_colors") or None)
    return {
        name: {"color": info["color"], "shape": info["shape"]}
        for name, info in display["types"].items()
    }


def _resolved_entity_colors(
    output_dir: Path, resolved_domain: str | None, template: dict
) -> dict[str, str]:
    """Return ``{entity_type: "#rrggbb"}`` for every type in the graph."""
    display = _resolved_entity_display(output_dir, resolved_domain, template)
    return {name: info["color"] for name, info in display.items()}


def cmd_view(
    output_dir: str,
    neighborhood: str | None = None,
    top_n: int | None = None,
    depth: int = 1,
    open_browser: bool = True,
    **_unused,
) -> None:
    """Write a self-contained graph.html and open it in the browser.

    The page runs the same graph modules as the workbench, so entity colors,
    shapes, legend, hover cards, edge categories and grouping match it.

    Args:
        output_dir: Directory holding graph_data.json (graph.html is written here).
        neighborhood: Entity to center a subset view on.
        top_n: Show only the N most connected entities and their neighbors.
        depth: Hop radius for ``neighborhood``.
        open_browser: Open the written file in the default browser.

    Raises:
        NotImplementedError: When a subset filter is requested.
        FileNotFoundError: When graph_data.json is missing.
    """
    if neighborhood is not None:
        raise NotImplementedError("view --neighborhood is not supported yet")
    if top_n is not None:
        raise NotImplementedError("view --top is not supported yet")

    # core/ must not import examples/ at module load; add the project root so the
    # lazy import works regardless of caller cwd.
    if str(_PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(_PROJECT_ROOT))
    from examples.workbench.static_export import write_static_graph

    dest = write_static_graph(Path(output_dir))
    print(f"Wrote {dest}")
    if open_browser:
        webbrowser.open(dest.resolve().as_uri())


def cmd_export(output_dir: str, fmt: str):
    (run_export,) = _import_sift(["run_export"])
    path = run_export(Path(output_dir), fmt)
    print(f"Exported: {path}")


def cmd_info(output_dir: str):
    (KnowledgeGraph,) = _import_sift(["KnowledgeGraph"])
    graph_path = Path(output_dir) / "graph_data.json"
    if not graph_path.exists():
        print(json.dumps({"error": "No graph found"}))
        return
    kg = KnowledgeGraph.load(graph_path)
    data = kg.export()
    print(json.dumps(data["metadata"], indent=2))


def cmd_search(output_dir: str, query: str, entity_type: str | None = None):
    (KnowledgeGraph,) = _import_sift(["KnowledgeGraph"])
    graph_path = Path(output_dir) / "graph_data.json"
    if not graph_path.exists():
        print(json.dumps({"error": "No graph found"}))
        return
    kg = KnowledgeGraph.load(graph_path)
    query_lower = query.lower()
    results = []
    for node_id, data in kg.graph.nodes(data=True):
        name = data.get("name", "")
        if query_lower in name.lower() or query_lower in node_id.lower():
            if entity_type and data.get("entity_type", "").upper() != entity_type.upper():
                continue
            results.append({"id": node_id, "name": name, "type": data.get("entity_type", ""), "confidence": data.get("confidence", 0)})
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    # --list-domains: print available domains and exit (no subcommand needed)
    if "--list-domains" in sys.argv:
        domains = list_domains()
        for name in domains:
            info = resolve_domain(name)
            schema = info.get("schema") or {}
            print(f"  {name:20s} v{schema.get('version', '?')}  {schema.get('description', '')}")
        sys.exit(0)

    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "build":
        domain = None
        if "--domain" in sys.argv:
            raw_domain_arg = sys.argv[sys.argv.index("--domain") + 1]
            domain = resolve_domain_arg(raw_domain_arg)  # FIDL-08 D-07: accept name or path
        cmd_build(sys.argv[2], domain)
    elif cmd == "view":
        kwargs = {}
        if "--neighborhood" in sys.argv:
            kwargs["neighborhood"] = sys.argv[sys.argv.index("--neighborhood") + 1]
        if "--top" in sys.argv:
            kwargs["top_n"] = int(sys.argv[sys.argv.index("--top") + 1])
        if "--no-open" in sys.argv:
            kwargs["open_browser"] = False
        cmd_view(sys.argv[2], **kwargs)
    elif cmd == "export":
        cmd_export(sys.argv[2], sys.argv[3])
    elif cmd == "info":
        cmd_info(sys.argv[2])
    elif cmd == "search":
        entity_type = None
        if "--type" in sys.argv:
            type_idx = sys.argv.index("--type")
            entity_type = sys.argv[type_idx + 1]
            # Remove --type and its value from argv before joining query
            args = sys.argv[3:type_idx] + sys.argv[type_idx + 2:]
        else:
            args = sys.argv[3:]
        cmd_search(sys.argv[2], " ".join(args), entity_type)
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
