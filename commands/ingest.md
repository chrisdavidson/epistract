---
name: epistract-ingest
description: Ingest scientific documents and build a drug discovery knowledge graph
---

# Epistract Document Ingestion Pipeline

You are running the epistract drug discovery knowledge graph pipeline.

## Usage Guard

**If invoked with no arguments or with `--help`:** Display the following usage block verbatim and stop — do not run any pipeline steps.

```
Usage: /epistract:ingest <corpus-dir> [options]

Required:
  <corpus-dir>    Directory or file path containing documents to ingest (PDF, DOCX, HTML, TXT, and 75+ formats)

Options:
  --domain <name>           Domain schema to use  (default: drug-discovery; choices: drug-discovery, contracts, clinicaltrials)
  --output <dir>            Output directory       (default: ./epistract-output)
  --validate                Enable molecular validation (auto-enabled if RDKit is installed)
  --view                    Open graph viewer after build (default: true)
  --fail-threshold <float>  Minimum extraction pass rate before graph build (default: 0.95, range: 0.0–1.0)
  --enrich                  Enrich graph via external APIs after build — clinicaltrials domain only
                            (Trial nodes → ClinicalTrials.gov v2; Compound nodes → PubChem PUG REST)
  --enrich-results          Also import ClinicalTrials.gov posted results (adverse events, PRIMARY/SECONDARY analyses) into the graph with provenance (implies --enrich) — clinicaltrials domain only
  --results-serious-min-pct <X>  Opt-in volume control for --enrich-results: keep a serious adverse event only when at least one arm has X% or more affected (default 0: every serious event)
  --refresh-results         With --enrich-results, re-import trials already enriched: update registry-owned values in place and flag vanished registry facts ctgov_withdrawn (never deletes) — clinicaltrials domain only

Examples:
  /epistract:ingest ./my-papers
  /epistract:ingest ./papers --domain clinicaltrials --enrich
  /epistract:ingest ./papers --domain clinicaltrials --enrich-results
  /epistract:ingest ./papers --domain clinicaltrials --enrich-results --results-serious-min-pct 1
  /epistract:ingest ./papers --domain clinicaltrials --enrich-results --refresh-results
  /epistract:ingest ./papers --domain contracts --output ./out --fail-threshold 0.9
```

