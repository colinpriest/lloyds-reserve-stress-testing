"""
Step 1: Historical Data Preparation

Prepares historical reserve movements with:
- Severity ratios (PYD / Opening Reserves)
- Portfolio complexity scores: R × (1 - HHI)
- LOB vectors (13-dimensional)
- Cause category classification

SEVERITY MODES:
- 'strict': Only use movements with actual reserve data (academic default)
- 'estimated': Allow severity estimation when reserves unavailable (requires sensitivity analysis)
"""

import sys
from pathlib import Path
_script_dir = Path(__file__).resolve().parent
if str(_script_dir) not in sys.path:
    sys.path.insert(0, str(_script_dir))

import json
import logging
from dataclasses import dataclass, asdict
from enum import Enum
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Any
from collections import defaultdict
import re

from config import (
    LLOYDS_LOBS, LOB_TO_INDEX, CauseCategory, CAUSE_KEYWORDS,
    HistoricalMovement
)

logger = logging.getLogger(__name__)


class SeverityMode(Enum):
    """Mode for severity calculation."""
    STRICT = 'strict'        # Only actual reserve data - academic default
    ESTIMATED = 'estimated'  # Allow estimation with industry ratios


@dataclass
class PreparationDiagnostics:
    """Diagnostics from data preparation process."""
    total_corpus: int
    after_direction_filter: int
    after_severity_filter: int
    final_count: int

    # Detailed drop reasons
    dropped_no_severity: int
    dropped_no_amount: int
    dropped_no_reserves: int
    dropped_no_profile: int

    # Estimation stats (when using estimated mode)
    estimated_severity_count: int
    actual_severity_count: int

    # Warnings
    warnings: List[str]

    # Coverage stats
    unique_syndicates: int
    unique_years: int
    lob_coverage: Dict[str, int]

    def to_dict(self) -> Dict:
        return asdict(self)


