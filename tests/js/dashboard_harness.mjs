// Behavioral harness for the Dashboard entity summary builders (dashboard.js).
// Imports the real dashboard.js (and display.js) against a stub DOM that records
// every created tag and every innerHTML assignment, then checks row order and
// markup, hostile type strings (SEC-01), click delegation, the totals button,
// the hint and the empty state.
// Prints one JSON line {"passed": [...], "failed": [...]} and exits 1 on failure.
import { pathToFileURL, fileURLToPath } from 'node:url';
import path from 'node:path';

const createdTags = [];
const innerHtmlWrites = [];

function parseSelector(sel) {
  const m = /^([a-z0-9]*)((?:\.[\w-]+)*)$/i.exec(sel);
  if (!m) return null;
  return { tag: m[1].toLowerCase(), classes: m[2].split('.').filter(Boolean) };
}

function makeEl(tag) {
  const listeners = {};
  const attrs = new Map();
  let text = '';
  const el = {
    tagName: String(tag).toLowerCase(),
    children: [],
    parentNode: null,
    className: '',
    appendChild(c) {
      if (c.parentNode) c.parentNode.removeChild(c);
      c.parentNode = el;
      el.children.push(c);
      return c;
    },
    append(...cs) { cs.forEach((c) => el.appendChild(typeof c === 'string' ? { textContent: c, children: [], isText: true } : c)); },
    removeChild(c) { el.children = el.children.filter((x) => x !== c); c.parentNode = null; return c; },
    replaceChildren(...cs) { el.children.forEach((c) => { c.parentNode = null; }); el.children = []; cs.forEach((c) => el.appendChild(c)); },
    setAttribute(k, v) { attrs.set(k, String(v)); if (k === 'class') el.className = String(v); },
    getAttribute: (k) => (attrs.has(k) ? attrs.get(k) : null),
    hasAttribute: (k) => attrs.has(k),
    removeAttribute(k) { attrs.delete(k); },
    addEventListener(type, fn) { (listeners[type] = listeners[type] || []).push(fn); },
    dispatch(type, extra = {}) {
      const event = { type, target: el, detail: 0, preventDefault() {}, ...extra };
      for (const fn of [...(listeners[type] || [])]) fn(event);
    },
    listenerCount: (type) => (listeners[type] || []).length,
    matches(sel) {
      const p = parseSelector(sel);
      if (!p) return false;
      const classes = String(el.className).split(/\s+/).filter(Boolean);
      return (!p.tag || p.tag === el.tagName) && p.classes.every((c) => classes.includes(c));
    },
    closest(sel) {
      for (let n = el; n; n = n.parentNode) if (n.matches && n.matches(sel)) return n;
      return null;
    },
    get dataset() {
      return new Proxy({}, {
        get: (_t, prop) => {
          const attr = `data-${String(prop).replace(/[A-Z]/g, (c) => `-${c.toLowerCase()}`)}`;
          return attrs.has(attr) ? attrs.get(attr) : undefined;
        },
      });
    },
    get textContent() { return text; },
    set textContent(v) { text = String(v); el.children = []; },
    get innerHTML() { return ''; },
    set innerHTML(v) { innerHtmlWrites.push(String(v)); },
    get firstChild() { return el.children[0] || null; },
  };
  return el;
}

globalThis.document = {
  createElement: (tag) => { createdTags.push(String(tag).toLowerCase()); return makeEl(tag); },
  createElementNS: (_ns, tag) => { createdTags.push(String(tag).toLowerCase()); return makeEl(tag); },
  createTextNode: (t) => ({ textContent: String(t), children: [], isText: true, parentNode: null }),
};

const textOf = (n) => (n.isText ? n.textContent : (n.textContent || '') + (n.children || []).map(textOf).join(''));
const walk = (n, fn) => { fn(n); (n.children || []).forEach((c) => walk(c, fn)); };
const find = (root, pred) => { const out = []; walk(root, (n) => { if (n.matches && pred(n)) out.push(n); }); return out; };
const byClass = (root, cls) => find(root, (n) => n.matches(`.${cls}`));
const byTag = (root, tag) => find(root, (n) => n.tagName === tag);

const passed = [];
const failed = [];
const check = (name, cond, detail = '') => {
  if (cond) passed.push(name); else failed.push({ name, detail: JSON.stringify(detail) });
};

const here = path.dirname(fileURLToPath(import.meta.url));
const staticDir = path.resolve(here, '..', '..', 'examples', 'workbench', 'static');
let dash;
try {
  const display = await import(pathToFileURL(path.join(staticDir, 'display.js')).href);
  display.setDisplayData({
    types: [
      { type: 'A', label: 'Alpha', color: '#5f66ed', shape: 'hexagon', family: 'Things' },
      { type: 'B', label: 'Beta Things', color: '#249e02', shape: 'square', family: 'Things' },
      { type: 'C', label: 'Charlie', color: '#ed4b43', shape: 'dot', family: 'Things' },
      { type: 'ONE', label: 'Solo', color: '#ed4b43', shape: 'dot', family: 'Things' },
      { type: 'DOCUMENT', label: 'Document', color: '#6b7280', shape: 'dot', family: 'Sources', is_source: true },
    ],
    families: [{ name: 'Things' }],
    relations: {},
    categories: {},
  });
  dash = await import(pathToFileURL(path.join(staticDir, 'dashboard.js')).href);
} catch (e) {
  process.stdout.write(JSON.stringify({ passed, failed: [{ name: 'import dashboard.js', detail: String(e && e.message) }] }) + '\n');
  process.exit(1);
}

