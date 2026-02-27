"""
GPD Diagnostic Statistics and Plots

Saves comprehensive diagnostics every time GPD is fitted:
1. Threshold selection analysis (all methods)
2. Parameter stability plots
3. Mean Residual Life plot
4. QQ plot
5. Fitted vs empirical tail comparison
6. Return level plot
7. Diagnostic statistics JSON
"""

import sys
from pathlib import Path
_script_dir = Path(__file__).resolve().parent
if str(_script_dir) not in sys.path:
    sys.path.insert(0, str(_script_dir))

import numpy as np
import json
import logging
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, asdict
from scipy import stats
import matplotlib
matplotlib.use('Agg')  # Non-interactive backend
import matplotlib.pyplot as plt

logger = logging.getLogger(__name__)


@dataclass
class ThresholdAnalysis:
    """Results from analyzing a single threshold."""
    percentile: float
    threshold: float
    n_exceedances: int
    shape: float
    scale: float
    shape_se: float  # Standard error
    scale_se: float
    ks_statistic: float
    ks_pvalue: float
    ad_statistic: float
    mean_excess: float  # E[X - u | X > u]


@dataclass
class GPDFitResult:
    """Results from a single GPD fit."""
    threshold: float
    threshold_percentile: float
    n_exceedances: int
    shape: float
    scale: float
    ks_statistic: float
    ks_pvalue: float
    ad_statistic: float
    return_periods: Dict[str, float]  # {"10": 0.69, "100": 3.63, ...}
    threshold_analyses: List[ThresholdAnalysis] = None  # Full analysis if available


@dataclass
class EmpiricalDistribution:
    """
    Smoothed empirical distribution for severity sampling.
    
    Properties:
    - Interpolated/smoothed CDF (monotonically increasing)
    - Capped at historical maximum (no extrapolation)
    - Proper density (monotonically decreasing in tail)
    """
    n_total: int
    data_min: float
    data_max: float  # Hard cap - no extrapolation beyond this
    
    # Smoothed CDF parameters (for inverse CDF sampling)
    cdf_x: List[float]  # Sorted unique severity values
    cdf_y: List[float]  # Corresponding CDF values (0 to 1)
    
    # Return periods (from smoothed distribution)
    return_periods: Dict[str, float]
    
    # Quality metrics
    smoothing_bandwidth: float = None
    ks_statistic: float = None  # KS test vs raw ECDF
    
    def sample(self, n: int, random_state: int = None) -> np.ndarray:
        """
        Sample from the smoothed empirical distribution using inverse CDF.
        
        Args:
            n: Number of samples
            random_state: Random seed
            
        Returns:
            Array of n severity samples, all <= data_max
        """
        rng = np.random.RandomState(random_state)
        u = rng.uniform(0, 1, n)
        
        # Inverse CDF via linear interpolation
        samples = np.interp(u, self.cdf_y, self.cdf_x)
        
        # Hard cap at historical maximum
        samples = np.minimum(samples, self.data_max)
        
        return samples
    
    def quantile(self, p: float) -> float:
        """
        Get quantile (inverse CDF) for probability p.
        
        Args:
            p: Probability (0 to 1)
            
        Returns:
            Severity value at that probability, capped at data_max
        """
        if p <= 0:
            return self.data_min
        if p >= 1:
            return self.data_max
        
        result = float(np.interp(p, self.cdf_y, self.cdf_x))
        return min(result, self.data_max)
    
    def cdf(self, x: float) -> float:
        """
        Get CDF value for severity x.
        
        Args:
            x: Severity value
            
        Returns:
            Probability P(X <= x)
        """
        if x <= self.data_min:
            return 0.0
        if x >= self.data_max:
            return 1.0
        
        return float(np.interp(x, self.cdf_x, self.cdf_y))
    
    def return_level(self, return_period: int) -> float:
        """
        Get severity for a given return period.
        
        Args:
            return_period: Return period in years (e.g., 100)
            
        Returns:
            Severity at that return period, capped at data_max
        """
        p = 1 - 1/return_period  # 100yr = 99th percentile
        return self.quantile(p)


