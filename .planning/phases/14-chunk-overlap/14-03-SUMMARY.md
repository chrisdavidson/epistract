---
phase: 14-chunk-overlap
plan: 03
subsystem: infra
tags: [chonkie, chunk-overlap, fidl-03, overlap-emit, schema-extension, tdd]

# Dependency graph
requires:
  - phase: 14-chunk-overlap
    provides: chonkie import guard, _make_chunker factory, _tail_sentences helper, OVERLAP_* constants, UT-031..UT-035 + UT-033b substrate tests (Plan 14-02)
provides:
  - Wired chonkie.SentenceChunker into _merge_small_sections::_flush (oversized-section path) with nonlocal _pending_tail cache for cross-flush M-1/M-2 overlap
  - Rewrote _split_fixed to delegate end-to-end to chonkie (D-04 #3, D-05 — one library reused)
  - Deleted _split_at_paragraphs (dead code after chonkie adoption)
  - Extended chunk JSON schema with overlap_prev_chars, overlap_next_chars, is_overlap_region, and honest per-sub-chunk char_offset (D-10, D-11)
  - Preserved D-12 (cont.) header propagation on sub-chunks 2..N
  - Post-loop correction ensures final chunk of document has overlap_next_chars=0
  - UT-036, UT-036b, UT-037, UT-038 — schema + honest-offset + ARTICLE-boundary + fallback-path tests
affects: [14-04, V2-scenario-runs]

# Tech tracking
tech-stack:
  added: []  # No new deps — chonkie already declared in 14-01/14-02
  patterns:
    - "Factory-backed call-site wiring: both _merge_small_sections::_flush (oversized path) and _split_fixed call _make_chunker(max_size) — one config touchpoint, identical behavior across split paths. Paired with _tail_sentences for cross-flush overlap (only place that helper is called)."
    - "Nonlocal cross-flush cache (M-1/M-2): _pending_tail is scoped inside _merge_small_sections as a nonlocal variable updated AT FLUSH END from the RAW buffer_text (NOT chunks[-1]['text']). This guarantees each flush's incoming overlap reflects the PREVIOUS flush's original body exactly once — no overlap-chaining across multiple flushes."
    - "Schema-extension chunk dict: HEAD had 4 keys (chunk_id, text, section_header, char_offset); post-14-03 adds overlap_prev_chars, overlap_next_chars, is_overlap_region — all present on every chunk emitted by chunk_document(), both clause-aware and fallback paths."
    - "Defensive chonkie fall-back: if chunker.chunk(buffer_text) returns [] on non-empty input (shouldn't happen for production inputs but seen in edge cases), emit the whole buffer as one chunk with the same 7 keys rather than silently dropping content."

key-files:
  created: []
  modified:
    - "core/chunk_document.py (+141/-42 net — _merge_small_sections fully rewritten with _pending_tail + chonkie delegation; _split_fixed rewritten end-to-end with chonkie; _split_at_paragraphs deleted entirely; _make_chunker docstring updated to reflect two call sites instead of three)"
    - "tests/test_unit.py (+197 lines — UT-036..UT-038 + UT-036b appended after UT-031..UT-035 + UT-033b; no existing test modified)"

key-decisions:
  - "Split Tasks 1 and 2 into separate atomic commits despite tight coupling (_split_at_paragraphs deletion depended on _split_fixed rewrite). Task 1 commit left _split_at_paragraphs in place (as still-called dead-code-in-transition by HEAD _split_fixed) so the intermediate state remained green; Task 2 commit rewrote _split_fixed and removed _split_at_paragraphs. Both commits independently pass ruff + 48 existing unit tests; this keeps per-commit-bisect honest."
  - "UT-036 input shape deviates from the plan's verify-block text: plan used single-article 'ARTICLE I. DEFINITIONS\\n\\n' + 'Sentence content here. ' * 1500, which _split_at_sections produces as 1-section → falls through to _split_fixed (fallback path), so (cont.) headers are not emitted (fallback path always produces section_header=\"\"). Rewrote UT-036 input to be multi-article so the oversized clause-aware path in _merge_small_sections::_flush exercises and emits (cont.). D-12 invariant pinned correctly."
  - "UT-036b semantics corrected from the plan's draft: plan's draft test assumed char_offset points to the START of the RAW body (post-overlap-prefix), but chonkie's start_index points to the START of the WHOLE CHUNK including the overlap prefix (chonkie's overlap is a copy starting at cc.start_index). Rewrote the invariant as source_text[char_offset:char_offset+30] == chunk.text[:30] — honest by chonkie's construction, M-6 dissolved automatically (no blank-paragraph drift possible)."
  - "Chonkie 1.6.2 quirk documented in UT-036 comment: SentenceChunker collapses highly-repeated identical sentences into a single chunk regardless of input length (verified: 'Sentence. ' * 5000 → 1 chunk at chunk_size=10000; 'Sentence content here. ' * 1500 → 4 chunks). UT-036 uses varied sentence content to avoid the collapse; this is also why the plan's Task 1 verify block (which used identical repeated sentences in a single ARTICLE) would have been a false-green in isolation."
  - "Chunk count on tests/fixtures/sample_contract_text.txt is UNCHANGED: 4 chunks on HEAD, 4 chunks post-Wave-3. Same boundaries, same section_header values, same chunk_ids. The plan's e2e-regression gate (Plan 14-04) can safely assume structural equivalence — only the provenance fields are new. Each of the 4 chunks now carries overlap_prev_chars/overlap_next_chars (0/158, 158/126, 126/91, 91/0) — cross-section overlap is active."

patterns-established:
  - "Two-commit atomic split for file-wide interdependent rewrites: when Task N's deletion depends on Task N+1's rewrite (here, _split_at_paragraphs deletion depends on _split_fixed rewrite), keep the deletion in the later commit. Both commits pass tests + ruff; the intermediate commit preserves the deleted symbol as dead-code-in-transition."
  - "Schema-extension per-path symmetry audit: after modifying two chunker paths to emit a shared 7-key schema, use `grep -c 'overlap_prev_chars' core/chunk_document.py` ≥ 2 and `grep -c 'overlap_next_chars' core/chunk_document.py` ≥ 2 to catch a missing-key regression in either path before SUMMARY."
  - "Test input canon: when a test relies on a chunker path being exercised, prefer an input that's clearly multi-section (for clause-aware) or clearly header-less (for fallback), not an edge-case boundary input that depends on an internal regex pattern matching exactly. UT-036 chose multi-article; UT-038 chose no-headers; both are unambiguous dispatches."
  - "Chonkie quirk: repeated-sentence collapse is a chonkie 1.6.x behavior, not a regression. Tests that want chonkie to split a >max_size input MUST use varied sentence content, or use _make_chunker's output directly instead of chunk_document() to bypass section dispatch."

requirements-completed: [FIDL-03]  # Partial — Plan 14-03 delivers the wiring portion of FIDL-03. The e2e boundary-straddle acceptance test (FT-011) + V2 baseline regression gate (FT-012) remain for Plan 14-04.

# Metrics
duration: 85min
completed: 2026-04-18
---

# Phase 14 Plan 03: Wire Chonkie into Chunker Split Paths Summary

**Wired chonkie.SentenceChunker into both `_merge_small_sections::_flush` (oversized clause-aware path) and `_split_fixed` (no-structure fallback), extended the chunk JSON schema with three provenance fields (`overlap_prev_chars`, `overlap_next_chars`, `is_overlap_region`) + honest per-sub-chunk `char_offset`, threaded the cross-flush `_pending_tail` cache for ARTICLE-boundary overlap (M-1/M-2), deleted the now-unused `_split_at_paragraphs`, and pinned the whole design with UT-036, UT-036b, UT-037, UT-038. Zero regressions: 52 passed / 4 skipped. Plan 14-04's e2e gates can now assume chunks carry overlap provenance end-to-end.**

## Performance

- **Duration:** ~85 min wall-clock (including initial context read across 9 files totaling ~3,500 lines, plus chonkie-quirk debugging for UT-036 input shape and UT-036b semantics correction)
- **Started:** 2026-04-18T18:53:29Z
- **Completed:** 2026-04-18T20:18:45Z
- **Tasks:** 3 (committed atomically)
- **Files modified:** 2 (core/chunk_document.py, tests/test_unit.py)

## Accomplishments

- **Oversized-section path now chonkie-backed** — `_merge_small_sections::_flush` hands `buffer_text` to `_make_chunker(max_size).chunk(buffer_text)` and maps chonkie Chunks to epistract chunk dicts. Each sub-chunk carries honest `char_offset = buffer_offset + cc.start_index` (D-11), `overlap_prev_chars` from consecutive chunk offsets (chonkie-computed intra-flush overlap), and `section_header = buffer_header if j == 0 else f"{buffer_header} (cont.)"` (D-12).
- **Cross-flush overlap cache threaded** — nonlocal `_pending_tail` initialized to `""` inside `_merge_small_sections`, populated at flush end from `_tail_sentences(buffer_text)` (RAW body — NOT `chunks[-1]["text"]`), consumed at flush start as `incoming`. UT-037 pins the raw-tail invariant: `chunks[a2_idx]["overlap_prev_chars"] == len(_tail_sentences(article_1))` — any regression to reading `chunks[-1]["text"]` would chain overlaps across flushes and fail this assertion.
- **Fallback path now chonkie-backed** — `_split_fixed` rewritten to call `_make_chunker(max_size).chunk(text)` end-to-end. Returns chunks with all 7 fields, honest per-chunk `char_offset = cc.start_index`, first chunk `overlap_prev_chars=0`, last chunk `overlap_next_chars=0`. Biomedical papers (no clause structure) get first-class sentence-boundary-preserving overlap (closes D-04 #3, D-05).
- **`_split_at_paragraphs` deleted entirely** — no callers remain in `core/`. Audit via `grep -n '_split_at_paragraphs' core/ tests/` before deletion confirmed the only caller was HEAD's `_split_fixed` (rewritten here). The mention in `tests/TEST_REQUIREMENTS.md` line 383 is a doc description of UT-036b's pre-chonkie rationale; the test itself is now chonkie-based and still pins D-11, so the doc is harmlessly out-of-date (candidate for a future docs cleanup pass — not in Plan 14-03's scope).
- **Final-chunk correction** — post-loop in `_merge_small_sections`: `if chunks: chunks[-1]["overlap_next_chars"] = 0`. Pins the D-10 honest-provenance invariant that the last chunk of the whole document contributes no outgoing overlap. Mid-document sub-chunks retain their chonkie-computed or `_tail_sentences`-computed outgoing size.
- **Four new unit tests landed** — UT-036 (schema + (cont.) header), UT-036b (honest char_offset across blank-paragraph gaps), UT-037 (M-1/M-2 ARTICLE-boundary raw-tail invariant), UT-038 (fallback-path overlap). Unit suite: 52 → 56 collected, 48 → 52 passing (4 skipped unchanged, conditional on RDKit/Biopython/sift-kg availability).

## Task Commits

Each task committed atomically. Commits per hash:

1. **Task 1 — Rewrite `_merge_small_sections::_flush` with chonkie + `_pending_tail`** — `2a9668e` (feat)
2. **Task 2 — Rewrite `_split_fixed` with chonkie + delete `_split_at_paragraphs`** — `31091cc` (feat)
3. **Task 3 — Add UT-036, UT-036b, UT-037, UT-038 schema + boundary tests** — `f6eb9dc` (test)

## Files Created/Modified

- `core/chunk_document.py` — +141 insertions / -42 deletions vs. pre-14-03 HEAD (commit a56e59d). Net +99 lines. File now 537 lines (was 438 post-14-02). Three functions changed:
  - `_make_chunker` docstring: updated to reflect two call sites instead of three (post-`_split_at_paragraphs` deletion).
  - `_merge_small_sections`: body fully rewritten with nonlocal `_pending_tail` cache, chonkie delegation on oversized path, and 7-key chunk dict emission on all paths. Main-loop ARTICLE detection + buffer-merge logic preserved.
  - `_split_fixed`: body fully rewritten as thin wrapper over `_make_chunker(max_size).chunk(text)` with per-chunk overlap-size derivation from consecutive chonkie offsets.
  - `_split_at_paragraphs`: deleted entirely.
- `tests/test_unit.py` — +197 lines (1096 → 1293). Four new tests appended after UT-031..UT-035 + UT-033b; no existing test modified.

## Chunk JSON Shape (hand-picked smoke sample)

```json
{
  "chunk_id": "smoke_chunk_000",
  "text": "ARTICLE I\n\nShort body. Two sentences.",
  "section_header": "",
  "char_offset": 0,
  "overlap_prev_chars": 0,
  "overlap_next_chars": 0,
  "is_overlap_region": false
}
```

(From `chunk_document("ARTICLE I\n\nShort body. Two sentences.", "smoke")[0]`. The 3-char-sub-heading "ARTICLE I" without a colon/period isn't matched by `SECTION_PATTERNS`, so this input routes through `_split_fixed` — which emits `section_header=""`. Both paths produce the same 7-key shape.)

From an oversized multi-article case (`chunk_document('ARTICLE I. DEFINITIONS\n\n' + 'Sentence content here. ' * 1500 + '\n\nARTICLE II. SCOPE\n\nShort body', 'doc1')`), the 5-chunk output:

```
chunk_id                  offset  prev    next   header
doc1_chunk_000            0       0       1426   ARTICLE I. DEFINITIONS
doc1_chunk_001            8557    1426    1426   ARTICLE I. DEFINITIONS (cont.)
doc1_chunk_002            17113   1426    1426   ARTICLE I. DEFINITIONS (cont.)
doc1_chunk_003            25669   1426    68     ARTICLE I. DEFINITIONS (cont.)
doc1_chunk_004            34526   68      0      ARTICLE II. SCOPE
```

ARTICLE I split into 4 sub-chunks with (cont.) headers on 1-3 (D-12), intra-flush overlap 1426 chars between each (chonkie-computed). ARTICLE II absorbed 68 chars of outgoing from ARTICLE I's end (`_tail_sentences` of the RAW body of sub-chunk 3). First chunk `prev=0`, last chunk `next=0`. Offsets monotonic and unique (D-11).

## Sample Contract Fixture Delta (for Plan 14-04's V2 baseline expectations)

```
$ wc -c tests/fixtures/sample_contract_text.txt
    1145 tests/fixtures/sample_contract_text.txt

HEAD (pre-14-03):     4 chunks, no overlap provenance
post-14-03 wave 3:    4 chunks, overlap provenance present
```

Chunk count, chunk IDs, section headers, and `char_offset` values are identical. Only NEW fields (`overlap_prev_chars=[0, 158, 126, 91]`, `overlap_next_chars=[158, 126, 91, 0]`, `is_overlap_region=[False]*4`) differ.

**Implication for Plan 14-04:** V2 baseline scenario runs on short contract-style fixtures should produce identical chunk-level structure — only chunk text content changes (overlap prefixes now prepend), which increases the overlap-region bytes each chunk feeds into the LLM. The V2 baseline node/edge counts should hold or INCREASE (boundary-straddling entities/relations newly recoverable); a DECREASE would signal overlap-induced noise and warrants revisiting D-04 #2 per 14-CONTEXT.md D-14.

## Pytest Output (filtered + full)

Filtered (`.venv/bin/python3 -m pytest tests/test_unit.py -m unit -v -k "ut036 or ut036b or ut037 or ut038"`):

```
tests/test_unit.py::test_ut036_chunk_json_schema PASSED                  [ 25%]
tests/test_unit.py::test_ut036b_honest_offset_across_whitespace_gaps PASSED [ 50%]
tests/test_unit.py::test_ut037_overlap_at_article_boundary PASSED        [ 75%]
tests/test_unit.py::test_ut038_overlap_at_split_fixed_fallback PASSED    [100%]

4 passed, 52 deselected in 0.10s
```

Full (`.venv/bin/python3 -m pytest tests/test_unit.py -m unit -q`):

```
.....ss.ss..............................................                 [100%]
52 passed, 4 skipped in 7.02s
```

All 10 Phase 14 unit tests pass: UT-031, UT-032, UT-033, UT-033b, UT-034, UT-035, UT-036, UT-036b, UT-037, UT-038.

## Verification Results

- `grep -q '_make_chunker(' core/chunk_document.py` → PASS (3 hits: factory def + 2 call sites)
- `grep -q '_pending_tail' core/chunk_document.py` → PASS (M-1/M-2 cache present)
- `grep -c 'overlap_prev_chars' core/chunk_document.py` → 6 (≥2; dict literals in both size paths)
- `grep -c 'overlap_next_chars' core/chunk_document.py` → 7 (≥2)
- `grep -q 'is_overlap_region' core/chunk_document.py` → PASS
- `grep -q 'is_overlap_region reserved' core/chunk_document.py` → PASS (D-10 comment present, appears 4 times — once per emission site)
- `grep -q 'chunks\[-1\]\["overlap_next_chars"\] = 0' core/chunk_document.py` → PASS (final-chunk correction)
- `! grep -q '_tail_sentences(chunks\[-1\]\["text"\])' core/chunk_document.py` → PASS (M-1 bug absent)
- `! grep -q 'def _split_at_paragraphs' core/chunk_document.py` → PASS (function fully deleted)
- `grep -A 30 'def _split_fixed' core/chunk_document.py | grep -q '_make_chunker'` → PASS
- `grep -A 30 'def _split_fixed' core/chunk_document.py | grep -q 'overlap_prev_chars'` → PASS
- `grep -q 'def test_ut036_chunk_json_schema' tests/test_unit.py` → PASS
- `grep -q 'def test_ut036b_honest_offset_across_whitespace_gaps' tests/test_unit.py` → PASS
- `grep -q 'def test_ut037_overlap_at_article_boundary' tests/test_unit.py` → PASS
- `grep -q 'def test_ut038_overlap_at_split_fixed_fallback' tests/test_unit.py` → PASS
- `grep -q 'endswith("(cont.)")' tests/test_unit.py` → PASS (UT-036 pins D-12)
- `grep -q '_tail_sentences(article_1)' tests/test_unit.py` → PASS (UT-037 pins M-1/M-2 RAW-tail comparison, not `chunks[-1]["text"]`)
- `ruff check core/chunk_document.py` → PASS (all checks passed)
- `ruff check tests/test_unit.py` → 5 pre-existing violations unchanged (logged by 14-02 in deferred-items.md); this plan's additions introduce zero new errors
- JSON round-trip: `chunks[0]` serializes + deserializes with `isinstance(rt['overlap_prev_chars'], int)` and `isinstance(rt['is_overlap_region'], bool)` → PASS
- Smoke: 2-article doc produces 2 chunks with correct boundary-zero values and `A2['overlap_prev_chars'] == len(_tail_sentences(article_1))` = 17 chars → PASS

## Decisions Made

Summarized from the frontmatter `key-decisions` block:

1. **Two-commit split for interdependent rewrites** — Task 1 left `_split_at_paragraphs` in place as dead-code-in-transition; Task 2 deleted it atomically with the `_split_fixed` rewrite. Intermediate commit passes tests; honest for `git bisect`.
2. **UT-036 test-input rewrite** — Plan's single-article input fell through to `_split_fixed` (no `(cont.)` emission possible there). Rewrote to multi-article so `_merge_small_sections::_flush`'s oversized path exercises, and D-12 invariant is pinned correctly.
3. **UT-036b semantics correction** — Plan's draft assumed `char_offset` points to the post-overlap-prefix RAW body start, but chonkie's `start_index` points to the WHOLE chunk start (overlap prefix included). Rewrote the invariant as `source[char_offset:+30] == chunk.text[:30]`. Same D-11 intent; semantically correct for chonkie.
4. **Chonkie quirk documented** — `SentenceChunker(tokenizer="character")` collapses highly-repeated identical sentences into a single chunk. Tests use varied content.
5. **Sample contract chunk count unchanged** — 4 → 4. Plan 14-04's e2e regression gate should assume structural equivalence; only overlap provenance is new.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 — Bug] UT-036b test assertion modeled wrong offset semantics**
- **Found during:** Task 3 verification run
- **Issue:** Plan's draft UT-036b assumed `char_offset` points to where the RAW body (post-overlap-prefix) starts in the source. That's not how chonkie models offsets: `cc.start_index` points to the START of the whole chunk (including the overlap region chonkie copied from before), and `cc.text[:overlap_prev_chars]` is that overlap prefix. So `source_text[char_offset : char_offset + 30] == chunk.text[:30]` is the honest invariant — chonkie's `start_index` is honest by construction.
- **Fix:** Rewrote UT-036b's assertion as `probe == expected` where `probe = chunk.text[:30]` and `expected = source_text[char_offset : char_offset + 30]`. Docstring updated to explain M-6 dissolution. Also added `section_header == ""` assertion on every chunk to prove the fallback path was exercised.
- **Files modified:** tests/test_unit.py (only UT-036b body; other tests unchanged)
- **Commit:** f6eb9dc (folded into Task 3 commit since the failing test was the initial landing attempt; correction was made before commit)

**2. [Rule 1 — Bug] UT-036 test input routed through wrong path**
- **Found during:** Task 3 verification run (before initial commit)
- **Issue:** Plan's draft used single-article `'ARTICLE I. DEFINITIONS\n\n' + 'Sentence content here. ' * 1500` as UT-036 input. `_split_at_sections` produces exactly 1 section for that input, so `chunk_document()` falls through to `_split_fixed` (fallback path) rather than `_merge_small_sections::_flush` (oversized clause-aware path). The fallback path emits `section_header=""` uniformly — so `(cont.)`-header sub-chunks never appear, and UT-036's D-12 assertion (`any(c["section_header"].endswith("(cont.)") for c in chunks[1:])`) fails.
- **Fix:** Rewrote UT-036's input as multi-article (`'ARTICLE I. DEFINITIONS\n\n' + 'Sentence content here. ' * 1500 + '\n\nARTICLE II. SCOPE\n\nShort body for article two.'`). `_split_at_sections` produces 2 sections → `_merge_small_sections` path → ARTICLE I is oversized → chonkie splits into sub-chunks with `(cont.)` headers.
- **Files modified:** tests/test_unit.py (UT-036 only)
- **Commit:** f6eb9dc

### Spec Nuances (not deviations)

**1. Plan Task 1 acceptance criterion produced a false-expectation**
- **Observed:** Plan line 392 AC: `... chunks = chunk_document(text, 'd'); assert len(chunks) >= 2; assert chunks[0]['overlap_prev_chars'] == 0; ...` with input `'ARTICLE I. FOO\n\n' + ('Sentence. ' * 2000)`. This input goes through `_split_fixed` (1 section detected) — which on Task 1's commit is HEAD behavior — so `overlap_prev_chars` key is missing.
- **Root cause:** Plan assumed Task 1's path was unconditionally exercised, but dispatch to `_split_fixed` depends on the number of sections `_split_at_sections` detects, not on the presence of `ARTICLE` headers.
- **Resolution:** Verified Task 1 correctness via a multi-article input (`text + '\n\nARTICLE II. BAR\n\n' + 'Another. ' * 100`) which DOES route through `_merge_small_sections::_flush`. All 7 keys present, offsets monotonic, cross-flush overlap non-zero. No code change needed — the behavior is correct; the plan's AC test input was mismatched to the path under test. Noting here for the planner.

**2. Plan Task 2 acceptance criterion's "no-regression on clause-aware path" check**
- **Observed:** Plan line 499 AC: `... chunk_document('ARTICLE I. FOO\n\nTwo sentences here. That is enough.', 'd'); assert len(c) == 1 and c[0]['section_header'].startswith('ARTICLE') ...`. This input produces 1 section, falls through to `_split_fixed`, which emits `section_header=""`.
- **Root cause:** Same as above — short single-article input doesn't exercise the clause-aware path.
- **Verified on HEAD:** Ran the same input on pre-14-02 HEAD: `section_header=""` there too. Pre-existing behavior; not a regression.
- **Resolution:** No code change. The AC is testing a path it doesn't actually exercise; the path IS exercised in UT-036 with multi-article input.

**3. Chonkie 1.6.2 repeated-sentence collapse**
- **Observed:** `SentenceChunker(tokenizer="character", chunk_size=10000).chunk('Sentence. ' * 5000)` returns 1 chunk instead of the expected ~5-6.
- **Root cause:** Chonkie 1.6.x appears to treat identical repeated sentences as a single semantic unit (not confirmed by reading chonkie source; inferred from behavior). Varied content (`'Sentence %d is here. ' % i`) splits as expected.
- **Resolution:** UT-036 input uses varied-enough content (`'Sentence content here. ' * 1500` = 34.5K chars of a single multi-word sentence repeated, which DOES split cleanly into 4 chunks). Documented in UT-036 inline comment.

**4. Diff-stat differed slightly from plan estimate**
- **Plan:** +80/-50 net (+30 net)
- **Actual:** +141/-42 net (+99 net)
- **Driver:** Defensive `if not sub_chunks` fall-back block in `_flush` (plan included this but estimate didn't account for the full size), 4x inline `is_overlap_region reserved` comments (D-10 documentation per emission site), and verbose `# Cross-flush overlap cache` block comment on the `_pending_tail` declaration.

## Issues Encountered

Two draft-test corrections (noted as Auto-fixed Issues above) were caught by running the new tests in-loop during Task 3 before committing. No blockers. No architectural deviations. No auth gates.

## Authentication Gates

None. Pure code path — no external service access.

## Known Stubs

None — every chunk dict emitted by `chunk_document()` carries all 7 fields with honest values on both paths. Plan 14-04's FT-011 (synthetic boundary-straddle fixture) and FT-012 (V2 baseline regression) can now rely on the schema contract unconditionally.

## Line-Number Anchors (for Plan 14-04)

| File | Lines (post-14-03) | Content |
|------|---------------------|---------|
| `core/chunk_document.py` | 46-54 | `MAX_CHUNK_SIZE=10000`, `MIN_CHUNK_SIZE=500`, `OVERLAP_SENTENCES=3`, `OVERLAP_MAX_CHARS=1500` |
| `core/chunk_document.py` | 74-95 | `_make_chunker(max_size)` factory (unchanged from 14-02) |
| `core/chunk_document.py` | 97-181 | `_tail_sentences(text, n, max_chars)` helper (unchanged from 14-02) |
| `core/chunk_document.py` | 228-393 | `_merge_small_sections` (rewritten by Plan 14-03 Task 1) |
| `core/chunk_document.py` | 396-445 | `_split_fixed` (rewritten by Plan 14-03 Task 2) |
| `core/chunk_document.py` | 453-475 | `chunk_document` public API (untouched — two-branch dispatch is preserved) |
| `core/chunk_document.py` | 479-510 | `chunk_document_to_files` public API (untouched) |
| `tests/test_unit.py` | 1100-1294 | UT-036, UT-036b, UT-037, UT-038 (added by this plan) |
| `tests/test_unit.py` | 970-1096 | UT-031..UT-035 + UT-033b (from Plan 14-02) |

## Self-Check: PASSED

Artifact existence (each tested via Read/Grep):

- `core/chunk_document.py` — FOUND (537 lines)
- `tests/test_unit.py` — FOUND (1293 lines)
- `.planning/phases/14-chunk-overlap/14-03-SUMMARY.md` — FOUND (this file)
- `.planning/phases/14-chunk-overlap/14-01-SUMMARY.md` — FOUND (from Plan 14-01)
- `.planning/phases/14-chunk-overlap/14-02-SUMMARY.md` — FOUND (from Plan 14-02)
- `.planning/phases/14-chunk-overlap/deferred-items.md` — FOUND (unchanged — pre-existing ruff issues from 14-02 still apply)

Commit existence (each tested via `git log --oneline | grep $hash`):

- `2a9668e` (Task 1 — feat) — FOUND
- `31091cc` (Task 2 — feat) — FOUND
- `f6eb9dc` (Task 3 — test) — FOUND

Pytest: `52 passed, 4 skipped` (full unit suite) — 4 new tests contributing; zero regressions. 56 tests collected total (46 baseline + 6 from 14-02 + 4 from this plan).

---

*Phase: 14-chunk-overlap*
*Plan: 03*
*Completed: 2026-04-18*
