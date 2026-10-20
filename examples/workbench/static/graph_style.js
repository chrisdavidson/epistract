// graph_style.js - Pure style/model helpers for the graph panel (no DOM, no vis).
// Exports: isSourceEdge, linkDegrees, humanizeRelation, isNonAsserted, statusSuffix,
//          relationRowParts, relationSentence

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

// Display text for a relation type: lowercase words. DEVELOPES is a known
// upstream spelling of "develops" and is corrected for display only.
export function humanizeRelation(rel) {
    const raw = String(rel || '');
    const fixed = raw === 'DEVELOPES' ? 'develops' : raw;
    return fixed.replace(/_/g, ' ').toLowerCase().replace(/\s+/g, ' ').trim();
}

export function isNonAsserted(status) {
    return typeof status === 'string' && status !== '' && status.toLowerCase() !== 'asserted';
}

export function statusSuffix(status) {
    return isNonAsserted(status) ? ` (${status.toLowerCase()})` : '';
}

// Splits an edge into the parts of a relation row as seen from nodeId.
// A self-loop counts as outgoing.
export function relationRowParts(edge, nodeId, nameOf) {
    const outgoing = edge.source === nodeId;
    const otherId = outgoing ? edge.target : edge.source;
    return {
        direction: outgoing ? 'out' : 'in',
        relation: humanizeRelation(edge.relation_type),
        otherId,
        other: nameOf(otherId),
        status: isNonAsserted(edge.epistemic_status) ? edge.epistemic_status.toLowerCase() : '',
    };
}

// Outgoing: "<relation> → <other>"; incoming: "<other> · <relation> →".
export function relationSentence(parts) {
    return parts.direction === 'out'
        ? `${parts.relation} → ${parts.other}`
        : `${parts.other} · ${parts.relation} →`;
}
