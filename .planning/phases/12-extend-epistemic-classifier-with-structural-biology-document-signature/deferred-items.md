# Deferred Items — Phase 12

Out-of-scope issues discovered during Plan 12-01 execution but NOT fixed (per GSD
deviation-rules scope boundary). Log them here so a future phase can address.

## Pre-existing Lint/Format Violations (not introduced by Plan 12-01)

Confirmed pre-existing by stashing the Plan 12-01 changes and re-running ruff:

### `tests/test_unit.py`

- `tests/test_unit.py:138:12: F401 [*] \`importlib\` imported but unused` — unused import in test fixture.
- Multi-line `assert (len(domain.entity_types) == 17), f"..."` lines and various other
  format drift that ruff format would reformat. None of these lines are touched by
  Plan 12-01.

### `core/domain_wizard.py` (pre-existing, in functions NOT modified by 12-01)

Ruff format would reformat the following functions — all of which exist verbatim before
Plan 12-01 and are not touched by the FIDL-01 fix:

- `validate_generated_epistemic` (lines ~644) — `tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False,)` and
  `importlib.util.spec_from_file_location(..., str(tmp_path),)` trailing-comma blocks.
- `analyze_documents` (lines ~757) — list comprehension line-break.
- `generate_domain_package` (lines ~807, ~827) — trailing-comma arg blocks in calls to
  `generate_domain_yaml`, `generate_skill_md`, `generate_epistemic_py`,
  `generate_reference_docs`, `write_domain_package`.

### Proposed remediation

Run `ruff format core/ tests/` in a dedicated chore commit (e.g., a `chore(format):` quick
task) separate from this phase. Not done in Plan 12-01 because those lines are outside the
scope of the FIDL-01 fix and the GSD scope-boundary rule forbids touching unrelated code
during task execution.

## Verification

```bash
# Confirms pre-existing (git stash drops Plan 12-01 edits, ruff still complains):
git stash && ruff check tests/test_unit.py; ruff format --check core/domain_wizard.py; git stash pop
```
