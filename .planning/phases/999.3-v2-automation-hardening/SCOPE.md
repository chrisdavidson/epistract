# Phase 999.3 — V2 Automation Hardening [P3 BACKLOG]

**Goal:** A user can run all V2 validation scenarios (S1-S6 drug-discovery + contracts) through `/epistract:ingest` + downstream commands with **zero permission prompts** and have a canonical copy-paste allow-list committed to the repo, documented in `docs/showcases/drug-discovery-v2.md`.

**Source:** Two tooling todos captured during the autonomous V2 scenario runs on 2026-04-13:
- `2026-04-13-auto-approve-permissions-for-v2-scenario-runs-and-document.md`
- `2026-04-13-v2-automation-friction-log.md`

Both todos have now been consolidated into this scope document and archived to `.planning/todos/done/`.

## Scope

### Track A — Finalize `.claude/settings.local.json` allow-list

Capture every command pattern observed during S1 → S6 + contracts runs into a generalized wildcard allow-list. Categories observed:

1. `Bash(PYTHONPATH=. python3:*)` — env-var-prefixed Python invocations (already added during S3 run, carryover)
2. `Bash(python3 core/*.py *)` — post-v2.0 reorg path (replaces the `scripts/*.py` pattern from pre-v2.0 runs)
3. `Bash(python3 domains/*/validate_*.py *)` — per-domain validator invocations
4. `Bash(python3 tests/regression/run_regression.py *)` — regression runner
5. `Bash(python3 -c *)` — inline Playwright screenshot scripts (per-scenario paths vary)
6. `Bash(find tests/corpora -maxdepth 2 *)` — corpus inspection
7. `Bash(wc -w tests/corpora/*/docs/*.txt)` — corpus word counts
8. `Bash(cp tests/corpora/*/output-v2/screenshots/*.png tests/scenarios/screenshots/:*)` — screenshot copy
9. `Write(//Users/umeshbhatt/code/epistract/**)` + `Edit(//Users/umeshbhatt/code/epistract/**)` — repo-scoped file creation / modification

**Acceptance:** A clean run of all 7 scenarios (`/epistract:ingest tests/corpora/01_picalm_alzheimers/docs` etc.) triggers zero permission prompts.

### Track B — Documentation

Add a `## Automating V2 Runs — Permission Allow-List` section to `docs/showcases/drug-discovery-v2.md` (or split into a standalone `docs/runbook-v2-validation.md` if the showcase doc gets too long). The section must include:

1. **Canonical allow-list** — copy-paste block with one line per pattern + rationale
2. **`--dangerously-skip-permissions` alternative** — document the "just run all 7 scenarios" button with explicit safety caveats
3. **Cross-references** — link from `tests/scenarios/scenario-01-picalm-alzheimers-v2.md` back to the allow-list section

### Track C — Path-sensitivity audit

Pre-v2.0 allow-list patterns referenced `scripts/*.py`. Post-v2.0 reorg, the canonical paths are `core/*.py` and `domains/*/validate_*.py`. Audit `.claude/settings.local.json` for any remaining pre-v2.0 patterns that no longer match anything, and either:
- Remove them (dead allow-list entries)
- Update them to the post-v2.0 path

## Success criteria sketch

1. `.claude/settings.local.json` covers every command that `/epistract:ingest` + `/epistract:build` + `/epistract:view` + `/epistract:validate` + `/epistract:epistemic` issue on the current codebase
2. `docs/showcases/drug-discovery-v2.md` (or `docs/runbook-v2-validation.md`) has a "zero-prompt recipe" section
3. A user cloning the repo and running `scripts/setup.sh` then `/epistract:ingest` on any of the 7 pinned scenarios gets through the full pipeline without a single approval prompt
4. Dead pre-v2.0 allow-list entries removed or updated

## Out of scope

- Changing anything about the scenarios themselves — they already passed V2 regression (Phase 11)
- Adding scenarios or domains — this is pure automation polish
- `--dangerously-skip-permissions` as the default — document it, don't prescribe it

## Depends on

- Phase 11 complete (V2 scenarios exist) — ✓ already complete
- Nothing else. Can run in parallel with any v3.0 phase.

## References

- Todo 1: `.planning/todos/done/2026-04-13-auto-approve-permissions-for-v2-scenario-runs-and-document.md`
- Todo 2: `.planning/todos/done/2026-04-13-v2-automation-friction-log.md`
- Current allow-list: `.claude/settings.local.json`
- V2 showcase doc: `docs/showcases/drug-discovery-v2.md`

## Priority

**P3 BACKLOG** — tooling polish, no code-correctness impact, no user-facing bug. Can wait until the v3.0 Graph Fidelity phases (14-20) settle. Filed under 999.x to match the existing backlog parking-lot convention.
