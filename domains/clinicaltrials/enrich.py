#!/usr/bin/env python3
"""ClinicalTrials.gov + PubChem enrichment for the clinicaltrials domain.

Post-build enrichment step invoked by /epistract:ingest when --enrich is
passed with --domain clinicaltrials. Reads the built graph via
sift_kg.KnowledgeGraph.load(), patches Trial nodes with CT.gov v2 metadata
(overall_status, phase, enrollment, dates, title, allocation, masking) and Compound nodes with
PubChem PUG REST molecular data (CID, formula, weight, SMILES, InChI),
then saves and writes _enrichment_report.json.

Opt-in results mode (--results): the same per-trial CT.gov payload that feeds
the ct_* fields also carries resultsSection. With --results it is parsed
(serious adverse events, other adverse events at or above the registry
frequency threshold with a 5% floor, PRIMARY/SECONDARY outcome analyses) and
imported into the graph as AdverseEvent, OrganSystem, OutcomeAnalysis,
Outcome and StatisticalMethod nodes with their edges. Every registry node and
edge is tagged source "ctgov_results" with the NCT. Registry data is merged into
matching extracted nodes (conflicts are kept as registry_<attr>), a repeated
run changes nothing, and registry groups that match no extracted Cohort never
create one. Analyses merge only into an extracted analysis of the same trial
that compares the same arms (or has the same effect measure and estimate).
Each registry analysis also records ctgov_arm_groups: the CT.gov armGroup type
and interventions of every compared group that names an armGroup, added only
when missing (a re-run backfills it; an existing value is never overwritten).
An opt-in per-arm floor for serious events (--results-serious-min-pct X,
default 0 = every serious event) keeps a serious event only when at least one
arm reaches X percent affected; the report then records the floor and the
number of serious records omitted, and the AE edges carry serious_min_pct.
The floor applies to a trial's first import only: when a trial's registry AE
edges were written under another floor, its AEs are left as they are and the
trial is listed under serious_min_pct_conflicts (re-enrich the un-enriched
graph to change the floor).
The "results" block of _enrichment_report.json counts the parsed records and
the graph writes (created, merged); a trial whose write fails is rolled back
and listed under write_errors. Without --results, behaviour is unchanged.

Non-blocking: API failures log counts but never abort the pipeline.
ARCH-03: no core/ changes required; this module lives in the domain package.

Usage:
    python3 domains/clinicaltrials/enrich.py <output_dir> [--results] [--cache-dir DIR]
        [--results-serious-min-pct X]

    --results         also import posted results into the graph and add a "results" report block
    --cache-dir DIR   read/write one raw CT.gov payload per trial as DIR/<NCT>.json
    --results-serious-min-pct X
                      opt-in volume control for --results: keep a serious adverse event only
                      when at least one arm has X percent or more affected (default 0: keep
                      every serious event, the 3.5.0 behaviour); needs --results
"""
from __future__ import annotations

import copy
import json
import re
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

NCT_PATTERN = re.compile(r"NCT\d{8}", re.IGNORECASE)

CTGOV_URL = "https://clinicaltrials.gov/api/v2/studies/{nct_id}"
CTGOV_TIMEOUT = 15
CTGOV_RATE_SLEEP = 0.1  # per-request courtesy delay (CT.gov has no documented limit)

AE_FREQUENCY_FLOOR_PCT = 5.0  # used when the registry frequencyThreshold is 0/absent
SERIOUS_MIN_PCT_DEFAULT = 0.0  # opt-in per-arm floor for serious events; 0 keeps every one
RESULTS_OUTCOME_TYPES = frozenset({"PRIMARY", "SECONDARY"})

PUBCHEM_PROPS = "MolecularFormula,MolecularWeight,CanonicalSMILES,InChI"
PUBCHEM_URL = (
    "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{name}/"
    "property/{props}/JSON"
)
PUBCHEM_TIMEOUT = 30
PUBCHEM_RATE_SLEEP = 0.2  # 5 req/sec official limit
PUBCHEM_MAX_RETRIES = 3

REGISTRY_SOURCE = "ctgov_results"
REGISTRY_CONFIDENCE = 0.99
# OutcomeAnalysis statistic fields that describe one statistic and merge as a
# group: a group fills from the registry only when the extracted node has none
# of its fields, so a node never pairs a paper's estimate with a registry CI.
ANALYSIS_STAT_GROUPS = (
    ("p_value", "p_value_num", "p_value_qualifier"),
    ("effect_estimate", "effect_measure", "ci_lower", "ci_upper", "ci_level", "ci_sides"),
)

_MEASURE_PREFIXES = (
    "percentage of participants achieving",
    "change from baseline in",
    "mean change in",
    "change in",
)

_MEASURE_SYNONYMS = {
    "body mass index": "bmi",
    "glycated haemoglobin": "hba1c",
    "glycated hemoglobin": "hba1c",
    "hemoglobin a1c": "hba1c",
    "haemoglobin a1c": "hba1c",
    "systolic blood pressure": "sbp",
}

_PAREN_RE = re.compile(r"\([^)]*\)")
_WEEK_RE = re.compile(r"\s+at\s+weeks?\s+\d+\s*$")
_WS_RE = re.compile(r"\s+")

# British -> US spelling stems folded into one AE key. Rules are stem-anchored:
# an unanchored "oedem"/"oestr" would also rewrite US compounds whose prefix ends
# in "o" (hyp-o-estrogenism, angi-o-edema, phyt-o-estrogen, xen-o-estrogen) and
# split them from the British form. "oestr" folds only where British spelling
# puts it (word start, after "o", "er" or "yl": Oestradiol, Hypooestrogenism,
# Hyperoestrogenism, Ethinyloestradiol), so unknown US compounds stay unfolded;
# "oedem" keeps its "angi" lookbehind (British -oedema compounds such as
# Lymphoedema and Lipoedema need the fold) and "angio-oedem" folds its hyphen
# first. "aesthe" covers -aesthesia and anaesthetic/anaesthetist. "leuc" only
# before "o" and not in Leucovorin (Leucopenia), leaving Leucine alone.
_US_SPELLING = [
    (re.compile(r"angio-oedem", re.IGNORECASE), "angioedem"),
    (re.compile(r"(?<!angi)oedem", re.IGNORECASE), "edem"),
    (re.compile(r"oesophag", re.IGNORECASE), "esophag"),
    (re.compile(r"rhoe", re.IGNORECASE), "rhe"),
    (re.compile(r"pnoe", re.IGNORECASE), "pne"),  # dys/a/tachy/ortho/hypo/brady/hyperpnoea
    (re.compile(r"(?:(?<![a-z])|(?<=o)|(?<=er)|(?<=yl))oestr", re.IGNORECASE), "estr"),
    (re.compile(r"foet", re.IGNORECASE), "fet"),
    (re.compile(r"coeliac", re.IGNORECASE), "celiac"),
    (re.compile(r"amoeb", re.IGNORECASE), "ameb"),
    (re.compile(r"aesthe", re.IGNORECASE), "esthe"),  # para/hypo/an/dysaesthesia, anaesthetic
    (re.compile(r"faec", re.IGNORECASE), "fec"),
    (re.compile(r"gynaec", re.IGNORECASE), "gynec"),
    (re.compile(r"leuc(?=o(?!vorin))", re.IGNORECASE), "leuk"),
    (re.compile(r"ae(?=m)", re.IGNORECASE), "e"),
    (re.compile(r"haem", re.IGNORECASE), "hem"),
    (re.compile(r"tumour", re.IGNORECASE), "tumor"),
]

_COHORT_STOP_WORDS = frozenset({
    "mg", "mcg", "ug", "µg", "g", "iu", "unit", "units", "arm", "group", "cohort",
    "dose", "once", "weekly", "daily", "qw", "qd", "sc", "s", "c", "oral", "the",
    "of", "and", "or", "with",
})

_P_VALUE_RE = re.compile(
    r"^p?\s*(<=|≤|>=|≥|<|>|=)?\s*((?:\d+\.?\d*|\.\d+)(?:e-?\d+)?)$"
)
_P_QUALIFIERS = {"<": "<", "<=": "<", "≤": "<", ">": ">", ">=": ">", "≥": ">", "=": "=", None: "="}

# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def _extract_nct_id(text: str) -> str | None:
    """Return the first NCT number in text, uppercased, or None."""
    if not text:
        return None
    m = NCT_PATTERN.search(text)
    return m.group().upper() if m else None


