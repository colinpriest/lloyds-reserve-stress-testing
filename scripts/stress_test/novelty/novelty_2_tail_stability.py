"""Novelty 2 — Tail stability: diagnostics are more stable after LoB-mix standardisation.

Computes rolling-window tail metrics (tail ratios, mean-excess function, Hill
estimator) for Raw-A, Raw-B, and standardised severity, comparing variability
across windows.  Cluster bootstrap (by syndicate) within each window provides
uncertainty bands.  Cap-binding rates are tracked per window (R6).

Robustness checks: exclude capped severities; restrict to events observed by
at least 3 syndicates.

Outputs
-------
fig/novelty2_tail_ratio_full.png
    Rolling p99/p95 ratio with shaded bootstrap CI.
fig/novelty2_mef_full.png
    Mean excess function at u = 0.20 over time.
results/novelty2_tail_stability.json
    Variability metrics (sd, range) across windows for each metric/series.
"""

import sys
import json
import logging
import argparse
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
    compute_cap_binding_stats,
    audit_merge,
)
from common.severity_projection import lob_weights_to_array, beta_lob_array, N_LOBS
from common.tail_metrics import (
    empirical_var,
    empirical_tvar,
    hill_estimator,
    mean_excess_function,
    tail_ratio,
    bootstrap_ci,
    cluster_bootstrap_syndicate,
)
from common.time_windows import rolling_windows
from common.query_portfolios import compute_market_average_mix

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Output directories
# ---------------------------------------------------------------------------
FIG_DIR = _this_dir / "fig"
RESULTS_DIR = _this_dir / "results"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
WINDOW_WIDTH = 3
YEAR_START = 2014
YEAR_END = 2023
MIN_OBS_TAIL_RATIO = 200
MIN_EXCEEDANCES_MEF = 25
MIN_EXCEEDANCES_HILL = 40
MEF_THRESHOLDS = [0.10, 0.20, 0.30]
BOOTSTRAP_B = 500
BOOTSTRAP_SEED = 42
MIN_SYNDICATES_PER_EVENT = 3


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_float(v: Any) -> Any:
    """Convert numpy scalars to Python floats for JSON serialisation."""
    if isinstance(v, (np.floating, np.integer)):
        return float(v)
    if isinstance(v, np.ndarray):
        return v.tolist()
    return v


def _compute_tail_metrics_for_series(
    values: np.ndarray,
) -> Dict[str, Any]:
    """Compute tail diagnostics for a single severity vector.

    Returns a dict with keys: tail_ratio_99_95, tail_ratio_95_90,
    mef_0.10, mef_0.20, mef_0.30, hill_xi, hill_se.  Values are NaN
    where sample-size thresholds are not met.
    """
    n = len(values)
    result: Dict[str, Any] = {}

    # --- Tail ratios (require n >= MIN_OBS_TAIL_RATIO) ---
    if n >= MIN_OBS_TAIL_RATIO:
        result["tail_ratio_99_95"] = tail_ratio(values, 0.99, 0.95)
        result["tail_ratio_95_90"] = tail_ratio(values, 0.95, 0.90)
    else:
        result["tail_ratio_99_95"] = np.nan
        result["tail_ratio_95_90"] = np.nan

    # --- Mean excess function ---
    abs_vals = np.abs(values[~np.isnan(values)])
    thresholds = np.array(MEF_THRESHOLDS, dtype=np.float64)
    mef_vals = mean_excess_function(abs_vals, thresholds, min_exceedances=MIN_EXCEEDANCES_MEF)
    for i, u in enumerate(MEF_THRESHOLDS):
        result[f"mef_{u:.2f}"] = float(mef_vals[i]) if not np.isnan(mef_vals[i]) else np.nan

    # --- Hill estimator ---
    positive_vals = abs_vals[abs_vals > 0]
    if len(positive_vals) >= MIN_EXCEEDANCES_HILL + 1:
        k = MIN_EXCEEDANCES_HILL
        xi, se = hill_estimator(positive_vals, k=k)
        result["hill_xi"] = xi
        result["hill_se"] = se
    else:
        result["hill_xi"] = np.nan
        result["hill_se"] = np.nan

    return result


