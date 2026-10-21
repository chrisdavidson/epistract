"""Per-document entity and relation counts for the workbench Dashboard.

Each source document of a graph becomes one row::

    {doc_id, display_name, filename, entity_count, relation_count, has_text, has_pdf}

``entity_count`` is the number of distinct non-source entity nodes that cite the
document in ``source_documents`` (entities linked to ``doc:<id>`` by a
``MENTIONED_IN`` edge count as well). ``relation_count`` is the number of
distinct knowledge relations attributed to the document through
``source_document``, ``support_documents`` or ``mentions[].source_document``;
provenance edges never count. A document that the graph references but that has
no ingested text is still listed, with ``has_text`` false.

This module is pure: no FastAPI, no file or network access. It never raises;
input that is missing, ``None`` or malformed is skipped. Rows are sorted by
entity count (descending), then display name (case-insensitive), then doc id.
"""

from __future__ import annotations

from core.graph_display import SOURCE_EDGE_RELATIONS, entity_type_key
from core.graph_groups import DEFAULT_SOURCE_TYPES

# PUBLISHED_IN is provenance (a link to a publication node) but, unlike
# MENTIONED_IN, graph_display does not treat it as a source edge.
EXCLUDED_RELATIONS = SOURCE_EDGE_RELATIONS | {"PUBLISHED_IN"}

DOC_PREFIX = "doc:"


def _strings(values: object) -> list[str]:
    """Return the non-empty strings of a list; a bare string counts as one item."""
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, list):
        return []
    return [v for v in values if isinstance(v, str) and v]


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


def _link_documents(link: dict) -> set[str]:
    docs = set(_strings(link.get("source_document")))
    docs.update(_strings(link.get("support_documents")))
    mentions = link.get("mentions")
    if isinstance(mentions, list):
        for mention in mentions:
            if isinstance(mention, dict):
                docs.update(_strings(mention.get("source_document")))
    return docs


def _is_source_node(node: dict, node_id: str) -> bool:
    return node_id.startswith(DOC_PREFIX) or (
        entity_type_key(node.get("entity_type")) in DEFAULT_SOURCE_TYPES
    )


def build_document_stats(
    documents: list[dict] | None,
    nodes: list[dict] | None,
    links: list[dict] | None,
) -> list[dict]:
    """Return one stats row per source document, most entity-rich first."""
    rows: dict[str, dict] = {}
    for doc in documents if isinstance(documents, list) else []:
        if not isinstance(doc, dict):
            continue
        doc_id = doc.get("doc_id")
        if not isinstance(doc_id, str) or not doc_id or doc_id in rows:
            continue
        filename = doc.get("filename")
        filename = filename if isinstance(filename, str) and filename else doc_id
        display = doc.get("display_name")
        rows[doc_id] = {
            "doc_id": doc_id,
            "display_name": display if isinstance(display, str) and display else filename,
            "filename": filename,
            "has_text": bool(doc.get("has_text")),
            "has_pdf": bool(doc.get("has_pdf")),
        }

    referenced: set[str] = set()
    entities: dict[str, set[str]] = {}
    relations: dict[str, set[str]] = {}
    source_ids: set[str] = set()

    for node in nodes if isinstance(nodes, list) else []:
        if not isinstance(node, dict):
            continue
        node_id = node.get("id")
        node_id = node_id if isinstance(node_id, str) else ""
        if _is_source_node(node, node_id):
            if node_id:
                source_ids.add(node_id)
            if node_id.startswith(DOC_PREFIX) and len(node_id) > len(DOC_PREFIX):
                referenced.add(node_id[len(DOC_PREFIX) :])
            continue
        for doc_id in _strings(node.get("source_documents")):
            referenced.add(doc_id)
            if node_id:
                entities.setdefault(doc_id, set()).add(node_id)

    for link in links if isinstance(links, list) else []:
        if not isinstance(link, dict):
            continue
        rtype = _relation_type(link)
        if rtype in SOURCE_EDGE_RELATIONS:
            # Entity -> document provenance: the fallback for entities whose
            # node carries no source_documents.
            target = _endpoint(link.get("target"))
            entity = _endpoint(link.get("source"))
            if target.startswith(DOC_PREFIX) and len(target) > len(DOC_PREFIX):
                doc_id = target[len(DOC_PREFIX) :]
                referenced.add(doc_id)
                if entity and entity not in source_ids and not entity.startswith(DOC_PREFIX):
                    entities.setdefault(doc_id, set()).add(entity)
            continue
        if rtype in EXCLUDED_RELATIONS:
            continue
        key = _relation_key(link, rtype)
        if not key:
            continue
        for doc_id in _link_documents(link):
            relations.setdefault(doc_id, set()).add(key)

    for doc_id in referenced:
        rows.setdefault(
            doc_id,
            {
                "doc_id": doc_id,
                "display_name": doc_id,
                "filename": doc_id,
                "has_text": False,
                "has_pdf": False,
            },
        )

    result = []
    for doc_id, row in rows.items():
        result.append(
            {
                "doc_id": row["doc_id"],
                "display_name": row["display_name"],
                "filename": row["filename"],
                "entity_count": len(entities.get(doc_id, ())),
                "relation_count": len(relations.get(doc_id, ())),
                "has_text": row["has_text"],
                "has_pdf": row["has_pdf"],
            }
        )
    result.sort(key=lambda r: (-r["entity_count"], r["display_name"].lower(), r["doc_id"]))
    return result
