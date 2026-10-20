import { initSidebar, showNodeDetail, showEdgeDetail, hideSidebar } from './sidebar.js';
import {
    loadDisplay, typeDisplay, typeKey, entityColor, legendEntries, buildLegendChip,
    renderLegendMessage, isSourceType, isSourceRelation, sourceTypes, setChipPressed,
    relationDisplay, categoryEntries, makeEdgeSample,
} from './display.js';
import {
    isSourceEdge, linkDegrees, scaleBucket, labelFontSize, nodeSize, edgeWidth,
    truncateLabel, labelCutoff, stableEdgeIds, LABEL_BASE_WORLD,
    edgeDashes, edgeColorObject, EDGE_BASE_OPACITY, EDGE_DIM_OPACITY,
} from './graph_style.js';

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

const FALLBACK_SOURCE_TYPES = new Set(['DOCUMENT', 'PUBLICATION']); // used only when display data failed to load

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
let _labelUpdateTimer = null;             // pending throttled applyScaleStyle() call (260802-cu1)
let _lastStyleKey = null;                 // last-applied `${cutoff}|${bucket}`; skip DataSet writes when unchanged
let edgeColorById = new Map();            // stable edge id -> validated category color; source for every edge color write
let edgeIdByIndex = [];                   // stable vis edge id for each entry of allEdges

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
                        if (pressed) activeTypes.add(type);
                        else activeTypes.delete(type);
                        sourcesShown = sourceTypes().some(t => activeTypes.has(t));
                        if (sourcesShown) placeSources();
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
        searchInput.addEventListener('input', () => filterGraph());
    }

    // Severity filter
    const severityFilter = document.getElementById('severity-filter');
    if (severityFilter) {
        severityFilter.addEventListener('change', () => filterGraph());
    }

    // Resize handler for when panel opens
    window.addEventListener('graph-panel-opened', () => {
        if (network) {
            setTimeout(() => network.fit(), 100);
        }
    });
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

        buildGraph();
        buildEpistemicChips();
        initConfidenceSlider();
        buildRelationTypeDropdown();
        initMinDegreeSlider();
    } catch (e) {
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
// relation type stays reachable via hover tooltip + sidebar edge detail.
// ---------------------------------------------------------------------------
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
        budget = stop.maxLabels;
    }
    const cutoff = labelCutoff(sortedDegrees, budget);

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
    const nodeUpdates = visNodes.getIds().map(id => {
        const degree = linkDegreeMap[id] || 0;
        const isSource = sourceNodeIds.has(id);
        const visible = !isSource && degree >= cutoff;
        if (visible) labelled++;
        return {
            id,
            font: { ...NODE_FONT_BASE, size: visible ? fontWorld : LABEL_HIDDEN_FONT_SIZE },
            size: nodeSize(degree, maxDegree, scale, isSource),
        };
    });
    visNodes.update(nodeUpdates);

    if (visEdges) {
        const edgeUpdates = allEdges.map((e, i) => ({
            id: edgeIdByIndex[i],
            width: edgeWidth(e.support_count, scale),
            dashes: edgeDashes(e.epistemic_status, scale),
        }));
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
        sourcesShown = false;
        sourcesPlaced = false;
        for (const type of sourceTypes()) activeTypes.delete(type);
        network.destroy();
        network = null;
    }

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
    linkDegreeMap = linkDegrees(
        allEdges,
        e => isSourceEdge(e, id => sourceNodeIds.has(id), isSourceRelation),
    );
    maxDegree = Object.values(linkDegreeMap).reduce((acc, v) => Math.max(acc, v), 1);

    // 260802-cu1: descending degree list backing the label budget in
    // applyScaleStyle(). Built over allNodes, not degreeMap — degreeMap
    // omits isolated (degree-0) nodes, so indexing a budget into it would
    // silently overshoot on graphs with unconnected entities.
    sortedDegrees = allNodes
        .filter(n => !sourceNodeIds.has(n.id))
        .map(n => linkDegreeMap[n.id] || 0)
        .sort((a, b) => b - a);

    const nodes = allNodes.map(n => {
        // CR-01: Build tooltip as an HTMLElement so vis.js renders it via DOM
        // rather than innerHTML, preventing XSS from untrusted node data.
        const tooltipEl = document.createElement('div');
        tooltipEl.textContent = `${n.entity_type}: ${n.name}`;
        const d = typeDisplay(n.entity_type);
        const isSource = sourceNodeIds.has(n.id);
        return {
            id: n.id,
            label: truncateLabel(n.name || n.id),
            color: nodeColor(n.entity_type),
            borderWidth: 1,
            borderWidthSelected: 3,
            title: tooltipEl,
            shape: d.shape,
            hidden: isNodeHiddenAtBuild(n),
            size: nodeSize(linkDegreeMap[n.id] || 0, maxDegree, 1, isSource),
            font: { ...NODE_FONT_BASE, size: isSource ? LABEL_HIDDEN_FONT_SIZE : LABEL_BASE_WORLD },
            _data: n,
        };
    });

    // No text label on edges (260802-cu1 declutter) — relation_type remains
    // reachable via the vis hover tooltip default and the sidebar edge
    // detail panel (sidebar.js showEdgeDetail()), so no information is lost.
    edgeIdByIndex = stableEdgeIds(allEdges);
    edgeColorById = new Map(allEdges.map((e, i) => [
        edgeIdByIndex[i], relationDisplay(e.relation_type).color,
    ]));
    const edges = allEdges.map((e, i) => ({
        id: edgeIdByIndex[i],
        width: edgeWidth(e.support_count, 1),
        color: edgeColorObject(edgeColorById.get(edgeIdByIndex[i]), EDGE_BASE_OPACITY),
        dashes: edgeDashes(e.epistemic_status, 1),
        from: e.source,
        to: e.target,
        arrows: 'to',
        hidden: !sourcesShown && isSourceRelation(e.relation_type),
        _data: e,
    }));

    visNodes = new vis.DataSet(nodes);
    visEdges = new vis.DataSet(edges);

    // 260802-cu1: curved edges are configured once globally (below) instead
    // of per-edge, gated on edge count — above EDGE_SMOOTH_MAX_EDGES the
    // curve computation is both visual mud and a real per-frame render cost,
    // so straight edges read better at scale. Per-edge settings override the
    // global, so the per-edge `smooth` property must stay removed above.
    const edgeSmoothing = allEdges.length > EDGE_SMOOTH_MAX_EDGES ? false : { type: 'continuous' };

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
                iterations: PHYSICS_STABILIZATION_ITERATIONS,
                updateInterval: PHYSICS_STABILIZATION_UPDATE_INTERVAL,
                fit: true,
            },
            minVelocity: 0.75, // reach the stabilized event promptly once motion drops below this threshold
        },
        edges: {
            smooth: edgeSmoothing,
        },
        interaction: {
            hover: true,
            tooltipDelay: 200,
            multiselect: true,
            dragNodes: true,
            navigationButtons: false,
        },
    };

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
    let _settled = false;
    const settle = () => {
        if (_settled) return;
        _settled = true;
        network.setOptions({ physics: false });
        // Fit first so the controller reads the real fit scale, not the
        // pre-fit one (stabilization fit is animated and lags the event).
        network.fit({ animation: false });
        applyScaleStyle();
    };
    network.once('stabilizationIterationsDone', settle);
    network.once('stabilized', settle);

    // Click node -> highlight neighbourhood + sidebar; click edge -> sidebar only;
    // canvas background -> clear highlight + close sidebar. (D-01..D-04)
    network.on('click', (params) => {
        if (params.nodes.length > 0) {
            const nodeId = params.nodes[0];

            // D-02: second click on already-highlighted node clears dim; sidebar stays open
            if (highlightedNodeId === nodeId) {
                clearHighlight();
                showNodeDetail(nodeId, allNodes, allEdges, degreeMap);
                return;
            }

            // D-01: highlight this node's 1-hop neighbourhood; dim everything else
            clearHighlight();
            highlightedNodeId = nodeId;

            const neighbourIds = new Set(network.getConnectedNodes(nodeId));
            neighbourIds.add(nodeId);

            const connectedEdgeIds = new Set(network.getConnectedEdges(nodeId));

            // Dim non-neighbourhood nodes to opacity 0.15
            const nodeDims = visNodes.getIds()
                .filter(id => !neighbourIds.has(id))
                .map(id => ({ id, opacity: 0.15 }));
            if (nodeDims.length) visNodes.update(nodeDims);

            // Dim non-neighbourhood edges to opacity 0.15
            const edgeDims = visEdges.getIds()
                .filter(id => !connectedEdgeIds.has(id))
                .map(id => ({ id, color: edgeColorObject(edgeColorById.get(id), EDGE_DIM_OPACITY) }));
            if (edgeDims.length) visEdges.update(edgeDims);

            // Open sidebar (Phase 09 unchanged)
            showNodeDetail(nodeId, allNodes, allEdges, degreeMap);

        } else if (params.edges && params.edges.length > 0) {
            // D-04: edge click — sidebar only, no neighbourhood dim
            showEdgeDetail(params.edges[0], visEdges, allNodes);
        } else {
            // D-03: canvas background click — clear highlight AND close sidebar
            clearHighlight();
            hideSidebar();
        }
    });

    // Double-click -> recenter on neighborhood (D-17)
    network.on('doubleClick', (params) => {
        if (params.nodes.length > 0) {
            const nodeId = params.nodes[0];
            const connectedNodes = network.getConnectedNodes(nodeId);
            network.fit({ nodes: [nodeId, ...connectedNodes], animation: fitAnimation(500) });
        }
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
                network.fit({ animation: fitAnimation(400) });
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

        _btnListenersAttached = true;
    }

    syncSourcesButton();
    window._graphDebug = { network, visNodes, visEdges };

    // Close sidebar on window resize so it does not float
    // in a stale DOM position (RESEARCH Pitfall 4).
    // CR-02: Guard against accumulating duplicate listeners on repeated buildGraph() calls.
    if (!_resizeListenerAttached) {
        window.addEventListener('resize', hideSidebar);
        _resizeListenerAttached = true;
    }
}

