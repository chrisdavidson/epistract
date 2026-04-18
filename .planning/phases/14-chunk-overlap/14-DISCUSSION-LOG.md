# Phase 14: Chunk Overlap - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-18
**Phase:** 14-chunk-overlap
**Areas discussed:** Overlap strategy, Overlap size & configurability, Boundary respect, Provenance + regression test

---

## Area selection

Gray areas presented (multi-select, all chosen):

| Area | Description | Selected |
|------|-------------|----------|
| Overlap strategy | Character vs sentence vs hybrid; tokenizer dep trade-offs | ✓ |
| Overlap size & configurability | Default size, CLI flag exposure | ✓ |
| Boundary respect | Which split points emit overlap, ARTICLE-boundary behavior | ✓ |
| Provenance + regression test | Chunk metadata fields, char_offset honesty, acceptance anchors | ✓ |

**User's choice:** All 4 areas.

---

## Area 1: Overlap strategy

### Q1: How should overlap be constructed between adjacent chunks?

| Option | Description | Selected |
|--------|-------------|----------|
| Character tail (500-1000) | Simplest; zero new deps; may clip mid-sentence | |
| Sentence-aware (regex) | Stdlib regex splitter; zero new deps; some false splits on abbreviations | |
| Hybrid: char window, snap to sentence | Predictable size + semantic boundary | |
| Sentence-aware (nltk/blingfire) | Proper tokenizer; adds install weight | ✓ |

**User's choice:** Sentence-aware (nltk/blingfire).

### Q2: Which sentence-tokenizer dependency?

| Option | Description | Selected |
|--------|-------------|----------|
| blingfire | Microsoft; models bundled in wheel; ~2MB; fast; no runtime download | ✓ |
| pysbd | Pure-Python; zero-friction; slower | |
| nltk + punkt | Common in NLP; requires `nltk.download('punkt_tab')` first-run | |
| You decide | Claude picks | |

**User's choice:** blingfire.

**Notes:** blingfire wins on fresh-install UX — matches the framework's pit-of-success posture.

### Q3: How many sentences per overlap window?

| Option | Description | Selected |
|--------|-------------|----------|
| 3 sentences (recommended) | Enough context for pronouns/antecedents without doubling chunk count | ✓ |
| 2 sentences | Minimal overlap | |
| 5 sentences | Generous overlap; inflates token cost | |
| Configurable, 3 default | Expose --overlap-sentences, default 3 | |

**User's choice:** 3 sentences.

### Q4: Character-budget cap on the overlap window?

| Option | Description | Selected |
|--------|-------------|----------|
| Cap at 1500 chars (recommended) | Truncate to most-recent sentences under 1500 chars | ✓ |
| No cap | Trust tokenizer + N | |
| Cap at 1000 chars | Tighter ceiling | |

**User's choice:** Cap at 1500 chars.

---

## Area 2: Overlap size & configurability

### Q1: CLI flag on /epistract:ingest or internal-only?

| Option | Description | Selected |
|--------|-------------|----------|
| Internal, no flag (recommended) | Hardcoded in core/chunk_document.py; pit-of-success | ✓ |
| --overlap-sentences flag | Expose N with default 3; Phase 13 precedent | |
| Env var only (EPISTRACT_OVERLAP_SENTENCES) | Hidden operator knob | |
| You decide | | |

**User's choice:** Internal, no flag.

### Q2: Auto-disable overlap on missing blingfire, or fail loudly?

| Option | Description | Selected |
|--------|-------------|----------|
| Fail loudly (recommended) | Raise with install hint; Phase 12 "loud over silent" precedent | ✓ |
| Fall back to character tail | Log warning, use 500-char tail | |
| Add to /epistract:setup auto-install | Bundle install, fail-loud as safety net | |

**User's choice:** Fail loudly. (Implicitly accepting that `/epistract:setup` will install blingfire — captured as D-09.)

---

## Area 3: Boundary respect

### Q1: Which split points should emit overlap?

| Option | Description | Selected |
|--------|-------------|----------|
| Everywhere chunks split (recommended) | All 3 split points emit overlap; dedupe handles noise | ✓ |
| Paragraph/sub-chunk only, skip ARTICLE | Hard-flush stays hard at ARTICLE boundaries | |
| Paragraph-fallback only | Narrowest fix; leaves merged-section oversized splits broken | |

**User's choice:** Everywhere chunks split.

**Notes:** ARTICLE-boundary overlap is the acceptance-risk decision (see D-14 in CONTEXT.md). Contract V2 baseline (663 edges) is the guardrail.

### Q2: Fallback path (_split_fixed) — sentence-based or character tail?

| Option | Description | Selected |
|--------|-------------|----------|
| Yes, same sentence-based overlap (recommended) | One overlap primitive, reused | ✓ |
| Fallback uses character tail | Two overlap implementations to maintain | |

**User's choice:** Same sentence-based overlap.

---

## Area 4: Provenance + regression test

### Q1: Chunk JSON metadata?

| Option | Description | Selected |
|--------|-------------|----------|
| Add overlap fields (recommended) | overlap_prev_chars, overlap_next_chars, is_overlap_region | |
| Only fix char_offset honestly | Update to true per-sub-chunk offset; no new fields | |
| Both: overlap fields AND honest char_offset | Full provenance | ✓ |
| No metadata changes | Overlap silently in text field | |

**User's choice:** Both: overlap fields AND honest char_offset.

### Q2: Acceptance anchor?

| Option | Description | Selected |
|--------|-------------|----------|
| Both: fixture + baseline (recommended) | Synthetic boundary-straddle fixture + V2 edge-count non-regression | ✓ |
| Synthetic fixture only | Fast, reproducible; doesn't catch real-world recall gains/losses | |
| V2 baseline diff only | Slow, noisy; LLM variance can mask regressions | |

**User's choice:** Both: fixture + baseline.

---

## Scope-creep redirect

**PDF parsing (opendataloader-pdf vs Kreuzberg):** User asked mid-discussion whether Epistract has internal PDF parsing or should evaluate `opendataloader-pdf`. Redirected — parser quality is upstream of chunking and can't be fixed by Phase 14. Captured as Phase 999.4 backlog entry with bakeoff scope and dependencies on Phases 14 + 15. Also retained in CONTEXT.md `<deferred>` section.

---

## Claude's Discretion

Items where the user delegated to Claude:

- Internal decomposition of the overlap primitive (helper function name, signature, module placement)
- Whether to use a `HAS_BLINGFIRE` flag pattern vs. direct-import-and-raise
- Exact ImportError message wording
- Test fixture's surface form (which relation, which domain) — as long as it straddles 10K boundary and round-trips through the real extractor
- Whether V2 baseline comparison reuses `tests/test_e2e.py` scaffolding or adds a phase-specific test
- Sentence-count boundary behavior when a chunk has < 3 total sentences (sensible default: emit all sentences)

## Deferred Ideas

Captured in CONTEXT.md `<deferred>` and where applicable elevated to roadmap backlog:

- **opendataloader-pdf evaluation** — elevated to Phase 999.4 (new backlog entry)
- Per-domain overlap tuning (kept in CONTEXT.md only)
- Token-based overlap (kept in CONTEXT.md only)
- `--overlap-sentences` CLI flag (kept in CONTEXT.md only)
- Sub-region overlap annotation (kept in CONTEXT.md only)
- Cost / recall-gain empirical measurement (kept in CONTEXT.md only)
