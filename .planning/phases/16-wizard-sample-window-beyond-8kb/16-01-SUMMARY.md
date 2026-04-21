---
phase: 16-wizard-sample-window-beyond-8kb
plan: 01
subsystem: domain-wizard
tags: [wizard, schema-discovery, prompt-engineering, FIDL-05]
dependency_graph:
  requires:
    - "FIDL-01 (Phase 12): wizard reads PDFs as real text — without real text, expanding the window matters nothing"
  provides:
    - "core.domain_wizard._build_excerpts: pure helper returning [] or 3-slice list[str]"
    - "core.domain_wizard.EXCERPT_CHARS = 4000"
    - "core.domain_wizard.MULTI_EXCERPT_THRESHOLD = 12000"
    - "core.domain_wizard.build_schema_discovery_prompt: length-conditional two-branch prompt builder"
    - "docs/known-limitations.md: canonical source for Phase 20 README Pipeline Capacity section (D-15)"
    - "UT-042 (_build_excerpts contract) GREEN"
    - "FIDL-05 traceability row at §v3 pointing at 16-01"
  affects:
    - "Plan 16-02 consumes UT-043 (currently RED pending 16-02 Task 1 fixture creation)"
    - "Phase 20 README consumes docs/known-limitations.md"
tech_stack:
  added: []
  patterns:
    - "textwrap.dedent f-string prompt idiom (existing; extended with conditional branch)"
    - "SCREAMING_SNAKE_CASE module constants (existing; 2 new added)"
    - "RED-first TDD two-commit pattern (Phase 14/15 precedent)"
    - "UPDATE-in-place FIDL-row pattern (Phase 15 D-13 precedent)"
key_files:
  created:
    - docs/known-limitations.md
    - .planning/phases/16-wizard-sample-window-beyond-8kb/deferred-items.md
  modified:
    - core/domain_wizard.py
    - tests/test_unit.py
    - tests/TEST_REQUIREMENTS.md
    - .planning/REQUIREMENTS.md
decisions:
  - "Em-dash (U+2014) in markers is load-bearing — UT-043 asserts exact literal `[EXCERPT 1/3 — chars 0 to 4000 (head)]`."
  - "Singular `**Document text:**` preserved in short-doc path to keep the pre-Phase-16 prompt shape byte-identical for the 27-char existing test fixture — backward compat via branching, not wholesale rewrite."
  - "UT-043 intentionally RED at end of 16-01; Plan 16-02 Task 1 provides the synthetic 60K-char fixture that flips it GREEN — documented cross-plan handoff."
  - "Pre-existing lint/format issues in test_unit.py and unrelated portions of domain_wizard.py logged to deferred-items.md — not auto-fixed (scope boundary)."
metrics:
  duration: ~10min
  completed: 2026-04-21
  commits: 4
  tasks: 3
  files_touched: 6
---

# Phase 16 Plan 01: Wizard Sample Window Beyond 8KB — Multi-Excerpt Pass-1 Summary

