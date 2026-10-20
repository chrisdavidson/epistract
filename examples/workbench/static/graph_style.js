// graph_style.js - Pure style/model helpers for the graph panel (no DOM, no vis).
// Exports: isSourceEdge, linkDegrees, humanizeRelation, isNonAsserted, statusSuffix,
//          relationRowParts, relationSentence, scaleBucket, labelFontSize, nodeSize,
//          edgeWidth, truncateLabel, labelCutoff, stableEdgeIds and the screen-size
//          constants (NODE_MIN_PX ... TRUNCATE_LABEL_CHARS), edgeDashes, edgeColorObject,
//          EDGE_BASE_OPACITY, EDGE_DIM_OPACITY, EDGE_DASH_ON_PX, EDGE_DASH_OFF_PX,
//          HOVER_TOP_RELATIONS, CARD_OFFSET_PX, CARD_MARGIN_PX, hoverCardModel, cardPosition

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

// ---------------------------------------------------------------------------
// Hover card model (pure; no DOM)
// ---------------------------------------------------------------------------
export const HOVER_TOP_RELATIONS = 4;
export const CARD_OFFSET_PX = 16;
export const CARD_MARGIN_PX = 8;

function groupScoreCompare(a, b) {
    return (b.support - a.support)
        || (b.confidence - a.confidence)
        || (a.sentence < b.sentence ? -1 : a.sentence > b.sentence ? 1 : 0);
}

// Card content for a node. incidentEdges is the node's adjacency list, so no
// scan of the whole edge list is needed. opts: {isSourceNode(id), typeLabel,
// family, description, top}.
export function hoverCardModel(node, incidentEdges, nodeById, opts = {}) {
    const top = opts.top === undefined ? HOVER_TOP_RELATIONS : opts.top;
    const isSourceNode = opts.isSourceNode || (() => false);
    const nameOf = (id) => {
        const n = nodeById.get(id);
        return n && n.name ? n.name : String(id);
    };
    const groups = new Map();
    let linkCount = 0;
    for (const edge of incidentEdges || []) {
        const parts = relationRowParts(edge, node.id, nameOf);
        if (isSourceNode(parts.otherId)) continue;
        linkCount += 1;
        const key = `${parts.direction}|${edge.relation_type}|${parts.otherId}`;
        const support = Number(edge.support_count) || 0;
        const confidence = Number(edge.confidence) || 0;
        const group = groups.get(key);
        if (!group) {
            groups.set(key, { parts, count: 1, support, confidence, status: parts.status });
            continue;
        }
        group.count += 1;
        if (support > group.support || (support === group.support && confidence > group.confidence)) {
            group.support = support;
            group.confidence = confidence;
            group.status = parts.status;
        }
    }
    const ranked = [...groups.values()].map((g) => {
        const shown = { ...g.parts, other: truncateLabel(g.parts.other) };
        return { ...g, shown, sentence: relationSentence(shown) };
    }).sort(groupScoreCompare);

    const picked = ranked.slice(0, Math.max(top, 0));
    // Keep both grammars visible on hubs: if the pick is one-directional but
    // the other direction exists, the last pick yields to its best row.
    if (picked.length > 1) {
        const dirs = new Set(picked.map((g) => g.parts.direction));
        if (dirs.size === 1) {
            const missing = ranked.find((g) => !dirs.has(g.parts.direction));
            if (missing) picked[picked.length - 1] = missing;
        }
    }
    const relations = picked.map((g) => ({
        direction: g.parts.direction,
        relation: g.parts.relation,
        other: g.shown.other,
        sentence: g.sentence,
        title: relationSentence(g.parts) + statusSuffix(g.status),
        status: g.status,
        count: g.count,
    }));
    return {
        name: node.name || node.id,
        typeLabel: opts.typeLabel || '',
        family: opts.family || '',
        description: opts.description || '',
        linkCount,
        sourceCount: (node.source_documents || []).length,
        relations,
        more: ranked.length - relations.length,
        noLinks: linkCount === 0,
    };
}

// Fixed-position placement: offset from the pointer, flipped when it would
// overflow, then clamped so the card stays CARD_MARGIN_PX inside the viewport.
export function cardPosition(pointer, size, viewport) {
    let left = pointer.x + CARD_OFFSET_PX;
    let top = pointer.y + CARD_OFFSET_PX;
    if (left + size.w + CARD_MARGIN_PX > viewport.w) left = pointer.x - CARD_OFFSET_PX - size.w;
    if (top + size.h + CARD_MARGIN_PX > viewport.h) top = pointer.y - CARD_OFFSET_PX - size.h;
    const maxLeft = Math.max(CARD_MARGIN_PX, viewport.w - size.w - CARD_MARGIN_PX);
    const maxTop = Math.max(CARD_MARGIN_PX, viewport.h - size.h - CARD_MARGIN_PX);
    return {
        left: Math.min(Math.max(left, CARD_MARGIN_PX), maxLeft),
        top: Math.min(Math.max(top, CARD_MARGIN_PX), maxTop),
    };
}
