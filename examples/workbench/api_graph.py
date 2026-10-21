"""Graph data API endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from core.graph_payloads import claims_payload, entity_types_payload

router = APIRouter(prefix="/api/graph", tags=["graph"])


@router.get("")
async def get_graph(request: Request, entity_type: str | None = None):
    """Return full graph data or filtered by entity_type."""
    data = request.app.state.data
    if entity_type:
        nodes = data.get_nodes(entity_type=entity_type)
        # Filter edges to only include nodes in the filtered set
        node_ids = {n["id"] for n in nodes}
        edges = [
            e
            for e in data.get_edges()
            if e.get("source") in node_ids or e.get("target") in node_ids
        ]
        return {"nodes": nodes, "edges": edges}
    return {"nodes": data.get_nodes(), "edges": data.get_edges()}


@router.get("/node/{node_id:path}")
async def get_node(request: Request, node_id: str):
    """Return a single node with its connections."""
    data = request.app.state.data
    node = data.get_node_by_id(node_id)
    if not node:
        # See api_sources.py — a bare (body, status) tuple is a Flask idiom that
        # FastAPI serializes verbatim, producing HTTP 200 with an array body.
        return JSONResponse(
            status_code=404, content={"error": f"Node not found: {node_id}"}
        )
    # Find connected edges and neighbor nodes
    edges = [
        e
        for e in data.get_edges()
        if e.get("source") == node_id or e.get("target") == node_id
    ]
    neighbor_ids = set()
    for e in edges:
        neighbor_ids.add(e["source"] if e["target"] == node_id else e["target"])
    neighbors = [n for n in data.get_nodes() if n["id"] in neighbor_ids]
    return {"node": node, "edges": edges, "neighbors": neighbors}


@router.get("/claims")
async def get_claims(request: Request):
    """Return claims layer data (conflicts, gaps, risks, custom findings).

    The payload is built in ``core.graph_payloads.claims_payload`` so the static
    graph.html and the workbench share it: ``{conflicts, gaps, risks,
    cross_references, custom_findings, findings}``.
    """
    return claims_payload(request.app.state.data.claims_layer)


@router.get("/communities")
async def get_communities(request: Request):
    """Return community assignments."""
    data = request.app.state.data
    return data.communities


@router.get("/groups")
async def get_groups(request: Request):
    """Return the group payload: default mode plus ``cluster`` and ``family`` modes.

    Each mode carries ``available``/``reason``, its ``groups`` (``id``, short
    ``label``, ``full_label``, ``size``) and the node-to-group ``assignment``.
    """
    return request.app.state.groups


@router.get("/entity-types")
async def get_entity_types(request: Request):
    """Return entity type counts plus resolved display (types, families, relations, categories).

    Built in ``core.graph_payloads.entity_types_payload`` so graph.html and the
    workbench share it. Each type carries ``is_source`` and each relation
    ``source_edge``; the frontend only reads these flags.
    """
    data = request.app.state.data
    return entity_types_payload(data.get_nodes(), request.app.state.display)
