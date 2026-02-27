"""Time windowing utilities for trend and rolling-window analysis.

Provides rolling window generation, per-year summary statistics, and
quantile regression for trend estimation.

Design note (review feedback #4): quantile_trend is a diagnostic-only
sensitivity check. The primary trend method is: compute yearly quantiles,
then OLS on those quantiles with bootstrap CIs.
"""

import numpy as np
import pandas as pd
from typing import Callable, Dict, List, Optional, Tuple

import statsmodels.api as sm


def rolling_windows(
    years: List[int], width: int = 5
) -> List[Tuple[int, int]]:
    """Generate rolling windows over sorted years.

    Parameters
    ----------
    years : list of distinct years (will be sorted)
    width : window width in years (inclusive)

    Returns
    -------
    List of (start_year, end_year) inclusive tuples.
    E.g. years=[2014..2023], width=5 -> [(2014,2018), (2015,2019), ..., (2019,2023)]
    """
    sorted_years = sorted(set(years))
    if len(sorted_years) < width:
        return []
    windows = []
    for i in range(len(sorted_years) - width + 1):
        windows.append((sorted_years[i], sorted_years[i + width - 1]))
    return windows


def year_summary_stats(
    df: pd.DataFrame,
    severity_col: str,
    year_col: str = "year",
    stat_funcs: Optional[Dict[str, Callable]] = None,
    thresholds: Optional[List[float]] = None,
) -> pd.DataFrame:
    """Compute summary statistics per year.

    Parameters
    ----------
    df : DataFrame with at least year_col and severity_col
    severity_col : column containing severity values
    year_col : column containing year
    stat_funcs : dict of {name: func(array) -> scalar}. Defaults provided.
    thresholds : exceedance thresholds (e.g. [0.10, 0.20, 0.30])

    Returns
    -------
    DataFrame with year as index, stat names as columns.
    """
    if stat_funcs is None:
        stat_funcs = {
            "n": lambda x: len(x),
            "mean": lambda x: np.mean(x),
            "sd": lambda x: np.std(x, ddof=1) if len(x) > 1 else np.nan,
            "median": lambda x: np.median(x),
            "p90": lambda x: np.percentile(x, 90),
            "p95": lambda x: np.percentile(x, 95),
            "p99": lambda x: np.percentile(x, 99),
        }
    if thresholds is None:
        thresholds = [0.10, 0.20, 0.30]

    records = []
    for year, group in df.groupby(year_col):
        vals = group[severity_col].dropna().values
        if len(vals) == 0:
            continue
        row = {"year": year}
        for name, func in stat_funcs.items():
            row[name] = func(vals)
        for t in thresholds:
            row[f"exceed_{t:.2f}"] = float(np.mean(vals > t))
        records.append(row)

    result = pd.DataFrame(records)
    if len(result) > 0:
        result = result.set_index("year").sort_index()
    return result


def ols_trend(
    years: np.ndarray, values: np.ndarray, weights: Optional[np.ndarray] = None
) -> Tuple[float, float, float, float]:
    """OLS linear trend: values ~ a + b * years.

    Parameters
    ----------
    years : array of year values
    values : array of response values (e.g. yearly p95)
    weights : optional observation weights

    Returns
    -------
    (slope, intercept, slope_se, p_value)
    """
    years = np.asarray(years, dtype=np.float64)
    values = np.asarray(values, dtype=np.float64)
    mask = ~(np.isnan(years) | np.isnan(values))
    years, values = years[mask], values[mask]
    if len(years) < 3:
        return (np.nan, np.nan, np.nan, np.nan)

    X = sm.add_constant(years)
    if weights is not None:
        weights = np.asarray(weights, dtype=np.float64)[mask]
        model = sm.WLS(values, X, weights=weights).fit()
    else:
        model = sm.OLS(values, X).fit()

    slope = float(model.params[1])
    intercept = float(model.params[0])
    slope_se = float(model.bse[1])
    p_value = float(model.pvalues[1])
    return (slope, intercept, slope_se, p_value)


def quantile_trend(
    years: np.ndarray,
    values: np.ndarray,
    tau: float,
    weights: Optional[np.ndarray] = None,
) -> Tuple[float, float, float]:
    """Quantile regression: Q_tau(values) ~ a + b * years.

    Diagnostic only — not a headline estimator (see design note).

    Parameters
    ----------
    years, values : arrays
    tau : quantile level (e.g. 0.95)

    Returns
    -------
    (slope, intercept, slope_se)
    """
    from statsmodels.regression.quantile_regression import QuantReg

    years = np.asarray(years, dtype=np.float64)
    values = np.asarray(values, dtype=np.float64)
    mask = ~(np.isnan(years) | np.isnan(values))
    years, values = years[mask], values[mask]
    if len(years) < 3:
        return (np.nan, np.nan, np.nan)

    # Center years for numerical stability (large values cause simplex
    # solver convergence issues).  Slope is invariant to centering.
    year_mean = np.mean(years)
    X = sm.add_constant(years - year_mean)
    try:
        model = QuantReg(values, X).fit(q=tau, max_iter=1000)
        slope = float(model.params[1])
        # Recover original intercept: intercept_orig = a_centered - slope * year_mean
        intercept = float(model.params[0]) - slope * year_mean
        slope_se = float(model.bse[1])
    except Exception:
        return (np.nan, np.nan, np.nan)
    return (slope, intercept, slope_se)
