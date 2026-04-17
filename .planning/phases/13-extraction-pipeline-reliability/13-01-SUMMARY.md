---
phase: 13-extraction-pipeline-reliability
plan: 01
subsystem: extraction-pipeline
tags: [pydantic, document-extraction, provenance, cli, sift-kg, extraction-contract]

# Dependency graph
requires:
  - phase: 13-extraction-pipeline-reliability
    provides: FIDL-02c requirement row + traceability entry (Plan 13-00 Wave 0 scaffolding)
  - phase: 12-extend-epistemic-classifier-with-structural-biology-document-signature
    provides: HAS_SIFT_READER guard pattern + loud-failure posture over silent garbage
provides:
  - Write-time DocumentExtraction Pydantic validation in build_extraction.py (D-06)
  - Honest provenance threading via --model / --cost / EPISTRACT_MODEL env (D-07, D-08)
  - Extended _normalize_fields coercion of schema drift (D-03 subset for build_extraction layer)
  - HAS_SIFT_EXTRACTION_MODEL availability flag mirroring HAS_SIFT_READER
  - sys.path bootstrap so `python3 core/build_extraction.py` works as a plain script (agent invocation path)
  - 8 new unit tests: UT-022a, UT-024, UT-025, UT-026, UT-027, UT-028, UT-029, UT-030
affects:
  - 13-02-PLAN.md (normalize_extractions module will share _normalize_fields coercion rules established here)
  - 13-03-PLAN.md (extractor.md update can reference --model / --cost / EPISTRACT_MODEL contract)
  - 13-04-PLAN.md (e2e tests will benefit from the write-time raise that stops silent drops)
  - agents/extractor.md (consumer of build_extraction.py CLI — now gains --model / --cost flags)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - HAS_SIFT_EXTRACTION_MODEL optional-dep guard mirrors HAS_SIFT_READER from core/ingest_documents.py
    - Write-time Pydantic validation with sift-kg-default substitution for honest-null provenance fields
    - sys.argv CLI pattern extended with --model / --cost flags (no argparse migration)
    - from __future__ import annotations + str | None syntax per project convention

key-files:
  created: []
  modified:
    - core/build_extraction.py
    - tests/test_unit.py

key-decisions:
  - "Validated payload uses sift-kg defaults (0.0 / \"\") for None provenance during Pydantic check, but on-disk JSON preserves honest null — the sift-kg DocumentExtraction model rejects None on model_used/cost_usd even though the plan contract requires writing null to disk when unknown. Validation is about required-field enforcement (document_id, entity_type, etc.), not about dictating provenance nullability."
  - "Added sys.path bootstrap in build_extraction.py so extractor agents can invoke it as a plain script via absolute path (`python3 ${CLAUDE_PLUGIN_ROOT}/core/build_extraction.py`). Pre-existing latent bug surfaced by the subprocess-based UT-026..UT-030 tests; fixed per Rule 3 (blocking)."
  - "_normalize_fields uses `if ... not in e` rather than setdefault for context/attributes/evidence so the mutation is explicit and matches the existing coercion style for type→entity_type mapping."

patterns-established:
  - "Provenance fields honest: --flag → env var → null. Hardcoded model/cost strings are a lie; null is the honest unknown."
  - "Write-time contract enforcement: DocumentExtraction(**payload) raises inside write_extraction so sift-kg builder's silent skip (logger.warning; continue) never sees malformed input. Problem surfaces at agent call, not 30 min later."
  - "Separate validation payload from on-disk payload when upstream schema and downstream contract disagree on nullability."

requirements-completed:
  - FIDL-02c

# Metrics
duration: 6min
completed: 2026-04-17
---

# Phase 13 Plan 01: Write-Time Validation + Honest Provenance Summary

**DocumentExtraction Pydantic validation wired into build_extraction.write_extraction so agent-malformed payloads raise ValueError at disk-write time; hardcoded `claude-opus-4-6` / `0.0` replaced with --model / --cost / EPISTRACT_MODEL / null pipeline.**

## Performance

- **Duration:** ~6 min
- **Started:** 2026-04-17T12:17:49Z
- **Completed:** 2026-04-17T12:23:38Z
- **Tasks:** 3
- **Files modified:** 2 (`core/build_extraction.py`, `tests/test_unit.py`)

## Accomplishments

- Write-time contract enforcement: `DocumentExtraction(**extraction)` inside `write_extraction` raises `ValueError` with full Pydantic field-by-field detail on malformed input. Stops silent drop at sift-kg builder source (`sift_kg/graph/builder.py:308-313` `logger.warning; continue`).
- Provenance honesty: hardcoded `"cost_usd": 0.0` and `"model_used": "claude-opus-4-6"` removed. Sourcing: `--model` flag → `EPISTRACT_MODEL` env → `null`; `--cost` flag → `null`.
- Schema-drift coercion extended in `_normalize_fields`: numeric-string confidence → float, unparseable-string confidence → 0.5 Pydantic default, missing `context` / `evidence` → `""`, missing `attributes` → `{}`.
- 8 new unit tests (UT-022a + UT-024..UT-030) all green. UT-012 regression still green.
- CLI invocation path fixed: `python3 core/build_extraction.py ...` now works as a plain script (sys.path bootstrap for the `core.domain_resolver` import the extractor agents rely on).

