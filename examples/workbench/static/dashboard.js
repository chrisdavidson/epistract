// dashboard.js - DOM builders for the auto-generated Dashboard: the entity
// summary, the "Where to start" section (topic communities and the most
// connected entities), the epistemic health section and the documents table.
//
// SEC-01: entity type keys, claim text, statuses, entity names and document
// ids come from graph_data.json / claims_layer.json and are untrusted. They
// reach the DOM only through textContent and setAttribute, and are read back
// through dataset. Markup is never built from strings, no inline handlers are
// used, and class names, ids and data-section values come from fixed tables.
import { makeSwatch, legendEntries, typeKey } from './display.js';

const SWATCH_PX = 12;

function el(tag, className) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    return node;
}

function text(tag, className, value) {
    const node = el(tag, className);
    node.textContent = value;
    return node;
}

// Rows for the entity table: [{type, label, count}], largest first, label
// ascending on ties. The label is the display label for the type, else the
// raw key.
// Display label per type key, from the loaded display data.
function typeLabels() {
    return new Map(legendEntries().map(entry => [entry.type, entry.label]));
}

// The label shown for an entity type: its display label, else the raw key.
function typeLabelFor(type, labels) {
    return labels.get(typeKey(type)) || type;
}

export function sortEntityRows(entityCounts) {
    const labels = typeLabels();
    const rows = Object.entries(entityCounts || {}).map(([type, count]) => ({
        type,
        label: typeLabelFor(type, labels),
        count: Number(count) || 0,
    }));
    rows.sort((a, b) => (
        b.count - a.count
        || a.label.localeCompare(b.label, undefined, { sensitivity: 'base' })
    ));
    return rows;
}

function buildRow(row) {
    const tr = el('tr', 'dashboard-link-row');
    tr.setAttribute('data-entity-type', row.type);

    const cell = el('td', 'dashboard-link-cell');
    const btn = el('button', 'dashboard-link-btn');
    btn.setAttribute('type', 'button');
    btn.setAttribute('data-entity-type', row.type);
    btn.setAttribute(
        'aria-label',
        `Show ${row.count.toLocaleString()} ${row.label} ${row.count === 1 ? 'node' : 'nodes'} in the graph`,
    );
    const chevron = text('span', 'dashboard-link-chevron', '›');
    chevron.setAttribute('aria-hidden', 'true');
    btn.append(
        makeSwatch(row.type, SWATCH_PX),
        text('span', 'dashboard-link-label', row.label),
        chevron,
    );
    cell.appendChild(btn);

    tr.append(cell, text('td', 'dashboard-count', row.count.toLocaleString()));
    return tr;
}

function buildTable(rows, onSelectType) {
    const table = el('table', 'dashboard-table');
    const headRow = el('tr');
    headRow.append(text('th', '', 'Entity Type'), text('th', '', 'Count'));
    const thead = el('thead');
    thead.appendChild(headRow);
    const tbody = el('tbody');
    for (const row of rows) tbody.appendChild(buildRow(row));
    table.append(thead, tbody);

    // One delegated listener: a click on any part of a row (button or count
    // cell) selects that row's type.
    table.addEventListener('click', (event) => {
        const target = event && event.target;
        const row = target && typeof target.closest === 'function'
            ? target.closest('tr.dashboard-link-row')
            : null;
        if (!row) return;
        const type = row.dataset.entityType;
        if (typeof type !== 'string') return;
        if (typeof onSelectType === 'function') onSelectType(type, event);
    });

    const wrap = el('div', 'dashboard-table-wrap');
    wrap.appendChild(table);
    return wrap;
}

function strongNumber(value) {
    return text('strong', '', value.toLocaleString());
}

// The totals line is a button: it opens the graph with the default view.
function buildTotals(totalNodes, totalEdges, onShowAll) {
    const p = el('p', 'dashboard-totals');
    const btn = el('button', 'dashboard-totals-btn');
    btn.setAttribute('type', 'button');
    btn.setAttribute('data-dashboard-action', 'show-all');
    btn.setAttribute(
        'aria-label',
        `Show all ${totalNodes.toLocaleString()} entities and ${totalEdges.toLocaleString()} relationships in the graph`,
    );
    const chevron = text('span', '', '›');
    chevron.setAttribute('aria-hidden', 'true');
    btn.append(
        document.createTextNode('Total entities: '),
        strongNumber(totalNodes),
        document.createTextNode(' | Total relationships: '),
        strongNumber(totalEdges),
        document.createTextNode(' '),
        chevron,
    );
    btn.addEventListener('click', (event) => {
        if (typeof onShowAll === 'function') onShowAll(event);
    });
    p.appendChild(btn);
    return p;
}

function buildEmpty() {
    const box = el('div', 'dashboard-empty');
    box.append(
        text('p', 'dashboard-empty__title', 'No entities yet'),
        text(
            'p',
            'dashboard-empty__body',
            'The graph has no entities to summarize. Run /epistract:ingest to add documents, then reload the workbench.',
        ),
    );
    return box;
}

// The "Entity Summary" section: heading, hint, count-sorted table of
// clickable rows and the totals button. A graph without entities gets an
// explanation instead.
//   onSelectType(rawType, event)  a row was activated
//   onShowAll(event)              the totals were activated
export function buildEntitySummary({ entityCounts, totalNodes, totalEdges, onSelectType, onShowAll }) {
    const root = el('div', 'dashboard-entity-summary');
    root.appendChild(text('h3', '', 'Entity Summary'));

    const rows = sortEntityRows(entityCounts);
    const nodes = Number(totalNodes) || 0;
    const edges = Number(totalEdges) || 0;
    if (rows.length === 0 || nodes === 0) {
        root.appendChild(buildEmpty());
        return root;
    }

    root.appendChild(text('p', 'dashboard-hint', 'Select an entity type to see those nodes in the graph.'));
    root.appendChild(buildTable(rows, onSelectType));
    root.appendChild(buildTotals(nodes, edges, onShowAll));
    return root;
}

