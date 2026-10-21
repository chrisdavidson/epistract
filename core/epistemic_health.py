"""Epistemic-health normalizer for the workbench Dashboard.

Every shipped claims-layer shape (GLP-1 v3, legacy PICALM, pharmacovigilance,
FDA labels, contracts risks) is turned into one structure::

    {
      "available": bool,
      "status_counts": [{"status": str, "count": int}],
      "sections": [{"key", "label", "description", "count", "items": [item]}],
    }

with ``item = {title, kind, entities, statements, documents, question}``.

This module is pure: no FastAPI, no file or network access. It never raises;
input that is missing, ``None`` or malformed yields the "not run" shape
(``available`` false, no counts, no sections).
"""

from __future__ import annotations

from core.graph_display import entity_type_key
from core.graph_groups import _collapse, _truncate

MAX_ITEMS_PER_SECTION = 50
MAX_QUESTION_TEXT = 200
MAX_TITLE_TEXT = 400

# (key, label, description) in display order.
SECTIONS: tuple[tuple[str, str, str], ...] = (
    (
        "contradictions",
        "Contradictions",
        "The same relationship is stated with sharply different confidence across documents.",
    ),
    (
        "conflicts",
        "Conflicts",
        "Statements in the sources that point in opposite directions.",
    ),
    (
        "contested_claims",
        "Contested claims",
        "Claims whose support or confidence differs across the sources.",
    ),
    (
        "hypotheses",
        "Hypotheses",
        "Groups of related claims that the sources present as unconfirmed.",
    ),
    (
        "risks",
        "Risks",
        "Risks flagged by this domain's epistemic rules.",
    ),
    (
        "coverage_gaps",
        "Coverage gaps",
        "Things this graph should contain but does not.",
    ),
)

# Grammatical verb phrases for the most common relation types; anything else
# falls back to the humanized relation name.
RELATION_VERBS: dict[str, str] = {
    "INDICATED_FOR": "is indicated for",
    "CAUSES": "causes",
    "TREATS": "treats",
    "INHIBITS": "inhibits",
    "TARGETS": "targets",
    "HAS_MECHANISM": "acts via",
    "ASSOCIATED_WITH": "is associated with",
    "HAS_PHENOTYPE": "has phenotype",
    "ACTIVATES": "activates",
    "BINDS": "binds",
    "REGULATES": "regulates",
    "PREVENTS": "prevents",
    "CONTRAINDICATED_FOR": "is contraindicated for",
}

# Statements shown per contested claim.
_CONTESTED_STATEMENTS = 2


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _humanize_relation(rel: object) -> str:
    """Port of ``humanizeRelation`` in static/graph_style.js (underscores to spaces)."""
    raw = str(rel or "")
    fixed = "develops" if raw == "DEVELOPES" else raw
    return " ".join(fixed.replace("_", " ").lower().split())


def _verb(rel: object) -> str:
    """Return the verb phrase for a relation type."""
    if isinstance(rel, str) and rel in RELATION_VERBS:
        return RELATION_VERBS[rel]
    return _humanize_relation(rel)


def _text(value: object) -> str:
    """Collapse str/int/float values to a string; anything else becomes ''."""
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return ""
    return _collapse(value)


def _split_relation_id(rid: object) -> tuple[str, str, str] | None:
    """Split ``source|RELATION|target`` into its three parts, or None."""
    if not isinstance(rid, str):
        return None
    parts = rid.split("|")
    if len(parts) != 3 or not all(p.strip() for p in parts):
        return None
    return parts[0], parts[1], parts[2]


def _node_index(nodes: object) -> dict[str, dict]:
    index: dict[str, dict] = {}
    if not isinstance(nodes, list):
        return index
    for node in nodes:
        if isinstance(node, dict) and isinstance(node.get("id"), str):
            index[node["id"]] = node
    return index


def _name(node_id: str, index: dict[str, dict]) -> str:
    node = index.get(node_id)
    if node is not None:
        name = _text(node.get("name")) or _text(node.get("label"))
        if name:
            return name
    return node_id.split(":", 1)[-1].replace("_", " ")


def _entities(ids: object, index: dict[str, dict]) -> list[dict]:
    """Return ``{id, name, entity_type}`` for the ids present in the graph."""
    if not isinstance(ids, list):
        return []
    out: list[dict] = []
    seen: set[str] = set()
    for node_id in ids:
        if not isinstance(node_id, str) or node_id in seen or node_id not in index:
            continue
        seen.add(node_id)
        out.append(
            {
                "id": node_id,
                "name": _name(node_id, index),
                "entity_type": entity_type_key(index[node_id].get("entity_type")),
            }
        )
    return out


