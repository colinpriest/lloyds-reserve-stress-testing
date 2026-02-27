"""
GPD-Based Spliced Distribution Sampling

CORRECT APPROACH:
- GPD models ONLY exceedances above a threshold
- Below threshold: use empirical distribution from historical data
- Above threshold: use GPD

This is a "spliced" or "composite" distribution:
  F(x) = F_empirical(x)           for x < threshold
  F(x) = F(u) + (1-F(u)) * G(x-u) for x >= threshold

Where:
  u = threshold
  F(u) = proportion of data below threshold
  G = GPD cumulative distribution function

For sampling:
  1. Draw u ~ Uniform(0, 1)
  2. If u < F(threshold): sample from empirical distribution below threshold
  3. If u >= F(threshold): sample severity = threshold + GPD.rvs()

For percentiles:
  - Percentiles < threshold_percentile: use empirical below threshold
  - Percentiles >= threshold_percentile: use GPD tail formula
"""

import sys
from pathlib import Path
_script_dir = Path(__file__).resolve().parent
if str(_script_dir) not in sys.path:
    sys.path.insert(0, str(_script_dir))

import json
import logging
import numpy as np
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass, field
from collections import Counter
from scipy import stats

from config import SyntheticScenario, HistoricalMovement
from gpd_fitting import fit_gpd_improved, GPDFitResult

logger = logging.getLogger(__name__)


# =============================================================================
# Spliced Distribution
# =============================================================================

@dataclass
class SplicedDistribution:
    """
    A spliced distribution combining empirical (body) and GPD (tail).
    
    Structure:
      - Below threshold: empirical CDF from historical data
      - Above threshold: GPD tail
    """
    # GPD parameters for tail
    threshold: float
    threshold_percentile: float  # e.g., 70 means 70th percentile
    shape: float  # ξ
    scale: float  # σ
    
    # Empirical distribution for body (sorted values below threshold)
    body_values: np.ndarray = field(default_factory=lambda: np.array([]))
    
    # Original data for reference
    n_total: int = 0
    n_exceedances: int = 0
    
    @classmethod
    def from_gpd_fit(cls, gpd_fit: GPDFitResult, 
                     historical_data: np.ndarray) -> 'SplicedDistribution':
        """Create spliced distribution from GPD fit and historical data."""
        # Get values below threshold for empirical body
        body_mask = historical_data <= gpd_fit.threshold
        body_values = np.sort(historical_data[body_mask])
        
        return cls(
            threshold=gpd_fit.threshold,
            threshold_percentile=gpd_fit.threshold_percentile,
            shape=gpd_fit.shape,
            scale=gpd_fit.scale,
            body_values=body_values,
            n_total=len(historical_data),
            n_exceedances=gpd_fit.n_exceedances
        )
    
    @property
    def p_below_threshold(self) -> float:
        """Probability of being below threshold."""
        return len(self.body_values) / self.n_total
    
    def percentile(self, p: float) -> float:
        """
        Compute the p-th percentile of the spliced distribution.
        
        Args:
            p: Percentile (0-100)
        
        Returns:
            Value at that percentile
        """
        # Convert to probability
        prob = p / 100.0
        
        # Threshold probability
        p_threshold = self.threshold_percentile / 100.0
        
        if prob <= p_threshold:
            # Below threshold: use empirical distribution
            if len(self.body_values) == 0:
                return 0.0
            
            # Find the appropriate quantile in body values
            # prob goes from 0 to p_threshold, we need to map to 0-1 within body
            body_quantile = prob / p_threshold
            idx = int(body_quantile * (len(self.body_values) - 1))
            idx = min(idx, len(self.body_values) - 1)
            return float(self.body_values[idx])
        else:
            # Above threshold: use GPD
            # Map prob to position in tail: (prob - p_threshold) / (1 - p_threshold)
            p_in_tail = (prob - p_threshold) / (1 - p_threshold)
            
            # GPD inverse CDF (quantile function)
            # For GPD: Q(p) = σ/ξ * ((1-p)^(-ξ) - 1) for ξ ≠ 0
            #          Q(p) = -σ * log(1-p) for ξ = 0
            if abs(self.shape) < 1e-6:
                # Exponential case
                exceedance = -self.scale * np.log(1 - p_in_tail)
            else:
                exceedance = (self.scale / self.shape) * ((1 - p_in_tail)**(-self.shape) - 1)
            
            return self.threshold + exceedance
    
    def sample(self, n: int) -> np.ndarray:
        """
        Sample n values from the spliced distribution.
        
        Process:
        1. Draw u ~ Uniform(0, 1) for each sample
        2. If u < p_threshold: sample from body (empirical)
        3. If u >= p_threshold: sample from tail (GPD)
        """
        samples = np.zeros(n)
        u = np.random.uniform(0, 1, n)
        
        # Probability of being in body
        p_body = self.p_below_threshold
        
        # Body samples (below threshold)
        body_mask = u < p_body
        n_body = np.sum(body_mask)
        if n_body > 0 and len(self.body_values) > 0:
            # Sample with replacement from empirical distribution
            body_indices = np.random.randint(0, len(self.body_values), n_body)
            samples[body_mask] = self.body_values[body_indices]
        
        # Tail samples (above threshold)
        tail_mask = ~body_mask
        n_tail = np.sum(tail_mask)
        if n_tail > 0:
            # Sample from GPD
            exceedances = stats.genpareto.rvs(
                self.shape,
                loc=0,
                scale=self.scale,
                size=n_tail
            )
            samples[tail_mask] = self.threshold + exceedances
        
        return samples
    
    def severity_for_return_period(self, return_period: int) -> float:
        """
        Compute severity for a given return period.
        
        Return period T means: P(X > severity) = 1/T
        So severity is at percentile = 100 * (1 - 1/T)
        
        For T=100: percentile = 99th
        For T=10: percentile = 90th
        """
        # Convert return period to percentile
        p_exceed = 1.0 / return_period
        percentile = 100.0 * (1.0 - p_exceed)
        
        return self.percentile(percentile)


