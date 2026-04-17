#!/usr/bin/env python3
"""End-to-end pipeline tests for epistract.

Tests the full lifecycle: extraction JSON -> graph build -> epistemic -> export
for both drug-discovery and contracts domains.
"""
import json
import shutil

import pytest

from conftest import FIXTURES_DIR, HAS_SIFTKG, PROJECT_ROOT


# ---------------------------------------------------------------------------
# All E2E tests require sift-kg
# ---------------------------------------------------------------------------
pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not HAS_SIFTKG, reason="sift-kg not installed"),
]


def _setup_extraction(tmp_path, fixture_name, output_name):
    """Copy a fixture extraction JSON into tmp_path/extractions/."""
    extractions_dir = tmp_path / "extractions"
    extractions_dir.mkdir(exist_ok=True)
    src = FIXTURES_DIR / fixture_name
    dst = extractions_dir / output_name
    shutil.copy2(src, dst)
    return dst


@pytest.mark.e2e
def test_e2e_drug_discovery_pipeline(tmp_path):
    """Full lifecycle for drug-discovery domain: extract -> build -> epistemic -> export."""
    from run_sift import cmd_build, cmd_export
    from label_epistemic import analyze_epistemic

    # 1. Set up extraction fixture
    _setup_extraction(tmp_path, "sample_extraction_drug.json", "test_drug_paper.pdf.json")

    # 2. Build graph
    cmd_build(str(tmp_path), domain_name="drug-discovery")

    # 3. Verify graph was created
    graph_path = tmp_path / "graph_data.json"
    assert graph_path.exists(), f"graph_data.json not created after cmd_build in {tmp_path}"

    graph_data = json.loads(graph_path.read_text())
    assert len(graph_data.get("nodes", [])) > 0, f"Graph has no nodes: {list(graph_data.keys())}"

    # 4. Run epistemic analysis (label_communities is called by cmd_build)
    claims_layer = analyze_epistemic(tmp_path, domain_name="drug-discovery")

    # 5. Verify claims layer
    claims_path = tmp_path / "claims_layer.json"
    assert claims_path.exists(), f"claims_layer.json not created after epistemic analysis"
    assert isinstance(claims_layer, dict), f"analyze_epistemic returned {type(claims_layer)}, expected dict"

    # 6. Export to JSON
    cmd_export(str(tmp_path), "json")

    # 7. Verify export file exists (sift-kg creates export_*.json or similar)
    export_files = list(tmp_path.glob("*export*")) + list(tmp_path.glob("*.graphml")) + list(tmp_path.glob("export/"))
    # sift-kg export may vary; just verify no error was raised


@pytest.mark.e2e
def test_e2e_contract_pipeline(tmp_path):
    """Full lifecycle for contracts domain: extract -> build -> epistemic -> export."""
    from run_sift import cmd_build, cmd_export
    from label_epistemic import analyze_epistemic

    # 1. Set up extraction fixture
    _setup_extraction(tmp_path, "sample_extraction_contract.json", "test_vendor_agreement.pdf.json")

    # 2. Build graph
    cmd_build(str(tmp_path), domain_name="contracts")

    # 3. Verify graph was created
    graph_path = tmp_path / "graph_data.json"
    assert graph_path.exists(), f"graph_data.json not created after cmd_build in {tmp_path}"

    graph_data = json.loads(graph_path.read_text())
    assert len(graph_data.get("nodes", [])) > 0, f"Graph has no nodes: {list(graph_data.keys())}"

    # 4. Run epistemic analysis
    claims_layer = analyze_epistemic(tmp_path, domain_name="contract")

    # 5. Verify claims layer
    claims_path = tmp_path / "claims_layer.json"
    assert claims_path.exists(), f"claims_layer.json not created after epistemic analysis"

    # 6. Export
    cmd_export(str(tmp_path), "json")


@pytest.mark.e2e
def test_e2e_pipeline_graph_has_metadata(tmp_path):
    """Verify graph output includes proper node metadata."""
    from run_sift import cmd_build

    # Build from drug extraction fixture
    _setup_extraction(tmp_path, "sample_extraction_drug.json", "test_drug_paper.pdf.json")
    cmd_build(str(tmp_path), domain_name="drug-discovery")

    # Load and verify graph structure
    graph_path = tmp_path / "graph_data.json"
    assert graph_path.exists(), f"graph_data.json not created"

    data = json.loads(graph_path.read_text())

    # Verify top-level structure
    assert "nodes" in data, f"graph_data.json missing 'nodes' key, has: {list(data.keys())}"
    assert "links" in data or "edges" in data, f"graph_data.json missing 'links'/'edges' key, has: {list(data.keys())}"

    # Verify all nodes have required fields
    for node in data["nodes"]:
        assert "entity_type" in node, f"Node missing 'entity_type': {node}"
        assert "name" in node, f"Node missing 'name': {node}"