def _fetch_ct_gov_study(nct_id: str) -> dict | None:
    """Fetch the full CT.gov v2 study payload, or None on 404 / any error."""
    try:
        resp = requests.get(CTGOV_URL.format(nct_id=nct_id), timeout=CTGOV_TIMEOUT)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        body = resp.json()
    except (requests.RequestException, ValueError):
        return None
    return body if isinstance(body, dict) else None


def _parse_ct_protocol(study: dict) -> dict:
    """Flat ct_* dict from the protocolSection of a CT.gov study payload."""
    ps = study.get("protocolSection", {}) or {}
    id_mod = ps.get("identificationModule", {}) or {}
    status_mod = ps.get("statusModule", {}) or {}
    design_mod = ps.get("designModule", {}) or {}
    phases = design_mod.get("phases") or []
    enrollment_info = design_mod.get("enrollmentInfo") or {}
    design_info = design_mod.get("designInfo") or {}
    masking_info = design_info.get("maskingInfo") or {}
    start_struct = status_mod.get("startDateStruct") or {}
    completion_struct = status_mod.get("completionDateStruct") or {}
    return {
        "ct_overall_status": status_mod.get("overallStatus"),
        "ct_phase": phases[0] if phases else None,
        "ct_enrollment": enrollment_info.get("count"),
        "ct_start_date": start_struct.get("date"),
        "ct_completion_date": completion_struct.get("date"),
        "ct_brief_title": id_mod.get("briefTitle"),
        # Design fields read by epistemic.py's evidence grading:
        # masking NONE (open-label) caps a trial at medium_evidence.
        "ct_allocation": design_info.get("allocation"),
        "ct_masking": masking_info.get("masking"),
    }


def _fetch_ct_gov(nct_id: str) -> dict | None:
    """Fetch trial metadata from ClinicalTrials.gov v2 API.

    Returns a flat dict with ct_* keys, or None on 404 / any error.
    """
    study = _fetch_ct_gov_study(nct_id)
    return _parse_ct_protocol(study) if study is not None else None


def _get_ct_gov_study(nct_id: str, cache_dir) -> tuple[dict | None, bool]:
    """Return (study, fetched_from_network), reading/writing cache_dir if given."""
    if cache_dir is None:
        time.sleep(CTGOV_RATE_SLEEP)
        return _fetch_ct_gov_study(nct_id), True
    cache_file = Path(cache_dir) / f"{nct_id}.json"
    try:
        cached = json.loads(cache_file.read_text())
        if isinstance(cached, dict):
            return cached, False
    except (OSError, ValueError):
        pass
    time.sleep(CTGOV_RATE_SLEEP)
    study = _fetch_ct_gov_study(nct_id)
    if study is not None:
        try:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(json.dumps(study))
        except OSError:
            pass
    return study, True


def _as_list(value) -> list:
    return value if isinstance(value, list) else []


def _as_dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _parse_ct_results(study: dict, serious_min_pct: float = SERIOUS_MIN_PCT_DEFAULT) -> dict | None:
    """Parse posted results from a CT.gov study payload.

    Returns None when the trial has no posted results. Otherwise returns
    event groups, adverse events (all serious; other events at or above the
    frequency threshold) and PRIMARY/SECONDARY outcome analyses.

    serious_min_pct > 0 also applies a per-arm floor to serious events: one is
    kept only when some arm has at least that percent affected (an event with
    no computable rate is dropped, as for other events). The result then gains
    "serious_min_pct" and "serious_events_omitted"; with the default 0 the
    result is unchanged.
    """
    if study.get("hasResults") is not True:
        return None
    results = study.get("resultsSection")
    if not isinstance(results, dict) or not results:
        return None

    id_mod = _as_dict(_as_dict(study.get("protocolSection")).get("identificationModule"))
    ae_mod = _as_dict(results.get("adverseEventsModule"))

    threshold = AE_FREQUENCY_FLOOR_PCT
    source = "floor"
    try:
        registry = float(ae_mod.get("frequencyThreshold"))
        if registry > 0:
            threshold, source = registry, "registry"
    except (TypeError, ValueError):
        pass

    event_groups = []
    titles: dict = {}
    for g in _as_list(ae_mod.get("eventGroups")):
        g = _as_dict(g)
        titles[g.get("id")] = g.get("title")
        event_groups.append({
            "id": g.get("id"),
            "title": g.get("title"),
            "deaths_num_affected": g.get("deathsNumAffected"),
            "deaths_num_at_risk": g.get("deathsNumAtRisk"),
            "serious_num_affected": g.get("seriousNumAffected"),
            "serious_num_at_risk": g.get("seriousNumAtRisk"),
            "other_num_affected": g.get("otherNumAffected"),
            "other_num_at_risk": g.get("otherNumAtRisk"),
        })

    def _stats(event: dict) -> list:
        out = []
        for st in _as_list(event.get("stats")):
            st = _as_dict(st)
            out.append({
                "group_id": st.get("groupId"),
                "group_title": titles.get(st.get("groupId")),
                "num_events": st.get("numEvents"),
                "num_affected": st.get("numAffected"),
                "num_at_risk": st.get("numAtRisk"),
            })
        return out

    def _reaches(stats: list, floor: float = threshold) -> bool:
        for st in stats:
            at_risk, affected = st["num_at_risk"], st["num_affected"]
            if (
                isinstance(at_risk, (int, float)) and at_risk > 0
                and isinstance(affected, (int, float))
                and affected / at_risk * 100 >= floor
            ):
                return True
        return False

    adverse_events = []
    serious_omitted = 0
    for seriousness, key in (("serious", "seriousEvents"), ("other", "otherEvents")):
        for ev in _as_list(ae_mod.get(key)):
            ev = _as_dict(ev)
            stats = _stats(ev)
            if seriousness == "other" and not _reaches(stats):
                continue
            if seriousness == "serious" and serious_min_pct > 0 and not _reaches(stats, serious_min_pct):
                serious_omitted += 1
                continue
            adverse_events.append({
                "term": ev.get("term"),
                "organ_system": ev.get("organSystem"),
                "source_vocabulary": ev.get("sourceVocabulary"),
                "assessment_type": ev.get("assessmentType"),
                "seriousness": seriousness,
                "stats": stats,
            })

    analyses = []
    om_mod = _as_dict(results.get("outcomeMeasuresModule"))
    for om in _as_list(om_mod.get("outcomeMeasures")):
        om = _as_dict(om)
        if om.get("type") not in RESULTS_OUTCOME_TYPES:
            continue
        groups = {
            _as_dict(g).get("id"): _as_dict(g).get("title")
            for g in _as_list(om.get("groups"))
        }
        for an in _as_list(om.get("analyses")):
            an = _as_dict(an)
            analyses.append({
                "outcome_title": om.get("title"),
                "outcome_type": om.get("type"),
                "time_frame": om.get("timeFrame"),
                "outcome_param_type": om.get("paramType"),
                "unit": om.get("unitOfMeasure"),
                "groups": groups,
                "group_ids": an.get("groupIds") or [],
                "p_value": an.get("pValue"),
                "statistical_method": an.get("statisticalMethod"),
                "param_type": an.get("paramType"),
                "param_value": an.get("paramValue"),
                "ci_pct_value": an.get("ciPctValue"),
                "ci_num_sides": an.get("ciNumSides"),
                "ci_lower_limit": an.get("ciLowerLimit"),
                "ci_upper_limit": an.get("ciUpperLimit"),
                "non_inferiority_type": an.get("nonInferiorityType"),
            })

    arm_groups = []
    arms_mod = _as_dict(_as_dict(study.get("protocolSection")).get("armsInterventionsModule"))
    for arm in _as_list(arms_mod.get("armGroups")):
        arm = _as_dict(arm)
        arm_type = arm.get("type")
        arm_groups.append({
            "label": arm.get("label"),
            "type": str(arm_type).upper() if isinstance(arm_type, str) and arm_type else None,
            "interventions": [
                str(i) for i in _as_list(arm.get("interventionNames")) if isinstance(i, str)
            ],
        })

    parsed = {
        "nct_id": id_mod.get("nctId"),
        "ae_threshold_pct": threshold,
        "ae_threshold_source": source,
        "event_groups": event_groups,
        "adverse_events": adverse_events,
        "analyses": analyses,
        "arm_groups": arm_groups,
    }
    if serious_min_pct > 0:
        parsed["serious_min_pct"] = serious_min_pct
        parsed["serious_events_omitted"] = serious_omitted
    return parsed