def _confidence(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if 0 <= value <= 1 else None


def _statement(mention: object) -> dict | None:
    if not isinstance(mention, dict):
        return None
    text = _text(mention.get("evidence"))
    if not text:
        return None
    return {
        "text": text,
        "document": _text(mention.get("document") or mention.get("source_document")),
        "confidence": _confidence(mention.get("confidence")),
    }


def _statements(mentions: object) -> list[dict]:
    if not isinstance(mentions, list):
        return []
    return [s for s in (_statement(m) for m in mentions) if s is not None]


def _strings(values: object) -> list[str]:
    if not isinstance(values, list):
        return []
    return [s for s in (_text(v) for v in values if isinstance(v, str)) if s]


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(v for v in values if v))


def _title(value: str) -> str:
    return _truncate(value, MAX_TITLE_TEXT)


def _question(template: str, title: str) -> str:
    return template.format(_truncate(title, MAX_QUESTION_TEXT))


def _status_counts(summary: object) -> list[dict]:
    if not isinstance(summary, dict):
        return []
    counts = summary.get("epistemic_status_counts")
    if not isinstance(counts, dict):
        return []
    out = [
        {"status": str(status), "count": n}
        for status, n in counts.items()
        if type(n) is int and n > 0
    ]
    out.sort(key=lambda c: (-c["count"], c["status"]))
    return out


# ---------------------------------------------------------------------------
# Item builders (each returns an item dict or None)
# ---------------------------------------------------------------------------


def _relation_parts(raw: dict) -> tuple[str, str, str] | None:
    parts = _split_relation_id(raw.get("relation_id"))
    source = raw.get("source") if isinstance(raw.get("source"), str) else None
    target = raw.get("target") if isinstance(raw.get("target"), str) else None
    rel = raw.get("relation_type") if isinstance(raw.get("relation_type"), str) else None
    if parts is not None:
        source = source or parts[0]
        rel = rel or parts[1]
        target = target or parts[2]
    if not source or not target:
        return None
    return source, rel or "", target


def _extremes(statements: list[dict]) -> list[dict]:
    """Return the lowest- then highest-confidence statements (first wins ties)."""
    scored = [s for s in statements if s["confidence"] is not None]
    if len(scored) < 2:
        return statements[:2]
    low = min(scored, key=lambda s: s["confidence"])
    high = max(scored, key=lambda s: s["confidence"])
    return [low] if low is high else [low, high]


def _relation_item(raw: object, kind: str, index: dict[str, dict]) -> dict | None:
    if not isinstance(raw, dict):
        return None
    parts = _relation_parts(raw)
    if parts is None:
        return None
    source, rel, target = parts
    title = _title(f"{_name(source, index)} {_verb(rel)} {_name(target, index)}".replace("  ", " "))

    if kind == "contradiction":
        all_statements = _statements(raw.get("mentions"))
        positive = _statements(raw.get("positive_mentions"))
        negative = _statements(raw.get("negative_mentions"))
        if all_statements:
            statements = _extremes(all_statements)
        else:
            statements = positive[:1] + negative[:1]
        all_statements = all_statements + positive + negative
        documents = [s["document"] for s in all_statements]
        question = _question("Why do sources disagree on whether {}?", title)
    else:
        all_statements = _statements(raw.get("mentions"))
        statements = all_statements[:_CONTESTED_STATEMENTS]
        if not statements:
            fallback = _statement(raw)
            statements = [fallback] if fallback else []
        documents = [s["document"] for s in all_statements]
        documents += [_text(raw.get("source_document"))]
        documents += _strings(raw.get("support_documents"))
        question = _question("Why do sources disagree on whether {}?", title)

    return {
        "title": title,
        "kind": kind,
        "entities": _entities([source, target], index),
        "statements": statements,
        "documents": _dedupe(documents),
        "question": question,
    }


def _contradiction_item(raw: object, index: dict[str, dict]) -> dict | None:
    return _relation_item(raw, "contradiction", index)


def _contested_item(raw: object, index: dict[str, dict]) -> dict | None:
    return _relation_item(raw, "contested_claim", index)


def _hypothesis_item(raw: object, index: dict[str, dict]) -> dict | None:
    if not isinstance(raw, dict):
        return None
    label = _text(raw.get("label"))
    members = raw.get("member_entities")
    if not label and not isinstance(members, list):
        return None
    title = _title(label or "Hypothesis")
    return {
        "title": title,
        "kind": "hypothesis",
        "entities": _entities(members, index),
        "statements": [],
        "documents": _dedupe(_strings(raw.get("support_documents"))),
        "question": _question("What evidence supports the hypothesis: {}?", title),
    }


def _evidence_side(side: object) -> str:
    """Describe one side of a contracts conflict's evidence dict.

    Contracts sides look like ``{"clause"|"entity": name, "contract": doc}``,
    optionally with ``date`` or ``amount`` (domains/contracts/epistemic.py).
    """
    if not isinstance(side, dict):
        return ""
    name = _text(side.get("clause")) or _text(side.get("entity"))
    detail = _text(side.get("date")) or _text(side.get("amount"))
    label = f"{name}: {detail}" if name and detail else (name or detail)
    contract = _text(side.get("contract"))
    if label and contract:
        return f"{label} ({contract})"
    return label or contract


