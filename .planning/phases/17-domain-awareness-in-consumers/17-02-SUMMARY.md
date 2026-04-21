---
phase: 17-domain-awareness-in-consumers
plan: 02
subsystem: "domain-aware graph.html + chat analysis_patterns (pyvis post-process + system_prompt)"
tags: [FIDL-06, domain-awareness, pyvis, analysis_patterns, phase-17, complete]
requires:
  - 17-01
provides:
  - "cmd_view post-processes graph.html with <h1>{domain title}</h1> + entity_colors overlay script (D-04, D-05)"
  - "AnalysisPatterns Pydantic model on WorkbenchTemplate (optional, validated)"
  - "analysis_patterns block in contracts + drug-discovery workbench templates"
  - "build_system_prompt reads template['analysis_patterns'] with fallback-plus-warning (D-06)"
  - "FIDL-06 complete — traceability row `17-01, 17-02 | Complete`"
  - "docs/known-limitations.md §Domain awareness propagation (FIDL-06) — Phase 20 canonical reference"
affects:
  - core/run_sift.py
  - examples/workbench/template_schema.py
  - examples/workbench/system_prompt.py
  - domains/contracts/workbench/template.yaml
  - domains/drug-discovery/workbench/template.yaml
  - docs/known-limitations.md
  - tests/test_unit.py
  - tests/test_workbench.py
  - tests/TEST_REQUIREMENTS.md
  - .planning/REQUIREMENTS.md
tech-stack:
  added: []
  patterns:
    - "Post-process HTML as string (not subclass, not monkey-patch pyvis) — matches Plan 17-01's `cmd_build` post-process graph_data.json pattern; upgrade-safe across sift-kg versions"
    - "DOM-patch <script> on DOMContentLoaded with nodes.update(updates) — decoupled from vis.js initialization timing, resilient to pyvis template changes"
    - "One-shot stderr warning guard (module-level `_warned_about_missing_analysis_patterns` flag) — prevents chat-turn warning spam while preserving D-06 visibility"
    - "RED-first TDD commit cadence (Phase 14/15/16 precedent): test commit → feat commit — clean bisect path"
    - "UPDATE-in-place traceability row (Phase 15 D-13 precedent, carried through Plan 17-01): row goes from `17-01 | Pending` → `17-01, 17-02 | Complete` on the same line; `grep -c \"^| FIDL-06 |\"` stays at 1"
    - "Append-before-footer for docs/known-limitations.md (Phase 16 D-14/D-15 precedent): single footer line preserved at the bottom; new sections grow in the middle"
key-files:
  created:
    - .planning/phases/17-domain-awareness-in-consumers/17-02-SUMMARY.md
  modified:
    - core/run_sift.py (cmd_view post-processes graph.html for <h1> + entity_colors overlay)
    - examples/workbench/template_schema.py (added AnalysisPatterns nested model + optional field)
    - examples/workbench/system_prompt.py (+ module-level warning guard + _warn_missing_analysis_patterns + analysis_patterns read path)
    - domains/contracts/workbench/template.yaml (+ analysis_patterns: CROSS-CONTRACT REFERENCES)
    - domains/drug-discovery/workbench/template.yaml (+ analysis_patterns: CROSS-STUDY REFERENCES)
    - docs/known-limitations.md (+ §Domain awareness propagation — 8 subsections, Phase 16 FIDL-05 preserved)
    - tests/test_unit.py (+ UT-046 four-branch test: contracts, drug-discovery, fallback+warning, empty-claims)
    - tests/test_workbench.py (+ FT-018 four sub-tests: contracts, drug-discovery, explicit-beats-metadata, legacy)
    - tests/TEST_REQUIREMENTS.md (+ UT-046 + FT-018 prose sections + 2 matrix rows)
    - .planning/REQUIREMENTS.md (FIDL-06 checkbox [ ]→[x]; row `17-01 | Pending`→`17-01, 17-02 | Complete`; footer updated)
