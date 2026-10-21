// grouping.js - pure layout helpers for the grouped graph (no DOM, no vis).
//
// Exports: fnv1a, groupIterations, isAnchorId, packGroups, seedInside,
// anchorNodeSpecs, anchorEdgeSpecs, dataEdgeLengths and the tuning constants
// below. graph.js wires these into vis-network: each group gets a hidden fixed
// anchor node, every member is tied to its anchor by hidden spring edges, and
// members start inside their group's circle, so the force layout settles into
// separated groups. Everything keyed by node or group id is a Map (ids come
// from data and must never be used as plain-object keys).

export const ANCHOR_PREFIX = '__anchor:';           // id prefix of a group's hidden anchor node
export const ANCHOR_EDGE_PREFIX = '__anchor_edge:'; // id prefix of a hidden member-to-anchor edge
export const ANCHOR_EDGE_MULTIPLICITY = 3;          // hidden anchor edges per member (stronger pull toward the anchor)
export const GROUP_PACK_RADIUS = 80;                // world units of circle radius per sqrt(member count)
export const GROUP_ITERATIONS_SMALL = 200;          // stabilization iterations below GROUP_LARGE_NODE_COUNT nodes
export const GROUP_ITERATIONS_LARGE = 150;          // stabilization iterations at or above GROUP_LARGE_NODE_COUNT nodes
export const GROUP_LARGE_NODE_COUNT = 500;          // node count at which the lower iteration budget applies
export const INTRA_GROUP_EDGE_LENGTH = 90;          // rest length (world units) of an edge inside one group
export const FIT_MARGIN = 0.08;                     // fraction of the fitted scale given up as breathing room around the fit
const PACK_PAD_FRACTION = 0.25;                     // gap between packed circles, as a fraction of the new circle's radius
const PACK_PAD_WORLD = 60;                          // plus this many world units
const PACK_SPIRAL_RADIUS_STEP = 6;                  // world units the packing spiral grows per probe
const PACK_SPIRAL_ANGLE_STEP = 0.35;                // radians the packing spiral turns per probe
const SEED_RADIUS_FRACTION = 0.8;                   // seeded members stay within this fraction of the circle radius
const ANCHOR_EDGE_LENGTH_FRACTION = 0.5;            // anchor edge rest length as a fraction of the circle radius
const UINT32_RANGE = 4294967296;                    // 2^32, to map a hash into [0, 1)

// 32-bit FNV-1a hash of a string (unsigned).
export function fnv1a(str) {
    let h = 2166136261;
    const text = String(str);
    for (let i = 0; i < text.length; i++) {
        h ^= text.charCodeAt(i);
        h = Math.imul(h, 16777619);
    }
    return h >>> 0;
}

// Stabilization iteration budget for a grouped build of `nodeCount` nodes.
export function groupIterations(nodeCount) {
    return nodeCount >= GROUP_LARGE_NODE_COUNT ? GROUP_ITERATIONS_LARGE : GROUP_ITERATIONS_SMALL;
}

// True for the id of an anchor node or an anchor edge.
export function isAnchorId(id) {
    return typeof id === 'string'
        && (id.startsWith(ANCHOR_PREFIX) || id.startsWith(ANCHOR_EDGE_PREFIX));
}

// Place one circle per group on an Archimedean spiral so none overlap.
// sizes: Array<{id, size}>. Returns Map(id -> {x, y, r}); r = c * sqrt(size).
// Deterministic: groups are processed by size descending, then id, and the
// largest sits at the origin.
export function packGroups(sizes, c = GROUP_PACK_RADIUS) {
    const ordered = [...sizes].sort((a, b) => (b.size - a.size) || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
    const layout = new Map();
    const placed = [];
    for (const { id, size } of ordered) {
        const r = c * Math.sqrt(Math.max(size, 0));
        const pad = PACK_PAD_FRACTION * r + PACK_PAD_WORLD;
        let circle = null;
        if (placed.length === 0) {
            circle = { x: 0, y: 0, r };
        } else {
            let radius = 0;
            let angle = 0;
            while (circle === null) {
                radius += PACK_SPIRAL_RADIUS_STEP;
                angle += PACK_SPIRAL_ANGLE_STEP;
                const x = radius * Math.cos(angle);
                const y = radius * Math.sin(angle);
                if (placed.every(p => Math.hypot(p.x - x, p.y - y) >= p.r + r + pad)) {
                    circle = { x, y, r };
                }
            }
        }
        placed.push(circle);
        layout.set(id, circle);
    }
    return layout;
}

// Deterministic starting point for a node inside its group's circle.
export function seedInside(circle, nodeId) {
    const angle = (fnv1a(nodeId) / UINT32_RANGE) * 2 * Math.PI;
    const radial = Math.sqrt(fnv1a(`${nodeId}|r`) / UINT32_RANGE) * SEED_RADIUS_FRACTION * circle.r;
    return { x: circle.x + radial * Math.cos(angle), y: circle.y + radial * Math.sin(angle) };
}

// One hidden, fixed vis node per group circle, parked at the circle centre.
export function anchorNodeSpecs(layout) {
    const specs = [];
    for (const [groupId, circle] of layout) {
        specs.push({
            id: ANCHOR_PREFIX + groupId,
            x: circle.x,
            y: circle.y,
            fixed: { x: true, y: true },
            hidden: true,
            physics: true,
            size: 1,
            label: '',
            _anchor: true,
        });
    }
    return specs;
}

// `k` hidden spring edges from every member to its group's anchor.
// memberAssignment: Map(nodeId -> groupId). Members whose group has no circle are skipped.
export function anchorEdgeSpecs(memberAssignment, layout, k = ANCHOR_EDGE_MULTIPLICITY) {
    const specs = [];
    for (const [nodeId, groupId] of memberAssignment) {
        const circle = layout.get(groupId);
        if (!circle) continue;
        for (let i = 0; i < k; i++) {
            specs.push({
                id: `${ANCHOR_EDGE_PREFIX}${i}:${nodeId}`,
                from: nodeId,
                to: ANCHOR_PREFIX + groupId,
                hidden: true,
                physics: true,
                length: ANCHOR_EDGE_LENGTH_FRACTION * circle.r,
                width: 0.01,
                smooth: false,
                _anchor: true,
            });
        }
    }
    return specs;
}

// Rest length per data edge: short inside a group, the distance between the
// two group circles across groups. Edges with an unassigned end are skipped.
// edges: Array<{id, from, to}>; assignment: Map(nodeId -> groupId).
export function dataEdgeLengths(edges, assignment, layout) {
    const lengths = [];
    for (const edge of edges) {
        const a = assignment.get(edge.from);
        const b = assignment.get(edge.to);
        if (a === undefined || b === undefined) continue;
        if (a === b) {
            lengths.push({ id: edge.id, length: INTRA_GROUP_EDGE_LENGTH });
            continue;
        }
        const ca = layout.get(a);
        const cb = layout.get(b);
        if (!ca || !cb) continue;
        lengths.push({ id: edge.id, length: Math.hypot(ca.x - cb.x, ca.y - cb.y) });
    }
    return lengths;
}
