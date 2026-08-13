"""Unit suite for the crosswalk artifact builder (core/crosswalk*.py).

Fixtures under tests/fixtures/crosswalk/ set metadata.domain to the real
domain names on purpose -- resolve_domain() sends these fixtures through the
SHIPPED domains/*/crosswalk.yaml files rather than a test-local stub, so the
unit suite exercises the real extraction configs. Do not mock domain
resolution or rename the fixture domains; that removes the coverage.
"""

from __future__ import annotations

import json

import pytest

from core.crosswalk_normalize import CrosswalkConfigError, run_chain


def _crosswalk_fixture(fixtures_dir, name):
    return fixtures_dir / "crosswalk" / name


# ---------------------------------------------------------------------------
# Normalizer primitives
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_run_chain_collapse_whitespace_then_lowercase():
    assert run_chain("  DECLARE  ", [
        {"op": "collapse_whitespace"},
        {"op": "lowercase"},
    ]) == "declare"


@pytest.mark.unit
def test_run_chain_regex_extract_finds_match():
    result = run_chain(
        "Study NCT01730534 arm B",
        [{"op": "regex_extract", "pattern": r"NCT\d{8}"}],
    )
    assert result == "NCT01730534"


@pytest.mark.unit
def test_run_chain_regex_extract_no_match_yields_none():
    result = run_chain(
        "24-Week Monotherapy Trial",
        [{"op": "regex_extract", "pattern": r"NCT\d{8}"}],
    )
    assert result is None


@pytest.mark.unit
def test_run_chain_unknown_op_raises_with_op_name():
    with pytest.raises(CrosswalkConfigError) as exc_info:
        run_chain("x", [{"op": "not_a_real_op"}])
    assert "not_a_real_op" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Value-source resolution (one node, one axis)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_any_attribute_flattens_list_and_coerces_numeric():
    from core.crosswalk import source_candidates

    node = {
        "name": "SURPASS-1",
        "entity_type": "CLINICAL_STUDY",
        "attributes": {
            "arms": ["monotherapy", "placebo"],
            "n": 500,
            "nct_id": "NCT12345678",
        },
    }
    candidates = source_candidates(node, {"from": "any_attribute"})
    assert "monotherapy" in candidates
    assert "placebo" in candidates
    assert "500" in candidates
    assert "NCT12345678" in candidates


@pytest.mark.unit
def test_sources_ordered_first_non_empty_wins():
    from core.crosswalk import extract_axis_keys
    from core.crosswalk_normalize import build_chain

    chain = build_chain([{"op": "regex_extract", "pattern": r"NCT\d{8}"}, {"op": "uppercase"}])
    axis_cfg = {
        "entity_types": ["CLINICAL_STUDY"],
        "sources": [{"from": "attribute", "key": "primary"}, {"from": "name"}],
    }
    # 'primary' produces a match -- 'name' must never be consulted.
    node = {
        "name": "NCT99999999",  # would match if consulted
        "entity_type": "CLINICAL_STUDY",
        "attributes": {"primary": "NCT01730534"},
    }
    keys = extract_axis_keys(node, axis_cfg, chain)
    assert keys == {"NCT01730534"}


@pytest.mark.unit
def test_entity_type_not_in_axis_produces_no_keys():
    from core.crosswalk import extract_axis_keys
    from core.crosswalk_normalize import build_chain

    chain = build_chain([{"op": "regex_extract", "pattern": r"NCT\d{8}"}])
    axis_cfg = {"entity_types": ["CLINICAL_STUDY"], "sources": [{"from": "name"}]}
    node = {"name": "NCT01730534", "entity_type": "WARNING", "attributes": {}}
    assert extract_axis_keys(node, axis_cfg, chain) == set()


# ---------------------------------------------------------------------------
# Spine assembly over the two synthetic fixtures
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_spine_trial_axis_joins_declare_across_graphs(fixtures_dir):
    from core.crosswalk import build_spine, load_axis_spec, load_graphs, resolve_domain_configs

    labels_dir = _crosswalk_fixture(fixtures_dir, "labels")
    ct_dir = _crosswalk_fixture(fixtures_dir, "ct")
    graphs = load_graphs([str(labels_dir), str(ct_dir)])
    axis_spec = load_axis_spec("crosswalks/pharma.yaml")
    graphs = resolve_domain_configs(graphs, axis_spec)
    result = build_spine(graphs, axis_spec)

    trial_axis = result["axes"]["trial"]
    entry = trial_axis["NCT01730534"]["graphs"]
    assert entry["fda-product-labels"] == ["clinical_study:declare"]
    assert entry["clinicaltrials"] == ["trial:nct01730534"]


@pytest.mark.unit
def test_spine_single_graph_key_lists_one_graph(fixtures_dir):
    from core.crosswalk import build_spine, load_axis_spec, load_graphs, resolve_domain_configs

    labels_dir = _crosswalk_fixture(fixtures_dir, "labels")
    ct_dir = _crosswalk_fixture(fixtures_dir, "ct")
    graphs = load_graphs([str(labels_dir), str(ct_dir)])
    axis_spec = load_axis_spec("crosswalks/pharma.yaml")
    graphs = resolve_domain_configs(graphs, axis_spec)
    result = build_spine(graphs, axis_spec)

    trial_axis = result["axes"]["trial"]
    entry = trial_axis["NCT00000001"]["graphs"]
    assert list(entry.keys()) == ["clinicaltrials"]


