"""
EVT Diagnostic Visualization Module

Generates diagnostic plots for Extreme Value Theory analysis:
1. Shape Parameter Stability vs Threshold
2. Scale Parameter Stability vs Threshold  
3. Q-Q Plot (Threshold Exceedances vs GPD)
4. P-P Plot (Threshold Exceedances vs GPD)
5. Density Plot (Exceedances with fitted GPD)
6. Log-Log Plot (Pareto Tail Behavior)
7. Log-Log Linearity vs Threshold
8. Mean Excess Plot (Mean Residual Life)
9. Goodness of Fit (Anderson-Darling) vs Threshold
"""

import sys
from pathlib import Path
_script_dir = Path(__file__).resolve().parent
if str(_script_dir) not in sys.path:
    sys.path.insert(0, str(_script_dir))

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec
from scipy import stats
from scipy.optimize import minimize
from typing import Tuple, Dict, List, Optional
import logging

logger = logging.getLogger(__name__)

# Style configuration
plt.style.use('seaborn-v0_8-whitegrid')
COLORS = {
    'primary': '#2166AC',
    'secondary': '#B2182B', 
    'tertiary': '#4DAF4A',
    'threshold': '#E66101',
    'ci': '#92C5DE',
    'fit': '#D6604D'
}


# =============================================================================
# GPD Fitting Functions (local copies for visualization)
# =============================================================================

def fit_gpd_mle(exceedances: np.ndarray, max_shape: float = 0.5) -> Tuple[float, float]:
    """Fit GPD using MLE with shape constraint."""
    exceedances = exceedances[exceedances > 0]
    
    if len(exceedances) < 10:
        return 0.1, np.std(exceedances)
    
    # PWM initial estimates
    x_sorted = np.sort(exceedances)
    n = len(x_sorted)
    b0 = np.mean(x_sorted)
    b1 = np.sum(np.arange(1, n+1) * x_sorted) / (n * (n - 1))
    
    shape_init = np.clip(2 - b0 / (b0 - 2 * b1 + 1e-10), -0.5, max_shape - 0.01)
    scale_init = max(2 * b0 * b1 / (b0 - 2 * b1 + 1e-10), 0.01)
    
    def neg_loglik(params):
        xi, sigma = params
        if sigma <= 0:
            return np.inf
        n = len(exceedances)
        if abs(xi) < 1e-10:
            return n * np.log(sigma) + np.sum(exceedances) / sigma
        z = 1 + xi * exceedances / sigma
        if np.any(z <= 0):
            return np.inf
        return n * np.log(sigma) + (1 + 1/xi) * np.sum(np.log(z))
    
    result = minimize(neg_loglik, [shape_init, scale_init], 
                      method='L-BFGS-B',
                      bounds=[(-0.5, max_shape - 0.001), (1e-6, None)])
    
    if result.success:
        return result.x[0], result.x[1]
    return shape_init, scale_init


def gpd_cdf(x: np.ndarray, shape: float, scale: float) -> np.ndarray:
    """GPD cumulative distribution function."""
    x = np.asarray(x)
    if abs(shape) < 1e-10:
        return 1 - np.exp(-x / scale)
    z = 1 + shape * x / scale
    z = np.maximum(z, 1e-10)
    return 1 - z ** (-1 / shape)


def gpd_quantile(p: np.ndarray, shape: float, scale: float) -> np.ndarray:
    """GPD quantile function."""
    p = np.asarray(p)
    if abs(shape) < 1e-10:
        return -scale * np.log(1 - p)
    return scale * ((1 - p) ** (-shape) - 1) / shape


def gpd_pdf(x: np.ndarray, shape: float, scale: float) -> np.ndarray:
    """GPD probability density function."""
    x = np.asarray(x)
    if abs(shape) < 1e-10:
        return np.exp(-x / scale) / scale
    z = 1 + shape * x / scale
    z = np.maximum(z, 1e-10)
    return z ** (-(1 + 1/shape)) / scale


def anderson_darling_gpd(exceedances: np.ndarray, shape: float, scale: float) -> Tuple[float, float]:
    """Anderson-Darling test for GPD fit."""
    n = len(exceedances)
    pit = gpd_cdf(exceedances, shape, scale)
    pit = np.sort(pit)
    pit = np.clip(pit, 1e-10, 1 - 1e-10)
    
    i = np.arange(1, n + 1)
    ad_stat = -n - np.sum((2 * i - 1) * (np.log(pit) + np.log(1 - pit[::-1]))) / n
    
    # Approximate p-value
    ad_star = ad_stat * (1 + 0.75/n + 2.25/n**2)
    if ad_star < 0.2:
        p_value = 1 - np.exp(-13.436 + 101.14 * ad_star - 223.73 * ad_star**2)
    elif ad_star < 0.34:
        p_value = 1 - np.exp(-8.318 + 42.796 * ad_star - 59.938 * ad_star**2)
    elif ad_star < 0.6:
        p_value = np.exp(0.9177 - 4.279 * ad_star - 1.38 * ad_star**2)
    else:
        p_value = np.exp(1.2937 - 5.709 * ad_star + 0.0186 * ad_star**2)
    
    return ad_stat, np.clip(p_value, 0, 1)