One-liner: Replaced `doc_text[:8000]` head-only truncation in the domain wizard Pass-1 prompt builder with a length-conditional multi-excerpt strategy (head 4K + middle 4K centered on len//2 + tail 4K with em-dash `[EXCERPT N/3 — chars X to Y]` markers for docs >12K; full-text passthrough for docs ≤12K) and registered FIDL-05 with UT-042 (GREEN) + UT-043 (RED pending 16-02 fixture) + `docs/known-limitations.md`.

## What Changed

1. **REQUIREMENTS / test-spec bookkeeping** (`fd1832a`)
   - `.planning/REQUIREMENTS.md §v3` — updated the pre-registered FIDL-05 row `| FIDL-05 | Phase 16 | — | Pending |` in-place to `| FIDL-05 | Phase 16 | 16-01 | Pending |` (D-13; UPDATE, not APPEND — `grep -c` gate stays at 1).
   - `.planning/REQUIREMENTS.md` footer — cites FIDL-05 Phase 16 registration (2026-04-21).
   - `tests/TEST_REQUIREMENTS.md` — new "Phase 16 Tests" section with UT-042 and UT-043 specs; traceability matrix appended with UT-042/UT-043 rows citing the Plan 16-02 fixture path.

2. **TDD RED step** (`19ddde9`)
   - `tests/test_unit.py` — added `test_build_excerpts` (UT-042) and `test_multi_excerpt_prompt_contains_markers` (UT-043) BEFORE the implementation landed. RED confirmed: UT-042 failed with `ImportError: cannot import name '_build_excerpts'`; UT-043 failed with `FileNotFoundError` on the fixture path.

3. **Implementation: helper + constants + conditional prompt builder** (`eb2751d`)
   - `core/domain_wizard.py`:
     - Added constants `EXCERPT_CHARS = 4000` and `MULTI_EXCERPT_THRESHOLD = 12000` to the existing Constants block.
     - Added `_build_excerpts(doc_text, excerpt_chars=EXCERPT_CHARS) -> list[str]` pure helper — returns `[]` if `len(doc_text) <= MULTI_EXCERPT_THRESHOLD`, else `[head, middle, tail]` where `middle = doc_text[len//2 - 2000 : len//2 + 2000]` (D-03 centered-slice, not "second third").
     - Rewrote `build_schema_discovery_prompt` to branch on `_build_excerpts(doc_text)`:
       - Long-doc path emits `**Document excerpts:**` header, D-05 preface ("The following are three excerpts from a larger document…"), and the three em-dash `[EXCERPT 1/3 — chars 0 to 4000 (head)]` / `[EXCERPT 2/3 — chars m0 to m1 (middle)]` / `[EXCERPT 3/3 — chars t0 to end (tail)]` markers.
       - Short-doc path keeps the original `**Document text:**` singular header and passes `doc_text` verbatim — no truncation, no markers. `test_wizard_schema_discovery_prompt` (the existing 24-char Phase 8 test) continues to pass without modification.
     - `doc_text[:8000]` is gone.
     - `build_consolidation_prompt` (Pass 2) and `build_final_schema_prompt` (Pass 3) are byte-identical to pre-Phase-16 (D-07).

4. **Known-limitations doc** (`fb9ffa5`)
   - New file `docs/known-limitations.md` with first entry `## Domain Wizard sample window (FIDL-05)` documenting the 12K effective window, 4K per-excerpt slice, middle-centered slice, shoulder-region risk (chars 4K..len//2-2K and len//2+2K..len-4K never sent), tail-beyond-4KB limit, soft 24K token budget with no runtime enforcement, Pass-2/Pass-3 zero-impact, and the acceptance-gate sentinel names. Token-count body contains `<TOKEN_COUNT_PLACEHOLDER>` (Plan 16-02 Task 4 replaces). Designed to grow — future limitations append new `## <Section>` entries. D-15: Phase 20 README cites this file rather than re-deriving values.

## Reference Patterns Followed

- **Phase 15 UPDATE-in-place FIDL-row pattern** (`15-01-PLAN.md` Task 1): pre-registered `—` placeholder updated in place to plan ID; grep count stays at 1. Applied identically here for FIDL-05.
- **Phase 8 wizard prompt-building idiom**: `textwrap.dedent(f"""\...""")` for all prompt builders. Applied for both the new conditional body interpolation and the outer prompt template.
- **Phase 14 / 15 two-commit RED→GREEN TDD precedent** (`e215707` test, then `f6eb9dc` implementation): test file committed RED first, then implementation; each commit self-contained and buildable.
- **`.planning/REQUIREMENTS.md` v3 footer update pattern**: every FIDL plan touches the footer line — applied here for FIDL-05 registration.

## FIDL-05 Status Progression

- **Before Plan 16-01:** `| FIDL-05 | Phase 16 | — | Pending |` (pre-registered placeholder).
- **After Plan 16-01:** `| FIDL-05 | Phase 16 | 16-01 | Pending |` — traceability now points at this plan; requirement subsection `- [ ] **FIDL-05**` remains unchecked (Plan 16-02 FT-016/FT-017 acceptance gates + token measurement must complete first).
- **Blocks flipping to `Complete`:** Plan 16-02 Task 1 (synthetic 60K-char fixture), Task 2 (UT-043 GREEN on fixture), Task 3 (FT-016 strict-superset regression), Task 4 (tiktoken measurement replaces `<TOKEN_COUNT_PLACEHOLDER>`).

## Non-Obvious Decisions

1. **Em-dash U+2014 is the contract, not a stylistic choice.** UT-043 assertion 1 is `"[EXCERPT 1/3 — chars 0 to 4000 (head)]" in prompt` — the em-dash character is exact. ASCII hyphen would fail. This pins D-04 format verbatim.

2. **Short-doc header preserved.** We could have switched every call to the plural `**Document excerpts:**` header, but that would have required changing the existing Phase 8 test fixture. Keeping the singular header for short docs (length ≤ 12K) is a deliberate backward-compat choice (D-05 short-doc wording) so `test_wizard_schema_discovery_prompt` passes unchanged.

3. **`_build_excerpts` returns `[]` for short docs, not `None`.** Caller uses truthiness (`if excerpts:`) to pick the branch. `[]` avoids a sentinel-value footgun and keeps the helper type signature pure `list[str]`.

4. **Middle slice uses `doc_text[len//2 - 2000 : len//2 + 2000]`, not `[:4000]` of the second third.** For a 60K-char doc, "second third" is chars 20K-40K; this implementation returns chars 28K-32K. The centered slice gives a stable mid-document anchor regardless of intro-heavy or conclusion-heavy distributions (D-03).

5. **UT-043 RED at end of 16-01 is documented cross-plan handoff.** The plan explicitly marks UT-043 as fixture-dependent (16-02 Task 1). This is not a regression or failure; it is how 16-01 and 16-02 hand off state.

## Deferred to Plan 16-02

- `tests/fixtures/wizard_sample_window/long_contract.txt` synthetic 60K-char fixture (Task 1). Creates the 3 sentinels (`PARTY_SENTINEL_HEAD`, `OBLIGATION_SENTINEL_MIDDLE`, `TERMINATION_SENTINEL_TAIL`).
- UT-043 flipped to GREEN (Task 2) — same test file; fixture-read-through assertion succeeds once the file exists.
- FT-016 end-to-end sentinel-coverage acceptance test (Task 3).
- FT-017 strict-superset regression gate against existing contracts-wizard fixture (Task 3).
- Token-count measurement — tiktoken or `len(prompt)/4` fallback (Task 4) — replaces `<TOKEN_COUNT_PLACEHOLDER>` in `docs/known-limitations.md`.

## Deferred / Out of Scope

See `.planning/phases/16-wizard-sample-window-beyond-8kb/deferred-items.md` for pre-existing lint/format issues in `tests/test_unit.py` and unrelated portions of `core/domain_wizard.py` (trailing-comma-split argument lists in `validate_generated_epistemic` / `generate_domain_package`). All pre-exist on `main`; none touched or worsened by Phase 16. Explicit scope-boundary decision.

## Deviations from Plan

### Auto-fixed Issues

None.

### Architectural Decisions

None.

### Observations

- **Singular `**Document text:**` grep count is 2, not 1 as plan expected.** The docstring for `build_schema_discovery_prompt` mentions `**Document text:**` in prose, and the short-doc branch body contains it literally. Functional behavior is correct (singular header used only on short-doc path); the plan's "exactly 1" grep gate did not account for the docstring occurrence. This is cosmetic; the UT-043 short-doc assertion and `test_wizard_schema_discovery_prompt` both verify the functional invariant.

## Commits

| # | Commit  | Message                                                                             |
| - | ------- | ----------------------------------------------------------------------------------- |
| 1 | fd1832a | docs(16-01): register FIDL-05 traceability + UT-042/UT-043 for wizard sample window |
| 2 | 19ddde9 | test(16-01): add UT-042 + UT-043 RED for FIDL-05 multi-excerpt wizard prompt        |
| 3 | eb2751d | feat(16-01): multi-excerpt Pass-1 prompt with explicit markers (FIDL-05)            |
| 4 | fb9ffa5 | docs(16-01): create known-limitations.md with Domain Wizard sample window entry     |

## Test Status

| Test                                       | Status                         |
| ------------------------------------------ | ------------------------------ |
| UT-042 `test_build_excerpts`               | GREEN                          |
| UT-043 `test_multi_excerpt_prompt_...`     | RED (fixture handoff to 16-02) |
| `test_wizard_schema_discovery_prompt`      | GREEN (unchanged from Phase 8) |
| All 12 existing wizard tests (excl UT-043) | GREEN                          |

## Acceptance vs Plan Success Criteria

| Criterion                                         | Status |
| ------------------------------------------------- | ------ |
| 1. D-01 multi-excerpt for >12K                    | MET    |
| 2. D-02 conditional on length                     | MET    |
| 3. D-03 middle centered on len/2                  | MET    |
| 4. D-04 explicit em-dash markers                  | MET    |
| 5. D-05 plural header + preface (long); singular (short) | MET    |
| 6. D-06 Instructions unchanged                    | MET    |
| 7. D-07 Pass-2 / Pass-3 untouched                 | MET    |
| 8. D-13 requirement registered in-place           | MET    |
| 9. D-14 known-limitations doc                     | MET    |
| 10. D-15 Phase 20 consumer contract               | MET    |
| 11. Scope discipline                              | MET    |

## Known Stubs

- `<TOKEN_COUNT_PLACEHOLDER>` in `docs/known-limitations.md` — explicit documented cross-plan handoff to Plan 16-02 Task 4 (tiktoken or `len/4` measurement). Plan 16-02 acceptance criteria require this replacement before FIDL-05 flips to `Complete`. Not a rendering stub (no UI consumer); it is a sentinel for the measurement task.

## Self-Check: PASSED

Verified files created/exist:
- `/Users/umeshbhatt/code/epistract/docs/known-limitations.md` — FOUND
- `/Users/umeshbhatt/code/epistract/.planning/phases/16-wizard-sample-window-beyond-8kb/deferred-items.md` — FOUND

Verified commits exist in git history:
- fd1832a — FOUND
- 19ddde9 — FOUND
- eb2751d — FOUND
- fb9ffa5 — FOUND
