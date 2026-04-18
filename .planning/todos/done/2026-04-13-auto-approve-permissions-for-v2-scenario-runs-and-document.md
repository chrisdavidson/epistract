---
created: 2026-04-13T19:55:53.564Z
title: Auto-approve permissions for V2 scenario runs and document the recipe
area: tooling
files:
  - .claude/settings.local.json
  - docs/showcases/drug-discovery-v2.md
  - tests/scenarios/scenario-01-picalm-alzheimers-v2.md
  - .planning/phases/11-end-to-end-scenario-validation/11-03-PLAN.md
---

## Problem

During the Phase 11-03 S1 (PICALM) run on 2026-04-13, many Bash / Edit / Write tool calls triggered permission prompts because `.claude/settings.local.json` only covers a subset of the command patterns the `/epistract:ingest` pipeline actually uses. This breaks the "fire the slash command and walk away" model the phase plan assumes, and the friction compounds across the remaining 5 drug-discovery scenarios + the contracts scenario.

The end goal is: running a V2 scenario should require zero permission approvals so the 7 runs can be batched without human babysitting. Each scenario surfaces slightly different commands (different corpora paths, different output dirs, different screenshot paths), so the allow-list needs to be generalized to wildcard patterns rather than fixed strings.

**Specific categories observed during S1 (incomplete — add to this list at every scenario):**

1. `PYTHONPATH=. python3 core/run_sift.py ...` — not covered by existing `Bash(python3:*)` because of the env-var prefix. Needed for `build`, `view`, `info`, `search`, `export`.
2. `PYTHONPATH=. python3 core/label_epistemic.py ...` — same env-var issue.
3. `python3 domains/drug-discovery/validate_molecules.py ...` — covered by `python3:*` but scoping to the epistract repo would be tighter.
4. `python3 tests/regression/run_regression.py ...` — same.
5. `python3 -c "<playwright screenshot script>"` — the inline Playwright driver for graph.html screenshots. Pattern varies per scenario (paths + viewport) but always inline Python.
6. `find tests/corpora -maxdepth 2 -type d -name "output-v2"` — `find:*` is probably needed.
7. `wc -w tests/corpora/*/docs/*.txt` — `wc:*` for corpus inspection.
8. Write tool first-use on new files under `tests/scenarios/scenario-XX-*-v2.md`, `tests/corpora/*/output-v2/screenshots/*.png`, `docs/showcases/drug-discovery-v2.md`.
9. Edit tool on `tests/regression/run_regression.py` (the resolver fix landed during S1).

Each scenario will add a few more command variants to this list. The todo is to **capture them incrementally** as we run each scenario, then fold them into `.claude/settings.local.json` + the showcase docs so future runs are fully hands-off.

## Solution

Two-track approach — track in parallel as each of S2–S6 + contracts runs:

**Track A — Settings hardening (per-scenario, incremental):**

1. After each scenario run, diff `.claude/settings.local.json` against the list of commands actually invoked during the run
2. Add the new command patterns as generalized wildcards (prefer directory-scoped: `Bash(PYTHONPATH=. python3 core/*.py *)`, `Bash(python3 domains/*/validate_*.py *)`, `Bash(python3 tests/regression/run_regression.py *)`)
3. Add `Write(/Users/umeshbhatt/code/epistract/**)` and `Edit(/Users/umeshbhatt/code/epistract/**)` once if they aren't already covered — scoping to the repo is fine since this is the user's local settings
4. Commit the settings change with message `chore(settings): allow <pattern> for Phase 11 V2 runs`
5. Next scenario run should hit fewer prompts. Iterate until zero.

**Track B — Documentation (one-shot at end of Phase 11, with incremental notes):**

1. Add a new section `## Automating V2 Runs — Permission Allow-List` to `docs/showcases/drug-discovery-v2.md` (or a standalone `docs/runbook-v2-validation.md`)
2. Include the full canonical allow-list (with rationale for each entry) so other users running V2 validation can copy-paste into their `.claude/settings.local.json`
3. Document the `--dangerously-skip-permissions` alternative for fully unattended runs, with a warning about its scope
4. Cross-reference from the Phase 11-03 plan and per-scenario V2 docs
5. Update `tests/scenarios/scenario-01-picalm-alzheimers-v2.md` retroactively with the final allow-list once it stabilizes

**Acceptance criteria:**

- [ ] Each V2 scenario run captures its command fingerprint in this todo (append under "Observed commands per scenario")
- [ ] `.claude/settings.local.json` is updated after each scenario to cover the new patterns
- [ ] Final run (contracts) triggers zero permission prompts
- [ ] Allow-list documented in `docs/showcases/drug-discovery-v2.md` with copy-paste recipe
- [ ] Retroactive update to scenario-01-v2 doc with the final list

**Observed commands per scenario** (append as we go):

### S1 — PICALM (2026-04-13) — partial capture

- `PYTHONPATH=. python3 core/run_sift.py build|view ...`
- `PYTHONPATH=. python3 core/label_epistemic.py ...`
- `python3 tests/regression/run_regression.py --baselines ... --scenario ...`
- `python3 -c "<playwright screenshot inline script>"`
- Write tool: `tests/corpora/01_picalm_alzheimers/output-v2/screenshots/graph_overview.png`, `tests/scenarios/scenario-01-picalm-alzheimers-v2.md`, `docs/showcases/drug-discovery-v2.md`
- Edit tool: `tests/regression/run_regression.py` (resolver fallback fix)

### S2 — KRAS G12C — TBD
### S3 — Rare Disease — TBD
### S4 — Immuno-Oncology — TBD
### S5 — Cardiovascular — TBD
### S6 — GLP-1 — TBD
### Contracts — TBD

## Notes

- **Scope of auto-approval:** Only scope to the epistract repo (not user home) to avoid over-granting. `Bash(cd /Users/umeshbhatt/code/epistract && *)` is too permissive.
- **Env-var prefix gotcha:** Claude Code's Bash approval matches the command string literally, so `PYTHONPATH=. python3 ...` is a different pattern from `python3 ...`. Easiest fix: add both, or export `PYTHONPATH` in the shell once via `/gsd:quick` preamble.
- **Alternative — fully unattended mode:** `claude --dangerously-skip-permissions` bypasses the allow-list entirely. Document this as the "just run all 6 scenarios" button but flag the safety tradeoff.
- This todo is linked to Phase 11-03 (E2E scenario validation) — complete the allow-list work before closing that plan.
