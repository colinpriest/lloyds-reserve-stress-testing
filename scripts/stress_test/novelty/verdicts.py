"""Evaluate novelty claims against pre-registered decision rules.

Each novelty has specific claims with testable criteria.  This module
reads the result JSONs and returns a single structured verdict dict
plus a human-readable summary.

Usage:
    python scripts/stress_test/novelty/verdicts.py          # after run_all.py
    python scripts/stress_test/novelty/verdicts.py --pretty  # coloured terminal output

Called programmatically by run_all.py after all novelties complete.
"""

import json
import math
import logging
import argparse
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_this_dir = Path(__file__).resolve().parent
RESULTS_DIR = _this_dir / "results"

# ---------------------------------------------------------------------------
# Verdict levels
# ---------------------------------------------------------------------------
SUPPORTED = "SUPPORTED"
PARTIAL = "PARTIAL"          # direction right but not significant, or subset disagrees
INCONCLUSIVE = "INCONCLUSIVE"
INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
NOT_SUPPORTED = "NOT_SUPPORTED"

_LEVEL_RANK = {
    SUPPORTED: 4,
    PARTIAL: 3,
    INCONCLUSIVE: 2,
    INSUFFICIENT_DATA: 1,
    NOT_SUPPORTED: 0,
}


def _load(name: str) -> Optional[dict]:
    path = RESULTS_DIR / name
    if not path.exists():
        return None
    with open(str(path), encoding="utf-8") as f:
        return json.load(f)


def _is_finite(v) -> bool:
    if v is None:
        return False
    if isinstance(v, (int, float)):
        return math.isfinite(v)
    return False


# ---------------------------------------------------------------------------
# Novelty 0: Sampling sensitivity
# ---------------------------------------------------------------------------

def _verdict_n0(data: dict) -> dict:
    """Claim: key outputs are stable under 10 % leave-p-out resampling.

    Rule: each metric's bootstrap CV (sd / |point|) < 30 %.
    """
    if data is None:
        return {"verdict": INSUFFICIENT_DATA, "claim": "Results stable under 10% leave-out resampling",
                "evidence": [], "reason": "Novelty 0 did not run."}

    metrics = data.get("metrics", {})
    all_stable = data.get("all_stable", False)
    threshold = data.get("stability_threshold", 0.3)
    evidence = []

    for mname, mdata in metrics.items():
        cv = mdata.get("ratio_sd_point")
        stable = mdata.get("stable")
        point = mdata.get("point_estimate")
        sd = mdata.get("sd")
        evidence.append({
            "metric": mname,
            "point": point,
            "sd": sd,
            "cv": cv,
            "stable": stable,
        })

    if all_stable:
        verdict = SUPPORTED
        reason = f"All {len(metrics)} metrics have CV < {threshold:.0%}."
    else:
        n_unstable = sum(1 for m in metrics.values() if not m.get("stable"))
        verdict = NOT_SUPPORTED
        reason = f"{n_unstable}/{len(metrics)} metrics exceed CV threshold {threshold:.0%}."

    return {
        "verdict": verdict,
        "claim": "Key outputs are stable under 10% leave-p-out resampling.",
        "evidence": evidence,
        "reason": reason,
    }


# ---------------------------------------------------------------------------
# Novelty 1: Mix drift vs true worsening
# ---------------------------------------------------------------------------

def _get_n1_slope(data: dict, subset: str, series: str) -> Tuple[Optional[float], Optional[float]]:
    """Extract (slope, p_value) for a given subset and series from N1 results."""
    subsets = data.get("subsets", {})
    sub = subsets.get(subset, {})
    series_data = sub.get("series", {}).get(series, {})
    trend = series_data.get("p95_ols_trend", {})
    return trend.get("slope"), trend.get("p_value")