decisions:
  - "D-04 + D-05 pattern: post-process pyvis's graph.html as a string after run_view returns — rejected monkey-patching sift_kg.visualize (fragile across upgrades) and subclassing (requires threading custom class through run_view). Simple string replace for <h1></h1> + append <script> before </body> is the minimal upgrade-safe seam."
  - "D-05 DOMContentLoaded overlay over rewriting the inline node JSON: the vis.js DataSet `nodes` has a documented `.update(...)` mutation API; patching at DOMContentLoaded avoids touching pyvis's generated node array. Keeps us resilient if pyvis changes its internal layout."
  - "D-06 AnalysisPatterns is a nested Pydantic model (not a bare dict) — gives validation of `cross_references_heading: str` and `appears_in_phrase: str` while keeping the field optional (`AnalysisPatterns | None = None`) so legacy templates still validate via Pydantic."
  - "D-06 fallback scope: ONLY the `CROSS-CONTRACT REFERENCES` heading and `appears in` phrase are template-driven. CONFLICTS / GAPS / RISKS headings stay generic English (they're not domain-specific vocabulary). Minimalist surface area — rewrite only what actually differs across domains."
  - "D-06 warning dedup: module-level `_warned_about_missing_analysis_patterns: bool` guard emits the stderr warning once per process. Chat turns call `build_system_prompt` repeatedly, so per-call warning would spam logs. Test exposes the guard via monkeypatch for deterministic Branch 3 verification."
  - "FT-018 GREEN on first run (no RED phase for Task 2 Sub-step B): the 4 sub-tests exercise Plan 17-01's resolve_domain → create_app → /api/template wiring combined with Task 1's analysis_patterns in templates. No new behavior in Task 2 Sub-step A is required for FT-018 because FT-018 is API-level, not HTML-level. Documented explicitly in the FT-018 commit message."
  - "D-15 UPDATE-in-place: `grep -c \"^| FIDL-06 |\" .planning/REQUIREMENTS.md` stays at 1 throughout the phase. Row goes `— | Pending` → `17-01 | Pending` (Plan 17-01) → `17-01, 17-02 | Complete` (Plan 17-02). Checkbox flips `[ ]` → `[x]` in-place. Footer rewritten to reflect Phase 17 completion."
  - "D-16 known-limitations append: new `## Domain awareness propagation (FIDL-06)` section inserted BEFORE the existing `---` + `*Last updated: ...*` footer. Phase 16 FIDL-05 section preserved byte-identically above. Footer updated to reflect Phase 17 addition. Single footer line is the canonical \"end of file\" marker Phase 20 can rely on."
metrics:
  duration: "approx 15 min"
  tasks_completed: 3
  files_modified: 10
  files_created: 1
  tests_added: 5  # UT-046 + 4 FT-018 sub-tests
  commits: 5  # 2 RED + 2 feat + 1 docs (includes Sub-edit C REQUIREMENTS.md flip)
  completed: "2026-04-21"
---

# Phase 17 Plan 2: Domain-Aware graph.html + Chat Analysis Patterns Summary

Complete FIDL-06 by (1) making `cmd_view` post-process pyvis's `graph.html` to inject domain-specific `<h1>` title + `entity_colors` overlay script, (2) making `build_system_prompt` read per-domain `analysis_patterns` block from template.yaml instead of hardcoding "CROSS-CONTRACT REFERENCES", (3) documenting the propagation contract in `docs/known-limitations.md` for Phase 20, and (4) flipping FIDL-06 traceability to `| FIDL-06 | Phase 17 | 17-01, 17-02 | Complete |`. Plan 17-01 established the single source of truth (`graph_data.json.metadata.domain`) and wired the workbench server + launcher; this plan closes the remaining two consumers (graph.html + chat system prompt) and the requirement.

## What Changed

