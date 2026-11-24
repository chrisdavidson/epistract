---
name: epistract-epistemic
description: Analyze epistemic patterns (hypotheses, contradictions, conditional claims) in a built knowledge graph and produce a Super Domain claims layer
---

# Epistract Epistemic Analysis

Analyze a built knowledge graph for epistemic patterns — hypotheses, contradictions, conditional claims, negative results, and patent vs. paper epistemic signatures. Produces a `claims_layer.json` overlay complementing the existing community structure.

## Usage Guard

**If invoked with no arguments or with `--help`:** Display the following usage block verbatim and stop — do not run any pipeline steps.

```
Usage: /epistract:epistemic <output-dir>

Required:
  <output-dir>    Path to directory containing graph_data.json from a prior /epistract:ingest or /epistract:build run

Examples:
  /epistract:epistemic ./epistract-output
  /epistract:epistemic ./clinical-output
```

## Arguments

## Arguments
- `path` (required): Output directory containing `graph_data.json` (from a prior `/epistract-ingest` or `/epistract-build`)
- `--no-narrate` (optional): Skip the LLM analyst narrator and produce only the deterministic rule output. Use for offline runs, when no API key is available, or when you want byte-identical repeat runs.

## What This Does

This command runs **after** the graph is built (after `/epistract-ingest` or `/epistract-build`). It reads the assembled `graph_data.json` — where cross-document evidence is merged — and identifies five categories of epistemic facts:

1. **Hypothesized mechanisms** — clusters of hedged relations forming a conjecture
2. **Conflicting evidence** — same relation with opposing evidence from different sources
3. **Patent vs. paper signatures** — prophetic/claimed vs. empirically demonstrated
4. **Temporal state transitions** — evolving truth (pre-clinical → approved)
5. **Negative results** — high-confidence statements about absence

After the rule-based analysis, an automatic **analyst narrator** reads the domain persona (from `domains/<name>/workbench/template.yaml:persona`) plus the fresh `claims_layer.json` and produces `epistemic_narrative.md` — a structured briefing an analyst would write: prophetic claim landscape grouped by topic, contested claims with source IDs, coverage gaps, recommended follow-ups. The narrator is ADDITIVE — any failure (no API key, API error, domain has no persona) leaves `claims_layer.json` on disk as the authoritative rule output and prints a clear note to stderr.

## Pipeline

### Step 1: Run the epistemic analysis script

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/core/label_epistemic.py <output_dir>          # with narrator
python3 ${CLAUDE_PLUGIN_ROOT}/core/label_epistemic.py <output_dir> --no-narrate   # rule-only
```

This reads `graph_data.json` and produces:
- `claims_layer.json` — the Super Domain overlay (epistemic claims, contradictions, grouped hypotheses) — rule-based, deterministic. Stamped `"generator": "label_epistemic"`.
- `epistemic_narrative.md` — the analyst briefing — LLM-generated. Skipped when `--no-narrate` is passed, when no API credentials are set, or when the domain's `workbench/template.yaml` has no `persona` field.
- Updates `graph_data.json` nodes/links with `epistemic_status` field.

### Claims-layer authorship guard

`claims_layer.json` is a fixed filename and this step rewrites it — and
`graph_data.json` — unconditionally. Not every claims layer comes from here:
`core/crosswalk_output.py` renders one for a crosswalk graph, which no
extraction pipeline ever built and over which epistemic analysis is not
meaningful.

So the script **refuses to run** when the claims layer on disk carries a
`generator` stamp naming a different producer, exits 1 with a message naming
that producer, and writes nothing at all — the check runs before any analysis,
so `graph_data.json` is left untouched too.

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/core/label_epistemic.py <output_dir> --force   # overwrite anyway
```

A claims layer with **no** stamp is treated as this script's own output and
overwritten as before: every layer written before stamping existed came from
here, so ordinary re-runs on existing projects are unaffected.

If you hit this on a crosswalk directory, you almost certainly want
`/epistract:crosswalk` (or `python3 -m core.crosswalk_output render`) instead —
not `--force`, which discards the joins and cross-domain findings.

### Narrator credentials (same priority as workbench chat)

1. `EPISTRACT_LLM_PROVIDER` (`local`, `anthropic`, `openrouter` or `foundry`) — forces one provider and fails with an error when its credentials are missing.
2. `EPISTRACT_LLM_BASE_URL` — a local OpenAI-compatible server (llama.cpp, Ollama, vLLM, LM Studio). No key needed; optional `EPISTRACT_LLM_MODEL` and `EPISTRACT_LLM_API_KEY`. It wins over the cloud keys below, which are never sent to it.
3. `AZURE_FOUNDRY_API_KEY` (with `AZURE_FOUNDRY_BASE_URL` or `AZURE_FOUNDRY_RESOURCE`) — Azure AI Foundry or custom Anthropic gateway.
4. `ANTHROPIC_API_KEY` — direct Anthropic API.
5. `OPENROUTER_API_KEY` — OpenRouter (OpenAI-compatible).