# =============================================================================
# Individual EVT Diagnostic Plots
# =============================================================================

def plot_shape_stability(data: np.ndarray,
                         n_thresholds: int = 30,
                         output_path: str = None) -> plt.Figure:
    """
    Plot 1: Shape Parameter Stability vs Threshold
    
    Shows how the estimated shape parameter ξ changes with threshold.
    A stable region indicates a good threshold choice.
    """
    fig, ax = plt.subplots(figsize=(8, 5))
    
    thresholds = np.linspace(np.percentile(data, 50), np.percentile(data, 95), n_thresholds)
    shapes = []
    shapes_se = []
    n_exceed = []
    
    for u in thresholds:
        exc = data[data > u] - u
        if len(exc) < 20:
            break
        shape, scale = fit_gpd_mle(exc)
        shapes.append(shape)
        n_exceed.append(len(exc))
        
        # Bootstrap SE
        boot_shapes = []
        for _ in range(100):
            boot_exc = np.random.choice(exc, len(exc), replace=True)
            bs, _ = fit_gpd_mle(boot_exc)
            boot_shapes.append(bs)
        shapes_se.append(np.std(boot_shapes))
    
    thresholds = thresholds[:len(shapes)]
    shapes = np.array(shapes)
    shapes_se = np.array(shapes_se)
    
    # Plot with confidence band
    ax.plot(thresholds, shapes, color=COLORS['primary'], linewidth=2, label='Shape (ξ)')
    ax.fill_between(thresholds, shapes - 1.96 * shapes_se, shapes + 1.96 * shapes_se,
                    color=COLORS['ci'], alpha=0.3, label='95% CI')
    
    ax.axhline(y=0, color='gray', linestyle='--', alpha=0.5)
    ax.set_xlabel('Threshold', fontsize=11)
    ax.set_ylabel('Shape Parameter (ξ)', fontsize=11)
    ax.set_title('Shape Parameter Stability vs Threshold', fontsize=12, fontweight='bold')
    ax.legend(loc='best', fontsize=9)
    
    # Add secondary axis for number of exceedances
    ax2 = ax.twinx()
    ax2.plot(thresholds, n_exceed, color=COLORS['tertiary'], linestyle=':', alpha=0.7)
    ax2.set_ylabel('Number of Exceedances', fontsize=10, color=COLORS['tertiary'])
    ax2.tick_params(axis='y', labelcolor=COLORS['tertiary'])
    
    plt.tight_layout()
    
    if output_path:
        fig.savefig(output_path, dpi=150, bbox_inches='tight', facecolor='white')
        logger.info(f"Saved shape stability plot to {output_path}")
    
    return fig


def plot_scale_stability(data: np.ndarray,
                         n_thresholds: int = 30,
                         output_path: str = None) -> plt.Figure:
    """
    Plot 2: Scale Parameter Stability vs Threshold
    
    Shows modified scale parameter σ* = σ - ξu which should be constant
    if GPD is appropriate.
    """
    fig, ax = plt.subplots(figsize=(8, 5))
    
    thresholds = np.linspace(np.percentile(data, 50), np.percentile(data, 95), n_thresholds)
    scales = []
    mod_scales = []
    scales_se = []
    
    for u in thresholds:
        exc = data[data > u] - u
        if len(exc) < 20:
            break
        shape, scale = fit_gpd_mle(exc)
        scales.append(scale)
        mod_scales.append(scale - shape * u)
        
        # Bootstrap SE
        boot_mod = []
        for _ in range(100):
            boot_exc = np.random.choice(exc, len(exc), replace=True)
            bs, bsc = fit_gpd_mle(boot_exc)
            boot_mod.append(bsc - bs * u)
        scales_se.append(np.std(boot_mod))
    
    thresholds = thresholds[:len(scales)]
    mod_scales = np.array(mod_scales)
    scales_se = np.array(scales_se)
    
    ax.plot(thresholds, mod_scales, color=COLORS['primary'], linewidth=2, 
            label='Modified Scale (σ* = σ - ξu)')
    ax.fill_between(thresholds, mod_scales - 1.96 * scales_se, mod_scales + 1.96 * scales_se,
                    color=COLORS['ci'], alpha=0.3, label='95% CI')
    
    ax.set_xlabel('Threshold', fontsize=11)
    ax.set_ylabel('Modified Scale Parameter (σ*)', fontsize=11)
    ax.set_title('Scale Parameter Stability vs Threshold', fontsize=12, fontweight='bold')
    ax.legend(loc='best', fontsize=9)
    
    plt.tight_layout()
    
    if output_path:
        fig.savefig(output_path, dpi=150, bbox_inches='tight', facecolor='white')
        logger.info(f"Saved scale stability plot to {output_path}")
    
    return fig


