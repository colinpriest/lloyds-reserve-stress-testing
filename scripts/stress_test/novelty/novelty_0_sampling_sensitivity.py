"""Novelty 0 — Leave-p-out sampling sensitivity analysis.

Shows that headline results (tail trend, beta estimate, VaR) are not driven
by which syndicates happened to be sampled.  Repeatedly drops a random 10% of
syndicates and recomputes the three key metrics, then reports how much each
metric varies across resamples.

Stability criterion: sd(metric) < 30% of |point estimate|.

Outputs
-------
results/novelty0_sampling_sensitivity.json
    Per-metric distribution (mean, sd, p5, p95, point, stable flag).
fig/novelty0_sensitivity_histograms.png
    Three-panel histogram of resampled metric distributions.
"""

import sys
import json
import argparse
import logging
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

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
)
from common.severity_projection import lob_weights_to_array, N_LOBS
from common.tail_metrics import empirical_var
from common.time_windows import year_summary_stats, ols_trend
from common.query_portfolios import compute_market_average_mix

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Output directories (relative to novelty/)
# ---------------------------------------------------------------------------
_FIG_DIR = _this_dir / "fig"
_RESULTS_DIR = _this_dir / "results"


# ---------------------------------------------------------------------------
# Metric computation helpers
# ---------------------------------------------------------------------------

def _p95_trend_slope(df: pd.DataFrame, severity_col: str) -> float:
    """OLS slope of yearly p95 of *severity_col* vs year."""
    ystats = year_summary_stats(df, severity_col)
    if len(ystats) < 3 or "p95" not in ystats.columns:
        return np.nan
    years = np.array(ystats.index, dtype=np.float64)
    p95_vals = ystats["p95"].values.astype(np.float64)
    slope, _intercept, _se, _p = ols_trend(years, p95_vals)
    return slope


def _overall_beta(df: pd.DataFrame) -> float:
    """Simple OLS: S_raw_a ~ intercept + beta * log(R_s).

    Returns the slope coefficient (beta).
    """
    sub = df.dropna(subset=["S_raw_a", "R_s"]).copy()
    sub = sub[sub["R_s"] > 0]
    if len(sub) < 5:
        return np.nan
    import statsmodels.api as sm
    X = sm.add_constant(np.log(sub["R_s"].values))
    y = sub["S_raw_a"].values.astype(np.float64)
    try:
        model = sm.OLS(y, X).fit()
        return float(model.params[1])
    except Exception:
        return np.nan


def _var_995(df: pd.DataFrame, severity_col: str) -> float:
    """Empirical VaR at 99.5% of severity_col."""
    vals = df[severity_col].dropna().values
    return empirical_var(vals, 0.995)


# ---------------------------------------------------------------------------
# Leave-p-out resampling engine
# ---------------------------------------------------------------------------

def leave_p_out_resampling(
    df: pd.DataFrame,
    severity_col: str,
    n_iter: int = 200,
    drop_frac: float = 0.10,
    seed: int = 42,
) -> Dict[str, np.ndarray]:
    """Run leave-p-out resampling over syndicates.

    Parameters
    ----------
    df : analysis table with query columns already added
    severity_col : standardised severity column (e.g. S_std_market_avg)
    n_iter : number of resamples
    drop_frac : fraction of syndicates to drop each time
    seed : random seed

    Returns
    -------
    dict with keys 'p95_slope', 'beta', 'var995', each an ndarray[n_iter].
    """
    rng = np.random.default_rng(seed)
    syndicates = df["syndicate_id"].unique()
    n_drop = max(1, int(len(syndicates) * drop_frac))

    slopes = np.empty(n_iter)
    betas = np.empty(n_iter)
    vars_ = np.empty(n_iter)

    for i in range(n_iter):
        drop_ids = rng.choice(syndicates, size=n_drop, replace=False)
        sub = df[~df["syndicate_id"].isin(drop_ids)]
        slopes[i] = _p95_trend_slope(sub, severity_col)
        betas[i] = _overall_beta(sub)
        vars_[i] = _var_995(sub, severity_col)

    return {"p95_slope": slopes, "beta": betas, "var995": vars_}


