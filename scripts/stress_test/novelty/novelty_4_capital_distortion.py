"""Novelty 4 -- Capital distortion from ignoring mix and/or size adjustments.

Quantifies the error in tail capital metrics (VaR, TVaR) that arises when
the exposure-adjustment methodology is partially or wholly omitted.

Four severity distributions are compared for each query portfolio:
  S_naive   = S_raw_a   (no adjustment -- raw aggregate severity)
  S_mix     = dot(w_q, s_lob)   (mix-only adjustment)
  S_size    = S_raw_a * (R_q/R_ref)^beta_bar   (size-only, applied to source-mix severity)
  S_mixsize = dot(w_q, s_lob) * (R_q/R_ref)^beta_weighted   (full adjustment)

Attribution follows a sequential decomposition (review feedback #7):
  mix_effect  = metric(S_mix)     - metric(S_naive)
  size_effect = metric(S_mixsize) - metric(S_mix)
  total_effect= metric(S_mixsize) - metric(S_naive)

By construction mix_effect + size_effect = total_effect in this sequential
scheme, which avoids forcing additivity on nonlinear functionals.

Outputs:
  fig/novelty4_cdf_market_avg_medium.png
  fig/novelty4_cdf_property_heavy_small.png
  fig/novelty4_distortion_bars.png
  results/novelty4_capital_distortion.json
"""

import sys
import json
import logging
import argparse
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
_this_dir = Path(__file__).resolve().parent
_stress_test_dir = _this_dir.parent
if str(_stress_test_dir) not in sys.path:
    sys.path.insert(0, str(_stress_test_dir))
if str(_this_dir) not in sys.path:
    sys.path.insert(0, str(_this_dir))

