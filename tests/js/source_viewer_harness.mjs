// Behavioral harness for the in-workbench source viewer (source_viewer.js).
// Imports a fresh copy of the real module per scenario against a stub DOM, a
// window event bus and a controllable fetch, then checks the header, the reader
// states, Back/Esc and origin handling, latest-open-wins loading, Show in graph
// and SEC-01 (no innerHTML, hostile strings stay text).
// Prints one JSON line {"passed": [...], "failed": [...]} and exits 1 on failure.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const MODULE = path.resolve(here, '..', '..', 'examples', 'workbench', 'static', 'source_viewer.js');

const passed = [];
const failed = [];
const check = (name, cond, detail = '') => {
  if (cond) passed.push(name); else failed.push({ name, detail: JSON.stringify(detail) });
};

// --- stub DOM ---------------------------------------------------------------

let createdTags = [];
let innerHtmlWrites = [];

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
    scrollTop: 0,
    isRoot: false,
    appendChild(c) {
      if (c.parentNode) c.parentNode.removeChild(c);
      c.parentNode = el;
      el.children.push(c);
      return c;
    },
    append(...cs) {
      cs.forEach((c) => el.appendChild(typeof c === 'string' ? { textContent: c, children: [], isText: true } : c));
    },
    removeChild(c) { el.children = el.children.filter((x) => x !== c); c.parentNode = null; return c; },
    replaceChildren(...cs) {
      el.children.forEach((c) => { c.parentNode = null; });
      el.children = [];
      cs.forEach((c) => el.appendChild(c));
    },
    remove() { if (el.parentNode) el.parentNode.removeChild(el); },
    setAttribute(k, v) { attrs.set(k, String(v)); if (k === 'class') el.className = String(v); },
    getAttribute: (k) => (attrs.has(k) ? attrs.get(k) : null),
    hasAttribute: (k) => attrs.has(k),
    removeAttribute(k) { attrs.delete(k); },
    addEventListener(type, fn) { (listeners[type] = listeners[type] || []).push(fn); },
    dispatch(type, extra = {}) {
      const event = { type, target: el, detail: 0, defaultPrevented: false, preventDefault() { this.defaultPrevented = true; }, ...extra };
      for (const fn of [...(listeners[type] || [])]) fn(event);
      return event;
    },
    listenerCount: (type) => (listeners[type] || []).length,
    focus(options) { focusLog.push({ el, options }); doc.activeElement = el; },
    getClientRects() { return el.isConnected ? [{}] : []; },
    scrollIntoView() {},
    matches(sel) {
      const m = /^([a-z0-9]*)((?:\.[\w-]+)*)$/i.exec(sel);
      if (!m) return false;
      const classes = String(el.className).split(/\s+/).filter(Boolean);
      return (!m[1] || m[1].toLowerCase() === el.tagName) && m[2].split('.').filter(Boolean).every((c) => classes.includes(c));
    },
    get isConnected() {
      for (let n = el; n; n = n.parentNode) if (n.isRoot) return true;
      return false;
    },
    get textContent() { return text; },
    set textContent(v) { text = String(v); el.children = []; },
    get innerHTML() { return ''; },
    set innerHTML(v) { innerHtmlWrites.push(String(v)); },
  };
  return el;
}

let focusLog = [];
let doc;

const textOf = (n) => (n.isText ? n.textContent : (n.textContent || '') + (n.children || []).map(textOf).join(''));
const walk = (n, fn) => { if (!n) return; fn(n); (n.children || []).forEach((c) => walk(c, fn)); };
const find = (root, pred) => { const out = []; walk(root, (n) => { if (n.matches && pred(n)) out.push(n); }); return out; };
const byClass = (root, cls) => find(root, (n) => n.matches(`.${cls}`));
const byTag = (root, tag) => find(root, (n) => n.tagName === tag);
const tick = () => new Promise((r) => setTimeout(r, 0));
const settle = async () => { for (let i = 0; i < 6; i += 1) await tick(); };

// --- environment ------------------------------------------------------------

let importCounter = 0;

