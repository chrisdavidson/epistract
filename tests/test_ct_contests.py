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
@pytest.mark.parametrize("title, unit, effect, param, kind", [
    # WR-02: "HR" in a title is heart rate, not a hazard ratio
    ("Change From Baseline in Heart Rate (HR)", None, None, None, "continuous"),
    ("Change From Baseline in Heart Rate (HR)", "beats per minute", None, None, "continuous"),
    ("Change from baseline in heart rate", None, None, None, "continuous"),
    # WR-02: a threshold qualifying a subgroup of a continuous measure
    ("Change From Baseline in Body Weight in Participants With Baseline HbA1c >=8%", None, None, None, "continuous"),
    ("Change From Baseline in Body Weight in Participants With Baseline HbA1c >=8%", "kg", None, None, "continuous"),
    ("Body Weight Loss ≥5%", None, None, None, "responder"),
    # WR-02: a measured duration is not a time-to-event outcome
    ("Change From Baseline in Time to Exhaustion", None, None, None, "continuous"),
    ("Time to Exhaustion", "seconds", None, None, None),
    ("Time to Exhaustion", "seconds", None, "MEAN", "continuous"),
    ("Time to Exhaustion", "seconds", "Hazard Ratio (HR)", None, "time_to_event"),
    ("Time to First Occurrence of MACE", "months", None, None, "time_to_event"),
    ("Time to Onset of Rescue Therapy", None, None, None, "time_to_event"),
    # WR-03: the registry paramType decides before the title
    ("Body weight", None, None, "LEAST_SQUARES_MEAN", "continuous"),
    ("Body weight", None, None, "GEOMETRIC_MEAN", "continuous"),
    ("Body weight", None, None, "COUNT_OF_PARTICIPANTS", "responder"),
    ("Change From Baseline in HbA1c", "percentage of participants", None, "NUMBER", "responder"),
    ("Number of Participants With MACE", "participants", "Hazard Ratio (HR)", "COUNT_OF_PARTICIPANTS",
     "time_to_event"),
    ("Percentage of Participants Achieving HbA1c <7%", "%", None, None, "responder"),
    ("Body weight", None, None, "NUMBER", None),
    # responder wording in the effect measure still decides before the title
    ("percentage change from baseline in body weight", None, "proportion of participants (arm-level)", None,
     "responder"),
    # WR-03 (review round 2): the abbreviations OR, RR and HR are case-sensitive,
    # so the words "or" and "hr" in a free-text effect measure name no model
    ("Change From Baseline in HbA1c", None, "Mean difference or LS mean", None, "continuous"),
    ("Change From Baseline in Body Weight", None, "ETD (or treatment ratio)", None, "continuous"),
    ("Change in Heart Rate", None, "Change per hr", None, None),
    ("Some measure", None, "OR (95% CI)", None, "responder"),
    ("Some measure", None, "RR", None, "responder"),
    ("Some measure", None, "HR 0.74", None, "time_to_event"),
    ("Some measure", None, "Odds Ratio", None, "responder"),
    ("Some measure", None, "cox proportional hazards", None, "time_to_event"),
])
def test_review1_outcome_kind_classification(ep, title, unit, effect, param, kind):
    assert ep._outcome_kind(title, unit, effect, param) == kind


@pytest.mark.unit
def test_review1_registry_param_type_classifies_the_finding(ep):
    graph = _graph([_spec("ra1", "NCT00000001", "Tirzepatide 15 mg", "<0.001", title="Body weight")])
    assert _claims(_run(ep, graph))["ra1"]["outcome_kind"] is None
    for node in graph["nodes"]:
        if node["id"] == "ra1":
            node["attributes"]["outcome_param_type"] = "LEAST_SQUARES_MEAN"
    assert _claims(_run(ep, graph))["ra1"]["outcome_kind"] == "continuous"