## Arguments
- `path` (required): Directory or file path containing documents
- `--output` (optional): Output directory (default: ./epistract-output)
- `--domain` (optional): Domain name for extraction (default: drug-discovery). Choices: `drug-discovery`, `contracts`, `clinicaltrials`. Aliases (`contract`, `clinicaltrial`, `clinical_trials`) resolve automatically.
- `--validate` (optional): Enable molecular validation (default: true if rdkit installed)
- `--view` (optional): Open viewer after build (default: true)
- `--fail-threshold <float>` (optional): Minimum post-normalization pass rate required before graph build (default: 0.95, range: [0.0, 1.0]). Pipeline aborts with a clear error if the pass rate falls below this threshold.
- `--enrich` (optional flag): When present AND `--domain` is `clinicaltrials` (or aliases `clinicaltrial` / `clinical_trials`), triggers post-build enrichment against ClinicalTrials.gov v2 and PubChem PUG REST APIs. Trial nodes with NCT IDs get trial metadata; Compound nodes get molecular data. Non-blocking: API failures log counts but do not abort the pipeline.
- `--enrich-results` (optional flag): Implies `--enrich`. enrich.py then also reads each trial's `resultsSection` from the same single ClinicalTrials.gov payload; trials without posted results are counted and skipped; network/HTTP/parse failures are counted, never fatal. Registry AEs and analyses are written as AdverseEvent/OrganSystem/OutcomeAnalysis/Outcome/StatisticalMethod nodes tagged source `ctgov_results` with the NCT, merged with extracted nodes, idempotent on re-runs, and never creating Cohort nodes for unmatched registry groups.
- `--results-serious-min-pct <X>` (optional, with `--enrich-results`): a per-arm floor for serious adverse events, a number from 0 to 100. By default (0) every serious event is imported, as in 3.5.0. With X > 0 a serious event is kept only when at least one arm has X% or more of participants affected, which is the same per-arm rule the "other" events use with their registry threshold. "Other" events are not affected. The floor applies when a trial's results are first imported: a graph that was already enriched under another floor keeps its adverse events, and the report lists those trials under `serious_min_pct_conflicts`. To change the floor, re-run on the un-enriched graph. On corpus `07_glp1_phase3_trials`, X = 1 keeps 27 of 1782 serious records and X = 2 keeps 7, which cuts AdverseEvent nodes from 1118 to 61 or 46. See the volume table in the v2.1 report before you choose a value.
- `--refresh-results` (optional flag, requires `--enrich-results`): passed to enrich.py as `--refresh-results`. By default a trial whose registry results are already in the graph is skipped. With this flag those NCTs are re-imported: registry-owned attributes (nodes and edges tagged source `ctgov_results` and first written by this NCT) are updated in place, a payload attribute the new payload no longer produces (for example a removed p-value, or `count_basis` once an event is listed in one table only) is removed from them, and AEs and analyses new in the payload are added. On a registry node that other NCTs also support, such an attribute is kept, because their import may have filled it. On extracted or shared nodes only `registry_<attr>` / `registry_<attr>_by_nct` bookkeeping for this NCT changes, and no extracted value is touched. A dict such as `by_group` is refreshed the way a first import fills it: per-arm keys it lacks are added, and a per-arm value it already has is kept and not recorded (a first import records none either). A registry fact only this NCT supports that is missing from the new payload (also when the trial no longer has results) gets `ctgov_withdrawn: true`. On a fact other NCTs also support, the NCT is recorded in `ctgov_withdrawn_by_nct` (`{NCT: true}`), and a registry fact gets `ctgov_withdrawn: true` only once every NCT recorded on it has withdrawn it, whatever order the NCTs run in. When another NCT first reports a fact flagged `ctgov_withdrawn` (in a default run or a refresh), the flag is replaced by `ctgov_withdrawn_by_nct` entries for the NCTs already recorded, because the new NCT supports the fact. An extracted node or edge that the registry merged into only gets the `ctgov_withdrawn_by_nct` entry: its registry corroboration is gone, the extracted fact stays, and its `sources` still lists `ctgov_results`, so check `ctgov_withdrawn_by_nct` before treating it as registry-backed. Nothing is deleted, and a fact that reappears loses this NCT's entry and the flag. On an unchanged payload a refresh is a no-op, from the first refresh on. Through `ingest` every run fetches each trial live (no cache directory is passed), so a refresh always reads the current registry record; for direct runs with `--cache-dir`, see below. If the user passes `--refresh-results` without `--enrich-results`, stop and report the error "--refresh-results requires --enrich-results" instead of running enrichment.

### Registry arm-type treatment edges

With `--results`, a registry-created analysis whose treatment the Cohort-receiving rule did not resolve gets an `assesses_effect_of` edge from the registry arm types: the arm typed EXPERIMENTAL (or the arm the comparator is measured against, with an add-on background dropped) names the Compound. These edges carry `source: ctgov_results` and `treatment_basis: registry_arm_type`. They are written only for registry analyses, never for extracted analyses, and only when the treatment is unambiguous: an arm naming no Compound, a name shared by two Compound nodes, or two candidate compounds in one arm writes nothing. The arm-type rules use the same comparator wording as the epistemic layer: "Semaglutide + usual care" is an active add-on arm, "glycaemic control" names no arm, and a comparator such as "Usual care (metformin)" names no compound. A refresh withdraws the edge like any other registry fact. When a refresh resolves another compound, it writes the new edge, withdraws the old one and updates the analysis's stored `ctgov_arm_groups`. When the refreshed payload gives no arm groups for the analysis (no armGroups, or none matching a compared group), the edge is withdrawn and the stored `ctgov_arm_groups` is removed, so grading cannot resolve the old compound from it. A refresh that changes only the stored arm groups of an existing analysis counts it in `updated_nodes`. An analysis the refresh creates counts only in `created_nodes`. A withdrawn edge never blocks a new one. Registry analyses also record the outcome measure's `paramType` as `outcome_param_type`, which the epistemic layer uses to classify the outcome kind. Graphs enriched earlier get it on `--refresh-results`. Without `--results`, output is unchanged.

