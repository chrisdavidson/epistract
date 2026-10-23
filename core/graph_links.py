"""Shared link helpers for the workbench's per-graph counts.

``core/document_stats.py`` (the Dashboard's Documents table) and
``core/dashboard_start.py`` (the "Where to start" hubs) count knowledge
relations with one rule, defined here so the two can never disagree:

- ``EXCLUDED_RELATIONS`` are provenance, never knowledge: the graph_display
  source edges (``MENTIONED_IN``) plus ``PUBLISHED_IN``.
- ``DOC_PREFIX`` marks a document node id (``doc:<id>``).
- ``endpoint`` / ``relation_type`` / ``relation_key`` read a link's ends, its
  relation type and its identity tolerantly (ids or ``{"id": ...}`` ends, a
  missing ``relation_type`` recovered from ``relation_id``).

This module is pure and never raises on malformed links.
"""

from __future__ import annotations

from core.graph_display import SOURCE_EDGE_RELATIONS

# PUBLISHED_IN is provenance (a link to a publication node) but, unlike
# MENTIONED_IN, graph_display does not treat it as a source edge.
EXCLUDED_RELATIONS = SOURCE_EDGE_RELATIONS | {"PUBLISHED_IN"}

DOC_PREFIX = "doc:"


def endpoint(value: object) -> str:
    """Return the node id of a link end given as an id or as ``{"id": ...}``."""
    if isinstance(value, dict):
        value = value.get("id")
    return value if isinstance(value, str) else ""


def relation_type(link: dict) -> str:
    """Return the link's relation type, falling back to the middle of its id."""
    rtype = link.get("relation_type")
    if isinstance(rtype, str) and rtype:
        return rtype
    rid = link.get("relation_id")
    if isinstance(rid, str):
        parts = rid.split("|")
        if len(parts) >= 3:
            return parts[1]
    return ""


def relation_key(link: dict, rtype: str) -> str:
    """Return the link's identity: its ``relation_id``, else ``source|type|target``.

    Returns '' when the link has neither an id nor both ends.
    """
    rid = link.get("relation_id")
    if isinstance(rid, str) and rid:
        return rid
    source, target = endpoint(link.get("source")), endpoint(link.get("target"))
    if not source or not target:
        return ""
    return f"{source}|{rtype}|{target}"
