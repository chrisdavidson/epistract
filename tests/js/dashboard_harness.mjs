// Behavioral harness for the Dashboard entity summary builders (dashboard.js).
// Imports the real dashboard.js (and display.js) against a stub DOM that records
// every created tag and every innerHTML assignment, then checks row order and
// markup, hostile type strings (SEC-01), click delegation, the totals button,
// the hint and the empty state. The `epistemic` mode covers
// buildEpistemicHealth (run: node dashboard_harness.mjs epistemic) and the
// `documents` mode covers buildDocuments (run: node dashboard_harness.mjs documents),
// and the `start-here` mode covers buildStartHere, the "Where to start" section
// with its topic communities and most-connected entities tables
// (run: node dashboard_harness.mjs start-here).
// Prints one JSON line {"passed": [...], "failed": [...]} and exits 1 on failure.
// The `ask-question` mode covers askAboutQuestion, the "Ask about this" question
// templates for every card kind (run: node dashboard_harness.mjs ask-question).
// The `ask-buttons` mode covers the "Ask about this" button of every builder
// (run: node dashboard_harness.mjs ask-buttons) and the `findings` mode covers
// buildFindings, the Analysis Findings table (run: node dashboard_harness.mjs findings).
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
      check('actions: Show in graph then Ask about this', g && a && g.textContent === 'Show in graph' && textOf(a) === 'Ask about this'
        && g.getAttribute('type') === 'button' && a.getAttribute('type') === 'button'
        && g.getAttribute('data-action') === 'show-graph' && a.getAttribute('data-action') === 'ask-chat', [g && g.textContent, a && a.textContent]);
      check('actions: data-section and data-index', g.getAttribute('data-section') === 'contradictions' && g.getAttribute('data-index') === '0'
        && cardsOf(sectionOf(root, 'contradictions'))[1].children.length > 0
        && byClass(cardsOf(sectionOf(root, 'contradictions'))[1], 'epistemic-btn')[0].getAttribute('data-index') === '1');
      check('actions: aria-labels', g.getAttribute('aria-label') === 'Show semaglutide is indicated for Obesity in the graph'
        && a.getAttribute('aria-label') === 'Ask about this: semaglutide is indicated for Obesity', [g.getAttribute('aria-label'), a.getAttribute('aria-label')]);
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
      check('dispatch: Ask about this passes the question and the event', asked.length === 1 && asked[0].question === GLP.sections[0].items[0].question
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
      check('disabled: Ask about this still works', asked.length === 1 && asked[0].question === 'What is behind this conflict?');
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

if (MODE === 'start-here') {
  const HINT = 'Begin with the largest topics or the most-connected entities. Select a row to see it in the graph.';
  const NO_COMMUNITIES = 'No topic communities were found for this graph.';
  const NO_HUBS = 'No connected entities yet.';
  if (typeof dash.buildStartHere !== 'function') {
    check('buildStartHere is exported by dashboard.js', false, typeof dash.buildStartHere);
  } else {
    const shown = [];
    const startHere = (payload, totalNodes = 218, callbacks = null) => dash.buildStartHere({
      startHere: payload,
      totalNodes,
      ...(callbacks || {
        onShowCommunity: (row, event) => shown.push({ kind: 'community', row, event }),
        onShowEntity: (row, event) => shown.push({ kind: 'entity', row, event }),
      }),
    });
    const community = (i, extra = {}) => ({
      id: `c${i}`, label: `Topic ${i}`, full_label: `Topic ${i} full label`, member_count: 40 - i,
      top_members: [`M${i}a`, `M${i}b`, `M${i}c`], ...extra,
    });
    const communities = (n) => Array.from({ length: n }, (_, i) => community(i + 1));
    const hub = (i, extra = {}) => ({
      id: `e${i}`, name: `Entity ${i}`, entity_type: 'A', connections: 30 - i,
      community_id: 'c1', community_label: 'Topic 1', ...extra,
    });
    const hubs = (n) => Array.from({ length: n }, (_, i) => hub(i + 1));
    const blocks = (root) => byClass(root, 'start-block');
    const commTable = (root) => byClass(root, 'start-communities-table')[0];
    const hubTable = (root) => byClass(root, 'start-hubs-table')[0];
    const rowsIn = (n) => (n ? byClass(n, 'dashboard-link-row') : []);
    const mainBtn = (row) => byClass(row, 'dashboard-link-btn')[0];
    const toggleBtn = (root) => byClass(root, 'start-toggle')[0];
    const statusEl = (root) => find(root, (n) => n.getAttribute && n.getAttribute('id') === 'start-status')[0];
    const tbodies = (root) => byTag(commTable(root), 'tbody');

    // --- structure: 10 communities + 10 hubs ---
    {
      createdTags.length = 0;
      innerHtmlWrites.length = 0;
      const root = startHere({ communities: communities(10), hubs: hubs(10) });
      check('start: section element', root && root.tagName === 'section' && root.className === 'start-here'
        && root.getAttribute('aria-labelledby') === 'start-here-heading', root && root.className);
      const h3 = byTag(root, 'h3')[0];
      check('start: h3 Where to start', h3 && h3.textContent === 'Where to start' && h3.getAttribute('id') === 'start-here-heading', h3 && h3.textContent);
      const hint = byClass(root, 'dashboard-hint')[0];
      check('start: hint copy', hint && hint.textContent === HINT, hint && hint.textContent);
      check('start: two blocks, communities first', blocks(root).length === 2
        && byClass(blocks(root)[0], 'start-communities-table').length === 1
        && byClass(blocks(root)[1], 'start-hubs-table').length === 1);
      const h4s = byTag(root, 'h4');
      check('start: block titles', h4s.length === 2 && h4s[0].textContent === 'Topic communities (10)'
        && h4s[0].getAttribute('id') === 'start-communities-heading' && h4s[0].className === 'start-block__title'
        && h4s[1].textContent === 'Most-connected entities' && h4s[1].getAttribute('id') === 'start-hubs-heading'
        && h4s[1].className === 'start-block__title', h4s.map((h) => h.textContent));
      const st = statusEl(root);
      check('start: status region', st && st.tagName === 'span' && st.className === 'visually-hidden'
        && st.getAttribute('role') === 'status' && st.getAttribute('aria-live') === 'polite');
      check('start: no img or script, no innerHTML', !createdTags.includes('img') && !createdTags.includes('script') && innerHtmlWrites.length === 0, createdTags);

      const ct = commTable(root);
      check('communities: table classes and label', ct && ct.className === 'dashboard-table start-communities-table'
        && ct.getAttribute('aria-labelledby') === 'start-communities-heading', ct && ct.className);
      check('communities: no colgroup', byTag(root, 'colgroup').length === 0);
      const cth = byTag(ct, 'th');
      check('communities: headers', JSON.stringify(cth.map((t) => t.textContent)) === JSON.stringify(['Community', 'Members'])
        && cth[1].matches('th.start-col-count'), cth.map((t) => t.textContent));
      const rows = rowsIn(ct);
      check('communities: 10 rows in payload order', rows.length === 10 && rows.every((r, i) => r.tagName === 'tr'
        && r.getAttribute('data-index') === String(i) && r.getAttribute('data-group-id') === `c${i + 1}`), rows.length);
      const r0 = rows[0];
      const cell0 = byClass(r0, 'dashboard-link-cell')[0];
      const actions0 = cell0 && cell0.children[0];
      const btn0 = mainBtn(r0);
      check('communities: cell > start-action > button', cell0 && cell0.tagName === 'td' && actions0 && actions0.tagName === 'div'
        && actions0.className === 'start-action' && actions0.children[0] === btn0);
      check('communities: button attributes', btn0 && btn0.tagName === 'button' && btn0.getAttribute('type') === 'button'
        && btn0.getAttribute('data-start-action') === 'show', btn0 && btn0.getAttribute('data-start-action'));
      const name0 = byClass(btn0, 'start-name')[0];
      check('communities: name stack', name0 && name0.tagName === 'span' && byClass(name0, 'start-name__text')[0].textContent === 'Topic 1'
        && byClass(name0, 'start-name__sub')[0].textContent === 'Top members: M1a, M1b, M1c');
      const chev = byClass(btn0, 'dashboard-link-chevron')[0];
      check('communities: chevron last and hidden', chev && chev.textContent === '›' && chev.getAttribute('aria-hidden') === 'true'
        && btn0.children[btn0.children.length - 1] === chev);
      check('communities: title is the full label and the members line', btn0.getAttribute('title') === 'Topic 1 full label\nTop members: M1a, M1b, M1c', btn0.getAttribute('title'));
      check('communities: aria-label with three members', btn0.getAttribute('aria-label')
        === 'Show the Topic 1 full label community in the graph: 39 members, including M1a, M1b and M1c', btn0.getAttribute('aria-label'));
      const counts = rows.map((r) => byClass(r, 'dashboard-count')[0].textContent);
      check('communities: member counts', JSON.stringify(counts) === JSON.stringify(['39', '38', '37', '36', '35', '34', '33', '32', '31', '30']), counts);
      check('communities: one tab stop per row', rows.every((r) => byTag(r, 'button').length === 1));
      check('communities: no toggle and one tbody', !toggleBtn(root) && tbodies(root).length === 1);

      const ht = hubTable(root);
      check('hubs: table classes and label', ht && ht.className === 'dashboard-table start-hubs-table'
        && ht.getAttribute('aria-labelledby') === 'start-hubs-heading', ht && ht.className);
      const hth = byTag(ht, 'th');
      check('hubs: headers', JSON.stringify(hth.map((t) => t.textContent)) === JSON.stringify(['Entity', 'Type', 'Connections', 'Community'])
        && hth[1].matches('th.start-col-type') && hth[2].matches('th.start-col-count') && hth[3].matches('th.start-col-community'), hth.map((t) => t.textContent));
      const hrows = rowsIn(ht);
      check('hubs: 10 rows with index and node id', hrows.length === 10 && hrows.every((r, i) => r.getAttribute('data-index') === String(i)
        && r.getAttribute('data-node-id') === `e${i + 1}`));
      check('hubs: one tbody, no toggle', byTag(ht, 'tbody').length === 1);
    }

    // --- row details and copy ---
    {
      const comms = [
        community(1, { member_count: 1, top_members: ['Solo'] }),
        community(2, { member_count: 0, top_members: ['A1', 'B1'] }),
        community(3, { member_count: 1234, top_members: [] }),
        community(4, { label: '', full_label: 'Only full', top_members: 'x' }),
        community(5, { label: '', full_label: '', top_members: null }),
      ];
      const hs = [
        hub(1, { connections: 1, community_id: 'c1', community_label: 'Topic 1' }),
        hub(2, { connections: 2, community_id: null, community_label: null }),
        hub(3, { connections: 1500, community_id: 'gone', community_label: 'Short gone' }),
        hub(4, { name: '', entity_type: 'ZED' }),
        hub(5, { entity_type: 'B' }),
      ];
      const root = startHere({ communities: comms, hubs: hs });
      const rows = rowsIn(commTable(root));
      const aria = rows.map((r) => mainBtn(r).getAttribute('aria-label'));
      check('copy: one member singular, one name', aria[0] === 'Show the Topic 1 full label community in the graph: 1 member, including Solo', aria[0]);
      check('copy: two names joined with and', aria[1] === 'Show the Topic 2 full label community in the graph: 0 members, including A1 and B1', aria[1]);
      check('copy: no members suffix and locale count', aria[2] === 'Show the Topic 3 full label community in the graph: 1,234 members', aria[2]);
      const labels = rows.map((r) => byClass(r, 'start-name__text')[0].textContent);
      check('copy: label falls back to full label then id', labels[3] === 'Only full' && labels[4] === 'c5', labels);
      check('copy: no sub line without members', byClass(rows[2], 'start-name__sub').length === 0 && byClass(rows[3], 'start-name__sub').length === 0
        && byClass(rows[4], 'start-name__sub').length === 0);
      check('copy: title without members is the full label', mainBtn(rows[2]).getAttribute('title') === 'Topic 3 full label', mainBtn(rows[2]).getAttribute('title'));
      check('copy: zero members muted', byClass(rows[1], 'dashboard-count--zero').length === 1 && byClass(rows[0], 'dashboard-count--zero').length === 0);
      check('copy: member count locale', byClass(rows[2], 'dashboard-count')[0].textContent === '1,234');

      const hrows = rowsIn(hubTable(root));
      const haria = hrows.map((r) => mainBtn(r).getAttribute('aria-label'));
      check('hub: aria-label with the community full label, singular', haria[0] === 'Show Entity 1 and its connections in the graph: Alpha, 1 connection, in the Topic 1 full label community', haria[0]);
      check('hub: aria-label not in a community', haria[1] === 'Show Entity 2 and its connections in the graph: Alpha, 2 connections, not in a topic community', haria[1]);
      check('hub: aria-label falls back to the short label (A-7)', haria[2] === 'Show Entity 3 and its connections in the graph: Alpha, 1,500 connections, in the Short gone community', haria[2]);
      check('hub: title is the name', mainBtn(hrows[0]).getAttribute('title') === 'Entity 1');
      const names = hrows.map((r) => byClass(r, 'start-name__text')[0].textContent);
      check('hub: name falls back to id', names[3] === 'e4', names);
      check('hub: no sub line', hrows.every((r) => byClass(r, 'start-name__sub').length === 0));
      const typeCells = hrows.map((r) => byClass(r, 'start-type')[0]);
      check('hub: type cell is a td with a swatch and a label', typeCells.every((c) => c && c.tagName === 'td'
        && byClass(c, 'type-swatch').length === 1 && byClass(c, 'start-type__label').length === 1));
      const typeLabels = typeCells.map((c) => byClass(c, 'start-type__label')[0].textContent);
      check('hub: type labels', JSON.stringify(typeLabels) === JSON.stringify(['Alpha', 'Alpha', 'Alpha', 'ZED', 'Beta Things']), typeLabels);
      check('hub: type cell title is the label', typeCells.every((c, i) => c.getAttribute('title') === typeLabels[i]));
      const summaryLabels = new Map(dash.sortEntityRows({ A: 1, B: 1, ZED: 1 }).map((r) => [r.type, r.label]));
      check('hub: type labels equal the Entity Summary labels', typeLabels[0] === summaryLabels.get('A')
        && typeLabels[3] === summaryLabels.get('ZED') && typeLabels[4] === summaryLabels.get('B'), [...summaryLabels]);
      const conn = hrows.map((r) => byClass(r, 'dashboard-count')[0].textContent);
      check('hub: connections locale', conn[2] === '1,500' && conn[0] === '1', conn);
      const commCells = hrows.map((r) => byClass(r, 'start-community')[0]);
      check('hub: community cell short label and full-label title', commCells[0].tagName === 'td' && commCells[0].textContent === 'Topic 1'
        && commCells[0].getAttribute('title') === 'Topic 1 full label', commCells[0].getAttribute('title'));
      check('hub: unclustered community', commCells[1].textContent === 'Unclustered' && commCells[1].matches('td.start-community--none'), commCells[1].className);
      check('hub: unknown community id keeps the short label as title', commCells[2].textContent === 'Short gone'
        && commCells[2].getAttribute('title') === 'Short gone' && !commCells[2].matches('td.start-community--none'));
      check('hub: community cell is plain text', commCells.every((c) => byTag(c, 'button').length === 0));
    }

    // --- 25 communities: Show all toggle ---
    {
      focusLog.length = 0;
      const root = startHere({ communities: communities(25), hubs: hubs(3) });
      check('toggle: title count', byTag(root, 'h4')[0].textContent === 'Topic communities (25)');
      const [first, rest] = tbodies(root);
      check('toggle: first tbody 10 rows', tbodies(root).length === 2 && rowsIn(first).length === 10, tbodies(root).length);
      check('toggle: rest tbody 15 rows hidden', rest && rowsIn(rest).length === 15 && rest.hasAttribute('hidden')
        && rest.getAttribute('id') === 'start-communities-rest');
      const t = toggleBtn(root);
      check('toggle: collapsed state', t && t.tagName === 'button' && t.getAttribute('type') === 'button' && t.textContent === 'Show all 25'
        && t.getAttribute('aria-expanded') === 'false' && t.getAttribute('aria-controls') === 'start-communities-rest'
        && t.getAttribute('aria-label') === 'Show all 25 topic communities', t && t.textContent);
      const commBlock = blocks(root)[0];
      check('toggle: inside the communities block after the table', t && commBlock.children.indexOf(t) > commBlock.children.findIndex((c) => c.className === 'dashboard-table-wrap'));
      t.dispatch('click', { detail: 1 });
      check('toggle: expands', t.getAttribute('aria-expanded') === 'true' && !rest.hasAttribute('hidden') && t.textContent === 'Show first 10'
        && t.getAttribute('aria-label') === 'Show only the first 10 topic communities', [t.textContent, t.getAttribute('aria-label')]);
      check('toggle: status all', statusEl(root).textContent === 'Showing all 25 topic communities.', statusEl(root).textContent);
      const target = mainBtn(rowsIn(rest)[0]);
      check('toggle: focus on row 11 with preventScroll', focusLog.length === 1 && focusLog[0].el === target
        && focusLog[0].options && focusLog[0].options.preventScroll === true, focusLog.length);
      t.dispatch('click', { detail: 1 });
      check('toggle: collapses', t.getAttribute('aria-expanded') === 'false' && rest.hasAttribute('hidden') && t.textContent === 'Show all 25'
        && t.getAttribute('aria-label') === 'Show all 25 topic communities');
      check('toggle: status first 10', statusEl(root).textContent === 'Showing the first 10 of 25 topic communities.', statusEl(root).textContent);
      check('toggle: focus back on the toggle', focusLog.length === 2 && focusLog[1].el === t && focusLog[1].options && focusLog[1].options.preventScroll === true);
      const eleven = startHere({ communities: communities(11), hubs: [] });
      check('toggle: 11 communities give one hidden row', toggleBtn(eleven) && rowsIn(tbodies(eleven)[1]).length === 1);
      const big = startHere({ communities: Array.from({ length: 1200 }, (_, i) => community(i + 1)), hubs: [] });
      check('toggle: locale counts', byTag(big, 'h4')[0].textContent === 'Topic communities (1,200)' && toggleBtn(big).textContent === 'Show all 1,200', toggleBtn(big).textContent);
    }

    // --- empty and missing ---
    {
      const noComm = startHere({ communities: [], hubs: hubs(2) });
      const h4 = byTag(noComm, 'h4');
      check('empty: communities title without count', h4[0].textContent === 'Topic communities', h4[0].textContent);
      const commBlock = blocks(noComm)[0];
      const body = byClass(commBlock, 'dashboard-empty__body');
      check('empty: communities copy, no table or toggle', body.length === 1 && body[0].textContent === NO_COMMUNITIES
        && !commTable(noComm) && !toggleBtn(noComm), body.map((b) => b.textContent));
      check('empty: hubs still render', rowsIn(hubTable(noComm)).length === 2);
      check('empty: hint shown when one block has rows', byClass(noComm, 'dashboard-hint').length === 1);
      const noHubs = startHere({ communities: communities(2), hubs: [] });
      const hubBody = byClass(blocks(noHubs)[1], 'dashboard-empty__body');
      check('empty: hubs copy, no table', hubBody.length === 1 && hubBody[0].textContent === NO_HUBS && !hubTable(noHubs)
        && byTag(noHubs, 'h4')[1].textContent === 'Most-connected entities');
      check('empty: both empty, no nodes -> null', startHere({ communities: [], hubs: [] }, 0) === null);
      const both = startHere({ communities: [], hubs: [] }, 5);
      check('empty: both empty with nodes -> both copies, no hint', both && byClass(both, 'dashboard-empty__body').length === 2
        && byClass(both, 'dashboard-hint').length === 0);
      for (const bad of [undefined, null, 'x', [], 7]) {
        check(`missing: startHere ${JSON.stringify(bad)} -> null`, startHere(bad) === null);
      }
      const notArrays = startHere({ communities: 'x', hubs: { a: 1 } }, 5);
      check('missing: non-array lists are treated as empty', notArrays && byClass(notArrays, 'dashboard-empty__body').length === 2);
      check('missing: non-array lists with no nodes -> null', startHere({ communities: 'x', hubs: null }, 0) === null);
      const dirty = startHere({ communities: [null, 3, 'x', [], community(1)], hubs: [null, 'y', hub(1)] });
      check('missing: non-object rows are skipped', rowsIn(commTable(dirty)).length === 1 && rowsIn(hubTable(dirty)).length === 1
        && rowsIn(commTable(dirty))[0].getAttribute('data-index') === '0');
      // IN-03: a row whose click could not name its target is not drawn.
      const badIds = [{ id: '' }, { id: 7 }, { id: null }, { id: undefined }];
      const noIds = startHere({
        communities: [...badIds.map((b) => community(9, b)), community(1)],
        hubs: [...badIds.map((b) => hub(9, b)), hub(1)],
      });
      check('missing: rows without a non-empty string id are skipped', rowsIn(commTable(noIds)).length === 1
        && rowsIn(hubTable(noIds)).length === 1, [rowsIn(commTable(noIds)).length, rowsIn(hubTable(noIds)).length]);
    }

    // --- activation ---
    {
      shown.length = 0;
      const comms = communities(12);
      const hs = hubs(4);
      const root = startHere({ communities: comms, hubs: hs });
      const ct = commTable(root);
      const ht = hubTable(root);
      const crows = rowsIn(ct);
      const hrows = rowsIn(ht);
      ct.dispatch('click', { target: mainBtn(crows[1]), detail: 1 });
      check('click: community button calls onShowCommunity once with the payload row', shown.length === 1 && shown[0].kind === 'community'
        && shown[0].row === comms[1] && shown[0].event && shown[0].event.detail === 1, shown.map((x) => x.kind));
      ct.dispatch('click', { target: byClass(crows[11], 'dashboard-count')[0] });
      check('click: a count cell in the rest tbody opens its row', shown.length === 2 && shown[1].row === comms[11]);
      ct.dispatch('click', { target: byClass(crows[0], 'start-name__sub')[0] });
      check('click: a nested span resolves to its row', shown.length === 3 && shown[2].row === comms[0]);
      ht.dispatch('click', { target: mainBtn(hrows[2]), detail: 0 });
      check('click: hub button calls onShowEntity with the payload row', shown.length === 4 && shown[3].kind === 'entity' && shown[3].row === hs[2]
        && shown[3].event.detail === 0);
      ht.dispatch('click', { target: byClass(hrows[0], 'start-type')[0] });
      ht.dispatch('click', { target: byClass(hrows[1], 'start-community')[0] });
      check('click: type and community cells open their hub', shown.length === 6 && shown[4].row === hs[0] && shown[5].row === hs[1]);
      ct.dispatch('click', { target: byTag(ct, 'th')[0] });
      ht.dispatch('click', { target: ht });
      check('click: headers and tables do nothing', shown.length === 6, shown.length);
      check('click: delegation only', [...crows, ...hrows].every((r) => r.listenerCount('click') === 0 && mainBtn(r).listenerCount('click') === 0));
      crows[2].setAttribute('data-index', '999');
      ct.dispatch('click', { target: mainBtn(crows[2]) });
      crows[2].setAttribute('data-index', 'abc');
      ct.dispatch('click', { target: mainBtn(crows[2]) });
      crows[2].setAttribute('data-index', '-1');
      ct.dispatch('click', { target: mainBtn(crows[2]) });
      hrows[1].setAttribute('data-index', '1.5');
      ht.dispatch('click', { target: mainBtn(hrows[1]) });
      check('click: tampered data-index opens nothing', shown.length === 6, shown.length);
      // Phase 10 routing: a second action button appended into the row's .start-action.
      const ask = document.createElement('button');
      ask.setAttribute('type', 'button');
      ask.setAttribute('data-start-action', 'ask');
      byClass(crows[3], 'start-action')[0].appendChild(ask);
      ct.dispatch('click', { target: ask });
      const askHub = document.createElement('button');
      askHub.setAttribute('data-start-action', 'ask');
      byClass(hrows[3], 'start-action')[0].appendChild(askHub);
      ht.dispatch('click', { target: askHub });
      check('click: an ask action calls neither callback', shown.length === 6, shown.length);
      const bare = startHere({ communities: comms, hubs: hs }, 218, {});
      let threw = false;
      try {
        commTable(bare).dispatch('click', { target: mainBtn(rowsIn(commTable(bare))[0]) });
        hubTable(bare).dispatch('click', { target: mainBtn(rowsIn(hubTable(bare))[0]) });
      } catch { threw = true; }
      check('click: missing callbacks are tolerated', !threw);
    }

    // --- hostile ---
    {
      const hostile = ['<img src=x onerror=1>', '"><script>alert(1)</script>'];
      createdTags.length = 0;
      innerHtmlWrites.length = 0;
      shown.length = 0;
      const root = startHere({
        communities: [community(1, { id: hostile[1], label: hostile[0], full_label: hostile[1], top_members: [hostile[0], hostile[1]] })],
        hubs: [hub(1, { id: hostile[0], name: hostile[1], entity_type: hostile[0], community_id: hostile[1], community_label: hostile[0] })],
      });
      check('hostile: no img or script element is created', !createdTags.includes('img') && !createdTags.includes('script'), createdTags);
      check('hostile: innerHTML is never assigned', innerHtmlWrites.length === 0);
      check('hostile: the tree holds no img or script', find(root, (n) => n.tagName === 'img' || n.tagName === 'script').length === 0);
      const crow = rowsIn(commTable(root))[0];
      const hrow = rowsIn(hubTable(root))[0];
      check('hostile: label and members are text', byClass(crow, 'start-name__text')[0].textContent === hostile[0]
        && byClass(crow, 'start-name__sub')[0].textContent === `Top members: ${hostile[0]}, ${hostile[1]}`);
      check('hostile: ids are attribute values', crow.getAttribute('data-group-id') === hostile[1] && hrow.getAttribute('data-node-id') === hostile[0]);
      check('hostile: hub name, type and community are text', byClass(hrow, 'start-name__text')[0].textContent === hostile[1]
        && byClass(hrow, 'start-type__label')[0].textContent === hostile[0]
        && byClass(hrow, 'start-community')[0].textContent === hostile[0]
        && byClass(hrow, 'start-community')[0].getAttribute('title') === hostile[1]);
      let badClass = false;
      walk(root, (n) => { if (/[<>"']|onerror|script/i.test(String(n.className || ''))) badClass = true; });
      check('hostile: no data-derived class names', !badClass);
      commTable(root).dispatch('click', { target: mainBtn(crow) });
      check('hostile: the raw row reaches the callback', shown.length === 1 && shown[0].row.id === hostile[1]);
    }
  }
}

if (MODE === 'ask-question') {
  if (typeof dash.askAboutQuestion !== 'function') {
    check('askAboutQuestion is exported by dashboard.js', false, typeof dash.askAboutQuestion);
  } else {
    const q = dash.askAboutQuestion;
    const GRAPH_Q = 'Give me an overview of this knowledge graph: what are its main topics and most important entities?';
    const STATUS_Q = "What does the epistemic status distribution say about how well supported this graph's claims are?";
    const typeQ = (label) => `What are the most important ${label} entities in this graph, and how do they connect?`;
    const commQ = (label) => `Summarize the ${label} community.`;
    const hubQ = (name) => `What is ${name}, and why is it so connected in this graph?`;
    const docQ = (inner) => `Summarize the document ${inner}: what are its key findings?`;
    const findQ = (rule, total) => `Explain the ${rule} findings (${total}): which ones matter most and why?`;
    const eq = (name, got, want) => check(name, got === want, { got, want });

    // --- graph ---
    eq('graph: no fields', q('graph'), GRAPH_Q);
    eq('graph: null fields', q('graph', null), GRAPH_Q);
    eq('graph: number fields', q('graph', 5), GRAPH_Q);

    // --- type ---
    eq('type: display label', q('type', { label: 'Disease', type: 'DISEASE' }), typeQ('Disease'));
    eq('type: whitespace collapsed', q('type', { label: '  Beta \n Things ', type: 'B' }), typeQ('Beta Things'));
    eq('type: empty label falls back to the type key', q('type', { label: '', type: 'MYSTERY_TYPE' }), typeQ('MYSTERY_TYPE'));
    eq('type: whitespace-only label and key give empty', q('type', { label: '   ', type: '  ' }), '');

    // --- community ---
    eq('community: full label collapsed', q('community', { fullLabel: '  Tau\n  protein ', label: 'x', id: 'c1' }), commQ('Tau protein'));
    eq('community: empty full label falls back to label', q('community', { fullLabel: '', label: 'Tau', id: 'c1' }), commQ('Tau'));
    eq('community: id is the last fallback', q('community', { id: 'c9' }), commQ('c9'));
    eq('community: GLP-1 v3 label with dash and parens', q('community', { fullLabel: 'Systemic Hypertension — Glp-1(7-37)' }),
      commQ('Systemic Hypertension — Glp-1(7-37)'));
    eq('community: all empty give empty', q('community', { fullLabel: ' ', label: '', id: '\n' }), '');

    // --- hub ---
    eq('hub: name', q('hub', { name: 'semaglutide', id: 'compound:semaglutide' }), hubQ('semaglutide'));
    eq('hub: empty name falls back to id', q('hub', { name: '', id: 'compound:x' }), hubQ('compound:x'));
    eq('hub: both empty give empty', q('hub', { name: '', id: '' }), '');

    // --- epistemic ---
    eq('epistemic: payload question verbatim',
      q('epistemic', { question: 'Why do sources disagree on whether semaglutide is indicated for Obesity?', title: 't', sectionKey: 'contradictions' }),
      'Why do sources disagree on whether semaglutide is indicated for Obesity?');
    eq('epistemic: question is not collapsed', q('epistemic', { question: '  spaced   question  ', title: 't', sectionKey: 'risks' }),
      '  spaced   question  ');
    eq('epistemic: fallback names the title', q('epistemic', { question: '', title: 'A title', sectionKey: 'risks' }),
      'What does the evidence say about: A title?');
    eq('epistemic: fallback names the section key', q('epistemic', { question: '', title: '', sectionKey: 'hypotheses' }),
      'What does the evidence say about: hypotheses?');

    // --- epistemic-status ---
    eq('epistemic-status: fixed question', q('epistemic-status'), STATUS_Q);
    eq('epistemic-status: fields are ignored', q('epistemic-status', { label: 'x', question: 'y' }), STATUS_Q);

    // --- document ---
    eq('document: name and id', q('document', { name: 'Doc 1', doc_id: 'doc_1' }), docQ('Doc 1 (doc_1)'));
    eq('document: name equal to id omits the parenthetical', q('document', { name: 'pmid_38851997', doc_id: 'pmid_38851997' }),
      docQ('pmid_38851997'));
    eq('document: names differing only by case keep the id',
      q('document', { name: 'patent_06_US10370426B2_triple_agonist', doc_id: 'patent_06_us10370426b2_triple_agonist' }),
      docQ('patent_06_US10370426B2_triple_agonist (patent_06_us10370426b2_triple_agonist)'));
    eq('document: empty name uses the id once', q('document', { name: '', doc_id: 'd' }), docQ('d'));
    eq('document: empty id omits the parenthetical', q('document', { name: 'X', doc_id: '' }), docQ('X'));
    eq('document: both empty give empty', q('document', { name: '', doc_id: '' }), '');

    // --- finding ---
    eq('finding: rule and total', q('finding', { rule_name: 'label_gap', total: 1 }), findQ('label_gap', 1));
    eq('finding: zero total', q('finding', { rule_name: 'r', total: 0 }), findQ('r', 0));
    eq('finding: missing total is 0', q('finding', { rule_name: 'r' }), findQ('r', 0));
    eq('finding: whitespace rule gives empty', q('finding', { rule_name: '   ', total: 2 }), '');
    eq('finding: non-string rule gives empty', q('finding', { rule_name: 7 }), '');

    // --- hostile ---
    for (const h of ['<img src=x onerror=1>', '"><script>alert(1)</script>']) {
      eq(`hostile ${h}: community`, q('community', { fullLabel: h, label: 'x', id: 'c' }), commQ(h));
      eq(`hostile ${h}: hub`, q('hub', { name: h, id: 'e' }), hubQ(h));
      eq(`hostile ${h}: document`, q('document', { name: h, doc_id: 'd' }), docQ(`${h} (d)`));
      eq(`hostile ${h}: finding`, q('finding', { rule_name: h, total: 3 }), findQ(h, 3));
    }

    // --- no truncation ---
    {
      const long = 'L'.repeat(300);
      eq('no truncation: a 300-character community label is whole', q('community', { fullLabel: long }), commQ(long));
    }

    // --- unknown kinds and odd fields ---
    for (const kind of ['nope', undefined, 7, '__proto__', 'constructor', 'toString', 'hasOwnProperty', null]) {
      eq(`unknown kind ${String(kind)} gives empty`, q(kind, { label: 'x', name: 'x', fullLabel: 'x', rule_name: 'x' }), '');
    }
    {
      const kinds = ['graph', 'type', 'community', 'hub', 'epistemic', 'epistemic-status', 'document', 'finding'];
      let threw = null;
      let nonString = null;
      for (const kind of kinds) {
        for (const fields of [null, undefined, 3, 's', [], { label: 5, name: {}, fullLabel: [], doc_id: 9, question: 4 }]) {
          try {
            const out = q(kind, fields);
            if (typeof out !== 'string') nonString = { kind, fields, out };
          } catch (e) {
            threw = { kind, fields, error: String(e) };
          }
        }
      }
      check('odd fields: never throws', threw === null, threw);
      check('odd fields: always returns a string', nonString === null, nonString);
    }

    // --- purity ---
    {
      const fields = { name: ' Doc  A ', doc_id: 'doc_a', fullLabel: 'F', label: 'L', id: 'i', rule_name: 'r', total: 2 };
      const before = JSON.stringify(fields);
      const kinds = ['graph', 'type', 'community', 'hub', 'epistemic', 'epistemic-status', 'document', 'finding'];
      const first = kinds.map((k) => q(k, fields));
      const second = kinds.map((k) => q(k, fields));
      check('purity: same input gives the same output', JSON.stringify(first) === JSON.stringify(second), [first, second]);
      check('purity: the fields object is not mutated', JSON.stringify(fields) === before, fields);
    }
  }
}

// Shared by the ask-buttons and findings modes.
const ASK_TITLE_TEXT = 'Puts a question in the chat box. Nothing is sent until you press Send.';
const classList = (n) => String((n && n.className) || '').split(/\s+/).filter(Boolean);
const askButtons = (root) => find(root, (n) => n.matches('button.ask-about-btn'));
const askIn = (n) => (n ? find(n, (x) => x.matches('button.ask-about-btn'))[0] : undefined);
// One block of checks; an exception (a missing element on a red run) is a
// named failure instead of a crash.
const guarded = (name, fn) => {
  try { fn(); } catch (e) { check(`${name}: runs without throwing`, false, String(e && e.stack ? e.stack.split('\n').slice(0, 2).join(' ') : e)); }
};
// The shared Ask anatomy (UI-SPEC A, A-1, A-2).
const checkAnatomy = (name, btn, kind, aria, extraClasses = []) => {
  check(`${name}: Ask button exists`, !!btn, kind);
  if (!btn) return;
  check(`${name}: button element of type button`, btn.tagName === 'button' && btn.getAttribute('type') === 'button', btn.tagName);
  check(`${name}: classes include ask-about-btn`, ['ask-about-btn', ...extraClasses].every((c) => classList(btn).includes(c)), btn.className);
  check(`${name}: data-ask is ${kind}`, btn.getAttribute('data-ask') === kind, btn.getAttribute('data-ask'));
  check(`${name}: title is ASK_TITLE`, btn.getAttribute('title') === ASK_TITLE_TEXT, btn.getAttribute('title'));
  check(`${name}: text is Ask about this`, textOf(btn) === 'Ask about this', textOf(btn));
  const [first, second] = btn.children;
  check(`${name}: first child is the text node Ask`, !!first && first.isText === true && first.textContent === 'Ask', first && first.textContent);
  check(`${name}: second child is span.ask-about-btn__more " about this"`, !!second && !!second.matches
    && second.matches('span.ask-about-btn__more') && textOf(second) === ' about this', second && textOf(second));
  check(`${name}: aria-label`, btn.getAttribute('aria-label') === aria, { got: btn.getAttribute('aria-label'), want: aria });
};

if (MODE === 'ask-buttons') {
  const Q = (kind, fields) => (typeof dash.askAboutQuestion === 'function' ? dash.askAboutQuestion(kind, fields) : `<${kind}>`);
  const GRAPH_Q = 'Give me an overview of this knowledge graph: what are its main topics and most important entities?';
  const STATUS_Q = "What does the epistemic status distribution say about how well supported this graph's claims are?";

  // --- Entity Summary rows and totals ---
  guarded('summary', () => {
    const asked = [];
    const picked = [];
    let all = 0;
    const root = dash.buildEntitySummary({
      entityCounts: { A: 3, B: 10, ONE: 1, '   ': 2 },
      totalNodes: 16,
      totalEdges: 4,
      onSelectType: (type, event) => picked.push({ type, event }),
      onShowAll: () => { all += 1; },
      onAsk: (question, event) => asked.push({ question, event }),
    });
    const rows = byClass(root, 'dashboard-link-row');
    const rowOf = (type) => rows.find((r) => r.getAttribute('data-entity-type') === type);
    check('summary: four rows', rows.length === 4, rows.length);
    const table = byTag(root, 'table')[0];
    const typeAsks = table ? askButtons(table) : [];
    check('summary: three Ask buttons in the table (the blank key gets none)', typeAsks.length === 3, typeAsks.length);
    const blank = rowOf('   ');
    const blankCell = blank && byClass(blank, 'dashboard-link-cell')[0];
    check('summary: the blank-key row has no Ask and no wrapper', !!blankCell && blankCell.children.length === 1
      && blankCell.children[0].matches('button.dashboard-link-btn') && !askIn(blank)
      && byClass(blank, 'dashboard-row-actions').length === 0, blankCell && blankCell.children.map((c) => c.className));
    for (const [type, label] of [['A', 'Alpha'], ['B', 'Beta Things'], ['ONE', 'Solo']]) {
      const row = rowOf(type);
      const cell = row && byClass(row, 'dashboard-link-cell')[0];
      const wrap = cell && cell.children.length === 1 ? cell.children[0] : null;
      const ok = !!wrap && wrap.tagName === 'div' && wrap.className === 'dashboard-row-actions' && wrap.children.length === 2
        && wrap.children[0].matches('button.dashboard-link-btn') && wrap.children[1].matches('button.ask-about-btn');
      check(`summary: ${type} first cell is div.dashboard-row-actions [main, Ask]`, ok, cell && cell.children.map((c) => c.className));
      const ask = askIn(row);
      check(`summary: ${type} Ask is not a row button`, !!ask && !classList(ask).includes('dashboard-link-btn')
        && !ask.hasAttribute('data-entity-type'), ask && ask.className);
      check(`summary: ${type} Ask aria-label`, !!ask && ask.getAttribute('aria-label') === `Ask about this: ${label} entities`, ask && ask.getAttribute('aria-label'));
    }
    const askB = askIn(rowOf('B'));
    checkAnatomy('anatomy type', askB, 'type', 'Ask about this: Beta Things entities');
    const BQ = 'What are the most important Beta Things entities in this graph, and how do they connect?';
    table.dispatch('click', { target: askB || table, detail: 1 });
    check('summary: B Ask calls onAsk once with the type question and the event', asked.length === 1 && asked[0].question === BQ
      && asked[0].event && asked[0].event.detail === 1, asked.map((a) => a.question));
    check('summary: B Ask never selects the type', picked.length === 0, picked.map((p) => p.type));
    const more = askB ? byClass(askB, 'ask-about-btn__more')[0] : null;
    table.dispatch('click', { target: more || table });
    check('summary: a click on the Ask span also asks', asked.length === 2 && asked[1].question === BQ && picked.length === 0, asked.length);
    asked.length = 0;
    picked.length = 0;
    table.dispatch('click', { target: byClass(rowOf('B'), 'dashboard-link-btn')[0] });
    table.dispatch('click', { target: byClass(rowOf('B'), 'dashboard-count')[0] });
    check('summary: main button and count cell still select B, not ask', picked.length === 2 && picked.every((p) => p.type === 'B')
      && asked.length === 0, { picked: picked.map((p) => p.type), asked: asked.length });

    const totals = byClass(root, 'dashboard-totals')[0];
    const totalsBtn = totals && byClass(totals, 'dashboard-totals-btn')[0];
    const totalsAsk = askIn(totals);
    check('totals: p.dashboard-totals children are [totals button, Ask]', !!totals && totals.children.length === 2
      && totals.children[0] === totalsBtn && totals.children[1] === totalsAsk && !!totalsAsk, totals && totals.children.map((c) => c.className));
    checkAnatomy('anatomy graph', totalsAsk, 'graph', 'Ask about this: the knowledge graph');
    asked.length = 0;
    if (totalsAsk) totalsAsk.dispatch('click', { detail: 0 });
    check('totals: Ask calls onAsk with the graph question, not onShowAll', asked.length === 1 && asked[0].question === GRAPH_Q && all === 0,
      { asked: asked.map((a) => a.question), all });
    asked.length = 0;
    all = 0;
    if (totalsBtn) totalsBtn.dispatch('click', { detail: 0 });
    check('totals: the totals button still shows all and does not ask', all === 1 && asked.length === 0, { all, asked: asked.length });
  });

  guarded('summary without onAsk', () => {
    const plain = dash.buildEntitySummary({ entityCounts: { A: 3, B: 10 }, totalNodes: 13, totalEdges: 2, onSelectType: () => {}, onShowAll: () => {} });
    check('summary without onAsk: no Ask and no wrapper', askButtons(plain).length === 0 && byClass(plain, 'dashboard-row-actions').length === 0);
    const empty = dash.buildEntitySummary({ entityCounts: {}, totalNodes: 0, totalEdges: 0, onAsk: () => {} });
    check('summary empty state with onAsk: no Ask and no wrapper', askButtons(empty).length === 0 && byClass(empty, 'dashboard-row-actions').length === 0);
  });

  // --- Where to start ---
  const community = (i, extra = {}) => ({
    id: `c${i}`, label: `Topic ${i}`, full_label: `Topic ${i} full label`, member_count: 40 - i,
    top_members: [`M${i}a`, `M${i}b`, `M${i}c`], ...extra,
  });
  const hub = (i, extra = {}) => ({
    id: `e${i}`, name: `Entity ${i}`, entity_type: 'A', connections: 30 - i, community_id: 'c1', community_label: 'Topic 1', ...extra,
  });
  guarded('start', () => {
    const asked = [];
    const shown = [];
    focusLog.length = 0;
    const comms = Array.from({ length: 25 }, (_, i) => community(i + 1));
    const hs = Array.from({ length: 10 }, (_, i) => hub(i + 1));
    const root = dash.buildStartHere({
      startHere: { communities: comms, hubs: hs },
      totalNodes: 218,
      onShowCommunity: (row, event) => shown.push({ kind: 'community', row, event }),
      onShowEntity: (row, event) => shown.push({ kind: 'entity', row, event }),
      onAsk: (question, event) => asked.push({ question, event }),
    });
    const ct = byClass(root, 'start-communities-table')[0];
    const ht = byClass(root, 'start-hubs-table')[0];
    const crows = byClass(ct, 'dashboard-link-row');
    const hrows = byClass(ht, 'dashboard-link-row');
    check('start: 35 Ask buttons', askButtons(root).length === 35, askButtons(root).length);
    const rest = find(root, (n) => n.getAttribute && n.getAttribute('id') === 'start-communities-rest')[0];
    check('start: the 15 hidden community rows have their Ask too', !!rest && askButtons(rest).length === 15, rest && askButtons(rest).length);
    const slots = byClass(root, 'start-action');
    check('start: every .start-action is "start-action dashboard-row-actions" with [main, Ask]', slots.length === 35
      && slots.every((s) => s.className === 'start-action dashboard-row-actions' && s.children.length === 2
        && s.children[0].matches('button.dashboard-link-btn') && s.children[1].matches('button.ask-about-btn')),
    slots.map((s) => s.className).slice(0, 3));
    check('start: Ask buttons carry data-start-action="ask"', askButtons(root).length === 35
      && askButtons(root).every((b) => b.getAttribute('data-start-action') === 'ask'));
    check('start: data-ask community / hub', askButtons(ct).length === 25 && askButtons(ct).every((b) => b.getAttribute('data-ask') === 'community')
      && askButtons(ht).length === 10 && askButtons(ht).every((b) => b.getAttribute('data-ask') === 'hub'));
    checkAnatomy('anatomy community', askIn(crows[0]), 'community', 'Ask about this: the Topic 1 full label community');
    checkAnatomy('anatomy hub', askIn(hrows[2]), 'hub', 'Ask about this: Entity 3');

    ct.dispatch('click', { target: askIn(crows[11]) || ct, detail: 1 });
    check('start: Ask in hidden row 12 asks about Topic 12', asked.length === 1 && asked[0].question === 'Summarize the Topic 12 full label community.'
      && asked[0].event && asked[0].event.detail === 1, asked.map((a) => a.question));
    check('start: the community Ask never shows the community', shown.length === 0, shown.length);
    ht.dispatch('click', { target: askIn(hrows[2]) || ht });
    check('start: hub 3 Ask asks about Entity 3', asked.length === 2
      && asked[1].question === 'What is Entity 3, and why is it so connected in this graph?', asked.map((a) => a.question));
    check('start: the hub Ask never shows the entity', shown.length === 0, shown.length);

    // A-4: the question comes from the cleaned row (collapsed fullLabel).
    const spaced = dash.buildStartHere({
      startHere: { communities: [community(1, { full_label: '  Full   one ', label: 'Short' })], hubs: [] },
      totalNodes: 5,
      onShowCommunity: () => {},
      onAsk: (question) => asked.push({ question }),
    });
    const st = byClass(spaced, 'start-communities-table')[0];
    asked.length = 0;
    st.dispatch('click', { target: askIn(byClass(st, 'dashboard-link-row')[0]) || st });
    check('start: the handler gets the cleaned row (collapsed full label)', asked.length === 1
      && asked[0].question === 'Summarize the Full one community.', asked.map((a) => a.question));

    // The question comes from the closure, not the DOM.
    const r1 = crows[1];
    const ask1 = askIn(r1);
    const main1 = byClass(r1, 'dashboard-link-btn')[0];
    main1.setAttribute('aria-label', 'evil');
    main1.setAttribute('title', 'evil');
    if (ask1) ask1.setAttribute('aria-label', 'evil');
    asked.length = 0;
    ct.dispatch('click', { target: ask1 || ct });
    check('start: tampered labels do not change the question', asked.length === 1
      && asked[0].question === 'Summarize the Topic 2 full label community.', asked.map((a) => a.question));

    const before = asked.length;
    const r2 = crows[2];
    for (const bad of ['-1', '1.5', '99']) {
      r2.setAttribute('data-index', bad);
      ct.dispatch('click', { target: askIn(r2) || ct });
    }
    r2.setAttribute('data-index', '2');
    check('start: a tampered data-index asks nothing and shows nothing', asked.length === before && shown.length === 0,
      { asked: asked.length - before, shown: shown.length });

    ct.dispatch('click', { target: main1 });
    ht.dispatch('click', { target: byClass(hrows[0], 'dashboard-link-btn')[0] });
    check('start: main buttons still show and do not ask', shown.length === 2 && shown[0].kind === 'community' && shown[0].row === comms[1]
      && shown[1].kind === 'entity' && shown[1].row === hs[0] && asked.length === before, { shown: shown.length, asked: asked.length - before });

    const toggle = byClass(root, 'start-toggle')[0];
    focusLog.length = 0;
    toggle.dispatch('click', { detail: 1 });
    const firstRestMain = byClass(byClass(rest, 'dashboard-link-row')[0], 'dashboard-link-btn')[0];
    check('start: Show all still focuses the row-11 main button', focusLog.length === 1 && focusLog[0].el === firstRestMain
      && classList(focusLog[0].el).includes('dashboard-link-btn'), focusLog.map((f) => f.el.className));
  });

  guarded('start without onAsk', () => {
    const plain = dash.buildStartHere({
      startHere: { communities: Array.from({ length: 12 }, (_, i) => community(i + 1)), hubs: [hub(1), hub(2)] },
      totalNodes: 50,
      onShowCommunity: () => {},
      onShowEntity: () => {},
    });
    check('start without onAsk: no Ask and no dashboard-row-actions', askButtons(plain).length === 0
      && byClass(plain, 'dashboard-row-actions').length === 0 && byClass(plain, 'start-action').every((s) => s.className === 'start-action'));
  });

  // --- Epistemic health ---
  const ent = (id, name, type = 'COMPOUND') => ({ id, name, entity_type: type });
  const GLP_EPI = {
    available: true,
    status_counts: [{ status: 'asserted', count: 758 }, { status: 'prophetic', count: 61 }],
    sections: [
      {
        key: 'contradictions', label: 'Contradictions', description: 'd', count: 2,
        items: [
          {
            title: 'semaglutide is indicated for Obesity', kind: 'contradiction',
            entities: [ent('compound:semaglutide', 'semaglutide'), ent('disease:obesity', 'Obesity', 'DISEASE')],
            statements: [{ text: 'Low', document: 'patent_x', confidence: 0.55 }], documents: ['patent_x'],
            question: 'Why do sources disagree on whether semaglutide is indicated for Obesity?',
          },
          { title: 'tirzepatide treats Diabetes', entities: [ent('compound:t', 't')], statements: [], documents: [], question: 'Q2?' },
        ],
      },
      {
        key: 'contested_claims', label: 'Contested claims', description: 'd', count: 7,
        items: Array.from({ length: 7 }, (_, i) => ({ title: `Claim ${i}`, entities: [], statements: [], documents: [], question: `Question ${i}?` })),
      },
    ],
  };
  guarded('epistemic', () => {
    const asked = [];
    const shown = [];
    const root = dash.buildEpistemicHealth({
      epistemic: GLP_EPI,
      onShowInGraph: (id, event) => shown.push({ id, event }),
      onAskInChat: (question, event) => asked.push({ question, event }),
    });
    const cards = byClass(root, 'epistemic-card');
    check('epistemic: nine cards', cards.length === 9, cards.length);
    const cardAsks = cards.map((c) => find(c, (n) => n.matches('button[data-action="ask-chat"]'))[0]);
    check('epistemic: every card Ask is epistemic-btn ask-about-btn with data-ask="epistemic"', cardAsks.every((b) => b
      && classList(b).includes('epistemic-btn') && classList(b).includes('ask-about-btn') && b.getAttribute('data-ask') === 'epistemic'
      && textOf(b) === 'Ask about this'), cardAsks.map((b) => b && [b.className, textOf(b)]));
    const first = cardAsks[0];
    checkAnatomy('anatomy epistemic', first, 'epistemic', 'Ask about this: semaglutide is indicated for Obesity', ['epistemic-btn']);
    check('epistemic: the card Ask keeps data-action, data-section and data-index', !!first && first.getAttribute('data-action') === 'ask-chat'
      && first.getAttribute('data-section') === 'contradictions' && first.getAttribute('data-index') === '0');
    const acts = byClass(cards[0], 'epistemic-actions')[0];
    check('epistemic: the Ask is second in .epistemic-actions, after Show in graph', !!acts && acts.children.length === 2
      && acts.children[0].getAttribute('data-action') === 'show-graph' && acts.children[1] === first);
    root.dispatch('click', { target: first, detail: 1 });
    check('epistemic: the card Ask asks the payload question verbatim', asked.length === 1
      && asked[0].question === 'Why do sources disagree on whether semaglutide is indicated for Obesity?' && asked[0].event.detail === 1
      && shown.length === 0, asked.map((a) => a.question));

    const statusAsks = find(root, (n) => n.matches('[data-ask="epistemic-status"]'));
    check('epistemic-status: exactly one status Ask', statusAsks.length === 1, statusAsks.length);
    const sAsk = statusAsks[0];
    checkAnatomy('anatomy epistemic-status', sAsk, 'epistemic-status', 'Ask about this: the epistemic status distribution');
    check('epistemic-status: data-action="ask-status"', !!sAsk && sAsk.getAttribute('data-action') === 'ask-status');
    const counts = byClass(root, 'epistemic-counts')[0];
    const ci = root.children.indexOf(counts);
    check('epistemic-status: the root child right after p.epistemic-counts', ci >= 0 && root.children[ci + 1] === sAsk && !!sAsk, ci);
    root.dispatch('click', { target: sAsk || root, detail: 0 });
    check('epistemic-status: a click asks the status question once, never shows', asked.length === 2 && asked[1].question === STATUS_Q
      && shown.length === 0, asked.map((a) => a.question));

    // 130-character title keeps the aria-label truncation; empty question falls back.
    const long = dash.buildEpistemicHealth({
      epistemic: {
        available: true, status_counts: [], sections: [{
          key: 'risks', label: 'Risks', description: 'd', count: 2,
          items: [
            { title: 'T'.repeat(130), entities: [], statements: [], documents: [], question: 'q' },
            { title: '', entities: [], statements: [], documents: [], question: '' },
          ],
        }],
      },
      onAskInChat: (question) => asked.push({ question }),
    });
    const longAsks = find(long, (n) => n.matches('button[data-action="ask-chat"]'));
    check('epistemic: a long title is truncated in the Ask aria-label', !!longAsks[0]
      && longAsks[0].getAttribute('aria-label') === `Ask about this: ${'T'.repeat(100)}...`, longAsks[0] && longAsks[0].getAttribute('aria-label'));
    asked.length = 0;
    long.dispatch('click', { target: longAsks[1] || long });
    check('epistemic: no question and no title asks about the section key', asked.length === 1
      && asked[0].question === 'What does the evidence say about: risks?', asked.map((a) => a.question));
    check('epistemic-status: no status Ask without status counts', find(long, (n) => n.matches('[data-ask="epistemic-status"]')).length === 0);

    const noSections = dash.buildEpistemicHealth({
      epistemic: { available: true, status_counts: [{ status: 'asserted', count: 4 }], sections: [] },
      onAskInChat: () => {},
    });
    const hint = byClass(noSections, 'epistemic-hint').find((h) => h.textContent === 'No contradictions, conflicts or hypotheses were found.');
    const hi = noSections.children.indexOf(hint);
    const nsAsk = find(noSections, (n) => n.matches('[data-ask="epistemic-status"]'))[0];
    check('epistemic-status: with no sections the Ask follows the "No contradictions..." hint', hi >= 0 && !!nsAsk
      && noSections.children[hi + 1] === nsAsk, hi);

    const bare = dash.buildEpistemicHealth({ epistemic: GLP_EPI });
    const bareAsks = find(bare, (n) => n.matches('button[data-action="ask-chat"]'));
    check('epistemic without onAskInChat: card Ask buttons are still there (A-3)', bareAsks.length === 9
      && bareAsks.every((b) => classList(b).includes('ask-about-btn')), bareAsks.length);
    check('epistemic without onAskInChat: no status Ask', find(bare, (n) => n.matches('[data-ask="epistemic-status"]')).length === 0);
    let threw = false;
    try { bare.dispatch('click', { target: bareAsks[0] || bare }); } catch { threw = true; }
    check('epistemic without onAskInChat: a card Ask click does not throw', !threw);
  });

  // --- Documents ---
  const mk = (i, extra = {}) => ({
    doc_id: `doc_${i}`, display_name: `Doc ${i}`, filename: `Doc ${i}.txt`,
    entity_count: 100 - i, relation_count: 50 - i, has_text: true, has_pdf: false, ...extra,
  });
  guarded('documents', () => {
    const asked = [];
    const opened = [];
    focusLog.length = 0;
    const docs = Array.from({ length: 34 }, (_, i) => mk(i + 1));
    const root = dash.buildDocuments({
      documents: docs,
      onOpen: (doc, event) => opened.push({ doc, event }),
      onAsk: (question, event) => asked.push({ question, event }),
    });
    const table = byTag(root, 'table')[0];
    const rows = byClass(root, 'dashboard-doc-row');
    check('documents: 34 Ask buttons', askButtons(root).length === 34, askButtons(root).length);
    const rest = find(root, (n) => n.getAttribute && n.getAttribute('id') === 'documents-rest')[0];
    check('documents: 24 of them in the hidden rows', !!rest && askButtons(rest).length === 24, rest && askButtons(rest).length);
    const cell0 = byClass(rows[0], 'dashboard-link-cell')[0];
    const wrap0 = cell0 && cell0.children.length === 1 ? cell0.children[0] : null;
    check('documents: first cell is div.dashboard-row-actions [main .dashboard-doc-btn, Ask]', !!wrap0 && wrap0.tagName === 'div'
      && wrap0.className === 'dashboard-row-actions' && wrap0.children.length === 2 && wrap0.children[0].matches('button.dashboard-doc-btn')
      && wrap0.children[1].matches('button.ask-about-btn'), cell0 && cell0.children.map((c) => c.className));
    checkAnatomy('anatomy document', askIn(rows[0]), 'document', 'Ask about this: Doc 1');
    table.dispatch('click', { target: askIn(rows[0]) || table, detail: 1 });
    check('documents: row 0 Ask asks about Doc 1 (doc_1)', asked.length === 1
      && asked[0].question === 'Summarize the document Doc 1 (doc_1): what are its key findings?' && asked[0].event.detail === 1,
    asked.map((a) => a.question));
    table.dispatch('click', { target: askIn(rows[19]) || table });
    check('documents: Ask in hidden row 20 asks and never opens', asked.length === 2
      && asked[1].question === 'Summarize the document Doc 20 (doc_20): what are its key findings?' && opened.length === 0,
    { asked: asked.map((a) => a.question), opened: opened.length });
    asked.length = 0;
    table.dispatch('click', { target: byClass(rows[2], 'dashboard-doc-btn')[0], detail: 1 });
    check('documents: the main button still opens and does not ask', opened.length === 1 && opened[0].doc === docs[2] && asked.length === 0,
      { opened: opened.length, asked: asked.length });

    const toggle = byClass(root, 'documents-toggle')[0];
    focusLog.length = 0;
    toggle.dispatch('click', { detail: 1 });
    check('documents: Show all still focuses the row-11 main button', focusLog.length === 1
      && focusLog[0].el === byClass(byClass(rest, 'dashboard-doc-row')[0], 'dashboard-doc-btn')[0], focusLog.map((f) => f.el.className));

    const odd = dash.buildDocuments({
      documents: [
        { doc_id: 'y', display_name: 'y', filename: 'y' },
        { doc_id: 'x', filename: 'Some Report.pdf' },
      ],
      onAsk: (question) => asked.push({ question }),
    });
    const ot = byTag(odd, 'table')[0];
    const orows = byClass(odd, 'dashboard-doc-row');
    asked.length = 0;
    ot.dispatch('click', { target: askIn(orows[0]) || ot });
    check('documents: a name equal to the id omits the parenthetical', asked.length === 1
      && asked[0].question === 'Summarize the document y: what are its key findings?', asked.map((a) => a.question));
    asked.length = 0;
    ot.dispatch('click', { target: askIn(orows[1]) || ot });
    check('documents: the filename fallback names the document', asked.length === 1
      && asked[0].question === 'Summarize the document Some Report.pdf (x): what are its key findings?', asked.map((a) => a.question));

    const plain = dash.buildDocuments({ documents: docs.slice(0, 3), onOpen: () => {} });
    check('documents without onAsk: Phase 8 markup (no wrapper, no Ask)', askButtons(plain).length === 0
      && byClass(plain, 'dashboard-row-actions').length === 0
      && byClass(plain, 'dashboard-link-cell').every((c) => c.children.length === 1 && c.children[0].matches('button.dashboard-doc-btn')));
  });

  // --- Near misses (10-REVIEW WR-01) ---
  // A click that lands on the row-actions wrapper itself (the Ask button's
  // margin, or the empty line beside a wrapped Ask) is not on any button: it
  // does nothing, in every table. Clicks elsewhere in the row still act.
  guarded('near miss', () => {
    const asked = [];
    const picked = [];
    const shown = [];
    const opened = [];
    const onAsk = (question) => asked.push(question);

    const summary = dash.buildEntitySummary({
      entityCounts: { A: 3, B: 10 }, totalNodes: 13, totalEdges: 2,
      onSelectType: (type) => picked.push(type), onShowAll: () => {}, onAsk,
    });
    const st = byTag(summary, 'table')[0];
    const sWrap = byClass(st, 'dashboard-row-actions')[0];
    st.dispatch('click', { target: sWrap || st, detail: 1 });
    check('near miss: the Entity Summary wrapper selects no type and asks nothing', !!sWrap && picked.length === 0 && asked.length === 0,
      { picked, asked });
    picked.length = 0;
    st.dispatch('click', { target: byClass(st, 'dashboard-count')[0], detail: 1 });
    check('near miss control: the Entity Summary count cell still selects its type', picked.length === 1, picked);

    const start = dash.buildStartHere({
      startHere: { communities: [community(1), community(2)], hubs: [hub(1), hub(2)] },
      totalNodes: 50,
      onShowCommunity: (row) => shown.push(['community', row.id]),
      onShowEntity: (row) => shown.push(['entity', row.id]),
      onAsk,
    });
    const ct = byClass(start, 'start-communities-table')[0];
    const ht = byClass(start, 'start-hubs-table')[0];
    const cWrap = byClass(ct, 'start-action')[0];
    const hWrap = byClass(ht, 'start-action')[0];
    ct.dispatch('click', { target: cWrap || ct, detail: 1 });
    ht.dispatch('click', { target: hWrap || ht, detail: 1 });
    check('near miss: the community and hub wrappers show nothing and ask nothing', !!cWrap && !!hWrap && shown.length === 0
      && asked.length === 0, { shown, asked });
    shown.length = 0;
    ht.dispatch('click', { target: byClass(ht, 'dashboard-count')[0], detail: 1 });
    check('near miss control: the hub count cell still shows the entity', shown.length === 1 && shown[0][0] === 'entity', shown);

    // The Phase 9 .start-action wrapper (no Ask) is a wrapper too.
    shown.length = 0;
    const plain = dash.buildStartHere({
      startHere: { communities: [community(1)], hubs: [] },
      totalNodes: 50,
      onShowCommunity: (row) => shown.push(['community', row.id]),
    });
    const pt = byClass(plain, 'start-communities-table')[0];
    pt.dispatch('click', { target: byClass(pt, 'start-action')[0] || pt, detail: 1 });
    check('near miss: a plain .start-action wrapper shows nothing', shown.length === 0, shown);
    shown.length = 0;
    pt.dispatch('click', { target: byClass(pt, 'dashboard-link-btn')[0], detail: 1 });
    check('near miss control: the plain community main button still shows', shown.length === 1, shown);

    const docs = dash.buildDocuments({
      documents: [{ doc_id: 'doc_1', display_name: 'Doc 1', filename: 'Doc 1.txt', entity_count: 3, relation_count: 1, has_text: true }],
      onOpen: (doc) => opened.push(doc.doc_id),
      onAsk,
    });
    const dt = byTag(docs, 'table')[0];
    const dWrap = byClass(dt, 'dashboard-row-actions')[0];
    dt.dispatch('click', { target: dWrap || dt, detail: 1 });
    check('near miss: the Documents wrapper opens nothing and asks nothing', !!dWrap && opened.length === 0 && asked.length === 0,
      { opened, asked });
    opened.length = 0;
    dt.dispatch('click', { target: byClass(dt, 'dashboard-count')[0], detail: 1 });
    check('near miss control: the Documents count cell still opens the document', opened.length === 1 && opened[0] === 'doc_1', opened);
  });

  // --- Hostile strings in every builder ---
  guarded('hostile', () => {
    const H = ['<img src=x onerror=1>', '"><script>alert(1)</script>'];
    createdTags.length = 0;
    innerHtmlWrites.length = 0;
    const asked = [];
    const onAsk = (question) => asked.push(question);
    const summary = dash.buildEntitySummary({ entityCounts: { [H[0]]: 2, [H[1]]: 1 }, totalNodes: 3, totalEdges: 1, onAsk });
    const start = dash.buildStartHere({
      startHere: { communities: [community(1, { full_label: H[0], label: H[1] })], hubs: [hub(1, { name: H[1] })] },
      totalNodes: 5, onAsk,
    });
    const docs = dash.buildDocuments({ documents: [mk(1, { display_name: H[0] })], onAsk });
    const epi = dash.buildEpistemicHealth({
      epistemic: { available: true, status_counts: [], sections: [{ key: 'risks', label: 'Risks', description: 'd', count: 1,
        items: [{ title: H[1], entities: [], statements: [], documents: [], question: '' }] }] },
      onAskInChat: onAsk,
    });
    const roots = [summary, start, docs, epi];
    check('hostile: no img or script element is created', !createdTags.includes('img') && !createdTags.includes('script'), createdTags);
    check('hostile: innerHTML is never assigned', innerHtmlWrites.length === 0, innerHtmlWrites);
    const arias = roots.flatMap((r) => askButtons(r).map((b) => b.getAttribute('aria-label')));
    const wantAria = [
      `Ask about this: ${H[0]} entities`, `Ask about this: ${H[1]} entities`,
      `Ask about this: the ${H[0]} community`, `Ask about this: ${H[1]}`,
      `Ask about this: ${H[0]}`, `Ask about this: ${H[1]}`,
    ];
    check('hostile: aria-labels hold the strings literally', wantAria.every((a) => arias.includes(a)), arias);
    const tableOf = (r, cls) => byClass(r, cls)[0];
    const clickAsk = (container) => { const b = askIn(container); if (b && container) container.dispatch('click', { target: b }); };
    clickAsk(tableOf(start, 'start-communities-table'));
    clickAsk(tableOf(start, 'start-hubs-table'));
    clickAsk(byTag(docs, 'table')[0]);
    const epiAsk = find(epi, (n) => n.matches('button[data-action="ask-chat"]'))[0];
    if (epiAsk) epi.dispatch('click', { target: epiAsk });
    const st = byTag(summary, 'table')[0];
    const sRow = byClass(st, 'dashboard-link-row').find((r) => r.getAttribute('data-entity-type') === H[0]);
    if (sRow && askIn(sRow)) st.dispatch('click', { target: askIn(sRow) });
    const wantQ = [
      `Summarize the ${H[0]} community.`,
      `What is ${H[1]}, and why is it so connected in this graph?`,
      `Summarize the document ${H[0]} (doc_1): what are its key findings?`,
      `What does the evidence say about: ${H[1]}?`,
      `What are the most important ${H[0]} entities in this graph, and how do they connect?`,
    ];
    check('hostile: questions hold the strings literally', JSON.stringify(asked) === JSON.stringify(wantQ), asked);
    let badClass = false;
    for (const r of roots) walk(r, (n) => { if (/[<>"]|onerror|script/i.test(String(n.className || ''))) badClass = true; });
    check('hostile: no data-derived class names', !badClass);
    check('hostile: the trees hold no img or script', roots.every((r) => find(r, (n) => n.tagName === 'img' || n.tagName === 'script').length === 0));
  });
}

if (MODE === 'findings') {
  if (typeof dash.buildFindings !== 'function') {
    check('buildFindings is exported by dashboard.js', false, typeof dash.buildFindings);
  } else {
    const FIXTURE = [
      { rule_name: '<img src=x onerror=1>', total: 1, errors: 0, by_severity: { low: 1 } },
      { rule_name: 'dosing_window_conflict', total: 3, errors: 0, by_severity: { high: 2, low: 1 } },
      { rule_name: 'label_gap', total: 1, errors: 1, by_severity: { medium: 1 } },
    ];
    const F = [...FIXTURE, null, 'x', { rule_name: '', total: 2 }, { rule_name: 7 }, { rule_name: 'no_counts' }];
    // The old app.js formula, kept here as the content reference.
    const oldCells = (f) => [
      f.errors ? String(f.rule_name) + ' (' + f.errors + ' rule error(s))' : String(f.rule_name),
      String(f.total || 0),
      Object.entries(f.by_severity || {}).map(([k, v]) => k + ': ' + v).join(', '),
    ];
    const kept = [...FIXTURE, { rule_name: 'no_counts' }];

    guarded('findings', () => {
      createdTags.length = 0;
      innerHtmlWrites.length = 0;
      const asked = [];
      const root = dash.buildFindings({ findings: F, onAsk: (question, event) => asked.push({ question, event }) });
      check('findings: section.findings-section labelled by the heading', !!root && root.tagName === 'section'
        && classList(root).includes('findings-section') && root.getAttribute('aria-labelledby') === 'findings-heading', root && root.className);
      const h3 = root.children[0];
      check('findings: first child h3#findings-heading "Analysis Findings"', !!h3 && h3.tagName === 'h3'
        && h3.getAttribute('id') === 'findings-heading' && h3.textContent === 'Analysis Findings', h3 && h3.textContent);
      const wrap = root.children[1];
      const table = wrap && wrap.children[0];
      check('findings: div.dashboard-table-wrap > table.dashboard-table.findings-table', !!wrap && wrap.matches('div.dashboard-table-wrap')
        && !!table && table.matches('table.dashboard-table.findings-table') && table.getAttribute('aria-labelledby') === 'findings-heading',
      [wrap && wrap.className, table && table.className]);
      const heads = byTag(root, 'th').map((t) => t.textContent);
      check('findings: headers Rule, Findings, By Severity', JSON.stringify(heads) === JSON.stringify(['Rule', 'Findings', 'By Severity']), heads);
      const body = byTag(root, 'tbody')[0];
      const rows = body ? byTag(body, 'tr') : [];
      check('findings: four rows with data-index 0..3', rows.length === 4 && rows.every((r, i) => r.getAttribute('data-index') === String(i)),
        rows.map((r) => r.getAttribute('data-index')));
      const cellsOf = (r) => {
        const tds = r.children.filter((c) => c.tagName === 'td');
        const rule = byClass(tds[0], 'findings-rule')[0];
        return [rule ? textOf(rule) : null, tds[1] ? textOf(tds[1]) : null, tds[2] ? textOf(tds[2]) : null];
      };
      const got = rows.map(cellsOf);
      const want = kept.map(oldCells);
      check('findings: cell texts equal the old table formula', JSON.stringify(got) === JSON.stringify(want), { got, want });
      check('findings: the reference values', JSON.stringify(want) === JSON.stringify([
        ['<img src=x onerror=1>', '1', 'low: 1'], ['dosing_window_conflict', '3', 'high: 2, low: 1'],
        ['label_gap (1 rule error(s))', '1', 'medium: 1'], ['no_counts', '0', '']]), want);
      const first = rows.map((r) => r.children[0]);
      check('findings: first cell td.findings-rule-cell > div.dashboard-row-actions [span.findings-rule, Ask]', first.length === 4
        && first.every((c) => c.matches('td.findings-rule-cell') && c.children.length === 1 && c.children[0].matches('div.dashboard-row-actions')
          && c.children[0].children.length === 2 && c.children[0].children[0].matches('span.findings-rule')
          && c.children[0].children[1].matches('button.ask-about-btn')), first.map((c) => c.children.map((x) => x.className)));
      checkAnatomy('anatomy finding', askIn(rows[2]), 'finding', 'Ask about this: the label_gap findings');
      table.dispatch('click', { target: askIn(rows[2]) || table, detail: 1 });
      check('findings: row 2 Ask asks about label_gap (1)', asked.length === 1
        && asked[0].question === 'Explain the label_gap findings (1): which ones matter most and why?' && asked[0].event.detail === 1,
      asked.map((a) => a.question));
      table.dispatch('click', { target: askIn(rows[1]) || table });
      check('findings: row 1 Ask asks about dosing_window_conflict (3)', asked.length === 2
        && asked[1].question === 'Explain the dosing_window_conflict findings (3): which ones matter most and why?', asked.map((a) => a.question));
      table.dispatch('click', { target: byClass(rows[0], 'findings-rule')[0] || table });
      table.dispatch('click', { target: rows[0].children[1] });
      table.dispatch('click', { target: table });
      check('findings: rule text, count cell and table clicks do nothing', asked.length === 2, asked.length);

      check('findings hostile: no img or script element is created', !createdTags.includes('img') && !createdTags.includes('script'), createdTags);
      check('findings hostile: innerHTML is never assigned', innerHtmlWrites.length === 0, innerHtmlWrites);
      check('findings hostile: the rule text is literal', got[0] && got[0][0] === '<img src=x onerror=1>', got[0]);
      let badClass = false;
      walk(root, (n) => { if (/[<>"]|onerror|script/i.test(String(n.className || ''))) badClass = true; });
      check('findings hostile: no data-derived class names', !badClass);
      check('findings: rows are not link rows', rows.every((r) => !classList(r).includes('dashboard-link-row')));
    });

    guarded('findings without onAsk', () => {
      const root = dash.buildFindings({ findings: F });
      const rows = byTag(byTag(root, 'tbody')[0], 'tr');
      check('findings without onAsk: no Ask and no wrapper', askButtons(root).length === 0 && byClass(root, 'dashboard-row-actions').length === 0);
      check('findings without onAsk: each first cell holds only span.findings-rule', rows.length === 4
        && rows.every((r) => r.children[0].children.length === 1 && r.children[0].children[0].matches('span.findings-rule')));
    });

    guarded('findings null', () => {
      for (const bad of [[], undefined, null, 'x', {}, [null, 'x', { rule_name: '' }]]) {
        check(`findings: ${JSON.stringify(bad)} returns null`, dash.buildFindings({ findings: bad, onAsk: () => {} }) === null);
      }
    });
  }
}

process.stdout.write(JSON.stringify({ passed, failed }) + '\n');
process.exit(failed.length ? 1 : 0);
