# Roadmap: Epistract — v1.1 ArXiv Computer Science Domain

## Milestones

- ✅ **v1.0 FDA Product Labels Domain** — Phases 01-07 (shipped 2026-04-26)
- 🚧 **v1.1 ArXiv CS Domain** — Phase 08 (in progress)

## Phases

### 🚧 v1.1 ArXiv CS Domain (In Progress)

- [ ] Phase 08: arxiv-cs-domain — Build domain schema, extraction prompt, epistemic module, and fetch/corpus script for arXiv Computer Science papers

## Progress

| Phase | Milestone | Plans | Status | Completed |
|-------|-----------|-------|--------|-----------|
| 08. arxiv-cs-domain | v1.1 | 3/7 | In Progress|  |

## Phase 08: arxiv-cs-domain

**Goal:** Deliver the fifth pre-built domain (arxiv-cs) with a 12-entity-type / 10-relation-type schema, four-level preprint epistemology (claimed/reproduced/ablated/theoretical), fetch script, 8-paper showcase corpus, full pipeline run, documentation, workbench screenshots, and arXiv URL enrichment on PAPER nodes.

**Requirements:** ACS-01, ACS-02, ACS-03, ACS-04, ACS-05, ACS-06, ACS-07, ACS-08

**Plans:**
3/7 plans executed
- [x] 08-02-PLAN.md — Fetch script (scripts/fetch_arxiv_papers.py) + 8-document corpus + ACS-05 unit tests
- [x] 08-03-PLAN.md — Full pipeline run: ingest, extract, normalize, graph build, epistemic analysis, narrator (autonomous:false)
- [ ] 08-04-PLAN.md — Documentation: scenario-09-arxiv-cs-papers.md + SHOWCASE-ARXIV-CS.md
- [ ] 08-05-PLAN.md — Workbench screenshots (4 PNG files, port 8045, autonomous:false)
- [ ] 08-06-PLAN.md — README.md + CHANGELOG.md updates
- [ ] 08-07-PLAN.md — arXiv URL enrichment: abs_url on PAPER nodes via epistemic.py + extraction JSON patch