## Task Commits

Each task was committed atomically:

1. **Task 1: Extend _normalize_fields + DocumentExtraction guard** — `02a7a52` (feat)
2. **Task 2: Write-time Pydantic validation in write_extraction** — `b93ff32` (feat)
3. **Task 3: --model / --cost / EPISTRACT_MODEL provenance threading** — `a98b6a4` (feat)

_(Interleaved with 13-00 parallel-executor commits `bfa62a7`, `6c561ba`, `7d9526c`, `58b6c80`, `4bd2fed` — not owned by this plan.)_

## Files Created/Modified

### Modified
- `core/build_extraction.py` — HAS_SIFT_EXTRACTION_MODEL guard, `from __future__ import annotations`, sys.path bootstrap, extended `_normalize_fields`, new `write_extraction` kwargs `model_used` / `cost_usd`, write-time Pydantic validation block with None→default substitution, CLI `--model` / `--cost` parsing with `EPISTRACT_MODEL` env fallback. Output JSON uses honest `null` for unknown provenance.
- `tests/test_unit.py` — +167 lines under new "Phase 13 — FIDL-02c" section:
  - `test_normalize_coerces_schema_drift` (UT-022a)
  - `test_build_extraction_raises_on_missing_doc_id` (UT-024 — direct Pydantic + wrapped ValueError)
  - `test_build_extraction_raises_on_invalid_entity` (UT-025)
  - `test_build_extraction_threads_model_flag` (UT-026, subprocess)
  - `test_build_extraction_reads_model_env` (UT-027, subprocess with EPISTRACT_MODEL env)
  - `test_build_extraction_threads_cost_flag` (UT-028, subprocess + `pytest.approx(0.0123)`)
  - `test_build_extraction_no_hardcoded_model` (UT-029, subprocess asserts `model_used is None`)
  - `test_build_extraction_no_hardcoded_cost` (UT-030, subprocess asserts `cost_usd is None`)

## Decisions Made

- **None→default substitution during validation.** The sift-kg `DocumentExtraction` Pydantic model (verified via `model_json_schema()`) declares `cost_usd: float = 0.0` and `model_used: str = ""` — non-nullable. But D-07/D-08 require honest `null` on disk when unknown. Chose to validate a sanitized copy (`_validation_payload`) with defaults substituted for `None`, and write the original dict with honest `null` to disk. Validation's purpose is required-field enforcement (document_id, entity_type, etc.), not dictating provenance nullability.
- **sys.path bootstrap in module preamble** rather than tests-set-PYTHONPATH. Extractor agents invoke `python3 ${CLAUDE_PLUGIN_ROOT}/core/build_extraction.py` (absolute path, no PYTHONPATH). The `from core.domain_resolver import resolve_domain` import requires PROJECT_ROOT on sys.path. Adding the bootstrap inside the module makes the script self-contained and the tests mirror the real invocation path.
- **Followed plan-prescribed tests verbatim** for UT-022a through UT-030. Only two deviations from plan text — both required by newly-observed behavior (see below).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] sift-kg DocumentExtraction rejects `None` on model_used / cost_usd**
- **Found during:** Task 3 (--model / --cost threading)
- **Issue:** The plan says `model_used` and `cost_usd` should be `null` (Python `None`) in the output JSON when unknown. But the sift-kg `DocumentExtraction` Pydantic model declares them as `float` and `str` with non-null defaults — passing `None` raises `pydantic_core._pydantic_core.ValidationError`. Task 3 tests (UT-029, UT-030) assert `out["model_used"] is None` and `out["cost_usd"] is None`, so we cannot short-circuit validation when provenance is None.
- **Fix:** Build a separate `_validation_payload = dict(extraction)` and substitute sift-kg defaults (`0.0` / `""`) only in the validation copy. The on-disk JSON still serialises `null` per plan contract.
- **Files modified:** `core/build_extraction.py` (validation block only)
- **Verification:** UT-029 and UT-030 both assert `None` in output JSON and pass; UT-024 still catches missing document_id (validation logic intact).
- **Committed in:** `a98b6a4` (Task 3 commit)

