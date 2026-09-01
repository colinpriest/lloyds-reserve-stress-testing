"""
Portfolio Size Diversification Analysis

Tests four data-driven approaches to estimate how reserve severity
varies with portfolio size, while preserving semantic links to scenarios.

Approaches:
1. Common Event Matching - same event, different syndicates
2. Within-Syndicate Volatility Scaling - panel volatility vs size
3. LOB-Specific Size Effects with Hierarchical Shrinkage
4. Relative Severity Rankings Within Event Cohorts

For each approach, we assess:
- Data sufficiency (sample sizes, coverage)
- Statistical robustness (significance, stability)
- Sensibility (correct sign, plausible magnitude)
- Convergence (do approaches agree?)

Author: Colin Priest
Date: December 2024
"""

import json
import logging
import numpy as np
import pandas as pd
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass, field
from collections import defaultdict
import warnings

# Statistical imports
from scipy import stats
from scipy.cluster.hierarchy import linkage, fcluster
from scipy.spatial.distance import pdist, squareform
import statsmodels.api as sm
from statsmodels.regression.quantile_regression import QuantReg
from statsmodels.stats.diagnostic import het_breuschpagan
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.cluster import AgglomerativeClustering

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


# =============================================================================
# Data Classes for Results
# =============================================================================

@dataclass
class ApproachDiagnostics:
    """Diagnostics for a single approach."""
    name: str
    description: str
    
    # Data sufficiency
    n_observations: int = 0
    n_syndicates: int = 0
    n_years: int = 0
    n_events: int = 0  # For event-based approaches
    min_obs_per_group: int = 0
    data_sufficient: bool = False
    data_issues: List[str] = field(default_factory=list)
    
    # Statistical results
    size_coefficient: Optional[float] = None
    size_coefficient_se: Optional[float] = None
    size_coefficient_pvalue: Optional[float] = None
    r_squared: Optional[float] = None
    
    # LOB-specific coefficients (for approach 3)
    lob_coefficients: Dict[str, float] = field(default_factory=dict)
    lob_coefficients_se: Dict[str, float] = field(default_factory=dict)
    
    # Robustness
    bootstrap_mean: Optional[float] = None
    bootstrap_std: Optional[float] = None
    bootstrap_ci_lower: Optional[float] = None
    bootstrap_ci_upper: Optional[float] = None
    cv_stability: Optional[float] = None  # CV of estimates across folds
    
    # Sensibility checks
    sign_correct: bool = False  # Expect negative (larger = less volatile)
    magnitude_plausible: bool = False  # Expect -0.1 to -0.7 roughly
    
    # Overall assessment
    statistically_significant: bool = False
    robust: bool = False
    trustworthy: bool = False
    recommendation: str = ""
    
    def to_dict(self) -> Dict:
        return {
            'name': self.name,
            'description': self.description,
            'data_sufficiency': {
                'n_observations': self.n_observations,
                'n_syndicates': self.n_syndicates,
                'n_years': self.n_years,
                'n_events': self.n_events,
                'min_obs_per_group': self.min_obs_per_group,
                'sufficient': self.data_sufficient,
                'issues': self.data_issues
            },
            'estimates': {
                'size_coefficient': self.size_coefficient,
                'size_coefficient_se': self.size_coefficient_se,
                'size_coefficient_pvalue': self.size_coefficient_pvalue,
                'r_squared': self.r_squared,
                'lob_coefficients': self.lob_coefficients
            },
            'robustness': {
                'bootstrap_mean': self.bootstrap_mean,
                'bootstrap_std': self.bootstrap_std,
                'bootstrap_ci': [self.bootstrap_ci_lower, self.bootstrap_ci_upper],
                'cv_stability': self.cv_stability
            },
            'assessment': {
                'sign_correct': self.sign_correct,
                'magnitude_plausible': self.magnitude_plausible,
                'statistically_significant': self.statistically_significant,
                'robust': self.robust,
                'trustworthy': self.trustworthy,
                'recommendation': self.recommendation
            }
        }


@dataclass 
class AnalysisResults:
    """Complete analysis results."""
    corpus_summary: Dict[str, Any]
    approach_results: Dict[str, ApproachDiagnostics]
    convergence_analysis: Dict[str, Any]
    overall_recommendation: str
    
    def to_dict(self) -> Dict:
        return {
            'corpus_summary': self.corpus_summary,
            'approaches': {k: v.to_dict() for k, v in self.approach_results.items()},
            'convergence': self.convergence_analysis,
            'overall_recommendation': self.overall_recommendation
        }


# =============================================================================
# Data Loading and Preparation
# =============================================================================