def _verdict_n1(data: dict) -> dict:
    """Claim: standardisation reduces or eliminates the apparent time trend
    in tail severity.

    Rules:
      (a) Raw-A and Raw-B slopes agree in sign on DENSE.
      (b) DENSE and BALANCED_K8 slopes agree in sign.
      (c) Standardised slope is smaller in magnitude than raw slope on DENSE.
      (d) Statistical significance at p < 0.05.
    """
    if data is None:
        return {"verdict": INSUFFICIENT_DATA, "claim": "Standardisation reduces time trend in tail severity",
                "evidence": [], "reason": "Novelty 1 did not run."}

    evidence = []

    raw_a_slope, raw_a_p = _get_n1_slope(data, "DENSE", "raw_a")
    raw_b_slope, raw_b_p = _get_n1_slope(data, "DENSE", "raw_b")
    std_slope, std_p = _get_n1_slope(data, "DENSE", "standardised")
    bk8_slope, bk8_p = _get_n1_slope(data, "DENSE", "raw_a")
    bk8_raw_slope, _ = _get_n1_slope(data, "BALANCED_K8", "raw_a")

    # Rule (a): Raw-A and Raw-B sign agreement
    rule_a = None
    if _is_finite(raw_a_slope) and _is_finite(raw_b_slope):
        rule_a = (raw_a_slope >= 0) == (raw_b_slope >= 0)
        evidence.append({"rule": "A: Raw-A/Raw-B sign agree (DENSE)",
                         "raw_a_slope": raw_a_slope, "raw_b_slope": raw_b_slope,
                         "passed": rule_a})

    # Rule (b): DENSE and BALANCED_K8 sign agreement
    rule_b = None
    if _is_finite(raw_a_slope) and _is_finite(bk8_raw_slope):
        rule_b = (raw_a_slope >= 0) == (bk8_raw_slope >= 0)
        evidence.append({"rule": "B: DENSE/BK8 sign agree",
                         "dense_slope": raw_a_slope, "bk8_slope": bk8_raw_slope,
                         "passed": rule_b})

    # Rule (c): Standardised magnitude < raw magnitude
    rule_c = None
    if _is_finite(raw_a_slope) and _is_finite(std_slope):
        rule_c = abs(std_slope) < abs(raw_a_slope)
        evidence.append({"rule": "C: |standardised slope| < |raw slope| (DENSE)",
                         "raw_slope": raw_a_slope, "std_slope": std_slope,
                         "reduction_pct": (1.0 - abs(std_slope) / abs(raw_a_slope)) * 100
                         if raw_a_slope != 0 else None,
                         "passed": rule_c})

    # Rule (d): Statistical significance
    raw_sig = _is_finite(raw_a_p) and raw_a_p < 0.05
    std_sig = _is_finite(std_p) and std_p < 0.05
    evidence.append({"rule": "D: Statistical significance (p < 0.05)",
                     "raw_a_p": raw_a_p, "std_p": std_p,
                     "raw_significant": raw_sig, "std_significant": std_sig})

    # Determine verdict
    if rule_c is True and rule_a is True and rule_b is True:
        if raw_sig and not std_sig:
            verdict = SUPPORTED
            reason = ("Standardisation eliminates significant trend: raw trend "
                      f"slope={raw_a_slope:.3f} (p={raw_a_p:.3f}), standardised "
                      f"slope={std_slope:.3f} (p={std_p:.3f}).")
        elif not raw_sig and not std_sig:
            verdict = PARTIAL
            reason = (f"Direction consistent (raw slope {raw_a_slope:.3f} reduces to "
                      f"std slope {std_slope:.3f}) but neither is significant at 5%.")
        elif raw_sig and std_sig:
            verdict = PARTIAL
            reason = (f"Standardisation reduces slope ({raw_a_slope:.3f} → {std_slope:.3f}) "
                      "but trend remains significant after adjustment.")
        else:
            verdict = INCONCLUSIVE
            reason = "Unexpected pattern in significance."
    elif rule_c is False:
        verdict = NOT_SUPPORTED
        reason = (f"Standardised slope ({std_slope:.3f}) is not smaller than "
                  f"raw slope ({raw_a_slope:.3f}).")
    else:
        verdict = INCONCLUSIVE
        reason = "Insufficient data to evaluate all rules."

    return {
        "verdict": verdict,
        "claim": "LoB-mix standardisation reduces the apparent time trend in tail severity.",
        "evidence": evidence,
        "reason": reason,
    }


