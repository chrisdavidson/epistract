# Phase 999.4 — Evaluate opendataloader-pdf vs Kreuzberg [P3 BACKLOG]

**Goal:** Decide whether `opendataloader-pdf` (https://github.com/opendataloader-project/opendataloader-pdf) should replace or supplement Kreuzberg as Epistract's PDF reader. Output a go/no-go decision backed by a side-by-side bakeoff on a representative mixed corpus.

**Source:** Discussion during Phase 14 (Chunk Overlap) context gathering on 2026-04-18. User raised the question while evaluating chunking strategy; deferred from Phase 14 because chunking operates on already-extracted text and can't fix upstream parser quality issues.

## Scope

### Track A — Bakeoff corpus assembly

Assemble a fixed evaluation corpus covering the two production domains plus pathological edge cases:

1. **Contract samples (3-5 docs)** — multi-column layouts, tables of fees, stamped signatures, scanned addenda. Draw from the STA infrastructure corpus.
2. **Biomedical samples (3-5 docs)** — PubMed papers with inline citations, multi-column layouts, figures with captions, supplementary tables. Reuse Scenario 1-6 inputs.
3. **Edge cases (2-3 docs)** — scanned-only PDFs (OCR required), rotated pages, password-protected-then-unlocked, heavy-figure documents where reading order is ambiguous.

### Track B — Side-by-side extraction

Run both parsers on every corpus document; record for each:

- Extracted character count and approximate reading-order fidelity
- Table detection and serialization quality (rows/cells preserved?)
- OCR fallback behavior on scanned pages
- Time-to-extract per document
- Failure modes (crashes, empty output, partial output)

### Track C — Downstream impact

Feed both extraction results through the full Epistract pipeline (`/epistract:ingest` → extract → build graph) on the same corpus and compare:

- Entity counts and types
- Relation counts and types
- Cross-reference / epistemic findings
- Wall-clock pipeline time

## Success criteria sketch

1. A markdown report documents the bakeoff results with side-by-side numbers per document.
2. A recommendation: adopt `opendataloader-pdf` outright, adopt it as a selectable `--reader` option, supplement Kreuzberg for specific formats (e.g., tables), or reject (stay on Kreuzberg).
3. If adopted: migration plan for `core/ingest_documents.py:21` and `core/domain_wizard.py:35` call sites; risk assessment for backward compatibility with existing V2 baselines.
4. If rejected or supplemented: documented rationale captured in `docs/adrs/` or equivalent so the decision doesn't get re-litigated.

## Out of scope

- Changing anything about the chunker (Phase 14 owns that)
- Wholesale parser replacement without the bakeoff data
- Non-PDF formats — DOCX/HTML/EPUB etc. stay on Kreuzberg regardless

## Depends on

- Phase 14 complete (chunk overlap shipped so parser-quality comparison isn't confounded by chunking recall gaps)
- Phase 15 complete (format discovery parity shipped so format support isn't a confound)

## References

- `core/ingest_documents.py:21` — current Kreuzberg integration point via `sift_kg.ingest.reader.read_document`
- `core/domain_wizard.py:35` — wizard integration point (fixed in Phase 12)
- CLAUDE.md §Key Dependencies — current stack (Kreuzberg ≥4.0, pdfplumber ≥0.10 legacy)
- `.planning/phases/14-chunk-overlap/14-CONTEXT.md` §Deferred — original capture

## Priority

**P3 BACKLOG** — parser quality is a real concern but Kreuzberg works today for both production domains. No user-facing bug, no correctness gap. Revisit after v3.0 ships when we have breathing room to evaluate alternatives without blocking milestone work.
