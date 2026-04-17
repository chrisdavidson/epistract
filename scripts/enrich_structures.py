#!/usr/bin/env python3
"""Enrich clinical trial corpus documents with chemical structure data from PubChem.

For each nct_*.txt file in the corpus docs directory, extracts drug intervention
names, queries PubChem for structural properties (SMILES, InChIKey, MW, formula),
and appends a CHEMICAL STRUCTURES section to the document.

Run this between /epistract-acquire-trials and /epistract-ingest so that the
existing RDKit validation step finds real SMILES strings instead of false positives.

Usage:
    python enrich_structures.py <output_dir>
    python enrich_structures.py <output_dir> --dry-run
"""

from __future__ import annotations

import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


# Names that are not real drug entities — skip PubChem lookup
_SKIP_NAMES: frozenset[str] = frozenset({
    "placebo",
    "saline",
    "vehicle",
    "control",
    "observation",
    "observational",
    "standard of care",
    "usual care",
    "best supportive care",
    "lifestyle intervention",
    "dietary intervention",
    "exercise",
    "diet",
    "matching placebo",
    "oral placebo",
    "injectable placebo",
})

# Drug class terms that PubChem won't resolve to a single structure
_CLASS_TERMS: frozenset[str] = frozenset({
    "glp-1 receptor agonists",
    "sglt2 inhibitors",
    "dpp-4 inhibitors",
    "sulfonylureas",
    "insulin",
    "beta blockers",
    "ace inhibitors",
    "statins",
})

_MIN_NAME_LEN = 4

# PubChem polite rate limit (3 requests/sec max per their guidelines)
_PUBCHEM_DELAY = 0.34


def _clean_name(raw: str) -> str:
    """Strip type tags and parenthetical brand names from an intervention name.

    Examples:
        'semaglutide (Ozempic) (DRUG)' -> 'semaglutide'
        'tirzepatide (Zepbound) (DRUG)'  -> 'tirzepatide'
        'GLP-1 receptor agonists (DRUG)' -> 'GLP-1 receptor agonists'
        'oral semaglutide (DRUG)'        -> 'oral semaglutide'
    """
    # Remove trailing intervention type tag — wrap alternatives in (?:...) so
    # | stays scoped and the closing \) anchors to the whole group, not just
    # the last alternative.
    name = re.sub(
        r"\s*\((?:DRUG|BIOLOGICAL|DEVICE|PROCEDURE|RADIATION|DIETARY_SUPPLEMENT"
        r"|COMBINATION_PRODUCT|DIAGNOSTIC_TEST|GENETIC|OTHER)\)\s*$",
        "",
        raw.strip(),
        flags=re.IGNORECASE,
    )
    # Remove remaining parenthetical brand name annotations, e.g. (Ozempic)
    name = re.sub(r"\s*\([^)]+\)\s*", " ", name)
    # Strip any residual stray punctuation left by nested parens
    name = re.sub(r"[)]+", "", name)
    return name.strip()


def _extract_intervention_names(doc_text: str) -> list[str]:
    """Parse drug names from the 'Interventions:' metadata line."""
    names: list[str] = []
    for line in doc_text.splitlines():
        if line.startswith("Interventions:"):
            raw = line.removeprefix("Interventions:").strip()
            for part in raw.split(","):
                name = _clean_name(part.strip())
                if name:
                    names.append(name)
    return names


_ROUTE_PREFIXES: tuple[str, ...] = (
    "oral ", "subcutaneous ", "injectable ", "intravenous ", "topical ",
    "inhaled ", "intramuscular ", "transdermal ", "extended-release ",
)


def _is_skippable(name: str) -> bool:
    """Return True if this name should not be sent to PubChem."""
    if len(name) < _MIN_NAME_LEN:
        return True
    lower = name.lower()
    return lower in _SKIP_NAMES or lower in _CLASS_TERMS


def _strip_route_prefix(name: str) -> str | None:
    """Return name with leading route/formulation prefix stripped, or None."""
    lower = name.lower()
    for prefix in _ROUTE_PREFIXES:
        if lower.startswith(prefix):
            return name[len(prefix):].strip()
    return None


def _query_pubchem(name: str) -> dict | None:
    """Look up a compound by name in PubChem. Returns property dict or None."""
    encoded = urllib.parse.quote(name)
    url = (
        f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{encoded}"
        "/property/IsomericSMILES,MolecularFormula,MolecularWeight,InChIKey/JSON"
    )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "epistract/1.1"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        props = data.get("PropertyTable", {}).get("Properties", [])
        if not props:
            return None
        # Use the first (most canonical) result.
        # PubChem returns the key as "SMILES" regardless of which
        # SMILES variant was requested in the URL.
        p = props[0]
        return {
            "cid": p.get("CID"),
            "smiles": p.get("SMILES") or p.get("IsomericSMILES") or p.get("CanonicalSMILES"),
            "formula": p.get("MolecularFormula"),
            "molecular_weight": p.get("MolecularWeight"),
            "inchikey": p.get("InChIKey"),
            "source": "PubChem",
        }
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None  # Compound not in PubChem — expected for some names
        return None
    except Exception:
        return None


