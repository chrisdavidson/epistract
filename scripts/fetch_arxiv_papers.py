#!/usr/bin/env python3
"""Fetch arXiv CS paper abstracts into a text corpus for Phase 08 showcase.

Retrieves paper metadata and abstracts from the arXiv Atom API using only
stdlib urllib + xml.etree.ElementTree (zero extra dependencies). Each paper
is rendered as structured plaintext trimmed to MAX_CHARS bytes.

Usage:
    python scripts/fetch_arxiv_papers.py <output_dir>
    python scripts/fetch_arxiv_papers.py <output_dir> --ids 1706.03762,1810.04805
    python scripts/fetch_arxiv_papers.py <output_dir> --category cs.CL --max-results 10

Example:
    python scripts/fetch_arxiv_papers.py tests/corpora/09_arxiv_cs
"""

from __future__ import annotations

import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

ARXIV_API_URL = "http://export.arxiv.org/api/query"
MAX_CHARS = 15_000
SLEEP_BETWEEN_REQUESTS = 3.0

# Default categories for --category mode
CATEGORIES = ["cs.CL", "cs.CV", "cs.LG"]

# XML namespace map (required for ElementTree findall/findtext with namespaces)
NS = {
    "a": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
    "opensearch": "http://a9.com/-/spec/opensearch/1.1/",
}

# Showcase corpus — verified accessible 2026-04-26
# 4 cs.CL papers, 3 cs.CV papers, 1 cs.LG paper
SHOWCASE_IDS: list[tuple[str, str]] = [
    ("1706.03762", "attention_is_all_you_need"),
    ("1810.04805", "bert"),
    ("2005.14165", "gpt3"),
    ("2302.13971", "llama"),
    ("1512.03385", "resnet"),
    ("2010.11929", "vit"),
    ("2103.00020", "clip"),
    ("1412.6980", "adam"),
]

# FIELD_MAP — ordered list of (paper_dict_key, display_label) tuples
# Only fields with non-empty values are included in rendered output.
FIELD_MAP: list[tuple[str, str]] = [
    ("arxiv_id", "arXiv ID"),
    ("title", "Title"),
    ("authors", "Authors"),
    ("primary_cat", "Primary Category"),
    ("categories", "All Categories"),
    ("published", "Published"),
    ("journal_ref", "Journal/Venue"),
    ("comment", "Comment"),
]


# ---------------------------------------------------------------------------
# XML parsing
# ---------------------------------------------------------------------------


def _parse_entries(xml_text: str) -> list[dict]:
    """Parse Atom XML response into list of paper dicts.

    Each dict has keys: arxiv_id, title, authors, categories,
    primary_cat, published, updated, journal_ref, abstract,
    comment, pdf_url, abs_url.

    Args:
        xml_text: Raw UTF-8 Atom XML from arXiv API.

    Returns:
        List of paper dicts (empty list if no entries found).
    """
    root = ET.fromstring(xml_text)
    papers = []
    for entry in root.findall("a:entry", NS):
        # arXiv ID — strip URL prefix and version suffix
        raw_id = entry.findtext("a:id", "", NS)
        arxiv_id = raw_id.rsplit("/", 1)[-1].rsplit("v", 1)[0]  # "1706.03762"

        # Authors — list of names
        authors = [
            a.findtext("a:name", "", NS).strip() for a in entry.findall("a:author", NS)
        ]

        # Categories — all listed
        cats = [c.get("term", "") for c in entry.findall("a:category", NS)]

        # Primary category — may be absent; fall back to first cat
        pcat_el = entry.find("arxiv:primary_category", NS)
        primary_cat = (
            pcat_el.get("term", cats[0] if cats else "")
            if pcat_el is not None
            else (cats[0] if cats else "")
        )

        journal_ref = entry.findtext("arxiv:journal_ref", "", NS).strip()
        comment = entry.findtext("arxiv:comment", "", NS).strip()

        published_raw = entry.findtext("a:published", "", NS)
        updated_raw = entry.findtext("a:updated", "", NS)

        papers.append(
            {
                "arxiv_id": arxiv_id,
                "title": entry.findtext("a:title", "", NS).strip().replace("\n", " "),
                "abstract": entry.findtext("a:summary", "", NS).strip(),
                "authors": authors,
                "categories": cats,
                "primary_cat": primary_cat,
                "published": published_raw[:10]
                if published_raw
                else "",  # "YYYY-MM-DD"
                "updated": updated_raw[:10] if updated_raw else "",
                "journal_ref": journal_ref,
                "comment": comment,
                "abs_url": f"https://arxiv.org/abs/{arxiv_id}",
                "pdf_url": f"https://arxiv.org/pdf/{arxiv_id}",
            }
        )
    return papers


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------


