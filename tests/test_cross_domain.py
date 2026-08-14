"""Unit suite for the cross-domain epistemic rules engine
(core/cross_domain.py, core/cross_domain_compare.py).

Fixtures under tests/fixtures/cross_domain/ set metadata.domain to the real
domain names on purpose -- exactly like tests/fixtures/crosswalk/, these
fixtures route through the SHIPPED domains/*/crosswalk.yaml files (extended
with the new `edges:` sections this work adds) rather than a test-local
stub. Do not touch tests/fixtures/crosswalk/ -- that suite's assertions
must not move underneath this work.
"""

from __future__ import annotations

import pytest

from core.cross_domain_compare import (
    SUBTYPE_ABSENT,
    SUBTYPE_ATTRIBUTED_ELSEWHERE,
    SUBTYPE_GRANULARITY_VARIANT,
    classify_miss,
    coverage_ratio,
    resolve_band,
    tokenize,
)
from core.crosswalk_normalize import CrosswalkConfigError


def _cross_domain_fixture(fixtures_dir, name):
    return fixtures_dir / "cross_domain" / name


# ---------------------------------------------------------------------------
# Subtype classification (hand-built cases)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_classify_miss_absent_when_not_in_reference_anywhere():
    result = classify_miss("pancreatitis", {"nausea", "headache"}, {"nausea", "headache", "rash"})
    assert result == {"subtype": SUBTYPE_ABSENT, "reference_variants": []}


@pytest.mark.unit
def test_classify_miss_attributed_elsewhere_when_present_under_other_subject():
    result = classify_miss("rash", {"nausea", "headache"}, {"nausea", "headache", "rash"})
    assert result == {"subtype": SUBTYPE_ATTRIBUTED_ELSEWHERE, "reference_variants": []}


@pytest.mark.unit
def test_classify_miss_granularity_variant_names_the_collision():
    result = classify_miss(
        "abdominal pain upper", {"nausea", "abdominal pain"}, {"nausea", "abdominal pain"}
    )
    assert result["subtype"] == SUBTYPE_GRANULARITY_VARIANT
    assert result["reference_variants"] == ["abdominal pain"]


@pytest.mark.unit
def test_classify_miss_order_granularity_wins_over_attributed_elsewhere():
    # "rash upper" is both a superstring of the subject's own "rash" (would
    # classify as granularity_variant) AND present verbatim elsewhere in
    # the reference graph as "rash upper" attached to a different subject
    # (would classify as attributed_elsewhere). Granularity must win.
    result = classify_miss(
        "rash upper", {"nausea", "rash"}, {"nausea", "rash", "rash upper", "headache"}
    )
    assert result["subtype"] == SUBTYPE_GRANULARITY_VARIANT
    assert result["reference_variants"] == ["rash"]


# ---------------------------------------------------------------------------
# Rules spec loading -- eager validation against the spine
# ---------------------------------------------------------------------------


def _synthetic_spine():
    return {
        "graphs": {"pharmacovigilance": "/x", "fda-product-labels": "/y"},
        "axes": {"drug": {}, "adverse_event": {}},
    }


def _write_rules_yaml(tmp_path, content):
    path = tmp_path / "rules.yaml"
    path.write_text(content)
    return path


@pytest.mark.unit
def test_unknown_probe_graph_raises_naming_missing_and_available(tmp_path):
    from core.cross_domain import load_rules_spec

    path = _write_rules_yaml(
        tmp_path,
        """
rules:
  - name: r1
    type: safety_signal
    subject_axis: drug
    object_axis: adverse_event
    probe: not_a_real_graph
    reference: fda-product-labels
    compare: spine_keys
    severity: {absent: medium, attributed_elsewhere: high, granularity_variant: low}
    descriptions: {absent: "{object_key} {subject_key} {probe} {reference}"}
""",
    )
    with pytest.raises(CrosswalkConfigError) as exc_info:
        load_rules_spec(path, _synthetic_spine())
    message = str(exc_info.value)
    assert "not_a_real_graph" in message
    assert "pharmacovigilance" in message
    assert "fda-product-labels" in message


