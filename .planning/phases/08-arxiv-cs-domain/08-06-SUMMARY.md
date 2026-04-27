---
plan: 08-06
phase: 08-arxiv-cs-domain
status: complete
completed_at: 2026-04-27
subsystem: docs
tags: [readme, changelog, arxiv-cs, documentation]
---

# Phase 08 Plan 06: README + CHANGELOG Documentation Update Summary

## One-liner

Updated README.md and CHANGELOG.md to document the fifth pre-built domain (arxiv-cs) with 94 nodes / 179 edges / 1637-word narrative.

## What Was Built

Documentation-only update. Two files edited to reflect the addition of the `arxiv-cs` domain completed in plans 08-01 through 08-05.

## README.md Changes

Four targeted edits:

1. **"four" to "five" (line 9, two occurrences)** — Updated the architecture diagram caption:
   - `the four pre-built domains` changed to `the five pre-built domains`
   - `The four pills along the bottom` changed to `The five pills along the bottom`

2. **Domain list sentence (line 17)** — Updated the inline domain enumeration:
   - `four domains out of the box (drug-discovery, contracts, clinicaltrials, fda-product-labels)` changed to `five domains out of the box (drug-discovery, contracts, clinicaltrials, fda-product-labels, arxiv-cs)`
   - Appended after the fda-product-labels sentence: `arxiv-cs launched its first showcase in v1.1 (8-paper arXiv CS corpus, S9 — Transformer, BERT, GPT-3, LLaMA, ResNet, ViT, CLIP, Adam).`

3. **Pre-built Domains table** — Inserted new arxiv-cs row after the fda-product-labels row:
   - Schema: 12 / 10
   - Scenario: S9 arXiv CS Papers (94 nodes / 179 edges, 1637-word narrator briefing)
   - Links to `tests/scenarios/scenario-09-arxiv-cs-papers.md` and `docs/SHOWCASE-ARXIV-CS.md`
   - Specialty pipeline: four-level preprint epistemology (claimed / reproduced / ablated / theoretical)

4. **Footer domain list** — Updated from "All four" to "All five" and added `domains/arxiv-cs/domain.yaml` to the inspectable paths list.

## CHANGELOG.md [3.2.2] Entry

Inserted at line 5 (immediately after the 4-line file header, before the previous top entry [3.2.1]).

**Actual values used (sourced from 08-03-SUMMARY.md):**
- Nodes: 94
- Edges/Links: 179
- Narrator word count: 1637

Entry covers:
- Fifth pre-built domain (`arxiv-cs`) — 12 entity types, 10 relation types
- `scripts/fetch_arxiv_papers.py` fetch script
- 8 arXiv CS abstract text files (IDs: 1706.03762, 1810.04805, 2005.14165, 2302.13971, 1512.03385, 2010.11929, 2103.00020, 1412.6980)
- Full pipeline output artifacts
- `tests/scenarios/scenario-09-arxiv-cs-papers.md` (S9)
- `docs/SHOWCASE-ARXIV-CS.md`
- 4 workbench screenshots
- Unit tests ACS-01 through ACS-06

## Phase 08 Completion Confirmation

Phase 08 (08-arxiv-cs-domain) is complete. Coverage by plan:

| Plan | Description | Requirements covered |
|------|-------------|---------------------|
| 08-01 | arxiv-cs domain package (domain.yaml, SKILL.md, epistemic.py) | ACS-01, ACS-02 |
| 08-02 | fetch script + test fixtures | ACS-03, ACS-04 |
| 08-03 | Run pipeline (94 nodes, 179 links, 1637-word narrative) | ACS-05, ACS-06, ACS-07 |
| 08-04 | Scenario doc + showcase doc + screenshots | ACS-08 |
| 08-05 | Unit tests (ACS-01 through ACS-06 test IDs) | — |
| 08-06 | README + CHANGELOG documentation | — |
| 08-07 | arXiv URL enrichment on PAPER nodes | — |

ACS-01 through ACS-08 are covered across plans 08-01 through 08-04 (domain package, fetch script, pipeline run, scenario/showcase docs). Plans 08-05 through 08-07 add unit tests, documentation updates, and URL enrichment respectively.

## Deviations from Plan

None — plan executed exactly as written.

## Self-Check: PASSED

- README.md: `grep -q "arxiv-cs"` OK, `grep -q "scenario-09-arxiv-cs-papers"` OK, `grep -q "SHOWCASE-ARXIV-CS"` OK, `grep -c "five"` = 4
- CHANGELOG.md: [3.2.2] entry at line 5, `fetch_arxiv_papers` present, `1706.03762` present
