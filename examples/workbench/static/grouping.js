// grouping.js - pure layout helpers for the grouped graph (no DOM, no vis).
//
// Exports: fnv1a, clampIntoRegion, regionGeometry, placeRegionLabels, groupIterations, isAnchorId, packGroups, seedInside,
// anchorNodeSpecs, anchorEdgeSpecs, dataEdgeLengths, separateRegions, focusLayout and the tuning constants
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

// ---------------------------------------------------------------------------
// Focus mode: k-hop neighbourhoods, the breadcrumb stack and focus labels.
// Everything here is pure (Map/Set/array in, new value out).
// ---------------------------------------------------------------------------
export const FOCUS_OUTER_RING_LABELS = false;       // label 2-hop nodes at rest in focus (false: only hover/selection labels them)
export const FOCUS_MODE_MAX_LABELS = 120;
export const FOCUS_TRUNCATE_CHARS = 40;
export const FOCUS_MAX_CRUMBS = 4;

function clampHops(hops) {
    return hops === 2 ? 2 : 1;
}

// Breadth-first set of node ids within `hops` of `centerId`, centre included.
// `adjacency` maps id -> incident edge records ({source, target}). Only
// eligible edges are walked and only eligible nodes are entered, so a filtered
// out node never carries the walk across it. An unknown or ineligible centre
// gives an empty Set.
export function kHop(adjacency, centerId, hops, isEligibleEdge, isEligibleNode) {
    const reached = new Set();
    if (!adjacency.has(centerId) || !isEligibleNode(centerId)) return reached;
    reached.add(centerId);
    let frontier = [centerId];
    for (let depth = 0; depth < hops && frontier.length > 0; depth++) {
        const next = [];
        for (const id of frontier) {
            for (const edge of adjacency.get(id) || []) {
                if (!isEligibleEdge(edge)) continue;
                const other = edge.source === id ? edge.target : edge.source;
                if (reached.has(other) || !isEligibleNode(other)) continue;
                reached.add(other);
                next.push(other);
            }
        }
        frontier = next;
    }
    return reached;
}

export function pushFocus(stack, entry) {
    return [...stack, { id: entry.id, hops: clampHops(entry.hops) }];
}

export function popFocus(stack) {
    return stack.slice(0, -1);
}

// Keeps the entries up to and including `index`.
export function truncateFocus(stack, index) {
    return stack.slice(0, index + 1);
}

export function setTopHops(stack, hops) {
    if (stack.length === 0) return [];
    const next = stack.slice();
    next[next.length - 1] = { ...next[next.length - 1], hops: clampHops(hops) };
    return next;
}

// Breadcrumb model: "All nodes" first, then one crumb per stack entry. With
// more than `maxCrumbs` crumbs the oldest entries collapse into one inert
// ellipsis crumb whose title lists the hidden names.
// Each crumb: {kind: 'all' | 'node' | 'collapsed', label, title, index, current}.
export function crumbsFor(stack, nameOf, maxCrumbs = FOCUS_MAX_CRUMBS) {
    const crumbs = [{ kind: 'all', label: 'All nodes', title: 'All nodes', index: -1, current: false }];
    const entries = stack.map((entry, index) => ({
        kind: 'node',
        label: nameOf(entry.id),
        title: nameOf(entry.id),
        index,
        current: index === stack.length - 1,
    }));
    if (entries.length + 1 <= maxCrumbs) return crumbs.concat(entries);
    const keep = Math.max(1, maxCrumbs - 2);
    const hidden = entries.slice(0, entries.length - keep);
    crumbs.push({
        kind: 'collapsed',
        label: '…',
        title: hidden.map(entry => entry.label).join(' › '),
        index: -1,
        current: false,
    });
    return crumbs.concat(entries.slice(entries.length - keep));
}