const selected = [];
let showAll = 0;
const build = (entityCounts, totalNodes = 21, totalEdges = 5) => dash.buildEntitySummary({
  entityCounts,
  totalNodes,
  totalEdges,
  onSelectType: (type, event) => selected.push({ type, event }),
  onShowAll: () => { showAll += 1; },
});
const rowsOf = (root) => byClass(root, 'dashboard-link-row');

// --- rows-sorted ---
{
  const sortedRows = dash.sortEntityRows({ A: 3, B: 10, C: 3, DOCUMENT: 5 });
  check('rows-sorted: sortEntityRows is count desc then label asc',
    JSON.stringify(sortedRows.map((r) => r.type)) === JSON.stringify(['B', 'DOCUMENT', 'A', 'C']), sortedRows);
  check('rows-sorted: rows carry type, label and count',
    sortedRows[0].label === 'Beta Things' && sortedRows[0].count === 10, sortedRows[0]);
  const root = build({ A: 3, B: 10, C: 3, DOCUMENT: 5 });
  check('rows-sorted: data-entity-type order follows the sort',
    JSON.stringify(rowsOf(root).map((r) => r.getAttribute('data-entity-type'))) === JSON.stringify(['B', 'DOCUMENT', 'A', 'C']),
    rowsOf(root).map((r) => r.getAttribute('data-entity-type')));
}

// --- row-markup ---
{
  const root = build({ B: 10, ONE: 1 });
  const rows = rowsOf(root);
  check('row-markup: one row per type', rows.length === 2, rows.length);
  const [b, one] = rows;
  check('row-markup: rows are tr elements', rows.every((r) => r.tagName === 'tr'));
  const btns = byClass(b, 'dashboard-link-btn');
  check('row-markup: exactly one button per row', btns.length === 1 && byTag(b, 'button').length === 1, btns.length);
  const btn = btns[0];
  check('row-markup: button type and data-entity-type', btn.getAttribute('type') === 'button' && btn.getAttribute('data-entity-type') === 'B');
  check('row-markup: plural aria-label', btn.getAttribute('aria-label') === 'Show 10 Beta Things nodes in the graph', btn.getAttribute('aria-label'));
  check('row-markup: singular aria-label', byClass(one, 'dashboard-link-btn')[0].getAttribute('aria-label') === 'Show 1 Solo node in the graph',
    byClass(one, 'dashboard-link-btn')[0].getAttribute('aria-label'));
  const first = btn.children[0];
  check('row-markup: swatch is the first child of the button', first && first.tagName === 'svg' && first.getAttribute('class') === 'type-swatch', first && first.tagName);
  const label = byClass(btn, 'dashboard-link-label')[0];
  check('row-markup: label span text', label && label.tagName === 'span' && label.textContent === 'Beta Things');
  const chevron = byClass(btn, 'dashboard-link-chevron')[0];
  check('row-markup: chevron is decorative', chevron && chevron.getAttribute('aria-hidden') === 'true' && chevron.textContent === '›');
  const count = byClass(b, 'dashboard-count')[0];
  check('row-markup: count cell', count && count.tagName === 'td' && count.textContent === '10', count && count.textContent);
  check('row-markup: the button cell has no padding class hook', byClass(b, 'dashboard-link-cell').length === 1);
  const heads = byTag(root, 'th').map((t) => t.textContent);
  check('row-markup: table header', JSON.stringify(heads) === JSON.stringify(['Entity Type', 'Count']), heads);
  check('row-markup: section heading', byTag(root, 'h3')[0].textContent === 'Entity Summary');
}

// --- label-fallback ---
{
  const root = build({ MYSTERY_TYPE: 4 });
  const btn = byClass(root, 'dashboard-link-btn')[0];
  check('label-fallback: raw key is the label', byClass(btn, 'dashboard-link-label')[0].textContent === 'MYSTERY_TYPE');
  check('label-fallback: raw key in the aria-label', btn.getAttribute('aria-label') === 'Show 4 MYSTERY_TYPE nodes in the graph', btn.getAttribute('aria-label'));
}

