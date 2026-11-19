# Showcase — Clinical Trials GLP-1 Phase 3 Landscape

A 10-document corpus of ClinicalTrials.gov Phase 3 / pivotal trial protocols for GLP-1 receptor agonists (SURPASS, SURMOUNT, STEP, PIONEER, SUSTAIN, ACHIEVE series). Built end-to-end with the v3.1 pipeline and the new `clinicaltrials` domain on 2026-04-23. Outputs and the narrator briefing are committed under `tests/corpora/07_glp1_phase3_trials/output/`.

## Try it yourself

```bash
python scripts/launch_workbench.py tests/corpora/07_glp1_phase3_trials/output \
    --domain clinicaltrials
```

Open http://127.0.0.1:8000. Ask the chat panel:

- *"Compare the primary endpoints of SURPASS-2 vs SUSTAIN-6."*
- *"Which trials have high-evidence outcomes for `tirzepatide` vs `semaglutide` in obesity?"*
- *"What arms and cohorts does SURMOUNT-1 have, and what's the enrollment per arm?"*
- *"Are there coverage gaps — missing long-term safety data, absent confirmatory trials, incomplete CVOT integration?"*

The chat panel is grounded in the same graph + claims layer that produced the narrative below. The clinicaltrials persona commits to Phase-based evidence grading — `high_evidence` for Phase III randomized double-blind trials with ≥300 enrollment, `medium_evidence` for Phase II, `low_evidence` for Phase I / observational / single-arm / early-termination.

## Why this showcase matters

The S6 GLP-1 narrator flagged specific gaps in the **literature** corpus and recommended follow-ups:

> *"Integrate SURPASS-2 trial data: Add a clinical_trial:surpass_2 node with direct tirzepatide vs semaglutide efficacy and safety relations to close the head-to-head gap."*
>
> *"No long-term safety data for orforglipron or retatrutide: Phase 3 trial references exist but cardiovascular outcome trials (CVOT), renal safety, and oncology signals are entirely absent."*
>
> *"PIONEER oral semaglutide trial integration is incomplete."*

S7 is the answer. Same molecular targets, same companies, but instead of patents + PubMed abstracts (S6), the source is **authoritative trial protocols from ClinicalTrials.gov** — the data that settles the gaps S6 identified.

## V3.1 numbers (2026-04-23)

| Metric | V3.1 (Sonnet 4.6) |
|---|---:|
| Documents | 10 (CT.gov Phase 3 / pivotal protocols) |
| Extraction pass rate | 100% (10 / 10 Pydantic-validated, 0 silent drops) |
| Extraction cost | $0.98 |
| Extraction duration | ~13 min (sequential, Sonnet 4.6 via OpenRouter) |
| Nodes | 142 |
| Edges | 395 |
| Entity types | 11 (Trial, Intervention, Condition, Sponsor, Outcome, Compound, Biomarker, Cohort, Population, TrialPhase, DOCUMENT) |
| Communities | 8 |
| Trials captured | 10 (100% — every NCT anchored) |
| Interventions (drug arms) | 16 |
| Compounds | 2 |
| Outcomes (primary + secondary) | 65 |
| Cohorts | 13 |
| Populations | 10 |
| Biomarkers | 5 |
| Claims (relations excluding `MENTIONED_IN` provenance links) | 198 |
| `asserted` claims (v3 status) | 191 |
| `hypothesized` claims (v3 status) | 7 (`treats` claims backed only by protocol intent language) |
| `high_evidence` claims (phase-tier) | 141 (after `--enrich`) |
| `medium_evidence` claims (phase-tier) | 57 (after `--enrich`; open-label SURPASS-2 and SURMOUNT-5 are capped at medium) |
| `unclassified` claims (phase-tier) | 0 (every claim is traced to its source trial) |
| Enrichment hit rate | 10/10 trials (100%), 2/2 compounds (100%) |
| Contradictions / contested claims | 0 / 0 (no source reports a different result) |
| Mixed-tier claims | 5 (supported by both blinded and open-label trials) |
| `metadata.domain` | `clinicaltrials` |
| `epistemic_narrative.md` | 1,197 words |

