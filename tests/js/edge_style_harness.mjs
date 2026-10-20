// Behavioral harness for edge color/dash helpers in display.js and graph_style.js.
// argv[2] = path to a /api/graph/entity-types payload. Prints one JSON line
// {"passed": [...], "failed": [...]} and exits 1 on failure.
import { pathToFileURL, fileURLToPath } from 'node:url';
import path from 'node:path';
import fs from 'node:fs';

function makeEl(tag = '', ns = null) {
  const attrs = {};
  return {
    tagName: tag,
    namespaceURI: ns,
    attrs,
    children: [],
    setAttribute(k, v) { attrs[k] = String(v); },
    getAttribute: (k) => (k in attrs ? attrs[k] : null),
    removeAttribute(k) { delete attrs[k]; },
    appendChild(c) { this.children.push(c); return c; },
  };
}
globalThis.document = {
  createElement: (t) => makeEl(t),
  createElementNS: (ns, t) => makeEl(t, ns),
  getElementById: () => null,
};
globalThis.window = {};

const payload = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const here = path.dirname(fileURLToPath(import.meta.url));
const base = path.join(here, '../../examples/workbench/static');
const display = await import(pathToFileURL(path.join(base, 'display.js')).href);
const style = await import(pathToFileURL(path.join(base, 'graph_style.js')).href);

const passed = [];
const failed = [];
function check(name, cond, detail = '') {
  if (cond) passed.push(name); else failed.push({ name, detail });
}
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);

try {
  // No display data yet: neutral fallback.
  check('no data: neutral', display.relationDisplay('TREATS').color === '#8b8f99');
  check('no data: no categories', display.categoryEntries().length === 0);

  display.setDisplayData(payload);
  for (const [rel, spec] of Object.entries(payload.relations)) {
    check(`served color ${rel}`, display.relationDisplay(rel).color === spec.color, rel);
  }
  const cats = display.categoryEntries();
  check('category order', same(cats.map((c) => c.name), Object.keys(payload.categories)));
  const otherColor = payload.categories.other.color;
  check('unknown relation -> other', display.relationDisplay('NOT_A_REL').category === 'other'
    && display.relationDisplay('NOT_A_REL').color === otherColor);

  // Hostile colors fall back to the other category color.
  const bad = JSON.parse(JSON.stringify(payload));
  const names = Object.keys(bad.relations);
  bad.relations[names[0]].color = 'red';
  bad.relations[names[1]].color = '<x>';
  display.setDisplayData(bad);
  check('red -> other color', display.relationDisplay(names[0]).color !== 'red');
  check('<x> -> safe color', /^#[0-9a-f]{6}$/i.test(display.relationDisplay(names[1]).color));

  // Dashes
  check('dash hypothesized', same(style.edgeDashes('hypothesized', 0.5), [14, 10]));
  check('dash asserted', style.edgeDashes('asserted', 0.5) === false);
  check('dash undefined', style.edgeDashes(undefined, 0.5) === false);
  check('dash constants', style.EDGE_BASE_OPACITY === 0.8 && style.EDGE_DIM_OPACITY === 0.15);

  // Complete color object
  check('color object', same(style.edgeColorObject('#009e73', 0.8), {
    color: '#009e73',
    highlight: { color: '#009e73', opacity: 1 },
    hover: { color: '#009e73', opacity: 1 },
    inherit: false,
    opacity: 0.8,
  }));

  // Edge sample
  const svg = display.makeEdgeSample('#009e73', { dashed: true });
  check('sample is svg', svg.tagName === 'svg' && svg.children.length === 1);
  const line = svg.children[0];
  check('sample line', line.tagName === 'line' && line.attrs.stroke === '#009e73'
    && line.attrs['stroke-dasharray']);
  const solid = display.makeEdgeSample('#009e73');
  check('solid sample no dasharray', !('stroke-dasharray' in solid.children[0].attrs));
  const evil = display.makeEdgeSample('javascript:x');
  check('sample neutral on bad color', evil.children[0].attrs.stroke === '#8b8f99');
} catch (err) {
  failed.push({ name: 'exception', detail: String(err && err.stack || err) });
}

process.stdout.write(JSON.stringify({ passed, failed }) + '\n');
process.exit(failed.length ? 1 : 0);
