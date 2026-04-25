#!/usr/bin/env python3
"""Build the sample.sqlite fixture for Phase 6 db_corpus unit tests.

All data in this fixture is entirely synthetic and fictional.
No real patients, no real PII. Row 4 is intentionally all-NULL to test
the empty-content skip path (DB-03). Row 5 contains unicode to test
header rendering (DB-02).

Usage:
    python tests/fixtures/build_sample_sqlite.py

Re-running is idempotent: any existing sample.sqlite is deleted first.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
FIXTURE_PATH = Path(__file__).resolve().parent / "sample.sqlite"

ROWS: list[tuple] = [
    (1, "Alice Patient", "Hypertension", "Takes lisinopril 10mg daily; stable on therapy."),
    (2, "Bob Patient", "Type 2 Diabetes", "HbA1c 7.2%; metformin titrated."),
    (3, "Charlie Patient", "Asthma", "Albuterol PRN; mild persistent."),
    (4, None, None, None),
    (5, "Daniël Müller", "Migraine", "Topiramate 50mg; efficacy noted in Köln cohort."),
]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    """Create (or recreate) sample.sqlite with 5 synthetic patient rows."""
    if FIXTURE_PATH.exists():
        FIXTURE_PATH.unlink()

    conn = sqlite3.connect(FIXTURE_PATH)
    conn.execute(
        "CREATE TABLE patients ("
        "id INTEGER PRIMARY KEY, "
        "name TEXT, "
        "condition TEXT, "
        "notes TEXT"
        ")"
    )
    conn.executemany(
        "INSERT INTO patients (id, name, condition, notes) VALUES (?, ?, ?, ?)",
        ROWS,
    )
    conn.commit()
    conn.close()

    print(json.dumps({"fixture": str(FIXTURE_PATH), "rows": len(ROWS)}, indent=2))


if __name__ == "__main__":
    main()
