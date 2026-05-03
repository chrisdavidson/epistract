// graph.js - Graph panel: vis.js network, search, entity type toggles

const PALETTE = ['#6366f1','#f59e0b','#ef4444','#10b981','#8b5cf6','#06b6d4','#64748b','#ec4899','#f97316','#14b8a6','#a855f7','#0ea5e9'];

let ENTITY_COLORS = {};
let network = null;
let allNodes = [];
let allEdges = [];
let visNodes = null;
let visEdges = null;
let activeTypes = new Set();
let callbacks = {};
const pinnedNodes = new Set();

function getEntityColor(type) {
    if (ENTITY_COLORS[type]) return ENTITY_COLORS[type];
    // Assign from palette by alphabetical index
    const types = [...activeTypes].sort();
    const idx = types.indexOf(type);
    return PALETTE[idx >= 0 ? idx % PALETTE.length : 0];
}

export async function initGraph(opts) {
    callbacks = opts || {};
    const template = opts.template || {};
    ENTITY_COLORS = template.entity_colors || {};

    // Build toggle buttons dynamically from entity-types API
    const toggleContainer = document.getElementById('entity-toggles');
    if (toggleContainer) {
        try {
            const entityResp = await fetch('/api/graph/entity-types');
            const entityData = await entityResp.json();
            toggleContainer.innerHTML = '';
            for (const type of Object.keys(entityData.entity_types || {})) {
                activeTypes.add(type);
                const btn = document.createElement('button');
                btn.className = 'toggle-btn active';
                btn.dataset.type = type;
                btn.style.color = getEntityColor(type);
                btn.textContent = type.charAt(0) + type.slice(1).toLowerCase().replace(/_/g, ' ');
                btn.addEventListener('click', () => {
                    if (activeTypes.has(type)) {
                        activeTypes.delete(type);
                        btn.classList.remove('active');
                    } else {
                        activeTypes.add(type);
                        btn.classList.add('active');
                    }
                    filterGraph();
                });
                toggleContainer.appendChild(btn);
            }
        } catch (e) {
            console.warn('Could not load entity types for toggles:', e);
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
        const data = await resp.json();
        allNodes = data.nodes || [];
        allEdges = data.edges || [];

        // Load claims data for severity filtering
        try {
            const claimsResp = await fetch('/api/graph/claims');
            window._claimsData = await claimsResp.json();
        } catch (e) {
            window._claimsData = null;
        }

        buildGraph();
    } catch (e) {
        console.error('Failed to load graph data:', e);
        const container = document.getElementById('graph-container');
        if (container) container.innerHTML = '<p class="graph-placeholder">No entities match the current filters. Try broadening your search or toggling entity types.</p>';
    }
}

function buildGraph() {
    const container = document.getElementById('graph-container');
    if (!container || !window.vis) return;

    // Clear placeholder
    container.innerHTML = '';

    // Pre-compute node degree (total incoming + outgoing edges) for visual sizing.
    // Range: 8px (isolated node) to 24px (highest-degree hub). See UI-SPEC Degree-Based Node Sizing.
    const degreeMap = {};
    allEdges.forEach(e => {
        degreeMap[e.source] = (degreeMap[e.source] || 0) + 1;
        degreeMap[e.target] = (degreeMap[e.target] || 0) + 1;
    });
    const maxDegree = Math.max(...Object.values(degreeMap), 1);

    const nodes = allNodes.map(n => ({
        id: n.id,
        label: n.name || n.id,
        color: getEntityColor(n.entity_type),
        title: `${n.entity_type}: ${n.name}`,
        shape: 'dot',
        size: 8 + Math.round(((degreeMap[n.id] || 0) / maxDegree) * 16),
        font: {
            size: 12,
            color: '#1a1a1a',
            background: 'rgba(255, 255, 255, 0.85)',
        },
        _data: n,
    }));

    const edges = allEdges.map(e => ({
        from: e.source,
        to: e.target,
        label: e.relation_type,
        arrows: 'to',
        font: { size: 9, color: '#888' },
        smooth: { type: 'continuous' },
        _data: e,
    }));

    visNodes = new vis.DataSet(nodes);
    visEdges = new vis.DataSet(edges);

    const options = {
        physics: {
            solver: 'barnesHut',
            barnesHut: { gravitationalConstant: -3000, springLength: 150 },
            stabilization: { iterations: 100 },
        },
        scaling: {
            label: {
                enabled: true,
                min: 8,
                max: 14,
                maxVisible: 14,
                drawThreshold: 6,
            },
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

    // Disable physics after stabilization (research pitfall 4)
    network.once('stabilized', () => {
        network.setOptions({ physics: false });
    });

    // Click node -> node popover; click edge -> edge popover (D-16)
    // Node-first ordering: vis populates params.edges with the connected
    // edges of a clicked node, so we must check nodes before edges.
    network.on('click', (params) => {
        if (params.nodes.length > 0) {
            showNodePopover(params.nodes[0], params.pointer.DOM);
        } else if (params.edges && params.edges.length > 0) {
            showEdgePopover(params.edges[0], params.pointer.DOM);
        } else {
            hideAllPopovers();
        }
    });

    // Double-click -> recenter on neighborhood (D-17)
    network.on('doubleClick', (params) => {
        if (params.nodes.length > 0) {
            const nodeId = params.nodes[0];
            const connectedNodes = network.getConnectedNodes(nodeId);
            network.fit({ nodes: [nodeId, ...connectedNodes], animation: { duration: 500 } });
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

    // Fit View: recenter all nodes in the viewport with a short animation.
    const fitBtn = document.getElementById('graph-fit-btn');
    if (fitBtn) {
        fitBtn.addEventListener('click', () => {
            network.fit({ animation: { duration: 400 } });
        });
    }

    // Reset Pins: unpin every pinned node and restore entity-type border color.
    const resetPinsBtn = document.getElementById('graph-reset-pins-btn');
    if (resetPinsBtn) {
        resetPinsBtn.addEventListener('click', () => {
            if (pinnedNodes.size === 0) return;
            const unfixUpdates = [...pinnedNodes].map(nodeId => {
                const node = allNodes.find(n => n.id === nodeId);
                const entityColor = getEntityColor(node?.entity_type || '');
                return {
                    id: nodeId,
                    fixed: false,
                    borderWidth: 1,
                    color: { border: entityColor, highlight: { border: entityColor } },
                };
            });
            visNodes.update(unfixUpdates);
            pinnedNodes.clear();
        });
    }

    // Close any open popover on window resize so it does not float
    // in a stale DOM position (RESEARCH Pitfall 4).
    window.addEventListener('resize', hideAllPopovers);
}

function filterGraph() {
    if (!visNodes) return;

    const searchTerm = (document.getElementById('graph-search')?.value || '').toLowerCase();
    const severityFilter = document.getElementById('severity-filter')?.value || 'all';

    // Build set of node IDs involved in claims of selected severity
    let severityNodeIds = null;  // null means no filter (show all)
    if (severityFilter !== 'all' && window._claimsData) {
        severityNodeIds = new Set();
        const claims = window._claimsData;
        for (const section of ['conflicts', 'gaps', 'risks']) {
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
        const typeVisible = activeTypes.has(n.entity_type);
        const searchMatch = !searchTerm || (n.name || '').toLowerCase().includes(searchTerm);
        const severityMatch = !severityNodeIds || severityNodeIds.has(n.id);
        const hidden = !(typeVisible && searchMatch && severityMatch);
        return { id: n.id, hidden };
    });

    visNodes.update(updates);

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

function showNodePopover(nodeId, position) {
    const node = allNodes.find(n => n.id === nodeId);
    if (!node) return;

    hideAllPopovers();

    const popover = document.createElement('div');
    popover.className = 'node-popover';
    popover.id = 'node-popover';
    popover.style.left = position.x + 'px';
    popover.style.top = position.y + 'px';

    // SEC-01 / VUL-02: every field below comes from graph_data.json (untrusted).
    // Build the popover via DOM API + textContent so a node name like
    // `<img src=x onerror=alert(1)>` cannot inject HTML into the workbench.
    const displayName = node.name || node.id;
    const attrs = node.attributes || {};
    const docs = node.source_documents || [];

    // Header row: <div><strong>name</strong><span class=entity-badge>type</span></div>
    const header = document.createElement('div');
    header.style.cssText = 'display:flex;justify-content:space-between;align-items:center;margin-bottom:8px';
    const nameEl = document.createElement('strong');
    nameEl.textContent = displayName;
    header.appendChild(nameEl);
    const badge = document.createElement('span');
    badge.className = 'entity-badge';
    badge.style.color = getEntityColor(node.entity_type);
    badge.textContent = node.entity_type || '';
    header.appendChild(badge);
    popover.appendChild(header);

    // Attribute key/value rows.
    const attrEntries = Object.entries(attrs).filter(([, v]) => v);
    if (attrEntries.length) {
        const attrsWrap = document.createElement('div');
        attrsWrap.className = 'node-attrs';
        for (const [k, v] of attrEntries) {
            const row = document.createElement('div');
            const labelSpan = document.createElement('span');
            labelSpan.className = 'label';
            labelSpan.textContent = k + ':';
            const dataSpan = document.createElement('span');
            dataSpan.className = 'data';
            dataSpan.textContent = ' ' + String(v);
            row.appendChild(labelSpan);
            row.appendChild(dataSpan);
            attrsWrap.appendChild(row);
        }
        popover.appendChild(attrsWrap);
    }

    // Source documents line.
    if (docs.length) {
        const docsWrap = document.createElement('div');
        docsWrap.className = 'node-docs';
        const docsLabel = document.createElement('span');
        docsLabel.className = 'label';
        docsLabel.textContent = 'Sources:';
        docsWrap.appendChild(docsLabel);
        docsWrap.appendChild(document.createTextNode(' ' + docs.join(', ')));
        popover.appendChild(docsWrap);
    }

    // Ask-about button — bind via addEventListener so the displayName never
    // crosses an HTML parser. The dispatched event detail is a plain string.
    const askBtn = document.createElement('button');
    askBtn.className = 'ask-about-btn';
    askBtn.textContent = 'Ask about this';
    askBtn.addEventListener('click', () => {
        window.dispatchEvent(new CustomEvent('ask-question', {
            detail: {
                question: 'Tell me about ' + displayName + '. What are the key details and relationships?',
            },
        }));
    });
    popover.appendChild(askBtn);

    document.getElementById('graph-panel').appendChild(popover);
    clampPopoverIntoView(popover);
}

function hideNodePopover() {
    const existing = document.getElementById('node-popover');
    if (existing) existing.remove();
}

function hideEdgePopover() {
    const existing = document.getElementById('edge-popover');
    if (existing) existing.remove();
}

function hideAllPopovers() {
    hideNodePopover();
    hideEdgePopover();
}

// Keep popovers fully inside the graph panel. Tall content like a 25-attribute
// Compound node, or a multi-mention edge popover, can overflow the viewport
// when anchored at the click point — shift it so the bottom/right edges stay
// 8px inside the panel. Vertical overflow inside the popover itself is handled
// by `max-height: 70vh; overflow-y: auto` in CSS.
function clampPopoverIntoView(popover) {
    const panel = document.getElementById('graph-panel');
    if (!panel) return;
    const panelRect = panel.getBoundingClientRect();
    const popRect = popover.getBoundingClientRect();
    const margin = 8;

    let dx = 0;
    let dy = 0;
    if (popRect.right > panelRect.right - margin) {
        dx = (panelRect.right - margin) - popRect.right;
    }
    if (popRect.bottom > panelRect.bottom - margin) {
        dy = (panelRect.bottom - margin) - popRect.bottom;
    }
    if (popRect.left + dx < panelRect.left + margin) {
        dx = (panelRect.left + margin) - popRect.left;
    }
    if (popRect.top + dy < panelRect.top + margin) {
        dy = (panelRect.top + margin) - popRect.top;
    }

    if (dx !== 0 || dy !== 0) {
        const currentLeft = parseFloat(popover.style.left) || 0;
        const currentTop = parseFloat(popover.style.top) || 0;
        popover.style.left = (currentLeft + dx) + 'px';
        popover.style.top = (currentTop + dy) + 'px';
    }
}

function showEdgePopover(edgeId, position) {
    const edgeRecord = visEdges && visEdges.get(edgeId);
    if (!edgeRecord) return;
    const edge = edgeRecord._data || {};

    hideAllPopovers();

    const popover = document.createElement('div');
    popover.className = 'edge-popover';
    popover.id = 'edge-popover';
    popover.style.left = position.x + 'px';
    popover.style.top = position.y + 'px';

    // SEC-01 / VUL-02: relation_type, evidence, source_document, and entity
    // names all originate from extracted document text. Build the popover via
    // DOM API + textContent so a quote like `<img src=x onerror=alert(1)>`
    // cannot inject HTML into the workbench.

    // Header: relation_type + epistemic_status badge.
    const header = document.createElement('div');
    header.className = 'edge-header';
    const relationEl = document.createElement('span');
    relationEl.className = 'edge-relation';
    relationEl.textContent = edge.relation_type || 'RELATION';
    header.appendChild(relationEl);

    const status = String(edge.epistemic_status || 'unknown').toLowerCase();
    const safeStatusClass = status.replace(/[^a-z0-9_-]/g, '');
    const badge = document.createElement('span');
    badge.className = 'epistemic-badge status-' + safeStatusClass;
    badge.textContent = status;
    header.appendChild(badge);
    popover.appendChild(header);

    // source -> target row.
    const sourceNode = allNodes.find(n => n.id === edge.source);
    const targetNode = allNodes.find(n => n.id === edge.target);
    const pair = document.createElement('div');
    pair.className = 'edge-pair';
    const srcStrong = document.createElement('strong');
    srcStrong.textContent = sourceNode?.name || edge.source || '';
    pair.appendChild(srcStrong);
    pair.appendChild(document.createTextNode(' → '));
    const tgtStrong = document.createElement('strong');
    tgtStrong.textContent = targetNode?.name || edge.target || '';
    pair.appendChild(tgtStrong);
    popover.appendChild(pair);

    // Multi-source view: one block per mention. This makes contested confidence
    // (e.g. semaglutide INDICATED_FOR obesity at 0.55 vs 0.97) visible at the
    // click moment instead of being averaged away.
    const mentions = Array.isArray(edge.mentions) && edge.mentions.length
        ? edge.mentions
        : [{
            source_document: edge.source_document,
            confidence: edge.confidence,
            evidence: edge.evidence,
        }];

    const mentionsHeader = document.createElement('div');
    mentionsHeader.className = 'mentions-header';
    mentionsHeader.textContent = mentions.length === 1
        ? 'Source'
        : 'Sources (' + mentions.length + ')';
    popover.appendChild(mentionsHeader);

    for (const m of mentions) {
        const block = document.createElement('div');
        block.className = 'edge-mention';

        const meta = document.createElement('div');
        meta.className = 'mention-meta';
        const docEl = document.createElement('span');
        docEl.textContent = m.source_document || '(unknown source)';
        meta.appendChild(docEl);
        const confEl = document.createElement('span');
        confEl.className = 'confidence-pill';
        const conf = typeof m.confidence === 'number' ? m.confidence : null;
        confEl.textContent = conf !== null ? conf.toFixed(2) : '—';
        meta.appendChild(confEl);
        block.appendChild(meta);

        const ev = String(m.evidence || '').trim();
        if (ev) {
            const quote = document.createElement('blockquote');
            quote.className = 'mention-evidence';
            quote.textContent = ev;
            block.appendChild(quote);
        } else {
            const empty = document.createElement('div');
            empty.className = 'mention-evidence-empty';
            empty.textContent = 'No evidence quote (typically a document-link relation)';
            block.appendChild(empty);
        }
        popover.appendChild(block);
    }

    document.getElementById('graph-panel').appendChild(popover);
    clampPopoverIntoView(popover);
}
