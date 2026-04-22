---
phase: 18-per-domain-epistemic-and-validator-extensibility
plan: 01
subsystem: "per-domain extensibility (CUSTOM_RULES dispatch + validation_dir discovery + auto-validator hook)"
tags: [FIDL-07, custom-rules, validation, domain-resolver, label-epistemic, run-sift, phase-18]
requires: [FIDL-06]
provides:
  - "core.domain_resolver.get_validation_dir(name) -> Path | None"
  - "resolve_domain(name) return dict additive 'validation_dir' key"
  - "core.label_epistemic.analyze_epistemic CUSTOM_RULES iteration with per-rule try/except"
  - "core.run_sift.cmd_build post-build validation dispatch + validation_report.json"
  - "domains/drug-discovery/validation/run_validation.py convention entry point"
affects:
  - core/domain_resolver.py
  - core/label_epistemic.py
  - core/run_sift.py
  - domains/drug-discovery/validation/run_validation.py
  - tests/test_unit.py
  - tests/TEST_REQUIREMENTS.md
  - .planning/REQUIREMENTS.md
tech-stack:
  added: []
  patterns:
    - "convention-over-configuration dispatch: getattr(mod, 'CUSTOM_RULES', []) mirrors the existing analyze_<slug>_epistemic convention — no new YAML DSL, no plugin registry"
    - "per-rule try/except isolation (rule failures write a status='error' record but do NOT abort the phase) — axmp-compliance resilience contract"
    - "dynamic module loading via importlib.util.spec_from_file_location reused from core.label_epistemic._load_domain_epistemic (single pattern, two call sites)"
    - "additive return-dict keys (validation_dir joins name/dir/yaml_path/skill_path/schema) — zero regression for existing callers of resolve_domain"
    - "absence-is-no-op: domains without CUSTOM_RULES produce claims_layer.json without a custom_findings key (not empty-dict) so V2 baseline JSON is byte-identical"
key-files:
  created:
    - domains/drug-discovery/validation/run_validation.py
    - .planning/phases/18-per-domain-epistemic-and-validator-extensibility/18-01-SUMMARY.md
  modified:
    - core/domain_resolver.py (+35 lines: get_validation_dir + resolve_domain validation_dir key)
    - core/label_epistemic.py (+40 lines: CUSTOM_RULES iteration inside analyze_epistemic)
    - core/run_sift.py (+80 lines: _load_validation_module + post-build validation dispatch in cmd_build)
    - tests/test_unit.py (+184 lines: UT-047, UT-048, UT-050 + three private helpers)
    - tests/TEST_REQUIREMENTS.md (Phase 18 section before Traceability Matrix + 3 matrix rows)
    - .planning/REQUIREMENTS.md (footer bumped; FIDL-07 row preserved as Pending)
decisions:
  - "D-01/D-02: CUSTOM_RULES = list[callable] is the extension point; callable signature is rule(nodes, links, context) -> list[dict]. Findings merge into claims_layer.super_domain.custom_findings[rule.__name__]. No YAML DSL — Python callables are strictly more powerful."
  - "D-03: resolve_domain() return dict gains a 6th additive key 'validation_dir' (str | None). All five pre-existing keys preserved byte-identically. get_validation_dir() is the standalone discovery helper."
  - "D-04: cmd_build dispatches validation for BOTH explicit --domain AND the default (drug-discovery) path, so legacy `cmd_build <out>` calls also trigger the validator."
  - "D-07 (backward-compat): absent CUSTOM_RULES → empty list → no custom_findings key added to claims_layer. V2 baseline JSON is byte-identical when no domain has adopted the hook. Gate: test_workbench + test_e2e pass count unchanged (94 → 97 pre/post, delta entirely from the 3 new UTs)."
  - "D-08 (silent skip): domains without a validation/ dir (e.g. contracts) produce NO validation_report.json and emit NO stderr warning. Absence of a validator is not a warning condition."
  - "D-09 / D-15 (rule isolation): per-rule try/except records {status: 'error', error: str(e)} on failure. UT-050 gates this — broken_rule coexists with good_rule_a + good_rule_b in custom_findings, analyze_epistemic does not re-raise."
  - "D-18 (UPDATE-in-place traceability): FIDL-07 row was pre-registered in REQUIREMENTS.md during the roadmap pass; this plan's Task 1 only bumps the footer date. grep -c '^| FIDL-07 |' invariant = 1. Plan 18-02 will flip Pending → Complete on the same row (never duplicate)."
metrics:
  duration: "approx 15 min"
  tasks_completed: 4
  files_modified: 6
  files_created: 2
  tests_added: 3
  commits: 4
  completed: "2026-04-22"
---

# Phase 18 Plan 1: Per-Domain Extensibility Infrastructure Summary

Ship the per-domain extensibility hooks (FIDL-07 Part A) that let domains author custom epistemic rules via a plain Python `CUSTOM_RULES: list[callable]` attribute, and let `cmd_build` auto-discover and run an optional `validation/run_validation.py` convention entry point. Three RED-first unit tests (UT-047 dispatch, UT-048 resolution, UT-050 isolation) pin the new behavior.