// --- Epistemic health ------------------------------------------------------

const SECTION_KEYS = [
    { key: 'contradictions', one: 'contradiction', many: 'contradictions', singular: 'Contradiction' },
    { key: 'conflicts', one: 'conflict', many: 'conflicts', singular: 'Conflict' },
    { key: 'contested_claims', one: 'contested claim', many: 'contested claims', singular: 'Contested claim' },
    { key: 'hypotheses', one: 'hypothesis', many: 'hypotheses', singular: 'Hypothesis' },
    { key: 'risks', one: 'risk', many: 'risks', singular: 'Risk' },
    { key: 'coverage_gaps', one: 'coverage gap', many: 'coverage gaps', singular: 'Coverage gap' },
];

const STATUS_CLASS = {
    asserted: 'status-asserted',
    established: 'status-asserted',
    observed: 'status-asserted',
    reported: 'status-asserted',
    confirmed: 'status-asserted',
    prophetic: 'status-prophetic',
    hypothesized: 'status-hypothesized',
    theoretical: 'status-hypothesized',
    unverified: 'status-hypothesized',
    hypothetical: 'status-hypothesized',
    contested: 'status-contested',
    contradiction: 'status-contradiction',
    negative: 'status-negative',
    speculative: 'status-speculative',
    unknown: 'status-unknown',
    unclassified: 'status-unknown',
    '': 'status-unknown',
};
const FALLBACK_CLASSES = ['status-fallback-1', 'status-fallback-2', 'status-fallback-3', 'status-fallback-4'];

const VISIBLE_CARDS = 5;
const MAX_NAMES = 3;
const MAX_QUOTES = 2;
const LABEL_TITLE_MAX = 100;

const NOT_RUN_COPY = 'Epistemic analysis has not been run for this graph. '
    + 'Run /epistract:epistemic <output-dir> to find contradictions, hypotheses and gaps.';
const NONE_FOUND_COPY = 'No contradictions, conflicts or hypotheses were found.';
const NO_GRAPH_ENTITY_TITLE = 'No entity from this item is in the graph.';
const NO_GRAPH_ENTITY_NOTE = "None of this item's entities are in the graph, so there is nothing to focus.";
const ASK_TITLE = 'Puts a question in the chat box. Nothing is sent until you press Send.';

const isObj = (v) => v !== null && typeof v === 'object' && !Array.isArray(v);
const str = (v) => (typeof v === 'string' ? v : '');

function statusLabel(status) {
    return status.replace(/_/g, ' ').replace(/(^|\s)(\S)/g, (_m, space, ch) => space + ch.toUpperCase());
}

function shareOf(count, total) {
    const pct = Math.round((count * 100) / total);
    return pct === 0 && count > 0 ? '<1%' : `${pct}%`;
}

function plural(count, one, many) {
    return count === 1 ? `1 ${one}` : `${count.toLocaleString()} ${many}`;
}

function cleanStatusCounts(raw) {
    if (!Array.isArray(raw)) return [];
    const rows = raw
        .filter((r) => isObj(r) && typeof r.status === 'string' && Number.isInteger(r.count) && r.count > 0)
        .map((r) => ({ status: r.status, count: r.count }));
    // Array.prototype.sort is stable: equal counts keep the payload order.
    return rows.sort((a, b) => b.count - a.count);
}

function cleanItem(raw) {
    const item = isObj(raw) ? raw : {};
    const entities = (Array.isArray(item.entities) ? item.entities : [])
        .filter(isObj)
        .map((e) => ({ id: str(e.id), name: str(e.name) || str(e.id), type: str(e.entity_type) }));
    const statements = (Array.isArray(item.statements) ? item.statements : [])
        .filter(isObj)
        .map((st) => ({
            text: str(st.text),
            document: str(st.document),
            confidence: typeof st.confidence === 'number' && Number.isFinite(st.confidence) ? st.confidence : null,
        }));
    const documents = (Array.isArray(item.documents) ? item.documents : []).filter((d) => typeof d === 'string' && d);
    return {
        title: str(item.title),
        entities,
        statements,
        documents,
        question: str(item.question),
    };
}

function cleanSections(raw) {
    if (!Array.isArray(raw)) return [];
    const out = [];
    for (const sec of raw) {
        if (!isObj(sec) || !Array.isArray(sec.items)) continue;
        const def = SECTION_KEYS.find((d) => d.key === sec.key);
        if (!def) continue;
        const items = sec.items.map(cleanItem);
        const count = Number.isInteger(sec.count) && sec.count >= items.length ? sec.count : items.length;
        if (count === 0) continue;
        out.push({
            def,
            label: str(sec.label) || def.singular + 's',
            description: str(sec.description),
            count,
            items,
        });
    }
    const order = SECTION_KEYS.map((d) => d.key);
    return out.sort((a, b) => order.indexOf(a.def.key) - order.indexOf(b.def.key));
}

function shortTitle(title) {
    return title.length > LABEL_TITLE_MAX ? `${title.slice(0, LABEL_TITLE_MAX)}...` : title;
}

