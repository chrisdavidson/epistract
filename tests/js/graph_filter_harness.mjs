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
// argv[2] = "groups" serves a /api/graph/groups payload and prints the grouped
// default build facts (anchors, iterations, fit set, anchor edges after a
// filter). Every other mode gets a 404 there and builds ungrouped.
// argv[2] = "regions" serves a payload with a hostile label, drives the
// beforeDrawing/afterDrawing handlers with a recording canvas context and the
// Groups button and list through the fake DOM.
// argv[2] = "control" / "control-nocomm" / "control-fail" / "control-sources"
// drive the Group by radiogroup: relayout lifecycle, fallback without topic
// clusters, relayout failure recovery and group-aware source placement. In
// "ok" (groups 404) the harness also reports the load-failure control state.
import { pathToFileURL, fileURLToPath } from 'node:url';
import path from 'node:path';

const mode = process.argv[2] || 'ok';
const isRegions = mode === 'regions';
const isControl = mode.startsWith('control');

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
    dispatch(type, extra = {}) {
      for (const fn of [...(listeners[type] || [])]) fn({ target: el, preventDefault() {}, ...extra });
    },
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
    focus() { globalThis.__focused = el; },
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

const GROUP_MODES = ['cluster', 'family', 'none'];
const groupButtons = {};
for (const m of GROUP_MODES) {
  const b = makeEl(`group-${m}`);
  b.setAttribute('data-mode', m);
  b.setAttribute('role', 'radio');
  groupButtons[m] = b;
}
document.getElementById('graph-group').querySelectorAll = () => GROUP_MODES.map((m) => groupButtons[m]);

