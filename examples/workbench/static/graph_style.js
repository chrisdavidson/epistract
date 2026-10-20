// graph_style.js - Pure style/model helpers for the graph panel (no DOM, no vis).
// Exports: isSourceEdge, linkDegrees, humanizeRelation, isNonAsserted, statusSuffix,
//          relationRowParts, relationSentence, scaleBucket, labelFontSize, nodeSize,
//          edgeWidth, truncateLabel, labelCutoff, stableEdgeIds and the screen-size
//          constants (NODE_MIN_PX ... TRUNCATE_LABEL_CHARS), edgeDashes, edgeColorObject,
//          EDGE_BASE_OPACITY, EDGE_DIM_OPACITY, EDGE_DASH_ON_PX, EDGE_DASH_OFF_PX

// Screen-constant sizing. vis draws in world units, so at a fit scale of ~0.14
// a world-unit size is a fraction of a pixel. These constants are pixel targets;
// the functions below divide by the current scale to reach them.
export const NODE_MIN_PX = 4;
export const NODE_MAX_PX = 11;
export const SOURCE_NODE_FACTOR = 0.7;
export const SOURCE_NODE_MIN_PX = 3;
export const EDGE_MIN_PX = 1.4;
export const EDGE_MAX_PX = 4;
export const LABEL_SCREEN_PX = 12;
export const LABEL_BASE_WORLD = 12;
export const LABEL_MAX_WORLD = 240;
export const TRUNCATE_LABEL_CHARS = 22;
export const EDGE_BASE_OPACITY = 0.8;
export const EDGE_DIM_OPACITY = 0.15;
export const EDGE_DASH_ON_PX = 7;
export const EDGE_DASH_OFF_PX = 5;

// Integer bucket of the zoom level (half-octave steps); the label controller
// only rewrites styles when this or the degree cutoff changes.
export function scaleBucket(scale) {
    return Math.round(Math.log2(Math.max(scale, 0.01)) * 2);
}

// World-unit font size that draws at about LABEL_SCREEN_PX on screen.
export function labelFontSize(scale) {
    const s = Math.max(Number(scale) || 0, 0.01);
    return Math.min(LABEL_MAX_WORLD, Math.max(LABEL_BASE_WORLD, LABEL_SCREEN_PX / s));
}

// World-unit node size: never below the old degree formula, never below the
// pixel floor at the current scale.
export function nodeSize(linkDeg, maxLinkDeg, scale, isSource) {
    const ratio = maxLinkDeg > 0 ? Math.min(Math.max(linkDeg / maxLinkDeg, 0), 1) : 0;
    const base = 8 + Math.round(ratio * 16);
    const floorPx = NODE_MIN_PX + (NODE_MAX_PX - NODE_MIN_PX) * Math.sqrt(ratio);
    const s = Math.max(Number(scale) || 0, 0.01);
    if (isSource) {
        return Math.max(base * 0.6, Math.max(SOURCE_NODE_MIN_PX, floorPx * SOURCE_NODE_FACTOR) / s);
    }
    return Math.max(base, floorPx / s);
}

// World-unit edge width that draws between EDGE_MIN_PX and EDGE_MAX_PX on
// screen, growing with support_count.
export function edgeWidth(supportCount, scale) {
    const sc = Math.max(Number(supportCount) || 1, 1);
    const px = Math.min(EDGE_MAX_PX, Math.max(EDGE_MIN_PX, 1 + 0.9 * Math.log2(Math.min(sc, 1e9))));
    const s = Math.max(Number(scale) || 0, 0.01);
    return px / s;
}

// Dash pattern that draws 7 px on / 5 px off at scale s for claims that are
// not asserted; false (solid) for asserted or missing status.
export function edgeDashes(status, scale) {
    if (!isNonAsserted(status)) return false;
    const s = Math.max(Number(scale) || 0, 0.01);
    return [EDGE_DASH_ON_PX / s, EDGE_DASH_OFF_PX / s];
}

// Complete vis edge color object; partial objects let vis drop the category color.
export function edgeColorObject(color, opacity) {
    return {
        color,
        highlight: { color, opacity: 1 },
        hover: { color, opacity: 1 },
        inherit: false,
        opacity,
    };
}

// Code-point-safe truncation with an ellipsis.
export function truncateLabel(text, max = TRUNCATE_LABEL_CHARS) {
    if (text === null || text === undefined) return '';
    const chars = Array.from(String(text));
    if (chars.length <= max) return chars.join('');
    return chars.slice(0, max - 1).join('') + '\u2026';
}

// Degree cutoff for a label budget over a descending degree list.
export function labelCutoff(sortedDesc, budget) {
    return budget >= sortedDesc.length ? 0 : (sortedDesc[budget - 1] || 0);
}

// One unique string id per edge: relation_id when it is a non-empty string not
// used yet, otherwise an index-based id.
export function stableEdgeIds(edges) {
    const used = new Set();
    return edges.map((e, i) => {
        const rid = e && typeof e.relation_id === 'string' ? e.relation_id : '';
        let id = rid && !used.has(rid) ? rid : `e${i}`;
        while (used.has(id)) id += '_';
        used.add(id);
        return id;
    });
}

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
