// source_viewer.js - the in-workbench document viewer: header, Back, original
// PDF link, Show in graph and the document text in a scrollable reader.
//
// It owns the single 'navigate-source' listener: any part of the page opens a
// document with
//   window.dispatchEvent(new CustomEvent('navigate-source', { detail: { docId, highlight } }))
// (the legacy `section` field is read as `highlight`).
//
// SEC-01: document ids, names, text and highlight strings come from the corpus
// and are untrusted. They reach the DOM only through createElement,
// textContent and setAttribute; markup is never built from strings, and ids
// are percent-encoded before they go into a URL.

const MAX_RENDERED_CHARS = 2000000;
const TEXT_URL = '/api/sources/';
const PDF_URL = '/api/sources/pdf/';

const COPY = {
    loading: 'Loading document...',
    emptyTitle: 'This document is empty',
    emptyBody: 'No text was extracted from this document.',
    emptyPdf: ' Open the original PDF to read it.',
    missingTitle: 'Document not available',
    missingBody: "This document's text is not available in this output directory.",
    missingPdf: ' The original PDF is still available above.',
    errorTitle: "Couldn't load this document",
    errorBody: 'The workbench server did not respond. Check that it is still running, then try again.',
    retry: 'Try again',
    graphTitle: 'Focus the graph on this document and its direct connections.',
    graphTitleDisabled: 'This document has no entities in the graph.',
    graphNote: 'This document has no entities in the graph, so there is nothing to focus.',
};

const documents = new Map();
const subscribers = new Set();

let deps = null;
let ui = null;
let listening = false;

let current = null; // { docId, highlight }
let origin = 'dashboard';
let trigger = null;
let savedScroll = { dashboard: 0, chat: 0 };
let loadToken = 0;
let controller = null;
let retryButton = null;
let headerSignature = '';

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

