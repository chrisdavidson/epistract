"""Graph payload builders shared by the workbench API and the static graph.html.

Both surfaces serve the same JSON to the same browser modules, so the payloads
are built here once. This module is pure: no FastAPI, no file or network access.
"""

from __future__ import annotations

import json

from core.graph_display import entity_type_key


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