**2. [Rule 3 - Blocking] `python3 core/build_extraction.py ...` fails with ModuleNotFoundError for `core.domain_resolver`**
- **Found during:** Task 3 (subprocess-based tests UT-026..UT-030)
- **Issue:** Running `build_extraction.py` directly from the project root (as extractor agents do via absolute path) fails with `ModuleNotFoundError: No module named 'core.domain_resolver'` because Python does not add cwd to sys.path when invoking a script file. Pre-existing latent bug — the scenario-06 notes in `tests/scenarios/scenario-06-glp1-landscape-v2.md:92` already documented S6 extractor agents needing `python3 -m core.build_extraction` as a workaround. Task 3's subprocess tests exercise the normal path and surface the bug.
- **Fix:** Added a 5-line sys.path bootstrap before the `from core.domain_resolver import resolve_domain` import — inserts `Path(__file__).resolve().parent.parent` onto `sys.path` if not already present. Works as both a plain script (`python3 core/build_extraction.py ...`) and a module import (no effect — path already present).
- **Files modified:** `core/build_extraction.py` (lines 18-23)
- **Verification:** All 5 subprocess tests (UT-026..UT-030) pass from project root without PYTHONPATH set. Existing import path `from build_extraction import write_extraction` in tests/conftest-sys.path chain still works (bootstrap is idempotent).
- **Committed in:** `a98b6a4` (Task 3 commit)

---

**Total deviations:** 2 auto-fixed (1 Rule 1 bug, 1 Rule 3 blocking)
**Impact on plan:** Both fixes necessary for the plan's own tests to pass. No scope creep — the validation-null substitution is a faithful interpretation of D-06 + D-07/D-08 read together; the sys.path bootstrap just makes the extractor-agent invocation path work the same as module import.

## Issues Encountered

- **sift-kg model declares non-nullable provenance fields** — Discovered by running the Task 3 tests. Documented in deviation #1 above. Alternative considered: change the sift-kg fork to allow `Optional[float]` / `Optional[str]` — out of scope (would require upstream sift-kg change and break Phase 6's schema format compatibility).
- **Parallel executor commits interleaved** — Plan 13-00 ran concurrently and its commits (`58b6c80`, `6c561ba`, `bfa62a7`, `7d9526c`, `4bd2fed`) appear between our three task commits in `git log`. Expected behaviour under `<parallel_execution>`. All 13-01 commits are intact and in order.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

**Ready for Plan 13-02 (normalize_extractions module):**
- `_normalize_fields` in `build_extraction.py` is the reference implementation for the Plan 02 module-level normalizer. Plan 13-02 should import or duplicate the same coercion rules (numeric-string confidence → float, unparseable → 0.5, missing context/attributes/evidence → defaults).
- Agents bypassing `build_extraction.py` and writing JSON directly via the `Write` tool still produce variant filenames — that normalization lives in Plan 02's module.

**Ready for Plan 13-03 (extractor.md Required-Fields block):**
- The CLI contract is now `python3 core/build_extraction.py <doc_id> <output_dir> [--domain <name>] [--model <id>] [--cost <float>] [--json '<json>']` with `EPISTRACT_MODEL` env fallback. Plan 03 can document this in `agents/extractor.md`.

**Ready for Plan 13-04 (e2e tests):**
- Write-time `ValueError` means the `--fail-threshold` abort in Plan 13-02 is now a second-line defence. FT-009 / FT-010 corpora can rely on invalid-payload detection happening at the extractor-agent call rather than 30 minutes later.

**No blockers.**

## Known Stubs

None. `cost_usd: null` and `model_used: null` are *intentional* (plan-mandated honest-unknown values per D-07/D-08), not stubs. They will be filled when the caller passes `--cost` / `--model` or sets `EPISTRACT_MODEL` — no future plan is required to "wire" them beyond Plan 13-03's extractor-agent update.

## Self-Check

**Files verified on disk:**
- FOUND: core/build_extraction.py (HAS_SIFT_EXTRACTION_MODEL, DocumentExtraction import, sys.path bootstrap, extended _normalize_fields, cost_usd/model_used kwargs + CLI flags, no "claude-opus-4-6" or hardcoded 0.0)
- FOUND: tests/test_unit.py (8 new test functions under Phase 13 — FIDL-02c section)
- FOUND: .planning/phases/13-extraction-pipeline-reliability/13-01-SUMMARY.md

**Commits verified:**
- FOUND: 02a7a52 feat(13-01): extend _normalize_fields + add DocumentExtraction guard
- FOUND: b93ff32 feat(13-01): add write-time DocumentExtraction validation
- FOUND: a98b6a4 feat(13-01): thread honest --model / --cost / EPISTRACT_MODEL provenance

**Test suite verified:**
- PASS: tests/test_unit.py::test_normalize_coerces_schema_drift (UT-022a)
- PASS: tests/test_unit.py::test_build_extraction_raises_on_missing_doc_id (UT-024)
- PASS: tests/test_unit.py::test_build_extraction_raises_on_invalid_entity (UT-025)
- PASS: tests/test_unit.py::test_build_extraction_threads_model_flag (UT-026)
- PASS: tests/test_unit.py::test_build_extraction_reads_model_env (UT-027)
- PASS: tests/test_unit.py::test_build_extraction_threads_cost_flag (UT-028)
- PASS: tests/test_unit.py::test_build_extraction_no_hardcoded_model (UT-029)
- PASS: tests/test_unit.py::test_build_extraction_no_hardcoded_cost (UT-030)
- PASS: tests/test_unit.py::test_ut012_extraction_adapter (regression)

## Self-Check: PASSED

---
*Phase: 13-extraction-pipeline-reliability*
*Completed: 2026-04-17*
