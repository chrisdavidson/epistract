#!/usr/bin/env python3
"""Epistemic analysis for arxiv_cs domain.

Performs contradiction detection, confidence calibration,
gap analysis, and cross-document linking for arXiv Computer Science
preprints. Classifies relations using a four-level preprint epistemology:

  claimed      -- author's own experimental result on full system (dominant tier)
  reproduced   -- independently replicated or confirmed by third-party
  ablated      -- result from ablation study or component analysis
  theoretical  -- mathematical proof, complexity analysis, or architectural reasoning
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path


# ---------------------------------------------------------------------------
# Domain-specific parameters
# ---------------------------------------------------------------------------

_CONTRADICTION_PAIRS = [
    ("OUTPERFORMS", "OUTPERFORMS"),
    ("ACHIEVES", "BENCHMARK"),
]
_GAP_TARGET_TYPES = {
    "DATASET": "Paper proposes algorithm but names no dataset — cannot verify empirical grounding.",
    "METRIC": "Paper claims performance improvement but names no evaluation metric.",
    "RESULT": "Paper describes benchmark evaluation but reports no quantitative result.",
    "ALGORITHM": "Paper discusses a task without proposing a distinct algorithm (survey or position paper).",
}

# arXiv preprint language markers used by the four-level epistemic classifier.
# Lowercased substrings; matched case-insensitively against link.evidence.
# Classification order: reproduced → claimed → ablated → theoretical.
_REPRODUCED_MARKERS = (
    "we reproduce",
    "consistent with",
    "our replication",
    "across multiple independent",
    "independent implementations",
    "confirm the findings",
)
_CLAIMED_MARKERS = (
    "we achieve",
    "our model achieves",
    "we report",
    "improves over",
    "state-of-the-art",
    "we outperform",
    "surpasses",
    "accuracy of",
    "bleu score of",
    "f1 score of",
    "top-1 accuracy",
    "we propose",
    "our approach achieves",
)
_ABLATED_MARKERS = (
    "ablation study",
    "without ",
    "when we remove",
    "w/o ",
    "ablating",
    "component analysis",
    "we find that removing",
)
_THEORETICAL_MARKERS = (
    "we prove",
    "theorem",
    "o(n",
    "theoretically",
    "by design",
    "in principle",
    "we conjecture",
    "we hypothesize",
    "future work",
    "we believe",
    "is expected to",
)


def analyze_arxiv_cs_epistemic(
    output_dir: Path,
    graph_data: dict,
) -> dict:
    """Analyze epistemic status of arxiv_cs knowledge graph.

    Classifies each relation (link) using arXiv preprint epistemology:
      - reproduced: independent third-party replication or meta-analysis
      - claimed:    author's own experimental result on the full system
      - ablated:    result from ablation study or component analysis
      - theoretical: mathematical proof, complexity bound, or architectural reasoning

    Args:
        output_dir: Directory containing graph outputs.
        graph_data: Parsed graph_data.json with nodes and links.

    Returns:
        Dict with keys: metadata, evidence_tier_counts, epistemic_status_counts,
        summary, base_domain, super_domain.
    """
    nodes = graph_data.get("nodes", [])
    links = graph_data.get("links", [])

    # --- Contradiction detection ---
    conflicts: list[dict] = []
    for pair in _CONTRADICTION_PAIRS:
        if len(pair) != 2:
            continue
        term_a, term_b = pair[0].lower(), pair[1].lower()
        for link in links:
            evidence = str(link.get("evidence", "")).lower()
            if term_a in evidence and term_b in evidence:
                conflicts.append(
                    {
                        "type": "contradiction",
                        "terms": [pair[0], pair[1]],
                        "relation": link.get("id", ""),
                        "evidence": link.get("evidence", ""),
                    }
                )

    # --- arXiv preprint epistemology classification ---
    # Levels reflect author-claimed vs. third-party vs. ablation vs. theory:
    #   reproduced   -- "we reproduce", "consistent with", "our replication"
    #   claimed      -- "we achieve", "state-of-the-art", "BLEU score of", "we propose"
    #   ablated      -- "ablation study", "without [component]", "w/o"
    #   theoretical  -- "we prove", "theorem", "O(n", "we conjecture"
    # Confidence is the tiebreaker when no marker matches.

    reproduced_count = 0
    claimed_count = 0
    ablated_count = 0
    theoretical_count = 0

    for link in links:
        evidence = str(link.get("evidence", "")).lower()
        confidence = link.get("confidence", 0.5)

        if any(marker in evidence for marker in _REPRODUCED_MARKERS):
            level = "reproduced"
        elif any(marker in evidence for marker in _CLAIMED_MARKERS):
            level = "claimed"
        elif any(marker in evidence for marker in _ABLATED_MARKERS):
            level = "ablated"
        elif any(marker in evidence for marker in _THEORETICAL_MARKERS):
            level = "theoretical"
        elif confidence >= 0.85:
            level = "claimed"
        elif confidence >= 0.65:
            level = "ablated"
        else:
            level = "theoretical"

        link["epistemic_status"] = level
        if level == "reproduced":
            reproduced_count += 1
        elif level == "claimed":
            claimed_count += 1
        elif level == "ablated":
            ablated_count += 1
        else:
            theoretical_count += 1

    # --- Gap analysis ---
    gaps: list[dict] = []
    node_types: dict[str, int] = defaultdict(int)
    for node in nodes:
        node_types[node.get("entity_type", "")] += 1

    for gap_category, description in _GAP_TARGET_TYPES.items():
        if node_types.get(gap_category, 0) == 0:
            gaps.append(
                {
                    "category": gap_category,
                    "missing_type": gap_category,
                    "description": description,
                }
            )

    # --- Cross-document linking ---
    doc_entities: dict[str, set] = defaultdict(set)
    for node in nodes:
        for doc in node.get("source_documents", []):
            doc_entities[node.get("name", "")].add(doc)
    cross_doc_entities = [
        {"name": name, "document_count": len(docs)}
        for name, docs in doc_entities.items()
        if len(docs) > 1
    ]

    # --- Build claims_layer ---
    # Top-level evidence_tier_counts: arXiv four-level preprint epistemology
    # (reproduced / claimed / ablated / theoretical).
    # Top-level epistemic_status_counts: v3 standard parity (same values,
    # different key name used by the generic epistemic verifier).
    _tier_counts = {
        "reproduced": reproduced_count,
        "claimed": claimed_count,
        "ablated": ablated_count,
        "theoretical": theoretical_count,
    }
    claims_layer = {
        "metadata": {
            "domain": "arxiv-cs",
            "description": "Epistemic analysis for arxiv_cs domain",
            "generated_from": str(output_dir / "graph_data.json"),
            "total_relations": len(links),
        },
        # Both keys required for narrator/workbench parity (ACS-04 acceptance).
        "evidence_tier_counts": _tier_counts,
        "epistemic_status_counts": _tier_counts,
        "summary": {
            "conflicts_found": len(conflicts),
            "gaps_found": len(gaps),
            "cross_document_entities": len(cross_doc_entities),
            "epistemic_status_counts": _tier_counts,
        },
        "base_domain": {
            "description": "Factual arxiv_cs knowledge graph relations",
            "relation_count": claimed_count,
        },
        "super_domain": {
            "domain": "arxiv-cs",
            "description": "Epistemic layer -- conflicts, gaps, cross-document linking",
            "conflicts": conflicts,
            "coverage_gaps": gaps,
            "cross_document_entities": cross_doc_entities,
        },
    }

    return claims_layer


# ------------------------------------------------------------------
# CUSTOM_RULES -- domain-specific epistemic rules (FIDL-07 opt-in)
# ------------------------------------------------------------------
# Each rule is a callable with signature:
#     rule(nodes: list[dict], links: list[dict], context: dict) -> list[dict]
# where context = {"output_dir", "graph_data", "domain_name"}.
# Rule failures are isolated (one exception logs status='error' but
# does NOT abort the phase). Findings merge into
# claims_layer["super_domain"]["custom_findings"][rule.__name__].
# See docs/known-limitations.md (Per-Domain Extensibility, FIDL-07)
# for the full contract. Example:
#
#     def my_rule(nodes, links, context):
#         return [{"rule_name": "my_rule", "type": "example",
#                   "severity": "INFO", "description": "x",
#                   "evidence": {}}]
#     CUSTOM_RULES.append(my_rule)

CUSTOM_RULES: list = []
