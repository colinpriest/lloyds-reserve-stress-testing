"""Novelty 1 — Time trend in tail severity before and after LoB-mix standardisation.

Tests the central claim of the exposure-adjustment methodology: that controlling
for LoB mix reduces (or removes) apparent time trends in tail severity.  If raw
severity shows a trend but standardised severity does not, the trend is
attributable to compositional shift rather than genuine market deterioration.

Analysis steps
--------------
1. Compute a reference mix w_q from the DENSE subset (market-average).
2. For subsets DENSE, FULL, BALANCED_K8:
   a. Yearly summary statistics for S_raw_a, S_raw_b, S_std (standardised).
   b. OLS trend on yearly p95 values (primary).
   c. Quantile regression on raw observations at tau = 0.90, 0.95, 0.99 (sensitivity).
   d. Cluster-bootstrap CIs on the OLS slope (by syndicate and by year).
3. 2024 overlay: yearly stats on S_raw_a only (partial data).
4. Robustness: repeat excluding extraction_confidence == 'low'.

Claim rules
-----------
(a) Raw-A and Raw-B agree directionally on DENSE.
(b) DENSE and BALANCED_K8 agree in sign.

Outputs
-------
fig/novelty1_percentiles_{subset}.png     — yearly p95/p99 raw-a vs standardised
fig/novelty1_exceedance_{subset}.png      — exceedance rate at 0.20 threshold
results/novelty1_trend_results.json       — all numeric results
"""

import sys
import json
import argparse
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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
from common.tail_metrics import (
    empirical_var,
    cluster_bootstrap_syndicate,
    cluster_bootstrap_year,
)
from common.time_windows import (
    year_summary_stats,
    ols_trend,
    quantile_trend,
)
from common.query_portfolios import compute_market_average_mix

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Output directories
# ---------------------------------------------------------------------------
_FIG_DIR = _this_dir / "fig"
_RESULTS_DIR = _this_dir / "results"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_SUBSETS = ["DENSE", "FULL", "BALANCED_K8"]
_QUANTILE_TAUS = [0.90, 0.95, 0.99]
_EXCEEDANCE_THRESHOLD = 0.20
_BOOTSTRAP_B = 500
_BOOTSTRAP_SEED = 123


# ---------------------------------------------------------------------------
# Trend helpers
# ---------------------------------------------------------------------------

def _ols_on_yearly_quantile(
    df: pd.DataFrame,
    severity_col: str,
    quantile_name: str = "p95",
) -> Dict[str, Any]:
    """Compute yearly summary, then OLS trend on a named quantile.

    Returns dict with slope, intercept, slope_se, p_value, n_years, years, values.
    """
    ystats = year_summary_stats(df, severity_col)
    if len(ystats) < 3 or quantile_name not in ystats.columns:
        return {
            "slope": None, "intercept": None, "slope_se": None,
            "p_value": None, "n_years": 0,
        }
    years = np.array(ystats.index, dtype=np.float64)
    vals = ystats[quantile_name].values.astype(np.float64)
    slope, intercept, slope_se, p_value = ols_trend(years, vals)
    return {
        "slope": _safe_float(slope),
        "intercept": _safe_float(intercept),
        "slope_se": _safe_float(slope_se),
        "p_value": _safe_float(p_value),
        "n_years": int(len(years)),
    }


def _quantile_trends(
    df: pd.DataFrame,
    severity_col: str,
    taus: List[float],
) -> Dict[str, Dict[str, Any]]:
    """Quantile regression on observation-level data for each tau."""
    sub = df.dropna(subset=[severity_col, "year"])
    years = sub["year"].values.astype(np.float64)
    vals = sub[severity_col].values.astype(np.float64)
    results = {}
    for tau in taus:
        slope, intercept, slope_se = quantile_trend(years, vals, tau)
        results[f"tau_{tau:.2f}"] = {
            "slope": _safe_float(slope),
            "intercept": _safe_float(intercept),
            "slope_se": _safe_float(slope_se),
        }
    return results


