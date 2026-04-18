# Phase 14: Chunk Overlap - Context

**Gathered:** 2026-04-18
**Status:** Ready for planning

<domain>
## Phase Boundary

Implement sliding-window overlap in `core/chunk_document.py` so entities and relations whose mentions straddle a chunk boundary are extracted. `commands/ingest.md:34` has promised "chunks with overlap" since v1; the implementation has never honored it. After this phase, every graph built by `/epistract:ingest` recovers the cross-boundary recall that has been silently lost to date, on every corpus, without regressing V2 baselines.

**In scope (FIDL-03 umbrella, Phase 14 slice):**
- Sentence-aware overlap between adjacent chunks in both clause-aware and fallback paths
- New runtime dependency: `blingfire` sentence tokenizer (bundled models, no runtime download)
- Chunk JSON schema extension: `overlap_prev_chars`, `overlap_next_chars`, `is_overlap_region`, honest per-sub-chunk `char_offset`
- Auto-install of `blingfire` via `/epistract:setup`
- Fail-loud import guard when `blingfire` is missing (matches Phase 12 posture)
- Doc alignment: `commands/ingest.md:34` promise now matches behavior

**Out of scope (other phases):**
- Format discovery parity (PPTX/EPUB/MD/RTF/ODT/CSV discovery) — Phase 15
- Wizard sample-window beyond 8KB — Phase 16
- Domain awareness in consumers — Phase 17
- Per-domain epistemic/validator extensibility — Phase 18
- PDF parser quality (e.g., opendataloader-pdf as Kreuzberg alternative) — deferred, see `<deferred>` below
- Token-level or pricing-based cost accounting — deferred beyond v3.0 (inherited from Phase 13)

**Acceptance target:** A relation straddling the 10,000-char boundary in a synthetic fixture is present in the built graph; and the 6 drug-discovery V2 baseline scenarios produce **≥ V2 edge counts** (overlap should increase recall, not regress it).

</domain>

<decisions>
## Implementation Decisions

### Overlap strategy

- **D-01:** Overlap is **sentence-aware** via `blingfire` (Microsoft). Models ship bundled in the wheel — no runtime download, no `nltk.download` friction. Chosen over character-tail (clips mid-sentence), `pysbd` (slower), and `nltk+punkt` (hostile fresh-install UX).
- **D-02:** Overlap window is the **last 3 sentences** of the previous chunk, prepended to the next chunk's text. Three is the SCOPE.md starting point: enough for pronoun resolution and multi-sentence antecedents without doubling LLM token cost.
- **D-03:** Character-budget cap of **1500 chars** on the overlap window. If the last 3 sentences exceed 1500 chars (pathological "whereas…" blocks in contracts), truncate to the most-recent sentences that fit under 1500. Prevents a single long sentence from dominating the chunk.
- **D-04:** Overlap applies at **every split point** where `chunk_document` currently emits a boundary:
  1. Between sub-chunks inside `_split_at_paragraphs` (when one merged section exceeds `MAX_CHUNK_SIZE = 10000`) — this is where most silent drop happens today.
  2. Between top-level ARTICLE-level sections in `_merge_small_sections` (even across the `is_major` hard-flush).
  3. Between paragraph-bucket chunks in `_split_fixed` (no-section-structure fallback).
- **D-05:** The fallback `_split_fixed` path uses the **same sentence-based overlap primitive** (not a separate character-tail implementation). One primitive, reused — simpler maintenance. Biomedical papers (which usually fall through to this path) get first-class overlap.

### Configurability

- **D-06:** **No CLI flag.** Overlap parameters (3 sentences, 1500-char cap) are hardcoded constants in `core/chunk_document.py`. Pit-of-success precedent from Phase 12/13: users never think about overlap. A flag can be added later if operator demand appears.
- **D-07:** **No env var.** Symmetric with D-06 — no hidden operator knob.

### Missing-dependency behavior

- **D-08:** If `import blingfire` fails at module load, **raise loud** with a clear install hint (`uv pip install blingfire`). No silent fallback to character-tail — running without overlap silently IS the bug Phase 14 fixes. Mirrors Phase 12's "prefer loud failure over silent garbage."
- **D-09:** `/epistract:setup` gains `blingfire` as a required install step (not optional). Fresh-install users never hit the fail-loud branch. Optional validator deps (RDKit, Biopython) stay optional; `blingfire` is promoted to required because the core chunker depends on it.

