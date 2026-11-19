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
"""

from __future__ import annotations

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

# Relations that assert a drug or intervention works for a condition.
EFFICACY_RELATIONS = {"treats"}

# Protocol language describes what a trial will test, not what it showed.
PROTOCOL_INTENT_RE = re.compile(
    r"\b(evaluat\w*|assess\w*|investigat\w*|will (?:receive|be)|to (?:compare|determine|test)|"
    r"being (?:studied|tested)|under study|compar\w* (?:to|with|against)|active comparator)\b",
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
# Main epistemic analysis function
# ---------------------------------------------------------------------------


def analyze_clinicaltrials_epistemic(output_dir: Path, graph_data: dict) -> dict:
    """Run clinical-trial epistemic analysis on a built graph.

    Every non-bookkeeping relation is graded per mention: each mention's
    source document is traced to the Trial(s) it describes, and that trial's
    phase, blinding and enrollment set the mention's tier. The relation's
    tier is the best tier among its mentions. Contradictions and contested
    claims compare those per-source tiers inside one merged relation.

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

        unique_tiers = set(tiers)
        finding_base = {
            "source_entity": link.get("source"),
            "target_entity": link.get("target"),
            "relation_type": relation_type,
            "tiers": tiers,
            "sources": mention_tiers,
            # Standard fields read by core/epistemic_health.py
            "mentions": _link_mentions(link),
            "support_documents": [m["source_document"] for m in mention_tiers if m["source_document"]],
        }
        if "high_evidence" in unique_tiers and "low_evidence" in unique_tiers:
            contradictions.append(dict(finding_base))
        if "high_evidence" in unique_tiers and "medium_evidence" in unique_tiers:
            contested.append({**finding_base, "epistemic_status": "contested"})

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
            "hypothesized_found": len(hypothesized_links),
            # v3 standard key shared with drug-discovery (hypothesis groups).
            "hypotheses_found": len(hypotheses),
            "trials_with_phase": sum(1 for n in trial_lookup.values() if _trial_phase(n)),
            "trials_with_enrollment": sum(1 for n in trial_lookup.values() if _enrollment(n) is not None),
        },
        "base_domain": {
            "description": "High-evidence relations from Phase 3, randomized, or large-enrollment trials",
            "relation_count": evidence_counts.get("high_evidence", 0),
        },
        "super_domain": {
            "description": "Medium/low/unclassified-evidence relations — smaller trials, early phase, or unclassifiable",
            "relation_count": sum(v for k, v in evidence_counts.items() if k != "high_evidence"),
            "contradictions": contradictions,
            "contested_claims": contested,
            "hypotheses": hypotheses,
        },
    }