// Ids labelled while focused. The centre and every 1-hop id always get a
// label; the remaining slots up to `cap` go to the highest in-set degree, ties
// broken by id. `inSetDegree` is a Map or a plain object.
export function focusModeLabelIds(centerId, focusSet, oneHopIds, inSetDegree, cap = FOCUS_MODE_MAX_LABELS) {
    const degreeOf = id => (inSetDegree instanceof Map ? inSetDegree.get(id) : inSetDegree[id]) || 0;
    const labelled = new Set();
    if (focusSet.has(centerId)) labelled.add(centerId);
    for (const id of oneHopIds) if (focusSet.has(id)) labelled.add(id);
    const rest = [...focusSet].filter(id => !labelled.has(id));
    rest.sort((a, b) => degreeOf(b) - degreeOf(a) || (a < b ? -1 : a > b ? 1 : 0));
    for (const id of rest) {
        if (labelled.size >= cap) break;
        labelled.add(id);
    }
    return labelled;
}

// Keyboard handling shared by the radiogroups. Returns the value to select
// for `key`, undefined when the key is not handled, null when there is
// nothing to select. `values` are the enabled options in order.
export function radioTarget(key, values, current) {
    const i = values.indexOf(current);
    switch (key) {
        case 'ArrowLeft':
        case 'ArrowUp':
            return values.length ? values[(i - 1 + values.length) % values.length] : null;
        case 'ArrowRight':
        case 'ArrowDown':
            return values.length ? values[(i + 1) % values.length] : null;
        case 'Home':
            return values.length ? values[0] : null;
        case 'End':
            return values.length ? values[values.length - 1] : null;
        case ' ':
        case 'Enter':
            return i >= 0 ? current : null;
        default:
            return undefined;
    }
}

// ---------------------------------------------------------------------------
// Region separation and focus layout
// ---------------------------------------------------------------------------
export const REGION_SEPARATION_GAP = 24;           // minimum world-unit gap kept between two region circles
const SEPARATION_MAX_ITERATIONS = 400;              // upper bound on separation passes
export const FOCUS_BOX_GAP = 6;                     // px of clear space kept between two focus label boxes
const FOCUS_ROW_FILL = 1.15;                         // row width slack over the ideal packed area when sizing rows
const FOCUS_DEFAULT_BOX = { w: 30, h: 28, dy: 8 };  // box used for a node with no measured box

// Pushes overlapping region circles apart along the line between their
// centres until none overlap (gap included). regions: Array<{id, cx, cy, r}>.
// Returns Map(id -> {dx, dy}) of the translation each region needs; whole
// groups move rigidly, so no radius changes. Deterministic: pairs are visited
// in id order and coincident centres separate along an id-derived direction.
export function separateRegions(regions, gap = REGION_SEPARATION_GAP, maxIterations = SEPARATION_MAX_ITERATIONS) {
    const items = [...regions]
        .sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0))
        .map(r => ({ id: r.id, x: r.cx, y: r.cy, r: r.r, dx: 0, dy: 0 }));
    for (let iter = 0; iter < maxIterations; iter++) {
        let moved = false;
        for (let i = 0; i < items.length; i++) {
            for (let j = i + 1; j < items.length; j++) {
                const a = items[i];
                const b = items[j];
                const need = a.r + b.r + gap;
                let ex = b.x - a.x;
                let ey = b.y - a.y;
                let d = Math.hypot(ex, ey);
                if (d >= need) continue;
                if (d < 1e-6) {
                    const angle = (fnv1a(a.id + '|' + b.id) / UINT32_RANGE) * 2 * Math.PI;
                    ex = Math.cos(angle);
                    ey = Math.sin(angle);
                    d = 1;
                }
                const push = (need - d) / 2 + 0.01;
                const ux = ex / d;
                const uy = ey / d;
                a.x -= ux * push; a.y -= uy * push; a.dx -= ux * push; a.dy -= uy * push;
                b.x += ux * push; b.y += uy * push; b.dx += ux * push; b.dy += uy * push;
                moved = true;
            }
        }
        if (!moved) break;
    }
    return new Map(items.map(i => [i.id, { dx: i.dx, dy: i.dy }]));
}

