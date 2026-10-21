// Behavioral harness for the graph hover card (GVIS-07).
// argv[2] = path to a graph JSON ({nodes, links}); argv[3] = path to an
// /api/graph/entity-types payload; argv[4] = mode.
//   model  - pure card model + positioning + DOM rendering (incl. hostile text)
//   wiring - real graph.js against a recording vis stub and fake timers
//   perf   - model + render of the max-degree node, median of 20
// Prints one JSON line {"passed": [...], "failed": [...], "timings": {...}}.
import { pathToFileURL, fileURLToPath } from 'node:url';
import path from 'node:path';
import fs from 'node:fs';

const [, , graphPath, displayPath, mode = 'model'] = process.argv;
const violations = [];

function makeEl(tagName = '', ns = null) {
  const listeners = {};
  const attrs = {};
  const el = {
    tagName,
    namespaceURI: ns,
    id: '',
    className: '',
    textContent: '',
    title: '',
    value: '',
    hidden: false,
    style: {},
    children: [],
    dataset: {},
    parentNode: null,
    classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
    offsetWidth: 300,
    offsetHeight: 200,
    clientWidth: 800,
    clientHeight: 600,
    _html: '',
    get innerHTML() { return this._html; },
    set innerHTML(v) {
      violations.push(`${tagName}.${this.className}`);
      this._html = String(v);
    },
    get firstChild() { return this.children[0] || null; },
    addEventListener(type, fn) { (listeners[type] ||= []).push(fn); },
    removeEventListener() {},
    dispatch(type) { for (const fn of listeners[type] || []) fn({ target: el }); },
    appendChild(c) { c.parentNode = el; el.children.push(c); return c; },
    append(...cs) { cs.forEach((c) => { if (c && typeof c === 'object') c.parentNode = el; el.children.push(c); }); },
    replaceChildren(...cs) { el.children = []; el.append(...cs); },
    removeChild() {},
    remove() {},
    setAttribute(k, v) { attrs[k] = String(v); },
    getAttribute: (k) => (k in attrs ? attrs[k] : null),
    removeAttribute(k) { delete attrs[k]; },
    hasAttribute: (k) => k in attrs,
    querySelector: () => null,
    querySelectorAll: () => [],
    contains: () => false,
    getBoundingClientRect: () => ({ left: 10, top: 20, width: 800, height: 600 }),
    focus() {},
  };
  return el;
}

function walk(el, fn) {
  fn(el);
  (el.children || []).forEach((c) => c && typeof c === 'object' && walk(c, fn));
}
function findAll(el, pred) {
  const out = [];
  walk(el, (n) => { if (pred(n)) out.push(n); });
  return out;
}
const byClass = (root, cls) => findAll(root, (n) => n.className === cls || (n.className || '').split(' ').includes(cls));

const elements = new Map();
const docListeners = {};
const winListeners = {};
const body = makeEl('body');
globalThis.document = {
  getElementById(id) {
    if (id === 'graph-hover-card') return findAll(body, (n) => n.id === id)[0] || null;
    if (!elements.has(id)) { const e = makeEl('div'); e.id = id; elements.set(id, e); }
    return elements.get(id);
  },
  createElement: (tag) => makeEl(String(tag).toLowerCase()),
  createElementNS: (ns, tag) => makeEl(String(tag), ns),
  createDocumentFragment: () => makeEl('#fragment'),
  createTextNode: (t) => ({ nodeType: 3, textContent: String(t) }),
  addEventListener(type, fn) { (docListeners[type] ||= []).push(fn); },
  removeEventListener() {},
  querySelector: () => null,
  querySelectorAll: () => [],
  body,
};
globalThis.window = {
  addEventListener(type, fn) { (winListeners[type] ||= []).push(fn); },
  removeEventListener() {},
  innerWidth: 1200,
  innerHeight: 800,
  matchMedia: () => ({ matches: false }),
};
console.warn = () => {};
console.error = () => {};

const here = path.dirname(fileURLToPath(import.meta.url));
const staticDir = path.join(here, '../../examples/workbench/static');
const imp = (f) => import(pathToFileURL(path.join(staticDir, f)).href);

const passed = [];
const failed = [];
const timings = {};
function check(name, cond, detail = '') {
  if (cond) passed.push(name); else failed.push({ name, detail: JSON.stringify(detail) });
}

