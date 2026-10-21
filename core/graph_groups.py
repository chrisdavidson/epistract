"""Group assignment for the workbench graph: topic clusters and entity families.

This module is import-light on purpose (standard library plus
``core.graph_display``): the workbench API serves its output at
``GET /api/graph/groups``. It lives in ``core`` so the static
``/epistract:view`` graph can reuse ``build_groups`` (planned for Phase 5;
the workbench is the only caller today) and group a graph the same way.

Three public functions, none of which raise on malformed input:

* ``normalize_communities``: turn the two ``communities.json`` shapes (and the
  per-node ``community`` field) into one ``{node_id: label}`` mapping.
* ``short_label``: derive a short readable region label from a long community
  label at display time (``label_communities.py`` output is unchanged).
* ``build_groups``: produce the payload with a ``cluster`` and a ``family``
  mode, per-mode availability, the default mode and the node assignment.
"""

from __future__ import annotations

import re
from collections import Counter

from core.graph_display import OTHER_FAMILY, SOURCES_FAMILY, entity_type_key

# Longest short label shown on a region (characters, including a trailing ellipsis).
MAX_SHORT_LABEL = 24
# Longest full label kept for tooltips (characters).
MAX_FULL_LABEL = 200
# Largest number of topic-cluster groups; smaller communities join Unclustered.
MAX_CLUSTER_GROUPS = 100
# Group id for knowledge nodes that belong to no topic cluster.
OTHER_GROUP_ID = "other"
# Label shown for the group of knowledge nodes without a topic cluster.
OTHER_GROUP_LABEL = "Unclustered"
# Wider budgets tried when shortened labels collide (results must still fit MAX_SHORT_LABEL).
COLLISION_BUDGETS = (30, 36)
# Prefix of family group ids.
FAMILY_ID_PREFIX = "f:"
# Entity types treated as sources when no display resolution is available.
DEFAULT_SOURCE_TYPES = frozenset({"DOCUMENT", "PUBLICATION"})

# Availability reasons shown by the grouping control.
REASON_NO_CLUSTERS = "No topic clusters in this project"
REASON_ONE_CLUSTER = "Only one topic cluster found"
REASON_NO_FAMILIES = "No entity families defined for this domain"

_TRAILING_PAREN = re.compile(r"\s*\([^)]*\)\s*$")
_MORE_SUFFIX = re.compile(r"\s*\+\s*(\d+)\s+more\s*$", re.IGNORECASE)
_TRIM_CHARS = " ,:;-/&"


# ---------------------------------------------------------------------------
# Labels
# ---------------------------------------------------------------------------


def _collapse(value: object) -> str:
    """Return ``value`` as a whitespace-collapsed string ('' for None)."""
    if value is None:
        return ""
    return " ".join(str(value).split())


def _truncate(text: str, max_len: int) -> str:
    """Cut at a word boundary (when past half the budget) and add an ellipsis."""
    if len(text) <= max_len:
        return text
    cut = text[: max_len - 1].rstrip()
    space = cut.rfind(" ")
    if space >= int(max_len * 0.5):
        cut = cut[:space].rstrip(_TRIM_CHARS)
    return cut + "…"


def _strip_paren(part: str) -> str:
    stripped = _TRAILING_PAREN.sub("", part).strip()
    return stripped or part


def short_label(label: object, max_len: int = MAX_SHORT_LABEL) -> str:
    """Return a deterministic short form of a community label.

    Keeps the label when it fits; otherwise takes the head before `` — ``,
    joins its `` / `` parts while they fit (one trailing parenthetical stripped
    per part) and falls back to a word-boundary truncation with an ellipsis. A
    trailing `` + N more`` is kept as a compact `` +N`` suffix. Never returns
    an empty string and never exceeds ``max_len``.
    """
    text = _collapse(label)
    if not text:
        return "Cluster"
    if len(text) <= max_len:
        return text
    suffix = ""
    more = _MORE_SUFFIX.search(text)
    if more:
        candidate = f" +{more.group(1)}"
        base = text[: more.start()].strip()
        if base and len(candidate) < max_len - 4:
            text, suffix = base, candidate
    budget = max_len - len(suffix)
    if len(text) > budget:
        head = text.split(" — ")[0]
        parts = [_strip_paren(p.strip()) for p in head.split(" / ") if p.strip()]
        if not parts:
            result = _truncate(text, budget)
        else:
            out = parts[0]
            for part in parts[1:]:
                if len(out) + 3 + len(part) <= budget:
                    out += " / " + part
                else:
                    break
            result = _truncate(out, budget)
    else:
        result = text
    return (result + suffix) or "Cluster"