async function setup({ activePanel = 'dashboard', docs } = {}) {
  createdTags = [];
  innerHtmlWrites = [];
  focusLog = [];
  const registry = new Map();
  const docListeners = {};
  doc = {
    activeElement: null,
    body: makeEl('body'),
    createElement: (tag) => { createdTags.push(String(tag).toLowerCase()); return makeEl(tag); },
    createTextNode: (t) => ({ textContent: String(t), children: [], isText: true, parentNode: null }),
    getElementById: (id) => registry.get(id) || null,
    querySelector: (sel) => registry.get(`q:${sel}`) || null,
    addEventListener(type, fn) { (docListeners[type] = docListeners[type] || []).push(fn); },
    keydown(key, extra = {}) {
      const event = { type: 'keydown', key, defaultPrevented: false, preventDefault() { this.defaultPrevented = true; }, ...extra };
      for (const fn of docListeners.keydown || []) fn(event);
      return event;
    },
    listenerCount: (type) => (docListeners[type] || []).length,
  };
  doc.body.isRoot = true;
  globalThis.document = doc;

  const winListeners = {};
  globalThis.CustomEvent = class { constructor(type, init) { this.type = type; this.detail = init && init.detail; } };
  globalThis.window = {
    addEventListener(type, fn) { (winListeners[type] = winListeners[type] || []).push(fn); },
    dispatchEvent(ev) { for (const fn of [...(winListeners[ev.type] || [])]) fn(ev); return true; },
    listenerCount: (type) => (winListeners[type] || []).length,
    matchMedia: () => ({ matches: false }),
  };

  const mount = (id, tag = 'div') => {
    const e = makeEl(tag);
    doc.body.appendChild(e);
    registry.set(id, e);
    return e;
  };
  const panel = mount('source-panel', 'section');
  const dashboard = mount('dashboard-panel', 'section');
  const messages = mount('messages');
  const chatInput = mount('chat-input', 'textarea');
  const firstDocBtn = makeEl('button');
  dashboard.appendChild(firstDocBtn);
  registry.set('q:.documents-table .dashboard-doc-btn', firstDocBtn);

  // fetch: every call is recorded and answered by hand (respond/fail) unless a route answers.
  const calls = [];
  globalThis.fetch = (url, opts = {}) => new Promise((resolve, reject) => {
    const call = { url, opts, resolve, reject, done: false };
    calls.push(call);
    if (opts.signal) opts.signal.addEventListener('abort', () => { call.aborted = true; });
  });
  const respond = (call, status, body) => {
    call.done = true;
    call.resolve({ status, ok: status >= 200 && status < 300, json: async () => body });
  };
  const fail = (call) => { call.done = true; call.reject(new TypeError('network down')); };
  const pending = (url) => calls.filter((c) => c.url === url && !c.done);

  const state = { active: activePanel, switched: [], graph: [] };
  const deps = {
    switchPanel: (p) => { state.switched.push(p); state.active = p === 'sources' ? 'source' : p; },
    getActivePanel: () => state.active,
    openGraphWith: (detail, event) => state.graph.push({ detail, event }),
  };

  importCounter += 1;
  const mod = await import(`${pathToFileURL(MODULE).href}?run=${importCounter}`);
  if (docs) mod.setDocuments(docs);
  mod.initSourceViewer(deps);
  const open = (detail) => globalThis.window.dispatchEvent(new globalThis.CustomEvent('navigate-source', { detail }));
  const q = {
    title: () => byClass(panel, 'source-title')[0],
    id: () => byClass(panel, 'source-id')[0],
    meta: () => byClass(panel, 'source-meta')[0],
    back: () => byTag(panel, 'button').find((b) => b.getAttribute('id') === 'source-back-btn'),
    graphBtn: () => byTag(panel, 'button').find((b) => b.getAttribute('id') === 'source-graph-btn'),
    graphNote: () => byClass(panel, 'source-note').find((n) => n.getAttribute('id') === 'source-graph-note'),
    pdf: () => byTag(panel, 'a').find((a) => a.getAttribute('id') === 'source-pdf-link'),
    reader: () => byClass(panel, 'source-reader')[0],
    text: () => byClass(panel, 'source-text')[0],
    stateTitle: () => (byClass(panel, 'source-state__title')[0] || {}).textContent,
    stateBody: () => (byClass(panel, 'source-state__body')[0] || {}).textContent,
    status: () => byClass(panel, 'visually-hidden').find((n) => n.getAttribute('id') === 'source-status'),
    retry: () => byTag(panel, 'button').find((b) => textOf(b) === 'Try again'),
  };
  return { mod, deps, state, panel, dashboard, messages, chatInput, firstDocBtn, calls, respond, fail, pending, open, q, winListeners };
}

