"""Graph payload builders shared by the workbench API and the static graph.html.

Both surfaces serve the same JSON to the same browser modules, so the payloads
are built here once. This module is pure: no FastAPI, no file or network access.
"""

from __future__ import annotations

import json

from core.graph_display import entity_type_key, is_source_edge


class EntityLookupError(ValueError):
    """A ``--neighborhood`` query matched no node or several nodes."""


def json_for_script(value: object) -> str:
    """Serialize value as JSON that is safe to embed inside an HTML <script> block.

    ``json.dumps`` leaves ``<``, ``>`` and ``&`` intact, so a string such as
    ``</script><script>...`` (an LLM-extracted entity type, for example) would
    close the script element. Escaping them as ``\\u`` sequences keeps the
    value identical once parsed by JavaScript. U+2028/U+2029 are escaped too,
    since older JavaScript engines treat them as line terminators.

    Args:
        value: Any JSON-serializable value.

    Returns:
        The JSON text with HTML-significant characters escaped.
    """
    return (
        json.dumps(value)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
        .replace(" ", "\\u2028")
        .replace(" ", "\\u2029")
    )


def entity_types_payload(nodes: list[dict], display: dict) -> dict:
    """Build the ``/api/graph/entity-types`` payload.

    Counts nodes per resolved entity type and attaches each type's resolved
    display (color, shape, family, ``is_source``) plus the family, relation and
    category tables. The frontend only reads these values.

    Args:
        nodes: Graph nodes (each may carry an ``entity_type``).
        display: Result of ``core.graph_display.resolve_display``.

    Returns:
        ``{"entity_types", "types", "families", "relations", "categories"}``.
    """
    type_counts: dict[str, int] = {}
    for node in nodes:
        t = entity_type_key(node.get("entity_type"))
        type_counts[t] = type_counts.get(t, 0) + 1
    types = []
    for t, count in type_counts.items():
        # Every observed type was resolved from the same nodes (same key
        # function), so a miss means the data changed underneath us; skip it
        # rather than resolve a type in isolation (which would collide with the
        # first palette color).
        spec = display["types"].get(t)
        if spec is None:
            continue
        entry = {k: v for k, v in spec.items() if k != "origin"}
        types.append({**entry, "type": t, "count": count})
    return {
        "entity_types": type_counts,
        "types": types,
        "families": display["families"],
        "relations": display["relations"],
        "categories": display["categories"],
    }


def claims_payload(claims_layer: dict) -> dict:
    """Build the ``/api/graph/claims`` payload from a claims layer.

    Reshapes the nested claims_layer structure into the flat format the
    frontend expects. ``custom_findings`` is the channel both the per-domain
    ``CUSTOM_RULES`` hook (``core/label_epistemic.py``) and the cross-domain
    rules engine (``core/cross_domain.py``) write to, keyed by rule name;
    ``findings`` is the same data flattened into one severity-bearing list.

    Args:
        claims_layer: Parsed claims_layer.json (``{}`` when absent).

    Returns:
        ``{"conflicts", "gaps", "risks", "cross_references", "custom_findings",
        "findings"}``.
    """
    sd = claims_layer.get("super_domain", {})
    custom_findings = sd.get("custom_findings", {}) or {}

    flattened: list[dict] = []
    for rule_name, rule_findings in custom_findings.items():
        if not isinstance(rule_findings, list):
            continue
        for f in rule_findings:
            if isinstance(f, dict):
                flattened.append({"rule_name": rule_name, **f})

    return {
        "conflicts": sd.get("conflicts", []),
        "gaps": sd.get("coverage_gaps", []),
        "risks": sd.get("risks", []),
        "cross_references": sd.get("cross_contract_entities", []),
        "custom_findings": custom_findings,
        "findings": flattened,
    }