@pytest.mark.unit
def test_spine_stats_reports_required_fields(fixtures_dir):
    from core.crosswalk import build_spine, load_axis_spec, load_graphs, resolve_domain_configs

    labels_dir = _crosswalk_fixture(fixtures_dir, "labels")
    ct_dir = _crosswalk_fixture(fixtures_dir, "ct")
    graphs = load_graphs([str(labels_dir), str(ct_dir)])
    axis_spec = load_axis_spec("crosswalks/pharma.yaml")
    graphs = resolve_domain_configs(graphs, axis_spec)
    result = build_spine(graphs, axis_spec)

    stats = result["stats"]["trial"]
    for field in (
        "keys_total",
        "keys_per_graph",
        "pairwise",
        "shared_by_2_or_more",
        "shared_by_all_graphs",
        "declared_by",
    ):
        assert field in stats, f"missing stats field: {field}"
    assert sorted(stats["declared_by"]) == ["clinicaltrials", "fda-product-labels"]
    pair_key = "clinicaltrials|fda-product-labels"
    assert stats["pairwise"][pair_key] == stats["shared_by_all_graphs"]


@pytest.mark.unit
def test_shared_by_all_graphs_scoped_to_declaring_graphs(fixtures_dir):
    """A third, loaded-but-non-declaring graph must not zero out the
    all-graph intersection for an axis it doesn't declare."""
    from core.crosswalk import build_spine, load_axis_spec, load_graphs, resolve_domain_configs

    labels_dir = _crosswalk_fixture(fixtures_dir, "labels")
    ct_dir = _crosswalk_fixture(fixtures_dir, "ct")
    other_dir = _crosswalk_fixture(fixtures_dir, "other")
    graphs = load_graphs([str(labels_dir), str(ct_dir), f"extra_no_axis={other_dir}"])
    axis_spec = load_axis_spec("crosswalks/pharma.yaml")
    graphs = resolve_domain_configs(graphs, axis_spec)
    result = build_spine(graphs, axis_spec)

    stats = result["stats"]["trial"]
    # 'other' fixture's domain (drug-discovery) ships no crosswalk.yaml --
    # it must not appear in declared_by.
    assert "extra_no_axis" not in stats["declared_by"]
    assert stats["shared_by_all_graphs"] >= 1


# ---------------------------------------------------------------------------
# Loader boundaries
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_missing_graph_data_json_raises_naming_directory(tmp_path):
    from core.crosswalk import load_graphs

    empty_dir = tmp_path / "empty_graph"
    empty_dir.mkdir()
    with pytest.raises(CrosswalkConfigError) as exc_info:
        load_graphs([str(empty_dir)])
    assert str(empty_dir) in str(exc_info.value)


@pytest.mark.unit
def test_domain_with_no_crosswalk_yaml_is_skipped_not_aborted(tmp_path):
    from core.crosswalk import load_domain_config

    payload = {"metadata": {"domain": "drug-discovery"}, "nodes": [], "links": []}
    # drug-discovery ships no crosswalk.yaml -- must return None, not raise.
    assert load_domain_config(payload) is None


@pytest.mark.unit
def test_duplicate_graph_key_raises_unless_disambiguated(fixtures_dir):
    from core.crosswalk import load_graphs

    labels_dir = _crosswalk_fixture(fixtures_dir, "labels")
    with pytest.raises(CrosswalkConfigError):
        load_graphs([str(labels_dir), str(labels_dir)])

    # Disambiguated with NAME=DIR -- must not raise.
    graphs = load_graphs([f"first={labels_dir}", f"second={labels_dir}"])
    assert set(graphs) == {"first", "second"}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_cli_build_writes_roundtripping_spine(fixtures_dir, tmp_path):
    from core.crosswalk import main

    labels_dir = _crosswalk_fixture(fixtures_dir, "labels")
    ct_dir = _crosswalk_fixture(fixtures_dir, "ct")
    out_path = tmp_path / "spine.json"
    rc = main([
        "build",
        "--graph", str(labels_dir),
        "--graph", str(ct_dir),
        "--axes", "crosswalks/pharma.yaml",
        "--out", str(out_path),
    ])
    assert rc == 0
    payload = json.loads(out_path.read_text())
    for field in ("spine_version", "generated_at", "graphs", "axes", "stats"):
        assert field in payload


@pytest.mark.unit
def test_cli_missing_axes_exits_nonzero(fixtures_dir, tmp_path):
    from core.crosswalk import main

    labels_dir = _crosswalk_fixture(fixtures_dir, "labels")
    out_path = tmp_path / "spine.json"
    with pytest.raises(SystemExit) as exc_info:
        main(["build", "--graph", str(labels_dir), "--out", str(out_path)])
    assert exc_info.value.code != 0
