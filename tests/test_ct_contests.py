"""Contract tests for outcome-kind and dose-aware registry contests.

The module under test is domains/clinicaltrials/epistemic.py, or the file named
by the CT_EPISTEMIC_PATH environment variable (used to run these tests against
a staged copy before it is applied). The no-registry identity tests compare it
with the module as of BASE_EPISTEMIC_COMMIT, read from git.
"""
from __future__ import annotations

import copy
import importlib.util
import json
import os
import subprocess
from pathlib import Path

import pytest

EPI_ROOT = Path(__file__).resolve().parents[1]
BASE_EPISTEMIC_COMMIT = "21cacb559846303aba9952bf208f3d4b383d50f1"
GLP1_GRAPH = EPI_ROOT / "tests" / "corpora" / "07_glp1_phase3_trials" / "output" / "graph_data.json"
ALLOW_MISSING_BASELINES_ENV = "CT_ALLOW_MISSING_BASELINES"


def _load_epistemic(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def ep():
    override = os.environ.get("CT_EPISTEMIC_PATH")
    path = Path(override) if override else EPI_ROOT / "domains" / "clinicaltrials" / "epistemic.py"
    return _load_epistemic(path, "ct_epistemic_under_test")


@pytest.fixture(scope="module")
def base_ep(tmp_path_factory):
    """epistemic.py as of BASE_EPISTEMIC_COMMIT, read from git.

    A missing commit fails (not skips) unless CT_ALLOW_MISSING_BASELINES=1.
    """
    try:
        shown = subprocess.run(
            ["git", "-C", str(EPI_ROOT), "show", f"{BASE_EPISTEMIC_COMMIT}:domains/clinicaltrials/epistemic.py"],
            capture_output=True, check=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        message = (
            f"cannot read pinned baseline {BASE_EPISTEMIC_COMMIT} from git ({exc}); the identity "
            f"tests need the full epistract history. Fetch it or set {ALLOW_MISSING_BASELINES_ENV}=1."
        )
        if os.environ.get(ALLOW_MISSING_BASELINES_ENV) == "1":
            pytest.skip(message)
        pytest.fail(message)
    path = tmp_path_factory.mktemp("base") / "epistemic_base.py"
    path.write_bytes(shown.stdout)
    return _load_epistemic(path, "ct_epistemic_base")


def _n(i, t, name, **kw):
    return {"id": i, "entity_type": t, "name": name, **kw}


def _e(s, t, r):
    return {"source": s, "target": t, "relation_type": r}


def _run(mod, graph):
    return mod.analyze_clinicaltrials_epistemic(Path("/nonexistent"), copy.deepcopy(graph))


def _entries(result):
    return [e for e in result["super_domain"]["contested_claims"] if e.get("basis") == "outcome_analysis"]


def _claims(result):
    return {c["analysis"]: c for c in result["base_domain"]["analysis_claims"]}


# --- registry graph builders -------------------------------------------------

CHANGE_TITLE = "Change From Baseline in HbA1c"
RESPONDER_TITLE = "Percentage of Participants Achieving HbA1c <7%"


def _trial(nct):
    return _n(f"trial:{nct.lower()}", "Trial", nct, ct_phase="PHASE3", ct_masking="DOUBLE",
              ct_enrollment=900, ct_nct_id=nct, attributes={"nct_id": nct})


def _analysis(i, nct, groups, title, p, unit=None, effect_measure=None):
    attrs = {
        "source": "ctgov_results",
        "ctgov_nct_ids": [nct],
        "compared_groups": list(groups),
        "unmatched_groups": list(groups),
        "p_value": p,
    }
    if unit:
        attrs["unit"] = unit
    if effect_measure:
        attrs["effect_measure"] = effect_measure
    return _n(i, "OutcomeAnalysis", f"{nct}: {title}", source_documents=[f"ctgov:{nct}"], attributes=attrs)


def _graph(specs):
    """specs: list of dicts with ra, nct, arm (group title), title, p, unit?, effect?."""
    nodes = [_n("c1", "Compound", "Tirzepatide")]
    links = []
    for nct in sorted({s["nct"] for s in specs}):
        nodes.append(_trial(nct))
    for k, s in enumerate(specs):
        oc = f"oc{k}"
        nodes.append(_n(oc, "Outcome", s["title"]))
        nodes.append(_analysis(
            s["ra"], s["nct"], [s["arm"], "Placebo"], s["title"], s["p"],
            unit=s.get("unit"), effect_measure=s.get("effect"),
        ))
        links.append(_e(s["ra"], oc, "analyzes"))
    return {"nodes": nodes, "links": links}


def _spec(ra, nct, arm, p, title=CHANGE_TITLE, **kw):
    return {"ra": ra, "nct": nct, "arm": arm, "p": p, "title": title, **kw}


# --- CONTEST-02: outcome kind --------------------------------------------------

@pytest.mark.unit
@pytest.mark.parametrize("title, unit, effect, kind", [
    ("Percentage of Participants Achieving HbA1c <7%", None, None, "responder"),
    ("Number of Participants With ≥5% Body Weight Loss", None, None, "responder"),
    ("Some measure", "percentage of participants", None, "responder"),
    ("Some measure", None, "Odds Ratio (OR)", "responder"),
    ("Change From Baseline in HbA1c", "percentage of HbA1c", None, "continuous"),
    ("Change From Baseline in Body Weight", "kg", None, "continuous"),
    ("LS Mean Change in Fasting Glucose", "mmol/mol", None, "continuous"),
    ("Time to First Occurrence of MACE", None, None, "time_to_event"),
    ("Some measure", None, "Hazard Ratio (HR)", "time_to_event"),
    ("Some measure", None, None, None),
])
def test_contest02_outcome_kind_classification(ep, title, unit, effect, kind):
    assert ep._outcome_kind(title, unit, effect) == kind


@pytest.mark.unit
def test_contest02_responder_and_continuous_never_contest(ep):
    graph = _graph([
        _spec("ra1", "NCT00000001", "Tirzepatide 15 mg", "<0.001", title=RESPONDER_TITLE,
              unit="percentage of participants"),
        _spec("ra2", "NCT00000002", "Tirzepatide 15 mg", "0.42", title="Change From Baseline in HbA1c",
              unit="percentage of HbA1c"),
    ])
    result = _run(ep, graph)
    claims = _claims(result)
    assert claims["ra1"]["outcome_kind"] == "responder"
    assert claims["ra2"]["outcome_kind"] == "continuous"
    assert result["summary"]["analysis_contested_found"] == 0


@pytest.mark.unit
def test_contest02_same_kind_contests_with_outcome_kind_on_entry(ep):
    graph = _graph([
        _spec("ra1", "NCT00000001", "Tirzepatide 15 mg", "<0.001", unit="percentage of HbA1c"),
        _spec("ra2", "NCT00000002", "Tirzepatide 15 mg", "0.42", unit="percentage of HbA1c"),
    ])
    entries = _entries(_run(ep, graph))
    assert len(entries) == 1
    assert entries[0]["outcome_kind"] == "continuous"


@pytest.mark.unit
def test_contest02_summary_counts_kinds(ep):
    graph = _graph([
        _spec("ra1", "NCT00000001", "Tirzepatide 15 mg", "<0.001", title=RESPONDER_TITLE),
        _spec("ra2", "NCT00000002", "Tirzepatide 15 mg", "0.42"),
        _spec("ra3", "NCT00000003", "Tirzepatide 15 mg", "0.42", title="Some other measure"),
    ])
    summary = _run(ep, graph)["summary"]
    assert summary["analysis_outcome_kind_counts"] == {"continuous": 1, "responder": 1, "unknown": 1}
    assert "analysis_contests_dose_aware" in summary and "analysis_contests_dose_fallback" in summary


# --- CONTEST-01: dose ----------------------------------------------------------

@pytest.mark.unit
@pytest.mark.parametrize("text, doses", [
    ("Tirzepatide 15 mg", {15.0}),
    ("Semaglutide 2.4 mg", {2.4}),
    ("Semaglutide 500 µg", {0.5}),
    ("Semaglutide 500 mcg", {0.5}),
    ("Tirzepatide 15mg", {15.0}),
    ("10 mg/kg", set()),
    ("Placebo", set()),
    ("Tirzepatide 5 mg, 10 mg or 15 mg", {5.0, 10.0, 15.0}),
    ("Tirzepatide 5/10/15 mg", {5.0, 10.0, 15.0}),
])
def test_contest01_parse_dose(ep, text, doses):
    assert ep._parse_dose(text) == doses


def _patterns(ep):
    nodes = {n["id"]: n for n in [
        _n("c1", "Compound", "Semaglutide"), _n("c2", "Compound", "Metformin"),
        _n("c3", "Compound", "Tirzepatide"),
    ]}
    return ep._compound_patterns(nodes)


@pytest.mark.unit
@pytest.mark.parametrize("texts, treatment, dose", [
    (["Semaglutide 1 mg + Metformin 1000 mg"], "c1", 1.0),
    (["Tirzepatide 5/10/15 mg"], "c3", None),
    (["Tirzepatide 5 mg", "Tirzepatide 10 mg"], "c3", None),
    (["15 mg"], "c3", 15.0),
    (["Tirzepatide 15 mg", "15 mg"], "c3", 15.0),
    (["Placebo"], "c3", None),
])
def test_contest01_finding_dose(ep, texts, treatment, dose):
    assert ep._finding_dose(texts, treatment, _patterns(ep)) == dose


@pytest.mark.unit
def test_contest01_different_doses_across_trials_do_not_contest(ep):
    graph = _graph([
        _spec("ra1", "NCT00000001", "Tirzepatide 15 mg", "<0.001"),
        _spec("ra2", "NCT00000002", "Tirzepatide 5 mg", "0.42"),
    ])
    result = _run(ep, graph)
    assert _claims(result)["ra1"]["dose_mg"] == 15.0
    assert _claims(result)["ra2"]["dose_mg"] == 5.0
    assert result["summary"]["analysis_contested_found"] == 0


@pytest.mark.unit
def test_contest01_same_dose_across_trials_contests_dose_aware(ep):
    graph = _graph([
        _spec("ra1", "NCT00000001", "Tirzepatide 15 mg", "<0.001"),
        _spec("ra2", "NCT00000002", "Tirzepatide 15 mg", "0.42"),
    ])
    result = _run(ep, graph)
    entries = _entries(result)
    assert len(entries) == 1
    assert entries[0]["dose_aware"] is True and entries[0]["dose_mg"] == 15.0
    assert result["summary"]["analysis_contests_dose_aware"] == 1
    assert result["summary"]["analysis_contests_dose_fallback"] == 0


@pytest.mark.unit
def test_contest01_missing_dose_falls_back_to_pooled_key(ep):
    graph = _graph([
        _spec("ra1", "NCT00000001", "Tirzepatide 15 mg", "<0.001"),
        _spec("ra2", "NCT00000002", "Tirzepatide", "0.42"),
    ])
    result = _run(ep, graph)
    entries = _entries(result)
    assert len(entries) == 1
    assert entries[0]["dose_aware"] is False and "dose_mg" not in entries[0]
    assert result["summary"]["analysis_contests_dose_fallback"] == 1


@pytest.mark.unit
def test_contest01_dose_split_inside_one_trial_is_not_a_contest(ep):
    graph = _graph([
        _spec("ra1", "NCT00000001", "Tirzepatide 15 mg", "<0.001"),
        _spec("ra2", "NCT00000001", "Tirzepatide 5 mg", "0.42"),
    ])
    result = _run(ep, graph)
    assert result["summary"]["analysis_contested_found"] == 0
    assert result["super_domain"]["contradictions"] == []


# --- no-registry identity with the iteration-32 module -------------------------

def _dumped(result):
    return json.dumps(result, sort_keys=True, default=str)


def _no_registry_graph():
    nodes = [
        _n("ta", "Trial", "Trial A", ct_phase="PHASE3", ct_masking="DOUBLE", ct_enrollment=900),
        _n("tb", "Trial", "Trial B", ct_phase="PHASE3", ct_masking="DOUBLE", ct_enrollment=900),
        _n("doc:da", "DOCUMENT", "doc a"), _n("doc:db", "DOCUMENT", "doc b"),
        _n("so1", "StandardOutcome", "HbA1c"),
        _n("oca", "Outcome", "Change in HbA1c at week 30", source_documents=["da"]),
        _n("ocb", "Outcome", "Change in HbA1c at week 40", source_documents=["db"]),
        _n("c1", "Compound", "Semaglutide"),
        _n("oa1", "OutcomeAnalysis", "Analysis 1", source_documents=["da"], attributes={"p_value": "<0.001"}),
        _n("oa2", "OutcomeAnalysis", "Analysis 2", source_documents=["db"], attributes={"p_value": "0.4"}),
    ]
    links = [
        _e("ta", "doc:da", "MENTIONED_IN"), _e("tb", "doc:db", "MENTIONED_IN"),
        _e("so1", "oca", "measures"), _e("so1", "ocb", "measures"),
        _e("oa1", "oca", "analyzes"), _e("oa2", "ocb", "analyzes"),
        _e("oa1", "c1", "assesses_effect_of"), _e("oa2", "c1", "assesses_effect_of"),
    ]
    return {"nodes": nodes, "links": links}


@pytest.mark.unit
def test_no_registry_identity_on_fixture_graph(ep, base_ep):
    graph = _no_registry_graph()
    new, old = _run(ep, graph), _run(base_ep, graph)
    assert new["summary"]["analysis_contested_found"] == 1
    assert _dumped(new) == _dumped(old)


@pytest.mark.unit
@pytest.mark.skipif(not GLP1_GRAPH.exists(), reason="corpus 07 graph not present")
def test_no_registry_identity_on_glp1_corpus_graph(ep, base_ep):
    graph = json.loads(GLP1_GRAPH.read_text())
    assert _dumped(_run(ep, graph)) == _dumped(_run(base_ep, graph))