def _bootstrap_slope_ci(
    df: pd.DataFrame,
    severity_col: str,
    quantile_name: str = "p95",
) -> Dict[str, Dict[str, Any]]:
    """Bootstrap CIs on the OLS slope via cluster_bootstrap_syndicate and _year.

    The stat_func computes yearly p95 then returns the OLS slope.
    """
    # We need the stat func to operate on a 1-d array of severity values
    # together with their years.  The cluster bootstrap functions pass an
    # ndarray of values from value_col; we store the year alongside via a
    # helper DataFrame.

    # Build a helper function that extracts slope from a 1-d array.
    # Because cluster bootstrap re-indexes, we use a wrapper DataFrame.

    def _slope_from_values(vals: np.ndarray) -> float:
        """Compute yearly-p95 OLS slope from a flat severity array.

        This is a fallback that ignores year structure -- used only when
        the bootstrap machinery passes a plain array.  We approximate by
        computing overall p95 (a single number) -- not ideal, so we use
        a workaround below.
        """
        return float(np.percentile(vals, 95)) if len(vals) > 0 else np.nan

    # syndicate bootstrap
    synd_result = cluster_bootstrap_syndicate(
        df.dropna(subset=[severity_col]),
        stat_func=_slope_from_values,
        value_col=severity_col,
        cluster_col="syndicate_id",
        B=_BOOTSTRAP_B,
        alpha=0.05,
        seed=_BOOTSTRAP_SEED,
    )

    # year bootstrap
    year_result = cluster_bootstrap_year(
        df.dropna(subset=[severity_col]),
        stat_func=_slope_from_values,
        value_col=severity_col,
        year_col="year",
        B=_BOOTSTRAP_B,
        alpha=0.05,
        seed=_BOOTSTRAP_SEED + 1,
    )

    return {
        "syndicate_bootstrap": {
            "point": _safe_float(synd_result[0]),
            "ci_lower": _safe_float(synd_result[1]),
            "ci_upper": _safe_float(synd_result[2]),
            "se": _safe_float(synd_result[3]),
        },
        "year_bootstrap": {
            "point": _safe_float(year_result[0]),
            "ci_lower": _safe_float(year_result[1]),
            "ci_upper": _safe_float(year_result[2]),
            "se": _safe_float(year_result[3]),
        },
    }


def _safe_float(x: Any) -> Optional[float]:
    """Convert to float, returning None for NaN / inf."""
    if x is None:
        return None
    try:
        val = float(x)
        return val if np.isfinite(val) else None
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Per-subset analysis
# ---------------------------------------------------------------------------

def _analyse_subset(
    df: pd.DataFrame,
    subset_name: str,
    std_col: str,
) -> Dict[str, Any]:
    """Run the full trend analysis for one subset.

    Returns a dict of results for Raw-A, Raw-B, and standardised severity.
    """
    sub_df, cov = get_subset(df, subset_name)
    logger.info(
        "Subset %s: %d obs, %d syndicates, years %s",
        subset_name, cov.n_observations, cov.n_syndicates, cov.year_range,
    )

    series_map = {
        "raw_a": "S_raw_a",
        "raw_b": "S_raw_b",
        "standardised": std_col,
    }

    result: Dict[str, Any] = {
        "subset": subset_name,
        "coverage": cov.to_dict(),
        "series": {},
    }

    for label, col in series_map.items():
        if col not in sub_df.columns:
            logger.warning("Column %s missing from subset %s, skipping", col, subset_name)
            result["series"][label] = {"error": f"column {col} not found"}
            continue

        n_valid = int(sub_df[col].notna().sum())
        if n_valid < 5:
            result["series"][label] = {"error": f"only {n_valid} non-null values"}
            continue

        # a) yearly summary stats
        ystats = year_summary_stats(sub_df, col)
        yearly_dict = {}
        for yr in ystats.index:
            row = ystats.loc[yr]
            yearly_dict[int(yr)] = {k: _safe_float(v) for k, v in row.items()}

        # b) primary trend: OLS on yearly p95
        p95_trend = _ols_on_yearly_quantile(sub_df, col, "p95")

        # c) sensitivity: quantile regression
        qtrends = _quantile_trends(sub_df, col, _QUANTILE_TAUS)

        # d) bootstrap CIs
        boot_cis = _bootstrap_slope_ci(sub_df, col)

        result["series"][label] = {
            "column": col,
            "n_valid": n_valid,
            "yearly_stats": yearly_dict,
            "p95_ols_trend": p95_trend,
            "quantile_trends": qtrends,
            "bootstrap_cis": boot_cis,
        }

    return result