def _full_label(label: object) -> str:
    return _collapse(label)[:MAX_FULL_LABEL]


def _unique_short_labels(groups: list[dict]) -> None:
    """Fill ``label`` on ``groups`` (sorted by size desc) so labels are unique.

    The largest group keeps a contested label; the others are retried with the
    wider budgets (kept only if they still fit ``MAX_SHORT_LABEL`` and are
    unique), then given a numeric suffix in size order.
    """
    used: set[str] = {OTHER_GROUP_LABEL}
    for group in groups:
        if group["id"] == OTHER_GROUP_ID:
            group["label"] = OTHER_GROUP_LABEL
    pending = [g for g in groups if g["id"] != OTHER_GROUP_ID]
    for group in pending:
        group["label"] = short_label(group["full_label"])
    for group in pending:
        label = group["label"]
        if label in used:
            label = _disambiguate(group["full_label"], label, used)
        group["label"] = label
        used.add(label)


def _disambiguate(full_label: str, label: str, used: set[str]) -> str:
    """Return a label not in ``used``: a wider-budget form, else a numeric suffix."""
    for budget in COLLISION_BUDGETS:
        candidate = short_label(full_label, budget)
        if len(candidate) <= MAX_SHORT_LABEL and candidate not in used:
            return candidate
    n = 2
    while True:
        tail = f" {n}"
        candidate = _truncate(label, MAX_SHORT_LABEL - len(tail)) + tail
        if candidate not in used:
            return candidate
        n += 1


# ---------------------------------------------------------------------------
# Community normalization
# ---------------------------------------------------------------------------


def _node_ids(nodes: object) -> list[dict]:
    if not isinstance(nodes, list):
        return []
    return [n for n in nodes if isinstance(n, dict) and n.get("id") is not None]


def _ranked_communities(raw: object, nodes: list[dict]) -> list[tuple[str, list[str]]]:
    """Return ``[(label, member_ids)]`` per community, largest first.

    One entry per community *identity*: each list-shape entry is its own
    community even when its label repeats another's. The flat
    ``{node_id: label}`` shape (and the per-node ``community`` field) carries
    no identity beyond the label, so equal flat labels are one community; a
    ``community`` field whose label matches a list entry joins that entry.
    Empty labels become ``Cluster N`` (N = size rank).
    """
    # identity key -> members; ("list", index) for list entries, ("flat", label) otherwise.
    members: dict[object, list[str]] = {}
    labels: dict[object, str] = {}
    listed_key_for_label: dict[str, object] = {}

    def add(key: object, label: str, node_id: str) -> None:
        members.setdefault(key, []).append(node_id)
        labels[key] = label

    covered: set[str] = set()
    if isinstance(raw, dict):
        # "communities" is the list shape's reserved key, never a node id.
        if "communities" in raw:
            listed = raw["communities"] if isinstance(raw["communities"], list) else []
            for index, entry in enumerate(listed):
                if not isinstance(entry, dict) or not isinstance(entry.get("members"), list):
                    continue
                label = _collapse(entry.get("label"))
                listed_key_for_label.setdefault(label, ("list", index))
                for member in entry["members"]:
                    if isinstance(member, (str, int)) and str(member) not in covered:
                        covered.add(str(member))
                        add(("list", index), label, str(member))
        else:
            for node_id, value in raw.items():
                if isinstance(value, (dict, list)) or value is None:
                    continue
                label = _collapse(value)
                covered.add(str(node_id))
                add(("flat", label), label, str(node_id))
    for node in _node_ids(nodes):
        node_id = str(node["id"])
        if node_id in covered:
            continue
        value = node.get("community")
        if value is None or isinstance(value, (dict, list)):
            continue
        label = _collapse(value)
        covered.add(node_id)
        add(listed_key_for_label.get(label, ("flat", label)), label, node_id)

    ranked = sorted(members, key=lambda k: (-len(members[k]), labels[k], str(k)))
    return [
        (labels[key] or f"Cluster {rank}", members[key]) for rank, key in enumerate(ranked, start=1)
    ]