@pytest.mark.unit
def test_unknown_axis_raises_naming_axis_and_available(tmp_path):
    from core.cross_domain import load_rules_spec

    path = _write_rules_yaml(
        tmp_path,
        """
rules:
  - name: r1
    type: safety_signal
    subject_axis: not_a_real_axis
    object_axis: adverse_event
    probe: pharmacovigilance
    reference: fda-product-labels
    compare: spine_keys
    severity: {absent: medium, attributed_elsewhere: high, granularity_variant: low}
    descriptions: {absent: "{object_key} {subject_key} {probe} {reference}"}
""",
    )
    with pytest.raises(CrosswalkConfigError) as exc_info:
        load_rules_spec(path, _synthetic_spine())
    message = str(exc_info.value)
    assert "not_a_real_axis" in message
    assert "drug" in message
    assert "adverse_event" in message


@pytest.mark.unit
def test_unknown_compare_mode_raises_naming_mode(tmp_path):
    from core.cross_domain import load_rules_spec

    path = _write_rules_yaml(
        tmp_path,
        """
rules:
  - name: r1
    type: safety_signal
    subject_axis: drug
    object_axis: adverse_event
    probe: pharmacovigilance
    reference: fda-product-labels
    compare: not_a_real_mode
    severity: {absent: medium, attributed_elsewhere: high, granularity_variant: low}
    descriptions: {absent: "{object_key} {subject_key} {probe} {reference}"}
""",
    )
    with pytest.raises(CrosswalkConfigError) as exc_info:
        load_rules_spec(path, _synthetic_spine())
    assert "not_a_real_mode" in str(exc_info.value)


@pytest.mark.unit
def test_rules_spec_with_valid_rule_loads_cleanly(tmp_path):
    from core.cross_domain import load_rules_spec

    path = _write_rules_yaml(
        tmp_path,
        """
rules:
  - name: r1
    type: safety_signal
    subject_axis: drug
    object_axis: adverse_event
    probe: pharmacovigilance
    reference: fda-product-labels
    compare: spine_keys
    severity: {absent: medium, attributed_elsewhere: high, granularity_variant: low}
    descriptions: {absent: "{object_key} {subject_key} {probe} {reference}"}
""",
    )
    spec = load_rules_spec(path, _synthetic_spine())
    assert [r["name"] for r in spec["rules"]] == ["r1"]


# ---------------------------------------------------------------------------
# Description rendering
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_render_description_renders_known_fields():
    from core.cross_domain import render_description

    result = render_description("{object_key} vs {subject_key}", {"object_key": "a", "subject_key": "b"})
    assert result == "a vs b"


@pytest.mark.unit
def test_render_description_unknown_field_raises_config_error_naming_field():
    from core.cross_domain import render_description

    with pytest.raises(CrosswalkConfigError) as exc_info:
        render_description("{object_key} vs {not_a_real_field}", {"object_key": "a"})
    assert "not_a_real_field" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Projection
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_projection_matches_relation_in_either_direction_and_drops_unlisted():
    from core.cross_domain import project_edges

    node_index = {
        "drug": {"g": {"d1": ["drugkey"]}},
        "adverse_event": {"g": {"e1": ["ekey"], "e2": ["ekey2"]}},
    }
    graph = {
        "payload": {
            "links": [
                {"source": "d1", "target": "e1", "relation_type": "CAUSES"},
                {"source": "e2", "target": "d1", "relation_type": "OCCURRED_AFTER"},
                {"source": "d1", "target": "e2", "relation_type": "SOME_OTHER_RELATION"},
            ]
        }
    }
    result = project_edges(graph, "g", "drug", "adverse_event", node_index, ["CAUSES", "OCCURRED_AFTER"])
    assert result == {"drugkey": {"ekey", "ekey2"}}


@pytest.mark.unit
def test_projection_ignores_edge_endpoints_not_on_named_axes():
    from core.cross_domain import project_edges

    node_index = {
        "drug": {"g": {"d1": ["drugkey"]}},
        "adverse_event": {"g": {"e1": ["ekey"]}},
    }
    graph = {
        "payload": {
            "links": [
                {"source": "d1", "target": "unrelated_node", "relation_type": "CAUSES"},
                {"source": "unrelated_node", "target": "e1", "relation_type": "CAUSES"},
            ]
        }
    }
    result = project_edges(graph, "g", "drug", "adverse_event", node_index, ["CAUSES"])
    assert result == {}


# ---------------------------------------------------------------------------
# Rule isolation, sorting, output nesting -- full engine dispatch
# ---------------------------------------------------------------------------