function buildDistribution(counts) {
    const wrap = el('div', 'epistemic-status');
    const total = counts.reduce((sum, r) => sum + r.count, 0);
    wrap.appendChild(text(
        'p',
        'epistemic-hint',
        `Epistemic status of ${total.toLocaleString()} ${total === 1 ? 'relation' : 'relations'}`,
    ));

    let fallbacks = 0;
    const rows = counts.map((row) => {
        let cls = Object.prototype.hasOwnProperty.call(STATUS_CLASS, row.status.trim().toLowerCase())
            ? STATUS_CLASS[row.status.trim().toLowerCase()]
            : null;
        if (!cls) {
            cls = FALLBACK_CLASSES[fallbacks % FALLBACK_CLASSES.length];
            fallbacks += 1;
        }
        return { ...row, cls, label: statusLabel(row.status), share: shareOf(row.count, total) };
    });

    const bar = el('div', 'epistemic-bar');
    bar.setAttribute('aria-hidden', 'true');
    for (const row of rows) {
        const seg = el('span', `epistemic-bar__seg ${row.cls}`);
        seg.style.flex = `${row.count} 1 0`;
        seg.setAttribute('title', `${row.label}: ${row.count.toLocaleString()} (${row.share})`);
        bar.appendChild(seg);
    }
    wrap.appendChild(bar);

    const list = el('ul', 'epistemic-status-list');
    list.setAttribute('aria-label', 'Relations by epistemic status');
    for (const row of rows) {
        const li = el('li', `epistemic-chip ${row.cls}`);
        li.setAttribute('title', row.status);
        li.setAttribute(
            'aria-label',
            `${row.label}: ${plural(row.count, 'relation', 'relations')}, ${row.share === '<1%' ? 'less than 1%' : row.share}`,
        );
        li.append(
            text('span', 'epistemic-chip__label', row.label),
            document.createTextNode(' '),
            text('span', 'epistemic-chip__count', row.count.toLocaleString()),
            document.createTextNode(' '),
            text('span', 'epistemic-chip__share', row.share),
        );
        list.appendChild(li);
    }
    wrap.appendChild(list);
    return wrap;
}

// `names` is a string (one span) or a short list of nodes already built.
function buildMetaLine(label, names, rest, fullTitle) {
    const p = el('p', 'epistemic-meta');
    p.appendChild(text('strong', '', label));
    if (Array.isArray(names)) {
        for (const node of names) p.appendChild(node);
    } else {
        p.appendChild(text('span', '', names));
    }
    if (rest > 0) p.appendChild(document.createTextNode(` +${rest} more`));
    if (fullTitle) p.setAttribute('title', fullTitle);
    return p;
}

// A document id that is in the Documents list is a button that opens the source
// viewer; any other id stays plain text. The click handler looks the payload up
// in the closure through data-section / data-index (/ data-statement).
function buildDocLink(ctx, docId, key, index, statementIndex, highlighted) {
    if (!ctx.known.has(docId)) {
        const plain = text('span', 'epistemic-meta__doc', docId);
        plain.setAttribute('title', docId);
        return plain;
    }
    const b = text('button', 'epistemic-doc-link epistemic-meta__doc', docId);
    b.setAttribute('type', 'button');
    b.setAttribute('title', docId);
    b.setAttribute('data-action', 'open-doc');
    b.setAttribute('data-section', key);
    b.setAttribute('data-index', String(index));
    b.setAttribute('data-doc-id', docId);
    if (statementIndex !== null) b.setAttribute('data-statement', String(statementIndex));
    b.setAttribute('aria-label', highlighted ? `Read ${docId} with the cited passage highlighted` : `Read ${docId}`);
    return b;
}

function buildStatement(st, ctx, key, index, statementIndex) {
    const frag = [];
    const quote = el('blockquote', 'epistemic-quote');
    quote.textContent = st.text;
    quote.setAttribute('title', st.text);
    frag.push(quote);
    const hasConf = st.confidence !== null;
    if (st.document || hasConf) {
        const meta = el('p', 'epistemic-meta');
        if (st.document) {
            meta.appendChild(buildDocLink(ctx, st.document, key, index, statementIndex, !!st.text));
        }
        if (hasConf) {
            const conf = `Confidence ${Math.round(st.confidence * 100)}%`;
            meta.appendChild(document.createTextNode(st.document ? ` · ${conf}` : conf));
        }
        frag.push(meta);
    }
    return frag;
}

