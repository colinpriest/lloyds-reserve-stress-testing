"""
Step 6: Importance-Sampled Severity Distribution

Reweights synthetic scenarios so the final library matches the GPD tail distribution.
Uses 5% severity bins for importance sampling.
"""

import sys
from pathlib import Path
_script_dir = Path(__file__).resolve().parent
if str(_script_dir) not in sys.path:
    sys.path.insert(0, str(_script_dir))

import numpy as np
import logging
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass
import json

from config import ValidationConfig, DEFAULT_VALIDATION_CONFIG, SyntheticScenario
from evt_threshold import GPDFit, gpd_cdf, gpd_quantile

logger = logging.getLogger(__name__)


# =============================================================================
# Importance Weights Computation
# =============================================================================

def compute_bin_probabilities(gpd_fit: GPDFit,
                              severity_bins: List[Tuple[float, float]],
                              historical_severities: np.ndarray) -> Dict[Tuple, float]:
    """
    Compute target probability for each severity bin based on GPD.
    
    Below threshold: use empirical distribution
    Above threshold: use GPD
    """
    n_total = len(historical_severities)
    p_above_threshold = gpd_fit.n_exceedances / n_total
    
    bin_probs = {}
    
    for lo, hi in severity_bins:
        if hi <= gpd_fit.threshold:
            # Below threshold: empirical
            count = np.sum((historical_severities >= lo) & (historical_severities < hi))
            prob = count / n_total
        elif lo >= gpd_fit.threshold:
            # Above threshold: GPD
            # P(lo < X < hi | X > u) from GPD
            excess_lo = max(0, lo - gpd_fit.threshold)
            excess_hi = hi - gpd_fit.threshold
            
            cdf_lo = gpd_cdf(excess_lo, gpd_fit.shape, gpd_fit.scale)
            cdf_hi = gpd_cdf(excess_hi, gpd_fit.shape, gpd_fit.scale)
            
            prob = (cdf_hi - cdf_lo) * p_above_threshold
        else:
            # Straddles threshold: split
            # Below part: empirical
            count_below = np.sum((historical_severities >= lo) & 
                                 (historical_severities < gpd_fit.threshold))
            prob_below = count_below / n_total
            
            # Above part: GPD
            excess_hi = hi - gpd_fit.threshold
            cdf_hi = gpd_cdf(excess_hi, gpd_fit.shape, gpd_fit.scale)
            prob_above = cdf_hi * p_above_threshold
            
            prob = prob_below + prob_above
        
        bin_probs[(lo, hi)] = max(prob, 1e-6)
    
    return bin_probs


def compute_importance_weights(scenarios: List[SyntheticScenario],
                               target_probs: Dict[Tuple, float],
                               severity_bins: List[Tuple[float, float]]) -> np.ndarray:
    """
    Compute importance weights for each scenario.
    
    Weight = target_prob / current_prob for the scenario's severity bin.
    """
    # Count scenarios per bin
    bin_counts = {b: 0 for b in severity_bins}
    scenario_bins = []
    
    for s in scenarios:
        # Find which bin this scenario falls into
        assigned_bin = None
        for lo, hi in severity_bins:
            if lo <= s.severity_ratio < hi:
                assigned_bin = (lo, hi)
                break
        
        if assigned_bin is None:
            # Assign to last bin if above max
            assigned_bin = severity_bins[-1]
        
        scenario_bins.append(assigned_bin)
        bin_counts[assigned_bin] += 1
    
    total = len(scenarios)
    
    # Compute weights
    weights = []
    for i, s in enumerate(scenarios):
        bin_key = scenario_bins[i]
        current_prob = bin_counts[bin_key] / total
        target_prob = target_probs[bin_key]
        
        weight = target_prob / current_prob if current_prob > 0 else 0
        weights.append(weight)
    
    return np.array(weights)


# =============================================================================
# Importance Sampling
# =============================================================================

def importance_sample(scenarios: List[SyntheticScenario],
                      weights: np.ndarray,
                      target_size: int,
                      with_replacement: bool = True) -> List[SyntheticScenario]:
    """
    Sample scenarios according to importance weights.
    """
    # Normalise weights to probabilities
    probs = weights / weights.sum()
    
    # Sample indices
    indices = np.random.choice(
        len(scenarios), 
        size=target_size, 
        replace=with_replacement,
        p=probs
    )
    
    return [scenarios[i] for i in indices]