def _variability_stats(
    window_values: List[float],
) -> Dict[str, float]:
    """SD and range of a metric across windows (dropping NaN)."""
    arr = np.array(window_values, dtype=np.float64)
    arr = arr[~np.isnan(arr)]
    if len(arr) < 2:
        return {"sd": np.nan, "range": np.nan, "n_valid": len(arr)}
    return {
        "sd": float(np.std(arr, ddof=1)),
        "range": float(np.ptp(arr)),
        "n_valid": int(len(arr)),
    }


# ---------------------------------------------------------------------------
# Core analysis
# ---------------------------------------------------------------------------

def run_tail_stability(
    df: pd.DataFrame,
    ref_query_name: str = "ref",
    bootstrap_B: int = BOOTSTRAP_B,
    seed: int = BOOTSTRAP_SEED,
) -> Dict[str, Any]:
    """Run rolling-window tail stability analysis.

    Parameters
    ----------
    df : analysis table with S_std_ref column already added.
    ref_query_name : suffix used for the standardised column.
    bootstrap_B : number of bootstrap replicates per window.
    seed : random seed for reproducibility.

    Returns
    -------
    Dict with keys: windows, per_window, variability, cap_binding,
    robustness_excl_capped, robustness_min_3_synd.
    """
    std_col = f"S_std_{ref_query_name}"
    series_map = {
        "Raw-A": "S_raw_a",
        "Raw-B": "S_raw_b",
        "Standardised": std_col,
    }

    # Build windows from FULL years
    years = sorted(df["year"].unique())
    windows = rolling_windows(years, width=WINDOW_WIDTH)
    logger.info("Rolling windows (%d-year): %d windows from %s", WINDOW_WIDTH, len(windows), windows)

    per_window: List[Dict[str, Any]] = []
    # Accumulators for variability comparison
    metric_traces: Dict[str, Dict[str, List[float]]] = {
        sname: {
            "tail_ratio_99_95": [],
            "tail_ratio_95_90": [],
            "mef_0.10": [],
            "mef_0.20": [],
            "mef_0.30": [],
            "hill_xi": [],
        }
        for sname in series_map
    }
    # Bootstrap traces for tail_ratio_99_95
    bootstrap_traces: Dict[str, List[Dict[str, float]]] = {sname: [] for sname in series_map}

    cap_binding_per_window: List[Dict[str, Any]] = []

    for w_start, w_end in windows:
        w_df = df[(df["year"] >= w_start) & (df["year"] <= w_end)].copy()
        w_label = f"{w_start}-{w_end}"
        w_result: Dict[str, Any] = {"window": w_label, "n": len(w_df)}
        logger.info("Window %s: n=%d", w_label, len(w_df))

        for sname, col in series_map.items():
            vals = w_df[col].dropna().values.astype(np.float64)
            metrics = _compute_tail_metrics_for_series(vals)
            for mkey, mval in metrics.items():
                w_result[f"{sname}_{mkey}"] = _safe_float(mval)
                if mkey in metric_traces[sname]:
                    metric_traces[sname][mkey].append(mval)

            # Cluster bootstrap for tail_ratio_99_95
            if len(vals) >= MIN_OBS_TAIL_RATIO:
                stat_func = lambda x: tail_ratio(x, 0.99, 0.95)
                pt, lo, hi, se = cluster_bootstrap_syndicate(
                    w_df.dropna(subset=[col]),
                    stat_func=stat_func,
                    value_col=col,
                    B=bootstrap_B,
                    seed=seed,
                )
                bootstrap_traces[sname].append(
                    {"window": w_label, "point": pt, "lo": lo, "hi": hi, "se": se}
                )
            else:
                bootstrap_traces[sname].append(
                    {"window": w_label, "point": np.nan, "lo": np.nan, "hi": np.nan, "se": np.nan}
                )

        # Cap-binding stats for this window (R6)
        cb = compute_cap_binding_stats(w_df)
        cap_binding_per_window.append({"window": w_label, **{k: v for k, v in cb.items() if k != "by_year"}})

        per_window.append(w_result)

    # --- Variability comparison ---
    variability: Dict[str, Dict[str, Dict[str, float]]] = {}
    for sname in series_map:
        variability[sname] = {}
        for mkey in metric_traces[sname]:
            variability[sname][mkey] = _variability_stats(metric_traces[sname][mkey])

    # --- Robustness: exclude capped severities ---
    robustness_excl_capped = _robustness_exclude_capped(df, series_map, windows)

    # --- Robustness: only events with >= 3 syndicates ---
    robustness_min_3 = _robustness_min_syndicates(df, series_map, windows)

    return {
        "windows": [f"{s}-{e}" for s, e in windows],
        "per_window": per_window,
        "variability": variability,
        "bootstrap_tail_ratio": {
            sname: [
                {k: _safe_float(v) for k, v in entry.items()} for entry in entries
            ]
            for sname, entries in bootstrap_traces.items()
        },
        "cap_binding_per_window": cap_binding_per_window,
        "robustness_excl_capped": robustness_excl_capped,
        "robustness_min_3_synd": robustness_min_3,
    }


