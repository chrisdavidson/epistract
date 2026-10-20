// Behavioral harness for the workbench display.js single color source.
// Imports the real display.js against a stub DOM and a stub fetch that serves
// the /api/graph/entity-types payload given as argv[2].
// Prints one JSON line {"passed": [...], "failed": [...]} and exits 1 on failure.
import { pathToFileURL, fileURLToPath } from 'node:url';
import path from 'node:path';
import fs from 'node:fs';

function makeEl(id = '') {
  const listeners = {};
  const attrs = {};
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
    setAttribute(name, value) { attrs[name] = String(value); },
    getAttribute(name) { return name in attrs ? attrs[name] : null; },
    removeAttribute(name) { delete attrs[name]; },
    addEventListener(type, fn) { (listeners[type] ||= []).push(fn); },
    dispatchEvent(evt) {
      (listeners[evt.type] || []).forEach((fn) => fn({ ...evt, type: evt.type, preventDefault() {} }));
      return true;
    },
    focus() { this.focused = true; },
  };
  return el;
}

globalThis.document = {
  getElementById: () => null,
  createElement: () => makeEl(''),
  createElementNS: () => makeEl(''),
  querySelectorAll: () => [],
};
globalThis.window = makeEl('window');

const payloadPath = process.argv[2];
const payload = JSON.parse(fs.readFileSync(payloadPath, 'utf8'));

let fetchCalls = 0;
globalThis.fetch = async () => {
  fetchCalls += 1;
  return { ok: true, status: 200, statusText: 'OK', json: async () => payload };
};

const here = path.dirname(fileURLToPath(import.meta.url));
const display = await import(
  pathToFileURL(path.join(here, '../../examples/workbench/static/display.js')).href
);

const passed = [];
const failed = [];
function check(name, cond, detail = '') {
  if (cond) passed.push(name); else failed.push({ name, detail });
}

try {
  // (a) loadDisplay resolves once and is cached
  const loaded = await display.loadDisplay();
  check('a: loadDisplay resolves', loaded && Array.isArray(loaded.types));
  await display.loadDisplay();
  check('a: fetch called once', fetchCalls === 1, `calls=${fetchCalls}`);

  // (b) typeDisplay / entityColor agree with the payload
  for (const t of payload.types) {
    const d = display.typeDisplay(t.type);
    check(
      `b: ${t.type} matches payload`,
      d.color === t.color && d.shape === t.shape && d.label === t.label && d.family === t.family,
      JSON.stringify(d),
    );
    check(`b: ${t.type} entityColor`, display.entityColor(t.type) === t.color);
  }

  // (c) colors unique
  const colors = payload.types.map((t) => t.color);
  check('c: colors unique', new Set(colors).size === colors.length);

  // (d) unknown type falls back to neutral
  const unknown = display.typeDisplay('NOT_A_TYPE');
  check('d: unknown color', unknown.color === '#6b7280', unknown.color);
  check('d: unknown shape', unknown.shape === 'dot', unknown.shape);
  check('d: unknown label', unknown.label === 'Not a type', unknown.label);

  // (e) legend ordering
  const entries = display.legendEntries();
  check('e: one entry per type', entries.length === payload.types.length, String(entries.length));
  let seenSources = false;
  let sourcesLast = true;
  for (const e of entries) {
    if (e.family === 'Sources') seenSources = true;
    else if (seenSources) sourcesLast = false;
  }
  check('e: Sources family last', sourcesLast);
  let countsOk = true;
  for (let i = 1; i < entries.length; i++) {
    if (entries[i].family === entries[i - 1].family && entries[i].count > entries[i - 1].count) {
      countsOk = false;
    }
  }
  check('e: counts non-increasing within family', countsOk);

  // (f) tampered payload is sanitized client-side
  const tampered = JSON.parse(JSON.stringify(payload));
  tampered.types[0].color = 'red;background:url(x)';
  tampered.types[0].shape = 'script';
  display.setDisplayData(tampered);
  const bad = display.typeDisplay(tampered.types[0].type);
  check('f: tampered color neutral', bad.color === '#6b7280', bad.color);
  check('f: tampered shape dot', bad.shape === 'dot', bad.shape);
  check('f: isHexColor rejects', display.isHexColor('red') === false && display.isHexColor('#5f66ed') === true);
} catch (e) {
  failed.push({ name: 'harness error', detail: String((e && e.stack) || e) });
}

console.log(JSON.stringify({ passed, failed }));
process.exit(failed.length ? 1 : 0);
