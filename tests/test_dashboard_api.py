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
DOCUMENT_KEYS = {
    "doc_id",
    "display_name",
    "filename",
    "entity_count",
    "relation_count",
    "has_text",
    "has_pdf",
}

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
    body = TestClient(app).get("/api/dashboard").json()
    assert body == {"html": page}
    assert "start_here" not in body


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


# -- Documents ---------------------------------------------------------------


@pytest.fixture()
def glp1_with_docs(glp1_copy):
    shutil.copytree(GLP1 / "ingested", glp1_copy / "ingested")
    shutil.copy2(GLP1 / "triage.json", glp1_copy / "triage.json")
    return glp1_copy


def test_glp1_documents_rows(glp1_with_docs):
    body = TestClient(create_app(glp1_with_docs, domain=None)).get("/api/dashboard").json()
    docs = body["documents"]
    assert len(docs) == 34
    assert all(set(d) == DOCUMENT_KEYS for d in docs)
    counts = [d["entity_count"] for d in docs]
    assert counts[0] == max(counts) and counts == sorted(counts, reverse=True)
    assert all(d["has_text"] is True and d["has_pdf"] is False for d in docs)
    for key in ("epistemic", "entity_counts", "findings", "total_nodes", "total_edges"):
        assert key in body, f"missing {key}"


def test_documents_empty_without_ingested_dir(glp1_copy):
    body = TestClient(create_app(glp1_copy, domain=None)).get("/api/dashboard").json()
    assert body["documents"] == []
    assert body["epistemic"]["available"] is True


def test_sources_contract_unchanged_and_gains_flags(glp1_with_docs):
    client = TestClient(create_app(glp1_with_docs, domain=None))
    listing = client.get("/api/sources").json()
    assert len(listing["documents"]) == 34
    first = listing["documents"][0]
    for key in ("doc_id", "filename", "display_name", "original_path", "size_bytes"):
        assert key in first
    assert first["has_text"] is True and first["has_pdf"] is False
    ok = client.get(f"/api/sources/{first['doc_id']}")
    assert ok.status_code == 200
    assert set(ok.json()) == {"doc_id", "text"} and ok.json()["text"]
    missing = client.get("/api/sources/no_such_doc")
    assert missing.status_code == 404 and "error" in missing.json()
    assert client.get("/api/sources/pdf/no_such_doc").status_code == 404
    for hostile in ("..%2Fgraph_data", "%2e%2e%2fgraph_data", "..%5Cgraph_data"):
        response = client.get(f"/api/sources/{hostile}")
        assert response.status_code in (404, 422), hostile
        assert "nodes" not in response.text


def _pdf_output(tmp_path, *, triage_pdf: bool, pdf_name: str):
    out = tmp_path / "out"
    (out / "ingested").mkdir(parents=True)
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (out / "ingested" / "foo_report.txt").write_text("Foo body", encoding="utf-8")
    (out / "ingested" / "other.txt").write_text("Other body", encoding="utf-8")
    (out / "graph_data.json").write_text(json.dumps({"nodes": [], "links": []}), encoding="utf-8")
    (corpus / pdf_name).write_bytes(b"%PDF-1.4 stub")
    first = corpus / ("Foo Report.pdf" if triage_pdf else "Foo Report.txt")
    triage = {
        "documents": [
            {"doc_id": "foo_report", "file_path": str(first)},
            {"doc_id": "other", "file_path": str(corpus / "other.txt")},
        ]
    }
    (out / "triage.json").write_text(json.dumps(triage), encoding="utf-8")
    return out


def test_has_pdf_from_triage_path(tmp_path):
    out = _pdf_output(tmp_path, triage_pdf=True, pdf_name="Foo Report.pdf")
    client = TestClient(create_app(out, domain=None))
    docs = {d["doc_id"]: d for d in client.get("/api/sources").json()["documents"]}
    assert docs["foo_report"]["has_pdf"] is True
    assert docs["other"]["has_pdf"] is False
    dash = {d["doc_id"]: d for d in client.get("/api/dashboard").json()["documents"]}
    assert dash["foo_report"]["has_pdf"] is True and dash["foo_report"]["has_text"] is True
    pdf = client.get("/api/sources/pdf/foo_report")
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"


