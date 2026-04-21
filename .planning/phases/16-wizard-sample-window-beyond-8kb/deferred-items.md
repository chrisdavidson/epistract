# Deferred Items — Phase 16

Items surfaced during Phase 16 execution that are out of scope for this phase.

## Pre-existing lint/format issues (out-of-scope)

Discovered during Plan 16-01 Task 2 `ruff format --check` run. All pre-exist on `main` before Phase 16 changes; none are in code touched by Phase 16.

### `tests/test_unit.py`

- `tests/test_unit.py:138:12: F401` — `importlib` imported but unused (unrelated test module import).
- `tests/test_unit.py:814:5: E401` — Multiple imports on one line (Phase 14 or earlier test).
- `tests/test_unit.py:864:5: E401` — Multiple imports on one line.
- `tests/test_unit.py:987:5: F841` — Local variable `result` assigned but never used.
- `tests/test_unit.py:1042:5: F841` — Local variable `result` assigned but never used.
- `ruff format --check` wants to reformat ~8 sites (long asserts, subprocess imports, validate_molecules block) in code NOT touched by Phase 16.

All Phase 16 additions (UT-042, UT-043) pass `ruff check` and are formatted correctly on first write.

### `core/domain_wizard.py`

- `ruff format --check` wants to reformat `validate_generated_epistemic` (lines ~720+) and `generate_domain_package` (lines ~885+) — trailing-comma-split argument lists. All pre-exist on `main`; Phase 16 only added `_build_excerpts` and rewrote `build_schema_discovery_prompt`, both of which pass `ruff format --check` individually.

`ruff check core/domain_wizard.py` passes with no errors.

**Action:** Leave out of scope. A future cleanup pass (or `make format`) will address these uniformly. Fixing them during Phase 16 would muddy the Phase 16 diff.
