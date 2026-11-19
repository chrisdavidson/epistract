# Epistemic Briefing

## Executive Summary

- **This corpus describes trial designs, not trial results.** It covers ten completed Phase 3 incretin trials across semaglutide (injectable and oral), tirzepatide and one orforglipron study (`NCT05971940`). Every claim in the graph is `asserted` and `high_evidence`, but those claims describe what each protocol says it will measure: endpoints, arms, populations and comparators. The graph holds no effect sizes, p-values or statements that an endpoint was met. Treat the uniform high grade as a grade on trial design, not as confirmed efficacy.
- **Semaglutide dominates the corpus.** Six of the ten trials study semaglutide and are Novo Nordisk-sponsored or semaglutide-centred. They cover type 2 diabetes glycaemic control (`NCT02906930`, `NCT03552757`), weight management (`NCT03548935` STEP 1, `NCT03611582`) and two large cardiovascular outcome or safety trials (`NCT01720446`, n=3,297; `NCT02692716`, n=3,183). Enrollment and status come from CT.gov enrichment.
- **Only one trial compares two drugs head to head.** `NCT03987919` tests tirzepatide against once-weekly semaglutide as add-on to metformin (n=1,879). Every other comparison in the graph is against placebo or within a single programme.
- **There are no contested claims, contradictions or prophetic claims.** In a protocol-only corpus this is expected and is not evidence of agreement between sources. The design simply leaves no room for divergent results to appear.
- **Orforglipron has thin coverage.** One trial (`NCT05971940`, n=559, T2D on diet and exercise alone) is the only evidence for the oral non-peptide agent. No obesity-indication orforglipron trial appears.

## Prophetic Claim Landscape

The graph contains no `prophetic` claims. That fits the source type: these are ClinicalTrials.gov protocol records, not patent filings, so forward-looking patent language ("may be prepared by", "is expected to") does not occur.

There is a related caveat. Protocol text is forward-looking in its own way: it states what a trial *intends* to measure. Relations such as `has_outcome` and `evaluated_for` link an intervention to an outcome *measure*, not to an observed benefit. For example, `semaglutide 0.5 mg once weekly s.c.` linked to `Change in HbA1c` means HbA1c change was a planned endpoint. It does not mean HbA1c fell. Reading these `asserted` relations as efficacy findings would overstate them. This caveat applies to every trial in the corpus, including the cardiovascular outcome trials `NCT01720446` and `NCT02692716`, whose MACE-type endpoints appear as measures with no reported hazard ratios.

## Contested Claims & Contradictions

The graph contains no `contested` claims and no `contradictions`. Each trial is described by its own protocol document, and no two sources make opposing statements about the same relation. The one setting where divergence could appear is the comparison between `NCT03987919` (tirzepatide vs semaglutide) and the semaglutide-only trials. It cannot appear here because neither side has results in the graph.

## Coverage Gaps

**Outcome values (the main gap).** The graph has many Outcome entities but no measured values, confidence intervals or met/not-met flags for any trial. All ten trials are COMPLETED according to CT.gov, so results almost certainly exist. The graph does not hold them.

**Verbatim endpoint language.** The summary I received does not include primary or secondary endpoint wording, so I cannot quote it here. It needs to be pulled from each protocol before any endpoint-level comparison.

**Trial phase spread.**
- Every trial is `Phase 3`.
- There are no Phase 1 or 2 dose-finding studies, so the dose choices (for example, the separate `semaglutide 0.5 mg` and `Semaglutide 1.0 mg` interventions) have no supporting evidence in the graph.
- There are no Phase 4 or post-marketing studies. For approved products such as semaglutide and tirzepatide, the absence of any post-market safety source is a finding in itself.

**Tier assignment needs checking.** By definition, `high_evidence` requires randomized, double-blind, placebo-controlled designs. `NCT03987919` is an active-comparator trial, and the graph does not record whether it was blinded. If it was open-label, the rubric would place it at `medium_evidence`, and the uniform `high_evidence` grade would be wrong for it.

