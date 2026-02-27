"""
Main Pipeline Orchestrator

Coordinates the full stress test generation workflow:

PHASE 1: Build Synthetic Scenario Library (run once)
  Step 1: Prepare historical data with severity ratios and complexity scores
  Step 2: Build joint semantic-numeric embedding space
  Step 3: Select GPD threshold and fit distribution
  Step 4: Generate synthetic scenarios across severity × complexity grid
  Step 5: Validate semantic coverage
  Step 6: Importance sample to match GPD distribution
  Step 7: Validate coherence
  Step 8: Generate diagnostic plots
  → Output: validated_scenario_library.json

PHASE 2: Portfolio Query (run per request)
  Step A: Convert return period to severity
  Step B: Filter and select scenarios
  Step C: Fine-tune for portfolio
  Step D: Generate explanations
  → Output: portfolio_stress_scenarios.json

Usage (from project root):
  python scripts/stress_test/pipeline.py build --corpus results/combined/unified_corpus.json --output results/stress_test/
  python scripts/stress_test/pipeline.py query --library results/stress_test/validated_scenario_library.json --gpd results/stress_test/gpd_fit.json --reserves 200 --return-period 100
"""

import json
import logging
import numpy as np
from pathlib import Path
from typing import List, Dict, Optional
from dataclasses import dataclass, asdict
import time
import sys
import warnings

# Suppress non-critical numerical warnings from sklearn
warnings.filterwarnings('ignore', category=RuntimeWarning, 
                        message='invalid value encountered in divide')
warnings.filterwarnings('ignore', category=RuntimeWarning,
                        message='divide by zero encountered')

# Add stress_test directory to path for imports
_script_dir = Path(__file__).resolve().parent
if str(_script_dir) not in sys.path:
    sys.path.insert(0, str(_script_dir))

from config import (
    EmbeddingConfig, EVTConfig, GenerationConfig, 
    ValidationConfig, QueryConfig,
    HistoricalMovement, SyntheticScenario, PortfolioSpec, StressScenario,
    DEFAULT_EMBEDDING_CONFIG, DEFAULT_EVT_CONFIG, DEFAULT_GENERATION_CONFIG,
    DEFAULT_VALIDATION_CONFIG, DEFAULT_QUERY_CONFIG, LLOYDS_LOBS
)
from data_preparation import prepare_historical_data, analyze_coverage
from joint_embedding import JointEmbeddingSpace
from evt_threshold import fit_gpd_constrained, GPDFit, return_period_to_severity
from synthetic_generation import SyntheticScenarioGenerator
from coverage_validation import validate_coverage, flag_edge_cases
from importance_sampling import resample_to_gpd
from coherence_validation import validate_coherence, filter_incoherent
from portfolio_query import PortfolioQueryEngine
from visualization import generate_all_diagnostic_plots, plot_latent_space
from evt_visualization import generate_evt_diagnostic_plots, plot_evt_summary

logger = logging.getLogger(__name__)


# =============================================================================
# Helper Functions
# =============================================================================

