// Behavioral harness for chat citation links (chat.js linkifyCitations,
// setCitationDocuments and the delegated click listener).
// Imports the real chat.js against a stub DOM. linkifyCitations walks the text
// nodes of a sanitized message element, so the harness carries a tiny HTML
// parser and serializer (browser-like: entities decoded into text nodes,
// text re-escaped on output); no CDN scripts are needed.
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

// --- tiny DOM for linkifyCitations ------------------------------------------------
// parse(html) -> root element; serialize(root) -> inner HTML, the way a browser
// would print it (text escapes & < >, attributes escape & and ").

const VOID = new Set(['img', 'br', 'hr', 'input']);
const NAMED = { amp: '&', lt: '<', gt: '>', quot: '"', apos: "'", nbsp: ' ' };
const decode = (t) => t.replace(/&(#x[0-9a-f]+|#\d+|[a-z]+);/gi, (m, e) => {
  if (e[0] === '#') return String.fromCodePoint(e[1].toLowerCase() === 'x' ? parseInt(e.slice(2), 16) : parseInt(e.slice(1), 10));
  return Object.prototype.hasOwnProperty.call(NAMED, e.toLowerCase()) ? NAMED[e.toLowerCase()] : m;
});
const escText = (t) => t.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/ /g, '&nbsp;');
const escAttr = (t) => t.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/ /g, '&nbsp;');

const miniDoc = {
  createElement(tag) { return miniEl(tag); },
  createTextNode(data) { return miniText(data); },
};
const createdBy = { elements: 0 };
function miniText(data) {
  return { nodeType: 3, nodeName: '#text', nodeValue: data, parentNode: null, ownerDocument: miniDoc };
}
function miniEl(tag) {
  createdBy.elements += 1;
  const el = {
    nodeType: 1,
    nodeName: tag.toUpperCase(),
    tag: tag.toLowerCase(),
    attrs: [],
    childNodes: [],
    parentNode: null,
    ownerDocument: miniDoc,
    setAttribute(name, value) {
      const at = el.attrs.find((a) => a[0] === name);
      if (at) at[1] = String(value); else el.attrs.push([name, String(value)]);
    },
    getAttribute(name) { const at = el.attrs.find((a) => a[0] === name); return at ? at[1] : null; },
    appendChild(c) { c.parentNode = el; el.childNodes.push(c); return c; },
    insertBefore(c, ref) {
      const i = el.childNodes.indexOf(ref);
      if (i < 0) throw new Error('insertBefore: ref is not a child');
      c.parentNode = el; el.childNodes.splice(i, 0, c); return c;
    },
    removeChild(c) {
      const i = el.childNodes.indexOf(c);
      if (i < 0) throw new Error('removeChild: not a child');
      el.childNodes.splice(i, 1); c.parentNode = null; return c;
    },
    set textContent(v) { el.childNodes = []; el.appendChild(miniText(String(v))); },
    get textContent() { return el.childNodes.map((c) => (c.nodeType === 3 ? c.nodeValue : c.textContent)).join(''); },
  };
  return el;
}

