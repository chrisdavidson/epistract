// Headless-chromium click-through checks for the live workbench Dashboard.
//
// usage: node workbench_dashboard_cdp.mjs <cdp-port> <workbench-url> <mode> [screenshot-dir]
//   mode: click  full Dashboard -> Graph flow (rows, keyboard, mouse, sources, totals)
//         early  Dashboard click fired before the graph has finished loading
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
  ws.onmessage = (e) => {
    const m = JSON.parse(e.data);
    if (m.id && pend[m.id]) pend[m.id](m.result ?? m.error);
    else if (m.method === 'Runtime.exceptionThrown') {
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
  const KEYS = {
    Escape: { code: 27 },
    Tab: { code: 9 },
    Enter: { code: 13, text: '\r' },
  };
  const key = async (k) => {
    const def = KEYS[k];
    const p = { key: k, code: k, windowsVirtualKeyCode: def.code };
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
  return { send, ev, shot, click, key, viewport, waitFor, errors, done };
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
  return s.waitFor(`document.querySelectorAll('.dashboard-link-btn').length > 0`);
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
  const rows = await s.ev(`(() => [...document.querySelectorAll('.dashboard-link-btn')].map((b) => ({
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
  await s.ev(`document.querySelector('.dashboard-link-btn[data-entity-type="COMPOUND"]').focus()`);
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
  check('dashboard still lists 13 rows', (await s.ev(`document.querySelectorAll('.dashboard-link-btn').length`)) === 13);
  const pt = await s.ev(`(() => { const r = document.querySelector('tr.dashboard-link-row[data-entity-type="DISEASE"] td.dashboard-count').getBoundingClientRect();
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
  await s.ev(`document.querySelector('.dashboard-link-btn[data-entity-type="DOCUMENT"]').click()`);
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
  // Click the COMPOUND row as soon as the Dashboard renders it, recording
  // whether the graph had finished loading at that moment.
  await s.send('Page.addScriptToEvaluateOnNewDocument', { source: `
    document.addEventListener('DOMContentLoaded', () => {
      const t = setInterval(() => {
        const b = document.querySelector('.dashboard-link-btn[data-entity-type="COMPOUND"]');
        if (!b) return;
        clearInterval(t);
        window.__early = { graphReady: !!window._graphDebug };
        b.click();
      }, 1);
    });` });
  await s.send('Page.navigate', { url: URL_ });
  check('early click fired', await s.waitFor(`!!window.__early`, 30000), await s.ev(`window.__early`));
  await s.waitFor(`!!window._graphDebug && window._graphDebug.settled`, 30000);
  const sets = await expectedSets(s);
  check('early click: COMPOUND solo visible set', await waitVisible(s, sets.COMPOUND), (await s.ev(visibleIds)).length);
  check('early click: only COMPOUND chip pressed', JSON.stringify(await s.ev(pressedChips)) === '["COMPOUND"]', await s.ev(pressedChips));
  check('early click: graph panel shown', (await s.ev(`document.getElementById('graph-panel').style.display`)) === 'flex');
  check('early click: no script exceptions', s.errors.length === 0, s.errors.slice(0, 3));
  await s.done();
}

try {
  if (MODE === 'early') await early();
  else await click();
} catch (e) {
  check('script completed', false, String(e && e.stack || e));
}
console.log(JSON.stringify({ passed: passedCount, failed: failures }));
process.exit(failures.length ? 1 : 0);
