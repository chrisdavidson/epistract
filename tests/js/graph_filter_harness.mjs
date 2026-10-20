// Behavioral harness for graph.js node filtering (WR-02).
// Loads the real graph.js against a permissive stub DOM, a stub vis.js and a
// stub fetch. argv[2] = "ok" serves a working /api/graph/entity-types payload;
// argv[2] = "fail" makes that endpoint return 500. After initGraph() and the
// graph load, a search "input" event triggers filterGraph(); the harness prints
// {"hidden": [...ids], "total": n} as one JSON line.
// argv[2] = "sources" / "nosources" exercise the Show sources toolbar button:
// the harness prints {initialHidden, initialHiddenEdges, afterShow, pressed,
// label, afterHide, disabled} read straight from the captured DataSets.
// argv[2] = "edges" / "edges-fail" check edge category colors, dashes and the
// complete color objects restored after a neighbourhood highlight is cleared.
// argv[2] = "fit" fires the recorded stabilization handler at scale 0.1375 and
// prints {fitBeforeFont, minLabelPx, minNodePx, minEdgePx, edgeIdsAreStrings}.
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
const FIT_SCALE = 0.1375;
const handlers = new Map();
const calls = [];
let order = 0;
class DataSet {
  constructor(items) { datasets.push(this); this.items = new Map(items.map((i) => [i.id ?? Math.random(), { ...i }])); }
  update(us) {
    for (const u of [].concat(us)) {
      calls.push({ kind: 'update', order: order++, u: JSON.parse(JSON.stringify(u)) });
      this.items.set(u.id, { ...(this.items.get(u.id) || {}), ...u });
    }
  }
  get(id) { return id === undefined ? [...this.items.values()] : this.items.get(id); }
  getIds() { return [...this.items.keys()]; }
  forEach(fn) { this.items.forEach((v) => fn(v)); }
}
// Network: every method is a no-op; getScale/getPositions return sane values.
class Network {
  constructor() {
    return new Proxy(this, {
      get(target, prop) {
        if (prop === 'getScale') return () => (mode === 'fit' ? FIT_SCALE : 1);
        if (prop === 'on' || prop === 'once') {
          return (event, fn) => { (handlers.get(event) || handlers.set(event, []).get(event)).push(fn); };
        }
        if (prop === 'fit') {
          return (opts) => { calls.push({ kind: 'fit', order: order++, opts }); };
        }
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
const FIT_NODES = [{ id: 'hub', name: 'Hub compound', entity_type: 'COMPOUND' }];
const FIT_EDGES = [];
for (let i = 0; i < 90; i++) {
  FIT_NODES.push({ id: `n${i}`, name: `Compound number ${i}`, entity_type: 'COMPOUND' });
  if (i > 0) {
    FIT_EDGES.push({
      source: `n${i - 1}`, target: `n${i}`, relation_type: 'TREATS',
      relation_id: `r${i}`, support_count: (i % 11) + 1,
    });
  }
  if (i < 30) {
    FIT_EDGES.push({
      source: 'hub', target: `n${i}`, relation_type: 'TREATS',
      relation_id: `h${i}`, support_count: (i % 11) + 1,
    });
  }
}
const isEdges = mode === 'edges' || mode === 'edges-fail';
const EDGE_NODES = [
  { id: 'a', name: 'Aspirin', entity_type: 'COMPOUND' },
  { id: 'b', name: 'Diabetes', entity_type: 'DISEASE' },
  { id: 'c', name: 'Target', entity_type: 'COMPOUND' },
];
const EDGE_EDGES = [
  { source: 'a', target: 'b', relation_type: 'TREATS', relation_id: 'r1', epistemic_status: 'asserted' },
  { source: 'a', target: 'c', relation_type: 'INHIBITS', relation_id: 'r2', epistemic_status: 'hypothesized' },
  { source: 'b', target: 'c', relation_type: 'NOT_IN_SCHEMA', relation_id: 'r3' },
];
const NODES = isEdges ? EDGE_NODES : mode === 'fit' ? FIT_NODES : [
  { id: 'a', name: 'Aspirin', entity_type: 'COMPOUND' },
  { id: 'b', name: 'Diabetes', entity_type: 'DISEASE' },
  { id: 'c', name: 'Mystery', entity_type: null },
  ...(withSources ? [{ id: 'd1', name: 'Doc one', entity_type: 'DOCUMENT' }] : []),
];
const EDGES = isEdges ? EDGE_EDGES : mode === 'fit' ? FIT_EDGES : withSources
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
    : isEdges
      ? {
        TREATS: { category: 'therapeutic', color: '#009e73', source_edge: false, description: '' },
        INHIBITS: { category: 'mechanism', color: '#0072b2', source_edge: false, description: '' },
      }
      : {},
  categories: {
    mechanism: { label: 'Mechanism', color: '#0072b2' },
    therapeutic: { label: 'Therapeutic', color: '#009e73' },
    other: { label: 'Other', color: '#8b8f99' },
  },
};

function respond(status, body) {
  return { ok: status < 400, status, statusText: String(status), json: async () => body };
}
globalThis.fetch = async (url) => {
  if (url === '/api/graph/entity-types') {
    return (mode === 'fail' || mode === 'edges-fail') ? respond(500, {}) : respond(200, DISPLAY);
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

if (mode === 'fit') {
  calls.length = 0;
  for (const fn of [...(handlers.get('stabilizationIterationsDone') || [])]) fn();
  const firstFit = calls.find((c) => c.kind === 'fit' && c.opts && c.opts.animation === false);
  const fontWrites = calls.filter((c) => c.kind === 'update' && c.u.font && c.u.font.size > 0);
  const nodeDs = [...datasets].reverse().find((d) => [...d.items.values()].some((i) => 'label' in i && !('from' in i)));
  const edgeDs = [...datasets].reverse().find((d) => [...d.items.values()].some((i) => 'from' in i));
  const nodes = [...nodeDs.items.values()];
  const edges = [...edgeDs.items.values()];
  const out = {
    fitBeforeFont: Boolean(firstFit) && fontWrites.length > 0 && fontWrites.every((c) => c.order > firstFit.order),
    minLabelPx: fontWrites.length
      ? Math.min(...fontWrites.map((c) => c.u.font.size * FIT_SCALE))
      : 0,
    labelled: fontWrites.length,
    minNodePx: Math.min(...nodes.map((n) => n.size * FIT_SCALE)),
    minEdgePx: Math.min(...edges.map((e) => (typeof e.width === 'number' ? e.width * FIT_SCALE : 0))),
    edgeIdsAreStrings: edges.every((e) => typeof e.id === 'string'),
  };
  process.stdout.write(JSON.stringify(out) + '\n');
  process.exit(0);
}

if (isEdges) {
  const edgeSet = () => [...datasets].reverse().find((d) => [...d.items.values()].some((i) => 'from' in i));
  const record = (id) => edgeSet().items.get(id);
  const passed = [];
  const failed = [];
  const check = (name, cond, detail = '') => {
    if (cond) passed.push(name); else failed.push({ name, detail: JSON.stringify(detail) });
  };
  const complete = (e, color, opacity) => e.color && e.color.color === color
    && e.color.opacity === opacity && e.color.inherit === false
    && e.color.highlight === color
    && e.color.hover === color;
  const colors = mode === 'edges'
    ? { r1: '#009e73', r2: '#0072b2', r3: '#8b8f99' }
    : { r1: '#8b8f99', r2: '#8b8f99', r3: '#8b8f99' };
  for (const id of ['r1', 'r2', 'r3']) {
    check(`${id} initial color`, complete(record(id), colors[id], 0.8), record(id).color);
  }
  check('asserted solid', record('r1').dashes === false, record('r1').dashes);
  check('missing status solid', record('r3').dashes === false, record('r3').dashes);
  check('hypothesized dashed', Array.isArray(record('r2').dashes)
    && record('r2').dashes[0] === 7 && record('r2').dashes[1] === 5, record('r2').dashes);
  check('width stays numeric', typeof record('r1').width === 'number');
  const click = (params) => { for (const fn of handlers.get('click') || []) fn(params); };
  click({ nodes: ['a'], edges: [] });
  click({ nodes: [], edges: [] });
  for (const id of ['r1', 'r2', 'r3']) {
    check(`${id} restored`, complete(record(id), colors[id], 0.8), record(id).color);
  }
  const panel = document.getElementById('edge-key');
  const toggle = document.getElementById('edge-key-toggle');
  if (mode === 'edges') {
    check('edge key rows', panel.children.length === 4, panel.children.length);
    check('edge key toggle visible', !toggle.hasAttribute('hidden'));
    toggle.dispatch('click');
    check('edge key opens', toggle.getAttribute('aria-expanded') === 'true' && !panel.hasAttribute('hidden'));
  } else {
    check('edge key hidden on failure', toggle.hasAttribute('hidden') && panel.hasAttribute('hidden'));
  }
  check('dash survives highlight', Array.isArray(record('r2').dashes));
  process.stdout.write(JSON.stringify({ passed, failed }) + '\n');
  process.exit(failed.length ? 1 : 0);
}

if (mode === 'sources' || mode === 'nosources') {
  const nodeSet = () => [...datasets].reverse().find((d) => [...d.items.values()].some((i) => 'label' in i && !('from' in i)));
  const edgeSet = () => [...datasets].reverse().find((d) => [...d.items.values()].some((i) => 'from' in i));
  const hiddenNodes = () => [...nodeSet().items.values()].filter((i) => i.hidden).map((i) => i.id);
  const hiddenEdges = () => [...edgeSet().items.values()].filter((i) => i.hidden).length;
  const btn = document.getElementById('graph-show-sources-btn');
  const label = () => (btn.children[0] ? btn.children[0].textContent : btn.textContent);
  // WR-02: ids of nodes / relation types of edges excluded from physics.
  const noPhysics = () => ({
    nodes: [...nodeSet().items.values()].filter((i) => i.physics === false).map((i) => i.id),
    edges: [...edgeSet().items.values()].filter((i) => i.physics === false).map((i) => i._data.relation_type),
  });
  const out = {
    initialHidden: hiddenNodes(),
    initialHiddenEdges: hiddenEdges(),
    initialNoPhysics: noPhysics(),
    disabled: btn.hasAttribute('disabled'),
  };
  if (!out.disabled) {
    btn.dispatch('click');
    out.afterShow = hiddenNodes();
    out.afterShowNoPhysics = noPhysics();
    out.pressed = btn.getAttribute('aria-pressed');
    out.label = label();
    btn.dispatch('click');
    out.afterHide = hiddenNodes();
    out.afterHideNoPhysics = noPhysics();
    // WR-01: a min-degree threshold must not hide source nodes while shown.
    const slider = document.getElementById('min-degree-slider');
    slider.value = '1';
    slider.dispatch('input');
    btn.dispatch('click');
    out.afterShowMinDegree1 = hiddenNodes();
    out.pressedMinDegree1 = btn.getAttribute('aria-pressed');
    btn.dispatch('click');
    slider.value = '0';
    slider.dispatch('input');
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