def plot_qq_gpd(data: np.ndarray,
                threshold: float = None,
                output_path: str = None) -> plt.Figure:
    """
    Plot 3: Q-Q Plot (Threshold Exceedances vs GPD)
    
    Compares empirical quantiles against fitted GPD quantiles.
    Points should lie on the diagonal if GPD fits well.
    """
    if threshold is None:
        threshold = np.percentile(data, 85)
    
    exceedances = data[data > threshold] - threshold
    shape, scale = fit_gpd_mle(exceedances)
    
    fig, ax = plt.subplots(figsize=(7, 7))
    
    n = len(exceedances)
    empirical = np.sort(exceedances)
    p = (np.arange(1, n + 1) - 0.5) / n
    theoretical = gpd_quantile(p, shape, scale)
    
    ax.scatter(theoretical, empirical, c=COLORS['primary'], alpha=0.6, s=30, edgecolors='white')
    
    # Reference line
    max_val = max(empirical.max(), theoretical.max())
    ax.plot([0, max_val], [0, max_val], 'r--', linewidth=2, label='Perfect fit')
    
    # Add confidence envelope (approximate)
    se = scale * np.sqrt(p * (1 - p)) / (n * gpd_pdf(theoretical, shape, scale) + 1e-10)
    ax.fill_between(theoretical, empirical - 1.96 * se, empirical + 1.96 * se,
                    color=COLORS['ci'], alpha=0.2)
    
    ax.set_xlabel('Theoretical Quantiles (GPD)', fontsize=11)
    ax.set_ylabel('Empirical Quantiles', fontsize=11)
    ax.set_title(f'Q-Q Plot: GPD Fit (threshold={threshold:.3f}, ξ={shape:.3f})', 
                 fontsize=12, fontweight='bold')
    ax.legend(loc='lower right', fontsize=9)
    ax.set_aspect('equal')
    
    plt.tight_layout()
    
    if output_path:
        fig.savefig(output_path, dpi=150, bbox_inches='tight', facecolor='white')
        logger.info(f"Saved Q-Q plot to {output_path}")
    
    return fig


def plot_pp_gpd(data: np.ndarray,
                threshold: float = None,
                output_path: str = None) -> plt.Figure:
    """
    Plot 4: P-P Plot (Threshold Exceedances vs GPD)
    
    Compares empirical CDF against fitted GPD CDF.
    Points should lie on the diagonal if GPD fits well.
    """
    if threshold is None:
        threshold = np.percentile(data, 85)
    
    exceedances = data[data > threshold] - threshold
    shape, scale = fit_gpd_mle(exceedances)
    
    fig, ax = plt.subplots(figsize=(7, 7))
    
    n = len(exceedances)
    exceedances_sorted = np.sort(exceedances)
    empirical_cdf = (np.arange(1, n + 1)) / (n + 1)
    theoretical_cdf = gpd_cdf(exceedances_sorted, shape, scale)
    
    ax.scatter(theoretical_cdf, empirical_cdf, c=COLORS['primary'], alpha=0.6, s=30, edgecolors='white')
    
    # Reference line
    ax.plot([0, 1], [0, 1], 'r--', linewidth=2, label='Perfect fit')
    
    # Confidence bands (Kolmogorov-Smirnov)
    ks_crit = 1.36 / np.sqrt(n)  # 95% critical value
    ax.fill_between([0, 1], [0 - ks_crit, 1 - ks_crit], [0 + ks_crit, 1 + ks_crit],
                    color=COLORS['ci'], alpha=0.2, label='95% KS band')
    
    ax.set_xlabel('Theoretical CDF (GPD)', fontsize=11)
    ax.set_ylabel('Empirical CDF', fontsize=11)
    ax.set_title(f'P-P Plot: GPD Fit (threshold={threshold:.3f}, ξ={shape:.3f})',
                 fontsize=12, fontweight='bold')
    ax.legend(loc='lower right', fontsize=9)
    ax.set_xlim(-0.02, 1.02)
    ax.set_ylim(-0.02, 1.02)
    ax.set_aspect('equal')
    
    plt.tight_layout()
    
    if output_path:
        fig.savefig(output_path, dpi=150, bbox_inches='tight', facecolor='white')
        logger.info(f"Saved P-P plot to {output_path}")
    
    return fig