### Running enrich.py directly

`ingest` does not pass `--cache-dir`. For direct runs, `python3 ${CLAUDE_PLUGIN_ROOT}/domains/clinicaltrials/enrich.py <output_dir> --results --cache-dir DIR --cache-ttl-days N` refetches cached payloads whose file mtime is older than N days, and uses the stale payload when the refetch fails. The top-level `cache` report block counts `expired`, `refetched`, `stale_used`, and `stale_after_not_found` (stale payloads used because the refetch got a 404, so the trial may have left the registry; its facts are not withdrawn). `--cache-ttl-days` needs `--cache-dir`; by default a cache never expires. A direct `--refresh-results` run with `--cache-dir` reuses the cached payloads, so to pick up revised registry data combine it with `--cache-ttl-days` (0 refetches every cached trial) or a new cache directory.

## Pipeline Steps

### Step 1: Discover and Read Documents

Discover all documents in the provided path. Format support is resolved at runtime from sift-kg's Kreuzberg extractor — no hardcoded allowlist. Supported categories:

- **Documents**: PDF, DOCX, DOC, ODT, RTF
- **Spreadsheets**: XLSX, XLSM, XLS, ODS, CSV
- **Presentations**: PPTX
- **Web / Data**: HTML, HTM, XML, JSON, YAML, YML
- **Text / Notes**: TXT, MD, MARKDOWN, RST, LOG
- **eBooks**: EPUB, FB2
- **Email**: EML, MSG
- **Academic**: BIB, TEX, IPYNB
- **Images (OCR-gated)**: PNG, JPG, JPEG, GIF, WEBP, BMP, TIFF, TIF — discovered only when `--ocr` is set or the caller passes `discover_corpus(..., ocr=True)`
- **Archives**: `.zip` is explicitly excluded (breaks per-document provenance; see Phase 15 D-05)

Authoritative runtime list: whatever `sift_kg.ingest.create_extractor(backend='kreuzberg').supported_extensions()` returns — this string matches the Kreuzberg wheel currently installed, so adding a new format upstream is picked up automatically by `core.ingest_documents.discover_corpus`.

For each document, read its text content using sift-kg:
```python
from sift_kg.ingest.reader import read_document
text = read_document(Path(doc_path))
```

Extraction failures after discovery are recorded in `triage.json` under each document's `warnings[]` field (codes: `extraction_failed:<reason>`, `empty_text`) — discovery remains pure extension-match; content validation happens at parse time.

### Step 2: Chunk Text

Split each document's text into ~10,000 character chunks with overlap. Use your judgment on natural break points (paragraph boundaries, section headers).

### Step 3: Extract Entities and Relations

For EACH text chunk, extract entities and relations using the domain's SKILL.md for guidance. When spawning extraction agents, provide the domain name so they load the correct SKILL.md. Output valid JSON:

```json
{
  "entities": [
    {"name": "sotorasib", "entity_type": "COMPOUND", "attributes": {"modality": "small molecule"}, "confidence": 0.95, "context": "exact quote from text"}
  ],
  "relations": [
    {"relation_type": "INHIBITS", "source_entity": "sotorasib", "target_entity": "KRAS G12C", "confidence": 0.98, "evidence": "exact quote"}
  ]
}
```

Write each document's combined extraction to disk:
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/core/build_extraction.py <doc_id> <output_dir> --json '<combined_json>'
```

**Provenance threading (BOTH env var AND `--model` flag):** Before dispatching extraction agents, do BOTH of the following unconditionally:

1. Set `EPISTRACT_MODEL=<model_id>` in the invocation env for the agent dispatch.
2. Pass `--model <model_id>` literally in the Bash invocation shown in the dispatch prompt to the extractor agent.

Example dispatch-prompt Bash line shown to each agent:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/core/build_extraction.py <doc_id> <output_dir> --domain <domain_name> --model <model_id> --json '<combined_json>'
```