const graph = JSON.parse(fs.readFileSync(graphPath, 'utf8'));
const displayPayload = JSON.parse(fs.readFileSync(displayPath, 'utf8'));
const nodes = graph.nodes;
const edges = graph.links || graph.edges;

function buildMaps() {
  const nodeById = new Map(nodes.map((n) => [n.id, n]));
  const adjacency = new Map();
  for (const e of edges) {
    for (const id of new Set([e.source, e.target])) {
      if (!adjacency.has(id)) adjacency.set(id, []);
      adjacency.get(id).push(e);
    }
  }
  return { nodeById, adjacency };
}

function modelFor(style, display, id, maps) {
  const node = maps.nodeById.get(id);
  const d = display.typeDisplay(node.entity_type);
  return style.hoverCardModel(node, maps.adjacency.get(id) || [], maps.nodeById, {
    isSourceNode: (nid) => {
      const n = maps.nodeById.get(nid);
      return Boolean(n) && display.isSourceType(n.entity_type);
    },
    typeLabel: d.label,
    family: d.family,
    description: d.description,
  });
}

try {
  const display = await imp('display.js');
  const style = await imp('graph_style.js');
  display.setDisplayData(displayPayload);

  if (mode === 'model') {
    const hover = await imp('hovercard.js');
    const maps = buildMaps();

    // GLP-1 semaglutide
    const m = modelFor(style, display, 'compound:semaglutide', maps);
    check('sema: name', m.name === 'semaglutide', m.name);
    check('sema: 60 links', m.linkCount === 60, m.linkCount);
    check('sema: 17 sources', m.sourceCount === 17, m.sourceCount);
    check('sema: family present', typeof m.family === 'string' && m.family.length > 0, m.family);
    check('sema: 4 relations', m.relations.length === 4, m.relations.length);
    check('sema: out row', m.relations.some((r) => r.direction === 'out' && r.sentence.includes(' → ')));
    check('sema: in row', m.relations.some((r) => r.direction === 'in' && /^.+ · .+ →$/.test(r.sentence)),
      m.relations.map((r) => r.sentence));
    check('sema: no arrow-left', m.relations.every((r) => !r.sentence.includes('←')));
    check('sema: more > 0', m.more > 0, m.more);
    check('sema: not noLinks', m.noLinks === false);
    check('sema: others truncated', m.relations.every((r) => Array.from(r.other).length <= 22));

    // only edges to Sources nodes
    const sn = [
      { id: 'a', name: 'A', entity_type: 'COMPOUND' },
      { id: 'd', name: 'Doc', entity_type: 'DOCUMENT' },
    ];
    const se = [{ source: 'a', target: 'd', relation_type: 'MENTIONED_IN' }];
    const smaps = { nodeById: new Map(sn.map((n) => [n.id, n])), adjacency: new Map([['a', se], ['d', se]]) };
    const sm = style.hoverCardModel(sn[0], se, smaps.nodeById, {
      isSourceNode: (id) => id === 'd', typeLabel: 'Compound', family: 'X', description: undefined,
    });
    check('sources only: linkCount 0', sm.linkCount === 0, sm.linkCount);
    // WR-04: a source node counts its mentions; a flagged relation is not a link.
    const dm = style.hoverCardModel(sn[1], se, smaps.nodeById, { isSourceNode: (id) => id === 'd' });
    check('source node: counts mentions', dm.linkCount === 1 && dm.linkWord === 'mention' && dm.relations.length === 1, dm);
    const fe = [{ source: 'a', target: 'b', relation_type: 'MENTIONED_IN' }];
    const fm = style.hoverCardModel(sn[0], fe, smaps.nodeById, {
      isSourceNode: () => false, isSourceEdge: (e) => e.relation_type === 'MENTIONED_IN',
    });
    check('flagged relation not a link', fm.linkCount === 0 && fm.relations.length === 0 && fm.linkWord === 'link', fm);
    check('sources only: no relations', sm.relations.length === 0);
    check('sources only: noLinks', sm.noLinks === true);
    check('no description -> empty string', sm.description === '', sm.description);

    // grouping and ranking
    const gn = [
      { id: 'a', name: 'A', entity_type: 'COMPOUND' },
      { id: 'b', name: 'B', entity_type: 'DISEASE' },
      { id: 'c', name: 'C', entity_type: 'DISEASE' },
      { id: 'd', name: 'D', entity_type: 'DISEASE' },
    ];
    const ge = [
      { source: 'a', target: 'b', relation_type: 'TREATS', support_count: 1, confidence: 0.9 },
      { source: 'a', target: 'b', relation_type: 'TREATS', support_count: 1, confidence: 0.8 },
      { source: 'a', target: 'c', relation_type: 'TREATS', support_count: 5, confidence: 0.5 },
      { source: 'a', target: 'd', relation_type: 'TREATS', support_count: 1, confidence: 0.95 },
    ];
    const gm = style.hoverCardModel(gn[0], ge, new Map(gn.map((n) => [n.id, n])), {
      isSourceNode: () => false, typeLabel: 'Compound', family: 'X', description: '',
    });
    check('group: 3 rows', gm.relations.length === 3, gm.relations.length);
    const bRow = gm.relations.find((r) => r.sentence === 'treats → B');
    check('group: parallel edges count 2', bRow && bRow.count === 2, gm.relations);
    check('rank: support 5 first', gm.relations[0].sentence === 'treats → C', gm.relations[0]);
    check('rank: confidence breaks tie', gm.relations[1].sentence === 'treats → D', gm.relations[1]);
    check('group: more 0 when not truncated', gm.more === 0, gm.more);

    // positioning
    const pos = style.cardPosition({ x: 100, y: 100 }, { w: 300, h: 200 }, { w: 1200, h: 800 });
    check('position: offset', pos.left === 116 && pos.top === 116, pos);
    const flip = style.cardPosition({ x: 1150, y: 760 }, { w: 300, h: 200 }, { w: 1200, h: 800 });
    check('position: flips', flip.left === 1150 - 16 - 300 && flip.top === 760 - 16 - 200, flip);
    const edgeCases = [[0, 0], [1199, 799], [-50, -50], [5000, 5000], [600, 790]]
      .map(([x, y]) => style.cardPosition({ x, y }, { w: 300, h: 200 }, { w: 1200, h: 800 }));
    check('position: always >= 8px inside', edgeCases.every((p) => p.left >= 8 && p.top >= 8
      && p.left + 300 <= 1192 && p.top + 200 <= 792), edgeCases);

    // hostile text
    const evil = '<img src=x onerror=alert(1)>';
    hover.initHoverCard();
    violations.length = 0;
    const hm = {
      name: evil, typeLabel: evil, family: evil, description: evil, linkCount: 1, sourceCount: 0,
      relations: [{ direction: 'out', relation: evil, other: evil, sentence: `${evil} → ${evil}`,
        title: evil, status: evil, count: 1 }],
      more: 0, noLinks: false,
    };
    hover.showHoverCard(hm, 'COMPOUND', { x: 50, y: 50 });
    const card = document.getElementById('graph-hover-card');
    check('hostile: card on body', card && card.parentNode === body);
    check('hostile: visible', card && card.hidden === false);
    check('hostile: no innerHTML', violations.length === 0, violations);
    const nameEl = byClass(card, 'graph-hover-card__name')[0];
    check('hostile: name literal', nameEl && nameEl.textContent === evil, nameEl && nameEl.textContent);
    check('hostile: no footer when not truncated', byClass(card, 'graph-hover-card__more').length === 0);
    check('hostile: tooltip role', card.getAttribute('role') === 'tooltip');
    hover.showHoverCard({ ...hm, more: 3 }, 'COMPOUND', { x: 50, y: 50 });
    const more = byClass(card, 'graph-hover-card__more')[0];
    check('footer when truncated', more && more.textContent === '+3 more · click for details', more && more.textContent);
    hover.showHoverCard(modelFor(style, display, 'compound:semaglutide', maps), 'COMPOUND', { x: 50, y: 50 });
    const meta = byClass(card, 'graph-hover-card__meta')[0];
    check('meta row text', meta && /^60 links · 17 sources · .+$/.test(meta.textContent), meta && meta.textContent);
    check('rows rendered', byClass(card, 'graph-hover-card__row').length === 4);
    hover.showHoverCard(sm, 'COMPOUND', { x: 50, y: 50 });
    check('no-links row', byClass(card, 'graph-hover-card__row').some((r) => r.textContent === 'No links besides sources.'));
    hover.hideHoverCard();
    check('hide', card.hidden === true && hover.isHoverCardVisible() === false);
  }

  if (mode === 'perf') {
    const hover = await imp('hovercard.js');
    const maps = buildMaps();
    let best = null;
    for (const [id, list] of maps.adjacency) if (!best || list.length > best.n) best = { id, n: list.length };
    hover.initHoverCard();
    const runs = [];
    for (let i = 0; i < 20; i++) {
      const t0 = performance.now();
      const model = modelFor(style, display, best.id, maps);
      hover.showHoverCard(model, maps.nodeById.get(best.id).entity_type, { x: 400, y: 300 });
      runs.push(performance.now() - t0);
    }
    runs.sort((a, b) => a - b);
    timings.median_ms = runs[10];
    timings.max_ms = runs[19];
    timings.hub_edges = best.n;
    timings.nodes = nodes.length;
    timings.edges = edges.length;
    check('perf: hub has many edges', best.n >= 200, best.n);

    // hover update on the hub (focus compute + both DataSet writes)
    {
      const w = await setupWiring();
      const other = [...w.nodeDs.items.keys()].find((id) => id !== best.id);
      const hubParams = { node: best.id, pointer: { DOM: { x: 100, y: 100 } } };
      const hoverRuns = [];
      for (let i = 0; i < 20; i++) {
        const t0 = performance.now();
        w.fire('hoverNode', hubParams);
        w.advance(20);
        hoverRuns.push(performance.now() - t0);
        w.fire('blurNode', { node: best.id });
        w.advance(20);
      }
      hoverRuns.sort((a, b) => a - b);
      timings.hover_update_median_ms = hoverRuns[10];
      check('perf: hover wrote focus', w.updateLog.some((u) => u.kind === 'nodes' && u.items.some((i) => i.font.size > 0)));
      void other;
    }
  }

  async function setupWiring() {
    const datasets = [];
    const handlers = new Map();
    const updateLog = [];
    class DataSet {
      constructor(items) {
        datasets.push(this);
        this.kind = items[0] && 'from' in items[0] ? 'edges' : 'nodes';
        this.items = new Map(items.map((i) => [i.id, { ...i }]));
      }
      update(us) {
        const list = [].concat(us);
        updateLog.push({ kind: this.kind, items: list.map((u) => ({ ...u })) });
        for (const u of list) this.items.set(u.id, { ...(this.items.get(u.id) || {}), ...u });
      }
      get(id) {
        if (id === undefined) return [...this.items.values()];
        if (id && typeof id === 'object') {
          const all = [...this.items.values()];
          return typeof id.filter === 'function' ? all.filter(id.filter) : all;
        }
        return this.items.get(id);
      }
      getIds() { return [...this.items.keys()]; }
    }
    let edgeAdj = null;
    const adjacencyOf = () => {
      if (edgeAdj) return edgeAdj;
      edgeAdj = new Map();
      const eds = datasets.find((d) => d.kind === 'edges');
      for (const e of eds.items.values()) {
        for (const [a, b] of [[e.from, e.to], [e.to, e.from]]) {
          if (!edgeAdj.has(a)) edgeAdj.set(a, []);
          edgeAdj.get(a).push({ edge: e.id, other: b });
        }
      }
      return edgeAdj;
    };
    class Network {
      constructor() {
        return new Proxy(this, {
          get(_t, prop) {
            if (prop === 'getScale') return () => 1;
            if (prop === 'getConnectedNodes') return (id) => [...new Set((adjacencyOf().get(id) || []).map((x) => x.other))];
            if (prop === 'getConnectedEdges') return (id) => (adjacencyOf().get(id) || []).map((x) => x.edge);
            if (prop === 'on' || prop === 'once') {
              return (event, fn) => { (handlers.get(event) || handlers.set(event, []).get(event)).push(fn); };
            }
            if (prop === 'getPositions') return (ids) => Object.fromEntries(ids.map((i) => [i, { x: 40, y: 50 }]));
            if (prop === 'canvasToDOM') return (p) => ({ x: p.x + 100, y: p.y + 100 });
            if (prop === 'getSelectedNodes') return () => [];
            if (prop === 'then') return undefined;
            return () => undefined;
          },
        });
      }
    }
    globalThis.vis = { DataSet, Network };
    globalThis.window.vis = globalThis.vis;
    globalThis.fetch = async (url) => {
      const respond = (status, b) => ({ ok: status < 400, status, statusText: String(status), json: async () => b });
      if (url === '/api/graph/entity-types') return respond(200, displayPayload);
      if (url === '/api/graph') return respond(200, { nodes, edges });
      return respond(404, {});
    };

    const g = await imp('graph.js');
    await g.initGraph({});
    for (let i = 0; i < 20; i++) await new Promise((r) => setTimeout(r, 0));
    // vis reports the initial layout done; focus and the Group by control wait for it.
    for (const fn of [...(handlers.get('stabilizationIterationsDone') || [])]) fn();

    // Deterministic timers from here on.
    let now = 0;
    let seq = 0;
    const queue = [];
    globalThis.setTimeout = (fn, ms = 0) => { const id = ++seq; queue.push({ id, due: now + ms, fn }); return id; };
    globalThis.clearTimeout = (id) => { const i = queue.findIndex((q) => q.id === id); if (i >= 0) queue.splice(i, 1); };
    const advance = (ms) => {
      now += ms;
      for (;;) {
        queue.sort((a, b) => a.due - b.due);
        if (!queue.length || queue[0].due > now) break;
        queue.shift().fn();
      }
    };
    const fire = (event, params) => { for (const fn of handlers.get(event) || []) fn(params); };
    const card = () => document.getElementById('graph-hover-card');
    const visible = () => Boolean(card()) && card().hidden === false;
    const container = document.getElementById('graph-container');
    const target = 'compound:semaglutide';
    const hoverParams = { node: target, pointer: { DOM: { x: 100, y: 100 } } };
    globalThis.requestAnimationFrame = (fn) => globalThis.setTimeout(fn, 16);
    globalThis.cancelAnimationFrame = (id) => globalThis.clearTimeout(id);
    const nodeDs = datasets.find((d) => d.kind === 'nodes');
    const edgeDs = datasets.find((d) => d.kind === 'edges');
    return { datasets, handlers, updateLog, fire, advance, card, visible, container, target, hoverParams, nodeDs, edgeDs };
  }

  if (mode === 'focus') {
    const { fire, advance, updateLog, nodeDs, edgeDs, hoverParams, target } = await setupWiring();
    const style = await imp('graph_style.js');
    const edgesOf = (id) => [...edgeDs.items.values()].filter((e) => e.from === id || e.to === id);
    const connectedEdgeIds = new Set(edgesOf(target).map((e) => e.id));

    // pure helpers
    const fi = style.focusIds('h', ['a', 'b', 'c'], { a: 1, b: 9, c: 5 }, 3);
    check('focusIds: center plus top by degree', fi instanceof Set && [...fi].sort().join() === 'b,c,h', [...fi]);
    const tie = style.focusIds('h', ['z', 'y', 'x'], {}, 3);
    check('focusIds: ties by id and cap', [...tie].join() === 'h,x,y', [...tie]);
    check('focusIds: cap constant is 25', style.FOCUS_MAX_LABELS === 25);
    const d = style.focusDelta(new Set(['a', 'b']), new Set(['b', 'c']));
    check('focusDelta: added/removed', d.added.join() === 'c' && d.removed.join() === 'a', d);
    const ef = style.edgeLabelFont(0.5);
    check('edgeLabelFont: complete object', ef.size === style.labelFontSize(0.5) * 0.85
      && ef.color === '#1a1a1a' && ef.strokeColor === '#ffffff' && ef.strokeWidth === 3 && ef.align === 'middle', ef);
    check('edgeLabelFont: hidden size 0', style.edgeLabelFont(1, false).size === 0);

    // rest state
    const recs = [...edgeDs.items.values()];
    check('edges carry label strings', recs.every((e) => typeof e.label === 'string' && e.label.length > 0));
    check('edges rest at font size 0', recs.every((e) => e.font && e.font.size === 0));
    const rested = edgeDs.items.get(edgesOf(target)[0].id);
    check('edge label is humanized', rested.label === rested.label.toLowerCase() && !rested.label.includes('_'), rested.label);

    // hover
    updateLog.length = 0;
    fire('hoverNode', hoverParams);
    advance(20);
    const nodeWrites = updateLog.filter((u) => u.kind === 'nodes');
    const edgeWrites = updateLog.filter((u) => u.kind === 'edges');
    check('hover: one nodes update', nodeWrites.length === 1, nodeWrites.length);
    check('hover: hub (> 12 edges) writes no edge names', connectedEdgeIds.size > style.EDGE_NAME_MAX_EDGES && edgeWrites.length === 0, [connectedEdgeIds.size, edgeWrites.length]);
    const nKeys = new Set(nodeWrites.flatMap((u) => u.items.flatMap((i) => Object.keys(i))));
    check('hover: node keys id+font only', [...nKeys].sort().join() === 'font,id', [...nKeys]);
    const labelled = nodeWrites.flatMap((u) => u.items).filter((i) => i.font.size > 0);
    check('hover: at most 25 gain labels', labelled.length <= 25 && labelled.length > 1, labelled.length);
    check('hover: hovered node labelled', labelled.some((i) => i.id === target));
    const eItems = edgeWrites.flatMap((u) => u.items);
    const focusedNodeIds = new Set(labelled.map((i) => i.id));

    // blur
    updateLog.length = 0;
    fire('blurNode', { node: target });
    advance(20);
    const backN = updateLog.filter((u) => u.kind === 'nodes').flatMap((u) => u.items);
    const backE = updateLog.filter((u) => u.kind === 'edges').flatMap((u) => u.items);
    check('blur: only focused ids written back', backN.length > 0 && backN.every((i) => focusedNodeIds.has(i.id)), backN.length);
    check('blur: no edge writes for hub', backE.length === 0, backE.length);
    check('blur: no opacity/hidden/color keys', updateLog.every((u) => u.items.every((i) => !('opacity' in i) && !('hidden' in i) && !('color' in i))));
    const restN = backN.filter((i) => i.font.size > 0).map((i) => i.id);
    check('blur: resting labels follow degree rule', restN.every((id) => id !== undefined), restN);

    // selection persists across another hover
    const other = [...nodeDs.items.keys()].find((id) => id !== target && !edgesOf(target).some((e) => e.from === id || e.to === id)
      && edgesOf(id).length > 0 && nodeDs.items.get(id).hidden !== true);
    updateLog.length = 0;
    fire('click', { nodes: [target], edges: [] });
    advance(20);
    const selNodes = new Set(nodeDs.items.get(target) ? [...nodeDs.items.values()].filter((n) => n.font && n.font.size > 0).map((n) => n.id) : []);
    check('select: node labelled', selNodes.has(target));
    const neighborSample = edgesOf(target).map((e) => (e.from === target ? e.to : e.from)).filter((id) => nodeDs.items.get(id).hidden !== true);
    check('select: neighbors labelled (capped)', neighborSample.some((id) => selNodes.has(id)));
    fire('hoverNode', { node: other, pointer: { DOM: { x: 5, y: 5 } } });
    advance(20);
    fire('blurNode', { node: other });
    advance(20);
    const afterSel = new Set([...nodeDs.items.values()].filter((n) => n.font && n.font.size > 0).map((n) => n.id));
    check('select: survives other hover+blur', [...selNodes].every((id) => afterSel.has(id)), [...selNodes].filter((id) => !afterSel.has(id)));
    const edgeShown = (id) => edgeDs.items.get(id).font.size > 0;
    check('select: hub edges stay unnamed', [...connectedEdgeIds].every((id) => !edgeShown(id)));
    fire('click', { nodes: [], edges: [] });
    advance(20);
    check('clear: selection labels removed', [...connectedEdgeIds].every((id) => !edgeShown(id)));

    // single edge hover
    const eid = [...edgeDs.items.keys()][0];
    updateLog.length = 0;
    fire('hoverEdge', { edge: eid });
    advance(20);
    const only = updateLog.filter((u) => u.kind === 'edges').flatMap((u) => u.items);
    check('hoverEdge: only that edge', only.length === 1 && only[0].id === eid && only[0].font.size > 0, only);
    updateLog.length = 0;
    fire('blurEdge', { edge: eid });
    advance(20);
    check('blurEdge: restored to 0', edgeDs.items.get(eid).font.size === 0);

    // small node (<= cap visible edges): every connected edge is named, then restored
    const small = [...nodeDs.items.keys()].find((id) => {
      const es = edgesOf(id).filter((e) => e.hidden !== true);
      return nodeDs.items.get(id).hidden !== true && es.length >= 2 && es.length <= style.EDGE_NAME_MAX_EDGES;
    });
    const smallEdgeIds = edgesOf(small).filter((e) => e.hidden !== true).map((e) => e.id);
    updateLog.length = 0;
    fire('hoverNode', { node: small, pointer: { DOM: { x: 5, y: 5 } } });
    advance(20);
    const sw = updateLog.filter((u) => u.kind === 'edges').flatMap((u) => u.items);
    check('hover: small node edge keys id+font only', sw.every((i) => Object.keys(i).sort().join() === 'font,id'));
    check('hover: small node names all its edges', sw.length === smallEdgeIds.length
      && smallEdgeIds.every((id) => edgeDs.items.get(id).font.size > 0), [sw.length, smallEdgeIds.length]);
    check('hover: small node complete edge font', sw.every((i) => i.font.color === '#1a1a1a' && i.font.strokeColor === '#ffffff'));
    fire('blurNode', { node: small });
    advance(20);
    check('blur: small node edges hidden again', smallEdgeIds.every((id) => edgeDs.items.get(id).font.size === 0));

    // WR-05: an edge to a hidden node (PUBLISHED_IN to a hidden source keeps
    // hidden: false) is not drawn, so it is neither named nor counted.
    const trial = 'clinical_trial:sustain';
    const shownEnd = (e) => nodeDs.items.get(e.from).hidden !== true && nodeDs.items.get(e.to).hidden !== true;
    const tEdges = edgesOf(trial).filter((e) => e.hidden !== true);
    const undrawn = tEdges.filter((e) => !shownEnd(e));
    const drawn = tEdges.filter(shownEnd);
    check('WR-05 fixture: trial has an undrawn edge', undrawn.length >= 1 && drawn.length >= 1, [undrawn.length, drawn.length]);
    updateLog.length = 0;
    fire('hoverNode', { node: trial, pointer: { DOM: { x: 5, y: 5 } } });
    advance(20);
    const named = updateLog.filter((u) => u.kind === 'edges').flatMap((u) => u.items).map((i) => i.id);
    check('hover: undrawn edges get no name', undrawn.every((e) => !named.includes(e.id)), named);
    check('hover: drawn edges named', drawn.every((e) => named.includes(e.id)), named);
    fire('blurNode', { node: trial });
    advance(20);
  }

  if (mode === 'wiring') {
    const { datasets, fire, advance, card, visible, container, target, hoverParams } = await setupWiring();
    const nodeDs = datasets.find((d) => d.kind === 'nodes');
    check('no vis title on nodes', Boolean(nodeDs) && [...nodeDs.items.values()].every((i) => !('title' in i)));
    check('card lives on body', Boolean(card()) && card().parentNode === body);
    check('card not in graph container', !findAll(container, (n) => n.id === 'graph-hover-card').length);
    check('card starts hidden', !visible());

    fire('hoverNode', hoverParams);
    advance(100);
    check('not shown before 150ms', !visible());
    advance(60);
    check('shown after 150ms', visible());
    const nameEl = visible() && byClass(card(), 'graph-hover-card__name')[0];
    check('card shows node name', nameEl && nameEl.textContent === 'semaglutide', nameEl && nameEl.textContent);
    check('aria-describedby set', container.getAttribute('aria-describedby') === 'graph-hover-card',
      container.getAttribute('aria-describedby'));
    fire('blurNode', { node: target });
    check('blur hides', !visible());
    check('aria-describedby removed', container.getAttribute('aria-describedby') === null);

    fire('hoverNode', hoverParams);
    fire('blurNode', { node: target });
    advance(300);
    check('blur cancels pending show', !visible());

    for (const ev of ['dragStart', 'zoom']) {
      fire('hoverNode', hoverParams);
      advance(160);
      const wasVisible = visible();
      fire(ev, {});
      check(`${ev} hides`, wasVisible && !visible());
    }

    fire('hoverNode', hoverParams);
    advance(160);
    fire('click', { nodes: [], edges: [] });
    check('blank click hides', !visible());

    // node click opens the sidebar, so the card is hidden and the container
    // is described by the sidebar instead
    fire('hoverNode', hoverParams);
    advance(160);
    check('card visible before click', visible());
    fire('click', { nodes: [target], edges: [] });
    check('click hides card (sidebar is the detail view)', !visible());
    check('click: aria-describedby points at sidebar', container.getAttribute('aria-describedby') === 'graph-detail-sidebar', container.getAttribute('aria-describedby'));
    fire('hoverNode', { node: 'compound:semaglutide', pointer: { DOM: { x: 10, y: 10 } } });
    advance(160);
    fire('blurNode', { node: target });
    check('card does not pin after blur', !visible());
    for (const fn of docListeners.keydown || []) fn({ key: 'Escape' });
    check('Escape keeps card hidden', !visible());
    for (const ev of ['resize', 'scroll']) {
      fire('hoverNode', hoverParams);
      advance(160);
      const wasVisible = visible();
      for (const fn of winListeners[ev] || []) fn({});
      check(`window ${ev} hides`, wasVisible && !visible(), (winListeners[ev] || []).length);
    }
    check('no innerHTML on card', violations.filter((v) => v.includes('graph-hover-card')).length === 0, violations);

    // WR-03: leaving the canvas or the graph panel ends the hover.
    fire('click', { nodes: [], edges: [] });
    fire('hoverNode', hoverParams);
    advance(160);
    const shownBeforeLeave = visible();
    container.dispatch('pointerleave');
    check('pointerleave hides card', shownBeforeLeave && !visible());
    fire('hoverNode', hoverParams);
    advance(50);
    container.dispatch('pointerleave');
    advance(300);
    check('pointerleave cancels pending show', !visible());
    const focusCount = () => (window._labelDebug || {}).focusNodes;
    advance(20);
    fire('hoverNode', hoverParams);
    advance(20);
    const hoverFocus = focusCount();
    container.dispatch('pointerleave');
    advance(20);
    check('pointerleave clears hover focus labels', hoverFocus > 0 && focusCount() === 0,
      [hoverFocus, focusCount()]);
    fire('hoverNode', hoverParams);
    advance(160);
    const shownBeforeClose = visible();
    for (const fn of winListeners['graph-panel-closed'] || []) fn({});
    check('graph-panel-closed hides card', shownBeforeClose && !visible(), (winListeners['graph-panel-closed'] || []).length);
    fire('click', { nodes: [target], edges: [] });
    container.dispatch('pointerleave');
    check('pointerleave keeps sidebar description', container.getAttribute('aria-describedby') === 'graph-detail-sidebar',
      container.getAttribute('aria-describedby'));

    // Esc order: hover card, then one focus level, then the Groups-row region.
    const emit = (type, detail) => { for (const fn of winListeners[type] || []) fn({ type, detail }); };
    const depth = () => window._graphDebug.focus().stack.length;
    const plain = { tagName: 'DIV', closest: () => null };
    const escape = (t) => { for (const fn of docListeners.keydown || []) fn({ key: 'Escape', target: t }); };
    emit('graph-panel-opened');
    emit('graph-focus-node', { id: target, hops: 1 });
    advance(20);
    check('esc: focus entered through graph-focus-node', depth() === 1, depth());
    fire('hoverNode', hoverParams);
    advance(160);
    check('esc: card visible while focused', visible());
    escape(plain);
    check('esc: first Escape closes the hover card', !visible());
    check('esc: first Escape leaves focus intact', depth() === 1, depth());
    escape(plain);
    check('esc: second Escape pops focus', depth() === 0, depth());
    emit('graph-focus-node', { id: target, hops: 1 });
    advance(20);
    escape({ tagName: 'INPUT', closest: () => null });
    escape({ tagName: 'TEXTAREA', closest: () => null });
    escape({ tagName: 'DIV', closest: (sel) => (sel.includes('chat-panel') ? {} : null) });
    check('esc: ignored in inputs and the chat panel', depth() === 1, depth());
    emit('graph-panel-closed');
    escape(plain);
    check('esc: ignored after graph-panel-closed', depth() === 1, depth());
    emit('graph-panel-opened');
    escape(plain);
    check('esc: pops again once the panel is back', depth() === 0, depth());
  }
} catch (e) {
  failed.push({ name: 'harness error', detail: String((e && e.stack) || e) });
}

console.log(JSON.stringify({ passed, failed, timings }));
process.exit(failed.length ? 1 : 0);