def plot_density_gpd(data: np.ndarray,
                     threshold: float = None,
                     output_path: str = None) -> plt.Figure:
    """
    Plot 5: Density Plot (Exceedances with fitted GPD)
    
    Shows histogram of exceedances overlaid with fitted GPD density.
    """
    if threshold is None:
        threshold = np.percentile(data, 85)
    
    exceedances = data[data > threshold] - threshold
    shape, scale = fit_gpd_mle(exceedances)
    
    fig, ax = plt.subplots(figsize=(9, 5))
    
    # Histogram
    ax.hist(exceedances, bins=30, density=True, color=COLORS['primary'], 
            alpha=0.5, edgecolor='white', label='Empirical')
    
    # Fitted GPD density
    x_range = np.linspace(0, exceedances.max() * 1.1, 200)
    gpd_density = gpd_pdf(x_range, shape, scale)
    ax.plot(x_range, gpd_density, color=COLORS['secondary'], linewidth=2.5, 
            label=f'Fitted GPD (ξ={shape:.3f}, σ={scale:.3f})')
    
    # KDE for comparison
    if len(exceedances) > 20:
        kde = stats.gaussian_kde(exceedances)
        ax.plot(x_range, kde(x_range), color=COLORS['tertiary'], linewidth=2, 
                linestyle='--', label='KDE')
    
    ax.set_xlabel('Exceedance (x - u)', fontsize=11)
    ax.set_ylabel('Density', fontsize=11)
    ax.set_title(f'Density: Exceedances Above Threshold ({threshold:.3f})',
                 fontsize=12, fontweight='bold')
    ax.legend(loc='upper right', fontsize=9)
    ax.set_xlim(0, None)
    
    plt.tight_layout()
    
    if output_path:
        fig.savefig(output_path, dpi=150, bbox_inches='tight', facecolor='white')
        logger.info(f"Saved density plot to {output_path}")
    
    return fig


def plot_loglog_tail(data: np.ndarray,
                     threshold: float = None,
                     output_path: str = None) -> plt.Figure:
    """
    Plot 6: Log-Log Plot of Exceedances (Pareto Tail Behavior)
    
    For Pareto-type tails, log(1-F(x)) vs log(x) should be approximately linear.
    Slope ≈ -1/ξ for GPD with shape ξ > 0.
    """
    if threshold is None:
        threshold = np.percentile(data, 85)
    
    exceedances = data[data > threshold] - threshold
    exceedances = exceedances[exceedances > 0]
    shape, scale = fit_gpd_mle(exceedances)
    
    fig, ax = plt.subplots(figsize=(8, 6))
    
    n = len(exceedances)
    exceedances_sorted = np.sort(exceedances)[::-1]  # Descending
    survival = np.arange(1, n + 1) / (n + 1)
    
    # Plot empirical
    ax.scatter(np.log(exceedances_sorted), np.log(survival), 
               c=COLORS['primary'], alpha=0.6, s=30, edgecolors='white', label='Empirical')
    
    # Fitted GPD line
    x_range = np.linspace(exceedances_sorted.min(), exceedances_sorted.max(), 100)
    gpd_survival = 1 - gpd_cdf(x_range, shape, scale)
    gpd_survival = np.maximum(gpd_survival, 1e-10)
    ax.plot(np.log(x_range), np.log(gpd_survival), color=COLORS['secondary'], 
            linewidth=2, label=f'Fitted GPD (ξ={shape:.3f})')
    
    # Reference Pareto line
    if shape > 0.01:
        slope = -1 / shape
        intercept = np.log(survival).mean() - slope * np.log(exceedances_sorted).mean()
        pareto_y = slope * np.log(x_range) + intercept
        ax.plot(np.log(x_range), pareto_y, '--', color=COLORS['tertiary'], 
                linewidth=1.5, alpha=0.7, label=f'Pareto slope (-1/ξ = {slope:.2f})')
    
    ax.set_xlabel('log(Exceedance)', fontsize=11)
    ax.set_ylabel('log(Survival Probability)', fontsize=11)
    ax.set_title('Log-Log Plot: Pareto Tail Behavior', fontsize=12, fontweight='bold')
    ax.legend(loc='lower left', fontsize=9)
    
    plt.tight_layout()
    
    if output_path:
        fig.savefig(output_path, dpi=150, bbox_inches='tight', facecolor='white')
        logger.info(f"Saved log-log tail plot to {output_path}")
    
    return fig