@pytest.mark.unit
def test_review1_unknown_kind_joins_the_single_classified_kind(ep):
    graph = _graph([
        _spec("ra1", "NCT00000001", "Tirzepatide 15 mg", "<0.001",
              title="Change From Baseline in Body Weight", unit="kg"),
        _spec("ra2", "NCT00000002", "Tirzepatide 15 mg", "0.40", title="Change in Body Weight"),
    ])
    result = _run(ep, graph)
    claims = _claims(result)
    assert claims["ra1"]["outcome_kind"] == "continuous"
    assert claims["ra2"]["outcome_kind"] is None
    entries = _entries(result)
    assert len(entries) == 1
    assert entries[0]["outcome_kind"] == "continuous"
    assert entries[0]["positive"] == ["ra1"] and entries[0]["negative"] == ["ra2"]


@pytest.mark.unit
def test_review1_unknown_kind_stays_apart_when_two_kinds_are_classified(ep):
    graph = _graph([
        _spec("ra1", "NCT00000001", "Tirzepatide 15 mg", "<0.001",
              title="Change From Baseline in Body Weight", unit="kg"),
        # same measure key "body weight", counted in participants: responder
        _spec("ra2", "NCT00000002", "Tirzepatide 15 mg", "<0.001", title="Body Weight",
              unit="percentage of participants"),
        _spec("ra3", "NCT00000003", "Tirzepatide 15 mg", "0.40", title="Change in Body Weight"),
    ])
    result = _run(ep, graph)
    claims = _claims(result)
    assert [claims[a]["outcome_kind"] for a in ("ra1", "ra2", "ra3")] == ["continuous", "responder", None]
    assert _entries(result) == []


@pytest.mark.unit
def test_review1_unknown_kind_only_group_still_contests(ep):
    graph = _graph([
        _spec("ra1", "NCT00000001", "Tirzepatide 15 mg", "<0.001", title="Change in Body Weight"),
        _spec("ra2", "NCT00000002", "Tirzepatide 15 mg", "0.40", title="Change in Body Weight"),
    ])
    entries = _entries(_run(ep, graph))
    assert len(entries) == 1 and entries[0]["outcome_kind"] is None


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
    # CR-01 (review round 1): thousands separators and ranges
    ("Metformin 1,000 mg", {1000.0}),
    ("Metformin 1,500 mg", {1500.0}),
    ("Metformin 2,000 mg", {2000.0}),
    ("Orforglipron 12-45 mg", {12.0, 45.0}),
    ("Orforglipron 12 to 45 mg", {12.0, 45.0}),
    ("Semaglutide 0.25 to 1 mg", {0.25, 1.0}),
    ("Semaglutide 0.25 mg to 1 mg", {0.25, 1.0}),
    ("Metformin 1,000/2,000 mg", {1000.0, 2000.0}),
    # WR-01 (review round 2): per-weight and concentration ranges are no dose
    ("10-20 mg/kg", set()),
    ("0.5-5.0 mg/ml", set()),
    ("Semaglutide 1 mg (0.5-5.0 mg/ml)", {1.0}),
    ("semaglutide 0.5-5.0 mg/ml SC liquid formulation", set()),
    # WR-02 (review round 2): a label number is no range end, and a dose
    # hyphen-attached to a name is read
    ("Cohort 2 - 10 mg Tirzepatide", {10.0}),
    ("Part 1 - 5 mg", {5.0}),
    ("Arm 3 – 15 mg", {15.0}),
    ("Group 1 to 4 mg", {4.0}),
    ("Dose level 2 - 10 mg", {10.0}),
    ("Period 2 to 10 mg", {10.0}),
    ("Week 4 - 2.4 mg", {2.4}),
    ("Semaglutide-1 mg", {1.0}),
    ("LY3298176-5mg", {5.0}),
    ("Semaglutide-2.4 mg", {2.4}),
    ("Cohort 1: 5 mg to 10 mg", {5.0, 10.0}),
    ("Arm A: 1-2 mg", {1.0, 2.0}),
    ("Tirzepatide 2.5-15 mg", {2.5, 15.0}),
    ("Orforglipron 12–45 mg", {12.0, 45.0}),
    ("Semaglutide 500 mcg to 1 mg", {0.5, 1.0}),
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
    (["Tirzepatide 12-45 mg"], "c3", None),
    (["Semaglutide 1 mg + Metformin 1,000 mg"], "c1", 1.0),
    (["Semaglutide 1 mg + Metformin 1,000 mg"], "c2", 1000.0),
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
def test_review1_thousands_separated_doses_do_not_pool(ep):
    graph = _graph([
        _spec("ra1", "NCT00000001", "Tirzepatide 1,000 mg", "<0.001"),
        _spec("ra2", "NCT00000002", "Tirzepatide 2,000 mg", "0.40"),
    ])
    result = _run(ep, graph)
    claims = _claims(result)
    assert claims["ra1"]["dose_mg"] == 1000.0 and claims["ra2"]["dose_mg"] == 2000.0
    assert _entries(result) == []
    graph = _graph([
        _spec("ra1", "NCT00000001", "Tirzepatide 1,500 mg", "<0.001"),
        _spec("ra2", "NCT00000002", "Tirzepatide 500 mg", "0.40"),
    ])
    assert _entries(_run(ep, graph)) == []
    graph = _graph([
        _spec("ra1", "NCT00000001", "Tirzepatide 1,000 mg", "<0.001"),
        _spec("ra2", "NCT00000002", "Tirzepatide 1000 mg", "0.40"),
    ])
    entries = _entries(_run(ep, graph))
    assert len(entries) == 1 and entries[0]["dose_aware"] is True and entries[0]["dose_mg"] == 1000.0


