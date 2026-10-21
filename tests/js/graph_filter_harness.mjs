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
// argv[2] = "control-early" clicks the Group by control before the initial
// layout settles (CR-01): the control is disabled and a stale initial-settle
// handler cannot stop a later relayout.
// argv[2] = "focus" / "focus-filters" drive focus mode: double-click entry, the
// breadcrumb bar, hop toggle, Esc chain, graph-focus-* events, composition with
// Show sources, filters and grouping.
import { pathToFileURL, fileURLToPath } from 'node:url';
import path from 'node:path';

const mode = process.argv[2] || 'ok';
const isRegions = mode === 'regions';
const isControl = mode.startsWith('control');
const isFocus = mode.startsWith('focus');

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
const docListeners = {};
const winListeners = {};
const windowEvents = [];
globalThis.document = {
  getElementById(id) {
    if (!elements.has(id)) elements.set(id, makeEl(id));
    return elements.get(id);
  },
  createElement: (tag) => { const el = makeEl(); el.tagName = String(tag).toLowerCase(); return el; },
  createElementNS: () => makeEl(),
  createDocumentFragment: () => makeEl(),
  createTextNode: (t) => ({ textContent: t }),
  addEventListener(type, fn) { (docListeners[type] = docListeners[type] || []).push(fn); },
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
        if (prop === 'setSize' || prop === 'redraw') {
          return (...args) => { calls.push({ kind: String(prop), order: order++, args }); };
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
          if (mode !== 'groups' && !isFocus) return () => ({});
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
  addEventListener(type, fn) { (winListeners[type] = winListeners[type] || []).push(fn); },
  removeEventListener() {},
  dispatchEvent(ev) {
    windowEvents.push({ type: ev.type, detail: ev.detail === undefined ? undefined : JSON.parse(JSON.stringify(ev.detail)) });
    for (const fn of [...(winListeners[ev.type] || [])]) fn(ev);
    return true;
  },
  innerWidth: 1200,
  innerHeight: 800,
};

const isGroups = mode === 'groups' || isRegions || isControl || isFocus;
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
const FOCUS_LONG = 'Gamma node with a very long descriptive name that keeps going and going';
const FOCUS_NODES = [
  { id: 'hub', name: 'Hub core', entity_type: 'COMPOUND' },
  { id: 'n1', name: 'Alpha core', entity_type: 'COMPOUND' },
  { id: 'n2', name: 'Beta core', entity_type: 'DISEASE' },
  { id: 'n3', name: FOCUS_LONG, entity_type: 'COMPOUND' },
  { id: 'x1', name: 'Xi core', entity_type: 'COMPOUND' },
  { id: 'x2', name: 'Omega core', entity_type: 'COMPOUND' },
  { id: 'h1', name: '<img src=x onerror=alert(1)>', entity_type: 'DISEASE' },
  { id: 'lone', name: 'Lonely core', entity_type: 'COMPOUND' },
  { id: 's1', name: 'Doc one', entity_type: 'DOCUMENT' },
];
const FOCUS_EDGES = [
  { source: 'hub', target: 'n1', relation_type: 'TREATS' },
  { source: 'hub', target: 'n2', relation_type: 'TREATS' },
  { source: 'hub', target: 'n3', relation_type: 'TREATS' },
  { source: 'n1', target: 'x1', relation_type: 'TREATS' },
  { source: 'x1', target: 'x2', relation_type: 'TREATS' },
  { source: 'n2', target: 'h1', relation_type: 'TREATS' },
  { source: 'hub', target: 's1', relation_type: 'MENTIONED_IN' },
];
const NODES = isFocus ? FOCUS_NODES : isEdges ? EDGE_NODES : mode === 'fit' ? FIT_NODES : [
  { id: 'a', name: 'Aspirin', entity_type: 'COMPOUND' },
  { id: 'b', name: 'Diabetes', entity_type: 'DISEASE' },
  { id: 'c', name: 'Mystery', entity_type: null },
  ...(isGroups && !isFocus ? [{ id: 'e', name: 'Empagliflozin', entity_type: 'COMPOUND' }] : []),
  ...(isRegions || isControl ? [{ id: 'f', name: 'Fenofibrate', entity_type: 'COMPOUND' }, { id: 'g', name: 'Gemfibrozil', entity_type: 'COMPOUND' }] : []),
  ...(withSources ? [{ id: 'd1', name: 'Doc one', entity_type: 'DOCUMENT' }] : []),
];
const EDGES = isFocus ? FOCUS_EDGES : isEdges ? EDGE_EDGES : mode === 'fit' ? FIT_EDGES : isGroups
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

const FOCUS_PAYLOAD = {
  default: 'cluster',
  modes: {
    cluster: {
      available: true,
      reason: null,
      groups: [
        { id: 'c1', label: 'Core', full_label: 'Core', size: 4 },
        { id: 'c2', label: 'Outer', full_label: 'Outer', size: 3 },
      ],
      assignment: { hub: 'c1', n1: 'c1', n2: 'c1', n3: 'c1', x1: 'c2', x2: 'c2', h1: 'c2', lone: 'c2', s1: 'c1' },
    },
    family: {
      available: true,
      reason: null,
      groups: [
        { id: 'fam1', label: 'Interventions', full_label: 'Interventions', size: 5 },
        { id: 'fam2', label: 'Conditions', full_label: 'Conditions', size: 2 },
      ],
      assignment: { hub: 'fam1', n1: 'fam1', n3: 'fam1', x1: 'fam1', x2: 'fam1', n2: 'fam2', h1: 'fam2', lone: 'fam1', s1: 'fam1' },
    },
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
  if (url === '/api/graph/groups' && isFocus) return respond(200, FOCUS_PAYLOAD);
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
// The real vis always reports the initial layout done; modes that do not
// drive it themselves get it here (the Group by control waits for it).
if (['ok', 'fail', 'sources', 'nosources'].includes(mode)) {
  for (const fn of [...(handlers.get('stabilizationIterationsDone') || [])]) fn();
}

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

  if (mode !== 'control-early') {
    emitDone(); // the initial build settles
    await tick();
  }

  if (mode === 'control-early') {
    const snap0 = controlSnapshot();
    check('before settle: every option aria-disabled', GROUP_MODES.every((m) => snap0.disabled[m] === 'true'), snap0.disabled);
    check('before settle: the build mode stays checked', snap0.checked.cluster === 'true', snap0.checked);
    check('before settle: titles give the reason', GROUP_MODES.every((m) => snap0.titles[m] === 'Available once the layout has settled'), snap0.titles);
    check('before settle: arranging text', snap0.hint === 'Arranging groups…', snap0.hint);
    check('before settle: graph busy', container.getAttribute('aria-busy') === 'true' && window._graphDebug.settled === false);
    groupButtons.family.dispatch('click');
    groupButtons.none.dispatch('click');
    groupButtons.cluster.dispatch('keydown', { key: 'ArrowRight' });
    await tick();
    check('clicks before settle are ignored', stabilizeCalls().length === 0 && window._graphDebug.mode === 'cluster'
      && controlSnapshot().checked.family === 'false', { n: stabilizeCalls().length, mode: window._graphDebug.mode });
    const staleDone = [...(handlers.get('stabilizationIterationsDone') || [])];
    const staleStab = [...(handlers.get('stabilized') || [])];
    // vis's safety-net event settles the initial layout.
    for (const fn of staleStab) fn();
    await tick();
    const snap1 = controlSnapshot();
    check('settle enables the control', GROUP_MODES.every((m) => snap1.disabled[m] === null) && window._graphDebug.settled === true, snap1.disabled);
    check('settle restores the option titles', snap1.titles.family === 'Group nodes by entity family', snap1.titles);
    check('settle clears the arranging text and busy state', snap1.hint === '' && container.getAttribute('aria-busy') === null, snap1.hint);
    check('settle removes both of its handlers', !(handlers.get('stabilizationIterationsDone') || []).some((h) => staleDone.includes(h))
      && !(handlers.get('stabilized') || []).some((h) => staleStab.includes(h)));
    groupButtons.family.dispatch('click');
    await tick();
    check('after settle a click starts a relayout', stabilizeCalls().length === 1 && window._graphDebug.busy === true);
    const offBefore = networkCalls.filter((c) => c.kind === 'setOptions' && c.args[0] && c.args[0].physics === false).length;
    for (const fn of [...staleDone, ...staleStab]) fn();
    await tick();
    check('a stale initial settle cannot stop the relayout', window._graphDebug.busy === true
      && networkCalls.filter((c) => c.kind === 'setOptions' && c.args[0] && c.args[0].physics === false).length === offBefore
      && hint() === 'Arranging groups…', hint());
    emitDone();
    await tick();
    check('the relayout completes normally', window._graphDebug.mode === 'family' && status() === 'Grouped by entity family: 3 groups.', status());
    groupButtons.none.dispatch('click');
    await tick();
    check('None runs a real free layout (nothing cached early)', stabilizeCalls().length === 2 && stabilizeCalls()[1].args[0] === 400, stabilizeCalls());
    emitDone();
    await tick();
  }

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
    window._relayoutTimeoutMs = 5000;
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
    // a and e are in the source's group; b (1000 units away) is not. Jitter for index 0 is (-36, -36).
    const wa0 = world.get('a');
    const we0 = world.get('e');
    check('source sits at its group centroid', last1 && Math.abs(last1.args[1] - ((wa0.x + we0.x) / 2 - 36)) < 1e-6
      && Math.abs(last1.args[2] - ((wa0.y + we0.y) / 2 - 36)) < 1e-6, last1 && last1.args);
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


if (isFocus) {
  const passed = [];
  const failed = [];
  const check = (name, cond, detail = '') => {
    if (cond) passed.push(name); else failed.push({ name, detail: JSON.stringify(detail) });
  };
  const nodeSet = () => [...datasets].reverse().find((d) => [...d.items.values()].some((i) => 'label' in i && !('from' in i)));
  const dataNodes = () => [...nodeSet().items.values()].filter((n) => !n._anchor);
  const anchorNodes = () => [...nodeSet().items.values()].filter((n) => n._anchor);
  const visibleIds = () => dataNodes().filter((n) => n.hidden !== true).map((n) => n.id).sort();
  const sorted = (ids) => [...ids].sort();
  const same = (a, b) => JSON.stringify(sorted(a)) === JSON.stringify(sorted(b));
  const textOf = (el) => (el.children && el.children.length
    ? el.children.map((c) => textOf(c)).join('') : (el.textContent || ''));
  const bar = document.getElementById('graph-focus-bar');
  const crumbsEl = document.getElementById('graph-focus-crumbs');
  const hop1 = document.getElementById('graph-focus-hop-1');
  const hop2 = document.getElementById('graph-focus-hop-2');
  const exitBtn = document.getElementById('graph-focus-exit');
  const barShown = () => !bar.hasAttribute('hidden');
  const crumbItems = () => crumbsEl.children.map((li) => (li.children && li.children[0]) || li);
  const crumbTexts = () => crumbItems().map((c) => textOf(c));
  const status = () => document.getElementById('graph-group-status').textContent;
  const hint = () => document.getElementById('graph-group-hint').textContent;
  const dbl = (id) => { for (const fn of handlers.get('doubleClick') || []) fn({ nodes: [id], edges: [] }); };
  const winEvent = (type, detail) => window.dispatchEvent(new CustomEvent(type, { detail }));
  const lastFit = () => [...calls].reverse().find((c) => c.kind === 'fit' && c.opts && Array.isArray(c.opts.nodes));
  const changedEvents = () => windowEvents.filter((e) => e.type === 'graph-focus-changed');
  const lastChanged = () => changedEvents()[changedEvents().length - 1];
  const stackIds = () => window._graphDebug.focus().stack.map((s) => s.id);
  const esc = (target) => { for (const fn of docListeners.keydown || []) fn({ key: 'Escape', target }); };
  const tick = (ms = 30) => new Promise((r) => setTimeout(r, ms));
  const settle = () => { for (const fn of [...(handlers.get('stabilizationIterationsDone') || [])]) fn(); };
  const search = document.getElementById('graph-search');
  const lenOf = (s) => Array.from(s).length;

  settle();
  await tick();
  winEvent('graph-panel-opened');
  check('starts unfocused with the bar hidden', !barShown() && window._graphDebug.focus().stack.length === 0);
  check('all knowledge nodes visible at rest', same(visibleIds(), ['hub', 'n1', 'n2', 'n3', 'x1', 'x2', 'h1', 'lone']), visibleIds());
  check('resting label is 22 characters', lenOf(nodeSet().items.get('n3').label) === 22, nodeSet().items.get('n3').label);

  if (mode === 'focus') {
    // --- enter 1-hop focus by double-click ---
    calls.length = 0;
    windowEvents.length = 0;
    dbl('hub');
    await tick();
    check('dblclick hub shows only its 1-hop set', same(visibleIds(), ['hub', 'n1', 'n2', 'n3']), visibleIds());
    check('anchors stay hidden and present', anchorNodes().length === 2 && anchorNodes().every((a) => a.hidden === true));
    const fit1 = lastFit();
    check('fit called with exactly the focus ids', fit1 && same(fit1.opts.nodes, ['hub', 'n1', 'n2', 'n3']), fit1 && fit1.opts.nodes);
    check('focus fit is animated 250ms', fit1 && fit1.opts.animation && fit1.opts.animation.duration === 250, fit1 && fit1.opts.animation);
    const sizeCall = calls.find((c) => c.kind === 'setSize');
    check('canvas is resized after the bar appears, before the fit', Boolean(sizeCall) && sizeCall.order < fit1.order, calls.map((c) => c.kind));
    check('focus bar shown', barShown());
    check('crumbs are All nodes and the centre', JSON.stringify(crumbTexts()) === JSON.stringify(['All nodes', 'Hub core']), crumbTexts());
    const items = crumbItems();
    check('last crumb is current', items[1].getAttribute('aria-current') === 'location' && items[0].getAttribute('aria-current') === null);
    check('last crumb is plain text and the others are buttons', items[1].tagName !== 'button' && items[0].tagName === 'button', [items[0].tagName, items[1].tagName]);
    check('1 hop segment text', textOf(hop1) === '1 hop · 4 nodes', textOf(hop1));
    check('2 hops segment text', textOf(hop2) === '2 hops · 6 nodes', textOf(hop2));
    check('1 hop is checked', hop1.getAttribute('aria-checked') === 'true' && hop2.getAttribute('aria-checked') === 'false');
    check('roving tabindex on hop radios', hop1.getAttribute('tabindex') === '0' && hop2.getAttribute('tabindex') === '-1');
    check('status announces the focus', status() === 'Focus: Hub core, 1 hop, 4 nodes shown.', status());
    check('graph-focus-changed carries id, hops and counts', lastChanged() && lastChanged().detail.id === 'hub'
      && lastChanged().detail.hops === 1 && lastChanged().detail.counts[1] === 4 && lastChanged().detail.counts[2] === 6, lastChanged());
    check('the centre is selected with its sidebar', window._graphDebug.focus().stack.length === 1);
    check('focus bar node font is visible for every shown node', ['hub', 'n1', 'n2', 'n3'].every((id) => nodeSet().items.get(id).font.size > 0));
    check('focus label truncates at 40 characters', lenOf(nodeSet().items.get('n3').label) === 40, nodeSet().items.get('n3').label);
    check('focus label of a short name is untouched', nodeSet().items.get('hub').label === 'Hub core');

    // --- 2 hops ---
    calls.length = 0;
    hop2.dispatch('click');
    await tick();
    check('2 hops shows the wider set', same(visibleIds(), ['hub', 'n1', 'n2', 'n3', 'x1', 'h1']), visibleIds());
    check('2 hops refits to the wider set', lastFit() && same(lastFit().opts.nodes, ['hub', 'n1', 'n2', 'n3', 'x1', 'h1']));
    check('2 hops checked', hop2.getAttribute('aria-checked') === 'true' && hop1.getAttribute('aria-checked') === 'false');
    check('2 hops did not push a crumb', crumbTexts().length === 2);
    check('2 hops announced', status() === 'Focus: Hub core, 2 hops, 6 nodes shown.', status());
    check('the event reports hops 2', lastChanged().detail.hops === 2);
    hop1.dispatch('keydown', { key: 'ArrowRight' });
    await tick();
    check('arrow key moves the hop radio', hop2.getAttribute('aria-checked') === 'true');
    hop1.dispatch('click');
    await tick();
    hop2.dispatch('click');
    await tick();

    // --- push, truncate ---
    dbl('n1');
    await tick();
    check('dblclick on a visible node pushes a crumb', JSON.stringify(crumbTexts()) === JSON.stringify(['All nodes', 'Hub core', 'Alpha core']), crumbTexts());
    check('pushed focus shows the new 1-hop set', same(visibleIds(), ['hub', 'n1', 'x1']), visibleIds());
    check('stack has two entries', JSON.stringify(stackIds()) === JSON.stringify(['hub', 'n1']));
    check('double-click on the current centre does not push again', (dbl('n1'), stackIds().length === 2));
    crumbItems()[1].dispatch('click');
    await tick();
    check('middle crumb truncates the stack', JSON.stringify(stackIds()) === JSON.stringify(['hub']) && crumbTexts().length === 2, crumbTexts());
    check('truncate restores the hub focus with its hops', same(visibleIds(), ['hub', 'n1', 'n2', 'n3', 'x1', 'h1']), visibleIds());
    check('truncate announces going back', status() === 'Focus: back to Hub core.', status());

    // --- exit ---
    calls.length = 0;
    exitBtn.dispatch('click');
    await tick();
    check('Exit focus restores every filter-visible node', same(visibleIds(), ['hub', 'n1', 'n2', 'n3', 'x1', 'x2', 'h1', 'lone']), visibleIds());
    check('Exit focus hides the bar', !barShown());
    check('Exit focus refits to all visible nodes', lastFit() && same(lastFit().opts.nodes, ['hub', 'n1', 'n2', 'n3', 'x1', 'x2', 'h1', 'lone']));
    check('Exit focus resizes the canvas', calls.some((c) => c.kind === 'setSize'));
    check('Exit focus announces', status() === 'Focus ended.', status());
    check('exit event has a null id', lastChanged().detail.id === null && window._graphDebug.focus().stack.length === 0, lastChanged());
    check('resting 22-character label returns', lenOf(nodeSet().items.get('n3').label) === 22, nodeSet().items.get('n3').label);
    check('anchors are still hidden after exit', anchorNodes().every((a) => a.hidden === true));

    // --- All nodes crumb and Esc ---
    dbl('hub');
    await tick();
    crumbItems()[0].dispatch('click');
    await tick();
    check('the All nodes crumb exits', !barShown() && visibleIds().length === 8);
    dbl('hub');
    await tick();
    dbl('n2');
    await tick();
    check('two levels deep', JSON.stringify(stackIds()) === JSON.stringify(['hub', 'n2']));
    esc({ tagName: 'DIV', closest: () => null });
    await tick();
    check('Esc pops one level', JSON.stringify(stackIds()) === JSON.stringify(['hub']) && barShown());
    check('Esc back announces', status() === 'Focus: back to Hub core.', status());
    esc({ tagName: 'DIV', closest: () => null });
    await tick();
    check('Esc at depth 1 exits', stackIds().length === 0 && !barShown() && visibleIds().length === 8);
    check('Esc with nothing to do changes nothing', (esc(undefined), visibleIds().length === 8));
    dbl('hub');
    await tick();
    esc({ tagName: 'INPUT', closest: () => null });
    esc({ tagName: 'TEXTAREA', closest: () => null });
    esc({ tagName: 'SELECT', closest: () => null });
    esc({ tagName: 'DIV', isContentEditable: true, closest: () => null });
    esc({ tagName: 'DIV', closest: (sel) => (sel.includes('chat-panel') ? {} : null) });
    check('Esc in inputs, editable text and the chat panel does nothing', stackIds().length === 1);
    winEvent('graph-panel-closed');
    esc({ tagName: 'DIV', closest: () => null });
    check('Esc with the Graph tab inactive does nothing', stackIds().length === 1);
    winEvent('graph-panel-opened');
    esc({ tagName: 'DIV', closest: () => null });
    check('Esc works again when the tab returns', stackIds().length === 0);

    // --- graph-focus-node / graph-focus-exit ---
    windowEvents.length = 0;
    winEvent('graph-focus-node', { id: 'hub', hops: 2 });
    await tick();
    check('graph-focus-node enters 2-hop focus', JSON.stringify(stackIds()) === JSON.stringify(['hub'])
      && same(visibleIds(), ['hub', 'n1', 'n2', 'n3', 'x1', 'h1']), visibleIds());
    check('graph-focus-node 2 hops checks the 2 hops radio', hop2.getAttribute('aria-checked') === 'true');
    winEvent('graph-focus-node', { id: 'hub', hops: 1 });
    await tick();
    check('same id rewrites the top entry instead of pushing', JSON.stringify(stackIds()) === JSON.stringify(['hub'])
      && window._graphDebug.focus().stack[0].hops === 1 && visibleIds().length === 4, window._graphDebug.focus());
    check('rewriting hops announces and dispatches', lastChanged().detail.hops === 1);
    const nBefore = changedEvents().length;
    winEvent('graph-focus-node', { id: 'does-not-exist', hops: 1 });
    winEvent('graph-focus-node', { id: 12, hops: 1 });
    winEvent('graph-focus-node', {});
    winEvent('graph-focus-node', undefined);
    check('unknown or malformed ids are ignored', stackIds().length === 1 && changedEvents().length === nBefore);
    winEvent('graph-focus-node', { id: 'n2', hops: 99 });
    await tick();
    check('hops outside 1 or 2 clamp to 1', stackIds().length === 2 && window._graphDebug.focus().stack[1].hops === 1);
    check('anchor ids cannot be focused', (winEvent('graph-focus-node', { id: '__anchor:c1', hops: 1 }), stackIds().length === 2));
    winEvent('graph-focus-exit');
    await tick();
    check('graph-focus-exit leaves focus', stackIds().length === 0 && !barShown() && visibleIds().length === 8);
    winEvent('graph-focus-exit');
    check('graph-focus-exit while unfocused is harmless', stackIds().length === 0);
    check('every change dispatched graph-focus-changed', changedEvents().length >= 4);
    check('source node cannot be focused while hidden', (winEvent('graph-focus-node', { id: 's1', hops: 1 }), stackIds().length === 0));
    check('a node with no eligible neighbour is not focused by dblclick', (dbl('lone'), stackIds().length === 0 && !barShown()));

    // --- hostile name stays literal ---
    dbl('hub');
    await tick();
    dbl('n2');
    await tick();
    dbl('h1');
    await tick();
    const hostileCrumb = crumbTexts()[crumbTexts().length - 1];
    check('hostile name renders literally in the crumb', hostileCrumb === '<img src=x onerror=alert(1)>', hostileCrumb);
    check('crumb title carries the full name', crumbItems()[crumbItems().length - 1].getAttribute('title') === '<img src=x onerror=alert(1)>');
    check('no crumb used innerHTML', crumbsEl.innerHTML === '' && crumbItems().every((c) => c.innerHTML === ''));
    exitBtn.dispatch('click');
    await tick();

    // --- rebuild resets ---
    dbl('hub');
    await tick();
    await graph.initGraph({});
    for (let i = 0; i < 20; i++) await tick(0);
    check('buildGraph resets the focus stack and bar', stackIds().length === 0 && !barShown());
    check('rebuild shows every node again', visibleIds().length === 8, visibleIds());
  }

  if (mode === 'focus-filters') {
    // --- sources only join with Show sources ---
    const srcBtn = document.getElementById('graph-show-sources-btn');
    dbl('hub');
    await tick();
    check('sources hidden: not in the focus set', !visibleIds().includes('s1') && visibleIds().length === 4, visibleIds());
    srcBtn.dispatch('click');
    await tick();
    check('Show sources adds the source neighbour to the set', visibleIds().includes('s1') && visibleIds().length === 5, visibleIds());
    check('the bar counts the source', textOf(hop1) === '1 hop · 5 nodes', textOf(hop1));
    srcBtn.dispatch('click');
    await tick();
    check('Hide sources removes it again', !visibleIds().includes('s1') && visibleIds().length === 4, visibleIds());
    check('focus info counts match', window._graphDebug.focusInfo('hub').counts[1] === 4 && window._graphDebug.focusInfo('hub').counts[2] === 6, window._graphDebug.focusInfo('hub'));
    const info = window._graphDebug.focusInfo('n1');
    check('focusInfo reports counts for any node with the current centre', info.centerId === 'hub' && info.hops === 1 && info.counts[1] === 3, info);

    // --- a filter that removes a neighbour shrinks the set and counts ---
    windowEvents.length = 0;
    search.value = 'core';
    search.dispatch('input');
    await tick();
    check('search shrinks the focus set', same(visibleIds(), ['hub', 'n1', 'n2']), visibleIds());
    check('the 1 hop count shrinks', textOf(hop1) === '1 hop · 3 nodes', textOf(hop1));
    check('the 2 hops count shrinks', textOf(hop2) === '2 hops · 4 nodes', textOf(hop2));
    check('the change is dispatched with new counts', lastChanged() && lastChanged().detail.counts[1] === 3 && lastChanged().detail.counts[2] === 4, lastChanged());
    check('focus survives a filter that keeps the centre', stackIds().length === 1 && barShown());
    hop2.dispatch('click');
    await tick();
    check('2 hops respects the filter too', same(visibleIds(), ['hub', 'n1', 'n2', 'x1']), visibleIds());
    search.value = '';
    search.dispatch('input');
    await tick();
    check('clearing the filter restores the set', same(visibleIds(), ['hub', 'n1', 'n2', 'n3', 'x1', 'h1']), visibleIds());
    hop1.dispatch('click');
    await tick();

    // --- the filter removes the centre ---
    windowEvents.length = 0;
    search.value = 'alpha';
    search.dispatch('input');
    await tick();
    check('hiding the centre exits focus', stackIds().length === 0 && !barShown());
    check('the filter ending is announced', status() === 'Focus ended: Hub core is hidden by the current filters.', status());
    check('the hint slot shows the same text', hint() === 'Focus ended: Hub core is hidden by the current filters.', hint());
    check('exit is dispatched', lastChanged() && lastChanged().detail.id === null, lastChanged());
    check('filtered view is not forced back to a focus', same(visibleIds(), ['n1']), visibleIds());
    search.value = '';
    search.dispatch('input');
    await tick();
    check('all nodes return when the filter clears', visibleIds().length === 8, visibleIds());

    // --- grouping change while focused ---
    dbl('hub');
    await tick();
    calls.length = 0;
    groupButtons.family.dispatch('click');
    await tick(120);
    check('relayout starts', stabilizeCalls().length > 0);
    check('focus survives the relayout', stackIds().length === 1 && same(visibleIds(), ['hub', 'n1', 'n2', 'n3']), visibleIds());
    settle();
    await tick();
    const fitAfter = lastFit();
    check('relayout refits to the focus set', fitAfter && same(fitAfter.opts.nodes, ['hub', 'n1', 'n2', 'n3']), fitAfter && fitAfter.opts.nodes);
    check('mode switched to family while focused', window._graphDebug.mode === 'family');
    check('anchors never join the fit', fitAfter && fitAfter.opts.nodes.every((id) => !String(id).startsWith('__anchor')));
    exitBtn.dispatch('click');
    await tick();
    check('exit after a grouping change restores the nodes', visibleIds().length === 8 && anchorNodes().every((a) => a.hidden === true));
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
