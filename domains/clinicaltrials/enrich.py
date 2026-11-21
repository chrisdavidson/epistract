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
matching extracted nodes (the first conflicting value is kept as
registry_<attr>; every conflicting value is also kept as
registry_<attr>_by_nct = {NCT: value}), a repeated run changes nothing, and
registry groups that match no extracted Cohort never create one. When several
Trial nodes carry one NCT, the registry edges that start at a Trial
(reports_adverse_event, has_outcome) are written once, from the canonical Trial
node (the lowest id), or merged into the edge another Trial node of that NCT
already has; the other Trial nodes of that NCT get the attribute
same_trial_as = <canonical id> and no registry edges of their own. Analyses merge only into an extracted analysis of the same trial
that compares the same arms (or has the same effect measure and estimate).
Each registry analysis also records ctgov_arm_groups: the CT.gov armGroup type
and interventions of every compared group that names an armGroup, added only
when missing (a re-run backfills it; an existing value is never overwritten).
A registry-created analysis that the Cohort-receives rule left without an
assesses_effect_of edge gets one to a Compound when its armGroup types resolve the
treatment unambiguously (exactly one EXPERIMENTAL group, every other compared group
a comparator type, one graph Compound named by the EXPERIMENTAL group after dropping
compounds every comparator group also names). The edge is a registry edge
(source ctgov_results) with attributes.treatment_basis = registry_arm_type, which
the epistemic layer reads first; an extracted analysis is never given one.
An opt-in per-arm floor for serious events (--results-serious-min-pct X,
default 0 = every serious event) keeps a serious event only when at least one
arm reaches X percent affected; the report then records the floor and the
number of serious records omitted, and the AE edges carry serious_min_pct.
The floor applies to a trial's first import only: when a trial's registry AE
edges were written under another floor, its AEs are left as they are and the
trial is listed under serious_min_pct_conflicts (re-enrich the un-enriched
graph to change the floor).
The "results" block of _enrichment_report.json counts the parsed records and
the graph writes (created, merged; merged_by_type splits merged into
AdverseEvent, OutcomeAnalysis and Outcome, where an Outcome merge is a registry
analysis reusing an extracted Outcome); a trial whose write fails is rolled back
and listed under write_errors. Without --results, behaviour is unchanged.

Opt-in refresh (--refresh-results, needs --results): a trial whose registry
facts are already recorded is re-imported in place. Registry-owned node and
edge attributes (source ctgov_results, first NCT = this trial) are replaced
with the new payload values, and a payload attribute the new payload no
longer produces (e.g. a dropped p-value, or count_basis when an event is no
longer in both tables) is removed; on a registry node other NCTs also
support such an attribute is kept, since their first import may have filled
it. On extracted or shared targets only the registry_<attr> /
registry_<attr>_by_nct bookkeeping for this NCT changes, and an extracted
attribute value is never touched. A dict attribute such as by_group follows
the first-import rule: sub-keys it lacks are added, a sub-key it already has
keeps its value and is not recorded (a first import records none there
either), so an unchanged payload changes nothing. New adverse events and
analyses are added. A registry fact that only this NCT supports and that the new payload no
longer has is marked ctgov_withdrawn: true (also when the payload has no
results at all). On a fact other NCTs also support, the NCT is recorded in
ctgov_withdrawn_by_nct = {NCT: true}, and a registry fact is flagged
ctgov_withdrawn once every NCT recorded on it has withdrawn it, whatever the
order of the NCTs. When another NCT first reports a fact flagged
ctgov_withdrawn (in a default run or a refresh), the flag is turned into
ctgov_withdrawn_by_nct entries for the NCTs already recorded and dropped,
since the new NCT supports the fact. An extracted node or edge the registry
merged into only gets the ctgov_withdrawn_by_nct entry: its registry
corroboration is withdrawn, the fact is not (its sources still list
ctgov_results). Nothing is deleted, and a fact that reappears loses this NCT's entry and the flag.
Without the flag a re-run changes nothing. A refresh does not refetch by
itself: use --cache-ttl-days to age out cached payloads (--cache-ttl-days 0
refetches every cached trial). The "results" block gains a "refresh" block
(trials_refreshed: trials whose facts were already recorded, updated_nodes,
updated_edges: changed facts this NCT had already recorded, withdrawn,
restored: flags dropped, also by an NCT that first reports a withdrawn fact,
which is not counted in updated_*, legacy_copies_skipped: a second edge copy
of a fact on another Trial node of the NCT, left as it is).

Opt-in cache expiry (--cache-ttl-days N, needs --cache-dir): a cached payload
whose file is older than N days is refetched and rewritten; when the refetch
fails the stale payload is used. The report then gains a top-level "cache"
block (ttl_days, expired, refetched, stale_used, stale_after_not_found: stale
payloads used because the refetch got a 404, i.e. the trial may have left the
registry). Without it a cached payload never expires.

Non-blocking: API failures log counts but never abort the pipeline.
ARCH-03: no core/ changes required; this module lives in the domain package.

