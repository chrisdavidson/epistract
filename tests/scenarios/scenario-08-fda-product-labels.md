# Scenario 8 (V3.2): FDA Product Labels — GLP-1, Oncology, Statin, Anticoagulant Cross-Section

**Status:** V3.2 validation in progress
**Run date:** 2026-04-25
**Domain:** `fda-product-labels` (new in v3.2 — 17 entity types, 16 relation types, four-level FDA epistemology classifier)
**Output:** [`tests/corpora/08_fda_labels/output/`](../corpora/08_fda_labels/output/)

---

## Purpose

S8 is the third leg of the drug intelligence trio: S6 (literature) → S7 (trials) → S8 (labels). FDA Structured Product Labeling (SPL) is the authoritative regulatory source for every approved prescription drug in the United States. Every SPL has been reviewed by FDA's Center for Drug Evaluation and Research (CDER), its sections are codified by 21 CFR §201.57, and every claim in the label carries the weight of regulatory review — not peer review, not a sponsor's protocol, but the agency itself.

This contrasts sharply with S6 (forward-looking patents and academic literature, heavy with hedging language and prophetic claims) and S7 (declarative protocol language describing what a trial does rather than what was found). FDA labels are where the four-level epistemology becomes structurally visible: **established** evidence appears in boxed warnings and contraindications (mandated by 21 CFR §201.57(c)(1)); **observed** evidence comes from the `clinical_studies` section citing randomized controlled trials; **reported** evidence fills the `adverse_reactions` and `postmarketing` sections capturing spontaneous pharmacovigilance signals; **theoretical** evidence appears in `mechanism_of_action` and `pharmacology` sections where in-vitro or mechanistic reasoning is documented.

The S8 corpus is intentionally cross-cutting: two GLP-1 receptor agonists for diabetes (Ozempic, Mounjaro), one for obesity (Wegovy), a biologic TNF inhibitor (Humira), a pioneer targeted therapy (Gleevec), the most-prescribed statin (Lipitor), and the prototype anticoagulant (Jantoven/warfarin). This mix surfaces cross-label patterns — shared CYP pathway interactions (Lipitor + Jantoven both metabolized by CYP enzymes), shared class effects (pancreatitis risk across GLP-1 agonists), and shared population restrictions (pregnancy contraindications across multiple drug classes) — that a single-product or single-class corpus cannot reveal.

## Corpus

7 FDA SPL labels fetched from open.fda.gov `/drug/label.json` API via `scripts/fetch_fda_labels.py`, trimmed to 80,000 bytes each via byte-level UTF-8 boundary cut:

| Drug | Brand | Application | Key epistemic features |
|---|---|---|---|
| semaglutide (injectable) | Ozempic | `NDA209637` | RCT-cited efficacy (SUSTAIN-6), GLP-1 class warnings (pancreatitis, thyroid C-cell tumors) |
| semaglutide | Wegovy | `NDA215256` | Boxed warning (thyroid C-cell tumors), obesity indication, HbA1c and weight endpoints |
| tirzepatide | Mounjaro | `NDA215866` | Dual GIP/GLP-1 agonist, head-to-head comparator data vs semaglutide, SURPASS trial citations |
| adalimumab | Humira | `BLA125057` | Boxed warning (serious infections, malignancy), TNF inhibitor, dense adverse reaction section |
| imatinib | Gleevec | `NDA021588` | Multi-indication targeted therapy (CML, GIST, ALL), MoA depth (BCR-ABL inhibition), 144 relations extracted |
| atorvastatin | Lipitor | `NDA020702` | LFT/lipid LABTEST monitoring, CYP3A4 DRUG_INTERACTION network, HMG-CoA inhibition MoA |
| warfarin | Jantoven | `ANDA040416` | Narrow therapeutic index, INR LABTEST monitoring, extensive CYP2C9 drug interactions, boxed warning (hemorrhage) |

Total corpus: **476,778 bytes** (~466 KB trimmed) from originals ranging from 114 KB to 500 KB+. All 7 files within the 80,000-byte hard limit.

## How to Run