def _already_enriched(doc_text: str) -> bool:
    return "CHEMICAL STRUCTURES:" in doc_text


def _build_structure_section(resolved: dict[str, dict]) -> str:
    """Render the CHEMICAL STRUCTURES appendix block."""
    lines = ["", "CHEMICAL STRUCTURES:"]
    for name, props in resolved.items():
        lines.append(f"Compound: {name}")
        if props.get("formula"):
            lines.append(f"Formula: {props['formula']} | MW: {props['molecular_weight']} Da")
        if props.get("inchikey"):
            lines.append(f"InChIKey: {props['inchikey']}")
        if props.get("cid"):
            lines.append(f"PubChem CID: {props['cid']}")
        if props.get("smiles"):
            lines.append(f"SMILES: {props['smiles']}")
        lines.append("")
    return "\n".join(lines)


def enrich_document(doc_path: Path, dry_run: bool = False) -> dict:
    """Enrich a single trial document with PubChem structure data.

    Returns a result summary dict suitable for JSON serialisation.
    """
    text = doc_path.read_text(encoding="utf-8")

    if _already_enriched(text):
        return {"file": doc_path.name, "status": "already_enriched", "compounds": []}

    names = _extract_intervention_names(text)
    resolved: dict[str, dict] = {}
    not_found: list[str] = []
    skipped: list[str] = []

    for name in names:
        if _is_skippable(name):
            skipped.append(name)
            continue
        if name in resolved:
            continue  # Deduplicate within document

        result = _query_pubchem(name)
        time.sleep(_PUBCHEM_DELAY)

        # Fallback: strip route/formulation prefix and retry
        # e.g. "oral semaglutide" -> "semaglutide"
        if result is None:
            canonical = _strip_route_prefix(name)
            if canonical and canonical not in resolved and not _is_skippable(canonical):
                result = _query_pubchem(canonical)
                time.sleep(_PUBCHEM_DELAY)
                if result:
                    result["resolved_from"] = name  # Record the original name

        if result:
            resolved[name] = result
        else:
            not_found.append(name)

    if not resolved:
        return {
            "file": doc_path.name,
            "status": "no_structures_found",
            "compounds": [],
            "not_found": not_found,
            "skipped": skipped,
        }

    if not dry_run:
        structure_section = _build_structure_section(resolved)
        doc_path.write_text(text + structure_section, encoding="utf-8")

    return {
        "file": doc_path.name,
        "status": "enriched" if not dry_run else "dry_run",
        "compounds": [
            {
                "name": name,
                "cid": props["cid"],
                "formula": props["formula"],
                "molecular_weight": props["molecular_weight"],
                "inchikey": props["inchikey"],
            }
            for name, props in resolved.items()
        ],
        "not_found": not_found,
        "skipped": skipped,
    }


def main() -> None:
    args = sys.argv[1:]

    if not args:
        print(f"Usage: {sys.argv[0]} <output_dir> [--dry-run]", file=sys.stderr)
        sys.exit(1)

    output_dir = Path(args[0])
    dry_run = "--dry-run" in args
    docs_dir = output_dir / "docs"

    if not docs_dir.exists():
        print(f"Docs directory not found: {docs_dir}", file=sys.stderr)
        sys.exit(1)

    trial_docs = sorted(docs_dir.glob("nct_*.txt"))
    if not trial_docs:
        print("No nct_*.txt files found", file=sys.stderr)
        sys.exit(1)

    results = []
    for doc_path in trial_docs:
        result = enrich_document(doc_path, dry_run=dry_run)
        results.append(result)

    enriched = [r for r in results if r["status"] in ("enriched", "dry_run")]
    already_done = [r for r in results if r["status"] == "already_enriched"]
    no_structures = [r for r in results if r["status"] == "no_structures_found"]
    total_compounds = sum(len(r.get("compounds", [])) for r in enriched)

    print(json.dumps({
        "docs_dir": str(docs_dir),
        "dry_run": dry_run,
        "files_scanned": len(trial_docs),
        "enriched": len(enriched),
        "already_enriched": len(already_done),
        "no_structures_found": len(no_structures),
        "total_compounds_resolved": total_compounds,
        "results": results,
    }, indent=2))


if __name__ == "__main__":
    main()