def load_corpus(corpus_path: str) -> pd.DataFrame:
    """Load and prepare corpus data for analysis."""
    
    with open(corpus_path, 'r') as f:
        data = json.load(f)
    
    movements = data.get('movements', [])
    logger.info(f"Loaded {len(movements)} movements from corpus")
    
    # Debug: show available fields
    if movements:
        sample_keys = list(movements[0].keys())
        logger.info(f"Available fields: {sample_keys}")
    
    records = []
    for m in movements:
        # Extract core fields - try multiple possible field names
        record = {}
        
        # Syndicate ID
        record['syndicate'] = (
            m.get('syndicate') or 
            m.get('syndicate_id') or 
            m.get('syndicate_number') or
            m.get('id')
        )
        
        # Year
        record['year'] = (
            m.get('year') or 
            m.get('reporting_year') or
            m.get('accident_year')
        )
        
        # Severity ratio - try multiple names
        record['severity_ratio'] = (
            m.get('severity_ratio') or
            m.get('severity') or
            m.get('reserve_movement_pct') or
            m.get('movement_ratio') or
            m.get('pct_change')
        )
        
        # Also check if it's stored as a decimal that needs no conversion
        # or if it's in a nested structure
        if record['severity_ratio'] is None:
            # Try nested paths
            if 'metrics' in m:
                record['severity_ratio'] = m['metrics'].get('severity_ratio')
            elif 'reserve_movement' in m and 'prior_reserves' in m:
                # Calculate from raw values
                movement = m.get('reserve_movement', 0)
                prior = m.get('prior_reserves', 0)
                if prior and prior != 0:
                    record['severity_ratio'] = movement / prior
        
        # Narrative text
        record['narrative'] = (
            m.get('narrative') or 
            m.get('text') or 
            m.get('commentary') or
            m.get('description') or
            m.get('summary') or
            ''
        )
        
        # Cause category
        record['cause_category'] = (
            m.get('cause_category') or 
            m.get('cause') or
            m.get('peril') or
            m.get('category') or
            'unknown'
        )
        
        # Line of business
        record['line_of_business'] = (
            m.get('line_of_business') or 
            m.get('lob') or
            m.get('class_of_business') or
            m.get('business_class') or
            'unknown'
        )
        
        # Size proxies - try multiple fields
        record['size'] = (
            m.get('prior_reserves_gbp_m') or 
            m.get('prior_reserves') or
            m.get('reserves_gbp_m') or
            m.get('reserves') or
            m.get('stamp_capacity_gbp_m') or
            m.get('stamp_capacity') or
            m.get('capacity') or
            m.get('gross_premium_gbp_m') or
            m.get('premium') or
            m.get('size')
        )
        
        # LOB breakdown if available
        lob_breakdown = m.get('lob_breakdown', {}) or m.get('lob_split', {}) or {}
        if lob_breakdown:
            total = sum(v for v in lob_breakdown.values() if isinstance(v, (int, float)))
            if total > 0:
                for lob, val in lob_breakdown.items():
                    if isinstance(val, (int, float)):
                        record[f'lob_share_{lob}'] = val / total
        
        records.append(record)
    
    df = pd.DataFrame(records)
    
    # Show what we got before filtering
    logger.info(f"Extracted {len(df)} records")
    logger.info(f"  severity_ratio non-null: {df['severity_ratio'].notna().sum()}")
    logger.info(f"  size non-null: {df['size'].notna().sum()}")
    logger.info(f"  syndicate non-null: {df['syndicate'].notna().sum()}")
    logger.info(f"  year non-null: {df['year'].notna().sum()}")
    
    # Show sample of data
    if len(df) > 0:
        logger.info(f"\nSample record:")
        for col in ['syndicate', 'year', 'severity_ratio', 'size', 'line_of_business']:
            if col in df.columns:
                val = df[col].iloc[0]
                logger.info(f"  {col}: {val}")
    
    # Filter to complete records
    required_cols = ['severity_ratio', 'size']
    available_required = [c for c in required_cols if c in df.columns and df[c].notna().any()]
    
    if len(available_required) < 2:
        # Show what fields exist in raw data for debugging
        if movements:
            logger.error("Could not find required fields. Raw data sample:")
            for k, v in list(movements[0].items())[:20]:
                logger.error(f"  {k}: {repr(v)[:80]}")
        raise ValueError(f"Missing required fields. Need severity_ratio and size. Found: {available_required}")
    
    # Drop rows with missing key fields
    df = df.dropna(subset=available_required)
    
    # Add syndicate and year filtering only if those columns exist and have data
    if 'syndicate' in df.columns and df['syndicate'].notna().any():
        df = df[df['syndicate'].notna()]
    if 'year' in df.columns and df['year'].notna().any():
        df = df[df['year'].notna()]
    
    if len(df) == 0:
        raise ValueError("No valid records after filtering for required fields")
    
    # Ensure numeric types for key columns
    df['size'] = pd.to_numeric(df['size'], errors='coerce')
    df['severity_ratio'] = pd.to_numeric(df['severity_ratio'], errors='coerce')
    
    # Filter to valid data
    df = df[df['size'] > 0]
    df = df[df['severity_ratio'].notna()]
    
    # Handle extreme outliers in severity_ratio
    # Winsorize at 1st and 99th percentiles to reduce influence of data errors
    severity_p01 = df['severity_ratio'].quantile(0.01)
    severity_p99 = df['severity_ratio'].quantile(0.99)
    n_outliers = ((df['severity_ratio'] < severity_p01) | (df['severity_ratio'] > severity_p99)).sum()
    if n_outliers > 0:
        logger.info(f"  Winsorizing {n_outliers} extreme severity values (outside [{severity_p01:.1%}, {severity_p99:.1%}])")
        df['severity_ratio'] = df['severity_ratio'].clip(lower=severity_p01, upper=severity_p99)
    
    # Compute log size
    df['log_size'] = np.log(df['size'].clip(lower=1))
    
    # Ensure year is numeric
    if 'year' in df.columns:
        df['year'] = pd.to_numeric(df['year'], errors='coerce')
    
    # Ensure syndicate is consistent type (string for grouping)
    if 'syndicate' in df.columns:
        df['syndicate'] = df['syndicate'].astype(str)
    
    # Identify LOB columns
    lob_cols = [c for c in df.columns if c.startswith('lob_share_')]
    
    logger.info(f"\nPrepared {len(df)} observations with size and severity")
    if 'syndicate' in df.columns:
        logger.info(f"  Syndicates: {df['syndicate'].nunique()}")
    if 'year' in df.columns:
        logger.info(f"  Years: {df['year'].nunique()} ({df['year'].min()}-{df['year'].max()})")
    logger.info(f"  LOB columns: {len(lob_cols)}")
    logger.info(f"  Severity range: {df['severity_ratio'].min():.2%} to {df['severity_ratio'].max():.2%}")
    logger.info(f"  Size range: {df['size'].min():.1f} to {df['size'].max():.1f}")
    
    return df


def summarise_corpus(df: pd.DataFrame) -> Dict[str, Any]:
    """Generate summary statistics for the corpus."""
    
    lob_cols = [c for c in df.columns if c.startswith('lob_share_')]
    
    summary = {
        'n_observations': len(df),
        'n_syndicates': df['syndicate'].nunique() if 'syndicate' in df.columns else 0,
        'n_years': df['year'].nunique() if 'year' in df.columns else 0,
        'year_range': [int(df['year'].min()), int(df['year'].max())] if 'year' in df.columns and df['year'].notna().any() else [0, 0],
        'severity_stats': {
            'mean': float(df['severity_ratio'].mean()),
            'std': float(df['severity_ratio'].std()),
            'median': float(df['severity_ratio'].median()),
            'min': float(df['severity_ratio'].min()),
            'max': float(df['severity_ratio'].max()),
            'pct_adverse': float((df['severity_ratio'] > 0).mean())
        },
        'size_stats': {
            'mean': float(df['size'].mean()),
            'std': float(df['size'].std()),
            'median': float(df['size'].median()),
            'min': float(df['size'].min()),
            'max': float(df['size'].max()),
            'log_size_range': [float(df['log_size'].min()), float(df['log_size'].max())]
        },
        'lob_coverage': {
            col.replace('lob_share_', ''): float(df[col].notna().mean()) 
            for col in lob_cols
        } if lob_cols else {},
        'cause_categories': df['cause_category'].value_counts().to_dict() if 'cause_category' in df.columns else {},
        'line_of_business': df['line_of_business'].value_counts().to_dict() if 'line_of_business' in df.columns else {},
    }
    
    if 'syndicate' in df.columns and df['syndicate'].notna().any():
        obs_per_synd = df.groupby('syndicate').size()
        summary['obs_per_syndicate'] = {
            'mean': float(obs_per_synd.mean()),
            'min': int(obs_per_synd.min()),
            'max': int(obs_per_synd.max())
        }
    else:
        summary['obs_per_syndicate'] = {'mean': 0, 'min': 0, 'max': 0}
    
    return summary


# =============================================================================
# Approach 1: Common Event Matching
# =============================================================================

