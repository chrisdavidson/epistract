// Behavioral harness for chat citation links (chat.js linkifyCitations,
// setCitationDocuments and the delegated click listener).
// Imports the real chat.js against a stub DOM; the linkify logic is pure string
// work, so no CDN scripts are needed.
// Prints one JSON line {"passed": [...], "failed": [...]} and exits 1 on failure.
import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL, fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const MODULE = path.resolve(here, '..', '..', 'examples', 'workbench', 'static', 'chat.js');

const passed = [];
const failed = [];
const check = (name, cond, detail = '') => {
  if (cond) passed.push(name); else failed.push({ name, detail: JSON.stringify(detail) });
};

// --- stub DOM ---------------------------------------------------------------

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
    innerHTML: '',
    appendChild(c) { c.parentNode = el; el.children.push(c); return c; },
    removeChild(c) { el.children = el.children.filter((x) => x !== c); c.parentNode = null; return c; },
    replaceChildren() { el.children = []; },
    addEventListener(type, fn) { (listeners[type] ||= []).push(fn); },
    dispatchEvent(evt) { (listeners[evt.type] || []).forEach((fn) => fn(evt)); return true; },
    listenerCount: (type) => (listeners[type] || []).length,
    focus() {},
  };
  return el;
}

const reg = {};
for (const id of ['messages', 'welcome', 'starter-cards', 'chat-form', 'chat-input', 'model-select', 'chat-clear-btn', 'model-sort-btn']) {
  reg[id] = makeEl(id);
}

globalThis.document = {
  getElementById: (id) => reg[id] || null,
  createElement: () => makeEl(''),
  querySelectorAll: () => [],
};
const windowListeners = {};
const dispatched = [];
globalThis.window = {
  addEventListener(type, fn) { (windowListeners[type] ||= []).push(fn); },
  dispatchEvent(ev) { dispatched.push(ev); (windowListeners[ev.type] || []).forEach((fn) => fn(ev)); return true; },
};
globalThis.fetch = () => Promise.reject(new Error('no network in this harness'));

const chat = await import(pathToFileURL(MODULE).href);

// --- exports and the no-documents state --------------------------------------------

check('exports: linkifyCitations and setCitationDocuments', typeof chat.linkifyCitations === 'function' && typeof chat.setCitationDocuments === 'function');
const { linkifyCitations, setCitationDocuments } = chat;
if (typeof linkifyCitations !== 'function' || typeof setCitationDocuments !== 'function') {
  console.log(JSON.stringify({ passed, failed }));
  process.exit(1);
}

const sample = '<p>See pmid_35650449 and [Hilton Ballroom Agreement].</p>';
check('before documents are set the input is returned unchanged', linkifyCitations(sample) === sample);

const DOCS = [
  { doc_id: 'pmid_35650449', display_name: 'pmid_35650449', filename: 'pmid_35650449.txt' },
  { doc_id: 'patent_03_us10335462b2_semaglutide_longacting', display_name: 'patent_03_US10335462B2_semaglutide_longacting', filename: 'patent_03_us10335462b2_semaglutide_longacting.txt' },
  { doc_id: 'patent_03_us10335462b2', display_name: 'patent_03_US10335462B2', filename: 'patent_03_us10335462b2.txt' },
  { doc_id: 'hilton_ballroom_agreement', display_name: 'Hilton Ballroom Agreement', filename: 'Hilton Ballroom Agreement.pdf' },
];
setCitationDocuments(DOCS);

const anchors = (html) => [...html.matchAll(/<a\b[^>]*>[\s\S]*?<\/a>/g)].map((m) => m[0]);
const attr = (tag, name) => { const m = new RegExp(`\\s${name}="([^"]*)"`).exec(tag); return m ? m[1] : null; };

// --- resolved citations -----------------------------------------------------------------

