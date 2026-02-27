"""Tests for common/severity_projection.py — the pure-math exposure-adjustment
formulas: LoB-mix standardisation, composite beta, size adjustment, and capping.

Worked example from exposure-adjustment.md section 7:
    w_q = {Property: 0.60, Casualty: 0.40}, R_q = 200, R_ref = 500
    s = {Property: 0.15, Casualty: 0.08}
    => S_raw = 0.122, beta_weighted = -0.414, A ~ 1.461, S_adj ~ 0.178
"""

import sys
from pathlib import Path

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# Path setup — mirrors the pattern used in the production modules
# ---------------------------------------------------------------------------
_tests_dir = Path(__file__).resolve().parent
_novelty_dir = _tests_dir.parent
_stress_test_dir = _novelty_dir.parent
if str(_stress_test_dir) not in sys.path:
    sys.path.insert(0, str(_stress_test_dir))
if str(_novelty_dir) not in sys.path:
    sys.path.insert(0, str(_novelty_dir))

from common.severity_projection import (
    lob_weights_to_array,
    beta_lob_array,
    project_severity,
    composite_beta,
    size_adjustment_factor,
    adjusted_severity,
    cap_severity,
    cap_severity_array,
    N_LOBS,
)
from config import LLOYDS_LOBS, LOB_TO_INDEX
from portfolio_size_adjustment import (
    DEFAULT_LOB_COEFFICIENTS,
    DEFAULT_REFERENCE_SIZE_M,
    DEFAULT_OVERALL_COEFFICIENT,
)

# ---------------------------------------------------------------------------
# Helpers — build the worked-example arrays once
# ---------------------------------------------------------------------------

def _worked_example_arrays():
    """Return (w_q, s_lob) for the docstring worked example."""
    w_q = np.zeros(N_LOBS, dtype=np.float64)
    w_q[LOB_TO_INDEX["Property"]] = 0.60
    w_q[LOB_TO_INDEX["Casualty"]] = 0.40

    s_lob = np.zeros(N_LOBS, dtype=np.float64)
    s_lob[LOB_TO_INDEX["Property"]] = 0.15
    s_lob[LOB_TO_INDEX["Casualty"]] = 0.08
    return w_q, s_lob


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestProjectSeverity:
    """Tests for the LoB-mix standardised severity: S_raw = dot(w_q, s_lob)."""

    def test_project_severity_worked_example(self):
        w_q, s_lob = _worked_example_arrays()
        S_raw = project_severity(w_q, s_lob)
        # 0.60 * 0.15 + 0.40 * 0.08 = 0.09 + 0.032 = 0.122
        assert abs(S_raw - 0.122) < 1e-9

    def test_project_severity_identity(self):
        """When w_q == w_s the result equals the plain weighted sum."""
        w = np.zeros(N_LOBS, dtype=np.float64)
        w[0] = 0.5
        w[1] = 0.3
        w[2] = 0.2

        s = np.zeros(N_LOBS, dtype=np.float64)
        s[0] = 0.10
        s[1] = 0.20
        s[2] = 0.05

        expected = float(np.dot(w, s))
        assert abs(project_severity(w, s) - expected) < 1e-12


class TestCompositeBeta:
    """Tests for the LoB-weighted composite size exponent."""

    def test_composite_beta_worked_example(self):
        w_q, _ = _worked_example_arrays()
        beta = composite_beta(w_q)
        # beta_Property = -0.49, beta_Casualty = -0.30
        # beta_weighted = (0.60*(-0.49) + 0.40*(-0.30)) / 1.0 = -0.414
        assert abs(beta - (-0.414)) < 1e-9


