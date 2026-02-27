"""Novelty 3 -- Size-severity (beta) estimation: validate across model variants.

Estimates the size-severity exponent beta using five model specifications on
three data subsets (DENSE, FULL, BALANCED_K8).  Provides James-Stein shrinkage
for LoB-specific betas, temporal stability checks, influence diagnostics for
the largest syndicates, and cluster-robust standard errors (HC3).

Models
------
M0  No FE: s_i ~ a + beta * ln(R_i)                          (diagnostic)
M1  Event-FE OLS: s_i ~ a + beta * ln(R_i) + gamma_event     (main)
M2  log(|s_i| + eps) ~ a + b * log(R_i) + event FE           (abs deviation)
M3  log(s_i^2 + eps) ~ a + b * log(R_i) + event FE           (squared)
M4  Quantile regression Q_tau(s) ~ a + b * log(R) tau=0.90,0.95 (no FE, diagnostic)

Outputs
-------
fig/novelty3_loglog_scatter.png
    Binned median(|s|) vs R on log-log axes.
fig/novelty3_beta_comparison.png
    beta across model variants (bar chart).
fig/novelty3_lob_betas.png
    beta_ell raw vs shrunk (horizontal bar chart).
results/novelty3_size_validation.json
    Full results including temporal stability, influence, robustness.
"""

import sys
import json
import logging
import argparse
import warnings
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import statsmodels.api as sm

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
_this_dir = Path(__file__).resolve().parent
_stress_test_dir = _this_dir.parent  # scripts/stress_test
if str(_stress_test_dir) not in sys.path:
    sys.path.insert(0, str(_stress_test_dir))
if str(_this_dir) not in sys.path:
    sys.path.insert(0, str(_this_dir))

from common.analysis_table import (
    build_analysis_table,
    add_query_columns,
    get_subset,
    load_or_build,
    CoverageStats,
    compute_cap_binding_stats,
    audit_merge,
)
from common.severity_projection import (
    lob_weights_to_array,
    beta_lob_array,
    N_LOBS,
)
from common.query_portfolios import compute_market_average_mix
from config import LLOYDS_LOBS, LOB_TO_INDEX
from portfolio_size_adjustment import (
    DEFAULT_LOB_COEFFICIENTS,
    DEFAULT_REFERENCE_SIZE_M,
    DEFAULT_OVERALL_COEFFICIENT,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Output directories
# ---------------------------------------------------------------------------
FIG_DIR = _this_dir / "fig"
RESULTS_DIR = _this_dir / "results"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
EPS = 1e-6  # offset for log transforms
MIN_SYNDICATES_PER_EVENT = 3
TEMPORAL_PERIODS = {
    "2014-2016": (2014, 2016),
    "2017-2019": (2017, 2019),
    "2020-2023": (2020, 2023),
}
N_BINS_SCATTER = 15
TOP_K_LEVERAGE = 5


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_float(v: Any) -> Any:
    """Convert numpy scalars for JSON."""
    if isinstance(v, (np.floating, np.integer)):
        if isinstance(v, np.floating) and np.isnan(v):
            return None
        return float(v)
    if isinstance(v, np.ndarray):
        return v.tolist()
    if isinstance(v, float) and np.isnan(v):
        return None
    return v


def _json_default(obj: Any) -> Any:
    """Custom JSON encoder for numpy types and CoverageStats."""
    if isinstance(obj, (np.floating,)):
        if np.isnan(obj):
            return None
        return float(obj)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, CoverageStats):
        return obj.to_dict()
    if isinstance(obj, float) and np.isnan(obj):
        return None
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def _prepare_regression_df(df: pd.DataFrame) -> pd.DataFrame:
    """Filter to rows with valid R_s and build event groups.

    Returns DataFrame with columns: syndicate_id, year, cause_category,
    event_id, R_s, S_raw_a, S_raw_b, log_R, s_lob (ndarray), w_s_array.
    Only events with >= MIN_SYNDICATES_PER_EVENT syndicates are retained.
    """
    sub = df.dropna(subset=["R_s"]).copy()
    sub = sub[sub["R_s"] > 0].copy()

    # Rebuild event_id in case it needs refreshing
    sub["event_id"] = sub["year"].astype(str) + "_" + sub["cause_category"].astype(str)

    # Filter events by min syndicates
    ev_counts = sub.groupby("event_id")["syndicate_id"].nunique()
    valid_events = set(ev_counts[ev_counts >= MIN_SYNDICATES_PER_EVENT].index)
    sub = sub[sub["event_id"].isin(valid_events)].copy()

    sub["log_R"] = np.log(sub["R_s"].values)
    logger.info("Regression data: %d rows, %d events, %d syndicates",
                len(sub), sub["event_id"].nunique(), sub["syndicate_id"].nunique())
    return sub