Usage:
    python3 domains/clinicaltrials/enrich.py <output_dir> [--results] [--cache-dir DIR]
        [--results-serious-min-pct X] [--refresh-results] [--cache-ttl-days N]

    --results         also import posted results into the graph and add a "results" report block
    --cache-dir DIR   read/write one raw CT.gov payload per trial as DIR/<NCT>.json
    --results-serious-min-pct X
                      opt-in volume control for --results: keep a serious adverse event only
                      when at least one arm has X percent or more affected (default 0: keep
                      every serious event, the 3.5.0 behaviour); needs --results
    --refresh-results re-import registry facts already recorded: update in place, add new
                      facts, mark vanished ones ctgov_withdrawn; needs --results
    --cache-ttl-days N
                      refetch cached payloads older than N days (default: never expire);
                      needs --cache-dir
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
# Attributes the registry import derives from a payload: AdverseEvent,
# OrganSystem, Outcome and OutcomeAnalysis nodes, reports_adverse_event and
# observed_in edges. A refresh removes one that the new payload no longer
# produces from a registry-owned fact (see _refresh_attrs).
REGISTRY_PAYLOAD_KEYS = frozenset({
    "reported_term", "meddra_pt", "meddra_version",
    "classification",
    "seriousness", "assessment_type", "n_affected", "n_at_risk", "n_events", "percent",
    "frequency_threshold", "frequency_threshold_source", "by_group", "serious_min_pct",
    "count_basis", "by_seriousness", "registry_counts",
    "endpoint_type", "timeframe", "unit",
    "p_value", "p_value_num", "p_value_qualifier", "effect_estimate", "effect_measure",
    "ci_lower", "ci_upper", "ci_level", "ci_sides", "non_inferiority_type", "timepoint",
    "compared_groups", "unmatched_groups", "outcome_param_type",
})
# Refresh: NCTs whose refreshed payload no longer has a fact ({NCT: True}).
WITHDRAWN_BY_NCT = "ctgov_withdrawn_by_nct"

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
# split them from the British form. "oestr" folds everywhere except after the
# known US o-prefixes hyp/phyt/xen/pr/myc/metall/neur/pseud/zo (Hypoestrogenism,
# Phytoestrogen, Xenoestrogen, Proestrus, Mycoestrogen, Metalloestrogen,
# Neuroestradiol, Pseudoestrus, Zooestrogen keep their keys), so British
# compounds with any other prefix fold: Oestradiol, Hypooestrogenism,
# Hyperoestrogenism, Ethinyloestradiol, Diethylstilboestrol, Antioestrogen,
# Fosfoestrol, Dioestrus, Anoestrus. This prefix list is best-effort, not
# complete: a US compound with a linking "o" before "estr" (myc-o-estrogen)
# looks the same as a British spelling (fosf-oestrol), so a US prefix missing
# from the list is folded and flagged as British.
# "oedem" keeps its "angi" lookbehind (British -oedema compounds such as
# Lymphoedema and Lipoedema need the fold) and "angio-oedem" folds its hyphen
# first. "aesthes" folds everywhere (Paraesthesia, Hypo-aesthesia,
# Aesthesioneuroblastoma); "aesthet" needs a preceding letter, so it covers
# anaesthetic/anaesthetist but leaves the US word "aesthetic" alone. "leuc" only
# before "o" and not in Leucovorin or Leuconostoc (Leucopenia), leaving Leucine
# alone. Lookarounds are chained, not alternated, so no pattern contains "|".
_US_SPELLING = [
    (re.compile(r"angio-oedem", re.IGNORECASE), "angioedem"),
    (re.compile(r"(?<!angi)oedem", re.IGNORECASE), "edem"),
    (re.compile(r"oesophag", re.IGNORECASE), "esophag"),
    (re.compile(r"rhoe", re.IGNORECASE), "rhe"),
    (re.compile(r"pnoe", re.IGNORECASE), "pne"),  # dys/a/tachy/ortho/hypo/brady/hyperpnoea
    (re.compile(r"(?<!hyp)(?<!phyt)(?<!xen)(?<!pr)(?<!myc)(?<!metall)(?<!neur)(?<!pseud)(?<!zo)oestr",
                re.IGNORECASE), "estr"),
    (re.compile(r"foet", re.IGNORECASE), "fet"),
    (re.compile(r"coeliac", re.IGNORECASE), "celiac"),
    (re.compile(r"amoeb", re.IGNORECASE), "ameb"),
    (re.compile(r"aesthes", re.IGNORECASE), "esthes"),  # -aesthesia, aesthesio-, hypo-aesthesia
    (re.compile(r"(?<=[a-z])aesthet", re.IGNORECASE), "esthet"),  # anaesthetic/anaesthetist; US "aesthetic" kept
    (re.compile(r"faec", re.IGNORECASE), "fec"),
    (re.compile(r"gynaec", re.IGNORECASE), "gynec"),
    (re.compile(r"leuc(?=o(?!vorin)(?!nostoc))", re.IGNORECASE), "leuk"),
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


def _fetch_ct_gov_study(nct_id: str, outcome: dict | None = None) -> dict | None:
    """Fetch the full CT.gov v2 study payload, or None on 404 / any error.

    When outcome is given, outcome["not_found"] is set to True on a 404.
    """
    try:
        resp = requests.get(CTGOV_URL.format(nct_id=nct_id), timeout=CTGOV_TIMEOUT)
        if resp.status_code == 404:
            if outcome is not None:
                outcome["not_found"] = True
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


def _get_ct_gov_study(
    nct_id: str, cache_dir, ttl_days: float | None = None, stats: dict | None = None,
) -> tuple[dict | None, bool]:
    """Return (study, fetched_from_network), reading/writing cache_dir if given.

    With ttl_days, a cache file whose mtime is that many days old or older is
    expired and refetched; when the refetch fails the stale payload is used.
    stats (expired / refetched / stale_used / stale_after_not_found) is updated
    when given; stale_after_not_found counts the stale payloads used because
    the refetch got a 404 (the trial may have left the registry). Without
    ttl_days a cached payload never expires.
    """
    if cache_dir is None:
        time.sleep(CTGOV_RATE_SLEEP)
        return _fetch_ct_gov_study(nct_id), True
    cache_file = Path(cache_dir) / f"{nct_id}.json"
    stale = None
    try:
        cached = json.loads(cache_file.read_text())
        if isinstance(cached, dict):
            if ttl_days is None:
                return cached, False
            age = time.time() - cache_file.stat().st_mtime
            if age < ttl_days * 86400:
                return cached, False
            stale = cached
            if stats is not None:
                stats["expired"] += 1
    except (OSError, ValueError):
        pass
    time.sleep(CTGOV_RATE_SLEEP)
    outcome: dict = {}
    study = _fetch_ct_gov_study(nct_id, outcome)
    if study is not None:
        try:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(json.dumps(study))
        except OSError:
            pass
        if stale is not None and stats is not None:
            stats["refetched"] += 1
    elif stale is not None:
        if stats is not None:
            stats["stale_used"] += 1
            if outcome.get("not_found"):
                stats["stale_after_not_found"] += 1
        return stale, False
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
        "merged_by_type": {"AdverseEvent": 0, "OutcomeAnalysis": 0, "Outcome": 0},
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


def _merge_attrs(
    target: dict, attrs: dict, rename: dict | None = None, groups=(), nct: str | None = None,
) -> None:
    """Fill missing attributes; keep a differing existing value, store the new
    one as registry_<attr>. Never deletes or overwrites.

    REFRESH-03: registry_<attr> keeps the first conflicting value; when nct is
    given, every conflicting value is also stored as registry_<attr>_by_nct
    = {nct: value}.

    For each group in groups: when the target has any of the group's fields,
    none of them is filled; every new value that differs from or is absent on
    the target is stored as registry_<attr> instead.
    """
    rename = rename or {}

    def conflict(key, value) -> None:
        name = rename.get(key, f"registry_{key}")
        target.setdefault(name, value)
        if nct is not None:
            by_nct = target.get(f"{name}_by_nct")
            if not isinstance(by_nct, dict):
                by_nct = {}
                target[f"{name}_by_nct"] = by_nct
            by_nct[nct] = value

    held: set = set()
    for group in groups:
        if not any(target.get(k) not in (None, "", []) for k in group):
            continue
        for key in group:
            held.add(key)
            value = attrs.get(key)
            if value is not None and target.get(key) != value:
                conflict(key, value)
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
            conflict(key, value)


def _refresh_ctx(counters, nct):
    """The refresh context of the NCT being refreshed, or None."""
    ctx = counters.get("refresh")
    return ctx if ctx and ctx["nct"] == nct else None


def _owned_by(target: dict, nct) -> bool:
    """True when the registry created this node/edge for this NCT (first NCT)."""
    ids = target.get("ctgov_nct_ids") or []
    return target.get("source") == REGISTRY_SOURCE and bool(ids) and ids[0] == nct


def _restore(target: dict, ctx, nct) -> bool:
    """A fact present in the payload again: this NCT's withdrawal entry is
    dropped and the fact loses its withdrawn flag (counted as restored).

    True when this NCT's ctgov_withdrawn_by_nct entry was dropped.
    """
    dropped = False
    by_nct = target.get(WITHDRAWN_BY_NCT)
    if isinstance(by_nct, dict) and nct in by_nct:
        del by_nct[nct]
        if not by_nct:
            target.pop(WITHDRAWN_BY_NCT)
        dropped = True
    if target.pop("ctgov_withdrawn", None) is not None:
        ctx["stats"]["restored"] += 1
    return dropped


def _withdraw(target: dict, nct, registry: bool) -> str | None:
    """Record that this NCT's refreshed payload no longer has a fact.

    A registry fact this NCT alone supports gets ctgov_withdrawn: true. Otherwise
    this NCT is recorded in ctgov_withdrawn_by_nct, and a registry fact gets
    ctgov_withdrawn: true once every NCT in ctgov_nct_ids has withdrawn it, so
    the result does not depend on the order the NCTs are refreshed in. An
    extracted fact only ever gets the per-NCT entry: its registry corroboration
    is withdrawn, the fact itself is not.

    Returns "withdrawn" when the flag was set, "updated" when only the per-NCT
    entry was added, None when nothing changed.
    """
    ids = target.get("ctgov_nct_ids") or []
    if registry and ids == [nct]:
        target["ctgov_withdrawn"] = True
        return "withdrawn"
    by_nct = target.get(WITHDRAWN_BY_NCT)
    if not isinstance(by_nct, dict):
        by_nct = {}
    if by_nct.get(nct) is True:
        return None
    by_nct[nct] = True
    target[WITHDRAWN_BY_NCT] = by_nct
    if registry and all(by_nct.get(i) is True for i in ids):
        target["ctgov_withdrawn"] = True
        return "withdrawn"
    return "updated"


def _join_withdrawn(target: dict, ctx) -> None:
    """A new NCT supports a fact flagged ctgov_withdrawn: the NCTs already
    recorded keep their withdrawal as ctgov_withdrawn_by_nct entries and the
    flag is dropped (counted as restored in a refresh), so the outcome does not
    depend on whether the join or the earlier NCT's next sweep comes first.
    A join is not counted in updated_nodes / updated_edges: those count facts
    the refreshed NCT had already recorded, and a joining NCT records the fact
    for the first time (its merge is not counted there either).
    """
    if target.pop("ctgov_withdrawn", None) is None:
        return
    by_nct = target.get(WITHDRAWN_BY_NCT)
    by_nct = by_nct if isinstance(by_nct, dict) else {}
    for i in target.get("ctgov_nct_ids") or []:
        by_nct.setdefault(i, True)
    if by_nct:
        target[WITHDRAWN_BY_NCT] = by_nct
    if ctx is not None:
        ctx["stats"]["restored"] += 1


def _refresh_bookkeeping(target, key, value, rename, nct, differs=None) -> bool:
    """Record a refreshed value that differs from, or equals, the plain value
    of a target this NCT does not own. Never modifies target[key].

    differs overrides the plain comparison (used for nested dicts). registry_<attr>
    holds the first conflicting value; it follows this NCT's value only when no
    other NCT holds the value it had. On a graph enriched before _by_nct existed
    (registry_<attr> without registry_<attr>_by_nct), registry_<attr> is taken as
    this NCT's value when this NCT is the only one recorded on the target.
    """
    name = rename.get(key, f"registry_{key}")
    by_key = f"{name}_by_nct"
    by_nct = target.get(by_key)
    seeded = False
    if not isinstance(by_nct, dict):
        by_nct = None
        if name in target and (target.get("ctgov_nct_ids") or []) == [nct]:
            by_nct = {nct: target[name]}
            seeded = True
    if differs is None:
        differs = target.get(key) != value
    if differs:
        if by_nct is None:
            by_nct = {}
        previous = by_nct.get(nct)
        if previous == value and (by_key in target or seeded):
            return False
        others = [v for n, v in by_nct.items() if n != nct]
        by_nct[nct] = value
        target[by_key] = by_nct
        if name not in target or (
            previous is not None and target.get(name) == previous and previous not in others
        ):
            target[name] = value
        return True
    if by_nct is not None and nct in by_nct:
        previous = by_nct.pop(nct)
        if target.get(name) == previous and previous not in by_nct.values():
            if by_nct:
                target[name] = next(iter(by_nct.values()))
            else:
                target.pop(name, None)
        if not by_nct:
            target.pop(by_key, None)
        return True
    return False


def _refresh_nested(target, key, current: dict, value: dict, rename, nct) -> bool:
    """Refresh a dict attribute (by_group, by_seriousness, registry_counts) of a
    target this NCT does not own.

    The first-import rule (_merge_attrs) applies, so a refresh of an unchanged
    payload changes nothing: a sub-key the target lacks is added, and a sub-key
    the target already has keeps its value and is not recorded, because a first
    import records no registry_<attr> for it either (the extracted value and an
    earlier registry value cannot be told apart). A sub-key named by an NCT
    (registry_counts = {NCT: counts}) is this NCT's own entry and is replaced
    in place. A registry_<attr>_by_nct entry of this NCT written by an earlier
    refresh is dropped.
    """
    changed = False
    for sub, subvalue in value.items():
        if NCT_PATTERN.fullmatch(str(sub)):
            if current.get(sub) != subvalue:
                current[sub] = subvalue
                changed = True
        elif sub not in current:
            current[sub] = subvalue
            changed = True
    return _refresh_bookkeeping(target, key, value, rename, nct, differs=False) or changed


def _refresh_attrs(target, attrs, rename, groups, nct, drop_absent: bool = True) -> bool:
    """Apply a refreshed payload to a node/edge attribute dict. True when changed.

    Owned targets get the new values in place, and with drop_absent a payload
    attribute (REGISTRY_PAYLOAD_KEYS) that the new payload no longer produces
    is removed, so the fact matches what a fresh import of the payload writes.
    Other targets only get this NCT's registry_<attr> / registry_<attr>_by_nct
    bookkeeping (and values for attributes or dict sub-keys they lack); a plain
    attribute that is already set is never changed.
    """
    rename = rename or {}
    changed = False
    if _owned_by(target, nct):
        for key, value in attrs.items():
            if value is not None and target.get(key) != value:
                target[key] = value
                changed = True
        if drop_absent:
            for key in [k for k in target if k in REGISTRY_PAYLOAD_KEYS and attrs.get(k) is None]:
                del target[key]
                changed = True
        return changed
    held: set = set()
    for group in groups:
        if any(target.get(k) not in (None, "", []) for k in group):
            held.update(group)
    for key, value in attrs.items():
        if value is None:
            continue
        current = target.get(key)
        if key in held:
            changed |= _refresh_bookkeeping(target, key, value, rename, nct)
        elif current in (None, "", []):
            # An empty value equal to the payload's (e.g. []) is not a change.
            if current != value:
                target[key] = value
                changed = True
        elif isinstance(current, dict) and isinstance(value, dict):
            changed |= _refresh_nested(target, key, current, value, rename, nct)
        else:
            changed |= _refresh_bookkeeping(target, key, value, rename, nct)
    return changed


def _merge_into_node(kg, node_id, attrs, nct, counters, rename=None, count=False, groups=()) -> bool:
    """Merge registry attributes into an existing node under the merge rules.

    Returns True when this NCT was newly recorded on the node.

    In a refresh only the first write of the NCT to a node is applied, as in a
    first import (where a repeated write for a recorded NCT is a no-op): two
    measures of one trial that share a title keep the first measure's values.
    """
    node = kg.graph.nodes[node_id]
    target = _node_attrs(kg, node_id)
    ctx = _refresh_ctx(counters, nct)
    seen = ctx is not None and node_id in ctx["nodes"]
    if ctx is not None:
        ctx["nodes"].add(node_id)
    if nct in (target.get("ctgov_nct_ids") or []):
        if ctx is not None and not seen:
            restored_before = ctx["stats"]["restored"]
            dropped = _restore(target, ctx, nct)
            # A shared registry node keeps an attribute the owner's payload no
            # longer has: another NCT's first import may have filled it.
            changed = _refresh_attrs(
                target, attrs, rename, () if target.get("source") == REGISTRY_SOURCE else groups, nct,
                drop_absent=(target.get("ctgov_nct_ids") or []) == [nct],
            )
            if changed or dropped or ctx["stats"]["restored"] != restored_before:
                ctx["stats"]["updated_nodes"] += 1
        return False
    if target.get("source") == REGISTRY_SOURCE:
        _append_unique(node, "source_documents", f"ctgov:{nct}")
        _merge_attrs(target, attrs, rename, nct=nct)
    else:
        _merge_attrs(target, attrs, rename, groups, nct=nct)
        _append_unique(target, "sources", REGISTRY_SOURCE)
        if count:
            counters["merged"] += 1
            by_type = counters.setdefault("merged_by_type", {})
            etype = str(node.get("entity_type") or "")
            by_type[etype] = by_type.get(etype, 0) + 1
    _join_withdrawn(target, ctx)
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
    ctx = _refresh_ctx(counters, nct)
    if ctx is not None:
        ctx["nodes"].add(node_id)
    return True


def _find_edge(kg, src, rel, tgt):
    """(key, data) of the first edge src -rel-> tgt, or (None, None)."""
    for key, data in sorted((kg.graph.get_edge_data(src, tgt) or {}).items(), key=lambda kv: str(kv[0])):
        if data.get("relation_type") == rel:
            return key, data
    return None, None


def _upsert_edge(kg, src, rel, tgt, nct, evidence, attrs, counters) -> bool:
    """Create or merge a registry edge; a repeated call for the same NCT is a no-op.

    In a refresh only the first write of the NCT to an edge is applied (as in a
    first import), and a registry edge first written by another NCT gets no
    attributes for this NCT, because a first import records none there either.
    """
    if not (kg.graph.has_node(src) and kg.graph.has_node(tgt)):
        return False
    attrs = {k: v for k, v in (attrs or {}).items() if v is not None}
    ctx = _refresh_ctx(counters, nct)
    seen = ctx is not None and (src, rel, tgt) in ctx["edges"]
    if ctx is not None:
        ctx["edges"].add((src, rel, tgt))
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
        ctx = _refresh_ctx(counters, nct)
        if ctx is not None:
            ctx["edges"].add((src, rel, tgt))
        return True
    target = data.get("attributes")
    if not isinstance(target, dict):
        target = {}
        data["attributes"] = target
    if nct in (target.get("ctgov_nct_ids") or []):
        if ctx is not None and not seen:
            restored_before = ctx["stats"]["restored"]
            dropped = _restore(target, ctx, nct)
            shared_registry = target.get("source") == REGISTRY_SOURCE and not _owned_by(target, nct)
            # Every attribute of a registry edge comes from its owner (another
            # NCT only adds a mention), so absent payload keys are removed.
            changed = dropped
            if not shared_registry:
                changed = _refresh_attrs(target, attrs, None, (), nct) or changed
            if _owned_by(target, nct) and len(target.get("ctgov_nct_ids") or []) == 1:
                # A reload derives the edge evidence from the mentions, so the
                # mention of this NCT carries the new text as well.
                for mention in data.get("mentions") or []:
                    if (
                        isinstance(mention, dict)
                        and mention.get("source_document") == f"ctgov:{nct}"
                        and mention.get("evidence") != evidence
                    ):
                        mention["evidence"] = evidence
                        changed = True
                if data.get("evidence") != evidence:
                    data["evidence"] = evidence
                    changed = True
            if changed or ctx["stats"]["restored"] != restored_before:
                ctx["stats"]["updated_edges"] += 1
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
        _merge_attrs(target, attrs, nct=nct)
        _append_unique(target, "sources", REGISTRY_SOURCE)
    _join_withdrawn(target, _refresh_ctx(counters, nct))
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


def _trial_edge_source(kg, trial_ids, rel, tgt, nct=None) -> str:
    """The Trial node a registry edge src -rel-> tgt is written from.

    REFRESH-02: the edge that already records this NCT, so a Trial node added
    after the first import never gets a second copy of the NCT's data (lowest
    id first; an edge the registry created for this NCT before an extracted
    edge it was merged into, which only graphs enriched by iterations 27-31
    can hold both of). Otherwise the first Trial node of the NCT (lowest id
    first) that has the edge, so registry data merges into an extracted edge
    on a non-canonical Trial node instead of beside it; else the canonical node.
    """
    edges = [(tid, _find_edge(kg, tid, rel, tgt)[1]) for tid in trial_ids]
    if nct is not None:
        recorded = [
            (tid, _plain_attrs(d)) for tid, d in edges
            if d is not None and nct in (_plain_attrs(d).get("ctgov_nct_ids") or [])
        ]
        owned = next((tid for tid, a in recorded if _owned_by(a, nct)), None)
        if owned is not None:
            return owned
        if recorded:
            return recorded[0][0]
    return next((tid for tid, d in edges if d is not None), trial_ids[0])


def _trial_edge_sources(kg, trial_ids, rel, tgt, nct, counters) -> list:
    """The Trial nodes a registry edge src -rel-> tgt is written from: the one
    _trial_edge_source picks and, in a refresh, every other Trial node of the
    NCT whose edge is an extracted edge recording the NCT. A graph enriched by
    iterations 27-31 can hold such a second copy (the registry merged into an
    extracted edge of a lower-id Trial node added after the first import);
    both copies then follow the payload. Registry copies from before iteration
    27 are not written (see _legacy_copy).
    """
    first = _trial_edge_source(kg, trial_ids, rel, tgt, nct)
    if _refresh_ctx(counters, nct) is None:
        return [first]
    sources = [first]
    for tid in trial_ids:
        if tid == first:
            continue
        attrs = _plain_attrs(_find_edge(kg, tid, rel, tgt)[1] or {})
        if nct in (attrs.get("ctgov_nct_ids") or []) and attrs.get("source") != REGISTRY_SOURCE:
            sources.append(tid)
    return sources


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
        # REFRESH-02: one edge, from the canonical Trial node (lowest id), or
        # merged into the edge another Trial node of this NCT already has.
        for src in _trial_edge_sources(kg, trial_ids, "reports_adverse_event", ae_id, nct, counters):
            _upsert_edge(
                kg, src, "reports_adverse_event", ae_id, nct, evidence, edge_attrs, counters,
            )

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
        "outcome_param_type": _outcome_param_type(an),
        "compared_groups": titles,
        "unmatched_groups": unmatched,
    }
    return {k: v for k, v in attrs.items() if v is not None}


