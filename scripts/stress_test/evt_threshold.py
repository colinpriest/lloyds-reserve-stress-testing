"""
Step 3: GPD Threshold Selection using Extreme Value Theory

Proper EVT techniques for threshold selection:
1. Mean Residual Life (MRL) plot - threshold where MRL becomes linear
2. Parameter stability plot - where ξ and σ* stabilise
3. Anderson-Darling goodness-of-fit test

Fits GPD with constraints:
- ξ < 0.5 for finite variance
- Upper/lower bound extrapolation constraints
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
from scipy import stats
from scipy.optimize import minimize, minimize_scalar
import warnings

from config import EVTConfig, DEFAULT_EVT_CONFIG

logger = logging.getLogger(__name__)


# =============================================================================
# Generalised Pareto Distribution
# =============================================================================

@dataclass
class GPDFit:
    """Results of GPD fitting."""
    threshold: float
    shape: float  # ξ (xi)
    scale: float  # σ (sigma)
    n_exceedances: int
    n_total: int
    
    # Diagnostics
    ad_statistic: float
    ad_pvalue: float
    ks_statistic: float
    ks_pvalue: float
    
    # Confidence intervals (bootstrap)
    shape_ci: Optional[Tuple[float, float]] = None
    scale_ci: Optional[Tuple[float, float]] = None

    def __post_init__(self):
        """Convert lists to tuples (e.g. when loaded from JSON)."""
        if isinstance(self.shape_ci, list):
            self.shape_ci = tuple(self.shape_ci)
        if isinstance(self.scale_ci, list):
            self.scale_ci = tuple(self.scale_ci)


def gpd_cdf(x: np.ndarray, shape: float, scale: float) -> np.ndarray:
    """GPD cumulative distribution function."""
    if abs(shape) < 1e-10:
        # Exponential case (ξ → 0)
        return 1 - np.exp(-x / scale)
    else:
        z = 1 + shape * x / scale
        z = np.maximum(z, 1e-10)  # Avoid negative values
        return 1 - z ** (-1 / shape)


def gpd_quantile(p: float, shape: float, scale: float) -> float:
    """GPD quantile function (inverse CDF)."""
    if abs(shape) < 1e-10:
        return -scale * np.log(1 - p)
    else:
        return scale * ((1 - p) ** (-shape) - 1) / shape


def gpd_log_likelihood(params: np.ndarray, exceedances: np.ndarray) -> float:
    """Negative log-likelihood for GPD."""
    shape, scale = params
    
    if scale <= 0:
        return np.inf
    
    n = len(exceedances)
    
    if abs(shape) < 1e-10:
        # Exponential case
        return n * np.log(scale) + np.sum(exceedances) / scale
    
    # Check support constraint: 1 + ξx/σ > 0
    z = 1 + shape * exceedances / scale
    if np.any(z <= 0):
        return np.inf
    
    # Negative log-likelihood
    ll = n * np.log(scale) + (1 + 1/shape) * np.sum(np.log(z))
    return ll


def fit_gpd(exceedances: np.ndarray, 
            max_shape: float = 0.5,
            method: str = 'mle') -> Tuple[float, float]:
    """
    Fit GPD to exceedances using constrained MLE.
    
    Returns:
        (shape, scale) parameters
    """
    exceedances = np.asarray(exceedances)
    exceedances = exceedances[exceedances > 0]  # Remove zeros
    
    if len(exceedances) < 10:
        logger.warning("Too few exceedances for reliable GPD fit")
        return 0.1, np.std(exceedances)
    
    # Initial estimates using probability weighted moments
    exceedances_sorted = np.sort(exceedances)
    n = len(exceedances_sorted)
    
    # PWM estimators
    b0 = np.mean(exceedances_sorted)
    b1 = np.sum(np.arange(0, n) * exceedances_sorted) / (n * (n - 1))
    
    # Initial shape and scale from PWM
    shape_init = 2 - b0 / (b0 - 2 * b1)
    scale_init = 2 * b0 * b1 / (b0 - 2 * b1)
    
    # Clamp initial values
    shape_init = np.clip(shape_init, -0.5, max_shape - 0.01)
    scale_init = max(scale_init, 0.01)
    
    # Constrained optimisation
    def objective(params):
        return gpd_log_likelihood(params, exceedances)
    
    # Constraints: shape < max_shape, scale > 0
    bounds = [(-0.5, max_shape - 0.001), (1e-6, None)]
    
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        result = minimize(
            objective,
            [shape_init, scale_init],
            method='L-BFGS-B',
            bounds=bounds
        )
    
    if result.success:
        return result.x[0], result.x[1]
    else:
        logger.warning(f"GPD optimisation did not converge: {result.message}")
        return shape_init, scale_init


def gpd_goodness_of_fit(exceedances: np.ndarray, 
                        shape: float, 
                        scale: float) -> Tuple[float, float, float, float]:
    """
    Compute goodness-of-fit statistics for GPD fit.
    
    Returns:
        (ad_statistic, ad_pvalue, ks_statistic, ks_pvalue)
    """
    n = len(exceedances)
    
    # Compute probability integral transform
    pit = gpd_cdf(exceedances, shape, scale)
    pit = np.sort(pit)
    
    # Anderson-Darling statistic
    i = np.arange(1, n + 1)
    ad_stat = -n - np.sum((2 * i - 1) * (np.log(pit + 1e-10) + np.log(1 - pit[::-1] + 1e-10))) / n
    
    # AD p-value (asymptotic approximation for uniform)
    # Using modified statistic
    ad_star = ad_stat * (1 + 0.75/n + 2.25/n**2)
    if ad_star < 0.2:
        ad_pvalue = 1 - np.exp(-13.436 + 101.14 * ad_star - 223.73 * ad_star**2)
    elif ad_star < 0.34:
        ad_pvalue = 1 - np.exp(-8.318 + 42.796 * ad_star - 59.938 * ad_star**2)
    elif ad_star < 0.6:
        ad_pvalue = np.exp(0.9177 - 4.279 * ad_star - 1.38 * ad_star**2)
    else:
        ad_pvalue = np.exp(1.2937 - 5.709 * ad_star + 0.0186 * ad_star**2)
    ad_pvalue = np.clip(ad_pvalue, 0, 1)
    
    # Kolmogorov-Smirnov test
    ks_result = stats.kstest(pit, 'uniform')
    
    return ad_stat, ad_pvalue, ks_result.statistic, ks_result.pvalue


# =============================================================================
# Threshold Selection Diagnostics
# =============================================================================

def mean_residual_life_plot(data: np.ndarray, 
                            n_thresholds: int = 50) -> Dict:
    """
    Compute Mean Residual Life (MRL) plot data.
    
    MRL at threshold u = E[X - u | X > u]
    
    Valid threshold: where MRL becomes approximately linear.
    """
    data = np.sort(data)
    n = len(data)
    
    # Candidate thresholds (from 10th to 90th percentile)
    thresholds = np.linspace(np.percentile(data, 10), np.percentile(data, 90), n_thresholds)
    
    mrl_values = []
    mrl_ci_lower = []
    mrl_ci_upper = []
    n_exceed = []
    
    for u in thresholds:
        exceedances = data[data > u] - u
        if len(exceedances) < 10:
            break
        
        mean_excess = np.mean(exceedances)
        std_excess = np.std(exceedances) / np.sqrt(len(exceedances))
        
        mrl_values.append(mean_excess)
        mrl_ci_lower.append(mean_excess - 1.96 * std_excess)
        mrl_ci_upper.append(mean_excess + 1.96 * std_excess)
        n_exceed.append(len(exceedances))
    
    return {
        'thresholds': thresholds[:len(mrl_values)],
        'mrl': np.array(mrl_values),
        'ci_lower': np.array(mrl_ci_lower),
        'ci_upper': np.array(mrl_ci_upper),
        'n_exceedances': np.array(n_exceed)
    }


def parameter_stability_plot(data: np.ndarray,
                             n_thresholds: int = 30,
                             max_shape: float = 0.5) -> Dict:
    """
    Compute parameter stability plot data.
    
    Fit GPD at each threshold and track shape (ξ) and modified scale (σ* = σ - ξu).
    
    Valid threshold: where both parameters stabilise.
    """
    data = np.sort(data)
    
    # Candidate thresholds
    thresholds = np.linspace(np.percentile(data, 50), np.percentile(data, 95), n_thresholds)
    
    shapes = []
    scales = []
    modified_scales = []  # σ* = σ - ξu
    n_exceed = []
    
    for u in thresholds:
        exceedances = data[data > u] - u
        if len(exceedances) < 20:
            break
        
        shape, scale = fit_gpd(exceedances, max_shape=max_shape)
        mod_scale = scale - shape * u
        
        shapes.append(shape)
        scales.append(scale)
        modified_scales.append(mod_scale)
        n_exceed.append(len(exceedances))
    
    return {
        'thresholds': thresholds[:len(shapes)],
        'shape': np.array(shapes),
        'scale': np.array(scales),
        'modified_scale': np.array(modified_scales),
        'n_exceedances': np.array(n_exceed)
    }


def find_stable_region(values: np.ndarray, window: int = 5) -> Tuple[int, int]:
    """
    Find region where values are approximately stable.
    
    Uses rolling standard deviation to find low-variance region.
    """
    if len(values) < window * 2:
        return 0, len(values) - 1
    
    # Rolling std
    rolling_std = np.array([
        np.std(values[i:i+window]) 
        for i in range(len(values) - window + 1)
    ])
    
    # Find region with lowest rolling std
    min_idx = np.argmin(rolling_std)
    
    # Expand region while std stays low
    threshold = rolling_std[min_idx] * 2
    start = min_idx
    end = min_idx + window
    
    while start > 0 and rolling_std[start - 1] < threshold:
        start -= 1
    while end < len(values) and end - window < len(rolling_std) and rolling_std[end - window] < threshold:
        end += 1
    
    return start, end


def select_threshold_consensus(data: np.ndarray,
                               config: EVTConfig = None) -> Tuple[float, Dict]:
    """
    Select GPD threshold using consensus of diagnostic methods.
    
    Returns:
        (selected_threshold, diagnostics_dict)
    """
    config = config or DEFAULT_EVT_CONFIG
    
    logger.info("Selecting GPD threshold using consensus approach...")
    
    # 1. Mean Residual Life analysis
    mrl_data = mean_residual_life_plot(data)
    mrl_stable_start, mrl_stable_end = find_stable_region(mrl_data['mrl'])
    mrl_threshold = mrl_data['thresholds'][mrl_stable_start]
    logger.info(f"MRL suggests threshold around {mrl_threshold:.4f}")
    
    # 2. Parameter stability analysis
    stability_data = parameter_stability_plot(data, max_shape=config.max_shape)
    shape_stable_start, shape_stable_end = find_stable_region(stability_data['shape'])
    stability_threshold = stability_data['thresholds'][shape_stable_start]
    logger.info(f"Parameter stability suggests threshold around {stability_threshold:.4f}")
    
    # 3. Anderson-Darling goodness-of-fit
    candidate_thresholds = np.linspace(
        np.percentile(data, 70),
        np.percentile(data, 95),
        config.threshold_candidates
    )
    
    ad_results = []
    for u in candidate_thresholds:
        exceedances = data[data > u] - u
        if len(exceedances) < config.min_exceedances:
            continue
        
        shape, scale = fit_gpd(exceedances, max_shape=config.max_shape)
        ad_stat, ad_pval, _, _ = gpd_goodness_of_fit(exceedances, shape, scale)
        ad_results.append((u, ad_pval, shape, scale, len(exceedances)))
    
    # Find thresholds with acceptable fit (p > 0.05)
    acceptable = [(u, p, s, sc, n) for u, p, s, sc, n in ad_results if p > config.ad_significance]
    
    if acceptable:
        # Choose lowest threshold with acceptable fit
        ad_threshold = min(acceptable, key=lambda x: x[0])[0]
    else:
        # Fall back to highest p-value
        ad_threshold = max(ad_results, key=lambda x: x[1])[0]
    logger.info(f"Anderson-Darling suggests threshold around {ad_threshold:.4f}")
    
    # Consensus: weighted average favouring lower thresholds (more data)
    thresholds = [mrl_threshold, stability_threshold, ad_threshold]
    weights = [0.3, 0.3, 0.4]  # Slightly favour AD test
    
    consensus_threshold = np.average(thresholds, weights=weights)
    
    # Ensure minimum exceedances
    n_exceed = np.sum(data > consensus_threshold)
    if n_exceed < config.min_exceedances:
        # Lower threshold to get enough data
        sorted_data = np.sort(data)[::-1]
        consensus_threshold = sorted_data[config.min_exceedances - 1]
        logger.warning(f"Raised threshold to ensure {config.min_exceedances} exceedances")
    
    logger.info(f"Consensus threshold: {consensus_threshold:.4f} "
                f"({np.sum(data > consensus_threshold)} exceedances)")
    
    return consensus_threshold, {
        'mrl': mrl_data,
        'stability': stability_data,
        'ad_results': ad_results,
        'individual_thresholds': {
            'mrl': mrl_threshold,
            'stability': stability_threshold,
            'ad': ad_threshold
        }
    }


# =============================================================================
# Full GPD Fitting with Constraints
# =============================================================================

def fit_gpd_constrained(data: np.ndarray,
                        threshold: float = None,
                        config: EVTConfig = None) -> GPDFit:
    """
    Fit GPD with all constraints from the paper:
    
    1. ξ < 0.5 for finite variance
    2. Upper-bound extrapolation: F(x_max) ≤ 1 - 0.5/n_u
    3. Lower-bound coverage: F(x_max) ≥ 1 - 1.5/n_u
    """
    config = config or DEFAULT_EVT_CONFIG
    
    # Select threshold if not provided
    if threshold is None:
        threshold, _ = select_threshold_consensus(data, config)
    
    # Get exceedances
    exceedances = data[data > threshold] - threshold
    n_exceed = len(exceedances)
    n_total = len(data)
    
    logger.info(f"Fitting GPD: threshold={threshold:.4f}, n_exceedances={n_exceed}")
    
    # Fit with shape constraint
    shape, scale = fit_gpd(exceedances, max_shape=config.max_shape)
    
    # Check extrapolation constraints
    x_max = np.max(exceedances)
    f_max = gpd_cdf(x_max, shape, scale)
    
    upper_bound = 1 - 0.5 / n_exceed
    lower_bound = 1 - 1.5 / n_exceed
    
    if f_max > upper_bound:
        logger.warning(f"F(x_max)={f_max:.4f} exceeds upper bound {upper_bound:.4f}")
        # Adjust scale to satisfy constraint
        # Solve: 1 - (1 + ξ*x_max/σ)^(-1/ξ) = upper_bound
        target_cdf = upper_bound
        if abs(shape) > 1e-10:
            scale = shape * x_max / ((1 - target_cdf) ** (-shape) - 1)
        
    if f_max < lower_bound:
        logger.warning(f"F(x_max)={f_max:.4f} below lower bound {lower_bound:.4f}")
    
    # Goodness of fit
    ad_stat, ad_pval, ks_stat, ks_pval = gpd_goodness_of_fit(exceedances, shape, scale)
    
    # Bootstrap confidence intervals
    shape_samples = []
    scale_samples = []
    
    for _ in range(config.n_bootstrap):
        boot_idx = np.random.choice(n_exceed, n_exceed, replace=True)
        boot_exc = exceedances[boot_idx]
        boot_shape, boot_scale = fit_gpd(boot_exc, max_shape=config.max_shape)
        shape_samples.append(boot_shape)
        scale_samples.append(boot_scale)
    
    shape_ci = (np.percentile(shape_samples, 2.5), np.percentile(shape_samples, 97.5))
    scale_ci = (np.percentile(scale_samples, 2.5), np.percentile(scale_samples, 97.5))
    
    return GPDFit(
        threshold=threshold,
        shape=shape,
        scale=scale,
        n_exceedances=n_exceed,
        n_total=n_total,
        ad_statistic=ad_stat,
        ad_pvalue=ad_pval,
        ks_statistic=ks_stat,
        ks_pvalue=ks_pval,
        shape_ci=shape_ci,
        scale_ci=scale_ci
    )


def return_period_to_severity(gpd_fit: GPDFit, 
                               return_period: int,
                               n_observations_per_year: float = 1.0) -> float:
    """
    Convert return period to severity quantile.
    
    Args:
        gpd_fit: Fitted GPD parameters
        return_period: Return period in years
        n_observations_per_year: Expected observations per year (for scaling)
    
    Returns:
        Severity ratio corresponding to return period
    """
    # Probability of exceedance
    p_exceed = 1.0 / (return_period * n_observations_per_year)
    
    # Probability of being above threshold
    p_above_threshold = gpd_fit.n_exceedances / gpd_fit.n_total
    
    # Conditional probability within GPD
    p_gpd = 1 - p_exceed / p_above_threshold
    
    if p_gpd < 0 or p_gpd > 1:
        logger.warning(f"Invalid GPD probability {p_gpd} for return period {return_period} "
                       f"— return period is below the threshold region, returning threshold severity")
        return gpd_fit.threshold
    
    # GPD quantile
    excess = gpd_quantile(p_gpd, gpd_fit.shape, gpd_fit.scale)
    
    return gpd_fit.threshold + excess


def severity_to_return_period(gpd_fit: GPDFit,
                               severity: float,
                               historical_severities: np.ndarray = None,
                               n_observations_per_year: float = 1.0) -> float:
    """
    Convert severity to return period.

    Args:
        gpd_fit: Fitted GPD parameters
        severity: Severity value to convert
        historical_severities: Array of historical severity values for empirical CDF
        n_observations_per_year: Number of observations per year
    """
    if severity <= gpd_fit.threshold:
        if historical_severities is None:
            raise ValueError("historical_severities required for below-threshold severity-to-return-period conversion")
        # Below threshold: use empirical exceedance probability
        n_exceed = np.sum(historical_severities >= severity)
        p_exceed = n_exceed / len(historical_severities)
        return 1.0 / max(p_exceed * n_observations_per_year, 0.0001)
    
    excess = severity - gpd_fit.threshold
    p_gpd = gpd_cdf(excess, gpd_fit.shape, gpd_fit.scale)
    p_above_threshold = gpd_fit.n_exceedances / gpd_fit.n_total
    p_exceed = (1 - p_gpd) * p_above_threshold
    
    return 1.0 / max(p_exceed * n_observations_per_year, 0.0001)


# =============================================================================
# CLI
# =============================================================================

if __name__ == "__main__":
    import argparse
    import json
    
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    
    parser = argparse.ArgumentParser(description="Fit GPD to severity data")
    parser.add_argument('--input', '-i', default='results/stress_test/prepared_data.json',
                        help='Path to prepared data')
    parser.add_argument('--output', '-o', default='results/stress_test/gpd_fit.json',
                        help='Output path for GPD parameters')
    
    args = parser.parse_args()
    
    # Load data
    with open(args.input, 'r') as f:
        data = json.load(f)
    
    severities = np.array([m['severity_ratio'] for m in data['movements']])
    
    print(f"\nData: {len(severities)} observations")
    print(f"Severity range: {severities.min():.4f} - {severities.max():.4f}")
    print(f"Severity mean: {severities.mean():.4f}")
    print(f"Severity 95th percentile: {np.percentile(severities, 95):.4f}")
    
    # Select threshold and fit GPD
    gpd_fit = fit_gpd_constrained(severities)
    
    print(f"\n=== GPD Fit Results ===")
    print(f"Threshold: {gpd_fit.threshold:.4f}")
    print(f"Shape (xi): {gpd_fit.shape:.4f} ({gpd_fit.shape_ci[0]:.4f}, {gpd_fit.shape_ci[1]:.4f})")
    print(f"Scale (sigma): {gpd_fit.scale:.4f} ({gpd_fit.scale_ci[0]:.4f}, {gpd_fit.scale_ci[1]:.4f})")
    print(f"Exceedances: {gpd_fit.n_exceedances}")
    print(f"Anderson-Darling: stat={gpd_fit.ad_statistic:.4f}, p={gpd_fit.ad_pvalue:.4f}")
    print(f"Kolmogorov-Smirnov: stat={gpd_fit.ks_statistic:.4f}, p={gpd_fit.ks_pvalue:.4f}")
    
    # Return period examples
    print(f"\n=== Return Period Mapping ===")
    for rp in [10, 25, 50, 100, 200, 500]:
        sev = return_period_to_severity(gpd_fit, rp)
        print(f"{rp}-year: {sev:.2%} severity")
    
    # Save results
    output_data = {
        'threshold': gpd_fit.threshold,
        'shape': gpd_fit.shape,
        'scale': gpd_fit.scale,
        'shape_ci': gpd_fit.shape_ci,
        'scale_ci': gpd_fit.scale_ci,
        'n_exceedances': gpd_fit.n_exceedances,
        'n_total': gpd_fit.n_total,
        'ad_statistic': gpd_fit.ad_statistic,
        'ad_pvalue': gpd_fit.ad_pvalue,
        'ks_statistic': gpd_fit.ks_statistic,
        'ks_pvalue': gpd_fit.ks_pvalue
    }
    
    with open(args.output, 'w') as f:
        json.dump(output_data, f, indent=2)
    print(f"\nSaved GPD fit to {args.output}")
