"""Tail metrics: VaR, TVaR, Hill estimator, mean excess, and dual-mode bootstrap.

Provides both iid and cluster bootstrap (by syndicate or by year) to reflect
partial-market sampling uncertainty (design rules R2).

All bootstrap functions use numpy.random.default_rng(seed) for reproducibility.
"""

import numpy as np
import pandas as pd
from typing import Callable, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Point estimators
# ---------------------------------------------------------------------------

def empirical_var(data: np.ndarray, alpha: float) -> float:
    """Value at Risk at level alpha (e.g. 0.995).

    Returns np.percentile(data, alpha * 100).
    """
    data = np.asarray(data, dtype=np.float64)
    data = data[~np.isnan(data)]
    if len(data) == 0:
        return np.nan
    return float(np.percentile(data, alpha * 100))


def empirical_tvar(data: np.ndarray, alpha: float) -> float:
    """Tail Value at Risk: E[X | X >= VaR(alpha)].

    Mean of observations at or above the VaR threshold.
    """
    data = np.asarray(data, dtype=np.float64)
    data = data[~np.isnan(data)]
    if len(data) == 0:
        return np.nan
    var = empirical_var(data, alpha)
    tail = data[data >= var]
    if len(tail) == 0:
        return var
    return float(np.mean(tail))


def hill_estimator(data: np.ndarray, k: int) -> Tuple[float, float]:
    """Hill estimator for the tail index xi using top-k order statistics.

    Parameters
    ----------
    data : positive values only (negative/zero silently dropped)
    k : number of upper order statistics to use

    Returns
    -------
    (xi_hat, se) where xi_hat = (1/k) * Σ log(X_(n-i+1) / X_(n-k))
    and se = xi_hat / sqrt(k).

    Returns (nan, nan) if insufficient data.
    """
    data = np.asarray(data, dtype=np.float64)
    data = data[(data > 0) & ~np.isnan(data)]
    if len(data) < k + 1 or k < 1:
        return (np.nan, np.nan)
    sorted_data = np.sort(data)[::-1]  # descending
    # top k values: sorted_data[0..k-1], threshold: sorted_data[k]
    threshold = sorted_data[k]
    if threshold <= 0:
        return (np.nan, np.nan)
    log_ratios = np.log(sorted_data[:k] / threshold)
    xi_hat = float(np.mean(log_ratios))
    se = xi_hat / np.sqrt(k) if k > 0 else np.nan
    return (xi_hat, float(se))


def mean_excess_function(
    data: np.ndarray, thresholds: np.ndarray, min_exceedances: int = 5
) -> np.ndarray:
    """Mean excess function: E[X - u | X > u] for each threshold u.

    Returns NaN where fewer than min_exceedances observations exceed u.
    """
    data = np.asarray(data, dtype=np.float64)
    data = data[~np.isnan(data)]
    thresholds = np.asarray(thresholds, dtype=np.float64)
    result = np.full(len(thresholds), np.nan)
    for i, u in enumerate(thresholds):
        exceedances = data[data > u] - u
        if len(exceedances) >= min_exceedances:
            result[i] = float(np.mean(exceedances))
    return result


def tail_ratio(data: np.ndarray, q1: float, q2: float) -> float:
    """Ratio of quantiles: percentile(q1) / percentile(q2).

    E.g. tail_ratio(data, 0.99, 0.95) = p99/p95.
    Returns NaN if denominator is zero.
    """
    data = np.asarray(data, dtype=np.float64)
    data = data[~np.isnan(data)]
    if len(data) == 0:
        return np.nan
    p_q1 = np.percentile(data, q1 * 100)
    p_q2 = np.percentile(data, q2 * 100)
    if p_q2 == 0.0:
        return np.nan
    return float(p_q1 / p_q2)


# ---------------------------------------------------------------------------
# Bootstrap: iid
# ---------------------------------------------------------------------------

def bootstrap_ci(
    data: np.ndarray,
    stat_func: Callable[[np.ndarray], float],
    B: int = 1000,
    alpha: float = 0.05,
    seed: Optional[int] = None,
) -> Tuple[float, float, float, float]:
    """Non-parametric iid bootstrap CI.

    Returns (point_estimate, ci_lower, ci_upper, se).
    """
    data = np.asarray(data, dtype=np.float64)
    data = data[~np.isnan(data)]
    point = stat_func(data)
    if len(data) == 0:
        return (np.nan, np.nan, np.nan, np.nan)

    rng = np.random.default_rng(seed)
    boot_stats = np.empty(B)
    for b in range(B):
        sample = rng.choice(data, size=len(data), replace=True)
        boot_stats[b] = stat_func(sample)

    ci_lower = float(np.percentile(boot_stats, (alpha / 2) * 100))
    ci_upper = float(np.percentile(boot_stats, (1 - alpha / 2) * 100))
    se = float(np.std(boot_stats, ddof=1))
    return (float(point), ci_lower, ci_upper, se)


