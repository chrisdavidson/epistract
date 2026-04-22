---
phase: 19-wizard-and-cli-ergonomics
plan: 01
subsystem: "wizard ergonomics (safe slugification + auto-emit workbench/template.yaml)"
tags: [FIDL-08, slug, workbench-template, domain-wizard, phase-19]
requires: [FIDL-06]
provides:
  - "core.domain_wizard.generate_slug(name: str) -> str"
  - "core.domain_wizard.generate_workbench_template(domain_slug, entity_types) -> str"
  - "core.domain_wizard.DEFAULT_ENTITY_COLORS (12-entry vis.js-friendly palette)"
  - "core.domain_wizard.write_domain_package workbench_yaml= keyword-only kwarg"
  - "core.domain_wizard.generate_domain_package auto-emission of workbench/template.yaml in files_written"
affects:
  - core/domain_wizard.py
  - tests/test_unit.py
  - tests/TEST_REQUIREMENTS.md
tech-stack:
  added: []
  patterns:
    - "NFKD Unicode normalization + ASCII-ignore for accent/CJK stripping — stdlib pattern, no new dependency"
    - "Deterministic palette rotation: sort entity_type keys alphabetically, cycle DEFAULT_ENTITY_COLORS via modulo (palette[i % len])"
    - "Complete-override YAML emission (every WorkbenchTemplate field populated) so downstream consumers never fall back to Pydantic defaults"
    - "Keyword-only kwarg addition preserves positional-arg back-compat for write_domain_package (existing 6 positional args unchanged)"
    - "Belt-and-suspenders slug normalization: re.sub(r'[^a-z0-9]+', '-') followed by re.sub(r'-+', '-') defends against regex drift"
key-files:
  created:
    - .planning/phases/19-wizard-and-cli-ergonomics/19-01-SUMMARY.md
  modified:
    - core/domain_wizard.py (+136/-2 lines: imports re/unicodedata; DEFAULT_ENTITY_COLORS; generate_slug; generate_workbench_template; write_domain_package workbench_yaml kwarg; generate_domain_package wiring)
    - tests/test_unit.py (+95 lines: UT-051 edge-case parametrize, UT-051 rejects-empty parametrize, UT-052 template shape)
    - tests/TEST_REQUIREMENTS.md (+32 lines: Phase 19 section before Traceability Matrix + 2 matrix rows)
decisions:
  - "D-01: generate_slug rules — NFKD + ASCII-ignore, lowercase, non-alnum runs → single '-', strip leading/trailing '-', collapse '--+' defensive pass, raise ValueError on empty/malformed"
  - "D-02: replace line 925 bug site domain_name.lower().replace(' ', '-') with generate_slug(domain_name). grep 'lower().replace(\" \", \"-\")' in core/ == 0"
  - "D-03: post-condition — generate_slug return value satisfies result == result.strip('-'), '--' not in result, all chars in [a-z0-9-]. UT-051 asserts invariants on every successful case"
  - "D-04: generate_workbench_template emits complete WorkbenchTemplate YAML with deterministic 12-color palette rotation (alphabetical sort → modulo cycle). UT-052 locks palette[0:3] = ['#97c2fc', '#ffa07a', '#90ee90'] for Bar/Baz/Foo"
  - "D-05: write_domain_package gains keyword-only workbench_yaml= kwarg. When None, byte-identical to Phase 18 behavior — zero regression for external callers. When provided, creates workbench/ subdir and writes template.yaml"
  - "D-06: generate_domain_package calls generate_slug first, then generate_workbench_template(dir_name, entity_types), then passes workbench_yaml= to write_domain_package. files_written gains workbench/template.yaml as 7th entry"
  - "D-14: backward-compat byte-identity for existing domains — generate_slug('drug-discovery') == 'drug-discovery', generate_slug('contracts') == 'contracts'. git diff HEAD~3 -- domains/drug-discovery/ domains/contracts/ == empty"
  - "D-15: UT-051 locks the D-15 edge table (Q&A, whitespace, multi--dash, existing domains, non-ASCII, empty/whitespace ValueError) via @pytest.mark.parametrize — 9 test IDs total"
  - "D-16: UT-052 gates against Phase 17 WorkbenchTemplate Pydantic contract; asserts shape, cardinality, deterministic palette, required analysis_patterns + dashboard keys, byte-identical repeat calls"