// --- hostile ---
{
  const hostile = ['<img src=x onerror=1>', '"><script>alert(1)</script>'];
  createdTags.length = 0;
  innerHtmlWrites.length = 0;
  selected.length = 0;
  const root = build({ [hostile[0]]: 7, [hostile[1]]: 3 });
  check('hostile: no img or script element is created', !createdTags.includes('img') && !createdTags.includes('script'), createdTags);
  check('hostile: innerHTML is never assigned', innerHtmlWrites.length === 0, innerHtmlWrites);
  const rows = rowsOf(root);
  check('hostile: data-entity-type equals the raw string',
    JSON.stringify(rows.map((r) => r.getAttribute('data-entity-type'))) === JSON.stringify(hostile), rows.map((r) => r.getAttribute('data-entity-type')));
  check('hostile: label textContent equals the raw string',
    JSON.stringify(rows.map((r) => byClass(r, 'dashboard-link-label')[0].textContent)) === JSON.stringify(hostile));
  check('hostile: the tree holds no img or script element', find(root, (n) => n.tagName === 'img' || n.tagName === 'script').length === 0);
  const table = byTag(root, 'table')[0];
  table.dispatch('click', { target: byClass(rows[0], 'dashboard-count')[0] });
  check('hostile: click dispatches the raw string', selected.length === 1 && selected[0].type === hostile[0], selected.map((s) => s.type));
  build({});
  check('hostile: the empty state creates nothing risky either', innerHtmlWrites.length === 0);
}

// --- row-click ---
{
  selected.length = 0;
  showAll = 0;
  const root = build({ B: 10, A: 3 });
  const table = byTag(root, 'table')[0];
  const rows = rowsOf(root);
  const countCell = byClass(rows[0], 'dashboard-count')[0];
  table.dispatch('click', { target: countCell, detail: 1 });
  check('row-click: the count cell resolves to the row type', selected.length === 1 && selected[0].type === 'B', selected.map((s) => s.type));
  check('row-click: the event is passed through', selected[0].event && selected[0].event.detail === 1, selected[0] && selected[0].event);
  table.dispatch('click', { target: byClass(rows[1], 'dashboard-link-btn')[0], detail: 0 });
  check('row-click: a button click selects once', selected.length === 2 && selected[1].type === 'A' && selected[1].event.detail === 0, selected.map((s) => s.type));
  table.dispatch('click', { target: byTag(root, 'thead')[0] });
  table.dispatch('click', { target: byTag(root, 'th')[0] });
  table.dispatch('click', { target: table });
  check('row-click: the header and the table itself do nothing', selected.length === 2, selected.length);
  check('row-click: no row-level listeners (delegation)', rows.every((r) => r.listenerCount('click') === 0)
    && rows.every((r) => byClass(r, 'dashboard-link-btn')[0].listenerCount('click') === 0));
  check('row-click: the row click never shows all', showAll === 0);
}

// --- totals ---
{
  selected.length = 0;
  showAll = 0;
  const root = build({ B: 10, A: 3 }, 278, 900);
  const totals = byClass(root, 'dashboard-totals')[0];
  check('totals: paragraph wrapper', totals && totals.tagName === 'p');
  const btn = byClass(totals, 'dashboard-totals-btn')[0];
  check('totals: button markup', btn && btn.tagName === 'button' && btn.getAttribute('type') === 'button'
    && btn.getAttribute('data-dashboard-action') === 'show-all');
  check('totals: visible text', textOf(btn) === 'Total entities: 278 | Total relationships: 900 ›', textOf(btn));
  const strongs = byTag(btn, 'strong').map((s) => s.textContent);
  check('totals: numbers are in strong elements', JSON.stringify(strongs) === JSON.stringify(['278', '900']), strongs);
  check('totals: aria-label', btn.getAttribute('aria-label') === 'Show all 278 entities and 900 relationships in the graph', btn.getAttribute('aria-label'));
  btn.dispatch('click', { detail: 0 });
  check('totals: click calls onShowAll once and never onSelectType', showAll === 1 && selected.length === 0, { showAll, selected: selected.length });
}

// --- hint ---
{
  const root = build({ B: 10 });
  const hint = byClass(root, 'dashboard-hint')[0];
  check('hint: copy', hint && hint.tagName === 'p' && hint.textContent === 'Select an entity type to see those nodes in the graph.', hint && hint.textContent);
  const kids = root.children;
  const hintIdx = kids.indexOf(hint);
  const tableIdx = kids.findIndex((k) => byTag(k, 'table').length > 0 || k.tagName === 'table');
  check('hint: precedes the table', hintIdx >= 0 && tableIdx > hintIdx, { hintIdx, tableIdx });
}

// --- empty ---
{
  const BODY = 'The graph has no entities to summarize. Run /epistract:ingest to add documents, then reload the workbench.';
  for (const [name, root] of [['no types', build({})], ['zero nodes', build({ A: 3 }, 0, 0)]]) {
    check(`empty (${name}): no table, hint or totals button`, byTag(root, 'table').length === 0
      && byClass(root, 'dashboard-hint').length === 0 && byClass(root, 'dashboard-totals-btn').length === 0
      && byTag(root, 'button').length === 0);
    const title = byClass(root, 'dashboard-empty__title')[0];
    const body = byClass(root, 'dashboard-empty__body')[0];
    check(`empty (${name}): heading and body copy`, title && title.textContent === 'No entities yet' && body && body.textContent === BODY,
      [title && title.textContent, body && body.textContent]);
    check(`empty (${name}): keeps the section heading`, byTag(root, 'h3')[0].textContent === 'Entity Summary');
  }
}

process.stdout.write(JSON.stringify({ passed, failed }) + '\n');
process.exit(failed.length ? 1 : 0);
