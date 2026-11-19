"""Clinical-trials epistemic analysis — phase-based evidence grading.

Called by core/label_epistemic.py's convention-based dispatcher:
- Domain slug "clinicaltrials" -> function name "analyze_clinicaltrials_epistemic"
  (derived via slug.replace("-", "_")).
- Returns a claims_layer dict with the standard {metadata, summary,
  base_domain, super_domain} envelope consumed by /epistract-epistemic.

Evidence grading rules:
1. Phase III trials -> high_evidence
2. Phase II -> medium_evidence
3. Phase I or observational -> low_evidence
4. Blinded trials bump up one tier. Blinding comes from the registry
   (ct_masking SINGLE/DOUBLE/TRIPLE/QUADRUPLE, set by enrich.py); when the
   registry is silent, randomized / blinded / placebo-controlled wording in
   the evidence quote is used instead.
5. Large enrollment (>=300) bumps up one tier; small (<50) bumps down
6. Open-label trials (ct_masking NONE, or "open-label" in the evidence when
   the registry is silent) are capped at medium_evidence, after the
   enrollment bump, so size cannot buy back the missing blinding.
7. OutcomeAnalysis nodes are graded from their reported significance (the
   significant flag, then the p-value, then the confidence interval against
   the null), tiered by their trial, and recorded as asserted, negative or
   unresolved. One StandardOutcome + Compound pair with significant and
   non-significant analyses from DIFFERENT trials is contested; a split
   inside one trial (primary vs subgroup) is not. Ratio measures are
   recognised by pattern (aHR, "Hazard Ratio (HR)"); an unknown measure
   decides only when the ratio and difference nulls agree.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from pathlib import Path


# ---------------------------------------------------------------------------
# Phase classification constants
# ---------------------------------------------------------------------------

PHASE3_VALUES = {"PHASE3", "Phase 3", "Phase III", "PHASE_3"}
PHASE2_VALUES = {"PHASE2", "Phase 2", "Phase II", "PHASE_2"}
PHASE1_VALUES = {"PHASE1", "Phase 1", "Phase I", "PHASE_1"}
OBSERVATIONAL_VALUES = {"OBSERVATIONAL", "Observational"}

BLINDING_RE = re.compile(
    r"\b(randomi[sz]ed|double[- ]blind|single[- ]blind|placebo[- ]controlled)\b",
    re.IGNORECASE,
)

EVIDENCE_TIERS = ("low_evidence", "medium_evidence", "high_evidence")

OPEN_LABEL_RE = re.compile(
    r"\b(open[- ]label|unblinded|non[- ]blinded|no masking)\b",
    re.IGNORECASE,
)

# CT.gov v2 designInfo.maskingInfo.masking values
BLINDED_MASKING = {"SINGLE", "DOUBLE", "TRIPLE", "QUADRUPLE"}
OPEN_MASKING = {"NONE", "OPEN", "OPEN_LABEL", "OPEN LABEL"}
OPEN_LABEL_CAP = "medium_evidence"

# Provenance links written by the graph builder; not claims.
MENTIONED_IN = "MENTIONED_IN"

# Relations and types that tie an OutcomeAnalysis to its outcome, treatment and trial.
ANALYSIS_TYPE = "outcomeanalysis"
ANALYZES = "analyzes"
MEASURES = "measures"
ASSESSES = "assesses_effect_of"
CONTAINS = "contains_compound"
COMPARES = "compares"

# Effect measures whose null value is 1.0 (ratios); every other measure is
# a difference with a null of 0.
RATIO_MEASURES = {
    "hr", "or", "rr", "irr", "hazard ratio", "odds ratio", "risk ratio",
    "relative risk", "rate ratio", "incidence rate ratio",
}
# Measure labels are free text ("aHR", "Hazard Ratio (HR)", "Cox HR"), so they
# are classified by pattern, not exact name.
_RATIO_MEASURE_RE = re.compile(r"ratio|\b(?:a|adj\.?\s*)?(?:hr|or|rr|irr|sir)\b", re.IGNORECASE)
_DIFFERENCE_MEASURE_RE = re.compile(
    r"differen|\betd\b|\bmd\b|\blsm|least[- ]squares|mean change|\bchange\b|\bdelta\b",
    re.IGNORECASE,
)
# Reported "not significant" without a number.
_NOT_SIGNIFICANT_RE = re.compile(r"^\s*(?:p\s*)?(?:n\.?\s*s\.?|not\s+(?:statistically\s+)?significant)\s*$", re.IGNORECASE)
SIGNIFICANCE_LEVEL = 0.05

_P_VALUE_RE = re.compile(
    r"^\s*p?\s*(<=|>=|\u2264|\u2265|<|>|=)?\s*(\d*\.?\d+(?:e[-+]?\d+)?)\s*$",
    re.IGNORECASE,
)

# Relations that assert a drug or intervention works for a condition.
EFFICACY_RELATIONS = {"treats"}

# Protocol language describes what a trial will test, not what it showed.
PROTOCOL_INTENT_RE = re.compile(
    r"\b(evaluat\w*|assess\w*|investigat\w*|will (?:receive|be)|to (?:compare|determine|test)|"
    r"being (?:studied|tested)|under study|compar\w* (?:to|with|against)|active comparator)\b",
    re.IGNORECASE,
)

# Language that reports a null or negative observed result.
NEGATIVE_RESULT_RE = re.compile(
    r"\b(did not (?:meet|reach|achieve|show|demonstrate|reduce|improve)|failed to|"
    r"no (?:significant|statistically significant) (?:difference|effect|reduction|improvement)|"
    r"not (?:statistically )?significant|was not superior|not non-?inferior)\b",
    re.IGNORECASE,
)

# Language that reports an observed result rather than intent.
RESULT_RE = re.compile(
    r"\b(reduced|improved|demonstrated|showed|resulted in|significantly|superior|non-?inferior|"
    r"approved for|indicated for|hazard ratio|p\s*[<=])",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _trial_phase(node: dict) -> str | None:
    """Return normalized phase ('PHASE3'|'PHASE2'|'PHASE1'|'OBSERVATIONAL') or None.

    Reads node['ct_phase'] first (set by enrich.py in Plan 21-02), then falls
    back to node['attributes']['phase'] if present.
    """
    # Check ct_phase attribute first (set by enrichment)
    ct_phase = node.get("ct_phase")
    if ct_phase:
        if ct_phase in PHASE3_VALUES:
            return "PHASE3"
        if ct_phase in PHASE2_VALUES:
            return "PHASE2"
        if ct_phase in PHASE1_VALUES:
            return "PHASE1"
        if ct_phase in OBSERVATIONAL_VALUES:
            return "OBSERVATIONAL"

    # Fallback to attributes dict
    attrs = node.get("attributes", {}) or {}
    phase = attrs.get("phase", "")
    if phase:
        if phase in PHASE3_VALUES:
            return "PHASE3"
        if phase in PHASE2_VALUES:
            return "PHASE2"
        if phase in PHASE1_VALUES:
            return "PHASE1"
        if phase in OBSERVATIONAL_VALUES:
            return "OBSERVATIONAL"

    return None


def _enrollment(node: dict) -> int | None:
    """Return enrollment count from Trial node — ct_enrollment or attributes.enrollment."""
    # Check ct_enrollment first (set by enrichment)
    ct_enrollment = node.get("ct_enrollment")
    if ct_enrollment is not None:
        try:
            return int(ct_enrollment)
        except (ValueError, TypeError):
            pass

    # Fallback to attributes dict
    attrs = node.get("attributes", {}) or {}
    enrollment = attrs.get("enrollment")
    if enrollment is not None:
        try:
            return int(enrollment)
        except (ValueError, TypeError):
            pass

    return None


def _bump_tier(tier: str, delta: int) -> str:
    """Move tier up (+1) or down (-1) within EVIDENCE_TIERS; clamp at endpoints.

    Input 'unclassified' returns unchanged.
    """
    if tier == "unclassified":
        return "unclassified"
    try:
        idx = EVIDENCE_TIERS.index(tier)
    except ValueError:
        return "unclassified"
    new_idx = max(0, min(len(EVIDENCE_TIERS) - 1, idx + delta))
    return EVIDENCE_TIERS[new_idx]


def _trial_blinding(node: dict) -> str | None:
    """Return 'blinded', 'open', or None from registry masking on a Trial node.

    Reads ct_masking (set by enrich.py) first, then attributes.masking.
    """
    attrs = node.get("attributes", {}) or {}
    value = node.get("ct_masking") or attrs.get("masking")
    if not value:
        return None
    masking = str(value).strip().upper().replace("-", "_")
    if masking in OPEN_MASKING or "OPEN" in masking:
        return "open"
    if masking in BLINDED_MASKING or "BLIND" in masking:
        return "blinded"
    return None


def _grade_trial(trial_node: dict, evidence_text: str) -> str:
    """Return the evidence tier one trial lends to one piece of evidence.

    Apply phase -> blinding -> enrollment bumps in that order, then cap
    open-label trials at medium_evidence.
    """
    # Step 1: Determine starting tier from trial phase
    phase = _trial_phase(trial_node)
    if phase == "PHASE3":
        tier = "high_evidence"
    elif phase == "PHASE2":
        tier = "medium_evidence"
    else:
        # Phase 1, observational, or no phase info — start at low
        tier = "low_evidence"

    # Step 2: Apply blinding bump. Registry masking wins; the evidence
    # quote is only a fallback when the registry says nothing.
    blinding = _trial_blinding(trial_node)
    if blinding is None and OPEN_LABEL_RE.search(evidence_text or ""):
        blinding = "open"
    if blinding == "blinded" or (blinding is None and BLINDING_RE.search(evidence_text or "")):
        tier = _bump_tier(tier, +1)

    # Step 3: Apply enrollment bump
    enrollment = _enrollment(trial_node)
    if enrollment is not None:
        if enrollment >= 300:
            tier = _bump_tier(tier, +1)
        elif enrollment < 50:
            tier = _bump_tier(tier, -1)

    # Step 4: Open-label cap, applied last so enrollment cannot undo it.
    if blinding == "open" and tier in EVIDENCE_TIERS:
        cap = EVIDENCE_TIERS.index(OPEN_LABEL_CAP)
        if EVIDENCE_TIERS.index(tier) > cap:
            tier = OPEN_LABEL_CAP

    return tier


def _grade_relation(link: dict, trial_lookup: dict) -> str:
    """Return evidence tier for one relation that touches a Trial node.

    If no connected Trial node is found, return 'unclassified'. Kept for
    callers that grade a single link; analyze_clinicaltrials_epistemic grades
    per mention so links between non-trial entities can be graded too.
    """
    trial_node = trial_lookup.get(link.get("source", "")) or trial_lookup.get(link.get("target", ""))
    if trial_node is None:
        return "unclassified"
    return _grade_trial(trial_node, link.get("evidence", "") or "")


def _best_tier(tiers: list[str]) -> str:
    """Highest evidence tier in the list; 'unclassified' if none are graded."""
    graded = [t for t in tiers if t in EVIDENCE_TIERS]
    if not graded:
        return "unclassified"
    return max(graded, key=EVIDENCE_TIERS.index)


def _link_mentions(link: dict) -> list[dict]:
    """Per-source mentions of a merged link, or the link itself if unmerged."""
    mentions = link.get("mentions")
    if mentions:
        return mentions
    return [{
        "source_document": link.get("source_document", ""),
        "evidence": link.get("evidence", ""),
        "confidence": link.get("confidence"),
    }]


def _doc_trial_map(links: list[dict], trial_lookup: dict) -> dict[str, list[str]]:
    """Map document id (without 'doc:' prefix) -> Trial node ids it mentions.

    Built from the Trial MENTIONED_IN Document links the graph builder writes,
    so a mention's source_document can be traced back to its trial even when
    the relation itself does not touch a Trial node (e.g. Compound treats
    Condition).
    """
    doc_trials: dict[str, list[str]] = defaultdict(list)
    for link in links:
        if link.get("relation_type") != MENTIONED_IN:
            continue
        source = link.get("source", "")
        if source in trial_lookup:
            doc_id = str(link.get("target", "")).removeprefix("doc:")
            if source not in doc_trials[doc_id]:
                doc_trials[doc_id].append(source)
    return doc_trials


def _confidence(link: dict) -> float:
    """Link confidence, defaulting to 0.8 only when missing or null.

    An explicit 0.0 is a real score and must stay 0.0 (it previously
    became 0.8 through a falsy `or` default and was labeled asserted).
    """
    value = link.get("confidence")
    if value is None:
        return 0.8
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.8


# ---------------------------------------------------------------------------
# OutcomeAnalysis grading
# ---------------------------------------------------------------------------


def _number(value) -> float | None:
    """Finite float from an int or float; None for bools, NaN, inf and strings."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value):
        return None
    return float(value)


