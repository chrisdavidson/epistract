#!/usr/bin/env python3
"""epistract CLI — multi-project dataset management, indexing, and search.

Usage:
    python3 -m core.cli init <name> [--domain D] [--dir PATH]
    python3 -m core.cli add project <name> [--domain D] [--dir PATH]
    python3 -m core.cli add files <path>... [--project NAME]
    python3 -m core.cli add url <url>... [--project NAME]
    python3 -m core.cli index [--project NAME] [--rebuild]
    python3 -m core.cli search <query> [--project NAME] [--type T] [-k N] [--expand]
    python3 -m core.cli enhance [--project NAME] [--judge] [--resolve] [--epistemic]
    python3 -m core.cli llm check [--json]
    python3 -m core.cli export --format okf [--project NAME] [--out DIR]
                                [--no-evidence] [--min-confidence F]
    python3 -m core.cli projects list|info <name>|delete <name> [--purge]
    python3 -m core.cli status [--project NAME]

Project resolution order: --project flag > $EPISTRACT_PROJECT > nearest
ancestor directory containing .epistract/project.json.

All subcommands accept --json for machine-readable output.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import index_db
from . import registry
from .graph_retrieval import expand_from_seeds
from .llm_client import LOCAL_PLACEHOLDER_KEY, LLMCallError, LLMConfigError
from .registry import ProjectError


def _emit(payload: dict | list, as_json: bool, human: str) -> None:
    print(json.dumps(payload, indent=2) if as_json else human)


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------


def cmd_init(args) -> int:
    project = registry.init_project(args.name, root=args.dir, domain=args.domain)
    _emit(
        {"name": project["name"], "root": project["root"], "domain": project["domain"]},
        args.json,
        f"Initialized project '{project['name']}' ({project['domain']}) at {project['root']}",
    )
    return 0


def cmd_add_files(args) -> int:
    project = registry.resolve_project(args.project)
    report = registry.add_files(project, args.paths)
    human = (
        f"Project '{project['name']}': "
        f"{len(report['added'])} added, "
        f"{len(report['skipped_duplicate'])} duplicate(s) skipped, "
        f"{len(report['missing'])} missing"
    )
    for path in report["missing"]:
        human += f"\n  missing: {path}"
    _emit(report, args.json, human)
    return 1 if report["missing"] and not report["added"] else 0


def cmd_add_url(args) -> int:
    project = registry.resolve_project(args.project)
    results = [registry.add_url(project, url) for url in args.urls]
    lines = [f"  {r['url']}: {r['status']}" for r in results]
    _emit(results, args.json, f"Project '{project['name']}':\n" + "\n".join(lines))
    return 0


def cmd_index(args) -> int:
    project = registry.resolve_project(args.project)
    stats = index_db.index_project(project, rebuild=args.rebuild)
    human = (
        f"Project '{project['name']}': indexed {len(stats['indexed'])} document(s) "
        f"({stats['chunks']} chunks), skipped {stats['skipped']} unchanged, "
        f"{stats['entities']} entities from graph"
    )
    if stats["failed"]:
        human += f"\n  extraction failed: {', '.join(stats['failed'])}"
    _emit(stats, args.json, human)
    return 0


def cmd_search(args) -> int:
    project = registry.resolve_project(args.project)
    results = index_db.search_index(
        project, args.query, k=args.k, entity_type=args.type
    )
    if args.expand:
        graph_path = Path(project["root"]) / "graph_data.json"
        seeds = [e["node_id"] for e in results["entities"] if e.get("node_id")]
        results["expanded"] = (
            expand_from_seeds(graph_path, seeds, top_k=args.k)
            if graph_path.exists() and seeds
            else []
        )
    if args.json:
        print(json.dumps(results, indent=2))
        return 0
    if not results["fused"]:
        print(f"No results for '{args.query}' in project '{project['name']}'")
        return 0
    print(f"Results for '{args.query}' in project '{project['name']}':")
    for item in results["fused"]:
        if item["kind"] == "entity":
            print(f"  [entity] {item['name']} ({item['entity_type']})")
        else:
            snippet = " ".join(item["snippet"].split())[:120]
            print(f"  [chunk]  {item['doc_id']}#{item['chunk_no']}: {snippet}")
    for item in results.get("expanded", []):
        print(
            f"  [graph]  {item['name']} ({item['entity_type']}) score={item['score']}"
        )
    return 0


def _preflight_message(pre: dict, cfg) -> str:
    kind = pre.get("kind")
    err = pre.get("error")
    if kind == "not_chat":
        return (
            f"error: model {cfg.model} is not a chat model (e.g. a rerank or "
            "embedding model). Set EPISTRACT_LLM_MODEL or OPENROUTER_MODEL to a "
            f"chat model. Server said: {err}"
        )
    if kind == "unreachable":
        return f"error: cannot reach {cfg.base_url} - is the server running? ({err})"
    if kind == "quota":
        return f"error: provider quota or daily limit reached: {err}"
    return f"error: LLM preflight failed ({kind}): {err}"


def cmd_enhance(args) -> int:
    """Run arXiv-backed quality passes over the project's built graph.

    Passes (opt-in; if none selected, all run):
      --judge      LLM-as-judge triple gate (GraphJudge / GraphEval)
      --resolve    two-stage entity resolution (ComEM)
      --epistemic  bi-temporal contradiction layer + graded hedge scoring (Zep)

    Operates on <root>/graph_data.json and writes back in place, plus an
    enhancement_report.json. Uses lexical fallbacks unless --llm is given,
    so it runs offline. With --llm the provider is preflighted before any
    relation is judged; a judge abort (or Ctrl-C) exits non-zero without
    touching the graph or the report and keeps <root>/.judge_checkpoint.jsonl
    so the next run resumes (--fresh discards it).
    """
    from . import entity_resolution_v2 as erv2
    from . import epistemic_temporal as et
    from . import hedging
    from . import triple_judge

    project = registry.resolve_project(args.project)
    graph_path = Path(project["root"]) / "graph_data.json"
    if not graph_path.exists():
        print(
            f"Error: no graph_data.json in project '{project['name']}'. "
            "Build the graph first (/epistract:build).",
            file=sys.stderr,
        )
        return 1

    graph = json.loads(graph_path.read_text())
    link_key = "links" if "links" in graph else "edges"
    run_all = not (args.judge or args.resolve or args.epistemic)
    report: dict = {"project": project["name"]}

    if args.resolve or run_all:
        # Lexical/embedding cascade; an LLM entity-verifier can be plugged in
        # here via verify_fn once configured (kept lexical for offline default).
        res = erv2.resolve_entities(graph.get("nodes", []))
        graph = erv2.apply_merge_map(graph, res["merge_map"])
        report["resolve"] = {
            "auto_merged": res["auto_merged"],
            "clusters": len(res["clusters"]),
            "merged_ids": len(res["merge_map"]),
        }

    checkpoint = Path(project["root"]) / ".judge_checkpoint.jsonl"
    if args.judge or run_all:
        judge_fn = None
        cfg = None
        if args.llm:
            try:
                judge_fn = triple_judge.make_llm_judge()
            except LLMConfigError as e:
                print(f"error: --llm needs an LLM provider: {e}", file=sys.stderr)
                return 1
            except ImportError as e:
                print(
                    f"Error: --llm requires an LLM client but it could not be "
                    f"imported ({e}). Install the LLM dependencies or omit "
                    "--llm to use the offline lexical fallback.",
                    file=sys.stderr,
                )
                return 1
            cfg = getattr(judge_fn, "config", None)
            if cfg is not None:
                print(
                    f"LLM judge: provider={cfg.provider} model={cfg.model} "
                    f"base_url={cfg.base_url}",
                    file=sys.stderr,
                )
                from . import llm_local

                pre = llm_local.check_chat(cfg)
                if not pre["ok"]:
                    print(_preflight_message(pre, cfg), file=sys.stderr)
                    return 1
        try:
            report["judge"] = triple_judge.judge_graph(
                graph,
                judge_fn=judge_fn,
                checkpoint_path=checkpoint if args.llm else None,
                resume=not args.fresh,
                progress=bool(args.llm),
            )
        except triple_judge.JudgeAbort as e:
            st = e.stats or {}
            print(f"error: LLM judge aborted: {e}", file=sys.stderr)
            print(
                f"  calls={st.get('calls', 0)} llm_judged={st.get('llm_judged', 0)} "
                f"fallback={st.get('fallback', 0)}; nothing was written; "
                f"checkpoint kept at {checkpoint} - re-run to resume, "
                "or pass --fresh to start over",
                file=sys.stderr,
            )
            return 1
        except KeyboardInterrupt:
            print(
                "Interrupted; nothing was written; checkpoint kept at "
                f"{checkpoint} - re-run to resume",
                file=sys.stderr,
            )
            return 130
        report["judge"].update(
            {
                "mode": "llm" if args.llm else "lexical",
                "provider": getattr(cfg, "provider", None),
                "model": getattr(cfg, "model", None),
                "base_url": getattr(cfg, "base_url", None),
                "aborted": False,
            }
        )

    if args.epistemic or run_all:
        links = graph.get(link_key, [])
        scored = [hedging.score_relation(link) for link in links]
        temporal = et.apply_temporal_layer(scored)
        graph[link_key] = temporal["links"]
        status_counts: dict[str, int] = {}
        for link in temporal["links"]:
            status = link.get("epistemic_status", "unclassified")
            status_counts[status] = status_counts.get(status, 0) + 1
        report["epistemic"] = {
            "status_counts": status_counts,
            "contradictions": len(temporal["contradictions"]),
            "invalidated": temporal["invalidated"],
        }

    graph_path.write_text(json.dumps(graph, indent=2) + "\n")
    (Path(project["root"]) / "enhancement_report.json").write_text(
        json.dumps(report, indent=2) + "\n"
    )
    if args.llm:
        checkpoint.unlink(missing_ok=True)

    if args.json:
        print(json.dumps(report, indent=2))
        return 0
    print(f"Enhanced project '{project['name']}':")
    if "resolve" in report:
        r = report["resolve"]
        print(
            f"  entity resolution: merged {r['merged_ids']} into {r['clusters']} cluster(s)"
        )
    if "judge" in report:
        j = report["judge"]
        print(
            f"  triple judge: {j['verdict_counts']} — {j['gated_count']} gated "
            f"(score < {j['min_score']})"
        )
        if j.get("mode") == "llm":
            print(
                f"    llm_judged={j['llm_judged']} fallback={j['fallback']} "
                f"skipped_no_evidence={j['skipped_no_evidence']} "
                f"resumed={j['resumed']}"
            )
    if "epistemic" in report:
        e = report["epistemic"]
        print(
            f"  epistemic: {e['status_counts']}; "
            f"{e['contradictions']} contradiction(s), {e['invalidated']} superseded"
        )
    return 0


_NO_PROVIDER_MSG = (
    "No LLM provider configured. Set EPISTRACT_LLM_BASE_URL for a local "
    "OpenAI-compatible server, or ANTHROPIC_API_KEY / OPENROUTER_API_KEY / "
    "AZURE_FOUNDRY_API_KEY."
)

_CHECK_HINTS = {
    "not_chat": "the model does not serve chat completions; pick a chat model "
    "(EPISTRACT_LLM_MODEL / OPENROUTER_MODEL)",
    "unreachable": "the server is not reachable; is it running at the base URL?",
    "quota": "the provider's quota or daily limit is exhausted",
}


def cmd_llm_check(args) -> int:
    """Report the resolved LLM provider and whether it serves chat completions."""
    from . import llm_local
    from .llm_client import resolve_api_config

    try:
        cfg = resolve_api_config()
    except LLMConfigError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    if cfg is None:
        print(f"error: {_NO_PROVIDER_MSG}", file=sys.stderr)
        return 1

    models: list[str] = []
    note = None
    if cfg.provider == "local":
        real_key = None if cfg.api_key == LOCAL_PLACEHOLDER_KEY else cfg.api_key
        try:
            models = [m["id"] for m in llm_local.list_models(cfg.base_url, real_key)]
        except LLMCallError as e:
            note = str(e)
    pre = llm_local.check_chat(cfg)
    result = {
        "provider": cfg.provider,
        "base_url": cfg.base_url,
        "model": cfg.model,
        "context_window": cfg.context_window,
        "models": models,
        "chat_ok": bool(pre["ok"]),
        "kind": pre["kind"],
        "error": pre["error"],
    }
    if args.json:
        print(json.dumps(result, indent=2))
        return 0 if pre["ok"] else 1
    ctx = cfg.context_window if cfg.context_window else "unknown"
    print(f"provider:       {cfg.provider}")
    print(f"base url:       {cfg.base_url}")
    print(f"model:          {cfg.model}")
    print(f"context window: {ctx}")
    print(f"served models:  {', '.join(models) if models else '(none listed)'}")
    if note:
        print(f"  note: could not list models: {note}")
    if pre["ok"]:
        print("chat: ok")
        return 0
    print(f"chat: FAILED ({pre['kind']}): {pre['error']}")
    hint = _CHECK_HINTS.get(pre["kind"])
    if hint:
        print(f"  hint: {hint}")
    return 1


def cmd_export(args) -> int:
    """Export the project's graph as an OKF bundle.

    Only `--format okf` is handled here. Other formats (graphml, gexf, csv,
    sqlite, plain json) continue to go through `core/run_sift.py export`
    (see `/epistract:export`), which operates on a bare output directory
    rather than a registered project.
    """
    if args.format != "okf":
        print(
            f"Error: `epistract export` only supports --format okf. "
            f"For '{args.format}', use core/run_sift.py export "
            "(graphml, gexf, csv, sqlite, json).",
            file=sys.stderr,
        )
        return 2

    try:
        from .okf_export import export_okf
    except ImportError as e:
        print(
            f"Error: OKF export requires dependencies that are not installed "
            f"({e}). Run `scripts/setup.sh` (or `uv pip install sift-kg`) to "
            "install them.",
            file=sys.stderr,
        )
        return 1

    project = registry.resolve_project(args.project)
    try:
        summary = export_okf(
            project["root"],
            args.out,
            include_evidence=not args.no_evidence,
            min_confidence=args.min_confidence,
        )
    except (FileNotFoundError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    human = (
        f"Project '{project['name']}': exported OKF bundle to {summary['bundle_path']}\n"
        f"  concepts: {summary['concept_counts']}\n"
        f"  skipped edges (below min-confidence): {summary['skipped_edges']}"
    )
    if summary["warnings"]:
        human += "\n  warnings:\n" + "\n".join(
            f"    - {w}" for w in summary["warnings"]
        )
    _emit(summary, args.json, human)
    return 0


def cmd_projects(args) -> int:
    if args.action == "list":
        projects = registry.list_projects()
        human = (
            "\n".join(
                f"  {p['name']:24s} {p.get('domain', ''):18s} {p['root']}"
                for p in projects
            )
            or "  (no projects — run `epistract init <name>`)"
        )
        _emit(projects, args.json, f"Registered projects:\n{human}")
        return 0
    if args.action == "info":
        project = registry.get_project(args.name)
        sources = project["manifest"]["sources"]
        _emit(
            project,
            args.json,
            f"{project['name']} ({project['domain']}) at {project['root']}\n"
            f"  sources: {len(sources)}",
        )
        return 0
    if args.action == "delete":
        removed = registry.delete_project(args.name, purge=args.purge)
        _emit(
            removed,
            args.json,
            f"Removed '{args.name}' from registry"
            + (" and purged .epistract state" if args.purge else "")
            + f" (files at {removed['root']} untouched)",
        )
        return 0
    return 2


def cmd_status(args) -> int:
    project = registry.resolve_project(args.project)
    root = Path(project["root"])
    graph_path = root / "graph_data.json"
    graph_nodes = (
        len(json.loads(graph_path.read_text()).get("nodes", []))
        if graph_path.exists()
        else 0
    )
    indexed = 0
    if index_db.index_path(project).exists():
        db = index_db.open_index(project)
        indexed = db.execute("SELECT count(*) FROM documents").fetchone()[0]
        db.close()
    payload = {
        "name": project["name"],
        "root": project["root"],
        "domain": project["domain"],
        "sources": len(project["manifest"]["sources"]),
        "indexed_documents": indexed,
        "graph_nodes": graph_nodes,
        "claims_layer": (root / "claims_layer.json").exists(),
    }
    _emit(
        payload,
        args.json,
        f"{payload['name']} ({payload['domain']}) at {payload['root']}\n"
        f"  sources: {payload['sources']}  indexed: {indexed}  "
        f"graph nodes: {graph_nodes}  claims layer: "
        f"{'yes' if payload['claims_layer'] else 'no'}",
    )
    return 0


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="epistract", description="Multi-project knowledge graph datasets"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="Create a new project")
    p_init.add_argument("name")
    p_init.add_argument("--domain", default=None, help="Domain package name")
    p_init.add_argument(
        "--dir", default=None, help="Project directory (default ./<name>)"
    )
    p_init.add_argument("--json", action="store_true")
    p_init.set_defaults(func=cmd_init)

    p_add = sub.add_parser("add", help="Add a project, files, or URLs")
    add_sub = p_add.add_subparsers(dest="what", required=True)

    p_add_project = add_sub.add_parser("project", help="Register a new project")
    p_add_project.add_argument("name")
    p_add_project.add_argument("--domain", default=None)
    p_add_project.add_argument("--dir", default=None)
    p_add_project.add_argument("--json", action="store_true")
    p_add_project.set_defaults(func=cmd_init)

    p_add_files = add_sub.add_parser("files", help="Add source files to the corpus")
    p_add_files.add_argument("paths", nargs="+")
    p_add_files.add_argument("--project", default=None)
    p_add_files.add_argument("--json", action="store_true")
    p_add_files.set_defaults(func=cmd_add_files)

    p_add_url = add_sub.add_parser("url", help="Fetch URLs into the corpus")
    p_add_url.add_argument("urls", nargs="+")
    p_add_url.add_argument("--project", default=None)
    p_add_url.add_argument("--json", action="store_true")
    p_add_url.set_defaults(func=cmd_add_url)

    p_index = sub.add_parser("index", help="Incrementally index the project")
    p_index.add_argument("--project", default=None)
    p_index.add_argument(
        "--rebuild", action="store_true", help="Drop and rebuild the index"
    )
    p_index.add_argument("--json", action="store_true")
    p_index.set_defaults(func=cmd_index)

    p_search = sub.add_parser("search", help="Hybrid search (entities + chunks)")
    p_search.add_argument("query")
    p_search.add_argument("--project", default=None)
    p_search.add_argument("--type", default=None, help="Filter entities by type")
    p_search.add_argument("-k", type=int, default=10, help="Max results")
    p_search.add_argument(
        "--expand",
        action="store_true",
        help="Graph expansion via personalized PageRank",
    )
    p_search.add_argument("--json", action="store_true")
    p_search.set_defaults(func=cmd_search)

    p_enhance = sub.add_parser(
        "enhance", help="Run KG quality passes (judge / resolve / epistemic)"
    )
    p_enhance.add_argument("--project", default=None)
    p_enhance.add_argument(
        "--judge", action="store_true", help="LLM-as-judge triple gate"
    )
    p_enhance.add_argument(
        "--resolve", action="store_true", help="Entity resolution merge"
    )
    p_enhance.add_argument(
        "--epistemic",
        action="store_true",
        help="Bi-temporal contradiction + hedge layer",
    )
    p_enhance.add_argument(
        "--llm",
        action="store_true",
        help="Use the configured LLM provider (EPISTRACT_LLM_BASE_URL for a "
        "local server; aborts instead of silently falling back)",
    )
    p_enhance.add_argument(
        "--fresh",
        action="store_true",
        help="Ignore any judge checkpoint and re-judge every relation",
    )
    p_enhance.add_argument("--json", action="store_true")
    p_enhance.set_defaults(func=cmd_enhance)

    p_llm = sub.add_parser("llm", help="Inspect the configured LLM provider")
    llm_sub = p_llm.add_subparsers(dest="action", required=True)
    p_llm_check = llm_sub.add_parser(
        "check", help="Verify the provider serves chat completions"
    )
    p_llm_check.add_argument("--json", action="store_true")
    p_llm_check.set_defaults(func=cmd_llm_check)

    p_export = sub.add_parser("export", help="Export the graph (currently: OKF bundle)")
    p_export.add_argument(
        "--format",
        default="okf",
        help="Export format (only 'okf' supported here; see run_sift.py for others)",
    )
    p_export.add_argument("--project", default=None)
    p_export.add_argument(
        "--out", default=None, help="Bundle output directory (default: <root>/okf/)"
    )
    p_export.add_argument(
        "--no-evidence",
        action="store_true",
        help="Redact evidence text from concept bodies and sidecar JSON",
    )
    p_export.add_argument(
        "--min-confidence",
        type=float,
        default=0.0,
        help="Omit relations below this confidence from Relations tables",
    )
    p_export.add_argument("--json", action="store_true")
    p_export.set_defaults(func=cmd_export)

    p_projects = sub.add_parser("projects", help="Manage the project registry")
    projects_sub = p_projects.add_subparsers(dest="action", required=True)
    p_list = projects_sub.add_parser("list")
    p_list.add_argument("--json", action="store_true")
    p_info = projects_sub.add_parser("info")
    p_info.add_argument("name")
    p_info.add_argument("--json", action="store_true")
    p_delete = projects_sub.add_parser("delete")
    p_delete.add_argument("name")
    p_delete.add_argument(
        "--purge", action="store_true", help="Also remove .epistract state"
    )
    p_delete.add_argument("--json", action="store_true")
    p_projects.set_defaults(func=cmd_projects)

    p_status = sub.add_parser("status", help="Show project status")
    p_status.add_argument("--project", default=None)
    p_status.add_argument("--json", action="store_true")
    p_status.set_defaults(func=cmd_status)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except ProjectError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
