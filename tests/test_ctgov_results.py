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
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

EPI_ROOT = Path(__file__).resolve().parents[1]
FIX = Path(__file__).parent / "fixtures" / "ctgov"
CTGOV_PREFIX = "https://clinicaltrials.gov/api/v2/studies/"
OLD_COMMIT = "c80444b"

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
    "adverse_events_parsed", "analyses_parsed", "created", "merged",
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
    try:
        shown = subprocess.run(
            ["git", "-C", str(EPI_ROOT), "show", f"{OLD_COMMIT}:domains/clinicaltrials/enrich.py"],
            capture_output=True, check=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        pytest.skip(f"cannot read {OLD_COMMIT} from git: {exc}")
    old_path.write_bytes(shown.stdout)
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
    assert block["merged"] == sum(len(_nattr(n, "ctgov_nct_ids", [])) for n in gained)
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
        assert _edges(links, "reports_adverse_event", tid)


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

ITERATION20_COMMIT = "1589524"


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
    try:
        shown = subprocess.run(
            ["git", "-C", str(EPI_ROOT), "show", f"{ITERATION20_COMMIT}:domains/clinicaltrials/enrich.py"],
            capture_output=True, check=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        pytest.skip(f"cannot read {ITERATION20_COMMIT} from git: {exc}")
    old_path.write_bytes(shown.stdout)
    old = _load_enrich("_ct_enrich_iter20", old_path)
    monkeypatch.setattr(old.time, "sleep", lambda s: None)
    bodies = _all_fixture_bodies()
    d_old = _seeded_graph(tmp_path / "old")
    d_new = _seeded_graph(tmp_path / "new")
    with patch.object(old.requests, "get", side_effect=_router(bodies)):
        rep_old = old.enrich_graph(d_old, results=True)
    with patch.object(enrich.requests, "get", side_effect=_router(bodies)):
        rep_new = enrich.enrich_graph(d_new, results=True)
    g_old = _normalize_stamps((d_old / "graph_data.json").read_bytes())
    g_new = _normalize_stamps((d_new / "graph_data.json").read_bytes())
    assert g_old == g_new
    rep_old.pop("generated_at")
    rep_new.pop("generated_at")
    assert rep_old == rep_new and _same_key_order(rep_old, rep_new)


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