def plot_loglog_linearity(data: np.ndarray,
                          n_thresholds: int = 20,
                          output_path: str = None) -> plt.Figure:
    """
    Plot 7: Log-Log Linearity vs Threshold
    
    Shows R² of log-log linear fit at different thresholds.
    Higher R² indicates better Pareto tail approximation.
    """
    fig, ax = plt.subplots(figsize=(8, 5))
    
    thresholds = np.linspace(np.percentile(data, 50), np.percentile(data, 95), n_thresholds)
    r_squared = []
    n_exceed = []
    
    for u in thresholds:
        exc = data[data > u] - u
        exc = exc[exc > 0]
        if len(exc) < 20:
            break
        
        n = len(exc)
        exc_sorted = np.sort(exc)[::-1]
        survival = np.arange(1, n + 1) / (n + 1)
        
        # Linear regression in log-log space
        log_x = np.log(exc_sorted)
        log_y = np.log(survival)
        
        # R² calculation
        slope, intercept = np.polyfit(log_x, log_y, 1)
        fitted = slope * log_x + intercept
        ss_res = np.sum((log_y - fitted) ** 2)
        ss_tot = np.sum((log_y - log_y.mean()) ** 2)
        r2 = 1 - ss_res / ss_tot
        
        r_squared.append(r2)
        n_exceed.append(n)
    
    thresholds = thresholds[:len(r_squared)]
    
    ax.plot(thresholds, r_squared, color=COLORS['primary'], linewidth=2, marker='o', markersize=5)
    ax.axhline(y=0.95, color='green', linestyle='--', alpha=0.7, label='R² = 0.95')
    ax.axhline(y=0.90, color='orange', linestyle='--', alpha=0.7, label='R² = 0.90')
    
    ax.set_xlabel('Threshold', fontsize=11)
    ax.set_ylabel('R² (Log-Log Linearity)', fontsize=11)
    ax.set_title('Log-Log Linearity vs Threshold', fontsize=12, fontweight='bold')
    ax.set_ylim(0, 1.02)
    ax.legend(loc='lower left', fontsize=9)
    
    # Secondary axis for exceedances
    ax2 = ax.twinx()
    ax2.plot(thresholds, n_exceed, color=COLORS['tertiary'], linestyle=':', alpha=0.7)
    ax2.set_ylabel('Number of Exceedances', fontsize=10, color=COLORS['tertiary'])
    ax2.tick_params(axis='y', labelcolor=COLORS['tertiary'])
    
    plt.tight_layout()
    
    if output_path:
        fig.savefig(output_path, dpi=150, bbox_inches='tight', facecolor='white')
        logger.info(f"Saved log-log linearity plot to {output_path}")
    
    return fig


def plot_mean_excess(data: np.ndarray,
                     n_thresholds: int = 50,
                     output_path: str = None) -> plt.Figure:
    """
    Plot 8: Mean Excess Plot (Mean Residual Life)
    
    E[X - u | X > u] vs u. For GPD with ξ > -1, this should be linear
    with slope ξ/(1-ξ) and intercept σ/(1-ξ).
    """
    fig, ax = plt.subplots(figsize=(9, 5))
    
    data_sorted = np.sort(data)
    thresholds = np.linspace(np.percentile(data, 10), np.percentile(data, 95), n_thresholds)
    
    mean_excess = []
    me_ci_lower = []
    me_ci_upper = []
    n_exceed = []
    
    for u in thresholds:
        exc = data[data > u] - u
        if len(exc) < 10:
            break
        
        me = np.mean(exc)
        se = np.std(exc) / np.sqrt(len(exc))
        
        mean_excess.append(me)
        me_ci_lower.append(me - 1.96 * se)
        me_ci_upper.append(me + 1.96 * se)
        n_exceed.append(len(exc))
    
    thresholds = thresholds[:len(mean_excess)]
    mean_excess = np.array(mean_excess)
    me_ci_lower = np.array(me_ci_lower)
    me_ci_upper = np.array(me_ci_upper)
    
    ax.plot(thresholds, mean_excess, color=COLORS['primary'], linewidth=2, label='Mean Excess')
    ax.fill_between(thresholds, me_ci_lower, me_ci_upper, color=COLORS['ci'], alpha=0.3, label='95% CI')
    
    # Fit linear trend to identify stable region
    if len(thresholds) > 10:
        mid_idx = len(thresholds) // 2
        slope, intercept = np.polyfit(thresholds[mid_idx:], mean_excess[mid_idx:], 1)
        linear_fit = slope * thresholds + intercept
        ax.plot(thresholds, linear_fit, '--', color=COLORS['secondary'], linewidth=1.5,
                label=f'Linear fit (slope={slope:.3f})')
    
    ax.set_xlabel('Threshold (u)', fontsize=11)
    ax.set_ylabel('Mean Excess E[X - u | X > u]', fontsize=11)
    ax.set_title('Mean Excess Plot (Mean Residual Life)', fontsize=12, fontweight='bold')
    ax.legend(loc='upper left', fontsize=9)
    
    plt.tight_layout()
    
    if output_path:
        fig.savefig(output_path, dpi=150, bbox_inches='tight', facecolor='white')
        logger.info(f"Saved mean excess plot to {output_path}")
    
    return fig