### What the numbers say

**Outcome-heavy, intervention-light.** 65 Outcome nodes vs 16 Intervention nodes. CT.gov protocols are exhaustive about endpoint definitions (primary, secondary, time frames, populations) — the extractor captured this faithfully. The 6.5-to-1 outcome-to-intervention ratio is the biggest feature of the graph.

**Cohort and population stratification is richly captured.** 13 Cohort nodes + 10 Population nodes across 10 trials means the arm-level structure is visible — SURMOUNT-1's 4 active arms (5/10/15mg tirzepatide + placebo) and SURPASS-2's 4 arms (tirzepatide 5/10/15mg + semaglutide 1mg) are there. The clinicaltrials persona's arm/cohort-stratification guidance has structured data to work with.

**191 of 198 claims are `asserted`; 7 are `hypothesized`.** CT.gov protocol language is declarative ("participants will receive", "primary endpoint is measured at week 24"), so structural facts (sponsor, phase, endpoints, arms) are correctly asserted. The exception is efficacy: a protocol says a drug *will be evaluated* for a condition, not that it works. The seven `treats` claims whose every source is intent language ("semaglutide evaluated as treatment for type 2 diabetes") are labeled `hypothesized`. One `treats` claim stays asserted because one source cites prior results ("shown to have beneficial impact on blood sugar"). Earlier versions of this page reported 394 asserted relations; that count included 196 `MENTIONED_IN` provenance links, which are not claims.

**Five mixed-tier claims, because two trials are open-label.** Inside each merged claim the per-source evidence tiers are compared; earlier versions compared merged links with each other, which can never disagree. Registry masking (pulled by `--enrich` as `ct_masking`) shows SURPASS-2 (`NCT03987919`) and SURMOUNT-5 (`NCT05822830`) are open-label, and open-label trials are capped at `medium_evidence` however large they are. Claims such as `semaglutide treats obesity`, supported by double-blind STEP trials and by open-label SURMOUNT-5, are therefore `mixed_tier`: the sources agree, but their weight differs. `contested` is reserved for sources that report different results (one shows an effect, another reports none), and `contradictions` for contested claims with a `high_evidence` source on both sides. Protocols contain no results, so both are zero here.

**Phase tagging is a structural gap — resolved via `--enrich`.** Pre-enrichment, only 2 `TrialPhase` entity nodes were extracted for 10 trials (the extractor captured Phase as an attribute rather than a standalone entity). Phase-tier grading defaulted to `medium_evidence` (197) and `unclassified` (198). **After running `domains/clinicaltrials/enrich.py`**, all 10 Trial nodes now carry `ct_phase: PHASE3` from the CT.gov v2 API, plus `ct_enrollment`, `ct_overall_status`, `ct_start_date`, `ct_completion_date`, `ct_brief_title`. `_trial_phase()` reads the new attribute, flipping **177 relations to `high_evidence`** (Phase 3 + enrollment ≥300). Claims that do not touch a Trial node, such as `semaglutide treats obesity`, are now graded through the trials their source documents describe, so none remain `unclassified`.

**Compound enrichment from PubChem.** Both `Compound` nodes (semaglutide, tirzepatide) now carry `pubchem_cid`, `molecular_formula`, `molecular_weight`, `canonical_smiles`, `inchi`. No new nodes; existing nodes got richer.

## Re-extraction with the updated schema (`output-v2/`)

A fresh verification build of the corrected corpus was made with the updated domain (`evaluated_for`, `compared_with`, canonical Condition names, mid-range calibration examples). The corpus correction replaces `NCT05715307` (CREATION, an endocrinologist training study that had been fetched as "ACHIEVE-1") with the real ACHIEVE-1, `NCT05971940` (orforglipron, Phase 3, n=559). Extraction used Claude Code extractor agents (claude-opus-5-5) rather than the Sonnet 4.6 OpenRouter run behind `output/`, so differences mix schema and model effects. To keep the repository lean, only its analyst briefing is committed (`output-v2/epistemic_narrative.md`). Rebuild the rest by ingesting `tests/corpora/07_glp1_phase3_trials/docs` with `--domain clinicaltrials --enrich` into `output-v2/`.

