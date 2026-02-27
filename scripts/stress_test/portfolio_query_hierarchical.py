"""
Portfolio Query with Hierarchical Matching
==========================================

Implements query-time scenario construction for arbitrary portfolio LOB mixes:

1. Compute proper LOB-level severities (movement / LOB_reserves)
2. Hierarchical matching:
   - Priority 1: Single syndicate covering all query LOBs
   - Priority 2: Supplement gaps with same-year syndicates
   - Priority 3: Full synthetic construction from same-year specialists
3. Narrative synthesis for merged scenarios
4. Size adjustment using empirical coefficients

This preserves:
- Intra-syndicate correlation (when using single syndicate)
- Inter-LOB market correlation (when merging within same year)

Usage:
    from portfolio_query_hierarchical import PortfolioQueryEngine
    
    engine = PortfolioQueryEngine()
    engine.load_corpus("results/combined/enhanced_corpus.json")
    
    results = engine.query(
        lob_weights={"Property": 0.6, "Marine": 0.4},
        portfolio_size_m=200,
        n_scenarios=100
    )

Author: Colin Priest
Date: December 2024
"""

import json
import logging
import numpy as np
import pandas as pd
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any, Set
from dataclasses import dataclass, field, asdict
from collections import defaultdict
import warnings

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


# =============================================================================
# Size Adjustment Coefficients (from empirical analysis)
# =============================================================================

DEFAULT_SIZE_COEFFICIENTS = {
    "Property": -0.49,
    "Aggregate": -0.34,
    "Casualty": -0.30,
    "Energy": -0.05,
    "Professional Lines": -0.03,
    "Reinsurance - Casualty": -0.02,
    "Accident & Health": -0.01,
    "Marine": -0.01,
    "Reinsurance - Property": 0.02,
    "Reinsurance - Specialty": 0.0,
    "Aviation": -0.02,
    "Motor": -0.02,
    "Cyber": -0.02,
}

DEFAULT_OVERALL_COEFFICIENT = -0.24
DEFAULT_REFERENCE_SIZE_M = 500.0


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class LOBObservation:
    """A single LOB-level observation with proper severity calculation."""
    syndicate: str
    year: int
    lob: str
    
    # Movement data
    movement_gbp_m: float
    direction: str  # 'release', 'strengthening', 'mixed', 'flat'
    
    # Reserve base for this LOB
    lob_reserves_gbp_m: float
    
    # Computed severity (movement / lob_reserves)
    lob_severity: float
    
    # Context
    narrative: str
    primary_causes: List[str]
    specific_events: List[str]
    
    # Syndicate context
    syndicate_total_reserves_gbp_m: float
    syndicate_lob_weight: float  # This LOB's share of syndicate
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class SyndicateYear:
    """All LOB observations for a syndicate in a given year."""
    syndicate: str
    year: int
    total_reserves_gbp_m: float
    
    # LOB data
    lob_weights: Dict[str, float]  # LOB -> weight in syndicate
    lob_observations: Dict[str, LOBObservation]  # LOB -> observation
    
    def has_lob(self, lob: str) -> bool:
        return lob in self.lob_observations
    
    def get_lob_severity(self, lob: str) -> Optional[float]:
        if lob in self.lob_observations:
            return self.lob_observations[lob].lob_severity
        return None
    
    def get_lob_narrative(self, lob: str) -> Optional[str]:
        if lob in self.lob_observations:
            return self.lob_observations[lob].narrative
        return None
    
    def coverage_score(self, query_lobs: Dict[str, float]) -> float:
        """
        Score how well this syndicate covers the query LOB mix.
        Returns fraction of query weight covered.
        """
        covered_weight = sum(
            weight for lob, weight in query_lobs.items()
            if self.has_lob(lob)
        )
        return covered_weight
    
    def lobs_covered(self, query_lobs: Dict[str, float]) -> Set[str]:
        """Return set of query LOBs that this syndicate covers."""
        return {lob for lob in query_lobs if self.has_lob(lob)}


@dataclass
class ScenarioComponent:
    """A single LOB component of a constructed scenario."""
    lob: str
    severity: float
    source_syndicate: str
    source_year: int
    match_type: str  # 'primary', 'supplementary'
    narrative: str
    primary_causes: List[str]
    specific_events: List[str]
    lob_weight_in_source: float
    

