// Headless-chromium checks for the standalone graph.html.
//
// usage: node static_view_cdp.mjs <cdp-port> <file-url> <mode> [screenshot-dir]
//
// Talks to an already running chromium over the DevTools protocol using only
// Node built-ins (WebSocket, fetch, fs). Prints one JSON line per check and a
// final {"passed": n, "failed": [...]} line; exits 1 when any check fails.
import fs from 'node:fs';

const [PORT, URL_, MODE = 'layout', SHOTS] = process.argv.slice(2);
if (!PORT || !URL_) {
  console.error('usage: static_view_cdp.mjs <port> <file-url> <mode> [shot-dir]');
  process.exit(2);
}

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
  const requests = [];
  ws.onmessage = (e) => {
    const m = JSON.parse(e.data);
    if (m.id && pend[m.id]) pend[m.id](m.result ?? m.error);
    else if (m.method === 'Runtime.exceptionThrown') {
      errors.push('EXC ' + JSON.stringify(m.params.exceptionDetails).slice(0, 300));
    } else if (m.method === 'Runtime.consoleAPICalled' && m.params.type === 'error') {
      errors.push('console.error ' + m.params.args.map((a) => a.value ?? a.description ?? '').join(' ').slice(0, 300));
    } else if (m.method === 'Network.requestWillBeSent') {
      requests.push(m.params.request.url);
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
  const KEYS = { Escape: 27, Tab: 9 };
  const key = async (k) => {
    const p = { key: k, code: k, windowsVirtualKeyCode: KEYS[k] };
    await send('Input.dispatchKeyEvent', { type: 'rawKeyDown', ...p });
    await send('Input.dispatchKeyEvent', { type: 'keyUp', ...p });
  };
  await send('Page.enable');
  await send('Network.enable');
  await send('Runtime.enable');
  await send('Network.setCacheDisabled', { cacheDisabled: true });
  const viewport = (width, height) => send('Emulation.setDeviceMetricsOverride', {
    width, height, deviceScaleFactor: 1, mobile: false,
  });
  const settled = `(() => { const g = window._graphDebug; if (!g) return false;
    const h = document.getElementById('graph-group-hint');
    if (h && /Arranging/.test(h.textContent)) return false;
    if (g.mode !== 'none' && g.regionGeometry().length === 0) return false;
    return true; })()`;
  const waitSettled = async (cap = 20000) => {
    const t0 = Date.now();
    while (Date.now() - t0 < cap) {
      if (await ev(settled)) break;
      await sleep(50);
    }
    await sleep(2500);
  };
  const done = async () => {
    try { await fetch(`http://127.0.0.1:${PORT}/json/close/${list.id}`); } catch { /* already gone */ }
    ws.close();
  };
  return { send, ev, shot, mouse, key, viewport, waitSettled, errors, requests, done };
}

const rect = (sel) => `(() => { const e = document.querySelector(${JSON.stringify(sel)});
  if (!e) return null; const r = e.getBoundingClientRect();
  return { top: r.top, height: r.height, width: r.width, visible: r.width > 0 && r.height > 0 }; })()`;

async function layout() {
  const s = await session();
  await s.viewport(1440, 1000);
  await s.send('Network.emulateNetworkConditions', { offline: true, latency: 0, downloadThroughput: 0, uploadThroughput: 0 });
  await s.send('Page.navigate', { url: URL_ });
  await s.waitSettled();

  check('no script errors', s.errors.length === 0, s.errors.slice(0, 3));
  const extra = s.requests.filter((u) => u !== URL_ && !u.startsWith('data:'));
  check('only the file is requested', extra.length === 0, extra.slice(0, 3));

  const c1440 = await s.ev(rect('#graph-container'));
  check('1440: canvas top <= 250', c1440 && c1440.top <= 250, c1440);
  check('1440: canvas height >= 700', c1440 && c1440.height >= 700, c1440);
  await s.shot('phase5-layout-1440.png');

  const legend = await s.ev(`(() => { const e = document.getElementById('entity-toggles');
    const r = e.getBoundingClientRect(); const chips = [...e.querySelectorAll('button')];
    const pressed = (t) => { const c = chips.find((b) => b.textContent.trim().toLowerCase().startsWith(t));
      return c ? c.getAttribute('aria-pressed') : null; };
    return { height: r.height, width: r.width, chips: chips.length,
      doc: pressed('document'), pub: pressed('publication') }; })()`);
  check('legend visible, <= 68px tall', legend.width > 0 && legend.height > 0 && legend.height <= 68, legend);
  check('legend has 13 chips', legend.chips === 13, legend.chips);
  check('Document and Publication chips are off', legend.doc === 'false' && legend.pub === 'false', legend);

  const btn0 = await s.ev(`(() => { const b = document.getElementById('static-filters-btn');
    return b ? { exp: b.getAttribute('aria-expanded'), ctl: b.getAttribute('aria-controls') } : null; })()`);
  check('Filters button closed with aria-controls', btn0 && btn0.exp === 'false' && btn0.ctl === 'static-filters-panel', btn0);

  // Opening the popover must not resize the canvas or move nodes.
  const probe = `(() => { const g = window._graphDebug;
    const ids = g.dataNodes().filter((n) => !n.hidden).slice(0, 20).map((n) => n.id);
    const p = g.network.getPositions(ids);
    return { h: document.getElementById('graph-container').getBoundingClientRect().height,
      pos: ids.map((i) => [Math.round(p[i].x * 10) / 10, Math.round(p[i].y * 10) / 10]) }; })()`;
  const before = await s.ev(probe);
  await s.ev(`document.getElementById('static-filters-btn').click()`);
  await sleep(500);
  const open = await s.ev(`(() => { const b = document.getElementById('static-filters-btn');
    const p = document.getElementById('static-filters-panel'); if (!p) return null;
    const r = p.getBoundingClientRect();
    const has = (sel) => !!p.querySelector(sel);
    return { exp: b.getAttribute('aria-expanded'), visible: r.width > 0 && r.height > 0 && !p.hidden,
      epi: has('#epistemic-toggles'), conf: has('#confidence-slider'), deg: has('#min-degree-slider'),
      rel: has('#relation-type-details') }; })()`);
  check('Filters opens the panel with all four filters',
    open && open.exp === 'true' && open.visible && open.epi && open.conf && open.deg && open.rel, open);
  const after = await s.ev(probe);
  check('canvas height unchanged by popover', before.h === after.h, [before.h, after.h]);
  check('node positions unchanged by popover', JSON.stringify(before.pos) === JSON.stringify(after.pos), null);
  await s.shot('phase5-filters-open.png');

  // Badge counts non-default filters.
  const base = await s.ev(`(() => { const sl = document.getElementById('confidence-slider');
    return { def: sl.value, hidden: window._graphDebug.dataEdges().filter((e) => e.hidden).length }; })()`);
  await s.ev(`(() => { const sl = document.getElementById('confidence-slider'); sl.value = '0.5';
    sl.dispatchEvent(new Event('input', { bubbles: true })); })()`);
  await sleep(500);
  const badge = await s.ev(`(() => { const b = document.getElementById('static-filters-btn');
    const c = b.querySelector('.count');
    return { text: c.textContent, shown: !c.hidden && c.getBoundingClientRect().width > 0,
      label: b.getAttribute('aria-label'),
      hidden: window._graphDebug.dataEdges().filter((e) => e.hidden).length }; })()`);
  check('badge shows 1 with aria-label', badge.text === '1' && badge.shown && badge.label === 'Filters, 1 active', badge);
  check('hidden edge count increases', badge.hidden > base.hidden, [base.hidden, badge.hidden]);
  await s.ev(`(() => { const sl = document.getElementById('confidence-slider'); sl.value = ${JSON.stringify(base.def)};
    sl.dispatchEvent(new Event('input', { bubbles: true })); })()`);
  await sleep(500);
  const badge0 = await s.ev(`(() => { const b = document.getElementById('static-filters-btn');
    const c = b.querySelector('.count');
    return { hidden: c.hidden || c.getBoundingClientRect().width === 0, label: b.getAttribute('aria-label') }; })()`);
  check('badge hides again at the default', badge0.hidden && !badge0.label, badge0);
  await s.ev(`document.getElementById('static-filters-btn').click()`);
  await sleep(200);

  // Esc inside the popover leaves focus mode alone.
  await s.ev(`window.dispatchEvent(new CustomEvent('graph-focus-node', { detail: { id: 'compound:semaglutide' } }))`);
  await sleep(1500);
  const f0 = await s.ev(`window._graphDebug.focus()`);
  check('focus mode entered', f0 && f0.size > 0, f0);
  await s.ev(`document.getElementById('static-filters-btn').click()`);
  await sleep(200);
  await s.ev(`document.getElementById('confidence-slider').focus()`);
  await s.key('Escape');
  await sleep(300);
  const esc = await s.ev(`(() => { const b = document.getElementById('static-filters-btn');
    const p = document.getElementById('static-filters-panel');
    return { exp: b.getAttribute('aria-expanded'), hidden: p.hidden,
      focusOnBtn: document.activeElement === b, focusSize: window._graphDebug.focus().size }; })()`);
  check('Esc closes popover and returns focus to the button', esc.exp === 'false' && esc.hidden && esc.focusOnBtn, esc);
  check('Esc keeps focus mode', esc.focusSize === f0.size, esc);
  await s.ev(`document.getElementById('static-filters-btn').click()`);
  await sleep(200);
  await s.mouse('mousePressed', 5, 600);
  await s.mouse('mouseReleased', 5, 600);
  await sleep(300);
  const outside = await s.ev(`document.getElementById('static-filters-panel').hidden`);
  check('click outside closes the popover', outside === true, outside);
  await s.ev(`window.dispatchEvent(new CustomEvent('graph-focus-exit'))`);
  await sleep(1500);

  // Tab order from the document start.
  // Reset the sequential-focus starting point to the top of the document.
  await s.ev(`(() => { document.activeElement && document.activeElement.blur(); window.scrollTo(0, 0);
    document.body.setAttribute('tabindex', '-1'); document.body.focus(); document.body.removeAttribute('tabindex'); })()`);
  const seen = [];
  const describe = `(() => { const a = document.activeElement; if (!a) return '';
    if (a.classList.contains('static-skip')) return 'skip';
    if (a.id === 'graph-search') return 'search';
    if (a.getAttribute('role') === 'radio') return 'group-radio';
    if (a.closest && a.closest('#entity-toggles')) return 'legend-chip';
    return a.id || a.tagName; })()`;
  for (let i = 0; i < 12; i++) {
    await s.key('Tab');
    const d = await s.ev(describe);
    if (seen[seen.length - 1] !== d) seen.push(d);
    if (d === 'legend-chip') break;
  }
  const want = ['skip', 'search', 'group-radio', 'graph-show-sources-btn', 'static-filters-btn',
    'edge-key-toggle', 'graph-groups-btn', 'graph-fit-btn', 'graph-reset-pins-btn', 'legend-chip'];
  check('Tab order equals visual order', JSON.stringify(seen) === JSON.stringify(want), seen);

  // Narrower viewport.
  await s.viewport(1000, 1000);
  await sleep(1200);
  const c1000 = await s.ev(rect('#graph-container'));
  check('1000: canvas top <= 250', c1000 && c1000.top <= 250, c1000);
  await s.shot('phase5-layout-1000.png');

  // Sidebar: opens at 320px, no Ask button.
  await s.viewport(1440, 1000);
  await sleep(1200);
  const pt = await s.ev(`(() => { const g = window._graphDebug;
    const p = g.network.getPositions(['compound:semaglutide'])['compound:semaglutide'];
    const d = g.network.canvasToDOM(p); const r = document.getElementById('graph-container').getBoundingClientRect();
    return { x: r.left + d.x, y: r.top + d.y }; })()`);
  await s.mouse('mouseMoved', pt.x, pt.y);
  await s.mouse('mousePressed', pt.x, pt.y);
  await s.mouse('mouseReleased', pt.x, pt.y);
  await sleep(1000);
  const side = await s.ev(`(() => { const e = document.getElementById('graph-detail-sidebar');
    const r = e.getBoundingClientRect(); const ask = e.querySelector('.graph-detail-sidebar__ask-btn');
    return { closed: e.classList.contains('graph-detail-sidebar--closed'), width: r.width,
      ask: ask ? getComputedStyle(ask).display : 'absent' }; })()`);
  check('node click opens a 320px sidebar', !side.closed && side.width === 320, side);
  check('Ask about this is not displayed', side.ask === 'none' || side.ask === 'absent', side);

  // Print.
  await s.ev(`document.getElementById('static-filters-btn').click()`);
  await s.send('Emulation.setEmulatedMedia', { media: 'print' });
  await sleep(300);
  const print = await s.ev(`(() => { const d = (sel) => getComputedStyle(document.querySelector(sel)).display;
    const h = document.querySelector('.static-header').getBoundingClientRect();
    const g = document.getElementById('graph-container').getBoundingClientRect();
    return { controls: d('.graph-controls'), sidebar: d('#graph-detail-sidebar'),
      popover: d('#static-filters-panel'), header: h.height > 0, canvas: g.height > 0 }; })()`);
  check('print hides controls, sidebar and popover',
    print.controls === 'none' && print.sidebar === 'none' && print.popover === 'none', print);
  check('print keeps header and canvas', print.header && print.canvas, print);
  await s.send('Emulation.setEmulatedMedia', { media: '' });

  // Reduced motion.
  await s.send('Emulation.setEmulatedMedia', { media: '', features: [{ name: 'prefers-reduced-motion', value: 'reduce' }] });
  await sleep(300);
  const rm = await s.ev(`['#static-filters-btn', '#static-filters-panel', '#graph-detail-sidebar']
    .map((sel) => getComputedStyle(document.querySelector(sel)).transitionDuration)`);
  check('reduced motion removes transitions', rm.every((v) => v === '0s'), rm);

  check('no script errors at the end', s.errors.length === 0, s.errors.slice(0, 3));
  await s.done();
}

const CARD_TITLE = "This graph couldn't be loaded";
const CARD_DAMAGED = 'The data in this file is missing or damaged. Run /epistract:view again to regenerate graph.html.';
const CARD_SCRIPT = 'Your browser could not run the graph script. Try a current version of Chrome, Edge, Firefox or Safari, or regenerate the file with /epistract:view.';
const EMPTY_BODY = 'This graph has no nodes yet. Run /epistract:ingest to add documents, then run /epistract:view again.';
const GROUP_MISSING = 'Grouping data is missing from this file. Run /epistract:view again.';
const DISPLAY_MISSING = 'Some display data is missing from this file. Run /epistract:view again to regenerate it.';

async function open(mode) {
  const s = await session();
  await s.viewport(1440, 1000);
  await s.send('Page.navigate', { url: URL_ });
  if (mode === 'no-groups' || mode === 'no-display') await s.waitSettled();
  else await sleep(3000);
  return s;
}

const cardState = `(() => { const a = document.querySelector('[role="alert"]');
  const vis = (sel) => { const e = document.querySelector(sel);
    if (!e) return 'absent'; const r = e.getBoundingClientRect();
    return (r.width > 0 && r.height > 0 && getComputedStyle(e).display !== 'none') ? 'shown' : 'hidden'; };
  return { text: a ? a.textContent : null, count: document.querySelectorAll('[role="alert"]').length,
    heading: a ? (a.querySelector('h2') || {}).textContent : null,
    filters: vis('#static-filters-btn'), toolbar: vis('.graph-toolbar'), legend: vis('#entity-toggles'),
    h1: (document.querySelector('.static-header h1') || {}).textContent }; })()`;

async function brokenPayload(mode) {
  const s = await open(mode);
  const st = await s.ev(cardState);
  check(`${mode}: alert card with heading`, st.text && st.heading === CARD_TITLE && st.count === 1, st);
  check(`${mode}: damaged-file body and regenerate hint`, st.text && st.text.includes(CARD_DAMAGED), st.text);
  check(`${mode}: no Filters button, toolbar or legend`,
    st.filters === 'absent' && st.toolbar !== 'shown' && st.legend !== 'shown', st);
  check(`${mode}: header still shows`, Boolean(st.h1), st.h1);
  const exc = s.errors.filter((e) => e.startsWith('EXC') || e.startsWith('eval'));
  const logged = s.errors.filter((e) => e.startsWith('console.error'));
  check(`${mode}: no exception loop`, exc.length === 0, exc.slice(0, 3));
  check(`${mode}: a single console.error`, logged.length <= 1, logged);
  await s.shot(`phase5-${mode}.png`);
  await s.done();
}

async function scriptError() {
  const s = await open('script-error');
  const st = await s.ev(cardState);
  check('script-error: alert card with heading', st.text && st.heading === CARD_TITLE && st.count === 1, st);
  check('script-error: script-failure body', st.text && st.text.includes(CARD_SCRIPT), st.text);
  check('script-error: no Filters button', st.filters === 'absent', st);
  const exc = s.errors.filter((e) => e.startsWith('EXC'));
  check('script-error: only the one thrown error', exc.length <= 1, exc);
  await s.shot('phase5-script-error.png');
  await s.done();
}

async function noGroups() {
  const s = await open('no-groups');
  const st = await s.ev(`(() => { const r = (m) => document.querySelector('#graph-group [data-mode="' + m + '"]');
    return { mode: window._graphDebug.mode,
      cluster: r('cluster').getAttribute('aria-disabled'), family: r('family').getAttribute('aria-disabled'),
      none: r('none').getAttribute('aria-checked'),
      title: r('cluster').getAttribute('title'),
      hint: document.getElementById('graph-group-hint').textContent }; })()`);
  check('no-groups: mode None selected', st.mode === 'none' && st.none === 'true', st);
  check('no-groups: cluster and family disabled', st.cluster === 'true' && st.family === 'true', st);
  check('no-groups: standalone hint', st.hint.includes(GROUP_MISSING) && !st.hint.includes('Reload the page'), st.hint);
  check('no-groups: standalone title', st.title === GROUP_MISSING, st.title);
  check('no-groups: no alert and no errors', (await s.ev(`document.querySelectorAll('[role="alert"]').length`)) === 0 && s.errors.length === 0, s.errors.slice(0, 3));
  await s.done();
}

async function noDisplay() {
  const s = await open('no-display');
  const st = await s.ev(`(() => { const status = document.querySelector('.static-header [role="status"]');
    const legend = document.getElementById('entity-toggles');
    return { status: status ? status.textContent : null, legend: legend ? legend.textContent : null,
      alert: document.querySelectorAll('[role="alert"]').length }; })()`);
  check('no-display: header status line', st.status === DISPLAY_MISSING, st.status);
  check('no-display: legend shows an error message', st.legend && /entity types?/i.test(st.legend) && st.legend.length > 20, st.legend);
  check('no-display: no graph-failure card', st.alert === 0, st);
  const hidden0 = await s.ev(`window._graphDebug.dataNodes().filter((n) => n.hidden).length`);
  await s.ev(`document.getElementById('graph-show-sources-btn').click()`);
  await sleep(800);
  const hidden1 = await s.ev(`window._graphDebug.dataNodes().filter((n) => n.hidden).length`);
  check('no-display: Show sources still toggles', hidden1 !== hidden0 || (await s.ev(`document.getElementById('graph-show-sources-btn').getAttribute('aria-pressed')`)) === 'true', [hidden0, hidden1]);
  const exc = s.errors.filter((e) => e.startsWith('EXC') || e.startsWith('eval'));
  check('no-display: no exceptions', exc.length === 0, exc.slice(0, 3));
  await s.done();
}

async function emptyGraph() {
  const s = await open('empty');
  const st = await s.ev(`(() => { const c = document.getElementById('graph-container');
    const h = c && c.querySelector('h2'); const p = c && c.querySelector('p');
    return { heading: h ? h.textContent : null, body: p ? p.textContent : null,
      filters: !!document.getElementById('static-filters-btn') }; })()`);
  check('empty: heading', st.heading === 'No nodes to show', st);
  check('empty: ingest next step', st.body === EMPTY_BODY, st.body);
  check('empty: Filters button exists', st.filters, st);
  const exc = s.errors.filter((e) => e.startsWith('EXC') || e.startsWith('eval'));
  check('empty: no exceptions', exc.length === 0, exc.slice(0, 3));
  await s.shot('phase5-empty.png');
  await s.done();
}

if (MODE === 'layout') {
  try {
    await layout();
  } catch (err) {
    check('script ran to completion', false, String(err && err.message).slice(0, 200));
  }
} else if (['no-graph', 'bad-json', 'script-error', 'no-groups', 'no-display', 'empty'].includes(MODE)) {
  try {
    const run = { 'no-graph': brokenPayload, 'bad-json': brokenPayload, 'script-error': scriptError,
      'no-groups': noGroups, 'no-display': noDisplay, empty: emptyGraph }[MODE];
    await run(MODE);
  } catch (err) {
    check('script ran to completion', false, String(err && err.message).slice(0, 200));
  }
} else {
  console.error('unknown mode ' + MODE);
  process.exit(2);
}
console.log(JSON.stringify({ passed: passedCount, failed: failures }));
process.exit(failures.length ? 1 : 0);
