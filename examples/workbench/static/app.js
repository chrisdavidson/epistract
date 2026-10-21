// app.js - Main application coordinator
import { initChat, loadModelSelector } from './chat.js';
import { initGraph } from './graph.js';
import { loadDisplay, legendEntries, makeSwatch } from './display.js';
import { buildDocuments, buildEntitySummary, buildEpistemicHealth } from './dashboard.js';
import { getOrigin, initSourceViewer, setDocuments } from './source_viewer.js';
// sources.js removed -- source docs now accessed via dashboard links

// SEC-01 / VUL-03: local escapeHtml helper. We intentionally do NOT import the
// copy from sources.js because that file is no longer wired into the module
// graph (see line above). DOM-based escaping handles every HTML metacharacter
// without an explicit replacement table.
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text == null ? '' : String(text);
    return div.innerHTML;
}

// ---------------------------------------------------------------------------
// Panel State -- only one panel visible at a time
// ---------------------------------------------------------------------------
let activePanel = 'chat'; // 'dashboard' | 'chat' | 'graph' | 'source'

function getActivePanel() {
    return activePanel;
}

function switchPanel(requested) {
    // 'sources' is the old name of the document viewer panel.
    const panel = requested === 'sources' ? 'source' : requested;
    activePanel = panel;

    const dashboardPanel = document.getElementById('dashboard-panel');
    const chatPanel = document.querySelector('.chat-panel');
    const sidePanel = document.getElementById('side-panel');
    const graphPanel = document.getElementById('graph-panel');
    const sourcePanel = document.getElementById('source-panel');
    // Hide all panels
    dashboardPanel.style.display = 'none';
    chatPanel.style.display = 'none';
    sidePanel.style.display = 'none';
    if (sourcePanel) sourcePanel.style.display = 'none';
    // Shows the graph filter rail (and hides the entity legend) in the sidebar.
    document.body.classList.toggle('graph-active', panel === 'graph');

    if (panel === 'dashboard') {
        dashboardPanel.style.display = 'flex';
    } else if (panel === 'chat') {
        chatPanel.style.display = 'flex';
    } else if (panel === 'source') {
        if (sourcePanel) sourcePanel.style.display = 'flex';
    } else if (panel === 'graph') {
        sidePanel.style.display = 'flex';
        sidePanel.classList.add('open');
        graphPanel.style.display = 'flex';
    }

    // The viewer is opened from the Dashboard or Chat: that nav link stays marked.
    updateNavLinks(panel === 'source' ? getOrigin() : panel);
    updatePanelTabs(panel);

    // Notify graph panel when shown (vis.js needs resize) or hidden (the
    // hover card is fixed on document.body and must not float over others).
    if (panel === 'graph') {
        window.dispatchEvent(new CustomEvent('graph-panel-opened'));
    } else {
        window.dispatchEvent(new CustomEvent('graph-panel-closed'));
    }
}

function updateNavLinks(active) {
    document.querySelectorAll('.nav-link').forEach(link => {
        link.classList.toggle('active', link.dataset.panel === active);
    });
}

function updatePanelTabs(active) {
    document.querySelectorAll('.panel-tab').forEach(tab => {
        tab.classList.toggle('active', tab.dataset.tab === active);
    });
}

// ---------------------------------------------------------------------------
// Graph filter rail -- the graph filters live in the sidebar, not above the graph
// ---------------------------------------------------------------------------
// [filter section id, accessible name, starts collapsed]. Relation types have
// no toggle of their own: the section is already a <details>.
const RAIL_SECTIONS = [
    ['entity-type-filter', 'Entity types', false],
    ['epistemic-filter', 'Epistemic status', false],
    ['confidence-filter', 'Confidence', true],
    ['relation-type-filter', null, false],
    ['min-degree-filter', 'Min. connections', true],
];
const SIDEBAR_COLLAPSED_KEY = 'epistract.sidebarCollapsed';