def subset_graph(
    nodes: list[dict],
    links: list[dict],
    display: dict,
    *,
    neighborhood: str | None = None,
    top_n: int | None = None,
    depth: int = 1,
) -> tuple[list[dict], list[dict], dict | None]:
    """Reduce a graph to a neighbourhood or its best-connected entities.

    Mirrors sift-kg's ``filter_graph`` matching and ranking rules, with two
    deliberate differences: degree and adjacency use knowledge edges only
    (provenance edges to source nodes never rank a hub or bridge two entities),
    and every source node attached to a kept node is kept so Show sources still
    works on the subset. Links whose endpoints are not both kept are dropped.
    When both filters are given, ``neighborhood`` wins.

    Args:
        nodes: Graph nodes (``id``, ``name``, ``entity_type``).
        links: Graph links (``source``, ``target``, ``relation_type``).
        display: Result of ``core.graph_display.resolve_display`` over the
            full graph (decides which nodes are sources).
        neighborhood: Node id, or case-insensitive name, to center on.
        top_n: Keep the N nodes of highest knowledge degree and their neighbors
            (must be >= 1).
        depth: Hop radius for ``neighborhood`` (must be >= 1).

    Returns:
        ``(kept_nodes, kept_links, info)`` in input order. ``info`` is None
        without filters, else ``{"mode", "name", "depth", "top_n", "shown",
        "total"}`` where shown/total count all nodes including sources.

    Raises:
        EntityLookupError: When ``neighborhood`` matches no node or several nodes.
        ValueError: When ``top_n`` or ``depth`` is below 1.
    """
    # depth 0 would be the start node alone, which is not a neighbourhood.
    if top_n is not None and top_n < 1:
        raise ValueError(f"top_n must be >= 1, got {top_n}")
    if depth < 1:
        raise ValueError(f"depth must be >= 1, got {depth}")
    if neighborhood is None and top_n is None:
        return nodes, links, None

    types = display.get("types", {})
    source_ids = {
        n["id"]
        for n in nodes
        if types.get(entity_type_key(n.get("entity_type")), {}).get("is_source")
    }
    relations = display.get("relations", {})
    adjacency: dict[str, set[str]] = {n["id"]: set() for n in nodes}
    for link in links:
        src, tgt = link.get("source"), link.get("target")
        if src not in adjacency or tgt not in adjacency:
            continue
        if is_source_edge(link, source_ids, relations):
            continue
        adjacency[src].add(tgt)
        adjacency[tgt].add(src)

    by_id = {n["id"]: n for n in nodes}
    name: str | None = None
    if neighborhood is not None:
        start = neighborhood
        if start not in by_id:
            query = neighborhood.lower()
            matches = [n["id"] for n in nodes if str(n.get("name") or "").lower() == query]
            if len(matches) == 1:
                start = matches[0]
            elif matches:
                raise EntityLookupError(
                    f"Multiple entities match {neighborhood!r}: {', '.join(matches)}. "
                    "Use the full entity ID instead."
                )
            else:
                raise EntityLookupError(
                    f"Entity {neighborhood!r} not found in graph. "
                    "Use entity ID (e.g. 'person:alice') or display name."
                )
        name = by_id[start].get("name") or start
        keep = {start}
        frontier = {start}
        for _ in range(depth):
            frontier = {nb for node in frontier for nb in adjacency[node]} - keep
            keep |= frontier
        mode = "neighborhood"
    else:
        ranked = sorted(
            (i for i in adjacency if i not in source_ids),
            key=lambda i: (-len(adjacency[i]), i),
        )
        hubs = set(ranked[:top_n])
        keep = set(hubs)
        for hub in hubs:
            keep |= adjacency[hub]
        mode = "top"

    # Sources attached to any kept node ride along.
    for link in links:
        src, tgt = link.get("source"), link.get("target")
        if src in keep and tgt in source_ids:
            keep.add(tgt)
        if tgt in keep and src in source_ids:
            keep.add(src)

    kept_nodes = [n for n in nodes if n["id"] in keep]
    kept_links = [lk for lk in links if lk.get("source") in keep and lk.get("target") in keep]
    info = {
        "mode": mode,
        "name": name,
        "depth": depth,
        "top_n": top_n if mode == "top" else None,
        "shown": len(kept_nodes),
        "total": len(nodes),
    }
    return kept_nodes, kept_links, info