def normalize_communities(raw: object, nodes: list[dict]) -> dict[str, str]:
    """Return ``{node_id: label}`` from either ``communities.json`` shape.

    Accepts the flat ``{node_id: label}`` map and the
    ``{"communities": [{"id", "label", "members"}]}`` list shape. Nodes not
    covered fall back to their own ``community`` field. Non-string labels are
    stringified; empty labels become ``Cluster N`` (N = size rank). Anything
    unusable yields ``{}``. Grouping uses the community identity, not this
    label map (two list entries may share a label).
    """
    return {node_id: label for label, ids in _ranked_communities(raw, nodes) for node_id in ids}


# ---------------------------------------------------------------------------
# Group building
# ---------------------------------------------------------------------------


def _is_source(node: dict, display: dict | None) -> bool:
    key = entity_type_key(node.get("entity_type"))
    types = display.get("types") if isinstance(display, dict) else None
    if isinstance(types, dict) and isinstance(types.get(key), dict):
        return bool(types[key].get("is_source"))
    return key in DEFAULT_SOURCE_TYPES


def _unavailable(reason: str) -> dict:
    return {"available": False, "reason": reason, "groups": [], "assignment": {}}


def _finish_mode(groups: dict[str, dict], assignment: dict[str, str]) -> dict:
    """Order groups, assign unique short labels and package one mode."""
    ordered = sorted(
        (g for g in groups.values() if g["id"] != OTHER_GROUP_ID),
        key=lambda g: (-g["size"], g["full_label"], g["id"]),
    )
    if OTHER_GROUP_ID in groups:
        ordered.append(groups[OTHER_GROUP_ID])
    return {"available": True, "reason": None, "ordered": ordered, "assignment": assignment}


def _cluster_mode(knowledge: list[str], communities: list[tuple[str, list[str]]]) -> dict:
    """Topic-cluster mode: one group per community identity (not per label).

    Distinct communities that share a label stay distinct groups;
    ``_unique_short_labels`` later tells their short labels apart.
    """
    member_of = {node_id: i for i, (_, ids) in enumerate(communities) for node_id in ids}
    by_comm: dict[int, list[str]] = {}
    for node_id in knowledge:
        index = member_of.get(node_id)
        if index is not None:
            by_comm.setdefault(index, []).append(node_id)
    if not by_comm:
        return _unavailable(REASON_NO_CLUSTERS)
    if len(by_comm) < 2:
        return _unavailable(REASON_ONE_CLUSTER)
    ranked = sorted(by_comm, key=lambda i: (-len(by_comm[i]), _full_label(communities[i][0]), i))
    kept = ranked[:MAX_CLUSTER_GROUPS]
    groups: dict[str, dict] = {}
    assignment: dict[str, str] = {}
    for rank, comm in enumerate(kept, start=1):
        gid = f"c{rank}"
        groups[gid] = {
            "id": gid,
            "label": "",
            "full_label": _full_label(communities[comm][0]),
            "size": len(by_comm[comm]),
        }
        for node_id in by_comm[comm]:
            assignment[node_id] = gid
    leftover = [n for n in knowledge if n not in assignment]
    if leftover:
        groups[OTHER_GROUP_ID] = {
            "id": OTHER_GROUP_ID,
            "label": OTHER_GROUP_LABEL,
            "full_label": OTHER_GROUP_LABEL,
            "size": len(leftover),
        }
        for node_id in leftover:
            assignment[node_id] = OTHER_GROUP_ID
    return _finish_mode(groups, assignment)