export function formatSize(bytes) {
    if (!bytes || typeof bytes !== 'number') return '';
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

// --- document list ------------------------------------------------------------

function snapshot() {
    return Array.from(documents.values());
}

function notify() {
    for (const callback of Array.from(subscribers)) callback(snapshot());
}

// Merges rows by doc_id: the Dashboard row (counts) and the /api/sources row
// (size) describe the same document.
export function setDocuments(list) {
    if (!Array.isArray(list)) return;
    for (const row of list) {
        if (!row || typeof row !== 'object' || typeof row.doc_id !== 'string' || !row.doc_id) continue;
        documents.set(row.doc_id, { ...documents.get(row.doc_id), ...row });
    }
    notify();
    if (current) renderHeader();
}

// Calls callback with the merged list now and after every change; returns the
// function that stops the calls.
export function subscribeDocuments(callback) {
    if (typeof callback !== 'function') return () => {};
    subscribers.add(callback);
    callback(snapshot());
    return () => { subscribers.delete(callback); };
}

export function getOrigin() {
    return origin;
}

// --- panel -----------------------------------------------------------------------

function describe() {
    const id = current ? current.docId : '';
    const row = documents.get(id) || null;
    const name = (row && (row.display_name || row.filename)) || id || 'Unknown document';
    return { id, row, name };
}

function metaText(row) {
    if (!row) return '';
    const parts = [];
    if (typeof row.entity_count === 'number') {
        parts.push(`${row.entity_count.toLocaleString()} ${row.entity_count === 1 ? 'entity' : 'entities'}`);
    }
    if (typeof row.relation_count === 'number') {
        parts.push(`${row.relation_count.toLocaleString()} ${row.relation_count === 1 ? 'relation' : 'relations'}`);
    }
    const size = formatSize(row.size_bytes);
    if (size) parts.push(size);
    return parts.join(' · ');
}

function renderHeader() {
    if (!ui || !current) return;
    const { id, row, name } = describe();
    const meta = metaText(row);
    const hasPdf = !!(row && row.has_pdf === true);
    const graphReady = !!(row && typeof row.entity_count === 'number' && row.entity_count > 0);
    const backLabel = origin === 'chat' ? 'Back to Chat' : 'Back to Dashboard';
    const signature = JSON.stringify([id, name, meta, hasPdf, graphReady, backLabel]);
    if (signature === headerSignature) return;
    headerSignature = signature;

    ui.backLabel.textContent = backLabel;
    ui.back.setAttribute('aria-label', backLabel);
    ui.title.textContent = name;
    ui.title.setAttribute('title', name);
    ui.id.textContent = id;
    ui.meta.textContent = meta;
    if (meta) ui.meta.removeAttribute('hidden');
    else ui.meta.setAttribute('hidden', '');
    ui.reader.setAttribute('aria-label', `Text of ${name}`);

    const actions = [];
    if (hasPdf) {
        ui.pdf.setAttribute('href', PDF_URL + encodeURIComponent(id));
        ui.pdf.setAttribute('aria-label', `Open the original PDF of ${name} in a new tab`);
        actions.push(ui.pdf);
    }
    ui.graph.setAttribute('aria-label', `Show ${name} in the graph`);
    if (graphReady) {
        ui.graph.removeAttribute('aria-disabled');
        ui.graph.removeAttribute('aria-describedby');
        ui.graph.setAttribute('title', COPY.graphTitle);
    } else {
        ui.graph.setAttribute('aria-disabled', 'true');
        ui.graph.setAttribute('aria-describedby', 'source-graph-note');
        ui.graph.setAttribute('title', COPY.graphTitleDisabled);
    }
    actions.push(ui.graph);
    if (!graphReady) actions.push(ui.note);
    ui.actions.replaceChildren(...actions);
}

function announce(message) {
    ui.status.textContent = message;
}

function stateBlock(title, body, extra) {
    const block = el('div', 'source-state');
    if (title) block.appendChild(text('p', 'source-state__title', title));
    block.appendChild(text('p', 'source-state__body', body));
    if (extra) block.appendChild(extra);
    return block;
}

function showState(token, kind, payload) {
    if (token !== loadToken) return;
    const { id, row, name } = describe();
    const hadRetryFocus = !!retryButton && document.activeElement === retryButton;
    retryButton = null;
    ui.reader.setAttribute('aria-busy', 'false');
    ui.reader.scrollTop = 0;
    const hasPdf = !!(row && row.has_pdf === true);

    if (kind === 'text') {
        const total = payload.length;
        const shown = total > MAX_RENDERED_CHARS ? payload.slice(0, MAX_RENDERED_CHARS) : payload;
        const nodes = [];
        if (total > MAX_RENDERED_CHARS) {
            const size = formatSize(row && row.size_bytes) || formatSize(total);
            const filename = (row && row.filename) || id;
            nodes.push(text('p', 'source-note', `Showing the first 2 MB of ${size}. The full text is in ${filename}.`));
        }
        nodes.push(text('div', 'source-text', shown));
        ui.reader.replaceChildren(...nodes);
        announce(`Opened ${name}.`);
    } else if (kind === 'empty') {
        ui.reader.replaceChildren(stateBlock(COPY.emptyTitle, COPY.emptyBody + (hasPdf ? COPY.emptyPdf : '')));
        announce(`Opened ${name}.`);
    } else if (kind === 'missing') {
        ui.reader.replaceChildren(stateBlock(COPY.missingTitle, COPY.missingBody + (hasPdf ? COPY.missingPdf : '')));
        announce(`${name}: text not available.`);
    } else {
        const retry = text('button', 'source-btn', COPY.retry);
        retry.setAttribute('type', 'button');
        retry.addEventListener('click', () => load(true));
        retryButton = retry;
        ui.reader.replaceChildren(stateBlock(COPY.errorTitle, COPY.errorBody, retry));
        announce(`Could not load ${name}.`);
    }
    if (hadRetryFocus) ui.title.focus();
}

function load(keepContent) {
    if (!current) return;
    const { docId } = current;
    loadToken += 1;
    const token = loadToken;
    if (controller) controller.abort();
    controller = typeof AbortController === 'function' ? new AbortController() : null;
    const { name } = describe();

    ui.reader.setAttribute('aria-busy', 'true');
    if (!keepContent) {
        retryButton = null;
        ui.reader.replaceChildren(stateBlock('', COPY.loading));
        ui.reader.scrollTop = 0;
    }
    announce(`Loading ${name}.`);

    if (!docId) {
        showState(token, 'missing');
        return;
    }
    (async () => {
        try {
            const response = await fetch(TEXT_URL + encodeURIComponent(docId), controller ? { signal: controller.signal } : {});
            if (token !== loadToken) return;
            if (response.status === 404) {
                showState(token, 'missing');
                return;
            }
            if (response.status !== 200) {
                showState(token, 'error');
                return;
            }
            const body = await response.json();
            if (token !== loadToken) return;
            if (!body || typeof body.text !== 'string') showState(token, 'error');
            else if (!body.text.trim()) showState(token, 'empty');
            else showState(token, 'text', body.text);
        } catch (error) {
            showState(token, 'error');
        }
    })();
}

// --- opening and leaving ------------------------------------------------------------

function originFor(panel) {
    return panel === 'chat' ? 'chat' : 'dashboard';
}

function openDocument(detail) {
    if (!deps || !ui) return;
    const d = detail && typeof detail === 'object' ? detail : {};
    const rawId = d.docId;
    const docId = typeof rawId === 'string' ? rawId : (typeof rawId === 'number' ? String(rawId) : '');
    let highlight = '';
    if (typeof d.highlight === 'string') highlight = d.highlight;
    else if (typeof d.section === 'string') highlight = d.section;

    if (deps.getActivePanel() !== 'source') {
        // First open from another panel: remember where to return to. A second
        // open from inside the viewer keeps the original Back target.
        origin = originFor(deps.getActivePanel());
        const active = document.activeElement;
        trigger = active && active !== document.body ? active : null;
        const dashboard = document.getElementById('dashboard-panel');
        const messages = document.getElementById('messages');
        savedScroll = {
            dashboard: dashboard ? dashboard.scrollTop : 0,
            chat: messages ? messages.scrollTop : 0,
        };
    }
    current = { docId, highlight };
    headerSignature = '';
    deps.switchPanel('source');
    renderHeader();
    load(false);
    ui.title.focus();
}

function isVisible(node) {
    if (!node || !node.isConnected) return false;
    return typeof node.getClientRects !== 'function' || node.getClientRects().length > 0;
}

function goBack() {
    if (!deps || !ui) return;
    loadToken += 1;
    if (controller) controller.abort();
    controller = null;
    const target = origin;
    deps.switchPanel(target);
    const dashboard = document.getElementById('dashboard-panel');
    const messages = document.getElementById('messages');
    if (dashboard) dashboard.scrollTop = savedScroll.dashboard;
    if (messages) messages.scrollTop = savedScroll.chat;

    let focusTarget = isVisible(trigger) ? trigger : null;
    if (!focusTarget) {
        focusTarget = target === 'chat'
            ? document.getElementById('chat-input')
            : document.querySelector('.documents-table .dashboard-doc-btn');
    }
    if (focusTarget && typeof focusTarget.focus === 'function') focusTarget.focus();
}

function onShowInGraph(event) {
    if (!current || ui.graph.getAttribute('aria-disabled') === 'true') return;
    deps.openGraphWith({ reset: true, focus: { id: `doc:${current.docId}`, hops: 1 } }, event);
}

// --- construction ----------------------------------------------------------------------

function buildPanel(panel) {
    const column = el('div', 'source-column');

    const backRow = el('div', 'source-back');
    const back = el('button', 'source-btn');
    back.setAttribute('type', 'button');
    back.setAttribute('id', 'source-back-btn');
    back.setAttribute('aria-keyshortcuts', 'Escape');
    back.setAttribute('title', 'Back (Esc)');
    const arrow = text('span', '', '‹');
    arrow.setAttribute('aria-hidden', 'true');
    const backLabel = text('span', '', 'Back to Dashboard');
    back.append(arrow, backLabel);
    back.addEventListener('click', goBack);
    backRow.appendChild(back);

    const head = el('div', 'source-head');
    const title = el('h2', 'source-title');
    title.setAttribute('id', 'source-title');
    title.setAttribute('tabindex', '-1');
    const id = el('p', 'source-id');
    const meta = el('p', 'source-meta');
    meta.setAttribute('hidden', '');
    head.append(title, id, meta);

    const actions = el('div', 'source-actions');
    const pdf = el('a', 'source-btn');
    pdf.setAttribute('id', 'source-pdf-link');
    pdf.setAttribute('target', '_blank');
    pdf.setAttribute('rel', 'noopener noreferrer');
    pdf.setAttribute('title', 'Opens in a new tab.');
    const arrowOut = text('span', '', '↗');
    arrowOut.setAttribute('aria-hidden', 'true');
    pdf.append(document.createTextNode('Open original PDF '), arrowOut);
    const graph = text('button', 'source-btn', 'Show in graph');
    graph.setAttribute('type', 'button');
    graph.setAttribute('id', 'source-graph-btn');
    graph.addEventListener('click', onShowInGraph);
    actions.appendChild(graph);
    const note = text('p', 'source-note', COPY.graphNote);
    note.setAttribute('id', 'source-graph-note');

    const reader = el('div', 'source-reader');
    reader.setAttribute('id', 'source-reader');
    reader.setAttribute('role', 'region');
    reader.setAttribute('tabindex', '0');
    reader.setAttribute('aria-busy', 'false');

    const status = el('span', 'visually-hidden');
    status.setAttribute('id', 'source-status');
    status.setAttribute('role', 'status');
    status.setAttribute('aria-live', 'polite');

    column.append(backRow, head, actions, reader, status);
    panel.replaceChildren(column);
    return { back, backLabel, title, id, meta, actions, pdf, graph, note, reader, status };
}

async function seedDocuments() {
    try {
        const response = await fetch('/api/sources');
        if (!response.ok) return;
        const body = await response.json();
        if (body && Array.isArray(body.documents)) setDocuments(body.documents);
    } catch (error) {
        // The list only adds sizes and flags; the viewer works without it.
    }
}

// switchPanel(panel), getActivePanel() and openGraphWith(detail, event) come
// from app.js. Calling this again only refreshes them.
export function initSourceViewer({ switchPanel, getActivePanel, openGraphWith }) {
    deps = { switchPanel, getActivePanel, openGraphWith };
    if (listening) return;
    const panel = document.getElementById('source-panel');
    if (!panel) return;
    listening = true;
    ui = buildPanel(panel);

    window.addEventListener('navigate-source', (event) => openDocument(event && event.detail));
    document.addEventListener('keydown', (event) => {
        if (!deps || deps.getActivePanel() !== 'source') return;
        if (event.key !== 'Escape' || event.defaultPrevented) return;
        goBack();
    });
    seedDocuments();
}