def _outcome_param_type(an) -> str | None:
    """The registry outcome-measure paramType (MEAN, LEAST_SQUARES_MEAN,
    COUNT_OF_PARTICIPANTS, ...) an analysis belongs to, read by the epistemic
    layer to classify the outcome kind (CONTEST-02)."""
    value = an.get("outcome_param_type")
    return value.strip() if isinstance(value, str) and value.strip() else None


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


# CONTEST-04: treatment from CT.gov armGroup types. This is the same resolver as
# epistemic._arm_type_treatment (the grading layer's fallback): the comparator
# wording below is epistemic's HARD_PLACEBO_KEYWORDS / SOFT_PLACEBO_KEYWORDS with
# the same soft-keyword rules (an add-on to usual care is an active arm,
# "glycaemic control" names no arm), copied because domain modules are loaded
# by path and import nothing from each other. The one intended difference: a
# Compound name two Compound nodes share resolves to nothing here, so an edge is
# written only when grading would reach the same compound
# (tests/test_ctgov_results.py::test_contest04_resolver_parity_with_epistemic).
ARM_EXPERIMENTAL = "EXPERIMENTAL"
ARM_COMPARATOR_TYPES = frozenset({
    "ACTIVE_COMPARATOR", "PLACEBO_COMPARATOR", "SHAM_COMPARATOR", "NO_INTERVENTION",
})
ARM_TYPE_BASIS = "registry_arm_type"
MIN_COMPOUND_NAME = 3
ARM_HARD_COMPARATOR_KEYWORDS = ("placebo", "comparator")
ARM_SOFT_COMPARATOR_KEYWORDS = ("standard of care", "usual care", "control")


