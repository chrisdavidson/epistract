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

const filterParts = arrangeControls();
await initGraph({});
window.dispatchEvent(new CustomEvent('graph-panel-opened'));
if (filterParts) wireFilters(filterParts);