class TestSizeAdjustmentFactor:
    """Tests for the multiplicative size adjustment A = (R_q / R_ref)^beta."""

    def test_size_adjustment_factor_worked_example(self):
        # (200/500)^(-0.414) = 0.4^(-0.414)
        A = size_adjustment_factor(200.0, 500.0, -0.414)
        assert abs(A - 1.461) < 0.005

    def test_size_adjustment_factor_identity(self):
        """When R_q == R_ref the factor is 1.0."""
        A = size_adjustment_factor(500.0, 500.0, -0.414)
        assert abs(A - 1.0) < 1e-12

    def test_size_adjustment_factor_zero_guard(self):
        """Zero or negative reserves yield factor 1.0."""
        assert size_adjustment_factor(0.0, 500.0, -0.3) == 1.0
        assert size_adjustment_factor(500.0, 0.0, -0.3) == 1.0
        assert size_adjustment_factor(-100.0, 500.0, -0.3) == 1.0


class TestAdjustedSeverity:
    """End-to-end: S_adj = S_raw * (R_q / R_ref)^beta."""

    def test_adjusted_severity_worked_example(self):
        S_adj = adjusted_severity(0.122, 200.0, 500.0, -0.414)
        # 0.122 * 1.461 ~ 0.178
        assert abs(S_adj - 0.178) < 0.005


class TestCapSeverity:
    """Tests for clipping severity to [-max, +max]."""

    def test_cap_severity_within_bounds(self):
        assert cap_severity(2.5) == 2.5
        assert cap_severity(-2.5) == -2.5

    def test_cap_severity_clips_positive(self):
        assert cap_severity(7.0) == 5.0

    def test_cap_severity_clips_negative(self):
        assert cap_severity(-7.0) == -5.0

    def test_cap_severity_custom_max(self):
        assert cap_severity(3.5, max_sev=3.0) == 3.0
        assert cap_severity(-3.5, max_sev=3.0) == -3.0

    def test_cap_severity_array_clips(self):
        arr = np.array([-6.0, -2.0, 0.0, 3.0, 8.0])
        result = cap_severity_array(arr)
        np.testing.assert_array_equal(result, [-5.0, -2.0, 0.0, 3.0, 5.0])


class TestLobWeightsToArray:
    """Tests for converting dict weights to the 13-element aligned array."""

    def test_lob_weights_to_array_ordering(self):
        weights = {"Property": 0.5, "Casualty": 0.3, "Marine": 0.2}
        arr = lob_weights_to_array(weights)
        assert arr[LOB_TO_INDEX["Property"]] == 0.5
        assert arr[LOB_TO_INDEX["Casualty"]] == 0.3
        assert arr[LOB_TO_INDEX["Marine"]] == 0.2
        # All other entries should be zero
        for i in range(N_LOBS):
            if LLOYDS_LOBS[i] not in weights:
                assert arr[i] == 0.0

    def test_lob_weights_to_array_length(self):
        arr = lob_weights_to_array({"Property": 1.0})
        assert len(arr) == N_LOBS

    def test_lob_weights_to_array_empty(self):
        arr = lob_weights_to_array({})
        np.testing.assert_array_equal(arr, np.zeros(N_LOBS))


class TestBetaLobArray:
    """Tests for the per-LoB beta coefficient array."""

    def test_beta_lob_array_property(self):
        """Property at index 0 should be -0.49."""
        betas = beta_lob_array()
        assert betas[LOB_TO_INDEX["Property"]] == DEFAULT_LOB_COEFFICIENTS["Property"]
        assert betas[LOB_TO_INDEX["Property"]] == -0.49

    def test_beta_lob_array_length(self):
        betas = beta_lob_array()
        assert len(betas) == N_LOBS

    def test_beta_lob_array_all_lobs_present(self):
        """Every LOB with a default coefficient should appear at the right index."""
        betas = beta_lob_array()
        for lob, expected_beta in DEFAULT_LOB_COEFFICIENTS.items():
            idx = LOB_TO_INDEX.get(lob)
            if idx is not None:
                assert betas[idx] == expected_beta, f"{lob}: expected {expected_beta}, got {betas[idx]}"
