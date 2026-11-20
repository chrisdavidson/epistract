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


def _write_graph(directory: Path, nct_ids, extra_nodes=()):
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
        "links": [],
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


@pytest.mark.unit
def test_results_report_block(enrich, tmp_path):
    _write_graph(tmp_path, [WITH_RESULTS_A, WITH_RESULTS_B])
    report, _ = _run(enrich, tmp_path, _all_fixture_bodies(), results=True)
    block = report["results"]
    assert set(block) == {
        "trials_with_results", "trials_without_results", "results_failed",
        "adverse_events_parsed", "analyses_parsed", "created", "merged",
    }
    assert block["trials_with_results"] == 2
    assert block["adverse_events_parsed"] == {"serious": 178, "other": 39}
    assert block["analyses_parsed"] == 43
    assert block["created"] == 0
    assert block["merged"] == 0
    written = json.loads((tmp_path / "extractions" / "_enrichment_report.json").read_text())
    assert written["results"] == block
    assert (
        block["trials_with_results"] + block["trials_without_results"] + block["results_failed"]
        == report["trials"]["total"] - report["trials"]["not_found"]
    )


@pytest.mark.unit
def test_results_flag_does_not_change_graph(enrich, tmp_path):
    ids = [WITH_RESULTS_A, WITH_RESULTS_B, NO_RESULTS]
    plain = _write_graph(tmp_path / "plain", ids)
    with_results = _write_graph(tmp_path / "res", ids)
    _run(enrich, plain, _all_fixture_bodies())
    _run(enrich, with_results, _all_fixture_bodies(), results=True)
    assert _normalize_stamps((plain / "graph_data.json").read_bytes()) == _normalize_stamps(
        (with_results / "graph_data.json").read_bytes()
    )


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
    assert "--cache-dir" in proc.stdout
