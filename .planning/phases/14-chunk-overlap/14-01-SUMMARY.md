---
phase: 14-chunk-overlap
plan: 01
subsystem: infra
tags: [requirements, blingfire, chunk-overlap, fidl-03, dependencies, docs]

# Dependency graph
requires:
  - phase: 13-extraction-pipeline-reliability
    provides: FIDL-02a/b/c precedent for requirement-row + traceability-table pattern; agents/extractor.md → core/build_extraction.py invocation path (unaffected here)
provides:
  - FIDL-03 row in .planning/REQUIREMENTS.md (v3 section + traceability table)
  - Phase 14 test IDs registered in tests/TEST_REQUIREMENTS.md (UT-031..UT-038, UT-033b, UT-036b, FT-011, FT-012)
  - blingfire declared as core runtime dep in pyproject.toml (partial [project].dependencies)
  - scripts/setup.sh auto-installs blingfire in the required-install block (before RDKit/Biopython optional block)
  - CLAUDE.md §Key Dependencies documents blingfire; §Platform Requirements disk-space updated
affects: [14-02, 14-03, 14-04, V2-scenario-runs]

# Tech tracking
tech-stack:
  added: [blingfire>=0.1.8 (sentence tokenizer, bundled models)]
  patterns:
    - "Phase 14 required-dep pattern mirrors sift-kg block in setup.sh: column-0 heredoc, fail-loud on install failure (exit 1), import probe via venv python, honest --check handling, NOT gated on INSTALL_ALL"
    - "pyproject.toml [project].dependencies is PARTIAL: only phase-14 dep declared; full dep graph remains in scripts/setup.sh (M-4 header comment explains why)"

key-files:
  created: []
  modified:
    - ".planning/REQUIREMENTS.md (FIDL-03 req bullet + traceability row + footer)"
    - "tests/TEST_REQUIREMENTS.md (Section 6 added — 10 Phase 14 test IDs)"
    - "pyproject.toml (added [project] table + M-4 header comment — HEAD was pytest-only)"
    - "scripts/setup.sh (inserted blingfire required-install block lines 138-167)"
    - "CLAUDE.md (§Key Dependencies bullet + §Platform Requirements disk-space line)"

key-decisions:
  - "pyproject.toml [project].dependencies is PARTIAL (only blingfire>=0.1.8) — canonical install path remains scripts/setup.sh; M-4 header comment documents the intentional scope"
  - "blingfire install NOT gated on INSTALL_ALL — required dep, not optional like RDKit/Biopython (per D-09)"
  - "Column-0 heredoc style preserved exactly (m-1 fix) to avoid EOF-sentinel parse errors; bash -n confirms syntax"
  - "Phase 13 content (FIDL-02a/b/c, UT-017..UT-030, FT-009/010) left entirely untouched — no regression"
  - "UT-035 uses pytest monkeypatch.setitem (not try/finally) for safe ordering under pytest-randomly / pytest-xdist (B-3 fix)"
  - "FT-012 treats missing tests/baselines/v2/expected.json as FAIL (not SKIP) — file-backed floor per B-2 fix"

patterns-established:
  - "Phase-N requirement registration workflow (mirrors Phase 13 plan 00): (1) append requirement bullet to v3 section, (2) add traceability row, (3) bump footer, (4) append test-requirements section before Traceability Matrix"
  - "Required-dep declaration (multi-file): pyproject.toml + scripts/setup.sh required-install block + CLAUDE.md §Key Dependencies — all three edited in a single commit to keep dep-graph consistent"

requirements-completed: [FIDL-03]

# Metrics
duration: 4min
completed: 2026-04-18
---

# Phase 14 Plan 01: Register FIDL-03 and Provision blingfire Summary

**FIDL-03 declared as a v3 requirement; blingfire promoted to first-class required runtime dep (pyproject.toml + scripts/setup.sh + CLAUDE.md) so Plan 14-02 can `import blingfire` without a runtime pip hunt.**

