"""
Stress Test Generation System for Lloyd's Reserve Risk

This package implements a hybrid LLM + EVT approach for generating
stress test scenarios with causal narratives.

Modules:
- config: Configuration and data structures
- data_preparation: Prepare historical data with complexity scores
- joint_embedding: Joint semantic-numeric embedding space
- evt_threshold: GPD threshold selection using EVT techniques
- synthetic_generation: Stratified synthetic scenario generation
- coverage_validation: Semantic space coverage testing
- importance_sampling: Match severity distribution to GPD
- coherence_validation: Narrative-severity coherence checks
- portfolio_query: Portfolio-specific scenario selection
- visualization: Embedding and coverage plots
- evt_visualization: EVT diagnostic plots
- pipeline: Main orchestration
"""

import sys
from pathlib import Path
_script_dir = Path(__file__).resolve().parent
if str(_script_dir) not in sys.path:
    sys.path.insert(0, str(_script_dir))

from config import (
    LLOYDS_LOBS,
    LOB_TO_INDEX,
    CauseCategory,
    EmbeddingConfig,
    EVTConfig,
    GenerationConfig,
    ValidationConfig,
    QueryConfig,
    HistoricalMovement,
    SyntheticScenario,
    PortfolioSpec,
    StressScenario,
)

from visualization import (
    plot_latent_space,
    plot_coverage_scatter,
    plot_historical_density,
    plot_synthetic_density,
    plot_severity_histogram,
    plot_density_comparison,
    generate_all_diagnostic_plots,
)

from evt_visualization import (
    plot_shape_stability,
    plot_scale_stability,
    plot_qq_gpd,
    plot_pp_gpd,
    plot_density_gpd,
    plot_loglog_tail,
    plot_loglog_linearity,
    plot_mean_excess,
    plot_ad_vs_threshold,
    plot_evt_summary,
    generate_evt_diagnostic_plots,
)

__all__ = [
    'LLOYDS_LOBS',
    'LOB_TO_INDEX', 
    'CauseCategory',
    'EmbeddingConfig',
    'EVTConfig',
    'GenerationConfig',
    'ValidationConfig',
    'QueryConfig',
    'HistoricalMovement',
    'SyntheticScenario',
    'PortfolioSpec',
    'StressScenario',
    # Embedding/Coverage Visualization
    'plot_latent_space',
    'plot_coverage_scatter',
    'plot_historical_density',
    'plot_synthetic_density',
    'plot_severity_histogram',
    'plot_density_comparison',
    'generate_all_diagnostic_plots',
    # EVT Visualization
    'plot_shape_stability',
    'plot_scale_stability',
    'plot_qq_gpd',
    'plot_pp_gpd',
    'plot_density_gpd',
    'plot_loglog_tail',
    'plot_loglog_linearity',
    'plot_mean_excess',
    'plot_ad_vs_threshold',
    'plot_evt_summary',
    'generate_evt_diagnostic_plots',
]
