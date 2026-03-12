"""Generate tables (LaTeX) and figures for the IME paper.

Reads novelty analysis results and the analysis table, then writes all
outputs into an ``IME/`` subfolder.

Usage:
    python IME-paper-table-figures.py
"""

import json
import math
import pickle
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

# ---------------------------------------------------------------------------
# Path setup — allow imports from stress_test modules
# ---------------------------------------------------------------------------
_STRESS_TEST_DIR = Path(__file__).resolve().parent / "scripts" / "stress_test"
_NOVELTY_DIR = _STRESS_TEST_DIR / "novelty"
if str(_STRESS_TEST_DIR) not in sys.path:
    sys.path.insert(0, str(_STRESS_TEST_DIR))
if str(_NOVELTY_DIR) not in sys.path:
    sys.path.insert(0, str(_NOVELTY_DIR))

from common.severity_projection import (
    lob_weights_to_array,
    project_severity,
    composite_beta,
    size_adjustment_factor,
    N_LOBS,
)
from common.query_portfolios import (
    PROPERTY_HEAVY,
    CASUALTY_HEAVY,
    SIZES_M,
    compute_market_average_mix,
)
from portfolio_size_adjustment import DEFAULT_REFERENCE_SIZE_M

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent
RESULTS_DIR = PROJECT_ROOT / "scripts" / "stress_test" / "novelty" / "results"
OUTPUT_DIR = PROJECT_ROOT / "IME"

ANALYSIS_TABLE_PATH = RESULTS_DIR / "_analysis_table.pkl"
N0_PATH = RESULTS_DIR / "novelty0_sampling_sensitivity.json"
N1_PATH = RESULTS_DIR / "novelty1_trend_results.json"
N2_PATH = RESULTS_DIR / "novelty2_tail_stability.json"
N3_PATH = RESULTS_DIR / "novelty3_size_validation.json"
N4_PATH = RESULTS_DIR / "novelty4_capital_distortion.json"

# ---------------------------------------------------------------------------
# Styling constants
# ---------------------------------------------------------------------------
COLOUR_RAW = "#2166ac"
COLOUR_STD = "#b2182b"
COLOUR_SIZE = "#4daf4a"
COLOUR_MIX = "#ffd700"

FIGSIZE_SINGLE = (6, 4)
DPI = 300


def _load_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_analysis_table() -> pd.DataFrame:
    with open(ANALYSIS_TABLE_PATH, "rb") as f:
        return pickle.load(f)


def _save_tex(tex: str, name: str) -> Path:
    out = OUTPUT_DIR / name
    with open(out, "w", encoding="utf-8") as f:
        f.write(tex)
    logger.info(f"Wrote {out}")
    return out