| | `output/` | `output-v2/` |
|---|---|---|
| Claims (excluding provenance links) | 198 | 269 |
| `treats` from protocol intent | 8 | 0 (recorded as `evaluated_for`) |
| `compared_with` | n/a | 16 |
| Mentions scored 0.70–0.89 | 1% | 26% |
| Duplicate type 2 diabetes / "overweight or obesity" nodes | yes | no |
| Claims `high_evidence` / `medium_evidence` | 141 / 57 | 220 / 49 (open-label SURPASS-2 and SURMOUNT-5 capped at medium) |
| Mixed-tier / contested claims | 5 / 0 | 5 / 0 |

The `output-v2/epistemic_narrative.md` briefing was produced from the narrator's exact prompt (`_summarize_graph_for_narrator` + the clinicaltrials persona + `_NARRATOR_USER_PROMPT`), answered by a Claude Code agent because no narrator API key was configured. The narrator summary now separates claims from `MENTIONED_IN` provenance links, lists claim relation types, names the key entities with their CT.gov fields (including masking), and shows each contested claim's per-trial evidence tiers. The current briefing was regenerated after the open-label cap: it identifies SURPASS-2 and SURMOUNT-5 as open-label `medium_evidence` sources, and reads the five mixed-tier claims as blinded-versus-open-label weight differences rather than disputes. (An earlier draft of the briefing suggested this separate mixed-tier label; it has since been added.) Two slips come from the top-25 entity cut-off, not the reasoning: it questions whether semaglutide is a real comparator in SURMOUNT-5 (it is; SURMOUNT-5 is tirzepatide versus semaglutide), and it reports no PubChem record for orforglipron (CID 137319706 is attached).

## What V3.1 delivers on clinical trials that V3.0 did not

- **Dedicated clinicaltrials domain** — 12 entity types + 12 relation types (10 at release; `evaluated_for` and `compared_with` added later) purpose-built for trial protocol shape (Trials, Interventions, Conditions, Sponsors, Investigators, Outcomes, Compounds, Biomarkers, Cohorts, Populations, TrialPhases, Sites).
- **Phase-based evidence grading** — `domains/clinicaltrials/epistemic.py` grades every Trial-connected relation by trial design (Phase, enrollment, randomization, blinding). The narrator combines this *with* v3's epistemic status vocabulary so a `high_evidence + contested` claim is flagged differently than a `high_evidence + asserted` one.
- **Optional `--enrich` flag** — `/epistract:ingest --enrich` runs `domains/clinicaltrials/enrich.py` after graph build, pulling live metadata:
  - ClinicalTrials.gov v2 API → `ct_overall_status`, `ct_phase`, `ct_enrollment`, `ct_start_date`, `ct_completion_date`, `ct_brief_title`
  - PubChem PUG REST → `pubchem_cid`, `molecular_formula`, `molecular_weight`, `canonical_smiles`, `inchi`
  - Non-blocking: API failures log to `_enrichment_report.json` with per-entity-type hit rates but never abort the pipeline.
- **Clinical trials analyst persona** — shipped in `domains/clinicaltrials/workbench/template.yaml`. Same persona drives both workbench chat (reactive) and automatic narrator (proactive). Commits to NCT citation discipline, arm/cohort stratification, Phase-tier reasoning, and combining phase evidence grading with v3 epistemic status.

## Analyst briefing excerpt

From the auto-generated `epistemic_narrative.md` (full 1,197 words in `tests/corpora/07_glp1_phase3_trials/output/`). This briefing was generated before the evidence-grading fixes and quotes the old counts (394 of 395 asserted, which included provenance links); regenerate it with `/epistract:epistemic` to refresh:

> **Executive Summary**
>
> - The knowledge graph is **dominated by `asserted` claims** (394 of 395 relations), with a single unclassified relation — suggesting a highly curated corpus of trial protocols.
> - The graph is **outcome-heavy** (65 Outcome nodes across 10 trials) but **intervention-light** (16 Intervention nodes), indicating that endpoint language is well-captured while the mechanistic and compound-level detail needed for cross-trial comparability may be underrepresented.
> - **Cohort and population stratification** (13 Cohort nodes, 10 Population nodes) is present but not yet linked to divergent outcome signals in the current annotation — a critical gap for any subgroup-level efficacy or safety inference.
> - With only 2 `TrialPhase` nodes recorded against 10 trials, **phase-based evidence grading cannot be applied uniformly** across the corpus; several efficacy claims may be sourced from Phase 1/2 data and should be treated as `low_evidence` or `medium_evidence` until phase attribution is completed.
>
> **Structural tension**: the combination of outcome-heavy annotation with minimal phase tagging means that a Phase 1 signal and a Phase 3 null result for the same compound-condition pair could coexist in the graph as two `asserted` claims with no contradiction flag. This is a material risk for any analyst using the graph to support regulatory or investment decisions.
>
> **Recommended action**: Re-run ingestion with `--enrich` so `ct_phase` is pulled from the CT.gov v2 API as a node attribute. The phase-tier grader already reads this attribute — enriching will convert most `unclassified` tier assignments to `high_evidence` for Phase 3 trials.

The narrator correctly flagged the phase-tagging gap as the highest-priority structural issue and identified the outcome-to-intervention imbalance as the dominant structural feature — both real findings in the generated graph.

## Artifacts produced

- `tests/corpora/07_glp1_phase3_trials/docs/nct*.txt` — 10 trial protocol text files (fetched via `scripts/fetch_ct_protocols.py`)
- `tests/corpora/07_glp1_phase3_trials/output/graph_data.json` — knowledge graph, `metadata.domain: clinicaltrials`
- `tests/corpora/07_glp1_phase3_trials/output/communities.json` — Louvain communities
- `tests/corpora/07_glp1_phase3_trials/output/claims_layer.json` — phase-graded epistemic layer with v3 status vocabulary
- `tests/corpora/07_glp1_phase3_trials/output/epistemic_narrative.md` — clinical trials analyst briefing (new in v3.1, persona-driven)
- `tests/corpora/07_glp1_phase3_trials/output/graph.html` — static interactive viewer
- `tests/corpora/07_glp1_phase3_trials/output/extract_run.json` — per-doc extraction stats

## Cross-scenario narrative

S6 (GLP-1 Competitive Intelligence, literature) → S7 (GLP-1 Phase 3 Trials, protocols) is the intended pair. Run both workbenches side-by-side:

```bash
# Terminal 1 — S6 literature graph
python scripts/launch_workbench.py tests/corpora/06_glp1_landscape/output-v3 \
    --domain drug-discovery --port 8000

# Terminal 2 — S7 trial-protocol graph
python scripts/launch_workbench.py tests/corpora/07_glp1_phase3_trials/output \
    --domain clinicaltrials --port 8001
```

Ask the same question in both — "What's the evidence for tirzepatide in obesity?" — and compare how each domain's persona frames the answer. S6 will cite patents and PubMed abstracts, flag prophetic vs asserted, call out the SURPASS-2 gap. S7 will cite NCT IDs, grade by Phase, and surface arm-level enrollment. Together they are a competitive-intelligence brief that neither alone can produce.

## See also

- [docs/SHOWCASE-GLP1.md](SHOWCASE-GLP1.md) — the S6 drug-discovery literature showcase that motivated this one
- [tests/scenarios/scenario-07-clinicaltrials-glp1-phase3.md](../tests/scenarios/scenario-07-clinicaltrials-glp1-phase3.md) — scenario validation doc
- [docs/ADDING-DOMAINS.md §Domain Enrichment](ADDING-DOMAINS.md) — how the `--enrich` contract works if you want to wire your own domain to an external API