def _build_labels_pv_spine(fixtures_dir):
    from core.crosswalk import build_spine, load_axis_spec, load_graphs, resolve_domain_configs

    labels_dir = _cross_domain_fixture(fixtures_dir, "labels")
    pv_dir = _cross_domain_fixture(fixtures_dir, "pv")
    graphs = load_graphs([str(labels_dir), str(pv_dir)])
    axis_spec = load_axis_spec("crosswalks/pharma.yaml")
    graphs = resolve_domain_configs(graphs, axis_spec)
    spine_result = build_spine(graphs, axis_spec)
    spine = {
        "spine_version": "1.0",
        "generated_at": "2026-08-13T00:00:00+00:00",
        "graphs": {key: str(g["dir"]) for key, g in graphs.items()},
        "axes": spine_result["axes"],
        "stats": spine_result["stats"],
    }
    return spine, graphs


@pytest.mark.unit
def test_end_to_end_all_three_subtypes_and_fully_covered_subject(fixtures_dir):
    from core.cross_domain import run_rules

    spine, graphs = _build_labels_pv_spine(fixtures_dir)
    rules_spec = {
        "rules": [
            {
                "name": "unlabeled_adverse_event",
                "type": "safety_signal",
                "subject_axis": "drug",
                "object_axis": "adverse_event",
                "probe": "pharmacovigilance",
                "reference": "fda-product-labels",
                "compare": "spine_keys",
                "severity": {"absent": "medium", "attributed_elsewhere": "high", "granularity_variant": "low"},
                "descriptions": {
                    "absent": "{object_key} is reported against {subject_key} in {probe} and does not appear anywhere in {reference}",
                    "attributed_elsewhere": "{object_key} appears in {reference} but never against {subject_key}, which reports it in {probe}",
                    "granularity_variant": "{object_key} reported against {subject_key} in {probe} is a granularity variant of {reference_variants} already recorded against it in {reference}",
                },
            }
        ]
    }
    result = run_rules(rules_spec, spine, graphs, include_advisory=False)

    findings = result["custom_findings"]["unlabeled_adverse_event"]
    subtypes = {f["evidence"]["subtype"] for f in findings}
    assert subtypes == {"absent", "attributed_elsewhere", "granularity_variant"}

    # fullycovinn's only probe pair (dizziness) is fully covered by the
    # label -- it must produce zero findings, proving the rule
    # distinguishes signal from a blanket miss.
    fullycov_findings = [f for f in findings if f["evidence"]["subject_key"] == "fullycovinn"]
    assert fullycov_findings == []

    # The patient-experience edge in the pv fixture (EXPERIENCED,
    # sampletide -> dizziness) is not in the configured relation list for
    # the drug/adverse_event axis pair and must never surface a finding.
    assert not any(f["evidence"]["object_key"] == "dizziness" for f in findings)

    stats = result["stats"]["unlabeled_adverse_event"]
    assert stats["status"] == "ok"
    assert stats["findings"] == len(findings)
    assert stats["subjects_with_findings"] == 1
    assert set(stats["by_subtype"]) == {"absent", "attributed_elsewhere", "granularity_variant"}

    # Output nests findings under super_domain.custom_findings by rule name
    # -- asserted directly on the shape run_rules returns.
    assert "unlabeled_adverse_event" in result["custom_findings"]

    # Sorted by subject key then object key.
    keys = [(f["evidence"]["subject_key"], f["evidence"]["object_key"]) for f in findings]
    assert keys == sorted(keys)