def _arm_keyword_re(words) -> re.Pattern:
    return re.compile(
        r"(?<![A-Za-z0-9])(?:" + "|".join(re.escape(k) for k in words) + r")(?![A-Za-z0-9])",
        re.IGNORECASE,
    )


_HARD_COMPARATOR_RE = _arm_keyword_re(ARM_HARD_COMPARATOR_KEYWORDS)
_SOFT_COMPARATOR_RE = _arm_keyword_re(ARM_SOFT_COMPARATOR_KEYWORDS)
_COMPARATOR_WORDING_RE = _arm_keyword_re(ARM_HARD_COMPARATOR_KEYWORDS + ARM_SOFT_COMPARATOR_KEYWORDS)
_ARM_ADD_ON_RE = re.compile(
    r"\+|(?<![A-Za-z0-9])(?:plus|with|and|added to|add-on to|on top of|in addition to)(?![A-Za-z0-9])",
    re.IGNORECASE,
)
# A word naming what "control" controls; "glycaemic control" names no arm.
_ARM_CONTROL_QUALIFIER_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:glyc\w*|glucose|weight|pressure|metabolic|lipids?|sugar|appetite|"
    r"diabet\w*|disease|symptoms?|pain|rate|rhythm|infection)[\s-]+$",
    re.IGNORECASE,
)
# "Drug: Tirzepatide" -> "Tirzepatide" (CT.gov intervention names carry the type).
_INTERVENTION_PREFIX_RE = re.compile(
    r"^\s*(?:Drug|Biological|Combination Product|Other|Dietary Supplement|Device|"
    r"Procedure|Behavioral|Genetic|Radiation|Diagnostic Test)\s*:\s*",
    re.IGNORECASE,
)


