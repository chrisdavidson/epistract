// Headless-chromium click-through checks for the live workbench Dashboard.
//
// usage: node workbench_dashboard_cdp.mjs <cdp-port> <workbench-url> <mode> [screenshot-dir]
//   mode: click  full Dashboard -> Graph flow (rows, keyboard, mouse, sources, totals)
//         early  Dashboard click fired before the graph has finished loading
//         epistemic        GLP-1 v3 Epistemic health section: render, toggle, Show in graph, Ask about this
//         epistemic-early  Show in graph clicked before the graph has finished loading
//         epistemic-legacy legacy PICALM claims layer renders the section
//         documents        GLP-1 v3 Documents table and the in-workbench source viewer
//         card-highlight   GLP-1 v3 Epistemic card document id opens the viewer on the cited passage
//         citations        a stubbed chat reply with a document id becomes a link that opens the viewer
//         fda-highlight    FDA labels: a passage deep in an 80,000-character document is centred
//         start-here       GLP-1 v3 Where to start section: communities, hubs, narrow widths, click-through
//         start-here-early a community row clicked before the graph has finished loading
//         ask-about        GLP-1 v3 "Ask about this" on every card: counts, placement, prefill
//                          (mouse, Enter, Space), draft and Undo, textarea growth, narrow
//                          widths, styles, Present mode; no chat request is ever sent
//         ask-about-findings  GLP-1 v3 copy with custom findings: the Analysis Findings
//                          table and its Ask about this buttons
//         ask-guard        GLP-1 v3 "Ask about this" guards: a double-click, held Enter, near miss or press on Ask
//                          sends nothing, runs no row action and does not shade the row; a single starter click after the
//                          guard window still sends
//
// A run that cannot be judged because a third-party script did not load ends with
// a "skipped" reason in the final line instead of failures.
//
// Talks to an already running chromium over the DevTools protocol using only
// Node built-ins. Prints one JSON line per check and a final
// {"passed": n, "failed": [...]} line; exits 1 when any check fails.
import fs from 'node:fs';

const [PORT, URL_, MODE = 'click', SHOTS] = process.argv.slice(2);
if (!PORT || !URL_) {
  console.error('usage: workbench_dashboard_cdp.mjs <port> <url> <mode> [shot-dir]');
  process.exit(2);
}

const ORIGIN = new URL(URL_).origin;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const failures = [];
let passedCount = 0;
const check = (name, ok, val) => {
  console.log(JSON.stringify({ name, ok: Boolean(ok), val }));
  if (ok) passedCount += 1;
  else failures.push(name);
};

