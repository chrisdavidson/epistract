"""Offline contract tests for opt-in ClinicalTrials.gov results enrichment.

The module under test is domains/clinicaltrials/enrich.py, or the file named by
the CT_ENRICH_PATH environment variable (used to run these tests against a
staged copy of the module before it is applied). Every network call is mocked.
"""
from __future__ import annotations

import copy
import glob
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

EPI_ROOT = Path(__file__).resolve().parents[1]
FIX = Path(__file__).parent / "fixtures" / "ctgov"
CTGOV_PREFIX = "https://clinicaltrials.gov/api/v2/studies/"
OLD_COMMIT = "c80444b0f5e12db68661539004eb8d264fde821d"
# Set to 1 to let the byte-identity tests skip when a pinned commit is not in
# the local git history (shallow clone, source tarball). By default they fail.
ALLOW_MISSING_BASELINES_ENV = "CT_ALLOW_MISSING_BASELINES"


def _baseline_enrich_source(commit: str) -> bytes:
    """enrich.py as of a pinned commit, read from git.

    The byte-identity tests guard the "default runs are unchanged" invariant,
    so a missing commit is a failure, not a silent skip, unless
    CT_ALLOW_MISSING_BASELINES=1 is set.
    """
    try:
        shown = subprocess.run(
            ["git", "-C", str(EPI_ROOT), "show", f"{commit}:domains/clinicaltrials/enrich.py"],
            capture_output=True, check=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        message = (
            f"cannot read pinned baseline {commit} from git ({exc}); the byte-identity "
            f"tests need the full epistract history. Fetch it (git fetch --unshallow) or set "
            f"{ALLOW_MISSING_BASELINES_ENV}=1 to skip them."
        )
        if os.environ.get(ALLOW_MISSING_BASELINES_ENV) == "1":
            pytest.skip(message)
        pytest.fail(message)
    return shown.stdout

WITH_RESULTS_A = "NCT05971940"
WITH_RESULTS_B = "NCT03548935"


def _find_no_results_fixture() -> str:
    for f in sorted(glob.glob(str(FIX / "NCT*.json"))):
        body = json.loads(Path(f).read_text())
        if body.get("hasResults") is False:
            return Path(f).stem
    raise RuntimeError("no hasResults=false fixture in tests/fixtures/ctgov")


NO_RESULTS = _find_no_results_fixture()


def _study(nct: str) -> dict:
    return json.loads((FIX / f"{nct}.json").read_text())


def _module_path() -> Path:
    env = os.environ.get("CT_ENRICH_PATH")
    return Path(env) if env else EPI_ROOT / "domains" / "clinicaltrials" / "enrich.py"


def _load_enrich(name: str = "_ct_enrich_under_test", path: Path | None = None):
    path = Path(path) if path else _module_path()
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def enrich(monkeypatch):
    mod = _load_enrich()
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)
    return mod


def _router(bodies: dict):
    """Build a requests.get side_effect keyed by NCT id."""

    def _get(url, *args, **kwargs):
        if not url.startswith(CTGOV_PREFIX):
            return MagicMock(status_code=404)
        nct = url[len(CTGOV_PREFIX):].split("?")[0]
        if nct not in bodies:
            return MagicMock(status_code=404)
        body = bodies[nct]
        if isinstance(body, Exception):
            raise body
        if body == "500":
            resp = MagicMock(status_code=500)
            resp.raise_for_status.side_effect = requests.HTTPError("500")
            return resp
        if body == "badjson":
            resp = MagicMock(status_code=200)
            resp.json.side_effect = ValueError("bad json")
            return resp
        resp = MagicMock(status_code=200)
        resp.json.return_value = copy.deepcopy(body)
        return resp

    return _get


def _write_graph(directory: Path, nct_ids, extra_nodes=(), extra_links=()):
    directory.mkdir(parents=True, exist_ok=True)
    nodes = [
        {"id": f"trial:{n.lower()}", "name": n, "entity_type": "Trial"} for n in nct_ids
    ]
    nodes.extend(extra_nodes)
    graph = {
        "metadata": {
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
        },
        "nodes": nodes,
        "links": list(extra_links),
    }
    (directory / "graph_data.json").write_text(json.dumps(graph, indent=2))
    return directory


def _ctgov_calls(m) -> int:
    return sum(
        1 for c in m.call_args_list
        if c.args and str(c.args[0]).startswith("https://clinicaltrials.gov")
    )


def _all_fixture_bodies() -> dict:
    return {n: _study(n) for n in (WITH_RESULTS_A, WITH_RESULTS_B, NO_RESULTS)}


def _read_nodes(directory: Path) -> dict:
    data = json.loads((directory / "graph_data.json").read_text())
    return {n["name"]: n for n in data["nodes"]}


def _run(enrich, directory: Path, bodies: dict, **kwargs):
    with patch.object(enrich.requests, "get", side_effect=_router(bodies)) as m:
        report = enrich.enrich_graph(directory, **kwargs)
    return report, m


def _stat_pct(stat) -> float:
    at_risk = stat["num_at_risk"]
    return stat["num_affected"] / at_risk * 100 if at_risk else 0.0



# --- Phase 7 helpers --------------------------------------------------------

TRIAL_A = f"trial:{WITH_RESULTS_A.lower()}"
TRIAL_B = f"trial:{WITH_RESULTS_B.lower()}"
COHORT_PLACEBO = "cohort:placebo"
COHORT_12 = "cohort:orforglipron_12mg"
COHORT_36 = "cohort:orforglipron_high_dose"
COMPOUND = "compound:orforglipron"
GROUP_TO_COHORT = {
    "Placebo": COHORT_PLACEBO,
    "12 mg Orforglipron": COHORT_12,
    "36 mg Orforglipron": COHORT_36,
}


def _link(src, rel, tgt, source_document="doc_seed", **attrs):
    key = f"{src}|{rel}|{tgt}"
    link = {
        "source": src,
        "target": tgt,
        "relation_type": rel,
        "relation_id": key,
        "canonical_key": key,
        "confidence": 0.9,
        "evidence": "seed",
        "source_document": source_document,
    }
    if attrs:
        link["attributes"] = attrs
    return link


def _seed_cohorts():
    def cohort(cid, name, **attrs):
        return {
            "id": cid, "name": name, "entity_type": "Cohort",
            "attributes": {"trial": WITH_RESULTS_A, **attrs},
            "source_documents": ["doc_seed"],
        }

    nodes = [
        cohort(COHORT_PLACEBO, "Placebo"),
        cohort(COHORT_12, "Orforglipron 12mg"),
        cohort(COHORT_36, "Orforglipron high dose", arm_label="36 mg Orforglipron"),
        {"id": COMPOUND, "name": "Orforglipron", "entity_type": "Compound",
         "source_documents": ["doc_seed"]},
    ]
    links = [_link(TRIAL_A, "enrolls", c) for c in (COHORT_PLACEBO, COHORT_12, COHORT_36)]
    links += [_link(c, "receives", COMPOUND) for c in (COHORT_12, COHORT_36)]
    return nodes, links


def _seeded_graph(directory: Path, extra_nodes=(), extra_links=()):
    nodes, links = _seed_cohorts()
    return _write_graph(
        directory, [WITH_RESULTS_A, WITH_RESULTS_B],
        [*nodes, *extra_nodes], [*links, *extra_links],
    )


def _read_graph(directory: Path):
    data = json.loads((directory / "graph_data.json").read_text())
    return {n["id"]: n for n in data["nodes"]}, data["links"]


def _edges(links, rel, src=None, tgt=None):
    return [
        l for l in links
        if l.get("relation_type") == rel
        and (src is None or l["source"] == src)
        and (tgt is None or l["target"] == tgt)
    ]


def _nattr(node, key, default=None):
    return (node.get("attributes") or {}).get(key, default)


def _eattr(link, key, default=None):
    # sift_kg flattens edge fields into the link dict, where "source" is the
    # endpoint; registry edge attributes therefore live in link["attributes"].
    return (link.get("attributes") or {}).get(key, default)


def _registry_nodes(nodes, entity_type=None):
    return [
        n for n in nodes.values()
        if _nattr(n, "source") == "ctgov_results"
        and (entity_type is None or n.get("entity_type") == entity_type)
    ]


def _parsed(enrich, nct):
    return enrich._parse_ct_results(_study(nct))


def _hba1c_outcome_nodes():
    node = {
        "id": "outcome:glycated_hemoglobin_hba1c", "name": "Glycated hemoglobin (HbA1c)",
        "entity_type": "Outcome", "source_documents": ["doc_seed"],
        "attributes": {"endpoint_type": "Primary", "timeframe": "Week 40"},
    }
    return [node], [_link(TRIAL_A, "has_outcome", node["id"])]


def _hba1c_analysis(enrich, other_group):
    return next(
        a for a in _parsed(enrich, WITH_RESULTS_A)["analyses"]
        if a["outcome_title"] == "Change From Baseline in HbA1c"
        and a["groups"][a["group_ids"][1]] == other_group
    )


def _extracted_ae_seed(enrich):
    """An extracted AE whose key equals that of a registry 'other' term."""
    res = _parsed(enrich, WITH_RESULTS_A)
    keys = [enrich._ae_key(a["term"]) for a in res["adverse_events"]]
    for ae in res["adverse_events"]:
        term = ae["term"]
        if ae["seriousness"] != "other" or keys.count(enrich._ae_key(term)) != 1:
            continue
        if term.lower().endswith("s"):
            continue
        for variant in (term.upper(), term.lower() + "s"):
            if enrich._ae_key(variant) == enrich._ae_key(term) and variant != term:
                node = {
                    "id": f"adverseevent:{enrich._slug(variant)}", "name": variant,
                    "entity_type": "AdverseEvent", "source_documents": ["doc_seed"],
                    "attributes": {"reported_term": "seeded wording", "n_affected": 999},
                }
                link = _link(TRIAL_A, "reports_adverse_event", node["id"], n_affected=999)
                total = sum(s["num_affected"] for s in ae["stats"])
                return ae, node, link, total
    raise AssertionError("no suitable AE term in fixture")


def _extracted_analysis_seed(enrich):
    ref = _hba1c_analysis(enrich, "36 mg Orforglipron")
    outcome_nodes, outcome_links = _hba1c_outcome_nodes()
    node = {
        "id": "outcomeanalysis:seed_hba1c_36", "name": "Seeded HbA1c analysis",
        "entity_type": "OutcomeAnalysis", "source_documents": ["doc_seed"],
        "attributes": {
            "effect_measure": ref["param_type"],
            "effect_estimate": round(float(ref["param_value"]), 1),
        },
    }
    links = [
        *outcome_links,
        _link(node["id"], "analyzes", outcome_nodes[0]["id"]),
        _link(node["id"], "compares", COHORT_36),
    ]
    return ref, [*outcome_nodes, node], links


def _fully_seeded(enrich, directory: Path):
    _, ae_node, ae_link, _ = _extracted_ae_seed(enrich)
    _, an_nodes, an_links = _extracted_analysis_seed(enrich)
    return _seeded_graph(directory, [ae_node, *an_nodes], [ae_link, *an_links])


def _seeded_run(enrich, directory: Path, **seed):
    _seeded_graph(directory, **seed)
    report, m = _run(enrich, directory, _all_fixture_bodies(), results=True)
    return report, m, *_read_graph(directory)



# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_parse_protocol_matches_legacy_fetch(enrich):
    study = _study(WITH_RESULTS_A)
    parsed = enrich._parse_ct_protocol(study)
    assert set(parsed) == {
        "ct_overall_status", "ct_phase", "ct_enrollment", "ct_start_date",
        "ct_completion_date", "ct_brief_title", "ct_allocation", "ct_masking",
    }
    with patch.object(enrich.requests, "get", side_effect=_router({WITH_RESULTS_A: study})):
        assert enrich._fetch_ct_gov(WITH_RESULTS_A) == parsed


@pytest.mark.unit
def test_single_fetch_per_trial_with_results(enrich, tmp_path):
    _write_graph(tmp_path, [WITH_RESULTS_A, WITH_RESULTS_B, NO_RESULTS])
    _, m = _run(enrich, tmp_path, _all_fixture_bodies(), results=True)
    assert _ctgov_calls(m) == 3
    nodes = _read_nodes(tmp_path)
    for nct in (WITH_RESULTS_A, WITH_RESULTS_B, NO_RESULTS):
        expected = enrich._parse_ct_protocol(_study(nct))
        for key, value in expected.items():
            assert nodes[nct].get(key) == value, (nct, key)


@pytest.mark.unit
def test_ae_floor_when_threshold_zero(enrich):
    res = enrich._parse_ct_results(_study(WITH_RESULTS_A))
    assert res["nct_id"] == WITH_RESULTS_A
    assert res["ae_threshold_pct"] == 5.0
    assert res["ae_threshold_source"] == "floor"
    assert [g["id"] for g in res["event_groups"]] == ["EG000", "EG001", "EG002", "EG003"]
    aes = res["adverse_events"]
    serious = [a for a in aes if a["seriousness"] == "serious"]
    other = [a for a in aes if a["seriousness"] == "other"]
    assert len(serious) == 29
    assert len(other) == 16
    for ae in other:
        assert any(_stat_pct(s) >= 5 for s in ae["stats"]), ae["term"]
    titles = {g["id"]: g["title"] for g in res["event_groups"]}
    for ae in aes:
        assert ae["term"] and ae["organ_system"]
        assert str(ae["source_vocabulary"]).startswith("MedDRA")
        assert ae["stats"]
        for s in ae["stats"]:
            assert s["group_title"] == titles[s["group_id"]]


@pytest.mark.unit
def test_registry_threshold_used_when_positive(enrich):
    res = enrich._parse_ct_results(_study(WITH_RESULTS_B))
    assert res["ae_threshold_pct"] == 5.0
    assert res["ae_threshold_source"] == "registry"
    assert sum(1 for a in res["adverse_events"] if a["seriousness"] == "serious") == 149
    assert sum(1 for a in res["adverse_events"] if a["seriousness"] == "other") == 23


@pytest.mark.unit
def test_analyses_primary_secondary_only(enrich):
    study = _study(WITH_RESULTS_A)
    res = enrich._parse_ct_results(study)
    analyses = res["analyses"]
    assert len(analyses) == 39
    assert {a["outcome_type"] for a in analyses} <= {"PRIMARY", "SECONDARY"}
    assert sum(1 for a in analyses if a["outcome_type"] == "PRIMARY") == 3
    assert any(a["p_value"] == "<.001" for a in analyses)
    for a in analyses:
        assert set(a["group_ids"]) <= set(a["groups"])

    mutated = copy.deepcopy(study)
    template = copy.deepcopy(
        mutated["resultsSection"]["outcomeMeasuresModule"]["outcomeMeasures"][0]
    )
    for extra_type in ("OTHER_PRE_SPECIFIED", "POST_HOC"):
        extra = copy.deepcopy(template)
        extra["type"] = extra_type
        extra["analyses"] = extra["analyses"][:1]
        mutated["resultsSection"]["outcomeMeasuresModule"]["outcomeMeasures"].append(extra)
    assert len(enrich._parse_ct_results(mutated)["analyses"]) == 39

    raw_b = _study(WITH_RESULTS_B)
    res_b = enrich._parse_ct_results(raw_b)
    assert len(res_b["analyses"]) == 4
    expected_p = [
        an.get("pValue")
        for om in raw_b["resultsSection"]["outcomeMeasuresModule"]["outcomeMeasures"]
        if om.get("type") in ("PRIMARY", "SECONDARY")
        for an in om.get("analyses") or []
    ]
    assert [a["p_value"] for a in res_b["analyses"]] == expected_p
    assert any(p in ("<.0001", "<0.0001") for p in expected_p)


@pytest.mark.unit
def test_no_results_trial_counted_and_skipped(enrich, tmp_path):
    assert enrich._parse_ct_results(_study(NO_RESULTS)) is None
    _write_graph(tmp_path, [NO_RESULTS])
    report, _ = _run(enrich, tmp_path, _all_fixture_bodies(), results=True)
    block = report["results"]
    assert block["trials_without_results"] == 1
    assert block["trials_with_results"] == 0
    assert block["results_failed"] == 0
    node = _read_nodes(tmp_path)[NO_RESULTS]
    assert node["ct_overall_status"] == _study(NO_RESULTS)["protocolSection"]["statusModule"]["overallStatus"]


@pytest.mark.unit
@pytest.mark.parametrize(
    "failure",
    [
        requests.exceptions.Timeout("t"),
        requests.exceptions.ConnectionError("down"),
        "500",
        "badjson",
    ],
    ids=["timeout", "connection", "http500", "badjson"],
)
def test_failure_paths_never_raise(enrich, tmp_path, failure):
    _write_graph(tmp_path, [WITH_RESULTS_A])
    report, _ = _run(enrich, tmp_path, {WITH_RESULTS_A: failure}, results=True)
    assert report["trials"]["failed"] == 1
    assert report["results"]["results_failed"] == 1
    assert report["results"]["trials_with_results"] == 0


@pytest.mark.unit
def test_malformed_results_section_counted(enrich, tmp_path):
    study = _study(WITH_RESULTS_A)
    study["resultsSection"]["adverseEventsModule"] = ["not", "a", "dict"]
    for om in study["resultsSection"]["outcomeMeasuresModule"]["outcomeMeasures"]:
        om["analyses"] = "not a list"
    _write_graph(tmp_path, [WITH_RESULTS_A])
    report, _ = _run(enrich, tmp_path, {WITH_RESULTS_A: study}, results=True)
    block = report["results"]
    assert block["results_failed"] + block["trials_with_results"] == 1
    assert report["trials"]["enriched"] == 1
    node = _read_nodes(tmp_path)[WITH_RESULTS_A]
    assert node["ct_overall_status"]


REPORT_KEYS = [
    "trials_with_results", "trials_without_results", "results_failed",
    "adverse_events_parsed", "analyses_parsed", "created", "merged", "merged_by_type",
    "created_nodes", "created_edges", "write_failed",
]


@pytest.mark.unit
def test_results_report_block(enrich, tmp_path):
    _write_graph(tmp_path, [WITH_RESULTS_A, WITH_RESULTS_B])
    report, _ = _run(enrich, tmp_path, _all_fixture_bodies(), results=True)
    block = report["results"]
    assert set(block) == set(REPORT_KEYS)
    assert block["trials_with_results"] == 2
    assert block["adverse_events_parsed"] == {"serious": 178, "other": 39}
    assert block["analyses_parsed"] == 43
    assert block["created"] > 0
    assert block["merged"] == 0
    written = json.loads((tmp_path / "extractions" / "_enrichment_report.json").read_text())
    assert written["results"] == block
    assert (
        block["trials_with_results"] + block["trials_without_results"] + block["results_failed"]
        == report["trials"]["total"] - report["trials"]["not_found"]
    )


@pytest.mark.unit
def test_results_graph_is_superset_with_provenance(enrich, tmp_path):
    ids = [WITH_RESULTS_A, WITH_RESULTS_B, NO_RESULTS]
    plain = _write_graph(tmp_path / "plain", ids)
    with_results = _write_graph(tmp_path / "res", ids)
    _run(enrich, plain, _all_fixture_bodies())
    _run(enrich, with_results, _all_fixture_bodies(), results=True)
    p_nodes, p_links = _read_graph(plain)
    r_nodes, r_links = _read_graph(with_results)
    for node_id, node in p_nodes.items():
        assert r_nodes.get(node_id) == node, node_id
    r_rel_ids = {l.get("relation_id") for l in r_links}
    assert {l.get("relation_id") for l in p_links} <= r_rel_ids
    extra_nodes = [n for i, n in r_nodes.items() if i not in p_nodes]
    assert extra_nodes
    for node in extra_nodes:
        assert _nattr(node, "source") == "ctgov_results", node["id"]
    plain_rel_ids = {l.get("relation_id") for l in p_links}
    extra_links = [l for l in r_links if l.get("relation_id") not in plain_rel_ids]
    assert extra_links
    for link in extra_links:
        assert _eattr(link, "source") == "ctgov_results", link["relation_id"]


@pytest.mark.unit
def test_no_flag_report_has_no_results_block(enrich, tmp_path):
    _write_graph(tmp_path, [WITH_RESULTS_A])
    report, _ = _run(enrich, tmp_path, _all_fixture_bodies())
    assert "results" not in report
    written = json.loads((tmp_path / "extractions" / "_enrichment_report.json").read_text())
    assert "results" not in written


@pytest.mark.unit
def test_cache_dir_roundtrip(enrich, tmp_path):
    cache = tmp_path / "cache"
    first = _write_graph(tmp_path / "g1", [WITH_RESULTS_A])
    _, m1 = _run(enrich, first, _all_fixture_bodies(), results=True, cache_dir=cache)
    assert _ctgov_calls(m1) == 1
    cached = cache / f"{WITH_RESULTS_A}.json"
    assert cached.exists()
    assert json.loads(cached.read_text()) == _study(WITH_RESULTS_A)

    second = _write_graph(tmp_path / "g2", [WITH_RESULTS_A])
    offline = {WITH_RESULTS_A: requests.exceptions.ConnectionError("down")}
    report, m2 = _run(enrich, second, offline, results=True, cache_dir=cache)
    assert _ctgov_calls(m2) == 0
    assert report["trials"]["enriched"] == 1
    assert report["results"]["trials_with_results"] == 1

    cached.write_text("{not json")
    third = _write_graph(tmp_path / "g3", [WITH_RESULTS_A])
    report, m3 = _run(enrich, third, _all_fixture_bodies(), results=True, cache_dir=cache)
    assert _ctgov_calls(m3) == 1
    assert report["trials"]["enriched"] == 1

    blocker = tmp_path / "not_a_dir"
    blocker.write_text("x")
    fourth = _write_graph(tmp_path / "g4", [WITH_RESULTS_A])
    report, _ = _run(enrich, fourth, _all_fixture_bodies(), results=True, cache_dir=blocker)
    assert report["trials"]["enriched"] == 1


def _normalize_stamps(raw: bytes) -> bytes:
    # sift_kg stamps created_at/updated_at at load/save time; those two values
    # are the only normalization applied before the byte comparison.
    return re.sub(
        rb'"(created_at|updated_at)": "[^"]*"', rb'"\1": "<stamp>"', raw
    )


def _same_key_order(a, b) -> bool:
    if isinstance(a, dict) and isinstance(b, dict):
        return list(a) == list(b) and all(_same_key_order(a[k], b[k]) for k in a)
    return True


@pytest.mark.unit
def test_byte_identical_to_v340_without_flag(enrich, tmp_path, monkeypatch):
    old_path = tmp_path / "enrich_v340.py"
    old_path.write_bytes(_baseline_enrich_source(OLD_COMMIT))
    old = _load_enrich("_ct_enrich_v340", old_path)
    monkeypatch.setattr(old.time, "sleep", lambda s: None)

    extras = [
        {"id": "trial:noid", "name": "Some trial without id", "entity_type": "Trial"},
        {"id": "compound:x", "name": "Orforglipron", "entity_type": "Compound"},
    ]
    ids = [WITH_RESULTS_A, WITH_RESULTS_B, NO_RESULTS]
    d_old = _write_graph(tmp_path / "old", ids, extras)
    d_new = _write_graph(tmp_path / "new", ids, extras)
    bodies = _all_fixture_bodies()

    with patch.object(old.requests, "get", side_effect=_router(bodies)) as m_old:
        rep_old = old.enrich_graph(d_old)
    with patch.object(enrich.requests, "get", side_effect=_router(bodies)) as m_new:
        rep_new = enrich.enrich_graph(d_new)

    g_old = (d_old / "graph_data.json").read_bytes()
    g_new = (d_new / "graph_data.json").read_bytes()
    if g_old != g_new:
        g_old, g_new = _normalize_stamps(g_old), _normalize_stamps(g_new)
    assert g_old == g_new

    rep_old.pop("generated_at")
    rep_new.pop("generated_at")
    assert rep_old == rep_new
    assert _same_key_order(rep_old, rep_new)
    assert list(rep_old) == list(rep_new)
    assert "results" not in rep_new
    assert m_old.call_count == m_new.call_count