**Few head-to-head trials.** Only `NCT03987919` compares tirzepatide with semaglutide directly.
- There is no semaglutide vs orforglipron comparison.
- There is no tirzepatide vs placebo trial in T2D.
- Obesity comparisons across programmes (`NCT03548935` vs `NCT04184622`, n=2,539) would be indirect only.

The trials compared:

| Trial | Compound(s) | Population focus | Comparator | Tier | Enrollment |
|---|---|---|---|---|---|
| `NCT03987919` | tirzepatide vs semaglutide | T2D on metformin | Active | high_evidence (unverified) | 1,879 |
| `NCT03548935` (STEP 1) | semaglutide | Overweight/obesity | Placebo | high_evidence | 1,961 |
| `NCT04184622` | tirzepatide | Obesity/overweight | Not specified in summary | high_evidence | 2,539 |
| `NCT05822830` | tirzepatide | Obesity/overweight with comorbidities | Not specified in summary | high_evidence | 751 |
| `NCT05971940` | orforglipron | T2D, diet and exercise only | Not specified in summary | high_evidence | 559 |

**Investigators and sites.** These are part of the schema, but neither type appears among the entity types extracted. The graph cannot answer questions about geography, site concentration or investigator overlap.

**Sponsor attribution.** The graph has two Sponsor entities, but only `Novo Nordisk` is clearly resolved. The tirzepatide and orforglipron trials use LY compound codes, yet the graph does not name their sponsor. Confirm it against CT.gov before making any sponsor-level statement.

**Mechanism.** There are very few `targets` relations. The graph barely records GLP-1 receptor or GIP receptor pharmacology, so it cannot separate the mono-agonists (semaglutide, orforglipron) from the dual agonist (tirzepatide).

**Biomarkers and strata.** `HbA1c` and `Body Mass Index` dominate. The other biomarker entities are not prominent, and no biomarker-defined subgroup or companion diagnostic appears. The population strata visible in the trial titles (diet and exercise only, metformin add-on, weight-related comorbidities, intensive lifestyle programme in `NCT03611582`) need to be checked against the Population and Cohort nodes.

**Entity hygiene.**
- A Cohort node named `Semaglutide` and an Intervention named `Placebo (semaglutide)` mix up arms and compounds.
- With 19 interventions mapped to 5 compounds, combination and co-intervention links (`co_intervention`) need review. Lifestyle and background therapy must not be counted as active compounds.

## Recommended Follow-Ups

1. **Pull CT.gov posted results** for all ten trials, starting with `NCT01720446`, `NCT02692716` (CV outcomes) and `NCT03987919` (head to head). Store primary endpoint results as separate result-bearing relations so they are not merged with the protocol-intent `has_outcome` edges.
2. **Extract verbatim primary and secondary endpoint text** from each protocol, so that endpoint comparisons can be made with quoted language.
3. **Check blinding and masking for `NCT03987919`** and re-tier it if it was open-label. Do the same check on every trial whose comparator the summary does not state (`NCT04184622`, `NCT05822830`, `NCT05971940`).
4. **Resolve the second Sponsor entity** and attach it to the tirzepatide and orforglipron trials.
5. **Add `targets` relations** for the GLP-1R and GIPR mechanisms to all five compounds, using the PubChem-enriched records (`semaglutide` CID 56843331, `tirzepatide` CID 166567236) as anchors.
6. **Fix the arm-vs-compound naming** (`Semaglutide` as a Cohort, `Placebo (semaglutide)`). Check that every Intervention links to the right Compound and that background therapies are kept separate.
7. **Fill in the evidence base** with the dose-finding Phase 2 trials and any Phase 4 or pharmacovigilance sources for semaglutide and tirzepatide. Add more orforglipron trials (especially obesity), so that obesity and T2D findings are not resting on a single trial.
8. **Re-run the epistemic layer after results are ingested.** Only then can `contested` claims or `contradictions` emerge, for example between the tirzepatide vs semaglutide comparison in `NCT03987919` and the semaglutide placebo-controlled effect sizes.
