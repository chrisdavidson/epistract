# Changelog

All notable changes to epistract are documented here. This project follows [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Changed
- **Crosswalk `shared_by_all_graphs` semantics:** it now counts keys present in every graph that contributes at least one key to the axis, instead of every graph that declares the axis. Before, a declaring graph with no keys on the axis (for example a clinicaltrials graph with no adverse events) made the count 0. It is 0 when fewer than two graphs contribute.

### Added
- **clinicaltrials registry edges once per NCT (Domain Builder iteration 27, commit 9ff9e3d; tests 849b005):** with `--results`, registry edges starting at a Trial are written once from the canonical Trial node (lowest id) and other Trial nodes of the NCT get `same_trial_as`. Conflicting registry values are also kept per NCT as `registry_<attr>_by_nct`, and the results report gains `merged_by_type` (AdverseEvent, OutcomeAnalysis, Outcome); `merged` now counts Outcome merges. Output without `--results` is unchanged; a fresh `--results` run differs only by the `_by_nct` keys and `merged_by_type` (corpus 07: 369 nodes gain `_by_nct`, counts identical).
- **clinicaltrials `--refresh-results` and `--cache-ttl-days` (Domain Builder iteration 28, commit c7aa6f9; tests 3637986):** `--refresh-results` re-imports registry facts in place, adds new AEs and analyses, and flags facts missing from the payload `ctgov_withdrawn` (never deletes, never changes extracted values). `--cache-ttl-days N` (with `--cache-dir`) refetches payloads older than N days and falls back to the stale payload on failure. Defaults are byte-identical to iteration 27. `commands/ingest.md` documents both.
- **clinicaltrials refresh no-op (Domain Builder iteration 29, commit 466cf72; tests fee21b3):** `--refresh-results` on an unchanged payload changes nothing (corpus 06: 0 updated nodes and edges; iteration 28 gave 9 and 14). In a refresh only the first write of an NCT applies, and a shared registry edge first written by another NCT gets no attributes, as in a first import.
- **clinicaltrials refresh review fixes (Domain Builder iteration 30, commit caa8af0; tests 35c038a):** a refresh withdraws a fact that other NCTs also support only per NCT (`ctgov_withdrawn_by_nct`), and flags `ctgov_withdrawn` once every NCT recorded on it has withdrawn it, whatever the NCT order. A registry-owned fact drops payload attributes the new payload no longer produces (a removed p-value, `count_basis`/`by_seriousness` after an event leaves the serious table). Changed `by_group` values on merged extracted edges are kept as `registry_by_group_by_nct`, and extracted facts whose registry data vanished get `ctgov_withdrawn_by_nct`. `trials_refreshed` counts only trials already recorded, and the cache block adds `stale_after_not_found`. With `--results`, registry counts now merge into an extracted AE edge on a non-canonical Trial node instead of a parallel canonical edge. Apart from that case, default runs are byte-identical to iteration 29 (fixture tests; corpus 07 graph equal). The byte-identity tests fail instead of skipping when a pinned commit is missing, unless `CT_ALLOW_MISSING_BASELINES=1` is set.
- **clinicaltrials refresh round-2 review fixes (Domain Builder iteration 31, commit d77cc0e; tests d9423c0):** when another NCT first reports a fact that a refresh flagged `ctgov_withdrawn` (in a default run or a refresh), the flag is replaced by `ctgov_withdrawn_by_nct` entries for the NCTs already recorded, so the earlier withdrawal is kept whatever the NCT order and a refresh on unchanged payloads is a no-op from the first run. The refresh sweep now withdraws a registry edge on a non-canonical Trial node when it is the NCT's only copy (for example after a lower-id Trial node was extracted later); only edges another Trial node of the NCT also has count as `legacy_copies_skipped`. A dict attribute such as `by_group` on a merged extracted fact is refreshed by the first-import rule: missing per-arm keys are added, existing per-arm values are kept and not recorded, so the iteration-30 `registry_by_group_by_nct` bookkeeping is no longer written (and is dropped on the next refresh). Default runs are byte-identical to iteration 30 (fixture tests; corpus 07 graph equal), except on graphs a refresh left with `ctgov_withdrawn` facts that another NCT joins. Corpus 06: refresh on the unchanged cache is still byte-identical.
- **clinicaltrials refresh round-3 review fixes (Domain Builder iteration 32, commit 40d3834; tests 88f8121):** registry edges are written through the Trial node whose edge already records the NCT, so a lower-id Trial node with an extracted edge added after the first import no longer receives a second copy of the NCT's registry data (iteration 31 merged into it, after which the original registry edge was never refreshed or withdrawn). On graphs iterations 27-31 already left with both copies, a refresh writes both (the extracted copy through its `registry_*` bookkeeping) and, when the payload drops the fact, withdraws the registry copy and records `ctgov_withdrawn_by_nct` on the extracted one; `legacy_copies_skipped` counts only a copy the refresh did not write while it wrote the other, or pre-iteration-27 registry copies. The `refresh` block docs now say that `restored` includes flags dropped by a joining NCT and `updated_*` excludes them. Default runs are byte-identical to iteration 31 (fixture tests; corpus 07 graph equal), except in that late-Trial-node case, where the extracted edge is left as extracted. Corpus 06: refresh on the unchanged cache is still byte-identical (0 updated, 0 withdrawn). The round-3 fixes were not re-reviewed (review cap of 3 rounds).
- **clinicaltrials 999.4 dose- and outcome-kind-aware contests (Domain Builder iterations 33-35, commits 3f30247 (C33), 27fd037 (C34), 84742eb (C35); tests 5ce704f, 6860d24, 6ab3a08):** registry contests are keyed by outcome kind (responder, continuous, time-to-event) and by dose when every finding carries one (`dose_aware`, else a dose-unaware fallback). Treatments are read from an `assesses_effect_of` edge, then registry arm types, then titles, with `ambiguous_active_comparator` and `label_conflict` flags and new `analysis_*` summary keys. Withdrawn registry facts are no longer corroboration (`registry_withdrawn`). With `--results`, registry analyses get `assesses_effect_of` edges (`treatment_basis: registry_arm_type`) from arm types. Without registry data, output is identical to iteration 32 (07 and q4m9). Measured offline: corpus 07 contested 1 to 1 and contradictions 1 to 1 (the semaglutide MACE contest gains `time_to_event`), +148 arm-type edges; corpus 06 contested 0 to 0 and contradictions 0 to 0, +80 arm-type edges; hand-check 0 wrong (`docs/reports/v2.2-phase13-999.4.md` in Domain Builder).
- **`contributing_graphs`** in per-axis crosswalk stats: the sorted declaring graphs that hold at least one key on the axis. `declared_by` is unchanged.
- **Domain Builder shared-crosswalk path:** `crosswalks/` is now tracked and validated by Domain Builder as `_crosswalks` (loaded by this repo's own crosswalk loaders), and an applied iteration can be committed to a named branch of this repo.

### Fixed
- **clinicaltrials 999.4 contest review fixes (Domain Builder iteration 36, commit 759346f; tests 4fd0d57):** the dose parser reads thousands separators ("1,000 mg" was read as 0 mg, "1,500 mg" as 500 mg) and treats a range ("12-45 mg", "0.25 to 1 mg") as no single dose, so 1,000 mg and 2,000 mg arms no longer form a dose-aware contest. A withdrawn NCT's `ctgov:` document is no longer a support document of the finding or its contest entries, also when the node inherited it in `source_documents`. An analysis whose outcome kind is unknown joins the one known kind of its measure and treatment instead of forming its own group. The outcome kind is read from the registry measure `paramType` (now stored on registry analyses as `outcome_param_type`) and `unitOfMeasure` before the title. "HR" in a title (heart rate), a threshold naming a continuous subgroup and a measured duration ("Time to Exhaustion") no longer change the kind. When a Cohort name and its registry arm label disagree on the dose, `dose_mg` is null. `ambiguous_active_comparator` is set only when the arm types are absent. In enrichment, a withdrawn arm-type `assesses_effect_of` edge no longer blocks a new one, and a refresh that resolves another compound moves the edge and updates `ctgov_arm_groups`. The arm-type resolver now uses the epistemic layer's comparator wording ("Semaglutide + usual care" is an active add-on arm), and a parity test pins this. Without registry data, output is identical to iteration 32 (07 and q4m9). Corpus 07 contested 1 to 1, contradictions 1 to 1; corpus 06 0 to 0 and 0 to 0; `assesses_effect_of` unchanged (148 and 80 arm-type edges); 40 and 27 label-conflict findings lose a dose (`docs/reports/v2.2-phase13-999.4.md` in Domain Builder).
- **clinicaltrials `_ae_key` residual British spellings (Domain Builder iteration 23, commit 05d0850):** the AE matching key now merges Paraesthesia, Faecal incontinence, Gynaecomastia, Leucopenia, Hypooestrogenism and Angio-oedema with their US spellings. US compounds with an o-prefix (Angioedema, Hypoestrogenism, Phytoestrogen) keep their own keys, because the `oedem` and `oestr` stems are now anchored. `tests/test_ctgov_results.py` pins these pairs (commit e68179a).
- **clinicaltrials `_ae_key` review fixes (Domain Builder iteration 24, commit aafcb45):** the `aesthe` stem also covers anaesthetic terms (Anaesthetic complication), `oestr` folds only at a word start or after o/er/yl so US Xenoestrogen and Proestrus keep their keys, and Leucovorin is no longer folded. Pinned in `tests/test_ctgov_results.py` (commit 296cec7).
- **clinicaltrials `_ae_key` round-2 review fixes (Domain Builder iteration 25, commit df08d43):** `oestr` is a denylist again: it folds everywhere except after the US o-prefixes hyp/phyt/xen/pr. British compounds that iteration 24 had split from their US forms (Diethylstilboestrol, Stilboestrol, Antioestrogen, Fosfoestrol, Hexoestrol, Dienoestrol, Polyoestradiol, Dioestrus, Anoestrus, Metoestrus) merge again, while Hypoestrogenism, Phytoestrogen, Xenoestrogen and Proestrus keep their keys. `aesthe` now needs a preceding letter, so the US word "aesthetic" is not rewritten, and the genus Leuconostoc is no longer folded. Pinned in `tests/test_ctgov_results.py`.
- **clinicaltrials `_ae_key` round-3 review fixes (Domain Builder iteration 26, commit cf9e8b7):** the `oestr` denylist also covers the US o-prefixes myc/metall/neur/pseud/zo, so Mycoestrogen, Metalloestrogen, Neuroestradiol, Pseudoestrus and Zooestrogen keep their keys, are not flagged as British, and merge with their British oo-forms (Mycooestrogen, Neurooestradiol). The prefix list is best-effort: a US compound with a linking "o" before "estr" cannot be told apart from a British spelling, so an unlisted US prefix is still folded. `aesthe` is split into `aesthes` (folds everywhere: Aesthesioneuroblastoma, Hypo-aesthesia) and `aesthet` after a letter (Anaesthetic), so the US word "aesthetic" keeps its key. Pinned in `tests/test_ctgov_results.py` (commit e113f6c).

### Measured
- **corpus 06 (34 documents, 9 NCTs), `--results`:** nodes 316 to 1,786, links 1,245 to 7,718, AdverseEvent 9 to 1,168, OutcomeAnalysis 16 to 241, Outcome 49 to 106. One extracted AE merged with its registry record, hand-checked correct; 0 wrong merges. `--refresh-results` on the unchanged cache is byte-identical (`docs/reports/v2.2-phase12-999.3.md` in Domain Builder).
- **corpus-07 AE count, iteration 22 to 23, 24, 25 and 26:** 1,118 to 1,118 (delta 0 for each). The corpus holds only one spelling of each of the six pairs, so nothing merged (`docs/reports/v2.2-phase11/corpus07_ae_delta.json` in Domain Builder).
- **`pharma.yaml` adverse_event axis (Domain Builder crosswalk iteration 2, commit 1b3b446):** the clinicaltrials x pharmacovigilance join is 30 before and after. Seven further British-to-US pairs (anaem, paraesth, faec, oesophag, leucop, gynaecom, oestr) each measured +0, so none were added; the change records that measurement in the axis comment.

## [3.5.0] — 2026-11-20

**Clinical trials results enrichment from ClinicalTrials.gov.** The `clinicaltrials` domain can now fill adverse events and outcome analyses directly from a trial's posted results in the ClinicalTrials.gov API v2 (`resultsSection`). This is the same source the CTKG paper and AACT use, so these facts no longer depend on what the extractor happened to read. It is opt-in: without the new flag, `--enrich` output is byte-identical to 3.4.0, and graphs without registry data grade exactly as before. Domain Builder iterations 8–22 reviewed and applied the changes.

### Added
- **`/epistract:ingest --enrich-results`** (`enrich.py --results [--cache-dir DIR]`): fetches each trial once and reads protocol and results from the same payload. Network, HTTP and parse failures never stop the pipeline. `_enrichment_report.json` gains a `results` block with counts of trials with and without results, failures, parsed AEs and analyses, and created and merged nodes. `--cache-dir` makes runs reproducible offline.
- **Registry adverse events:** every serious event, plus "other" events at or above the registry's reporting threshold in at least one arm. A 5% floor applies when the registry reports a threshold of 0. Each event has `reported_term`, and gets `meddra_pt`/`meddra_version` only when the registry says the term is MedDRA-coded; no dictionary is shipped. Events link to their `OrganSystem`, their `Trial`, and the matching `Cohort` arms, with per-arm counts on the edges. Arms that don't match an existing Cohort are never created.
- **`--results-serious-min-pct X`** (`/epistract:ingest` and `enrich.py`, `enrich_graph(serious_min_pct=X)`): an opt-in per-arm floor for serious events. A serious event is kept only when at least one arm has X% or more of participants affected. The default 0 keeps every serious event, and output is then byte-identical to the behaviour without the flag. With X > 0, the `results` block records `serious_min_pct` and `serious_events_omitted`, and each AE edge carries `serious_min_pct`. A trial already imported under another floor keeps its AEs and is listed under `serious_min_pct_conflicts`.
- **Registry outcome analyses:** analyses on PRIMARY and SECONDARY measures become `OutcomeAnalysis` nodes with p-value (keeping inequalities such as `<.001`), effect estimate and measure, CI, non-inferiority type and timeframe. They link to the Outcome, compared arms and a shared `StatisticalMethod`, and keep the registry arm types in `ctgov_arm_groups`.
- **Provenance and merge:** every registry fact carries `source: ctgov_results` and its NCT ID. A registry fact merges into the extracted fact for the same event or analysis in the same trial, never across trials; conflicting registry values are kept under `registry_*` keys. Re-running enrichment is idempotent.

### Changed
- **Epistemic grading with registry analyses:** registry values decide significance over extracted ones, and each finding records `significance_source` and `treatment_basis`. Trials are found by NCT ID. The drug being tested is found from the compared arms, the registry arm types (EXPERIMENTAL vs comparator) or arm titles. Outcomes without a StandardOutcome are grouped by a normalised measure key, in which 3-point MACE titles ("MACE", "major adverse cardiovascular events", or death + non-fatal MI + non-fatal stroke) share the key `mace`. Contests are decided per outcome title and then merged, so the same trial pair, drug and key gives one entry. An entry carries `design_note` when a compared analysis is registered with a `non_inferiority_type` other than SUPERIORITY. Non-inferiority analyses aren't graded as efficacy, and different doses within one trial don't count as contests. New summary keys: `analysis_by_source`, `analysis_superseded`, `analysis_treatment_unresolved`.
- The AdverseEvent description allows `meddra_pt` to come from the registry. The AE matching key now handles British spellings by stem, and no longer strips "oe" from words like "toe".

### Measured (corpus `07_glp1_phase3_trials`, 10 GLP-1 Phase 3 trials)
- 1,118 adverse events, 27 organ systems, 177 analyses, 7 statistical methods. High-evidence claims went from 278 to 2,036, and every analysis from a blinded Phase 3 trial is high-evidence.
- 1 analysis contradiction: SUSTAIN-6 vs PIONEER 6 (semaglutide, MACE), which was reported twice under two outcome titles before the MACE key. It is a real disagreement in the registry and is kept. Its `design_note` records that the compared analyses are registered as SUPERIORITY_OR_OTHER, OTHER and SUPERIORITY. The trials also differ in formulation (injectable vs oral semaglutide).
- The graph grows about 7.5x in nodes, because serious events are uncapped by default. With `--results-serious-min-pct 1` corpus 07 has 61 adverse events and 508 nodes instead of 1,118 and 1,575. With 2, it has 46 and 491.

## [3.4.0] — 2026-11-19

**Clinical trials schema v2: safety, outcome standardisation and evidence grading.** The `clinicaltrials` domain adopts the concepts and relations of the Clinical Trials Knowledge Graph (CTKG; Chen et al., *Sci Rep* 12:4724, 2022) for document extraction. It now models adverse events and the organ systems they affect, links every arm and dose-specific intervention to its compound, maps trial-specific outcomes to canonical measures, and grades efficacy claims from reported statistical analyses. All changes are additive: no type or relation was renamed or removed, and graphs built with 3.3.0 still analyse with identical results. The changes were reviewed and applied in six recorded iterations with the epistract Domain Builder.

### Added

- `clinicaltrials` entity types (12 → 17):
  - `AdverseEvent`
  - `OrganSystem`, a node type of its own at system-organ-class level
  - `StandardOutcome`, the canonical measure shared across trials, such as "HbA1c" or "Body weight"
  - `OutcomeAnalysis`, a reported comparison with its effect estimate, confidence interval and p-value
  - `StatisticalMethod`
- `clinicaltrials` relation types (12 → 23):
  - Safety: `reports_adverse_event`, `observed_in`, `affects_organ_system`
  - Drug linkage: `receives`, `contains_compound`, `uses_background_drug`
  - Evidence: `measures`, `analyzes`, `compares`, `assesses_effect_of`, `uses_method`
- Extraction guidance in `SKILL.md`:
  - Drug-linkage rules: every dose-specific Intervention links to its Compound, and every arm links to what it receives.
  - Standard-outcome identification rules, following CTKG §4.3.
  - Canonical statistical-method names.
  - OutcomeAnalysis naming and attributes, extracted only when a result is reported.
  - New quality checks.
- **Adverse Event Normalization**: rule-based naming with no MedDRA lookup, following CTKG §4.1.
  - Strip asides, laterality and timeframes, and name the event rather than its grade or arm.
  - Use US spelling and preferred-term-level wording, and merge spelling variants.
  - Keep the source wording in `reported_term`. Add `meddra_pt` only when the extractor is confident of it.
  - No MedDRA dictionary content is shipped, because its license does not allow it.
- Evidence grading from OutcomeAnalysis in `epistemic.py`:
  - A significant result counts as asserted, a non-significant one as negative, and an undecidable one as unresolved.
  - Significance is read from p-value text first. That text may be "<0.001", "NS" or "0,03". The next fallback is a numeric p-value in [0, 1]. Last comes the confidence interval against the right null: ratio measures, such as aHR or "Hazard Ratio (HR)", are recognised by pattern.
  - A standard outcome and treatment pair is contested only when results disagree across different trials. It is also a contradiction when both sides include high-evidence trials.
  - New output keys:
    - `summary.analysis_claims_found`, `analysis_graded`, `analysis_contested_found` and `analysis_status_counts`
    - `base_domain.analysis_claims`
- `clinicaltrials/crosswalk.yaml`: an `adverse_event` axis that matches on `meddra_pt` and falls back to the name, which is the same key as pharmacovigilance. There is also a `trial → adverse_event` edge.

### Changed

- The `clinicaltrials` crosswalk `outcome` axis now takes keys from `StandardOutcome` first, then `Outcome`. `clinicaltrials` now appears in `declared_by` for the `adverse_event` axis. Graphs extracted before 3.4.0 contribute no adverse-event keys.
- The `clinicaltrials` workbench persona lists the new entity types.
- `clinicaltrials` epistemic grading no longer needs enrichment. When the `enrich.py` registry fields are absent it falls back to the normalized extracted `attributes.phase` (3a/3b, roman numerals, 2/3 as 2, NA ignored), then to the linked `TrialPhase` node (`is_phase`), and reads blinding from strict design text (open-label wins; "placebo-controlled" or "randomised" alone is not blinding). OutcomeAnalysis contradictions can therefore fire on un-enriched graphs (Domain Builder iteration 7).
- The test tables for the `clinicaltrials` schema were updated in `tests/test_domain_display.py`, `tests/test_unit.py` and `tests/test_crosswalk.py`. These are assertion changes only.

### Notes

- Re-extract existing `clinicaltrials` projects to populate the new types. On a 10-document GLP-1 registry corpus, compound linkage rose from 0% to 86% and 95% of outcomes mapped to a canonical measure. Registry protocol summaries carry no results, so OutcomeAnalysis and adverse-event coverage depend on documents that report results.
- The shared `crosswalks/pharma.yaml` normalizers are unchanged.

## [3.3.0] — 2026-10-24

**Workbench refresh: Material Paper theme, a richer Dashboard, and an offline `graph.html`.** The workbench gets a new visual identity, a Dashboard that shows where to start and the health of the evidence, a source viewer, and `/epistract:view` now writes the workbench graph as a single offline page. `graph.html` is built from the workbench graph renderer instead of sift-kg/pyvis, so the standalone page and the workbench look and behave alike.

### Added

- Workbench Dashboard: Where to start (largest topic communities and most-connected entities), an Epistemic health section with contradictions and contested claims, a documents table, and Ask about this on every card (fork PRs #8, #10).
- Source viewer: open a document from the Dashboard, a citation or the graph, with the cited passage highlighted (fork PR #8).
- Graph sidebar Ask about this opens Chat with the same double-press guard as the Dashboard (fork PR #11).
- Workbench Clear chat control, and an Epistract favicon instead of a 404 (fork PR #9).
- Self-contained `graph.html` built from the workbench renderer (`examples/workbench/static_export.py`, payloads from `core/graph_payloads.py`); works offline from disk with no external scripts.
- `--depth <d>` (hop radius for `--neighborhood`) and `--no-open` (write without opening a browser) flags.
- Subset notice for `--neighborhood` / `--top` views and a metadata line on every page.
- Readable error, empty and no-JavaScript states.

### Changed

- Workbench and `graph.html` use the Material Paper theme: a white navigation drawer with an indigo header, paper cards with shadows on a blue-grey background, Roboto type, and a round Send button. Theme colors, elevation and shape are tokens on `:root` in `style.css`; severity, epistemic-status and entity-type colors are unchanged (fork PR #12).
- `/epistract:view` no longer uses sift-kg/pyvis to render. Node colors and shapes come from the same `domain.yaml` display hints as the workbench; grouping defaults to Topic cluster; sources are hidden until "Show sources".

### Removed

- sift-kg viewer controls: per-type color pickers, source-document dropdown, min-support-docs slider, community checkbox list, title text color options, and sift-kg's own search/detail panel. Replaced by domain.yaml display colors, Show sources, confidence and min-connections sliders (in Filters), Group by and the Groups list, and the workbench search and detail sidebar.

### Security

- No external scripts; all graph data lives in an escaped JSON island. sift-kg's unescaped sidebar is no longer on the view path.

## [3.2.2] — 2026-04-28

**Workbench security hardening.** Closes all HIGH/MEDIUM vulnerabilities identified in the workbench example app, each proven by a failing-then-passing regression test. Contributed by Chris Davidson (PR #19) and ported as a controlled release.

### Security

- **SEC-01 / XSS** — `chat.js` wraps every dynamic `innerHTML` assignment in `DOMPurify.sanitize` (incremental render, final render); SSE error path rebuilt via DOM API + `textContent`. `graph.js` node popover fully reconstructed with `createElement`/`textContent`. `app.js` dashboard escapes all interpolations (`escapeHtml`) and sanitizes domain-supplied HTML via DOMPurify. `sources.js` escapes `displayName`.
- **SEC-02 / Path traversal** — `data_loader.py::get_document_text` and `get_document_pdf_path` enforce two-layer containment: string-level reject of `..`/`/`/`\\` plus `Path.resolve().relative_to(ingested_dir.resolve())`.
- **SEC-03 / Role injection** — `ChatMessage.role: Literal["user", "assistant"]`; Pydantic rejects `system`/`tool` payloads at deserialization before the handler runs.
- **SEC-04 / SRI missing** — `index.html` pins DOMPurify 3.4.1 + marked@18.0.2 with `integrity=sha384-…` and `crossorigin=anonymous`. DOMPurify loads first so `window.DOMPurify` is available to `chat.js`.
- **SEC-05 / CORS wildcard** — `server.py` replaces `allow_origins=["*"]` with explicit `LOCALHOST_ORIGINS` allowlist (4 localhost ports); `allow_methods` narrowed to `GET`/`POST`, `allow_headers` to `Content-Type`.

### Fixed

- `chat.js` no longer overwrites a real SSE error message with the generic "No response received" fallback when the `done` event arrives after an `error` event (`errorShown` flag).
- `tests/test_unit.py::test_chat_request_model_field` updated to compare via `model_dump()` instead of dict equality (consumer of the new `ChatMessage` schema).

### Added

- `tests/test_workbench_security.py` — 5 regression tests (one per SEC-0x).
- `tests/conftest.py` — shared `client` TestClient fixture.

### Known issues

- Citation links rendered by `chat.js` `linkifyCitations` use inline `onclick` handlers, which DOMPurify strips during sanitization. Citations now render as inert `<a>` tags. Tracked as a follow-up — replace inline handlers with delegated `addEventListener` at the document level (mirrors the `.source-link` pattern in `index.html`).

## [3.2.1] — 2026-04-26

**S8 FDA Product Labels showcase corpus.** Ships the first bundled-corpus showcase for the fda-product-labels domain: a 7-document FDA SPL corpus (Ozempic NDA209637, Wegovy NDA215256, Mounjaro NDA215866, Humira BLA125057, Gleevec NDA021588, Lipitor NDA020702, Jantoven ANDA040416), the openFDA fetch script, the full pipeline output (81 nodes / 149 edges / 1,579-word narrative), 4 workbench screenshots, scenario validation doc, and public-facing showcase doc. Closes #14.

### Added

- `scripts/fetch_fda_labels.py` — openFDA SPL fetcher (stdlib urllib, zero new deps, mirrors `fetch_ct_protocols.py`)
- `tests/corpora/08_fda_labels/docs/` — 7 SPL label text files (each ≤ 80 KB)
- `tests/corpora/08_fda_labels/output/` — full pipeline artifacts (graph_data.json, communities.json, claims_layer.json, epistemic_narrative.md, graph.html, extract_run.json, per-doc extractions)
- `tests/scenarios/scenario-08-fda-product-labels.md` — scenario validation doc (9-section, V3.2 results)
- `docs/SHOWCASE-FDA.md` — public-facing showcase doc
- `docs/screenshots/fda-labels-{01-dashboard,02-chat-welcome,03-graph,04-chat-epistemic}.png` — 4 workbench screenshots

### Fixed

- `domains/fda-product-labels/epistemic.py` — gap analysis loop iterated over string characters instead of entity-type dict keys (produced hundreds of spurious gap entries)
- `scripts/extract_corpus.py` — added `_normalize_relation()` to handle `source`/`target` field name variants that were silently dropped by deduplication

### Changed

- `README.md` — fda-product-labels row updated to show S8 as its first validated scenario; showcase block expanded with graph/narrative/screenshot links
- `.claude-plugin/plugin.json` — version bump 3.2.0 → 3.2.1

---

## [3.2.0] — 2026-04-25

**Workbench enhancements + fourth pre-built domain (FDA Product Labels).** Adds the fda-product-labels domain (17 entity types, 16 relation types, four-level FDA epistemology classifier), a runtime LLM model selector with live OpenRouter model browsing and health filtering, interactive node pinning with Fit View / Reset Pins toolbar, and graph visual legibility improvements (degree-based node sizing, halo labels, zoom-aware scaling). Also adds the `community_label_anchors` schema field for domain-aware community labeling.

### Highlights

- **Phase 4 — Domain-aware community labeling.** New `community_label_anchors: list[str]` field in `domain.yaml` lets domains specify which entity types should drive community labels. `core/label_communities.py` gains `_anchor_label()` (priority-ordered lookup with truncation, slash format for 2 matches, "+N more" for 3+) and `_load_domain_anchors()` (reads anchors via `resolve_domain()`; backward compatible — empty list when missing). `core/domain_wizard.py:generate_workbench_template` and `generate_domain_package` accept `community_label_anchors` parameter; `--schema` bypass reads optional field from schema JSON.
- **Phase 5-01 — Graph visual legibility.** Node font upgraded to 12px with rgba semi-transparent halo (`rgba(255,255,255,0.85)`) for legibility against background. Zoom-aware label scaling (`scaling.label.{enabled, min, max, maxVisible, drawThreshold}`) auto-hides labels at far zoom-out. Degree-based node sizing (8–24px range): hub nodes render larger, isolated nodes smaller. Multiselect, dragNodes, navigationButtons made explicit on the interaction block.
- **Phase 5-02 — Interactive node pinning.** Drag-to-pin: dragging a node fixes it in place with a 2px accent (`#4a6cf7`) border. Group drag: dragging a pinned node moves connected neighbors with it. Fit View and Reset Pins toolbar buttons in the graph control bar. Window-resize handler closes stale popovers.
- **Phase 5-03 — Runtime LLM model selector.** New `<select id="model-select">` dropdown in chat input. `GET /api/models` endpoint returns provider-specific model list. `ChatRequest.model: str | None` field allows per-request override. `_resolve_api_config(model_override=...)` threads override into Anthropic and OpenRouter branches (Foundry intentionally ignored). LocalStorage persists user selection. Foundry/no-key environments hide the dropdown. **Fixes the long-standing OpenRouter 4096-token-cap 402 error** — users can now pick a smaller-context model when credits are tight.
- **Phase 5-04 — Live OpenRouter model browser.** TTL-cached (1 hour) live fetch from `openrouter.ai/api/v1/models`. Filtering: drops non-text output_modalities, OpenRouter-router prefixes, negative pricing, expired entries. CATEGORY_MAP groups models by provider prefix into `<optgroup>` rows (anthropic, openai, google, meta-llama, mistralai, qwen, deepseek, etc.). Cost-sort toggle button (persistent via localStorage) flips between grouped-by-provider and flat-sorted-by-input-cost. Graceful network-error fallback to PROVIDER_MODELS["openrouter"].
- **Phase 5-05 — Health-filtered model dropdown.** `_check_or_model_health()` parallel-probes OpenRouter `/endpoints` API for every candidate model before caching. Models with empty endpoints (broken at provider) are excluded entirely. Models with low uptime have free variants excluded (paid tier only retained). Fail-open at per-task and gather levels — health check failures don't break the dropdown.
- **SSE error surface fix.** `_stream_openai_compat` now detects error events embedded in OpenRouter's SSE stream (rate limits, context overflows, unavailable models) and surfaces them through the chat panel instead of silently dropping the response. `chat.js` shows actionable fallback message when stream ends empty.
- **Fourth pre-built domain — fda-product-labels.** 17 entity types (DRUG_PRODUCT, ACTIVE_INGREDIENT, INACTIVE_INGREDIENT, MANUFACTURER, INDICATION, CONTRAINDICATION, ADVERSE_REACTION, WARNING, DRUG_INTERACTION, DOSAGE_REGIMEN, PATIENT_POPULATION, MECHANISM_OF_ACTION, PHARMACOKINETIC_PROPERTY, CLINICAL_STUDY, PHARMACOLOGIC_CLASS, REGULATORY_IDENTIFIER, LABTEST). 16 relation types covering product↔ingredient, product↔manufacturer, product↔indication/contraindication/warning/interaction, dosing, populations, mechanisms, pharmacokinetics, classes, and identifiers. SKILL.md aligned to FDA SPL JSON document structure. **Four-level FDA epistemology classifier** in `epistemic.py`: established (boxed warnings, contraindications, RCT evidence) / reported (adverse reactions, post-marketing surveillance) / theoretical (mechanism, pharmacology, in vitro) / asserted (default). Populates v3-standard `epistemic_status` field on every relation alongside the FDA tier — same parity pattern as clinicaltrials.
- **Hand-tailored FDA-analyst persona.** Senior FDA regulatory intelligence analyst voice with depth in pharmacovigilance, formulary analysis, drug-interaction screening, SPL document review. Citation discipline scoped to FDA-canonical identifiers (SPL set ID, NDA/ANDA number, NDC, RxCUI, UNII). Vocabulary standards for INN/brand naming, EPC/MoA/CS/PE pharmacologic class designations, MedDRA-style verbatim adverse-event wording. Drives both reactive workbench chat AND proactive `/epistract:epistemic` narrator (single source of truth pattern).
- **18 new unit tests** — model selector backward-compat + override, OpenRouter live/fallback/filter/grouping, health-check pruning, fda-product-labels domain shape, community_label_anchors anchor matching, wizard schema-bypass anchor read, narrator parity. **126 passed, 4 skipped** total (no regressions against v3.1.0 baseline).

### Added

- `domains/fda-product-labels/` — fourth pre-built domain package (`domain.yaml`, `SKILL.md`, `epistemic.py`, `__init__.py`, `workbench/template.yaml`, `references/entity-types.md`, `references/relation-types.md`)
- `examples/workbench/server.py` — `GET /api/models`, `_fetch_or_models()`, `_filter_and_group_or_models()`, `_check_or_model_health()`
- `examples/workbench/api_chat.py` — `PROVIDER_MODELS`, `ChatRequest.model`, `_resolve_api_config(model_override=...)`, SSE error surface
- `examples/workbench/static/index.html` — graph toolbar row, model select element
- `examples/workbench/static/style.css` — toolbar, pin accent, model select styles
- `examples/workbench/static/graph.js` — label halo, zoom scaling, degree sizing, pin Set, dragEnd handler, group drag, toolbar handlers, resize handler
- `examples/workbench/static/chat.js` — `loadModelSelector()`, model send, localStorage, SSE error display
- `core/label_communities.py` — `_anchor_label()`, `_load_domain_anchors()`, dispatch via anchor path with backward-compat fallback
- `core/domain_wizard.py` — `community_label_anchors` parameter on `generate_workbench_template` + `generate_domain_package`; `--schema` bypass reads optional field
- 18 new unit tests in `tests/test_unit.py`

### Changed

- `.claude-plugin/plugin.json` — version `3.1.0` → `3.2.0`; description names all four pre-built domains plus the workbench enhancement headline; keywords gain `fda`, `spl`, `pharmacovigilance`, `drug-labels`
- `README.md` — Pre-built Domains table gains fda-product-labels row (17 / 16); Showcases & visual artifacts gains a brief fda-product-labels entry pointing at the domain package and persona

### Attribution

- Phase 4, Phase 5-01..05, fda-product-labels domain extraction prompt + epistemic.py + four-level FDA classifier authored by Chris Davidson (`Christopher.Davidson@gmail.com`) originally as PR #12. Ported and merged in this release. Hand-tailored FDA-analyst persona authored by Umesh Bhatt + Claude as a v3.1-spec follow-up to Chris's domain shell.

### Migration

- Existing domains continue to work byte-identically. The new `community_label_anchors` field is optional — domains without it use the existing `_generate_label()` path (top-N entities) unchanged.
- Workbench frontend changes are additive — graph and chat both render correctly without the new toolbar / model selector if the corresponding env or API isn't present.
- No breaking changes.

---

## [3.1.0] — 2026-04-23

**Clinical Trials domain + external API enrichment + usage guards.** Adds a third pre-built domain (`clinicaltrials`) alongside drug-discovery and contracts, plus post-build enrichment against ClinicalTrials.gov v2 + PubChem PUG REST via `--enrich`. Hardens all 12 `/epistract:*` commands with Usage Guard blocks. Ships on top of v3.0.0's narrator + persona framework — the clinicaltrials domain gets a full analyst persona that drives both the workbench chat (reactive) and the automatic narrator (proactive).

### Highlights

- **Phase 21 — Clinical Trials domain package.** `domains/clinicaltrials/` ships with `domain.yaml` (12 entity types: Trial, Intervention, Condition, Sponsor, Investigator, Outcome, Compound, Biomarker, Cohort, Population, TrialPhase, Site; 10 relation types), `SKILL.md` (NCT ID capture, Phase classification, intervention/condition disambiguation, arm/cohort structure; 529 lines), and `epistemic.py` (phase-based evidence grading: Phase III → high, Phase II → medium, Phase I/observational → low; blinding/enrollment signals).
- **External enrichment via `--enrich`.** `/epistract:ingest --domain clinicaltrials --enrich` runs `domains/clinicaltrials/enrich.py` after graph build. Trial nodes matching `NCT\d{8}` get `ct_overall_status`, `ct_phase`, `ct_enrollment`, `ct_start_date`, `ct_completion_date`, `ct_brief_title`. Compound nodes get `pubchem_cid`, `molecular_formula`, `molecular_weight`, `canonical_smiles`, `inchi`. Per-entity-type hit rates recorded in `<output_dir>/extractions/_enrichment_report.json`. Non-blocking by design: 404/429/timeout/connection errors log counts but never abort the pipeline.
- **Usage Guard blocks on all 12 commands.** Every `/epistract:*` command now shows a formatted usage summary when invoked without required args or with `--help`. 9 commands use the guard-and-stop pattern; 3 orientation-summary variants (view, setup, domain) for commands with no required args.
- **Three pre-built domains, one persona pattern.** The clinicaltrials domain ships with a `workbench/template.yaml` that carries a senior clinical-trials analyst persona — Phase III emphasis, NCT ID citations, enrollment-size reasoning, stratification by randomization/blinding. Same single-source-of-truth as v3.0: powers both reactive chat and proactive narrator.

### Added

- `domains/clinicaltrials/` — complete domain package (`domain.yaml`, `SKILL.md`, `epistemic.py`, `enrich.py`, `workbench/template.yaml`)
- `core/domain_resolver.py` — `clinicaltrial` / `clinical_trials` aliases
- `tests/fixtures/clinicaltrials/` — CT.gov v2 + PubChem mock responses, 404 shape fixture, sample CT protocol text
- `tests/test_unit.py` — 12 CTDM tests (CTDM-01 through CTDM-06) covering domain YAML shape, resolver registration, SKILL.md directives, epistemic module dispatch, CT.gov/PubChem mock enrichment, 404-handling, non-blocking contract, and `_enrichment_report.json` schema
- `commands/ingest.md` — `--enrich` flag + Step 5.5 (Enrich Knowledge Graph) invoking `domains/clinicaltrials/enrich.py` with rate-limit notes
- All 12 `commands/*.md` — `## Usage Guard` section (guard-and-stop for required args; orientation-summary for the 3 arg-free commands)
- `docs/ADDING-DOMAINS.md` — new "Domain Enrichment (Optional)" section documenting the `enrich_graph()` contract, when to use enrichment, the `_enrichment_report.json` schema, and how to wire a new domain into Step 5.5

### Changed

- `.claude-plugin/plugin.json` — version `3.0.0` → `3.1.0`; description names all three pre-built domains; keywords gain `clinical-trials`, `clinicaltrials`, `pubchem`

### Attribution

- Phase 21 implementation (clinicaltrials domain + enrichment + usage guards) authored by Chris Davidson (<Christopher.Davidson@gmail.com>) originally as PR #8. Ported onto v3.0.0 main in this release via a controlled port that preserves his authorship on the new commit while reconciling with v3.0's persona + narrator + documentation-restructure changes.

### Migration

- Existing domains continue to work byte-identically. The `--enrich` flag is opt-in and only activates for the `clinicaltrials` domain.
- No breaking changes.

---

## [3.0.0] — 2026-04-23

**Graph Fidelity & Honest Limits.** Closes nine FIDL requirements (FIDL-01..09) across Phases 12–20 that hardened the pipeline from ingest through epistemic narrative. Every capacity number in `docs/PIPELINE-CAPACITY.md` is grep-verifiable in source or measured against the codebase. No aspirational claims. On top of the v2.1 reliability work, v3 adds domain-aware metadata propagation, per-domain validators, a wizard/CLI ergonomics pass, and — new in this release — an automatic LLM analyst narrator that writes `epistemic_narrative.md` on every `/epistract:epistemic` run, grounded in the per-domain persona that doubles as the workbench chat system prompt.

### Highlights

- **FIDL-03 — Sentence-aware chunk overlap.** Chunk boundaries emit `chonkie.SentenceChunker` overlap — last 3 sentences of previous chunk, capped at 1,500 chars, preserved at every split point. Each chunk JSON records `overlap_prev_chars`, `overlap_next_chars`, `is_overlap_region`. Recovers cross-chunk entities and relations that the pre-v3 hard 10,000-char boundary dropped. `chonkie` is now a required runtime dep (ARM64 / x86 parity — replaces earlier `blingfire` plan).
- **FIDL-04 — Format discovery parity.** `core/ingest_documents.discover_corpus` delegates to `sift_kg.ingest.reader` — no hardcoded allowlist. Runtime-resolved: 29 text-class extensions (37 with `--ocr`), `.zip` excluded for provenance, loud `ImportError` when `sift_kg.ingest.reader` is missing.
- **FIDL-05 — Wizard sample window beyond 8KB.** Pass-1 schema discovery now sees beyond the first 8KB of each sample document. Multi-excerpt strategy for documents > 12K chars: head (first 4K) + middle (4K centered on midpoint) + tail (last 4K), joined with explicit `[EXCERPT N/3]` markers. Documents ≤ 12K pass through as full text. Measured cost: ~2,631 input tokens per Pass-1 call.
- **FIDL-06 — Domain awareness in downstream consumers.** `graph_data.json metadata.domain` is the new source of truth. `/epistract:dashboard` auto-detects domain; workbench chat system prompt loads per-domain `analysis_patterns`; `graph.html` gets domain-aware title + entity colors from `workbench/template.yaml`. Precedence: explicit `--domain` flag > metadata > hardcoded default. Legacy graphs fall back cleanly with a one-shot stderr warning.
- **FIDL-07 — Per-domain epistemic & validator extensibility.** Domains can ship `CUSTOM_RULES: list[callable]` in `epistemic.py`; merged into `claims_layer.super_domain.custom_findings` by rule name. `core/domain_resolver.get_validation_dir(domain)` discovers `domains/<name>/validation/run_validation.py`; `cmd_build` auto-invokes and writes `validation_report.json`. Failure isolation: one failing rule or validator records `{status: error}` but does NOT abort the pipeline. Structural-biology doctype: drug-discovery `infer_doc_type` recognizes PDB-prefixed IDs + X-ray/cryo-EM signals; high-confidence (≥0.9) structural claims short-circuit to `asserted`.
- **FIDL-08 — Wizard & CLI ergonomics.** Safe slugification (NFKD → ASCII) handles `Q&A Analysis (v2)` → `q-a-analysis-v2`. Wizard auto-emits `domains/<slug>/workbench/template.yaml` with deterministic palette entity colors + Pydantic-validated analysis_patterns. `--domain` accepts path: `run_sift build --domain /path/to/domain.yaml` infers the name when inside `domains/`. `--schema <file.json>` bypass flag generates a complete domain package in one shot, LLM-free.
- **FIDL-09 — Pipeline Capacity & Limits (now `docs/PIPELINE-CAPACITY.md`).** Every capacity number grep-verifiable or measured against the codebase.
- **Automatic analyst narrator (`epistemic_narrative.md`).** After the rule engine writes `claims_layer.json`, `core.label_epistemic` calls an LLM with the domain `persona` (from `domains/<name>/workbench/template.yaml`) and writes a structured analyst briefing. The same persona drives both the workbench chat (reactive) and the narrator (proactive) — single source of truth. Opt out with `--no-narrate`. Non-blocking on API error: `claims_layer.json` is authoritative.
- **Shared LLM client** (`core/llm_client.py`). Synchronous provider-auto-detection client mirroring workbench priority: Azure Foundry → Anthropic → OpenRouter. Reusable from any core-layer script.
- **V3 S06 rebuild (GLP-1 Competitive Intelligence).** 34-document corpus rebuilt end-to-end with Sonnet 4.6 via OpenRouter: 278 nodes (+44% vs V2), 855 edges (+38%), 10 communities, 61 prophetic claims (+307%), 33 contested claims (+560%), `metadata.domain` populated, `validation_report.json` emitted, `epistemic_narrative.md` produced. Full comparison: `docs/SHOWCASE-GLP1.md`.
- **Documentation reorganization.** README rewritten as a first-visitor story focused on V3 as the final product. Detailed content extracted to `docs/ARCHITECTURE.md`, `docs/WORKBENCH.md`, `docs/COMMANDS.md`, `docs/PIPELINE-CAPACITY.md`, `docs/SHOWCASE-GLP1.md`. Stale intermediate artifacts moved to `archive/` (gitignored).

### Added

- `core/llm_client.py` — provider-auto-detection synchronous LLM client.
- `core/label_epistemic.py` — narrator step: `_load_domain_persona`, `_summarize_graph_for_narrator`, `narrate_claims_layer`. `--no-narrate` CLI flag.
- `scripts/extract_corpus.py` — direct-call OpenRouter extraction script with resume-safe skip-if-exists and per-doc cost/token tracking.
- `scripts/s06_v2_v3_delta.py` — V2/V3 delta capture.
- `docs/ARCHITECTURE.md`, `docs/WORKBENCH.md`, `docs/COMMANDS.md`, `docs/PIPELINE-CAPACITY.md`, `docs/SHOWCASE-GLP1.md` — new user-facing documentation.
- `domains/drug-discovery/workbench/template.yaml` — upgraded persona with epistemic-status vocabulary, citation discipline, vocabulary standards (INN/HGNC/MeSH/MedDRA).
- `domains/drug-discovery/validation/run_validation.py` — molecular validation entry point (RDKit-gated; gracefully skipped when RDKit not installed).
- **Requirements**: FIDL-03..FIDL-09 registered and completed in `.planning/REQUIREMENTS.md`.
- **Tests**: UT-031..UT-057 + FT-012..FT-020 + additional narrator tests (`test_ut055_narrator_load_domain_persona`, `test_ut056_narrator_summarize_graph_shape`, `test_ut057_narrator_non_blocking_on_missing_credentials`).

### Changed

- `README.md` — rewritten as a first-visitor story. Previous version preserved in `archive/README-pre-v3-2026-04-23.md`.
- `core/label_epistemic.py:analyze_epistemic` — accepts `narrate=True` parameter; writes `epistemic_narrative.md` alongside `claims_layer.json` when persona and credentials are available.
- `core/domain_wizard.py:generate_workbench_template` — new `persona_override` param; emits an analyst-shaped multi-paragraph persona template by default (was one sentence).
- `core/domain_wizard.py:generate_domain_package` — new `persona` param threaded through; `--schema` bypass reads optional `persona` field from schema JSON.
- `core/run_sift.py:cmd_view` — fills only the first of pyvis's two empty `<h1></h1>` tags and strips the second, so `graph.html` renders the title exactly once (was duplicated).
- `commands/domain.md` — new persona-elicitation step in the interactive wizard flow; `persona` documented in `--schema` bypass section.
- `commands/epistemic.md` — documents `--no-narrate` flag, `epistemic_narrative.md` artifact, narrator credential priority, single-source-of-truth persona mechanism.

### Deprecations

- `blingfire` removed from plan. `chonkie` is the sentence chunker going forward (ARM64 / x86 parity).

### Migration

- **Rebuild your graphs to get v3 metadata.** Graphs built before v3 lack `metadata.domain` — they still work but downstream consumers fall back to explicit `--domain` flag or default.
- **No migration script shipped** — a quick rebuild is faster than writing one.
- Existing domains without `CUSTOM_RULES`, `validation/` directory, or `workbench/template.yaml` continue to work byte-identically. All v3 additions are backward-compatible.

---

## [2.1.0] — 2026-04-17

**Graph Fidelity & Extraction Pipeline Reliability.** Two reliability phases close silent-data-loss holes in the extraction pipeline. The extraction-load rate jumped from ~70% (axmp-compliance 23-doc run lost 7 documents) to ≥95%, proven end-to-end on a 24-file Bug-4 reproducer (FT-009 at 100%). The `/epistract:domain` wizard now reads PDFs correctly instead of leaking binary headers into generated schemas.

### Highlights

- **Phase 12 — FIDL-01 wizard PDF binary read fix.** `/epistract:domain` was reading PDFs as raw binary (null bytes and `%PDF-` headers leaked into the proposed schema). Wizard now routes sample reads through `sift_kg.ingest.reader.read_document` — the same reader the main ingest pipeline uses — so generated entity type names are derived from real document content.
- **Phase 13 — FIDL-02a/b/c extraction pipeline reliability.** Three-layer defense against silent extraction drop:
  - **Write-time Pydantic validation** in `core/build_extraction.py` catches malformed extractions immediately (missing `document_id`, invalid `entity_type`, schema drift). Honest `--model` / `--cost` / `EPISTRACT_MODEL` provenance threading replaces the hardcoded `claude-opus-4-6` / `0.0` fabrication.
  - **`core/normalize_extractions.py`** — new post-extraction Step 3.5 that renames variant filenames (`*_raw.json`, `*-extraction.json`), infers missing `document_id` from filename stems, dedupes same-doc variants via composite score, coerces schema drift (numeric-string confidence, missing context/evidence/attributes), and emits `_normalization_report.json`. CLI entry-point with `--fail-threshold` (default 0.95) aborts the pipeline before graph build if recovery rate is too low.
  - **`agents/extractor.md` Required-Fields enforcement** — explicit REQUIRED top-level fields block (`document_id`, `entities`, `relations`), stdin fallback for large payloads, ban on direct `Write` tool use, and a `/scripts/`→`/core/` path bug fix.
- **End-to-end acceptance loop** — `tests/test_e2e.py` adds FT-009 (24-file Bug-4 reproducer achieves ≥95% load rate through normalize → build) and FT-010 (10-file below-threshold fixture aborts with exit 1 before `graph_data.json` is written).

### Added

- `core/normalize_extractions.py` — post-extraction normalization module (334 lines) + CLI entry-point with `--fail-threshold` abort gate
- `tests/test_e2e.py` — new end-to-end regression module (FT-009 + FT-010)
- `tests/fixtures/normalization/` — 24-file Bug-4 reproducer corpus (23 logical docs post-dedupe) with variant filenames, missing `document_id` fields, schema drift, and orphan extractions
- `tests/fixtures/normalization_below_threshold/` — 10-file corpus (2 survivors + 8 unrecoverable) for the `--fail-threshold` abort gate
- `tests/fixtures/wizard/` — sample PDFs for the FIDL-01 wizard regression test
- **Requirements**: FIDL-01 (wizard PDF binary read), FIDL-02a (extractor contract enforcement), FIDL-02b (post-extraction normalization + abort gate), FIDL-02c (honest extraction provenance + write-time validation) registered in `.planning/REQUIREMENTS.md`
- **Test IDs**: UT-017..UT-030 (14 new unit tests) + FT-009, FT-010 (2 e2e tests) registered in `tests/TEST_REQUIREMENTS.md`

### Changed

- `core/build_extraction.py` — validates against `sift_kg.extract.models.DocumentExtraction` at write time; accepts `--model` / `--cost` CLI flags and `EPISTRACT_MODEL` environment variable; substitutes sift-kg defaults (`cost_usd=0.0`, `model_used=""`) on disk so direct `write → build` invocation remains sift-kg-loadable without a prior normalize pass
- `core/normalize_extractions.py` — internal `_normalize_fields` helper extended to coerce numeric-string confidence values, missing `context` / `evidence`, and missing `attributes` dictionaries
- `agents/extractor.md` — Required-Fields block enforces the JSON contract; stdin-pipe fallback for payloads exceeding Bash argv limits; corrects the `/scripts/` → `/core/` path reference
- `commands/ingest.md` — inserts Step 3.5 (normalization) between extraction dispatch and `run_sift.py build`; documents the `--fail-threshold` pass-rate gate; exports `EPISTRACT_MODEL` and threads `--model` / `--cost` into `build_extraction.py` invocations
- `core/chunk_document.py` — wizard sample reader routes through sift-kg reader (no more raw binary)
- `scripts/setup.sh` — updated for Python 3.13+ wheel support (`rdkit-pypi` → `rdkit`)
- `examples/workbench` — bypass SOCKS proxy in `httpx.AsyncClient` for enterprise proxy environments

### Fixed

- Wizard extracting null bytes and PDF/EPUB binary headers as candidate entity type names (FIDL-01)
- `sift_kg.graph.builder.load_extractions` silently dropping files with inconsistent filenames or missing `document_id` (FIDL-02a/b)
- Hardcoded `claude-opus-4-6` / `0.0` provenance in written extractions (FIDL-02c)
- UT-013 regression introduced mid-phase by the honest-null-on-disk contract; resolved by symmetric sift-kg default substitution in `write_extraction` so direct `write → build` calls remain sift-kg-loadable

### Test suite

- `.venv/bin/python -m pytest tests/test_unit.py tests/test_e2e.py` — **47 passed + 4 skipped** (RDKit/Biopython optional deps)
- Phase 13 acceptance (FT-009): 24-file reproducer flows through normalize → build at 100% pass_rate with non-empty `graph_data.json`
- Phase 13 abort gate (FT-010): below-threshold fixture aborts with exit 1, no `graph_data.json` created

---

## [2.0.0] — 2026-04-14

**Cross-Domain Knowledge Graph Framework.** The v1.0 drug-discovery / contracts codebase is refactored into a domain-agnostic framework. Plug in a domain schema (YAML + extraction prompt + epistemic rules), point at a document corpus, and get a structured two-layer knowledge graph. Ships with pre-built drug-discovery and contracts domain packages, a domain creation wizard, and an interactive web workbench.

### Highlights

- **Cross-domain framework** — `core/` (domain-agnostic pipeline) + `domains/` (pluggable packages) + `examples/` (consumer applications). The same pipeline runs against any schema. Adding a new domain requires only `domain.yaml` + `SKILL.md` + `epistemic.py`; no pipeline code changes.
- **Two pre-built domains ship with the framework:**
  - **drug-discovery** — 17 entity types, 30 relation types, molecular validation via RDKit/Biopython, patent-vs-paper epistemic classification (asserted / hypothesized / prophetic / contradictory)
  - **contracts** — 11 entity types, 11 relation types, cross-contract conflict detection, obligation gap scoring, risk indicators (ships as schema scaffold without bundled corpus — bring your own)
- **`/epistract:domain` wizard** — auto-generates a starter domain package from a sample corpus. Analyzes documents, proposes entity/relation types, writes `domain.yaml` + `SKILL.md` + `epistemic.py`.
- **`/epistract:acquire` PubMed pipeline** — search PubMed and download articles into a local corpus in one command (Chris Davidson, PR #2).
- **Interactive workbench** — FastAPI-backed three-panel UI (dashboard / chat / graph) with domain-aware persona, entity-type filter pills, natural-language chat grounded to source documents, domain-specific starter questions, and a force-directed graph canvas.
- **Three-provider LLM chat panel** — workbench auto-detects credentials for **Azure AI Foundry** (standard resource endpoint OR custom gateway URL), **Anthropic direct**, or **OpenRouter**. Supports both `AZURE_FOUNDRY_*` and `ANTHROPIC_FOUNDRY_*` env var naming conventions for enterprise environments.
- **End-to-end V2 validation** — 6 drug-discovery scenarios re-validated through `/epistract:*` slash commands. Aggregate: **111 documents → 867 nodes, 2,592 links, 39 communities** (+10.7% nodes, +16.2% edges, +18.2% communities vs V1 baseline). All 6 pass regression at the ≥80% threshold. See `docs/showcases/drug-discovery-v2.md`.
- **Pinned regression suite** — `tests/regression/run_regression.py` compares each scenario's output against pinned V1 baselines and reports PASS/FAIL per scenario. V2 baselines written on demand via `--update-baselines`.
- **uv-first install with project-local `.venv`** — `scripts/setup.sh` requires uv, auto-creates `.venv` via `uv venv`, installs `sift-kg` into the project venv (not system Python), and fails loud with remediation steps if PyPI is unreachable.

### Added

- `core/` — domain-agnostic pipeline engine
  - `domain_resolver.py` — loads domain packages by name or alias from `domains/`
  - `run_sift.py` — wraps sift-kg build/view/export/search/info as the plugin's Python entry point
  - `build_extraction.py` — writes extraction JSON in the `DocumentExtraction` interchange format
  - `label_epistemic.py` — dispatches epistemic analysis to the domain-specific module
  - `label_communities.py` — Louvain detection + auto-labeling
  - `domain_wizard.py` — drives `/epistract:domain` package generation
- `domains/` — pluggable domain packages
  - `drug-discovery/` — full package with 17 entity types, 30 relation types, RDKit/Biopython validation, and domain-specific epistemic rules including patent/prophetic detection
  - `contracts/` — schema scaffold (no bundled corpus) with 11 entity types, 11 relation types, and cross-contract conflict/gap/risk rules
- `examples/workbench/` — FastAPI workbench with chat (SSE streaming via Anthropic or OpenRouter), force-directed graph (vis.js), entity-type filters, source-document drill-through, and domain-configurable persona
- `examples/telegram_bot/` — Telegram chat interface backed by the same graph data
- `commands/` — 12 Claude Code slash commands: `setup`, `ingest`, `build`, `view`, `validate`, `epistemic`, `query`, `export`, `domain`, `dashboard`, `ask`, `acquire`
- `agents/` — 3 Claude Code subagents: `extractor`, `acquirer`, `validator`
- `tests/scenarios/scenario-0[1-6]-*-v2.md` — 6 per-scenario V2 reports with V1→V2 delta tables, entity/relation breakdowns, community analysis, and domain insights
- `tests/scenarios/screenshots/scenario-0[1-6]-graph-v2.png` — rendered force-directed graphs for each drug-discovery scenario
- `tests/regression/run_regression.py` + `tests/regression/compare_baselines.py` — pinned regression suite with threshold-based comparison
- `tests/baselines/v1/*.json` — 7 pinned V1 baselines (6 drug-discovery + 1 contracts) with scenario counts and epistemic thresholds
- `docs/showcases/drug-discovery-v2.md` — master V2 showcase with 6-scenario gallery, aggregate metrics, and 7 framework-level insights
- `docs/showcases/contracts.md` — cross-domain demonstration page (shared-vs-domain-specific separation table)
- `docs/screenshots/workbench-0[1-4]-*.png` — 4 live workbench screenshots (dashboard, chat welcome, graph view, epistemic query)
- `docs/diagrams/` — architecture SVGs (Mermaid-rendered)
- `docs/ADDING-DOMAINS.md` — wizard-first guide to creating new domain packages
- **Azure AI Foundry** as a third LLM provider for the workbench chat panel. Auto-detected when `AZURE_FOUNDRY_API_KEY` (or alias `ANTHROPIC_FOUNDRY_API_KEY`) is set. Supports two endpoint patterns:
  - **Standard Azure hostname** via `AZURE_FOUNDRY_RESOURCE` → `https://<resource>.services.ai.azure.com/anthropic/v1/messages`
  - **Custom gateway** via `AZURE_FOUNDRY_BASE_URL` (or alias `ANTHROPIC_FOUNDRY_BASE_URL`) for enterprise deployments behind API management, VNet-integrated private endpoints, or reverse proxies on non-standard hostnames. `/v1/messages` is auto-appended if missing.
  - Optional `AZURE_FOUNDRY_DEPLOYMENT` (or alias `ANTHROPIC_FOUNDRY_DEPLOYMENT`) — deployment/model name, defaults to `claude-sonnet-4-6`.
  - Accepts both `AZURE_FOUNDRY_*` and `ANTHROPIC_FOUNDRY_*` env var prefixes for environments that standardize naming around the provider rather than the cloud.
  - Reuses the native Anthropic streaming path (`_stream_anthropic()`) — zero new code paths, same SSE protocol. Foundry's Anthropic-compatible endpoint uses identical headers (`x-api-key`, `anthropic-version`) and request/response shapes.
- `_ensure_messages_suffix()` helper in `api_chat.py` — normalizes Foundry base URLs so `.../anthropic`, `.../anthropic/v1`, and `.../anthropic/v1/messages` all resolve to the canonical form.
- `/api/health` now reports `llm_provider` field (`azure-foundry` | `azure-foundry-custom` | `anthropic` | `openrouter` | `null`) for ops visibility.

### Changed

- **README rewritten** — framework-first pitch, three quick-start paths (pre-built domain / PubMed acquire / custom domain wizard), V2 showcase gallery, slash-command map split between full-pipeline and single-stage commands, interactive workbench section with 4 live screenshots
- **`/epistract:ingest` is the full pipeline** — reads → chunks → extracts → validates → builds graph → generates viewer in one command. Do **not** also invoke `/epistract:build` or `/epistract:view` afterward; they are only for re-running individual stages on existing output.
- **`/epistract:epistemic` is a separate command** — runs after ingest, reads `graph_data.json`, writes `claims_layer.json`. Produces contradictions, hypotheses, and (for drug-discovery patent corpora) prophetic claims.
- **Per-document parallel extraction** — one `epistract:extractor` subagent per document instead of shared-context batches. Cleaner context isolation, higher per-doc entity yield, 111 parallel subagents validated across 6 scenarios with zero failures.
- **Regression runner transition support** — `tests/regression/run_regression.py` prefers `output-v2/` when present and falls back to `output/`, allowing V1 baselines to remain pinned while V2 validation runs in parallel.
- **`scripts/launch_workbench.py`** — now parses `--domain` and passes it through to `create_app()` (was previously ignored). Boot banner reads the domain title from `load_template(domain)` instead of hardcoding "Sample Contract Analysis Workbench".
- **Workbench sidebar legend** is now data-driven from `claims_layer.json` — the Severity section only shows when the current domain emits severity-tagged claims (contracts). Drug-discovery never sees it.
- **`scripts/setup.sh` rewritten** — now requires `uv` up front (errors with install instructions if missing), auto-creates project-local `.venv` via `uv venv`, resolves Python from the venv via `BASH_SOURCE`-based project root detection (works from any cwd), and no longer falls back to plain `pip` on failure. Supports `--check` mode for non-mutating verification. Warns on Python 3.14+ (untested).
- **README Installation section** — rewritten with explicit two-step plugin install flow (`/plugin marketplace add ./` + `/plugin install epistract@epistract`), project `.venv` rationale, supported Python version range (3.11–3.13), and a Troubleshooting subsection covering the four most common failure modes (SSL proxy, missing `./` prefix, wrong-env sift-kg, Python 3.14).
- **README LLM Provider section** — documents all three providers with Azure Foundry standard + custom gateway examples, both env var naming conventions, and the fail-loud behavior on missing resource/base-URL.

### Fixed

- **`examples/workbench/server.py` `/api/dashboard` returning 500 on drug-discovery** — Pydantic's `WorkbenchTemplate.dashboard` defaults to `None`; `dict.get(k, default)` doesn't honor `default` when the value is `None`. Chained `.get("title", ...)` raised AttributeError. Fixed with `template.get("dashboard") or {}`.
- **`scripts/launch_workbench.py` silently loaded the generic template regardless of `--domain`** — launcher parsed `--port` and `--host` but never extracted `--domain` from argv and never passed it to `create_app()`. Every domain ended up running the generic fallback persona, colors, and starter questions. Fixed.
- **Severity sidebar legend visually clashed with entity-type colors** — hardcoded Critical/Warning/Info dots (red/orange/blue) looked identical to entity-type dots (Disease red, Gene orange, Document blue). Fixed by default-hiding `#severity-section` and `#severity-filter` in `index.html` and revealing them via `configureSeverityVisibility()` in `app.js` only when `/api/graph/claims` returns items with a `severity` field.
- **`/epistract:dashboard` command was a static AKKA portfolio summary** — had been repurposed during a demo session and never restored to its intended workbench launcher role. Rewrote `commands/dashboard.md` as a proper generic workbench launcher that shells out to `scripts/launch_workbench.py` with domain forwarding.
- **`tests/regression/run_regression.py._resolve_output_dir` hardcoded `scenario/output/`** — blocked V2 validation runs that wrote to `scenario/output-v2/`. Fixed with a fallback list `(output-v2, output)` for drug-discovery scenarios and a parallel fallback list for the contracts scenario.
- **`scripts/setup.sh` checked wrong module name** — line 26 did `import sift` instead of `import sift_kg`, so the script always thought `sift-kg` was missing and tried to reinstall on every run. Fixed with `import sift_kg`.
- **`scripts/setup.sh` used bare `python3`** — resolved to system Python (often 3.14) rather than the project `.venv` (3.13). Packages got installed to the wrong environment, causing "sift-kg is installed but the viewer can't find it" confusion. Fixed by explicitly using `.venv/bin/python3` after `cd PROJECT_ROOT`.
- **`scripts/setup.sh` silently fell back to plain `pip` on uv failure** — on corporate networks with SSL-inspection proxies, `uv pip install sift-kg` would fail, the error was swallowed by `2>/dev/null`, and plain `pip` installed into the wrong Python environment. Fixed by removing the pip fallback entirely — the script now exits non-zero with three remediation options (SSL cert bundle, network check, Python version) so users can see the real failure.
- **README `/plugin marketplace add .` instruction failed** — Claude Code requires the `./` prefix for local paths (a bare `.` fails with "source not found"). Fixed in the README and called out in a blockquote + troubleshooting entry.
- **README didn't document Python version range or `.venv` setup** — users cloning fresh had no idea where the venv would come from or which Python versions were supported. README now says "3.11, 3.12, or 3.13 — tested primarily on 3.13" and Step 2 explains the project-local venv flow end-to-end.

### Security

- **`.claude/settings.local.json` purged from all 318+ commits via `git filter-repo`** — contained an OpenRouter API key (since disabled by the provider) and a Telegram bot token. The force-push cleared GitGuardian alerts on the feature branch.
- **AKKA confidential content scrubbed from 424 commits** — deleted `domains/contracts/workbench/dashboard.html` (real vendor portfolio with dollar amounts and person names), `tests/fixtures/sample_ingested/pcc_license_agreement.txt`, `tests/fixtures/sample_ingested/marriott_contract.txt`, and `docs/plans/2026-04-01-contract-kg-pipeline-TODO.md` via `filter-repo --invert-paths`. Replaced AKKA / Kannada / person-name strings across all remaining commits via `filter-repo --replace-text`.
- **`.gitignore` hardened** — `.claude/` (entire directory), `*.local.<ext>` patterns for private variants alongside public files, `sample-contracts/`, `sample-output/`, `sample-output-v2/`, `private-corpus/`.
- **Contracts domain ships as schema scaffold only** — no sample corpus, no pre-extracted graph data, no dashboard.html. Bring your own contracts to reproduce.

### Removed

- `domains/contracts/workbench/dashboard.html` — real vendor portfolio (purged from history)
- `tests/fixtures/sample_ingested/pcc_license_agreement.txt` — real contract text (purged from history)
- `tests/fixtures/sample_ingested/marriott_contract.txt` — real contract text (purged from history)
- `docs/plans/2026-04-01-contract-kg-pipeline-TODO.md` — planning doc with personal names and local file paths (purged from history)
- Hardcoded severity legend in `examples/workbench/static/index.html` — replaced with data-driven visibility controlled by `app.js`
- `package-lock.json`, stale 999.x backlog `.gitkeep` files
- `umesh-todo.md` — all items complete

### Migration Notes

- **V1 users:** The `commands/dashboard.md` slash command no longer returns a static contract portfolio summary. It now launches the interactive workbench. If you were relying on the old behavior, migrate to `/epistract:ask` or build a custom command.
- **Contract domain users:** `domains/contracts/` no longer ships with `dashboard.html` or sample fixtures. The schema, SKILL.md, references, and epistemic rules remain. To reproduce the workbench dashboard view, ship a private `dashboard.local.html` alongside the tracked files (now ignored by `.gitignore`'s `*.local.<ext>` rule).
- **OpenRouter users:** If you had `OPENROUTER_API_KEY` set in a previous `.claude/settings.local.json`, re-export it from `~/.zshrc` or an equivalent location — `.claude/` is now entirely gitignored.
- **Regression baselines:** V2 baselines are written on demand by `run_regression.py --update-baselines` to `tests/baselines/v2/`. The V2 baselines directory is gitignored (it's a generated artifact). V1 baselines in `tests/baselines/v1/` remain pinned for regression comparison.
- **Python version:** epistract supports 3.11–3.13. If you're on 3.14, pin the venv to 3.13 with `uv venv --python 3.13` or expect `WARN: Python 3.14.x is newer than the tested range` during setup.
- **Setup script now fails loud on corporate proxies:** if `uv pip install sift-kg` can't reach PyPI through an SSL-inspection proxy, the script exits non-zero with three remediation steps instead of silently falling through to plain `pip`. Set `SSL_CERT_FILE` or `REQUESTS_CA_BUNDLE` to your corporate CA bundle and re-run.

### Known Gaps (deferred to v2.1)

- **Structural biology documents classified as `document_type: unknown`** — the drug-discovery epistemic classifier only recognizes `paper` and `patent` signatures. Structural documents like `structural_sotorasib.txt` (S2 KRAS) and `structural_nivolumab_sequence.txt` (S4 Immuno-Oncology) appear in the claims layer with `unknown` doctype. Low severity; no misclassifications occur, only the doctype breakdown in the summary is incomplete. Tracked as Phase 12 in the roadmap.

### Credits

- **Chris Davidson** — `/epistract:acquire` PubMed acquisition pipeline (PR #2)
- **Umesh Bhatt** — framework architecture, drug-discovery + contracts domains, workbench, epistemic layer, V2 validation, release engineering

---

## [1.0.0] — 2026-04-02

Initial release. Single-domain (contracts) knowledge graph extraction pipeline for event contract analysis. Served as the proof-of-concept that became the v2.0 cross-domain framework.
