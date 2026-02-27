"""Query portfolio definitions: 3 LoB mixes × 3 sizes for the test grid.

The market-average mix is computed dynamically from the DENSE subset
(2014–2019 volume-weighted average) to avoid hard-coding.
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Static portfolio definitions
# ---------------------------------------------------------------------------

PROPERTY_HEAVY: Dict[str, float] = {
    "Property": 0.60,
    "Casualty": 0.20,
    "Marine": 0.10,
    "Professional Lines": 0.10,
}

CASUALTY_HEAVY: Dict[str, float] = {
    "Casualty": 0.50,
    "Professional Lines": 0.20,
    "Property": 0.15,
    "Reinsurance - Casualty": 0.15,
}

SIZES_M: List[float] = [200.0, 500.0, 2000.0]

SIZE_LABELS: Dict[float, str] = {
    200.0: "small",
    500.0: "medium",
    2000.0: "large",
}


def _normalise_weights(w: Dict[str, float]) -> Dict[str, float]:
    """Normalise weights to sum to 1."""
    total = sum(w.values())
    if total <= 0:
        return w
    return {k: v / total for k, v in w.items()}


def compute_market_average_mix(
    df: pd.DataFrame, subset: str = "dense"
) -> Dict[str, float]:
    """Volume-weighted average LoB mix over the specified subset.

    Parameters
    ----------
    df : analysis table with 'year', 'R_s', 'w_s' columns
    subset : 'dense' (2014–2019) or 'full' (2014–2023)

    Returns
    -------
    Dict[str, float] — normalised LoB weights
    """
    if subset == "dense":
        mask = df["year"].between(2014, 2019)
    elif subset == "full":
        mask = df["year"].between(2014, 2023)
    else:
        mask = pd.Series(True, index=df.index)

    sub = df.loc[mask].dropna(subset=["R_s", "w_s"])
    if len(sub) == 0:
        # Fallback to equal weighting of Property and Casualty
        return {"Property": 0.50, "Casualty": 0.50}

    # Volume-weighted average: weight each syndicate-year's w_s by its R_s
    total_volume = 0.0
    agg: Dict[str, float] = {}
    for _, row in sub.iterrows():
        vol = row["R_s"] if pd.notna(row["R_s"]) and row["R_s"] > 0 else 1.0
        w_s = row["w_s"]
        if not isinstance(w_s, dict):
            continue
        for lob, w in w_s.items():
            agg[lob] = agg.get(lob, 0.0) + w * vol
        total_volume += vol

    if total_volume > 0:
        agg = {k: v / total_volume for k, v in agg.items()}
    return _normalise_weights(agg)


def get_query_portfolios(
    df: Optional[pd.DataFrame] = None,
) -> List[Tuple[str, Dict[str, float], float]]:
    """Return the full 3×3 grid of (name, lob_weights, size_m).

    Parameters
    ----------
    df : analysis table (needed to compute market-average mix).
         If None, market-average defaults to equal Property/Casualty.

    Returns
    -------
    List of (name, weights_dict, size_m) tuples, 9 entries.
    """
    if df is not None:
        market_avg = compute_market_average_mix(df, subset="dense")
    else:
        market_avg = {"Property": 0.50, "Casualty": 0.50}

    mixes = [
        ("market_avg", market_avg),
        ("property_heavy", PROPERTY_HEAVY),
        ("casualty_heavy", CASUALTY_HEAVY),
    ]

    portfolios = []
    for mix_name, weights in mixes:
        for size_m in SIZES_M:
            size_label = SIZE_LABELS.get(size_m, f"{int(size_m)}")
            name = f"{mix_name}_{size_label}"
            portfolios.append((name, _normalise_weights(weights), size_m))
    return portfolios
