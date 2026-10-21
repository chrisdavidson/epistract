"""Payload parity: the shared core helpers must equal what the workbench routes return."""

from __future__ import annotations

import inspect
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

    assert got_types == expected_types, (
        f"entity-types payload differs: {got_types} != {expected_types}"
    )
    assert got_claims == expected_claims, (
        f"claims payload differs: {got_claims} != {expected_claims}"
    )


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


def test_routes_delegate_to_shared_helpers():
    """The route modules call the core helpers so a future inline copy is caught."""
    from examples.workbench import api_graph

    assert "entity_types_payload" in inspect.getsource(api_graph.get_entity_types)
    assert "claims_payload" in inspect.getsource(api_graph.get_claims)


# ---------------------------------------------------------------------------
# subset_graph
# ---------------------------------------------------------------------------

from core.graph_display import entity_type_key, is_source_edge, resolve_display  # noqa: E402
from core import graph_payloads  # noqa: E402


def subset_graph(*args, **kwargs):
    return graph_payloads.subset_graph(*args, **kwargs)


def _synthetic():
    """Two hubs (h1, h2), a chain c1-c2-c3 off h1, and a document node."""
    types = {"COMPOUND": "COMPOUND", "DOCUMENT": "DOCUMENT"}
    names = {
        "h1": "Hub One",
        "h2": "Hub Two",
        "a": "Alpha",
        "b": "Beta",
        "c1": "Chain 1",
        "c2": "Chain 2",
        "c3": "Chain 3",
        "far": "Far",
        "doc_near": "Doc Near",
        "doc_far": "Doc Far",
        "dup1": "Same",
        "dup2": "Same",
    }
    nodes = [
        {"id": i, "name": n, "entity_type": "DOCUMENT" if i.startswith("doc") else "COMPOUND"}
        for i, n in names.items()
    ]

    def link(s, t, rel="TREATS"):
        return {"source": s, "target": t, "relation_type": rel}

    links = [
        link("h1", "a"),
        link("h1", "b"),
        link("h1", "c1"),
        link("c1", "c2"),
        link("c2", "c3"),
        link("h2", "a"),
        link("h2", "far"),
        link("h2", "dup1"),
        link("h2", "dup2"),
        link("a", "doc_near", "MENTIONED_IN"),
        link("far", "doc_far", "MENTIONED_IN"),
        # a document bridging c3 to doc_far must not extend a neighbourhood
        link("c3", "doc_far", "MENTIONED_IN"),
    ]
    display = resolve_display(None, set(types), None)
    return nodes, links, display


def test_subset_graph_without_filters_is_unchanged():
    nodes, links, display = _synthetic()
    out_nodes, out_links, info = subset_graph(nodes, links, display)
    assert out_nodes == nodes and out_links == links and info is None


def test_subset_neighborhood_by_id_and_case_insensitive_name():
    nodes, links, display = _synthetic()
    by_id, _l, info = subset_graph(nodes, links, display, neighborhood="h1")
    by_name, _l2, _i = subset_graph(nodes, links, display, neighborhood="hub one")
    ids = {n["id"] for n in by_id}
    assert ids == {"h1", "a", "b", "c1", "doc_near"}, ids
    assert {n["id"] for n in by_name} == ids
    assert info["mode"] == "neighborhood" and info["name"] == "Hub One"
    assert info["shown"] == 5 and info["total"] == len(nodes) and info["depth"] == 1


def test_subset_neighborhood_errors_for_missing_and_ambiguous():
    nodes, links, display = _synthetic()
    with pytest.raises(ValueError, match="not found"):
        subset_graph(nodes, links, display, neighborhood="nobody")
    with pytest.raises(ValueError, match="Multiple entities"):
        subset_graph(nodes, links, display, neighborhood="same")


def test_subset_neighborhood_depth_two_and_sources_never_bridge():
    nodes, links, display = _synthetic()
    kept, kept_links, _info = subset_graph(nodes, links, display, neighborhood="h1", depth=2)
    ids = {n["id"] for n in kept}
    assert {"c2", "h2"} <= ids, "depth 2 reaches two knowledge hops"
    assert "c3" not in ids
    # doc_far connects c3 and far, but is only attached to dropped nodes here
    assert "doc_far" not in ids
    kept_ids = ids
    for lk in kept_links:
        assert lk["source"] in kept_ids and lk["target"] in kept_ids