const DOCS = [
  { doc_id: 'doc_1', display_name: 'Doc One', filename: 'Doc One.txt', entity_count: 12, relation_count: 8, size_bytes: 3584, has_text: true, has_pdf: false },
  { doc_id: 'doc_pdf', display_name: 'PDF Doc', filename: 'PDF Doc.pdf', entity_count: 3, relation_count: 1, size_bytes: 900, has_text: true, has_pdf: true },
  { doc_id: 'doc_zero', display_name: 'Zero Doc', filename: 'Zero Doc.txt', entity_count: 0, relation_count: 0, has_text: true, has_pdf: false },
  { doc_id: 'doc_single', display_name: 'Single', filename: 'Single.txt', entity_count: 1, relation_count: 1, size_bytes: 20, has_text: true, has_pdf: false },
];

const loaded = async (env, docId, body = { doc_id: docId, text: 'Hello\nworld' }, detail = {}) => {
  env.open({ docId, ...detail });
  await settle();
  const call = env.pending(`/api/sources/${encodeURIComponent(docId)}`)[0];
  env.respond(call, 200, body);
  await settle();
  return call;
};

// --- 1. formatSize and exports ------------------------------------------------
{
  const env = await setup({ docs: DOCS });
  const { formatSize } = env.mod;
  check('exports: initSourceViewer, setDocuments, subscribeDocuments, getOrigin, formatSize',
    ['initSourceViewer', 'setDocuments', 'subscribeDocuments', 'getOrigin', 'formatSize'].every((k) => typeof env.mod[k] === 'function'));
  check('formatSize: bytes', formatSize(512) === '512 B', formatSize(512));
  check('formatSize: KB with one decimal', formatSize(3584) === '3.5 KB' && formatSize(1024) === '1.0 KB', formatSize(3584));
  check('formatSize: MB with one decimal', formatSize(1.5 * 1024 * 1024) === '1.5 MB', formatSize(1.5 * 1024 * 1024));
  check('formatSize: unknown is empty', formatSize(0) === '' && formatSize(undefined) === '' && formatSize('x') === '' && formatSize(null) === '');
  check('getOrigin: defaults to dashboard', env.mod.getOrigin() === 'dashboard');
}

// --- 2. init wiring ----------------------------------------------------------
{
  const env = await setup({ docs: DOCS });
  check('init: exactly one navigate-source listener', env.winListeners['navigate-source'].length === 1, env.winListeners['navigate-source'].length);
  check('init: exactly one keydown listener on document', env.panel && doc.listenerCount('keydown') === 1);
  env.mod.initSourceViewer(env.deps);
  check('init: a second call adds no listeners', env.winListeners['navigate-source'].length === 1 && doc.listenerCount('keydown') === 1);
  const seed = env.calls.filter((c) => c.url === '/api/sources');
  check('init: the document list is fetched once from /api/sources', seed.length === 1, env.calls.map((c) => c.url));
  check('init: the panel interior is built', !!env.q.title() && !!env.q.back() && !!env.q.graphBtn() && !!env.q.reader() && !!env.q.status());
  const reader = env.q.reader();
  check('init: reader is a focusable labelled region', reader.getAttribute('role') === 'region' && reader.getAttribute('tabindex') === '0');
  const title = env.q.title();
  check('init: title is a programmatic focus target', title.tagName === 'h2' && title.getAttribute('tabindex') === '-1' && title.getAttribute('id') === 'source-title');
  const status = env.q.status();
  check('init: live status region', status.getAttribute('role') === 'status' && status.getAttribute('aria-live') === 'polite');
  const back = env.q.back();
  check('init: back button', back.getAttribute('type') === 'button' && back.getAttribute('aria-keyshortcuts') === 'Escape' && back.getAttribute('title') === 'Back (Esc)'
    && back.className.includes('source-btn'));
  respondSeed(env, seed[0]);
  await settle();
  await loaded(env, 'doc_1');
  check('init: seeded rows feed the header', env.q.meta().textContent.includes('3.5 KB'), env.q.meta().textContent);
}

function respondSeed(env, call) {
  env.respond(call, 200, { documents: [{ doc_id: 'doc_1', size_bytes: 3584, display_name: 'Doc One' }] });
}