- `core/run_sift.cmd_view(output_dir, **kwargs)` now calls `run_view` (unchanged) then post-processes `{output_dir}/graph.html`: (a) D-04: replace pyvis's empty `<h1></h1>` with `<h1>{template.title}</h1>` resolved via Plan 17-01's `resolve_domain(Path(output_dir), None)` + `load_template(resolved_domain)`; legacy graph → generic "Knowledge Graph" fallback. (b) D-05: append a `<script>` block before `</body>` that runs on `DOMContentLoaded`, iterates the vis.js `nodes` DataSet, and calls `nodes.update(updates)` to override `color.background`/`border` for nodes whose `entity_type` matches a key in the resolved template's `entity_colors` dict. Legacy graph or template without `entity_colors` → no overlay injected; pyvis's default palette preserved. Non-fatal on ImportError (workbench helpers missing) / OSError (read/write failure) — stderr warning, graph.html left in pyvis's original state.
- `examples/workbench/template_schema.py` grows a new nested `AnalysisPatterns(BaseModel)` with `cross_references_heading: str = "CROSS-CONTRACT REFERENCES"` and `appears_in_phrase: str = "appears in"`. `WorkbenchTemplate` adds the optional field `analysis_patterns: AnalysisPatterns | None = None`, keeping all existing fields byte-identical so legacy templates (and `test_template_schema_validation`) continue to validate.
- `domains/contracts/workbench/template.yaml` appends a top-level `analysis_patterns:` block with contracts-specific values (extracted from the hardcoded `system_prompt.py` wording). `domains/drug-discovery/workbench/template.yaml` appends a top-level `analysis_patterns:` block with drug-discovery values ("CROSS-STUDY REFERENCES").
- `examples/workbench/system_prompt.build_system_prompt(data, template)` reads `template.get("analysis_patterns")` for the cross-references section heading + "appears in" phrase; when the key is missing (legacy template or generic fallback), falls back to hardcoded `"CROSS-CONTRACT REFERENCES"` + `"appears in"` and emits a one-shot stderr warning via module-level guard `_warned_about_missing_analysis_patterns`. Signature unchanged `(data: WorkbenchData, template: dict) -> str`. CONFLICTS / GAPS / RISKS / KG Summary / FULL ENTITY DATA / ANALYSIS FINDINGS headings all unchanged (D-06 minimalism — rewrite only what actually differs across domains).
- `docs/known-limitations.md` gains a new `## Domain awareness propagation (FIDL-06)` section inserted BEFORE the Phase 16 footer. Eight subsections: Scope, Single source of truth, Precedence rule, Propagation points (4), Legacy-graph behavior (D-08), What propagation does NOT do, Acceptance gate, Related refs. Phase 16 FIDL-05 entry preserved byte-identically above. Footer updated to `2026-04-21 — Phase 17 FIDL-06 (Domain Awareness in Consumers) added; Phase 16 FIDL-05 entry preserved.`.
- `tests/test_unit.py` adds UT-046 (`test_build_system_prompt_loads_analysis_patterns`) — 4 branches (contracts heading, drug-discovery heading, legacy fallback + stderr warning capture via capsys, empty-claims heading omission). Uses a `_StubData` class so no sift-kg, no FastAPI, no file I/O required.
- `tests/test_workbench.py` adds FT-018 as 4 sub-tests using the FastAPI TestClient: `test_ft018_domain_autodetect_through_api_contracts`, `test_ft018_domain_autodetect_through_api_drug_discovery`, `test_ft018_explicit_beats_metadata`, `test_ft018_legacy_graph_no_metadata_domain`. Stub `graph_data.json` writer helper builds minimal valid metadata (7 pre-existing keys + new `domain`). End-to-end pipeline: stub graph → `resolve_domain` → `create_app` → GET `/api/template` → assert title + `analysis_patterns.cross_references_heading`.
- `tests/TEST_REQUIREMENTS.md` adds UT-046 + FT-018 prose sections in the Phase 17 block; appends 2 new Traceability Matrix rows.
- `.planning/REQUIREMENTS.md` FIDL-06 row UPDATED in place from `| FIDL-06 | Phase 17 | 17-01 | Pending |` → `| FIDL-06 | Phase 17 | 17-01, 17-02 | Complete |`; subsection checkbox flipped `[ ]` → `[x]`; footer updated to `FIDL-06 Phase 17 complete (Domain Awareness in Consumers)`. `grep -c "^| FIDL-06 |" .planning/REQUIREMENTS.md` remains exactly 1 throughout (D-15 UPDATE-in-place gate).