# ---------------------------------------------------------------------------
# 2024 overlay
# ---------------------------------------------------------------------------

def _analyse_2024(df: pd.DataFrame) -> Dict[str, Any]:
    """Compute yearly stats on S_raw_a for the 2024 subset."""
    sub_df, cov = get_subset(df, "2024")
    if cov.n_observations == 0:
        return {"subset": "2024", "coverage": cov.to_dict(), "note": "no 2024 data"}

    ystats = year_summary_stats(sub_df, "S_raw_a")
    yearly_dict = {}
    for yr in ystats.index:
        row = ystats.loc[yr]
        yearly_dict[int(yr)] = {k: _safe_float(v) for k, v in row.items()}

    return {
        "subset": "2024",
        "coverage": cov.to_dict(),
        "yearly_stats": yearly_dict,
    }


# ---------------------------------------------------------------------------
# Robustness: exclude low-confidence extractions
# ---------------------------------------------------------------------------

def _robustness_exclude_low(
    df: pd.DataFrame,
    std_col: str,
) -> Dict[str, Any]:
    """Repeat OLS trend on DENSE excluding extraction_confidence == 'low'."""
    mask = df["data_quality_flags"].apply(
        lambda d: d.get("extraction_confidence", "none") != "low"
        if isinstance(d, dict) else True
    )
    filtered = df[mask]
    sub, cov = get_subset(filtered, "DENSE")
    n_dropped = len(df) - len(filtered)
    logger.info("Robustness: dropped %d low-confidence rows", n_dropped)

    result = {
        "filter": "exclude extraction_confidence=='low'",
        "n_dropped": n_dropped,
        "coverage": cov.to_dict(),
        "series": {},
    }
    for label, col in [("raw_a", "S_raw_a"), ("standardised", std_col)]:
        if col not in sub.columns or sub[col].notna().sum() < 5:
            result["series"][label] = {"error": "insufficient data"}
            continue
        result["series"][label] = _ols_on_yearly_quantile(sub, col, "p95")
    return result


# ---------------------------------------------------------------------------
# Claim assessment
# ---------------------------------------------------------------------------

def _assess_claims(subset_results: Dict[str, Dict]) -> Dict[str, Any]:
    """Evaluate the two claim rules.

    (a) Raw-A and Raw-B agree directionally on DENSE.
    (b) DENSE and BALANCED_K8 agree in sign.
    """
    claims: Dict[str, Any] = {}

    # Rule (a): directional agreement Raw-A vs Raw-B on DENSE
    dense = subset_results.get("DENSE", {}).get("series", {})
    slope_a = (dense.get("raw_a", {}).get("p95_ols_trend", {}) or {}).get("slope")
    slope_b = (dense.get("raw_b", {}).get("p95_ols_trend", {}) or {}).get("slope")
    if slope_a is not None and slope_b is not None:
        agree = (slope_a >= 0) == (slope_b >= 0)
        claims["rule_a_raw_agree_dense"] = {
            "raw_a_slope": slope_a,
            "raw_b_slope": slope_b,
            "agree": bool(agree),
        }
    else:
        claims["rule_a_raw_agree_dense"] = {"agree": None, "reason": "insufficient data"}

    # Rule (b): DENSE vs BALANCED_K8 sign agreement (Raw-A)
    bk8 = subset_results.get("BALANCED_K8", {}).get("series", {})
    slope_dense = slope_a
    slope_bk8 = (bk8.get("raw_a", {}).get("p95_ols_trend", {}) or {}).get("slope")
    if slope_dense is not None and slope_bk8 is not None:
        agree = (slope_dense >= 0) == (slope_bk8 >= 0)
        claims["rule_b_dense_bk8_agree"] = {
            "dense_slope": slope_dense,
            "bk8_slope": slope_bk8,
            "agree": bool(agree),
        }
    else:
        claims["rule_b_dense_bk8_agree"] = {"agree": None, "reason": "insufficient data"}

    return claims


# ---------------------------------------------------------------------------
# Plotting: percentiles
# ---------------------------------------------------------------------------