function buildCard(section, index, item, ctx) {
    const key = section.def.key;
    const title = item.title || section.def.singular;
    const li = el('li', 'epistemic-card');

    const titleEl = text('p', 'epistemic-card__title', title);
    titleEl.setAttribute('title', title);
    li.appendChild(titleEl);

    if (item.entities.length) {
        const names = item.entities.slice(0, MAX_NAMES).map((e) => e.name).join(', ');
        const full = item.entities.map((e) => (e.type ? `${e.name} (${e.type})` : e.name)).join(', ');
        li.appendChild(buildMetaLine('Entities: ', names, item.entities.length - MAX_NAMES, full));
    }

    const quoted = item.statements.slice(0, MAX_QUOTES);
    quoted.forEach((st, statementIndex) => {
        for (const node of buildStatement(st, ctx, key, index, statementIndex)) li.appendChild(node);
    });

    const shownDocs = new Set(quoted.map((st) => st.document));
    const sources = item.documents.filter((d) => !shownDocs.has(d));
    if (sources.length) {
        const shownSources = sources.slice(0, MAX_NAMES);
        let names;
        if (shownSources.some((id) => ctx.known.has(id))) {
            names = [];
            shownSources.forEach((id, i) => {
                if (i > 0) names.push(document.createTextNode(', '));
                const cited = item.statements.some((st) => st.document === id && st.text);
                names.push(buildDocLink(ctx, id, key, index, null, cited));
            });
        } else {
            names = [text('span', 'epistemic-meta__doc', shownSources.join(', '))];
        }
        li.appendChild(buildMetaLine('Sources: ', names, sources.length - MAX_NAMES, item.documents.join(', ')));
    }

    const graphEntity = item.entities.find((e) => e.id);
    const actions = el('div', 'epistemic-actions');
    const show = text('button', 'epistemic-btn', 'Show in graph');
    const ask = text('button', 'epistemic-btn', 'Ask in chat');
    for (const [b, action] of [[show, 'show-graph'], [ask, 'ask-chat']]) {
        b.setAttribute('type', 'button');
        b.setAttribute('data-action', action);
        b.setAttribute('data-section', key);
        b.setAttribute('data-index', String(index));
    }
    show.setAttribute('aria-label', `Show ${shortTitle(title)} in the graph`);
    ask.setAttribute('aria-label', `Ask in chat about ${shortTitle(title)}`);
    ask.setAttribute('title', ASK_TITLE);
    const noteId = `epistemic-note-${key}-${index}`;
    if (graphEntity) {
        show.setAttribute('title', `Focus the graph on ${graphEntity.name} and its direct connections.`);
    } else {
        show.setAttribute('aria-disabled', 'true');
        show.setAttribute('title', NO_GRAPH_ENTITY_TITLE);
        show.setAttribute('aria-describedby', noteId);
    }
    actions.append(show, ask);
    li.appendChild(actions);
    if (!graphEntity) {
        const note = text('p', 'epistemic-note', NO_GRAPH_ENTITY_NOTE);
        note.setAttribute('id', noteId);
        li.appendChild(note);
    }
    return li;
}

function buildSection(section, itemsByKey, toggles, ctx) {
    const key = section.def.key;
    const block = el('div', 'epistemic-section');
    const heading = text('h4', '', `${section.label} (${section.count.toLocaleString()})`);
    heading.setAttribute('id', `epistemic-sec-${key}`);
    block.appendChild(heading);
    if (section.description) block.appendChild(text('p', 'epistemic-section__desc', section.description));

    const head = el('ul', 'epistemic-items');
    head.setAttribute('aria-labelledby', `epistemic-sec-${key}`);
    section.items.forEach((item, index) => {
        itemsByKey.set(`${key}:${index}`, item);
    });
    section.items.slice(0, VISIBLE_CARDS).forEach((item, index) => head.appendChild(buildCard(section, index, item, ctx)));
    block.appendChild(head);

    if (section.items.length > VISIBLE_CARDS) {
        const lower = section.label.toLowerCase();
        const restId = `epistemic-rest-${key}`;
        const total = section.items.length;
        // A capped section (count > items sent) cannot show "all": say how many of the total.
        const show = total < section.count
            ? `Show ${total.toLocaleString()} of ${section.count.toLocaleString()}`
            : `Show all ${total}`;
        const toggle = el('button', 'epistemic-toggle');
        toggle.setAttribute('type', 'button');
        toggle.setAttribute('data-action', 'toggle');
        toggle.setAttribute('data-section', key);
        toggle.setAttribute('aria-expanded', 'false');
        toggle.setAttribute('aria-controls', restId);
        toggle.setAttribute('aria-label', `${show} ${lower}`);
        toggle.textContent = show;
        const rest = el('ul', 'epistemic-items epistemic-items--rest');
        rest.setAttribute('id', restId);
        rest.setAttribute('hidden', '');
        rest.setAttribute('aria-labelledby', `epistemic-sec-${key}`);
        section.items.slice(VISIBLE_CARDS).forEach((item, i) => rest.appendChild(buildCard(section, i + VISIBLE_CARDS, item, ctx)));
        block.append(toggle, rest);
        toggles.set(key, { toggle, rest, lower, show });
    }
    if (section.items.length < section.count) {
        block.appendChild(text('p', 'epistemic-section__desc', `Showing ${section.items.length} of ${section.count}.`));
    }
    return block;
}

function flipToggle(state) {
    const open = state.toggle.getAttribute('aria-expanded') !== 'true';
    state.toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    if (open) state.rest.removeAttribute('hidden');
    else state.rest.setAttribute('hidden', '');
    state.toggle.textContent = open ? `Show first ${VISIBLE_CARDS}` : state.show;
    state.toggle.setAttribute(
        'aria-label',
        open ? `Show only the first ${VISIBLE_CARDS} ${state.lower}` : `${state.show} ${state.lower}`,
    );
}

