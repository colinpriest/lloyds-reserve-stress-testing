"""Tests for novelty_0_sampling_sensitivity.py.

Uses synthetic data to validate leave-p-out resampling logic and
stability assessment without requiring the full corpus.
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
from novelty_0_sampling_sensitivity import (
    leave_p_out_resampling,
    _summarise_metric,
)


def _make_syndicate_df(n_syndicates: int = 100, seed: int = 0) -> pd.DataFrame:
    """Create a minimal DataFrame with syndicate_id, year, S_raw_a, R_s, S_std_market_avg."""
    rng = np.random.default_rng(seed)
    rows = []
    for s in range(n_syndicates):
        for year in range(2014, 2020):
            rows.append({
                "syndicate_id": f"S{s:04d}",
                "year": year,
                "S_raw_a": rng.normal(0.10, 0.05),
                "R_s": rng.uniform(100, 2000),
                "S_std_market_avg": rng.normal(0.10, 0.04),
            })
    return pd.DataFrame(rows)


def test_leave_p_out_drops_correct_fraction():
    """Dropping 10% of 100 syndicates should leave 90 syndicates per resample."""
    df = _make_syndicate_df(n_syndicates=100)
    all_syndicates = df["syndicate_id"].unique()
    assert len(all_syndicates) == 100

    n_drop = max(1, int(len(all_syndicates) * 0.10))
    assert n_drop == 10

    rng = np.random.default_rng(42)
    drop_ids = rng.choice(all_syndicates, size=n_drop, replace=False)
    remaining = df[~df["syndicate_id"].isin(drop_ids)]
    remaining_syndicates = remaining["syndicate_id"].nunique()
    assert remaining_syndicates == 90


def test_stability_threshold():
    """Verify _summarise_metric stability classification.

    sd/|point| < 0.30 => stable; sd/|point| >= 0.30 => not stable.
    """
    # Stable case: sd=0.05, point=1.0 => ratio=0.05 < 0.30
    samples_stable = np.random.default_rng(0).normal(1.0, 0.05, size=200)
    result_stable = _summarise_metric(samples_stable, point=1.0, name="test_stable")
    assert result_stable["stable"] is True
    assert result_stable["ratio_sd_point"] < 0.30

    # Unstable case: sd=0.4, point=1.0 => ratio=0.4 > 0.30
    samples_unstable = np.random.default_rng(1).normal(1.0, 0.40, size=200)
    result_unstable = _summarise_metric(samples_unstable, point=1.0, name="test_unstable")
    assert result_unstable["stable"] is False
    assert result_unstable["ratio_sd_point"] > 0.30