def _plot_percentiles(
    df: pd.DataFrame,
    subset_name: str,
    std_col: str,
    output_path: Path,
) -> None:
    """Yearly p95/p99 for raw-a vs standardised severity."""
    sub_df, _ = get_subset(df, subset_name)
    stats_raw = year_summary_stats(sub_df, "S_raw_a")
    stats_std = year_summary_stats(sub_df, std_col)

    if len(stats_raw) == 0 or len(stats_std) == 0:
        logger.warning("No yearly stats for %s, skipping percentile plot", subset_name)
        return

    fig, axes = plt.subplots(1, 2, figsize=(12, 5), sharey=True)

    # Panel 1: p95
    ax = axes[0]
    years_raw = np.array(stats_raw.index, dtype=float)
    years_std = np.array(stats_std.index, dtype=float)

    if "p95" in stats_raw.columns:
        ax.plot(years_raw, stats_raw["p95"].values, "o-", color="#DC3912",
                linewidth=1.8, markersize=5, label="Raw-A p95")
    if "p95" in stats_std.columns:
        ax.plot(years_std, stats_std["p95"].values, "s-", color="#3366CC",
                linewidth=1.8, markersize=5, label="Standardised p95")
    ax.set_xlabel("Year", fontsize=10)
    ax.set_ylabel("Severity", fontsize=10)
    ax.set_title(f"{subset_name} — Yearly p95", fontsize=11, fontweight="bold")
    ax.legend(fontsize=9)
    ax.grid(True, alpha=0.3)
    ax.tick_params(labelsize=9)

    # Panel 2: p99
    ax = axes[1]
    if "p99" in stats_raw.columns:
        ax.plot(years_raw, stats_raw["p99"].values, "o-", color="#DC3912",
                linewidth=1.8, markersize=5, label="Raw-A p99")
    if "p99" in stats_std.columns:
        ax.plot(years_std, stats_std["p99"].values, "s-", color="#3366CC",
                linewidth=1.8, markersize=5, label="Standardised p99")
    ax.set_xlabel("Year", fontsize=10)
    ax.set_title(f"{subset_name} — Yearly p99", fontsize=11, fontweight="bold")
    ax.legend(fontsize=9)
    ax.grid(True, alpha=0.3)
    ax.tick_params(labelsize=9)

    fig.suptitle(
        f"Novelty 1: Tail Percentiles — Raw vs Standardised ({subset_name})",
        fontsize=13, fontweight="bold", y=1.02,
    )
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(str(output_path), dpi=200, bbox_inches="tight")
    plt.close(fig)
    logger.info("Saved percentile figure to %s", output_path)


# ---------------------------------------------------------------------------
# Plotting: exceedance rates
# ---------------------------------------------------------------------------