// Moves the graph-panel filters into the sidebar rail and the search box into
// the toolbar row. The markup stays in the graph panel of index.html because
// the static graph.html export slices that region and lays it out itself
// (static_view.js); only the element ids matter to graph.js.
function arrangeGraphRail() {
    const rail = document.getElementById('graph-filter-rail');
    const controls = document.querySelector('#graph-panel .graph-controls');
    const toolbar = controls && controls.querySelector('.graph-toolbar');
    const search = document.getElementById('graph-search');
    const legendLabel = document.getElementById('entity-legend-label');
    const entityToggles = document.getElementById('entity-toggles');
    if (!rail || !controls || !toolbar) return;

    if (search) toolbar.insertBefore(search, toolbar.firstChild);

    // The entity label and chips are loose children of .graph-controls; give
    // them a section wrapper like the other filters have.
    if (legendLabel && entityToggles) {
        const entitySection = document.createElement('div');
        entitySection.id = 'entity-type-filter';
        entitySection.append(legendLabel, entityToggles);
        controls.appendChild(entitySection);
    }

    for (const [id, name, collapsed] of RAIL_SECTIONS) {
        const filter = document.getElementById(id);
        if (!filter) continue;
        const section = document.createElement('div');
        section.className = 'rail-section';
        if (name) {
            const toggle = document.createElement('button');
            toggle.type = 'button';
            toggle.className = 'rail-section__toggle';
            toggle.setAttribute('aria-controls', id);
            toggle.addEventListener('click', () => {
                setRailSectionCollapsed(section, toggle, name, !section.classList.contains('rail-section--collapsed'));
            });
            section.appendChild(toggle);
            setRailSectionCollapsed(section, toggle, name, collapsed);
        }
        section.appendChild(filter);
        rail.appendChild(section);
    }

    const severity = document.getElementById('severity-filter');
    if (severity) rail.appendChild(severity);
}

function setRailSectionCollapsed(section, toggle, name, collapsed) {
    section.classList.toggle('rail-section--collapsed', collapsed);
    toggle.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
    toggle.setAttribute('aria-label', `${collapsed ? 'Expand' : 'Collapse'} ${name}`);
    toggle.textContent = collapsed ? '▸' : '▾';
}

// Collapses the sidebar to an icon strip on the graph panel. The choice is a
// per-viewer convenience, so storage failures are ignored.
function wireSidebarCollapse() {
    const btn = document.getElementById('sidebar-collapse-btn');
    if (!btn) return;
    let collapsed = false;
    try {
        collapsed = localStorage.getItem(SIDEBAR_COLLAPSED_KEY) === '1';
    } catch (e) { /* storage unavailable */ }

    function apply() {
        document.body.classList.toggle('sidebar-collapsed', collapsed);
        btn.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
        btn.title = collapsed ? 'Expand sidebar' : 'Collapse sidebar';
        btn.setAttribute('aria-label', btn.title);
        btn.textContent = collapsed ? '\u00BB' : '\u00AB Collapse';
    }

    btn.addEventListener('click', () => {
        collapsed = !collapsed;
        apply();
        if (presentRestore === null) {
            try {
                localStorage.setItem(SIDEBAR_COLLAPSED_KEY, collapsed ? '1' : '0');
            } catch (e) { /* storage unavailable */ }
        }
        // The graph canvas changed width; refit it to the new size.
        if (activePanel === 'graph') window.dispatchEvent(new CustomEvent('graph-panel-opened'));
    });

    // Present mode collapses the sidebar without saving that as the viewer's
    // choice; leaving it restores the state from before. graph.js refits.
    let presentRestore = null;
    window.addEventListener('graph-present-changed', (event) => {
        const on = Boolean(event.detail && event.detail.on);
        if (on && presentRestore === null) {
            presentRestore = collapsed;
            collapsed = true;
        } else if (!on && presentRestore !== null) {
            collapsed = presentRestore;
            presentRestore = null;
        }
        apply();
    });
    apply();
}

