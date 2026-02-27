# Stress Test Scenario Generator

A hybrid LLM + EVT system for generating stress test scenarios for Lloyd's insurance reserve risk.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        PHASE 1: BUILD LIBRARY                           │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  Step 1: Data Preparation                                               │
│  ├── Load unified corpus (syndicate + market movements)                 │
│  ├── Compute severity ratios (PYD / Opening Reserves)                   │
│  ├── Compute complexity scores: R × (1 - HHI)                          │
│  └── Extract LOB vectors and cause classifications                      │
│                                                                         │
│  Step 2: Joint Embedding Space                                          │
│  ├── Text embedding (all-MiniLM-L6-v2, 384d)                           │
│  ├── Combine: [text ∥ severity ∥ complexity ∥ LOB]                     │
│  └── Orthogonally regularised MLP → 3D latent space                    │
│                                                                         │
│  Step 3: GPD Threshold Selection                                        │
│  ├── Mean Residual Life plot                                           │
│  ├── Parameter stability plot                                          │
│  ├── Anderson-Darling goodness-of-fit                                  │
│  └── Consensus threshold → GPD fit with constraints                    │
│                                                                         │
│  Step 4: Synthetic Generation                                           │
│  ├── For each (severity_bin × complexity_bin):                         │
│  │   ├── Find k=7 diverse historical neighbours                        │
│  │   ├── Few-shot prompt with diversification examples                 │
│  │   └── Generate 5× scenarios per cell                                │
│  └── Output: over-generated scenario pool                              │
│                                                                         │
│  Step 5: Coverage Validation                                            │
│  ├── Alpha-shape boundary detection                                    │
│  ├── Maximum Mean Discrepancy (MMD) test                               │
│  ├── Grid coverage check                                               │
│  └── KL divergence assessment                                          │
│                                                                         │
│  Step 6: Importance Sampling                                            │
│  ├── Compute target probabilities from GPD                             │
│  ├── Weight scenarios to match distribution                            │
│  └── Resample with jittering for underrepresented bins                 │
│                                                                         │
│  Step 7: Coherence Validation                                           │
│  ├── Keyword-severity matching                                         │
│  ├── Regression validator (TF-IDF + GB)                                │
│  └── Complexity-LOB consistency check                                  │
│                                                                         │
│  Output: validated_scenario_library.json                                │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────┐
│                     PHASE 2: PORTFOLIO QUERY                            │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  Input: Portfolio (LOB weights, total reserves) + Return period         │
│                                                                         │
│  Step A: Return Period → Severity                                       │
│  └── Query GPD: 100-year → 18.5% severity                              │
│                                                                         │
│  Step B: Filter Library                                                 │
│  ├── Severity band: target ± 3%                                        │
│  ├── Complexity band: portfolio ± 50                                   │
│  ├── LOB compatibility filter                                          │
│  └── Cause diversity selection                                         │
│                                                                         │
│  Step C: Fine-Tune for Portfolio                                        │
│  ├── Zero out unexposed LOBs                                           │
│  ├── Rebalance to maintain total severity                              │
│  └── Compute weighted portfolio impact                                 │
│                                                                         │
│  Step D: Chain-of-Thought Explanation                                   │
│  ├── Include historical analogues at similar severity/complexity       │
│  ├── Explain why severity is appropriate for return period             │
│  └── Note diversification effects vs historical comparators            │
│                                                                         │
│  Output: Portfolio-specific stress scenarios with explanations          │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

## Installation

```bash
pip install openai sentence-transformers scikit-learn scipy numpy
```

## Usage

All commands run from project root (`lloyds_reserve_stress_testing/`):

### Build Scenario Library (Phase 1)

```bash
# Full build (includes LLM generation - ~$50-100 API cost)
python scripts/stress_test/pipeline.py build \
    --corpus results/combined/unified_corpus.json \
    --output results/stress_test/

# Skip generation (use existing scenarios)
python scripts/stress_test/pipeline.py build \
    --corpus results/combined/unified_corpus.json \
    --output results/stress_test/ \
    --skip-generation
```

### Query for Portfolio (Phase 2)

