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
    for edge in _edges(links, "reports_adverse_event", TRIAL_A):
        if _eattr(edge, "by_group") and "3 mg Orforglipron" in _eattr(edge, "by_group"):
            entry = _eattr(edge, "by_group")["3 mg Orforglipron"]
            assert entry["cohort"] is None
            assert "n_affected" in entry
            assert _eattr(edge, "by_group")["Placebo"]["cohort"] == COHORT_PLACEBO

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
    assert attrs["p_value"] == ref["p_value"]
    assert attrs["p_value_num"] == 0.001
    assert attrs["ci_lower"] == float(ref["ci_lower_limit"])
    assert attrs["ci_upper"] == float(ref["ci_upper_limit"])
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
