"""Tests for novelty_2_tail_stability.py.

Validates Hill estimator convergence, minimum sample thresholds for
tail ratio and mean excess function, and rolling window coverage.
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

from common.tail_metrics import hill_estimator, mean_excess_function, tail_ratio
from common.time_windows import rolling_windows
from novelty_2_tail_stability import (
    _compute_tail_metrics_for_series,
    MIN_OBS_TAIL_RATIO,
    MIN_EXCEEDANCES_MEF,
)


def test_hill_convergence_pareto():
    """For Pareto(alpha=2) data, the Hill estimator at k=100 should yield xi ~ 0.5.

    Pareto with shape alpha=2 has tail index xi = 1/alpha = 0.5.
    """
    rng = np.random.default_rng(42)
    # Generate Pareto(alpha=2) data: X = U^(-1/alpha) where U ~ Uniform(0,1)
    alpha = 2.0
    n = 5000
    u = rng.uniform(0, 1, size=n)
    pareto_data = u ** (-1.0 / alpha)  # Pareto distributed with shape=alpha

    k = 100
    xi_hat, se = hill_estimator(pareto_data, k=k)

    # xi should be approximately 1/alpha = 0.5
    assert xi_hat == pytest.approx(0.5, abs=0.15), (
        f"Hill xi_hat={xi_hat:.4f}, expected ~0.5 for Pareto(2)"
    )
    # SE should be finite and positive
    assert se > 0
    assert np.isfinite(se)


def test_min_sample_tail_ratio():
    """If n < MIN_OBS_TAIL_RATIO (200) in a window, tail_ratio should be NaN."""
    # Create a small sample (fewer than 200 observations)
    rng = np.random.default_rng(7)
    small_data = rng.normal(0.10, 0.05, size=100)
    assert len(small_data) < MIN_OBS_TAIL_RATIO

    metrics = _compute_tail_metrics_for_series(small_data)
    assert np.isnan(metrics["tail_ratio_99_95"])
    assert np.isnan(metrics["tail_ratio_95_90"])

    # With enough data, tail_ratio should be computed
    large_data = rng.normal(0.10, 0.05, size=300)
    metrics_large = _compute_tail_metrics_for_series(large_data)
    assert not np.isnan(metrics_large["tail_ratio_99_95"])


def test_min_exceedances_mef():
    """mean_excess_function returns NaN when fewer than min_exceedances observations exceed u."""
    # Only 3 values exceed u=0.50, but min_exceedances=5
    data = np.array([0.01, 0.02, 0.03, 0.04, 0.55, 0.60, 0.70])
    thresholds = np.array([0.50])
    result = mean_excess_function(data, thresholds, min_exceedances=5)
    assert np.isnan(result[0])

    # With enough exceedances (>=5), should return a valid value
    data_more = np.array([0.01, 0.02, 0.51, 0.55, 0.60, 0.70, 0.80, 0.90])
    result_more = mean_excess_function(data_more, thresholds, min_exceedances=5)
    assert not np.isnan(result_more[0])
    # Mean excess = mean([0.01, 0.05, 0.10, 0.20, 0.30, 0.40]) for exceedances above 0.50
    exceedances = data_more[data_more > 0.50] - 0.50
    assert result_more[0] == pytest.approx(np.mean(exceedances))


def test_rolling_window_coverage():
    """rolling_windows([2014..2023], width=3) should produce 8 windows, each spanning 3 years."""
    years = list(range(2014, 2024))  # 2014 to 2023 inclusive = 10 years
    windows = rolling_windows(years, width=3)

    # 10 years with width=3 -> 10-3+1 = 8 windows
    assert len(windows) == 8

    # Each window should span exactly 3 years
    for start, end in windows:
        assert end - start == 2  # inclusive, so 3 years span = end - start + 1 = 3
        assert start >= 2014
        assert end <= 2023

    # First and last windows
    assert windows[0] == (2014, 2016)
    assert windows[-1] == (2021, 2023)