This is belt + suspenders per D-07 cascade (`--model` flag > `EPISTRACT_MODEL` env > null): if Claude Code's Agent tool inherits env vars, both paths succeed and the `--model` flag wins the cascade; if env inheritance does not work in this runtime, the `--model` flag alone still threads provenance end-to-end. No runtime ambiguity — both paths are always set.

**For 4+ documents:** Use the Agent tool to dispatch parallel extraction agents (one per document) for speed.

**Cap concurrency at 20 agents.** Dispatch at most 20 extraction agents at a time; for
larger corpora, process in successive waves of 20 and wait for each wave to return before
starting the next. "One per document" is the *mapping*, not the *batch size* — a 200-document
corpus is 10 waves, not 200 simultaneous agents. Beyond ~20 concurrent agents the runtime
queues them anyway, so the extra dispatches buy no speed while multiplying token spend and
making a partial failure much harder to attribute to a specific document.

### Step 3.5: Normalize Extractions

**MUST run AFTER all Agent-dispatched extractions complete.** Parallel Agent dispatches block until all return — but this step boundary is stated explicitly so future changes to the dispatcher do not accidentally break the sequencing.

Normalize the `extractions/*.json` files in place: rename variant filenames to canonical `<doc_id>.json`, infer missing `document_id` from filename stems, dedupe same-doc_id files (richer version wins; losers moved to `extractions/_dedupe_archive/`), and validate every payload against sift-kg's `DocumentExtraction` Pydantic schema.

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/core/normalize_extractions.py <output_dir> --fail-threshold 0.95
```

Pass the user's `--fail-threshold` value through if they supplied one; otherwise the default 0.95 applies.

A one-line summary prints to stdout. A detailed audit report is written to `<output_dir>/extractions/_normalization_report.json`. If the post-normalization pass-rate is below `--fail-threshold`, the script exits non-zero — the pipeline MUST abort before Step 4 and surface the error and the report path to the user.

### Step 4: Validate Molecular Identifiers

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/domains/drug-discovery/validate_molecules.py <output_dir>
```

### Step 5: Build Knowledge Graph

If `--domain` was provided to this command, pass it through. Otherwise omit (defaults to drug-discovery).

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/core/run_sift.py build <output_dir> --domain ${CLAUDE_PLUGIN_ROOT}/domains/drug-discovery/domain.yaml
```

### Step 5.5: Enrich Knowledge Graph (if --enrich flag provided)

Skip this step entirely unless BOTH of these are true:
1. The user passed `--enrich` or `--enrich-results` to the command.
2. The resolved `--domain` is `clinicaltrials` (or one of its aliases: `clinicaltrial`, `clinical_trials`).

When both conditions hold, invoke the domain's enrichment module:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/domains/clinicaltrials/enrich.py <output_dir>
```

If the user passed `--enrich-results`, append ` --results` to that command. If they also passed `--refresh-results`, append ` --refresh-results`. If they passed `--refresh-results` without `--enrich-results`, do not run enrichment: report the error "--refresh-results requires --enrich-results". If they also passed `--results-serious-min-pct <X>`, append ` --results-serious-min-pct <X>` as well. enrich.py refuses a floor above 0 without `--results`.

