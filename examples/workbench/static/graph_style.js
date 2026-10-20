// graph_style.js - Pure style/model helpers for the graph panel (no DOM, no vis).
// Exports: isSourceEdge, linkDegrees

// Mirrors core.graph_display.is_source_edge: an edge is a source edge when
// either endpoint is a source node or its relation is flagged as one.
export function isSourceEdge(edge, isSourceNodeId, isSourceRelation) {
    if (!edge) return false;
    return Boolean(
        isSourceNodeId(edge.source)
        || isSourceNodeId(edge.target)
        || isSourceRelation(edge.relation_type),
    );
}

// Returns a plain object id -> number of non-source edges touching the node.
export function linkDegrees(edges, isSourceEdgeFn) {
    const degrees = {};
    for (const e of edges) {
        if (isSourceEdgeFn(e)) continue;
        degrees[e.source] = (degrees[e.source] || 0) + 1;
        degrees[e.target] = (degrees[e.target] || 0) + 1;
    }
    return degrees;
}