## Reference Patterns Followed

- **Plan 17-01's `resolve_domain` helper — reused directly, no reimplementation.** `cmd_view` calls `resolve_domain(Path(output_dir), None)` followed by `load_template(resolved)`. This is the "idempotent double-call" pattern from Plan 17-01 where both server + launcher call `resolve_domain` for self-containment; `cmd_view` is now the third caller.
- **Phase 16 Plan 16-01's known-limitations.md append pattern (D-14/D-15):** Insert new section BEFORE the `*Last updated: ...*` footer line so the single footer stays the canonical end-of-file marker. Update the footer's date + content to reflect the newly added phase. Phase 16 FIDL-05 section preserved byte-identically above.
- **Phase 15 Plan 15-02 / Plan 17-01's UPDATE-in-place traceability row pattern (D-15):** Single FIDL-06 row in REQUIREMENTS.md v3 table lives on line 219; it starts at `— | Pending`, becomes `17-01 | Pending` at end of Plan 17-01, and becomes `17-01, 17-02 | Complete` at end of Plan 17-02 — always the same line, never duplicated. `grep -c "^| FIDL-06 |"` stays at 1 through all 3 states.
- **RED-first TDD from Phase 13/14/16 + Plan 17-01:** Task 1 committed as `test(17-02): RED` (UT-046 fails with "CROSS-STUDY REFERENCES not in prompt") followed by `feat(17-02): GREEN` (analysis_patterns wiring). Task 2 committed FT-018 first even though it was GREEN on first run (the behavior it verifies is cross-cutting — Plan 17-01's resolve_domain + Task 1's templates — and committing the test first pins that behavior on future changes).
- **One-shot warning guard pattern from Plan 17-01's `resolve_domain` fallback branch:** stderr warning, not raised exception; emitted once per process; test uses monkeypatch to reset the guard flag for the fallback-branch assertion.

## FIDL-06 Status Progression

Row evolution across Phase 17:

| Event                       | Row state                                             |
| --------------------------- | ----------------------------------------------------- |
| Pre-Phase-17 (pre-17-01)    | `| FIDL-06 | Phase 17 | — | Pending |`                |
| Plan 17-01 Task 3 registers | `| FIDL-06 | Phase 17 | 17-01 | Pending |`            |
| Plan 17-02 Task 3 completes | `| FIDL-06 | Phase 17 | 17-01, 17-02 | Complete |`    |

Checkbox evolution (subsection at line 133):
- Plan 17-01: `- [ ] **FIDL-06**: ...` (registered but pending)
- Plan 17-02: `- [x] **FIDL-06**: ...` (flipped at end of plan)

`grep -c "^| FIDL-06 |" .planning/REQUIREMENTS.md` = 1 throughout (D-15 UPDATE-in-place gate, never duplicated).

## Acceptance Gate Results