@dataclass
class ConstructedScenario:
    """A complete scenario constructed for a query portfolio."""
    year: int
    components: Dict[str, ScenarioComponent]
    
    # Computed values
    portfolio_severity_raw: float  # Before size adjustment
    portfolio_severity_adjusted: float  # After size adjustment
    
    # Quality metrics
    correlation_quality: str  # 'high' (single syndicate), 'medium' (same year), 'low' (mixed years)
    coverage_fraction: float  # Fraction of query weight covered
    primary_syndicate: Optional[str]  # If single syndicate covers most
    n_syndicates_used: int
    
    # Narrative
    combined_narrative: str
    
    # Size adjustment metadata
    query_size_m: float
    reference_size_m: float
    size_adjustment_factor: float
    
    def to_dict(self) -> Dict:
        def convert_numpy(obj):
            """Convert numpy types to native Python types."""
            if isinstance(obj, dict):
                return {k: convert_numpy(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [convert_numpy(v) for v in obj]
            elif isinstance(obj, (np.integer,)):
                return int(obj)
            elif isinstance(obj, (np.floating,)):
                return float(obj)
            elif isinstance(obj, np.ndarray):
                return obj.tolist()
            else:
                return obj

        d = asdict(self)
        d['components'] = {k: convert_numpy(asdict(v)) for k, v in self.components.items()}
        return convert_numpy(d)


@dataclass
class PerYearStats:
    """Statistics for a single year in even-year sampling."""
    year: int
    attempted: int
    valid: int
    valid_rate: float
    primary_selection_counts: Dict[str, int]  # syndicate -> count
    supplementation_counts: Dict[str, Dict[str, int]]  # LOB -> {syndicate -> count}


@dataclass
class QuerySummary:
    """Summary output from query_summary_even_years."""
    n_scenarios: int
    portfolio: Dict[str, Any]

    # Severity statistics
    severity_raw: Dict[str, Any]
    severity_adjusted: Dict[str, Any]

    # Metadata
    size_adjustment_factor: float
    coverage: Dict[str, float]
    correlation_quality: Dict[str, int]

    # Even-year specific fields
    years_included: List[int]
    years_excluded: Dict[int, str]  # year -> reason
    per_year_stats: Dict[int, PerYearStats]
    weights_description: str

    # Sampling configuration
    sampling_config: Dict[str, Any]
    seed: Optional[int]

    def to_dict(self) -> Dict:
        d = asdict(self)
        d['per_year_stats'] = {k: asdict(v) for k, v in self.per_year_stats.items()}
        return d


@dataclass
class BootstrapSummary:
    """Summary output from year-block bootstrap."""
    # Point estimates from full data
    point_estimate: Dict[float, float]  # percentile -> value

    # Bootstrap distributions
    bootstrap_quantiles: List[Dict[float, float]]  # list of {percentile -> value} per replicate

    # Confidence intervals for each percentile
    confidence_intervals: Dict[float, Dict[str, Any]]  # percentile -> {ci_90, ci_95, std_err, bias}

    # Metadata
    n_replicates: int
    n_per_year: int
    feasible_years: List[int]
    excluded_years: Dict[int, str]
    seed: Optional[int]
    sampling_config: Dict[str, Any]

    def to_dict(self) -> Dict:
        return asdict(self)


# =============================================================================
# Sampling Configuration
# =============================================================================

@dataclass
class SamplingConfig:
    """Configuration for stochastic selection."""
    # Primary selection parameters
    coverage_cap: float = 0.9
    alpha: float = 1.0
    tau: float = 0.15  # softmax temperature

    # Specialist selection parameters
    top_k: int = 5
    alpha_spec: float = 1.0

    # Size matching (off by default)
    use_size_matching: bool = False
    size_sigma: float = 1.0

    def to_dict(self) -> Dict:
        return asdict(self)


# =============================================================================
# Utility Functions
# =============================================================================

def weighted_quantile(values: np.ndarray, weights: np.ndarray,
                      quantiles: List[float]) -> Dict[float, float]:
    """
    Compute weighted quantiles.

    Args:
        values: Array of values
        weights: Array of weights (must sum to 1 or will be normalized)
        quantiles: List of quantiles to compute (0-1 scale)

    Returns:
        Dict mapping quantile -> value
    """
    if len(values) == 0:
        return {q: np.nan for q in quantiles}

    # Normalize weights
    weights = np.asarray(weights, dtype=np.float64)
    total_weight = weights.sum()
    if total_weight <= 0:
        return {q: np.nan for q in quantiles}
    weights = weights / total_weight

    # Sort by values
    sorter = np.argsort(values)
    values_sorted = np.asarray(values)[sorter]
    weights_sorted = weights[sorter]

    # Compute cumulative weights
    cumsum = np.cumsum(weights_sorted)

    results = {}
    for q in quantiles:
        # Find first index where cumulative weight >= q
        idx = np.searchsorted(cumsum, q)
        if idx >= len(values_sorted):
            idx = len(values_sorted) - 1
        results[q] = float(values_sorted[idx])

    return results


def softmax_with_temperature(scores: np.ndarray, tau: float) -> np.ndarray:
    """
    Compute softmax probabilities with temperature.

    Args:
        scores: Array of scores
        tau: Temperature (lower = more greedy, higher = more uniform)

    Returns:
        Array of probabilities
    """
    if tau <= 0:
        tau = 0.01  # Avoid division by zero

    # Subtract max for numerical stability
    scores_shifted = scores - np.max(scores)
    exp_scores = np.exp(scores_shifted / tau)
    return exp_scores / exp_scores.sum()


# =============================================================================
# Corpus Preparation
# =============================================================================

class CorpusPreparator:
    """Prepares corpus data with proper LOB-level severities."""

    def __init__(self, strict_mode: bool = False, max_estimated_pct: float = 50.0):
        """
        Initialize corpus preparator.

        Args:
            strict_mode: If True, raise error when data quality is poor
            max_estimated_pct: Maximum % of syndicate-years with estimated reserves
                              before raising error in strict mode (default: 50%)
        """
        self.strict_mode = strict_mode
        self.max_estimated_pct = max_estimated_pct
        self.syndicate_years: Dict[Tuple[str, int], SyndicateYear] = {}
        self.years_available: Set[int] = set()
        self.lobs_available: Set[str] = set()
        self.coverage_stats: Dict[str, Any] = {}
        # Data quality tracking
        self.data_quality: Dict[str, Any] = {
            'has_actual_reserves': 0,
            'has_estimated_reserves': 0,
            'has_lob_weights': 0,
            'has_precomputed_severity': 0,
            'missing_syndicate': 0,
            'missing_year': 0,
            'missing_amount': 0,
            'zero_reserves': 0,
        }

    def load_and_prepare(self, corpus_path: str) -> 'CorpusPreparator':
        """Load corpus and compute LOB-level severities."""

        logger.info(f"Loading corpus from {corpus_path}")

        with open(corpus_path, 'r') as f:
            data = json.load(f)

        movements = data.get('movements', [])
        logger.info(f"Loaded {len(movements)} movements")

        # Check for required fields in first few movements
        self._check_corpus_fields(movements)

        # Group by syndicate-year
        synd_year_movements = defaultdict(list)
        for m in movements:
            syndicate = m.get('syndicate')
            year = m.get('year')
            if not syndicate:
                self.data_quality['missing_syndicate'] += 1
                continue
            if not year:
                self.data_quality['missing_year'] += 1
                continue
            synd_year_movements[(str(syndicate), int(year))].append(m)

        logger.info(f"Found {len(synd_year_movements)} syndicate-years")

        # Process each syndicate-year
        for (syndicate, year), movements_list in synd_year_movements.items():
            synd_year = self._process_syndicate_year(syndicate, year, movements_list)
            if synd_year and synd_year.lob_observations:
                self.syndicate_years[(syndicate, year)] = synd_year
                self.years_available.add(year)
                self.lobs_available.update(synd_year.lob_observations.keys())

        self._compute_coverage_stats()
        self._log_data_quality_report()

        return self

    def _check_corpus_fields(self, all_movements: List[Dict]) -> None:
        """Check what fields are available in the corpus and log summary."""
        if not all_movements:
            logger.warning("Corpus is empty - no movements to process")
            return

        # Check for reserve fields across ALL movements (not just sample)
        reserve_fields = [
            'prior_reserves_gbp_m',
            'technical_provisions_gbp_m',
            'claims_outstanding_gbp_m',
            'stamp_capacity_gbp_m'
        ]
        found_reserve_fields = []
        counts = {}
        for field in reserve_fields:
            count = sum(1 for m in all_movements if m.get(field))
            if count > 0:
                found_reserve_fields.append(field)
                counts[field] = count

        if not found_reserve_fields:
            logger.warning("=" * 60)
            logger.warning("DATA QUALITY WARNING: No reserve fields found in corpus!")
            logger.warning("Expected one of: " + ", ".join(reserve_fields))
            logger.warning("Will estimate reserves from movement amounts (10x multiplier)")
            logger.warning("For accurate severity calculations, run:")
            logger.warning("  python extract_size_metrics.py merge --size-metrics size_metrics.json \\")
            logger.warning("         --corpus unified_corpus.json --output enhanced_corpus.json")
            logger.warning("=" * 60)
        else:
            logger.info(f"Found reserve fields: {found_reserve_fields}")
            for field, count in counts.items():
                logger.info(f"  - {field}: {count} movements ({100*count/len(all_movements):.1f}%)")

        # Check for LOB weight fields
        if any(m.get('lob_weights') for m in all_movements):
            logger.info("Found pre-computed LOB weights in corpus")
        else:
            logger.info("No pre-computed LOB weights - will estimate from movements")

        # Check for pre-computed severity
        if any(m.get('lob_severity_ratio') for m in all_movements):
            logger.info("Found pre-computed LOB severity ratios in corpus")

    def _log_data_quality_report(self) -> None:
        """Log a summary of data quality metrics and enforce strict mode if enabled."""
        dq = self.data_quality
        total = dq['has_actual_reserves'] + dq['has_estimated_reserves']

        logger.info("=" * 60)
        logger.info("DATA QUALITY REPORT")
        logger.info("=" * 60)
        logger.info(f"Syndicate-years processed: {len(self.syndicate_years)}")

        if self.years_available:
            logger.info(f"Years available: {min(self.years_available)}-{max(self.years_available)}")
            logger.info(f"LOBs available: {len(self.lobs_available)}")

        logger.info(f"\nReserve data:")
        logger.info(f"  - With actual reserves: {dq['has_actual_reserves']}")
        logger.info(f"  - With estimated reserves: {dq['has_estimated_reserves']}")

        pct_estimated = 0.0
        if total > 0:
            pct_estimated = dq['has_estimated_reserves'] / total * 100
            if pct_estimated > 50:
                logger.warning(f"  WARNING: {pct_estimated:.0f}% of syndicate-years use estimated reserves!")
                logger.warning("  This produces UNRELIABLE severity calculations!")
                logger.warning("  Run extract_size_metrics.py to merge actual reserve data.")

        logger.info(f"\nEnhanced data:")
        logger.info(f"  - With LOB weights: {dq['has_lob_weights']}")
        logger.info(f"  - With pre-computed severity: {dq['has_precomputed_severity']}")

        if dq['missing_syndicate'] > 0 or dq['missing_year'] > 0:
            logger.warning(f"\nSkipped movements:")
            logger.warning(f"  - Missing syndicate: {dq['missing_syndicate']}")
            logger.warning(f"  - Missing year: {dq['missing_year']}")

        if dq['zero_reserves'] > 0:
            logger.warning(f"  - Zero/invalid reserves: {dq['zero_reserves']}")

        logger.info("=" * 60)

        # Store for access
        self.coverage_stats['data_quality'] = dict(dq)

        # STRICT MODE: Fail if data quality is poor
        if self.strict_mode and pct_estimated > self.max_estimated_pct:
            raise ValueError(
                f"DATA QUALITY FAILURE (strict_mode=True): "
                f"{pct_estimated:.0f}% of syndicate-years use estimated reserves "
                f"(threshold: {self.max_estimated_pct}%). "
                f"Run extract_size_metrics.py to merge actual reserve data, or "
                f"set strict_mode=False to proceed with degraded accuracy."
            )
    
    def _process_syndicate_year(self, syndicate: str, year: int,
                                 movements: List[Dict]) -> Optional[SyndicateYear]:
        """Process all movements for a syndicate-year into LOB observations."""

        # Compute LOB amounts first (needed for reserve estimation fallback)
        lob_amounts = defaultdict(float)
        for m in movements:
            lob = m.get('line_of_business', 'Aggregate')
            amount = abs(m.get('amount_gbp_m') or 0)
            lob_amounts[lob] += amount

        total_amount = sum(lob_amounts.values())

        # Get syndicate total reserves (should be same across all movements)
        total_reserves = None
        for m in movements:
            reserves = (
                m.get('prior_reserves_gbp_m') or
                m.get('technical_provisions_gbp_m') or
                m.get('claims_outstanding_gbp_m') or
                m.get('stamp_capacity_gbp_m')
            )
            if reserves:
                total_reserves = float(reserves)
                break

        # Fallback: estimate total reserves from movement amounts
        # Movements typically represent 5-15% of reserves, so use 10x multiplier
        if not total_reserves or total_reserves <= 0:
            if total_amount > 0:
                total_reserves = total_amount * 10.0  # Heuristic: movements ~10% of reserves
                self.data_quality['has_estimated_reserves'] += 1
                logger.debug(f"Estimated reserves for {syndicate}/{year}: {total_reserves:.1f}m from movements {total_amount:.1f}m")
            else:
                self.data_quality['zero_reserves'] += 1
                return None
        else:
            self.data_quality['has_actual_reserves'] += 1

        # Check if we have pre-computed LOB weights from Segmental Analysis extraction
        # Use the first movement's lob_weights as they're all from the same syndicate-year
        corpus_lob_weights = None
        for m in movements:
            if 'lob_weights' in m and m['lob_weights']:
                corpus_lob_weights = m['lob_weights']
                self.data_quality['has_lob_weights'] += 1
                break

        # Check for pre-computed severity
        has_precomputed = any(m.get('lob_severity_ratio') is not None for m in movements)
        if has_precomputed:
            self.data_quality['has_precomputed_severity'] += 1

        if corpus_lob_weights:
            # Use actual LOB weights from Segmental Analysis
            lob_weights = corpus_lob_weights
        elif total_amount <= 0:
            # Fall back to equal weights
            lob_weights = {lob: 1.0 / len(movements) for lob in lob_amounts}
        else:
            # Fall back to movement-based weights (circular, but better than nothing)
            lob_weights = {lob: amt / total_amount for lob, amt in lob_amounts.items()}
        
        # Create LOB observations
        lob_observations = {}
        for m in movements:
            lob = m.get('line_of_business', 'Aggregate')
            movement_amt = m.get('amount_gbp_m')
            direction = m.get('direction', 'mixed')
            
            if movement_amt is None:
                continue
            
            # Check if we have pre-computed LOB severity from corpus
            precomputed_severity = m.get('lob_severity_ratio')
            precomputed_lob_reserves = m.get('lob_reserves_gbp_m')
            precomputed_lob_weight = m.get('lob_weight')
            
            if precomputed_severity is not None and precomputed_lob_reserves is not None:
                # Use pre-computed values from Segmental Analysis extraction
                lob_severity = precomputed_severity
                lob_reserves = precomputed_lob_reserves
                lob_weight = precomputed_lob_weight or lob_weights.get(lob, 0.1)
            else:
                # Fall back to estimated calculation
                # Get LOB weight from corpus weights or estimate
                lob_weight = lob_weights.get(lob, 0.1)  # Default 10% if unknown
                lob_reserves = total_reserves * max(lob_weight, 0.01)  # Floor to avoid division issues
                
                # Compute LOB severity
                # Positive severity = adverse (strengthening)
                # Negative severity = favorable (release)
                movement_amt = float(movement_amt)
                if direction == 'release':
                    signed_movement = -abs(movement_amt)
                elif direction == 'strengthening':
                    signed_movement = abs(movement_amt)
                else:
                    signed_movement = movement_amt
                
                lob_severity = signed_movement / lob_reserves
            
            # Cap extreme severities to ±500% (prevents unrealistic values from tiny LOB exposures)
            MAX_SEVERITY = 5.0  # 500%
            if abs(lob_severity) > MAX_SEVERITY:
                lob_severity = MAX_SEVERITY if lob_severity > 0 else -MAX_SEVERITY
            
            # Store lob_weight for query-time filtering (filter will be relative to query weight)
            movement_amt = float(movement_amt)
            
            # Create observation
            obs = LOBObservation(
                syndicate=syndicate,
                year=year,
                lob=lob,
                movement_gbp_m=movement_amt,
                direction=direction,
                lob_reserves_gbp_m=lob_reserves,
                lob_severity=lob_severity,
                narrative=m.get('standardized_narrative', ''),
                primary_causes=m.get('primary_causes', []),
                specific_events=m.get('specific_events', []),
                syndicate_total_reserves_gbp_m=total_reserves,
                syndicate_lob_weight=lob_weight
            )
            
            # Keep only one observation per LOB (the most significant)
            if lob not in lob_observations or abs(obs.lob_severity) > abs(lob_observations[lob].lob_severity):
                lob_observations[lob] = obs
        
        if not lob_observations:
            return None
        
        return SyndicateYear(
            syndicate=syndicate,
            year=year,
            total_reserves_gbp_m=total_reserves,
            lob_weights=lob_weights,
            lob_observations=lob_observations
        )
    
    def _compute_coverage_stats(self):
        """Compute statistics about data coverage."""
        
        # LOB coverage by year
        lob_by_year = defaultdict(set)
        for (synd, year), sy in self.syndicate_years.items():
            for lob in sy.lob_observations:
                lob_by_year[year].add(lob)
        
        # Syndicate count by year
        syndicates_by_year = defaultdict(set)
        for (synd, year), sy in self.syndicate_years.items():
            syndicates_by_year[year].add(synd)
        
        # LOB observation counts
        lob_counts = defaultdict(int)
        for sy in self.syndicate_years.values():
            for lob in sy.lob_observations:
                lob_counts[lob] += 1
        
        self.coverage_stats = {
            'n_syndicate_years': len(self.syndicate_years),
            'n_years': len(self.years_available),
            'n_lobs': len(self.lobs_available),
            'lob_counts': dict(lob_counts),
            'syndicates_per_year': {y: len(s) for y, s in syndicates_by_year.items()},
            'lobs_per_year': {y: len(l) for y, l in lob_by_year.items()}
        }
    
    def get_syndicates_for_year(self, year: int) -> List[SyndicateYear]:
        """Get all syndicate-years for a given year."""
        return [
            sy for (synd, y), sy in self.syndicate_years.items()
            if y == year
        ]
    
    def get_years_with_lob(self, lob: str) -> Set[int]:
        """Get years that have observations for a specific LOB."""
        years = set()
        for (synd, year), sy in self.syndicate_years.items():
            if sy.has_lob(lob):
                years.add(year)
        return years

    def year_feasibility(self, year: int, query_lob_weights: Dict[str, float],
                         min_coverage: float) -> Tuple[bool, float]:
        """
        Check if a year is feasible for constructing scenarios.

        A year is feasible if at least one constructed draw can reach
        coverage_fraction >= min_coverage using same-year supplementation.

        Args:
            year: Year to check
            query_lob_weights: Query portfolio LOB weights
            min_coverage: Minimum coverage fraction required

        Returns:
            Tuple of (is_feasible, max_achievable_coverage)
        """
        syndicates = self.get_syndicates_for_year(year)
        if not syndicates:
            return False, 0.0

        required_lobs = {lob for lob, w in query_lob_weights.items() if w > 0}

        # Dynamic minimum LOB weight threshold
        def min_source_weight(query_weight: float) -> float:
            return max(0.01, min(0.10, query_weight * 0.25))

        # Compute max achievable coverage by union of all LOBs available in the year
        # that satisfy the exposure sufficiency rule
        coverable_lobs = set()
        for lob in required_lobs:
            query_weight = query_lob_weights.get(lob, 0)
            min_weight = min_source_weight(query_weight)
            # Check if any syndicate in this year can provide this LOB
            for synd in syndicates:
                if synd.has_lob(lob):
                    obs = synd.lob_observations[lob]
                    if obs.syndicate_lob_weight >= min_weight:
                        coverable_lobs.add(lob)
                        break

        max_coverage = sum(
            query_lob_weights.get(lob, 0)
            for lob in coverable_lobs
        )

        return max_coverage >= min_coverage, max_coverage

    def get_feasible_years(self, query_lob_weights: Dict[str, float],
                           min_coverage: float) -> Tuple[List[int], Dict[int, str]]:
        """
        Get all feasible years for a query portfolio.

        Args:
            query_lob_weights: Query portfolio LOB weights
            min_coverage: Minimum coverage fraction required

        Returns:
            Tuple of (feasible_years_list, excluded_years_dict)
            excluded_years_dict maps year -> exclusion reason
        """
        feasible_years = []
        excluded_years = {}

        for year in sorted(self.years_available):
            is_feasible, max_cov = self.year_feasibility(year, query_lob_weights, min_coverage)
            if is_feasible:
                feasible_years.append(year)
            else:
                excluded_years[year] = f"max_coverage={max_cov:.2f} < min_coverage={min_coverage}"

        return feasible_years, excluded_years


# =============================================================================
# Hierarchical Matching Engine
# =============================================================================

class HierarchicalMatcher:
    """Matches query portfolios to historical data using hierarchical strategy."""

    def __init__(self, corpus: CorpusPreparator, min_coverage: float = 0.5,
                 sampling_config: Optional[SamplingConfig] = None):
        """
        Args:
            corpus: Prepared corpus data
            min_coverage: Minimum coverage fraction to use a single syndicate
            sampling_config: Configuration for stochastic selection
        """
        self.corpus = corpus
        self.min_coverage = min_coverage
        self.sampling_config = sampling_config or SamplingConfig()

    def construct_scenario_for_year(self,
                                     year: int,
                                     query_lob_weights: Dict[str, float]
                                     ) -> Optional[Dict[str, ScenarioComponent]]:
        """
        Construct a scenario for the query portfolio from a specific year.
        (Deterministic version - uses argmax selection)

        Uses hierarchical matching:
        1. Try single syndicate covering most/all LOBs
        2. Supplement gaps with same-year syndicates

        Returns dict of LOB -> ScenarioComponent, or None if year has no data
        """
        syndicates = self.corpus.get_syndicates_for_year(year)
        if not syndicates:
            return None

        required_lobs = {lob for lob, w in query_lob_weights.items() if w > 0}
        result: Dict[str, ScenarioComponent] = {}
        unmatched_lobs = set(required_lobs)

        # Dynamic minimum LOB weight: source should have at least 25% of query weight
        # but with an absolute floor of 1% and cap at 10%
        def min_source_weight(query_weight: float) -> float:
            return max(0.01, min(0.10, query_weight * 0.25))

        # Priority 1: Find best single syndicate
        best_syndicate = None
        best_coverage = 0

        for synd in syndicates:
            coverage = synd.coverage_score(query_lob_weights)
            if coverage > best_coverage:
                best_coverage = coverage
                best_syndicate = synd

        # Use best syndicate if it meets minimum coverage
        primary_syndicate = None
        if best_syndicate and best_coverage >= self.min_coverage:
            primary_syndicate = best_syndicate.syndicate
            for lob in required_lobs:
                if best_syndicate.has_lob(lob):
                    obs = best_syndicate.lob_observations[lob]
                    query_weight = query_lob_weights.get(lob, 0)

                    # Check if source has sufficient exposure relative to query
                    if obs.syndicate_lob_weight >= min_source_weight(query_weight):
                        result[lob] = ScenarioComponent(
                            lob=lob,
                            severity=obs.lob_severity,
                            source_syndicate=best_syndicate.syndicate,
                            source_year=year,
                            match_type='primary',
                            narrative=obs.narrative,
                            primary_causes=obs.primary_causes,
                            specific_events=obs.specific_events,
                            lob_weight_in_source=obs.syndicate_lob_weight
                        )
                        unmatched_lobs.discard(lob)

        # Priority 2 & 3: Fill gaps from same-year specialists
        for lob in list(unmatched_lobs):
            query_weight = query_lob_weights.get(lob, 0)
            specialist = self._find_lob_specialist(lob, syndicates, min_source_weight(query_weight))
            if specialist:
                obs = specialist.lob_observations[lob]
                result[lob] = ScenarioComponent(
                    lob=lob,
                    severity=obs.lob_severity,
                    source_syndicate=specialist.syndicate,
                    source_year=year,
                    match_type='supplementary',
                    narrative=obs.narrative,
                    primary_causes=obs.primary_causes,
                    specific_events=obs.specific_events,
                    lob_weight_in_source=obs.syndicate_lob_weight
                )
                unmatched_lobs.discard(lob)

        if not result:
            return None

        return result

    def construct_scenario_for_year_stochastic(
            self,
            year: int,
            query_lob_weights: Dict[str, float],
            rng: np.random.Generator,
            target_size_m: Optional[float] = None
    ) -> Tuple[Optional[Dict[str, ScenarioComponent]], Optional[str], Dict[str, str]]:
        """
        Construct a scenario using stochastic selection.

        Args:
            year: Year to construct scenario from
            query_lob_weights: Query portfolio LOB weights
            rng: Random number generator for reproducibility
            target_size_m: Target portfolio size (for optional size matching)

        Returns:
            Tuple of (components_dict, primary_syndicate_id, supplementary_selections)
            where supplementary_selections maps LOB -> syndicate_id
        """
        syndicates = self.corpus.get_syndicates_for_year(year)
        if not syndicates:
            return None, None, {}

        required_lobs = {lob for lob, w in query_lob_weights.items() if w > 0}
        result: Dict[str, ScenarioComponent] = {}
        unmatched_lobs = set(required_lobs)
        supplementary_selections: Dict[str, str] = {}

        cfg = self.sampling_config

        # Dynamic minimum LOB weight threshold
        def min_source_weight(query_weight: float) -> float:
            return max(0.01, min(0.10, query_weight * 0.25))

        # =========================================================
        # STOCHASTIC PRIMARY SELECTION
        # =========================================================
        # Build candidate set: syndicates with coverage >= min_coverage (roughly)
        primary_candidates = []
        primary_scores = []

        for synd in syndicates:
            coverage = synd.coverage_score(query_lob_weights)
            if coverage >= self.min_coverage * 0.5:  # Allow some flexibility
                # Compute score with capping and alpha
                capped_coverage = min(coverage, cfg.coverage_cap)
                score = capped_coverage ** cfg.alpha

                # Optional size matching
                if cfg.use_size_matching and target_size_m and target_size_m > 0:
                    log_size_diff = np.log(synd.total_reserves_gbp_m + 1) - np.log(target_size_m + 1)
                    size_kernel = np.exp(-log_size_diff**2 / (2 * cfg.size_sigma**2))
                    score *= size_kernel

                primary_candidates.append(synd)
                primary_scores.append(score)

        # Select primary syndicate stochastically
        primary_syndicate = None
        selected_primary_id = None

        if primary_candidates:
            # Convert to probabilities with softmax temperature
            scores_array = np.array(primary_scores)
            probs = softmax_with_temperature(scores_array, cfg.tau)

            # Sample primary
            idx = rng.choice(len(primary_candidates), p=probs)
            primary_syndicate = primary_candidates[idx]
            selected_primary_id = primary_syndicate.syndicate

            # Extract LOBs from primary
            for lob in required_lobs:
                if primary_syndicate.has_lob(lob):
                    obs = primary_syndicate.lob_observations[lob]
                    query_weight = query_lob_weights.get(lob, 0)

                    if obs.syndicate_lob_weight >= min_source_weight(query_weight):
                        result[lob] = ScenarioComponent(
                            lob=lob,
                            severity=obs.lob_severity,
                            source_syndicate=primary_syndicate.syndicate,
                            source_year=year,
                            match_type='primary',
                            narrative=obs.narrative,
                            primary_causes=obs.primary_causes,
                            specific_events=obs.specific_events,
                            lob_weight_in_source=obs.syndicate_lob_weight
                        )
                        unmatched_lobs.discard(lob)

        # =========================================================
        # STOCHASTIC SPECIALIST SELECTION FOR REMAINING LOBS
        # =========================================================
        for lob in list(unmatched_lobs):
            query_weight = query_lob_weights.get(lob, 0)
            specialist = self._find_lob_specialist_stochastic(
                lob, syndicates, min_source_weight(query_weight), rng
            )
            if specialist:
                obs = specialist.lob_observations[lob]
                result[lob] = ScenarioComponent(
                    lob=lob,
                    severity=obs.lob_severity,
                    source_syndicate=specialist.syndicate,
                    source_year=year,
                    match_type='supplementary',
                    narrative=obs.narrative,
                    primary_causes=obs.primary_causes,
                    specific_events=obs.specific_events,
                    lob_weight_in_source=obs.syndicate_lob_weight
                )
                supplementary_selections[lob] = specialist.syndicate
                unmatched_lobs.discard(lob)

        if not result:
            return None, None, {}

        return result, selected_primary_id, supplementary_selections

    def _find_lob_specialist(self, lob: str, syndicates: List[SyndicateYear],
                              min_weight: float = 0.01) -> Optional[SyndicateYear]:
        """Find the best syndicate for a specific LOB (highest weight in that LOB).
        (Deterministic version)

        Args:
            lob: Line of business to find
            syndicates: List of candidate syndicates
            min_weight: Minimum LOB weight required in source syndicate
        """
        best = None
        best_weight = 0

        for synd in syndicates:
            if synd.has_lob(lob):
                weight = synd.lob_weights.get(lob, 0)
                if weight >= min_weight and weight > best_weight:
                    best_weight = weight
                    best = synd

        return best

    def _find_lob_specialist_stochastic(
            self,
            lob: str,
            syndicates: List[SyndicateYear],
            min_weight: float,
            rng: np.random.Generator
    ) -> Optional[SyndicateYear]:
        """
        Find a specialist syndicate for a LOB using stochastic selection.

        Selects from top-k candidates by LOB weight, with probability
        proportional to (lob_weight)^alpha_spec.

        Args:
            lob: Line of business to find
            syndicates: List of candidate syndicates
            min_weight: Minimum LOB weight required
            rng: Random number generator

        Returns:
            Selected syndicate or None
        """
        cfg = self.sampling_config

        # Build candidate set
        candidates = []
        weights = []

        for synd in syndicates:
            if synd.has_lob(lob):
                weight = synd.lob_weights.get(lob, 0)
                if weight >= min_weight:
                    candidates.append(synd)
                    weights.append(weight)

        if not candidates:
            return None

        # Sort by weight and take top-k
        sorted_indices = np.argsort(weights)[::-1][:cfg.top_k]
        top_candidates = [candidates[i] for i in sorted_indices]
        top_weights = np.array([weights[i] for i in sorted_indices])

        # Compute selection probabilities
        scores = top_weights ** cfg.alpha_spec
        probs = scores / scores.sum()

        # Sample
        idx = rng.choice(len(top_candidates), p=probs)
        return top_candidates[idx]

    def assess_correlation_quality(self, components: Dict[str, ScenarioComponent]) -> str:
        """Assess the correlation quality of a constructed scenario."""
        if not components:
            return 'none'
        
        syndicates_used = {c.source_syndicate for c in components.values()}
        
        if len(syndicates_used) == 1:
            return 'high'  # All from same syndicate - intra-syndicate correlation preserved
        else:
            return 'medium'  # Same year, different syndicates - inter-LOB market correlation only


# =============================================================================
# Size Adjustment
# =============================================================================

class SizeAdjuster:
    """Applies size-based severity adjustments."""
    
    def __init__(self, 
                 coefficients: Dict[str, float] = None,
                 reference_size_m: float = DEFAULT_REFERENCE_SIZE_M):
        self.coefficients = coefficients or DEFAULT_SIZE_COEFFICIENTS
        self.overall_coefficient = DEFAULT_OVERALL_COEFFICIENT
        self.reference_size_m = reference_size_m
    
    def get_coefficient(self, lob: str) -> float:
        """Get size coefficient for a LOB."""
        if lob in self.coefficients:
            return self.coefficients[lob]
        
        # Try partial match
        lob_lower = lob.lower()
        for key, value in self.coefficients.items():
            if lob_lower in key.lower() or key.lower() in lob_lower:
                return value
        
        return self.overall_coefficient
    
    def compute_weighted_coefficient(self, lob_weights: Dict[str, float]) -> float:
        """Compute LOB-weighted size coefficient."""
        total_weight = sum(lob_weights.values())
        if total_weight == 0:
            return self.overall_coefficient
        
        weighted_coef = sum(
            weight * self.get_coefficient(lob)
            for lob, weight in lob_weights.items()
        )
        return weighted_coef / total_weight
    
    def adjustment_factor(self, 
                          query_size_m: float,
                          lob_weights: Dict[str, float]) -> float:
        """Compute size adjustment factor for a portfolio."""
        if query_size_m <= 0:
            return 1.0
        
        beta = self.compute_weighted_coefficient(lob_weights)
        return (query_size_m / self.reference_size_m) ** beta


# =============================================================================
# Narrative Synthesis
# =============================================================================

class NarrativeSynthesizer:
    """Synthesizes combined narratives from scenario components."""
    
    def synthesize(self, 
                   components: Dict[str, ScenarioComponent],
                   query_lob_weights: Dict[str, float]) -> str:
        """
        Create a combined narrative from components.
        
        For now, uses simple concatenation with structure.
        Can be enhanced to use LLM synthesis.
        """
        if not components:
            return "No scenario components available."
        
        # Sort by query weight (most important LOBs first)
        sorted_lobs = sorted(
            components.keys(),
            key=lambda lob: query_lob_weights.get(lob, 0),
            reverse=True
        )
        
        # Check if all from same syndicate
        syndicates = {c.source_syndicate for c in components.values()}
        year = next(iter(components.values())).source_year
        
        if len(syndicates) == 1:
            synd = next(iter(syndicates))
            header = f"Scenario based on Syndicate {synd} experience in {year}:\n\n"
        else:
            header = f"Scenario based on {year} market experience (combined from {len(syndicates)} syndicates):\n\n"
        
        # Build narrative
        sections = []
        for lob in sorted_lobs:
            comp = components[lob]
            weight = query_lob_weights.get(lob, 0)
            
            direction = "adverse" if comp.severity > 0 else "favorable"
            severity_pct = abs(comp.severity) * 100
            
            section = f"**{lob}** ({weight:.0%} of portfolio): {severity_pct:.1f}% {direction} development"
            
            if comp.narrative:
                # Extract first sentence or two
                narrative_short = comp.narrative[:200]
                if len(comp.narrative) > 200:
                    narrative_short = narrative_short.rsplit(' ', 1)[0] + '...'
                section += f"\n  {narrative_short}"
            
            if comp.primary_causes:
                section += f"\n  Causes: {', '.join(comp.primary_causes[:3])}"
            
            sections.append(section)
        
        return header + '\n\n'.join(sections)
    
    def synthesize_with_llm(self,
                            components: Dict[str, ScenarioComponent],
                            query_lob_weights: Dict[str, float],
                            llm_client: Any = None) -> str:
        """
        Use LLM to synthesize a coherent combined narrative.
        
        Args:
            components: Scenario components by LOB
            query_lob_weights: Query portfolio weights
            llm_client: LLM client for generation
            
        Returns:
            Synthesized narrative
        """
        if llm_client is None:
            return self.synthesize(components, query_lob_weights)
        
        # Build prompt
        year = next(iter(components.values())).source_year
        syndicates = {c.source_syndicate for c in components.values()}
        
        component_descriptions = []
        for lob, comp in components.items():
            weight = query_lob_weights.get(lob, 0)
            direction = "strengthening" if comp.severity > 0 else "release"
            component_descriptions.append(
                f"- {lob} ({weight:.0%} of portfolio): {abs(comp.severity)*100:.1f}% {direction}\n"
                f"  From Syndicate {comp.source_syndicate}: {comp.narrative}"
            )
        
        prompt = f"""Synthesize a coherent stress scenario narrative from these {year} Lloyd's market experiences.

The target portfolio has the following LOB mix and historical impacts:

{chr(10).join(component_descriptions)}

Write a unified 2-3 paragraph scenario narrative that:
1. Describes the key market events/conditions that drove these outcomes
2. Explains the causal relationships
3. Is written from the perspective of a portfolio with this LOB mix
4. Does not mention specific syndicate numbers

Scenario:"""

        # Call LLM (implementation depends on client)
        # response = llm_client.complete(prompt)
        # return response
        
        # Fallback to simple synthesis
        return self.synthesize(components, query_lob_weights)


# =============================================================================
# Main Query Engine
# =============================================================================

class PortfolioQueryEngine:
    """
    Main engine for querying scenarios for arbitrary portfolios.

    Combines:
    - Corpus preparation with LOB-level severities
    - Hierarchical matching
    - Size adjustment
    - Narrative synthesis
    """

    def __init__(self, strict_mode: bool = False):
        """
        Initialize the portfolio query engine.

        Args:
            strict_mode: If True, raise error when data quality is poor
                        (e.g., >50% of syndicate-years use estimated reserves)
        """
        self.strict_mode = strict_mode
        self.corpus: Optional[CorpusPreparator] = None
        self.matcher: Optional[HierarchicalMatcher] = None
        self.size_adjuster = SizeAdjuster()
        self.narrative_synth = NarrativeSynthesizer()
        self._is_loaded = False

    def load_corpus(self, corpus_path: str) -> 'PortfolioQueryEngine':
        """Load and prepare the corpus."""
        self.corpus = CorpusPreparator(strict_mode=self.strict_mode)
        self.corpus.load_and_prepare(corpus_path)

        if not self.corpus.years_available:
            raise ValueError(
                f"No valid syndicate-years found in corpus at {corpus_path}. "
                "Ensure the corpus contains movements with 'syndicate', 'year', "
                "reserve data (prior_reserves_gbp_m, etc.), and movement amounts (amount_gbp_m)."
            )

        self.matcher = HierarchicalMatcher(self.corpus)
        self._is_loaded = True
        return self
    
    def query(self,
              lob_weights: Dict[str, float],
              portfolio_size_m: float,
              n_scenarios: int = 100,
              years: Optional[List[int]] = None,
              min_coverage: float = 0.3,
              synthesize_narrative: bool = True) -> List[ConstructedScenario]:
        """
        Query scenarios for a portfolio.
        
        Args:
            lob_weights: Portfolio LOB weights (should sum to 1)
            portfolio_size_m: Portfolio size in £m
            n_scenarios: Number of scenarios to generate
            years: Specific years to sample from (None = all available)
            min_coverage: Minimum fraction of portfolio that must be covered
            synthesize_narrative: Whether to create combined narratives
            
        Returns:
            List of ConstructedScenario objects
        """
        if not self._is_loaded:
            raise RuntimeError("Corpus not loaded. Call load_corpus() first.")
        
        # Normalize weights
        total_weight = sum(lob_weights.values())
        if total_weight > 0:
            lob_weights = {k: v / total_weight for k, v in lob_weights.items()}
        
        # Determine years to sample
        if years is None:
            years = list(self.corpus.years_available)
        else:
            years = [y for y in years if y in self.corpus.years_available]
        
        if not years:
            logger.warning("No valid years available")
            return []
        
        # Compute size adjustment factor
        size_factor = self.size_adjuster.adjustment_factor(portfolio_size_m, lob_weights)
        
        # Sample scenarios
        scenarios = []
        attempts = 0
        max_attempts = n_scenarios * 3
        
        while len(scenarios) < n_scenarios and attempts < max_attempts:
            attempts += 1
            
            # Sample a year
            year = np.random.choice(years)
            
            # Construct scenario for this year
            components = self.matcher.construct_scenario_for_year(year, lob_weights)
            
            if not components:
                continue
            
            # Check coverage
            covered_weight = sum(
                lob_weights.get(lob, 0)
                for lob in components
            )
            
            if covered_weight < min_coverage:
                continue
            
            # Compute portfolio severity
            portfolio_severity_raw = sum(
                lob_weights.get(lob, 0) * comp.severity
                for lob, comp in components.items()
            )
            
            # Apply size adjustment
            portfolio_severity_adjusted = portfolio_severity_raw * size_factor
            
            # Assess quality
            correlation_quality = self.matcher.assess_correlation_quality(components)
            syndicates_used = {c.source_syndicate for c in components.values()}
            primary = None
            primary_count = 0
            for synd in syndicates_used:
                count = sum(1 for c in components.values() if c.source_syndicate == synd)
                if count > primary_count:
                    primary_count = count
                    primary = synd
            
            # Synthesize narrative
            if synthesize_narrative:
                narrative = self.narrative_synth.synthesize(components, lob_weights)
            else:
                narrative = ""
            
            # Create scenario
            scenario = ConstructedScenario(
                year=year,
                components=components,
                portfolio_severity_raw=portfolio_severity_raw,
                portfolio_severity_adjusted=portfolio_severity_adjusted,
                correlation_quality=correlation_quality,
                coverage_fraction=covered_weight,
                primary_syndicate=primary,
                n_syndicates_used=len(syndicates_used),
                combined_narrative=narrative,
                query_size_m=portfolio_size_m,
                reference_size_m=self.size_adjuster.reference_size_m,
                size_adjustment_factor=size_factor
            )
            
            scenarios.append(scenario)
        
        logger.info(f"Constructed {len(scenarios)} scenarios from {attempts} attempts")
        
        return scenarios
    
    def query_summary(self,
                      lob_weights: Dict[str, float],
                      portfolio_size_m: float,
                      n_scenarios: int = 1000,
                      percentiles: List[float] = None) -> Dict[str, Any]:
        """
        Query and summarize severity distribution.
        
        Returns summary statistics and percentiles.
        """
        if percentiles is None:
            percentiles = [50, 75, 90, 95, 99, 99.5]
        
        scenarios = self.query(
            lob_weights=lob_weights,
            portfolio_size_m=portfolio_size_m,
            n_scenarios=n_scenarios,
            synthesize_narrative=False
        )
        
        if not scenarios:
            return {'error': 'No scenarios generated'}
        
        severities_raw = [s.portfolio_severity_raw for s in scenarios]
        severities_adj = [s.portfolio_severity_adjusted for s in scenarios]
        
        # Coverage analysis
        coverages = [s.coverage_fraction for s in scenarios]
        quality_counts = defaultdict(int)
        for s in scenarios:
            quality_counts[s.correlation_quality] += 1
        
        # Years used
        years_used = defaultdict(int)
        for s in scenarios:
            years_used[s.year] += 1
        
        return {
            'n_scenarios': len(scenarios),
            'portfolio': {
                'lob_weights': lob_weights,
                'size_m': portfolio_size_m
            },
            'severity_raw': {
                'mean': float(np.mean(severities_raw)),
                'std': float(np.std(severities_raw)),
                'percentiles': {
                    p: float(np.percentile(severities_raw, p))
                    for p in percentiles
                }
            },
            'severity_adjusted': {
                'mean': float(np.mean(severities_adj)),
                'std': float(np.std(severities_adj)),
                'percentiles': {
                    p: float(np.percentile(severities_adj, p))
                    for p in percentiles
                }
            },
            'size_adjustment_factor': scenarios[0].size_adjustment_factor if scenarios else 1.0,
            'coverage': {
                'mean': float(np.mean(coverages)),
                'min': float(np.min(coverages)),
            },
            'correlation_quality': dict(quality_counts),
            'years_sampled': dict(years_used)
        }
    
    def coverage_report(self, lob_weights: Dict[str, float]) -> Dict[str, Any]:
        """
        Report on data coverage for a query portfolio.
        
        Identifies gaps and limitations.
        """
        if not self._is_loaded:
            raise RuntimeError("Corpus not loaded. Call load_corpus() first.")
        
        required_lobs = {lob for lob, w in lob_weights.items() if w > 0}
        
        # Check coverage by LOB
        lob_coverage = {}
        for lob in required_lobs:
            years_with_lob = self.corpus.get_years_with_lob(lob)
            lob_coverage[lob] = {
                'weight_in_query': lob_weights[lob],
                'years_available': len(years_with_lob),
                'observations': self.corpus.coverage_stats['lob_counts'].get(lob, 0),
                'covered': len(years_with_lob) > 0
            }
        
        # Identify gaps
        uncovered_lobs = [lob for lob, cov in lob_coverage.items() if not cov['covered']]
        uncovered_weight = sum(lob_weights.get(lob, 0) for lob in uncovered_lobs)
        
        # Check year coverage
        years_with_full_coverage = []
        years_with_partial_coverage = []
        
        for year in self.corpus.years_available:
            syndicates = self.corpus.get_syndicates_for_year(year)
            year_lobs = set()
            for synd in syndicates:
                year_lobs.update(synd.lob_observations.keys())
            
            covered_in_year = required_lobs.intersection(year_lobs)
            if covered_in_year == required_lobs:
                years_with_full_coverage.append(year)
            elif covered_in_year:
                years_with_partial_coverage.append(year)
        
        return {
            'query_lobs': list(required_lobs),
            'lob_coverage': lob_coverage,
            'uncovered_lobs': uncovered_lobs,
            'uncovered_weight': uncovered_weight,
            'years_with_full_coverage': sorted(years_with_full_coverage),
            'years_with_partial_coverage': sorted(years_with_partial_coverage),
            'total_years_available': len(self.corpus.years_available),
            'recommendation': self._coverage_recommendation(uncovered_weight, len(years_with_full_coverage))
        }
    
    def _coverage_recommendation(self, uncovered_weight: float, full_coverage_years: int) -> str:
        """Generate a recommendation based on coverage."""
        if uncovered_weight > 0.2:
            return f"WARNING: {uncovered_weight:.0%} of portfolio has no historical coverage. Results will be incomplete."
        elif uncovered_weight > 0:
            return f"CAUTION: {uncovered_weight:.0%} of portfolio has no historical coverage."
        elif full_coverage_years < 5:
            return f"LIMITED: Only {full_coverage_years} years have full LOB coverage. Consider results preliminary."
        else:
            return "GOOD: Portfolio has adequate historical coverage."

    # =========================================================================
    # UPGRADE A: Even-Year Sampling
    # =========================================================================

    def query_summary_even_years(
            self,
            lob_weights: Dict[str, float],
            portfolio_size_m: float,
            n_per_year: int = 200,
            percentiles: Tuple[float, ...] = (0.5, 0.75, 0.9, 0.95, 0.99, 0.995),
            min_coverage: float = 0.3,
            seed: Optional[int] = None,
            year_set: Optional[List[int]] = None,
            feasibility_mode: str = "feasible_years",
            min_success_per_year: int = 1,
            sampling_config: Optional[SamplingConfig] = None
    ) -> QuerySummary:
        """
        Query scenarios with even year weighting.

        Each year contributes equal total weight to the final severity distribution,
        eliminating bias from years with better LOB disclosure or easier gap fill.

        Args:
            lob_weights: Portfolio LOB weights (will be normalized to sum to 1)
            portfolio_size_m: Portfolio size in £m
            n_per_year: Number of draws generated for each year included
            percentiles: Percentiles to compute (0-1 scale, e.g., 0.99 for 99th)
            min_coverage: Minimum fraction of portfolio that must be covered
            seed: Random seed for reproducibility
            year_set: Optional explicit year list (for bootstrap replicates)
            feasibility_mode: How to define year set ("feasible_years" or "all_years")
            min_success_per_year: Minimum valid draws per year to include
            sampling_config: Configuration for stochastic selection

        Returns:
            QuerySummary with even-year weighted statistics
        """
        if not self._is_loaded:
            raise RuntimeError("Corpus not loaded. Call load_corpus() first.")

        # Initialize RNG
        rng = np.random.default_rng(seed)

        # Normalize weights
        total_weight = sum(lob_weights.values())
        if total_weight > 0:
            lob_weights = {k: v / total_weight for k, v in lob_weights.items()}

        # Configure sampling
        cfg = sampling_config or SamplingConfig()
        self.matcher.sampling_config = cfg

        # Determine year set
        if year_set is not None:
            # Use provided year set (for bootstrap)
            years = [y for y in year_set if y in self.corpus.years_available]
            excluded_years = {
                y: "not in corpus"
                for y in year_set if y not in self.corpus.years_available
            }
        elif feasibility_mode == "feasible_years":
            years, excluded_years = self.corpus.get_feasible_years(lob_weights, min_coverage)
        else:  # all_years
            years = list(self.corpus.years_available)
            excluded_years = {}

        if not years:
            logger.warning("No feasible years available for query")
            return self._empty_query_summary(lob_weights, portfolio_size_m, cfg, seed)

        # Compute size adjustment factor
        size_factor = self.size_adjuster.adjustment_factor(portfolio_size_m, lob_weights)

        # =====================================================================
        # Generate draws for each year
        # =====================================================================
        all_draws = []  # List of (severity_raw, severity_adj, year, coverage)
        per_year_stats: Dict[int, PerYearStats] = {}
        years_included = []

        for year in years:
            year_draws = []
            primary_counts: Dict[str, int] = defaultdict(int)
            supplementary_counts: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))

            for _ in range(n_per_year):
                components, primary_id, supp_selections = self.matcher.construct_scenario_for_year_stochastic(
                    year, lob_weights, rng, portfolio_size_m
                )

                if components is None:
                    continue

                # Check coverage
                covered_weight = sum(lob_weights.get(lob, 0) for lob in components)
                if covered_weight < min_coverage:
                    continue

                # Compute portfolio severity
                portfolio_severity_raw = sum(
                    lob_weights.get(lob, 0) * comp.severity
                    for lob, comp in components.items()
                )
                portfolio_severity_adj = portfolio_severity_raw * size_factor

                year_draws.append((portfolio_severity_raw, portfolio_severity_adj, covered_weight))

                # Track selection counts
                if primary_id:
                    primary_counts[primary_id] += 1
                for lob, synd_id in supp_selections.items():
                    supplementary_counts[lob][synd_id] += 1

            # Check minimum success threshold
            if len(year_draws) < min_success_per_year:
                excluded_years[year] = f"insufficient_valid_draws ({len(year_draws)} < {min_success_per_year})"
                continue

            years_included.append(year)

            # Store per-year statistics
            per_year_stats[year] = PerYearStats(
                year=year,
                attempted=n_per_year,
                valid=len(year_draws),
                valid_rate=len(year_draws) / n_per_year,
                primary_selection_counts=dict(primary_counts),
                supplementation_counts={k: dict(v) for k, v in supplementary_counts.items()}
            )

            # Add draws with year tag
            for sev_raw, sev_adj, cov in year_draws:
                all_draws.append((sev_raw, sev_adj, year, cov))

        if not all_draws:
            logger.warning("No valid draws generated across all years")
            return self._empty_query_summary(lob_weights, portfolio_size_m, cfg, seed)

        # =====================================================================
        # Compute weighted quantiles with equal year weight
        # =====================================================================
        K = len(years_included)
        year_valid_counts = {y: per_year_stats[y].valid for y in years_included}

        # Compute weights: each draw weight = 1 / (K * m_y)
        weights = []
        severities_raw = []
        severities_adj = []
        coverages = []

        for sev_raw, sev_adj, year, cov in all_draws:
            m_y = year_valid_counts[year]
            weight = 1.0 / (K * m_y)
            weights.append(weight)
            severities_raw.append(sev_raw)
            severities_adj.append(sev_adj)
            coverages.append(cov)

        weights = np.array(weights)
        severities_raw = np.array(severities_raw)
        severities_adj = np.array(severities_adj)

        # Compute weighted quantiles
        raw_quantiles = weighted_quantile(severities_raw, weights, list(percentiles))
        adj_quantiles = weighted_quantile(severities_adj, weights, list(percentiles))

        # Compute weighted statistics
        weighted_mean_raw = float(np.sum(weights * severities_raw))
        weighted_mean_adj = float(np.sum(weights * severities_adj))

        # Weighted variance
        weighted_var_raw = float(np.sum(weights * (severities_raw - weighted_mean_raw)**2))
        weighted_var_adj = float(np.sum(weights * (severities_adj - weighted_mean_adj)**2))

        # Quality counts
        quality_counts: Dict[str, int] = defaultdict(int)
        # For even-year sampling we don't track per-draw quality directly,
        # but we can compute from year stats
        for year in years_included:
            # Approximate: count primary-only vs supplemented
            stats = per_year_stats[year]
            # This is a simplification - real quality would need per-draw tracking
            quality_counts['medium'] += stats.valid  # Same year = medium

        return QuerySummary(
            n_scenarios=len(all_draws),
            portfolio={'lob_weights': lob_weights, 'size_m': portfolio_size_m},
            severity_raw={
                'mean': weighted_mean_raw,
                'std': float(np.sqrt(weighted_var_raw)),
                'percentiles': {p: raw_quantiles[p] for p in percentiles}
            },
            severity_adjusted={
                'mean': weighted_mean_adj,
                'std': float(np.sqrt(weighted_var_adj)),
                'percentiles': {p: adj_quantiles[p] for p in percentiles}
            },
            size_adjustment_factor=size_factor,
            coverage={
                'mean': float(np.mean(coverages)),
                'min': float(np.min(coverages))
            },
            correlation_quality=dict(quality_counts),
            years_included=sorted(years_included),
            years_excluded=excluded_years,
            per_year_stats=per_year_stats,
            weights_description="equal total weight per year: each draw weight = 1/(K * m_y)",
            sampling_config=cfg.to_dict(),
            seed=seed
        )

    def _empty_query_summary(self, lob_weights: Dict[str, float],
                             portfolio_size_m: float,
                             cfg: SamplingConfig,
                             seed: Optional[int]) -> QuerySummary:
        """Return an empty QuerySummary when no data is available."""
        return QuerySummary(
            n_scenarios=0,
            portfolio={'lob_weights': lob_weights, 'size_m': portfolio_size_m},
            severity_raw={'mean': np.nan, 'std': np.nan, 'percentiles': {}},
            severity_adjusted={'mean': np.nan, 'std': np.nan, 'percentiles': {}},
            size_adjustment_factor=1.0,
            coverage={'mean': np.nan, 'min': np.nan},
            correlation_quality={},
            years_included=[],
            years_excluded={},
            per_year_stats={},
            weights_description="no data",
            sampling_config=cfg.to_dict(),
            seed=seed
        )

    # =========================================================================
    # UPGRADE C: Year-Block Bootstrap
    # =========================================================================

    def query_summary_year_block_bootstrap(
            self,
            lob_weights: Dict[str, float],
            portfolio_size_m: float,
            percentiles: Tuple[float, ...] = (0.5, 0.75, 0.9, 0.95, 0.99, 0.995),
            B: int = 500,
            n_per_year: int = 200,
            min_coverage: float = 0.3,
            seed: Optional[int] = None,
            feasibility_mode: str = "feasible_years",
            min_success_per_year: int = 1,
            sampling_config: Optional[SamplingConfig] = None
    ) -> BootstrapSummary:
        """
        Compute return levels with year-block bootstrap uncertainty estimation.

        Quantifies uncertainty in return-level estimates due to having only a
        limited set of distinct calendar years, without assuming syndicate-years
        are independent time draws.

        Args:
            lob_weights: Portfolio LOB weights (will be normalized to sum to 1)
            portfolio_size_m: Portfolio size in £m
            percentiles: Percentiles to compute (0-1 scale)
            B: Number of bootstrap replicates
            n_per_year: Number of draws per year per replicate
            min_coverage: Minimum coverage fraction
            seed: Random seed for reproducibility
            feasibility_mode: How to define year set
            min_success_per_year: Minimum valid draws per year
            sampling_config: Configuration for stochastic selection

        Returns:
            BootstrapSummary with point estimates and confidence intervals
        """
        if not self._is_loaded:
            raise RuntimeError("Corpus not loaded. Call load_corpus() first.")

        # Initialize RNG
        rng = np.random.default_rng(seed)

        # Normalize weights
        total_weight = sum(lob_weights.values())
        if total_weight > 0:
            lob_weights = {k: v / total_weight for k, v in lob_weights.items()}

        # Configure sampling
        cfg = sampling_config or SamplingConfig()

        # Get feasible years
        if feasibility_mode == "feasible_years":
            feasible_years, excluded_years = self.corpus.get_feasible_years(lob_weights, min_coverage)
        else:
            feasible_years = list(self.corpus.years_available)
            excluded_years = {}

        if not feasible_years:
            logger.warning("No feasible years available for bootstrap")
            return self._empty_bootstrap_summary(percentiles, cfg, seed)

        K = len(feasible_years)
        logger.info(f"Bootstrap: {K} feasible years, {B} replicates, {n_per_year} draws/year")

        # =====================================================================
        # Point estimate from full data
        # =====================================================================
        point_result = self.query_summary_even_years(
            lob_weights=lob_weights,
            portfolio_size_m=portfolio_size_m,
            n_per_year=n_per_year,
            percentiles=percentiles,
            min_coverage=min_coverage,
            seed=rng.integers(0, 2**31),
            year_set=feasible_years,
            feasibility_mode="all_years",  # We already filtered
            min_success_per_year=min_success_per_year,
            sampling_config=cfg
        )

        point_estimate = {p: point_result.severity_adjusted['percentiles'].get(p, np.nan)
                         for p in percentiles}

        # =====================================================================
        # Bootstrap replicates
        # =====================================================================
        bootstrap_quantiles: List[Dict[float, float]] = []

        for b in range(B):
            # Sample K years with replacement
            sampled_years = list(rng.choice(feasible_years, size=K, replace=True))

            # Generate draws for this replicate
            replicate_result = self.query_summary_even_years(
                lob_weights=lob_weights,
                portfolio_size_m=portfolio_size_m,
                n_per_year=n_per_year,
                percentiles=percentiles,
                min_coverage=min_coverage,
                seed=rng.integers(0, 2**31),
                year_set=sampled_years,
                feasibility_mode="all_years",
                min_success_per_year=1,  # More lenient for bootstrap
                sampling_config=cfg
            )

            replicate_quantiles = {
                p: replicate_result.severity_adjusted['percentiles'].get(p, np.nan)
                for p in percentiles
            }
            bootstrap_quantiles.append(replicate_quantiles)

            if (b + 1) % 100 == 0:
                logger.info(f"Bootstrap progress: {b + 1}/{B} replicates")

        # =====================================================================
        # Compute confidence intervals
        # =====================================================================
        confidence_intervals: Dict[float, Dict[str, Any]] = {}

        for p in percentiles:
            boot_values = np.array([bq[p] for bq in bootstrap_quantiles])
            # Remove NaNs
            boot_values = boot_values[~np.isnan(boot_values)]

            if len(boot_values) == 0:
                confidence_intervals[p] = {
                    'ci_90': [np.nan, np.nan],
                    'ci_95': [np.nan, np.nan],
                    'std_err': np.nan,
                    'bias': np.nan
                }
                continue

            # Confidence intervals
            ci_90 = [float(np.percentile(boot_values, 5)), float(np.percentile(boot_values, 95))]
            ci_95 = [float(np.percentile(boot_values, 2.5)), float(np.percentile(boot_values, 97.5))]

            # Standard error
            std_err = float(np.std(boot_values))

            # Bias
            point_val = point_estimate[p]
            bias = float(np.mean(boot_values) - point_val) if not np.isnan(point_val) else np.nan

            confidence_intervals[p] = {
                'ci_90': ci_90,
                'ci_95': ci_95,
                'std_err': std_err,
                'bias': bias
            }

        return BootstrapSummary(
            point_estimate=point_estimate,
            bootstrap_quantiles=bootstrap_quantiles,
            confidence_intervals=confidence_intervals,
            n_replicates=B,
            n_per_year=n_per_year,
            feasible_years=sorted(feasible_years),
            excluded_years=excluded_years,
            seed=seed,
            sampling_config=cfg.to_dict()
        )

    def _empty_bootstrap_summary(self, percentiles: Tuple[float, ...],
                                  cfg: SamplingConfig,
                                  seed: Optional[int]) -> BootstrapSummary:
        """Return an empty BootstrapSummary when no data is available."""
        return BootstrapSummary(
            point_estimate={p: np.nan for p in percentiles},
            bootstrap_quantiles=[],
            confidence_intervals={p: {'ci_90': [np.nan, np.nan], 'ci_95': [np.nan, np.nan],
                                       'std_err': np.nan, 'bias': np.nan}
                                  for p in percentiles},
            n_replicates=0,
            n_per_year=0,
            feasible_years=[],
            excluded_years={},
            seed=seed,
            sampling_config=cfg.to_dict()
        )


