"""Clinical-trials epistemic analysis — phase-based evidence grading.

Called by core/label_epistemic.py's convention-based dispatcher:
- Domain slug "clinicaltrials" -> function name "analyze_clinicaltrials_epistemic"
  (derived via slug.replace("-", "_")).
- Returns a claims_layer dict with the standard {metadata, summary,
  base_domain, super_domain} envelope consumed by /epistract-epistemic.

Evidence grading rules:
1. Phase III trials -> high_evidence. Phase comes from the registry ct_phase,
   then the extracted attributes.phase, then the TrialPhase node linked by
   is_phase, each normalized (3a/3b -> 3, roman numerals, 2/3 -> 2, NA ignored).
2. Phase II -> medium_evidence
3. Phase I or observational -> low_evidence
4. Blinded trials bump up one tier. Blinding comes from the registry
   (ct_masking SINGLE/DOUBLE/TRIPLE/QUADRUPLE, set by enrich.py), then
   attributes.masking (only when it carries masking vocabulary), then strict
   design/allocation text (double-blind, masked; open-label wins). When all
   of those are silent, randomized / blinded / placebo-controlled wording in
   the evidence quote is used instead.
5. Large enrollment (>=300) bumps up one tier; small (<50) bumps down
6. Open-label trials (ct_masking NONE, open-label design text, or
   "open-label" in the evidence when nothing else is stated) are capped at medium_evidence, after the
   enrollment bump, so size cannot buy back the missing blinding.
7. OutcomeAnalysis nodes are graded from their reported significance (the
   significant flag, then the p-value, then the confidence interval against
   the null), tiered by their trial, and recorded as asserted, negative or
   unresolved. One StandardOutcome + Compound pair with significant and
   non-significant analyses from DIFFERENT trials is contested; a split
   inside one trial (primary vs subgroup) is not. Ratio measures are
   recognised by pattern (aHR, "Hazard Ratio (HR)"); an unknown measure
   decides only when the ratio and difference nulls agree. With registry data
   the contest key also carries the outcome kind (responder, continuous,
   time-to-event) so a responder analysis never contests a continuous one, and
   the dose (mg) when every analysis of the group names one, so different doses
   of one drug in different trials do not contest each other; a group missing a
   dose keeps the dose-free key and its entry says dose_aware: false.

With registry data a treatment resolves from an assesses_effect_of edge, then
the registry arm types (add-on background compounds dropped), then the Cohort
/ group-title rule; an active-comparator set with no comparator keyword stays
unresolved and is marked ambiguous_active_comparator, and a Cohort whose name
conflicts with its registry arm_label is matched on the label
(label_conflict). Registry facts withdrawn by a refresh (ctgov_withdrawn,
ctgov_withdrawn_by_nct) are not corroboration: no ctgov: support document, no
registry statistics, no supersession and no part in contests.

Precedence, for both phase and blinding: registry ct_* fields > extracted
attributes > graph-derived (linked TrialPhase, design text) > per-claim
evidence text.
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

# Strict design-text patterns for blinding. Unlike BLINDING_RE they exclude
# "randomised" and "placebo-controlled", which are not blinding evidence.
DESIGN_OPEN_RE = re.compile(
    r"\b(open[- ]label|unblinded|non[- ]blinded|no masking)\b",
    re.IGNORECASE,
)
DESIGN_BLINDED_RE = re.compile(
    r"\b((single|double|triple|quadruple)[- ]?(blind(ed)?|mask(ed)?)|masked|blinded)\b",
    re.IGNORECASE,
)

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
RECEIVES = "receives"
HAS_OUTCOME = "has_outcome"

# Provenance tag Phase 7 registry import writes on nodes it creates or merges into.
REGISTRY_SOURCE = "ctgov_results"
# Statistic groups merged as a unit by the registry import: when an extracted
# value exists in a group, the registry values of that group are stored beside
# it as registry_<key> instead of being filled in.
ANALYSIS_P_GROUP = ("p_value", "p_value_num", "p_value_qualifier")
ANALYSIS_CI_GROUP = (
    "effect_estimate", "effect_measure", "ci_lower", "ci_upper", "ci_level", "ci_sides",
)
# Significance source of a finding nothing decided.
NO_SOURCE = "none"
# Comparator arms are told apart by name; arm_type is not a signal because
# active arms carry "Active comparator". The registry armGroup type
# (ctgov_arm_groups) is used only by the registry-mode treatment fallback
# (_arm_type_treatment) and never to classify a Cohort as placebo. A hard keyword always marks a
# comparator arm ("Semaglutide placebo 0.5 mg"). A soft keyword
# (standard of care, usual care, control) marks one when it stands outside
# parentheses with no Compound of the graph joined to it ("Usual care",
# "Standard of care (metformin)"), or when it sits in a parenthetical
# ("Insulin glargine (control)"). A Compound joined to a soft keyword by an
# add-on connector, in either order, makes an active add-on arm whose
# treatment is that compound ("Semaglutide 2.4 mg with usual care",
# "Usual care + semaglutide 0.5 mg"). "control" qualified by what is
# controlled ("glycaemic control", "weight control") is no keyword at all.
HARD_PLACEBO_KEYWORDS = ("placebo", "comparator")
SOFT_PLACEBO_KEYWORDS = ("standard of care", "usual care", "control")


def _keyword_re(words) -> re.Pattern:
    return re.compile(
        r"(?<![A-Za-z0-9])(?:" + "|".join(re.escape(k) for k in words) + r")(?![A-Za-z0-9])",
        re.IGNORECASE,
    )


_HARD_PLACEBO_RE = _keyword_re(HARD_PLACEBO_KEYWORDS)
_SOFT_PLACEBO_RE = _keyword_re(SOFT_PLACEBO_KEYWORDS)
_ADD_ON_RE = re.compile(
    r"\+|(?<![A-Za-z0-9])(?:plus|with|and|added to|add-on to|on top of|in addition to)(?![A-Za-z0-9])",
    re.IGNORECASE,
)
# A word naming what "control" controls; "glycaemic control" names no arm.
_CONTROL_QUALIFIER_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:glyc\w*|glucose|weight|pressure|metabolic|lipids?|sugar|appetite|"
    r"diabet\w*|disease|symptoms?|pain|rate|rhythm|infection)[\s-]+$",
    re.IGNORECASE,
)
# Registry non_inferiority_type values that make an analysis a
# non-inferiority or equivalence test (NON_INFERIORITY, EQUIVALENCE,
# NON_INFERIORITY_OR_EQUIVALENCE). SUPERIORITY, SUPERIORITY_OR_OTHER and
# OTHER are superiority-or-unspecified tests and are graded as efficacy.
_NON_INFERIORITY_RE = re.compile(r"NON[_\s-]?INFERIORITY|EQUIVALENCE", re.IGNORECASE)
MIN_COMPOUND_NAME = 3
# CT.gov armGroup types (attribute ctgov_arm_groups of a registry analysis).
ARM_EXPERIMENTAL = "EXPERIMENTAL"
ARM_COMPARATOR_TYPES = frozenset({
    "ACTIVE_COMPARATOR", "PLACEBO_COMPARATOR", "SHAM_COMPARATOR", "NO_INTERVENTION",
})
# "Drug: Tirzepatide" -> "Tirzepatide" (CT.gov intervention names carry the type).
_INTERVENTION_PREFIX_RE = re.compile(
    r"^\s*(?:Drug|Biological|Combination Product|Other|Dietary Supplement|Device|"
    r"Procedure|Behavioral|Genetic|Radiation|Diagnostic Test)\s*:\s*",
    re.IGNORECASE,
)
NCT_RE = re.compile(r"NCT\d{8}", re.IGNORECASE)

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
# A registry p text with a trailing word qualifier and no further number
# ("0.21 (ANCOVA)", "<0.001 two-sided"); "0.5 x 10-3" does not match.
_LEADING_P_VALUE_RE = re.compile(
    r"^\s*p?\s*(<=|>=|\u2264|\u2265|<|>|=)?\s*(\d*\.?\d+(?:e[-+]?\d+)?)"
    r"\s*[(\[,;:]?\s*(?![xX](?![A-Za-z]))[A-Za-z][^\d]*$",
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


_ROMAN = {"i": 1, "ii": 2, "iii": 3}
_PHASE_NAMES = {1: "PHASE1", 2: "PHASE2", 3: "PHASE3"}
_PHASE_TOKEN_RE = re.compile(r"^(?:phase)?(\d|iii|ii|i)[ab]?(?:/(\d|iii|ii|i)[ab]?)?$")


def _normalize_phase(value) -> str | None:
    """Return 'PHASE3'|'PHASE2'|'PHASE1'|'OBSERVATIONAL' for a phase label, else None.

    Accepts the registry spellings plus free text: case and separator
    variants ("phase_3"), 3a/3b suffixes, roman numerals. A combined phase
    ("2/3", "II/III") maps to the lower phase. NA, Phase 4 and anything
    unrecognised return None.
    """
    if not isinstance(value, str):
        return None
    if value in PHASE3_VALUES:
        return "PHASE3"
    if value in PHASE2_VALUES:
        return "PHASE2"
    if value in PHASE1_VALUES:
        return "PHASE1"
    if value in OBSERVATIONAL_VALUES:
        return "OBSERVATIONAL"
    text = re.sub(r"[\s_-]+", "", value.strip().lower())
    if not text or text in {"na", "n/a", "notapplicable"}:
        return None
    if text == "observational":
        return "OBSERVATIONAL"
    match = _PHASE_TOKEN_RE.match(text)
    if not match:
        return None
    numbers = []
    for token in match.groups():
        if token is None:
            continue
        numbers.append(_ROMAN.get(token) or int(token))
    return _PHASE_NAMES.get(min(numbers))


def _trial_phase(node: dict) -> str | None:
    """Return normalized phase ('PHASE3'|'PHASE2'|'PHASE1'|'OBSERVATIONAL') or None.

    Precedence: registry ct_phase, then attributes.phase, then the phase of
    the TrialPhase node linked by is_phase (carried as _linked_phase on the
    analyzer's trial copies). The first value that normalizes wins, so an
    "NA" in attributes falls through to the linked node.
    """
    attrs = node.get("attributes") or {}
    if not isinstance(attrs, dict):
        attrs = {}
    for raw in (node.get("ct_phase"), attrs.get("phase"), node.get("_linked_phase")):
        phase = _normalize_phase(raw)
        if phase:
            return phase
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


def _masking_verdict(value) -> str | None:
    """Classify one registry-style masking value as 'open', 'blinded' or None."""
    if not value:
        return None
    masking = str(value).strip().upper().replace("-", "_")
    if masking in OPEN_MASKING or "OPEN" in masking:
        return "open"
    if masking in BLINDED_MASKING or "BLIND" in masking:
        return "blinded"
    return None


def _trial_blinding(node: dict) -> str | None:
    """Return 'blinded', 'open', or None from what the Trial node itself states.

    Precedence: ct_masking (set by enrich.py), then attributes.masking when it
    carries masking vocabulary (a value like "Placebo-controlled" is treated
    as absent), then strict design/allocation text where open-label wins over
    "assessors masked". Randomised or placebo-controlled alone is not evidence.
    """
    attrs = node.get("attributes") or {}
    if not isinstance(attrs, dict):
        attrs = {}
    verdict = _masking_verdict(node.get("ct_masking"))
    if verdict:
        return verdict
    verdict = _masking_verdict(attrs.get("masking"))
    if verdict:
        return verdict
    text = " ".join(
        v for v in (attrs.get("design"), attrs.get("allocation")) if isinstance(v, str)
    )
    if DESIGN_OPEN_RE.search(text):
        return "open"
    if DESIGN_BLINDED_RE.search(text):
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


def _has_registry_provenance(attrs) -> bool:
    """True for a node created by, or merged with, the registry import.

    This only says the registry import touched the node. It is what decides
    whether a graph is in registry mode; whether the node still counts as
    registry corroboration is _is_registry_backed.
    """
    if not isinstance(attrs, dict):
        return False
    if attrs.get("source") == REGISTRY_SOURCE:
        return True
    sources = attrs.get("sources")
    return isinstance(sources, list) and REGISTRY_SOURCE in sources


def _withdrawn_ncts(attrs) -> set[str]:
    """NCT ids marked withdrawn in ctgov_withdrawn_by_nct (upper case)."""
    marks = attrs.get("ctgov_withdrawn_by_nct") if isinstance(attrs, dict) else None
    if not isinstance(marks, dict):
        return set()
    return {str(k).strip().upper() for k, v in marks.items() if v is True}


def _is_withdrawn(attrs) -> bool:
    """True when the registry withdrew its support for a node's facts.

    The node is flagged ctgov_withdrawn, or every NCT it records is marked
    withdrawn in ctgov_withdrawn_by_nct. A node some NCT still supports is not
    withdrawn. WR-02 follow-up: a withdrawn fact is not corroboration.
    """
    if not isinstance(attrs, dict):
        return False
    if attrs.get("ctgov_withdrawn") is True:
        return True
    ids = attrs.get("ctgov_nct_ids")
    if isinstance(ids, list) and ids:
        withdrawn = _withdrawn_ncts(attrs)
        return all(str(i).strip().upper() in withdrawn for i in ids)
    return False


def _is_registry_backed(attrs) -> bool:
    """True for a node the registry import created or merged into, whose
    registry support has not been withdrawn (see _is_withdrawn).

    Withdrawn registry facts are not corroboration: they are not registry
    statistics, add no ctgov: support documents, supersede nothing and take
    no part in contests. Registry-mode detection uses _has_registry_provenance
    instead, so a graph whose only registry facts are withdrawn stays in
    registry mode.
    """
    return _has_registry_provenance(attrs) and not _is_withdrawn(attrs)


_QUALIFIERS = {"<": "<", "<=": "<=", "≤": "<=", ">": ">", ">=": ">=", "≥": ">=", "=": "="}


def _significance_from_view(view: dict, use_qualifier: bool = False) -> bool | None:
    """Decide significance from p / CI statistics alone (no `significant` flag).

    The reported p text keeps its comparator ("<0.05"), so it decides first;
    p_value_num is the fallback and must be a probability. With use_qualifier
    (registry statistics) p_value_num is read with its p_value_qualifier, so
    a registry "<" 0.05 is significant and ">" 0.01 does not decide. Then the
    confidence interval against the null (1.0 for ratio measures, 0 for
    differences; an unknown measure decides only when both nulls agree).
    """
    decided = _p_significance(_parse_p_value(view.get("p_value")))
    if decided is not None:
        return decided
    p_num = _number(view.get("p_value_num"))
    if p_num is not None and 0.0 <= p_num <= 1.0:
        qualifier = view.get("p_value_qualifier")
        qualifier = _QUALIFIERS.get(qualifier.strip()) if isinstance(qualifier, str) else None
        if use_qualifier and qualifier is not None:
            decided = _p_significance((qualifier, p_num))
            if decided is not None:
                return decided
        else:
            return p_num < SIGNIFICANCE_LEVEL

    lower = _number(view.get("ci_lower"))
    upper = _number(view.get("ci_upper"))
    if lower is not None and upper is not None:
        ratio = _is_ratio_measure(view.get("effect_measure"))
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


def _non_inferiority_type(attrs: dict) -> str | None:
    """The registry non_inferiority_type of a non-inferiority or equivalence
    analysis, else None. The registry value of a merged node comes first."""
    for key in ("registry_non_inferiority_type", "non_inferiority_type"):
        value = attrs.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip() if _NON_INFERIORITY_RE.search(value) else None
    return None


def _registry_group_view(attrs: dict, group: tuple) -> dict | None:
    """The registry side of one statistic group on a merged node, or None.

    Present only when the registry import stored at least one registry_<key>
    of the group. For a group the extracted node already had, the import
    stores a registry value as registry_<key> only when it differs from the
    plain one, and stores nothing when the registry value is absent. A plain
    field with no registry_<key> twin therefore holds either the registry's
    equal value or a value the registry did not report. It completes the
    view only where it cannot be the second kind:
    - p: the registry p_value_num and qualifier are parsed from its p_value
      text, so beside a registry_p_value text they are never taken from the
      plain fields; a registry text the strict parser rejects is read by its
      leading number when only a word qualifier follows ("0.21 (ANCOVA)"),
      else it does not decide. A stored number or qualifier without
      registry_p_value means the texts were equal, so the plain text completes
      it when it parses to that number.
    - CI: a bound is borrowed only when the registry stored neither bound
      (both bounds are then the registry's, equal to the plain ones). A single
      registry bound leaves the interval registry-incomplete (its partner may
      be "NA" in the registry); a one-sided registry interval reports one
      bound by design. Neither decides.
    """
    view = {
        k: attrs[f"registry_{k}"] for k in group if attrs.get(f"registry_{k}") is not None
    }
    if not view:
        return None
    stored = set(view)
    sides = view.get("ci_sides", attrs.get("ci_sides"))
    one_sided = isinstance(sides, str) and "ONE" in sides.upper()
    registry_bound = "ci_lower" in stored or "ci_upper" in stored
    if "p_value" in stored and "p_value_num" not in stored and _parse_p_value(view["p_value"]) is None:
        lead = _LEADING_P_VALUE_RE.match(str(view["p_value"]))
        if lead is not None:
            view["p_value_num"] = float(lead.group(2))
            view.setdefault("p_value_qualifier", lead.group(1) or "=")
    for k in group:
        if k in view or attrs.get(k) is None:
            continue
        if (one_sided or registry_bound) and k in ("ci_lower", "ci_upper"):
            continue
        if "p_value" in stored and k in ("p_value_num", "p_value_qualifier"):
            continue
        if k == "p_value" and "p_value_num" in view:
            # Equal texts parse to the same number; a plain text that does
            # not is not the registry's and is never read beside its number.
            parsed = _parse_p_value(attrs[k])
            if parsed is None or parsed[1] != _number(view["p_value_num"]):
                continue
        view[k] = attrs[k]
    return view


def _plain_group_view(attrs: dict, group: tuple) -> dict | None:
    """The plain attributes of one statistic group, or None when it has none."""
    view = {k: attrs[k] for k in group if attrs.get(k) is not None}
    return view or None


def _analysis_significance_with_source(node: dict) -> tuple[bool | None, str]:
    """(significance, source) of an OutcomeAnalysis node.

    source is "ctgov_results" when registry statistics decided (or, on a node
    the registry import created, its own flag), "extracted" when extracted
    values decided, and "none" when nothing decided. A withdrawn registry fact
    (see _is_withdrawn) is no registry statistic: a registry node keeps its
    significance with source "ctgov_withdrawn", and a merged node is graded in
    the non-registry order below with source "extracted", ignoring its
    registry_<key> values. The plain values the registry import filled into a
    group the extracted node lacked carry no marker, so on a withdrawn merged
    node they cannot be told from extracted ones and are graded as extracted.

    On a merged node (sources include "ctgov_results") the registry
    statistics win over an extracted `significant` flag. The registry import
    fills a group the extracted node lacked entirely into the plain
    attributes, and stores registry_<key> for differing values of a group the
    extracted node had. A group carrying registry_<key> values is
    unambiguously registry data and is read first (see _registry_group_view).
    Only then is a group with no registry_<key> read from its plain values,
    which are the registry's (filled in or equal) and graded as registry
    statistics. (When the registry reported nothing for a group the extracted
    node had, its values are read the same way; the import leaves no marker
    to tell them apart.) A node that is not registry-backed keeps the
    original order: the flag, then p, then CI.
    """
    attrs = node.get("attributes")
    if not isinstance(attrs, dict):
        return None, NO_SOURCE

    registry_node = attrs.get("source") == REGISTRY_SOURCE
    registry_label = "ctgov_withdrawn" if _is_withdrawn(attrs) else REGISTRY_SOURCE
    if registry_node:
        # A registry node: its plain statistics are the registry's.
        decided = _significance_from_view(attrs, use_qualifier=True)
        if decided is not None:
            return decided, registry_label
    elif _is_registry_backed(attrs):
        # A merged node: groups with registry_<key> values first, then the
        # plain groups the registry filled or matched.
        groups = (ANALYSIS_P_GROUP, ANALYSIS_CI_GROUP)
        registry_views = [_registry_group_view(attrs, g) for g in groups]
        plain_views = [
            _plain_group_view(attrs, g) if v is None else None
            for g, v in zip(groups, registry_views)
        ]
        for view in registry_views + plain_views:
            if view is None:
                continue
            decided = _significance_from_view(view, use_qualifier=True)
            if decided is not None:
                return decided, REGISTRY_SOURCE

    flag = attrs.get("significant")
    if isinstance(flag, bool):
        return flag, registry_label if registry_node else "extracted"
    if registry_node:
        return None, NO_SOURCE
    decided = _significance_from_view(attrs)
    return decided, "extracted" if decided is not None else NO_SOURCE


def _analysis_significance(node: dict) -> bool | None:
    """Whether an OutcomeAnalysis node reports a statistically significant result.

    Precedence: on a registry-backed node, the registry p or CI statistics
    (see _analysis_significance_with_source); then a bool `significant` attribute, then the parsed `p_value` text (it
    keeps its comparator; "NS" reads as not significant), then a
    `p_value_num` in [0, 1], then the confidence interval against the null
    (1.0 for ratio measures, 0 for differences; an unknown measure decides
    only when both nulls agree). Returns None when nothing decides it.
    """
    return _analysis_significance_with_source(node)[0]


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


# Outcome-measure normalization. A copy of the Domain Builder metrics helper,
# extended for registry outcome titles, so differently worded titles of the
# same measure ("Change From Baseline in Hemoglobin A1c (HbA1c) - Primary
# Treatment Period", "... Glycosylated Haemoglobin (HbA1c)") share one key.
MEASURE_PREFIXES = (
    "change from baseline to last assessment in the trial in other treatment outcomes:",
    "percentage of participants achieving",
    "percent change from baseline in",
    "relative change from baseline in",
    "change from baseline in",
    "relative change in",
    "percent change in",
    "mean change in",
    "change in",
)
MEASURE_PREFIXES = tuple(sorted(MEASURE_PREFIXES, key=len, reverse=True))

MEASURE_SYNONYMS = {
    "body mass index": "bmi",
    "glycated haemoglobin": "hba1c",
    "glycated hemoglobin": "hba1c",
    "glycosylated haemoglobin": "hba1c",
    "glycosylated hemoglobin": "hba1c",
    "hemoglobin a1c": "hba1c",
    "haemoglobin a1c": "hba1c",
    "hemoglobin a1c (hba1c)": "hba1c",
    "systolic blood pressure": "sbp",
}

_MEASURE_PAREN_RE = re.compile(r"\([^)]*\)")
_MEASURE_WEEK_RE = re.compile(r"\s+(?:from baseline )?(?:at|to)\s+weeks?\s+\d+\s*$")
_MEASURE_WS_RE = re.compile(r"\s+")
# " - primary treatment period", " - semaglutide 2.4 mg versus placebo"
_MEASURE_SUFFIX_RE = re.compile(r"\s+-\s+.*$")
_MEASURE_COMPARING_RE = re.compile(r"\s+comparing\b.*$")
# "change from baseline to week 68 in", "change from baseline to end of treatment in"
_MEASURE_GENERIC_PREFIX_RE = re.compile(r"^change from baseline to [^:]{1,80}?\s+in\s+")

# 3-point MACE. A registry names the same composite as "MACE", "Major Adverse
# Cardiovascular Events", "3-point MACE" or by its three components
# ("cardiovascular death, non-fatal MI or non-fatal stroke"; SUSTAIN-6 and
# PIONEER 6 also report an all-cause-death variant), often after "Time (from
# randomisation) to first (occurrence of)". All of these key as "mace".
# Conservative: the check reads the whole title, before normalize_measure
# strips anything, and only these parentheticals are dropped: "(MACE)",
# "(3-point MACE)", "(MI)", "(myocardial infarction)", "(CV)",
# "(cardiovascular)". Any other parenthetical, a " - ..." suffix or another
# leading phrase ("Percentage of participants achieving") keeps the title off
# the key. The components must be exactly death, non-fatal MI and non-fatal
# stroke in that order, so expanded composites (revascularisation, unstable
# angina, heart failure), 4-point MACE and single components keep their own
# keys.
_MACE_PAREN_RE = re.compile(
    r"\s*\((?:mace|(?:3|three)[- ]?point mace|mi|myocardial infarction|cv|cardiovascular)\)"
)
_MACE_TIME_PREFIX_RE = re.compile(
    r"^time (?:from randomi[sz]ation )?to (?:the )?first(?: (?:occurrence|event) of)?\s*:?\s*(?:an? |the )?"
)
_MACE_NAME = r"(?:(?:3|three)[- ]?point (?:mace|major adverse cardiovascular events?)|mace(?:[- ]3)?|major adverse cardiovascular events?)"
_MACE_NAME_RE = re.compile(rf"^{_MACE_NAME}$")
_MACE_HEADER_RE = re.compile(
    rf"^(?:{_MACE_NAME}(?: composite(?: end ?point| outcome)?)?|(?:a )?composite(?: end ?point| outcome)?)"
    r",?\s*(?:defined as|consisting of|comprising|of)?\s*:?\s*"
)
_MACE_DEATH = r"(?:(?:cardiovascular|cv|all[- ]cause) (?:death|mortality)|death from (?:cardiovascular|any) causes?)"
_MACE_SEP = r"\s*(?:,\s*(?:and |or )?|and |or |/\s*)\s*"
_MACE_COMPONENTS_RE = re.compile(
    rf"^{_MACE_DEATH}{_MACE_SEP}non[- ]?fatal (?:myocardial infarction|mi){_MACE_SEP}non[- ]?fatal stroke$"
)


def _is_mace(name) -> bool:
    """True when an outcome-measure title names a 3-point MACE composite."""
    t = _MEASURE_WS_RE.sub(" ", str(name or "").lower()).strip()
    t = _MEASURE_WS_RE.sub(" ", _MACE_PAREN_RE.sub("", t)).strip()
    t = re.sub(r"[\s.,;:]+$", "", t)
    t = _MACE_TIME_PREFIX_RE.sub("", t, count=1)
    if _MACE_NAME_RE.match(t):
        return True
    return bool(_MACE_COMPONENTS_RE.match(_MACE_HEADER_RE.sub("", t, count=1)))


def normalize_measure(name) -> str:
    """Reduce an outcome-measure name to a canonical key.

    3-point MACE composites share the key "mace" (see _is_mace). Only
    registry mode uses this key, so graphs without registry data group
    exactly as before.
    """
    if _is_mace(name):
        return "mace"
    return _base_measure_key(name)


def _base_measure_key(name) -> str:
    """normalize_measure without the MACE key: the per-title key that registry
    contests are decided on (see _analysis_contests)."""
    s = _MEASURE_WS_RE.sub(" ", str(name or "").lower()).strip()
    s = _MEASURE_SUFFIX_RE.sub("", s)
    s = _MEASURE_COMPARING_RE.sub("", s)
    stripped = False
    for prefix in MEASURE_PREFIXES:
        # Word boundary: "change in" must not eat the start of "change inflammation".
        if s.startswith(prefix) and (len(s) == len(prefix) or not s[len(prefix)].isalnum()):
            s = s[len(prefix):].lstrip()
            stripped = True
            break
    if not stripped:
        s = _MEASURE_GENERIC_PREFIX_RE.sub("", s, count=1)
    s = _MEASURE_PAREN_RE.sub(" ", s)
    s = _MEASURE_WS_RE.sub(" ", s).strip()
    s = _MEASURE_WEEK_RE.sub("", s)
    s = re.sub(r"[\s.,;:]+$", "", s)
    s = _MEASURE_WS_RE.sub(" ", s).strip()
    s = MEASURE_SYNONYMS.get(s, s)
    if s and _is_mace(s) and not _is_mace(name):
        # The stripping removed a qualifier ("MACE (4-point)", "MACE -
        # expanded composite", "Percentage of participants achieving MACE"):
        # keep the whole title so it never shares the 3-point MACE key.
        return _MEASURE_WS_RE.sub(" ", str(name or "").lower()).strip()
    return s


_REGISTRY_STAT_KEYS = frozenset(
    f"registry_{k}" for k in ANALYSIS_P_GROUP + ANALYSIS_CI_GROUP
)


def _graph_has_registry_data(nodes: list[dict]) -> bool:
    """True when any node carries registry-import provenance, or an
    OutcomeAnalysis carries a registry statistic stored beside an extracted one.

    Other registry_<attr> conflict keys (a TrialPhase's registry_value, an
    Intervention's registry_label) come from earlier registry enrichment and
    do not make a graph one with registry analyses.
    """
    for node in nodes:
        attrs = node.get("attributes") if isinstance(node, dict) else None
        if not isinstance(attrs, dict):
            continue
        if _has_registry_provenance(attrs):
            return True
        if (
            str(node.get("entity_type", "")).lower() == ANALYSIS_TYPE
            and _REGISTRY_STAT_KEYS & set(attrs)
        ):
            return True
    return False


def _node_ncts(node: dict, attrs: dict) -> list[str]:
    """NCT ids of an analysis: its attributes, ctgov: documents, then its name."""
    found: list[str] = []
    ids = attrs.get("ctgov_nct_ids")
    if isinstance(ids, list):
        found.extend(str(i).strip() for i in ids)
    if isinstance(attrs.get("ctgov_nct_id"), str):
        found.append(attrs["ctgov_nct_id"].strip())
    docs = node.get("source_documents")
    for doc in docs if isinstance(docs, list) else ():
        text = str(doc).strip()
        if text.lower().startswith("ctgov:"):
            found.append(text[len("ctgov:"):].strip())
    prefix = NCT_RE.match(str(node.get("name") or ""))
    if prefix:
        found.append(prefix.group(0))
    ncts: list[str] = []
    for value in found:
        value = value.upper()
        if NCT_RE.fullmatch(value) and value not in ncts:
            ncts.append(value)
    return ncts


def _ctgov_doc_key(doc) -> str | None:
    """"ctgov:<NCT>" with the NCT upper-cased (as _node_ncts reads it), else None."""
    text = str(doc).strip()
    if not text.lower().startswith("ctgov:"):
        return None
    return "ctgov:" + text[len("ctgov:"):].strip().upper()


def _trial_nct_map(trial_lookup: dict) -> dict[str, str]:
    """NCT id -> the lowest Trial id carrying it (name, nct_id attribute or id)."""
    mapping: dict[str, str] = {}
    for trial_id in sorted(trial_lookup, key=str):
        trial = trial_lookup[trial_id]
        attrs = trial.get("attributes") if isinstance(trial.get("attributes"), dict) else {}
        found = [str(trial.get("name") or "").strip().upper(), str(attrs.get("nct_id") or "").strip().upper()]
        found.extend(m.upper() for m in NCT_RE.findall(str(trial_id)))
        for nct in found:
            if NCT_RE.fullmatch(nct):
                mapping.setdefault(nct, trial_id)
    return mapping


def _compound_patterns(by_id: dict) -> list[tuple[str, re.Pattern]]:
    """(compound id, word-boundary pattern) for every Compound name of 3+ chars
    that is not a comparator keyword phrase."""
    patterns = []
    for node_id in sorted(by_id, key=str):
        node = by_id[node_id]
        if str(node.get("entity_type", "")).lower() != "compound":
            continue
        name = str(node.get("name") or "").strip()
        # A Compound named like a comparator ("Standard of care") names no
        # treatment.
        if len(name) < MIN_COMPOUND_NAME or _HARD_PLACEBO_RE.search(name) or _SOFT_PLACEBO_RE.search(name):
            continue
        patterns.append((node_id, re.compile(
            r"(?<![A-Za-z0-9])" + re.escape(name) + r"(?![A-Za-z0-9])", re.IGNORECASE
        )))
    return patterns


def _soft_keyword_spans(text: str) -> list[tuple[int, int]]:
    """(start, end) of every soft comparator keyword in text. "control"
    qualified by what it controls ("glycaemic control", "blood pressure
    control") names no comparator arm and is skipped."""
    spans = []
    for match in _SOFT_PLACEBO_RE.finditer(text):
        if match.group(0).lower() == "control" and _CONTROL_QUALIFIER_RE.search(text, 0, match.start()):
            continue
        spans.append(match.span())
    return spans


def _split_parentheticals(text: str) -> tuple[str, list[str]]:
    """(text with every parenthetical blanked to spaces, the contents of its
    top-level parentheticals). Positions in the blanked text match text."""
    outside: list[str] = []
    segments: list[str] = []
    inner: list[str] = []
    depth = 0
    for ch in text:
        if ch == "(":
            depth += 1
            if depth == 1:
                inner = []
                outside.append(" ")
                continue
        elif ch == ")" and depth:
            depth -= 1
            if depth == 0:
                segments.append("".join(inner))
                outside.append(" ")
                continue
        if depth:
            inner.append(ch)
            outside.append(" ")
        else:
            outside.append(ch)
    if depth:
        segments.append("".join(inner))
    return "".join(outside), segments


def _joined_compounds(text: str, spans, patterns: list[tuple[str, re.Pattern]]) -> set[str]:
    """Compounds joined to a soft keyword span by an add-on connector, in either
    order ("Semaglutide 1 mg with usual care", "Usual care + semaglutide")."""
    joined = set()
    for compound_id, pattern in patterns:
        for match in pattern.finditer(text):
            for start, end in spans:
                gap = (match.end(), start) if match.end() <= start else (end, match.start())
                if gap[0] <= gap[1] and _ADD_ON_RE.search(text, gap[0], gap[1]):
                    joined.add(compound_id)
    return joined


def _soft_arm(text: str, patterns: list[tuple[str, re.Pattern]]) -> tuple[bool, set[str]] | None:
    """(is comparator, arm compounds) of a text with a soft keyword and no hard
    one, or None when it has no soft keyword.

    A soft keyword outside parentheses marks a comparator arm unless a
    Compound named outside parentheses is joined to it by an add-on
    connector; the joined compounds are then the active add-on arm's
    ("Usual care + semaglutide 0.5 mg"), and a compound only in a
    parenthetical is the comparator's background ("Standard of care
    (metformin)"). A soft keyword only inside a parenthetical marks a
    comparator ("Insulin glargine (control)") unless the parenthetical joins
    it to the arm by a connector before it ("Semaglutide 1 mg (added to
    standard of care)").
    """
    outside, segments = _split_parentheticals(text)
    spans = _soft_keyword_spans(outside)
    if spans:
        joined = _joined_compounds(outside, spans, patterns)
        return (False, joined) if joined else (True, set())
    inside = [segment for segment in segments if _soft_keyword_spans(segment)]
    if not inside:
        return None
    named = {compound_id for compound_id, pattern in patterns if pattern.search(outside)}
    for segment in inside:
        first = _soft_keyword_spans(segment)[0]
        if named and _ADD_ON_RE.search(segment, 0, first[0]):
            return False, named
    return True, set()


def _is_comparator_text(text, patterns: list[tuple[str, re.Pattern]]) -> bool:
    """True when text names a comparator arm (see SOFT_PLACEBO_KEYWORDS)."""
    if not isinstance(text, str) or not text:
        return False
    if _HARD_PLACEBO_RE.search(text):
        return True
    soft = _soft_arm(text, patterns)
    return soft is not None and soft[0]


def _compounds_in_text(text, patterns: list[tuple[str, re.Pattern]]) -> set[str]:
    """Compound ids whose name appears in text at a word boundary.

    Comparator text names no treatment ("Semaglutide placebo", "Usual care
    (metformin)"); an active add-on arm names the compounds joined to its
    soft keyword ("Semaglutide 2.4 mg + usual care").
    """
    if not isinstance(text, str) or not text or _HARD_PLACEBO_RE.search(text):
        return set()
    soft = _soft_arm(text, patterns)
    if soft is not None:
        return soft[1]
    return {compound_id for compound_id, pattern in patterns if pattern.search(text)}


def _is_placebo_cohort(cohort: dict, received_names: list[str], patterns=()) -> bool:
    """A comparator arm: a comparator keyword in its name, arm label or group
    description that is not an active add-on to standard of care (see
    _is_comparator_text), or every compound or intervention it receives is
    placebo.
    """
    attrs = cohort.get("attributes") if isinstance(cohort.get("attributes"), dict) else {}
    for text in (cohort.get("name"), attrs.get("arm_label"), attrs.get("group_description")):
        if _is_comparator_text(text, patterns):
            return True
    return bool(received_names) and all("placebo" in name.lower() for name in received_names)


def _registry_treatment(
    node_id, attrs: dict, related, by_id: dict, adjacency, patterns, cohort_info,
    label_of=None,
) -> tuple[str | None, set[str], bool]:
    """Resolve the treatment compound from compares Cohorts and registry group titles.

    Placebo and comparator arms are dropped before any name match, because a
    placebo arm's name can contain the compound ("Semaglutide placebo 0.5 mg").
    Returns (compound id or None, non-placebo compared cohort ids, ambiguous).
    label_of maps a Cohort whose extracted name conflicts with its registry
    arm_label to that label; such a cohort is matched on the label alone
    (CONTEST-03). ambiguous is True for an active-comparator set with no
    comparator keyword: at least two arms each naming a compound, no
    comparator or placebo arm, and the arms' compounds not all the same
    (Tirzepatide vs Insulin Glargine), so the treatment is genuinely unclear.
    The treatment is set only when exactly one compound results. When several
    result and at least one compared arm is a comparator arm, a compound that
    every compared arm receives (the comparator included) is background
    therapy and is dropped, if exactly one remains. Without a comparator arm
    the shared compound is the comparison itself (CagriSema vs semaglutide),
    so the treatment stays ambiguous.
    """
    def received(cohort_id) -> set[str]:
        label = label_of(cohort_id) if label_of else None
        if label:
            return _compounds_in_text(label, patterns)
        found = set(related(cohort_id, RECEIVES, "compound"))
        for intervention in related(cohort_id, RECEIVES, "intervention"):
            found.update(related(intervention, CONTAINS, "compound"))
        return found

    cohorts = related(node_id, COMPARES, "cohort")
    active = [c for c in cohorts if not cohort_info(c)]
    compounds: set[str] = set()
    # Compounds per compared arm, for the background-therapy check.
    arms: list[set[str]] = []
    for cohort_id in cohorts:
        if cohort_id not in active:
            arms.append({
                c for c in received(cohort_id)
                if "placebo" not in str(by_id[c].get("name") or "").lower()
            })
            continue
        found = received(cohort_id)
        if not found and not (label_of and label_of(cohort_id)):
            found = _compounds_in_text(by_id[cohort_id].get("name"), patterns)
        compounds.update(found)
        arms.append(found)

    # Group titles that matched no Cohort stand in for the missing arm. With no
    # compared Cohort, or only comparator ones, the active arm is one of the
    # compared group titles.
    titles = attrs.get("unmatched_groups") if active else attrs.get("compared_groups")
    has_comparator = len(active) < len(cohorts)
    for title in titles if isinstance(titles, list) else ():
        if _is_comparator_text(title, patterns):
            has_comparator = True
        found = _compounds_in_text(title, patterns)
        compounds.update(found)
        arms.append(found)

    if has_comparator and len(compounds) > 1 and len(arms) > 1:
        remaining = compounds - set.intersection(*arms)
        if len(remaining) == 1:
            compounds = remaining
    treatment = next(iter(compounds)) if len(compounds) == 1 else None
    ambiguous = (
        not has_comparator
        and len(arms) >= 2
        and all(arms)
        and len({frozenset(a) for a in arms}) > 1
    )
    return treatment, set(active), ambiguous


def _group_compounds(group: dict, patterns) -> set[str]:
    """Compounds an armGroup names: its title, else its non-placebo interventions."""
    found = _compounds_in_text(group.get("title"), patterns)
    if not found:
        for intervention in group.get("interventions") or ():
            if isinstance(intervention, str) and not _HARD_PLACEBO_RE.search(intervention):
                found |= _compounds_in_text(_INTERVENTION_PREFIX_RE.sub("", intervention), patterns)
    return found


def _arm_type_treatment(attrs: dict, patterns) -> str | None:
    """Treatment compound from the registry armGroup types of an analysis.

    Needs ctgov_arm_groups with at least two entries, every one typed, exactly
    one EXPERIMENTAL and all the others comparator types (active, placebo, sham,
    no intervention). The compound is the one the EXPERIMENTAL group's title
    names or, when the title names none, the one its interventions name.
    CONTEST-03: when that names several compounds, every compound all the
    comparator groups also name is add-on background (semaglutide + metformin
    against insulin glargine + metformin) and is dropped. Zero or several
    remaining compounds give None.
    """
    groups = attrs.get("ctgov_arm_groups")
    if not isinstance(groups, list) or len(groups) < 2:
        return None
    if not all(isinstance(g, dict) and isinstance(g.get("arm_type"), str) for g in groups):
        return None
    experimental = [g for g in groups if g["arm_type"] == ARM_EXPERIMENTAL]
    if len(experimental) != 1:
        return None
    comparators = [g for g in groups if g is not experimental[0]]
    if not all(g["arm_type"] in ARM_COMPARATOR_TYPES for g in comparators):
        return None
    arm = experimental[0]
    # A group typed EXPERIMENTAL but titled as a comparator (a blinded placebo
    # arm) names no treatment, whatever its interventions list.
    if _is_comparator_text(arm.get("title"), patterns):
        return None
    found = _group_compounds(arm, patterns)
    if len(found) > 1 and comparators:
        background = set.intersection(*(_group_compounds(g, patterns) for g in comparators))
        if found - background:
            found = found - background
    return next(iter(found)) if len(found) == 1 else None


# CONTEST-02: outcome kind from the registry paramType and unitOfMeasure first,
# then the measure title (and the registry effect measure).
OUTCOME_KINDS = ("responder", "continuous", "time_to_event")
# Registry analysis paramType (the effect measure) naming a time-to-event model.
# "HR" is read only here, never in a title, where it is usually heart rate.
# The abbreviations HR, OR and RR are matched case-sensitively, so the words
# "or" and "hr" in a free-text effect measure name no model; the descriptive
# phrases are matched in any case.
_TIME_TO_EVENT_EFFECT_RE = re.compile(r"(?i:hazard|\bcox\b)|\bHR\b")
_RESPONDER_EFFECT_RE = re.compile(
    r"(?i:odds\s+ratio|risk\s+ratio|relative\s+risk|risk\s+difference)|\bOR\b|\bRR\b"
)
# Registry outcome-measure paramType values (outcome_param_type).
_RESPONDER_PARAM_TYPES = frozenset({"COUNT_OF_PARTICIPANTS"})
_CONTINUOUS_PARAM_TYPES = frozenset({
    "MEAN", "LEAST_SQUARES_MEAN", "GEOMETRIC_MEAN", "GEOMETRIC_LEAST_SQUARES_MEAN", "LOG_MEAN",
})
# A unit counting participants (or their percentage) is a responder unit.
_RESPONDER_UNIT_RE = re.compile(
    r"(?:percentage|percent|proportion|number|count)\s+of\s+(?:participants|patients|subjects)|"
    r"^\s*(?:participants|patients|subjects)\s*$",
    re.IGNORECASE,
)
# Units that measure a quantity, never a share of participants ("%" and
# "percent" are ambiguous and decide only after the title, see _outcome_kind).
_CONTINUOUS_STRONG_UNIT_RE = re.compile(
    r"\bkg\b|kilogram|mmol|mg/dl|\bcm\b|mmhg|\bpounds?\b|\blbs?\b|\bkg/m|beats\s+per\s+minute|\bbpm\b",
    re.IGNORECASE,
)
_CONTINUOUS_UNIT_RE = re.compile(
    r"\bkg\b|kilogram|%|percent|mmol|mg/dl|\bcm\b|mmhg|\bpounds?\b|\blbs?\b|\bkg/m", re.IGNORECASE
)
# "Time to" names a time-to-event outcome only with event wording ("Time to
# First Occurrence of MACE"); "Time to Exhaustion" is a measured duration.
_TIME_TO_EVENT_TITLE_RE = re.compile(
    r"hazard\s+ratio|\btime\s+to\s+(?:the\s+)?(?:first|onset|occurrence|event|death|progression|"
    r"relapse|recurrence|discontinu|rescue|hospitali[sz]|withdrawal|treatment\s+failure|failure|"
    r"initiation|need|requir|development|confirmed|sustained)|\bevent[-\s]free\b|\bsurvival\b",
    re.IGNORECASE,
)
_RESPONDER_TITLE_RE = re.compile(
    r"percentage\s+of\s+(?:participants|patients|subjects)|\bproportion\b|\bachiev|\bresponders?\b|"
    r"number\s+of\s+(?:participants|patients|subjects)|"
    r"^\s*(?:count\s+of\s+)?participants\s*$",
    re.IGNORECASE,
)
# A threshold ("≥5%") makes a responder title only when no continuous marker
# says the measure is a change ("Change From Baseline in Body Weight in
# Participants With Baseline HbA1c >=8%" is a continuous subgroup).
_THRESHOLD_RE = re.compile(r"(?:≥|>=|≤|<=|<|>)\s*\d+(?:\.\d+)?\s*%")
_CONTINUOUS_TITLE_RE = re.compile(
    r"change\s+from\s+baseline|\bmean\b|\bls\s+mean\b|least\s+squares?\s+mean",
    re.IGNORECASE,
)


def _outcome_kind(title, unit=None, effect_measure=None, param_type=None) -> str | None:
    """Classify an outcome as responder, continuous or time_to_event, else None.

    Order: a time-to-event effect measure (hazard ratio, HR, Cox); the
    registry paramType (COUNT_OF_PARTICIPANTS responder; MEAN, LEAST_SQUARES_MEAN
    and the geometric means continuous); the unitOfMeasure (participant counts
    responder; kg, mmol, mmHg and similar continuous); a responder effect
    measure (odds or risk ratio, risk difference, "proportion of
    participants"); then the title:
    time-to-event wording ("hazard ratio", "time to first ...", not a measured
    duration such as "Time to Exhaustion"), responder wording ("percentage of
    participants", "achieving"), continuous wording ("change from baseline",
    "mean"), a responder threshold ("≥5%") in a title with no continuous
    wording, and last a "%" or "percent" unit (continuous).
    """
    title = str(title or "")
    unit = str(unit or "")
    effect = str(effect_measure or "")
    param = str(param_type or "").strip().upper().replace(" ", "_")
    if _TIME_TO_EVENT_EFFECT_RE.search(effect):
        return "time_to_event"
    if param in _RESPONDER_PARAM_TYPES:
        return "responder"
    if param in _CONTINUOUS_PARAM_TYPES:
        return "continuous"
    if _RESPONDER_UNIT_RE.search(unit):
        return "responder"
    if _CONTINUOUS_STRONG_UNIT_RE.search(unit):
        return "continuous"
    if _RESPONDER_EFFECT_RE.search(effect) or _RESPONDER_TITLE_RE.search(effect):
        return "responder"
    continuous_title = bool(_CONTINUOUS_TITLE_RE.search(title))
    if _TIME_TO_EVENT_TITLE_RE.search(title) and not re.search(r"change\s+from\s+baseline", title, re.I):
        return "time_to_event"
    if _RESPONDER_TITLE_RE.search(title):
        return "responder"
    if continuous_title or re.search(r"mean\s+difference", effect, re.IGNORECASE):
        return "continuous"
    if _THRESHOLD_RE.search(title):
        return "responder"
    if _CONTINUOUS_UNIT_RE.search(unit):
        return "continuous"
    return None


# CONTEST-01: dose in mg from arm and group titles. A number may carry
# thousands separators ("1,000 mg" is 1000 mg). A range ("12-45 mg", "0.25 to
# 1 mg") names both ends, so it is never one dose. A match never starts inside
# a number ("1,000", "12-45") but may follow a name and a hyphen
# ("Semaglutide-1 mg", "LY3298176-5mg").
_DOSE_UNITS = r"(?:milligrams?|mg|mcg|µg|μg|ug|g)"
_DOSE_NUM = r"(?:\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
_DOSE_START = r"(?<![\w.,])(?<!\d[-–—])"
_DOSE_END = r"(?![A-Za-z0-9µμ])"
# Per-weight and concentration values ("10 mg/kg", "0.5-5.0 mg/ml") are no dose.
_PER_UNIT_TAIL = r"\s*/\s*(?:kg|m2|m²|dl|ml|l)\b"
_DOSE_PER_UNIT = r"(?!" + _PER_UNIT_TAIL + r")"
_DOSE_RANGE_BODY = (
    _DOSE_START + r"(" + _DOSE_NUM + r")\s*(" + _DOSE_UNITS + r")?\s*(?:-|–|—|\s+to\s+)\s*("
    + _DOSE_NUM + r")\s*(" + _DOSE_UNITS + r")" + _DOSE_END
)
_DOSE_RANGE_RE = re.compile(_DOSE_RANGE_BODY + _DOSE_PER_UNIT, re.IGNORECASE)
# A range whose upper end is per-weight or a concentration ("10 mg - 20 mg/kg")
# is per-weight as a whole: neither end is read as a dose.
_DOSE_PER_UNIT_RANGE_RE = re.compile(_DOSE_RANGE_BODY + r"(?=" + _PER_UNIT_TAIL + r")", re.IGNORECASE)
# A hyphen joining a name or code that contains a letter to a number
# ("Semaglutide-1 mg", "LY3298176-5mg") separates the name from the dose; a
# hyphen between two plain numbers ("12-45 mg") is a range, and so is one after
# a unit ("1 mg-2 mg").
_DOSE_NAME_HYPHEN_RE = re.compile(
    r"(?<![\w.])(?!(?i:" + _DOSE_UNITS + r")[-–—])((?=[A-Za-z0-9]*[A-Za-z])[A-Za-z0-9]+)[-–—](?=\d)"
)
# A unit-less whole number right after a label word is the label's number, not
# the low end of a range: "Cohort 2 - 10 mg" and "Group 1 to 4 mg" name one
# dose. A decimal ("treatment 0.25 to 2.4 mg") is never a label number, and
# descriptor words ("treatment", "regimen") are no labels: "Titration regimen
# 5 to 10 mg" is a range.
_DOSE_LABEL_BEFORE_RE = re.compile(
    r"\b(?:cohorts?|parts?|groups?|arms?|periods?|weeks?|wks?|days?|stages?|steps?|phases?|"
    r"levels?|visits?|panels?|sequences?|segments?|blocks?|"
    r"months?|years?|no|nos|numbers?)\.?\s*(?:#|no\.?|number)?\s*[:#]?\s*$",
    re.IGNORECASE,
)
_DOSE_POOL_RE = re.compile(
    _DOSE_START + r"((?:" + _DOSE_NUM + r"\s*/\s*)+" + _DOSE_NUM + r")\s*(" + _DOSE_UNITS + r")(?![A-Za-z0-9µμ/])",
    re.IGNORECASE,
)
_DOSE_RE = re.compile(
    _DOSE_START + r"(" + _DOSE_NUM + r")\s*(" + _DOSE_UNITS + r")" + _DOSE_END + _DOSE_PER_UNIT,
    re.IGNORECASE,
)
_DOSE_SEGMENT_RE = re.compile(
    r"\s*(?:\+|;|,(?!\d)|\s+plus\s+|\s+and\s+|\s+with\s+|\s+vs\.?\s+)\s*", re.IGNORECASE
)


def _to_mg(value: str, unit: str) -> float:
    unit = unit.lower()
    number = float(value.replace(",", ""))
    if unit in ("mcg", "µg", "μg", "ug"):
        number /= 1000.0
    elif unit == "g":
        number *= 1000.0
    return round(number, 4)


def _parse_dose(text) -> set[float]:
    """Doses in mg named by a text (a slash-pooled "5/10/15 mg" gives several).

    Thousands separators are read ("1,000 mg" is 1000). A range ("12-45 mg",
    "0.25 to 1 mg") gives both ends, so it never reads as one dose.
    Per-weight and concentration values ("10 mg/kg", "10-20 mg/kg",
    "0.5-5.0 mg/ml") are not doses, and neither end of a range whose upper
    end is one ("10 mg - 20 mg/kg") is. A whole label number before a dash or
    "to" ("Cohort 2 - 10 mg", "Part 1 - 5 mg", "Group 1 to 4 mg") is no range
    end, unless it carries a unit itself; a decimal always is.
    """
    text = _DOSE_NAME_HYPHEN_RE.sub(r"\1 ", str(text or ""))
    text = _DOSE_PER_UNIT_RANGE_RE.sub(" ", text)
    found: set[float] = set()
    kept: list[str] = []
    pos = 0
    search_from = 0
    while True:
        match = _DOSE_RANGE_RE.search(text, search_from)
        if match is None:
            break
        if (
            match.group(2) is None
            and "." not in match.group(1)
            and _DOSE_LABEL_BEFORE_RE.search(text, 0, match.start())
        ):
            # Not a range: retry after the label number, so the dose after
            # the separator is still read (by the single-dose pattern).
            search_from = match.end(1)
            continue
        found.add(_to_mg(match.group(1), match.group(2) or match.group(4)))
        found.add(_to_mg(match.group(3), match.group(4)))
        kept.append(text[pos:match.start()])
        kept.append(" ")
        pos = search_from = match.end()
    kept.append(text[pos:])
    text = "".join(kept)
    for match in _DOSE_POOL_RE.finditer(text):
        for number in re.split(r"\s*/\s*", match.group(1)):
            found.add(_to_mg(number, match.group(2)))
    remainder = _DOSE_POOL_RE.sub(" ", text)
    for match in _DOSE_RE.finditer(remainder):
        found.add(_to_mg(match.group(1), match.group(2)))
    return found


def _finding_dose(texts, treatment_id, patterns) -> float | None:
    """The single dose (mg) of the treatment compound across its arm texts, else None.

    A text that names compounds counts only the segments (split on "+", "plus",
    "and", "with", ",", ";", "vs") that name the treatment; a segment naming no
    compound follows the segment before it. A text that names no compound
    contributes its doses as they are. Several distinct doses give None.
    """
    doses: set[float] = set()
    for text in texts:
        text = str(text or "")
        if not text.strip():
            continue
        if not _compounds_in_text(text, patterns):
            doses |= _parse_dose(text)
            continue
        current = False
        for segment in _DOSE_SEGMENT_RE.split(text):
            named = _compounds_in_text(segment, patterns)
            if named:
                current = treatment_id in named
            if current:
                doses |= _parse_dose(segment)
    return next(iter(doses)) if len(doses) == 1 else None


def _analysis_findings(
    nodes: list[dict], links: list[dict], trial_lookup: dict, doc_trials: dict,
    registry_mode: bool = False, arm_stats: dict | None = None,
) -> list[dict]:
    """Grade every OutcomeAnalysis node into one finding dict.

    The outcome, treatment and trial are resolved through the graph's edges
    in either direction, so a reversed edge still resolves.

    With registry_mode (the graph carries registry-import data) a registry
    analysis also resolves its Trial through its NCT ids, its treatment through
    its compared Cohorts or group titles, and its outcome to a normalized
    measure key; findings then record their significance source and
    registry-backed provenance, and an extracted analysis duplicated by a
    registry analysis is marked superseded.

    CONTEST-03: in registry mode the treatment comes from an assesses_effect_of
    edge first, then from the registry arm types (_arm_type_treatment: one
    EXPERIMENTAL group against comparators, add-on background dropped), then
    from the Cohort / group-title rule (_registry_treatment). An edge answer
    always stands and an arm answer that differs from it is only counted in
    arm_stats["disagreements"]. treatment_basis "registry_arm_type" is set
    only when the arm answer fills a None or overrides a different title
    answer (also counted as a disagreement); an edge's own treatment_basis is
    copied. With no answer, no usable arm types and an ambiguous active
    comparator set the basis is "ambiguous_active_comparator". A compared
    Cohort whose name conflicts with its registry arm_label is matched on the
    label and recorded in label_conflict; when the name and the label name
    different doses the finding's dose_mg is None (SA-01). An assesses_effect_of link written
    by the registry import and withdrawn (_is_withdrawn) is ignored.
    A withdrawn registry fact is not corroboration (WR-02 follow-up): no
    ctgov: support document for a withdrawn NCT (also not one inherited from
    the node's source_documents), registry_withdrawn on the
    finding, and a withdrawn registry analysis does not supersede anything.
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

    nct_trials: dict[str, str] = {}
    patterns: list[tuple[str, re.Pattern]] = []
    placebo_cache: dict[str, bool] = {}
    if registry_mode:
        nct_trials = _trial_nct_map(trial_lookup)
        patterns = _compound_patterns(by_id)

    # assesses_effect_of link attributes per (analysis, target), both directions.
    assess_attrs: dict[tuple, list[dict]] = defaultdict(list)
    for link in links:
        if link.get("relation_type") != ASSESSES:
            continue
        link_attrs = link.get("attributes") if isinstance(link.get("attributes"), dict) else {}
        assess_attrs[(link.get("source"), link.get("target"))].append(link_attrs)
        assess_attrs[(link.get("target"), link.get("source"))].append(link_attrs)

    def kept_edges(node_id, other) -> list[dict]:
        """Attributes of the assesses links between two nodes that still count:
        a registry-written link that is withdrawn is dropped (WR-02 follow-up)."""
        return [
            a for a in assess_attrs.get((node_id, other), ())
            if not (registry_mode and a.get("source") == REGISTRY_SOURCE and _is_withdrawn(a))
        ]

    def assesses(node_id, entity_type: str) -> list[str]:
        return [o for o in related(node_id, ASSESSES, entity_type) if kept_edges(node_id, o)]

    conflict_cache: dict[str, dict | None] = {}

    def label_conflict(cohort_id) -> dict | None:
        """CONTEST-03: the cohort's name and registry arm_label disagree on
        compounds, dose or comparator status (a missing compound or dose on
        one side is not a disagreement)."""
        if cohort_id not in conflict_cache:
            cohort = by_id[cohort_id]
            cattrs = cohort.get("attributes") if isinstance(cohort.get("attributes"), dict) else {}
            name, label = cohort.get("name"), cattrs.get("arm_label")
            conflict = None
            if isinstance(label, str) and label.strip() and isinstance(name, str):
                name_compounds = _compounds_in_text(name, patterns)
                label_compounds = _compounds_in_text(label, patterns)
                name_doses, label_doses = _parse_dose(name), _parse_dose(label)
                if (
                    _is_comparator_text(name, patterns) != _is_comparator_text(label, patterns)
                    or (name_compounds and label_compounds and name_compounds != label_compounds)
                    or (name_doses and label_doses and name_doses != label_doses)
                ):
                    conflict = {"cohort": cohort_id, "cohort_name": name, "arm_label": label}
            conflict_cache[cohort_id] = conflict
        return conflict_cache[cohort_id]

    def label_of(cohort_id) -> str | None:
        conflict = label_conflict(cohort_id)
        return conflict["arm_label"] if conflict else None

    def dose_conflict(cohort_id) -> bool:
        """The cohort's name and registry arm_label both name doses and the
        doses differ: the arm's dose is unknown (SA-01, conservative)."""
        if not label_conflict(cohort_id):
            return False
        cohort = by_id[cohort_id]
        cattrs = cohort.get("attributes") if isinstance(cohort.get("attributes"), dict) else {}
        name_doses = _parse_dose(cohort.get("name"))
        label_doses = _parse_dose(cattrs.get("arm_label"))
        return bool(name_doses and label_doses and name_doses != label_doses)

    def cohort_info(cohort_id) -> bool:
        if cohort_id not in placebo_cache and label_of(cohort_id):
            placebo_cache[cohort_id] = _is_comparator_text(label_of(cohort_id), patterns)
        if cohort_id not in placebo_cache:
            received = [
                str(by_id[t].get("name") or "")
                for t in sorted({
                    o for r, o in adjacency.get(cohort_id, ())
                    if r == RECEIVES and o in by_id
                })
            ]
            placebo_cache[cohort_id] = _is_placebo_cohort(by_id[cohort_id], received, patterns)
        return placebo_cache[cohort_id]

    findings: list[dict] = []
    # Per-finding data the supersession pass needs; never stored on the finding.
    side: dict[str, dict] = {}
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
        edge_target = None
        compounds = assesses(node_id, "compound")
        if compounds:
            treatment_id = edge_target = compounds[0]
        else:
            interventions = assesses(node_id, "intervention")
            if interventions:
                edge_target = interventions[0]
                contained = related(interventions[0], CONTAINS, "compound")
                treatment_id = contained[0] if contained else interventions[0]
        treatment_basis = None
        if treatment_id is not None:
            for edge in kept_edges(node_id, edge_target):
                if isinstance(edge.get("treatment_basis"), str):
                    treatment_basis = edge["treatment_basis"]
                    break
        active_cohorts: set[str] = set()
        ambiguous = False
        if registry_mode:
            fallback, active_cohorts, ambiguous = _registry_treatment(
                node_id, attrs, related, by_id, adjacency, patterns, cohort_info, label_of
            )
            arm = _arm_type_treatment(attrs, patterns)
            if treatment_id is not None:
                # An edge answer stands; a differing arm answer is only counted.
                if arm is not None and arm != treatment_id and etype(treatment_id) == "compound" and arm_stats is not None:
                    arm_stats["disagreements"] = arm_stats.get("disagreements", 0) + 1
            elif arm is not None:
                # CONTEST-03: arm types come before the Cohort / title rule. The
                # basis is recorded only when the arm answer filled a None or
                # overrode a different answer, never when the two agree.
                treatment_id = arm
                if fallback is None:
                    treatment_basis = "registry_arm_type"
                elif arm != fallback:
                    treatment_basis = "registry_arm_type"
                    if arm_stats is not None:
                        arm_stats["disagreements"] = arm_stats.get("disagreements", 0) + 1
            else:
                treatment_id = fallback
                if fallback is None and ambiguous and not attrs.get("ctgov_arm_groups"):
                    treatment_basis = "ambiguous_active_comparator"
        treatment = name_of(treatment_id) if treatment_id else None

        # Trial: a direct edge first, then the NCT ids (registry mode), else
        # the trials of the source documents
        candidates = sorted({
            other for rel, other in adjacency.get(node_id, ()) if other in trial_lookup
        })
        if not candidates and registry_mode:
            candidates = sorted({
                nct_trials[nct] for nct in _node_ncts(node, attrs) if nct in nct_trials
            }, key=str)
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

        significant, significance_source = _analysis_significance_with_source(node)
        p_value = attrs.get("p_value")
        if p_value is None:
            p_value = attrs.get("p_value_num")
        support_documents = [str(d) for d in node.get("source_documents") or []]
        finding = {
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
            "support_documents": support_documents,
            "basis": "outcome_analysis",
            "epistemic_status": (
                "asserted" if significant is True
                else "negative" if significant is False
                else "unresolved"
            ),
        }
        if registry_mode:
            backed = _is_registry_backed(attrs)
            withdrawn = _has_registry_provenance(attrs) and _is_withdrawn(attrs)
            withdrawn_ncts = _withdrawn_ncts(attrs)
            # CR-02: a withdrawn NCT's ctgov: document is no support, also when
            # the node's own source_documents carry it (enrich writes ctgov:<NCT>
            # there for every registry-created and merged node).
            withdrawn_docs = {f"ctgov:{nct}" for nct in withdrawn_ncts}
            if withdrawn:
                withdrawn_docs |= {f"ctgov:{nct}" for nct in _node_ncts(node, attrs)}
            if withdrawn_docs:
                support_documents[:] = [
                    d for d in support_documents if _ctgov_doc_key(d) not in withdrawn_docs
                ]
            if backed:
                for nct in _node_ncts(node, attrs):
                    if nct in withdrawn_ncts:
                        continue
                    doc = f"ctgov:{nct}"
                    if doc not in support_documents:
                        support_documents.append(doc)
            raw_sources = attrs.get("sources")
            if isinstance(raw_sources, list):
                sources = [str(s) for s in raw_sources]
            elif isinstance(attrs.get("source"), str):
                sources = [attrs["source"]]
            else:
                sources = ["extracted"]
            if treatment_basis:
                finding["treatment_basis"] = treatment_basis
            if withdrawn:
                finding["registry_withdrawn"] = True
            conflicts = sorted(
                (c for c in map(label_conflict, related(node_id, COMPARES, "cohort")) if c),
                key=lambda c: str(c["cohort"]),
            )
            if conflicts:
                finding["label_conflict"] = conflicts
            # CONTEST-02: the outcome kind keys the contest; CONTEST-01: so does the dose.
            outcome_node = by_id.get(outcomes[0]) if outcomes else None
            outcome_attrs = (
                outcome_node.get("attributes")
                if outcome_node and isinstance(outcome_node.get("attributes"), dict) else {}
            )
            finding["outcome_kind"] = (
                _outcome_kind(
                    outcome_node.get("name") if outcome_node else None,
                    attrs.get("unit") or outcome_attrs.get("unit"),
                    attrs.get("effect_measure"),
                    attrs.get("outcome_param_type") or outcome_attrs.get("outcome_param_type"),
                ) if outcome_node else None
            )
            finding["dose_mg"] = None
            if treatment_id is not None and etype(treatment_id) == "compound":
                dose_texts: list = []
                for cohort_id in sorted(active_cohorts):
                    cohort = by_id[cohort_id]
                    cohort_attrs = cohort.get("attributes") if isinstance(cohort.get("attributes"), dict) else {}
                    if label_of(cohort_id):
                        dose_texts.append(label_of(cohort_id))
                    else:
                        dose_texts += [cohort.get("name"), cohort_attrs.get("arm_label")]
                compared = attrs.get("compared_groups")
                for title in compared if isinstance(compared, list) else ():
                    if not _is_comparator_text(title, patterns):
                        dose_texts.append(title)
                arm_groups = attrs.get("ctgov_arm_groups")
                for group in arm_groups if isinstance(arm_groups, list) else ():
                    if isinstance(group, dict) and group.get("arm_type") == ARM_EXPERIMENTAL:
                        dose_texts.append(group.get("title"))
                if not any(dose_conflict(c) for c in active_cohorts):
                    finding["dose_mg"] = _finding_dose(dose_texts, treatment_id, patterns)
            finding["significance_source"] = significance_source
            finding["sources"] = sources
            # An outcome whose name normalizes to nothing ("Change from baseline
            # in (HbA1c)") keys on its own id, so it groups with no other.
            finding["standard_outcome_key"] = (
                (normalize_measure(standard_outcome) or str(standard_outcome_id))
                if standard_outcome else None
            )
            if backed:
                ni_type = _non_inferiority_type(attrs)
                if ni_type:
                    finding["non_inferiority"] = ni_type
            side[node_id] = {
                "registry": attrs.get("source") == REGISTRY_SOURCE and not withdrawn,
                "backed": backed,
                "cohorts": set(related(node_id, COMPARES, "cohort")),
                "active": active_cohorts,
            }
        findings.append(finding)

    if registry_mode:
        _mark_superseded(findings, side)
    return findings


def _mark_superseded(findings: list[dict], side: dict[str, dict]) -> None:
    """Mark extracted findings that a registry finding of the same comparison replaces.

    Same resolved trial, outcome key and treatment, and a shared non-placebo
    compared Cohort. When either side has no compared Cohorts the pair matches
    only if exactly one registry finding is a candidate. With several matches
    the lowest registry analysis id wins. Both findings stay in the claims.
    """
    registry = [f for f in findings if side[f["analysis"]]["registry"]]
    for finding in findings:
        info = side[finding["analysis"]]
        if info["backed"]:
            continue
        if finding["trial"] is None or finding["standard_outcome_key"] is None or finding["treatment"] is None:
            continue
        candidates = [
            r for r in registry
            if r["trial"] == finding["trial"]
            and r["standard_outcome_key"] == finding["standard_outcome_key"]
            and str(r["treatment"]).lower() == str(finding["treatment"]).lower()
        ]
        matches = []
        for candidate in candidates:
            other = side[candidate["analysis"]]
            if info["cohorts"] and other["cohorts"]:
                if info["active"] & other["active"]:
                    matches.append(candidate)
            elif len(candidates) == 1:
                matches.append(candidate)
        if matches:
            finding["superseded_by"] = min(m["analysis"] for m in matches)


def _analysis_contests(
    findings: list[dict], registry_mode: bool = False, test_types: dict | None = None
) -> tuple[list[dict], list[dict]]:
    """Find StandardOutcome + treatment pairs whose analyses disagree on significance.

    Returns (contested, contradictions). A contested entry is also a
    contradiction when both sides include a high_evidence analysis. In
    registry mode superseded and non-inferiority findings take no part, and the
    contest is decided per trial (see _registry_contest_entry) on the per-title
    measure key (_base_measure_key), so a trial significant on one MACE
    variant and not on another is never made "mixed" by the shared key. The
    entries are then merged so one (outcome key, treatment, positive trials,
    negative trials) gives one entry: "MACE" and its three-component title
    reported by the same two trials are one contest, not one per title.
    test_types maps a registry analysis id to its registry non_inferiority_type
    (registry mode only; see _registry_test_types).

    CONTEST-02: in registry mode the group key is (measure key, outcome kind,
    treatment), so responder, continuous and time-to-event analyses of one
    measure and drug never contest each other. An unclassified finding joins
    the one classified kind of its (measure key, treatment) group, and stays
    apart only when two or more kinds are present (_split_by_kind). CONTEST-01: when every finding
    of a group has a dose_mg the group is split by dose (the same dose across
    trials contests, different doses do not) and its entries carry
    dose_aware: true and dose_mg; otherwise the group keeps the dose-free key
    and its entries carry dose_aware: false.
    """
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for finding in findings:
        if finding["significant"] is None:
            continue
        if finding["standard_outcome"] is None or finding["treatment"] is None:
            continue
        if registry_mode:
            if (
                finding.get("significance_source") == "ctgov_withdrawn"
                or finding.get("superseded_by")
                or finding.get("non_inferiority")
                or finding.get("standard_outcome_key") is None
            ):
                continue
            fine = _base_measure_key(finding["standard_outcome"]) or str(finding["standard_outcome_id"])
            key = (fine, str(finding["treatment"]).lower())
        else:
            key = (str(finding["standard_outcome"]).lower(), str(finding["treatment"]).lower())
        groups[key].append(finding)

    contested: list[dict] = []
    contradictions: list[dict] = []
    if registry_mode:
        return _registry_contests(_split_by_dose(_split_by_kind(groups)), test_types)
    for key, group in sorted(groups.items()):
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


def _split_by_kind(groups: dict) -> dict:
    """Split each (measure key, treatment) group by outcome kind.

    WR-01: an unknown kind is compatible, not a kind of its own. When the
    classified findings of a group have exactly one kind, the unclassified ones
    join it; with no classified finding the group keeps the kind "" (unknown);
    with two or more classified kinds each kind is its own group and the
    unclassified findings stay together under "". Keys become (measure key,
    kind, treatment).
    """
    out: dict[tuple, list[dict]] = {}
    for (fine, treatment), group in groups.items():
        kinds = sorted({f.get("outcome_kind") for f in group if f.get("outcome_kind")})
        for finding in group:
            kind = finding.get("outcome_kind") or ""
            if not kind and len(kinds) == 1:
                kind = kinds[0]
            out.setdefault((fine, kind, treatment), []).append(finding)
    return out


def _split_by_dose(groups: dict) -> dict:
    """Extend each (measure key, kind, treatment) group key with the dose.

    A group whose findings all have a dose_mg is split into one group per dose
    (key + (dose,)); any other group stays whole (key + (None,)).
    """
    out: dict[tuple, list[dict]] = {}
    for key, group in groups.items():
        if group and all(f.get("dose_mg") is not None for f in group):
            for finding in group:
                out.setdefault(key + (finding["dose_mg"],), []).append(finding)
        else:
            out[key + (None,)] = group
    return out


def _registry_contests(groups: dict, test_types: dict | None) -> tuple[list[dict], list[dict]]:
    """Decide registry contests per (per-title key, outcome kind, treatment, dose)
    group, then merge the entries that share (outcome key, kind, treatment, dose,
    positive trials, negative trials) into one, rebuilt from the union of their analyses. The merged
    entry is a contradiction when any of its parts is. Entries keep the order
    of their first part."""
    merged: dict[tuple, dict] = {}
    for key, group in sorted(groups.items()):
        entry, is_contradiction = _registry_contest_entry(key, group, test_types)
        if entry is None:
            continue
        coarse = str(group[0]["standard_outcome_key"])
        dedupe = (
            coarse, key[1], key[2], key[3],
            tuple(entry["positive_trials"]), tuple(entry["negative_trials"]),
        )
        slot = merged.setdefault(dedupe, {"entry": entry, "group": [], "parts": 0, "contradiction": False})
        slot["group"].extend(group)
        slot["parts"] += 1
        slot["contradiction"] = slot["contradiction"] or is_contradiction
    contested: list[dict] = []
    contradictions: list[dict] = []
    for (coarse, kind, treatment, dose, _, _), slot in merged.items():
        entry = slot["entry"]
        if slot["parts"] > 1:
            entry, _ = _registry_contest_entry((coarse, kind, treatment, dose), slot["group"], test_types)
        else:
            entry = {**entry, "standard_outcome_key": coarse}
        contested.append({**entry, "epistemic_status": "contested"})
        if slot["contradiction"]:
            contradictions.append({**entry, "epistemic_status": "contradiction"})
    return contested, contradictions


# CT.gov nonInferiorityType values. On a node that is not registry-sourced (an
# extracted analysis that received registry data) a plain non_inferiority_type
# is read only when it is one of these, so extracted free text never sets a
# design note.
CTGOV_TEST_TYPES = frozenset({
    "SUPERIORITY", "SUPERIORITY_OR_OTHER", "NON_INFERIORITY", "EQUIVALENCE",
    "NON_INFERIORITY_OR_EQUIVALENCE", "OTHER",
})


def _registry_test_types(nodes: list[dict]) -> dict[str, str]:
    """Map registry-backed OutcomeAnalysis id -> registry non_inferiority_type
    (upper case). A merged node's registry_non_inferiority_type comes first;
    its plain value counts only when the node is registry-sourced or the
    value is a CT.gov type (CTGOV_TEST_TYPES)."""
    out: dict[str, str] = {}
    for node in nodes:
        if not isinstance(node, dict) or str(node.get("entity_type", "")).lower() != ANALYSIS_TYPE:
            continue
        attrs = node.get("attributes")
        if not isinstance(attrs, dict) or not _is_registry_backed(attrs):
            continue
        registry_sourced = attrs.get("source") == REGISTRY_SOURCE
        for key in ("registry_non_inferiority_type", "non_inferiority_type"):
            value = attrs.get(key)
            if not (isinstance(value, str) and value.strip()):
                continue
            value = value.strip()
            if key == "non_inferiority_type" and not registry_sourced and value not in CTGOV_TEST_TYPES:
                continue
            out[str(node.get("id"))] = value.upper()
            break
    return out


def _design_note(positive: list[dict], negative: list[dict], test_types: dict | None) -> str | None:
    """A note when a compared analysis is registered with a non_inferiority_type
    other than SUPERIORITY (for example SUPERIORITY_OR_OTHER or OTHER), else None.

    The contest is kept: the note only says the registry does not record every
    compared analysis as a superiority test. Analyses without a registry type
    never add a note.
    """
    if not test_types:
        return None

    def side(findings) -> str:
        counts: dict[str, int] = defaultdict(int)
        for f in findings:
            counts[test_types.get(str(f["analysis"]), "not recorded")] += 1
        return ", ".join(f"{t} x{n}" for t, n in sorted(counts.items()))

    members = positive + negative
    if not any(
        test_types.get(str(f["analysis"])) not in (None, "SUPERIORITY") for f in members
    ):
        return None
    return (
        "non_inferiority_type other than SUPERIORITY on a compared analysis "
        f"(positive: {side(positive)}; negative: {side(negative)}); "
        "the registry does not record every compared analysis as a superiority test"
    )


def _registry_contest_entry(
    key: tuple, group: list[dict], test_types: dict | None = None
) -> tuple[dict | None, bool]:
    """Decide one registry-mode (measure key, outcome kind, treatment, dose) group at trial level.

    A trial is positive when all its analyses in the group are significant,
    negative when none is, and mixed otherwise (for example a dose-response
    split between dose arms). Only positive trials contest negative trials;
    mixed trials are listed but pair with nothing. The group is a
    contradiction when a high_evidence positive trial (every one of its
    analyses high_evidence) meets a high_evidence negative trial. The entry is
    named from the group key and its sorted member outcome ids, so it does not
    depend on node order. It carries design_note when a positive or negative
    analysis is registered with a non_inferiority_type other than SUPERIORITY
    (see _design_note). Returns (entry or None, is_contradiction).

    The key is (measure key, outcome kind, treatment, dose); a legacy
    (measure key, treatment) key reads as no kind and no dose. The entry
    carries outcome_kind (None when the kind is unknown) and dose_aware, plus
    dose_mg when dose_aware.
    """
    kind = (key[1] or None) if len(key) >= 4 else None
    dose = key[3] if len(key) >= 4 else None
    by_trial: dict[str, list[dict]] = defaultdict(list)
    for finding in group:
        if finding["trial"] is not None:
            by_trial[finding["trial"]].append(finding)
    positive_trials, negative_trials, mixed_trials = [], [], []
    for trial in sorted(by_trial, key=str):
        verdicts = {f["significant"] for f in by_trial[trial]}
        if verdicts == {True}:
            positive_trials.append(trial)
        elif verdicts == {False}:
            negative_trials.append(trial)
        else:
            mixed_trials.append(trial)
    if not positive_trials or not negative_trials:
        return None, False

    def members(trials, verdict=None):
        return sorted(
            (f for t in trials for f in by_trial[t] if verdict is None or f["significant"] is verdict),
            key=lambda f: str(f["analysis"]),
        )

    def high(trial) -> bool:
        return all(f["evidence_tier"] == "high_evidence" for f in by_trial[trial])

    positive = members(positive_trials)
    negative = members(negative_trials)
    outcome_ids = sorted({
        str(f["standard_outcome_id"]) for f in group if f.get("standard_outcome_id") is not None
    })
    representative = outcome_ids[0] if outcome_ids else None
    treated = min(group, key=lambda f: (str(f.get("treatment_id")), str(f["analysis"])))
    docs = sorted({d for f in group for d in f.get("support_documents") or []})
    # An outcome whose name normalizes to nothing keys on its own id; name the
    # entry after that outcome rather than the id.
    display = key[0]
    if key[0] in outcome_ids:
        display = next((
            str(f["standard_outcome"]) for f in sorted(group, key=lambda f: str(f["analysis"]))
            if str(f.get("standard_outcome_id")) == key[0] and f.get("standard_outcome")
        ), key[0])
    entry = {
        "standard_outcome": display,
        "standard_outcome_key": key[0],
        "standard_outcome_ids": outcome_ids,
        "outcome_kind": kind,
        "dose_aware": dose is not None,
        "treatment": treated["treatment"],
        "positive": [f["analysis"] for f in positive],
        "negative": [f["analysis"] for f in negative],
        "positive_tiers": [f["evidence_tier"] for f in positive],
        "negative_tiers": [f["evidence_tier"] for f in negative],
        "positive_trials": positive_trials,
        "negative_trials": negative_trials,
        "mixed_trials": [
            {
                "trial": trial,
                "positive": [f["analysis"] for f in members([trial], True)],
                "negative": [f["analysis"] for f in members([trial], False)],
            }
            for trial in mixed_trials
        ],
        "trials": sorted(by_trial, key=str),
        "basis": "outcome_analysis",
        # Standard fields read by core/epistemic_health.py
        "source": treated.get("treatment_id"),
        "target": representative,
        "source_entity": treated.get("treatment_id"),
        "target_entity": representative,
        "relation_type": ASSESSES,
        "mentions": [{"source_document": d} for d in docs],
        "support_documents": docs,
    }
    if dose is not None:
        entry["dose_mg"] = dose
    note = _design_note(positive, negative, test_types)
    if note:
        entry["design_note"] = note
    is_contradiction = any(high(t) for t in positive_trials) and any(high(t) for t in negative_trials)
    return entry, is_contradiction


# ---------------------------------------------------------------------------
# Main epistemic analysis function
# ---------------------------------------------------------------------------


def _linked_phases(nodes: list[dict], links: list[dict], trial_ids: set) -> dict[str, str]:
    """Map trial id -> name of its TrialPhase node, from is_phase links (either direction).

    Only a TrialPhase-typed endpoint counts. A trial linked to several keeps
    the most conservative (lowest) normalized phase, then the first seen.
    """
    phase_names = {
        n["id"]: n.get("name")
        for n in nodes
        if str(n.get("entity_type", "")).lower().replace("_", "") == "trialphase"
    }
    order = {"PHASE1": 1, "PHASE2": 2, "PHASE3": 3}
    found: dict[str, str] = {}
    for link in links:
        if link.get("relation_type") != "is_phase":
            continue
        src, tgt = link.get("source"), link.get("target")
        if src in trial_ids and tgt in phase_names:
            trial, name = src, phase_names[tgt]
        elif tgt in trial_ids and src in phase_names:
            trial, name = tgt, phase_names[src]
        else:
            continue
        if not isinstance(name, str):
            continue
        current = found.get(trial)
        if current is None:
            found[trial] = name
            continue
        new_rank = order.get(_normalize_phase(name) or "", 0)
        cur_rank = order.get(_normalize_phase(current) or "", 0)
        if 0 < new_rank < cur_rank or cur_rank == 0 and new_rank:
            found[trial] = name
    return found


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
    trial_ids = {
        n["id"] for n in nodes
        if str(n.get("entity_type", "")).lower() == "trial"
    }
    linked_phase = _linked_phases(nodes, links, trial_ids)
    # Shallow copies carry the linked phase; the input nodes are never mutated.
    trial_lookup: dict[str, dict] = {
        n["id"]: ({**n, "_linked_phase": linked_phase[n["id"]]} if n["id"] in linked_phase else dict(n))
        for n in nodes
        if n["id"] in trial_ids
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
    registry_mode = _graph_has_registry_data(nodes)
    arm_stats: dict = {}
    analysis_claims = _analysis_findings(
        nodes, links, trial_lookup, doc_trials, registry_mode=registry_mode, arm_stats=arm_stats
    )
    analysis_contested, analysis_contradictions = _analysis_contests(
        analysis_claims,
        registry_mode=registry_mode,
        test_types=_registry_test_types(nodes) if registry_mode else None,
    )
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

    summary = {
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
    }
    if registry_mode:
        by_source: dict[str, int] = defaultdict(int)
        for finding in analysis_claims:
            by_source[finding["significance_source"]] += 1
        summary["analysis_by_source"] = dict(sorted(by_source.items()))
        summary["analysis_superseded"] = sum(1 for f in analysis_claims if f.get("superseded_by"))
        summary["analysis_treatment_unresolved"] = sum(
            1 for f in analysis_claims if f["treatment"] is None
        )
        summary["analysis_non_inferiority"] = sum(
            1 for f in analysis_claims if f.get("non_inferiority")
        )
        summary["analysis_treatment_from_arm_type"] = sum(
            1 for f in analysis_claims if f.get("treatment_basis") == "registry_arm_type"
        )
        summary["analysis_treatment_arm_type_disagreements"] = arm_stats.get("disagreements", 0)
        summary["analysis_treatment_ambiguous_active_comparator"] = sum(
            1 for f in analysis_claims if f.get("treatment_basis") == "ambiguous_active_comparator"
        )
        summary["analysis_label_conflicts"] = sum(1 for f in analysis_claims if f.get("label_conflict"))
        summary["analysis_registry_withdrawn"] = sum(
            1 for f in analysis_claims if f.get("registry_withdrawn")
        )
        kind_counts: dict[str, int] = defaultdict(int)
        for finding in analysis_claims:
            kind_counts[finding.get("outcome_kind") or "unknown"] += 1
        summary["analysis_outcome_kind_counts"] = dict(sorted(kind_counts.items()))
        summary["analysis_contests_dose_aware"] = sum(
            1 for c in analysis_contested if c.get("dose_aware")
        )
        summary["analysis_contests_dose_fallback"] = sum(
            1 for c in analysis_contested if c.get("dose_aware") is False
        )

    return {
        "metadata": {
            "description": "Clinical-trial epistemic layer — phase-based evidence grading",
            "domain": "clinicaltrials",
            "generated_from": str(output_dir / "graph_data.json"),
            "total_relations": claim_count,
            "trial_count": len(trial_lookup),
        },
        "summary": summary,
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