def plot_ad_vs_threshold(data: np.ndarray,
                         n_thresholds: int = 25,
                         output_path: str = None) -> plt.Figure:
    """
    Plot 9: Goodness of Fit (Anderson-Darling) vs Threshold
    
    Shows AD test statistic and p-value at different thresholds.
    Higher p-value indicates better GPD fit.
    """
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(9, 8), sharex=True)
    
    thresholds = np.linspace(np.percentile(data, 60), np.percentile(data, 95), n_thresholds)
    ad_stats = []
    ad_pvals = []
    n_exceed = []
    
    for u in thresholds:
        exc = data[data > u] - u
        if len(exc) < 25:
            break
        
        shape, scale = fit_gpd_mle(exc)
        ad_stat, ad_pval = anderson_darling_gpd(exc, shape, scale)
        
        ad_stats.append(ad_stat)
        ad_pvals.append(ad_pval)
        n_exceed.append(len(exc))
    
    thresholds = thresholds[:len(ad_stats)]
    
    # Top: AD statistic
    ax1.plot(thresholds, ad_stats, color=COLORS['primary'], linewidth=2, marker='o', markersize=4)
    ax1.set_ylabel('Anderson-Darling Statistic', fontsize=11)
    ax1.set_title('Goodness of Fit vs Threshold', fontsize=12, fontweight='bold')
    
    # Bottom: p-value
    ax2.plot(thresholds, ad_pvals, color=COLORS['secondary'], linewidth=2, marker='o', markersize=4)
    ax2.axhline(y=0.05, color='red', linestyle='--', alpha=0.7, label='α = 0.05')
    ax2.axhline(y=0.10, color='orange', linestyle='--', alpha=0.7, label='α = 0.10')
    ax2.fill_between(thresholds, 0.05, 1, color='green', alpha=0.1)
    ax2.set_xlabel('Threshold', fontsize=11)
    ax2.set_ylabel('p-value', fontsize=11)
    ax2.set_ylim(0, 1.02)
    ax2.legend(loc='lower right', fontsize=9)
    
    # Highlight acceptable region
    acceptable = np.array(ad_pvals) > 0.05
    if any(acceptable):
        min_thresh = thresholds[np.where(acceptable)[0][0]]
        ax1.axvline(x=min_thresh, color='green', linestyle=':', alpha=0.7)
        ax2.axvline(x=min_thresh, color='green', linestyle=':', alpha=0.7, 
                    label=f'Min acceptable: {min_thresh:.3f}')
    
    plt.tight_layout()
    
    if output_path:
        fig.savefig(output_path, dpi=150, bbox_inches='tight', facecolor='white')
        logger.info(f"Saved AD vs threshold plot to {output_path}")
    
    return fig


# =============================================================================
# Combined EVT Dashboard
# =============================================================================

def generate_evt_diagnostic_plots(severities: np.ndarray,
                                   threshold: float = None,
                                   output_dir: str = None) -> Dict[str, plt.Figure]:
    """
    Generate all EVT diagnostic plots.
    
    Args:
        severities: Array of severity ratios
        threshold: Optional threshold (will be auto-selected if None)
        output_dir: Optional directory to save plots
    
    Returns:
        Dictionary of plot names to Figure objects
    """
    from pathlib import Path
    
    figures = {}
    
    if output_dir:
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
    
    # Auto-select threshold if not provided
    if threshold is None:
        threshold = np.percentile(severities, 85)
    
    logger.info(f"Generating EVT diagnostics (threshold={threshold:.4f})...")
    
    # 1. Shape stability
    logger.info("  Plot 1: Shape parameter stability")
    figures['shape_stability'] = plot_shape_stability(
        severities,
        output_path=str(output_path / 'evt_1_shape_stability.png') if output_dir else None
    )
    
    # 2. Scale stability
    logger.info("  Plot 2: Scale parameter stability")
    figures['scale_stability'] = plot_scale_stability(
        severities,
        output_path=str(output_path / 'evt_2_scale_stability.png') if output_dir else None
    )
    
    # 3. Q-Q plot
    logger.info("  Plot 3: Q-Q plot")
    figures['qq_plot'] = plot_qq_gpd(
        severities, threshold,
        output_path=str(output_path / 'evt_3_qq_plot.png') if output_dir else None
    )
    
    # 4. P-P plot
    logger.info("  Plot 4: P-P plot")
    figures['pp_plot'] = plot_pp_gpd(
        severities, threshold,
        output_path=str(output_path / 'evt_4_pp_plot.png') if output_dir else None
    )
    
    # 5. Density plot
    logger.info("  Plot 5: Density plot")
    figures['density'] = plot_density_gpd(
        severities, threshold,
        output_path=str(output_path / 'evt_5_density.png') if output_dir else None
    )
    
    # 6. Log-log tail
    logger.info("  Plot 6: Log-log tail plot")
    figures['loglog_tail'] = plot_loglog_tail(
        severities, threshold,
        output_path=str(output_path / 'evt_6_loglog_tail.png') if output_dir else None
    )
    
    # 7. Log-log linearity
    logger.info("  Plot 7: Log-log linearity vs threshold")
    figures['loglog_linearity'] = plot_loglog_linearity(
        severities,
        output_path=str(output_path / 'evt_7_loglog_linearity.png') if output_dir else None
    )
    
    # 8. Mean excess
    logger.info("  Plot 8: Mean excess plot")
    figures['mean_excess'] = plot_mean_excess(
        severities,
        output_path=str(output_path / 'evt_8_mean_excess.png') if output_dir else None
    )
    
    # 9. AD vs threshold
    logger.info("  Plot 9: Anderson-Darling vs threshold")
    figures['ad_vs_threshold'] = plot_ad_vs_threshold(
        severities,
        output_path=str(output_path / 'evt_9_ad_threshold.png') if output_dir else None
    )
    
    logger.info(f"Generated {len(figures)} EVT diagnostic plots")
    
    return figures


