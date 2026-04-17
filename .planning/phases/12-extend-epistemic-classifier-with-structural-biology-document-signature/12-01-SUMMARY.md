---
phase: 12-extend-epistemic-classifier-with-structural-biology-document-signature
plan: 01
subsystem: domain-wizard
tags: [sift-kg, pdf, read_document, domain-wizard, fidl-01, binary-safe-read]

# Dependency graph
requires:
  - phase: 08-domain-wizard-generation
    provides: "core/domain_wizard.py::read_sample_documents and build_schema_discovery_prompt surface"
  - phase: 06-core-architecture
    provides: "core/ingest_documents.py::parse_document reference pattern for sift_kg.ingest.reader guarded imports"
provides:
  - "HAS_SIFT_READER import guard in core/domain_wizard.py"
  - "Binary-safe PDF/DOCX/HTML read path for the domain creation wizard via sift_kg.ingest.reader.read_document"
  - "Loud-failure fallback (skip + MIN_SAMPLE_DOCS ValueError) when sift-kg is not installed, replacing the silent %PDF-binary-as-text regression"
  - "tests/fixtures/wizard/sample_lease_2.pdf — first binary wizard fixture"
  - "Two regression tests locking in FIDL-01: test_wizard_reads_pdf_as_text and test_wizard_skips_binary_when_sift_reader_missing"
  - "FIDL-01 requirement entry and v3 traceability row in .planning/REQUIREMENTS.md"
affects: [phase-16-wizard-sample-window, phase-17-domain-awareness-in-consumers, any-future-wizard-format-coverage-work]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Optional sift-kg dependency guard: `try: from sift_kg.ingest.reader import read_document; HAS_SIFT_READER = True` mirrors core/ingest_documents.py:20-25."
    - "Loud-fail fallback: when the binary-safe reader is absent, skip non-.txt inputs and let MIN_SAMPLE_DOCS raise a clear ValueError — never return binary-bytes-as-text."

key-files:
  created:
    - ".planning/phases/12-extend-epistemic-classifier-with-structural-biology-document-signature/12-01-SUMMARY.md"
    - ".planning/phases/12-extend-epistemic-classifier-with-structural-biology-document-signature/deferred-items.md"
    - "tests/fixtures/wizard/sample_lease_2.pdf"
  modified:
    - "core/domain_wizard.py"
    - "tests/test_unit.py"
    - ".planning/REQUIREMENTS.md"

key-decisions:
  - "Dropped errors='replace' fallback entirely rather than keeping it as a last-resort branch. Binary-as-text IS the bug we are fixing — keeping any path that produces %PDF-prefixed 'text' would preserve the silent-garbage failure mode. Loud failure via MIN_SAMPLE_DOCS is strictly better than silent garbage schemas."
  - "Mirrored the HAS_SIFT_READER guard from core/ingest_documents.py verbatim (not shared-utility extraction). Shared utility can wait — duplicating one six-line import block keeps this plan narrow and avoids touching ingestion."
  - "Kept the returned dict shape unchanged ({path, text, char_count}) so downstream callers (build_schema_discovery_prompt, analyze_documents) require no modification — zero blast radius outside read_sample_documents."
  - "Used the existing sample_contract_a.pdf as the wizard PDF fixture rather than generating a new one; already a valid 1-page PDF v1.3 that exercises the binary-read path."

patterns-established:
  - "Binary-safe document reader guard: any core/ function that consumes user-supplied documents must route through sift_kg.ingest.reader.read_document when available, and fail loudly (not silently read binary) when it is not."
  - "Wizard-specific fixtures live in tests/fixtures/wizard/; binary formats are OK there (they represent real user inputs)."

requirements-completed: [FIDL-01]

# Metrics
duration: 3min
completed: 2026-04-17
---

# Phase 12 Plan 01: Fix wizard PDF binary read (Bug 3 — FIDL-01) Summary

**read_sample_documents() now routes through sift_kg.ingest.reader.read_document so /epistract:domain produces real schemas from PDF corpora instead of garbage derived from %PDF-1.4 binary headers.**

## Performance