function filterGraph() {
    if (!visNodes) return;
    clearHighlight();

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

    // Update node visibility
    const updates = allNodes.map(n => {
        const typeVisible = typeFilterEnabled
            ? activeTypes.has(typeKey(n.entity_type))
            : !(sourceNodeIds.has(n.id) && !sourcesShown);
        const searchMatch = !searchTerm || (n.name || '').toLowerCase().includes(searchTerm);
        const severityMatch = !severityNodeIds || severityNodeIds.has(n.id);
        // DEGREE-01: hide nodes whose linkDegree (linkDegreeMap, computed at build time
        // across ALL non-source edges, not currently visible edges) is below the threshold.
        const degreeOk = (linkDegreeMap[n.id] || 0) >= minDegreeThreshold;
        const hidden = !(typeVisible && searchMatch && severityMatch && degreeOk);
        return { id: n.id, hidden };
    });

    visNodes.update(updates);

    // Edge visibility: epistemic status filter + confidence threshold filter (FILTER-01..03)
    // D-09: confidence slider filters edges only — node visibility is not affected here
    if (visEdges) {
        // WR-01: retrieve edge source data by ID from the DataSet record (_data field)
        // rather than correlating by positional index. vis.DataSet.getIds() does not
        // guarantee insertion order, so index-based correlation can silently apply
        // the wrong filter to the wrong edge after any DataSet mutation.
        const edgeUpdates = visEdges.getIds().map(edgeId => {
            const record = visEdges.get(edgeId);
            const e = record?._data;
            if (!e) return { id: edgeId, hidden: false };

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

            return {
                id: edgeId,
                hidden: epistemicHidden || confidenceHidden || relationHidden || sourceRelHidden,
            };
        });

        visEdges.update(edgeUpdates);
    }

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
    if (sourcesPlaced || !network) return;
    sourcesPlaced = true;
    const ids = [...sourceNodeIds].sort();
    ids.forEach((id, index) => {
        const neighbourIds = [...(sourceNeighbours.get(id) || [])];
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
        network.moveNode(id, sx / n + jitterX, sy / n + jitterY);
    });
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
    syncSourcesButton();
    filterGraph();
    const status = document.getElementById('graph-sources-status');
    if (status) {
        status.textContent = on
            ? `Sources shown: ${sourceNodeIds.size.toLocaleString()} nodes.`
            : 'Sources hidden.';
    }
}

function clearHighlight() {
    if (!visNodes || !visEdges) return;
    const nodeRestores = visNodes.getIds().map(id => ({ id, opacity: 1 }));
    const edgeRestores = visEdges.getIds().map(id => ({
        id, color: edgeColorObject(edgeColorById.get(id), EDGE_BASE_OPACITY),
    }));
    visNodes.update(nodeRestores);
    visEdges.update(edgeRestores);
    highlightedNodeId = null;
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
            minDegreeThreshold = parseInt(slider.value, 10) || 0;
            readout.textContent = String(minDegreeThreshold);   // textContent only (SEC-01)
            filterGraph();
        });
        _degreeSliderListenerAttached = true;
    }
}