def to_python_types(obj):
    """Recursively convert numpy types to Python types for JSON serialization."""
    if isinstance(obj, dict):
        return {k: to_python_types(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [to_python_types(v) for v in obj]
    elif isinstance(obj, tuple):
        return tuple(to_python_types(v) for v in obj)
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    elif isinstance(obj, (np.integer, np.int64, np.int32)):
        return int(obj)
    elif isinstance(obj, (np.floating, np.float64, np.float32)):
        return float(obj)
    elif isinstance(obj, (np.bool_, bool)):
        return bool(obj)
    elif obj is None or isinstance(obj, (str, int, float)):
        return obj
    else:
        return str(obj)  # Fallback to string


# =============================================================================
# Pipeline Configuration
# =============================================================================

@dataclass
class PipelineConfig:
    """Full pipeline configuration."""
    # Paths
    corpus_path: str = "results/combined/unified_corpus.json"
    output_dir: str = "results/stress_test"
    
    # Component configs
    embedding_config: EmbeddingConfig = None
    evt_config: EVTConfig = None
    generation_config: GenerationConfig = None
    validation_config: ValidationConfig = None
    query_config: QueryConfig = None
    
    # Pipeline options
    direction_filter: str = "strengthening"  # Focus on adverse development
    skip_generation: bool = False  # Skip if library already exists
    skip_validation: bool = False  # Skip validation steps
    target_library_size: int = 2000
    
    def __post_init__(self):
        self.embedding_config = self.embedding_config or DEFAULT_EMBEDDING_CONFIG
        self.evt_config = self.evt_config or DEFAULT_EVT_CONFIG
        self.generation_config = self.generation_config or DEFAULT_GENERATION_CONFIG
        self.validation_config = self.validation_config or DEFAULT_VALIDATION_CONFIG
        self.query_config = self.query_config or DEFAULT_QUERY_CONFIG


# =============================================================================
# Phase 1: Build Scenario Library
# =============================================================================

class ScenarioLibraryBuilder:
    """
    Builds the synthetic scenario library through all Phase 1 steps.
    """
    
    def __init__(self, config: PipelineConfig):
        self.config = config
        self.output_dir = Path(config.output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # State
        self.historical_movements: List[HistoricalMovement] = []
        self.embedding_space: Optional[JointEmbeddingSpace] = None
        self.gpd_fit: Optional[GPDFit] = None
        self.synthetic_scenarios: List[SyntheticScenario] = []
        self.validated_library: List[SyntheticScenario] = []
        
        # Timing
        self.step_times: Dict[str, float] = {}
    
    def run(self) -> List[SyntheticScenario]:
        """
        Execute full Phase 1 pipeline.
        """
        logger.info("=" * 60)
        logger.info("PHASE 1: Building Synthetic Scenario Library")
        logger.info("=" * 60)
        
        start_time = time.time()
        
        # Step 1: Prepare historical data
        self._step1_prepare_data()
        
        # Step 2: Build embedding space
        self._step2_build_embedding_space()
        
        # Step 3: Fit GPD
        self._step3_fit_gpd()
        
        # Step 4: Generate synthetic scenarios
        if not self.config.skip_generation:
            self._step4_generate_scenarios()
        else:
            self._load_existing_scenarios()
        
        # Step 5: Validate coverage
        if not self.config.skip_validation:
            self._step5_validate_coverage()
        
        # Step 6: Importance sample
        self._step6_importance_sample()
        
        # Step 7: Validate coherence
        if not self.config.skip_validation:
            self._step7_validate_coherence()
        
        # Step 8: Generate diagnostic plots
        self._step8_generate_plots()
        
        # Save final library
        self._save_final_library()
        
        total_time = time.time() - start_time
        logger.info(f"\nPhase 1 complete in {total_time:.1f}s")
        logger.info(f"Final library size: {len(self.validated_library)} scenarios")
        
        return self.validated_library
    
    def _step1_prepare_data(self):
        """Step 1: Prepare historical data."""
        logger.info("\n--- Step 1: Preparing Historical Data ---")
        start = time.time()
        
        self.historical_movements = prepare_historical_data(
            self.config.corpus_path,
            str(self.output_dir / "prepared_data.json"),
            self.config.direction_filter
        )
        
        # Analyze coverage
        coverage = analyze_coverage(self.historical_movements)
        logger.info(f"Years covered: {min(coverage['by_year'].keys())} - {max(coverage['by_year'].keys())}")
        logger.info(f"LOBs covered: {len(coverage['by_lob'])}")
        
        self.step_times['step1'] = time.time() - start
        logger.info(f"Step 1 complete in {self.step_times['step1']:.1f}s")
    
    def _step2_build_embedding_space(self):
        """Step 2: Build joint embedding space."""
        logger.info("\n--- Step 2: Building Joint Embedding Space ---")
        start = time.time()
        
        self.embedding_space = JointEmbeddingSpace(self.config.embedding_config)
        self.embedding_space.fit(self.historical_movements)
        self.embedding_space.save(str(self.output_dir / "embedding_space"))
        
        bounds = self.embedding_space.get_latent_bounds()
        logger.info(f"Latent space bounds:")
        for dim, (lo, hi) in bounds.items():
            logger.info(f"  {dim}: [{lo:.3f}, {hi:.3f}]")
        
        self.step_times['step2'] = time.time() - start
        logger.info(f"Step 2 complete in {self.step_times['step2']:.1f}s")
    
    def _step3_fit_gpd(self):
        """Step 3: Select threshold and fit GPD."""
        logger.info("\n--- Step 3: Fitting GPD ---")
        start = time.time()
        
        severities = np.array([m.severity_ratio for m in self.historical_movements])
        self.gpd_fit = fit_gpd_constrained(severities, config=self.config.evt_config)
        
        # Save GPD parameters
        gpd_data = {
            'threshold': float(self.gpd_fit.threshold),
            'shape': float(self.gpd_fit.shape),
            'scale': float(self.gpd_fit.scale),
            'shape_ci': [float(x) for x in self.gpd_fit.shape_ci] if self.gpd_fit.shape_ci else None,
            'scale_ci': [float(x) for x in self.gpd_fit.scale_ci] if self.gpd_fit.scale_ci else None,
            'n_exceedances': int(self.gpd_fit.n_exceedances),
            'n_total': int(self.gpd_fit.n_total),
            'ad_statistic': float(self.gpd_fit.ad_statistic) if self.gpd_fit.ad_statistic else None,
            'ad_pvalue': float(self.gpd_fit.ad_pvalue) if self.gpd_fit.ad_pvalue else None,
            'ks_statistic': float(self.gpd_fit.ks_statistic) if self.gpd_fit.ks_statistic else None,
            'ks_pvalue': float(self.gpd_fit.ks_pvalue) if self.gpd_fit.ks_pvalue else None
        }
        
        with open(self.output_dir / "gpd_fit.json", 'w') as f:
            json.dump(gpd_data, f, indent=2)
        
        logger.info(f"Threshold: {self.gpd_fit.threshold:.4f}")
        logger.info(f"Shape (xi): {self.gpd_fit.shape:.4f}")
        logger.info(f"Scale (sigma): {self.gpd_fit.scale:.4f}")
        logger.info(f"A-D p-value: {self.gpd_fit.ad_pvalue:.4f}")
        
        # Return period examples
        for rp in [10, 50, 100, 200]:
            sev = return_period_to_severity(self.gpd_fit, rp)
            logger.info(f"  {rp}-year → {sev:.1%}")
        
        self.step_times['step3'] = time.time() - start
        logger.info(f"Step 3 complete in {self.step_times['step3']:.1f}s")
    
    def _step4_generate_scenarios(self):
        """Step 4: Generate synthetic scenarios."""
        logger.info("\n--- Step 4: Generating Synthetic Scenarios ---")
        start = time.time()
        
        generator = SyntheticScenarioGenerator(
            self.embedding_space, 
            self.config.generation_config
        )
        
        self.synthetic_scenarios = generator.generate_all()
        
        generator.save_scenarios(
            self.synthetic_scenarios,
            str(self.output_dir / "synthetic_scenarios_raw.json")
        )
        
        logger.info(f"Generated {len(self.synthetic_scenarios)} scenarios")
        logger.info(f"API calls: {generator.api_calls}")
        logger.info(f"Total tokens: {generator.total_tokens}")
        
        self.step_times['step4'] = time.time() - start
        logger.info(f"Step 4 complete in {self.step_times['step4']:.1f}s")
    
    def _load_existing_scenarios(self):
        """Load existing scenarios if skipping generation."""
        logger.info("\n--- Step 4: Loading Existing Scenarios ---")
        
        scenarios_path = self.output_dir / "synthetic_scenarios_raw.json"
        if scenarios_path.exists():
            with open(scenarios_path, 'r') as f:
                data = json.load(f)
            self.synthetic_scenarios = [SyntheticScenario(**s) for s in data['scenarios']]
            logger.info(f"Loaded {len(self.synthetic_scenarios)} existing scenarios")
        else:
            logger.warning("No existing scenarios found, generation required")
            self._step4_generate_scenarios()
    
    def _step5_validate_coverage(self):
        """Step 5: Validate semantic coverage."""
        logger.info("\n--- Step 5: Validating Semantic Coverage ---")
        logger.info("(This step may take 2-5 minutes for MMD permutation test)")
        start = time.time()
        
        # Get latent coordinates
        historical_coords = self.embedding_space.latent_coords
        
        # Project synthetic scenarios
        synthetic_coords = []
        for s in self.synthetic_scenarios:
            if s.latent_coords:
                synthetic_coords.append(s.latent_coords)
            else:
                # Project using embedding space
                coords = self.embedding_space.project(
                    s.narrative,
                    s.severity_ratio,
                    s.complexity_score,
                    [0.0] * 13  # LOB vector placeholder
                )
                s.latent_coords = coords.tolist()
                synthetic_coords.append(coords.tolist())
        
        synthetic_coords = np.array(synthetic_coords)
        
        # Run validation
        result = validate_coverage(
            historical_coords,
            synthetic_coords,
            self.config.validation_config
        )
        
        # Flag edge cases
        self.synthetic_scenarios = flag_edge_cases(
            self.synthetic_scenarios,
            result.boundary_violation_indices
        )
        
        # Save validation results (convert numpy types to Python types)
        validation_data = {
            'boundary_violations': int(result.n_boundary_violations),
            'boundary_violation_rate': float(result.boundary_violation_rate),
            'mmd_statistic': float(result.mmd_statistic),
            'mmd_pvalue': float(result.mmd_pvalue),
            'mmd_passed': bool(result.mmd_passed),
            'coverage_rate': float(result.coverage_rate),
            'kl_divergence': [float(x) for x in result.kl_divergence] if hasattr(result.kl_divergence, '__iter__') else float(result.kl_divergence),
            'passed': bool(result.passed),
            'warnings': list(result.warnings) if result.warnings else []
        }
        
        with open(self.output_dir / "coverage_validation.json", 'w') as f:
            json.dump(validation_data, f, indent=2)
        
        logger.info(f"Coverage validation: {'PASSED' if result.passed else 'FAILED'}")
        if result.warnings:
            for w in result.warnings:
                logger.warning(f"  {w}")
        
        self.step_times['step5'] = time.time() - start
        logger.info(f"Step 5 complete in {self.step_times['step5']:.1f}s")
    
    def _step6_importance_sample(self):
        """Step 6: Importance sample to match GPD."""
        logger.info("\n--- Step 6: Importance Sampling ---")
        start = time.time()
        
        historical_severities = np.array([m.severity_ratio for m in self.historical_movements])
        
        resampled, result = resample_to_gpd(
            self.synthetic_scenarios,
            self.gpd_fit,
            historical_severities,
            self.config.target_library_size
        )
        
        self.synthetic_scenarios = resampled
        
        # Save resampling results (convert numpy types)
        with open(self.output_dir / "importance_sampling.json", 'w') as f:
            json.dump({
                'original_count': int(result.original_count),
                'sampled_count': int(result.sampled_count),
                'kl_improvement': float(result.kl_divergence_original - result.kl_divergence_sampled),
                'kl_original': float(result.kl_divergence_original),
                'kl_sampled': float(result.kl_divergence_sampled),
                'target_bin_probs': to_python_types(result.target_bin_probs),
                'sampled_bin_counts': to_python_types(result.sampled_bin_counts)
            }, f, indent=2)
        
        logger.info(f"Resampled: {result.original_count} → {result.sampled_count}")
        logger.info(f"KL divergence: {result.kl_divergence_original:.4f} → {result.kl_divergence_sampled:.4f}")
        
        self.step_times['step6'] = time.time() - start
        logger.info(f"Step 6 complete in {self.step_times['step6']:.1f}s")
    
    def _step7_validate_coherence(self):
        """Step 7: Validate narrative-severity coherence."""
        logger.info("\n--- Step 7: Validating Coherence ---")
        start = time.time()
        
        historical_texts = [m.narrative or '' for m in self.historical_movements]
        historical_severities = np.array([m.severity_ratio for m in self.historical_movements])
        
        results, summary = validate_coherence(
            self.synthetic_scenarios,
            historical_texts,
            historical_severities,
            self.config.validation_config
        )
        
        # Filter incoherent scenarios (flag rather than remove)
        self.validated_library = filter_incoherent(
            self.synthetic_scenarios, results, mode='flag'
        )
        
        # Save coherence results (convert numpy types)
        with open(self.output_dir / "coherence_validation.json", 'w') as f:
            json.dump(to_python_types(summary), f, indent=2)
        
        logger.info(f"Coherence rate: {summary['coherence_rate']:.1%}")
        logger.info(f"Keyword failures: {summary['keyword_failures']}")
        logger.info(f"Regression failures: {summary['regression_failures']}")
        
        self.step_times['step7'] = time.time() - start
        logger.info(f"Step 7 complete in {self.step_times['step7']:.1f}s")
    
    def _step8_generate_plots(self):
        """Step 8: Generate diagnostic plots."""
        logger.info("\n--- Step 8: Generating Diagnostic Plots ---")
        start = time.time()
        
        # Create plots directory
        plots_dir = self.output_dir / "plots"
        plots_dir.mkdir(parents=True, exist_ok=True)
        
        # Get latent coordinates
        historical_coords = self.embedding_space.latent_coords
        
        # Project synthetic scenarios if not already done
        synthetic_coords = []
        for s in self.synthetic_scenarios:
            if s.latent_coords:
                synthetic_coords.append(s.latent_coords)
            else:
                coords = self.embedding_space.project(
                    s.narrative or '',
                    s.severity_ratio,
                    s.complexity_score,
                    [0.0] * len(LLOYDS_LOBS)
                )
                synthetic_coords.append(coords.tolist())
        synthetic_coords = np.array(synthetic_coords)
        
        # Get severity and complexity arrays
        historical_severities = np.array([m.severity_ratio for m in self.historical_movements])
        synthetic_severities = np.array([s.severity_ratio for s in self.synthetic_scenarios])
        historical_complexities = np.array([m.complexity_score for m in self.historical_movements])
        
        # Generate all plots
        try:
            figures = generate_all_diagnostic_plots(
                historical_coords=historical_coords,
                synthetic_coords=synthetic_coords,
                historical_severities=historical_severities,
                synthetic_severities=synthetic_severities,
                historical_complexities=historical_complexities,
                output_dir=str(plots_dir)
            )
            logger.info(f"Generated {len(figures)} embedding/coverage plots")
        except Exception as e:
            logger.warning(f"Failed to generate embedding plots: {e}")
        
        # Generate EVT diagnostic plots
        try:
            evt_plots_dir = plots_dir / "evt"
            evt_plots_dir.mkdir(parents=True, exist_ok=True)
            
            evt_figures = generate_evt_diagnostic_plots(
                historical_severities,
                threshold=self.gpd_fit.threshold if self.gpd_fit else None,
                output_dir=str(evt_plots_dir)
            )
            
            # Also generate summary
            plot_evt_summary(
                historical_severities,
                threshold=self.gpd_fit.threshold if self.gpd_fit else None,
                output_path=str(evt_plots_dir / 'evt_0_summary.png')
            )
            
            logger.info(f"Generated {len(evt_figures) + 1} EVT diagnostic plots")
        except Exception as e:
            logger.warning(f"Failed to generate EVT plots: {e}")
        
        self.step_times['step8'] = time.time() - start
        logger.info(f"Step 8 complete in {self.step_times['step8']:.1f}s")
    
    def _save_final_library(self):
        """Save the final validated scenario library."""
        logger.info("\n--- Saving Final Library ---")
        
        # Use synthetic_scenarios if validation was skipped
        if not self.validated_library:
            self.validated_library = self.synthetic_scenarios
        
        output_data = {
            'scenarios': [vars(s) for s in self.validated_library],
            'metadata': {
                'total_scenarios': len(self.validated_library),
                'edge_cases': sum(1 for s in self.validated_library if s.is_edge_case),
                'gpd_threshold': self.gpd_fit.threshold,
                'gpd_shape': self.gpd_fit.shape,
                'gpd_scale': self.gpd_fit.scale,
                'step_times': self.step_times
            }
        }
        
        with open(self.output_dir / "validated_scenario_library.json", 'w') as f:
            json.dump(output_data, f, indent=2, default=str)
        
        logger.info(f"Saved {len(self.validated_library)} scenarios to validated_scenario_library.json")


# =============================================================================
# Phase 2: Portfolio Query Interface
# =============================================================================

class StressTestGenerator:
    """
    User-facing interface for generating portfolio-specific stress tests.
    """
    
    def __init__(self, library_dir: str = "results/stress_test"):
        self.library_dir = Path(library_dir)
        
        # Load components
        self._load_library()
        self._load_gpd()
        self._load_embedding_space()
        
        # Create query engine
        self.engine = PortfolioQueryEngine(
            self.scenarios,
            self.gpd_fit,
            self.embedding_space
        )
    
    def _load_library(self):
        """Load scenario library."""
        with open(self.library_dir / "validated_scenario_library.json", 'r') as f:
            data = json.load(f)
        self.scenarios = [SyntheticScenario(**s) for s in data['scenarios']]
        logger.info(f"Loaded {len(self.scenarios)} scenarios")
    
    def _load_gpd(self):
        """Load GPD fit."""
        with open(self.library_dir / "gpd_fit.json", 'r') as f:
            data = json.load(f)
        self.gpd_fit = GPDFit(**data)
        logger.info(f"Loaded GPD: xi={self.gpd_fit.shape:.4f}, sigma={self.gpd_fit.scale:.4f}")
    
    def _load_embedding_space(self):
        """Load embedding space."""
        embedding_dir = self.library_dir / "embedding_space"
        if embedding_dir.exists():
            self.embedding_space = JointEmbeddingSpace.load(str(embedding_dir))
        else:
            self.embedding_space = None
            logger.warning("Embedding space not found, historical analogues disabled")
    
    def generate(self,
                 lob_weights: Dict[str, float],
                 total_reserves_gbp_m: float,
                 return_period: int = 100,
                 n_scenarios: int = 5) -> List[StressScenario]:
        """
        Generate stress scenarios for a portfolio.
        
        Args:
            lob_weights: Dictionary of LOB name to weight (should sum to 1)
            total_reserves_gbp_m: Total reserves in GBP millions
            return_period: Return period in years (e.g., 100 = 1-in-100)
            n_scenarios: Number of scenarios to generate
        
        Returns:
            List of StressScenario objects
        
        Example:
            generator = StressTestGenerator()
            scenarios = generator.generate(
                lob_weights={'Property': 0.5, 'Casualty': 0.3, 'Marine': 0.2},
                total_reserves_gbp_m=200,
                return_period=100,
                n_scenarios=5
            )
        """
        # Normalise weights
        total = sum(lob_weights.values())
        lob_weights = {k: v / total for k, v in lob_weights.items()}
        
        portfolio = PortfolioSpec(
            lob_weights=lob_weights,
            total_reserves_gbp_m=total_reserves_gbp_m
        )
        
        return self.engine.query(portfolio, return_period, n_scenarios)
    
    def return_period_to_severity(self, return_period: int) -> float:
        """Convert return period to expected severity."""
        return return_period_to_severity(self.gpd_fit, return_period)
    
    def severity_distribution_summary(self) -> Dict:
        """Get summary statistics of library severity distribution."""
        severities = [s.severity_ratio for s in self.scenarios]
        return {
            'count': len(severities),
            'min': min(severities),
            'max': max(severities),
            'mean': np.mean(severities),
            'median': np.median(severities),
            'p90': np.percentile(severities, 90),
            'p95': np.percentile(severities, 95),
            'p99': np.percentile(severities, 99)
        }


# =============================================================================
# CLI Entry Points
# =============================================================================

def build_library(config: PipelineConfig = None) -> List[SyntheticScenario]:
    """Build the scenario library (Phase 1)."""
    config = config or PipelineConfig()
    builder = ScenarioLibraryBuilder(config)
    return builder.run()


def query_portfolio(lob_weights: Dict[str, float],
                    reserves: float,
                    return_period: int = 100,
                    n_scenarios: int = 5,
                    library_dir: str = "results/stress_test") -> List[StressScenario]:
    """Query stress scenarios for a portfolio (Phase 2)."""
    generator = StressTestGenerator(library_dir)
    return generator.generate(lob_weights, reserves, return_period, n_scenarios)


if __name__ == "__main__":
    import argparse
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    parser = argparse.ArgumentParser(description="Stress Test Generation Pipeline")
    subparsers = parser.add_subparsers(dest='command', help='Commands')
    
    # Build command
    build_parser = subparsers.add_parser('build', help='Build scenario library (Phase 1)')
    build_parser.add_argument('--corpus', '-c', default='results/combined/unified_corpus.json',
                              help='Path to unified corpus')
    build_parser.add_argument('--output', '-o', default='results/stress_test',
                              help='Output directory')
    build_parser.add_argument('--target-size', '-n', type=int, default=2000,
                              help='Target library size')
    build_parser.add_argument('--skip-generation', action='store_true',
                              help='Skip generation (use existing)')
    build_parser.add_argument('--skip-validation', action='store_true',
                              help='Skip validation steps')
    
    # Query command
    query_parser = subparsers.add_parser('query', help='Query portfolio scenarios (Phase 2)')
    query_parser.add_argument('--library', '-l', default='results/stress_test',
                              help='Path to scenario library')
    query_parser.add_argument('--reserves', '-r', type=float, required=True,
                              help='Total reserves (GBP millions)')
    query_parser.add_argument('--return-period', '-p', type=int, default=100,
                              help='Return period (years)')
    query_parser.add_argument('--n-scenarios', '-n', type=int, default=5,
                              help='Number of scenarios')
    query_parser.add_argument('--lob', action='append', nargs=2,
                              metavar=('LOB', 'WEIGHT'),
                              help='LOB and weight (repeat for multiple)')
    query_parser.add_argument('--output', '-o',
                              help='Output file (optional)')
    
    # Summary command
    summary_parser = subparsers.add_parser('summary', help='Show library summary statistics')
    summary_parser.add_argument('--library', '-l', required=True,
                                help='Path to validated_scenario_library.json')
    
    # Normalize command
    normalize_parser = subparsers.add_parser('normalize', help='Re-normalize LOBs in existing library')
    normalize_parser.add_argument('--library', '-l', required=True,
                                  help='Path to validated_scenario_library.json')
    normalize_parser.add_argument('--output', '-o',
                                  help='Output path (defaults to overwriting input)')
    
    args = parser.parse_args()
    
    if args.command == 'build':
        config = PipelineConfig(
            corpus_path=args.corpus,
            output_dir=args.output,
            target_library_size=args.target_size,
            skip_generation=args.skip_generation,
            skip_validation=args.skip_validation
        )
        build_library(config)
        
    elif args.command == 'query':
        # Parse LOB weights
        lob_weights = {}
        if args.lob:
            for lob, weight in args.lob:
                lob_weights[lob] = float(weight)
        else:
            # Default portfolio
            lob_weights = {
                'Property': 0.4,
                'Casualty': 0.3,
                'Marine': 0.15,
                'Professional Lines': 0.15
            }
        
        # Handle library path - can be directory or file
        library_path = Path(args.library)
        if library_path.is_file():
            library_dir = str(library_path.parent)
        else:
            library_dir = str(library_path)
        
        scenarios = query_portfolio(
            lob_weights,
            args.reserves,
            args.return_period,
            args.n_scenarios,
            library_dir
        )
        
        # Print results
        print(f"\n{'='*60}")
        print(f"{args.return_period}-Year Stress Scenarios for £{args.reserves:.0f}m Portfolio")
        print(f"{'='*60}")
        
        for i, s in enumerate(scenarios, 1):
            print(f"\n--- Scenario {i}: {s.name} ---")
            print(f"Severity: {s.severity_ratio:.1%}")
            print(f"Portfolio Impact: {s.portfolio_impact:.1%}")
            print(f"\nLOB Impacts:")
            for lob, impact in sorted(s.lob_impacts.items(), key=lambda x: -x[1]):
                if impact > 0:
                    print(f"  {lob}: {impact:.1%}")
            print(f"\nNarrative:\n{s.narrative[:500]}...")
        
        # Save if requested
        if args.output:
            with open(args.output, 'w') as f:
                json.dump([vars(s) for s in scenarios], f, indent=2, default=str)
            print(f"\nSaved to {args.output}")
    
    elif args.command == 'summary':
        # Load and summarize library
        library_path = Path(args.library)
        
        with open(library_path, 'r') as f:
            data = json.load(f)
        
        scenarios = data.get('scenarios', data) if isinstance(data, dict) else data
        
        print(f"\n{'='*60}")
        print("SCENARIO LIBRARY SUMMARY")
        print(f"{'='*60}")
        print(f"\nTotal scenarios: {len(scenarios)}")
        
        # Severity distribution
        severities = [s.get('severity_ratio', 0) for s in scenarios]
        print(f"\nSeverity Distribution:")
        print(f"  Min:    {min(severities):.1%}")
        print(f"  25th:   {np.percentile(severities, 25):.1%}")
        print(f"  Median: {np.percentile(severities, 50):.1%}")
        print(f"  75th:   {np.percentile(severities, 75):.1%}")
        print(f"  95th:   {np.percentile(severities, 95):.1%}")
        print(f"  Max:    {max(severities):.1%}")
        
        # Cause category distribution
        from collections import Counter
        causes = Counter(s.get('cause_category', 'Unknown') for s in scenarios)
        print(f"\nCause Categories:")
        for cause, count in causes.most_common():
            print(f"  {cause}: {count} ({100*count/len(scenarios):.1f}%)")
        
        # LOB coverage
        lobs_seen = set()
        for s in scenarios:
            lob_breakdown = s.get('lob_breakdown', {})
            if isinstance(lob_breakdown, dict):
                lobs_seen.update(lob_breakdown.keys())
        print(f"\nLOBs covered: {len(lobs_seen)}")
        for lob in sorted(lobs_seen):
            count = sum(1 for s in scenarios if lob in s.get('lob_breakdown', {}))
            print(f"  {lob}: {count} scenarios")
        
        # Validation flags
        flagged = sum(1 for s in scenarios if s.get('flagged_incoherent') or s.get('is_edge_case'))
        print(f"\nFlagged scenarios: {flagged} ({100*flagged/len(scenarios):.1f}%)")
        
        # GPD fit info
        gpd_path = library_path.parent / "gpd_fit.json"
        if gpd_path.exists():
            with open(gpd_path, 'r') as f:
                gpd = json.load(f)
            print(f"\nGPD Fit:")
            print(f"  Threshold: {gpd['threshold']:.1%}")
            print(f"  Shape (xi): {gpd['shape']:.4f}")
            print(f"  Scale (sigma): {gpd['scale']:.4f}")
            
            # Return period examples
            from evt_threshold import return_period_to_severity, GPDFit
            gpd_fit = GPDFit(**gpd)
            print(f"\nReturn Period → Severity:")
            for rp in [10, 25, 50, 100, 200]:
                sev = return_period_to_severity(gpd_fit, rp)
                print(f"  {rp:3d}-year → {sev:.1%}")
    
    elif args.command == 'normalize':
        # Re-normalize LOBs in existing library
        from synthetic_generation import normalize_lob_breakdown
        
        library_path = Path(args.library)
        output_path = Path(args.output) if args.output else library_path
        
        with open(library_path, 'r') as f:
            data = json.load(f)
        
        # Handle both formats
        if isinstance(data, dict) and 'scenarios' in data:
            scenarios = data['scenarios']
            is_wrapped = True
        else:
            scenarios = data
            is_wrapped = False
        
        print(f"Normalizing {len(scenarios)} scenarios...")
        
        # Track LOB changes
        lobs_before = set()
        lobs_after = set()
        
        for s in scenarios:
            lob_breakdown = s.get('lob_breakdown', {})
            if isinstance(lob_breakdown, dict):
                lobs_before.update(lob_breakdown.keys())
                normalized = normalize_lob_breakdown(lob_breakdown)
                s['lob_breakdown'] = normalized
                lobs_after.update(normalized.keys())
        
        print(f"LOBs before: {len(lobs_before)} → after: {len(lobs_after)}")
        
        # Save
        if is_wrapped:
            data['scenarios'] = scenarios
            output_data = data
        else:
            output_data = scenarios
        
        with open(output_path, 'w') as f:
            json.dump(output_data, f, indent=2, default=str)
        
        print(f"Saved normalized library to {output_path}")
        
        # Show new LOB distribution
        print("\nNormalized LOB distribution:")
        from collections import Counter
        lob_counts = Counter()
        for s in scenarios:
            for lob in s.get('lob_breakdown', {}).keys():
                lob_counts[lob] += 1
        for lob, count in lob_counts.most_common():
            print(f"  {lob}: {count}")
    
    else:
        parser.print_help()