def _save_fig(fig, name: str) -> Path:
    out = OUTPUT_DIR / name
    fig.savefig(out, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    logger.info(f"Wrote {out}")
    return out


# ===================================================================
# TABLE 1 — Corpus Summary
# ===================================================================
def table1_corpus_summary(df: pd.DataFrame) -> str:
    years = sorted(df["year"].unique())
    year_min, year_max = int(min(years)), int(max(years))
    total_obs = len(df)
    n_syndicates = df["syndicate_id"].nunique()

    synd_per_year = df.groupby("year")["syndicate_id"].nunique()
    dense_years = [y for y in years if y <= 2019]
    sparse_years = [y for y in years if 2020 <= y <= 2023]
    dense_range = f"{int(synd_per_year[dense_years].min())}--{int(synd_per_year[dense_years].max())}" if dense_years else "---"
    sparse_range = f"{int(synd_per_year[sparse_years].min())}--{int(synd_per_year[sparse_years].max())}" if sparse_years else "---"

    # Balanced-panel: syndicates appearing in all 10 full years (2014-2023)
    full_years = [y for y in years if y <= 2023]
    year_counts = df[df["year"].isin(full_years)].groupby("syndicate_id")["year"].nunique()
    n_balanced = int((year_counts == len(full_years)).sum())

    partial_2024 = int(synd_per_year.get(2024, 0))

    median_reserves = df.dropna(subset=["R_s"])["R_s"].median()

    n_lob_cats = 13  # from config.py LLOYDS_LOBS

    rows = [
        ("Years covered", f"{year_min}--{year_max}"),
        ("Total observations", f"{total_obs:,}"),
        ("Unique syndicates", f"{n_syndicates}"),
        (f"Syndicates per year ({dense_years[0]}--{dense_years[-1]})", dense_range),
        (f"Syndicates per year ({sparse_years[0]}--{sparse_years[-1]})", sparse_range),
        ("Balanced-panel syndicates", f"{n_balanced}"),
        ("Partial-year observations (2024)", f"{partial_2024}"),
        (r"Median reserves (\pounds m)", f"{median_reserves:.1f}"),
        ("LoB categories", f"{n_lob_cats}"),
    ]

    tex_lines = [
        r"\begin{table}[htbp]",
        r"\centering",
        r"\caption{Corpus summary statistics.}",
        r"\label{tab:corpus_summary}",
        r"\begin{tabular}{lr}",
        r"\toprule",
        r"Metric & Value \\",
        r"\midrule",
    ]
    for metric, value in rows:
        tex_lines.append(f"{metric} & {value} \\\\")
    tex_lines += [
        r"\bottomrule",
        r"\end{tabular}",
        r"\end{table}",
    ]
    return "\n".join(tex_lines)


# ===================================================================
# FIGURE 1 — Raw vs Standardised Tail Trend
# ===================================================================
def figure1_tail_trend(n1: dict) -> plt.Figure:
    dense = n1["subsets"]["DENSE"]

    # Extract yearly p95 for both series
    raw_stats = dense["series"]["raw_a"]["yearly_stats"]
    std_stats = dense["series"]["standardised"]["yearly_stats"]

    raw_trend = dense["series"]["raw_a"]["p95_ols_trend"]
    std_trend = dense["series"]["standardised"]["p95_ols_trend"]

    # Also pull FULL data for 2020-2024 (hollow markers)
    full = n1["subsets"].get("FULL", {})
    full_raw_stats = full.get("series", {}).get("raw_a", {}).get("yearly_stats", {})
    full_std_stats = full.get("series", {}).get("standardised", {}).get("yearly_stats", {})

    # Dense years: solid markers
    dense_years = sorted(int(y) for y in raw_stats.keys())
    raw_p95 = [raw_stats[str(y)]["p95"] for y in dense_years]
    std_p95 = [std_stats[str(y)]["p95"] for y in dense_years]

    # Extended years (2020+): hollow markers
    ext_years_raw, ext_p95_raw = [], []
    ext_years_std, ext_p95_std = [], []
    for y in sorted(int(k) for k in full_raw_stats.keys()):
        if y > 2019:
            ext_years_raw.append(y)
            ext_p95_raw.append(full_raw_stats[str(y)]["p95"])
    for y in sorted(int(k) for k in full_std_stats.keys()):
        if y > 2019:
            ext_years_std.append(y)
            ext_p95_std.append(full_std_stats[str(y)]["p95"])

    fig, ax = plt.subplots(figsize=FIGSIZE_SINGLE)

    # Dense points (filled)
    ax.plot(dense_years, raw_p95, "o-", color=COLOUR_RAW,
            markersize=7, linewidth=1.5, label="Raw severity", zorder=3)
    ax.plot(dense_years, std_p95, "s-", color=COLOUR_STD,
            markersize=7, linewidth=1.5, label="Mix-standardised severity", zorder=3)

    # Extended points (hollow)
    if ext_years_raw:
        ax.plot(ext_years_raw, ext_p95_raw, "o", color=COLOUR_RAW,
                markersize=7, markerfacecolor="white", markeredgewidth=1.5, zorder=3)
    if ext_years_std:
        ax.plot(ext_years_std, ext_p95_std, "s", color=COLOUR_STD,
                markersize=7, markerfacecolor="white", markeredgewidth=1.5, zorder=3)

    # Connect dense to extended with dashed line
    if ext_years_raw:
        ax.plot([dense_years[-1]] + ext_years_raw,
                [raw_p95[-1]] + ext_p95_raw,
                "--", color=COLOUR_RAW, linewidth=1, alpha=0.5, zorder=2)
    if ext_years_std:
        ax.plot([dense_years[-1]] + ext_years_std,
                [std_p95[-1]] + ext_p95_std,
                "--", color=COLOUR_STD, linewidth=1, alpha=0.5, zorder=2)

    # Regression lines over dense range
    x_fit = np.array(dense_years, dtype=float)
    ax.plot(x_fit,
            raw_trend["intercept"] + raw_trend["slope"] * x_fit,
            ":", color=COLOUR_RAW, linewidth=2, alpha=0.7)
    ax.plot(x_fit,
            std_trend["intercept"] + std_trend["slope"] * x_fit,
            ":", color=COLOUR_STD, linewidth=2, alpha=0.7)

    ax.set_xlabel("Year", fontsize=11)
    ax.set_ylabel("95th percentile severity", fontsize=11)
    ax.set_title("Raw vs mix-standardised tail severity trend", fontsize=12, fontweight="bold")
    ax.legend(fontsize=9, loc="upper left")
    ax.grid(True, alpha=0.3)

    # Annotate slope reduction
    raw_slope = raw_trend["slope"]
    std_slope = std_trend["slope"]
    reduction_pct = (1.0 - abs(std_slope) / abs(raw_slope)) * 100
    ax.annotate(
        f"Slope reduction: {reduction_pct:.0f}%\n"
        f"Raw: {raw_slope:.2f}/yr  Std: {std_slope:.2f}/yr",
        xy=(0.98, 0.98), xycoords="axes fraction",
        ha="right", va="top", fontsize=8,
        bbox=dict(boxstyle="round,pad=0.3", facecolor="wheat", alpha=0.8),
    )

    # Unified legend with hollow marker entries
    hollow_raw = Line2D([0], [0], marker="o", color=COLOUR_RAW, markersize=6,
                        markerfacecolor="white", markeredgewidth=1.5, linestyle="none")
    hollow_std = Line2D([0], [0], marker="s", color=COLOUR_STD, markersize=6,
                        markerfacecolor="white", markeredgewidth=1.5, linestyle="none")

    handles, labels = ax.get_legend_handles_labels()
    handles += [hollow_raw, hollow_std]
    labels += ["Raw (2020+, sparse panel)", "Std (2020+, sparse panel)"]
    ax.legend(handles, labels, fontsize=8, loc="upper left", framealpha=0.9)

    return fig


# ===================================================================
# FIGURE 2 — Tail Diagnostic: Mean Excess Function
# ===================================================================
def figure2_mean_excess(df: pd.DataFrame, n1: dict) -> plt.Figure:
    """Plot Mean Excess Function E[S - u | S > u] for raw vs standardised."""
    from scripts.stress_test.novelty.common.severity_projection import project_severity

    # Get reference portfolio mix from N1
    ref_mix = n1["reference_portfolio"]["mix"]

    # Compute standardised severity for each observation
    raw_sev = df["S_raw_a"].dropna().values
    raw_sev_pos = raw_sev[raw_sev > 0]

    # For standardised, use the full analysis table's standardised severity
    # Recompute from raw data using projection
    w_ref = np.array([ref_mix.get(lob, 0.0) for lob in [
        "Property", "Professional Lines", "Casualty", "Marine",
        "Reinsurance - Property", "Energy", "Motor", "Aviation",
        "Cyber", "Accident & Health", "Aggregate",
        "Reinsurance - Casualty", "Reinsurance - Specialty"
    ]])

    # Use projected severity where available
    std_values = []
    for _, row in df.iterrows():
        w_s = row.get("w_s_array")
        s_lob = row.get("s_lob")
        if w_s is not None and s_lob is not None:
            try:
                w_s = np.array(w_s)
                s_lob = np.array(s_lob)
                # project_severity: S_std = w_ref . s_lob
                s_std = float(np.dot(w_ref[:len(s_lob)], s_lob))
                std_values.append(s_std)
            except Exception:
                pass
    std_sev_pos = np.array([v for v in std_values if v > 0])

    fig, ax = plt.subplots(figsize=FIGSIZE_SINGLE)

    for sev_arr, colour, label in [
        (raw_sev_pos, COLOUR_RAW, "Raw severity"),
        (std_sev_pos, COLOUR_STD, "Mix-standardised severity"),
    ]:
        if len(sev_arr) < 10:
            continue
        sev_sorted = np.sort(sev_arr)
        # Use thresholds from 10th to 85th percentile
        thresholds = np.percentile(sev_sorted, np.linspace(5, 85, 40))
        mef = []
        n_exceed = []
        for u in thresholds:
            exceedances = sev_sorted[sev_sorted > u] - u
            if len(exceedances) >= 5:
                mef.append(np.mean(exceedances))
                n_exceed.append(len(exceedances))
            else:
                mef.append(np.nan)
                n_exceed.append(0)
        valid = ~np.isnan(mef)
        ax.plot(np.array(thresholds)[valid], np.array(mef)[valid],
                "o-", color=colour, markersize=4, linewidth=1.5, label=label)

    ax.set_xlabel("Threshold $u$", fontsize=11)
    ax.set_ylabel(r"$\mathrm{E}[S - u \mid S > u]$", fontsize=11)
    ax.set_title("Mean excess function: raw vs standardised", fontsize=12, fontweight="bold")
    ax.legend(fontsize=9)
    ax.grid(True, alpha=0.3)

    return fig


# ===================================================================
# FIGURE 3 — Size–Severity Scaling
# ===================================================================
def figure3_size_severity(df: pd.DataFrame, n3: dict) -> plt.Figure:
    """Scatter of log(reserve size) vs log(|severity|) with fitted regression."""
    valid = df.dropna(subset=["R_s", "S_raw_a"]).copy()
    valid = valid[valid["S_raw_a"].abs() > 0.001]  # exclude near-zero
    valid = valid[valid["R_s"] > 0]

    log_R = np.log(valid["R_s"].values)
    log_S = np.log(valid["S_raw_a"].abs().values)

    fig, ax = plt.subplots(figsize=FIGSIZE_SINGLE)

    # Bin the data for cleaner presentation
    n_bins = 15
    bin_edges = np.percentile(log_R, np.linspace(0, 100, n_bins + 1))
    bin_centres = []
    bin_means = []
    bin_q25 = []
    bin_q75 = []
    bin_counts = []

    for i in range(n_bins):
        mask = (log_R >= bin_edges[i]) & (log_R < bin_edges[i + 1])
        if i == n_bins - 1:
            mask = (log_R >= bin_edges[i]) & (log_R <= bin_edges[i + 1])
        if mask.sum() >= 3:
            bin_centres.append(np.mean(log_R[mask]))
            bin_means.append(np.mean(log_S[mask]))
            bin_q25.append(np.percentile(log_S[mask], 25))
            bin_q75.append(np.percentile(log_S[mask], 75))
            bin_counts.append(mask.sum())

    bin_centres = np.array(bin_centres)
    bin_means = np.array(bin_means)
    bin_q25 = np.array(bin_q25)
    bin_q75 = np.array(bin_q75)

    # Background scatter (faint)
    ax.scatter(log_R, log_S, alpha=0.12, s=15, color="grey", zorder=1,
              rasterized=True)

    # Binned means with IQR whiskers (clamp to non-negative)
    yerr_lo = np.maximum(bin_means - bin_q25, 0)
    yerr_hi = np.maximum(bin_q75 - bin_means, 0)
    ax.errorbar(bin_centres, bin_means,
                yerr=[yerr_lo, yerr_hi],
                fmt="o", color=COLOUR_RAW, markersize=7,
                capsize=3, linewidth=1.5, zorder=3,
                label="Binned mean (IQR)")

    # Fitted regression line from N3 M1 (event FE on signed severity)
    m1_dense = n3["model_results"]["DENSE"]["M1_event_fe"]
    beta = m1_dense["beta"]
    # For display: fit intercept from the binned data
    intercept_fit = np.mean(bin_means) - beta * np.mean(bin_centres)
    x_line = np.linspace(log_R.min(), log_R.max(), 100)
    ax.plot(x_line, intercept_fit + beta * x_line, "-",
            color=COLOUR_STD, linewidth=2.5, zorder=2,
            label=rf"$\hat{{\beta}}$ = {beta:.3f} (p = {m1_dense['pvalue']:.3f})")

    ax.set_xlabel("log(reserves, £m)", fontsize=11)
    ax.set_ylabel("log(|severity|)", fontsize=11)
    ax.set_title("Size--severity scaling relationship", fontsize=12, fontweight="bold")
    ax.legend(fontsize=9, loc="upper right")
    ax.grid(True, alpha=0.3)

    return fig


# ===================================================================
# TABLE 2 — Size Elasticity Estimates
# ===================================================================
def table2_size_elasticity(n3: dict) -> str:
    dense = n3["model_results"]["DENSE"]
    bk8 = n3["model_results"]["BALANCED_K8"]

    rows = [
        ("M0: No fixed effects",
         dense["M0_no_fe"]["beta"], dense["M0_no_fe"]["se"], dense["M0_no_fe"]["pvalue"]),
        ("M1: Event FE (signed $S$)",
         dense["M1_event_fe"]["beta"], dense["M1_event_fe"]["se"], dense["M1_event_fe"]["pvalue"]),
        (r"M2: Event FE ($\log|S|$)",
         dense["M2_log_abs"]["beta"], dense["M2_log_abs"]["se"], dense["M2_log_abs"]["pvalue"]),
        (r"M3: Event FE ($\log S^2$)",
         dense["M3_log_sq"]["beta"], dense["M3_log_sq"]["se"], dense["M3_log_sq"]["pvalue"]),
        ("M1: Balanced panel ($k \\geq 8$)",
         bk8["M1_event_fe"]["beta"], bk8["M1_event_fe"]["se"], bk8["M1_event_fe"]["pvalue"]),
    ]

    def _fmt_p(p):
        if p < 0.001:
            return f"$<$0.001"
        return f"{p:.3f}"

    def _stars(p):
        if p < 0.001:
            return "***"
        if p < 0.01:
            return "**"
        if p < 0.05:
            return "*"
        if p < 0.10:
            return r"\dag"
        return ""

    tex_lines = [
        r"\begin{table}[htbp]",
        r"\centering",
        r"\caption{Size--severity elasticity ($\beta$) estimates across model specifications.  DENSE subset (2014--2019, $n = 177$) unless otherwise noted.}",
        r"\label{tab:size_elasticity}",
        r"\begin{tabular}{lrrr}",
        r"\toprule",
        r"Model & $\hat{\beta}$ & Std.\ error & $p$-value \\",
        r"\midrule",
    ]
    for label, beta, se, p in rows:
        tex_lines.append(
            f"{label} & {beta:.3f}{_stars(p)} & {se:.3f} & {_fmt_p(p)} \\\\"
        )
    tex_lines += [
        r"\bottomrule",
        r"\multicolumn{4}{l}{\footnotesize $^{***}p<0.001$; $^{**}p<0.01$; $^{*}p<0.05$; $^{\dag}p<0.10$} \\",
        r"\end{tabular}",
        r"\end{table}",
    ]
    return "\n".join(tex_lines)


# ===================================================================
# TABLE 3 — Sampling Robustness (Novelty 0)
# ===================================================================
def table3_sampling_robustness(n0: dict) -> str:
    metrics = n0["metrics"]
    threshold = n0["stability_threshold"]

    label_map = {
        "p95_slope": "p95 trend slope",
        "beta": r"$\beta$ elasticity",
        "var995": "VaR 99.5\\%",
    }

    tex_lines = [
        r"\begin{table}[htbp]",
        r"\centering",
        r"\caption{Sampling robustness under 10\% leave-out resampling (200 iterations, DENSE subset).}",
        r"\label{tab:sampling_robustness}",
        r"\begin{tabular}{lrrrl}",
        r"\toprule",
        r"Metric & Estimate & SD & CV (\%) & Stability \\",
        r"\midrule",
    ]
    for key, mdata in metrics.items():
        label = label_map.get(key, key)
        point = mdata["point"]
        sd = mdata["sd"]
        cv = mdata["ratio_sd_point"] * 100
        stable = "Stable" if mdata["stable"] else "Unstable"
        tex_lines.append(
            f"{label} & {point:.3f} & {sd:.3f} & {cv:.1f} & {stable} \\\\"
        )
    tex_lines += [
        r"\bottomrule",
        rf"\multicolumn{{5}}{{l}}{{\footnotesize Stability threshold: CV $<$ {threshold:.0%}}} \\",
        r"\end{tabular}",
        r"\end{table}",
    ]
    return "\n".join(tex_lines)


# ===================================================================
# TABLE 4 — Capital Distortion Results (with bootstrap CIs)
# ===================================================================

def _bootstrap_distortion_cis(
    df: pd.DataFrame,
    w_q_dict: Dict[str, float],
    R_q: float,
    B: int = 500,
    seed: int = 42,
) -> Dict[str, Dict[str, Any]]:
    """Cluster bootstrap (syndicate) CIs on VaR 99.5% and attribution effects.

    Within each bootstrap replicate, all four severity distributions are
    re-projected from s_lob and w_q, so mix and size adjustments are
    recomputed per replicate.

    Returns dict with keys per method and per attribution effect,
    each containing {point, ci_lower, ci_upper}.
    """
    w_q = lob_weights_to_array(w_q_dict)
    beta_w = composite_beta(w_q)
    A_w = size_adjustment_factor(R_q, DEFAULT_REFERENCE_SIZE_M, beta_w)
    A_bar = size_adjustment_factor(R_q, DEFAULT_REFERENCE_SIZE_M, -0.20)

    valid = df.dropna(subset=["S_raw_a"]).copy()
    if len(valid) < 10:
        empty = {"point": None, "ci_lower": None, "ci_upper": None}
        return {k: dict(empty) for k in
                ["S_naive", "S_mix", "S_size", "S_mixsize",
                 "mix_effect", "size_effect"]}

    clusters = valid["syndicate_id"].unique()
    n_clusters = len(clusters)
    grouped = {c: valid.loc[valid["syndicate_id"] == c].index.tolist()
               for c in clusters}

    rng = np.random.default_rng(seed)

    def _compute_stats(sub_df):
        S_raw = sub_df["S_raw_a"].values.astype(np.float64)
        S_mix = np.array(
            [project_severity(w_q, np.array(s, dtype=np.float64))
             for s in sub_df["s_lob"].values],
            dtype=np.float64,
        )
        S_size = S_raw * A_bar
        S_mixsize = S_mix * A_w

        v_naive = np.percentile(S_raw, 99.5)
        v_mix = np.percentile(S_mix, 99.5)
        v_size = np.percentile(S_size, 99.5)
        v_full = np.percentile(S_mixsize, 99.5)
        mix_eff = v_mix - v_naive
        size_eff = v_full - v_mix
        return v_naive, v_mix, v_size, v_full, mix_eff, size_eff

    point_stats = _compute_stats(valid)

    boot_stats = np.empty((B, 6))
    for b in range(B):
        sampled = rng.choice(clusters, size=n_clusters, replace=True)
        idx = []
        for c in sampled:
            idx.extend(grouped[c])
        boot_df = valid.loc[idx]
        boot_stats[b] = _compute_stats(boot_df)

    result = {}
    names = ["S_naive", "S_mix", "S_size", "S_mixsize",
             "mix_effect", "size_effect"]
    for i, name in enumerate(names):
        lo = float(np.percentile(boot_stats[:, i], 2.5))
        hi = float(np.percentile(boot_stats[:, i], 97.5))
        result[name] = {
            "point": float(point_stats[i]),
            "ci_lower": lo,
            "ci_upper": hi,
        }
    return result


def _compute_all_distortion_cis(
    df: pd.DataFrame, B: int = 500, seed: int = 42,
) -> Dict[str, Dict[str, Dict[str, Any]]]:
    """Compute bootstrap CIs for all 6 portfolios on DENSE subset."""
    dense = df[df["year"].between(2014, 2019)].copy()

    portfolios = [
        ("property_heavy_small", PROPERTY_HEAVY, 200.0),
        ("property_heavy_medium", PROPERTY_HEAVY, 500.0),
        ("property_heavy_large", PROPERTY_HEAVY, 2000.0),
        ("casualty_heavy_small", CASUALTY_HEAVY, 200.0),
        ("casualty_heavy_medium", CASUALTY_HEAVY, 500.0),
        ("casualty_heavy_large", CASUALTY_HEAVY, 2000.0),
    ]

    result = {}
    for name, w_q_dict, R_q in portfolios:
        result[name] = _bootstrap_distortion_cis(
            dense, w_q_dict, R_q, B=B, seed=seed,
        )
    return result


def table4_capital_distortion(n4: dict, boot_cis: Dict) -> str:
    """Capital distortion with cluster-bootstrap 95% CIs on VaR 99.5%.

    Parameters
    ----------
    n4 : novelty4 JSON results (for point estimates and VaR 99%)
    boot_cis : output of _compute_all_distortion_cis()
    """
    dense = n4["subsets"]["DENSE"]["portfolios"]

    portfolio_display = [
        (r"Property-heavy (\pounds 200m)", "property_heavy_small"),
        (r"Property-heavy (\pounds 500m)", "property_heavy_medium"),
        (r"Property-heavy (\pounds 2000m)", "property_heavy_large"),
        (r"Casualty-heavy (\pounds 200m)", "casualty_heavy_small"),
        (r"Casualty-heavy (\pounds 500m)", "casualty_heavy_medium"),
        (r"Casualty-heavy (\pounds 2000m)", "casualty_heavy_large"),
    ]

    method_map = [
        ("Raw", "S_naive"),
        ("Mix-adjusted", "S_mix"),
        ("Size-adjusted", "S_size"),
        ("Full adjustment", "S_mixsize"),
    ]

    tex_lines = [
        r"\begin{table}[htbp]",
        r"\centering",
        r"\caption{Capital distortion from omitting exposure adjustments.  "
        r"VaR reported as severity (\% of reserves), DENSE subset.  "
        r"95\% CIs from 500 syndicate-cluster bootstrap replicates "
        r"(mix and size re-projection within each replicate).}",
        r"\label{tab:capital_distortion}",
        r"\begin{tabular}{llrrl}",
        r"\toprule",
        r"Portfolio & Method & VaR 99\% & VaR 99.5\% & 95\% CI \\",
        r"\midrule",
    ]

    for i, (display_name, key) in enumerate(portfolio_display):
        p = dense[key]
        ci_p = boot_cis[key]

        for j, (method_label, method_key) in enumerate(method_map):
            m = p["metrics"][method_key]
            v99 = m["VaR_99"]
            v995 = m["VaR_995"]
            name_col = display_name if j == 0 else ""

            ci = ci_p.get(method_key, {})
            if ci.get("ci_lower") is not None:
                ci_str = f"[{ci['ci_lower']:.1f}, {ci['ci_upper']:.1f}]"
            else:
                ci_str = "---"

            tex_lines.append(
                f"{name_col} & {method_label} & {v99:.2f} & {v995:.2f} & {ci_str} \\\\"
            )

        # Attribution effects row
        mix_ci = ci_p.get("mix_effect", {})
        size_ci = ci_p.get("size_effect", {})
        mix_pt = mix_ci.get("point")
        size_pt = size_ci.get("point")

        if mix_pt is not None:
            mix_str = (f"Mix effect: {mix_pt:+.1f} "
                       f"[{mix_ci['ci_lower']:+.1f}, {mix_ci['ci_upper']:+.1f}]")
        else:
            mix_str = ""
        if size_pt is not None:
            size_str = (f"Size effect: {size_pt:+.1f} "
                        f"[{size_ci['ci_lower']:+.1f}, {size_ci['ci_upper']:+.1f}]")
        else:
            size_str = ""

        tex_lines.append(
            rf" & \multicolumn{{4}}{{l}}{{\footnotesize {mix_str}; {size_str}}} \\"
        )

        if i < len(portfolio_display) - 1:
            tex_lines.append(r"\addlinespace")

    tex_lines += [
        r"\bottomrule",
        r"\end{tabular}",
        r"\end{table}",
    ]
    return "\n".join(tex_lines)


# ===================================================================
# FIGURE 4 — Capital Distortion: Stacked Decomposition
# ===================================================================
COLOUR_SIZE_PENALTY = "#ff7f0e"  # orange — size made VaR worse


def figure4_capital_decomposition(n4: dict) -> plt.Figure:
    """Stacked decomposition of Raw VaR into mix effect, size effect, and
    residual adjusted VaR.

    Each bar's total height equals Raw VaR 99.5%.  Three segments:
      bottom (red)    — adjusted VaR floor = min(Final, Mix-only)
      middle (grn/org) — |size effect| (green if size helped, orange if hurt)
      top (purple)     — mix reduction (always dominant)
    """
    dense = n4["subsets"]["DENSE"]["portfolios"]

    portfolio_groups = [
        ("Prop-heavy\n£200m", "property_heavy_small"),
        ("Prop-heavy\n£500m", "property_heavy_medium"),
        ("Prop-heavy\n£2bn", "property_heavy_large"),
        ("Cas-heavy\n£200m", "casualty_heavy_small"),
        ("Cas-heavy\n£500m", "casualty_heavy_medium"),
        ("Cas-heavy\n£2bn", "casualty_heavy_large"),
    ]

    x = np.arange(len(portfolio_groups))
    width = 0.55

    # Extract values
    seg_base = []      # bottom red segment
    seg_size = []      # middle |size effect|
    seg_mix = []       # top mix reduction
    size_helped = []   # True if size reduced VaR
    final_vals = []

    for _, pkey in portfolio_groups:
        raw = dense[pkey]["metrics"]["S_naive"]["VaR_995"]
        mix_only = dense[pkey]["metrics"]["S_mix"]["VaR_995"]
        full = dense[pkey]["metrics"]["S_mixsize"]["VaR_995"]

        base = min(full, mix_only)
        size_eff = abs(full - mix_only)
        mix_red = raw - max(full, mix_only)

        seg_base.append(base)
        seg_size.append(size_eff)
        seg_mix.append(mix_red)
        size_helped.append(full < mix_only)
        final_vals.append(full)

    seg_base = np.array(seg_base)
    seg_size = np.array(seg_size)
    seg_mix = np.array(seg_mix)

    fig, ax = plt.subplots(figsize=(7, 5))

    # 1. Base segment (red) — adjusted VaR floor
    ax.bar(x, seg_base, width, color=COLOUR_STD, label="Adjusted VaR", zorder=3)

    # 2. Size-effect segment — green (credit) or orange (penalty) per bar
    for i in range(len(x)):
        if seg_size[i] < 0.005:
            continue  # skip negligible (reference size)
        colour = COLOUR_SIZE if size_helped[i] else COLOUR_SIZE_PENALTY
        ax.bar(x[i], seg_size[i], width, bottom=seg_base[i],
               color=colour, zorder=3)

    # 3. Mix-reduction segment (purple) — always the big one
    ax.bar(x, seg_mix, width, bottom=seg_base + seg_size,
           color=COLOUR_MIX, alpha=0.85, label="Mix effect (removed)", zorder=3)

    # Annotate each bar: adjusted VaR inside red segment, mix reduction in yellow
    for i in range(len(x)):
        fv = final_vals[i]
        mix_mid = (seg_base[i] + seg_size[i] + seg_base[i] + seg_size[i] + seg_mix[i]) / 2
        # Adjusted VaR label with arrow into red segment
        ax.annotate(
            f"Adj {fv:.1f}%",
            xy=(x[i], fv / 2), ha="center", va="center",
            fontsize=6.5, fontweight="bold", color="white",
        )
        # Mix reduction label centred in yellow segment
        ax.annotate(
            f"\u2212{seg_mix[i]:.0f}pp",
            xy=(x[i], mix_mid), ha="center", va="center",
            fontsize=8, fontweight="bold", color="#444444",
        )

    # Horizontal line at Raw VaR level
    raw_val = dense["property_heavy_small"]["metrics"]["S_naive"]["VaR_995"]
    ax.axhline(raw_val, color="grey", linewidth=0.8, linestyle="--", zorder=2)
    ax.text(x[0] - 0.42, raw_val - 0.8, f"Raw VaR = {raw_val:.0f}%",
            ha="left", va="top", fontsize=8, color="grey")

    # Build legend with all four entries
    legend_handles = [
        Patch(facecolor=COLOUR_MIX, alpha=0.85, label="Mix effect (removed)"),
        Patch(facecolor=COLOUR_SIZE, label="Size credit (large)"),
        Patch(facecolor=COLOUR_SIZE_PENALTY, label="Size penalty (small)"),
        Patch(facecolor=COLOUR_STD, label="Adjusted VaR"),
    ]
    ax.legend(handles=legend_handles, fontsize=8, loc="upper left",
              bbox_to_anchor=(0.0, -0.18), ncol=2, frameon=False)

    ax.set_xlabel("Portfolio", fontsize=11)
    ax.set_ylabel("VaR 99.5% (% of reserves)", fontsize=11)
    ax.set_title("Decomposition of capital distortion", fontsize=12, fontweight="bold")
    ax.set_xticks(x)
    ax.set_xticklabels([name for name, _ in portfolio_groups], fontsize=8)
    ax.grid(True, axis="y", alpha=0.3, zorder=0)
    ax.set_ylim(0, raw_val * 1.08)

    return fig


# ===================================================================
# FIGURE 5 — LoB-level β: Raw vs James–Stein Shrinkage
# ===================================================================
def figure5_lob_shrinkage(n3: dict) -> plt.Figure:
    """Dot plot showing raw LoB-level β estimates with SEs, shrunk
    estimates, and the grand mean.  Arrows connect raw → shrunk to
    visualise the direction and magnitude of shrinkage."""
    dense_lob = n3["lob_betas"]["DENSE"]
    raw = dense_lob["raw_betas"]
    ses = dense_lob["raw_ses"]
    shrunk = dense_lob["shrunk_betas"]
    lambdas = dense_lob["shrinkage_lambdas"]
    grand_mean = dense_lob["grand_mean"]

    lobs = list(raw.keys())
    n_lobs = len(lobs)
    y = np.arange(n_lobs)

    raw_vals = np.array([raw[l] for l in lobs])
    se_vals = np.array([ses[l] for l in lobs])
    shrunk_vals = np.array([shrunk[l] for l in lobs])
    lam_vals = np.array([lambdas[l] for l in lobs])

    fig, ax = plt.subplots(figsize=(7, 4))

    # Grand mean reference line
    ax.axvline(grand_mean, color="grey", linewidth=1, linestyle="--", zorder=1)
    ax.annotate(f"Grand mean ({grand_mean:.3f})",
                xy=(grand_mean, 1.0), xycoords=("data", "axes fraction"),
                xytext=(5, -5), textcoords="offset points",
                fontsize=7, color="grey", ha="left", va="top")

    # Zero reference
    ax.axvline(0, color="black", linewidth=0.5, zorder=1)

    # Raw estimates with SE bars
    ax.errorbar(raw_vals, y, xerr=1.96 * se_vals, fmt="o",
                color=COLOUR_RAW, markersize=7, capsize=3, linewidth=1.2,
                label="Raw $\\hat{\\beta}_\\ell$ (95% CI)", zorder=3)

    # Shrunk estimates
    ax.scatter(shrunk_vals, y, marker="D", s=50, color=COLOUR_STD,
               zorder=4, label="James–Stein shrunk $\\tilde{\\beta}_\\ell$")

    # Arrows from raw to shrunk
    for i in range(n_lobs):
        ax.annotate("", xy=(shrunk_vals[i], y[i]),
                     xytext=(raw_vals[i], y[i]),
                     arrowprops=dict(arrowstyle="->", color="#888888",
                                     linewidth=1, shrinkA=4, shrinkB=3))
        # Shrinkage factor annotation — to the right of the shrunk marker
        label_x = shrunk_vals[i] + 0.008
        ax.text(label_x, y[i] + 0.25,
                f"$\\lambda$={lam_vals[i]:.2f}",
                fontsize=6.5, ha="left", va="top", color="#666666")

    ax.set_yticks(y)
    ax.set_yticklabels(lobs, fontsize=9)
    ax.set_xlabel("Size–severity elasticity $\\beta_\\ell$", fontsize=11)
    ax.set_title("LoB-level $\\beta$: raw vs empirical Bayes shrinkage",
                 fontsize=12, fontweight="bold")
    ax.legend(fontsize=8, loc="lower left")
    ax.grid(True, axis="x", alpha=0.3)
    ax.invert_yaxis()

    return fig


# ===================================================================
# LOCAL-DONOR SENSITIVITY ANALYSIS
# ===================================================================

def _hellinger_distance(p: np.ndarray, q: np.ndarray) -> float:
    """Hellinger distance between two discrete distributions.

    H(p, q) = (1/√2) · ‖√p − √q‖₂    ∈ [0, 1]
    """
    sp = np.sqrt(np.clip(p, 0, None))
    sq = np.sqrt(np.clip(q, 0, None))
    return float(np.sqrt(0.5 * np.sum((sp - sq) ** 2)))


def _local_donor_analysis(
    df: pd.DataFrame,
    w_q_dict: Dict[str, float],
    R_q: float,
    thresholds: List[float],
) -> List[Dict[str, Any]]:
    """Compute VaR 99.5% (raw and adjusted) restricting donors by Hellinger distance.

    Parameters
    ----------
    df : analysis table (DENSE subset, with S_raw_a, w_s_array, s_lob columns)
    w_q_dict : target portfolio LoB weights
    R_q : target portfolio reserve size £m
    thresholds : Hellinger-distance thresholds to sweep

    Returns
    -------
    List of dicts, one per threshold, with keys:
        h_max, n_donors, var995_raw, var995_adj, var99_raw, var99_adj
    """
    w_q = lob_weights_to_array(w_q_dict)
    w_q_sum = w_q.sum()
    if w_q_sum > 0:
        w_q_norm = w_q / w_q_sum
    else:
        w_q_norm = w_q

    valid = df.dropna(subset=["S_raw_a"]).copy()
    # Pre-compute w_s arrays (normalised) for distance calculation
    ws_arrays = []
    for _, row in valid.iterrows():
        ws = row.get("w_s_array")
        if ws is not None:
            ws = np.array(ws, dtype=np.float64)
            ws_sum = ws.sum()
            ws_arrays.append(ws / ws_sum if ws_sum > 0 else ws)
        else:
            ws_arrays.append(np.zeros(N_LOBS))
    ws_arrays = np.array(ws_arrays)

    # Compute Hellinger distance from each donor to query
    distances = np.array([_hellinger_distance(ws, w_q_norm) for ws in ws_arrays])

    beta_w = composite_beta(w_q)
    A_w = size_adjustment_factor(R_q, DEFAULT_REFERENCE_SIZE_M, beta_w)

    results = []
    for h_max in thresholds:
        mask = distances <= h_max
        n_donors = int(mask.sum())

        if n_donors < 10:
            results.append({
                "h_max": h_max, "n_donors": n_donors,
                "var995_raw": None, "var995_adj": None,
                "var99_raw": None, "var99_adj": None,
            })
            continue

        sub = valid.loc[mask]
        S_raw = sub["S_raw_a"].values.astype(np.float64)
        S_mix = np.array(
            [project_severity(w_q, np.array(s, dtype=np.float64))
             for s in sub["s_lob"].values],
            dtype=np.float64,
        )
        S_adj = S_mix * A_w

        results.append({
            "h_max": h_max,
            "n_donors": n_donors,
            "var995_raw": float(np.percentile(S_raw, 99.5)),
            "var995_adj": float(np.percentile(S_adj, 99.5)),
            "var99_raw": float(np.percentile(S_raw, 99.0)),
            "var99_adj": float(np.percentile(S_adj, 99.0)),
        })

    return results


def _run_local_donor_sensitivity(df: pd.DataFrame) -> Dict[str, Any]:
    """Run the full local-donor sensitivity for all target portfolios.

    Operates on DENSE subset (2014-2019).
    """
    dense = df[df["year"].between(2014, 2019)].copy()

    thresholds = [0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90, 1.0]

    portfolios = [
        ("property_heavy_small", PROPERTY_HEAVY, 200.0),
        ("property_heavy_medium", PROPERTY_HEAVY, 500.0),
        ("property_heavy_large", PROPERTY_HEAVY, 2000.0),
        ("casualty_heavy_small", CASUALTY_HEAVY, 200.0),
        ("casualty_heavy_medium", CASUALTY_HEAVY, 500.0),
        ("casualty_heavy_large", CASUALTY_HEAVY, 2000.0),
    ]

    out: Dict[str, Any] = {"thresholds": thresholds, "portfolios": {}}

    for name, w_q_dict, R_q in portfolios:
        rows = _local_donor_analysis(dense, w_q_dict, R_q, thresholds)
        out["portfolios"][name] = {
            "w_q": w_q_dict,
            "R_q": R_q,
            "results": rows,
        }

    return out


# ===================================================================
# TABLE 5 — Local-Donor Sensitivity
# ===================================================================
def table5_local_donor_sensitivity(sens: Dict[str, Any]) -> str:
    """LaTeX table: VaR 99.5% at each Hellinger-distance threshold."""
    all_thresholds = sens["thresholds"]
    # Select a readable subset for the table
    show_thresholds = [h for h in all_thresholds if h in (0.40, 0.50, 0.60, 0.70, 0.80, 1.0)]
    if not show_thresholds:
        show_thresholds = all_thresholds

    # Show two representative portfolios at the reference size (£500m)
    display_portfolios = [
        (r"Property-heavy (\pounds 500m)", "property_heavy_medium"),
        (r"Casualty-heavy (\pounds 500m)", "casualty_heavy_medium"),
    ]

    thresholds = show_thresholds
    # Build header
    h_cols = " & ".join([f"$H \\leq {h:.2f}$" for h in thresholds])
    tex_lines = [
        r"\begin{table}[htbp]",
        r"\centering",
        r"\caption{Local-donor sensitivity: VaR 99.5\% (\% of reserves) by Hellinger-distance restriction on source LoB mix.  $H=1.0$ is unrestricted; lower $H$ retains only mix-similar donors.  Non-monotonicity in Raw confirms that a few mix-dissimilar syndicates drive the unadjusted tail.  DENSE subset.}",
        r"\label{tab:local_donor}",
        r"\begin{tabular}{ll" + "r" * len(thresholds) + "}",
        r"\toprule",
        f"Portfolio & Series & {h_cols} \\\\",
        r"\midrule",
    ]

    for i, (display_name, key) in enumerate(display_portfolios):
        all_results = sens["portfolios"][key]["results"]
        # Filter to shown thresholds
        pdata = [r for r in all_results if r["h_max"] in thresholds]

        # Row 1: n donors
        n_vals = " & ".join(
            [str(r["n_donors"]) if r["n_donors"] else "---" for r in pdata]
        )
        tex_lines.append(f"{display_name} & $n$ donors & {n_vals} \\\\")

        # Row 2: raw VaR 99.5
        raw_vals = " & ".join(
            [f"{r['var995_raw']:.2f}" if r["var995_raw"] is not None else "---"
             for r in pdata]
        )
        tex_lines.append(f" & Raw & {raw_vals} \\\\")

        # Row 3: adjusted VaR 99.5
        adj_vals = " & ".join(
            [f"{r['var995_adj']:.2f}" if r["var995_adj"] is not None else "---"
             for r in pdata]
        )
        tex_lines.append(f" & Adjusted & {adj_vals} \\\\")

        if i < len(display_portfolios) - 1:
            tex_lines.append(r"\addlinespace")

    tex_lines += [
        r"\bottomrule",
        r"\end{tabular}",
        r"\end{table}",
    ]
    return "\n".join(tex_lines)


# ===================================================================
# FIGURE 6 — Local-Donor Convergence
# ===================================================================
def figure6_local_donor(sens: Dict[str, Any]) -> plt.Figure:
    """Show raw VaR converging toward adjusted VaR as donor pool tightens.

    Two panels: property-heavy (left), casualty-heavy (right).
    Each panel overlays all three sizes with distinct markers.
    X-axis: Hellinger threshold (tighter → left).
    """
    panel_specs = [
        ("Property-heavy", [
            ("£200m", "property_heavy_small", "o", "-"),
            ("£500m", "property_heavy_medium", "s", "-"),
            ("£2bn", "property_heavy_large", "D", "-"),
        ]),
        ("Casualty-heavy", [
            ("£200m", "casualty_heavy_small", "o", "-"),
            ("£500m", "casualty_heavy_medium", "s", "-"),
            ("£2bn", "casualty_heavy_large", "D", "-"),
        ]),
    ]

    fig, axes = plt.subplots(1, 2, figsize=(10, 4.5), sharey=True)

    for ax, (panel_title, portfolios) in zip(axes, panel_specs):
        for size_label, key, marker, ls in portfolios:
            pdata = sens["portfolios"][key]["results"]
            hs = [r["h_max"] for r in pdata if r["var995_raw"] is not None]
            raw = [r["var995_raw"] for r in pdata if r["var995_raw"] is not None]
            adj = [r["var995_adj"] for r in pdata if r["var995_adj"] is not None]
            n_don = [r["n_donors"] for r in pdata if r["var995_raw"] is not None]

            if not hs:
                continue

            # Raw: blue family
            ax.plot(hs, raw, marker=marker, linestyle=ls, color=COLOUR_RAW,
                    markersize=6, linewidth=1.5, alpha=0.7, zorder=3)
            # Adjusted: red family
            ax.plot(hs, adj, marker=marker, linestyle=ls, color=COLOUR_STD,
                    markersize=6, linewidth=1.5, alpha=0.7, zorder=3)

            # Donor-count annotations on the topmost (raw) line only for £500m
            if size_label == "£500m":
                for h, r_val, n in zip(hs, raw, n_don):
                    ax.annotate(f"n={n}", xy=(h, r_val), xytext=(0, 8),
                                textcoords="offset points", fontsize=6,
                                ha="center", color="#666666")

        ax.set_xlabel("Hellinger distance threshold $H_{\\max}$", fontsize=10)
        ax.set_title(panel_title, fontsize=11, fontweight="bold")
        ax.grid(True, alpha=0.3)
        ax.invert_xaxis()

    axes[0].set_ylabel("VaR 99.5% (% of reserves)", fontsize=10)

    # Build a combined legend
    raw_line = Line2D([], [], color=COLOUR_RAW, linewidth=1.5, label="Raw VaR 99.5%")
    adj_line = Line2D([], [], color=COLOUR_STD, linewidth=1.5, label="Adjusted VaR 99.5%")
    m200 = Line2D([], [], color="grey", marker="o", linestyle="None", markersize=6, label="£200m")
    m500 = Line2D([], [], color="grey", marker="s", linestyle="None", markersize=6, label="£500m")
    m2bn = Line2D([], [], color="grey", marker="D", linestyle="None", markersize=6, label="£2bn")
    axes[0].legend(handles=[raw_line, adj_line, m200, m500, m2bn],
                   fontsize=7.5, loc="upper left", ncol=2)

    fig.suptitle("Local-donor restriction: raw VaR converges to adjusted VaR",
                 fontsize=12, fontweight="bold", y=1.02)
    fig.tight_layout()
    return fig


# ===================================================================
# Main
# ===================================================================
def main():
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    logger.info("Loading data...")
    df = _load_analysis_table()
    n0 = _load_json(N0_PATH)
    n1 = _load_json(N1_PATH)
    n2 = _load_json(N2_PATH)
    n3 = _load_json(N3_PATH)
    n4 = _load_json(N4_PATH)

    # Tables
    logger.info("--- Table 1: Corpus Summary ---")
    tex1 = table1_corpus_summary(df)
    _save_tex(tex1, "table1_corpus_summary.tex")

    logger.info("--- Table 2: Size Elasticity ---")
    tex2 = table2_size_elasticity(n3)
    _save_tex(tex2, "table2_size_elasticity.tex")

    logger.info("--- Table 3: Sampling Robustness ---")
    tex3 = table3_sampling_robustness(n0)
    _save_tex(tex3, "table3_sampling_robustness.tex")

    logger.info("--- Table 4: Capital Distortion (computing bootstrap CIs) ---")
    boot_cis = _compute_all_distortion_cis(df, B=500, seed=42)
    tex4 = table4_capital_distortion(n4, boot_cis)
    _save_tex(tex4, "table4_capital_distortion.tex")

    # Figures
    logger.info("--- Figure 1: Raw vs Standardised Tail Trend ---")
    fig1 = figure1_tail_trend(n1)
    _save_fig(fig1, "figure1_tail_trend.pdf")
    fig1b = figure1_tail_trend(n1)
    _save_fig(fig1b, "figure1_tail_trend.png")

    logger.info("--- Figure 2: Mean Excess Function ---")
    fig2 = figure2_mean_excess(df, n1)
    _save_fig(fig2, "figure2_mean_excess.pdf")
    fig2b = figure2_mean_excess(df, n1)
    _save_fig(fig2b, "figure2_mean_excess.png")

    logger.info("--- Figure 3: Size-Severity Scaling ---")
    fig3 = figure3_size_severity(df, n3)
    _save_fig(fig3, "figure3_size_severity.pdf")
    fig3b = figure3_size_severity(df, n3)
    _save_fig(fig3b, "figure3_size_severity.png")

    logger.info("--- Figure 4: Capital Distortion Decomposition ---")
    fig4 = figure4_capital_decomposition(n4)
    _save_fig(fig4, "figure4_capital_decomposition.pdf")
    fig4b = figure4_capital_decomposition(n4)
    _save_fig(fig4b, "figure4_capital_decomposition.png")

    logger.info("--- Figure 5: LoB Shrinkage ---")
    fig5 = figure5_lob_shrinkage(n3)
    _save_fig(fig5, "figure5_lob_shrinkage.pdf")
    fig5b = figure5_lob_shrinkage(n3)
    _save_fig(fig5b, "figure5_lob_shrinkage.png")

    # Local-donor sensitivity analysis (computed live from the analysis table)
    logger.info("--- Local-Donor Sensitivity Analysis ---")
    sens = _run_local_donor_sensitivity(df)

    # Save JSON results
    sens_path = OUTPUT_DIR / "local_donor_sensitivity.json"
    with open(sens_path, "w", encoding="utf-8") as f:
        json.dump(sens, f, indent=2, ensure_ascii=False)
    logger.info(f"Wrote {sens_path}")

    logger.info("--- Table 5: Local-Donor Sensitivity ---")
    tex5 = table5_local_donor_sensitivity(sens)
    _save_tex(tex5, "table5_local_donor_sensitivity.tex")

    logger.info("--- Figure 6: Local-Donor Convergence ---")
    fig6 = figure6_local_donor(sens)
    _save_fig(fig6, "figure6_local_donor.pdf")
    fig6b = figure6_local_donor(sens)
    _save_fig(fig6b, "figure6_local_donor.png")

    logger.info("\nAll outputs written to %s", OUTPUT_DIR)
    logger.info("  5 tables (.tex)")
    logger.info("  6 figures (.pdf + .png)")


if __name__ == "__main__":
    main()