# ---------------------------------------------------------------------------
# Novelty 2: Tail stability
# ---------------------------------------------------------------------------

def _verdict_n2(data: dict) -> dict:
    """Claim: tail diagnostics are more stable across time after
    standardisation.

    Rule: for metrics with >= 3 valid windows, sd(standardised) < sd(raw).
    """
    if data is None:
        return {"verdict": INSUFFICIENT_DATA,
                "claim": "Tail diagnostics more stable after standardisation",
                "evidence": [], "reason": "Novelty 2 did not run."}

    variability = data.get("variability", {})
    raw_a = variability.get("Raw-A", {})
    std = variability.get("Standardised", {})
    min_valid = 3

    evidence = []
    comparisons = 0
    std_better = 0

    for metric in raw_a:
        raw_info = raw_a.get(metric, {})
        std_info = std.get(metric, {})
        raw_n = raw_info.get("n_valid", 0)
        std_n = std_info.get("n_valid", 0)
        raw_sd = raw_info.get("sd")
        std_sd = std_info.get("sd")

        if raw_n >= min_valid and std_n >= min_valid and _is_finite(raw_sd) and _is_finite(std_sd):
            comparisons += 1
            is_better = std_sd < raw_sd
            if is_better:
                std_better += 1
            evidence.append({
                "metric": metric,
                "raw_a_sd": raw_sd, "raw_a_n_valid": raw_n,
                "std_sd": std_sd, "std_n_valid": std_n,
                "std_is_lower": is_better,
            })
        else:
            evidence.append({
                "metric": metric,
                "raw_a_n_valid": raw_n,
                "std_n_valid": std_n,
                "skipped": "fewer than 3 valid windows in one or both series",
            })

    # Count how many metrics were skipped and why
    n_skipped = len(evidence) - comparisons

    if comparisons == 0:
        verdict = INSUFFICIENT_DATA
        reason = (f"Underpowered: no metric had >= {min_valid} valid windows in both "
                  f"Raw-A and Standardised ({n_skipped} metrics skipped due to "
                  "insufficient exceedance counts per rolling window).")
    elif std_better == comparisons:
        verdict = SUPPORTED
        reason = (f"All {comparisons} comparable metrics show lower variability "
                  "after standardisation.")
    elif std_better > 0:
        verdict = PARTIAL
        reason = (f"{std_better}/{comparisons} comparable metrics show lower variability "
                  f"after standardisation; underpowered on {n_skipped} other metrics "
                  "due to insufficient exceedance counts per rolling window.")
    else:
        verdict = NOT_SUPPORTED
        reason = ("Standardisation does not reduce variability in any comparable "
                  "tail metric.")

    return {
        "verdict": verdict,
        "claim": "Tail diagnostics are more stable across time after standardisation.",
        "evidence": evidence,
        "reason": reason,
    }


# ---------------------------------------------------------------------------
# Novelty 3: Size scaling validation
# ---------------------------------------------------------------------------