@pytest.mark.unit
def test_review1_dose_range_is_no_single_dose(ep):
    graph = _graph([
        _spec("ra1", "NCT00000001", "Tirzepatide 12-45 mg", "<0.001"),
        _spec("ra2", "NCT00000002", "Tirzepatide 45 mg", "0.40"),
    ])
    result = _run(ep, graph)
    assert _claims(result)["ra1"]["dose_mg"] is None
    entries = _entries(result)
    assert len(entries) == 1 and entries[0]["dose_aware"] is False


@pytest.mark.unit
@pytest.mark.parametrize("arm", [
    "Cohort 2 - 10 mg Tirzepatide",
    "Tirzepatide-10 mg",
    "Tirzepatide 10 mg (0.5-5.0 mg/ml)",
])
def test_review2_label_number_and_concentration_keep_the_dose(ep, arm):
    """A cohort number or a concentration range no longer erases the dose, so the
    group stays dose-aware and contests the same dose in another trial."""
    graph = _graph([
        _spec("ra1", "NCT00000001", arm, "<0.001"),
        _spec("ra2", "NCT00000002", "Tirzepatide 10 mg", "0.40"),
    ])
    result = _run(ep, graph)
    assert _claims(result)["ra1"]["dose_mg"] == 10.0
    entries = _entries(result)
    assert len(entries) == 1 and entries[0]["dose_aware"] is True and entries[0]["dose_mg"] == 10.0


@pytest.mark.unit
def test_review2_lowercase_or_in_effect_measure_keeps_the_kind_group(ep):
    """An effect measure with the word "or" stays continuous and still contests
    the continuous finding of another trial."""
    graph = _graph([
        _spec("ra1", "NCT00000001", "Tirzepatide 15 mg", "<0.001", effect="Mean difference or LS mean"),
        _spec("ra2", "NCT00000002", "Tirzepatide 15 mg", "0.40", unit="kg"),
    ])
    result = _run(ep, graph)
    assert _claims(result)["ra1"]["outcome_kind"] == "continuous"
    entries = _entries(result)
    assert len(entries) == 1 and entries[0]["outcome_kind"] == "continuous"


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


# --- CONTEST-03: arm types first, ambiguity, label conflicts -------------------

SEMA_NAMES = ["Semaglutide", "Metformin", "Insulin Glargine", "Tirzepatide"]


def _c03_graph(analysis_attrs=None, extra_nodes=(), extra_links=(), nct="NCT00000001", names=SEMA_NAMES):
    nodes = [_n(f"c_{name.split()[0].lower()}", "Compound", name) for name in names]
    nodes += [_trial(nct), _n("oc", "Outcome", CHANGE_TITLE)]
    attrs = {"source": "ctgov_results", "ctgov_nct_ids": [nct], "p_value": "<0.001"}
    attrs.update(analysis_attrs or {})
    nodes.append(_n("ra", "OutcomeAnalysis", f"{nct}: {CHANGE_TITLE}",
                    source_documents=[f"ctgov:{nct}"], attributes=attrs))
    nodes += list(extra_nodes)
    return {"nodes": nodes, "links": [_e("ra", "oc", "analyzes"), *extra_links]}


