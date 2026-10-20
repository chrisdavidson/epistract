// Behavioral harness for the workbench sidebar relation rows and source counts.
// Imports the real display.js, graph_style.js and sidebar.js against a stub DOM.
// argv[2] = path to a GLP-1 graph_data.json.
// Prints one JSON line {"passed": [...], "failed": [...]} and exits 1 on failure.
import { pathToFileURL, fileURLToPath } from 'node:url';
import path from 'node:path';
import fs from 'node:fs';

const violations = [];

function makeEl(id = '', tagName = '', namespaceURI = null) {
  const listeners = {};
  const attrs = {};
  const classes = new Set();
  const el = {
    id,
    tagName,
    namespaceURI,
    attributes: attrs,
    classList: {
      add: (...c) => c.forEach((x) => classes.add(x)),
      remove: (...c) => c.forEach((x) => classes.delete(x)),
      contains: (c) => classes.has(c),
    },
    className: '',
    textContent: '',
    title: '',
    value: '',
    scrollTop: 0,
    style: {},
    children: [],
    parentNode: null,
    _html: '',
    get innerHTML() { return this._html; },
    set innerHTML(v) {
      violations.push(`innerHTML set on <${tagName}>`);
      this._html = String(v);
    },
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
    setAttribute(name, value) { attrs[name] = String(value); },
    getAttribute(name) { return name in attrs ? attrs[name] : null; },
    addEventListener(type, fn) { (listeners[type] ||= []).push(fn); },
  };
  return el;
}

function makeFragment() {
  const frag = makeEl('', '#fragment');
  frag.isFragment = true;
  frag.appendChild = function (c) {
    if (c.parentNode) c.parentNode.removeChild(c);
    c.parentNode = this;
    this.children.push(c);
    return c;
  };
  return frag;
}

// Appending a fragment moves its children, like the real DOM.
function patchFragmentAppend(parent) {
  const orig = parent.appendChild;
  parent.appendChild = function (c) {
    if (c.isFragment) {
      const kids = c.children.slice();
      c.children = [];
      kids.forEach((k) => orig.call(this, k));
      return c;
    }
    return orig.call(this, c);
  };
}

const sidebar = makeEl('graph-detail-sidebar', 'div');
const body = makeEl('', 'div');
const header = makeEl('', 'div');
patchFragmentAppend(body);
sidebar.querySelector = (sel) => {
  if (sel === '.graph-detail-sidebar__body') return body;
  if (sel === '.graph-detail-sidebar__header') return header;
  return null;
};

globalThis.document = {
  getElementById: (id) => (id === 'graph-detail-sidebar' ? sidebar : null),
  createElement: (tag) => makeEl('', String(tag).toLowerCase(), null),
  createElementNS: (ns, tag) => makeEl('', String(tag), ns),
  createTextNode: (text) => ({ nodeType: 3, textContent: String(text), parentNode: null }),
  createDocumentFragment: () => {
    const f = makeFragment();
    return f;
  },
  querySelectorAll: () => [],
};
globalThis.window = makeEl('window');
globalThis.console.warn = () => {};

function textOf(el) {
  if (!el) return '';
  if (el.nodeType === 3) return el.textContent;
  return (el.textContent || '') + (el.children || []).map(textOf).join('');
}

function walk(el, fn) {
  fn(el);
  (el.children || []).forEach((c) => walk(c, fn));
}

function findAll(el, pred) {
  const out = [];
  walk(el, (n) => { if (pred(n)) out.push(n); });
  return out;
}

const here = path.dirname(fileURLToPath(import.meta.url));
const staticDir = path.join(here, '../../examples/workbench/static');
const display = await import(pathToFileURL(path.join(staticDir, 'display.js')).href);
const style = await import(pathToFileURL(path.join(staticDir, 'graph_style.js')).href);
const side = await import(pathToFileURL(path.join(staticDir, 'sidebar.js')).href);

const passed = [];
const failed = [];
function check(name, cond, detail = '') {
  if (cond) passed.push(name); else failed.push({ name, detail });
}

function degreesOf(nodes, edges) {
  const m = {};
  nodes.forEach((n) => { m[n.id] = 0; });
  edges.forEach((e) => {
    m[e.source] = (m[e.source] || 0) + 1;
    m[e.target] = (m[e.target] || 0) + 1;
  });
  return m;
}

function relationRows() {
  return findAll(body, (n) => n.className === 'graph-detail-sidebar__relation-row');
}