## What Changed

- **`core/domain_resolver.py`** gains a new public `get_validation_dir(domain_name)` helper that returns `<domain_dir>/validation` iff that directory contains `run_validation.py`, else `None` (silent — missing validators are not warning conditions per D-08). `resolve_domain(name)` now returns a six-key dict: the five pre-existing keys (`name`, `dir`, `yaml_path`, `skill_path`, `schema`) preserved byte-identically plus the additive `validation_dir: str | None`. All existing callers keep working without modification.
- **`core/label_epistemic.analyze_epistemic`** iterates `getattr(domain_mod, 'CUSTOM_RULES', [])` after the three-branch domain dispatch (slug → generic → biomedical fallback) and before the claims_layer serialization. Each rule is invoked as `rule(nodes, links, context)` with `context = {'output_dir', 'graph_data', 'domain_name': effective_domain}`. Findings merge into `claims_layer['super_domain']['custom_findings'][rule.__name__]`. Per-rule `try/except` records `{status: 'error', error: str(e)}` on failure and continues — one bad rule cannot break the phase.
- **`core/run_sift.py`** gains a private `_load_validation_module(validation_dir)` helper that mirrors `core.label_epistemic._load_domain_epistemic` via `importlib.util.spec_from_file_location`. `cmd_build` dispatches validation after community labeling and before the final print: for both explicit `--domain` and the default-domain (drug-discovery) path, it looks up `resolve_domain(...)['validation_dir']`, and if present dynamically loads the module, calls `run_validation(output_dir)`, and writes the return dict to `<output_dir>/validation_report.json`. Validator failures write an error-status report but do NOT abort the build (D-04).
- **`domains/drug-discovery/validation/run_validation.py`** (new, 95 lines) iterates `<output_dir>/extractions/*.json`, walks each extraction's entities, validates any `CHEMICAL_STRUCTURE` entity's `attributes.smiles` (or `canonical_smiles`) via the sibling `validate_smiles()` function, and aggregates into `{status, documents_validated, total_smiles_checked, invalid_smiles, errors}`. RDKit-optional: returns `{"status": "skipped", "reason": "RDKit not installed"}` when the optional dep is missing.
- **Three new unit tests** (`test_custom_rules_dispatch`, `test_get_validation_dir_resolution`, `test_rule_failure_isolation`) land RED (KeyError / ImportError) in Task 2 and flip GREEN in Task 3. All three use only `tmp_path` — no writes to the real `domains/` dir. UT-050 is the non-negotiable isolation gate: broken_rule's error record coexists with good_rule_a + good_rule_b findings, and `analyze_epistemic` does not re-raise.
- **`tests/TEST_REQUIREMENTS.md`** gains a new Phase 18 section before the Traceability Matrix heading, plus three matrix rows. UT-049 and FT-019 are deliberately absent (deferred to Plan 18-02 — structural doctype + end-to-end).
- **`.planning/REQUIREMENTS.md`** footer bumped to Phase 18 / Plan 18-01. FIDL-07 row preserved byte-identical as Pending (UPDATE-in-place: `grep -c '^| FIDL-07 |'` invariant stays at 1).

## Reference Patterns Followed

- **Phase 14 `__getattr__` / Phase 15/16/17 helper-factoring pattern:** `get_validation_dir` is the Phase 18 equivalent — a single-purpose pure helper consumed by `resolve_domain` (for the additive dict key) and `cmd_build` (for the dispatch hook). Keeps discovery logic in one place.
- **Phase 17 D-09 UPDATE-in-place traceability:** FIDL-07 row was pre-registered during the roadmap pass; Task 1 only bumps the footer. Plan 18-02 will flip Pending → Complete by editing the same line — no duplicate row ever.
- **RED-first TDD (Phase 13/14/16/17 precedent):** Two-commit sequence — test commit (Task 2: all three RED) → feat commit (Task 3: all three GREEN). Clean bisect path, TDD discipline visible in `git log --oneline`.
- **Convention-over-configuration dispatch:** Mirrors the existing `analyze_<slug>_epistemic` convention — no new YAML DSL, no plugin registry, no entry_points rework. `getattr(mod, 'CUSTOM_RULES', [])` means missing attribute = empty list = zero diff for legacy domains.

## FIDL-07 Status Progression

Current state: `| FIDL-07 | Phase 18 | 18-01, 18-02 | Pending |`

Plan 18-02 will add:
- Structural doctype signals in `core/label_epistemic.infer_doc_type` + `domains/drug-discovery/epistemic.py:infer_doc_type` (D-05): `PDB_PATTERN`, `CRYSTAL_PATTERN`, `"cryo-EM"`, resolution-in-Å signals.
- `classify_epistemic_status` ≥0.9 structural short-circuit — crystallography reports literal facts, not hypotheses (D-06).
- Wizard `generate_epistemic_py` emits `CUSTOM_RULES: list = []` stub with example comment (D-10).
- UT-049 (structural doctype detection) (D-14) and FT-019 (end-to-end: contracts baseline unchanged + drug-discovery PDB doc in corpus → `document_type: "structural"` + `validation_report.json` exists) (D-16).
- `docs/known-limitations.md §Per-Domain Extensibility (FIDL-07)` append (D-19).
- `commands/ingest.md` Step 5 (post-extraction validation) prose update.
- FIDL-07 status flip to `| FIDL-07 | Phase 18 | 18-01, 18-02 | Complete |`.

