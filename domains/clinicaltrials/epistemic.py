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
   decides only when the ratio and difference nulls agree.

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
# Comparator arms are told apart by name; arm_type is not a signal because
# active arms carry "Active comparator".
PLACEBO_KEYWORDS = ("placebo", "comparator", "standard of care", "usual care", "control")
_PLACEBO_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:" + "|".join(re.escape(k) for k in PLACEBO_KEYWORDS) + r")(?![A-Za-z0-9])",
    re.IGNORECASE,
)
MIN_COMPOUND_NAME = 3
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


def _is_registry_backed(attrs) -> bool:
    """True for a node created by, or merged with, the registry import."""
    if not isinstance(attrs, dict):
        return False
    if attrs.get("source") == REGISTRY_SOURCE:
        return True
    sources = attrs.get("sources")
    return isinstance(sources, list) and REGISTRY_SOURCE in sources


def _significance_from_view(view: dict) -> bool | None:
    """Decide significance from p / CI statistics alone (no `significant` flag).

    The reported p text keeps its comparator ("<0.05"), so it decides first;
    p_value_num is the fallback and must be a probability. Then the confidence
    interval against the null (1.0 for ratio measures, 0 for differences; an
    unknown measure decides only when both nulls agree).
    """
    decided = _p_significance(_parse_p_value(view.get("p_value")))
    if decided is not None:
        return decided
    p_num = _number(view.get("p_value_num"))
    if p_num is not None and 0.0 <= p_num <= 1.0:
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


def _registry_group_view(attrs: dict, group: tuple) -> dict | None:
    """The registry side of one statistic group on a merged node, or None.

    Present only when the registry import stored at least one registry_<key>
    of the group. The view holds registry values only, so a registry number is
    never read beside an extracted p text or an extracted interval bound. The
    one exception is effect_measure, which names the scale of the registry
    interval and is read from the plain attribute when the registry did not
    store a different one.
    """
    view = {
        k: attrs[f"registry_{k}"] for k in group if attrs.get(f"registry_{k}") is not None
    }
    if not view:
        return None
    if "effect_measure" in group and "effect_measure" not in view:
        view["effect_measure"] = attrs.get("effect_measure")
    return view


def _analysis_significance_with_source(node: dict) -> tuple[bool | None, str]:
    """(significance, source) of an OutcomeAnalysis node.

    source is "ctgov_results" when a registry-backed statistic group decided,
    else "extracted". On a registry-backed node a decision from the registry
    p group or CI group wins over an extracted `significant` flag; the flag is
    consulted only when neither registry group decides. A node that is not
    registry-backed keeps the original order: the flag, then p, then CI.
    """
    attrs = node.get("attributes")
    if not isinstance(attrs, dict):
        return None, "extracted"

    if attrs.get("source") == REGISTRY_SOURCE:
        # A registry node: its plain statistics are the registry's.
        decided = _significance_from_view(attrs)
        if decided is not None:
            return decided, REGISTRY_SOURCE
    elif _is_registry_backed(attrs):
        # A merged node: registry statistics sit beside the extracted ones.
        for group in (ANALYSIS_P_GROUP, ANALYSIS_CI_GROUP):
            view = _registry_group_view(attrs, group)
            if view is None:
                continue
            decided = _significance_from_view(view)
            if decided is not None:
                return decided, REGISTRY_SOURCE

    flag = attrs.get("significant")
    if isinstance(flag, bool):
        return flag, "extracted"
    if attrs.get("source") == REGISTRY_SOURCE:
        return None, "extracted"
    return _significance_from_view(attrs), "extracted"


