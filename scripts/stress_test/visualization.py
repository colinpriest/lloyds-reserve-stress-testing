"""
Visualization Module for Stress Test Diagnostics

Generates diagnostic plots for:
a) 3D latent space projections (three 2D scatter plots)
b) Coverage comparison: historical vs synthetic scatter plots
c) Historical density contour plots
d) Synthetic density contour plots
e) Severity distribution histograms
"""

import sys
from pathlib import Path
_script_dir = Path(__file__).resolve().parent
if str(_script_dir) not in sys.path:
    sys.path.insert(0, str(_script_dir))

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
from matplotlib.gridspec import GridSpec
from scipy import stats
from scipy.ndimage import gaussian_filter
from pathlib import Path
from typing import List, Dict, Tuple, Optional
import logging
import json

from config import HistoricalMovement, SyntheticScenario, LLOYDS_LOBS

logger = logging.getLogger(__name__)

# Style configuration
plt.style.use('seaborn-v0_8-whitegrid')
COLORS = {
    'historical': '#2166AC',  # Blue
    'synthetic': '#B2182B',   # Red
    'overlap': '#7570B3',     # Purple
    'contour_hist': 'Blues',
    'contour_syn': 'Reds'
}

AXIS_LABELS = {
    0: 'Severity Axis',
    1: 'Causality/Semantic Axis',
    2: 'Portfolio Structure Axis'
}

DIM_PAIRS = [(0, 1), (0, 2), (1, 2)]
DIM_PAIR_NAMES = [
    ('Severity', 'Causality'),
    ('Severity', 'Portfolio'),
    ('Causality', 'Portfolio')
]


# =============================================================================
# Helper Functions
# =============================================================================

def setup_figure(n_cols: int = 3, n_rows: int = 1, 
                 figsize: Tuple[float, float] = None,
                 title: str = None) -> Tuple[plt.Figure, np.ndarray]:
    """Create figure with consistent styling."""
    if figsize is None:
        figsize = (5 * n_cols, 4.5 * n_rows)
    
    fig, axes = plt.subplots(n_rows, n_cols, figsize=figsize)
    
    if title:
        fig.suptitle(title, fontsize=14, fontweight='bold', y=1.02)
    
    return fig, np.atleast_2d(axes) if n_rows > 1 else np.atleast_1d(axes)


