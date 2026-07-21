# Lloyd's Reserve Stress Testing — Agent Instructions

The canonical project guide is [CLAUDE.md](CLAUDE.md) — read it first. It covers the data
collection & extraction pipeline (scraping, quality classification, RAG-lite PDF extraction,
corpus merge), setup, code conventions, environment variables, and common issues.

This file only adds what CLAUDE.md does not cover: the stress-testing pipeline built on top
of the unified corpus.

## Stress Testing Pipeline (`scripts/stress_test/`)

Two-phase workflow using EVT (Generalized Pareto tail modelling) + semantic-numeric joint
embeddings + LLM scenario generation:

**Phase 1 — Build** (one-time, ~2 hours on the full corpus): compute severity ratios and
complexity scores from historical movements, project narratives into a joint latent space,
select a GPD threshold (MRL plot, parameter stability, A-D goodness-of-fit), generate
synthetic scenarios via few-shot LLM prompting across the severity × complexity grid, then
validate semantic coverage and economic coherence.
Output: `results/stress_test/validated_scenario_library.json`.

**Phase 2 — Query** (per-request, <5 seconds): given portfolio reserves, return period, and
LOB weights, retrieve matching scenarios and tune narratives to the portfolio.

### Commands

```bash
# Build scenario library (Phase 1)
python scripts/stress_test/pipeline.py build --corpus results/combined/unified_corpus.json --output results/stress_test

# Query for a portfolio (Phase 2) — --lob takes NAME WEIGHT and repeats
python scripts/stress_test/pipeline.py query --library results/stress_test \
  --reserves 200 --return-period 100 --lob Property 0.4 --lob Casualty 0.6

# Library statistics / LOB re-normalization
python scripts/stress_test/pipeline.py summary --library results/stress_test/validated_scenario_library.json
python scripts/stress_test/pipeline.py normalize --library results/stress_test/validated_scenario_library.json

# Dash web interface for portfolio queries
python scripts/stress_test/app_dash.py
```

### Key Modules

| Module | Purpose |
|--------|---------|
| `config.py` | `LLOYDS_LOBS`, cause-category keywords, embedding/EVT/generation/validation/query config dataclasses |
| `pipeline.py` (+ `pipeline_v2.py`, `dual_mode_pipeline.py`) | Orchestrators (build & query phases) |
| `data_preparation.py` | Severity ratios and complexity scores |
| `joint_embedding.py` | Semantic-numeric embedding space (sentence-transformers) |
| `evt_threshold.py`, `gpd_fitting.py`, `gpd_sampling.py`, `gpd_diagnostics.py` | GPD threshold selection, fitting, sampling, diagnostics |
| `synthetic_generation.py` (+ `_v2`) | LLM scenario generation |
| `importance_sampling.py` | GPD-weighted re-weighting of scenarios |
| `coherence_validation.py`, `coverage_validation.py` | Scenario validation |
| `portfolio_query.py` (+ `_v2`, `_hierarchical`), `portfolio_size_adjustment.py` | Portfolio-specific retrieval and tuning |
| `novelty/` | Novelty analysis subpackage |
| `visualization.py`, `evt_visualization.py`, `diagnostic_*.py` | Plots and diagnostic reports |
| `app_dash.py` | Dash UI for queries |

Module docs: [scripts/stress_test/README.md](scripts/stress_test/README.md).
Related top-level helpers: `scripts/embedding_retrieval.py`, `scripts/portfolio_query.py`.

### Additional Environment Variable

Beyond those listed in CLAUDE.md, extraction adjudication (`adjudicate.py`) requires
`ANTHROPIC_API_KEY` (Claude API).

### Outputs

- `results/stress_test/` — scenario library, validation results, diagnostics
- `results/index/` — FAISS vector index (`vector_store.pkl`, `index_config.json`)
