"""Create frozen dataset and stratified validation sample for manual audit.

Outputs:
  docs/validation/syndicate_corpus_v1.0.csv   -- frozen analysis table
  docs/validation/validation_sample.xlsx      -- Excel workbook for manual audit
  docs/validation/rejection_log.xlsx          -- screening log for rejected reports

Usage:
  python scripts/stress_test/create_validation_sample.py --freeze --sample --rejection-log
  python scripts/stress_test/create_validation_sample.py --all   # runs all three
"""

import argparse
import hashlib
import json
import logging
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
VALIDATION_DIR = PROJECT_ROOT / "docs" / "validation"

CORPUS_PATH = PROJECT_ROOT / "results" / "combined" / "enhanced_corpus.json"
LOB_WEIGHTS_PATH = PROJECT_ROOT / "data" / "lob_weights.json"
SIZE_METRICS_PATH = PROJECT_ROOT / "data" / "size_metrics.json"
QUALITY_REPORT_PATH = PROJECT_ROOT / "syndicate_reports" / "quality_report.json"

FROZEN_CSV = VALIDATION_DIR / "syndicate_corpus_v1.0.csv"
SAMPLE_XLSX = VALIDATION_DIR / "validation_sample.xlsx"
REJECTION_XLSX = VALIDATION_DIR / "rejection_log.xlsx"

# ---------------------------------------------------------------------------
# Rejection reason taxonomy
# ---------------------------------------------------------------------------
REJECTION_REASONS = {
    "insufficient_reserve_disclosure": "Report contains minimal or boilerplate reserve commentary without quantified movements",
    "missing_lob_breakdown": "Reserve movements disclosed at aggregate level only, no line-of-business split",
    "missing_causal_detail": "LoB breakdown present but causal explanations absent or generic",
    "scanned_unreadable": "Scanned PDF with OCR failure or unreadable formatting",
    "extraction_failure": "Text extraction failed entirely across all methods",
    "ambiguous_segment_taxonomy": "LoB segmentation too coarse or non-standard to map to canonical basis",
    "duplicate_superseded": "Superseded by a later filing for the same syndicate-year",
}