def _robustness_exclude_capped(
    df: pd.DataFrame,
    series_map: Dict[str, str],
    windows: List[Tuple[int, int]],
) -> Dict[str, Dict[str, Dict[str, float]]]:
    """Re-run variability after removing rows where any LoB severity hit the cap."""
    # A row is capped if cap_binding dict is non-empty
    mask_uncapped = df["cap_binding"].apply(lambda d: len(d) == 0 if isinstance(d, dict) else True)
    df_clean = df.loc[mask_uncapped].copy()
    logger.info("Robustness (excl capped): %d -> %d rows", len(df), len(df_clean))

    traces: Dict[str, Dict[str, List[float]]] = {
        sname: {m: [] for m in ["tail_ratio_99_95", "mef_0.20", "hill_xi"]}
        for sname in series_map
    }
    for w_start, w_end in windows:
        w_df = df_clean[(df_clean["year"] >= w_start) & (df_clean["year"] <= w_end)]
        for sname, col in series_map.items():
            vals = w_df[col].dropna().values.astype(np.float64)
            metrics = _compute_tail_metrics_for_series(vals)
            for mkey in traces[sname]:
                traces[sname][mkey].append(metrics.get(mkey, np.nan))

    result: Dict[str, Dict[str, Dict[str, float]]] = {}
    for sname in series_map:
        result[sname] = {}
        for mkey in traces[sname]:
            result[sname][mkey] = _variability_stats(traces[sname][mkey])
    return result


def _robustness_min_syndicates(
    df: pd.DataFrame,
    series_map: Dict[str, str],
    windows: List[Tuple[int, int]],
) -> Dict[str, Dict[str, Dict[str, float]]]:
    """Re-run variability restricted to events with >= MIN_SYNDICATES_PER_EVENT syndicates."""
    event_counts = df.groupby("event_id")["syndicate_id"].nunique()
    valid_events = set(event_counts[event_counts >= MIN_SYNDICATES_PER_EVENT].index)
    df_clean = df[df["event_id"].isin(valid_events)].copy()
    logger.info("Robustness (>=%d synd): %d -> %d rows", MIN_SYNDICATES_PER_EVENT, len(df), len(df_clean))

    traces: Dict[str, Dict[str, List[float]]] = {
        sname: {m: [] for m in ["tail_ratio_99_95", "mef_0.20", "hill_xi"]}
        for sname in series_map
    }
    for w_start, w_end in windows:
        w_df = df_clean[(df_clean["year"] >= w_start) & (df_clean["year"] <= w_end)]
        for sname, col in series_map.items():
            vals = w_df[col].dropna().values.astype(np.float64)
            metrics = _compute_tail_metrics_for_series(vals)
            for mkey in traces[sname]:
                traces[sname][mkey].append(metrics.get(mkey, np.nan))

    result: Dict[str, Dict[str, Dict[str, float]]] = {}
    for sname in series_map:
        result[sname] = {}
        for mkey in traces[sname]:
            result[sname][mkey] = _variability_stats(traces[sname][mkey])
    return result