def load_unified_corpus(corpus_path: str) -> List[Dict]:
    """Load unified corpus from JSON file."""
    with open(corpus_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return data.get('movements', [])


def compute_lob_vector(lob: str) -> List[float]:
    """
    Convert LOB string to 13-dimensional one-hot vector.
    """
    vector = [0.0] * len(LLOYDS_LOBS)
    if lob in LOB_TO_INDEX:
        vector[LOB_TO_INDEX[lob]] = 1.0
    else:
        # Map to Aggregate if unknown
        vector[LOB_TO_INDEX['Aggregate']] = 1.0
    return vector


def classify_cause_category(causes: List[str], narrative: str) -> CauseCategory:
    """
    Classify primary cause into a category based on keywords.
    """
    text = ' '.join(causes).lower() + ' ' + narrative.lower()
    
    # Check each category's keywords
    for category, keywords in CAUSE_KEYWORDS.items():
        for keyword in keywords:
            if keyword in text:
                return category
    
    # Default based on cause strings
    cause_str = ' '.join(causes).lower()
    if 'adverse' in cause_str or 'deterioration' in cause_str:
        return CauseCategory.ADVERSE_DEV
    elif 'large loss' in cause_str:
        return CauseCategory.LARGE_LOSS
    elif 'ibnr' in cause_str:
        return CauseCategory.IBNR
    
    return CauseCategory.OTHER


def estimate_severity_ratio(
    movement: Dict,
    mode: SeverityMode = SeverityMode.STRICT
) -> Tuple[Optional[float], str]:
    """
    Get severity ratio from available data.

    Args:
        movement: Movement dictionary
        mode: STRICT (only actual data) or ESTIMATED (allow industry ratio estimates)

    Returns:
        Tuple of (severity_ratio, source) where source is:
        - 'precomputed': From corpus severity_ratio field
        - 'calculated': From amount_gbp_m / prior_reserves_gbp_m
        - 'estimated': From industry ratio estimate (only in ESTIMATED mode)
        - None: Could not determine severity
    """
    # Priority 1: Pre-calculated severity_ratio from corpus (most accurate)
    if movement.get('severity_ratio') is not None:
        try:
            sev = float(movement['severity_ratio'])
            # For strengthening movements, we want positive severity
            if movement.get('direction') == 'strengthening':
                sev = abs(sev)
            if sev > 0:
                return sev, 'precomputed'
        except (ValueError, TypeError):
            pass

    # Priority 2: Calculate from actual amount and reserves
    if movement.get('amount_gbp_m') and movement.get('prior_reserves_gbp_m'):
        try:
            amt = float(movement['amount_gbp_m'])
            reserves = float(movement['prior_reserves_gbp_m'])
            if reserves > 0:
                sev = abs(amt) / reserves
                if sev > 0:
                    return sev, 'calculated'
        except (ValueError, TypeError):
            pass

    # Priority 3: ESTIMATED mode - estimate using industry ratios
    # Only if ESTIMATED mode AND we have amount data
    if mode == SeverityMode.ESTIMATED and movement.get('amount_gbp_m'):
        try:
            amt = abs(float(movement['amount_gbp_m']))
            if amt > 0:
                # Industry heuristic: PYD movements typically 5-15% of reserves
                # Use 10x multiplier (assumes movement ≈ 10% of reserves)
                # This is documented and must be disclosed in academic work
                estimated_reserves = amt * 10.0
                sev = amt / estimated_reserves  # = 0.10 (10%)

                # But we can do better - use amount percentile to vary the ratio
                # Small movements more likely to be larger % of reserves
                # Large movements more likely to be smaller % of reserves
                # Use log-linear scaling between 5% and 20%
                import math
                # Scale factor: 5m movement -> ~15%, 50m movement -> ~8%, 200m -> ~5%
                scale = max(0.05, min(0.20, 0.20 - 0.03 * math.log10(max(1, amt))))
                sev = scale

                return sev, 'estimated'
        except (ValueError, TypeError):
            pass

    # No severity could be determined
    return None, None


def estimate_severity_ratio_strict(movement: Dict) -> Optional[float]:
    """
    Legacy wrapper for strict mode severity estimation.

    STRICT MODE: Only returns severity when we have actual reserve data.
    No fallback estimates that could corrupt academic results.
    """
    sev, source = estimate_severity_ratio(movement, SeverityMode.STRICT)
    return sev


def compute_syndicate_portfolio_profile(
    movements: List[Dict],
    syndicate: str,
    year: int
) -> Tuple[Optional[float], float, Dict[str, float], bool]:
    """
    Compute portfolio profile for a syndicate in a given year.

    Returns:
        - Total reserves (GBP m) - actual if available, None otherwise
        - HHI (Herfindahl-Hirschman Index)
        - LOB weights
        - has_actual_reserves: True if reserves are from actual data
    """
    # Get all movements for this syndicate-year
    syn_movements = [
        m for m in movements
        if m.get('syndicate') == syndicate and m.get('year') == year
    ]

    if not syn_movements:
        return None, 1.0, {}, False

    # First, try to get ACTUAL reserves from corpus (from size_metrics merge)
    actual_reserves = None
    for m in syn_movements:
        reserves = m.get('prior_reserves_gbp_m')
        if reserves is not None and reserves > 0:
            actual_reserves = float(reserves)
            break

    # Count LOB occurrences and amounts (for weights and fallback)
    lob_amounts = defaultdict(float)
    total_amount = 0.0

    for m in syn_movements:
        lob = m.get('line_of_business', 'Aggregate')
        gbp = m.get('amount_gbp_m')
        usd = m.get('amount_usd_m')
        if gbp is not None:
            amt = abs(gbp)
        elif usd is not None:
            amt = abs(usd / 1.25)
        else:
            # Skip movements without amount data
            continue
        lob_amounts[lob] += amt
        total_amount += amt

    # Compute weights from actual movement data
    if total_amount > 0:
        lob_weights = {lob: amt / total_amount for lob, amt in lob_amounts.items()}
    elif syn_movements:
        # Equal weights when no amounts available
        unique_lobs = set(m.get('line_of_business', 'Aggregate') for m in syn_movements)
        lob_weights = {lob: 1.0 / len(unique_lobs) for lob in unique_lobs}
    else:
        lob_weights = {}

    # Compute HHI
    hhi = sum(w ** 2 for w in lob_weights.values()) if lob_weights else 1.0

    return actual_reserves, hhi, lob_weights, actual_reserves is not None


def prepare_historical_data(
    corpus_path: str,
    output_path: Optional[str] = None,
    direction_filter: str = 'strengthening',
    severity_mode: str = 'strict',
    return_diagnostics: bool = False
) -> Tuple[List[HistoricalMovement], Optional[PreparationDiagnostics]]:
    """
    Main function to prepare historical data.

    Args:
        corpus_path: Path to unified_corpus.json
        output_path: Optional path to save prepared data
        direction_filter: 'strengthening', 'release', or 'all'
        severity_mode: 'strict' (only actual data) or 'estimated' (allow industry estimates)
        return_diagnostics: If True, return diagnostics object

    Returns:
        If return_diagnostics=False: List of prepared HistoricalMovement objects
        If return_diagnostics=True: Tuple of (movements, PreparationDiagnostics)

    IMPORTANT for academic work:
        - Use 'strict' mode (default) for publishable results
        - If using 'estimated' mode, you MUST:
          1. Document the estimation methodology in your paper
          2. Run sensitivity analysis comparing strict vs estimated
          3. Report the percentage of estimated severities
    """
    # Parse severity mode
    try:
        sev_mode = SeverityMode(severity_mode)
    except ValueError:
        logger.warning(f"Unknown severity_mode '{severity_mode}', defaulting to 'strict'")
        sev_mode = SeverityMode.STRICT

    if sev_mode == SeverityMode.ESTIMATED:
        logger.warning("=" * 70)
        logger.warning("USING ESTIMATED SEVERITY MODE")
        logger.warning("This allows severity estimation using industry ratios")
        logger.warning("For academic work, you MUST:")
        logger.warning("  1. Document the estimation methodology")
        logger.warning("  2. Run sensitivity analysis (strict vs estimated)")
        logger.warning("  3. Report % of estimated severities")
        logger.warning("=" * 70)

    logger.info(f"Loading corpus from {corpus_path}")
    raw_movements = load_unified_corpus(corpus_path)
    total_corpus = len(raw_movements)
    logger.info(f"Loaded {total_corpus} raw movements")
    
    # Filter by direction
    if direction_filter != 'all':
        raw_movements = [m for m in raw_movements if m.get('direction') == direction_filter]
        logger.info(f"Filtered to {len(raw_movements)} {direction_filter} movements")
    
    # Build syndicate profiles for complexity calculation
    logger.info("Computing syndicate portfolio profiles...")
    syndicate_profiles = {}
    profiles_with_actual_reserves = 0
    profiles_without_reserves = 0

    for m in raw_movements:
        syn = m.get('syndicate')
        year = m.get('year')
        if syn and year:
            key = (syn, year)
            if key not in syndicate_profiles:
                reserves, hhi, lob_weights, has_actual = compute_syndicate_portfolio_profile(
                    raw_movements, syn, year
                )
                syndicate_profiles[key] = {
                    'reserves': reserves,
                    'hhi': hhi,
                    'lob_weights': lob_weights,
                    'has_actual_reserves': has_actual
                }
                if has_actual:
                    profiles_with_actual_reserves += 1
                else:
                    profiles_without_reserves += 1

    # Report reserve data quality
    total_profiles = profiles_with_actual_reserves + profiles_without_reserves
    if total_profiles > 0:
        pct_with_reserves = 100 * profiles_with_actual_reserves / total_profiles
        logger.info(f"Syndicate profiles: {profiles_with_actual_reserves}/{total_profiles} "
                   f"({pct_with_reserves:.0f}%) have actual reserve data")
        if pct_with_reserves < 50:
            logger.warning("WARNING: Less than 50% of syndicate-years have actual reserve data!")
            logger.warning("         Complexity scores will be unreliable for profiles without reserves.")
            logger.warning("         Run extract_size_metrics.py to merge reserve data into corpus.")

    # Track diagnostics
    after_direction = len(raw_movements)
    dropped_no_severity = 0
    dropped_no_amount = 0
    dropped_no_reserves_sev = 0
    dropped_no_profile = 0
    estimated_count = 0
    actual_count = 0
    skipped_no_reserves_complexity = 0
    warnings = []
    lob_counts = defaultdict(int)

    # Process each movement
    prepared = []

    for m in raw_movements:
        # Get severity ratio using configured mode
        severity, sev_source = estimate_severity_ratio(m, sev_mode)

        if severity is None or severity <= 0:
            # Track why dropped
            if not m.get('amount_gbp_m'):
                dropped_no_amount += 1
            elif not m.get('prior_reserves_gbp_m') and not m.get('severity_ratio'):
                dropped_no_reserves_sev += 1
            else:
                dropped_no_severity += 1
            continue

        # Track severity source
        if sev_source == 'estimated':
            estimated_count += 1
        else:
            actual_count += 1

        # Get portfolio profile
        syn = m.get('syndicate')
        year = m.get('year')
        profile = syndicate_profiles.get((syn, year))

        if profile is None:
            dropped_no_profile += 1
            continue

        # Get reserves - use actual from corpus if available
        reserves = profile.get('reserves')
        if reserves is None:
            # Try to get from movement directly
            reserves = m.get('prior_reserves_gbp_m')

        if reserves is None or reserves <= 0:
            # Cannot compute meaningful complexity without reserves
            skipped_no_reserves_complexity += 1
            # Use amount-based estimate for complexity only (not severity)
            amt = abs(m.get('amount_gbp_m', 0) or 0)
            reserves = max(amt * 10, 50.0)  # Conservative estimate, min 50m
            logger.debug(f"No reserves for {syn}/{year}, estimated complexity from amount")

        # Compute complexity score: R × (1 - HHI)
        complexity = reserves * (1 - profile['hhi'])

        # Classify cause
        causes = m.get('primary_causes', [])
        narrative = m.get('standardized_narrative', '')
        cause_category = classify_cause_category(causes, narrative)

        # Track LOB coverage
        lob = m.get('line_of_business', 'Aggregate')
        lob_counts[lob] += 1

        # Create structured movement
        prepared_movement = HistoricalMovement(
            id=m.get('id', f"{syn}_{year}_{lob}"),
            source_type=m.get('source_type', 'syndicate'),
            year=year,
            syndicate=syn,
            line_of_business=lob,
            direction=m.get('direction', 'strengthening'),
            severity_ratio=severity,
            amount_gbp_m=m.get('amount_gbp_m'),
            amount_usd_m=m.get('amount_usd_m'),
            primary_causes=causes,
            specific_events=m.get('specific_events', []),
            narrative=narrative,
            lob_vector=compute_lob_vector(lob),
            complexity_score=complexity
        )

        prepared.append(prepared_movement)

    # Build warnings
    if estimated_count > 0:
        pct = 100 * estimated_count / (estimated_count + actual_count)
        warnings.append(f"WARNING: {pct:.0f}% of severities are estimated (not from actual data)")
        if pct > 30:
            warnings.append("CRITICAL: >30% estimated - run sensitivity analysis before publishing")

    if skipped_no_reserves_complexity > 0:
        warnings.append(f"NOTE: {skipped_no_reserves_complexity} movements used estimated complexity")

    total_dropped = dropped_no_severity + dropped_no_amount + dropped_no_reserves_sev + dropped_no_profile
    retention = len(prepared) / after_direction if after_direction > 0 else 0
    if retention < 0.5:
        warnings.append(f"LOW RETENTION: Only {retention:.0%} of {direction_filter} movements retained")
        warnings.append("Consider running extract_size_metrics.py to add reserve data")

    # Log results
    logger.info(f"Prepared {len(prepared)} movements")
    logger.info(f"  Dropped: {total_dropped} total")
    logger.info(f"    - No severity data: {dropped_no_severity}")
    logger.info(f"    - No amount: {dropped_no_amount}")
    logger.info(f"    - No reserves for severity: {dropped_no_reserves_sev}")
    logger.info(f"    - No syndicate profile: {dropped_no_profile}")
    if estimated_count > 0:
        logger.info(f"  Severity sources: {actual_count} actual, {estimated_count} estimated")
    if skipped_no_reserves_complexity > 0:
        logger.info(f"  Complexity: {skipped_no_reserves_complexity} used estimated reserves")

    for warn in warnings:
        logger.warning(warn)

    # Summary statistics
    if prepared:
        severities = [m.severity_ratio for m in prepared]
        complexities = [m.complexity_score for m in prepared]

        logger.info(f"Severity range: {min(severities):.3f} - {max(severities):.3f}")
        logger.info(f"Severity median: {sorted(severities)[len(severities)//2]:.3f}")
        logger.info(f"Complexity range: {min(complexities):.1f} - {max(complexities):.1f}")
    else:
        severities = []
        complexities = []
        logger.warning("No movements prepared - check filtering diagnostics")

    # Build diagnostics object
    diagnostics = PreparationDiagnostics(
        total_corpus=total_corpus,
        after_direction_filter=after_direction,
        after_severity_filter=actual_count + estimated_count,
        final_count=len(prepared),
        dropped_no_severity=dropped_no_severity,
        dropped_no_amount=dropped_no_amount,
        dropped_no_reserves=dropped_no_reserves_sev,
        dropped_no_profile=dropped_no_profile,
        estimated_severity_count=estimated_count,
        actual_severity_count=actual_count,
        warnings=warnings,
        unique_syndicates=len(set(m.syndicate for m in prepared)),
        unique_years=len(set(m.year for m in prepared)),
        lob_coverage=dict(lob_counts)
    )

    # Save if requested
    if output_path:
        output_data = {
            'movements': [vars(m) for m in prepared],
            'metadata': {
                'total_movements': len(prepared),
                'direction_filter': direction_filter,
                'severity_mode': severity_mode,
                'data_quality': {
                    'profiles_with_actual_reserves': profiles_with_actual_reserves,
                    'profiles_without_reserves': profiles_without_reserves,
                    'actual_severity_count': actual_count,
                    'estimated_severity_count': estimated_count,
                    'dropped_no_severity': dropped_no_severity,
                    'dropped_no_amount': dropped_no_amount,
                    'dropped_no_reserves': dropped_no_reserves_sev,
                    'dropped_no_profile': dropped_no_profile
                },
                'severity_stats': {
                    'min': min(severities) if severities else None,
                    'max': max(severities) if severities else None,
                    'median': sorted(severities)[len(severities)//2] if severities else None
                },
                'complexity_stats': {
                    'min': min(complexities) if complexities else None,
                    'max': max(complexities) if complexities else None,
                    'median': sorted(complexities)[len(complexities)//2] if complexities else None
                },
                'coverage': {
                    'unique_syndicates': diagnostics.unique_syndicates,
                    'unique_years': diagnostics.unique_years,
                    'lob_distribution': dict(lob_counts)
                },
                'warnings': warnings
            }
        }

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, indent=2, default=str)
        logger.info(f"Saved prepared data to {output_path}")

    # Return based on return_diagnostics flag
    if return_diagnostics:
        return prepared, diagnostics
    return prepared


def analyze_coverage(movements: List[HistoricalMovement]) -> Dict:
    """
    Analyze coverage of historical data across dimensions.
    """
    # By year
    years = defaultdict(int)
    for m in movements:
        years[m.year] += 1
    
    # By LOB
    lobs = defaultdict(int)
    for m in movements:
        lobs[m.line_of_business] += 1
    
    # By cause category
    causes = defaultdict(int)
    for m in movements:
        cat = classify_cause_category(m.primary_causes, m.narrative)
        causes[cat.value] += 1
    
    # Severity distribution
    severities = [m.severity_ratio for m in movements]
    severity_bins = defaultdict(int)
    for s in severities:
        bin_idx = int(s * 20)  # 5% bins
        bin_label = f"{bin_idx * 5}%-{(bin_idx + 1) * 5}%"
        severity_bins[bin_label] += 1
    
    # Complexity distribution
    complexities = [m.complexity_score for m in movements]
    complexity_bins = defaultdict(int)
    for c in complexities:
        if c < 50:
            complexity_bins['0-50'] += 1
        elif c < 150:
            complexity_bins['50-150'] += 1
        elif c < 300:
            complexity_bins['150-300'] += 1
        elif c < 500:
            complexity_bins['300-500'] += 1
        else:
            complexity_bins['500+'] += 1
    
    return {
        'by_year': dict(sorted(years.items())),
        'by_lob': dict(sorted(lobs.items(), key=lambda x: -x[1])),
        'by_cause': dict(sorted(causes.items(), key=lambda x: -x[1])),
        'by_severity': dict(sorted(severity_bins.items())),
        'by_complexity': dict(sorted(complexity_bins.items()))
    }


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

    parser = argparse.ArgumentParser(
        description="Prepare historical data for stress testing",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
SEVERITY MODES:
  strict   - Only use movements with actual reserve data (academic default)
  estimated - Allow severity estimation using industry ratios
              REQUIRES sensitivity analysis for academic work

EXAMPLES:
  # Standard preparation (strict mode)
  python data_preparation.py -c results/combined/unified_corpus.json

  # Include releases and use estimated severity (more data, less accurate)
  python data_preparation.py --direction all --severity-mode estimated

  # Run filtering diagnostics
  python filtering_diagnostics.py -c results/combined/unified_corpus.json
        """
    )
    parser.add_argument('--corpus', '-c', default='results/combined/unified_corpus.json',
                       help='Path to unified corpus')
    parser.add_argument('--output', '-o', default='results/stress_test/prepared_data.json',
                       help='Output path for prepared data')
    parser.add_argument('--direction', '-d', default='strengthening',
                       choices=['strengthening', 'release', 'all'],
                       help='Filter by direction (default: strengthening)')
    parser.add_argument('--severity-mode', '-m', default='strict',
                       choices=['strict', 'estimated'],
                       help='Severity calculation mode (default: strict)')
    parser.add_argument('--diagnostics', action='store_true',
                       help='Show detailed diagnostics')

    args = parser.parse_args()

    result = prepare_historical_data(
        args.corpus,
        args.output,
        args.direction,
        severity_mode=args.severity_mode,
        return_diagnostics=args.diagnostics
    )

    if args.diagnostics:
        movements, diagnostics = result
        print("\n" + "=" * 60)
        print("PREPARATION DIAGNOSTICS")
        print("=" * 60)
        print(f"Corpus total: {diagnostics.total_corpus}")
        print(f"After direction filter: {diagnostics.after_direction_filter}")
        print(f"After severity filter: {diagnostics.after_severity_filter}")
        print(f"Final count: {diagnostics.final_count}")
        print(f"\nRetention rate: {diagnostics.final_count / diagnostics.total_corpus:.1%}")
        print(f"\nSeverity sources:")
        print(f"  Actual: {diagnostics.actual_severity_count}")
        print(f"  Estimated: {diagnostics.estimated_severity_count}")
        print(f"\nDrop reasons:")
        print(f"  No severity data: {diagnostics.dropped_no_severity}")
        print(f"  No amount: {diagnostics.dropped_no_amount}")
        print(f"  No reserves: {diagnostics.dropped_no_reserves}")
        print(f"  No profile: {diagnostics.dropped_no_profile}")
        print(f"\nCoverage:")
        print(f"  Unique syndicates: {diagnostics.unique_syndicates}")
        print(f"  Unique years: {diagnostics.unique_years}")
        print(f"  LOBs: {list(diagnostics.lob_coverage.keys())}")
        if diagnostics.warnings:
            print(f"\nWarnings:")
            for w in diagnostics.warnings:
                print(f"  [!] {w}")
    else:
        movements = result

    print("\n=== Coverage Analysis ===")
    coverage = analyze_coverage(movements)
    for dim, counts in coverage.items():
        print(f"\n{dim}:")
        for k, v in counts.items():
            print(f"  {k}: {v}")
