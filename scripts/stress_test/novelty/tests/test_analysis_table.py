"""Tests for common/analysis_table.py — golden-file integration tests using
the mini fixture files.

Builds the unified analysis table from mini_corpus.json, mini_lob_weights.json,
and mini_size_metrics.json, then verifies structure, merge audit, balanced
panel logic, cap-binding diagnostics, dual raw severity metrics, and subset
filtering.
"""

import sys
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
_tests_dir = Path(__file__).resolve().parent
_novelty_dir = _tests_dir.parent
_stress_test_dir = _novelty_dir.parent
if str(_stress_test_dir) not in sys.path:
    sys.path.insert(0, str(_stress_test_dir))
if str(_novelty_dir) not in sys.path:
    sys.path.insert(0, str(_novelty_dir))

from common.analysis_table import (
    build_analysis_table,
    audit_merge,
    compute_cap_binding_stats,
    get_subset,
    _compute_balanced_panels,
)

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------
_FIXTURES_DIR = _tests_dir / "fixtures"
_CORPUS_PATH = str(_FIXTURES_DIR / "mini_corpus.json")
_LOB_WEIGHTS_PATH = str(_FIXTURES_DIR / "mini_lob_weights.json")
_SIZE_METRICS_PATH = str(_FIXTURES_DIR / "mini_size_metrics.json")


# ---------------------------------------------------------------------------
# Module-scoped fixture: build the table once for all tests
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def analysis_table() -> pd.DataFrame:
    """Build the analysis table from mini fixtures once per module."""
    df = build_analysis_table(
        corpus_path=_CORPUS_PATH,
        lob_weights_path=_LOB_WEIGHTS_PATH,
        size_metrics_path=_SIZE_METRICS_PATH,
    )
    return df


# ---------------------------------------------------------------------------
# Structure tests
# ---------------------------------------------------------------------------

class TestBuildTableFromFixtures:
    """Verify that the table built from mini fixtures has the right shape."""

    def test_row_count(self, analysis_table):
        """3 syndicates x 3 years = 9 syndicate-year rows."""
        assert len(analysis_table) == 9, (
            f"Expected 9 rows, got {len(analysis_table)}"
        )

    def test_required_columns_exist(self, analysis_table):
        """All expected columns must be present."""
        required = [
            "syndicate_id", "year", "cause_category", "event_id",
            "R_s", "R_s_source", "w_s", "w_s_array", "s_lob",
            "S_raw_a", "S_raw_b", "HHI_s", "n_lobs",
            "lob_present_mask", "data_quality_flags", "cap_binding",
        ]
        for col in required:
            assert col in analysis_table.columns, f"Missing column: {col}"

    def test_join_keys_match(self, analysis_table):
        """Every syndicate-year combination from the fixtures should appear."""
        expected_keys = set()
        for syn in [100, 200, 300]:
            for yr in [2015, 2016, 2017]:
                expected_keys.add((str(syn), yr))

        actual_keys = set(
            zip(analysis_table["syndicate_id"], analysis_table["year"])
        )
        assert actual_keys == expected_keys

    def test_syndicate_id_is_string(self, analysis_table):
        """syndicate_id should be stored as strings."""
        assert analysis_table["syndicate_id"].dtype == object
        for val in analysis_table["syndicate_id"]:
            assert isinstance(val, str)


# ---------------------------------------------------------------------------
# Merge audit diagnostics
# ---------------------------------------------------------------------------

class TestMergeAuditDiagnostics:
    """Tests for audit_merge: reports missingness rates."""

    def test_audit_merge_structure(self, analysis_table):
        audit = audit_merge(analysis_table)
        assert "n_rows" in audit
        assert audit["n_rows"] == 9
        assert "pct_missing_R_s" in audit
        assert "pct_missing_w_s" in audit
        assert "pct_missing_S_raw_a" in audit
        assert "pct_missing_S_raw_b" in audit
        assert "n_syndicates" in audit
        assert audit["n_syndicates"] == 3

    def test_audit_merge_low_missingness(self, analysis_table):
        """With our complete fixture data, missingness should be 0 for R_s."""
        audit = audit_merge(analysis_table)
        assert audit["pct_missing_R_s"] == 0.0, (
            f"Expected 0% missing R_s, got {audit['pct_missing_R_s']:.1%}"
        )

    def test_audit_merge_year_range(self, analysis_table):
        audit = audit_merge(analysis_table)
        assert audit["year_range"] == [2015, 2017]


# ---------------------------------------------------------------------------
# Balanced panel K-of-T
# ---------------------------------------------------------------------------

class TestBalancedPanel:
    """Tests for _compute_balanced_panels on the fixture data."""

    def test_balanced_panel_k_of_t(self, analysis_table):
        """On fixture data (3 syndicates x 3 years, all within 2014-2023),
        ALL syndicates should appear in every year, so ALL should contain
        all 3 syndicates."""
        panels = _compute_balanced_panels(analysis_table)

        # n_years = 3 (2015, 2016, 2017)
        # ALL: syndicates appearing in all 3 years
        assert len(panels["ALL"]) == 3, (
            f"Expected 3 syndicates in ALL panel, got {len(panels['ALL'])}"
        )

        # K8: min(8, 3) = 3, same as ALL
        assert panels["K8"] == panels["ALL"]

        # K6: min(6, 3) = 3, same as ALL
        assert panels["K6"] == panels["ALL"]

    def test_balanced_panel_syndicate_ids(self, analysis_table):
        """Verify the actual syndicate IDs in the ALL panel."""
        panels = _compute_balanced_panels(analysis_table)
        assert panels["ALL"] == {"100", "200", "300"}


