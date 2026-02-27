"""Tests for novelty_4_capital_distortion.py.

Validates the identity (no-adjustment) case, sequential decomposition
additivity, VaR/TVaR against numpy, and non-zero distortion for
different mix compositions.
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
from common.tail_metrics import empirical_var, empirical_tvar
from common.severity_projection import (
    project_severity,
    composite_beta,
    size_adjustment_factor,
    N_LOBS,
)
from novelty_4_capital_distortion import (
    _compute_four_distributions,
    _tail_metrics_table,
    _attribution,
)
from portfolio_size_adjustment import DEFAULT_REFERENCE_SIZE_M


def _make_distortion_df(n=200, seed=42, w_s_override=None):
    """Build a synthetic DataFrame for distortion tests.

    Each row has s_lob, S_raw_a, w_s_array, syndicate_id, year, cause_category.
    If w_s_override is provided, every row gets the same source weights.
    """
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(n):
        if w_s_override is not None:
            w_s = w_s_override.copy()
        else:
            w_s = np.zeros(N_LOBS, dtype=np.float64)
            w_s[0] = rng.uniform(0.2, 0.6)   # Property
            w_s[1] = rng.uniform(0.1, 0.4)   # Casualty
            w_s[2] = rng.uniform(0.0, 0.2)   # Marine
            total = w_s.sum()
            if total > 0:
                w_s = w_s / total

        s_lob = np.zeros(N_LOBS, dtype=np.float64)
        s_lob[0] = rng.normal(0.12, 0.04)
        s_lob[1] = rng.normal(0.08, 0.03)
        s_lob[2] = rng.normal(0.05, 0.02)

        S_raw_a = float(np.dot(w_s, s_lob))

        rows.append({
            "syndicate_id": f"S{i % 20:04d}",
            "year": 2014 + (i % 10),
            "cause_category": "natural_cat",
            "event_id": f"{2014 + (i % 10)}_natural_cat",
            "R_s": rng.uniform(200, 1500),
            "w_s_array": w_s,
            "s_lob": s_lob,
            "S_raw_a": S_raw_a,
            "S_raw_b": S_raw_a,
            "cap_binding": {},
        })
    return pd.DataFrame(rows)


def test_identity_no_adjustment():
    """When w_q == w_s for every row AND R_q == R_ref, S_naive ~ S_mix and S_mixsize ~ S_mix.

    If the query mix matches every source's mix exactly, the mix-projected
    severity equals the raw severity. With R_q == R_ref, the size adjustment
    factor is 1.0, so all four distributions should be nearly identical.
    """
    # Use a fixed w_s for all rows
    w_fixed = np.zeros(N_LOBS, dtype=np.float64)
    w_fixed[0] = 0.5  # Property
    w_fixed[1] = 0.3  # Casualty
    w_fixed[2] = 0.2  # Marine

    df = _make_distortion_df(n=300, seed=10, w_s_override=w_fixed)

    # Query = same mix, R_q = R_ref
    w_q = w_fixed.copy()
    R_q = DEFAULT_REFERENCE_SIZE_M  # R_q == R_ref => size factor = 1.0

    dists = _compute_four_distributions(df, w_q, R_q, R_ref=DEFAULT_REFERENCE_SIZE_M)

    # S_naive and S_mix should be essentially identical because w_q == w_s for all rows
    np.testing.assert_allclose(dists["S_naive"], dists["S_mix"], atol=1e-10)

    # S_mixsize should equal S_mix when size factor = 1.0 (R_q == R_ref)
    # The composite beta is irrelevant because (R_q/R_ref)^beta = 1^beta = 1
    np.testing.assert_allclose(dists["S_mix"], dists["S_mixsize"], atol=1e-10)


def test_residual_attribution_sums():
    """By construction of sequential decomposition: mix_effect + size_effect = total_effect.

    Use random data and verify the decomposition holds exactly.
    """
    rng = np.random.default_rng(77)
    df = _make_distortion_df(n=500, seed=77)

    # Use a different query mix from source
    w_q = np.zeros(N_LOBS, dtype=np.float64)
    w_q[0] = 0.7  # Property heavy
    w_q[1] = 0.2
    w_q[2] = 0.1

    R_q = 200.0  # Different from R_ref (500), so size adjustment is non-trivial

    dists = _compute_four_distributions(df, w_q, R_q)
    metrics = _tail_metrics_table(dists)
    attr = _attribution(metrics)

    # For every metric, mix_effect + size_effect must equal total_effect
    for metric_name, effects in attr.items():
        mix_eff = effects["mix_effect"]
        size_eff = effects["size_effect"]
        total_eff = effects["total_effect"]
        if mix_eff is not None and size_eff is not None and total_eff is not None:
            assert mix_eff + size_eff == pytest.approx(total_eff, abs=1e-12), (
                f"Decomposition failed for {metric_name}: "
                f"mix={mix_eff} + size={size_eff} != total={total_eff}"
            )


def test_var_tvar_against_numpy():
    """Verify empirical_var and empirical_tvar match numpy computations."""
    data = np.arange(0.01, 1.01, 0.01)  # [0.01, 0.02, ..., 1.00]
    assert len(data) == 100

    # VaR at alpha=0.99: np.percentile(data, 99)
    expected_var = np.percentile(data, 99)
    actual_var = empirical_var(data, 0.99)
    assert actual_var == pytest.approx(expected_var, abs=1e-12)

    # TVaR: mean of values >= VaR
    tail = data[data >= expected_var]
    expected_tvar = np.mean(tail)
    actual_tvar = empirical_tvar(data, 0.99)
    assert actual_tvar == pytest.approx(expected_tvar, abs=1e-12)


def test_distortion_nonzero_for_different_mix():
    """When source is Property-heavy but query is Casualty-heavy, S_mix should differ from S_naive.

    Property-heavy source: s_Property is large, s_Casualty is small.
    Casualty-heavy query: w_q weights Casualty more, so the projected
    severity S_mix = dot(w_q, s_lob) should differ from S_naive = dot(w_s, s_lob).
    """
    # Source mix is Property-heavy
    w_s = np.zeros(N_LOBS, dtype=np.float64)
    w_s[0] = 0.70  # Property
    w_s[1] = 0.20  # Casualty
    w_s[2] = 0.10  # Marine

    rng = np.random.default_rng(55)
    n = 300
    rows = []
    for i in range(n):
        s_lob = np.zeros(N_LOBS, dtype=np.float64)
        # Property has significantly higher severity than Casualty
        s_lob[0] = rng.normal(0.20, 0.05)
        s_lob[1] = rng.normal(0.05, 0.02)
        s_lob[2] = rng.normal(0.03, 0.01)
        S_raw_a = float(np.dot(w_s, s_lob))
        rows.append({
            "syndicate_id": f"S{i % 15:04d}",
            "year": 2014 + (i % 6),
            "cause_category": "natural_cat",
            "event_id": f"{2014 + (i % 6)}_natural_cat",
            "R_s": 500.0,
            "w_s_array": w_s.copy(),
            "s_lob": s_lob,
            "S_raw_a": S_raw_a,
            "S_raw_b": S_raw_a,
            "cap_binding": {},
        })
    df = pd.DataFrame(rows)

    # Query is Casualty-heavy
    w_q = np.zeros(N_LOBS, dtype=np.float64)
    w_q[0] = 0.20  # Property
    w_q[1] = 0.70  # Casualty
    w_q[2] = 0.10  # Marine

    R_q = DEFAULT_REFERENCE_SIZE_M  # Keep size neutral to isolate mix effect

    dists = _compute_four_distributions(df, w_q, R_q, R_ref=DEFAULT_REFERENCE_SIZE_M)

    # S_mix should differ materially from S_naive because query up-weights
    # Casualty (low severity) and down-weights Property (high severity)
    mean_naive = np.mean(dists["S_naive"])
    mean_mix = np.mean(dists["S_mix"])

    # Casualty-heavy query should produce lower average severity than
    # Property-heavy source, so mean_mix < mean_naive
    assert mean_mix < mean_naive, (
        f"Expected mean_mix ({mean_mix:.4f}) < mean_naive ({mean_naive:.4f}) "
        f"when shifting from Property-heavy source to Casualty-heavy query"
    )

    # The difference should be meaningfully non-zero
    assert abs(mean_naive - mean_mix) > 0.01, (
        f"Distortion too small: |{mean_naive:.4f} - {mean_mix:.4f}| should be > 0.01"
    )
