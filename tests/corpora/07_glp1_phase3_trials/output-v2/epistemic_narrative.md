# Epistemic Briefing

## Executive Summary

- **The whole corpus is Phase 3 and every claim is asserted.** All ten trials are registered as `PHASE3` and `COMPLETED` (per CT.gov enrichment). Most claims grade `high_evidence`. The `medium_evidence` share comes from the two open-label (masking `NONE`) studies, `NCT03987919` (SURPASS-2) and `NCT05822830` (SURMOUNT-5). No claim is hypothesized, prophetic, or negative, so the epistemic layer adds little beyond the phase-tier grading.
- **The five contested claims reflect mixed evidence tiers, not conflicting results.** Each one links `semaglutide` or `tirzepatide` to type 2 diabetes, obesity, or overweight. In every case, double-blind sources (`high_evidence`) sit alongside an open-label source (`medium_evidence`). Nothing in the graph shows one source reporting benefit while another reports none. Read these as "graded differently by source", not as a disputed Phase 3 result.
- **The only direct comparisons are open-label.** `NCT03987919` is by title a tirzepatide-versus-semaglutide study as add-on to metformin in type 2 diabetes. `NCT05822830` contributes semaglutide–obesity and semaglutide–overweight claims, which suggests a semaglutide arm, but its registry title names only tirzepatide. Any comparative-efficacy conclusion from this graph rests on `medium_evidence`.
- **The graph names outcomes but holds no outcome values.** It records many outcome nodes (for example `Change in HbA1c`) and biomarkers (`HbA1c`, `Body Mass Index`). The summary contains no effect sizes, p-values, confidence intervals, or met/not-met status. The graph can tell you which endpoints were measured, but not whether any primary endpoint was met.
- **Two cardiovascular outcome trials anchor the safety evidence.** These are `NCT01720446` (SUSTAIN-6, subcutaneous semaglutide, enrollment 3297) and `NCT02692716` (PIONEER 6, oral semaglutide, enrollment 3183). There is no equivalent cardiovascular outcome trial for `tirzepatide` or the orforglipron program (`NCT05971940`).

## Prophetic Claim Landscape

**There are no prophetic claims in this corpus.** Every claim relation carries the `asserted` status. That fits the source type: completed ClinicalTrials.gov registrations and study reports, with no patent filings and none of the "is expected to" or "may be prepared by" language that would trigger a prophetic tag.

The closest risk is a different one: forward-looking **protocol intent** being read as a result. Registry titles such as "Research Study to Look at How Well Semaglutide is at Lowering Weight…" (`NCT03611582`) and "How Well Semaglutide Works…" (STEP 1, `NCT03548935`) describe what the trial set out to measure. They do not establish efficacy. Because the summary contains no outcome values, any `has_outcome` claim should be read as "this endpoint was measured", not "this endpoint was achieved". So the gap is not between prophetic and asserted language. It is between asserted design facts and the results data the graph does not contain.

## Contested Claims & Contradictions

All five contested relations follow the same pattern: double-blind sources (`high_evidence`) are combined with an open-label Phase 3 source (`medium_evidence`) on the same compound–condition edge.

| Relation | `high_evidence` sources | `medium_evidence` source | Nature of contest |
|---|---|---|---|
| `semaglutide` evaluated_for Type 2 Diabetes Mellitus | `NCT01720446` (SUSTAIN-6, n=3297), `NCT02692716` (PIONEER 6, n=3183), `NCT02906930` (PIONEER 1, n=703), `NCT03552757` (STEP 2, n=1210) | `NCT03987919` (SURPASS-2, open-label, n=1879) | Tier mismatch: comparator role in an open-label head-to-head |
| `semaglutide` evaluated_for Obesity | `NCT03548935` (STEP 1, n=1961), `NCT03552757` (STEP 2) | `NCT05822830` (SURMOUNT-5, open-label, n=751) | Tier mismatch |
| `semaglutide` evaluated_for Overweight | `NCT03548935`, `NCT03552757` | `NCT05822830` | Tier mismatch |
| `tirzepatide` evaluated_for Obesity | `NCT04184622` (SURMOUNT-1, n=2539) | `NCT05822830` | Tier mismatch |
| `tirzepatide` evaluated_for Overweight | `NCT04184622` | `NCT05822830` | Tier mismatch |

What this means:

- **These are not contradictions in the substantive sense.** None of the relations is tagged `contradictions` or `negative`, and the graph contains no opposing result values. The contest is about how much weight each source should carry, not about what the sources found.
- **Semaglutide's evidence for type 2 diabetes does not depend on the contested source.** Four double-blind trials support it, including two large cardiovascular outcome trials. SURPASS-2 (`NCT03987919`) adds only an open-label comparator observation.
- **Tirzepatide's evidence for obesity is thinner.** It rests on a single `high_evidence` source (SURMOUNT-1, `NCT04184622`) plus one open-label study. Any further disagreement would affect tirzepatide's obesity profile more than semaglutide's.
- **Check the roles of the open-label trials.** For SURMOUNT-5 (`NCT05822830`), confirm whether semaglutide is a randomized comparator arm or only mentioned in background text. If it is only background, the semaglutide–obesity and semaglutide–overweight contests are artifacts of extraction.

## Coverage Gaps

- **No outcome magnitudes or endpoint status.** The graph does not contain HbA1c change, percentage body-weight change, MACE hazard ratios, or met/not-met flags for any trial. The protocol's primary and secondary endpoint wording, which should be quoted verbatim, is also not in the summary, so none can be quoted here.
- **Only Phase 3 trials.** There are no Phase 1 or Phase 2 trials, no observational or Phase 4 studies, and no post-marketing pharmacovigilance sources. As a result, the graph cannot surface post-approval safety signals for `semaglutide` or `tirzepatide`, and this absence is itself a finding.
- **No adverse-event or safety-outcome detail.** SUSTAIN-6 and PIONEER 6 are cardiovascular safety trials by title, but the summary shows no adverse-event, discontinuation, or MACE-component outcomes. The relation types that are present do not include an explicit safety or adverse-event relation.
- **Limited head-to-head coverage, all open-label.** No double-blind head-to-head trial exists between any two incretin agents. Oral versus subcutaneous semaglutide is never directly compared.
- **The orforglipron program is isolated.** `NCT05971940` (n=559, double-blind) is the only trial in its program. It sits outside every contested relation, so its claims cannot be checked against any other source.
- **Population detail is thin compared with cohort counts.** Many cohort and population nodes exist, but the summary does not show age ranges, BMI thresholds, HbA1c entry criteria, or comorbidity strata. For example, the summary does not show the "weight related comorbidities" that SURMOUNT-5's title refers to.
- **Sponsors are incompletely attributed.** Only two sponsor entities exist, and only `Novo Nordisk` appears among the top entities. The tirzepatide and orforglipron trials (LY-coded compounds) should be checked for a correctly linked sponsor.
- **Not every compound has an enrichment record.** PubChem identifiers appear for `semaglutide` and `tirzepatide`, but the summary shows none for the other compound nodes.

## Recommended Follow-Ups

1. **Pull CT.gov results sections or the primary publications** for all ten NCT IDs. Load primary-endpoint values, analysis populations, and met/not-met status, and add them as outcome attributes. This would turn `has_outcome` from "measured" into "achieved".
2. **Manually review the SURMOUNT-5 (`NCT05822830`) arm structure.** Confirm whether `semaglutide` is a randomized comparator. If it is not, remove the semaglutide–obesity and semaglutide–overweight edges sourced from it and resolve two of the five contested claims.
3. **Decide how mixed-tier edges should be labeled.** Consider a separate status such as "mixed-tier" for edges that combine double-blind and open-label support. Reserve `contested` for actual divergence in results, so the label signals real disagreement.
4. **Quote the endpoint language verbatim.** Extract the exact primary and secondary endpoint wording for SUSTAIN-6 (`NCT01720446`), PIONEER 6 (`NCT02692716`), STEP 1 (`NCT03548935`), and SURMOUNT-1 (`NCT04184622`).
5. **Add sources on safety and later-phase evidence.** Include FDA labels or pharmacovigilance documents for `semaglutide` and `tirzepatide`, and any cardiovascular outcome trial for `tirzepatide`, to close the post-market and cardiovascular-safety gap.
6. **Check entity hygiene.** Confirm that the second sponsor is attached to every Lilly-coded trial. Confirm that orforglipron is represented as a Compound with enrichment. Check that the cohort node named `Semaglutide` is not duplicating the compound node.
7. **Make population criteria explicit.** Surface age, BMI, and HbA1c inclusion thresholds per cohort, so that STEP 1 (`NCT03548935`), STEP 2 (`NCT03552757`), and SURMOUNT-1 (`NCT04184622`) can be compared by stratum rather than by trial label alone.