What this step does:
- Loads `<output_dir>/graph_data.json` via `sift_kg.KnowledgeGraph.load()`.
- For every Trial node whose name matches `NCT\d{8}`, calls the ClinicalTrials.gov v2 API (`/api/v2/studies/{nctId}`) and attaches `ct_overall_status`, `ct_phase`, `ct_enrollment`, `ct_start_date`, `ct_completion_date`, `ct_brief_title` as node attributes.
- For every Compound node, calls PubChem PUG REST (`/rest/pug/compound/name/{name}/property/.../JSON`) and attaches `pubchem_cid`, `molecular_formula`, `molecular_weight`, `canonical_smiles`, `inchi` as node attributes.
- Saves the mutated graph back to `graph_data.json`.
- Writes a summary to `<output_dir>/extractions/_enrichment_report.json` with per-entity-type counts (total / enriched / not_found / failed) and hit rates.
- With `--results`, the report also has a `results` block: trials with/without results, results_failed, adverse events parsed (serious/other), analyses parsed, created, merged. `created` counts registry nodes and edges written (`created_nodes` + `created_edges`), `merged` counts (node, trial) merges: one per extracted AE/analysis node per trial whose registry data it received (AE nodes are shared across trials, so one node merged by three trials counts 3), `merged_by_type` splits `merged` into AdverseEvent, OutcomeAnalysis and Outcome (`merged` is their sum; an Outcome merge is an extracted Outcome reused by a registry analysis, counted once per outcome and trial). With `--refresh-results` the block also has `refresh`: `trials_refreshed` (trials whose registry facts were already recorded), `updated_nodes`, `updated_edges` (including facts that only gained a `ctgov_withdrawn_by_nct` entry), `withdrawn` (facts flagged `ctgov_withdrawn`), `restored` (flags dropped, including a flag dropped because another NCT first reports the fact; such a join is not counted in `updated_nodes`/`updated_edges`, which count only facts the refreshed NCT had already recorded) and `legacy_copies_skipped` (a second edge copy of a fact on another Trial node of the NCT, left as it is: the copy the refresh did not write while it wrote the other one, or, when the payload no longer has the fact, a registry copy beside another registry copy from graphs enriched before iteration 27. A graph enriched by iterations 27-31 can hold a registry edge plus a merged extracted edge on a lower-id Trial node added later for the same fact; a refresh writes and withdraws both. A non-canonical Trial node's edge that is the NCT's only copy is refreshed and withdrawn like any other). With a cache TTL the report has a top-level `cache` block. Graph markers: a non-canonical Trial node that shares an NCT gets `same_trial_as` (registry edges are written once: through the edge that already records the NCT, else merged into the edge another Trial node of the NCT already has, else from the lowest id; so a Trial node added after the first import never gets a second copy), conflicting registry values are kept per NCT under `registry_<attr>_by_nct`, withdrawn registry facts carry `ctgov_withdrawn`, and per-NCT withdrawals carry `ctgov_withdrawn_by_nct`. `write_failed` counts trials whose write failed (a failed trial is rolled back, so no partial write is kept; `write_errors` maps each failed NCT to its error and appears only when a write failed), and `skipped_reason` appears when sift-kg is unavailable. With `--results-serious-min-pct X` (X > 0) the block also has `serious_min_pct` and `serious_events_omitted` (serious event records below the floor), `adverse_events_parsed.serious` counts only the kept ones, and each `reports_adverse_event` edge carries `serious_min_pct`. `serious_min_pct_conflicts` maps each trial imported earlier under a different floor to that floor. It appears only when there is at least one such trial, and those trials add nothing to `serious_events_omitted`.

Enrichment is **non-blocking**. If the Python process exits non-zero, report the failure to the user and continue to Step 6. Do NOT abort the pipeline — the unenriched graph is still valid output.

Rate-limit considerations:
- ClinicalTrials.gov: undocumented limit; enrich.py sleeps 0.1s between requests as a courtesy.
- PubChem: 5 req/sec official limit; enrich.py sleeps 0.2s between requests and retries up to 3x with exponential backoff on 429.

### Step 6: Open Visualization

Writes a self-contained `graph.html` (works offline, same graph look as the workbench) and opens it.

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/core/run_sift.py view <output_dir>
```

### Step 7: Report Summary

Tell the user:
- Documents processed and format breakdown
- Normalization pass-rate (read from `<output_dir>/extractions/_normalization_report.json`, e.g., "23/23 = 100.0% (0 recovered, 0 unrecoverable)")
- Total entities by type (table)
- Total relations by type (table)
- Molecular identifiers found and validated
- Communities detected
- Output directory location
- How to explore further (/epistract-query, /epistract-export)