// --- 3. open a listed document ------------------------------------------------
{
  const env = await setup({ docs: DOCS });
  const trigger = makeEl('button');
  env.dashboard.appendChild(trigger);
  doc.activeElement = trigger;
  env.dashboard.scrollTop = 321;
  env.messages.scrollTop = 45;
  env.open({ docId: 'doc_1' });
  check('open: switchPanel called once with source', env.state.switched.length === 1 && env.state.switched[0] === 'source', env.state.switched);
  check('open: title is the display name', env.q.title().textContent === 'Doc One' && env.q.title().getAttribute('title') === 'Doc One');
  check('open: id line', env.q.id().textContent === 'doc_1');
  check('open: meta line', env.q.meta().textContent === '12 entities · 8 relations · 3.5 KB', env.q.meta().textContent);
  check('open: reader is busy and shows Loading document...', env.q.reader().getAttribute('aria-busy') === 'true'
    && textOf(env.q.reader()).trim() === 'Loading document...', textOf(env.q.reader()));
  check('open: status says Loading', env.q.status().textContent === 'Loading Doc One.', env.q.status().textContent);
  check('open: reader aria-label', env.q.reader().getAttribute('aria-label') === 'Text of Doc One');
  check('open: focus moves to the title', doc.activeElement === env.q.title());
  const call = env.calls.find((c) => c.url === '/api/sources/doc_1');
  check('open: text fetched with an abort signal', !!call && !!call.opts.signal);
  check('open: nothing happens on the Back target yet', env.mod.getOrigin() === 'dashboard');
  env.respond(call, 200, { doc_id: 'doc_1', text: 'Hello\nworld' });
  await settle();
  const texts = byClass(env.q.reader(), 'source-text');
  check('loaded: exactly one source-text div holding the text', texts.length === 1 && texts[0].tagName === 'div' && texts[0].textContent === 'Hello\nworld', texts.length);
  check('loaded: reader no longer busy and no state block', env.q.reader().getAttribute('aria-busy') === 'false' && byClass(env.q.reader(), 'source-state').length === 0);
  check('loaded: status says Opened', env.q.status().textContent === 'Opened Doc One.', env.q.status().textContent);
  check('loaded: no mark without a highlight', byTag(env.q.reader(), 'mark').length === 0);
  check('loaded: reader scrolled to the top', env.q.reader().scrollTop === 0);
  check('loaded: focus is on the title', doc.activeElement === env.q.title());
  check('loaded: Show in graph is enabled', env.q.graphBtn().getAttribute('aria-disabled') === null && !env.q.graphNote(), env.q.graphBtn().getAttribute('aria-disabled'));
  check('loaded: no PDF link for a text-only document', !env.q.pdf());

  // Back restores scroll and focus on the trigger
  env.dashboard.scrollTop = 0;
  env.messages.scrollTop = 0;
  env.q.back().dispatch('click');
  check('back: switchPanel called with the origin', env.state.switched[env.state.switched.length - 1] === 'dashboard', env.state.switched);
  check('back: dashboard scroll restored', env.dashboard.scrollTop === 321, env.dashboard.scrollTop);
  check('back: chat scroll restored', env.messages.scrollTop === 45, env.messages.scrollTop);
  check('back: focus returned to the trigger', doc.activeElement === trigger);
}

// --- 4. meta line variants ------------------------------------------------------
{
  const env = await setup({ docs: DOCS });
  await loaded(env, 'doc_single');
  check('meta: singular forms', env.q.meta().textContent === '1 entity · 1 relation · 20 B', env.q.meta().textContent);
  env.open({ docId: 'doc_zero' });
  check('meta: size omitted when unknown', env.q.meta().textContent === '0 entities · 0 relations', env.q.meta().textContent);
  env.open({ docId: 'never_listed' });
  check('meta: unknown id has no meta line', !env.q.meta().textContent && env.q.meta().hasAttribute('hidden'), env.q.meta().textContent);
  check('meta: unknown id shows the raw id as the title', env.q.title().textContent === 'never_listed' && env.q.id().textContent === 'never_listed');
}