// The "Epistemic health" section: status distribution, per-kind counts and
// cards for contradictions, conflicts, contested claims, hypotheses, risks and
// gaps. Anything that is not a well-formed payload renders the not-run message.
//   onShowInGraph(entityId, event)  "Show in graph" on an item with a graph entity
//   onAskInChat(question, event)    "Ask in chat" (prefills the chat only)
//   documents                       the Documents list; only ids in it become links
//   onOpenDocument(docId, highlight, event)  a document id link; highlight is the
//                                   cited statement's text when there is one
export function buildEpistemicHealth({ epistemic, onShowInGraph, onAskInChat, documents, onOpenDocument }) {
    const root = el('section', 'epistemic-health');
    root.setAttribute('aria-labelledby', 'epistemic-heading');
    const heading = text('h3', '', 'Epistemic health');
    heading.setAttribute('id', 'epistemic-heading');
    root.appendChild(heading);

    const data = isObj(epistemic) ? epistemic : {};
    const counts = cleanStatusCounts(data.status_counts);
    const sections = cleanSections(data.sections);
    if (data.available !== true || (counts.length === 0 && sections.length === 0)) {
        root.appendChild(text('p', 'epistemic-hint', NOT_RUN_COPY));
        return root;
    }

    if (counts.length) root.appendChild(buildDistribution(counts));
    if (sections.length) {
        root.appendChild(text(
            'p',
            'epistemic-counts',
            sections.map((s) => plural(s.count, s.def.one, s.def.many)).join(' · '),
        ));
    } else {
        root.appendChild(text('p', 'epistemic-hint', NONE_FOUND_COPY));
    }

    const known = new Set();
    if (Array.isArray(documents)) {
        for (const row of documents) {
            if (isObj(row) && typeof row.doc_id === 'string' && row.doc_id) known.add(row.doc_id);
        }
    }
    const ctx = { known };
    const itemsByKey = new Map();
    const toggles = new Map();
    for (const section of sections) root.appendChild(buildSection(section, itemsByKey, toggles, ctx));

    // One delegated listener; the item payload comes from the closure, never
    // from the DOM.
    root.addEventListener('click', (event) => {
        const target = event && event.target;
        const button = target && typeof target.closest === 'function' ? target.closest('button[data-action]') : null;
        if (!button) return;
        const action = button.dataset.action;
        const sectionKey = button.dataset.section;
        if (action === 'toggle') {
            const state = toggles.get(sectionKey);
            if (state) flipToggle(state);
            return;
        }
        const item = itemsByKey.get(`${sectionKey}:${button.dataset.index}`);
        if (!item) return;
        if (action === 'open-doc') {
            // The id and the passage come from the item in the closure; the
            // attributes only say which statement was meant.
            const statementIndex = button.dataset.statement;
            let docId;
            let statement;
            if (statementIndex !== undefined) {
                statement = item.statements[Number(statementIndex)];
                docId = statement ? statement.document : '';
            } else {
                docId = button.dataset.docId;
                if (!item.documents.includes(docId)) return;
                statement = item.statements.find((st) => st.document === docId && st.text);
            }
            if (!docId || !known.has(docId)) return;
            const highlight = statement && statement.document === docId && statement.text ? statement.text : undefined;
            if (typeof onOpenDocument === 'function') onOpenDocument(docId, highlight, event);
            return;
        }
        if (action === 'show-graph') {
            if (button.getAttribute('aria-disabled') === 'true') return;
            const entity = item.entities.find((e) => e.id);
            if (entity && typeof onShowInGraph === 'function') onShowInGraph(entity.id, event);
        } else if (action === 'ask-chat') {
            const question = item.question || `What does the evidence say about: ${item.title || sectionKey}?`;
            if (typeof onAskInChat === 'function') onAskInChat(question, event);
        }
    });
    return root;
}

// --- Documents ---------------------------------------------------------------

const VISIBLE_DOCUMENTS = 10;
const DOCUMENTS_HINT = 'Entities and relations extracted from each document. Select a document to read it.';
const DOCUMENTS_EMPTY_COPY = 'No source documents were found in this output directory. '
    + 'Run /epistract:ingest to add documents, then reload the workbench.';

function slug(value) {
    return String(value).toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '');
}

function nonNegative(value) {
    const n = Number(value);
    return Number.isFinite(n) && n > 0 ? Math.floor(n) : 0;
}

function cleanDocument(raw) {
    if (!isObj(raw) || typeof raw.doc_id !== 'string' || !raw.doc_id) return null;
    const filename = str(raw.filename);
    return {
        raw,
        doc_id: raw.doc_id,
        name: str(raw.display_name) || filename || raw.doc_id,
        entities: nonNegative(raw.entity_count),
        relations: nonNegative(raw.relation_count),
        hasText: raw.has_text !== false,
        hasPdf: raw.has_pdf === true,
    };
}

function unitLabel(n, one, many) {
    return `${n.toLocaleString()} ${n === 1 ? one : many}`;
}

function buildDocumentRow(doc, index) {
    const tr = el('tr', 'dashboard-link-row dashboard-doc-row');
    tr.setAttribute('data-index', String(index));
    tr.setAttribute('data-doc-id', doc.doc_id);

    const showId = slug(doc.name) !== slug(doc.doc_id);
    const btn = el('button', 'dashboard-link-btn dashboard-doc-btn');
    btn.setAttribute('type', 'button');
    btn.setAttribute('data-doc-id', doc.doc_id);
    let label = `Read ${doc.name}: ${unitLabel(doc.entities, 'entity', 'entities')}, ${unitLabel(doc.relations, 'relation', 'relations')}`;
    if (!doc.hasText) label += doc.hasPdf ? ' (PDF only)' : ' (text not available)';
    btn.setAttribute('aria-label', label);
    btn.setAttribute('title', showId ? `${doc.name}\n${doc.doc_id}` : doc.name);

    const nameStack = el('span', 'documents-name');
    nameStack.appendChild(text('span', 'documents-name__text', doc.name));
    if (showId) nameStack.appendChild(text('span', 'documents-name__id', doc.doc_id));
    btn.appendChild(nameStack);
    if (!doc.hasText) btn.appendChild(text('span', 'documents-flag', doc.hasPdf ? 'PDF only' : 'No text'));
    const chevron = text('span', 'dashboard-link-chevron', '›');
    chevron.setAttribute('aria-hidden', 'true');
    btn.appendChild(chevron);

    const cell = el('td', 'dashboard-link-cell');
    cell.appendChild(btn);
    const countCell = (n) => text('td', n === 0 ? 'dashboard-count dashboard-count--zero' : 'dashboard-count', n.toLocaleString());
    tr.append(cell, countCell(doc.entities), countCell(doc.relations));
    return { tr, btn };
}

