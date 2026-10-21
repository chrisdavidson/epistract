import { initSidebar, showNodeDetail, showEdgeDetail, hideSidebar } from './sidebar.js';
import {
    loadDisplay, typeDisplay, typeKey, entityColor, legendEntries, buildLegendChip,
    renderLegendMessage, isSourceType, isSourceRelation, sourceTypes, setChipPressed,
    relationDisplay, categoryEntries, makeEdgeSample,
} from './display.js';
import {
    isSourceEdge, linkDegrees, scaleBucket, labelFontSize, nodeSize, edgeWidth,
    truncateLabel, labelCutoff, stableEdgeIds, LABEL_BASE_WORLD,
    edgeDashes, edgeColorObject, namedEdgeIds, edgeBaseOpacity, edgeDimOpacity, hoverCardModel,
    humanizeRelation, focusIds, focusDelta, edgeLabelFont,
    PRESENT_DISPLAY_SCALE, setDisplayScale, getDisplayScale, labelBudget,
} from './graph_style.js';
import { initHoverCard, showHoverCard, hideHoverCard, isHoverCardVisible } from './hovercard.js';
import {
    packGroups, seedInside, anchorNodeSpecs, anchorEdgeSpecs, dataEdgeLengths,
    isAnchorId, groupIterations, relayoutTimeoutFor, FIT_MARGIN, regionGeometry, placeRegionLabels,
    REGION_COLORS, REGION_LABEL_PX, REGION_PILL_PAD_PX, clampIntoRegion,
    kHop, pushFocus, popFocus, truncateFocus, setTopHops, crumbsFor, focusModeLabelIds,
    radioTarget, FOCUS_MODE_MAX_LABELS, FOCUS_OUTER_RING_LABELS, FOCUS_TRUNCATE_CHARS, separateRegions, REGION_SEPARATION_GAP, focusLayout, fnv1a,
} from './grouping.js';

// graph.js - Graph panel: vis.js network, search, entity type toggles

// ---------------------------------------------------------------------------
// Tuning constants — these are the knobs a developer retunes by eye in the
// dashboard (see Task 3 checkpoint in 260802-cu1-PLAN.md). One-line edits.
// ---------------------------------------------------------------------------
const LABEL_MIN_NODE_COUNT = 80;      // graphs smaller than this: every node stays labelled at every zoom level (no gating)
const LABEL_ZOOM_STOPS = [
    // Ordered most-zoomed-in -> most-zoomed-out. Walk top-down and take the
    // FIRST stop whose `scale` is <= network.getScale(); `maxLabels` is then
    // the budget of labels to draw, and the degree cutoff is derived as the
    // degree of the maxLabels-th highest-degree node. The final stop MUST
    // have scale: 0 so the lookup always terminates.
    //
    // maxLabels (a count) rather than a fraction of maxDegree, because
    // maxDegree is set by a single outlier hub and the mapping from fraction
    // to on-screen label count is wildly non-linear. On the 278-node GLP-1
    // graph (maxDegree 79) fractions 0.03/0.05/0.20 yielded 152/109/24
    // labels — unpredictable. A count is the thing we actually want to
    // control, so tune these numbers directly against what looks right.
    { scale: 2.00, maxLabels: Infinity }, // deep zoom: label everything
    { scale: 1.20, maxLabels: 120 },
    { scale: 0.80, maxLabels: 60 },
    { scale: 0.50, maxLabels: 30 },
    { scale: 0.00, maxLabels: 15 },       // fit view / zoomed out: hubs only
];
const LABEL_HIDDEN_FONT_SIZE = 0;     // vis-network skips drawing a label at font size 0 without dropping the label string (tooltips/search still work)
const LABEL_UPDATE_THROTTLE_MS = 120; // trailing-debounce window; vis fires `zoom` continuously during a scroll gesture
const NODE_FONT_BASE = {              // non-size font properties — single source of truth for node mapping + label controller
    color: '#1a1a1a',
    background: 'rgba(255, 255, 255, 0.85)',
};
const PRESENT_LABEL_BACKGROUND = '#ffffff';  // opaque label pills in present mode; edges behind a label blur it on a projector
const PRESENT_STORAGE_KEY = 'epistract.presentMode';
const NODE_BORDER = 'rgba(0,0,0,0.25)';       // neutral node outline; the type is carried by fill + shape
const NODE_SELECTED_BORDER = '#1a1a2e';
const EDGE_SMOOTH_MAX_EDGES = 400;              // above this edge count, render straight edges — curved edges are visual mud and a per-frame render cost at scale
const PHYSICS_STABILIZATION_ITERATIONS = 400;   // raise for a better-separated layout at the cost of a longer time-to-stabilize
const PHYSICS_STABILIZATION_UPDATE_INTERVAL = 50; // how often vis reports stabilization progress and redraws while settling
const FA2_GRAVITATIONAL_CONSTANT = -120;        // node-node repulsion; more negative pushes clusters further apart
const FA2_CENTRAL_GRAVITY = 0.005;              // pull toward the centre; lower lets clusters spread
const FA2_SPRING_LENGTH = 160;                  // rest length of an edge
const FA2_SPRING_CONSTANT = 0.05;               // edge stiffness
const FA2_DAMPING = 0.5;                        // higher settles faster with less oscillation
const FA2_AVOID_OVERLAP = 0.6;                  // 0 to 1; adds a node-radius-aware repulsion term that stops dots from stacking

const HOVER_CARD_DELAY_MS = 150;      // pause before the hover card appears

const FALLBACK_SOURCE_TYPES = new Set(['DOCUMENT', 'PUBLICATION']); // used only when display data failed to load

// The one "is this a source edge" rule for every surface (size, labels,
// slider, sidebar, hover card, physics): an endpoint is a Sources-family node
// or the relation is flagged source_edge by the resolver.
function isSourceEdgeRecord(e) {
    return isSourceEdge(e, id => sourceNodeIds.has(id), isSourceRelation);
}

function isSourceNodeId(id) {
    return sourceNodeIds.has(id);
}

const SIDEBAR_OPTS = { isSourceNode: isSourceNodeId, isSourceEdge: isSourceEdgeRecord, focusInfo };

// Reduced-motion users get an instant fit; everyone else an eased one.
function fitAnimation(duration) {
    const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches;
    return reduce ? false : { duration };
}

let network = null;
let allNodes = [];
let allEdges = [];
let degreeMap = {};          // hoisted for sidebar and Phase 10 neighbourhood highlight
let visNodes = null;
let visEdges = null;
let activeTypes = new Set();
// WR-02: the type filter only applies once the legend has been built from the
// display data. If that data failed to load (or is empty), activeTypes stays
// empty and must not hide every node.
let typeFilterEnabled = false;
let callbacks = {};
const pinnedNodes = new Set();
let _resizeListenerAttached = false;
let _panelListenersAttached = false;      // graph-panel-opened/closed window listeners
let highlightedNodeId = null;             // currently highlighted node; null = no highlight active
let activeEpistemicStatuses = new Set();  // populated by buildEpistemicChips() (plan 03)
let confidenceThreshold = 0;             // populated by initConfidenceSlider() (plan 03)
let activeRelationTypes = new Set();      // populated by buildRelationTypeDropdown() (Phase 11)
let minDegreeThreshold = 0;               // populated by initMinDegreeSlider() (Phase 11)
let maxDegree = 0;                        // highest linkDegree (edges without a Sources endpoint); read by initMinDegreeSlider() (Phase 11 D-10)
let sortedDegrees = [];                   // linkDegrees of non-source nodes, descending; rebuilt in buildGraph() (260802-cu1)
let linkDegreeMap = {};                   // id -> count of non-source edges; drives size, label budget and the min-degree slider
let sourceNodeIds = new Set();            // ids of Sources-family nodes in the loaded graph
let sourcesShown = false;                 // Show sources toggle; sources are hidden on load
let sourcesPlaced = false;                // sources already moved next to their neighbours for this build
let sourceNeighbours = new Map();         // source id -> ids of its non-source neighbours
let sourcePhysicsOn = false;              // source nodes/edges currently take part in the force layout
let _labelUpdateTimer = null;             // pending throttled applyScaleStyle() call (260802-cu1)
let _lastStyleKey = null;                 // last-applied `${cutoff}|${bucket}`; skip DataSet writes when unchanged
let edgeColorById = new Map();            // stable edge id -> validated category color; source for every edge color write
let edgeIdByIndex = [];                   // stable vis edge id for each entry of allEdges
let nodeById = new Map();                 // id -> node record; built once per graph
let adjacency = new Map();                // id -> incident edges; built once so hover never scans allEdges
let _hoverTimer = null;                   // pending hover-card show
let pinnedCardNodeId = null;              // node whose card stays pinned while selected
let _hoverListenersAttached = false;
let hoverFocus = new Set();               // hovered node + capped neighbours
let selectFocus = new Set();              // selected node + capped neighbours
let hoverCenterId = null;
let selectCenterId = null;
let focusNodeIds = new Set();             // union currently applied to the node DataSet
let focusEdgeIds = new Set();             // edges currently showing their relation name
let hoveredEdgeId = null;
let _focusRaf = null;                     // pending applyFocus() handle
let _focusCancel = null;                  // matching cancel function
let _lastCutoff = 0;                      // degree cutoff last applied by applyScaleStyle()
let groupsPayload = null;                 // /api/graph/groups response; null when the endpoint failed
let groupMode = 'none';                   // 'cluster' | 'family' | 'none' for the current build
let groupAssignment = new Map();          // non-source node id -> group id for the current build
let groupLayout = new Map();              // group id -> {x, y, r} circle the group is packed into
let sourceGroup = new Map();               // source id -> its plurality group id for the current build
let _fitShrink = null;                    // pending post-animation fit margin handler
let layoutToken = 0;                      // bumped by every relayout, failure and rebuild; stale completions compare and bail
let relayoutBusy = false;                 // a layout (the initial one or a relayout) is in flight
let _initialSettled = false;              // the initial layout of the current build has settled
let freeLayoutPositions = null;           // Map id -> {x, y} of the free layout; restored by the None option
let relayoutPrev = null;                  // layout state to roll back to if the running relayout fails
let _relayoutTimer = null;                // fails a relayout that never completes
let _hintOverride = null;                 // transient text shown in the group hint slot
let _hintTimer = null;                    // clears the relayout failure message
let _groupControlAttached = false;
let focusStack = [];                      // focus mode path: [{id, hops}], the last entry is the centre
let focusHops = 1;                        // neighbourhood size of the current focus (shared with the sidebar)
let focusPre = null;                      // {positions, sourcesPlaced} captured before the first focus layout
let _focusLayoutKey = null;              // signature of the focus layout last applied
let _focusOpensSidebar = false;           // set while a focus change that will open the sidebar lays out
let _measureCtx = null;                  // 2d context used to measure label widths
let focusSet = null;                      // Set of node ids shown while focused; null when not focused
let focusLabelIds = new Set();            // focus nodes drawn with full labels
let focusCounts = { 1: 0, 2: 0 };         // node counts for 1 and 2 hops around the centre
let focusBarShown = false;                // the focus bar is currently visible
let focusEndedNote = null;                // name of a centre a filter just hid; set while filterGraph() runs
let graphPanelActive = false;             // the Graph tab is the visible panel (guards Escape)
let _lastFocusSig = null;                 // last graph-focus-changed payload, to dispatch only real changes
let _focusListenersAttached = false;
let pendingShowTypes = null;              // graph-show-types request waiting for the graph to load (or for a relayout to end); last request wins
let _showTypesListenerAttached = false;
let activeRegionId = null;                // group whose Groups-list row was clicked (zoomed to)
let emphasizedRegionId = null;            // group whose row is hovered or focused
let groupRowEls = new Map();              // group id -> its Groups-list row button
let _groupListenersAttached = false;
let _frameRegions = null;                 // regions computed by beforeDrawing, reused by afterDrawing
let _lastPlaced = [];                     // pill boxes drawn in the last frame
let _regionFont = null;                   // --font-body stack, read once
// A relayout not finished within relayoutTimeoutMs() is rolled back; the
// budget scales with the node count (grouping.js relayoutTimeoutFor, WR-05).
const RELAYOUT_FAIL_MESSAGE_MS = 6000;    // how long the failure message stays in the hint slot (window._relayoutFailMessageMs overrides)
const RELAYOUT_FAIL_TEXT = "Couldn't arrange groups. Showing the previous layout.";
const RELAYOUT_BUSY_TEXT = 'Arranging groups\u2026';
const LAYOUT_BUSY_TEXT = 'Arranging layout\u2026';   // hint while an ungrouped initial layout settles
const GROUP_SETTLING_TITLE = 'Available once the layout has settled';
const GROUP_LOAD_FAILURE = "Grouping data didn't load. Reload the page to try again.";
const GROUP_MODE_ORDER = ['cluster', 'family', 'none'];
const GROUP_MODE_LABELS = { cluster: 'Topic cluster', family: 'Entity family', none: 'None' };
const GROUP_MODE_TITLES = {
    cluster: 'Group nodes by topic cluster (communities found in the documents)',
    family: 'Group nodes by entity family',
    none: 'No grouping: free layout',
};
const GROUP_LIST_MAX_ROWS = 40;           // Groups list rows before the "+N more groups" line
const GROUPS_DISABLED_TITLE = 'Choose a grouping to list its groups.';
const REGION_DASH_PX = [6, 4];            // Unclustered ring dash pattern, screen px
const REGION_STROKE_PX = 1;               // region ring width, screen px
const REGION_STROKE_EMPH_PX = 2;          // emphasized ring width, screen px
const REGION_PILL_RADIUS_PX = 4;          // pill corner radius, screen px

// vis-network color object: type fill with a neutral border.
function nodeColor(type) {
    const fill = entityColor(type);
    const selected = { background: fill, border: NODE_SELECTED_BORDER };
    return {
        background: fill,
        border: NODE_BORDER,
        highlight: { ...selected },
        hover: { ...selected },
    };
}

export async function initGraph(opts) {
    callbacks = opts || {};
    initHoverCard();
    initPresentMode();

    // Registered before anything is awaited so a Dashboard click made while the
    // display data or the graph is still loading is queued, never lost.
    if (!_showTypesListenerAttached) {
        _showTypesListenerAttached = true;
        window.addEventListener('graph-show-types', (event) => {
            requestShowTypes(event && event.detail);
        });
    }

    // Resolve type colors/shapes once, before the legend or nodes are built, so
    // every surface reads the same values regardless of build order.
    let displayLoaded = true;
    try {
        await loadDisplay();
    } catch (e) {
        displayLoaded = false;
        console.warn('Could not load entity display data:', e);
    }

    // Build the entity-type legend (swatch, label, count, description, filter toggle)
    const toggleContainer = document.getElementById('entity-toggles');
    if (toggleContainer) {
        try {
            // WR-04: clear stale entity types before re-populating so that
            // repeated initGraph calls (e.g. domain switch) do not leave
            // ghost types active in the filter Set.
            activeTypes.clear();
            typeFilterEnabled = false;
            const entries = displayLoaded ? legendEntries() : [];
            if (!displayLoaded) {
                renderLegendMessage(toggleContainer, 'error');
            } else if (entries.length === 0) {
                renderLegendMessage(toggleContainer, 'empty');
            } else {
                toggleContainer.replaceChildren();
                typeFilterEnabled = true;
                for (const entry of entries) {
                    const sourceType = isSourceType(entry.type);
                    if (!sourceType) activeTypes.add(entry.type);
                    const chip = buildLegendChip(entry, (type, pressed) => {
                        dropPendingShowTypes();
                        if (pressed) activeTypes.add(type);
                        else activeTypes.delete(type);
                        sourcesShown = sourceTypes().some(t => activeTypes.has(t));
                        if (sourcesShown) placeSources();
                        syncSourcePhysics();
                        syncSourcesButton();
                        filterGraph();
                    });
                    if (sourceType) setChipPressed(chip, false);
                    toggleContainer.appendChild(chip);
                }
            }
        } catch (e) {
            console.warn('Could not build entity type legend:', e);
            typeFilterEnabled = false;
            renderLegendMessage(toggleContainer, 'error');
        }
    }

    // Load graph data
    loadGraphData();

    // Search bar
    const searchInput = document.getElementById('graph-search');
    if (searchInput) {
        searchInput.addEventListener('input', () => { dropPendingShowTypes(); filterGraph(); });
    }

    // Severity filter
    const severityFilter = document.getElementById('severity-filter');
    if (severityFilter) {
        severityFilter.addEventListener('change', () => { dropPendingShowTypes(); filterGraph(); });
    }

    // Panel open/close handlers: window listeners, so registered once even
    // when initGraph runs again (domain switch).
    if (!_panelListenersAttached) {
        _panelListenersAttached = true;
        window.addEventListener('graph-panel-closed', () => { graphPanelActive = false; });
        window.addEventListener('graph-panel-opened', () => {
            graphPanelActive = true;
            if (network) {
                // A plain fit() emits neither `zoom` nor `animationFinished`, so
                // the scale-aware label/size controller must be run explicitly or
                // it keeps the styles computed while the panel was hidden.
                setTimeout(() => fitView(null, false), 100);
            }
        });
    }
}