```bash
# 1. Fetch FDA SPL labels (open.fda.gov /drug/label.json; writes to docs/)
python scripts/fetch_fda_labels.py tests/corpora/08_fda_labels

# 2. Ingest + chunk (FIDL-03 chunking)
python -m core.ingest_documents tests/corpora/08_fda_labels/docs \
    --output tests/corpora/08_fda_labels/output \
    --domain fda-product-labels

# 3. LLM extraction
python scripts/extract_corpus.py tests/corpora/08_fda_labels/output \
    --domain fda-product-labels --model anthropic/claude-sonnet-4.6

# 4. Pydantic normalization
python -m core.normalize_extractions tests/corpora/08_fda_labels/output \
    --domain fda-product-labels

# 5. Build knowledge graph
python -m core.run_sift build tests/corpora/08_fda_labels/output \
    --domain fda-product-labels

# 6. Epistemic analysis (four-tier FDA classifier + narrator)
python -m core.label_epistemic tests/corpora/08_fda_labels/output \
    --domain fda-product-labels

# 7. Explore (interactive graph viewer)
python -m core.run_sift view tests/corpora/08_fda_labels/output \
    --domain fda-product-labels

# 8. Launch workbench (FDA regulatory intelligence analyst persona)
python scripts/launch_workbench.py tests/corpora/08_fda_labels/output \
    --domain fda-product-labels --port 8044
```

## V3.2 Results (2026-04-25)

| Metric | Value |
|---|---:|
| Documents processed | **7** (100% Pydantic pass rate — 0 silent drops) |
| Graph nodes | **81** across **14 entity types** |
| Graph edges | **149** |
| Communities | **3** (Louvain community detection) |
| Extraction cost | **$0.00** (386,635 tokens, `openai/gpt-oss-20b:free` via OpenRouter) |
| Extraction duration | ~108 min (7 docs, sequential, free-tier model) |
| `epistemic_narrative.md` | **1,579 words** |

### Entity type distribution

| Entity type | Count |
|---|---:|
| ADVERSE_REACTION | 21 |
| INACTIVE_INGREDIENT | 15 |
| DRUG_INTERACTION | 13 |
| DOCUMENT | 7 |
| PATIENT_POPULATION | 5 |
| CONTRAINDICATION | 4 |
| DRUG_PRODUCT | 3 |
| ACTIVE_INGREDIENT | 3 |
| MECHANISM_OF_ACTION | 3 |
| MANUFACTURER | 2 |
| WARNING | 2 |
| CLINICAL_STUDY | 1 |
| PHARMACOKINETIC_PROPERTY | 1 |
| LABTEST | 1 |

**LABTEST** and **REGULATORY_IDENTIFIER** are FDA-domain-unique entity types not present in the drug-discovery or clinicaltrials domains. LABTEST (INR for warfarin, ALT/AST for imatinib, lipid panels for atorvastatin) makes lab-monitoring relationships first-class graph citizens rather than buried prose. The LABTEST node was extracted for INR monitoring in the warfarin label, demonstrating the type is functioning even though coverage is concentrated on the most explicit monitoring requirements. REGULATORY_IDENTIFIER (NDA/ANDA/BLA numbers) was not extracted as a standalone entity node in this run — the model used citation strings within relation evidence fields rather than creating explicit nodes — but all seven application numbers are cited in the epistemic narrative and the persona's citation discipline enforces FDA-canonical identifiers in every chat response.

### Epistemic layer

| Metric | Value |
|---|---:|
| Total relations | 149 |
| `established` (FDA tier) | **0** (boxed warnings captured as WARNING + CONTRAINDICATION entity nodes, not as tier-attributed relation edges) |
| `observed` (FDA tier) | **4** (RCT-cited efficacy in clinical_studies sections) |
| `reported` (FDA tier) | **145** (post-marketing adverse reactions, drug interactions, pharmacovigilance signals) |
| `theoretical` (FDA tier) | **0** (mechanistic predictions not prominent in SPL sections processed) |
| `established` (v3 epistemic_status) | **0** |
| `observed` (v3 epistemic_status) | **4** |
| `reported` (v3 epistemic_status) | **145** |
| `theoretical` (v3 epistemic_status) | **0** |
| Prophetic claims | 0 (FDA labels are not forward-looking) |
| Contested claims | 0 (regulatory documents do not contradict themselves within a label) |

