"""Group assignment core (normalize, short labels, availability) and /api/graph/groups."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
GLP1 = ROOT / "tests" / "corpora" / "06_glp1_landscape" / "output-v3"
DRUG_YAML = ROOT / "domains" / "drug-discovery" / "domain.yaml"
FIXTURES = ROOT / "tests" / "fixtures"
SOURCE_TYPES = {"DOCUMENT", "PUBLICATION"}


def _graph() -> dict:
    return json.loads((GLP1 / "graph_data.json").read_text())


def _communities() -> dict:
    return json.loads((GLP1 / "communities.json").read_text())


def _display() -> dict:
    from core.graph_display import resolve_display

    observed = {n["entity_type"] for n in _graph()["nodes"]}
    return resolve_display(yaml.safe_load(DRUG_YAML.read_text()), observed, None)


def _glp1_groups() -> dict:
    from core.graph_groups import build_groups

    graph = _graph()
    return build_groups(graph["nodes"], graph["links"], _communities(), _display())


def _knowledge_ids() -> set[str]:
    return {n["id"] for n in _graph()["nodes"] if n["entity_type"] not in SOURCE_TYPES}


# ---------------------------------------------------------------------------
# normalize_communities
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_normalize_flat_list_and_node_field_agree():
    from core.graph_groups import normalize_communities

    nodes = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
    flat = {"a": "Alpha", "b": "Alpha", "c": "Beta"}
    listed = {
        "communities": [
            {"id": 0, "label": "Alpha", "members": ["a", "b"]},
            {"id": 1, "label": "Beta", "members": ["c"]},
        ]
    }
    from_nodes = [
        {"id": "a", "community": "Alpha"},
        {"id": "b", "community": "Alpha"},
        {"id": "c", "community": "Beta"},
    ]
    expected = {"a": "Alpha", "b": "Alpha", "c": "Beta"}
    assert normalize_communities(flat, nodes) == expected
    assert normalize_communities(listed, nodes) == expected
    assert normalize_communities({}, from_nodes) == expected
    assert normalize_communities(None, from_nodes) == expected


@pytest.mark.unit
def test_normalize_non_string_and_empty_labels():
    from core.graph_groups import normalize_communities

    nodes = [{"id": "a"}, {"id": "b"}, {"id": "c"}, {"id": "d"}]
    got = normalize_communities({"a": 7, "b": 7, "c": "", "d": None}, nodes)
    assert got["a"] == "7" and got["b"] == "7", got
    assert got["c"] == "Cluster 2", got
    assert "d" not in got, got


@pytest.mark.unit
def test_normalize_garbage_returns_empty():
    from core.graph_groups import normalize_communities

    for raw in ([], 5, None, "x", [1, 2], {"communities": "nope"}, {"communities": [3, None]}):
        assert normalize_communities(raw, []) == {}, raw
    assert normalize_communities({}, None) == {}
    assert normalize_communities({}, [None, 3, {"x": 1}]) == {}


@pytest.mark.unit
def test_normalize_glp1_covers_communities_file():
    from core.graph_groups import normalize_communities

    got = normalize_communities(_communities(), _graph()["nodes"])
    assert len(got) == 235
    assert len(set(got.values())) == 10


# ---------------------------------------------------------------------------
# short_label
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_short_label_easy_cases():
    from core.graph_groups import short_label

    assert short_label("Systemic Hypertension — Glp-1(7-37)") == "Systemic Hypertension"
    assert short_label("Parkinson Disease — Glucagon, Insulin") == "Parkinson Disease"
    assert short_label("Dopaminergic Pathway") == "Dopaminergic Pathway"


@pytest.mark.unit
def test_short_label_real_glp1_labels_hold_invariants():
    from core.graph_groups import MAX_SHORT_LABEL, short_label

    for label in set(_communities().values()):
        first = short_label(label)
        assert 1 <= len(first) <= MAX_SHORT_LABEL, (label, first)
        assert short_label(label) == first, label


@pytest.mark.unit
def test_short_label_keeps_more_suffix():
    from core.graph_groups import short_label

    got = short_label("Hydrochlorothiazide / Lisinopril / Amlodipine + 4 more")
    assert got.endswith("+4"), got
    assert "+…" not in got and len(got) <= 24, got


@pytest.mark.unit
def test_short_label_hostile_text_is_literal():
    from core.graph_groups import short_label

    hostile = "<img src=x onerror=alert(1)>"
    got = short_label(hostile)
    assert got.startswith("<img src=x"), got
    assert "&lt;" not in got and len(got) <= 24, got
    assert short_label("  spaced   out\n label ") == "spaced out label"
    for empty in (None, "", "   "):
        assert short_label(empty), empty


# ---------------------------------------------------------------------------
# build_groups: GLP-1
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_glp1_cluster_groups_and_labels():
    payload = _glp1_groups()
    assert payload["default"] == "cluster"
    cluster = payload["modes"]["cluster"]
    assert cluster["available"] is True and cluster["reason"] is None
    groups = cluster["groups"]
    assert len(groups) == 11
    assert [g["id"] for g in groups] == [f"c{i}" for i in range(1, 11)] + ["other"]
    assert groups[-1]["label"] == "Unclustered"
    labels = [g["label"] for g in groups]
    assert len(set(labels)) == len(labels), labels
    assert all(1 <= len(lab) <= 24 for lab in labels), labels
    assert all(len(g["full_label"]) <= 200 and g["full_label"] for g in groups)
    real = groups[:-1]
    assert [g["size"] for g in real] == sorted((g["size"] for g in real), reverse=True)
    assert sum(g["size"] for g in groups) == len(_knowledge_ids()) == 218
    assert set(cluster["assignment"]) >= _knowledge_ids()
    assert set(cluster["assignment"].values()) <= {g["id"] for g in groups}


@pytest.mark.unit
def test_glp1_family_groups():
    family = _glp1_groups()["modes"]["family"]
    assert family["available"] is True
    groups = family["groups"]
    assert len(groups) >= 2
    assert all(g["id"] == "f:" + g["label"].lower() for g in groups), groups
    assert "sources" not in {g["label"].lower() for g in groups}
    assert sum(g["size"] for g in groups) == 218
    assert set(family["assignment"]) >= _knowledge_ids()


# ---------------------------------------------------------------------------
# build_groups: sources, availability
# ---------------------------------------------------------------------------


def _toy_nodes() -> list[dict]:
    return [
        {"id": "a1", "entity_type": "COMPOUND"},
        {"id": "a2", "entity_type": "COMPOUND"},
        {"id": "a3", "entity_type": "COMPOUND"},
        {"id": "b1", "entity_type": "DISEASE"},
        {"id": "b2", "entity_type": "DISEASE"},
        {"id": "d1", "entity_type": "DOCUMENT"},
        {"id": "d2", "entity_type": "DOCUMENT"},
        {"id": "d3", "entity_type": "PUBLICATION"},
        {"id": "d4", "entity_type": "DOCUMENT"},
    ]


TOY_COMMUNITIES = {"a1": "Alpha", "a2": "Alpha", "a3": "Alpha", "b1": "Beta", "b2": "Beta"}


def _link(a: str, b: str) -> dict:
    return {"source": a, "target": b, "relation_type": "MENTIONED_IN"}


@pytest.mark.unit
def test_sources_join_plurality_group():
    from core.graph_groups import build_groups

    links = [
        _link("a1", "d1"),
        _link("a2", "d1"),
        _link("b1", "d1"),
        _link("d3", "a3"),
    ]
    payload = build_groups(_toy_nodes(), links, TOY_COMMUNITIES)
    cluster = payload["modes"]["cluster"]
    assign = cluster["assignment"]
    alpha = assign["a1"]
    assert assign["d1"] == alpha and assign["d3"] == alpha
    assert "d4" not in assign and "d2" not in assign
    assert sum(g["size"] for g in cluster["groups"]) == 5


@pytest.mark.unit
def test_sources_tie_goes_to_larger_group():
    from core.graph_groups import build_groups

    payload = build_groups(
        _toy_nodes(), [_link("a1", "d1"), _link("b1", "d1")], TOY_COMMUNITIES
    )
    assign = payload["modes"]["cluster"]["assignment"]
    assert assign["d1"] == assign["a1"], "tie must go to the larger group (Alpha has 3)"


@pytest.mark.unit
def test_availability_without_communities_falls_back_to_family():
    from core.graph_groups import build_groups

    display = _display()
    graph = _graph()
    nodes = [{k: v for k, v in n.items() if k != "community"} for n in graph["nodes"]]
    payload = build_groups(nodes, graph["links"], {}, display)
    cluster = payload["modes"]["cluster"]
    assert cluster["available"] is False
    assert cluster["reason"] == "No topic clusters in this project"
    assert cluster["groups"] == [] and cluster["assignment"] == {}
    assert payload["default"] == "family"
    assert payload["modes"]["family"]["available"] is True


@pytest.mark.unit
def test_availability_single_cluster_and_no_families():
    from core.graph_groups import build_groups

    nodes = [{"id": "x", "entity_type": "FOO"}, {"id": "y", "entity_type": "FOO"}]
    one = build_groups(nodes, [], {"x": "Only", "y": "Only"})
    assert one["modes"]["cluster"]["available"] is False
    assert one["modes"]["cluster"]["reason"] == "Only one topic cluster found"
    assert one["modes"]["family"]["available"] is False
    assert one["modes"]["family"]["reason"] == "No entity families defined for this domain"
    assert one["default"] == "none"


@pytest.mark.unit
def test_availability_collisions_stay_unique_and_short():
    from core.graph_groups import build_groups

    labels = [
        "Hypertension Therapy Alpha Study — one",
        "Hypertension Therapy Alpha Study — two",
        "Hypertension Therapy Alpha Study — three",
    ]
    nodes, comm = [], {}
    for i, label in enumerate(labels):
        for j in range(3 - i):
            nid = f"n{i}_{j}"
            nodes.append({"id": nid, "entity_type": "FOO"})
            comm[nid] = label
    groups = build_groups(nodes, [], comm)["modes"]["cluster"]["groups"]
    shorts = [g["label"] for g in groups]
    assert len(shorts) == 3 and len(set(shorts)) == 3, shorts
    assert all(1 <= len(s) <= 24 for s in shorts), shorts


@pytest.mark.unit
def test_availability_survives_garbage_input():
    from core.graph_groups import build_groups

    for args in (
        (None, None, None),
        ([None, 3, {"id": None}], "x", [1]),
        ([{"id": "a", "entity_type": 5}], [{"source": {}, "target": []}], {"a": ["x"]}),
    ):
        payload = build_groups(*args)
        assert payload["default"] in {"cluster", "family", "none"}


@pytest.mark.unit
def test_cluster_group_count_is_capped():
    from core.graph_groups import MAX_CLUSTER_GROUPS, build_groups

    nodes = [{"id": f"n{i}", "entity_type": "FOO"} for i in range(MAX_CLUSTER_GROUPS + 40)]
    comm = {n["id"]: f"Topic {n['id']}" for n in nodes}
    groups = build_groups(nodes, [], comm)["modes"]["cluster"]["groups"]
    assert len(groups) == MAX_CLUSTER_GROUPS + 1
    assert groups[-1]["id"] == "other" and groups[-1]["size"] == 40


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


def _client(output: Path, domain: str):
    from examples.workbench.server import create_app
    from starlette.testclient import TestClient

    return TestClient(create_app(output, domain=domain))


@pytest.mark.unit
def test_api_groups_glp1(tmp_path):
    shutil.copy(GLP1 / "graph_data.json", tmp_path / "graph_data.json")
    shutil.copy(GLP1 / "communities.json", tmp_path / "communities.json")
    client = _client(tmp_path, "drug-discovery")
    resp = client.get("/api/graph/groups")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["default"] == "cluster"
    assert set(body["modes"]) == {"cluster", "family"}
    cluster = body["modes"]["cluster"]
    assert len(cluster["groups"]) == 11
    for g in cluster["groups"]:
        assert {"id", "label", "full_label", "size"} <= set(g)
        assert len(g["label"]) <= 24 and len(g["full_label"]) <= 200
    assert set(cluster["assignment"]) >= _knowledge_ids()
    communities = client.get("/api/graph/communities").json()
    assert communities == _communities()


@pytest.mark.unit
def test_api_groups_contracts_fixture(tmp_path):
    shutil.copy(FIXTURES / "sample_graph_data.json", tmp_path / "graph_data.json")
    shutil.copy(FIXTURES / "sample_communities.json", tmp_path / "communities.json")
    body = _client(tmp_path, "contracts").get("/api/graph/groups").json()
    assert body["modes"]["cluster"]["available"] is True, body["modes"]["cluster"]["reason"]
    assert len(body["modes"]["cluster"]["groups"]) >= 2


@pytest.mark.unit
def test_api_groups_without_communities(tmp_path):
    graph = _graph()
    for node in graph["nodes"]:
        node.pop("community", None)
    (tmp_path / "graph_data.json").write_text(json.dumps(graph))
    resp = _client(tmp_path, "drug-discovery").get("/api/graph/groups")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["modes"]["cluster"]["available"] is False
    assert body["modes"]["cluster"]["reason"] == "No topic clusters in this project"
    assert body["default"] == "family"
