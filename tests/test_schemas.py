#!/usr/bin/env python3
"""Schema validation and domain skill coverage tests.

Covers TEST-03 (skill coverage) and TEST-04 (agent coverage via Pydantic).
Run: python -m pytest tests/test_schemas.py -m unit -v
"""
import json
from pathlib import Path

import pytest
import yaml
from pydantic import BaseModel, ValidationError

from conftest import FIXTURES_DIR, PROJECT_ROOT

# ---------------------------------------------------------------------------
# Pydantic models for DocumentExtraction validation (D-07)
# ---------------------------------------------------------------------------


class ExtractedEntity(BaseModel):
    name: str
    entity_type: str
    confidence: float
    context: str = ""


class ExtractedRelation(BaseModel):
    source_entity: str
    target_entity: str
    relation_type: str
    confidence: float
    evidence: str = ""


class DocumentExtraction(BaseModel):
    document_id: str
    entities: list[ExtractedEntity]
    relations: list[ExtractedRelation]
    extracted_at: str
    domain_name: str
    chunks_processed: int = 1
    document_path: str = ""
    cost_usd: float = 0.0
    model_used: str = ""
    chunk_size: int = 10000
    error: str | None = None


# ---------------------------------------------------------------------------
# Domain paths
# ---------------------------------------------------------------------------
DRUG_DISCOVERY_YAML = PROJECT_ROOT / "domains" / "drug-discovery" / "domain.yaml"
CONTRACTS_YAML = PROJECT_ROOT / "domains" / "contracts" / "domain.yaml"
DRUG_DISCOVERY_SKILL = PROJECT_ROOT / "domains" / "drug-discovery" / "SKILL.md"
CONTRACTS_SKILL = PROJECT_ROOT / "domains" / "contracts" / "SKILL.md"
DOMAINS_DIR = PROJECT_ROOT / "domains"

# Valid drug-discovery entity types
DRUG_DISCOVERY_ENTITY_TYPES = {
    "COMPOUND",
    "GENE",
    "PROTEIN",
    "DISEASE",
    "MECHANISM_OF_ACTION",
    "CLINICAL_TRIAL",
    "PATHWAY",
    "BIOMARKER",
    "ADVERSE_EVENT",
    "ORGANIZATION",
    "PUBLICATION",
    "REGULATORY_ACTION",
    "PHENOTYPE",
    "METABOLITE",
    "CELL_OR_TISSUE",
    "PROTEIN_DOMAIN",
    "SEQUENCE_VARIANT",
}


# ========================================================================
# TEST-04: Agent coverage via Pydantic DocumentExtraction validation
# ========================================================================


@pytest.mark.unit
def test_extraction_schema_drug_discovery():
    """Load drug extraction fixture and validate with DocumentExtraction model."""
    data = json.loads((FIXTURES_DIR / "sample_extraction_drug.json").read_text())
    result = DocumentExtraction(**data)
    assert len(result.entities) >= 3, f"Expected >= 3 entities, got {len(result.entities)}"
    assert result.domain_name == "drug-discovery"


@pytest.mark.unit
def test_extraction_schema_contracts():
    """Load contract extraction fixture and validate with DocumentExtraction model."""
    data = json.loads((FIXTURES_DIR / "sample_extraction_contract.json").read_text())
    result = DocumentExtraction(**data)
    assert result.domain_name == "contracts"
    assert len(result.entities) >= 2


@pytest.mark.unit
def test_extraction_schema_rejects_invalid():
    """DocumentExtraction rejects dict missing required document_id field."""
    invalid_data = {
        "entities": [],
        "relations": [],
        "extracted_at": "2026-01-01T00:00:00Z",
        "domain_name": "test",
    }
    with pytest.raises(ValidationError):
        DocumentExtraction(**invalid_data)


@pytest.mark.unit
def test_extraction_entity_types_valid():
    """All entity types in drug extraction fixture are valid drug-discovery types."""
    data = json.loads((FIXTURES_DIR / "sample_extraction_drug.json").read_text())
    result = DocumentExtraction(**data)
    for entity in result.entities:
        assert entity.entity_type in DRUG_DISCOVERY_ENTITY_TYPES, (
            f"Unknown entity type: {entity.entity_type}"
        )


# ========================================================================
# TEST-03: Skill coverage via domain YAML validation
# ========================================================================