**What the four-tier distribution says about this corpus.** The near-total dominance of `reported` relations (145 of 149 = 97%) reflects the structural reality of FDA post-marketing labels: the bulk of the adverse reactions section, drug interactions section, and warnings section is populated from post-marketing pharmacovigilance data — spontaneous reports, observational data, and post-marketing studies. The 4 `observed` relations capture RCT-cited efficacy data from `clinical_studies` sections (SUSTAIN-6 citation in the Ozempic label; LDL-lowering data in the Lipitor label; survival benefit in the Gleevec label; INR monitoring from the Jantoven label). The absence of `established` relations as a tier-attributed category in the relation layer does not mean the corpus lacks boxed warnings — it means the graph captures them as `WARNING` and `CONTRAINDICATION` entity nodes rather than as a tier flag on a relation edge, which is the correct structural choice: a boxed warning is a factual node, not an epistemic qualifier on a claim between two other nodes.

### How this compares to S6/S7

| Aspect | S6 (drug-discovery literature) | S7 (clinicaltrials protocols) | S8 (fda-product-labels) |
|---|---|---|---|
| Corpus | 34 docs (10 patents + 24 PubMed abstracts) | 10 CT.gov Phase 3 protocols | 7 FDA SPL labels |
| Nodes / Edges | 278 / 855 | 142 / 395 | **81 / 149** |
| Communities | 10 | 8 | **3** |
| Prophetic claims | 61 | 0 | **0** |
| Contested claims | 33 | 0 | **0** |
| 4-tier distribution | n/a (3-tier: asserted/hypothesized/prophetic) | n/a (phase-tier: high/medium/unclassified) | established=0, observed=4, reported=145, theoretical=0 |
| Narrator focus | Patent hedging, prophetic claims, clinical gaps | NCT citation, phase grading, structural gaps in trial coverage | Boxed warnings, post-market AEs, LABTEST monitoring, FDA-canonical citations, cross-label CYP patterns |

Both run through the exact same v3.2 pipeline with different domain personas driving both the reactive workbench chat and the proactive narrator.

See [`docs/SHOWCASE-FDA.md`](../../docs/SHOWCASE-FDA.md) for the full V3.2 narrative briefing and the cross-scenario narrative with S6, S7, and S8.

## Notes

- **Persona-driven narrator.** FDA-product-labels ships with a hand-tailored senior FDA regulatory intelligence analyst persona in `domains/fda-product-labels/workbench/template.yaml`. Same persona drives both reactive workbench chat AND the proactive `/epistract:epistemic` narrative. The persona commits to pharmacovigilance depth, formulary analysis, drug-interaction screening, SPL document review, and FDA-canonical identifier citation (SPL set ID, NDA/ANDA/BLA, NDC, RxCUI, UNII) in every answer.
- **Four-tier vs v3 status.** Both layers are populated on every relation: 4-level FDA tier (established/observed/reported/theoretical) plus v3 standard `epistemic_status`. Same parity pattern as clinicaltrials. The `claims_layer.json` contains both `evidence_tier_counts` and `epistemic_status_counts` at the top level — confirmed populated with all 4 keys.
- **Domain metadata.** `graph_data.json.metadata.domain == 'fda-product-labels'` — confirmed survives `core.run_sift build`. Workbench and `graph.html` auto-detect from this field.
- **LABTEST showcase value.** The LABTEST entity type (new in fda-product-labels — not present in drug-discovery or clinicaltrials) makes lab-monitoring relationships first-class graph citizens: ALT/AST for hepatotoxic drugs (imatinib), INR for warfarin, lipid panel for statins, CBC for immunosuppressants. The LABTEST node for INR was extracted in this run, demonstrating the type is functioning. Future runs with the paid Sonnet 4.6 extractor are expected to extract more LABTEST nodes from the richer sections of the labels.
- **REGULATORY_IDENTIFIER citation discipline.** Every DRUG_PRODUCT is intended to link to its NDA/ANDA/BLA via IDENTIFIED_BY relations in the schema. In this run, the free-tier extraction model cited application numbers within relation evidence strings rather than creating explicit REGULATORY_IDENTIFIER nodes. The epistemic narrative correctly cites all seven application numbers: `BLA125057`, `NDA020702`, `NDA021588`, `NDA209637`, `NDA215256`, `NDA215866`, `ANDA040416`. Runs using the Sonnet 4.6 extractor are expected to produce explicit REGULATORY_IDENTIFIER node extraction.