## Performance

- **Duration:** ~4 min
- **Started:** 2026-04-18T14:15:52Z
- **Completed:** 2026-04-18T14:19:47Z
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments

- **FIDL-03 live** in REQUIREMENTS.md (line 121 bullet, line 204 traceability row, line 208 footer). Phase 14 now has a declared requirement that plans 14-02/14-03/14-04 can grep against.
- **10 Phase 14 test IDs registered** in tests/TEST_REQUIREMENTS.md Section 6 — including the two M-5/M-6 pin tests (UT-033b partial-fit, UT-036b whitespace-gap offset fidelity) and FT-011/FT-012 cross-boundary regressions.
- **blingfire provisioned by `scripts/setup.sh`** in the required-install block (lines 138-167), mirroring the sift-kg pattern exactly — column-0 heredoc, fail-loud exit, NOT gated on INSTALL_ALL. `bash scripts/setup.sh --check` now reports `MISSING: blingfire (run without --check to install)` on a fresh box.
- **pyproject.toml gains a `[project]` table** (HEAD was pytest-only) with `blingfire>=0.1.8` as its sole dep — plus an explicit M-4 header comment clarifying that this is a PARTIAL declaration and `uv pip install -e .` alone will NOT produce a working install.
- **CLAUDE.md §Key Dependencies** alphabetically slots blingfire between NetworkX and SemHash; §Platform Requirements disk-space line adds `~10MB for blingfire`.

## Task Commits

Each task committed atomically:

1. **Task 1: Register FIDL-03 in REQUIREMENTS.md + TEST_REQUIREMENTS.md** — `00bdf3d` (docs)
2. **Task 2: Declare blingfire as core runtime dep (pyproject.toml + setup.sh + CLAUDE.md)** — `5956dbd` (feat)

## Files Created/Modified

- `.planning/REQUIREMENTS.md` — Added §Chunk Overlap (Phase 14) block (lines 119-121), v3 traceability row (line 204), updated footer (line 208). Phase 13 section untouched.
- `tests/TEST_REQUIREMENTS.md` — Added §6 Phase 14 Tests (UT-031..UT-038 + UT-033b/UT-036b + FT-011/FT-012) between existing FT-010 entry and §4 Traceability Matrix. All Phase 13 entries preserved verbatim.
- `pyproject.toml` — Wrote a new `[project]` table with M-4 header comment documenting the partial-declaration intent. Existing `[tool.pytest.ini_options]` preserved verbatim.
- `scripts/setup.sh` — Inserted a 29-line blingfire required-install block between the sift-kg `fi` (line 136) and the `# RDKit (optional)` header. Column-0 heredoc style mirrors sift-kg. No regression to sift-kg/RDKit/Biopython blocks.
- `CLAUDE.md` — Added one bullet to §Key Dependencies (between NetworkX and SemHash) plus appended `~10MB for blingfire` to the §Platform Requirements disk-space line.

## Verification Results

