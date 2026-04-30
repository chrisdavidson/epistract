#!/usr/bin/env python3
"""Validate SEC EDGAR Central Index Key (CIK) identifiers.

A CIK is assigned by the SEC to every filer. The canonical form is a
zero-padded 10-digit decimal string (e.g., "0001234567"). EDGAR also
accepts the un-padded integer form ("1234567"). Values must be in
[1, 9_999_999_999]; CIK 0 is reserved.

Usage:
    Single:  python validate_cik.py 0001234567
    Batch:   echo '["1234567", "0000320193", "abc"]' | python validate_cik.py --batch
"""

from __future__ import annotations

import json
import re
import sys

# Accept either un-padded (1-10 digits) or zero-padded 10-digit form.
_CIK_RE = re.compile(r"^\d{1,10}$")


def validate_cik(cik: str) -> dict:
    """Validate a single CIK string.

    Returns a dict with `valid` plus, when valid, the canonical
    zero-padded 10-digit form and the EDGAR browse URL.
    """
    if not isinstance(cik, str):
        return {"valid": False, "input": cik, "error": "CIK must be a string"}

    raw = cik.strip()
    if not raw:
        return {"valid": False, "input": cik, "error": "Empty CIK"}

    # Tolerate a "CIK" prefix (e.g. "CIK 0000320193" or "CIK#1234567")
    candidate = re.sub(r"(?i)^cik[\s#:]*", "", raw)

    if not _CIK_RE.match(candidate):
        return {
            "valid": False,
            "input": cik,
            "error": "CIK must be 1-10 decimal digits",
        }

    value = int(candidate)
    if value == 0:
        return {"valid": False, "input": cik, "error": "CIK 0 is reserved"}

    canonical = f"{value:010d}"
    return {
        "valid": True,
        "input": cik,
        "canonical": canonical,
        "value": value,
        "edgar_url": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={canonical}",
    }


def validate_batch(ciks: list[str]) -> list[dict]:
    """Validate a list of CIK strings."""
    return [validate_cik(c) for c in ciks]


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: validate_cik.py <cik> | --batch (reads JSON list on stdin)")
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

    json.dump(validate_cik(sys.argv[1]), sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
