"""
Portfolio Size Diversification Adjustment
=========================================

Combines two empirically-validated approaches to adjust stress scenario
severities based on portfolio size:

1. Common Event Matching (Approach 1): Estimates size effects from 
   within-event variation across syndicates experiencing the same event.

2. LOB-Specific Effects (Approach 3): Estimates size effects separately
   by line of business with hierarchical shrinkage.

The combined model uses:
- LOB-specific coefficients for differentiated diversification by line
- Event fixed effects to control for event-specific severity
- Hierarchical shrinkage to handle sparse LOBs

Usage:
    from portfolio_size_adjustment import PortfolioSizeAdjuster
    
    adjuster = PortfolioSizeAdjuster()
    adjuster.fit(corpus_path="results/combined/enhanced_corpus.json")
    
    # Adjust a single severity
    adjusted = adjuster.adjust_severity(
        base_severity=0.25,
        portfolio_size_m=100,
        lob="Property"
    )
    
    # Adjust scenarios in a library
    adjuster.adjust_scenario_library(library_path, output_path, portfolio_size_m=100)

Author: Colin Priest
Date: December 2024
"""

import json
import logging
import numpy as np
import pandas as pd
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field, asdict
from collections import defaultdict

import statsmodels.api as sm

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


# =============================================================================
# Default Coefficients (from analysis)
# =============================================================================

# These are the empirically estimated coefficients from Lloyd's syndicate data
# Can be overridden by fitting to new data

DEFAULT_OVERALL_COEFFICIENT = -0.24  # Average of approaches 1 and 3

DEFAULT_LOB_COEFFICIENTS = {
    "Property": -0.49,
    "Aggregate": -0.34,
    "Casualty": -0.30,
    "Energy": -0.05,
    "Professional Lines": -0.03,
    "Reinsurance - Casualty": -0.02,
    "Accident & Health": -0.01,
    "Marine": -0.01,
    "Reinsurance - Property": 0.02,
    "Reinsurance - Specialty": 0.0,
    "Aviation": -0.02,
    "Motor": -0.02,
    "Cyber": -0.02,
}

DEFAULT_REFERENCE_SIZE_M = 500.0  # Reference portfolio size in £m


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class SizeAdjustmentModel:
    """Fitted size adjustment model parameters."""
    
    # Overall coefficient
    overall_coefficient: float = DEFAULT_OVERALL_COEFFICIENT
    overall_se: float = 0.07
    overall_pvalue: float = 0.001
    
    # LOB-specific coefficients
    lob_coefficients: Dict[str, float] = field(default_factory=lambda: DEFAULT_LOB_COEFFICIENTS.copy())
    lob_standard_errors: Dict[str, float] = field(default_factory=dict)
    
    # Reference size (median from training data)
    reference_size_m: float = DEFAULT_REFERENCE_SIZE_M
    
    # Model metadata
    n_observations: int = 0
    n_syndicates: int = 0
    n_events: int = 0
    fitting_method: str = "default"
    
    # Shrinkage parameters
    shrinkage_tau: float = 0.0  # Between-LOB variance
    
    def to_dict(self) -> Dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, d: Dict) -> 'SizeAdjustmentModel':
        return cls(**d)
    
    def save(self, path: str):
        """Save model to JSON file."""
        with open(path, 'w') as f:
            json.dump(self.to_dict(), f, indent=2)
        logger.info(f"Model saved to {path}")
    
    @classmethod
    def load(cls, path: str) -> 'SizeAdjustmentModel':
        """Load model from JSON file."""
        with open(path, 'r') as f:
            d = json.load(f)
        return cls.from_dict(d)


# =============================================================================
# Main Adjuster Class
# =============================================================================

