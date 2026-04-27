---
phase: 08-arxiv-cs-domain
plan: "02"
subsystem: corpus-assembly
tags: [arxiv, fetch-script, corpus, stdlib, unit-tests]
dependency_graph:
  requires: [08-01]
  provides: [fetch_arxiv_papers_script, arxiv_cs_corpus]
  affects: [08-03]
tech_stack:
  added: []
  patterns: [stdlib-urllib-fetch, xml-etree-parse, batch-id-list-request]
key_files:
  created:
    - scripts/fetch_arxiv_papers.py
    - tests/corpora/09_arxiv_cs/docs/1706_03762_attention_is_all_you_need.txt
    - tests/corpora/09_arxiv_cs/docs/1810_04805_bert.txt
    - tests/corpora/09_arxiv_cs/docs/2005_14165_gpt3.txt
    - tests/corpora/09_arxiv_cs/docs/2302_13971_llama.txt
    - tests/corpora/09_arxiv_cs/docs/1512_03385_resnet.txt
    - tests/corpora/09_arxiv_cs/docs/2010_11929_vit.txt
    - tests/corpora/09_arxiv_cs/docs/2103_00020_clip.txt
    - tests/corpora/09_arxiv_cs/docs/1412_6980_adam.txt
  modified:
    - tests/test_unit.py
decisions:
  - "Single batch id_list request for all 8 showcase papers (1 HTTP call total)"
  - "SLEEP_BETWEEN_REQUESTS=3.0 applied only in --category mode per arXiv guidance"
  - "render() uses inline FIELD_MAP labels matching fetch_fda_labels.py meta_block pattern"
metrics:
  duration: "~5 minutes"
  completed: "2026-04-26"
  tasks_completed: 2
  tasks_total: 2
  files_created: 9
  files_modified: 1
---

# Phase 08 Plan 02: arXiv CS Fetch Script + Corpus Summary

**One-liner:** stdlib-only arXiv Atom API fetch script with XML parsing, single-batch id_list request, and 8-document showcase corpus across cs.CL/cs.CV/cs.LG.

## What Was Built

### Task 1: fetch_arxiv_papers.py + ACS-05 unit tests

`scripts/fetch_arxiv_papers.py` (282 lines) mirrors `fetch_fda_labels.py` structure:

- `_parse_entries(xml_text)` — parses arXiv Atom XML with `xml.etree.ElementTree` + NS dict; strips URL prefix and version suffix from `<id>` via `rsplit("/",1)[-1].rsplit("v",1)[0]`; handles absent `arxiv:primary_category`
- `fetch_by_ids(id_list)` — single batch HTTP request using `urllib.request.Request` + `urlopen(timeout=30)`, returns `list[dict] | None`
- `fetch_by_category(category, max_results)` — category search variant with same error handling
- `render(paper, filename_stem)` — assembles FIELD_MAP header block + `=== ABSTRACT ===` section; UTF-8 byte-boundary trim to `MAX_CHARS=15_000`
- `main()` — three modes: default (SHOWCASE_IDS batch), `--ids`, `--category`; skip-if-exists; sleep only in category mode

Constants: `MAX_CHARS = 15_000`, `SLEEP_BETWEEN_REQUESTS = 3.0`, `SHOWCASE_IDS` (8 tuples), `NS` namespace dict, `FIELD_MAP` (8 label tuples).

Two ACS-05 unit tests appended to `tests/test_unit.py`:
- `test_acs05_fetch_parse_mock_xml` — reads `tests/fixtures/arxiv_api_mock.xml`, calls `_parse_entries()`, asserts 2 papers, IDs without version suffix or URL path, non-empty abstract/title, authors as list
- `test_acs05_fetch_render_fields` — calls `render()` with synthetic paper dict, asserts starts with `arXiv Paper:`, contains `=== ABSTRACT ===`, title and authors present, byte length `<= MAX_CHARS`

### Task 2: 8-document showcase corpus (ACS-06)

Corpus produced via **single batch API call** — `fetch_by_ids` with all 8 IDs in one `id_list` parameter (1 HTTP request total, no per-paper sleep).

| File | Bytes | Category | Paper |
|------|-------|----------|-------|
| 1706_03762_attention_is_all_you_need.txt | 1532 | cs.CL | Attention Is All You Need |
| 1810_04805_bert.txt | 1358 | cs.CL | BERT |
| 2005_14165_gpt3.txt | 2518 | cs.CL | GPT-3 (Language Models are Few-Shot Learners) |
| 2302_13971_llama.txt | 989 | cs.CL | LLaMA |
| 1512_03385_resnet.txt | 1599 | cs.CV | ResNet |
| 2010_11929_vit.txt | 1702 | cs.CV | ViT |
| 2103_00020_clip.txt | 1918 | cs.CV | CLIP |
| 1412_6980_adam.txt | 1493 | cs.LG | Adam optimizer |

**Total corpus size:** 14,109 bytes across 8 files
**API calls made:** 1 (single batch id_list request)
**Failed papers:** 0

All files contain `=== ABSTRACT ===`, are within 15,000 byte limit, and contain no secrets.

## ACS-05 Unit Test Results

| Test | Status |
|------|--------|
| test_acs05_fetch_parse_mock_xml | PASSED |
| test_acs05_fetch_render_fields | PASSED |

**Pass count: 2/2** (no live network — uses `tests/fixtures/arxiv_api_mock.xml` fixture)

## Decisions Made

1. **Single batch request** — All 8 SHOWCASE_IDS fetched in one `id_list` call. No sleep needed in default mode; `SLEEP_BETWEEN_REQUESTS=3.0` applies only to `--category` mode which makes one call per category.

2. **Render format** — Inline label format (`arXiv ID: ...`, `Title: ...`) per plan FIELD_MAP spec and `08-RESEARCH.md` render pattern. Matches `fetch_fda_labels.py` `_meta_block()` pattern.

3. **No argparse** — Manual `sys.argv` parsing per CLAUDE.md conventions.

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None. All 8 corpus files contain real abstract content from the arXiv API.

## Threat Flags

None. T-08-05 mitigated: `grep -riE "password|secret|api_key"` on corpus returned no matches. T-08-06 mitigated: single batch request for showcase corpus; rate-limit sleep enforced in category mode.

## Commits

- `daf1c61` — feat(08-02): add fetch_arxiv_papers.py and ACS-05 unit tests
- `8aec7be` — feat(08-02): add arXiv CS showcase corpus (ACS-06)

## Self-Check: PASSED

- scripts/fetch_arxiv_papers.py: FOUND (282 lines, ruff-clean, no requests import)
- tests/corpora/09_arxiv_cs/docs/ (8 files): FOUND, all within 15000 bytes
- ACS-05 tests in tests/test_unit.py: FOUND, 2/2 passing
- Commit daf1c61: FOUND
- Commit 8aec7be: FOUND