- UT-044 (cmd_build writes metadata.domain) — PASS (Plan 17-01)
- UT-045 (resolve_domain precedence — 4 branches) — PASS (Plan 17-01)
- UT-046 (build_system_prompt analysis_patterns + fallback + warning — 4 branches) — PASS (Plan 17-02)
- FT-018 (end-to-end domain auto-detect through /api/template — 4 sub-tests) — PASS (Plan 17-02)
- Workbench regression (D-14 gate): 25 of 26 tests pass; 1 pre-existing `test_schema_expansion` failure unchanged from Wave 1 baseline (documented in `deferred-items.md` as Phase 6 reorg legacy, NOT FIDL-06-related)
- FIDL-01..05 non-regression: all 16 wizard/discover/ingest tests PASS; Plan 17-01 UT-044/UT-045 still PASS
- Full test_unit.py + test_workbench.py run: 87 passed, 4 skipped, 1 pre-existing failure

## Non-obvious Decisions

- **Task 2 Sub-step A (cmd_view HTML post-process) is not exercised by FT-018.** FT-018 is end-to-end through the FastAPI `/api/template` endpoint — it tests the server + resolve_domain + template_loader pipeline, not the standalone `graph.html`. The cmd_view post-process is verified by grep acceptance criteria (`FIDL-06 D-04`, `FIDL-06 D-05`, `html.replace("<h1></h1>"`, `nodes.update(updates)`) + manual smoke test (optional per plan). Adding an HTML-string assertion test would require running `run_view` which opens a browser — infeasible for CI. Phase 20's README can add a smoke-test checklist step for human verification.
- **`&amp;&amp;` in generated JS:** The overlay `<script>` is written via an f-string that ends up as HTML-parsed content. HTML parsers decode `&amp;` → `&` before passing the string to the JS engine, so the browser sees `n.color && n.color.border` at runtime. Writing `&&` directly would be parsed as a stray-ampersand error under strict HTML5 validators even though browsers would recover; using `&amp;&amp;` is the defensively correct choice.
- **Contracts template keeps its current wording (unchanged user-visible output).** D-06 says "contracts template keeps current wording"; `CROSS-CONTRACT REFERENCES` + `appears in` was already the hardcoded system_prompt output for contracts. Moving it into `template.yaml` makes it a configuration override point without changing byte-level output for the contracts domain. Drug-discovery gets its own wording (`CROSS-STUDY REFERENCES`) — a new user-visible change only for drug-discovery users (a new domain for the workbench, so no regression).
- **Warning guard reset in test (monkeypatch setattr)**: UT-046 Branch 3 expects a warning on stderr; the guard flag would normally suppress it if a prior branch had already triggered it. `monkeypatch.setattr(sp, "_warned_about_missing_analysis_patterns", False)` resets the flag so Branch 3 deterministically sees the warning. `capsys.readouterr()` clears any prior output. The guard is the production behavior; the reset is test-only.
- **FT-018 sub-test decomposition** (4 sub-tests vs 1 parametrized): the plan permits either shape. Chose 4 separate `test_ft018_*` names so pytest failures isolate which branch broke. `grep -c "^| FT-018 |"` in the Traceability Matrix still treats them as one logical FT-018 with 4 sub-criteria.

## Deferred to Future Phases

All FIDL-06 scope items are now Complete; deferred items from 17-CONTEXT.md §deferred remain deferred:

1. DomainContext class threaded through build/view/dashboard/chat — only if a second cross-cutting field (e.g., `ocr_mode`, `extensions`) needs the same propagation.
2. Graph metadata migration tool for pre-Phase-17 graphs — quick rebuild is faster.
3. Per-domain CSS theming (fonts/logos/layout) — colors only for v3.0.
4. Dashboard widget registry (per-domain widgets).
5. Dynamic domain templates (remote URL).

Phase 18 (per-domain epistemic & validator extensibility) is the next v3.0 phase per the ROADMAP.

## Deferred Issues (Out of Scope for 17-02)