# ---------------------------------------------------------------------------
# Model fitting
# ---------------------------------------------------------------------------

def _fit_m0(sub: pd.DataFrame, y_col: str = "S_raw_a") -> Dict[str, Any]:
    """M0: no FE — s ~ a + beta * ln(R)."""
    y = sub[y_col].values.astype(np.float64)
    X = sm.add_constant(sub["log_R"].values.astype(np.float64))
    mask = ~(np.isnan(y) | np.isnan(X).any(axis=1))
    if mask.sum() < 10:
        return {"beta": np.nan, "se": np.nan, "pvalue": np.nan, "n": int(mask.sum()), "r2": np.nan}
    model = _fit_with_robust_se(y[mask], X[mask], "x1")
    return {
        "beta": float(model.params[1]),
        "se": float(model.bse[1]),
        "pvalue": float(model.pvalues[1]),
        "n": int(mask.sum()),
        "r2": float(model.rsquared),
    }


def _fit_with_robust_se(y, X, param_name: str):
    """Fit OLS with HC3 SEs, falling back to HC1 if any leverage point = 1.

    HC3 divides by (1 - h_i)^2 which is undefined when a hat-matrix
    diagonal equals 1.  We check for this before requesting HC3 to avoid
    the RuntimeWarning entirely.
    """
    base = sm.OLS(y, X).fit()
    hat_diag = base.get_influence().hat_matrix_diag
    if np.any(hat_diag >= 1.0 - 1e-10):
        return sm.OLS(y, X).fit(cov_type="HC1")
    return sm.OLS(y, X).fit(cov_type="HC3")


def _fit_m1(sub: pd.DataFrame, y_col: str = "S_raw_a") -> Dict[str, Any]:
    """M1: event-FE OLS — s ~ a + beta * ln(R) + event dummies.  HC3 SEs (HC1 fallback)."""
    sub_clean = sub.dropna(subset=[y_col, "log_R"]).copy()
    if len(sub_clean) < 10 or sub_clean["event_id"].nunique() < 2:
        return {"beta": np.nan, "se": np.nan, "pvalue": np.nan, "n": len(sub_clean), "r2": np.nan}

    event_dummies = pd.get_dummies(
        sub_clean["event_id"].astype(str), prefix="ev", drop_first=True
    ).astype(np.float64)
    X = pd.concat([
        sub_clean[["log_R"]].reset_index(drop=True).astype(np.float64),
        event_dummies.reset_index(drop=True),
    ], axis=1)
    X = sm.add_constant(X)
    y = sub_clean[y_col].reset_index(drop=True).values.astype(np.float64)

    try:
        model = _fit_with_robust_se(y, X, "log_R")
        return {
            "beta": float(model.params["log_R"]),
            "se": float(model.bse["log_R"]),
            "pvalue": float(model.pvalues["log_R"]),
            "n": int(len(y)),
            "r2": float(model.rsquared),
        }
    except Exception as e:
        logger.warning("M1 fitting failed: %s", e)
        return {"beta": np.nan, "se": np.nan, "pvalue": np.nan, "n": len(sub_clean), "r2": np.nan}


