// Behavioral harness for graph.js node filtering (WR-02).
// Loads the real graph.js against a permissive stub DOM, a stub vis.js and a
// stub fetch. argv[2] = "ok" serves a working /api/graph/entity-types payload;
// argv[2] = "fail" makes that endpoint return 500. After initGraph() and the
// graph load, a search "input" event triggers filterGraph(); the harness prints
// {"hidden": [...ids], "total": n} as one JSON line.
// argv[2] = "sources" / "nosources" exercise the Show sources toolbar button:
// the harness prints {initialHidden, initialHiddenEdges, afterShow, pressed,
// label, afterHide, disabled} read straight from the captured DataSets.
import { pathToFileURL, fileURLToPath } from 'node:url';
import path from 'node:path';

const mode = process.argv[2] || 'ok';

function makeEl(id = '') {
  const listeners = {};
  const attrs = new Map();
  const el = {
    id,
    value: '',
    textContent: '',
    className: '',
    style: {},
    children: [],
    dataset: {},
    classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
    addEventListener(type, fn) { (listeners[type] = listeners[type] || []).push(fn); },
    removeEventListener() {},
    dispatch(type) { for (const fn of listeners[type] || []) fn({ target: el }); },
    appendChild(c) { el.children.push(c); return c; },
    append(...cs) { el.children.push(...cs); },
    replaceChildren(...cs) { el.children = cs; },
    removeChild() {},
    remove() {},
    setAttribute(k, v) { attrs.set(k, String(v)); },
    getAttribute: (k) => (attrs.has(k) ? attrs.get(k) : null),
    removeAttribute(k) { attrs.delete(k); },
    hasAttribute: (k) => attrs.has(k),
    querySelector: () => null,
    querySelectorAll: () => [],
    contains: () => false,
    getBoundingClientRect: () => ({ left: 0, top: 0, width: 800, height: 600 }),
    focus() {},
    get firstChild() { return el.children[0] || null; },
    innerHTML: '',
    offsetWidth: 800,
    offsetHeight: 600,
    clientWidth: 800,
    clientHeight: 600,
  };
  return el;
}

const elements = new Map();
globalThis.document = {
  getElementById(id) {
    if (!elements.has(id)) elements.set(id, makeEl(id));
    return elements.get(id);
  },
  createElement: () => makeEl(),
  createElementNS: () => makeEl(),
  createDocumentFragment: () => makeEl(),
  createTextNode: (t) => ({ textContent: t }),
  addEventListener() {},
  querySelector: () => null,
  querySelectorAll: () => [],
  body: makeEl('body'),
};

const datasets = [];
class DataSet {
  constructor(items) { datasets.push(this); this.items = new Map(items.map((i) => [i.id ?? Math.random(), { ...i }])); }
  update(us) { for (const u of [].concat(us)) this.items.set(u.id, { ...(this.items.get(u.id) || {}), ...u }); }
  get(id) { return id === undefined ? [...this.items.values()] : this.items.get(id); }
  getIds() { return [...this.items.keys()]; }
  forEach(fn) { this.items.forEach((v) => fn(v)); }
}
// Network: every method is a no-op; getScale/getPositions return sane values.
class Network {
  constructor() {
    return new Proxy(this, {
      get(target, prop) {
        if (prop === 'getScale') return () => 1;
        if (prop === 'getPositions') return () => ({});
        if (prop === 'getSelectedNodes') return () => [];
        if (prop === 'body') return { data: { nodes: new DataSet([]) } };
        if (prop === 'then') return undefined;
        return () => undefined;
      },
    });
  }
}
const vis = { DataSet, Network };
globalThis.vis = vis;
globalThis.window = {
  vis,
  addEventListener() {},
  removeEventListener() {},
  innerWidth: 1200,
  innerHeight: 800,
};

