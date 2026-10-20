// display.js - Sole frontend source of entity type color, shape, label and description.
// Exports: isHexColor, typeKey, setDisplayData, loadDisplay, typeDisplay, entityColor, legendEntries,
//          makeSwatch, buildLegendChip, renderLegendMessage, isSourceType, isSourceRelation,
//          sourceTypes, setChipPressed, relationDisplay, categoryEntries, makeEdgeSample
// SEC-01: values are validated before use and rendered via textContent, setAttribute and
// createElement/createElementNS only. SVG tag names come from SWATCH_GEOMETRY, never from data.

const NEUTRAL_COLOR = '#6b7280';
const EDGE_NEUTRAL_COLOR = '#8b8f99';
const SHAPES = ['dot', 'square', 'diamond', 'triangle', 'triangleDown', 'star', 'hexagon'];
const SOURCES_FAMILY = 'Sources';

let typeMap = new Map();
let familyOrder = [];
let relationMap = new Map();
let categoryMap = new Map();
let loadPromise = null;

export function isHexColor(value) {
    return typeof value === 'string' && /^#[0-9a-fA-F]{6}$/.test(value);
}

// Mirrors core.graph_display.entity_type_key: null/missing/empty -> 'UNKNOWN'.
export function typeKey(type) {
    return type === null || type === undefined || type === '' ? 'UNKNOWN' : String(type);
}

function humanize(type) {
    const text = String(type || '')
        .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
        .replace(/([A-Z])([A-Z][a-z])/g, '$1 $2')
        .replace(/_/g, ' ')
        .trim()
        .replace(/\s+/g, ' ')
        .toLowerCase();
    return text.charAt(0).toUpperCase() + text.slice(1);
}

function otherEdgeColor(cats) {
    return cats.has('other') ? cats.get('other').color : EDGE_NEUTRAL_COLOR;
}

// Pure: validates every color and shape, then replaces module state.
export function setDisplayData(payload) {
    const next = new Map();
    for (const t of (payload && payload.types) || []) {
        if (!t || typeof t.type !== 'string') continue;
        const family = typeof t.family === 'string' && t.family ? t.family : 'Other';
        next.set(t.type, {
            isSource: t.is_source === true || family === SOURCES_FAMILY,
            color: isHexColor(t.color) ? t.color.toLowerCase() : NEUTRAL_COLOR,
            shape: SHAPES.includes(t.shape) ? t.shape : 'dot',
            family,
            label: typeof t.label === 'string' && t.label ? t.label : humanize(t.type),
            description: typeof t.description === 'string' ? t.description : '',
            count: Number.isFinite(t.count) ? t.count : 0,
        });
    }
    typeMap = next;
    const cats = new Map();
    const rawCats = payload && payload.categories;
    if (rawCats && typeof rawCats === 'object') {
        for (const [name, c] of Object.entries(rawCats)) {
            if (!c || typeof c !== 'object') continue;
            cats.set(name, {
                label: typeof c.label === 'string' && c.label ? c.label : humanize(name),
                color: isHexColor(c.color) ? c.color.toLowerCase() : EDGE_NEUTRAL_COLOR,
            });
        }
    }
    categoryMap = cats;
    const rels = new Map();
    const rawRels = payload && payload.relations;
    if (rawRels && typeof rawRels === 'object') {
        for (const [name, r] of Object.entries(rawRels)) {
            if (!r || typeof r !== 'object') continue;
            const category = typeof r.category === 'string' && r.category ? r.category : 'other';
            const catColor = cats.has(category) ? cats.get(category).color : otherEdgeColor(cats);
            rels.set(name, {
                category,
                color: isHexColor(r.color) ? r.color.toLowerCase() : catColor,
                description: typeof r.description === 'string' ? r.description : '',
                sourceEdge: r.source_edge === true,
            });
        }
    }
    relationMap = rels;
    familyOrder = ((payload && payload.families) || [])
        .map((f) => (f && typeof f.name === 'string' ? f.name : ''))
        .filter(Boolean);
}

// Fetches the resolved display once; the promise is cached. A failure clears
// the cache so a later call can retry.
export function loadDisplay() {
    if (!loadPromise) {
        loadPromise = (async () => {
            const resp = await fetch('/api/graph/entity-types');
            if (!resp.ok) {
                throw new Error(`Entity-types API returned ${resp.status} ${resp.statusText}`);
            }
            const payload = await resp.json();
            setDisplayData(payload);
            return payload;
        })().catch((err) => {
            loadPromise = null;
            throw err;
        });
    }
    return loadPromise;
}