# ---------------------------------------------------------------------------
# Plotting
# ---------------------------------------------------------------------------

def plot_tail_ratio_rolling(
    analysis: Dict[str, Any],
    output_path: Path,
) -> None:
    """Plot rolling p99/p95 tail ratio with bootstrap CI bands."""
    windows = analysis["windows"]
    bt = analysis["bootstrap_tail_ratio"]
    series_order = ["Raw-A", "Raw-B", "Standardised"]
    colors = {"Raw-A": "#d62728", "Raw-B": "#ff7f0e", "Standardised": "#1f77b4"}

    fig, ax = plt.subplots(figsize=(10, 5))
    x = np.arange(len(windows))

    for sname in series_order:
        entries = bt[sname]
        pts = np.array([e["point"] for e in entries], dtype=np.float64)
        lo = np.array([e["lo"] for e in entries], dtype=np.float64)
        hi = np.array([e["hi"] for e in entries], dtype=np.float64)

        valid = ~np.isnan(pts)
        ax.plot(x[valid], pts[valid], "o-", label=sname, color=colors[sname], linewidth=1.5)
        ax.fill_between(x[valid], lo[valid], hi[valid], alpha=0.15, color=colors[sname])

    ax.set_xticks(x)
    ax.set_xticklabels(windows, rotation=45, ha="right", fontsize=8)
    ax.set_ylabel("p99 / p95 Tail Ratio")
    ax.set_title("Rolling Tail Ratio (p99/p95) with Cluster Bootstrap 95% CI")
    ax.legend(frameon=True, fontsize=9)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(str(output_path), dpi=150)
    plt.close(fig)
    logger.info("Saved %s", output_path)


def plot_mef_rolling(
    analysis: Dict[str, Any],
    output_path: Path,
) -> None:
    """Plot mean excess at u=0.20 over rolling windows."""
    windows = analysis["windows"]
    per_window = analysis["per_window"]
    series_order = ["Raw-A", "Raw-B", "Standardised"]
    colors = {"Raw-A": "#d62728", "Raw-B": "#ff7f0e", "Standardised": "#1f77b4"}

    fig, ax = plt.subplots(figsize=(10, 5))
    x = np.arange(len(windows))

    for sname in series_order:
        key = f"{sname}_mef_0.20"
        vals = np.array([pw.get(key, np.nan) for pw in per_window], dtype=np.float64)
        valid = ~np.isnan(vals)
        ax.plot(x[valid], vals[valid], "s-", label=sname, color=colors[sname], linewidth=1.5)

    ax.set_xticks(x)
    ax.set_xticklabels(windows, rotation=45, ha="right", fontsize=8)
    ax.set_ylabel("Mean Excess at u = 0.20")
    ax.set_title("Rolling Mean Excess Function (u = 0.20)")
    ax.legend(frameon=True, fontsize=9)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(str(output_path), dpi=150)
    plt.close(fig)
    logger.info("Saved %s", output_path)