// ---------------------------------------------------------------------------
// Template-driven initialization helpers
// ---------------------------------------------------------------------------

function populatePageContent(template) {
    // Page title
    document.title = template.title || 'Knowledge Graph Explorer';
    // Sidebar title
    document.getElementById('sidebar-title').textContent = template.title || 'Workbench';
    // Welcome heading
    document.getElementById('welcome-title').textContent = 'Welcome to ' + (template.title || 'Knowledge Graph Explorer');
    // Welcome body
    const welcomeBody = document.getElementById('welcome-body');
    if (welcomeBody) {
        welcomeBody.textContent = template.subtitle
            ? 'Ask questions about ' + template.subtitle.toLowerCase() + '. Choose a starter question below or type your own.'
            : 'Ask questions about the knowledge graph. Choose a starter question below or type your own.';
    }
    // Chat placeholder
    const chatInput = document.getElementById('chat-input');
    if (chatInput) chatInput.placeholder = template.placeholder || 'Ask a question about the knowledge graph...';
}

function populateStarterCards(template) {
    const starterContainer = document.getElementById('starter-cards');
    if (!starterContainer) return;
    let starters = template.starter_questions || [];
    if (starters.length === 0) {
        starters = ['What are the main entities in this knowledge graph?'];
    }
    for (const q of starters) {
        const btn = document.createElement('button');
        btn.className = 'starter-card';
        btn.textContent = q;
        starterContainer.appendChild(btn);
    }
}

// Switches to the Graph tab first (vis needs a visible container), then asks
// graph.js to filter: detail is {types: [rawType]} or {reset: true}.
// A keyboard activation (event.detail === 0) moves focus to the graph so the
// user does not stay on a button of the hidden Dashboard.
function openGraphWith(detail, event) {
    switchPanel('graph');
    window.dispatchEvent(new CustomEvent('graph-show-types', { detail }));
    if (event && event.detail === 0) {
        const container = document.getElementById('graph-container');
        if (container) container.focus();
    }
}

// Puts a question in the chat box. Prefill only: chat.js never sends it.
function askInChat(question) {
    switchPanel('chat');
    window.dispatchEvent(new CustomEvent('ask-question', { detail: { question } }));
}

