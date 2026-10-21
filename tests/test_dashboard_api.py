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


def test_domain_dashboard_html_path_unchanged(tmp_path, monkeypatch):
    domains = tmp_path / "domains"
    wb = domains / "fakedomain" / "workbench"
    wb.mkdir(parents=True)
    page = "<p>custom dashboard</p>"
    (wb / "dashboard.html").write_text(page, encoding="utf-8")
    monkeypatch.setattr(server_module, "DOMAINS_DIR", domains)
    out = tmp_path / "out"
    out.mkdir()
    (out / "graph_data.json").write_text(
        json.dumps({"nodes": [], "links": []}), encoding="utf-8"
    )
    app = create_app(out, domain="fakedomain")
    assert TestClient(app).get("/api/dashboard").json() == {"html": page}
