"""Contract tests for /api/dashboard, the data source of the clickable Dashboard."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from starlette.testclient import TestClient

import examples.workbench.server as server_module
from examples.workbench.server import create_app

ROOT = Path(__file__).resolve().parent.parent
GLP1 = ROOT / "tests" / "corpora" / "06_glp1_landscape" / "output-v3"
GLP1_FILES = ("graph_data.json", "communities.json", "claims_layer.json")

pytestmark = pytest.mark.unit


@pytest.fixture()
def glp1_copy(tmp_path):
    for name in GLP1_FILES:
        shutil.copy2(GLP1 / name, tmp_path / name)
    return tmp_path


@pytest.mark.parametrize("domain", [None, "drug-discovery"])
def test_glp1_auto_summary_shape(glp1_copy, domain):
    app = create_app(glp1_copy, domain=domain)
    body = TestClient(app).get("/api/dashboard").json()
    assert body["html"] is None, "auto summary must not carry domain html"
    for key in ("title", "entity_counts", "total_nodes", "total_edges", "findings"):
        assert key in body, f"missing {key}"
    counts = body["entity_counts"]
    assert sum(counts.values()) == body["total_nodes"] == 278, counts
    assert counts["DISEASE"] == 48
    assert counts["DOCUMENT"] == 34


def test_hostile_type_returned_verbatim(tmp_path):
    hostile = "<img src=x onerror=1>"
    graph = {
        "nodes": [{"id": "n1", "label": "n1", "entity_type": hostile}],
        "links": [],
    }
    (tmp_path / "graph_data.json").write_text(json.dumps(graph), encoding="utf-8")
    body = TestClient(create_app(tmp_path, domain=None)).get("/api/dashboard").json()
    assert body["entity_counts"] == {hostile: 1}, body["entity_counts"]


def test_missing_null_or_empty_type_counts_as_unknown(tmp_path):
    graph = {
        "nodes": [
            {"id": "n1", "label": "n1", "entity_type": None},
            {"id": "n2", "label": "n2", "entity_type": ""},
            {"id": "n3", "label": "n3"},
            {"id": "n4", "label": "n4", "entity_type": "DRUG"},
        ],
        "links": [],
    }
    (tmp_path / "graph_data.json").write_text(json.dumps(graph), encoding="utf-8")
    body = TestClient(create_app(tmp_path, domain=None)).get("/api/dashboard").json()
    assert body["entity_counts"] == {"UNKNOWN": 3, "DRUG": 1}, body["entity_counts"]


def test_domain_dashboard_html_path_unchanged(tmp_path, monkeypatch):
    domains = tmp_path / "domains"
    wb = domains / "fakedomain" / "workbench"
    wb.mkdir(parents=True)
    page = "<p>custom dashboard</p>"
    (wb / "dashboard.html").write_text(page, encoding="utf-8")
    monkeypatch.setattr(server_module, "DOMAINS_DIR", domains)
    out = tmp_path / "out"
    out.mkdir()
    (out / "graph_data.json").write_text(json.dumps({"nodes": [], "links": []}), encoding="utf-8")
    app = create_app(out, domain="fakedomain")
    assert TestClient(app).get("/api/dashboard").json() == {"html": page}


@pytest.mark.parametrize("domain", [None, "drug-discovery"])
def test_glp1_epistemic_section(glp1_copy, domain):
    body = TestClient(create_app(glp1_copy, domain=domain)).get("/api/dashboard").json()
    for key in ("title", "entity_counts", "total_nodes", "total_edges", "findings"):
        assert key in body, f"missing {key}"
    epistemic = body["epistemic"]
    assert epistemic["available"] is True
    sections = epistemic["sections"]
    assert [s["key"] for s in sections] == ["contradictions", "contested_claims", "hypotheses"]
    assert [s["count"] for s in sections] == [2, 33, 2]
    assert sum(s["count"] for s in epistemic["status_counts"]) == 855
    assert epistemic["status_counts"][0] == {"status": "asserted", "count": 758}


def test_no_claims_layer_epistemic_not_run(tmp_path):
    graph = {"nodes": [{"id": "n1", "label": "n1", "entity_type": "DRUG"}], "links": []}
    (tmp_path / "graph_data.json").write_text(json.dumps(graph), encoding="utf-8")
    body = TestClient(create_app(tmp_path, domain=None)).get("/api/dashboard").json()
    assert body["epistemic"] == {"available": False, "status_counts": [], "sections": []}


def test_hostile_claim_strings_verbatim(tmp_path):
    evidence = "<img src=x onerror=1>"
    gap = '"><script>alert(1)</script>'
    graph = {"nodes": [{"id": "n1", "label": "n1", "entity_type": "DRUG"}], "links": []}
    claims = {
        "super_domain": {
            "conflicts": [{"type": "contradiction", "evidence": evidence}],
            "coverage_gaps": [{"description": gap}],
        }
    }
    (tmp_path / "graph_data.json").write_text(json.dumps(graph), encoding="utf-8")
    (tmp_path / "claims_layer.json").write_text(json.dumps(claims), encoding="utf-8")
    body = TestClient(create_app(tmp_path, domain=None)).get("/api/dashboard").json()
    sections = {s["key"]: s for s in body["epistemic"]["sections"]}
    assert sections["conflicts"]["items"][0]["title"] == evidence
    assert sections["coverage_gaps"]["items"][0]["title"] == gap


def test_malformed_claims_layer_still_200(tmp_path):
    graph = {"nodes": [{"id": "n1", "label": "n1", "entity_type": "DRUG"}], "links": []}
    claims = {"super_domain": "oops", "summary": []}
    (tmp_path / "graph_data.json").write_text(json.dumps(graph), encoding="utf-8")
    (tmp_path / "claims_layer.json").write_text(json.dumps(claims), encoding="utf-8")
    response = TestClient(create_app(tmp_path, domain=None)).get("/api/dashboard")
    assert response.status_code == 200
    assert response.json()["epistemic"]["available"] is False


@pytest.mark.parametrize("claims", [[], None, "oops", 3])
def test_non_object_claims_layer_still_200(tmp_path, claims):
    graph = {"nodes": [{"id": "n1", "label": "n1", "entity_type": "DRUG"}], "links": []}
    (tmp_path / "graph_data.json").write_text(json.dumps(graph), encoding="utf-8")
    (tmp_path / "claims_layer.json").write_text(json.dumps(claims), encoding="utf-8")
    client = TestClient(create_app(tmp_path, domain=None))
    response = client.get("/api/dashboard")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["epistemic"]["available"] is False
    assert body["findings"] == []
    assert client.get("/api/graph/claims").status_code == 200