try {
  display.setDisplayData({
    types: [
      { type: 'DOCUMENT', color: '#6b7280', shape: 'dot', family: 'Sources', is_source: true, label: 'Document', count: 1 },
      { type: 'PUBLICATION', color: '#a8a29e', shape: 'dot', family: 'Sources', is_source: true, label: 'Publication', count: 1 },
      { type: 'COMPOUND', color: '#1f77b4', shape: 'dot', family: 'Interventions', label: 'Compound', count: 1 },
      { type: 'PROTEIN', color: '#ff7f0e', shape: 'square', family: 'Biology', label: 'Protein', count: 1 },
      { type: 'ORGANIZATION', color: '#2ca02c', shape: 'diamond', family: 'Orgs', label: 'Organization', count: 1 },
    ],
    families: [],
  });

  // (a) pure helpers
  check('a: humanize INDICATED_FOR', style.humanizeRelation('INDICATED_FOR') === 'indicated for', style.humanizeRelation('INDICATED_FOR'));
  check('a: humanize DEVELOPES', style.humanizeRelation('DEVELOPES') === 'develops', style.humanizeRelation('DEVELOPES'));
  check('a: humanize empty', style.humanizeRelation('') === '');
  check('a: humanize undefined', style.humanizeRelation(undefined) === '');
  check('a: asserted false', style.isNonAsserted('asserted') === false);
  check('a: undefined false', style.isNonAsserted(undefined) === false);
  check('a: empty false', style.isNonAsserted('') === false);
  check('a: hypothesized true', style.isNonAsserted('hypothesized') === true);
  check('a: suffix prophetic', style.statusSuffix('prophetic') === ' (prophetic)', style.statusSuffix('prophetic'));
  check('a: suffix asserted', style.statusSuffix('asserted') === '');

  const data = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
  const nodes = data.nodes;
  const edges = data.links;
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const nameOf = (id) => (byId.get(id) ? byId.get(id).name : id);

  // (b) sentence grammar on real edges
  const act = edges.find((e) => e.source === 'compound:semaglutide' && e.relation_type === 'ACTIVATES' && nameOf(e.target) === 'GLP-1 receptor');
  check('b: ACTIVATES edge exists', Boolean(act));
  if (act) {
    const s = style.relationSentence(style.relationRowParts(act, 'compound:semaglutide', nameOf));
    check('b: outgoing sentence', s === 'activates → GLP-1 receptor', s);
  }
  const dev = edges.find((e) => e.target === 'compound:semaglutide' && e.relation_type === 'DEVELOPES' && nameOf(e.source) === 'Novo Nordisk AS');
  check('b: DEVELOPES edge exists', Boolean(dev));
  if (dev) {
    const s = style.relationSentence(style.relationRowParts(dev, 'compound:semaglutide', nameOf));
    check('b: incoming sentence', s === 'Novo Nordisk AS · develops →', s);
  }
  const loop = style.relationRowParts({ source: 'x', target: 'x', relation_type: 'RELATED_TO' }, 'x', () => 'X');
  check('b: self-loop is outgoing', loop.direction === 'out', loop.direction);

  // (c) semaglutide sidebar
  side.initSidebar();
  side.showNodeDetail('compound:semaglutide', nodes, edges, degreesOf(nodes, edges));
  const rows = relationRows();
  check('c: 60 relation rows', rows.length === 60, String(rows.length));
  const texts = rows.map(textOf);
  check('c: no arrow-left', texts.every((t) => !t.includes('←')));
  check('c: no MENTIONED_IN rows', texts.every((t) => !/mentioned in/i.test(t) && !t.includes('MENTIONED_IN')));
  check('c: has incoming row', texts.some((t) => t.includes(' · ') && t.endsWith('→')));
  check('c: has Novo develops row', texts.includes('Novo Nordisk AS · develops →'));
  check('c: has activates row', texts.includes('activates → GLP-1 receptor'));
  const attrRows = findAll(body, (n) => n.className === 'graph-detail-sidebar__attr-row');
  const srcRow = attrRows.find((r) => textOf(r).startsWith('Sources:'));
  check('c: Sources row value 17', srcRow && srcRow.children[1].textContent === '17', srcRow && textOf(srcRow));
  const labels = findAll(body, (n) => n.className === 'graph-detail-sidebar__section-label').map(textOf);
  check('c: Source Documents (17) label', labels.includes('Source Documents (17)'), JSON.stringify(labels));

  // (d) hostile names
  const evil = '<img src=x onerror=alert(1)>';
  const hn = [
    { id: 'a', name: evil, entity_type: 'COMPOUND', source_documents: [evil] },
    { id: 'b', name: 'B', entity_type: 'PROTEIN', source_documents: [] },
  ];
  const he = [{ source: 'b', target: 'a', relation_type: evil, epistemic_status: evil }];
  side.showNodeDetail('a', hn, he, degreesOf(hn, he));
  const hrows = relationRows();
  check('d: one hostile row', hrows.length === 1, String(hrows.length));
  check('d: relation text literal', hrows.length === 1 && textOf(hrows[0]).includes('B · '), hrows[0] && textOf(hrows[0]));
  check('d: no innerHTML', violations.length === 0, violations.join('; '));
  side.showNodeDetail('b', hn, he, degreesOf(hn, he));
  check('d: hostile name as text', relationRows().some((r) => textOf(r).includes(evil)));
  check('d: no innerHTML after second render', violations.length === 0, violations.join('; '));
} catch (e) {
  failed.push({ name: 'harness error', detail: String((e && e.stack) || e) });
}

console.log(JSON.stringify({ passed, failed }));
process.exit(failed.length ? 1 : 0);
