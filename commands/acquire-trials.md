---
name: epistract-acquire-trials
description: Search ClinicalTrials.gov and download trial protocols into a local corpus for epistract ingestion
---

# Epistract ClinicalTrials.gov Acquisition

You are building a document corpus from ClinicalTrials.gov for the epistract knowledge graph pipeline.

## Arguments
- `condition` (required): Disease, condition, or keyword to search for (e.g. "KRAS G12C", "non-small cell lung cancer")
- `--status` (optional): Filter by trial status — RECRUITING, COMPLETED, ACTIVE_NOT_RECRUITING, etc. (default: no filter)
- `--phase` (optional): Filter by phase — PHASE1, PHASE2, PHASE3, PHASE4, EARLY_PHASE1 (default: no filter)
- `--max` (optional): Maximum trials to fetch (default: 20)
- `--output` (optional): Output directory (default: ./epistract-corpus)

## Pipeline Steps

### Step 1: Search ClinicalTrials.gov

Use WebFetch to query the ClinicalTrials.gov API v2:

```
GET https://clinicaltrials.gov/api/v2/studies?query.cond=<condition>&pageSize=<max>&format=json
```

Optional filters appended as query parameters:
- `filter.overallStatus=<status>` when `--status` is provided
- `filter.phase=<phase>` when `--phase` is provided

Request only the fields needed for extraction. A minimal field set that covers all text content:
```
fields=NCTId,BriefTitle,OfficialTitle,BriefSummary,DetailedDescription,Condition,Keyword,Phase,OverallStatus,StartDate,PrimaryCompletionDate,LeadSponsorName,InterventionName,InterventionType,InterventionDescription,PrimaryOutcomeMeasure,PrimaryOutcomeDescription,EligibilityCriteria,MinimumAge,MaximumAge
```

Respect ClinicalTrials.gov rate limits — if you receive a 429 response, wait briefly and retry.

### Step 2: Collect Trial Metadata

For each result, extract from the API response:
- NCT ID (`protocolSection.identificationModule.nctId`)
- Brief title (`protocolSection.identificationModule.briefTitle`)
- Official title (`protocolSection.identificationModule.officialTitle`)
- Brief summary (`protocolSection.descriptionModule.briefSummary`)
- Detailed description (`protocolSection.descriptionModule.detailedDescription`)
- Conditions (`protocolSection.conditionsModule.conditions`)
- Keywords (`protocolSection.conditionsModule.keywords`)
- Phase (`protocolSection.designModule.phases`)
- Overall status (`protocolSection.statusModule.overallStatus`)
- Start date (`protocolSection.statusModule.startDateStruct.date`)
- Primary completion date (`protocolSection.statusModule.primaryCompletionDateStruct.date`)
- Lead sponsor (`protocolSection.sponsorCollaboratorsModule.leadSponsor.name`)
- Interventions (`protocolSection.armsInterventionsModule.interventions` — name, type, description)
- Primary outcomes (`protocolSection.outcomesModule.primaryOutcomes` — measure, description)
- Eligibility criteria (`protocolSection.eligibilityModule.eligibilityCriteria`)
- Age range (`protocolSection.eligibilityModule.minimumAge`, `maximumAge`)

### Step 3: Deduplicate

Check the output directory for existing `nct_*.txt` files. Skip trials already in the corpus.

### Step 4: Write Corpus Files

Build a JSON array of trials and write them to disk:

```bash
echo '<trials_json>' | python3 ${CLAUDE_PLUGIN_ROOT}/scripts/write_clinicaltrials_doc.py <output_dir>
```

The JSON format expected by the script:
```json
{
  "trials": [
    {
      "nct_id": "NCT12345678",
      "brief_title": "...",
      "official_title": "...",
      "brief_summary": "...",
      "detailed_description": "...",
      "conditions": ["Non-Small Cell Lung Cancer"],
      "keywords": ["KRAS", "KRAS G12C"],
      "phase": ["PHASE2"],
      "status": "COMPLETED",
      "start_date": "2020-01",
      "primary_completion_date": "2022-06",
      "lead_sponsor": "Amgen",
      "interventions": [
        {"name": "sotorasib", "type": "DRUG", "description": "..."}
      ],
      "primary_outcomes": [
        {"measure": "Objective Response Rate", "description": "..."}
      ],
      "eligibility_criteria": "Inclusion Criteria:\n...\nExclusion Criteria:\n...",
      "minimum_age": "18 Years",
      "maximum_age": "N/A"
    }
  ]
}
```

**For 10+ trials:** Use the Agent tool to dispatch parallel trial-acquirer agents (batches of 5) for speed.

### Step 5: Enrich with Chemical Structures

For each trial written to disk, resolve intervention drug names to structural data via PubChem:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/enrich_structures.py <output_dir>
```

This appends a `CHEMICAL STRUCTURES:` section to each document containing the compound's IsomericSMILES, molecular formula, molecular weight, InChIKey, and PubChem CID. These are then found by the RDKit validation step during `/epistract-ingest`, enabling real structure-based enrichment rather than false positive pattern matches.

The script handles failures gracefully:
- Drug class terms (e.g. "GLP-1 receptor agonists") and placebos are skipped automatically
- Compounds not in PubChem are skipped without blocking the pipeline
- Documents already enriched are skipped on re-runs (idempotent)

### Step 6: Report Summary

Tell the user:
- Total trials found vs fetched
- Phase breakdown (Phase 1/2/3 counts)
- Status breakdown (Recruiting/Completed/Active counts)
- Duplicates skipped
- Top conditions and interventions across the corpus
- Output directory location
- Suggest next step: `/epistract-ingest <output_dir>` to build the knowledge graph

### Step 6: Offer Corpus Expansion

If the result set is small (<10 trials), suggest:
- Broader condition terms (e.g. "lung cancer" instead of "non-small cell lung cancer")
- Removing phase or status filters to widen the search
- Related intervention names or gene targets to search directly