async function loadGraphData() {
    try {
        const resp = await fetch('/api/graph');
        if (!resp.ok) {
            throw new Error(`Graph API returned ${resp.status} ${resp.statusText}`);
        }
        const data = await resp.json();
        allNodes = data.nodes || [];
        allEdges = data.edges || [];

        // Load claims data for severity filtering
        try {
            const claimsResp = await fetch('/api/graph/claims');
            if (!claimsResp.ok) {
                throw new Error(`Claims API returned ${claimsResp.status} ${claimsResp.statusText}`);
            }
            window._claimsData = await claimsResp.json();
        } catch (e) {
            window._claimsData = null;
        }

        // Group assignment never blocks the graph: any failure builds it ungrouped.
        try {
            const groupsResp = await fetch('/api/graph/groups');
            if (!groupsResp.ok) {
                throw new Error(`Groups API returned ${groupsResp.status} ${groupsResp.statusText}`);
            }
            groupsPayload = await groupsResp.json();
        } catch (e) {
            groupsPayload = null;
        }

        buildGraph();
        buildEpistemicChips();
        initConfidenceSlider();
        buildRelationTypeDropdown();
        initMinDegreeSlider();
        flushPendingShowTypes();
    } catch (e) {
        pendingShowTypes = null;
        console.error('Failed to load graph data:', e);
        const container = document.getElementById('graph-container');
        // CR-01: use createElement/textContent instead of innerHTML (SEC-01)
        if (container) {
            const errMsg = document.createElement('p');
            errMsg.className = 'graph-placeholder';
            errMsg.textContent = 'Failed to load graph data. Please reload the page.';
            container.appendChild(errMsg);
        }
    }
}

let _btnListenersAttached = false;   // WR-02: guard fitBtn + resetPinsBtn duplicate registration
let _sliderListenerAttached = false; // WR-02: guard confidence slider duplicate registration
let _relationFilterListenerAttached = false; // WR-02: guard relation-type bulk-action listeners
let _degreeSliderListenerAttached = false;   // WR-02: guard min-degree slider duplicate registration

// ---------------------------------------------------------------------------
// 260802-cu1: node label declutter. Gates node label visibility on zoom
// scale multiplied by node degree, so only hub nodes are labelled when
// zoomed out. Edge labels are removed entirely (see edge mapping above);
// relation type stays reachable via sidebar edge detail.
// ---------------------------------------------------------------------------
// Font for one node: labelled when it is in the hover/selection focus set or
// is a non-source hub at or above the degree cutoff. Always a complete object.
function nodeLabelFont(id, scale, cutoff) {
    // While focused, nodes outside the labelled focus set stay unlabelled at
    // rest (hover and selection still label them through focusNodeIds).
    const restingOk = focusSet === null || FOCUS_OUTER_RING_LABELS || focusLabelIds.has(id);
    const visible = focusNodeIds.has(id)
        || focusLabelIds.has(id)
        || (restingOk && !sourceNodeIds.has(id) && (linkDegreeMap[id] || 0) >= cutoff);
    return { ...nodeFontBase(), size: visible ? labelFontSize(scale) : LABEL_HIDDEN_FONT_SIZE };
}

function applyScaleStyle() {
    if (!network || !visNodes) return;

    const scale = network.getScale();
    const bucket = scaleBucket(scale);
    const gated = allNodes.length >= LABEL_MIN_NODE_COUNT;

    // Translate the label budget into a degree cutoff: the degree of the
    // maxLabels-th highest-degree node. Ties at the cutoff degree let a few
    // extra labels through, which beats dropping one of two equally-connected
    // nodes. Small graphs are never gated: every non-source node is labelled.
    let budget = Infinity;
    if (gated) {
        const stop = LABEL_ZOOM_STOPS.find(s => scale >= s.scale) || LABEL_ZOOM_STOPS[LABEL_ZOOM_STOPS.length - 1];
        budget = labelBudget(stop.maxLabels);
    }
    const cutoff = labelCutoff(sortedDegrees, budget);
    _lastCutoff = cutoff;

    // The expensive DataSet writes happen only when the cutoff or the scale
    // bucket changes, not on every zoom tick.
    const key = `${cutoff}|${bucket}`;
    if (key === _lastStyleKey) return;
    _lastStyleKey = key;

    // Node updates carry ONLY id + font + size and edge updates ONLY id +
    // width - never opacity, hidden, colour, or fixed - so this controller
    // cannot clobber the neighbourhood highlight (opacity), filterGraph()
    // visibility (hidden), or the pinned-node border (color/borderWidth/fixed).
    const fontWorld = labelFontSize(scale);
    let labelled = 0;
    const nodeUpdates = visNodes.getIds().filter(id => !isAnchorId(id)).map(id => {
        const degree = linkDegreeMap[id] || 0;
        const isSource = sourceNodeIds.has(id);
        const font = nodeLabelFont(id, scale, cutoff);
        if (font.size > 0) labelled++;
        return {
            id,
            font,
            size: nodeSize(degree, maxDegree, scale, isSource),
        };
    });
    visNodes.update(nodeUpdates);

    if (visEdges) {
        const edgeUpdates = allEdges.map((e, i) => {
            const update = {
                id: edgeIdByIndex[i],
                width: edgeWidth(e.support_count, scale),
                dashes: edgeDashes(e.epistemic_status, scale),
            };
            if (focusEdgeIds.has(update.id)) update.font = edgeLabelFont(scale, true);
            return update;
        });
        visEdges.update(edgeUpdates);
    }

    // Retuning aid: read `window._labelDebug` in the devtools console to see
    // which band the current view resolved to and how many labels it drew.
    window._labelDebug = {
        scale: Number(scale.toFixed(3)),
        bucket: bucket,
        budget: budget,
        cutoff: cutoff,
        fontWorld: Number(fontWorld.toFixed(1)),
        labelled: labelled,
        totalNodes: allNodes.length,
    };
}

// ---------------------------------------------------------------------------
// Present mode: one switch that scales labels, nodes, edges and group pills by
// PRESENT_DISPLAY_SCALE for projectors and shared screens. Positions never
// change, so the flip is instant and the map does not jump.
// ---------------------------------------------------------------------------
let _presentListenersAttached = false;

function nodeFontBase() {
    return getDisplayScale() > 1 ? { ...NODE_FONT_BASE, background: PRESENT_LABEL_BACKGROUND } : NODE_FONT_BASE;
}

function isPresentMode() {
    return getDisplayScale() > 1;
}

// ?present=1 / ?present=0 in the URL wins, then the viewer's last choice.
function initialPresentMode() {
    try {
        const param = new URLSearchParams(window.location.search).get('present');
        if (param === '1' || param === 'true') return true;
        if (param === '0' || param === 'false') return false;
    } catch (e) { /* no usable URL */ }
    try {
        return localStorage.getItem(PRESENT_STORAGE_KEY) === '1';
    } catch (e) {
        return false;
    }
}

// Rewrites every edge colour at the opacity the current mode uses, keeping
// the selected node's neighbourhood highlight.
function refreshEdgeOpacity() {
    if (!network || !visEdges) return;
    const keep = highlightedNodeId !== null ? new Set(network.getConnectedEdges(highlightedNodeId)) : null;
    const updates = visEdges.getIds().filter(id => !isAnchorId(id)).map(id => ({
        id,
        color: edgeColorObject(edgeColorById.get(id), keep && !keep.has(id) ? edgeDimOpacity() : edgeBaseOpacity()),
    }));
    if (updates.length) visEdges.update(updates);
}

function syncPresentButton() {
    const btn = document.getElementById('graph-present-btn');
    if (!btn) return;
    const on = isPresentMode();
    btn.setAttribute('aria-pressed', on ? 'true' : 'false');
    btn.title = on ? 'Back to desktop sizes (P)' : 'Larger labels, nodes and lines for projectors (P)';
}

function setPresentMode(on, persist = true) {
    setDisplayScale(on ? PRESENT_DISPLAY_SCALE : 1);
    document.body.classList.toggle('present', on);
    syncPresentButton();
    if (persist) {
        try {
            localStorage.setItem(PRESENT_STORAGE_KEY, on ? '1' : '0');
        } catch (e) { /* storage unavailable */ }
    }
    const status = document.getElementById('graph-present-status');
    if (status) status.textContent = on ? 'Present mode on.' : 'Present mode off.';
    // The workbench collapses its sidebar while presenting (app.js).
    window.dispatchEvent(new CustomEvent('graph-present-changed', { detail: { on } }));
    if (!network) return;
    _lastStyleKey = null;
    refreshEdgeOpacity();
    applyScaleStyle();
    network.redraw();
    // Present mode hides toolbar buttons and the sidebar, so the canvas
    // changes size; refit once the layout has reflowed.
    setTimeout(() => fitView(null, false), 100);
}

function initPresentMode() {
    // Desktop is the default state, so only an initial present mode applies.
    if (initialPresentMode()) setPresentMode(true, false);
    else syncPresentButton();
    if (_presentListenersAttached) return;
    _presentListenersAttached = true;
    const btn = document.getElementById('graph-present-btn');
    if (btn) btn.addEventListener('click', () => setPresentMode(!isPresentMode()));
    document.addEventListener('keydown', (event) => {
        if (event.key !== 'p' && event.key !== 'P') return;
        if (event.ctrlKey || event.metaKey || event.altKey) return;
        if (!graphPanelActive || isEditableTarget(event.target)) return;
        event.preventDefault();
        setPresentMode(!isPresentMode());
    });
}

// ---------------------------------------------------------------------------
// Grouped layout. The payload comes from /api/graph/groups; the pure geometry
// lives in grouping.js. A group is a hidden fixed anchor node plus hidden
// spring edges to its members, so anchors and anchor edges exist only inside
// the DataSets: every loop over a DataSet must skip them (isAnchorId).
// ---------------------------------------------------------------------------
// The mode this build lays out by: the payload default when that mode is
// available, otherwise 'none' (the free layout).
function resolveGroupMode(payload) {
    if (!payload || typeof payload !== 'object') return 'none';
    const mode = payload.default;
    if (mode !== 'cluster' && mode !== 'family') return 'none';
    const entry = payload.modes && payload.modes[mode];
    const usable = entry && entry.available === true
        && entry.assignment && typeof entry.assignment === 'object';
    return usable ? mode : 'none';
}

// Non-source node id -> group id for `mode`. Ids are read with Object.hasOwn so
// data keys cannot reach the prototype.
function buildGroupAssignment(payload, mode) {
    const assignment = new Map();
    if (mode === 'none') return assignment;
    const source = payload.modes[mode].assignment;
    for (const n of allNodes) {
        if (sourceNodeIds.has(n.id) || !Object.hasOwn(source, n.id)) continue;
        const gid = source[n.id];
        if (typeof gid === 'string') assignment.set(n.id, gid);
    }
    return assignment;
}

// Source id -> plurality group id for `mode`, read from the payload. Sources
// never join groupAssignment, so they never count toward a region.
function buildSourceGroups(payload, mode) {
    const groups = new Map();
    if (mode === 'none') return groups;
    const source = payload.modes[mode].assignment;
    for (const id of sourceNodeIds) {
        if (!Object.hasOwn(source, id)) continue;
        const gid = source[id];
        if (typeof gid === 'string') groups.set(id, gid);
    }
    return groups;
}

// Switches the module's grouping state to `mode`: assignment, source groups and
// the circle each group is packed into.
function applyGroupMode(mode) {
    groupMode = mode;
    groupAssignment = buildGroupAssignment(groupsPayload, mode);
    sourceGroup = buildSourceGroups(groupsPayload, mode);
    groupLayout = new Map();
    if (mode !== 'none') {
        const counts = new Map();
        for (const gid of groupAssignment.values()) counts.set(gid, (counts.get(gid) || 0) + 1);
        groupLayout = packGroups([...counts].map(([id, size]) => ({ id, size })));
    }
}

// Ids of the data nodes currently drawn (anchors and hidden nodes excluded).
function visibleDataNodeIds() {
    if (!visNodes) return [];
    return visNodes.get({ filter: n => !n._anchor && n.hidden !== true }).map(n => n.id);
}

// Fit the view to `ids` (default: every drawn data node) and leave FIT_MARGIN
// of breathing room. Animated fits apply the margin once the animation ends.
function fitView(ids, animation = false) {
    if (!network || !visNodes) return;
    const fitIds = ids || visibleDataNodeIds();
    if (fitIds.length === 0) return;
    if (_fitShrink) {
        network.off('animationFinished', _fitShrink);
        _fitShrink = null;
    }
    const cover = sidebarCoverPx();
    if (cover > 0) {
        fitBesideSidebar(fitIds, cover, animation);
        return;
    }
    network.fit({ nodes: fitIds, animation });
    const shrink = () => {
        network.moveTo({ scale: network.getScale() * (1 - FIT_MARGIN), animation: false });
    };
    if (animation === false) {
        shrink();
        applyScaleStyle();
    } else {
        _fitShrink = () => {
            _fitShrink = null;
            shrink();
        };
        network.once('animationFinished', _fitShrink);
    }
}

// Width in px of the part of the canvas the open detail sidebar covers.
function sidebarCoverPx() {
    const sb = document.getElementById('graph-detail-sidebar');
    if (!sb || !sb.classList || sb.classList.contains('graph-detail-sidebar--closed')) return 0;
    return sb.offsetWidth || SIDEBAR_FALLBACK_PX;
}

// Fits `ids` into the canvas area the sidebar leaves uncovered.
function fitBesideSidebar(ids, cover, animation) {
    const container = document.getElementById('graph-container');
    const cw = (container && container.clientWidth) || 0;
    const ch = (container && container.clientHeight) || 0;
    const positions = network.getPositions(ids);
    let minX = Infinity; let maxX = -Infinity; let minY = Infinity; let maxY = -Infinity;
    for (const id of ids) {
        const p = positions[id];
        if (!p) continue;
        minX = Math.min(minX, p.x); maxX = Math.max(maxX, p.x);
        minY = Math.min(minY, p.y); maxY = Math.max(maxY, p.y);
    }
    const availW = cw - cover;
    if (!Number.isFinite(minX) || availW <= 2 * FIT_EDGE_PAD_PX || ch <= 2 * FIT_EDGE_PAD_PX) {
        network.fit({ nodes: ids, animation });
        return;
    }
    const spanX = Math.max(maxX - minX, 1);
    const spanY = Math.max(maxY - minY, 1);
    const scale = Math.min(
        Math.min((availW - 2 * FIT_EDGE_PAD_PX) / spanX, (ch - 2 * FIT_EDGE_PAD_PX) / spanY) * (1 - FIT_MARGIN),
        FIT_MAX_SCALE,
    );
    // The view position is the world point at the canvas centre; centring the
    // nodes in the uncovered area means looking cover / 2 px to the right of them.
    const position = { x: (minX + maxX) / 2 + cover / 2 / scale, y: (minY + maxY) / 2 };
    network.moveTo({ position, scale, animation });
    if (animation === false) {
        applyScaleStyle();
    } else {
        _fitShrink = () => {
            _fitShrink = null;
            applyScaleStyle();
        };
        network.once('animationFinished', _fitShrink);
    }
}

// ---------------------------------------------------------------------------
// Group regions (canvas) and the Groups list (DOM twin). Regions are drawn
// from vis beforeDrawing/afterDrawing and write nothing to the DataSets.
// ---------------------------------------------------------------------------
function currentGroups() {
    if (groupMode === 'none' || !groupsPayload) return [];
    const entry = groupsPayload.modes && groupsPayload.modes[groupMode];
    return entry && Array.isArray(entry.groups) ? entry.groups : [];
}

// Group id -> ids of its currently drawn data nodes.
function visibleMembersByGroup() {
    const byGroup = new Map();
    if (!visNodes) return byGroup;
    for (const [id, gid] of groupAssignment) {
        const rec = visNodes.get(id);
        if (!rec || rec.hidden === true) continue;
        if (!byGroup.has(gid)) byGroup.set(gid, []);
        byGroup.get(gid).push(id);
    }
    return byGroup;
}

