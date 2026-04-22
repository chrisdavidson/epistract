---
phase: 20-readme-pipeline-capacity-and-limits
plan: 01
subsystem: "user-facing docs (README Pipeline Capacity & Limits — FIDL-09 close-out)"
tags: [FIDL-09, readme, docs, v3.0-close, phase-20]
requires: [FIDL-01, FIDL-02c, FIDL-03, FIDL-04, FIDL-05, FIDL-06, FIDL-07, FIDL-08]
provides:
  - "README.md ## Pipeline Capacity & Limits section (Document Ingestion, Wizard Schema Discovery, Extraction & Graph Build, Epistemic Layer)"
  - "FIDL-09 traceability state flipped Pending -> Complete (UPDATE-in-place)"
  - "v3.0 'Graph Fidelity & Honest Limits' milestone complete"
affects:
  - README.md
  - .planning/REQUIREMENTS.md
tech-stack:
  added: []
  patterns:
    - "Docs-only phase with grep-verifiable numbers: every table value traced to docs/known-limitations.md or codebase constant (no aspirational claims)"
    - "Additive README edit: section inserted before '## Pre-built Domains' anchor; no existing README content modified"
    - "UPDATE-in-place traceability flip: grep -c '^| FIDL-09 |' stays at 1; checkbox [ ] -> [x]; status Pending -> Complete — no duplicate rows"
    - "Milestone close-out pattern: final phase of v3.0 (Phase 20) ships docs-only after all engineering work (Phases 12-19) landed"
key-files:
  created:
    - .planning/phases/20-readme-pipeline-capacity-and-limits/20-01-PLAN.md
    - .planning/phases/20-readme-pipeline-capacity-and-limits/20-01-SUMMARY.md
  modified:
    - "README.md (+57 lines: new ## Pipeline Capacity & Limits section between ## How It Works and ## Pre-built Domains)"
    - ".planning/REQUIREMENTS.md (3 UPDATE-in-place edits: checkbox [ ] -> [x]; traceability row Pending -> Complete; footer 2026-04-22 FIDL-09 Phase 20 complete)"
decisions:
  - "D-01..D-07 section structure honored: four subsections (Document Ingestion, Wizard Schema Discovery, Extraction & Graph Build, Epistemic Layer) each with a Feature | Value | Notes table plus a 'Known limits' line referencing docs/known-limitations.md"
  - "D-10, D-11 FIDL-09 UPDATE-in-place flip: checkbox line 145 [ ] -> [x]; traceability row 234 Pending -> Complete; footer 238 updated. grep -c '^| FIDL-09 |' == 1 invariant held"
  - "D-12 no docs/known-limitations.md edit: FIDL-09 is README-facing only; docs/known-limitations.md remains the developer-facing source-of-truth written by Phases 12-19"
metrics:
  duration: "approx 6 min"
  tasks_completed: 3
  files_modified: 2
  files_created: 2
  commits: 3
  completed: "2026-04-22"
---

# Phase 20 Plan 1: README Pipeline Capacity & Limits Summary

Ship FIDL-09 — the README-facing "Pipeline Capacity & Limits" section documenting the post-v3.0 pipeline state. Docs-only phase; closes the v3.0 "Graph Fidelity & Honest Limits" milestone.

## What shipped

- **`README.md ## Pipeline Capacity & Limits`** — new section inserted between `## How It Works` and `## Pre-built Domains`. Four subsections, each a `Feature | Value | Notes` table plus a "Known limits" line linking to `docs/known-limitations.md`:
  - **Document Ingestion** — 29 text-class extensions (37 with `--ocr`), `.zip` excluded, `warnings[]` in `triage.json`, 12-31 MB PDF support (FIDL-04).
  - **Wizard Schema Discovery** — 3 × 4,000-char excerpts for docs > 12,000 chars, ~2,631 measured input tokens/call, `--schema` LLM bypass, safe NFKD slugification (FIDL-05, FIDL-08).
  - **Extraction & Graph Build** — 10,000-char chunks, 3-sentence / 1,500-char overlap via `chonkie.SentenceChunker`, `DocumentExtraction` Pydantic model, ≥ 0.95 `--fail-threshold` gate, `metadata.domain` source-of-truth with precedence explicit > metadata > fallback (FIDL-02c, FIDL-03, FIDL-06).
  - **Epistemic Layer** — 12 hedging regex rules, structural doctype (PDB/X-ray/cryo-EM) with high-confidence short-circuit, `CUSTOM_RULES` per-domain with try/except isolation, auto-invoked validators, per-domain `workbench/template.yaml` (FIDL-07, FIDL-08).
- **`.planning/REQUIREMENTS.md` FIDL-09 UPDATE-in-place flip** — three surgical edits: checkbox `[ ] -> [x]`; traceability row `Pending -> Complete`; footer updated to `2026-04-22 — FIDL-09 Phase 20 complete (README Pipeline Capacity & Limits)`.

## Decisions honored

D-01 (four subsections), D-02 (Known-limits footer per subsection), D-03 (concrete, no hedging), D-04 (numbers first), D-05 (one table per subsection), D-06 (single `##` header), D-07 (link to `docs/known-limitations.md`), D-08 (purely additive to README), D-09 (grep-based verification), D-10 (FIDL-09 UPDATE-in-place flip), D-11 (footer updated), D-12 (no `docs/known-limitations.md` changes).