# =============================================================================
# Matching GPD Samples to LLM Scenarios
# =============================================================================

def match_samples_to_scenarios(
    target_severities: np.ndarray,
    scenarios: List[SyntheticScenario],
    max_severity_gap: float = 0.10
) -> Tuple[List[SyntheticScenario], Dict]:
    """
    Match each target severity to the nearest LLM scenario by severity.
    
    For each target severity:
    - Find the LLM scenario with closest severity
    - Use that scenario (narrative, cause, LOBs all come from LLM)
    
    Note: Same LLM scenario may be selected multiple times if it's the
    nearest match for multiple targets. This is intentional.
    """
    scenario_severities = np.array([s.severity_ratio for s in scenarios])
    
    matched = []
    gaps = []
    scenario_usage = Counter()
    
    for target in target_severities:
        # Find nearest scenario
        distances = np.abs(scenario_severities - target)
        best_idx = np.argmin(distances)
        gap = distances[best_idx]
        
        matched.append(scenarios[best_idx])
        gaps.append(gap)
        scenario_usage[scenarios[best_idx].id] += 1
    
    # Compile stats
    gaps = np.array(gaps)
    large_gap_count = np.sum(gaps > max_severity_gap)
    
    match_stats = {
        'n_unique_scenarios_used': len(scenario_usage),
        'n_large_gaps': int(large_gap_count),
        'pct_large_gaps': 100 * large_gap_count / len(target_severities),
        'mean_gap': float(np.mean(gaps)),
        'median_gap': float(np.median(gaps)),
        'max_gap': float(np.max(gaps)),
        'p90_gap': float(np.percentile(gaps, 90)),
        'p99_gap': float(np.percentile(gaps, 99)),
        'target_range': (float(target_severities.min()), float(target_severities.max())),
        'llm_range': (float(scenario_severities.min()), float(scenario_severities.max())),
        'most_used_scenarios': scenario_usage.most_common(10)
    }
    
    if match_stats['max_gap'] > 0.20:
        logger.warning(f"Max severity gap is {match_stats['max_gap']:.1%} - "
                      "LLM may need more scenarios at that severity level")
    
    return matched, match_stats


# =============================================================================
# Main Sampling Function
# =============================================================================