// --- 5. legacy section, coercion, encoding --------------------------------------
{
  const env = await setup({ docs: DOCS });
  env.open({ docId: 'doc_1', section: 'old style' });
  await settle();
  check('legacy: a section-only detail opens the document', env.calls.some((c) => c.url === '/api/sources/doc_1'));
  env.open({ docId: 'a b/c?d' });
  check('encode: the id is URL-encoded in the request', env.calls.some((c) => c.url === '/api/sources/a%20b%2Fc%3Fd'), env.calls.map((c) => c.url));
  env.open({ docId: 12 });
  check('coerce: a numeric id becomes a string request', env.calls.some((c) => c.url === '/api/sources/12'));
  let threw = false;
  try { env.open({}); env.open(null); env.open({ docId: '' }); await settle(); } catch { threw = true; }
  check('coerce: missing or empty ids do not throw', !threw);
  check('coerce: an empty id shows Document not available', env.q.stateTitle() === 'Document not available', env.q.stateTitle());
  check('coerce: an empty id makes no text request', !env.calls.some((c) => c.url === '/api/sources/'));
}

// --- 6. empty, not available, error --------------------------------------------
{
  const env = await setup({ docs: DOCS });
  await loaded(env, 'doc_1', { doc_id: 'doc_1', text: '   \n\t ' });
  check('empty: title and body', env.q.stateTitle() === 'This document is empty' && env.q.stateBody() === 'No text was extracted from this document.', [env.q.stateTitle(), env.q.stateBody()]);
  check('empty: no source-text block', !env.q.text());
  await loaded(env, 'doc_pdf', { doc_id: 'doc_pdf', text: '' });
  check('empty with a PDF: extra sentence', env.q.stateBody() === 'No text was extracted from this document. Open the original PDF to read it.', env.q.stateBody());

  env.open({ docId: 'doc_1' });
  await settle();
  env.respond(env.pending('/api/sources/doc_1')[0], 404, { error: 'Document not found' });
  await settle();
  check('404: title and exact body', env.q.stateTitle() === 'Document not available'
    && env.q.stateBody() === "This document's text is not available in this output directory.", [env.q.stateTitle(), env.q.stateBody()]);
  check('404: status', env.q.status().textContent === 'Doc One: text not available.', env.q.status().textContent);
  check('404: reader no longer busy', env.q.reader().getAttribute('aria-busy') === 'false');

  env.open({ docId: 'doc_pdf' });
  await settle();
  env.respond(env.pending('/api/sources/doc_pdf')[0], 404, { error: 'x' });
  await settle();
  check('404 with a PDF: extra sentence', env.q.stateBody() === "This document's text is not available in this output directory. The original PDF is still available above.", env.q.stateBody());
}
{
  const env = await setup({ docs: DOCS });
  env.open({ docId: 'doc_1', highlight: 'keep me' });
  await settle();
  env.fail(env.pending('/api/sources/doc_1')[0]);
  await settle();
  check('error (reject): title and body', env.q.stateTitle() === "Couldn't load this document"
    && env.q.stateBody() === 'The workbench server did not respond. Check that it is still running, then try again.', [env.q.stateTitle(), env.q.stateBody()]);
  check('error: status', env.q.status().textContent === 'Could not load Doc One.', env.q.status().textContent);
  const retry = env.q.retry();
  check('error: Try again button inside the reader', !!retry && retry.className.includes('source-btn') && retry.getAttribute('type') === 'button');
  retry.focus();
  const before = env.calls.filter((c) => c.url === '/api/sources/doc_1').length;
  retry.dispatch('click');
  await settle();
  check('retry: repeats the same load', env.calls.filter((c) => c.url === '/api/sources/doc_1').length === before + 1);
  check('retry: focus stays on the button while loading', doc.activeElement === retry);
  const switchedBefore = env.state.switched.length;
  env.respond(env.pending('/api/sources/doc_1')[0], 200, { doc_id: 'doc_1', text: 'finally' });
  await settle();
  check('retry: the text renders', env.q.text() && env.q.text().textContent === 'finally');
  check('retry: focus then moves to the title', doc.activeElement === env.q.title());
  check('retry: the panel is not switched again', env.state.switched.length === switchedBefore);

  env.open({ docId: 'doc_1' });
  await settle();
  env.respond(env.pending('/api/sources/doc_1')[0], 500, { detail: 'boom' });
  await settle();
  check('error (500): same state', env.q.stateTitle() === "Couldn't load this document" && !!env.q.retry());
  env.open({ docId: 'doc_1' });
  await settle();
  env.respond(env.pending('/api/sources/doc_1')[0], 200, { doc_id: 'doc_1', text: 5 });
  await settle();
  check('error (non-text body): same state', env.q.stateTitle() === "Couldn't load this document");
}

