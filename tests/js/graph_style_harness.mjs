// Pure assertions for the scale-aware helpers in graph_style.js.
// Prints one JSON line {"passed": n, "failed": [...]} and exits 1 on failure.
import { pathToFileURL, fileURLToPath } from 'node:url';
import path from 'node:path';

const here = path.dirname(fileURLToPath(import.meta.url));
const stylePath = path.resolve(here, '..', '..', 'examples', 'workbench', 'static', 'graph_style.js');
const S = await import(pathToFileURL(stylePath).href);

let passed = 0;
const failed = [];
function check(name, cond) {
  if (cond) passed++;
  else failed.push(name);
}

const SCALES = [0.05, 0.1, 0.1375, 0.2, 0.5, 1, 1.5, 2];

for (const s of SCALES) {
  check(`labelFontSize px @${s}`, S.labelFontSize(s) * s >= 10 - 1e-9);
  check(`labelFontSize cap @${s}`, S.labelFontSize(s) <= 240);
  for (let d = 0; d <= 60; d++) {
    check(`nodeSize px d=${d} @${s}`, S.nodeSize(d, 60, s, false) * s >= 3.5 - 1e-9);
    check(`source nodeSize px d=${d} @${s}`, S.nodeSize(d, 60, s, true) * s >= 3 - 1e-9);
  }
  check(`nodeSize hub bigger @${s}`, S.nodeSize(60, 60, s, false) > S.nodeSize(0, 60, s, false));
  for (const sc of [undefined, 0, 1, 2, 3, 11, 100, -5, 1e9, 'x']) {
    const px = S.edgeWidth(sc, s) * s;
    check(`edgeWidth px sc=${sc} @${s}`, px >= 1.4 - 1e-9 && px <= 4 + 1e-9);
  }
}
for (let d = 0; d <= 60; d++) {
  check(`nodeSize world floor d=${d}`, S.nodeSize(d, 60, 1, false) >= 8 + Math.round((d / 60) * 16));
}
check('edgeWidth grows with support', S.edgeWidth(11, 1) > S.edgeWidth(1, 1));

check('scaleBucket differs fit vs 1', S.scaleBucket(0.1375) !== S.scaleBucket(1));
let prev = -Infinity;
let mono = true;
for (let s = 0.01; s < 4; s += 0.01) {
  const b = S.scaleBucket(s);
  if (b < prev) mono = false;
  prev = b;
}
check('scaleBucket monotone', mono);

check('truncate short', S.truncateLabel('abc', 22) === 'abc');
const long = 'x'.repeat(30);
const t = S.truncateLabel(long, 22);
check('truncate long length', Array.from(t).length === 22);
check('truncate long ellipsis', t.endsWith('…'));
const astral = '\u{1F600}'.repeat(30);
const ta = Array.from(S.truncateLabel(astral, 22));
check('truncate astral', ta.length === 22 && ta[0] === '\u{1F600}' && ta[21] === '…');
check('truncate null', S.truncateLabel(null) === '');

check('labelCutoff budget', S.labelCutoff([60, 40, 10, 10, 5], 3) === 10);
check('labelCutoff infinity', S.labelCutoff([60, 40, 10, 10, 5], Infinity) === 0);

const ids = S.stableEdgeIds([{ relation_id: 'r1' }, { relation_id: 'r1' }, {}, { relation_id: '' }]);
check('stableEdgeIds values', JSON.stringify(ids) === JSON.stringify(['r1', 'e1', 'e2', 'e3']));
check('stableEdgeIds unique', new Set(ids).size === ids.length);
const clash = S.stableEdgeIds([{}, { relation_id: 'e0' }, { relation_id: 7 }]);
check('stableEdgeIds clash unique', new Set(clash).size === 3 && clash.every((x) => typeof x === 'string'));

const hubEdges = Array.from({ length: 60 }, (_, i) => `h${i}`);
const smallEdges = ['s0', 's1', 's2'];
check('edge names: hub > cap names none', S.namedEdgeIds([hubEdges], null).size === 0);
check('edge names: hovered edge on hub names one', (() => { const n = S.namedEdgeIds([hubEdges], 'h5'); return n.size === 1 && n.has('h5'); })());
check('edge names: small node names all', S.namedEdgeIds([smallEdges], null).size === 3);
check('edge names: exactly cap names all', S.namedEdgeIds([hubEdges.slice(0, S.EDGE_NAME_MAX_EDGES)], null).size === S.EDGE_NAME_MAX_EDGES);
check('edge names: cap constant', S.EDGE_NAME_MAX_EDGES === 12);

process.stdout.write(JSON.stringify({ passed, failed }) + '\n');
process.exit(failed.length ? 1 : 0);
