"""Per-document entity and relation counts for the workbench Dashboard."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CORPORA = ROOT / "tests" / "corpora"
GLP1 = CORPORA / "06_glp1_landscape" / "output-v3"
FDA = CORPORA / "08_fda_labels" / "output"
FIXTURES = ROOT / "tests" / "fixtures"

ROW_KEYS = {
    "doc_id",
    "display_name",
    "filename",
    "entity_count",
    "relation_count",
    "has_text",
    "has_pdf",
}

pytestmark = pytest.mark.unit


def _build(documents, nodes, links):
    from core.document_stats import build_document_stats

    return build_document_stats(documents, nodes, links)


def _loaded(corpus: Path):
    from examples.workbench.data_loader import WorkbenchData

    data = WorkbenchData(corpus)
    return data, data.get_nodes(), data.get_edges()


def _doc(doc_id, **extra):
    row = {
        "doc_id": doc_id,
        "filename": f"{doc_id}.txt",
        "display_name": doc_id,
        "has_text": True,
        "has_pdf": False,
    }
    row.update(extra)
    return row


def _by_id(rows):
    return {r["doc_id"]: r for r in rows}


# --- GLP-1 v3 and FDA labels, cross-checked against graph_data.json ----------


def _recount(corpus: Path) -> dict[str, tuple[int, int]]:
    """Independent recomputation straight from graph_data.json."""
    graph = json.loads((corpus / "graph_data.json").read_text())
    entities: dict[str, set] = {}
    relations: dict[str, set] = {}
    sources = {
        n["id"]
        for n in graph["nodes"]
        if n.get("entity_type") in ("DOCUMENT", "PUBLICATION") or n["id"].startswith("doc:")
    }
    for node in graph["nodes"]:
        if node["id"] in sources:
            continue
        for doc in node.get("source_documents") or []:
            entities.setdefault(doc, set()).add(node["id"])
    for link in graph["links"]:
        if link["relation_type"] in ("MENTIONED_IN", "PUBLISHED_IN"):
            continue
        if link["source"] in sources or link["target"] in sources:
            continue
        docs = set(link.get("support_documents") or [])
        if link.get("source_document"):
            docs.add(link["source_document"])
        docs.update(m["source_document"] for m in link.get("mentions") or [])
        for doc in docs:
            relations.setdefault(doc, set()).add(link["relation_id"])
    every = set(entities) | set(relations)
    return {d: (len(entities.get(d, ())), len(relations.get(d, ()))) for d in every}


def test_glp1_v3_matches_independent_recount():
    data, nodes, links = _loaded(GLP1)
    rows = _build(data.documents, nodes, links)
    assert len(rows) == 34
    assert all(set(r) == ROW_KEYS for r in rows)
    assert all(r["has_text"] is True and r["has_pdf"] is False for r in rows)
    expected = _recount(GLP1)
    for row in rows:
        want = expected.get(row["doc_id"], (0, 0))
        assert (row["entity_count"], row["relation_count"]) == want, row["doc_id"]
    assert max(r["entity_count"] for r in rows) > 0
    assert sum(r["relation_count"] for r in rows) > 0


def test_glp1_v3_links_touching_source_nodes_are_not_counted():
    """GLP-1 v3 has 10 knowledge-typed links to a document/publication node
    (9 DEVELOPES, 1 ASSOCIATED_WITH); none of them adds to relation_count."""
    graph = json.loads((GLP1 / "graph_data.json").read_text())
    sources = {
        n["id"]
        for n in graph["nodes"]
        if n.get("entity_type") in ("DOCUMENT", "PUBLICATION") or n["id"].startswith("doc:")
    }
    touching = [
        link
        for link in graph["links"]
        if link["relation_type"] not in ("MENTIONED_IN", "PUBLISHED_IN")
        and (link["source"] in sources or link["target"] in sources)
    ]
    assert len(touching) == 10, len(touching)
    data, nodes, links = _loaded(GLP1)
    rows = _build(data.documents, nodes, links)
    kept = _build(data.documents, nodes, [link for link in links if link not in touching])
    assert [r["relation_count"] for r in rows] == [r["relation_count"] for r in kept]


def test_glp1_v3_sorted_by_entities_then_name_then_id():
    data, nodes, links = _loaded(GLP1)
    rows = _build(data.documents, nodes, links)
    keys = [(-r["entity_count"], r["display_name"].lower(), r["doc_id"]) for r in rows]
    assert keys == sorted(keys)


def test_fda_labels_seven_documents_with_text():
    data, nodes, links = _loaded(FDA)
    rows = _build(data.documents, nodes, links)
    assert len(rows) == 7
    assert all(r["has_text"] is True for r in rows)
    expected = _recount(FDA)
    for row in rows:
        assert (row["entity_count"], row["relation_count"]) == expected.get(row["doc_id"], (0, 0))


def test_sample_contracts_fixture_lists_referenced_pdfs_without_text():
    """The contracts fixture has edges without provenance keys and ingested ids
    (sample_contract_a/b) that match no node. Documents referenced only through
    node ``source_documents`` ids are still listed, with has_text False, so the
    ``*.pdf`` names appear as no-text rows; the ingested ones get 0/0."""
    graph = json.loads((FIXTURES / "sample_graph_data.json").read_text())
    documents = [_doc("sample_contract_a"), _doc("sample_contract_b")]
    rows = _by_id(_build(documents, graph["nodes"], graph["edges"]))
    for doc_id in ("sample_contract_a", "sample_contract_b"):
        assert rows[doc_id]["has_text"] is True
        assert (rows[doc_id]["entity_count"], rows[doc_id]["relation_count"]) == (0, 0)
    referenced = {d for n in graph["nodes"] for d in n.get("source_documents", [])}
    for doc_id in referenced:
        assert rows[doc_id]["has_text"] is False
        assert rows[doc_id]["display_name"] == rows[doc_id]["filename"] == doc_id
        assert rows[doc_id]["entity_count"] > 0
        assert rows[doc_id]["relation_count"] == 0


# --- synthetic graphs --------------------------------------------------------


def test_referenced_only_documents_are_listed_without_text():
    nodes = [
        {"id": "doc:ghost_one", "entity_type": "DOCUMENT", "source_documents": []},
        {"id": "e1", "entity_type": "DRUG", "source_documents": ["ghost_two"]},
    ]
    links = [
        {
            "source": "e1",
            "target": "doc:ghost_three",
            "relation_type": "MENTIONED_IN",
        }
    ]
    rows = _by_id(_build([], nodes, links))
    assert set(rows) == {"ghost_one", "ghost_two", "ghost_three"}
    for row in rows.values():
        assert row["has_text"] is False and row["has_pdf"] is False
        assert row["display_name"] == row["filename"] == row["doc_id"]
    assert rows["ghost_two"]["entity_count"] == 1
    assert rows["ghost_three"]["entity_count"] == 1


def test_mentioned_in_only_provenance_counts_entity_not_relation():
    nodes = [
        {"id": "doc:a", "entity_type": "DOCUMENT"},
        {"id": "e1", "entity_type": "DRUG"},
        {"id": "e2", "entity_type": "DISEASE"},
    ]
    links = [
        {"source": "e1", "target": "doc:a", "relation_type": "MENTIONED_IN"},
        {"source": "e2", "target": "doc:a", "relation_type": "MENTIONED_IN"},
    ]
    row = _by_id(_build([_doc("a")], nodes, links))["a"]
    assert row["entity_count"] == 2
    assert row["relation_count"] == 0


def test_link_fallback_accepts_dict_endpoints():
    nodes = [{"id": "e1", "entity_type": "DRUG"}]
    links = [
        {
            "source": {"id": "e1"},
            "target": {"id": "doc:a"},
            "relation_type": "MENTIONED_IN",
        }
    ]
    assert _by_id(_build([_doc("a")], nodes, links))["a"]["entity_count"] == 1


def test_published_in_and_mentioned_in_never_count_as_relations():
    links = [
        {
            "source": "e1",
            "target": "publication:p",
            "relation_type": "PUBLISHED_IN",
            "source_document": "a",
        },
        {
            "source": "e1",
            "target": "doc:a",
            "relation_type": "MENTIONED_IN",
            "source_document": "a",
        },
        {"source": "e1", "target": "e2", "relation_type": "TREATS", "source_document": "a"},
    ]
    assert _by_id(_build([_doc("a")], [], links))["a"]["relation_count"] == 1


def test_links_touching_source_nodes_never_count_as_relations():
    nodes = [
        {"id": "doc:a", "entity_type": "DOCUMENT"},
        {"id": "publication:p", "entity_type": "PUBLICATION"},
        {"id": "e1", "entity_type": "DRUG", "source_documents": ["a"]},
        {"id": "e2", "entity_type": "DISEASE", "source_documents": ["a"]},
    ]
    links = [
        {"source": "e1", "target": "doc:a", "relation_type": "DEVELOPES", "source_document": "a"},
        {
            "source": "publication:p",
            "target": "e1",
            "relation_type": "ASSOCIATED_WITH",
            "source_document": "a",
        },
        {
            "source": "doc:unlisted",
            "target": "e2",
            "relation_type": "TREATS",
            "source_document": "a",
        },
        {
            "source": {"id": "e1"},
            "target": {"id": "doc:a"},
            "relation_type": "CITES",
            "source_document": "a",
        },
        {"source": "e1", "target": "e2", "relation_type": "TREATS", "source_document": "a"},
    ]
    row = _by_id(_build([_doc("a")], nodes, links))["a"]
    assert (row["entity_count"], row["relation_count"]) == (2, 1)


def test_source_nodes_and_doc_prefixed_ids_never_count_as_entities():
    nodes = [
        {"id": "doc:a", "entity_type": "DOCUMENT", "source_documents": ["a"]},
        {"id": "publication:p", "entity_type": "PUBLICATION", "source_documents": ["a"]},
        {"id": "doc:odd", "entity_type": "DRUG", "source_documents": ["a"]},
        {"id": "e1", "entity_type": "DRUG", "source_documents": ["a"]},
    ]
    assert _by_id(_build([_doc("a")], nodes, []))["a"]["entity_count"] == 1


def test_relation_attributed_through_mentions_only():
    links = [
        {
            "source": "e1",
            "target": "e2",
            "relation_type": "TREATS",
            "relation_id": "r1",
            "mentions": [{"source_document": "a"}, {"source_document": "b"}],
        }
    ]
    rows = _by_id(_build([_doc("a"), _doc("b")], [], links))
    assert rows["a"]["relation_count"] == rows["b"]["relation_count"] == 1


def test_same_relation_in_several_fields_counts_once():
    links = [
        {
            "source": "e1",
            "target": "e2",
            "relation_type": "TREATS",
            "relation_id": "r1",
            "source_document": "a",
            "support_documents": ["a"],
            "mentions": [{"source_document": "a"}],
        },
        {
            "source": "e1",
            "target": "e2",
            "relation_type": "TREATS",
            "relation_id": "r1",
            "source_document": "a",
        },
    ]
    assert _by_id(_build([_doc("a")], [], links))["a"]["relation_count"] == 1


def test_relation_without_id_is_keyed_by_endpoints_and_type():
    links = [
        {"source": "e1", "target": "e2", "relation_type": "TREATS", "source_document": "a"},
        {"source": "e1", "target": "e2", "relation_type": "TREATS", "source_document": "a"},
        {"source": "e1", "target": "e3", "relation_type": "TREATS", "source_document": "a"},
    ]
    assert _by_id(_build([_doc("a")], [], links))["a"]["relation_count"] == 2


def test_stringified_lists_are_treated_as_one_item():
    nodes = [{"id": "e1", "entity_type": "DRUG", "source_documents": "a"}]
    links = [
        {
            "source": "e1",
            "target": "e2",
            "relation_type": "TREATS",
            "relation_id": "r1",
            "support_documents": "a",
        }
    ]
    row = _by_id(_build([_doc("a")], nodes, links))["a"]
    assert (row["entity_count"], row["relation_count"]) == (1, 1)


@pytest.mark.parametrize(
    "documents, nodes, links",
    [
        ([], [], []),
        (None, None, None),
        ("x", 3, {"a": 1}),
        ([None, 1, "s"], [None, 5, [], "n"], [None, 7, "l"]),
        (
            [{"doc_id": 5}, {}, {"doc_id": ""}],
            [{"id": None, "source_documents": [1, None, {}]}],
            [{"source": None, "target": 3, "mentions": "oops", "support_documents": [None]}],
        ),
    ],
)
def test_malformed_input_never_raises_and_serializes(documents, nodes, links):
    rows = _build(documents, nodes, links)
    assert isinstance(rows, list)
    assert all(set(r) == ROW_KEYS for r in rows)
    json.dumps(rows)


def test_empty_inputs_return_empty_list():
    assert _build([], [], []) == []
    assert _build(None, None, None) == []


def test_hostile_names_are_returned_verbatim():
    hostile = "<img src=x onerror=1>"
    docs = [_doc("a", display_name=hostile, filename=hostile)]
    rows = _build(docs, [], [])
    assert rows[0]["display_name"] == hostile
    assert rows[0]["filename"] == hostile
    assert json.loads(json.dumps(rows)) == rows


def test_display_name_falls_back_to_filename_then_doc_id():
    rows = _by_id(
        _build(
            [
                {"doc_id": "a", "filename": "A.txt", "has_text": True},
                {"doc_id": "b", "has_text": True},
            ],
            [],
            [],
        )
    )
    assert rows["a"]["display_name"] == "A.txt"
    assert rows["b"]["display_name"] == "b" and rows["b"]["filename"] == "b"


def test_sort_ties_break_on_case_insensitive_name_then_id():
    docs = [
        _doc("z1", display_name="beta"),
        _doc("a2", display_name="Alpha"),
        _doc("a1", display_name="alpha"),
    ]
    assert [r["doc_id"] for r in _build(docs, [], [])] == ["a1", "a2", "z1"]


def test_module_is_pure():
    source = (ROOT / "core" / "document_stats.py").read_text()
    assert "open(" not in source and "Path(" not in source