# ---------------------------------------------------------------------------
# Step 1: Freeze the dataset
# ---------------------------------------------------------------------------
def freeze_dataset() -> pd.DataFrame:
    """Build the analysis table and freeze it as a CSV with metadata header."""
    logger.info("Loading corpus, LoB weights, and size metrics...")

    # Load enhanced corpus
    with open(CORPUS_PATH, "r", encoding="utf-8") as f:
        corpus_data = json.load(f)
    movements = corpus_data["movements"]

    # Load LoB weights
    with open(LOB_WEIGHTS_PATH, "r", encoding="utf-8") as f:
        lob_weights_data = json.load(f)
    extractions = lob_weights_data.get("extractions", {})

    # Load size metrics
    with open(SIZE_METRICS_PATH, "r", encoding="utf-8") as f:
        size_data = json.load(f)
    size_metrics = {
        (m["syndicate"], m["year"]): m for m in size_data.get("metrics", [])
    }

    # Build rows: one per syndicate-year
    rows = []
    synd_year_movements: Dict[Tuple[int, int], list] = {}
    for m in movements:
        s = m.get("syndicate")
        y = m.get("year")
        if s is None or y is None:
            continue
        synd_year_movements.setdefault((s, y), []).append(m)

    for (synd, year), mvmts in sorted(synd_year_movements.items()):
        # Aggregate movement
        total_amount = 0.0
        lobs_seen = []
        directions = []
        causes = []
        confidence_vals = []
        narratives = []
        source_file = ""

        for m in mvmts:
            amt = m.get("amount_gbp_m")
            direction = m.get("direction", "")
            if amt is not None:
                signed = -abs(amt) if direction == "release" else abs(amt)
                total_amount += signed
            lob = m.get("line_of_business", "")
            if lob:
                lobs_seen.append(lob)
            directions.append(direction)
            causes.extend(m.get("primary_causes", []))
            confidence_vals.append(m.get("confidence", ""))
            narratives.append(m.get("standardized_narrative", ""))
            if not source_file:
                source_file = m.get("source_file", "")

        # Reserve base (priority cascade)
        R_s = None
        R_s_source = "none"
        # Priority 1: from corpus
        for m in mvmts:
            pr = m.get("prior_reserves_gbp_m")
            if pr is not None and pr > 0:
                R_s = pr
                R_s_source = "prior_reserves_gbp_m"
                break
        # Priority 2-4: from size metrics
        if R_s is None:
            sm = size_metrics.get((synd, year), {})
            for field in [
                "technical_provisions_gbp_m",
                "claims_outstanding_gbp_m",
                "stamp_capacity_gbp_m",
            ]:
                val = sm.get(field)
                if val is not None and val > 0:
                    R_s = val
                    R_s_source = field
                    break

        # Severity ratio
        S_raw_a = total_amount / R_s if R_s and R_s > 0 else None

        # LoB weights
        key = f"{synd}_{year}"
        ext = extractions.get(key, {})
        best_weights = ext.get("best_weights", {})
        weight_source = ext.get("weight_source", "none")
        extraction_confidence = ext.get("extraction_confidence", "none")

        # LoB weight string for validation
        lob_weights_str = ""
        if best_weights:
            # Top 3 LoBs
            sorted_w = sorted(best_weights.items(), key=lambda x: -x[1])
            lob_weights_str = "; ".join(
                f"{k}: {v:.1%}" for k, v in sorted_w[:5]
            )

        rows.append(
            {
                "row_id": len(rows),
                "syndicate_id": synd,
                "year": year,
                "R_s": R_s,
                "R_s_source": R_s_source,
                "S_raw_a": S_raw_a,
                "total_movement_gbp_m": total_amount,
                "n_movements": len(mvmts),
                "n_lobs": len(set(lobs_seen)),
                "lobs": "; ".join(sorted(set(lobs_seen))),
                "direction_summary": "; ".join(sorted(set(directions))),
                "weight_source": weight_source,
                "extraction_confidence": extraction_confidence,
                "lob_weights_top5": lob_weights_str,
                "causes": "; ".join(sorted(set(causes)))[:200],
                "confidence": "; ".join(sorted(set(confidence_vals))),
                "source_file": source_file,
                "narrative_excerpt": (narratives[0][:200] if narratives else ""),
            }
        )

    df = pd.DataFrame(rows)

    # Write frozen CSV
    VALIDATION_DIR.mkdir(parents=True, exist_ok=True)

    # Compute hash of content
    csv_content = df.to_csv(index=False)
    file_hash = hashlib.sha256(csv_content.encode("utf-8")).hexdigest()

    n_syndicates = df["syndicate_id"].nunique()
    year_min, year_max = df["year"].min(), df["year"].max()

    header = (
        f"# Frozen dataset: syndicate_corpus_v1.0\n"
        f"# Generated: {datetime.now().isoformat()}\n"
        f"# Rows: {len(df)}\n"
        f"# Unique syndicates: {n_syndicates}\n"
        f"# Year range: {year_min}-{year_max}\n"
        f"# SHA-256: {file_hash}\n"
        f"#\n"
    )

    with open(FROZEN_CSV, "w", encoding="utf-8", newline="") as f:
        f.write(header)
        f.write(csv_content)

    logger.info(
        f"Frozen dataset written: {FROZEN_CSV} "
        f"({len(df)} rows, {n_syndicates} syndicates, {year_min}-{year_max})"
    )
    logger.info(f"SHA-256: {file_hash}")

    return df


