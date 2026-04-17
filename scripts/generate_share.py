#!/usr/bin/env python3
"""Generate a shareable HTML or Markdown report from a sift-kg knowledge graph."""

import json
import sys
from datetime import datetime
from pathlib import Path


def _load_graph(output_dir: Path) -> dict:
    graph_path = output_dir / "graph_data.json"
    if not graph_path.exists():
        raise FileNotFoundError(f"No graph_data.json found in {output_dir}")
    return json.loads(graph_path.read_text())


def _load_communities(output_dir: Path) -> dict:
    comm_path = output_dir / "communities.json"
    return json.loads(comm_path.read_text()) if comm_path.exists() else {}


def _entity_tables(nodes: list[dict]) -> dict[str, list[dict]]:
    tables: dict[str, list[dict]] = {}
    for node in nodes:
        etype = node["entity_type"]
        if etype in ("DOCUMENT", "CHEMICAL_STRUCTURE"):
            continue
        tables.setdefault(etype, []).append(node)
    for etype in tables:
        tables[etype].sort(key=lambda n: n.get("confidence", 0), reverse=True)
    return tables


def _top_relations(links: list[dict], n: int = 30) -> list[dict]:
    rel = [r for r in links if r["relation_type"] != "MENTIONED_IN"]
    return sorted(rel, key=lambda r: r.get("confidence", 0), reverse=True)[:n]


def _community_groups(nodes: list[dict]) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {}
    for node in nodes:
        if node["entity_type"] in ("DOCUMENT", "CHEMICAL_STRUCTURE"):
            continue
        label = node.get("community") or "Ungrouped"
        groups.setdefault(label, []).append(node["name"])
    return groups


def _source_docs(nodes: list[dict]) -> list[str]:
    return sorted({n["name"] for n in nodes if n["entity_type"] == "DOCUMENT"})


def _css() -> str:
    return (
        "body{font-family:system-ui,-apple-system,sans-serif;margin:0;padding:0;"
        "background:#f8f9fa;color:#1a1a2e}"
        ".container{max-width:1100px;margin:0 auto;padding:2rem}"
        "header{background:#1a1a2e;color:#fff;padding:2rem;border-radius:12px;margin-bottom:2rem}"
        "header h1{margin:0 0 0.5rem;font-size:1.6rem}"
        "header p{margin:0;opacity:0.75;font-size:0.9rem}"
        ".meta-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));"
        "gap:1rem;margin-top:1.5rem}"
        ".meta-card{background:rgba(255,255,255,0.12);border-radius:8px;padding:1rem;text-align:center}"
        ".meta-card .num{font-size:2rem;font-weight:700}"
        ".meta-card .lbl{font-size:0.75rem;opacity:0.8;text-transform:uppercase;letter-spacing:0.05em}"
        "section{background:#fff;border-radius:12px;padding:1.5rem;margin-bottom:1.5rem;"
        "box-shadow:0 1px 4px rgba(0,0,0,0.06)}"
        "section h2{margin:0 0 1rem;font-size:1.1rem;color:#1a1a2e;"
        "border-bottom:2px solid #e9ecef;padding-bottom:0.5rem}"
        "table{width:100%;border-collapse:collapse;font-size:0.85rem}"
        "th{background:#f1f3f5;text-align:left;padding:0.5rem 0.75rem;font-weight:600;color:#495057}"
        "td{padding:0.45rem 0.75rem;border-bottom:1px solid #f1f3f5;vertical-align:top}"
        "tr:last-child td{border-bottom:none}"
        ".badge{display:inline-block;padding:0.15rem 0.5rem;border-radius:99px;"
        "font-size:0.7rem;font-weight:600;text-transform:uppercase;letter-spacing:0.04em}"
        ".badge-compound{background:#d0ebff;color:#1864ab}"
        ".badge-protein{background:#d3f9d8;color:#1b5e20}"
        ".badge-disease{background:#ffe8cc;color:#7d4e00}"
        ".badge-clinical_trial{background:#e5dbff;color:#5f3dc4}"
        ".badge-pathway{background:#fff3bf;color:#7c5e00}"
        ".badge-biomarker{background:#ffdce3;color:#86182e}"
        ".badge-adverse_event{background:#fce4d6;color:#7c2d12}"
        ".badge-phenotype{background:#e2e8f0;color:#334155}"
        ".badge-default{background:#e9ecef;color:#495057}"
        ".conf{font-size:0.75rem;color:#868e96}"
        "code{font-size:0.75rem;background:#f1f3f5;padding:0.1rem 0.3rem;border-radius:4px}"
        ".evidence{font-size:0.78rem;color:#495057;font-style:italic;max-width:360px}"
        ".community-chip{display:inline-block;background:#e7f5ff;color:#1971c2;"
        "padding:0.2rem 0.6rem;border-radius:6px;font-size:0.75rem;margin:0.15rem}"
        ".source-list{list-style:none;padding:0;margin:0}"
        ".source-list li{padding:0.4rem 0;border-bottom:1px solid #f1f3f5;"
        "font-size:0.85rem;font-family:monospace}"
        ".source-list li:last-child{border-bottom:none}"
        "footer{text-align:center;font-size:0.75rem;color:#adb5bd;padding:1rem 0}"
    )