// The "Documents" section: one row per source document with its entity and
// relation counts, the first ten shown and the rest behind a toggle. Returns
// null when the reply carried no `documents` list, so the caller omits the
// section.
//   onOpen(doc, event)  a row was activated; doc is the cleaned row from the list
export function buildDocuments({ documents, onOpen }) {
    if (!Array.isArray(documents)) return null;
    const docs = documents.map(cleanDocument).filter(Boolean);

    const root = el('section', 'documents-section');
    root.setAttribute('aria-labelledby', 'documents-heading');
    const heading = text('h3', '', docs.length ? `Documents (${docs.length.toLocaleString()})` : 'Documents');
    heading.setAttribute('id', 'documents-heading');
    root.appendChild(heading);
    if (docs.length === 0) {
        root.appendChild(text('p', 'dashboard-empty__body', DOCUMENTS_EMPTY_COPY));
        return root;
    }

    root.appendChild(text('p', 'dashboard-hint', DOCUMENTS_HINT));

    const table = el('table', 'dashboard-table documents-table');
    table.setAttribute('aria-labelledby', 'documents-heading');
    const colgroup = el('colgroup');
    for (let i = 0; i < 3; i += 1) colgroup.appendChild(el('col'));
    const headRow = el('tr');
    headRow.append(text('th', '', 'Document'), text('th', '', 'Entities'), text('th', '', 'Relations'));
    const thead = el('thead');
    thead.appendChild(headRow);
    const head = el('tbody');
    docs.slice(0, VISIBLE_DOCUMENTS).forEach((doc, i) => head.appendChild(buildDocumentRow(doc, i).tr));
    table.append(colgroup, thead, head);

    let rest = null;
    let firstRevealed = null;
    if (docs.length > VISIBLE_DOCUMENTS) {
        rest = el('tbody');
        rest.setAttribute('id', 'documents-rest');
        rest.setAttribute('hidden', '');
        docs.slice(VISIBLE_DOCUMENTS).forEach((doc, i) => {
            const built = buildDocumentRow(doc, i + VISIBLE_DOCUMENTS);
            if (!firstRevealed) firstRevealed = built.btn;
            rest.appendChild(built.tr);
        });
        table.appendChild(rest);
    }

    // One delegated listener on the table; the document comes from the closure
    // by row index, never from the DOM text.
    table.addEventListener('click', (event) => {
        const target = event && event.target;
        const row = target && typeof target.closest === 'function'
            ? target.closest('tr.dashboard-link-row')
            : null;
        if (!row) return;
        const index = Number(row.getAttribute('data-index'));
        if (!Number.isInteger(index) || index < 0 || index >= docs.length) return;
        if (typeof onOpen === 'function') onOpen(docs[index].raw, event);
    });

    const wrap = el('div', 'dashboard-table-wrap');
    wrap.appendChild(table);
    root.appendChild(wrap);

    const status = el('span', 'visually-hidden');
    status.setAttribute('id', 'documents-status');
    status.setAttribute('role', 'status');
    status.setAttribute('aria-live', 'polite');

    if (rest) {
        const total = docs.length.toLocaleString();
        const toggle = el('button', 'documents-toggle');
        toggle.setAttribute('type', 'button');
        toggle.setAttribute('aria-expanded', 'false');
        toggle.setAttribute('aria-controls', 'documents-rest');
        const collapsed = () => {
            toggle.textContent = `Show all ${total}`;
            toggle.setAttribute('aria-label', `Show all ${total} documents`);
        };
        collapsed();
        toggle.addEventListener('click', () => {
            const open = toggle.getAttribute('aria-expanded') !== 'true';
            toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
            if (open) {
                rest.removeAttribute('hidden');
                toggle.textContent = `Show first ${VISIBLE_DOCUMENTS}`;
                toggle.setAttribute('aria-label', `Show only the first ${VISIBLE_DOCUMENTS} documents`);
                status.textContent = `Showing all ${total} documents.`;
                // The toggle sits below the table: land in the revealed rows.
                firstRevealed.focus({ preventScroll: true });
            } else {
                rest.setAttribute('hidden', '');
                collapsed();
                status.textContent = `Showing the first ${VISIBLE_DOCUMENTS} of ${total} documents.`;
                toggle.focus({ preventScroll: true });
            }
        });
        root.appendChild(toggle);
    }
    root.appendChild(status);
    return root;
}

// --- Where to start ----------------------------------------------------------

const VISIBLE_COMMUNITIES = 10;
const START_HINT = 'Begin with the largest topics or the most-connected entities. Select a row to see it in the graph.';
const NO_COMMUNITIES_COPY = 'No topic communities were found for this graph.';
const NO_HUBS_COPY = 'No connected entities yet.';
const UNCLUSTERED = 'Unclustered';

function cleanCommunity(raw) {
    if (!isObj(raw)) return null;
    const id = str(raw.id);
    const fullLabel = str(raw.full_label) || str(raw.label) || id;
    const members = Array.isArray(raw.top_members)
        ? raw.top_members.filter(m => typeof m === 'string' && m).slice(0, 3)
        : [];
    return {
        raw,
        id,
        label: str(raw.label) || str(raw.full_label) || id,
        fullLabel,
        members: nonNegative(raw.member_count),
        topMembers: members,
    };
}