function currentRegions() {
    // A focus view lays out only its own neighbourhood; group regions are not drawn then.
    if (groupMode === 'none' || focusStack.length > 0 || !network || !visNodes) return [];
    const ids = [];
    for (const list of visibleMembersByGroup().values()) ids.push(...list);
    const positions = network.getPositions(ids) || {};
    return regionGeometry(currentGroups(), positions, new Set(ids), groupAssignment);
}

function regionBodyFont() {
    if (_regionFont === null) {
        const style = window.getComputedStyle ? window.getComputedStyle(document.body) : null;
        _regionFont = (style && style.fontFamily) || 'sans-serif';
    }
    return _regionFont;
}

function pillPath(ctx, box, radius) {
    const { x, y, w, h } = box;
    ctx.beginPath();
    ctx.moveTo(x + radius, y);
    ctx.arcTo(x + w, y, x + w, y + h, radius);
    ctx.arcTo(x + w, y + h, x, y + h, radius);
    ctx.arcTo(x, y + h, x, y, radius);
    ctx.arcTo(x, y, x + w, y, radius);
    ctx.closePath();
}

// Zoom scale for converting the region px constants to world units. Dividing
// by the display factor grows rings and pills with present mode; it is used
// only for those sizes, never for positions.
function regionPxScale() {
    return (network.getScale() || 1) / getDisplayScale();
}

function drawRegionCircles(ctx) {
    _frameRegions = currentRegions();
    if (_frameRegions.length === 0) return;
    const scale = regionPxScale();
    const emphasized = emphasizedRegionId !== null ? emphasizedRegionId : activeRegionId;
    ctx.save();
    for (const region of _frameRegions) {
        const isEmph = region.id === emphasized;
        ctx.beginPath();
        ctx.arc(region.cx, region.cy, region.r, 0, 2 * Math.PI);
        ctx.fillStyle = isEmph ? REGION_COLORS.fillEmph : region.other ? REGION_COLORS.fillOther : REGION_COLORS.fill;
        ctx.fill();
        ctx.lineWidth = (isEmph ? REGION_STROKE_EMPH_PX : REGION_STROKE_PX) / scale;
        ctx.strokeStyle = isEmph ? REGION_COLORS.strokeEmph : REGION_COLORS.stroke;
        ctx.setLineDash(region.other && !isEmph ? REGION_DASH_PX.map(d => d / scale) : []);
        ctx.stroke();
    }
    ctx.restore();
}

function drawRegionLabels(ctx) {
    const regions = _frameRegions || currentRegions();
    _frameRegions = null;
    _lastPlaced = [];
    if (regions.length === 0) return;
    const scale = regionPxScale();
    const container = document.getElementById('graph-container');
    const width = (container && container.clientWidth) || 0;
    const height = (container && container.clientHeight) || 0;
    const topLeft = network.DOMtoCanvas({ x: 0, y: 0 });
    const bottomRight = network.DOMtoCanvas({ x: width, y: height });
    const viewRect = { left: topLeft.x, top: topLeft.y, right: bottomRight.x, bottom: bottomRight.y };
    ctx.save();
    ctx.font = `600 ${REGION_LABEL_PX / scale}px ${regionBodyFont()}`;
    const emphasized = emphasizedRegionId !== null ? emphasizedRegionId : activeRegionId;
    _lastPlaced = placeRegionLabels(regions, text => ctx.measureText(text).width, scale, emphasized, viewRect);
    const pad = REGION_PILL_PAD_PX / scale;
    ctx.textBaseline = 'middle';
    ctx.textAlign = 'left';
    for (const box of _lastPlaced) {
        pillPath(ctx, box, REGION_PILL_RADIUS_PX / scale);
        ctx.fillStyle = REGION_COLORS.pillFill;
        ctx.fill();
        ctx.lineWidth = REGION_STROKE_PX / scale;
        ctx.strokeStyle = REGION_COLORS.pillStroke;
        ctx.setLineDash([]);
        ctx.stroke();
        ctx.fillStyle = REGION_COLORS.ink;
        ctx.fillText(box.label, box.x + pad, box.y + box.h / 2);
    }
    ctx.restore();
}

function announceGroup(text) {
    const status = document.getElementById('graph-group-status');
    if (status) status.textContent = text;
}

function syncGroupRows() {
    for (const [gid, row] of groupRowEls) {
        if (gid === activeRegionId) row.setAttribute('aria-current', 'true');
        else row.removeAttribute('aria-current');
    }
}

// Clears the zoomed-to group (second row click, Fit View, Esc).
function clearActiveRegion() {
    if (activeRegionId === null) return;
    activeRegionId = null;
    syncGroupRows();
    if (network) network.redraw();
}

function setEmphasizedRegion(gid) {
    if (emphasizedRegionId === gid) return;
    emphasizedRegionId = gid;
    if (network) network.redraw();
}

function toggleActiveRegion(group, visibleIds) {
    if (visibleIds.length === 0) return;
    if (activeRegionId === group.id) {
        clearActiveRegion();
        return;
    }
    activeRegionId = group.id;
    syncGroupRows();
    fitView(visibleIds, fitAnimation(250));
    announceGroup(`Zoomed to ${group.full_label}: ${visibleIds.length.toLocaleString()} nodes.`);
    if (network) network.redraw();
}

// Rebuilds the Groups button and list from the current build and filters.
function renderGroupsList() {
    const btn = document.getElementById('graph-groups-btn');
    const panel = document.getElementById('graph-groups');
    if (!btn || !panel) return;
    groupRowEls = new Map();
    const groups = currentGroups();
    const label = document.createTextNode('Groups ');
    const count = document.createElement('span');
    count.className = 'count';
    count.textContent = String(groups.length);
    btn.replaceChildren(label, count);
    if (groupMode === 'none' || groups.length === 0) {
        activeRegionId = null;
        emphasizedRegionId = null;
        btn.setAttribute('disabled', '');
        btn.setAttribute('title', GROUPS_DISABLED_TITLE);
        btn.setAttribute('aria-expanded', 'false');
        panel.setAttribute('hidden', '');
        panel.replaceChildren();
        return;
    }
    btn.removeAttribute('disabled');
    btn.removeAttribute('title');
    const visible = visibleMembersByGroup();
    const totals = new Map();
    for (const gid of groupAssignment.values()) totals.set(gid, (totals.get(gid) || 0) + 1);
    const list = document.createElement('ul');
    list.setAttribute('role', 'list');
    for (const group of groups.slice(0, GROUP_LIST_MAX_ROWS)) {
        const ids = visible.get(group.id) || [];
        const total = totals.get(group.id) || 0;
        const item = document.createElement('li');
        const row = document.createElement('button');
        row.setAttribute('type', 'button');
        row.className = 'graph-group-row';
        row.setAttribute('data-group', group.id);
        row.setAttribute('title', ids.length < total
            ? `${group.full_label} (${ids.length.toLocaleString()} of ${total.toLocaleString()} shown)`
            : group.full_label);
        if (ids.length === 0) row.setAttribute('aria-disabled', 'true');
        const marker = document.createElement('span');
        marker.className = group.id === 'other'
            ? 'graph-group-row__marker graph-group-row__marker--other'
            : 'graph-group-row__marker';
        const name = document.createElement('span');
        name.className = 'graph-group-row__label';
        name.textContent = group.label;
        const num = document.createElement('span');
        num.className = 'graph-group-row__count';
        num.textContent = ids.length.toLocaleString();
        row.append(marker, name, num);
        row.addEventListener('mouseenter', () => setEmphasizedRegion(group.id));
        row.addEventListener('focus', () => setEmphasizedRegion(group.id));
        row.addEventListener('mouseleave', () => setEmphasizedRegion(null));
        row.addEventListener('blur', () => setEmphasizedRegion(null));
        row.addEventListener('click', () => toggleActiveRegion(group, visibleMembersByGroup().get(group.id) || []));
        item.appendChild(row);
        list.appendChild(item);
        groupRowEls.set(group.id, row);
    }
    if (groups.length > GROUP_LIST_MAX_ROWS) {
        const more = document.createElement('li');
        more.className = 'graph-groups__more';
        more.textContent = `+${(groups.length - GROUP_LIST_MAX_ROWS).toLocaleString()} more groups`;
        list.appendChild(more);
    }
    panel.replaceChildren(list);
    const open = btn.getAttribute('aria-expanded') === 'true';
    btn.setAttribute('aria-expanded', String(open));
    if (open) panel.removeAttribute('hidden');
    else panel.setAttribute('hidden', '');
    syncGroupRows();
}

// ---------------------------------------------------------------------------
// Group by control and relayout. Switching modes removes the old anchors, adds
// the new ones, reseeds the members and stabilizes once; None restores the
// cached free layout. A layout token discards completions that belong to an
// abandoned relayout, and a timer rolls back one that never finishes.
// ---------------------------------------------------------------------------
function trimPeriod(text) {
    return String(text).replace(/\.\s*$/, '');
}

// Whether `mode` can be selected and the reason when it cannot. None always
// can. Reasons come from the payload and are only ever written as text.
function groupModeState(mode) {
    if (mode === 'none') return { enabled: true, reason: '' };
    if (!groupsPayload || typeof groupsPayload !== 'object') {
        return { enabled: false, reason: callbacks.groupLoadFailure || GROUP_LOAD_FAILURE };
    }
    const entry = groupsPayload.modes && groupsPayload.modes[mode];
    const usable = entry && entry.available === true
        && entry.assignment && typeof entry.assignment === 'object';
    if (usable) return { enabled: true, reason: '' };
    const reason = entry && typeof entry.reason === 'string' && entry.reason
        ? entry.reason
        : 'Not available for this project';
    return { enabled: false, reason };
}

function enabledGroupModes() {
    return GROUP_MODE_ORDER.filter(mode => groupModeState(mode).enabled);
}

function groupControlButtons() {
    const group = document.getElementById('graph-group');
    return group ? [...group.querySelectorAll('[data-mode]')] : [];
}

// The hint slot shows the transient text (arranging / failure) when there is
// one, otherwise one sentence per unavailable mode.
function renderGroupHint() {
    const hint = document.getElementById('graph-group-hint');
    if (!hint) return;
    if (_hintOverride !== null) {
        hint.textContent = _hintOverride;
        return;
    }
    const parts = [];
    for (const mode of GROUP_MODE_ORDER) {
        const state = groupModeState(mode);
        if (!state.enabled) parts.push(`${GROUP_MODE_LABELS[mode]}: ${trimPeriod(state.reason)}.`);
    }
    hint.textContent = parts.join(' ');
}

// Mirrors availability and the selection onto the radio buttons.
function syncGroupControl(selected = groupMode) {
    for (const btn of groupControlButtons()) {
        const mode = btn.getAttribute('data-mode');
        if (!GROUP_MODE_ORDER.includes(mode)) continue;
        const state = groupModeState(mode);
        const checked = state.enabled && mode === selected;
        btn.setAttribute('aria-checked', String(checked));
        btn.setAttribute('tabindex', checked ? '0' : '-1');
        if (state.enabled && !_initialSettled) {
            // CR-01: the initial layout is still stabilizing; a relayout now
            // would cut it short, so every option waits for it.
            btn.setAttribute('aria-disabled', 'true');
            btn.setAttribute('title', GROUP_SETTLING_TITLE);
        } else if (state.enabled) {
            btn.removeAttribute('aria-disabled');
            btn.setAttribute('title', GROUP_MODE_TITLES[mode]);
        } else {
            btn.setAttribute('aria-disabled', 'true');
            btn.setAttribute('title', state.reason);
        }
    }
    renderGroupHint();
}

function setGroupBusy(on) {
    relayoutBusy = on;
    // A graph-show-types request held back by a running relayout is applied as
    // soon as the layout that is finishing has run its follow-ups.
    if (!on && pendingShowTypes !== null) queueMicrotask(flushPendingShowTypes);
    const group = document.getElementById('graph-group');
    const container = document.getElementById('graph-container');
    for (const el of [group, container]) {
        if (!el) continue;
        if (on) el.setAttribute('aria-busy', 'true');
        else el.removeAttribute('aria-busy');
    }
    if (group) group.classList.toggle('graph-group--busy', on);
}

function setHintOverride(text, clearAfterMs = 0) {
    if (_hintTimer) {
        clearTimeout(_hintTimer);
        _hintTimer = null;
    }
    _hintOverride = text;
    renderGroupHint();
    if (text !== null && clearAfterMs > 0) {
        _hintTimer = setTimeout(() => {
            _hintTimer = null;
            _hintOverride = null;
            renderGroupHint();
        }, clearAfterMs);
    }
}

// Forgets any relayout in flight (rebuild or domain switch). Pending
// completions see a new token and do nothing.
function resetRelayoutState() {
    layoutToken += 1;
    if (_relayoutTimer) {
        clearTimeout(_relayoutTimer);
        _relayoutTimer = null;
    }
    relayoutPrev = null;
    setGroupBusy(false);
    setHintOverride(null);
}

// Runs `fn` after `count` animation frames (timers when frames are unavailable).
function afterFrames(count, fn) {
    if (count <= 0) {
        fn();
        return;
    }
    const next = () => afterFrames(count - 1, fn);
    if (typeof requestAnimationFrame === 'function') requestAnimationFrame(next);
    else setTimeout(next, 16);
}

// WR-02: every position write is one batched DataSet update (per-node
// network.moveNode costs a full synchronous redraw each while physics is off).
// vis parses DataSet x/y with parseInt, so coordinates are rounded here and
// layouts are snapped to integers once they settle (snapLayout); captured
// positions are rounded the same way, so a restore puts nodes back exactly.
function writePositions(entries) {
    const updates = [];
    for (const [id, p] of entries) {
        if (!p || !visNodes.get(id)) continue;
        updates.push({ id, x: Math.round(p.x), y: Math.round(p.y) });
    }
    if (updates.length > 0) visNodes.update(updates);
    return updates.length;
}

// Rounds every data node of a settled layout to integer coordinates (one write).
function snapLayout() {
    const ids = visNodes.getIds().filter(id => !isAnchorId(id));
    const positions = network.getPositions(ids) || {};
    const off = [];
    for (const id of ids) {
        const p = positions[id];
        if (p && (!Number.isInteger(p.x) || !Number.isInteger(p.y))) off.push([id, p]);
    }
    writePositions(off);
}

function captureDataPositions() {
    const ids = visNodes.getIds().filter(id => !isAnchorId(id));
    const positions = network.getPositions(ids);
    return new Map(ids.filter(id => positions[id])
        .map(id => [id, { x: Math.round(positions[id].x), y: Math.round(positions[id].y) }]));
}

// Geometry of the region circles as drawn (visible members); a focus view,
// which draws none, uses every member.
function separationRegions() {
    if (groupMode === 'none' || !network || !visNodes) return [];
    if (focusStack.length === 0) return currentRegions();
    const all = [...groupAssignment.keys()].filter(id => visNodes.get(id));
    return regionGeometry(currentGroups(), network.getPositions(all) || {}, new Set(all), groupAssignment);
}

// After a force layout, moves whole groups apart until no two drawn region
// circles are closer than REGION_GAP_SCREEN_PX on screen. Members keep their
// relative positions, so every radius is unchanged. The margin in world units
// depends on the fit scale, which depends on the spread, so the separation is
// iterated on the circles alone (cheap) until the estimated margin holds, and
// the nodes are moved once at the end.
function separateGroupRegionsForView() {
    const regions = separationRegions();
    if (regions.length < 2) return;
    const container = document.getElementById('graph-container');
    const cw = ((container && container.clientWidth) || 0) - sidebarCoverPx();
    const ch = (container && container.clientHeight) || 0;
    const moved = regions.map(r => ({ ...r }));
    const total = new Map(regions.map(r => [r.id, { dx: 0, dy: 0 }]));
    let gap = REGION_SEPARATION_GAP;
    for (let pass = 0; pass < REGION_GAP_PASSES; pass++) {
        const offsets = separateRegions(moved, gap);
        for (const r of moved) {
            const off = offsets.get(r.id);
            r.cx += off.dx;
            r.cy += off.dy;
            total.get(r.id).dx += off.dx;
            total.get(r.id).dy += off.dy;
        }
        const spanX = Math.max(...moved.map(r => r.cx + r.r)) - Math.min(...moved.map(r => r.cx - r.r));
        const spanY = Math.max(...moved.map(r => r.cy + r.r)) - Math.min(...moved.map(r => r.cy - r.r));
        const scale = cw > 0 && ch > 0 && spanX > 0 && spanY > 0
            ? Math.min((cw - 2 * FIT_EDGE_PAD_PX) / spanX, (ch - 2 * FIT_EDGE_PAD_PX) / spanY, FIT_MAX_SCALE) * (1 - FIT_MARGIN)
            : 1;
        const needed = REGION_GAP_SCREEN_PX / Math.max(scale, 1e-6);
        if (needed <= gap * 1.02) break;
        gap = needed;
    }
    const byGroup = new Map();
    for (const [id, gid] of groupAssignment) {
        if (!byGroup.has(gid)) byGroup.set(gid, []);
        byGroup.get(gid).push(id);
    }
    // One batched DataSet write; per-node network.moveNode calls were far slower on large graphs.
    const moves = [];
    for (const [gid, off] of total) {
        if (Math.abs(off.dx) < 1e-6 && Math.abs(off.dy) < 1e-6) continue;
        const ids = (byGroup.get(gid) || []).filter(id => visNodes.get(id));
        const positions = network.getPositions(ids);
        for (const id of ids) {
            const p = positions[id];
            if (p) moves.push([id, { x: p.x + off.dx, y: p.y + off.dy }]);
        }
    }
    writePositions(moves);
}

