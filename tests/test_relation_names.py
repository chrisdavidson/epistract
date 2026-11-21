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
