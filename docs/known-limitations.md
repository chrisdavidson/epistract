# Known Limitations

This document records behavioral limits of the epistract pipeline that are deliberate design choices or deferred improvements. It is cited by the Phase 20 README "Pipeline Capacity & Limits" section — update here first, then let Phase 20 quote values from this file rather than re-deriving them.

Each section is scoped to a subsystem. Add new sections as limitations are surfaced or deferred.

---

## Domain Wizard sample window (FIDL-05)

**Scope:** `core/domain_wizard.build_schema_discovery_prompt` — the Pass-1 prompt sent to the LLM once per sample document during `/epistract:domain` schema discovery.

**Source:** `.planning/phases/16-wizard-sample-window-beyond-8kb/16-CONTEXT.md` (D-01..D-09). Implemented in Phase 16 Plan 16-01.

### What the wizard sees

For each sample document, the wizard builds Pass-1 prompts using a length-conditional strategy:

- **Documents ≤ 12,000 characters** (`MULTI_EXCERPT_THRESHOLD`) — pass through as full text under the `**Document text:**` header. No truncation, no excerpt markers. This matches the pre-Phase-16 prompt shape for short samples.
- **Documents > 12,000 characters** — three excerpts totalling 12,000 characters:
  - **Head** — first 4,000 characters (`EXCERPT_CHARS`), annotated `[EXCERPT 1/3 — chars 0 to 4000 (head)]`.
  - **Middle** — 4,000-character slice centered on `len(doc) // 2`, annotated `[EXCERPT 2/3 — chars <m0> to <m1> (middle)]`. Explicit midpoint centering (not "second third") so the mid-body anchor lands correctly regardless of head-heavy intros or tail-heavy conclusions.
  - **Tail** — last 4,000 characters, annotated `[EXCERPT 3/3 — chars <t0> to <end> (tail)]`.

  The excerpts are introduced with the preface: "The following are three excerpts from a larger document. Treat them as non-contiguous samples of the same document, not as a single continuous passage." The markers and preface together prevent the LLM from confabulating structural continuity between disjoint slices.

### What the wizard does NOT see

- **Shoulder regions** — for very long documents, the chars between ~4,000 and the start of the middle slice (e.g., chars 4000..len//2-2000), and between the end of the middle slice and the start of the tail (e.g., chars len//2+2000..len-4000), are NEVER sent in a Pass-1 call. An entity type that appears only in a "shoulder region" of a single document will not be proposed from that document. Mitigation: Pass-2 consolidation across multiple documents often surfaces shoulder-region vocabulary from at least one other sample with overlapping coverage.
- **Very long tails beyond 4KB** — the last 4,000 characters are the full tail budget. A 200KB patent's claims section at chars 190,000..200,000 is captured; a 600KB legal compendium's chars 500,000..596,000 region is not.
- **Summarization** — no summarizer pass; excerpts are raw character slices. Deferred — see `16-CONTEXT.md` §deferred item 1.

### Why no sliding-window or summarize-then-analyze

- **Sliding-window (N calls/doc)** — rejected for Phase 16. N× the token cost for a marginal per-doc coverage gain that Pass-2 cross-document dedupe already supplies. See `16-CONTEXT.md` §specifics "Multi-excerpt over sliding-window…".
- **Summarize-then-analyze** — deferred. Adds a summarizer pass and opens the "what is a good summary for schema discovery" question; revisit in v3.x if multi-excerpt proves insufficient for specific corpora.

### Token cost (measured 2026-04-21)

- **Input tokens per Pass-1 call (measured on the `long_contract.txt` fixture, 60,200 chars, 2026-04-21):** 2631 input tokens. Method: tiktoken cl100k_base. Soft budget 24,000 tokens → headroom ≈ 9× the measured cost.
- **Soft budget:** ~24,000 input tokens per call. Headroom: ~9× the measured value (2631 tokens measured 2026-04-21). No runtime enforcement — the wizard is user-invoked and cost escalations are user-visible.
- **Rationale for no enforcement:** `16-CONTEXT.md` §deferred item 3 (runtime budget would require injecting tiktoken into the critical path; out of scope for v3.0).

### Pass-2 / Pass-3 impact

None. Pass-2 (consolidation, `build_consolidation_prompt`) and Pass-3 (final schema, `build_final_schema_prompt`) are byte-identical to the pre-Phase-16 implementation. They consume the richer Pass-1 candidate lists without format changes. See `16-CONTEXT.md` D-07.

### Acceptance gate

Phase 16's acceptance is prompt-level, not LLM-level: for the synthetic fixture `tests/fixtures/wizard_sample_window/long_contract.txt` (~60,000 chars with three sentinel phrases placed in head / middle / tail), the prompt built by `build_schema_discovery_prompt` contains all three sentinels verbatim (`PARTY_SENTINEL_HEAD`, `OBLIGATION_SENTINEL_MIDDLE`, `TERMINATION_SENTINEL_TAIL`) plus all three `[EXCERPT N/3 — ...]` markers. See `tests/TEST_REQUIREMENTS.md` UT-043 and FT-016.

### Related

- `core/domain_wizard.EXCERPT_CHARS` — 4,000.
- `core/domain_wizard.MULTI_EXCERPT_THRESHOLD` — 12,000.
- `core/domain_wizard._build_excerpts` — pure slice helper.
- Phase 20 README "Pipeline Capacity & Limits" section consumes the values in this section.

---

*Last updated: 2026-04-21 — Phase 16 FIDL-05 (Wizard Sample Window) initial entry; token cost measured.*