```bash
# Example: £200m portfolio, 60% Property / 40% Casualty
python scripts/stress_test/pipeline.py query \
    --library results/stress_test/validated_scenario_library.json \
    --gpd results/stress_test/gpd_fit.json \
    --reserves 200 \
    --lob Property 0.6 \
    --lob Casualty 0.4 \
    --return-period 100 \
    --n-scenarios 5 \
    --output results/stress_test/portfolio_100y.json
```

### View Library Summary

```bash
python scripts/stress_test/pipeline.py summary \
    --library results/stress_test/validated_scenario_library.json \
    --gpd results/stress_test/gpd_fit.json
```

## Module Reference

| Module | Purpose | Key Functions |
|--------|---------|---------------|
| `config.py` | Data structures and constants | `PortfolioSpec`, `SyntheticScenario`, `LLOYDS_LOBS` |
| `data_preparation.py` | Step 1 | `prepare_historical_data()` |
| `joint_embedding.py` | Step 2 | `JointEmbeddingSpace.fit()` |
| `evt_threshold.py` | Step 3 | `fit_gpd_constrained()`, `return_period_to_severity()` |
| `synthetic_generation.py` | Step 4 | `SyntheticScenarioGenerator.generate_all()` |
| `coverage_validation.py` | Step 5 | `validate_coverage()` |
| `importance_sampling.py` | Step 6 | `resample_to_gpd()` |
| `coherence_validation.py` | Step 7 | `validate_coherence()` |
| `visualization.py` | Step 8 | `generate_all_diagnostic_plots()` |
| `portfolio_query.py` | Phase 2 | `PortfolioQueryEngine.query()` |
| `pipeline.py` | Orchestration | `ScenarioLibraryBuilder.run()` |

## Key Design Decisions

| Question | Answer |
|----------|--------|
| What does EVT do? | Outputs severity magnitude for given return period. Nothing else. |
| What does retrieval do? | Finds diverse historical examples that teach causal patterns. |
| What does LLM do? | Generates narratives explaining EVT-derived severity. |
| How ensure diversity? | Stratified sampling by year, cause type, severity band, complexity. |
| How ensure realism? | LLM cites historical analogues; severity constrained by EVT. |
| Portfolio size handling? | Complexity = R × (1 - HHI) captures both size and diversification. |

## Output Files

After running the build pipeline:

```
results/stress_test/
├── prepared_data.json                # Historical movements with severity/complexity
├── embedding_space/                  # Trained embedding model
│   ├── projection_network.pkl
│   ├── text_embeddings.npy
│   ├── latent_coords.npy
│   └── movements.json
├── gpd_fit.json                      # GPD parameters and return period mapping
├── synthetic_scenarios.json          # Raw generated scenarios
├── coverage_validation.json          # Coverage test results
├── importance_sampling.json          # Resampling statistics
├── coherence_validation.json         # Coherence check results
├── validated_scenario_library.json   # FINAL: Use this for queries
├── pipeline_metrics.json             # Build statistics
└── plots/                            # Diagnostic visualizations
    ├── a_latent_space.png
    ├── b_coverage_scatter.png
    ├── c_historical_density.png
    ├── d_synthetic_density.png
    ├── e_severity_histogram.png
    ├── f_density_comparison.png
    └── evt/                          # EVT diagnostic plots
        ├── evt_0_summary.png         # 3×3 summary dashboard
        ├── evt_1_shape_stability.png
        ├── evt_2_scale_stability.png
        ├── evt_3_qq_plot.png
        ├── evt_4_pp_plot.png
        ├── evt_5_density.png
        ├── evt_6_loglog_tail.png
        ├── evt_7_loglog_linearity.png
        ├── evt_8_mean_excess.png
        └── evt_9_ad_threshold.png
```

## Diagnostic Plots

The pipeline automatically generates diagnostic plots in two categories:

### Embedding/Coverage Plots (`plots/`)

| Plot | Description |
|------|-------------|
| `a_latent_space.png` | 3D latent space projections (Severity×Causality, Severity×Portfolio, Causality×Portfolio) |
| `b_coverage_scatter.png` | Historical (blue) vs Synthetic (red) in latent space |
| `c_historical_density.png` | KDE density contours of historical data |
| `d_synthetic_density.png` | KDE density contours of synthetic data |
| `e_severity_histogram.png` | Severity distribution comparison with KDE |
| `f_density_comparison.png` | Side-by-side density comparison (2×3 grid) |