def identify_common_events(df: pd.DataFrame, 
                           min_syndicates: int = 3,
                           similarity_threshold: float = 0.3) -> pd.DataFrame:
    """
    Identify common events affecting multiple syndicates.
    
    Uses combination of:
    - Same year + same cause category
    - Narrative text similarity
    """
    
    # Check required columns
    has_year = 'year' in df.columns and df['year'].notna().any()
    has_syndicate = 'syndicate' in df.columns and df['syndicate'].notna().any()
    has_cause = 'cause_category' in df.columns and df['cause_category'].notna().any()
    has_narrative = 'narrative' in df.columns and df['narrative'].notna().any()
    
    if not has_syndicate:
        logger.warning("No syndicate column - cannot identify common events")
        return pd.DataFrame()
    
    df = df.copy()
    
    # Create grouping key based on available fields
    if has_year and has_cause:
        df['group_key'] = df['year'].astype(str) + '_' + df['cause_category'].fillna('unknown')
    elif has_year:
        df['group_key'] = df['year'].astype(str)
    elif has_cause:
        df['group_key'] = df['cause_category'].fillna('unknown')
    else:
        logger.warning("No year or cause_category column - using narrative clustering only")
        df['group_key'] = 'all'
    
    # Count syndicates per group
    group_counts = df.groupby('group_key')['syndicate'].nunique()
    valid_groups = group_counts[group_counts >= min_syndicates].index
    
    logger.info(f"Found {len(valid_groups)} group combinations with >= {min_syndicates} syndicates")
    
    # Identify events
    events = []
    event_id = 0
    
    # If we have year, iterate by year
    if has_year:
        year_values = df['year'].unique()
    else:
        year_values = ['all']
    
    for year_val in year_values:
        if has_year:
            year_df = df[df['year'] == year_val].copy()
        else:
            year_df = df.copy()
        
        if len(year_df) < min_syndicates:
            continue
        
        # Compute narrative similarity
        narratives = year_df['narrative'].fillna('').tolist() if 'narrative' in year_df.columns else [''] * len(year_df)
        
        if not any(narratives) or not has_narrative:
            # Fall back to cause grouping
            if has_cause:
                for cause in year_df['cause_category'].dropna().unique():
                    cause_df = year_df[year_df['cause_category'] == cause]
                    if len(cause_df) >= min_syndicates:
                        for idx in cause_df.index:
                            events.append({
                                'index': idx,
                                'event_id': event_id,
                                'event_type': 'year_cause',
                                'event_desc': f"{year_val}_{cause}"
                            })
                        event_id += 1
            continue
        
        # TF-IDF similarity
        try:
            vectorizer = TfidfVectorizer(max_features=500, stop_words='english')
            tfidf = vectorizer.fit_transform(narratives)
            sim_matrix = cosine_similarity(tfidf)
            
            # Cluster based on similarity
            # Convert similarity to distance
            dist_matrix = 1 - sim_matrix
            np.fill_diagonal(dist_matrix, 0)
            dist_matrix = np.clip(dist_matrix, 0, 1)
            
            if len(year_df) >= 2:
                clustering = AgglomerativeClustering(
                    n_clusters=None,
                    distance_threshold=1 - similarity_threshold,
                    metric='precomputed',
                    linkage='average'
                )
                clusters = clustering.fit_predict(dist_matrix)
                
                # Find clusters with enough syndicates
                cluster_counts = pd.Series(clusters).value_counts()
                valid_clusters = cluster_counts[cluster_counts >= min_syndicates].index
                
                for cluster_id in valid_clusters:
                    cluster_mask = clusters == cluster_id
                    cluster_indices = year_df.index[cluster_mask]
                    
                    # Get representative narrative snippet
                    if has_cause:
                        common_cause = year_df.loc[cluster_indices, 'cause_category'].mode()
                        common_cause = common_cause.iloc[0] if len(common_cause) > 0 else 'mixed'
                    else:
                        common_cause = 'unknown'
                    
                    for idx in cluster_indices:
                        events.append({
                            'index': idx,
                            'event_id': event_id,
                            'event_type': 'narrative_cluster',
                            'event_desc': f"{year_val}_{common_cause}_cluster{cluster_id}"
                        })
                    event_id += 1
                    
        except Exception as e:
            logger.warning(f"Clustering failed for {year_val}: {e}")
            # Fall back to cause grouping
            if has_cause:
                for cause in year_df['cause_category'].dropna().unique():
                    cause_df = year_df[year_df['cause_category'] == cause]
                    if len(cause_df) >= min_syndicates:
                        for idx in cause_df.index:
                            events.append({
                                'index': idx,
                                'event_id': event_id,
                                'event_type': 'year_cause_fallback',
                                'event_desc': f"{year_val}_{cause}"
                            })
                        event_id += 1
    
    if not events:
        logger.warning("No common events identified")
        return pd.DataFrame()
    
    events_df = pd.DataFrame(events).set_index('index')
    df_with_events = df.join(events_df, how='inner')
    
    logger.info(f"Identified {event_id} distinct events covering {len(df_with_events)} observations")
    
    return df_with_events