@pytest.mark.unit
def test_rule_isolation_error_status_and_remaining_rules_still_run(fixtures_dir):
    from core.cross_domain import run_rules

    spine, graphs = _build_labels_pv_spine(fixtures_dir)
    good_rule = {
        "name": "unlabeled_adverse_event",
        "type": "safety_signal",
        "subject_axis": "drug",
        "object_axis": "adverse_event",
        "probe": "pharmacovigilance",
        "reference": "fda-product-labels",
        "compare": "spine_keys",
        "severity": {"absent": "medium", "attributed_elsewhere": "high", "granularity_variant": "low"},
        "descriptions": {
            "absent": "{object_key} vs {subject_key}",
            "attributed_elsewhere": "{object_key} vs {subject_key}",
            "granularity_variant": "{object_key} vs {subject_key}",
        },
    }
    # This rule's description template references a field the engine does
    # not supply -- it passes eager load-time validation (template
    # correctness isn't checked there) but raises at render time, which is
    # exactly the runtime failure per-rule isolation exists to contain.
    broken_rule = {
        **good_rule,
        "name": "broken_rule",
        "descriptions": {
            "absent": "{object_key} vs {not_a_real_field}",
            "attributed_elsewhere": "{object_key} vs {not_a_real_field}",
            "granularity_variant": "{object_key} vs {not_a_real_field}",
        },
    }
    rules_spec = {"rules": [broken_rule, good_rule]}
    result = run_rules(rules_spec, spine, graphs, include_advisory=False)

    assert result["stats"]["broken_rule"]["status"] == "error"
    assert "not_a_real_field" in result["stats"]["broken_rule"]["error"]
    assert result["custom_findings"]["broken_rule"] == [
        {
            "rule_name": "broken_rule",
            "status": "error",
            "error": result["stats"]["broken_rule"]["error"],
        }
    ]

    # The rule after the broken one still produced findings.
    assert result["stats"]["unlabeled_adverse_event"]["status"] == "ok"
    assert len(result["custom_findings"]["unlabeled_adverse_event"]) > 0


# ---------------------------------------------------------------------------
# Config safety: the new edges section must be inert for the spine builder
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_edges_section_is_inert_for_spine_builder(fixtures_dir):
    from core.crosswalk import build_spine, load_axis_spec, load_graphs, resolve_domain_configs

    labels_dir = _cross_domain_fixture(fixtures_dir, "labels")
    pv_dir = _cross_domain_fixture(fixtures_dir, "pv")
    graphs = load_graphs([str(labels_dir), str(pv_dir)])
    axis_spec = load_axis_spec("crosswalks/pharma.yaml")
    graphs = resolve_domain_configs(graphs, axis_spec)
    with_edges = build_spine(graphs, axis_spec)

    stripped = {
        key: {**g, "domain_config": {k: v for k, v in (g["domain_config"] or {}).items() if k != "edges"}}
        for key, g in graphs.items()
    }
    without_edges = build_spine(stripped, axis_spec)

    assert with_edges["axes"] == without_edges["axes"]


# ---------------------------------------------------------------------------
# Token coverage primitives
# ---------------------------------------------------------------------------

_STOPWORDS = {"was", "not", "in", "this", "the", "a", "of"}


@pytest.mark.unit
def test_tokenize_honours_pattern_min_length_and_stopwords():
    tokens = tokenize(
        "Fasting glucose change was measured in this study.",
        pattern="[a-z]+",
        min_token_length=3,
        stopwords=_STOPWORDS,
    )
    assert tokens == {"fasting", "glucose", "change", "measured", "study"}


@pytest.mark.unit
def test_tokenize_all_stopwords_yields_empty_set():
    tokens = tokenize("was not in this", pattern="[a-z]+", min_token_length=1, stopwords=_STOPWORDS)
    assert tokens == set()


@pytest.mark.unit
def test_coverage_ratio_all_present_scores_one():
    assert coverage_ratio({"fasting", "glucose"}, {"fasting", "glucose", "change"}) == 1.0


@pytest.mark.unit
def test_coverage_ratio_no_overlap_scores_zero():
    assert coverage_ratio({"quality", "life"}, {"fasting", "glucose"}) == 0.0


@pytest.mark.unit
def test_resolve_band_boundary_is_exclusive_on_the_upper_edge():
    bands = [
        {"below": 0.34, "severity": "high"},
        {"below": 0.67, "severity": "medium"},
        {"below": 1.0, "severity": "low"},
    ]
    # Exactly on the boundary -- must land in the NEXT band, not this one.
    assert resolve_band(0.34, bands) == "medium"
    assert resolve_band(0.33, bands) == "high"
    assert resolve_band(0.5, bands) == "medium"
    assert resolve_band(0.9, bands) == "low"


# ---------------------------------------------------------------------------
# text_tokens compare mode -- full engine dispatch (coverage rule)
# ---------------------------------------------------------------------------

_COVERAGE_RULE_CFG = {
    "name": "coverage_gap",
    "type": "evidence_gap",
    "subject_axis": "trial",
    "object_axis": "outcome",
    "probe": "clinicaltrials",
    "reference": "fda-product-labels",
    "compare": "text_tokens",
    "text_tokens": {
        "token_pattern": "[a-z]+",
        "min_token_length": 3,
        "report_below": 0.9,
        "severity_bands": [
            {"below": 0.34, "severity": "high"},
            {"below": 0.67, "severity": "medium"},
            {"below": 1.0, "severity": "low"},
        ],
        "stopwords": ["was", "not", "in", "this"],
    },
    "descriptions": {
        "gap": "{object_key} is measured in {subject_key} per {probe}, but {reference} asserts only {coverage_ratio} of its terms for that trial"
    },
}