def _discover_domain_yamls() -> list[Path]:
    """Discover every tracked domain.yaml under domains/, one level deep.

    The glob is deliberately `*/domain.yaml` (not `**/domain.yaml`): STATE.md documents
    `domains/_archived/<name>/` as the archive convention, which sits two levels deep, and a
    recursive glob would sweep archived domains back into the live guard. Domain directories
    with no `domain.yaml` (e.g. untracked in-progress domains) are skipped identically whether
    they exist locally or not in CI -- no exclusion list is needed.

    Raises AssertionError naming the missing anchor if either `DRUG_DISCOVERY_YAML` or
    `CONTRACTS_YAML` is absent from the result, so a broken/empty glob cannot make callers
    pass vacuously (D-02) -- the check lives here so every future call site inherits it.

    Returns:
        Sorted list of discovered domain.yaml paths (deterministic failure ordering).
    """
    paths = sorted(DOMAINS_DIR.glob("*/domain.yaml"))
    assert DRUG_DISCOVERY_YAML in paths, (
        f"drug-discovery domain.yaml missing from discovery under {DOMAINS_DIR}: {paths}"
    )
    assert CONTRACTS_YAML in paths, (
        f"contracts domain.yaml missing from discovery under {DOMAINS_DIR}: {paths}"
    )
    return paths


def _assert_type_keys_are_strings(types_container: dict | list, kind: str, source: str) -> None:
    """Assert every declared type identifier in a domain YAML container is a str.

    Guards against PyYAML's YAML 1.1 boolean/null scalar coercion: a bare `on`/`off`/
    `yes`/`no`/`null` type identifier in hand-authored domain.yaml silently parses as
    `True`/`False`/`None` instead of the intended string. `NO` (nitric oxide) is a realistic
    biomedical entity-type identifier that would be silently lost this way.

    Handles both container shapes used across tracked domains: a dict keyed by type name
    (`{TYPE_NAME: {description: ...}}`), and a list of entries with a `name` field
    (`[{name: ..., description: ...}]`). List entries missing `name` are skipped here --
    the caller's inline presence assertion reports that case with a clearer message.

    Args:
        types_container: The `entity_types` or `relation_types` value from a loaded domain.yaml.
        kind: Label for error messages, e.g. "Entity" or "Relation".
        source: Label identifying the source file, e.g. a filename.

    Returns:
        None. Raises AssertionError if any type identifier is not a str.
    """
    if isinstance(types_container, dict):
        for type_name in types_container:
            assert isinstance(type_name, str), (
                f"{kind} type key must be str in {source}: {type_name!r} ({type(type_name).__name__})"
            )
    elif isinstance(types_container, list):
        for entry in types_container:
            if isinstance(entry, dict) and "name" in entry:
                type_name = entry["name"]
                assert isinstance(type_name, str), (
                    f"{kind} type name must be str in {source}: "
                    f"{type_name!r} ({type(type_name).__name__})"
                )


@pytest.mark.unit
def test_drug_discovery_domain_yaml_loads():
    """Drug-discovery domain.yaml loads and has 17 entity types and 30 relation types."""
    data = yaml.safe_load(DRUG_DISCOVERY_YAML.read_text())
    assert data["name"] is not None
    assert len(data["entity_types"]) == 17, f"Expected 17, got {len(data['entity_types'])}"
    assert len(data["relation_types"]) == 30, f"Expected 30, got {len(data['relation_types'])}"


@pytest.mark.unit
def test_contracts_domain_yaml_loads():
    """Contracts domain.yaml loads and has 9 entity types and 9 relation types."""
    data = yaml.safe_load(CONTRACTS_YAML.read_text())
    assert data["name"] is not None
    assert len(data["entity_types"]) == 9, f"Expected 9, got {len(data['entity_types'])}"
    assert len(data["relation_types"]) == 9, f"Expected 9, got {len(data['relation_types'])}"


@pytest.mark.unit
def test_drug_discovery_skill_md_exists():
    """Drug-discovery SKILL.md exists and is non-trivial (> 100 bytes)."""
    assert DRUG_DISCOVERY_SKILL.exists(), f"Missing: {DRUG_DISCOVERY_SKILL}"
    assert DRUG_DISCOVERY_SKILL.stat().st_size > 100, "SKILL.md is too small"


@pytest.mark.unit
def test_contracts_skill_md_exists():
    """Contracts SKILL.md exists and is non-trivial (> 100 bytes)."""
    assert CONTRACTS_SKILL.exists(), f"Missing: {CONTRACTS_SKILL}"
    assert CONTRACTS_SKILL.stat().st_size > 100, "SKILL.md is too small"


@pytest.mark.unit
def test_domain_yaml_entity_types_have_required_fields():
    """Every entity type in every tracked domain YAML has name and description."""
    for yaml_path in _discover_domain_yamls():
        data = yaml.safe_load(yaml_path.read_text())
        entity_types = data["entity_types"]
        _assert_type_keys_are_strings(entity_types, "Entity", yaml_path.name)

        if isinstance(entity_types, dict):
            # Drug-discovery format: {TYPE_NAME: {description: ..., ...}}
            for type_name, type_def in entity_types.items():
                assert "description" in type_def, (
                    f"Entity type {type_name} in {yaml_path.name} missing 'description'"
                )
        elif isinstance(entity_types, list):
            # Contracts format: [{name: ..., description: ...}, ...]
            for entry in entity_types:
                assert "name" in entry, (
                    f"Entity type entry in {yaml_path.name} missing 'name': {entry}"
                )
                assert "description" in entry, (
                    f"Entity type {entry.get('name', '?')} in {yaml_path.name} missing 'description'"
                )