### EVT Diagnostic Plots (`plots/evt/`)

| Plot | Description |
|------|-------------|
| `evt_0_summary.png` | **3×3 summary dashboard** of all EVT diagnostics |
| `evt_1_shape_stability.png` | Shape parameter (ξ) stability vs threshold with 95% CI |
| `evt_2_scale_stability.png` | Modified scale (σ* = σ - ξu) stability vs threshold |
| `evt_3_qq_plot.png` | Q-Q plot: empirical vs GPD theoretical quantiles |
| `evt_4_pp_plot.png` | P-P plot: empirical vs GPD CDFs with KS bands |
| `evt_5_density.png` | Exceedance histogram with fitted GPD and KDE overlay |
| `evt_6_loglog_tail.png` | Log-log survival plot showing Pareto tail behavior |
| `evt_7_loglog_linearity.png` | R² of log-log linear fit vs threshold |
| `evt_8_mean_excess.png` | Mean Residual Life plot with linear fit |
| `evt_9_ad_threshold.png` | Anderson-Darling statistic and p-value vs threshold |

### Interpreting EVT Plots

**Threshold Selection:**
- **Shape/Scale Stability**: Look for region where parameters stabilize
- **Mean Excess Plot**: Should become linear above valid threshold
- **AD p-value**: Choose lowest threshold with p-value > 0.05

**GPD Fit Quality:**
- **Q-Q Plot**: Points should lie on diagonal
- **P-P Plot**: Points should lie on diagonal within KS bands
- **Density Plot**: GPD curve should match histogram

**Tail Behavior:**
- **Log-Log Plot**: Linear relationship indicates Pareto-type tail
- **Log-Log Linearity**: R² > 0.95 suggests good power-law fit

### Standalone Plot Generation

```python
# Embedding/Coverage plots
from stress_test.visualization import (
    plot_latent_space,
    plot_coverage_scatter,
    plot_severity_histogram,
    generate_all_diagnostic_plots
)

# Generate single plot
fig = plot_severity_histogram(
    historical_severities,
    synthetic_severities,
    output_path='severity_comparison.png'
)

# Generate all embedding plots
figures = generate_all_diagnostic_plots(
    historical_coords=hist_coords,
    synthetic_coords=syn_coords,
    historical_severities=hist_sev,
    synthetic_severities=syn_sev,
    output_dir='plots/'
)

# EVT diagnostic plots
from stress_test.evt_visualization import (
    plot_shape_stability,
    plot_mean_excess,
    plot_qq_gpd,
    plot_evt_summary,
    generate_evt_diagnostic_plots
)

# Generate single EVT plot
fig = plot_mean_excess(severities, output_path='mean_excess.png')

# Generate all EVT plots
evt_figures = generate_evt_diagnostic_plots(
    severities,
    threshold=0.10,  # Optional, auto-selected if None
    output_dir='evt_plots/'
)

# Generate EVT summary dashboard
fig = plot_evt_summary(severities, output_path='evt_summary.png')
```

## Configuration

Create `config.json` for custom settings:

```json
{
  "embedding": {
    "text_model": "all-MiniLM-L6-v2",
    "latent_dim": 3,
    "epochs": 100
  },
  "evt": {
    "min_exceedances": 30,
    "max_shape": 0.5,
    "n_bootstrap": 1000
  },
  "generation": {
    "scenarios_per_cell": 5,
    "k_neighbours": 7,
    "llm_model": "gpt-4o"
  },
  "validation": {
    "target_library_size": 2000,
    "coherence_zscore_threshold": 2.5
  }
}
```

Then run:

```bash
python scripts/stress_test/pipeline.py build --config config.json ...
```

## API Cost Estimation

Phase 1 generation (Step 4) makes LLM calls:
- Severity bins: 12
- Complexity bins: 5
- Scenarios per cell: 5 × 5 (overgeneration)
- **Total cells**: 60
- **Estimated cost**: ~$50-100 (GPT-4o)

Phase 2 queries make 1 LLM call per scenario for explanations:
- 5 scenarios × 1 call = ~$0.10 per query
