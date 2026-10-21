"""Epistemic-health normalizer: every shipped claims-layer shape becomes one payload."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CORPORA = ROOT / "tests" / "corpora"
GLP1 = CORPORA / "06_glp1_landscape" / "output-v3"
PICALM = CORPORA / "01_picalm_alzheimers" / "output"
PV = CORPORA / "09_pharmacovigilance" / "output"
FDA = CORPORA / "08_fda_labels" / "output"

NOT_RUN = {"available": False, "status_counts": [], "sections": []}

pytestmark = pytest.mark.unit


def _load(corpus: Path) -> tuple[dict, list[dict]]:
    claims = json.loads((corpus / "claims_layer.json").read_text())
    graph = json.loads((corpus / "graph_data.json").read_text())
    return claims, graph["nodes"]


def _build(corpus: Path) -> dict:
    from core.epistemic_health import build_epistemic_health

    claims, nodes = _load(corpus)
    return build_epistemic_health(claims, nodes)


def _section(result: dict, key: str) -> dict:
    return next(s for s in result["sections"] if s["key"] == key)


def _name(nodes: list[dict], node_id: str) -> str:
    return next(n for n in nodes if n["id"] == node_id)["name"]


def test_glp1_v3_sections_and_status_counts():
    result = _build(GLP1)
    assert result["available"] is True
    assert [s["key"] for s in result["sections"]] == [
        "contradictions",
        "contested_claims",
        "hypotheses",
    ]
    assert [s["count"] for s in result["sections"]] == [2, 33, 2]
    assert len(_section(result, "contested_claims")["items"]) == 33
    assert result["status_counts"] == [
        {"status": "asserted", "count": 758},
        {"status": "prophetic", "count": 61},
        {"status": "hypothesized", "count": 31},
        {"status": "speculative", "count": 2},
        {"status": "unclassified", "count": 2},
        {"status": "negative", "count": 1},
    ]
    assert sum(s["count"] for s in result["status_counts"]) == 855


def test_glp1_first_contradiction():
    result = _build(GLP1)
    item = _section(result, "contradictions")["items"][0]
    assert item["title"] == "semaglutide is indicated for Obesity"
    assert item["kind"] == "contradiction"
    assert [e["id"] for e in item["entities"]] == ["compound:semaglutide", "disease:obesity"]
    assert [e["name"] for e in item["entities"]] == ["semaglutide", "Obesity"]
    assert all(e["entity_type"] for e in item["entities"])
    assert len(item["statements"]) == 2
    low, high = item["statements"]
    assert low["confidence"] == 0.55
    assert low["document"] == "patent_03_us10335462b2_semaglutide_longacting"
    assert high["confidence"] == 0.97
    assert high["document"] == "pmid_35650449"
    assert len(item["documents"]) == 7
    assert len(set(item["documents"])) == 7
    assert item["question"] == (
        "Why do sources disagree on whether semaglutide is indicated for Obesity?"
    )


def test_glp1_contested_claim_uses_source_document_mentions():
    claims, nodes = _load(GLP1)
    result = _build(GLP1)
    item = _section(result, "contested_claims")["items"][0]
    nash = _name(nodes, "disease:non_alcoholic_steatohepatitis")
    assert item["title"] == f"semaglutide is indicated for {nash}"
    assert item["kind"] == "contested_claim"
    assert item["statements"], "mentions with source_document must yield statements"
    assert item["statements"][0]["document"] == "pmid_35650449"
    assert len(item["statements"]) <= 2
    raw = claims["super_domain"]["contested_claims"][0]
    for doc in raw["support_documents"]:
        assert doc in item["documents"]


def test_glp1_hypothesis():
    claims, _ = _load(GLP1)
    result = _build(GLP1)
    item = _section(result, "hypotheses")["items"][0]
    raw = claims["super_domain"]["hypotheses"][0]
    label = " ".join(raw["label"].split())
    assert item["title"] == label
    assert item["kind"] == "hypothesis"
    assert item["statements"] == []
    assert len(item["entities"]) == 68
    assert item["documents"] == list(dict.fromkeys(raw["support_documents"]))
    assert item["question"] == f"What evidence supports the hypothesis: {label}?"


def test_picalm_legacy_shape():
    result = _build(PICALM)
    keys = [s["key"] for s in result["sections"]]
    assert keys == ["contradictions", "hypotheses"]
    contradiction = _section(result, "contradictions")
    assert contradiction["count"] == 1
    item = contradiction["items"][0]
    assert len(item["statements"]) == 2
    assert {s["document"] for s in item["statements"]} == {"pmid_31385771", "pmid_26611835"}
    assert _section(result, "hypotheses")["count"] == 1
    assert {"status": "contested", "count": 7} in result["status_counts"]


def test_pharmacovigilance_conflicts_and_gaps():
    result = _build(PV)
    assert [s["key"] for s in result["sections"]] == ["conflicts", "coverage_gaps"]
    conflicts = _section(result, "conflicts")
    assert conflicts["count"] == 3
    item = conflicts["items"][0]
    assert item["title"] == "Myalgia — Not recovered/not resolved"
    assert item["entities"] == []
    assert item["statements"] == [
        {"text": "Conflicting terms: resolved vs not recovered", "document": "", "confidence": None}
    ]
    assert item["question"].startswith("What is behind this conflict: ")
    gaps = _section(result, "coverage_gaps")
    assert gaps["count"] == 2
    gap = gaps["items"][0]
    assert gap["title"] == "No TemporalRelationship entities found in graph"
    assert gap["kind"] == "coverage_gap"
    assert gap["question"] == "What is missing: No TemporalRelationship entities found in graph?"
    assert {s["status"] for s in result["status_counts"]} == {
        "asserted",
        "hypothesized",
        "unverified",
    }


def test_fda_labels_zero_counts_dropped_and_gaps_capped():
    from core.epistemic_health import MAX_ITEMS_PER_SECTION

    result = _build(FDA)
    statuses = {s["status"] for s in result["status_counts"]}
    assert "established" not in statuses and "theoretical" not in statuses
    assert statuses == {"observed", "reported"}
    assert [s["key"] for s in result["sections"]] == ["coverage_gaps"]
    gaps = result["sections"][0]
    assert gaps["count"] == 417
    assert len(gaps["items"]) == MAX_ITEMS_PER_SECTION == 50


def test_contracts_risks_synthetic():
    from core.epistemic_health import build_epistemic_health

    claims = {
        "super_domain": {
            "risks": [
                {
                    "id": "R1",
                    "severity": "high",
                    "source_type": "conflict",
                    "source_id": "party:acme",
                    "description": "Overlapping exclusivity",
                    "suggested_action": "Review clause 4",
                    "contracts_affected": ["c1.pdf", "c2.pdf"],
                }
            ]
        }
    }
    nodes = [{"id": "party:acme", "name": "Acme", "entity_type": "PARTY"}]
    result = build_epistemic_health(claims, nodes)
    assert result["available"] is True
    assert [s["key"] for s in result["sections"]] == ["risks"]
    item = result["sections"][0]["items"][0]
    assert item["title"] == "Overlapping exclusivity"
    assert item["kind"] == "risk"
    assert item["entities"] == [{"id": "party:acme", "name": "Acme", "entity_type": "PARTY"}]
    assert item["statements"] == [
        {"text": "Suggested action: Review clause 4", "document": "", "confidence": None}
    ]
    assert item["documents"] == ["c1.pdf", "c2.pdf"]
    assert item["question"] == "What should I do about this risk: Overlapping exclusivity?"


@pytest.mark.parametrize(
    "bad",
    [{}, None, "x", [], {"super_domain": None, "summary": None}],
    ids=["empty", "none", "str", "list", "null-parts"],
)
def test_empty_and_bad_input(bad):
    from core.epistemic_health import build_epistemic_health

    assert build_epistemic_health(bad, None) == NOT_RUN
    assert build_epistemic_health(bad, []) == NOT_RUN


def test_malformed_items_are_skipped():
    from core.epistemic_health import build_epistemic_health

    valid = {
        "source": "a:x",
        "target": "b:y",
        "relation_type": "TREATS",
        "mentions": [{"document": "d1", "evidence": "e", "confidence": 0.5}],
    }
    claims = {
        "super_domain": {
            "contradictions": ["s", None, 3, {}, valid],
            "hypotheses": [{"label": None, "member_entities": "notalist"}, "oops"],
        }
    }
    result = build_epistemic_health(claims, [])
    contradictions = _section(result, "contradictions")
    assert contradictions["count"] == 1
    assert len(contradictions["items"]) == 1
    for section in result["sections"]:
        assert section["count"] >= len(section["items"]) >= 1


def test_status_counts_accept_only_positive_ints():
    from core.epistemic_health import build_epistemic_health

    claims = {
        "summary": {
            "epistemic_status_counts": {
                "a": "7",
                "b": -1,
                "c": None,
                "d": 2.5,
                "e": 3,
                "f": True,
                "g": 0,
            }
        }
    }
    result = build_epistemic_health(claims, [])
    assert result["status_counts"] == [{"status": "e", "count": 3}]
    assert result["available"] is True
    assert result["sections"] == []


def test_entities_absent_from_nodes_are_dropped_but_title_uses_fallback_name():
    from core.epistemic_health import build_epistemic_health

    claims = {
        "super_domain": {
            "contradictions": [
                {
                    "source": "compound:drug_a",
                    "target": "disease:rare_thing",
                    "relation_type": "TREATS",
                    "mentions": [{"document": "d1", "evidence": "e", "confidence": 0.4}],
                }
            ]
        }
    }
    nodes = [{"id": "compound:drug_a", "name": "Drug A", "entity_type": "COMPOUND"}]
    item = build_epistemic_health(claims, nodes)["sections"][0]["items"][0]
    assert [e["id"] for e in item["entities"]] == ["compound:drug_a"]
    assert item["title"] == "Drug A treats rare thing"


def test_relation_id_fallback():
    from core.epistemic_health import build_epistemic_health

    claims = {
        "super_domain": {
            "contested_claims": [
                {
                    "relation_id": "compound:a|TREATS|disease:b",
                    "evidence": "x",
                    "source_document": "d1",
                    "confidence": 0.7,
                }
            ]
        }
    }
    nodes = [
        {"id": "compound:a", "name": "Alpha", "entity_type": "COMPOUND"},
        {"id": "disease:b", "name": "Beta", "entity_type": "DISEASE"},
    ]
    item = build_epistemic_health(claims, nodes)["sections"][0]["items"][0]
    assert item["title"] == "Alpha treats Beta"
    assert item["statements"] == [{"text": "x", "document": "d1", "confidence": 0.7}]
    assert item["documents"] == ["d1"]


def test_unknown_verbs_are_humanized():
    from core.epistemic_health import build_epistemic_health

    def title(rel: str) -> str:
        claims = {
            "super_domain": {
                "contested_claims": [
                    {"source": "a:x", "target": "b:y", "relation_type": rel, "evidence": "e"}
                ]
            }
        }
        nodes = [
            {"id": "a:x", "name": "X", "entity_type": "T"},
            {"id": "b:y", "name": "Y", "entity_type": "T"},
        ]
        return build_epistemic_health(claims, nodes)["sections"][0]["items"][0]["title"]

    assert title("HAS_SIDE_EFFECT") == "X has side effect Y"
    assert title("DEVELOPES") == "X develops Y"


def test_ignored_keys_produce_no_section():
    from core.epistemic_health import build_epistemic_health

    claims = {
        "super_domain": {
            "custom_findings": {"r": [{"x": 1}]},
            "cross_document_entities": [{"name": "n"}],
            "cross_contract_entities": [{"name": "n"}],
            "zzz": [{"title": "t"}],
        }
    }
    assert build_epistemic_health(claims, []) == NOT_RUN


def test_json_round_trip():
    result = _build(GLP1)
    assert json.loads(json.dumps(result)) == result


def test_question_truncation():
    from core.epistemic_health import build_epistemic_health

    claims = {"super_domain": {"conflicts": [{"type": "contradiction", "evidence": "word " * 200}]}}
    item = build_epistemic_health(claims, [])["sections"][0]["items"][0]
    assert len(item["question"]) < 260
    assert item["question"].endswith("?")
