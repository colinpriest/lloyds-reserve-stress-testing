"""Tests for novelty_3_size_scaling_validation.py.

Validates James-Stein shrinkage arithmetic, composite beta dot-product,
simulated OLS recovery of a known beta, and the sanity-band check.
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
import statsmodels.api as sm
from common.severity_projection import composite_beta, N_LOBS
from novelty_3_size_scaling_validation import _sanity_check


def test_shrinkage_formula():
    """Verify the James-Stein shrinkage formula.

    Given:
      tau2 = 0.04, sigma2 = 0.01, beta_hat = -0.30, beta_bar = -0.24
    Then:
      lambda = tau2 / (tau2 + sigma2) = 0.04 / 0.05 = 0.80
      beta_star = lambda * beta_hat + (1 - lambda) * beta_bar
               = 0.80 * (-0.30) + 0.20 * (-0.24)
               = -0.240 + (-0.048)
               = -0.288
    """
    tau_sq = 0.04
    sigma_sq = 0.01
    beta_hat = -0.30
    beta_bar = -0.24

    lam = tau_sq / (tau_sq + sigma_sq)
    assert lam == pytest.approx(0.80, abs=1e-12)

    beta_star = lam * beta_hat + (1.0 - lam) * beta_bar
    assert beta_star == pytest.approx(-0.288, abs=1e-12)


def test_composite_beta_dot_product():
    """Verify composite_beta computes the weighted average correctly.

    w_q = [0.6 Property, 0.4 Casualty], beta = [-0.49, -0.30]
    composite = (0.6 * -0.49 + 0.4 * -0.30) / (0.6 + 0.4)
              = (-0.294 + -0.120) / 1.0
              = -0.414
    """
    w_q = np.zeros(N_LOBS, dtype=np.float64)
    beta_lob = np.zeros(N_LOBS, dtype=np.float64)

    # Property is index 0, Casualty is index 1 (based on LLOYDS_LOBS ordering)
    # We set only these two to create a clean test
    w_q[0] = 0.6   # Property
    w_q[1] = 0.4   # Casualty
    beta_lob[0] = -0.49  # Property beta
    beta_lob[1] = -0.30  # Casualty beta

    result = composite_beta(w_q, beta_lob)
    expected = (0.6 * (-0.49) + 0.4 * (-0.30)) / (0.6 + 0.4)
    assert result == pytest.approx(expected, abs=1e-12)
    assert result == pytest.approx(-0.414, abs=1e-12)


def test_simulated_data_recovery():
    """Generate 500 observations with true beta=-0.3 and verify OLS recovers it.

    DGP: s_i = 0.1 + (-0.3) * log(R_i) + noise
    where R_i ~ Uniform(100, 2000) and noise ~ N(0, 0.02).
    """
    rng = np.random.default_rng(99)
    n = 500
    true_intercept = 0.1
    true_beta = -0.3
    noise_sd = 0.02

    R = rng.uniform(100, 2000, size=n)
    log_R = np.log(R)
    noise = rng.normal(0, noise_sd, size=n)
    s = true_intercept + true_beta * log_R + noise

    X = sm.add_constant(log_R)
    model = sm.OLS(s, X).fit()
    recovered_beta = model.params[1]

    assert recovered_beta == pytest.approx(true_beta, abs=0.15), (
        f"Recovered beta={recovered_beta:.4f}, expected ~{true_beta}"
    )


def test_sanity_band():
    """beta must be in [-0.7, 0.0] for the sanity check to pass.

    _sanity_check looks at model_results['DENSE']['M1_event_fe']['beta'].
    """
    # Case 1: beta in range => pass
    model_results_pass = {
        "DENSE": {
            "M1_event_fe": {"beta": -0.35, "se": 0.05, "pvalue": 0.001, "n": 100, "r2": 0.3}
        }
    }
    result = _sanity_check(model_results_pass)
    assert result["passed"] is True

    # Case 2: beta too negative => fail
    model_results_fail_low = {
        "DENSE": {
            "M1_event_fe": {"beta": -0.80, "se": 0.05, "pvalue": 0.001, "n": 100, "r2": 0.3}
        }
    }
    result_low = _sanity_check(model_results_fail_low)
    assert result_low["passed"] is False

    # Case 3: beta positive => fail
    model_results_fail_high = {
        "DENSE": {
            "M1_event_fe": {"beta": 0.10, "se": 0.05, "pvalue": 0.001, "n": 100, "r2": 0.3}
        }
    }
    result_high = _sanity_check(model_results_fail_high)
    assert result_high["passed"] is False

    # Case 4: beta at boundary -0.7 => pass
    model_results_boundary = {
        "DENSE": {
            "M1_event_fe": {"beta": -0.7, "se": 0.05, "pvalue": 0.001, "n": 100, "r2": 0.3}
        }
    }
    result_boundary = _sanity_check(model_results_boundary)
    assert result_boundary["passed"] is True

    # Case 5: beta at boundary 0.0 => pass
    model_results_zero = {
        "DENSE": {
            "M1_event_fe": {"beta": 0.0, "se": 0.05, "pvalue": 0.001, "n": 100, "r2": 0.3}
        }
    }
    result_zero = _sanity_check(model_results_zero)
    assert result_zero["passed"] is True
