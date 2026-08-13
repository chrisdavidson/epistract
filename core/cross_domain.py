#!/usr/bin/env python3
"""cross_domain -- consume a spine.json crosswalk plus the graphs it was
built from and emit cross-domain epistemic findings.

Mirrors core/crosswalk.py exactly: same two-layer config split, same eager-
validation discipline, same domain-agnostic gate, same argparse-invoked-as-
a-module shape. `core/label_epistemic.py` dispatches domain rules as
``rule(nodes, links, context)`` over exactly ONE graph_data.json for exactly
ONE domain -- a single-graph, single-domain contract. Cross-domain rules
need N graphs plus the spine, so they do not fit that hook, and this module
does not modify it. See the plan's decision_rationale for the full
argument.

Every finding is a set difference across two graphs joined on a canonical
spine key, computed by one of two comparison modes (core/cross_domain_
compare.py):

- ``spine_keys`` -- canonical-key set difference, with subtype
  classification (absent / attributed_elsewhere / granularity_variant).
- ``text_tokens`` -- configurable token-coverage ratio, for axis pairs
  where the reference side holds no comparably-typed entities to
  key-difference against.

Which graphs play probe/reference, which axis pair a rule spans, which
relation types connect the pair, how a miss is worded, and how it is
graded all arrive from config: the repo-level rules spec
(crosswalks/pharma-rules.yaml) plus each domain's `edges:` section
(<domain_dir>/crosswalk.yaml). This module and core/cross_domain_compare.py
contain no domain vocabulary of their own -- no entity type names, no
relation type names, no attribute key names, no clinical or molecule terms.

Grade vocabulary: lowercase ``high`` / ``medium`` / ``low`` / ``advisory``.
Existing consumers treat the finding grade as free-form (the workbench
slugifies it into a tag; the contracts domain uses capitalised words), but
these rules need a graded band, which a single-level vocabulary cannot
express.

Usage:
    python3 -m core.cross_domain analyze --spine spine.json \\
        --rules crosswalks/pharma-rules.yaml --out cross_domain_findings.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import yaml

from .cross_domain_compare import classify_miss, coverage_ratio, resolve_band, tokenize
from .crosswalk import load_domain_config, load_graphs, source_candidates
from .crosswalk_normalize import CrosswalkConfigError

__all__ = [
    "CrosswalkConfigError",
    "attach_domain_configs",
    "build_axis_node_index",
    "build_parser",
    "load_rules_spec",
    "load_spine",
    "main",
    "project_edges",
    "render_description",
    "resolve_graph_specs",
    "run_rule",
    "run_rules",
]

_COMPARE_MODES = ("spine_keys", "text_tokens")
_REQUIRED_RULE_KEYS = ("name", "subject_axis", "object_axis", "probe", "reference", "compare")


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load_spine(path: str | Path) -> dict:
    """Load a spine.json written by core/crosswalk.py."""
    spine_path = Path(path).resolve()
    try:
        return json.loads(spine_path.read_text())
    except FileNotFoundError as e:
        raise CrosswalkConfigError(f"No spine file at {spine_path}") from e
    except json.JSONDecodeError as e:
        raise CrosswalkConfigError(f"Unreadable JSON in {spine_path}: {e}") from e


def resolve_graph_specs(spine: dict, overrides: list[str]) -> list[str]:
    """Return ``[NAME=DIR, ...]`` specs for core.crosswalk.load_graphs,
    one per graph the spine recorded, using the spine-recorded directory by
    default and substituting any ``NAME=DIR`` override for the matching
    key. The NAME= form is always used (even for the default) so the
    loaded graph's key is forced to the spine's recorded key regardless of
    what that graph's own metadata.domain says -- a spine built with a
    NAME= override records a key that a plain re-derivation from
    metadata.domain would not reproduce.
    """
    override_map: dict[str, str] = {}
    for spec in overrides:
        if "=" not in spec:
            raise CrosswalkConfigError(
                f"--graph override {spec!r} must be in NAME=DIR form, naming "
                "one of the spine's recorded graph keys"
            )
        name, dir_str = spec.split("=", 1)
        override_map[name] = dir_str

    recorded = spine.get("graphs") or {}
    unknown_overrides = sorted(set(override_map) - set(recorded))
    if unknown_overrides:
        raise CrosswalkConfigError(
            f"--graph override names {unknown_overrides} not recorded in the "
            f"spine; the spine recorded: {sorted(recorded)}"
        )
    return [
        f"{key}={override_map.get(key, recorded_dir)}" for key, recorded_dir in recorded.items()
    ]


def attach_domain_configs(graphs: dict) -> dict:
    """Attach each graph's domain-level crosswalk.yaml (functionally --
    returns a new dict; never mutates the loaded graph payloads), the same
    way core.crosswalk.resolve_domain_configs does for spine building. This
    engine reads only the ``edges:`` section, so unlike
    resolve_domain_configs it validates nothing against an axis spec --
    axis names here are validated against the spine instead (see
    load_rules_spec)."""
    return {
        key: {**graph, "domain_config": load_domain_config(graph["payload"])}
        for key, graph in graphs.items()
    }


def load_rules_spec(path: str | Path, spine: dict) -> dict:
    """Load and eagerly validate the repo-level rules spec against the
    spine: every rule's probe/reference graph name and subject/object axis
    name is checked against what the spine actually recorded, and its
    compare mode against the two modes this engine implements. A typo here
    must fail loudly at load time, naming both the offending value and the
    valid alternatives -- a silent zero-finding run is exactly the failure
    mode this validation exists to prevent (see plan key_links).

    Per-rule template correctness (whether a description template's fields
    are all ones the engine actually supplies) is NOT validated here -- it
    is checked at render time, once the fields a produced finding carries
    are known. See ``render_description``.
    """
    spec_path = Path(path).resolve()
    spec = yaml.safe_load(spec_path.read_text()) or {}
    graph_keys = sorted((spine.get("graphs") or {}).keys())
    axis_keys = sorted((spine.get("axes") or {}).keys())

    rules: list[dict] = []
    for raw_rule in spec.get("rules") or []:
        name = raw_rule.get("name", "<unnamed>")
        missing = [k for k in _REQUIRED_RULE_KEYS if k not in raw_rule]
        if missing:
            raise CrosswalkConfigError(
                f"{spec_path}: rule {name!r} is missing required key(s): {missing}"
            )
        for role, graph_key in (("probe", raw_rule["probe"]), ("reference", raw_rule["reference"])):
            if graph_key not in graph_keys:
                raise CrosswalkConfigError(
                    f"{spec_path}: rule {name!r} names {role} graph {graph_key!r}, "
                    f"which the spine does not record. Graphs the spine recorded: "
                    f"{graph_keys}"
                )
        for role, axis_name in (
            ("subject_axis", raw_rule["subject_axis"]),
            ("object_axis", raw_rule["object_axis"]),
        ):
            if axis_name not in axis_keys:
                raise CrosswalkConfigError(
                    f"{spec_path}: rule {name!r} names {role} {axis_name!r}, which "
                    f"the spine does not carry. Axes the spine carries: {axis_keys}"
                )
        compare_mode = raw_rule["compare"]
        if compare_mode not in _COMPARE_MODES:
            raise CrosswalkConfigError(
                f"{spec_path}: rule {name!r} names unknown compare mode "
                f"{compare_mode!r}. Known modes: {list(_COMPARE_MODES)}"
            )
        if compare_mode == "text_tokens" and not raw_rule.get("text_tokens"):
            raise CrosswalkConfigError(
                f"{spec_path}: rule {name!r} uses compare: text_tokens but "
                "declares no 'text_tokens' config block"
            )
        rules.append(raw_rule)

    return {"rules": rules, "path": spec_path}


# ---------------------------------------------------------------------------
# Spine indexing and projection
# ---------------------------------------------------------------------------


def build_axis_node_index(spine: dict) -> dict[str, dict[str, dict[str, list[str]]]]:
    """Build ``{axis_name: {graph_key: {node_id: [canonical_key, ...]}}}``
    from a loaded spine -- the reverse of the spine's own
    canonical-key-to-node-id-list shape, needed to resolve a link's
    endpoints back to their canonical keys during projection."""
    index: dict[str, dict[str, dict[str, list[str]]]] = {}
    for axis_name, axis_entries in (spine.get("axes") or {}).items():
        axis_index: dict[str, dict[str, list[str]]] = {}
        for canonical_key, entry in axis_entries.items():
            for graph_key, node_ids in (entry.get("graphs") or {}).items():
                graph_index = axis_index.setdefault(graph_key, {})
                for node_id in node_ids:
                    graph_index.setdefault(node_id, []).append(canonical_key)
        index[axis_name] = axis_index
    return index


def project_edges(
    graph: dict,
    graph_key: str,
    subject_axis: str,
    object_axis: str,
    node_index: dict,
    relations: list[str],
) -> dict[str, set[str]]:
    """Project one graph's links into ``{subject_key: {object_key, ...}}``
    for one axis pair, using only the configured relation types and
    matching them in either direction (an edge subject->object or
    object->subject both count -- the axis entity-type filter already
    constrains which endpoint is which). An edge whose endpoints are not on
    the two named axes at all, or whose relation type is not in
    ``relations``, contributes nothing."""
    subject_lookup = node_index.get(subject_axis, {}).get(graph_key, {})
    object_lookup = node_index.get(object_axis, {}).get(graph_key, {})
    relation_set = set(relations)

    result: dict[str, set[str]] = {}
    for link in graph.get("payload", {}).get("links") or []:
        if link.get("relation_type") not in relation_set:
            continue
        source_id, target_id = link.get("source"), link.get("target")

        subject_keys = subject_lookup.get(source_id)
        object_keys = object_lookup.get(target_id)
        if subject_keys and object_keys:
            for subject_key in subject_keys:
                result.setdefault(subject_key, set()).update(object_keys)
            continue

        subject_keys = subject_lookup.get(target_id)
        object_keys = object_lookup.get(source_id)
        if subject_keys and object_keys:
            for subject_key in subject_keys:
                result.setdefault(subject_key, set()).update(object_keys)

    return result


def _edge_config(graph: dict, subject_axis: str, object_axis: str) -> dict | None:
    """Look up the ``edges:`` entry for one axis pair in a graph's domain
    config. Returns None if the graph's domain declares no such edge --
    the caller decides whether that is an error (e.g. neither side of a
    spine_keys rule can proceed without one) or expected (a graph
    participating only as the probe side of a text_tokens rule has no
    edge entry for the reference side's text sources)."""
    domain_cfg = graph.get("domain_config") or {}
    for edge in domain_cfg.get("edges") or []:
        if edge.get("subject") == subject_axis and edge.get("object") == object_axis:
            return edge
    return None


# ---------------------------------------------------------------------------
# Description rendering
# ---------------------------------------------------------------------------


class _StrictFormatDict(dict):
    def __missing__(self, key):
        raise CrosswalkConfigError(
            f"Description template references unknown field {key!r}. Known "
            f"fields: {sorted(self)}"
        )


def render_description(template: str, data: dict) -> str:
    """Render a description template against a finding's field dict.

    A template referencing a field the caller did not supply raises
    CrosswalkConfigError naming the missing field -- not a bare KeyError --
    because a template typo is a config error, not a code bug.
    """
    try:
        return template.format_map(_StrictFormatDict(data))
    except (IndexError, ValueError) as e:
        raise CrosswalkConfigError(f"Malformed description template {template!r}: {e}") from e


# ---------------------------------------------------------------------------
# Rule dispatch
# ---------------------------------------------------------------------------


def _severity_for(rule_cfg: dict, subtype: str) -> str:
    severities = rule_cfg.get("severity") or {}
    if subtype not in severities:
        raise CrosswalkConfigError(
            f"Rule {rule_cfg.get('name')!r} has no severity configured for "
            f"subtype {subtype!r}. Configured subtypes: {sorted(severities)}"
        )
    return severities[subtype]


def _description_for(rule_cfg: dict, subtype: str) -> str:
    descriptions = rule_cfg.get("descriptions") or {}
    if subtype not in descriptions:
        raise CrosswalkConfigError(
            f"Rule {rule_cfg.get('name')!r} has no description template for "
            f"subtype {subtype!r}. Configured subtypes: {sorted(descriptions)}"
        )
    return descriptions[subtype]


def _spine_node_ids(spine: dict, axis: str, canonical_key: str, graph_key: str) -> list[str]:
    entry = (spine.get("axes") or {}).get(axis, {}).get(canonical_key) or {}
    return list((entry.get("graphs") or {}).get(graph_key, []))


def _run_spine_keys_rule(
    rule_cfg: dict, spine: dict, graphs: dict, node_index: dict
) -> tuple[list[dict], dict]:
    name = rule_cfg["name"]
    subject_axis, object_axis = rule_cfg["subject_axis"], rule_cfg["object_axis"]
    probe_key, reference_key = rule_cfg["probe"], rule_cfg["reference"]
    probe_graph, reference_graph = graphs[probe_key], graphs[reference_key]

    probe_edge = _edge_config(probe_graph, subject_axis, object_axis)
    if probe_edge is None or not probe_edge.get("relations"):
        raise CrosswalkConfigError(
            f"Rule {name!r}: probe graph {probe_key!r} declares no edges "
            f"entry with relations for {subject_axis!r}/{object_axis!r}"
        )
    reference_edge = _edge_config(reference_graph, subject_axis, object_axis)
    if reference_edge is None or not reference_edge.get("relations"):
        raise CrosswalkConfigError(
            f"Rule {name!r}: reference graph {reference_key!r} declares no "
            f"edges entry with relations for {subject_axis!r}/{object_axis!r}"
        )

    probe_map = project_edges(
        probe_graph, probe_key, subject_axis, object_axis, node_index, probe_edge["relations"]
    )
    reference_map = project_edges(
        reference_graph,
        reference_key,
        subject_axis,
        object_axis,
        node_index,
        reference_edge["relations"],
    )
    all_reference_keys: set[str] = set()
    for keys in reference_map.values():
        all_reference_keys |= keys

    shared_axis = spine.get("axes", {}).get(subject_axis, {})
    shared_subjects = {
        key
        for key, entry in shared_axis.items()
        if probe_key in entry.get("graphs", {}) and reference_key in entry.get("graphs", {})
    }
    subjects_compared = {s for s in shared_subjects if probe_map.get(s)}

    is_advisory = bool(rule_cfg.get("advisory"))
    caveat = rule_cfg.get("caveat")

    findings: list[dict] = []
    by_subtype: dict[str, int] = {}
    by_severity: dict[str, int] = {}
    subjects_with_findings: set[str] = set()

    for subject_key in subjects_compared:
        subject_reference_keys = reference_map.get(subject_key, set())
        for object_key in probe_map[subject_key]:
            if object_key in subject_reference_keys:
                continue
            classification = classify_miss(object_key, subject_reference_keys, all_reference_keys)
            subtype = classification["subtype"]
            severity = "advisory" if is_advisory else _severity_for(rule_cfg, subtype)
            description = render_description(
                _description_for(rule_cfg, subtype),
                {
                    "object_key": object_key,
                    "subject_key": subject_key,
                    "probe": probe_key,
                    "reference": reference_key,
                    "reference_variants": ", ".join(classification["reference_variants"]),
                },
            )
            evidence = {
                "subject_axis": subject_axis,
                "subject_key": subject_key,
                "object_axis": object_axis,
                "object_key": object_key,
                "probe_graph": probe_key,
                "reference_graph": reference_key,
                "subtype": subtype,
                "probe_nodes": sorted(
                    set(_spine_node_ids(spine, subject_axis, subject_key, probe_key))
                    | set(_spine_node_ids(spine, object_axis, object_key, probe_key))
                ),
                "reference_subject_nodes": sorted(
                    _spine_node_ids(spine, subject_axis, subject_key, reference_key)
                ),
                "reference_object_nodes": sorted(
                    _spine_node_ids(spine, object_axis, object_key, reference_key)
                ),
            }
            if is_advisory and caveat:
                evidence["caveat"] = caveat
            findings.append(
                {
                    "rule_name": name,
                    "type": rule_cfg.get("type", ""),
                    "severity": severity,
                    "description": description,
                    "evidence": evidence,
                }
            )
            by_subtype[subtype] = by_subtype.get(subtype, 0) + 1
            by_severity[severity] = by_severity.get(severity, 0) + 1
            subjects_with_findings.add(subject_key)

    findings.sort(key=lambda f: (f["evidence"]["subject_key"], f["evidence"]["object_key"]))
    stats = {
        "status": "ok",
        "findings": len(findings),
        "subjects_compared": len(subjects_compared),
        "subjects_with_findings": len(subjects_with_findings),
        "by_subtype": by_subtype,
        "by_severity": by_severity,
    }
    return findings, stats


def _run_text_tokens_rule(
    rule_cfg: dict, spine: dict, graphs: dict, node_index: dict
) -> tuple[list[dict], dict]:
    name = rule_cfg["name"]
    subject_axis, object_axis = rule_cfg["subject_axis"], rule_cfg["object_axis"]
    probe_key, reference_key = rule_cfg["probe"], rule_cfg["reference"]
    probe_graph, reference_graph = graphs[probe_key], graphs[reference_key]
    token_cfg = rule_cfg["text_tokens"]

    pattern = token_cfg["token_pattern"]
    min_len = token_cfg["min_token_length"]
    stopwords = set(token_cfg.get("stopwords") or [])
    report_below = token_cfg["report_below"]
    bands = token_cfg["severity_bands"]

    probe_edge = _edge_config(probe_graph, subject_axis, object_axis)
    if probe_edge is None or not probe_edge.get("relations"):
        raise CrosswalkConfigError(
            f"Rule {name!r}: probe graph {probe_key!r} declares no edges "
            f"entry with relations for {subject_axis!r}/{object_axis!r}"
        )
    reference_edge = _edge_config(reference_graph, subject_axis, object_axis)
    if reference_edge is None or not reference_edge.get("text_sources"):
        raise CrosswalkConfigError(
            f"Rule {name!r}: reference graph {reference_key!r} declares no "
            f"edges entry with text_sources for {subject_axis!r}/{object_axis!r}"
        )
    text_sources = reference_edge["text_sources"]

    probe_map = project_edges(
        probe_graph, probe_key, subject_axis, object_axis, node_index, probe_edge["relations"]
    )

    shared_axis = spine.get("axes", {}).get(subject_axis, {})
    shared_subjects = {
        key
        for key, entry in shared_axis.items()
        if probe_key in entry.get("graphs", {}) and reference_key in entry.get("graphs", {})
    }
    subjects_compared = {s for s in shared_subjects if probe_map.get(s)}

    is_advisory = bool(rule_cfg.get("advisory"))
    caveat = rule_cfg.get("caveat")
    description_template = _description_for(rule_cfg, "gap")

    reference_nodes = reference_graph.get("payload", {}).get("nodes") or []
    reference_nodes_by_id = {n["id"]: n for n in reference_nodes}

    findings: list[dict] = []
    by_severity: dict[str, int] = {}
    subjects_with_findings: set[str] = set()
    objects_compared = 0
    objects_covered = 0

    for subject_key in subjects_compared:
        reference_node_ids = _spine_node_ids(spine, subject_axis, subject_key, reference_key)
        text_parts: list[str] = []
        for node_id in reference_node_ids:
            node = reference_nodes_by_id.get(node_id)
            if node is None:
                continue
            for source in text_sources:
                text_parts.extend(source_candidates(node, source))
        reference_text = " ".join(text_parts)
        reference_tokens = tokenize(reference_text, pattern, min_len, stopwords)

        for object_key in probe_map[subject_key]:
            objects_compared += 1
            probe_tokens = tokenize(object_key, pattern, min_len, stopwords)
            ratio = coverage_ratio(probe_tokens, reference_tokens)
            if ratio >= report_below:
                objects_covered += 1
                continue
            severity = "advisory" if is_advisory else resolve_band(ratio, bands)
            description = render_description(
                description_template,
                {
                    "object_key": object_key,
                    "subject_key": subject_key,
                    "probe": probe_key,
                    "reference": reference_key,
                    "coverage_ratio": round(ratio, 3),
                },
            )
            evidence = {
                "subject_axis": subject_axis,
                "subject_key": subject_key,
                "object_axis": object_axis,
                "object_key": object_key,
                "probe_graph": probe_key,
                "reference_graph": reference_key,
                "subtype": "gap",
                "probe_nodes": sorted(_spine_node_ids(spine, subject_axis, subject_key, probe_key)),
                "reference_subject_nodes": sorted(reference_node_ids),
                "reference_object_nodes": [],
                "coverage_ratio": round(ratio, 3),
            }
            if is_advisory and caveat:
                evidence["caveat"] = caveat
            findings.append(
                {
                    "rule_name": name,
                    "type": rule_cfg.get("type", ""),
                    "severity": severity,
                    "description": description,
                    "evidence": evidence,
                }
            )
            by_severity[severity] = by_severity.get(severity, 0) + 1
            subjects_with_findings.add(subject_key)

    findings.sort(key=lambda f: (f["evidence"]["subject_key"], f["evidence"]["object_key"]))
    stats = {
        "status": "ok",
        "findings": len(findings),
        "subjects_compared": len(subjects_compared),
        "subjects_with_findings": len(subjects_with_findings),
        "objects_compared": objects_compared,
        "objects_covered": objects_covered,
        "by_severity": by_severity,
    }
    return findings, stats


def run_rule(
    rule_cfg: dict, spine: dict, graphs: dict, node_index: dict
) -> tuple[list[dict], dict]:
    """Run one rule (already eagerly validated by load_rules_spec) and
    return ``(findings, stats)``. Raises on any runtime failure -- callers
    that want per-rule isolation must catch around this (see run_rules)."""
    compare_mode = rule_cfg["compare"]
    if compare_mode == "spine_keys":
        return _run_spine_keys_rule(rule_cfg, spine, graphs, node_index)
    if compare_mode == "text_tokens":
        return _run_text_tokens_rule(rule_cfg, spine, graphs, node_index)
    raise CrosswalkConfigError(f"Unknown compare mode {compare_mode!r}")  # pragma: no cover


def run_rules(rules_spec: dict, spine: dict, graphs: dict, include_advisory: bool) -> dict:
    """Run every rule in a loaded (validated) rules spec, isolating
    failures per rule -- one raising rule records an error status and the
    remaining rules still produce findings, mirroring the isolation
    core/label_epistemic.py already uses for its single-graph CUSTOM_RULES.

    A rule flagged ``advisory: true`` is skipped entirely unless
    ``include_advisory`` is set: its stats slot records status
    'skipped-advisory' and it gets NO key at all in custom_findings, so an
    un-opted-in run cannot be mistaken for a zero-signal one.
    """
    node_index = build_axis_node_index(spine)
    custom_findings: dict[str, list[dict]] = {}
    stats: dict[str, dict] = {}

    if isinstance(rules_spec, dict) and "rules" in rules_spec:
        rules = rules_spec["rules"]
    else:
        rules = rules_spec
    for rule_cfg in rules:
        name = rule_cfg["name"]
        if rule_cfg.get("advisory") and not include_advisory:
            stats[name] = {"status": "skipped-advisory"}
            continue
        try:
            findings, rule_stats = run_rule(rule_cfg, spine, graphs, node_index)
            custom_findings[name] = findings
            stats[name] = rule_stats
        except Exception as e:  # noqa: BLE001 — rule isolation is the whole point
            error_message = str(e)
            custom_findings[name] = [
                {"rule_name": name, "status": "error", "error": error_message}
            ]
            stats[name] = {"status": "error", "error": error_message}

    return {"custom_findings": custom_findings, "stats": stats}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cross_domain", description="Run cross-domain epistemic rules over a spine.json"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_analyze = sub.add_parser("analyze", help="Run the rules spec over a spine and its graphs")
    p_analyze.add_argument("--spine", required=True, help="Path to spine.json")
    p_analyze.add_argument("--rules", required=True, help="Path to the rules spec YAML")
    p_analyze.add_argument(
        "--graph",
        action="append",
        dest="graphs",
        default=[],
        help="NAME=DIR -- repeatable, overrides a spine-recorded graph directory",
    )
    p_analyze.add_argument(
        "--out", default="cross_domain_findings.json", help="Output findings JSON path"
    )
    p_analyze.add_argument(
        "--include-advisory",
        action="store_true",
        help="Opt into advisory-only rules (skipped by default)",
    )
    p_analyze.add_argument("--json", action="store_true", help="Print the stats block to stdout")
    p_analyze.set_defaults(func=_cmd_analyze)

    return parser


def _cmd_analyze(args: argparse.Namespace) -> int:
    try:
        spine = load_spine(args.spine)
        rules_spec = load_rules_spec(args.rules, spine)
        graph_specs = resolve_graph_specs(spine, args.graphs)
        graphs = load_graphs(graph_specs)
        graphs = attach_domain_configs(graphs)
        result = run_rules(rules_spec, spine, graphs, include_advisory=args.include_advisory)
    except CrosswalkConfigError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    payload = {
        "cross_domain_version": "1.0",
        "generated_at": datetime.now(UTC).isoformat(),
        "spine": str(Path(args.spine).resolve()),
        "graphs": {key: str(graph["dir"]) for key, graph in graphs.items()},
        "super_domain": {"custom_findings": result["custom_findings"]},
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