def _arm_soft_spans(text: str) -> list:
    """(start, end) of every soft comparator keyword; a qualified "control"
    ("glycaemic control") is skipped."""
    spans = []
    for found in _SOFT_COMPARATOR_RE.finditer(text):
        if found.group(0).lower() == "control" and _ARM_CONTROL_QUALIFIER_RE.search(text, 0, found.start()):
            continue
        spans.append(found.span())
    return spans


def _arm_split_parentheticals(text: str):
    """(text with every parenthetical blanked to spaces, the contents of its
    top-level parentheticals). Positions in the blanked text match text."""
    outside, segments, inner, depth = [], [], [], 0
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


def _arm_joined(text: str, spans, index) -> set:
    """Compounds joined to a soft keyword span by an add-on connector, in either order."""
    joined = set()
    for cid, pattern in index:
        for found in pattern.finditer(text):
            for start, end in spans:
                gap = (found.end(), start) if found.end() <= start else (end, found.start())
                if gap[0] <= gap[1] and _ARM_ADD_ON_RE.search(text, gap[0], gap[1]):
                    joined.add(cid)
    return joined


def _arm_soft(text: str, index):
    """(is comparator, arm compounds) of a text with a soft keyword, or None when
    it has none (epistemic._soft_arm): a soft keyword outside parentheses is a
    comparator unless a compound outside parentheses is joined to it by an add-on
    connector ("Semaglutide + usual care"); a soft keyword only inside a
    parenthetical is a comparator ("Insulin glargine (control)") unless the
    parenthetical joins it to the arm ("Semaglutide (added to standard of care)").
    """
    outside, segments = _arm_split_parentheticals(text)
    spans = _arm_soft_spans(outside)
    if spans:
        joined = _arm_joined(outside, spans, index)
        return (False, joined) if joined else (True, set())
    inside = [segment for segment in segments if _arm_soft_spans(segment)]
    if not inside:
        return None
    named = {cid for cid, pattern in index if pattern.search(outside)}
    for segment in inside:
        first = _arm_soft_spans(segment)[0]
        if named and _ARM_ADD_ON_RE.search(segment, 0, first[0]):
            return False, named
    return True, set()


def _is_comparator_title(text, index) -> bool:
    """True when text names a comparator arm (hard keyword, or soft keyword not
    joined to an active add-on compound)."""
    if not isinstance(text, str) or not text:
        return False
    if _HARD_COMPARATOR_RE.search(text):
        return True
    soft = _arm_soft(text, index)
    return soft is not None and soft[0]


def _compound_index(kg) -> list:
    """(compound id, word-boundary pattern) for every Compound named by 3+ chars.

    A comparator-worded name ("Standard of care") names no treatment and is not
    indexed. A name two Compound nodes share is indexed with id None: a group that
    names it resolves to no treatment (see _arm_type_compound).
    """
    names: dict = {}
    for node_id, data in kg.graph.nodes(data=True):
        if str(data.get("entity_type", "")).lower() != "compound":
            continue
        name = str(data.get("name") or "").strip()
        if len(name) < MIN_COMPOUND_NAME or _COMPARATOR_WORDING_RE.search(name):
            continue
        names.setdefault(name.lower(), []).append((node_id, name))
    index = []
    for key in sorted(names):
        node_id, name = names[key][0]
        if len(names[key]) != 1:
            node_id = None
        index.append((node_id, re.compile(
            r"(?<![A-Za-z0-9])" + re.escape(name) + r"(?![A-Za-z0-9])", re.IGNORECASE
        )))
    return index