function removeAnchors() {
    const edgeIds = visEdges.getIds().filter(isAnchorId);
    if (edgeIds.length) visEdges.remove(edgeIds);
    const nodeIds = visNodes.getIds().filter(isAnchorId);
    if (nodeIds.length) visNodes.remove(nodeIds);
}

// Adds the anchors and rest lengths for the current grouping state (rest
// lengths go back to the plain spring length when ungrouped).
function installAnchors() {
    removeAnchors();
    const records = visEdges.get({ filter: e => !e._anchor });
    const lengths = new Map(groupMode === 'none'
        ? []
        : dataEdgeLengths(records, groupAssignment, groupLayout).map(l => [l.id, l.length]));
    visEdges.update(records.map(e => ({ id: e.id, length: lengths.get(e.id) ?? FA2_SPRING_LENGTH })));
    if (groupMode === 'none') return;
    visNodes.add(anchorNodeSpecs(groupLayout));
    visEdges.add(anchorEdgeSpecs(groupAssignment, groupLayout));
}

function reseedMembers() {
    const seeds = [];
    for (const [id, gid] of groupAssignment) {
        const circle = groupLayout.get(gid);
        if (!circle || pinnedNodes.has(id)) continue;
        seeds.push([id, seedInside(circle, id)]);
    }
    writePositions(seeds);
}

function restoreFreeLayout() {
    writePositions([...freeLayoutPositions].filter(([id]) => !pinnedNodes.has(id)));
}

function groupCountText(mode) {
    if (mode === 'none') return 'Grouping off.';
    const sizes = new Map();
    for (const gid of groupAssignment.values()) sizes.set(gid, (sizes.get(gid) || 0) + 1);
    const n = [...sizes.values()].filter(size => size >= 2).length;
    const label = mode === 'cluster' ? 'topic cluster' : 'entity family';
    return `Grouped by ${label}: ${n} ${n === 1 ? 'group' : 'groups'}.`;
}

// Common ending of a successful relayout, also used by the instant None restore.
function completeRelayout(mode) {
    if (_relayoutTimer) {
        clearTimeout(_relayoutTimer);
        _relayoutTimer = null;
    }
    network.setOptions({ physics: false });
    // The layout is final from here on; the follow-ups below (focus layout,
    // source placement) are held while a layout is in flight, so release first.
    setGroupBusy(false);
    separateGroupRegionsForView();
    snapLayout();
    if (mode === 'none' && !freeLayoutPositions) freeLayoutPositions = captureDataPositions();
    // The positions a focus view would restore are stale after a relayout.
    focusPre = null;
    _focusLayoutKey = null;
    sourcesPlaced = false;
    if (sourcesActive()) placeSources();
    syncSourcePhysics();
    syncFocusLayout();
    fitView(null, false);
    applyScaleStyle();
    relayoutPrev = null;
    renderGroupsList();
    setHintOverride(null);
    syncGroupControl();
    announceGroup(groupCountText(mode));
}

// Puts the previous grouping, anchors and positions back and says so.
function failRelayout(token) {
    if (token !== layoutToken || !relayoutPrev) return;
    layoutToken += 1;
    if (_relayoutTimer) {
        clearTimeout(_relayoutTimer);
        _relayoutTimer = null;
    }
    const prev = relayoutPrev;
    relayoutPrev = null;
    try {
        if (typeof network.stopSimulation === 'function') network.stopSimulation();
        network.setOptions({ physics: false });
        // Physics is off: the deferred follow-ups (sources) may run again.
        setGroupBusy(false);
        groupMode = prev.mode;
        groupAssignment = prev.assignment;
        sourceGroup = prev.sourceGroup;
        groupLayout = prev.layout;
        installAnchors();
        writePositions(prev.positions);
        if (sourcesActive()) placeSources();
        syncSourcePhysics();
        fitView(null, false);
        applyScaleStyle();
        renderGroupsList();
    } catch (e) {
        console.warn('Could not restore the previous layout:', e);
    }
    setGroupBusy(false);
    const failMs = window._relayoutFailMessageMs ?? RELAYOUT_FAIL_MESSAGE_MS;
    setHintOverride(RELAYOUT_FAIL_TEXT, failMs);
    syncGroupControl();
    announceGroup(RELAYOUT_FAIL_TEXT);
}

// Stabilizes the new layout and completes when vis reports the iteration
// budget spent. Only `stabilizationIterationsDone` is used: it always arrives
// after an explicit stabilize(), unlike `stabilized`.
function runRelayoutStabilization(mode, iterations, token) {
    const finish = () => {
        network.off('stabilizationIterationsDone', finish);
        if (token !== layoutToken) return;
        try {
            completeRelayout(mode);
        } catch (e) {
            console.warn('Relayout failed:', e);
            failRelayout(token);
        }
    };
    network.once('stabilizationIterationsDone', finish);
    network.setOptions({ physics: { enabled: true, stabilization: { fit: false } } });
    network.stabilize(iterations);
}

function startRelayout(mode, token) {
    // Sources and their edges stay out of the force simulation while it runs.
    syncSourcePhysics(true, false);
    clearActiveRegion();
    setEmphasizedRegion(null);
    removeAnchors();
    applyGroupMode(mode);
    if (mode === 'none') {
        installAnchors();
        runRelayoutStabilization(mode, PHYSICS_STABILIZATION_ITERATIONS, token);
        return;
    }
    reseedMembers();
    installAnchors();
    const knowledgeCount = allNodes.length - sourceNodeIds.size;
    runRelayoutStabilization(mode, groupIterations(knowledgeCount), token);
}

// window._relayoutTimeoutMs overrides the scaled budget (tests, debugging).
function relayoutTimeoutMs() {
    return window._relayoutTimeoutMs ?? relayoutTimeoutFor(allNodes.length);
}

function captureLayoutState() {
    return {
        mode: groupMode,
        assignment: groupAssignment,
        sourceGroup,
        layout: groupLayout,
        positions: captureDataPositions(),
    };
}

function relayout(mode) {
    // CR-01: never restart stabilize() underneath the initial layout.
    if (!_initialSettled || relayoutBusy || !network || !visNodes || !visEdges) return;
    if (!GROUP_MODE_ORDER.includes(mode) || mode === groupMode) return;
    if (!groupModeState(mode).enabled) return;
    const token = layoutToken += 1;
    relayoutPrev = captureLayoutState();

    // None with a cached free layout is instant: no physics, no busy state.
    if (mode === 'none' && freeLayoutPositions) {
        try {
            clearActiveRegion();
            setEmphasizedRegion(null);
            removeAnchors();
            applyGroupMode('none');
            installAnchors();
            restoreFreeLayout();
            completeRelayout('none');
        } catch (e) {
            console.warn('Relayout failed:', e);
            failRelayout(token);
        }
        return;
    }

    setGroupBusy(true);
    setHintOverride(RELAYOUT_BUSY_TEXT);
    syncGroupControl(mode);
    _relayoutTimer = setTimeout(() => failRelayout(token), relayoutTimeoutMs());
    // Two frames let the arranging text paint before stabilization blocks.
    afterFrames(2, () => {
        if (token !== layoutToken) return;
        try {
            startRelayout(mode, token);
        } catch (e) {
            console.warn('Relayout failed:', e);
            failRelayout(token);
        }
    });
}

// Click and keyboard handling for the Group by radiogroup (attached once).
function attachGroupControl() {
    if (_groupControlAttached) return;
    const buttons = groupControlButtons();
    if (buttons.length === 0) return;
    _groupControlAttached = true;
    for (const btn of buttons) {
        const mode = btn.getAttribute('data-mode');
        if (!GROUP_MODE_ORDER.includes(mode)) continue;
        btn.addEventListener('click', () => relayout(mode));
        btn.addEventListener('keydown', (event) => {
            const target = radioTarget(event.key, enabledGroupModes(), mode);
            if (target === undefined) return;
            event.preventDefault();
            if (relayoutBusy || !target) return;
            const targetBtn = buttons.find(b => b.getAttribute('data-mode') === target);
            if (targetBtn && typeof targetBtn.focus === 'function') targetBtn.focus();
            relayout(target);
        });
    }
}

