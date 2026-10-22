"""Start-here data for the workbench Dashboard: topic communities and hub entities."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
CORPORA = ROOT / "tests" / "corpora"
GLP1 = CORPORA / "06_glp1_landscape" / "output-v3"
DRUG_YAML = ROOT / "domains" / "drug-discovery" / "domain.yaml"

COMMUNITY_KEYS = {"id", "label", "full_label", "member_count", "top_members"}
HUB_KEYS = {"id", "name", "entity_type", "connections", "community_id", "community_label"}
SOURCE_TYPES = ("DOCUMENT", "PUBLICATION")
PROVENANCE = ("MENTIONED_IN", "PUBLISHED_IN")

pytestmark = pytest.mark.unit


def _build(nodes, links, groups, display=None):
    from core.dashboard_start import build_start_here

    return build_start_here(nodes, links, groups, display)


def _loaded(corpus: Path):
    from examples.workbench.data_loader import WorkbenchData

    data = WorkbenchData(corpus)
    return data, data.get_nodes(), data.get_edges()


def _display(nodes) -> dict:
    from core.graph_display import entity_type_key, resolve_display

    observed = {entity_type_key(n.get("entity_type")) for n in nodes}
    return resolve_display(yaml.safe_load(DRUG_YAML.read_text()), observed, None)


def _served_groups(nodes, links, communities, display=None) -> dict:
    """The /api/graph/groups payload, built the way the server builds it."""
    from core.graph_groups import build_groups

    return build_groups(nodes, links, communities, display)


def _glp1():
    data, nodes, links = _loaded(GLP1)
    display = _display(nodes)
    groups = _served_groups(nodes, links, data.communities, display)
    return nodes, links, groups, display


def _independent_counts(graph_json: Path) -> tuple[dict[str, int], dict[str, dict]]:
    """Recount knowledge connections straight from graph_data.json.

    Returns ``({node_id: connections}, {node_id: node})`` for knowledge nodes.
    """
    graph = json.loads(graph_json.read_text())
    knowledge = {
        n["id"]: n
        for n in graph["nodes"]
        if n.get("entity_type") not in SOURCE_TYPES and not n["id"].startswith("doc:")
    }
    keys: dict[str, set] = {node_id: set() for node_id in knowledge}
    for link in graph["links"]:
        rtype = link.get("relation_type")
        if rtype in PROVENANCE:
            continue
        source, target = link["source"], link["target"]
        if source not in knowledge or target not in knowledge:
            continue
        key = link.get("relation_id") or f"{source}|{rtype}|{target}"
        keys[source].add(key)
        keys[target].add(key)
    return {node_id: len(k) for node_id, k in keys.items()}, knowledge


def _cluster(groups_payload: dict) -> dict:
    return groups_payload["modes"]["cluster"]


def _payload(groups, assignment=None, available=True) -> dict:
    """A minimal groups payload with only a cluster mode."""
    return {
        "default": "cluster",
        "modes": {
            "cluster": {
                "available": available,
                "reason": None,
                "groups": groups,
                "assignment": assignment or {},
            }
        },
    }


def _group(gid, size, label=None, full_label=None):
    label = label if label is not None else gid.upper()
    return {
        "id": gid,
        "label": label,
        "full_label": full_label if full_label is not None else label,
        "size": size,
    }


def _node(node_id, entity_type="DRUG", name=None):
    return {"id": node_id, "entity_type": entity_type, "name": name or node_id}


def _link(source, target, rtype="TREATS", rid=None):
    link = {"source": source, "target": target, "relation_type": rtype}
    if rid is not None:
        link["relation_id"] = rid
    return link


def _hub_ids(result):
    return [h["id"] for h in result["hubs"]]


def _hub(result, node_id):
    return next(h for h in result["hubs"] if h["id"] == node_id)


# --- GLP-1 v3, cross-checked against build_groups and graph_data.json -------


def test_glp1_communities_match_served_cluster_groups():
    nodes, links, groups, display = _glp1()
    result = _build(nodes, links, groups, display)
    communities = result["communities"]
    served = [g for g in _cluster(groups)["groups"] if g["id"] != "other"]
    assert len(communities) == 10 == len(served)
    assert all(set(c) == COMMUNITY_KEYS for c in communities)
    # The served order itself (size, then full label, then id), never re-derived.
    assert [c["id"] for c in communities] == [g["id"] for g in served]
    by_id = {g["id"]: g for g in served}
    for row in communities:
        group = by_id[row["id"]]
        assert row["label"] == group["label"], row["id"]
        assert row["full_label"] == group["full_label"], row["id"]
        assert row["member_count"] == group["size"], row["id"]
    largest = max(g["size"] for g in served)
    assert communities[0]["member_count"] == largest == 38


def test_glp1_top_members_follow_independent_counts():
    nodes, links, groups, display = _glp1()
    result = _build(nodes, links, groups, display)
    counts, knowledge = _independent_counts(GLP1 / "graph_data.json")
    assignment = _cluster(groups)["assignment"]
    for row in result["communities"]:
        members = [n for n in knowledge if assignment.get(n) == row["id"] and counts[n] > 0]
        members.sort(key=lambda n: (-counts[n], knowledge[n]["name"].lower(), n))
        expected = [knowledge[n]["name"] for n in members[:3]]
        assert 1 <= len(row["top_members"]) <= 3, row
        assert row["top_members"] == expected, row["id"]


def test_glp1_hubs_match_independent_recount():
    nodes, links, groups, display = _glp1()
    result = _build(nodes, links, groups, display)
    hubs = result["hubs"]
    assert len(hubs) == 10
    assert all(set(h) == HUB_KEYS for h in hubs)
    counts, knowledge = _independent_counts(GLP1 / "graph_data.json")
    ranked = sorted(
        (n for n in counts if counts[n] > 0),
        key=lambda n: (-counts[n], knowledge[n]["name"].lower(), n),
    )[:10]
    assert _hub_ids(result) == ranked
    assert [h["connections"] for h in hubs] == [counts[n] for n in ranked]
    assert all(h["connections"] > 0 for h in hubs)
    assert [h["name"] for h in hubs] == [knowledge[n]["name"] for n in ranked]


def test_glp1_hub_type_and_community_fields():
    from core.graph_display import entity_type_key

    nodes, links, groups, display = _glp1()
    result = _build(nodes, links, groups, display)
    cluster = _cluster(groups)
    labels = {g["id"]: g["label"] for g in cluster["groups"]}
    index = {n["id"]: n for n in nodes}
    for hub in result["hubs"]:
        assert hub["entity_type"] == entity_type_key(index[hub["id"]].get("entity_type"))
        gid = cluster["assignment"].get(hub["id"])
        if gid is None or gid == "other":
            assert hub["community_id"] is None and hub["community_label"] is None
        else:
            assert hub["community_id"] == gid
            assert hub["community_label"] == labels[gid]


# --- synthetic graphs --------------------------------------------------------

SMALL_NODES = [_node("a", name="Alpha"), _node("b", name="Beta"), _node("c", name="Gamma")]
SMALL_LINKS = [_link("a", "b", rid="r1"), _link("b", "c", rid="r2")]


@pytest.mark.parametrize(
    "groups",
    [
        _payload([_group("c1", 2)], {"a": "c1"}, available=False),
        {"default": "none", "modes": {}},
        {"default": "none", "modes": {"cluster": None}},
        None,
        _payload("not a list", {"a": "c1"}),
    ],
    ids=["unavailable", "missing", "none-mode", "none-payload", "groups-not-list"],
)
def test_cluster_mode_unavailable_gives_no_communities(groups):
    result = _build(SMALL_NODES, SMALL_LINKS, groups)
    assert result["communities"] == []
    assert _hub_ids(result) == ["b", "a", "c"]
    for hub in result["hubs"]:
        assert hub["community_id"] is None and hub["community_label"] is None


def test_list_shape_communities_json_rows_match_groups():
    nodes = [_node(f"n{i}", name=f"Node {i}") for i in range(6)]
    links = [
        _link("n0", "n1", rid="r1"),
        _link("n0", "n2", rid="r2"),
        _link("n1", "n2", rid="r3"),
        _link("n3", "n4", rid="r4"),
        _link("n4", "n5", rid="r5"),
    ]
    communities = {
        "communities": [
            {"id": 0, "label": "Small Topic", "members": ["n3", "n4"]},
            {"id": 1, "label": "Big Topic", "members": ["n0", "n1", "n2", "n5"]},
        ]
    }
    groups = _served_groups(nodes, links, communities)
    assert _cluster(groups)["available"] is True
    result = _build(nodes, links, groups)
    served = [g for g in _cluster(groups)["groups"] if g["id"] != "other"]
    assert [c["id"] for c in result["communities"]] == [g["id"] for g in served]
    assert [c["member_count"] for c in result["communities"]] == [4, 2]
    assert result["communities"][0]["full_label"] == "Big Topic"
    assert result["communities"][0]["top_members"][0] in {"Node 0", "Node 1", "Node 2"}
    assert result["communities"][1]["top_members"] == ["Node 4", "Node 3"]


def test_scrambled_groups_are_resorted_by_size_then_full_label_then_id():
    # The /api/graph/groups key: size desc, then full label (case-sensitive), then id.
    groups = _payload(
        [
            _group("g3", 2, "beta"),
            _group("g1", 5, "Zeta"),
            _group("g4", 2, "alpha"),
            _group("g2", 2, "Alpha"),
            _group("g5", 2, "Alpha"),
        ]
    )
    result = _build(SMALL_NODES, SMALL_LINKS, groups)
    assert [c["id"] for c in result["communities"]] == ["g1", "g2", "g5", "g4", "g3"]


def test_size_ties_follow_full_label_not_short_label():
    # Short labels are truncated and suffixed ("Adults With… 2"), so their order
    # can differ from the full labels the Groups list is sorted by.
    groups = _payload(
        [
            _group("c1", 3, "Adults With Type 2…", "Adults With Type 2 Diabetes"),
            _group("c2", 3, "Adults With… 2", "Adults With Obesity"),
        ]
    )
    result = _build(SMALL_NODES, SMALL_LINKS, groups)
    assert [c["id"] for c in result["communities"]] == ["c2", "c1"]


def test_tied_corpus_communities_keep_the_served_order():
    # 07_glp1_phase3_trials has three 13-member groups whose short-label order
    # ("Adults With Type 2…" < "Adults With… 2") differs from the served order.
    data, nodes, links = _loaded(CORPORA / "07_glp1_phase3_trials" / "output")
    groups = _served_groups(nodes, links, data.communities)
    served = [g for g in _cluster(groups)["groups"] if g["id"] != "other"]
    sizes = [g["size"] for g in served]
    assert any(sizes.count(size) > 1 for size in sizes), "fixture lost its size tie"
    tied = sorted(served, key=lambda g: (-g["size"], g["label"].lower(), g["id"]))
    assert tied != served, "fixture no longer separates short-label and served order"
    result = _build(nodes, links, groups)
    assert [c["id"] for c in result["communities"]] == [g["id"] for g in served]


def test_other_group_is_excluded_even_when_ranked_first():
    groups = _payload(
        [_group("other", 99, "Unclustered"), _group("c1", 2, "Real")],
        {"a": "other", "b": "c1", "c": "c1"},
    )
    result = _build(SMALL_NODES, SMALL_LINKS, groups)
    assert [c["id"] for c in result["communities"]] == ["c1"]
    assert _hub(result, "a")["community_id"] is None
    assert _hub(result, "a")["community_label"] is None
    assert _hub(result, "b")["community_id"] == "c1"
    assert _hub(result, "b")["community_label"] == "Real"


def test_display_source_type_is_excluded_from_hubs_and_top_members():
    nodes = SMALL_NODES + [_node("s", entity_type="SOURCEISH", name="A Source")]
    links = SMALL_LINKS + [
        _link("s", "a", rid="r3"),
        _link("s", "b", rid="r4"),
        _link("s", "c", rid="r5"),
    ]
    display = {"types": {"SOURCEISH": {"is_source": True}, "DRUG": {"is_source": False}}}
    groups = _payload([_group("c1", 3)], {"a": "c1", "b": "c1", "c": "c1", "s": "c1"})
    result = _build(nodes, links, groups, display)
    assert "s" not in _hub_ids(result)
    assert "A Source" not in result["communities"][0]["top_members"]
    assert _hub(result, "a")["connections"] == 1


def test_source_edge_relation_from_display_is_not_counted():
    links = SMALL_LINKS + [_link("a", "c", rtype="CITED_BY", rid="r9")]
    display = {"relations": {"CITED_BY": {"source_edge": True}}}
    result = _build(SMALL_NODES, links, None, display)
    assert _hub(result, "a")["connections"] == 1
    assert _hub(result, "c")["connections"] == 1


def test_mentioned_in_and_published_in_never_count():
    links = [
        _link("a", "b", rtype="MENTIONED_IN", rid="m1"),
        _link("a", "c", rtype="PUBLISHED_IN", rid="p1"),
        _link("b", "c", rid="r1"),
    ]
    result = _build(SMALL_NODES, links, None)
    assert "a" not in _hub_ids(result)
    assert _hub(result, "b")["connections"] == 1


def test_links_touching_source_nodes_never_count():
    nodes = SMALL_NODES + [
        {"id": "doc:x", "entity_type": "DRUG", "name": "doc x"},
        {"id": "pub", "entity_type": "PUBLICATION", "name": "pub"},
    ]
    links = [
        _link("a", "doc:x", rtype="DEVELOPES", rid="d1"),
        _link("pub", "a", rtype="ASSOCIATED_WITH", rid="d2"),
        _link("b", "c", rid="r1"),
    ]
    result = _build(nodes, links, None)
    assert _hub_ids(result) == ["b", "c"]


def test_dict_endpoints_are_counted():
    links = [
        {"source": {"id": "a"}, "target": {"id": "b"}, "relation_type": "TREATS"},
        {"source": {"id": "b"}, "target": "c", "relation_type": "TREATS"},
    ]
    result = _build(SMALL_NODES, links, None)
    assert _hub(result, "b")["connections"] == 2
    assert _hub(result, "a")["connections"] == 1


def test_self_loop_counts_once():
    links = [_link("a", "a", rid="loop"), _link("a", "b", rid="r1")]
    result = _build(SMALL_NODES, links, None)
    assert _hub(result, "a")["connections"] == 2
    assert _hub(result, "b")["connections"] == 1


def test_same_relation_id_listed_twice_counts_once():
    links = [_link("a", "b", rid="r1"), _link("a", "b", rid="r1")]
    result = _build(SMALL_NODES, links, None)
    assert _hub(result, "a")["connections"] == 1


def test_relations_without_id_are_keyed_by_endpoints_and_type():
    links = [_link("a", "b"), _link("a", "b"), _link("a", "b", rtype="INHIBITS")]
    result = _build(SMALL_NODES, links, None)
    assert _hub(result, "a")["connections"] == 2


def test_link_to_unknown_node_is_ignored():
    links = [_link("a", "ghost", rid="r1"), _link("b", "c", rid="r2")]
    result = _build(SMALL_NODES, links, None)
    assert "a" not in _hub_ids(result)
    assert "ghost" not in _hub_ids(result)


def test_hub_ties_break_on_case_insensitive_name_then_id():
    nodes = [
        _node("z1", name="beta"),
        _node("a2", name="Alpha"),
        _node("a1", name="alpha"),
        _node("hub", name="Hub"),
    ]
    links = [_link("hub", n, rid=f"r-{n}") for n in ("z1", "a2", "a1")]
    result = _build(nodes, links, None)
    assert _hub_ids(result) == ["hub", "a1", "a2", "z1"]


def test_fewer_than_ten_entities_lists_what_exists():
    result = _build(SMALL_NODES, SMALL_LINKS, None)
    assert len(result["hubs"]) == 3


def test_zero_connection_entities_are_never_listed():
    nodes = SMALL_NODES + [_node("lonely")]
    result = _build(nodes, SMALL_LINKS, None)
    assert "lonely" not in _hub_ids(result)
    assert all(h["connections"] > 0 for h in result["hubs"])
    assert _build(SMALL_NODES, [], None)["hubs"] == []


def test_more_than_ten_connected_entities_gives_exactly_ten():
    nodes = [_node(f"n{i:02d}") for i in range(15)]
    links = [_link(f"n{i:02d}", f"n{i + 1:02d}", rid=f"r{i}") for i in range(14)]
    result = _build(nodes, links, None)
    assert len(result["hubs"]) == 10
    assert [h["connections"] for h in result["hubs"]] == [2] * 10


def test_top_members_keep_three_most_connected_named_members():
    nodes = [_node(f"m{i}", name=f"Member {i}") for i in range(5)]
    links = [
        _link("m0", "m1", rid="r1"),
        _link("m0", "m2", rid="r2"),
        _link("m0", "m3", rid="r3"),
        _link("m1", "m2", rid="r4"),
    ]
    assignment = {f"m{i}": "c1" for i in range(5)}
    result = _build(nodes, links, _payload([_group("c1", 5)], assignment))
    assert result["communities"][0]["top_members"] == ["Member 0", "Member 1", "Member 2"]
    assert result["communities"][0]["member_count"] == 5


def test_name_falls_back_to_label_then_id_tail():
    nodes = [
        {"id": "drug:semaglutide_oral", "entity_type": "DRUG"},
        {"id": "x", "entity_type": "DRUG", "label": "Labelled"},
    ]
    result = _build(nodes, [_link("drug:semaglutide_oral", "x", rid="r1")], None)
    names = {h["id"]: h["name"] for h in result["hubs"]}
    assert names == {"drug:semaglutide_oral": "semaglutide oral", "x": "Labelled"}


@pytest.mark.parametrize("position", [0, 1, 2, 3], ids=["nodes", "links", "groups", "display"])
@pytest.mark.parametrize("bad", [None, "x", 3, [1, "a", None], {}], ids=repr)
def test_malformed_input_never_raises_and_serializes(position, bad):
    args = [SMALL_NODES, SMALL_LINKS, _payload([_group("c1", 3)], {"a": "c1"}), None]
    args[position] = bad
    result = _build(*args)
    assert isinstance(result, dict)
    assert isinstance(result["communities"], list)
    assert isinstance(result["hubs"], list)
    json.dumps(result)


def test_malformed_items_inside_containers_never_raise():
    nodes = [None, 5, {"id": None}, {"id": ""}, {"id": 7}, _node("a"), _node("b")]
    links = [
        None,
        "l",
        {"source": None, "target": 3},
        {"source": [], "target": {}},
        {"relation_id": 5},
        _link("a", "b", rid="r1"),
    ]
    groups = _payload(
        [None, 3, {"id": None}, {"id": 4, "size": 1}, {"id": "c1", "size": -2}, {"id": "c2"}],
        {"a": "c1", "b": 5, 7: "c1"},
    )
    result = _build(nodes, links, groups)
    assert [c["id"] for c in result["communities"]] == ["c1", "c2"]
    assert [c["member_count"] for c in result["communities"]] == [0, 0]
    assert _hub_ids(result) == ["a", "b"]
    json.dumps(result)


def test_hostile_strings_are_returned_verbatim():
    label = "<img src=x onerror=1>"
    name = '"><script>alert(1)</script>'
    nodes = [_node("a", name=name), _node("b")]
    groups = _payload([_group("c1", 2, label, label)], {"a": "c1", "b": "c1"})
    result = _build(nodes, [_link("a", "b", rid="r1")], groups)
    assert result["communities"][0]["label"] == label
    assert result["communities"][0]["full_label"] == label
    assert name in result["communities"][0]["top_members"]
    assert _hub(result, "a")["name"] == name
    assert _hub(result, "a")["community_label"] == label
    assert json.loads(json.dumps(result)) == result


def test_module_is_pure():
    source = (ROOT / "core" / "dashboard_start.py").read_text()
    assert "open(" not in source and "Path(" not in source
    assert "import fastapi" not in source


def test_link_rules_are_shared_with_document_stats():
    # WR-05: one provenance-exclusion rule for hub counts and the Documents
    # table, and no reach into graph_groups' private names.
    import core.dashboard_start as start
    import core.document_stats as stats
    import core.graph_links as links

    for name in ("EXCLUDED_RELATIONS", "DOC_PREFIX", "endpoint", "relation_type", "relation_key"):
        assert getattr(start, name) is getattr(links, name), name
        assert getattr(stats, name) is getattr(links, name), name
    source = (ROOT / "core" / "dashboard_start.py").read_text()
    assert "def _endpoint" not in source and "def _relation_key" not in source
    assert "_is_source" not in source
    from core.graph_groups import is_source_node

    assert start.is_source_node is is_source_node
    assert is_source_node({"entity_type": "DOCUMENT"}, None) is True
    assert is_source_node({"entity_type": "DOCUMENT"}, {"types": {"DOCUMENT": {}}}) is False
    assert is_source_node({"entity_type": "DRUG"}, None) is False
