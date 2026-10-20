"""Tests for schema-declared display in the shipped domains, templates and loaders."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest
import yaml

from core.graph_display import ALLOWED_SHAPES, RELATION_CATEGORIES, resolve_display

ROOT = Path(__file__).resolve().parent.parent
DOMAINS = ROOT / "domains"
GLP1 = ROOT / "tests" / "corpora" / "06_glp1_landscape" / "output-v3"

DOMAIN_NAMES = [
    "drug-discovery",
    "contracts",
    "clinicaltrials",
    "pharmacovigilance",
    "fda-product-labels",
    "crosswalk",
]

COUNTS = {
    "drug-discovery": (17, 30),
    "contracts": (9, 9),
    "clinicaltrials": (12, 10),
    "pharmacovigilance": (12, 12),
    "fda-product-labels": (17, 16),
    "crosswalk": (6, 4),
}

# Entity family assignment table (family -> member types).
ENTITY_FAMILIES: dict[str, dict[str, list[str]]] = {
    "drug-discovery": {
        "Interventions": ["COMPOUND", "METABOLITE"],
        "Molecular": ["GENE", "PROTEIN", "PROTEIN_DOMAIN", "SEQUENCE_VARIANT", "CELL_OR_TISSUE"],
        "Concepts": ["MECHANISM_OF_ACTION", "PATHWAY", "BIOMARKER", "PHENOTYPE"],
        "Conditions": ["DISEASE", "ADVERSE_EVENT"],
        "Evidence": ["CLINICAL_TRIAL", "REGULATORY_ACTION"],
        "Actors": ["ORGANIZATION"],
        "Sources": ["PUBLICATION"],
    },
    "contracts": {
        "Actors": ["PARTY", "VENUE"],
        "Agreements": ["CONTRACT"],
        "Terms": ["OBLIGATION", "DEADLINE", "PENALTY", "INSURANCE"],
        "Financials": ["COST"],
        "Services": ["SERVICE"],
    },
    "clinicaltrials": {
        "Evidence": ["Trial", "TrialPhase", "Outcome"],
        "Interventions": ["Intervention", "Compound"],
        "Conditions": ["Condition"],
        "Actors": ["Sponsor", "Investigator", "Site"],
        "Concepts": ["Biomarker"],
        "Populations": ["Cohort", "Population"],
    },
    "pharmacovigilance": {
        "Interventions": ["Drug", "Concomitant"],
        "Conditions": ["AdverseEvent", "Indication"],
        "Actors": ["Patient", "Reporter"],
        "Evidence": ["ReportType", "RegulatoryAction", "CausalitySignal"],
        "Concepts": ["TemporalRelationship", "DechallengeRechallenge", "Outcome"],
    },
    "fda-product-labels": {
        "Interventions": [
            "DRUG_PRODUCT",
            "ACTIVE_INGREDIENT",
            "INACTIVE_INGREDIENT",
            "DOSAGE_REGIMEN",
        ],
        "Actors": ["MANUFACTURER", "PATIENT_POPULATION"],
        "Conditions": ["INDICATION", "CONTRAINDICATION", "ADVERSE_REACTION", "WARNING"],
        "Concepts": [
            "MECHANISM_OF_ACTION",
            "PHARMACOKINETIC_PROPERTY",
            "PHARMACOLOGIC_CLASS",
            "DRUG_INTERACTION",
        ],
        "Evidence": ["CLINICAL_STUDY", "LABTEST", "REGULATORY_IDENTIFIER"],
    },
    "crosswalk": {
        "Sources": ["Graph"],
        "Evidence": ["Trial", "Outcome"],
        "Interventions": ["Drug"],
        "Conditions": ["AdverseEvent", "Indication"],
    },
}

# Relation category assignment table (category -> member relation types).
RELATION_CATS: dict[str, dict[str, list[str]]] = {
    "drug-discovery": {
        "mechanism": [
            "TARGETS", "INHIBITS", "ACTIVATES", "BINDS_TO", "HAS_MECHANISM",
            "PARTICIPATES_IN", "INTERACTS_WITH", "METABOLIZED_BY", "PHOSPHORYLATES",
            "FORMS_COMPLEX_WITH", "REGULATES_EXPRESSION",
        ],
        "therapeutic": ["INDICATED_FOR", "CONTRAINDICATED_FOR", "EVALUATED_IN", "COMBINED_WITH"],
        "causal": ["CAUSES", "IMPLICATED_IN", "CONFERS_RESISTANCE_TO"],
        "association": ["PREDICTS_RESPONSE_TO", "DIAGNOSTIC_FOR", "ASSOCIATED_WITH"],
        "structural": [
            "DERIVED_FROM", "ENCODES", "EXPRESSED_IN", "HAS_VARIANT", "HAS_DOMAIN",
            "LOCALIZED_TO",
        ],
        "organizational": ["DEVELOPED_BY"],
        "provenance": ["PUBLISHED_IN"],
        "regulatory": ["GRANTS_APPROVAL_FOR"],
    },
    "contracts": {
        "organizational": ["OBLIGATED_TO", "SIGNED_BY", "PROVIDES_SERVICE", "HELD_AT"],
        "structural": ["HAS_DEADLINE", "COSTS", "CROSS_REFERENCES"],
        "regulatory": ["REQUIRES_INSURANCE", "PENALIZES"],
    },
    "clinicaltrials": {
        "therapeutic": ["tests", "treats", "co_intervention"],
        "organizational": ["sponsored_by", "investigates"],
        "association": ["has_outcome", "uses_biomarker"],
        "structural": ["enrolls", "is_phase"],
        "mechanism": ["targets"],
    },
    "pharmacovigilance": {
        "causal": [
            "EXPERIENCED", "RESULTED_IN", "RESOLVED_ON_DECHALLENGE",
            "RECURRED_ON_RECHALLENGE", "CAUSED_BY",
        ],
        "therapeutic": ["TOOK", "INDICATED_FOR", "CO_ADMINISTERED_WITH"],
        "provenance": ["REPORTED_BY"],
        "association": ["OCCURRED_AFTER", "CONTRADICTS"],
        "regulatory": ["TRIGGERED"],
    },
    "fda-product-labels": {
        "structural": ["HAS_ACTIVE_INGREDIENT", "HAS_INACTIVE_INGREDIENT", "BELONGS_TO_CLASS"],
        "organizational": ["MANUFACTURED_BY"],
        "therapeutic": [
            "INDICATED_FOR", "CONTRAINDICATED_IN", "DOSED_VIA", "EVALUATED_IN",
            "CONTRAINDICATED_WITH",
        ],
        "causal": ["CAUSES_ADVERSE_REACTION"],
        "regulatory": ["HAS_WARNING", "IDENTIFIED_BY"],
        "mechanism": ["INTERACTS_WITH", "HAS_MECHANISM", "HAS_PK_PROPERTY"],
        "association": ["STUDIED_IN_POPULATION"],
    },
    "crosswalk": {
        "provenance": ["PRESENT_IN"],
        "causal": ["UNLABELED_ADVERSE_EVENT"],
        "association": ["COVERAGE_GAP"],
        "therapeutic": ["OFF_LABEL_EXPOSURE"],
    },
}


def _schema(domain: str) -> dict:
    return yaml.safe_load((DOMAINS / domain / "domain.yaml").read_text())


# ---------------------------------------------------------------------------
# Shipped domain.yaml files
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("domain", DOMAIN_NAMES)
def test_shipped_domains_declare_display(domain):
    schema = _schema(domain)
    for name, spec in schema["entity_types"].items():
        display = spec.get("display")
        assert isinstance(display, dict), f"{domain}/{name} has no display block"
        assert display.get("family"), f"{domain}/{name} has no family"
        assert display.get("shape") in ALLOWED_SHAPES, f"{domain}/{name} bad shape"
        assert re.fullmatch(r"#[0-9a-f]{6}", display.get("color", "")), (
            f"{domain}/{name} bad color {display.get('color')!r}"
        )
    for name, spec in schema["relation_types"].items():
        assert spec.get("category") in RELATION_CATEGORIES, f"{domain}/{name} bad category"


@pytest.mark.parametrize("domain", DOMAIN_NAMES)
def test_shipped_domains_resolve_clean(domain):
    schema = _schema(domain)
    out = resolve_display(schema, ["DOCUMENT"], None)
    assert out["warnings"] == [], out["warnings"]
    colors = [t["color"] for t in out["types"].values()]
    assert len(colors) == len(set(colors)), f"{domain} has duplicate colors"
    for name in schema["entity_types"]:
        assert out["types"][name]["origin"] == "declared", f"{domain}/{name} not declared"


@pytest.mark.parametrize("domain", DOMAIN_NAMES)
def test_shipped_domains_family_shape(domain):
    schema = _schema(domain)
    shapes: dict[str, set[str]] = {}
    for spec in schema["entity_types"].values():
        shapes.setdefault(spec["display"]["family"], set()).add(spec["display"]["shape"])
    for family, found in shapes.items():
        assert len(found) == 1, f"{domain} family {family} has shapes {found}"
    if domain == "drug-discovery":
        used = {s for found in shapes.values() for s in found}
        assert used == set(ALLOWED_SHAPES)


@pytest.mark.parametrize("domain", DOMAIN_NAMES)
def test_shipped_domains_match_assignment_table(domain):
    schema = _schema(domain)
    expected = {t: fam for fam, types in ENTITY_FAMILIES[domain].items() for t in types}
    actual = {n: s["display"]["family"] for n, s in schema["entity_types"].items()}
    assert actual == expected
    expected_cat = {t: c for c, types in RELATION_CATS[domain].items() for t in types}
    actual_cat = {n: s["category"] for n, s in schema["relation_types"].items()}
    assert actual_cat == expected_cat


@pytest.mark.parametrize("domain", DOMAIN_NAMES)
def test_shipped_domains_sift_load(domain):
    sift_kg = pytest.importorskip("sift_kg")
    loaded = sift_kg.load_domain(domain_path=DOMAINS / domain / "domain.yaml")
    entities, relations = COUNTS[domain]
    assert len(loaded.entity_types) == entities
    assert len(loaded.relation_types) == relations


def test_glp1_shapes_vary():
    observed = {n["entity_type"] for n in json.loads((GLP1 / "graph_data.json").read_text())["nodes"]}
    out = resolve_display(_schema("drug-discovery"), observed, None)
    types = {t: out["types"][t] for t in observed}
    assert len({t["shape"] for t in types.values()}) >= 6
    assert len({t["color"] for t in types.values()}) == len(observed) == 13
    assert all(t["origin"] in ("declared", "pipeline") for t in types.values())