def importance_sample_with_jittering(scenarios: List[SyntheticScenario],
                                     weights: np.ndarray,
                                     target_size: int,
                                     jitter_std: float = 0.01) -> List[SyntheticScenario]:
    """
    Sample with replacement and add small jitter to severity ratios
    to avoid exact duplicates in underrepresented bins.
    """
    probs = weights / weights.sum()
    
    indices = np.random.choice(
        len(scenarios),
        size=target_size,
        replace=True,
        p=probs
    )
    
    # Count how many times each scenario is selected
    from collections import Counter
    counts = Counter(indices)
    
    # Create output with jittered duplicates
    sampled = []
    for idx, count in counts.items():
        base_scenario = scenarios[idx]
        
        for i in range(count):
            # Copy scenario
            s = SyntheticScenario(
                id=f"{base_scenario.id}_jit{i}" if i > 0 else base_scenario.id,
                severity_ratio=base_scenario.severity_ratio,
                complexity_score=base_scenario.complexity_score,
                lob_breakdown=base_scenario.lob_breakdown.copy(),
                cause_category=base_scenario.cause_category,
                specific_events=base_scenario.specific_events.copy(),
                narrative=base_scenario.narrative,
                source_neighbours=base_scenario.source_neighbours.copy(),
                generation_bin=base_scenario.generation_bin,
                text_embedding=base_scenario.text_embedding,
                latent_coords=base_scenario.latent_coords,
                coherence_score=base_scenario.coherence_score,
                is_edge_case=base_scenario.is_edge_case
            )
            
            # Add jitter to duplicates
            if i > 0:
                jitter = np.random.normal(0, jitter_std)
                s.severity_ratio = max(0, s.severity_ratio + jitter)
            
            sampled.append(s)
    
    return sampled


# =============================================================================
# Full Importance Sampling Pipeline
# =============================================================================

@dataclass
class ImportanceSamplingResult:
    """Results of importance sampling."""
    original_count: int
    sampled_count: int
    
    # Distribution comparison
    original_bin_counts: Dict[str, int]
    target_bin_probs: Dict[str, float]
    sampled_bin_counts: Dict[str, int]
    
    # Quality metrics
    kl_divergence_original: float
    kl_divergence_sampled: float