def test_has_pdf_from_doc_id_file_next_to_corpus(tmp_path):
    out = _pdf_output(tmp_path, triage_pdf=False, pdf_name="other.pdf")
    client = TestClient(create_app(out, domain=None))
    docs = {d["doc_id"]: d for d in client.get("/api/sources").json()["documents"]}
    assert docs["other"]["has_pdf"] is True
    assert docs["foo_report"]["has_pdf"] is False
    assert client.get("/api/sources/pdf/other").status_code == 200
    assert client.get("/api/sources/pdf/foo_report").status_code == 404


def _assert_flag_matches_endpoint(client):
    """has_pdf is true exactly when /api/sources/pdf/{doc_id} serves a PDF."""
    docs = client.get("/api/sources").json()["documents"]
    assert docs, "no documents listed"
    for doc in docs:
        status = client.get(f"/api/sources/pdf/{doc['doc_id']}").status_code
        assert (status == 200) is doc["has_pdf"], (doc["doc_id"], doc["has_pdf"], status)
    return {d["doc_id"]: d for d in docs}


def test_has_pdf_and_endpoint_agree_without_walking_the_tree(tmp_path, monkeypatch):
    # A PDF one level below the corpus folder is neither flagged nor served:
    # there is no recursive walk at load time or at request time.
    out = _pdf_output(tmp_path, triage_pdf=True, pdf_name="Foo Report.pdf")
    nested = tmp_path / "corpus" / "nested"
    nested.mkdir()
    (nested / "other.pdf").write_bytes(b"%PDF-1.4 stub")

    def boom(self, pattern):
        raise AssertionError("rglob must not run")

    monkeypatch.setattr(Path, "rglob", boom)
    docs = _assert_flag_matches_endpoint(TestClient(create_app(out, domain=None)))
    assert docs["foo_report"]["has_pdf"] is True
    assert docs["other"]["has_pdf"] is False


def test_has_pdf_and_endpoint_agree_for_unnormalised_names(tmp_path):
    # "Acme (2024).pdf" gets the id acme__2024_; the triage path is the one
    # resolver, so the flag and the endpoint both find it.
    out = tmp_path / "out"
    (out / "ingested").mkdir(parents=True)
    corpus = tmp_path / "corpus"
    (corpus / "sub").mkdir(parents=True)
    (out / "graph_data.json").write_text(json.dumps({"nodes": [], "links": []}), encoding="utf-8")
    (out / "ingested" / "acme__2024_.txt").write_text("Acme", encoding="utf-8")
    (out / "ingested" / "my_doc.txt").write_text("Mine", encoding="utf-8")
    (corpus / "Acme (2024).pdf").write_bytes(b"%PDF-1.4 stub")
    (corpus / "sub" / "My_Doc.pdf").write_bytes(b"%PDF-1.4 stub")
    triage = {
        "documents": [
            {"doc_id": "acme__2024_", "file_path": str(corpus / "Acme (2024).pdf")},
            {"doc_id": "my_doc", "file_path": str(corpus / "sub" / "My_Doc.pdf")},
        ]
    }
    (out / "triage.json").write_text(json.dumps(triage), encoding="utf-8")
    docs = _assert_flag_matches_endpoint(TestClient(create_app(out, domain=None)))
    assert docs["acme__2024_"]["has_pdf"] is True
    assert docs["my_doc"]["has_pdf"] is True


def test_relative_triage_paths_resolve_against_the_output_dir(tmp_path, monkeypatch):
    out = tmp_path / "out"
    (out / "ingested").mkdir(parents=True)
    (out / "originals").mkdir()
    (out / "graph_data.json").write_text(json.dumps({"nodes": [], "links": []}), encoding="utf-8")
    (out / "ingested" / "rel_doc.txt").write_text("Rel", encoding="utf-8")
    (out / "originals" / "Rel Doc.pdf").write_bytes(b"%PDF-1.4 stub")
    triage = {"documents": [{"doc_id": "rel_doc", "file_path": "originals/Rel Doc.pdf"}]}
    (out / "triage.json").write_text(json.dumps(triage), encoding="utf-8")

    # A decoy at the same relative path under the process cwd must not be used.
    elsewhere = tmp_path / "elsewhere"
    (elsewhere / "originals").mkdir(parents=True)
    monkeypatch.chdir(elsewhere)
    docs = _assert_flag_matches_endpoint(TestClient(create_app(out, domain=None)))
    assert docs["rel_doc"]["has_pdf"] is True

    # And a relative path that only exists under the cwd is not a PDF of this output.
    (out / "originals" / "Rel Doc.pdf").unlink()
    (elsewhere / "originals" / "Rel Doc.pdf").write_bytes(b"%PDF-1.4 stub")
    docs = _assert_flag_matches_endpoint(TestClient(create_app(out, domain=None)))
    assert docs["rel_doc"]["has_pdf"] is False