// --- 7. unknown document and Show in graph -----------------------------------------
{
  const env = await setup({ docs: DOCS });
  env.open({ docId: 'no_such_doc' });
  await settle();
  env.respond(env.pending('/api/sources/no_such_doc')[0], 404, { error: 'x' });
  await settle();
  const g = env.q.graphBtn();
  check('unknown: Show in graph is aria-disabled', g.getAttribute('aria-disabled') === 'true' && g.getAttribute('title') === 'This document has no entities in the graph.'
    && g.getAttribute('aria-describedby') === 'source-graph-note');
  check('unknown: visible note', !!env.q.graphNote() && env.q.graphNote().textContent === 'This document has no entities in the graph, so there is nothing to focus.');
  g.dispatch('click', { detail: 1 });
  check('unknown: clicking the disabled button does nothing', env.state.graph.length === 0);

  await loaded(env, 'doc_zero');
  check('zero entities: disabled with the note', env.q.graphBtn().getAttribute('aria-disabled') === 'true' && !!env.q.graphNote());
  env.q.graphBtn().dispatch('click');
  check('zero entities: click is a no-op', env.state.graph.length === 0);

  await loaded(env, 'doc_1');
  const g2 = env.q.graphBtn();
  check('enabled: no aria-disabled, no note, enabled title', g2.getAttribute('aria-disabled') === null && !env.q.graphNote()
    && g2.getAttribute('title') === 'Focus the graph on this document and its direct connections.' && g2.getAttribute('aria-describedby') === null);
  check('enabled: aria-label', g2.getAttribute('aria-label') === 'Show Doc One in the graph', g2.getAttribute('aria-label'));
  g2.dispatch('click', { detail: 0 });
  check('enabled: openGraphWith gets the document focus and the event', env.state.graph.length === 1
    && JSON.stringify(env.state.graph[0].detail) === JSON.stringify({ reset: true, focus: { id: 'doc:doc_1', hops: 1 } })
    && env.state.graph[0].event && env.state.graph[0].event.detail === 0, env.state.graph);
  check('enabled: the viewer does not switch panels itself for the graph', !env.state.switched.includes('graph'));

  // A row that came only from /api/sources has no counts: disabled.
  const seeded = await setup({});
  seeded.mod.setDocuments([{ doc_id: 'only_listed', display_name: 'Only Listed', size_bytes: 10 }]);
  await loaded(seeded, 'only_listed');
  check('seeded without counts: Show in graph is disabled', seeded.q.graphBtn().getAttribute('aria-disabled') === 'true');
  check('seeded without counts: meta shows only the size', seeded.q.meta().textContent === '10 B', seeded.q.meta().textContent);
}

// --- 8. PDF link ----------------------------------------------------------------------
{
  const env = await setup({ docs: DOCS });
  await loaded(env, 'doc_pdf');
  const a = env.q.pdf();
  check('pdf: link present for has_pdf', !!a && a.className.includes('source-btn'));
  check('pdf: href, target and rel', a.getAttribute('href') === '/api/sources/pdf/doc_pdf' && a.getAttribute('target') === '_blank'
    && a.getAttribute('rel') === 'noopener noreferrer', [a.getAttribute('href'), a.getAttribute('rel')]);
  check('pdf: label and title', a.getAttribute('aria-label') === 'Open the original PDF of PDF Doc in a new tab' && a.getAttribute('title') === 'Opens in a new tab.');
  check('pdf: visible text with a decorative arrow', textOf(a) === 'Open original PDF ↗' && find(a, (n) => n.getAttribute && n.getAttribute('aria-hidden') === 'true').length === 1, textOf(a));
  await loaded(env, 'doc_1');
  check('pdf: link removed for the next document', !env.q.pdf());
  env.mod.setDocuments([{ doc_id: 'we ird/id', display_name: 'Weird', has_pdf: true, entity_count: 1 }]);
  env.open({ docId: 'we ird/id' });
  check('pdf: href encodes the id', env.q.pdf().getAttribute('href') === '/api/sources/pdf/we%20ird%2Fid', env.q.pdf().getAttribute('href'));
}

