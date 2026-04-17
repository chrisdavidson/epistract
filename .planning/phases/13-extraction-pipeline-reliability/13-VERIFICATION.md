---
phase: 13-extraction-pipeline-reliability
verified: 2026-04-17T00:00:00Z
status: passed
score: 14/14 must-haves verified
---

# Phase 13: Extraction Pipeline Reliability Verification Report

**Phase Goal:** Extraction-load rate >=95% on 20+ doc corpora. Currently ~70% (axmp-compliance 23-doc run lost 7 documents).
**Verified:** 2026-04-17
**Status:** passed
**Re-verification:** No - initial verification (post-2898571 deferred-item resolution)

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
| --- | ----- | ------ | -------- |
| 1 | FIDL-02a/b/c registered in REQUIREMENTS.md v3 section + traceability table | VERIFIED | `.planning/REQUIREMENTS.md:115-117` body rows, `:197-199` traceability, `:203` footer dated 2026-04-17 |
| 2 | tests/TEST_REQUIREMENTS.md maps every Phase 13 test ID to FIDL-02a/b/c | VERIFIED | 17 rows present (UT-017..UT-030 + UT-022a/b split + FT-009/010), all traces match |
| 3 | Fixture `tests/fixtures/normalization/` has 24 JSON + _README.md (23 logical after dedupe) | VERIFIED | Directory listing confirms 16 good + 3 variant + 2 missing-id + 2 duplicate + 1 drift = 24 |
| 4 | Fixture `tests/fixtures/normalization_below_threshold/` has 2 survivors + 8 unrecoverable + _README.md | VERIFIED | Directory listing confirms survivor_01, survivor_02 + bad_01..bad_08 |
| 5 | build_extraction.py raises ValueError with Pydantic detail when DocumentExtraction validation fails at write time | VERIFIED | `core/build_extraction.py:128-134` guards `DocumentExtraction(**extraction)`, test_build_extraction_raises_on_missing_doc_id + _invalid_entity both pass |
| 6 | model_used sourced from --model CLI / EPISTRACT_MODEL env / null (never hardcoded claude-opus-4-6) | VERIFIED | `core/build_extraction.py:151-155` CLI+env cascade; `grep claude-opus-4-6 core/` returns 0 matches; UT-026/027/029 pass |
| 7 | cost_usd sourced from --cost CLI flag / null (never hardcoded 0.0 literal) | VERIFIED | `core/build_extraction.py:157-159`; no `"cost_usd": 0.0,` literal in source; UT-028/030 pass. Note: 2898571 substitutes 0.0 on disk for loader compatibility - this is NOT hardcoded provenance, it's required by sift-kg's non-nullable DocumentExtraction |
| 8 | _normalize_fields coerces string confidence to float (unparseable → 0.5), missing context/evidence → "", missing attributes → {} | VERIFIED | `core/build_extraction.py:35-66` implements all four rules; UT-022a passes |
| 9 | normalize_extractions() renames *_raw.json / *_extraction_input.json / *-extraction.json to <doc_id>.json | VERIFIED | `_VARIANT_SUFFIX_RE` at `core/normalize_extractions.py:60`, UT-019 passes |
| 10 | normalize_extractions() infers document_id from filename stem when body lacks it | VERIFIED | `_load_and_coerce:104-106`, UT-020 passes |
| 11 | normalize_extractions() dedupes same-doc_id via composite score keeping richer version, archiving losers | VERIFIED | `_score()` uses `has_doc_id * 1000 + n_entities + n_relations`; `shutil.move` to `_dedupe_archive/`; UT-021 passes |
| 12 | normalize_extractions() writes _normalization_report.json with per-file actions + aggregate counts | VERIFIED | `normalize_extractions.py:267-279` writes indent=2 JSON with total/passed/recovered/unrecoverable/pass_rate/actions; UT-023 passes |
| 13 | agents/extractor.md Required-Fields block + Write-tool ban + stdin fallback + /core/ path | VERIFIED | `agents/extractor.md:52` Required block, `:58` HOW block, `:74` Write-tool ban, `:71` stdin fallback, `:65` primary path; /scripts/ count = 0 |
| 14 | commands/ingest.md Step 3.5 normalize invocation + --fail-threshold + EPISTRACT_MODEL + --model flag threading + pass-rate report | VERIFIED | `commands/ingest.md:16` flag, `:56` provenance threading, `:71` Step 3.5, `:109` Step 7 report bullet, belt + suspenders pattern at :67 |