def _fetch_pubchem(compound_name: str) -> dict | None:
    """Fetch molecular data from PubChem PUG REST.

    Retries up to PUBCHEM_MAX_RETRIES times on 429 with exponential backoff.
    Reads ConnectivitySMILES from response (PubChem API quirk — see
    21-RESEARCH.md Pitfall 2: the request asks for CanonicalSMILES but the
    JSON response always returns the key 'ConnectivitySMILES').
    Returns None on 404 or after exhausted retries.
    """
    url = PUBCHEM_URL.format(
        name=requests.utils.quote(compound_name),
        props=PUBCHEM_PROPS,
    )
    for attempt in range(PUBCHEM_MAX_RETRIES):
        try:
            resp = requests.get(url, timeout=PUBCHEM_TIMEOUT)
            if resp.status_code == 404:
                return None
            if resp.status_code == 429:
                time.sleep(2 ** attempt)
                continue
            resp.raise_for_status()
            body = resp.json()
        except (requests.RequestException, ValueError):
            if attempt == PUBCHEM_MAX_RETRIES - 1:
                return None
            time.sleep(2 ** attempt)
            continue

        props_list = (body.get("PropertyTable") or {}).get("Properties") or []
        if not props_list:
            return None
        p = props_list[0]
        return {
            "pubchem_cid": p.get("CID"),
            "molecular_formula": p.get("MolecularFormula"),
            "molecular_weight": p.get("MolecularWeight"),
            # CRITICAL: response key is ConnectivitySMILES (Pitfall 2)
            "canonical_smiles": p.get("ConnectivitySMILES"),
            "inchi": p.get("InChI"),
        }
    return None


# ---------------------------------------------------------------------------
# Registry results import: pure helpers
# ---------------------------------------------------------------------------


def _slug(text) -> str:
    """Lowercase, runs of non [a-z0-9] collapsed to '_', ends stripped."""
    return re.sub(r"[^a-z0-9]+", "_", str(text or "").lower()).strip("_")


def _ae_key(name: str) -> str:
    """Spelling/case/plural-insensitive key: equal keys are one adverse event."""
    s = (name or "").lower().strip()
    for rx, rep in _US_SPELLING:
        s = rx.sub(rep, s)
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:-1] if s.endswith("s") and not s.endswith("ss") else s


def normalize_measure(name: str) -> str:
    """Reduce an outcome-measure name to a canonical key."""
    s = _WS_RE.sub(" ", (name or "").lower()).strip()
    for prefix in _MEASURE_PREFIXES:
        if s.startswith(prefix) and (len(s) == len(prefix) or not s[len(prefix)].isalnum()):
            s = s[len(prefix):].lstrip()
            break
    s = _PAREN_RE.sub(" ", s)
    s = _WS_RE.sub(" ", s).strip()
    s = _WEEK_RE.sub("", s)
    s = re.sub(r"[\s.,;:]+$", "", s)
    s = _WS_RE.sub(" ", s).strip()
    return _MEASURE_SYNONYMS.get(s, s)


def _parse_p_value(text) -> tuple:
    """Return (numeric p-value, qualifier) from registry text, or (None, None)."""
    if not isinstance(text, str):
        return None, None
    m = _P_VALUE_RE.match(text.strip().lower())
    if not m:
        return None, None
    try:
        return float(m.group(2)), _P_QUALIFIERS[m.group(1)]
    except (ValueError, KeyError):
        return None, None


def _to_float(value) -> float | None:
    """Float of a registry numeric string; None for absent, 'NA' or unparseable."""
    if value is None or isinstance(value, bool):
        return None
    try:
        out = float(str(value).strip())
    except ValueError:
        return None
    return out if out == out and out not in (float("inf"), float("-inf")) else None


def _norm_arm(text) -> str:
    """Normalize an arm or group label for comparison."""
    s = str(text or "").lower()
    s = re.sub(r"(?<=\d)(?=[a-zµ])", " ", s)
    s = re.sub(r"[^a-z0-9µ. ]+", " ", s)
    s = re.sub(r"(?<!\d)\.|\.(?!\d)", " ", s)
    return _WS_RE.sub(" ", s).strip()


def _arm_tokens(text) -> tuple:
    """(dose numbers, drug words) of a normalized arm label."""
    doses, words = set(), set()
    for tok in _norm_arm(text).split():
        if re.fullmatch(r"\d+(?:\.\d+)?", tok):
            doses.add(tok)
        elif tok.isalpha() and tok not in _COHORT_STOP_WORDS:
            words.add(tok)
    return frozenset(doses), frozenset(words)


def _match_label(title, candidates) -> str | None:
    """Return the key of the one candidate matching a registry group title, else None.

    candidates is a list of (key, texts): each text is a name or label the
    candidate answers to (None and empty texts are skipped). Exact normalized
    match first; then equal dose numbers with a drug-word subset relation. Zero
    or several candidates return None (a match is never guessed).
    """
    want = _norm_arm(title)
    if not want:
        return None
    exact = {
        key for key, texts in candidates
        if any(t and want == _norm_arm(t) for t in texts)
    }
    if exact:
        return next(iter(exact)) if len(exact) == 1 else None
    doses, words = _arm_tokens(title)
    if not words:
        return None
    found = set()
    for key, texts in candidates:
        for text in texts:
            if not text:
                continue
            c_doses, c_words = _arm_tokens(text)
            if c_doses == doses and c_words and (words <= c_words or c_words <= words):
                found.add(key)
    return next(iter(found)) if len(found) == 1 else None


def _match_cohort(title, cohorts) -> str | None:
    """Return the id of the one cohort matching a registry group title, else None.

    cohorts is a list of (cohort_id, name, arm_label_or_None); see _match_label.
    """
    return _match_label(title, [(cid, [name, label]) for cid, name, label in cohorts])


def _decimals(value) -> int:
    text = repr(float(value))
    return len(text.split(".")[1].rstrip("0")) if "." in text and "e" not in text else 0


def _same_estimate(a, b) -> bool:
    """Equal within rounding: at most half a unit of the coarser stated precision
    apart, and never coarser than one decimal place (so 1.0 does not match 0.55)."""
    try:
        a, b = float(a), float(b)
    except (TypeError, ValueError):
        return False
    places = max(1, min(_decimals(a), _decimals(b)))
    return abs(a - b) <= 0.5 * 10 ** -places + 1e-9


# ---------------------------------------------------------------------------
# Registry results import: graph writes
# ---------------------------------------------------------------------------


def _new_counters() -> dict:
    return {
        "created_nodes": 0, "created_edges": 0, "merged": 0, "ae_index": None,
        "cross_trial_ae_links_ignored": 0,
    }


def _node_attrs(kg, node_id: str) -> dict:
    data = kg.graph.nodes[node_id]
    attrs = data.get("attributes")
    if not isinstance(attrs, dict):
        attrs = {}
        data["attributes"] = attrs
    return attrs


def _append_unique(container: dict, key: str, value) -> bool:
    """Append value to the list container[key] when absent; True when added."""
    items = container.get(key)
    if not isinstance(items, list):
        items = [] if items in (None, "") else [items]
        container[key] = items
    if value in items:
        return False
    items.append(value)
    return True


def _merge_attrs(target: dict, attrs: dict, rename: dict | None = None, groups=()) -> None:
    """Fill missing attributes; keep a differing existing value, store the new
    one as registry_<attr>. Never deletes or overwrites.

    For each group in groups: when the target has any of the group's fields,
    none of them is filled; every new value that differs from or is absent on
    the target is stored as registry_<attr> instead.
    """
    rename = rename or {}
    held: set = set()
    for group in groups:
        if not any(target.get(k) not in (None, "", []) for k in group):
            continue
        for key in group:
            held.add(key)
            value = attrs.get(key)
            if value is not None and target.get(key) != value:
                target.setdefault(rename.get(key, f"registry_{key}"), value)
    for key, value in attrs.items():
        if value is None or key in held:
            continue
        current = target.get(key)
        if current in (None, "", []):
            target[key] = value
        elif isinstance(current, dict) and isinstance(value, dict):
            for sub, subvalue in value.items():
                current.setdefault(sub, subvalue)
        elif current != value:
            target.setdefault(rename.get(key, f"registry_{key}"), value)


def _merge_into_node(kg, node_id, attrs, nct, counters, rename=None, count=False, groups=()) -> bool:
    """Merge registry attributes into an existing node under the merge rules.

    Returns True when this NCT was newly recorded on the node.
    """
    node = kg.graph.nodes[node_id]
    target = _node_attrs(kg, node_id)
    if nct in (target.get("ctgov_nct_ids") or []):
        return False
    if target.get("source") == REGISTRY_SOURCE:
        _append_unique(node, "source_documents", f"ctgov:{nct}")
        _merge_attrs(target, attrs, rename)
    else:
        _merge_attrs(target, attrs, rename, groups)
        _append_unique(target, "sources", REGISTRY_SOURCE)
        if count:
            counters["merged"] += 1
    _append_unique(target, "ctgov_nct_ids", nct)
    return True


