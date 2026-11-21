"""Relation names in every shipped domain must survive sift-kg's build.

sift-kg ``activate_passive_relations`` rewrites passive relation names at build
time (explicit map plus a ``^[A-Z]+ED_BY$`` heuristic, e.g. REPORTED_BY ->
REPORTES, DEVELOPED_BY -> DEVELOPES) and flips the edge. A schema name ending
in ``_BY`` therefore never appears in a built graph. Pins the Domain Builder
renames (pharmacovigilance it.2; drug-discovery, fda-product-labels and
contracts it.2).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
DOMAINS = sorted(p.parent.name for p in (ROOT / "domains").glob("*/domain.yaml"))


def _schema(domain):
    return yaml.safe_load((ROOT / "domains" / domain / "domain.yaml").read_text())


@pytest.mark.parametrize("domain", DOMAINS)
def test_no_uppercase_passive_relation_names(domain):
    rels = _schema(domain)["relation_types"]
    assert [r for r in rels if re.match(r"^[A-Z_]+_BY$", r)] == []


# (domain, relation, source entity, target entity, legacy passive name or None)
RENAMED = [
    ("drug-discovery", "DEVELOPS", ("Merck", "ORGANIZATION"), ("pembrolizumab", "COMPOUND"), None),
    ("drug-discovery", "METABOLIZES", ("CYP3A4", "PROTEIN"), ("simvastatin", "COMPOUND"), "METABOLIZED_BY"),
    ("fda-product-labels", "MANUFACTURES", ("Pfizer", "MANUFACTURER"), ("Lipitor", "DRUG_PRODUCT"), "MANUFACTURED_BY"),
    ("fda-product-labels", "IDENTIFIES", ("NDA020702", "REGULATORY_IDENTIFIER"), ("Lipitor", "DRUG_PRODUCT"), "IDENTIFIED_BY"),
    ("contracts", "SIGNS", ("Acme Events LLC", "PARTY"), ("Venue Agreement", "CONTRACT"), None),
]


def _build(tmp_path, domain, src, tgt, rel_type, reverse=False):
    sift = pytest.importorskip("sift_kg")
    s, t = (tgt, src) if reverse else (src, tgt)
    doc = {
        "document_id": "rename_case", "document_path": "", "chunks_processed": 1,
        "domain_name": domain,
        "entities": [
            {"name": n, "entity_type": et, "attributes": {}, "confidence": 0.9, "context": n}
            for n, et in (src, tgt)
        ],
        "relations": [{"relation_type": rel_type, "source_entity": s[0], "target_entity": t[0],
                       "confidence": 0.9, "evidence": "x"}],
    }
    out = tmp_path / "out"
    (out / "extractions").mkdir(parents=True)
    (out / "extractions" / "rename_case.json").write_text(json.dumps(doc))
    sift.run_build(out, sift.load_domain(domain_path=ROOT / "domains" / domain / "domain.yaml"))
    g = json.loads((out / "graph_data.json").read_text())
    nodes = {n["id"]: n for n in g["nodes"]}
    return [(nodes[l["source"]]["name"], l["relation_type"], nodes[l["target"]]["name"])
            for l in g["links"] if l["relation_type"] != "MENTIONED_IN"]


@pytest.mark.integration
@pytest.mark.parametrize("domain,rel,src,tgt,legacy", RENAMED)
def test_renamed_relation_survives_build(tmp_path, domain, rel, src, tgt, legacy):
    cfg = _schema(domain)["relation_types"][rel]
    assert src[1] in cfg["source_types"] and tgt[1] in cfg["target_types"]
    assert _build(tmp_path, domain, src, tgt, rel) == [(src[0], rel, tgt[0])]


@pytest.mark.integration
@pytest.mark.parametrize("domain,rel,src,tgt,legacy", [r for r in RENAMED if r[4]])
def test_legacy_passive_name_lands_on_schema(tmp_path, domain, rel, src, tgt, legacy):
    # A legacy extraction written in the old passive direction (target BY source)
    # is rewritten by sift-kg onto the new active name and direction.
    assert _build(tmp_path, domain, src, tgt, legacy, reverse=True) == [(src[0], rel, tgt[0])]


@pytest.mark.integration
def test_ct_investigator_and_site_survive_build(tmp_path):
    """Investigator and Site used to have no relation and were always pruned."""
    sift = pytest.importorskip("sift_kg")
    ents = [("NCT03548935", "Trial"), ("Melissa L. Johnson", "Investigator"),
            ("Sarah Cannon Research Institute", "Site")]
    rels = [("NCT03548935", "has_investigator", "Melissa L. Johnson"),
            ("NCT03548935", "conducted_at", "Sarah Cannon Research Institute"),
            ("Melissa L. Johnson", "affiliated_with", "Sarah Cannon Research Institute")]
    doc = {"document_id": "ct_case", "document_path": "", "chunks_processed": 1,
           "domain_name": "clinicaltrials",
           "entities": [{"name": n, "entity_type": t, "attributes": {}, "confidence": 0.9, "context": n}
                        for n, t in ents],
           "relations": [{"relation_type": r, "source_entity": s, "target_entity": t,
                          "confidence": 0.9, "evidence": "x"} for s, r, t in rels]}
    out = tmp_path / "out"
    (out / "extractions").mkdir(parents=True)
    (out / "extractions" / "ct_case.json").write_text(json.dumps(doc))
    sift.run_build(out, sift.load_domain(domain_path=ROOT / "domains" / "clinicaltrials" / "domain.yaml"))
    g = json.loads((out / "graph_data.json").read_text())
    nodes = {n["id"]: n for n in g["nodes"]}
    assert {n["entity_type"] for n in g["nodes"]} >= {"Trial", "Investigator", "Site"}
    got = {(nodes[l["source"]]["name"], l["relation_type"], nodes[l["target"]]["name"])
           for l in g["links"] if l["relation_type"] != "MENTIONED_IN"}
    assert got == set(rels)


@pytest.mark.parametrize("domain", DOMAINS)
def test_typed_relations_reach_every_entity_type(domain):
    """When a domain types its relations, every entity type must be reachable.

    An entity type no relation can touch is pruned as isolated at build time
    (clinicaltrials Investigator/Site, drug-discovery METABOLITE before the
    Domain Builder iterations that fixed them).
    """
    schema = _schema(domain)
    rels = [c for c in schema["relation_types"].values() if isinstance(c, dict)]
    typed = [c for c in rels if c.get("source_types") and c.get("target_types")]
    if len(typed) < len(rels):
        pytest.skip(f"{domain} has untyped relations")
    touched = set()
    for c in typed:
        touched |= set(c["source_types"]) | set(c["target_types"])
    assert set(schema["entity_types"]) - touched == set()


def test_drug_discovery_skill_matches_schema():
    """Every SKILL.md relation entry states the schema's endpoint types."""
    skill = (ROOT / "domains" / "drug-discovery" / "SKILL.md").read_text()
    rels = _schema("drug-discovery")["relation_types"]
    for m in re.finditer(r"#### ([A-Z_]+)\n((?:(?!#### |### ).*\n)*)", skill):
        if m.group(1) not in rels:
            continue
        src = re.search(r"\*\*Source types:\*\* (.*)", m.group(2)).group(1).split(", ")
        tgt = re.search(r"\*\*Target types:\*\* (.*)", m.group(2)).group(1).split(", ")
        assert (src, tgt) == (rels[m.group(1)]["source_types"], rels[m.group(1)]["target_types"]), m.group(1)


@pytest.mark.parametrize("domain", ["pharmacovigilance", "fda-product-labels"])
def test_skill_relation_table_matches_schema(domain):
    """The SKILL.md Relation Types table states each relation's Source → Target."""
    skill = (ROOT / "domains" / domain / "SKILL.md").read_text()
    for rel, cfg in _schema(domain)["relation_types"].items():
        row = f"| {rel} | {'/'.join(cfg['source_types'])} → {'/'.join(cfg['target_types'])}"
        assert row in skill, rel


def test_fda_skill_forbids_placeholder_endpoints():
    # Corpus 08's committed extraction lost 830/979 relations to placeholder
    # endpoints such as DRUG_PRODUCT_1; the prompt must rule them out.
    skill = (ROOT / "domains" / "fda-product-labels" / "SKILL.md").read_text()
    assert "Never use placeholder IDs" in skill