// --- 9. latest open wins ----------------------------------------------------------------
{
  const env = await setup({ docs: DOCS });
  env.open({ docId: 'doc_1' });
  await settle();
  const first = env.pending('/api/sources/doc_1')[0];
  env.open({ docId: 'doc_pdf' });
  await settle();
  const second = env.pending('/api/sources/doc_pdf')[0];
  check('latest: the earlier request was aborted', first.aborted === true && first.opts.signal.aborted === true);
  env.respond(second, 200, { doc_id: 'doc_pdf', text: 'second text' });
  await settle();
  env.respond(first, 200, { doc_id: 'doc_1', text: 'first text' });
  await settle();
  check('latest: a late response for the earlier open is discarded', env.q.text() && env.q.text().textContent === 'second text', env.q.text() && env.q.text().textContent);
  check('latest: header still belongs to the second document', env.q.title().textContent === 'PDF Doc');
  check('latest: status is not overwritten', env.q.status().textContent === 'Opened PDF Doc.', env.q.status().textContent);

  const e2 = await setup({ docs: DOCS });
  e2.open({ docId: 'doc_1' });
  await settle();
  const a = e2.pending('/api/sources/doc_1')[0];
  e2.open({ docId: 'doc_pdf' });
  await settle();
  e2.fail(a);
  await settle();
  check('latest: a late failure for the earlier open is ignored', e2.q.stateTitle() !== "Couldn't load this document", e2.q.stateTitle());
}

// --- 10. origin and Back label ---------------------------------------------------------
{
  const env = await setup({ docs: DOCS, activePanel: 'chat' });
  const trigger = makeEl('a');
  env.messages.appendChild(trigger);
  doc.activeElement = trigger;
  env.open({ docId: 'doc_1' });
  check('origin: chat origin gives Back to Chat', textOf(env.q.back()).includes('Back to Chat') && env.q.back().getAttribute('aria-label') === 'Back to Chat', textOf(env.q.back()));
  check('origin: getOrigin reports chat', env.mod.getOrigin() === 'chat');
  doc.activeElement = env.q.title();
  env.open({ docId: 'doc_pdf' });
  check('origin: a second open keeps the first Back target', env.mod.getOrigin() === 'chat' && textOf(env.q.back()).includes('Back to Chat'));
  env.q.back().dispatch('click');
  check('origin: Back goes to chat and focuses the citation link', env.state.switched[env.state.switched.length - 1] === 'chat' && doc.activeElement === trigger);

  const g = await setup({ docs: DOCS, activePanel: 'graph' });
  g.open({ docId: 'doc_1' });
  check('origin: graph falls back to the dashboard', g.mod.getOrigin() === 'dashboard' && textOf(g.q.back()).includes('Back to Dashboard'));

  const gone = await setup({ docs: DOCS, activePanel: 'dashboard' });
  const orphan = makeEl('button');
  gone.dashboard.appendChild(orphan);
  doc.activeElement = orphan;
  gone.open({ docId: 'doc_1' });
  orphan.parentNode.removeChild(orphan);
  gone.q.back().dispatch('click');
  check('origin: a removed trigger falls back to the first document row', doc.activeElement === gone.firstDocBtn);

  const c = await setup({ docs: DOCS, activePanel: 'chat' });
  doc.activeElement = null;
  c.open({ docId: 'doc_1' });
  c.q.back().dispatch('click');
  check('origin: with no trigger the chat input gets focus', doc.activeElement === c.chatInput);
}

// --- 11. Esc gating -----------------------------------------------------------------------
{
  const env = await setup({ docs: DOCS });
  env.open({ docId: 'doc_1' });
  const before = env.state.switched.length;
  doc.keydown('a');
  doc.keydown('Enter');
  check('esc: other keys do nothing', env.state.switched.length === before);
  const prevented = doc.keydown('Escape', { defaultPrevented: true });
  check('esc: a handled Escape is ignored', env.state.switched.length === before && prevented.defaultPrevented === true);
  doc.keydown('Escape');
  check('esc: Escape on the viewer goes back', env.state.switched.length === before + 1 && env.state.switched[before] === 'dashboard', env.state.switched);
  env.state.active = 'graph';
  doc.keydown('Escape');
  check('esc: Escape on the graph does nothing', env.state.switched.length === before + 1);
  env.state.active = 'chat';
  doc.keydown('Escape');
  check('esc: Escape on chat does nothing', env.state.switched.length === before + 1);
}