def _fit_m2(sub: pd.DataFrame) -> Dict[str, Any]:
    """M2: log(|s| + eps) ~ a + b*log(R) + event FE."""
    sub_clean = sub.dropna(subset=["S_raw_a", "log_R"]).copy()
    if len(sub_clean) < 10 or sub_clean["event_id"].nunique() < 2:
        return {"beta": np.nan, "se": np.nan, "pvalue": np.nan, "n": len(sub_clean), "r2": np.nan}

    y_raw = sub_clean["S_raw_a"].values.astype(np.float64)
    y = np.log(np.abs(y_raw) + EPS)

    event_dummies = pd.get_dummies(
        sub_clean["event_id"].astype(str), prefix="ev", drop_first=True
    ).astype(np.float64)
    X = pd.concat([
        sub_clean[["log_R"]].reset_index(drop=True).astype(np.float64),
        event_dummies.reset_index(drop=True),
    ], axis=1)
    X = sm.add_constant(X)

    try:
        model = _fit_with_robust_se(y, X, "log_R")
        return {
            "beta": float(model.params["log_R"]),
            "se": float(model.bse["log_R"]),
            "pvalue": float(model.pvalues["log_R"]),
            "n": int(len(y)),
            "r2": float(model.rsquared),
        }
    except Exception as e:
        logger.warning("M2 fitting failed: %s", e)
        return {"beta": np.nan, "se": np.nan, "pvalue": np.nan, "n": len(sub_clean), "r2": np.nan}


def _fit_m3(sub: pd.DataFrame) -> Dict[str, Any]:
    """M3: log(s^2 + eps) ~ a + b*log(R) + event FE."""
    sub_clean = sub.dropna(subset=["S_raw_a", "log_R"]).copy()
    if len(sub_clean) < 10 or sub_clean["event_id"].nunique() < 2:
        return {"beta": np.nan, "se": np.nan, "pvalue": np.nan, "n": len(sub_clean), "r2": np.nan}

    y_raw = sub_clean["S_raw_a"].values.astype(np.float64)
    y = np.log(y_raw ** 2 + EPS)

    event_dummies = pd.get_dummies(
        sub_clean["event_id"].astype(str), prefix="ev", drop_first=True
    ).astype(np.float64)
    X = pd.concat([
        sub_clean[["log_R"]].reset_index(drop=True).astype(np.float64),
        event_dummies.reset_index(drop=True),
    ], axis=1)
    X = sm.add_constant(X)

    try:
        model = _fit_with_robust_se(y, X, "log_R")
        return {
            "beta": float(model.params["log_R"]),
            "se": float(model.bse["log_R"]),
            "pvalue": float(model.pvalues["log_R"]),
            "n": int(len(y)),
            "r2": float(model.rsquared),
        }
    except Exception as e:
        logger.warning("M3 fitting failed: %s", e)
        return {"beta": np.nan, "se": np.nan, "pvalue": np.nan, "n": len(sub_clean), "r2": np.nan}


def _fit_m4(sub: pd.DataFrame, taus: List[float] = None) -> Dict[str, Any]:
    """M4: quantile regression Q_tau(s) ~ a + b*log(R), no FE (diagnostic)."""
    from statsmodels.regression.quantile_regression import QuantReg

    if taus is None:
        taus = [0.90, 0.95]

    sub_clean = sub.dropna(subset=["S_raw_a", "log_R"]).copy()
    if len(sub_clean) < 10:
        return {f"tau_{t}": {"beta": np.nan, "se": np.nan, "pvalue": np.nan}
                for t in taus}

    # Center predictor for numerical stability in the simplex solver
    log_R_vals = sub_clean["log_R"].values.astype(np.float64)
    log_R_mean = np.mean(log_R_vals)
    X = sm.add_constant(log_R_vals - log_R_mean)
    y = sub_clean["S_raw_a"].values.astype(np.float64)
    results: Dict[str, Any] = {"n": len(sub_clean)}

    for tau in taus:
        try:
            model = QuantReg(y, X).fit(q=tau, max_iter=1000)
            results[f"tau_{tau}"] = {
                "beta": float(model.params[1]),
                "se": float(model.bse[1]),
                "pvalue": float(model.pvalues[1]),
            }
        except Exception as e:
            logger.warning("M4 tau=%.2f failed: %s", tau, e)
            results[f"tau_{tau}"] = {"beta": np.nan, "se": np.nan, "pvalue": np.nan}
    return results


# ---------------------------------------------------------------------------
# LoB-specific beta with James-Stein shrinkage
# ---------------------------------------------------------------------------