# ---------------------------------------------------------------------------
# Step 2: Stratified validation sample
# ---------------------------------------------------------------------------
def draw_stratified_sample(
    df: pd.DataFrame,
    n_accepted: int = 40,
    n_rejected: int = 10,
    seed: int = 42,
) -> pd.DataFrame:
    """Draw a stratified sample for manual audit.

    Stratification on accepted rows:
      - Year band: early (2014-2016), middle (2017-2019), late (2020-2024)
      - Reserve size: small (<200m), medium (200-800m), large (>800m)
      - Overweight: top decile |S_raw_a|, top decile LoB entropy
    """
    rng = np.random.RandomState(seed)

    # Load quality report for tier info and rejected reports
    with open(QUALITY_REPORT_PATH, "r", encoding="utf-8") as f:
        qr = json.load(f)
    quality_lookup = {
        (a["syndicate"], a["year"]): a for a in qr["assessments"]
    }

    # Add quality tier to df
    df = df.copy()
    df["quality_tier"] = df.apply(
        lambda r: quality_lookup.get(
            (r["syndicate_id"], r["year"]), {}
        ).get("quality", "UNKNOWN"),
        axis=1,
    )

    # --- Accepted rows (VERY_HIGH / HIGH) ---
    accepted = df[df["quality_tier"].isin(["VERY_HIGH", "HIGH"])].copy()

    # Year band
    accepted["year_band"] = pd.cut(
        accepted["year"],
        bins=[2013, 2016, 2019, 2025],
        labels=["early", "middle", "late"],
    )

    # Reserve size band
    accepted["size_band"] = pd.cut(
        accepted["R_s"].fillna(0),
        bins=[-1, 200, 800, 1e9],
        labels=["small", "medium", "large"],
    )

    # LoB entropy (for unusual mix detection)
    def _lob_entropy(row):
        weights_str = row.get("lob_weights_top5", "")
        if not weights_str:
            return 0.0
        parts = weights_str.split("; ")
        vals = []
        for p in parts:
            try:
                v = float(p.split(": ")[1].rstrip("%")) / 100
                if v > 0:
                    vals.append(v)
            except (IndexError, ValueError):
                pass
        if not vals:
            return 0.0
        arr = np.array(vals)
        arr = arr / arr.sum()
        return -np.sum(arr * np.log(arr + 1e-12))

    accepted["lob_entropy"] = accepted.apply(_lob_entropy, axis=1)

    # Flag extreme severity and unusual mix
    sev_abs = accepted["S_raw_a"].abs()
    sev_threshold = sev_abs.quantile(0.90) if len(sev_abs.dropna()) > 10 else 999
    entropy_threshold = (
        accepted["lob_entropy"].quantile(0.90)
        if len(accepted["lob_entropy"].dropna()) > 10
        else 999
    )
    accepted["is_extreme"] = (sev_abs >= sev_threshold) | (
        accepted["lob_entropy"] >= entropy_threshold
    )

    # Stratified sampling
    sampled_ids = set()

    # Ensure at least 2 from each stratum
    for yb in ["early", "middle", "late"]:
        for sb in ["small", "medium", "large"]:
            stratum = accepted[
                (accepted["year_band"] == yb) & (accepted["size_band"] == sb)
            ]
            if len(stratum) == 0:
                continue
            n_take = min(2, len(stratum))
            picks = stratum.sample(n=n_take, random_state=rng)
            sampled_ids.update(picks.index.tolist())

    # Add extreme cases
    extreme = accepted[
        accepted["is_extreme"] & ~accepted.index.isin(sampled_ids)
    ]
    n_extreme = min(8, len(extreme))
    if n_extreme > 0:
        picks = extreme.sample(n=n_extreme, random_state=rng)
        sampled_ids.update(picks.index.tolist())

    # Fill remaining from accepted
    remaining = accepted[~accepted.index.isin(sampled_ids)]
    n_fill = max(0, n_accepted - len(sampled_ids))
    if n_fill > 0 and len(remaining) > 0:
        picks = remaining.sample(n=min(n_fill, len(remaining)), random_state=rng)
        sampled_ids.update(picks.index.tolist())

    accepted_sample = accepted.loc[list(sampled_ids)].copy()

    # --- Rejected rows (MEDIUM / LOW / ERROR) ---
    # These are NOT in the frozen corpus df, so pull directly from quality report
    rejected_rows = []
    for a in qr["assessments"]:
        if a.get("quality") not in ("MEDIUM", "LOW", "ERROR"):
            continue
        synd = a["syndicate"]
        year = a["year"]
        rejected_rows.append(
            {
                "row_id": f"REJ_{synd}_{year}",
                "syndicate_id": synd,
                "year": year,
                "R_s": None,
                "R_s_source": "n/a (rejected)",
                "S_raw_a": None,
                "total_movement_gbp_m": None,
                "n_movements": 0,
                "n_lobs": 0,
                "lobs": "",
                "direction_summary": "",
                "weight_source": "none",
                "extraction_confidence": "none",
                "lob_weights_top5": "",
                "causes": "",
                "confidence": "",
                "source_file": f"syndicate_{synd}_{year}.pdf",
                "narrative_excerpt": "",
                "quality_tier": a["quality"],
            }
        )
    rejected = pd.DataFrame(rejected_rows)

    n_rej_take = min(n_rejected, len(rejected))
    if n_rej_take > 0:
        rej_low = rejected[rejected["quality_tier"].isin(["LOW", "ERROR"])]
        rej_med = rejected[rejected["quality_tier"] == "MEDIUM"]
        rej_picks = []
        n_low = min(4, len(rej_low))
        if n_low > 0:
            rej_picks.append(rej_low.sample(n=n_low, random_state=rng))
        n_med = min(n_rej_take - n_low, len(rej_med))
        if n_med > 0:
            rej_picks.append(rej_med.sample(n=n_med, random_state=rng))
        rejected_sample = pd.concat(rej_picks) if rej_picks else pd.DataFrame()
    else:
        rejected_sample = pd.DataFrame()

    # Combine
    sample = pd.concat([accepted_sample, rejected_sample], ignore_index=False)
    sample = sample.sort_values(["year", "syndicate_id"]).reset_index(drop=True)

    logger.info(
        f"Validation sample: {len(accepted_sample)} accepted + "
        f"{len(rejected_sample)} rejected = {len(sample)} total"
    )

    return sample


