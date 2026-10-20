"""Deterministic synthetic knowledge graph for workbench performance tests.

The default size (1738 nodes, 2500 edges, one ~300-edge hub) mirrors the largest
corpus the workbench is exercised against. Only a private ``random.Random`` is
used, so the same seed always yields the same graph.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

ENTITY_TYPES = ["COMPOUND", "DISEASE", "PROTEIN"]
SOURCE_TYPE = "DOCUMENT"
RELATIONS = [
    "TREATS",
    "INHIBITS",
    "ACTIVATES",
    "INDICATED_FOR",
    "DEVELOPES",
    "BINDS_TO",
    "ASSOCIATED_WITH",
]
STATUSES = ["asserted", "hypothesized", "prophetic", "speculative"]
STATUS_WEIGHTS = [85, 8, 4, 3]
NAME_WORDS = [
    "alpha",
    "receptor",
    "agonist",
    "semaglutide",
    "tirzepatide",
    "obesity",
    "diabetes",
    "kinase",
    "inhibitor",
    "glucagon",
    "peptide",
    "clinical",
    "syndrome",
]
HUB_EDGES = 300


def _name(rng: random.Random, index: int) -> str:
    """Return a name of varied length (some longer than 22 characters)."""
    count = rng.choice([1, 2, 2, 3, 4, 5])
    words = [rng.choice(NAME_WORDS) for _ in range(count)]
    return f"{' '.join(words)} {index}"


def make_synthetic_graph(n_nodes: int = 1738, n_edges: int = 2500, seed: int = 7) -> dict:
    """Build a GLP-1-shaped graph dict with ``nodes`` and ``links`` lists."""
    rng = random.Random(seed)
    nodes: list[dict] = []
    for i in range(n_nodes):
        is_doc = i > 0 and rng.random() < 0.2
        etype = SOURCE_TYPE if is_doc else rng.choice(ENTITY_TYPES)
        if i == 0:
            etype = "COMPOUND"
        nodes.append(
            {
                "id": f"n{i}",
                "name": _name(rng, i) if i else "hub compound with a very long display name",
                "entity_type": etype,
                "source_documents": [
                    f"doc{rng.randrange(40)}.pdf" for _ in range(rng.randrange(0, 6))
                ],
            }
        )

    links: list[dict] = []
    for i in range(n_edges):
        if i < HUB_EDGES:
            a, b = 0, rng.randrange(1, n_nodes)
        else:
            a, b = rng.randrange(n_nodes), rng.randrange(n_nodes)
        if nodes[a]["entity_type"] == SOURCE_TYPE and nodes[b]["entity_type"] != SOURCE_TYPE:
            a, b = b, a
        if nodes[b]["entity_type"] == SOURCE_TYPE:
            relation = "MENTIONED_IN"
        else:
            relation = rng.choice(RELATIONS)
        links.append(
            {
                "source": nodes[a]["id"],
                "target": nodes[b]["id"],
                "relation_type": relation,
                "relation_id": f"r{i}",
                "confidence": round(rng.uniform(0.5, 1.0), 2),
                "support_count": max(1, min(11, int(rng.paretovariate(1.5)))),
                "epistemic_status": rng.choices(STATUSES, weights=STATUS_WEIGHTS)[0],
            }
        )
    return {"nodes": nodes, "links": links}


def write_synthetic_graph(path: Path) -> Path:
    """Write the default synthetic graph to ``path`` as indented JSON."""
    path.write_text(json.dumps(make_synthetic_graph(), indent=2))
    return path