def fit_empirical_distribution(
    data: np.ndarray,
    smoothing: str = 'linear',
    bandwidth: float = None
) -> EmpiricalDistribution:
    """
    Fit a smoothed empirical distribution to severity data.
    
    The distribution:
    - Is interpolated/smoothed for continuous sampling
    - Is capped at the historical maximum (no extrapolation)
    - Has monotonically increasing CDF
    - Has monotonically decreasing PDF (in the tail)
    
    Args:
        data: Array of historical severity values
        smoothing: Smoothing method - 'linear', 'cubic', or 'kde'
        bandwidth: KDE bandwidth (auto-selected if None)
    
    Returns:
        EmpiricalDistribution object
    """
    data = np.array(data)
    data = data[~np.isnan(data) & (data > 0)]
    data = np.sort(data)
    
    n = len(data)
    data_min = float(data[0])
    data_max = float(data[-1])
    
    if smoothing == 'kde':
        # Kernel density estimation with reflection at boundaries
        # This gives a smooth PDF but we need to integrate for CDF
        from scipy.stats import gaussian_kde
        
        # Reflect data at boundaries for better edge behavior
        reflected_data = np.concatenate([
            2*data_min - data[:n//10],  # Reflect at min
            data,
            2*data_max - data[-n//10:][::-1]  # Reflect at max
        ])
        
        if bandwidth is None:
            kde = gaussian_kde(reflected_data)
        else:
            kde = gaussian_kde(reflected_data, bw_method=bandwidth)
        
        # Create CDF by integrating PDF
        x_grid = np.linspace(data_min, data_max, 500)
        pdf_vals = kde(x_grid)
        
        # Normalize PDF to integrate to 1 over [data_min, data_max]
        dx = x_grid[1] - x_grid[0]
        total = np.sum(pdf_vals) * dx
        pdf_vals = pdf_vals / total
        
        # Integrate to get CDF
        cdf_vals = np.cumsum(pdf_vals) * dx
        cdf_vals = cdf_vals / cdf_vals[-1]  # Ensure ends at 1
        
        # Ensure monotonicity
        cdf_vals = np.maximum.accumulate(cdf_vals)
        
        cdf_x = x_grid.tolist()
        cdf_y = cdf_vals.tolist()
        smoothing_bw = float(kde.factor)
        
    elif smoothing == 'cubic':
        # Monotonic cubic spline interpolation
        from scipy.interpolate import PchipInterpolator
        
        # ECDF points
        ecdf_y = (np.arange(1, n + 1) - 0.5) / n  # Plotting positions
        
        # Remove duplicates by averaging y values
        unique_x, indices = np.unique(data, return_inverse=True)
        unique_y = np.zeros(len(unique_x))
        counts = np.zeros(len(unique_x))
        for i, idx in enumerate(indices):
            unique_y[idx] += ecdf_y[i]
            counts[idx] += 1
        unique_y = unique_y / counts
        
        # Fit monotonic cubic spline
        if len(unique_x) > 3:
            spline = PchipInterpolator(unique_x, unique_y)
            
            # Create fine grid
            x_grid = np.linspace(data_min, data_max, 500)
            cdf_vals = spline(x_grid)
            
            # Clip to [0, 1] and ensure monotonicity
            cdf_vals = np.clip(cdf_vals, 0, 1)
            cdf_vals = np.maximum.accumulate(cdf_vals)
            cdf_vals[-1] = 1.0  # Ensure ends at 1
            
            cdf_x = x_grid.tolist()
            cdf_y = cdf_vals.tolist()
        else:
            # Fall back to linear for small datasets
            cdf_x = data.tolist()
            cdf_y = ecdf_y.tolist()
        
        smoothing_bw = None
        
    else:  # linear (default)
        # Linear interpolation of ECDF - simplest, always monotonic
        ecdf_y = (np.arange(1, n + 1) - 0.5) / n  # Plotting positions
        
        # For linear, just use the sorted data points
        # Add endpoints to ensure full range
        cdf_x = [data_min] + data.tolist()
        cdf_y = [0.0] + ecdf_y.tolist()
        
        # Ensure strictly monotonic by removing duplicates
        unique_pairs = []
        prev_x = None
        for x, y in zip(cdf_x, cdf_y):
            if x != prev_x:
                unique_pairs.append((x, y))
                prev_x = x
        
        cdf_x = [p[0] for p in unique_pairs]
        cdf_y = [p[1] for p in unique_pairs]
        
        smoothing_bw = None
    
    # Compute return periods from the smoothed distribution
    return_periods = {}
    for rp in [10, 25, 50, 100, 200, 250, 500]:
        p = 1 - 1/rp
        if p <= cdf_y[-1]:  # Only if within data range
            sev = float(np.interp(p, cdf_y, cdf_x))
            sev = min(sev, data_max)  # Cap at max
            return_periods[str(rp)] = sev
        else:
            return_periods[str(rp)] = data_max  # Cap at historical max
    
    # KS test vs raw ECDF
    raw_ecdf_y = np.arange(1, n + 1) / n
    interp_at_data = np.interp(data, cdf_x, cdf_y)
    ks_stat = float(np.max(np.abs(interp_at_data - raw_ecdf_y)))
    
    return EmpiricalDistribution(
        n_total=n,
        data_min=data_min,
        data_max=data_max,
        cdf_x=cdf_x,
        cdf_y=cdf_y,
        return_periods=return_periods,
        smoothing_bandwidth=smoothing_bw,
        ks_statistic=ks_stat
    )


@dataclass 
class GPDDiagnostics:
    """Complete diagnostics for GPD fitting with multiple severity modes."""
    # Data summary
    n_total: int
    data_min: float
    data_max: float
    data_mean: float
    data_median: float
    data_std: float
    data_skewness: float
    data_kurtosis: float
    
    # Percentiles
    percentiles: Dict[str, float]  # {10: value, 25: value, ...}
    
    # Warnings
    warnings: List[str]
    
    # =========================================================================
    # FOUR SEVERITY MODES
    # =========================================================================
    
    # 1. CONSTRAINED (xi < 0.5) - default, conservative
    constrained: GPDFitResult = None
    
    # 2. UNCONSTRAINED (MLE, no shape limit)
    unconstrained: GPDFitResult = None
    
    # 3. UNCONSTRAINED WITH MAX REMOVED (robustness check)
    unconstrained_no_max: GPDFitResult = None
    max_value_removed: float = None  # The removed value
    
    # 4. EMPIRICAL - smoothed empirical distribution (capped at historical max)
    empirical: EmpiricalDistribution = None
    empirical_return_periods: Dict[str, float] = None  # For backward compatibility
    
    # =========================================================================
    # RECOMMENDATION
    # =========================================================================
    recommended_mode: str = None  # 'constrained', 'unconstrained', 'unconstrained_no_max', 'empirical'
    recommendation_reason: str = None
    recommendation_scores: Dict[str, Dict[str, float]] = None  # Scores for each mode
    
    # Legacy fields for backward compatibility
    @property
    def selected_percentile(self):
        return self.constrained.threshold_percentile if self.constrained else None
    
    @property
    def selected_threshold(self):
        return self.constrained.threshold if self.constrained else None
    
    @property
    def final_shape(self):
        return self.constrained.shape if self.constrained else None
    
    @property
    def final_scale(self):
        return self.constrained.scale if self.constrained else None
    
    @property
    def final_n_exceedances(self):
        return self.constrained.n_exceedances if self.constrained else None
    
    @property
    def ks_statistic(self):
        return self.constrained.ks_statistic if self.constrained else None
    
    @property
    def ks_pvalue(self):
        return self.constrained.ks_pvalue if self.constrained else None
    
    @property
    def ad_statistic(self):
        return self.constrained.ad_statistic if self.constrained else None
    
    @property
    def return_period_severities(self):
        return self.constrained.return_periods if self.constrained else None
    
    @property
    def threshold_analyses(self):
        return self.constrained.threshold_analyses if self.constrained else None
    
    @property
    def selection_method(self):
        return "consensus"
    
    @property
    def selection_scores(self):
        return {}
    
    # Unconstrained legacy
    @property
    def unconstrained_threshold(self):
        return self.unconstrained.threshold if self.unconstrained else None
    
    @property
    def unconstrained_threshold_percentile(self):
        return self.unconstrained.threshold_percentile if self.unconstrained else None
    
    @property
    def unconstrained_shape(self):
        return self.unconstrained.shape if self.unconstrained else None
    
    @property
    def unconstrained_scale(self):
        return self.unconstrained.scale if self.unconstrained else None
    
    @property
    def unconstrained_n_exceedances(self):
        return self.unconstrained.n_exceedances if self.unconstrained else None
    
    @property
    def unconstrained_ks_pvalue(self):
        return self.unconstrained.ks_pvalue if self.unconstrained else None
    
    @property
    def unconstrained_ad_statistic(self):
        return self.unconstrained.ad_statistic if self.unconstrained else None
    
    @property
    def unconstrained_return_periods(self):
        return self.unconstrained.return_periods if self.unconstrained else None
    
    @property
    def unconstrained_threshold_analyses(self):
        return self.unconstrained.threshold_analyses if self.unconstrained else None


def _fit_gpd_at_threshold(data: np.ndarray, threshold: float, shape_cap: float = None) -> dict:
    """Fit GPD at a specific threshold with optional shape constraint."""
    exceedances = data[data > threshold] - threshold
    n_exc = len(exceedances)
    
    if n_exc < 10:
        return None
    
    try:
        c, _, scale = stats.genpareto.fit(exceedances, floc=0)
        shape = min(c, shape_cap) if shape_cap is not None else c
        
        # Goodness of fit
        ks_stat, ks_p = stats.kstest(exceedances, 'genpareto', args=(shape, 0, scale))
        
        # Anderson-Darling
        sorted_exc = np.sort(exceedances)
        n = len(sorted_exc)
        cdf_vals = stats.genpareto.cdf(sorted_exc, shape, loc=0, scale=scale)
        cdf_vals = np.clip(cdf_vals, 1e-10, 1 - 1e-10)
        i = np.arange(1, n + 1)
        ad_stat = -n - np.sum((2*i - 1) * (np.log(cdf_vals) + np.log(1 - cdf_vals[::-1]))) / n
        
        return {
            'shape': float(shape),
            'scale': float(scale),
            'n_exceedances': n_exc,
            'ks_statistic': float(ks_stat),
            'ks_pvalue': float(ks_p),
            'ad_statistic': float(ad_stat)
        }
    except:
        return None


def _compute_return_periods(threshold: float, shape: float, scale: float, 
                           n_exceedances: int, n_total: int) -> Dict[str, float]:
    """Compute return period severities for a GPD fit."""
    rp_severities = {}
    exceedance_prob = n_exceedances / n_total
    
    for rp in [10, 25, 50, 100, 200, 250, 500]:
        p_exceed = 1 / rp
        if p_exceed > exceedance_prob:
            sev = threshold * (p_exceed / exceedance_prob)
        else:
            p_cond = p_exceed / exceedance_prob
            if abs(shape) < 1e-6:
                exc = -scale * np.log(p_cond)
            else:
                exc = (scale / shape) * (p_cond**(-shape) - 1)
            sev = threshold + exc
        rp_severities[str(rp)] = float(sev)
    
    return rp_severities


def _fit_gpd_mode(data: np.ndarray, percentile_range: Tuple[float, float], 
                  n_thresholds: int, shape_cap: float = None, 
                  mode_name: str = "unknown") -> Optional[GPDFitResult]:
    """
    Fit GPD with its own optimal threshold selection.
    
    Args:
        data: Severity data
        percentile_range: Range of percentiles to test
        n_thresholds: Number of thresholds to test
        shape_cap: Optional maximum shape parameter
        mode_name: Name of the mode for logging
    
    Returns:
        GPDFitResult or None if fitting fails
    """
    n_total = len(data)
    
    # Analyze across thresholds
    percentiles = np.linspace(percentile_range[0], percentile_range[1], n_thresholds)
    analyses = []
    
    for pct in percentiles:
        threshold = np.percentile(data, pct)
        exceedances = data[data > threshold] - threshold
        n_exc = len(exceedances)
        
        if n_exc < 10:
            continue
        
        try:
            c, _, scale = stats.genpareto.fit(exceedances, floc=0)
            shape = min(c, shape_cap) if shape_cap is not None else c
            
            # Standard errors (approximate)
            shape_se = abs(shape) * np.sqrt(2 / n_exc) if n_exc > 2 else np.nan
            scale_se = scale * np.sqrt(2 / n_exc) if n_exc > 2 else np.nan
            
            # Goodness of fit
            ks_stat, ks_p = stats.kstest(exceedances, 'genpareto', args=(shape, 0, scale))
            
            # Anderson-Darling
            sorted_exc = np.sort(exceedances)
            n = len(sorted_exc)
            cdf_vals = stats.genpareto.cdf(sorted_exc, shape, loc=0, scale=scale)
            cdf_vals = np.clip(cdf_vals, 1e-10, 1 - 1e-10)
            i = np.arange(1, n + 1)
            ad_stat = -n - np.sum((2*i - 1) * (np.log(cdf_vals) + np.log(1 - cdf_vals[::-1]))) / n
            
            mean_excess = np.mean(exceedances)
            
            analyses.append(ThresholdAnalysis(
                percentile=float(pct),
                threshold=float(threshold),
                n_exceedances=n_exc,
                shape=float(shape),
                scale=float(scale),
                shape_se=float(shape_se),
                scale_se=float(scale_se),
                ks_statistic=float(ks_stat),
                ks_pvalue=float(ks_p),
                ad_statistic=float(ad_stat),
                mean_excess=float(mean_excess)
            ))
            
        except Exception as e:
            logger.debug(f"GPD fit failed at {pct}th percentile ({mode_name}): {e}")
            continue
    
    if len(analyses) < 3:
        logger.warning(f"Too few valid threshold fits for {mode_name}")
        return None
    
    # Select best threshold using consensus method
    selection_scores = _compute_threshold_scores(analyses, data)
    best_pct = _select_threshold_consensus(selection_scores, analyses)
    
    # Get best analysis
    best_analysis = None
    for ta in analyses:
        if abs(ta.percentile - best_pct) < 1:
            best_analysis = ta
            break
    
    if best_analysis is None:
        # Fallback to 85th percentile
        best_pct = 85.0
        threshold = np.percentile(data, 85)
        fit = _fit_gpd_at_threshold(data, threshold, shape_cap)
        if fit is None:
            return None
        
        return_periods = _compute_return_periods(
            threshold, fit['shape'], fit['scale'], 
            fit['n_exceedances'], n_total
        )
        
        return GPDFitResult(
            threshold=float(threshold),
            threshold_percentile=float(best_pct),
            n_exceedances=fit['n_exceedances'],
            shape=fit['shape'],
            scale=fit['scale'],
            ks_statistic=fit['ks_statistic'],
            ks_pvalue=fit['ks_pvalue'],
            ad_statistic=fit['ad_statistic'],
            return_periods=return_periods,
            threshold_analyses=analyses
        )
    
    # Compute return periods
    return_periods = _compute_return_periods(
        best_analysis.threshold, best_analysis.shape, best_analysis.scale,
        best_analysis.n_exceedances, n_total
    )
    
    return GPDFitResult(
        threshold=best_analysis.threshold,
        threshold_percentile=best_analysis.percentile,
        n_exceedances=best_analysis.n_exceedances,
        shape=best_analysis.shape,
        scale=best_analysis.scale,
        ks_statistic=best_analysis.ks_statistic,
        ks_pvalue=best_analysis.ks_pvalue,
        ad_statistic=best_analysis.ad_statistic,
        return_periods=return_periods,
        threshold_analyses=analyses
    )


def _compute_recommendation(constrained: GPDFitResult, unconstrained: GPDFitResult,
                           unconstrained_no_max: GPDFitResult, 
                           empirical_dist: EmpiricalDistribution,
                           data_max: float) -> Tuple[str, str, Dict]:
    """
    Recommend which severity mode to use based on fit quality and consistency.
    
    Returns:
        (recommended_mode, reason, scores_dict)
    """
    scores = {
        'constrained': {'ks_pvalue': 0, 'ad_score': 0, 'empirical_match': 0, 'extrapolation': 0, 'total': 0},
        'unconstrained': {'ks_pvalue': 0, 'ad_score': 0, 'empirical_match': 0, 'extrapolation': 0, 'total': 0},
        'unconstrained_no_max': {'ks_pvalue': 0, 'ad_score': 0, 'empirical_match': 0, 'extrapolation': 0, 'total': 0},
        'empirical': {'ks_pvalue': 0, 'ad_score': 0, 'empirical_match': 30, 'extrapolation': 0, 'total': 0}  # Perfect match to itself
    }
    
    gpd_modes = {
        'constrained': constrained,
        'unconstrained': unconstrained,
        'unconstrained_no_max': unconstrained_no_max
    }
    
    # Get empirical return periods for comparison
    emp_rp = empirical_dist.return_periods if empirical_dist else {}
    
    # Score each GPD mode
    for mode_name, fit in gpd_modes.items():
        if fit is None:
            continue
        
        # KS p-value score (higher is better, max 30 points)
        scores[mode_name]['ks_pvalue'] = min(30, fit.ks_pvalue * 30)
        
        # AD statistic score (lower is better, max 20 points)
        # AD < 1 is good, AD > 3 is bad
        ad_score = max(0, 20 - (fit.ad_statistic - 1) * 6.67)
        scores[mode_name]['ad_score'] = max(0, min(20, ad_score))
        
        # Empirical match score (max 30 points)
        # Compare 10yr and 25yr return periods with empirical (observable range)
        emp_match_score = 0
        for rp in ['10', '25']:
            emp = emp_rp.get(rp)
            fitted = fit.return_periods.get(rp)
            if emp and fitted and emp > 0:
                ratio = fitted / emp
                # Perfect match = 15 points, >2x or <0.5x = 0 points
                if 0.8 <= ratio <= 1.2:
                    emp_match_score += 15
                elif 0.5 <= ratio <= 2.0:
                    emp_match_score += 15 * (1 - abs(ratio - 1) / 0.8)
        scores[mode_name]['empirical_match'] = max(0, emp_match_score)
        
        # Extrapolation capability bonus (max 20 points)
        # GPD can extrapolate beyond data, empirical cannot
        scores[mode_name]['extrapolation'] = 20
        
        # Total
        scores[mode_name]['total'] = (
            scores[mode_name]['ks_pvalue'] + 
            scores[mode_name]['ad_score'] + 
            scores[mode_name]['empirical_match'] +
            scores[mode_name]['extrapolation']
        )
    
    # Score empirical mode
    # Empirical gets perfect empirical match but no extrapolation
    scores['empirical']['ks_pvalue'] = 25  # Smoothed empirical fits data well by definition
    scores['empirical']['ad_score'] = 15   # Reasonable fit
    scores['empirical']['empirical_match'] = 30  # Perfect match to itself
    scores['empirical']['extrapolation'] = 0  # Cannot extrapolate beyond data
    scores['empirical']['total'] = 70  # Baseline score
    
    # Empirical is preferred when:
    # 1. All GPD fits are poor (low KS p-values)
    # 2. User wants conservative estimates (no extrapolation risk)
    # 3. Data is sufficient for rare events (n > 500)
    
    if empirical_dist and empirical_dist.n_total >= 500:
        scores['empirical']['total'] += 10  # Bonus for large sample
    
    # Find best mode
    best_mode = max(scores.keys(), key=lambda m: scores[m]['total'])
    
    # Generate reason
    reasons = []
    
    if best_mode == 'constrained':
        reasons.append("Constrained fit provides stable extrapolation")
        if constrained and constrained.ks_pvalue > 0.1:
            reasons.append(f"Good KS p-value ({constrained.ks_pvalue:.3f})")
    elif best_mode == 'unconstrained':
        reasons.append("Unconstrained fit better captures tail behavior")
        if constrained and unconstrained:
            if scores['unconstrained']['empirical_match'] > scores['constrained']['empirical_match']:
                reasons.append("Better match to empirical return periods")
    elif best_mode == 'unconstrained_no_max':
        reasons.append("Max value may be outlier - fit without max is more robust")
        if unconstrained and unconstrained_no_max:
            shape_diff = unconstrained.shape - unconstrained_no_max.shape
            if abs(shape_diff) > 0.1:
                reasons.append(f"Shape changes by {shape_diff:.3f} without max value")
    else:  # empirical
        reasons.append("Empirical distribution recommended - no extrapolation beyond observed data")
        if empirical_dist:
            reasons.append(f"Capped at historical max ({empirical_dist.data_max:.1%})")
            if empirical_dist.n_total >= 500:
                reasons.append(f"Large sample ({empirical_dist.n_total} obs) supports empirical approach")
    
    # Add warnings about shape constraints
    if unconstrained and constrained:
        shape_diff = unconstrained.shape - constrained.shape
        if shape_diff > 0.2:
            reasons.append(f"WARNING: Large shape difference ({shape_diff:.3f}) - constraint may be too restrictive")
    
    reason = "; ".join(reasons)
    
    return best_mode, reason, scores


def compute_gpd_diagnostics(
    data: np.ndarray,
    percentile_range: Tuple[float, float] = (80, 99),
    n_thresholds: int = 30,
    max_shape: float = 0.5
) -> GPDDiagnostics:
    """
    Compute comprehensive GPD diagnostics with all four severity modes.
    
    Args:
        data: Array of severity values
        percentile_range: Range of percentiles to test for threshold
        n_thresholds: Number of thresholds to test
        max_shape: Maximum allowed shape parameter for constrained fit
    
    Returns:
        GPDDiagnostics with complete analysis of all 4 modes
    """
    data = np.array(data)
    data = data[~np.isnan(data) & (data > 0)]  # Clean data
    
    warnings = []
    
    # Data summary
    n_total = len(data)
    if n_total < 50:
        warnings.append(f"Small sample size ({n_total}), GPD fit may be unreliable")
    
    # Percentiles
    pct_values = {}
    for p in [5, 10, 25, 50, 75, 90, 95, 99, 99.5]:
        pct_values[str(p)] = float(np.percentile(data, p))
    
    # Check for extreme outliers
    p99 = np.percentile(data, 99)
    p95 = np.percentile(data, 95)
    max_val = np.max(data)
    
    if max_val > 3 * p99:
        warnings.append(f"Extreme outlier detected: max ({max_val:.1%}) is >{3:.0f}x the 99th percentile ({p99:.1%})")
    
    if p99 > 5 * p95:
        warnings.append(f"Heavy tail: 99th percentile ({p99:.1%}) is >{5:.0f}x the 95th ({p95:.1%})")
    
    # =========================================================================
    # FIT ALL 4 MODES
    # =========================================================================
    
    # 1. CONSTRAINED (xi < max_shape)
    logger.info("Fitting constrained GPD (xi < 0.5)...")
    constrained_fit = _fit_gpd_mode(
        data, percentile_range, n_thresholds, 
        shape_cap=max_shape, mode_name="constrained"
    )
    
    if constrained_fit and constrained_fit.shape >= max_shape - 0.01:
        warnings.append(f"Constrained shape hit limit ({constrained_fit.shape:.3f} ~ {max_shape})")
    
    # 2. UNCONSTRAINED (no shape limit)
    logger.info("Fitting unconstrained GPD...")
    unconstrained_fit = _fit_gpd_mode(
        data, percentile_range, n_thresholds,
        shape_cap=None, mode_name="unconstrained"
    )
    
    if unconstrained_fit and unconstrained_fit.shape > max_shape + 0.1:
        warnings.append(f"Unconstrained shape ({unconstrained_fit.shape:.3f}) exceeds constraint")
    
    # 3. UNCONSTRAINED WITH MAX REMOVED
    logger.info("Fitting unconstrained GPD with max removed...")
    data_no_max = data[data < max_val]
    second_max = np.max(data_no_max) if len(data_no_max) > 0 else max_val
    
    unconstrained_no_max_fit = _fit_gpd_mode(
        data_no_max, percentile_range, n_thresholds,
        shape_cap=None, mode_name="unconstrained_no_max"
    )
    
    if unconstrained_fit and unconstrained_no_max_fit:
        shape_change = unconstrained_fit.shape - unconstrained_no_max_fit.shape
        if abs(shape_change) > 0.1:
            warnings.append(f"Removing max changes shape by {shape_change:.3f} - max may be outlier")
    
    # 4. EMPIRICAL - smoothed empirical distribution (capped at historical max)
    logger.info("Fitting smoothed empirical distribution...")
    empirical_dist = fit_empirical_distribution(data, smoothing='linear')
    
    # Also compute raw percentile-based return periods for backward compatibility
    rp_severities_emp = empirical_dist.return_periods.copy()
    
    # Add note about empirical limitations
    if n_total < 200:
        warnings.append(f"Empirical distribution based on only {n_total} observations - high uncertainty for rare events")
    
    # =========================================================================
    # COMPUTE RECOMMENDATION
    # =========================================================================
    recommended_mode, recommendation_reason, recommendation_scores = _compute_recommendation(
        constrained_fit, unconstrained_fit, unconstrained_no_max_fit,
        empirical_dist, max_val
    )
    
    logger.info(f"Recommended mode: {recommended_mode}")
    
    # =========================================================================
    # BUILD DIAGNOSTICS OBJECT
    # =========================================================================
    return GPDDiagnostics(
        n_total=n_total,
        data_min=float(np.min(data)),
        data_max=float(max_val),
        data_mean=float(np.mean(data)),
        data_median=float(np.median(data)),
        data_std=float(np.std(data)),
        data_skewness=float(stats.skew(data)),
        data_kurtosis=float(stats.kurtosis(data)),
        percentiles=pct_values,
        warnings=warnings,
        constrained=constrained_fit,
        unconstrained=unconstrained_fit,
        unconstrained_no_max=unconstrained_no_max_fit,
        max_value_removed=float(max_val),
        empirical=empirical_dist,
        empirical_return_periods=rp_severities_emp,
        recommended_mode=recommended_mode,
        recommendation_reason=recommendation_reason,
        recommendation_scores=recommendation_scores
    )


def _compute_threshold_scores(
    analyses: List[ThresholdAnalysis],
    data: np.ndarray
) -> Dict[str, float]:
    """Compute threshold selection scores from each method."""
    if len(analyses) < 3:
        return {}
    
    percentiles = [a.percentile for a in analyses]
    shapes = [a.shape for a in analyses]
    scales = [a.scale for a in analyses]
    mean_excesses = [a.mean_excess for a in analyses]
    ad_stats = [a.ad_statistic for a in analyses]
    ks_pvals = [a.ks_pvalue for a in analyses]
    
    scores = {}
    
    # Method 1: Shape stability (look for plateau)
    shape_diffs = np.abs(np.diff(shapes))
    smoothed_diffs = np.convolve(shape_diffs, np.ones(3)/3, mode='valid')
    if len(smoothed_diffs) > 0:
        stable_idx = np.argmin(smoothed_diffs)
        scores['shape_stability'] = percentiles[stable_idx + 1]
    
    # Method 2: Scale stability
    # Modified scale: σ* = σ - ξu should be constant
    mod_scales = [a.scale - a.shape * a.threshold for a in analyses]
    scale_diffs = np.abs(np.diff(mod_scales))
    if len(scale_diffs) > 2:
        smoothed = np.convolve(scale_diffs, np.ones(3)/3, mode='valid')
        stable_idx = np.argmin(smoothed)
        scores['scale_stability'] = percentiles[stable_idx + 1]
    
    # Method 3: Mean excess linearity
    # E[X-u | X>u] should be linear in u for GPD
    # Look for where linearity starts
    if len(mean_excesses) > 5:
        # Fit line to last portion
        for start_idx in range(len(mean_excesses) - 5):
            subset_pct = percentiles[start_idx:]
            subset_me = mean_excesses[start_idx:]
            slope, intercept, r, _, _ = stats.linregress(subset_pct, subset_me)
            if r**2 > 0.9:  # Good linear fit
                scores['mean_excess'] = percentiles[start_idx]
                break
    
    # Method 4: Anderson-Darling minimum
    if len(ad_stats) > 0:
        min_ad_idx = np.argmin(ad_stats)
        scores['ad_minimum'] = percentiles[min_ad_idx]
    
    # Method 5: KS p-value maximum
    if len(ks_pvals) > 0:
        max_ks_idx = np.argmax(ks_pvals)
        scores['ks_maximum'] = percentiles[max_ks_idx]
    
    return scores


def _select_threshold_consensus(
    scores: Dict[str, float],
    analyses: List[ThresholdAnalysis]
) -> float:
    """Select threshold using weighted consensus of methods."""
    if not scores:
        return 80.0  # Default
    
    # Weight methods
    weights = {
        'shape_stability': 1.5,
        'scale_stability': 1.0,
        'mean_excess': 1.0,
        'ad_minimum': 1.5,
        'ks_maximum': 1.0
    }
    
    weighted_sum = 0.0
    total_weight = 0.0
    
    for method, pct in scores.items():
        w = weights.get(method, 1.0)
        weighted_sum += w * pct
        total_weight += w
    
    consensus = weighted_sum / total_weight if total_weight > 0 else 80.0
    
    # Round to nearest analyzed percentile
    if analyses:
        available = [a.percentile for a in analyses]
        closest = min(available, key=lambda x: abs(x - consensus))
        return closest
    
    return consensus


def plot_gpd_diagnostics(
    data: np.ndarray,
    diagnostics: GPDDiagnostics,
    output_dir: Path,
    prefix: str = "gpd"
) -> List[Path]:
    """
    Generate and save all GPD diagnostic plots.
    
    Returns list of saved file paths.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    saved_files = []
    
    data = np.array(data)
    data = data[~np.isnan(data) & (data > 0)]
    
    # 1. Data histogram with threshold
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.hist(data, bins=50, density=True, alpha=0.7, label='Data')
    ax.axvline(diagnostics.selected_threshold, color='r', linestyle='--', 
               linewidth=2, label=f'Threshold ({diagnostics.selected_percentile:.0f}th pct)')
    ax.axvline(diagnostics.data_max, color='orange', linestyle=':', 
               linewidth=2, label=f'Max ({diagnostics.data_max:.1%})')
    ax.set_xlabel('Severity')
    ax.set_ylabel('Density')
    ax.set_title('Severity Distribution with GPD Threshold')
    ax.legend()
    ax.set_xlim(0, min(diagnostics.data_max * 1.1, np.percentile(data, 99.5) * 2))
    
    path = output_dir / f"{prefix}_01_histogram.png"
    fig.savefig(path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    saved_files.append(path)
    
    # 2. Parameter stability plots
    if diagnostics.threshold_analyses:
        fig, axes = plt.subplots(2, 2, figsize=(12, 10))
        
        pcts = [a.percentile for a in diagnostics.threshold_analyses]
        shapes = [a.shape for a in diagnostics.threshold_analyses]
        scales = [a.scale for a in diagnostics.threshold_analyses]
        shape_ses = [a.shape_se for a in diagnostics.threshold_analyses]
        scale_ses = [a.scale_se for a in diagnostics.threshold_analyses]
        
        # Shape vs threshold
        ax = axes[0, 0]
        ax.errorbar(pcts, shapes, yerr=shape_ses, fmt='o-', capsize=3, alpha=0.7)
        ax.axvline(diagnostics.selected_percentile, color='r', linestyle='--', 
                   label=f'Selected ({diagnostics.selected_percentile:.0f}th)')
        ax.axhline(0.5, color='orange', linestyle=':', label='Max shape (0.5)')
        ax.set_xlabel('Threshold Percentile')
        ax.set_ylabel('Shape (ξ)')
        ax.set_title('Shape Parameter Stability')
        ax.legend()
        ax.grid(True, alpha=0.3)
        
        # Scale vs threshold
        ax = axes[0, 1]
        ax.errorbar(pcts, scales, yerr=scale_ses, fmt='o-', capsize=3, alpha=0.7)
        ax.axvline(diagnostics.selected_percentile, color='r', linestyle='--')
        ax.set_xlabel('Threshold Percentile')
        ax.set_ylabel('Scale (σ)')
        ax.set_title('Scale Parameter Stability')
        ax.grid(True, alpha=0.3)
        
        # Modified scale (should be constant)
        ax = axes[1, 0]
        mod_scales = [a.scale - a.shape * a.threshold for a in diagnostics.threshold_analyses]
        ax.plot(pcts, mod_scales, 'o-', alpha=0.7)
        ax.axvline(diagnostics.selected_percentile, color='r', linestyle='--')
        ax.set_xlabel('Threshold Percentile')
        ax.set_ylabel('σ - ξu (modified scale)')
        ax.set_title('Modified Scale (should be constant for good fit)')
        ax.grid(True, alpha=0.3)
        
        # AD statistic vs threshold
        ax = axes[1, 1]
        ad_stats = [a.ad_statistic for a in diagnostics.threshold_analyses]
        ax.plot(pcts, ad_stats, 'o-', alpha=0.7)
        ax.axvline(diagnostics.selected_percentile, color='r', linestyle='--')
        ax.axhline(2.5, color='orange', linestyle=':', label='Threshold (2.5)')
        ax.set_xlabel('Threshold Percentile')
        ax.set_ylabel('Anderson-Darling Statistic')
        ax.set_title('Goodness-of-Fit vs Threshold')
        ax.legend()
        ax.grid(True, alpha=0.3)
        
        plt.tight_layout()
        path = output_dir / f"{prefix}_02_parameter_stability.png"
        fig.savefig(path, dpi=150, bbox_inches='tight')
        plt.close(fig)
        saved_files.append(path)
    
    # 3. Mean Residual Life plot
    fig, ax = plt.subplots(figsize=(10, 6))
    
    sorted_data = np.sort(data)
    thresholds = sorted_data[:-10]  # Leave at least 10 exceedances
    mean_excesses = []
    
    for u in thresholds[::max(1, len(thresholds)//100)]:  # Sample for speed
        exceedances = data[data > u] - u
        if len(exceedances) >= 5:
            mean_excesses.append((u, np.mean(exceedances)))
    
    if mean_excesses:
        us, mes = zip(*mean_excesses)
        ax.plot(us, mes, 'o', alpha=0.5, markersize=3)
        ax.axvline(diagnostics.selected_threshold, color='r', linestyle='--', 
                   label=f'Selected threshold')
        
        # Fit line above threshold
        above_thresh = [(u, m) for u, m in mean_excesses if u >= diagnostics.selected_threshold]
        if len(above_thresh) > 2:
            us_above, mes_above = zip(*above_thresh)
            slope, intercept, r, _, _ = stats.linregress(us_above, mes_above)
            x_line = np.array([min(us_above), max(us_above)])
            ax.plot(x_line, intercept + slope * x_line, 'g--', 
                    label=f'Linear fit (R²={r**2:.3f})')
    
    ax.set_xlabel('Threshold')
    ax.set_ylabel('Mean Excess')
    ax.set_title('Mean Residual Life Plot\n(should be linear above threshold for GPD)')
    ax.legend()
    ax.grid(True, alpha=0.3)
    
    path = output_dir / f"{prefix}_03_mean_residual_life.png"
    fig.savefig(path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    saved_files.append(path)
    
    # 4. QQ plot
    fig, ax = plt.subplots(figsize=(8, 8))
    
    exceedances = data[data > diagnostics.selected_threshold] - diagnostics.selected_threshold
    sorted_exc = np.sort(exceedances)
    n = len(sorted_exc)
    
    # Theoretical quantiles
    probs = (np.arange(1, n + 1) - 0.5) / n
    theoretical = stats.genpareto.ppf(probs, diagnostics.final_shape, 
                                       loc=0, scale=diagnostics.final_scale)
    
    ax.scatter(theoretical, sorted_exc, alpha=0.5, s=20)
    
    # 45-degree line
    max_val = max(max(theoretical), max(sorted_exc))
    ax.plot([0, max_val], [0, max_val], 'r--', label='Perfect fit')
    
    ax.set_xlabel('Theoretical Quantiles (GPD)')
    ax.set_ylabel('Empirical Quantiles')
    ax.set_title(f'QQ Plot of Exceedances\n(ξ={diagnostics.final_shape:.3f}, σ={diagnostics.final_scale:.3f})')
    ax.legend()
    ax.grid(True, alpha=0.3)
    ax.set_aspect('equal')
    
    path = output_dir / f"{prefix}_04_qq_plot.png"
    fig.savefig(path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    saved_files.append(path)
    
    # 5. Tail comparison (empirical vs fitted)
    fig, ax = plt.subplots(figsize=(10, 6))
    
    # Empirical survival function
    sorted_data = np.sort(data)[::-1]  # Descending
    n_total = len(sorted_data)
    empirical_probs = np.arange(1, n_total + 1) / n_total
    
    ax.semilogy(sorted_data, empirical_probs, 'b-', linewidth=1.5, label='Empirical')
    
    # Fitted GPD survival
    x_range = np.linspace(diagnostics.selected_threshold, sorted_data[0] * 1.2, 200)
    exc_prob = diagnostics.final_n_exceedances / n_total
    gpd_survival = exc_prob * (1 - stats.genpareto.cdf(
        x_range - diagnostics.selected_threshold,
        diagnostics.final_shape,
        loc=0,
        scale=diagnostics.final_scale
    ))
    
    ax.semilogy(x_range, gpd_survival, 'r--', linewidth=2, label='GPD fit')
    
    # Mark return periods
    for rp, sev in diagnostics.return_period_severities.items():
        if float(rp) in [10, 50, 100, 200]:
            ax.axhline(1/float(rp), color='gray', linestyle=':', alpha=0.5)
            ax.axvline(sev, color='gray', linestyle=':', alpha=0.5)
            ax.annotate(f'{rp}yr', xy=(sev, 1/float(rp)), fontsize=8)
    
    ax.set_xlabel('Severity')
    ax.set_ylabel('Exceedance Probability')
    ax.set_title('Tail Comparison: Empirical vs GPD')
    ax.legend()
    ax.grid(True, alpha=0.3)
    
    path = output_dir / f"{prefix}_05_tail_comparison.png"
    fig.savefig(path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    saved_files.append(path)
    
    # 6. Return level plot
    fig, ax = plt.subplots(figsize=(10, 6))
    
    return_periods = [2, 5, 10, 25, 50, 100, 200, 500]
    return_levels = [diagnostics.return_period_severities.get(str(rp), np.nan) 
                     for rp in return_periods]
    
    ax.semilogx(return_periods, [r * 100 for r in return_levels], 'bo-', 
                linewidth=2, markersize=8, label='GPD estimate')
    
    # Add empirical estimates where possible
    emp_return_levels = []
    for rp in return_periods:
        pct = 100 * (1 - 1/rp)
        if pct <= 99.5:  # Only if we have enough data
            emp_return_levels.append(np.percentile(data, pct))
        else:
            emp_return_levels.append(np.nan)
    
    valid_mask = ~np.isnan(emp_return_levels)
    ax.semilogx(np.array(return_periods)[valid_mask], 
                [r * 100 for r in np.array(emp_return_levels)[valid_mask]], 
                'g^', markersize=10, label='Empirical')
    
    ax.set_xlabel('Return Period (years)')
    ax.set_ylabel('Severity (%)')
    ax.set_title('Return Level Plot')
    ax.legend()
    ax.grid(True, alpha=0.3)
    
    path = output_dir / f"{prefix}_06_return_levels.png"
    fig.savefig(path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    saved_files.append(path)
    
    # 7. Summary panel
    fig, axes = plt.subplots(2, 3, figsize=(15, 10))
    
    # Text summary
    ax = axes[0, 0]
    ax.axis('off')
    
    summary_text = f"""GPD FIT SUMMARY
    
Data: n={diagnostics.n_total}, range=[{diagnostics.data_min:.1%}, {diagnostics.data_max:.1%}]
Mean: {diagnostics.data_mean:.1%}, Median: {diagnostics.data_median:.1%}
Skewness: {diagnostics.data_skewness:.2f}, Kurtosis: {diagnostics.data_kurtosis:.2f}

Threshold: {diagnostics.selected_threshold:.1%} ({diagnostics.selected_percentile:.0f}th percentile)
Exceedances: {diagnostics.final_n_exceedances}

GPD Parameters:
  Shape (ξ): {diagnostics.final_shape:.4f}
  Scale (σ): {diagnostics.final_scale:.4f}

Fit Quality:
  KS statistic: {diagnostics.ks_statistic:.4f} (p={diagnostics.ks_pvalue:.4f})
  AD statistic: {diagnostics.ad_statistic:.2f}

Return Periods:
  10yr:  {diagnostics.return_period_severities.get('10', 0):.1%}
  50yr:  {diagnostics.return_period_severities.get('50', 0):.1%}
  100yr: {diagnostics.return_period_severities.get('100', 0):.1%}
  200yr: {diagnostics.return_period_severities.get('200', 0):.1%}
"""
    
    if diagnostics.warnings:
        summary_text += "\nWARNINGS:\n"
        for w in diagnostics.warnings:
            summary_text += f"  • {w}\n"
    
    ax.text(0.05, 0.95, summary_text, transform=ax.transAxes, 
            fontsize=9, verticalalignment='top', fontfamily='monospace',
            bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))
    
    # Mini versions of key plots
    # Histogram
    ax = axes[0, 1]
    ax.hist(data, bins=30, density=True, alpha=0.7)
    ax.axvline(diagnostics.selected_threshold, color='r', linestyle='--')
    ax.set_title('Distribution')
    ax.set_xlim(0, np.percentile(data, 99))
    
    # Shape stability
    ax = axes[0, 2]
    if diagnostics.threshold_analyses:
        pcts = [a.percentile for a in diagnostics.threshold_analyses]
        shapes = [a.shape for a in diagnostics.threshold_analyses]
        ax.plot(pcts, shapes, 'o-', markersize=3)
        ax.axvline(diagnostics.selected_percentile, color='r', linestyle='--')
        ax.axhline(0.5, color='orange', linestyle=':')
    ax.set_title('Shape Stability')
    ax.set_xlabel('Threshold %ile')
    
    # QQ plot mini
    ax = axes[1, 0]
    if len(sorted_exc) > 0:
        ax.scatter(theoretical[:50], sorted_exc[:50], alpha=0.5, s=10)
        max_val = max(max(theoretical[:50]), max(sorted_exc[:50]))
        ax.plot([0, max_val], [0, max_val], 'r--')
    ax.set_title('QQ Plot')
    
    # Tail comparison mini
    ax = axes[1, 1]
    ax.semilogy(sorted_data[:100], empirical_probs[:100], 'b-', linewidth=1)
    tail_x = x_range[x_range <= sorted_data[0]]
    tail_gpd = exc_prob * (1 - stats.genpareto.cdf(
        tail_x - diagnostics.selected_threshold,
        diagnostics.final_shape, loc=0, scale=diagnostics.final_scale
    ))
    ax.semilogy(tail_x, tail_gpd, 'r--', linewidth=1)
    ax.set_title('Tail Comparison')
    
    # Return levels mini
    ax = axes[1, 2]
    ax.semilogx(return_periods, [r * 100 for r in return_levels], 'o-')
    ax.set_title('Return Levels')
    ax.set_xlabel('Return Period')
    ax.set_ylabel('Severity %')
    
    plt.tight_layout()
    path = output_dir / f"{prefix}_00_summary.png"
    fig.savefig(path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    saved_files.insert(0, path)  # Put summary first
    
    # 8. CONSTRAINED vs UNCONSTRAINED COMPARISON PLOTS
    if diagnostics.unconstrained_shape is not None:
        
        # 8a. Side-by-side QQ plots (each using its own threshold)
        fig, axes = plt.subplots(1, 2, figsize=(14, 6))
        
        # Constrained QQ - uses constrained threshold
        exceedances_c = data[data > diagnostics.selected_threshold] - diagnostics.selected_threshold
        sorted_exc_c = np.sort(exceedances_c)
        n_c = len(sorted_exc_c)
        probs_c = (np.arange(1, n_c + 1) - 0.5) / n_c
        
        ax = axes[0]
        theoretical_c = stats.genpareto.ppf(probs_c, diagnostics.final_shape, 
                                             loc=0, scale=diagnostics.final_scale)
        ax.scatter(theoretical_c, sorted_exc_c, alpha=0.5, s=20, c='blue')
        max_val = max(max(theoretical_c), max(sorted_exc_c))
        ax.plot([0, max_val], [0, max_val], 'r--', label='Perfect fit')
        ax.set_xlabel('Theoretical Quantiles')
        ax.set_ylabel('Empirical Quantiles')
        ax.set_title(f'QQ Plot - CONSTRAINED\nThreshold: {diagnostics.selected_threshold:.1%} ({diagnostics.selected_percentile:.0f}th)\n(xi={diagnostics.final_shape:.3f}, sigma={diagnostics.final_scale:.3f})\nKS p={diagnostics.ks_pvalue:.3f}, AD={diagnostics.ad_statistic:.2f}')
        ax.legend()
        ax.grid(True, alpha=0.3)
        ax.set_aspect('equal')
        
        # Unconstrained QQ - uses UNCONSTRAINED threshold
        exceedances_u = data[data > diagnostics.unconstrained_threshold] - diagnostics.unconstrained_threshold
        sorted_exc_u = np.sort(exceedances_u)
        n_u = len(sorted_exc_u)
        probs_u = (np.arange(1, n_u + 1) - 0.5) / n_u
        
        ax = axes[1]
        theoretical_u = stats.genpareto.ppf(probs_u, diagnostics.unconstrained_shape, 
                                             loc=0, scale=diagnostics.unconstrained_scale)
        ax.scatter(theoretical_u, sorted_exc_u, alpha=0.5, s=20, c='green')
        max_val = max(max(theoretical_u), max(sorted_exc_u))
        ax.plot([0, max_val], [0, max_val], 'r--', label='Perfect fit')
        ax.set_xlabel('Theoretical Quantiles')
        ax.set_ylabel('Empirical Quantiles')
        ax.set_title(f'QQ Plot - UNCONSTRAINED\nThreshold: {diagnostics.unconstrained_threshold:.1%} ({diagnostics.unconstrained_threshold_percentile:.0f}th)\n(xi={diagnostics.unconstrained_shape:.3f}, sigma={diagnostics.unconstrained_scale:.3f})\nKS p={diagnostics.unconstrained_ks_pvalue:.3f}, AD={diagnostics.unconstrained_ad_statistic:.2f}')
        ax.legend()
        ax.grid(True, alpha=0.3)
        ax.set_aspect('equal')
        
        plt.tight_layout()
        path = output_dir / f"{prefix}_07_qq_comparison.png"
        fig.savefig(path, dpi=150, bbox_inches='tight')
        plt.close(fig)
        saved_files.append(path)
        
        # 8b. Tail comparison with both fits (each using its own threshold)
        fig, ax = plt.subplots(figsize=(12, 7))
        
        # Empirical survival function
        sorted_data = np.sort(data)[::-1]
        n_total = len(sorted_data)
        empirical_probs = np.arange(1, n_total + 1) / n_total
        
        ax.semilogy(sorted_data, empirical_probs, 'b-', linewidth=2, label='Empirical', alpha=0.7)
        
        # Fitted GPD survival - constrained (uses constrained threshold)
        x_range_c = np.linspace(diagnostics.selected_threshold, sorted_data[0] * 1.5, 300)
        exc_prob_c = diagnostics.final_n_exceedances / n_total
        
        gpd_survival_c = exc_prob_c * (1 - stats.genpareto.cdf(
            x_range_c - diagnostics.selected_threshold,
            diagnostics.final_shape,
            loc=0,
            scale=diagnostics.final_scale
        ))
        ax.semilogy(x_range_c, gpd_survival_c, 'r--', linewidth=2.5, 
                    label=f'Constrained (xi={diagnostics.final_shape:.3f}, u={diagnostics.selected_threshold:.1%})')
        
        # Fitted GPD survival - unconstrained (uses UNCONSTRAINED threshold)
        x_range_u = np.linspace(diagnostics.unconstrained_threshold, sorted_data[0] * 1.5, 300)
        exc_prob_u = diagnostics.unconstrained_n_exceedances / n_total
        
        gpd_survival_u = exc_prob_u * (1 - stats.genpareto.cdf(
            x_range_u - diagnostics.unconstrained_threshold,
            diagnostics.unconstrained_shape,
            loc=0,
            scale=diagnostics.unconstrained_scale
        ))
        ax.semilogy(x_range_u, gpd_survival_u, 'g-.', linewidth=2.5, 
                    label=f'Unconstrained (xi={diagnostics.unconstrained_shape:.3f}, u={diagnostics.unconstrained_threshold:.1%})')
        
        # Mark return periods for both
        for rp in [50, 100, 200]:
            ax.axhline(1/rp, color='gray', linestyle=':', alpha=0.4)
            
            # Constrained
            sev_c = diagnostics.return_period_severities.get(str(rp), 0)
            if sev_c:
                ax.plot(sev_c, 1/rp, 'rs', markersize=8)
                
            # Unconstrained
            if diagnostics.unconstrained_return_periods:
                sev_u = diagnostics.unconstrained_return_periods.get(str(rp), 0)
                if sev_u:
                    ax.plot(sev_u, 1/rp, 'g^', markersize=8)
        
        # Mark both thresholds
        ax.axvline(diagnostics.selected_threshold, color='red', linestyle=':', 
                   alpha=0.5, label=f'Constr. threshold ({diagnostics.selected_percentile:.0f}th)')
        if abs(diagnostics.unconstrained_threshold - diagnostics.selected_threshold) > 0.001:
            ax.axvline(diagnostics.unconstrained_threshold, color='green', linestyle=':', 
                       alpha=0.5, label=f'Unconstr. threshold ({diagnostics.unconstrained_threshold_percentile:.0f}th)')
        
        ax.set_xlabel('Severity', fontsize=12)
        ax.set_ylabel('Exceedance Probability', fontsize=12)
        ax.set_title('Tail Comparison: Constrained vs Unconstrained GPD\n(each with its own optimal threshold)', fontsize=14)
        ax.legend(loc='upper right')
        ax.grid(True, alpha=0.3)
        ax.set_ylim(1e-4, 1)
        
        path = output_dir / f"{prefix}_08_tail_comparison_both.png"
        fig.savefig(path, dpi=150, bbox_inches='tight')
        plt.close(fig)
        saved_files.append(path)
        
        # 8c. Return level comparison
        fig, ax = plt.subplots(figsize=(10, 7))
        
        return_periods_plot = [5, 10, 25, 50, 100, 200, 500]
        
        # Constrained return levels
        return_levels_c = [diagnostics.return_period_severities.get(str(rp), np.nan) 
                          for rp in return_periods_plot]
        ax.semilogx(return_periods_plot, [r * 100 for r in return_levels_c], 'ro-', 
                    linewidth=2, markersize=10, label='Constrained (xi<0.5)')
        
        # Unconstrained return levels
        if diagnostics.unconstrained_return_periods:
            return_levels_u = [diagnostics.unconstrained_return_periods.get(str(rp), np.nan) 
                              for rp in return_periods_plot]
            ax.semilogx(return_periods_plot, [r * 100 for r in return_levels_u], 'g^--', 
                        linewidth=2, markersize=10, label='Unconstrained')
        
        # Empirical estimates
        emp_return_levels = []
        for rp in return_periods_plot:
            pct = 100 * (1 - 1/rp)
            if pct <= 99:
                emp_return_levels.append(np.percentile(data, pct))
            else:
                emp_return_levels.append(np.nan)
        
        valid_mask = ~np.isnan(emp_return_levels)
        ax.semilogx(np.array(return_periods_plot)[valid_mask], 
                    [r * 100 for r in np.array(emp_return_levels)[valid_mask]], 
                    'bs', markersize=12, label='Empirical', alpha=0.7)
        
        # Add difference annotation
        if diagnostics.unconstrained_return_periods:
            for rp in [100, 200]:
                sev_c = diagnostics.return_period_severities.get(str(rp), 0)
                sev_u = diagnostics.unconstrained_return_periods.get(str(rp), 0)
                if sev_c and sev_u:
                    diff_pct = (sev_u - sev_c) / sev_c * 100
                    mid_y = (sev_c + sev_u) / 2 * 100
                    ax.annotate(f'{diff_pct:+.0f}%', xy=(rp, mid_y), fontsize=10, 
                               ha='left', color='purple', fontweight='bold')
        
        ax.set_xlabel('Return Period (years)', fontsize=12)
        ax.set_ylabel('Severity (%)', fontsize=12)
        ax.set_title('Return Level Comparison: Constrained vs Unconstrained', fontsize=14)
        ax.legend(loc='upper left')
        ax.grid(True, alpha=0.3)
        
        path = output_dir / f"{prefix}_09_return_level_comparison.png"
        fig.savefig(path, dpi=150, bbox_inches='tight')
        plt.close(fig)
        saved_files.append(path)
        
        # 8d. Summary comparison panel
        fig, axes = plt.subplots(2, 2, figsize=(14, 10))
        
        # Text comparison
        ax = axes[0, 0]
        ax.axis('off')
        
        shape_diff = diagnostics.unconstrained_shape - diagnostics.final_shape
        threshold_diff = abs(diagnostics.unconstrained_threshold - diagnostics.selected_threshold) > 0.001
        binding = "YES - constraint is active" if shape_diff > 0.01 else "NO - similar fits"
        
        comparison_text = f"""CONSTRAINED vs UNCONSTRAINED COMPARISON

                    CONSTRAINED    UNCONSTRAINED
Threshold:       {diagnostics.selected_threshold:>8.1%} ({diagnostics.selected_percentile:.0f}th)  {diagnostics.unconstrained_threshold:>8.1%} ({diagnostics.unconstrained_threshold_percentile:.0f}th)
Exceedances:          {diagnostics.final_n_exceedances:>5}            {diagnostics.unconstrained_n_exceedances:>5}
Shape (xi):           {diagnostics.final_shape:>8.4f}       {diagnostics.unconstrained_shape:>8.4f}
Scale (sigma):        {diagnostics.final_scale:>8.4f}       {diagnostics.unconstrained_scale:>8.4f}
KS p-value:           {diagnostics.ks_pvalue:>8.4f}       {diagnostics.unconstrained_ks_pvalue:>8.4f}
AD statistic:         {diagnostics.ad_statistic:>8.2f}       {diagnostics.unconstrained_ad_statistic:>8.2f}

Shape difference: {shape_diff:+.4f}
Constraint binding: {binding}

RETURN PERIODS:
                    CONSTRAINED    UNCONSTRAINED     DIFF
"""
        for rp in ['50', '100', '200']:
            sev_c = diagnostics.return_period_severities.get(rp, 0)
            sev_u = diagnostics.unconstrained_return_periods.get(rp, 0) if diagnostics.unconstrained_return_periods else 0
            diff = (sev_u - sev_c) / sev_c * 100 if sev_c > 0 else 0
            comparison_text += f"  {rp:>3}-year:        {sev_c:>8.1%}       {sev_u:>8.1%}    {diff:>+6.0f}%\n"
        
        ax.text(0.05, 0.95, comparison_text, transform=ax.transAxes, 
                fontsize=10, verticalalignment='top', fontfamily='monospace',
                bbox=dict(boxstyle='round', facecolor='lightyellow', alpha=0.8))
        
        # Mini QQ comparison (using each fit's own exceedances)
        ax = axes[0, 1]
        n_pts = min(50, len(sorted_exc_c), len(sorted_exc_u))
        ax.scatter(theoretical_c[:n_pts], sorted_exc_c[:n_pts], alpha=0.5, s=15, c='red', label='Constrained')
        ax.scatter(theoretical_u[:n_pts], sorted_exc_u[:n_pts], alpha=0.5, s=15, c='green', label='Unconstrained')
        max_val = max(max(theoretical_c[:n_pts]), max(theoretical_u[:n_pts]), max(sorted_exc_c[:n_pts]), max(sorted_exc_u[:n_pts]))
        ax.plot([0, max_val], [0, max_val], 'k--', alpha=0.5)
        ax.set_title('QQ Comparison (first 50 points)')
        ax.legend()
        ax.set_aspect('equal')
        
        # Mini tail comparison
        ax = axes[1, 0]
        ax.semilogy(sorted_data[:50], empirical_probs[:50], 'b-', linewidth=1.5, label='Empirical')
        tail_x_c = x_range_c[x_range_c <= sorted_data[0]]
        tail_x_u = x_range_u[x_range_u <= sorted_data[0]]
        ax.semilogy(tail_x_c, gpd_survival_c[x_range_c <= sorted_data[0]], 'r--', linewidth=1.5, label='Constrained')
        ax.semilogy(tail_x_u, gpd_survival_u[x_range_u <= sorted_data[0]], 'g-.', linewidth=1.5, label='Unconstrained')
        ax.set_title('Tail Comparison')
        ax.legend(fontsize=8)
        ax.grid(True, alpha=0.3)
        
        # Return level comparison
        ax = axes[1, 1]
        ax.semilogx(return_periods_plot, [r * 100 for r in return_levels_c], 'ro-', 
                    linewidth=1.5, markersize=6, label='Constrained')
        if diagnostics.unconstrained_return_periods:
            ax.semilogx(return_periods_plot, [r * 100 for r in return_levels_u], 'g^--', 
                        linewidth=1.5, markersize=6, label='Unconstrained')
        ax.semilogx(np.array(return_periods_plot)[valid_mask], 
                    [r * 100 for r in np.array(emp_return_levels)[valid_mask]], 
                    'bs', markersize=8, label='Empirical')
        ax.set_title('Return Levels')
        ax.set_xlabel('Return Period')
        ax.set_ylabel('Severity %')
        ax.legend(fontsize=8)
        ax.grid(True, alpha=0.3)
        
        plt.tight_layout()
        path = output_dir / f"{prefix}_10_comparison_summary.png"
        fig.savefig(path, dpi=150, bbox_inches='tight')
        plt.close(fig)
        saved_files.append(path)
    
    return saved_files


def _gpd_fit_to_dict(fit: GPDFitResult) -> dict:
    """Convert GPDFitResult to JSON-serializable dict."""
    if fit is None:
        return None
    return {
        'threshold': fit.threshold,
        'threshold_percentile': fit.threshold_percentile,
        'n_exceedances': fit.n_exceedances,
        'shape': fit.shape,
        'scale': fit.scale,
        'ks_statistic': fit.ks_statistic,
        'ks_pvalue': fit.ks_pvalue,
        'ad_statistic': fit.ad_statistic,
        'return_periods': fit.return_periods,
        'threshold_analyses': [asdict(ta) for ta in fit.threshold_analyses] if fit.threshold_analyses else None
    }


def save_gpd_diagnostics(
    data: np.ndarray,
    output_dir: Path,
    prefix: str = "gpd",
    percentile_range: Tuple[float, float] = (80, 99)
) -> Tuple[GPDDiagnostics, List[Path]]:
    """
    Compute and save complete GPD diagnostics with all 4 severity modes.
    
    Args:
        data: Severity data array
        output_dir: Directory to save outputs
        prefix: Filename prefix
        percentile_range: Range of percentiles to test
    
    Returns:
        (diagnostics, list of saved file paths)
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    logger.info("Computing GPD diagnostics...")
    diagnostics = compute_gpd_diagnostics(data, percentile_range)
    
    # Save JSON with all 4 modes
    json_path = output_dir / f"{prefix}_diagnostics.json"
    
    diag_dict = {
        'n_total': diagnostics.n_total,
        'data_min': diagnostics.data_min,
        'data_max': diagnostics.data_max,
        'data_mean': diagnostics.data_mean,
        'data_median': diagnostics.data_median,
        'data_std': diagnostics.data_std,
        'data_skewness': diagnostics.data_skewness,
        'data_kurtosis': diagnostics.data_kurtosis,
        'percentiles': diagnostics.percentiles,
        'warnings': diagnostics.warnings,
        
        # All 4 severity modes
        'constrained': _gpd_fit_to_dict(diagnostics.constrained),
        'unconstrained': _gpd_fit_to_dict(diagnostics.unconstrained),
        'unconstrained_no_max': _gpd_fit_to_dict(diagnostics.unconstrained_no_max),
        'max_value_removed': diagnostics.max_value_removed,
        'empirical_return_periods': diagnostics.empirical_return_periods,
        
        # Recommendation
        'recommended_mode': diagnostics.recommended_mode,
        'recommendation_reason': diagnostics.recommendation_reason,
        'recommendation_scores': diagnostics.recommendation_scores,
        
        # Legacy fields for backward compatibility
        'selected_percentile': diagnostics.selected_percentile,
        'selected_threshold': diagnostics.selected_threshold,
        'final_shape': diagnostics.final_shape,
        'final_scale': diagnostics.final_scale,
        'final_n_exceedances': diagnostics.final_n_exceedances,
        'ks_statistic': diagnostics.ks_statistic,
        'ks_pvalue': diagnostics.ks_pvalue,
        'ad_statistic': diagnostics.ad_statistic,
        'return_period_severities': diagnostics.return_period_severities,
        'unconstrained_threshold': diagnostics.unconstrained_threshold,
        'unconstrained_threshold_percentile': diagnostics.unconstrained_threshold_percentile,
        'unconstrained_shape': diagnostics.unconstrained_shape,
        'unconstrained_scale': diagnostics.unconstrained_scale,
        'unconstrained_n_exceedances': diagnostics.unconstrained_n_exceedances,
        'unconstrained_ks_pvalue': diagnostics.unconstrained_ks_pvalue,
        'unconstrained_ad_statistic': diagnostics.unconstrained_ad_statistic,
        'unconstrained_return_periods': diagnostics.unconstrained_return_periods,
    }
    
    with open(json_path, 'w') as f:
        json.dump(diag_dict, f, indent=2)
    
    logger.info(f"Saved diagnostics JSON: {json_path}")
    
    # Generate plots
    logger.info("Generating diagnostic plots...")
    plot_paths = plot_gpd_diagnostics(data, diagnostics, output_dir, prefix)
    
    # Generate 4-mode comparison plots
    logger.info("Generating 4-mode comparison plots...")
    comparison_paths = plot_4mode_comparison(data, diagnostics, output_dir, prefix)
    plot_paths.extend(comparison_paths)
    
    logger.info(f"Saved {len(plot_paths)} diagnostic plots")
    
    # Log warnings
    if diagnostics.warnings:
        logger.warning("GPD FIT WARNINGS:")
        for w in diagnostics.warnings:
            logger.warning(f"  WARNING: {w}")
    
    all_paths = [json_path] + plot_paths
    return diagnostics, all_paths


def plot_4mode_comparison(
    data: np.ndarray,
    diagnostics: GPDDiagnostics,
    output_dir: Path,
    prefix: str = "gpd"
) -> List[Path]:
    """
    Generate comparison plots for all 4 severity modes.
    """
    saved_files = []
    data = np.array(data)
    data = data[~np.isnan(data) & (data > 0)]
    n_total = len(data)
    
    # Colors for each mode
    colors = {
        'constrained': '#d62728',      # Red
        'unconstrained': '#2ca02c',    # Green
        'unconstrained_no_max': '#9467bd',  # Purple
        'empirical': '#1f77b4'         # Blue
    }
    
    labels = {
        'constrained': 'Constrained (ξ<0.5)',
        'unconstrained': 'Unconstrained',
        'unconstrained_no_max': 'Unconstr. (no max)',
        'empirical': 'Empirical'
    }
    
    # =========================================================================
    # PLOT 1: 4-way QQ comparison
    # =========================================================================
    modes_with_fits = []
    if diagnostics.constrained:
        modes_with_fits.append(('constrained', diagnostics.constrained))
    if diagnostics.unconstrained:
        modes_with_fits.append(('unconstrained', diagnostics.unconstrained))
    if diagnostics.unconstrained_no_max:
        modes_with_fits.append(('unconstrained_no_max', diagnostics.unconstrained_no_max))
    
    n_modes = len(modes_with_fits)
    if n_modes > 0:
        fig, axes = plt.subplots(1, n_modes, figsize=(5*n_modes, 5))
        if n_modes == 1:
            axes = [axes]
        
        for idx, (mode_name, fit) in enumerate(modes_with_fits):
            ax = axes[idx]
            
            # Get exceedances for this mode's threshold
            exceedances = data[data > fit.threshold] - fit.threshold
            sorted_exc = np.sort(exceedances)
            n = len(sorted_exc)
            probs = (np.arange(1, n + 1) - 0.5) / n
            
            theoretical = stats.genpareto.ppf(probs, fit.shape, loc=0, scale=fit.scale)
            
            ax.scatter(theoretical, sorted_exc, alpha=0.5, s=20, c=colors[mode_name])
            max_val = max(max(theoretical), max(sorted_exc))
            ax.plot([0, max_val], [0, max_val], 'k--', label='Perfect fit')
            
            ax.set_xlabel('Theoretical')
            ax.set_ylabel('Empirical')
            ax.set_title(f'{labels[mode_name]}\nξ={fit.shape:.3f}, u={fit.threshold:.1%}\nKS p={fit.ks_pvalue:.3f}')
            ax.set_aspect('equal')
            ax.grid(True, alpha=0.3)
        
        plt.tight_layout()
        path = output_dir / f"{prefix}_11_qq_4mode.png"
        fig.savefig(path, dpi=150, bbox_inches='tight')
        plt.close(fig)
        saved_files.append(path)
    
    # =========================================================================
    # PLOT 2: Return period comparison (all 4 modes)
    # =========================================================================
    fig, ax = plt.subplots(figsize=(12, 8))
    
    return_periods = [10, 25, 50, 100, 200, 500]
    
    # Empirical
    if diagnostics.empirical_return_periods:
        emp_values = [diagnostics.empirical_return_periods.get(str(rp)) for rp in return_periods]
        valid_mask = [v is not None for v in emp_values]
        valid_rp = [rp for rp, v in zip(return_periods, valid_mask) if v]
        valid_emp = [v*100 for v, m in zip(emp_values, valid_mask) if m]
        ax.semilogx(valid_rp, valid_emp, 'o-', color=colors['empirical'], 
                    linewidth=2, markersize=10, label=labels['empirical'])
    
    # GPD modes
    for mode_name, fit in modes_with_fits:
        rp_values = [fit.return_periods.get(str(rp), np.nan) * 100 for rp in return_periods]
        ax.semilogx(return_periods, rp_values, 'o--', color=colors[mode_name],
                    linewidth=2, markersize=8, label=labels[mode_name])
    
    ax.set_xlabel('Return Period (years)', fontsize=12)
    ax.set_ylabel('Severity (%)', fontsize=12)
    ax.set_title('Return Period Comparison: All 4 Severity Modes', fontsize=14)
    ax.legend(loc='upper left', fontsize=10)
    ax.grid(True, alpha=0.3)
    
    # Add recommendation box
    rec_text = f"RECOMMENDED: {diagnostics.recommended_mode}\n{diagnostics.recommendation_reason}"
    ax.text(0.98, 0.02, rec_text, transform=ax.transAxes, fontsize=9,
            verticalalignment='bottom', horizontalalignment='right',
            bbox=dict(boxstyle='round', facecolor='lightyellow', alpha=0.8))
    
    path = output_dir / f"{prefix}_12_return_periods_4mode.png"
    fig.savefig(path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    saved_files.append(path)
    
    # =========================================================================
    # PLOT 3: Tail survival comparison (all 4 modes)
    # =========================================================================
    fig, ax = plt.subplots(figsize=(12, 8))
    
    # Empirical survival
    sorted_data = np.sort(data)[::-1]
    empirical_probs = np.arange(1, n_total + 1) / n_total
    ax.semilogy(sorted_data, empirical_probs, '-', color=colors['empirical'], 
                linewidth=2.5, label=labels['empirical'], alpha=0.8)
    
    # GPD survival curves
    for mode_name, fit in modes_with_fits:
        x_range = np.linspace(fit.threshold, sorted_data[0] * 1.2, 300)
        exc_prob = fit.n_exceedances / n_total
        
        gpd_survival = exc_prob * (1 - stats.genpareto.cdf(
            x_range - fit.threshold,
            fit.shape,
            loc=0,
            scale=fit.scale
        ))
        ax.semilogy(x_range, gpd_survival, '--', color=colors[mode_name],
                    linewidth=2, label=labels[mode_name])
    
    # Mark return periods
    for rp in [50, 100, 200]:
        ax.axhline(1/rp, color='gray', linestyle=':', alpha=0.4)
        ax.text(sorted_data[0] * 1.15, 1/rp, f'{rp}yr', fontsize=8, va='center')
    
    ax.set_xlabel('Severity', fontsize=12)
    ax.set_ylabel('Exceedance Probability', fontsize=12)
    ax.set_title('Tail Survival Comparison: All 4 Severity Modes', fontsize=14)
    ax.legend(loc='upper right', fontsize=10)
    ax.grid(True, alpha=0.3)
    ax.set_ylim(1e-4, 1)
    
    path = output_dir / f"{prefix}_13_tail_4mode.png"
    fig.savefig(path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    saved_files.append(path)
    
    # =========================================================================
    # PLOT 4: Empirical Distribution Detail (smoothed CDF)
    # =========================================================================
    if diagnostics.empirical:
        fig, axes = plt.subplots(1, 2, figsize=(14, 6))
        
        emp = diagnostics.empirical
        
        # Left panel: CDF comparison
        ax = axes[0]
        
        # Raw ECDF
        sorted_data_asc = np.sort(data)
        raw_ecdf_y = (np.arange(1, n_total + 1) - 0.5) / n_total
        ax.plot(sorted_data_asc, raw_ecdf_y, 'b-', alpha=0.5, linewidth=1, label='Raw ECDF')
        
        # Smoothed CDF
        ax.plot(emp.cdf_x, emp.cdf_y, 'r-', linewidth=2, label='Smoothed CDF')
        
        # Mark max value cap
        ax.axvline(emp.data_max, color='green', linestyle='--', linewidth=2, 
                   label=f'Max cap ({emp.data_max:.1%})')
        
        ax.set_xlabel('Severity', fontsize=12)
        ax.set_ylabel('CDF P(X ≤ x)', fontsize=12)
        ax.set_title('Empirical Distribution: Smoothed CDF\n(monotonically increasing, capped at historical max)', fontsize=12)
        ax.legend(loc='lower right')
        ax.grid(True, alpha=0.3)
        ax.set_xlim(0, emp.data_max * 1.1)
        ax.set_ylim(0, 1.02)
        
        # Right panel: Tail detail (survival function)
        ax = axes[1]
        
        # Raw survival
        ax.semilogy(sorted_data, empirical_probs, 'b-', alpha=0.5, linewidth=1, label='Raw empirical')
        
        # Smoothed survival
        smooth_survival_x = np.array(emp.cdf_x)
        smooth_survival_y = 1 - np.array(emp.cdf_y)
        smooth_survival_y = np.maximum(smooth_survival_y, 1e-6)  # Avoid log(0)
        ax.semilogy(smooth_survival_x, smooth_survival_y, 'r-', linewidth=2, label='Smoothed empirical')
        
        # Mark return periods
        for rp in [10, 25, 50, 100]:
            sev = emp.return_periods.get(str(rp))
            if sev:
                ax.axhline(1/rp, color='gray', linestyle=':', alpha=0.4)
                ax.plot(sev, 1/rp, 'ro', markersize=8)
                ax.text(sev * 1.05, 1/rp, f'{rp}yr: {sev:.1%}', fontsize=9, va='center')
        
        # Mark max cap
        ax.axvline(emp.data_max, color='green', linestyle='--', linewidth=2, 
                   label=f'Max cap ({emp.data_max:.1%})')
        
        ax.set_xlabel('Severity', fontsize=12)
        ax.set_ylabel('Survival P(X > x)', fontsize=12)
        ax.set_title('Empirical Tail: Survival Function\n(no extrapolation beyond historical max)', fontsize=12)
        ax.legend(loc='upper right')
        ax.grid(True, alpha=0.3)
        ax.set_ylim(1e-3, 1)
        
        plt.tight_layout()
        path = output_dir / f"{prefix}_15_empirical_detail.png"
        fig.savefig(path, dpi=150, bbox_inches='tight')
        plt.close(fig)
        saved_files.append(path)
    
    # =========================================================================
    # PLOT 5: Summary comparison table
    # =========================================================================
    fig, ax = plt.subplots(figsize=(14, 11))
    ax.axis('off')
    
    # Build comparison text
    summary_text = """4-MODE SEVERITY DISTRIBUTION COMPARISON
================================================================================

                        CONSTRAINED      UNCONSTRAINED    UNCONSTR.(no max)   EMPIRICAL
                        (xi < 0.5)                                            (smoothed)
--------------------------------------------------------------------------------
"""
    
    # Threshold row
    if diagnostics.constrained:
        c_thr = f"{diagnostics.constrained.threshold:.1%} ({diagnostics.constrained.threshold_percentile:.0f}th)"
    else:
        c_thr = "N/A"
    
    if diagnostics.unconstrained:
        u_thr = f"{diagnostics.unconstrained.threshold:.1%} ({diagnostics.unconstrained.threshold_percentile:.0f}th)"
    else:
        u_thr = "N/A"
        
    if diagnostics.unconstrained_no_max:
        unm_thr = f"{diagnostics.unconstrained_no_max.threshold:.1%} ({diagnostics.unconstrained_no_max.threshold_percentile:.0f}th)"
    else:
        unm_thr = "N/A"
    
    summary_text += f"Threshold:          {c_thr:>16}  {u_thr:>16}  {unm_thr:>18}         -\n"
    
    # Shape row
    c_shape = f"{diagnostics.constrained.shape:.4f}" if diagnostics.constrained else "N/A"
    u_shape = f"{diagnostics.unconstrained.shape:.4f}" if diagnostics.unconstrained else "N/A"
    unm_shape = f"{diagnostics.unconstrained_no_max.shape:.4f}" if diagnostics.unconstrained_no_max else "N/A"
    summary_text += f"Shape (xi):               {c_shape:>10}        {u_shape:>10}          {unm_shape:>10}         -\n"
    
    # Scale row
    c_scale = f"{diagnostics.constrained.scale:.4f}" if diagnostics.constrained else "N/A"
    u_scale = f"{diagnostics.unconstrained.scale:.4f}" if diagnostics.unconstrained else "N/A"
    unm_scale = f"{diagnostics.unconstrained_no_max.scale:.4f}" if diagnostics.unconstrained_no_max else "N/A"
    summary_text += f"Scale (sigma):            {c_scale:>10}        {u_scale:>10}          {unm_scale:>10}         -\n"
    
    # KS p-value row
    c_ks = f"{diagnostics.constrained.ks_pvalue:.4f}" if diagnostics.constrained else "N/A"
    u_ks = f"{diagnostics.unconstrained.ks_pvalue:.4f}" if diagnostics.unconstrained else "N/A"
    unm_ks = f"{diagnostics.unconstrained_no_max.ks_pvalue:.4f}" if diagnostics.unconstrained_no_max else "N/A"
    emp_ks = f"{diagnostics.empirical.ks_statistic:.4f}" if diagnostics.empirical else "N/A"
    summary_text += f"KS statistic:             {c_ks:>10}        {u_ks:>10}          {unm_ks:>10}     {emp_ks:>10}\n"
    
    # AD statistic row
    c_ad = f"{diagnostics.constrained.ad_statistic:.2f}" if diagnostics.constrained else "N/A"
    u_ad = f"{diagnostics.unconstrained.ad_statistic:.2f}" if diagnostics.unconstrained else "N/A"
    unm_ad = f"{diagnostics.unconstrained_no_max.ad_statistic:.2f}" if diagnostics.unconstrained_no_max else "N/A"
    summary_text += f"AD statistic:             {c_ad:>10}        {u_ad:>10}          {unm_ad:>10}         -\n"
    
    # Empirical details
    if diagnostics.empirical:
        summary_text += f"\nEMPIRICAL DISTRIBUTION DETAILS:\n"
        summary_text += f"  Sample size: {diagnostics.empirical.n_total}\n"
        summary_text += f"  Range: [{diagnostics.empirical.data_min:.1%}, {diagnostics.empirical.data_max:.1%}]\n"
        summary_text += f"  Extrapolation: NONE (capped at historical max)\n"
    
    summary_text += "\n--------------------------------------------------------------------------------\n"
    summary_text += "RETURN PERIODS:\n"
    
    for rp in ['10', '25', '50', '100', '200']:
        c_rp = f"{diagnostics.constrained.return_periods.get(rp, 0)*100:.1f}%" if diagnostics.constrained else "N/A"
        u_rp = f"{diagnostics.unconstrained.return_periods.get(rp, 0)*100:.1f}%" if diagnostics.unconstrained else "N/A"
        unm_rp = f"{diagnostics.unconstrained_no_max.return_periods.get(rp, 0)*100:.1f}%" if diagnostics.unconstrained_no_max else "N/A"
        emp_val = diagnostics.empirical_return_periods.get(rp)
        emp_rp = f"{emp_val*100:.1f}%" if emp_val else "N/A"
        
        # Mark if empirical is capped
        if emp_val and diagnostics.empirical and emp_val >= diagnostics.empirical.data_max * 0.99:
            emp_rp += " (CAP)"
        
        summary_text += f"  {rp:>3}-year:              {c_rp:>10}        {u_rp:>10}          {unm_rp:>10}     {emp_rp:>10}\n"
    
    summary_text += f"""
--------------------------------------------------------------------------------
RECOMMENDATION SCORES:
"""
    if diagnostics.recommendation_scores:
        for mode, scores in diagnostics.recommendation_scores.items():
            extrap = scores.get('extrapolation', 0)
            summary_text += f"  {mode:>20}: KS={scores['ks_pvalue']:.1f}, AD={scores['ad_score']:.1f}, Emp={scores['empirical_match']:.1f}, Extrap={extrap:.0f}, TOTAL={scores['total']:.1f}\n"
    
    summary_text += f"""
================================================================================
RECOMMENDED MODE: {diagnostics.recommended_mode.upper()}
{diagnostics.recommendation_reason}
================================================================================

NOTES:
- Empirical mode: Uses smoothed CDF, capped at historical max ({diagnostics.data_max:.1%})
- GPD modes: Allow extrapolation beyond observed data
- 'Extrap' score = 20 for GPD modes, 0 for empirical (no extrapolation capability)
"""
    
    ax.text(0.02, 0.98, summary_text, transform=ax.transAxes,
            fontsize=9, verticalalignment='top', fontfamily='monospace',
            bbox=dict(boxstyle='round', facecolor='white', alpha=0.9))
    
    path = output_dir / f"{prefix}_14_summary_4mode.png"
    fig.savefig(path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    saved_files.append(path)
    
    return saved_files