# ---------------------------------------------------------------------------
# JSON serialiser helper
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Novelty 2: tail stability analysis — raw vs standardised severity."
    )
    parser.add_argument(
        "--cache", default=None,
        help="Path to analysis table pickle cache.",
    )
    parser.add_argument(
        "--bootstrap-B", type=int, default=BOOTSTRAP_B,
        help="Number of bootstrap replicates per window (default %(default)s).",
    )
    parser.add_argument(
        "--seed", type=int, default=BOOTSTRAP_SEED,
        help="Random seed (default %(default)s).",
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
    # 2. Reference query: market-average mix from DENSE, size 500
    # ------------------------------------------------------------------
    df_dense, cov_dense = get_subset(df, "DENSE")
    market_avg = compute_market_average_mix(df, subset="dense")
    w_q_ref = lob_weights_to_array(market_avg)
    total_w = w_q_ref.sum()
    if total_w > 0:
        w_q_ref = w_q_ref / total_w

    ref_query_name = "ref"
    df = add_query_columns(df, w_q=w_q_ref, R_q=500.0, query_name=ref_query_name)

    # ------------------------------------------------------------------
    # 3. Subset to FULL (2014-2023)
    # ------------------------------------------------------------------
    df_full, cov_full = get_subset(df, "FULL")
    logger.info("FULL subset: %d rows, coverage: %s", len(df_full), cov_full)

    # ------------------------------------------------------------------
    # 4. Run rolling-window tail stability analysis
    # ------------------------------------------------------------------
    analysis = run_tail_stability(
        df_full,
        ref_query_name=ref_query_name,
        bootstrap_B=args.bootstrap_B,
        seed=args.seed,
    )

    # ------------------------------------------------------------------
    # 5. Plots
    # ------------------------------------------------------------------
    plot_tail_ratio_rolling(analysis, FIG_DIR / "novelty2_tail_ratio_full.png")
    plot_mef_rolling(analysis, FIG_DIR / "novelty2_mef_full.png")

    # ------------------------------------------------------------------
    # 6. JSON output
    # ------------------------------------------------------------------
    output = {
        "description": (
            "Novelty 2: tail stability diagnostics across rolling 3-year windows. "
            "Compares variability of tail metrics for Raw-A, Raw-B, and LoB-mix "
            "standardised severity."
        ),
        "coverage_full": cov_full.to_dict(),
        "coverage_dense_ref": cov_dense.to_dict(),
        "reference_mix": market_avg,
        "reference_size_m": 500.0,
        "window_width": WINDOW_WIDTH,
        "thresholds": {
            "min_obs_tail_ratio": MIN_OBS_TAIL_RATIO,
            "min_exceedances_mef": MIN_EXCEEDANCES_MEF,
            "min_exceedances_hill": MIN_EXCEEDANCES_HILL,
        },
        "variability": analysis["variability"],
        "per_window": analysis["per_window"],
        "bootstrap_tail_ratio": analysis["bootstrap_tail_ratio"],
        "cap_binding_per_window": analysis["cap_binding_per_window"],
        "robustness_excl_capped": analysis["robustness_excl_capped"],
        "robustness_min_3_synd": analysis["robustness_min_3_synd"],
    }

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RESULTS_DIR / "novelty2_tail_stability.json"
    with open(str(out_path), "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, default=_json_default)
    logger.info("Results written to %s", out_path)

    # ------------------------------------------------------------------
    # 7. Summary to console
    # ------------------------------------------------------------------
    print("\n=== Novelty 2: Tail Stability Summary ===")
    for sname in ["Raw-A", "Raw-B", "Standardised"]:
        tr_var = analysis["variability"][sname].get("tail_ratio_99_95", {})
        mef_var = analysis["variability"][sname].get("mef_0.20", {})
        print(f"  {sname:15s}  tail_ratio_99_95 sd={tr_var.get('sd', 'NA'):.4f}  "
              f"mef_0.20 sd={mef_var.get('sd', 'NA'):.4f}")
    print(f"\nOutputs: {FIG_DIR / 'novelty2_tail_ratio_full.png'}")
    print(f"         {FIG_DIR / 'novelty2_mef_full.png'}")
    print(f"         {out_path}")


if __name__ == "__main__":
    main()