def _arm(title, arm_type, interventions=()):
    return {"title": title, "arm_type": arm_type, "interventions": list(interventions)}


@pytest.mark.unit
def test_contest03_add_on_background_is_dropped_by_arm_types(ep):
    titles = ["Semaglutide + Metformin", "Insulin Glargine + Metformin"]
    graph = _c03_graph({
        "compared_groups": titles, "unmatched_groups": titles,
        "ctgov_arm_groups": [_arm(titles[0], "EXPERIMENTAL"), _arm(titles[1], "ACTIVE_COMPARATOR")],
    })
    result = _run(ep, graph)
    finding = _claims(result)["ra"]
    assert finding["treatment"] == "Semaglutide"
    assert finding["treatment_basis"] == "registry_arm_type"
    assert result["summary"]["analysis_treatment_from_arm_type"] == 1


@pytest.mark.unit
def test_contest03_arm_types_come_before_the_title_rule(ep):
    titles = ["Tirzepatide", "Placebo"]
    arms = [_arm("Semaglutide", "EXPERIMENTAL"), _arm("Placebo", "PLACEBO_COMPARATOR")]
    graph = _c03_graph({"compared_groups": titles, "unmatched_groups": titles, "ctgov_arm_groups": arms})
    result = _run(ep, graph)
    finding = _claims(result)["ra"]
    assert finding["treatment"] == "Semaglutide"
    assert finding["treatment_basis"] == "registry_arm_type"
    assert result["summary"]["analysis_treatment_from_arm_type"] == 1
    assert result["summary"]["analysis_treatment_arm_type_disagreements"] == 1


@pytest.mark.unit
def test_contest03_assesses_edge_still_wins_over_arm_types(ep):
    titles = ["Tirzepatide", "Placebo"]
    arms = [_arm("Semaglutide", "EXPERIMENTAL"), _arm("Placebo", "PLACEBO_COMPARATOR")]
    graph = _c03_graph({"compared_groups": titles, "unmatched_groups": titles, "ctgov_arm_groups": arms},
                       extra_links=[_e("ra", "c_tirzepatide", "assesses_effect_of")])
    result = _run(ep, graph)
    finding = _claims(result)["ra"]
    assert finding["treatment"] == "Tirzepatide"
    assert "treatment_basis" not in finding
    assert result["summary"]["analysis_treatment_from_arm_type"] == 0
    assert result["summary"]["analysis_treatment_arm_type_disagreements"] == 1


@pytest.mark.unit
def test_contest03_agreement_leaves_no_basis_and_no_count(ep):
    titles = ["Semaglutide", "Placebo"]
    arms = [_arm("Semaglutide", "EXPERIMENTAL"), _arm("Placebo", "PLACEBO_COMPARATOR")]
    result = _run(ep, _c03_graph({"compared_groups": titles, "unmatched_groups": titles, "ctgov_arm_groups": arms}))
    finding = _claims(result)["ra"]
    assert finding["treatment"] == "Semaglutide"
    assert "treatment_basis" not in finding
    assert result["summary"]["analysis_treatment_from_arm_type"] == 0
    assert result["summary"]["analysis_treatment_arm_type_disagreements"] == 0


@pytest.mark.unit
def test_contest03_keywordless_active_comparator_is_marked_ambiguous(ep):
    titles = ["Tirzepatide", "Insulin Glargine"]
    result = _run(ep, _c03_graph({"compared_groups": titles, "unmatched_groups": titles}))
    finding = _claims(result)["ra"]
    assert finding["treatment"] is None
    assert finding["treatment_basis"] == "ambiguous_active_comparator"
    assert result["summary"]["analysis_treatment_ambiguous_active_comparator"] == 1
    assert result["summary"]["analysis_treatment_unresolved"] == 1


@pytest.mark.unit
def test_review1_unusable_arm_types_are_not_marked_ambiguous(ep):
    titles = ["Tirzepatide", "Insulin Glargine"]
    arms = [_arm("Tirzepatide", "EXPERIMENTAL"), _arm("Insulin Glargine", "EXPERIMENTAL")]
    result = _run(ep, _c03_graph({"compared_groups": titles, "unmatched_groups": titles, "ctgov_arm_groups": arms}))
    finding = _claims(result)["ra"]
    assert finding["treatment"] is None
    assert "treatment_basis" not in finding
    assert result["summary"]["analysis_treatment_ambiguous_active_comparator"] == 0
    assert result["summary"]["analysis_treatment_unresolved"] == 1