def _build_labels_ct_spine(fixtures_dir):
    from core.crosswalk import build_spine, load_axis_spec, load_graphs, resolve_domain_configs

    labels_dir = _cross_domain_fixture(fixtures_dir, "labels")
    ct_dir = _cross_domain_fixture(fixtures_dir, "ct")
    graphs = load_graphs([str(labels_dir), str(ct_dir)])
    axis_spec = load_axis_spec("crosswalks/pharma.yaml")
    graphs = resolve_domain_configs(graphs, axis_spec)
    spine_result = build_spine(graphs, axis_spec)
    spine = {
        "spine_version": "1.0",
        "generated_at": "2026-08-13T00:00:00+00:00",
        "graphs": {key: str(g["dir"]) for key, g in graphs.items()},
        "axes": spine_result["axes"],
        "stats": spine_result["stats"],
    }
    return spine, graphs


@pytest.mark.unit
def test_text_tokens_mode_grades_split_and_counts_covered(fixtures_dir):
    from core.cross_domain import run_rules

    spine, graphs = _build_labels_ct_spine(fixtures_dir)
    result = run_rules({"rules": [_COVERAGE_RULE_CFG]}, spine, graphs, include_advisory=False)

    findings = result["custom_findings"]["coverage_gap"]
    by_object = {f["evidence"]["object_key"]: f for f in findings}

    # fully covered (ratio 1.0, >= report_below) -> no finding at all.
    assert "fasting glucose change" not in by_object
    # partially covered (ratio 0.5) -> medium band.
    assert by_object["body weight kidney function"]["severity"] == "medium"
    assert by_object["body weight kidney function"]["evidence"]["coverage_ratio"] == 0.5
    # zero overlap (ratio 0.0) -> top (high) band.
    assert by_object["quality of life score"]["severity"] == "high"
    assert by_object["quality of life score"]["evidence"]["coverage_ratio"] == 0.0

    # The CT-only trial (no counterpart in the labels fixture) must not be
    # compared at all -- its outcome never appears in the findings.
    assert "ct only outcome" not in by_object

    stats = result["stats"]["coverage_gap"]
    assert stats["objects_compared"] == 3
    assert stats["objects_covered"] == 1
    assert stats["findings"] == 2


# ---------------------------------------------------------------------------
# Advisory gate
# ---------------------------------------------------------------------------


def _advisory_rule_cfg():
    return {
        "name": "off_label_exposure",
        "type": "exposure_signal",
        "subject_axis": "drug",
        "object_axis": "adverse_event",
        "probe": "pharmacovigilance",
        "reference": "fda-product-labels",
        "compare": "spine_keys",
        "advisory": True,
        "caveat": "Advisory only. Treat as a review queue, never as a count.",
        "descriptions": {
            "absent": "{object_key} vs {subject_key}",
            "attributed_elsewhere": "{object_key} vs {subject_key}",
            "granularity_variant": "{object_key} vs {subject_key}",
        },
    }


@pytest.mark.unit
def test_advisory_rule_skipped_without_opt_in(fixtures_dir):
    from core.cross_domain import run_rules

    spine, graphs = _build_labels_pv_spine(fixtures_dir)
    result = run_rules({"rules": [_advisory_rule_cfg()]}, spine, graphs, include_advisory=False)

    assert "off_label_exposure" not in result["custom_findings"]
    assert result["stats"]["off_label_exposure"] == {"status": "skipped-advisory"}


@pytest.mark.unit
def test_advisory_rule_forced_advisory_with_opt_in_and_caveat(fixtures_dir):
    from core.cross_domain import run_rules

    spine, graphs = _build_labels_pv_spine(fixtures_dir)
    result = run_rules({"rules": [_advisory_rule_cfg()]}, spine, graphs, include_advisory=True)

    findings = result["custom_findings"]["off_label_exposure"]
    assert findings, "expected the advisory rule to produce findings when opted in"
    for finding in findings:
        assert finding["severity"] == "advisory"
        assert finding["evidence"]["caveat"] == "Advisory only. Treat as a review queue, never as a count."
