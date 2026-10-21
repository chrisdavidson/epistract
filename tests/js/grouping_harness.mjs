// Pure assertions for the layout helpers in grouping.js.
// Prints one JSON line {"passed": n, "failed": [...]} and exits 1 on failure.
import { pathToFileURL, fileURLToPath } from 'node:url';
import { readFileSync } from 'node:fs';
import path from 'node:path';

const here = path.dirname(fileURLToPath(import.meta.url));
const groupingPath = path.resolve(here, '..', '..', 'examples', 'workbench', 'static', 'grouping.js');
const G = await import(pathToFileURL(groupingPath).href);

let passed = 0;
const failed = [];
function check(name, cond) {
    if (cond) passed++;
    else failed.push(name);
}

// --- hashing -------------------------------------------------------------
check('fnv1a empty string', G.fnv1a('') === 2166136261);
check('fnv1a "a"', G.fnv1a('a') === 0xe40c292c);
check('fnv1a "foobar"', G.fnv1a('foobar') === 0xbf9cf968);
check('fnv1a is uint32', G.fnv1a('compound:semaglutide') >= 0 && G.fnv1a('compound:semaglutide') < 2 ** 32);
check('fnv1a stable', G.fnv1a('x:y') === G.fnv1a('x:y'));

// --- packGroups ----------------------------------------------------------
const sizes = [
    { id: 'c1', size: 43 }, { id: 'c2', size: 32 }, { id: 'c3', size: 29 }, { id: 'c4', size: 28 },
    { id: 'c5', size: 28 }, { id: 'c6', size: 18 }, { id: 'c7', size: 17 }, { id: 'c8', size: 12 },
    { id: 'c9', size: 9 }, { id: 'other', size: 8 }, { id: 'tiny', size: 1 },
];
const layoutA = G.packGroups(sizes);
const layoutB = G.packGroups([...sizes].reverse());
check('packGroups returns a Map', layoutA instanceof Map);
check('packGroups covers every group', layoutA.size === sizes.length);
let same = true;
for (const [id, c] of layoutA) {
    const o = layoutB.get(id);
    if (!o || o.x !== c.x || o.y !== c.y || o.r !== c.r) same = false;
}
check('packGroups deterministic (input order independent)', same);
check('packGroups largest at origin', layoutA.get('c1').x === 0 && layoutA.get('c1').y === 0);
let radiusOk = true;
for (const s of sizes) {
    if (Math.abs(layoutA.get(s.id).r - G.GROUP_PACK_RADIUS * Math.sqrt(s.size)) > 1e-9) radiusOk = false;
}
check('packGroups r = GROUP_PACK_RADIUS*sqrt(n)', radiusOk);
let overlap = false;
const circles = [...layoutA.values()];
for (let i = 0; i < circles.length; i++) {
    for (let j = i + 1; j < circles.length; j++) {
        const d = Math.hypot(circles[i].x - circles[j].x, circles[i].y - circles[j].y);
        if (d < circles[i].r + circles[j].r) overlap = true;
    }
}
check('packGroups circles do not overlap', !overlap);
check('packGroups empty input', G.packGroups([]).size === 0);

// --- seedInside ----------------------------------------------------------
const circle = layoutA.get('c3');
let inside = true;
for (let i = 0; i < 200; i++) {
    const p = G.seedInside(circle, `node-${i}`);
    if (Math.hypot(p.x - circle.x, p.y - circle.y) > 0.8 * circle.r + 1e-9) inside = false;
}
check('seedInside stays within 0.8*r', inside);
const p1 = G.seedInside(circle, 'node-7');
const p2 = G.seedInside(circle, 'node-7');
check('seedInside deterministic', p1.x === p2.x && p1.y === p2.y);
check('seedInside differs per node', G.seedInside(circle, 'a').x !== G.seedInside(circle, 'b').x);