function cleanHub(raw) {
    if (!isObj(raw)) return null;
    const id = str(raw.id);
    const communityId = typeof raw.community_id === 'string' && raw.community_id ? raw.community_id : null;
    return {
        raw,
        id,
        name: str(raw.name) || id,
        type: str(raw.entity_type),
        connections: nonNegative(raw.connections),
        communityId,
        communityLabel: communityId === null ? '' : (str(raw.community_label) || communityId),
    };
}

// "A", "A and B", "A, B and C".
function joinNames(names) {
    if (names.length <= 1) return names.join('');
    return `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`;
}

// The main row button with the name stack and chevron, inside the row's
// .start-action wrapper (a later second action is appended to `actions`).
function buildStartAction(label, subLine, ariaLabel, title) {
    const btn = el('button', 'dashboard-link-btn');
    btn.setAttribute('type', 'button');
    btn.setAttribute('data-start-action', 'show');
    btn.setAttribute('aria-label', ariaLabel);
    btn.setAttribute('title', title);
    const nameStack = el('span', 'start-name');
    nameStack.appendChild(text('span', 'start-name__text', label));
    if (subLine) nameStack.appendChild(text('span', 'start-name__sub', subLine));
    const chevron = text('span', 'dashboard-link-chevron', '›');
    chevron.setAttribute('aria-hidden', 'true');
    btn.append(nameStack, chevron);
    const actions = el('div', 'start-action');
    actions.appendChild(btn);
    const cell = el('td', 'dashboard-link-cell');
    cell.appendChild(actions);
    return { cell, btn, actions };
}

function countCell(n) {
    return text('td', n === 0 ? 'dashboard-count dashboard-count--zero' : 'dashboard-count', n.toLocaleString());
}

function buildCommunityRow(row, index) {
    const tr = el('tr', 'dashboard-link-row');
    tr.setAttribute('data-index', String(index));
    tr.setAttribute('data-group-id', row.id);
    const membersLine = row.topMembers.length ? `Top members: ${row.topMembers.join(', ')}` : '';
    let aria = `Show the ${row.fullLabel} community in the graph: ${unitLabel(row.members, 'member', 'members')}`;
    if (row.topMembers.length) aria += `, including ${joinNames(row.topMembers)}`;
    const title = membersLine ? `${row.fullLabel}\n${membersLine}` : row.fullLabel;
    const { cell, btn, actions } = buildStartAction(row.label, membersLine, aria, title);
    tr.append(cell, countCell(row.members));
    return { tr, btn, actions };
}

function buildHubRow(row, index, fullLabels, labels) {
    const tr = el('tr', 'dashboard-link-row');
    tr.setAttribute('data-index', String(index));
    tr.setAttribute('data-node-id', row.id);
    const typeLabel = typeLabelFor(row.type, labels);
    const communityFull = row.communityId === null
        ? ''
        : (fullLabels.get(row.communityId) || row.communityLabel);
    const where = row.communityId === null
        ? 'not in a topic community'
        : `in the ${communityFull} community`;
    const aria = `Show ${row.name} and its connections in the graph: ${typeLabel}, `
        + `${unitLabel(row.connections, 'connection', 'connections')}, ${where}`;
    const { cell, btn, actions } = buildStartAction(row.name, '', aria, row.name);

    const typeCell = el('td', 'start-type');
    typeCell.setAttribute('title', typeLabel);
    typeCell.append(makeSwatch(row.type, SWATCH_PX), text('span', 'start-type__label', typeLabel));

    const community = row.communityId === null
        ? text('td', 'start-community start-community--none', UNCLUSTERED)
        : text('td', 'start-community', row.communityLabel);
    community.setAttribute('title', row.communityId === null ? UNCLUSTERED : communityFull);

    tr.append(cell, typeCell, countCell(row.connections), community);
    return { tr, btn, actions };
}

function headerCell(label, className) {
    return text('th', className || '', label);
}

function startTable(tableClass, headingId, headers) {
    const table = el('table', `dashboard-table ${tableClass}`);
    table.setAttribute('aria-labelledby', headingId);
    const headRow = el('tr');
    for (const [label, className] of headers) headRow.appendChild(headerCell(label, className));
    const thead = el('thead');
    thead.appendChild(headRow);
    table.appendChild(thead);
    return table;
}

// One delegated listener per table: the row comes from the closure by index,
// never from DOM text; the action from the nearest data-start-action ("show"
// when the click landed elsewhere in the row). Unknown actions are ignored.
function delegateStartClicks(table, rows, actions) {
    table.addEventListener('click', (event) => {
        const target = event && event.target;
        const tr = target && typeof target.closest === 'function'
            ? target.closest('tr.dashboard-link-row')
            : null;
        if (!tr) return;
        const index = Number(tr.getAttribute('data-index'));
        if (!Number.isInteger(index) || index < 0 || index >= rows.length) return;
        const actionEl = target.closest('[data-start-action]');
        const action = actionEl ? actionEl.getAttribute('data-start-action') : 'show';
        const handler = Object.prototype.hasOwnProperty.call(actions, action) ? actions[action] : null;
        if (typeof handler === 'function') handler(rows[index].raw, event);
    });
}

function blockTitle(id, label) {
    const h4 = text('h4', 'start-block__title', label);
    h4.setAttribute('id', id);
    return h4;
}