function buildGraph() {
    const container = document.getElementById('graph-container');
    if (!container || !window.vis) return;

    // WR-03: destroy previous network instance before creating a new one to
    // prevent canvas context leaks and competing requestAnimationFrame loops.
    if (network) {
        // 260802-cu1: clear pending label-controller state before destroying
        // the network — otherwise a timer scheduled against the outgoing
        // network fires after the rebuild and writes a stale cutoff into the
        // freshly built DataSet.
        if (_labelUpdateTimer) {
            clearTimeout(_labelUpdateTimer);
            _labelUpdateTimer = null;
        }
        _lastStyleKey = null;
        _lastCutoff = 0;
        _fitShrink = null;
        cancelFocus();
        highlightedNodeId = null;
        hoverFocus = new Set();
        selectFocus = new Set();
        hoverCenterId = null;
        selectCenterId = null;
        focusNodeIds = new Set();
        focusEdgeIds = new Set();
        hoveredEdgeId = null;
        cancelHover();
        pinnedCardNodeId = null;
        hideCard();
        sourcesShown = false;
        sourcesPlaced = false;
        for (const type of sourceTypes()) activeTypes.delete(type);
        resetRelayoutState();
        network.destroy();
        network = null;
    }

    freeLayoutPositions = null;
    resetFocusState();

    // WR-04: Close sidebar before rebuilding so stale content is not shown
    // alongside newly rebuilt graph data.
    hideSidebar();

    // Clear placeholder
    container.innerHTML = '';

    // Pre-compute node degree (total incoming + outgoing edges) for visual sizing.
    // Range: 8px (isolated node) to 24px (highest-degree hub). See UI-SPEC Degree-Based Node Sizing.
    degreeMap = {};
    allEdges.forEach(e => {
        degreeMap[e.source] = (degreeMap[e.source] || 0) + 1;
        degreeMap[e.target] = (degreeMap[e.target] || 0) + 1;
    });

    nodeById = new Map(allNodes.map(n => [n.id, n]));
    adjacency = new Map();
    for (const e of allEdges) {
        for (const id of new Set([e.source, e.target])) {
            if (!adjacency.has(id)) adjacency.set(id, []);
            adjacency.get(id).push(e);
        }
    }

    // Sources-family nodes. Without display data the type filter is off, so
    // fall back to the pipeline's own DOCUMENT/PUBLICATION types.
    sourceNodeIds = new Set(allNodes
        .filter(n => (typeFilterEnabled
            ? isSourceType(n.entity_type)
            : FALLBACK_SOURCE_TYPES.has(n.entity_type)))
        .map(n => n.id));

    sourceNeighbours = new Map();
    for (const e of allEdges) {
        const sourceEnd = sourceNodeIds.has(e.source);
        const otherEnd = sourceNodeIds.has(e.target);
        if (sourceEnd === otherEnd) continue;
        const [src, nb] = sourceEnd ? [e.source, e.target] : [e.target, e.source];
        if (!sourceNeighbours.has(src)) sourceNeighbours.set(src, new Set());
        sourceNeighbours.get(src).add(nb);
    }

    // linkDegree: edges without a Sources endpoint. Size, label budget and the
    // min-degree slider use it; the sidebar Degree row keeps the total.
    linkDegreeMap = linkDegrees(allEdges, isSourceEdgeRecord);
    maxDegree = Object.values(linkDegreeMap).reduce((acc, v) => Math.max(acc, v), 1);

    // 260802-cu1: descending degree list backing the label budget in
    // applyScaleStyle(). Built over allNodes, not degreeMap — degreeMap
    // omits isolated (degree-0) nodes, so indexing a budget into it would
    // silently overshoot on graphs with unconnected entities.
    sortedDegrees = allNodes
        .filter(n => !sourceNodeIds.has(n.id))
        .map(n => linkDegreeMap[n.id] || 0)
        .sort((a, b) => b - a);

    // Grouped layout (default topic cluster): members start inside their
    // group's circle; anchors and anchor edges are added to the DataSets below.
    applyGroupMode(resolveGroupMode(groupsPayload));
    if (groupAssignment.size === 0) applyGroupMode('none');

    const nodes = allNodes.map(n => {
        const d = typeDisplay(n.entity_type);
        const isSource = sourceNodeIds.has(n.id);
        return {
            id: n.id,
            label: truncateLabel(n.name || n.id),
            color: nodeColor(n.entity_type),
            borderWidth: 1,
            borderWidthSelected: 3,
            shape: d.shape,
            hidden: isNodeHiddenAtBuild(n),
            // Hidden sources stay out of the force layout; placeSources()
            // positions them when they are first revealed.
            physics: !isSource || sourcesShown,
            size: nodeSize(linkDegreeMap[n.id] || 0, maxDegree, 1, isSource),
            font: { ...nodeFontBase(), size: isSource ? LABEL_HIDDEN_FONT_SIZE : LABEL_BASE_WORLD },
            _data: n,
        };
    });
    if (groupMode !== 'none') {
        for (const node of nodes) {
            const gid = groupAssignment.get(node.id);
            if (gid === undefined || pinnedNodes.has(node.id)) continue;
            const seed = seedInside(groupLayout.get(gid), node.id);
            node.x = seed.x;
            node.y = seed.y;
        }
        nodes.push(...anchorNodeSpecs(groupLayout));
    }

    // Edges carry their relation name as the label string but rest at font
    // size 0 (nothing drawn); applyFocus() raises the size for edges of the
    // hovered/selected node or a hovered edge.
    edgeIdByIndex = stableEdgeIds(allEdges);
    edgeColorById = new Map(allEdges.map((e, i) => [
        edgeIdByIndex[i], relationDisplay(e.relation_type).color,
    ]));
    const edges = allEdges.map((e, i) => ({
        id: edgeIdByIndex[i],
        width: edgeWidth(e.support_count, 1),
        color: edgeColorObject(edgeColorById.get(edgeIdByIndex[i]), edgeBaseOpacity()),
        dashes: edgeDashes(e.epistemic_status, 1),
        label: humanizeRelation(e.relation_type),
        font: edgeLabelFont(1, false),
        from: e.source,
        to: e.target,
        arrows: 'to',
        hidden: !sourcesShown && isSourceRelation(e.relation_type),
        physics: sourcesShown || !isSourceEdgeRecord(e),
        _data: e,
    }));
    sourcePhysicsOn = sourcesShown;
    if (groupMode !== 'none') {
        // Short rest length inside a group, the distance between the two
        // group circles across groups; then the hidden member-to-anchor edges.
        const lengths = new Map(dataEdgeLengths(edges, groupAssignment, groupLayout)
            .map(l => [l.id, l.length]));
        for (const edge of edges) {
            if (lengths.has(edge.id)) edge.length = lengths.get(edge.id);
        }
        edges.push(...anchorEdgeSpecs(groupAssignment, groupLayout));
    }

    visNodes = new vis.DataSet(nodes);
    visEdges = new vis.DataSet(edges);

    // 260802-cu1: curved edges are configured once globally (below) instead
    // of per-edge, gated on edge count — above EDGE_SMOOTH_MAX_EDGES the
    // curve computation is both visual mud and a real per-frame render cost,
    // so straight edges read better at scale. Per-edge settings override the
    // global, so the per-edge `smooth` property must stay removed above.
    const edgeSmoothing = allEdges.length > EDGE_SMOOTH_MAX_EDGES ? false : { type: 'continuous' };

    const knowledgeCount = allNodes.length - sourceNodeIds.size;
    const options = {
        physics: {
            solver: 'forceAtlas2Based',
            forceAtlas2Based: {
                gravitationalConstant: FA2_GRAVITATIONAL_CONSTANT,
                centralGravity: FA2_CENTRAL_GRAVITY,
                springLength: FA2_SPRING_LENGTH,
                springConstant: FA2_SPRING_CONSTANT,
                damping: FA2_DAMPING,
                avoidOverlap: FA2_AVOID_OVERLAP,
            },
            // 260802-cu1: raising stabilization iterations lengthens the blank
            // period between container.innerHTML = '' (above) and the first
            // settled frame. Deliberately NOT re-appending a status element —
            // .graph-placeholder is normal-flow and .graph-container is a flex
            // child, so a <p> sibling of the vis canvas would trigger a canvas
            // resize (the v1.2 architecture constraint this avoids), and it is
            // also outside this task's one-file scope. updateInterval gives vis
            // a progress cadence during settling; if the wait feels too long,
            // lower PHYSICS_STABILIZATION_ITERATIONS — one line, at the top.
            stabilization: {
                enabled: true,
                iterations: groupMode === 'none'
                    ? PHYSICS_STABILIZATION_ITERATIONS
                    : groupIterations(knowledgeCount),
                updateInterval: PHYSICS_STABILIZATION_UPDATE_INTERVAL,
                fit: groupMode === 'none', // grouped builds fit the drawn nodes in settle() instead
            },
            minVelocity: 0.75, // reach the stabilized event promptly once motion drops below this threshold
        },
        edges: {
            smooth: edgeSmoothing,
        },
        interaction: {
            hover: true,
            multiselect: true,
            dragNodes: true,
            navigationButtons: false,
        },
    };

    // CR-01: the initial stabilization is a layout in flight. The Group by
    // control, focus and source placement wait for settle() to release it.
    _initialSettled = false;
    setGroupBusy(true);
    const buildToken = layoutToken;
    network = new vis.Network(container, { nodes: visNodes, edges: visEdges }, options);
    initSidebar();

    // 260802-cu1: throttled label-visibility refresh. vis fires `zoom`
    // continuously during a scroll gesture, so trailing-debounce it at
    // LABEL_UPDATE_THROTTLE_MS. Also bind `animationFinished` — Fit View and
    // the double-click recenter (below) animate the scale without reliably
    // emitting `zoom`, so labels would otherwise go stale after those.
    // WR-02 note: both listeners bind to `network`, not a DOM node, and
    // network.destroy() (WR-03 above) tears them down along with the
    // network, so no module-level listener-attached guard is needed here —
    // unlike the button, slider, and window-resize listeners below that
    // bind to persistent DOM.
    const scheduleLabelUpdate = () => {
        if (_labelUpdateTimer) clearTimeout(_labelUpdateTimer);
        _labelUpdateTimer = setTimeout(applyScaleStyle, LABEL_UPDATE_THROTTLE_MS);
    };
    network.on('zoom', scheduleLabelUpdate);
    network.on('animationFinished', scheduleLabelUpdate);
    network.on('beforeDrawing', drawRegionCircles);
    network.on('afterDrawing', drawRegionLabels);

    // Disable physics after stabilization (research pitfall 4) and prime the
    // initial label-visibility state.
    //
    // 260802-cu1: keyed on `stabilizationIterationsDone`, NOT `stabilized`.
    // vis emits `stabilizationIterationsDone` when the configured iteration
    // budget is exhausted, then keeps free-running the simulation and emits
    // `stabilized` only once velocity falls below minVelocity. On a large
    // graph that second event may never arrive: measured on the 1738-node FDA
    // corpus, iterations finished at 7.0s but `stabilized` had still not fired
    // after 10 minutes, so physics ran forever and this callback never
    // executed — meaning label gating silently did nothing on exactly the
    // graphs it exists for. (Pre-existing for the physics-off half; both
    // solvers behave this way.) Iteration-budget completion is deterministic
    // and bounded, so key off it and keep `stabilized` as a safety net for
    // the case where the simulation settles before the budget is spent.
    //
    // CR-01: settle() belongs to this build only. A handler left over from an
    // earlier build (stale token) or a second event never touches physics.
    let _settled = false;
    const settle = () => {
        if (_settled || buildToken !== layoutToken) return;
        _settled = true;
        network.off('stabilizationIterationsDone', settle);
        network.off('stabilized', settle);
        network.setOptions({ physics: false });
        _initialSettled = true;
        setGroupBusy(false);
        // Fit first so the controller reads the real fit scale, not the
        // pre-fit one (stabilization fit is animated and lags the event).
        separateGroupRegionsForView();
        snapLayout();
        fitView(null, false);
        applyScaleStyle();
        if (groupMode === 'none') freeLayoutPositions = captureDataPositions();
        // WR-03: a Show sources toggle made while the layout ran is applied now.
        if (sourcesActive()) placeSources();
        syncSourcePhysics();
        setHintOverride(null);
        syncGroupControl();
    };
    network.once('stabilizationIterationsDone', settle);
    network.once('stabilized', settle);

    // Hover card: shown after a short pause over a node; hidden by any
    // gesture that moves the view. A selected node keeps its card pinned.
    network.on('hoverNode', (params) => {
        cancelHover();
        const nodeId = params.node;
        hoverCenterId = nodeId;
        hoverFocus = focusIds(nodeId, neighborsOf(nodeId), linkDegreeMap);
        scheduleFocus();
        const point = params.pointer && params.pointer.DOM;
        if (!point) return;
        _hoverTimer = setTimeout(() => {
            _hoverTimer = null;
            showCardFor(nodeId, domToClient(point));
        }, HOVER_CARD_DELAY_MS);
    });
    network.on('blurNode', () => {
        hoverCenterId = null;
        hoverFocus = new Set();
        scheduleFocus();
        cancelHover();
        if (pinnedCardNodeId !== null) showPinnedCard();
        else hideCard();
    });
    network.on('hoverEdge', (params) => { hoveredEdgeId = params.edge; scheduleFocus(); });
    network.on('blurEdge', () => { hoveredEdgeId = null; scheduleFocus(); });
    network.on('dragStart', () => { cancelHover(); hideCard(); });
    network.on('zoom', () => { cancelHover(); hideCard(); });

    // Click node -> highlight neighbourhood + sidebar; click edge -> sidebar only;
    // canvas background -> clear highlight + close sidebar. (D-01..D-04)
    network.on('click', (params) => {
        cancelHover();
        if (params.nodes.length > 0) {
            const nodeId = params.nodes[0];
            // The sidebar is the detail view for a selected node, so no card
            // stays pinned over it; assistive tech is pointed at the sidebar.
            pinnedCardNodeId = null;
            hideCard();

            // D-02: second click on already-highlighted node clears dim; sidebar stays open
            if (highlightedNodeId === nodeId) {
                clearHighlight();
                showNodeDetail(nodeId, allNodes, allEdges, SIDEBAR_OPTS);
                describeBySidebar();
                return;
            }

            // D-01: highlight this node's 1-hop neighbourhood; dim everything else
            clearHighlight();
            highlightedNodeId = nodeId;
            selectCenterId = nodeId;
            selectFocus = focusIds(nodeId, neighborsOf(nodeId), linkDegreeMap);
            scheduleFocus();

            const neighbourIds = new Set(network.getConnectedNodes(nodeId));
            neighbourIds.add(nodeId);

            const connectedEdgeIds = new Set(network.getConnectedEdges(nodeId));

            // Dim non-neighbourhood nodes to opacity 0.15
            const nodeDims = visNodes.getIds()
                .filter(id => !isAnchorId(id) && !neighbourIds.has(id))
                .map(id => ({ id, opacity: 0.15 }));
            if (nodeDims.length) visNodes.update(nodeDims);

            // Dim non-neighbourhood edges to opacity 0.15
            const edgeDims = visEdges.getIds()
                .filter(id => !isAnchorId(id) && !connectedEdgeIds.has(id))
                .map(id => ({ id, color: edgeColorObject(edgeColorById.get(id), edgeDimOpacity()) }));
            if (edgeDims.length) visEdges.update(edgeDims);

            // Open sidebar (Phase 09 unchanged)
            showNodeDetail(nodeId, allNodes, allEdges, SIDEBAR_OPTS);
            describeBySidebar();

        } else if (params.edges && params.edges.length > 0) {
            // D-04: edge click — sidebar only, no neighbourhood dim
            showEdgeDetail(params.edges[0], visEdges, allNodes);
        } else {
            // D-03: canvas background click — clear highlight AND close sidebar
            pinnedCardNodeId = null;
            hideCard();
            clearHighlight();
            hideSidebar();
        }
    });

    // Double-click -> focus mode on the node's 1-hop neighbourhood (R-01). This
    // replaces the earlier recenter-and-fit on double-click (D-17): a focus fit
    // does the same framing and also hides everything outside the set. A node
    // without a visible neighbour is only selected by the clicks.
    network.on('doubleClick', (params) => {
        if (params.nodes.length > 0) enterFocus(params.nodes[0], 1);
    });

    // Drag-to-pin: when user drops a node, pin it and apply the accent border.
    // Guard against canvas pan (params.nodes is empty for non-node drags).
    network.on('dragEnd', (params) => {
        if (!params.nodes || params.nodes.length === 0) return;
        const updates = params.nodes.map(nodeId => {
            pinnedNodes.add(nodeId);
            return {
                id: nodeId,
                fixed: { x: true, y: true },
                borderWidth: 2,
                color: {
                    border: '#4a6cf7',
                    highlight: { border: '#4a6cf7' },
                },
            };
        });
        visNodes.update(updates);
    });

    // WR-02: Guard fit-view and reset-pins listeners against duplicate registration
    // on repeated buildGraph() calls (mirrors _resizeListenerAttached pattern).
    if (!_btnListenersAttached) {
        const fitBtn = document.getElementById('graph-fit-btn');
        if (fitBtn) {
            fitBtn.addEventListener('click', () => {
                clearActiveRegion();
                fitView(null, fitAnimation(400));
            });
        }

        const resetPinsBtn = document.getElementById('graph-reset-pins-btn');
        if (resetPinsBtn) {
            resetPinsBtn.addEventListener('click', () => {
                if (pinnedNodes.size === 0) return;
                const unfixUpdates = [...pinnedNodes].map(nodeId => {
                    const node = allNodes.find(n => n.id === nodeId);
                    return {
                        id: nodeId,
                        fixed: false,
                        borderWidth: 1,
                        color: nodeColor(node?.entity_type || ''),
                    };
                });
                visNodes.update(unfixUpdates);
                pinnedNodes.clear();
            });
        }

        const sourcesBtn = document.getElementById('graph-show-sources-btn');
        if (sourcesBtn) {
            sourcesBtn.addEventListener('click', () => {
                setSourcesShown(sourcesBtn.getAttribute('aria-pressed') !== 'true');
            });
        }

        const edgeKeyBtn = document.getElementById('edge-key-toggle');
        if (edgeKeyBtn) {
            edgeKeyBtn.addEventListener('click', () => {
                const open = edgeKeyBtn.getAttribute('aria-expanded') !== 'true';
                edgeKeyBtn.setAttribute('aria-expanded', String(open));
                const panel = document.getElementById('edge-key');
                if (!panel) return;
                if (open) panel.removeAttribute('hidden');
                else panel.setAttribute('hidden', '');
            });
        }

        const groupsBtn = document.getElementById('graph-groups-btn');
        if (groupsBtn) {
            groupsBtn.addEventListener('click', () => {
                if (groupsBtn.hasAttribute('disabled')) return;
                const open = groupsBtn.getAttribute('aria-expanded') !== 'true';
                groupsBtn.setAttribute('aria-expanded', String(open));
                const panel = document.getElementById('graph-groups');
                if (!panel) return;
                if (open) panel.removeAttribute('hidden');
                else panel.setAttribute('hidden', '');
            });
        }

        attachGroupControl();
        _btnListenersAttached = true;
    }

    attachFocusListeners();
    activeRegionId = null;
    emphasizedRegionId = null;
    _frameRegions = null;
    _lastPlaced = [];
    syncSourcesButton();
    buildEdgeKey();
    renderGroupsList();
    syncGroupControl();
    _hintOverride = groupMode !== 'none' ? RELAYOUT_BUSY_TEXT : LAYOUT_BUSY_TEXT;
    renderGroupHint();
    if (groupMode === 'family' && groupModeState('cluster').enabled === false) {
        announceGroup(`Topic clusters unavailable: ${trimPeriod(groupModeState('cluster').reason)}. Grouped by entity family.`);
    }
    window._graphDebug = {
        network,
        visNodes,
        visEdges,
        get mode() { return groupMode; },
        get groupCount() { return groupLayout.size; },
        get settled() { return _initialSettled; },
        get busy() { return relayoutBusy; },
        relayoutTimeoutMs: () => relayoutTimeoutMs(),
        dataNodes: () => visNodes.get().filter(n => !n._anchor),
        dataEdges: () => visEdges.get().filter(e => !e._anchor),
        anchorCount: () => visNodes.get().filter(n => n._anchor).length,
        regionGeometry: () => currentRegions(),
        placedLabels: () => _lastPlaced,
        focus: () => ({ stack: focusStack.map(entry => ({ ...entry })), size: focusSet ? focusSet.size : 0 }),
        focusInfo: id => focusInfo(id),
    };

    // Close sidebar on window resize so it does not float
    // in a stale DOM position (RESEARCH Pitfall 4).
    // CR-02: Guard against accumulating duplicate listeners on repeated buildGraph() calls.
    if (!_resizeListenerAttached) {
        window.addEventListener('resize', hideSidebar);
        _resizeListenerAttached = true;
    }

    if (!_hoverListenersAttached) {
        const dismiss = () => { cancelHover(); hideCard(); };
        window.addEventListener('resize', dismiss);
        window.addEventListener('scroll', dismiss, true);
        // vis decides hover inside its canvas mousemove handler and never
        // emits blurNode when the pointer leaves the canvas, so leaving the
        // container (or switching away from the graph panel) ends the hover.
        container.addEventListener('pointerleave', endHover);
        window.addEventListener('graph-panel-closed', endHover);
        document.addEventListener('keydown', (event) => {
            if (event.key !== 'Escape') return;
            if (!graphPanelActive || isEditableTarget(event.target)) return;
            // One level per press: the hover card, then focus, then the zoomed-to group.
            // While a layout runs, the focus level is held (popOneFocus is a no-op).
            const cardOpen = isHoverCardVisible();
            pinnedCardNodeId = null;
            dismiss();
            if (cardOpen) return;
            if (focusStack.length > 0) {
                popOneFocus();
                return;
            }
            clearActiveRegion();
        });
        _hoverListenersAttached = true;
    }
}

// ---------------------------------------------------------------------------
// Neighborhood labels. The focus set (hover union selection) is written to the
// DataSets as deltas carrying only id + font, so it cannot clobber the
// highlight (opacity/color), filters (hidden) or pins.
// ---------------------------------------------------------------------------
// vis skips an edge whose endpoint node is hidden even though the edge itself
// keeps hidden: false, so an edge is drawn only when it and both ends are shown.
function edgeDrawn(edgeId) {
    if (isAnchorId(edgeId)) return false;
    const rec = visEdges.get(edgeId);
    if (!rec || rec.hidden === true) return false;
    const a = visNodes.get(rec.from);
    const b = visNodes.get(rec.to);
    return Boolean(a && b) && a.hidden !== true && b.hidden !== true;
}

function neighborsOf(id) {
    if (!network || !visNodes) return [];
    return (network.getConnectedNodes(id) || []).filter(nid => {
        if (isAnchorId(nid)) return false;
        const rec = visNodes.get(nid);
        return rec && rec.hidden !== true;
    });
}

function scheduleFocus() {
    if (_focusRaf !== null) return;
    if (typeof requestAnimationFrame === 'function') {
        _focusRaf = requestAnimationFrame(applyFocus);
        _focusCancel = cancelAnimationFrame;
    } else {
        _focusRaf = setTimeout(applyFocus, 16);
        _focusCancel = clearTimeout;
    }
}

function cancelFocus() {
    if (_focusRaf !== null && _focusCancel) _focusCancel(_focusRaf);
    _focusRaf = null;
    _focusCancel = null;
}

