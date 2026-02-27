"""Shared utilities for novelty analysis scripts.

Provides: severity projection math, tail metrics, time windowing,
query portfolio definitions, and the unified analysis table builder.
"""

from .severity_projection import (
    lob_weights_to_array,
    beta_lob_array,
    project_severity,
    composite_beta,
    size_adjustment_factor,
    adjusted_severity,
    cap_severity,
)
from .tail_metrics import (
    empirical_var,
    empirical_tvar,
    hill_estimator,
    mean_excess_function,
    tail_ratio,
    bootstrap_ci,
    cluster_bootstrap_syndicate,
    cluster_bootstrap_year,
    bootstrap_quantiles,
)
from .time_windows import (
    rolling_windows,
    year_summary_stats,
    quantile_trend,
)
from .query_portfolios import (
    PROPERTY_HEAVY,
    CASUALTY_HEAVY,
    SIZES_M,
    compute_market_average_mix,
    get_query_portfolios,
)
from .analysis_table import (
    build_analysis_table,
    add_query_columns,
    get_subset,
    load_or_build,
    CoverageStats,
)