def _upsert_node(kg, node_id, etype, name, attrs, nct, counters, rename=None, count=False):
    """Create a registry node, or merge into the existing node with this id."""
    if kg.graph.has_node(node_id):
        _merge_into_node(kg, node_id, attrs, nct, counters, rename, count)
        return False
    kg.add_entity(
        node_id, etype, name,
        confidence=REGISTRY_CONFIDENCE,
        source_documents=[f"ctgov:{nct}"],
        attributes={
            **{k: v for k, v in attrs.items() if v is not None},
            "source": REGISTRY_SOURCE,
            "ctgov_nct_ids": [nct],
        },
    )
    counters["created_nodes"] += 1
    return True


def _find_edge(kg, src, rel, tgt):
    """(key, data) of the first edge src -rel-> tgt, or (None, None)."""
    for key, data in sorted((kg.graph.get_edge_data(src, tgt) or {}).items(), key=lambda kv: str(kv[0])):
        if data.get("relation_type") == rel:
            return key, data
    return None, None


def _upsert_edge(kg, src, rel, tgt, nct, evidence, attrs, counters) -> bool:
    """Create or merge a registry edge; a repeated call for the same NCT is a no-op."""
    if not (kg.graph.has_node(src) and kg.graph.has_node(tgt)):
        return False
    attrs = {k: v for k, v in (attrs or {}).items() if v is not None}
    _, data = _find_edge(kg, src, rel, tgt)
    if data is None:
        key = f"{src}|{rel}|{tgt}"
        if not kg.add_relation(
            key, src, tgt, rel, confidence=REGISTRY_CONFIDENCE,
            evidence=evidence, source_document=f"ctgov:{nct}",
        ):
            return False
        _, data = _find_edge(kg, src, rel, tgt)
        data["attributes"] = {**attrs, "source": REGISTRY_SOURCE, "ctgov_nct_ids": [nct]}
        counters["created_edges"] += 1
        return True
    target = data.get("attributes")
    if not isinstance(target, dict):
        target = {}
        data["attributes"] = target
    if nct in (target.get("ctgov_nct_ids") or []):
        return False
    if target.get("source") == REGISTRY_SOURCE:
        # Another trial supports the same registry edge: add its mention but keep
        # the first mention's evidence, which is what a reload would select.
        first_evidence = data.get("evidence")
        first_document = data.get("source_document")
        kg.add_relation(
            data.get("relation_id") or f"{src}|{rel}|{tgt}", src, tgt, rel,
            confidence=REGISTRY_CONFIDENCE, evidence=evidence,
            source_document=f"ctgov:{nct}",
        )
        _, data = _find_edge(kg, src, rel, tgt)
        data["evidence"] = first_evidence
        data["source_document"] = first_document
    else:
        _merge_attrs(target, attrs)
        _append_unique(target, "sources", REGISTRY_SOURCE)
    _append_unique(target, "ctgov_nct_ids", nct)
    return True


def _node_type(kg, node_id) -> str:
    return str(kg.graph.nodes[node_id].get("entity_type", "")).lower()


def _out_targets(kg, node_id, rel) -> list:
    return sorted({
        tgt for _, tgt, data in kg.graph.out_edges(node_id, data=True)
        if data.get("relation_type") == rel
    })


def _trial_cohorts(kg, nct, trial_ids) -> list:
    """(id, name, arm_label) of the cohorts belonging to the trial NCT."""
    found = set()
    for tid in trial_ids:
        for tgt in _out_targets(kg, tid, "enrolls"):
            if _node_type(kg, tgt) == "cohort":
                found.add(tgt)
    for node_id, data in kg.graph.nodes(data=True):
        if str(data.get("entity_type", "")).lower() != "cohort":
            continue
        attrs = data.get("attributes") if isinstance(data.get("attributes"), dict) else {}
        if str(attrs.get("trial", "")).upper() == nct or nct in str(data.get("name", "")).upper():
            found.add(node_id)
    out = []
    for cid in sorted(found):
        data = kg.graph.nodes[cid]
        attrs = data.get("attributes") if isinstance(data.get("attributes"), dict) else {}
        out.append((cid, str(data.get("name", "")), attrs.get("arm_label") or None))
    return out


def _ae_index(kg, counters) -> dict:
    """AE key -> sorted node ids, built once per run and updated on creation."""
    if counters["ae_index"] is None:
        index: dict = {}
        for node_id, data in kg.graph.nodes(data=True):
            if str(data.get("entity_type", "")).lower() == "adverseevent":
                index.setdefault(_ae_key(str(data.get("name", ""))), []).append(node_id)
        for ids in index.values():
            ids.sort()
        counters["ae_index"] = index
    return counters["ae_index"]


def _trial_documents(kg, trial_ids) -> set:
    """Ids (without a doc: prefix) of the documents the trial nodes are mentioned in."""
    docs = set()
    for tid in trial_ids:
        for _, tgt, data in kg.graph.out_edges(tid, data=True):
            if data.get("relation_type") == "MENTIONED_IN":
                docs.add(str(tgt).removeprefix("doc:"))
    return docs


def _ae_linked_to_trial(kg, trial_ids, nid, trial_docs) -> bool:
    """True when AE node nid is one this trial reports for its own reasons.

    An edge from the trial counts unless the registry alone wrote it, the node
    is an extracted one (not registry-only) and none of its source documents
    belongs to the trial: that is a link left by a registry run that merged
    across trials.
    """
    node_registry = _plain_attrs(kg.graph.nodes[nid]).get("source") == REGISTRY_SOURCE
    own_docs = {str(d).removeprefix("doc:") for d in kg.graph.nodes[nid].get("source_documents") or []}
    for tid in trial_ids:
        _, data = _find_edge(kg, tid, "reports_adverse_event", nid)
        if data is None:
            continue
        if node_registry or _plain_attrs(data).get("source") != REGISTRY_SOURCE or own_docs & trial_docs:
            return True
    return False


def _has_edge_from(kg, src, rel, tgt) -> bool:
    return _find_edge(kg, src, rel, tgt)[1] is not None


def _registry_text(*parts) -> str:
    return " ".join(str(p) for p in parts if p not in (None, ""))


def _sum(stats, field) -> int | None:
    values = [s[field] for s in stats if isinstance(s.get(field), (int, float))]
    return sum(values) if values else None


def _percent(affected, at_risk):
    if isinstance(affected, (int, float)) and isinstance(at_risk, (int, float)) and at_risk > 0:
        return round(affected / at_risk * 100, 2)
    return None


def _group_counts(stat) -> dict:
    return {
        k: v for k, v in (
            ("n_affected", stat.get("num_affected")),
            ("n_at_risk", stat.get("num_at_risk")),
            ("n_events", stat.get("num_events")),
        ) if v is not None
    }


def _group_label(stat) -> str:
    return str(stat.get("group_title") or stat.get("group_id") or "")


def _combined_stats(by_seriousness: dict, primary: dict) -> list:
    """Per-group stats of one event. When the registry lists it in both the
    serious and the other table, affected and event counts are summed per group
    and the at-risk count is taken once per group (the larger value)."""
    if len(by_seriousness) == 1:
        return primary["stats"]
    out: dict = {}
    ordered = [primary] + [r for s, r in sorted(by_seriousness.items()) if r is not primary]
    for record in ordered:
        for stat in record["stats"]:
            cur = out.setdefault(_group_label(stat), {
                "group_id": stat.get("group_id"), "group_title": stat.get("group_title"),
            })
            for field in ("num_affected", "num_events"):
                if isinstance(stat.get(field), (int, float)):
                    cur[field] = cur.get(field, 0) + stat[field]
            if isinstance(stat.get("num_at_risk"), (int, float)):
                cur["num_at_risk"] = max(cur.get("num_at_risk", 0), stat["num_at_risk"])
    return list(out.values())