function applyFocus() {
    _focusRaf = null;
    _focusCancel = null;
    if (!network || !visNodes || !visEdges) return;
    const scale = network.getScale();

    const nextNodes = new Set([...hoverFocus, ...selectFocus]);
    const nodeDelta = focusDelta(focusNodeIds, nextNodes);
    focusNodeIds = nextNodes;
    const nodeChanged = [...nodeDelta.added, ...nodeDelta.removed];
    if (nodeChanged.length) {
        visNodes.update(nodeChanged.map(id => ({ id, font: nodeLabelFont(id, scale, _lastCutoff) })));
    }

    const centerEdgeLists = [];
    for (const center of [hoverCenterId, selectCenterId]) {
        if (center === null) continue;
        centerEdgeLists.push((network.getConnectedEdges(center) || []).filter(edgeDrawn));
    }
    const nextEdges = namedEdgeIds(centerEdgeLists, hoveredEdgeId);
    const edgeDelta = focusDelta(focusEdgeIds, nextEdges);
    focusEdgeIds = nextEdges;
    const edgeUpdates = [
        ...edgeDelta.added.map(id => ({ id, font: edgeLabelFont(scale, true) })),
        ...edgeDelta.removed.map(id => ({ id, font: edgeLabelFont(scale, false) })),
    ];
    if (edgeUpdates.length) visEdges.update(edgeUpdates);

    window._labelDebug = {
        ...(window._labelDebug || {}),
        focusNodes: focusNodeIds.size,
        focusEdges: focusEdgeIds.size,
    };
}

// ---------------------------------------------------------------------------
// Hover card helpers
// ---------------------------------------------------------------------------
function cancelHover() {
    if (_hoverTimer) {
        clearTimeout(_hoverTimer);
        _hoverTimer = null;
    }
}

// Only drops aria-describedby when it points at the card; a selection keeps
// the container described by the open sidebar.
function hideCard() {
    hideHoverCard();
    const container = document.getElementById('graph-container');
    if (container && container.getAttribute('aria-describedby') === 'graph-hover-card') {
        container.removeAttribute('aria-describedby');
    }
}

// Ends any hover: cancels a pending card, hides the card and clears the
// hover focus labels and hovered-edge name. The selection focus is kept.
function endHover() {
    cancelHover();
    hideCard();
    hoverCenterId = null;
    hoverFocus = new Set();
    hoveredEdgeId = null;
    scheduleFocus();
}

// vis reports DOM coordinates relative to the canvas; the card is positioned
// against the viewport.
function domToClient(point) {
    const container = document.getElementById('graph-container');
    const rect = container ? container.getBoundingClientRect() : { left: 0, top: 0 };
    return { x: rect.left + point.x, y: rect.top + point.y };
}

function showCardFor(nodeId, clientPoint) {
    const node = nodeById.get(nodeId);
    if (!node) return;
    const d = typeDisplay(node.entity_type);
    const model = hoverCardModel(node, adjacency.get(nodeId) || [], nodeById, {
        isSourceNode: isSourceNodeId,
        isSourceEdge: isSourceEdgeRecord,
        typeLabel: d.label,
        family: d.family,
        description: d.description,
    });
    showHoverCard(model, node.entity_type, clientPoint);
    const container = document.getElementById('graph-container');
    if (container) container.setAttribute('aria-describedby', 'graph-hover-card');
}

function describeBySidebar() {
    const container = document.getElementById('graph-container');
    if (container) container.setAttribute('aria-describedby', 'graph-detail-sidebar');
}

function showPinnedCard() {
    if (!network || pinnedCardNodeId === null) return;
    const pos = network.getPositions([pinnedCardNodeId])[pinnedCardNodeId];
    if (!pos) return;
    showCardFor(pinnedCardNodeId, domToClient(network.canvasToDOM(pos)));
}

// Edge key: one row per relation category among the edges currently drawn
// (rebuilt by filterGraph()) plus a dashed row for claims that are not
// asserted. Hidden when no display data.
function buildEdgeKey() {
    const toggle = document.getElementById('edge-key-toggle');
    const panel = document.getElementById('edge-key');
    if (!toggle || !panel) return;
    const entries = categoryEntries();
    const counts = new Map();
    allEdges.forEach((e, i) => {
        if (visEdges && visNodes && !edgeDrawn(edgeIdByIndex[i])) return;
        const category = relationDisplay(e.relation_type).category;
        counts.set(category, (counts.get(category) || 0) + 1);
    });
    const rows = [];
    for (const entry of entries) {
        const count = counts.get(entry.name) || 0;
        if (count === 0) continue;
        const row = document.createElement('div');
        row.className = 'edge-key__row';
        const label = document.createElement('span');
        label.className = 'edge-key__label';
        label.textContent = entry.label;
        const num = document.createElement('span');
        num.className = 'edge-key__count';
        num.textContent = count.toLocaleString();
        row.append(makeEdgeSample(entry.color), label, num);
        rows.push(row);
    }
    if (entries.length === 0) {
        panel.replaceChildren();
        panel.setAttribute('hidden', '');
        toggle.setAttribute('hidden', '');
        toggle.setAttribute('aria-expanded', 'false');
        return;
    }
    const other = entries.find(c => c.name === 'other');
    const dashedRow = document.createElement('div');
    dashedRow.className = 'edge-key__row';
    const dashedLabel = document.createElement('span');
    dashedLabel.className = 'edge-key__label';
    dashedLabel.textContent = 'Dashed: not asserted (any other status, e.g. hypothesized, prophetic, speculative)';
    dashedRow.append(makeEdgeSample(other ? other.color : undefined, { dashed: true }), dashedLabel);
    rows.push(dashedRow);
    panel.replaceChildren(...rows);
    toggle.removeAttribute('hidden');
    if (toggle.getAttribute('aria-expanded') !== 'true') panel.setAttribute('hidden', '');
}

// The filter inputs read from the toolbar. `severityNodeIds` is null when no
// severity filter is active.
function filterContext() {
    const searchTerm = (document.getElementById('graph-search')?.value || '').toLowerCase();
    const severityFilter = document.getElementById('severity-filter')?.value || 'all';

    // Build set of node IDs involved in claims of selected severity
    let severityNodeIds = null;  // null means no filter (show all)
    if (severityFilter !== 'all' && window._claimsData) {
        severityNodeIds = new Set();
        const claims = window._claimsData;
        // `findings` is the flattened custom-rule channel (per-domain
        // CUSTOM_RULES and the cross-domain rules engine). Its items carry the
        // same `severity` + `affected_entities` fields as the three original
        // sections, so it needs no special-casing beyond being listed here.
        for (const section of ['conflicts', 'gaps', 'risks', 'findings']) {
            for (const item of (claims[section] || [])) {
                if ((item.severity || '').toLowerCase() === severityFilter.toLowerCase()) {
                    // Collect affected entity IDs
                    if (item.entity_a) severityNodeIds.add(item.entity_a);
                    if (item.entity_b) severityNodeIds.add(item.entity_b);
                    for (const eid of (item.affected_entities || [])) {
                        severityNodeIds.add(eid);
                    }
                }
            }
        }
    }
    return { searchTerm, severityNodeIds };
}

// Does the node pass every node-level filter (type, search, severity, degree)?
function nodePassesFilters(n, ctx) {
    const typeVisible = typeFilterEnabled
        ? activeTypes.has(typeKey(n.entity_type))
        : !(sourceNodeIds.has(n.id) && !sourcesShown);
    const searchMatch = !ctx.searchTerm || (n.name || '').toLowerCase().includes(ctx.searchTerm);
    const severityMatch = !ctx.severityNodeIds || ctx.severityNodeIds.has(n.id);
    // DEGREE-01: hide nodes whose linkDegree (linkDegreeMap, computed at build time
    // across ALL non-source edges, not currently visible edges) is below the threshold.
    // Source nodes have no non-source edges by definition (linkDegree 0), so the
    // threshold does not apply to them: the Show sources toggle alone decides.
    const degreeOk = sourceNodeIds.has(n.id)
        || (linkDegreeMap[n.id] || 0) >= minDegreeThreshold;
    return typeVisible && searchMatch && severityMatch && degreeOk;
}

// Is the edge hidden by the epistemic, confidence, relation or sources filters?
function edgeFilterHidden(e) {
    const status = e.epistemic_status;
    const confidence = e.confidence;

    // Epistemic filter:
    // - Edge with no status: always visible from this dimension
    // - Edge with status not in activeEpistemicStatuses: hidden (D-07: empty set hides all status-bearing edges)
    const hasStatus = status != null && status !== '';
    const epistemicHidden = hasStatus && !activeEpistemicStatuses.has(status);

    // Confidence filter:
    // - Scored edge (numeric confidence): hidden when confidence < threshold
    // - Unscored edge (null/undefined): hidden when threshold > 0.5 (D-12)
    const isScored = typeof confidence === 'number' && isFinite(confidence);
    const confidenceHidden = isScored
        ? confidence < confidenceThreshold
        : confidenceThreshold > 0.5;

    // RTYPE-03: hide edges whose relation_type is not in activeRelationTypes.
    // Edges with no relation_type field remain visible from this dimension
    // (mirrors the "hasStatus" guard for epistemic_status above).
    const hasRelType = e.relation_type != null && e.relation_type !== '';
    const relationHidden = hasRelType && !activeRelationTypes.has(e.relation_type);

    const sourceRelHidden = !sourcesShown && isSourceRelation(e.relation_type);

    return epistemicHidden || confidenceHidden || relationHidden || sourceRelHidden;
}

function eligibleNodeSet(ctx) {
    const eligible = new Set();
    for (const n of allNodes) if (nodePassesFilters(n, ctx)) eligible.add(n.id);
    return eligible;
}

// Focus walks only edges that are drawn by the current filters; source edges
// join only while sources are shown. The walk reads the adjacency Map, never
// the vis hidden flags.
function focusEdgeEligible(e) {
    return !edgeFilterHidden(e) && (sourcesActive() || !isSourceEdgeRecord(e));
}

function focusNeighbourhood(centerId, hops, eligible) {
    return kHop(adjacency, centerId, hops, focusEdgeEligible, id => eligible.has(id));
}

function filterGraph() {
    if (!visNodes) return;
    clearHighlight();

    const ctx = filterContext();
    const eligible = eligibleNodeSet(ctx);
    const previousLabels = focusLabelIds;
    resolveFocus(eligible);

    // Update node visibility. Focus is a second mask over the filters: nodes
    // outside the focus set are hidden, never moved.
    const updates = allNodes.map(n => ({
        id: n.id,
        hidden: !eligible.has(n.id) || (focusSet !== null && !focusSet.has(n.id)),
    }));

    visNodes.update(updates);

    // Edge visibility: epistemic status filter + confidence threshold filter (FILTER-01..03)
    // D-09: confidence slider filters edges only — node visibility is not affected here
    if (visEdges) {
        // WR-01: retrieve edge source data by ID from the DataSet record (_data field)
        // rather than correlating by positional index. vis.DataSet.getIds() does not
        // guarantee insertion order, so index-based correlation can silently apply
        // the wrong filter to the wrong edge after any DataSet mutation.
        const edgeUpdates = visEdges.getIds().filter(id => !isAnchorId(id)).map(edgeId => {
            const record = visEdges.get(edgeId);
            const e = record?._data;
            if (!e) return { id: edgeId, hidden: false };
            return { id: edgeId, hidden: edgeFilterHidden(e) };
        });

        visEdges.update(edgeUpdates);
    }

    buildEdgeKey();
    renderGroupsList();
    finishFocusUpdate(previousLabels);

    // Show empty state if all hidden
    const visibleCount = updates.filter(u => !u.hidden).length;
    const container = document.getElementById('graph-container');
    const emptyMsg = container?.querySelector('.graph-empty-msg');
    if (visibleCount === 0 && !emptyMsg) {
        const msg = document.createElement('p');
        msg.className = 'graph-placeholder graph-empty-msg';
        msg.textContent = 'No entities match the current filters. Try broadening your search or toggling entity types.';
        container?.appendChild(msg);
    } else if (visibleCount > 0 && emptyMsg) {
        emptyMsg.remove();
    }
}

// ---------------------------------------------------------------------------
// Focus mode (R-01, R-02). A focus is a stack of centres; the top entry's 1- or
// 2-hop neighbourhood over the filter-eligible graph is the only part of the
// graph shown. It is a second mask inside filterGraph(): nodes outside the set
// are hidden and nothing is dimmed; the shown nodes are laid out afresh (and
// put back on exit). The walk reads the
// adjacency Map, never vis hidden flags or network.getConnected*.
// ---------------------------------------------------------------------------
const HOP_WORD = { 1: '1 hop', 2: '2 hops' };
const FOCUS_BUSY_TEXT = 'Focus is unavailable while the layout is arranging. Try again when it finishes.';
const FOCUS_ENDED_HINT_MS = 6000;
const REGION_GAP_SCREEN_PX = 16;         // clear screen px kept between two drawn region circles
const REGION_GAP_PASSES = 4;             // separation passes while the fit scale settles
const SIDEBAR_FALLBACK_PX = 320;         // sidebar width when it cannot be measured
const FIT_EDGE_PAD_PX = 30;              // clear px kept between fitted nodes and the uncovered area's edge
const FIT_MAX_SCALE = 1;                 // a fit never zooms in past 1:1
const FOCUS_LAYOUT_FONT_PX = 13;         // label size assumed when spacing a focus layout
const FOCUS_NODE_HALF_PX = 3;            // half the node marker height assumed in a focus label box
const FOCUS_LABEL_LINE_PX = 16;          // label line height assumed in a focus label box
const FOCUS_CENTRE_SCALE = 1.35;         // the centre's label box is this much wider than its measured text
const FOCUS_CENTRE_EXTRA_PX = 14;        // and this much taller (larger marker)
const FOCUS_VIEW_PAD_PX = 40;            // px of the viewport reserved around a focus layout

function nodeName(id) {
    const n = nodeById.get(id);
    return String((n && n.name) || id);
}

function countText(n) {
    return `${n.toLocaleString()} ${n === 1 ? 'node' : 'nodes'}`;
}

function resetFocusState() {
    focusPre = null;
    _focusLayoutKey = null;
    focusStack = [];
    focusHops = 1;
    focusSet = null;
    focusLabelIds = new Set();
    focusCounts = { 1: 0, 2: 0 };
    focusEndedNote = null;
    focusBarShown = false;
    _lastFocusSig = JSON.stringify(focusDetail());
    const bar = document.getElementById('graph-focus-bar');
    if (bar) bar.setAttribute('hidden', '');
}

function focusDetail() {
    const top = focusStack[focusStack.length - 1] || null;
    return { id: top ? top.id : null, hops: focusHops, counts: { 1: focusCounts[1], 2: focusCounts[2] } };
}

// Recomputes the focus set, hop counts and label ids from the current filter
// eligibility. A centre hidden by the filters ends focus.
function resolveFocus(eligible) {
    focusEndedNote = null;
    if (focusStack.length > 0) {
        const top = focusStack[focusStack.length - 1];
        if (!eligible.has(top.id)) {
            focusEndedNote = nodeName(top.id);
            focusStack = [];
        }
    }
    if (focusStack.length === 0) {
        focusSet = null;
        focusLabelIds = new Set();
        focusCounts = { 1: 0, 2: 0 };
        return;
    }
    const top = focusStack[focusStack.length - 1];
    const one = focusNeighbourhood(top.id, 1, eligible);
    const two = focusNeighbourhood(top.id, 2, eligible);
    focusCounts = { 1: one.size, 2: two.size };
    focusHops = top.hops;
    focusSet = top.hops === 2 ? two : one;
    // In-set degree: edges drawn between two focus nodes.
    const inSetDegree = new Map();
    for (const id of focusSet) {
        let degree = 0;
        for (const e of adjacency.get(id) || []) {
            const other = e.source === id ? e.target : e.source;
            if (focusSet.has(other) && focusEdgeEligible(e)) degree += 1;
        }
        inSetDegree.set(id, degree);
    }
    focusLabelIds = focusModeLabelIds(top.id, focusSet, one, inSetDegree, FOCUS_OUTER_RING_LABELS ? FOCUS_MODE_MAX_LABELS : 0);
}

// Width in px of `text` at the focus label size.
function labelWidthPx(text) {
    if (_measureCtx === null && typeof document.createElement === 'function') {
        const canvas = document.createElement('canvas');
        _measureCtx = (canvas && typeof canvas.getContext === 'function' && canvas.getContext('2d')) || false;
    }
    if (_measureCtx) {
        _measureCtx.font = `${FOCUS_LAYOUT_FONT_PX}px sans-serif`;
        return _measureCtx.measureText(text).width;
    }
    return text.length * FOCUS_LAYOUT_FONT_PX * 0.55;
}

function focusSortKey(id) {
    const n = nodeById.get(id);
    return `${groupAssignment.get(id) || ''}\u0000${(n && n.entity_type) || ''}\u0000${nodeName(id)}`;
}