@pytest.mark.unit
def test_contest03_typed_arms_or_placebo_are_never_ambiguous(ep):
    titles = ["Tirzepatide", "Insulin Glargine"]
    arms = [_arm("Tirzepatide", "EXPERIMENTAL"), _arm("Insulin Glargine", "ACTIVE_COMPARATOR")]
    result = _run(ep, _c03_graph({"compared_groups": titles, "unmatched_groups": titles, "ctgov_arm_groups": arms}))
    assert _claims(result)["ra"]["treatment"] == "Tirzepatide"
    assert result["summary"]["analysis_treatment_ambiguous_active_comparator"] == 0
    titles = ["Tirzepatide", "Placebo"]
    result = _run(ep, _c03_graph({"compared_groups": titles, "unmatched_groups": titles}))
    finding = _claims(result)["ra"]
    assert finding["treatment"] == "Tirzepatide"
    assert "treatment_basis" not in finding
    assert result["summary"]["analysis_treatment_ambiguous_active_comparator"] == 0


def _cohort_graph(co1_name, co1_label, co2_name="Placebo", co2_label=None, extra_attrs=None):
    def cohort(i, name, label):
        return _n(i, "Cohort", name, attributes={"arm_label": label} if label else {})
    # Registry group titles follow the registry arm label, not the extracted name.
    attrs = {"compared_groups": [co1_label or co1_name, co2_label or co2_name], "unmatched_groups": []}
    attrs.update(extra_attrs or {})
    return _c03_graph(
        attrs,
        extra_nodes=[cohort("co1", co1_name, co1_label), cohort("co2", co2_name, co2_label)],
        extra_links=[_e("ra", "co1", "compares"), _e("ra", "co2", "compares")],
    )


@pytest.mark.unit
def test_contest03_label_conflict_prefers_the_registry_label(ep):
    result = _run(ep, _cohort_graph("Tirzepatide 5 mg", "Tirzepatide 15 mg"))
    finding = _claims(result)["ra"]
    assert finding["treatment"] == "Tirzepatide"
    # SA-01 ruling (review round 1): name and label disagree on the dose, so the
    # dose is unknown; the label still decides matching.
    assert finding["dose_mg"] is None
    assert finding["label_conflict"] == [
        {"cohort": "co1", "cohort_name": "Tirzepatide 5 mg", "arm_label": "Tirzepatide 15 mg"}
    ]
    assert result["summary"]["analysis_label_conflicts"] == 1


@pytest.mark.unit
def test_review1_label_conflict_on_compound_only_keeps_the_dose(ep):
    result = _run(ep, _cohort_graph("Semaglutide 15 mg", "Tirzepatide 15 mg"))
    finding = _claims(result)["ra"]
    assert finding["treatment"] == "Tirzepatide"
    assert finding["label_conflict"][0]["cohort"] == "co1"
    assert finding["dose_mg"] == 15.0


@pytest.mark.unit
def test_contest03_spacing_is_not_a_label_conflict(ep):
    result = _run(ep, _cohort_graph("Tirzepatide 15mg", "tirzepatide 15 mg"))
    finding = _claims(result)["ra"]
    assert "label_conflict" not in finding
    assert result["summary"]["analysis_label_conflicts"] == 0


@pytest.mark.unit
def test_contest03_placebo_named_cohort_with_active_label_is_active(ep):
    result = _run(ep, _cohort_graph("Placebo", "Tirzepatide 5 mg", co2_name="Placebo B"))
    finding = _claims(result)["ra"]
    assert finding["treatment"] == "Tirzepatide"
    assert finding["label_conflict"][0]["cohort"] == "co1"
    assert finding["dose_mg"] == 5.0