def _write_adverse_events(kg, nct, parsed, trial_ids, match, counters) -> None:
    records: dict = {}
    for ev in parsed["adverse_events"]:
        term = str(ev.get("term") or "").strip()
        if not _slug(term):
            continue
        records.setdefault(_ae_key(term), {}).setdefault(ev["seriousness"], ev)
    threshold = parsed["ae_threshold_pct"]
    threshold_source = parsed["ae_threshold_source"]
    index = _ae_index(kg, counters)
    trial_docs = _trial_documents(kg, trial_ids)

    for key in sorted(records):
        by_seriousness = records[key]
        primary = by_seriousness.get("serious") or by_seriousness["other"]
        term = str(primary["term"]).strip()
        vocab = str(primary.get("source_vocabulary") or "")
        attrs = {"reported_term": term}
        if vocab.startswith("MedDRA"):
            attrs["meddra_pt"] = term
            attrs["meddra_version"] = vocab[len("MedDRA"):].strip() or None

        known = index.get(key, [])
        reported = [
            nid for nid in known
            if any(_has_edge_from(kg, tid, "reports_adverse_event", nid) for tid in trial_ids)
        ]
        linked = [nid for nid in reported if _ae_linked_to_trial(kg, trial_ids, nid, trial_docs)]
        counters["cross_trial_ae_links_ignored"] += len(reported) - len(linked)
        # A registry AE merges only into an AE this trial already reports, or
        # into a registry-only AE shared by registry trials. An extracted AE
        # of another trial is never merged into; the registry AE then gets one
        # id shared by every registry trial (not tied to an NCT or to the order
        # the trials run in) when the plain id is taken by that extracted AE.
        shared = [
            nid for nid in known
            if _plain_attrs(kg.graph.nodes[nid]).get("source") == REGISTRY_SOURCE
        ]
        default_id = f"adverseevent:{_slug(term)}"
        if not (linked or shared) and kg.graph.has_node(default_id):
            default_id = f"{default_id}_ctgov"
        ae_id = (linked or shared or [default_id])[0]
        created = _upsert_node(
            kg, ae_id, "AdverseEvent", term, attrs, nct, counters,
            rename={"reported_term": "registry_term"}, count=True,
        )
        if created:
            index.setdefault(key, []).append(ae_id)
            index[key].sort()

        organ = str(primary.get("organ_system") or "").strip()
        if _slug(organ):
            organ_id = f"organsystem:{_slug(organ)}"
            if not kg.graph.has_node(organ_id):
                for nid, data in kg.graph.nodes(data=True):
                    if (
                        str(data.get("entity_type", "")).lower() == "organsystem"
                        and str(data.get("name", "")).lower() == organ.lower()
                    ):
                        organ_id = nid
                        break
            _upsert_node(
                kg, organ_id, "OrganSystem", organ,
                {"classification": "system organ class"}, nct, counters,
            )
            _upsert_edge(
                kg, ae_id, "affects_organ_system", organ_id, nct,
                f"ClinicalTrials.gov results {nct}: {term} is classified under {organ}",
                {}, counters,
            )

        def _by_group(stats) -> dict:
            out = {}
            for stat in stats:
                label = _group_label(stat)
                out[label] = {**_group_counts(stat), "cohort": match(stat.get("group_title"))}
            return out

        # Headline counts cover every table the event is listed in; the
        # seriousness flag says whether any of it was serious.
        stats = _combined_stats(by_seriousness, primary)
        both = len(by_seriousness) > 1
        label = "serious and other" if both else primary["seriousness"]
        edge_attrs = {
            "seriousness": primary["seriousness"],
            "assessment_type": primary.get("assessment_type"),
            "n_affected": _sum(stats, "num_affected"),
            "n_at_risk": _sum(stats, "num_at_risk"),
            "frequency_threshold": threshold,
            "frequency_threshold_source": threshold_source,
            "by_group": _by_group(stats),
        }
        if "serious_min_pct" in parsed:
            edge_attrs["serious_min_pct"] = parsed["serious_min_pct"]
        if both:
            edge_attrs["count_basis"] = "serious+other"
            edge_attrs["by_seriousness"] = {
                sers: {
                    "assessment_type": rec.get("assessment_type"),
                    "n_affected": _sum(rec["stats"], "num_affected"),
                    "n_at_risk": _sum(rec["stats"], "num_at_risk"),
                    "by_group": _by_group(rec["stats"]),
                }
                for sers, rec in sorted(by_seriousness.items())
            }
        evidence = (
            f"ClinicalTrials.gov results {nct}: {term} ({label}), "
            f"{edge_attrs['n_affected']} of {edge_attrs['n_at_risk']} participants"
        )
        for tid in trial_ids:
            _upsert_edge(kg, tid, "reports_adverse_event", ae_id, nct, evidence, edge_attrs, counters)

        done = set()
        for stat in stats:
            cid = match(stat.get("group_title"))
            if cid is None or cid in done:
                continue
            done.add(cid)
            counts = {
                sers: {**_group_counts(s), "percent": _percent(s.get("num_affected"), s.get("num_at_risk"))}
                for sers, rec in sorted(by_seriousness.items())
                for s in rec["stats"]
                if match(s.get("group_title")) == cid
            }
            counts = {s: {k: v for k, v in c.items() if v is not None} for s, c in counts.items()}
            obs_attrs = {
                **_group_counts(stat),
                "percent": _percent(stat.get("num_affected"), stat.get("num_at_risk")),
                "registry_counts": {nct: counts},
            }
            _upsert_edge(
                kg, ae_id, "observed_in", cid, nct,
                f"ClinicalTrials.gov results {nct}: {term} ({label}) "
                f"{stat.get('num_affected')}/{stat.get('num_at_risk')} in {_group_label(stat)}",
                obs_attrs, counters,
            )


def _analysis_attrs(an: dict, titles: list, unmatched: list) -> dict:
    p_num, p_qual = _parse_p_value(an.get("p_value"))
    p_raw = an.get("p_value")
    ci_level = _to_float(an.get("ci_pct_value"))
    if ci_level is not None and ci_level == int(ci_level):
        ci_level = int(ci_level)
    attrs = {
        "p_value": p_raw if isinstance(p_raw, str) and p_raw.strip() else None,
        "p_value_num": p_num,
        "p_value_qualifier": p_qual,
        "effect_estimate": _to_float(an.get("param_value")),
        "effect_measure": an.get("param_type"),
        "ci_lower": _to_float(an.get("ci_lower_limit")),
        "ci_upper": _to_float(an.get("ci_upper_limit")),
        "ci_level": ci_level,
        "ci_sides": an.get("ci_num_sides"),
        "endpoint_type": str(an.get("outcome_type") or "").lower() or None,
        "non_inferiority_type": an.get("non_inferiority_type"),
        "timepoint": an.get("time_frame"),
        "unit": an.get("unit"),
        "compared_groups": titles,
        "unmatched_groups": unmatched,
    }
    return {k: v for k, v in attrs.items() if v is not None}


def _plain_attrs(data) -> dict:
    attrs = data.get("attributes")
    return attrs if isinstance(attrs, dict) else {}


def _is_placebo_cohort(kg, cid) -> bool:
    """A comparator arm: placebo in its name or arm label, or every compound or
    intervention it receives is a placebo. An active arm that also receives a
    matching placebo (double-dummy or dose-blinding designs) is not placebo.
    """
    data = kg.graph.nodes[cid]
    if any(
        "placebo" in str(t or "").lower()
        for t in (data.get("name"), _plain_attrs(data).get("arm_label"))
    ):
        return True
    received = [
        str(kg.graph.nodes[t].get("name") or "").lower()
        for t in _out_targets(kg, cid, "receives")
    ]
    return bool(received) and all("placebo" in name for name in received)


def _trial_nct(data) -> str | None:
    """NCT of a Trial node: its name, then attributes.nct_id, then context."""
    attrs = _plain_attrs(data)
    for text in (data.get("name"), attrs.get("nct_id"), data.get("context")):
        found = _extract_nct_id(str(text or ""))
        if found:
            return found
    return None


def _shared_with_other_trial(kg, cid, nct) -> bool:
    """True when a cohort is tied to a trial other than nct: enrolled by a Trial
    node with a different (or no) NCT, or naming another NCT itself."""
    for src, _, d in kg.graph.in_edges(cid, data=True):
        if (
            d.get("relation_type") == "enrolls"
            and _node_type(kg, src) == "trial"
            and _trial_nct(kg.graph.nodes[src]) != nct
        ):
            return True
    data = kg.graph.nodes[cid]
    for text in (data.get("name"), _plain_attrs(data).get("trial")):
        if any(m.upper() != nct for m in NCT_PATTERN.findall(str(text or ""))):
            return True
    return False