// --- anchors -------------------------------------------------------------
const nodeSpecs = G.anchorNodeSpecs(layoutA);
check('one anchor per group', nodeSpecs.length === layoutA.size);
check('anchor ids prefixed', nodeSpecs.every((n) => n.id.startsWith(G.ANCHOR_PREFIX)));
check('anchors hidden', nodeSpecs.every((n) => n.hidden === true));
check('anchors fixed in x and y', nodeSpecs.every((n) => n.fixed && n.fixed.x === true && n.fixed.y === true));
check('anchors in physics', nodeSpecs.every((n) => n.physics === true));
check('anchors flagged', nodeSpecs.every((n) => n._anchor === true));
check('anchors placed at the circle centre', nodeSpecs.every((n) => {
    const c = layoutA.get(n.id.slice(G.ANCHOR_PREFIX.length));
    return c && n.x === c.x && n.y === c.y;
}));

const members = new Map([['n1', 'c1'], ['n2', 'c1'], ['n3', 'c2']]);
const edgeSpecs = G.anchorEdgeSpecs(members, layoutA);
check('multiplicity constant is 3', G.ANCHOR_EDGE_MULTIPLICITY === 3);
check('3 anchor edges per member', edgeSpecs.length === 3 * members.size);
check('anchor edges hidden physics edges', edgeSpecs.every((e) => e.hidden === true && e.physics === true && e._anchor === true));
check('anchor edge ids prefixed and unique', new Set(edgeSpecs.map((e) => e.id)).size === edgeSpecs.length
    && edgeSpecs.every((e) => e.id.startsWith(G.ANCHOR_EDGE_PREFIX)));
check('anchor edge length is half the radius', edgeSpecs.every((e) => {
    const gid = e.to.slice(G.ANCHOR_PREFIX.length);
    return Math.abs(e.length - 0.5 * layoutA.get(gid).r) < 1e-9;
}));
check('anchor edge endpoints', edgeSpecs.every((e) => members.has(e.from) && e.to.startsWith(G.ANCHOR_PREFIX)));
check('anchor edges skip groups without a circle',
    G.anchorEdgeSpecs(new Map([['n9', 'missing']]), layoutA).length === 0);
check('custom multiplicity', G.anchorEdgeSpecs(members, layoutA, 1).length === members.size);

// --- data edge lengths ---------------------------------------------------
const assign = new Map([['n1', 'c1'], ['n2', 'c1'], ['n3', 'c2']]);
const lengths = G.dataEdgeLengths([
    { id: 'e1', from: 'n1', to: 'n2' },
    { id: 'e2', from: 'n1', to: 'n3' },
    { id: 'e3', from: 'n1', to: 'unassigned' },
], assign, layoutA);
const byId = new Map(lengths.map((l) => [l.id, l.length]));
check('intra-group edge length', byId.get('e1') === G.INTRA_GROUP_EDGE_LENGTH && G.INTRA_GROUP_EDGE_LENGTH === 90);
const a = layoutA.get('c1');
const b = layoutA.get('c2');
check('inter-group edge length is the anchor distance',
    Math.abs(byId.get('e2') - Math.hypot(a.x - b.x, a.y - b.y)) < 1e-9);
check('edges with an unassigned end are skipped', !byId.has('e3') && lengths.length === 2);

// --- ids and iterations --------------------------------------------------
check('isAnchorId true for anchor node', G.isAnchorId(G.ANCHOR_PREFIX + 'c1'));
check('isAnchorId true for anchor edge', G.isAnchorId(G.ANCHOR_EDGE_PREFIX + '0:n1'));
check('isAnchorId false for data ids', !G.isAnchorId('compound:semaglutide') && !G.isAnchorId('r1') && !G.isAnchorId(''));
check('isAnchorId tolerates non-strings', !G.isAnchorId(undefined) && !G.isAnchorId(null) && !G.isAnchorId(12));
check('groupIterations(499) = 200', G.groupIterations(499) === 200);
check('groupIterations(500) = 150', G.groupIterations(500) === 150);
check('groupIterations(1738) = 150', G.groupIterations(1738) === 150);

