"""Run all novelty analyses in sequence.

Builds the analysis table once, caches it, then runs Novelties 0–4.
Each novelty writes its own JSON results to results/ and figures to fig/.

Usage:
    python scripts/stress_test/novelty/run_all.py
    python scripts/stress_test/novelty/run_all.py --skip 0 2   # skip novelties 0 and 2
    python scripts/stress_test/novelty/run_all.py --only 1 4    # run only novelties 1 and 4
    python scripts/stress_test/novelty/run_all.py --bootstrap-B 200 --seed 123
"""

import sys
import json
import time
import logging
import argparse
import traceback
from pathlib import Path

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
_this_dir = Path(__file__).resolve().parent
_stress_test_dir = _this_dir.parent
if str(_stress_test_dir) not in sys.path:
    sys.path.insert(0, str(_stress_test_dir))
if str(_this_dir) not in sys.path:
    sys.path.insert(0, str(_this_dir))

from common.analysis_table import (
    build_analysis_table,
    load_or_build,
    audit_merge,
    get_subset,
    add_query_columns,
    compute_cap_binding_stats,
    CoverageStats,
)
from common.severity_projection import lob_weights_to_array
from common.query_portfolios import compute_market_average_mix

logger = logging.getLogger("run_all")

FIG_DIR = _this_dir / "fig"
RESULTS_DIR = _this_dir / "results"
CACHE_PATH = _this_dir / "results" / "_analysis_table.pkl"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _json_default(obj):
    """JSON serialiser fallback for numpy/Path/etc."""
    import numpy as np
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, set):
        return sorted(obj)
    return str(obj)


def _elapsed(t0: float) -> str:
    """Format elapsed time."""
    dt = time.time() - t0
    if dt < 60:
        return f"{dt:.1f}s"
    return f"{dt / 60:.1f}m"


# ---------------------------------------------------------------------------
# Individual novelty runners
# ---------------------------------------------------------------------------

def run_novelty_0(cache_path: str, seed: int, **kwargs) -> dict:
    """Novelty 0: Sampling sensitivity (leave-p-out)."""
    from novelty_0_sampling_sensitivity import run as n0_run
    return n0_run(
        n_iter=kwargs.get("n_iter", 200),
        drop_frac=0.10,
        seed=seed,
        subset="DENSE",
        cache_path=cache_path,
    )


def run_novelty_1(cache_path: str, **kwargs) -> dict:
    """Novelty 1: Mix drift vs true worsening."""
    from novelty_1_mix_trend import run as n1_run
    return n1_run(cache_path=cache_path)