// Positions for a focus view, in px, with the centre node at the origin.
// Label boxes (wide and short) are packed into horizontal rows that stack
// outward from the centre row, alternating below and above it, so the 1-hop
// nodes occupy the rows nearest the centre and the 2-hop nodes start on fresh
// rows outside them. Nodes keep the order given (callers sort 1-hop nodes by
// group, entity type and name, and 2-hop nodes by their parent's position), so
// related nodes sit side by side. The row width follows the viewport aspect
// (width / height) so the result fills the view without shrinking it.
//   ring1: Array<{id, key}>; ring2: Array<{id, key, parent}>
//   boxes: Map(id -> {w, h, dy}) label box size in px, centred dy below the node point
// Returns Map(id -> {x, y}). Pure and deterministic; no two boxes overlap.
export function focusLayout({ centerId, ring1, ring2 = [], boxes, aspect = 1.6, gap = FOCUS_BOX_GAP }) {
    const boxOf = id => (boxes && boxes.get(id)) || FOCUS_DEFAULT_BOX;
    const byKey = (a, b) => (a.key < b.key ? -1 : a.key > b.key ? 1 : (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
    const out = new Map();
    const first = [...ring1].sort(byKey);
    const order1 = new Map(first.map((it, i) => [it.id, i]));
    const orderOf = id => (order1.has(id) ? order1.get(id) : -1);
    const second = [...ring2].sort((a, b) => (orderOf(a.parent) - orderOf(b.parent)) || byKey(a, b));

    const cBox = boxOf(centerId);
    const all = [{ id: centerId }, ...first, ...second];
    const area = all.reduce((sum, it) => sum + (boxOf(it.id).w + gap) * (boxOf(it.id).h + gap / 2), 0);
    const maxW = all.reduce((m, it) => Math.max(m, boxOf(it.id).w + gap), 0);
    const rowWidth = Math.max(maxW, Math.sqrt(area * Math.max(aspect, 0.5) * FOCUS_ROW_FILL));

    // Split the sequence into rows first, then stack them by their own heights.
    const rows = [];
    const split = (items, withCentre) => {
        let i = 0;
        while (i < items.length || withCentre) {
            const line = [];
            let width = 0;
            if (withCentre) {
                withCentre = false;
                width = cBox.w + gap;
            }
            while (i < items.length && ((line.length === 0 && width === 0) || width + boxOf(items[i].id).w + gap <= rowWidth)) {
                width += boxOf(items[i].id).w + gap;
                line.push(items[i]);
                i += 1;
            }
            rows.push({ line, width, centre: rows.length === 0 });
        }
    };
    split(first, true);
    if (second.length > 0) split(second, false);

    // Row 0 holds the centre; later rows alternate below (+) and above (-), each
    // as tall as its tallest box, so rows of bare markers take little room.
    const rowH = r => Math.max(r.centre ? cBox.h : 0, ...r.line.map(it => boxOf(it.id).h)) + gap / 2;
    const reach = { 1: rowH(rows[0]) / 2, '-1': rowH(rows[0]) / 2 };
    rows.forEach((r, k) => {
        const h = rowH(r);
        let centreY = cBox.dy;
        if (k > 0) {
            const side = k % 2 === 1 ? 1 : -1;
            centreY = cBox.dy + side * (reach[side] + h / 2);
            reach[side] += h;
        }
        if (r.centre) {
            // The centre node stays at x = 0; the row's items split around it.
            const half = Math.ceil(r.line.length / 2);
            let x = -(cBox.w / 2 + gap);
            for (let j = half - 1; j >= 0; j--) {
                const b = boxOf(r.line[j].id);
                out.set(r.line[j].id, { x: x - b.w / 2, y: centreY - b.dy });
                x -= b.w + gap;
            }
            x = cBox.w / 2 + gap;
            for (const it of r.line.slice(half)) {
                const b = boxOf(it.id);
                out.set(it.id, { x: x + b.w / 2, y: centreY - b.dy });
                x += b.w + gap;
            }
        } else {
            let x = -(r.width - gap) / 2;
            for (const it of r.line) {
                const b = boxOf(it.id);
                out.set(it.id, { x: x + b.w / 2, y: centreY - b.dy });
                x += b.w + gap;
            }
        }
    });
    out.set(centerId, { x: 0, y: 0 });
    return out;
}