def _estimate_lob_betas(
    sub: pd.DataFrame,
    min_obs: int = 15,
) -> Dict[str, Any]:
    """Estimate per-LoB betas via within-event OLS, then apply James-Stein shrinkage.

    For each LoB l, collects observations where w_s_array[l] > 0.05 and
    regresses s_lob[l] ~ a + b*log(R) + event FE.

    Returns dict with raw_betas, raw_ses, shrunk_betas, shrinkage_lambdas,
    grand_mean, tau_sq.
    """
    raw_betas: Dict[str, float] = {}
    raw_ses: Dict[str, float] = {}

    for l_idx, lob_name in enumerate(LLOYDS_LOBS):
        # Select rows where this LoB has non-trivial weight
        mask = sub["w_s_array"].apply(lambda w: w[l_idx] > 0.05)
        lob_sub = sub.loc[mask].copy()
        if len(lob_sub) < min_obs or lob_sub["event_id"].nunique() < 2:
            continue

        # Extract LoB severity
        lob_sub["s_l"] = lob_sub["s_lob"].apply(lambda s: float(s[l_idx]))
        lob_clean = lob_sub.dropna(subset=["s_l", "log_R"])
        if len(lob_clean) < min_obs:
            continue

        event_dummies = pd.get_dummies(
            lob_clean["event_id"].astype(str), prefix="ev", drop_first=True
        ).astype(np.float64)
        X = pd.concat([
            lob_clean[["log_R"]].reset_index(drop=True).astype(np.float64),
            event_dummies.reset_index(drop=True),
        ], axis=1)
        X = sm.add_constant(X)
        y = lob_clean["s_l"].reset_index(drop=True).values.astype(np.float64)

        try:
            model = _fit_with_robust_se(y, X, "log_R")
            raw_betas[lob_name] = float(model.params["log_R"])
            raw_ses[lob_name] = float(model.bse["log_R"])
        except Exception as e:
            logger.debug("LoB %s beta estimation failed: %s", lob_name, e)

    if len(raw_betas) < 2:
        return {
            "raw_betas": raw_betas,
            "raw_ses": raw_ses,
            "shrunk_betas": raw_betas.copy(),
            "shrinkage_lambdas": {},
            "grand_mean": np.nan,
            "tau_sq": np.nan,
        }

    # Grand mean and between-LoB variance
    beta_vals = np.array(list(raw_betas.values()), dtype=np.float64)
    beta_bar = float(np.mean(beta_vals))
    tau_sq = float(np.var(beta_vals, ddof=1))

    # James-Stein shrinkage: lambda_l = tau^2 / (tau^2 + sigma_l^2)
    shrunk_betas: Dict[str, float] = {}
    lambdas: Dict[str, float] = {}
    for lob_name in raw_betas:
        sigma_sq_l = raw_ses[lob_name] ** 2
        denom = tau_sq + sigma_sq_l
        if denom > 0:
            lam = tau_sq / denom
        else:
            lam = 0.5
        lambdas[lob_name] = float(lam)
        shrunk_betas[lob_name] = float(lam * raw_betas[lob_name] + (1.0 - lam) * beta_bar)

    return {
        "raw_betas": {k: _safe_float(v) for k, v in raw_betas.items()},
        "raw_ses": {k: _safe_float(v) for k, v in raw_ses.items()},
        "shrunk_betas": {k: _safe_float(v) for k, v in shrunk_betas.items()},
        "shrinkage_lambdas": {k: _safe_float(v) for k, v in lambdas.items()},
        "grand_mean": _safe_float(beta_bar),
        "tau_sq": _safe_float(tau_sq),
    }


# ---------------------------------------------------------------------------
# Temporal stability
# ---------------------------------------------------------------------------

def _temporal_stability(sub: pd.DataFrame) -> Dict[str, Any]:
    """Re-estimate M1 on each temporal period."""
    results: Dict[str, Any] = {}
    for period_name, (y_start, y_end) in TEMPORAL_PERIODS.items():
        period_df = sub[(sub["year"] >= y_start) & (sub["year"] <= y_end)]
        if len(period_df) < 10:
            results[period_name] = {"beta": np.nan, "se": np.nan, "n": len(period_df)}
            continue
        m1 = _fit_m1(period_df, y_col="S_raw_a")
        results[period_name] = m1
    return results