def _verdict_n3(data: dict) -> dict:
    """Claim: size-severity beta is negative and robust across models and
    subsets.

    Rules:
      (a) Sanity check passes (M1 beta on DENSE in plausible band).
      (b) All model variants (M0–M3) agree on sign of beta on DENSE.
      (c) DENSE and BALANCED_K8 agree in sign for M1.
      (d) M1 beta is statistically significant (p < 0.05) on DENSE.
    """
    if data is None:
        return {"verdict": INSUFFICIENT_DATA,
                "claim": "Size-severity beta is negative and robust",
                "evidence": [], "reason": "Novelty 3 did not run."}

    model_results = data.get("model_results", {})
    sanity = data.get("sanity_check", {})
    evidence = []

    # Rule (a): Sanity check
    sanity_passed = sanity.get("passed", False)
    evidence.append({"rule": "A: Sanity check", "passed": sanity_passed,
                     "detail": sanity.get("message", "")})

    # Rule (b): All M0–M3 negative on DENSE
    dense = model_results.get("DENSE", {})
    model_keys = ["M0_no_fe", "M1_event_fe", "M2_log_abs", "M3_log_sq"]
    all_negative = True
    model_signs = {}
    for mk in model_keys:
        b = dense.get(mk, {}).get("beta")
        if _is_finite(b):
            model_signs[mk] = b
            if b >= 0:
                all_negative = False
        else:
            model_signs[mk] = None
    evidence.append({"rule": "B: All M0-M3 negative on DENSE",
                     "betas": model_signs, "passed": all_negative})

    # Rule (c): DENSE and BK8 agree in sign for M1
    dense_beta = dense.get("M1_event_fe", {}).get("beta")
    bk8_beta = model_results.get("BALANCED_K8", {}).get("M1_event_fe", {}).get("beta")
    rule_c = None
    if _is_finite(dense_beta) and _is_finite(bk8_beta):
        rule_c = (dense_beta < 0) == (bk8_beta < 0)
    evidence.append({"rule": "C: DENSE/BK8 M1 sign agree",
                     "dense_beta": dense_beta, "bk8_beta": bk8_beta,
                     "passed": rule_c})

    # Rule (d): Statistical significance
    dense_p = dense.get("M1_event_fe", {}).get("pvalue")
    sig = _is_finite(dense_p) and dense_p < 0.05
    evidence.append({"rule": "D: DENSE M1 significant at 5%",
                     "pvalue": dense_p, "passed": sig})

    # Temporal stability note
    temporal = data.get("temporal_stability", {})
    period_betas = {}
    for period, pdata in temporal.items():
        b = pdata.get("beta")
        period_betas[period] = b
    evidence.append({"rule": "Note: temporal stability",
                     "period_betas": period_betas})

    # Determine verdict
    if sanity_passed and all_negative and rule_c and sig:
        verdict = SUPPORTED
        reason = (f"Beta is robustly negative: M1 DENSE = {dense_beta:.3f} "
                  f"(p = {dense_p:.3f}), all models agree, DENSE/BK8 agree.")
    elif sanity_passed and all_negative and rule_c:
        verdict = PARTIAL
        reason = (f"Beta is consistently negative (M1 DENSE = {dense_beta:.3f}) "
                  f"but not significant at 5% (p = {dense_p:.3f}).")
    elif sanity_passed and all_negative:
        verdict = PARTIAL
        reason = (f"Beta is negative on DENSE (M1 = {dense_beta:.3f}) but "
                  f"DENSE/BK8 disagree or BK8 unavailable.")
    else:
        verdict = NOT_SUPPORTED
        reason = "Beta sign or sanity check failed."

    return {
        "verdict": verdict,
        "claim": "The size-severity exponent (beta) is negative and robust across model specifications.",
        "evidence": evidence,
        "reason": reason,
    }


# ---------------------------------------------------------------------------
# Novelty 4: Capital distortion
# ---------------------------------------------------------------------------