// --- 12. documents list ---------------------------------------------------------------------
{
  const env = await setup({});
  const seen = [];
  const off = env.mod.subscribeDocuments((list) => seen.push(list.map((d) => d.doc_id).join(',')));
  check('documents: a subscriber is called immediately', seen.length === 1 && seen[0] === '', seen);
  env.mod.setDocuments([{ doc_id: 'a', entity_count: 1 }, { doc_id: 'b' }]);
  env.mod.setDocuments([{ doc_id: 'a', size_bytes: 5 }, { doc_id: 'c' }]);
  check('documents: every change notifies', seen.length === 3 && seen[2] === 'a,b,c', seen);
  let merged;
  env.mod.subscribeDocuments((list) => { merged = list; });
  check('documents: rows merge by doc_id', merged.find((d) => d.doc_id === 'a').entity_count === 1 && merged.find((d) => d.doc_id === 'a').size_bytes === 5, merged);
  check('documents: subscribe returns an unsubscribe function', typeof off === 'function');
  off();
  env.mod.setDocuments([{ doc_id: 'd' }]);
  check('documents: an unsubscribed callback is not called again', seen.length === 3, seen);
  let threw = false;
  try { env.mod.setDocuments(undefined); env.mod.setDocuments('x'); env.mod.setDocuments([null, 3, {}, { doc_id: '' }]); } catch { threw = true; }
  check('documents: malformed lists are ignored without throwing', !threw);
}

// --- 13. large documents ----------------------------------------------------------------------
{
  const env = await setup({ docs: [{ doc_id: 'big', display_name: 'Big', filename: 'Big.txt', entity_count: 1, relation_count: 0, size_bytes: 2600000 }] });
  const big = 'x'.repeat(2500000);
  await loaded(env, 'big', { doc_id: 'big', text: big });
  const shown = env.q.text();
  check('large: only the first 2,000,000 characters are rendered', shown && shown.textContent.length === 2000000, shown && shown.textContent.length);
  const notes = byClass(env.q.reader(), 'source-note');
  check('large: a note explains the cut', notes.length === 1 && notes[0].textContent === 'Showing the first 2 MB of 2.5 MB. The full text is in Big.txt.', notes.map((n) => n.textContent));
  check('large: the note sits above the text', env.q.reader().children.indexOf(notes[0]) < env.q.reader().children.indexOf(shown));
  await loaded(env, 'big', { doc_id: 'big', text: 'y'.repeat(2000000) });
  check('large: exactly 2,000,000 characters are not cut', byClass(env.q.reader(), 'source-note').length === 0 && env.q.text().textContent.length === 2000000);
}

// --- 14. SEC-01 ---------------------------------------------------------------------------------
{
  const hostile = ['<img src=x onerror=1>', '"><script>alert(1)</script>'];
  const env = await setup({ docs: [{ doc_id: hostile[0], display_name: hostile[1], filename: hostile[1], entity_count: 1, relation_count: 1, has_pdf: true }] });
  createdTags = [];
  innerHtmlWrites = [];
  await loaded(env, hostile[0], { doc_id: hostile[0], text: `<script>alert(1)</script> ${hostile[1]}` });
  check('hostile: no img or script element is created', !createdTags.includes('img') && !createdTags.includes('script'), createdTags);
  check('hostile: the tree holds no img or script element', find(env.panel, (n) => n.tagName === 'img' || n.tagName === 'script').length === 0);
  check('hostile: title and id are literal text', env.q.title().textContent === hostile[1] && env.q.id().textContent === hostile[0]);
  check('hostile: document text is literal', env.q.text().textContent.startsWith('<script>alert(1)</script>'));
  check('hostile: the request path encodes the id', env.calls.some((c) => c.url === `/api/sources/${encodeURIComponent(hostile[0])}`));
  check('hostile: the PDF href encodes the id', env.q.pdf().getAttribute('href') === `/api/sources/pdf/${encodeURIComponent(hostile[0])}`);
  check('hostile: no data-derived class names', !find(env.panel, (n) => /[<>"']|onerror/i.test(String(n.className))).length);
  check('hostile: innerHTML is never assigned', innerHtmlWrites.length === 0, innerHtmlWrites);
  const source = fs.readFileSync(MODULE, 'utf8');
  check('source: the module never mentions innerHTML', !source.includes('innerHTML'));
  check('source: only one navigate-source listener and one keydown listener are registered',
    (source.match(/addEventListener\('navigate-source'/g) || []).length === 1 && (source.match(/addEventListener\('keydown'/g) || []).length === 1);
  check('source: text requests encode the id', source.includes("encodeURIComponent"));
}

process.stdout.write(JSON.stringify({ passed, failed }) + '\n');
process.exit(failed.length ? 1 : 0);
