#!/usr/bin/env python3
"""crosswalk -- build a cross-graph spine.json joining independently-built
epistract project graphs on shared identifier axes.

No cross-graph merge exists in core/ or in sift-kg, and the project registry
is strictly one domain per project directory. spine.json is therefore a new
artifact: a mapping from a canonical key per axis to the node IDs holding
that key in each graph, plus a stats block.

Architecture, in two config files so this module stays domain-agnostic:

1. Extraction (domain knowledge) -- an optional ``<domain_dir>/crosswalk.yaml``
   per domain, following the ``get_validation_dir`` convention: probe, return
   None when absent, stay silent. Declares, per axis, which entity types
   participate and which value sources to try (in order).
2. Canonicalisation (axis knowledge) -- a single repo-level axis spec
   (``--axes``) holding exactly one normalizer chain per axis, applied
   identically to every graph. See core/crosswalk_normalize.py for the
   primitive table and chain runner.

Usage:
    python3 -m core.crosswalk build --graph DIR1 --graph NAME=DIR2 \\
        --axes crosswalks/pharma.yaml --out spine.json
"""

from __future__ import annotations

import argparse
import itertools
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import yaml

from . import domain_resolver
from .crosswalk_normalize import CrosswalkConfigError, build_chain, run_compiled_chain

__all__ = [
    "CrosswalkConfigError",
    "build_parser",
    "build_spine",
    "collect_identifiers",
    "compute_stats",
    "domain_crosswalk_path",
    "extract_axis_keys",
    "load_axis_spec",
    "load_domain_config",
    "load_graph",
    "load_graphs",
    "main",
    "resolve_domain_configs",
    "source_candidates",
]

_PAIR_SEPARATOR = "|"


# ---------------------------------------------------------------------------
# Graph loading
# ---------------------------------------------------------------------------


def load_graph(spec: str) -> dict:
    """Load one graph from a ``[NAME=]DIR`` spec.

    Returns a dict with keys: key (graph identity used in spine output,
    from the explicit NAME or metadata.domain or the directory name),
    dir (Path), payload (the parsed graph_data.json dict).
    """
    explicit_name = None
    dir_str = spec
    if "=" in spec:
        explicit_name, dir_str = spec.split("=", 1)
    graph_dir = Path(dir_str).resolve()
    graph_file = graph_dir / "graph_data.json"
    if not graph_file.is_file():
        raise CrosswalkConfigError(
            f"No graph_data.json found in {graph_dir} (from graph spec {spec!r})"
        )
    try:
        payload = json.loads(graph_file.read_text())
    except json.JSONDecodeError as e:
        raise CrosswalkConfigError(f"Unreadable JSON in {graph_file}: {e}") from e

    key = explicit_name or payload.get("metadata", {}).get("domain") or graph_dir.name
    return {"key": key, "dir": graph_dir, "payload": payload}


def load_graphs(specs: list[str]) -> dict[str, dict]:
    """Load multiple graphs, keyed by their resolved identity.

    Raises CrosswalkConfigError on a duplicate key naming both directories
    and pointing at the NAME=DIR disambiguation form.
    """
    graphs: dict[str, dict] = {}
    for spec in specs:
        graph = load_graph(spec)
        key = graph["key"]
        if key in graphs:
            raise CrosswalkConfigError(
                f"Duplicate graph key {key!r} from {graph['dir']} and "
                f"{graphs[key]['dir']}; disambiguate with the NAME=DIR form, "
                f"e.g. --graph other_{key}={graph['dir']}"
            )
        graphs[key] = graph
    return graphs


# ---------------------------------------------------------------------------
# Config resolution
# ---------------------------------------------------------------------------


def load_axis_spec(path: str | Path) -> dict:
    """Load and validate the repo-level axis spec.

    Returns {"raw": {axis_name: axis_config, ...}, "compiled": {axis_name:
    compiled_chain, ...}}. Op names are validated eagerly here (at load
    time) so a config typo fails at startup rather than silently producing
    zero joins.
    """
    spec_path = Path(path).resolve()
    spec = yaml.safe_load(spec_path.read_text()) or {}
    axes = spec.get("axes") or {}
    compiled: dict[str, list] = {}
    for axis_name, axis_cfg in axes.items():
        normalize_chain = (axis_cfg or {}).get("normalize") or []
        try:
            compiled[axis_name] = build_chain(normalize_chain)
        except CrosswalkConfigError as e:
            raise CrosswalkConfigError(
                f"{spec_path}: axis {axis_name!r}: {e}"
            ) from e
    return {"raw": axes, "compiled": compiled, "path": spec_path}