def _analysis_owned_by(kg, cand_id, nct, trial_cohort_ids: set) -> bool:
    """True when an extracted OutcomeAnalysis belongs to trial nct.

    An NCT number in its name or trial attributes decides. Otherwise every
    compared cohort must belong to the trial, and at least one non-placebo
    compared arm must be exclusive to it: Cohort nodes (placebo and active
    doses alike) can be shared between trials, and a shared cohort is no
    evidence of which trial the analysis reports. Otherwise its source
    documents must name the NCT. Outcome nodes are shared across trials, so an
    analysis on the same Outcome is not evidence on its own.
    """
    data = kg.graph.nodes[cand_id]
    attrs = _plain_attrs(data)
    named = {
        m.upper()
        for text in (data.get("name"), attrs.get("trial"), attrs.get("nct_id"), attrs.get("ctgov_nct_id"))
        if text
        for m in NCT_PATTERN.findall(str(text))
    }
    if named:
        return nct in named
    compared = set(_out_targets(kg, cand_id, "compares"))
    exclusive = {
        c for c in compared
        if not _is_placebo_cohort(kg, c) and not _shared_with_other_trial(kg, c, nct)
    }
    if compared and exclusive and compared <= trial_cohort_ids:
        return True
    return any(nct in str(d).upper() for d in data.get("source_documents") or [])


def _score_pair(
    reg_attrs: dict, reg_cohorts: set, reg_complete: bool,
    cand_attrs: dict, cand_cohorts: set, placebo: set,
) -> int:
    """Evidence that an extracted analysis is the same comparison as a registry one.

    3: same arms and the same effect measure with the estimate within rounding;
    2: same arms; 1: same effect measure and estimate, with no extracted arm
    outside the registry's. Same arms means every registry group matched a
    cohort and the compared cohorts are equal, or the extracted side names a
    subset with the same non-placebo arms. A shared placebo arm alone is not
    overlap.
    """
    active_reg = reg_cohorts - placebo
    same_arms = (
        reg_complete and bool(reg_cohorts) and bool(cand_cohorts)
        and (
            cand_cohorts == reg_cohorts
            or (cand_cohorts <= reg_cohorts and bool(active_reg) and cand_cohorts - placebo == active_reg)
        )
    )
    measure = (
        reg_attrs.get("effect_measure") is not None
        and str(reg_attrs["effect_measure"]).lower() == str(cand_attrs.get("effect_measure", "")).lower()
    )
    estimate = (
        measure
        and reg_attrs.get("effect_estimate") is not None
        and cand_attrs.get("effect_estimate") is not None
        and _same_estimate(reg_attrs["effect_estimate"], cand_attrs["effect_estimate"])
    )
    if same_arms and estimate:
        return 3
    if same_arms:
        return 2
    if estimate and cand_cohorts <= reg_cohorts:
        return 1
    return 0


def _same_text(a, b) -> bool:
    return _WS_RE.sub(" ", str(a or "").lower()).strip() == _WS_RE.sub(" ", str(b or "").lower()).strip()


def _outcome_fit(kg, oid, title, unit, time_frame):
    """Rank of an Outcome node for a registry measure (lower is better), or None
    when it is a different measure.

    A registry-created Outcome is reused only for the same title and unit. An
    extracted Outcome conflicts when its unit differs or a parenthetical in its
    name (e.g. "(mmol/mol)") appears nowhere in the registry title, unit or time
    frame.
    """
    data = kg.graph.nodes[oid]
    attrs = _plain_attrs(data)
    name = str(data.get("name", ""))
    node_unit = attrs.get("unit")
    if attrs.get("source") == REGISTRY_SOURCE:
        if _same_text(name, title) and _same_text(node_unit, unit):
            return (0, 0, 0, oid)
        return None
    if node_unit and unit and _norm_arm(node_unit) != _norm_arm(unit):
        return None
    hay = f" {_norm_arm(' '.join(str(x) for x in (title, unit, time_frame) if x))} "
    qualifiers = [q for q in (_norm_arm(p) for p in re.findall(r"\(([^)]*)\)", name)) if q]
    if any(f" {q} " not in hay for q in qualifiers):
        return None
    return (0 if _same_text(name, title) else 1, 0 if node_unit else 1, -len(qualifiers), oid)


def _registry_outcome_id(kg, nct, title, unit) -> str:
    """Id for a new registry Outcome: outcome:<slug>, or an NCT-scoped id when
    that id is held by an extracted node or by a different registry measure."""
    base = _slug(title)
    candidates = [f"outcome:{base}", f"outcome:{_slug(nct)}_{base}"]
    n = 2
    while True:
        for oid in candidates:
            if not kg.graph.has_node(oid):
                return oid
            data = kg.graph.nodes[oid]
            attrs = _plain_attrs(data)
            if (
                attrs.get("source") == REGISTRY_SOURCE
                and _same_text(data.get("name"), title)
                and _same_text(attrs.get("unit"), unit)
            ):
                return oid
        candidates = [f"outcome:{_slug(nct)}_{base}_{n}"]
        n += 1


