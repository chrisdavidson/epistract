"""Payload parity: the shared core helpers must equal what the workbench routes return."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from core.graph_payloads import claims_payload, entity_types_payload
from examples.workbench.server import create_app

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parent.parent
GLP1 = ROOT / "tests" / "corpora" / "06_glp1_landscape" / "output-v3"
GLP1_FILES = ("graph_data.json", "communities.json", "claims_layer.json")


def _glp1_copy(tmp_path: Path) -> Path:
    work = tmp_path / "glp1"
    work.mkdir()
    for name in GLP1_FILES:
        shutil.copy2(GLP1 / name, work / name)
    return work


def test_payload_helpers_match_routes_for_contracts_sample(client):
    """entity_types_payload and claims_payload equal the live routes (contracts fixture)."""
    state = client.app.state
    expected_types = client.get("/api/graph/entity-types").json()
    expected_claims = client.get("/api/graph/claims").json()

    got_types = entity_types_payload(state.data.get_nodes(), state.display)
    got_claims = claims_payload(state.data.claims_layer)

    assert got_types == expected_types, f"entity-types payload differs: {got_types} != {expected_types}"
    assert got_claims == expected_claims, f"claims payload differs: {got_claims} != {expected_claims}"


def test_payload_helpers_match_routes_for_glp1(tmp_path):
    """Same parity on the full GLP-1 graph (many types, families, relations)."""
    work = _glp1_copy(tmp_path)
    app_client = TestClient(create_app(work))
    state = app_client.app.state

    got_types = entity_types_payload(state.data.get_nodes(), state.display)
    got_claims = claims_payload(state.data.claims_layer)

    assert got_types == app_client.get("/api/graph/entity-types").json()
    assert got_claims == app_client.get("/api/graph/claims").json()
    assert got_types["types"], "GLP-1 should resolve at least one entity type"


def test_claims_payload_tolerates_empty_layer():
    """An absent claims layer yields the six empty keys the frontend expects."""
    assert claims_payload({}) == {
        "conflicts": [],
        "gaps": [],
        "risks": [],
        "cross_references": [],
        "custom_findings": {},
        "findings": [],
    }