async function session() {
  const list = await (await fetch(`http://127.0.0.1:${PORT}/json/new?about:blank`, { method: 'PUT' })).json();
  const ws = new WebSocket(list.webSocketDebuggerUrl);
  await new Promise((r) => { ws.onopen = r; });
  let id = 0;
  const pend = {};
  const errors = [];
  const handlers = {};
  const on = (method, fn) => { handlers[method] = fn; };
  ws.onmessage = (e) => {
    const m = JSON.parse(e.data);
    if (m.id && pend[m.id]) pend[m.id](m.result ?? m.error);
    else if (m.method && handlers[m.method]) handlers[m.method](m.params);
    if (m.method === 'Runtime.exceptionThrown') {
      const d = m.params.exceptionDetails;
      // CDN script failures (offline runs) are not product errors; only
      // exceptions raised by scripts served from the workbench count.
      if (String(d.url || '').startsWith(ORIGIN)) errors.push('EXC ' + JSON.stringify(d).slice(0, 300));
    }
  };
  const send = (method, params = {}) => new Promise((r) => {
    const i = ++id;
    pend[i] = r;
    ws.send(JSON.stringify({ id: i, method, params }));
  });
  const ev = async (expr) => {
    const r = await send('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true });
    if (r.exceptionDetails) {
      console.log('EXC', JSON.stringify(r.exceptionDetails).slice(0, 400));
      errors.push('eval ' + expr.slice(0, 60));
    }
    return r.result?.value;
  };
  const shot = async (name) => {
    if (!SHOTS) return;
    const r = await send('Page.captureScreenshot', { format: 'png' });
    fs.writeFileSync(`${SHOTS}/${name}`, Buffer.from(r.data, 'base64'));
  };
  const mouse = (type, x, y) => send('Input.dispatchMouseEvent', {
    type, x, y, button: type === 'mouseMoved' ? 'none' : 'left',
    buttons: type === 'mousePressed' ? 1 : 0, clickCount: type === 'mouseMoved' ? 0 : 1,
  });
  const click = async (x, y) => {
    await mouse('mouseMoved', x, y);
    await mouse('mousePressed', x, y);
    await mouse('mouseReleased', x, y);
  };
  // A real double-click: two press/release pairs on one point, the second
  // with clickCount 2 (event.detail 2), `gap` ms apart.
  const dblclick = async (x, y, gap = 80) => {
    await mouse('mouseMoved', x, y);
    for (const n of [1, 2]) {
      await send('Input.dispatchMouseEvent', { type: 'mousePressed', x, y, button: 'left', buttons: 1, clickCount: n });
      await send('Input.dispatchMouseEvent', { type: 'mouseReleased', x, y, button: 'left', buttons: 0, clickCount: n });
      if (n === 1) await sleep(gap);
    }
  };
  const KEYS = {
    Escape: { code: 27 },
    Tab: { code: 9 },
    Enter: { code: 13, text: '\r' },
    Space: { code: 32, key: ' ', codeName: 'Space', text: ' ' },
  };
  const key = async (k) => {
    const def = KEYS[k];
    const p = { key: def.key ?? k, code: def.codeName ?? k, windowsVirtualKeyCode: def.code };
    await send('Input.dispatchKeyEvent', { type: def.text ? 'keyDown' : 'rawKeyDown', ...p, ...(def.text ? { text: def.text } : {}) });
    await send('Input.dispatchKeyEvent', { type: 'keyUp', ...p });
  };
  await send('Page.enable');
  await send('Runtime.enable');
  await send('Network.enable');
  await send('Network.setCacheDisabled', { cacheDisabled: true });
  const viewport = (width, height) => send('Emulation.setDeviceMetricsOverride', {
    width, height, deviceScaleFactor: 1, mobile: false,
  });
  const waitFor = async (expr, cap = 15000) => {
    const t0 = Date.now();
    while (Date.now() - t0 < cap) {
      if (await ev(expr)) return true;
      await sleep(100);
    }
    return false;
  };
  const done = async () => {
    try { await fetch(`http://127.0.0.1:${PORT}/json/close/${list.id}`); } catch { /* already gone */ }
    ws.close();
  };
  return { send, on, ev, shot, mouse, click, dblclick, key, viewport, waitFor, errors, done };
}

const q = (sel) => JSON.stringify(sel);
const sameSet = (a, b) => a.length === b.length && new Set(a).size === a.length && b.every((x) => new Set(a).has(x));

const visibleIds = `(() => window._graphDebug.dataNodes().filter((n) => !n.hidden).map((n) => n.id))()`;
const pressedChips = `(() => [...document.querySelectorAll('.legend-chip[data-type]')]
  .filter((c) => c.getAttribute('aria-pressed') === 'true').map((c) => c.getAttribute('data-type')))()`;
const SOURCE = ['DOCUMENT', 'PUBLICATION'];

async function expectedSets(s) {
  return s.ev(`(async () => {
    const g = await (await fetch('/api/graph')).json();
    const byType = {};
    for (const n of g.nodes) (byType[n.entity_type] ||= []).push(n.id);
    return byType;
  })()`);
}

async function openDashboard(s) {
  await s.ev(`document.querySelector('.nav-link[data-panel=dashboard]').click()`);
  return s.waitFor(`document.querySelectorAll('.dashboard-entity-summary .dashboard-link-btn').length > 0`);
}

// Waits until the graph is built and the visible node set equals `want`.
async function waitVisible(s, want) {
  const wantJson = JSON.stringify([...want].sort());
  const ok = await s.waitFor(`(() => { const g = window._graphDebug; if (!g) return false;
    const v = ${visibleIds}; return JSON.stringify(v.slice().sort()) === ${q(wantJson)}; })()`);
  await s.ev(`new Promise((r) => setTimeout(r, 500))`);
  return ok;
}

async function load(s) {
  await s.viewport(1440, 1000);
  await s.send('Page.navigate', { url: URL_ });
  await s.waitFor(`!!window._graphDebug && !!document.querySelector('.nav-link[data-panel=dashboard]')`, 30000);
  await s.waitFor(`window._graphDebug && window._graphDebug.settled`, 30000);
}

async function click() {
  const s = await session();
  await load(s);
  const sets = await expectedSets(s);
  const nonSource = Object.entries(sets).filter(([t]) => !SOURCE.includes(t)).flatMap(([, ids]) => ids);

  check('dashboard opens with rows', await openDashboard(s));
  await s.shot('dashboard.png');

  // (a) rows
  const rows = await s.ev(`(() => [...document.querySelectorAll('.dashboard-entity-summary .dashboard-link-btn')].map((b) => ({
    type: b.getAttribute('data-entity-type'),
    count: Number(b.closest('tr').querySelector('td.dashboard-count').textContent.replace(/,/g, '')),
    cell: b.closest('tr').querySelector('td.dashboard-count').textContent.trim(),
    swatch: !!b.querySelector('svg.type-swatch'),
    aria: b.getAttribute('aria-label'),
  })))()`);
  check('13 dashboard rows', rows.length === 13, rows.length);
  check('DISEASE first', rows[0] && rows[0].type === 'DISEASE', rows[0]);
  check('counts non-increasing', rows.every((r, i) => i === 0 || rows[i - 1].count >= r.count));
  check('DISEASE cell shows 48', rows[0] && rows[0].cell === '48', rows[0]);
  check('every row has a swatch', rows.every((r) => r.swatch));
  check('aria-labels match', rows.every((r) => /^Show \d[\d,]* .+ nodes? in the graph$/.test(r.aria || '')), rows.map((r) => r.aria).slice(0, 2));

  // (b) no injected markup
  const inj = await s.ev(`document.querySelectorAll('#dashboard-content img, #dashboard-content script').length`);
  check('no img/script in dashboard', inj === 0, inj);

  // (c) keyboard: real Enter on the COMPOUND button
  await s.ev(`document.querySelector('.dashboard-entity-summary .dashboard-link-btn[data-entity-type="COMPOUND"]').focus()`);
  await s.key('Enter');
  check('Enter shows graph panel', await s.waitFor(`document.getElementById('graph-panel').style.display === 'flex'`));
  check('COMPOUND solo visible set', await waitVisible(s, sets.COMPOUND), (await s.ev(visibleIds)).length);
  check('COMPOUND count is 33', sets.COMPOUND.length === 33, sets.COMPOUND.length);
  check('only COMPOUND chip pressed', JSON.stringify(await s.ev(pressedChips)) === '["COMPOUND"]', await s.ev(pressedChips));
  const status = await s.ev(`document.getElementById('graph-sources-status').textContent`);
  check('status starts "Showing 33 "', status.startsWith('Showing 33 '), status);
  check('focus moved to graph container', (await s.ev(`document.activeElement && document.activeElement.id`)) === 'graph-container');
  await s.shot('graph-solo.png');

  // (d) stale state, then a real mouse click on the count cell. Focus is entered
  // first, from the default view (a solo COMPOUND view has no node with a visible
  // neighbour), and must survive the dirty filters, so the arrival really has to
  // leave focus through the live vis-network.
  await s.ev(`window.dispatchEvent(new CustomEvent('graph-show-types', { detail: { reset: true } }))`);
  await s.waitFor(`!window._graphDebug.busy`);
  const centre = await s.ev(`(() => {
    for (const n of window._graphDebug.dataNodes().filter((d) => !d.hidden)) {
      window.dispatchEvent(new CustomEvent('graph-focus-node', { detail: { id: n.id, hops: 1 } }));
      if (window._graphDebug.focus().stack.length > 0) return { id: n.id };
    }
    return null;
  })()`);
  check('setup: a focus centre was found', !!centre, centre);
  await s.waitFor(`!window._graphDebug.busy`);
  const before = await s.ev(`({ size: window._graphDebug.focus().size,
    sidebarOpen: !document.getElementById('graph-detail-sidebar').classList.contains('graph-detail-sidebar--closed') })`);
  check('setup: focus active', before.size > 0, before);
  check('setup: focus opened the sidebar', before.sidebarOpen, before);
  // The search term is the centre's own name, so the centre stays eligible and
  // focus is kept while the search and min-degree filters are dirty.
  const centreName = await s.ev(`(async () => {
    const g = await (await fetch('/api/graph')).json();
    const n = g.nodes.find((x) => x.id === ${q(centre ? centre.id : '')});
    return n ? String(n.name || '') : '';
  })()`);
  await s.ev(`(() => {
    const se = document.getElementById('graph-search'); se.value = ${q(centreName)}; se.dispatchEvent(new Event('input', { bubbles: true }));
    const sl = document.getElementById('min-degree-slider'); sl.value = '1'; sl.dispatchEvent(new Event('input', { bubbles: true }));
  })()`);
  await sleep(800);
  const dirty = await s.ev(`({ stack: window._graphDebug.focus().stack.length, search: document.getElementById('graph-search').value,
    slider: document.getElementById('min-degree-slider').value })`);
  check('setup: focus survives the dirty filters', dirty.stack > 0 && dirty.search !== '' && dirty.slider === '1', dirty);
  check('open dashboard again', await openDashboard(s));
  check('dashboard still lists 13 rows', (await s.ev(`document.querySelectorAll('.dashboard-entity-summary .dashboard-link-btn').length`)) === 13);
  const pt = await s.ev(`(() => { const r = document.querySelector('.dashboard-entity-summary tr.dashboard-link-row[data-entity-type="DISEASE"] td.dashboard-count').getBoundingClientRect();
    return { x: r.left + r.width / 2, y: r.top + r.height / 2 }; })()`);
  await s.click(pt.x, pt.y);
  check('DISEASE solo visible set', await waitVisible(s, sets.DISEASE), sets.DISEASE.length);
  check('DISEASE count is 48', sets.DISEASE.length === 48);
  const reset = await s.ev(`({ search: document.getElementById('graph-search').value,
    slider: document.getElementById('min-degree-slider').value,
    readout: document.getElementById('min-degree-value').textContent,
    focus: window._graphDebug.focus().size, stack: window._graphDebug.focus().stack.length,
    sidebarClosed: document.getElementById('graph-detail-sidebar').classList.contains('graph-detail-sidebar--closed') })`);
  check('search cleared', reset.search === '', reset);
  check('min-degree reset', reset.slider === '0' && reset.readout === '0', reset);
  check('focus cleared', reset.focus === 0 && reset.stack === 0, reset);
  check('sidebar closed on arrival', reset.sidebarClosed, reset);
  check('only DISEASE chip pressed', JSON.stringify(await s.ev(pressedChips)) === '["DISEASE"]', await s.ev(pressedChips));

  // (e) source type
  check('open dashboard for DOCUMENT', await openDashboard(s));
  await s.ev(`document.querySelector('.dashboard-entity-summary .dashboard-link-btn[data-entity-type="DOCUMENT"]').click()`);
  check('DOCUMENT solo visible set', await waitVisible(s, sets.DOCUMENT), sets.DOCUMENT.length);
  check('DOCUMENT count is 34', sets.DOCUMENT.length === 34);
  check('Show sources pressed', (await s.ev(`document.getElementById('graph-show-sources-btn').getAttribute('aria-pressed')`)) === 'true');

  // (f) totals -> default view
  check('open dashboard for totals', await openDashboard(s));
  await s.ev(`document.querySelector('.dashboard-totals-btn').click()`);
  check('totals shows 218 non-source nodes', await waitVisible(s, nonSource), nonSource.length);
  check('218 non-source nodes', nonSource.length === 218, nonSource.length);
  const chips = await s.ev(`(() => Object.fromEntries([...document.querySelectorAll('.legend-chip[data-type]')]
    .map((c) => [c.getAttribute('data-type'), c.getAttribute('aria-pressed')])))()`);
  check('source chips off', SOURCE.every((t) => chips[t] === 'false'), chips);
  check('other 11 chips on', Object.entries(chips).filter(([t]) => !SOURCE.includes(t)).length === 11
    && Object.entries(chips).filter(([t]) => !SOURCE.includes(t)).every(([, v]) => v === 'true'), chips);
  const st = await s.ev(`document.getElementById('graph-sources-status').textContent`);
  check('default-graph announcement', st === 'Showing the default graph: 218 entities.', st);
  await s.shot('graph-default.png');

  // (h)
  check('no script exceptions from the workbench', s.errors.length === 0, s.errors.slice(0, 3));
  await s.done();
}

async function early() {
  const s = await session();
  await s.viewport(1440, 1000);
  // Hold the /api/graph response until the Dashboard click has fired, so the
  // click always lands before the graph exists and must take the queue path
  // (requestShowTypes -> flushPendingShowTypes), whatever the machine speed.
  // Only the exact /api/graph URL is paused; claims and groups load normally.
  const held = [];
  let released = false;
  s.on('Fetch.requestPaused', (p) => {
    if (released) s.send('Fetch.continueRequest', { requestId: p.requestId });
    else held.push(p.requestId);
  });
  await s.send('Fetch.enable', { patterns: [{ urlPattern: '*/api/graph', requestStage: 'Request' }] });
  // Click the COMPOUND row as soon as the Dashboard renders it, recording
  // whether the graph had finished loading at that moment.
  await s.send('Page.addScriptToEvaluateOnNewDocument', { source: `
    document.addEventListener('DOMContentLoaded', () => {
      const t = setInterval(() => {
        const b = document.querySelector('.dashboard-entity-summary .dashboard-link-btn[data-entity-type="COMPOUND"]');
        if (!b) return;
        clearInterval(t);
        window.__early = { graphReady: !!window._graphDebug };
        b.click();
      }, 1);
    });` });
  await s.send('Page.navigate', { url: URL_ });
  check('early click fired', await s.waitFor(`!!window.__early`, 30000), await s.ev(`window.__early`));
  const early = await s.ev(`window.__early`);
  check('early click: made before the graph loaded', early && early.graphReady === false, early);
  check('early click: /api/graph was held until the click', held.length > 0, held.length);
  check('early click: graph not built while held', (await s.ev(`!window._graphDebug`)) === true);
  released = true;
  for (const requestId of held.splice(0)) await s.send('Fetch.continueRequest', { requestId });
  await s.send('Fetch.disable');
  await s.waitFor(`!!window._graphDebug && window._graphDebug.settled`, 30000);
  const sets = await expectedSets(s);
  check('early click: COMPOUND solo visible set', await waitVisible(s, sets.COMPOUND), (await s.ev(visibleIds)).length);
  check('early click: only COMPOUND chip pressed', JSON.stringify(await s.ev(pressedChips)) === '["COMPOUND"]', await s.ev(pressedChips));
  check('early click: graph panel shown', (await s.ev(`document.getElementById('graph-panel').style.display`)) === 'flex');
  check('early click: no script exceptions', s.errors.length === 0, s.errors.slice(0, 3));
  await s.done();
}

// --- Epistemic health ------------------------------------------------------

async function openEpistemic(s) {
  await s.ev(`document.querySelector('.nav-link[data-panel=dashboard]').click()`);
  const ok = await s.waitFor(`!!document.querySelector('.epistemic-health')`);
  await s.ev(`document.querySelector('.epistemic-health').scrollIntoView({ block: 'start', behavior: 'instant' })`);
  return ok;
}

// In-page expression for a section's buttons: key is a fixed section key.
const secBtn = (key, action, nth = 0) => `document.querySelector('#epistemic-sec-${key}').parentElement`
  + `.querySelectorAll('[data-action="${action}"]')[${nth}]`;

// Scrolls the element to the middle of the viewport and returns its centre.
async function centreOf(s, expr) {
  return s.ev(`(() => { const b = ${expr}; if (!b) return null;
    b.scrollIntoView({ block: 'center', behavior: 'instant' });
    const r = b.getBoundingClientRect(); return { x: r.left + r.width / 2, y: r.top + r.height / 2 }; })()`);
}

async function clickEl(s, expr) {
  const pt = await centreOf(s, expr);
  if (!pt) return false;
  await s.click(pt.x, pt.y);
  return true;
}

const focusTop = `(() => { const st = window._graphDebug.focus().stack; return st.length ? st[st.length - 1].id : null; })()`;

async function epistemic() {
  const s = await session();
  await load(s);
  check('dashboard opens with the epistemic section', await openEpistemic(s));

  // (1) heading order
  const heads = await s.ev(`[...document.querySelectorAll('#dashboard-content h3')].map((h) => h.textContent)`);
  const iEnt = heads.indexOf('Entity Summary');
  const iStart = heads.indexOf('Where to start');
  const iEpi = heads.indexOf('Epistemic health');
  const iFind = heads.indexOf('Analysis Findings');
  // Dashboard order: Entity Summary, Where to start, Epistemic health, ... Findings
  // (the Where to start section sits between the Entity Summary and this one).
  check('heading sits right after Entity Summary and before Analysis Findings',
    iEnt >= 0 && iStart === iEnt + 1 && iEpi === iStart + 1 && (iFind === -1 || iFind > iEpi), heads);

  // (2) chips
  const chips = await s.ev(`[...document.querySelectorAll('.epistemic-health .epistemic-chip')].map((c) => c.textContent.replace(/\\s+/g, ' ').trim())`);
  check('six status chips', chips.length === 6, chips);
  check('chip order and shares', chips[0] === 'Asserted 758 89%' && chips[1] === 'Prophetic 61 7%' && chips[2] === 'Hypothesized 31 4%'
    && chips.slice(3).every((c) => c.endsWith(' <1%')), chips);
  check('status caption', (await s.ev(`document.querySelector('.epistemic-status .epistemic-hint').textContent`)) === 'Epistemic status of 855 relations');

  // (3) tiny segment stays visible
  const negW = await s.ev(`(() => { const seg = [...document.querySelectorAll('.epistemic-bar__seg')].find((x) => x.title.startsWith('Negative'));
    return seg ? seg.getBoundingClientRect().width : -1; })()`);
  check('negative segment is at least 6px wide', negW >= 6, negW);

  // (4) counts
  check('counts line', (await s.ev(`document.querySelector('.epistemic-counts').textContent`)) === '2 contradictions · 33 contested claims · 2 hypotheses');

  // (5) card counts
  const vis = (key) => s.ev(`(() => { const sec = document.querySelector('#epistemic-sec-${key}').parentElement;
    return [...sec.querySelectorAll('.epistemic-card')].filter((c) => c.offsetParent !== null).length; })()`);
  check('contradictions: 2 cards', (await vis('contradictions')) === 2);
  check('hypotheses: 2 cards and no toggle', (await vis('hypotheses')) === 2
    && (await s.ev(`!document.querySelector('#epistemic-sec-hypotheses').parentElement.querySelector('.epistemic-toggle')`)));
  check('contested: 5 visible cards', (await vis('contested_claims')) === 5);
  const tgText = await s.ev(`document.querySelector('#epistemic-sec-contested_claims').parentElement.querySelector('.epistemic-toggle').textContent`);
  check('contested toggle reads Show all 33', tgText === 'Show all 33', tgText);

  // screenshot before the toggle moves things
  await s.ev(`document.querySelector('.epistemic-health').scrollIntoView({ block: 'start', behavior: 'instant' })`);
  await s.shot('dashboard-epistemic.png');

  // (6) toggle with a real mouse click
  const toggleExpr = `document.querySelector('#epistemic-sec-contested_claims').parentElement.querySelector('.epistemic-toggle')`;
  check('toggle clicked', await clickEl(s, toggleExpr));
  check('toggle expands', (await s.ev(`${toggleExpr}.getAttribute('aria-expanded')`)) === 'true'
    && (await vis('contested_claims')) === 33, await vis('contested_claims'));
  check('toggle keeps focus', (await s.ev(`document.activeElement === ${toggleExpr}`)) === true);
  check('toggle label flips', (await s.ev(`${toggleExpr}.textContent`)) === 'Show first 5');
  await s.shot('dashboard-epistemic-expanded.png');
  await clickEl(s, toggleExpr);
  check('toggle collapses again', (await vis('contested_claims')) === 5 && (await s.ev(`${toggleExpr}.getAttribute('aria-expanded')`)) === 'false');

  // (7) quotes
  const quotes = await s.ev(`(() => [...document.querySelectorAll('.epistemic-card')].map((c) => {
    const qs = [...c.querySelectorAll('.epistemic-quote')];
    return { n: qs.length, clamp: qs.map((q) => getComputedStyle(q).webkitLineClamp) };
  }))()`);
  check('at most two quotes per card, clamped to 3 lines', quotes.every((c) => c.n <= 2 && c.clamp.every((v) => v === '3')) && quotes.some((c) => c.n === 2), quotes.slice(0, 3));

  // (8) hypothesis card
  const hyp = await s.ev(`(() => { const card = document.querySelector('#epistemic-sec-hypotheses').parentElement.querySelector('.epistemic-card');
    return [...card.querySelectorAll('.epistemic-meta')].map((m) => m.textContent); })()`);
  check('hypothesis card: capped entities', hyp.some((m) => m.startsWith('Entities:') && m.includes('+') && m.includes('more')), hyp);
  check('hypothesis card: Sources line', hyp.some((m) => m.startsWith('Sources:')), hyp);

  // (9) type scale
  const type = await s.ev(`(() => {
    const bad = [];
    for (const n of document.querySelectorAll('.epistemic-health, .epistemic-health *')) {
      const own = [...n.childNodes].some((c) => c.nodeType === 3 && c.textContent.trim());
      if (!own) continue;
      const cs = getComputedStyle(n);
      if (!['13px', '14px', '15px'].includes(cs.fontSize) || !['400', '600'].includes(cs.fontWeight)) {
        bad.push([n.tagName, n.className, cs.fontSize, cs.fontWeight]);
      }
    }
    return bad;
  })()`);
  check('only 13/14/15px sizes and 400/600 weights', type.length === 0, type.slice(0, 4));

  // (10) Show in graph, settled graph, real mouse click
  const firstGraph = secBtn('contradictions', 'show-graph', 0);
  check('Show in graph is enabled for the first contradiction', (await s.ev(`${firstGraph}.getAttribute('aria-disabled')`)) === null);
  check('Show in graph clicked', await clickEl(s, firstGraph));
  check('graph panel shown', await s.waitFor(`document.getElementById('graph-panel').style.display === 'flex'`));
  check('graph focused on semaglutide', await s.waitFor(`(${focusTop}) === 'compound:semaglutide'`), await s.ev(focusTop));
  check('the focus layout settles', await s.waitFor(`!window._graphDebug.busy`));
  const fsize = await s.ev(`window._graphDebug.focus().size`);
  check('focus set has at least two nodes', fsize >= 2, fsize);
  check('graph search is empty', (await s.ev(`document.getElementById('graph-search').value`)) === '');
  await s.ev(`new Promise((r) => setTimeout(r, 600))`);
  await s.shot('graph-focus-semaglutide.png');

  // (11) keyboard activation moves focus to the graph. Restore the default
  // view first so the focus check below can only pass if Enter dispatched it.
  await s.ev(`window.dispatchEvent(new CustomEvent('graph-show-types', { detail: { reset: true } }))`);
  check('setup: the reset leaves focus mode', await s.waitFor(`(${focusTop}) === null`), await s.ev(focusTop));
  check('setup: the reset layout settles', await s.waitFor(`!window._graphDebug.busy`));
  check('open the dashboard again', await openEpistemic(s));
  check('setup: still no focus before Enter', (await s.ev(focusTop)) === null, await s.ev(focusTop));
  await s.ev(`${firstGraph}.scrollIntoView({ block: 'center', behavior: 'instant' }); ${firstGraph}.focus()`);
  check('setup: the Show in graph button has keyboard focus', (await s.ev(`document.activeElement === ${firstGraph}`)) === true);
  await s.key('Enter');
  check('Enter focuses the graph container', await s.waitFor(`document.activeElement && document.activeElement.id === 'graph-container'`));
  check('Enter enters focus on semaglutide', await s.waitFor(`(${focusTop}) === 'compound:semaglutide'`), await s.ev(focusTop));
  check('the keyboard focus layout settles', await s.waitFor(`!window._graphDebug.busy`));
  check('keyboard focus centre is still semaglutide', (await s.ev(focusTop)) === 'compound:semaglutide', await s.ev(focusTop));

  // (12) Ask about this only prefills
  const urls = [];
  s.on('Network.requestWillBeSent', (p) => urls.push(p.request.url));
  const expectedQ = await s.ev(`(async () => { const d = await (await fetch('/api/dashboard')).json();
    return d.epistemic.sections[0].items[0].question; })()`);
  check('the API supplies a question', typeof expectedQ === 'string' && expectedQ.length > 0, expectedQ);
  check('open the dashboard for chat', await openEpistemic(s));
  urls.length = 0;
  check('Ask about this clicked', await clickEl(s, secBtn('contradictions', 'ask-chat', 0)));
  check('chat panel shown', await s.waitFor(`document.querySelector('.chat-panel').style.display === 'flex'`));
  check('chat input holds the question', (await s.ev(`document.getElementById('chat-input').value`)) === expectedQ,
    await s.ev(`document.getElementById('chat-input').value`));
  check('chat input has focus', (await s.ev(`document.activeElement && document.activeElement.id`)) === 'chat-input');
  await s.ev(`new Promise((r) => setTimeout(r, 1000))`);
  check('no /api/chat request was made', !urls.some((u) => u.includes('/api/chat')), urls.filter((u) => u.includes('/api/')));
  await s.shot('chat-prefilled.png');

  // (12b) a draft in the chat box is replaced as an edit that Undo restores
  const draft = 'my own unsent draft';
  await s.ev(`(() => { const i = document.getElementById('chat-input'); i.focus(); i.select(); })()`);
  await s.send('Input.insertText', { text: draft });
  check('setup: the draft is typed', (await s.ev(`document.getElementById('chat-input').value`)) === draft,
    await s.ev(`document.getElementById('chat-input').value`));
  const secondQ = await s.ev(`(async () => { const d = await (await fetch('/api/dashboard')).json();
    return d.epistemic.sections[0].items[1].question; })()`);
  check('open the dashboard with a draft', await openEpistemic(s));
  urls.length = 0;
  check('Ask about this clicked over a draft', await clickEl(s, secBtn('contradictions', 'ask-chat', 1)));
  check('chat panel shown again', await s.waitFor(`document.querySelector('.chat-panel').style.display === 'flex'`));
  check('the question replaces the draft', (await s.ev(`document.getElementById('chat-input').value`)) === secondQ,
    await s.ev(`document.getElementById('chat-input').value`));
  const undone = await s.ev(`(() => { const i = document.getElementById('chat-input'); i.focus();
    document.execCommand('undo'); return i.value; })()`);
  check('Undo brings the draft back', undone === draft, undone);
  check('no /api/chat request was made for the draft case', !urls.some((u) => u.includes('/api/chat')), urls.filter((u) => u.includes('/api/')));

  // (13)
  check('no script exceptions from the workbench', s.errors.length === 0, s.errors.slice(0, 3));
  await s.done();
}

async function epistemicEarly() {
  const s = await session();
  await s.viewport(1440, 1000);
  const held = [];
  let released = false;
  s.on('Fetch.requestPaused', (p) => {
    if (released) s.send('Fetch.continueRequest', { requestId: p.requestId });
    else held.push(p.requestId);
  });
  await s.send('Fetch.enable', { patterns: [{ urlPattern: '*/api/graph', requestStage: 'Request' }] });
  await s.send('Page.addScriptToEvaluateOnNewDocument', { source: `
    document.addEventListener('DOMContentLoaded', () => {
      const t = setInterval(() => {
        const b = document.querySelector('.epistemic-btn[data-action="show-graph"]');
        if (!b) return;
        clearInterval(t);
        window.__early = { graphReady: !!window._graphDebug };
        b.click();
      }, 1);
    });` });
  await s.send('Page.navigate', { url: URL_ });
  check('early Show in graph click fired', await s.waitFor(`!!window.__early`, 30000), await s.ev(`window.__early`));
  const early = await s.ev(`window.__early`);
  check('early click: made before the graph loaded', early && early.graphReady === false, early);
  check('early click: /api/graph was held until the click', held.length > 0, held.length);
  check('early click: graph not built while held', (await s.ev(`!window._graphDebug`)) === true);
  released = true;
  for (const requestId of held.splice(0)) await s.send('Fetch.continueRequest', { requestId });
  await s.send('Fetch.disable');
  await s.waitFor(`!!window._graphDebug && window._graphDebug.settled`, 30000);
  check('early click: graph panel shown', (await s.ev(`document.getElementById('graph-panel').style.display`)) === 'flex');
  check('early click: graph focused on semaglutide', await s.waitFor(`window._graphDebug && (${focusTop}) === 'compound:semaglutide'`, 30000), await s.ev(focusTop));
  check('early click: no script exceptions', s.errors.length === 0, s.errors.slice(0, 3));
  await s.done();
}

async function epistemicLegacy() {
  const s = await session();
  await load(s);
  check('dashboard opens with the epistemic section', await openEpistemic(s));
  check('legacy counts line', (await s.ev(`document.querySelector('.epistemic-counts').textContent`)) === '1 contradiction · 1 hypothesis',
    await s.ev(`document.querySelector('.epistemic-counts') && document.querySelector('.epistemic-counts').textContent`));
  const quotes = await s.ev(`document.querySelector('#epistemic-sec-contradictions').parentElement.querySelector('.epistemic-card').querySelectorAll('.epistemic-quote').length`);
  check('the contradiction card shows both statements', quotes === 2, quotes);
  const chips = await s.ev(`[...document.querySelectorAll('.epistemic-health .epistemic-chip')].map((c) => c.textContent.trim())`);
  check('a Contested chip exists', chips.some((c) => c.startsWith('Contested')), chips);
  check('Show in graph is enabled', (await s.ev(`${secBtn('contradictions', 'show-graph', 0)}.getAttribute('aria-disabled')`)) === null);
  await s.ev(`document.querySelector('.epistemic-health').scrollIntoView({ block: 'start', behavior: 'instant' })`);
  await s.shot('dashboard-epistemic-picalm.png');
  check('legacy: no script exceptions', s.errors.length === 0, s.errors.slice(0, 3));
  await s.done();
}

// --- Documents and the source viewer ----------------------------------------

const DOC_BTN = '.documents-table .dashboard-doc-btn';
const docRows = `[...document.querySelectorAll('.documents-table tbody tr.dashboard-doc-row')]`;
const visibleDocRows = `${docRows}.filter((r) => r.offsetParent !== null)`;

async function openDocuments(s) {
  await s.ev(`document.querySelector('.nav-link[data-panel=dashboard]').click()`);
  return s.waitFor(`document.querySelectorAll('${DOC_BTN}').length > 0`);
}

const panelDisplay = (s, sel) => s.ev(`getComputedStyle(document.querySelector(${q(sel)})).display`);

async function documents() {
  const s = await session();
  await load(s);
  check('dashboard opens with the documents table', await openDocuments(s));

  const api = await s.ev(`(async () => (await (await fetch('/api/dashboard')).json()).documents)()`);
  check('the API returns 34 documents', Array.isArray(api) && api.length === 34, api && api.length);

  // (1) placement and heading
  const heads = await s.ev(`[...document.querySelectorAll('#dashboard-content h3')].map((h) => h.textContent)`);
  const iEpi = heads.indexOf('Epistemic health');
  const iDocs = heads.indexOf('Documents (34)');
  const iFind = heads.indexOf('Analysis Findings');
  check('Documents (34) sits after Epistemic health and before Analysis Findings',
    iEpi >= 0 && iDocs > iEpi && (iFind === -1 || iFind > iDocs), heads);

  // (2) rows
  const visible = await s.ev(`${visibleDocRows}.length`);
  check('10 rows are visible', visible === 10, visible);
  const rows = await s.ev(`(() => ${docRows}.map((r) => ({
    aria: r.querySelector('button').getAttribute('aria-label'),
    buttons: r.querySelectorAll('button').length,
    pair: [...r.querySelectorAll('button')].map((b) => b.classList.contains('dashboard-link-btn') ? 'main' : (b.classList.contains('ask-about-btn') ? 'ask' : 'other')).join(','),
    entities: r.querySelectorAll('td.dashboard-count')[0].textContent.trim(),
    relations: r.querySelectorAll('td.dashboard-count')[1].textContent.trim(),
    shared: r.classList.contains('dashboard-link-row') && r.querySelector('button').classList.contains('dashboard-link-btn'),
  })))()`);
  check('34 rows in the DOM, one main button and one Ask button each',
    rows.length === 34 && rows.every((r) => r.buttons === 2 && r.pair === 'main,ask'), rows.length);
  check('row buttons keep the shared dashboard classes', rows.every((r) => r.shared));
  check('aria-labels read "Read name: E entities, R relations"',
    rows.every((r) => /^Read .+: \d[\d,]* entit(y|ies), \d[\d,]* relations?$/.test(r.aria || '')), rows.slice(0, 2).map((r) => r.aria));
  check('count cells equal the API values in order',
    rows.every((r, i) => r.entities === api[i].entity_count.toLocaleString('en-US')
      && r.relations === api[i].relation_count.toLocaleString('en-US')), rows.slice(0, 2));
  check('rows follow the API order (entity count descending)',
    api.every((d, i) => i === 0 || api[i - 1].entity_count >= d.entity_count));
  const names = await s.ev(`(() => ${docRows}.map((r) => r.querySelector('.documents-name__text').textContent))()`);
  check('row names are the API display names', names.every((n, i) => n === api[i].display_name), names.slice(0, 2));
  check('no row shows an id line', (await s.ev(`document.querySelectorAll('.documents-name__id').length`)) === 0);
  check('entity summary rows are untouched', (await s.ev(`document.querySelectorAll('.dashboard-entity-summary tr.dashboard-link-row').length`)) === 13);

  // (3) toggle
  const toggle = `document.querySelector('.documents-toggle')`;
  check('toggle reads Show all 34, collapsed',
    (await s.ev(`${toggle}.textContent`)) === 'Show all 34' && (await s.ev(`${toggle}.getAttribute('aria-expanded')`)) === 'false');
  await s.ev(`document.querySelector('.documents-section').scrollIntoView({ block: 'start', behavior: 'instant' })`);
  await s.shot('dashboard-documents.png');
  check('toggle clicked', await clickEl(s, toggle));
  check('34 rows visible after expanding', (await s.ev(`${visibleDocRows}.length`)) === 34);
  check('toggle reads Show first 10',
    (await s.ev(`${toggle}.textContent`)) === 'Show first 10' && (await s.ev(`${toggle}.getAttribute('aria-expanded')`)) === 'true');
  check('focus moved to the 11th row button',
    (await s.ev(`document.activeElement === document.querySelectorAll('${DOC_BTN}')[10]`)) === true);
  check('status announces all documents', (await s.ev(`document.getElementById('documents-status').textContent`)) === 'Showing all 34 documents.');
  check('toggle clicked again', await clickEl(s, toggle));
  check('24 rows hidden again', (await s.ev(`${visibleDocRows}.length`)) === 10);
  check('focus returned to the toggle', (await s.ev(`document.activeElement === ${toggle}`)) === true);

  // (4) open the first document with a real pointer click
  const first = api[0];
  const firstBtn = `document.querySelectorAll('${DOC_BTN}')[0]`;
  const pt = await centreOf(s, firstBtn);
  const scrolled = await s.ev(`document.getElementById('dashboard-panel').scrollTop`);
  check('the dashboard is scrolled before opening', scrolled > 0, scrolled);
  await s.click(pt.x, pt.y);
  check('source panel shown', await s.waitFor(`getComputedStyle(document.getElementById('source-panel')).display === 'flex'`));
  check('dashboard hidden', (await panelDisplay(s, '#dashboard-panel')) === 'none');
  check('the reader shows the text', await s.waitFor(`!!document.querySelector('#source-reader .source-text')`));
  const want = await s.ev(`(async () => (await (await fetch('/api/sources/${first.doc_id}')).json()).text)()`);
  const got = await s.ev(`document.querySelector('#source-reader .source-text').textContent`);
  check('reader text equals the API text', typeof want === 'string' && want.length > 0 && got === want, [want && want.length, got && got.length]);
  check('no highlight mark without a highlight', (await s.ev(`document.querySelectorAll('#source-reader mark').length`)) === 0);
  check('title is the display name', (await s.ev(`document.getElementById('source-title').textContent`)) === first.display_name);
  check('title has focus', (await s.ev(`document.activeElement === document.getElementById('source-title')`)) === true);
  check('status reads Opened name', (await s.ev(`document.getElementById('source-status').textContent`)) === `Opened ${first.display_name}.`);
  check('the id line shows the document id', (await s.ev(`document.querySelector('.source-id').textContent`)) === first.doc_id);
  const meta = await s.ev(`document.querySelector('.source-meta').textContent`);
  check('meta line carries the counts', meta.startsWith(`${first.entity_count.toLocaleString('en-US')} entit`) && meta.includes(' relation'), meta);
  check('nav Dashboard link stays active', (await s.ev(`document.querySelector('.nav-link[data-panel="dashboard"]').classList.contains('active')`)) === true);
  check('back button says Back to Dashboard', (await s.ev(`document.getElementById('source-back-btn').textContent`)).includes('Back to Dashboard'));
  check('no PDF link without a PDF', (await s.ev(`!document.getElementById('source-pdf-link')`)) === true);
  await s.shot('source-viewer.png');

  // (5) Esc goes back
  await s.key('Escape');
  check('Esc shows the dashboard again', await s.waitFor(`getComputedStyle(document.getElementById('dashboard-panel')).display === 'flex'`));
  check('viewer hidden after Esc', (await panelDisplay(s, '#source-panel')) === 'none');
  const restored = await s.ev(`document.getElementById('dashboard-panel').scrollTop`);
  check('scrollTop restored', Math.abs(restored - scrolled) <= 1, [scrolled, restored]);
  check('focus back on the row button', (await s.ev(`document.activeElement === ${firstBtn}`)) === true);

  // (6) keyboard open, then the Back button
  await s.key('Enter');
  check('Enter on the row opens the viewer', await s.waitFor(`getComputedStyle(document.getElementById('source-panel')).display === 'flex'`));
  check('the viewer loaded again', await s.waitFor(`!!document.querySelector('#source-reader .source-text')`));
  await s.ev(`document.getElementById('source-back-btn').click()`);
  check('Back button shows the dashboard', await s.waitFor(`getComputedStyle(document.getElementById('dashboard-panel')).display === 'flex'`));
  check('Back button restores scrollTop', Math.abs((await s.ev(`document.getElementById('dashboard-panel').scrollTop`)) - scrolled) <= 1);
  check('Back button restores focus', (await s.ev(`document.activeElement === ${firstBtn}`)) === true);

  // (7) Show in graph
  await s.ev(`window.__gst = []; window.addEventListener('graph-show-types', (e) => window.__gst.push(JSON.parse(JSON.stringify(e.detail))));`);
  await clickEl(s, firstBtn);
  check('viewer open for Show in graph', await s.waitFor(`!!document.querySelector('#source-reader .source-text')`));
  check('Show in graph is enabled for a document with entities',
    (await s.ev(`document.getElementById('source-graph-btn').getAttribute('aria-disabled')`)) === null && first.entity_count > 0);
  check('Show in graph clicked', await clickEl(s, `document.getElementById('source-graph-btn')`));
  check('graph panel shown', await s.waitFor(`getComputedStyle(document.getElementById('graph-panel')).display === 'flex' && getComputedStyle(document.getElementById('side-panel')).display === 'flex'`));
  const gst = await s.ev(`window.__gst`);
  check('graph-show-types carries the document focus',
    JSON.stringify(gst) === JSON.stringify([{ reset: true, focus: { id: `doc:${first.doc_id}`, hops: 1 } }]), gst);
  check('viewer hidden once the graph is shown', (await panelDisplay(s, '#source-panel')) === 'none');
  await s.waitFor(`!window._graphDebug.busy`);

  // (8) Esc on the Graph panel does not touch the viewer
  await s.key('Escape');
  await sleep(300);
  check('Esc on the graph keeps the viewer hidden', (await panelDisplay(s, '#source-panel')) === 'none');
  check('Esc on the graph keeps the graph visible', (await panelDisplay(s, '#graph-panel')) === 'flex');

  // (9) unknown document
  check('open the dashboard again', await openDocuments(s));
  await s.ev(`window.dispatchEvent(new CustomEvent('navigate-source', { detail: { docId: 'no_such_doc' } }))`);
  check('unknown id shows the viewer', await s.waitFor(`getComputedStyle(document.getElementById('source-panel')).display === 'flex'`));
  check('unknown id: Document not available', await s.waitFor(`(document.querySelector('.source-state__title') || {}).textContent === 'Document not available'`),
    await s.ev(`document.getElementById('source-reader').textContent`));
  check('unknown id: exact body copy',
    (await s.ev(`document.querySelector('.source-state__body').textContent`)) === "This document's text is not available in this output directory.");
  check('unknown id: Show in graph is aria-disabled with its note',
    (await s.ev(`document.getElementById('source-graph-btn').getAttribute('aria-disabled')`)) === 'true'
    && (await s.ev(`(document.getElementById('source-graph-note') || {}).textContent`)) === 'This document has no entities in the graph, so there is nothing to focus.');
  await s.shot('source-viewer-unavailable.png');
  await s.ev(`document.getElementById('source-back-btn').click()`);
  check('Back works from the unavailable state', await s.waitFor(`getComputedStyle(document.getElementById('dashboard-panel')).display === 'flex'`));

  check('no script exceptions from the workbench', s.errors.length === 0, s.errors.slice(0, 3));
  await s.done();
}


// --- Source highlight, chat citations ----------------------------------------

const RIGHT = `getComputedStyle(document.getElementById('source-panel')).display === 'flex'`;
const normalise = (t) => String(t).replace(/\s+/g, ' ').trim().toLowerCase();

async function waitScrollSettled(s, expr, cap = 8000) {
  const t0 = Date.now();
  let last = null;
  let stableSince = Date.now();
  while (Date.now() - t0 < cap) {
    const v = await s.ev(expr);
    if (v !== last) { last = v; stableSince = Date.now(); }
    else if (Date.now() - stableSince >= 300) return v;
    await sleep(60);
  }
  return last;
}

async function cardHighlight() {
  const s = await session();
  await load(s);
  check('dashboard opens with the epistemic section', await openEpistemic(s));

  const api = await s.ev(`(async () => { const d = await (await fetch('/api/dashboard')).json();
    return { docs: d.documents.map((x) => x.doc_id), statement: d.epistemic.sections[0].items[0].statements[0] }; })()`);
  check('the first contradiction has a statement in a listed document', !!api.statement && api.docs.includes(api.statement.document), api.statement);

  // Ids in the list are buttons; the others stay plain text.
  const linkIds = await s.ev(`[...document.querySelectorAll('.epistemic-health button.epistemic-doc-link')].map((b) => b.getAttribute('data-doc-id'))`);
  check('every card doc-id button is a listed document', linkIds.length > 0 && linkIds.every((id) => api.docs.includes(id)), linkIds.slice(0, 3));
  const plain = await s.ev(`[...document.querySelectorAll('.epistemic-health span.epistemic-meta__doc')].map((n) => n.textContent)`);
  check('plain doc ids are not in the documents list', plain.every((t) => !api.docs.includes(t)), plain.slice(0, 3));

  const link = `document.querySelector('#epistemic-sec-contradictions').parentElement.querySelector('.epistemic-card button.epistemic-doc-link')`;
  check('the first statement id is a button', (await s.ev(`!!${link} && ${link}.textContent`)) === api.statement.document, await s.ev(`${link} && ${link}.textContent`));
  check('its aria-label mentions the highlighted passage', (await s.ev(`${link}.getAttribute('aria-label')`)) === `Read ${api.statement.document} with the cited passage highlighted`);

  check('the id button is clicked', await clickEl(s, link));
  check('source panel shown', await s.waitFor(RIGHT));
  check('dashboard hidden', (await panelDisplay(s, '#dashboard-panel')) === 'none');
  check('exactly one highlight mark', await s.waitFor(`document.querySelectorAll('#source-reader mark.source-highlight').length === 1`), await s.ev(`document.querySelectorAll('#source-reader mark').length`));
  const bg = await s.ev(`getComputedStyle(document.querySelector('#source-reader mark.source-highlight')).backgroundColor`);
  check('the mark is amber', bg === 'rgb(253, 230, 138)', bg);
  const markText = await s.ev(`document.querySelector('#source-reader mark.source-highlight').textContent`);
  check('the mark holds the statement text', normalise(markText) === normalise(api.statement.text) || normalise(api.statement.text).startsWith(normalise(markText)), [markText.slice(0, 60), api.statement.text.slice(0, 60)]);
  await waitScrollSettled(s, `document.getElementById('source-reader').scrollTop`);
  const inside = await s.ev(`(() => { const m = document.querySelector('#source-reader mark').getBoundingClientRect();
    const r = document.getElementById('source-reader').getBoundingClientRect();
    return m.top >= r.top - 1 && m.bottom <= r.bottom + 1 && m.left >= r.left - 1 && m.right <= r.right + 1; })()`);
  check('the mark lies inside the reader', inside === true);
  check('the status ends with the cited-passage sentence', (await s.ev(`document.getElementById('source-status').textContent`)).endsWith('Cited passage highlighted.'),
    await s.ev(`document.getElementById('source-status').textContent`));
  check('the reader still holds the whole document text', (await s.ev(`(async () => (await (await fetch('/api/sources/${api.statement.document}')).json()).text)()`))
    === (await s.ev(`document.querySelector('#source-reader .source-text').textContent`)));
  await s.shot('source-viewer-highlight.png');

  await s.ev(`document.getElementById('source-back-btn').click()`);
  check('Back returns to the Dashboard', await s.waitFor(`getComputedStyle(document.getElementById('dashboard-panel')).display === 'flex'`));

  // A highlight that does not occur opens the document at the top without a mark.
  await s.ev(`window.dispatchEvent(new CustomEvent('navigate-source', { detail: { docId: ${q(api.statement.document)}, highlight: 'this passage is not anywhere in the document 0xC0FFEE' } }))`);
  check('a missing passage still opens the viewer', await s.waitFor(`${RIGHT} && !!document.querySelector('#source-reader .source-text')`));
  check('a missing passage: no mark', (await s.ev(`document.querySelectorAll('#source-reader mark').length`)) === 0);
  check('a missing passage: reader at the top', (await s.ev(`document.getElementById('source-reader').scrollTop`)) === 0);
  check('a missing passage: no error state', (await s.ev(`document.querySelectorAll('#source-reader .source-state').length`)) === 0);
  check('a missing passage: plain opened status', (await s.ev(`document.getElementById('source-status').textContent`)).indexOf('Cited passage') === -1);

  check('no script exceptions from the workbench', s.errors.length === 0, s.errors.slice(0, 3));
  await s.done();
}

const CHAT_REPLY = 'Semaglutide was approved (pmid_35650449). See [Nonexistent Thing] and `pmid_35650449`.';

async function citations() {
  const s = await session();
  await load(s);
  const cdn = await s.waitFor(`typeof marked !== 'undefined' && typeof DOMPurify !== 'undefined'`, 15000);
  if (!cdn) {
    await s.done();
    console.log(JSON.stringify({ passed: passedCount, failed: failures, skipped: 'marked/DOMPurify CDN unavailable' }));
    process.exit(0);
  }
  check('marked and DOMPurify are loaded', cdn);

  const chatCalls = [];
  s.on('Fetch.requestPaused', (p) => {
    chatCalls.push(p.request.url);
    const body = `data: ${JSON.stringify({ type: 'text', content: CHAT_REPLY })}\n\ndata: ${JSON.stringify({ type: 'done' })}\n\n`;
    s.send('Fetch.fulfillRequest', {
      requestId: p.requestId,
      responseCode: 200,
      responseHeaders: [
        { name: 'Content-Type', value: 'text/event-stream' },
        { name: 'Cache-Control', value: 'no-cache' },
      ],
      body: Buffer.from(body).toString('base64'),
    });
  });
  await s.send('Fetch.enable', { patterns: [{ urlPattern: '*/api/chat', requestStage: 'Request' }] });

  // The Dashboard has loaded the document list; the chat resolves citations against it.
  check('the document list reached the chat', await s.waitFor(`document.querySelectorAll('.documents-table .dashboard-doc-btn').length > 0`));
  await s.ev(`document.querySelector('.nav-link[data-panel=chat]').click()`);
  check('chat panel shown', await s.waitFor(`document.querySelector('.chat-panel').style.display === 'flex'`));
  await s.ev(`(() => { document.getElementById('chat-input').value = 'What was approved?';
    document.getElementById('chat-form').dispatchEvent(new Event('submit', { cancelable: true })); })()`);
  const linkSel = `.chat-msg--assistant a.citation-link[data-doc="pmid_35650449"]`;
  check('the reply contains a citation link', await s.waitFor(`document.querySelectorAll('${linkSel}').length > 0`), chatCalls);
  check('the stubbed /api/chat was used (no real model call)', chatCalls.length === 1 && chatCalls[0].includes('/api/chat'), chatCalls);
  check('exactly one link: the code-span copy is not linked', (await s.ev(`document.querySelectorAll('${linkSel}').length`)) === 1);
  check('the link has a title and no onclick', (await s.ev(`document.querySelector('${linkSel}').getAttribute('title')`)) === 'Open pmid_35650449 in the source viewer'
    && (await s.ev(`!document.querySelector('${linkSel}').hasAttribute('onclick')`)) === true);
  check('no element in the assistant message has an onclick', (await s.ev(`[...document.querySelectorAll('.chat-msg--assistant *')].every((e) => !e.hasAttribute('onclick'))`)) === true);
  check('the code span keeps the id as plain text', (await s.ev(`[...document.querySelectorAll('.chat-msg--assistant code')].some((c) => c.textContent === 'pmid_35650449' && !c.closest('a'))`)) === true);
  check('[Nonexistent Thing] stays text, outside any link', (await s.ev(`document.querySelector('.chat-msg--assistant').textContent.includes('[Nonexistent Thing]')
    && ![...document.querySelectorAll('.chat-msg--assistant a')].some((a) => a.textContent.includes('Nonexistent'))`)) === true);
  await s.shot('chat-citation.png');
  await s.send('Fetch.disable');

  check('the link is clicked', await clickEl(s, `document.querySelector('${linkSel}')`));
  check('the viewer is shown', await s.waitFor(RIGHT));
  check('the viewer shows pmid_35650449', await s.waitFor(`document.getElementById('source-title').textContent === 'pmid_35650449' && !!document.querySelector('#source-reader .source-text')`));
  check('Back says Back to Chat', (await s.ev(`document.getElementById('source-back-btn').textContent`)).includes('Back to Chat'));
  check('the chat nav link stays active', (await s.ev(`document.querySelector('.nav-link[data-panel="chat"]').classList.contains('active')`)) === true);
  await s.ev(`document.getElementById('source-back-btn').click()`);
  check('Back returns to the chat', await s.waitFor(`document.querySelector('.chat-panel').style.display === 'flex'`));
  check('the viewer is hidden again', (await panelDisplay(s, '#source-panel')) === 'none');
  check('no script exceptions from the workbench', s.errors.length === 0, s.errors.slice(0, 3));
  await s.done();
}

async function fdaHighlight() {
  const s = await session();
  await load(s);
  check('dashboard opens with the documents table', await openDocuments(s));
  check('FDA labels list 7 documents', (await s.ev(`${docRows}.length`)) === 7, await s.ev(`${docRows}.length`));
  check('no Documents toggle for 7 documents', (await s.ev(`!document.querySelector('.documents-toggle')`)) === true);

  const pick = await s.ev(`(async () => {
    const text = (await (await fetch('/api/sources/semaglutide_wegovy')).json()).text;
    const lower = text.toLowerCase();
    const isSpace = (c) => /\\s/.test(c);
    for (let start = Math.floor(text.length * 0.7); start < text.length - 200; start += 53) {
      let i = start;
      while (i < text.length && !isSpace(text[i])) i += 1;
      while (i < text.length && isSpace(text[i])) i += 1;
      let end = Math.min(i + 100, text.length);
      while (end > i + 40 && !isSpace(text[end])) end -= 1;
      const passage = text.slice(i, end).trim();
      if (passage.length < 40) continue;
      const at = lower.indexOf(passage.toLowerCase());
      if (at === i && lower.indexOf(passage.toLowerCase(), at + 1) === -1) return { length: text.length, passage, at: i };
    }
    return { length: text.length, passage: null };
  })()`);
  check('semaglutide_wegovy is an 80 KB document (79,814 characters)', pick.length > 79000 && pick.length <= 80000, pick.length);
  check('a unique deep passage was found', !!pick.passage && pick.at > 50000, pick);

  await s.ev(`window.dispatchEvent(new CustomEvent('navigate-source', { detail: { docId: 'semaglutide_wegovy', highlight: ${JSON.stringify(pick.passage)} } }))`);
  check('source panel shown', await s.waitFor(RIGHT));
  check('one mark placed', await s.waitFor(`document.querySelectorAll('#source-reader mark.source-highlight').length === 1`));
  const top = await waitScrollSettled(s, `document.getElementById('source-reader').scrollTop`);
  check('the reader scrolled down', top > 0, top);
  const off = await s.ev(`(() => { const m = document.querySelector('#source-reader mark').getBoundingClientRect();
    const r = document.getElementById('source-reader').getBoundingClientRect();
    return { mark: (m.top + m.bottom) / 2, reader: (r.top + r.bottom) / 2 }; })()`);
  check('the mark is within one line of the reader middle', Math.abs(off.mark - off.reader) <= 24, off);
  const style = await s.ev(`(() => { const cs = getComputedStyle(document.querySelector('#source-reader .source-text')); const r = document.getElementById('source-reader');
    return { size: cs.fontSize, line: cs.lineHeight, ws: cs.whiteSpace, family: cs.fontFamily, overflow: r.scrollWidth - r.clientWidth }; })()`);
  check('reading text is 15px with a 24px line', style.size === '15px' && style.line === '24px', style);
  check('reading text keeps its line breaks', style.ws === 'pre-wrap', style.ws);
  check('reading text is not monospace', !/mono/i.test(style.family), style.family);
  check('the reader has no horizontal overflow', style.overflow <= 0, style.overflow);
  await s.shot('source-viewer-fda.png');
  check('no script exceptions from the workbench', s.errors.length === 0, s.errors.slice(0, 3));
  await s.done();
}

// --- Where to start ------------------------------------------------------------

const START = `document.querySelector('section.start-here')`;
const COMM_BTN = '.start-communities-table tbody tr.dashboard-link-row button.dashboard-link-btn';
const HUB_BTN = '.start-hubs-table tbody tr.dashboard-link-row button.dashboard-link-btn';
const commBtn = (nth) => `document.querySelectorAll(${q(COMM_BTN)})[${nth}]`;
const SCALE = `window._graphDebug.network.getScale()`;
const activeRegion = `(window._graphDebug ? window._graphDebug.activeRegion : undefined)`;
const graphShown = `document.getElementById('graph-panel').style.display === 'flex'`;

// Waits at least 600 ms, then until two scale reads 200 ms apart are equal, so
// any zoom animation and the panel-open refit are over.
async function settledScale(s) {
  await sleep(600);
  let prev = await s.ev(SCALE);
  for (let i = 0; i < 50; i += 1) {
    await sleep(200);
    const cur = await s.ev(SCALE);
    if (cur === prev) return cur;
    prev = cur;
  }
  return prev;
}

// The canvas rectangle currently in view and the drawn group regions.
const viewAndRegions = `(() => {
  const n = window._graphDebug.network;
  const c = document.getElementById('graph-container');
  const a = n.DOMtoCanvas({ x: 0, y: 0 });
  const b = n.DOMtoCanvas({ x: c.clientWidth, y: c.clientHeight });
  const view = { x0: Math.min(a.x, b.x), y0: Math.min(a.y, b.y), x1: Math.max(a.x, b.x), y1: Math.max(a.y, b.y) };
  return { view, regions: window._graphDebug.regionGeometry() };
})()`;
const centreIn = (v, r) => !!r && r.cx >= v.x0 && r.cx <= v.x1 && r.cy >= v.y0 && r.cy <= v.y1;
const fullyIn = (v, r) => !!r && r.cx - r.r >= v.x0 && r.cx + r.r <= v.x1 && r.cy - r.r >= v.y0 && r.cy + r.r <= v.y1;

// Checks that the view is zoomed onto region `id`: the scale is well above the
// whole-graph fit, the region centre is in view and some other region is not.
async function checkZoomed(s, label, id, s0) {
  const scale = await settledScale(s);
  check(`${label}: settled scale >= 1.2 x the whole-graph fit`, typeof scale === 'number' && scale >= 1.2 * s0, [scale, s0]);
  const vr = await s.ev(viewAndRegions);
  const mine = vr && vr.regions.find((r) => r.id === id);
  check(`${label}: the region centre is inside the view`, centreIn(vr && vr.view, mine), { view: vr && vr.view, mine });
  const others = vr ? vr.regions.filter((r) => r.id !== id) : [];
  check(`${label}: another region centre lies outside the view`, others.some((r) => !centreIn(vr.view, r)), others.length);
  return vr;
}

async function startHere() {
  const s = await session();
  await load(s);
  check('dashboard opens', await openDashboard(s));
  const api = await s.ev(`(async () => {
    const d = await (await fetch('/api/dashboard')).json();
    const g = await (await fetch('/api/graph/groups')).json();
    return { start: d.start_here, cluster: g.modes.cluster.groups };
  })()`);
  const comms = (api && api.start && api.start.communities) || [];
  const hubs = (api && api.start && api.start.hubs) || [];
  const fullLabel = Object.fromEntries(comms.map((c) => [c.id, c.full_label]));

  // (a) placement and headings
  check('the section exists', await s.waitFor(`!!${START}`, 5000));
  const place = await s.ev(`(() => {
    const sec = ${START};
    const summary = document.querySelector('.dashboard-entity-summary');
    const epi = document.querySelector('section.epistemic-health');
    if (!sec || !summary || !epi) return null;
    const F = Node.DOCUMENT_POSITION_FOLLOWING;
    return {
      h3: (sec.querySelector('h3') || {}).textContent,
      h4: [...sec.querySelectorAll('h4')].map((h) => h.textContent),
      afterSummary: !summary.contains(sec) && Boolean(summary.compareDocumentPosition(sec) & F),
      beforeEpistemic: !sec.contains(epi) && Boolean(sec.compareDocumentPosition(epi) & F),
    };
  })()`);
  check('h3 reads Where to start', !!place && place.h3 === 'Where to start', place);
  check('the section follows the Entity Summary', !!place && place.afterSummary, place);
  check('the section precedes Epistemic health', !!place && place.beforeEpistemic, place);
  check('block titles in order', !!place && JSON.stringify(place.h4) === JSON.stringify(['Topic communities (10)', 'Most-connected entities']), place && place.h4);

  // (b) communities table
  const ct = await s.ev(`(() => {
    const t = document.querySelector('.start-communities-table');
    if (!t) return null;
    return {
      heads: [...t.querySelectorAll('thead th')].map((th) => th.textContent.trim()),
      rows: [...t.querySelectorAll('tbody tr.dashboard-link-row')].map((tr) => {
        const btns = tr.querySelectorAll('div.start-action > button.dashboard-link-btn[data-start-action="show"]');
        const b = btns[0];
        return {
          id: tr.getAttribute('data-group-id'),
          members: (tr.querySelector('td.dashboard-count') || {}).textContent,
          buttons: btns.length,
          aria: b ? b.getAttribute('aria-label') : null,
          title: b ? b.getAttribute('title') : null,
          text: b ? (b.querySelector('.start-name__text') || {}).textContent : null,
          sub: b && b.querySelector('.start-name__sub') ? b.querySelector('.start-name__sub').textContent : null,
        };
      }),
      toggle: !!document.querySelector('.start-toggle'),
    };
  })()`);
  check('communities headers are Community, Members', !!ct && JSON.stringify(ct.heads) === '["Community","Members"]', ct && ct.heads);
  const crows = ct ? ct.rows : [];
  check('10 community rows', crows.length === 10, crows.length);
  // The served /api/graph/groups order itself (the Groups list order), not re-sorted.
  const expectedIds = (api ? api.cluster : []).filter((g) => g.id !== 'other').map((g) => g.id);
  const rowIds = crows.map((r) => r.id);
  check('row ids equal start_here ids', JSON.stringify(rowIds) === JSON.stringify(comms.map((c) => c.id)), rowIds);
  check('row ids equal the served cluster group order', JSON.stringify(rowIds) === JSON.stringify(expectedIds), expectedIds);
  const memberTexts = await s.ev(`(${JSON.stringify(comms.map((c) => c.member_count))}).map((n) => n.toLocaleString())`);
  check('Members cells show member_count', JSON.stringify(crows.map((r) => r.members)) === JSON.stringify(memberTexts), crows.map((r) => r.members));
  check('no Show all toggle for 10 communities', !!ct && ct.toggle === false);
  check('one show button per community row', crows.length > 0 && crows.every((r) => r.buttons === 1), crows.map((r) => r.buttons));
  check('community aria-labels', crows.length > 0 && crows.every((r) => /^Show the .+ community in the graph: \d+ members?/.test(r.aria || '')), crows.slice(0, 2).map((r) => r.aria));
  check('visible label is the short label', crows.length === comms.length && crows.length > 0 && crows.every((r, i) => r.text === comms[i].label), crows.slice(0, 2));
  check('title starts with the full label', crows.length === comms.length && crows.length > 0 && crows.every((r, i) => (r.title || '').startsWith(comms[i].full_label)));
  check('rows with top members show the Top members line', crows.length === comms.length && crows.length > 0
    && crows.every((r, i) => (comms[i].top_members.length === 0) || (r.sub || '').startsWith('Top members: ')), crows.map((r) => r.sub).slice(0, 2));

  // (c) hubs table
  const ht = await s.ev(`(() => {
    const t = document.querySelector('.start-hubs-table');
    if (!t) return null;
    const summaryLabel = (type) => {
      const tr = [...document.querySelectorAll('.dashboard-entity-summary tr.dashboard-link-row')].find((r) => r.getAttribute('data-entity-type') === type);
      const l = tr && tr.querySelector('.dashboard-link-label');
      return l ? l.textContent : null;
    };
    return {
      heads: [...t.querySelectorAll('thead th')].map((th) => th.textContent.trim()),
      rows: [...t.querySelectorAll('tbody tr.dashboard-link-row')].map((tr) => {
        const comm = tr.querySelector('td.start-community');
        return {
          id: tr.getAttribute('data-node-id'),
          connections: Number(((tr.querySelector('td.dashboard-count') || {}).textContent || '').replace(/,/g, '')),
          swatch: !!tr.querySelector('td.start-type svg.type-swatch'),
          typeLabel: (tr.querySelector('td.start-type .start-type__label') || {}).textContent,
          community: comm ? comm.textContent : null,
          none: comm ? comm.classList.contains('start-community--none') : false,
        };
      }),
      summaryLabels: Object.fromEntries(${JSON.stringify([...new Set(hubs.map((h) => h.entity_type))])}.map((t) => [t, summaryLabel(t)])),
    };
  })()`);
  check('hubs headers are Entity, Type, Connections, Community', !!ht && JSON.stringify(ht.heads) === '["Entity","Type","Connections","Community"]', ht && ht.heads);
  const hrows = ht ? ht.rows : [];
  check('1 to 10 hub rows', hrows.length >= 1 && hrows.length <= 10 && hrows.length === hubs.length, [hrows.length, hubs.length]);
  check('hub rows follow start_here order', JSON.stringify(hrows.map((r) => r.id)) === JSON.stringify(hubs.map((h) => h.id)));
  check('connections are non-increasing', hrows.length > 0 && hrows.every((r, i) => i === 0 || hrows[i - 1].connections >= r.connections), hrows.map((r) => r.connections));
  check('every Type cell has a swatch', hrows.length > 0 && hrows.every((r) => r.swatch));
  const typeOk = hrows.length === hubs.length && hrows.length > 0 && hrows.every((r, i) => {
    const want = ht.summaryLabels[hubs[i].entity_type];
    return typeof want === 'string' && want.length > 0 && r.typeLabel === want;
  });
  check('every hub type label equals its Entity Summary label', typeOk, hrows.map((r, i) => [r.typeLabel, ht && ht.summaryLabels[hubs[i] && hubs[i].entity_type]]));
  check('community cells: label or Unclustered', hrows.length === hubs.length && hrows.length > 0 && hrows.every((r, i) => (hubs[i].community_id === null
    ? r.community === 'Unclustered' && r.none
    : r.community === hubs[i].community_label && !r.none)), hrows.map((r) => r.community));
  await s.ev(`(${START} || document.body).scrollIntoView({ block: 'start', behavior: 'instant' })`);
  await s.shot('dashboard-start-here.png');

  // (d) narrow widths (container queries on the section)
  const narrow = await s.ev(`(async () => {
    const sec = ${START};
    if (!sec) return null;
    sec.style.width = '640px';
    await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
    const th = document.querySelector('.start-hubs-table th.start-col-community');
    const td = document.querySelector('.start-hubs-table td.start-community');
    return {
      th: th ? getComputedStyle(th).display : null,
      td: td ? getComputedStyle(td).display : null,
      wraps: [...sec.querySelectorAll('.dashboard-table-wrap')].map((w) => [w.scrollWidth, w.clientWidth]),
    };
  })()`);
  check('640px: the hubs Community column is hidden', !!narrow && narrow.th === 'none' && narrow.td === 'none', narrow);
  check('640px: no table wrap overflows', !!narrow && narrow.wraps.length === 2 && narrow.wraps.every(([sw, cw]) => sw <= cw), narrow && narrow.wraps);
  await s.shot('start-here-narrow.png');
  const tiny = await s.ev(`(async () => {
    const sec = ${START};
    if (!sec) return null;
    sec.style.width = '420px';
    await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
    const label = document.querySelector('.start-hubs-table .start-type__label');
    const swatch = document.querySelector('.start-hubs-table td.start-type svg.type-swatch');
    const out = {
      labelWidth: label ? label.getBoundingClientRect().width : null,
      labelText: label ? label.textContent : '',
      swatchWidth: swatch ? swatch.getBoundingClientRect().width : 0,
    };
    sec.style.width = '';
    return out;
  })()`);
  check('420px: type label visually hidden but present', !!tiny && tiny.labelWidth !== null && tiny.labelWidth <= 1 && tiny.labelText.length > 0, tiny);
  check('420px: the swatch stays visible', !!tiny && tiny.swatchWidth > 0, tiny);

  // (e) typography of the text classes only (A-2)
  const TYPO = `(() => {
    const sec = ${START};
    if (!sec) return null;
    const sel = '.start-block__title, .start-name__text, .start-name__sub, .start-type, .start-type__label, .start-community, .start-toggle, td.dashboard-count';
    return [...sec.querySelectorAll(sel)].map((e) => {
      const cs = getComputedStyle(e);
      return [e.className, cs.fontSize, cs.fontWeight];
    });
  })()`;
  const typoOk = (list) => Array.isArray(list) && list.length > 0
    && list.every(([, size, weight]) => ['13px', '14px', '15px'].includes(size) && ['400', '600'].includes(weight));
  const typo = await s.ev(TYPO);
  check('text sizes 13/14/15px, weights 400/600', typoOk(typo), (typo || []).filter(([, sz, w]) => !['13px', '14px', '15px'].includes(sz) || !['400', '600'].includes(w)).slice(0, 4));
  await s.ev(`document.body.classList.add('present')`);
  const typoPresent = await s.ev(TYPO);
  await s.ev(`document.body.classList.remove('present')`);
  check('Present mode keeps the same text sizes', typoOk(typoPresent) && JSON.stringify(typoPresent) === JSON.stringify(typo));

  // (f) an invalid group id falls back to the default view
  await s.ev(`document.querySelector('.nav-link[data-panel="graph"]').click()`);
  await s.waitFor(`${graphShown} && !window._graphDebug.busy`, 30000);
  const modeBefore = await s.ev(`window._graphDebug.mode`);
  await s.ev(`window.dispatchEvent(new CustomEvent('graph-show-types', { detail: { reset: true } }))`);
  await s.waitFor(`!window._graphDebug.busy`, 30000);
  await sleep(300);
  const defaultVisible = await s.ev(visibleIds);
  const defaultChips = await s.ev(pressedChips);
  const s0 = await settledScale(s);
  await s.ev(`window.dispatchEvent(new CustomEvent('graph-show-types', { detail: { reset: true, group: 'nope' } }))`);
  await sleep(500);
  await s.waitFor(`!window._graphDebug.busy`, 30000);
  const invalid = await s.ev(`({
    mode: window._graphDebug.mode,
    active: ${activeRegion},
    current: document.querySelectorAll('.graph-group-row[aria-current="true"]').length,
    status: document.getElementById('graph-sources-status').textContent,
  })`);
  check('invalid group: Group by unchanged', invalid.mode === modeBefore, [invalid.mode, modeBefore]);
  check('invalid group: no active region', invalid.active === null, invalid.active);
  check('invalid group: no Groups row is current', invalid.current === 0, invalid.current);
  check('invalid group: not-in-graph status', invalid.status.startsWith('The selected community is not in this graph. Showing the default graph: '), invalid.status);
  check('invalid group: default visible set', sameSet(await s.ev(visibleIds), defaultVisible) && defaultVisible.length > 0, defaultVisible.length);
  check('invalid group: default chips', JSON.stringify(await s.ev(pressedChips)) === JSON.stringify(defaultChips), defaultChips);

  // (g) a community click starting from Group by None
  await clickEl(s, `document.querySelector('#graph-group button[data-mode="none"]')`);
  check('setup: Group by None', await s.waitFor(`window._graphDebug.mode === 'none' && !window._graphDebug.busy`, 30000), await s.ev(`window._graphDebug.mode`));
  check('dashboard opens for the community click', await openDashboard(s));
  const first = comms[0] ? comms[0].id : null;
  const clickedFirst = await clickEl(s, commBtn(0));
  check('first community row clicked', clickedFirst);
  const zoomed = clickedFirst && await s.waitFor(`${graphShown} && window._graphDebug.mode === 'cluster' && !window._graphDebug.busy && ${activeRegion} === ${q(first)}`, 30000);
  check('community click: Graph panel, Topic cluster, zoomed region', zoomed, await s.ev(`({ mode: window._graphDebug.mode, active: ${activeRegion} })`));
  if (zoomed) {
    check('community click: Topic cluster radio checked',
      (await s.ev(`document.querySelector('#graph-group button[data-mode="cluster"]').getAttribute('aria-checked')`)) === 'true');
    check('community click: Groups row is current',
      (await s.ev(`(document.querySelector('.graph-group-row[data-group=' + ${JSON.stringify(JSON.stringify(first))} + ']') || { getAttribute: () => null }).getAttribute('aria-current')`)) === 'true');
    await checkZoomed(s, 'community click', first, s0);
    const groupStatus = await s.ev(`document.getElementById('graph-group-status').textContent`);
    check('community click: zoom announcement', groupStatus.startsWith(`Zoomed to ${fullLabel[first]}: `), groupStatus);
    const srcStatus = await s.ev(`document.getElementById('graph-sources-status').textContent`);
    check('community click: sources status', srcStatus.startsWith(`Showing the ${fullLabel[first]} community: `), srcStatus);
    check('community click: pointer activation leaves the container unfocused',
      (await s.ev(`document.activeElement && document.activeElement.id`)) !== 'graph-container');
    await s.shot('start-here-community-zoom.png');
  }

  // (h) the same row again, already on Topic cluster: stays zoomed, no toggle-off
  check('dashboard opens for the repeat click', await openDashboard(s));
  const again = await clickEl(s, commBtn(0));
  const zoomedAgain = again && await s.waitFor(`${graphShown} && !window._graphDebug.busy && ${activeRegion} === ${q(first)}`, 30000);
  check('repeat click: region still active', zoomedAgain);
  if (zoomedAgain) {
    await checkZoomed(s, 'repeat click', first, s0);
    check('repeat click: still the active region after settling', (await s.ev(activeRegion)) === first);
    check('repeat click: Groups row still current',
      (await s.ev(`(document.querySelector('.graph-group-row[data-group=' + ${JSON.stringify(JSON.stringify(first))} + ']') || { getAttribute: () => null }).getAttribute('aria-current')`)) === 'true');
  }
  check('dashboard opens for the second community', await openDashboard(s));
  const second = comms[1] ? comms[1].id : null;
  const clickedSecond = await clickEl(s, commBtn(1));
  const zoomedSecond = clickedSecond && await s.waitFor(`${graphShown} && !window._graphDebug.busy && ${activeRegion} === ${q(second)}`, 30000);
  check('second community: region active', zoomedSecond);
  if (zoomedSecond) {
    const vr = await checkZoomed(s, 'second community', second, s0);
    const firstRegion = vr && vr.regions.find((r) => r.id === first);
    check('second community: the first region is no longer fully in view',
      !!firstRegion && (!centreIn(vr.view, firstRegion) || !fullyIn(vr.view, firstRegion)), firstRegion);
  }

  // (i) hub by keyboard
  check('dashboard opens for the hub', await openDashboard(s));
  const hub = hubs[0] || { id: null, name: '' };
  const focused = await s.ev(`(() => { const b = document.querySelector(${q(HUB_BTN)}); if (!b) return false; b.focus(); return document.activeElement === b; })()`);
  check('first hub button focused', focused);
  if (focused) await s.key('Enter');
  const inFocus = focused && await s.waitFor(`${graphShown} && ${focusTop} === ${q(hub.id)}`, 30000);
  check('hub Enter: focus mode on the hub', inFocus, await s.ev(`window._graphDebug && ${focusTop}`));
  if (inFocus) {
    check('hub Enter: focus bar shown', (await s.ev(`document.getElementById('graph-focus-bar').hidden`)) === false);
    const st = await s.ev(`document.getElementById('graph-group-status').textContent`);
    check('hub Enter: focus announcement', st.startsWith(`Focus: ${hub.name}`), st);
    check('hub Enter: keyboard focus on the graph container', (await s.ev(`document.activeElement && document.activeElement.id`)) === 'graph-container');
    await s.shot('start-here-hub-focus.png');
  }

  // (j) Present mode
  await s.ev(`document.body.classList.add('present')`);
  check('dashboard opens in Present mode', await openDashboard(s));
  const third = comms[2] ? comms[2].id : null;
  const clickedThird = await clickEl(s, commBtn(2));
  const zoomedThird = clickedThird && await s.waitFor(`${graphShown} && !window._graphDebug.busy && ${activeRegion} === ${q(third)}`, 30000);
  check('Present mode: third community zoomed', zoomedThird);
  if (zoomedThird) {
    const scale = await settledScale(s);
    check('Present mode: scale >= 1.2 x the whole-graph fit', scale >= 1.2 * s0, [scale, s0]);
    const st = await s.ev(`document.getElementById('graph-group-status').textContent`);
    check('Present mode: zoom announcement', st.startsWith('Zoomed to '), st);
  }
  await s.ev(`document.body.classList.remove('present')`);

  // (k)
  check('no script exceptions from the workbench', s.errors.length === 0, s.errors.slice(0, 3));
  await s.done();
}

async function startHereEarly() {
  const s = await session();
  await s.viewport(1440, 1000);
  // Hold /api/graph until the community click has fired (see early()).
  const held = [];
  let released = false;
  s.on('Fetch.requestPaused', (p) => {
    if (released) s.send('Fetch.continueRequest', { requestId: p.requestId });
    else held.push(p.requestId);
  });
  await s.send('Fetch.enable', { patterns: [{ urlPattern: '*/api/graph', requestStage: 'Request' }] });
  await s.send('Page.addScriptToEvaluateOnNewDocument', { source: `
    document.addEventListener('DOMContentLoaded', () => {
      const t = setInterval(() => {
        const b = document.querySelectorAll(${q(COMM_BTN)})[2];
        if (!b) return;
        clearInterval(t);
        const tr = b.closest('tr');
        window.__earlyStart = { graphReady: !!window._graphDebug, id: tr ? tr.getAttribute('data-group-id') : null };
        b.click();
      }, 1);
    });` });
  await s.send('Page.navigate', { url: URL_ });
  check('early community click fired', await s.waitFor(`!!window.__earlyStart`, 30000), await s.ev(`window.__earlyStart`));
  const info = await s.ev(`window.__earlyStart`);
  check('early community click: made before the graph loaded', !!info && info.graphReady === false, info);
  check('early community click: /api/graph was held until the click', held.length > 0, held.length);
  released = true;
  for (const requestId of held.splice(0)) await s.send('Fetch.continueRequest', { requestId });
  await s.send('Fetch.disable');
  const id = info ? info.id : null;
  const zoomed = !!info && await s.waitFor(`!!window._graphDebug && window._graphDebug.mode === 'cluster' && !window._graphDebug.busy && ${activeRegion} === ${q(id)}`, 30000);
  check('early community click: zoomed to that community', zoomed, await s.ev(`window._graphDebug ? { mode: window._graphDebug.mode, active: window._graphDebug.activeRegion } : null`));
  if (zoomed) {
    const st = await s.ev(`document.getElementById('graph-group-status').textContent`);
    check('early community click: zoom announcement', st.startsWith('Zoomed to '), st);
    const scale = await settledScale(s);
    await s.ev(`window.dispatchEvent(new CustomEvent('graph-show-types', { detail: { reset: true } }))`);
    await s.waitFor(`!window._graphDebug.busy`, 30000);
    const whole = await settledScale(s);
    check('early community click: scale >= 1.2 x the whole-graph fit', scale >= 1.2 * whole, [scale, whole]);
  }
  check('early community click: no script exceptions', s.errors.length === 0, s.errors.slice(0, 3));
  await s.done();
}

// --- Ask about this ----------------------------------------------------------

const ASK = '#dashboard-content button.ask-about-btn';
const ASK_TITLE = 'Puts a question in the chat box. Nothing is sent until you press Send.';
const chatValue = `document.getElementById('chat-input').value`;
const chatFocused = `(document.activeElement && document.activeElement.id === 'chat-input')`;
const chatShown = `(document.querySelector('.chat-panel').style.display === 'flex')`;
const typeAsk = (type) => `document.querySelector('.dashboard-entity-summary tr.dashboard-link-row[data-entity-type="${type}"] .ask-about-btn')`;
const typeMain = (type) => `document.querySelector('.dashboard-entity-summary tr.dashboard-link-row[data-entity-type="${type}"] .dashboard-link-btn')`;
const commAsk = (id) => `document.querySelector('.start-communities-table tr[data-group-id="${id}"] .ask-about-btn')`;
const hubAsk = (i) => `document.querySelector('.start-hubs-table tbody tr[data-index="${i}"] .ask-about-btn')`;
const docAsk = (id) => `document.querySelector('.documents-table tr[data-doc-id="${id}"] .ask-about-btn')`;
const findingAsk = (i) => `document.querySelector('.findings-table tbody tr[data-index="${i}"] .ask-about-btn')`;
const TOTALS_ASK = `document.querySelector('.dashboard-totals .ask-about-btn')`;
const STATUS_ASK = `document.querySelector('#dashboard-content [data-ask="epistemic-status"]')`;

// Row-action events, every request URL, and a Fetch stub that fails every
// /api/chat request (the model is never called) while counting it.
async function armSpies(s) {
  await s.ev(`(() => { window.__rowEvents = [];
    if (!window.__rowSpies) {
      window.__rowSpies = true;
      for (const t of ['graph-show-types', 'navigate-source', 'graph-focus-node']) {
        window.addEventListener(t, () => window.__rowEvents.push(t));
      }
    }
    return true; })()`);
  const spy = { urls: [], chat: 0 };
  s.on('Network.requestWillBeSent', (p) => spy.urls.push(p.request.url));
  s.on('Fetch.requestPaused', (p) => {
    spy.chat += 1;
    s.send('Fetch.failRequest', { requestId: p.requestId, errorReason: 'Aborted' });
  });
  await s.send('Fetch.enable', { patterns: [{ urlPattern: '*/api/chat*', requestStage: 'Request' }] });
  return spy;
}

// Activates an Ask button (mouse, Enter or Space) and checks the prefill
// contract: chat shown, exact question, focus in the input, no row action, the
// graph and the source viewer not opened, the Chat nav link active.
async function askCheck(s, label, expr, expected, how = 'mouse') {
  await s.ev(`(() => { window.__rowEvents = []; return true; })()`);
  let found;
  if (how === 'mouse') {
    found = await clickEl(s, expr);
  } else {
    found = await s.ev(`(() => { const b = ${expr}; if (!b) return false;
      b.scrollIntoView({ block: 'center', behavior: 'instant' }); b.focus(); return document.activeElement === b; })()`);
    if (found) await s.key(how);
  }
  if (!found) {
    check(`${label}: Ask button found`, false, expr);
    return false;
  }
  check(`${label}: chat panel shown`, await s.waitFor(chatShown, 5000));
  const st = await s.ev(`(() => ({
    value: ${chatValue},
    focused: ${chatFocused},
    rowEvents: (window.__rowEvents || []).slice(),
    side: getComputedStyle(document.getElementById('side-panel')).display,
    source: getComputedStyle(document.getElementById('source-panel')).display,
    nav: document.querySelector('.nav-link[data-panel="chat"]').classList.contains('active'),
  }))()`);
  check(`${label}: the chat input holds the question`, st.value === expected, { got: st.value, want: expected });
  check(`${label}: focus is in the chat input`, st.focused === true);
  check(`${label}: the row's own action did not run`, st.rowEvents.length === 0, st.rowEvents);
  check(`${label}: the graph was not opened`, st.side === 'none', st.side);
  check(`${label}: the source viewer was not opened`, st.source === 'none', st.source);
  check(`${label}: the Chat nav link is active`, st.nav === true);
  return true;
}

const Q_GRAPH = 'Give me an overview of this knowledge graph: what are its main topics and most important entities?';
const Q_STATUS = "What does the epistemic status distribution say about how well supported this graph's claims are?";
const Q_DISEASE = 'What are the most important Disease entities in this graph, and how do they connect?';
const Q_COMPOUND = 'What are the most important Compound entities in this graph, and how do they connect?';
const C1 = 'Systemic Hypertension — Glp-1(7-37)';
const C2 = 'Cilofexor / Denifanstat / Efruxifermin';
const Q_C1 = `Summarize the ${C1} community.`;
const Q_C2 = `Summarize the ${C2} community.`;
const Q_HUB1 = 'What is semaglutide, and why is it so connected in this graph?';
const Q_HUB2 = 'What is Obesity, and why is it so connected in this graph?';
const Q_HUB3 = 'What is GLP-1 receptor, and why is it so connected in this graph?';
const Q_CARD1 = 'Why do sources disagree on whether semaglutide is indicated for Obesity?';
const Q_DOC1 = 'Summarize the document pmid_38851997: what are its key findings?';
const PATENT = 'patent_06_us10370426b2_triple_agonist';
const PATENT_NAME = 'patent_06_US10370426B2_triple_agonist';
// The name differs from the id only by letter case, so the id is not repeated
// (10-REVIEW IN-06).
const Q_PATENT = `Summarize the document ${PATENT_NAME}: what are its key findings?`;

const NARROW_SECTIONS = ['.dashboard-entity-summary', 'section.start-here', 'section.documents-section'];

async function askAbout() {
  const s = await session();
  await load(s);
  check('dashboard opens', await openDashboard(s));

  // (a) data anchors from the API, so data drift and product bugs are told apart
  const api = await s.ev(`(async () => {
    const d = await (await fetch('/api/dashboard')).json();
    const items = (d.epistemic && d.epistemic.sections || []).reduce((n, sec) => n + (sec.items || []).length, 0);
    return {
      types: Object.keys(d.entity_counts || {}),
      communities: (d.start_here && d.start_here.communities || []).map((c) => c.full_label),
      hubs: (d.start_here && d.start_here.hubs || []).map((h) => h.name),
      items,
      firstQuestion: d.epistemic && d.epistemic.sections && d.epistemic.sections[0] && d.epistemic.sections[0].items[0].question,
      status: (d.epistemic && d.epistemic.status_counts || []).length,
      docs: (d.documents || []).map((x) => [x.doc_id, x.display_name]),
      findings: d.findings,
    };
  })()`);
  check('data: 13 entity types', api.types.length === 13, api.types.length);
  check('data: 10 communities, c1 and c2 full labels', api.communities.length === 10 && api.communities[0] === C1 && api.communities[1] === C2,
    api.communities.slice(0, 2));
  check('data: 10 hubs, semaglutide then Obesity', api.hubs.length === 10 && api.hubs[0] === 'semaglutide' && api.hubs[1] === 'Obesity', api.hubs.slice(0, 3));
  check('data: 37 epistemic items, first question', api.items === 37 && api.firstQuestion === Q_CARD1, [api.items, api.firstQuestion]);
  check('data: 6 status counts', api.status === 6, api.status);
  check('data: 34 documents, [0] and [3] names', api.docs.length === 34 && api.docs[0][0] === 'pmid_38851997' && api.docs[0][1] === 'pmid_38851997'
    && api.docs[3][0] === PATENT && api.docs[3][1] === PATENT_NAME, [api.docs[0], api.docs[3]]);
  check('data: no findings', Array.isArray(api.findings) && api.findings.length === 0, api.findings);

  // (b) counts, anatomy and placement
  const census = await s.ev(`(() => {
    const all = [...document.querySelectorAll(${q(ASK)})];
    const byKind = {};
    for (const b of all) { const k = b.getAttribute('data-ask'); byKind[k] = (byKind[k] || 0) + 1; }
    return {
      total: all.length,
      byKind,
      hidden: all.filter((b) => b.offsetParent === null).length,
      bad: all.filter((b) => !(b.type === 'button' && b.textContent === 'Ask about this' && b.title === ${q(ASK_TITLE)}
        && (b.getAttribute('aria-label') || '').startsWith('Ask about this: '))).map((b) => [b.getAttribute('data-ask'), b.textContent, b.getAttribute('aria-label')]).slice(0, 3),
    };
  })()`);
  const derived = api.types.filter((t) => t.trim()).length + 1 + api.communities.length + api.hubs.length + api.items
    + (api.status ? 1 : 0) + api.docs.length + api.findings.length;
  check('Ask count is 106 and equals the API-derived sum', census.total === 106 && census.total === derived, [census.total, derived]);
  const wantKinds = { graph: 1, type: 13, community: 10, hub: 10, epistemic: 37, 'epistemic-status': 1, document: 34 };
  check('Ask count per kind, and no other data-ask value', Object.keys(census.byKind).length === Object.keys(wantKinds).length
    && Object.entries(wantKinds).every(([k, n]) => census.byKind[k] === n), census.byKind);
  check('52 Ask buttons sit in collapsed rows', census.hidden === 52, census.hidden);
  check('every Ask: button type, text, title, aria-label prefix', census.total > 0 && census.bad.length === 0, census.bad);
  const arias = await s.ev(`(() => { const a = (b) => (b ? b.getAttribute('aria-label') : null); return {
    disease: a(${typeAsk('DISEASE')}), c1: a(${commAsk('c1')}), hub: a(${hubAsk(0)}),
    card: a(${secBtn('contradictions', 'ask-chat', 0)}), status: a(${STATUS_ASK}), doc: a(${docAsk('pmid_38851997')}), totals: a(${TOTALS_ASK}),
  }; })()`);
  check('aria: DISEASE row', arias.disease === 'Ask about this: Disease entities', arias.disease);
  check('aria: c1', arias.c1 === `Ask about this: the ${C1} community`, arias.c1);
  check('aria: first hub', arias.hub === 'Ask about this: semaglutide', arias.hub);
  check('aria: first contradiction card', arias.card === 'Ask about this: semaglutide is indicated for Obesity', arias.card);
  check('aria: status distribution', arias.status === 'Ask about this: the epistemic status distribution', arias.status);
  check('aria: first document', arias.doc === 'Ask about this: pmid_38851997', arias.doc);
  check('aria: totals', arias.totals === 'Ask about this: the knowledge graph', arias.totals);
  const place = await s.ev(`(() => {
    const rowAsks = [...document.querySelectorAll(${q(ASK)})].filter((b) => ['type', 'community', 'hub', 'document'].includes(b.getAttribute('data-ask')));
    const misplaced = rowAsks.filter((b) => {
      const p = b.parentElement;
      const tr = b.closest('tr');
      const startRow = b.getAttribute('data-ask') === 'community' || b.getAttribute('data-ask') === 'hub';
      return !(p && p.matches('div.dashboard-row-actions') && tr && p.parentElement === tr.cells[0]
        && b.previousElementSibling && b.previousElementSibling.matches('.dashboard-link-btn')
        && (!startRow || p.classList.contains('start-action')));
    }).map((b) => [b.getAttribute('data-ask'), b.parentElement && b.parentElement.className]);
    const heads = (sel) => { const t = document.querySelector(sel); return t ? t.querySelectorAll('thead th').length : -1; };
    const cards = [...document.querySelectorAll('#dashboard-content .epistemic-actions')];
    const status = ${STATUS_ASK};
    return {
      rowAsks: rowAsks.length,
      misplaced: misplaced.slice(0, 3),
      heads: [heads('.dashboard-entity-summary table'), heads('.start-communities-table'), heads('.start-hubs-table'), heads('.documents-table')],
      cols: document.querySelectorAll('.documents-table col').length,
      cardsOk: cards.length === 37 && cards.every((a) => a.children.length === 2 && a.children[1].matches('button.ask-about-btn[data-action="ask-chat"]')),
      statusAfterCounts: !!status && !!status.previousElementSibling && status.previousElementSibling.matches('p.epistemic-counts'),
      injected: document.querySelectorAll('#dashboard-content img, #dashboard-content script').length,
    };
  })()`);
  check('placement: 67 row Ask buttons, each after the main button in the first cell slot', place.rowAsks === 67 && place.misplaced.length === 0,
    [place.rowAsks, place.misplaced]);
  check('placement: header cells unchanged (2, 2, 4, 3) and 3 cols', JSON.stringify(place.heads) === '[2,2,4,3]' && place.cols === 3, [place.heads, place.cols]);
  check('placement: every epistemic card Ask is second in .epistemic-actions', place.cardsOk === true);
  check('placement: the status Ask follows p.epistemic-counts', place.statusAfterCounts === true);
  check('no img/script in the dashboard', place.injected === 0, place.injected);
  await s.ev(`(document.querySelector('.dashboard-entity-summary') || document.body).scrollIntoView({ block: 'start', behavior: 'instant' })`);
  await s.shot('dashboard-ask-buttons.png');

  // (c) pointer activation, one card of every kind
  const spy = await armSpies(s);
  const m0 = await s.ev(`document.getElementById('messages').children.length`);
  const pointer = [
    ['totals', TOTALS_ASK, Q_GRAPH],
    ['DISEASE row', typeAsk('DISEASE'), Q_DISEASE],
    ['c1 community', commAsk('c1'), Q_C1],
    ['first hub', hubAsk(0), Q_HUB1],
    ['first contradiction card', secBtn('contradictions', 'ask-chat', 0), Q_CARD1],
    ['status distribution', STATUS_ASK, Q_STATUS],
    ['first document', docAsk('pmid_38851997'), Q_DOC1],
  ];
  for (const [label, expr, expected] of pointer) {
    await openDashboard(s);
    await askCheck(s, `mouse ${label}`, expr, expected, 'mouse');
  }
  await sleep(1000);
  check('pointer: no /api/chat request', !spy.urls.some((u) => u.includes('/api/chat')) && spy.chat === 0, spy.chat);
  check('pointer: no new chat message', (await s.ev(`document.getElementById('messages').children.length`)) === m0);

  // (d) keyboard activation
  await openDashboard(s);
  await askCheck(s, 'Enter on the second hub', hubAsk(1), Q_HUB2, 'Enter');
  await openDashboard(s);
  await askCheck(s, 'Space on c2', commAsk('c2'), Q_C2, 'Space');

  // (e) Tab order and focus ring
  await openDashboard(s);
  const tabbed = await s.ev(`(() => { const m = ${typeMain('DISEASE')}; if (!m) return false;
    m.scrollIntoView({ block: 'center', behavior: 'instant' }); m.focus(); return document.activeElement === m; })()`);
  check('setup: the DISEASE main button has focus', tabbed === true);
  await s.key('Tab');
  const ring = await s.ev(`(() => { const a = ${typeAsk('DISEASE')}; const f = document.activeElement;
    const cs = f ? getComputedStyle(f) : null;
    return { onAsk: !!a && f === a, style: cs && cs.outlineStyle, width: cs && cs.outlineWidth, color: cs && cs.outlineColor }; })()`);
  check('Tab moves from the DISEASE main button to its Ask', ring.onAsk === true, ring);
  check('the focused Ask shows a 2px solid accent outline', ring.onAsk === true && ring.style === 'solid' && ring.width === '2px'
    && ring.color === 'rgb(74, 108, 247)', ring);

  // (f) a typed draft is replaced and Undo restores it; a previous prefill too
  const draft = 'my own unsent draft';
  await s.ev(`document.querySelector('.nav-link[data-panel=chat]').click()`);
  check('setup: chat shown for the draft', await s.waitFor(chatShown, 5000));
  await s.ev(`(() => { const i = document.getElementById('chat-input'); i.value = ''; i.focus(); i.select(); return true; })()`);
  await s.send('Input.insertText', { text: draft });
  check('setup: the draft is typed', (await s.ev(chatValue)) === draft, await s.ev(chatValue));
  await openDashboard(s);
  if (await askCheck(s, 'COMPOUND row over a draft', typeAsk('COMPOUND'), Q_COMPOUND, 'mouse')) {
    const undone = await s.ev(`(() => { const i = document.getElementById('chat-input'); i.focus(); document.execCommand('undo'); return i.value; })()`);
    check('Undo brings the draft back', undone === draft, undone);
  }
  await openDashboard(s);
  if (await askCheck(s, 'c1 over the draft', commAsk('c1'), Q_C1, 'mouse')) {
    await openDashboard(s);
    if (await askCheck(s, 'first hub over a prefill', hubAsk(0), Q_HUB1, 'mouse')) {
      const back = await s.ev(`(() => { const i = document.getElementById('chat-input'); i.focus(); document.execCommand('undo'); return i.value; })()`);
      check('Undo brings the previous prefill back', back === Q_C1, back);
    }
  }

  // (g) the textarea grows to show a long question (O-1)
  await s.viewport(700, 1000);
  await s.ev(`document.querySelector('.nav-link[data-panel=chat]').click()`);
  await s.waitFor(chatShown, 5000);
  const h0 = await s.ev(`(() => { const i = document.getElementById('chat-input'); i.value = ''; i.style.height = '';
    i.dispatchEvent(new Event('input')); return i.offsetHeight; })()`);
  await openDashboard(s);
  if (await askCheck(s, 'patent document at 700px', docAsk(PATENT), Q_PATENT, 'mouse')) {
    const grown = await s.ev(`(() => { const i = document.getElementById('chat-input');
      return { h: i.offsetHeight, style: i.style.height, want: Math.min(i.scrollHeight, 120) + 'px' }; })()`);
    check('the textarea grew past its one-row height', grown.h > h0, [h0, grown]);
    check('the textarea height follows the auto-resize rule', grown.style === grown.want, grown);
    // The click leaves the pointer over a starter card (a hover border, not
    // focus): move it off the chat panel so the shot shows only the prefill.
    const hoveredBefore = await s.ev(`document.querySelectorAll('.starter-card:hover').length`);
    await s.send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: 5, y: 990, button: 'none', buttons: 0 });
    await sleep(300);
    const shotState = await s.ev(`({ hovered: document.querySelectorAll('.starter-card:hover').length, focused: ${chatFocused} })`);
    check('screenshot: no starter card is hovered and focus is still in the chat input', shotState.hovered === 0
      && shotState.focused === true, { hoveredBefore, ...shotState });
    await s.shot('chat-ask-prefilled.png');
  }
  await s.viewport(1440, 1000);

  // (h) narrow sections
  await openDashboard(s);
  const narrowAt = (w) => s.ev(`(async () => {
    const secs = ${JSON.stringify(NARROW_SECTIONS)}.map((sel) => document.querySelector(sel)).filter(Boolean);
    for (const sec of secs) sec.style.width = '${w}px';
    await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
    const rendered = (root) => [...root.querySelectorAll('button.ask-about-btn')].filter((b) => b.offsetParent !== null);
    const rowAsks = secs.flatMap((sec) => rendered(sec).filter((b) => b.closest('.dashboard-row-actions')));
    const more = (b) => { const m = b.querySelector('.ask-about-btn__more'); return m ? getComputedStyle(m).display : 'missing'; };
    const totals = document.querySelector('.dashboard-totals .ask-about-btn');
    const cardAsks = [...document.querySelectorAll('.epistemic-actions .ask-about-btn')].filter((b) => b.offsetParent !== null);
    const firstDoc = document.querySelector('.documents-table tbody tr.dashboard-doc-row');
    const docMain = firstDoc && firstDoc.querySelector('.dashboard-doc-btn');
    const docAskEl = firstDoc && firstDoc.querySelector('.ask-about-btn');
    return {
      secs: secs.length,
      rowAsks: rowAsks.length,
      rowShort: rowAsks.filter((b) => more(b) !== 'none' || b.textContent !== 'Ask about this' || b.getBoundingClientRect().width >= 60)
        .map((b) => [b.getAttribute('data-ask'), more(b), b.getBoundingClientRect().width]).slice(0, 3),
      totalsMore: totals ? more(totals) : 'missing',
      cardMore: cardAsks.length ? cardAsks.map(more) : ['missing'],
      wraps: secs.flatMap((sec) => [...sec.querySelectorAll('.dashboard-table-wrap')].map((x) => [x.scrollWidth, x.clientWidth])),
      small: secs.flatMap((sec) => rendered(sec)).filter((b) => { const r = b.getBoundingClientRect(); return r.width < 28 || r.height < 28; })
        .map((b) => [b.getAttribute('data-ask'), b.getBoundingClientRect().width, b.getBoundingClientRect().height]).slice(0, 3),
      docWrap: docMain && docAskEl ? [docAskEl.getBoundingClientRect().top, docMain.getBoundingClientRect().bottom] : null,
    };
  })()`);
  const n520 = await narrowAt(520);
  check('520px: row Ask buttons show only "Ask" and stay under 60px', n520.secs === 3 && n520.rowAsks > 0 && n520.rowShort.length === 0, n520);
  check('520px: the totals Ask keeps its full text', n520.totalsMore !== 'none' && n520.totalsMore !== 'missing', n520.totalsMore);
  check('520px: the epistemic Ask buttons keep their full text', n520.cardMore.every((d) => d !== 'none' && d !== 'missing'), n520.cardMore.slice(0, 3));
  for (const w of [640, 420, 320]) {
    const n = await narrowAt(w);
    check(`${w}px: no table wrap overflows`, n.wraps.length > 0 && n.wraps.every(([sw, cw]) => sw <= cw), n.wraps);
    check(`${w}px: every rendered Ask is at least 28x28`, n.rowAsks > 0 && n.small.length === 0, n.small);
    if (w === 320) {
      check('320px: the first document Ask wraps under its main button', !!n.docWrap && n.docWrap[0] >= n.docWrap[1] - 1, n.docWrap);
      await s.ev(`(document.querySelector('section.documents-section') || document.body).scrollIntoView({ block: 'start', behavior: 'instant' })`);
      await s.shot('dashboard-ask-narrow.png');
    }
  }
  await s.ev(`(() => { for (const sel of ${JSON.stringify(NARROW_SECTIONS)}) { const x = document.querySelector(sel); if (x) x.style.width = ''; } return true; })()`);

  // (i) computed style
  const STYLE = `(() => { const b = ${typeAsk('DISEASE')}; const c = ${secBtn('contradictions', 'ask-chat', 0)};
    if (!b) return null; const cs = getComputedStyle(b);
    return { fontSize: cs.fontSize, fontWeight: cs.fontWeight, minHeight: cs.minHeight, borderWidth: cs.borderTopWidth,
      borderColor: cs.borderTopColor, background: cs.backgroundColor, display: cs.display, width: b.offsetWidth,
      cardMin: c ? getComputedStyle(c).minHeight : null }; })()`;
  const st = await s.ev(STYLE);
  check('style: a type-row Ask is 13px / 400 / min-height 28px', !!st && st.fontSize === '13px' && st.fontWeight === '400' && st.minHeight === '28px', st);
  check('style: 1px #e5e7eb border on white', !!st && st.borderWidth === '1px' && st.borderColor === 'rgb(229, 231, 235)'
    && st.background === 'rgb(255, 255, 255)', st);
  // A flex item's computed display is always blockified, so the width is the
  // proof that the legacy full-width block rule no longer applies.
  check('style: inline-sized, not the legacy full-width block', !!st && st.width > 0 && st.width < 140, st);
  check('style: a card Ask keeps min-height 36px', !!st && st.cardMin === '36px', st);

  // (j) Present mode changes nothing on the Dashboard
  await s.ev(`document.body.classList.add('present')`);
  const pst = await s.ev(STYLE);
  check('present: the type-row Ask has the same size', !!st && !!pst && pst.fontSize === st.fontSize && pst.minHeight === st.minHeight
    && pst.width === st.width, [st, pst]);
  await askCheck(s, 'present: third hub', hubAsk(2), Q_HUB3, 'mouse');
  await s.ev(`document.body.classList.remove('present')`);

  // (k) positive controls: the spies can see a row action and a real send
  await openDashboard(s);
  await s.ev(`(() => { window.__rowEvents = []; return true; })()`);
  await clickEl(s, typeMain('DISEASE'));
  await s.waitFor(`getComputedStyle(document.getElementById('side-panel')).display === 'flex'`, 5000);
  const ctl = await s.ev(`({ events: (window.__rowEvents || []).slice(), side: getComputedStyle(document.getElementById('side-panel')).display })`);
  check('control: the DISEASE main button fires graph-show-types and opens the graph', ctl.events.includes('graph-show-types') && ctl.side === 'flex', ctl);
  check('no /api/chat request since the spies were armed', spy.chat === 0 && !spy.urls.some((u) => u.includes('/api/chat')), spy.chat);
  await s.ev(`document.querySelector('.nav-link[data-panel=chat]').click()`);
  check('control: chat shown', await s.waitFor(chatShown, 5000));
  await s.ev(`(() => { document.getElementById('chat-input').value = 'positive control';
    document.getElementById('chat-form').requestSubmit(); return true; })()`);
  let seen = false;
  for (const t0 = Date.now(); Date.now() - t0 < 5000 && !seen;) {
    if (spy.chat >= 1) seen = true;
    else await sleep(100);
  }
  await sleep(1000);
  check('control: a real Send reaches the /api/chat stub exactly once', seen && spy.chat === 1, spy.chat);

  // (l)
  check('no script exceptions from the workbench', s.errors.length === 0, s.errors.slice(0, 3));
  await s.send('Fetch.disable');
  await s.done();
}