// While focused the neighbourhood is laid out in label-sized rows around the
// centre (see focusLayout); the positions from before the first focus are kept and put
// back exactly when focus ends. Physics is already off after any layout.
function syncFocusLayout() {
    // WR-01: positions are in flux while a layout runs; completeRelayout() and
    // settle() lay the focus out once it is final.
    if (!network || !visNodes || relayoutBusy) return;
    if (focusStack.length === 0 || focusSet === null) {
        restoreFocusLayout();
        return;
    }
    const top = focusStack[focusStack.length - 1];
    const eligible = eligibleNodeSet(filterContext());
    const ring1Ids = [...focusNeighbourhood(top.id, 1, eligible)].filter(id => id !== top.id && focusSet.has(id));
    const ring1Set = new Set(ring1Ids);
    const ring2Ids = [...focusSet].filter(id => id !== top.id && !ring1Set.has(id));
    const shownSources = [...sourceNodeIds].filter(id => {
        const rec = visNodes.get(id);
        return rec && rec.hidden !== true;
    }).sort();
    const key = fnv1a([top.id, top.hops, [...focusSet].sort().join(','), shownSources.join(',')].join('|'));
    if (key === _focusLayoutKey) return;
    _focusLayoutKey = key;
    if (!focusPre) focusPre = { positions: captureDataPositions(), sourcesPlaced };

    const keyed = id => ({ id, key: focusSortKey(id) });
    const ring1 = ring1Ids.map(keyed).sort((a, b) => (a.key < b.key ? -1 : a.key > b.key ? 1 : (a.id < b.id ? -1 : 1)));
    const rank = new Map(ring1.map((it, i) => [it.id, i]));
    const ring2 = ring2Ids.map(id => {
        let parent = null;
        for (const e of adjacency.get(id) || []) {
            const other = e.source === id ? e.target : e.source;
            if (rank.has(other) && focusEdgeEligible(e) && (parent === null || rank.get(other) < rank.get(parent))) parent = other;
        }
        return { ...keyed(id), parent };
    });
    const boxes = new Map();
    for (const id of focusSet) {
        // Labelled focus nodes reserve their full name; the rest (2-hop nodes
        // when FOCUS_OUTER_RING_LABELS is off) are bare markers.
        const labelled = focusLabelIds.has(id) || FOCUS_OUTER_RING_LABELS;
        const text = labelled ? truncateLabel(nodeName(id), focusLabelIds.has(id) ? FOCUS_TRUNCATE_CHARS : undefined) : '';
        boxes.set(id, {
            w: Math.max(text ? labelWidthPx(text) : 0, 2 * FOCUS_NODE_HALF_PX) + 4,
            h: 2 * FOCUS_NODE_HALF_PX + (labelled ? FOCUS_LABEL_LINE_PX : 0),
            dy: labelled ? FOCUS_LABEL_LINE_PX / 2 : 0,
        });
    }
    // The centre is drawn larger (bigger marker, bigger label) than its neighbours.
    const centreBox = boxes.get(top.id);
    boxes.set(top.id, {
        w: Math.round(centreBox.w * FOCUS_CENTRE_SCALE),
        h: centreBox.h + FOCUS_CENTRE_EXTRA_PX,
        dy: centreBox.dy + FOCUS_CENTRE_EXTRA_PX / 2,
    });
    const container = document.getElementById('graph-container');
    const cover = focusCoverPx();
    const availW = Math.max(((container && container.clientWidth) || 0) - cover - FOCUS_VIEW_PAD_PX, 200);
    const availH = Math.max(((container && container.clientHeight) || 0) - FOCUS_VIEW_PAD_PX, 200);
    const layout = focusLayout({ centerId: top.id, ring1, ring2, boxes, aspect: availW / availH });
    const moves = [...layout];
    // Sources have no labels: each sits at its focused neighbours' centre.
    shownSources.forEach((id, index) => {
        let sx = 0; let sy = 0; let n = 0;
        for (const nb of sourceNeighbours.get(id) || []) {
            const p = layout.get(nb);
            if (!p) continue;
            sx += p.x; sy += p.y; n += 1;
        }
        if (n === 0) return;
        moves.push([id, { x: sx / n + ((index % 7) - 3) * 12, y: sy / n + ((Math.floor(index / 7) % 7) - 3) * 12 }]);
    });
    writePositions(moves);
}

// IN-06: canvas width the sidebar covers for a focus layout: the open sidebar,
// or the one the running focus change is about to open (entry selects the
// centre after filterGraph() has laid the focus out). A closed sidebar that
// stays closed (e.g. a filter change after a canvas click) covers nothing.
function focusCoverPx() {
    const open = sidebarCoverPx();
    if (open > 0 || !_focusOpensSidebar) return open;
    const sb = document.getElementById('graph-detail-sidebar');
    return (sb && sb.offsetWidth) || SIDEBAR_FALLBACK_PX;
}

function restoreFocusLayout() {
    _focusLayoutKey = null;
    if (!focusPre) return;
    const pre = focusPre;
    focusPre = null;
    writePositions(pre.positions);
    sourcesPlaced = pre.sourcesPlaced;
    if (!sourcesPlaced && sourcesActive()) placeSources();
}

// Runs after filterGraph() wrote the visibility: labels, bar and event.
function finishFocusUpdate(previousLabels) {
    syncFocusLayout();
    refreshFocusLabels(previousLabels);
    syncFocusBar();
    if (focusEndedNote !== null) {
        const text = `Focus ended: ${focusEndedNote} is hidden by the current filters.`;
        setHintOverride(text, FOCUS_ENDED_HINT_MS);
        announceGroup(text);
    }
    emitFocusChanged();
}

// Focus nodes keep their full name up to FOCUS_TRUNCATE_CHARS; every other
// node uses the resting truncation. Only ids that changed sides are written.
function refreshFocusLabels(previousLabels) {
    if (!visNodes) return;
    const changed = [];
    for (const id of focusLabelIds) if (!previousLabels.has(id)) changed.push(id);
    for (const id of previousLabels) if (!focusLabelIds.has(id)) changed.push(id);
    if (changed.length === 0 && focusSet === null) return;
    visNodes.update(changed.filter(id => nodeById.has(id)).map(id => ({
        id,
        label: truncateLabel(nodeName(id), focusLabelIds.has(id) ? FOCUS_TRUNCATE_CHARS : undefined),
    })));
    // Fonts follow the label ids; force the scale controller to rewrite them.
    _lastStyleKey = null;
    applyScaleStyle();
}

function emitFocusChanged() {
    const detail = focusDetail();
    const sig = JSON.stringify(detail);
    if (sig === _lastFocusSig) return;
    _lastFocusSig = sig;
    if (typeof window.dispatchEvent === 'function' && typeof CustomEvent === 'function') {
        window.dispatchEvent(new CustomEvent('graph-focus-changed', { detail }));
    }
}

// What the sidebar shows for node `id`: the current centre, hop setting and
// the 1- and 2-hop sizes around `id` over the filter-eligible graph.
function focusInfo(id) {
    const top = focusStack[focusStack.length - 1] || null;
    const eligible = eligibleNodeSet(filterContext());
    const known = typeof id === 'string' && nodeById.has(id);
    return {
        centerId: top ? top.id : null,
        hops: focusHops,
        counts: {
            1: known ? focusNeighbourhood(id, 1, eligible).size : 0,
            2: known ? focusNeighbourhood(id, 2, eligible).size : 0,
        },
    };
}

function focusMessage() {
    const top = focusStack[focusStack.length - 1];
    return `Focus: ${nodeName(top.id)}, ${HOP_WORD[top.hops]}, ${countText(focusSet.size)} shown.`;
}

// Selects the centre like a click does (sidebar plus neighbourhood labels).
function selectFocusCenter(id) {
    pinnedCardNodeId = null;
    hideCard();
    highlightedNodeId = id;
    selectCenterId = id;
    selectFocus = focusIds(id, neighborsOf(id), linkDegreeMap);
    scheduleFocus();
    showNodeDetail(id, allNodes, allEdges, SIDEBAR_OPTS);
    describeBySidebar();
}

// Applies the stack as it stands: filters, bar, selection, announcement and a
// fit to what is shown. `kind` is 'enter' | 'back' | 'exit'.
function applyFocusChange(kind) {
    cancelHover();
    hideCard();
    _focusOpensSidebar = kind !== 'exit';
    try {
        filterGraph();
    } finally {
        _focusOpensSidebar = false;
    }
    if (focusEndedNote === null) {
        const top = focusStack[focusStack.length - 1];
        if (kind === 'exit') announceGroup('Focus ended.');
        else if (kind === 'back') announceGroup(`Focus: back to ${nodeName(top.id)}.`);
        else announceGroup(focusMessage());
        if (top) selectFocusCenter(top.id);
    }
    fitView(focusSet ? [...focusSet] : null, fitAnimation(250));
}

// WR-01: focus changes wait while a layout (initial or relayout) is in flight,
// so the saved pre-focus positions and the focus layout never mix with a
// running simulation. The request is dropped and the reason announced.
function focusBlocked() {
    if (!relayoutBusy) return false;
    announceGroup(FOCUS_BUSY_TEXT);
    return true;
}

// Enters focus on `id` (or retargets the hops of the current centre). Returns
// false for ids that are unknown, filtered out or have no visible neighbour,
// and while a layout is in flight.
function enterFocus(id, hops = 1) {
    if (!network || !visNodes || typeof id !== 'string' || isAnchorId(id) || !nodeById.has(id)) return false;
    if (focusBlocked()) return false;
    const size = hops === 2 ? 2 : 1;
    const eligible = eligibleNodeSet(filterContext());
    if (!eligible.has(id)) return false;
    const top = focusStack[focusStack.length - 1];
    if (top && top.id === id) {
        if (top.hops === size) return true;
        focusStack = setTopHops(focusStack, size);
    } else {
        if (focusNeighbourhood(id, 1, eligible).size < 2) return false;
        clearActiveRegion();
        focusStack = pushFocus(focusStack, { id, hops: size });
    }
    focusHops = size;
    applyFocusChange('enter');
    return true;
}

function exitFocus() {
    if (focusStack.length === 0 || focusBlocked()) return;
    focusStack = [];
    applyFocusChange('exit');
}

function popOneFocus() {
    if (focusStack.length === 0 || focusBlocked()) return;
    if (focusStack.length === 1) {
        exitFocus();
        return;
    }
    focusStack = popFocus(focusStack);
    focusHops = focusStack[focusStack.length - 1].hops;
    applyFocusChange('back');
}

function truncateFocusTo(index) {
    if (index < 0 || index >= focusStack.length - 1 || focusBlocked()) return;
    focusStack = truncateFocus(focusStack, index);
    focusHops = focusStack[focusStack.length - 1].hops;
    applyFocusChange('back');
}

function setFocusHops(hops) {
    if (focusStack.length === 0) return;
    const size = hops === 2 ? 2 : 1;
    if (focusStack[focusStack.length - 1].hops === size || focusBlocked()) return;
    focusStack = setTopHops(focusStack, size);
    focusHops = size;
    applyFocusChange('enter');
}

// Escape is ignored while the user types or works in the chat panel.
function isEditableTarget(target) {
    if (!target) return false;
    const tag = String(target.tagName || '').toUpperCase();
    if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return true;
    if (target.isContentEditable === true) return true;
    return typeof target.closest === 'function' && Boolean(target.closest('#chat-panel, .chat-panel'));
}

function crumbButton(crumb, onClick) {
    const btn = document.createElement('button');
    btn.setAttribute('type', 'button');
    btn.className = 'graph-focus-bar__crumb';
    btn.textContent = crumb.label;
    btn.setAttribute('title', crumb.title);
    btn.addEventListener('click', onClick);
    return btn;
}

function renderFocusCrumbs() {
    const list = document.getElementById('graph-focus-crumbs');
    if (!list) return;
    const items = crumbsFor(focusStack, nodeName).map(crumb => {
        const li = document.createElement('li');
        let el;
        if (crumb.kind === 'all') {
            el = crumbButton(crumb, () => exitFocus());
        } else if (crumb.kind === 'node' && !crumb.current) {
            el = crumbButton(crumb, () => truncateFocusTo(crumb.index));
        } else {
            el = document.createElement('span');
            el.className = 'graph-focus-bar__crumb';
            el.textContent = crumb.label;
            el.setAttribute('title', crumb.title);
            if (crumb.current) {
                el.className += ' graph-focus-bar__crumb--current';
                el.setAttribute('aria-current', 'location');
            } else {
                el.className += ' graph-focus-bar__crumb--collapsed';
            }
        }
        li.appendChild(el);
        return li;
    });
    list.replaceChildren(...items);
}

function renderFocusHops() {
    for (const hops of [1, 2]) {
        const btn = document.getElementById(`graph-focus-hop-${hops}`);
        if (!btn) continue;
        const count = document.createElement('span');
        count.className = 'graph-focus-bar__count';
        count.textContent = countText(focusCounts[hops]);
        btn.replaceChildren(document.createTextNode(`${HOP_WORD[hops]} · `), count);
        const checked = focusHops === hops;
        btn.setAttribute('aria-checked', String(checked));
        btn.setAttribute('tabindex', checked ? '0' : '-1');
    }
}

// The bar sits in the page flow, so showing or hiding it changes the canvas
// height by about 36px. vis only re-measures on its own timer, so the canvas
// is resized right away, before the caller fits the view.
function syncFocusBar() {
    const bar = document.getElementById('graph-focus-bar');
    if (!bar) return;
    const focused = focusStack.length > 0;
    if (focused) {
        renderFocusCrumbs();
        renderFocusHops();
        bar.removeAttribute('hidden');
    } else {
        bar.setAttribute('hidden', '');
    }
    if (focused !== focusBarShown) {
        focusBarShown = focused;
        if (network) {
            network.setSize('100%', '100%');
            network.redraw();
        }
    }
}

function attachFocusListeners() {
    if (_focusListenersAttached) return;
    _focusListenersAttached = true;
    const exitBtn = document.getElementById('graph-focus-exit');
    if (exitBtn) exitBtn.addEventListener('click', () => exitFocus());
    for (const hops of [1, 2]) {
        const btn = document.getElementById(`graph-focus-hop-${hops}`);
        if (!btn) continue;
        btn.addEventListener('click', () => setFocusHops(hops));
        btn.addEventListener('keydown', (event) => {
            const target = radioTarget(event.key, [1, 2], hops);
            if (target === undefined) return;
            event.preventDefault();
            if (!target) return;
            const targetBtn = document.getElementById(`graph-focus-hop-${target}`);
            if (targetBtn && typeof targetBtn.focus === 'function') targetBtn.focus();
            setFocusHops(target);
        });
    }
    // Entry points for other modules (the sidebar): ids and hops are validated
    // here, whatever the sender put in the event.
    window.addEventListener('graph-focus-node', (event) => {
        const detail = (event && event.detail) || {};
        enterFocus(detail.id, detail.hops);
    });
    window.addEventListener('graph-focus-exit', () => exitFocus());
    // The sidebar's hop toggle for a node that is not the centre: it only sets
    // the shared hop count. While focused, the centre keeps its own setting.
    window.addEventListener('graph-focus-hops', (event) => {
        const detail = (event && event.detail) || {};
        if (focusStack.length === 0) focusHops = detail.hops === 2 ? 2 : 1;
    });
}

// ---------------------------------------------------------------------------
// Show sources toggle (GVIS-06). Classification comes from the resolver via
// display.js; this code only reads the flags.
// ---------------------------------------------------------------------------
function isNodeHiddenAtBuild(n) {
    if (typeFilterEnabled) return !activeTypes.has(typeKey(n.entity_type));
    return sourceNodeIds.has(n.id) && !sourcesShown;
}

function sourcesActive() {
    return typeFilterEnabled ? sourceTypes().some(t => activeTypes.has(t)) : sourcesShown;
}

function syncSourcesButton() {
    const btn = document.getElementById('graph-show-sources-btn');
    if (!btn) return;
    const text = document.createElement('span');
    text.className = 'graph-toolbar__label';
    if (sourceNodeIds.size === 0) {
        btn.setAttribute('disabled', '');
        btn.setAttribute('aria-pressed', 'false');
        btn.setAttribute('title', 'This graph has no source nodes.');
        text.textContent = 'Show sources';
        btn.replaceChildren(text);
        return;
    }
    btn.removeAttribute('disabled');
    const on = sourcesActive();
    document.querySelectorAll('.legend-chip[data-type]').forEach(chip => {
        const type = chip.getAttribute('data-type');
        if (isSourceType(type)) setChipPressed(chip, activeTypes.has(type));
    });
    btn.setAttribute('aria-pressed', String(on));
    btn.setAttribute('title', on
        ? 'Hide source documents and publications'
        : `Show source documents and publications (${sourceNodeIds.size.toLocaleString()}) and their links`);
    text.textContent = on ? 'Hide sources' : 'Show sources';
    const count = document.createElement('span');
    count.className = 'graph-toolbar__count';
    count.textContent = sourceNodeIds.size.toLocaleString();
    btn.replaceChildren(text, count);
}