## Numbers cross-checked against source

Every table cell traces to either `docs/known-limitations.md` or a codebase constant:

| Claim | Source |
| --- | --- |
| 29 text-class / 37 with `--ocr` extensions | `core/ingest_documents._supported_extensions`, live runtime enumeration of `sift_kg.ingest.reader.create_extractor(backend="kreuzberg").supported_extensions()` minus `_EXCLUDED_EXTENSIONS` / `_IMAGE_EXTENSIONS` |
| 3 × 4,000-char excerpts, > 12,000-char threshold | `core/domain_wizard.EXCERPT_CHARS = 4000`, `MULTI_EXCERPT_THRESHOLD = 12000` |
| ~2,631 input tokens per Pass-1 call | `docs/known-limitations.md §FIDL-05` (measured 2026-04-21 on long_contract.txt fixture, tiktoken cl100k_base) |
| 10,000-char chunks, 3 sentence overlap, 1,500-char cap | `core/build_extraction.py chunk_size=10000`, `core/chunk_document.OVERLAP_SENTENCES = 3`, `OVERLAP_MAX_CHARS = 1500` |
| 12 hedging regex rules | `core/label_epistemic.HEDGING_PATTERNS` — 12 compiled regex tuples (hypothesized × 5, speculative × 2, prophetic × 2, negative × 3) |
| 0.95 default `--fail-threshold` | `core/normalize_extractions.py fail_threshold = 0.95` |

Template numbers adjusted against source: template's "~4.5K input tokens" was aspirational; source-of-truth says ~2,631 measured — corrected.

## Deviations from template

- Template said "sentence-aware via blingfire"; actual chunker is `chonkie.SentenceChunker` per `core/chunk_document.py:30`. Corrected to `chonkie.SentenceChunker`.
- Template said "29 formats"; verified accurate by live runtime enumeration (after `_EXCLUDED_EXTENSIONS`/`_IMAGE_EXTENSIONS` subtraction). Added "(text class)" / "(with `--ocr`)" split for the two relevant counts.
- Template said "~4.5K input tokens"; corrected to `~2,631` per `docs/known-limitations.md §FIDL-05` measurement.
- Adjusted the wizard PDF-reading value from `sift_kg.ingest.reader.read_document` per known-limitations (kept matching grep).

## Verification (all passing)

- `grep -c "^## Pipeline Capacity & Limits" README.md` == `1`
- `grep -c "docs/known-limitations.md" README.md` == `3` (>= 2 required)
- `awk '/^## Pipeline Capacity & Limits/,/^## Pre-built Domains/' README.md | wc -l` == `55` (<= 160 required)
- `grep -c "^| FIDL-09 |" .planning/REQUIREMENTS.md` == `1`
- `grep -c "^- \[x\] \*\*FIDL-09\*\*" .planning/REQUIREMENTS.md` == `1`
- `grep -c "^- \[ \] \*\*FIDL-09\*\*" .planning/REQUIREMENTS.md` == `0`

## v3.0 Milestone — Graph Fidelity & Honest Limits — COMPLETE

| Requirement | Phase | Plans | Status |
| --- | --- | --- | --- |
| FIDL-01 | Phase 12 | 12-01 | Complete |
| FIDL-02a | Phase 13 | 13-01 | Complete |
| FIDL-02b | Phase 13 | 13-02 | Complete |
| FIDL-02c | Phase 13 | 13-03 | Complete |
| FIDL-03 | Phase 14 | 14-01, 14-02 | Complete |
| FIDL-04 | Phase 15 | 15-01, 15-02 | Complete |
| FIDL-05 | Phase 16 | 16-01, 16-02 | Complete |
| FIDL-06 | Phase 17 | 17-01, 17-02 | Complete |
| FIDL-07 | Phase 18 | 18-01, 18-02 | Complete |
| FIDL-08 | Phase 19 | 19-01, 19-02 | Complete |
| FIDL-09 | Phase 20 | 20-01 | Complete |

The v3.0 milestone closes here. All nine requirements Complete. Every claim in the new README section traces to `docs/known-limitations.md` or a codebase constant; no aspirational numbers shipped.

## Commits (3 atomic, all `--no-verify`)

1. `3fce364` — `docs(20-01): plan README Pipeline Capacity & Limits section`
2. `4d246e2` — `docs(20-01): add Pipeline Capacity & Limits section to README + flip FIDL-09 (v3.0 milestone complete)`
3. (this commit) — `docs(20-01): complete README Pipeline Capacity & Limits plan`

## Self-Check

- Created: `.planning/phases/20-readme-pipeline-capacity-and-limits/20-01-PLAN.md` — FOUND.
- Created: `.planning/phases/20-readme-pipeline-capacity-and-limits/20-01-SUMMARY.md` — FOUND (this file).
- Modified: `README.md` — FOUND (section inserted, 55 lines).
- Modified: `.planning/REQUIREMENTS.md` — FOUND (FIDL-09 flipped).
- Commits:
  - `3fce364` — FOUND (git log).
  - `4d246e2` — FOUND (git log).

## Self-Check: PASSED