def run_novelty_2(df, bootstrap_B: int, seed: int, **kwargs) -> dict:
    """Novelty 2: Tail stability — rolling windows."""
    from novelty_2_tail_stability import (
        run_tail_stability,
        plot_tail_ratio_rolling,
        plot_mef_rolling,
    )

    # Prepare reference mix (same logic as novelty_2 main())
    ref_query_name = "ref"
    market_mix = compute_market_average_mix(df, "dense")
    w_q_ref = lob_weights_to_array(market_mix)
    df = add_query_columns(df, w_q=w_q_ref, R_q=500.0, query_name=ref_query_name)

    # Subset to FULL
    df_full, cov_full = get_subset(df, "FULL")

    # Run analysis
    analysis = run_tail_stability(
        df_full,
        ref_query_name=ref_query_name,
        bootstrap_B=bootstrap_B,
        seed=seed,
    )

    # Plots
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    plot_tail_ratio_rolling(analysis, FIG_DIR / "novelty2_tail_ratio_full.png")
    plot_mef_rolling(analysis, FIG_DIR / "novelty2_mef_full.png")

    # JSON output
    output = {
        "analysis": "novelty_2_tail_stability",
        "coverage": cov_full.to_dict(),
        "cap_binding": compute_cap_binding_stats(df_full),
        **analysis,
    }
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RESULTS_DIR / "novelty2_tail_stability.json"
    with open(str(out_path), "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, default=_json_default)
    logger.info("Novelty 2 results → %s", out_path)

    return output


def run_novelty_3(df, **kwargs) -> dict:
    """Novelty 3: Size scaling validation."""
    from novelty_3_size_scaling_validation import (
        run_size_validation,
        plot_loglog_scatter,
        plot_beta_comparison,
        plot_lob_betas,
    )

    results = run_size_validation(df)
    reg_df = results.pop("_regression_df")
    model_results = results["model_results"]
    lob_betas = results["lob_betas"]

    # Plots
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    plot_loglog_scatter(reg_df, FIG_DIR / "novelty3_loglog_scatter.png")
    plot_beta_comparison(model_results, FIG_DIR / "novelty3_beta_comparison.png")

    lob_plot_subset = "FULL" if "FULL" in lob_betas else "DENSE"
    plot_lob_betas(lob_betas, lob_plot_subset, FIG_DIR / "novelty3_lob_betas.png")

    # JSON output
    output = {
        "analysis": "novelty_3_size_scaling_validation",
        **results,
    }
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RESULTS_DIR / "novelty3_size_validation.json"
    with open(str(out_path), "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, default=_json_default)
    logger.info("Novelty 3 results → %s", out_path)

    return output


def run_novelty_4(cache_path: str, bootstrap_B: int, seed: int, **kwargs) -> dict:
    """Novelty 4: Capital distortion."""
    from novelty_4_capital_distortion import run_analysis as n4_run
    return n4_run(
        cache_path=cache_path,
        bootstrap_B=bootstrap_B,
        seed=seed,
    )


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

NOVELTIES = {
    0: ("Sampling sensitivity (leave-p-out)", run_novelty_0),
    1: ("Mix drift vs true worsening", run_novelty_1),
    2: ("Tail stability (rolling windows)", run_novelty_2),
    3: ("Size scaling validation", run_novelty_3),
    4: ("Capital distortion", run_novelty_4),
}


def run_all(
    novelties: list[int] | None = None,
    bootstrap_B: int = 500,
    seed: int = 42,
    n_iter: int = 200,
    cache_path: str | None = None,
) -> dict:
    """Run selected (or all) novelty analyses.

    Parameters
    ----------
    novelties : list of novelty numbers to run (0–4). None = all.
    bootstrap_B : bootstrap replicates for novelties 2 and 4.
    seed : random seed.
    n_iter : leave-p-out iterations for novelty 0.
    cache_path : path to pickle cache for analysis table.

    Returns
    -------
    Dict with per-novelty results and timing.
    """
    if novelties is None:
        novelties = sorted(NOVELTIES.keys())

    if cache_path is None:
        cache_path = str(CACHE_PATH)

    FIG_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Step 1: Build analysis table (shared across all novelties)
    # ------------------------------------------------------------------
    t0 = time.time()
    logger.info("=" * 70)
    logger.info("BUILDING ANALYSIS TABLE")
    logger.info("=" * 70)
    df = load_or_build(cache_path=cache_path)
    audit = audit_merge(df, output_path=str(RESULTS_DIR / "analysis_table_audit.json"))
    logger.info(
        "Table: %d rows, %d syndicates, years %d–%d  [%s]",
        len(df), df["syndicate_id"].nunique(),
        df["year"].min(), df["year"].max(),
        _elapsed(t0),
    )

    # ------------------------------------------------------------------
    # Step 2: Run each novelty
    # ------------------------------------------------------------------
    summary = {
        "table_rows": len(df),
        "table_syndicates": int(df["syndicate_id"].nunique()),
        "merge_audit": audit,
        "novelties": {},
    }

    for n_id in novelties:
        if n_id not in NOVELTIES:
            logger.warning("Unknown novelty %d — skipping", n_id)
            continue

        desc, runner = NOVELTIES[n_id]
        logger.info("")
        logger.info("=" * 70)
        logger.info("NOVELTY %d: %s", n_id, desc)
        logger.info("=" * 70)

        t_start = time.time()
        try:
            # Novelties 0, 1, 4 manage their own data loading via cache_path.
            # Novelties 2, 3 take the DataFrame directly.
            if n_id in (0,):
                result = runner(
                    cache_path=cache_path, seed=seed, n_iter=n_iter,
                )
            elif n_id in (1,):
                result = runner(cache_path=cache_path)
            elif n_id in (2,):
                result = runner(
                    df=df.copy(), bootstrap_B=bootstrap_B, seed=seed,
                )
            elif n_id in (3,):
                result = runner(df=df.copy())
            elif n_id in (4,):
                result = runner(
                    cache_path=cache_path, bootstrap_B=bootstrap_B, seed=seed,
                )
            else:
                result = runner(cache_path=cache_path)

            elapsed = _elapsed(t_start)
            logger.info("Novelty %d completed in %s", n_id, elapsed)
            summary["novelties"][n_id] = {
                "status": "ok",
                "elapsed": elapsed,
                "description": desc,
            }

        except Exception as e:
            elapsed = _elapsed(t_start)
            tb = traceback.format_exc()
            logger.error("Novelty %d FAILED after %s: %s", n_id, elapsed, e)
            logger.debug(tb)
            summary["novelties"][n_id] = {
                "status": "error",
                "elapsed": elapsed,
                "description": desc,
                "error": str(e),
                "traceback": tb,
            }

    # ------------------------------------------------------------------
    # Step 3: Summary
    # ------------------------------------------------------------------
    total_elapsed = _elapsed(t0)
    n_ok = sum(1 for v in summary["novelties"].values() if v["status"] == "ok")
    n_err = sum(1 for v in summary["novelties"].values() if v["status"] == "error")

    logger.info("")
    logger.info("=" * 70)
    logger.info("ALL DONE  [%s total]", total_elapsed)
    logger.info("=" * 70)
    logger.info("  %d/%d succeeded, %d failed", n_ok, n_ok + n_err, n_err)
    for n_id in sorted(summary["novelties"]):
        info = summary["novelties"][n_id]
        marker = "OK" if info["status"] == "ok" else "FAIL"
        logger.info(
            "  [%s] Novelty %d: %s  (%s)",
            marker, n_id, info["description"], info["elapsed"],
        )

    # Write summary
    summary_path = RESULTS_DIR / "run_all_summary.json"
    summary["total_elapsed"] = total_elapsed
    with open(str(summary_path), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, default=_json_default)
    logger.info("Summary → %s", summary_path)

    return summary


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Run all novelty analyses (0–4) for exposure adjustment validation.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  python run_all.py                     # run everything
  python run_all.py --skip 0            # skip sampling sensitivity (slow)
  python run_all.py --only 1 4          # run mix-trend and capital-distortion only
  python run_all.py --bootstrap-B 100   # fewer bootstrap replicates (faster)
""",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--skip", type=int, nargs="+", default=[],
        help="Novelty numbers to skip (e.g. --skip 0 2).",
    )
    group.add_argument(
        "--only", type=int, nargs="+", default=None,
        help="Run only these novelties (e.g. --only 1 4).",
    )
    parser.add_argument(
        "--bootstrap-B", type=int, default=500,
        help="Bootstrap replicates for novelties 2 and 4 (default 500).",
    )
    parser.add_argument(
        "--seed", type=int, default=42,
        help="Random seed (default 42).",
    )
    parser.add_argument(
        "--n-iter", type=int, default=200,
        help="Leave-p-out iterations for novelty 0 (default 200).",
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
        format="%(asctime)s %(levelname)-5s [%(name)s] %(message)s",
    )

    # Determine which novelties to run
    if args.only is not None:
        novelties = sorted(set(args.only))
    else:
        novelties = sorted(set(NOVELTIES.keys()) - set(args.skip))

    logger.info("Will run novelties: %s", novelties)

    summary = run_all(
        novelties=novelties,
        bootstrap_B=args.bootstrap_B,
        seed=args.seed,
        n_iter=args.n_iter,
        cache_path=args.cache,
    )

    # Print final report to stdout
    print("\n" + "=" * 70)
    print("NOVELTY ANALYSIS RESULTS")
    print("=" * 70)
    print(f"Analysis table: {summary['table_rows']} rows, "
          f"{summary['table_syndicates']} syndicates")
    print(f"Total elapsed: {summary['total_elapsed']}")
    print()
    for n_id in sorted(summary["novelties"]):
        info = summary["novelties"][n_id]
        status = "PASS" if info["status"] == "ok" else "FAIL"
        print(f"  [{status}] Novelty {n_id}: {info['description']}  ({info['elapsed']})")
        if info["status"] == "error":
            print(f"         Error: {info.get('error', 'unknown')}")
    print()

    # Evaluate verdicts
    from verdicts import evaluate_all, format_summary
    verdict_summary = evaluate_all(results_dir=RESULTS_DIR)
    print(format_summary(verdict_summary))

    # Write verdicts JSON
    verdict_path = RESULTS_DIR / "verdicts.json"
    with open(str(verdict_path), "w", encoding="utf-8") as f:
        json.dump(verdict_summary, f, indent=2, default=_json_default)

    print()
    print(f"Outputs: {FIG_DIR}/")
    print(f"         {RESULTS_DIR}/")
    print(f"         {verdict_path}")
    print("=" * 70)


if __name__ == "__main__":
    main()