async function populateDashboard(template) {
    const dashContent = document.getElementById('dashboard-content');
    if (!dashContent) return;
    try {
        const dashResp = await fetch('/api/dashboard');
        // An error reply ({"detail": ...}) has no html or entity_counts and would
        // otherwise render the "No entities yet" empty state: show the failure.
        if (!dashResp.ok) throw new Error(`/api/dashboard returned ${dashResp.status}`);
        const dashData = await dashResp.json();
        if (dashData.html) {
            // SEC-01 / VUL-03: dashData.html may be a domain-supplied dashboard.html
            // file (trusted authorship but still HTML) OR a server-rendered string
            // mixing in entity_type values from graph_data.json (untrusted). Sanitize
            // unconditionally — DOMPurify preserves heading ids per Pitfall 1.
            dashContent.innerHTML = (typeof DOMPurify !== 'undefined')
                ? DOMPurify.sanitize(dashData.html, { ADD_ATTR: ['id'] })
                : dashData.html;
        } else {
            // Auto-generate summary. Every interpolation goes through escapeHtml —
            // `type` is an entity_type key from graph_data.json (attacker-controlled
            // when a malicious graph is loaded); `count` is numeric but coerced via
            // String() defensively.
            const safeTitle = escapeHtml(dashData.title || 'Knowledge Graph Summary');
            const safeSubtitle = dashData.subtitle ? escapeHtml(dashData.subtitle) : '';
            let autoHtml = '<h2 class="dashboard-title">' + safeTitle + '</h2>';
            if (safeSubtitle) autoHtml += '<p class="dashboard-subtitle">' + safeSubtitle + '</p>';
            // The entity section is built as DOM nodes (buildEntitySummary) after
            // this sanitized head, so its data-* and aria-label attributes survive.
            dashContent.innerHTML = (typeof DOMPurify !== 'undefined')
                ? DOMPurify.sanitize(autoHtml, { ADD_ATTR: ['id'] })
                : autoHtml;
            try {
                await loadDisplay();
            } catch (e) {
                console.warn('Could not load entity types for the dashboard:', e);
            }
            dashContent.appendChild(buildEntitySummary({
                entityCounts: dashData.entity_counts,
                totalNodes: dashData.total_nodes,
                totalEdges: dashData.total_edges,
                onSelectType: (type, event) => openGraphWith({ types: [type] }, event),
                onShowAll: (event) => openGraphWith({ reset: true }, event),
            }));
            dashContent.appendChild(buildEpistemicHealth({
                epistemic: dashData.epistemic,
                onShowInGraph: (id, event) => openGraphWith({ reset: true, focus: { id, hops: 1 } }, event),
                onAskInChat: (question) => askInChat(question),
            }));
            // The viewer module owns the 'navigate-source' event and switches panels.
            const docsSection = buildDocuments({
                documents: dashData.documents,
                onOpen: (doc) => window.dispatchEvent(
                    new CustomEvent('navigate-source', { detail: { docId: doc.doc_id } }),
                ),
            });
            if (docsSection) dashContent.appendChild(docsSection);
            setDocuments(dashData.documents);
            // Custom rule findings — per-domain CUSTOM_RULES and cross-domain
            // rules both land in claims_layer.super_domain.custom_findings.
            // Purely additive: domains that ship no custom rules get an empty
            // list from /api/dashboard and this block renders nothing.
            const findings = dashData.findings || [];
            if (findings.length) {
                let findingsHtml = '<h3>Analysis Findings</h3><div class="dashboard-table-wrap">'
                    + '<table class="dashboard-table"><thead><tr><th>Rule</th><th>Findings</th><th>By Severity</th></tr></thead><tbody>';
                for (const f of findings) {
                    const sev = Object.entries(f.by_severity || {})
                        .map(([k, v]) => k + ': ' + v).join(', ');
                    const label = f.errors
                        ? String(f.rule_name) + ' (' + f.errors + ' rule error(s))'
                        : String(f.rule_name);
                    findingsHtml += '<tr><td>' + escapeHtml(label) + '</td><td>'
                        + escapeHtml(String(f.total || 0)) + '</td><td>'
                        + escapeHtml(sev) + '</td></tr>';
                }
                findingsHtml += '</tbody></table></div>';
                const findingsBox = document.createElement('div');
                findingsBox.innerHTML = (typeof DOMPurify !== 'undefined')
                    ? DOMPurify.sanitize(findingsHtml, { ADD_ATTR: ['id'] })
                    : findingsHtml;
                dashContent.appendChild(findingsBox);
            }
        }
    } catch (e) {
        const failure = document.createElement('p');
        failure.textContent = 'Failed to load dashboard content. Reload the page to try again.';
        dashContent.replaceChildren(failure);
    }
}

async function populateEntityLegend() {
    const legendContainer = document.getElementById('entity-legend');
    if (!legendContainer) return;
    try {
        await loadDisplay();
        for (const entry of legendEntries()) {
            const item = document.createElement('div');
            item.className = 'legend-item';
            const swatch = makeSwatch(entry.type, 12);
            const label = document.createElement('span');
            label.className = 'legend-label';
            label.textContent = entry.label;
            item.replaceChildren(swatch, label);
            legendContainer.appendChild(item);
        }
    } catch (e) {
        console.warn('Could not load entity types for legend:', e);
    }
}

/**
 * Reveal the Severity sidebar legend and graph-panel filter dropdown only
 * if the current domain's epistemic layer actually produces severity-tagged
 * claims. The contracts domain (Critical/Warning/Info) does; the
 * drug-discovery domain (asserted/hypothesized/prophetic) does not.
 *
 * Default state in index.html is `display: none` for both elements, so this
 * function is purely additive — no side effects when claims_layer.json is
 * absent or has no `severity` field.
 */
