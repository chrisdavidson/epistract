// Behavioral harness for the workbench Clear control.
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
  createElement: () => makeEl(''),
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
  check('clearChat exported', typeof chat.clearChat === 'function');
  const clear = () => reg['chat-clear-btn'].dispatchEvent(new Event('click'));

  // A: CHAT-01
  await exchange('q1', 'a1');
  check('A: messages grew before clear', reg['messages'].children.length > 1, String(reg['messages'].children.length));
  clear();
  await flush();
  const msgs = reg['messages'];
  check('A: welcome only child', msgs.children.length === 1 && msgs.children[0] === reg['welcome'], `children=${msgs.children.length}`);
  check('A: welcome visible', reg['welcome'].style.display === '', `display=${reg['welcome'].style.display}`);
  check('A: starter card preserved', reg['welcome'].children[0] === card);

  // B: CHAT-02
  calls.length = 0;
  await exchange('q1', 'a1');
  await exchange('q2', 'a2');
  await send('q3');
  const third = calls[2];
  check('B: history carries over', third?.body?.history?.length === 4, JSON.stringify(third?.body?.history));
  third.push({ type: 'done' }); third.finish(); await flush();
  clear();
  await flush();
  calls.length = 0;
  await send('after');
  check('B: history empty after clear', Array.isArray(calls[0]?.body?.history) && calls[0].body.history.length === 0, JSON.stringify(calls[0]?.body?.history));
  calls[0].push({ type: 'done' }); calls[0].finish(); await flush();
  clear(); await flush();

  // C: CHAT-03
  calls.length = 0;
  await send('streaming');
  const c = calls[0];
  c.push({ type: 'text', content: 'partial' });
  await flush();
  clear();
  await flush();
  check('C: signal aborted', c.signal?.aborted === true);
  c.queue = [{ type: 'text', content: 'late' }, { type: 'done' }];
  await flush();
  const ids = (n) => [n.className, ...n.children.flatMap(ids)];
  check('C: only welcome remains', msgs.children.length === 1 && msgs.children[0] === reg['welcome'], `children=${msgs.children.length}`);
  check('C: no error rendered', !ids(msgs).some((x) => String(x).includes('error-msg')) && !String(reg['welcome'].innerHTML).includes('error-msg'));
  calls.length = 0;
  await send('next');
  check('C: next send history empty', calls[0]?.body?.history?.length === 0, JSON.stringify(calls[0]?.body?.history));
  calls[0].push({ type: 'done' }); calls[0].finish(); await flush();
} catch (e) {
  failed.push({ name: 'harness error', detail: String(e && e.stack || e) });
}

console.log(JSON.stringify({ passed, failed }));
process.exit(failed.length ? 1 : 0);
