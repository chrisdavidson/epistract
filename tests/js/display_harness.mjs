// Behavioral harness for the workbench display.js single color source.
// Imports the real display.js against a stub DOM and a stub fetch that serves
// the /api/graph/entity-types payload given as argv[2].
// Prints one JSON line {"passed": [...], "failed": [...]} and exits 1 on failure.
import { pathToFileURL, fileURLToPath } from 'node:url';
import path from 'node:path';
import fs from 'node:fs';

const violations = [];

function makeEl(id = '', tagName = '', namespaceURI = null) {
  const listeners = {};
  const attrs = {};
  const classes = new Set();
  const el = {
    id,
    tagName,
    namespaceURI,
    attributes: attrs,
    classList: {
      add: (...c) => c.forEach((x) => classes.add(x)),
      remove: (...c) => c.forEach((x) => classes.delete(x)),
      contains: (c) => classes.has(c),
    },
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
      violations.push(`innerHTML set on <${tagName}>`);
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
  createElement: (tag) => makeEl('', String(tag).toLowerCase(), null),
  createElementNS: (ns, tag) => makeEl('', String(tag), ns),
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

  // (g) swatch geometry, hostile shapes, hollow state
  const SVG_NS = 'http://www.w3.org/2000/svg';
  const expectedTag = {
    dot: 'circle', square: 'rect', diamond: 'polygon', triangle: 'polygon',
    triangleDown: 'polygon', hexagon: 'polygon', star: 'polygon',
  };
  const shapeSeen = {};
  display.setDisplayData(payload);
  for (const t of payload.types) shapeSeen[t.shape] = t;
  const synth = {
    types: Object.keys(expectedTag).map((shape, i) => ({
      type: `T_${shape}`, color: '#1f77b4', shape, family: 'F', label: `L ${shape}`,
      description: '', count: i,
    })),
    families: [{ name: 'F' }],
  };
  display.setDisplayData(synth);
  for (const shape of Object.keys(expectedTag)) {
    const svg = display.makeSwatch(`T_${shape}`);
    const child = svg.children[0];
    check(`g: ${shape} svg ns`, svg.tagName === 'svg' && svg.namespaceURI === SVG_NS, `${svg.tagName} ${svg.namespaceURI}`);
    check(`g: ${shape} one child`, svg.children.length === 1, String(svg.children.length));
    check(`g: ${shape} tag`, child && child.tagName === expectedTag[shape], child && child.tagName);
    check(`g: ${shape} fill`, child && child.getAttribute('fill') === '#1f77b4', child && child.getAttribute('fill'));
    check(`g: ${shape} aria`, svg.getAttribute('aria-hidden') === 'true' && svg.getAttribute('focusable') === 'false');
    check(`g: ${shape} class`, svg.getAttribute('class') === 'type-swatch');
    check(`g: ${shape} viewBox`, svg.getAttribute('viewBox') === '0 0 16 16');
  }
  const tamperedSwatch = {
    types: [{ type: 'EVIL', color: '#1f77b4', shape: 'script', family: 'F', label: 'Evil', description: '', count: 1 }],
    families: [],
  };
  display.setDisplayData(tamperedSwatch);
  const evil = display.makeSwatch('EVIL');
  check('g: hostile shape is circle', evil.children[0].tagName === 'circle', evil.children[0].tagName);
  check('g: hostile shape neutral fill', evil.children[0].getAttribute('fill') === '#1f77b4' || evil.children[0].getAttribute('fill') === '#6b7280');
  const unk = display.makeSwatch('NOT_IN_DATA');
  check('g: unknown type circle', unk.children[0].tagName === 'circle', unk.children[0].tagName);
  check('g: unknown type neutral fill', unk.children[0].getAttribute('fill') === '#6b7280', unk.children[0].getAttribute('fill'));
  display.setDisplayData(synth);
  const hollow = display.makeSwatch('T_square', 16, { hollow: true });
  const hc = hollow.children[0];
  check('g: hollow fill none', hc.getAttribute('fill') === 'none', hc.getAttribute('fill'));
  check('g: hollow stroke', hc.getAttribute('stroke') === '#1f77b4', hc.getAttribute('stroke'));
  check('g: hollow stroke-width', hc.getAttribute('stroke-width') === '1.5', hc.getAttribute('stroke-width'));
  const sized = display.makeSwatch('T_dot', 12);
  check('g: size attrs', sized.getAttribute('width') === '12' && sized.getAttribute('height') === '12');

  // (h) legend chip behaviour
  const entry = {
    type: 'T_dot', color: '#1f77b4', shape: 'dot', family: 'Interventions', label: 'Compound',
    description: 'A <img src=x onerror=alert(1)> thing', count: 1234,
  };
  display.setDisplayData({ types: [entry], families: [{ name: 'Interventions' }] });
  const calls = [];
  const chip = display.buildLegendChip(entry, (type, pressed) => calls.push([type, pressed]));
  check('h: chip is button', chip.tagName === 'button', chip.tagName);
  check('h: chip type attr', chip.getAttribute('type') === 'button');
  check('h: chip class', chip.getAttribute('class') === 'legend-chip' || chip.className === 'legend-chip', chip.className);
  check('h: chip data-type', chip.getAttribute('data-type') === 'T_dot');
  check('h: chip pressed', chip.getAttribute('aria-pressed') === 'true');
  const label = chip.children.find((c) => c.className === 'legend-chip__label');
  const count = chip.children.find((c) => c.className === 'legend-chip__count');
  check('h: label text', label && label.textContent === 'Compound', label && label.textContent);
  check('h: count text', count && count.textContent === (1234).toLocaleString(), count && count.textContent);
  check('h: title is description verbatim', chip.getAttribute('title') === entry.description, chip.getAttribute('title'));
  check('h: aria-label', chip.getAttribute('aria-label') === `Compound, ${(1234).toLocaleString()}`, chip.getAttribute('aria-label'));
  const descSpan = chip.children.find((c) => c.className === 'visually-hidden');
  check('h: description span text', descSpan && descSpan.textContent === entry.description);
  check('h: describedby matches id', descSpan && descSpan.id && chip.getAttribute('aria-describedby') === descSpan.id);
  check('h: swatch first child', chip.children[0].tagName === 'svg');
  chip.dispatchEvent({ type: 'click' });
  check('h: click -> pressed false', chip.getAttribute('aria-pressed') === 'false');
  check('h: click -> hollow swatch', chip.children[0].children[0].getAttribute('fill') === 'none');
  check('h: onToggle off', calls.length === 1 && calls[0][0] === 'T_dot' && calls[0][1] === false, JSON.stringify(calls));
  chip.dispatchEvent({ type: 'click' });
  check('h: second click -> pressed true', chip.getAttribute('aria-pressed') === 'true');
  check('h: second click -> filled swatch', chip.children[0].children[0].getAttribute('fill') === '#1f77b4');
  check('h: onToggle on', calls.length === 2 && calls[1][1] === true, JSON.stringify(calls));

  const noDesc = display.buildLegendChip({ ...entry, type: 'X', description: '' }, () => {});
  check('h: title falls back to family', noDesc.getAttribute('title') === 'Interventions family', noDesc.getAttribute('title'));
  check('h: no describedby without description', noDesc.getAttribute('aria-describedby') === null);
  const second = display.buildLegendChip(entry, () => {});
  const secondId = second.children.find((c) => c.className === 'visually-hidden').id;
  check('h: description ids unique per chip', secondId && secondId !== descSpan.id, `${secondId} vs ${descSpan.id}`);

  // (i) messages
  const box = makeEl('box', 'div');
  display.renderLegendMessage(box, 'empty');
  const emptyText = box.children.map((c) => c.textContent).join(' ');
  check('i: empty heading', emptyText.includes('No entity types to show'), emptyText);
  check('i: empty body', emptyText.includes('Run /epistract:ingest to add documents'), emptyText);
  display.renderLegendMessage(box, 'error');
  const errText = box.children.map((c) => c.textContent).join(' ');
  check('i: error copy', errText.startsWith("Couldn't load entity types."), errText);
  check('i: error replaced prior', !errText.includes('No entity types'));
  check('i: error class', box.children.every((c) => c.className.includes('legend-message')));
  check('i: error modifier', box.children.some((c) => c.className.includes('legend-message--error')));

  // (j) no innerHTML anywhere
  check('j: no innerHTML setter used', violations.length === 0, violations.join('; '));
} catch (e) {
  failed.push({ name: 'harness error', detail: String((e && e.stack) || e) });
}

console.log(JSON.stringify({ passed, failed }));
process.exit(failed.length ? 1 : 0);