deferred:
  - "D-07, D-08: `run_sift.py build --domain path` shim (Plan 19-02)"
  - "D-09, D-10, D-11, D-12: `/epistract:domain --schema <file.json> --name <slug>` flag + docs (Plan 19-02)"
  - "D-17: UT-053 (--domain path shim) — Plan 19-02"
  - "D-18: UT-054 (--schema end-to-end) — Plan 19-02"
  - "D-19: FT-020 (full /epistract:domain --schema → ingest pipeline) — Plan 19-02"
  - "D-21: FIDL-08 Pending → Complete traceability flip (Plan 19-02)"
  - "D-22: docs/known-limitations.md §Wizard & CLI Ergonomics (FIDL-08) append (Plan 19-02)"
metrics:
  duration: "approx 10 min"
  tasks_completed: 4
  files_modified: 3
  files_created: 1
  tests_added: 10  # 6 UT-051 parametrize + 3 UT-051-rejects parametrize + 1 UT-052
  commits: 4
  completed: "2026-04-22"
---

# Phase 19 Plan 1: Safe Slugification + Auto-Emit workbench/template.yaml Summary

Ship the first half of FIDL-08 (Phase 19 Plan 1 of 2): **safe slugification** (Bug 5) and **wizard auto-emission of `workbench/template.yaml`** (Enhancement 1). Two new module-level helpers in `core/domain_wizard.py` — `generate_slug(name)` and `generate_workbench_template(domain_slug, entity_types)` — plus a keyword-only `workbench_yaml=` parameter on `write_domain_package` and its invocation site in `generate_domain_package`. Two new RED-first unit tests (UT-051 slug edge cases, UT-052 template shape) pin the behavior. Pre-registered UT-051 and UT-052 in `tests/TEST_REQUIREMENTS.md` under a new Phase 19 / FIDL-08 section with Traceability Matrix rows.

## What shipped

- **`generate_slug(name: str) -> str`** — Safe slugifier: NFKD → ASCII → lowercase → `[^a-z0-9]+ → -` → strip → collapse `--+ → -` → `ValueError` on empty/malformed. Fixes the line-925 bug `domain_name.lower().replace(" ", "-")` that produced invalid directory names for common inputs like `"Q&A Analysis (v2)"`.
- **`generate_workbench_template(domain_slug, entity_types) -> str`** — Deterministic YAML emitter for `domains/<slug>/workbench/template.yaml`. Complete override against the Phase 17 `WorkbenchTemplate` Pydantic contract with 12-color palette rotation (alphabetical sort → modulo cycle).
- **`DEFAULT_ENTITY_COLORS`** — 12-entry vis.js-friendly palette; order locked by UT-052 (indices 0, 1, 2 explicitly asserted).
- **`write_domain_package` keyword-only `workbench_yaml=` kwarg** — Optional addition; when None, byte-identical to Phase 18 behavior (external-caller back-compat). When provided, creates `workbench/` subdir and writes `template.yaml`.
- **`generate_domain_package` wiring** — Replaces line-925 bug site with `generate_slug(domain_name)`, calls `generate_workbench_template(dir_name, entity_types)`, threads YAML through `write_domain_package(..., workbench_yaml=...)`, and lists `workbench/template.yaml` as the 7th entry in `files_written`.
- **UT-051 (9 parametrized test IDs)** — Edge table (Q&A, whitespace, multi--dash, drug-discovery, contracts, Chinese+Latin) + rejects-empty (empty string, whitespace-only, tabs/newlines).
- **UT-052 (1 test)** — `WorkbenchTemplate.model_validate` gate + entity_colors cardinality + deterministic palette assignment + required `analysis_patterns` / `dashboard` keys + byte-identical repeat calls.

## Decisions honored

