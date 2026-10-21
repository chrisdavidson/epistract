// dashboard.js - DOM builders for the auto-generated Dashboard entity summary.
//
// SEC-01: entity type keys come from graph_data.json and are untrusted. They
// reach the DOM only through textContent and setAttribute, and are read back
// through dataset. Markup is never built from strings and no inline handlers
// are used.
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