let out = linkifyCitations('<p>See pmid_35650449.</p>');
check('bare id: wrapped in one citation link', anchors(out).length === 1, out);
const bare = anchors(out)[0] || '';
check('bare id: exact anchor markup', bare === '<a href="#" class="citation-link" data-doc="pmid_35650449" data-section="pmid_35650449" title="Open pmid_35650449 in the source viewer">pmid_35650449</a>', bare);
check('bare id: surrounding text and punctuation preserved', out === `<p>See ${bare}.</p>`, out);

out = linkifyCitations('<p>Per [Hilton Ballroom Agreement], the fee applies.</p>');
const named = anchors(out)[0] || '';
check('bracketed name: one link around the whole bracketed text', anchors(out).length === 1 && named.endsWith('>[Hilton Ballroom Agreement]</a>'), out);
check('bracketed name: data-doc is the known id and title uses the display name', attr(named, 'data-doc') === 'hilton_ballroom_agreement'
  && attr(named, 'title') === 'Open Hilton Ballroom Agreement in the source viewer' && attr(named, 'data-section') === 'Hilton Ballroom Agreement', named);

out = linkifyCitations('<p>[Hilton_Ballroom_Agreement] and [hilton ballroom agreement]</p>');
check('bracketed name: slug match is case and separator insensitive', anchors(out).length === 2, out);

out = linkifyCitations('<p>Filed as patent_03_us10335462b2_semaglutide_longacting and patent_03_us10335462b2.</p>');
const patentAnchors = anchors(out);
check('longest id wins over a shorter prefix id', patentAnchors.length === 2
  && attr(patentAnchors[0], 'data-doc') === 'patent_03_us10335462b2_semaglutide_longacting'
  && attr(patentAnchors[1], 'data-doc') === 'patent_03_us10335462b2'
  && patentAnchors[0].endsWith('>patent_03_us10335462b2_semaglutide_longacting</a>'), patentAnchors);

out = linkifyCitations('<p>pmid_35650449 twice: pmid_35650449</p>');
check('every occurrence is linked', anchors(out).length === 2, out);

// --- left unchanged ----------------------------------------------------------------------

for (const [label, html] of [
  ['unresolved bracket', '<p>See [Nonexistent Thing] here.</p>'],
  ['unknown token', '<p>See pmid_99999999 here.</p>'],
  ['checkbox x', '<p>[x] done</p>'],
  ['checkbox space', '<p>[ ] todo</p>'],
  ['markdown link text', '<p>[Hilton Ballroom Agreement](http://example.com)</p>'],
  ['id inside code', '<p>Use <code>pmid_35650449</code> here</p>'],
  ['id inside pre', '<pre><code>pmid_35650449\n[Hilton Ballroom Agreement]</code></pre>'],
  ['id inside an existing link', '<p><a href="http://x">pmid_35650449</a></p>'],
  ['bracket inside an existing link', '<p><a href="http://x">[Hilton Ballroom Agreement]</a></p>'],
  ['id inside another tag attribute', '<p><img alt="pmid_35650449" src="x.png"></p>'],
  ['id glued to a letter', '<p>xpmid_35650449</p>'],
  ['id glued to a digit', '<p>pmid_356504491</p>'],
  ['id followed by an underscore', '<p>pmid_35650449_extra</p>'],
  ['traversal-style id', '<p>[../etc/passwd] and ../pmid_35650449x</p>'],
]) {
  check(`unchanged: ${label}`, linkifyCitations(html) === html, linkifyCitations(html));
}

out = linkifyCitations('<p>Known pmid_35650449 and <code>pmid_35650449</code> and <a href="u">pmid_35650449</a> and [Nonexistent Thing].</p>');
check('mixed: only the plain-text id is linked', anchors(out).length === 2 && out.includes('<code>pmid_35650449</code>')
  && out.includes('<a href="u">pmid_35650449</a>') && out.includes('[Nonexistent Thing]'), out);

// --- safety ------------------------------------------------------------------------------------