export function typeDisplay(type) {
    const known = typeMap.get(typeKey(type));
    if (known) return { ...known };
    return {
        color: NEUTRAL_COLOR,
        shape: 'dot',
        family: 'Other',
        label: humanize(type),
        description: '',
        count: 0,
    };
}

// True when the resolver classed the type as a source (Sources family).
export function isSourceType(type) {
    const known = typeMap.get(typeKey(type));
    return known ? known.isSource === true : false;
}

// True when the relation is flagged source_edge. Without display data the
// documented fallback is MENTIONED_IN only.
export function isSourceRelation(rel) {
    if (relationMap.size === 0) return rel === 'MENTIONED_IN';
    const known = relationMap.get(rel);
    return known ? known.sourceEdge === true : false;
}

// Observed type keys that the resolver classed as sources.
export function sourceTypes() {
    return [...typeMap.entries()].filter(([, d]) => d.isSource).map(([type]) => type);
}

// Category, color, label and description for a relation. Unknown relations are
// category 'other'; without display data the color is the neutral edge grey.
export function relationDisplay(rel) {
    const known = relationMap.get(rel);
    if (known) {
        return {
            category: known.category,
            color: known.color,
            label: humanize(rel),
            description: known.description,
        };
    }
    return {
        category: 'other',
        color: otherEdgeColor(categoryMap),
        label: humanize(rel),
        description: '',
    };
}

// Relation categories in served order: [{name, label, color}].
export function categoryEntries() {
    return [...categoryMap.entries()].map(([name, c]) => ({ name, label: c.label, color: c.color }));
}

export function entityColor(type) {
    return typeDisplay(type).color;
}

function familyRank(family) {
    if (family === SOURCES_FAMILY) return Number.MAX_SAFE_INTEGER;
    const idx = familyOrder.indexOf(family);
    return idx >= 0 ? idx : Number.MAX_SAFE_INTEGER - 1;
}

// Observed types: family order (Sources last), then count desc, then label asc.
export function legendEntries() {
    const entries = [...typeMap.entries()].map(([type, d]) => ({ type, ...d }));
    entries.sort((a, b) => (
        familyRank(a.family) - familyRank(b.family)
        || b.count - a.count
        || a.label.localeCompare(b.label)
    ));
    return entries;
}

// ---------------------------------------------------------------------------
// Swatches, legend chips and legend messages
// ---------------------------------------------------------------------------

const SVG_NS = 'http://www.w3.org/2000/svg';

// Fixed table: the only place an SVG tag name or geometry is defined.
const SWATCH_GEOMETRY = {
    dot: { tag: 'circle', attrs: { cx: '8', cy: '8', r: '6' } },
    square: { tag: 'rect', attrs: { x: '2', y: '2', width: '12', height: '12', rx: '2' } },
    diamond: { tag: 'polygon', attrs: { points: '8,1 15,8 8,15 1,8' } },
    triangle: { tag: 'polygon', attrs: { points: '8,2 15,14 1,14' } },
    triangleDown: { tag: 'polygon', attrs: { points: '1,2 15,2 8,14' } },
    hexagon: { tag: 'polygon', attrs: { points: '8,1 14,4.5 14,11.5 8,15 2,11.5 2,4.5' } },
    star: {
        tag: 'polygon',
        attrs: {
            points: '8,1 9.76,5.57 14.66,5.84 10.85,8.93 12.11,13.66 8,11 3.89,13.66 5.15,8.93 1.34,5.84 6.24,5.57',
        },
    },
};

function paintSwatchShape(shapeEl, color, hollow) {
    if (hollow) {
        shapeEl.setAttribute('fill', 'none');
        shapeEl.setAttribute('stroke', color);
        shapeEl.setAttribute('stroke-width', '1.5');
    } else {
        shapeEl.setAttribute('fill', color);
        shapeEl.removeAttribute('stroke');
        shapeEl.removeAttribute('stroke-width');
    }
}

// Sets a legend chip's pressed state and repaints its swatch hollow/filled.
export function setChipPressed(chip, pressed) {
    chip.setAttribute('aria-pressed', String(pressed));
    const type = chip.getAttribute('data-type');
    const shapeEl = chip.firstChild || (chip.children && chip.children[0]) || null;
    if (type === null || !shapeEl || !shapeEl.firstChild) return;
    const color = entityColor(type);
    paintSwatchShape(shapeEl.firstChild, isHexColor(color) ? color : NEUTRAL_COLOR, !pressed);
}