@pytest.mark.unit
def test_contest03_edge_treatment_basis_is_copied_and_counted(ep):
    link = {**_e("ra", "c_tirzepatide", "assesses_effect_of"),
            "attributes": {"source": "ctgov_results", "treatment_basis": "registry_arm_type"}}
    result = _run(ep, _c03_graph(extra_links=[link]))
    finding = _claims(result)["ra"]
    assert finding["treatment"] == "Tirzepatide"
    assert finding["treatment_basis"] == "registry_arm_type"
    assert result["summary"]["analysis_treatment_from_arm_type"] == 1


# --- WR-02 follow-up: withdrawn registry facts are not corroboration -----------

def _contest_graph(first_attrs=None):
    graph = _graph([_spec("ra1", "NCT00000001", "Tirzepatide", "<0.001"),
                    _spec("ra2", "NCT00000002", "Tirzepatide", "0.40")])
    for node in graph["nodes"]:
        if node["id"] == "ra1":
            node["attributes"].update(first_attrs or {})
    return graph


@pytest.mark.unit
def test_withdrawn_registry_analysis_takes_no_part_in_contests(ep):
    control = _run(ep, _contest_graph())
    assert len(_entries(control)) == 1
    result = _run(ep, _contest_graph({"ctgov_withdrawn": True}))
    assert _entries(result) == []
    finding = _claims(result)["ra1"]
    assert finding["registry_withdrawn"] is True
    assert finding["significant"] is True
    assert finding["significance_source"] == "ctgov_withdrawn"
    assert result["summary"]["analysis_registry_withdrawn"] == 1
    assert result["summary"]["analysis_by_source"]["ctgov_withdrawn"] == 1


@pytest.mark.unit
def test_withdrawn_by_nct_on_every_nct_equals_withdrawn(ep):
    result = _run(ep, _contest_graph({"ctgov_withdrawn_by_nct": {"nct00000001": True}}))
    assert _entries(result) == []
    assert _claims(result)["ra1"]["registry_withdrawn"] is True


def _supersede_graph(withdrawn):
    graph = _c03_graph({"compared_groups": ["Tirzepatide", "Placebo"], "unmatched_groups": ["Tirzepatide", "Placebo"],
                        **({"ctgov_withdrawn": True} if withdrawn else {})},
                       extra_links=[_e("ra", "c_tirzepatide", "assesses_effect_of")])
    graph["nodes"].append(_n("ex", "OutcomeAnalysis", "extracted", source_documents=["doc:x"],
                             attributes={"p_value": "0.5"}))
    graph["links"] += [_e("ex", "oc", "analyzes"), _e("ex", "c_tirzepatide", "assesses_effect_of"),
                       _e("ex", "trial:nct00000001", "reported_in")]
    return graph


@pytest.mark.unit
def test_withdrawn_registry_analysis_supersedes_nothing(ep):
    assert "superseded_by" in _claims(_run(ep, _supersede_graph(False)))["ex"]
    assert "superseded_by" not in _claims(_run(ep, _supersede_graph(True)))["ex"]


def _merged_graph(attrs, docs=("doc:x",)):
    graph = _c03_graph(extra_links=[_e("ra", "c_tirzepatide", "assesses_effect_of")])
    for node in graph["nodes"]:
        if node["id"] == "ra":
            node["attributes"] = {"sources": ["extracted", "ctgov_results"], **attrs}
            node["source_documents"] = list(docs)
    return graph


MERGED = {"p_value": "0.30", "registry_p_value": "0.001", "ctgov_nct_ids": ["NCT00000001"],
          "ci_lower": -0.5, "ci_upper": 0.4}


@pytest.mark.unit
def test_withdrawn_merged_analysis_is_graded_from_extracted_values(ep):
    control = _claims(_run(ep, _merged_graph(MERGED)))["ra"]
    assert control["significant"] is True
    assert control["significance_source"] == "ctgov_results"
    assert "ctgov:NCT00000001" in control["support_documents"]
    result = _run(ep, _merged_graph({**MERGED, "ctgov_withdrawn_by_nct": {"NCT00000001": True}}))
    finding = _claims(result)["ra"]
    assert finding["significant"] is False
    assert finding["significance_source"] == "extracted"
    assert finding["registry_withdrawn"] is True
    assert "ctgov:NCT00000001" not in finding["support_documents"]
    assert result["summary"]["analysis_registry_withdrawn"] == 1