# ---------------------------------------------------------------------------
# Influence diagnostics
# ---------------------------------------------------------------------------

def _influence_diagnostics(sub: pd.DataFrame) -> Dict[str, Any]:
    """Compute leverage of top-K largest syndicates (by median R_s).

    Leverage is defined as the hat-matrix diagonal from the M0 regression.
    Reports the average leverage for observations from each of the top-K
    syndicates, compared to the average leverage for all other observations.
    """
    sub_clean = sub.dropna(subset=["S_raw_a", "log_R"]).copy()
    if len(sub_clean) < 20:
        return {"top_syndicates": [], "avg_leverage_top": np.nan, "avg_leverage_rest": np.nan}

    # Identify top-K largest syndicates by median R_s
    median_R = sub_clean.groupby("syndicate_id")["R_s"].median().sort_values(ascending=False)
    top_synds = list(median_R.head(TOP_K_LEVERAGE).index)

    X = sm.add_constant(sub_clean["log_R"].values.astype(np.float64))
    y = sub_clean["S_raw_a"].values.astype(np.float64)

    try:
        model = sm.OLS(y, X).fit()
        hat_matrix_diag = model.get_influence().hat_matrix_diag
    except Exception as e:
        logger.warning("Influence diagnostics failed: %s", e)
        return {"top_syndicates": top_synds, "avg_leverage_top": np.nan, "avg_leverage_rest": np.nan}

    sub_clean = sub_clean.reset_index(drop=True)
    is_top = sub_clean["syndicate_id"].isin(top_synds).values
    avg_lev_top = float(np.mean(hat_matrix_diag[is_top])) if is_top.sum() > 0 else np.nan
    avg_lev_rest = float(np.mean(hat_matrix_diag[~is_top])) if (~is_top).sum() > 0 else np.nan

    top_details = []
    for synd in top_synds:
        synd_mask = (sub_clean["syndicate_id"] == synd).values
        n_obs = int(synd_mask.sum())
        median_r = float(median_R[synd])
        avg_lev = float(np.mean(hat_matrix_diag[synd_mask])) if n_obs > 0 else np.nan
        top_details.append({
            "syndicate_id": synd,
            "n_obs": n_obs,
            "median_R_s": median_r,
            "avg_leverage": avg_lev,
        })

    return {
        "top_syndicates": top_details,
        "avg_leverage_top": avg_lev_top,
        "avg_leverage_rest": avg_lev_rest,
    }


# ---------------------------------------------------------------------------
# Core analysis
# ---------------------------------------------------------------------------

def run_size_validation(df: pd.DataFrame) -> Dict[str, Any]:
    """Run all model variants on DENSE, FULL, BALANCED_K8 subsets.

    Returns structured results dict.
    """
    reg_df = _prepare_regression_df(df)

    subset_names = ["DENSE", "FULL", "BALANCED_K8"]
    model_results: Dict[str, Dict[str, Any]] = {}
    lob_betas_results: Dict[str, Any] = {}
    temporal_results: Dict[str, Any] = {}
    influence_results: Dict[str, Any] = {}
    coverage_stats: Dict[str, Any] = {}

    for sname in subset_names:
        sub_df, cov = get_subset(reg_df, sname)
        coverage_stats[sname] = cov.to_dict()
        n = len(sub_df)
        logger.info("Subset %s: %d rows, %d syndicates, %d events",
                     sname, n, sub_df["syndicate_id"].nunique(), sub_df["event_id"].nunique())

        if n < 10:
            logger.warning("Subset %s has too few rows (%d), skipping", sname, n)
            model_results[sname] = {}
            continue

        # Fit all models
        model_results[sname] = {
            "M0_no_fe": _fit_m0(sub_df, "S_raw_a"),
            "M1_event_fe": _fit_m1(sub_df, "S_raw_a"),
            "M2_log_abs": _fit_m2(sub_df),
            "M3_log_sq": _fit_m3(sub_df),
            "M4_quantile": _fit_m4(sub_df),
        }

        # LoB-specific betas (on this subset)
        lob_betas_results[sname] = _estimate_lob_betas(sub_df)

    # Temporal stability on FULL
    full_df, _ = get_subset(reg_df, "FULL")
    temporal_results = _temporal_stability(full_df)

    # Influence diagnostics on FULL
    influence_results = _influence_diagnostics(full_df)

    # Sanity check: beta should be negative and in [-0.6, 0.0] on DENSE
    sanity = _sanity_check(model_results)

    return {
        "model_results": model_results,
        "lob_betas": lob_betas_results,
        "temporal_stability": temporal_results,
        "influence_diagnostics": influence_results,
        "coverage": coverage_stats,
        "sanity_check": sanity,
        "_regression_df": reg_df,  # for plotting (not serialised)
    }