- **Duration:** 3min (approx. 3min 22s wall)
- **Started:** 2026-04-17T00:59:48Z
- **Completed:** 2026-04-17T01:03:10Z
- **Tasks:** 2 completed (3 commits, TDD RED→GREEN)
- **Files modified:** 3 (plus 2 created: PDF fixture, deferred-items.md)

## Accomplishments

- Eliminated Bug 3: the wizard no longer feeds `%PDF-1.4\n%\xd0\xd4...` bytes into the 3-pass LLM schema discovery. The /epistract:domain "create your own domain" path is now viable for PDF-native corpora (the majority of real-world inputs).
- Locked in the regression with two unit tests: a GREEN-path test asserting extracted PDF text does not start with `%PDF`, and a failure-mode test patching `HAS_SIFT_READER=False` to prove binary files are skipped (hitting MIN_SAMPLE_DOCS) rather than silently returned as garbage.
- Made FIDL-01 a first-class, traceable v3 requirement in `.planning/REQUIREMENTS.md`, opening the v3 "Graph Fidelity & Honest Limits" milestone section with a clean phase→plan traceability row.
- Mirrored the sift-kg reader guard from `core/ingest_documents.py:20-25` so the wizard now matches the ingestion pipeline's binary-read strategy verbatim.

## Task Commits

Each task was committed atomically:

1. **Task 1: Add FIDL-01 requirement to REQUIREMENTS.md** — `8de927a` (docs)
2. **Task 2 RED: Add FIDL-01 regression for PDF wizard read** — `054b011` (test)
3. **Task 2 GREEN: Route wizard sample reads through sift-kg reader** — `d73a04f` (fix)

_Task 2 used TDD (tdd="true"): the RED commit locked the failure mode (AssertionError on `%PDF` prefix, AttributeError on missing HAS_SIFT_READER), then the GREEN commit made it pass. No refactor commit needed — the fix was minimal._

## Files Created/Modified

- `core/domain_wizard.py` — Added HAS_SIFT_READER import guard (lines 32-39) and rewrote `read_sample_documents()` body (lines 56-113) to route through `read_document(p)` when available, fall back to `.txt`-only plain-text read otherwise, and skip binary files instead of reading them as garbage. Removed the buggy `p.read_text(errors="replace")` line entirely.
- `tests/test_unit.py` — Added two regression tests after `test_wizard_schema_discovery_prompt`: `test_wizard_reads_pdf_as_text` (skipif not HAS_SIFTKG) and `test_wizard_skips_binary_when_sift_reader_missing` (uses `mock.patch.object(domain_wizard, "HAS_SIFT_READER", False)`).
- `tests/fixtures/wizard/sample_lease_2.pdf` — Copied from `tests/fixtures/sample_contract_a.pdf`. Valid 1-page PDF v1.3 used as the binary wizard fixture.
- `.planning/REQUIREMENTS.md` — New `## v3 Requirements (In Progress)` section with `### Graph Fidelity & Honest Limits (Phase 12)` containing FIDL-01. New `### v3 (Mapped to Phases 12+)` traceability table. Bumped "Last updated" footer to 2026-04-16.
- `.planning/phases/12-.../deferred-items.md` — Logged pre-existing lint/format drift in `tests/test_unit.py` (F401 importlib) and `core/domain_wizard.py` (trailing-comma arg blocks in functions NOT modified by this plan). Out of scope per GSD scope-boundary rule; proposed remediation is a dedicated `chore(format):` quick task.

## Decisions Made

1. **Dropped `errors="replace"` fallback entirely.** The plan explicitly calls for removing the line; I also chose not to add any "last-resort" binary-as-text branch. Rationale: binary-as-text IS the bug being fixed — every path that produces `%PDF`-prefixed "text" preserves the silent-garbage failure mode for PDF-native users. Loud failure (skip + MIN_SAMPLE_DOCS ValueError) is strictly better because it surfaces the missing-dependency problem instead of producing wrong schemas.

2. **Duplicated the HAS_SIFT_READER guard rather than extracting a shared helper.** `core/ingest_documents.py:20-25` has the same six-line try/except block. Extracting a shared `core/_sift_reader.py` utility is tempting but out of scope for a single-bug plan. Duplicate now; extract when a third caller appears.