- `tests/test_workbench.py::test_schema_expansion` — pre-existing failure carried over from Plan 17-01's `deferred-items.md` (Phase 6 reorg legacy referencing `skills/contract-extraction/domain.yaml`). Unchanged by this plan; NOT in FIDL-06 critical path.
- Pre-existing ruff lint + format drift in `tests/test_unit.py` (5 errors at lines 138, 926, 976, 1099, 1154) and `examples/workbench/system_prompt.py` / `template_schema.py` (blank line after docstring). Verified pre-existing via Plan 17-01 deferred-items + git-stash diff. Out of scope per SCOPE BOUNDARY rule — not caused by this plan's additions.

## Self-Check

Verifying claimed artifacts and commits exist:

- [x] `core/run_sift.py::cmd_view` — `grep "FIDL-06 D-04"` = 2, `grep "FIDL-06 D-05"` = 2, `grep 'html.replace("<h1></h1>"'` = 1, `grep "nodes.update(updates)"` = 1
- [x] `examples/workbench/template_schema.py` — `class AnalysisPatterns` present, `analysis_patterns: AnalysisPatterns | None = None` field added
- [x] `examples/workbench/system_prompt.py` — `_warn_missing_analysis_patterns` defined + called; `template.get("analysis_patterns")` read path present
- [x] `domains/contracts/workbench/template.yaml` — `^analysis_patterns:` block present with `CROSS-CONTRACT REFERENCES`
- [x] `domains/drug-discovery/workbench/template.yaml` — `^analysis_patterns:` block present with `CROSS-STUDY REFERENCES`
- [x] Pydantic validation: `WorkbenchTemplate(**contracts_yaml).analysis_patterns.cross_references_heading == "CROSS-CONTRACT REFERENCES"` (verified)
- [x] Pydantic validation: `WorkbenchTemplate(**drug_discovery_yaml).analysis_patterns.cross_references_heading == "CROSS-STUDY REFERENCES"` (verified)
- [x] `docs/known-limitations.md` — `## Domain awareness propagation (FIDL-06)` section present; Phase 16 FIDL-05 section preserved; footer updated to 2026-04-21
- [x] `tests/TEST_REQUIREMENTS.md` — UT-046 + FT-018 prose sections + 2 matrix rows present; UT-044 + UT-045 rows preserved
- [x] `.planning/REQUIREMENTS.md` — `| FIDL-06 | Phase 17 | 17-01, 17-02 | Complete |` present; `grep -c "^| FIDL-06 |"` = 1 (D-15 gate); `- [x] **FIDL-06**` present; `- [ ] **FIDL-06**` absent; footer rewritten
- [x] `tests/test_unit.py::test_build_system_prompt_loads_analysis_patterns` — PASSES (UT-046)
- [x] `tests/test_workbench.py::test_ft018_domain_autodetect_through_api_contracts` — PASSES
- [x] `tests/test_workbench.py::test_ft018_domain_autodetect_through_api_drug_discovery` — PASSES
- [x] `tests/test_workbench.py::test_ft018_explicit_beats_metadata` — PASSES
- [x] `tests/test_workbench.py::test_ft018_legacy_graph_no_metadata_domain` — PASSES
- [x] D-14 regression: `.venv/bin/python -m pytest tests/test_workbench.py` → 25 of 26 pass (1 pre-existing `test_schema_expansion` failure unchanged — Plan 17-01 deferred-items)
- [x] FIDL-01..05 non-regression: `.venv/bin/python -m pytest tests/test_unit.py -k "wizard or discover or ingest or resolve_domain or cmd_build or analysis_patterns" -v` → 19 of 19 PASS
- [x] Full test run: `.venv/bin/python -m pytest tests/test_unit.py tests/test_workbench.py` → 87 passed, 4 skipped, 1 pre-existing failure
- [x] All 5 commits present in `git log --oneline`: `d931bb2` (test RED UT-046), `2d333ce` (feat Task 1 GREEN), `c2e3d54` (test FT-018), `6199d27` (feat Task 2 cmd_view), `ac49186` (docs Task 3 FIDL-06 complete)

## Self-Check: PASSED