// --- regionGeometry ------------------------------------------------------
{
    const groups = [
        { id: 'g1', label: 'Alpha', size: 4 },
        { id: 'g2', label: 'Beta', size: 3 },
        { id: 'g3', label: 'Gamma', size: 12 },
    ];
    const assignment = new Map([
        ['a', 'g1'], ['b', 'g1'], ['c', 'g1'], ['d', 'g1'],
        ['e', 'g2'], ['f', 'g2'],
    ]);
    const positions = {
        a: { x: 0, y: 0 }, b: { x: 100, y: 0 }, c: { x: 0, y: 100 }, d: { x: 100, y: 100 },
        e: { x: 500, y: 500 }, f: { x: 500, y: 520 },
        '__anchor:g1': { x: 9999, y: 9999 }, src: { x: -9999, y: -9999 },
    };
    const visible = new Set(['a', 'b', 'c', 'd', 'e', '__anchor:g1', 'src']);
    const regions = G.regionGeometry(groups, positions, visible, assignment);
    const byId = new Map(regions.map((r) => [r.id, r]));
    check('regionGeometry drops groups with < 2 visible members', !byId.has('g2') && !byId.has('g3') && regions.length === 1);
    const r1 = byId.get('g1');
    check('regionGeometry centroid', r1 && r1.cx === 50 && r1.cy === 50);
    check('regionGeometry radius = p90 + pad', r1 && Math.abs(r1.r - (Math.hypot(50, 50) + G.REGION_PAD)) < 1e-9);
    check('regionGeometry carries label and count', r1 && r1.label === 'Alpha' && r1.count === 4);
    check('regionGeometry ignores anchors and unassigned ids', r1 && r1.count === 4);
    check('REGION constants', G.REGION_PAD === 40 && G.REGION_MIN_RADIUS === 40 && G.REGION_LABEL_PX === 13);
    const tight = G.regionGeometry([{ id: 'g', label: 'T', size: 2 }],
        { x1: { x: 0, y: 0 }, x2: { x: 2, y: 0 } }, new Set(['x1', 'x2']),
        new Map([['x1', 'g'], ['x2', 'g']]));
    check('regionGeometry min radius', tight.length === 1 && tight[0].r >= G.REGION_MIN_RADIUS);
    // One far outlier among 10 points must not stretch the circle to it.
    const pts = {};
    const asg = new Map();
    for (let i = 0; i < 9; i++) { pts[`p${i}`] = { x: i, y: 0 }; asg.set(`p${i}`, 'g'); }
    pts.out = { x: 5000, y: 0 };
    asg.set('out', 'g');
    const outl = G.regionGeometry([{ id: 'g', label: 'O', size: 10 }], pts, new Set(Object.keys(pts)), asg);
    check('regionGeometry p90 resists an outlier', outl.length === 1 && outl[0].r < 5000 - outl[0].cx);
    check('regionGeometry empty input', G.regionGeometry([], {}, new Set(), new Map()).length === 0);
}

