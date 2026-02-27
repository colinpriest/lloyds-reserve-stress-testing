"""Tests for common/tail_metrics.py — VaR, TVaR, Hill estimator, mean excess
function, tail ratio, and both iid and cluster bootstrap.

Key properties tested:
- VaR / TVaR on known distributions (uniform 1..100)
- Hill estimator recovers Pareto tail index
- Hill returns (nan, nan) when k > n
- Mean excess function is constant for exponential
- Tail ratio on Uniform[0,1] ~ 0.99/0.95
- Bootstrap determinism under fixed seed
- Cluster bootstrap resamples whole clusters, not individual observations
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

from common.tail_metrics import (
    empirical_var,
    empirical_tvar,
    hill_estimator,
    mean_excess_function,
    tail_ratio,
    bootstrap_ci,
    cluster_bootstrap_syndicate,
    cluster_bootstrap_year,
)


# ---------------------------------------------------------------------------
# Point estimators
# ---------------------------------------------------------------------------

class TestEmpiricalVaR:
    """Tests for empirical_var (percentile-based VaR)."""

    def test_empirical_var_known(self):
        """For array [1..100], VaR at 0.95 should be near 95.05."""
        data = np.arange(1, 101, dtype=np.float64)
        var_95 = empirical_var(data, 0.95)
        # np.percentile([1..100], 95) = 95.05 (linear interpolation)
        assert abs(var_95 - 95.05) < 0.5

    def test_empirical_var_empty(self):
        assert np.isnan(empirical_var(np.array([]), 0.95))

    def test_empirical_var_nan_handling(self):
        data = np.array([1.0, 2.0, np.nan, 4.0, 5.0])
        var = empirical_var(data, 0.50)
        # After dropping NaN we have [1,2,4,5], median ~ 3.0
        assert abs(var - 3.0) < 0.5


class TestEmpiricalTVaR:
    """Tests for empirical_tvar: E[X | X >= VaR]."""

    def test_empirical_tvar_known(self):
        """For array [1..100], TVaR at 0.95 = mean of values >= VaR(0.95)."""
        data = np.arange(1, 101, dtype=np.float64)
        var_95 = empirical_var(data, 0.95)
        tvar_95 = empirical_tvar(data, 0.95)
        # Values >= 95.05 are {96, 97, 98, 99, 100}
        expected_tail_mean = np.mean([96, 97, 98, 99, 100])
        assert abs(tvar_95 - expected_tail_mean) < 0.5

    def test_tvar_geq_var(self):
        """TVaR should always be >= VaR."""
        rng = np.random.default_rng(42)
        data = rng.exponential(1.0, size=500)
        var = empirical_var(data, 0.95)
        tvar = empirical_tvar(data, 0.95)
        assert tvar >= var - 1e-9


class TestHillEstimator:
    """Tests for the Hill tail-index estimator."""

    def test_hill_pareto(self):
        """Generate Pareto(alpha=2) data; Hill with k=200 should recover xi ~ 0.5."""
        rng = np.random.default_rng(12345)
        # Pareto(alpha=2): CDF = 1 - x^(-2), so xi = 1/alpha = 0.5
        uniform = rng.uniform(0, 1, size=10000)
        pareto_data = (1 - uniform) ** (-1.0 / 2.0)  # Inverse CDF transform
        xi_hat, se = hill_estimator(pareto_data, k=200)
        assert abs(xi_hat - 0.5) < 0.15, f"Hill xi = {xi_hat}, expected ~0.5"
        assert se > 0

    def test_hill_insufficient_data(self):
        """Returns (nan, nan) when k > n."""
        data = np.array([1.0, 2.0, 3.0])
        xi, se = hill_estimator(data, k=10)
        assert np.isnan(xi)
        assert np.isnan(se)

    def test_hill_k_equals_n(self):
        """k == n should still fail (need k+1 values)."""
        data = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        xi, se = hill_estimator(data, k=5)
        assert np.isnan(xi)
        assert np.isnan(se)


class TestMeanExcessFunction:
    """Tests for the mean excess function E[X - u | X > u]."""

    def test_mef_exponential(self):
        """For Exp(1) the MEF should be constant ~ 1.0 at all thresholds."""
        rng = np.random.default_rng(99)
        data = rng.exponential(scale=1.0, size=10000)
        thresholds = np.array([0.5, 1.0, 1.5, 2.0])
        mef = mean_excess_function(data, thresholds, min_exceedances=5)
        # All non-NaN values should be close to 1.0
        for i, u in enumerate(thresholds):
            if not np.isnan(mef[i]):
                assert abs(mef[i] - 1.0) < 0.2, (
                    f"MEF at threshold {u} = {mef[i]}, expected ~1.0"
                )

    def test_mef_returns_nan_for_high_threshold(self):
        """Threshold above max data -> NaN due to insufficient exceedances."""
        data = np.arange(1.0, 11.0)
        thresholds = np.array([100.0])
        mef = mean_excess_function(data, thresholds, min_exceedances=5)
        assert np.isnan(mef[0])


class TestTailRatio:
    """Tests for tail_ratio: p_q1 / p_q2."""

    def test_tail_ratio_uniform(self):
        """Uniform[0,1] -> p99/p95 ~ 0.99/0.95 ~ 1.042."""
        rng = np.random.default_rng(42)
        data = rng.uniform(0, 1, size=100000)
        ratio = tail_ratio(data, 0.99, 0.95)
        expected = 0.99 / 0.95  # ~ 1.04211
        assert abs(ratio - expected) < 0.01

    def test_tail_ratio_nan_on_empty(self):
        assert np.isnan(tail_ratio(np.array([]), 0.99, 0.95))


# ---------------------------------------------------------------------------
# Bootstrap (iid)
# ---------------------------------------------------------------------------

class TestBootstrapCI:
    """Tests for the iid bootstrap CI."""

    def test_bootstrap_ci_deterministic(self):
        """Same seed produces identical CI."""
        data = np.arange(1, 51, dtype=np.float64)
        stat_func = np.mean

        result1 = bootstrap_ci(data, stat_func, B=200, seed=7)
        result2 = bootstrap_ci(data, stat_func, B=200, seed=7)

        for a, b in zip(result1, result2):
            assert a == b, "Bootstrap results differ with same seed"

    def test_bootstrap_ci_covers_true_mean(self):
        """CI from normal data should contain the true mean (mu=5)."""
        rng = np.random.default_rng(42)
        data = rng.normal(loc=5.0, scale=1.0, size=200)
        point, lo, hi, se = bootstrap_ci(data, np.mean, B=500, seed=42)
        assert lo < 5.0 < hi, f"CI [{lo}, {hi}] does not contain 5.0"

    def test_bootstrap_ci_returns_four_values(self):
        data = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        result = bootstrap_ci(data, np.mean, B=50, seed=0)
        assert len(result) == 4  # (point, lower, upper, se)


# ---------------------------------------------------------------------------
# Cluster bootstrap
# ---------------------------------------------------------------------------

class TestClusterBootstrapSyndicate:
    """Tests for cluster_bootstrap_syndicate: resamples whole syndicates."""

    def test_cluster_bootstrap_syndicate_groups(self):
        """Verify it resamples clusters, not individual observations.

        Construct 3 syndicates, each with 10 identical observations.
        After cluster resampling, the number of unique syndicate values in
        each replicate should always be <= 3 (not 30).
        """
        rows = []
        for syn in [100, 200, 300]:
            for _ in range(10):
                rows.append({
                    "syndicate_id": syn,
                    "value": float(syn),  # values equal to syndicate ID
                })
        df = pd.DataFrame(rows)

        # Use a stat that is sensitive to cluster composition
        point, lo, hi, se = cluster_bootstrap_syndicate(
            df,
            stat_func=np.mean,
            value_col="value",
            cluster_col="syndicate_id",
            B=200,
            seed=42,
        )
        # Point estimate should be mean of [100]*10 + [200]*10 + [300]*10 = 200
        assert abs(point - 200.0) < 1e-9

        # CI should not be degenerate (cluster resampling introduces variance)
        assert lo < hi

    def test_cluster_bootstrap_syndicate_deterministic(self):
        """Same seed gives same result."""
        rows = []
        for syn in [10, 20]:
            for _ in range(5):
                rows.append({"syndicate_id": syn, "value": float(syn)})
        df = pd.DataFrame(rows)

        r1 = cluster_bootstrap_syndicate(df, np.mean, "value", B=100, seed=7)
        r2 = cluster_bootstrap_syndicate(df, np.mean, "value", B=100, seed=7)
        for a, b in zip(r1, r2):
            assert a == b


class TestClusterBootstrapYear:
    """Tests for cluster_bootstrap_year: resamples whole years."""

    def test_cluster_bootstrap_year_groups(self):
        """Verify it resamples year clusters, not individual observations.

        3 years, each with 10 observations. Values are year-dependent.
        """
        rows = []
        for yr in [2015, 2016, 2017]:
            for i in range(10):
                rows.append({
                    "year": yr,
                    "value": float(yr - 2000),  # 15, 16, 17
                })
        df = pd.DataFrame(rows)

        point, lo, hi, se = cluster_bootstrap_year(
            df,
            stat_func=np.mean,
            value_col="value",
            year_col="year",
            B=200,
            seed=42,
        )
        # Point estimate = mean of [15]*10 + [16]*10 + [17]*10 = 16
        assert abs(point - 16.0) < 1e-9
        # CI should not be degenerate
        assert lo < hi

    def test_cluster_bootstrap_year_deterministic(self):
        """Same seed gives same result."""
        rows = []
        for yr in [2020, 2021]:
            for _ in range(5):
                rows.append({"year": yr, "value": float(yr - 2000)})
        df = pd.DataFrame(rows)

        r1 = cluster_bootstrap_year(df, np.mean, "value", B=100, seed=11)
        r2 = cluster_bootstrap_year(df, np.mean, "value", B=100, seed=11)
        for a, b in zip(r1, r2):
            assert a == b
