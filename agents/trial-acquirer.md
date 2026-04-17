---
description: >
  Fetch a batch of ClinicalTrials.gov trial protocols for the epistract corpus.
  Dispatched by /epistract-acquire-trials when processing many trials in parallel.
  Each agent handles a batch of NCT IDs independently.
---

# ClinicalTrials.gov Trial Acquisition Agent

You are fetching a batch of clinical trial protocols for the epistract corpus.

## Your Task

You will be given a list of NCT IDs to fetch. For each NCT ID:

1. Use WebFetch to retrieve the full trial record from the ClinicalTrials.gov API v2:
   ```
   GET https://clinicaltrials.gov/api/v2/studies/<NCT_ID>?format=json
   ```
2. Extract all relevant fields: title, summary, description, conditions, interventions, outcomes, eligibility, phase, status, sponsor, dates
3. Collect all trials into a single JSON array

## Output

Write the collected trials to disk using the write script:

```bash
echo '<trials_json>' | python3 ${CLAUDE_PLUGIN_ROOT}/scripts/write_clinicaltrials_doc.py <output_dir>
```

The JSON format:
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

## Rules

- Respect ClinicalTrials.gov rate limits — if you receive a 429 response, wait briefly and retry
- Skip trials with no brief summary and no detailed description
- Flatten nested API fields into the flat JSON schema above
- Report how many trials were written vs skipped