def plot_evt_summary(severities: np.ndarray,
                     threshold: float = None,
                     output_path: str = None) -> plt.Figure:
    """
    Create a single summary figure with key EVT diagnostics in a 3x3 grid.
    """
    if threshold is None:
        threshold = np.percentile(severities, 85)
    
    exceedances = severities[severities > threshold] - threshold
    shape, scale = fit_gpd_mle(exceedances)
    
    fig = plt.figure(figsize=(15, 12))
    gs = GridSpec(3, 3, figure=fig, hspace=0.35, wspace=0.3)
    fig.suptitle(f'EVT Diagnostic Summary (threshold={threshold:.3f}, ξ={shape:.3f}, σ={scale:.3f})', 
                 fontsize=14, fontweight='bold', y=0.98)
    
    # Row 1: Parameter stability
    ax1 = fig.add_subplot(gs[0, 0])
    ax2 = fig.add_subplot(gs[0, 1])
    ax3 = fig.add_subplot(gs[0, 2])
    
    # Row 2: Fit diagnostics
    ax4 = fig.add_subplot(gs[1, 0])
    ax5 = fig.add_subplot(gs[1, 1])
    ax6 = fig.add_subplot(gs[1, 2])
    
    # Row 3: Tail behavior
    ax7 = fig.add_subplot(gs[2, 0])
    ax8 = fig.add_subplot(gs[2, 1])
    ax9 = fig.add_subplot(gs[2, 2])
    
    # 1. Shape stability (simplified)
    thresholds = np.linspace(np.percentile(severities, 50), np.percentile(severities, 95), 20)
    shapes = []
    for u in thresholds:
        exc = severities[severities > u] - u
        if len(exc) < 20:
            break
        s, _ = fit_gpd_mle(exc)
        shapes.append(s)
    ax1.plot(thresholds[:len(shapes)], shapes, color=COLORS['primary'], linewidth=2)
    ax1.axhline(y=shape, color='red', linestyle='--', alpha=0.7)
    ax1.set_xlabel('Threshold')
    ax1.set_ylabel('Shape (ξ)')
    ax1.set_title('Shape Stability')
    
    # 2. Mean excess
    me_thresholds = np.linspace(np.percentile(severities, 10), np.percentile(severities, 90), 30)
    mean_excess = [np.mean(severities[severities > u] - u) for u in me_thresholds if len(severities[severities > u]) > 10]
    ax2.plot(me_thresholds[:len(mean_excess)], mean_excess, color=COLORS['primary'], linewidth=2)
    ax2.axvline(x=threshold, color='red', linestyle='--', alpha=0.7)
    ax2.set_xlabel('Threshold')
    ax2.set_ylabel('Mean Excess')
    ax2.set_title('Mean Excess Plot')
    
    # 3. AD p-value
    ad_thresholds = np.linspace(np.percentile(severities, 60), np.percentile(severities, 95), 15)
    ad_pvals = []
    for u in ad_thresholds:
        exc = severities[severities > u] - u
        if len(exc) < 25:
            break
        s, sc = fit_gpd_mle(exc)
        _, pval = anderson_darling_gpd(exc, s, sc)
        ad_pvals.append(pval)
    ax3.plot(ad_thresholds[:len(ad_pvals)], ad_pvals, color=COLORS['primary'], linewidth=2, marker='o', markersize=4)
    ax3.axhline(y=0.05, color='red', linestyle='--', alpha=0.7)
    ax3.axvline(x=threshold, color='green', linestyle='--', alpha=0.7)
    ax3.set_xlabel('Threshold')
    ax3.set_ylabel('AD p-value')
    ax3.set_title('Goodness of Fit')
    ax3.set_ylim(0, 1)
    
    # 4. Q-Q plot
    n = len(exceedances)
    empirical = np.sort(exceedances)
    p = (np.arange(1, n + 1) - 0.5) / n
    theoretical = gpd_quantile(p, shape, scale)
    ax4.scatter(theoretical, empirical, c=COLORS['primary'], alpha=0.6, s=20)
    max_val = max(empirical.max(), theoretical.max())
    ax4.plot([0, max_val], [0, max_val], 'r--', linewidth=2)
    ax4.set_xlabel('Theoretical')
    ax4.set_ylabel('Empirical')
    ax4.set_title('Q-Q Plot')
    ax4.set_aspect('equal')
    
    # 5. P-P plot
    empirical_cdf = (np.arange(1, n + 1)) / (n + 1)
    theoretical_cdf = gpd_cdf(np.sort(exceedances), shape, scale)
    ax5.scatter(theoretical_cdf, empirical_cdf, c=COLORS['primary'], alpha=0.6, s=20)
    ax5.plot([0, 1], [0, 1], 'r--', linewidth=2)
    ax5.set_xlabel('Theoretical CDF')
    ax5.set_ylabel('Empirical CDF')
    ax5.set_title('P-P Plot')
    ax5.set_aspect('equal')
    
    # 6. Density
    ax6.hist(exceedances, bins=25, density=True, color=COLORS['primary'], alpha=0.5, edgecolor='white')
    x_range = np.linspace(0, exceedances.max() * 1.1, 100)
    ax6.plot(x_range, gpd_pdf(x_range, shape, scale), color=COLORS['secondary'], linewidth=2)
    ax6.set_xlabel('Exceedance')
    ax6.set_ylabel('Density')
    ax6.set_title('Fitted Density')
    
    # 7. Log-log tail
    exc_sorted = np.sort(exceedances)[::-1]
    survival = np.arange(1, n + 1) / (n + 1)
    ax7.scatter(np.log(exc_sorted), np.log(survival), c=COLORS['primary'], alpha=0.6, s=20)
    x_fit = np.linspace(exc_sorted.min(), exc_sorted.max(), 50)
    gpd_surv = 1 - gpd_cdf(x_fit, shape, scale)
    ax7.plot(np.log(x_fit), np.log(np.maximum(gpd_surv, 1e-10)), color=COLORS['secondary'], linewidth=2)
    ax7.set_xlabel('log(Exceedance)')
    ax7.set_ylabel('log(Survival)')
    ax7.set_title('Log-Log Tail')
    
    # 8. Severity histogram with threshold
    ax8.hist(severities, bins=40, color=COLORS['primary'], alpha=0.6, edgecolor='white')
    ax8.axvline(x=threshold, color='red', linewidth=2, linestyle='--', label=f'Threshold: {threshold:.3f}')
    ax8.set_xlabel('Severity')
    ax8.set_ylabel('Count')
    ax8.set_title('Severity Distribution')
    ax8.legend(fontsize=8)
    
    # 9. Return period mapping
    return_periods = [5, 10, 25, 50, 100, 200, 500]
    n_total = len(severities)
    n_exceed = len(exceedances)
    p_exceed = n_exceed / n_total
    
    rp_severities = []
    for rp in return_periods:
        p_rp = 1 / rp
        p_gpd = 1 - p_rp / p_exceed
        if 0 < p_gpd < 1:
            sev = threshold + gpd_quantile(p_gpd, shape, scale)
            rp_severities.append(sev)
        else:
            rp_severities.append(np.nan)
    
    ax9.semilogy(rp_severities, return_periods, 'o-', color=COLORS['primary'], linewidth=2, markersize=8)
    ax9.set_xlabel('Severity')
    ax9.set_ylabel('Return Period (years)')
    ax9.set_title('Return Period Mapping')
    ax9.grid(True, alpha=0.3)
    
    if output_path:
        fig.savefig(output_path, dpi=150, bbox_inches='tight', facecolor='white')
        logger.info(f"Saved EVT summary to {output_path}")
    
    return fig


