#!/usr/bin/env python3
"""Validate stock ticker symbols as they appear in SEC filings.

A ticker is 1-5 uppercase letters, optionally followed by a class suffix:
either ``.X`` (e.g. ``BRK.A``) or ``-X`` (e.g. ``BF-B``). Tickers may be
prefixed with an exchange (``NYSE:``, ``NASDAQ:``, ``AMEX:``, ``OTC:``).
Single-letter listings ("F", "T", "C") are accepted; pure-numeric symbols
are rejected.

Usage:
    Single:  python validate_ticker.py BRK.A
    Batch:   echo '["ACME", "BRK.A", "BF-B", "NASDAQ:GOOG", "123"]' | python validate_ticker.py --batch
"""

from __future__ import annotations

import json
import re
import sys

_TICKER_RE = re.compile(
    r"""
    ^
    (?:(?P<exchange>NYSE|NASDAQ|NASDAQGS|NASDAQGM|AMEX|OTC|OTCBB|ARCA|BATS|CBOE)[:\.])?
    (?P<root>[A-Z]{1,5})
    (?:(?P<sep>[.\-])(?P<class>[A-Z]))?
    $
    """,
    re.VERBOSE,
)

_KNOWN_EXCHANGES = {
    "NYSE", "NASDAQ", "NASDAQGS", "NASDAQGM", "AMEX",
    "OTC", "OTCBB", "ARCA", "BATS", "CBOE",
}


def validate_ticker(ticker: str) -> dict:
    """Validate a single ticker string.

    Returns a dict with `valid` plus, when valid, the canonical form
    (uppercase, no exchange prefix, ``.`` as the class separator) and
    any detected exchange prefix.
    """
    if not isinstance(ticker, str):
        return {"valid": False, "input": ticker, "error": "Ticker must be a string"}

    raw = ticker.strip().upper()
    if not raw:
        return {"valid": False, "input": ticker, "error": "Empty ticker"}

    m = _TICKER_RE.match(raw)
    if not m:
        return {
            "valid": False,
            "input": ticker,
            "error": "Ticker must be 1-5 uppercase letters with optional .X or -X class suffix",
        }

    root = m.group("root")
    exchange = m.group("exchange")
    cls = m.group("class")

    canonical = f"{root}.{cls}" if cls else root

    return {
        "valid": True,
        "input": ticker,
        "canonical": canonical,
        "root": root,
        "share_class": cls,
        "exchange": exchange if exchange in _KNOWN_EXCHANGES else None,
    }


def validate_batch(tickers: list[str]) -> list[dict]:
    """Validate a list of ticker strings."""
    return [validate_ticker(t) for t in tickers]


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: validate_ticker.py <ticker> | --batch (reads JSON list on stdin)")
        return 1

    if sys.argv[1] == "--batch":
        try:
            payload = json.load(sys.stdin)
        except json.JSONDecodeError as e:
            print(json.dumps({"error": f"Invalid JSON on stdin: {e}"}))
            return 1
        if not isinstance(payload, list):
            print(json.dumps({"error": "Batch input must be a JSON array of strings"}))
            return 1
        json.dump(validate_batch(payload), sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    json.dump(validate_ticker(sys.argv[1]), sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