def _family_mode(knowledge: list[dict], display: dict | None) -> dict:
    types = display.get("types") if isinstance(display, dict) else None
    groups: dict[str, dict] = {}
    assignment: dict[str, str] = {}
    for node in knowledge:
        spec = (
            types.get(entity_type_key(node.get("entity_type"))) if isinstance(types, dict) else None
        )
        family = _collapse(spec.get("family")) if isinstance(spec, dict) else ""
        if not family or family == SOURCES_FAMILY:
            family = OTHER_FAMILY
        gid = FAMILY_ID_PREFIX + family.lower()
        group = groups.setdefault(
            gid, {"id": gid, "label": "", "full_label": _full_label(family), "size": 0}
        )
        group["size"] += 1
        assignment[str(node["id"])] = gid
    if len(groups) < 2:
        return _unavailable(REASON_NO_FAMILIES)
    return _finish_mode(groups, assignment)


def _assign_sources(
    mode: dict, sources: list[str], neighbours: dict[str, list[str]], sizes: dict[str, int]
) -> None:
    """Give each source the plurality group of its non-source neighbours."""
    assignment = mode["assignment"]
    additions: dict[str, str] = {}
    for source_id in sources:
        votes = Counter(assignment[n] for n in neighbours.get(source_id, ()) if n in assignment)
        if not votes:
            continue
        best = min(votes, key=lambda g: (-votes[g], -sizes.get(g, 0), g))
        additions[source_id] = best
    assignment.update(additions)


def build_groups(
    nodes: list[dict],
    links: list[dict],
    communities: object,
    display: dict | None = None,
) -> dict:
    """Return the ``/api/graph/groups`` payload.

    ``{"default": "cluster"|"family"|"none", "modes": {"cluster": mode,
    "family": mode}}`` where each mode is ``{"available", "reason", "groups":
    [{"id", "label", "full_label", "size"}], "assignment": {node_id: group_id}}``.
    ``size`` counts knowledge nodes only; sources are assigned to the plurality
    group of their non-source neighbours and sources without neighbours are
    omitted. Never raises on malformed input.
    """
    valid = _node_ids(nodes)
    source_ids: list[str] = []
    knowledge_nodes: list[dict] = []
    for node in valid:
        if _is_source(node, display):
            source_ids.append(str(node["id"]))
        else:
            knowledge_nodes.append(node)
    knowledge_ids = [str(n["id"]) for n in knowledge_nodes]
    known = set(knowledge_ids) | set(source_ids)

    neighbours: dict[str, list[str]] = {}
    if isinstance(links, list):
        source_set = set(source_ids)
        for link in links:
            if not isinstance(link, dict):
                continue
            a, b = link.get("source"), link.get("target")
            if not isinstance(a, (str, int)) or not isinstance(b, (str, int)):
                continue
            a, b = str(a), str(b)
            if a not in known or b not in known:
                continue
            if a in source_set and b not in source_set:
                neighbours.setdefault(a, []).append(b)
            elif b in source_set and a not in source_set:
                neighbours.setdefault(b, []).append(a)

    modes = {
        "cluster": _cluster_mode(knowledge_ids, _ranked_communities(communities, valid)),
        "family": _family_mode(knowledge_nodes, display),
    }
    for mode in modes.values():
        if mode["available"]:
            groups = mode.pop("ordered")
            _unique_short_labels(groups)
            sizes = {g["id"]: g["size"] for g in groups}
            _assign_sources(mode, source_ids, neighbours, sizes)
            mode["groups"] = groups
    default = "none"
    for name in ("cluster", "family"):
        if modes[name]["available"]:
            default = name
            break
    return {"default": default, "modes": modes}
