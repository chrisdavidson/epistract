---
created: 2026-04-13T22:30:00.000Z
title: V2 automation friction log — captured during autonomous S3-S6 run
area: tooling
files:
  - .claude/settings.local.json
  - docs/showcases/drug-discovery-v2.md
  - core/label_epistemic.py
  - domains/drug-discovery/epistemic.py
  - tests/regression/run_regression.py
---

## Problem

The user asked me to run S3 through contracts autonomously after fixing any automation permission issues surfaced during S2, and to keep a running note of every friction point so documentation can be updated once the full validation completes. This file is that running log. Each scenario gets an entry with observed issues, fixes applied, and remaining gaps.

Goal: by the end of the contracts scenario, the full S3–S6+contracts pipeline should run with **zero permission prompts** and any non-permission issues (epistemic classifier gaps, regression runner behavior, etc.) should be captured as standalone todos.

## Settings patches applied before this run (carryover from S1 and S2)

Already in `.claude/settings.local.json` as of start of S3:

1. `Bash(PYTHONPATH=. python3:*)` — covers cwd-based Python invocations
2. `Bash(cp tests/corpora/:*)` — covers screenshot copying to canonical dir
3. `Bash(cp tests/corpora/*/output-v2/screenshots/graph_overview.png tests/scenarios/screenshots/:*)` — narrow alt form
4. `Write(//Users/umeshbhatt/code/epistract/**)` — covers new V2 docs, screenshots, baselines
5. `Edit(//Users/umeshbhatt/code/epistract/**)` — covers in-flight fixes to regression runner, docs

Plus baseline patterns from prior sessions: `Bash(python3:*)`, `Bash(mkdir:*)`, `Bash(cat:*)`, `Bash(du:*)`, `Bash(jq:*)`, `Read(//Users/umeshbhatt/code/epistract/**)`, etc.

## Per-scenario friction log

### S3 — Rare Disease Therapeutics (TBD)

Settings changes needed: *(to be filled during run)*
Non-permission issues: *(to be filled during run)*

### S4 — Immuno-Oncology Combinations (TBD)

### S5 — Cardiovascular & Inflammation (TBD)

### S6 — GLP-1 Competitive Intelligence (TBD)

### Contracts — AKKA (TBD)

## Known gaps flagged during S1/S2 (not-yet-resolved)

1. **Phase 12** — Epistemic classifier only knows `paper` and `patent`; structural biology docs classify as `unknown`. Phase added to roadmap 2026-04-13 as low-severity.
2. **gsd-tool `phase add` bug** — On 2026-04-13, the tool assigned phase 11 when 11 already existed (duplicate directory created). Manually renamed to 12. Worth a bug report to the gsd upstream.
3. **Regression runner output-dir mapping** — Fixed during S1: `_resolve_output_dir` now prefers `output-v2/` with fallback to `output/`. No outstanding work here.

## Acceptance criteria for this log

- [ ] S3 entry filled with observed friction + fixes
- [ ] S4 entry filled
- [ ] S5 entry filled
- [ ] S6 entry filled
- [ ] Contracts entry filled (or marked "skipped — no AKKA data")
- [ ] Final `.claude/settings.local.json` allow-list documented in `docs/showcases/drug-discovery-v2.md` as a copy-paste recipe
- [ ] Track B of auto-approve todo updated with the final recipe
- [ ] This log moved to `.planning/todos/done/` once docs are updated