def bootstrap_quantiles(
    data: np.ndarray,
    quantiles: List[float],
    B: int = 1000,
    seed: Optional[int] = None,
    alpha: float = 0.05,
) -> Dict[float, Tuple[float, float, float]]:
    """Bootstrap CIs for multiple quantiles simultaneously.

    Returns {q: (point, lower, upper)} for each q.
    """
    data = np.asarray(data, dtype=np.float64)
    data = data[~np.isnan(data)]
    if len(data) == 0:
        return {q: (np.nan, np.nan, np.nan) for q in quantiles}

    rng = np.random.default_rng(seed)
    boot_matrix = np.empty((B, len(quantiles)))
    for b in range(B):
        sample = rng.choice(data, size=len(data), replace=True)
        for j, q in enumerate(quantiles):
            boot_matrix[b, j] = np.percentile(sample, q * 100)

    result = {}
    for j, q in enumerate(quantiles):
        point = float(np.percentile(data, q * 100))
        lower = float(np.percentile(boot_matrix[:, j], (alpha / 2) * 100))
        upper = float(np.percentile(boot_matrix[:, j], (1 - alpha / 2) * 100))
        result[q] = (point, lower, upper)
    return result


# ---------------------------------------------------------------------------
# Cluster bootstrap: by syndicate (R2)
# ---------------------------------------------------------------------------

def cluster_bootstrap_syndicate(
    df: pd.DataFrame,
    stat_func: Callable[[np.ndarray], float],
    value_col: str,
    cluster_col: str = "syndicate_id",
    B: int = 500,
    alpha: float = 0.05,
    seed: Optional[int] = None,
) -> Tuple[float, float, float, float]:
    """Cluster bootstrap resampling syndicates with replacement.

    For each bootstrap replicate: sample clusters (syndicates) with replacement,
    then include ALL observations from each sampled cluster. This captures
    "which syndicates we happened to sample" uncertainty.

    Returns (point_estimate, ci_lower, ci_upper, se).
    """
    df = df.dropna(subset=[value_col])
    if len(df) == 0:
        return (np.nan, np.nan, np.nan, np.nan)

    point = stat_func(df[value_col].values)
    clusters = df[cluster_col].unique()
    n_clusters = len(clusters)
    if n_clusters == 0:
        return (float(point), np.nan, np.nan, np.nan)

    # Pre-group for efficiency
    grouped = {c: df.loc[df[cluster_col] == c, value_col].values for c in clusters}

    rng = np.random.default_rng(seed)
    boot_stats = np.empty(B)
    for b in range(B):
        sampled_clusters = rng.choice(clusters, size=n_clusters, replace=True)
        boot_data = np.concatenate([grouped[c] for c in sampled_clusters])
        boot_stats[b] = stat_func(boot_data)

    ci_lower = float(np.percentile(boot_stats, (alpha / 2) * 100))
    ci_upper = float(np.percentile(boot_stats, (1 - alpha / 2) * 100))
    se = float(np.std(boot_stats, ddof=1))
    return (float(point), ci_lower, ci_upper, se)


# ---------------------------------------------------------------------------
# Cluster bootstrap: by year (R2)
# ---------------------------------------------------------------------------

def cluster_bootstrap_year(
    df: pd.DataFrame,
    stat_func: Callable[[np.ndarray], float],
    value_col: str,
    year_col: str = "year",
    B: int = 500,
    alpha: float = 0.05,
    seed: Optional[int] = None,
) -> Tuple[float, float, float, float]:
    """Cluster bootstrap resampling years with replacement.

    For each bootstrap replicate: sample years with replacement, then include
    ALL syndicates observed in each sampled year. Captures year-composition
    uncertainty relevant for trend claims.

    Returns (point_estimate, ci_lower, ci_upper, se).
    """
    df = df.dropna(subset=[value_col])
    if len(df) == 0:
        return (np.nan, np.nan, np.nan, np.nan)

    point = stat_func(df[value_col].values)
    years = df[year_col].unique()
    n_years = len(years)
    if n_years == 0:
        return (float(point), np.nan, np.nan, np.nan)

    # Pre-group for efficiency
    grouped = {y: df.loc[df[year_col] == y, value_col].values for y in years}

    rng = np.random.default_rng(seed)
    boot_stats = np.empty(B)
    for b in range(B):
        sampled_years = rng.choice(years, size=n_years, replace=True)
        boot_data = np.concatenate([grouped[y] for y in sampled_years])
        boot_stats[b] = stat_func(boot_data)

    ci_lower = float(np.percentile(boot_stats, (alpha / 2) * 100))
    ci_upper = float(np.percentile(boot_stats, (1 - alpha / 2) * 100))
    se = float(np.std(boot_stats, ddof=1))
    return (float(point), ci_lower, ci_upper, se)