## Non-obvious Decisions

- **Absent-CUSTOM_RULES produces NO `custom_findings` key** (not an empty dict). This is the D-07 backward-compatibility contract: V2 baseline claims_layer.json is byte-identical when no domain has adopted the hook. Choosing the empty-dict alternative would have polluted every existing baseline fixture and broken the D-17 regression gate. The `setdefault` pattern in `analyze_epistemic` only runs inside the `if custom_rules:` guard.
- **`cmd_build` validation dispatch fires for BOTH explicit `--domain` AND the default path.** When `domain_name` is None, `cmd_build` already defaults to drug-discovery for `load_domain`; we mirror that default here so `python run_sift.py build <out>` (no flag) also triggers the drug-discovery validator. This means _all_ drug-discovery builds now produce `validation_report.json` — intended behavior, not a side effect.
- **`run_validation.py` uses a dual-path import** (`from .validate_smiles` first, fall back to `sys.path`-injected absolute import). Dynamic loading via `spec_from_file_location` does not always set the package context correctly when the target module itself does relative imports. The fallback is defensive coding for both invocation modes (package-style via `import domains.drug-discovery.validation.run_validation`, and spec-load style via `cmd_build`'s `_load_validation_module`).
- **Per-rule error records include explicit `"status": "error"` key** so consumer UIs (Phase 20 workbench or later) can cleanly distinguish errors from findings at render time without pattern-matching on description text. This is the D-09 resilience contract made self-describing.
- **`validation_dir` is stringified in the `resolve_domain` return dict** (matching `dir`, `yaml_path`, `skill_path`) for JSON-serialization compatibility; `get_validation_dir` itself returns `Path | None` for ergonomic Python callers. UT-048 tests both shapes.

## Deferred to Plan 18-02

- **Structural doctype signals** in `core/label_epistemic.infer_doc_type` + `domains/drug-discovery/epistemic.py:infer_doc_type` (D-05): `PDB_PATTERN`, `CRYSTAL_PATTERN`, cryo-EM signals.
- **`classify_epistemic_status` ≥0.9 structural short-circuit** in drug-discovery (D-06).
- **Wizard `generate_epistemic_py`** emitting `CUSTOM_RULES: list = []` stub + example comment (D-10).
- **UT-049** (structural doctype detection) and **FT-019** (end-to-end build with PDB-prefixed synthetic doc + validation_report.json existence).
- **`docs/known-limitations.md §Per-Domain Extensibility (FIDL-07)`** append (D-19).
- **`commands/ingest.md` Step 5** (post-extraction validation) prose update.
- **FIDL-07 flip** to `| FIDL-07 | Phase 18 | 18-01, 18-02 | Complete |`.

## V2 Baseline Regression Gate — PASSED

Pre-Phase-18: `pytest tests/test_unit.py tests/test_workbench.py tests/test_e2e.py -q` → **94 passed, 1 failed, 4 skipped**.

Post-Task-3: same command → **97 passed, 1 failed, 4 skipped**. Delta = +3 passes (exactly the three new UTs), zero new failures. The single failing test (`test_schema_expansion` on contract domain — expects COMMITTEE/PERSON/EVENT/STAGE/ROOM entity types that were never added to contract schema) is pre-existing Phase-15-era expectation drift, unchanged by this plan.

## Commits

1. `5e54560` — `docs(18-01): register FIDL-07 traceability + UT-047/UT-048/UT-050`
2. `c9fd217` — `test(18-01): add UT-047/UT-048/UT-050 RED for FIDL-07 extensibility`
3. `9fd379f` — `feat(18-01): CUSTOM_RULES dispatch + validation_dir discovery + auto-validator hook (FIDL-07)`
4. (this commit) — `docs(18-01): complete per-domain extensibility infra plan`

## Self-Check: PASSED

- UT-047, UT-048, UT-050 all GREEN (3/3 passed)
- V2 regression gate holds: 97 passed / 1 failed (pre-existing) / 4 skipped (zero delta in pre-existing tests)
- `grep -c '^| FIDL-07 |' .planning/REQUIREMENTS.md` = 1 (invariant)
- `grep -c '^### UT-049' tests/TEST_REQUIREMENTS.md` = 0 (correctly deferred to 18-02)
- `grep -c '^### FT-019' tests/TEST_REQUIREMENTS.md` = 0 (correctly deferred to 18-02)
- `resolve_domain('drug-discovery')` returns a 6-key dict; `validation_dir` points at the new run_validation.py
- `cmd_build` → `validation_report.json` wire-up verified via import-smoke: `_load_validation_module(vdir)` loads a module with a `run_validation` callable
- Plan 18-01 complete — ready to unblock Plan 18-02 (structural doctype + wizard + known-limitations + FIDL-07 flip).