def create_gpd_sampled_library(
    scenarios: List[SyntheticScenario],
    historical_severities: np.ndarray,
    target_size: int = 2000,
    output_dir: Optional[Path] = None,
    percentile_range: Tuple[float, float] = (80, 99),
    severity_mode: str = "auto"
) -> Tuple[List[SyntheticScenario], SplicedDistribution, Dict]:
    """
    Create scenario library with severity distribution matching a spliced
    empirical + GPD distribution.
    
    Process:
    1. Fit GPD to historical severities (tail only, above threshold)
    2. Create spliced distribution (empirical body + GPD tail)
    3. Sample N severities from spliced distribution
    4. For each sampled severity, find nearest LLM scenario
    
    The final library will have a realistic severity distribution:
    - Body matches empirical (small deteriorations are realistic)
    - Tail follows GPD (extreme events extrapolated properly)
    
    Args:
        scenarios: Pool of LLM-generated scenarios
        historical_severities: Historical severity data for fitting
        target_size: Number of scenarios in final library
        output_dir: Directory to save GPD diagnostics (optional)
        percentile_range: Range of percentiles to search for threshold (default: 80-99)
        severity_mode: Which severity distribution to use:
            - 'auto': Use recommended mode from diagnostics
            - 'constrained': GPD with shape capped at 0.5
            - 'unconstrained': GPD with no shape constraint
            - 'unconstrained_no_max': GPD fitted without the maximum value
            - 'empirical': Use empirical distribution only (no extrapolation)
    
    Returns:
        (sampled_library, spliced_distribution, stats)
    """
    logger.info("="*60)
    logger.info("SPLICED DISTRIBUTION SAMPLING")
    logger.info("(Empirical body + GPD tail)")
    logger.info("="*60)
    
    # Check LLM scenario coverage
    llm_severities = np.array([s.severity_ratio for s in scenarios])
    logger.info(f"\nLLM scenario pool: {len(scenarios)} scenarios")
    logger.info(f"  Severity range: {llm_severities.min():.1%} to {llm_severities.max():.1%}")
    logger.info(f"  Median: {np.median(llm_severities):.1%}")
    logger.info(f"  95th percentile: {np.percentile(llm_severities, 95):.1%}")
    
    hist_max = historical_severities.max()
    n_above_max = np.sum(llm_severities > hist_max)
    logger.info(f"  Historical max: {hist_max:.1%}")
    logger.info(f"  LLM scenarios above historical max: {n_above_max}")
    
    # Save comprehensive GPD diagnostics if output_dir provided
    gpd_diagnostics = None
    if output_dir:
        from gpd_diagnostics import save_gpd_diagnostics
        output_dir = Path(output_dir)
        logger.info("\n" + "-"*60)
        logger.info("STEP 0: Computing GPD diagnostics")
        logger.info(f"  Threshold search range: {percentile_range[0]:.0f}th to {percentile_range[1]:.0f}th percentile")
        logger.info("-"*60)
        gpd_diagnostics, diag_files = save_gpd_diagnostics(
            historical_severities,
            output_dir,
            prefix="gpd",
            percentile_range=percentile_range
        )
        logger.info(f"  Saved {len(diag_files)} diagnostic files to {output_dir}")
        
        # Use diagnostics-selected threshold
        selected_pct = gpd_diagnostics.selected_percentile
        logger.info(f"  Diagnostics selected threshold: {selected_pct:.0f}th percentile")
    else:
        selected_pct = None
    
    # Step 1: Fit GPD to tail of historical data
    logger.info("\n" + "-"*60)
    logger.info("STEP 1: Fitting GPD to historical tail")
    logger.info("-"*60)
    logger.info("Using multi-method consensus for threshold selection:")
    logger.info("  - Shape parameter stability")
    logger.info("  - Scale parameter stability")
    logger.info("  - Mean excess linearity")
    logger.info("  - Anderson-Darling goodness-of-fit")
    
    # Determine which severity mode to use
    actual_mode = severity_mode
    if gpd_diagnostics and severity_mode == 'auto':
        actual_mode = gpd_diagnostics.recommended_mode or 'constrained'
        logger.info(f"\n  Auto mode selected: {actual_mode} (recommended)")
    else:
        logger.info(f"\n  Severity mode: {actual_mode}")
    
    # Handle empirical mode separately (no GPD extrapolation)
    if actual_mode == 'empirical':
        logger.info("  Using empirical distribution only (no GPD extrapolation)")
        logger.info(f"  All samples will be capped at historical max: {historical_severities.max():.1%}")
        
        # For empirical mode, we still need a spliced distribution but with
        # effectively no tail extrapolation. We'll use constrained fit but
        # cap samples at historical max
        if gpd_diagnostics and gpd_diagnostics.constrained:
            fit_obj = gpd_diagnostics.constrained
            gpd_fit = GPDFitResult(
                threshold=fit_obj.threshold,
                threshold_percentile=fit_obj.threshold_percentile,
                shape=fit_obj.shape,
                scale=fit_obj.scale,
                n_exceedances=fit_obj.n_exceedances,
                n_total=gpd_diagnostics.n_total,
                ad_statistic=fit_obj.ad_statistic,
                ks_statistic=fit_obj.ks_statistic,
                ks_pvalue=fit_obj.ks_pvalue,
                method="empirical"
            )
        else:
            gpd_fit = fit_gpd_improved(
                historical_severities,
                method='automated',
                max_shape=0.5,
                min_exceedances=20,
                percentile_range=percentile_range
            )
        # We'll cap samples after creating spliced distribution
        empirical_cap = historical_severities.max()
    else:
        empirical_cap = None
        
        # Use diagnostics if available, selecting the right mode
        if gpd_diagnostics:
            # Get the appropriate fit based on mode
            if actual_mode == 'constrained' and gpd_diagnostics.constrained:
                fit_obj = gpd_diagnostics.constrained
            elif actual_mode == 'unconstrained' and gpd_diagnostics.unconstrained:
                fit_obj = gpd_diagnostics.unconstrained
            elif actual_mode == 'unconstrained_no_max' and gpd_diagnostics.unconstrained_no_max:
                fit_obj = gpd_diagnostics.unconstrained_no_max
            else:
                # Fallback to constrained
                fit_obj = gpd_diagnostics.constrained
                logger.warning(f"  Mode '{actual_mode}' not available, falling back to constrained")
            
            # Create GPDFitResult from the selected fit
            gpd_fit = GPDFitResult(
                threshold=fit_obj.threshold,
                threshold_percentile=fit_obj.threshold_percentile,
                shape=fit_obj.shape,
                scale=fit_obj.scale,
                n_exceedances=fit_obj.n_exceedances,
                n_total=gpd_diagnostics.n_total,
                ad_statistic=fit_obj.ad_statistic,
                ks_statistic=fit_obj.ks_statistic,
                ks_pvalue=fit_obj.ks_pvalue,
                method=actual_mode
            )
        else:
            # No diagnostics - fit directly
            max_shape = 0.5 if actual_mode == 'constrained' else None
            gpd_fit = fit_gpd_improved(
                historical_severities,
                method='automated',
                max_shape=max_shape,
                min_exceedances=20,
                percentile_range=percentile_range
            )
    
    logger.info(f"\nGPD FIT RESULTS ({actual_mode}):")
    logger.info(f"  Threshold: {gpd_fit.threshold:.1%} ({gpd_fit.threshold_percentile:.0f}th percentile)")
    logger.info(f"  Shape (xi): {gpd_fit.shape:.4f}")
    logger.info(f"  Scale (sigma): {gpd_fit.scale:.4f}")
    logger.info(f"  Exceedances: {gpd_fit.n_exceedances}/{gpd_fit.n_total}")
    if gpd_fit.ks_pvalue is not None:
        logger.info(f"  KS test p-value: {gpd_fit.ks_pvalue:.4f}")
    if gpd_fit.ad_statistic is not None:
        logger.info(f"  AD statistic: {gpd_fit.ad_statistic:.4f}")
    
    # Show comparison of all modes for verification
    if gpd_diagnostics:
        logger.info(f"\n  ALL MODES COMPARISON:")
        if gpd_diagnostics.constrained:
            c = gpd_diagnostics.constrained
            marker = " <-- SELECTED" if actual_mode == 'constrained' else ""
            logger.info(f"    Constrained:        xi={c.shape:.4f}, sigma={c.scale:.4f}{marker}")
        if gpd_diagnostics.unconstrained:
            u = gpd_diagnostics.unconstrained
            marker = " <-- SELECTED" if actual_mode == 'unconstrained' else ""
            logger.info(f"    Unconstrained:      xi={u.shape:.4f}, sigma={u.scale:.4f}{marker}")
        if gpd_diagnostics.unconstrained_no_max:
            unm = gpd_diagnostics.unconstrained_no_max
            marker = " <-- SELECTED" if actual_mode == 'unconstrained_no_max' else ""
            logger.info(f"    Unc. (no max):      xi={unm.shape:.4f}, sigma={unm.scale:.4f}{marker}")
        if actual_mode == 'empirical':
            logger.info(f"    Empirical:          capped at {historical_severities.max():.1%} <-- SELECTED")
    
    # Log warnings from diagnostics
    if gpd_diagnostics and gpd_diagnostics.warnings:
        logger.warning("\nWARNING:  GPD FIT WARNINGS:")
        for w in gpd_diagnostics.warnings:
            logger.warning(f"    {w}")
    
    # Step 2: Create spliced distribution
    logger.info("\n" + "-"*60)
    logger.info("STEP 2: Creating spliced distribution")
    logger.info("-"*60)
    
    spliced = SplicedDistribution.from_gpd_fit(gpd_fit, historical_severities)
    
    logger.info(f"  Body (empirical): {len(spliced.body_values)} values below threshold")
    logger.info(f"  Tail (GPD): {spliced.n_exceedances} exceedances")
    logger.info(f"  P(below threshold): {spliced.p_below_threshold:.1%}")
    
    # Show return period severities
    logger.info("\n  Return period → Severity:")
    for rp in [10, 25, 50, 100, 200]:
        sev = spliced.severity_for_return_period(rp)
        gap = abs(llm_severities - sev).min()
        status = "✓" if gap < 0.10 else f"✗ gap={gap:.1%}"
        logger.info(f"    {rp:3d}-year: {sev:>7.1%}  (nearest LLM: {status})")
    
    # Step 3: Sample from spliced distribution
    logger.info("\n" + "-"*60)
    logger.info(f"STEP 3: Sampling {target_size} severities from spliced distribution")
    logger.info("-"*60)
    
    sampled_severities = spliced.sample(target_size)
    
    # Apply empirical cap if using empirical mode
    if empirical_cap is not None:
        n_capped = np.sum(sampled_severities > empirical_cap)
        sampled_severities = np.minimum(sampled_severities, empirical_cap)
        logger.info(f"  Empirical mode: capped {n_capped} samples at historical max {empirical_cap:.1%}")
    
    n_below = np.sum(sampled_severities <= spliced.threshold)
    n_above = np.sum(sampled_severities > spliced.threshold)
    logger.info(f"  Below threshold (body): {n_below} ({100*n_below/target_size:.1f}%)")
    logger.info(f"  Above threshold (tail): {n_above} ({100*n_above/target_size:.1f}%)")
    logger.info(f"  Sample range: {sampled_severities.min():.1%} to {sampled_severities.max():.1%}")
    logger.info(f"  Sample 99th percentile: {np.percentile(sampled_severities, 99):.1%}")
    
    # Step 4: Match samples to LLM scenarios
    logger.info("\n" + "-"*60)
    logger.info("STEP 4: Matching samples to LLM scenarios")
    logger.info("-"*60)
    
    matched, match_stats = match_samples_to_scenarios(sampled_severities, scenarios)
    
    logger.info(f"  Unique LLM scenarios used: {match_stats['n_unique_scenarios_used']}")
    logger.info(f"  Mean severity gap: {match_stats['mean_gap']:.1%}")
    logger.info(f"  Max severity gap: {match_stats['max_gap']:.1%}")
    logger.info(f"  Large gaps (>10%): {match_stats['n_large_gaps']} ({match_stats['pct_large_gaps']:.1f}%)")
    
    if match_stats['pct_large_gaps'] > 10:
        logger.warning("More than 10% of matches have large gaps!")
        logger.warning("Consider increasing LLM extrapolation factor")
    
    # Compile stats
    all_stats = {
        'gpd': {
            'threshold': float(gpd_fit.threshold),
            'threshold_percentile': float(gpd_fit.threshold_percentile),
            'shape': float(gpd_fit.shape),
            'scale': float(gpd_fit.scale),
            'n_exceedances': gpd_fit.n_exceedances,
            'ks_pvalue': float(gpd_fit.ks_pvalue) if gpd_fit.ks_pvalue else None,
            'ad_statistic': float(gpd_fit.ad_statistic) if gpd_fit.ad_statistic else None,
            'severity_mode': actual_mode,
            'empirical_cap': float(empirical_cap) if empirical_cap else None
        },
        'spliced': {
            'n_body': len(spliced.body_values),
            'p_below_threshold': float(spliced.p_below_threshold),
            'n_sampled_below': int(n_below),
            'n_sampled_above': int(n_above)
        },
        'matching': match_stats,
        'input_scenarios': len(scenarios),
        'output_scenarios': len(matched)
    }
    
    return matched, spliced, all_stats