def _write_analyses(
    kg, nct, parsed, trial_ids, trial_cohort_ids, match, counters, arm_match=None,
) -> None:
    """Write one trial's registry analyses, merging into extracted ones.

    arm_match maps a group title to the index of the one CT.gov armGroup it
    names (see _write_results). A registry analysis whose compared groups match
    at least one armGroup records ctgov_arm_groups, one {title, arm_type,
    interventions} per compared group (unmatched groups: arm_type None and no
    interventions). The attribute is added with setdefault on the created node
    or the merged holder, so a value already there is never overwritten and no
    registry_ conflict key is recorded; a re-run backfills a node that lacks it.
    The backfill is counted as neither created nor merged.
    """
    analyses = parsed["analyses"]
    if not analyses:
        return
    outcome_by_norm: dict = {}
    for tid in trial_ids:
        for oid in _out_targets(kg, tid, "has_outcome"):
            if _node_type(kg, oid) == "outcome":
                ids = outcome_by_norm.setdefault(
                    normalize_measure(str(kg.graph.nodes[oid].get("name", ""))), []
                )
                if oid not in ids:
                    ids.append(oid)

    used_ids: set = set()
    prepared = []
    for an in analyses:
        title = str(an.get("outcome_title") or "").strip()
        if not _slug(title):
            continue
        groups = an.get("groups") or {}
        group_titles = [str(groups.get(gid) or gid) for gid in an.get("group_ids") or []]
        cohort_ids = [match(t) for t in group_titles]
        unmatched = [t for t, c in zip(group_titles, cohort_ids) if c is None]
        # Deduplicate on the id, not the raw name: names differing only in
        # punctuation ("≤6.5%" vs "<=6.5%") share a slug.
        base = f"{nct}: {title} — {' vs '.join(group_titles)}"
        name, repeat = base, 1
        while _slug(name) in used_ids:
            repeat += 1
            name = f"{base} ({repeat})"
        used_ids.add(_slug(name))
        norm = normalize_measure(title)
        unit, time_frame = an.get("unit"), an.get("time_frame")
        fits = [
            (rank, oid) for oid in outcome_by_norm.get(norm, [])
            if (rank := _outcome_fit(kg, oid, title, unit, time_frame)) is not None
        ]
        if fits:
            outcome_id = min(fits)[1]
        else:
            outcome_id = _registry_outcome_id(kg, nct, title, unit)
            _upsert_node(
                kg, outcome_id, "Outcome", title,
                {
                    "endpoint_type": str(an.get("outcome_type") or "").capitalize() or None,
                    "timeframe": time_frame,
                    "unit": unit,
                },
                nct, counters,
            )
            for tid in trial_ids:
                _upsert_edge(
                    kg, tid, "has_outcome", outcome_id, nct,
                    f"ClinicalTrials.gov results {nct}: outcome {title}", {}, counters,
                )
            outcome_by_norm.setdefault(norm, []).append(outcome_id)
        prepared.append({
            "an": an, "title": title, "name": name, "id": f"outcomeanalysis:{_slug(name)}",
            "outcome": outcome_id, "cohorts": [c for c in cohort_ids if c],
            "complete": not unmatched,
            "attrs": _analysis_attrs(an, group_titles, unmatched), "groups": group_titles,
            "arm_groups": _compared_arm_groups(group_titles, parsed.get("arm_groups"), arm_match),
        })

    # Resolve which registry analyses are already present (second run) or are
    # absorbed by an extracted analysis of this trial, best evidence first.
    holder_by_reg: dict = {}
    for node_id, data in kg.graph.nodes(data=True):
        if str(data.get("entity_type", "")).lower() != "outcomeanalysis":
            continue
        for rid in (data.get("attributes") or {}).get("ctgov_analysis_ids") or []:
            holder_by_reg[rid] = node_id
    owned: dict = {}
    placebo: dict = {}

    def is_placebo(cid) -> bool:
        if cid not in placebo:
            placebo[cid] = _is_placebo_cohort(kg, cid)
        return placebo[cid]

    pairs = []
    for idx, item in enumerate(prepared):
        if item["id"] in holder_by_reg or kg.graph.has_node(item["id"]):
            continue
        reg_cohorts = set(item["cohorts"])
        for src, _, data in kg.graph.in_edges(item["outcome"], data=True):
            if data.get("relation_type") != "analyzes" or _node_type(kg, src) != "outcomeanalysis":
                continue
            cand = _plain_attrs(kg.graph.nodes[src])
            if cand.get("source") == REGISTRY_SOURCE or cand.get("ctgov_analysis_ids"):
                continue
            if src not in owned:
                owned[src] = _analysis_owned_by(kg, src, nct, trial_cohort_ids)
            if not owned[src]:
                continue
            cand_cohorts = set(_out_targets(kg, src, "compares"))
            score = _score_pair(
                item["attrs"], reg_cohorts, item["complete"], cand, cand_cohorts,
                {c for c in reg_cohorts | cand_cohorts if is_placebo(c)},
            )
            if score:
                pairs.append((-score, idx, src))
    # An estimate-only match (score 1) carries no arm evidence, so it is taken
    # only when unambiguous on both sides: the extracted analysis fits exactly
    # one registry analysis that way, and that registry analysis fits exactly
    # one extracted analysis. A tie is never broken by registry order.
    by_cand = Counter(src for s, _, src in pairs if s == -1)
    by_reg = Counter(idx for s, idx, _ in pairs if s == -1)
    pairs = [
        p for p in pairs
        if p[0] != -1 or (by_cand[p[2]] == 1 and by_reg[p[1]] == 1)
    ]
    taken_reg, taken_cand = set(), set()
    for _, idx, cand_id in sorted(pairs):
        if idx in taken_reg or cand_id in taken_cand:
            continue
        taken_reg.add(idx)
        taken_cand.add(cand_id)
        holder_by_reg[prepared[idx]["id"]] = cand_id

    for item in prepared:
        an = item["an"]
        holder = holder_by_reg.get(item["id"])
        if holder is not None and kg.graph.has_node(holder) and holder != item["id"]:
            oa_id = holder
            attrs = _node_attrs(kg, oa_id)
            if nct not in (attrs.get("ctgov_nct_ids") or []):
                _merge_into_node(
                    kg, oa_id, item["attrs"], nct, counters, count=True, groups=ANALYSIS_STAT_GROUPS,
                )
                _append_unique(attrs, "ctgov_analysis_ids", item["id"])
        else:
            oa_id = item["id"]
            _upsert_node(
                kg, oa_id, "OutcomeAnalysis", item["name"], item["attrs"], nct, counters, count=True,
            )
        if item["arm_groups"]:
            _node_attrs(kg, oa_id).setdefault("ctgov_arm_groups", item["arm_groups"])
        text = _registry_text(
            f"ClinicalTrials.gov results {nct}: {item['title']} — {' vs '.join(item['groups'])},",
            an.get("param_type"), an.get("param_value"),
            f"({an['ci_pct_value']}% CI {an.get('ci_lower_limit')} to {an.get('ci_upper_limit')}),"
            if an.get("ci_pct_value") not in (None, "") else None,
            f"p {an['p_value']}" if an.get("p_value") not in (None, "") else None,
        ).rstrip(",")
        _upsert_edge(kg, oa_id, "analyzes", item["outcome"], nct, text, {}, counters)
        for cid in item["cohorts"]:
            _upsert_edge(kg, oa_id, "compares", cid, nct, text, {}, counters)
        targets = set()
        for cid in item["cohorts"]:
            for tgt in _out_targets(kg, cid, "receives"):
                if (
                    _node_type(kg, tgt) in ("compound", "intervention")
                    and "placebo" not in str(kg.graph.nodes[tgt].get("name", "")).lower()
                ):
                    targets.add(tgt)
        if len(targets) == 1:
            _upsert_edge(kg, oa_id, "assesses_effect_of", next(iter(targets)), nct, text, {}, counters)
        method = _WS_RE.sub(" ", str(an.get("statistical_method") or "")).strip()
        if _slug(method):
            method_id = f"statisticalmethod:{_slug(method)}"
            _upsert_node(kg, method_id, "StatisticalMethod", method, {}, nct, counters)
            _upsert_edge(kg, oa_id, "uses_method", method_id, nct, text, {}, counters)


def _compared_arm_groups(group_titles, arm_groups, arm_match) -> list | None:
    """One {title, arm_type, interventions} per compared group, or None.

    None unless at least one title matched a CT.gov armGroup, so a trial
    without armGroups records nothing.
    """
    if not arm_groups or arm_match is None:
        return None
    out, matched = [], False
    for title in group_titles:
        idx = arm_match(title)
        arm = arm_groups[idx] if idx is not None else None
        matched = matched or arm is not None
        out.append({
            "title": title,
            "arm_type": arm.get("type") if arm else None,
            "interventions": list(arm.get("interventions") or []) if arm else [],
        })
    return out if matched else None


def _write_results(kg, nct, parsed, trial_ids, counters) -> None:
    """Write one trial's parsed registry results into the graph."""
    cohorts = _trial_cohorts(kg, nct, trial_ids)
    cache: dict = {}
    arm_cache: dict = {}
    arm_candidates = [
        (i, [g.get("label")]) for i, g in enumerate(parsed.get("arm_groups") or [])
    ]

    def match(title):
        if title not in cache:
            cache[title] = _match_cohort(title, cohorts)
        return cache[title]

    def arm_match(title):
        if title not in arm_cache:
            arm_cache[title] = _match_label(title, arm_candidates)
        return arm_cache[title]

    _write_adverse_events(kg, nct, parsed, trial_ids, match, counters)
    _write_analyses(
        kg, nct, parsed, trial_ids, {c[0] for c in cohorts}, match, counters, arm_match,
    )


# ---------------------------------------------------------------------------
# Main enrichment function
# ---------------------------------------------------------------------------


def _empty_results_block() -> dict:
    return {
        "trials_with_results": 0,
        "trials_without_results": 0,
        "results_failed": 0,
        "adverse_events_parsed": {"serious": 0, "other": 0},
        "analyses_parsed": 0,
        "created": 0,
        "merged": 0,
        "created_nodes": 0,
        "created_edges": 0,
        "write_failed": 0,
    }


