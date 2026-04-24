---
phase: 04-domain-aware-community-labeling
plan: "01"
subsystem: community-labeling
tags: [fda-product-labels, community-labeling, domain-config, tdd, backward-compat]
dependency_graph:
  requires: []
  provides:
    - domains/fda-product-labels/domain.yaml:community_label_anchors
    - core/label_communities.py:_anchor_label
    - core/label_communities.py:_load_domain_anchors
    - core/domain_wizard.py:generate_domain_yaml:community_label_anchors
  affects:
    - core/run_sift.py (calls label_communities — now anchor-aware for fda-product-labels)
tech_stack:
  added: []
  patterns:
    - config-driven behavior (community_label_anchors in domain.yaml drives label strategy)
    - backward-compatible optional parameter (None default — key omitted)
    - catch-all exception swallow in _load_domain_anchors for resilience
key_files:
  created:
    - domains/fda-product-labels/domain.yaml
  modified:
    - core/label_communities.py
    - core/domain_wizard.py
    - tests/test_unit.py
decisions:
  - anchor lookup walks priority list — first anchor type with any member wins (not most-frequent)
  - _load_domain_anchors swallows all exceptions and returns [] to preserve backward compat
  - _anchor_label returns None (not empty string) on no match so caller can chain with or
  - truncation at 40 chars plus ellipsis (U+2026) gives clean single-char suffix, total len 41
  - community_label_anchors omitted from YAML when None (not present when not provided)
metrics:
  duration_seconds: 299
  completed_at: "2026-04-24T00:48:37Z"
  tasks_completed: 3
  tasks_total: 3
  files_modified: 4
requirements:
  - FDA-09
---

# Phase 04 Plan 01: Domain-Aware Community Labeling Anchors Summary

Config-driven community labeling anchors: `community_label_anchors` in `domain.yaml` drives human-readable drug/ingredient labels for fda-product-labels graphs, with full backward-compatible fallback to existing `_generate_label` logic.

## What Was Built

### Task 1 — fda-product-labels domain.yaml with community_label_anchors (commit a4e1069)

Created `domains/fda-product-labels/domain.yaml` with 16 entity types, 16 relation types, and the new `community_label_anchors` top-level key as the last entry:

```yaml
community_label_anchors:
  - DRUG_PRODUCT
  - ACTIVE_INGREDIENT
  - INDICATION
  - MANUFACTURER
```

All four anchor types are defined entity types in the schema (validated by tests).

### Task 2 — Anchor-based label path in label_communities.py (commit 9fd17d2)

Added two new functions to `core/label_communities.py`:

- `_anchor_label(members, anchors) -> str | None`: Walks the priority list; first matching anchor type becomes the label source. Format rules: 1 match returns name, 2 matches returns `"A / B"`, 3+ returns `"A + N more"`. Names truncated at 40 chars with ellipsis suffix.
- `_load_domain_anchors(graph_data) -> list[str]`: Reads `metadata.domain` from graph_data, resolves domain via `core.domain_resolver.resolve_domain`, returns `community_label_anchors` list. Returns `[]` on any error (unknown domain, missing key, non-list value).

Updated `label_communities()` dispatch:

```python
domain_anchors = _load_domain_anchors(graph_data)
# in the label generation loop:
if domain_anchors:
    label = _anchor_label(members, domain_anchors) or _generate_label(members)
else:
    label = _generate_label(members)
```

### Task 3 — domain_wizard.py emits community_label_anchors (commit 05747c4)

Updated `generate_domain_yaml()` to accept `community_label_anchors: list[str] | None = None` and conditionally insert it as the last schema key before `yaml.safe_dump`. Updated `generate_domain_package()` with the same optional parameter, passing it through to `generate_domain_yaml()`. All existing callers remain unaffected (parameter defaults to `None`).

## Test Results

```
12 test_fda09_* tests — 12 passed, 0 failed
Full regression — 108 passed, 2 skipped, 0 failed
```

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None. The anchor labeling path is fully wired: `domain.yaml` -> `_load_domain_anchors()` -> `_anchor_label()` -> label output.

## Threat Flags

No new network endpoints, auth paths, file access patterns, or schema changes at trust boundaries beyond those documented in the plan's threat model. T-04-02 (exception swallowing) and T-04-03 (non-list guard) mitigations are implemented as specified.

## Self-Check: PASSED

| Item | Result |
|------|--------|
| domains/fda-product-labels/domain.yaml | FOUND |
| core/label_communities.py | FOUND |
| core/domain_wizard.py | FOUND |
| commit a4e1069 (Task 1) | FOUND |
| commit 9fd17d2 (Task 2) | FOUND |
| commit 05747c4 (Task 3) | FOUND |