# ---------------------------------------------------------------------------
# Stability assessment
# ---------------------------------------------------------------------------

def _summarise_metric(
    samples: np.ndarray, point: float, name: str, threshold: float = 0.30
) -> Dict[str, Any]:
    """Summarise bootstrap distribution and assess stability."""
    clean = samples[~np.isnan(samples)]
    if len(clean) == 0:
        return {
            "name": name,
            "point": None,
            "mean": None,
            "sd": None,
            "p5": None,
            "p95": None,
            "stable": False,
            "ratio_sd_point": None,
            "n_valid": 0,
        }
    sd = float(np.std(clean, ddof=1))
    abs_point = abs(point) if point != 0 else 1e-12
    ratio = sd / abs_point
    return {
        "name": name,
        "point": float(point),
        "mean": float(np.mean(clean)),
        "sd": sd,
        "p5": float(np.percentile(clean, 5)),
        "p95": float(np.percentile(clean, 95)),
        "stable": bool(ratio < threshold),
        "ratio_sd_point": float(ratio),
        "n_valid": int(len(clean)),
    }


# ---------------------------------------------------------------------------
# Plotting
# ---------------------------------------------------------------------------

def _plot_histograms(
    results: Dict[str, np.ndarray],
    point_estimates: Dict[str, float],
    output_path: Path,
) -> None:
    """Three-panel histogram of resampled metric distributions."""
    fig, axes = plt.subplots(1, 3, figsize=(14, 4.5))

    labels = {
        "p95_slope": "p95 Trend Slope (per year)",
        "beta": r"Overall $\beta$ (S_raw_a ~ log R_s)",
        "var995": "VaR 99.5% of S_std",
    }
    colours = {
        "p95_slope": "#3366CC",
        "beta": "#DC3912",
        "var995": "#FF9900",
    }

    for ax, key in zip(axes, ["p95_slope", "beta", "var995"]):
        samples = results[key]
        clean = samples[~np.isnan(samples)]
        if len(clean) == 0:
            ax.set_title(labels[key])
            ax.text(0.5, 0.5, "No valid samples", ha="center", va="center",
                    transform=ax.transAxes)
            continue

        ax.hist(clean, bins=30, color=colours[key], alpha=0.75, edgecolor="white",
                linewidth=0.5)
        point_val = point_estimates[key]
        if np.isfinite(point_val):
            ax.axvline(point_val, color="black", linestyle="--", linewidth=1.5,
                       label=f"Point = {point_val:.4f}")
        mean_val = np.mean(clean)
        ax.axvline(mean_val, color="grey", linestyle=":", linewidth=1.2,
                   label=f"Mean = {mean_val:.4f}")
        ax.set_xlabel(labels[key], fontsize=9)
        ax.set_ylabel("Count", fontsize=9)
        ax.set_title(labels[key], fontsize=10, fontweight="bold")
        ax.legend(fontsize=7, loc="upper right")
        ax.tick_params(labelsize=8)

    fig.suptitle(
        "Novelty 0: Leave-10%-Out Sampling Sensitivity (200 resamples)",
        fontsize=12, fontweight="bold", y=1.02,
    )
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(str(output_path), dpi=200, bbox_inches="tight")
    plt.close(fig)
    logger.info("Saved histogram figure to %s", output_path)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(
    n_iter: int = 200,
    drop_frac: float = 0.10,
    seed: int = 42,
    subset: str = "DENSE",
    cache_path: str | None = None,
) -> Dict[str, Any]:
    """Execute the full sampling sensitivity analysis.

    Returns the JSON-serialisable result dict.
    """
    # 1. Load / build analysis table
    logger.info("Building analysis table ...")
    df = load_or_build(cache_path=cache_path)

    # 2. Representative query portfolio: market_avg at 500m
    w_q_dict = compute_market_average_mix(df, "dense")
    w_q_array = lob_weights_to_array(w_q_dict)
    total_w = w_q_array.sum()
    if total_w > 0:
        w_q_array = w_q_array / total_w
    df = add_query_columns(df, w_q_array, 500.0, "market_avg")

    severity_col = "S_std_market_avg"

    # 3. Take subset
    sub_df, cov_stats = get_subset(df, subset)
    logger.info(
        "Subset %s: %d observations, %d syndicates",
        subset, cov_stats.n_observations, cov_stats.n_syndicates,
    )

    # 4. Point estimates on full subset
    point_slope = _p95_trend_slope(sub_df, severity_col)
    point_beta = _overall_beta(sub_df)
    point_var = _var_995(sub_df, severity_col)
    point_estimates = {
        "p95_slope": point_slope,
        "beta": point_beta,
        "var995": point_var,
    }
    logger.info(
        "Point estimates — slope=%.5f, beta=%.5f, var995=%.5f",
        point_slope, point_beta, point_var,
    )

    # 5. Leave-p-out resampling
    logger.info("Running %d leave-%.0f%%-out resamples ...", n_iter, drop_frac * 100)
    resampled = leave_p_out_resampling(
        sub_df, severity_col, n_iter=n_iter, drop_frac=drop_frac, seed=seed,
    )

    # 6. Summarise
    summaries = {}
    for key in ["p95_slope", "beta", "var995"]:
        summaries[key] = _summarise_metric(
            resampled[key], point_estimates[key], key
        )
    all_stable = all(s["stable"] for s in summaries.values())

    # 7. Assemble output
    output = {
        "analysis": "novelty_0_sampling_sensitivity",
        "subset": subset,
        "n_iter": n_iter,
        "drop_frac": drop_frac,
        "seed": seed,
        "coverage": cov_stats.to_dict(),
        "point_estimates": {k: float(v) if np.isfinite(v) else None
                           for k, v in point_estimates.items()},
        "metrics": summaries,
        "all_stable": all_stable,
        "stability_threshold": 0.30,
        "query_portfolio": {
            "mix": w_q_dict,
            "size_m": 500.0,
        },
    }

    # 8. Write JSON
    _RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    json_path = _RESULTS_DIR / "novelty0_sampling_sensitivity.json"
    with open(str(json_path), "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, default=str)
    logger.info("Results written to %s", json_path)

    # 9. Plot
    _FIG_DIR.mkdir(parents=True, exist_ok=True)
    fig_path = _FIG_DIR / "novelty0_sensitivity_histograms.png"
    _plot_histograms(resampled, point_estimates, fig_path)

    return output


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Novelty 0: Leave-p-out sampling sensitivity analysis",
    )
    parser.add_argument(
        "--n-iter", type=int, default=200,
        help="Number of leave-p-out resamples (default 200)",
    )
    parser.add_argument(
        "--drop-frac", type=float, default=0.10,
        help="Fraction of syndicates to drop per resample (default 0.10)",
    )
    parser.add_argument(
        "--seed", type=int, default=42,
        help="Random seed (default 42)",
    )
    parser.add_argument(
        "--subset", type=str, default="DENSE",
        choices=["DENSE", "MID", "FULL", "BALANCED_K8", "BALANCED_K6", "BALANCED_ALL"],
        help="Subset to analyse (default DENSE)",
    )
    parser.add_argument(
        "--cache", type=str, default=None,
        help="Path to analysis table pickle cache",
    )
    parser.add_argument(
        "--log-level", type=str, default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level (default INFO)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    result = run(
        n_iter=args.n_iter,
        drop_frac=args.drop_frac,
        seed=args.seed,
        subset=args.subset,
        cache_path=args.cache,
    )

    stable_tag = "STABLE" if result["all_stable"] else "UNSTABLE"
    logger.info("Sampling sensitivity: %s", stable_tag)
    for key, summary in result["metrics"].items():
        logger.info(
            "  %-12s point=%.5f  mean=%.5f  sd=%.5f  [p5=%.5f, p95=%.5f]  %s",
            key,
            summary["point"] or 0.0,
            summary["mean"] or 0.0,
            summary["sd"] or 0.0,
            summary["p5"] or 0.0,
            summary["p95"] or 0.0,
            "OK" if summary["stable"] else "WARN",
        )


if __name__ == "__main__":
    main()
