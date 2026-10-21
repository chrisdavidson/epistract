// dashboard.js - DOM builders for the auto-generated Dashboard: the entity
// summary and the epistemic health section.
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
export function sortEntityRows(entityCounts) {
    const labels = new Map(legendEntries().map(entry => [entry.type, entry.label]));
    const rows = Object.entries(entityCounts || {}).map(([type, count]) => ({
        type,
        label: labels.get(typeKey(type)) || type,
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

function buildMetaLine(label, names, rest, fullTitle) {
    const p = el('p', 'epistemic-meta');
    p.append(text('strong', '', label), text('span', '', names));
    if (rest > 0) p.appendChild(document.createTextNode(` +${rest} more`));
    if (fullTitle) p.setAttribute('title', fullTitle);
    return p;
}

function buildStatement(st) {
    const frag = [];
    const quote = el('blockquote', 'epistemic-quote');
    quote.textContent = st.text;
    quote.setAttribute('title', st.text);
    frag.push(quote);
    const hasConf = st.confidence !== null;
    if (st.document || hasConf) {
        const meta = el('p', 'epistemic-meta');
        if (st.document) {
            const doc = text('span', 'epistemic-meta__doc', st.document);
            doc.setAttribute('title', st.document);
            meta.appendChild(doc);
        }
        if (hasConf) {
            const conf = `Confidence ${Math.round(st.confidence * 100)}%`;
            meta.appendChild(document.createTextNode(st.document ? ` · ${conf}` : conf));
        }
        frag.push(meta);
    }
    return frag;
}

function buildCard(section, index, item) {
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
    for (const st of quoted) {
        for (const node of buildStatement(st)) li.appendChild(node);
    }

    const shownDocs = new Set(quoted.map((st) => st.document));
    const sources = item.documents.filter((d) => !shownDocs.has(d));
    if (sources.length) {
        const line = buildMetaLine('Sources: ', sources.slice(0, MAX_NAMES).join(', '), sources.length - MAX_NAMES, item.documents.join(', '));
        line.children[1].className = 'epistemic-meta__doc';
        li.appendChild(line);
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

function buildSection(section, itemsByKey, toggles) {
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
    section.items.slice(0, VISIBLE_CARDS).forEach((item, index) => head.appendChild(buildCard(section, index, item)));
    block.appendChild(head);

    if (section.items.length > VISIBLE_CARDS) {
        const lower = section.label.toLowerCase();
        const restId = `epistemic-rest-${key}`;
        const total = section.items.length;
        const toggle = el('button', 'epistemic-toggle');
        toggle.setAttribute('type', 'button');
        toggle.setAttribute('data-action', 'toggle');
        toggle.setAttribute('data-section', key);
        toggle.setAttribute('aria-expanded', 'false');
        toggle.setAttribute('aria-controls', restId);
        toggle.setAttribute('aria-label', `Show all ${total} ${lower}`);
        toggle.textContent = `Show all ${total}`;
        const rest = el('ul', 'epistemic-items epistemic-items--rest');
        rest.setAttribute('id', restId);
        rest.setAttribute('hidden', '');
        rest.setAttribute('aria-labelledby', `epistemic-sec-${key}`);
        section.items.slice(VISIBLE_CARDS).forEach((item, i) => rest.appendChild(buildCard(section, i + VISIBLE_CARDS, item)));
        block.append(toggle, rest);
        toggles.set(key, { toggle, rest, lower, total });
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
    state.toggle.textContent = open ? `Show first ${VISIBLE_CARDS}` : `Show all ${state.total}`;
    state.toggle.setAttribute(
        'aria-label',
        open ? `Show only the first ${VISIBLE_CARDS} ${state.lower}` : `Show all ${state.total} ${state.lower}`,
    );
}

// The "Epistemic health" section: status distribution, per-kind counts and
// cards for contradictions, conflicts, contested claims, hypotheses, risks and
// gaps. Anything that is not a well-formed payload renders the not-run message.
//   onShowInGraph(entityId, event)  "Show in graph" on an item with a graph entity
//   onAskInChat(question, event)    "Ask in chat" (prefills the chat only)
export function buildEpistemicHealth({ epistemic, onShowInGraph, onAskInChat }) {
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

    const itemsByKey = new Map();
    const toggles = new Map();
    for (const section of sections) root.appendChild(buildSection(section, itemsByKey, toggles));

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
