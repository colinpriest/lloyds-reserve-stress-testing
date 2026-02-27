"""
Improved GPD Fitting with Multiple Threshold Selection Methods

Methods implemented:
1. Shape parameter stability analysis
2. Scale parameter stability analysis  
3. Mean residual life plot linearity
4. Anderson-Darling goodness-of-fit
5. Automated consensus selection

Constraints:
- Shape parameter ξ < 0.5 (finite variance)
- Tail extrapolation bounds (not too conservative, not too aggressive)
"""

import sys
from pathlib import Path
_script_dir = Path(__file__).resolve().parent
if str(_script_dir) not in sys.path:
    sys.path.insert(0, str(_script_dir))

import numpy as np
import logging
from typing import Tuple, Dict, List, Optional
from dataclasses import dataclass
from scipy import stats
from scipy.optimize import minimize
from scipy.ndimage import uniform_filter1d

logger = logging.getLogger(__name__)


@dataclass
class GPDFitResult:
    """Result of GPD fitting."""
    threshold: float
    threshold_percentile: float
    shape: float  # ξ (xi)
    scale: float  # σ (sigma)
    n_exceedances: int
    n_total: int
    
    # Fit quality metrics
    ad_statistic: float = None  # Anderson-Darling
    ks_statistic: float = None  # Kolmogorov-Smirnov
    ks_pvalue: float = None
    
    # Method used
    method: str = "automated"
    
    @property
    def exceedance_prob(self) -> float:
        return self.n_exceedances / self.n_total
    
    def severity_for_return_period(self, return_period: int) -> float:
        """Compute severity for a given return period."""
        p_exceed = 1 / return_period
        p_threshold = self.exceedance_prob
        
        if p_exceed > p_threshold:
            # Below threshold - linear interpolation
            return self.threshold * (p_exceed / p_threshold)
        
        # Conditional exceedance probability
        p_cond = p_exceed / p_threshold
        
        if abs(self.shape) < 1e-6:
            # Exponential case
            exceedance = -self.scale * np.log(p_cond)
        else:
            exceedance = (self.scale / self.shape) * (p_cond**(-self.shape) - 1)
        
        return self.threshold + exceedance


# =============================================================================
# Threshold Selection Methods
# =============================================================================

def analyze_parameter_stability(data: np.ndarray,
                                percentile_range: Tuple[float, float] = (80, 99),
                                n_thresholds: int = 50) -> Dict:
    """
    Analyze shape and scale parameter stability across thresholds.
    
    Returns dict with threshold analysis results.
    """
    percentiles = np.linspace(percentile_range[0], percentile_range[1], n_thresholds)
    thresholds = np.percentile(data, percentiles)
    
    shapes = []
    scales = []
    shape_cis = []
    scale_cis = []
    n_exceedances_list = []
    
    for u in thresholds:
        exceedances = data[data > u] - u
        n_exc = len(exceedances)
        
        if n_exc < 10:
            shapes.append(np.nan)
            scales.append(np.nan)
            shape_cis.append((np.nan, np.nan))
            scale_cis.append((np.nan, np.nan))
            n_exceedances_list.append(n_exc)
            continue
        
        try:
            # Fit GPD
            c, loc, scale = stats.genpareto.fit(exceedances, floc=0)
            shape = c
            
            # Bootstrap CI (simplified)
            n_bootstrap = 100
            boot_shapes = []
            boot_scales = []
            for _ in range(n_bootstrap):
                boot_sample = np.random.choice(exceedances, size=len(exceedances), replace=True)
                try:
                    bc, _, bs = stats.genpareto.fit(boot_sample, floc=0)
                    boot_shapes.append(bc)
                    boot_scales.append(bs)
                except:
                    pass
            
            if boot_shapes:
                shape_ci = (np.percentile(boot_shapes, 2.5), np.percentile(boot_shapes, 97.5))
                scale_ci = (np.percentile(boot_scales, 2.5), np.percentile(boot_scales, 97.5))
            else:
                shape_ci = (np.nan, np.nan)
                scale_ci = (np.nan, np.nan)
            
            shapes.append(shape)
            scales.append(scale)
            shape_cis.append(shape_ci)
            scale_cis.append(scale_ci)
            n_exceedances_list.append(n_exc)
            
        except Exception as e:
            shapes.append(np.nan)
            scales.append(np.nan)
            shape_cis.append((np.nan, np.nan))
            scale_cis.append((np.nan, np.nan))
            n_exceedances_list.append(n_exc)
    
    return {
        'percentiles': percentiles,
        'thresholds': thresholds,
        'shapes': np.array(shapes),
        'scales': np.array(scales),
        'shape_cis': shape_cis,
        'scale_cis': scale_cis,
        'n_exceedances': n_exceedances_list
    }