def _sanity_check(model_results: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Assert M1 beta on DENSE is negative and in [-0.7, 0.0].

    The band is deliberately wide — this is a plausible-magnitude check,
    not a precise statistical test.
    """
    dense = model_results.get("DENSE", {})
    m1 = dense.get("M1_event_fe", {})
    beta = m1.get("beta", np.nan)
    passed = False
    message = "DENSE M1 beta not available"
    if beta is not None and not (isinstance(beta, float) and np.isnan(beta)):
        if -0.7 <= beta <= 0.0:
            passed = True
            message = f"PASS: DENSE M1 beta = {beta:.4f} in [-0.7, 0.0]"
        else:
            message = f"FAIL: DENSE M1 beta = {beta:.4f} outside [-0.7, 0.0]"
    logger.info("Sanity check: %s", message)
    return {"passed": passed, "beta": _safe_float(beta), "message": message}


# ---------------------------------------------------------------------------
# Plotting
# ---------------------------------------------------------------------------

def plot_loglog_scatter(
    reg_df: pd.DataFrame,
    output_path: Path,
) -> None:
    """Binned median(|s|) vs R on log-log axes."""
    sub = reg_df.dropna(subset=["S_raw_a", "R_s"]).copy()
    if len(sub) == 0:
        logger.warning("No data for log-log scatter plot")
        return

    sub["abs_s"] = np.abs(sub["S_raw_a"])
    # Create log-spaced bins for R_s
    r_min, r_max = sub["R_s"].min(), sub["R_s"].max()
    if r_min <= 0:
        r_min = sub.loc[sub["R_s"] > 0, "R_s"].min()
    bin_edges = np.logspace(np.log10(max(r_min, 1.0)), np.log10(r_max), N_BINS_SCATTER + 1)
    sub["R_bin"] = pd.cut(sub["R_s"], bins=bin_edges, labels=False)

    binned = sub.groupby("R_bin").agg(
        median_abs_s=("abs_s", "median"),
        median_R=("R_s", "median"),
        n=("abs_s", "count"),
    ).dropna()
    binned = binned[binned["n"] >= 5]

    if len(binned) < 3:
        logger.warning("Too few bins for log-log scatter")
        return

    fig, ax = plt.subplots(figsize=(8, 6))
    ax.scatter(
        binned["median_R"], binned["median_abs_s"],
        s=np.clip(binned["n"].values * 2, 20, 200),
        alpha=0.7, edgecolors="k", linewidths=0.5,
        c="#1f77b4", label="Binned median |s|",
    )

    # OLS fit on log-log (exclude bins where median |s| = 0)
    pos_mask = binned["median_abs_s"].values > 0
    log_R = np.log(binned["median_R"].values[pos_mask])
    log_s = np.log(binned["median_abs_s"].values[pos_mask])
    valid = np.isfinite(log_R) & np.isfinite(log_s)
    if valid.sum() >= 3:
        X_fit = sm.add_constant(log_R[valid])
        ols = sm.OLS(log_s[valid], X_fit).fit()
        R_line = np.logspace(np.log10(binned["median_R"].min()), np.log10(binned["median_R"].max()), 50)
        s_line = np.exp(ols.params[0]) * R_line ** ols.params[1]
        ax.plot(R_line, s_line, "r--", linewidth=1.5,
                label=f"OLS: slope = {ols.params[1]:.3f}")

    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("Reserve Base R (GBP m, log scale)")
    ax.set_ylabel("Median |Severity| (log scale)")
    ax.set_title("Size-Severity Relationship: Binned Median |s| vs R")
    ax.legend(fontsize=9)
    ax.grid(True, alpha=0.3, which="both")
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(str(output_path), dpi=150)
    plt.close(fig)
    logger.info("Saved %s", output_path)


def plot_beta_comparison(
    model_results: Dict[str, Dict[str, Any]],
    output_path: Path,
) -> None:
    """Bar chart of beta across model variants and subsets."""
    subsets = ["DENSE", "FULL", "BALANCED_K8"]
    models_to_plot = ["M0_no_fe", "M1_event_fe", "M2_log_abs", "M3_log_sq"]
    model_labels = ["M0: No FE", "M1: Event FE", "M2: log|s|", "M3: log(s^2)"]
    colors = ["#d62728", "#1f77b4", "#2ca02c", "#9467bd"]

    fig, ax = plt.subplots(figsize=(10, 5))
    n_models = len(models_to_plot)
    n_subsets = len(subsets)
    bar_width = 0.18
    x = np.arange(n_subsets)

    for i, (model_key, label) in enumerate(zip(models_to_plot, model_labels)):
        betas = []
        ses = []
        for sname in subsets:
            m = model_results.get(sname, {}).get(model_key, {})
            b = m.get("beta", np.nan)
            s = m.get("se", np.nan)
            betas.append(b if b is not None else np.nan)
            ses.append(s if s is not None else np.nan)

        betas = np.array(betas, dtype=np.float64)
        ses = np.array(ses, dtype=np.float64)
        offset = (i - n_models / 2 + 0.5) * bar_width

        ax.bar(x + offset, betas, bar_width, yerr=ses, label=label,
               color=colors[i], alpha=0.8, capsize=3, edgecolor="k", linewidth=0.5)

    ax.axhline(0, color="grey", linestyle="--", linewidth=0.8)
    ax.set_xticks(x)
    ax.set_xticklabels(subsets)
    ax.set_ylabel("Beta (size-severity exponent)")
    ax.set_title("Size-Severity Beta Across Model Variants and Subsets")
    ax.legend(fontsize=8, ncol=2)
    ax.grid(True, axis="y", alpha=0.3)
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(str(output_path), dpi=150)
    plt.close(fig)
    logger.info("Saved %s", output_path)


def plot_lob_betas(
    lob_betas: Dict[str, Any],
    subset_name: str,
    output_path: Path,
) -> None:
    """Horizontal bar chart of LoB betas: raw vs shrunk."""
    data = lob_betas.get(subset_name, {})
    raw = data.get("raw_betas", {})
    shrunk = data.get("shrunk_betas", {})
    raw_se = data.get("raw_ses", {})

    if not raw:
        logger.warning("No LoB betas to plot for %s", subset_name)
        return

    # Sort by shrunk beta
    lobs_sorted = sorted(shrunk.keys(), key=lambda l: shrunk.get(l, 0))

    fig, ax = plt.subplots(figsize=(9, max(5, len(lobs_sorted) * 0.45)))
    y_pos = np.arange(len(lobs_sorted))
    bar_height = 0.35

    raw_vals = [raw.get(l, np.nan) for l in lobs_sorted]
    shrunk_vals = [shrunk.get(l, np.nan) for l in lobs_sorted]
    raw_errs = [raw_se.get(l, 0.0) for l in lobs_sorted]

    ax.barh(y_pos + bar_height / 2, raw_vals, bar_height, xerr=raw_errs,
            label="Raw OLS", color="#d62728", alpha=0.7, capsize=2, edgecolor="k", linewidth=0.3)
    ax.barh(y_pos - bar_height / 2, shrunk_vals, bar_height,
            label="James-Stein Shrunk", color="#1f77b4", alpha=0.7, edgecolor="k", linewidth=0.3)

    ax.axvline(0, color="grey", linestyle="--", linewidth=0.8)
    grand_mean = data.get("grand_mean")
    if grand_mean is not None and not (isinstance(grand_mean, float) and np.isnan(grand_mean)):
        ax.axvline(grand_mean, color="green", linestyle=":", linewidth=1.2,
                    label=f"Grand mean = {grand_mean:.3f}")

    ax.set_yticks(y_pos)
    ax.set_yticklabels(lobs_sorted, fontsize=8)
    ax.set_xlabel("Beta (size-severity exponent)")
    ax.set_title(f"LoB-Specific Betas: Raw vs Shrunk ({subset_name})")
    ax.legend(fontsize=8, loc="lower right")
    ax.grid(True, axis="x", alpha=0.3)
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(str(output_path), dpi=150)
    plt.close(fig)
    logger.info("Saved %s", output_path)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Novelty 3: size-severity beta validation across model variants."
    )
    parser.add_argument(
        "--cache", default=None,
        help="Path to analysis table pickle cache.",
    )
    parser.add_argument(
        "--log-level", default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    # ------------------------------------------------------------------
    # 1. Load / build analysis table
    # ------------------------------------------------------------------
    logger.info("Loading analysis table ...")
    df = load_or_build(cache_path=args.cache)
    audit_merge(df)

    # ------------------------------------------------------------------
    # 2. Run size validation
    # ------------------------------------------------------------------
    results = run_size_validation(df)

    # Extract for plotting
    reg_df = results.pop("_regression_df")
    model_results = results["model_results"]
    lob_betas = results["lob_betas"]

    # ------------------------------------------------------------------
    # 3. Plots
    # ------------------------------------------------------------------
    plot_loglog_scatter(reg_df, FIG_DIR / "novelty3_loglog_scatter.png")
    plot_beta_comparison(model_results, FIG_DIR / "novelty3_beta_comparison.png")

    # LoB betas plot: prefer FULL, fall back to DENSE
    lob_plot_subset = "FULL" if "FULL" in lob_betas and lob_betas["FULL"].get("raw_betas") else "DENSE"
    plot_lob_betas(lob_betas, lob_plot_subset, FIG_DIR / "novelty3_lob_betas.png")

    # ------------------------------------------------------------------
    # 4. JSON output
    # ------------------------------------------------------------------
    output = {
        "description": (
            "Novelty 3: size-severity beta validation. Estimates beta across "
            "five model variants (M0-M4) on three subsets (DENSE, FULL, BALANCED_K8). "
            "Includes James-Stein shrinkage for LoB-specific betas, temporal stability, "
            "and influence diagnostics."
        ),
        "model_results": results["model_results"],
        "lob_betas": results["lob_betas"],
        "temporal_stability": results["temporal_stability"],
        "influence_diagnostics": results["influence_diagnostics"],
        "coverage": results["coverage"],
        "sanity_check": results["sanity_check"],
    }

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RESULTS_DIR / "novelty3_size_validation.json"
    with open(str(out_path), "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, default=_json_default)
    logger.info("Results written to %s", out_path)

    # ------------------------------------------------------------------
    # 5. Summary to console
    # ------------------------------------------------------------------
    print("\n=== Novelty 3: Size-Severity Beta Validation ===")
    for sname in ["DENSE", "FULL", "BALANCED_K8"]:
        m1 = model_results.get(sname, {}).get("M1_event_fe", {})
        b = m1.get("beta", "N/A")
        se = m1.get("se", "N/A")
        n = m1.get("n", "N/A")
        b_str = f"{b:.4f}" if isinstance(b, (int, float)) and not np.isnan(b) else str(b)
        se_str = f"{se:.4f}" if isinstance(se, (int, float)) and not np.isnan(se) else str(se)
        print(f"  {sname:15s}  M1 beta = {b_str} (se={se_str}, n={n})")

    sc = results["sanity_check"]
    print(f"\nSanity check: {sc['message']}")

    print(f"\nTemporal stability (M1 beta by period):")
    for period, pres in results["temporal_stability"].items():
        b = pres.get("beta", np.nan)
        b_str = f"{b:.4f}" if isinstance(b, (int, float)) and not np.isnan(b) else "N/A"
        print(f"  {period}: beta = {b_str}")

    print(f"\nOutputs: {FIG_DIR / 'novelty3_loglog_scatter.png'}")
    print(f"         {FIG_DIR / 'novelty3_beta_comparison.png'}")
    print(f"         {FIG_DIR / 'novelty3_lob_betas.png'}")
    print(f"         {out_path}")


if __name__ == "__main__":
    main()