def test_subset_source_attached_to_kept_node_is_kept_and_dropped_otherwise():
    nodes, links, display = _synthetic()
    kept, _l, _i = subset_graph(nodes, links, display, neighborhood="h1", depth=3)
    ids = {n["id"] for n in kept}
    assert "c3" in ids and "doc_far" in ids, "doc attached to kept c3 is kept"
    assert "doc_near" in ids


def test_subset_top_n_hubs_by_knowledge_degree_with_id_tiebreak():
    nodes, links, display = _synthetic()
    kept, _l, info = subset_graph(nodes, links, display, top_n=1)
    ids = {n["id"] for n in kept}
    # h2 has the highest knowledge degree (5); its neighbours come with it
    assert {"h2", "a", "far", "dup1", "dup2"} <= ids
    assert "h1" not in ids
    assert info["mode"] == "top" and info["top_n"] == 1 and info["name"] is None
    kept2, _l2, _i2 = subset_graph(nodes, links, display, top_n=2)
    assert {"h1", "h2"} <= {n["id"] for n in kept2}


def test_subset_neighborhood_wins_over_top():
    nodes, links, display = _synthetic()
    _k, _l, info = subset_graph(nodes, links, display, neighborhood="h1", top_n=1)
    assert info["mode"] == "neighborhood"


def _independent_subset(graph, display, *, start=None, top_n=None):
    """BFS/degree over raw graph_data.json without calling subset_graph."""
    node_type = {n["id"]: entity_type_key(n.get("entity_type")) for n in graph["nodes"]}
    sources = {i for i, t in node_type.items() if display["types"][t]["is_source"]}
    adj: dict[str, set[str]] = {i: set() for i in node_type}
    for lk in graph["links"]:
        if not is_source_edge(lk, sources, display["relations"]):
            adj[lk["source"]].add(lk["target"])
            adj[lk["target"]].add(lk["source"])
    if start is not None:
        keep = {start} | adj[start]
    else:
        ranked = sorted((i for i in adj if i not in sources), key=lambda i: (-len(adj[i]), i))
        hubs = set(ranked[:top_n])
        keep = set(hubs).union(*(adj[h] for h in hubs))
    for lk in graph["links"]:
        if lk["source"] in keep and lk["target"] in sources:
            keep.add(lk["target"])
        if lk["target"] in keep and lk["source"] in sources:
            keep.add(lk["source"])
    links = [lk for lk in graph["links"] if lk["source"] in keep and lk["target"] in keep]
    return keep, links


def _glp1_graph_and_display():
    import json

    graph = json.loads((GLP1 / "graph_data.json").read_text(encoding="utf-8"))
    types = {entity_type_key(n.get("entity_type")) for n in graph["nodes"]}
    return graph, resolve_display(None, types, None)


def test_subset_glp1_neighborhood_semaglutide_matches_independent_bfs():
    graph, display = _glp1_graph_and_display()
    start = next(n["id"] for n in graph["nodes"] if n["name"].lower() == "semaglutide")
    keep, links = _independent_subset(graph, display, start=start)
    nodes_out, links_out, info = subset_graph(
        graph["nodes"], graph["links"], display, neighborhood="semaglutide"
    )
    assert {n["id"] for n in nodes_out} == keep
    assert len(links_out) == len(links)
    assert info["shown"] == len(keep) and info["total"] == len(graph["nodes"])


def test_subset_glp1_top_10_matches_independent_degree_ranking():
    graph, display = _glp1_graph_and_display()
    keep, links = _independent_subset(graph, display, top_n=10)
    nodes_out, links_out, info = subset_graph(graph["nodes"], graph["links"], display, top_n=10)
    assert {n["id"] for n in nodes_out} == keep
    assert len(links_out) == len(links)
    assert info["mode"] == "top" and info["shown"] == len(keep)


@pytest.mark.parametrize("kwargs", [{"top_n": 0}, {"top_n": -1}])
def test_subset_rejects_non_positive_top_n(kwargs):
    nodes, links, display = _synthetic()
    with pytest.raises(ValueError, match="top_n must be >= 1"):
        subset_graph(nodes, links, display, **kwargs)


@pytest.mark.parametrize("depth", [0, -3])
def test_subset_rejects_non_positive_depth(depth):
    nodes, links, display = _synthetic()
    with pytest.raises(ValueError, match="depth must be >= 1"):
        subset_graph(nodes, links, display, neighborhood="h1", depth=depth)