def _parse_p_value(value) -> tuple[str, float] | None:
    """Parse a p-value into (comparator, number), or None when unparseable.

    Accepts a number or text such as "<0.001", "p = 0.03" or "\u22640.05". The
    comparator is one of "<", "<=", "=", ">", ">=".
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = _number(value)
        return ("=", number) if number is not None else None
    if not isinstance(value, str):
        return None
    if _NOT_SIGNIFICANT_RE.match(value):
        return (">=", SIGNIFICANCE_LEVEL)
    # Tolerate decimal commas ("0,03") and footnote markers ("<0.05*").
    value = value.replace(",", ".").rstrip("*\u2020\u2021 ")
    match = _P_VALUE_RE.match(value)
    if not match:
        return None
    comparator = {"\u2264": "<=", "\u2265": ">="}.get(match.group(1), match.group(1) or "=")
    try:
        number = float(match.group(2))
    except ValueError:
        return None
    if not math.isfinite(number) or not 0.0 <= number <= 1.0:
        return None
    return comparator, number


def _p_significance(parsed: tuple[str, float] | None) -> bool | None:
    """Significance implied by a parsed p-value; None when the bound is undecidable."""
    if parsed is None:
        return None
    comparator, number = parsed
    if comparator == "=":
        return number < SIGNIFICANCE_LEVEL
    if comparator in ("<", "<="):
        return True if number <= SIGNIFICANCE_LEVEL else None
    if comparator in (">", ">="):
        return False if number >= SIGNIFICANCE_LEVEL else None
    return None


def _analysis_significance(node: dict) -> bool | None:
    """Whether an OutcomeAnalysis node reports a statistically significant result.

    Precedence: a bool `significant` attribute, then the parsed `p_value` text
    (it keeps its comparator; "NS" reads as not significant), then a
    `p_value_num` in [0, 1], then the confidence interval against the null
    (1.0 for ratio measures, 0 for differences; an unknown measure decides
    only when both nulls agree). Returns None when nothing decides it.
    """
    attrs = node.get("attributes")
    if not isinstance(attrs, dict):
        return None
    flag = attrs.get("significant")
    if isinstance(flag, bool):
        return flag

    # The reported text keeps its comparator ("<0.05"), so it decides first;
    # p_value_num is the fallback and must be a probability.
    decided = _p_significance(_parse_p_value(attrs.get("p_value")))
    if decided is not None:
        return decided
    p_num = _number(attrs.get("p_value_num"))
    if p_num is not None and 0.0 <= p_num <= 1.0:
        return p_num < SIGNIFICANCE_LEVEL

    lower = _number(attrs.get("ci_lower"))
    upper = _number(attrs.get("ci_upper"))
    if lower is not None and upper is not None:
        ratio = _is_ratio_measure(attrs.get("effect_measure"))
        if ratio is None and lower <= 0.0:
            ratio = False  # ratios are strictly positive, so this is a difference
        excludes_ratio_null = lower > 1.0 or upper < 1.0
        excludes_diff_null = lower > 0.0 or upper < 0.0
        if ratio is True:
            return excludes_ratio_null
        if ratio is False:
            return excludes_diff_null
        # Unknown measure: decide only when both readings agree.
        return excludes_ratio_null if excludes_ratio_null == excludes_diff_null else None
    return None


def _is_ratio_measure(measure) -> bool | None:
    """True for ratio measures (null 1), False for differences (null 0), None if unknown."""
    text = str(measure or "").strip().lower()
    if not text:
        return None
    if text in RATIO_MEASURES or _RATIO_MEASURE_RE.search(text):
        return True
    if _DIFFERENCE_MEASURE_RE.search(text):
        return False
    return None


def _analysis_findings(
    nodes: list[dict], links: list[dict], trial_lookup: dict, doc_trials: dict
) -> list[dict]:
    """Grade every OutcomeAnalysis node into one finding dict.

    The outcome, treatment and trial are resolved through the graph's edges
    in either direction, so a reversed edge still resolves.
    """
    by_id = {n["id"]: n for n in nodes if "id" in n}
    adjacency: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for link in links:
        relation = link.get("relation_type")
        if relation == MENTIONED_IN:
            continue
        source, target = link.get("source"), link.get("target")
        adjacency[source].append((relation, target))
        adjacency[target].append((relation, source))

    def etype(node_id) -> str:
        return str((by_id.get(node_id) or {}).get("entity_type", "")).lower()

    def related(node_id, relation: str, entity_type: str) -> list[str]:
        return sorted({
            other for rel, other in adjacency.get(node_id, ())
            if rel == relation and etype(other) == entity_type and other in by_id
        })

    def name_of(node_id) -> str | None:
        node = by_id.get(node_id)
        return str(node.get("name") or node_id) if node else None

    findings: list[dict] = []
    for node in nodes:
        if str(node.get("entity_type", "")).lower() != ANALYSIS_TYPE:
            continue
        node_id = node.get("id")
        attrs = node.get("attributes") if isinstance(node.get("attributes"), dict) else {}

        # Outcome -> StandardOutcome
        outcomes = related(node_id, ANALYZES, "outcome")
        standard_outcome = standard_outcome_id = None
        if outcomes:
            standards = related(outcomes[0], MEASURES, "standardoutcome")
            standard_outcome_id = standards[0] if standards else outcomes[0]
            standard_outcome = name_of(standard_outcome_id)

        # Treatment: a Compound, or an Intervention resolved to its Compound
        treatment_id = None
        compounds = related(node_id, ASSESSES, "compound")
        if compounds:
            treatment_id = compounds[0]
        else:
            interventions = related(node_id, ASSESSES, "intervention")
            if interventions:
                contained = related(interventions[0], CONTAINS, "compound")
                treatment_id = contained[0] if contained else interventions[0]
        treatment = name_of(treatment_id) if treatment_id else None

        # Trial: a direct edge first, else the trials of the source documents
        candidates = sorted({
            other for rel, other in adjacency.get(node_id, ()) if other in trial_lookup
        })
        if not candidates:
            seen: set[str] = set()
            for doc in node.get("source_documents") or []:
                for trial_id in doc_trials.get(str(doc).removeprefix("doc:"), []):
                    seen.add(trial_id)
            candidates = sorted(seen)
        context = node.get("context") or ""
        # No resolvable trial: same "unclassified" tier the per-link grading uses.
        trial_id, tier = None, "unclassified"
        best = -1
        for candidate in candidates:
            graded = _grade_trial(trial_lookup[candidate], context)
            rank = EVIDENCE_TIERS.index(graded) if graded in EVIDENCE_TIERS else -1
            if rank > best:
                trial_id, tier, best = candidate, graded, rank
        if trial_id is not None and tier not in EVIDENCE_TIERS:
            tier = "low_evidence"

        significant = _analysis_significance(node)
        p_value = attrs.get("p_value")
        if p_value is None:
            p_value = attrs.get("p_value_num")
        findings.append({
            "analysis": node_id,
            "analysis_name": node.get("name"),
            "trial": trial_id,
            "trial_name": name_of(trial_id) if trial_id else None,
            "standard_outcome": standard_outcome,
            "standard_outcome_id": standard_outcome_id,
            "treatment": treatment,
            "treatment_id": treatment_id,
            "significant": significant,
            "direction": attrs.get("direction"),
            "p_value": p_value,
            "effect_estimate": attrs.get("effect_estimate"),
            "evidence_tier": tier,
            "support_documents": [str(d) for d in node.get("source_documents") or []],
            "basis": "outcome_analysis",
            "epistemic_status": (
                "asserted" if significant is True
                else "negative" if significant is False
                else "unresolved"
            ),
        })
    return findings


def _analysis_contests(findings: list[dict]) -> tuple[list[dict], list[dict]]:
    """Find StandardOutcome + treatment pairs whose analyses disagree on significance.

    Returns (contested, contradictions). A contested entry is also a
    contradiction when both sides include a high_evidence analysis.
    """
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for finding in findings:
        if finding["significant"] is None:
            continue
        if finding["standard_outcome"] is None or finding["treatment"] is None:
            continue
        key = (str(finding["standard_outcome"]).lower(), str(finding["treatment"]).lower())
        groups[key].append(finding)

    contested: list[dict] = []
    contradictions: list[dict] = []
    for _key, group in sorted(groups.items()):
        positive = [f for f in group if f["significant"] is True]
        negative = [f for f in group if f["significant"] is False]
        if not positive or not negative:
            continue
        # Cross-trial only: a split inside one trial (e.g. primary vs subgroup
        # analysis) is not a contest between sources.
        if not any(
            p["trial"] and n["trial"] and p["trial"] != n["trial"]
            for p in positive for n in negative
        ):
            continue
        docs = sorted({d for f in group for d in f.get("support_documents") or []})
        positive_tiers = [f["evidence_tier"] for f in positive]
        negative_tiers = [f["evidence_tier"] for f in negative]
        entry = {
            "standard_outcome": group[0]["standard_outcome"],
            "treatment": group[0]["treatment"],
            "positive": sorted(f["analysis"] for f in positive),
            "negative": sorted(f["analysis"] for f in negative),
            "positive_tiers": positive_tiers,
            "negative_tiers": negative_tiers,
            "trials": sorted({f["trial"] for f in group if f["trial"] is not None}),
            "basis": "outcome_analysis",
            # Standard fields read by core/epistemic_health.py
            "source": group[0].get("treatment_id"),
            "target": group[0].get("standard_outcome_id"),
            "source_entity": group[0].get("treatment_id"),
            "target_entity": group[0].get("standard_outcome_id"),
            "relation_type": ASSESSES,
            "mentions": [{"source_document": d} for d in docs],
            "support_documents": docs,
        }
        contested.append({**entry, "epistemic_status": "contested"})
        if "high_evidence" in positive_tiers and "high_evidence" in negative_tiers:
            contradictions.append({**entry, "epistemic_status": "contradiction"})
    return contested, contradictions


# ---------------------------------------------------------------------------
# Main epistemic analysis function
# ---------------------------------------------------------------------------


def analyze_clinicaltrials_epistemic(output_dir: Path, graph_data: dict) -> dict:
    """Run clinical-trial epistemic analysis on a built graph.

    Every non-bookkeeping relation is graded per mention: each mention's
    source document is traced to the Trial(s) it describes, and that trial's
    phase, blinding and enrollment set the mention's tier. The relation's
    tier is the best tier among its mentions.

    Inside one merged relation, the per-source findings are compared:
    - mixed_tier: sources of different evidence tiers support the claim
      (e.g. double-blind and open-label trials). The sources agree.
    - contested: one source reports an effect and another reports none.
    - contradictions: contested claims where both sides have a
      high_evidence source.

    OutcomeAnalysis nodes are graded separately from their reported
    significance (see _analysis_significance). They add the summary keys
    analysis_claims_found, analysis_graded and analysis_contested_found, the
    findings in base_domain.analysis_claims, and cross-trial contested /
    contradiction entries with basis "outcome_analysis".

    MENTIONED_IN links are provenance bookkeeping, not claims: they are not
    graded, labeled, or counted.

    Args:
        output_dir: directory containing graph_data.json (used for metadata paths only).
        graph_data: parsed graph_data.json dict with 'nodes' and 'links'.

    Returns:
        claims_layer dict with keys: metadata, summary, base_domain, super_domain.
    """
    nodes = graph_data.get("nodes", [])
    links = graph_data.get("links", [])

    # Build Trial lookup (accept both capitalized 'Trial' and upper 'TRIAL')
    trial_lookup: dict[str, dict] = {
        n["id"]: n for n in nodes
        if str(n.get("entity_type", "")).lower() == "trial"
    }
    doc_trials = _doc_trial_map(links, trial_lookup)
    names = {n["id"]: str(n.get("name") or n["id"]) for n in nodes if "id" in n}

    evidence_counts: dict[str, int] = defaultdict(int)
    status_counts: dict[str, int] = defaultdict(int)
    # Reuse the core epistemic-status classifier so narrator + workbench chat
    # see the same vocabulary (asserted / hypothesized / prophetic / etc.) as
    # drug-discovery and contracts. Trial-protocol evidence defaults to
    # "paper" doc_type since CT.gov protocols are not patents.
    try:
        from core.label_epistemic import classify_epistemic_status
        _HAVE_CLASSIFIER = True
    except ImportError:
        _HAVE_CLASSIFIER = False

    hypothesized_links: list[dict] = []
    contradictions: list[dict] = []
    contested: list[dict] = []
    mixed_tier: list[dict] = []
    claim_count = 0

    for link in links:
        relation_type = link.get("relation_type")
        if relation_type == MENTIONED_IN:
            continue
        claim_count += 1

        # --- Evidence tier, graded per mention -------------------------------
        direct_trial = trial_lookup.get(link.get("source", "")) or trial_lookup.get(link.get("target", ""))
        mention_tiers: list[dict] = []
        for mention in _link_mentions(link):
            evidence = mention.get("evidence", "") or ""
            doc_id = str(mention.get("source_document", "") or "")
            if direct_trial is not None:
                trials = [direct_trial]
            else:
                trials = [trial_lookup[t] for t in doc_trials.get(doc_id, [])]
            tier = _best_tier([_grade_trial(t, evidence) for t in trials])
            mention_tiers.append({"source_document": doc_id, "tier": tier})

        tiers = [m["tier"] for m in mention_tiers]
        link_tier = _best_tier(tiers)
        link["evidence_tier"] = link_tier
        link["mention_evidence_tiers"] = mention_tiers
        evidence_counts[link_tier] += 1

        finding_base = {
            # source/target are what core/epistemic_health.py reads;
            # source_entity/target_entity are kept for existing consumers.
            "source": link.get("source"),
            "target": link.get("target"),
            "source_entity": link.get("source"),
            "target_entity": link.get("target"),
            "relation_type": relation_type,
            "tiers": tiers,
            "sources": mention_tiers,
            # Standard fields read by core/epistemic_health.py
            "mentions": _link_mentions(link),
            "support_documents": [m["source_document"] for m in mention_tiers if m["source_document"]],
        }

        # Mixed tier: the sources agree but differ in design rigor (for
        # example double-blind and open-label trials behind one claim).
        graded = {t for t in tiers if t in EVIDENCE_TIERS}
        if len(graded) > 1:
            link["evidence_mix"] = "mixed_tier"
            mixed_tier.append({
                **finding_base,
                "epistemic_status": "mixed_tier",
                "tier_spread": [t for t in EVIDENCE_TIERS if t in graded],
            })

        # Contested: the sources disagree about the result itself — one
        # reports an effect, another reports none. A contradiction is a
        # contested claim where both sides include high_evidence sources.
        positive_tiers, negative_tiers = [], []
        for mention, mt in zip(_link_mentions(link), mention_tiers):
            evidence = mention.get("evidence", "") or ""
            if NEGATIVE_RESULT_RE.search(evidence):
                negative_tiers.append(mt["tier"])
            elif RESULT_RE.search(evidence):
                positive_tiers.append(mt["tier"])
        if positive_tiers and negative_tiers:
            result_split = {
                **finding_base,
                "positive_tiers": positive_tiers,
                "negative_tiers": negative_tiers,
            }
            contested.append({**result_split, "epistemic_status": "contested"})
            if "high_evidence" in positive_tiers and "high_evidence" in negative_tiers:
                contradictions.append({**result_split, "epistemic_status": "contradiction"})

        # --- Epistemic status ---------------------------------------------------
        if _HAVE_CLASSIFIER:
            evidence = link.get("evidence", "") or ""
            confidence = _confidence(link)
            # doc_type for trial protocols: "paper" (not patent).
            status = classify_epistemic_status(evidence, confidence, "paper")
            # A protocol says what a trial will test, not what works. A
            # treats claim supported only by intent language ("evaluated",
            # "will receive", "to assess") is a hypothesis under test.
            if relation_type in EFFICACY_RELATIONS and status == "asserted":
                mention_evidence = [m.get("evidence", "") or "" for m in _link_mentions(link)]
                if mention_evidence and all(
                    PROTOCOL_INTENT_RE.search(e) and not RESULT_RE.search(e)
                    for e in mention_evidence
                ):
                    status = "hypothesized"
                    link["status_reason"] = "efficacy claim supported only by protocol intent language"
            link["epistemic_status"] = status
            status_counts[status] += 1
            if status in ("hypothesized", "speculative"):
                hypothesized_links.append(link)

    # --- OutcomeAnalysis claims ---------------------------------------------
    analysis_claims = _analysis_findings(nodes, links, trial_lookup, doc_trials)
    analysis_contested, analysis_contradictions = _analysis_contests(analysis_claims)
    contested.extend(analysis_contested)
    contradictions.extend(analysis_contradictions)
    # Kept separate from epistemic_status_counts: the analysis edges are already
    # counted there by the per-link loop, so merging would double count.
    analysis_status_counts: dict[str, int] = defaultdict(int)
    for finding in analysis_claims:
        analysis_status_counts[finding["epistemic_status"]] += 1

    # Same envelope as the drug-discovery hypothesis groups (label,
    # member_entities, support_documents) so the health report and narrator
    # render them; one group per hypothesized relation.
    hypotheses = [
        {
            "label": " ".join([
                names.get(link.get("source"), str(link.get("source"))),
                str(link.get("relation_type", "")).replace("_", " "),
                names.get(link.get("target"), str(link.get("target"))),
            ]),
            "member_entities": [link.get("source"), link.get("target")],
            "support_documents": [
                str(m.get("source_document", "")) for m in _link_mentions(link) if m.get("source_document")
            ],
            "source_entity": link.get("source"),
            "target_entity": link.get("target"),
            "relation_type": link.get("relation_type"),
            "confidence": link.get("confidence"),
            "evidence_tier": link.get("evidence_tier"),
            "reason": link.get("status_reason", "hedged or low-confidence evidence"),
        }
        for link in hypothesized_links
    ]

    return {
        "metadata": {
            "description": "Clinical-trial epistemic layer — phase-based evidence grading",
            "domain": "clinicaltrials",
            "generated_from": str(output_dir / "graph_data.json"),
            "total_relations": claim_count,
            "trial_count": len(trial_lookup),
        },
        "summary": {
            "evidence_tier_counts": dict(evidence_counts),
            # v3 standard key — enables narrator + workbench chat parity across domains.
            "epistemic_status_counts": dict(status_counts),
            "contradictions_found": len(contradictions),
            "contested_found": len(contested),
            "mixed_tier_found": len(mixed_tier),
            "hypothesized_found": len(hypothesized_links),
            # v3 standard key shared with drug-discovery (hypothesis groups).
            "hypotheses_found": len(hypotheses),
            "trials_with_phase": sum(1 for n in trial_lookup.values() if _trial_phase(n)),
            "trials_with_enrollment": sum(1 for n in trial_lookup.values() if _enrollment(n) is not None),
            "analysis_claims_found": len(analysis_claims),
            "analysis_graded": sum(1 for f in analysis_claims if f["significant"] is not None),
            "analysis_contested_found": len(analysis_contested),
            "analysis_status_counts": dict(analysis_status_counts),
        },
        "base_domain": {
            "description": "High-evidence relations from Phase 3, randomized, or large-enrollment trials",
            "relation_count": evidence_counts.get("high_evidence", 0),
            "analysis_claims": analysis_claims,
        },
        "super_domain": {
            "description": "Medium/low/unclassified-evidence relations — smaller trials, early phase, or unclassifiable",
            "relation_count": sum(v for k, v in evidence_counts.items() if k != "high_evidence"),
            "contradictions": contradictions,
            "contested_claims": contested,
            "mixed_tier_claims": mixed_tier,
            "hypotheses": hypotheses,
        },
    }