def write_validation_excel(sample: pd.DataFrame) -> None:
    """Write the validation sample as an Excel workbook with audit columns."""
    VALIDATION_DIR.mkdir(parents=True, exist_ok=True)

    # Build output dataframe with audit columns
    out = pd.DataFrame()
    out["row_id"] = sample["row_id"]
    out["syndicate"] = sample["syndicate_id"]
    out["year"] = sample["year"]
    out["quality_tier"] = sample["quality_tier"]
    out["source_document"] = sample["source_file"].apply(
        lambda x: Path(x).name if x else ""
    )
    out["source_page"] = ""  # to be filled manually

    # Extracted values
    out["extracted_reserve_gbp_m"] = sample["R_s"].round(1)
    out["extracted_reserve_source"] = sample["R_s_source"]
    out["validated_reserve_gbp_m"] = ""  # manual
    out["extracted_deterioration_pct"] = (sample["S_raw_a"] * 100).round(2)
    out["validated_deterioration_pct"] = ""  # manual
    out["extracted_movement_gbp_m"] = sample["total_movement_gbp_m"].round(1)
    out["validated_movement_gbp_m"] = ""  # manual
    out["extracted_lob_weights"] = sample["lob_weights_top5"]
    out["validated_lob_weights"] = ""  # manual
    out["extracted_direction"] = sample["direction_summary"]
    out["extracted_causes"] = sample["causes"]
    out["narrative_excerpt"] = sample["narrative_excerpt"]

    # Audit columns
    out["error_type"] = ""  # FO / RB / LM / TE / AD or blank
    out["material_error_yn"] = ""  # Y / N
    out["notes"] = ""

    # Write Excel
    with pd.ExcelWriter(SAMPLE_XLSX, engine="openpyxl") as writer:
        out.to_excel(writer, sheet_name="Validation Sample", index=False)

        # Error taxonomy reference sheet
        taxonomy = pd.DataFrame(
            [
                ("FO", "Field omission", "A disclosed field was not captured by extraction"),
                ("RB", "Reserve-base mismatch", "Wrong reserve figure used as R_s denominator"),
                ("LM", "LoB mapping error", "Syndicate LoB mapped to wrong canonical LoB"),
                ("TE", "Transcription/numeric", "Amount incorrectly transcribed from source"),
                ("AD", "Ambiguous disclosure", "Source language genuinely unclear on direction or amount"),
            ],
            columns=["Code", "Error Type", "Definition"],
        )
        taxonomy.to_excel(writer, sheet_name="Error Taxonomy", index=False)

        # Summary sheet with dataset metadata
        with open(FROZEN_CSV, "r", encoding="utf-8") as f:
            lines = f.readlines()
        meta_lines = [l.lstrip("# ").strip() for l in lines if l.startswith("#")]
        meta_df = pd.DataFrame({"Dataset Metadata": meta_lines})
        meta_df.to_excel(writer, sheet_name="Dataset Info", index=False)

    logger.info(f"Validation workbook written: {SAMPLE_XLSX}")


