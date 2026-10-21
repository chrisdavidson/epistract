// grouping.js - pure layout helpers for the grouped graph (no DOM, no vis).
//
// Exports: fnv1a, clampIntoRegion, regionGeometry, placeRegionLabels, groupIterations, isAnchorId, packGroups, seedInside,
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
export const REGION_PAD = 40;                       // world units added to the p90 member distance for a region radius
export const REGION_MIN_RADIUS = 40;                // smallest region radius in world units
export const REGION_LABEL_PX = 13;                  // region label size in screen px at every zoom
export const REGION_PILL_PAD_PX = 4;                // padding between pill text and pill edge, screen px
export const REGION_PILL_GAP_PX = 4;                // gap between a region's top edge and its pill, screen px
export const SOURCE_INSET = 0.95;                   // fraction of a region's radius a pulled-in source is placed at
export const REGION_MIN_MEMBERS = 2;                // visible members a group needs before its region is drawn
const REGION_P90 = 0.9;                             // member-distance percentile the radius is based on
// Region colors as named strings (neutral ink over a transparent tint).
export const REGION_COLORS = {
    fill: 'rgba(26, 26, 46, 0.045)',
    fillOther: 'rgba(26, 26, 46, 0.025)',
    fillEmph: 'rgba(26, 26, 46, 0.09)',
    stroke: 'rgba(26, 26, 46, 0.28)',
    strokeEmph: 'rgba(26, 26, 46, 0.6)',
    pillFill: 'rgba(255, 255, 255, 0.88)',
    pillStroke: 'rgba(26, 26, 46, 0.28)',
    ink: '#1a1a1a',
};
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

// One region per group with at least REGION_MIN_MEMBERS visible members.
// groups: Array<{id, label, size}>; positions: {nodeId: {x, y}}; visibleIds:
// iterable of drawn node ids; assignment: Map(nodeId -> groupId). Ids that are
// anchors, not visible, unassigned or without a position never count.
// Returns Array<{id, label, cx, cy, r, count, other}>; r = p90 distance from
// the centroid + REGION_PAD, at least REGION_MIN_RADIUS.
export function regionGeometry(groups, positions, visibleIds, assignment) {
    const visible = visibleIds instanceof Set ? visibleIds : new Set(visibleIds);
    const members = new Map();
    for (const id of visible) {
        if (isAnchorId(id)) continue;
        const gid = assignment.get(id);
        if (gid === undefined || !Object.hasOwn(positions, id)) continue;
        if (!members.has(gid)) members.set(gid, []);
        members.get(gid).push(positions[id]);
    }
    const regions = [];
    for (const group of groups) {
        const pts = members.get(group.id);
        if (!pts || pts.length < REGION_MIN_MEMBERS) continue;
        let cx = 0;
        let cy = 0;
        for (const p of pts) {
            cx += p.x;
            cy += p.y;
        }
        cx /= pts.length;
        cy /= pts.length;
        const dist = pts.map(p => Math.hypot(p.x - cx, p.y - cy)).sort((a, b) => a - b);
        const p90 = dist[Math.max(0, Math.ceil(REGION_P90 * dist.length) - 1)];
        regions.push({
            id: group.id,
            label: group.label,
            cx,
            cy,
            r: Math.max(REGION_MIN_RADIUS, p90 + REGION_PAD),
            count: pts.length,
            other: group.id === 'other',
        });
    }
    return regions;
}

function boxesIntersect(a, b) {
    return a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
}

// Greedy label placement in world units. `measure(text)` returns the world
// width of the text at the label font. Order: emphasized first, then count
// descending, then label ascending. A pill that would intersect an already
// placed one at every candidate spot is skipped (the emphasized one is placed
// first, so it always survives). Every box is clamped inside viewRect {left, top, right, bottom}.
// Returns Array<{id, label, x, y, w, h, emphasized}>.
export function placeRegionLabels(regions, measure, scale, emphasizedId, viewRect) {
    const pad = REGION_PILL_PAD_PX / scale;
    const gap = REGION_PILL_GAP_PX / scale;
    const height = REGION_LABEL_PX / scale + 2 * pad;
    const ordered = [...regions].sort((a, b) => {
        if ((a.id === emphasizedId) !== (b.id === emphasizedId)) return a.id === emphasizedId ? -1 : 1;
        if (a.count !== b.count) return b.count - a.count;
        return a.label < b.label ? -1 : a.label > b.label ? 1 : 0;
    });
    const placed = [];
    for (const region of ordered) {
        const w = measure(region.label) + 2 * pad;
        const x = Math.max(viewRect.left, Math.min(region.cx - w / 2, viewRect.right - w));
        const clampY = y => Math.max(viewRect.top, Math.min(y, viewRect.bottom - height));
        // Preferred spot is above the circle; when that collides the pill
        // tries below it, then the circle's middle.
        const candidates = [
            region.cy - region.r - gap - height,
            region.cy + region.r + gap,
            region.cy - height / 2,
        ];
        for (const top of candidates) {
            const box = { id: region.id, label: region.label, x, y: clampY(top), w, h: height, emphasized: region.id === emphasizedId };
            if (placed.some(other => boxesIntersect(box, other))) continue;
            placed.push(box);
            break;
        }
    }
    return placed;
}

// Pulls `point` back inside `region` ({cx, cy, r}) when it lies outside, to
// SOURCE_INSET of the radius along the line from the region centre. Points
// already inside are returned unchanged.
export function clampIntoRegion(point, region) {
    const dx = point.x - region.cx;
    const dy = point.y - region.cy;
    const dist = Math.hypot(dx, dy);
    if (dist <= region.r) return point;
    const k = (region.r * SOURCE_INSET) / dist;
    return { x: region.cx + dx * k, y: region.cy + dy * k };
}