# =============================================================================
# CLI
# =============================================================================

if __name__ == "__main__":
    import argparse
    
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    
    parser = argparse.ArgumentParser(description="Generate EVT diagnostic plots")
    parser.add_argument('--data', '-d', help='Path to JSON with severity data')
    parser.add_argument('--threshold', '-t', type=float, help='GPD threshold')
    parser.add_argument('--output', '-o', default='results/stress_test/evt_plots',
                        help='Output directory')
    parser.add_argument('--summary-only', action='store_true', help='Generate only summary plot')
    
    args = parser.parse_args()
    
    # Generate test data if no input
    if args.data:
        import json
        with open(args.data, 'r') as f:
            data = json.load(f)
        severities = np.array([m['severity_ratio'] for m in data.get('movements', data)])
    else:
        np.random.seed(42)
        severities = np.concatenate([
            np.random.exponential(0.05, 300),
            np.random.exponential(0.15, 50) + 0.1
        ])
        severities = np.clip(severities, 0.01, 1.0)
        print("Using synthetic test data")
    
    print(f"Data: {len(severities)} observations")
    print(f"Range: {severities.min():.4f} - {severities.max():.4f}")
    
    from pathlib import Path
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    if args.summary_only:
        fig = plot_evt_summary(severities, args.threshold, 
                               str(output_dir / 'evt_summary.png'))
    else:
        figures = generate_evt_diagnostic_plots(severities, args.threshold, str(output_dir))
        
        # Also generate summary
        fig = plot_evt_summary(severities, args.threshold,
                               str(output_dir / 'evt_0_summary.png'))
    
    print(f"\nPlots saved to {output_dir}")
    plt.show()
