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

// --- source hygiene ------------------------------------------------------
const text = readFileSync(groupingPath, 'utf8');
for (const token of ['document', 'window', 'Math.random']) {
    check(`grouping.js has no "${token}"`, !text.includes(token));
}

process.stdout.write(JSON.stringify({ passed, failed }) + '\n');
process.exit(failed.length ? 1 : 0);
