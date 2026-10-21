// static_view.js - entry module of the standalone graph.html.
// The workbench never loads this file. It rearranges the graph panel into a
// compact toolbar plus legend strip, moves the rarely used filters into a
// Filters popover, then starts the shared graph modules.
// SEC-01: controls are built with createElement / textContent / setAttribute
// only; no graph data is ever written into markup.

import { initGraph } from './graph.js';

const GLYPH_CLOSED = '▾';
const GLYPH_OPEN = '▴';

function byId(id) {
    return document.getElementById(id);
}

// Moves the existing controls into the order they are laid out in, so Tab
// order equals visual order, and returns the elements the popover needs.
function arrangeControls() {
    const controls = document.querySelector('.graph-controls');
    const toolbar = controls && controls.querySelector('.graph-toolbar');
    const search = byId('graph-search');
    const legendLabel = byId('entity-legend-label');
    const sourcesStatus = byId('graph-sources-status');
    const fitBtn = byId('graph-fit-btn');
    const panelRoot = byId('graph-panel');
    if (!controls || !toolbar || !search || !panelRoot || !fitBtn || !sourcesStatus) return null;

    toolbar.insertBefore(search, toolbar.firstChild);
    controls.insertBefore(toolbar, legendLabel || controls.firstChild);
    for (const id of ['edge-key-toggle', 'graph-groups-btn']) {
        const btn = byId(id);
        if (btn) toolbar.insertBefore(btn, fitBtn);
    }
    if (legendLabel) legendLabel.classList.add('visually-hidden');

    const button = document.createElement('button');
    button.type = 'button';
    button.id = 'static-filters-btn';
    button.className = 'toggle-btn';
    button.setAttribute('aria-expanded', 'false');
    button.setAttribute('aria-controls', 'static-filters-panel');
    const text = document.createElement('span');
    text.textContent = 'Filters';
    const badge = document.createElement('span');
    badge.className = 'count';
    badge.hidden = true;
    badge.textContent = '0';
    const glyph = document.createElement('span');
    glyph.setAttribute('aria-hidden', 'true');
    glyph.textContent = GLYPH_CLOSED;
    button.append(text, badge, glyph);
    sourcesStatus.after(button);

    const panel = document.createElement('div');
    panel.id = 'static-filters-panel';
    panel.className = 'static-filters';
    panel.setAttribute('role', 'group');
    panel.setAttribute('aria-label', 'Graph filters');
    panel.hidden = true;
    controls.after(panel);
    for (const id of ['epistemic-filter', 'confidence-filter', 'min-degree-filter', 'relation-type-filter']) {
        const section = byId(id);
        if (section) panel.appendChild(section);
    }
    return { controls, button, panel, badge, glyph };
}

