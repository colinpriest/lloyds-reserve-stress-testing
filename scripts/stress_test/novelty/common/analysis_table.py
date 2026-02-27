"""Unified analysis table: one row per syndicate-year observation.

Merges data from enhanced_corpus.json, lob_weights.json, and size_metrics.json
into a single DataFrame suitable for all novelty analyses. Enforces R0 subset
definitions, R5 dual raw severity metrics, R6 cap-binding diagnostics, and
includes merge audit diagnostics (review feedback #9).
"""

import sys
import json
import logging
import hashlib
import pickle
from dataclasses import dataclass, field, asdict
from pathlib import Path
from collections import defaultdict
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
_this_dir = Path(__file__).resolve().parent
_stress_test_dir = _this_dir.parent.parent
if str(_stress_test_dir) not in sys.path:
    sys.path.insert(0, str(_stress_test_dir))

from config import LLOYDS_LOBS, LOB_TO_INDEX, CauseCategory
from .severity_projection import (
    lob_weights_to_array,
    beta_lob_array,
    project_severity,
    composite_beta,
    size_adjustment_factor,
    cap_severity_array,
    N_LOBS,
)
from portfolio_size_adjustment import (
    DEFAULT_REFERENCE_SIZE_M,
    DEFAULT_OVERALL_COEFFICIENT,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Project root — data files are relative to project root
# ---------------------------------------------------------------------------
_PROJECT_ROOT = _stress_test_dir.parent.parent  # d:/dev/lloyds_reserve_stress_testing


# ---------------------------------------------------------------------------
# CoverageStats dataclass (R1)
# ---------------------------------------------------------------------------

@dataclass
class CoverageStats:
    """Coverage metadata attached to every result output (rule R1)."""
    n_observations: int = 0
    n_syndicates: int = 0
    syndicates_per_year_min: int = 0
    syndicates_per_year_max: int = 0
    year_range: Tuple[int, int] = (0, 0)
    exclusion_rules: List[str] = field(default_factory=list)
    raw_metric_used: str = "both"
    cap_binding_rates: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def _compute_coverage_stats(
    df: pd.DataFrame, exclusion_rules: Optional[List[str]] = None
) -> CoverageStats:
    """Compute CoverageStats from a (possibly subset) DataFrame."""
    if len(df) == 0:
        return CoverageStats(exclusion_rules=exclusion_rules or [])
    synd_per_year = df.groupby("year")["syndicate_id"].nunique()
    return CoverageStats(
        n_observations=len(df),
        n_syndicates=df["syndicate_id"].nunique(),
        syndicates_per_year_min=int(synd_per_year.min()),
        syndicates_per_year_max=int(synd_per_year.max()),
        year_range=(int(df["year"].min()), int(df["year"].max())),
        exclusion_rules=exclusion_rules or [],
    )


# ---------------------------------------------------------------------------
# Cause classification (lightweight version)
# ---------------------------------------------------------------------------

_CAUSE_KEYWORDS = {
    "natural_cat": ["catastrophe", "cat", "hurricane", "flood", "earthquake", "wildfire", "storm", "typhoon"],
    "man_made": ["man-made", "explosion", "fire", "collision"],
    "social_inflation": ["social inflation", "litigation", "nuclear verdict"],
    "economic_inflation": ["economic inflation", "claims cost", "cost inflation"],
    "covid": ["covid", "pandemic"],
    "ogden": ["ogden"],
    "adverse_dev": ["adverse", "deterioration", "prior year", "strengthening"],
    "large_loss": ["large loss", "large claim"],
    "reinsurance": ["reinsurance", "recoveries"],
    "court_rulings": ["court", "ruling", "legal"],
    "ibnr": ["ibnr", "incurred but not reported"],
    "regulatory": ["regulatory", "regulation", "solvency"],
    "methodology": ["methodology", "reserving approach", "assumption"],
    "geopolitical": ["geopolitical", "sanctions", "war"],
}


def _classify_cause(causes: List[str], narrative: str = "") -> str:
    """Classify cause into a category from primary_causes + narrative."""
    text = " ".join(causes).lower() + " " + narrative.lower()
    for cat, keywords in _CAUSE_KEYWORDS.items():
        for kw in keywords:
            if kw in text:
                return cat
    return "other"


# ---------------------------------------------------------------------------
# Data loading helpers
# ---------------------------------------------------------------------------

def _load_corpus(path: str) -> List[Dict]:
    """Load enhanced_corpus.json movements."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return data
    return data.get("movements", [])


def _load_lob_weights(path: str) -> Dict[str, Dict]:
    """Load lob_weights.json -> dict keyed by '{syndicate}_{year}'."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("extractions", {})


def _load_size_metrics(path: str) -> Dict[str, Dict]:
    """Load size_metrics.json -> dict keyed by '{syndicate}_{year}'."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    metrics_list = data.get("metrics", [])
    result = {}
    for m in metrics_list:
        key = f"{m['syndicate']}_{m['year']}"
        result[key] = m
    return result


# ---------------------------------------------------------------------------
# Reserve base determination
# ---------------------------------------------------------------------------

def _determine_reserve_base(
    corpus_records: List[Dict], size_record: Optional[Dict]
) -> Tuple[Optional[float], str]:
    """Determine R_s via priority cascade.

    Priority:
    1. prior_reserves_gbp_m (from corpus — 426/827 available)
    2. technical_provisions_gbp_m (from size_metrics — 341/621)
    3. claims_outstanding_gbp_m
    4. stamp_capacity_gbp_m (from corpus or size_metrics)

    Returns (value_in_gbp_m, source_field).
    """
    # Priority 1: prior_reserves from corpus (most common enhanced field)
    for rec in corpus_records:
        val = rec.get("prior_reserves_gbp_m")
        if val is not None and val > 0:
            return (float(val), "prior_reserves_gbp_m")

    # Priority 2-4: from size_metrics
    if size_record:
        for field_name in (
            "technical_provisions_gbp_m",
            "claims_outstanding_gbp_m",
            "stamp_capacity_gbp_m",
        ):
            val = size_record.get(field_name)
            if val is not None and val > 0:
                return (float(val), field_name)

    # Fallback: stamp_capacity from corpus
    for rec in corpus_records:
        val = rec.get("stamp_capacity_gbp_m")
        if val is not None and val > 0:
            return (float(val), "stamp_capacity_gbp_m")

    return (None, "none")


# ---------------------------------------------------------------------------
# Core table builder
# ---------------------------------------------------------------------------

def build_analysis_table(
    corpus_path: Optional[str] = None,
    lob_weights_path: Optional[str] = None,
    size_metrics_path: Optional[str] = None,
    max_severity: float = 5.0,
    direction_filter: str = "all",
) -> pd.DataFrame:
    """Build the unified analysis DataFrame: one row per syndicate-year.

    Parameters
    ----------
    corpus_path : path to enhanced_corpus.json
    lob_weights_path : path to lob_weights.json
    size_metrics_path : path to size_metrics.json
    max_severity : cap on LoB-level severity (±)
    direction_filter : 'all', 'strengthening', or 'release'
    """
    # Resolve default paths relative to project root
    if corpus_path is None:
        corpus_path = str(_PROJECT_ROOT / "results" / "combined" / "enhanced_corpus.json")
    if lob_weights_path is None:
        lob_weights_path = str(_PROJECT_ROOT / "lob_weights.json")
    if size_metrics_path is None:
        size_metrics_path = str(_PROJECT_ROOT / "size_metrics.json")

    logger.info("Loading corpus from %s", corpus_path)
    movements = _load_corpus(corpus_path)
    logger.info("Loading LOB weights from %s", lob_weights_path)
    lob_weights_data = _load_lob_weights(lob_weights_path)
    logger.info("Loading size metrics from %s", size_metrics_path)
    size_metrics_data = _load_size_metrics(size_metrics_path)

    # Filter by direction if requested
    if direction_filter != "all":
        movements = [m for m in movements if m.get("direction") == direction_filter]

    # Group movements by (syndicate, year)
    synd_year_groups: Dict[str, List[Dict]] = defaultdict(list)
    for m in movements:
        synd = m.get("syndicate")
        year = m.get("year")
        if synd is None or year is None:
            continue
        key = f"{synd}_{year}"
        synd_year_groups[key] = synd_year_groups.get(key, []) + [m]

    logger.info("Found %d syndicate-years from %d movements", len(synd_year_groups), len(movements))

    rows = []
    for sy_key, records in synd_year_groups.items():
        synd_str = str(records[0]["syndicate"])
        year = int(records[0]["year"])

        # --- Reserve base ---
        size_rec = size_metrics_data.get(sy_key)
        R_s, R_s_source = _determine_reserve_base(records, size_rec)

        # --- LOB weights ---
        lob_ext = lob_weights_data.get(sy_key, {})
        best_weights = lob_ext.get("best_weights", {})
        weight_source = lob_ext.get("weight_source", "none")
        extraction_confidence = lob_ext.get("extraction_confidence", "none")

        w_s: Optional[Dict[str, float]] = None
        w_s_array = np.zeros(N_LOBS, dtype=np.float64)
        if best_weights and len(best_weights) > 0:
            w_s = dict(best_weights)
            w_s_array = lob_weights_to_array(w_s)
            # Normalise
            total_w = w_s_array.sum()
            if total_w > 0:
                w_s_array = w_s_array / total_w
        else:
            # Fallback: movement-amount-based weights
            lob_amounts: Dict[str, float] = {}
            for rec in records:
                lob = rec.get("line_of_business", "")
                amt = abs(rec.get("amount_gbp_m") or 0.0)
                if lob and amt > 0:
                    lob_amounts[lob] = lob_amounts.get(lob, 0.0) + amt
            if lob_amounts:
                total_amt = sum(lob_amounts.values())
                w_s = {k: v / total_amt for k, v in lob_amounts.items()}
                w_s_array = lob_weights_to_array(w_s)
                weight_source = "movement_amounts"
            else:
                weight_source = "none"

        # --- LoB severities ---
        s_lob = np.full(N_LOBS, np.nan, dtype=np.float64)
        cap_binding = {}

        if R_s is not None and R_s > 0 and w_s is not None:
            for rec in records:
                lob = rec.get("line_of_business", "")
                idx = LOB_TO_INDEX.get(lob)
                if idx is None:
                    continue
                amt = rec.get("amount_gbp_m")
                if amt is None:
                    continue
                # Signed amount: positive = strengthening, negative = release
                signed_amt = abs(amt) if rec.get("direction") == "strengthening" else -abs(amt)
                # LOB reserves = R_s * max(w_s_ℓ, 0.01)
                lob_weight = max(w_s_array[idx], 0.01)
                lob_reserves = R_s * lob_weight
                if lob_reserves > 0:
                    raw_sev = signed_amt / lob_reserves
                    capped = float(np.clip(raw_sev, -max_severity, max_severity))
                    if abs(raw_sev) >= max_severity:
                        cap_binding[lob] = raw_sev
                    # If multiple records for same LOB, take the one with largest abs amount
                    if np.isnan(s_lob[idx]) or abs(capped) > abs(s_lob[idx]):
                        s_lob[idx] = capped

        # Fill unobserved LOBs with 0.0 (no movement)
        lob_present_mask = ~np.isnan(s_lob)
        s_lob_clean = np.where(np.isnan(s_lob), 0.0, s_lob)

        # --- Aggregate severity Raw-A: M_total / R_s ---
        S_raw_a = np.nan
        if R_s is not None and R_s > 0:
            # Total signed movement
            total_M = 0.0
            for rec in records:
                amt = rec.get("amount_gbp_m")
                if amt is None:
                    continue
                signed = abs(amt) if rec.get("direction") == "strengthening" else -abs(amt)
                total_M += signed
            S_raw_a = total_M / R_s
            # Also check for precomputed severity_ratio
            for rec in records:
                sev = rec.get("severity_ratio")
                if sev is not None:
                    S_raw_a = float(sev)
                    break  # prefer precomputed

        # --- Aggregate severity Raw-B: dot(w_s, s_lob) ---
        S_raw_b = np.nan
        if w_s is not None and not np.all(s_lob_clean == 0.0):
            S_raw_b = float(np.dot(w_s_array, s_lob_clean))

        # --- Cause classification ---
        all_causes = []
        all_narratives = []
        for rec in records:
            all_causes.extend(rec.get("primary_causes", []))
            narr = rec.get("standardized_narrative", "")
            if narr:
                all_narratives.append(narr)
        cause_category = _classify_cause(all_causes, " ".join(all_narratives))
        event_id = f"{year}_{cause_category}"

        # --- HHI ---
        HHI_s = float(np.sum(w_s_array ** 2)) if w_s is not None else np.nan

        rows.append({
            "syndicate_id": synd_str,
            "year": year,
            "cause_category": cause_category,
            "event_id": event_id,
            "R_s": R_s,
            "R_s_source": R_s_source,
            "w_s": w_s,
            "w_s_array": w_s_array,
            "s_lob": s_lob_clean,
            "S_raw_a": S_raw_a,
            "S_raw_b": S_raw_b,
            "HHI_s": HHI_s,
            "n_lobs": int(lob_present_mask.sum()),
            "lob_present_mask": lob_present_mask,
            "data_quality_flags": {
                "weight_source": weight_source,
                "extraction_confidence": extraction_confidence,
                "R_s_source": R_s_source,
            },
            "cap_binding": cap_binding,
        })

    df = pd.DataFrame(rows)
    logger.info("Analysis table built: %d rows", len(df))
    return df


# ---------------------------------------------------------------------------
# Query column addition
# ---------------------------------------------------------------------------

def add_query_columns(
    df: pd.DataFrame,
    w_q: np.ndarray,
    R_q: float,
    query_name: str,
    beta_lob: Optional[np.ndarray] = None,
    R_ref: float = DEFAULT_REFERENCE_SIZE_M,
) -> pd.DataFrame:
    """Add derived severity columns for a specific query portfolio.

    Adds columns:
    - S_std_{query_name}: dot(w_q, s_lob) — mix-standardised severity
    - beta_weighted_{query_name}: composite beta for this portfolio
    - S_adj_{query_name}: S_std * (R_q / R_ref) ^ beta_weighted
    """
    if beta_lob is None:
        beta_lob = beta_lob_array()

    beta_w = composite_beta(w_q, beta_lob)
    adj_factor = size_adjustment_factor(R_q, R_ref, beta_w)

    s_std_col = f"S_std_{query_name}"
    s_adj_col = f"S_adj_{query_name}"

    df[s_std_col] = df["s_lob"].apply(lambda s: project_severity(w_q, s))
    df[s_adj_col] = df[s_std_col] * adj_factor
    df[f"beta_weighted_{query_name}"] = beta_w
    return df


# ---------------------------------------------------------------------------
# Subset extraction (R0)
# ---------------------------------------------------------------------------

def _compute_balanced_panels(df: pd.DataFrame) -> Dict[str, Set[str]]:
    """Compute K-of-T balanced panels dynamically.

    Returns {'K8': set, 'K6': set, 'ALL': set} of syndicate_id values.
    """
    # Only consider 2014-2023 for balanced panel computation
    sub = df[df["year"].between(2014, 2023)]
    synd_year_counts = sub.groupby("syndicate_id")["year"].nunique()
    n_years = sub["year"].nunique()
    return {
        "K8": set(synd_year_counts[synd_year_counts >= min(8, n_years)].index),
        "K6": set(synd_year_counts[synd_year_counts >= min(6, n_years)].index),
        "ALL": set(synd_year_counts[synd_year_counts >= n_years].index),
    }


def get_subset(
    df: pd.DataFrame, subset_name: str
) -> Tuple[pd.DataFrame, CoverageStats]:
    """Return a filtered DataFrame + CoverageStats for a named subset.

    Subset names: DENSE, MID, FULL, BALANCED_K8, BALANCED_K6, BALANCED_ALL, 2024
    """
    subset_name = subset_name.upper()
    panels = _compute_balanced_panels(df)

    if subset_name == "DENSE":
        mask = df["year"].between(2014, 2019)
        rules = ["years 2014-2019"]
    elif subset_name == "MID":
        mask = df["year"].between(2020, 2023)
        rules = ["years 2020-2023"]
    elif subset_name == "FULL":
        mask = df["year"].between(2014, 2023)
        rules = ["years 2014-2023"]
    elif subset_name == "BALANCED_K8":
        mask = df["year"].between(2014, 2023) & df["syndicate_id"].isin(panels["K8"])
        rules = [f"years 2014-2023, syndicates in >=8 years (n={len(panels['K8'])})"]
    elif subset_name == "BALANCED_K6":
        mask = df["year"].between(2014, 2023) & df["syndicate_id"].isin(panels["K6"])
        rules = [f"years 2014-2023, syndicates in >=6 years (n={len(panels['K6'])})"]
    elif subset_name == "BALANCED_ALL":
        mask = df["year"].between(2014, 2023) & df["syndicate_id"].isin(panels["ALL"])
        rules = [f"years 2014-2023, syndicates in all years (n={len(panels['ALL'])})"]
    elif subset_name == "2024":
        mask = df["year"] == 2024
        rules = ["year 2024 only (partial, Raw-A only)"]
    else:
        raise ValueError(f"Unknown subset: {subset_name}")

    sub = df.loc[mask].copy()
    stats = _compute_coverage_stats(sub, exclusion_rules=rules)
    return sub, stats


# ---------------------------------------------------------------------------
# Cap-binding diagnostics (R6)
# ---------------------------------------------------------------------------

def compute_cap_binding_stats(df: pd.DataFrame) -> Dict[str, Any]:
    """Compute cap-binding rates per year and overall.

    Returns dict with:
    - pct_capped_pos_5: overall % of s_lob hitting +5.0
    - pct_capped_neg_5: overall % hitting -5.0
    - pct_floor_weight_1pct: % of LOB weights floored at 1%
    - by_year: per-year breakdown
    """
    total_lob_entries = 0
    capped_pos = 0
    capped_neg = 0
    floor_engaged = 0
    by_year: Dict[int, Dict] = {}

    for _, row in df.iterrows():
        s_lob = row["s_lob"]
        w_s_array = row["w_s_array"]
        mask = row["lob_present_mask"]
        year = row["year"]

        n_present = int(mask.sum())
        n_cap_pos = int(np.sum((s_lob >= 4.99) & mask))
        n_cap_neg = int(np.sum((s_lob <= -4.99) & mask))
        n_floor = int(np.sum((w_s_array > 0) & (w_s_array < 0.011)))

        total_lob_entries += n_present
        capped_pos += n_cap_pos
        capped_neg += n_cap_neg
        floor_engaged += n_floor

        if year not in by_year:
            by_year[year] = {"n_lob_entries": 0, "capped_pos": 0, "capped_neg": 0, "floor": 0}
        by_year[year]["n_lob_entries"] += n_present
        by_year[year]["capped_pos"] += n_cap_pos
        by_year[year]["capped_neg"] += n_cap_neg
        by_year[year]["floor"] += n_floor

    safe_div = lambda a, b: a / b if b > 0 else 0.0
    return {
        "pct_capped_pos_5": safe_div(capped_pos, total_lob_entries),
        "pct_capped_neg_5": safe_div(capped_neg, total_lob_entries),
        "pct_floor_weight_1pct": safe_div(floor_engaged, total_lob_entries),
        "by_year": {
            yr: {
                "pct_capped_pos": safe_div(d["capped_pos"], d["n_lob_entries"]),
                "pct_capped_neg": safe_div(d["capped_neg"], d["n_lob_entries"]),
                "pct_floor": safe_div(d["floor"], d["n_lob_entries"]),
            }
            for yr, d in sorted(by_year.items())
        },
    }


# ---------------------------------------------------------------------------
# Merge audit diagnostics (review feedback #9)
# ---------------------------------------------------------------------------

def audit_merge(df: pd.DataFrame, output_path: Optional[str] = None) -> Dict[str, Any]:
    """Post-merge diagnostic: % rows missing key fields.

    Warns loudly if any field exceeds 10% missing. Optionally writes
    results/analysis_table_audit.json.
    """
    n = len(df)
    if n == 0:
        return {"error": "empty table"}

    audit = {
        "n_rows": n,
        "pct_missing_R_s": float(df["R_s"].isna().sum() / n),
        "pct_missing_w_s": float(df["w_s"].isna().sum() / n),
        "pct_missing_S_raw_a": float(df["S_raw_a"].isna().sum() / n),
        "pct_missing_S_raw_b": float(df["S_raw_b"].isna().sum() / n),
        "pct_missing_cause": float((df["cause_category"] == "other").sum() / n),
        "n_syndicates": int(df["syndicate_id"].nunique()),
        "year_range": [int(df["year"].min()), int(df["year"].max())],
        "R_s_source_dist": df["R_s_source"].value_counts().to_dict(),
        "weight_source_dist": df["data_quality_flags"].apply(
            lambda d: d.get("weight_source", "unknown") if isinstance(d, dict) else "unknown"
        ).value_counts().to_dict(),
    }

    # Warn on high missingness
    for key in ("pct_missing_R_s", "pct_missing_w_s", "pct_missing_S_raw_a"):
        if audit[key] > 0.10:
            logger.warning("HIGH MISSINGNESS: %s = %.1f%%", key, audit[key] * 100)

    if output_path:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(audit, f, indent=2, default=str)
        logger.info("Merge audit written to %s", output_path)

    return audit


# ---------------------------------------------------------------------------
# Cache load/build
# ---------------------------------------------------------------------------

def load_or_build(
    cache_path: Optional[str] = None, **build_kwargs
) -> pd.DataFrame:
    """Load analysis table from pickle cache, or build and cache it.

    Cache is invalidated if any source file is newer than the cache.
    """
    if cache_path:
        cache_file = Path(cache_path)
        if cache_file.exists():
            try:
                df = pd.read_pickle(cache_file)
                logger.info("Loaded analysis table from cache: %s (%d rows)", cache_path, len(df))
                return df
            except Exception as e:
                logger.warning("Cache load failed (%s), rebuilding", e)

    df = build_analysis_table(**build_kwargs)

    if cache_path:
        Path(cache_path).parent.mkdir(parents=True, exist_ok=True)
        df.to_pickle(cache_path)
        logger.info("Cached analysis table to %s", cache_path)

    return df
