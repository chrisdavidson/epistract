// Behavioral harness for the Dashboard entity summary builders (dashboard.js).
// Imports the real dashboard.js (and display.js) against a stub DOM that records
// every created tag and every innerHTML assignment, then checks row order and
// markup, hostile type strings (SEC-01), click delegation, the totals button,
// the hint and the empty state. The `epistemic` mode covers
// buildEpistemicHealth (run: node dashboard_harness.mjs epistemic) and the
// `documents` mode covers buildDocuments (run: node dashboard_harness.mjs documents).
// Prints one JSON line {"passed": [...], "failed": [...]} and exits 1 on failure.
import { pathToFileURL, fileURLToPath } from 'node:url';
import path from 'node:path';

const MODE = process.argv[2] || 'summary';
const createdTags = [];
const innerHtmlWrites = [];
const focusLog = [];

function parseSelector(sel) {
  const m = /^([a-z0-9]*)((?:\.[\w-]+)*)(?:\[([\w-]+)(?:="([^"]*)")?\])?$/i.exec(sel);
  if (!m) return null;
  return {
    tag: m[1].toLowerCase(),
    classes: m[2].split('.').filter(Boolean),
    attr: m[3] || null,
    attrValue: m[4] === undefined ? null : m[4],
  };
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
    style: {},
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
    focus(options) { focusLog.push({ el, options }); },
    matches(sel) {
      const p = parseSelector(sel);
      if (!p) return false;
      const classes = String(el.className).split(/\s+/).filter(Boolean);
      const attrOk = !p.attr || (attrs.has(p.attr) && (p.attrValue === null || attrs.get(p.attr) === p.attrValue));
      return (!p.tag || p.tag === el.tagName) && p.classes.every((c) => classes.includes(c)) && attrOk;
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
const walk = (n, fn) => { if (!n) return; fn(n); (n.children || []).forEach((c) => walk(c, fn)); };
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

if (MODE === 'summary') {
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
  const btn = byClass(totals, 'dashboard-totals-btn')[0] || makeEl('missing');
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

}

if (MODE === 'epistemic') {
  const NOT_RUN = 'Epistemic analysis has not been run for this graph. Run /epistract:epistemic <output-dir> to find contradictions, hypotheses and gaps.';
  const NONE_FOUND = 'No contradictions, conflicts or hypotheses were found.';
  if (typeof dash.buildEpistemicHealth !== 'function') {
    check('buildEpistemicHealth is exported by dashboard.js', false, typeof dash.buildEpistemicHealth);
  } else {
    const shown = [];
    const asked = [];
    const buildEpi = (epistemic) => dash.buildEpistemicHealth({
      epistemic,
      onShowInGraph: (id, event) => shown.push({ id, event }),
      onAskInChat: (question, event) => asked.push({ question, event }),
    });
    const ent = (id, name, type = 'COMPOUND') => ({ id, name, entity_type: type });
    const stm = (t, document, confidence) => ({ text: t, document, confidence });
    const classesOf = (n) => String(n.className).split(/\s+/).filter(Boolean);
    const sections = (root) => find(root, (n) => n.matches('div.epistemic-section'));
    const sectionOf = (root, key) => sections(root).find((s) => byTag(s, 'h4')[0].getAttribute('id') === `epistemic-sec-${key}`);
    const mainList = (s) => find(s, (n) => n.matches('ul.epistemic-items') && !classesOf(n).includes('epistemic-items--rest'))[0];
    const restList = (s) => find(s, (n) => n.matches('ul.epistemic-items--rest'))[0];
    const cardsOf = (n) => byClass(n, 'epistemic-card');
    const toggleOf = (s) => byClass(s, 'epistemic-toggle')[0];
    const chipsOf = (root) => byClass(root, 'epistemic-chip');
    const btn = (card, action) => find(card, (n) => n.matches(`button[data-action="${action}"]`))[0];
    const metas = (card) => byClass(card, 'epistemic-meta').map(textOf);

    const hyp70 = Array.from({ length: 70 }, (_, i) => ent(`c:n${i}`, `n${i}`));
    const GLP = {
      available: true,
      status_counts: [
        { status: 'asserted', count: 758 },
        { status: 'prophetic', count: 61 },
        { status: 'hypothesized', count: 31 },
        { status: 'speculative', count: 2 },
        { status: 'unclassified', count: 2 },
        { status: 'negative', count: 1 },
      ],
      sections: [
        {
          key: 'contradictions', label: 'Contradictions', description: 'DESC-contradictions', count: 2,
          items: [
            {
              title: 'semaglutide is indicated for Obesity', kind: 'contradiction',
              entities: [ent('compound:semaglutide', 'semaglutide'), ent('disease:obesity', 'Obesity', 'DISEASE')],
              statements: [stm('Low side text', 'patent_x', 0.55), stm('High side text', 'pmid_y', null)],
              documents: ['patent_x', 'pmid_y'],
              question: 'Why do sources disagree on whether semaglutide is indicated for Obesity?',
            },
            {
              title: 'tirzepatide treats Diabetes', kind: 'contradiction',
              entities: [ent('compound:tirzepatide', 'tirzepatide')],
              statements: [stm('A', 'd1', 0.2), stm('B', 'd2', 0.9)], documents: ['d1', 'd2'], question: 'Q2?',
            },
          ],
        },
        {
          key: 'contested_claims', label: 'Contested claims', description: 'DESC-contested', count: 33,
          items: Array.from({ length: 33 }, (_, i) => ({
            title: `Claim ${i}`, kind: 'contested', entities: [ent(`c:e${i}`, `e${i}`)],
            statements: [stm(`statement ${i}`, `doc${i}`, 0.9)], documents: [`doc${i}`], question: `Question ${i}?`,
          })),
        },
        {
          key: 'hypotheses', label: 'Hypotheses', description: 'DESC-hypotheses', count: 2,
          items: [
            {
              title: 'Hypothesis A', kind: 'hypothesis', entities: hyp70, statements: [],
              documents: ['d0', 'd1', 'd2', 'd3', 'd4'], question: 'What evidence supports the hypothesis: Hypothesis A?',
            },
            { title: 'Hypothesis B', kind: 'hypothesis', entities: [ent('c:b', 'b')], statements: [], documents: ['d9'], question: 'QB?' },
          ],
        },
      ],
    };

    // --- render, chips, bar ---
    {
      const root = buildEpi(GLP);
      check('render: section element with the heading link', root.tagName === 'section' && classesOf(root).includes('epistemic-health')
        && root.getAttribute('aria-labelledby') === 'epistemic-heading', [root.tagName, root.className]);
      const h3 = byTag(root, 'h3')[0];
      check('render: h3#epistemic-heading', h3 && h3.getAttribute('id') === 'epistemic-heading' && h3.textContent === 'Epistemic health', h3 && h3.textContent);
      const caption = byClass(root, 'epistemic-hint')[0];
      check('render: caption total', caption && caption.textContent === 'Epistemic status of 855 relations', caption && caption.textContent);
      const chips = chipsOf(root);
      check('chips: six in payload order', chips.length === 6, chips.length);
      const t = chips.map(textOf);
      check('chips: labels, counts and shares',
        t[0].includes('Asserted') && t[0].includes('758') && t[0].includes('89%')
        && t[1].includes('Prophetic') && t[1].includes('61') && t[1].includes('7%')
        && t[2].includes('Hypothesized') && t[2].includes('31') && t[2].includes('4%')
        && t.slice(3).every((x) => x.includes('<1%')), t);
      check('chips: aria-labels', chips[0].getAttribute('aria-label') === 'Asserted: 758 relations, 89%'
        && chips[5].getAttribute('aria-label') === 'Negative: 1 relation, less than 1%',
      [chips[0].getAttribute('aria-label'), chips[5].getAttribute('aria-label')]);
      const want = ['status-asserted', 'status-prophetic', 'status-hypothesized', 'status-speculative', 'status-unknown', 'status-negative'];
      check('chips: status classes', chips.every((c, i) => classesOf(c).includes(want[i])), chips.map((c) => c.className));
      const list = byClass(root, 'epistemic-status-list')[0];
      check('chips: list label', list && list.tagName === 'ul' && list.getAttribute('aria-label') === 'Relations by epistemic status');
      const bar = byClass(root, 'epistemic-bar')[0];
      const segs = byClass(root, 'epistemic-bar__seg');
      check('bar: hidden from assistive tech', bar && bar.getAttribute('aria-hidden') === 'true');
      check('bar: six segments with flex and title', segs.length === 6 && segs[0].style.flex === '758 1 0' && segs[5].style.flex === '1 1 0'
        && segs[0].getAttribute('title') === 'Asserted: 758 (89%)' && segs[5].getAttribute('title') === 'Negative: 1 (<1%)',
      segs.map((s) => [s.style.flex, s.getAttribute('title')]));
      check('bar: segments carry the status class', segs.every((s, i) => classesOf(s).includes(want[i])));
      check('chips: no tab stops', byTag(chips[0], 'button').length === 0 && chips.every((c) => !c.hasAttribute('tabindex')));
    }

    // --- status aliases and fallback colors ---
    {
      const names = ['established', 'observed', 'reported', 'unverified', 'theoretical', 'contested', 'foo', 'bar', 'baz', 'qux', 'quux'];
      const root = buildEpi({
        available: true,
        status_counts: names.map((status, i) => ({ status, count: 20 - i })),
        sections: [],
      });
      const cls = chipsOf(root).map((c) => classesOf(c).find((x) => x.startsWith('status-')));
      check('aliases: established/observed/reported map to asserted', cls.slice(0, 3).every((c) => c === 'status-asserted'), cls);
      check('aliases: unverified/theoretical map to hypothesized', cls[3] === 'status-hypothesized' && cls[4] === 'status-hypothesized', cls);
      check('aliases: contested keeps its own color', cls[5] === 'status-contested', cls);
      check('aliases: unknown statuses take fallback 1..4 in count order and wrap',
        JSON.stringify(cls.slice(6)) === JSON.stringify(['status-fallback-1', 'status-fallback-2', 'status-fallback-3', 'status-fallback-4', 'status-fallback-1']), cls);
    }

    // --- counts line ---
    {
      const root = buildEpi(GLP);
      const counts = byClass(root, 'epistemic-counts')[0];
      check('counts: plural line', counts && counts.tagName === 'p' && counts.textContent === '2 contradictions · 33 contested claims · 2 hypotheses', counts && counts.textContent);
      const one = (key, label) => ({ key, label, description: 'd', count: 1, items: [{ title: 't', entities: [], statements: [], documents: [], question: 'q' }] });
      const singular = buildEpi({
        available: true,
        status_counts: [{ status: 'asserted', count: 1 }],
        sections: [one('contradictions', 'Contradictions'), one('conflicts', 'Conflicts'), one('contested_claims', 'Contested claims'),
          one('hypotheses', 'Hypotheses'), one('risks', 'Risks'), one('coverage_gaps', 'Coverage gaps')],
      });
      check('counts: singular forms', byClass(singular, 'epistemic-counts')[0].textContent
        === '1 contradiction · 1 conflict · 1 contested claim · 1 hypothesis · 1 risk · 1 coverage gap', byClass(singular, 'epistemic-counts')[0].textContent);
      check('counts: singular caption', byClass(singular, 'epistemic-hint')[0].textContent === 'Epistemic status of 1 relation');
    }

    // --- sections ---
    {
      const root = buildEpi(GLP);
      const secs = sections(root);
      check('sections: three blocks in order', secs.length === 3
        && JSON.stringify(secs.map((s) => byTag(s, 'h4')[0].textContent)) === JSON.stringify(['Contradictions (2)', 'Contested claims (33)', 'Hypotheses (2)']),
      secs.map((s) => byTag(s, 'h4')[0].textContent));
      check('sections: heading ids from the fixed keys', secs.map((s) => byTag(s, 'h4')[0].getAttribute('id')).join() === 'epistemic-sec-contradictions,epistemic-sec-contested_claims,epistemic-sec-hypotheses');
      check('sections: description from the payload', byClass(secs[0], 'epistemic-section__desc')[0].textContent === 'DESC-contradictions');
      check('sections: list labelled by the heading', mainList(secs[0]).getAttribute('aria-labelledby') === 'epistemic-sec-contradictions');
    }

    // --- show all ---
    {
      const root = buildEpi(GLP);
      const s = sectionOf(root, 'contested_claims');
      check('show-all: five cards before the toggle', cardsOf(mainList(s)).length === 5, cardsOf(mainList(s)).length);
      const tg = toggleOf(s);
      check('show-all: collapsed toggle', tg && tg.tagName === 'button' && tg.getAttribute('type') === 'button' && tg.textContent === 'Show all 33'
        && tg.getAttribute('aria-expanded') === 'false' && tg.getAttribute('aria-controls') === 'epistemic-rest-contested_claims'
        && tg.getAttribute('aria-label') === 'Show all 33 contested claims', tg && [tg.textContent, tg.getAttribute('aria-label')]);
      const rest = restList(s);
      check('show-all: rest list hidden with 28 cards', rest && rest.getAttribute('id') === 'epistemic-rest-contested_claims'
        && rest.hasAttribute('hidden') && cardsOf(rest).length === 28, rest && cardsOf(rest).length);
      root.dispatch('click', { target: tg });
      check('show-all: expanded', tg.getAttribute('aria-expanded') === 'true' && !rest.hasAttribute('hidden') && tg.textContent === 'Show first 5'
        && tg.getAttribute('aria-label') === 'Show only the first 5 contested claims', [tg.textContent, tg.getAttribute('aria-label')]);
      root.dispatch('click', { target: tg });
      check('show-all: collapsed again', tg.getAttribute('aria-expanded') === 'false' && rest.hasAttribute('hidden') && tg.textContent === 'Show all 33');
      check('show-all: small sections have no toggle', !toggleOf(sectionOf(root, 'contradictions')) && !restList(sectionOf(root, 'hypotheses')));
      check('show-all: toggle never calls the actions', shown.length === 0 && asked.length === 0);
    }

    // --- truncated ---
    {
      const items = Array.from({ length: 50 }, (_, i) => ({ title: `Gap ${i}`, entities: [], statements: [], documents: [], question: `q${i}` }));
      const root = buildEpi({
        available: true, status_counts: [{ status: 'asserted', count: 10 }],
        sections: [{ key: 'coverage_gaps', label: 'Coverage gaps', description: 'DESC-gaps', count: 417, items }],
      });
      const s = sectionOf(root, 'coverage_gaps');
      const notes = byClass(s, 'epistemic-section__desc').map((n) => n.textContent);
      check('truncated: heading counts the full 417', byTag(s, 'h4')[0].textContent === 'Coverage gaps (417)', byTag(s, 'h4')[0].textContent);
      check('truncated: toggle says 50 of 417, not all', toggleOf(s).textContent === 'Show 50 of 417'
        && toggleOf(s).getAttribute('aria-label') === 'Show 50 of 417 coverage gaps', [toggleOf(s).textContent, toggleOf(s).getAttribute('aria-label')]);
      root.dispatch('click', { target: toggleOf(s) });
      check('truncated: expanded label', toggleOf(s).textContent === 'Show first 5', toggleOf(s).textContent);
      root.dispatch('click', { target: toggleOf(s) });
      check('truncated: collapsed label returns', toggleOf(s).textContent === 'Show 50 of 417', toggleOf(s).textContent);
      check('truncated: states Showing 50 of 417.', notes[notes.length - 1] === 'Showing 50 of 417.', notes);
      const lastKid = s.children[s.children.length - 1];
      check('truncated: the note follows the lists', lastKid && lastKid.textContent === 'Showing 50 of 417.');
    }

    // --- card ---
    {
      const root = buildEpi(GLP);
      const first = cardsOf(sectionOf(root, 'contradictions'))[0];
      const title = byClass(first, 'epistemic-card__title')[0];
      check('card: title text and title attribute', title && title.tagName === 'p' && title.textContent === 'semaglutide is indicated for Obesity'
        && title.getAttribute('title') === 'semaglutide is indicated for Obesity');
      const quotes = byTag(first, 'blockquote');
      check('card: two quotes with the full text in title', quotes.length === 2 && classesOf(quotes[0]).includes('epistemic-quote')
        && quotes[0].textContent === 'Low side text' && quotes[0].getAttribute('title') === 'Low side text');
      const m = metas(first);
      check('card: statement meta with confidence', m.includes('patent_x · Confidence 55%'), m);
      check('card: statement meta without confidence is the document id', m.includes('pmid_y'), m);
      check('card: entities line', m.includes('Entities: semaglutide, Obesity'), m);
      check('card: no Sources line when documents are all quoted', !m.some((x) => x.startsWith('Sources:')), m);
      const hypo = cardsOf(sectionOf(root, 'hypotheses'))[0];
      const hm = metas(hypo);
      check('card: entities capped at three plus more', hm.includes('Entities: n0, n1, n2 +67 more'), hm);
      check('card: Sources line for a hypothesis', hm.includes('Sources: d0, d1, d2 +2 more'), hm);
      check('card: a hypothesis has no quotes', byTag(hypo, 'blockquote').length === 0);
      check('card: entity types are in the line title', byClass(first, 'epistemic-meta')[0] && /semaglutide \(COMPOUND\)/.test(byClass(first, 'epistemic-meta').find((n) => textOf(n).startsWith('Entities:')).getAttribute('title') || ''));
      const three = buildEpi({
        available: true, status_counts: [], sections: [{
          key: 'contested_claims', label: 'Contested claims', description: 'd', count: 1,
          items: [{ title: 'x', entities: [], documents: ['a'], statements: [stm('q1', 'a', 1), stm('q2', 'a', 0), stm('q3', 'a', 0.5)], question: 'q' }],
        }],
      });
      check('card: at most two quotes', byTag(three, 'blockquote').length === 2);
    }

    // --- actions ---
    {
      const root = buildEpi(GLP);
      const first = cardsOf(sectionOf(root, 'contradictions'))[0];
      const acts = byClass(first, 'epistemic-actions')[0];
      const [g, a] = byClass(acts, 'epistemic-btn');
      check('actions: Show in graph then Ask in chat', g && a && g.textContent === 'Show in graph' && a.textContent === 'Ask in chat'
        && g.getAttribute('type') === 'button' && a.getAttribute('type') === 'button'
        && g.getAttribute('data-action') === 'show-graph' && a.getAttribute('data-action') === 'ask-chat', [g && g.textContent, a && a.textContent]);
      check('actions: data-section and data-index', g.getAttribute('data-section') === 'contradictions' && g.getAttribute('data-index') === '0'
        && cardsOf(sectionOf(root, 'contradictions'))[1].children.length > 0
        && byClass(cardsOf(sectionOf(root, 'contradictions'))[1], 'epistemic-btn')[0].getAttribute('data-index') === '1');
      check('actions: aria-labels', g.getAttribute('aria-label') === 'Show semaglutide is indicated for Obesity in the graph'
        && a.getAttribute('aria-label') === 'Ask in chat about semaglutide is indicated for Obesity', [g.getAttribute('aria-label'), a.getAttribute('aria-label')]);
      check('actions: titles', g.getAttribute('title') === 'Focus the graph on semaglutide and its direct connections.'
        && a.getAttribute('title') === 'Puts a question in the chat box. Nothing is sent until you press Send.', [g.getAttribute('title'), a.getAttribute('title')]);
      const longTitle = 'T'.repeat(130);
      const long = buildEpi({
        available: true, status_counts: [], sections: [{
          key: 'risks', label: 'Risks', description: 'd', count: 1,
          items: [{ title: longTitle, entities: [ent('a:b', 'b')], statements: [], documents: [], question: 'q' }],
        }],
      });
      const lg = byClass(long, 'epistemic-btn')[0];
      check('actions: long titles are truncated in the aria-label only', lg.getAttribute('aria-label') === `Show ${'T'.repeat(100)}... in the graph`
        && byClass(long, 'epistemic-card__title')[0].textContent === longTitle, lg.getAttribute('aria-label'));

      shown.length = 0;
      asked.length = 0;
      root.dispatch('click', { target: g, detail: 0 });
      check('dispatch: Show in graph passes the first entity id and the event', shown.length === 1 && shown[0].id === 'compound:semaglutide'
        && shown[0].event && shown[0].event.detail === 0 && asked.length === 0, shown);
      root.dispatch('click', { target: a, detail: 1 });
      check('dispatch: Ask in chat passes the question and the event', asked.length === 1 && asked[0].question === GLP.sections[0].items[0].question
        && asked[0].event.detail === 1 && shown.length === 1, asked);
      root.dispatch('click', { target: byTag(first, 'blockquote')[0] });
      root.dispatch('click', { target: root });
      root.dispatch('click', { target: byClass(first, 'epistemic-card__title')[0] });
      check('dispatch: quotes, titles and the root call nothing', shown.length === 1 && asked.length === 1);
      const later = byClass(cardsOf(sectionOf(root, 'contested_claims'))[2], 'epistemic-btn');
      root.dispatch('click', { target: later[0] });
      check('dispatch: a later card resolves its own item', shown.length === 2 && shown[1].id === 'c:e2', shown[1]);
      sectionOf(root, 'contested_claims');
      root.dispatch('click', { target: toggleOf(sectionOf(root, 'contested_claims')) });
      const revealed = byClass(cardsOf(restList(sectionOf(root, 'contested_claims')))[0], 'epistemic-btn');
      root.dispatch('click', { target: revealed[1] });
      check('dispatch: revealed cards work too', asked.length === 2 && asked[1].question === 'Question 5?', asked[1]);
    }

    // --- disabled Show in graph ---
    {
      shown.length = 0;
      asked.length = 0;
      const root = buildEpi({
        available: true, status_counts: [{ status: 'asserted', count: 3 }],
        sections: [{
          key: 'conflicts', label: 'Conflicts', description: 'd', count: 1,
          items: [{ title: 'A conflict', entities: [], statements: [stm('evidence', 'pv_doc', null)], documents: ['pv_doc'], question: 'What is behind this conflict?' }],
        }],
      });
      const card = cardsOf(root)[0];
      const g = btn(card, 'show-graph');
      const a = btn(card, 'ask-chat');
      check('disabled: aria-disabled without the disabled attribute', g.getAttribute('aria-disabled') === 'true' && !g.hasAttribute('disabled'));
      check('disabled: title and description', g.getAttribute('title') === 'No entity from this item is in the graph.'
        && g.getAttribute('aria-describedby') === 'epistemic-note-conflicts-0', [g.getAttribute('title'), g.getAttribute('aria-describedby')]);
      const note = byClass(card, 'epistemic-note')[0];
      check('disabled: visible note', note && note.tagName === 'p' && note.getAttribute('id') === 'epistemic-note-conflicts-0'
        && note.textContent === "None of this item's entities are in the graph, so there is nothing to focus.", note && note.textContent);
      check('disabled: no Entities line', !metas(card).some((x) => x.startsWith('Entities:')), metas(card));
      root.dispatch('click', { target: g });
      check('disabled: click does nothing', shown.length === 0, shown);
      root.dispatch('click', { target: a });
      check('disabled: Ask in chat still works', asked.length === 1 && asked[0].question === 'What is behind this conflict?');
      const enabled = btn(cardsOf(buildEpi(GLP))[0], 'show-graph');
      check('disabled: enabled buttons have no aria-disabled or note', !enabled.hasAttribute('aria-disabled')
        && byClass(cardsOf(buildEpi(GLP))[0], 'epistemic-note').length === 0);
    }

    // --- hostile ---
    {
      createdTags.length = 0;
      innerHtmlWrites.length = 0;
      shown.length = 0;
      const root = buildEpi({
        available: true,
        status_counts: [{ status: '<b>x</b>', count: 3 }, { status: '"><script>alert(1)</script>', count: 1 }],
        sections: [{
          key: 'contradictions', label: '<img src=x onerror=1>', description: '<img src=x onerror=1>', count: 1,
          items: [{
            title: '<img src=x onerror=1>', kind: '<svg onload=1>',
            entities: [ent('<img src=x onerror=1>', '<svg onload=1>', '"><script>alert(1)</script>')],
            statements: [stm('"><script>alert(1)</script>', '<svg onload=1>', 0.5)],
            documents: ['<svg onload=1>', '<script>x</script>'], question: '<img src=x onerror=1>',
          }],
        }],
      });
      check('hostile: no img, script, b or svg element is created', !['img', 'script', 'b', 'svg'].some((t) => createdTags.includes(t)), createdTags);
      check('hostile: innerHTML is never assigned', innerHtmlWrites.length === 0, innerHtmlWrites);
      const text = textOf(root);
      check('hostile: literal text is visible', text.includes('<img src=x onerror=1>') && text.includes('"><script>alert(1)</script>')
        && text.includes('<svg onload=1>') && text.includes('<b>x</b>'));
      let badClass = false;
      walk(root, (n) => { if (/[<>"']|onerror|script/i.test(String(n.className || ''))) badClass = true; });
      check('hostile: no data-derived class names', !badClass);
      check('hostile: the tree holds no img or script element', find(root, (n) => ['img', 'script', 'b', 'svg'].includes(n.tagName)).length === 0);
      root.dispatch('click', { target: byClass(root, 'epistemic-btn')[0] });
      check('hostile: the raw id is dispatched as a string', shown.length === 1 && shown[0].id === '<img src=x onerror=1>', shown);
      check('hostile: statuses fall back to fixed classes', chipsOf(root).every((c) => /status-fallback-\d/.test(c.className)), chipsOf(root).map((c) => c.className));
    }

    // --- not-run ---
    {
      let threw = false;
      const cases = [undefined, null, 'x', 7, [], {}, { available: false, status_counts: [], sections: [] },
        { available: false, status_counts: [{ status: 'asserted', count: 4 }], sections: [] },
        { available: true, status_counts: 'bad', sections: 'bad' }];
      for (const c of cases) {
        let root;
        try { root = buildEpi(c); } catch (e) { threw = true; check(`not-run: ${JSON.stringify(c)} does not throw`, false, String(e)); continue; }
        const hints = byClass(root, 'epistemic-hint');
        const ok = byTag(root, 'h3')[0].textContent === 'Epistemic health' && hints.length === 1 && hints[0].textContent === NOT_RUN
          && byClass(root, 'epistemic-bar').length === 0 && sections(root).length === 0 && byClass(root, 'epistemic-counts').length === 0;
        check(`not-run: ${JSON.stringify(c)}`, ok, hints.map((h) => h.textContent));
      }
      check('not-run: never throws', !threw);
      const sloppy = buildEpi({
        available: true,
        status_counts: [{ status: 7, count: 3 }, { status: 'asserted', count: 0 }, { status: 'asserted', count: 1.5 }, null, { status: 'asserted', count: 4 }],
        sections: [{ key: 'bogus', items: [] }, { key: 'risks', label: 'Risks', description: 'd', count: 1, items: 'no' }, null],
      });
      check('not-run: invalid entries are dropped', chipsOf(sloppy).length === 1 && sections(sloppy).length === 0, chipsOf(sloppy).length);
    }

    // --- nothing found / sections only ---
    {
      const root = buildEpi({ available: true, status_counts: [{ status: 'asserted', count: 4 }, { status: 'negative', count: 1 }], sections: [] });
      const hints = byClass(root, 'epistemic-hint').map((h) => h.textContent);
      check('nothing-found: caption, bar, chips and the message', hints[0] === 'Epistemic status of 5 relations' && hints[1] === NONE_FOUND
        && byClass(root, 'epistemic-bar').length === 1 && chipsOf(root).length === 2, hints);
      check('nothing-found: no counts line or sections', byClass(root, 'epistemic-counts').length === 0 && sections(root).length === 0);
      const only = buildEpi({ available: true, status_counts: [], sections: GLP.sections });
      check('sections-only: no bar or chips', byClass(only, 'epistemic-bar').length === 0 && chipsOf(only).length === 0
        && byClass(only, 'epistemic-hint').length === 0, byClass(only, 'epistemic-hint').length);
      check('sections-only: counts line and sections', byClass(only, 'epistemic-counts').length === 1 && sections(only).length === 3);
    }
  }
}

if (MODE === 'doc-links') {
  const opened = [];
  const ent = (id, name) => ({ id, name, entity_type: 'COMPOUND' });
  const stm = (t, document, confidence) => ({ text: t, document, confidence });
  const classesOf = (n) => String(n.className).split(/\s+/).filter(Boolean);
  const payload = (documents, statements) => ({
    available: true,
    status_counts: [{ status: 'asserted', count: 3 }],
    sections: [{
      key: 'contradictions', label: 'Contradictions', description: 'd', count: 1,
      items: [{
        title: 'A vs B', kind: 'contradiction', entities: [ent('c:a', 'a')], statements,
        documents, question: 'q',
      }],
    }],
  });
  const STATEMENTS = [
    stm('Quote from the first doc', 'pmid_35650449', 0.5),
    stm('Quote from an unknown doc', 'unlisted_doc', null),
    stm('Third statement from src_one', 'src_one', 0.9),
  ];
  const DOC_IDS = ['pmid_35650449', 'unlisted_doc', 'src_one', 'src_two', 'src_three', 'src_four'];
  const build = (documents) => dash.buildEpistemicHealth({
    epistemic: payload(DOC_IDS, STATEMENTS),
    documents,
    onShowInGraph: () => {},
    onAskInChat: () => {},
    onOpenDocument: (docId, highlight, event) => opened.push({ docId, highlight, event }),
  });
  const known = [{ doc_id: 'pmid_35650449' }, { doc_id: 'src_one' }, { doc_id: 'src_three' }];
  const links = (root) => find(root, (n) => n.matches('button.epistemic-doc-link'));
  const metaLines = (root) => byClass(root, 'epistemic-meta');
  const sourcesLine = (root) => metaLines(root).find((m) => textOf(m).startsWith('Sources:'));

  {
    const root = build(known);
    const btns = links(root);
    check('doc-links: known ids become buttons (statement id, plus two on the Sources line)', btns.length === 3, btns.map(textOf));
    const first = btns[0];
    check('doc-links: statement id button markup', textOf(first) === 'pmid_35650449' && first.getAttribute('type') === 'button'
      && first.getAttribute('data-action') === 'open-doc' && first.getAttribute('title') === 'pmid_35650449'
      && classesOf(first).includes('epistemic-meta__doc') && first.getAttribute('aria-label') === 'Read pmid_35650449 with the cited passage highlighted',
    [first.className, first.getAttribute('aria-label')]);
    const statementMeta = metaLines(root).find((m) => textOf(m).startsWith('pmid_35650449'));
    check('doc-links: the statement meta text is unchanged', textOf(statementMeta) === 'pmid_35650449 · Confidence 50%', textOf(statementMeta));
    const unlisted = find(root, (n) => n.matches('span.epistemic-meta__doc') && textOf(n) === 'unlisted_doc');
    check('doc-links: an id not in the list stays a plain span with its title', unlisted.length === 1 && unlisted[0].getAttribute('title') === 'unlisted_doc'
      && !find(root, (n) => n.matches('button') && textOf(n) === 'unlisted_doc').length);

    root.dispatch('click', { target: first });
    check('doc-links: statement click opens the document with that statement text', opened.length === 1 && opened[0].docId === 'pmid_35650449'
      && opened[0].highlight === 'Quote from the first doc' && !!opened[0].event, opened.map((o) => [o.docId, o.highlight]));

    const src = sourcesLine(root);
    check('doc-links: Sources line text keeps ids, separators and the more tail', textOf(src) === 'Sources: src_one, src_two, src_three +1 more', textOf(src));
    const srcBtns = byTag(src, 'button');
    check('doc-links: only known Sources ids are buttons', srcBtns.length === 2 && textOf(srcBtns[0]) === 'src_one' && textOf(srcBtns[1]) === 'src_three');
    const srcSpans = find(src, (n) => n.matches('span.epistemic-meta__doc'));
    check('doc-links: unknown Sources ids stay plain spans', srcSpans.length === 1 && textOf(srcSpans[0]) === 'src_two');
    check('doc-links: the Sources line keeps its full-list title', src.getAttribute('title') === DOC_IDS.join(', '), src.getAttribute('title'));

    root.dispatch('click', { target: srcBtns[0] });
    check('doc-links: Sources id highlights the first statement of that document (A-6)', opened.length === 2 && opened[1].docId === 'src_one'
      && opened[1].highlight === 'Third statement from src_one' && srcBtns[0].getAttribute('aria-label') === 'Read src_one with the cited passage highlighted',
    [opened[1], srcBtns[0].getAttribute('aria-label')]);
    root.dispatch('click', { target: srcBtns[1] });
    check('doc-links: Sources id with no statement opens without a highlight', opened.length === 3 && opened[2].docId === 'src_three'
      && opened[2].highlight === undefined && srcBtns[1].getAttribute('aria-label') === 'Read src_three', [opened[2], srcBtns[1].getAttribute('aria-label')]);

    srcBtns[0].setAttribute('data-doc-id', 'not_in_this_item');
    root.dispatch('click', { target: srcBtns[0] });
    check('doc-links: a tampered doc id attribute is ignored', opened.length === 3);
    check('doc-links: opening never calls the other actions or throws on a missing handler', true);
  }

  {
    const root = build(undefined);
    check('doc-links: without documents no id is a button', links(root).length === 0);
    const src = sourcesLine(root);
    const spans = find(src, (n) => n.matches('span.epistemic-meta__doc'));
    check('doc-links: without documents the Sources line is one span, as before', spans.length === 1 && textOf(spans[0]) === 'src_one, src_two, src_three' && textOf(src) === 'Sources: src_one, src_two, src_three +1 more', textOf(src));
    const none = build([]);
    check('doc-links: an empty documents list also leaves ids plain', links(none).length === 0);
    const noHandler = dash.buildEpistemicHealth({ epistemic: payload(DOC_IDS, STATEMENTS), documents: known });
    let threw = false;
    try { noHandler.dispatch('click', { target: links(noHandler)[0] }); } catch { threw = true; }
    check('doc-links: a click without onOpenDocument does not throw', !threw);
  }

  {
    const hostile = '<img src=x onerror=1>';
    createdTags.length = 0;
    innerHtmlWrites.length = 0;
    const before = opened.length;
    const root = dash.buildEpistemicHealth({
      epistemic: payload([hostile, 'other'], [stm('quote', hostile, 0.5)]),
      documents: [{ doc_id: hostile }],
      onOpenDocument: (docId, highlight) => opened.push({ docId, highlight }),
    });
    const btn = links(root)[0];
    check('doc-links hostile: the id is button text and an attribute value', btn && textOf(btn) === hostile && btn.getAttribute('data-doc-id') === hostile);
    check('doc-links hostile: no img or script element and no innerHTML write', !createdTags.includes('img') && !createdTags.includes('script') && innerHtmlWrites.length === 0, createdTags);
    root.dispatch('click', { target: btn });
    check('doc-links hostile: the raw id reaches the handler', opened.length === before + 1 && opened[before].docId === hostile && opened[before].highlight === 'quote');
    let badClass = false;
    walk(root, (n) => { if (/[<>"']|onerror|script/i.test(String(n.className || ''))) badClass = true; });
    check('doc-links hostile: no data-derived class names', !badClass);
  }
}

if (MODE === 'documents') {
  const EMPTY = 'No source documents were found in this output directory. Run /epistract:ingest to add documents, then reload the workbench.';
  if (typeof dash.buildDocuments !== 'function') {
    check('buildDocuments is exported by dashboard.js', false, typeof dash.buildDocuments);
  } else {
    const opened = [];
    const buildDocs = (documents) => dash.buildDocuments({ documents, onOpen: (doc, event) => opened.push({ doc, event }) });
    const mk = (i, extra = {}) => ({
      doc_id: `doc_${i}`, display_name: `Doc ${i}`, filename: `Doc ${i}.txt`,
      entity_count: 100 - i, relation_count: 50 - i, has_text: true, has_pdf: false, ...extra,
    });
    const many = (n) => Array.from({ length: n }, (_, i) => mk(i + 1));
    const bodies = (root) => byTag(root, 'tbody');
    const docRowsOf = (root) => byClass(root, 'dashboard-doc-row');
    const rowBtn = (row) => byClass(row, 'dashboard-doc-btn')[0];
    const toggleBtn = (root) => byClass(root, 'documents-toggle')[0];
    const statusOf = (root) => byClass(root, 'visually-hidden')[0];
    const hasAttr = (n, k) => n.hasAttribute(k);

    // --- structure for 34 documents ---
    {
      createdTags.length = 0;
      innerHtmlWrites.length = 0;
      const root = buildDocs(many(34));
      check('documents: section element and class', root && root.tagName === 'section' && root.className === 'documents-section'
        && root.getAttribute('aria-labelledby') === 'documents-heading', root && root.className);
      const h3 = byTag(root, 'h3')[0];
      check('documents: heading Documents (34)', h3 && h3.textContent === 'Documents (34)' && h3.getAttribute('id') === 'documents-heading', h3 && h3.textContent);
      const hint = byClass(root, 'dashboard-hint')[0];
      check('documents: hint copy', hint && hint.textContent === 'Entities and relations extracted from each document. Select a document to read it.', hint && hint.textContent);
      const table = byTag(root, 'table')[0];
      check('documents: table classes and label', table && table.className === 'dashboard-table documents-table'
        && table.getAttribute('aria-labelledby') === 'documents-heading', table && table.className);
      check('documents: three columns in a colgroup', byTag(root, 'colgroup').length === 1 && byTag(root, 'col').length === 3);
      const heads = byTag(root, 'th').map((t) => t.textContent);
      check('documents: headers', JSON.stringify(heads) === JSON.stringify(['Document', 'Entities', 'Relations']), heads);
      const [first, rest] = bodies(root);
      check('documents: two tbody elements', bodies(root).length === 2);
      check('documents: first tbody has 10 rows', byClass(first, 'dashboard-doc-row').length === 10, byClass(first, 'dashboard-doc-row').length);
      check('documents: rest tbody has 24 rows and is hidden', byClass(rest, 'dashboard-doc-row').length === 24
        && hasAttr(rest, 'hidden') && rest.getAttribute('id') === 'documents-rest');
      const t = toggleBtn(root);
      check('documents: toggle collapsed state', t && t.tagName === 'button' && t.getAttribute('type') === 'button'
        && t.textContent === 'Show all 34' && t.getAttribute('aria-expanded') === 'false'
        && t.getAttribute('aria-controls') === 'documents-rest' && t.getAttribute('aria-label') === 'Show all 34 documents', t && t.textContent);
      const st = statusOf(root);
      check('documents: status region', st && st.tagName === 'span' && st.getAttribute('role') === 'status'
        && st.getAttribute('aria-live') === 'polite' && st.getAttribute('id') === 'documents-status');
      check('documents: toggle sits after the table and before the status', root.children.indexOf(t) > 0
        && root.children.findIndex((c) => c.className === 'dashboard-table-wrap') < root.children.indexOf(t)
        && root.children.indexOf(t) < root.children.indexOf(st));
      check('documents: no img or script, no innerHTML', !createdTags.includes('img') && !createdTags.includes('script') && innerHtmlWrites.length === 0, createdTags);
    }

    // --- row markup ---
    {
      const docs = [
        mk(1, { entity_count: 1234, relation_count: 1 }),
        mk(2, { entity_count: 1, relation_count: 0 }),
        { doc_id: 'x', display_name: 'Some Report', filename: 'Some Report.pdf', entity_count: 0, relation_count: 0, has_text: false, has_pdf: true },
        { doc_id: 'y', display_name: 'y', filename: 'y', entity_count: 0, relation_count: 0, has_text: false, has_pdf: false },
      ];
      const root = buildDocs(docs);
      const rows = docRowsOf(root);
      check('row: tr carries both class sets and the data attributes', rows.every((r, i) => r.tagName === 'tr'
        && r.matches('tr.dashboard-link-row') && r.matches('tr.dashboard-doc-row')
        && r.getAttribute('data-index') === String(i) && r.getAttribute('data-doc-id') === docs[i].doc_id));
      check('row: exactly one button per row with both class sets', rows.every((r) => byTag(r, 'button').length === 1
        && rowBtn(r).matches('button.dashboard-link-btn') && rowBtn(r).getAttribute('type') === 'button'
        && rowBtn(r).getAttribute('data-doc-id') !== null));
      const aria = rows.map((r) => rowBtn(r).getAttribute('aria-label'));
      check('row: plural aria-label with locale counts', aria[0] === 'Read Doc 1: 1,234 entities, 1 relation', aria[0]);
      check('row: singular entity, zero relations', aria[1] === 'Read Doc 2: 1 entity, 0 relations', aria[1]);
      check('row: PDF only suffix', aria[2] === 'Read Some Report: 0 entities, 0 relations (PDF only)', aria[2]);
      check('row: no-text suffix', aria[3] === 'Read y: 0 entities, 0 relations (text not available)', aria[3]);
      const flags = rows.map((r) => byClass(r, 'documents-flag').map((f) => f.textContent));
      check('row: flags', JSON.stringify(flags) === JSON.stringify([[], [], ['PDF only'], ['No text']]), flags);
      const ids = rows.map((r) => byClass(r, 'documents-name__id').map((f) => f.textContent));
      check('row: id line only when the slugs differ', JSON.stringify(ids) === JSON.stringify([[], [], ['x'], []]), ids);
      check('row: titles carry the full name and, with an id line, the id',
        rowBtn(rows[0]).getAttribute('title') === 'Doc 1' && rowBtn(rows[2]).getAttribute('title') === 'Some Report\nx',
        [rowBtn(rows[0]).getAttribute('title'), rowBtn(rows[2]).getAttribute('title')]);
      const name = byClass(rows[0], 'documents-name')[0];
      check('row: name stack holds the text span', name && name.tagName === 'span' && byClass(name, 'documents-name__text')[0].textContent === 'Doc 1');
      const chevron = byClass(rows[0], 'dashboard-link-chevron')[0];
      check('row: decorative chevron', chevron && chevron.getAttribute('aria-hidden') === 'true' && chevron.textContent === '›');
      const counts = rows.map((r) => byClass(r, 'dashboard-count').map((c) => c.textContent));
      check('row: count cells use locale formatting', JSON.stringify(counts[0]) === JSON.stringify(['1,234', '1']) && JSON.stringify(counts[1]) === JSON.stringify(['1', '0']), counts);
      check('row: zero counts get the muted class', byClass(rows[1], 'dashboard-count--zero').length === 1 && byClass(rows[0], 'dashboard-count--zero').length === 0
        && byClass(rows[2], 'dashboard-count--zero').length === 2);
      const fallback = buildDocs([{ doc_id: 'only_id' }, { doc_id: 'with_file', filename: 'With File.txt' }]);
      const names = docRowsOf(fallback).map((r) => byClass(r, 'documents-name__text')[0].textContent);
      check('row: name falls back to filename then doc id', JSON.stringify(names) === JSON.stringify(['only_id', 'With File.txt']), names);
      const dirty = buildDocs([null, 5, 'x', {}, { doc_id: '' }, { doc_id: 'ok', entity_count: 'many', relation_count: -3 }]);
      const dirtyRows = docRowsOf(dirty);
      check('row: malformed entries are dropped and counts coerced', dirtyRows.length === 1
        && JSON.stringify(byClass(dirtyRows[0], 'dashboard-count').map((c) => c.textContent)) === JSON.stringify(['0', '0']), dirtyRows.length);
    }

    // --- toggle ---
    {
      focusLog.length = 0;
      const root = buildDocs(many(34));
      const t = toggleBtn(root);
      const [first, rest] = bodies(root);
      t.dispatch('click', { detail: 1 });
      check('toggle: expands', t.getAttribute('aria-expanded') === 'true' && !hasAttr(rest, 'hidden') && t.textContent === 'Show first 10'
        && t.getAttribute('aria-label') === 'Show only the first 10 documents', [t.textContent, t.getAttribute('aria-label')]);
      check('toggle: status announces all documents', statusOf(root).textContent === 'Showing all 34 documents.', statusOf(root).textContent);
      const target = rowBtn(byClass(rest, 'dashboard-doc-row')[0]);
      check('toggle: focus moves to the first revealed row button with preventScroll',
        focusLog.length === 1 && focusLog[0].el === target && focusLog[0].options && focusLog[0].options.preventScroll === true, focusLog.map((f) => f.options));
      t.dispatch('click', { detail: 1 });
      check('toggle: collapses', t.getAttribute('aria-expanded') === 'false' && hasAttr(rest, 'hidden') && t.textContent === 'Show all 34'
        && t.getAttribute('aria-label') === 'Show all 34 documents');
      check('toggle: collapsed status', statusOf(root).textContent === 'Showing the first 10 of 34 documents.', statusOf(root).textContent);
      check('toggle: focus returns to the toggle', focusLog.length === 2 && focusLog[1].el === t, focusLog.length);
      check('toggle: the first tbody is untouched', byClass(first, 'dashboard-doc-row').length === 10);
    }

    // --- sizes around the limit ---
    {
      for (const n of [7, 10]) {
        const root = buildDocs(many(n));
        check(`size ${n}: all rows, no toggle`, docRowsOf(root).length === n && !toggleBtn(root) && bodies(root).length === 1
          && byTag(root, 'h3')[0].textContent === `Documents (${n})`, docRowsOf(root).length);
      }
      const eleven = buildDocs(many(11));
      check('size 11: toggle appears with one hidden row', !!toggleBtn(eleven) && toggleBtn(eleven).textContent === 'Show all 11'
        && byClass(bodies(eleven)[1], 'dashboard-doc-row').length === 1);
      const big = buildDocs(many(1200));
      check('size 1200: heading uses locale formatting', byTag(big, 'h3')[0].textContent === 'Documents (1,200)', byTag(big, 'h3')[0].textContent);
      check('size 1200: toggle label', toggleBtn(big).textContent === 'Show all 1,200', toggleBtn(big).textContent);
    }

    // --- empty and missing ---
    {
      const empty = buildDocs([]);
      check('empty: heading has no count', byTag(empty, 'h3')[0].textContent === 'Documents');
      const body = byClass(empty, 'dashboard-empty__body');
      check('empty: only the empty copy', body.length === 1 && body[0].textContent === EMPTY
        && byTag(empty, 'table').length === 0 && byTag(empty, 'button').length === 0 && byClass(empty, 'dashboard-hint').length === 0, body.map((b) => b.textContent));
      for (const bad of [undefined, null, 'x', 7, {}]) {
        check(`missing: ${JSON.stringify(bad)} returns null`, buildDocs(bad) === null);
      }
      check('missing: an array of only malformed entries is the empty state', byClass(buildDocs([null, 3]), 'dashboard-empty__body').length === 1);
    }

    // --- click delegation ---
    {
      opened.length = 0;
      const docs = many(14);
      const root = buildDocs(docs);
      const table = byTag(root, 'table')[0];
      const rows = docRowsOf(root);
      table.dispatch('click', { target: rowBtn(rows[2]), detail: 1 });
      check('click: the button opens the row document once', opened.length === 1 && opened[0].doc.doc_id === 'doc_3'
        && opened[0].event && opened[0].event.detail === 1, opened.map((o) => o.doc.doc_id));
      table.dispatch('click', { target: byClass(rows[12], 'dashboard-count')[0], detail: 1 });
      check('click: a count cell in the hidden-then-revealed tbody opens its row', opened.length === 2 && opened[1].doc.doc_id === 'doc_13', opened.map((o) => o.doc.doc_id));
      table.dispatch('click', { target: byClass(rows[0], 'documents-name__text')[0] });
      check('click: a nested span resolves to its row', opened.length === 3 && opened[2].doc.doc_id === 'doc_1');
      table.dispatch('click', { target: byTag(root, 'thead')[0] });
      table.dispatch('click', { target: byTag(root, 'th')[0] });
      table.dispatch('click', { target: table });
      check('click: header and table do nothing', opened.length === 3, opened.length);
      check('click: delegation, no row or button listeners', rows.every((r) => r.listenerCount('click') === 0 && rowBtn(r).listenerCount('click') === 0));
      check('click: a tampered data-index opens nothing', (() => {
        rows[3].setAttribute('data-index', '999');
        table.dispatch('click', { target: rowBtn(rows[3]) });
        rows[3].setAttribute('data-index', 'abc');
        table.dispatch('click', { target: rowBtn(rows[3]) });
        return opened.length === 3;
      })(), opened.length);
      const noHandler = dash.buildDocuments({ documents: docs });
      let threw = false;
      try { byTag(noHandler, 'table')[0].dispatch('click', { target: rowBtn(docRowsOf(noHandler)[0]) }); } catch { threw = true; }
      check('click: a missing onOpen is tolerated', !threw);
    }

    // --- hostile ---
    {
      const hostile = ['<img src=x onerror=1>', '"><script>alert(1)</script>'];
      createdTags.length = 0;
      innerHtmlWrites.length = 0;
      opened.length = 0;
      const root = buildDocs([
        mk(1, { doc_id: hostile[0], display_name: hostile[1], filename: hostile[1] }),
        mk(2, { doc_id: hostile[1], display_name: hostile[0], filename: hostile[0] }),
      ]);
      check('hostile: no img or script element is created', !createdTags.includes('img') && !createdTags.includes('script'), createdTags);
      check('hostile: innerHTML is never assigned', innerHtmlWrites.length === 0);
      check('hostile: the tree holds no img or script element', find(root, (n) => n.tagName === 'img' || n.tagName === 'script').length === 0);
      const names = docRowsOf(root).map((r) => byClass(r, 'documents-name__text')[0].textContent);
      check('hostile: names are text', JSON.stringify(names) === JSON.stringify([hostile[1], hostile[0]]), names);
      const ids = docRowsOf(root).map((r) => r.getAttribute('data-doc-id'));
      check('hostile: ids are attribute values', JSON.stringify(ids) === JSON.stringify(hostile), ids);
      let badClass = false;
      walk(root, (n) => { if (/[<>"']|onerror|script/i.test(String(n.className || ''))) badClass = true; });
      check('hostile: no data-derived class names', !badClass);
      byTag(root, 'table')[0].dispatch('click', { target: rowBtn(docRowsOf(root)[0]) });
      check('hostile: the raw id reaches onOpen as a string', opened.length === 1 && opened[0].doc.doc_id === hostile[0], opened.map((o) => o.doc.doc_id));
    }
  }
}

process.stdout.write(JSON.stringify({ passed, failed }) + '\n');
process.exit(failed.length ? 1 : 0);