### Chunk JSON schema (provenance)

- **D-10:** Each chunk dict gains three new keys:
  - `overlap_prev_chars` (int) — character count of sentences bled in from the previous chunk, 0 for the first chunk of a document.
  - `overlap_next_chars` (int) — character count contributed to the next chunk's overlap region, 0 for the last chunk.
  - `is_overlap_region` (bool) — always `false` at the chunk level; reserved for future sub-region annotation if/when we emit overlap as a separate JSON region rather than inline prefix.
- **D-11:** `char_offset` is **recomputed honestly per sub-chunk**. Today (line 113–118) sub-chunks within an oversized merged section all share the section's offset; after this phase, each sub-chunk records its true starting char offset in the original document text. Needed for overlap auditing and downstream provenance.
- **D-12:** `section_header` propagation unchanged — overlap does not affect header labelling. Sub-chunks after the first still get `{header} (cont.)` (existing behavior at line 116).

### Acceptance & regression

- **D-13:** Two-anchor acceptance (mirrors Phase 13 belt-and-suspenders):
  1. **Synthetic fixture** — a text document where a known relation (e.g., `INHIBITS(sotorasib, KRAS G12C)` with `sotorasib` ending at char ~9999 and `KRAS G12C` starting at char ~10001) straddles the 10,000-char boundary. Test asserts the relation is **absent** on HEAD (RED) and **present** after the fix (GREEN).
  2. **V2 baseline diff** — all 6 drug-discovery scenarios plus the contract scenario must produce **edge counts ≥ V2 baseline**. Overlap is supposed to *increase* recall; a regression means the implementation is wrong.
