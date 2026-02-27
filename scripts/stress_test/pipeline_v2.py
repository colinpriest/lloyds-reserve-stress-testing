"""
Stress Test Pipeline v2 - Anchor-Based Generation

Major changes from v1:
1. Anchor-based generation: Each historical example generates 10 scenarios
2. Quantile-based binning: 20 bins at 5% quantiles, min 50 per bin
3. Neighbour-based query: Find 500 neighbours, use empirical return period

Usage:
    # Build library (Phase 1)
    python pipeline_v2.py build --corpus results/combined/unified_corpus.json --output results/stress_test_v2
    
    # Query (Phase 2)
    python pipeline_v2.py query --library results/stress_test_v2 --reserves 500 --return-period 100 --lob Property 0.4 --lob Casualty 0.3
    
    # Summary
    python pipeline_v2.py summary --library results/stress_test_v2/scenario_library.json
"""

import sys
from pathlib import Path
_script_dir = Path(__file__).resolve().parent
if str(_script_dir) not in sys.path:
    sys.path.insert(0, str(_script_dir))

import json
import logging
import numpy as np
from pathlib import Path
from typing import List, Dict, Optional
from dataclasses import dataclass, asdict
import time
import warnings

warnings.filterwarnings('ignore', category=RuntimeWarning)

from config import (
    EmbeddingConfig, GenerationConfig, ValidationConfig, QueryConfig,
    HistoricalMovement, SyntheticScenario, PortfolioSpec, StressScenario,
    DEFAULT_EMBEDDING_CONFIG, DEFAULT_GENERATION_CONFIG, DEFAULT_QUERY_CONFIG,
    LLOYDS_LOBS
)
from data_preparation import prepare_historical_data, analyze_coverage
from joint_embedding import JointEmbeddingSpace
from synthetic_generation_v2 import (
    AnchorBasedGenerator, 
    apply_quantile_sampling,
    compute_quantile_bins
)
from gpd_fitting import fit_gpd_improved, GPDFitResult, sample_from_gpd
from gpd_sampling import (
    create_gpd_sampled_library,
    analyze_severity_distribution,
    SplicedDistribution
)
from portfolio_query_v2 import NeighbourBasedQuery, create_portfolio

logger = logging.getLogger(__name__)


# =============================================================================
# Helper Functions
# =============================================================================

def to_python_types(obj):
    """Convert numpy types to Python types for JSON."""
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
        return str(obj)


# =============================================================================
# Pipeline Configuration
# =============================================================================

@dataclass
class PipelineConfigV2:
    """Configuration for v2 pipeline."""
    corpus_path: str = "results/combined/unified_corpus.json"
    output_dir: str = "results/stress_test_v2"
    
    # Generation parameters
    scenarios_per_anchor: int = 10
    extrapolation_factor: float = 2.5  # Allow up to 2.5x anchor severity
    llm_model: str = "gpt-4o-mini"  # LLM model for scenario generation
    
    # GPD sampling parameters
    target_library_size: int = 2000
    gpd_percentile_min: float = 80  # Min threshold percentile to search
    gpd_percentile_max: float = 99  # Max threshold percentile to search
    severity_mode: str = "auto"  # constrained, unconstrained, unconstrained_no_max, empirical, auto
    
    # Query parameters
    n_neighbours: int = 500
    
    # Audit trail parameters
    run_assessments: bool = False  # Run LLM assessments on generated scenarios
    assessment_mode: str = "sample"  # "sample", "all", or "tail" (≥50yr return period)
    assessment_sample_rate: float = 0.1  # Fraction of scenarios to assess (if mode=sample)
    max_assessments: int = 100  # Maximum number of assessments (if mode=sample)
    
    # Component configs
    embedding_config: EmbeddingConfig = None
    generation_config: GenerationConfig = None
    
    def __post_init__(self):
        self.embedding_config = self.embedding_config or DEFAULT_EMBEDDING_CONFIG
        # Create generation config with specified model
        if self.generation_config is None:
            self.generation_config = GenerationConfig(llm_model=self.llm_model)
        else:
            self.generation_config.llm_model = self.llm_model


# =============================================================================
# Phase 1: Library Building
# =============================================================================