function buildCommunitiesBlock(communities, status, onShowCommunity) {
    const block = el('div', 'start-block');
    const total = communities.length;
    block.appendChild(blockTitle(
        'start-communities-heading',
        total ? `Topic communities (${total.toLocaleString()})` : 'Topic communities',
    ));
    if (total === 0) {
        block.appendChild(text('p', 'dashboard-empty__body', NO_COMMUNITIES_COPY));
        return block;
    }
    const table = startTable('start-communities-table', 'start-communities-heading', [
        ['Community', ''],
        ['Members', 'start-col-count'],
    ]);
    const head = el('tbody');
    communities.slice(0, VISIBLE_COMMUNITIES).forEach((row, i) => head.appendChild(buildCommunityRow(row, i).tr));
    table.appendChild(head);

    let rest = null;
    let firstRevealed = null;
    if (total > VISIBLE_COMMUNITIES) {
        rest = el('tbody');
        rest.setAttribute('id', 'start-communities-rest');
        rest.setAttribute('hidden', '');
        communities.slice(VISIBLE_COMMUNITIES).forEach((row, i) => {
            const built = buildCommunityRow(row, i + VISIBLE_COMMUNITIES);
            if (!firstRevealed) firstRevealed = built.btn;
            rest.appendChild(built.tr);
        });
        table.appendChild(rest);
    }
    delegateStartClicks(table, communities, { show: onShowCommunity });

    const wrap = el('div', 'dashboard-table-wrap');
    wrap.appendChild(table);
    block.appendChild(wrap);

    if (rest) {
        const count = total.toLocaleString();
        const toggle = el('button', 'start-toggle');
        toggle.setAttribute('type', 'button');
        toggle.setAttribute('aria-expanded', 'false');
        toggle.setAttribute('aria-controls', 'start-communities-rest');
        const collapsed = () => {
            toggle.textContent = `Show all ${count}`;
            toggle.setAttribute('aria-label', `Show all ${count} topic communities`);
        };
        collapsed();
        toggle.addEventListener('click', () => {
            const open = toggle.getAttribute('aria-expanded') !== 'true';
            toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
            if (open) {
                rest.removeAttribute('hidden');
                toggle.textContent = `Show first ${VISIBLE_COMMUNITIES}`;
                toggle.setAttribute('aria-label', `Show only the first ${VISIBLE_COMMUNITIES} topic communities`);
                status.textContent = `Showing all ${count} topic communities.`;
                // The toggle sits below the table: land in the revealed rows.
                firstRevealed.focus({ preventScroll: true });
            } else {
                rest.setAttribute('hidden', '');
                collapsed();
                status.textContent = `Showing the first ${VISIBLE_COMMUNITIES} of ${count} topic communities.`;
                toggle.focus({ preventScroll: true });
            }
        });
        block.appendChild(toggle);
    }
    return block;
}

function buildHubsBlock(hubs, communities, onShowEntity) {
    const block = el('div', 'start-block');
    block.appendChild(blockTitle('start-hubs-heading', 'Most-connected entities'));
    if (hubs.length === 0) {
        block.appendChild(text('p', 'dashboard-empty__body', NO_HUBS_COPY));
        return block;
    }
    const fullLabels = new Map(communities.map(row => [row.id, row.fullLabel]));
    const labels = typeLabels();
    const table = startTable('start-hubs-table', 'start-hubs-heading', [
        ['Entity', ''],
        ['Type', 'start-col-type'],
        ['Connections', 'start-col-count'],
        ['Community', 'start-col-community'],
    ]);
    const body = el('tbody');
    hubs.forEach((row, i) => body.appendChild(buildHubRow(row, i, fullLabels, labels).tr));
    table.appendChild(body);
    delegateStartClicks(table, hubs, { show: onShowEntity });
    const wrap = el('div', 'dashboard-table-wrap');
    wrap.appendChild(table);
    block.appendChild(wrap);
    return block;
}

// The "Where to start" section: the topic communities (largest first, ten
// shown and the rest behind a toggle) and the most-connected entities. Returns
// null when the reply carried no `start_here` object, or when both lists are
// empty and the graph has no nodes, so the caller omits the section.
//   onShowCommunity(row, event)  a community row was activated (payload row)
//   onShowEntity(row, event)     an entity row was activated (payload row)
export function buildStartHere({ startHere, totalNodes, onShowCommunity, onShowEntity }) {
    if (!isObj(startHere)) return null;
    const communities = (Array.isArray(startHere.communities) ? startHere.communities : [])
        .map(cleanCommunity).filter(Boolean);
    const hubs = (Array.isArray(startHere.hubs) ? startHere.hubs : [])
        .map(cleanHub).filter(Boolean);
    if (communities.length === 0 && hubs.length === 0 && nonNegative(totalNodes) === 0) return null;

    const root = el('section', 'start-here');
    root.setAttribute('aria-labelledby', 'start-here-heading');
    const heading = text('h3', '', 'Where to start');
    heading.setAttribute('id', 'start-here-heading');
    root.appendChild(heading);
    if (communities.length || hubs.length) root.appendChild(text('p', 'dashboard-hint', START_HINT));

    const status = el('span', 'visually-hidden');
    status.setAttribute('id', 'start-status');
    status.setAttribute('role', 'status');
    status.setAttribute('aria-live', 'polite');

    root.appendChild(buildCommunitiesBlock(communities, status, onShowCommunity));
    root.appendChild(buildHubsBlock(hubs, communities, onShowEntity));
    root.appendChild(status);
    return root;
}