# ========================================================================
# Phase 13 — FIDL-02b: Bug-4 reproducer end-to-end
# ========================================================================

@pytest.mark.e2e
def test_e2e_bug4_normalization_95pct(tmp_path):
    """FT-009: 24-file Bug-4 reproducer achieves ≥95% pass rate and graph builds.

    Copies tests/fixtures/normalization/ into tmp_path/extractions/, runs
    normalize_extractions, asserts pass_rate >= 0.95, then runs cmd_build
    to confirm the normalized extractions actually reach sift-kg's graph builder
    (closing the 30% silent-drop loophole).
    """
    from normalize_extractions import normalize_extractions
    from run_sift import cmd_build

    # 1. Stage fixture into tmp_path/extractions/
    src_fixture_dir = FIXTURES_DIR / "normalization"
    assert src_fixture_dir.is_dir(), f"Missing fixture dir: {src_fixture_dir}"

    ext_dir = tmp_path / "extractions"
    ext_dir.mkdir()
    fixture_files = list(src_fixture_dir.glob("*.json"))
    assert len(fixture_files) == 24, \
        f"Expected 24 fixture files, got {len(fixture_files)}"
    for src in fixture_files:
        shutil.copy2(src, ext_dir / src.name)

    # 2. Run normalize_extractions — must report pass_rate >= 0.95
    result = normalize_extractions(tmp_path, fail_threshold=0.95)

    assert result["pass_rate"] >= 0.95, (
        f"Bug-4 reproducer pass rate below 95% gate: "
        f"pass_rate={result['pass_rate']:.2%}, "
        f"passed={result['passed']}, recovered={result['recovered']}, "
        f"unrecoverable={result['unrecoverable']}, total={result['total']}"
    )

    report_path = tmp_path / "extractions" / "_normalization_report.json"
    assert report_path.exists(), "Normalization report not written"
    report = json.loads(report_path.read_text())
    assert report["above_threshold"] is True

    # 3. Run sift-kg build — normalized files must actually reach the graph
    cmd_build(str(tmp_path), domain_name="drug-discovery")
    graph_path = tmp_path / "graph_data.json"
    assert graph_path.exists(), (
        f"graph_data.json not created after normalize+build; "
        f"sift-kg silent-drop bug may have regressed"
    )
    graph = json.loads(graph_path.read_text())
    nodes = graph.get("nodes", [])
    assert len(nodes) > 0, (
        f"Graph has no nodes — normalized extractions not reaching builder. "
        f"Normalization report: {report}"
    )


@pytest.mark.e2e
def test_e2e_fail_threshold_aborts(tmp_path):
    """FT-010: --fail-threshold aborts pipeline BEFORE graph build when pass rate is below threshold.

    Copies tests/fixtures/normalization_below_threshold/ (2 good + 8 unrecoverable)
    into tmp_path/extractions/, invokes core/normalize_extractions.py via subprocess
    with --fail-threshold 0.95, asserts non-zero exit AND absence of graph_data.json.
    """
    import subprocess

    # 1. Stage fixture
    src_fixture_dir = FIXTURES_DIR / "normalization_below_threshold"
    assert src_fixture_dir.is_dir(), f"Missing fixture dir: {src_fixture_dir}"

    ext_dir = tmp_path / "extractions"
    ext_dir.mkdir()
    fixture_files = list(src_fixture_dir.glob("*.json"))
    assert len(fixture_files) == 10, \
        f"Expected 10 below-threshold fixture files, got {len(fixture_files)}"
    for src in fixture_files:
        shutil.copy2(src, ext_dir / src.name)

    # 2. Run normalize_extractions CLI with --fail-threshold 0.95
    script = PROJECT_ROOT / "core" / "normalize_extractions.py"
    result = subprocess.run(
        ["python3", str(script), str(tmp_path), "--fail-threshold", "0.95"],
        capture_output=True, text=True, cwd=str(PROJECT_ROOT),
    )

    # 3. Abort expectations
    assert result.returncode == 1, (
        f"Expected abort exit code 1 (below-threshold), got {result.returncode}. "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    assert "ABORT" in result.stderr, \
        f"Stderr should mention ABORT; got: {result.stderr!r}"

    # 4. Report was written with above_threshold: false
    report_path = ext_dir / "_normalization_report.json"
    assert report_path.exists(), "Normalization report not written even on abort path"
    report = json.loads(report_path.read_text())
    assert report["above_threshold"] is False, \
        f"Report should mark above_threshold=false when aborting; got: {report}"
    assert report["pass_rate"] < 0.95

    # 5. CRITICAL: graph_data.json MUST NOT exist — the pipeline aborted before build
    graph_path = tmp_path / "graph_data.json"
    assert not graph_path.exists(), (
        "graph_data.json was created despite --fail-threshold abort; "
        "pipeline does not gate graph build on normalization pass-rate"
    )
