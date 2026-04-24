---
phase: 05-workbench-visualization-enhancements
plan: "02"
subsystem: workbench-graph-panel
tags: [vis-network, node-pinning, drag-to-pin, fit-view, reset-pins, toolbar, resize-handler]
dependency_graph:
  requires: [05-01]
  provides: [node-pinning, graph-toolbar, fit-view-button, reset-pins-button, resize-popover-cleanup]
  affects: [examples/workbench/static/graph.js, examples/workbench/static/index.html, examples/workbench/static/style.css]
tech_stack:
  added: []
  patterns: [vis-network-dragEnd-pinning, vis-network-DataSet-immutable-update, vis-network-fit-animation]
key_files:
  created: []
  modified:
    - examples/workbench/static/graph.js
    - examples/workbench/static/index.html
    - examples/workbench/static/style.css
decisions:
  - "pinnedNodes is a module-scope const Set (not function-scope) to match existing allNodes/allEdges/network module-scope pattern"
  - "Accent color #4a6cf7 hardcoded as string literal (not getComputedStyle) per UI-SPEC line 95 for performance and cross-browser safety"
  - "canvas pan guard uses params.nodes.length === 0 check to prevent phantom pins on empty-canvas drags (RESEARCH Pitfall 2)"
  - "visNodes.update([...]) used exclusively — direct visNodes._data mutation avoided (RESEARCH Pitfall 3 / T-05-04 mitigate)"
metrics:
  duration: "~8 minutes"
  completed: "2026-04-24"
  tasks_completed: 2
  tasks_total: 3
  files_modified: 3
---

# Phase 05 Plan 02: Interactive Node Pinning and Graph Toolbar Summary

**One-liner:** Drag-to-pin with 2px accent border feedback, Fit View + Reset Pins toolbar buttons, and window-resize popover cleanup added to the workbench graph panel via vis-network dragEnd/fit/DataSet APIs.

---

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Add .graph-toolbar HTML row and CSS rule | 7e4743b | examples/workbench/static/index.html, examples/workbench/static/style.css |
| 2 | Add pinnedNodes Set, dragEnd handler, toolbar click handlers, resize handler | 02633ff | examples/workbench/static/graph.js |

---

## What Was Built

### Task 1: HTML Toolbar Row + CSS Rule

Added a `.graph-toolbar` div as the last child of `.graph-controls` in `index.html`:

```html
<div class="graph-toolbar">
  <button class="toggle-btn active" id="graph-fit-btn" title="Fit all nodes in view">Fit View</button>
  <button class="toggle-btn active" id="graph-reset-pins-btn" title="Unpin all dragged nodes">Reset Pins</button>
</div>
```

Added `.graph-toolbar` CSS rule in `style.css` after `.severity-filter` block:

```css
.graph-toolbar {
  display: flex;
  gap: var(--space-xs);
  flex-wrap: wrap;
}
```

Buttons reuse the existing `.toggle-btn.active` class — no new CSS custom properties introduced.

### Task 2: graph.js Event Handlers + State

Added module-scope `pinnedNodes` Set after `let callbacks = {}`:

```javascript
const pinnedNodes = new Set();
```

Added `dragEnd` handler inside `buildGraph()` after the `doubleClick` handler:
- Guards against canvas pans via `params.nodes.length === 0` check (RESEARCH Pitfall 2)
- Marks dragged nodes fixed (`{ x: true, y: true }`) and paints 2px `#4a6cf7` border
- Uses `visNodes.update([...])` immutable pattern (RESEARCH Pitfall 3)

Added Fit View click handler:
- Calls `network.fit({ animation: { duration: 400 } })` on `#graph-fit-btn` click

Added Reset Pins click handler:
- Early-returns if `pinnedNodes.size === 0`
- Restores each pinned node's entity-type border color via `getEntityColor(node?.entity_type || '')`
- Calls `visNodes.update(unfixUpdates)` then `pinnedNodes.clear()`

Added window resize handler:
- `window.addEventListener('resize', hideNodePopover)` closes stale popovers on resize (RESEARCH Pitfall 4)

Final file: 339 LOC (under 350 ceiling). Stabilization, click, and doubleClick handlers preserved unmodified.

---

## Deviations from Plan

None — plan executed exactly as written. All four edits were additive; no existing handlers or node-config fields were modified.

---

## Known Stubs

None. All event handlers wire to live vis-network APIs and the DOM elements created in Task 1. No placeholder values, empty arrays, or TODO markers introduced.

---

## Threat Flags

None. No new network endpoints, auth paths, file access patterns, or schema changes introduced. The `pinnedNodes` Set holds vis-network internal node IDs (not user-typed input). The `visNodes.update()` immutable pattern satisfies T-05-04 mitigation. The `hideNodePopover()` resize handler calls the existing escape function without touching popover content, satisfying T-05-06.

---

## Self-Check

### Files exist

- [x] `examples/workbench/static/index.html` — modified (graph-toolbar div confirmed at line 107)
- [x] `examples/workbench/static/style.css` — modified (.graph-toolbar rule confirmed)
- [x] `examples/workbench/static/graph.js` — modified (339 LOC, all acceptance criteria grep checks pass)

### Commits exist

- [x] 7e4743b — Task 1: HTML toolbar row + CSS rule
- [x] 02633ff — Task 2: pinnedNodes Set + dragEnd + toolbar handlers + resize handler

## Self-Check: PASSED

---

## Checkpoint Status

**Task 3 (human-verify) reached.** Execution paused for human smoke-test. See checkpoint message for the 11-step verification procedure.