def _analysis_significance(node: dict) -> bool | None:
    """Whether an OutcomeAnalysis node reports a statistically significant result.

    Precedence: on a registry-backed node, the registry p or CI statistics;
    then a bool `significant` attribute, then the parsed `p_value` text (it
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


def normalize_measure(name) -> str:
    """Reduce an outcome-measure name to a canonical key."""
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
    return MEASURE_SYNONYMS.get(s, s)


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
        if _is_registry_backed(attrs):
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
    """(compound id, word-boundary pattern) for every Compound name of 3+ chars."""
    patterns = []
    for node_id in sorted(by_id, key=str):
        node = by_id[node_id]
        if str(node.get("entity_type", "")).lower() != "compound":
            continue
        name = str(node.get("name") or "").strip()
        if len(name) < MIN_COMPOUND_NAME:
            continue
        patterns.append((node_id, re.compile(
            r"(?<![A-Za-z0-9])" + re.escape(name) + r"(?![A-Za-z0-9])", re.IGNORECASE
        )))
    return patterns


def _compounds_in_text(text, patterns: list[tuple[str, re.Pattern]]) -> set[str]:
    """Compound ids whose name appears in text at a word boundary."""
    if not isinstance(text, str) or not text or _PLACEBO_RE.search(text):
        return set()
    return {compound_id for compound_id, pattern in patterns if pattern.search(text)}


def _is_placebo_cohort(cohort: dict, received_names: list[str]) -> bool:
    """A comparator arm: a placebo/comparator keyword in its name, arm label or
    group description, or every compound or intervention it receives is placebo.
    """
    attrs = cohort.get("attributes") if isinstance(cohort.get("attributes"), dict) else {}
    for text in (cohort.get("name"), attrs.get("arm_label"), attrs.get("group_description")):
        if isinstance(text, str) and _PLACEBO_RE.search(text):
            return True
    return bool(received_names) and all("placebo" in name.lower() for name in received_names)


def _registry_treatment(
    node_id, attrs: dict, related, by_id: dict, adjacency, patterns, cohort_info
) -> tuple[str | None, set[str]]:
    """Resolve the treatment compound from compares Cohorts and registry group titles.

    Placebo and comparator arms are dropped before any name match, because a
    placebo arm's name can contain the compound ("Semaglutide placebo 0.5 mg").
    Returns (compound id or None, non-placebo compared cohort ids). The
    treatment is set only when exactly one compound results.
    """
    cohorts = related(node_id, COMPARES, "cohort")
    active = [c for c in cohorts if not cohort_info(c)[0]]
    compounds: set[str] = set()
    for cohort_id in active:
        direct = related(cohort_id, RECEIVES, "compound")
        found = set(direct)
        for intervention in related(cohort_id, RECEIVES, "intervention"):
            found.update(related(intervention, CONTAINS, "compound"))
        if not found:
            found = _compounds_in_text(by_id[cohort_id].get("name"), patterns)
        compounds.update(found)

    # Group titles that matched no Cohort stand in for the missing arm. With no
    # compared Cohort, or only comparator ones, the active arm is one of the
    # compared group titles.
    titles = attrs.get("unmatched_groups") if active else attrs.get("compared_groups")
    for title in titles if isinstance(titles, list) else ():
        compounds.update(_compounds_in_text(title, patterns))

    treatment = next(iter(compounds)) if len(compounds) == 1 else None
    return treatment, set(active)


def _analysis_findings(
    nodes: list[dict], links: list[dict], trial_lookup: dict, doc_trials: dict,
    registry_mode: bool = False,
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

    def cohort_info(cohort_id) -> tuple[bool]:
        if cohort_id not in placebo_cache:
            received = [
                str(by_id[t].get("name") or "")
                for t in sorted({
                    o for r, o in adjacency.get(cohort_id, ())
                    if r == RECEIVES and o in by_id
                })
            ]
            placebo_cache[cohort_id] = _is_placebo_cohort(by_id[cohort_id], received)
        return (placebo_cache[cohort_id],)

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
        compounds = related(node_id, ASSESSES, "compound")
        if compounds:
            treatment_id = compounds[0]
        else:
            interventions = related(node_id, ASSESSES, "intervention")
            if interventions:
                contained = related(interventions[0], CONTAINS, "compound")
                treatment_id = contained[0] if contained else interventions[0]
        active_cohorts: set[str] = set()
        if registry_mode:
            fallback, active_cohorts = _registry_treatment(
                node_id, attrs, related, by_id, adjacency, patterns, cohort_info
            )
            if treatment_id is None:
                treatment_id = fallback
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
            if backed:
                for nct in _node_ncts(node, attrs):
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
            finding["significance_source"] = significance_source
            finding["sources"] = sources
            finding["standard_outcome_key"] = (
                normalize_measure(standard_outcome) if standard_outcome else None
            )
            side[node_id] = {
                "registry": attrs.get("source") == REGISTRY_SOURCE,
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


def _analysis_contests(findings: list[dict], registry_mode: bool = False) -> tuple[list[dict], list[dict]]:
    """Find StandardOutcome + treatment pairs whose analyses disagree on significance.

    Returns (contested, contradictions). A contested entry is also a
    contradiction when both sides include a high_evidence analysis. In
    registry mode analyses group by their normalized outcome key, and
    superseded findings take no part.
    """
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for finding in findings:
        if finding["significant"] is None:
            continue
        if finding["standard_outcome"] is None or finding["treatment"] is None:
            continue
        if registry_mode:
            if finding.get("superseded_by") or finding.get("standard_outcome_key") is None:
                continue
            key = (str(finding["standard_outcome_key"]), str(finding["treatment"]).lower())
        else:
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
    analysis_claims = _analysis_findings(
        nodes, links, trial_lookup, doc_trials, registry_mode=registry_mode
    )
    analysis_contested, analysis_contradictions = _analysis_contests(
        analysis_claims, registry_mode=registry_mode
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