D-01 (slug rules), D-02 (replace bug site), D-03 (post-condition assertion), D-04 (workbench template emitter + palette), D-05 (write_domain_package workbench_yaml kwarg), D-06 (generate_domain_package wiring + files_written), D-14 (backward-compat byte-identity for existing domains), D-15 (UT-051), D-16 (UT-052).

## Deferred to Plan 19-02

D-07, D-08 (`run_sift.py build --domain path` shim), D-09, D-10, D-11, D-12 (`--schema` flag + docs), D-17 (UT-053 path shim), D-18 (UT-054 --schema e2e), D-19 (FT-020 end-to-end), D-21 (FIDL-08 Pending → Complete flip), D-22 (known-limitations append).

## Commits (4 atomic, all `--no-verify`)

1. `bb37370` — `docs(19-01): register FIDL-08 traceability + UT-051/UT-052`
2. `bc4b3b7` — `test(19-01): add UT-051/UT-052 RED for FIDL-08 slug + workbench template`
3. `6785246` — `feat(19-01): safe slugification + auto-emit workbench/template.yaml (FIDL-08 D-01, D-04)`
4. (this commit) — `docs(19-01): complete slug + workbench template plan`

## V2 regression gate

- **Baseline (pre-Phase-19):** `166 passed, 3 failed, 5 skipped` — pre-existing failures: `test_kg_provenance.py::test_akka_party_referenced_in_response`, `test_telegram_bot.py::test_format_welcome_with_starters`, `test_workbench.py::test_schema_expansion`. None FIDL-08-related.
- **Post-Plan 19-01:** `176 passed, 3 failed, 5 skipped` — delta +10 new passes (6 UT-051 edge + 3 UT-051-rejects + 1 UT-052). Same 3 pre-existing failures, unchanged. **Zero new regressions.**
- **Existing-domain byte-identity:** `git diff HEAD~3 -- domains/drug-discovery/ domains/contracts/` returns empty diff — this plan does NOT modify any existing domain package. The new `workbench/template.yaml` emission only runs when the wizard is invoked to create a NEW domain.
- **Helper invariants (all pass):**
  - `grep -c '^def generate_slug' core/domain_wizard.py` == 1
  - `grep -c '^def generate_workbench_template' core/domain_wizard.py` == 1
  - `grep -c '^DEFAULT_ENTITY_COLORS' core/domain_wizard.py` == 1
  - `grep -c 'lower().replace(" ", "-")' core/domain_wizard.py` == 0 (bug site eliminated)
  - `grep -rn 'lower().replace(" ", "-")' core/ domains/ examples/` == 0 matches
- **Traceability state unchanged:** `.planning/REQUIREMENTS.md §v3` FIDL-08 row remains `| FIDL-08 | Phase 19 | 19-01, 19-02 | Pending |`. `grep -c '^| FIDL-08 |' .planning/REQUIREMENTS.md` == 1. Plan 19-02 will flip to Complete.

## Handoff to Plan 19-02

Plan 19-02 picks up:
1. `core/run_sift.py` `--domain path` shim — resolves `/abs/path/domains/<name>/domain.yaml` to `<name>`; clear error for outside-`domains/` paths (D-07, D-08). UT-053 gates this.
2. `/epistract:domain --schema <file.json> --name <slug>` flag — bypasses the 3-pass LLM discovery entirely; loads entity/relation types directly from JSON (D-09, D-10, D-11). UT-054 + FT-020 gate this.
3. `commands/domain.md` docs update for `--schema` flag (D-12).
4. `docs/known-limitations.md §Wizard & CLI Ergonomics (FIDL-08)` append (D-22).
5. FIDL-08 Pending → Complete flip in `.planning/REQUIREMENTS.md §v3` (D-21).

## Self-Check

Created: `.planning/phases/19-wizard-and-cli-ergonomics/19-01-SUMMARY.md` — FOUND (this file).
Commits:
- `bb37370` — FOUND (git log).
- `bc4b3b7` — FOUND (git log).
- `6785246` — FOUND (git log).

## Self-Check: PASSED