// Returns an inline SVG showing the type's shape and color.
export function makeSwatch(type, px = 16, { hollow = false } = {}) {
    const d = typeDisplay(type);
    const color = isHexColor(d.color) ? d.color : NEUTRAL_COLOR;
    const geom = Object.prototype.hasOwnProperty.call(SWATCH_GEOMETRY, d.shape)
        ? SWATCH_GEOMETRY[d.shape]
        : SWATCH_GEOMETRY.dot;

    const svg = document.createElementNS(SVG_NS, 'svg');
    svg.setAttribute('viewBox', '0 0 16 16');
    svg.setAttribute('width', String(px));
    svg.setAttribute('height', String(px));
    svg.setAttribute('aria-hidden', 'true');
    svg.setAttribute('focusable', 'false');
    svg.setAttribute('class', 'type-swatch');

    const shapeEl = document.createElementNS(SVG_NS, geom.tag);
    for (const [name, value] of Object.entries(geom.attrs)) shapeEl.setAttribute(name, value);
    paintSwatchShape(shapeEl, color, hollow);
    svg.appendChild(shapeEl);
    return svg;
}

// Returns a 24x8 inline SVG line sample in the given edge color; dashed for
// claims that are not asserted. The color is validated before use.
export function makeEdgeSample(color, { dashed = false } = {}) {
    const svg = document.createElementNS(SVG_NS, 'svg');
    svg.setAttribute('viewBox', '0 0 24 8');
    svg.setAttribute('width', '24');
    svg.setAttribute('height', '8');
    svg.setAttribute('aria-hidden', 'true');
    svg.setAttribute('focusable', 'false');
    svg.setAttribute('class', 'edge-sample');

    const line = document.createElementNS(SVG_NS, 'line');
    line.setAttribute('x1', '0');
    line.setAttribute('y1', '4');
    line.setAttribute('x2', '24');
    line.setAttribute('y2', '4');
    line.setAttribute('stroke', isHexColor(color) ? color : EDGE_NEUTRAL_COLOR);
    line.setAttribute('stroke-width', '2');
    if (dashed) line.setAttribute('stroke-dasharray', '4 3');
    svg.appendChild(line);
    return svg;
}

let descriptionCounter = 0;

// Builds one toggle chip for the entity-type legend. onToggle(type, pressed) fires after each click.
export function buildLegendChip(entry, onToggle) {
    const label = typeof entry.label === 'string' && entry.label ? entry.label : humanize(entry.type);
    const count = Number.isFinite(entry.count) ? entry.count : 0;
    const description = typeof entry.description === 'string' ? entry.description : '';
    const family = typeof entry.family === 'string' && entry.family ? entry.family : 'Other';

    const chip = document.createElement('button');
    chip.setAttribute('type', 'button');
    chip.className = 'legend-chip';
    chip.setAttribute('aria-pressed', 'true');
    chip.setAttribute('data-type', String(entry.type));
    chip.setAttribute('title', description || `${family} family`);
    chip.setAttribute('aria-label', `${label}, ${count.toLocaleString()}`);

    const swatch = makeSwatch(entry.type, 16);
    chip.appendChild(swatch);

    const labelEl = document.createElement('span');
    labelEl.className = 'legend-chip__label';
    labelEl.textContent = label;
    chip.appendChild(labelEl);

    const countEl = document.createElement('span');
    countEl.className = 'legend-chip__count';
    countEl.textContent = count.toLocaleString();
    chip.appendChild(countEl);

    if (description) {
        descriptionCounter += 1;
        const descEl = document.createElement('span');
        descEl.id = `legend-desc-${descriptionCounter}`;
        descEl.className = 'visually-hidden';
        descEl.textContent = description;
        chip.appendChild(descEl);
        chip.setAttribute('aria-describedby', descEl.id);
    }

    chip.addEventListener('click', () => {
        const pressed = chip.getAttribute('aria-pressed') !== 'true';
        setChipPressed(chip, pressed);
        if (typeof onToggle === 'function') onToggle(entry.type, pressed);
    });

    return chip;
}

const LEGEND_MESSAGES = {
    empty: [
        'No entity types to show',
        'This graph has no nodes yet. Run /epistract:ingest to add documents, then reopen the workbench.',
    ],
    error: [
        "Couldn't load entity types. The graph still works, but colors and the legend are unavailable. "
        + 'Reload the page; if it persists, check that the workbench server is running.',
    ],
};

// Replaces the container's content with the empty or error copy.
export function renderLegendMessage(container, kind) {
    const lines = LEGEND_MESSAGES[kind === 'error' ? 'error' : 'empty'];
    const nodes = lines.map((text) => {
        const p = document.createElement('p');
        p.className = kind === 'error' ? 'legend-message legend-message--error' : 'legend-message';
        p.textContent = text;
        return p;
    });
    container.replaceChildren(...nodes);
}