// The "Ask about this" guards (10-REVIEW rulings): after an Ask, the rest of
// the user's gesture lands on the Chat panel and must never send anything.
// Ends with a positive control: a single starter click made after the guard
// window still sends.
const messageCount = `document.getElementById('messages').children.length`;
const starterCount = `document.querySelectorAll('#messages .starter-card').length`;

async function askGuard() {
  const s = await session();
  await load(s);
  check('dashboard opens', await openDashboard(s));
  const spy = await armSpies(s);
  const m0 = await s.ev(messageCount);
  check('setup: the chat welcome shows starter cards', (await s.ev(starterCount)) > 0, await s.ev(starterCount));

  // (a) CR-01: a double-click on an Ask button. At 700x1000 the switch to the
  // Chat panel puts a starter card under the resting pointer, so the second
  // press lands on it.
  await s.viewport(700, 1000);
  const dbl = [
    ['first document', docAsk('pmid_38851997'), Q_DOC1],
    ['first hub', hubAsk(0), Q_HUB1],
    ['DISEASE row', typeAsk('DISEASE'), Q_DISEASE],
  ];
  for (const [label, expr, expected] of dbl) {
    await openDashboard(s);
    await s.ev(`(() => { document.getElementById('chat-input').value = ''; return true; })()`);
    const pt = await centreOf(s, expr);
    if (!pt) {
      check(`double-click ${label}: Ask button found`, false, expr);
      continue;
    }
    await s.dblclick(pt.x, pt.y);
    await sleep(1000);
    const st = await s.ev(`(() => { const u = document.elementFromPoint(${pt.x}, ${pt.y}); return {
      value: ${chatValue}, focused: ${chatFocused}, shown: ${chatShown}, messages: ${messageCount},
      under: u ? String(u.className || u.tagName) : null }; })()`);
    // Precondition: the second press really lands on a starter card, so the
    // guard is what keeps it from sending (10 branch review IN-04).
    check(`double-click ${label}: the pointer rests on a starter card`, !!st.under && st.under.includes('starter-card'), st.under);
    check(`double-click ${label}: no /api/chat request`, spy.chat === 0 && !spy.urls.some((u) => u.includes('/api/chat')),
      { chat: spy.chat, under: st.under });
    check(`double-click ${label}: chat shown with the question prefilled`, st.shown === true && st.value === expected,
      { got: st.value, want: expected });
    check(`double-click ${label}: focus stays in the chat input`, st.focused === true, st.under);
    check(`double-click ${label}: no new chat message`, st.messages === m0, [m0, st.messages]);
  }
  await s.viewport(1440, 1000);

  // (b) IN-04: Enter held on a focused Ask button. The first keydown activates
  // the Ask and moves focus into #chat-input; the auto-repeats land there.
  const ENTER = { key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13 };
  for (const [label, expr, expected] of [['second hub', hubAsk(1), Q_HUB2], ['first document', docAsk('pmid_38851997'), Q_DOC1]]) {
    await openDashboard(s);
    await s.ev(`(() => { document.getElementById('chat-input').value = ''; return true; })()`);
    const focused = await s.ev(`(() => { const b = ${expr}; if (!b) return false;
      b.scrollIntoView({ block: 'center', behavior: 'instant' }); b.focus(); return document.activeElement === b; })()`);
    check(`hold Enter ${label}: the Ask button has focus`, focused === true);
    if (!focused) continue;
    await s.send('Input.dispatchKeyEvent', { type: 'keyDown', ...ENTER, text: '\r' });
    for (let i = 0; i < 3; i += 1) {
      await sleep(40);
      await s.send('Input.dispatchKeyEvent', { type: 'keyDown', ...ENTER, text: '\r', autoRepeat: true });
    }
    await s.send('Input.dispatchKeyEvent', { type: 'keyUp', ...ENTER });
    await sleep(1000);
    const st = await s.ev(`({ value: ${chatValue}, focused: ${chatFocused}, shown: ${chatShown}, messages: ${messageCount} })`);
    check(`hold Enter ${label}: no /api/chat request`, spy.chat === 0 && !spy.urls.some((u) => u.includes('/api/chat')), spy.chat);
    check(`hold Enter ${label}: the question is still prefilled, unchanged`, st.shown === true && st.value === expected,
      { got: st.value, want: expected });
    check(`hold Enter ${label}: focus is in the chat input`, st.focused === true);
    check(`hold Enter ${label}: no new chat message`, st.messages === m0, [m0, st.messages]);
  }

  // (c) WR-01: a near miss 2px left of an Ask button lands in the row-actions
  // wrapper (the Ask's margin), not on a button: nothing happens.
  for (const [label, expr] of [['DISEASE row', typeAsk('DISEASE')], ['first hub', hubAsk(0)], ['first document', docAsk('pmid_38851997')]]) {
    await openDashboard(s);
    await s.ev(`(() => { window.__rowEvents = []; return true; })()`);
    const pt = await s.ev(`(() => { const b = ${expr}; if (!b) return null;
      b.scrollIntoView({ block: 'center', behavior: 'instant' });
      const r = b.getBoundingClientRect(); const x = r.left - 2; const y = r.top + r.height / 2;
      const u = document.elementFromPoint(x, y);
      return { x, y, wrapper: !!u && u.classList.contains('dashboard-row-actions') && u === b.parentElement }; })()`);
    check(`near miss ${label}: the point 2px left of Ask is the row-actions wrapper`, !!pt && pt.wrapper === true, pt);
    if (!pt) continue;
    await s.click(pt.x, pt.y);
    await sleep(600);
    const st = await s.ev(`({
      rowEvents: (window.__rowEvents || []).slice(),
      dash: document.querySelector('.nav-link[data-panel="dashboard"]').classList.contains('active'),
      side: getComputedStyle(document.getElementById('side-panel')).display,
      source: getComputedStyle(document.getElementById('source-panel')).display,
      chat: ${chatShown},
    })`);
    check(`near miss ${label}: no graph-show-types / navigate-source / focus event`, st.rowEvents.length === 0, st.rowEvents);
    check(`near miss ${label}: still on the Dashboard (no graph, viewer or chat)`, st.dash === true && st.side === 'none'
      && st.source === 'none' && st.chat === false, st);
  }
  check('near miss: no /api/chat request', spy.chat === 0, spy.chat);

  // (d) IN-01: pressing an Ask does not darken the row with the
  // .dashboard-link-row:active shade its own button gives. While the pointer
  // is on the row the hover rule wins, so the visible case is a press on the
  // button followed by a drag off the row with the button still held (the
  // :active chain stays, :hover goes). The release lands outside the row, so
  // no Ask and no row action runs.
  const HOVER_TINT = 'rgb(248, 250, 252)';
  const PRESSED = 'rgba(0, 0, 0, 0.08)';
  const OFF = { x: 1435, y: 995 };
  const pressAndDragOff = async (expr) => {
    const pt = await centreOf(s, expr);
    if (!pt) return null;
    await s.mouse('mouseMoved', pt.x, pt.y);
    await s.mouse('mousePressed', pt.x, pt.y);
    await sleep(400);  // past the 0.15s background transition
    const onRow = await s.ev(`(() => { const tr = (${expr}).closest('tr'); return getComputedStyle(tr).backgroundColor; })()`);
    await s.send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: OFF.x, y: OFF.y, button: 'left', buttons: 1 });
    await sleep(400);
    const off = await s.ev(`(() => { const b = ${expr}; const tr = b.closest('tr');
      return { bg: getComputedStyle(tr).backgroundColor, active: b.matches(':active'), hovered: tr.matches(':hover') }; })()`);
    await s.mouse('mouseReleased', OFF.x, OFF.y);
    await sleep(200);
    return { onRow, ...off };
  };
  for (const [label, expr] of [['DISEASE row', typeAsk('DISEASE')], ['first hub', hubAsk(0)], ['first document', docAsk('pmid_38851997')]]) {
    await openDashboard(s);
    await s.ev(`(() => { window.__rowEvents = []; return true; })()`);
    const st = await pressAndDragOff(expr);
    check(`press ${label} Ask: the row keeps the hover tint under the pointer`, !!st && st.onRow === HOVER_TINT, st);
    check(`press ${label} Ask and drag off: the Ask is still pressed, the row not hovered`, !!st && st.active === true && st.hovered === false, st);
    check(`press ${label} Ask and drag off: the row does not take the pressed shade`, !!st && st.bg !== PRESSED, st);
    const after = await s.ev(`({ ev: (window.__rowEvents || []).slice(), chat: ${chatShown} })`);
    check(`press ${label} Ask and drag off: the release runs nothing`, after.ev.length === 0 && after.chat === false, after);
  }
  // Control: the same gesture on the row's own main button darkens the row.
  await openDashboard(s);
  const ctlPress = await pressAndDragOff(typeMain('DISEASE'));
  check('press control: the DISEASE main button pressed and dragged off darkens the row', !!ctlPress && ctlPress.bg === PRESSED, ctlPress);
  check('press: no /api/chat request', spy.chat === 0, spy.chat);

  // (z) positive control: past the guard window (2000 ms) a single starter click sends.
  await sleep(2200);
  await s.ev(`document.querySelector('.nav-link[data-panel=chat]').click()`);
  check('control: chat shown', await s.waitFor(chatShown, 5000));
  const before = spy.chat;
  const card = await centreOf(s, `document.querySelector('#messages .starter-card')`);
  check('control: a visible starter card is there', !!card && card.x > 0 && card.y > 0, card);
  if (card) await s.click(card.x, card.y);
  let sent = false;
  for (const t0 = Date.now(); Date.now() - t0 < 5000 && !sent;) {
    if (spy.chat > before) sent = true;
    else await sleep(100);
  }
  await sleep(1000);
  check('control: a single starter click after the guard window sends exactly once', sent && spy.chat === before + 1,
    [before, spy.chat]);
  // Only repeated Enters are guarded: a fresh Enter in the chat box still sends.
  const beforeEnter = spy.chat;
  await s.ev(`(() => { const i = document.getElementById('chat-input'); i.value = 'enter control'; i.focus(); return true; })()`);
  await s.key('Enter');
  let enterSent = false;
  for (const t0 = Date.now(); Date.now() - t0 < 5000 && !enterSent;) {
    if (spy.chat > beforeEnter) enterSent = true;
    else await sleep(100);
  }
  await sleep(1000);
  check('control: a fresh Enter in the chat box sends exactly once', enterSent && spy.chat === beforeEnter + 1, [beforeEnter, spy.chat]);

  check('no script exceptions from the workbench', s.errors.length === 0, s.errors.slice(0, 3));
  await s.send('Fetch.disable');
  await s.done();
}