# -- Where to start ----------------------------------------------------------

EXISTING_KEYS = {
    "html",
    "auto",
    "title",
    "subtitle",
    "entity_counts",
    "total_nodes",
    "total_edges",
    "findings",
    "epistemic",
    "documents",
}


@pytest.mark.parametrize("domain", [None, "drug-discovery"])
def test_glp1_start_here_matches_graph_groups(glp1_copy, domain):
    client = TestClient(create_app(glp1_copy, domain=domain))
    body = client.get("/api/dashboard").json()
    start = body["start_here"]
    assert isinstance(start, dict)
    assert isinstance(start["communities"], list) and isinstance(start["hubs"], list)
    assert len(start["communities"]) == 10
    assert len(start["hubs"]) == 10
    served = client.get("/api/graph/groups").json()["modes"]["cluster"]["groups"]
    sizes = {g["id"]: g["size"] for g in served if g["id"] != "other"}
    assert {c["id"] for c in start["communities"]} == set(sizes)
    assert {c["id"]: c["member_count"] for c in start["communities"]} == sizes
    # Same order as the Groups list the click lands on.
    assert [c["id"] for c in start["communities"]] == list(sizes)


def test_tied_corpus_start_here_order_matches_graph_groups(tmp_path):
    corpus = ROOT / "tests" / "corpora" / "07_glp1_phase3_trials" / "output"
    for name in GLP1_FILES:
        shutil.copy2(corpus / name, tmp_path / name)
    client = TestClient(create_app(tmp_path, domain=None))
    start = client.get("/api/dashboard").json()["start_here"]
    served = client.get("/api/graph/groups").json()["modes"]["cluster"]["groups"]
    served_ids = [g["id"] for g in served if g["id"] != "other"]
    assert len(served_ids) == 8
    assert [c["id"] for c in start["communities"]] == served_ids


def test_existing_dashboard_keys_kept(glp1_copy):
    body = TestClient(create_app(glp1_copy, domain=None)).get("/api/dashboard").json()
    assert EXISTING_KEYS <= set(body), EXISTING_KEYS - set(body)
    assert set(body) == EXISTING_KEYS | {"start_here"}
    assert body["auto"] is True and body["html"] is None


def test_start_here_without_communities(tmp_path):
    graph = {
        "nodes": [
            {"id": "e1", "name": "One", "entity_type": "DRUG"},
            {"id": "e2", "name": "Two", "entity_type": "DISEASE"},
            {"id": "e3", "name": "Three", "entity_type": "PROTEIN"},
            {"id": "doc:a", "name": "a", "entity_type": "DOCUMENT"},
        ],
        "links": [
            {"source": "e1", "target": "e2", "relation_type": "TREATS"},
            {"source": "e2", "target": "e3", "relation_type": "ASSOCIATED_WITH"},
            {"source": "e1", "target": "e3", "relation_type": "TARGETS"},
            {"source": "e1", "target": "doc:a", "relation_type": "MENTIONED_IN"},
        ],
    }
    (tmp_path / "graph_data.json").write_text(json.dumps(graph), encoding="utf-8")
    body = TestClient(create_app(tmp_path, domain=None)).get("/api/dashboard").json()
    start = body["start_here"]
    assert start["communities"] == []
    assert [h["id"] for h in start["hubs"]] == ["e1", "e3", "e2"]  # One, Three, Two
    assert [h["connections"] for h in start["hubs"]] == [2, 2, 2]
    assert all(h["community_id"] is None for h in start["hubs"])
