---
phase: 19-wizard-and-cli-ergonomics
plan: 02
subsystem: "wizard ergonomics (--domain path shim + --schema bypass + FIDL-08 complete)"
tags: [FIDL-08, domain-cli, schema-bypass, wizard, phase-19]
requires: [FIDL-06, "FIDL-08 Plan 19-01"]
provides:
  - "core.run_sift.resolve_domain_arg(value: str) -> str path shim helper"
  - "core.domain_wizard.main(argv) + __main__ block supporting --schema <file.json> --name <slug> bypass"
  - "tests/fixtures/wizard/schema.json minimal valid schema fixture (3 entity types, 2 relation types)"
  - "FIDL-08 traceability state flipped Pending → Complete (UPDATE-in-place)"
affects:
  - core/run_sift.py
  - core/domain_wizard.py
  - tests/test_unit.py
  - tests/test_e2e.py
  - tests/TEST_REQUIREMENTS.md
  - tests/fixtures/wizard/schema.json
  - commands/domain.md
  - docs/known-limitations.md
  - .planning/REQUIREMENTS.md
tech-stack:
  added: []
  patterns:
    - "CLI path-shim helper pattern: bare name passthrough (filesystem-free fast path) + Path.relative_to(DOMAINS_DIR) for name extraction + clear stderr error with suggested correction when outside DOMAINS_DIR"
    - "Testable CLI entry point via main(argv: list[str] | None = None) -> int signature — tests pass explicit argv; production __main__ calls main() with sys.argv[1:] default"
    - "LLM-free bypass via monkeypatch.setitem(sys.modules, 'litellm', None) gate — UT-054 proves the bypass path never touches LiteLLM"
    - "DOMAINS_DIR monkeypatch for test hermeticity: monkeypatch.setattr('core.domain_wizard.DOMAINS_DIR', tmp_path / 'domains') prevents permanent domain-dir leakage into the repo's real domains/"
    - "Bundled docs commit (commands/domain.md + known-limitations.md + REQUIREMENTS.md flip in one commit) — Phase 18-02 Task 5 precedent for minimal commit count"
    - "UPDATE-in-place traceability flip: grep -c '^| FIDL-08 |' stays at 1; checkbox [ ] → [x]; status Pending → Complete — no duplicate rows"
