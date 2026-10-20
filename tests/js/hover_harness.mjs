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
  }

  if (mode === 'wiring') {
    const datasets = [];
    const handlers = new Map();
    class DataSet {
      constructor(items) { datasets.push(this); this.items = new Map(items.map((i) => [i.id, { ...i }])); }
      update(us) { for (const u of [].concat(us)) this.items.set(u.id, { ...(this.items.get(u.id) || {}), ...u }); }
      get(id) { return id === undefined ? [...this.items.values()] : this.items.get(id); }
      getIds() { return [...this.items.keys()]; }
    }
    class Network {
      constructor() {
        return new Proxy(this, {
          get(_t, prop) {
            if (prop === 'getScale') return () => 1;
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

    const nodeDs = datasets.find((d) => [...d.items.values()].some((i) => 'label' in i));
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

    fire('click', { nodes: [target], edges: [] });
    check('click pins card', visible());
    fire('hoverNode', { node: 'compound:semaglutide', pointer: { DOM: { x: 10, y: 10 } } });
    advance(160);
    fire('blurNode', { node: target });
    check('pinned card survives blur', visible());

    for (const fn of docListeners.keydown || []) fn({ key: 'Escape' });
    check('Escape hides', !visible());
    fire('blurNode', { node: target });
    check('Escape clears pin', !visible());

    fire('click', { nodes: [target], edges: [] });
    check('re-pin', visible());
    for (const ev of ['resize', 'scroll']) {
      fire('click', { nodes: [target], edges: [] });
      if (!visible()) fire('click', { nodes: [target], edges: [] });
      for (const fn of winListeners[ev] || []) fn({});
      check(`window ${ev} hides`, !visible(), (winListeners[ev] || []).length);
    }
    check('no innerHTML on card', violations.filter((v) => v.includes('graph-hover-card')).length === 0, violations);
  }
} catch (e) {
  failed.push({ name: 'harness error', detail: String((e && e.stack) || e) });
}

console.log(JSON.stringify({ passed, failed, timings }));
process.exit(failed.length ? 1 : 0);
