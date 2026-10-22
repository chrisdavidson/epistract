"""Where-to-start data for the workbench Dashboard: topic communities and hubs.

``build_start_here`` returns ``{"communities": [...], "hubs": [...]}``.

Each topic community is one row::

    {id, label, full_label, member_count, top_members}

taken from the cluster groups of the ``/api/graph/groups`` payload, so the ids
are exactly the regions the graph draws. The ``other`` (Unclustered) group is
never listed. ``member_count`` is the group's ``size`` (knowledge nodes only);
``top_members`` holds up to three member names, most connected first. Rows are
sorted by member count (descending), then label (case-insensitive), then id.
When the cluster mode is unavailable the list is empty.

Each hub entity is one row::

    {id, name, entity_type, connections, community_id, community_label}

for the ten most-connected knowledge entities. ``connections`` is the number of
distinct knowledge relations touching the node: ``MENTIONED_IN`` and
``PUBLISHED_IN`` links, relations the display marks as ``source_edge``, links
touching a source node (a display source type, DOCUMENT/PUBLICATION, or a
``doc:<id>`` node) and links to unknown nodes never count; a self-loop counts
once. Rows are sorted by connections (descending), then name
(case-insensitive), then id; entities with no connections are never listed.
``community_id`` / ``community_label`` are ``None`` for unclustered entities.

This module is pure: no FastAPI, no file or network access. It never raises;
input that is missing, ``None`` or malformed is skipped. Strings are returned
verbatim (escaping is the renderer's job).
"""

from __future__ import annotations

from core.graph_display import SOURCE_EDGE_RELATIONS, entity_type_key
from core.graph_groups import OTHER_GROUP_ID, _is_source

# Most hub entities listed.
MAX_HUBS = 10
# Most member names shown per topic community.
MAX_TOP_MEMBERS = 3
# PUBLISHED_IN is provenance (a link to a publication node) but, unlike
# MENTIONED_IN, graph_display does not treat it as a source edge.
EXCLUDED_RELATIONS = SOURCE_EDGE_RELATIONS | {"PUBLISHED_IN"}

DOC_PREFIX = "doc:"


# ---------------------------------------------------------------------------
# Links
# ---------------------------------------------------------------------------


def _endpoint(value: object) -> str:
    """Return the node id of a link end given as an id or as ``{"id": ...}``."""
    if isinstance(value, dict):
        value = value.get("id")
    return value if isinstance(value, str) else ""


def _relation_type(link: dict) -> str:
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


def _relation_key(link: dict, rtype: str) -> str:
    rid = link.get("relation_id")
    if isinstance(rid, str) and rid:
        return rid
    source, target = _endpoint(link.get("source")), _endpoint(link.get("target"))
    if not source or not target:
        return ""
    return f"{source}|{rtype}|{target}"


def _source_edge_relations(display: dict | None) -> set[str]:
    """Relation names the display marks as ``source_edge``."""
    relations = display.get("relations") if isinstance(display, dict) else None
    if not isinstance(relations, dict):
        return set()
    return {
        name
        for name, spec in relations.items()
        if isinstance(name, str) and isinstance(spec, dict) and spec.get("source_edge") is True
    }


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------


def _text(value: object) -> str:
    """Return a non-blank string verbatim; anything else becomes ''."""
    return value if isinstance(value, str) and value.strip() else ""


def _name(node_id: str, index: dict[str, dict]) -> str:
    node = index.get(node_id)
    if node is not None:
        name = _text(node.get("name")) or _text(node.get("label"))
        if name:
            return name
    return node_id.split(":", 1)[-1].replace("_", " ")


def _knowledge_index(nodes: object, display: dict | None) -> dict[str, dict]:
    """Return ``{id: node}`` for the non-source nodes with a string id."""
    index: dict[str, dict] = {}
    for node in nodes if isinstance(nodes, list) else []:
        if not isinstance(node, dict):
            continue
        node_id = node.get("id")
        if not isinstance(node_id, str) or not node_id or node_id in index:
            continue
        if node_id.startswith(DOC_PREFIX) or _is_source(node, display):
            continue
        index[node_id] = node
    return index


def _connections(links: object, index: dict[str, dict], display: dict | None) -> dict[str, int]:
    """Count distinct knowledge relations per knowledge node."""
    skipped = EXCLUDED_RELATIONS | _source_edge_relations(display)
    keys: dict[str, set[str]] = {}
    for link in links if isinstance(links, list) else []:
        if not isinstance(link, dict):
            continue
        rtype = _relation_type(link)
        if rtype in skipped:
            continue
        ends = (_endpoint(link.get("source")), _endpoint(link.get("target")))
        # Both ends must be known knowledge nodes: this also drops links that
        # touch a source node and links to nodes missing from the graph.
        if not all(end in index for end in ends):
            continue
        key = _relation_key(link, rtype)
        if not key:
            continue
        for end in ends:
            keys.setdefault(end, set()).add(key)
    return {node_id: len(found) for node_id, found in keys.items()}