from config import LLOYDS_LOBS
from portfolio_size_adjustment import (
    DEFAULT_LOB_COEFFICIENTS,
    DEFAULT_REFERENCE_SIZE_M,
    DEFAULT_OVERALL_COEFFICIENT,
)
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
    project_severity,
    composite_beta,
    size_adjustment_factor,
    adjusted_severity,
    cap_severity,
    N_LOBS,
)
from common.tail_metrics import (
    empirical_var,
    empirical_tvar,
    hill_estimator,
    bootstrap_ci,
    cluster_bootstrap_syndicate,
    cluster_bootstrap_year,
    bootstrap_quantiles,
)
from common.query_portfolios import (
    PROPERTY_HEAVY,
    CASUALTY_HEAVY,
    SIZES_M,
    compute_market_average_mix,
    get_query_portfolios,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Output directories
# ---------------------------------------------------------------------------
_FIG_DIR = _this_dir / "fig"
_RESULTS_DIR = _this_dir / "results"

# ---------------------------------------------------------------------------
# Method labels (display order)
# ---------------------------------------------------------------------------
METHOD_LABELS = ["S_naive", "S_mix", "S_size", "S_mixsize"]
METHOD_DISPLAY = {
    "S_naive": "Naive (no adjustment)",
    "S_mix": "Mix-only",
    "S_size": "Size-only",
    "S_mixsize": "Full (mix + size)",
}
METHOD_COLOURS = {
    "S_naive": "#d62728",
    "S_mix": "#ff7f0e",
    "S_size": "#2ca02c",
    "S_mixsize": "#1f77b4",
}
METHOD_LINESTYLES = {
    "S_naive": "--",
    "S_mix": "-.",
    "S_size": ":",
    "S_mixsize": "-",
}

# Quantile levels for VaR / TVaR
_ALPHA_LEVELS = [0.99, 0.995]


# ===================================================================
# Core computation helpers
# ===================================================================

def _compute_four_distributions(
    df: pd.DataFrame,
    w_q: np.ndarray,
    R_q: float,
    R_ref: float = DEFAULT_REFERENCE_SIZE_M,
) -> Dict[str, np.ndarray]:
    """Compute the four severity distributions for one query portfolio.

    Parameters
    ----------
    df : analysis table (must contain S_raw_a, s_lob columns, no NaN in S_raw_a)
    w_q : ndarray[13] -- query LoB weight vector (normalised)
    R_q : float -- query portfolio reserve size in GBP m
    R_ref : float -- reference size

    Returns
    -------
    dict mapping method label -> 1-D float array of severities
    """
    # Filter rows with valid S_raw_a
    valid = df.dropna(subset=["S_raw_a"]).copy()
    n = len(valid)
    if n == 0:
        return {m: np.array([], dtype=np.float64) for m in METHOD_LABELS}

    # S_naive: raw aggregate severity (no adjustment)
    S_naive = valid["S_raw_a"].values.astype(np.float64)

    # S_mix: dot(w_q, s_lob) for each observation
    S_mix = np.array(
        [project_severity(w_q, s) for s in valid["s_lob"].values],
        dtype=np.float64,
    )

    # S_size: S_raw_a * (R_q / R_ref)^beta_bar   (size-only, applied to
    # source-mix severity -- i.e. the raw aggregate is size-adjusted using
    # the overall exponent, without re-weighting by the query mix)
    beta_bar = DEFAULT_OVERALL_COEFFICIENT
    A_bar = size_adjustment_factor(R_q, R_ref, beta_bar)
    S_size = S_naive * A_bar

    # S_mixsize: dot(w_q, s_lob) * (R_q / R_ref)^beta_weighted
    beta_w = composite_beta(w_q)
    A_w = size_adjustment_factor(R_q, R_ref, beta_w)
    S_mixsize = S_mix * A_w

    return {
        "S_naive": S_naive,
        "S_mix": S_mix,
        "S_size": S_size,
        "S_mixsize": S_mixsize,
    }


def _tail_metrics_table(
    distributions: Dict[str, np.ndarray],
) -> Dict[str, Dict[str, float]]:
    """Compute VaR and TVaR at each alpha level for every method.

    Returns nested dict: method -> metric_name -> value.
    """
    table: Dict[str, Dict[str, float]] = {}
    for method, data in distributions.items():
        row: Dict[str, float] = {}
        for alpha in _ALPHA_LEVELS:
            pct_label = str(alpha).replace("0.", "")
            row[f"VaR_{pct_label}"] = empirical_var(data, alpha)
            row[f"TVaR_{pct_label}"] = empirical_tvar(data, alpha)
        table[method] = row
    return table


def _attribution(
    metrics_table: Dict[str, Dict[str, float]],
) -> Dict[str, Dict[str, float]]:
    """Sequential attribution of mix and size effects.

    For each metric:
      mix_effect  = metric(S_mix)     - metric(S_naive)
      size_effect = metric(S_mixsize) - metric(S_mix)
      total_effect= metric(S_mixsize) - metric(S_naive)
    """
    attr: Dict[str, Dict[str, float]] = {}
    naive_row = metrics_table.get("S_naive", {})
    mix_row = metrics_table.get("S_mix", {})
    full_row = metrics_table.get("S_mixsize", {})
    for metric_name in naive_row:
        v_naive = naive_row[metric_name]
        v_mix = mix_row.get(metric_name, np.nan)
        v_full = full_row.get(metric_name, np.nan)
        mix_eff = v_mix - v_naive
        size_eff = v_full - v_mix
        total_eff = v_full - v_naive
        attr[metric_name] = {
            "mix_effect": _safe_float(mix_eff),
            "size_effect": _safe_float(size_eff),
            "total_effect": _safe_float(total_eff),
        }
    return attr


def _safe_float(x: Any) -> Optional[float]:
    """Convert to float, mapping NaN/inf to None for JSON serialisation."""
    if x is None:
        return None
    f = float(x)
    if np.isnan(f) or np.isinf(f):
        return None
    return f


# ===================================================================
# Cluster bootstrap CIs for VaR_99.5
# ===================================================================

def _bootstrap_cis_for_portfolio(
    df: pd.DataFrame,
    w_q: np.ndarray,
    R_q: float,
    B: int = 500,
    seed: int = 42,
) -> Dict[str, Dict[str, Any]]:
    """Cluster bootstrap (syndicate mode) CIs on VaR_99.5 for each method.

    Adds a temporary column per method, then calls cluster_bootstrap_syndicate.

    Returns dict: method -> {point, ci_lower, ci_upper, se}.
    """
    valid = df.dropna(subset=["S_raw_a"]).copy()
    if len(valid) == 0:
        empty = {"point": None, "ci_lower": None, "ci_upper": None, "se": None}
        return {m: dict(empty) for m in METHOD_LABELS}

    distributions = _compute_four_distributions(valid, w_q, R_q)
    cis: Dict[str, Dict[str, Any]] = {}
    for method in METHOD_LABELS:
        col_name = f"_tmp_{method}"
        valid[col_name] = distributions[method]
        stat_fn = lambda arr: empirical_var(arr, 0.995)  # noqa: E731
        pt, lo, hi, se = cluster_bootstrap_syndicate(
            valid,
            stat_func=stat_fn,
            value_col=col_name,
            cluster_col="syndicate_id",
            B=B,
            alpha=0.05,
            seed=seed,
        )
        cis[method] = {
            "point": _safe_float(pt),
            "ci_lower": _safe_float(lo),
            "ci_upper": _safe_float(hi),
            "se": _safe_float(se),
        }
    return cis


# ===================================================================
# Cause-category robustness
# ===================================================================

def _cause_robustness(
    df: pd.DataFrame,
    w_q: np.ndarray,
    R_q: float,
) -> Dict[str, Dict[str, Dict[str, float]]]:
    """Compute distortion metrics broken out by cause_category.

    Returns dict: cause -> method -> metric -> value.
    """
    causes = df["cause_category"].dropna().unique()
    results: Dict[str, Dict[str, Dict[str, float]]] = {}
    for cause in sorted(causes):
        sub = df[df["cause_category"] == cause]
        if len(sub.dropna(subset=["S_raw_a"])) < 5:
            continue
        dists = _compute_four_distributions(sub, w_q, R_q)
        metrics = _tail_metrics_table(dists)
        results[cause] = metrics
    return results


# ===================================================================
# Plotting helpers
# ===================================================================

def _ensure_matplotlib():
    """Import matplotlib with Agg backend for headless rendering."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    return plt


def _plot_cdf_overlay(
    distributions: Dict[str, np.ndarray],
    query_name: str,
    output_path: Path,
) -> None:
    """Plot overlaid empirical CDFs for the four severity methods.

    Saves to *output_path* and closes the figure.
    """
    plt = _ensure_matplotlib()
    fig, ax = plt.subplots(figsize=(8, 5))

    for method in METHOD_LABELS:
        data = distributions[method]
        if len(data) == 0:
            continue
        sorted_data = np.sort(data)
        cdf = np.arange(1, len(sorted_data) + 1) / len(sorted_data)
        ax.plot(
            sorted_data,
            cdf,
            label=METHOD_DISPLAY[method],
            color=METHOD_COLOURS[method],
            linestyle=METHOD_LINESTYLES[method],
            linewidth=1.5,
        )

    ax.set_xlabel("Severity", fontsize=11)
    ax.set_ylabel("Cumulative probability", fontsize=11)
    ax.set_title(
        f"Empirical CDF by adjustment method\n{query_name}",
        fontsize=12,
    )
    ax.legend(loc="lower right", fontsize=9, framealpha=0.9)
    ax.grid(True, alpha=0.3)
    ax.tick_params(labelsize=9)

    # Focus on the tail region: set x-limits to show p1 to p100
    all_vals = np.concatenate([distributions[m] for m in METHOD_LABELS if len(distributions[m]) > 0])
    if len(all_vals) > 0:
        x_lo = float(np.percentile(all_vals, 1))
        x_hi = float(np.percentile(all_vals, 100))
        margin = (x_hi - x_lo) * 0.05 if x_hi > x_lo else 0.1
        ax.set_xlim(x_lo - margin, x_hi + margin)

    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(str(output_path), dpi=150, bbox_inches="tight")
    plt.close(fig)
    logger.info("Saved CDF overlay: %s", output_path)


def _plot_distortion_bars(
    all_attributions: Dict[str, Dict[str, Dict[str, float]]],
    output_path: Path,
) -> None:
    """Bar chart of mix_effect and size_effect on VaR_995 across portfolios.

    One group of bars per portfolio in the 3x3 grid; two bars per group
    (mix_effect, size_effect).
    """
    plt = _ensure_matplotlib()

    metric_key = "VaR_995"
    portfolio_names = []
    mix_effects = []
    size_effects = []

    for pf_name in sorted(all_attributions.keys()):
        attr = all_attributions[pf_name].get(metric_key, {})
        me = attr.get("mix_effect")
        se = attr.get("size_effect")
        if me is None or se is None:
            continue
        portfolio_names.append(pf_name)
        mix_effects.append(me)
        size_effects.append(se)

    if len(portfolio_names) == 0:
        logger.warning("No attribution data for bar chart; skipping.")
        return

    n = len(portfolio_names)
    x = np.arange(n)
    width = 0.35

    fig, ax = plt.subplots(figsize=(max(10, n * 1.2), 5))
    bars_mix = ax.bar(
        x - width / 2,
        mix_effects,
        width,
        label="Mix effect",
        color="#ff7f0e",
        edgecolor="white",
    )
    bars_size = ax.bar(
        x + width / 2,
        size_effects,
        width,
        label="Size effect",
        color="#1f77b4",
        edgecolor="white",
    )

    ax.set_xlabel("Query portfolio", fontsize=11)
    ax.set_ylabel(f"Effect on {metric_key}", fontsize=11)
    ax.set_title(
        "Capital distortion attribution: mix vs. size effects\n"
        f"(metric: {metric_key})",
        fontsize=12,
    )
    ax.set_xticks(x)
    ax.set_xticklabels(portfolio_names, rotation=45, ha="right", fontsize=8)
    ax.legend(fontsize=9)
    ax.axhline(0, color="black", linewidth=0.8)
    ax.grid(True, axis="y", alpha=0.3)
    ax.tick_params(labelsize=9)

    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(str(output_path), dpi=150, bbox_inches="tight")
    plt.close(fig)
    logger.info("Saved distortion bar chart: %s", output_path)


# ===================================================================
# Main analysis driver
# ===================================================================

def run_analysis(
    cache_path: Optional[str] = None,
    bootstrap_B: int = 500,
    seed: int = 42,
) -> Dict[str, Any]:
    """Run the full Novelty-4 capital distortion analysis.

    Parameters
    ----------
    cache_path : optional path for the analysis-table pickle cache
    bootstrap_B : number of cluster-bootstrap replicates
    seed : RNG seed for reproducibility

    Returns
    -------
    dict with full results (also written to JSON)
    """
    logger.info("=== Novelty 4: Capital distortion analysis ===")

    # ----------------------------------------------------------------
    # 1. Load / build the analysis table
    # ----------------------------------------------------------------
    df = load_or_build(cache_path=cache_path)
    logger.info("Analysis table loaded: %d rows", len(df))
    merge_audit = audit_merge(df)

    # ----------------------------------------------------------------
    # 2. Get query portfolios (3 mixes x 3 sizes = 9)
    # ----------------------------------------------------------------
    portfolios = get_query_portfolios(df)
    beta_lob = beta_lob_array()
    logger.info("Query portfolios: %d", len(portfolios))

    # ----------------------------------------------------------------
    # 3. Process each subset (DENSE = primary, FULL = secondary)
    # ----------------------------------------------------------------
    subset_names = ["DENSE", "FULL"]
    results: Dict[str, Any] = {
        "analysis": "novelty_4_capital_distortion",
        "description": (
            "Quantifies capital error from ignoring LoB-mix and/or "
            "portfolio-size adjustments."
        ),
        "subsets": {},
        "merge_audit": merge_audit,
    }

    # Collect all attributions across subsets for the bar chart
    bar_chart_attributions: Dict[str, Dict[str, Dict[str, float]]] = {}

    for subset_name in subset_names:
        logger.info("--- Subset: %s ---", subset_name)
        sub_df, cov_stats = get_subset(df, subset_name)
        if len(sub_df.dropna(subset=["S_raw_a"])) < 10:
            logger.warning(
                "Subset %s has <10 valid observations; skipping.", subset_name
            )
            results["subsets"][subset_name] = {
                "coverage": cov_stats.to_dict(),
                "skipped": True,
                "reason": "insufficient data",
            }
            continue

        cap_stats = compute_cap_binding_stats(sub_df)
        subset_results: Dict[str, Any] = {
            "coverage": cov_stats.to_dict(),
            "cap_binding_stats": cap_stats,
            "portfolios": {},
        }

        for query_name, w_dict, R_q in portfolios:
            logger.info("  Portfolio: %s (R_q=%.0f)", query_name, R_q)
            w_q = lob_weights_to_array(w_dict)
            # Normalise
            w_sum = w_q.sum()
            if w_sum > 0:
                w_q = w_q / w_sum

            # 4 distributions
            dists = _compute_four_distributions(sub_df, w_q, R_q)
            n_obs = len(dists["S_naive"])

            # Tail metrics
            metrics = _tail_metrics_table(dists)

            # Attribution
            attr = _attribution(metrics)

            # Bootstrap CIs on VaR_99.5
            cis = _bootstrap_cis_for_portfolio(
                sub_df, w_q, R_q, B=bootstrap_B, seed=seed
            )

            # Cause-category robustness
            cause_rob = _cause_robustness(sub_df, w_q, R_q)

            # Beta values for this portfolio
            beta_weighted = composite_beta(w_q, beta_lob)
            A_factor = size_adjustment_factor(R_q, DEFAULT_REFERENCE_SIZE_M, beta_weighted)

            pf_result = {
                "query_name": query_name,
                "w_q": {lob: _safe_float(w_q[i]) for i, lob in enumerate(LLOYDS_LOBS) if w_q[i] > 0},
                "R_q": R_q,
                "R_ref": DEFAULT_REFERENCE_SIZE_M,
                "beta_overall": DEFAULT_OVERALL_COEFFICIENT,
                "beta_weighted": _safe_float(beta_weighted),
                "size_adjustment_factor": _safe_float(A_factor),
                "n_observations": n_obs,
                "metrics": {
                    method: {k: _safe_float(v) for k, v in row.items()}
                    for method, row in metrics.items()
                },
                "attribution": {
                    metric_name: {k: _safe_float(v) for k, v in attr_row.items()}
                    for metric_name, attr_row in attr.items()
                },
                "bootstrap_ci_VaR_995": cis,
                "cause_robustness": {
                    cause: {
                        method: {k: _safe_float(v) for k, v in mrow.items()}
                        for method, mrow in cause_metrics.items()
                    }
                    for cause, cause_metrics in cause_rob.items()
                },
            }
            subset_results["portfolios"][query_name] = pf_result

            # Accumulate for bar chart (use primary subset only)
            if subset_name == "DENSE":
                bar_chart_attributions[query_name] = attr

            # CDF plots for two representative portfolios (primary subset only)
            if subset_name == "DENSE":
                if query_name == "market_avg_medium":
                    _plot_cdf_overlay(
                        dists,
                        query_name,
                        _FIG_DIR / "novelty4_cdf_market_avg_medium.png",
                    )
                elif query_name == "property_heavy_small":
                    _plot_cdf_overlay(
                        dists,
                        query_name,
                        _FIG_DIR / "novelty4_cdf_property_heavy_small.png",
                    )

        results["subsets"][subset_name] = subset_results

    # ----------------------------------------------------------------
    # 4. Distortion bar chart (all 9 portfolios, DENSE subset)
    # ----------------------------------------------------------------
    if bar_chart_attributions:
        _plot_distortion_bars(
            bar_chart_attributions,
            _FIG_DIR / "novelty4_distortion_bars.png",
        )

    # ----------------------------------------------------------------
    # 5. Write JSON results
    # ----------------------------------------------------------------
    json_path = _RESULTS_DIR / "novelty4_capital_distortion.json"
    json_path.parent.mkdir(parents=True, exist_ok=True)
    with open(str(json_path), "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, default=str)
    logger.info("Results written to %s", json_path)

    return results


# ===================================================================
# CLI entry-point
# ===================================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Novelty 4: Quantify capital distortion from ignoring "
            "LoB-mix and/or portfolio-size adjustments."
        ),
    )
    parser.add_argument(
        "--cache",
        type=str,
        default=None,
        help="Path to analysis-table pickle cache (speeds up repeated runs).",
    )
    parser.add_argument(
        "--bootstrap-B",
        type=int,
        default=500,
        help="Number of cluster-bootstrap replicates (default: 500).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducibility (default: 42).",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level (default: INFO).",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s  %(name)-30s  %(levelname)-8s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    results = run_analysis(
        cache_path=args.cache,
        bootstrap_B=args.bootstrap_B,
        seed=args.seed,
    )

    # Quick summary to stdout
    for subset_name, sdata in results.get("subsets", {}).items():
        if sdata.get("skipped"):
            print(f"\n[{subset_name}] skipped: {sdata.get('reason')}")
            continue
        cov = sdata.get("coverage", {})
        print(f"\n[{subset_name}] n_observations={cov.get('n_observations')}")
        for pf_name, pf_data in sdata.get("portfolios", {}).items():
            metrics = pf_data.get("metrics", {})
            attr = pf_data.get("attribution", {})
            var_995_naive = (metrics.get("S_naive") or {}).get("VaR_995")
            var_995_full = (metrics.get("S_mixsize") or {}).get("VaR_995")
            total = (attr.get("VaR_995") or {}).get("total_effect")
            print(
                f"  {pf_name:30s}  VaR_995: naive={_fmt(var_995_naive)} "
                f"full={_fmt(var_995_full)}  total_effect={_fmt(total)}"
            )


def _fmt(x: Optional[float], decimals: int = 4) -> str:
    """Format a float for display, handling None."""
    if x is None:
        return "N/A"
    return f"{x:.{decimals}f}"


if __name__ == "__main__":
    main()