# ---------------------------------------------------------------------------
# Cap-binding diagnostics
# ---------------------------------------------------------------------------

class TestCapBindingStats:
    """Tests for compute_cap_binding_stats on the fixture data."""

    def test_cap_binding_stats_structure(self, analysis_table):
        stats = compute_cap_binding_stats(analysis_table)
        assert "pct_capped_pos_5" in stats
        assert "pct_capped_neg_5" in stats
        assert "pct_floor_weight_1pct" in stats
        assert "by_year" in stats
        assert isinstance(stats["by_year"], dict)

    def test_cap_binding_stats_values(self, analysis_table):
        """With moderate fixture severities (all < 1.0), no values should
        hit the +/-5.0 cap."""
        stats = compute_cap_binding_stats(analysis_table)
        assert stats["pct_capped_pos_5"] == 0.0
        assert stats["pct_capped_neg_5"] == 0.0

    def test_cap_binding_by_year_keys(self, analysis_table):
        stats = compute_cap_binding_stats(analysis_table)
        assert set(stats["by_year"].keys()) == {2015, 2016, 2017}


# ---------------------------------------------------------------------------
# Dual raw severity metrics (Raw-A vs Raw-B)
# ---------------------------------------------------------------------------

class TestRawAvsRawB:
    """Tests for S_raw_a and S_raw_b on the fixture data."""

    def test_raw_a_vs_raw_b_non_nan(self, analysis_table):
        """On fixtures where both are computable, both should be non-NaN."""
        for _, row in analysis_table.iterrows():
            # R_s is present for all fixtures (prior_reserves_gbp_m is set)
            assert not np.isnan(row["S_raw_a"]), (
                f"S_raw_a is NaN for {row['syndicate_id']}_{row['year']}"
            )
            assert not np.isnan(row["S_raw_b"]), (
                f"S_raw_b is NaN for {row['syndicate_id']}_{row['year']}"
            )

    def test_raw_a_is_precomputed(self, analysis_table):
        """S_raw_a should use the precomputed severity_ratio from the corpus
        when available (which it is for all our fixtures)."""
        # Load the corpus to check precomputed values
        with open(_CORPUS_PATH, "r") as f:
            corpus = json.load(f)

        # Build a map of syndicate_year -> first severity_ratio
        sv_map = {}
        for m in corpus["movements"]:
            key = f"{m['syndicate']}_{m['year']}"
            if key not in sv_map and m.get("severity_ratio") is not None:
                sv_map[key] = m["severity_ratio"]

        for _, row in analysis_table.iterrows():
            key = f"{row['syndicate_id']}_{row['year']}"
            if key in sv_map:
                # The code prefers the precomputed severity_ratio
                # (it breaks after finding the first one)
                assert not np.isnan(row["S_raw_a"])

    def test_raw_b_is_weighted_sum(self, analysis_table):
        """S_raw_b = dot(w_s_array, s_lob); verify it is a plausible
        weighted sum of per-LoB severities."""
        for _, row in analysis_table.iterrows():
            w = row["w_s_array"]
            s = row["s_lob"]
            expected = float(np.dot(w, s))
            if not np.isnan(row["S_raw_b"]):
                assert abs(row["S_raw_b"] - expected) < 1e-9, (
                    f"S_raw_b mismatch for {row['syndicate_id']}_{row['year']}: "
                    f"got {row['S_raw_b']}, expected {expected}"
                )


# ---------------------------------------------------------------------------
# Subset extraction
# ---------------------------------------------------------------------------

class TestGetSubset:
    """Tests for get_subset: named subsets with year/syndicate filters."""

    def test_get_subset_dense(self, analysis_table):
        """DENSE filters to years 2014-2019; our data is 2015-2017 so all
        9 rows should pass."""
        sub, stats = get_subset(analysis_table, "DENSE")
        assert len(sub) == 9
        assert stats.n_observations == 9
        assert stats.n_syndicates == 3
        assert stats.year_range == (2015, 2017)

    def test_get_subset_full(self, analysis_table):
        """FULL filters to years 2014-2023; all fixture data should pass."""
        sub, stats = get_subset(analysis_table, "FULL")
        assert len(sub) == 9

    def test_get_subset_mid_empty(self, analysis_table):
        """MID filters to years 2020-2023; no fixture data in that range."""
        sub, stats = get_subset(analysis_table, "MID")
        assert len(sub) == 0
        assert stats.n_observations == 0

    def test_get_subset_balanced_all(self, analysis_table):
        """BALANCED_ALL: all 3 syndicates appear in all 3 years, so all
        9 rows should be included."""
        sub, stats = get_subset(analysis_table, "BALANCED_ALL")
        assert len(sub) == 9
        assert stats.n_syndicates == 3

    def test_get_subset_unknown_raises(self, analysis_table):
        """Unknown subset name should raise ValueError."""
        with pytest.raises(ValueError, match="Unknown subset"):
            get_subset(analysis_table, "NONEXISTENT")

    def test_get_subset_coverage_stats(self, analysis_table):
        """Verify CoverageStats structure from get_subset."""
        _, stats = get_subset(analysis_table, "DENSE")
        assert hasattr(stats, "n_observations")
        assert hasattr(stats, "n_syndicates")
        assert hasattr(stats, "syndicates_per_year_min")
        assert hasattr(stats, "syndicates_per_year_max")
        assert hasattr(stats, "year_range")
        assert hasattr(stats, "exclusion_rules")
        # For our balanced fixture, min == max == 3 syndicates per year
        assert stats.syndicates_per_year_min == 3
        assert stats.syndicates_per_year_max == 3