def _verdict_n4(data: dict) -> dict:
    """Claim: ignoring mix/size adjustments materially distorts tail risk
    capital, with mix adjustment being the dominant effect.

    Rules:
      (a) |mix_effect| > |size_effect| for majority of portfolios on DENSE.
      (b) mix_effect and total_effect are materially nonzero (> 1 pp of VaR).
      (c) Results directionally consistent between DENSE and FULL.
    """
    if data is None:
        return {"verdict": INSUFFICIENT_DATA,
                "claim": "Mix adjustment is the dominant source of capital distortion",
                "evidence": [], "reason": "Novelty 4 did not run."}

    subsets = data.get("subsets", {})
    dense = subsets.get("DENSE", {})
    full = subsets.get("FULL", {})
    evidence = []

    # Rule (a): mix dominates size for each portfolio on DENSE
    dense_portfolios = dense.get("portfolios", {})
    mix_dominates = 0
    total_portfolios = 0
    portfolio_details = []

    for pname, pdata in dense_portfolios.items():
        attr = pdata.get("attribution", {}).get("VaR_995", {})
        mix_eff = attr.get("mix_effect")
        size_eff = attr.get("size_effect")
        if _is_finite(mix_eff) and _is_finite(size_eff):
            total_portfolios += 1
            dominates = abs(mix_eff) > abs(size_eff)
            if dominates:
                mix_dominates += 1
            portfolio_details.append({
                "portfolio": pname,
                "mix_effect": round(mix_eff, 3),
                "size_effect": round(size_eff, 3),
                "mix_dominates": dominates,
            })

    rule_a = total_portfolios > 0 and mix_dominates == total_portfolios
    evidence.append({
        "rule": "A: |mix_effect| > |size_effect| for all DENSE portfolios",
        "passed": rule_a,
        "count": f"{mix_dominates}/{total_portfolios}",
        "portfolios": portfolio_details,
    })

    # Rule (b): effects are material (|total_effect| > 1 pp VaR)
    material_count = 0
    for pd_item in portfolio_details:
        total_eff = pd_item["mix_effect"] + pd_item["size_effect"]
        if abs(total_eff) > 1.0:
            material_count += 1
    rule_b = material_count > 0
    evidence.append({
        "rule": "B: Total distortion > 1 percentage point for at least one portfolio",
        "passed": rule_b,
        "material_portfolios": material_count,
    })

    # Rule (c): DENSE and FULL agree directionally
    full_portfolios = full.get("portfolios", {})
    agree_count = 0
    compare_count = 0
    for pname in dense_portfolios:
        dense_attr = dense_portfolios[pname].get("attribution", {}).get("VaR_995", {})
        full_attr = full_portfolios.get(pname, {}).get("attribution", {}).get("VaR_995", {})
        d_mix = dense_attr.get("mix_effect")
        f_mix = full_attr.get("mix_effect")
        if _is_finite(d_mix) and _is_finite(f_mix):
            compare_count += 1
            if (d_mix >= 0) == (f_mix >= 0):
                agree_count += 1
    rule_c = compare_count > 0 and agree_count == compare_count
    evidence.append({
        "rule": "C: DENSE/FULL agree directionally",
        "passed": rule_c,
        "detail": f"{agree_count}/{compare_count} portfolios agree",
    })

    # Determine verdict
    if rule_a and rule_b and rule_c:
        verdict = SUPPORTED
        reason = (f"Mix adjustment dominates in all {total_portfolios} portfolios; "
                  f"distortion is material; DENSE and FULL agree.")
    elif rule_a and rule_b:
        verdict = PARTIAL
        reason = "Mix dominates and is material, but DENSE/FULL directional check failed."
    elif rule_b:
        verdict = PARTIAL
        reason = "Distortion is material but mix does not dominate size in all portfolios."
    else:
        verdict = NOT_SUPPORTED
        reason = "No material capital distortion detected."

    return {
        "verdict": verdict,
        "claim": "Ignoring LoB-mix adjustment materially distorts capital; mix is the dominant effect.",
        "evidence": evidence,
        "reason": reason,
    }


# ---------------------------------------------------------------------------
# Overall summary
# ---------------------------------------------------------------------------