def analyze_severity_distribution(
    historical: np.ndarray,
    synthetic_raw: np.ndarray,
    synthetic_sampled: np.ndarray,
    spliced: SplicedDistribution
) -> Dict:
    """
    Compare severity distributions: historical, raw synthetic, spliced-sampled.
    
    Uses the spliced distribution for theoretical percentiles:
    - Below threshold: empirical
    - Above threshold: GPD
    """
    percentiles = [10, 25, 50, 75, 90, 95, 99]
    
    # Compute theoretical values from spliced distribution
    spliced_theoretical = [spliced.percentile(p) for p in percentiles]
    
    analysis = {
        'percentiles': percentiles,
        'historical': [float(np.percentile(historical, p)) for p in percentiles],
        'synthetic_raw': [float(np.percentile(synthetic_raw, p)) for p in percentiles],
        'synthetic_sampled': [float(np.percentile(synthetic_sampled, p)) for p in percentiles],
        'spliced_theoretical': spliced_theoretical,
        'threshold_percentile': spliced.threshold_percentile
    }
    
    logger.info("\n" + "="*70)
    logger.info("SEVERITY DISTRIBUTION COMPARISON")
    logger.info("="*70)
    logger.info(f"  GPD threshold at {spliced.threshold_percentile:.0f}th percentile ({spliced.threshold:.1%})")
    logger.info(f"  Below threshold: empirical distribution")
    logger.info(f"  Above threshold: GPD tail (xi={spliced.shape:.3f}, sigma={spliced.scale:.3f})")
    logger.info("")
    logger.info(f"{'Percentile':>12} {'Historical':>12} {'Raw Synth':>12} {'Sampled':>12} {'Theoretical':>12}")
    logger.info("-"*70)
    
    for i, p in enumerate(percentiles):
        marker = " " if p < spliced.threshold_percentile else "*"  # Mark tail percentiles
        logger.info(f"{p:>11}th{marker} {analysis['historical'][i]:>11.1%} "
                   f"{analysis['synthetic_raw'][i]:>11.1%} "
                   f"{analysis['synthetic_sampled'][i]:>11.1%} "
                   f"{analysis['spliced_theoretical'][i]:>11.1%}")
    
    logger.info("-"*70)
    logger.info("  * = percentile in GPD tail (above threshold)")
    
    # Check for large mismatches (could indicate wrong severity mode)
    hist_99 = analysis['historical'][-1]  # 99th percentile
    theo_99 = analysis['spliced_theoretical'][-1]
    if hist_99 > 0 and theo_99 > 0:
        ratio = hist_99 / theo_99
        if ratio > 3:
            logger.warning(f"\n  ⚠️  WARNING: Historical 99th ({hist_99:.1%}) is {ratio:.1f}x higher than theoretical ({theo_99:.1%})")
            logger.warning(f"      This may indicate the GPD shape is too low.")
            logger.warning(f"      Consider using 'unconstrained' or 'unconstrained_no_max' severity mode.")
    
    return analysis


# =============================================================================
# Backward Compatibility
# =============================================================================

# Re-export for backward compatibility with existing code
def severity_for_return_period(gpd_fit: GPDFitResult, return_period: int) -> float:
    """Backward compatible wrapper."""
    # Create a minimal spliced distribution
    spliced = SplicedDistribution(
        threshold=gpd_fit.threshold,
        threshold_percentile=gpd_fit.threshold_percentile,
        shape=gpd_fit.shape,
        scale=gpd_fit.scale,
        n_total=gpd_fit.n_total,
        n_exceedances=gpd_fit.n_exceedances
    )
    return spliced.severity_for_return_period(return_period)