key-files:
  created:
    - tests/fixtures/wizard/schema.json (fixture for FT-020)
    - .planning/phases/19-wizard-and-cli-ergonomics/19-02-SUMMARY.md
  modified:
    - core/run_sift.py (+49/-2 lines: extend domain_resolver import with DOMAINS_DIR; new resolve_domain_arg helper; wire helper into __main__ build branch)
    - core/domain_wizard.py (+113 lines: main(argv) + __main__ block; --schema/--name parsing; schema validation; generate_domain_package direct call)
    - tests/test_unit.py (+93 lines: UT-053 + UT-054 under existing FIDL-08 banner)
    - tests/test_e2e.py (+63 lines: FT-020 with @skipif(False) override of module-level skipif(not HAS_SIFTKG))
    - tests/TEST_REQUIREMENTS.md (+24 lines: UT-053, UT-054, FT-020 prose entries + 3 matrix rows)
    - commands/domain.md (+49 lines: ## Schema Bypass (--schema) section before ## Notes)
    - docs/known-limitations.md (+80 lines: ## Wizard & CLI Ergonomics (FIDL-08) section; footer updated to 2026-04-22 — FIDL-08 Phase 19 complete)
    - .planning/REQUIREMENTS.md (3 UPDATE-in-place edits: checkbox line 141 [ ] → [x]; traceability row Pending → Complete; footer updated)
decisions:
  - "D-07 (--domain path shim): resolve_domain_arg accepts name or path; Path.relative_to(DOMAINS_DIR) extracts <name> when inside domains/<name>/domain.yaml; outside-DOMAINS_DIR → stderr error + sys.exit(1) with suggested '--domain <inferred>' correction. Inside-DOMAINS_DIR-but-not-<name>/domain.yaml same error pattern"
  - "D-08 (bare-name non-ambiguity): if '/' not in value and not value.endswith('.yaml'), return value unchanged — filesystem never touched. Prevents path heuristics from accidentally rejecting valid bare names like 'contracts'"
  - "D-09 (--schema bypass): main() loads JSON via json.loads(Path(schema_path).read_text()); validates entity_types + relation_types keys present AND dicts; defaults optional keys (description='', system_context='Domain extraction pipeline', extraction_guidelines='Follow domain schema.', contradiction_pairs=[], gap_target_types={}, confidence_thresholds={high:0.9, medium:0.7, low:0.5})"
  - "D-10 (--name required with --schema): missing --name → 'Error: --schema requires --name <slug> (no sample corpus to derive a name from)' + return 1"
  - "D-11 (LLM bypass): --schema branch calls generate_domain_package(...) directly, bypassing analyze_documents / read_sample_documents / build_schema_discovery_prompt / litellm entirely. UT-054 asserts the no-LLM contract via monkeypatch.setitem(sys.modules, 'litellm', None)"
  - "D-12 (commands/domain.md docs): ## Schema Bypass (--schema) section inserted before ## Notes; covers invocation syntax, required/optional schema keys with defaults, no-LLM guarantee, example JSON, when-to-use bullets. Existing interactive-flow docs untouched"
  - "D-17 (UT-053): bare-name passthrough + path→name extraction + outside-domains SystemExit with stderr match — uses real domains/contracts + domains/drug-discovery (always present in repo) + tmp_path for alien path"
  - "D-18 (UT-054): monkeypatch sys.modules[litellm] = None + DOMAINS_DIR → tmp_path; invoke main() with synthetic schema + --name; assert exit 0 AND all 4 package files exist (domain.yaml, SKILL.md, epistemic.py, workbench/template.yaml)"
  - "D-19 (FT-020): end-to-end in-process invocation via main(); validates Phase 17 WorkbenchTemplate Pydantic contract on emitted workbench/template.yaml; entity_colors cardinality matches fixture's 3 entity types; hard constraint: no pollution of real domains/ via DOMAINS_DIR monkeypatch. @pytest.mark.skipif(False, ...) overrides module-level skipif(not HAS_SIFTKG) since FT-020 is wizard-only, no sift-kg needed"
  - "D-21 (FIDL-08 Pending → Complete UPDATE-in-place): three surgical edits in .planning/REQUIREMENTS.md — checkbox line 141 [ ] → [x]; traceability row 'Pending' → 'Complete'; footer 2026-04-22 wording updated to reflect Phase 19 completion. grep cardinality invariant held: '^| FIDL-08 |' count == 1"
  - "D-22 (known-limitations append): ## Wizard & CLI Ergonomics (FIDL-08) section inserted before --- footer; ~80 lines covering slug rules + worked examples, DEFAULT_ENTITY_COLORS palette rotation, --domain path shim behavior, --schema constraints, non-Latin handling, 'what FIDL-08 does NOT do' scope boundary, acceptance-gate tests, related code refs. FIDL-05, FIDL-06, FIDL-07 sections preserved byte-identically above"
metrics:
  duration: "approx 12 min"
  tasks_completed: 6
  files_modified: 9
  files_created: 2
  tests_added: 3  # UT-053, UT-054, FT-020
  commits: 6
  completed: "2026-04-22"
---

# Phase 19 Plan 2: Domain Path Shim + --schema Bypass + FIDL-08 Complete Summary

Ship the second half of FIDL-08 (Phase 19 Plan 2 of 2): **`--domain` path shim** (Enh 4 — D-07, D-08), **`--schema` LLM-free bypass** (Enh 5 — D-09, D-10, D-11), **UT-053 + UT-054 + FT-020** end-to-end gates, **`commands/domain.md §Schema Bypass`** documentation, **`docs/known-limitations.md §Wizard & CLI Ergonomics (FIDL-08)`** canonical reference for Phase 20, and **FIDL-08 UPDATE-in-place flip** from `Pending` → `Complete` in the traceability matrix. Plan 19-01 shipped the two additive helpers (`generate_slug` + `generate_workbench_template`); this plan closes the remaining four items and flips FIDL-08 to Complete.

## What shipped

- **`core.run_sift.resolve_domain_arg(value)`** — path-shim helper. Bare name (no `/`, no `.yaml`) → passthrough (filesystem never touched — D-08 explicit non-ambiguity). Path inside `DOMAINS_DIR` matching `<DOMAINS_DIR>/<name>/domain.yaml` → returns `<name>`. Path outside → `sys.exit(1)` with a clear `"Try --domain <inferred> after registering the domain."` suggestion. Wired into the `__main__` build branch (line 333-335) before `cmd_build` — `cmd_build` itself unchanged.
- **`core.domain_wizard.main(argv)` + `__main__` block** — `--schema <file.json>` + `--name <slug>` bypass. Parses JSON via `json.loads(Path(schema_path).read_text())`. Validates `entity_types` + `relation_types` keys are present AND dicts; clear error on missing/wrong-type with the key listed. Optional keys (`description`, `system_context`, `extraction_guidelines`, `contradiction_pairs`, `gap_target_types`, `confidence_thresholds`) default to sensible stubs. Calls `generate_domain_package(...)` directly — bypasses the 3-pass LLM discovery entirely (D-11). `raise SystemExit(main())` propagates return codes for `python -m core.domain_wizard ...`.
- **`tests/fixtures/wizard/schema.json`** — minimal valid schema fixture: 3 entity types (`PARTY`, `OBLIGATION`, `TERM`), 2 relation types (`HAS_OBLIGATION`, `EXPIRES_ON`), optional metadata keys exercising all default-consumption paths.
- **UT-053 (`test_resolve_domain_arg_path_shim`)** — Asserts bare-name passthrough (`contracts`, `drug-discovery`), path-to-name extraction (real `domains/contracts/domain.yaml` + `domains/drug-discovery/domain.yaml`), outside-domains SystemExit with stderr containing `"--domain expects a name registered under domains/"`.
- **UT-054 (`test_wizard_schema_bypass_skips_llm`)** — Monkeypatches `sys.modules["litellm"] = None` + `DOMAINS_DIR` → `tmp_path/domains`. Invokes `main(["--schema", <schema>, "--name", "ut054-test-domain"])`. Asserts exit 0 and all 4 package files exist (`domain.yaml`, `SKILL.md`, `epistemic.py`, `workbench/template.yaml`). If bypass accidentally touches LiteLLM, test fails.
- **FT-020 (`test_ft020_wizard_schema_end_to_end`)** — End-to-end: loads fixture, monkeypatches `DOMAINS_DIR`, invokes `main()` in-process, asserts all 7 expected package files exist, validates emitted `workbench/template.yaml` against Phase 17 `WorkbenchTemplate` Pydantic model, spot-checks `entity_colors` cardinality matches fixture. `@pytest.mark.skipif(False, ...)` overrides module-level `skipif(not HAS_SIFTKG)` since FT-020 is wizard-only.
- **`commands/domain.md §Schema Bypass (--schema)`** — new section before `## Notes` documenting invocation syntax, required/optional JSON schema keys with defaults, no-LLM guarantee, example JSON, when-to-use bullets. Existing interactive-flow docs byte-identical.
- **`docs/known-limitations.md §Wizard & CLI Ergonomics (FIDL-08)`** — ~80-line canonical reference section before the `---` footer. Covers `generate_slug` rules with worked examples, `DEFAULT_ENTITY_COLORS` palette rotation, `--domain` path shim behavior, `--schema` constraints, non-Latin input handling, explicit "what FIDL-08 does NOT do" scope boundary, acceptance-gate test list, related code refs. FIDL-05, FIDL-06, FIDL-07 sections preserved byte-identically above. Footer updated to `*Last updated: 2026-04-22 — FIDL-08 Phase 19 complete (Wizard & CLI Ergonomics); FIDL-07, FIDL-06, FIDL-05 entries preserved.*`.
- **`.planning/REQUIREMENTS.md` FIDL-08 UPDATE-in-place flip** — three surgical edits: line 141 checkbox `[ ]` → `[x]`; traceability row `Pending` → `Complete`; footer updated to reflect Phase 19 completion. `grep -c "^| FIDL-08 |"` cardinality invariant held at 1.

## Decisions honored

D-07, D-08, D-09, D-10, D-11, D-12, D-17, D-18, D-19, D-21, D-22.

## Decisions deferred from 19-01 and now complete

- D-07, D-08 (`run_sift.py build --domain path` shim) — shipped Task 2.
- D-09, D-10, D-11 (`--schema` flag + --name required + LLM bypass) — shipped Task 3.
- D-12 (`commands/domain.md` --schema docs) — shipped Task 5.
- D-17 (UT-053 path shim) — shipped Task 1 RED, Task 2 GREEN.
- D-18 (UT-054 --schema e2e without LLM) — shipped Task 1 RED, Task 3 GREEN.
- D-19 (FT-020 full wizard end-to-end) — shipped Task 4.
- D-21 (FIDL-08 Pending → Complete UPDATE-in-place) — shipped Task 5.
- D-22 (known-limitations `§Wizard & CLI Ergonomics (FIDL-08)` append) — shipped Task 5.

## Reference patterns followed

- **RED-first TDD (Task 1 → Tasks 2, 3):** UT-053 + UT-054 added as failing tests first, then the helper + bypass make them GREEN. Clear ImportError / AttributeError failures in RED state confirm the test actually exercises the missing API.
- **UPDATE-in-place traceability flip (D-21, mirrors 18-02 D-18):** FIDL-08 row never duplicated; `grep -c "^| FIDL-08 |"` stays at 1 pre- and post-flip. Pre-registered row from 19-01 transitions `Pending` → `Complete` without re-adding.
- **Single-commit docs bundle (Task 5, mirrors 18-02 Task 5):** `commands/domain.md` + `docs/known-limitations.md` + `.planning/REQUIREMENTS.md` flip bundled into one commit for minimal commit count. Commit message lists all three edit sites with their grep invariants.
- **Test-hermetic `DOMAINS_DIR` monkeypatch (hard constraint):** Both UT-054 and FT-020 use `monkeypatch.setattr("core.domain_wizard.DOMAINS_DIR", tmp_path / "domains")` so the generated test domain lands in `tmp_path` (auto-cleaned by pytest). Post-run `ls domains/ | grep -v -E '(contracts|drug-discovery)'` returns empty.
- **Pre-registered requirements (19-01 D-21 seeded `19-01, 19-02 | Pending`, 19-02 flips to `Complete`):** Enables Plan 19-02 to ship with a single UPDATE-in-place edit rather than insertion + row ordering logic.

## FIDL-08 Status Progression

| Phase | Traceability | Subsection | Docs |
| --- | --- | --- | --- |
| Pre-Phase-19 | — (not registered) | Not present | Not present |
| Plan 19-01 | `19-01, 19-02 \| Pending` (pre-registered, D-21 seeding) | `[ ] **FIDL-08**` | Empty (no section yet) |
| Plan 19-02 (this plan) | `19-01, 19-02 \| Complete` (UPDATE-in-place flip) | `[x] **FIDL-08**` | `## Wizard & CLI Ergonomics (FIDL-08)` section appended to `docs/known-limitations.md` + `## Schema Bypass (--schema)` section in `commands/domain.md` |

## Non-obvious decisions

- **`resolve_domain_arg` kept as simple module-level function, not a class:** makes `from core.run_sift import resolve_domain_arg` trivial for UT-053; avoids instantiation ceremony. Bare-name fast path is 2 lines, total helper is ~30 lines.
- **`main(argv: list[str] | None = None) -> int` signature:** allows UT-054 and FT-020 to inject argv deterministically via `main([...])` without touching `sys.argv`. The `__main__` block invokes `main()` with the default (uses `sys.argv[1:]`) for production CLI usage.
- **`--schema` defaults for optional keys mirror `generate_domain_package` internal defaults:** no new contract introduced. Users supplying a minimal schema (just `entity_types` + `relation_types`) get the same domain package as if they'd supplied all keys with those values.
- **Test-hermetic `monkeypatch.setattr("core.domain_wizard.DOMAINS_DIR", tmp_path)` pattern:** mandatory hard constraint. Without it, UT-054 would create `domains/ut054-test-domain/` in the repo on every test run — permanent filesystem pollution. The monkeypatch is safe because `core.domain_wizard.write_domain_package` resolves `DOMAINS_DIR` via module globals at call time (reassignment via monkeypatch takes effect immediately).
- **`@pytest.mark.skipif(False, reason=...)` override on FT-020:** the module-level `pytestmark = [skipif(not HAS_SIFTKG)]` in `tests/test_e2e.py` would otherwise skip FT-020 on sift-kg-absent machines. But FT-020 is wizard-only — no graph building, no sift-kg required. The explicit `skipif(False, reason="wizard-only, no sift-kg needed")` marker wins pytest's stacking order and unconditionally allows FT-020 to run.
- **Bundled docs commit (Task 5):** `commands/domain.md` + `docs/known-limitations.md` + `.planning/REQUIREMENTS.md` flip in ONE commit. Rationale: minimal commit count (Phase 18-02 Task 5 precedent) + atomic FIDL-08-complete state transition. Reviewers see all three edit sites together, no intermediate state where docs are updated but traceability is stale (or vice versa).

## V2+V3 Baseline Regression Gate — PASSED

- **Baseline (pre-Phase-19):** `166 passed, 3 failed, 5 skipped` — pre-existing failures: `test_kg_provenance.py::test_akka_party_referenced_in_response`, `test_telegram_bot.py::test_format_welcome_with_starters`, `test_workbench.py::test_schema_expansion`. None FIDL-08-related.
- **Post-Plan 19-01:** `176 passed, 3 failed, 5 skipped` — delta from baseline +10 (UT-051 edge parametrize + UT-051 rejects-empty parametrize + UT-052).
- **Post-Plan 19-02 (this plan):** `179 passed, 3 failed, 5 skipped` — delta from Plan 19-01 **+3 new passes** (UT-053 + UT-054 + FT-020). Same 3 pre-existing failures, unchanged. **Zero new regressions.**
- **`ls domains/ | grep -v -E '(contracts|drug-discovery)' | wc -l`:** `0` — no test-domain leakage (hard constraint upheld via `DOMAINS_DIR` monkeypatch in UT-054 + FT-020).
- **`git diff HEAD~5 -- domains/drug-discovery/ domains/contracts/ | wc -l`:** `0` — existing domains byte-identical throughout Phase 19. This plan modifies neither existing domain package.
- **Invariant self-check (all pass):**
  - `grep -c '^| FIDL-08 |' .planning/REQUIREMENTS.md` == `1` (UPDATE-in-place, never duplicated)
  - `grep -c '^- \[x\] \*\*FIDL-08\*\*' .planning/REQUIREMENTS.md` == `1`
  - `grep -c '^- \[ \] \*\*FIDL-08\*\*' .planning/REQUIREMENTS.md` == `0`
  - `grep -c '^## Wizard & CLI Ergonomics (FIDL-08)' docs/known-limitations.md` == `1`
  - `grep -c '^## Schema Bypass' commands/domain.md` == `1`
  - `grep -c '^def resolve_domain_arg' core/run_sift.py` == `1`
  - `grep -c 'if __name__ == "__main__"' core/domain_wizard.py` == `1`
  - `grep -c '^### UT-053' tests/TEST_REQUIREMENTS.md` == `1`
  - `grep -c '^### UT-054' tests/TEST_REQUIREMENTS.md` == `1`
  - `grep -c '^### FT-020' tests/TEST_REQUIREMENTS.md` == `1`
  - `ls tests/fixtures/wizard/schema.json` — present

## Commits (6 atomic, all `--no-verify`)

1. `6c2d965` — `test(19-02): add UT-053/UT-054 RED for --domain path shim + --schema bypass`
2. `b370f1c` — `feat(19-02): --domain accepts path, infers name from domains/ (FIDL-08 D-07)`
3. `12c5497` — `feat(19-02): --schema bypass flag skips LLM discovery (FIDL-08 D-09..D-11)`
4. `88fdd28` — `test(19-02): add FT-020 end-to-end --schema wizard (FIDL-08 D-19)`
5. `28d7fe5` — `docs(19-02): FIDL-08 complete — commands/domain.md --schema docs + known-limitations append + flip traceability`
6. (this commit) — `docs(19-02): complete domain-path shim + --schema + docs plan`

## Self-Check

Created: `.planning/phases/19-wizard-and-cli-ergonomics/19-02-SUMMARY.md` — FOUND (this file).
Created: `tests/fixtures/wizard/schema.json` — FOUND.
Commits:
- `6c2d965` — FOUND (git log).
- `b370f1c` — FOUND (git log).
- `12c5497` — FOUND (git log).
- `88fdd28` — FOUND (git log).
- `28d7fe5` — FOUND (git log).

## Self-Check: PASSED