def _text_compounds(text, index) -> set:
    """Compounds a text names (epistemic._compounds_in_text): comparator text names
    none ("Usual care (metformin)"), an add-on arm names the compounds joined to
    its soft keyword ("Semaglutide + usual care")."""
    if not isinstance(text, str) or not text or _HARD_COMPARATOR_RE.search(text):
        return set()
    soft = _arm_soft(text, index)
    if soft is not None:
        return soft[1]
    return {cid for cid, pattern in index if pattern.search(text)}


def _group_compound_ids(group, index) -> set:
    """Compounds an armGroup names: its title, else its non-placebo interventions."""
    found = _text_compounds(group.get("title"), index)
    if not found:
        for intervention in group.get("interventions") or ():
            if isinstance(intervention, str) and not _HARD_COMPARATOR_RE.search(intervention):
                found |= _text_compounds(_INTERVENTION_PREFIX_RE.sub("", intervention), index)
    return found


def _arm_type_compound(arm_groups, index):
    """The one Compound a registry analysis assesses, resolved from armGroup types.

    The same rules as epistemic._arm_type_treatment. Needs at least two compared groups,
    every one typed, exactly one EXPERIMENTAL and every other group a comparator
    type. An EXPERIMENTAL group titled as a comparator (a blinded placebo arm, or
    "Usual care" not joined to a compound) names no treatment. The compound is the one the EXPERIMENTAL title names or,
    when the title names none, one its interventions name; when that is several,
    the compounds every comparator group also names (add-on background) are
    dropped. None unless exactly one compound remains.
    """
    if not isinstance(arm_groups, list) or len(arm_groups) < 2:
        return None
    if not all(isinstance(g, dict) and isinstance(g.get("arm_type"), str) for g in arm_groups):
        return None
    experimental = [g for g in arm_groups if g["arm_type"] == ARM_EXPERIMENTAL]
    if len(experimental) != 1:
        return None
    comparators = [g for g in arm_groups if g is not experimental[0]]
    if not all(g["arm_type"] in ARM_COMPARATOR_TYPES for g in comparators):
        return None
    arm = experimental[0]
    if _is_comparator_title(arm.get("title"), index):
        return None
    found = _group_compound_ids(arm, index)
    if None in found:
        return None
    if len(found) > 1 and comparators:
        background = set.intersection(*(_group_compound_ids(g, index) for g in comparators))
        if found - background:
            found = found - background
    return next(iter(found)) if len(found) == 1 else None


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
    The backfill is counted as neither created nor merged. A --refresh-results
    run replaces it on a registry-owned analysis, so it follows the payload.

    A registry-created analysis without an assesses_effect_of edge after the
    Cohort-receives rule gets one from its armGroup types (_arm_type_compound),
    written through _upsert_edge with treatment_basis registry_arm_type; merged
    extracted analyses are never written to, and an ambiguous resolution writes
    nothing. Withdrawn edges block nothing; a live arm-type edge to another
    compound is replaced only in a refresh (the sweep withdraws the old one).
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
    outcome_merges: set = set()
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
            reused_extracted = (
                _plain_attrs(kg.graph.nodes[outcome_id]).get("source") != REGISTRY_SOURCE
            )
            if not reused_extracted and _refresh_ctx(counters, nct) is not None:
                # A refresh re-reads the registry Outcome (and its trial edge) this
                # NCT wrote, so it counts as present and takes the new attributes.
                _upsert_node(
                    kg, outcome_id, "Outcome", title,
                    {
                        "endpoint_type": str(an.get("outcome_type") or "").capitalize() or None,
                        "timeframe": time_frame,
                        "unit": unit,
                    },
                    nct, counters,
                )
                for src in _trial_edge_sources(kg, trial_ids, "has_outcome", outcome_id, nct, counters):
                    _upsert_edge(
                        kg, src, "has_outcome", outcome_id, nct,
                        f"ClinicalTrials.gov results {nct}: outcome {title}", {}, counters,
                    )
        else:
            reused_extracted = False
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
            # REFRESH-02: one edge, from the canonical Trial node (lowest id).
            for src in _trial_edge_sources(kg, trial_ids, "has_outcome", outcome_id, nct, counters):
                _upsert_edge(
                    kg, src, "has_outcome", outcome_id, nct,
                    f"ClinicalTrials.gov results {nct}: outcome {title}", {}, counters,
                )
            outcome_by_norm.setdefault(norm, []).append(outcome_id)
        prepared.append({
            "an": an, "title": title, "name": name, "id": f"outcomeanalysis:{_slug(name)}",
            "outcome": outcome_id, "reused_extracted": reused_extracted,
            "cohorts": [c for c in cohort_ids if c],
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

    compound_index = None
    for item in prepared:
        an = item["an"]
        holder = holder_by_reg.get(item["id"])
        ctx = _refresh_ctx(counters, nct)
        updated_before = ctx["stats"]["updated_nodes"] if ctx is not None else None
        existed = kg.graph.has_node(item["id"])
        if holder is not None and kg.graph.has_node(holder) and holder != item["id"]:
            oa_id = holder
            attrs = _node_attrs(kg, oa_id)
            if _refresh_ctx(counters, nct) is not None or nct not in (attrs.get("ctgov_nct_ids") or []):
                _merge_into_node(
                    kg, oa_id, item["attrs"], nct, counters, count=True, groups=ANALYSIS_STAT_GROUPS,
                )
                _append_unique(attrs, "ctgov_analysis_ids", item["id"])
        else:
            oa_id = item["id"]
            _upsert_node(
                kg, oa_id, "OutcomeAnalysis", item["name"], item["attrs"], nct, counters, count=True,
            )
        node_attrs = _node_attrs(kg, oa_id)
        if ctx is not None and oa_id == item["id"] and _owned_by(node_attrs, nct):
            # A refresh re-reads the arm types of a registry-owned analysis, so
            # the stored groups follow the payload the edge is written from: they
            # are replaced, or removed when the payload gives none any more (no
            # armGroups, or no compared group matches an arm), so grading cannot
            # resolve the old compound from them. A change to a node that existed
            # before this refresh counts as an updated node, once per node; an
            # analysis the refresh creates counts as created only.
            previous = node_attrs.get("ctgov_arm_groups")
            if item["arm_groups"]:
                node_attrs["ctgov_arm_groups"] = item["arm_groups"]
            else:
                node_attrs.pop("ctgov_arm_groups", None)
            if (
                existed
                and previous != node_attrs.get("ctgov_arm_groups")
                and ctx["stats"]["updated_nodes"] == updated_before
            ):
                ctx["stats"]["updated_nodes"] += 1
        elif item["arm_groups"]:
            node_attrs.setdefault("ctgov_arm_groups", item["arm_groups"])
        text = _registry_text(
            f"ClinicalTrials.gov results {nct}: {item['title']} — {' vs '.join(item['groups'])},",
            an.get("param_type"), an.get("param_value"),
            f"({an['ci_pct_value']}% CI {an.get('ci_lower_limit')} to {an.get('ci_upper_limit')}),"
            if an.get("ci_pct_value") not in (None, "") else None,
            f"p {an['p_value']}" if an.get("p_value") not in (None, "") else None,
        ).rstrip(",")
        wrote_analyzes = _upsert_edge(kg, oa_id, "analyzes", item["outcome"], nct, text, {}, counters)
        if wrote_analyzes and item["reused_extracted"] and item["outcome"] not in outcome_merges:
            # REFRESH-03: a registry analysis reusing an extracted Outcome is one
            # merge per (outcome, NCT); the Outcome node itself is not modified.
            outcome_merges.add(item["outcome"])
            counters["merged"] += 1
            by_type = counters.setdefault("merged_by_type", {})
            by_type["Outcome"] = by_type.get("Outcome", 0) + 1
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
        # CONTEST-04: a registry-created analysis the Cohort rule left without an
        # assesses_effect_of edge gets one from its armGroup types, tagged
        # treatment_basis registry_arm_type. An extracted analysis (a merged
        # holder) is never written to. The write is repeated on a re-run or refresh
        # for an edge already recorded, so a refresh sweep sees it as present.
        if oa_id == item["id"] and item["arm_groups"] and (
            _node_attrs(kg, oa_id).get("source") == REGISTRY_SOURCE
        ):
            # Only live edges count: a withdrawn edge (an earlier resolution the
            # payload no longer gives) blocks nothing. A live arm-type edge to
            # another compound blocks a new one outside a refresh; in a refresh
            # the new edge is written and the sweep withdraws the old one.
            live = {}
            for tgt in _out_targets(kg, oa_id, "assesses_effect_of"):
                edge_attrs = ((_find_edge(kg, oa_id, "assesses_effect_of", tgt)[1] or {}).get("attributes") or {})
                if edge_attrs.get("ctgov_withdrawn") is not True:
                    live[tgt] = edge_attrs
            if all(a.get("treatment_basis") == ARM_TYPE_BASIS for a in live.values()):
                if compound_index is None:
                    compound_index = _compound_index(kg)
                compound_id = _arm_type_compound(item["arm_groups"], compound_index)
                if compound_id is not None and (
                    not live or compound_id in live or _refresh_ctx(counters, nct) is not None
                ):
                    _upsert_edge(
                        kg, oa_id, "assesses_effect_of", compound_id, nct, text,
                        {"treatment_basis": ARM_TYPE_BASIS}, counters,
                    )
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


def _has_registry_edge(kg, nct, trial_ids) -> bool:
    """True when an edge out of any of these Trial nodes carries this NCT from the registry."""
    for tid in trial_ids:
        for _, _, data in kg.graph.out_edges(tid, data=True):
            attrs = data.get("attributes")
            if (
                isinstance(attrs, dict)
                and attrs.get("source") == REGISTRY_SOURCE
                and nct in (attrs.get("ctgov_nct_ids") or [])
            ):
                return True
    return False


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

    first_import = len(trial_ids) > 1 and not _has_registry_edge(kg, nct, trial_ids)
    _write_adverse_events(kg, nct, parsed, trial_ids, match, counters)
    _write_analyses(
        kg, nct, parsed, trial_ids, {c[0] for c in cohorts}, match, counters, arm_match,
    )
    if first_import and _has_registry_edge(kg, nct, trial_ids):
        # REFRESH-02: the registry edges live on the canonical Trial node only.
        for tid in trial_ids[1:]:
            _node_attrs(kg, tid).setdefault("same_trial_as", trial_ids[0])


_AE_NODE_TYPES = ("adverseevent", "organsystem")
_AE_RELATIONS = ("reports_adverse_event", "observed_in", "affects_organ_system")


def _new_refresh_stats() -> dict:
    return {
        "trials_refreshed": 0, "updated_nodes": 0, "updated_edges": 0,
        "withdrawn": 0, "restored": 0, "legacy_copies_skipped": 0,
    }


def _has_recorded_facts(kg, nct) -> bool:
    """True when a node or edge already records this NCT (ctgov_nct_ids)."""
    for _, data in kg.graph.nodes(data=True):
        if nct in (_plain_attrs(data).get("ctgov_nct_ids") or []):
            return True
    for _, _, data in kg.graph.edges(data=True):
        if nct in (_plain_attrs(data).get("ctgov_nct_ids") or []):
            return True
    return False


def _legacy_copy(kg, trial_ids, src, rel, tgt, nct, attrs, touched) -> bool:
    """True when the untouched edge src -rel-> tgt recording nct is a second
    copy of a fact another Trial node of the NCT holds (also recording nct).

    It is when the refresh wrote the fact through that other edge (touched
    holds the (src, rel, tgt) the refresh wrote), wherever src sorts: the fact
    is live. When no copy was written (the payload no longer has the fact),
    only a registry edge from a non-canonical Trial node beside another
    registry copy is one (registry edges written per Trial node before
    iteration 27). Any other copy, e.g. the registry edge this NCT created
    beside an extracted edge the registry later merged into on a lower-id
    Trial node (iterations 27-31), is swept like the rest.
    """
    others = []
    for tid in trial_ids:
        if tid == src:
            continue
        _, data = _find_edge(kg, tid, rel, tgt)
        if data is not None and nct in (_plain_attrs(data).get("ctgov_nct_ids") or []):
            if (tid, rel, tgt) in touched:
                return True
            others.append(_plain_attrs(data))
    if not others or src not in trial_ids[1:]:
        return False
    return attrs.get("source") == REGISTRY_SOURCE and any(
        o.get("source") == REGISTRY_SOURCE for o in others
    )


def _refresh_sweep(kg, nct, trial_ids, ctx, skip_ae: bool) -> None:
    """Record the facts of this NCT that the refreshed payload did not touch
    (see _withdraw). Nothing is deleted.

    A registry fact this NCT alone supports gets ctgov_withdrawn: true. On a
    fact other NCTs also support, this NCT goes into ctgov_withdrawn_by_nct,
    and a registry fact is flagged ctgov_withdrawn once every NCT recorded on
    it has withdrawn it. An extracted node or edge the registry merged into
    only gets the per-NCT entry; its extracted values are untouched. A per-NCT
    entry alone counts as an updated node or edge, the flag as withdrawn.

    When two Trial nodes of the NCT have the same edge recording the NCT (see
    _legacy_copy), the copy the refresh did not write is left as it is and
    counted as legacy_copies_skipped while the refresh wrote the other one;
    when it wrote neither, only registry copies from before iteration 27 are
    skipped, and every other copy is swept. An edge on a non-canonical Trial
    node that is the NCT's only copy (REFRESH-02 writes through the edge that
    records the NCT, e.g. after a lower-id Trial node was extracted later) is
    swept like any other. skip_ae leaves adverse-event facts alone (the
    trial's adverse events were not rewritten, see the serious floor).
    """
    stats = ctx["stats"]
    for src, tgt, key, data in list(kg.graph.edges(keys=True, data=True)):
        attrs = data.get("attributes")
        if not isinstance(attrs, dict) or nct not in (attrs.get("ctgov_nct_ids") or []):
            continue
        rel = data.get("relation_type")
        if (src, rel, tgt) in ctx["edges"] or "ctgov_withdrawn" in attrs:
            continue
        if skip_ae and rel in _AE_RELATIONS:
            continue
        registry = attrs.get("source") == REGISTRY_SOURCE
        if src in trial_ids and _legacy_copy(kg, trial_ids, src, rel, tgt, nct, attrs, ctx["edges"]):
            stats["legacy_copies_skipped"] += 1
            continue
        result = _withdraw(attrs, nct, registry)
        if result == "withdrawn":
            stats["withdrawn"] += 1
        elif result == "updated":
            stats["updated_edges"] += 1
    for node_id, data in kg.graph.nodes(data=True):
        attrs = data.get("attributes")
        if (
            not isinstance(attrs, dict)
            or nct not in (attrs.get("ctgov_nct_ids") or [])
            or node_id in ctx["nodes"]
            or "ctgov_withdrawn" in attrs
        ):
            continue
        if skip_ae and str(data.get("entity_type", "")).lower() in _AE_NODE_TYPES:
            continue
        result = _withdraw(attrs, nct, attrs.get("source") == REGISTRY_SOURCE)
        if result == "withdrawn":
            stats["withdrawn"] += 1
        elif result == "updated":
            stats["updated_nodes"] += 1


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
        "merged_by_type": {"AdverseEvent": 0, "OutcomeAnalysis": 0, "Outcome": 0},
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
    refresh: bool = False,
    cache_ttl_days: float | None = None,
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
        refresh: Re-import registry facts that are already recorded (needs
            results): update in place, add new facts, mark vanished ones
            ctgov_withdrawn. Adds results.refresh to the report.
        cache_ttl_days: Refetch cached payloads older than this many days (needs
            cache_dir; None never expires). Adds a top-level "cache" report block.

    Returns:
        Report dict with domain, trials counts, compounds counts, hit_rate.
    """
    serious_min_pct = _check_serious_min_pct(serious_min_pct)
    if cache_ttl_days is not None:
        cache_ttl_days = _check_cache_ttl(cache_ttl_days)
        if cache_dir is None:
            raise ValueError("cache_ttl_days needs cache_dir")
    if refresh and not results:
        raise ValueError("refresh needs results")
    cache_stats = (
        {"ttl_days": cache_ttl_days, "expired": 0, "refetched": 0, "stale_used": 0,
         "stale_after_not_found": 0}
        if cache_ttl_days is not None else None
    )
    refresh_stats = _new_refresh_stats()
    output_dir = Path(output_dir)
    graph_path = output_dir / "graph_data.json"
    if not graph_path.exists():
        report = _build_report(domain, 0, 0, 0, 0, 0, 0, 0, 0)
        if results:
            report["results"] = _empty_results_block()
            if refresh:
                report["results"]["refresh"] = refresh_stats
        if cache_stats is not None:
            report["cache"] = cache_stats
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
    no_results_ncts: set = set()

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
                studies_by_nct[candidate], _ = _get_ct_gov_study(
                    candidate, cache_dir, cache_ttl_days, cache_stats,
                )
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
                            no_results_ncts.add(candidate)
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

    if results and (parsed_by_nct or (refresh and no_results_ncts)):
        if kg is None:
            results_block["skipped_reason"] = (
                "sift_kg unavailable: registry results were parsed but not written"
                if parsed_by_nct else
                "sift_kg unavailable: the refresh of trials without results was not applied"
            )
            serious_omitted = sum(p.get("serious_events_omitted", 0) for p in parsed_by_nct.values())
        else:
            counters = _new_counters()
            write_errors: dict = {}
            sweep_only = no_results_ncts if refresh else set()
            for nct in sorted(set(parsed_by_nct) | sweep_only):
                to_write = parsed_by_nct.get(nct)
                prior = (
                    _prior_serious_floors(kg, trial_ids_by_nct[nct], nct)
                    if to_write is not None else set()
                )
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
                refresh_before = dict(refresh_stats)
                try:
                    # Only a trial with facts already recorded is refreshed; a
                    # first import is not counted under trials_refreshed.
                    refreshing = refresh and _has_recorded_facts(kg, nct)
                    if refresh:
                        counters["refresh"] = {
                            "nct": nct, "nodes": set(), "edges": set(), "stats": refresh_stats,
                        }
                    if to_write is not None:
                        _write_results(
                            kg, nct, to_write, sorted(trial_ids_by_nct[nct]), counters
                        )
                        if nct not in floor_conflicts:
                            serious_omitted += to_write.get("serious_events_omitted", 0)
                    if refresh:
                        _refresh_sweep(
                            kg, nct, sorted(trial_ids_by_nct[nct]), counters["refresh"],
                            skip_ae=nct in floor_conflicts,
                        )
                        if refreshing:
                            counters["refresh"]["stats"]["trials_refreshed"] += 1
                        counters["refresh"] = None
                except Exception as exc:
                    kg.graph = graph_before
                    counters = counters_before
                    refresh_stats.update(refresh_before)
                    message = f"{type(exc).__name__}: {exc}"
                    write_errors[nct] = message
                    results_block["write_failed"] += 1
                    print(f"enrich.py: registry write failed for {nct}: {message}", file=sys.stderr)
            results_block["created_nodes"] = counters["created_nodes"]
            results_block["created_edges"] = counters["created_edges"]
            results_block["created"] = counters["created_nodes"] + counters["created_edges"]
            results_block["merged"] = counters["merged"]
            results_block["merged_by_type"] = dict(counters["merged_by_type"])
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
        if refresh:
            results_block["refresh"] = refresh_stats
        report["results"] = results_block
    if cache_stats is not None:
        report["cache"] = cache_stats
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


def _check_cache_ttl(value) -> float:
    """Validate the cache TTL in days: a finite number >= 0."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"cache_ttl_days must be a number, got {value!r}")
    value = float(value)
    if not (0.0 <= value < float("inf")):  # also rejects NaN
        raise ValueError(f"cache_ttl_days must be a finite number >= 0, got {value!r}")
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
    parser.add_argument("--refresh-results", action="store_true")
    parser.add_argument("--cache-ttl-days", type=float, default=None)
    args = parser.parse_args()
    cache_ttl_days = None
    if args.cache_ttl_days is not None:
        try:
            cache_ttl_days = _check_cache_ttl(args.cache_ttl_days)
        except ValueError as exc:
            parser.error(str(exc))
        if args.cache_dir is None:
            parser.error("--cache-ttl-days needs --cache-dir")
    if args.refresh_results and not args.results:
        parser.error("--refresh-results needs --results")
    try:
        serious_min_pct = _check_serious_min_pct(args.results_serious_min_pct)
    except ValueError as exc:
        parser.error(str(exc))
    if serious_min_pct > 0 and not args.results:
        parser.error("--results-serious-min-pct needs --results")
    report = enrich_graph(
        Path(args.output_dir), results=args.results, cache_dir=args.cache_dir,
        serious_min_pct=serious_min_pct, refresh=args.refresh_results,
        cache_ttl_days=cache_ttl_days,
    )
    print(json.dumps(report, indent=2))
