# Epistemic Briefing

## Executive Summary

- **The corpus is all Phase 3 and all asserted.** Every trial in the graph is a completed Phase 3 study (CT.gov enrichment). The graph tags every claim `asserted`, with nothing `prophetic`, `hypothesized`, `contested` or in `contradictions`. That gives a clean evidence base, but it also suggests the corpus or the extraction picks up only positive, protocol-level statements.
- **Most claims are at `high_evidence` tier.** Eight of the ten trials are double- or quadruple-masked with enrollment from 559 to 3,297 (CT.gov). The cardiovascular safety studies are the largest: `NCT01720446` (SUSTAIN 6, n=3,297) and `NCT02692716` (PIONEER 6, n=3,183).
- **The only `medium_evidence` sources are the two open-label tirzepatide trials.** These are `NCT03987919` (SURPASS-2, tirzepatide vs semaglutide on metformin, n=1,879, masking NONE) and `NCT05822830` (SURMOUNT-5, n=751, masking NONE). They are also the only head-to-head comparisons between the two incretins in the graph, so the most commercially important question rests on the less rigorous designs.
- **The mixed-tier claims are not disputes.** Each of the five mixed-tier claims (semaglutide or tirzepatide `evaluated_for` T2DM, Obesity or Overweight) still holds on the `high_evidence` trials alone.
- **The graph cannot support efficacy magnitudes.** The summary contains no outcome values, effect sizes, p-values or verbatim endpoint text. Any briefing on how much weight or HbA1c was lost needs the outcome records pulled directly.

## Prophetic Claim Landscape

The graph has no `prophetic` claims. That fits a corpus made of ClinicalTrials.gov protocols and study reports rather than patents: phrasing such as "is expected to" or "may be prepared by" does not occur in registered trial records the way it does in patent claims.

Two points follow:

- **Protocol intent should not be read as efficacy.** Registrations describe what a trial *will* measure. A `has_outcome` edge from a protocol means an endpoint was pre-specified, not that it was met. The summary does not show whether these edges come from results postings or protocol text, so treat them as design facts, not findings.
- **The gap between prophetic and asserted is zero only by construction.** Some trial titles are worded as intent, for example `NCT03611582` ("Research Study to Look at How Well Semaglutide is at Lowering Weight…") and `NCT03548935` (STEP 1, "Research Study Investigating How Well Semaglutide Works…"). If that language reached the graph as `asserted` efficacy, it is forward-looking content without a prophetic label. Spot-check this before relying on it.

## Contested Claims & Contradictions

The graph contains no `contested` claims and no `contradictions`. No two sources report different results for the same relation.

The five mixed-tier claims agree across sources and differ only in design rigor:

| Claim | `high_evidence` sources | `medium_evidence` sources | Holds on high tier alone? |
|---|---|---|---|
| `semaglutide` → Type 2 Diabetes Mellitus | `NCT01720446` (SUSTAIN 6, n=3,297), `NCT02692716` (PIONEER 6, n=3,183), `NCT02906930` (PIONEER 1, n=703), `NCT03552757` (STEP 2, n=1,210) | `NCT03987919` (SURPASS-2, open-label, n=1,879) | Yes |
| `semaglutide` → Obesity | `NCT03548935` (STEP 1, n=1,961), `NCT03552757` (STEP 2) | `NCT05822830` (SURMOUNT-5, open-label, n=751) | Yes |
| `semaglutide` → Overweight | `NCT03548935`, `NCT03552757` | `NCT05822830` | Yes |
| `tirzepatide` → Obesity | `NCT04184622` (SURMOUNT-1, n=2,539) | `NCT05822830` | Yes, on one trial |
| `tirzepatide` → Overweight | `NCT04184622` | `NCT05822830` | Yes, on one trial |

The tirzepatide obesity and overweight claims rest on a single double-blind trial, `NCT04184622`. The semaglutide claims have two to four. "No contradictions" also means the graph has no case of two trials testing the same intervention in the same condition and reaching different conclusions. With this many semaglutide studies in T2DM and obesity, the more likely explanation is that the graph does not capture results, not that the results are uniform.