def enrich_graph(
    output_dir: Path,
    domain: str = "clinicaltrials",
    results: bool = False,
    cache_dir: Path | None = None,
    serious_min_pct: float = SERIOUS_MIN_PCT_DEFAULT,
) -> dict:
    """Load graph, enrich Trial + Compound nodes, save, write report.

    Args:
        output_dir: Directory containing graph_data.json.
        domain: Domain name stamped into the report.
        results: Also parse posted results from the same per-trial payload and
            import them into the graph (see module docstring) and add a "results"
            block to the report.
        cache_dir: Optional directory caching one raw payload per trial.
        serious_min_pct: Opt-in per-arm floor (percent affected) for serious
            adverse events in results mode. 0 (the default) keeps every
            serious event. When > 0 the "results" block gains serious_min_pct
            and serious_events_omitted. Must be a finite number from 0 to 100.

    Returns:
        Report dict with domain, trials counts, compounds counts, hit_rate.
    """
    serious_min_pct = _check_serious_min_pct(serious_min_pct)
    output_dir = Path(output_dir)
    graph_path = output_dir / "graph_data.json"
    if not graph_path.exists():
        report = _build_report(domain, 0, 0, 0, 0, 0, 0, 0, 0)
        if results:
            report["results"] = _empty_results_block()
        _write_report(output_dir, report)
        return report

    # Load via sift-kg; fall back to raw JSON if sift-kg is unavailable
    try:
        from sift_kg import KnowledgeGraph
        kg = KnowledgeGraph.load(graph_path)
        node_iter = list(kg.graph.nodes(data=True))
    except ImportError:
        kg = None
        raw = json.loads(graph_path.read_text())
        node_iter = [(n.get("id"), n) for n in raw.get("nodes", [])]

    trials_total = trials_enriched = trials_not_found = trials_failed = 0
    compounds_total = compounds_enriched = compounds_not_found = compounds_failed = 0
    results_block = _empty_results_block()
    serious_omitted = 0
    floor_conflicts: dict = {}
    studies_by_nct: dict = {}
    trial_ids_by_nct: dict = {}
    parsed_by_nct: dict = {}

    for node_id, data in node_iter:
        etype = str(data.get("entity_type", "")).lower()
        if etype == "trial":
            trials_total += 1
            # Look for NCT ID in name first, then attributes, then context
            candidate = _extract_nct_id(str(data.get("name", "")))
            if not candidate:
                attrs = data.get("attributes") or {}
                if isinstance(attrs, dict):
                    candidate = _extract_nct_id(str(attrs.get("nct_id", "")))
            if not candidate:
                candidate = _extract_nct_id(str(data.get("context", "")))
            if not candidate:
                trials_not_found += 1
                continue
            first_sight = candidate not in studies_by_nct
            if first_sight:
                studies_by_nct[candidate], _ = _get_ct_gov_study(candidate, cache_dir)
            study = studies_by_nct[candidate]
            trial_ids_by_nct.setdefault(candidate, []).append(node_id)
            try:
                enrichment = _parse_ct_protocol(study) if study is not None else None
            except (AttributeError, TypeError):
                enrichment = None
            if results and first_sight:
                if study is None:
                    results_block["results_failed"] += 1
                else:
                    try:
                        parsed = _parse_ct_results(study, serious_min_pct)
                    except Exception:
                        results_block["results_failed"] += 1
                    else:
                        if parsed is None:
                            results_block["trials_without_results"] += 1
                        else:
                            results_block["trials_with_results"] += 1
                            parsed_by_nct[candidate] = parsed
                            for ev in parsed["adverse_events"]:
                                results_block["adverse_events_parsed"][ev["seriousness"]] += 1
                            results_block["analyses_parsed"] += len(parsed["analyses"])
            if enrichment:
                data.update(enrichment)
                trials_enriched += 1
            else:
                trials_failed += 1
        elif etype == "compound":
            compounds_total += 1
            name = str(data.get("name", "")).strip()
            if not name:
                compounds_not_found += 1
                continue
            time.sleep(PUBCHEM_RATE_SLEEP)
            enrichment = _fetch_pubchem(name)
            if enrichment:
                data.update(enrichment)
                compounds_enriched += 1
            else:
                compounds_failed += 1

    if results and parsed_by_nct:
        if kg is None:
            results_block["skipped_reason"] = (
                "sift_kg unavailable: registry results were parsed but not written"
            )
            serious_omitted = sum(p.get("serious_events_omitted", 0) for p in parsed_by_nct.values())
        else:
            counters = _new_counters()
            write_errors: dict = {}
            for nct in sorted(parsed_by_nct):
                to_write = parsed_by_nct[nct]
                prior = _prior_serious_floors(kg, trial_ids_by_nct[nct], nct)
                if prior and prior != {serious_min_pct}:
                    # Already imported under another floor: registry writes are
                    # idempotent per NCT, so applying this floor would only add
                    # edges beside the old ones. Leave the AEs as they are.
                    floor_conflicts[nct] = sorted(prior)
                    to_write = {**to_write, "adverse_events": []}
                    print(
                        f"enrich.py: {nct} was imported with serious_min_pct "
                        f"{sorted(prior)}, not {serious_min_pct}; its adverse events are "
                        "unchanged (re-enrich the un-enriched graph to change the floor)",
                        file=sys.stderr,
                    )
                # One trial's write is atomic: on any error the graph and the
                # counters go back to their state before this trial, so no
                # partial write is stamped with the NCT (which would make every
                # rerun skip it).
                graph_before = copy.deepcopy(kg.graph)
                counters_before = copy.deepcopy(counters)
                try:
                    _write_results(
                        kg, nct, to_write, sorted(trial_ids_by_nct[nct]), counters
                    )
                    if nct not in floor_conflicts:
                        serious_omitted += to_write.get("serious_events_omitted", 0)
                except Exception as exc:
                    kg.graph = graph_before
                    counters = counters_before
                    message = f"{type(exc).__name__}: {exc}"
                    write_errors[nct] = message
                    results_block["write_failed"] += 1
                    print(f"enrich.py: registry write failed for {nct}: {message}", file=sys.stderr)
            results_block["created_nodes"] = counters["created_nodes"]
            results_block["created_edges"] = counters["created_edges"]
            results_block["created"] = counters["created_nodes"] + counters["created_edges"]
            results_block["merged"] = counters["merged"]
            if counters["cross_trial_ae_links_ignored"]:
                results_block["cross_trial_ae_links_ignored"] = counters["cross_trial_ae_links_ignored"]
            if write_errors:
                results_block["write_errors"] = write_errors

    # Persist mutations
    if kg is not None:
        kg.save(graph_path)
    else:
        # Non-sift-kg path: write back raw JSON (best effort)
        raw_nodes = [data for _, data in node_iter]
        raw_data = json.loads(graph_path.read_text())
        raw_data["nodes"] = raw_nodes
        graph_path.write_text(json.dumps(raw_data, indent=2))

    report = _build_report(
        domain,
        trials_total, trials_enriched, trials_not_found, trials_failed,
        compounds_total, compounds_enriched, compounds_not_found, compounds_failed,
    )
    if results:
        if serious_min_pct > 0:
            results_block["serious_min_pct"] = serious_min_pct
            results_block["serious_events_omitted"] = serious_omitted
        if floor_conflicts:
            results_block["serious_min_pct_conflicts"] = floor_conflicts
        report["results"] = results_block
    _write_report(output_dir, report)
    return report


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _prior_serious_floors(kg, trial_ids, nct) -> set:
    """The serious_min_pct values (0.0 when absent) of the registry
    reports_adverse_event edges this NCT already wrote from its trial nodes;
    empty when the trial's AEs were never imported."""
    floors = set()
    for tid in trial_ids:
        if not kg.graph.has_node(tid):
            continue
        for _, _, data in kg.graph.out_edges(tid, data=True):
            if data.get("relation_type") != "reports_adverse_event":
                continue
            attrs = _plain_attrs(data)
            if nct not in (attrs.get("ctgov_nct_ids") or []):
                continue
            value = attrs.get("serious_min_pct", 0.0)
            floors.add(float(value) if isinstance(value, (int, float)) else 0.0)
    return floors


def _check_serious_min_pct(value) -> float:
    """Validate the serious-event floor: a finite number from 0 to 100."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"serious_min_pct must be a number, got {value!r}")
    value = float(value)
    if not (0.0 <= value <= 100.0):  # also rejects NaN
        raise ValueError(f"serious_min_pct must be from 0 to 100, got {value!r}")
    return value


def _build_report(
    domain: str,
    t_total: int, t_enriched: int, t_not_found: int, t_failed: int,
    c_total: int, c_enriched: int, c_not_found: int, c_failed: int,
) -> dict:
    """Build the enrichment report dict matching 21-RESEARCH.md schema."""
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "domain": domain,
        "trials": {
            "total": t_total,
            "enriched": t_enriched,
            "not_found": t_not_found,
            "failed": t_failed,
        },
        "compounds": {
            "total": c_total,
            "enriched": c_enriched,
            "not_found": c_not_found,
            "failed": c_failed,
        },
        "hit_rate": {
            "trials": round(t_enriched / t_total, 3) if t_total else 0.0,
            "compounds": round(c_enriched / c_total, 3) if c_total else 0.0,
        },
    }


def _write_report(output_dir: Path, report: dict) -> Path | None:
    """Write _enrichment_report.json under <output_dir>/extractions/.

    Returns the path on success, or None if the directory cannot be created
    (e.g., output_dir is a nonexistent path on a read-only filesystem).
    """
    try:
        extractions_dir = output_dir / "extractions"
        extractions_dir.mkdir(parents=True, exist_ok=True)
        report_path = extractions_dir / "_enrichment_report.json"
        report_path.write_text(json.dumps(report, indent=2))
        return report_path
    except OSError:
        return None


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] in ("--help", "-h"):
        print(__doc__)
        sys.exit(0 if "--help" in sys.argv or "-h" in sys.argv else 1)
    import argparse

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("output_dir")
    parser.add_argument("--results", action="store_true")
    parser.add_argument("--cache-dir", type=Path, default=None)
    parser.add_argument("--results-serious-min-pct", type=float, default=SERIOUS_MIN_PCT_DEFAULT)
    args = parser.parse_args()
    try:
        serious_min_pct = _check_serious_min_pct(args.results_serious_min_pct)
    except ValueError as exc:
        parser.error(str(exc))
    if serious_min_pct > 0 and not args.results:
        parser.error("--results-serious-min-pct needs --results")
    report = enrich_graph(
        Path(args.output_dir), results=args.results, cache_dir=args.cache_dir,
        serious_min_pct=serious_min_pct,
    )
    print(json.dumps(report, indent=2))