def compute_density_grid(points: np.ndarray, 
                         grid_size: int = 100,
                         bandwidth: float = None) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Compute 2D density on a grid using KDE.
    
    Returns:
        (xx, yy, density) meshgrid and density values
    """
    if len(points) < 10:
        return None, None, None
    
    x, y = points[:, 0], points[:, 1]
    
    # Create grid
    x_min, x_max = x.min() - 0.1 * (x.max() - x.min()), x.max() + 0.1 * (x.max() - x.min())
    y_min, y_max = y.min() - 0.1 * (y.max() - y.min()), y.max() + 0.1 * (y.max() - y.min())
    
    xx, yy = np.meshgrid(
        np.linspace(x_min, x_max, grid_size),
        np.linspace(y_min, y_max, grid_size)
    )
    
    # Compute KDE
    try:
        if bandwidth is None:
            kde = stats.gaussian_kde(points.T)
        else:
            kde = stats.gaussian_kde(points.T, bw_method=bandwidth)
        
        positions = np.vstack([xx.ravel(), yy.ravel()])
        density = kde(positions).reshape(xx.shape)
    except np.linalg.LinAlgError:
        # Fallback to histogram-based density
        density, x_edges, y_edges = np.histogram2d(x, y, bins=grid_size)
        density = gaussian_filter(density.T, sigma=2)
        xx, yy = np.meshgrid(
            (x_edges[:-1] + x_edges[1:]) / 2,
            (y_edges[:-1] + y_edges[1:]) / 2
        )
    
    return xx, yy, density


# =============================================================================
# Plot a) Latent Space Scatter Plots
# =============================================================================

def plot_latent_space(latent_coords: np.ndarray,
                      severities: np.ndarray = None,
                      complexities: np.ndarray = None,
                      output_path: str = None,
                      title: str = "Joint Embedding: 3D Latent Space Projections") -> plt.Figure:
    """
    Plot three 2D scatter plots showing all dimension pairs of the latent space.
    
    Args:
        latent_coords: Nx3 array of latent coordinates
        severities: Optional array for color coding
        complexities: Optional array for size coding
        output_path: Optional path to save figure
        title: Figure title
    
    Returns:
        matplotlib Figure
    """
    fig, axes = setup_figure(n_cols=3, title=title)
    
    # Default color by severity if available
    if severities is not None:
        colors = severities
        cmap = 'viridis'
        vmin, vmax = np.percentile(severities, [5, 95])
    else:
        colors = latent_coords[:, 0]  # Color by first dimension
        cmap = 'viridis'
        vmin, vmax = None, None
    
    # Size by complexity if available
    if complexities is not None:
        sizes = 20 + 80 * (complexities - complexities.min()) / (complexities.max() - complexities.min() + 1e-10)
    else:
        sizes = 30
    
    for idx, ((dim_x, dim_y), (name_x, name_y)) in enumerate(zip(DIM_PAIRS, DIM_PAIR_NAMES)):
        ax = axes[idx]
        
        scatter = ax.scatter(
            latent_coords[:, dim_x],
            latent_coords[:, dim_y],
            c=colors,
            s=sizes,
            cmap=cmap,
            alpha=0.6,
            edgecolors='white',
            linewidths=0.5,
            vmin=vmin,
            vmax=vmax
        )
        
        ax.set_xlabel(f'Dim {dim_x + 1}: {name_x}', fontsize=10)
        ax.set_ylabel(f'Dim {dim_y + 1}: {name_y}', fontsize=10)
        ax.set_title(f'{name_x} vs {name_y}', fontsize=11, fontweight='bold')
        
        # Add colorbar to last plot
        if idx == 2 and severities is not None:
            cbar = plt.colorbar(scatter, ax=ax, shrink=0.8)
            cbar.set_label('Severity Ratio', fontsize=9)
    
    plt.tight_layout()
    
    if output_path:
        fig.savefig(output_path, dpi=150, bbox_inches='tight', facecolor='white')
        logger.info(f"Saved latent space plot to {output_path}")
    
    return fig


# =============================================================================
# Plot b) Coverage Scatter Plots (Historical vs Synthetic)
# =============================================================================

def plot_coverage_scatter(historical_coords: np.ndarray,
                          synthetic_coords: np.ndarray,
                          output_path: str = None,
                          title: str = "Coverage Comparison: Historical vs Synthetic") -> plt.Figure:
    """
    Plot three 2D scatter plots comparing historical (blue) and synthetic (red) points.
    
    Args:
        historical_coords: Nx3 array of historical latent coordinates
        synthetic_coords: Mx3 array of synthetic latent coordinates
        output_path: Optional path to save figure
        title: Figure title
    
    Returns:
        matplotlib Figure
    """
    fig, axes = setup_figure(n_cols=3, title=title)
    
    for idx, ((dim_x, dim_y), (name_x, name_y)) in enumerate(zip(DIM_PAIRS, DIM_PAIR_NAMES)):
        ax = axes[idx]
        
        # Plot synthetic first (background)
        ax.scatter(
            synthetic_coords[:, dim_x],
            synthetic_coords[:, dim_y],
            c=COLORS['synthetic'],
            s=25,
            alpha=0.4,
            edgecolors='none',
            label=f'Synthetic (n={len(synthetic_coords)})'
        )
        
        # Plot historical on top
        ax.scatter(
            historical_coords[:, dim_x],
            historical_coords[:, dim_y],
            c=COLORS['historical'],
            s=35,
            alpha=0.7,
            edgecolors='white',
            linewidths=0.5,
            label=f'Historical (n={len(historical_coords)})'
        )
        
        ax.set_xlabel(f'Dim {dim_x + 1}: {name_x}', fontsize=10)
        ax.set_ylabel(f'Dim {dim_y + 1}: {name_y}', fontsize=10)
        ax.set_title(f'{name_x} vs {name_y}', fontsize=11, fontweight='bold')
        
        if idx == 0:
            ax.legend(loc='upper left', fontsize=8, framealpha=0.9)
    
    plt.tight_layout()
    
    if output_path:
        fig.savefig(output_path, dpi=150, bbox_inches='tight', facecolor='white')
        logger.info(f"Saved coverage scatter plot to {output_path}")
    
    return fig


# =============================================================================
# Plot c) Historical Density Contours
# =============================================================================

def plot_density_contours(coords: np.ndarray,
                          color_scheme: str = 'historical',
                          output_path: str = None,
                          title: str = None,
                          n_levels: int = 10) -> plt.Figure:
    """
    Plot three 2D contour plots showing density of points.
    
    Args:
        coords: Nx3 array of latent coordinates
        color_scheme: 'historical' (blue) or 'synthetic' (red)
        output_path: Optional path to save figure
        title: Figure title
        n_levels: Number of contour levels
    
    Returns:
        matplotlib Figure
    """
    if title is None:
        title = f"{'Historical' if color_scheme == 'historical' else 'Synthetic'} Density Distribution"
    
    fig, axes = setup_figure(n_cols=3, title=title)
    
    cmap = COLORS['contour_hist'] if color_scheme == 'historical' else COLORS['contour_syn']
    point_color = COLORS['historical'] if color_scheme == 'historical' else COLORS['synthetic']
    
    for idx, ((dim_x, dim_y), (name_x, name_y)) in enumerate(zip(DIM_PAIRS, DIM_PAIR_NAMES)):
        ax = axes[idx]
        
        # Extract 2D coordinates
        points_2d = coords[:, [dim_x, dim_y]]
        
        # Compute density
        xx, yy, density = compute_density_grid(points_2d)
        
        if density is not None:
            # Filled contours
            contourf = ax.contourf(xx, yy, density, levels=n_levels, cmap=cmap, alpha=0.8)
            
            # Contour lines
            ax.contour(xx, yy, density, levels=n_levels, colors='white', linewidths=0.5, alpha=0.5)
            
            # Add colorbar
            cbar = plt.colorbar(contourf, ax=ax, shrink=0.8)
            cbar.set_label('Density', fontsize=8)
        
        # Overlay scatter points
        ax.scatter(
            coords[:, dim_x],
            coords[:, dim_y],
            c=point_color,
            s=10,
            alpha=0.3,
            edgecolors='none'
        )
        
        ax.set_xlabel(f'Dim {dim_x + 1}: {name_x}', fontsize=10)
        ax.set_ylabel(f'Dim {dim_y + 1}: {name_y}', fontsize=10)
        ax.set_title(f'{name_x} vs {name_y}', fontsize=11, fontweight='bold')
    
    plt.tight_layout()
    
    if output_path:
        fig.savefig(output_path, dpi=150, bbox_inches='tight', facecolor='white')
        logger.info(f"Saved density contour plot to {output_path}")
    
    return fig


def plot_historical_density(historical_coords: np.ndarray,
                            output_path: str = None) -> plt.Figure:
    """Plot historical density contours."""
    return plot_density_contours(
        historical_coords,
        color_scheme='historical',
        output_path=output_path,
        title="Historical Data: Density Distribution in Latent Space"
    )


def plot_synthetic_density(synthetic_coords: np.ndarray,
                           output_path: str = None) -> plt.Figure:
    """Plot synthetic density contours."""
    return plot_density_contours(
        synthetic_coords,
        color_scheme='synthetic',
        output_path=output_path,
        title="Synthetic Data: Density Distribution in Latent Space"
    )


# =============================================================================
# Plot e) Severity Distribution Histogram
# =============================================================================

def plot_severity_histogram(historical_severities: np.ndarray,
                            synthetic_severities: np.ndarray,
                            output_path: str = None,
                            n_bins: int = 25,
                            title: str = "Severity Distribution: Historical vs Synthetic") -> plt.Figure:
    """
    Plot overlapping histograms of historical and synthetic severities.
    
    Args:
        historical_severities: Array of historical severity ratios
        synthetic_severities: Array of synthetic severity ratios
        output_path: Optional path to save figure
        n_bins: Number of histogram bins
        title: Figure title
    
    Returns:
        matplotlib Figure
    """
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    fig.suptitle(title, fontsize=14, fontweight='bold', y=1.02)
    
    # Compute common bin edges
    all_severities = np.concatenate([historical_severities, synthetic_severities])
    bin_edges = np.linspace(0, min(all_severities.max() * 1.1, 1.0), n_bins + 1)
    
    # Left plot: Overlapping histograms
    ax1 = axes[0]
    
    ax1.hist(
        historical_severities,
        bins=bin_edges,
        color=COLORS['historical'],
        alpha=0.6,
        label=f'Historical (n={len(historical_severities)})',
        edgecolor='white',
        linewidth=0.5
    )
    
    ax1.hist(
        synthetic_severities,
        bins=bin_edges,
        color=COLORS['synthetic'],
        alpha=0.6,
        label=f'Synthetic (n={len(synthetic_severities)})',
        edgecolor='white',
        linewidth=0.5
    )
    
    ax1.set_xlabel('Severity Ratio', fontsize=11)
    ax1.set_ylabel('Count', fontsize=11)
    ax1.set_title('Overlapping Histograms', fontsize=11, fontweight='bold')
    ax1.legend(loc='upper right', fontsize=9)
    ax1.set_xlim(0, bin_edges[-1])
    
    # Add statistics
    stats_text = (
        f"Historical: μ={historical_severities.mean():.3f}, σ={historical_severities.std():.3f}\n"
        f"Synthetic: μ={synthetic_severities.mean():.3f}, σ={synthetic_severities.std():.3f}"
    )
    ax1.text(0.95, 0.75, stats_text, transform=ax1.transAxes, fontsize=8,
             verticalalignment='top', horizontalalignment='right',
             bbox=dict(boxstyle='round', facecolor='white', alpha=0.8))
    
    # Right plot: Normalized density comparison
    ax2 = axes[1]
    
    ax2.hist(
        historical_severities,
        bins=bin_edges,
        color=COLORS['historical'],
        alpha=0.6,
        density=True,
        label='Historical',
        edgecolor='white',
        linewidth=0.5
    )
    
    ax2.hist(
        synthetic_severities,
        bins=bin_edges,
        color=COLORS['synthetic'],
        alpha=0.6,
        density=True,
        label='Synthetic',
        edgecolor='white',
        linewidth=0.5
    )
    
    # Add KDE curves
    if len(historical_severities) > 10:
        kde_hist = stats.gaussian_kde(historical_severities)
        x_kde = np.linspace(0, bin_edges[-1], 200)
        ax2.plot(x_kde, kde_hist(x_kde), color=COLORS['historical'], 
                 linewidth=2, linestyle='-', label='Historical KDE')
    
    if len(synthetic_severities) > 10:
        kde_syn = stats.gaussian_kde(synthetic_severities)
        ax2.plot(x_kde, kde_syn(x_kde), color=COLORS['synthetic'],
                 linewidth=2, linestyle='-', label='Synthetic KDE')
    
    ax2.set_xlabel('Severity Ratio', fontsize=11)
    ax2.set_ylabel('Density', fontsize=11)
    ax2.set_title('Normalized Density Comparison', fontsize=11, fontweight='bold')
    ax2.legend(loc='upper right', fontsize=9)
    ax2.set_xlim(0, bin_edges[-1])
    
    plt.tight_layout()
    
    if output_path:
        fig.savefig(output_path, dpi=150, bbox_inches='tight', facecolor='white')
        logger.info(f"Saved severity histogram to {output_path}")
    
    return fig


# =============================================================================
# Plot f) Combined Density Comparison (Side by Side)
# =============================================================================

def plot_density_comparison(historical_coords: np.ndarray,
                            synthetic_coords: np.ndarray,
                            output_path: str = None,
                            title: str = "Density Comparison: Historical vs Synthetic") -> plt.Figure:
    """
    Plot historical and synthetic densities side by side for comparison.
    
    Creates a 2x3 grid:
    - Top row: Historical density contours
    - Bottom row: Synthetic density contours
    
    Args:
        historical_coords: Nx3 array of historical latent coordinates
        synthetic_coords: Mx3 array of synthetic latent coordinates
        output_path: Optional path to save figure
        title: Figure title
    
    Returns:
        matplotlib Figure
    """
    fig = plt.figure(figsize=(15, 10))
    gs = GridSpec(2, 3, figure=fig, hspace=0.3, wspace=0.25)
    fig.suptitle(title, fontsize=14, fontweight='bold', y=0.98)
    
    # Compute common axis limits
    all_coords = np.vstack([historical_coords, synthetic_coords])
    limits = []
    for dim in range(3):
        margin = 0.1 * (all_coords[:, dim].max() - all_coords[:, dim].min())
        limits.append((all_coords[:, dim].min() - margin, all_coords[:, dim].max() + margin))
    
    n_levels = 10
    
    for row, (coords, label, cmap) in enumerate([
        (historical_coords, 'Historical', COLORS['contour_hist']),
        (synthetic_coords, 'Synthetic', COLORS['contour_syn'])
    ]):
        for col, ((dim_x, dim_y), (name_x, name_y)) in enumerate(zip(DIM_PAIRS, DIM_PAIR_NAMES)):
            ax = fig.add_subplot(gs[row, col])
            
            # Extract 2D coordinates
            points_2d = coords[:, [dim_x, dim_y]]
            
            # Compute density
            xx, yy, density = compute_density_grid(points_2d)
            
            if density is not None:
                contourf = ax.contourf(xx, yy, density, levels=n_levels, cmap=cmap, alpha=0.8)
                ax.contour(xx, yy, density, levels=n_levels, colors='white', linewidths=0.3, alpha=0.5)
            
            # Overlay points
            point_color = COLORS['historical'] if row == 0 else COLORS['synthetic']
            ax.scatter(coords[:, dim_x], coords[:, dim_y], c=point_color, s=8, alpha=0.2, edgecolors='none')
            
            ax.set_xlim(limits[dim_x])
            ax.set_ylim(limits[dim_y])
            ax.set_xlabel(f'Dim {dim_x + 1}: {name_x}', fontsize=9)
            ax.set_ylabel(f'Dim {dim_y + 1}: {name_y}', fontsize=9)
            
            if col == 0:
                ax.set_ylabel(f'{label}\n\nDim {dim_y + 1}: {name_y}', fontsize=10, fontweight='bold')
            
            if row == 0:
                ax.set_title(f'{name_x} vs {name_y}', fontsize=10, fontweight='bold')
    
    if output_path:
        fig.savefig(output_path, dpi=150, bbox_inches='tight', facecolor='white')
        logger.info(f"Saved density comparison to {output_path}")
    
    return fig


# =============================================================================
# Master Function: Generate All Plots
# =============================================================================

def generate_all_diagnostic_plots(historical_coords: np.ndarray,
                                  synthetic_coords: np.ndarray,
                                  historical_severities: np.ndarray,
                                  synthetic_severities: np.ndarray,
                                  historical_complexities: np.ndarray = None,
                                  output_dir: str = None) -> Dict[str, plt.Figure]:
    """
    Generate all diagnostic plots.
    
    Args:
        historical_coords: Nx3 array of historical latent coordinates
        synthetic_coords: Mx3 array of synthetic latent coordinates
        historical_severities: Array of historical severity ratios
        synthetic_severities: Array of synthetic severity ratios
        historical_complexities: Optional array of historical complexity scores
        output_dir: Optional directory to save all plots
    
    Returns:
        Dictionary of figure names to matplotlib Figure objects
    """
    figures = {}
    
    if output_dir:
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
    
    logger.info("Generating diagnostic plots...")
    
    # a) Latent space scatter
    logger.info("  Plot (a): Latent space projections")
    figures['latent_space'] = plot_latent_space(
        historical_coords,
        severities=historical_severities,
        complexities=historical_complexities,
        output_path=str(output_path / 'a_latent_space.png') if output_dir else None
    )
    
    # b) Coverage scatter
    logger.info("  Plot (b): Coverage scatter comparison")
    figures['coverage_scatter'] = plot_coverage_scatter(
        historical_coords,
        synthetic_coords,
        output_path=str(output_path / 'b_coverage_scatter.png') if output_dir else None
    )
    
    # c) Historical density contours
    logger.info("  Plot (c): Historical density contours")
    figures['historical_density'] = plot_historical_density(
        historical_coords,
        output_path=str(output_path / 'c_historical_density.png') if output_dir else None
    )
    
    # d) Synthetic density contours
    logger.info("  Plot (d): Synthetic density contours")
    figures['synthetic_density'] = plot_synthetic_density(
        synthetic_coords,
        output_path=str(output_path / 'd_synthetic_density.png') if output_dir else None
    )
    
    # e) Severity histogram
    logger.info("  Plot (e): Severity distribution histogram")
    figures['severity_histogram'] = plot_severity_histogram(
        historical_severities,
        synthetic_severities,
        output_path=str(output_path / 'e_severity_histogram.png') if output_dir else None
    )
    
    # Bonus: Combined density comparison
    logger.info("  Plot (f): Combined density comparison")
    figures['density_comparison'] = plot_density_comparison(
        historical_coords,
        synthetic_coords,
        output_path=str(output_path / 'f_density_comparison.png') if output_dir else None
    )
    
    logger.info(f"Generated {len(figures)} diagnostic plots")
    
    return figures


# =============================================================================
# CLI
# =============================================================================

def main():
    """Command-line interface for generating diagnostic plots."""
    import argparse
    
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    
    parser = argparse.ArgumentParser(description="Generate diagnostic plots for stress test system")
    parser.add_argument('--historical', '-h', required=True,
                        help='Path to historical prepared data JSON')
    parser.add_argument('--synthetic', '-s', required=True,
                        help='Path to synthetic scenarios JSON')
    parser.add_argument('--embedding-space', '-e',
                        help='Path to embedding space directory')
    parser.add_argument('--output', '-o', default='results/stress_test/plots',
                        help='Output directory for plots')
    parser.add_argument('--plot', '-p', choices=['all', 'latent', 'coverage', 'hist_density', 
                                                   'syn_density', 'histogram', 'comparison'],
                        default='all', help='Which plot to generate')
    
    args = parser.parse_args()
    
    # Load historical data
    logger.info(f"Loading historical data from {args.historical}")
    with open(args.historical, 'r') as f:
        hist_data = json.load(f)
    
    movements = hist_data.get('movements', hist_data)
    if isinstance(movements, dict):
        movements = [movements]
    
    historical_severities = np.array([m['severity_ratio'] for m in movements])
    historical_complexities = np.array([m.get('complexity_score', 100) for m in movements])
    
    # Load synthetic data
    logger.info(f"Loading synthetic data from {args.synthetic}")
    with open(args.synthetic, 'r') as f:
        syn_data = json.load(f)
    
    scenarios = syn_data.get('scenarios', syn_data)
    synthetic_severities = np.array([s['severity_ratio'] for s in scenarios])
    
    # Load latent coordinates
    if args.embedding_space:
        logger.info(f"Loading embedding space from {args.embedding_space}")
        historical_coords = np.load(Path(args.embedding_space) / 'latent_coords.npy')
        
        # Project synthetic scenarios
        synthetic_coords = np.array([
            s.get('latent_coords', [0, 0, 0]) for s in scenarios
        ])
    else:
        # Generate random coords for testing
        logger.warning("No embedding space provided, using random coordinates for demo")
        historical_coords = np.random.randn(len(movements), 3)
        synthetic_coords = np.random.randn(len(scenarios), 3)
    
    # Create output directory
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Generate plots
    if args.plot == 'all':
        figures = generate_all_diagnostic_plots(
            historical_coords,
            synthetic_coords,
            historical_severities,
            synthetic_severities,
            historical_complexities,
            output_dir=str(output_dir)
        )
        print(f"\nGenerated {len(figures)} plots in {output_dir}")
    else:
        plot_map = {
            'latent': lambda: plot_latent_space(
                historical_coords, historical_severities, historical_complexities,
                output_path=str(output_dir / 'latent_space.png')
            ),
            'coverage': lambda: plot_coverage_scatter(
                historical_coords, synthetic_coords,
                output_path=str(output_dir / 'coverage_scatter.png')
            ),
            'hist_density': lambda: plot_historical_density(
                historical_coords,
                output_path=str(output_dir / 'historical_density.png')
            ),
            'syn_density': lambda: plot_synthetic_density(
                synthetic_coords,
                output_path=str(output_dir / 'synthetic_density.png')
            ),
            'histogram': lambda: plot_severity_histogram(
                historical_severities, synthetic_severities,
                output_path=str(output_dir / 'severity_histogram.png')
            ),
            'comparison': lambda: plot_density_comparison(
                historical_coords, synthetic_coords,
                output_path=str(output_dir / 'density_comparison.png')
            )
        }
        
        fig = plot_map[args.plot]()
        print(f"\nGenerated {args.plot} plot in {output_dir}")
    
    plt.show()


if __name__ == "__main__":
    main()