# =============================================================================
# CLI
# =============================================================================

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Query stress scenarios for a portfolio")
    
    subparsers = parser.add_subparsers(dest='command', help='Commands')
    
    # Query command
    query_parser = subparsers.add_parser('query', help='Query scenarios')
    query_parser.add_argument('--corpus', '-c', required=True, help='Path to enhanced_corpus.json')
    query_parser.add_argument('--lobs', '-l', required=True, help='LOB weights as JSON, e.g., \'{"Property": 0.6, "Marine": 0.4}\'')
    query_parser.add_argument('--size', '-s', type=float, required=True, help='Portfolio size in £m')
    query_parser.add_argument('--n', type=int, default=100, help='Number of scenarios')
    query_parser.add_argument('--output', '-o', help='Output JSON file')
    
    # Summary command
    summary_parser = subparsers.add_parser('summary', help='Query and summarize')
    summary_parser.add_argument('--corpus', '-c', required=True, help='Path to enhanced_corpus.json')
    summary_parser.add_argument('--lobs', '-l', required=True, help='LOB weights as JSON')
    summary_parser.add_argument('--size', '-s', type=float, required=True, help='Portfolio size in £m')
    summary_parser.add_argument('--n', type=int, default=1000, help='Number of scenarios')
    
    # Coverage command
    coverage_parser = subparsers.add_parser('coverage', help='Check data coverage')
    coverage_parser.add_argument('--corpus', '-c', required=True, help='Path to enhanced_corpus.json')
    coverage_parser.add_argument('--lobs', '-l', required=True, help='LOB weights as JSON')

    # Even-years command (Upgrade A)
    even_parser = subparsers.add_parser('even-years', help='Query with even year weighting')
    even_parser.add_argument('--corpus', '-c', required=True, help='Path to enhanced_corpus.json')
    even_parser.add_argument('--lobs', '-l', required=True, help='LOB weights as JSON')
    even_parser.add_argument('--size', '-s', type=float, required=True, help='Portfolio size in £m')
    even_parser.add_argument('--n-per-year', type=int, default=200, help='Draws per year')
    even_parser.add_argument('--seed', type=int, default=None, help='Random seed')
    even_parser.add_argument('--min-coverage', type=float, default=0.3, help='Minimum coverage')
    even_parser.add_argument('--output', '-o', help='Output JSON file')

    # Bootstrap command (Upgrade C)
    boot_parser = subparsers.add_parser('bootstrap', help='Query with year-block bootstrap')
    boot_parser.add_argument('--corpus', '-c', required=True, help='Path to enhanced_corpus.json')
    boot_parser.add_argument('--lobs', '-l', required=True, help='LOB weights as JSON')
    boot_parser.add_argument('--size', '-s', type=float, required=True, help='Portfolio size in £m')
    boot_parser.add_argument('--n-per-year', type=int, default=200, help='Draws per year')
    boot_parser.add_argument('--B', type=int, default=500, help='Bootstrap replicates')
    boot_parser.add_argument('--seed', type=int, default=None, help='Random seed')
    boot_parser.add_argument('--output', '-o', help='Output JSON file')

    args = parser.parse_args()
    
    if args.command in ['query', 'summary', 'coverage', 'even-years', 'bootstrap']:
        # Parse LOB weights
        lob_weights = json.loads(args.lobs)

        # Load engine
        engine = PortfolioQueryEngine()
        engine.load_corpus(args.corpus)

        if args.command == 'query':
            scenarios = engine.query(
                lob_weights=lob_weights,
                portfolio_size_m=args.size,
                n_scenarios=args.n
            )

            print(f"\nGenerated {len(scenarios)} scenarios")
            print(f"\nSample scenario (year {scenarios[0].year}):")
            print(f"  Coverage: {scenarios[0].coverage_fraction:.0%}")
            print(f"  Quality: {scenarios[0].correlation_quality}")
            print(f"  Raw severity: {scenarios[0].portfolio_severity_raw:.2%}")
            print(f"  Adjusted severity: {scenarios[0].portfolio_severity_adjusted:.2%}")
            print(f"\n{scenarios[0].combined_narrative}")

            if args.output:
                output_data = {
                    'query': {'lob_weights': lob_weights, 'size_m': args.size},
                    'scenarios': [s.to_dict() for s in scenarios]
                }
                with open(args.output, 'w') as f:
                    json.dump(output_data, f, indent=2)
                print(f"\nSaved to {args.output}")

        elif args.command == 'summary':
            summary = engine.query_summary(
                lob_weights=lob_weights,
                portfolio_size_m=args.size,
                n_scenarios=args.n
            )

            print("\n" + "=" * 60)
            print("PORTFOLIO STRESS SCENARIO SUMMARY")
            print("=" * 60)
            print(f"\nPortfolio: {lob_weights}")
            print(f"Size: £{args.size}m")
            print(f"Scenarios: {summary['n_scenarios']}")
            print(f"\nSeverity Distribution (size-adjusted):")
            for p, v in summary['severity_adjusted']['percentiles'].items():
                print(f"  {p}th percentile: {v:.2%}")
            print(f"\nSize adjustment factor: {summary['size_adjustment_factor']:.3f}")
            print(f"Mean coverage: {summary['coverage']['mean']:.0%}")
            print(f"Correlation quality: {summary['correlation_quality']}")
            print("=" * 60)

        elif args.command == 'coverage':
            report = engine.coverage_report(lob_weights)

            print("\n" + "=" * 60)
            print("DATA COVERAGE REPORT")
            print("=" * 60)
            print(f"\nQuery LOBs: {report['query_lobs']}")
            print(f"\nLOB Coverage:")
            for lob, cov in report['lob_coverage'].items():
                status = "✓" if cov['covered'] else "✗"
                print(f"  {status} {lob}: {cov['observations']} observations across {cov['years_available']} years")

            if report['uncovered_lobs']:
                print(f"\nUNCOVERED: {report['uncovered_lobs']} ({report['uncovered_weight']:.0%} of portfolio)")

            print(f"\nYears with full coverage: {len(report['years_with_full_coverage'])}")
            print(f"Years with partial coverage: {len(report['years_with_partial_coverage'])}")
            print(f"\n{report['recommendation']}")
            print("=" * 60)

        elif args.command == 'even-years':
            # Even-year sampling (Upgrade A)
            n_per_year = getattr(args, 'n_per_year', 200)
            min_coverage = getattr(args, 'min_coverage', 0.3)

            summary = engine.query_summary_even_years(
                lob_weights=lob_weights,
                portfolio_size_m=args.size,
                n_per_year=n_per_year,
                min_coverage=min_coverage,
                seed=args.seed
            )

            print("\n" + "=" * 60)
            print("EVEN-YEAR WEIGHTED SUMMARY")
            print("=" * 60)
            print(f"\nPortfolio: {lob_weights}")
            print(f"Size: £{args.size}m")
            print(f"Total draws: {summary.n_scenarios}")
            print(f"Years included: {len(summary.years_included)} {summary.years_included}")
            if summary.years_excluded:
                print(f"Years excluded: {summary.years_excluded}")
            print(f"\nSeverity Distribution (size-adjusted, equal year weight):")
            for p, v in summary.severity_adjusted['percentiles'].items():
                print(f"  {p*100:.1f}th percentile: {v:.2%}")
            print(f"\nSize adjustment factor: {summary.size_adjustment_factor:.3f}")
            print(f"Mean coverage: {summary.coverage['mean']:.0%}")
            print(f"Weights: {summary.weights_description}")
            print(f"Seed: {summary.seed}")
            print("=" * 60)

            if args.output:
                with open(args.output, 'w') as f:
                    json.dump(summary.to_dict(), f, indent=2, default=str)
                print(f"\nSaved to {args.output}")

        elif args.command == 'bootstrap':
            # Year-block bootstrap (Upgrade C)
            n_per_year = getattr(args, 'n_per_year', 200)
            B = getattr(args, 'B', 500)

            print(f"\nRunning year-block bootstrap with B={B} replicates...")

            result = engine.query_summary_year_block_bootstrap(
                lob_weights=lob_weights,
                portfolio_size_m=args.size,
                n_per_year=n_per_year,
                B=B,
                seed=args.seed
            )

            print("\n" + "=" * 60)
            print("YEAR-BLOCK BOOTSTRAP RESULTS")
            print("=" * 60)
            print(f"\nPortfolio: {lob_weights}")
            print(f"Size: £{args.size}m")
            print(f"Feasible years: {len(result.feasible_years)} {result.feasible_years}")
            print(f"Bootstrap replicates: {result.n_replicates}")
            print(f"Draws per year: {result.n_per_year}")

            print(f"\nReturn Levels with 95% Confidence Intervals:")
            print("-" * 50)
            for p in sorted(result.point_estimate.keys()):
                point = result.point_estimate[p]
                ci = result.confidence_intervals[p]
                ci_95 = ci['ci_95']
                std_err = ci['std_err']
                print(f"  {p*100:.1f}th percentile: {point:.2%}")
                print(f"    95% CI: [{ci_95[0]:.2%}, {ci_95[1]:.2%}]")
                print(f"    Std Error: {std_err:.4f}")

            print("=" * 60)

            if args.output:
                with open(args.output, 'w') as f:
                    json.dump(result.to_dict(), f, indent=2, default=str)
                print(f"\nSaved to {args.output}")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()