// World positions the control modes read and write through getPositions/moveNode.
const WORLD_DEFAULT = {
  a: { x: 0, y: 0 }, e: { x: 40, y: 0 }, b: { x: 1000, y: 0 }, c: { x: 1040, y: 0 },
  f: { x: 0, y: 1000 }, g: { x: 40, y: 1000 }, d1: { x: 500, y: 500 },
};
const world = new Map(Object.entries(WORLD_DEFAULT).map(([k, v]) => [k, { ...v }]));
const onceFns = new WeakSet();
const datasets = [];
const FIT_SCALE = 0.1375;
const handlers = new Map();
const calls = [];
let order = 0;
class DataSet {
  constructor(items) { datasets.push(this); this.items = new Map(items.map((i) => [i.id ?? Math.random(), { ...i }])); }
  get length() { return this.items.size; }
  add(us) {
    for (const u of [].concat(us)) {
      calls.push({ kind: 'add', order: order++, u: JSON.parse(JSON.stringify(u)) });
      this.items.set(u.id, { ...u });
    }
  }
  remove(ids) {
    for (const id of [].concat(ids)) {
      const key = typeof id === 'object' && id !== null ? id.id : id;
      calls.push({ kind: 'remove', order: order++, id: key });
      this.items.delete(key);
    }
  }
  update(us) {
    for (const u of [].concat(us)) {
      calls.push({ kind: 'update', order: order++, u: JSON.parse(JSON.stringify(u)) });
      this.items.set(u.id, { ...(this.items.get(u.id) || {}), ...u });
    }
  }
  get(arg) {
    if (arg === undefined) return [...this.items.values()];
    if (typeof arg === 'function') return [...this.items.values()].filter(arg);
    if (arg && typeof arg === 'object') {
      const all = [...this.items.values()];
      return typeof arg.filter === 'function' ? all.filter(arg.filter) : all;
    }
    return this.items.get(arg);
  }
  getIds() { return [...this.items.keys()]; }
  forEach(fn) { this.items.forEach((v) => fn(v)); }
}
// Network: every method is a no-op; getScale/getPositions return sane values.
let networkOptions = null;
const networkCalls = [];
class Network {
  constructor(container, data, options) {
    networkOptions = options;
    return new Proxy(this, {
      get(target, prop) {
        if (prop === 'getScale') return () => (mode === 'fit' ? FIT_SCALE : 1);
        if (prop === 'on' || prop === 'once') {
          return (event, fn) => {
            if (prop === 'once') onceFns.add(fn);
            (handlers.get(event) || handlers.set(event, []).get(event)).push(fn);
          };
        }
        if (prop === 'off') {
          return (event, fn) => {
            const list = handlers.get(event);
            if (list && fn) handlers.set(event, list.filter((h) => h !== fn));
          };
        }
        if (prop === 'stabilize') {
          return (...args) => {
            if (globalThis.__stabilizeThrows) throw new Error('stabilize failed');
            networkCalls.push({ kind: 'stabilize', args });
          };
        }
        if (prop === 'moveNode' && isControl) {
          return (id, x, y) => { world.set(id, { x, y }); networkCalls.push({ kind: 'moveNode', args: [id, x, y] }); };
        }
        if (prop === 'fit') {
          return (opts) => { calls.push({ kind: 'fit', order: order++, opts }); };
        }
        if (prop === 'setOptions' || prop === 'moveTo' || prop === 'moveNode') {
          return (...args) => { networkCalls.push({ kind: String(prop), args }); };
        }
        if (prop === 'DOMtoCanvas') {
          return (p) => ({ x: -300 + p.x * 2.25, y: -300 + p.y * 3 });
        }
        if (prop === 'getPositions') {
          if (isControl) {
            return (ids) => Object.fromEntries((ids || [...world.keys()]).map((id) => [id, { ...(world.get(id) || { x: 0, y: 0 }) }]));
          }
          if (isRegions) {
            const table = {
              a: { x: 0, y: 0 }, e: { x: 40, y: 0 }, b: { x: 1000, y: 0 }, c: { x: 1040, y: 0 },
              f: { x: 0, y: 1000 }, g: { x: 40, y: 1000 },
            };
            return (ids) => Object.fromEntries((ids || []).filter((id) => table[id]).map((id) => [id, table[id]]));
          }
          if (mode !== 'groups') return () => ({});
          return (ids) => Object.fromEntries((ids || []).map((id, i) => [id, { x: i * 10, y: i * 5 }]));
        }
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

const isGroups = mode === 'groups' || isRegions || isControl;
const withSources = mode === 'sources' || isGroups;
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
  ...(isGroups ? [{ id: 'e', name: 'Empagliflozin', entity_type: 'COMPOUND' }] : []),
  ...(isRegions || isControl ? [{ id: 'f', name: 'Fenofibrate', entity_type: 'COMPOUND' }, { id: 'g', name: 'Gemfibrozil', entity_type: 'COMPOUND' }] : []),
  ...(withSources ? [{ id: 'd1', name: 'Doc one', entity_type: 'DOCUMENT' }] : []),
];
const EDGES = isEdges ? EDGE_EDGES : mode === 'fit' ? FIT_EDGES : isGroups
  ? [
    { source: 'a', target: 'd1', relation_type: 'MENTIONED_IN' },
    { source: 'e', target: 'd1', relation_type: 'MENTIONED_IN' },
    { source: 'b', target: 'd1', relation_type: 'MENTIONED_IN' },
    { source: 'a', target: 'b', relation_type: 'TREATS' },
    { source: 'a', target: 'e', relation_type: 'TREATS' },
  ]
  : withSources
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

const HOSTILE = '<img src=x onerror=alert(1)>';
const REGIONS_PAYLOAD = {
  default: 'cluster',
  modes: {
    cluster: {
      available: true,
      reason: null,
      groups: [
        { id: 'c1', label: 'Glycemic control', full_label: 'Glycemic control: a and e', size: 2 },
        { id: 'c2', label: HOSTILE, full_label: HOSTILE + ' full', size: 2 },
        { id: 'other', label: 'Unclustered', full_label: 'Unclustered', size: 2 },
      ],
      assignment: { a: 'c1', e: 'c1', b: 'c2', c: 'c2', f: 'other', g: 'other', d1: 'c1' },
    },
    family: { available: false, reason: 'No entity families defined for this domain', groups: [], assignment: {} },
  },
};

const GROUPS_PAYLOAD = {
  default: 'cluster',
  modes: {
    cluster: {
      available: true,
      reason: null,
      groups: [
        { id: 'c1', label: 'Glycemic control', full_label: 'Glycemic control: a and e', size: 2 },
        { id: 'c2', label: 'Diabetes', full_label: 'Diabetes', size: 1 },
        { id: 'other', label: 'Unclustered', full_label: 'Unclustered', size: 1 },
      ],
      assignment: { a: 'c1', e: 'c1', b: 'c2', c: 'other', d1: 'c1' },
    },
    family: { available: false, reason: 'No entity families defined for this domain', groups: [], assignment: {} },
  },
};

const controlPayload = (clusterAvailable) => ({
  default: clusterAvailable ? 'cluster' : 'family',
  modes: {
    cluster: clusterAvailable
      ? {
        available: true,
        reason: null,
        groups: [
          { id: 'c1', label: 'Glycemic control', full_label: 'Glycemic control: a, e, f, g', size: 4 },
          { id: 'c2', label: 'Diabetes', full_label: 'Diabetes', size: 2 },
        ],
        assignment: { a: 'c1', e: 'c1', f: 'c1', g: 'c1', b: 'c2', c: 'c2', d1: 'c1' },
      }
      : { available: false, reason: 'No topic clusters in this project', groups: [], assignment: {} },
    family: {
      available: true,
      reason: null,
      groups: [
        { id: 'fam1', label: 'Interventions', full_label: 'Interventions', size: 2 },
        { id: 'fam2', label: 'Conditions', full_label: 'Conditions', size: 2 },
        { id: 'fam3', label: 'Other', full_label: 'Other', size: 2 },
      ],
      assignment: { a: 'fam1', b: 'fam1', e: 'fam2', f: 'fam2', c: 'fam3', g: 'fam3', d1: 'fam1' },
    },
  },
});

function respond(status, body) {
  return { ok: status < 400, status, statusText: String(status), json: async () => body };
}
globalThis.fetch = async (url) => {
  if (url === '/api/graph/entity-types') {
    return (mode === 'fail' || mode === 'edges-fail') ? respond(500, {}) : respond(200, DISPLAY);
  }
  if (url === '/api/graph') return respond(200, { nodes: NODES, edges: EDGES });
  if (url === '/api/graph/groups' && isControl) return respond(200, controlPayload(mode !== 'control-nocomm'));
  if (url === '/api/graph/groups' && isRegions) return respond(200, REGIONS_PAYLOAD);
  if (url === '/api/graph/groups' && isGroups) return respond(200, GROUPS_PAYLOAD);
  return respond(404, {});
};
console.warn = () => {};
console.error = () => {};

if (mode === 'control-fail') {
  window._relayoutTimeoutMs = 60;
  window._relayoutFailMessageMs = 400;
}

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

if (mode === 'groups') {
  const nodeSet = () => [...datasets].reverse().find((d) => [...d.items.values()].some((i) => 'label' in i && !('from' in i)));
  const edgeSet = () => [...datasets].reverse().find((d) => [...d.items.values()].some((i) => 'from' in i));
  const anchorNodes = () => [...nodeSet().items.values()].filter((n) => n._anchor);
  const anchorEdges = () => [...edgeSet().items.values()].filter((e) => e._anchor);
  const dataNodes = () => [...nodeSet().items.values()].filter((n) => !n._anchor);
  const settleFns = [...(handlers.get('stabilizationIterationsDone') || [])];
  calls.length = 0;
  for (const fn of settleFns) fn();
  const fitCall = calls.find((c) => c.kind === 'fit');
  const fitNodes = fitCall && fitCall.opts && Array.isArray(fitCall.opts.nodes) ? fitCall.opts.nodes : null;
  const stab = networkOptions && networkOptions.physics && networkOptions.physics.stabilization;
  const noAnchorsOrHidden = (ids) => Array.isArray(ids) && ids.length > 0 && ids.every((id) => {
    const rec = nodeSet().items.get(id);
    return rec && !rec._anchor && rec.hidden !== true && !String(id).startsWith('__anchor');
  });
  const out = {
    anchorCount: anchorNodes().length,
    groupCount: 3,
    anchorsHiddenFixed: anchorNodes().length > 0 && anchorNodes().every((n) => n.hidden === true
      && n.fixed && n.fixed.x === true && n.fixed.y === true && n.physics === true),
    anchorEdgeCount: anchorEdges().length,
    anchorEdgesHidden: anchorEdges().every((e) => e.hidden === true),
    sourcePhysicsOff: nodeSet().items.get('d1').physics === false,
    sourceHidden: nodeSet().items.get('d1').hidden === true,
    iterations: stab && stab.iterations,
    stabilizationFit: stab && stab.fit,
    fitNodesHaveNoAnchorOrHidden: noAnchorsOrHidden(fitNodes),
    debugMode: window._graphDebug && window._graphDebug.mode,
    debugGroupCount: window._graphDebug && window._graphDebug.groupCount,
    debugAnchorCount: window._graphDebug && window._graphDebug.anchorCount(),
    debugDataNodes: window._graphDebug && window._graphDebug.dataNodes().length,
  };
  // A search-driven filterGraph() must never unhide an anchor edge.
  const search = document.getElementById('graph-search');
  search.value = 'aspirin';
  search.dispatch('input');
  search.value = '';
  search.dispatch('input');
  out.anchorEdgesHiddenAfterFilter = anchorEdges().length > 0 && anchorEdges().every((e) => e.hidden === true);
  out.anchorNodesHiddenAfterFilter = anchorNodes().every((n) => n.hidden === true);
  const labelDebug = window._labelDebug || {};
  const labelledData = dataNodes().filter((n) => n.font && n.font.size > 0).length;
  out.labelledExcludesAnchors = labelDebug.labelled === labelledData
    && anchorNodes().every((n) => !('font' in n) && n.size === 1 && n.opacity === undefined);
  process.stdout.write(JSON.stringify(out) + '\n');
  process.exit(0);
}

const tick = (ms = 80) => new Promise((r) => setTimeout(r, ms));
const stabilizeCalls = () => networkCalls.filter((c) => c.kind === 'stabilize');
const controlSnapshot = () => ({
  checked: Object.fromEntries(GROUP_MODES.map((m) => [m, groupButtons[m].getAttribute('aria-checked')])),
  disabled: Object.fromEntries(GROUP_MODES.map((m) => [m, groupButtons[m].getAttribute('aria-disabled')])),
  titles: Object.fromEntries(GROUP_MODES.map((m) => [m, groupButtons[m].getAttribute('title')])),
  tabindex: Object.fromEntries(GROUP_MODES.map((m) => [m, groupButtons[m].getAttribute('tabindex')])),
  hint: document.getElementById('graph-group-hint').textContent,
});

if (isControl) {
  const passed = [];
  const failed = [];
  const check = (name, cond, detail = '') => {
    if (cond) passed.push(name); else failed.push({ name, detail: JSON.stringify(detail) });
  };
  const nodeSet = () => [...datasets].reverse().find((d) => [...d.items.values()].some((i) => 'label' in i && !('from' in i)));
  const edgeSet = () => [...datasets].reverse().find((d) => [...d.items.values()].some((i) => 'from' in i));
  const anchorIds = () => [...nodeSet().items.values()].filter((n) => n._anchor).map((n) => n.id).sort();
  const dataEdges = () => [...edgeSet().items.values()].filter((e) => !e._anchor);
  const container = document.getElementById('graph-container');
  const radiogroup = document.getElementById('graph-group');
  const hint = () => document.getElementById('graph-group-hint').textContent;
  const status = () => document.getElementById('graph-group-status').textContent;
  const DATA_IDS = ['a', 'b', 'c', 'e', 'f', 'g', 'd1'];
  const worldCopy = () => Object.fromEntries(DATA_IDS.map((id) => [id, { ...world.get(id) }]));
  const near = (a, b) => Math.abs(a.x - b.x) <= 1 && Math.abs(a.y - b.y) <= 1;
  // Fire the recorded completion handlers like vis would, after the layout has moved.
  const emitDone = () => {
    for (const id of DATA_IDS) {
      const w = world.get(id);
      world.set(id, { x: w.x + 7, y: w.y + 13 });
    }
    const fns = [...(handlers.get('stabilizationIterationsDone') || [])];
    for (const fn of fns) {
      if (onceFns.has(fn)) handlers.set('stabilizationIterationsDone', handlers.get('stabilizationIterationsDone').filter((h) => h !== fn));
      fn();
    }
  };
  const go = async (fn) => { fn(); await tick(); emitDone(); await tick(); };
  const lastFit = () => [...calls].reverse().find((c) => c.kind === 'fit' && c.opts && Array.isArray(c.opts.nodes));

  emitDone(); // the initial build settles
  await tick();

  if (mode === 'control') {
    let snap = controlSnapshot();
    check('cluster selected', snap.checked.cluster === 'true' && snap.checked.family === 'false' && snap.checked.none === 'false', snap.checked);
    check('roving tabindex', snap.tabindex.cluster === '0' && snap.tabindex.family === '-1' && snap.tabindex.none === '-1', snap.tabindex);
    check('enabled titles', snap.titles.cluster === 'Group nodes by topic cluster (communities found in the documents)'
      && snap.titles.family === 'Group nodes by entity family' && snap.titles.none === 'No grouping: free layout', snap.titles);
    check('nothing disabled', GROUP_MODES.every((m) => snap.disabled[m] === null), snap.disabled);
    check('hint empty when all enabled', snap.hint === '', snap.hint);
    check('cluster anchors', JSON.stringify(anchorIds()) === JSON.stringify(['__anchor:c1', '__anchor:c2']), anchorIds());

    // Entity family
    groupButtons.family.dispatch('click');
    check('busy on the radiogroup', radiogroup.getAttribute('aria-busy') === 'true');
    check('busy on the graph container', container.getAttribute('aria-busy') === 'true');
    check('arranging text shown', hint() === 'Arranging groups…', hint());
    check('target is selected while arranging', groupButtons.family.getAttribute('aria-checked') === 'true');
    groupButtons.none.dispatch('click');
    await tick();
    check('click while busy is ignored', groupButtons.none.getAttribute('aria-checked') === 'false'
      && stabilizeCalls().length === 1, { checked: groupButtons.none.getAttribute('aria-checked'), n: stabilizeCalls().length });
    check('family stabilizes with the group budget', stabilizeCalls().length === 1 && stabilizeCalls()[0].args[0] === 200, stabilizeCalls());
    check('cluster anchors replaced by family anchors', JSON.stringify(anchorIds()) === JSON.stringify(['__anchor:fam1', '__anchor:fam2', '__anchor:fam3']), anchorIds());
    check('mode is family', window._graphDebug.mode === 'family');
    emitDone();
    await tick();
    check('settled physics off', networkCalls.some((c) => c.kind === 'setOptions' && c.args[0] && c.args[0].physics === false));
    const fit = lastFit();
    check('settle fits visible data nodes only', fit && JSON.stringify([...fit.opts.nodes].sort()) === JSON.stringify(['a', 'b', 'c', 'e', 'f', 'g']), fit && fit.opts.nodes);
    check('busy released', radiogroup.getAttribute('aria-busy') === null && container.getAttribute('aria-busy') === null);
    check('arranging text cleared', hint() === '', hint());
    check('family announced', status() === 'Grouped by entity family: 3 groups.', status());
    check('family checked after settle', controlSnapshot().checked.family === 'true');

    // None: first time runs a free layout and caches it
    groupButtons.none.dispatch('click');
    await tick();
    check('none removes every anchor', anchorIds().length === 0, anchorIds());
    check('none resets edge lengths', dataEdges().every((e) => e.length === 160), dataEdges().map((e) => e.length));
    check('first none stabilizes freely', stabilizeCalls().length === 2 && stabilizeCalls()[1].args[0] === 400, stabilizeCalls());
    check('debug group count zero', window._graphDebug.groupCount === 0);
    emitDone();
    await tick();
    check('grouping off announced', status() === 'Grouping off.', status());
    const freeSnap = worldCopy();

    // Back through both grouped modes, then None restores the cache
    await go(() => groupButtons.cluster.dispatch('click'));
    check('cluster announced', status() === 'Grouped by topic cluster: 2 groups.', status());
    check('cluster anchors back', anchorIds().length === 2);
    await go(() => groupButtons.family.dispatch('click'));
    const stabilizeBefore = stabilizeCalls().length;
    check('grouped layout moved nodes', !near(world.get('a'), freeSnap.a));
    groupButtons.none.dispatch('click');
    check('restoring none is instant (not busy)', radiogroup.getAttribute('aria-busy') === null && hint() === '', hint());
    await tick();
    check('cached none runs no physics', stabilizeCalls().length === stabilizeBefore, stabilizeCalls().length);
    check('cached none removes anchors', anchorIds().length === 0);
    check('cached positions restored within 1 unit', DATA_IDS.every((id) => near(world.get(id), freeSnap[id])), { world: worldCopy(), freeSnap });
    check('cached none edge lengths reset', dataEdges().every((e) => e.length === 160));
    check('cached none announced', status() === 'Grouping off.' && controlSnapshot().checked.none === 'true', status());

    // Keyboard
    const key = async (target, k) => { groupButtons[target].dispatch('keydown', { key: k }); await tick(); emitDone(); await tick(); };
    await key('none', 'ArrowLeft');
    check('ArrowLeft moves to the previous option', controlSnapshot().checked.family === 'true' && globalThis.__focused === groupButtons.family, controlSnapshot().checked);
    await key('family', 'ArrowRight');
    check('ArrowRight moves to the next option', controlSnapshot().checked.none === 'true');
    await key('none', 'ArrowRight');
    check('ArrowRight wraps', controlSnapshot().checked.cluster === 'true');
    await key('cluster', 'ArrowLeft');
    check('ArrowLeft wraps', controlSnapshot().checked.none === 'true');
    await key('none', 'Home');
    check('Home selects the first', controlSnapshot().checked.cluster === 'true');
    await key('cluster', 'End');
    check('End selects the last', controlSnapshot().checked.none === 'true');
    await key('none', 'ArrowUp');
    check('ArrowUp moves back', controlSnapshot().checked.family === 'true');
    await key('family', 'ArrowDown');
    check('ArrowDown moves on', controlSnapshot().checked.none === 'true');
    await key('cluster', ' ');
    check('Space activates the focused option', controlSnapshot().checked.cluster === 'true');
    await key('family', 'Enter');
    check('Enter activates the focused option', controlSnapshot().checked.family === 'true');
    const nBefore = stabilizeCalls().length;
    groupButtons.family.dispatch('click');
    await tick();
    check('re-selecting the current mode does nothing', stabilizeCalls().length === nBefore);
  }

  if (mode === 'control-nocomm') {
    const snap = controlSnapshot();
    check('cluster disabled', snap.disabled.cluster === 'true', snap.disabled);
    check('cluster title is the reason', snap.titles.cluster === 'No topic clusters in this project', snap.titles);
    check('hint explains', snap.hint === 'Topic cluster: No topic clusters in this project.', snap.hint);
    check('family selected', snap.checked.family === 'true' && snap.checked.cluster === 'false', snap.checked);
    check('cluster tabindex -1', snap.tabindex.cluster === '-1' && snap.tabindex.family === '0', snap.tabindex);
    check('fallback announced', status() === 'Topic clusters unavailable: No topic clusters in this project. Grouped by entity family.', status());
    check('family anchors on load', anchorIds().length === 3);
    groupButtons.cluster.dispatch('click');
    await tick();
    check('clicking a disabled option does nothing', stabilizeCalls().length === 0 && controlSnapshot().checked.family === 'true');
    groupButtons.family.dispatch('keydown', { key: 'ArrowLeft' });
    await tick();
    check('ArrowLeft skips the disabled option', controlSnapshot().checked.cluster === 'false' && controlSnapshot().checked.none === 'true', controlSnapshot().checked);
    emitDone();
    await tick();
    check('none settles', anchorIds().length === 0 && controlSnapshot().checked.none === 'true');
    groupButtons.none.dispatch('keydown', { key: 'ArrowRight' });
    await tick();
    check('ArrowRight skips it too', controlSnapshot().checked.family === 'true', controlSnapshot().checked);
  }

  if (mode === 'control-fail') {
    const before = worldCopy();
    groupButtons.family.dispatch('click');
    await tick(40);
    const late = [...(handlers.get('stabilizationIterationsDone') || [])];
    check('stabilization started', stabilizeCalls().length === 1);
    await tick(150);
    const snap = controlSnapshot();
    const failText = "Couldn't arrange groups. Showing the previous layout.";
    check('previous mode reselected', snap.checked.cluster === 'true' && snap.checked.family === 'false', snap.checked);
    check('previous anchors restored', JSON.stringify(anchorIds()) === JSON.stringify(['__anchor:c1', '__anchor:c2']), anchorIds());
    check('failure shown in the hint', snap.hint === failText, snap.hint);
    check('failure announced', status() === failText, status());
    check('busy released after failure', radiogroup.getAttribute('aria-busy') === null && container.getAttribute('aria-busy') === null);
    check('mode restored', window._graphDebug.mode === 'cluster');
    check('positions restored', DATA_IDS.every((id) => near(world.get(id), before[id])), { world: worldCopy(), before });
    const fitsBefore = calls.filter((c) => c.kind === 'fit').length;
    const physicsOffBefore = networkCalls.filter((c) => c.kind === 'setOptions' && c.args[0] && c.args[0].physics === false).length;
    for (const fn of late) fn();
    await tick();
    check('stale completion is discarded', calls.filter((c) => c.kind === 'fit').length === fitsBefore
      && networkCalls.filter((c) => c.kind === 'setOptions' && c.args[0] && c.args[0].physics === false).length === physicsOffBefore
      && window._graphDebug.mode === 'cluster' && status() === failText, status());
    await tick(500);
    check('failure message clears', hint() === '', hint());

    globalThis.__stabilizeThrows = true;
    groupButtons.family.dispatch('click');
    await tick(120);
    check('a throwing relayout also recovers', controlSnapshot().checked.cluster === 'true'
      && controlSnapshot().hint === failText && anchorIds().length === 2 && window._graphDebug.mode === 'cluster', controlSnapshot());
    globalThis.__stabilizeThrows = false;
    await tick(500);
    await go(() => groupButtons.family.dispatch('click'));
    check('the control works again after a failure', window._graphDebug.mode === 'family' && controlSnapshot().checked.family === 'true', controlSnapshot().checked);
  }

  if (mode === 'control-sources') {
    const srcBtn = document.getElementById('graph-show-sources-btn');
    const regionsBefore = JSON.stringify(window._graphDebug.regionGeometry());
    const movesFor = (id) => networkCalls.filter((c) => c.kind === 'moveNode' && c.args[0] === id);
    srcBtn.dispatch('click');
    const m1 = movesFor('d1');
    const last1 = m1[m1.length - 1];
    check('source moved on reveal', Boolean(last1));
    // a (0,0) and e (40,0) are in the source's group; b is not. Jitter for index 0 is (-36, -36).
    check('source sits at its group centroid', last1 && Math.abs(last1.args[1] - (20 - 36)) < 1e-6 && Math.abs(last1.args[2] - (0 - 36)) < 1e-6, last1 && last1.args);
    check('source does not change region geometry', JSON.stringify(window._graphDebug.regionGeometry()) === regionsBefore);
    groupButtons.family.dispatch('click');
    await tick();
    const d1 = nodeSet().items.get('d1');
    check('source physics off during relayout', d1.physics === false, d1.physics);
    const sourceEdges = dataEdges().filter((e) => e._data && e._data.relation_type === 'MENTIONED_IN');
    check('source edges physics off during relayout', sourceEdges.length === 3 && sourceEdges.every((e) => e.physics === false), sourceEdges.map((e) => e.physics));
    emitDone();
    await tick();
    const m2 = movesFor('d1');
    const last2 = m2[m2.length - 1];
    // In the family mode d1's plurality group holds a and b, not e.
    const wa = world.get('a');
    const wb = world.get('b');
    check('source re-placed inside its family group', last2 && m2.length > m1.length
      && Math.abs(last2.args[1] - ((wa.x + wb.x) / 2 - 36)) < 1e-6 && Math.abs(last2.args[2] - ((wa.y + wb.y) / 2 - 36)) < 1e-6, last2 && last2.args);
    check('source physics restored after settle', nodeSet().items.get('d1').physics === true);
    check('source stays visible', nodeSet().items.get('d1').hidden !== true);
    check('anchors never include sources', !anchorIds().some((id) => id.includes('d1')));
  }

  process.stdout.write(JSON.stringify({ passed, failed }) + '\n');
  process.exit(failed.length ? 1 : 0);
}

if (isRegions || mode === 'nogroups') {
  const passed = [];
  const failed = [];
  const check = (name, cond, detail = '') => {
    if (cond) passed.push(name); else failed.push({ name, detail: JSON.stringify(detail) });
  };
  // Recording canvas context.
  const rec = { arcs: 0, texts: [], fills: new Set(), strokes: new Set(), fonts: [], widths: [], dashes: [] };
  const ctx = {
    set fillStyle(v) { rec.fills.add(v); },
    set strokeStyle(v) { rec.strokes.add(v); },
    set font(v) { rec.fonts.push(v); },
    set lineWidth(v) { rec.widths.push(v); },
    set textBaseline(v) {},
    set textAlign(v) {},
    setLineDash(d) { rec.dashes.push(d); },
    arc() { rec.arcs++; },
    fillText(t) { rec.texts.push(t); },
    measureText: (t) => ({ width: String(t).length * 7 }),
    save() {}, restore() {}, beginPath() {}, closePath() {}, fill() {}, stroke() {},
    moveTo() {}, lineTo() {}, arcTo() {}, quadraticCurveTo() {}, rect() {}, fillRect() {}, strokeRect() {},
  };
  const reset = () => { rec.arcs = 0; rec.texts = []; rec.fills.clear(); rec.strokes.clear(); rec.fonts = []; rec.widths = []; rec.dashes = []; };
  const draw = () => {
    reset();
    for (const fn of handlers.get('beforeDrawing') || []) fn(ctx);
    for (const fn of handlers.get('afterDrawing') || []) fn(ctx);
  };
  const writesBefore = calls.filter((c) => c.kind === 'add' || c.kind === 'update' || c.kind === 'remove').length;
  const btn = document.getElementById('graph-groups-btn');
  const panel = document.getElementById('graph-groups');
  if (mode === 'nogroups') {
    draw();
    check('no region handler draws in ungrouped mode', rec.arcs === 0 && rec.texts.length === 0, rec);
    check('Groups button disabled when ungrouped', btn.hasAttribute('disabled'));
    check('Groups button title', btn.getAttribute('title') === 'Choose a grouping to list its groups.', btn.getAttribute('title'));
    check('Groups panel hidden when ungrouped', panel.hasAttribute('hidden'));
    process.stdout.write(JSON.stringify({ passed, failed }) + '\n');
    process.exit(failed.length ? 1 : 0);
  }
  check('beforeDrawing registered', (handlers.get('beforeDrawing') || []).length >= 1);
  check('afterDrawing registered', (handlers.get('afterDrawing') || []).length >= 1);
  draw();
  check('one arc per region', rec.arcs === 3, rec.arcs);
  check('pills use exact payload labels', JSON.stringify([...rec.texts].sort()) === JSON.stringify(['Glycemic control', HOSTILE, 'Unclustered'].sort()), rec.texts);
  const palette = /^rgba\(26, ?26, ?46, ?[0-9.]+\)$|^rgba\(255, ?255, ?255, ?[0-9.]+\)$|^#1a1a1a$/;
  check('only neutral colors are used', [...rec.fills, ...rec.strokes].every((c) => palette.test(c)), [...rec.fills, ...rec.strokes]);
  check('pill font is 600 at 13 screen px', rec.fonts.some((f) => /\b600\b/.test(f) && /\b13px\b/.test(f)), rec.fonts);
  check('unclustered ring is dashed', rec.dashes.some((d) => Array.isArray(d) && d.length === 2 && d[0] === 6 && d[1] === 4), rec.dashes);
  check('rest stroke is 1 screen px', rec.widths.includes(1), rec.widths);
  check('draw performs no DataSet writes', calls.filter((c) => c.kind === 'add' || c.kind === 'update' || c.kind === 'remove').length === writesBefore);
  check('debug exposes regions', window._graphDebug.regionGeometry().length === 3);
  check('debug exposes placed labels', window._graphDebug.placedLabels().length === 3);

  const countSpan = btn.children.find((c) => c.className === 'count');
  check('Groups button not disabled', !btn.hasAttribute('disabled'));
  check('Groups count equals group count', countSpan && countSpan.textContent === '3', countSpan && countSpan.textContent);
  check('Groups button starts collapsed', btn.getAttribute('aria-expanded') === 'false' && panel.hasAttribute('hidden'));
  btn.dispatch('click');
  check('Groups button opens the panel', btn.getAttribute('aria-expanded') === 'true' && !panel.hasAttribute('hidden'));

  const rowsOf = () => {
    const ul = panel.children[0];
    return ul ? ul.children.map((li) => li.children[0]).filter((b) => b && b.className === 'graph-group-row') : [];
  };
  let rows = rowsOf();
  check('three rows', rows.length === 3, rows.length);
  const rowLabel = (r) => r.children.find((c) => c.className === 'graph-group-row__label');
  const rowCount = (r) => r.children.find((c) => c.className === 'graph-group-row__count');
  const byLabel = (t) => rows.find((r) => rowLabel(r) && rowLabel(r).textContent === t);
  const hostileRow = byLabel(HOSTILE);
  check('hostile label is literal text in the list', Boolean(hostileRow));
  check('row title is the full label', hostileRow && hostileRow.getAttribute('title') === HOSTILE + ' full', hostileRow && hostileRow.getAttribute('title'));
  check('row shows visible count', hostileRow && rowCount(hostileRow).textContent === '2');
  check('group id is not a class or id', rows.every((r) => !/c1|c2/.test(r.className) && !/c1|c2/.test(r.id || '')));

  // Hover emphasis.
  const glyc = byLabel('Glycemic control');
  glyc.dispatch('mouseenter');
  draw();
  check('hover emphasizes the region', rec.strokes.has('rgba(26, 26, 46, 0.6)') || rec.strokes.has('rgba(26,26,46,0.6)'), [...rec.strokes]);
  check('emphasis uses a 2px stroke', rec.widths.includes(2), rec.widths);
  glyc.dispatch('mouseleave');
  draw();
  check('leaving a row clears emphasis', !(rec.strokes.has('rgba(26, 26, 46, 0.6)') || rec.strokes.has('rgba(26,26,46,0.6)')));

  // Click zooms to the group's visible members.
  const fitsFor = () => calls.filter((c) => c.kind === 'fit' && c.opts && Array.isArray(c.opts.nodes));
  const before = fitsFor().length;
  glyc.dispatch('click');
  const fits = fitsFor();
  check('row click fits the group members', fits.length === before + 1
    && JSON.stringify([...fits[fits.length - 1].opts.nodes].sort()) === JSON.stringify(['a', 'e']), fits.map((f) => f.opts.nodes));
  check('active row is aria-current', glyc.getAttribute('aria-current') === 'true');
  const status = document.getElementById('graph-group-status');
  check('zoom is announced', status.textContent === 'Zoomed to Glycemic control: a and e: 2 nodes.', status.textContent);
  glyc.dispatch('click');
  check('second click clears the active row', glyc.getAttribute('aria-current') !== 'true');
  check('second click does not refit', fitsFor().length === before + 1);
  glyc.dispatch('click');
  check('active again', glyc.getAttribute('aria-current') === 'true');
  document.getElementById('graph-fit-btn').dispatch('click');
  check('Fit View clears the active row', glyc.getAttribute('aria-current') !== 'true');

  // Filtering updates counts and titles; empty rows are disabled.
  const search = document.getElementById('graph-search');
  search.value = 'aspirin';
  search.dispatch('input');
  rows = rowsOf();
  const glyc2 = byLabel('Glycemic control');
  const hostile2 = byLabel(HOSTILE);
  check('filtered title shows n of m', glyc2.getAttribute('title') === 'Glycemic control: a and e (1 of 2 shown)', glyc2.getAttribute('title'));
  check('filtered count updates', rowCount(glyc2).textContent === '1');
  check('empty group row is aria-disabled', hostile2.getAttribute('aria-disabled') === 'true');
  const fitsN = fitsFor().length;
  hostile2.dispatch('click');
  check('disabled row ignores clicks', fitsFor().length === fitsN);
  draw();
  check('a group with one visible member has no region', rec.arcs === 0 && rec.texts.length === 0, rec);
  search.value = '';
  search.dispatch('input');
  draw();
  check('regions return after the filter clears', rec.arcs === 3);

  process.stdout.write(JSON.stringify({ passed, failed }) + '\n');
  process.exit(failed.length ? 1 : 0);
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
    // IN-04: the key counts only drawn edges (unscored edges hide above 0.5).
    const conf = document.getElementById('confidence-slider');
    conf.value = '0.9';
    conf.dispatch('input');
    check('edge key drops hidden categories', panel.children.length === 1, panel.children.length);
    check('edge key stays open after refilter', !panel.hasAttribute('hidden'));
    conf.value = '0';
    conf.dispatch('input');
    check('edge key rows restored', panel.children.length === 4, panel.children.length);
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

const okStab = networkOptions && networkOptions.physics && networkOptions.physics.stabilization;
const anyAnchor = [...datasets].some((d) => [...d.items.values()].some((i) => i._anchor));
process.stdout.write(JSON.stringify({
  hidden: nodeUpdates.filter((u) => u.hidden).map((u) => u.id),
  total: nodeUpdates.length,
  anchorCount: anyAnchor ? 1 : 0,
  iterations: okStab && okStab.iterations,
  groupControl: await (async () => {
    const before = controlSnapshot();
    groupButtons.cluster.dispatch('click');
    groupButtons.family.dispatch('click');
    groupButtons.none.dispatch('keydown', { key: 'ArrowLeft' });
    await tick();
    return { ...before, stabilizeCalls: stabilizeCalls().length, after: controlSnapshot().checked };
  })(),
}) + '\n');
process.exit(0);