# ---------------------------------------------------------------------------
# Groups
# ---------------------------------------------------------------------------


def _cluster_entry(groups_payload: object) -> dict | None:
    """Return the available cluster mode of the groups payload, or None."""
    modes = groups_payload.get("modes") if isinstance(groups_payload, dict) else None
    cluster = modes.get("cluster") if isinstance(modes, dict) else None
    if not isinstance(cluster, dict) or cluster.get("available") is not True:
        return None
    if not isinstance(cluster.get("groups"), list):
        return None
    return cluster


def _community_rows(cluster: dict | None) -> dict[str, dict]:
    """Return ``{gid: row}`` for the real (non-``other``) cluster groups."""
    rows: dict[str, dict] = {}
    if cluster is None:
        return rows
    for group in cluster["groups"]:
        if not isinstance(group, dict):
            continue
        gid = group.get("id")
        if not isinstance(gid, str) or not gid or gid == OTHER_GROUP_ID or gid in rows:
            continue
        label = _text(group.get("label")) or _text(group.get("full_label")) or gid
        full_label = _text(group.get("full_label")) or label
        size = group.get("size")
        member_count = size if isinstance(size, int) and not isinstance(size, bool) else 0
        rows[gid] = {
            "id": gid,
            "label": label,
            "full_label": full_label,
            "member_count": max(member_count, 0),
            "top_members": [],
        }
    return rows


def _assignment(cluster: dict | None, index: dict[str, dict], gids: set[str]) -> dict[str, str]:
    """Return the cluster assignment limited to knowledge nodes and real groups."""
    raw = cluster.get("assignment") if cluster is not None else None
    if not isinstance(raw, dict):
        return {}
    return {
        node_id: gid
        for node_id, gid in raw.items()
        if isinstance(node_id, str) and node_id in index and isinstance(gid, str) and gid in gids
    }


# ---------------------------------------------------------------------------
# Public
# ---------------------------------------------------------------------------


def build_start_here(
    nodes: list[dict] | None,
    links: list[dict] | None,
    groups_payload: dict | None,
    display: dict | None = None,
) -> dict:
    """Return the topic communities and hub entities of a graph.

    Args:
        nodes: Graph nodes (``id``, ``entity_type``, ``name``/``label``).
        links: Graph links (``source``, ``target``, ``relation_type``,
            ``relation_id``); ends may be ids or ``{"id": ...}`` dicts.
        groups_payload: The ``/api/graph/groups`` payload (``build_groups``).
        display: The ``resolve_display`` result, for source types and
            ``source_edge`` relations; ``None`` falls back to the defaults.

    Returns:
        ``{"communities": [row, ...], "hubs": [row, ...]}`` as described in
        the module docstring. Never raises.
    """
    display = display if isinstance(display, dict) else None
    index = _knowledge_index(nodes, display)
    counts = _connections(links, index, display)

    def rank(node_id: str) -> tuple[int, str, str]:
        return (-counts.get(node_id, 0), _name(node_id, index).lower(), node_id)

    cluster = _cluster_entry(groups_payload)
    rows = _community_rows(cluster)
    assignment = _assignment(cluster, index, set(rows))

    members: dict[str, list[str]] = {}
    for node_id, gid in assignment.items():
        if counts.get(node_id, 0) > 0:
            members.setdefault(gid, []).append(node_id)
    for gid, ids in members.items():
        ids.sort(key=rank)
        rows[gid]["top_members"] = [_name(n, index) for n in ids[:MAX_TOP_MEMBERS]]

    communities = sorted(
        rows.values(), key=lambda r: (-r["member_count"], r["label"].lower(), r["id"])
    )

    hubs = []
    for node_id in sorted((n for n in counts if counts[n] > 0), key=rank)[:MAX_HUBS]:
        node = index[node_id]
        gid = assignment.get(node_id)
        hubs.append(
            {
                "id": node_id,
                "name": _name(node_id, index),
                "entity_type": entity_type_key(node.get("entity_type")),
                "connections": counts[node_id],
                "community_id": gid,
                "community_label": rows[gid]["label"] if gid is not None else None,
            }
        )
    return {"communities": communities, "hubs": hubs}