- **D-14:** The contract scenario (341 nodes, 663 edges baseline) is the noisiest case because of ARTICLE-boundary overlap (D-04 #2). Acceptance is `≥ 663 edges` — if overlap across ARTICLE boundaries introduces cross-contamination that reduces edges, revisit D-04 #2 before shipping.

### Claude's Discretion

- Exact internal decomposition of the overlap primitive (helper function name, signature, where it lives in `core/chunk_document.py`)
- Whether `blingfire` is imported at module top with a `HAS_BLINGFIRE` flag (pattern from `validate_molecules.py`) or inside a dedicated helper — D-08 mandates loud failure either way
- Precise wording of the ImportError message and the pointer to `/epistract:setup`
- The test fixture's surface form (which relation, which domain) — as long as it straddles the 10K boundary and round-trips through the real extractor path
- Whether the V2 baseline comparison reuses `tests/test_e2e.py` scaffolding or adds a Phase-14-specific test — goal-backward design matches Phase 13 precedent
- Whether overlap logic lives in one helper or is inlined per call-site — as long as D-05 (one primitive) holds
- Exact sentence-count boundary behavior when a chunk has fewer than 3 total sentences (fall back to "all sentences" is the sensible default; planner to confirm)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase scope & triage
- `.planning/ROADMAP.md` §Phase 14 — phase goal, scope (Part 1 Item 1), dependencies
- `.planning/phases/14-chunk-overlap/SCOPE.md` — touch points, open design questions, success criteria sketch
- `.planning/phases/12-extend-epistemic-classifier-with-structural-biology-document-signature/SCOPE-ADDITIONS.md` §Item 1 — problem statement, impact analysis, candidate fixes, acceptance sketch
- `.planning/phases/12-extend-epistemic-classifier-with-structural-biology-document-signature/axmp-compliance-bug-report-2026-04-16.md` — source bug report that surfaced chunk-overlap recall loss

### Project-level requirements
- `.planning/REQUIREMENTS.md` §v3 — add a new FIDL-03 requirement line for chunk overlap (Phase 14) during plan kickoff
- `.planning/PROJECT.md` §Future (V3) — v3.0 "Graph Fidelity & Honest Limits" milestone framing

### Prior phase context (decisions to respect)
- `.planning/phases/11-end-to-end-scenario-validation/11-CONTEXT.md` §D-03 — threshold-based regression comparison pattern (≥V2 baseline); informs D-13 / D-14
- `.planning/phases/12-.../12-01-PLAN.md` — "prefer loud failure over silent garbage" precedent; informs D-08 / D-09
- `.planning/phases/13-extraction-pipeline-reliability/13-CONTEXT.md` §D-01, D-06 — pit-of-success (no opt-out flags) + two-layer defense (enforcement at write time); informs D-06 / D-13

### Code to modify
- `core/chunk_document.py:25` — `MAX_CHUNK_SIZE = 10000` constant stays; add overlap constants (`OVERLAP_SENTENCES = 3`, `OVERLAP_MAX_CHARS = 1500`)
- `core/chunk_document.py:85-156` — `_merge_small_sections` gains overlap emit at every flush (D-04 #1, #2); `char_offset` recomputed per sub-chunk (D-11)
- `core/chunk_document.py:159-175` — `_split_at_paragraphs` returns sub-chunks with overlap prefix
- `core/chunk_document.py:178-204` — `_split_fixed` uses the same overlap primitive (D-05)
- `core/chunk_document.py` — new helper (name TBD by planner) that returns the last-N-sentence tail, capped at 1500 chars, using `blingfire.text_to_sentences_and_offsets`
- `commands/ingest.md:34` — prose already says "chunks with overlap"; no change needed, but verify it still describes actual behavior
- `scripts/setup.sh` — add `blingfire` to the required-install list (D-09)
- `pyproject.toml` — declare `blingfire` as a core runtime dep (not optional extra)
- `CLAUDE.md` §Key Dependencies — add `blingfire` with purpose note

### Test touch points
- `tests/test_unit.py` — unit tests for the overlap primitive (boundary cases: fewer-than-N sentences, sentence longer than cap, empty text)
- `tests/test_unit.py` — `chunk_document` emits correct `overlap_prev_chars`/`overlap_next_chars`/`is_overlap_region`/`char_offset` values
- New or existing `tests/test_e2e.py` — synthetic boundary-straddle fixture (D-13 #1): RED before implementation, GREEN after
- `tests/test_e2e.py` — V2 baseline diff acceptance (D-13 #2 / D-14): reuse Phase 11 regression scaffolding
- `tests/TEST_REQUIREMENTS.md` — register FIDL-03 traceability rows

### External references
- `blingfire` — https://github.com/microsoft/BlingFire — sentence tokenizer (`text_to_sentences_and_offsets` is the target API)
- Kreuzberg / sift-kg `read_document` — upstream of this phase; unchanged

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `core/chunk_document.py::_split_at_paragraphs` — paragraph splitter; overlap primitive plugs in on top, doesn't replace
- `core/chunk_document.py::_merge_small_sections` — already knows how to flush, just doesn't emit tail context; extend the flush path
- Phase 12 `HAS_SIFT_READER` guard pattern (mirrored in `core/ingest_documents.py:20-25`) — reuse for `HAS_BLINGFIRE` guard, though D-08 says raise rather than gracefully skip
- Phase 11 regression scaffolding in `tests/test_e2e.py` — baseline-diff machinery is reusable for D-13 #2

### Established Patterns
- Optional-dependency imports guarded at module level with `HAS_*` flags (`validate_molecules.py` pattern) — Phase 14 inverts the decision (required, not optional), but the guard pattern itself applies to the ImportError surface
- JSON outputs written with `indent=2` — new `overlap_*` fields follow this convention automatically
- Constants at module top in `SCREAMING_SNAKE_CASE` — `OVERLAP_SENTENCES`, `OVERLAP_MAX_CHARS` follow `MAX_CHUNK_SIZE` / `MIN_CHUNK_SIZE` precedent
- `pathlib.Path` everywhere; `from __future__ import annotations`; `str | None` unions — all apply
- Pytest with markers (`@pytest.mark.unit`, `@pytest.mark.e2e`) — Phase 7 infrastructure, reuse

### Integration Points
- `chunk_document_to_files(doc_id, output_dir, max_size)` is the public entrypoint called by `/epistract:ingest` Step 2 — no signature change needed (overlap is internal behavior)
- Downstream consumers of chunk JSON (`core/build_extraction.py`, extractor agent) don't need to know about `overlap_*` fields — they read `text` and pass it to the LLM. The new fields are pure provenance for auditing
- Entity resolution (sift-kg, configured by domain) already dedupes same-entity mentions across chunks — overlap-induced duplicates will be resolved, not double-counted in the final graph
- `/epistract:setup` script installs core deps; D-09 adds `blingfire` to the required-install block alongside `sift-kg`

### Constraints the code enforces today
- `MAX_CHUNK_SIZE = 10000` is hard-coded; overlap must not push chunks past this by much (overlap prefix + original body could exceed 10K if overlap is 1500 chars — planner should decide whether overlap counts toward the 10K budget or is emitted on top of it). Recommendation for planner: overlap is ON TOP of `max_size`, so effective max chunk ~ 11.5K chars, which stays well under 10-20K token LLM context windows
- `_merge_small_sections` hard-flushes at ARTICLE boundaries; D-04 requires overlap to apply here too, which is a behavioral change — contract-specific regression (V2 baseline: 341 nodes / 663 edges) gates this

</code_context>

<specifics>
## Specific Ideas

- **Pit-of-success reinforced:** No `--overlap-sentences` flag, no env var. Phase 13 added `--fail-threshold` because operators might genuinely tune that gate. Overlap isn't that kind of knob — 3 sentences is the right default and there's no production reason to override it. Adding a flag dilutes "ingest just works."
- **blingfire chosen over nltk:** The `nltk.download('punkt_tab')` first-run failure pattern is exactly the UX the rest of the framework is trying to eliminate (cf. Phase 12's `HAS_SIFT_READER` guard, Phase 13's write-time Pydantic validation). A bundled-model tokenizer belongs on the critical path.
- **Honest `char_offset` is not optional:** Today's sub-chunks share a single section-level offset, which makes overlap regions untraceable in provenance. With overlap emitting actual text bleed, operators auditing "did this entity come from the source doc or from the overlap prefix?" need per-sub-chunk offsets. Matches Phase 13's "metadata must tell the truth" decision (D-07/D-08 for `model_used`/`cost_usd`).
- **ARTICLE-boundary overlap is the acceptance-risk decision:** Overlap across a hard ARTICLE flush (D-04 #2) is the most contested choice. The contract V2 baseline (663 edges) is the guardrail — if overlap contaminates neighboring-ARTICLE extraction and edges drop, revisit before shipping. Biomedical scenarios don't have this risk because they have no ARTICLEs.
- **Two-layer defense parallel:** Phase 13 used prompt-enforcement + Pydantic-validation. Phase 14 parallels this: overlap at chunking (prevents loss) + entity resolution at graph-build (handles duplicates). Both layers required; either alone is insufficient.
- **`blingfire` promoted to required core dep:** RDKit and Biopython stay optional because they serve only the drug-discovery domain. `blingfire` is a domain-agnostic chunker dep — every domain uses the chunker. That's the criterion for the required/optional split.

</specifics>

<deferred>
## Deferred Ideas

- **`opendataloader-pdf` evaluation as Kreuzberg alternative/supplement** — raised during discussion. Not in Phase 14 scope (Phase 14 operates on already-extracted text). Likely a V3.x or post-v3 phase: side-by-side bakeoff on a mixed corpus (contracts with complex layouts + biomedical papers with inline citations), scored on reading-order fidelity, table extraction, and OCR-fallback quality. File an entry in the roadmap once v3.0 ships.
- **Per-domain overlap tuning** — e.g., contract domain uses 5-sentence overlap, biomedical uses 3. Deferred until we have evidence that one default doesn't fit both. D-02 / D-03 can be lifted into `domain.yaml` if domain-specific overlap becomes necessary.
- **Token-based overlap instead of character/sentence** — would require threading the target model's tokenizer into the chunker. Overkill for v3.0; revisit if chunk-size drift across LLM versions becomes an operational issue.
- **`--overlap-sentences` CLI flag** — explicitly rejected in D-06 for v3.0. Reserve for a future phase if operator demand appears.
- **Sub-region overlap annotation** — emit the overlap prefix as a separate JSON region with its own `is_overlap_region=true` marker, rather than as an inline prefix on the chunk text. D-10 reserves the `is_overlap_region` field for this but leaves the inline prefix as the v3.0 implementation. Upgrade path if downstream consumers need to distinguish overlap text from original text.
- **Evaluating overlap against extract-time token cost** — overlap costs tokens (each overlap region is extracted twice). Measuring the cost / recall-gain ratio empirically is post-ship work.

</deferred>

---

*Phase: 14-chunk-overlap*
*Context gathered: 2026-04-18*
