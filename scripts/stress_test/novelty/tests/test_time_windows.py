"""Tests for common/time_windows.py — rolling windows, OLS trend, quantile
trend, and per-year summary statistics.

Key properties tested:
- Rolling windows over 10 years with width 5 yield 6 windows
- Fewer years than the window width yields empty list
- Exact window width yields exactly one window
- OLS on constant data gives slope ~ 0
- OLS on perfectly linear data recovers the true slope
- Quantile regression slope close to true slope for linear data
- year_summary_stats returns correct median / p95 / exceedance rates
"""

import sys
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

from common.time_windows import (
    rolling_windows,
    year_summary_stats,
    ols_trend,
    quantile_trend,
)


# ---------------------------------------------------------------------------
# Rolling windows
# ---------------------------------------------------------------------------

class TestRollingWindows:
    """Tests for rolling_windows()."""

    def test_rolling_windows_basic(self):
        """years=[2014..2023], width=5 -> 6 windows."""
        years = list(range(2014, 2024))  # 10 years
        windows = rolling_windows(years, width=5)
        assert len(windows) == 6
        assert windows[0] == (2014, 2018)
        assert windows[-1] == (2019, 2023)

    def test_rolling_windows_short(self):
        """3 years, width=5 -> empty list."""
        years = [2020, 2021, 2022]
        windows = rolling_windows(years, width=5)
        assert windows == []

    def test_rolling_windows_equal(self):
        """5 years, width=5 -> exactly 1 window."""
        years = [2015, 2016, 2017, 2018, 2019]
        windows = rolling_windows(years, width=5)
        assert len(windows) == 1
        assert windows[0] == (2015, 2019)

    def test_rolling_windows_unsorted_input(self):
        """Unsorted input should still produce correct sorted windows."""
        years = [2023, 2020, 2021, 2022, 2019]
        windows = rolling_windows(years, width=3)
        assert len(windows) == 3
        assert windows[0] == (2019, 2021)
        assert windows[-1] == (2021, 2023)

    def test_rolling_windows_width_one(self):
        """Width=1 gives one window per year."""
        years = [2020, 2021, 2022]
        windows = rolling_windows(years, width=1)
        assert len(windows) == 3
        assert windows[0] == (2020, 2020)


# ---------------------------------------------------------------------------
# OLS trend
# ---------------------------------------------------------------------------

class TestOLSTrend:
    """Tests for ols_trend(): values ~ a + b * years."""

    def test_ols_trend_constant(self):
        """Constant values should have slope ~ 0."""
        years = np.arange(2010, 2020, dtype=np.float64)
        values = np.full(10, 5.0)
        slope, intercept, slope_se, p_value = ols_trend(years, values)
        assert abs(slope) < 1e-10

    def test_ols_trend_linear(self):
        """values = 2 * years should give slope ~ 2."""
        years = np.arange(2010, 2020, dtype=np.float64)
        values = 2.0 * years
        slope, intercept, slope_se, p_value = ols_trend(years, values)
        assert abs(slope - 2.0) < 1e-8
        assert abs(intercept - 0.0) < 1e-4

    def test_ols_trend_insufficient_data(self):
        """Fewer than 3 points returns all NaN."""
        years = np.array([2020.0, 2021.0])
        values = np.array([1.0, 2.0])
        result = ols_trend(years, values)
        assert all(np.isnan(v) for v in result)


# ---------------------------------------------------------------------------
# Quantile trend
# ---------------------------------------------------------------------------

class TestQuantileTrend:
    """Tests for quantile_trend(): quantile regression on linear data."""

    def test_quantile_trend_basic(self):
        """Linear data -> slope close to true value at any quantile."""
        rng = np.random.default_rng(42)
        years = np.arange(2010, 2025, dtype=np.float64)
        # y = 0.5 * year + noise (small noise)
        values = 0.5 * years + rng.normal(0, 0.1, size=len(years))
        slope, intercept, slope_se = quantile_trend(years, values, tau=0.5)
        # Median regression slope should be close to 0.5
        assert abs(slope - 0.5) < 0.1, f"slope={slope}, expected ~0.5"

    def test_quantile_trend_insufficient_data(self):
        """Fewer than 3 points returns NaN."""
        years = np.array([2020.0, 2021.0])
        values = np.array([1.0, 2.0])
        slope, intercept, slope_se = quantile_trend(years, values, tau=0.5)
        assert np.isnan(slope)


# ---------------------------------------------------------------------------
# Year summary stats
# ---------------------------------------------------------------------------

class TestYearSummaryStats:
    """Tests for year_summary_stats()."""

    def test_year_summary_stats(self):
        """Hand-constructed DataFrame -> verify median, p95, exceedance."""
        # Year 2020: values [0.05, 0.10, 0.15, 0.20, 0.25]
        # Year 2021: values [0.30, 0.35, 0.40, 0.45, 0.50]
        df = pd.DataFrame({
            "year": [2020]*5 + [2021]*5,
            "severity": [0.05, 0.10, 0.15, 0.20, 0.25,
                         0.30, 0.35, 0.40, 0.45, 0.50],
        })

        result = year_summary_stats(df, severity_col="severity")

        # Check 2020
        assert result.loc[2020, "n"] == 5
        assert abs(result.loc[2020, "median"] - 0.15) < 1e-9
        # p95 of [0.05, 0.10, 0.15, 0.20, 0.25] = 0.24 (np.percentile linear)
        assert result.loc[2020, "p95"] > 0.20
        assert result.loc[2020, "p95"] <= 0.25

        # Exceedance rate at 0.10: proportion of values > 0.10
        # [0.05, 0.10, 0.15, 0.20, 0.25] -> 3/5 = 0.60
        assert abs(result.loc[2020, "exceed_0.10"] - 0.60) < 1e-9

        # Check 2021
        assert result.loc[2021, "n"] == 5
        assert abs(result.loc[2021, "median"] - 0.40) < 1e-9
        # Exceedance at 0.30: values > 0.30 are [0.35, 0.40, 0.45, 0.50] -> 4/5
        assert abs(result.loc[2021, "exceed_0.30"] - 0.80) < 1e-9

    def test_year_summary_stats_empty_group(self):
        """Empty DataFrame returns empty result."""
        df = pd.DataFrame({"year": [], "severity": []})
        result = year_summary_stats(df, severity_col="severity")
        assert len(result) == 0