The narrator asks for up to 8192 output tokens, capped by `EPISTRACT_LLM_MAX_TOKENS` and clamped to what is left of the model's context window after the prompt. When the prompt leaves under 512 tokens of room the narrator is skipped with an "exceeds context" reason and the rule-based output stands; use a larger-context model for the narrator. Check the setup with `python3 -m core.cli llm check`.

### Narrator persona — single source of truth

The narrator reads the `persona` field from `domains/<name>/workbench/template.yaml` — the SAME persona the workbench chat uses at runtime. Upgrade the persona once; both surfaces improve together. The epistemic-status vocabulary (`asserted` / `prophetic` / `hypothesized` / `contested` / `contradictions` / `negative`) should be called out explicitly in the persona so the narrator knows to use it.

### Step 2: Report Summary

Tell the user:
- Total relations analyzed
- Breakdown by epistemic status (asserted, hypothesized, speculative, prophetic, negative, conflicting)
- Named claims identified (grouped hypotheses)
- Contradictions detected (with evidence quotes from both sides)
- Patent vs. paper distribution
- How this complements the community structure
- Whether `epistemic_narrative.md` was produced (print the `narrative_status` value from the JSON output — `ok` / `no-persona` / `disabled` / `error: …`)

### clinicaltrials: registry contests

For the `clinicaltrials` domain, graphs enriched with `--results` get registry-aware contest detection on outcome analyses:

- **Contest key:** (measure, `outcome_kind`, treatment, dose). `outcome_kind` is `responder`, `continuous` or `time_to_event`, so a responder analysis and a continuous one on the same measure are not contested against each other. The kind comes from the registry measure `paramType` (`outcome_param_type` on the analysis: `COUNT_OF_PARTICIPANTS` is responder, `MEAN`, `LEAST_SQUARES_MEAN` and the geometric means are continuous) and `unitOfMeasure` first, then the measure title; a hazard-ratio effect measure is always time-to-event. The abbreviations HR, OR and RR count only in capitals, so the words "or" and "hr" in a free-text effect measure do not change the kind. "HR" in a title (heart rate) and a threshold that names a subgroup of a continuous measure do not change the kind, and a measured duration ("Time to Exhaustion") is not time-to-event. An analysis whose kind is unknown joins the one known kind of its measure and treatment; it stays separate only when two or more kinds are present.
- **Dose:** `dose_mg` is read from the compared arm titles. Thousands separators are read ("1,000 mg" is 1000 mg). A range ("12-45 mg", "0.25 to 1 mg") is not a single dose. Per-weight and concentration values ("10 mg/kg", "10-20 mg/kg", "0.5-5.0 mg/ml") are not doses, so "Semaglutide 1 mg (0.5-5.0 mg/ml)" is 1 mg. A range whose upper end is per-weight names no dose at either end ("10 mg - 20 mg/kg" names none). A whole label number before a dash or "to" is not the low end of a range ("Cohort 2 - 10 mg", "Group 1 to 4 mg" and "Week 4 - 2.4 mg" are 10 mg, 4 mg and 2.4 mg). A decimal is never a label number, and "treatment" and "regimen" are not label words, so titration ranges such as "Semaglutide treatment 0.25 to 2.4 mg" and "Titration regimen 5 to 10 mg" are ranges with no single dose. Also, a dose joined to a name by a hyphen is read ("Semaglutide-1 mg" is 1 mg). Dose is part of the key only when every finding in the contest carries one (`dose_aware: true`); otherwise the contest falls back to the dose-unaware key (`dose_aware: false`). A single finding without a dose is enough to make its whole group fall back.
- **Treatment precedence:** an `assesses_effect_of` edge first, then the registry arm types, then the arm and outcome titles.
- **Flags on findings:** `ambiguous_active_comparator` (no usable arm types, and an active comparator that cannot be told from the experimental arm), `label_conflict` (an extracted Cohort name that disagrees with its registry arm label on compound, dose or comparator status; the label is used for matching, and when the two name different doses the finding's `dose_mg` is null) and `registry_withdrawn` (the registry fact was withdrawn from the payload; it keeps its significance but is not corroboration, and its `ctgov:` document is not a support document).
- **Summary keys:** `analysis_treatment_from_arm_type`, `analysis_treatment_arm_type_disagreements`, `analysis_treatment_ambiguous_active_comparator`, `analysis_label_conflicts`, `analysis_registry_withdrawn`, `analysis_outcome_kind_counts`, `analysis_contests_dose_aware` and `analysis_contests_dose_fallback`.

Without registry data, the output is unchanged.

### Step 3: Suggest Next Steps

- Review contradictions manually (highest-value findings)
- Read `epistemic_narrative.md` for the analyst synthesis; open the same graph in `/epistract:dashboard` to chat with the SAME persona reactively
- Use `/epistract-query` to search within the claims layer
- Export with `/epistract-export` — `claims_layer.json` and `epistemic_narrative.md` are included in exports