def _evidence_statement(evidence: object, confidence: object) -> dict | None:
    """One statement summarising the sides of a dict-shaped conflict evidence."""
    if not isinstance(evidence, dict):
        return None
    sides = [s for s in (_evidence_side(v) for v in evidence.values()) if s]
    if not sides:
        return None
    return {
        "text": _truncate("Sources disagree: " + " vs ".join(sides), MAX_TITLE_TEXT),
        "document": "",
        "confidence": _confidence(confidence),
    }


def _conflict_item(raw: object, index: dict[str, dict]) -> dict | None:
    """Pharmacovigilance/FDA conflicts (``evidence`` str, ``terms``, ``entity_a/b``)
    and contracts conflicts (``description``, ``evidence`` dict,
    ``entities_involved``, ``contracts_involved``, ``suggested_action``)."""
    if not isinstance(raw, dict):
        return None
    title = _title(
        _text(raw.get("description"))
        or _text(raw.get("evidence"))
        or _humanize_relation(raw.get("type") or "")
        or "Conflict"
    )
    ids: list[object] = [raw.get("entity_a"), raw.get("entity_b")]
    for key in ("affected_entities", "entities_involved"):
        listed = raw.get(key)
        if isinstance(listed, list):
            ids += listed
    statements: list[dict] = []
    sides = _evidence_statement(raw.get("evidence"), raw.get("confidence"))
    if sides is not None:
        statements.append(sides)
    terms = raw.get("terms")
    if isinstance(terms, list):
        words = [t for t in (_text(v) for v in terms) if t]
        if len(words) >= 2:
            statements.append(
                {
                    "text": f"Conflicting terms: {words[0]} vs {words[1]}",
                    "document": "",
                    "confidence": None,
                }
            )
    action = _text(raw.get("suggested_action"))
    if action:
        statements.append(
            {"text": f"Suggested action: {action}", "document": "", "confidence": None}
        )
    return {
        "title": title,
        "kind": "conflict",
        "entities": _entities(ids, index),
        "statements": statements,
        "documents": _dedupe(_strings(raw.get("contracts_involved"))),
        "question": _question("What is behind this conflict: {}?", title),
    }


def _risk_item(raw: object, index: dict[str, dict]) -> dict | None:
    if not isinstance(raw, dict):
        return None
    title = _title(_text(raw.get("description")) or "Risk")
    action = _text(raw.get("suggested_action"))
    statements = (
        [{"text": f"Suggested action: {action}", "document": "", "confidence": None}]
        if action
        else []
    )
    return {
        "title": title,
        "kind": "risk",
        "entities": _entities([raw.get("source_id")], index),
        "statements": statements,
        "documents": _dedupe(_strings(raw.get("contracts_affected"))),
        "question": _question("What should I do about this risk: {}?", title),
    }


def _gap_item(raw: object, index: dict[str, dict]) -> dict | None:
    if not isinstance(raw, dict):
        return None
    title = _text(raw.get("description"))
    if not title:
        missing = _text(raw.get("missing_type"))
        if not missing:
            return None
        title = f"No {missing} entities found"
    title = _title(title)
    return {
        "title": title,
        "kind": "coverage_gap",
        "entities": [],
        "statements": [],
        "documents": [],
        "question": _question("What is missing: {}?", title),
    }


_BUILDERS = {
    "contradictions": _contradiction_item,
    "conflicts": _conflict_item,
    "contested_claims": _contested_item,
    "hypotheses": _hypothesis_item,
    "risks": _risk_item,
    "coverage_gaps": _gap_item,
}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def build_epistemic_health(claims_layer: object, nodes: list[dict] | None) -> dict:
    """Normalize a claims layer into the Dashboard's epistemic-health payload.

    Args:
        claims_layer: Parsed ``claims_layer.json`` (any shape; may be None).
        nodes: Graph nodes, used to resolve entity names and filter entity ids.

    Returns:
        ``{"available", "status_counts", "sections"}``. Never raises; unusable
        input gives ``available`` false with empty counts and sections.
    """
    if not isinstance(claims_layer, dict):
        return {"available": False, "status_counts": [], "sections": []}
    index = _node_index(nodes)
    super_domain = claims_layer.get("super_domain")
    if not isinstance(super_domain, dict):
        super_domain = {}

    sections: list[dict] = []
    for key, label, description in SECTIONS:
        raw_items = super_domain.get(key)
        if not isinstance(raw_items, list):
            continue
        items: list[dict] = []
        for raw in raw_items:
            try:
                item = _BUILDERS[key](raw, index)
            except (TypeError, ValueError, AttributeError, KeyError):
                item = None
            if item is not None:
                items.append(item)
        if items:
            sections.append(
                {
                    "key": key,
                    "label": label,
                    "description": description,
                    "count": len(items),
                    "items": items[:MAX_ITEMS_PER_SECTION],
                }
            )

    status_counts = _status_counts(claims_layer.get("summary"))
    return {
        "available": bool(status_counts or sections),
        "status_counts": status_counts,
        "sections": sections,
    }