class LibraryBuilder:
    """Builds the scenario library using anchor-based generation."""
    
    def __init__(self, config: PipelineConfigV2):
        self.config = config
        self.output_dir = Path(config.output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # State
        self.historical_movements = []
        self.embedding_space = None
        self.raw_scenarios = []
        self.final_scenarios = []
        self.spliced_dist = None
        self.gpd_stats = None
        
        # Timing
        self.step_times = {}
    
    def run(self):
        """Execute the full build pipeline."""
        logger.info("="*60)
        logger.info("PHASE 1: Building Scenario Library (v2 - GPD Sampling)")
        logger.info("="*60)
        
        total_start = time.time()
        
        # Step 1: Prepare historical data
        self._step1_prepare_data()
        
        # Step 2: Build embedding space
        self._step2_build_embeddings()
        
        # Step 3: Generate scenarios (anchor-based with extrapolation)
        self._step3_generate_scenarios()
        
        # Step 4: GPD-based importance sampling
        self._step4_gpd_sampling()
        
        # Step 5: Save library
        self._step5_save_library()
        
        total_time = time.time() - total_start
        logger.info(f"\nPhase 1 complete in {total_time:.1f}s")
        logger.info(f"Final library size: {len(self.final_scenarios)} scenarios")
        
        return self.final_scenarios
    
    def _step1_prepare_data(self):
        """Load and prepare historical data."""
        logger.info("\n--- Step 1: Preparing Historical Data ---")
        start = time.time()
        
        self.historical_movements = prepare_historical_data(
            self.config.corpus_path,
            direction_filter="strengthening"
        )
        
        logger.info(f"Loaded {len(self.historical_movements)} historical movements")
        
        # Save historical data
        hist_data = [asdict(m) for m in self.historical_movements]
        with open(self.output_dir / "historical_movements.json", 'w') as f:
            json.dump(hist_data, f, indent=2, default=str)
        
        self.step_times['step1'] = time.time() - start
    
    def _step2_build_embeddings(self):
        """Build joint embedding space."""
        logger.info("\n--- Step 2: Building Embedding Space ---")
        start = time.time()
        
        self.embedding_space = JointEmbeddingSpace(self.config.embedding_config)
        self.embedding_space.fit(self.historical_movements)
        
        # Save embedding space
        embed_dir = self.output_dir / "embedding_space"
        self.embedding_space.save(str(embed_dir))
        
        logger.info(f"Embedding space built with {len(self.historical_movements)} points")
        
        self.step_times['step2'] = time.time() - start
    
    def _step3_generate_scenarios(self):
        """Generate scenarios using anchor-based approach with full audit trail."""
        logger.info("\n--- Step 3: Generating Anchor-Based Scenarios ---")
        logger.info(f"Anchors: {len(self.historical_movements)}")
        logger.info(f"Scenarios per anchor: {self.config.scenarios_per_anchor}")
        logger.info(f"Expected total: {len(self.historical_movements) * self.config.scenarios_per_anchor}")
        start = time.time()
        
        generator = AnchorBasedGenerator(
            self.historical_movements,
            self.embedding_space,
            self.config.generation_config,
            enable_audit=True  # Enable full audit trail
        )
        generator.scenarios_per_anchor = self.config.scenarios_per_anchor
        
        self.raw_scenarios = generator.generate_all(progress_interval=20)
        
        logger.info(f"Generated {len(self.raw_scenarios)} raw scenarios")
        logger.info(f"API calls: {generator.api_calls}, Tokens: {generator.total_tokens}")
        logger.info(f"Audit records captured: {len(generator.audit_records)}")
        
        # Save raw scenarios
        raw_data = [asdict(s) for s in self.raw_scenarios]
        with open(self.output_dir / "raw_scenarios.json", 'w') as f:
            json.dump({'scenarios': raw_data, 'count': len(raw_data)}, f, indent=2, default=str)
        
        # Save full audit trail (BEFORE any filtering/sampling)
        audit_path = self.output_dir / "generation_audit_trail.json"
        generator.save_audit_trail(str(audit_path))
        logger.info(f"Saved audit trail to {audit_path}")
        
        # Optionally run LLM assessments
        if hasattr(self.config, 'run_assessments') and self.config.run_assessments:
            mode = getattr(self.config, 'assessment_mode', 'sample')
            
            if mode == 'all':
                logger.info("\n--- Running LLM Assessments on ALL Scenarios ---")
                generator.assess_all_scenarios(sample_rate=1.0, max_assessments=999999)
                
            elif mode == 'tail':
                logger.info("\n--- Running LLM Assessments on TAIL Scenarios (≥50yr severity) ---")
                # Calculate 50yr severity threshold from historical data
                historical_severities = np.array([
                    m.severity_ratio for m in self.historical_movements 
                    if m.severity_ratio and m.severity_ratio > 0
                ])
                # 50yr = 98th percentile
                tail_threshold = np.percentile(historical_severities, 98)
                logger.info(f"Tail threshold (50yr): {tail_threshold:.1%}")
                generator.assess_tail_scenarios(threshold=tail_threshold)
                
            else:  # mode == 'sample'
                logger.info("\n--- Running LLM Assessments on Sample ---")
                generator.assess_all_scenarios(
                    sample_rate=getattr(self.config, 'assessment_sample_rate', 0.1),
                    max_assessments=getattr(self.config, 'max_assessments', 100)
                )
            
            # Re-save audit trail with assessments
            generator.save_audit_trail(str(audit_path))
        
        # Store generator reference for later access
        self.generator = generator
        
        self.step_times['step3'] = time.time() - start
    
    def _step4_gpd_sampling(self):
        """Apply GPD-based importance sampling with automatic threshold selection."""
        logger.info("\n--- Step 4: GPD-Based Importance Sampling ---")
        logger.info(f"Target library size: {self.config.target_library_size}")
        logger.info("GPD threshold: Automatically selected via multi-method consensus")
        start = time.time()
        
        # Get historical severities for GPD fitting
        historical_severities = np.array([
            m.severity_ratio for m in self.historical_movements 
            if m.severity_ratio and m.severity_ratio > 0
        ])
        
        logger.info(f"Historical severity range: {historical_severities.min():.1%} to {historical_severities.max():.1%}")
        
        # Apply GPD sampling (threshold automatically selected)
        # Returns: (matched_scenarios, spliced_distribution, stats)
        # Pass output_dir to save comprehensive GPD diagnostics
        self.final_scenarios, self.spliced_dist, self.gpd_stats = create_gpd_sampled_library(
            self.raw_scenarios,
            historical_severities,
            target_size=self.config.target_library_size,
            output_dir=self.output_dir,  # Save GPD diagnostics to output directory
            percentile_range=(self.config.gpd_percentile_min, self.config.gpd_percentile_max),
            severity_mode=self.config.severity_mode
        )
        
        # Analyze severity distribution
        raw_severities = np.array([s.severity_ratio for s in self.raw_scenarios])
        sampled_severities = np.array([s.severity_ratio for s in self.final_scenarios])
        
        self.dist_analysis = analyze_severity_distribution(
            historical_severities, raw_severities, sampled_severities, self.spliced_dist
        )
        
        # Project scenarios into embedding space (BATCHED for speed)
        logger.info(f"\nProjecting {len(self.final_scenarios)} scenarios into embedding space...")
        
        # Step 1: Batch embed all narratives at once (this is the slow part)
        logger.info("  Generating text embeddings (batched)...")
        texts = [s.narrative or "" for s in self.final_scenarios]
        text_embeddings = self.embedding_space.text_embedder.embed(texts)
        logger.info(f"  Text embeddings shape: {text_embeddings.shape}")
        
        # Step 2: Prepare inputs and project (fast - just matrix ops)
        logger.info("  Projecting to latent space...")
        from config import LOB_TO_INDEX
        
        projected_count = 0
        for i, s in enumerate(self.final_scenarios):
            try:
                # Build LOB vector
                lob_vector = [0.0] * len(LLOYDS_LOBS)
                if s.lob_breakdown:
                    for lob, weight in s.lob_breakdown.items():
                        if lob in LOB_TO_INDEX:
                            lob_vector[LOB_TO_INDEX[lob]] = weight
                
                # Use pre-computed text embedding
                inp = self.embedding_space.projection_net.prepare_input(
                    text_embeddings[i],
                    s.severity_ratio,
                    s.complexity_score,
                    lob_vector
                )
                coords = self.embedding_space.projection_net.project(inp.reshape(1, -1))[0]
                s.latent_coords = coords.tolist()
                projected_count += 1
                
            except Exception as e:
                logger.debug(f"Failed to project scenario {s.id}: {e}")
            
            # Progress every 500
            if (i + 1) % 500 == 0:
                logger.info(f"  Projected {i + 1}/{len(self.final_scenarios)} scenarios")
        
        logger.info(f"  Successfully projected {projected_count}/{len(self.final_scenarios)} scenarios")
        
        # Save GPD/spliced distribution parameters
        # Get GPD fit stats from the stats dict
        gpd_info = self.gpd_stats.get('gpd', {})
        
        gpd_data = {
            'threshold': float(self.spliced_dist.threshold),
            'threshold_percentile': float(self.spliced_dist.threshold_percentile),
            'shape': float(self.spliced_dist.shape),
            'scale': float(self.spliced_dist.scale),
            'n_exceedances': int(self.spliced_dist.n_exceedances),
            'n_total': int(self.spliced_dist.n_total),
            'n_body': len(self.spliced_dist.body_values),
            'p_below_threshold': float(self.spliced_dist.p_below_threshold),
            'ks_pvalue': gpd_info.get('ks_pvalue'),
            'ad_statistic': gpd_info.get('ad_statistic'),
            'return_period_severities': {
                str(rp): float(self.spliced_dist.severity_for_return_period(rp))
                for rp in [10, 25, 50, 100, 200, 250]
            }
        }
        with open(self.output_dir / "gpd_fit.json", 'w') as f:
            json.dump(gpd_data, f, indent=2)
        
        # Save sampling stats
        with open(self.output_dir / "gpd_sampling_stats.json", 'w') as f:
            json.dump(to_python_types(self.gpd_stats), f, indent=2)
        
        with open(self.output_dir / "severity_distribution.json", 'w') as f:
            json.dump(to_python_types(self.dist_analysis), f, indent=2)
        
        self.step_times['step4'] = time.time() - start
    
    def _step5_save_library(self):
        """Save final scenario library."""
        logger.info("\n--- Step 5: Saving Library ---")
        start = time.time()
        
        # Safety check for spliced_dist
        if self.spliced_dist is None:
            raise RuntimeError(
                "GPD sampling not completed - self.spliced_dist is None. "
                "This may indicate an error in Step 4 or an outdated version of the code. "
                "Please ensure you have the latest version of pipeline_v2.py"
            )
        
        # Convert to serializable format
        library_data = {
            'version': '2.0',
            'n_scenarios': len(self.final_scenarios),
            'n_anchors': len(self.historical_movements),
            'gpd_params': {
                'threshold': float(self.spliced_dist.threshold),
                'threshold_percentile': float(self.spliced_dist.threshold_percentile),
                'shape': float(self.spliced_dist.shape),
                'scale': float(self.spliced_dist.scale)
            },
            'scenarios': [to_python_types(asdict(s)) for s in self.final_scenarios]
        }
        
        with open(self.output_dir / "scenario_library.json", 'w') as f:
            json.dump(library_data, f, indent=2)
        
        logger.info(f"Saved {len(self.final_scenarios)} scenarios to scenario_library.json")
        
        self.step_times['step5'] = time.time() - start


# =============================================================================
# Phase 2: Query
# =============================================================================

class ScenarioQuery:
    """Query scenarios for a portfolio."""
    
    def __init__(self, library_dir: str):
        self.library_dir = Path(library_dir)
        self.scenarios = []
        self.embedding_space = None
        self.quantile_bins = []
        
        self._load()
    
    def _load(self):
        """Load library and embedding space."""
        # Load scenarios
        library_path = self.library_dir / "scenario_library.json"
        with open(library_path, 'r') as f:
            data = json.load(f)
        
        self.scenarios = [SyntheticScenario(**s) for s in data['scenarios']]
        self.quantile_bins = data.get('quantile_bins', [])
        
        logger.info(f"Loaded {len(self.scenarios)} scenarios")
        
        # Load embedding space
        embed_dir = self.library_dir / "embedding_space"
        if embed_dir.exists():
            self.embedding_space = JointEmbeddingSpace()
            self.embedding_space.load(str(embed_dir))
            logger.info("Loaded embedding space")
    
    def query(self,
              lob_weights: Dict[str, float],
              total_reserves: float,
              return_period: int = 100,
              n_scenarios: int = 5,
              n_neighbours: int = 500) -> List[StressScenario]:
        """Query scenarios for a portfolio."""
        portfolio = create_portfolio(lob_weights, total_reserves)
        
        engine = NeighbourBasedQuery(
            self.scenarios,
            self.embedding_space
        )
        
        return engine.query(portfolio, return_period, n_scenarios, n_neighbours)


# =============================================================================
# CLI
# =============================================================================

def main():
    import argparse
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    parser = argparse.ArgumentParser(description="Stress Test Pipeline v2")
    subparsers = parser.add_subparsers(dest='command', help='Commands')
    
    # Build command
    build_parser = subparsers.add_parser('build', help='Build scenario library')
    build_parser.add_argument('--corpus', '-c', default='results/combined/unified_corpus.json')
    build_parser.add_argument('--output', '-o', default='results/stress_test_v2')
    build_parser.add_argument('--scenarios-per-anchor', type=int, default=10,
                              help='Number of scenarios to generate per historical anchor')
    build_parser.add_argument('--extrapolation-factor', type=float, default=2.5,
                              help='Allow severity up to this multiple of anchor (default 2.5x)')
    build_parser.add_argument('--target-size', type=int, default=2000,
                              help='Target library size after GPD sampling')
    build_parser.add_argument('--gpd-percentile-min', type=float, default=80,
                              help='Min threshold percentile to search (default: 80)')
    build_parser.add_argument('--gpd-percentile-max', type=float, default=99,
                              help='Max threshold percentile to search (default: 99)')
    build_parser.add_argument('--severity-mode', choices=['constrained', 'unconstrained', 'unconstrained_no_max', 'empirical', 'auto'],
                              default='auto',
                              help='Severity sampling mode: constrained (xi<0.5), unconstrained, unconstrained_no_max, empirical, auto (recommended)')
    build_parser.add_argument('--run-assessments', action='store_true',
                              help='Run LLM assessments on generated scenarios')
    build_parser.add_argument('--assessment-mode', choices=['sample', 'all', 'tail'], default='sample',
                              help='Assessment mode: sample (default), all, or tail (≥50yr only)')
    build_parser.add_argument('--assessment-sample-rate', type=float, default=0.1,
                              help='Fraction of scenarios to assess when mode=sample (default 0.1)')
    build_parser.add_argument('--max-assessments', type=int, default=100,
                              help='Maximum assessments when mode=sample (default 100)')
    build_parser.add_argument('--model', default='gpt-4o-mini',
                              help='LLM model for generation (default: gpt-4o-mini)')
    
    # Query command
    query_parser = subparsers.add_parser('query', help='Query scenarios')
    query_parser.add_argument('--library', '-l', required=True)
    query_parser.add_argument('--reserves', '-r', type=float, required=True)
    query_parser.add_argument('--return-period', '-p', type=int, default=100)
    query_parser.add_argument('--n-scenarios', '-n', type=int, default=5)
    query_parser.add_argument('--n-neighbours', type=int, default=500)
    query_parser.add_argument('--lob', action='append', nargs=2, metavar=('LOB', 'WEIGHT'))
    query_parser.add_argument('--output', '-o', help='Output JSON file path')
    query_parser.add_argument('--report', help='Generate HTML report to this path')
    query_parser.add_argument('--assess-results', action='store_true',
                              help='Run LLM assessment on returned scenarios (just-in-time)')
    
    # Summary command
    summary_parser = subparsers.add_parser('summary', help='Show library summary')
    summary_parser.add_argument('--library', '-l', required=True)
    
    # Audit command
    audit_parser = subparsers.add_parser('audit', help='Analyze generation audit trail')
    audit_parser.add_argument('--library', '-l', required=True,
                              help='Path to library directory containing generation_audit_trail.json')
    audit_parser.add_argument('--scenario', '-s', help='Show details for specific scenario ID')
    audit_parser.add_argument('--anchor', '-a', help='Show all scenarios from specific anchor ID')
    audit_parser.add_argument('--low-probability', type=float, default=0.3,
                              help='Show scenarios with distributional probability below this threshold')
    audit_parser.add_argument('--extrapolated', action='store_true',
                              help='Show only extrapolated scenarios')
    audit_parser.add_argument('--export', '-e', help='Export filtered audit records to file')
    
    # GPD diagnostics command - fit GPD and save diagnostics without generating scenarios
    gpd_parser = subparsers.add_parser('gpd', help='Fit GPD and generate diagnostics (no scenario generation)')
    gpd_parser.add_argument('--corpus', '-c', default='results/combined/unified_corpus.json',
                            help='Path to historical corpus JSON')
    gpd_parser.add_argument('--output', '-o', default='results/gpd_diagnostics',
                            help='Output directory for diagnostics')
    gpd_parser.add_argument('--percentile-min', type=float, default=80,
                            help='Minimum threshold percentile to test (default: 80)')
    gpd_parser.add_argument('--percentile-max', type=float, default=99,
                            help='Maximum threshold percentile to test (default: 99)')
    gpd_parser.add_argument('--severity-mode', choices=['constrained', 'unconstrained', 'unconstrained_no_max', 'empirical', 'auto'],
                            default='auto',
                            help='Severity sampling mode: constrained (xi<0.5), unconstrained, unconstrained_no_max (max removed), empirical (data percentiles), auto (recommended)')
    
    # Library diagnostics command
    diag_parser = subparsers.add_parser('diagnostics', help='Run library diagnostics (severity, semantic, coverage)')
    diag_parser.add_argument('--library', '-l', required=True,
                            help='Path to scenario library directory or JSON')
    diag_parser.add_argument('--corpus', '-c', 
                            help='Path to historical corpus (auto-detected if not specified)')
    diag_parser.add_argument('--output', '-o',
                            help='Output directory for diagnostics (default: library/diagnostics)')
    diag_parser.add_argument('--bootstrap', '-b', type=int, default=500,
                            help='Bootstrap iterations for MMD p-value (default: 500)')
    diag_parser.add_argument('--report', '-r', action='store_true',
                            help='Generate HTML diagnostics report')
    
    args = parser.parse_args()
    
    if args.command == 'build':
        config = PipelineConfigV2(
            corpus_path=args.corpus,
            output_dir=args.output,
            scenarios_per_anchor=args.scenarios_per_anchor,
            extrapolation_factor=args.extrapolation_factor,
            llm_model=args.model,
            target_library_size=args.target_size,
            gpd_percentile_min=args.gpd_percentile_min,
            gpd_percentile_max=args.gpd_percentile_max,
            severity_mode=args.severity_mode,
            run_assessments=args.run_assessments,
            assessment_mode=args.assessment_mode,
            assessment_sample_rate=args.assessment_sample_rate,
            max_assessments=args.max_assessments
        )
        builder = LibraryBuilder(config)
        builder.run()
    
    elif args.command == 'query':
        # Parse LOB weights
        lob_weights = {}
        if args.lob:
            for lob, weight in args.lob:
                lob_weights[lob] = float(weight)
        else:
            lob_weights = {'Property': 0.4, 'Casualty': 0.3, 'Marine': 0.15, 'Professional Lines': 0.15}
        
        # Handle library path
        library_path = Path(args.library)
        if library_path.is_file():
            library_dir = library_path.parent
        else:
            library_dir = library_path
        
        # Check library exists
        scenario_file = library_dir / "scenario_library.json"
        if not scenario_file.exists():
            print(f"ERROR: scenario_library.json not found at {scenario_file}")
            print(f"Library path provided: {args.library}")
            print("Please build a library first using: python pipeline_v2.py build ...")
            sys.exit(1)
        
        try:
            query_engine = ScenarioQuery(str(library_dir))
        except Exception as e:
            print(f"ERROR: Failed to load library: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)
        
        try:
            scenarios = query_engine.query(
                lob_weights, args.reserves, args.return_period,
                args.n_scenarios, args.n_neighbours
            )
        except Exception as e:
            print(f"ERROR: Query failed: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)
        
        # JIT assessment if requested
        if hasattr(args, 'assess_results') and args.assess_results:
            print("\n--- Running JIT Assessments on Returned Scenarios ---")
            try:
                from openai import OpenAI
                client = OpenAI()
                
                for i, s in enumerate(scenarios):
                    print(f"Assessing scenario {i+1}/{len(scenarios)}...")
                    
                    # Build assessment prompt
                    prompt = f"""Assess whether this stress test scenario is plausible and well-calibrated.

SCENARIO:
- Name: {s.name}
- Severity: {s.severity_ratio:.1%} adverse reserve development
- Return Period: {args.return_period}-year event
- Cause: {getattr(s, 'cause_category', 'Unknown')}
- LOB Impacts: {s.lob_impacts}
- Explanation: {s.explanation[:500] if s.explanation else 'N/A'}...

Provide your assessment as JSON:
{{
  "plausibility_score": 0.0-1.0,
  "confidence": "high/medium/low",
  "reasoning": "2-3 sentences",
  "concerns": ["list of any concerns"],
  "strengths": ["list of strengths"]
}}"""
                    
                    try:
                        response = client.chat.completions.create(
                            model="gpt-4o",
                            messages=[
                                {"role": "system", "content": "You are an expert actuary assessing stress test scenarios."},
                                {"role": "user", "content": prompt}
                            ],
                            temperature=0.3,
                            max_tokens=500
                        )
                        assessment_text = response.choices[0].message.content
                        
                        # Try to parse JSON
                        import re
                        json_match = re.search(r'\{[^{}]*\}', assessment_text, re.DOTALL)
                        if json_match:
                            assessment = json.loads(json_match.group())
                            s.jit_assessment = assessment
                        else:
                            s.jit_assessment = {"raw": assessment_text}
                            
                    except Exception as e:
                        print(f"  Warning: Assessment failed: {e}")
                        s.jit_assessment = {"error": str(e)}
                        
            except ImportError:
                print("Warning: OpenAI not available for JIT assessment")
        
        # Print results
        print(f"\n{'='*60}")
        print(f"{args.return_period}-Year Stress Scenarios for £{args.reserves:.0f}m Portfolio")
        print(f"Portfolio: {', '.join(f'{l}: {w:.0%}' for l, w in lob_weights.items())}")
        print(f"{'='*60}")
        
        for i, s in enumerate(scenarios, 1):
            print(f"\n{'='*60}")
            print(f"SCENARIO {i}: {s.name}")
            print(f"{'='*60}")
            print(f"Return Period: {s.return_period}-year | Total Severity: {s.severity_ratio:.1%}")
            print(f"Portfolio Impact: {s.portfolio_impact:.1%}")
            
            print(f"\n[Narrative]")
            print(f"  {s.narrative}")

            if s.causal_chain:
                print(f"\n[Key Events]")
                print(f"  {s.causal_chain}")

            print(f"\n[LOB Impacts]")
            for lob, impact in sorted(s.lob_impacts.items(), key=lambda x: -x[1]):
                if impact > 0:
                    bar = "#" * int(impact * 20)  # Simple bar chart
                    print(f"  {lob:25s} {impact:>6.1%} {bar}")

            print(f"\n[Analysis]")
            print(f"  {s.explanation}")

            # Print JIT assessment if available
            if hasattr(s, 'jit_assessment') and s.jit_assessment:
                print(f"\n[JIT Assessment]")
                assessment = s.jit_assessment
                if 'plausibility_score' in assessment:
                    print(f"  Plausibility: {assessment['plausibility_score']:.0%}")
                    print(f"  Confidence: {assessment.get('confidence', 'N/A')}")
                    print(f"  Reasoning: {assessment.get('reasoning', 'N/A')}")
                elif 'error' in assessment:
                    print(f"  Error: {assessment['error']}")
                else:
                    print(f"  {assessment.get('raw', assessment)}")
        
        if args.output:
            # Convert to serializable format
            output_data = []
            for s in scenarios:
                d = asdict(s)
                if hasattr(s, 'jit_assessment'):
                    d['jit_assessment'] = s.jit_assessment
                output_data.append(d)
            with open(args.output, 'w') as f:
                json.dump(output_data, f, indent=2, default=str)
            print(f"\nSaved JSON to {args.output}")
        
        # Generate HTML report
        if args.report:
            print(f"\n{'='*60}")
            print("Generating HTML Report...")
            print(f"{'='*60}")
            
            try:
                from report_generator import generate_query_report
                from openai import OpenAI
                
                # Create portfolio dict
                portfolio = PortfolioSpec(
                    lob_weights=lob_weights,
                    total_reserves_gbp_m=args.reserves
                )
                
                # Initialize OpenAI client for commentary
                try:
                    client = OpenAI()
                except:
                    client = None
                    print("Warning: OpenAI client not available, skipping derivation commentary")
                
                report_path = generate_query_report(
                    scenarios=scenarios,
                    portfolio=portfolio,
                    return_period=args.return_period,
                    library_dir=library_dir,
                    output_path=Path(args.report),
                    client=client
                )
                
                print(f"[OK] HTML Report generated: {report_path}")
                print(f"\nOpen in browser: file://{report_path.absolute()}")
                
            except Exception as e:
                print(f"Error generating report: {e}")
                import traceback
                traceback.print_exc()
    
    elif args.command == 'summary':
        library_path = Path(args.library)
        if library_path.is_file():
            with open(library_path, 'r') as f:
                data = json.load(f)
            library_dir = library_path.parent
        else:
            with open(library_path / "scenario_library.json", 'r') as f:
                data = json.load(f)
            library_dir = library_path
        
        scenarios = data.get('scenarios', data)
        
        print(f"\n{'='*60}")
        print("SCENARIO LIBRARY SUMMARY (v2 - GPD Sampled)")
        print(f"{'='*60}")
        print(f"\nVersion: {data.get('version', '1.0')}")
        print(f"Total scenarios: {len(scenarios)}")
        print(f"Anchors used: {data.get('n_anchors', 'N/A')}")
        
        severities = [s.get('severity_ratio', 0) for s in scenarios]
        print(f"\nSeverity Distribution:")
        print(f"  Min:    {min(severities):.1%}")
        print(f"  25th:   {np.percentile(severities, 25):.1%}")
        print(f"  Median: {np.percentile(severities, 50):.1%}")
        print(f"  75th:   {np.percentile(severities, 75):.1%}")
        print(f"  95th:   {np.percentile(severities, 95):.1%}")
        print(f"  99th:   {np.percentile(severities, 99):.1%}")
        print(f"  Max:    {max(severities):.1%}")
        
        # GPD parameters
        if 'gpd_params' in data:
            gpd = data['gpd_params']
            print(f"\nGPD Parameters:")
            print(f"  Threshold (u): {gpd['threshold']:.1%}")
            print(f"  Shape (xi):     {gpd['shape']:.3f}")
            print(f"  Scale (sigma):     {gpd['scale']:.3f}")
        
        # Load GPD fit for return periods
        gpd_file = library_dir / "gpd_fit.json"
        if gpd_file.exists():
            with open(gpd_file, 'r') as f:
                gpd_fit = json.load(f)
            print(f"\nReturn Period -> Severity:")
            for rp, sev in gpd_fit.get('return_period_severities', {}).items():
                print(f"  {rp:>3}-year: {sev:.1%}")
        
        # Cause distribution
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
    
    elif args.command == 'audit':
        # Analyze audit trail
        library_path = Path(args.library)
        if library_path.is_file():
            library_dir = library_path.parent
        else:
            library_dir = library_path
        
        audit_file = library_dir / "generation_audit_trail.json"
        if not audit_file.exists():
            print(f"Audit trail not found: {audit_file}")
            print("Run 'build' command first to generate audit trail.")
            sys.exit(1)
        
        with open(audit_file, 'r') as f:
            audit_data = json.load(f)
        
        records = audit_data.get('records', [])
        metadata = audit_data.get('metadata', {})
        
        print(f"\n{'='*60}")
        print("GENERATION AUDIT TRAIL ANALYSIS")
        print(f"{'='*60}")
        print(f"\nTotal audit records: {len(records)}")
        print(f"Total anchors: {metadata.get('total_anchors', 'N/A')}")
        print(f"Edge case threshold: {metadata.get('edge_case_threshold', 'N/A')}")
        print(f"Max historical severity: {metadata.get('max_historical_severity', 'N/A')}")
        
        # Show few-shot selection stats if available
        fs_stats = metadata.get('few_shot_selection', {})
        if fs_stats:
            print(f"\nFew-shot selection strategy:")
            print(f"  Similarity examples: {fs_stats.get('similarity_examples', 0):,}")
            print(f"  Diversity examples: {fs_stats.get('diversity_examples', 0):,}")
        
        # Filter based on args
        filtered = records
        
        if args.scenario:
            filtered = [r for r in filtered if r['scenario_id'] == args.scenario]
        
        if args.anchor:
            filtered = [r for r in filtered if r['anchor_id'] == args.anchor]
        
        if args.extrapolated:
            filtered = [r for r in filtered if r.get('generation_params', {}).get('extrapolation_requested', False)]
        
        if args.low_probability:
            filtered = [r for r in filtered 
                       if r.get('assessment', {}).get('distributional_probability', 1.0) < args.low_probability]
        
        print(f"\nFiltered records: {len(filtered)}")
        
        if len(filtered) == 0:
            print("No records match the filter criteria.")
        elif args.scenario or len(filtered) <= 5:
            # Show detailed view for single scenario or small set
            for r in filtered:
                print(f"\n{'-'*60}")
                print(f"SCENARIO: {r['scenario_id']}")
                print(f"{'-'*60}")
                
                print(f"\n[ANCHOR]")
                anchor = r.get('anchor', {})
                syndicate = anchor.get('syndicate', 'Unknown')
                year = anchor.get('year', 'N/A')
                print(f"  ID: {r['anchor_id']}")
                print(f"  Source: {syndicate} ({year})")
                print(f"  LOB: {anchor.get('lob', 'N/A')}")
                sev = anchor.get('severity')
                print(f"  Severity: {sev:.1%}" if sev else "  Severity: N/A")
                print(f"  Causes: {', '.join(anchor.get('causes', [])[:3])}")
                print(f"  Narrative: {anchor.get('narrative', 'N/A')[:200]}...")
                
                print(f"\n[FEW-SHOT EXAMPLES]")
                for i, ex in enumerate(r.get('few_shot_examples', [])[:5], 1):
                    ex_syndicate = ex.get('syndicate', 'Unknown')
                    ex_year = ex.get('year', 'N/A')
                    selection_reason = ex.get('selection_reason', 'unknown').upper()
                    sev_ratio = ex.get('severity_ratio')
                    sev_str = f"{sev_ratio:.1%}" if sev_ratio else "N/A"
                    dist = ex.get('distance_to_anchor', 0)
                    
                    print(f"  {i}. [{selection_reason}] {ex.get('id', 'N/A')}")
                    print(f"     Source: {ex_syndicate} ({ex_year})")
                    print(f"     LOB: {ex.get('line_of_business', 'N/A')}, Severity: {sev_str}, Distance: {dist:.3f}")
                    print(f"     Causes: {', '.join(ex.get('primary_causes', [])[:2])}")
                
                print(f"\n[GENERATION PARAMS]")
                params = r.get('generation_params', {})
                print(f"  Severity range: {params.get('severity_range', 'N/A')}")
                print(f"  Extrapolation requested: {params.get('extrapolation_requested', False)}")
                print(f"  Random seed: {params.get('random_seed', 'N/A')}")
                print(f"  Generation time: {params.get('generation_time_ms', 'N/A')}ms")
                
                print(f"\n[GENERATED OUTPUT]")
                output = r.get('generated_output', {}).get('parsed', {})
                gen_sev = output.get('severity')
                print(f"  Severity: {gen_sev:.1%}" if gen_sev else "  Severity: N/A")
                print(f"  Cause: {output.get('cause_category', 'N/A')}")
                print(f"  LOBs: {output.get('lob_breakdown', {})}")
                print(f"  Narrative: {output.get('narrative', 'N/A')[:200]}...")
                
                if 'assessment' in r:
                    print(f"\n[LLM ASSESSMENT]")
                    assess = r['assessment']
                    print(f"  Distributional probability: {assess.get('distributional_probability', 'N/A')}")
                    print(f"  Confidence: {assess.get('confidence', 'N/A')}")
                    print(f"  Extrapolation type: {assess.get('extrapolation_type', 'N/A')}")
                    print(f"  Reasoning: {assess.get('reasoning', 'N/A')[:300]}...")
                    print(f"  Key similarities: {', '.join(assess.get('key_similarities', [])[:3])}")
                    print(f"  Key differences: {', '.join(assess.get('key_differences', [])[:3])}")
                    print(f"  Risk factors: {', '.join(assess.get('risk_factors', [])[:3])}")
        else:
            # Show summary for larger sets
            print(f"\nShowing summary for {len(filtered)} records:")
            
            # Severity distribution
            severities = [r.get('generated_output', {}).get('parsed', {}).get('severity', 0) for r in filtered]
            print(f"\nGenerated severity distribution:")
            print(f"  Min: {min(severities):.1%}, Median: {np.median(severities):.1%}, Max: {max(severities):.1%}")
            
            # Few-shot selection breakdown
            similarity_count = sum(
                1 for r in filtered 
                for ex in r.get('few_shot_examples', []) 
                if ex.get('selection_reason') == 'similarity'
            )
            diversity_count = sum(
                1 for r in filtered 
                for ex in r.get('few_shot_examples', []) 
                if ex.get('selection_reason') == 'diversity'
            )
            if similarity_count + diversity_count > 0:
                print(f"\nFew-shot selection breakdown (this filter):")
                print(f"  Similarity: {similarity_count}, Diversity: {diversity_count}")
            
            # Extrapolation stats
            n_extrap = sum(1 for r in filtered if r.get('generation_params', {}).get('extrapolation_requested', False))
            print(f"\nExtrapolation requests: {n_extrap} ({100*n_extrap/len(filtered):.1f}%)")
            
            # Assessment stats if available
            assessed = [r for r in filtered if 'assessment' in r]
            if assessed:
                probs = [r['assessment'].get('distributional_probability', 0) for r in assessed]
                print(f"\nAssessment stats ({len(assessed)} assessed):")
                print(f"  Distributional probability: min={min(probs):.2f}, median={np.median(probs):.2f}, max={max(probs):.2f}")
                
                extrap_types = {}
                for r in assessed:
                    t = r['assessment'].get('extrapolation_type', 'unknown')
                    extrap_types[t] = extrap_types.get(t, 0) + 1
                print(f"  Extrapolation types: {extrap_types}")
            
            # List first few with enhanced info
            print(f"\nFirst 10 scenarios:")
            for r in filtered[:10]:
                anchor = r.get('anchor', {})
                syndicate = anchor.get('syndicate', 'Unknown')
                year = anchor.get('year', '')
                output = r.get('generated_output', {}).get('parsed', {})
                assess = r.get('assessment', {})
                prob = assess.get('distributional_probability', 'N/A')
                prob_str = f"{prob:.2f}" if isinstance(prob, float) else prob
                sev = output.get('severity', 0)
                print(f"  {r['scenario_id']}: sev={sev:.1%}, "
                      f"anchor={syndicate[:15]}({year}), prob={prob_str}")
        
        # Export if requested
        if args.export:
            with open(args.export, 'w') as f:
                json.dump({'metadata': metadata, 'records': filtered}, f, indent=2, default=str)
            print(f"\nExported {len(filtered)} records to {args.export}")
    
    elif args.command == 'gpd':
        # Fit GPD and generate diagnostics without scenario generation
        from gpd_diagnostics import save_gpd_diagnostics
        from data_preparation import prepare_historical_data
        
        print("="*60)
        print("GPD DIAGNOSTICS")
        print("="*60)
        
        # Load corpus
        print(f"\nLoading corpus from {args.corpus}...")
        corpus_path = Path(args.corpus)
        if not corpus_path.exists():
            print(f"Error: Corpus file not found: {args.corpus}")
            sys.exit(1)
        
        movements = prepare_historical_data(str(corpus_path))
        print(f"Loaded {len(movements)} historical movements")
        
        # Extract severities
        severities = np.array([
            m.severity_ratio for m in movements 
            if m.severity_ratio and m.severity_ratio > 0
        ])
        print(f"Valid severities: {len(severities)}")
        print(f"Range: {severities.min():.1%} to {severities.max():.1%}")
        
        # Create output directory
        output_dir = Path(args.output)
        output_dir.mkdir(parents=True, exist_ok=True)
        print(f"\nOutput directory: {output_dir}")
        
        # Run GPD diagnostics
        print(f"\nFitting GPD with threshold search range: {args.percentile_min:.0f}th to {args.percentile_max:.0f}th percentile")
        
        diagnostics, saved_files = save_gpd_diagnostics(
            severities,
            output_dir,
            prefix="gpd",
            percentile_range=(args.percentile_min, args.percentile_max)
        )
        
        # Print summary with all 4 modes
        print("\n" + "="*80)
        print("GPD FIT SUMMARY - 4 SEVERITY MODES")
        print("="*80)
        print(f"  Data: n={diagnostics.n_total}, range=[{diagnostics.data_min:.1%}, {diagnostics.data_max:.1%}]")
        
        # Mode 1: Constrained
        print(f"\n  1. CONSTRAINED FIT (xi < 0.5):")
        if diagnostics.constrained:
            print(f"     Threshold: {diagnostics.constrained.threshold:.1%} ({diagnostics.constrained.threshold_percentile:.0f}th percentile)")
            print(f"     Shape (xi): {diagnostics.constrained.shape:.4f}, Scale (sigma): {diagnostics.constrained.scale:.4f}")
            print(f"     KS p-value: {diagnostics.constrained.ks_pvalue:.4f}, AD: {diagnostics.constrained.ad_statistic:.2f}")
        else:
            print("     [Failed to fit]")
        
        # Mode 2: Unconstrained
        print(f"\n  2. UNCONSTRAINED FIT:")
        if diagnostics.unconstrained:
            print(f"     Threshold: {diagnostics.unconstrained.threshold:.1%} ({diagnostics.unconstrained.threshold_percentile:.0f}th percentile)")
            print(f"     Shape (xi): {diagnostics.unconstrained.shape:.4f}, Scale (sigma): {diagnostics.unconstrained.scale:.4f}")
            print(f"     KS p-value: {diagnostics.unconstrained.ks_pvalue:.4f}, AD: {diagnostics.unconstrained.ad_statistic:.2f}")
        else:
            print("     [Failed to fit]")
        
        # Mode 3: Unconstrained no max
        print(f"\n  3. UNCONSTRAINED (max removed):")
        if diagnostics.unconstrained_no_max:
            print(f"     Threshold: {diagnostics.unconstrained_no_max.threshold:.1%} ({diagnostics.unconstrained_no_max.threshold_percentile:.0f}th percentile)")
            print(f"     Shape (xi): {diagnostics.unconstrained_no_max.shape:.4f}, Scale (sigma): {diagnostics.unconstrained_no_max.scale:.4f}")
            print(f"     KS p-value: {diagnostics.unconstrained_no_max.ks_pvalue:.4f}, AD: {diagnostics.unconstrained_no_max.ad_statistic:.2f}")
            print(f"     Max value removed: {diagnostics.max_value_removed:.1%}")
        else:
            print("     [Failed to fit]")
        
        # Mode 4: Empirical
        print(f"\n  4. EMPIRICAL (from data percentiles):")
        print(f"     Uses actual data percentiles - no extrapolation beyond observed data")
        
        # Return period comparison table
        print(f"\n  RETURN PERIOD COMPARISON:")
        print(f"    {'RP':>6}  {'Empirical':>10}  {'Constrained':>12}  {'Unconstrained':>14}  {'Unc(no max)':>12}")
        print(f"    {'-'*6}  {'-'*10}  {'-'*12}  {'-'*14}  {'-'*12}")
        
        for rp in ['10', '25', '50', '100', '200', '500']:
            emp = diagnostics.empirical_return_periods.get(rp) if diagnostics.empirical_return_periods else None
            con = diagnostics.constrained.return_periods.get(rp) if diagnostics.constrained else None
            unc = diagnostics.unconstrained.return_periods.get(rp) if diagnostics.unconstrained else None
            unm = diagnostics.unconstrained_no_max.return_periods.get(rp) if diagnostics.unconstrained_no_max else None
            
            emp_str = f"{emp*100:>9.1f}%" if emp else "     -    "
            con_str = f"{con*100:>11.1f}%" if con else "       -     "
            unc_str = f"{unc*100:>13.1f}%" if unc else "        -      "
            unm_str = f"{unm*100:>11.1f}%" if unm else "      -      "
            
            print(f"    {rp:>3}-yr  {emp_str}  {con_str}  {unc_str}  {unm_str}")
        
        # Recommendation
        print(f"\n  " + "-"*76)
        print(f"  RECOMMENDATION: {diagnostics.recommended_mode.upper()}")
        print(f"  {diagnostics.recommendation_reason}")
        print(f"  " + "-"*76)
        
        # Selected mode
        if args.severity_mode == 'auto':
            selected_mode = diagnostics.recommended_mode
            print(f"\n  Selected mode (auto): {selected_mode}")
        else:
            selected_mode = args.severity_mode
            print(f"\n  Selected mode (user override): {selected_mode}")
        
        if diagnostics.warnings:
            print(f"\n  WARNINGS:")
            for w in diagnostics.warnings:
                print(f"    - {w}")
        
        print(f"\n  Saved {len(saved_files)} files to {output_dir}")
        
        print("\n" + "="*80)
        print(f"To generate scenarios with selected mode, use:")
        print(f"  python pipeline_v2.py build --severity-mode {selected_mode} ...")
        print("="*80)
    
    elif args.command == 'diagnostics':
        # Run library diagnostics
        print("\n" + "="*80)
        print("LIBRARY DIAGNOSTICS")
        print("="*80)
        
        from library_diagnostics import LibraryDiagnostics
        
        library_path = Path(args.library)
        
        # Determine output directory
        if args.output:
            output_dir = Path(args.output)
        else:
            if library_path.is_file():
                output_dir = library_path.parent / "diagnostics"
            else:
                output_dir = library_path / "diagnostics"
        
        output_dir.mkdir(parents=True, exist_ok=True)
        
        print(f"\nLibrary: {library_path}")
        print(f"Output: {output_dir}")
        print(f"Bootstrap iterations: {args.bootstrap}")
        
        # Run diagnostics
        diag = LibraryDiagnostics(
            library_path=str(library_path),
            corpus_path=args.corpus,
            n_bootstrap=args.bootstrap
        )
        
        results = diag.run_all_diagnostics()
        
        # Save results
        results_path = output_dir / "diagnostics_results.json"
        diag.save_results(results, str(results_path))
        
        # Print summary
        print("\n" + "="*60)
        print("DIAGNOSTICS SUMMARY")
        print("="*60)
        print(f"\nOverall Score: {results.overall_score:.1f}/100 (Grade {results.overall_grade})")
        print(f"\nComponent Scores:")
        print(f"  Severity Distribution: {results.severity_score:.1f}/100")
        print(f"  Semantic Coverage:     {results.semantic_score:.1f}/100")
        print(f"  Cause Distribution:    {results.cause_score:.1f}/100")
        print(f"  LOB Coverage:          {results.lob_score:.1f}/100")
        print(f"  Coherence:             {results.coherence_score:.1f}/100")
        
        # Print detailed results
        if results.severity:
            sev = results.severity
            print(f"\n[SEVERITY TESTS]")
            print(f"  KS Test: stat={sev.ks_statistic:.4f}, p={sev.ks_pvalue:.4f} {'PASS' if sev.ks_pass else 'FAIL'}")
            print(f"  Bootstrap MMD: stat={sev.mmd_statistic:.4f}, p={sev.mmd_pvalue:.4f} {'PASS' if sev.mmd_pass else 'FAIL'}")
            print(f"  JS Divergence: {sev.js_divergence:.4f} {'PASS' if sev.js_pass else 'FAIL'}")

        if results.semantic:
            sem = results.semantic
            print(f"\n[SEMANTIC TESTS]")
            print(f"  Mean Cosine Sim: {sem.mean_cosine_similarity:.4f} {'PASS' if sem.cosine_pass else 'FAIL'}")
            print(f"  Bootstrap MMD: stat={sem.mmd_statistic:.4f}, p={sem.mmd_pvalue:.4f} {'PASS' if sem.mmd_pass else 'FAIL'}")
            print(f"  Cluster Coverage: {sem.cluster_coverage:.1%} {'PASS' if sem.cluster_pass else 'FAIL'}")
            print(f"  Outlier Rate: {sem.outlier_rate:.1%} {'PASS' if sem.outlier_pass else 'FAIL'}")
            print(f"  Diversity Ratio: {sem.diversity_ratio:.3f} {'PASS' if sem.diversity_pass else 'FAIL'}")

        print(f"\nRecommendations:")
        for rec in results.recommendations:
            print(f"  - {rec}")
        
        print(f"\nResults saved to: {results_path}")
        
        # Generate HTML report if requested
        if args.report:
            print(f"\n{'='*60}")
            print("Generating HTML Report...")
            print(f"{'='*60}")
            
            try:
                from diagnostic_report import generate_full_diagnostics_report
                
                report_path = generate_full_diagnostics_report(
                    library_path=str(library_path),
                    corpus_path=args.corpus,
                    output_dir=str(output_dir),
                    n_bootstrap=100  # Fewer for report (already computed)
                )
                
                print(f"\n[OK] HTML Report generated: {report_path}")
                print(f"\nOpen in browser: file://{Path(report_path).absolute()}")
                
            except Exception as e:
                print(f"Error generating report: {e}")
                import traceback
                traceback.print_exc()
    
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