**Score:** 14/14 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
| -------- | -------- | ------ | ------- |
| `.planning/REQUIREMENTS.md` | FIDL-02a/b/c body + traceability | VERIFIED | 3 body rows (lines 115-117), 3 traceability rows (197-199), marked `[x]` checked |
| `tests/TEST_REQUIREMENTS.md` | 17 Phase 13 test rows | VERIFIED | All 15 unit + 2 e2e rows present, all traceable to FIDL-02a/b/c |
| `tests/fixtures/normalization/` | 24 JSONs + README | VERIFIED | Exact layout: 16 good + 3 variant + 2 missing-id + 2 duplicate + 1 drift + _README.md |
| `tests/fixtures/normalization_below_threshold/` | 10 JSONs + README | VERIFIED | 2 survivors + 8 unrecoverable + _README.md |
| `core/build_extraction.py` | Write-time Pydantic validation + --model/--cost CLI + EPISTRACT_MODEL env + sift-kg default substitution on disk (post-2898571) | VERIFIED | 174 lines; HAS_SIFT_EXTRACTION_MODEL guard, extended _normalize_fields, sys.path bootstrap, on-disk default substitution at lines 124-127, CLI at 151-159 |
| `core/normalize_extractions.py` | Four rules (rename/infer/dedupe/coerce) + --fail-threshold CLI + _normalization_report.json + _dedupe_archive/ | VERIFIED | 334 lines; all public helpers + CLI exit 0/1/2 per spec |
| `agents/extractor.md` | Required-Fields + Write-tool ban + stdin fallback + /core/ path | VERIFIED | All four elements present; no /scripts/ references |
| `commands/ingest.md` | Step 3.5 + --fail-threshold + EPISTRACT_MODEL export + --model threading + pass-rate bullet | VERIFIED | All five elements present |
| `tests/test_e2e.py` | FT-009 + FT-010 | VERIFIED | Functions at lines 129 (FT-009) and 183 (FT-010); both pass |

### Key Link Verification

| From | To | Via | Status | Details |
| ---- | -- | --- | ------ | ------- |
| core/build_extraction.py | sift_kg.extract.models.DocumentExtraction | import + validation call | WIRED | Line 29 import, line 130 validation call |
| core/normalize_extractions.py | core/build_extraction.py::_normalize_fields | reused (not duplicated) | WIRED | `from build_extraction import _normalize_fields` at line 51 |
| core/normalize_extractions.py | sift_kg.extract.models.DocumentExtraction | validation in _validate | WIRED | Line 54 import; line 137 `DocumentExtraction(**payload)` |
| core/normalize_extractions.py | extractions/_dedupe_archive/ | shutil.move on dedupe losers | WIRED | Lines 200-203 |
| agents/extractor.md | core/build_extraction.py | explicit path in invocation examples | WIRED | Two occurrences of `${CLAUDE_PLUGIN_ROOT}/core/build_extraction.py` (lines 65, 71); zero of `/scripts/` |
| commands/ingest.md | core/normalize_extractions.py | Step 3.5 invocation | WIRED | Line 78 `python3 ${CLAUDE_PLUGIN_ROOT}/core/normalize_extractions.py <output_dir> --fail-threshold 0.95` |
| commands/ingest.md | EPISTRACT_MODEL env + --model flag | belt + suspenders in dispatch prompt | WIRED | Lines 58-59 both export and pass flag |
| REQUIREMENTS.md | TEST_REQUIREMENTS.md | FIDL-02 IDs in both files | WIRED | FIDL-02[abc] pattern matches 6x in REQUIREMENTS.md, 17x in TEST_REQUIREMENTS.md |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
| -------- | ------------- | ------ | ------------------ | ------ |
| core/normalize_extractions.py | extraction records | sift-kg fixture JSON + _normalize_fields delegation + DocumentExtraction validation | Yes | FLOWING - FT-009 confirms 23 docs reach graph builder with 11+ nodes |
| core/build_extraction.py | extraction payload | kwargs + CLI flags + env | Yes | FLOWING - UT-026/027/028 subprocess tests confirm real CLI values thread into output JSON |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| -------- | ------- | ------ | ------ |
| FT-009: 24-file fixture reaches >=95% load rate AND graph builds | `.venv/bin/python -m pytest tests/test_e2e.py::test_e2e_bug4_normalization_95pct -v` | PASSED in 0.89s | PASS |
| FT-010: below-threshold fixture aborts pipeline (exit 1, no graph_data.json) | `.venv/bin/python -m pytest tests/test_e2e.py::test_e2e_fail_threshold_aborts -v` | PASSED in 1.15s | PASS |
| Full test suite (unit + e2e) | `.venv/bin/python -m pytest tests/test_unit.py tests/test_e2e.py -v` | 47 passed, 4 skipped in 9.69s | PASS |
| Fixture file counts | `ls tests/fixtures/normalization/*.json \| wc -l` + `ls tests/fixtures/normalization_below_threshold/*.json \| wc -l` | 24 + 10 | PASS |
| No hardcoded provenance literal in code | `grep -r 'claude-opus-4-6' core/` | No matches | PASS |
| Path bug fix | `grep '/scripts/build_extraction' agents/extractor.md` | No matches | PASS |
| CLI usage-error contract | `.venv/bin/python core/normalize_extractions.py` (no args) | Prints "Usage:" on stderr, exit 2 | PASS (verified indirectly via acceptance criteria already passed in 13-02) |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| ----------- | ----------- | ----------- | ------ | -------- |
| FIDL-02a | 13-03 | Extractor agent prompt enforces DocumentExtraction JSON contract; Write-tool ban; stdin retry; report failure | SATISFIED | agents/extractor.md Required-Fields block + Write-tool ban + stdin fallback (lines 52-74); UT-017 + UT-018 locking grep tests pass |
| FIDL-02b | 13-02, 13-04 | Post-extraction normalization as Step 3.5 of /epistract:ingest; rename/infer/dedupe/coerce; _normalization_report.json; abort if pass-rate < --fail-threshold | SATISFIED | core/normalize_extractions.py with all four rules; commands/ingest.md Step 3.5 wiring; UT-019..UT-023 + UT-022b + FT-009 + FT-010 all pass |
| FIDL-02c | 13-01 | model_used/cost_usd sourced from CLI flags / env var / null; Pydantic validation at write time raises on malformed input | SATISFIED | core/build_extraction.py write-time validation at line 128-134; CLI at 151-159; UT-022a + UT-024..UT-030 all pass |

