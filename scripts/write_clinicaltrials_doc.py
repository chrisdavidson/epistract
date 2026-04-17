#!/usr/bin/env python3
"""Write ClinicalTrials.gov trial metadata to the epistract corpus text format.

Produces plain-text files matching the format used by existing test corpora,
so that /epistract-ingest can process them without modification.

Usage:
    echo '<json>' | python write_clinicaltrials_doc.py <output_dir>
    python write_clinicaltrials_doc.py <output_dir> --json '<json>'

Input JSON schema:
    {
        "trials": [
            {
                "nct_id": "NCT12345678",
                "brief_title": "...",
                "official_title": "...",          // optional
                "brief_summary": "...",
                "detailed_description": "...",    // optional
                "conditions": ["Disease A"],
                "keywords": ["keyword1"],         // optional
                "phase": ["PHASE2"],              // optional
                "status": "COMPLETED",
                "start_date": "2020-01",          // optional
                "primary_completion_date": "2022-06",  // optional
                "lead_sponsor": "Sponsor Name",   // optional
                "interventions": [                // optional
                    {"name": "...", "type": "DRUG", "description": "..."}
                ],
                "primary_outcomes": [             // optional
                    {"measure": "...", "description": "..."}
                ],
                "eligibility_criteria": "...",    // optional
                "minimum_age": "18 Years",        // optional
                "maximum_age": "N/A"              // optional
            }
        ]
    }

Output:
    <output_dir>/docs/nct_<NCT_ID>.txt  (one per trial)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def _format_phases(phases: list[str]) -> str:
    """Convert phase codes to readable labels (e.g. PHASE2 -> Phase 2)."""
    label_map = {
        "EARLY_PHASE1": "Early Phase 1",
        "PHASE1": "Phase 1",
        "PHASE2": "Phase 2",
        "PHASE3": "Phase 3",
        "PHASE4": "Phase 4",
        "NA": "N/A",
    }
    return ", ".join(label_map.get(p, p) for p in phases)


def write_trial(trial: dict, docs_dir: Path) -> str | None:
    """Write a single trial to the corpus directory.

    Returns the filename written, or None if skipped.
    """
    nct_id = trial.get("nct_id", "").strip()
    if not nct_id:
        return None

    brief_summary = (trial.get("brief_summary") or "").strip()
    detailed_description = (trial.get("detailed_description") or "").strip()

    # Skip trials with no usable text
    if not brief_summary and not detailed_description:
        return None

    brief_title = (trial.get("brief_title") or "").strip()
    official_title = (trial.get("official_title") or "").strip()
    title = official_title or brief_title

    conditions = trial.get("conditions") or []
    keywords = trial.get("keywords") or []
    phases = trial.get("phase") or []
    status = (trial.get("status") or "").strip()
    start_date = (trial.get("start_date") or "").strip()
    primary_completion_date = (trial.get("primary_completion_date") or "").strip()
    lead_sponsor = (trial.get("lead_sponsor") or "").strip()
    interventions = trial.get("interventions") or []
    primary_outcomes = trial.get("primary_outcomes") or []
    eligibility_criteria = (trial.get("eligibility_criteria") or "").strip()
    minimum_age = (trial.get("minimum_age") or "").strip()
    maximum_age = (trial.get("maximum_age") or "").strip()

    # Build metadata header
    lines = [
        f"Title: {title}",
    ]
    if lead_sponsor:
        lines.append(f"Sponsor: {lead_sponsor}")

    status_line = status
    if phases:
        status_line = f"{status} ({_format_phases(phases)})"
    if status_line:
        lines.append(f"Status: {status_line}")

    lines.append(f"NCT: {nct_id}")

    if start_date or primary_completion_date:
        date_range = " – ".join(filter(None, [start_date, primary_completion_date]))
        lines.append(f"Dates: {date_range}")

    if conditions:
        lines.append(f"Conditions: {', '.join(conditions)}")

    if interventions:
        intervention_names = [
            f"{i['name']} ({i['type']})" if i.get("type") else i["name"]
            for i in interventions
            if i.get("name")
        ]
        if intervention_names:
            lines.append(f"Interventions: {', '.join(intervention_names)}")

    if minimum_age or maximum_age:
        age_range = " – ".join(filter(None, [minimum_age, maximum_age]))
        lines.append(f"Age Range: {age_range}")

    if keywords:
        lines.append(f"Keywords: {', '.join(keywords)}")

    lines.append("Source: ClinicalTrials.gov API v2")

    # Body sections
    if brief_summary:
        lines.append("")
        lines.append("BRIEF SUMMARY:")
        lines.append(brief_summary)

    if detailed_description:
        lines.append("")
        lines.append("DETAILED DESCRIPTION:")
        lines.append(detailed_description)

    if primary_outcomes:
        lines.append("")
        lines.append("PRIMARY OUTCOMES:")
        for outcome in primary_outcomes:
            measure = outcome.get("measure", "").strip()
            description = outcome.get("description", "").strip()
            if measure:
                lines.append(f"- {measure}")
                if description:
                    lines.append(f"  {description}")

    if eligibility_criteria:
        lines.append("")
        lines.append("ELIGIBILITY CRITERIA:")
        lines.append(eligibility_criteria)

    if interventions:
        detailed_interventions = [
            i for i in interventions if i.get("description")
        ]
        if detailed_interventions:
            lines.append("")
            lines.append("INTERVENTION DETAILS:")
            for i in detailed_interventions:
                name = i.get("name", "")
                itype = i.get("type", "")
                desc = i.get("description", "")
                header = f"{name} ({itype})" if itype else name
                lines.append(f"- {header}: {desc}")

    fname = f"nct_{nct_id}.txt"
    out_path = docs_dir / fname
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return fname


def main() -> None:
    args = sys.argv[1:]

    if not args:
        print(
            f"Usage: {sys.argv[0]} <output_dir> [--json '<json>']",
            file=sys.stderr,
        )
        sys.exit(1)

    output_dir = Path(args[0])
    docs_dir = output_dir / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)

    # Read input JSON
    if "--json" in args:
        data = json.loads(args[args.index("--json") + 1])
    else:
        data = json.load(sys.stdin)

    trials = data.get("trials", [])
    if not trials:
        print("No trials in input", file=sys.stderr)
        sys.exit(1)

    # Check for existing NCT IDs to avoid duplicates
    existing_nct_ids: set[str] = set()
    for f in docs_dir.glob("nct_*.txt"):
        existing_nct_ids.add(f.stem.removeprefix("nct_"))

    written = []
    skipped_dup = 0
    skipped_empty = 0

    for trial in trials:
        nct_id = trial.get("nct_id", "").strip()
        if nct_id in existing_nct_ids:
            skipped_dup += 1
            continue

        fname = write_trial(trial, docs_dir)
        if fname:
            written.append(fname)
            existing_nct_ids.add(nct_id)
        else:
            skipped_empty += 1

    print(json.dumps({
        "docs_dir": str(docs_dir),
        "written": len(written),
        "skipped_duplicate": skipped_dup,
        "skipped_empty": skipped_empty,
        "files": written,
    }, indent=2))


if __name__ == "__main__":
    main()