// --- placeRegionLabels ---------------------------------------------------
{
    const measure = (t) => t.length * 7;
    const view = { left: -1000, top: -1000, right: 4000, bottom: 4000 };
    const regs = [];
    for (let i = 0; i < 11; i++) {
        regs.push({ id: `g${i}`, label: `Group ${String.fromCharCode(65 + i)}`, cx: (i % 4) * 400, cy: Math.floor(i / 4) * 400, r: 80, count: 20 - i, other: false });
    }
    const placed = G.placeRegionLabels(regs, measure, 1, null, view);
    check('placeRegionLabels places all spread regions', placed.length === 11);
    const hit = (a, b) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
    let overlap = false;
    for (let i = 0; i < placed.length; i++) for (let j = i + 1; j < placed.length; j++) if (hit(placed[i], placed[j])) overlap = true;
    check('placeRegionLabels boxes never overlap', !overlap);
    check('placeRegionLabels order by size desc', placed[0].id === 'g0' && placed[10].id === 'g10');
    check('placeRegionLabels box height = 13px + padding', Math.abs(placed[0].h - (13 + 8)) < 1e-9);
    check('placeRegionLabels box width = text + padding', Math.abs(placed[0].w - (measure(placed[0].label) + 8)) < 1e-9);
    const scaled = G.placeRegionLabels(regs, (t) => measure(t) / 0.5, 0.5, null, view);
    check('placeRegionLabels scales box height with 1/scale', Math.abs(scaled[0].h - (13 + 8) / 0.5) < 1e-9);
    // Crowded: regions at one spot fall back to the other candidate spots, then are skipped.
    const crowd = [
        { id: 'big', label: 'Big', cx: 0, cy: 0, r: 80, count: 50 },
        { id: 'mid', label: 'Mid', cx: 5, cy: 5, r: 80, count: 20 },
        { id: 'low', label: 'Low', cx: 5, cy: 5, r: 80, count: 10 },
        { id: 'small', label: 'Small', cx: 5, cy: 5, r: 80, count: 5 },
    ];
    const c1 = G.placeRegionLabels(crowd, measure, 1, null, view);
    check('placeRegionLabels falls back to another spot', c1.length === 3 && c1[1].id === 'mid' && c1[2].id === 'low');
    check('placeRegionLabels skips when every spot collides', !c1.some((b) => b.id === 'small'));
    let crowdOverlap = false;
    for (let i = 0; i < c1.length; i++) for (let j = i + 1; j < c1.length; j++) if (hit(c1[i], c1[j])) crowdOverlap = true;
    check('placeRegionLabels fallback boxes never overlap', !crowdOverlap);
    const c2 = G.placeRegionLabels(crowd, measure, 1, 'small', view);
    check('placeRegionLabels emphasized always drawn', c2.some((b) => b.id === 'small' && b.emphasized === true));
    check('placeRegionLabels emphasized placed first', c2[0].id === 'small');
    // Clamp: a region above the view gets its pill pulled inside.
    const edge = G.placeRegionLabels([{ id: 'e', label: 'Edge', cx: 0, cy: -990, r: 80, count: 3 }], measure, 1, null, view);
    check('placeRegionLabels clamps inside the view', edge.length === 1 && edge[0].y >= view.top && edge[0].x >= view.left
        && edge[0].x + edge[0].w <= view.right && edge[0].y + edge[0].h <= view.bottom);
    // tie on size -> label asc
    const ties = G.placeRegionLabels([
        { id: 't2', label: 'Zed', cx: 0, cy: 0, r: 50, count: 4 },
        { id: 't1', label: 'Ant', cx: 900, cy: 0, r: 50, count: 4 },
    ], measure, 1, null, view);
    check('placeRegionLabels tie broken by label', ties[0].label === 'Ant');
}

// --- clampIntoRegion ----------------------------------------------------
{
    const region = { cx: 100, cy: 200, r: 50 };
    const inside = { x: 120, y: 210 };
    check('clampIntoRegion keeps an inside point', G.clampIntoRegion(inside, region) === inside);
    const onEdge = { x: 150, y: 200 };
    check('clampIntoRegion keeps a point on the edge', G.clampIntoRegion(onEdge, region) === onEdge);
    const out = G.clampIntoRegion({ x: 300, y: 200 }, region);
    check('clampIntoRegion pulls an outside point to the inset radius',
        Math.abs(Math.hypot(out.x - 100, out.y - 200) - 50 * G.SOURCE_INSET) < 1e-9 && Math.abs(out.y - 200) < 1e-9);
    const diag = G.clampIntoRegion({ x: -500, y: -500 }, region);
    check('clampIntoRegion keeps the direction from the centre',
        Math.abs((diag.x - 100) / (diag.y - 200) - (-600 / -700)) < 1e-9);
}

// --- source hygiene ------------------------------------------------------
const text = readFileSync(groupingPath, 'utf8');
for (const token of ['document', 'window', 'Math.random', 'createElementNS', '.innerHTML =', 'PALETTE']) {
    check(`grouping.js has no "${token}"`, !text.includes(token));
}

process.stdout.write(JSON.stringify({ passed, failed }) + '\n');
process.exit(failed.length ? 1 : 0);