def fetch_by_ids(id_list: list[str]) -> list[dict] | None:
    """Fetch multiple papers in one API call using id_list parameter.

    Preferred for showcase corpus — one request per batch, respects rate limits.

    Args:
        id_list: List of arXiv IDs (e.g., ["1706.03762", "1810.04805"]).

    Returns:
        List of parsed paper dicts, or None on HTTP/parse error.
    """
    ids_param = ",".join(id_list)
    url = f"{ARXIV_API_URL}?id_list={ids_param}&max_results={len(id_list)}"
    req = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
            "Accept": "application/atom+xml",
        },
    )
    try:
        with urlopen(req, timeout=30) as resp:  # nosec - fixed public URL
            xml_text = resp.read().decode("utf-8")
        return _parse_entries(xml_text)
    except HTTPError as e:
        print(f"ERROR: arXiv API -> HTTP {e.code}", file=sys.stderr)
        return None
    except (URLError, ValueError) as e:
        print(f"ERROR: arXiv API -> request failed: {e}", file=sys.stderr)
        return None


def fetch_by_category(category: str, max_results: int = 10) -> list[dict] | None:
    """Fetch recent papers from a CS category.

    Args:
        category: arXiv category string (e.g., "cs.CL").
        max_results: Number of papers to fetch (default 10, max 2000).

    Returns:
        List of parsed paper dicts, or None on error.
    """
    url = (
        f"{ARXIV_API_URL}?search_query=cat:{category}"
        f"&max_results={max_results}&sortBy=submittedDate&sortOrder=descending"
    )
    req = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
            "Accept": "application/atom+xml",
        },
    )
    try:
        with urlopen(req, timeout=30) as resp:  # nosec - fixed public URL
            xml_text = resp.read().decode("utf-8")
        return _parse_entries(xml_text)
    except HTTPError as e:
        print(f"ERROR: arXiv API -> HTTP {e.code}", file=sys.stderr)
        return None
    except (URLError, ValueError) as e:
        print(f"ERROR: arXiv API -> request failed: {e}", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------


def render(paper: dict, filename_stem: str) -> str:
    """Render a paper dict into human+LLM readable plaintext.

    Mirrors fetch_fda_labels.py render() — assembles FIELD_MAP headers
    and trims to MAX_CHARS with UTF-8-safe truncation.

    Args:
        paper: Dict from _parse_entries().
        filename_stem: Output filename stem (used as document title).

    Returns:
        Rendered plaintext trimmed to at most MAX_CHARS bytes (UTF-8).
    """
    parts: list[str] = [
        f"arXiv Paper: {filename_stem}",
        f"URL: {paper.get('abs_url', '')}",
        "",
    ]

    meta_fields: list[tuple[str, str]] = [
        ("arXiv ID", paper.get("arxiv_id", "")),
        ("Title", paper.get("title", "")),
        ("Authors", "; ".join(paper.get("authors", []))),
        ("Primary Category", paper.get("primary_cat", "")),
        ("All Categories", ", ".join(paper.get("categories", []))),
        ("Published", paper.get("published", "")),
        ("Journal/Venue", paper.get("journal_ref", "")),
        ("Comment", paper.get("comment", "")),
    ]
    for label, value in meta_fields:
        if value:
            parts.append(f"{label}: {value}")
    parts.append("")

    abstract = paper.get("abstract", "").strip()
    if abstract:
        parts.append("=== ABSTRACT ===")
        parts.append(abstract)
        parts.append("")

    combined = "\n".join(parts).rstrip() + "\n"
    # UTF-8-safe trim — mirrors fetch_fda_labels.py lines 213-217
    encoded = combined.encode("utf-8")
    if len(encoded) > MAX_CHARS:
        encoded = encoded[:MAX_CHARS]
        return encoded.decode("utf-8", errors="ignore")
    return combined


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    """Entry point.

    Usage:
        python scripts/fetch_arxiv_papers.py <output_dir>
            [--ids 1706.03762,1810.04805]
            [--category cs.CL]
            [--max-results 10]

    Returns:
        0 on success, 1 if any fetch failed, 2 if bad args.
    """
    if len(sys.argv) < 2:
        print(
            "Usage: python scripts/fetch_arxiv_papers.py <output_dir>",
            file=sys.stderr,
        )
        print(
            "       [--ids 1706.03762,1810.04805] [--category cs.CL] [--max-results 10]",
            file=sys.stderr,
        )
        return 2

    out_root = Path(sys.argv[1]).resolve()
    docs_dir = out_root / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)

    # Parse optional flags
    ids_arg: str | None = None
    category_arg: str | None = None
    max_results_arg: int = 10

    if "--ids" in sys.argv:
        ids_arg = sys.argv[sys.argv.index("--ids") + 1]
    if "--category" in sys.argv:
        category_arg = sys.argv[sys.argv.index("--category") + 1]
    if "--max-results" in sys.argv:
        max_results_arg = int(sys.argv[sys.argv.index("--max-results") + 1])

    fetched, failed, skipped = 0, 0, 0

    if category_arg:
        # Category mode — fetch by category, sleep between calls if multiple
        papers = fetch_by_category(category_arg, max_results=max_results_arg)
        if papers is None:
            print(f"FAIL: category {category_arg}", file=sys.stderr)
            return 1
        for paper in papers:
            arxiv_id = paper["arxiv_id"]
            stem = arxiv_id.replace(".", "_").replace("/", "_")
            slug = stem  # no slug in category mode; use stem as filename
            target = docs_dir / f"{slug}.txt"
            if target.exists():
                print(f"SKIP {slug}")
                skipped += 1
                continue
            text = render(paper, slug)
            target.write_text(text, encoding="utf-8")
            size = target.stat().st_size
            print(f"wrote {size} bytes -> {target.name}")
            fetched += 1
            time.sleep(SLEEP_BETWEEN_REQUESTS)

    elif ids_arg:
        # Explicit IDs mode — batch fetch all provided IDs
        id_list = [i.strip() for i in ids_arg.split(",") if i.strip()]
        papers = fetch_by_ids(id_list)
        if papers is None:
            print("FAIL: id_list fetch returned None", file=sys.stderr)
            return 1
        lookup = {p["arxiv_id"]: p for p in papers}
        for arxiv_id in id_list:
            stem = arxiv_id.replace(".", "_").replace("/", "_")
            target = docs_dir / f"{stem}.txt"
            if target.exists():
                print(f"SKIP {stem}")
                skipped += 1
                continue
            paper = lookup.get(arxiv_id)
            if paper is None:
                print(f"FAIL {arxiv_id} (not returned by API)")
                failed += 1
                continue
            text = render(paper, stem)
            target.write_text(text, encoding="utf-8")
            size = target.stat().st_size
            print(f"wrote {size} bytes -> {target.name}")
            fetched += 1

    else:
        # Default mode — batch fetch all SHOWCASE_IDS in a single API call
        id_list = [arxiv_id for arxiv_id, _slug in SHOWCASE_IDS]
        papers = fetch_by_ids(id_list)
        if papers is None:
            print("FAIL: showcase batch fetch returned None", file=sys.stderr)
            return 1
        lookup = {p["arxiv_id"]: p for p in papers}
        for arxiv_id, slug in SHOWCASE_IDS:
            stem = arxiv_id.replace(".", "_")
            target = docs_dir / f"{stem}_{slug}.txt"
            if target.exists():
                print(f"SKIP {stem}_{slug}")
                skipped += 1
                continue
            print(f"Fetching {slug} ({arxiv_id}) ...", end=" ", flush=True)
            paper = lookup.get(arxiv_id)
            if paper is None:
                print("FAIL")
                failed += 1
                continue
            text = render(paper, f"{stem}_{slug}")
            target.write_text(text, encoding="utf-8")
            size = target.stat().st_size
            print(f"wrote {size} bytes -> {target.name}")
            fetched += 1

    print(f"\n=== Done: {fetched} fetched, {skipped} skipped, {failed} failed ===")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