@pytest.mark.unit
def test_cli_help_mentions_flags():
    proc = subprocess.run(
        [sys.executable, str(_module_path()), "--help"],
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0
    assert "--results" in proc.stdout
    assert "not yet written" not in proc.stdout
    assert "--cache-dir" in proc.stdout
    assert "--refresh-results" in proc.stdout
    assert "--cache-ttl-days" in proc.stdout


# --- Phase 7: pure helpers --------------------------------------------------


@pytest.mark.unit
def test_slug(enrich):
    assert enrich._slug("Semaglutide 0.5 mg") == "semaglutide_0_5_mg"
    assert enrich._slug("  Regression, Logistic ") == "regression_logistic"


@pytest.mark.unit
@pytest.mark.parametrize(
    "text,expected",
    [
        ("<.001", (0.001, "<")),
        ("0.0017", (0.0017, "=")),
        ("=0.03", (0.03, "=")),
        ("<=0.05", (0.05, "<")),
        ("≤0.05", (0.05, "<")),
        (">0.99", (0.99, ">")),
        (">=0.99", (0.99, ">")),
        ("≥0.99", (0.99, ">")),
        ("NA", (None, None)),
        ("", (None, None)),
        (None, (None, None)),
        ("n/a", (None, None)),
        ("ns", (None, None)),
    ],
)
def test_parse_p_value(enrich, text, expected):
    assert enrich._parse_p_value(text) == expected


@pytest.mark.unit
def test_match_cohort(enrich):
    m = enrich._match_cohort
    assert m("12 mg Orforglipron", [("c1", "Orforglipron 12mg", None)]) == "c1"
    assert m("3 mg Orforglipron", [("c1", "36 mg Orforglipron", None)]) is None
    assert m("Placebo", [("c1", "Semaglutide placebo 0.5 mg", None)]) is None
    assert m(
        "12 mg Orforglipron",
        [("c1", "Orforglipron 12mg", None), ("c2", "12 mg orforglipron QW", None)],
    ) is None
    assert m("12 mg Orforglipron", [("c1", "High cohort", "12 mg Orforglipron")]) == "c1"
    assert m("Placebo", [("c1", "Placebo", None), ("c2", "Orforglipron 12mg", None)]) == "c1"


@pytest.mark.unit
def test_ae_key_and_normalize_measure(enrich):
    assert enrich._ae_key("Diarrhoeas") == enrich._ae_key("diarrhea")
    assert enrich.normalize_measure("Change From Baseline in HbA1c") == enrich.normalize_measure(
        "Glycated hemoglobin (HbA1c)"
    )


@pytest.mark.unit
def test_ae_key_does_not_overstrip_oe(enrich):
    assert enrich._ae_key("Toe pain") != enrich._ae_key("Te pain")
    assert enrich._ae_key("toe").endswith("toe")
    for british, us in [
        ("Diarrhoea", "diarrhea"), ("Oedema", "edema"),
        ("Oesophagitis", "esophagitis"), ("Dyspnoea", "dyspnea"),
    ]:
        assert enrich._ae_key(british) == enrich._ae_key(us)


# British MedDRA preferred terms and their US spellings. Every pair here was one
# key under the pre-iteration-16 "oe -> e" rule; narrowing a rule must never
# split one of them again (09-REVIEW CR-01).
_BRITISH_US_AE_PAIRS = [
    ("Tachypnoea", "Tachypnea"), ("Orthopnoea", "Orthopnea"), ("Hypopnoea", "Hypopnea"),
    ("Bradypnoea", "Bradypnea"), ("Hyperpnoea", "Hyperpnea"), ("Dyspnoea exertional", "Dyspnea exertional"),
    ("Sleep apnoea syndrome", "Sleep apnea syndrome"), ("Amoebiasis", "Amebiasis"),
    ("Amoebic dysentery", "Amebic dysentery"), ("Diarrhoea", "Diarrhea"), ("Gonorrhoea", "Gonorrhea"),
    ("Amenorrhoea", "Amenorrhea"), ("Rhinorrhoea", "Rhinorrhea"), ("Oedema peripheral", "Edema peripheral"),
    ("Oesophagitis", "Esophagitis"), ("Oestradiol increased", "Estradiol increased"),
    ("Foetal distress syndrome", "Fetal distress syndrome"), ("Coeliac disease", "Celiac disease"),
    ("Anaemia", "Anemia"), ("Haemorrhage", "Hemorrhage"), ("Tumour pain", "Tumor pain"),
    # 999.5 / clinicaltrials iteration 23
    ("Paraesthesia", "Paresthesia"), ("Hypoaesthesia", "Hypoesthesia"), ("Anaesthesia", "Anesthesia"),
    ("Faecal incontinence", "Fecal incontinence"), ("Gynaecomastia", "Gynecomastia"),
    ("Leucopenia", "Leukopenia"), ("Leucocytosis", "Leukocytosis"),
    ("Hypooestrogenism", "Hypoestrogenism"), ("Hyperoestrogenism", "Hyperestrogenism"),
    ("Angio-oedema", "Angioedema"), ("Lymphoedema", "Lymphedema"),
    # 999.5 review fix / clinicaltrials iteration 24
    ("Anaesthetic complication", "Anesthetic complication"),
    ("Local anaesthetic systemic toxicity", "Local anesthetic systemic toxicity"),
    ("Ethinyloestradiol", "Ethinylestradiol"), ("Xenooestrogen", "Xenoestrogen"),
    ("Prooestrus", "Proestrus"),
    # 999.5 round-2 review fix / clinicaltrials iteration 25
    ("Diethylstilboestrol", "Diethylstilbestrol"), ("Stilboestrol", "Stilbestrol"),
    ("Antioestrogen", "Antiestrogen"), ("Fosfoestrol", "Fosfestrol"), ("Hexoestrol", "Hexestrol"),
    ("Dienoestrol", "Dienestrol"), ("Polyoestradiol", "Polyestradiol"), ("Dioestrus", "Diestrus"),
    ("Anoestrus", "Anestrus"), ("Metoestrus", "Metestrus"), ("Oestradiol", "Estradiol"),
    ("Anaesthetic", "Anesthetic"), ("Anaesthetist", "Anesthetist"),
    ("Hyperaesthesia", "Hyperesthesia"), ("Leucoencephalopathy", "Leukoencephalopathy"),
    ("Leucoderma", "Leukoderma"),
    # 999.5 round-3 review fix / clinicaltrials iteration 26
    ("Mycooestrogen", "Mycoestrogen"), ("Metallooestrogen", "Metalloestrogen"),
    ("Neurooestradiol", "Neuroestradiol"), ("Pseudooestrus", "Pseudoestrus"),
    ("Zoooestrogen", "Zooestrogen"), ("Aesthesioneuroblastoma", "Esthesioneuroblastoma"),
    ("Hypo-aesthesia", "Hypo-esthesia"),
]


@pytest.mark.unit
@pytest.mark.parametrize("british,us", _BRITISH_US_AE_PAIRS)
def test_ae_key_merges_british_meddra_terms(enrich, british, us):
    assert enrich._ae_key(british) == enrich._ae_key(us)


@pytest.mark.unit
def test_ae_key_pnoea_rule_keeps_toe(enrich):
    assert enrich._ae_key("Toe pain") == "toe pain"
    assert enrich._ae_key("Ingrown toenail") == "ingrown toenail"


@pytest.mark.unit
def test_ae_key_leaves_us_o_prefix_compounds(enrich):
    assert enrich._ae_key("Angioedema") == "angioedema"
    assert enrich._ae_key("Hypoestrogenism") == "hypoestrogenism"
    assert enrich._ae_key("Phytoestrogen") == "phytoestrogen"
    assert enrich._ae_key("Toe pain") == "toe pain"
    assert "leuk" not in enrich._ae_key("Leucine aminopeptidase increased")


@pytest.mark.unit
def test_ae_key_iteration24_word_table(enrich):
    """999.5 review fix (iteration 24): aesthe covers anaesthetic; oestr folds only
    where British spelling puts it; Leucovorin is left alone; earlier negatives hold."""
    expected = {
        "Anaesthetic complication": "anesthetic complication",
        "Xenoestrogen": "xenoestrogen",
        "Proestrus": "proestru",
        "Leucovorin toxicity": "leucovorin toxicity",
        "Toe pain": "toe pain",
        "Dyspnoea": "dyspnea",
        "Amoeba": "ameba",
        "Leucine": "leucine",
        "Angioedema": "angioedema",
        "Hypoestrogenism": "hypoestrogenism",
        "Phytoestrogen": "phytoestrogen",
    }
    for word, key in expected.items():
        assert enrich._ae_key(word) == key, word


@pytest.mark.unit
def test_ae_key_iteration25_word_table(enrich):
    """999.5 round-2 review fix (iteration 25): oestr folds everywhere except after
    the US o-prefixes hyp/phyt/xen/pr; aesthe needs a preceding letter, so the US
    word "aesthetic" is left alone; Leuconostoc (a genus) is not folded."""
    expected = {
        "Diethylstilboestrol": "diethylstilbestrol",
        "Antioestrogen therapy": "antiestrogen therapy",
        "Dioestrus": "diestru",
        "Hypooestrogenism": "hypoestrogenism",
        "Hypoestrogenism": "hypoestrogenism",
        "Phytoestrogen": "phytoestrogen",
        "Xenoestrogen": "xenoestrogen",
        "Proestrus": "proestru",
        "Anaesthesia": "anesthesia",
        "Hyperaesthesia": "hyperesthesia",
        "Aesthetic procedure complication": "aesthetic procedure complication",
        "Leucoencephalopathy": "leukoencephalopathy",
        "Leuconostoc infection": "leuconostoc infection",
        "Leucine": "leucine",
        "Leucovorin toxicity": "leucovorin toxicity",
    }
    for word, key in expected.items():
        assert enrich._ae_key(word) == key, word


@pytest.mark.unit
def test_ae_key_iteration26_word_table(enrich):
    """999.5 round-3 review fix (iteration 26): the oestr denylist also covers the
    US o-prefixes myc/metall/neur/pseud/zo (best-effort list); aesthes folds
    everywhere (Aesthesioneuroblastoma, Hypo-aesthesia) while aesthet still needs
    a preceding letter, so the US word "aesthetic" keeps its key."""
    expected = {
        "Mycoestrogen": "mycoestrogen",
        "Mycooestrogen": "mycoestrogen",
        "Metalloestrogen": "metalloestrogen",
        "Neuroestradiol": "neuroestradiol",
        "Neurooestradiol": "neuroestradiol",
        "Pseudoestrus": "pseudoestru",
        "Zooestrogen": "zooestrogen",
        "Zoooestrogen": "zooestrogen",
        "Hypooestrogenism": "hypoestrogenism",
        "Diethylstilboestrol": "diethylstilbestrol",
        "Fosfoestrol": "fosfestrol",
        "Aesthesioneuroblastoma": "esthesioneuroblastoma",
        "Hypo-aesthesia": "hypo esthesia",
        "Paraesthesia": "paresthesia",
        "Anaesthetic": "anesthetic",
        "Aesthetic": "aesthetic",
        "Aesthetic procedure complication": "aesthetic procedure complication",
    }
    for word, key in expected.items():
        assert enrich._ae_key(word) == key, word


# --- Phase 7: registry adverse events ---------------------------------------


@pytest.mark.unit
def test_registry_ae_threshold_floor(enrich, tmp_path):
    _, _, nodes, _ = _seeded_run(enrich, tmp_path)
    got = {
        enrich._ae_key(n["name"])
        for n in nodes.values()
        if n.get("entity_type") == "AdverseEvent"
        and WITH_RESULTS_A in (_nattr(n, "ctgov_nct_ids") or [])
    }
    parsed = _parsed(enrich, WITH_RESULTS_A)["adverse_events"]
    assert got == {enrich._ae_key(a["term"]) for a in parsed}

    module = _study(WITH_RESULTS_A)["resultsSection"]["adverseEventsModule"]
    kept = {enrich._ae_key(a["term"]) for a in parsed}
    below = [
        ev["term"] for ev in module["otherEvents"]
        if all(
            (s["numAffected"] / s["numAtRisk"] * 100 if s["numAtRisk"] else 0) < 5
            for s in ev["stats"]
        )
    ]
    assert below
    serious_keys = {enrich._ae_key(e["term"]) for e in module["seriousEvents"]}
    for term in below:
        if enrich._ae_key(term) not in serious_keys:
            assert enrich._ae_key(term) not in got, term


@pytest.mark.unit
def test_meddra_attribute_rules(enrich, tmp_path):
    _, _, nodes, _ = _seeded_run(enrich, tmp_path / "meddra")
    aes = [n for n in _registry_nodes(nodes, "AdverseEvent")
           if WITH_RESULTS_A in _nattr(n, "ctgov_nct_ids", [])]
    assert aes
    for n in aes:
        assert _nattr(n, "reported_term") == n["name"]
        assert _nattr(n, "meddra_pt") == n["name"]
        # One node serves every trial that reports the event. A node shared with
        # a trial on another MedDRA release keeps the first release and records
        # this one as registry_meddra_version.
        assert "27.1" in (
            _nattr(n, "meddra_version"), _nattr(n, "registry_meddra_version")
        ), n["id"]
        if _nattr(n, "ctgov_nct_ids") == [WITH_RESULTS_A]:
            assert _nattr(n, "meddra_version") == "27.1"

    study = _study(WITH_RESULTS_A)
    module = study["resultsSection"]["adverseEventsModule"]
    for key in ("seriousEvents", "otherEvents"):
        for ev in module[key]:
            ev["sourceVocabulary"] = "Custom dictionary"
    _write_graph(tmp_path / "custom", [WITH_RESULTS_A])
    _run(enrich, tmp_path / "custom", {WITH_RESULTS_A: study}, results=True)
    custom_nodes, _ = _read_graph(tmp_path / "custom")
    custom = _registry_nodes(custom_nodes, "AdverseEvent")
    assert custom
    for n in custom:
        assert _nattr(n, "reported_term")
        assert "meddra_pt" not in (n.get("attributes") or {})
        assert "meddra_version" not in (n.get("attributes") or {})
    assert "meddra_dictionary" not in _module_path().read_text()


@pytest.mark.unit
def test_ae_links(enrich, tmp_path):
    _, _, nodes, links = _seeded_run(enrich, tmp_path)
    parsed = _parsed(enrich, WITH_RESULTS_A)
    titles = {g["title"] for g in parsed["event_groups"]}
    by_key = {}
    for a in parsed["adverse_events"]:
        by_key.setdefault(enrich._ae_key(a["term"]), []).append(a)
    checked = 0
    for node in _registry_nodes(nodes, "AdverseEvent"):
        key = enrich._ae_key(node["name"])
        if WITH_RESULTS_A not in _nattr(node, "ctgov_nct_ids", []) or len(by_key.get(key, [])) != 1:
            continue
        record = by_key[key][0]
        organ = f"organsystem:{enrich._slug(record['organ_system'])}"
        assert organ in nodes
        assert _nattr(nodes[organ], "classification") == "system organ class"
        assert _edges(links, "affects_organ_system", node["id"], organ)
        reports = _edges(links, "reports_adverse_event", TRIAL_A, node["id"])
        assert len(reports) == 1
        edge = reports[0]
        assert _eattr(edge, "seriousness") == record["seriousness"]
        assert _eattr(edge, "assessment_type") == record["assessment_type"]
        assert _eattr(edge, "n_affected") == sum(s["num_affected"] for s in record["stats"])
        assert _eattr(edge, "n_at_risk") == sum(s["num_at_risk"] for s in record["stats"])
        assert _eattr(edge, "frequency_threshold") == 5.0
        assert set(_eattr(edge, "by_group")) == titles
        assert edge["source_document"] == f"ctgov:{WITH_RESULTS_A}"
        assert edge["evidence"].startswith(f"ClinicalTrials.gov results {WITH_RESULTS_A}:")
        checked += 1
    assert checked > 10


@pytest.mark.unit
def test_group_to_arm_mapping(enrich, tmp_path):
    _seeded_graph(tmp_path)
    before, _ = _read_graph(tmp_path)
    cohorts_before = {i for i, n in before.items() if n.get("entity_type") == "Cohort"}
    _run(enrich, tmp_path, _all_fixture_bodies(), results=True)
    nodes, links = _read_graph(tmp_path)
    assert {i for i, n in nodes.items() if n.get("entity_type") == "Cohort"} == cohorts_before

    parsed = _parsed(enrich, WITH_RESULTS_A)
    by_key = {}
    for a in parsed["adverse_events"]:
        by_key.setdefault(enrich._ae_key(a["term"]), []).append(a)
    observed = [
        l for l in _edges(links, "observed_in")
        if l.get("source_document") == f"ctgov:{WITH_RESULTS_A}"
    ]
    assert observed
    assert {l["target"] for l in observed} <= set(GROUP_TO_COHORT.values())
    for link in observed:
        record = by_key.get(enrich._ae_key(nodes[link["source"]]["name"]), [None])
        if len(record) != 1 or record[0] is None:
            continue
        stat = next(
            s for s in record[0]["stats"]
            if GROUP_TO_COHORT.get(s["group_title"]) == link["target"]
        )
        assert _eattr(link, "n_affected") == stat["num_affected"]
        assert _eattr(link, "n_at_risk") == stat["num_at_risk"]
        assert _eattr(link, "n_events") == stat["num_events"]
        assert _eattr(link, "percent") == round(
            stat["num_affected"] / stat["num_at_risk"] * 100, 2
        )
    unmatched_checked = 0
    for edge in _edges(links, "reports_adverse_event", TRIAL_A):
        if _eattr(edge, "by_group") and "3 mg Orforglipron" in _eattr(edge, "by_group"):
            entry = _eattr(edge, "by_group")["3 mg Orforglipron"]
            assert entry["cohort"] is None
            assert "n_affected" in entry
            assert _eattr(edge, "by_group")["Placebo"]["cohort"] == COHORT_PLACEBO
            unmatched_checked += 1
    assert unmatched_checked > 0

    other = [
        l for l in links
        if l.get("source_document") == f"ctgov:{WITH_RESULTS_B}"
        and l["relation_type"] in ("observed_in", "compares")
    ]
    assert other == []


@pytest.mark.unit
def test_provenance_on_created(enrich, tmp_path):
    _, _, nodes, links = _seeded_run(enrich, tmp_path)
    created = _registry_nodes(nodes)
    assert created
    for n in created:
        assert _nattr(n, "ctgov_nct_ids")
        assert any(str(d).startswith("ctgov:") for d in n.get("source_documents", []))
    ctgov_edges = [l for l in links if str(l.get("source_document", "")).startswith("ctgov:")]
    assert ctgov_edges
    for l in ctgov_edges:
        assert _eattr(l, "source") == "ctgov_results" or "ctgov_results" in (
            _eattr(l, "sources") or []
        ), l["relation_id"]
        assert _eattr(l, "ctgov_nct_ids")


# --- Phase 7: outcome analyses ----------------------------------------------


def _oa_nodes(nodes, nct=None):
    out = [n for n in _registry_nodes(nodes, "OutcomeAnalysis")]
    if nct:
        out = [n for n in out if nct in _nattr(n, "ctgov_nct_ids", [])]
    return out


@pytest.mark.unit
def test_analysis_attributes(enrich, tmp_path):
    _, _, nodes, links = _seeded_run(enrich, tmp_path)
    ref = _hba1c_analysis(enrich, "3 mg Orforglipron")
    study = _study(WITH_RESULTS_A)
    measure = next(
        om for om in study["resultsSection"]["outcomeMeasuresModule"]["outcomeMeasures"]
        if om["title"] == "Change From Baseline in HbA1c"
    )
    name = (
        f"{WITH_RESULTS_A}: Change From Baseline in HbA1c — "
        "Placebo vs 3 mg Orforglipron"
    )
    by_name = {n["name"]: n for n in nodes.values()}
    node = by_name[name]
    attrs = node["attributes"]
    assert node["entity_type"] == "OutcomeAnalysis"
    assert attrs["p_value"] == "<.001"
    assert attrs["p_value_num"] == 0.001
    assert attrs["p_value_qualifier"] == "<"
    assert attrs["effect_estimate"] == -1.12
    assert attrs["effect_measure"] == ref["param_type"]
    assert attrs["ci_lower"] == -1.43
    assert attrs["ci_upper"] == -0.8
    assert attrs["ci_level"] == 95 and isinstance(attrs["ci_level"], int)
    assert attrs["ci_sides"] == "TWO_SIDED"
    assert attrs["endpoint_type"] == "primary"
    assert attrs["non_inferiority_type"] == "SUPERIORITY"
    assert attrs["timepoint"] == measure["timeFrame"]
    assert attrs["unit"] == measure["unitOfMeasure"]
    assert attrs["compared_groups"] == ["Placebo", "3 mg Orforglipron"]
    assert attrs["unmatched_groups"] == ["3 mg Orforglipron"]
    assert all(v is not None for v in attrs.values())
    assert [l["target"] for l in _edges(links, "compares", node["id"])] == [COHORT_PLACEBO]
    uses = _edges(links, "uses_method", node["id"])
    assert [l["target"] for l in uses] == ["statisticalmethod:mixed_models_analysis"]
    analyzes = _edges(links, "analyzes", node["id"])
    assert len(analyzes) == 1
    assert _edges(links, "has_outcome", TRIAL_A, analyzes[0]["target"])
    assert len(_oa_nodes(nodes, WITH_RESULTS_A)) == len(
        _parsed(enrich, WITH_RESULTS_A)["analyses"]
    ) == 39


@pytest.mark.unit
def test_assesses_effect_of(enrich, tmp_path):
    _, _, nodes, links = _seeded_run(enrich, tmp_path)
    by_name = {n["name"]: n for n in nodes.values()}
    both = by_name[
        f"{WITH_RESULTS_A}: Change From Baseline in HbA1c — Placebo vs 12 mg Orforglipron"
    ]
    effect = _edges(links, "assesses_effect_of", both["id"])
    assert [l["target"] for l in effect] == [COMPOUND]
    none = by_name[
        f"{WITH_RESULTS_A}: Change From Baseline in HbA1c — Placebo vs 3 mg Orforglipron"
    ]
    assert _edges(links, "assesses_effect_of", none["id"]) == []


@pytest.mark.unit
def test_other_and_post_hoc_excluded(enrich, tmp_path):
    study = _study(WITH_RESULTS_A)
    measures = study["resultsSection"]["outcomeMeasuresModule"]["outcomeMeasures"]
    extra_titles = []
    for kind in ("OTHER_PRE_SPECIFIED", "POST_HOC"):
        extra = copy.deepcopy(measures[0])
        extra["type"] = kind
        extra["title"] = f"Zzdistinct {kind.lower()} measure"
        extra_titles.append(extra["title"])
        measures.append(extra)
    _write_graph(tmp_path, [WITH_RESULTS_A])
    _run(enrich, tmp_path, {WITH_RESULTS_A: study}, results=True)
    nodes, _ = _read_graph(tmp_path)
    for n in nodes.values():
        if n.get("entity_type") in ("OutcomeAnalysis", "Outcome"):
            assert not any(t in n["name"] for t in extra_titles), n["name"]
    assert len(_oa_nodes(nodes, WITH_RESULTS_A)) == 39


@pytest.mark.unit
def test_statistical_method_shared(enrich, tmp_path):
    _, _, nodes, links = _seeded_run(enrich, tmp_path)
    methods = {
        enrich._slug(a["statistical_method"])
        for nct in (WITH_RESULTS_A, WITH_RESULTS_B)
        for a in _parsed(enrich, nct)["analyses"]
        if a.get("statistical_method")
    }
    method_nodes = [n for n in nodes.values() if n.get("entity_type") == "StatisticalMethod"]
    assert {n["id"] for n in method_nodes} == {f"statisticalmethod:{m}" for m in methods}
    ancova = "statisticalmethod:ancova"
    sources = {nodes[l["source"]]["name"].split(":")[0] for l in _edges(links, "uses_method", tgt=ancova)}
    assert sources == {WITH_RESULTS_A, WITH_RESULTS_B}
    assert set(_nattr(nodes[ancova], "ctgov_nct_ids")) == {WITH_RESULTS_A, WITH_RESULTS_B}


@pytest.mark.unit
def test_outcome_match_or_create(enrich, tmp_path):
    outcome_nodes, outcome_links = _hba1c_outcome_nodes()
    seeded_id = outcome_nodes[0]["id"]
    _, _, nodes, links = _seeded_run(
        enrich, tmp_path, extra_nodes=outcome_nodes, extra_links=outcome_links
    )
    hba1c = [
        n for n in _oa_nodes(nodes, WITH_RESULTS_A)
        if " Change From Baseline in HbA1c — " in n["name"]
    ]
    assert len(hba1c) == 3
    for oa in hba1c:
        assert [l["target"] for l in _edges(links, "analyzes", oa["id"])] == [seeded_id]
    assert not any(n["name"] == "Change From Baseline in HbA1c" for n in nodes.values())
    assert nodes[seeded_id]["attributes"]["timeframe"] == "Week 40"

    analyses = _parsed(enrich, WITH_RESULTS_A)["analyses"]
    other = next(
        a for a in analyses
        if a["outcome_title"] == "Change From Baseline in Systolic Blood Pressure (SBP)"
    )
    oid = f"outcome:{enrich._slug(other['outcome_title'])}"
    created = nodes[oid]
    attrs = created["attributes"]
    assert created["name"] == other["outcome_title"]
    assert attrs["endpoint_type"] == other["outcome_type"].capitalize() == "Secondary"
    assert attrs["timeframe"] == other["time_frame"]
    assert "time_frame" not in attrs
    assert attrs["unit"] == other["unit"]
    assert attrs["source"] == "ctgov_results"
    assert _edges(links, "has_outcome", TRIAL_A, oid)


@pytest.mark.unit
def test_ae_merge_with_extracted(enrich, tmp_path):
    ae, node, link, total = _extracted_ae_seed(enrich)
    report, _, nodes, links = _seeded_run(
        enrich, tmp_path, extra_nodes=[node], extra_links=[link]
    )
    key = enrich._ae_key(ae["term"])
    same = [n for n in nodes.values()
            if n.get("entity_type") == "AdverseEvent" and enrich._ae_key(n["name"]) == key]
    assert len(same) == 1
    merged = same[0]
    assert merged["name"] == node["name"]
    attrs = merged["attributes"]
    assert attrs["reported_term"] == "seeded wording"
    assert attrs["registry_term"] == ae["term"]
    assert attrs["meddra_pt"] == ae["term"]
    assert "ctgov_results" in attrs["sources"]
    assert attrs["ctgov_nct_ids"] == [WITH_RESULTS_A]
    assert merged["source_documents"] == ["doc_seed"]
    edge = _edges(links, "reports_adverse_event", TRIAL_A, merged["id"])
    assert len(edge) == 1
    assert _eattr(edge[0], "n_affected") == 999
    assert _eattr(edge[0], "registry_n_affected") == total
    assert report["results"]["merged"] >= 1


@pytest.mark.unit
def test_analysis_merge(enrich, tmp_path):
    ref, nodes_seed, links_seed = _extracted_analysis_seed(enrich)
    seed_id = "outcomeanalysis:seed_hba1c_36"
    report, _, nodes, links = _seeded_run(
        enrich, tmp_path, extra_nodes=nodes_seed, extra_links=links_seed
    )
    dup_name = f"{WITH_RESULTS_A}: Change From Baseline in HbA1c — Placebo vs 36 mg Orforglipron"
    assert not [n for n in _registry_nodes(nodes, "OutcomeAnalysis") if n["name"] == dup_name]
    attrs = nodes[seed_id]["attributes"]
    assert nodes[seed_id]["name"] == "Seeded HbA1c analysis"
    # SA-04: the seed has no p-value field, so the p-value group fills whole.
    assert attrs["p_value"] == ref["p_value"]
    assert attrs["p_value_num"] == 0.001
    assert attrs["p_value_qualifier"] == "<"
    # It has an effect estimate, so the registry CI is recorded, not filled.
    assert "ci_lower" not in attrs and "ci_upper" not in attrs
    assert attrs["registry_ci_lower"] == float(ref["ci_lower_limit"])
    assert attrs["registry_ci_upper"] == float(ref["ci_upper_limit"])
    assert attrs["effect_estimate"] == round(float(ref["param_value"]), 1)
    if float(ref["param_value"]) != attrs["effect_estimate"]:
        assert attrs["registry_effect_estimate"] == float(ref["param_value"])
    assert attrs["ctgov_analysis_ids"] == [f"outcomeanalysis:{enrich._slug(dup_name)}"]
    assert report["results"]["merged"] >= 1
    assert len(_oa_nodes(nodes, WITH_RESULTS_A)) == 38


# --- Phase 7: idempotence, report, dedupe, fallback -------------------------


@pytest.mark.unit
def test_idempotent_second_run(enrich, tmp_path):
    _fully_seeded(enrich, tmp_path)
    _run(enrich, tmp_path, _all_fixture_bodies(), results=True)
    first = (tmp_path / "graph_data.json").read_bytes()
    n1, l1 = _read_graph(tmp_path)
    report, _ = _run(enrich, tmp_path, _all_fixture_bodies(), results=True)
    second = (tmp_path / "graph_data.json").read_bytes()
    n2, l2 = _read_graph(tmp_path)
    assert len(n1) == len(n2) and len(l1) == len(l2)
    assert _normalize_stamps(first) == _normalize_stamps(second)
    assert report["results"]["created"] == 0
    assert report["results"]["merged"] == 0
    m1 = {l["relation_id"]: len(l.get("mentions", [])) for l in l1}
    m2 = {l["relation_id"]: len(l.get("mentions", [])) for l in l2}
    assert m1 == m2


@pytest.mark.unit
def test_report_created_merged_counts(enrich, tmp_path):
    _fully_seeded(enrich, tmp_path)
    report, _ = _run(enrich, tmp_path, _all_fixture_bodies(), results=True)
    block = report["results"]
    nodes, links = _read_graph(tmp_path)
    assert list(block) == REPORT_KEYS
    assert block["created"] == block["created_nodes"] + block["created_edges"]
    assert block["created_nodes"] == len(_registry_nodes(nodes))
    assert block["created_edges"] == sum(1 for l in links if _eattr(l, "source") == "ctgov_results")
    gained = [
        n for n in nodes.values()
        if n.get("entity_type") in ("AdverseEvent", "OutcomeAnalysis")
        and _nattr(n, "source") != "ctgov_results"
        and "ctgov_results" in (_nattr(n, "sources") or [])
    ]
    assert len(gained) == 2
    by_type = block["merged_by_type"]
    assert list(by_type) == ["AdverseEvent", "OutcomeAnalysis", "Outcome"]
    assert by_type["AdverseEvent"] + by_type["OutcomeAnalysis"] == sum(
        len(_nattr(n, "ctgov_nct_ids", [])) for n in gained
    )
    assert block["merged"] == sum(by_type.values())
    assert block["write_failed"] == 0


@pytest.mark.unit
def test_duplicate_nct_trial_nodes(enrich, tmp_path):
    single = _write_graph(tmp_path / "single", [WITH_RESULTS_A])
    single_report, _ = _run(enrich, single, _all_fixture_bodies(), results=True)

    dup_node = {"id": "trial:achieve_1", "name": f"ACHIEVE-1 ({WITH_RESULTS_A})",
                "entity_type": "Trial"}
    dup = _write_graph(tmp_path / "dup", [WITH_RESULTS_A], [dup_node])
    report, m = _run(enrich, dup, _all_fixture_bodies(), results=True)
    assert _ctgov_calls(m) == 1
    block = report["results"]
    assert block["trials_with_results"] == 1
    assert block["adverse_events_parsed"] == single_report["results"]["adverse_events_parsed"]
    assert block["analyses_parsed"] == single_report["results"]["analyses_parsed"]
    nodes, links = _read_graph(dup)
    for tid in (TRIAL_A, "trial:achieve_1"):
        assert nodes[tid]["ct_overall_status"]
    # Registry edges are written once, from the canonical (lowest-id) Trial node.
    assert _edges(links, "reports_adverse_event", "trial:achieve_1")
    assert not _edges(links, "reports_adverse_event", TRIAL_A)


@pytest.mark.unit
def test_sift_kg_missing_skips_registry_writes(enrich, tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "sift_kg", None)
    _seeded_graph(tmp_path)
    report, _ = _run(enrich, tmp_path, _all_fixture_bodies(), results=True)
    block = report["results"]
    assert isinstance(block.get("skipped_reason"), str) and block["skipped_reason"]
    assert list(block)[-1] == "skipped_reason"
    assert block["created"] == 0
    nodes, links = _read_graph(tmp_path)
    assert not [n for n in nodes.values() if n.get("entity_type") == "AdverseEvent"]
    assert nodes[TRIAL_A]["ct_overall_status"]


# --- Phase 7 review fixes (07-REVIEW.md) ------------------------------------


def _study_with_measure_copy(index: int, title: str, time_frame: str | None = None) -> dict:
    """Study A with a copy of outcome measure `index` appended under a new title."""
    study = _study(WITH_RESULTS_A)
    measures = study["resultsSection"]["outcomeMeasuresModule"]["outcomeMeasures"]
    extra = copy.deepcopy(measures[index])
    extra["title"] = title
    if time_frame is not None:
        extra["timeFrame"] = time_frame
    measures.append(extra)
    return study


def _ctgov_ids(item) -> list:
    return list((item.get("attributes") or {}).get("ctgov_nct_ids") or [])


@pytest.mark.unit
def test_same_estimate_requires_stated_precision(enrich):
    # WR-01: an integer-valued side must not widen the match to +/-0.5.
    assert enrich._same_estimate(1.0, 0.55) is False
    assert enrich._same_estimate(-2, -1.62) is False
    assert enrich._same_estimate(-1.0, -1.12) is False
    assert enrich._same_estimate(-1.3, -1.30) is True
    assert enrich._same_estimate(-1.4, -1.44) is True
    assert enrich._same_estimate(0.66, 0.66) is True
    assert enrich._same_estimate(1, 1.0) is True


@pytest.mark.unit
def test_analysis_merge_same_trial_only(enrich, tmp_path):
    # CR-01: an Outcome shared by two trials must not let trial B's extracted
    # analysis absorb trial A's registry analysis.
    outcome_nodes, outcome_links = _hba1c_outcome_nodes()
    shared = outcome_nodes[0]["id"]
    ref = _hba1c_analysis(enrich, "12 mg Orforglipron")
    b_cohort = {
        "id": "cohort:semaglutide_2_4_mg_arm", "name": "Semaglutide 2.4 mg arm",
        "entity_type": "Cohort", "source_documents": ["doc_b"],
    }
    b_analysis = {
        "id": "outcomeanalysis:trial_b_hba1c", "name": "Semaglutide HbA1c analysis",
        "entity_type": "OutcomeAnalysis", "source_documents": ["doc_b"],
        "attributes": {
            "effect_measure": ref["param_type"],
            "effect_estimate": round(float(ref["param_value"]), 1),
        },
    }
    b_named = {
        "id": "outcomeanalysis:nct03548935_hba1c", "name": f"{WITH_RESULTS_B}: HbA1c — sema vs placebo",
        "entity_type": "OutcomeAnalysis", "source_documents": ["doc_b"],
        "attributes": {
            "effect_measure": ref["param_type"],
            "effect_estimate": round(float(ref["param_value"]), 1),
        },
    }
    links = [
        *outcome_links,
        _link(TRIAL_B, "has_outcome", shared),
        _link(TRIAL_B, "enrolls", b_cohort["id"]),
        _link(b_analysis["id"], "analyzes", shared),
        _link(b_analysis["id"], "compares", b_cohort["id"]),
        _link(b_named["id"], "analyzes", shared),
    ]
    _, _, nodes, links_out = _seeded_run(
        enrich, tmp_path, extra_nodes=[*outcome_nodes, b_cohort, b_analysis, b_named],
        extra_links=links,
    )
    for nid in (b_analysis["id"], b_named["id"]):
        attrs = nodes[nid].get("attributes") or {}
        assert WITH_RESULTS_A not in _ctgov_ids(nodes[nid]), nid
        assert "p_value" not in attrs and "ctgov_analysis_ids" not in attrs, nid
        assert "ctgov_results" not in (attrs.get("sources") or []), nid
        assert {l["target"] for l in _edges(links_out, "compares", nid)} <= {b_cohort["id"]}
    hba1c = [
        n for n in _oa_nodes(nodes, WITH_RESULTS_A)
        if " Change From Baseline in HbA1c — " in n["name"]
    ]
    assert len(hba1c) == 3


@pytest.mark.unit
def test_registry_outcome_id_never_reuses_other_trial_node(enrich, tmp_path):
    # CR-01: the created registry Outcome id must not resolve to another
    # trial's extracted node.
    title = "Change From Baseline in Systolic Blood Pressure (SBP)"
    other = {
        "id": f"outcome:{enrich._slug(title)}", "name": title, "entity_type": "Outcome",
        "source_documents": ["doc_b"], "attributes": {"timeframe": "Week 68"},
    }
    _, _, nodes, links = _seeded_run(
        enrich, tmp_path, extra_nodes=[other],
        extra_links=[_link(TRIAL_B, "has_outcome", other["id"])],
    )
    assert _ctgov_ids(nodes[other["id"]]) == []
    assert "ctgov_results" not in (_nattr(nodes[other["id"]], "sources") or [])
    assert not _edges(links, "has_outcome", TRIAL_A, other["id"])
    sbp = [n for n in _oa_nodes(nodes, WITH_RESULTS_A) if f" {title} — " in n["name"]]
    assert len(sbp) == 3
    targets = {l["target"] for n in sbp for l in _edges(links, "analyzes", n["id"])}
    assert len(targets) == 1 and other["id"] not in targets
    target = next(iter(targets))
    assert _nattr(nodes[target], "source") == "ctgov_results"
    assert _edges(links, "has_outcome", TRIAL_A, target)


@pytest.mark.unit
def test_analysis_merge_requires_same_arms(enrich, tmp_path):
    # CR-02: a shared placebo arm is not enough; the extracted 36 mg vs placebo
    # analysis must absorb only the registry 36 mg vs placebo analysis.
    outcome_nodes, outcome_links = _hba1c_outcome_nodes()
    seed_id = "outcomeanalysis:seed_hba1c_36_vs_placebo"
    seed = {
        "id": seed_id, "name": "Seeded HbA1c 36 mg vs placebo",
        "entity_type": "OutcomeAnalysis", "source_documents": ["doc_seed"],
        "attributes": {"effect_measure": "ETD", "effect_estimate": -1.3},
    }
    links = [
        *outcome_links,
        _link(seed_id, "analyzes", outcome_nodes[0]["id"]),
        _link(seed_id, "compares", COHORT_PLACEBO),
        _link(seed_id, "compares", COHORT_36),
    ]
    _, _, nodes, links_out = _seeded_run(
        enrich, tmp_path, extra_nodes=[*outcome_nodes, seed], extra_links=links,
    )
    want = f"{WITH_RESULTS_A}: Change From Baseline in HbA1c — Placebo vs 36 mg Orforglipron"
    attrs = nodes[seed_id]["attributes"]
    assert attrs["ctgov_analysis_ids"] == [f"outcomeanalysis:{enrich._slug(want)}"]
    assert {l["target"] for l in _edges(links_out, "compares", seed_id)} == {
        COHORT_PLACEBO, COHORT_36,
    }
    assert attrs["registry_effect_measure"] == _hba1c_analysis(enrich, "36 mg Orforglipron")["param_type"]
    names = {n["name"] for n in _oa_nodes(nodes, WITH_RESULTS_A)}
    for group in ("3 mg Orforglipron", "12 mg Orforglipron"):
        assert f"{WITH_RESULTS_A}: Change From Baseline in HbA1c — Placebo vs {group}" in names
    assert want not in names


@pytest.mark.unit
def test_outcome_match_keeps_distinct_measures(enrich, tmp_path):
    # WR-02: registry titles that differ only in a parenthetical get their own
    # Outcome nodes with their own time frame.
    base = "Change From Baseline in Systolic Blood Pressure (SBP)"
    variant = "Change From Baseline in Systolic Blood Pressure (Participants With Hypertension)"
    study = _study_with_measure_copy(10, variant, "Baseline, Week 26")
    _seeded_graph(tmp_path)
    _run(enrich, tmp_path, {WITH_RESULTS_A: study, WITH_RESULTS_B: _study(WITH_RESULTS_B)}, results=True)
    nodes, links = _read_graph(tmp_path)
    by_title = {}
    for n in _oa_nodes(nodes, WITH_RESULTS_A):
        for title in (base, variant):
            if f": {title} — " in n["name"]:
                by_title.setdefault(title, set()).update(
                    l["target"] for l in _edges(links, "analyzes", n["id"])
                )
    assert len(by_title[base]) == 1 and len(by_title[variant]) == 1
    assert by_title[base] != by_title[variant]
    variant_outcome = nodes[next(iter(by_title[variant]))]
    assert variant_outcome["name"] == variant
    assert _nattr(variant_outcome, "timeframe") == "Baseline, Week 26"


@pytest.mark.unit
def test_outcome_match_respects_unit_qualifier(enrich, tmp_path):
    # WR-02: an extracted "HbA1c (mmol/mol)" outcome is not the registry's
    # percentage HbA1c measure, whatever the id sort order.
    outcome_nodes, outcome_links = _hba1c_outcome_nodes()
    mmol = {
        "id": "outcome:change_in_hba1c_mmol_mol", "name": "Change in HbA1c (mmol/mol)",
        "entity_type": "Outcome", "source_documents": ["doc_seed"],
    }
    _, _, nodes, links = _seeded_run(
        enrich, tmp_path, extra_nodes=[*outcome_nodes, mmol],
        extra_links=[*outcome_links, _link(TRIAL_A, "has_outcome", mmol["id"])],
    )
    hba1c = [
        n for n in _oa_nodes(nodes, WITH_RESULTS_A)
        if " Change From Baseline in HbA1c — " in n["name"]
    ]
    assert len(hba1c) == 3
    for oa in hba1c:
        assert [l["target"] for l in _edges(links, "analyzes", oa["id"])] == [outcome_nodes[0]["id"]]
    assert not _edges(links, "analyzes", tgt=mmol["id"])


@pytest.mark.unit
def test_serious_and_other_event_counts_combined(enrich, tmp_path):
    # WR-03: an event in both tables carries combined headline counts, a serious
    # flag and the per-table breakdown.
    _, _, nodes, links = _seeded_run(enrich, tmp_path)
    parsed = _parsed(enrich, WITH_RESULTS_B)["adverse_events"]
    records = [a for a in parsed if enrich._ae_key(a["term"]) == "nausea"]
    assert {r["seriousness"] for r in records} == {"serious", "other"}
    ae_id = next(
        n["id"] for n in nodes.values()
        if n.get("entity_type") == "AdverseEvent" and enrich._ae_key(n["name"]) == "nausea"
    )
    edge = _edges(links, "reports_adverse_event", TRIAL_B, ae_id)
    assert len(edge) == 1
    edge = edge[0]
    affected = sum(s["num_affected"] for r in records for s in r["stats"])
    groups = {}
    for r in records:
        for s in r["stats"]:
            g = groups.setdefault(s["group_title"], {"n_affected": 0, "n_at_risk": 0})
            g["n_affected"] += s["num_affected"]
            g["n_at_risk"] = max(g["n_at_risk"], s["num_at_risk"])
    assert _eattr(edge, "seriousness") == "serious"
    assert _eattr(edge, "n_affected") == affected
    assert _eattr(edge, "n_at_risk") == sum(g["n_at_risk"] for g in groups.values())
    for title, g in groups.items():
        assert _eattr(edge, "by_group")[title]["n_affected"] == g["n_affected"]
        assert _eattr(edge, "by_group")[title]["n_at_risk"] == g["n_at_risk"]
    breakdown = _eattr(edge, "by_seriousness")
    assert set(breakdown) == {"serious", "other"}
    for r in records:
        assert breakdown[r["seriousness"]]["n_affected"] == sum(s["num_affected"] for s in r["stats"])
    assert f"{affected} of " in edge["evidence"]


@pytest.mark.unit
def test_write_failure_is_atomic_and_reported(enrich, tmp_path, monkeypatch, capsys):
    # WR-04: a failing trial leaves no partial writes, is reported with its
    # error, and a later run completes it.
    original = enrich._write_analyses

    def boom(kg, nct, *args, **kwargs):
        if nct == WITH_RESULTS_A:
            raise RuntimeError("injected failure")
        return original(kg, nct, *args, **kwargs)

    monkeypatch.setattr(enrich, "_write_analyses", boom)
    report, _, nodes, links = _seeded_run(enrich, tmp_path)
    block = report["results"]
    assert block["write_failed"] == 1
    assert "RuntimeError" in block["write_errors"][WITH_RESULTS_A]
    assert "injected failure" in capsys.readouterr().err
    assert not [n for n in nodes.values() if WITH_RESULTS_A in _ctgov_ids(n)]
    assert not [l for l in links if WITH_RESULTS_A in _ctgov_ids(l)]
    assert [n for n in nodes.values() if WITH_RESULTS_B in _ctgov_ids(n)]
    assert block["created_nodes"] == len(_registry_nodes(nodes))
    assert block["created_edges"] == sum(1 for l in links if _eattr(l, "source") == "ctgov_results")

    monkeypatch.setattr(enrich, "_write_analyses", original)
    report, _ = _run(enrich, tmp_path, _all_fixture_bodies(), results=True)
    assert report["results"]["write_failed"] == 0
    assert "write_errors" not in report["results"]
    nodes, _ = _read_graph(tmp_path)
    assert len(_oa_nodes(nodes, WITH_RESULTS_A)) == 39


@pytest.mark.unit
def test_analysis_names_differing_only_in_punctuation_both_kept(enrich, tmp_path):
    # IN-04: two analyses whose names slug to one id must both be written.
    variant = "Percentage of Participants With an HbA1c Target Value of <=6.5% (48 mmol/Mol)"
    study = _study_with_measure_copy(2, variant)
    _seeded_graph(tmp_path)
    _run(enrich, tmp_path, {WITH_RESULTS_A: study, WITH_RESULTS_B: _study(WITH_RESULTS_B)}, results=True)
    nodes, _ = _read_graph(tmp_path)
    assert len(_oa_nodes(nodes, WITH_RESULTS_A)) == 39 + 3


# --- Phase 7 review fixes, iteration 2 (07-REVIEW.md) ----------------------


@pytest.mark.unit
def test_analysis_merge_ignores_cohorts_shared_with_another_trial(enrich, tmp_path):
    # CR-01 (iteration 2): trial B also enrolls the 36 mg and placebo cohorts.
    # Its extracted analysis carries no NCT, so comparing cohorts that trial A
    # enrolls too is no evidence that it belongs to trial A.
    outcome_nodes, outcome_links = _hba1c_outcome_nodes()
    shared = outcome_nodes[0]["id"]
    b_analysis = {
        "id": "outcomeanalysis:paper_b_hba1c", "name": "Orforglipron high dose HbA1c analysis (paper B)",
        "entity_type": "OutcomeAnalysis", "source_documents": ["doc_b"],
        "attributes": {"effect_measure": "ETD", "effect_estimate": -0.4, "p_value_num": 0.3},
    }
    links = [
        *outcome_links,
        _link(TRIAL_B, "has_outcome", shared),
        _link(TRIAL_B, "enrolls", COHORT_36),
        _link(TRIAL_B, "enrolls", COHORT_PLACEBO),
        _link(b_analysis["id"], "analyzes", shared),
        _link(b_analysis["id"], "compares", COHORT_36),
        _link(b_analysis["id"], "compares", COHORT_PLACEBO),
    ]
    _, _, nodes, links_out = _seeded_run(
        enrich, tmp_path, extra_nodes=[*outcome_nodes, b_analysis], extra_links=links,
    )
    attrs = nodes[b_analysis["id"]].get("attributes") or {}
    assert _ctgov_ids(nodes[b_analysis["id"]]) == []
    assert attrs == b_analysis["attributes"]
    assert {l["target"] for l in _edges(links_out, "compares", b_analysis["id"])} == {
        COHORT_36, COHORT_PLACEBO,
    }
    want = f"{WITH_RESULTS_A}: Change From Baseline in HbA1c — Placebo vs 36 mg Orforglipron"
    assert want in {n["name"] for n in _oa_nodes(nodes, WITH_RESULTS_A)}
    assert len(_oa_nodes(nodes, WITH_RESULTS_A)) == 39


@pytest.mark.unit
def test_estimate_only_match_requires_unambiguous_pair(enrich, tmp_path):
    # WR-01 (iteration 2): an extracted analysis with no compares edges matches
    # several registry SF-36 analyses on measure and estimate alone (-0.04 for
    # 12 mg and 0.01 for 3 mg both round to 0.0). The tie must not be broken by
    # registry order. A unique estimate-only match still merges.
    sf36 = (
        "Change From Baseline in Short Form-36 Health Survey Version 2 (SF-36v2) Acute Form "
        "(Physical-Component and Mental-Component) Scores"
    )
    hba1c_nodes, hba1c_links = _hba1c_outcome_nodes()
    sf_outcome = {
        "id": "outcome:sf_36_seed", "name": sf36, "entity_type": "Outcome",
        "source_documents": ["doc_seed"], "attributes": {"unit": "T-score"},
    }
    tie = {
        "id": "outcomeanalysis:seed_sf36_mcs", "name": f"{WITH_RESULTS_A}: SF-36 MCS — 3 mg vs placebo",
        "entity_type": "OutcomeAnalysis", "source_documents": ["doc_seed"],
        "attributes": {"effect_measure": "LS Mean Difference (Net)", "effect_estimate": 0.0},
    }
    unique = {
        "id": "outcomeanalysis:seed_hba1c_unique", "name": f"{WITH_RESULTS_A}: HbA1c — 12 mg vs placebo",
        "entity_type": "OutcomeAnalysis", "source_documents": ["doc_seed"],
        "attributes": {"effect_measure": "LS Mean Difference (Net)", "effect_estimate": -1.44},
    }
    links = [
        *hba1c_links,
        _link(TRIAL_A, "has_outcome", sf_outcome["id"]),
        _link(tie["id"], "analyzes", sf_outcome["id"]),
        _link(unique["id"], "analyzes", hba1c_nodes[0]["id"]),
    ]
    _, _, nodes, _ = _seeded_run(
        enrich, tmp_path, extra_nodes=[*hba1c_nodes, sf_outcome, tie, unique], extra_links=links,
    )
    tie_attrs = nodes[tie["id"]].get("attributes") or {}
    assert tie_attrs == tie["attributes"]
    sf_names = {n["name"] for n in _oa_nodes(nodes, WITH_RESULTS_A) if f" {sf36} — " in n["name"]}
    assert len(sf_names) == 6
    want = f"{WITH_RESULTS_A}: Change From Baseline in HbA1c — Placebo vs 12 mg Orforglipron"
    assert _nattr(nodes[unique["id"]], "ctgov_analysis_ids") == [
        f"outcomeanalysis:{enrich._slug(want)}"
    ]
    assert len(_oa_nodes(nodes, WITH_RESULTS_A)) == 38


@pytest.mark.unit
def test_active_arm_with_matching_placebo_is_not_placebo(enrich, tmp_path):
    # IN-01 (iteration 2): a double-dummy active arm also receives a matching
    # placebo. It is still an active arm, so an un-NCT-named extracted analysis
    # that compares it belongs to the trial and absorbs the 36 mg analysis.
    from types import SimpleNamespace

    import networkx as nx

    g = nx.MultiDiGraph()
    g.add_node("cohort:a", name="Semaglutide 1.0 mg", entity_type="Cohort")
    g.add_node("cohort:b", name="Comparator arm", entity_type="Cohort")
    g.add_node("cohort:c", name="Placebo", entity_type="Cohort")
    g.add_node("cohort:d", name="Arm D", entity_type="Cohort", attributes={"arm_label": "Placebo arm"})
    g.add_node("cohort:e", name="Arm E", entity_type="Cohort")
    g.add_node("compound:sema", name="Semaglutide", entity_type="Compound")
    g.add_node("intervention:pbo_sema", name="Placebo (semaglutide)", entity_type="Intervention")
    for cid, tgt in (("cohort:a", "compound:sema"), ("cohort:a", "intervention:pbo_sema"),
                     ("cohort:b", "intervention:pbo_sema")):
        g.add_edge(cid, tgt, relation_type="receives")
    kg = SimpleNamespace(graph=g)
    assert enrich._is_placebo_cohort(kg, "cohort:a") is False
    assert enrich._is_placebo_cohort(kg, "cohort:b") is True
    assert enrich._is_placebo_cohort(kg, "cohort:c") is True
    assert enrich._is_placebo_cohort(kg, "cohort:d") is True
    assert enrich._is_placebo_cohort(kg, "cohort:e") is False

    ref, nodes_seed, links_seed = _extracted_analysis_seed(enrich)
    pbo = {
        "id": "intervention:placebo_orforglipron", "name": "Placebo matching orforglipron",
        "entity_type": "Intervention", "source_documents": ["doc_seed"],
    }
    seed_id = "outcomeanalysis:seed_hba1c_36"
    _, _, nodes, links = _seeded_run(
        enrich, tmp_path, extra_nodes=[*nodes_seed, pbo],
        extra_links=[*links_seed, _link(COHORT_36, "receives", pbo["id"])],
    )
    want = f"{WITH_RESULTS_A}: Change From Baseline in HbA1c — Placebo vs 36 mg Orforglipron"
    assert _nattr(nodes[seed_id], "ctgov_analysis_ids") == [f"outcomeanalysis:{enrich._slug(want)}"]
    assert want not in {n["name"] for n in _oa_nodes(nodes, WITH_RESULTS_A)}
    assert [l["target"] for l in _edges(links, "assesses_effect_of", seed_id)] == [COMPOUND]


@pytest.mark.unit
def test_analysis_merge_fills_statistic_groups_whole(enrich, tmp_path):
    # SA-04 ruling: p-value fields and effect/CI fields fill as groups. The
    # seed states its own estimate and p_value_num, so neither group is mixed
    # with registry values; every registry value of a partly present group that
    # differs or is absent is kept under registry_<attr>. Other attributes
    # still fill one at a time.
    ref = _hba1c_analysis(enrich, "36 mg Orforglipron")
    outcome_nodes, outcome_links = _hba1c_outcome_nodes()
    seed_id = "outcomeanalysis:seed_hba1c_36_own_stats"
    seed = {
        "id": seed_id, "name": "Seeded HbA1c 36 mg with its own statistics",
        "entity_type": "OutcomeAnalysis", "source_documents": ["doc_seed"],
        "attributes": {
            "effect_measure": ref["param_type"], "effect_estimate": -1.2, "p_value_num": 0.002,
        },
    }
    links = [
        *outcome_links,
        _link(seed_id, "analyzes", outcome_nodes[0]["id"]),
        _link(seed_id, "compares", COHORT_36),
    ]
    _, _, nodes, _ = _seeded_run(
        enrich, tmp_path, extra_nodes=[*outcome_nodes, seed], extra_links=links,
    )
    want = f"{WITH_RESULTS_A}: Change From Baseline in HbA1c — Placebo vs 36 mg Orforglipron"
    attrs = nodes[seed_id]["attributes"]
    assert attrs["ctgov_analysis_ids"] == [f"outcomeanalysis:{enrich._slug(want)}"]
    # Group P: extracted p_value_num kept; nothing filled beside it.
    assert attrs["p_value_num"] == 0.002
    assert "p_value" not in attrs and "p_value_qualifier" not in attrs
    assert attrs["registry_p_value"] == ref["p_value"]
    assert attrs["registry_p_value_num"] == 0.001
    assert attrs["registry_p_value_qualifier"] == "<"
    # Group E: extracted estimate and measure kept; no registry CI beside them.
    assert attrs["effect_estimate"] == -1.2
    assert attrs["effect_measure"] == ref["param_type"]
    for key in ("ci_lower", "ci_upper", "ci_level", "ci_sides"):
        assert key not in attrs, key
    assert attrs["registry_effect_estimate"] == float(ref["param_value"])
    assert "registry_effect_measure" not in attrs
    assert attrs["registry_ci_lower"] == float(ref["ci_lower_limit"])
    assert attrs["registry_ci_upper"] == float(ref["ci_upper_limit"])
    assert attrs["registry_ci_level"] == 95
    assert attrs["registry_ci_sides"] == "TWO_SIDED"
    # Ungrouped attributes keep the per-attribute fill rule.
    assert attrs["endpoint_type"] == "primary"
    assert attrs["timepoint"] and attrs["unit"]


# --- CT.gov arm groups on registry analyses ---------------------------------

HEAD_TO_HEAD = "NCT03987919"


def _h2h_bodies(strip_arm_groups: bool = False) -> dict:
    study = _study(HEAD_TO_HEAD)
    if strip_arm_groups:
        study = copy.deepcopy(study)
        del study["protocolSection"]["armsInterventionsModule"]["armGroups"]
    return {HEAD_TO_HEAD: study}


def _h2h_run(enrich, directory: Path, strip_arm_groups: bool = False):
    _write_graph(directory, [HEAD_TO_HEAD])
    report, _ = _run(enrich, directory, _h2h_bodies(strip_arm_groups), results=True)
    return report, *_read_graph(directory)


@pytest.mark.unit
def test_parse_arm_groups(enrich):
    arms = enrich._parse_ct_results(_study(HEAD_TO_HEAD))["arm_groups"]
    assert [(a["label"], a["type"], a["interventions"]) for a in arms] == [
        ("5 mg Tirzepatide", "EXPERIMENTAL", ["Drug: Tirzepatide"]),
        ("10 mg Tirzepatide", "EXPERIMENTAL", ["Drug: Tirzepatide"]),
        ("15 mg Tirzepatide", "EXPERIMENTAL", ["Drug: Tirzepatide"]),
        ("1 mg Semaglutide", "ACTIVE_COMPARATOR", ["Drug: Semaglutide"]),
    ]
    other = enrich._parse_ct_results(_study(WITH_RESULTS_A))["arm_groups"]
    assert [a["type"] for a in other].count("PLACEBO_COMPARATOR") == 1
    assert [a["type"] for a in other].count("EXPERIMENTAL") == 3


@pytest.mark.unit
def test_match_label_is_the_cohort_matcher(enrich):
    m = enrich._match_label
    assert m("12 mg Orforglipron", [("a", ["Orforglipron 12mg"])]) == "a"
    assert m("12 mg Orforglipron", [("a", ["Orforglipron 12mg"]), ("b", ["12 mg orforglipron QW"])]) is None
    assert m("Placebo", [("a", ["Semaglutide placebo 0.5 mg"])]) is None
    assert m("", [("a", ["x"])]) is None


@pytest.mark.unit
def test_analysis_arm_groups_written(enrich, tmp_path):
    report, nodes, _ = _h2h_run(enrich, tmp_path)
    analyses = _oa_nodes(nodes, HEAD_TO_HEAD)
    assert analyses
    for node in analyses:
        attrs = node["attributes"]
        groups = attrs["ctgov_arm_groups"]
        assert [g["title"] for g in groups] == attrs["compared_groups"]
        for g in groups:
            assert set(g) == {"title", "arm_type", "interventions"}
            if "Tirzepatide" in g["title"]:
                assert g["arm_type"] == "EXPERIMENTAL"
                assert g["interventions"] == ["Drug: Tirzepatide"]
            else:
                assert g["arm_type"] == "ACTIVE_COMPARATOR"
                assert g["interventions"] == ["Drug: Semaglutide"]


@pytest.mark.unit
def test_analysis_arm_groups_unmatched_title(enrich, tmp_path):
    study = copy.deepcopy(_study(HEAD_TO_HEAD))
    arms = study["protocolSection"]["armsInterventionsModule"]["armGroups"]
    study["protocolSection"]["armsInterventionsModule"]["armGroups"] = [
        a for a in arms if a["label"] != "10 mg Tirzepatide"
    ]
    _write_graph(tmp_path, [HEAD_TO_HEAD])
    _run(enrich, tmp_path, {HEAD_TO_HEAD: study}, results=True)
    nodes, _ = _read_graph(tmp_path)
    seen = False
    for node in _oa_nodes(nodes, HEAD_TO_HEAD):
        for g in node["attributes"].get("ctgov_arm_groups", []):
            if g["title"] == "10 mg Tirzepatide":
                seen = True
                assert g["arm_type"] is None and g["interventions"] == []
    assert seen


@pytest.mark.unit
def test_analysis_without_arm_groups_has_no_key(enrich, tmp_path):
    with_dir, without_dir = tmp_path / "with", tmp_path / "without"
    _, with_nodes, _ = _h2h_run(enrich, with_dir)
    _, without_nodes, _ = _h2h_run(enrich, without_dir, strip_arm_groups=True)
    a = {n["id"]: dict(n["attributes"]) for n in _oa_nodes(with_nodes)}
    b = {n["id"]: dict(n["attributes"]) for n in _oa_nodes(without_nodes)}
    assert a.keys() == b.keys() and a
    for key in a:
        assert "ctgov_arm_groups" not in b[key]
        a[key].pop("ctgov_arm_groups")
        assert a[key] == b[key]


@pytest.mark.unit
def test_analysis_merge_holder_gets_arm_groups(enrich, tmp_path):
    ref, nodes_seed, links_seed = _extracted_analysis_seed(enrich)
    _, _, nodes, _ = _seeded_run(enrich, tmp_path, extra_nodes=nodes_seed, extra_links=links_seed)
    attrs = nodes["outcomeanalysis:seed_hba1c_36"]["attributes"]
    assert [g["arm_type"] for g in attrs["ctgov_arm_groups"]] == ["PLACEBO_COMPARATOR", "EXPERIMENTAL"]
    assert not any(k.startswith("registry_ctgov") for k in attrs)


@pytest.mark.unit
def test_analysis_merge_keeps_existing_arm_groups(enrich, tmp_path):
    _, nodes_seed, links_seed = _extracted_analysis_seed(enrich)
    keep = [{"title": "kept", "arm_type": "OTHER", "interventions": []}]
    for n in nodes_seed:
        if n["id"] == "outcomeanalysis:seed_hba1c_36":
            n["attributes"]["ctgov_arm_groups"] = copy.deepcopy(keep)
    _, _, nodes, _ = _seeded_run(enrich, tmp_path, extra_nodes=nodes_seed, extra_links=links_seed)
    attrs = nodes["outcomeanalysis:seed_hba1c_36"]["attributes"]
    assert attrs["ctgov_arm_groups"] == keep
    assert "registry_ctgov_arm_groups" not in attrs


@pytest.mark.unit
def test_arm_groups_backfill_on_rerun(enrich, tmp_path):
    _h2h_run(enrich, tmp_path)
    path = tmp_path / "graph_data.json"
    data = json.loads(path.read_text())
    for n in data["nodes"]:
        if n.get("entity_type") == "OutcomeAnalysis":
            n["attributes"].pop("ctgov_arm_groups")
    path.write_text(json.dumps(data, indent=2))
    report, _ = _run(enrich, tmp_path, _h2h_bodies(), results=True)
    nodes, _ = _read_graph(tmp_path)
    assert report["results"]["created"] == 0 and report["results"]["merged"] == 0
    assert all("ctgov_arm_groups" in n["attributes"] for n in _oa_nodes(nodes))
    second = path.read_bytes()
    _run(enrich, tmp_path, _h2h_bodies(), results=True)
    assert _normalize_stamps(second) == _normalize_stamps(path.read_bytes())


# --- AE merge is limited to the same trial ----------------------------------


@pytest.mark.unit
def test_ae_not_merged_into_extracted_ae_of_another_trial(enrich, tmp_path):
    ae, node, link, _ = _extracted_ae_seed(enrich)
    key = enrich._ae_key(ae["term"])
    assert key not in {
        enrich._ae_key(a["term"]) for a in _parsed(enrich, WITH_RESULTS_B)["adverse_events"]
    }
    other = _link(TRIAL_B, "reports_adverse_event", node["id"], n_affected=999)
    report, _, nodes, links = _seeded_run(
        enrich, tmp_path, extra_nodes=[node], extra_links=[other]
    )
    seeded = nodes[node["id"]]
    assert seeded["attributes"] == node["attributes"]
    assert seeded["source_documents"] == ["doc_seed"]
    assert not _edges(links, "reports_adverse_event", TRIAL_A, node["id"])
    same = [n for n in nodes.values()
            if n.get("entity_type") == "AdverseEvent" and enrich._ae_key(n["name"]) == key]
    registry = [n for n in same if _nattr(n, "source") == "ctgov_results"]
    assert len(same) == 2 and len(registry) == 1
    assert registry[0]["id"] != node["id"]
    assert _nattr(registry[0], "ctgov_nct_ids") == [WITH_RESULTS_A]
    assert len(_edges(links, "reports_adverse_event", TRIAL_A, registry[0]["id"])) == 1
    # A second run finds the registry node through the trial's own edge.
    first, _ = _read_graph(tmp_path)
    again, _ = _run(enrich, tmp_path, _all_fixture_bodies(), results=True)
    assert again["results"]["created"] == 0 and again["results"]["merged"] == 0
    assert set(_read_graph(tmp_path)[0]) == set(first)


@pytest.mark.unit
def test_ae_registry_node_shared_by_registry_trials(enrich, tmp_path):
    _seeded_run(enrich, tmp_path)
    nodes, links = _read_graph(tmp_path)
    shared = {
        n["id"] for n in _registry_nodes(nodes, "AdverseEvent")
        if len(_nattr(n, "ctgov_nct_ids", [])) > 1
    }
    assert shared


# --- Registry AE ids are trial-order independent; stale cross-trial links ---


def _common_ae_term(enrich) -> str:
    def keys(nct):
        return {enrich._ae_key(a["term"]): a["term"] for a in _parsed(enrich, nct)["adverse_events"]}
    a, b = keys(WITH_RESULTS_A), keys(WITH_RESULTS_B)
    for key in sorted(set(a) & set(b)):
        if a[key] == b[key] and a[key] == a[key].capitalize() and " " not in a[key]:
            return a[key]
    raise AssertionError("no AE term shared by both fixtures")


def _foreign_ae(term):
    return {
        "id": f"adverseevent:{term.lower()}", "name": term, "entity_type": "AdverseEvent",
        "source_documents": ["doc_other"], "attributes": {"reported_term": "seeded wording"},
    }


@pytest.mark.unit
def test_registry_ae_id_is_shared_and_trial_independent(enrich, tmp_path):
    term = _common_ae_term(enrich)
    node = _foreign_ae(term)
    _, _, nodes, links = _seeded_run(enrich, tmp_path, extra_nodes=[node])
    assert nodes[node["id"]]["attributes"] == node["attributes"]
    registry_id = f"{node['id']}_ctgov"
    assert registry_id in nodes
    assert _nattr(nodes[registry_id], "source") == "ctgov_results"
    assert _nattr(nodes[registry_id], "ctgov_nct_ids") == sorted([WITH_RESULTS_A, WITH_RESULTS_B])
    assert not [i for i in nodes if re.search(r"_nct\d+$", i) and i.startswith("adverseevent:")]
    for trial in (TRIAL_A, TRIAL_B):
        assert len(_edges(links, "reports_adverse_event", trial, registry_id)) == 1
        assert not _edges(links, "reports_adverse_event", trial, node["id"])


@pytest.mark.unit
def test_stale_registry_link_to_another_trials_ae_is_ignored(enrich, tmp_path):
    term = _common_ae_term(enrich)
    node = _foreign_ae(term)
    own = _link(TRIAL_A, "reports_adverse_event", node["id"])
    stale = _link(
        TRIAL_B, "reports_adverse_event", node["id"], source_document=f"ctgov:{WITH_RESULTS_B}",
        source="ctgov_results", ctgov_nct_ids=[WITH_RESULTS_B],
    )
    report, _, nodes, links = _seeded_run(
        enrich, tmp_path, extra_nodes=[node], extra_links=[own, stale]
    )
    assert report["results"]["cross_trial_ae_links_ignored"] == 1
    merged = nodes[node["id"]]
    assert _nattr(merged, "ctgov_nct_ids") == [WITH_RESULTS_A]
    registry = nodes[f"{node['id']}_ctgov"]
    assert _nattr(registry, "ctgov_nct_ids") == [WITH_RESULTS_B]
    assert len(_edges(links, "reports_adverse_event", TRIAL_B, registry["id"])) == 1
    assert _edges(links, "reports_adverse_event", TRIAL_B, node["id"])  # never deleted
    again, _ = _run(enrich, tmp_path, _all_fixture_bodies(), results=True)
    assert again["results"]["created"] == 0 and again["results"]["merged"] == 0


# --- Opt-in serious-event floor (--results-serious-min-pct, iteration 21) ----

ITERATION20_COMMIT = "1589524b63f479f9ec5cd1a579fcb3b471948549"


def _serious_reaches(event, pct) -> bool:
    return any(
        s["numAtRisk"] and s["numAffected"] / s["numAtRisk"] * 100 >= pct
        for s in event.get("stats", [])
        if isinstance(s.get("numAtRisk"), (int, float)) and isinstance(s.get("numAffected"), (int, float))
    )


@pytest.mark.unit
def test_serious_min_pct_default_keeps_every_serious_event(enrich):
    for nct in (WITH_RESULTS_A, WITH_RESULTS_B):
        study = _study(nct)
        default = enrich._parse_ct_results(study)
        assert enrich._parse_ct_results(study, 0) == default
        assert "serious_min_pct" not in default and "serious_events_omitted" not in default
        module = study["resultsSection"]["adverseEventsModule"]
        assert sum(1 for a in default["adverse_events"] if a["seriousness"] == "serious") == len(
            module["seriousEvents"]
        )


@pytest.mark.unit
@pytest.mark.parametrize("nct, pct", [(WITH_RESULTS_A, 1), (WITH_RESULTS_B, 0.5)])
def test_serious_min_pct_floor_is_per_arm(enrich, nct, pct):
    # The fixtures' serious events are rare: 1 of 29 (A) reaches 1% in some
    # arm, 1 of 149 (B) reaches 0.5%.
    study = _study(nct)
    module = study["resultsSection"]["adverseEventsModule"]
    default = enrich._parse_ct_results(study)
    floored = enrich._parse_ct_results(study, pct)
    kept = [a for a in floored["adverse_events"] if a["seriousness"] == "serious"]
    expected = [e for e in module["seriousEvents"] if _serious_reaches(e, pct)]
    assert 0 < len(kept) < len(module["seriousEvents"])
    assert [a["term"] for a in kept] == [e["term"] for e in expected]
    for ae in kept:
        assert any(_stat_pct(s) >= pct for s in ae["stats"]), ae["term"]
    assert floored["serious_min_pct"] == pct
    assert floored["serious_events_omitted"] == len(module["seriousEvents"]) - len(kept)
    # Other events keep their own registry threshold.
    other = lambda r: [a for a in r["adverse_events"] if a["seriousness"] == "other"]
    assert other(floored) == other(default)


@pytest.mark.unit
def test_serious_min_pct_report_block_and_edges(enrich, tmp_path):
    _write_graph(tmp_path / "floor", [WITH_RESULTS_A, WITH_RESULTS_B])
    report, _ = _run(enrich, tmp_path / "floor", _all_fixture_bodies(), results=True, serious_min_pct=1)
    block = report["results"]
    assert set(block) == set(REPORT_KEYS) | {"serious_min_pct", "serious_events_omitted"}
    assert block["serious_min_pct"] == 1.0
    omitted = sum(
        enrich._parse_ct_results(_study(n), 1)["serious_events_omitted"]
        for n in (WITH_RESULTS_A, WITH_RESULTS_B)
    )
    assert block["serious_events_omitted"] == omitted > 0
    assert block["adverse_events_parsed"]["serious"] == 178 - omitted
    assert block["adverse_events_parsed"]["other"] == 39
    _, links = _read_graph(tmp_path / "floor")
    ae_links = _edges(links, "reports_adverse_event")
    assert ae_links and all(_eattr(l, "serious_min_pct") == 1.0 for l in ae_links)
    assert any(_eattr(l, "seriousness") == "serious" for l in ae_links)

    _write_graph(tmp_path / "default", [WITH_RESULTS_A, WITH_RESULTS_B])
    default, _ = _run(enrich, tmp_path / "default", _all_fixture_bodies(), results=True)
    assert set(default["results"]) == set(REPORT_KEYS)
    _, default_links = _read_graph(tmp_path / "default")
    assert not [l for l in default_links if _eattr(l, "serious_min_pct") is not None]
    assert len(_edges(default_links, "reports_adverse_event")) > len(ae_links)


@pytest.mark.unit
@pytest.mark.parametrize("bad", [-1, 100.5, float("nan"), "2", True])
def test_serious_min_pct_rejects_invalid(enrich, tmp_path, bad):
    _write_graph(tmp_path, [WITH_RESULTS_A])
    with pytest.raises(ValueError):
        _run(enrich, tmp_path, _all_fixture_bodies(), results=True, serious_min_pct=bad)


@pytest.mark.unit
def test_cli_serious_min_pct_flag(tmp_path):
    proc = subprocess.run(
        [sys.executable, str(_module_path()), "--help"], capture_output=True, text=True, timeout=60,
    )
    assert "--results-serious-min-pct" in proc.stdout
    bad = subprocess.run(
        [sys.executable, str(_module_path()), str(tmp_path), "--results", "--results-serious-min-pct", "-3"],
        capture_output=True, text=True, timeout=60,
    )
    assert bad.returncode == 2 and "serious_min_pct" in bad.stderr


@pytest.mark.unit
def test_results_default_byte_identical_to_iteration20(enrich, tmp_path, monkeypatch):
    """--results without the new flag writes exactly what iteration 20 wrote."""
    old_path = tmp_path / "enrich_iter20.py"
    old_path.write_bytes(_baseline_enrich_source(ITERATION20_COMMIT))
    old = _load_enrich("_ct_enrich_iter20", old_path)
    monkeypatch.setattr(old.time, "sleep", lambda s: None)
    bodies = _all_fixture_bodies()
    d_old = _seeded_graph(tmp_path / "old")
    d_new = _seeded_graph(tmp_path / "new")
    with patch.object(old.requests, "get", side_effect=_router(bodies)):
        rep_old = old.enrich_graph(d_old, results=True)
    with patch.object(enrich.requests, "get", side_effect=_router(bodies)):
        rep_new = enrich.enrich_graph(d_new, results=True)
    g_old = json.loads(_normalize_stamps((d_old / "graph_data.json").read_bytes()))
    g_new = json.loads(_normalize_stamps((d_new / "graph_data.json").read_bytes()))
    # Iteration 27 adds registry_<attr>_by_nct beside every stored conflict and
    # nothing else: without those keys the graphs are equal.
    assert g_old == _strip_by_nct(g_new) and _same_key_order(g_old, _strip_by_nct(g_new))
    rep_old.pop("generated_at")
    rep_new.pop("generated_at")
    _assert_report_delta(rep_old, rep_new)


# Iteration 22: a re-run under another floor never rewrites or misreports AEs


def _ae_edge_state(directory):
    _, links = _read_graph(directory)
    return sorted(
        (l["source"], l["target"], _eattr(l, "serious_min_pct")) for l in _edges(links, "reports_adverse_event")
    )


@pytest.mark.unit
@pytest.mark.parametrize("first, second", [(0, 1), (1, 0), (0.5, 2), (2, 0.5)])
def test_rerun_with_another_floor_leaves_aes_and_reports_conflict(enrich, tmp_path, first, second):
    _write_graph(tmp_path, [WITH_RESULTS_A, WITH_RESULTS_B])
    _run(enrich, tmp_path, _all_fixture_bodies(), results=True, serious_min_pct=first)
    before = _ae_edge_state(tmp_path)
    report, _ = _run(enrich, tmp_path, _all_fixture_bodies(), results=True, serious_min_pct=second)
    block = report["results"]
    assert _ae_edge_state(tmp_path) == before
    assert block["created"] == 0 and block["merged"] == 0
    assert block["serious_min_pct_conflicts"] == {
        WITH_RESULTS_A: [float(first)], WITH_RESULTS_B: [float(first)],
    }
    if second > 0:
        assert block["serious_min_pct"] == float(second)
        assert block["serious_events_omitted"] == 0  # the floor was applied to no trial


@pytest.mark.unit
@pytest.mark.parametrize("floor", [0, 1])
def test_rerun_with_the_same_floor_has_no_conflict(enrich, tmp_path, floor):
    _write_graph(tmp_path, [WITH_RESULTS_A, WITH_RESULTS_B])
    first, _ = _run(enrich, tmp_path, _all_fixture_bodies(), results=True, serious_min_pct=floor)
    again, _ = _run(enrich, tmp_path, _all_fixture_bodies(), results=True, serious_min_pct=floor)
    assert "serious_min_pct_conflicts" not in again["results"]
    assert again["results"]["created"] == 0
    assert again["results"].get("serious_events_omitted") == first["results"].get("serious_events_omitted")


@pytest.mark.unit
def test_floor_report_key_order_is_fixed(enrich, tmp_path):
    _write_graph(tmp_path / "a", [WITH_RESULTS_A])
    with_results, _ = _run(enrich, tmp_path / "a", _all_fixture_bodies(), results=True, serious_min_pct=1)
    _write_graph(tmp_path / "b", [NO_RESULTS])
    without, _ = _run(enrich, tmp_path / "b", _all_fixture_bodies(), results=True, serious_min_pct=1)
    assert list(with_results["results"])[-2:] == list(without["results"])[-2:] == [
        "serious_min_pct", "serious_events_omitted",
    ]
    assert without["results"]["serious_events_omitted"] == 0


@pytest.mark.unit
def test_cli_serious_min_pct_needs_results(tmp_path):
    proc = subprocess.run(
        [sys.executable, str(_module_path()), str(tmp_path), "--results-serious-min-pct", "1"],
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 2 and "needs --results" in proc.stderr


# --- Iteration 27 (999.3): canonical-trial edges, per-NCT conflicts, merged_by_type ---

ITERATION26_COMMIT = "cf9e8b7eb9d48e3f9bf92ff10786ea4e4e08a62e"
DUP_NODE = {"id": "trial:achieve_1", "name": f"ACHIEVE-1 ({WITH_RESULTS_A})", "entity_type": "Trial"}


def _strip_by_nct(value):
    """A copy of a parsed graph without any key ending in _by_nct."""
    if isinstance(value, dict):
        return {k: _strip_by_nct(v) for k, v in value.items() if not str(k).endswith("_by_nct")}
    if isinstance(value, list):
        return [_strip_by_nct(v) for v in value]
    return value


def _collect_by_nct(value, path=()):
    out = []
    if isinstance(value, dict):
        for k, v in value.items():
            if str(k).endswith("_by_nct"):
                out.append((path, k, v))
            else:
                out.extend(_collect_by_nct(v, (*path, k)))
    elif isinstance(value, list):
        for i, v in enumerate(value):
            out.extend(_collect_by_nct(v, (*path, i)))
    return out


def _assert_report_delta(rep_old, rep_new):
    """Iteration 27 report vs an older one: only merged_by_type and its Outcome share of merged differ."""
    assert list(rep_new) == list(rep_old)
    if "results" not in rep_old:
        assert rep_old == rep_new
        return
    old_block, new_block = dict(rep_old["results"]), dict(rep_new["results"])
    by_type = new_block.pop("merged_by_type")
    assert list(by_type) == ["AdverseEvent", "OutcomeAnalysis", "Outcome"]
    assert new_block["merged"] == old_block["merged"] + by_type["Outcome"]
    assert new_block["merged"] == sum(by_type.values())
    new_block["merged"] = old_block["merged"]
    assert new_block == old_block
    assert list(rep_new["results"]) == [
        k for key in old_block for k in ((key, "merged_by_type") if key == "merged" else (key,))
    ]
    assert {k: v for k, v in rep_new.items() if k != "results"} == {
        k: v for k, v in rep_old.items() if k != "results"
    }


def _load_old_enrich(tmp_path, commit, name, monkeypatch):
    path = tmp_path / f"{name}.py"
    path.write_bytes(_baseline_enrich_source(commit))
    old = _load_enrich(name, path)
    monkeypatch.setattr(old.time, "sleep", lambda s: None)
    return old


def _enrich_with(module, directory, bodies, **kwargs):
    with patch.object(module.requests, "get", side_effect=_router(bodies)):
        return module.enrich_graph(directory, **kwargs)


def _registry_edge_keys(links):
    return sorted(
        (l["source"], l["relation_type"], l["target"])
        for l in links if _eattr(l, "source") == "ctgov_results"
    )


@pytest.mark.unit
def test_refresh02_registry_edges_written_once_from_canonical_trial(enrich, tmp_path):
    single = _write_graph(tmp_path / "single", [WITH_RESULTS_A])
    single_report, _ = _run(enrich, single, _all_fixture_bodies(), results=True)
    dup = _write_graph(tmp_path / "dup", [WITH_RESULTS_A], [DUP_NODE])
    dup_report, _ = _run(enrich, dup, _all_fixture_bodies(), results=True)
    s_nodes, s_links = _read_graph(single)
    d_nodes, d_links = _read_graph(dup)

    canonical = "trial:achieve_1"
    assert canonical < TRIAL_A
    assert dup_report["results"] == single_report["results"]
    assert len(_registry_edge_keys(d_links)) == len(_registry_edge_keys(s_links))
    assert sorted(x["id"] for x in _registry_nodes(d_nodes)) == sorted(
        x["id"] for x in _registry_nodes(s_nodes)
    )
    registry_trial_edges = [
        l for l in d_links
        if _eattr(l, "source") == "ctgov_results"
        and l["relation_type"] in ("reports_adverse_event", "has_outcome")
    ]
    assert registry_trial_edges
    assert {l["source"] for l in registry_trial_edges} == {canonical}
    assert not _edges(d_links, "reports_adverse_event", TRIAL_A)
    assert not _edges(d_links, "has_outcome", TRIAL_A)
    assert _nattr(d_nodes[TRIAL_A], "same_trial_as") == canonical
    assert _nattr(d_nodes[canonical], "same_trial_as") is None
    for tid in (TRIAL_A, canonical):
        assert d_nodes[tid]["ct_overall_status"]
    # the same edges as the single-node run, with the canonical source swapped in
    renamed = sorted(
        (canonical if src == TRIAL_A else src, rel, tgt)
        for src, rel, tgt in _registry_edge_keys(s_links)
    )
    assert _registry_edge_keys(d_links) == renamed


@pytest.mark.unit
def test_refresh02_single_nct_graph_has_no_same_trial_as(enrich, tmp_path):
    _write_graph(tmp_path, [WITH_RESULTS_A, WITH_RESULTS_B])
    _run(enrich, tmp_path, _all_fixture_bodies(), results=True)
    nodes, _ = _read_graph(tmp_path)
    assert not [n for n in nodes.values() if _nattr(n, "same_trial_as") is not None]


@pytest.mark.unit
def test_refresh02_duplicate_graph_rerun_is_idempotent(enrich, tmp_path):
    dup = _write_graph(tmp_path / "dup", [WITH_RESULTS_A], [DUP_NODE])
    _run(enrich, dup, _all_fixture_bodies(), results=True)
    first = _normalize_stamps((dup / "graph_data.json").read_bytes())
    report, _ = _run(enrich, dup, _all_fixture_bodies(), results=True)
    assert _normalize_stamps((dup / "graph_data.json").read_bytes()) == first
    assert report["results"]["created"] == 0 and report["results"]["merged"] == 0


@pytest.mark.unit
@pytest.mark.parametrize("variant", ["seeded", "duplicate"])
def test_default_runs_rerun_on_iteration26_graph_is_byte_identical(enrich, tmp_path, monkeypatch, variant):
    old = _load_old_enrich(tmp_path, ITERATION26_COMMIT, "_ct_enrich_iter26_rerun", monkeypatch)
    if variant == "seeded":
        directory = _seeded_graph(tmp_path / "g")
    else:
        directory = _write_graph(tmp_path / "g", [WITH_RESULTS_A], [DUP_NODE])
    bodies = _all_fixture_bodies()
    _enrich_with(old, directory, bodies, results=True)
    before = _normalize_stamps((directory / "graph_data.json").read_bytes())
    report = _enrich_with(enrich, directory, bodies, results=True)
    assert _normalize_stamps((directory / "graph_data.json").read_bytes()) == before
    block = report["results"]
    assert block["created"] == 0 and block["merged"] == 0
    assert block["merged_by_type"] == {"AdverseEvent": 0, "OutcomeAnalysis": 0, "Outcome": 0}
    nodes, _ = _read_graph(directory)
    assert not [n for n in nodes.values() if _nattr(n, "same_trial_as") is not None]


@pytest.mark.unit
def test_default_runs_protocol_only_identical_to_iteration26(enrich, tmp_path, monkeypatch):
    old = _load_old_enrich(tmp_path, ITERATION26_COMMIT, "_ct_enrich_iter26_plain", monkeypatch)
    d_old = _seeded_graph(tmp_path / "old")
    d_new = _seeded_graph(tmp_path / "new")
    bodies = _all_fixture_bodies()
    rep_old = _enrich_with(old, d_old, bodies)
    rep_new = _enrich_with(enrich, d_new, bodies)
    assert _normalize_stamps((d_old / "graph_data.json").read_bytes()) == _normalize_stamps(
        (d_new / "graph_data.json").read_bytes()
    )
    rep_old.pop("generated_at")
    rep_new.pop("generated_at")
    assert rep_old == rep_new and _same_key_order(rep_old, rep_new) and "results" not in rep_new


@pytest.mark.unit
def test_default_runs_fresh_results_delta_is_by_nct_and_merged_by_type(enrich, tmp_path, monkeypatch):
    old = _load_old_enrich(tmp_path, ITERATION26_COMMIT, "_ct_enrich_iter26_delta", monkeypatch)
    d_old = _fully_seeded(enrich, tmp_path / "old")
    d_new = _fully_seeded(enrich, tmp_path / "new")
    bodies = _all_fixture_bodies()
    rep_old = _enrich_with(old, d_old, bodies, results=True)
    rep_new = _enrich_with(enrich, d_new, bodies, results=True)
    g_old = json.loads(_normalize_stamps((d_old / "graph_data.json").read_bytes()))
    g_new = json.loads(_normalize_stamps((d_new / "graph_data.json").read_bytes()))
    stripped = _strip_by_nct(g_new)
    assert g_old == stripped and _same_key_order(g_old, stripped)
    added = _collect_by_nct(g_new)
    assert added
    for path, key, mapping in added:
        holder = g_new
        for step in path:
            holder = holder[step]
        plain = holder[key[: -len("_by_nct")]]
        assert isinstance(mapping, dict) and mapping
        assert plain in mapping.values()
    rep_old.pop("generated_at")
    rep_new.pop("generated_at")
    _assert_report_delta(rep_old, rep_new)
    assert rep_new["results"]["merged_by_type"]["Outcome"] >= 1


def _stub_kg():
    import networkx as nx
    from types import SimpleNamespace

    return SimpleNamespace(graph=nx.MultiDiGraph())


@pytest.mark.unit
def test_refresh03_three_trials_keep_every_conflicting_value(enrich):
    kg = _stub_kg()
    kg.graph.add_node("adverseevent:nausea", name="Nausea", entity_type="AdverseEvent",
                      attributes={"reported_term": "Nausea"})
    counters = enrich._new_counters()
    for nct, term in (("NCT00000001", "nausea"), ("NCT00000002", "NAUSEA "), ("NCT00000003", "Nausea")):
        enrich._merge_into_node(
            kg, "adverseevent:nausea", {"reported_term": term}, nct, counters,
            rename={"reported_term": "registry_term"}, count=True,
        )
    attrs = kg.graph.nodes["adverseevent:nausea"]["attributes"]
    assert attrs["reported_term"] == "Nausea"
    assert attrs["registry_term"] == "nausea"
    assert attrs["registry_term_by_nct"] == {"NCT00000001": "nausea", "NCT00000002": "NAUSEA "}
    assert attrs["ctgov_nct_ids"] == ["NCT00000001", "NCT00000002", "NCT00000003"]
    assert counters["merged"] == 3 and counters["merged_by_type"]["AdverseEvent"] == 3


@pytest.mark.unit
def test_refresh03_plain_attribute_conflicts_across_three_ncts(enrich):
    target = {"enrollment": 10}
    for nct, value in (("NCT00000001", 11), ("NCT00000002", 12), ("NCT00000003", 13)):
        enrich._merge_attrs(target, {"enrollment": value}, nct=nct)
    assert target["registry_enrollment"] == 11
    assert target["registry_enrollment_by_nct"] == {
        "NCT00000001": 11, "NCT00000002": 12, "NCT00000003": 13,
    }
    # without an NCT the legacy behaviour is unchanged
    legacy = {"enrollment": 10}
    enrich._merge_attrs(legacy, {"enrollment": 11})
    assert legacy == {"enrollment": 10, "registry_enrollment": 11}


@pytest.mark.unit
def test_refresh03_held_stat_group_conflicts_keep_by_nct(enrich):
    target = {"p_value": "0.04", "effect_estimate": 1.2}
    attrs = {"p_value": "0.01", "p_value_num": 0.01, "effect_estimate": 1.5, "effect_measure": "Mean Difference"}
    enrich._merge_attrs(target, attrs, groups=enrich.ANALYSIS_STAT_GROUPS, nct="NCT00000001")
    assert target["p_value"] == "0.04" and "effect_measure" not in target
    assert target["registry_p_value"] == "0.01"
    assert target["registry_p_value_by_nct"] == {"NCT00000001": "0.01"}
    assert target["registry_effect_estimate_by_nct"] == {"NCT00000001": 1.5}
    assert target["registry_effect_measure_by_nct"] == {"NCT00000001": "Mean Difference"}
    assert target["registry_p_value_num_by_nct"] == {"NCT00000001": 0.01}


@pytest.mark.unit
def test_refresh03_merged_extracted_edge_keeps_by_nct(enrich):
    kg = _stub_kg()
    kg.graph.add_node("trial:a", entity_type="Trial")
    kg.graph.add_node("ae:x", entity_type="AdverseEvent")
    kg.graph.add_edge(
        "trial:a", "ae:x", key="trial:a|reports_adverse_event|ae:x",
        relation_type="reports_adverse_event", attributes={"n_affected": 999},
    )
    counters = enrich._new_counters()
    for nct, n in (("NCT00000001", 5), ("NCT00000002", 6)):
        assert enrich._upsert_edge(
            kg, "trial:a", "reports_adverse_event", "ae:x", nct, "ev", {"n_affected": n}, counters,
        )
    attrs = kg.graph.edges["trial:a", "ae:x", "trial:a|reports_adverse_event|ae:x"]["attributes"]
    assert attrs["n_affected"] == 999
    assert attrs["registry_n_affected"] == 5
    assert attrs["registry_n_affected_by_nct"] == {"NCT00000001": 5, "NCT00000002": 6}


@pytest.mark.unit
def test_refresh03_registry_node_merge_across_trials_keeps_by_nct(enrich, tmp_path):
    _seeded_graph(tmp_path)
    _run(enrich, tmp_path, _all_fixture_bodies(), results=True)
    nodes, _ = _read_graph(tmp_path)
    with_by_nct = [n for n in nodes.values() if _collect_by_nct(n.get("attributes") or {})]
    assert with_by_nct
    for node in with_by_nct:
        attrs = node["attributes"]
        for _, key, mapping in _collect_by_nct(attrs):
            base = key[: -len("_by_nct")]
            assert attrs[base] in mapping.values()
            assert set(mapping) <= set(attrs["ctgov_nct_ids"])


@pytest.mark.unit
def test_refresh03_report_counts_outcome_merges_by_type(enrich, tmp_path):
    _fully_seeded(enrich, tmp_path)
    outcome_id = "outcome:glycated_hemoglobin_hba1c"
    before = _read_graph(tmp_path)[0][outcome_id]
    report, _ = _run(enrich, tmp_path, _all_fixture_bodies(), results=True)
    block = report["results"]
    keys = list(block)
    assert keys[keys.index("merged") + 1] == "merged_by_type"
    by_type = block["merged_by_type"]
    assert list(by_type) == ["AdverseEvent", "OutcomeAnalysis", "Outcome"]
    assert block["merged"] == sum(by_type.values())
    assert by_type["Outcome"] >= 1
    assert _read_graph(tmp_path)[0][outcome_id] == before  # the extracted Outcome is untouched
    again, _ = _run(enrich, tmp_path, _all_fixture_bodies(), results=True)
    assert again["results"]["merged"] == 0
    assert again["results"]["merged_by_type"] == {"AdverseEvent": 0, "OutcomeAnalysis": 0, "Outcome": 0}


@pytest.mark.unit
def test_refresh03_empty_results_block_has_merged_by_type(enrich):
    block = enrich._empty_results_block()
    keys = list(block)
    assert keys[keys.index("merged") + 1] == "merged_by_type"
    assert block["merged_by_type"] == {"AdverseEvent": 0, "OutcomeAnalysis": 0, "Outcome": 0}


# --- Iteration 28 (999.3): --refresh-results and --cache-ttl-days ---------------

ITERATION27_COMMIT = "9ff9e3d913124dfd97947bcc453edf750708c831"
REFRESH_TERM_CHANGED = "Nausea"
REFRESH_TERM_REMOVED = "Headache"
REFRESH_TERM_ADDED = "Tinnitus"
SEED_P_VALUE = "<.001"


def _mutated_study(nct=WITH_RESULTS_A, new_p_value="0.042"):
    """A copy of a fixture payload with a changed count, an added AE, a removed AE
    and a changed analysis p-value."""
    study = _study(nct)
    results = study["resultsSection"]
    others = results["adverseEventsModule"]["otherEvents"]
    for ev in others:
        if ev["term"] == REFRESH_TERM_CHANGED:
            stat = next(s for s in ev["stats"] if s.get("numAffected"))
            stat["numAffected"] += 5
    removed = next(e for e in others if e["term"] == REFRESH_TERM_REMOVED)
    others.remove(removed)
    added = copy.deepcopy(removed)
    added["term"] = REFRESH_TERM_ADDED
    others.append(added)
    measure = results["outcomeMeasuresModule"]["outcomeMeasures"][0]
    measure["analyses"][0]["pValue"] = new_p_value
    return study


def _bodies(study):
    return {**_all_fixture_bodies(), WITH_RESULTS_A: study}


def _registry_facts(nodes, links):
    node_facts = {
        nid: n.get("attributes") for nid, n in nodes.items()
        if _nattr(n, "source") == "ctgov_results"
    }
    edge_facts = {
        (l["source"], l["relation_type"], l["target"]): (l.get("attributes"), l.get("evidence"))
        for l in links if _eattr(l, "source") == "ctgov_results"
    }
    return node_facts, edge_facts


def _without_withdrawn(facts):
    out = {}
    for key, value in facts.items():
        attrs, rest = (value if isinstance(value, tuple) else (value, None))
        if (attrs or {}).get("ctgov_withdrawn"):
            continue
        out[key] = value
    return out


def _owned_keep(key) -> bool:
    return key in (
        "ctgov_nct_ids", "sources", "ctgov_analysis_ids", "ctgov_arm_groups", "ctgov_withdrawn_by_nct",
    ) or str(key).startswith("registry_")


def _extracted_snapshot(nodes, links):
    """Every attribute of every non-registry node/edge except registry bookkeeping."""
    snap = {}
    for nid, n in nodes.items():
        attrs = n.get("attributes") or {}
        if attrs.get("source") == "ctgov_results":
            continue
        snap[("node", nid)] = {k: copy.deepcopy(v) for k, v in attrs.items() if not _owned_keep(k)}
    for l in links:
        attrs = l.get("attributes") or {}
        if attrs.get("source") == "ctgov_results":
            continue
        key = ("edge", l["source"], l["relation_type"], l["target"])
        snap[key] = {k: copy.deepcopy(v) for k, v in attrs.items() if not _owned_keep(k)}
    return snap


def _seed_with_p_value(enrich, directory):
    _, ae_node, ae_link, _ = _extracted_ae_seed(enrich)
    _, an_nodes, an_links = _extracted_analysis_seed(enrich)
    for node in an_nodes:
        if node["entity_type"] == "OutcomeAnalysis":
            node["attributes"]["p_value"] = SEED_P_VALUE
    return _seeded_graph(directory, [ae_node, *an_nodes], [ae_link, *an_links])


@pytest.mark.unit
def test_refresh01_updates_changed_record_in_place(enrich, tmp_path):
    directory = _seeded_graph(tmp_path / "g")
    _run(enrich, directory, _all_fixture_bodies(), results=True)
    nodes0, links0 = _read_graph(directory)

    mutated = _mutated_study()
    report, _ = _run(enrich, directory, _bodies(mutated), results=True, refresh=True)
    nodes1, links1 = _read_graph(directory)

    # nothing is deleted
    assert set(nodes0) <= set(nodes1) and len(nodes1) > len(nodes0)
    assert {(l["source"], l["relation_type"], l["target"]) for l in links0} <= {
        (l["source"], l["relation_type"], l["target"]) for l in links1
    }
    # the changed term carries the new counts, the added term exists
    nausea = _edges(links1, "reports_adverse_event", TRIAL_A, "adverseevent:nausea")[0]
    before = _edges(links0, "reports_adverse_event", TRIAL_A, "adverseevent:nausea")[0]
    assert _eattr(nausea, "n_affected") == _eattr(before, "n_affected") + 5
    assert _eattr(nausea, "by_group") != _eattr(before, "by_group")
    assert _eattr(nausea, "ctgov_withdrawn") is None
    assert [l for l in links1 if l["relation_type"] == "observed_in"
            and l["source"] == "adverseevent:nausea"] != [
        l for l in links0 if l["relation_type"] == "observed_in" and l["source"] == "adverseevent:nausea"
    ]
    added = _edges(links1, "reports_adverse_event", TRIAL_A, "adverseevent:tinnitus")
    assert added and "adverseevent:tinnitus" in nodes1
    # the removed term is flagged, not deleted
    gone = _edges(links1, "reports_adverse_event", TRIAL_A, "adverseevent:headache")
    assert gone and _eattr(gone[0], "ctgov_withdrawn") is True
    # the AE node is shared with the other trial, so only A's edge is flagged
    assert _nattr(nodes1["adverseevent:headache"], "ctgov_nct_ids") == [WITH_RESULTS_B, WITH_RESULTS_A]
    assert _nattr(nodes1["adverseevent:headache"], "ctgov_withdrawn") is None
    # the analysis p-value was replaced in place on the registry-created analysis
    changed = [n for n in _registry_nodes(nodes1, "OutcomeAnalysis") if _nattr(n, "p_value") == "0.042"]
    assert len(changed) == 1

    refresh = report["results"]["refresh"]
    assert list(refresh) == [
        "trials_refreshed", "updated_nodes", "updated_edges", "withdrawn", "restored",
        "legacy_copies_skipped",
    ]
    assert refresh["trials_refreshed"] == 2
    assert refresh["updated_nodes"] >= 1 and refresh["updated_edges"] >= 2
    assert refresh["withdrawn"] >= 1 and refresh["restored"] == 0
    flagged_edges = [l for l in links1 if _eattr(l, "ctgov_withdrawn")]
    assert refresh["withdrawn"] == len(flagged_edges)
    assert all("adverseevent:headache" in (l["source"], l["target"]) for l in flagged_edges)
    assert not [n for n in nodes1.values() if _nattr(n, "ctgov_withdrawn")]
    assert refresh["legacy_copies_skipped"] == 0
    assert report["results"]["created"] > 0 and report["results"]["merged"] == 0

    # every registry fact equals what a fresh import of the mutated payload gives
    fresh = _seeded_graph(tmp_path / "fresh")
    _run(enrich, fresh, _bodies(mutated), results=True)
    f_nodes, f_links = _read_graph(fresh)
    r_nf, r_ef = _registry_facts(nodes1, links1)
    f_nf, f_ef = _registry_facts(f_nodes, f_links)
    live_nodes, live_edges = _without_withdrawn(r_nf), _without_withdrawn(r_ef)
    # a refresh never removes this NCT from a node it was recorded on
    live_nodes.pop("adverseevent:headache")
    f_nf.pop("adverseevent:headache")
    live_edges = {k: v for k, v in live_edges.items() if "adverseevent:headache" not in (k[0], k[2])}
    f_ef = {k: v for k, v in f_ef.items() if "adverseevent:headache" not in (k[0], k[2])}
    assert live_nodes == f_nf
    assert live_edges == f_ef


@pytest.mark.unit
def test_refresh01_second_refresh_is_byte_identical_and_third_restores(enrich, tmp_path):
    directory = _write_graph(tmp_path / "g", [WITH_RESULTS_A])
    _run(enrich, directory, _all_fixture_bodies(), results=True)
    original = _normalize_stamps((directory / "graph_data.json").read_bytes())
    mutated = _bodies(_mutated_study())

    _run(enrich, directory, mutated, results=True, refresh=True)
    nodes_once, _ = _read_graph(directory)
    assert _nattr(nodes_once["adverseevent:headache"], "ctgov_nct_ids") == [WITH_RESULTS_A]
    assert _nattr(nodes_once["adverseevent:headache"], "ctgov_withdrawn") is True
    once = _normalize_stamps((directory / "graph_data.json").read_bytes())
    assert once != original
    report, _ = _run(enrich, directory, mutated, results=True, refresh=True)
    assert _normalize_stamps((directory / "graph_data.json").read_bytes()) == once
    refresh = report["results"]["refresh"]
    assert refresh["updated_nodes"] == refresh["updated_edges"] == refresh["withdrawn"] == 0
    assert report["results"]["created"] == 0 and report["results"]["merged"] == 0

    report, _ = _run(enrich, directory, _all_fixture_bodies(), results=True, refresh=True)
    nodes, links = _read_graph(directory)
    headache = _edges(links, "reports_adverse_event", TRIAL_A, "adverseevent:headache")[0]
    assert _eattr(headache, "ctgov_withdrawn") is None
    assert _nattr(nodes["adverseevent:headache"], "ctgov_withdrawn") is None
    nausea = _edges(links, "reports_adverse_event", TRIAL_A, "adverseevent:nausea")[0]
    ref_dir = _write_graph(tmp_path / "ref", [WITH_RESULTS_A])
    _run(enrich, ref_dir, _all_fixture_bodies(), results=True)
    _, ref_links = _read_graph(ref_dir)
    ref_nausea = _edges(ref_links, "reports_adverse_event", TRIAL_A, "adverseevent:nausea")[0]
    assert _eattr(nausea, "n_affected") == _eattr(ref_nausea, "n_affected")
    assert _eattr(nausea, "by_group") == _eattr(ref_nausea, "by_group")
    # the added term is withdrawn now, not deleted
    tinnitus = _edges(links, "reports_adverse_event", TRIAL_A, "adverseevent:tinnitus")[0]
    assert _eattr(tinnitus, "ctgov_withdrawn") is True
    assert report["results"]["refresh"]["restored"] >= 2


@pytest.mark.unit
def test_refresh01_without_flag_rerun_matches_iteration27(enrich, tmp_path, monkeypatch):
    """Without --refresh-results a re-run keeps every recorded fact as it is (counts
    are not updated, nothing is flagged); only facts that were never written are added."""
    old = _load_old_enrich(tmp_path, ITERATION27_COMMIT, "_ct_enrich_iter27_norefresh", monkeypatch)
    d_old = _write_graph(tmp_path / "old", [WITH_RESULTS_A])
    d_new = _write_graph(tmp_path / "new", [WITH_RESULTS_A])
    for module, directory in ((old, d_old), (enrich, d_new)):
        _enrich_with(module, directory, _all_fixture_bodies(), results=True)
    first_nodes, first_links = _read_graph(d_new)
    mutated = _bodies(_mutated_study())
    _enrich_with(old, d_old, mutated, results=True)
    report = _enrich_with(enrich, d_new, mutated, results=True)
    assert _normalize_stamps((d_old / "graph_data.json").read_bytes()) == _normalize_stamps(
        (d_new / "graph_data.json").read_bytes()
    )
    assert "refresh" not in report["results"] and list(report["results"]) == REPORT_KEYS
    nodes, links = _read_graph(d_new)
    nausea = _edges(links, "reports_adverse_event", TRIAL_A, "adverseevent:nausea")[0]
    kept = _edges(first_links, "reports_adverse_event", TRIAL_A, "adverseevent:nausea")[0]
    assert _eattr(nausea, "n_affected") == _eattr(kept, "n_affected")
    assert not [n for n in nodes.values() if _nattr(n, "ctgov_withdrawn")]
    assert not [l for l in links if _eattr(l, "ctgov_withdrawn")]


@pytest.mark.unit
def test_refresh01_extracted_data_untouched_and_bookkeeping_only(enrich, tmp_path):
    directory = _seed_with_p_value(enrich, tmp_path / "g")
    _run(enrich, directory, _all_fixture_bodies(), results=True)
    nodes0, links0 = _read_graph(directory)
    snap0 = _extracted_snapshot(nodes0, links0)
    holder = next(
        n for n in nodes0.values()
        if n["entity_type"] == "OutcomeAnalysis" and _nattr(n, "ctgov_analysis_ids")
        and n["id"] == "outcomeanalysis:seed_hba1c_36"
    )
    assert _nattr(holder, "p_value") == SEED_P_VALUE
    assert _nattr(holder, "registry_p_value_by_nct") is None

    mutated = _mutated_study()
    # change the p-value of the analysis the seed merged with
    ref = _hba1c_analysis(enrich, "36 mg Orforglipron")
    for an in mutated["resultsSection"]["outcomeMeasuresModule"]["outcomeMeasures"][0]["analyses"]:
        if an.get("paramValue") == ref["param_value"]:
            an["pValue"] = "0.042"
    report, _ = _run(enrich, directory, _bodies(mutated), results=True, refresh=True)
    nodes1, links1 = _read_graph(directory)
    assert _extracted_snapshot(nodes1, links1) == snap0
    holder1 = nodes1["outcomeanalysis:seed_hba1c_36"]
    assert _nattr(holder1, "p_value") == SEED_P_VALUE
    assert _nattr(holder1, "registry_p_value_by_nct") == {WITH_RESULTS_A: "0.042"}
    assert _nattr(holder1, "registry_p_value") == "0.042"
    assert report["results"]["merged"] == 0

    # equal to the plain value again: the bookkeeping entry for this NCT is dropped
    _run(enrich, directory, _all_fixture_bodies(), results=True, refresh=True)
    nodes2, links2 = _read_graph(directory)
    holder2 = nodes2["outcomeanalysis:seed_hba1c_36"]
    assert _nattr(holder2, "registry_p_value_by_nct") is None
    assert _nattr(holder2, "registry_p_value") is None
    assert _extracted_snapshot(nodes2, links2) == snap0


@pytest.mark.unit
def test_refresh01_extracted_ae_gets_bookkeeping_only(enrich, tmp_path):
    ref, ae_node, ae_link, _ = _extracted_ae_seed(enrich)
    ae_node["attributes"] = {**(ae_node.get("attributes") or {}), "note": "extracted"}
    directory = _seeded_graph(tmp_path / "g", [ae_node], [ae_link])
    _run(enrich, directory, _all_fixture_bodies(), results=True)
    nodes0, links0 = _read_graph(directory)
    snap0 = _extracted_snapshot(nodes0, links0)
    mutated = _mutated_study()
    for ev in mutated["resultsSection"]["adverseEventsModule"]["otherEvents"]:
        if ev["term"] == ref["term"]:
            ev["stats"][0]["numAffected"] = (ev["stats"][0].get("numAffected") or 0) + 3
    _run(enrich, directory, _bodies(mutated), results=True, refresh=True)
    nodes1, links1 = _read_graph(directory)
    assert _extracted_snapshot(nodes1, links1) == snap0
    assert nodes1[ae_node["id"]]["attributes"]["note"] == "extracted"


@pytest.mark.unit
def test_refresh01_payload_without_results_flags_every_registry_fact(enrich, tmp_path):
    directory = _fully_seeded(enrich, tmp_path / "g")
    _run(enrich, directory, _all_fixture_bodies(), results=True)
    nodes0, links0 = _read_graph(directory)
    snap0 = _extracted_snapshot(nodes0, links0)
    gone = _study(WITH_RESULTS_A)
    gone.pop("resultsSection")
    gone["hasResults"] = False

    report, _ = _run(enrich, directory, _bodies(gone), results=True, refresh=True)
    nodes1, links1 = _read_graph(directory)
    assert set(nodes0) <= set(nodes1) and len(links1) >= len(links0)
    assert _extracted_snapshot(nodes1, links1) == snap0
    assert report["results"]["trials_without_results"] >= 1
    assert report["results"]["refresh"]["trials_refreshed"] >= 1
    owned_edges = [
        l for l in links1
        if _eattr(l, "source") == "ctgov_results" and (_eattr(l, "ctgov_nct_ids") or [None])[0] == WITH_RESULTS_A
    ]
    assert owned_edges and all(_eattr(l, "ctgov_withdrawn") is True for l in owned_edges)
    owned_nodes = [
        n for n in _registry_nodes(nodes1) if _nattr(n, "ctgov_nct_ids") == [WITH_RESULTS_A]
    ]
    assert owned_nodes and all(_nattr(n, "ctgov_withdrawn") is True for n in owned_nodes)
    assert report["results"]["refresh"]["withdrawn"] == len(owned_edges) + len(owned_nodes)
    # another NCT's facts and shared extracted data are not flagged
    assert not [l for l in links1 if (_eattr(l, "ctgov_nct_ids") or [None])[0] == WITH_RESULTS_B
                and _eattr(l, "ctgov_withdrawn")]
    # WR-02: extracted facts the registry merged into record this NCT's withdrawal
    # (bookkeeping only) and are never flagged ctgov_withdrawn
    merged_nodes = [
        n for n in nodes1.values()
        if _nattr(n, "source") != "ctgov_results" and WITH_RESULTS_A in (_nattr(n, "ctgov_nct_ids") or [])
    ]
    merged_edges = [
        l for l in links1
        if _eattr(l, "source") != "ctgov_results" and WITH_RESULTS_A in (_eattr(l, "ctgov_nct_ids") or [])
    ]
    assert {"outcomeanalysis:seed_hba1c_36"} <= {n["id"] for n in merged_nodes}
    assert merged_edges
    for item in (*merged_nodes, *merged_edges):
        assert (item.get("attributes") or {}).get("ctgov_withdrawn_by_nct") == {WITH_RESULTS_A: True}
        assert (item.get("attributes") or {}).get("ctgov_withdrawn") is None
    # the registry payload coming back drops the entries again
    _run(enrich, directory, _all_fixture_bodies(), results=True, refresh=True)
    nodes2, links2 = _read_graph(directory)
    assert not [n for n in nodes2.values() if _nattr(n, "ctgov_withdrawn_by_nct")]
    assert not [l for l in links2 if _eattr(l, "ctgov_withdrawn_by_nct")]
    assert not [n for n in nodes2.values() if _nattr(n, "ctgov_withdrawn")]


@pytest.mark.unit
def test_refresh01_floor_conflict_leaves_adverse_events_alone(enrich, tmp_path):
    directory = _write_graph(tmp_path / "g", [WITH_RESULTS_A])
    _run(enrich, directory, _all_fixture_bodies(), results=True)
    _, links0 = _read_graph(directory)
    ae0 = [l for l in links0 if l["relation_type"] in ("reports_adverse_event", "observed_in")]
    report, _ = _run(
        enrich, directory, _bodies(_mutated_study()), results=True, refresh=True, serious_min_pct=10,
    )
    nodes1, links1 = _read_graph(directory)
    ae1 = [l for l in links1 if l["relation_type"] in ("reports_adverse_event", "observed_in")]
    assert ae1 == ae0
    assert report["results"]["serious_min_pct_conflicts"] == {WITH_RESULTS_A: [0.0]}
    assert not [n for n in nodes1.values() if n["entity_type"] == "AdverseEvent" and _nattr(n, "ctgov_withdrawn")]


@pytest.mark.unit
def test_refresh01_legacy_duplicate_trial_copies_are_skipped(enrich, tmp_path, monkeypatch):
    old = _load_old_enrich(tmp_path, ITERATION26_COMMIT, "_ct_enrich_iter26_legacy", monkeypatch)
    directory = _write_graph(tmp_path / "g", [WITH_RESULTS_A], [DUP_NODE])
    _enrich_with(old, directory, _all_fixture_bodies(), results=True)
    _, links0 = _read_graph(directory)
    legacy = [l for l in links0 if l["source"] == TRIAL_A and l["relation_type"] == "reports_adverse_event"]
    assert legacy
    report, _ = _run(enrich, directory, _bodies(_mutated_study()), results=True, refresh=True)
    _, links1 = _read_graph(directory)
    assert report["results"]["refresh"]["legacy_copies_skipped"] >= len(legacy)
    for l in links1:
        if l["source"] == TRIAL_A and l["relation_type"] == "reports_adverse_event":
            assert _eattr(l, "ctgov_withdrawn") is None


@pytest.mark.unit
def test_refresh01_requires_results(enrich, tmp_path):
    _write_graph(tmp_path, [WITH_RESULTS_A])
    with pytest.raises(ValueError):
        _run(enrich, tmp_path, _all_fixture_bodies(), refresh=True)


def _age_cache(path, days):
    stamp = time.time() - days * 86400
    os.utime(path, (stamp, stamp))


@pytest.mark.unit
def test_cache_ttl_expired_file_is_refetched_fresh_one_is_not(enrich, tmp_path):
    cache = tmp_path / "cache"
    seed = _write_graph(tmp_path / "g0", [WITH_RESULTS_A, WITH_RESULTS_B])
    _run(enrich, seed, _all_fixture_bodies(), results=True, cache_dir=cache)
    _age_cache(cache / f"{WITH_RESULTS_A}.json", 2)
    _age_cache(cache / f"{WITH_RESULTS_B}.json", 1 / 24)

    directory = _write_graph(tmp_path / "g1", [WITH_RESULTS_A, WITH_RESULTS_B])
    report, m = _run(
        enrich, directory, _bodies(_mutated_study()), results=True, cache_dir=cache, cache_ttl_days=1,
    )
    assert _ctgov_calls(m) == 1
    assert report["cache"] == {
        "ttl_days": 1.0, "expired": 1, "refetched": 1, "stale_used": 0, "stale_after_not_found": 0,
    }
    assert list(report)[-1] == "cache"
    cached = json.loads((cache / f"{WITH_RESULTS_A}.json").read_text())
    assert cached == _mutated_study()
    assert time.time() - (cache / f"{WITH_RESULTS_A}.json").stat().st_mtime < 3600

    # no TTL: nothing expires, no cache block
    _age_cache(cache / f"{WITH_RESULTS_A}.json", 400)
    again = _write_graph(tmp_path / "g2", [WITH_RESULTS_A, WITH_RESULTS_B])
    report, m = _run(enrich, again, _all_fixture_bodies(), results=True, cache_dir=cache)
    assert _ctgov_calls(m) == 0 and "cache" not in report


@pytest.mark.unit
def test_cache_ttl_zero_refetches_every_cached_trial(enrich, tmp_path):
    cache = tmp_path / "cache"
    _run(enrich, _write_graph(tmp_path / "g0", [WITH_RESULTS_A, WITH_RESULTS_B]),
         _all_fixture_bodies(), results=True, cache_dir=cache)
    report, m = _run(
        enrich, _write_graph(tmp_path / "g1", [WITH_RESULTS_A, WITH_RESULTS_B]),
        _all_fixture_bodies(), results=True, cache_dir=cache, cache_ttl_days=0,
    )
    assert _ctgov_calls(m) == 2
    assert report["cache"]["expired"] == 2 and report["cache"]["refetched"] == 2


@pytest.mark.unit
def test_cache_ttl_failed_refetch_falls_back_to_stale_payload(enrich, tmp_path):
    cache = tmp_path / "cache"
    _run(enrich, _write_graph(tmp_path / "g0", [WITH_RESULTS_A]),
         _all_fixture_bodies(), results=True, cache_dir=cache)
    _age_cache(cache / f"{WITH_RESULTS_A}.json", 5)
    directory = _write_graph(tmp_path / "g1", [WITH_RESULTS_A])
    report, m = _run(
        enrich, directory, {WITH_RESULTS_A: "500"}, results=True, cache_dir=cache, cache_ttl_days=1,
    )
    assert _ctgov_calls(m) == 1
    assert report["cache"] == {
        "ttl_days": 1.0, "expired": 1, "refetched": 0, "stale_used": 1, "stale_after_not_found": 0,
    }
    assert report["trials"]["enriched"] == 1 and report["results"]["trials_with_results"] == 1
    assert json.loads((cache / f"{WITH_RESULTS_A}.json").read_text()) == _study(WITH_RESULTS_A)


@pytest.mark.unit
@pytest.mark.parametrize("bad", [-1, float("nan"), float("inf"), True, "7"])
def test_cache_ttl_rejects_invalid_values(enrich, tmp_path, bad):
    _write_graph(tmp_path / "g", [WITH_RESULTS_A])
    with pytest.raises(ValueError):
        _run(enrich, tmp_path / "g", _all_fixture_bodies(), cache_dir=tmp_path / "c", cache_ttl_days=bad)


@pytest.mark.unit
def test_cache_ttl_needs_cache_dir(enrich, tmp_path):
    _write_graph(tmp_path / "g", [WITH_RESULTS_A])
    with pytest.raises(ValueError):
        _run(enrich, tmp_path / "g", _all_fixture_bodies(), cache_ttl_days=1)


@pytest.mark.unit
def test_refresh01_cli_guards(tmp_path):
    def cli(*args):
        return subprocess.run(
            [sys.executable, str(_module_path()), str(tmp_path), *args],
            capture_output=True, text=True, timeout=60,
        )

    bad = cli("--refresh-results")
    assert bad.returncode == 2 and "--results" in bad.stderr
    bad = cli("--cache-ttl-days", "1")
    assert bad.returncode == 2 and "--cache-dir" in bad.stderr
    bad = cli("--cache-dir", str(tmp_path / "c"), "--cache-ttl-days", "-1")
    assert bad.returncode == 2 and "cache_ttl_days" in bad.stderr
    bad = cli("--cache-dir", str(tmp_path / "c"), "--cache-ttl-days", "nan")
    assert bad.returncode == 2 and "cache_ttl_days" in bad.stderr


@pytest.mark.unit
@pytest.mark.parametrize("variant", ["protocol_only", "fresh_results", "rerun"])
def test_default_runs_identical_to_iteration27(enrich, tmp_path, monkeypatch, variant):
    old = _load_old_enrich(tmp_path, ITERATION27_COMMIT, "_ct_enrich_iter27", monkeypatch)
    bodies = _all_fixture_bodies()
    d_old = _fully_seeded(enrich, tmp_path / "old")
    d_new = _fully_seeded(enrich, tmp_path / "new")
    kwargs = {} if variant == "protocol_only" else {"results": True}
    if variant == "rerun":
        _enrich_with(old, d_old, bodies, results=True)
        _enrich_with(old, d_new, bodies, results=True)
    rep_old = _enrich_with(old, d_old, bodies, **kwargs)
    rep_new = _enrich_with(enrich, d_new, bodies, **kwargs)
    assert _normalize_stamps((d_old / "graph_data.json").read_bytes()) == _normalize_stamps(
        (d_new / "graph_data.json").read_bytes()
    )
    rep_old.pop("generated_at")
    rep_new.pop("generated_at")
    assert rep_old == rep_new
    assert _same_key_order(rep_old, rep_new) and list(rep_old) == list(rep_new)
    assert "cache" not in rep_new and "refresh" not in rep_new.get("results", {})


# --- Iteration 29 (999.3): --refresh-results on an unchanged payload is a no-op ---

ITERATION28_COMMIT = "c7aa6f9167b675063b22ed164c53ebd7920c6465"
COLLIDING_MEASURE = 0
COLLIDING_TIME_FRAME = "Week 99"


def _colliding_study():
    """Study A with a second outcome measure that has the title and unit of
    measure 0 but another time frame and type (a title collision in one trial)."""
    study = _study(WITH_RESULTS_A)
    measures = study["resultsSection"]["outcomeMeasuresModule"]["outcomeMeasures"]
    extra = copy.deepcopy(measures[COLLIDING_MEASURE])
    extra["timeFrame"] = COLLIDING_TIME_FRAME
    extra["type"] = "SECONDARY" if str(extra.get("type")).upper() == "PRIMARY" else "PRIMARY"
    measures.append(extra)
    return study


def _shared_placebo_graph(directory: Path):
    """Seeded graph whose placebo cohort is enrolled by both trials, so the
    registry observed_in edges on it are shared by two NCTs."""
    return _seeded_graph(directory, extra_links=[_link(TRIAL_B, "enrolls", COHORT_PLACEBO)])


def _shared_observed_in(links):
    return [
        l for l in _edges(links, "observed_in", tgt=COHORT_PLACEBO)
        if _eattr(l, "source") == "ctgov_results" and len(_eattr(l, "ctgov_nct_ids") or []) > 1
    ]


def _assert_refresh_noop(enrich, directory, bodies):
    before = _normalize_stamps((directory / "graph_data.json").read_bytes())
    report, _ = _run(enrich, directory, bodies, results=True, refresh=True)
    assert _normalize_stamps((directory / "graph_data.json").read_bytes()) == before
    refresh = report["results"]["refresh"]
    assert refresh["trials_refreshed"] >= 1
    assert (refresh["updated_nodes"], refresh["updated_edges"], refresh["withdrawn"], refresh["restored"]) == (0, 0, 0, 0)
    assert report["results"]["created"] == 0 and report["results"]["merged"] == 0
    return report


@pytest.mark.unit
def test_refresh01_title_colliding_measures_keep_first_measure(enrich, tmp_path):
    study = _colliding_study()
    first = study["resultsSection"]["outcomeMeasuresModule"]["outcomeMeasures"][COLLIDING_MEASURE]
    bodies = {**_all_fixture_bodies(), WITH_RESULTS_A: study}
    directory = _write_graph(tmp_path / "g", [WITH_RESULTS_A, WITH_RESULTS_B])
    _run(enrich, directory, bodies, results=True)
    nodes, _ = _read_graph(directory)
    outcome = [
        n for n in _registry_nodes(nodes, "Outcome")
        if _same_title(n["name"], first["title"]) and WITH_RESULTS_A in (_nattr(n, "ctgov_nct_ids") or [])
    ]
    assert len(outcome) == 1
    assert _nattr(outcome[0], "timeframe") == first["timeFrame"]

    _assert_refresh_noop(enrich, directory, bodies)
    nodes, _ = _read_graph(directory)
    assert _nattr(nodes[outcome[0]["id"]], "timeframe") == first["timeFrame"]
    assert _nattr(nodes[outcome[0]["id"]], "endpoint_type") == _nattr(outcome[0], "endpoint_type")


def _same_title(a, b) -> bool:
    return " ".join(str(a).lower().split()) == " ".join(str(b).lower().split())


@pytest.mark.unit
def test_refresh01_shared_cohort_edges_get_no_new_bookkeeping(enrich, tmp_path):
    directory = _shared_placebo_graph(tmp_path / "g")
    _run(enrich, directory, _all_fixture_bodies(), results=True)
    _, links = _read_graph(directory)
    shared = _shared_observed_in(links)
    assert shared  # the fixture really has registry edges shared by both NCTs
    _assert_refresh_noop(enrich, directory, _all_fixture_bodies())
    _, links1 = _read_graph(directory)
    assert _shared_observed_in(links1) == shared


@pytest.mark.unit
def test_refresh01_unchanged_payload_is_noop_on_fully_seeded_graph(enrich, tmp_path):
    """Title collision, shared cohort, extracted AE and analysis seeds together."""
    _, ae_node, ae_link, _ = _extracted_ae_seed(enrich)
    _, an_nodes, an_links = _extracted_analysis_seed(enrich)
    directory = _seeded_graph(
        tmp_path / "g", [ae_node, *an_nodes],
        [ae_link, *an_links, _link(TRIAL_B, "enrolls", COHORT_PLACEBO)],
    )
    bodies = {**_all_fixture_bodies(), WITH_RESULTS_A: _colliding_study()}
    _run(enrich, directory, bodies, results=True)
    _assert_refresh_noop(enrich, directory, bodies)
    _assert_refresh_noop(enrich, directory, bodies)


@pytest.mark.unit
def test_refresh01_first_import_and_refresh_agree_on_shared_edges(enrich, tmp_path):
    """A refresh with a changed payload of the NCT that does not own a shared
    registry edge leaves that edge as a first import of the changed payload has it."""
    mutated = _bodies(_mutated_study())
    refreshed = _shared_placebo_graph(tmp_path / "r")
    _run(enrich, refreshed, _all_fixture_bodies(), results=True)
    _run(enrich, refreshed, mutated, results=True, refresh=True)
    fresh = _shared_placebo_graph(tmp_path / "f")
    _run(enrich, fresh, mutated, results=True)
    _, r_links = _read_graph(refreshed)
    _, f_links = _read_graph(fresh)
    key = lambda l: (l["source"], l["target"])
    r_shared = {key(l): l.get("attributes") for l in _shared_observed_in(r_links) if _eattr(l, "ctgov_nct_ids")[0] != WITH_RESULTS_A}
    f_shared = {key(l): l.get("attributes") for l in _shared_observed_in(f_links) if _eattr(l, "ctgov_nct_ids")[0] != WITH_RESULTS_A}
    # a refresh never removes this NCT from an edge it was recorded on
    gone = f"adverseevent:{REFRESH_TERM_REMOVED.lower()}"
    r_shared = {k: v for k, v in r_shared.items() if k[0] != gone}
    f_shared = {k: v for k, v in f_shared.items() if k[0] != gone}
    assert r_shared and r_shared == f_shared


@pytest.mark.unit
@pytest.mark.parametrize("variant", ["protocol_only", "fresh_results", "rerun", "colliding_shared"])
def test_default_runs_identical_to_iteration28(enrich, tmp_path, monkeypatch, variant):
    old = _load_old_enrich(tmp_path, ITERATION28_COMMIT, "_ct_enrich_iter28", monkeypatch)
    bodies = _all_fixture_bodies()
    if variant == "colliding_shared":
        bodies = {**bodies, WITH_RESULTS_A: _colliding_study()}
        d_old = _shared_placebo_graph(tmp_path / "old")
        d_new = _shared_placebo_graph(tmp_path / "new")
    else:
        d_old = _fully_seeded(enrich, tmp_path / "old")
        d_new = _fully_seeded(enrich, tmp_path / "new")
    kwargs = {} if variant == "protocol_only" else {"results": True}
    if variant == "rerun":
        _enrich_with(old, d_old, bodies, results=True)
        _enrich_with(old, d_new, bodies, results=True)
    rep_old = _enrich_with(old, d_old, bodies, **kwargs)
    rep_new = _enrich_with(enrich, d_new, bodies, **kwargs)
    assert _normalize_stamps((d_old / "graph_data.json").read_bytes()) == _normalize_stamps(
        (d_new / "graph_data.json").read_bytes()
    )
    rep_old.pop("generated_at")
    rep_new.pop("generated_at")
    assert rep_old == rep_new and _same_key_order(rep_old, rep_new)


# --- Iteration 30: 12-REVIEW fixes (CR-01..03, WR-01..05, IN-01, IN-03, SA-02) ---

ITERATION29_COMMIT = "466cf7238bff126ebc3bdf0678ad74682fcf54a7"
SHARED_TERM = "Ectopic pregnancy"  # reported by both fixture trials
BOTH_TABLES_TERM = "Abdominal pain"  # serious and other in WITH_RESULTS_B


def _without_term(nct, term, study=None):
    study = study or _study(nct)
    module = study["resultsSection"]["adverseEventsModule"]
    for table in ("seriousEvents", "otherEvents"):
        module[table] = [e for e in module.get(table) or [] if e["term"] != term]
    return study


def _shared_graph(enrich, directory: Path, owner_first: bool):
    """Both fixture trials report SHARED_TERM. owner_first: A was imported on its
    own first, so A owns the shared registry facts; else both were imported in
    one run and B (the lower NCT) owns them."""
    if owner_first:
        _write_graph(directory, [WITH_RESULTS_A])
        _run(enrich, directory, _all_fixture_bodies(), results=True)
        graph = json.loads((directory / "graph_data.json").read_text())
        graph["nodes"].append({"id": TRIAL_B, "name": WITH_RESULTS_B, "entity_type": "Trial"})
        (directory / "graph_data.json").write_text(json.dumps(graph))
    else:
        _write_graph(directory, [WITH_RESULTS_A, WITH_RESULTS_B])
    _run(enrich, directory, _all_fixture_bodies(), results=True)
    return directory


def _shared_term_facts(nodes, links):
    """(AE id, registry edges on it that two NCTs support) for SHARED_TERM."""
    ae = f"adverseevent:{SHARED_TERM.lower().replace(' ', '_')}"
    shared_edges = [
        l for l in links
        if (l["source"] == ae or l["target"] == ae) and len(_eattr(l, "ctgov_nct_ids") or []) > 1
    ]
    return ae, shared_edges


@pytest.mark.unit
@pytest.mark.parametrize("owner_first", [True, False], ids=["a_owns", "b_owns"])
def test_refresh01_shared_fact_withdrawn_only_when_every_nct_withdrew(enrich, tmp_path, owner_first):
    """CR-01: a registry fact two NCTs support is withdrawn only when both payloads
    drop it, whichever NCT owns it and in whatever order they are refreshed."""
    directory = _shared_graph(enrich, tmp_path / "g", owner_first)
    nodes0, links0 = _read_graph(directory)
    ae, shared0 = _shared_term_facts(nodes0, links0)
    owner = WITH_RESULTS_A if owner_first else WITH_RESULTS_B
    assert shared0 and {(_eattr(l, "ctgov_nct_ids") or [None])[0] for l in shared0} == {owner}
    assert _nattr(nodes0[ae], "ctgov_nct_ids")[0] == owner

    # A drops the term, B still reports it: nothing shared is flagged
    report, _ = _run(
        enrich, directory, _bodies(_without_term(WITH_RESULTS_A, SHARED_TERM)), results=True, refresh=True,
    )
    nodes1, links1 = _read_graph(directory)
    _, shared1 = _shared_term_facts(nodes1, links1)
    assert not [l for l in links1 if _eattr(l, "ctgov_withdrawn") and len(_eattr(l, "ctgov_nct_ids")) > 1]
    assert not [n for n in nodes1.values() if _nattr(n, "ctgov_withdrawn")]
    assert shared1 and all(_eattr(l, "ctgov_withdrawn_by_nct") == {WITH_RESULTS_A: True} for l in shared1)
    assert _nattr(nodes1[ae], "ctgov_withdrawn_by_nct") == {WITH_RESULTS_A: True}
    # A's own edge to the term is withdrawn
    own = _edges(links1, "reports_adverse_event", TRIAL_A, ae)
    assert own and _eattr(own[0], "ctgov_withdrawn") is True
    refresh = report["results"]["refresh"]
    assert refresh["withdrawn"] == len([l for l in links1 if _eattr(l, "ctgov_withdrawn")])
    assert refresh["updated_edges"] >= len(shared1) and refresh["updated_nodes"] >= 1

    # B fails to fetch while A still lacks the term: still not flagged
    failing = {k: v for k, v in _bodies(_without_term(WITH_RESULTS_A, SHARED_TERM)).items() if k != WITH_RESULTS_B}
    report, _ = _run(enrich, directory, failing, results=True, refresh=True)
    assert report["results"]["results_failed"] == 1
    _, links_f = _read_graph(directory)
    assert not [l for l in links_f if _eattr(l, "ctgov_withdrawn") and len(_eattr(l, "ctgov_nct_ids")) > 1]

    # both drop it: the shared facts are flagged, with both NCTs recorded
    both = {
        **_all_fixture_bodies(),
        WITH_RESULTS_A: _without_term(WITH_RESULTS_A, SHARED_TERM),
        WITH_RESULTS_B: _without_term(WITH_RESULTS_B, SHARED_TERM),
    }
    _run(enrich, directory, both, results=True, refresh=True)
    nodes2, links2 = _read_graph(directory)
    _, shared2 = _shared_term_facts(nodes2, links2)
    for item in (*shared2, nodes2[ae]):
        attrs = item.get("attributes") or {}
        assert attrs.get("ctgov_withdrawn") is True
        assert attrs.get("ctgov_withdrawn_by_nct") == {WITH_RESULTS_A: True, WITH_RESULTS_B: True}

    # A reports it again: the flag goes, only B's entry is left
    only_b = {**_all_fixture_bodies(), WITH_RESULTS_B: _without_term(WITH_RESULTS_B, SHARED_TERM)}
    report, _ = _run(enrich, directory, only_b, results=True, refresh=True)
    nodes3, links3 = _read_graph(directory)
    _, shared3 = _shared_term_facts(nodes3, links3)
    for item in (*shared3, nodes3[ae]):
        attrs = item.get("attributes") or {}
        assert attrs.get("ctgov_withdrawn") is None
        assert attrs.get("ctgov_withdrawn_by_nct") == {WITH_RESULTS_B: True}
    assert report["results"]["refresh"]["restored"] >= len(shared3) + 1

    # both report it: no withdrawal bookkeeping is left on the shared facts
    _run(enrich, directory, _all_fixture_bodies(), results=True, refresh=True)
    nodes4, links4 = _read_graph(directory)
    _, shared4 = _shared_term_facts(nodes4, links4)
    for item in (*shared4, nodes4[ae]):
        attrs = item.get("attributes") or {}
        assert "ctgov_withdrawn" not in attrs and "ctgov_withdrawn_by_nct" not in attrs
    assert {k: v for k, v in _registry_facts(nodes4, links4)[1].items() if k[0] == ae or k[2] == ae} == {
        k: v for k, v in _registry_facts(nodes0, links0)[1].items() if k[0] == ae or k[2] == ae
    }


def _b_without_serious_and_p_value():
    """WITH_RESULTS_B with BOTH_TABLES_TERM only in the other table, and the
    p-value of its first analysis removed."""
    study = _study(WITH_RESULTS_B)
    module = study["resultsSection"]["adverseEventsModule"]
    module["seriousEvents"] = [e for e in module["seriousEvents"] if e["term"] != BOTH_TABLES_TERM]
    analysis = next(
        an for m in study["resultsSection"]["outcomeMeasuresModule"]["outcomeMeasures"]
        for an in m.get("analyses") or [] if an.get("pValue")
    )
    analysis.pop("pValue")
    return study


@pytest.mark.unit
def test_refresh01_owned_fact_drops_attributes_missing_from_payload(enrich, tmp_path):
    """CR-02: a registry-owned fact matches the new payload exactly, including the
    attributes it no longer produces."""
    directory = _write_graph(tmp_path / "g", [WITH_RESULTS_A, WITH_RESULTS_B])
    _run(enrich, directory, _all_fixture_bodies(), results=True)
    ae = f"adverseevent:{BOTH_TABLES_TERM.lower().replace(' ', '_')}"
    _, links0 = _read_graph(directory)
    edge0 = _edges(links0, "reports_adverse_event", TRIAL_B, ae)[0]
    assert _eattr(edge0, "count_basis") == "serious+other" and _eattr(edge0, "by_seriousness")
    nodes0, _ = _read_graph(directory)
    with_p = [n for n in _registry_nodes(nodes0, "OutcomeAnalysis")
              if _nattr(n, "ctgov_nct_ids") == [WITH_RESULTS_B] and _nattr(n, "p_value")]
    assert with_p

    mutated = {**_all_fixture_bodies(), WITH_RESULTS_B: _b_without_serious_and_p_value()}
    report, _ = _run(enrich, directory, mutated, results=True, refresh=True)
    nodes1, links1 = _read_graph(directory)
    edge1 = _edges(links1, "reports_adverse_event", TRIAL_B, ae)[0]
    assert _eattr(edge1, "seriousness") == "other"
    assert _eattr(edge1, "count_basis") is None and _eattr(edge1, "by_seriousness") is None

    fresh = _write_graph(tmp_path / "fresh", [WITH_RESULTS_A, WITH_RESULTS_B])
    _run(enrich, fresh, mutated, results=True)
    f_nodes, f_links = _read_graph(fresh)
    assert edge1.get("attributes") == _edges(f_links, "reports_adverse_event", TRIAL_B, ae)[0].get("attributes")
    # the analysis without a p-value lost every p-value attribute
    dropped = [n for n in _registry_nodes(nodes1, "OutcomeAnalysis")
               if _nattr(n, "ctgov_nct_ids") == [WITH_RESULTS_B] and n["id"] in {x["id"] for x in with_p}
               and _nattr(n, "p_value") is None]
    assert len(dropped) == 1
    assert not {"p_value", "p_value_num", "p_value_qualifier"} & set(dropped[0]["attributes"])
    assert dropped[0]["attributes"] == f_nodes[dropped[0]["id"]]["attributes"]
    refresh = report["results"]["refresh"]
    assert refresh["updated_nodes"] >= 1 and refresh["updated_edges"] >= 1
    # every live registry fact of B equals a fresh import of the changed payload
    r_nf, r_ef = _registry_facts(nodes1, links1)
    f_nf, f_ef = _registry_facts(f_nodes, f_links)
    assert {k: v for k, v in r_nf.items() if (v or {}).get("ctgov_nct_ids") == [WITH_RESULTS_B]} == {
        k: v for k, v in f_nf.items() if (v or {}).get("ctgov_nct_ids") == [WITH_RESULTS_B]
    }
    _assert_refresh_noop(enrich, directory, mutated)


@pytest.mark.unit
def test_refresh01_shared_registry_node_keeps_attribute_another_nct_filled(enrich):
    """CR-02 limit: on a registry node other NCTs also support, an attribute the
    owner's payload no longer has stays (another NCT's import may have filled it)."""
    target = {
        "source": "ctgov_results", "ctgov_nct_ids": [WITH_RESULTS_A, WITH_RESULTS_B],
        "reported_term": "x", "meddra_version": "27.0",
    }
    assert enrich._refresh_attrs(dict(target), {"reported_term": "x"}, None, (), WITH_RESULTS_A, drop_absent=False) is False
    single = {**target, "ctgov_nct_ids": [WITH_RESULTS_A]}
    assert enrich._refresh_attrs(single, {"reported_term": "x"}, None, (), WITH_RESULTS_A) is True
    assert "meddra_version" not in single and single["reported_term"] == "x"


@pytest.mark.unit
def test_refresh02_extracted_ae_edge_on_non_canonical_trial_is_merged_into(enrich, tmp_path):
    """CR-03: registry counts merge into an extracted reports_adverse_event edge on a
    non-canonical Trial node of the NCT; no parallel canonical edge is written."""
    nausea = "adverseevent:nausea"
    ae = {"id": nausea, "name": "nausea", "entity_type": "AdverseEvent", "attributes": {}}
    directory = _write_graph(
        tmp_path / "g", [WITH_RESULTS_A], [DUP_NODE, ae], [_link(TRIAL_A, "reports_adverse_event", nausea)],
    )
    report, _ = _run(enrich, directory, _all_fixture_bodies(), results=True)
    _, links = _read_graph(directory)
    to_nausea = [l for l in links if l["relation_type"] == "reports_adverse_event" and l["target"] == nausea]
    assert len(to_nausea) == 1 and to_nausea[0]["source"] == TRIAL_A
    merged = to_nausea[0]
    assert _eattr(merged, "source") is None
    assert "ctgov_results" in _eattr(merged, "sources") and _eattr(merged, "ctgov_nct_ids") == [WITH_RESULTS_A]
    assert isinstance(_eattr(merged, "n_affected"), int)
    assert report["results"]["merged_by_type"]["AdverseEvent"] >= 1
    # every other registry AE edge is still written once, from the canonical node
    other = [l for l in links if l["relation_type"] == "reports_adverse_event" and l["target"] != nausea]
    assert other and {l["source"] for l in other} == {"trial:achieve_1"}

    # a refresh records the changed count on the same edge and writes no copy
    _run(enrich, directory, _bodies(_mutated_study()), results=True, refresh=True)
    _, links1 = _read_graph(directory)
    to_nausea1 = [l for l in links1 if l["relation_type"] == "reports_adverse_event" and l["target"] == nausea]
    assert len(to_nausea1) == 1 and to_nausea1[0]["source"] == TRIAL_A
    assert _eattr(to_nausea1[0], "registry_n_affected_by_nct") == {
        WITH_RESULTS_A: _eattr(merged, "n_affected") + 5
    }
    assert _eattr(to_nausea1[0], "ctgov_withdrawn_by_nct") is None
    _assert_refresh_noop(enrich, directory, _bodies(_mutated_study()))


def _by_group_bumped(term):
    """WITH_RESULTS_A with one per-arm count of term raised by one."""
    mutated = _study(WITH_RESULTS_A)
    for ev in mutated["resultsSection"]["adverseEventsModule"]["otherEvents"]:
        if ev["term"] == term:
            stat = next(s for s in ev["stats"] if s.get("numAffected"))
            stat["numAffected"] += 1
    return mutated


@pytest.mark.unit
def test_refresh01_merged_extracted_edge_by_group_follows_first_import_rule(enrich, tmp_path):
    """12-REVIEW.iter2 WR-02 (replaces the iteration-30 WR-01 bookkeeping): a dict
    attribute of a merged extracted edge is refreshed like a first import fills it.
    A changed per-arm count is not recorded as registry_by_group (a first import
    records none either), the scalar n_affected bookkeeping still shows the change,
    and an iteration-30 registry_by_group entry of this NCT is dropped."""
    ref, ae_node, ae_link, _ = _extracted_ae_seed(enrich)
    directory = _seeded_graph(tmp_path / "g", [ae_node], [ae_link])
    _run(enrich, directory, _all_fixture_bodies(), results=True)
    _, links0 = _read_graph(directory)
    edge0 = _edges(links0, "reports_adverse_event", TRIAL_A, ae_node["id"])[0]
    by_group0 = _eattr(edge0, "by_group")
    assert by_group0 and _eattr(edge0, "source") is None
    n0 = _eattr(edge0, "registry_n_affected_by_nct")[WITH_RESULTS_A]

    mutated = _by_group_bumped(ref["term"])
    _run(enrich, directory, _bodies(mutated), results=True, refresh=True)
    _, links1 = _read_graph(directory)
    edge1 = _edges(links1, "reports_adverse_event", TRIAL_A, ae_node["id"])[0]
    assert _eattr(edge1, "by_group") == by_group0
    assert _eattr(edge1, "registry_by_group") is None and _eattr(edge1, "registry_by_group_by_nct") is None
    assert _eattr(edge1, "registry_n_affected_by_nct") == {WITH_RESULTS_A: n0 + 1}
    _assert_refresh_noop(enrich, directory, _bodies(mutated))

    # an entry an iteration-30 refresh wrote is dropped by the next refresh
    graph = json.loads((directory / "graph_data.json").read_text())
    for link in graph["links"]:
        if link["source"] == TRIAL_A and link["target"] == ae_node["id"]:
            link["attributes"]["registry_by_group"] = {"x": {"n_affected": 1}}
            link["attributes"]["registry_by_group_by_nct"] = {WITH_RESULTS_A: {"x": {"n_affected": 1}}}
    (directory / "graph_data.json").write_text(json.dumps(graph))
    report, _ = _run(enrich, directory, _all_fixture_bodies(), results=True, refresh=True)
    _, links2 = _read_graph(directory)
    edge2 = _edges(links2, "reports_adverse_event", TRIAL_A, ae_node["id"])[0]
    assert report["results"]["refresh"]["updated_edges"] >= 1
    assert edge2.get("attributes") == edge0.get("attributes")


@pytest.mark.unit
def test_refresh01_conflicting_extracted_dict_refresh_matches_first_import(enrich, tmp_path):
    """12-REVIEW.iter2 WR-02: an extracted edge whose by_group conflicts with the
    registry keeps it on --results, and the first --refresh-results of the same
    payload is a no-op (iteration 30 recorded registry_by_group there)."""
    ref, ae_node, ae_link, _ = _extracted_ae_seed(enrich)
    res = _parsed(enrich, WITH_RESULTS_A)
    stat = next(a for a in res["adverse_events"] if a["term"] == ref["term"])["stats"][0]
    label = enrich._group_label(stat)
    ae_link = {**ae_link, "attributes": {**ae_link["attributes"], "by_group": {label: {"n_affected": 12345}}}}
    directory = _seeded_graph(tmp_path / "g", [ae_node], [ae_link])
    _run(enrich, directory, _all_fixture_bodies(), results=True)
    _, links0 = _read_graph(directory)
    edge0 = _edges(links0, "reports_adverse_event", TRIAL_A, ae_node["id"])[0]
    assert _eattr(edge0, "by_group")[label] == {"n_affected": 12345}
    assert len(_eattr(edge0, "by_group")) > 1 and _eattr(edge0, "registry_by_group") is None
    _assert_refresh_noop(enrich, directory, _all_fixture_bodies())
    _assert_refresh_noop(enrich, directory, _all_fixture_bodies())


@pytest.mark.unit
def test_refresh_bookkeeping_legacy_and_shared_values(enrich):
    """IN-02: registry_<attr> without _by_nct (an older graph) is this NCT's value
    when it is the only NCT; registry_<attr> is kept while another NCT holds it."""
    legacy = {"ctgov_nct_ids": [WITH_RESULTS_A], "n": 1, "registry_n": 2}
    assert enrich._refresh_bookkeeping(legacy, "n", 3, {}, WITH_RESULTS_A) is True
    assert legacy["registry_n"] == 3 and legacy["registry_n_by_nct"] == {WITH_RESULTS_A: 3}
    unchanged = {"ctgov_nct_ids": [WITH_RESULTS_A], "n": 1, "registry_n": 2}
    assert enrich._refresh_bookkeeping(unchanged, "n", 2, {}, WITH_RESULTS_A) is False
    assert unchanged == {"ctgov_nct_ids": [WITH_RESULTS_A], "n": 1, "registry_n": 2}
    shared = {"n": 1, "registry_n": 2, "registry_n_by_nct": {WITH_RESULTS_A: 2, WITH_RESULTS_B: 2}}
    assert enrich._refresh_bookkeeping(shared, "n", 1, {}, WITH_RESULTS_A) is True
    assert shared["registry_n"] == 2 and shared["registry_n_by_nct"] == {WITH_RESULTS_B: 2}
    other = {"n": 1, "registry_n": 2, "registry_n_by_nct": {WITH_RESULTS_A: 2, WITH_RESULTS_B: 5}}
    assert enrich._refresh_bookkeeping(other, "n", 1, {}, WITH_RESULTS_A) is True
    assert other["registry_n"] == 5 and other["registry_n_by_nct"] == {WITH_RESULTS_B: 5}


@pytest.mark.unit
def test_refresh01_trials_refreshed_counts_only_recorded_trials(enrich, tmp_path):
    """IN-01: a first import run with --refresh-results refreshes nothing."""
    directory = _write_graph(tmp_path / "g", [WITH_RESULTS_A, WITH_RESULTS_B, NO_RESULTS])
    report, _ = _run(enrich, directory, _all_fixture_bodies(), results=True, refresh=True)
    assert report["results"]["refresh"]["trials_refreshed"] == 0
    assert report["results"]["created"] > 0
    report, _ = _run(enrich, directory, _all_fixture_bodies(), results=True, refresh=True)
    assert report["results"]["refresh"]["trials_refreshed"] == 2


@pytest.mark.unit
def test_sift_kg_missing_refresh_of_no_results_trials_reason(enrich, tmp_path, monkeypatch):
    """IN-03: nothing was parsed, so the reason does not claim results were parsed."""
    monkeypatch.setitem(sys.modules, "sift_kg", None)
    _write_graph(tmp_path, [NO_RESULTS])
    report, _ = _run(enrich, tmp_path, _all_fixture_bodies(), results=True, refresh=True)
    reason = report["results"]["skipped_reason"]
    assert "parsed" not in reason and "refresh" in reason


@pytest.mark.unit
def test_cache_ttl_stale_payload_after_404_is_counted(enrich, tmp_path):
    """SA-02: a stale payload used because the refetch got a 404 is counted apart."""
    cache = tmp_path / "cache"
    _run(enrich, _write_graph(tmp_path / "g0", [WITH_RESULTS_A, WITH_RESULTS_B]),
         _all_fixture_bodies(), results=True, cache_dir=cache)
    for nct in (WITH_RESULTS_A, WITH_RESULTS_B):
        _age_cache(cache / f"{nct}.json", 5)
    report, m = _run(
        enrich, _write_graph(tmp_path / "g1", [WITH_RESULTS_A, WITH_RESULTS_B]),
        {WITH_RESULTS_B: "500"}, results=True, cache_dir=cache, cache_ttl_days=1,
    )
    assert _ctgov_calls(m) == 2
    assert report["cache"] == {
        "ttl_days": 1.0, "expired": 2, "refetched": 0, "stale_used": 2, "stale_after_not_found": 1,
    }
    assert report["results"]["trials_with_results"] == 2


@pytest.mark.unit
def test_baseline_missing_commit_fails_unless_allowed(monkeypatch):
    """WR-04: a pinned baseline that git cannot show fails the test by default."""
    missing = "0" * 40
    monkeypatch.delenv(ALLOW_MISSING_BASELINES_ENV, raising=False)
    with pytest.raises(pytest.fail.Exception, match=ALLOW_MISSING_BASELINES_ENV):
        _baseline_enrich_source(missing)
    monkeypatch.setenv(ALLOW_MISSING_BASELINES_ENV, "1")
    with pytest.raises(pytest.skip.Exception):
        _baseline_enrich_source(missing)
    for commit in (OLD_COMMIT, ITERATION20_COMMIT, ITERATION26_COMMIT, ITERATION27_COMMIT,
                   ITERATION28_COMMIT, ITERATION29_COMMIT, ITERATION30_COMMIT):
        assert re.fullmatch(r"[0-9a-f]{40}", commit)


@pytest.mark.unit
@pytest.mark.parametrize("variant", ["protocol_only", "fresh_results", "rerun", "colliding_shared", "duplicate"])
def test_default_runs_identical_to_iteration29(enrich, tmp_path, monkeypatch, variant):
    old = _load_old_enrich(tmp_path, ITERATION29_COMMIT, "_ct_enrich_iter29", monkeypatch)
    bodies = _all_fixture_bodies()
    if variant == "colliding_shared":
        bodies = {**bodies, WITH_RESULTS_A: _colliding_study()}
        d_old = _shared_placebo_graph(tmp_path / "old")
        d_new = _shared_placebo_graph(tmp_path / "new")
    elif variant == "duplicate":
        d_old = _write_graph(tmp_path / "old", [WITH_RESULTS_A], [DUP_NODE])
        d_new = _write_graph(tmp_path / "new", [WITH_RESULTS_A], [DUP_NODE])
    else:
        d_old = _fully_seeded(enrich, tmp_path / "old")
        d_new = _fully_seeded(enrich, tmp_path / "new")
    kwargs = {} if variant == "protocol_only" else {"results": True}
    if variant == "rerun":
        _enrich_with(old, d_old, bodies, results=True)
        _enrich_with(old, d_new, bodies, results=True)
    rep_old = _enrich_with(old, d_old, bodies, **kwargs)
    rep_new = _enrich_with(enrich, d_new, bodies, **kwargs)
    assert _normalize_stamps((d_old / "graph_data.json").read_bytes()) == _normalize_stamps(
        (d_new / "graph_data.json").read_bytes()
    )
    rep_old.pop("generated_at")
    rep_new.pop("generated_at")
    assert rep_old == rep_new and _same_key_order(rep_old, rep_new)


@pytest.mark.unit
def test_default_runs_iteration29_delta_is_the_non_canonical_merge(enrich, tmp_path, monkeypatch):
    """The one default-run change from iteration 29 (CR-03): with an extracted AE edge
    on a non-canonical Trial node, iteration 29 wrote a parallel canonical registry
    edge; iteration 30 merges into the extracted edge. Everything else is equal."""
    old = _load_old_enrich(tmp_path, ITERATION29_COMMIT, "_ct_enrich_iter29_delta", monkeypatch)
    nausea = "adverseevent:nausea"

    def graph(d):
        ae = {"id": nausea, "name": "nausea", "entity_type": "AdverseEvent", "attributes": {}}
        return _write_graph(d, [WITH_RESULTS_A], [DUP_NODE, ae], [_link(TRIAL_A, "reports_adverse_event", nausea)])

    d_old, d_new = graph(tmp_path / "old"), graph(tmp_path / "new")
    _enrich_with(old, d_old, _all_fixture_bodies(), results=True)
    _enrich_with(enrich, d_new, _all_fixture_bodies(), results=True)
    o_nodes, o_links = _read_graph(d_old)
    n_nodes, n_links = _read_graph(d_new)
    key = lambda l: (l["source"], l["relation_type"], l["target"])
    copy_key = ("trial:achieve_1", "reports_adverse_event", nausea)
    merged_key = (TRIAL_A, "reports_adverse_event", nausea)
    assert copy_key in {key(l) for l in o_links} and copy_key not in {key(l) for l in n_links}
    rest_old = {key(l): l for l in o_links if key(l) not in (copy_key, merged_key)}
    rest_new = {key(l): l for l in n_links if key(l) not in (copy_key, merged_key)}
    assert rest_old == rest_new
    assert o_nodes == n_nodes


# ---------------------------------------------------------------------------
# Iteration 31: 12-REVIEW.iter2 (CR-01 withdrawn join, WR-01 live edge on a
# non-canonical Trial node, WR-02 dict refresh = first import)
# ---------------------------------------------------------------------------

ITERATION30_COMMIT = "caa8af0a07747f418d6acf72b8d03955b8a18ac7"


def _withdrawn_then_joined(enrich, directory: Path, owner: str, join_refresh: bool):
    """owner is imported alone and its refresh drops SHARED_TERM (the AE facts
    only it supports get ctgov_withdrawn); then the other fixture trial is added
    to the graph and first imports the term (in a default run or a refresh).
    Returns the bodies both later runs use."""
    joiner = WITH_RESULTS_B if owner == WITH_RESULTS_A else WITH_RESULTS_A
    _write_graph(directory, [owner])
    _run(enrich, directory, _all_fixture_bodies(), results=True)
    bodies = {**_all_fixture_bodies(), owner: _without_term(owner, SHARED_TERM)}
    _run(enrich, directory, bodies, results=True, refresh=True)
    nodes, _ = _read_graph(directory)
    ae = f"adverseevent:{SHARED_TERM.lower().replace(' ', '_')}"
    assert _nattr(nodes[ae], "ctgov_withdrawn") is True and _nattr(nodes[ae], "ctgov_nct_ids") == [owner]
    graph = json.loads((directory / "graph_data.json").read_text())
    graph["nodes"].append({"id": f"trial:{joiner.lower()}", "name": joiner, "entity_type": "Trial"})
    (directory / "graph_data.json").write_text(json.dumps(graph))
    report, _ = _run(enrich, directory, bodies, results=True, refresh=join_refresh)
    return ae, joiner, bodies, report


@pytest.mark.unit
@pytest.mark.parametrize("join_refresh", [False, True], ids=["join_default", "join_refresh"])
@pytest.mark.parametrize("owner", [WITH_RESULTS_B, WITH_RESULTS_A], ids=["owner_sorts_first", "owner_sorts_last"])
def test_refresh01_withdrawn_fact_joined_by_another_nct_keeps_the_withdrawal(
    enrich, tmp_path, owner, join_refresh,
):
    """12-REVIEW.iter2 CR-01: a fact withdrawn by its only NCT and later first
    reported by another NCT is not flagged, records the earlier withdrawal per
    NCT, and the next two refreshes on unchanged payloads are both no-ops,
    whichever NCT sorts first."""
    directory = tmp_path / "g"
    ae, joiner, bodies, report = _withdrawn_then_joined(enrich, directory, owner, join_refresh)
    nodes, links = _read_graph(directory)
    _, shared = _shared_term_facts(nodes, links)
    assert shared
    for item in (nodes[ae], *shared):
        attrs = item.get("attributes") or {}
        assert attrs.get("ctgov_nct_ids") == [owner, joiner]
        assert "ctgov_withdrawn" not in attrs
        assert attrs.get("ctgov_withdrawn_by_nct") == {owner: True}
    # the owner's own trial edge is still withdrawn; the joiner's is live
    own = _edges(links, "reports_adverse_event", f"trial:{owner.lower()}", ae)
    assert own and _eattr(own[0], "ctgov_withdrawn") is True
    joined = _edges(links, "reports_adverse_event", f"trial:{joiner.lower()}", ae)
    assert joined and _eattr(joined[0], "ctgov_withdrawn") is None
    if join_refresh:
        assert report["results"]["refresh"]["restored"] >= len(shared) + 1
    _assert_refresh_noop(enrich, directory, bodies)
    _assert_refresh_noop(enrich, directory, bodies)

    # the owner reports the term again: no withdrawal bookkeeping is left on it
    _run(enrich, directory, _all_fixture_bodies(), results=True, refresh=True)
    nodes2, links2 = _read_graph(directory)
    _, shared2 = _shared_term_facts(nodes2, links2)
    for item in (nodes2[ae], *shared2):
        attrs = item.get("attributes") or {}
        assert "ctgov_withdrawn" not in attrs and "ctgov_withdrawn_by_nct" not in attrs


@pytest.mark.unit
def test_join_withdrawn_converts_the_flag_per_nct(enrich):
    """_join_withdrawn keeps existing per-NCT entries and leaves unflagged facts alone."""
    plain = {"ctgov_nct_ids": [WITH_RESULTS_B], "x": 1}
    enrich._join_withdrawn(plain, None)
    assert plain == {"ctgov_nct_ids": [WITH_RESULTS_B], "x": 1}
    both = {
        "ctgov_nct_ids": [WITH_RESULTS_B, WITH_RESULTS_A], "ctgov_withdrawn": True,
        "ctgov_withdrawn_by_nct": {WITH_RESULTS_B: True, WITH_RESULTS_A: True},
    }
    stats = {"stats": {"restored": 0}}
    enrich._join_withdrawn(both, stats)
    assert both == {
        "ctgov_nct_ids": [WITH_RESULTS_B, WITH_RESULTS_A],
        "ctgov_withdrawn_by_nct": {WITH_RESULTS_B: True, WITH_RESULTS_A: True},
    }
    assert stats["stats"]["restored"] == 1


@pytest.mark.unit
def test_refresh02_live_registry_edge_on_later_non_canonical_trial_is_withdrawn(enrich, tmp_path):
    """12-REVIEW.iter2 WR-01: a lower-id Trial node of the NCT is added after the
    first import, so the NCT's live registry edges sit on a non-canonical node.
    A dropped term withdraws that edge (it is not a legacy copy), and a repeat
    refresh is a no-op."""
    ae = f"adverseevent:{REFRESH_TERM_REMOVED.lower()}"
    directory = _write_graph(tmp_path / "g", [WITH_RESULTS_A])
    _run(enrich, directory, _all_fixture_bodies(), results=True)
    graph = json.loads((directory / "graph_data.json").read_text())
    graph["nodes"].append(dict(DUP_NODE))  # trial:achieve_1 sorts before trial:nct05971940
    (directory / "graph_data.json").write_text(json.dumps(graph))
    bodies = _bodies(_without_term(WITH_RESULTS_A, REFRESH_TERM_REMOVED))
    report, _ = _run(enrich, directory, bodies, results=True, refresh=True)
    refresh = report["results"]["refresh"]
    assert refresh["legacy_copies_skipped"] == 0
    nodes, links = _read_graph(directory)
    edge = _edges(links, "reports_adverse_event", TRIAL_A, ae)
    assert len(edge) == 1 and _eattr(edge[0], "ctgov_withdrawn") is True
    assert not _edges(links, "reports_adverse_event", DUP_NODE["id"], ae)
    assert _nattr(nodes[ae], "ctgov_withdrawn") is True
    assert refresh["withdrawn"] == len(
        [l for l in links if _eattr(l, "ctgov_withdrawn")]
    ) + len([n for n in nodes.values() if _nattr(n, "ctgov_withdrawn")])
    _assert_refresh_noop(enrich, directory, bodies)
    # the term returns: the edge is live again
    _run(enrich, directory, _all_fixture_bodies(), results=True, refresh=True)
    _, links2 = _read_graph(directory)
    assert _eattr(_edges(links2, "reports_adverse_event", TRIAL_A, ae)[0], "ctgov_withdrawn") is None


@pytest.mark.unit
@pytest.mark.parametrize(
    "variant", ["protocol_only", "fresh_results", "rerun", "colliding_shared", "duplicate", "non_canonical"],
)
def test_default_runs_identical_to_iteration30(enrich, tmp_path, monkeypatch, variant):
    old = _load_old_enrich(tmp_path, ITERATION30_COMMIT, "_ct_enrich_iter30", monkeypatch)
    bodies = _all_fixture_bodies()
    if variant == "colliding_shared":
        bodies = {**bodies, WITH_RESULTS_A: _colliding_study()}
        d_old = _shared_placebo_graph(tmp_path / "old")
        d_new = _shared_placebo_graph(tmp_path / "new")
    elif variant == "duplicate":
        d_old = _write_graph(tmp_path / "old", [WITH_RESULTS_A], [DUP_NODE])
        d_new = _write_graph(tmp_path / "new", [WITH_RESULTS_A], [DUP_NODE])
    elif variant == "non_canonical":
        nausea = "adverseevent:nausea"
        ae = {"id": nausea, "name": "nausea", "entity_type": "AdverseEvent", "attributes": {}}
        seed = ([DUP_NODE, ae], [_link(TRIAL_A, "reports_adverse_event", nausea)])
        d_old = _write_graph(tmp_path / "old", [WITH_RESULTS_A], *seed)
        d_new = _write_graph(tmp_path / "new", [WITH_RESULTS_A], *seed)
    else:
        d_old = _fully_seeded(enrich, tmp_path / "old")
        d_new = _fully_seeded(enrich, tmp_path / "new")
    kwargs = {} if variant == "protocol_only" else {"results": True}
    if variant == "rerun":
        _enrich_with(old, d_old, bodies, results=True)
        _enrich_with(old, d_new, bodies, results=True)
    rep_old = _enrich_with(old, d_old, bodies, **kwargs)
    rep_new = _enrich_with(enrich, d_new, bodies, **kwargs)
    assert _normalize_stamps((d_old / "graph_data.json").read_bytes()) == _normalize_stamps(
        (d_new / "graph_data.json").read_bytes()
    )
    rep_old.pop("generated_at")
    rep_new.pop("generated_at")
    assert rep_old == rep_new and _same_key_order(rep_old, rep_new)


@pytest.mark.unit
def test_default_runs_iteration30_delta_is_the_withdrawn_join(enrich, tmp_path, monkeypatch):
    """The one default-run change from iteration 30 (12-REVIEW.iter2 CR-01): on a
    graph a refresh left with ctgov_withdrawn facts, a default run in which another
    NCT first reports such a fact turns the flag into per-NCT entries. Iteration 30
    left the flag. Everything else is equal."""
    old = _load_old_enrich(tmp_path, ITERATION30_COMMIT, "_ct_enrich_iter30_delta", monkeypatch)
    d_old, d_new = tmp_path / "old", tmp_path / "new"
    for module, d in ((old, d_old), (enrich, d_new)):
        _write_graph(d, [WITH_RESULTS_B])
        _enrich_with(module, d, _all_fixture_bodies(), results=True)
        bodies = {**_all_fixture_bodies(), WITH_RESULTS_B: _without_term(WITH_RESULTS_B, SHARED_TERM)}
        _enrich_with(module, d, bodies, results=True, refresh=True)
        graph = json.loads((d / "graph_data.json").read_text())
        graph["nodes"].append({"id": TRIAL_A, "name": WITH_RESULTS_A, "entity_type": "Trial"})
        (d / "graph_data.json").write_text(json.dumps(graph))
        _enrich_with(module, d, bodies, results=True)

    def strip(item):
        attrs = dict(item.get("attributes") or {})
        attrs.pop("ctgov_withdrawn", None)
        attrs.pop("ctgov_withdrawn_by_nct", None)
        return {**item, "attributes": attrs}

    key = lambda l: (l["source"], l["relation_type"], l["target"])
    o_nodes, o_links = _read_graph(d_old)
    n_nodes, n_links = _read_graph(d_new)
    changed = [
        k for k in o_nodes
        if (o_nodes[k].get("attributes") or {}) != (n_nodes[k].get("attributes") or {})
    ]
    assert changed and all(
        _nattr(o_nodes[k], "ctgov_withdrawn") is True and _nattr(n_nodes[k], "ctgov_withdrawn") is None
        and _nattr(n_nodes[k], "ctgov_withdrawn_by_nct") == {WITH_RESULTS_B: True}
        for k in changed
    )
    assert {k: strip(v) for k, v in o_nodes.items()} == {k: strip(v) for k, v in n_nodes.items()}
    assert {key(l): strip(l) for l in o_links} == {key(l): strip(l) for l in n_links}