async function configureSeverityVisibility() {
    const sidebarSection = document.getElementById('severity-section');
    const filterSelect = document.getElementById('severity-filter');
    if (!sidebarSection && !filterSelect) return;
    try {
        const resp = await fetch('/api/graph/claims');
        if (!resp.ok) return;
        const claims = await resp.json();
        // Walk every section of the claims payload and collect the distinct
        // severity values actually present. Sections vary by domain
        // (conflicts/gaps/risks for contracts; hypotheses/contradictions for
        // drug-discovery; findings for custom and cross-domain rules), so
        // iterate over every array we find.
        const severities = new Set();
        for (const section of Object.values(claims || {})) {
            if (!Array.isArray(section)) continue;
            for (const item of section) {
                if (item && typeof item === 'object' && item.severity) {
                    severities.add(String(item.severity));
                }
            }
        }
        if (severities.size) {
            if (sidebarSection) sidebarSection.style.display = '';
            if (filterSelect) {
                // Rebuild the option list from the severities this graph
                // actually carries. The markup ships critical/warning/info,
                // which is the contracts vocabulary; cross-domain rules grade
                // high/medium/low/advisory, and selecting an option no claim
                // uses would hide every node in the graph.
                filterSelect.replaceChildren();
                const all = document.createElement('option');
                all.value = 'all';
                all.textContent = 'All Severities';
                filterSelect.appendChild(all);
                for (const sev of [...severities].sort()) {
                    const opt = document.createElement('option');
                    opt.value = sev;
                    opt.textContent = sev.charAt(0).toUpperCase() + sev.slice(1);
                    filterSelect.appendChild(opt);
                }
                filterSelect.style.display = '';
            }
        }
    } catch (e) {
        console.warn('Could not check claims for severity field:', e);
    }
}

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------
document.addEventListener('DOMContentLoaded', async () => {
    // Check server health
    try {
        const health = await fetch('/api/health').then(r => r.json());
        console.log('Workbench health:', health);
        if (!health.has_api_key) {
            console.warn('No API key set - chat will not work');
        }
    } catch (e) {
        console.error('Server health check failed:', e);
    }

    // Fetch template for dynamic content
    let template = {};
    try {
        const templateResp = await fetch('/api/template');
        template = await templateResp.json();
    } catch (e) {
        console.warn('Could not load template, using defaults:', e);
    }

    // Populate dynamic content from template
    populatePageContent(template);
    populateStarterCards(template);
    populateDashboard(template);
    populateEntityLegend();
    configureSeverityVisibility();

    // Initialize panels with template
    // The viewer registers the 'navigate-source' listener, so it starts first.
    initSourceViewer({ switchPanel, getActivePanel, openGraphWith });
    initChat({ template });
    loadModelSelector();
    arrangeGraphRail();
    wireSidebarCollapse();
    await initGraph({ template, openChat: askInChat });
    // Sources panel removed -- docs accessible via dashboard contract links

    // Wire up sidebar nav -- each button switches to its panel
    document.querySelectorAll('.nav-link').forEach(link => {
        link.addEventListener('click', () => {
            switchPanel(link.dataset.panel);
        });
    });

    // Wire up panel tabs (graph/sources toggle within side panel)
    document.querySelectorAll('.panel-tab').forEach(tab => {
        tab.addEventListener('click', () => {
            switchPanel(tab.dataset.tab);
        });
    });

    // Hamburger menu for mobile
    const hamburger = document.getElementById('hamburger');
    const sidebar = document.getElementById('sidebar');
    if (hamburger && sidebar) {
        hamburger.addEventListener('click', () => {
            sidebar.classList.toggle('open');
        });
    }

    // Start on chat
    switchPanel('chat');
});

// Export for use by other modules
export { switchPanel, getActivePanel };