// Wires the open/close behavior and the active-filter badge.
function wireFilters({ controls, button, panel, badge, glyph }) {
    const confidence = byId('confidence-slider');
    const minDegree = byId('min-degree-slider');
    // The graph picks its own slider defaults (for example the lowest observed
    // confidence) once its data has loaded. The popover cannot be used before
    // that, so the defaults are read the first time it opens; any other value
    // counts as an active filter.
    let defaults = null;

    function readDefaults() {
        defaults = {
            confidence: confidence ? confidence.value : '0',
            minDegree: minDegree ? minDegree.value : '0',
        };
    }

    function activeCount() {
        if (!defaults) return 0;
        let n = 0;
        if (panel.querySelector('#epistemic-toggles .epistemic-chip:not(.active)')) n += 1;
        if (confidence && confidence.value !== defaults.confidence) n += 1;
        if (panel.querySelector('#relation-type-panel input[type="checkbox"]:not(:checked)')) n += 1;
        if (minDegree && minDegree.value !== defaults.minDegree) n += 1;
        return n;
    }

    function updateBadge() {
        const n = activeCount();
        badge.textContent = String(n);
        badge.hidden = n === 0;
        if (n > 0) button.setAttribute('aria-label', `Filters, ${n} active`);
        else button.removeAttribute('aria-label');
    }

    function place() {
        panel.style.setProperty('--static-filters-top', `${controls.offsetTop + controls.offsetHeight + 4}px`);
    }

    function setOpen(open) {
        if (open) {
            if (!defaults) readDefaults();
            place();
        }
        panel.hidden = !open;
        button.setAttribute('aria-expanded', open ? 'true' : 'false');
        button.classList.toggle('static-filters-btn--open', open);
        glyph.textContent = open ? GLYPH_OPEN : GLYPH_CLOSED;
    }

    button.addEventListener('click', () => setOpen(panel.hidden));

    // Esc closes the popover and keeps focus on the button. The event is
    // stopped only while the popover is open, so the graph's own Esc chain
    // (hover card, focus mode, zoomed group) is untouched otherwise.
    function onKeydown(event) {
        if (event.key !== 'Escape' || panel.hidden) return;
        event.stopPropagation();
        setOpen(false);
        button.focus();
    }
    button.addEventListener('keydown', onKeydown);
    panel.addEventListener('keydown', onKeydown);

    document.addEventListener('click', (event) => {
        if (panel.hidden) return;
        const target = event.target;
        if (button.contains(target) || panel.contains(target)) return;
        setOpen(false);
    });

    for (const type of ['input', 'change', 'click']) {
        // Deferred so the graph's own handler for the same event has run.
        panel.addEventListener(type, () => setTimeout(updateBadge, 0));
    }
    updateBadge();
}

function makeCard(heading, body) {
    const card = document.createElement('div');
    card.className = 'static-card';
    const h = document.createElement('h2');
    h.textContent = heading;
    const p = document.createElement('p');
    p.textContent = body;
    card.append(h, p);
    return card;
}

// Reads the embedded graph payload through the same fetch shim the graph uses.
async function embeddedNodeCount() {
    try {
        const resp = await fetch('/api/graph');
        const data = await resp.json();
        return Array.isArray(data.nodes) ? data.nodes.length : -1;
    } catch (e) {
        return -1;
    }
}

async function start() {
    const keys = Array.isArray(window.__epistractKeys) ? window.__epistractKeys : [];
    if (!keys.includes('/api/graph')) {
        // Details only on the console; the card never echoes data or errors.
        console.error('epistract: the graph payload is missing or unreadable in this file');
        window.__epistractShowCard(
            'The data in this file is missing or damaged. Run /epistract:view again to regenerate graph.html.');
        window.__epistractReady = true;
        return;
    }

    const filterParts = arrangeControls();
    await initGraph({
        groupLoadFailure: 'Grouping data is missing from this file. Run /epistract:view again.',
    });
    window.__epistractReady = true;
    window.dispatchEvent(new CustomEvent('graph-panel-opened'));
    if (filterParts) wireFilters(filterParts);

    if (!keys.includes('/api/graph/entity-types')) {
        const header = document.querySelector('.static-header');
        if (header) {
            const status = document.createElement('p');
            status.className = 'static-status';
            status.setAttribute('role', 'status');
            status.textContent = 'Some display data is missing from this file. Run /epistract:view again to regenerate it.';
            header.appendChild(status);
        }
    }

    if ((await embeddedNodeCount()) === 0) {
        // initGraph does not wait for the graph build; the data is embedded, so
        // the build finishes within the same task. Yield once so the empty card
        // replaces the (blank) canvas instead of being drawn over by it.
        await new Promise((resolve) => setTimeout(resolve, 0));
        const container = byId('graph-container');
        if (container) {
            container.removeAttribute('aria-busy');
            container.replaceChildren(makeCard(
                'No nodes to show',
                'This graph has no nodes yet. Run /epistract:ingest to add documents, then run /epistract:view again.'));
        }
    }
}

await start();
