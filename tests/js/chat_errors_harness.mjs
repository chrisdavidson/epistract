// Behavioral harness for chat error rendering (ERR-01..03).
// Imports the real chat.js against a stub DOM and a controllable stub fetch.
// Prints one JSON line {"passed": [...], "failed": [...]} and exits 1 on failure.
import { pathToFileURL, fileURLToPath } from 'node:url';
import path from 'node:path';

function makeEl(id = '') {
  const listeners = {};
  const el = {
    id,
    className: '',
    textContent: '',
    value: '',
    scrollTop: 0,
    scrollHeight: 0,
    style: {},
    children: [],
    parentNode: null,
    _html: '',
    get innerHTML() { return this._html; },
    set innerHTML(v) {
      this._html = String(v);
      if (v === '') this.children.forEach((c) => { c.parentNode = null; }), (this.children = []);
    },
    get firstChild() { return this.children[0] || null; },
    appendChild(c) {
      if (c.parentNode) c.parentNode.removeChild(c);
      c.parentNode = this;
      this.children.push(c);
      return c;
    },
    removeChild(c) {
      this.children = this.children.filter((x) => x !== c);
      c.parentNode = null;
      return c;
    },
    remove() { if (this.parentNode) this.parentNode.removeChild(this); },
    replaceChildren(...nodes) {
      this.children.forEach((c) => { c.parentNode = null; });
      this.children = [];
      nodes.forEach((n) => this.appendChild(n));
    },
    contains(n) { return this.children.includes(n); },
    addEventListener(type, fn) { (listeners[type] ||= []).push(fn); },
    dispatchEvent(evt) {
      (listeners[evt.type] || []).forEach((fn) => fn({ ...evt, type: evt.type, preventDefault() {} }));
      return true;
    },
    focus() { this.focused = true; },
  };
  return el;
}

const created = [];
const reg = {};
for (const id of ['messages', 'welcome', 'starter-cards', 'chat-form', 'chat-input', 'model-select', 'chat-clear-btn', 'model-sort-btn']) {
  reg[id] = makeEl(id);
}
reg['model-select'].value = '';
const card = makeEl('');
card.className = 'starter-card';
card.textContent = 'Starter question';
reg['welcome'].appendChild(card);
reg['messages'].appendChild(reg['welcome']);

globalThis.document = {
  getElementById: (id) => reg[id] || null,
  createElement: (tag) => {
    const e = makeEl('');
    e.tagName = String(tag).toUpperCase();
    created.push(e);
    return e;
  },
  querySelectorAll: (sel) => (sel === '.starter-card' ? [card] : []),
};
globalThis.window = makeEl('window');

// Controllable fetch stub
const calls = [];
globalThis.fetch = (url, init = {}) => {
  const call = { url, body: init.body ? JSON.parse(init.body) : null, signal: init.signal, pending: [] };
  calls.push(call);
  const abortErr = () => new DOMException('aborted', 'AbortError');
  if (init.signal?.aborted) return Promise.reject(abortErr());
  init.signal?.addEventListener('abort', () => {
    call.pending.splice(0).forEach((p) => p.reject(abortErr()));
  });
  const enc = new TextEncoder();
  call.push = (obj) => {
    const p = call.pending.shift();
    if (p) p.resolve({ done: false, value: enc.encode('data: ' + JSON.stringify(obj) + '\n') });
    else call.queue = [...(call.queue || []), obj];
  };
  call.finish = () => {
    const p = call.pending.shift();
    if (p) p.resolve({ done: true, value: undefined });
    else call.ended = true;
  };
  const reader = {
    read() {
      if (init.signal?.aborted) return Promise.reject(abortErr());
      if (call.queue?.length) {
        const obj = call.queue.shift();
        return Promise.resolve({ done: false, value: enc.encode('data: ' + JSON.stringify(obj) + '\n') });
      }
      if (call.ended) return Promise.resolve({ done: true, value: undefined });
      return new Promise((resolve, reject) => call.pending.push({ resolve, reject }));
    },
    cancel() { return Promise.resolve(); },
  };
  return Promise.resolve({ body: { getReader: () => reader } });
};

const flush = async (n = 5) => { for (let i = 0; i < n; i++) await new Promise((r) => setTimeout(r, 0)); };