def run_approach_1_common_events(df: pd.DataFrame, n_bootstrap: int = 200) -> ApproachDiagnostics:
    """
    Test Approach 1: Common Event Matching
    
    Estimate size effect from variation in severity across syndicates
    experiencing the same event.
    """
    
    diag = ApproachDiagnostics(
        name="Common Event Matching",
        description="Estimate size effect from same-event, different-syndicate variation"
    )
    
    # Identify common events
    df_events = identify_common_events(df, min_syndicates=3)
    
    if len(df_events) == 0:
        diag.data_issues.append("No common events identified with >= 3 syndicates")
        diag.recommendation = "INSUFFICIENT DATA - Cannot identify common events"
        return diag
    
    # Data sufficiency
    diag.n_observations = len(df_events)
    diag.n_syndicates = df_events['syndicate'].nunique()
    diag.n_events = df_events['event_id'].nunique()
    
    event_sizes = df_events.groupby('event_id').size()
    diag.min_obs_per_group = int(event_sizes.min())
    
    # Check sufficiency
    if diag.n_events < 5:
        diag.data_issues.append(f"Only {diag.n_events} events identified (need >= 5)")
    if diag.n_observations < 30:
        diag.data_issues.append(f"Only {diag.n_observations} observations (need >= 30)")
    if diag.min_obs_per_group < 3:
        diag.data_issues.append(f"Some events have only {diag.min_obs_per_group} syndicates")
    
    diag.data_sufficient = len(diag.data_issues) == 0
    
    # Fit model: severity ~ log_size + event fixed effects (+ LOB controls if available)
    # Use within-event variation
    
    try:
        # Create event dummies - ensure event_id is string for consistent dummies
        df_events = df_events.copy()
        df_events['event_id'] = df_events['event_id'].astype(str)
        event_dummies = pd.get_dummies(df_events['event_id'], prefix='event', drop_first=True)
        
        # Ensure all columns are float64
        event_dummies = event_dummies.astype(np.float64)
        
        # LOB controls if available
        lob_cols = [c for c in df_events.columns if c.startswith('lob_share_')]
        
        # Build design matrix - ensure numeric types
        X = df_events[['log_size']].copy().astype(np.float64)
        X = X.reset_index(drop=True)
        event_dummies = event_dummies.reset_index(drop=True)
        X = pd.concat([X, event_dummies], axis=1)
        
        if lob_cols:
            # Add LOB controls (drop one for identification)
            lob_data = df_events[lob_cols].fillna(0).astype(np.float64).reset_index(drop=True)
            if len(lob_cols) > 1:
                X = pd.concat([X, lob_data.iloc[:, :-1]], axis=1)
        
        X = sm.add_constant(X)
        y = df_events['severity_ratio'].astype(np.float64).reset_index(drop=True)
        
        # OLS regression
        model = sm.OLS(y, X).fit()
        
        diag.size_coefficient = float(model.params['log_size'])
        diag.size_coefficient_se = float(model.bse['log_size'])
        diag.size_coefficient_pvalue = float(model.pvalues['log_size'])
        diag.r_squared = float(model.rsquared)
        
        # Significance
        diag.statistically_significant = diag.size_coefficient_pvalue < 0.05
        
        # Sign and magnitude checks
        diag.sign_correct = diag.size_coefficient < 0  # Expect negative
        diag.magnitude_plausible = -0.7 < diag.size_coefficient < 0.1  # Reasonable range
        
        # Bootstrap for robustness
        bootstrap_coefs = []
        for _ in range(n_bootstrap):
            # Resample events (cluster bootstrap)
            event_ids = df_events['event_id'].unique()
            sampled_events = np.random.choice(event_ids, size=len(event_ids), replace=True)
            
            boot_dfs = [df_events[df_events['event_id'] == e] for e in sampled_events]
            boot_df = pd.concat(boot_dfs, ignore_index=True)
            
            if len(boot_df) < 10:
                continue
            
            try:
                # Rebuild design matrix
                boot_event_dummies = pd.get_dummies(boot_df['event_id'], prefix='event', drop_first=True)
                boot_X = boot_df[['log_size']].copy()
                boot_X = pd.concat([boot_X.reset_index(drop=True), 
                                   boot_event_dummies.reset_index(drop=True)], axis=1)
                boot_X = sm.add_constant(boot_X)
                boot_y = boot_df['severity_ratio'].reset_index(drop=True)
                
                boot_model = sm.OLS(boot_y, boot_X).fit()
                bootstrap_coefs.append(boot_model.params['log_size'])
            except:
                continue
        
        if len(bootstrap_coefs) >= 50:
            diag.bootstrap_mean = float(np.mean(bootstrap_coefs))
            diag.bootstrap_std = float(np.std(bootstrap_coefs))
            diag.bootstrap_ci_lower = float(np.percentile(bootstrap_coefs, 2.5))
            diag.bootstrap_ci_upper = float(np.percentile(bootstrap_coefs, 97.5))
            
            # Robust if CI doesn't include zero (or barely includes it)
            diag.robust = (diag.bootstrap_ci_upper < 0.05) or (diag.bootstrap_ci_lower > -0.05 and diag.size_coefficient < 0)
        
        # Overall assessment
        diag.trustworthy = (
            diag.data_sufficient and 
            diag.statistically_significant and 
            diag.sign_correct and 
            diag.magnitude_plausible
        )
        
        if diag.trustworthy:
            diag.recommendation = f"RECOMMENDED - Coefficient {diag.size_coefficient:.4f} is significant and plausible"
        elif diag.data_sufficient and diag.sign_correct:
            diag.recommendation = f"USABLE WITH CAUTION - Coefficient {diag.size_coefficient:.4f}, p={diag.size_coefficient_pvalue:.3f}"
        else:
            issues = []
            if not diag.data_sufficient:
                issues.append("insufficient data")
            if not diag.sign_correct:
                issues.append("wrong sign")
            if not diag.magnitude_plausible:
                issues.append("implausible magnitude")
            diag.recommendation = f"NOT RECOMMENDED - Issues: {', '.join(issues)}"
            
    except Exception as e:
        diag.data_issues.append(f"Model fitting failed: {str(e)}")
        diag.recommendation = f"FAILED - {str(e)}"
    
    return diag


# =============================================================================
# Approach 2: Within-Syndicate Volatility Scaling
# =============================================================================