def resample_to_gpd(scenarios: List[SyntheticScenario],
                    gpd_fit: GPDFit,
                    historical_severities: np.ndarray,
                    target_size: int,
                    severity_bins: List[Tuple[float, float]] = None) -> Tuple[List[SyntheticScenario], ImportanceSamplingResult]:
    """
    Resample scenarios to match GPD distribution.
    
    Args:
        scenarios: Generated synthetic scenarios
        gpd_fit: Fitted GPD parameters
        historical_severities: Historical severity ratios
        target_size: Target number of scenarios
        severity_bins: Optional custom bins (default: 5% bins)
    
    Returns:
        (resampled_scenarios, result_statistics)
    """
    logger.info(f"Resampling {len(scenarios)} scenarios to target size {target_size}")
    
    # Default 5% bins
    if severity_bins is None:
        max_sev = max(max(s.severity_ratio for s in scenarios), max(historical_severities))
        severity_bins = [(i * 0.05, (i + 1) * 0.05) for i in range(int(max_sev / 0.05) + 1)]
    
    # Compute target probabilities
    target_probs = compute_bin_probabilities(gpd_fit, severity_bins, historical_severities)
    
    # Compute importance weights
    weights = compute_importance_weights(scenarios, target_probs, severity_bins)
    
    # Log original distribution
    original_bin_counts = {f"{lo:.0%}-{hi:.0%}": 0 for lo, hi in severity_bins}
    for s in scenarios:
        for lo, hi in severity_bins:
            if lo <= s.severity_ratio < hi:
                original_bin_counts[f"{lo:.0%}-{hi:.0%}"] += 1
                break
    
    logger.info("Original distribution:")
    for bin_label, count in sorted(original_bin_counts.items()):
        if count > 0:
            logger.info(f"  {bin_label}: {count}")
    
    # Resample
    resampled = importance_sample_with_jittering(scenarios, weights, target_size)
    
    # Log resampled distribution
    sampled_bin_counts = {f"{lo:.0%}-{hi:.0%}": 0 for lo, hi in severity_bins}
    for s in resampled:
        for lo, hi in severity_bins:
            if lo <= s.severity_ratio < hi:
                sampled_bin_counts[f"{lo:.0%}-{hi:.0%}"] += 1
                break
    
    logger.info("Resampled distribution:")
    for bin_label, count in sorted(sampled_bin_counts.items()):
        if count > 0:
            logger.info(f"  {bin_label}: {count}")
    
    # Compute KL divergence improvement
    target_probs_arr = np.array([target_probs[b] for b in severity_bins])
    target_probs_arr = target_probs_arr / target_probs_arr.sum()
    
    original_probs = np.array([original_bin_counts[f"{lo:.0%}-{hi:.0%}"] / len(scenarios) 
                               for lo, hi in severity_bins])
    original_probs = np.clip(original_probs, 1e-10, 1)
    
    sampled_probs = np.array([sampled_bin_counts[f"{lo:.0%}-{hi:.0%}"] / len(resampled)
                              for lo, hi in severity_bins])
    sampled_probs = np.clip(sampled_probs, 1e-10, 1)
    
    kl_original = np.sum(target_probs_arr * np.log(target_probs_arr / original_probs))
    kl_sampled = np.sum(target_probs_arr * np.log(target_probs_arr / sampled_probs))
    
    logger.info(f"KL divergence: {kl_original:.4f} -> {kl_sampled:.4f}")
    
    result = ImportanceSamplingResult(
        original_count=len(scenarios),
        sampled_count=len(resampled),
        original_bin_counts=original_bin_counts,
        target_bin_probs={f"{lo:.0%}-{hi:.0%}": p for (lo, hi), p in target_probs.items()},
        sampled_bin_counts=sampled_bin_counts,
        kl_divergence_original=kl_original,
        kl_divergence_sampled=kl_sampled
    )
    
    return resampled, result


# =============================================================================
# CLI
# =============================================================================

if __name__ == "__main__":
    import argparse
    
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    
    parser = argparse.ArgumentParser(description="Importance sample scenarios to match GPD")
    parser.add_argument('--scenarios', '-s', required=True,
                        help='Path to synthetic scenarios JSON')
    parser.add_argument('--gpd', '-g', required=True,
                        help='Path to GPD fit JSON')
    parser.add_argument('--historical', '-h', required=True,
                        help='Path to historical data JSON')
    parser.add_argument('--target-size', '-n', type=int, default=2000,
                        help='Target library size')
    parser.add_argument('--output', '-o', default='results/stress_test/resampled_scenarios.json',
                        help='Output path')
    
    args = parser.parse_args()
    
    # Load data
    with open(args.scenarios, 'r') as f:
        scenarios_data = json.load(f)
    scenarios = [SyntheticScenario(**s) for s in scenarios_data['scenarios']]
    
    with open(args.gpd, 'r') as f:
        gpd_data = json.load(f)
    gpd_fit = GPDFit(**gpd_data)
    
    with open(args.historical, 'r') as f:
        hist_data = json.load(f)
    historical_severities = np.array([m['severity_ratio'] for m in hist_data['movements']])
    
    # Resample
    resampled, result = resample_to_gpd(
        scenarios, gpd_fit, historical_severities, args.target_size
    )
    
    # Save
    output_data = {
        'scenarios': [vars(s) for s in resampled],
        'resampling_result': {
            'original_count': result.original_count,
            'sampled_count': result.sampled_count,
            'kl_divergence_original': result.kl_divergence_original,
            'kl_divergence_sampled': result.kl_divergence_sampled,
            'target_bin_probs': result.target_bin_probs,
            'sampled_bin_counts': result.sampled_bin_counts
        }
    }
    
    with open(args.output, 'w') as f:
        json.dump(output_data, f, indent=2, default=str)
    
    print(f"\nSaved {len(resampled)} resampled scenarios to {args.output}")
