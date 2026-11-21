---
name: clinicaltrials-extraction
description: >
  Use when extracting entities and relations from ClinicalTrials.gov
  protocol documents, IRB submissions, clinical study reports, trial
  publications, or any document discussing trial designs, interventions,
  conditions, sponsors, and outcomes. Activates for documents containing
  NCT numbers, phase designations (Phase 1/2/3), or trial protocol
  sections (Primary Endpoint, Inclusion/Exclusion Criteria, Arms).
version: 1.0.0
---

# Clinical Trials Extraction Skill

## NCT ID Capture

For any Trial entity, the `name` field MUST be the NCT identifier
(format: `NCT` followed by 8 digits, e.g. `NCT04303780`) when one is
present in the document. Study acronyms ("CodeBreaK 200"), sponsor-assigned
codes ("AMG 510 study"), and descriptive titles ("Phase 3 study of
sotorasib in NSCLC") go into `attributes.trial_acronym` or
`attributes.descriptive_title` — not into `name`.

If no NCT ID is present, fall back to the study acronym. Only use a
descriptive title as `name` as a last resort, and set `confidence` <= 0.6.

This rule exists because the post-build enrichment step resolves Trial
nodes against ClinicalTrials.gov via their NCT ID. Nodes without an NCT
ID cannot be enriched.

## Output Format

Return a `DocumentExtraction` JSON envelope. The `document_id` field is
REQUIRED. All entities and relations are lists of objects.

```json
{
  "document_id": "nct04303780_protocol",
  "entities": [
    {
      "name": "NCT04303780",
      "entity_type": "Trial",
      "confidence": 0.95,
      "context": "Phase 3 CodeBreaK 200 trial evaluating sotorasib vs docetaxel",
      "attributes": {
        "trial_acronym": "CodeBreaK 200",
        "study_type": "Interventional"
      }
    },
    {
      "name": "sotorasib",
      "entity_type": "Compound",
      "confidence": 0.95,
      "context": "AMG 510; KRAS G12C inhibitor evaluated as experimental arm",
      "attributes": {
        "inn": "sotorasib",
        "sponsor_code": "AMG 510"
      }
    }
  ],
  "relations": [
    {
      "source_entity": "NCT04303780",
      "target_entity": "sotorasib",
      "relation_type": "tests",
      "confidence": 0.95,
      "evidence": "Trial NCT04303780 evaluates sotorasib in the experimental arm"
    }
  ]
}
```

## Field Requirements

### Entity fields
- `name` (required): Canonical identifier. For Trial, use NCT ID. For Compound, use INN. For Condition, use MeSH term.
- `entity_type` (required): Must match one of the 17 types in domain.yaml exactly (case-sensitive).
- `confidence` (required): Float 0.0–1.0. See Confidence Calibration section.
- `context` (required): Short excerpt or paraphrase from the source document justifying extraction.
- `attributes` (optional): Dict of domain-specific metadata (e.g. `trial_acronym`, `sponsor_code`, `phase`, `dose`).

### Relation fields
- `source_entity` (required): `name` value of the source entity.
- `target_entity` (required): `name` value of the target entity.
- `relation_type` (required): Must match one of the 23 relation types in domain.yaml exactly (case-sensitive).
- `confidence` (required): Float 0.0–1.0.
- `evidence` (required): Short quote or paraphrase from the document supporting the relation.

## Entity Types

### Trial

A clinical trial identified by its NCT registry ID. NCT IDs follow the format
`NCT` followed by exactly 8 digits (e.g. `NCT04303780`). Always use the NCT ID
as the canonical `name` when present. Capture the study acronym and descriptive
title in attributes.

```json
{
  "name": "NCT04303780",
  "entity_type": "Trial",
  "confidence": 0.98,
  "context": "CodeBreaK 200 (NCT04303780): a global Phase 3 randomized controlled trial",
  "attributes": {
    "trial_acronym": "CodeBreaK 200",
    "descriptive_title": "Study to Compare AMG 510 With Docetaxel in NSCLC",
    "study_type": "Interventional",
    "status": "Active, not recruiting"
  }
}
```

### Intervention

A procedure, behavioral intervention, device use, or non-drug therapy (i.e., not a
drug or biologic) being studied in the trial. An intervention that IS a drug or
biologic gets BOTH a Compound entity (with INN as name) AND an Intervention entity
(with the arm label as name), linked by the `tests` relation from the Trial.

```json
{
  "name": "sotorasib 960 mg QD oral",
  "entity_type": "Intervention",
  "confidence": 0.92,
  "context": "Experimental arm: sotorasib 960 mg administered orally once daily",
  "attributes": {
    "dose": "960 mg",
    "schedule": "QD",
    "route": "oral"
  }
}
```

Drug linkage rules:

- Every dose- or regimen-specific Intervention (e.g. 'semaglutide 1.0 mg QW SC') MUST link to its Compound via `contains_compound`.
- Each arm Cohort MUST link to what it receives via `receives` (the Intervention, and the Compound when named). Background, rescue or auxiliary medication that is not under study is linked from the Trial via `uses_background_drug`, never via `tests`.

### Condition

The disease, disorder, or indication being studied. Prefer MeSH disease terms as
the canonical name. Include disease subtypes and staging information when specified.

Use **one canonical name per disease across the whole corpus**, so that support from
different trials lands on the same node. Write "Type 2 Diabetes Mellitus", never
"Diabetes Mellitus, Type 2" or "T2DM" as the name (put variants in attributes). Split
combined labels: "overweight or obesity" becomes two Conditions, "Overweight" and
"Obesity".

```json
{
  "name": "Non-Small Cell Lung Carcinoma",
  "entity_type": "Condition",
  "confidence": 0.97,
  "context": "Patients with previously treated advanced NSCLC with KRAS G12C mutation",
  "attributes": {
    "mesh_term": "Carcinoma, Non-Small-Cell Lung",
    "subtype": "KRAS G12C-mutant",
    "staging": "Advanced"
  }
}
```

### Sponsor

Organization funding or running the trial — pharmaceutical companies, academic
medical centers, CROs, or government agencies. Use the most widely recognized
organization name.

```json
{
  "name": "Amgen",
  "entity_type": "Sponsor",
  "confidence": 0.98,
  "context": "Sponsored by Amgen Inc., a multinational biopharmaceutical company",
  "attributes": {
    "role": "Industry sponsor",
    "country": "United States"
  }
}
```

### Investigator

Principal investigator or key study personnel named in the protocol or publication.
Use the full name as listed. Capture institution and role in attributes.

```json
{
  "name": "Melissa L. Johnson",
  "entity_type": "Investigator",
  "confidence": 0.95,
  "context": "Principal investigator: Dr. Melissa L. Johnson, Sarah Cannon Research Institute",
  "attributes": {
    "role": "Principal Investigator",
    "institution": "Sarah Cannon Research Institute"
  }
}
```

### Outcome

A primary, secondary, or exploratory outcome measure — the endpoint being assessed.
Include the endpoint category (primary/secondary/exploratory) in attributes.

```json
{
  "name": "overall survival",
  "entity_type": "Outcome",
  "confidence": 0.97,
  "context": "Primary endpoint: overall survival (OS) assessed by BIRC review",
  "attributes": {
    "endpoint_type": "Primary",
    "assessment_method": "BIRC review"
  }
}
```

The Outcome node keeps the trial-specific endpoint wording. When it contains a recognised
measure, also create or reuse the matching StandardOutcome and link it with `measures`
(see `### StandardOutcome`).

### Compound

A small molecule, biologic, or drug candidate under investigation. Prefer the
International Nonproprietary Name (INN) as the canonical `name`. Record sponsor
codes, brand names, and chemical names in attributes. Compound nodes are candidates
for PubChem enrichment during `--enrich`.

```json
{
  "name": "sotorasib",
  "entity_type": "Compound",
  "confidence": 0.98,
  "context": "Sotorasib (AMG 510), a first-in-class KRAS G12C covalent inhibitor",
  "attributes": {
    "inn": "sotorasib",
    "sponsor_code": "AMG 510",
    "drug_class": "KRAS G12C inhibitor",
    "mechanism": "Covalent irreversible KRAS G12C inhibition"
  }
}
```

### Biomarker

A measurable indicator used for patient selection, stratification, or response
assessment. Capture threshold, measurement method, and biomarker category in
attributes when available.

```json
{
  "name": "KRAS G12C",
  "entity_type": "Biomarker",
  "confidence": 0.98,
  "context": "Eligible patients must have KRAS G12C mutation confirmed by local testing",
  "attributes": {
    "biomarker_type": "Genomic",
    "gene": "KRAS",
    "variant": "G12C",
    "use": "Patient selection (inclusion criterion)"
  }
}
```

### Cohort

A specific arm or group within the trial. Each study arm becomes a Cohort entity.
Name = arm label (e.g. 'Arm A: sotorasib 960 mg QD'). Attributes capture `dose`,
`schedule`, `population_size`.

```json
{
  "name": "Arm A: sotorasib 960 mg QD",
  "entity_type": "Cohort",
  "confidence": 0.95,
  "context": "Arm A: sotorasib 960 mg orally once daily; n=171",
  "attributes": {
    "arm_label": "Arm A",
    "dose": "960 mg",
    "schedule": "QD",
    "route": "oral",
    "population_size": 171
  }
}
```

### Population

The inclusion/exclusion-defined patient population for the trial. Captures the
eligibility criteria as a single entity representing who the trial targets.

```json
{
  "name": "Previously treated KRAS G12C-mutant NSCLC patients",
  "entity_type": "Population",
  "confidence": 0.92,
  "context": "Adults with advanced NSCLC, KRAS G12C mutation, 1-2 prior lines of therapy",
  "attributes": {
    "age_group": "Adult",
    "prior_treatment": "1-2 prior lines",
    "performance_status": "ECOG 0-1"
  }
}
```

### TrialPhase

The regulatory phase designation. Normalize phase values to exactly one of:
`Phase 1`, `Phase 2`, `Phase 2/3`, `Phase 3`, `Phase 4`, `Observational`.
Map 'I' -> `Phase 1`, 'II' -> `Phase 2`, 'III' -> `Phase 3`, 'IV' -> `Phase 4`.
Do not use Roman numerals or non-standard designations in the `name` field.

```json
{
  "name": "Phase 3",
  "entity_type": "TrialPhase",
  "confidence": 0.99,
  "context": "Phase 3, randomized, open-label, multicenter study",
  "attributes": {
    "design": "Randomized controlled trial",
    "blinding": "Open-label"
  }
}
```

### Site

A clinical study site — specific hospital, clinic, or country listed as a trial
location. Use the most specific available name (institution name preferred over
city/country alone).

```json
{
  "name": "Sarah Cannon Research Institute",
  "entity_type": "Site",
  "confidence": 0.90,
  "context": "Study sites include Sarah Cannon Research Institute, Nashville, TN",
  "attributes": {
    "city": "Nashville",
    "state": "TN",
    "country": "United States"
  }
}
```

### AdverseEvent

An adverse event or side effect reported among trial participants. Name it by the
event term itself, not by the arm, timepoint or count. Use one node per distinct
event term: when the same term is reported for several arms, it is ONE AdverseEvent
node with one `observed_in` relation per arm. Serious adverse events get
`serious: true`. Attributes: `serious` (bool), `grade`, `n_affected`, `n_at_risk`,
`percent`, `timeframe`, `reported_term`, `meddra_pt`. Link it to its OrganSystem via
`affects_organ_system` when the document groups events by system organ class. Name and
attribute it according to the rules in "Adverse Event Normalization" below.

```json
{
  "name": "Nausea",
  "entity_type": "AdverseEvent",
  "confidence": 0.95,
  "context": "Nausea was the most frequent adverse event (semaglutide 1.0 mg: 21.9% vs placebo: 6.1%)",
  "attributes": {
    "serious": false,
    "grade": "mild to moderate",
    "n_affected": 90,
    "n_at_risk": 411,
    "percent": 21.9,
    "timeframe": "weeks 0-30"
  }
}
```

### OrganSystem

The body or organ system an adverse event affects, named at system-organ-class level
(e.g. "Gastrointestinal disorders", "Cardiac disorders", "Nervous system disorders").
Use one node per class across the corpus, and create it only when the document
states or clearly implies the grouping.

```json
{
  "name": "Gastrointestinal disorders",
  "entity_type": "OrganSystem",
  "confidence": 0.9,
  "context": "Gastrointestinal disorders were the most common system organ class of adverse events",
  "attributes": {
    "classification": "system organ class"
  }
}
```

### StandardOutcome

A canonical, reusable outcome measure or assessment instrument shared across trials
(e.g. "HbA1c", "Body weight", "Systolic blood pressure", "SF-36 physical functioning",
"Overall survival"). The trial-specific wording stays on the Outcome node.

Identification rules (CTKG):

- Map each Outcome to a StandardOutcome when its wording contains a recognised measure.
- Use abbreviation-definition pairs: "glycated haemoglobin (HbA1c)" gives HbA1c.
- Recognise phrases built on the keywords scale, index, score, test, questionnaire, value, count, inventory, assessment, level, rate.
- Also recognise common measures without those keywords: overall survival, progression-free survival, body weight, blood pressure, HbA1c, triglycerides, waist circumference, BMI, MACE.
- Canonical naming: one StandardOutcome per measure across the corpus. Strip "change from baseline in", timepoints and units. Use the established short form where conventional (HbA1c, BMI, MACE) and sentence case otherwise ("Body weight", "Systolic blood pressure", "Fasting plasma glucose", "SF-36 physical functioning").
- A composite outcome gets ONE StandardOutcome for the composite (e.g. "MACE"). Do not split it.

```json
{
  "name": "Body weight",
  "entity_type": "StandardOutcome",
  "confidence": 0.92,
  "context": "Co-primary endpoint: percentage change in body weight from baseline to week 68",
  "attributes": {
    "aliases": [
      "bodyweight",
      "weight"
    ],
    "measure_kind": "anthropometric"
  }
}
```

### OutcomeAnalysis

A reported statistical comparison of arms on one outcome: the effect estimate, confidence
interval, and p-value for treatment vs comparator at a timepoint.

Name it `"<NCT ID>: <standard outcome> — <treatment> vs <comparator> (<timepoint>)"`, for example
`"NCT03548935: Body weight — semaglutide 2.4 mg vs placebo (week 68)"`.

Attributes:

- `p_value`: string as reported (e.g. "<0.001")
- `p_value_num`: float; the upper bound when reported as "<x"
- `effect_estimate`: float
- `effect_measure`: ETD / HR / OR / RR / mean difference
- `ci_lower`, `ci_upper`, `ci_level`: confidence interval bounds and level (default 95)
- `significant`: bool. True if p < 0.05 or the CI excludes the null (0 for differences, 1 for ratios); false if reported non-significant.
- `endpoint_type`: primary / secondary / exploratory
- `timepoint`: e.g. "week 68"
- `direction`: favours_treatment / favours_comparator / no_difference
- `missing_data_method`: e.g. "multiple imputation"

Only extract an OutcomeAnalysis when the text reports a result (an estimate or a p-value).
Protocol-only documents produce none.

Each OutcomeAnalysis links to its Outcome via `analyzes`, to each arm compared via `compares`
(one edge per arm), to the experimental treatment via `assesses_effect_of`, and to its method
via `uses_method` when one is named.

```json
{
  "name": "NCT03548935: Body weight — semaglutide 2.4 mg vs placebo (week 68)",
  "entity_type": "OutcomeAnalysis",
  "confidence": 0.95,
  "context": "Estimated treatment difference -12.4 percentage points (95% CI -13.4 to -11.5; P<0.001)",
  "attributes": {
    "p_value": "<0.001",
    "p_value_num": 0.001,
    "effect_estimate": -12.4,
    "effect_measure": "ETD",
    "ci_lower": -13.4,
    "ci_upper": -11.5,
    "ci_level": 95,
    "significant": true,
    "endpoint_type": "primary",
    "timepoint": "week 68",
    "direction": "favours_treatment",
    "missing_data_method": "multiple imputation"
  }
}
```

### StatisticalMethod

A statistical test or model used in an OutcomeAnalysis (e.g. "ANCOVA", "MMRM",
"Cox proportional hazards", "Log-rank test").

Use one canonical spelling and merge punctuation and word-order variants ("paired t test"
becomes "Paired t-test"). Seed list: ANCOVA, MMRM, Cox proportional hazards, Log-rank test,
Logistic regression, Chi-square test, Fisher's exact test, Paired t-test, Wilcoxon signed-rank
test, Cochran–Mantel–Haenszel test, Negative binomial regression, Hierarchical testing procedure.

Multiple imputation is NOT a StatisticalMethod node: record it as `missing_data_method` on the OutcomeAnalysis.

```json
{
  "name": "ANCOVA",
  "entity_type": "StatisticalMethod",
  "confidence": 0.9,
  "context": "Change in body weight was analysed with an analysis of covariance (ANCOVA) model, with multiple imputation for missing data",
  "attributes": {
    "full_name": "Analysis of covariance"
  }
}
```

## Adverse Event Normalization

Name every AdverseEvent with the rules below so that the same event reported in different
trials or wordings becomes one node. The rules follow CTKG section 4.1 and are applied by
you directly, without a MedDRA lookup. No MedDRA dictionary is shipped with this domain
(the license forbids it), so never invent or look up codes.

1. Strip parenthesised asides: "Nausea (mild, transient)" becomes "Nausea".
2. Strip laterality, phase and timeframe qualifiers such as "left", "right", "Baseline Phase",
   "during titration", "for 12 hours" or "Week 0-20". Keep the timeframe in `attributes.timeframe`.
3. Name the event, not the grade, arm or count: "Grade 3 nausea in semaglutide arm" becomes
   "Nausea", with the grade in `attributes.grade`.
4. Use the singular, sentence case and US spelling: "Diarrhoea" becomes "Diarrhea", "Oedema"
   becomes "Edema", "Haemorrhage" becomes "Hemorrhage", and "hypoglycaemia" becomes
   "Hypoglycemia", so spelling variants never create two nodes. This matches the
   `adverse_event` normalizer of the pharmacovigilance crosswalk.
5. Prefer the preferred-term-level wording that clinicians use: "Vomiting", not "Throwing up"
   or "Emesis episodes". Merge lowest-level variants of one event into a single node ("Eye
   itching" and "Ocular itching" become "Eye pruritus"). Correct obvious misspellings.
6. Record the wording found in the source in `attributes.reported_term`.
7. Record `attributes.meddra_pt` only when you are confident that it is the MedDRA preferred
   term wording; otherwise omit it. Never look it up. It is the same key the pharmacovigilance
   crosswalk joins on.
8. Assign the OrganSystem by system organ class name (for example "Gastrointestinal
   disorders"), judged from the clinical nature of the event.

```json
{
  "name": "Diarrhea",
  "entity_type": "AdverseEvent",
  "confidence": 0.9,
  "context": "Grade 2 diarrhoea (transient) during titration",
  "attributes": {
    "reported_term": "Grade 2 diarrhoea (transient) during titration",
    "grade": "2",
    "timeframe": "during titration"
  }
}
```

Add `meddra_pt` only when you are confident of the exact MedDRA PT wording; otherwise omit it.

## Relation Types

### tests

**Source:** Trial | **Target:** Compound or Intervention

A Trial tests a Compound or Intervention. Use this relation to connect the trial
to each experimental treatment arm. For drug interventions, create separate `tests`
relations to both the Compound (INN name) and the Intervention (arm label).

```json
{
  "source_entity": "NCT04303780",
  "target_entity": "sotorasib",
  "relation_type": "tests",
  "confidence": 0.98,
  "evidence": "NCT04303780 evaluates sotorasib 960 mg QD as experimental treatment"
}
```

### treats

**Source:** Compound or Intervention | **Target:** Condition

A Compound or Intervention has **shown or approved** efficacy for a Condition. Use
only when the text reports an observed result ("reduced HbA1c by 2.0%", "met its
primary endpoint") or an approved indication. A protocol that plans to test a
treatment is `evaluated_for`, not `treats`. Distinguish from `investigates`
(Trial->Condition).

```json
{
  "source_entity": "semaglutide",
  "target_entity": "Type 2 Diabetes Mellitus",
  "relation_type": "treats",
  "confidence": 0.92,
  "evidence": "Semaglutide is approved as an adjunct to diet and exercise to improve glycemic control in adults with type 2 diabetes"
}
```

### evaluated_for

**Source:** Compound or Intervention | **Target:** Condition

A Compound or Intervention is being tested as a treatment for a Condition. This is
the normal relation for protocol and registry text, which states intent rather than
results.

```json
{
  "source_entity": "sotorasib",
  "target_entity": "Non-Small Cell Lung Carcinoma",
  "relation_type": "evaluated_for",
  "confidence": 0.93,
  "evidence": "Sotorasib evaluated for treatment of previously treated NSCLC"
}
```

### compared_with

**Source:** Compound or Intervention | **Target:** Compound or Intervention

Two Compounds or Interventions are given in **separate arms** and compared against
each other: an active comparator, a head-to-head design, or a placebo control. Do
not use `co_intervention` for this.

```json
{
  "source_entity": "tirzepatide",
  "target_entity": "semaglutide",
  "relation_type": "compared_with",
  "confidence": 0.95,
  "evidence": "Tirzepatide 5, 10 or 15 mg once weekly versus semaglutide 1 mg once weekly"
}
```

### sponsored_by

**Source:** Trial | **Target:** Sponsor

A Trial is sponsored or funded by a Sponsor. Every Trial with a named sponsor in
the protocol MUST produce a `sponsored_by` relation.

```json
{
  "source_entity": "NCT04303780",
  "target_entity": "Amgen",
  "relation_type": "sponsored_by",
  "confidence": 0.98,
  "evidence": "Sponsored by Amgen Inc."
}
```

### has_investigator

**Source:** Trial | **Target:** Investigator

A Trial names an Investigator — principal investigator, study chair, or key study
personnel. Every Investigator entity MUST be linked to its Trial with
`has_investigator`; an Investigator with no relation is dropped from the graph.
When a publication reports a trial without an NCT ID, link to the Trial entity
named by the study acronym. Do not create Investigator entities for authors who
are not named as trial investigators.

```json
{
  "source_entity": "NCT04303780",
  "target_entity": "Melissa L. Johnson",
  "relation_type": "has_investigator",
  "confidence": 0.95,
  "evidence": "Principal investigator: Dr. Melissa L. Johnson"
}
```

### conducted_at

**Source:** Trial | **Target:** Site

A Trial is conducted at a Site. Every Site entity MUST be linked to its Trial with
`conducted_at`; a Site with no relation is dropped from the graph.

```json
{
  "source_entity": "NCT04303780",
  "target_entity": "Sarah Cannon Research Institute",
  "relation_type": "conducted_at",
  "confidence": 0.9,
  "evidence": "Study sites include Sarah Cannon Research Institute, Nashville, TN"
}
```

### affiliated_with

**Source:** Investigator | **Target:** Site

An Investigator is affiliated with a Site (their institution). Use only when the
institution is also a trial Site entity in the same document; otherwise keep the
institution as the Investigator's `institution` attribute.

```json
{
  "source_entity": "Melissa L. Johnson",
  "target_entity": "Sarah Cannon Research Institute",
  "relation_type": "affiliated_with",
  "confidence": 0.9,
  "evidence": "Dr. Melissa L. Johnson, Sarah Cannon Research Institute"
}
```

### has_outcome

**Source:** Trial | **Target:** Outcome

A Trial has a specified Outcome endpoint. Capture primary, secondary, and key
exploratory endpoints. Create one `has_outcome` relation per distinct endpoint.

```json
{
  "source_entity": "NCT04303780",
  "target_entity": "overall survival",
  "relation_type": "has_outcome",
  "confidence": 0.97,
  "evidence": "Primary endpoint: overall survival assessed by BIRC"
}
```

### uses_biomarker

**Source:** Trial | **Target:** Biomarker

A Trial uses a Biomarker for patient selection, stratification, or response
assessment. Include inclusion-criterion biomarkers and pharmacodynamic markers.

```json
{
  "source_entity": "NCT04303780",
  "target_entity": "KRAS G12C",
  "relation_type": "uses_biomarker",
  "confidence": 0.98,
  "evidence": "KRAS G12C mutation required for enrollment"
}
```

### enrolls

**Source:** Trial | **Target:** Population or Cohort

A Trial enrolls a specific Population (inclusion/exclusion-defined) or Cohort
(arm-specific subgroup). Create one `enrolls` relation per arm (Cohort) and one
for the overall patient Population.

```json
{
  "source_entity": "NCT04303780",
  "target_entity": "Previously treated KRAS G12C-mutant NSCLC patients",
  "relation_type": "enrolls",
  "confidence": 0.95,
  "evidence": "Enrolled adults with advanced NSCLC with KRAS G12C mutation"
}
```

### investigates

**Source:** Trial | **Target:** Condition

A Trial investigates a Condition (the disease under study). Use for the primary
disease indication. Distinct from `treats` which links Compound/Intervention to Condition.

```json
{
  "source_entity": "NCT04303780",
  "target_entity": "Non-Small Cell Lung Carcinoma",
  "relation_type": "investigates",
  "confidence": 0.98,
  "evidence": "CodeBreaK 200 investigates KRAS G12C-mutant NSCLC"
}
```

### targets

**Source:** Compound | **Target:** Biomarker

A Compound targets a Biomarker (molecular target). Use when the mechanism of action
involves specific binding to or modulation of a measurable molecular entity.

```json
{
  "source_entity": "sotorasib",
  "target_entity": "KRAS G12C",
  "relation_type": "targets",
  "confidence": 0.98,
  "evidence": "Sotorasib covalently and irreversibly binds KRAS G12C"
}
```

### is_phase

**Source:** Trial | **Target:** TrialPhase

A Trial is of a given TrialPhase. Every stated phase MUST produce an `is_phase`
relation from the Trial to the matching TrialPhase entity. Use normalized phase
names (Phase 1, Phase 2, Phase 2/3, Phase 3, Phase 4, Observational).

```json
{
  "source_entity": "NCT04303780",
  "target_entity": "Phase 3",
  "relation_type": "is_phase",
  "confidence": 0.99,
  "evidence": "Phase 3, randomized, open-label study"
}
```

### co_intervention

**Source:** Compound or Intervention | **Target:** Compound or Intervention

Two Interventions or Compounds are co-administered in the same Cohort. Use for
combination therapy arms where multiple agents are administered together. If the
agents are in separate arms being compared, use `compared_with` instead. Do not
force a comparison into this relation at low confidence.

```json
{
  "source_entity": "nivolumab",
  "target_entity": "ipilimumab",
  "relation_type": "co_intervention",
  "confidence": 0.95,
  "evidence": "Combination arm: nivolumab 3 mg/kg + ipilimumab 1 mg/kg Q3W"
}
```

### reports_adverse_event

**Source:** Trial | **Target:** AdverseEvent

A Trial reports an AdverseEvent among its participants. Create one relation per distinct adverse event term the trial reports.

```json
{
  "source_entity": "NCT01720446",
  "target_entity": "Nausea",
  "relation_type": "reports_adverse_event",
  "confidence": 0.95,
  "evidence": "Nausea was reported more frequently with semaglutide than with placebo"
}
```

### observed_in

**Source:** AdverseEvent | **Target:** Cohort

An AdverseEvent was observed in a specific arm (Cohort). Create one relation per arm in which the event is reported. Put the arm-level counts (n_affected, n_at_risk, percent) in the evidence text.

```json
{
  "source_entity": "Nausea",
  "target_entity": "Semaglutide 1.0 mg QW SC",
  "relation_type": "observed_in",
  "confidence": 0.93,
  "evidence": "Nausea: 90/411 (21.9%) in the semaglutide 1.0 mg arm"
}
```

### affects_organ_system

**Source:** AdverseEvent | **Target:** OrganSystem

An AdverseEvent belongs to an OrganSystem. Use it when the document groups events by system organ class.

```json
{
  "source_entity": "acute pancreatitis",
  "target_entity": "Gastrointestinal disorders",
  "relation_type": "affects_organ_system",
  "confidence": 0.9,
  "evidence": "Gastrointestinal disorders: acute pancreatitis"
}
```

### receives

**Source:** Cohort | **Target:** Compound or Intervention

A Cohort (arm) receives a Compound or Intervention. Unlike `tests`, which is Trial-level, `receives` is arm-level: use it to say which treatment each arm was given.

```json
{
  "source_entity": "Semaglutide 1.0 mg QW SC",
  "target_entity": "semaglutide 1.0 mg QW SC",
  "relation_type": "receives",
  "confidence": 0.95,
  "evidence": "Patients in this arm received semaglutide 1.0 mg subcutaneously once weekly"
}
```

### contains_compound

**Source:** Intervention | **Target:** Compound

A dose- or regimen-specific Intervention contains a Compound. Every dose-specific Intervention MUST link to its Compound, so the dose-level arm label resolves to the INN-named drug.

```json
{
  "source_entity": "semaglutide 1.0 mg QW SC",
  "target_entity": "semaglutide",
  "relation_type": "contains_compound",
  "confidence": 0.97,
  "evidence": "semaglutide 1.0 mg once weekly, subcutaneous"
}
```

### uses_background_drug

**Source:** Trial | **Target:** Compound or Intervention

Background, rescue, or auxiliary medication used in the trial but not under study, such as metformin background therapy. Unlike `tests`, the drug is not the object of the trial, so never use `tests` for it.

```json
{
  "source_entity": "NCT01720446",
  "target_entity": "metformin",
  "relation_type": "uses_background_drug",
  "confidence": 0.88,
  "evidence": "Patients continued their stable background metformin therapy"
}
```

### measures

**Source:** Outcome | **Target:** StandardOutcome

A trial-specific Outcome measures a canonical StandardOutcome. The Outcome keeps the trial wording; the StandardOutcome is the shared canonical measure.

```json
{
  "source_entity": "percentage change in body weight from baseline to week 68",
  "target_entity": "Body weight",
  "relation_type": "measures",
  "confidence": 0.93,
  "evidence": "Co-primary endpoint: percentage change in body weight from baseline to week 68"
}
```

### analyzes

**Source:** OutcomeAnalysis | **Target:** Outcome

An OutcomeAnalysis analyses a specific Outcome, the endpoint whose result it reports.

```json
{
  "source_entity": "NCT03548935: Body weight — semaglutide 2.4 mg vs placebo (week 68)",
  "target_entity": "percentage change in body weight from baseline to week 68",
  "relation_type": "analyzes",
  "confidence": 0.95,
  "evidence": "Mean change in body weight from baseline to week 68 was -14.9% with semaglutide vs -2.4% with placebo"
}
```

### compares

**Source:** OutcomeAnalysis | **Target:** Cohort

An OutcomeAnalysis compares this arm. Emit one edge per arm compared, the comparator arm included.

```json
{
  "source_entity": "NCT03548935: Body weight — semaglutide 2.4 mg vs placebo (week 68)",
  "target_entity": "Semaglutide 2.4 mg QW SC",
  "relation_type": "compares",
  "confidence": 0.94,
  "evidence": "Semaglutide 2.4 mg (n=1306) vs placebo (n=655)"
}
```

### assesses_effect_of

**Source:** OutcomeAnalysis | **Target:** Compound or Intervention

The treatment whose effect the OutcomeAnalysis estimates. It points to the experimental side only; the comparator is reached through `compares`.

```json
{
  "source_entity": "NCT03548935: Body weight — semaglutide 2.4 mg vs placebo (week 68)",
  "target_entity": "semaglutide",
  "relation_type": "assesses_effect_of",
  "confidence": 0.95,
  "evidence": "Estimated treatment difference for semaglutide vs placebo -12.4 percentage points"
}
```

### uses_method

**Source:** OutcomeAnalysis | **Target:** StatisticalMethod

The StatisticalMethod used for the analysis, when the text names one.

```json
{
  "source_entity": "NCT03548935: Body weight — semaglutide 2.4 mg vs placebo (week 68)",
  "target_entity": "ANCOVA",
  "relation_type": "uses_method",
  "confidence": 0.9,
  "evidence": "analysed using an analysis of covariance model"
}
```

## Confidence Calibration

The score says how strongly the text supports the extraction. It does not say
whether a treatment works; that is the job of `treats` versus `evaluated_for`.
Use the whole scale. Registry fields are often explicit, but eligibility criteria,
inferred arms and implied phases are not.

| Tier | Range | When to Use |
|------|-------|-------------|
| Explicit | 0.9–1.0 | Directly stated with a clear citation (e.g. "NCT04303780", stated phase, named sponsor, listed primary endpoint) |
| Supported | 0.7–0.89 | Strongly supported by context but not directly stated |
| Inferred | 0.5–0.69 | Inferred from indirect evidence or background knowledge |
| Speculative | < 0.5 | Speculative; flag for review; do not use if NCT ID is absent and title is vague |

Mid-range examples:

- **0.85, `uses_biomarker`:** an inclusion criterion ("BMI ≥30 kg/m²") read as a
  selection biomarker. The criterion is explicit; treating it as a biomarker is an
  interpretation.
- **0.80, `enrolls`:** a Cohort inferred from an arm label ("Arm B") when the
  document does not describe the arm's population.
- **0.75, `evaluated_for`:** a Condition named only in the eligibility criteria,
  not in the title, summary or conditions list.
- **0.65, `is_phase`:** phase implied by design ("randomized, 72-week,
  event-driven") but not stated, or listed as "NA".
- **0.55, `targets`:** a mechanism mentioned only in the background section as
  prior knowledge.

## Quality Checks

Before returning your extraction, verify:

- Every Trial with an NCT ID in the source document MUST be captured as a Trial entity with name == NCT ID.
- Every named Compound MUST be captured as a Compound entity with the INN as canonical name.
- Every stated phase MUST produce an `is_phase` relation from the Trial to the matching TrialPhase.
- Every Sponsor named in the protocol MUST produce a `sponsored_by` relation from the Trial.
- Every Investigator MUST have a `has_investigator` relation from its Trial, and every Site a `conducted_at` relation; unlinked Investigator and Site entities are dropped at build.
- Every primary endpoint MUST produce a `has_outcome` relation.
- Biomarkers used for patient selection MUST appear as Biomarker entities and linked via `uses_biomarker`.
- Drug interventions MUST appear as BOTH a Compound entity AND an Intervention entity (the arm label), connected via a `tests` relation from the Trial.
- TrialPhase names MUST be normalized: use `Phase 1`, `Phase 2`, `Phase 2/3`, `Phase 3`, `Phase 4`, or `Observational` — never Roman numerals.
- No duplicate entities: if the same NCT ID appears multiple times, extract only one Trial entity.
- Protocol intent ("will evaluate", "to assess", "active comparator") produces `evaluated_for`, never `treats`.
- Comparator arms produce `compared_with`, never `co_intervention`.
- Condition names are canonical across the corpus (one name per disease).
- Missing NCT ID: if no NCT ID is found, set Trial confidence <= 0.6 and use the study acronym as the name with a note in context.
- Every dose-specific Intervention MUST link to its Compound via `contains_compound`.
- Every arm Cohort MUST link to what it receives via `receives`.
- Background or rescue medication uses `uses_background_drug`, never `tests`.
- Each distinct adverse event term is ONE AdverseEvent node with `reports_adverse_event` from the Trial and `observed_in` per arm; serious AEs carry `serious: true`; names follow Adverse Event Normalization and the source wording is kept in `reported_term`.
- Every Outcome that contains a recognised measure MUST link to its StandardOutcome via `measures`; StandardOutcome names are canonical across the corpus.
- An OutcomeAnalysis exists only when a result (estimate or p-value) is reported, and it carries `significant` and `direction`.
- Every OutcomeAnalysis MUST have `analyzes` to its Outcome, `compares` to each arm compared, and `assesses_effect_of` to the experimental treatment.
- StatisticalMethod names use the canonical spelling; multiple imputation is an attribute, not a node.