- `grep -q 'FIDL-03' .planning/REQUIREMENTS.md` → PASS (3 occurrences — bullet + row + footer)
- `grep -q '^### Chunk Overlap (Phase 14)' .planning/REQUIREMENTS.md` → PASS
- `grep -q '^| FIDL-03 | Phase 14 | 14-01, 14-02, 14-03, 14-04 | Pending |'` → PASS
- `grep -q 'Last updated: 2026-04-18'` → PASS
- `grep -c 'UT-03' tests/TEST_REQUIREMENTS.md` → 12 (≥ 10 required)
- `grep -q 'UT-033b' && grep -q 'UT-036b' && grep -q 'FT-011' && grep -q 'FT-012'` → all PASS
- `grep -q '^## 6. Phase 14 Tests (Chunk Overlap)'` → PASS
- `grep -q 'expected.json' tests/TEST_REQUIREMENTS.md` → PASS (FT-012 file-backed floor)
- `grep -q 'monkeypatch.setitem' tests/TEST_REQUIREMENTS.md` → PASS (UT-035 B-3 fix doc'd)
- `grep -q 'cont\.' tests/TEST_REQUIREMENTS.md` → PASS (UT-036 D-12 pin)
- `python3 -c "import tomllib; ..."` → `['blingfire>=0.1.8']`
- `grep -Eq 'ONLY the phase-14|partial declaration'` → PASS (M-4 comment present)
- `bash -n scripts/setup.sh` → exit 0 (m-1 column-0 heredoc parses correctly)
- `bash scripts/setup.sh --check` → reports `MISSING: blingfire (run without --check to install)` on planner's box (blingfire not installed; installation is left to operators via `scripts/setup.sh` without `--check`)
- No regression: `grep -c 'FIDL-02' .planning/REQUIREMENTS.md` → 6 (Phase 13 untouched), `grep -c 'uv pip install sift-kg' scripts/setup.sh` → 2 (sift-kg block intact, second hit is inside its heredoc — same pattern this plan adopted for blingfire)

## Deviations from Plan

**None** — plan executed exactly as written.

One spec nuance worth noting (not a deviation): the acceptance criterion `grep -c 'uv pip install blingfire' scripts/setup.sh` equals 1 counted literal matches; the actual count is 2 because the plan explicitly directs us to "mirror the exact heredoc + exit 1 error-handling pattern used by sift-kg," and the sift-kg block itself has 2 matches of `uv pip install sift-kg` (once as the actual command, once as diagnostic text inside the EOF heredoc). Pattern conformance was prioritized over the literal grep count per the plan's explicit "mirror the sift-kg pattern exactly" guidance.

## Authentication Gates

None.

## Known Stubs

None — this plan touches only documentation/config and declares a dep; no UI/data surfaces involved.

## blingfire Install Status (Planner's Box)

```
$ uv pip show blingfire
NOT INSTALLED on planner's box (setup --check confirmed MISSING)
```

The next operator to run `bash scripts/setup.sh` (without `--check`) on this checkout will trigger the install. Plan 14-02's executor will provision it as the first step before touching `core/chunk_document.py`.

## Line-Number Anchors (for downstream plans)

| File | Lines | Content |
|------|-------|---------|
| `.planning/REQUIREMENTS.md` | 119-121 | FIDL-03 §Chunk Overlap (Phase 14) block |
| `.planning/REQUIREMENTS.md` | 204 | FIDL-03 row in v3 traceability table |
| `.planning/REQUIREMENTS.md` | 208 | Updated footer (2026-04-18 — FIDL-03 added) |
| `pyproject.toml` | 1-10 | M-4 partial-declaration header comment |
| `pyproject.toml` | 12-19 | `[project]` table with blingfire dep |
| `scripts/setup.sh` | 138-167 | blingfire required-install block |
| `CLAUDE.md` | 52 | §Key Dependencies bullet |
| `CLAUDE.md` | 79 | §Platform Requirements disk-space line |
| `tests/TEST_REQUIREMENTS.md` | `## 6. Phase 14 Tests` | 10 test IDs (UT-031..UT-038, UT-033b, UT-036b, FT-011, FT-012) |

## Self-Check: PASSED

- `.planning/phases/14-chunk-overlap/14-01-SUMMARY.md` — FOUND
- `.planning/REQUIREMENTS.md` — FOUND (FIDL-03 present)
- `tests/TEST_REQUIREMENTS.md` — FOUND (§6 present)
- `pyproject.toml` — FOUND (blingfire>=0.1.8 declared)
- `scripts/setup.sh` — FOUND (blingfire block present, bash -n passes)
- `CLAUDE.md` — FOUND (blingfire bullet present)
- Commit `00bdf3d` — FOUND in git log
- Commit `5956dbd` — FOUND in git log