def select_threshold_shape_stability(analysis: Dict, 
                                     max_shape: float = 0.5,
                                     stability_window: int = 5) -> Tuple[int, float]:
    """
    Select threshold based on shape parameter stability.
    
    Finds the region where shape parameter is stable and below max_shape.
    
    Returns:
        (best_idx, score)
    """
    shapes = analysis['shapes']
    percentiles = analysis['percentiles']
    
    # Find valid indices (not NaN and shape < max_shape)
    valid = ~np.isnan(shapes) & (shapes < max_shape) & (shapes > -0.5)
    
    if not np.any(valid):
        return None, 0.0
    
    # Compute local stability (low variance in rolling window)
    scores = np.zeros(len(shapes))
    
    for i in range(len(shapes)):
        if not valid[i]:
            continue
        
        # Get window around this point
        start = max(0, i - stability_window // 2)
        end = min(len(shapes), i + stability_window // 2 + 1)
        window = shapes[start:end]
        window = window[~np.isnan(window)]
        
        if len(window) < 3:
            continue
        
        # Score based on low CV and low gradient
        cv = np.std(window) / (np.abs(np.mean(window)) + 1e-6)
        gradient = np.abs(np.gradient(window)).mean() if len(window) > 1 else 1.0
        
        # Prefer lower CV and lower gradient
        stability_score = 1.0 / (1 + cv) * 1.0 / (1 + gradient * 10)
        
        # Bonus for having enough data (earlier thresholds have more exceedances)
        data_score = (100 - percentiles[i]) / 100  # More data = higher score
        
        # Penalty for shape near boundary
        shape_penalty = 1.0 - abs(shapes[i]) / max_shape
        
        scores[i] = stability_score * (0.5 + 0.5 * data_score) * shape_penalty
    
    if scores.max() == 0:
        return None, 0.0
    
    best_idx = np.argmax(scores)
    return best_idx, scores[best_idx]


def select_threshold_scale_stability(analysis: Dict,
                                     stability_window: int = 5) -> Tuple[int, float]:
    """
    Select threshold based on scale parameter stability.
    
    Looks for transition from increasing to stable scale parameter.
    
    Returns:
        (best_idx, score)
    """
    scales = analysis['scales']
    percentiles = analysis['percentiles']
    
    valid = ~np.isnan(scales)
    if not np.any(valid):
        return None, 0.0
    
    # Compute gradient
    scales_filled = np.where(valid, scales, np.interp(np.arange(len(scales)), 
                                                       np.where(valid)[0], 
                                                       scales[valid]))
    gradients = np.gradient(scales_filled)
    smooth_gradients = uniform_filter1d(gradients, size=stability_window)
    
    scores = np.zeros(len(scales))
    
    for i in range(len(scales)):
        if not valid[i]:
            continue
        
        # Score based on:
        # 1. Low local gradient (stable)
        gradient_score = 1.0 / (1 + abs(smooth_gradients[i]) * 10)
        
        # 2. Past transition point (gradient went from positive to near-zero)
        past_transition = False
        if i > stability_window:
            before = smooth_gradients[i-stability_window:i].mean()
            after = smooth_gradients[i:min(i+stability_window, len(smooth_gradients))].mean()
            if before > 0.01 and abs(after) < 0.01:
                past_transition = True
        transition_bonus = 0.3 if past_transition else 0.0
        
        # 3. Not too far in the tail (enough data)
        data_score = (100 - percentiles[i]) / 100
        
        scores[i] = gradient_score * (0.5 + 0.5 * data_score) + transition_bonus
    
    if scores.max() == 0:
        return None, 0.0
    
    best_idx = np.argmax(scores)
    return best_idx, scores[best_idx]


def select_threshold_mean_excess(data: np.ndarray,
                                 percentile_range: Tuple[float, float] = (80, 99),
                                 n_thresholds: int = 50) -> Tuple[float, float, float]:
    """
    Select threshold using mean excess plot linearity.
    
    For GPD, E[X - u | X > u] should be linear in u.
    
    Returns:
        (threshold, percentile, r2_score)
    """
    percentiles = np.linspace(percentile_range[0], percentile_range[1], n_thresholds)
    thresholds = np.percentile(data, percentiles)
    
    mean_excesses = []
    for u in thresholds:
        exceedances = data[data > u] - u
        if len(exceedances) >= 10:
            mean_excesses.append(exceedances.mean())
        else:
            mean_excesses.append(np.nan)
    
    mean_excesses = np.array(mean_excesses)
    valid = ~np.isnan(mean_excesses)
    
    if valid.sum() < 10:
        return thresholds[len(thresholds)//2], percentiles[len(percentiles)//2], 0.0
    
    # Find the threshold where linearity is best
    best_r2 = -np.inf
    best_idx = 0
    
    for start_idx in range(len(thresholds) - 10):
        # Fit linear model from start_idx to end
        x = thresholds[start_idx:][valid[start_idx:]]
        y = mean_excesses[start_idx:][valid[start_idx:]]
        
        if len(x) < 5:
            continue
        
        # Linear regression
        slope, intercept, r_value, _, _ = stats.linregress(x, y)
        r2 = r_value ** 2
        
        # Prefer earlier thresholds with good R²
        adjusted_r2 = r2 * (1 - start_idx / len(thresholds) * 0.3)
        
        if adjusted_r2 > best_r2:
            best_r2 = adjusted_r2
            best_idx = start_idx
    
    return thresholds[best_idx], percentiles[best_idx], best_r2


def select_threshold_goodness_of_fit(data: np.ndarray,
                                     percentile_range: Tuple[float, float] = (80, 99),
                                     n_thresholds: int = 30) -> Tuple[float, float, float]:
    """
    Select threshold by Anderson-Darling goodness-of-fit.
    
    Returns:
        (threshold, percentile, ad_statistic)
    """
    percentiles = np.linspace(percentile_range[0], percentile_range[1], n_thresholds)
    thresholds = np.percentile(data, percentiles)
    
    best_ad = np.inf
    best_idx = 0
    
    for i, u in enumerate(thresholds):
        exceedances = data[data > u] - u
        
        if len(exceedances) < 20:
            continue
        
        try:
            # Fit GPD
            c, _, scale = stats.genpareto.fit(exceedances, floc=0)
            
            # Skip if shape is unreasonable
            if c >= 0.5 or c < -0.5:
                continue
            
            # Anderson-Darling test
            # Transform to uniform using fitted CDF
            u_vals = stats.genpareto.cdf(exceedances, c, loc=0, scale=scale)
            
            # AD statistic for uniform
            u_sorted = np.sort(u_vals)
            n = len(u_sorted)
            i_vals = np.arange(1, n + 1)
            
            ad = -n - np.mean((2 * i_vals - 1) * (np.log(u_sorted + 1e-10) + 
                                                    np.log(1 - u_sorted[::-1] + 1e-10)))
            
            if ad < best_ad:
                best_ad = ad
                best_idx = i
                
        except Exception:
            continue
    
    return thresholds[best_idx], percentiles[best_idx], best_ad


# =============================================================================
# Main GPD Fitting Function
# =============================================================================

def fit_gpd_improved(data: np.ndarray,
                     method: str = 'automated',
                     max_shape: float = 0.5,
                     min_exceedances: int = 20,
                     percentile_range: Tuple[float, float] = (80, 99)) -> GPDFitResult:
    """
    Fit GPD with improved threshold selection.
    
    Methods:
    - 'shape_stability': Shape parameter stability analysis
    - 'scale_stability': Scale parameter stability analysis
    - 'mean_excess': Mean excess plot linearity
    - 'goodness_of_fit': Anderson-Darling minimization
    - 'automated': Consensus of all methods
    
    Args:
        data: Array of positive values (severities)
        method: Threshold selection method
        max_shape: Maximum allowed shape parameter (for finite variance)
        min_exceedances: Minimum exceedances required
        percentile_range: Range to search for threshold
    
    Returns:
        GPDFitResult with fitted parameters
    """
    data = np.asarray(data)
    data = data[data > 0]  # Remove zeros
    n_total = len(data)
    
    logger.info(f"Fitting GPD to {n_total} observations")
    logger.info(f"Data range: {data.min():.2%} to {data.max():.2%}")
    
    # Run parameter stability analysis
    analysis = analyze_parameter_stability(data, percentile_range)
    
    # Select threshold based on method
    if method == 'shape_stability':
        idx, score = select_threshold_shape_stability(analysis, max_shape)
        if idx is None:
            idx = len(analysis['thresholds']) // 2
        threshold = analysis['thresholds'][idx]
        threshold_pct = analysis['percentiles'][idx]
        
    elif method == 'scale_stability':
        idx, score = select_threshold_scale_stability(analysis)
        if idx is None:
            idx = len(analysis['thresholds']) // 2
        threshold = analysis['thresholds'][idx]
        threshold_pct = analysis['percentiles'][idx]
        
    elif method == 'mean_excess':
        threshold, threshold_pct, _ = select_threshold_mean_excess(data, percentile_range)
        
    elif method == 'goodness_of_fit':
        threshold, threshold_pct, _ = select_threshold_goodness_of_fit(data, percentile_range)
        
    elif method == 'automated':
        # Run all methods and take consensus
        results = []
        
        idx1, score1 = select_threshold_shape_stability(analysis, max_shape)
        if idx1 is not None:
            results.append(('shape', analysis['percentiles'][idx1], score1))
        
        idx2, score2 = select_threshold_scale_stability(analysis)
        if idx2 is not None:
            results.append(('scale', analysis['percentiles'][idx2], score2))
        
        _, pct3, r2 = select_threshold_mean_excess(data, percentile_range)
        results.append(('mean_excess', pct3, r2))
        
        _, pct4, ad = select_threshold_goodness_of_fit(data, percentile_range)
        results.append(('gof', pct4, 1.0 / (1 + ad)))  # Invert AD for scoring
        
        # Weighted average of percentiles
        if results:
            total_weight = sum(r[2] for r in results)
            if total_weight > 0:
                threshold_pct = sum(r[1] * r[2] for r in results) / total_weight
            else:
                threshold_pct = np.median([r[1] for r in results])
        else:
            threshold_pct = 85.0  # Fallback
        
        # Round to nearest 5%
        threshold_pct = round(threshold_pct / 5) * 5
        threshold_pct = np.clip(threshold_pct, percentile_range[0], percentile_range[1])
        threshold = np.percentile(data, threshold_pct)
        
        logger.info(f"Threshold selection results: {[(r[0], f'{r[1]:.0f}%') for r in results]}")
        logger.info(f"Consensus threshold: {threshold_pct:.0f}th percentile")
    
    else:
        raise ValueError(f"Unknown method: {method}")
    
    # Fit GPD with constraints
    exceedances = data[data > threshold] - threshold
    n_exc = len(exceedances)
    
    if n_exc < min_exceedances:
        logger.warning(f"Only {n_exc} exceedances, lowering threshold")
        threshold_pct = max(percentile_range[0], threshold_pct - 10)
        threshold = np.percentile(data, threshold_pct)
        exceedances = data[data > threshold] - threshold
        n_exc = len(exceedances)
    
    logger.info(f"Threshold: {threshold:.2%} ({threshold_pct:.0f}th percentile)")
    logger.info(f"Exceedances: {n_exc}")
    
    # Constrained GPD fit
    shape, scale = fit_gpd_constrained(
        exceedances, 
        max_shape=max_shape,
        data_max=data.max() - threshold
    )
    
    # Compute fit quality metrics
    try:
        # KS test
        ks_stat, ks_pval = stats.kstest(
            exceedances, 
            lambda x: stats.genpareto.cdf(x, shape, loc=0, scale=scale)
        )
        
        # AD statistic
        u_vals = stats.genpareto.cdf(exceedances, shape, loc=0, scale=scale)
        u_sorted = np.sort(u_vals)
        n = len(u_sorted)
        i_vals = np.arange(1, n + 1)
        ad_stat = -n - np.mean((2 * i_vals - 1) * (np.log(u_sorted + 1e-10) + 
                                                    np.log(1 - u_sorted[::-1] + 1e-10)))
    except:
        ks_stat, ks_pval, ad_stat = None, None, None
    
    result = GPDFitResult(
        threshold=threshold,
        threshold_percentile=threshold_pct,
        shape=shape,
        scale=scale,
        n_exceedances=n_exc,
        n_total=n_total,
        ad_statistic=ad_stat,
        ks_statistic=ks_stat,
        ks_pvalue=ks_pval,
        method=method
    )
    
    logger.info(f"GPD fit: xi={shape:.4f}, sigma={scale:.4f}")
    if ks_pval is not None:
        logger.info(f"KS test: stat={ks_stat:.4f}, p-value={ks_pval:.4f}")
    if ad_stat is not None:
        logger.info(f"AD statistic: {ad_stat:.4f}")
    
    # Log return period severities
    for rp in [10, 25, 50, 100, 200]:
        sev = result.severity_for_return_period(rp)
        logger.info(f"  {rp:3d}-year → {sev:.1%}")
    
    return result


def fit_gpd_constrained(exceedances: np.ndarray,
                        max_shape: float = 0.5,
                        data_max: float = None) -> Tuple[float, float]:
    """
    Fit GPD with constraints using constrained optimization.
    
    Constraints:
    1. Shape < max_shape (finite variance)
    2. CDF(data_max) ≤ 1 - 0.5/n (not too aggressive extrapolation)
    3. CDF(data_max) ≥ 1 - 1.5/n (not too conservative)
    
    Returns:
        (shape, scale)
    """
    n = len(exceedances)
    
    # Initial estimate using scipy
    try:
        c_init, _, scale_init = stats.genpareto.fit(exceedances, floc=0)
        c_init = np.clip(c_init, -0.5, max_shape - 0.01)
    except:
        c_init = 0.1
        scale_init = np.std(exceedances)
    
    # If no data_max constraint, just use scipy fit with shape bound
    if data_max is None:
        c, _, scale = stats.genpareto.fit(exceedances, floc=0)
        c = np.clip(c, -0.5, max_shape)
        return c, scale
    
    # Negative log-likelihood
    def neg_log_likelihood(params):
        c, log_scale = params
        scale = np.exp(log_scale)
        
        if scale <= 0:
            return 1e10
        
        # GPD log-likelihood
        if abs(c) < 1e-6:
            # Exponential case
            ll = -n * np.log(scale) - exceedances.sum() / scale
        else:
            z = exceedances / scale
            if c > 0:
                if np.any(z < 0):
                    return 1e10
                ll = -n * np.log(scale) - (1 + 1/c) * np.sum(np.log(1 + c * z))
            else:
                if np.any(1 + c * z <= 0):
                    return 1e10
                ll = -n * np.log(scale) - (1 + 1/c) * np.sum(np.log(1 + c * z))
        
        return -ll
    
    # Constraint: CDF(data_max) in [1-1.5/n, 1-0.5/n]
    def cdf_constraint_upper(params):
        c, log_scale = params
        scale = np.exp(log_scale)
        
        if abs(c) < 1e-6:
            F = 1 - np.exp(-data_max / scale)
        else:
            F = 1 - (1 + c * data_max / scale) ** (-1/c)
        
        # F <= 1 - 0.5/n  =>  1 - 0.5/n - F >= 0
        return (1 - 0.5/n) - F
    
    def cdf_constraint_lower(params):
        c, log_scale = params
        scale = np.exp(log_scale)
        
        if abs(c) < 1e-6:
            F = 1 - np.exp(-data_max / scale)
        else:
            z = data_max / scale
            if 1 + c * z <= 0:
                return -1  # Constraint violated
            F = 1 - (1 + c * z) ** (-1/c)
        
        # F >= 1 - 1.5/n  =>  F - (1 - 1.5/n) >= 0
        return F - (1 - 1.5/n)
    
    # Optimize
    x0 = [c_init, np.log(scale_init)]
    bounds = [(-0.5, max_shape), (np.log(1e-6), np.log(exceedances.max() * 10))]
    
    constraints = [
        {'type': 'ineq', 'fun': cdf_constraint_upper},
        {'type': 'ineq', 'fun': cdf_constraint_lower}
    ]
    
    try:
        result = minimize(
            neg_log_likelihood,
            x0,
            method='SLSQP',
            bounds=bounds,
            constraints=constraints,
            options={'maxiter': 1000}
        )
        
        if result.success:
            c, log_scale = result.x
            return c, np.exp(log_scale)
    except:
        pass
    
    # Fallback: unconstrained with bounds
    try:
        result = minimize(
            neg_log_likelihood,
            x0,
            method='L-BFGS-B',
            bounds=bounds
        )
        if result.success:
            c, log_scale = result.x
            return c, np.exp(log_scale)
    except:
        pass
    
    # Final fallback
    return c_init, scale_init


# =============================================================================
# GPD Sampling
# =============================================================================

def sample_from_gpd(gpd_fit: GPDFitResult, n_samples: int,
                    include_below_threshold: bool = True) -> np.ndarray:
    """
    Generate samples from fitted GPD distribution.
    
    If include_below_threshold, also samples from below threshold
    (using uniform distribution as approximation).
    """
    samples = []
    
    if include_below_threshold:
        # Proportion below threshold
        p_below = 1 - gpd_fit.exceedance_prob
        n_below = int(n_samples * p_below)
        n_above = n_samples - n_below
        
        # Below threshold: uniform from 0 to threshold
        below_samples = np.random.uniform(0, gpd_fit.threshold, n_below)
        samples.extend(below_samples)
    else:
        n_above = n_samples
    
    # Above threshold: GPD
    exceedances = stats.genpareto.rvs(
        gpd_fit.shape,
        loc=0,
        scale=gpd_fit.scale,
        size=n_above
    )
    above_samples = gpd_fit.threshold + exceedances
    samples.extend(above_samples)
    
    return np.array(samples)