const here = path.dirname(fileURLToPath(import.meta.url));
const chat = await import(pathToFileURL(path.join(here, '../../examples/workbench/static/chat.js')).href);

const passed = [];
const failed = [];
function check(name, cond, detail = '') {
  if (cond) passed.push(name); else failed.push({ name, detail });
}

function allText(n) {
  return [n.textContent || '', n._html || '', ...n.children.map(allText)].join(' ');
}
function find(n, pred) {
  if (pred(n)) return n;
  for (const c of n.children) {
    const r = find(c, pred);
    if (r) return r;
  }
  return null;
}
const hasClass = (n, cls) => String(n.className || '').split(/\s+/).includes(cls);
const lastBubble = () => {
  const kids = reg['messages'].children.filter((c) => hasClass(c, 'chat-msg--assistant'));
  return kids[kids.length - 1];
};

async function run(events) {
  await send('q');
  const c = calls[calls.length - 1];
  for (const ev of events) {
    c.push(ev);
    await flush();
  }
  c.finish();
  await flush();
  return lastBubble();
}

async function send(q) {
  reg['chat-input'].value = q;
  reg['chat-form'].dispatchEvent(new Event('submit'));
  await flush();
}
async function exchange(q, answer) {
  await send(q);
  const c = calls[calls.length - 1];
  c.push({ type: 'text', content: answer });
  await flush();
  c.push({ type: 'done' });
  await flush();
  c.finish();
  await flush();
}

try {
  chat.initChat({ template: {} });

  // 1: error then done keeps the structured error block (Bug A)
  let b = await run([
    { type: 'error', title: 'Spending limit reached for this API key', message: 'The key has hit its limit.', hint: 'Raise the limit at settings.', detail: 'HTTP 403 from OpenRouter', content: 'x' },
    { type: 'done' },
  ]);
  let err = find(b, (n) => hasClass(n, 'error-msg'));
  check('1: error block present after done', !!err);
  const txt = err ? allText(err) : '';
  check('1: title shown', txt.includes('Spending limit reached for this API key'), txt);
  check('1: hint shown', txt.includes('Raise the limit at settings.'), txt);
  const det = err && find(err, (n) => n.tagName === 'DETAILS' && hasClass(n, 'error-detail'));
  check('1: details disclosure', !!det);
  check('1: detail text inside', !!det && allText(det).includes('HTTP 403 from OpenRouter'));
  check('1: summary label', !!det && allText(det).includes('Technical details'));

  // 2: partial answer survives an error
  b = await run([
    { type: 'text', content: 'Partial answer' },
    { type: 'error', title: 'Overloaded', message: 'Try later.', hint: 'Retry.', detail: '' },
    { type: 'done' },
  ]);
  check('2: partial kept', allText(b).includes('Partial answer'), allText(b));
  check('2: error block appended', !!find(b, (n) => hasClass(n, 'error-msg')));

  // 3: legacy content-only error
  b = await run([{ type: 'error', content: 'legacy failure text' }, { type: 'done' }]);
  err = find(b, (n) => hasClass(n, 'error-msg'));
  check('3: legacy content shown', !!err && allText(err).includes('legacy failure text'));

  // 4: done only
  b = await run([{ type: 'done' }]);
  err = find(b, (n) => hasClass(n, 'error-msg'));
  check('4: generic no-response title', !!err && allText(err).includes('No response received'));
  check('4: explanatory sentence', !!err && allText(err).includes('rate-limited, unavailable'));

  // 5: HTML in provider text stays literal
  const evil = '<img src=x onerror=alert(1)>';
  b = await run([{ type: 'error', title: evil, message: evil, hint: evil, detail: evil }, { type: 'done' }]);
  err = find(b, (n) => hasClass(n, 'error-msg'));
  check('5: literal text', !!err && allText(err).includes(evil));
  check('5: no IMG element', !created.some((e) => e.tagName === 'IMG'));
  check('5: no <img in innerHTML', !(b._html || '').includes('<img') && !(err && err._html || '').includes('<img'));
} catch (e) {
  failed.push({ name: 'harness error', detail: String(e && e.stack || e) });
}

console.log(JSON.stringify({ passed, failed }));
process.exit(failed.length ? 1 : 0);
