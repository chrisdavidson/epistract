# Phase 14 Deferred Items

Pre-existing issues discovered during Phase 14 execution. Out of scope for the plans that found them — logged here per GSD scope-boundary rules.

## 14-02

### Pre-existing ruff violations in `tests/test_unit.py`

Found during Task 2 (adding UT-031..UT-035 + UT-033b). These are ALL in code that existed on HEAD before Plan 14-02 touched the file, confirmed by `git stash` → `ruff check` cycle showing the same 5 violations with the stash applied.

- `tests/test_unit.py:138:12` — F401 `importlib` imported but unused (pre-existing top-level import)
- `tests/test_unit.py:688:5`  — E401 multiple imports on one line
- `tests/test_unit.py:738:5`  — E401 multiple imports on one line
- `tests/test_unit.py:861:5`  — F841 local variable `result` assigned but never used
- `tests/test_unit.py:916:5`  — F841 local variable `result` assigned but never used

UT-031..UT-035 + UT-033b that this plan added do not introduce new ruff errors. Fixing the pre-existing violations is orthogonal to Phase 14 FIDL-03 — defer to a future lint-cleanup pass or piggy-back on whichever plan next touches those line ranges.