def domain_crosswalk_path(graph_payload: dict) -> Path | None:
    """Resolve the crosswalk.yaml path for a graph's domain, if it ships one.

    Mirrors get_validation_dir: probe, return None when absent, stay
    silent. Returns None if the graph has no resolvable metadata.domain or
    the resolved domain ships no crosswalk.yaml.
    """
    domain_name = (graph_payload.get("metadata") or {}).get("domain")
    if not domain_name:
        return None
    try:
        resolved = domain_resolver.resolve_domain(domain_name)
    except FileNotFoundError:
        return None
    crosswalk_path = Path(resolved["dir"]) / "crosswalk.yaml"
    return crosswalk_path if crosswalk_path.is_file() else None


def load_domain_config(graph_payload: dict) -> dict | None:
    """Load a graph's domain-level crosswalk.yaml, if the domain ships one."""
    crosswalk_path = domain_crosswalk_path(graph_payload)
    if crosswalk_path is None:
        return None
    return yaml.safe_load(crosswalk_path.read_text()) or {}


def resolve_domain_configs(graphs: dict[str, dict], axis_spec: dict) -> dict[str, dict]:
    """Attach each graph's domain crosswalk config (functionally -- returns
    a new dict; never mutates the loaded graph payloads).

    Raises CrosswalkConfigError, naming both files, if a domain config
    declares an axis the axis spec does not.
    """
    out: dict[str, dict] = {}
    for key, graph in graphs.items():
        domain_cfg = load_domain_config(graph["payload"])
        if domain_cfg:
            for axis_name in domain_cfg.get("axes") or {}:
                if axis_name not in axis_spec["raw"]:
                    crosswalk_path = domain_crosswalk_path(graph["payload"])
                    raise CrosswalkConfigError(
                        f"Graph {key!r} declares axis {axis_name!r} in "
                        f"{crosswalk_path}, but {axis_spec['path']} does "
                        "not declare that axis"
                    )
        out[key] = {**graph, "domain_config": domain_cfg}
    return out


# ---------------------------------------------------------------------------
# Key extraction
# ---------------------------------------------------------------------------


def _flatten_value(value) -> list[str]:
    """Flatten a possibly-list-valued, possibly-numeric attribute value into
    a list of string candidates. None/absent values contribute nothing."""
    if value is None:
        return []
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            out.extend(_flatten_value(item))
        return out
    return [str(value)]


def source_candidates(node: dict, source: dict) -> list[str]:
    """Resolve one value-source config to a list of raw string candidates
    for a node. Source kinds: {"from": "name"}, {"from": "any_attribute"},
    {"from": "attribute", "key": K}."""
    kind = source.get("from")
    if kind == "name":
        name = node.get("name")
        return [name] if name else []
    if kind == "any_attribute":
        out: list[str] = []
        for value in (node.get("attributes") or {}).values():
            out.extend(_flatten_value(value))
        return out
    if kind == "attribute":
        key = source.get("key")
        return _flatten_value((node.get("attributes") or {}).get(key))
    raise CrosswalkConfigError(f"Unknown value source 'from': {kind!r}")


def extract_axis_keys(node: dict, axis_domain_cfg: dict, compiled_chain: list) -> set[str]:
    """Extract the canonical key set for one node on one axis.

    Sources are tried in order; the first source producing at least one
    non-empty canonical key wins (union across sources is deliberately not
    done -- see module docstring / plan rationale). A node whose entity_type
    is not in the axis's entity_types produces no keys.
    """
    entity_types = axis_domain_cfg.get("entity_types") or []
    if node.get("entity_type") not in entity_types:
        return set()
    for source in axis_domain_cfg.get("sources") or []:
        candidates = source_candidates(node, source)
        keys = {
            key
            for candidate in candidates
            if (key := run_compiled_chain(candidate, compiled_chain))
        }
        if keys:
            return keys
    return set()


def collect_identifiers(node: dict, identifiers_cfg: dict) -> dict[str, list[str]]:
    """Collect stable-identifier values declared for one node on one axis.

    Identifier values are recorded verbatim (never run through the axis
    normalizer chain -- they are external codes, not names).
    """
    out: dict[str, list[str]] = {}
    for label, source in (identifiers_cfg or {}).items():
        values = source_candidates(node, source)
        if values:
            out[label] = sorted(set(values))
    return out


# ---------------------------------------------------------------------------
# Spine assembly
# ---------------------------------------------------------------------------