// First reveal: place each source node at the centroid of its non-source
// neighbours (plus deterministic jitter) so it appears next to what it cites.
function placeSources() {
    // WR-03: neighbour positions are in flux while a layout runs; placement is
    // deferred to the end of the layout (sourcesPlaced stays false).
    if (sourcesPlaced || !network || relayoutBusy) return;
    sourcesPlaced = true;
    const ids = [...sourceNodeIds].sort();
    // Region circles of the grouped layout; sources are not members, so placing
    // them never changes a radius.
    const regionById = new Map(currentRegions().map(r => [r.id, r]));
    const moves = [];
    ids.forEach((id, index) => {
        let neighbourIds = [...(sourceNeighbours.get(id) || [])];
        // Grouped: land among the neighbours of the source's own group so the
        // source sits inside that group's region.
        const gid = sourceGroup.get(id);
        if (gid !== undefined) {
            const inGroup = neighbourIds.filter(nb => groupAssignment.get(nb) === gid);
            if (inGroup.length > 0) neighbourIds = inGroup;
        }
        if (neighbourIds.length === 0) return;
        const positions = network.getPositions(neighbourIds);
        let sx = 0;
        let sy = 0;
        let n = 0;
        for (const nbId of neighbourIds) {
            const p = positions[nbId];
            if (!p) continue;
            sx += p.x;
            sy += p.y;
            n += 1;
        }
        if (n === 0) return;
        const jitterX = ((index % 7) - 3) * 12;
        const jitterY = ((Math.floor(index / 7) % 7) - 3) * 12;
        let target = { x: sx / n + jitterX, y: sy / n + jitterY };
        const region = gid === undefined ? undefined : regionById.get(gid);
        if (region) target = clampIntoRegion(target, region);
        moves.push([id, target]);
    });
    writePositions(moves);
}

// Sources join the force layout only while shown (vis-network simulates
// hidden items, so hiding alone would let invisible document hubs shape the
// layout). Writes only id + physics.
function syncSourcePhysics(force = false, onOverride = null) {
    if (!visNodes || !visEdges) return;
    // WR-03: while a layout runs, sources stay out of the simulation; settle(),
    // completeRelayout() and failRelayout() apply the toggle once it is final.
    if (relayoutBusy && onOverride === null) return;
    const on = onOverride === null ? sourcesActive() : onOverride;
    if (!force && on === sourcePhysicsOn) return;
    sourcePhysicsOn = on;
    visNodes.update([...sourceNodeIds].map(id => ({ id, physics: on })));
    const edgeUpdates = [];
    allEdges.forEach((e, i) => {
        if (isSourceEdgeRecord(e)) edgeUpdates.push({ id: edgeIdByIndex[i], physics: on });
    });
    if (edgeUpdates.length) visEdges.update(edgeUpdates);
}

function setSourcesShown(on) {
    sourcesShown = on;
    if (on) placeSources();
    for (const type of sourceTypes()) {
        if (on) activeTypes.add(type);
        else activeTypes.delete(type);
    }
    document.querySelectorAll('.legend-chip[data-type]').forEach(chip => {
        if (isSourceType(chip.getAttribute('data-type'))) setChipPressed(chip, on);
    });
    syncSourcePhysics();
    syncSourcesButton();
    filterGraph();
    const status = document.getElementById('graph-sources-status');
    if (status) {
        status.textContent = on
            ? `Sources shown: ${sourceNodeIds.size.toLocaleString()} nodes.`
            : 'Sources hidden.';
    }
}

// ---------------------------------------------------------------------------
// graph-show-types (Dashboard click-through). detail is {types: [rawType]} to
// show only that type, or {reset: true} for the default view. The payload comes
// from another module, so it is validated here: anything that does not name a
// known type with nodes falls back to the default view, never an empty graph.
// ---------------------------------------------------------------------------

// Node-hiding filters a Dashboard arrival must not inherit. Edge-only filters
// (relation types, epistemic status, confidence) and grouping are left alone.
function resetNodeFilters() {
    const search = document.getElementById('graph-search');
    if (search) search.value = '';
    const severity = document.getElementById('severity-filter');
    if (severity) severity.value = 'all';
    const slider = document.getElementById('min-degree-slider');
    const readout = document.getElementById('min-degree-value');
    if (slider) slider.value = '0';
    minDegreeThreshold = 0;
    if (readout) readout.textContent = '0';   // textContent only (SEC-01)
    if (focusStack.length > 0) exitFocus();
    // The arrival frames a new node set: the zoomed-to group no longer applies.
    clearActiveRegion();
    // Nor does the selection detail: the sidebar node (or pinned card) may now
    // be filtered out, and an open sidebar would also squeeze the caller's fit.
    pinnedCardNodeId = null;
    hideCard();
    hideSidebar();
}

// A node filter the user changes directly is newer than a Dashboard request
// still waiting (for the graph to load or for a relayout to end): the user's
// input wins and the stale request is dropped, never applied over it.
function dropPendingShowTypes() {
    pendingShowTypes = null;
}

function requestShowTypes(detail) {
    // No graph yet: keep the newest request and apply it when the graph loads.
    if (!visNodes) {
        pendingShowTypes = detail || {};
        return;
    }
    applyShowTypes(detail);
}

function flushPendingShowTypes() {
    if (pendingShowTypes === null || !visNodes) return;
    if (focusStack.length > 0 && relayoutBusy) return;
    const detail = pendingShowTypes;
    pendingShowTypes = null;
    try {
        applyShowTypes(detail);
    } catch (e) {
        console.warn('Could not apply the requested entity types:', e);
    }
}

function applyShowTypes(detail) {
    if (!visNodes) return;
    // Leaving focus needs an idle layout (exitFocus does nothing while one
    // runs): keep the request and apply it when the relayout ends.
    if (focusStack.length > 0 && relayoutBusy) {
        pendingShowTypes = detail || {};
        const waiting = document.getElementById('graph-sources-status');
        if (waiting) waiting.textContent = 'The graph is arranging; the selected type will be shown when it finishes.';
        return;
    }
    pendingShowTypes = null;

    const request = detail && typeof detail === 'object' ? detail : {};
    const requested = Array.isArray(request.types)
        ? request.types.filter(t => typeof t === 'string')
        : [];
    const entries = legendEntries();
    const known = new Set(entries.map(entry => entry.type));
    const present = new Set(allNodes.map(n => typeKey(n.entity_type)));
    const chosen = typeFilterEnabled
        ? [...new Set(requested.map(typeKey))].filter(t => known.has(t) && present.has(t))
        : [];

    resetNodeFilters();

    activeTypes.clear();
    if (chosen.length > 0) {
        for (const type of chosen) activeTypes.add(type);
    } else if (typeFilterEnabled) {
        for (const entry of entries) {
            if (!isSourceType(entry.type)) activeTypes.add(entry.type);
        }
    }
    sourcesShown = typeFilterEnabled ? sourceTypes().some(t => activeTypes.has(t)) : false;
    if (sourcesShown) placeSources();
    document.querySelectorAll('.legend-chip[data-type]').forEach(chip => {
        setChipPressed(chip, activeTypes.has(chip.getAttribute('data-type')));
    });
    syncSourcePhysics();
    syncSourcesButton();
    filterGraph();
    fitView(null, false);

    // Written last: the helpers above also write to this live region.
    let message;
    if (chosen.length > 0) {
        const count = allNodes.filter(n => chosen.includes(typeKey(n.entity_type))).length;
        const labels = entries.filter(entry => chosen.includes(entry.type)).map(entry => entry.label);
        message = `Showing ${count.toLocaleString()} ${labels.join(', ')} ${count === 1 ? 'node' : 'nodes'}. Use the legend to show other types.`;
    } else if (requested.length > 0 && typeFilterEnabled) {
        message = `No ${String(requested[0])} nodes found. Showing the default graph.`;
    } else {
        message = `Showing the default graph: ${visibleDataNodeIds().length.toLocaleString()} entities.`;
    }
    const status = document.getElementById('graph-sources-status');
    if (status) status.textContent = message;
}

function clearHighlight() {
    if (!visNodes || !visEdges) return;
    const nodeRestores = visNodes.getIds().filter(id => !isAnchorId(id)).map(id => ({ id, opacity: 1 }));
    const edgeRestores = visEdges.getIds().filter(id => !isAnchorId(id)).map(id => ({
        id, color: edgeColorObject(edgeColorById.get(id), edgeBaseOpacity()),
    }));
    visNodes.update(nodeRestores);
    visEdges.update(edgeRestores);
    highlightedNodeId = null;
    selectCenterId = null;
    selectFocus = new Set();
    scheduleFocus();
}


function buildEpistemicChips() {
    const container = document.getElementById('epistemic-toggles');
    const section = document.getElementById('epistemic-filter');
    if (!container || !section) return;

    // Collect distinct non-empty epistemic_status values
    const statusSet = new Set();
    for (const edge of allEdges) {
        const s = edge.epistemic_status;
        if (s != null && s !== '') statusSet.add(s);
    }

    // D-08: hide section entirely when no epistemic data
    if (statusSet.size === 0) {
        section.style.display = 'none';
        return;
    }

    // Colour map for known epistemic statuses (from UI-SPEC.md)
    const CHIP_COLORS = {
        asserted:      { bg: '#dcfce7', text: '#166534' },
        prophetic:     { bg: '#ede9fe', text: '#5b21b6' },
        hypothesized:  { bg: '#fef3c7', text: '#92400e' },
        contested:     { bg: '#fee2e2', text: '#991b1b' },
        contradiction: { bg: '#fecaca', text: '#7f1d1d' },
        negative:      { bg: '#f3f4f6', text: '#374151' },
        speculative:   { bg: '#e0e7ff', text: '#3730a3' },
        unknown:       { bg: '#f3f4f6', text: '#6b7280' },
    };
    const FALLBACK_COLOR = { bg: '#f3f4f6', text: '#6b7280' };

    // Reset chip container and active set
    container.innerHTML = '';   // safe: clears own controlled container, not graph data
    activeEpistemicStatuses.clear();

    for (const status of [...statusSet].sort()) {
        // D-06: all chips active by default
        activeEpistemicStatuses.add(status);

        const colors = CHIP_COLORS[status] || FALLBACK_COLOR;
        const btn = document.createElement('button');
        btn.className = 'toggle-btn epistemic-chip active';
        btn.dataset.status = status;
        btn.style.backgroundColor = colors.bg;
        btn.style.color = colors.text;
        // XSS discipline: chip label via textContent only (SEC-01 / SIDEBAR-04 pattern)
        const label = status.charAt(0).toUpperCase() + status.slice(1).replace(/_/g, ' ');
        btn.textContent = label;

        btn.addEventListener('click', () => {
            if (activeEpistemicStatuses.has(status)) {
                activeEpistemicStatuses.delete(status);
                btn.classList.remove('active');
            } else {
                activeEpistemicStatuses.add(status);
                btn.classList.add('active');
            }
            filterGraph();
        });

        container.appendChild(btn);
    }
}


function initConfidenceSlider() {
    const slider = document.getElementById('confidence-slider');
    const readout = document.getElementById('confidence-value');
    if (!slider || !readout) return;

    // D-10: default at domain minimum observed confidence; if no scored edges, use 0
    let domainMin = 0;
    let foundScored = false;
    for (const edge of allEdges) {
        const c = edge.confidence;
        if (typeof c === 'number' && isFinite(c)) {
            domainMin = !foundScored ? c : Math.min(domainMin, c);
            foundScored = true;
        }
    }

    confidenceThreshold = domainMin;
    slider.value = String(domainMin);
    readout.textContent = domainMin.toFixed(2);

    // D-11: continuous 0.01 steps; update on every input event
    // WR-02: guard against duplicate registration on repeated initConfidenceSlider() calls.
    if (!_sliderListenerAttached) {
        slider.addEventListener('input', () => {
            confidenceThreshold = parseFloat(slider.value);
            readout.textContent = confidenceThreshold.toFixed(2);  // textContent only (SEC-01)
            filterGraph();
        });
        _sliderListenerAttached = true;
    }
}


// ---------------------------------------------------------------------------
// Phase 11: Relation type dropdown (RTYPE-01, RTYPE-02)
// Mirrors buildEpistemicChips() structure. Edge-only filter (RTYPE-03 wired
// in Plan 11.3 by extending filterGraph()).
// ---------------------------------------------------------------------------
function buildRelationTypeDropdown() {
    const container = document.getElementById('relation-type-panel');
    const section = document.getElementById('relation-type-filter');
    const selectAllBtn = document.getElementById('relation-select-all');
    const clearAllBtn = document.getElementById('relation-clear-all');
    if (!container || !section) return;

    // WR-04: state reset is the FIRST mutation (D-15)
    activeRelationTypes.clear();

    // Collect distinct non-empty relation_type values
    const typeSet = new Set();
    for (const edge of allEdges) {
        const t = edge.relation_type;
        if (t != null && t !== '') typeSet.add(t);
    }

    // D-04: hide section entirely when no relation_type data
    if (typeSet.size === 0) {
        section.style.display = 'none';
        return;
    }
    section.style.display = '';

    // Reset checkbox panel (clears own controlled container, no graph data)
    container.innerHTML = '';

    const sortedTypes = [...typeSet].sort();

    for (const relType of sortedTypes) {
        // D-03: all types active on load
        activeRelationTypes.add(relType);

        const row = document.createElement('label');

        const cb = document.createElement('input');
        cb.type = 'checkbox';
        cb.checked = true;
        cb.dataset.relationType = relType;   // raw snake_case value (D-07)

        const text = document.createElement('span');
        // D-06: humanize for display only — textContent (SEC-01 invariant)
        text.textContent = relType.replace(/_/g, ' ');

        row.appendChild(cb);
        row.appendChild(text);
        container.appendChild(row);

        cb.addEventListener('change', () => {
            if (cb.checked) {
                activeRelationTypes.add(relType);
            } else {
                activeRelationTypes.delete(relType);
            }
            filterGraph();
        });
    }

    // D-14 / WR-02: guard bulk-action listener registration across rebuilds.
    // Listeners re-read the panel's checkboxes at click-time so they remain
    // correct after any subsequent buildRelationTypeDropdown() rebuild.
    if (!_relationFilterListenerAttached && selectAllBtn && clearAllBtn) {
        selectAllBtn.addEventListener('click', () => {
            const panel = document.getElementById('relation-type-panel');
            if (!panel) return;
            const boxes = panel.querySelectorAll('input[type="checkbox"][data-relation-type]');
            activeRelationTypes.clear();
            boxes.forEach(box => {
                box.checked = true;
                activeRelationTypes.add(box.dataset.relationType);
            });
            filterGraph();
        });

        clearAllBtn.addEventListener('click', () => {
            // D-05: empty set hides all relation-type edges
            const panel = document.getElementById('relation-type-panel');
            if (!panel) return;
            const boxes = panel.querySelectorAll('input[type="checkbox"][data-relation-type]');
            activeRelationTypes.clear();
            boxes.forEach(box => { box.checked = false; });
            filterGraph();
        });

        _relationFilterListenerAttached = true;
    }
}


// ---------------------------------------------------------------------------
// Phase 11: Min-degree slider (DEGREE-01)
// Mirrors initConfidenceSlider() structure. Node-only filter (wired in
// Plan 11.3 by extending filterGraph() node pass).
// ---------------------------------------------------------------------------
function initMinDegreeSlider() {
    const slider = document.getElementById('min-degree-slider');
    const readout = document.getElementById('min-degree-value');
    if (!slider || !readout) return;

    // D-10: read maxDegree from module scope (set by buildGraph())
    slider.max = String(maxDegree);
    slider.min = '0';
    slider.step = '1';
    slider.value = '0';
    minDegreeThreshold = 0;
    readout.textContent = '0';   // textContent only (SEC-01)

    // WR-02: guard against duplicate registration on repeated init calls
    if (!_degreeSliderListenerAttached) {
        slider.addEventListener('input', () => {
            dropPendingShowTypes();
            minDegreeThreshold = parseInt(slider.value, 10) || 0;
            readout.textContent = String(minDegreeThreshold);   // textContent only (SEC-01)
            filterGraph();
        });
        _degreeSliderListenerAttached = true;
    }
}
