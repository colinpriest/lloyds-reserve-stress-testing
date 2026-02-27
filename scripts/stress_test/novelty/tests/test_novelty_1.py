"""Tests for novelty_1_mix_trend.py.

Uses synthetic data to validate yearly summary statistics, OLS trend
estimation, subset filtering, and query column construction.
"""

import sys
from pathlib import Path
import numpy as np
import pytest

_tests_dir = Path(__file__).resolve().parent
_novelty_dir = _tests_dir.parent
_stress_test_dir = _novelty_dir.parent
if str(_stress_test_dir) not in sys.path:
    sys.path.insert(0, str(_stress_test_dir))
if str(_novelty_dir) not in sys.path:
    sys.path.insert(0, str(_novelty_dir))

import pandas as pd
from common.time_windows import year_summary_stats, ols_trend
from common.analysis_table import get_subset, add_query_columns
from common.severity_projection import N_LOBS


def _make_analysis_df(years=None, n_per_year=50, seed=0):
    """Build a synthetic analysis DataFrame with all columns needed by the novelty modules."""
    rng = np.random.default_rng(seed)
    if years is None:
        years = list(range(2014, 2024))
    rows = []
    for yr in years:
        for i in range(n_per_year):
            w_s = np.zeros(N_LOBS, dtype=np.float64)
            w_s[0] = 0.5  # Property
            w_s[1] = 0.3  # Casualty
            w_s[2] = 0.2  # Marine
            s_lob = np.zeros(N_LOBS, dtype=np.float64)
            s_lob[0] = rng.normal(0.10, 0.03)
            s_lob[1] = rng.normal(0.08, 0.02)
            s_lob[2] = rng.normal(0.05, 0.01)
            rows.append({
                "syndicate_id": f"S{i:04d}",
                "year": yr,
                "cause_category": "natural_cat",
                "event_id": f"{yr}_natural_cat",
                "R_s": rng.uniform(100, 2000),
                "R_s_source": "prior_reserves_gbp_m",
                "w_s": {"Property": 0.5, "Casualty": 0.3, "Marine": 0.2},
                "w_s_array": w_s,
                "s_lob": s_lob,
                "S_raw_a": float(np.dot(w_s, s_lob)),
                "S_raw_b": float(np.dot(w_s, s_lob)),
                "HHI_s": float(np.sum(w_s ** 2)),
                "n_lobs": 3,
                "lob_present_mask": np.array([True, True, True] + [False] * (N_LOBS - 3)),
                "data_quality_flags": {
                    "weight_source": "extraction",
                    "extraction_confidence": "high",
                    "R_s_source": "prior_reserves_gbp_m",
                },
                "cap_binding": {},
            })
    return pd.DataFrame(rows)


def test_yearly_stats_known_data():
    """Verify year_summary_stats returns correct median and p95 for known data."""
    # Create simple data: year 2014 has values [1, 2, 3, 4, 5]
    df = pd.DataFrame({
        "year": [2014] * 5 + [2015] * 5,
        "severity": [1.0, 2.0, 3.0, 4.0, 5.0, 10.0, 20.0, 30.0, 40.0, 50.0],
    })
    stats = year_summary_stats(df, "severity")
    assert 2014 in stats.index
    assert 2015 in stats.index
    # Median of [1,2,3,4,5] = 3.0
    assert stats.loc[2014, "median"] == pytest.approx(3.0)
    # Median of [10,20,30,40,50] = 30.0
    assert stats.loc[2015, "median"] == pytest.approx(30.0)
    # p95 of [1,2,3,4,5] = np.percentile([1,2,3,4,5], 95) = 4.8
    assert stats.loc[2014, "p95"] == pytest.approx(np.percentile([1, 2, 3, 4, 5], 95))


def test_trend_slope_zero_for_constant():
    """Constant p95 across years should produce OLS slope approximately zero."""
    years = np.array([2014, 2015, 2016, 2017, 2018, 2019], dtype=np.float64)
    p95_vals = np.array([0.15, 0.15, 0.15, 0.15, 0.15, 0.15], dtype=np.float64)
    slope, intercept, se, pval = ols_trend(years, p95_vals)
    assert abs(slope) < 1e-10


def test_trend_slope_positive_for_increasing():
    """Linearly increasing p95 values should yield a positive OLS slope."""
    years = np.array([2014, 2015, 2016, 2017, 2018, 2019], dtype=np.float64)
    p95_vals = np.array([0.10, 0.12, 0.14, 0.16, 0.18, 0.20], dtype=np.float64)
    slope, intercept, se, pval = ols_trend(years, p95_vals)
    assert slope > 0
    # Exact slope should be 0.02 per year
    assert slope == pytest.approx(0.02, abs=1e-10)


def test_dense_filter_years():
    """get_subset(df, 'DENSE') should return only rows with years 2014-2019."""
    df = _make_analysis_df(years=list(range(2014, 2024)), n_per_year=10)
    dense_df, cov = get_subset(df, "DENSE")
    years_in_dense = sorted(dense_df["year"].unique())
    assert years_in_dense == [2014, 2015, 2016, 2017, 2018, 2019]
    assert cov.year_range == (2014, 2019)


def test_both_raw_metrics_produced():
    """After add_query_columns, both S_raw_a and S_std columns should exist."""
    df = _make_analysis_df(years=[2014, 2015], n_per_year=10)
    w_q = np.zeros(N_LOBS, dtype=np.float64)
    w_q[0] = 0.6  # Property
    w_q[1] = 0.4  # Casualty
    df = add_query_columns(df, w_q, 500.0, "test_query")
    assert "S_raw_a" in df.columns
    assert "S_std_test_query" in df.columns
    # S_std should not be all NaN
    assert df["S_std_test_query"].notna().sum() > 0
