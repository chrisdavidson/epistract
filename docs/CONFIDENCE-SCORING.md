# Confidence Scoring

How epistract produces, combines and interprets the `confidence` value on every entity and relation. This is the canonical technical reference. Customer-facing material should link here rather than restate the rules, so that the explanation changes in the same pull request as the code.

**Short answer:** each extracted fact carries a single score in `[0.0, 1.0]`. The extraction model assigns it, following calibration rules defined by the domain. Scores are combined when the same claim appears in several documents, and the epistemic layer reads them to assign a status label. The score is a calibrated judgment of how strongly the text supports the claim. It is **not** a statistical confidence interval, and it has not been validated against labeled ground truth.

---

## 1. Where the score is created: extraction

The only step that creates a score is extraction. The extractor agent reads a document chunk by chunk and writes, for every entity and relation, an exact supporting quote (`context` / `evidence`) and a `confidence` float.

The scale it follows comes from two layers:

| Layer             | File                                                             | What it defines                                                       |
| ----------------- | ---------------------------------------------------------------- | --------------------------------------------------------------------- |
| Framework default | `agents/extractor.md`                                            | 0.9+ explicit, 0.7–0.9 supported, 0.5–0.7 inferred, < 0.5 speculative |
| Domain rules      | `domains/<domain>/SKILL.md` and `domain.yaml` (`system_context`) | How this field's sources and evidence types map onto the scale        |

The domain layer is what makes scores meaningful within a field. Examples:

- **drug-discovery** (`SKILL.md`, *Confidence Calibration* and the document-type guidance that follows it): primary results with statistics 0.9–1.0; clear secondary findings 0.7–0.89; post-hoc analyses 0.5–0.7; preprints about 0.1 below the equivalent peer-reviewed finding; prophetic patent examples 0.3–0.5; patent claims 0.4–0.6; FDA-label indications 0.95+.
- **pharmacovigilance** (`SKILL.md` rule 11, `domain.yaml`): HCP report with positive dechallenge and rechallenge ≥ 0.9; single HCP report 0.7–0.89; detailed consumer report 0.5–0.69; lawyer-submitted without clinical detail < 0.5.
- **clinicaltrials** (`domain.yaml`): explicit with clear citation 0.9–1.0, strongly supported 0.7–0.89, inferred 0.5–0.69, speculative < 0.5; trials identified only by descriptive title capped at ≤ 0.6.
- **contracts**: no domain-specific calibration; uses the framework default scale.

A new domain can start on the default scale and add source-specific rules to its `SKILL.md` as it matures. See [ADDING-DOMAINS.md](ADDING-DOMAINS.md).

## 2. Normalization

`core/build_extraction.py` repairs score formats before validation:

- numeric strings are coerced (`"0.9"` → `0.9`);
- unparseable strings become `0.5`, the Pydantic default, so the record is recovered rather than dropped.

Valid numeric scores pass through unchanged.

## 3. Combining repeated mentions

**Relations.** When the same `(source, relation_type, target)` appears in more than one place, sift-kg's graph builder keeps every mention (document, score, quote) in the edge's `mentions` list and computes an aggregate `confidence`. Epistract uses the sift-kg default, `product_complement`:

```
confidence = 1 − ∏ (1 − cᵢ)
```

Each agreeing mention removes part of the remaining doubt, so agreement raises the score. `mean` and `max` are also supported by sift-kg (`confidence_aggregation`) but are not used by default. The edge also records `support_count`, `support_documents` and `support_doc_count`.

Worked example from `tests/corpora/06_glp1_landscape/output-v3/graph_data.json`: `tirzepatide INDICATED_FOR obesity` has six mentions scored 0.65, 0.95, 0.95, 0.93, 0.97 and 0.90, giving `1 − (0.35 × 0.05 × 0.05 × 0.07 × 0.03 × 0.10) = 0.99999981625`.

**Entities.** Within a document, `core/entity_resolution.py` merges repeated entities across chunks and keeps the **maximum** confidence.

## 4. Interpreting the score: epistemic status

Downstream steps **read** `confidence` and attach labels. They do not change the number.

- `core/label_epistemic.py` (`classify_epistemic_status`, drug-discovery and default path), applied per mention, first match wins:
  1. no evidence text: `asserted` if confidence ≥ 0.8, else `unclassified`;
  2. structural-biology paper with confidence ≥ 0.9: `asserted` (skips the hedging scan; see [known-limitations.md](known-limitations.md));
  3. hedging pattern in the evidence (for example "may", "suggests"): `hypothesized` / `speculative` per pattern;
  4. patent source with confidence < 0.9: `prophetic`;
  5. confidence < 0.5: `speculative`;
  6. otherwise: `asserted`.
- `core/hedging.py` (`score_relation`) computes a graded `hedge_score` from the evidence and maps it with confidence to a status: hedge ≥ 0.55 `speculative`, ≥ 0.25 `hypothesized`, confidence < 0.5 `hypothesized`, else `asserted`. An existing `superseded` status is preserved.
- Domain `epistemic.py` modules apply their own cut-offs. pharmacovigilance and fda-product-labels: ≥ 0.9 `asserted`, ≥ 0.7 `hypothesized`, else `unverified`. Domains generated by the wizard get `confidence_thresholds` (default high 0.9 / medium 0.7 / low 0.5) written into their generated `epistemic.py` (`core/domain_wizard.py`).
- **Human review queue:** relations below 0.7 are written to `relation_review.yaml` with a `flag_reason` such as `Low confidence (0.55 < 0.7)`.
- **Temporal supersession:** `core/epistemic_temporal.py` uses confidence only as a tie-breaker when two conflicting claims have the same timestamp.

## 5. Independent second opinion (optional)

`core/triple_judge.py` (via `/epistract:enhance`) re-scores each relation against its evidence span, using a lexical judge offline or an LLM judge when configured. It writes separate fields (`judge_verdict`, `judge_score`, `judge_reason`, `gated`) and leaves `confidence` untouched. A relation with `judge_score < 0.35` (default) is marked `gated`.

## 6. Consumers

- `epistract export --format okf --min-confidence F` omits relations below `F` from Relations tables ([OKF-MAPPING.md](OKF-MAPPING.md)).
- The workbench and epistemic health report surface the lowest and highest-confidence statements when the same claim is scored differently across sources (`core/epistemic_health.py`).

## 7. Limitations

- **Not a probability.** Scores are model judgments guided by written rules. They have not been calibrated against expert-labeled data, so 0.8 does not mean "correct 80% of the time." Calibration per domain is the natural next step.
- **Saturation.** With several agreeing mentions, `product_complement` approaches 1.0 quickly (the six-source example above reaches 0.9999998). Differences past the third decimal are not meaningful; `support_doc_count` is the more informative figure.
- **Independence assumption.** `product_complement` treats mentions as independent. Several reviews restating one primary study can overstate support.
- **Mention-level vs. edge-level labels.** Status labels are assigned per mention and per edge by different modules; an edge can be `asserted` overall while individual mentions were `prophetic` or `hypothesized`. Read the `mentions` list for the full picture.
- **Source scoring depends on the extractor following the rules.** Spot checks of `mentions` evidence are still worthwhile; for example, MeSH-term-only evidence can receive high scores.