class PortfolioSizeAdjuster:
    """
    Adjusts stress scenario severities based on portfolio size.
    
    Uses empirically estimated coefficients from Lloyd's syndicate data
    combining common event matching and LOB-specific effects.
    """
    
    def __init__(self, model: Optional[SizeAdjustmentModel] = None):
        """
        Initialize adjuster.
        
        Args:
            model: Pre-fitted model, or None to use defaults
        """
        self.model = model or SizeAdjustmentModel()
    
    def fit(self, 
            corpus_path: str,
            min_obs_per_lob: int = 10,
            min_events: int = 3) -> 'PortfolioSizeAdjuster':
        """
        Fit the size adjustment model from corpus data.
        
        Combines:
        - Approach 1: Event fixed effects regression
        - Approach 3: LOB-specific coefficients with shrinkage
        
        Args:
            corpus_path: Path to enhanced_corpus.json
            min_obs_per_lob: Minimum observations to estimate LOB-specific coefficient
            min_events: Minimum syndicates per event to include
            
        Returns:
            self (for chaining)
        """
        logger.info(f"Fitting size adjustment model from {corpus_path}")
        
        # Load and prepare data
        df = self._load_corpus(corpus_path)
        
        if len(df) < 30:
            logger.warning(f"Only {len(df)} observations - using default coefficients")
            return self
        
        # Identify common events (year + cause category)
        df = self._identify_events(df, min_syndicates=min_events)
        
        # Fit combined model
        self.model = self._fit_combined_model(df, min_obs_per_lob)
        
        logger.info(f"Fitted model with {self.model.n_observations} observations")
        logger.info(f"Overall coefficient: {self.model.overall_coefficient:.4f}")
        logger.info(f"LOB coefficients: {len(self.model.lob_coefficients)}")
        
        return self
    
    def _load_corpus(self, corpus_path: str) -> pd.DataFrame:
        """Load and prepare corpus data."""
        with open(corpus_path, 'r') as f:
            data = json.load(f)
        
        movements = data.get('movements', [])
        
        records = []
        for m in movements:
            record = {
                'syndicate': str(m.get('syndicate', '')),
                'year': m.get('year'),
                'lob': m.get('line_of_business', 'Aggregate'),
                'severity_ratio': m.get('severity_ratio'),
                'direction': m.get('direction'),
                'cause_category': (m.get('primary_causes', ['unknown']) or ['unknown'])[0],
            }
            
            # Size - try multiple fields
            record['size'] = (
                m.get('prior_reserves_gbp_m') or
                m.get('technical_provisions_gbp_m') or
                m.get('claims_outstanding_gbp_m') or
                m.get('stamp_capacity_gbp_m') or
                m.get('gross_premium_gbp_m')
            )
            
            records.append(record)
        
        df = pd.DataFrame(records)
        
        # Convert to numeric
        df['size'] = pd.to_numeric(df['size'], errors='coerce')
        df['severity_ratio'] = pd.to_numeric(df['severity_ratio'], errors='coerce')
        df['year'] = pd.to_numeric(df['year'], errors='coerce')
        
        # Filter to valid records
        df = df.dropna(subset=['size', 'severity_ratio', 'syndicate', 'year'])
        df = df[df['size'] > 0]
        
        # Compute log size
        df['log_size'] = np.log(df['size'])
        
        # Winsorize extreme severities
        p01, p99 = df['severity_ratio'].quantile([0.01, 0.99])
        df['severity_ratio'] = df['severity_ratio'].clip(lower=p01, upper=p99)
        
        logger.info(f"Loaded {len(df)} valid observations")
        
        return df
    
    def _identify_events(self, df: pd.DataFrame, min_syndicates: int = 3) -> pd.DataFrame:
        """Identify common events (year + cause affecting multiple syndicates)."""
        df = df.copy()
        
        # Create event key
        df['event_key'] = df['year'].astype(str) + '_' + df['cause_category'].fillna('unknown')
        
        # Count syndicates per event
        event_counts = df.groupby('event_key')['syndicate'].nunique()
        valid_events = event_counts[event_counts >= min_syndicates].index
        
        # Filter to valid events
        df = df[df['event_key'].isin(valid_events)]
        
        # Create numeric event ID
        event_map = {e: i for i, e in enumerate(df['event_key'].unique())}
        df['event_id'] = df['event_key'].map(event_map)
        
        logger.info(f"Identified {len(valid_events)} events with >= {min_syndicates} syndicates")
        
        return df
    
    def _fit_combined_model(self, df: pd.DataFrame, min_obs_per_lob: int) -> SizeAdjustmentModel:
        """
        Fit combined model using event fixed effects and LOB stratification.
        """
        model = SizeAdjustmentModel()
        model.n_observations = len(df)
        model.n_syndicates = df['syndicate'].nunique()
        model.n_events = df['event_id'].nunique() if 'event_id' in df.columns else 0
        model.reference_size_m = float(df['size'].median())
        model.fitting_method = "combined_event_lob"
        
        # =================================================================
        # Part 1: Overall coefficient with event fixed effects (Approach 1)
        # =================================================================
        
        if 'event_id' in df.columns and df['event_id'].nunique() > 1:
            try:
                # Create event dummies
                event_dummies = pd.get_dummies(
                    df['event_id'].astype(str), 
                    prefix='event', 
                    drop_first=True
                ).astype(np.float64)
                
                X = pd.concat([
                    df[['log_size']].reset_index(drop=True).astype(np.float64),
                    event_dummies.reset_index(drop=True)
                ], axis=1)
                X = sm.add_constant(X)
                y = df['severity_ratio'].reset_index(drop=True).astype(np.float64)
                
                event_model = sm.OLS(y, X).fit()
                
                model.overall_coefficient = float(event_model.params['log_size'])
                model.overall_se = float(event_model.bse['log_size'])
                model.overall_pvalue = float(event_model.pvalues['log_size'])
                
                logger.info(f"Event FE model: β={model.overall_coefficient:.4f}, p={model.overall_pvalue:.4f}")
                
            except Exception as e:
                logger.warning(f"Event FE fitting failed: {e}, using simple regression")
                # Fall back to simple regression
                X = sm.add_constant(df[['log_size']].astype(np.float64))
                y = df['severity_ratio'].astype(np.float64)
                simple_model = sm.OLS(y, X).fit()
                model.overall_coefficient = float(simple_model.params['log_size'])
                model.overall_se = float(simple_model.bse['log_size'])
                model.overall_pvalue = float(simple_model.pvalues['log_size'])
        
        # =================================================================
        # Part 2: LOB-specific coefficients with shrinkage (Approach 3)
        # =================================================================
        
        lob_estimates = {}
        lob_se = {}
        lob_n = {}
        
        for lob in df['lob'].unique():
            lob_df = df[df['lob'] == lob]
            lob_n[lob] = len(lob_df)
            
            if len(lob_df) >= min_obs_per_lob:
                try:
                    X_lob = sm.add_constant(lob_df[['log_size']].astype(np.float64))
                    y_lob = lob_df['severity_ratio'].astype(np.float64)
                    lob_model = sm.OLS(y_lob, X_lob).fit()
                    lob_estimates[lob] = float(lob_model.params['log_size'])
                    lob_se[lob] = float(lob_model.bse['log_size'])
                except Exception as e:
                    logger.debug(f"LOB {lob} fitting failed: {e}")
                    lob_estimates[lob] = model.overall_coefficient
                    lob_se[lob] = model.overall_se * 2
            else:
                # Not enough data - will be shrunk toward overall
                lob_estimates[lob] = model.overall_coefficient
                lob_se[lob] = model.overall_se * 2  # Inflated SE for shrinkage
        
        # Apply hierarchical shrinkage
        if len(lob_estimates) > 1:
            tau_squared = np.var(list(lob_estimates.values()))  # Between-LOB variance
            model.shrinkage_tau = float(np.sqrt(tau_squared))
            
            shrunk_coefficients = {}
            for lob in lob_estimates:
                sigma_squared = lob_se[lob] ** 2
                # Shrinkage factor: how much to weight individual vs overall
                shrinkage = tau_squared / (tau_squared + sigma_squared) if (tau_squared + sigma_squared) > 0 else 0.5
                shrunk_coefficients[lob] = (
                    shrinkage * lob_estimates[lob] + 
                    (1 - shrinkage) * model.overall_coefficient
                )
            
            model.lob_coefficients = shrunk_coefficients
            model.lob_standard_errors = lob_se
        
        # Fill in any missing LOBs with defaults
        for lob, coef in DEFAULT_LOB_COEFFICIENTS.items():
            if lob not in model.lob_coefficients:
                model.lob_coefficients[lob] = coef
        
        return model
    
    def get_coefficient(self, lob: Optional[str] = None) -> float:
        """
        Get size adjustment coefficient.
        
        Args:
            lob: Line of business, or None for overall
            
        Returns:
            Size coefficient (negative means larger portfolios have lower severity)
        """
        if lob is None:
            return self.model.overall_coefficient
        
        # Try exact match
        if lob in self.model.lob_coefficients:
            return self.model.lob_coefficients[lob]
        
        # Try case-insensitive match
        lob_lower = lob.lower()
        for key, value in self.model.lob_coefficients.items():
            if key.lower() == lob_lower:
                return value
        
        # Try partial match
        for key, value in self.model.lob_coefficients.items():
            if lob_lower in key.lower() or key.lower() in lob_lower:
                return value
        
        # Fall back to overall
        return self.model.overall_coefficient
    
    def adjust_severity(self,
                        base_severity: float,
                        portfolio_size_m: float,
                        lob: Optional[str] = None,
                        reference_size_m: Optional[float] = None) -> float:
        """
        Adjust a severity ratio for portfolio size.
        
        The model is:
            severity_adjusted = severity_base * (size / reference_size)^β
        
        Where β < 0 means larger portfolios have lower severity (diversification benefit).
        
        Args:
            base_severity: Original severity ratio (e.g., 0.25 for 25%)
            portfolio_size_m: Target portfolio size in £m
            lob: Line of business for LOB-specific adjustment
            reference_size_m: Reference size (default: median from training data)
            
        Returns:
            Adjusted severity ratio
        """
        if reference_size_m is None:
            reference_size_m = self.model.reference_size_m
        
        if portfolio_size_m <= 0 or reference_size_m <= 0:
            return base_severity
        
        beta = self.get_coefficient(lob)
        
        # Apply adjustment: severity * (size/ref)^beta
        size_ratio = portfolio_size_m / reference_size_m
        adjustment_factor = size_ratio ** beta
        
        return base_severity * adjustment_factor
    
    def adjustment_factor(self,
                          portfolio_size_m: float,
                          lob: Optional[str] = None,
                          reference_size_m: Optional[float] = None) -> float:
        """
        Get the multiplicative adjustment factor for a portfolio size.
        
        Args:
            portfolio_size_m: Target portfolio size in £m
            lob: Line of business
            reference_size_m: Reference size
            
        Returns:
            Adjustment factor (multiply severity by this)
        """
        if reference_size_m is None:
            reference_size_m = self.model.reference_size_m
        
        if portfolio_size_m <= 0 or reference_size_m <= 0:
            return 1.0
        
        beta = self.get_coefficient(lob)
        size_ratio = portfolio_size_m / reference_size_m
        
        return size_ratio ** beta
    
    def adjustment_table(self,
                         sizes: List[float] = None,
                         lobs: List[str] = None) -> pd.DataFrame:
        """
        Generate a table of adjustment factors for different sizes and LOBs.
        
        Args:
            sizes: List of portfolio sizes in £m
            lobs: List of lines of business
            
        Returns:
            DataFrame with adjustment factors
        """
        if sizes is None:
            sizes = [50, 100, 250, 500, 1000, 2500, 5000]
        
        if lobs is None:
            lobs = ["Property", "Casualty", "Aggregate", "Marine", "Reinsurance - Property"]
        
        data = []
        for size in sizes:
            row = {'Portfolio Size (£m)': size}
            for lob in lobs:
                factor = self.adjustment_factor(size, lob)
                row[lob] = factor
            data.append(row)
        
        return pd.DataFrame(data)
    
    def adjust_scenario(self, scenario: Dict, portfolio_size_m: float) -> Dict:
        """
        Adjust a single scenario's severity for portfolio size.
        
        Args:
            scenario: Scenario dict with 'severity_ratio' and optionally 'lob_impacts'
            portfolio_size_m: Target portfolio size in £m
            
        Returns:
            New scenario dict with adjusted severities
        """
        adjusted = scenario.copy()
        
        # Get primary LOB from scenario
        primary_lob = scenario.get('line_of_business') or scenario.get('primary_lob')
        
        # Adjust overall severity
        if 'severity_ratio' in adjusted:
            adjusted['severity_ratio'] = self.adjust_severity(
                scenario['severity_ratio'],
                portfolio_size_m,
                lob=primary_lob
            )
            adjusted['severity_ratio_unadjusted'] = scenario['severity_ratio']
        
        # Adjust LOB-specific impacts
        if 'lob_impacts' in adjusted:
            adjusted_impacts = {}
            for lob, impact in scenario['lob_impacts'].items():
                adjusted_impacts[lob] = self.adjust_severity(
                    impact,
                    portfolio_size_m,
                    lob=lob
                )
            adjusted['lob_impacts'] = adjusted_impacts
            adjusted['lob_impacts_unadjusted'] = scenario['lob_impacts']
        
        # Record adjustment metadata
        adjusted['size_adjustment'] = {
            'portfolio_size_m': portfolio_size_m,
            'reference_size_m': self.model.reference_size_m,
            'coefficient_used': self.get_coefficient(primary_lob),
            'adjustment_factor': self.adjustment_factor(portfolio_size_m, primary_lob)
        }
        
        return adjusted
    
    def adjust_scenario_library(self,
                                library_path: str,
                                output_path: str,
                                portfolio_size_m: float) -> int:
        """
        Adjust all scenarios in a library for portfolio size.
        
        Args:
            library_path: Path to scenario_library.json
            output_path: Path to save adjusted library
            portfolio_size_m: Target portfolio size in £m
            
        Returns:
            Number of scenarios adjusted
        """
        with open(library_path, 'r') as f:
            library = json.load(f)
        
        scenarios = library.get('scenarios', [])
        adjusted_scenarios = []
        
        for scenario in scenarios:
            adjusted = self.adjust_scenario(scenario, portfolio_size_m)
            adjusted_scenarios.append(adjusted)
        
        # Update library
        library['scenarios'] = adjusted_scenarios
        library['size_adjustment'] = {
            'portfolio_size_m': portfolio_size_m,
            'reference_size_m': self.model.reference_size_m,
            'overall_coefficient': self.model.overall_coefficient,
            'adjusted_at': pd.Timestamp.now().isoformat()
        }
        
        with open(output_path, 'w') as f:
            json.dump(library, f, indent=2)
        
        logger.info(f"Adjusted {len(adjusted_scenarios)} scenarios for £{portfolio_size_m}m portfolio")
        logger.info(f"Saved to {output_path}")
        
        return len(adjusted_scenarios)
    
    def print_summary(self):
        """Print model summary."""
        print("\n" + "=" * 60)
        print("PORTFOLIO SIZE ADJUSTMENT MODEL")
        print("=" * 60)
        print(f"\nOverall coefficient: {self.model.overall_coefficient:.4f}")
        print(f"Standard error: {self.model.overall_se:.4f}")
        print(f"P-value: {self.model.overall_pvalue:.4f}")
        print(f"Reference size: £{self.model.reference_size_m:.0f}m")
        print(f"\nObservations: {self.model.n_observations}")
        print(f"Syndicates: {self.model.n_syndicates}")
        print(f"Events: {self.model.n_events}")
        
        print("\nLOB-Specific Coefficients:")
        print("-" * 40)
        for lob, coef in sorted(self.model.lob_coefficients.items(), key=lambda x: x[1]):
            print(f"  {lob:30s}: {coef:+.4f}")
        
        print("\nAdjustment Factors by Portfolio Size:")
        print("-" * 60)
        table = self.adjustment_table()
        print(table.to_string(index=False, float_format='{:.2f}'.format))
        print("=" * 60)