def build_spine(graphs: dict[str, dict], axis_spec: dict) -> dict:
    """Assemble the spine's axes + stats from resolved graphs.

    graphs must already carry "domain_config" (see resolve_domain_configs).
    Builds new dicts throughout -- never mutates the loaded graph payloads.
    """
    axes_out: dict[str, dict] = {}
    stats_out: dict[str, dict] = {}

    for axis_name, compiled_chain in axis_spec["compiled"].items():
        declaring_graphs: list[str] = []
        canonical: dict[str, dict] = {}

        for graph_key, graph in graphs.items():
            domain_cfg = graph.get("domain_config")
            if not domain_cfg or axis_name not in (domain_cfg.get("axes") or {}):
                continue
            declaring_graphs.append(graph_key)
            axis_domain_cfg = domain_cfg["axes"][axis_name]
            identifiers_cfg = axis_domain_cfg.get("identifiers") or {}

            for node in graph["payload"].get("nodes") or []:
                keys = extract_axis_keys(node, axis_domain_cfg, compiled_chain)
                if not keys:
                    continue
                id_values = collect_identifiers(node, identifiers_cfg) if identifiers_cfg else {}
                for key in keys:
                    entry = canonical.setdefault(key, {"identifiers": {}, "graphs": {}})
                    entry["graphs"].setdefault(graph_key, set()).add(node["id"])
                    for label, values in id_values.items():
                        entry["identifiers"].setdefault(label, set()).update(values)

        axes_out[axis_name] = {
            key: {
                "identifiers": {
                    label: sorted(values) for label, values in entry["identifiers"].items()
                },
                "graphs": {gk: sorted(ids) for gk, ids in entry["graphs"].items()},
            }
            for key, entry in sorted(canonical.items())
        }
        stats_out[axis_name] = compute_stats(axes_out[axis_name], declaring_graphs)

    return {"axes": axes_out, "stats": stats_out}


def compute_stats(axis_data: dict, declaring_graphs: list[str]) -> dict:
    """Per-axis stats: total keys, per-graph key counts, pairwise overlap
    counts, count shared by 2+ graphs, count shared by every declaring
    graph, and the list of declaring graphs.

    Intersections are computed over the graphs that DECLARE the axis, not
    over every graph loaded -- a non-participating loaded graph must not
    zero out the all-graph intersection.
    """
    declared_sorted = sorted(declaring_graphs)
    keys_per_graph: dict[str, int] = {g: 0 for g in declared_sorted}
    pairwise = {
        f"{g1}{_PAIR_SEPARATOR}{g2}": 0
        for g1, g2 in itertools.combinations(declared_sorted, 2)
    }
    shared_by_2_or_more = 0
    shared_by_all_graphs = 0

    for entry in axis_data.values():
        present = set(entry["graphs"])
        for g in present:
            keys_per_graph[g] = keys_per_graph.get(g, 0) + 1
        if len(present) >= 2:
            shared_by_2_or_more += 1
        if declared_sorted and len(present) == len(declared_sorted):
            shared_by_all_graphs += 1
        for g1, g2 in itertools.combinations(declared_sorted, 2):
            if g1 in present and g2 in present:
                pairwise[f"{g1}{_PAIR_SEPARATOR}{g2}"] += 1

    return {
        "keys_total": len(axis_data),
        "keys_per_graph": keys_per_graph,
        "pairwise": pairwise,
        "shared_by_2_or_more": shared_by_2_or_more,
        "shared_by_all_graphs": shared_by_all_graphs,
        "declared_by": declared_sorted,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="crosswalk", description="Build a cross-graph spine.json"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_build = sub.add_parser("build", help="Build spine.json from two or more graphs")
    p_build.add_argument(
        "--graph",
        action="append",
        dest="graphs",
        required=True,
        help="[NAME=]DIR -- repeatable, one per graph project directory",
    )
    p_build.add_argument("--axes", required=True, help="Path to the axis spec YAML")
    p_build.add_argument("--out", default="spine.json", help="Output spine.json path")
    p_build.add_argument("--json", action="store_true", help="Print the stats block to stdout")
    p_build.set_defaults(func=_cmd_build)

    return parser


def _cmd_build(args: argparse.Namespace) -> int:
    try:
        graphs = load_graphs(args.graphs)
        axis_spec = load_axis_spec(args.axes)
        graphs = resolve_domain_configs(graphs, axis_spec)
        result = build_spine(graphs, axis_spec)
    except CrosswalkConfigError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    payload = {
        "spine_version": "1.0",
        "generated_at": datetime.now(UTC).isoformat(),
        "graphs": {key: str(graph["dir"]) for key, graph in graphs.items()},
        "axes": result["axes"],
        "stats": result["stats"],
    }
    Path(args.out).resolve().write_text(json.dumps(payload, indent=2) + "\n")

    if args.json:
        print(json.dumps(result["stats"], indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