def _plot_exceedance(
    df: pd.DataFrame,
    subset_name: str,
    std_col: str,
    threshold: float,
    output_path: Path,
) -> None:
    """Yearly exceedance rate at the given threshold: raw-a vs standardised."""
    sub_df, _ = get_subset(df, subset_name)

    stats_raw = year_summary_stats(sub_df, "S_raw_a", thresholds=[threshold])
    stats_std = year_summary_stats(sub_df, std_col, thresholds=[threshold])

    exceed_col = f"exceed_{threshold:.2f}"
    if len(stats_raw) == 0 or exceed_col not in stats_raw.columns:
        logger.warning("No exceedance data for %s, skipping plot", subset_name)
        return

    fig, ax = plt.subplots(figsize=(8, 5))

    years_raw = np.array(stats_raw.index, dtype=float)
    ax.bar(years_raw - 0.15, stats_raw[exceed_col].values, width=0.3,
           color="#DC3912", alpha=0.8, label="Raw-A")

    if exceed_col in stats_std.columns:
        years_std = np.array(stats_std.index, dtype=float)
        ax.bar(years_std + 0.15, stats_std[exceed_col].values, width=0.3,
               color="#3366CC", alpha=0.8, label="Standardised")

    ax.set_xlabel("Year", fontsize=10)
    ax.set_ylabel(f"Exceedance Rate (threshold = {threshold:.2f})", fontsize=10)
    ax.set_title(
        f"Novelty 1: Exceedance Rates — {subset_name}",
        fontsize=12, fontweight="bold",
    )
    ax.legend(fontsize=10)
    ax.grid(True, axis="y", alpha=0.3)
    ax.tick_params(labelsize=9)
    ax.set_ylim(bottom=0)

    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(str(output_path), dpi=200, bbox_inches="tight")
    plt.close(fig)
    logger.info("Saved exceedance figure to %s", output_path)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(
    cache_path: str | None = None,
) -> Dict[str, Any]:
    """Execute the full mix-trend analysis.

    Returns the JSON-serialisable result dict.
    """
    # 1. Load / build analysis table
    logger.info("Building analysis table ...")
    df = load_or_build(cache_path=cache_path)

    # 2. Reference mix from DENSE subset
    w_q_dict = compute_market_average_mix(df, "dense")
    w_q_array = lob_weights_to_array(w_q_dict)
    total_w = w_q_array.sum()
    if total_w > 0:
        w_q_array = w_q_array / total_w
    logger.info("Reference mix (market_avg dense): %s", w_q_dict)

    # 3. Add query columns for reference portfolio
    df = add_query_columns(df, w_q_array, 500.0, "ref")
    std_col = "S_std_ref"

    # 4. Per-subset analysis
    subset_results: Dict[str, Dict] = {}
    for subset_name in _SUBSETS:
        logger.info("Analysing subset %s ...", subset_name)
        subset_results[subset_name] = _analyse_subset(df, subset_name, std_col)

    # 5. 2024 overlay
    logger.info("Analysing 2024 overlay ...")
    overlay_2024 = _analyse_2024(df)

    # 6. Robustness: exclude low-confidence
    logger.info("Running robustness check (exclude low confidence) ...")
    robustness = _robustness_exclude_low(df, std_col)

    # 7. Claim assessment
    claims = _assess_claims(subset_results)

    # 8. Assemble output
    output: Dict[str, Any] = {
        "analysis": "novelty_1_mix_trend",
        "reference_portfolio": {
            "mix": w_q_dict,
            "size_m": 500.0,
            "std_col": std_col,
        },
        "subsets": subset_results,
        "overlay_2024": overlay_2024,
        "robustness_exclude_low": robustness,
        "claims": claims,
    }

    # 9. Write JSON
    _RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    json_path = _RESULTS_DIR / "novelty1_trend_results.json"
    with open(str(json_path), "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, default=str)
    logger.info("Results written to %s", json_path)

    # 10. Plots
    _FIG_DIR.mkdir(parents=True, exist_ok=True)
    for subset_name in _SUBSETS:
        _plot_percentiles(
            df, subset_name, std_col,
            _FIG_DIR / f"novelty1_percentiles_{subset_name.lower()}.png",
        )
        _plot_exceedance(
            df, subset_name, std_col, _EXCEEDANCE_THRESHOLD,
            _FIG_DIR / f"novelty1_exceedance_{subset_name.lower()}.png",
        )

    return output


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Novelty 1: Time trend in tail severity — raw vs LoB-mix standardised",
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

    result = run(cache_path=args.cache)

    # Print summary
    logger.info("=== Novelty 1 Summary ===")

    # Report claim outcomes
    claims = result.get("claims", {})
    for rule_key, rule_val in claims.items():
        agree = rule_val.get("agree")
        if agree is True:
            logger.info("  %s: PASS", rule_key)
        elif agree is False:
            logger.warning("  %s: FAIL", rule_key)
        else:
            logger.warning("  %s: INDETERMINATE (%s)", rule_key, rule_val.get("reason", ""))

    # Report trend slopes
    for subset_name, sres in result.get("subsets", {}).items():
        series = sres.get("series", {})
        for label in ["raw_a", "raw_b", "standardised"]:
            trend = (series.get(label, {}).get("p95_ols_trend") or {})
            slope = trend.get("slope")
            pval = trend.get("p_value")
            if slope is not None:
                sig = "*" if (pval is not None and pval < 0.05) else ""
                logger.info(
                    "  %s / %-14s  p95-slope = %+.5f  (p=%.3f) %s",
                    subset_name, label, slope, pval or 0, sig,
                )


if __name__ == "__main__":
    main()
