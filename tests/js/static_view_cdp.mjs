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
    return { def: sl.value, hidden: window._graphDebug.dataNodes().filter((n) => n.hidden).length }; })()`);
  await s.ev(`(() => { const sl = document.getElementById('confidence-slider'); sl.value = '0.5';
    sl.dispatchEvent(new Event('input', { bubbles: true })); })()`);
  await sleep(500);
  const badge = await s.ev(`(() => { const b = document.getElementById('static-filters-btn');
    const c = b.querySelector('.count');
    return { text: c.textContent, shown: !c.hidden && c.getBoundingClientRect().width > 0,
      label: b.getAttribute('aria-label'),
      hidden: window._graphDebug.dataNodes().filter((n) => n.hidden).length }; })()`);
  check('badge shows 1 with aria-label', badge.text === '1' && badge.shown && badge.label === 'Filters, 1 active', badge);
  check('hidden node count increases', badge.hidden > base.hidden, [base.hidden, badge.hidden]);
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
  await s.ev(`(() => { document.activeElement && document.activeElement.blur(); window.scrollTo(0, 0); })()`);
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

if (MODE === 'layout') {
  try {
    await layout();
  } catch (err) {
    check('script ran to completion', false, String(err && err.message).slice(0, 200));
  }
} else {
  console.error('unknown mode ' + MODE);
  process.exit(2);
}
console.log(JSON.stringify({ passed: passedCount, failed: failures }));
process.exit(failures.length ? 1 : 0);