# ---------------------------------------------------------------------------
# Step 3: Rejection log
# ---------------------------------------------------------------------------
def create_rejection_log() -> None:
    """Create a retrospective screening table for all rejected reports."""
    with open(QUALITY_REPORT_PATH, "r", encoding="utf-8") as f:
        qr = json.load(f)

    rows = []
    for a in qr["assessments"]:
        quality = a.get("quality", "UNKNOWN")
        if quality not in ("MEDIUM", "LOW", "ERROR"):
            continue

        synd = a["syndicate"]
        year = a["year"]
        has_class = a.get("class_breakdown_found", False)
        has_causal = a.get("causal_language_found", False)
        has_quant = a.get("quantified_movements", False)
        method = a.get("extraction_method", "")
        pages = a.get("total_pages", 0)
        classes = a.get("classes_mentioned", [])
        confidence = a.get("confidence", 0)

        # Determine primary rejection reason
        n_classes = len(classes)
        n_amounts = len(a.get("monetary_amounts", []))

        if quality == "ERROR":
            primary = "extraction_failure"
            secondary = ""
            note = "Text extraction failed across all methods"
        elif method == "ocr" and pages == 0:
            primary = "scanned_unreadable"
            secondary = ""
            note = "Scanned PDF, OCR yielded no usable text"
        elif not has_quant and not has_class:
            primary = "insufficient_reserve_disclosure"
            secondary = ""
            note = "No quantified reserve movements or LoB breakdown found"
        elif has_class and n_classes >= 2 and n_amounts >= 2:
            # Had structured data but not enough causal detail for HIGH
            primary = "missing_causal_detail"
            secondary = ""
            note = f"LoB breakdown with {n_classes} classes, {n_amounts} amounts, but insufficient causal detail"
        elif has_class and not has_quant:
            primary = "insufficient_reserve_disclosure"
            secondary = "ambiguous_segment_taxonomy"
            note = f"LoB classes mentioned ({', '.join(classes[:3])}) but no quantified movements"
        elif has_quant and not has_class:
            primary = "missing_lob_breakdown"
            secondary = ""
            note = "Aggregate reserve commentary present but no LoB split"
        elif has_class and has_quant and n_amounts < 2:
            primary = "missing_lob_breakdown"
            secondary = "insufficient_reserve_disclosure"
            note = f"Some LoB references but only {n_amounts} quantified amount(s)"
        else:
            primary = "insufficient_reserve_disclosure"
            secondary = ""
            note = f"Quality={quality}, conf={confidence:.2f}, classes={n_classes}, amounts={n_amounts}"

        # Source document
        source_file = f"syndicate_{synd}_{year}.pdf"

        rows.append(
            {
                "syndicate": synd,
                "year": year,
                "report_identifier": f"syndicate_{synd}_{year}",
                "quality_tier": quality,
                "rejection_status": "rejected",
                "primary_rejection_reason": primary,
                "secondary_rejection_reason": secondary,
                "extraction_method": method,
                "total_pages": pages,
                "class_breakdown_found": has_class,
                "quantified_movements": has_quant,
                "causal_language_found": has_causal,
                "classes_mentioned": "; ".join(classes[:5]),
                "classifier_confidence": round(confidence, 2),
                "note": note,
            }
        )

    df = pd.DataFrame(rows)
    df = df.sort_values(["year", "syndicate"]).reset_index(drop=True)

    VALIDATION_DIR.mkdir(parents=True, exist_ok=True)

    with pd.ExcelWriter(REJECTION_XLSX, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Rejection Log", index=False)

        # Summary sheet
        summary_rows = []
        reason_counts = df["primary_rejection_reason"].value_counts()
        for reason, count in reason_counts.items():
            desc = REJECTION_REASONS.get(reason, "")
            summary_rows.append(
                {
                    "Rejection Reason": reason,
                    "Count": count,
                    "Share": f"{count / len(df):.1%}",
                    "Description": desc,
                }
            )
        summary_rows.append(
            {
                "Rejection Reason": "TOTAL",
                "Count": len(df),
                "Share": "100%",
                "Description": "",
            }
        )
        summary_df = pd.DataFrame(summary_rows)
        summary_df.to_excel(writer, sheet_name="Summary", index=False)

        # Year breakdown
        year_summary = (
            df.groupby("year")
            .agg(
                rejected=("rejection_status", "count"),
                low=("quality_tier", lambda x: (x == "LOW").sum()),
                medium=("quality_tier", lambda x: (x == "MEDIUM").sum()),
                error=("quality_tier", lambda x: (x == "ERROR").sum()),
            )
            .reset_index()
        )
        year_summary.to_excel(writer, sheet_name="By Year", index=False)

    logger.info(
        f"Rejection log written: {REJECTION_XLSX} ({len(df)} rejected reports)"
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Create frozen dataset and validation sample for manual audit"
    )
    parser.add_argument(
        "--freeze",
        action="store_true",
        help="Freeze the current analysis table as CSV",
    )
    parser.add_argument(
        "--sample",
        action="store_true",
        help="Draw stratified validation sample and output Excel",
    )
    parser.add_argument(
        "--rejection-log",
        action="store_true",
        help="Create rejection screening log",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Run all three steps",
    )
    parser.add_argument(
        "--n-accepted",
        type=int,
        default=40,
        help="Number of accepted rows in validation sample (default: 40)",
    )
    parser.add_argument(
        "--n-rejected",
        type=int,
        default=10,
        help="Number of rejected rows in validation sample (default: 10)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducibility",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    if args.all:
        args.freeze = True
        args.sample = True
        args.rejection_log = True

    if not (args.freeze or args.sample or args.rejection_log):
        parser.print_help()
        sys.exit(1)

    df = None
    if args.freeze or args.sample:
        df = freeze_dataset()

    if args.sample:
        sample = draw_stratified_sample(
            df, n_accepted=args.n_accepted, n_rejected=args.n_rejected, seed=args.seed
        )
        write_validation_excel(sample)

    if args.rejection_log:
        create_rejection_log()

    logger.info("Done.")


if __name__ == "__main__":
    main()
