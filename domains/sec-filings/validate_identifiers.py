#!/usr/bin/env python3
"""Orchestrate identifier validation across SEC-filings extraction JSONs.

Scans every ``<output_dir>/extractions/*.json`` for CIK and ticker
mentions (in entity names, contexts, and relation evidence), validates
each via the per-identifier validators, and writes a summary to
``<output_dir>/validation/sec_filings_validation.json``.

Usage:
    python validate_identifiers.py <output_dir>
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

VALIDATION_DIR = Path(__file__).parent / "validation"
sys.path.insert(0, str(VALIDATION_DIR))

from validate_cik import validate_cik  # noqa: E402
from validate_ticker import validate_ticker  # noqa: E402

# CIK appears as "CIK 0001234567", "CIK#1234567", or near a "CIK" marker.
# Bare numeric runs without a CIK marker are too noisy to scan.
_CIK_PATTERN = re.compile(r"\bCIK[\s#:]*([0-9]{1,10})\b", re.IGNORECASE)

# Ticker patterns:
#   - "(NASDAQ:ACME)", "(NYSE: BRK.A)", "(AMEX:BF-B)"
#   - "ticker symbol 'ACME'" or "ticker: ACME"
#   - "$ACME" cashtag form
_TICKER_PATTERNS = [
    re.compile(
        r"\((?:NYSE|NASDAQ|NASDAQGS|NASDAQGM|AMEX|OTC|OTCBB|ARCA|BATS|CBOE)\s*[:\.]\s*"
        r"([A-Z]{1,5}(?:[.\-][A-Z])?)\)"
    ),
    re.compile(
        r"(?i)\bticker(?:\s+symbol)?[\s:]+['\"]?([A-Z]{1,5}(?:[.\-][A-Z])?)['\"]?\b"
    ),
    re.compile(r"\$([A-Z]{1,5}(?:[.\-][A-Z])?)\b"),
]


def collect_texts(extraction: dict) -> list[str]:
    """Collect text strings from entity names/contexts and relation evidence."""
    texts: list[str] = []
    for entity in extraction.get("entities", []):
        name = entity.get("name", "")
        if name:
            texts.append(name)
        ctx = entity.get("context", "")
        if ctx:
            texts.append(ctx)
    for relation in extraction.get("relations", []):
        evidence = relation.get("evidence", "")
        if evidence:
            texts.append(evidence)
    return texts


def scan_text_for_identifiers(text: str) -> tuple[set[str], set[str]]:
    """Return (cik_candidates, ticker_candidates) found in `text`."""
    ciks = {m.group(1) for m in _CIK_PATTERN.finditer(text)}
    tickers: set[str] = set()
    for pat in _TICKER_PATTERNS:
        tickers.update(m.group(1) for m in pat.finditer(text))
    return ciks, tickers


def validate_extraction(extraction: dict) -> dict:
    """Validate all CIK and ticker mentions in a single extraction."""
    all_ciks: set[str] = set()
    all_tickers: set[str] = set()
    for text in collect_texts(extraction):
        ciks, tickers = scan_text_for_identifiers(text)
        all_ciks |= ciks
        all_tickers |= tickers

    cik_results = [validate_cik(c) for c in sorted(all_ciks)]
    ticker_results = [validate_ticker(t) for t in sorted(all_tickers)]

    return {
        "document_id": extraction.get("document_id", "<unknown>"),
        "ciks": cik_results,
        "tickers": ticker_results,
    }


def run(output_dir: Path) -> dict:
    """Run validation across every extraction JSON in `output_dir/extractions/`."""
    extractions_dir = output_dir / "extractions"
    if not extractions_dir.is_dir():
        raise FileNotFoundError(f"No extractions directory at {extractions_dir}")

    results: list[dict] = []
    total_ciks = total_valid_ciks = 0
    total_tickers = total_valid_tickers = 0

    for path in sorted(extractions_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text())
        except json.JSONDecodeError as e:
            print(f"  skip {path.name}: invalid JSON ({e})", file=sys.stderr)
            continue
        result = validate_extraction(data)
        results.append(result)
        total_ciks += len(result["ciks"])
        total_valid_ciks += sum(1 for r in result["ciks"] if r.get("valid"))
        total_tickers += len(result["tickers"])
        total_valid_tickers += sum(1 for r in result["tickers"] if r.get("valid"))

    summary = {
        "validated_at": datetime.now(timezone.utc).isoformat(),
        "domain": "sec-filings",
        "totals": {
            "ciks": total_ciks,
            "valid_ciks": total_valid_ciks,
            "tickers": total_tickers,
            "valid_tickers": total_valid_tickers,
        },
        "results": results,
    }

    out_dir = output_dir / "validation"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "sec_filings_validation.json"
    out_path.write_text(json.dumps(summary, indent=2) + "\n")

    print(
        f"sec-filings validation: {total_valid_ciks}/{total_ciks} CIKs, "
        f"{total_valid_tickers}/{total_tickers} tickers — written to {out_path}"
    )
    return summary


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: validate_identifiers.py <output_dir>", file=sys.stderr)
        return 1
    run(Path(sys.argv[1]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