def run_approach_2_volatility_scaling(df: pd.DataFrame, n_bootstrap: int = 200) -> ApproachDiagnostics:
    """
    Test Approach 2: Within-Syndicate Volatility Scaling
    
    Estimate relationship between syndicate size and severity volatility.
    """
    
    diag = ApproachDiagnostics(
        name="Within-Syndicate Volatility Scaling",
        description="Estimate size-volatility relationship from panel data"
    )
    
    # Check if we have syndicate column
    if 'syndicate' not in df.columns or not df['syndicate'].notna().any():
        diag.data_issues.append("No syndicate identifier available - cannot compute within-syndicate volatility")
        diag.data_sufficient = False
        diag.recommendation = "NOT APPLICABLE - No syndicate panel data available"
        return diag
    
    # Need multiple observations per syndicate
    syndicate_counts = df.groupby('syndicate').size()
    syndicates_with_panel = syndicate_counts[syndicate_counts >= 3].index
    
    df_panel = df[df['syndicate'].isin(syndicates_with_panel)].copy()
    
    diag.n_observations = len(df_panel)
    diag.n_syndicates = len(syndicates_with_panel)
    diag.n_years = df_panel['year'].nunique() if 'year' in df_panel.columns else 0
    diag.min_obs_per_group = int(syndicate_counts[syndicates_with_panel].min()) if len(syndicates_with_panel) > 0 else 0
    
    if diag.n_syndicates < 10:
        diag.data_issues.append(f"Only {diag.n_syndicates} syndicates with >= 3 observations")
    if diag.n_syndicates < 5:
        diag.data_sufficient = False
        diag.recommendation = "INSUFFICIENT DATA - Need more syndicates with panel data"
        return diag
    
    diag.data_sufficient = len(diag.data_issues) == 0
    
    try:
        # Step 1: Remove LOB and year effects
        lob_cols = [c for c in df_panel.columns if c.startswith('lob_share_')]
        
        # Build adjustment model - only include year if available
        X_adjust_parts = []
        
        if 'year' in df_panel.columns and df_panel['year'].notna().any():
            df_panel['year'] = df_panel['year'].astype(str)  # Ensure consistent type for dummies
            year_dummies = pd.get_dummies(df_panel['year'], prefix='year', drop_first=True).astype(np.float64)
            X_adjust_parts.append(year_dummies.reset_index(drop=True))
        
        if lob_cols:
            lob_data = df_panel[lob_cols].fillna(0).astype(np.float64).reset_index(drop=True)
            X_adjust_parts.append(lob_data)
        
        if X_adjust_parts:
            X_adjust = pd.concat(X_adjust_parts, axis=1)
            X_adjust = sm.add_constant(X_adjust)
            y_adjust = df_panel['severity_ratio'].astype(np.float64).reset_index(drop=True)
            adjust_model = sm.OLS(y_adjust, X_adjust).fit()
            df_panel = df_panel.copy()
            df_panel['residual'] = adjust_model.resid.values
        else:
            # No adjustments - use raw severity
            df_panel = df_panel.copy()
            df_panel['residual'] = df_panel['severity_ratio'] - df_panel['severity_ratio'].mean()
        
        # Step 2: Compute volatility per syndicate
        # Ensure residual and size are float64
        df_panel['residual'] = df_panel['residual'].astype(np.float64)
        df_panel['size'] = df_panel['size'].astype(np.float64)
        df_panel['log_size'] = df_panel['log_size'].astype(np.float64)
        
        syndicate_stats = df_panel.groupby('syndicate').agg({
            'residual': ['std', 'count'],
            'size': 'mean',
            'log_size': 'mean'
        })
        syndicate_stats.columns = ['resid_std', 'n_obs', 'mean_size', 'mean_log_size']
        syndicate_stats = syndicate_stats[syndicate_stats['resid_std'] > 0]  # Remove zero variance
        
        # Ensure all columns are float64
        for col in syndicate_stats.columns:
            syndicate_stats[col] = syndicate_stats[col].astype(np.float64)
        
        syndicate_stats['log_volatility'] = np.log(syndicate_stats['resid_std'])
        
        # Step 3: Regress log(volatility) on log(size)
        X = sm.add_constant(syndicate_stats['mean_log_size'].astype(np.float64))
        y = syndicate_stats['log_volatility'].astype(np.float64)
        
        vol_model = sm.OLS(y, X).fit()
        
        diag.size_coefficient = float(vol_model.params['mean_log_size'])
        diag.size_coefficient_se = float(vol_model.bse['mean_log_size'])
        diag.size_coefficient_pvalue = float(vol_model.pvalues['mean_log_size'])
        diag.r_squared = float(vol_model.rsquared)
        
        diag.statistically_significant = diag.size_coefficient_pvalue < 0.05
        diag.sign_correct = diag.size_coefficient < 0  # Larger = lower volatility
        diag.magnitude_plausible = -0.8 < diag.size_coefficient < 0.1
        
        # Bootstrap (resample syndicates)
        bootstrap_coefs = []
        for _ in range(n_bootstrap):
            boot_syndicates = syndicate_stats.sample(n=len(syndicate_stats), replace=True)
            try:
                boot_X = sm.add_constant(boot_syndicates['mean_log_size'])
                boot_y = boot_syndicates['log_volatility']
                boot_model = sm.OLS(boot_y, boot_X).fit()
                bootstrap_coefs.append(boot_model.params['mean_log_size'])
            except:
                continue
        
        if len(bootstrap_coefs) >= 50:
            diag.bootstrap_mean = float(np.mean(bootstrap_coefs))
            diag.bootstrap_std = float(np.std(bootstrap_coefs))
            diag.bootstrap_ci_lower = float(np.percentile(bootstrap_coefs, 2.5))
            diag.bootstrap_ci_upper = float(np.percentile(bootstrap_coefs, 97.5))
            diag.robust = diag.bootstrap_ci_upper < 0.1  # Upper CI should be below ~0
        
        # Cross-validation stability
        from sklearn.model_selection import KFold
        kf = KFold(n_splits=min(5, len(syndicate_stats) // 2), shuffle=True, random_state=42)
        cv_coefs = []
        for train_idx, _ in kf.split(syndicate_stats):
            train_data = syndicate_stats.iloc[train_idx]
            try:
                cv_X = sm.add_constant(train_data['mean_log_size'])
                cv_y = train_data['log_volatility']
                cv_model = sm.OLS(cv_y, cv_X).fit()
                cv_coefs.append(cv_model.params['mean_log_size'])
            except:
                continue
        
        if len(cv_coefs) >= 3:
            diag.cv_stability = float(np.std(cv_coefs) / abs(np.mean(cv_coefs))) if np.mean(cv_coefs) != 0 else np.inf
        
        # Overall assessment
        diag.trustworthy = (
            diag.data_sufficient and
            diag.statistically_significant and
            diag.sign_correct and
            diag.magnitude_plausible and
            (diag.cv_stability is None or diag.cv_stability < 0.5)
        )
        
        if diag.trustworthy:
            diag.recommendation = f"RECOMMENDED - Coefficient {diag.size_coefficient:.4f} indicates {'%.1f' % (100*(1-2**diag.size_coefficient))}% volatility reduction per doubling of size"
        elif diag.data_sufficient and diag.sign_correct:
            diag.recommendation = f"USABLE WITH CAUTION - Coefficient {diag.size_coefficient:.4f}, p={diag.size_coefficient_pvalue:.3f}"
        else:
            issues = []
            if not diag.data_sufficient:
                issues.append("insufficient panel data")
            if not diag.sign_correct:
                issues.append("wrong sign (larger syndicates more volatile)")
            if not diag.magnitude_plausible:
                issues.append(f"implausible magnitude ({diag.size_coefficient:.3f})")
            diag.recommendation = f"NOT RECOMMENDED - {', '.join(issues)}"
            
    except Exception as e:
        diag.data_issues.append(f"Model fitting failed: {str(e)}")
        diag.recommendation = f"FAILED - {str(e)}"
    
    return diag


# =============================================================================
# Approach 3: LOB-Specific Size Effects with Hierarchical Shrinkage
# =============================================================================

def run_approach_3_lob_specific(df: pd.DataFrame, n_bootstrap: int = 200) -> ApproachDiagnostics:
    """
    Test Approach 3: LOB-Specific Size Effects with Hierarchical Shrinkage
    
    Estimate size effects separately by LOB, with shrinkage toward overall.
    """
    
    diag = ApproachDiagnostics(
        name="LOB-Specific Size Effects",
        description="Estimate size effects by LOB with hierarchical shrinkage"
    )
    
    # Get primary LOB for each observation
    lob_cols = [c for c in df.columns if c.startswith('lob_share_')]
    
    if not lob_cols:
        # Use line_of_business column if available
        if 'line_of_business' in df.columns:
            df = df.copy()
            df['primary_lob'] = df['line_of_business']
        else:
            diag.data_issues.append("No LOB information available")
            diag.recommendation = "INSUFFICIENT DATA - No LOB breakdown"
            return diag
    else:
        # Identify primary LOB (highest share)
        df = df.copy()
        lob_shares = df[lob_cols].fillna(0)
        df['primary_lob'] = lob_shares.idxmax(axis=1).str.replace('lob_share_', '')
    
    # Count observations per LOB
    lob_counts = df['primary_lob'].value_counts()
    
    diag.n_observations = len(df)
    diag.n_syndicates = df['syndicate'].nunique()
    diag.min_obs_per_group = int(lob_counts.min()) if len(lob_counts) > 0 else 0
    
    # Need at least 10 observations per LOB for meaningful estimation
    valid_lobs = lob_counts[lob_counts >= 10].index.tolist()
    
    if len(valid_lobs) < 2:
        diag.data_issues.append(f"Only {len(valid_lobs)} LOBs with >= 10 observations")
        diag.data_sufficient = False
        diag.recommendation = "INSUFFICIENT DATA - Need more LOBs with sufficient observations"
        return diag
    
    diag.data_sufficient = True
    
    try:
        # First, estimate overall effect
        X_overall = sm.add_constant(df[['log_size']])
        y_overall = df['severity_ratio']
        overall_model = sm.OLS(y_overall, X_overall).fit()
        overall_coef = overall_model.params['log_size']
        overall_se = overall_model.bse['log_size']
        
        diag.size_coefficient = float(overall_coef)
        diag.size_coefficient_se = float(overall_se)
        diag.size_coefficient_pvalue = float(overall_model.pvalues['log_size'])
        
        # Estimate per-LOB effects
        lob_estimates = {}
        lob_se = {}
        lob_n = {}
        
        for lob in valid_lobs:
            lob_df = df[df['primary_lob'] == lob]
            lob_n[lob] = len(lob_df)
            
            if len(lob_df) >= 10:
                try:
                    X_lob = sm.add_constant(lob_df[['log_size']])
                    y_lob = lob_df['severity_ratio']
                    lob_model = sm.OLS(y_lob, X_lob).fit()
                    lob_estimates[lob] = lob_model.params['log_size']
                    lob_se[lob] = lob_model.bse['log_size']
                except:
                    lob_estimates[lob] = overall_coef
                    lob_se[lob] = overall_se * 2  # Inflate SE for shrinkage
            else:
                lob_estimates[lob] = overall_coef
                lob_se[lob] = overall_se * 2
        
        # Hierarchical shrinkage (empirical Bayes)
        # Shrink toward overall mean based on relative precision
        tau_squared = np.var(list(lob_estimates.values()))  # Between-LOB variance
        
        shrunk_estimates = {}
        for lob in lob_estimates:
            sigma_squared = lob_se[lob] ** 2  # Within-LOB variance
            shrinkage = tau_squared / (tau_squared + sigma_squared) if (tau_squared + sigma_squared) > 0 else 0.5
            shrunk_estimates[lob] = shrinkage * lob_estimates[lob] + (1 - shrinkage) * overall_coef
        
        diag.lob_coefficients = {lob: float(v) for lob, v in shrunk_estimates.items()}
        diag.lob_coefficients_se = {lob: float(v) for lob, v in lob_se.items()}
        
        # Check sensibility
        diag.sign_correct = overall_coef < 0
        diag.magnitude_plausible = -0.7 < overall_coef < 0.1
        diag.statistically_significant = diag.size_coefficient_pvalue < 0.05
        
        # Bootstrap
        bootstrap_overall = []
        bootstrap_lob = defaultdict(list)
        
        for _ in range(n_bootstrap):
            boot_df = df.sample(n=len(df), replace=True)
            try:
                boot_X = sm.add_constant(boot_df[['log_size']])
                boot_y = boot_df['severity_ratio']
                boot_model = sm.OLS(boot_y, boot_X).fit()
                bootstrap_overall.append(boot_model.params['log_size'])
                
                for lob in valid_lobs[:3]:  # Top 3 LOBs
                    lob_boot = boot_df[boot_df['primary_lob'] == lob]
                    if len(lob_boot) >= 5:
                        lob_X = sm.add_constant(lob_boot[['log_size']])
                        lob_y = lob_boot['severity_ratio']
                        lob_model = sm.OLS(lob_y, lob_X).fit()
                        bootstrap_lob[lob].append(lob_model.params['log_size'])
            except:
                continue
        
        if len(bootstrap_overall) >= 50:
            diag.bootstrap_mean = float(np.mean(bootstrap_overall))
            diag.bootstrap_std = float(np.std(bootstrap_overall))
            diag.bootstrap_ci_lower = float(np.percentile(bootstrap_overall, 2.5))
            diag.bootstrap_ci_upper = float(np.percentile(bootstrap_overall, 97.5))
            diag.robust = diag.bootstrap_ci_upper < 0.1
        
        # Overall assessment
        diag.trustworthy = (
            diag.data_sufficient and
            diag.sign_correct and
            diag.magnitude_plausible and
            len(shrunk_estimates) >= 3
        )
        
        # Check if LOB effects are consistent in direction
        lob_signs = [1 if v < 0 else -1 for v in shrunk_estimates.values()]
        sign_consistency = abs(sum(lob_signs)) / len(lob_signs) if lob_signs else 0
        
        if diag.trustworthy:
            lob_summary = ", ".join([f"{k}: {v:.3f}" for k, v in list(shrunk_estimates.items())[:4]])
            diag.recommendation = f"RECOMMENDED - Overall: {overall_coef:.4f}, LOBs: {lob_summary}"
        elif diag.data_sufficient:
            diag.recommendation = f"USABLE WITH CAUTION - Overall: {overall_coef:.4f}, sign consistency: {sign_consistency:.0%}"
        else:
            diag.recommendation = f"NOT RECOMMENDED - Insufficient data or inconsistent effects"
            
    except Exception as e:
        diag.data_issues.append(f"Model fitting failed: {str(e)}")
        diag.recommendation = f"FAILED - {str(e)}"
    
    return diag


# =============================================================================
# Approach 4: Relative Severity Rankings Within Event Cohorts
# =============================================================================

def run_approach_4_relative_rankings(df: pd.DataFrame, n_bootstrap: int = 200) -> ApproachDiagnostics:
    """
    Test Approach 4: Relative Severity Rankings Within Event Cohorts
    
    Test whether larger syndicates consistently rank lower in severity
    within shared events.
    """
    
    diag = ApproachDiagnostics(
        name="Relative Severity Rankings",
        description="Test whether larger syndicates rank lower in severity within shared events"
    )
    
    # Identify common events (reuse from approach 1)
    df_events = identify_common_events(df, min_syndicates=3)
    
    if len(df_events) == 0:
        diag.data_issues.append("No common events identified")
        diag.recommendation = "INSUFFICIENT DATA - Cannot identify common events"
        return diag
    
    diag.n_observations = len(df_events)
    diag.n_syndicates = df_events['syndicate'].nunique()
    diag.n_events = df_events['event_id'].nunique()
    
    # Compute within-event severity ranks
    df_events = df_events.copy()
    df_events['severity_rank'] = df_events.groupby('event_id')['severity_ratio'].rank(pct=True)
    df_events['size_rank'] = df_events.groupby('event_id')['size'].rank(pct=True)
    
    # Also compute overall percentile rank
    df_events['severity_rank_overall'] = df_events.groupby('event_id')['severity_ratio'].rank()
    df_events['n_in_event'] = df_events.groupby('event_id')['severity_ratio'].transform('count')
    df_events['severity_percentile'] = df_events['severity_rank_overall'] / df_events['n_in_event']
    
    diag.data_sufficient = diag.n_events >= 5 and diag.n_observations >= 30
    
    if not diag.data_sufficient:
        diag.data_issues.append(f"Only {diag.n_events} events with {diag.n_observations} observations")
        diag.recommendation = "INSUFFICIENT DATA"
        return diag
    
    try:
        # Method A: Correlation between size rank and severity rank within events
        correlations = []
        for event_id in df_events['event_id'].unique():
            event_df = df_events[df_events['event_id'] == event_id]
            if len(event_df) >= 3:
                corr, pval = stats.spearmanr(event_df['size'], event_df['severity_ratio'])
                if not np.isnan(corr):
                    correlations.append(corr)
        
        if correlations:
            mean_corr = np.mean(correlations)
            # Test if mean correlation is significantly different from zero
            t_stat, p_value = stats.ttest_1samp(correlations, 0)
            
            diag.size_coefficient = float(mean_corr)  # Using correlation as proxy
            diag.size_coefficient_pvalue = float(p_value)
            diag.statistically_significant = p_value < 0.05
            diag.sign_correct = mean_corr < 0  # Negative = larger syndicates have lower severity
        
        # Method B: Ordinal regression of severity rank on size
        try:
            # Simple OLS on percentile rank as proxy for ordinal
            X = sm.add_constant(df_events[['log_size']])
            y = df_events['severity_percentile']
            
            rank_model = sm.OLS(y, X).fit()
            
            # This coefficient is interpretable as: change in severity percentile per unit log_size
            rank_coef = rank_model.params['log_size']
            rank_pval = rank_model.pvalues['log_size']
            
            # Update if more significant
            if rank_pval < (diag.size_coefficient_pvalue or 1.0):
                diag.size_coefficient = float(rank_coef)
                diag.size_coefficient_pvalue = float(rank_pval)
                diag.size_coefficient_se = float(rank_model.bse['log_size'])
                diag.statistically_significant = rank_pval < 0.05
                diag.sign_correct = rank_coef < 0
                
        except Exception as e:
            logger.warning(f"Ordinal regression failed: {e}")
        
        diag.magnitude_plausible = abs(diag.size_coefficient or 0) < 0.5  # Correlation/rank effect
        
        # Bootstrap
        bootstrap_coefs = []
        for _ in range(n_bootstrap):
            # Resample events
            event_ids = df_events['event_id'].unique()
            sampled_events = np.random.choice(event_ids, size=len(event_ids), replace=True)
            boot_dfs = [df_events[df_events['event_id'] == e] for e in sampled_events]
            boot_df = pd.concat(boot_dfs, ignore_index=True)
            
            try:
                boot_X = sm.add_constant(boot_df[['log_size']])
                boot_y = boot_df['severity_percentile']
                boot_model = sm.OLS(boot_y, boot_X).fit()
                bootstrap_coefs.append(boot_model.params['log_size'])
            except:
                continue
        
        if len(bootstrap_coefs) >= 50:
            diag.bootstrap_mean = float(np.mean(bootstrap_coefs))
            diag.bootstrap_std = float(np.std(bootstrap_coefs))
            diag.bootstrap_ci_lower = float(np.percentile(bootstrap_coefs, 2.5))
            diag.bootstrap_ci_upper = float(np.percentile(bootstrap_coefs, 97.5))
            diag.robust = (diag.bootstrap_ci_upper < 0.05) if diag.sign_correct else False
        
        diag.trustworthy = (
            diag.data_sufficient and
            diag.statistically_significant and
            diag.sign_correct
        )
        
        if diag.trustworthy:
            direction = "lower" if diag.sign_correct else "higher"
            diag.recommendation = f"RECOMMENDED - Larger syndicates rank {direction} in severity (coef: {diag.size_coefficient:.4f}, p={diag.size_coefficient_pvalue:.3f})"
        elif diag.data_sufficient:
            diag.recommendation = f"WEAK EVIDENCE - Coefficient: {diag.size_coefficient:.4f}, p={diag.size_coefficient_pvalue:.3f}"
        else:
            diag.recommendation = "INSUFFICIENT DATA"
            
    except Exception as e:
        diag.data_issues.append(f"Analysis failed: {str(e)}")
        diag.recommendation = f"FAILED - {str(e)}"
    
    return diag


# =============================================================================
# Convergence Analysis
# =============================================================================

def analyse_convergence(results: Dict[str, ApproachDiagnostics]) -> Dict[str, Any]:
    """
    Compare results across approaches to assess convergence.
    """
    
    # Extract coefficients that are comparable
    coefs = {}
    for name, diag in results.items():
        if diag.size_coefficient is not None:
            coefs[name] = diag.size_coefficient
    
    if len(coefs) < 2:
        return {
            'n_approaches_with_estimates': len(coefs),
            'convergence_possible': False,
            'message': "Insufficient approaches produced estimates"
        }
    
    coef_values = list(coefs.values())
    
    # Check sign agreement
    signs = [1 if c < 0 else -1 for c in coef_values]
    sign_agreement = abs(sum(signs)) / len(signs)
    
    # Check magnitude similarity (coefficient of variation)
    coef_cv = np.std(coef_values) / abs(np.mean(coef_values)) if np.mean(coef_values) != 0 else np.inf
    
    # Identify outliers
    mean_coef = np.mean(coef_values)
    std_coef = np.std(coef_values)
    outliers = {k: v for k, v in coefs.items() if abs(v - mean_coef) > 2 * std_coef}
    
    convergence = {
        'n_approaches_with_estimates': len(coefs),
        'coefficients': coefs,
        'mean_coefficient': float(mean_coef),
        'std_coefficient': float(std_coef),
        'coefficient_cv': float(coef_cv),
        'sign_agreement': float(sign_agreement),
        'all_negative': all(c < 0 for c in coef_values),
        'all_positive': all(c > 0 for c in coef_values),
        'outlier_approaches': list(outliers.keys()),
        'convergent': sign_agreement > 0.5 and coef_cv < 1.0,
        'strongly_convergent': sign_agreement == 1.0 and coef_cv < 0.5
    }
    
    if convergence['strongly_convergent']:
        convergence['message'] = f"STRONG CONVERGENCE: All approaches agree on direction and similar magnitude (mean: {mean_coef:.4f})"
    elif convergence['convergent']:
        convergence['message'] = f"MODERATE CONVERGENCE: Approaches mostly agree (mean: {mean_coef:.4f}, CV: {coef_cv:.2f})"
    else:
        convergence['message'] = f"WEAK/NO CONVERGENCE: Approaches disagree (sign agreement: {sign_agreement:.0%})"
    
    return convergence


# =============================================================================
# Main Analysis
# =============================================================================

def run_analysis(corpus_path: str, output_path: Optional[str] = None, n_bootstrap: int = 200) -> AnalysisResults:
    """
    Run complete size diversification analysis.
    """
    
    logger.info("=" * 70)
    logger.info("PORTFOLIO SIZE DIVERSIFICATION ANALYSIS")
    logger.info("=" * 70)
    
    # Load data
    logger.info("\nLoading corpus...")
    df = load_corpus(corpus_path)
    corpus_summary = summarise_corpus(df)
    
    logger.info(f"\nCorpus summary:")
    logger.info(f"  Observations: {corpus_summary['n_observations']}")
    logger.info(f"  Syndicates: {corpus_summary['n_syndicates']}")
    logger.info(f"  Years: {corpus_summary['year_range'][0]}-{corpus_summary['year_range'][1]}")
    logger.info(f"  Size range: £{corpus_summary['size_stats']['min']:.0f}m - £{corpus_summary['size_stats']['max']:.0f}m")
    
    # Run each approach
    results = {}
    
    logger.info("\n" + "=" * 70)
    logger.info("APPROACH 1: Common Event Matching")
    logger.info("=" * 70)
    results['approach_1_common_events'] = run_approach_1_common_events(df, n_bootstrap)
    logger.info(f"Result: {results['approach_1_common_events'].recommendation}")
    
    logger.info("\n" + "=" * 70)
    logger.info("APPROACH 2: Within-Syndicate Volatility Scaling")
    logger.info("=" * 70)
    results['approach_2_volatility'] = run_approach_2_volatility_scaling(df, n_bootstrap)
    logger.info(f"Result: {results['approach_2_volatility'].recommendation}")
    
    logger.info("\n" + "=" * 70)
    logger.info("APPROACH 3: LOB-Specific Size Effects")
    logger.info("=" * 70)
    results['approach_3_lob_specific'] = run_approach_3_lob_specific(df, n_bootstrap)
    logger.info(f"Result: {results['approach_3_lob_specific'].recommendation}")
    
    logger.info("\n" + "=" * 70)
    logger.info("APPROACH 4: Relative Severity Rankings")
    logger.info("=" * 70)
    results['approach_4_rankings'] = run_approach_4_relative_rankings(df, n_bootstrap)
    logger.info(f"Result: {results['approach_4_rankings'].recommendation}")
    
    # Convergence analysis
    logger.info("\n" + "=" * 70)
    logger.info("CONVERGENCE ANALYSIS")
    logger.info("=" * 70)
    convergence = analyse_convergence(results)
    logger.info(f"Result: {convergence['message']}")
    
    # Overall recommendation
    trustworthy_approaches = [name for name, diag in results.items() if diag.trustworthy]
    usable_approaches = [name for name, diag in results.items() 
                        if diag.data_sufficient and diag.sign_correct]
    
    if len(trustworthy_approaches) >= 2 and convergence.get('convergent', False):
        overall = f"RECOMMENDED: Use average of {', '.join(trustworthy_approaches)}. Mean coefficient: {convergence['mean_coefficient']:.4f}"
    elif len(trustworthy_approaches) >= 1:
        overall = f"USABLE: {trustworthy_approaches[0]} appears most reliable. Coefficient: {results[trustworthy_approaches[0]].size_coefficient:.4f}"
    elif len(usable_approaches) >= 1:
        overall = f"WEAK EVIDENCE: {usable_approaches[0]} shows some signal but use with caution"
    else:
        overall = "INSUFFICIENT EVIDENCE: No approach produced reliable size effect estimates. Consider pooling with external data or using theoretical priors."
    
    logger.info("\n" + "=" * 70)
    logger.info("OVERALL RECOMMENDATION")
    logger.info("=" * 70)
    logger.info(overall)
    
    # Build results object
    analysis_results = AnalysisResults(
        corpus_summary=corpus_summary,
        approach_results=results,
        convergence_analysis=convergence,
        overall_recommendation=overall
    )
    
    # Save if requested
    if output_path:
        output_dict = analysis_results.to_dict()
        with open(output_path, 'w') as f:
            json.dump(output_dict, f, indent=2, default=str)
        logger.info(f"\nResults saved to: {output_path}")
    
    return analysis_results


def print_detailed_report(results: AnalysisResults):
    """Print detailed analysis report."""
    
    print("\n" + "=" * 80)
    print("DETAILED SIZE DIVERSIFICATION ANALYSIS REPORT")
    print("=" * 80)
    
    print("\n## DATA SUMMARY")
    print("-" * 40)
    cs = results.corpus_summary
    print(f"Observations: {cs['n_observations']}")
    print(f"Syndicates: {cs['n_syndicates']}")
    print(f"Years: {cs['year_range'][0]}-{cs['year_range'][1]}")
    print(f"Severity: mean={cs['severity_stats']['mean']:.1%}, std={cs['severity_stats']['std']:.1%}")
    print(f"Size: median=£{cs['size_stats']['median']:.0f}m, range=£{cs['size_stats']['min']:.0f}m-£{cs['size_stats']['max']:.0f}m")
    
    for name, diag in results.approach_results.items():
        print(f"\n## {diag.name.upper()}")
        print("-" * 40)
        print(f"Description: {diag.description}")
        print(f"\nData Sufficiency:")
        print(f"  Observations: {diag.n_observations}")
        print(f"  Syndicates: {diag.n_syndicates}")
        if diag.n_events > 0:
            print(f"  Events: {diag.n_events}")
        print(f"  Sufficient: {'✓' if diag.data_sufficient else '✗'}")
        if diag.data_issues:
            print(f"  Issues: {', '.join(diag.data_issues)}")
        
        if diag.size_coefficient is not None:
            print(f"\nStatistical Results:")
            print(f"  Size coefficient: {diag.size_coefficient:.4f}")
            if diag.size_coefficient_se:
                print(f"  Standard error: {diag.size_coefficient_se:.4f}")
            if diag.size_coefficient_pvalue:
                print(f"  P-value: {diag.size_coefficient_pvalue:.4f}")
            if diag.r_squared:
                print(f"  R-squared: {diag.r_squared:.4f}")
            
            if diag.lob_coefficients:
                print(f"\n  LOB-Specific Coefficients:")
                for lob, coef in sorted(diag.lob_coefficients.items(), key=lambda x: x[1]):
                    print(f"    {lob}: {coef:.4f}")
        
        if diag.bootstrap_mean is not None:
            print(f"\nBootstrap Results:")
            print(f"  Mean: {diag.bootstrap_mean:.4f}")
            print(f"  Std: {diag.bootstrap_std:.4f}")
            print(f"  95% CI: [{diag.bootstrap_ci_lower:.4f}, {diag.bootstrap_ci_upper:.4f}]")
        
        print(f"\nAssessment:")
        print(f"  Sign correct (negative): {'✓' if diag.sign_correct else '✗'}")
        print(f"  Magnitude plausible: {'✓' if diag.magnitude_plausible else '✗'}")
        print(f"  Statistically significant: {'✓' if diag.statistically_significant else '✗'}")
        print(f"  Robust: {'✓' if diag.robust else '✗'}")
        print(f"  TRUSTWORTHY: {'✓' if diag.trustworthy else '✗'}")
        print(f"\n  >> {diag.recommendation}")
    
    print(f"\n## CONVERGENCE ANALYSIS")
    print("-" * 40)
    conv = results.convergence_analysis
    print(f"Approaches with estimates: {conv.get('n_approaches_with_estimates', 0)}")
    if 'coefficients' in conv:
        print(f"Coefficients: {conv['coefficients']}")
        print(f"Mean coefficient: {conv.get('mean_coefficient', 'N/A')}")
        print(f"Sign agreement: {conv.get('sign_agreement', 0):.0%}")
        print(f"Convergent: {'✓' if conv.get('convergent', False) else '✗'}")
    print(f"\n{conv.get('message', 'No convergence analysis available')}")
    
    print(f"\n## OVERALL RECOMMENDATION")
    print("-" * 40)
    print(results.overall_recommendation)
    print("\n" + "=" * 80)


# =============================================================================
# CLI
# =============================================================================

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Test portfolio size diversification approaches")
    parser.add_argument("--corpus", "-c", required=True, help="Path to unified corpus JSON")
    parser.add_argument("--output", "-o", help="Output JSON path for results")
    parser.add_argument("--bootstrap", "-b", type=int, default=200, help="Bootstrap iterations")
    parser.add_argument("--verbose", "-v", action="store_true", help="Print detailed report")
    
    args = parser.parse_args()
    
    results = run_analysis(args.corpus, args.output, args.bootstrap)
    
    if args.verbose:
        print_detailed_report(results)