@pytest.mark.unit
def test_domain_yaml_relation_types_have_required_fields():
    """Every relation type in every tracked domain YAML has name/key and description."""
    for yaml_path in _discover_domain_yamls():
        data = yaml.safe_load(yaml_path.read_text())
        relation_types = data["relation_types"]
        _assert_type_keys_are_strings(relation_types, "Relation", yaml_path.name)

        if isinstance(relation_types, dict):
            # Drug-discovery format: {TYPE_NAME: {description: ..., ...}}
            for type_name, type_def in relation_types.items():
                assert "description" in type_def, (
                    f"Relation type {type_name} in {yaml_path.name} missing 'description'"
                )
        elif isinstance(relation_types, list):
            # Contracts format: [{name: ..., description: ...}, ...]
            for entry in relation_types:
                assert "name" in entry, (
                    f"Relation type entry in {yaml_path.name} missing 'name': {entry}"
                )
                assert "description" in entry, (
                    f"Relation type {entry.get('name', '?')} in {yaml_path.name} missing 'description'"
                )


@pytest.mark.unit
def test_domain_yaml_discovery_is_not_vacuous():
    """Discovery over domains/*/domain.yaml finds a plausible, non-empty set of tracked domains.

    _discover_domain_yamls() raises internally if either anchor domain is missing (D-02) --
    the anchor assertions below document that contract, they are not the enforcement path.
    A reader should not need to hunt for where the missing-anchor assertion actually fires;
    the >= 3 floor below is the only check in this test body that can actually trip.
    """
    paths = _discover_domain_yamls()

    assert paths, "Domain discovery returned no domain.yaml files"
    for path in paths:
        assert path.exists(), f"Discovered path does not exist: {path}"

    assert DRUG_DISCOVERY_YAML in paths, "drug-discovery domain.yaml missing from discovery"
    assert CONTRACTS_YAML in paths, "contracts domain.yaml missing from discovery"

    assert len(paths) >= 3, (
        f"Expected >= 3 tracked domain.yaml files (implausibly few found), got {len(paths)}. "
        "Lower this floor only when a domain is intentionally archived."
    )


@pytest.mark.unit
def test_yaml_boolean_coercion_caught_by_key_guard():
    """A YAML 1.1 boolean coercion of a domain type key is caught by the shared key-type guard.

    Covers both container shapes and both the positive (coerced) and negative (quoted) forms,
    so this proves the guard discriminates rather than always raising (D-04). `NO` here is
    nitric oxide -- a realistic biomedical entity-type key, not a contrived example.
    """
    # POSITIVE (coerced, dict shape): bare `on` / `NO` keys coerce to bool.
    coerced_dict_yaml = """
    entity_types:
      on:
        description: turned on
      NO:
        description: nitric oxide
    """
    coerced_dict_types = yaml.safe_load(coerced_dict_yaml)["entity_types"]
    assert True in coerced_dict_types and False in coerced_dict_types, (
        f"Expected PyYAML to coerce bare on/NO to bool keys, got {coerced_dict_types!r}"
    )
    with pytest.raises(AssertionError) as excinfo:
        _assert_type_keys_are_strings(coerced_dict_types, "Entity", "synthetic-dict.yaml")
    assert "bool" in str(excinfo.value), (
        f"Expected the guard's message to name the offending type, got: {excinfo.value}"
    )

    # POSITIVE (coerced, list shape): bare `NO` value under `name:` coerces to bool.
    coerced_list_yaml = """
    entity_types:
      - name: NO
        description: nitric oxide
    """
    coerced_list_types = yaml.safe_load(coerced_list_yaml)["entity_types"]
    assert coerced_list_types[0]["name"] is False, (
        f"Expected PyYAML to coerce bare NO to False, got {coerced_list_types[0]['name']!r}"
    )
    with pytest.raises(AssertionError) as excinfo:
        _assert_type_keys_are_strings(coerced_list_types, "Entity", "synthetic-list.yaml")
    assert "bool" in str(excinfo.value), (
        f"Expected the guard's message to name the offending type, got: {excinfo.value}"
    )

    # NEGATIVE CONTROL (quoted, dict shape): quoting keeps the keys as str -- the guard
    # must NOT raise here, or it would be satisfied by an unconditional raise (D-04).
    quoted_dict_yaml = """
    entity_types:
      'NO':
        description: nitric oxide
      "on":
        description: turned on
    """
    quoted_dict_types = yaml.safe_load(quoted_dict_yaml)["entity_types"]
    assert all(isinstance(key, str) for key in quoted_dict_types), (
        f"Expected quoted keys to stay str, got {list(quoted_dict_types.keys())!r}"
    )
    _assert_type_keys_are_strings(quoted_dict_types, "Entity", "synthetic-quoted.yaml")