@pytest.mark.unit
def test_review1_withdrawn_merged_analysis_drops_inherited_ctgov_document(ep):
    docs = ("doc:x", "ctgov:NCT00000001")
    control = _claims(_run(ep, _merged_graph(MERGED, docs=docs)))["ra"]
    assert "ctgov:NCT00000001" in control["support_documents"]
    finding = _claims(_run(ep, _merged_graph(
        {**MERGED, "ctgov_withdrawn_by_nct": {"NCT00000001": True}}, docs=docs)))["ra"]
    assert finding["support_documents"] == ["doc:x"]
    flagged = _claims(_run(ep, _merged_graph({**MERGED, "ctgov_withdrawn": True}, docs=("doc:x", "CTGOV:nct00000001"))))["ra"]
    assert flagged["support_documents"] == ["doc:x"]


@pytest.mark.unit
def test_review1_withdrawn_ctgov_document_is_absent_from_contest_entries(ep):
    graph = _contest_graph({
        "sources": ["extracted", "ctgov_results"], "source": None,
        "ctgov_withdrawn_by_nct": {"NCT00000001": True},
    })
    for node in graph["nodes"]:
        if node["id"] == "ra1":
            node["attributes"].pop("source")
            node["source_documents"] = ["doc:x", "ctgov:NCT00000001"]
    result = _run(ep, graph)
    finding = _claims(result)["ra1"]
    assert finding["registry_withdrawn"] is True and finding["significance_source"] == "extracted"
    assert "ctgov:NCT00000001" not in finding["support_documents"]
    entries = _entries(result)
    assert len(entries) == 1
    assert "ctgov:NCT00000001" not in entries[0]["support_documents"]
    assert {"source_document": "ctgov:NCT00000001"} not in entries[0]["mentions"]
    assert "ctgov:NCT00000002" in entries[0]["support_documents"]


@pytest.mark.unit
def test_withdrawn_partially_keeps_corroboration_for_the_other_nct(ep):
    attrs = {**MERGED, "ctgov_nct_ids": ["NCT00000001", "NCT00000002"],
             "ctgov_withdrawn_by_nct": {"NCT00000001": True}}
    finding = _claims(_run(ep, _merged_graph(attrs, docs=("doc:x", "ctgov:NCT00000001", "ctgov:NCT00000002"))))["ra"]
    assert finding["significance_source"] == "ctgov_results"
    assert "ctgov:NCT00000002" in finding["support_documents"]
    assert "ctgov:NCT00000001" not in finding["support_documents"]
    assert "registry_withdrawn" not in finding


@pytest.mark.unit
def test_withdrawn_registry_edge_is_ignored_but_extracted_edge_counts(ep):
    titles = ["Semaglutide", "Placebo"]
    arms = [_arm("Semaglutide", "EXPERIMENTAL"), _arm("Placebo", "PLACEBO_COMPARATOR")]
    base = {"compared_groups": titles, "unmatched_groups": titles, "ctgov_arm_groups": arms}

    def link(**attributes):
        return {**_e("ra", "c_tirzepatide", "assesses_effect_of"), "attributes": attributes}

    kept = _claims(_run(ep, _c03_graph(base, extra_links=[
        link(source="ctgov_results", treatment_basis="registry_arm_type")])))["ra"]
    assert kept["treatment"] == "Tirzepatide"
    dropped = _claims(_run(ep, _c03_graph(base, extra_links=[
        link(source="ctgov_results", treatment_basis="registry_arm_type", ctgov_withdrawn=True)])))["ra"]
    assert dropped["treatment"] == "Semaglutide"
    extracted = _claims(_run(ep, _c03_graph(base, extra_links=[
        link(ctgov_withdrawn_by_nct={"NCT00000001": True})])))["ra"]
    assert extracted["treatment"] == "Tirzepatide"


@pytest.mark.unit
def test_withdrawn_only_registry_graph_is_still_registry_mode(ep):
    graph = _contest_graph({"ctgov_withdrawn": True})
    for node in graph["nodes"]:
        if node["id"] == "ra2":
            node["attributes"]["ctgov_withdrawn"] = True
    assert ep._graph_has_registry_data(graph["nodes"]) is True
    result = _run(ep, graph)
    assert result["summary"]["analysis_registry_withdrawn"] == 2