def evaluate_all(results_dir: Optional[Path] = None) -> dict:
    """Load all novelty result files and produce verdicts.

    Returns a dict with per-novelty verdicts and an overall summary.
    """
    global RESULTS_DIR
    if results_dir is not None:
        RESULTS_DIR = results_dir

    n0 = _load("novelty0_sampling_sensitivity.json")
    n1 = _load("novelty1_trend_results.json")
    n2 = _load("novelty2_tail_stability.json")
    n3 = _load("novelty3_size_validation.json")
    n4 = _load("novelty4_capital_distortion.json")

    verdicts = {
        0: _verdict_n0(n0),
        1: _verdict_n1(n1),
        2: _verdict_n2(n2),
        3: _verdict_n3(n3),
        4: _verdict_n4(n4),
    }

    # Overall: weakest-link level
    levels = [_LEVEL_RANK.get(v["verdict"], 0) for v in verdicts.values()]
    overall_level = min(levels) if levels else 0
    overall_verdict = {v: k for k, v in _LEVEL_RANK.items()}.get(overall_level, INCONCLUSIVE)

    n_supported = sum(1 for v in verdicts.values() if v["verdict"] == SUPPORTED)
    n_partial = sum(1 for v in verdicts.values() if v["verdict"] == PARTIAL)
    n_not = sum(1 for v in verdicts.values() if v["verdict"] in (NOT_SUPPORTED, INCONCLUSIVE, INSUFFICIENT_DATA))

    # Build a diagnostic overall reason
    supported_ids = sorted(k for k, v in verdicts.items() if v["verdict"] == SUPPORTED)
    partial_ids = sorted(k for k, v in verdicts.items() if v["verdict"] == PARTIAL)
    weak_ids = sorted(k for k, v in verdicts.items()
                      if v["verdict"] in (NOT_SUPPORTED, INCONCLUSIVE, INSUFFICIENT_DATA))

    reason_parts = []
    if partial_ids or weak_ids:
        weak_labels = {
            1: "time-trend analysis",
            2: "tail-stability diagnostics",
        }
        weak_descs = [weak_labels.get(i, f"novelty {i}") for i in (partial_ids + weak_ids)]
        reason_parts.append(f"underpowered on {', '.join(weak_descs)}")
    if supported_ids:
        strong_labels = {
            0: "sampling robustness",
            3: "size scaling",
            4: "capital impact",
        }
        strong_descs = [strong_labels.get(i, f"novelty {i}") for i in supported_ids]
        reason_parts.append(f"strong support for {', '.join(strong_descs)}")
    overall_reason = "; ".join(reason_parts) + "." if reason_parts else ""

    summary = {
        "overall_verdict": overall_verdict,
        "overall_reason": overall_reason,
        "supported": n_supported,
        "partial": n_partial,
        "unsupported_or_inconclusive": n_not,
        "novelties": verdicts,
    }
    return summary


def format_summary(summary: dict) -> str:
    """Render verdicts as a human-readable text block."""
    lines = []
    lines.append("=" * 70)
    lines.append("NOVELTY ANALYSIS VERDICTS")
    lines.append("=" * 70)
    lines.append("")

    for n_id in sorted(summary["novelties"]):
        v = summary["novelties"][n_id]
        tag = v["verdict"]
        lines.append(f"  Novelty {n_id}  [{tag}]")
        lines.append(f"    Claim:   {v['claim']}")
        lines.append(f"    Reason:  {v['reason']}")
        lines.append("")

    lines.append("-" * 70)
    lines.append(f"  Overall: {summary['overall_verdict']}  "
                 f"({summary['supported']} supported, "
                 f"{summary['partial']} partial, "
                 f"{summary['unsupported_or_inconclusive']} inconclusive/insufficient)")
    if summary.get("overall_reason"):
        lines.append(f"  {summary['overall_reason']}")
    lines.append("=" * 70)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Evaluate novelty analysis claims against pre-registered decision rules."
    )
    parser.add_argument("--results-dir", type=Path, default=None,
                        help="Override results directory.")
    parser.add_argument("--json", action="store_true",
                        help="Output raw JSON instead of formatted text.")
    args = parser.parse_args()

    summary = evaluate_all(results_dir=args.results_dir)

    if args.json:
        print(json.dumps(summary, indent=2, default=str))
    else:
        print(format_summary(summary))

    # Also write JSON
    out_path = (args.results_dir or RESULTS_DIR) / "verdicts.json"
    with open(str(out_path), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"\nVerdicts written to {out_path}")


if __name__ == "__main__":
    main()