const hostileName = '"><img src=x onerror=1>';
setCitationDocuments([...DOCS, { doc_id: 'hostile_doc', display_name: hostileName, filename: 'h.txt' }]);
out = linkifyCitations('<p>See [&quot;&gt;&lt;img src=x onerror=1&gt;] now.</p>');
const hostileAnchor = anchors(out)[0] || '';
check('hostile name: resolves to the known id', attr(hostileAnchor, 'data-doc') === 'hostile_doc', out);
check('hostile name: title and data-section are escaped', attr(hostileAnchor, 'title') === 'Open &quot;&gt;&lt;img src=x onerror=1&gt; in the source viewer'
  && attr(hostileAnchor, 'data-section') === '&quot;&gt;&lt;img src=x onerror=1&gt;', hostileAnchor);
check('hostile name: no raw img tag in the output', !/<img/i.test(out), out);

setCitationDocuments([...DOCS, { doc_id: '../etc/passwd', display_name: 'Traversal' }, { doc_id: 'a"b', display_name: 'Quote' }, { doc_id: 5 }, null]);
out = linkifyCitations('<p>[Traversal] [Quote] ../etc/passwd a"b</p>');
check('ids outside the safe charset are never linked', anchors(out).length === 0, out);

setCitationDocuments('not a list');
out = linkifyCitations('<p>pmid_35650449</p>');
check('a non-array leaves the previous documents in place', anchors(out).length === 1, out);

setCitationDocuments(DOCS);
const everything = linkifyCitations('<p>pmid_35650449 [Hilton Ballroom Agreement] patent_03_us10335462b2</p>');
check('no output contains onclick', !/onclick/i.test(everything), everything);
check('every data-doc is a known safe id', anchors(everything).every((a) => /^[a-z0-9_]+$/.test(attr(a, 'data-doc')) && DOCS.some((d) => d.doc_id === attr(a, 'data-doc'))), anchors(everything));

// A large list stays usable.
const many = Array.from({ length: 3000 }, (_, i) => ({ doc_id: `doc_${i}`, display_name: `Doc ${i}` }));
setCitationDocuments(many);
const t0 = Date.now();
out = linkifyCitations(`<p>${'filler text '.repeat(5000)} doc_2999 and doc_12</p>`);
check('3000 documents: both ids linked quickly', anchors(out).length === 2 && Date.now() - t0 < 2000, Date.now() - t0);
setCitationDocuments(DOCS);

// --- delegated click ------------------------------------------------------------------------------

chat.initChat({ template: {} });
const messages = reg['messages'];
check('init: one delegated click listener on #messages', messages.listenerCount('click') === 1, messages.listenerCount('click'));

const makeTarget = (link) => ({ closest: (sel) => (sel === 'a.citation-link[data-doc]' ? link : null) });
const click = (target) => {
  const event = { type: 'click', target, defaultPrevented: false, preventDefault() { this.defaultPrevented = true; } };
  messages.dispatchEvent(event);
  return event;
};

dispatched.length = 0;
const link = { dataset: { doc: 'pmid_35650449', section: 'pmid_35650449' } };
let ev = click(makeTarget(link));
check('click on a citation: default prevented', ev.defaultPrevented === true);
check('click on a citation: one navigate-source with docId and highlight', dispatched.length === 1 && dispatched[0].type === 'navigate-source'
  && dispatched[0].detail.docId === 'pmid_35650449' && dispatched[0].detail.highlight === 'pmid_35650449', dispatched.map((d) => d.detail));

dispatched.length = 0;
ev = click(makeTarget(null));
check('click elsewhere: nothing dispatched and default untouched', dispatched.length === 0 && ev.defaultPrevented === false);
ev = click({});
check('click on a target without closest: ignored', dispatched.length === 0 && ev.defaultPrevented === false);
ev = click(null);
check('click with no target: ignored', dispatched.length === 0);

// --- source ----------------------------------------------------------------------------------------------

const source = fs.readFileSync(MODULE, 'utf8');
check('source: no inline handlers', !/onclick/i.test(source));
check('source: no escapeAttr helper', !source.includes('escapeAttr('));
check('source: the final render still sanitizes', source.includes('DOMPurify.sanitize(linkifyCitations('));

console.log(JSON.stringify({ passed, failed }));
process.exit(failed.length ? 1 : 0);
