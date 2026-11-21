"""Pharmacovigilance schema contract, build behaviour, and epistemic CUSTOM_RULES.

Pins Domain Builder iterations 2-3:
- relation names must survive sift-kg's passive-to-active rewrite (no ``*_BY``);
- every relation declares typed endpoints that exist and a known category;
- a sift-kg build keeps every schema relation name, flips reversed edges, and
  keeps an Indication and a same-condition AdverseEvent apart when the
  AdverseEvent is named per the SKILL.md rule;
- the three CUSTOM_RULES fire on the patterns they target.
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest
import yaml

from core.graph_display import RELATION_CATEGORIES

ROOT = Path(__file__).resolve().parent.parent
DOMAIN = ROOT / "domains" / "pharmacovigilance"
SCHEMA = yaml.safe_load((DOMAIN / "domain.yaml").read_text())
RELATIONS = SCHEMA["relation_types"]
ENTITIES = set(SCHEMA["entity_types"])

SECTION2 = {
    "SUPPORTS", "ASSESSES", "INTERACTS_WITH", "PROGRESSED_TO", "CHALLENGES",
    "HAS_ONSET", "APPLIES_TO", "HAS_CONDITION", "WORSENING_OF",
}


def _epistemic():
    spec = importlib.util.spec_from_file_location("pv_epistemic", DOMAIN / "epistemic.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --- schema contract -------------------------------------------------------


def test_no_passive_relation_names():
    passive = [r for r in RELATIONS if re.match(r"^[A-Z_]+_BY$", r)]
    assert passive == [], "sift-kg rewrites *_BY relation names at build time"


@pytest.mark.parametrize("rel", sorted(RELATIONS))
def test_relation_endpoints_typed_and_known(rel):
    cfg = RELATIONS[rel]
    assert cfg.get("source_types") and cfg.get("target_types")
    assert set(cfg["source_types"]) <= ENTITIES
    assert set(cfg["target_types"]) <= ENTITIES
    assert cfg["category"] in RELATION_CATEGORIES


def test_section2_relations_present():
    assert SECTION2 <= set(RELATIONS)
    assert RELATIONS["TRIGGERED"]["target_types"] == ["RegulatoryAction"]
    assert RELATIONS["INTERACTS_WITH"].get("symmetric") is True


def test_every_entity_type_is_reachable():
    touched = set()
    for cfg in RELATIONS.values():
        touched |= set(cfg["source_types"]) | set(cfg["target_types"])
    assert touched == ENTITIES


def test_skill_table_matches_schema():
    skill = (DOMAIN / "SKILL.md").read_text()
    for rel, cfg in RELATIONS.items():
        row = f"| {rel} | {'/'.join(cfg['source_types'])} → {'/'.join(cfg['target_types'])}"
        assert row in skill, rel


# --- sift-kg build ---------------------------------------------------------


def _entity(name, etype, **attrs):
    return {"name": name, "entity_type": etype, "attributes": attrs, "confidence": 0.9, "context": name}


def _rel(src, rel, tgt):
    return {"relation_type": rel, "source_entity": src, "target_entity": tgt, "confidence": 0.9, "evidence": "x"}


@pytest.fixture
def built_graph(tmp_path):
    sift = pytest.importorskip("sift_kg")
    doc = {
        "document_id": "synthetic_pv_case",
        "document_path": "",
        "chunks_processed": 1,
        "domain_name": "pharmacovigilance",
        "entities": [
            _entity("Patient (case 1)", "Patient"),
            _entity("Reporter (case 1, physician)", "Reporter"),
            _entity("FAERS spontaneous report", "ReportType"),
            _entity("simvastatin", "Drug"),
            _entity("clarithromycin", "Concomitant"),
            _entity("Rhabdomyolysis", "AdverseEvent", meddra_pt="Rhabdomyolysis"),
            _entity("Acute kidney injury", "AdverseEvent", meddra_pt="Acute kidney injury"),
            _entity("plasma cell myeloma", "Indication"),
            _entity("Plasma cell myeloma (adverse event)", "AdverseEvent", meddra_pt="Plasma cell myeloma"),
            _entity("onset: days", "TemporalRelationship"),
            _entity("simvastatin dechallenge (case 1)", "DechallengeRechallenge"),
            _entity("simvastatin-rhabdomyolysis signal", "CausalitySignal"),
            _entity("label change: contraindication", "RegulatoryAction"),
        ],
        "relations": [
            _rel("Patient (case 1)", "EXPERIENCED", "Rhabdomyolysis"),
            _rel("Reporter (case 1, physician)", "REPORTS", "FAERS spontaneous report"),
            _rel("Rhabdomyolysis", "CAUSES", "simvastatin"),  # reversed on purpose
            _rel("simvastatin", "INTERACTS_WITH", "clarithromycin"),
            _rel("Rhabdomyolysis", "PROGRESSED_TO", "Acute kidney injury"),
            _rel("Rhabdomyolysis", "HAS_ONSET", "onset: days"),
            _rel("simvastatin dechallenge (case 1)", "CHALLENGES", "simvastatin"),
            _rel("simvastatin dechallenge (case 1)", "SUPPORTS", "simvastatin-rhabdomyolysis signal"),
            _rel("simvastatin-rhabdomyolysis signal", "ASSESSES", "simvastatin"),
            _rel("simvastatin-rhabdomyolysis signal", "ASSESSES", "Rhabdomyolysis"),
            _rel("simvastatin-rhabdomyolysis signal", "TRIGGERED", "label change: contraindication"),
            _rel("label change: contraindication", "APPLIES_TO", "simvastatin"),
            _rel("Patient (case 1)", "HAS_CONDITION", "plasma cell myeloma"),
            _rel("Plasma cell myeloma (adverse event)", "WORSENING_OF", "plasma cell myeloma"),
        ],
    }
    out = tmp_path / "out"
    (out / "extractions").mkdir(parents=True)
    (out / "extractions" / "synthetic_pv_case.json").write_text(json.dumps(doc))
    sift.run_build(out, sift.load_domain(domain_path=DOMAIN / "domain.yaml"))
    return json.loads((out / "graph_data.json").read_text())


@pytest.mark.integration
def test_build_keeps_schema_names_and_directions(built_graph):
    nodes = {n["id"]: n for n in built_graph["nodes"]}
    seen = {}
    for link in built_graph["links"]:
        rel = link["relation_type"]
        if rel == "MENTIONED_IN":
            continue
        assert rel in RELATIONS, f"off-schema relation {rel}"
        cfg = RELATIONS[rel]
        s, t = nodes[link["source"]]["entity_type"], nodes[link["target"]]["entity_type"]
        ok = s in cfg["source_types"] and t in cfg["target_types"]
        if cfg.get("symmetric"):
            ok = ok or (t in cfg["source_types"] and s in cfg["target_types"])
        assert ok, f"{rel} {s}->{t}"
        seen[rel] = seen.get(rel, 0) + 1
    assert SECTION2 <= set(seen)
    assert {"CAUSES", "REPORTS", "TRIGGERED"} <= set(seen)


@pytest.mark.integration
def test_indication_and_event_stay_separate(built_graph):
    types = {n["name"].lower(): n["entity_type"] for n in built_graph["nodes"]}
    assert types["plasma cell myeloma"] == "Indication"
    assert types["plasma cell myeloma (adverse event)"] == "AdverseEvent"


# --- CUSTOM_RULES ----------------------------------------------------------


def _n(i, t):
    return {"id": i, "name": i, "entity_type": t}


def _l(s, r, t):
    return {"source": s, "target": t, "relation_type": r}


def test_custom_rules_registered():
    names = [r.__name__ for r in _epistemic().CUSTOM_RULES]
    assert names == ["confounding_by_indication", "unanchored_causality_signal", "interaction_signal"]


def test_confounding_by_indication_flags_treating_drug():
    mod = _epistemic()
    nodes = [_n("len", "Drug"), _n("pcm", "Indication"), _n("pcm_ae", "AdverseEvent"), _n("other", "Drug")]
    links = [_l("len", "INDICATED_FOR", "pcm"), _l("pcm_ae", "WORSENING_OF", "pcm"),
             _l("pcm_ae", "OCCURRED_AFTER", "len"), _l("other", "CAUSES", "pcm_ae")]
    [f] = mod.confounding_by_indication(nodes, links, {})
    assert f["severity"] == "WARNING"
    assert f["evidence"]["implicated_drugs"] == ["len"]


def test_confounding_by_indication_info_without_treating_drug():
    mod = _epistemic()
    nodes = [_n("pcm", "Indication"), _n("pcm_ae", "AdverseEvent")]
    [f] = mod.confounding_by_indication(nodes, [_l("pcm_ae", "WORSENING_OF", "pcm")], {})
    assert f["severity"] == "INFO" and f["evidence"]["implicated_drugs"] == []


def test_unanchored_signal():
    mod = _epistemic()
    nodes = [_n("s1", "CausalitySignal"), _n("s2", "CausalitySignal"), _n("d", "Drug"), _n("e", "AdverseEvent")]
    links = [_l("s1", "ASSESSES", "d"), _l("s1", "ASSESSES", "e"), _l("s2", "ASSESSES", "d")]
    [f] = mod.unanchored_causality_signal(nodes, links, {})
    assert f["evidence"]["signal"] == "s2" and f["evidence"]["missing"] == ["adverse_event"]


def test_interaction_signal_shared_event():
    mod = _epistemic()
    nodes = [_n("a", "Drug"), _n("b", "Drug"), _n("e", "AdverseEvent"), _n("c", "Drug")]
    links = [_l("a", "INTERACTS_WITH", "b"), _l("b", "INTERACTS_WITH", "a"),
             _l("a", "CAUSES", "e"), _l("b", "CAUSES", "e"), _l("c", "INTERACTS_WITH", "a")]
    findings = mod.interaction_signal(nodes, links, {})
    assert len(findings) == 2  # (a,b) once despite both directions, plus (a,c)
    ab = next(f for f in findings if f["evidence"]["drugs"] == ["a", "b"])
    assert ab["severity"] == "WARNING" and ab["evidence"]["shared_adverse_events"] == ["e"]


def test_rules_tolerate_dangling_links():
    mod = _epistemic()
    nodes = [_n("s", "CausalitySignal")]
    links = [_l("s", "ASSESSES", "missing"), _l("x", "INTERACTS_WITH", "y")]
    for rule in mod.CUSTOM_RULES:
        assert isinstance(rule(nodes, links, {}), list)