_TYPED_BADGES = frozenset(
    ("compound", "protein", "disease", "clinical_trial", "pathway", "biomarker", "adverse_event", "phenotype")
)


def _badge(entity_type: str) -> str:
    key = entity_type.lower()
    css_class = f"badge-{key}" if key in _TYPED_BADGES else "badge-default"
    return f'<span class="badge {css_class}">{entity_type.replace("_", " ")}</span>'


def generate_html(output_dir: Path) -> str:
    graph = _load_graph(output_dir)
    meta = graph["metadata"]
    nodes = graph["nodes"]
    links = graph["links"]
    generated = datetime.now().strftime("%B %d, %Y at %H:%M")

    entity_tables = _entity_tables(nodes)
    top_rels = _top_relations(links)
    comm_groups = _community_groups(nodes)
    source_docs = _source_docs(nodes)

    entities_html = ""
    for etype, ents in sorted(entity_tables.items()):
        entities_html += (
            f"<h3 style='margin:1rem 0 0.5rem;font-size:0.95rem;color:#495057'>"
            f"{_badge(etype)} ({len(ents)})</h3>"
            "<table><thead><tr><th>Name</th><th>Confidence</th><th>Source</th></tr></thead><tbody>"
        )
        for e in ents:
            src = ", ".join(e.get("source_documents", [])[:2])
            entities_html += (
                f"<tr><td>{e['name']}</td>"
                f"<td class='conf'>{e.get('confidence', 0):.2f}</td>"
                f"<td class='conf'>{src}</td></tr>"
            )
        entities_html += "</tbody></table>"

    rels_html = (
        "<table><thead><tr>"
        "<th>Source</th><th>Relation</th><th>Target</th><th>Evidence</th><th>Conf.</th>"
        "</tr></thead><tbody>"
    )
    for r in top_rels:
        src_name = r["source"].split(":", 1)[-1].replace("_", " ")
        tgt_name = r["target"].split(":", 1)[-1].replace("_", " ")
        rel_type = r["relation_type"].replace("_", " ")
        evidence = r.get("evidence") or ""
        truncated = evidence[:120] + ("…" if len(evidence) > 120 else "")
        rels_html += (
            f"<tr><td><b>{src_name}</b></td>"
            f"<td><code>{rel_type}</code></td>"
            f"<td><b>{tgt_name}</b></td>"
            f"<td class='evidence'>{truncated}</td>"
            f"<td class='conf'>{r.get('confidence', 0):.2f}</td></tr>"
        )
    rels_html += "</tbody></table>"

    comm_html = ""
    for label, members in sorted(comm_groups.items()):
        chips = "".join(f'<span class="community-chip">{m}</span>' for m in members[:12])
        overflow = f"<span class='conf'> +{len(members) - 12} more</span>" if len(members) > 12 else ""
        comm_html += (
            f"<div style='margin-bottom:1rem'>"
            f"<strong style='font-size:0.9rem'>{label}</strong>"
            f"<div style='margin-top:0.4rem'>{chips}{overflow}</div></div>"
        )

    docs_html = (
        "<ul class='source-list'>"
        + "".join(f"<li>{d}</li>" for d in source_docs)
        + "</ul>"
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Epistract Knowledge Graph Report</title>
<style>{_css()}</style>
</head>
<body>
<div class="container">
<header>
  <h1>Epistract Knowledge Graph Report</h1>
  <p>Generated {generated} &bull; {output_dir.resolve().name}</p>
  <div class="meta-grid">
    <div class="meta-card"><div class="num">{meta.get("entity_count", 0)}</div><div class="lbl">Entities</div></div>
    <div class="meta-card"><div class="num">{meta.get("relation_count", 0)}</div><div class="lbl">Relations</div></div>
    <div class="meta-card"><div class="num">{meta.get("document_count", 0)}</div><div class="lbl">Documents</div></div>
    <div class="meta-card"><div class="num">{len(comm_groups)}</div><div class="lbl">Communities</div></div>
  </div>
</header>

<section>
  <h2>Entities by Type</h2>
  {entities_html}
</section>

<section>
  <h2>Key Relations (top {len(top_rels)} by confidence)</h2>
  {rels_html}
</section>

<section>
  <h2>Knowledge Communities</h2>
  {comm_html}
</section>

<section>
  <h2>Source Documents ({len(source_docs)})</h2>
  {docs_html}
</section>

<footer>Generated by epistract &bull; sift-kg {meta.get("sift_kg_version", "")}</footer>
</div>
</body>
</html>"""


def generate_markdown(output_dir: Path) -> str:
    graph = _load_graph(output_dir)
    meta = graph["metadata"]
    nodes = graph["nodes"]
    links = graph["links"]
    generated = datetime.now().strftime("%Y-%m-%d %H:%M")

    entity_tables = _entity_tables(nodes)
    top_rels = _top_relations(links, n=20)
    comm_groups = _community_groups(nodes)
    source_docs = _source_docs(nodes)

    lines = [
        "# Epistract Knowledge Graph Report",
        "",
        f"Generated: {generated}  ",
        f"Source: `{output_dir.resolve().name}`",
        "",
        "## Summary",
        "",
        "| Metric | Count |",
        "|--------|-------|",
        f"| Entities | {meta.get('entity_count', 0)} |",
        f"| Relations | {meta.get('relation_count', 0)} |",
        f"| Documents | {meta.get('document_count', 0)} |",
        f"| Communities | {len(comm_groups)} |",
        "",
    ]

    lines += ["## Entities by Type", ""]
    for etype, ents in sorted(entity_tables.items()):
        lines.append(f"### {etype.replace('_', ' ').title()} ({len(ents)})")
        lines.append("")
        lines.append("| Name | Confidence | Source |")
        lines.append("|------|-----------|--------|")
        for e in ents:
            src = ", ".join(e.get("source_documents", [])[:2])
            lines.append(f"| {e['name']} | {e.get('confidence', 0):.2f} | {src} |")
        lines.append("")

    lines += ["## Key Relations", ""]
    lines.append("| Source | Relation | Target | Evidence | Conf. |")
    lines.append("|--------|----------|--------|----------|-------|")
    for r in top_rels:
        src = r["source"].split(":", 1)[-1].replace("_", " ")
        tgt = r["target"].split(":", 1)[-1].replace("_", " ")
        rel = r["relation_type"]
        evidence = r.get("evidence") or ""
        ev = evidence[:80].replace("|", "/") + ("…" if len(evidence) > 80 else "")
        lines.append(f"| {src} | {rel} | {tgt} | {ev} | {r.get('confidence', 0):.2f} |")
    lines.append("")

    lines += ["## Knowledge Communities", ""]
    for label, members in sorted(comm_groups.items()):
        preview = ", ".join(members[:8])
        if len(members) > 8:
            preview += f" (+{len(members) - 8} more)"
        lines.append(f"**{label}** — {preview}")
        lines.append("")

    lines += ["## Source Documents", ""]
    for doc in source_docs:
        lines.append(f"- `{doc}`")

    return "\n".join(lines)


def generate_share(output_dir: Path, fmt: str = "html") -> Path:
    share_dir = output_dir / "share"
    share_dir.mkdir(exist_ok=True)

    if fmt == "markdown":
        content = generate_markdown(output_dir)
        out_path = share_dir / "report.md"
    else:
        content = generate_html(output_dir)
        out_path = share_dir / "report.html"

    out_path.write_text(content, encoding="utf-8")
    return out_path


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python generate_share.py <output_dir> [html|markdown]")
        sys.exit(1)
    out_dir = Path(sys.argv[1])
    fmt = sys.argv[2] if len(sys.argv) > 2 else "html"
    path = generate_share(out_dir, fmt)
    print(json.dumps({"path": str(path), "format": fmt, "size_bytes": path.stat().st_size}))