const FINDINGS_API = [
  { rule_name: '<img src=x onerror=1>', total: 1, errors: 0, by_severity: { low: 1 } },
  { rule_name: 'dosing_window_conflict', total: 3, errors: 0, by_severity: { high: 2, low: 1 } },
  { rule_name: 'label_gap', total: 1, errors: 1, by_severity: { medium: 1 } },
];

async function askAboutFindings() {
  const s = await session();
  await load(s);
  check('dashboard opens', await openDashboard(s));

  // (a) the server path renders the fixture
  const api = await s.ev(`(async () => (await (await fetch('/api/dashboard')).json()).findings)()`);
  check('data: /api/dashboard findings are the three fixture rules', JSON.stringify(api) === JSON.stringify(FINDINGS_API), api);

  // (b) the Analysis Findings section
  const sec = await s.ev(`(() => {
    const f = document.querySelector('#dashboard-content section.findings-section');
    const d = document.querySelector('#dashboard-content section.documents-section');
    if (!f) return null;
    const h = f.querySelector('h3#findings-heading');
    const t = f.querySelector('table.findings-table');
    return {
      afterDocs: !!d && d.nextElementSibling === f,
      heading: h ? h.textContent : null,
      heads: t ? [...t.querySelectorAll('thead th')].map((x) => x.textContent) : [],
      rows: t ? [...t.querySelectorAll('tbody tr')].map((r) => [
        (r.querySelector('.findings-rule') || {}).textContent, r.cells[1] && r.cells[1].textContent, r.cells[2] && r.cells[2].textContent]) : [],
    };
  })()`);
  check('findings: the section is rendered', !!sec, sec);
  check('findings: it follows the Documents section', !!sec && sec.afterDocs === true);
  check('findings: heading Analysis Findings', !!sec && sec.heading === 'Analysis Findings', sec && sec.heading);
  check('findings: headers Rule, Findings, By Severity', !!sec && JSON.stringify(sec.heads) === '["Rule","Findings","By Severity"]', sec && sec.heads);
  check('findings: row texts as before', !!sec && JSON.stringify(sec.rows) === JSON.stringify([
    ['<img src=x onerror=1>', '1', 'low: 1'], ['dosing_window_conflict', '3', 'high: 2, low: 1'], ['label_gap (1 rule error(s))', '1', 'medium: 1']]),
  sec && sec.rows);
  check('findings: no img/script in the dashboard', (await s.ev(`document.querySelectorAll('#dashboard-content img, #dashboard-content script').length`)) === 0);

  // (c) counts
  const counts = await s.ev(`(() => ({ total: document.querySelectorAll(${q(ASK)}).length,
    finding: document.querySelectorAll('#dashboard-content [data-ask="finding"]').length,
    aria: (${findingAsk(2)} || { getAttribute: () => null }).getAttribute('aria-label') }))()`);
  check('Ask count is 109 with the findings rows', counts.total === 109, counts.total);
  check('three finding Ask buttons', counts.finding === 3, counts.finding);
  check('label_gap Ask aria-label', counts.aria === 'Ask about this: the label_gap findings', counts.aria);

  // (d) prefill
  const spy = await armSpies(s);
  await openDashboard(s);
  await askCheck(s, 'mouse label_gap', findingAsk(2), 'Explain the label_gap findings (1): which ones matter most and why?', 'mouse');
  await openDashboard(s);
  await askCheck(s, 'Enter dosing_window_conflict', findingAsk(1), 'Explain the dosing_window_conflict findings (3): which ones matter most and why?', 'Enter');
  await openDashboard(s);
  await askCheck(s, 'mouse hostile rule', findingAsk(0), 'Explain the <img src=x onerror=1> findings (1): which ones matter most and why?', 'mouse');
  check('the hostile rule name created no img element', (await s.ev(`document.querySelectorAll('img').length`)) === 0);
  await sleep(1000);
  check('no /api/chat request', spy.chat === 0 && !spy.urls.some((u) => u.includes('/api/chat')), spy.chat);

  // (e)
  await openDashboard(s);
  await s.ev(`(document.querySelector('section.findings-section') || document.body).scrollIntoView({ block: 'start', behavior: 'instant' })`);
  await s.shot('dashboard-findings-ask.png');

  // (f) narrow
  const narrow = await s.ev(`(async () => {
    const f = document.querySelector('section.findings-section');
    if (!f) return null;
    f.style.width = '520px';
    await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
    const m = f.querySelector('.ask-about-btn .ask-about-btn__more');
    const more = m ? getComputedStyle(m).display : 'missing';
    f.style.width = '320px';
    await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
    const w = f.querySelector('.dashboard-table-wrap');
    const wrap = w ? [w.scrollWidth, w.clientWidth] : null;
    f.style.width = '';
    return { more, wrap };
  })()`);
  check('520px: the findings Ask shows only "Ask"', !!narrow && narrow.more === 'none', narrow);
  check('320px: the findings table does not overflow', !!narrow && !!narrow.wrap && narrow.wrap[0] <= narrow.wrap[1], narrow);

  // (g)
  check('no script exceptions from the workbench', s.errors.length === 0, s.errors.slice(0, 3));
  await s.send('Fetch.disable');
  await s.done();
}

try {
  if (MODE === 'early') await early();
  else if (MODE === 'epistemic') await epistemic();
  else if (MODE === 'epistemic-early') await epistemicEarly();
  else if (MODE === 'epistemic-legacy') await epistemicLegacy();
  else if (MODE === 'documents') await documents();
  else if (MODE === 'card-highlight') await cardHighlight();
  else if (MODE === 'citations') await citations();
  else if (MODE === 'fda-highlight') await fdaHighlight();
  else if (MODE === 'start-here') await startHere();
  else if (MODE === 'start-here-early') await startHereEarly();
  else if (MODE === 'ask-about') await askAbout();
  else if (MODE === 'ask-about-findings') await askAboutFindings();
  else if (MODE === 'ask-guard') await askGuard();
  else await click();
} catch (e) {
  check('script completed', false, String(e && e.stack || e));
}
console.log(JSON.stringify({ passed: passedCount, failed: failures }));
process.exit(failures.length ? 1 : 0);