## Coverage Gaps

- **No outcome values.** The graph has many Outcome entities but the summary shows no results, effect sizes or confidence intervals, and no endpoint wording to quote. I cannot say whether any primary endpoint was met. Silence about a missed endpoint here is a gap in the data, not evidence that every endpoint was met.
- **No negative or failed findings.** No trial was terminated early or failed its primary endpoint, and nothing carries `negative` status. A ten-trial Phase 3 set with no negative signal at all looks like selection.
- **Head-to-head comparisons are only open-label.** The tirzepatide vs semaglutide comparisons come from `NCT03987919` and `NCT05822830`, both masking NONE. No double-blind head-to-head trial is in the graph. Orforglipron (`NCT05971940`, double-blind, n=559, CT.gov) has no comparator against an injectable incretin anywhere in the graph. Its comparator arm is not named in the summary.
- **Orforglipron is under-connected.** `NCT05971940` is a key trial, but orforglipron does not appear among the top compound entities or in any mixed-tier claim. It is unclear whether the compound node exists and is linked.
- **Cardiovascular outcomes are not visible.** `NCT01720446` and `NCT02692716` are cardiovascular outcome or safety trials by title, yet no MACE-type outcome or cardiovascular condition appears among the top entities.
- **Phases and post-market data are missing.** There are no Phase 1, Phase 2, Phase 4 or observational studies, so there is no dose-finding context and no post-market safety signal for any of the three compounds. Given the system-prompt rule, the absence of real-world pharmacovigilance for recently approved tirzepatide is a finding in itself.
- **Trial acronyms are missing for two trials.** `NCT03611582` (semaglutide with an intensive lifestyle program, n=611, quadruple-masked) and `NCT05971940` (orforglipron) have no acronym in the summary.
- **Sponsors are partly attributed.** Only Novo Nordisk is named. The second sponsor entity is not shown, so I cannot confirm sponsor attribution for the tirzepatide and orforglipron trials (Eli Lilly compound codes LY3298176 and LY3502970 appear in the CT.gov titles).
- **Investigators and sites are thin or absent.** Neither Investigator nor Site is among the represented entity types, so the graph cannot support geographic or site-level analysis.
- **Population stratification is shallow.** Cohort and Population nodes exist, but the summary does not show age, BMI threshold or baseline-HbA1c strata. Without them, arm-level comparisons, such as semaglutide 0.5 mg vs 1.0 mg against `NCT03987919` comparators, cannot be stratified.

## Recommended Follow-Ups

1. **Pull CT.gov results postings or primary publications** for all ten NCTs. Attach primary-endpoint values and verbatim endpoint language to the existing Outcome nodes. Start with `NCT03987919` and `NCT05822830`, since they carry the head-to-head conclusions.
2. **Check whether `has_outcome` edges come from protocols or results.** Separate pre-specified endpoints from reported findings, and reclassify any intent language that was captured as `asserted` efficacy.
3. **Verify the orforglipron subgraph.** Confirm that a Compound node exists for orforglipron, that `NCT05971940` links to it through `tests` and `evaluated_for`, and that its comparator arm and sponsor are recorded.
4. **Recover the cardiovascular endpoints** for `NCT01720446` and `NCT02692716` (MACE composite, non-inferiority margin) and link them to a cardiovascular condition node.
5. **Fill in the missing attributes:** acronyms for `NCT03611582` and `NCT05971940`, and the name of the second sponsor.
6. **Extend the corpus for balance.** Add Phase 2 dose-finding studies, at least one trial that missed its primary endpoint or was terminated early, and post-marketing safety sources, so that the absence of `contested` and `negative` statuses means something.
7. **Make the open-label caveat explicit.** Before citing a tirzepatide vs semaglutide superiority result, note that both sources are `medium_evidence` because they are unblinded, and that no double-blind head-to-head trial exists in this corpus.