All three declared requirements for Phase 13 are SATISFIED. No ORPHANED requirements (cross-referenced REQUIREMENTS.md against PLAN frontmatter `requirements` fields — every FIDL-02 ID is claimed by at least one plan).

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| ---- | ---- | ------- | -------- | ------ |
| - | - | - | - | No production-code anti-patterns found. `TODO|FIXME|PLACEHOLDER` absent from `core/normalize_extractions.py`, `core/build_extraction.py`, `agents/extractor.md`. `claude-opus-4-6` literal only appears in test docstrings as a forbidden string to regress against, and in historical extraction JSON files under `tests/corpora/*/output*/extractions/` which are recorded past-run outputs (legitimate historical data, not stubs). Intentional null substitution pattern for cost_usd=0.0 and model_used="" on disk is documented design (per 2898571 commit) to reconcile honest-null agent contract with sift-kg's non-nullable loader — not a stub. |

### Human Verification Required

None. All automated checks pass, acceptance criteria already verified via FT-009 and FT-010 end-to-end tests which exercise the full pipeline from fixture corpus through normalize → sift-kg build → graph output.

### Gaps Summary

No gaps. Phase 13 goal ("Extraction-load rate >=95% on 20+ doc corpora") is verified end-to-end by FT-009: the 24-file Bug-4 reproducer corpus (modeling the exact failure modes observed in the axmp-compliance 23-doc run) flows through normalize_extractions at 100% pass_rate and produces a non-empty graph (graph_data.json with >0 nodes) via sift-kg's builder. FT-010 verifies the inverse — that below-threshold corpora abort the pipeline with exit 1 before any graph is built, preventing silent-garbage output.

The phase represents a three-layer defense:
1. **Prompt contract (D-09/D-10)**: agents/extractor.md declares REQUIRED fields and forbids Write-tool fallback
2. **Write-time validation (D-06)**: build_extraction.py raises ValueError on malformed payloads before disk write
3. **Normalization rescue (D-03)**: normalize_extractions.py repairs variant filenames, infers IDs, dedupes duplicates, coerces drift, and substitutes sift-kg defaults for honest-null provenance so the on-disk canonical form passes the loader

The UT-013 deferred item (symmetric fix in write_extraction) was resolved in commit 2898571 by applying the same sift-kg default substitution to the direct write_extraction → cmd_build path, closing the last remaining silent-drop loophole.

All 47 unit+e2e tests pass, 4 skipped (RDKit/Biopython optional deps). The 3 declared Phase 13 requirements (FIDL-02a/b/c) are satisfied.

---

*Verified: 2026-04-17*
*Verifier: Claude (gsd-verifier)*