# =============================================================================
# Convenience Functions
# =============================================================================

def create_default_adjuster() -> PortfolioSizeAdjuster:
    """Create adjuster with default (empirically estimated) coefficients."""
    return PortfolioSizeAdjuster()


def fit_adjuster_from_corpus(corpus_path: str) -> PortfolioSizeAdjuster:
    """Fit adjuster from corpus data."""
    adjuster = PortfolioSizeAdjuster()
    adjuster.fit(corpus_path)
    return adjuster


def adjust_severity(base_severity: float,
                    portfolio_size_m: float,
                    lob: Optional[str] = None,
                    reference_size_m: float = DEFAULT_REFERENCE_SIZE_M) -> float:
    """
    Quick function to adjust severity using default coefficients.
    
    Args:
        base_severity: Original severity ratio
        portfolio_size_m: Target portfolio size in £m
        lob: Line of business (optional)
        reference_size_m: Reference size
        
    Returns:
        Adjusted severity ratio
    """
    adjuster = PortfolioSizeAdjuster()
    return adjuster.adjust_severity(base_severity, portfolio_size_m, lob, reference_size_m)


# =============================================================================
# CLI
# =============================================================================

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Portfolio size adjustment for stress scenarios")
    subparsers = parser.add_subparsers(dest='command', help='Commands')
    
    # Fit command
    fit_parser = subparsers.add_parser('fit', help='Fit model from corpus')
    fit_parser.add_argument('--corpus', '-c', required=True, help='Path to enhanced_corpus.json')
    fit_parser.add_argument('--output', '-o', default='size_adjustment_model.json', help='Output model file')
    
    # Adjust command
    adjust_parser = subparsers.add_parser('adjust', help='Adjust a scenario library')
    adjust_parser.add_argument('--library', '-l', required=True, help='Path to scenario_library.json')
    adjust_parser.add_argument('--output', '-o', required=True, help='Output path')
    adjust_parser.add_argument('--size', '-s', type=float, required=True, help='Portfolio size in £m')
    adjust_parser.add_argument('--model', '-m', help='Path to fitted model (optional)')
    
    # Table command
    table_parser = subparsers.add_parser('table', help='Show adjustment factor table')
    table_parser.add_argument('--model', '-m', help='Path to fitted model (optional)')
    
    # Calculate command
    calc_parser = subparsers.add_parser('calc', help='Calculate single adjustment')
    calc_parser.add_argument('--severity', type=float, required=True, help='Base severity ratio')
    calc_parser.add_argument('--size', type=float, required=True, help='Portfolio size in £m')
    calc_parser.add_argument('--lob', help='Line of business')
    calc_parser.add_argument('--model', '-m', help='Path to fitted model (optional)')
    
    args = parser.parse_args()
    
    if args.command == 'fit':
        adjuster = PortfolioSizeAdjuster()
        adjuster.fit(args.corpus)
        adjuster.model.save(args.output)
        adjuster.print_summary()
        
    elif args.command == 'adjust':
        if args.model:
            model = SizeAdjustmentModel.load(args.model)
            adjuster = PortfolioSizeAdjuster(model)
        else:
            adjuster = PortfolioSizeAdjuster()
        
        count = adjuster.adjust_scenario_library(args.library, args.output, args.size)
        print(f"\nAdjusted {count} scenarios for £{args.size}m portfolio")
        
    elif args.command == 'table':
        if args.model:
            model = SizeAdjustmentModel.load(args.model)
            adjuster = PortfolioSizeAdjuster(model)
        else:
            adjuster = PortfolioSizeAdjuster()
        
        adjuster.print_summary()
        
    elif args.command == 'calc':
        if args.model:
            model = SizeAdjustmentModel.load(args.model)
            adjuster = PortfolioSizeAdjuster(model)
        else:
            adjuster = PortfolioSizeAdjuster()
        
        adjusted = adjuster.adjust_severity(args.severity, args.size, args.lob)
        factor = adjuster.adjustment_factor(args.size, args.lob)
        
        print(f"\nBase severity: {args.severity:.2%}")
        print(f"Portfolio size: £{args.size}m")
        print(f"LOB: {args.lob or 'Overall'}")
        print(f"Coefficient: {adjuster.get_coefficient(args.lob):.4f}")
        print(f"Adjustment factor: {factor:.3f}")
        print(f"Adjusted severity: {adjusted:.2%}")
        
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