const withSources = mode === 'sources';
const NODES = [
  { id: 'a', name: 'Aspirin', entity_type: 'COMPOUND' },
  { id: 'b', name: 'Diabetes', entity_type: 'DISEASE' },
  { id: 'c', name: 'Mystery', entity_type: null },
  ...(withSources ? [{ id: 'd1', name: 'Doc one', entity_type: 'DOCUMENT' }] : []),
];
const EDGES = withSources
  ? [
    { source: 'a', target: 'd1', relation_type: 'MENTIONED_IN' },
    { source: 'a', target: 'b', relation_type: 'TREATS' },
  ]
  : mode === 'nosources'
    ? [{ source: 'a', target: 'b', relation_type: 'TREATS' }]
    : [];
const DISPLAY = {
  types: [
    { type: 'COMPOUND', color: '#5f66ed', shape: 'hexagon', family: 'Interventions', count: 1 },
    { type: 'DISEASE', color: '#249e02', shape: 'square', family: 'Conditions', count: 1 },
    { type: 'UNKNOWN', color: '#ed4b43', shape: 'dot', family: 'Other', count: 1 },
    ...(withSources
      ? [{
        type: 'DOCUMENT', color: '#6b7280', shape: 'dot', family: 'Sources',
        is_source: true, count: 1,
      }]
      : []),
  ],
  families: [{ name: 'Interventions' }, { name: 'Conditions' }, { name: 'Other' }],
  relations: withSources
    ? { MENTIONED_IN: { category: 'provenance', source_edge: true, description: '' } }
    : {},
};

function respond(status, body) {
  return { ok: status < 400, status, statusText: String(status), json: async () => body };
}
globalThis.fetch = async (url) => {
  if (url === '/api/graph/entity-types') {
    return mode === 'fail' ? respond(500, {}) : respond(200, DISPLAY);
  }
  if (url === '/api/graph') return respond(200, { nodes: NODES, edges: EDGES });
  return respond(404, {});
};
console.warn = () => {};
console.error = () => {};

const here = path.dirname(fileURLToPath(import.meta.url));
const graphJs = path.resolve(here, '..', '..', 'examples', 'workbench', 'static', 'graph.js');
const graph = await import(pathToFileURL(graphJs).href);

await graph.initGraph({});
// Let loadGraphData's fetches and buildGraph settle.
for (let i = 0; i < 20; i++) await new Promise((r) => setTimeout(r, 0));

if (mode === 'sources' || mode === 'nosources') {
  const nodeSet = () => [...datasets].reverse().find((d) => [...d.items.values()].some((i) => 'label' in i));
  const edgeSet = () => [...datasets].reverse().find((d) => [...d.items.values()].some((i) => 'from' in i));
  const hiddenNodes = () => [...nodeSet().items.values()].filter((i) => i.hidden).map((i) => i.id);
  const hiddenEdges = () => [...edgeSet().items.values()].filter((i) => i.hidden).length;
  const btn = document.getElementById('graph-show-sources-btn');
  const label = () => (btn.children[0] ? btn.children[0].textContent : btn.textContent);
  const out = {
    initialHidden: hiddenNodes(),
    initialHiddenEdges: hiddenEdges(),
    disabled: btn.hasAttribute('disabled'),
  };
  if (!out.disabled) {
    btn.dispatch('click');
    out.afterShow = hiddenNodes();
    out.pressed = btn.getAttribute('aria-pressed');
    out.label = label();
    btn.dispatch('click');
    out.afterHide = hiddenNodes();
  }
  process.stdout.write(JSON.stringify(out) + '\n');
  process.exit(0);
}

// graph.js keeps its DataSet private, so spy on DataSet.update while a search
// "input" event runs filterGraph(), and read the node visibility it applies.
const search = document.getElementById('graph-search');
search.value = '';
const seen = [];
const origUpdate = DataSet.prototype.update;
DataSet.prototype.update = function spy(us) {
  seen.push(...[].concat(us));
  return origUpdate.call(this, us);
};
search.dispatch('input');
DataSet.prototype.update = origUpdate;
const nodeUpdates = seen.filter((u) => NODES.some((n) => n.id === u.id) && 'hidden' in u);

process.stdout.write(JSON.stringify({
  hidden: nodeUpdates.filter((u) => u.hidden).map((u) => u.id),
  total: nodeUpdates.length,
}) + '\n');
process.exit(0);
