"""Severity projection: pure math for the central exposure-adjustment formula.

Implements the LoB-mix standardisation (§3.3) and portfolio size adjustment (§4.3)
from the exposure-adjustment methodology. All functions are stateless and I/O-free.

Reference — central formula (exposure-adjustment.md §4.3):
    S_adj = (Σ w_q_ℓ · s_ℓ) · (R_q / R_ref) ^ β_weighted

Worked example (§7):
    w_q = {Property: 0.60, Casualty: 0.40}, R_q = 200, R_ref = 500
    s = {Property: 0.15, Casualty: 0.08}
    => S_raw = 0.122, β_weighted = -0.414, A ≈ 1.461, S_adj ≈ 0.178
"""

import sys
from pathlib import Path
import numpy as np
from typing import Dict, Optional

# ---------------------------------------------------------------------------
# Path setup — allow imports from parent (scripts/stress_test)
# ---------------------------------------------------------------------------
_this_dir = Path(__file__).resolve().parent
_stress_test_dir = _this_dir.parent.parent  # scripts/stress_test
if str(_stress_test_dir) not in sys.path:
    sys.path.insert(0, str(_stress_test_dir))

from config import LLOYDS_LOBS, LOB_TO_INDEX
from portfolio_size_adjustment import (
    DEFAULT_LOB_COEFFICIENTS,
    DEFAULT_REFERENCE_SIZE_M,
    DEFAULT_OVERALL_COEFFICIENT,
)

N_LOBS = len(LLOYDS_LOBS)  # 13


def lob_weights_to_array(weights_dict: Dict[str, float]) -> np.ndarray:
    """Convert {lob_name: weight} dict to 13-element array aligned to LLOYDS_LOBS.

    Missing LOBs get weight 0.0.
    """
    arr = np.zeros(N_LOBS, dtype=np.float64)
    for lob, weight in weights_dict.items():
        idx = LOB_TO_INDEX.get(lob)
        if idx is not None:
            arr[idx] = weight
    return arr


def beta_lob_array() -> np.ndarray:
    """Return 13-element array of DEFAULT_LOB_COEFFICIENTS aligned to LLOYDS_LOBS.

    LOBs not in DEFAULT_LOB_COEFFICIENTS get the overall default coefficient.
    """
    arr = np.full(N_LOBS, DEFAULT_OVERALL_COEFFICIENT, dtype=np.float64)
    for lob, beta in DEFAULT_LOB_COEFFICIENTS.items():
        idx = LOB_TO_INDEX.get(lob)
        if idx is not None:
            arr[idx] = beta
    return arr


def project_severity(w_q: np.ndarray, s_lob: np.ndarray) -> float:
    """LoB-standardised severity: S_raw = dot(w_q, s_lob).

    NaN values in s_lob are treated as 0.0 (no movement for that LoB).

    Parameters
    ----------
    w_q : ndarray[13] — query portfolio LoB weight vector
    s_lob : ndarray[13] — source LoB severity vector
    """
    s_clean = np.where(np.isnan(s_lob), 0.0, s_lob)
    return float(np.dot(w_q, s_clean))


def composite_beta(
    w_q: np.ndarray, beta_lob: Optional[np.ndarray] = None
) -> float:
    """LoB-weighted composite size exponent: β_weighted = dot(w_q, β_ℓ) / sum(w_q).

    Parameters
    ----------
    w_q : ndarray[13] — query portfolio LoB weight vector
    beta_lob : ndarray[13], optional — per-LoB β values; defaults to beta_lob_array()
    """
    if beta_lob is None:
        beta_lob = beta_lob_array()
    total = w_q.sum()
    if total == 0.0:
        return DEFAULT_OVERALL_COEFFICIENT
    return float(np.dot(w_q, beta_lob) / total)


def size_adjustment_factor(
    R_q: float,
    R_ref: float = DEFAULT_REFERENCE_SIZE_M,
    beta: float = DEFAULT_OVERALL_COEFFICIENT,
) -> float:
    """Multiplicative size adjustment: A = (R_q / R_ref) ^ β.

    Parameters
    ----------
    R_q : query portfolio reserves (£m)
    R_ref : reference portfolio size (£m), default 500
    beta : size-adjustment exponent
    """
    if R_ref <= 0.0 or R_q <= 0.0:
        return 1.0
    return float((R_q / R_ref) ** beta)


def adjusted_severity(
    S_raw: float,
    R_q: float,
    R_ref: float = DEFAULT_REFERENCE_SIZE_M,
    beta: float = DEFAULT_OVERALL_COEFFICIENT,
) -> float:
    """Full exposure-adjusted severity: S_adj = S_raw · (R_q / R_ref) ^ β."""
    return S_raw * size_adjustment_factor(R_q, R_ref, beta)


def cap_severity(s: float, max_sev: float = 5.0) -> float:
    """Clip severity to [-max_sev, +max_sev]."""
    return float(np.clip(s, -max_sev, max_sev))


def cap_severity_array(s_lob: np.ndarray, max_sev: float = 5.0) -> np.ndarray:
    """Clip each element of a LoB severity vector to [-max_sev, +max_sev]."""
    return np.clip(s_lob, -max_sev, max_sev)