function parse(html) {
  const root = miniEl('div');
  let cur = root;
  const re = /<\/([a-z0-9]+)\s*>|<([a-z0-9]+)((?:\s+[a-z0-9_:-]+(?:="[^"]*")?)*)\s*\/?>|([^<]+)/gi;
  for (const m of html.matchAll(re)) {
    if (m[1]) { cur = cur.parentNode || root; continue; }
    if (m[2]) {
      const el = miniEl(m[2]);
      for (const a of m[3].matchAll(/([a-z0-9_:-]+)(?:="([^"]*)")?/gi)) el.setAttribute(a[1], decode(a[2] || ''));
      cur.appendChild(el);
      if (!VOID.has(el.tag)) cur = el;
      continue;
    }
    cur.appendChild(miniText(decode(m[4])));
  }
  return root;
}

function serialize(node) {
  return node.childNodes.map((c) => {
    if (c.nodeType === 3) return escText(c.nodeValue);
    const attrs = c.attrs.map(([k, v]) => ` ${k}="${escAttr(v)}"`).join('');
    return VOID.has(c.tag) ? `<${c.tag}${attrs}>` : `<${c.tag}${attrs}>${serialize(c)}</${c.tag}>`;
  }).join('');
}

// --- exports and the no-documents state --------------------------------------------

check('exports: linkifyCitations and setCitationDocuments', typeof chat.linkifyCitations === 'function' && typeof chat.setCitationDocuments === 'function');
const { setCitationDocuments } = chat;
if (typeof chat.linkifyCitations !== 'function' || typeof setCitationDocuments !== 'function') {
  console.log(JSON.stringify({ passed, failed }));
  process.exit(1);
}

// Parses html, links citations in the text nodes, returns the browser-style HTML.
const linkifyCitations = (html) => { const root = parse(html); chat.linkifyCitations(root); return serialize(root); };

check('harness: parse/serialize round-trips', serialize(parse('<p>Tom &amp; Jerry &lt;b&gt; <img alt="a&amp;b" src="x.png"></p>')) === '<p>Tom &amp; Jerry &lt;b&gt; <img alt="a&amp;b" src="x.png"></p>');
const sample = '<p>See pmid_35650449 and [Hilton Ballroom Agreement].</p>';
check('before documents are set the input is returned unchanged', linkifyCitations(sample) === sample);
check('non-element input is ignored', chat.linkifyCitations('<p>pmid_35650449</p>') === 0 && chat.linkifyCitations(null) === 0);

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
check('bare id: exact anchor markup (no data-section: a label is not a passage)', bare === '<a href="#" class="citation-link" data-doc="pmid_35650449" title="Open pmid_35650449 in the source viewer">pmid_35650449</a>', bare);
check('bare id: surrounding text and punctuation preserved', out === `<p>See ${bare}.</p>`, out);

out = linkifyCitations('<p>Per [Hilton Ballroom Agreement], the fee applies.</p>');
const named = anchors(out)[0] || '';
check('bracketed name: one link around the whole bracketed text', anchors(out).length === 1 && named.endsWith('>[Hilton Ballroom Agreement]</a>'), out);
check('bracketed name: data-doc is the known id and title uses the display name', attr(named, 'data-doc') === 'hilton_ballroom_agreement'
  && attr(named, 'title') === 'Open Hilton Ballroom Agreement in the source viewer' && attr(named, 'data-section') === null, named);

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

// --- entities, plain words, dotted tokens (WR-01) ------------------------------------------

setCitationDocuments([...DOCS,
  ...['amp', 'lt', 'gt', 'quot', '39', 'nbsp', 'notes', 'summary', 'agenda', '2', 'report-2', 'minutes'].map((id) => ({ doc_id: id, display_name: id })),
  { doc_id: 'acme_2024', display_name: 'Acme 2024' },
  { doc_id: 'release2024', display_name: 'Release 2024' },
]);
for (const [label, html] of [
  ['&amp; with id amp', '<p>Tom &amp; Jerry</p>'],
  ['&lt; &gt; with ids lt and gt', '<p>a &lt;b&gt; c</p>'],
  ['&quot; with id quot', '<p>He said &quot;hi&quot;</p>'],
  ['&#39; with id 39', "<p>it's &#39;fine&#39;</p>"],
  ['&nbsp; with id nbsp', '<p>a&nbsp;b</p>'],
  ['ids amp/lt/gt/quot/39 as plain words', '<p>amp lt gt quot 39 nbsp</p>'],
  ['plain-word ids', '<p>See the notes, the summary and the agenda in the minutes.</p>'],
  ['v1.2 with id 2', '<p>Upgrade to v1.2 or 2 now.</p>'],
  ['dashed id inside a longer dashed token', '<p>see report-2-final and old-report-2 here</p>'],
  ['bare id inside a dotted token', '<p>acme_2024.pdf and x.acme_2024</p>'],
  ['bare id inside a dashed token', '<p>old-acme_2024 and acme_2024-draft</p>'],
  ['bare id in a code span', '<p>Use <code>acme_2024</code> here</p>'],
  ['bare id in nested code inside pre', '<pre><code><span>acme_2024</span></code></pre>'],
  ['bare id inside an anchor child', '<p><a href="http://x"><em>acme_2024</em></a></p>'],
]) {
  // "Unchanged" = the same as the browser's own re-serialization of the input.
  const same = serialize(parse(html));
  check(`unchanged: ${label}`, linkifyCitations(html) === same, linkifyCitations(html));
}
out = linkifyCitations('<p>Tom &amp; Jerry: acme_2024, release2024 and [notes] and [2].</p>');
check('entity text survives next to linked ids', out.startsWith('<p>Tom &amp; Jerry: <a '), out);
check('ids with "_" or letters+digits (len >= 6) link bare; plain words and numbers link only in brackets',
  anchors(out).map((a) => attr(a, 'data-doc')).join(',') === 'acme_2024,release2024,notes,2', anchors(out).map((a) => attr(a, 'data-doc')));
out = linkifyCitations('<p>see report-2 here</p>');
check('a dashed id that qualifies (letters+digits, len >= 6) links as a whole token', anchors(out).length === 1 && attr(anchors(out)[0], 'data-doc') === 'report-2', out);
out = linkifyCitations('<p>(acme_2024). acme_2024: "acme_2024" #acme_2024 acme_2024.</p>');
check('punctuation-delimited bare ids link', anchors(out).length === 5, out);
out = linkifyCitations('<p><strong>acme_2024</strong> and <em>see [Acme 2024]</em></p>');
check('ids inside inline formatting link', anchors(out).length === 2 && out.includes('<strong><a ') && out.includes('<em>see <a '), out);
check('isBareCitableId rules', chat.isBareCitableId('pmid_35650449') && chat.isBareCitableId('abc123') && !chat.isBareCitableId('notes12'.slice(0, 5))
  && !chat.isBareCitableId('agenda') && !chat.isBareCitableId('123456') && !chat.isBareCitableId('a_b') && chat.isBareCitableId('a_b_cd'));
setCitationDocuments(DOCS);

// --- safety ------------------------------------------------------------------------------------

const hostileName = '"><img src=x onerror=1>';
setCitationDocuments([...DOCS, { doc_id: 'hostile_doc', display_name: hostileName, filename: 'h.txt' }]);
out = linkifyCitations('<p>See [&quot;&gt;&lt;img src=x onerror=1&gt;] now.</p>');
const hostileAnchor = anchors(out)[0] || '';
check('hostile name: resolves to the known id', attr(hostileAnchor, 'data-doc') === 'hostile_doc', out);
check('hostile name: title is an attribute value, escaped on output', attr(hostileAnchor, 'title') === 'Open &quot;><img src=x onerror=1> in the source viewer', hostileAnchor);
check('hostile name: the anchor text is the bracketed text, escaped', hostileAnchor.endsWith('>[&quot;&gt;&lt;img src=x onerror=1&gt;]</a>') || hostileAnchor.endsWith('>["&gt;&lt;img src=x onerror=1&gt;]</a>'), hostileAnchor);
check('hostile name: no img element in the output (only inside the quoted title value)', !/<img/i.test(out.replace(/"[^"]*"/g, '""')), out);

setCitationDocuments([...DOCS, { doc_id: '../etc/passwd', display_name: 'Traversal' }, { doc_id: 'a"b', display_name: 'Quote' }, { doc_id: 5 }, null]);
out = linkifyCitations('<p>[Traversal] [Quote] ../etc/passwd a"b</p>');
check('ids outside the safe charset are never linked', anchors(out).length === 0, out);

setCitationDocuments('not a list');
out = linkifyCitations('<p>pmid_35650449</p>');
check('a non-array leaves the previous documents in place', anchors(out).length === 1, out);

setCitationDocuments(DOCS);
const everything = linkifyCitations('<p>pmid_35650449 [Hilton Ballroom Agreement] patent_03_us10335462b2</p>');
check('no output contains onclick', !/onclick/i.test(everything), everything);
check('no output contains data-section', !/data-section/i.test(everything), everything);
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
check('click on a citation: one navigate-source with docId and no highlight', dispatched.length === 1 && dispatched[0].type === 'navigate-source'
  && dispatched[0].detail.docId === 'pmid_35650449' && !('highlight' in dispatched[0].detail) && !('section' in dispatched[0].detail), dispatched.map((d) => d.detail));

dispatched.length = 0;
ev = click(makeTarget({ dataset: { doc: 'anything_not_listed' } }));
check('click on a citation-like anchor with an unknown id: ignored', dispatched.length === 0 && ev.defaultPrevented === false, dispatched.map((d) => d.detail));
ev = click(makeTarget({ dataset: {} }));
check('click on a citation-like anchor with no id: ignored', dispatched.length === 0 && ev.defaultPrevented === false);

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
check('source: the final render sanitizes, then links text nodes', source.includes('DOMPurify.sanitize(renderMarkdown(fullResponse)') && source.includes('linkifyCitations(assistantDiv)')
  && !source.includes('DOMPurify.sanitize(linkifyCitations('));
check('source: anchors are built with DOM calls, not markup strings', !/<a href=/.test(source) && !/\.replace\(bareIdPattern/.test(source));

console.log(JSON.stringify({ passed, failed }));
process.exit(failed.length ? 1 : 0);