3. **Reused the existing `tests/fixtures/sample_contract_a.pdf` via copy rather than creating a new PDF.** Plan recommends this. It is already a valid 1-page PDF v1.3 in the repo, exercises the binary-read path, and avoids adding a wholly new artifact.

4. **Kept the returned dict shape unchanged** (`{path, text, char_count}`). Downstream callers — `build_schema_discovery_prompt`, `analyze_documents` — require no modification. Zero blast radius outside `read_sample_documents`.

## Deviations from Plan

None — plan executed exactly as written.

Every sub-step in Task 2 (import guard, function rewrite, fixture copy, test append) landed as specified. The only non-mechanical action was adding a `deferred-items.md` entry for pre-existing ruff format/lint drift in unrelated functions — this is Rule 3-adjacent (scope boundary), NOT a deviation from the plan itself.

## Issues Encountered

1. **`.planning/` is gitignored.** The project's `.gitignore` blocks `.planning/`, so `git add .planning/REQUIREMENTS.md` failed with "paths are ignored". Used `git add -f` (matches how STATE.md/ROADMAP.md are already tracked per `git status -M` at start of phase). Verified by the pre-existing tracked modifications to `.planning/ROADMAP.md` and `.planning/STATE.md`.

2. **`ruff format --check` reports pre-existing drift.** The plan acceptance criterion `ruff format --check core/domain_wizard.py tests/test_unit.py` cannot pass without reformatting functions I did not modify (`validate_generated_epistemic`, `analyze_documents`, `generate_domain_package` in domain_wizard.py, plus several asserts in test_unit.py). Confirmed pre-existing by `git stash && ruff format --check`. Per the GSD scope-boundary rule ("only auto-fix issues DIRECTLY caused by the current task's changes"), I reformatted only my new `results.append({...})` block in the rewritten `read_sample_documents()` and logged the rest to `deferred-items.md`. All new code I wrote is format-clean; the remaining drift is 100% pre-existing.

3. **`ruff check tests/test_unit.py` reports one pre-existing F401** (`importlib` imported but unused, line 138). Confirmed pre-existing via `git stash`. Out of scope; logged in `deferred-items.md`.

## User Setup Required

None — no external service configuration required. sift-kg was already installed in the project's venv (`.venv/bin/python -c "from sift_kg.ingest.reader import read_document"` succeeds).

## Next Phase Readiness

- **FIDL-01 status:** Complete. The requirement's traceability row (`FIDL-01 | Phase 12 | 12-01 | Pending`) should be updated to `Complete` by `requirements mark-complete` during the state-updates step of this execution.
- **Phase 16 (wizard sample window beyond 8KB) is unblocked.** Phase 16's ROADMAP entry explicitly notes "Depends on Phase 12 (wizard must read real text first)" — that dependency is now satisfied.
- **Phase 13 (extraction pipeline reliability)** is untouched by this plan but shares the same binary-safe-reader discipline; no new blockers introduced.
- **Open follow-up:** a `chore(format): reformat core/ and tests/` quick task should be run to clear the pre-existing lint/format drift documented in `deferred-items.md`.

## Reference Pattern Followed

This plan mirrored `core/ingest_documents.py` verbatim:

- Import guard: `core/ingest_documents.py:20-25` → `core/domain_wizard.py:32-39`.
- Reader-then-fallback logic: `core/ingest_documents.py::parse_document` (lines 122-155) → `core/domain_wizard.py::read_sample_documents` (lines 56-113), adapted from "return text or error dict" to "append to results list or skip via continue".

---
*Phase: 12-extend-epistemic-classifier-with-structural-biology-document-signature*
*Completed: 2026-04-17*

## Self-Check: PASSED

- FOUND: .planning/REQUIREMENTS.md
- FOUND: core/domain_wizard.py
- FOUND: tests/test_unit.py
- FOUND: tests/fixtures/wizard/sample_lease_2.pdf
- FOUND: .planning/phases/12-.../12-01-SUMMARY.md
- FOUND: .planning/phases/12-.../deferred-items.md
- FOUND: 8de927a (Task 1 — docs: register FIDL-01)
- FOUND: 054b011 (Task 2 RED — add FIDL-01 regression tests)
- FOUND: d73a04f (Task 2 GREEN — route wizard through sift-kg reader)
