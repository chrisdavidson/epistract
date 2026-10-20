// Parity harness: the legend chip, nav swatch and sidebar badge swatch for every
// type must draw the same SVG shape tag and fill as typeDisplay(type) and the API payload.
// Prints one JSON line {"passed": [...], "failed": [...]} and exits 1 on failure.
import { pathToFileURL, fileURLToPath } from 'node:url';
import path from 'node:path';
import fs from 'node:fs';

function makeEl(tagName = '', namespaceURI = null) {
  const listeners = {};
  const attrs = {};
  const classes = new Set();
  return {
    tagName,
    namespaceURI,
    classList: {
      add: (...c) => c.forEach((x) => classes.add(x)),
      remove: (...c) => c.forEach((x) => classes.delete(x)),
      contains: (c) => classes.has(c),
    },
    id: '',
    className: '',
    textContent: '',
    style: {},
    children: [],
    parentNode: null,
    get firstChild() { return this.children[0] || null; },
    appendChild(c) {
      if (c.parentNode) c.parentNode.removeChild(c);
      c.parentNode = this;
      this.children.push(c);
      return c;
    },
    removeChild(c) {
      this.children = this.children.filter((x) => x !== c);
      c.parentNode = null;
      return c;
    },
    replaceChildren(...nodes) {
      this.children.forEach((c) => { c.parentNode = null; });
      this.children = [];
      nodes.forEach((n) => this.appendChild(n));
    },
    setAttribute(name, value) { attrs[name] = String(value); },
    getAttribute(name) { return name in attrs ? attrs[name] : null; },
    removeAttribute(name) { delete attrs[name]; },
    addEventListener(type, fn) { (listeners[type] ||= []).push(fn); },
  };
}

globalThis.document = {
  getElementById: () => null,
  createElement: (tag) => makeEl(String(tag).toLowerCase(), null),
  createElementNS: (ns, tag) => makeEl(String(tag), ns),
  querySelectorAll: () => [],
};
globalThis.window = makeEl('window');

const payload = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const here = path.dirname(fileURLToPath(import.meta.url));
const display = await import(
  pathToFileURL(path.join(here, '../../examples/workbench/static/display.js')).href
);

const SHAPE_TAG = {
  dot: 'circle', square: 'rect', diamond: 'polygon', triangle: 'polygon',
  triangleDown: 'polygon', hexagon: 'polygon', star: 'polygon',
};

const passed = [];
const failed = [];
function check(name, cond, detail = '') {
  if (cond) passed.push(name); else failed.push({ name, detail });
}

function shapeOf(svg) {
  return svg && svg.children.length === 1 ? svg.children[0] : null;
}

try {
  display.setDisplayData(payload);
  const entries = display.legendEntries();
  for (const t of payload.types) {
    const d = display.typeDisplay(t.type);
    check(`${t.type}: typeDisplay equals payload`, d.color === t.color && d.shape === t.shape);
    const entry = entries.find((e) => e.type === t.type);
    check(`${t.type}: legend entry exists`, !!entry);
    const chip = display.buildLegendChip(entry, () => {});
    const surfaces = {
      chip: chip.children.find((c) => c.tagName === 'svg'),
      nav: display.makeSwatch(t.type, 12),
      badge: display.makeSwatch(t.type, 16),
    };
    for (const [name, svg] of Object.entries(surfaces)) {
      const el = shapeOf(svg);
      check(`${t.type}: ${name} has one shape child`, !!el);
      if (!el) continue;
      check(
        `${t.type}: ${name} tag`,
        el.tagName === SHAPE_TAG[d.shape],
        `${el.tagName} vs ${SHAPE_TAG[d.shape]}`,
      );
      check(`${t.type}: ${name} fill`, el.getAttribute('fill') === d.color && d.color === t.color,
        `${el.getAttribute('fill')} vs ${d.color}`);
    }
  }
  const colors = payload.types.map((t) => t.color);
  check('payload colors unique', new Set(colors).size === colors.length);
  let seenSources = false;
  let sourcesLast = true;
  for (const e of entries) {
    if (e.family === 'Sources') seenSources = true;
    else if (seenSources) sourcesLast = false;
  }
  check('Sources family last', sourcesLast);
} catch (err) {
  failed.push({ name: 'harness threw', detail: String(err && err.stack || err) });
}

console.log(JSON.stringify({ passed, failed }));
process.exit(failed.length ? 1 : 0);
