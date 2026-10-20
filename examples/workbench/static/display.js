// display.js - Sole frontend source of entity type color, shape, label and description.
// Exports: isHexColor, setDisplayData, loadDisplay, typeDisplay, entityColor, legendEntries
// SEC-01: values are validated before use and rendered via textContent and style properties only.

const NEUTRAL_COLOR = '#6b7280';
const SHAPES = ['dot', 'square', 'diamond', 'triangle', 'triangleDown', 'star', 'hexagon'];
const SOURCES_FAMILY = 'Sources';

let typeMap = new Map();
let familyOrder = [];
let loadPromise = null;

export function isHexColor(value) {
    return typeof value === 'string' && /^#[0-9a-fA-F]{6}$/.test(value);
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

// Pure: validates every color and shape, then replaces module state.
export function setDisplayData(payload) {
    const next = new Map();
    for (const t of (payload && payload.types) || []) {
        if (!t || typeof t.type !== 'string') continue;
        next.set(t.type, {
            color: isHexColor(t.color) ? t.color.toLowerCase() : NEUTRAL_COLOR,
            shape: SHAPES.includes(t.shape) ? t.shape : 'dot',
            family: typeof t.family === 'string' && t.family ? t.family : 'Other',
            label: typeof t.label === 'string' && t.label ? t.label : humanize(t.type),
            description: typeof t.description === 'string' ? t.description : '',
            count: Number.isFinite(t.count) ? t.count : 0,
        });
    }
    typeMap = next;
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
    const known = typeMap.get(type);
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
