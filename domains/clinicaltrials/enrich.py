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
counted in a "results" block of _enrichment_report.json. Parsed results are
not yet written to the graph; the graph written with --results equals the
graph written without it. Without --results, behaviour is unchanged.

Non-blocking: API failures log counts but never abort the pipeline.
ARCH-03: no core/ changes required; this module lives in the domain package.

Usage:
    python3 domains/clinicaltrials/enrich.py <output_dir> [--results] [--cache-dir DIR]

    --results         also parse posted results and add a "results" report block
    --cache-dir DIR   read/write one raw CT.gov payload per trial as DIR/<NCT>.json
"""
from __future__ import annotations

import json
import re
import sys
import time
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
RESULTS_OUTCOME_TYPES = frozenset({"PRIMARY", "SECONDARY"})

PUBCHEM_PROPS = "MolecularFormula,MolecularWeight,CanonicalSMILES,InChI"
PUBCHEM_URL = (
    "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{name}/"
    "property/{props}/JSON"
)
PUBCHEM_TIMEOUT = 30
PUBCHEM_RATE_SLEEP = 0.2  # 5 req/sec official limit
PUBCHEM_MAX_RETRIES = 3

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


def _parse_ct_results(study: dict) -> dict | None:
    """Parse posted results from a CT.gov study payload.

    Returns None when the trial has no posted results. Otherwise returns
    event groups, adverse events (all serious; other events at or above the
    frequency threshold) and PRIMARY/SECONDARY outcome analyses.
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

    def _reaches(stats: list) -> bool:
        for st in stats:
            at_risk, affected = st["num_at_risk"], st["num_affected"]
            if (
                isinstance(at_risk, (int, float)) and at_risk > 0
                and isinstance(affected, (int, float))
                and affected / at_risk * 100 >= threshold
            ):
                return True
        return False

    adverse_events = []
    for seriousness, key in (("serious", "seriousEvents"), ("other", "otherEvents")):
        for ev in _as_list(ae_mod.get(key)):
            ev = _as_dict(ev)
            stats = _stats(ev)
            if seriousness == "other" and not _reaches(stats):
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

    return {
        "nct_id": id_mod.get("nctId"),
        "ae_threshold_pct": threshold,
        "ae_threshold_source": source,
        "event_groups": event_groups,
        "adverse_events": adverse_events,
        "analyses": analyses,
    }


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
    }


def enrich_graph(
    output_dir: Path,
    domain: str = "clinicaltrials",
    results: bool = False,
    cache_dir: Path | None = None,
) -> dict:
    """Load graph, enrich Trial + Compound nodes, save, write report.

    Args:
        output_dir: Directory containing graph_data.json.
        domain: Domain name stamped into the report.
        results: Also parse posted results from the same per-trial payload and
            add a "results" block to the report (counts only; no graph writes).
        cache_dir: Optional directory caching one raw payload per trial.

    Returns:
        Report dict with domain, trials counts, compounds counts, hit_rate.
    """
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
            study, _ = _get_ct_gov_study(candidate, cache_dir)
            try:
                enrichment = _parse_ct_protocol(study) if study is not None else None
            except (AttributeError, TypeError):
                enrichment = None
            if results:
                if study is None:
                    results_block["results_failed"] += 1
                else:
                    try:
                        parsed = _parse_ct_results(study)
                    except Exception:
                        results_block["results_failed"] += 1
                    else:
                        if parsed is None:
                            results_block["trials_without_results"] += 1
                        else:
                            results_block["trials_with_results"] += 1
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
        report["results"] = results_block
    _write_report(output_dir, report)
    return report


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


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
    args = parser.parse_args()
    report = enrich_graph(
        Path(args.output_dir), results=args.results, cache_dir=args.cache_dir
    )
    print(json.dumps(report, indent=2))
