lloyds_reserve_stress_testing/
│
├── .env                                    # API keys (gitignored)
├── .gitignore
├── requirements.txt                        # Python dependencies
├── README.md
├── CLAUDE.md                               # Project documentation for AI assistants
├── AGENTS.md                               # Agent configuration
├── file_and_folder_structure.md            # This file
├── simulation-workflow.md                  # Simulation workflow documentation
├── query_documentation.md                  # Portfolio query documentation
├── query_upgrade_documentation.md          # Portfolio query upgrade documentation
│
├── table_extraction.py                     # Deterministic table extraction (triangle, LOB, provisions)
├── test_gemini.py                          # Main extraction pipeline (RAG-lite + dual-LLM)
├── test_azure.py                           # Azure Document Intelligence testing
├── test_nutrient.py                        # Nutrient.io API testing
├── test_adobe.py                           # Adobe PDF Extract testing
├── test_single_report.py                   # Single report extraction testing
├── adjudicate.py                           # LLM disagreement adjudication
├── manual_override.py                      # Manual override for extraction results
├── IME-paper-table-figures.py              # IME paper table/figure generation
├── temp.py                                 # Ad-hoc testing
│
├── lob_weights.json                        # LOB weight distributions
├── size_metrics.json                       # Syndicate size metrics
├── size_diversification_results.json       # Size-diversification analysis results
├── test_scenarios.json                     # Test scenario data
│
├── data/
│   ├── syndicate_numbers.py                # List of syndicate numbers to scrape (~300)
│   └── __init__.py
│
├── docs/                                   # Documentation and validation files
│   ├── data-construction.md                # Data construction methodology
│   ├── exposure-adjustment.md              # Exposure adjustment documentation
│   ├── llm-prompt-development.md           # LLM prompt development notes
│   ├── ocr-pipeline.md                     # OCR pipeline documentation
│   ├── table-4-explanation.md              # Table 4 explanation
│   └── validation/                         # Validation artefacts
│       ├── rejection_log.xlsx              # Rejected reports log
│       ├── syndicate_corpus_v1.0.csv       # Syndicate corpus v1.0
│       ├── validation_sample.xlsx          # Validation sample
│       └── validation_sample_checked.xlsx  # Checked validation sample
│
├── IME/                                    # IME paper outputs (figures and tables)
│   ├── appendix_worked_example.tex         # Worked example appendix
│   ├── figure1_tail_trend.{pdf,png}        # Tail trend figure
│   ├── figure2_mean_excess.{pdf,png}       # Mean excess function figure
│   ├── figure3_size_severity.{pdf,png}     # Size-severity relationship figure
│   ├── figure4_capital_decomposition.{pdf,png}  # Capital decomposition figure
│   ├── figure5_lob_shrinkage.{pdf,png}     # LOB shrinkage figure
│   ├── figure6_local_donor.{pdf,png}       # Local donor sensitivity figure
│   ├── local_donor_sensitivity.json        # Local donor sensitivity data
│   ├── table1_corpus_summary.tex           # Corpus summary table
│   ├── table2_size_elasticity.tex          # Size elasticity table
│   ├── table3_sampling_robustness.tex      # Sampling robustness table
│   ├── table4_capital_distortion.tex       # Capital distortion table
│   └── table5_local_donor_sensitivity.tex  # Local donor sensitivity table
│
├── syndicate_reports/                      # Syndicate report outputs (gitignored)
│   ├── pdfs/                               # Downloaded PDF and HTML files
│   │   └── syndicate_NNNN_YYYY.pdf         # ~581 PDFs, ~40 HTMLs
│   ├── metadata/
│   │   ├── reports.json                    # Metadata for all found reports
│   │   ├── summary.json                    # Summary statistics
│   │   └── errors.json                     # Any errors encountered
│   └── quality_report.json                 # Quality classification output
│
├── market_commentary/                      # Market commentary outputs
│   ├── pdfs/
│   │   ├── lloyds_official/                # Lloyd's official annual reports (2014-2024)
│   │   │   └── lloyds_annual_report_YYYY.pdf
│   │   └── am_best/                        # AM Best rating reports
│   │       └── am_best_lloyds_YYYY.pdf
│   ├── full_text/                          # Full extracted text (audit trail)
│   │   ├── lloyds_official/
│   │   │   └── lloyds_annual_report_YYYY.txt
│   │   ├── am_best/
│   │   │   └── am_best_lloyds_YYYY.txt
│   │   └── trade_press/                    # Trade press articles
│   │       ├── Artemis_YYYY_####.txt
│   │       ├── Insurance_Journal_YYYY_####.txt
│   │       ├── Insurance_Times_YYYY_####.txt
│   │       └── Reinsurance_News_YYYY_####.txt
│   ├── market_commentary.json              # Main scraped data (truncated content)
│   ├── audit_manifest.json                 # File manifest with hashes
│   ├── discovered_sources.json             # Perplexity discovery results
│   └── discovered_sources_urls.json        # Extracted URLs from discovery
│
├── pdf_extraction/                         # Extraction pipeline outputs
│   ├── syndicate_NNNN_YYYY.json            # Structured extraction results (~622 files)
│   ├── audit/
│   │   ├── disagreement_log.json           # LLM disagreements and resolutions
│   │   ├── rejection_log.json              # Reports rejected by adjudication
│   │   └── run_manifest.json               # Run statistics and metadata
│   ├── adobe_output/                       # Adobe PDF Extract API raw outputs
│   │   └── syndicate_NNNN_YYYY/            # Per-report: structuredData.json, tables/*.xlsx
│   ├── azure_output/                       # Azure Document Intelligence cached results
│   │   └── syndicate_NNNN_YYYY_azure.json
│   ├── nutrient_output/                    # Nutrient.io cached page extractions
│   ├── html_converted/                     # HTML reports converted for processing
│   ├── llm_cache/                          # LLM response cache (SHA-256 keyed)
│   ├── llm_slim/                           # Slimmed LLM cache
│   ├── ocr_page_cache/                     # Tesseract OCR results per page
│   └── spec/                               # Extraction spec versions
│
├── results/
│   ├── market/                             # ChatGPT market commentary outputs
│   │   ├── standardized_movements_YYYY.json # Standardized reserve movements (2014-2024)
│   │   ├── lob_summaries_YYYY.json          # Line of business summaries (2014-2024)
│   │   └── market_report_YYYY.md            # Human-readable market reports (2014-2024)
│   ├── syndicate/                          # ChatGPT syndicate outputs
│   │   ├── standardized_syndicate_movements.json
│   │   ├── syndicate_summary.json
│   │   ├── year_summary.json
│   │   └── lob_summary.json
│   ├── syndicate_v2/                       # V2 syndicate outputs
│   ├── combined/                           # Merged corpus for embedding
│   │   ├── unified_corpus.json             # Combined market + syndicate data
│   │   ├── enhanced_corpus.json            # Enhanced corpus with additional fields
│   │   ├── corpus_with_lob.json            # Corpus with LOB weights
│   │   ├── corpus_by_lob.json              # Corpus organized by line of business
│   │   ├── corpus_by_year.json             # Corpus organized by year
│   │   ├── corpus_summary.json             # Summary statistics
│   │   ├── embedding_inputs.json           # Prepared inputs for embedding
│   │   └── training_pairs.json             # Training pairs for model
│   ├── index/                              # Vector index for retrieval
│   │   ├── vector_store.pkl                # Pickled vector store
│   │   └── index_config.json               # Index configuration
│   └── stress_test/                        # Stress test outputs (current run)
│       ├── prepared_data.json              # Historical movements with severity/complexity
│       ├── prepared_data_strict.json       # Strict mode (RAG-only PYD)
│       ├── prepared_data_estimated.json    # Estimated mode (LLM-fallback PYD)
│       ├── prepared_data_all.json          # All movements combined
│       ├── gpd_fit.json                    # GPD parameters and return period mapping
│       ├── synthetic_scenarios_raw.json    # Raw generated scenarios
│       ├── coverage_validation.json        # Coverage test results
│       ├── importance_sampling.json        # Resampling statistics
│       ├── coherence_validation.json       # Coherence check results
│       ├── dual_mode_comparison.json       # Strict vs estimated mode comparison
│       ├── validated_scenario_library.json # FINAL: Use this for queries
│       ├── embedding_space/                # Trained embedding model
│       │   ├── projection_network.pkl
│       │   ├── text_embeddings.npy
│       │   ├── latent_coords.npy
│       │   └── movements.json
│       └── plots/                          # Diagnostic visualizations
│           ├── a_latent_space.png
│           ├── b_coverage_scatter.png
│           ├── c_historical_density.png
│           ├── d_synthetic_density.png
│           ├── e_severity_histogram.png
│           ├── f_density_comparison.png
│           └── evt/                        # EVT diagnostic plots
│               ├── evt_0_summary.png
│               ├── evt_1_shape_stability.png
│               ├── evt_2_scale_stability.png
│               ├── evt_3_qq_plot.png
│               ├── evt_4_pp_plot.png
│               ├── evt_5_density.png
│               ├── evt_6_loglog_tail.png
│               ├── evt_7_loglog_linearity.png
│               ├── evt_8_mean_excess.png
│               └── evt_9_ad_threshold.png
│
├── scripts/
│   ├── lloyds_scraper.py                   # Main scraper for downloading syndicate PDFs
│   ├── quality_classifier.py               # Quality classification of syndicate reserve commentary
│   ├── ocr_scanned_pdfs.py                 # OCR processing for scanned PDFs
│   ├── syndicate_summarizer.py             # ChatGPT summarization for syndicate reports
│   ├── market_commentary_scraper.py        # Market commentary scraper
│   ├── chatgpt_summarizer.py               # ChatGPT summarization for market commentary
│   ├── perplexity_discovery.py             # Source discovery via Perplexity API
│   ├── merge_corpus.py                     # Merge market and syndicate data into unified corpus
│   ├── embedding_retrieval.py              # Embedding and retrieval functionality
│   ├── portfolio_query.py                  # Portfolio query functionality
│   ├── analyse_strengthenings.py           # Analysis of reserve strengthenings
│   └── stress_test/                        # Stress testing pipeline
│       ├── __init__.py
│       ├── README.md                       # Stress test documentation
│       ├── requirements.txt                # Stress test specific dependencies
│       ├── config.py                       # Configuration settings and dataclasses
│       ├── pipeline.py                     # Main stress test pipeline (Phase 1 build)
│       ├── pipeline_v2.py                  # V2 pipeline with dual-mode support
│       ├── dual_mode_pipeline.py           # Strict vs estimated mode pipeline
│       ├── data_preparation.py             # Severity/complexity scoring
│       ├── joint_embedding.py              # Joint semantic-numeric embedding (3D latent space)
│       ├── evt_threshold.py                # EVT threshold calculation (MRL, stability, A-D)
│       ├── gpd_fitting.py                  # GPD distribution fitting
│       ├── gpd_diagnostics.py              # GPD diagnostic checks
│       ├── gpd_sampling.py                 # GPD-based sampling
│       ├── synthetic_generation.py         # Synthetic scenario generation (LLM)
│       ├── synthetic_generation_v2.py      # V2 generation with improvements
│       ├── importance_sampling.py          # GPD-weighted importance sampling
│       ├── coherence_validation.py         # Coherence validation of generated scenarios
│       ├── coverage_validation.py          # Semantic coverage validation
│       ├── filtering_diagnostics.py        # Filtering diagnostic utilities
│       ├── visualization.py                # General diagnostic plots
│       ├── evt_visualization.py            # EVT-specific diagnostic plots
│       ├── portfolio_query.py              # Portfolio query for stress testing
│       ├── portfolio_query_v2.py           # V2 portfolio query
│       ├── portfolio_query_hierarchical.py # Hierarchical portfolio query
│       ├── portfolio_size_adjustment.py    # Size-based severity adjustments
│       ├── report_generator.py             # Report generation utilities
│       ├── diagnostic_report.py            # Diagnostic report generation
│       ├── diagnostic_visualizer.py        # Diagnostic visualization utilities
│       ├── library_diagnostics.py          # Scenario library diagnostic checks
│       ├── app_dash.py                     # Dash web interface for queries
│       ├── extract_lob_weights.py          # LOB weight extraction utility
│       ├── extract_size_metrics.py         # Size metrics extraction utility
│       ├── create_validation_sample.py     # Validation sample creation
│       ├── test_size_diversification.py    # Size-diversification testing
│       └── novelty/                        # Novelty analysis for IME paper
│           ├── __init__.py
│           ├── run_all.py                  # Run all novelty analyses
│           ├── verdicts.py                 # Verdict aggregation
│           ├── novelty_0_sampling_sensitivity.py    # Sampling sensitivity analysis
│           ├── novelty_1_mix_trend.py               # Mix trend analysis
│           ├── novelty_2_tail_stability.py           # Tail stability analysis
│           ├── novelty_3_size_scaling_validation.py  # Size scaling validation
│           ├── novelty_4_capital_distortion.py       # Capital distortion analysis
│           ├── common/                     # Shared utilities for novelty analyses
│           │   ├── __init__.py
│           │   ├── analysis_table.py       # Analysis table construction
│           │   ├── query_portfolios.py     # Portfolio query helpers
│           │   ├── severity_projection.py  # Severity projection utilities
│           │   ├── tail_metrics.py         # Tail metric calculations
│           │   └── time_windows.py         # Time window utilities
│           ├── fig/                         # Generated figures
│           │   ├── novelty0_sensitivity_histograms.png
│           │   ├── novelty1_*.png           # Mix trend plots
│           │   ├── novelty2_*.png           # Tail stability plots
│           │   ├── novelty3_*.png           # Size scaling plots
│           │   └── novelty4_*.png           # Capital distortion plots
│           ├── results/                     # Novelty analysis results
│           │   ├── _analysis_table.pkl      # Cached analysis table
│           │   ├── analysis_table_audit.json
│           │   ├── novelty0_sampling_sensitivity.json
│           │   ├── novelty1_trend_results.json
│           │   ├── novelty2_tail_stability.json
│           │   ├── novelty3_size_validation.json
│           │   ├── novelty4_capital_distortion.json
│           │   ├── run_all_summary.json
│           │   └── verdicts.json
│           └── tests/                       # Novelty analysis tests
│               ├── __init__.py
│               ├── fixtures/                # Test fixtures
│               │   ├── mini_corpus.json
│               │   ├── mini_lob_weights.json
│               │   └── mini_size_metrics.json
│               ├── test_analysis_table.py
│               ├── test_novelty_0.py
│               ├── test_novelty_1.py
│               ├── test_novelty_2.py
│               ├── test_novelty_3.py
│               ├── test_novelty_4.py
│               ├── test_severity_projection.py
│               ├── test_tail_metrics.py
│               └── test_time_windows.py
│
└── analysis/                               # Analysis outputs (gitignored)
    └── quality.json                        # Quality analysis results

## Notes

- **PDFs and HTMLs are gitignored**: The actual report files are not tracked in git
- **Analysis outputs are gitignored**: Generated analysis files are excluded
- **.env is gitignored**: API keys are stored locally and not committed
- **Stress test module**: The `scripts/stress_test/` directory contains the complete stress testing pipeline
- **Novelty analyses**: The `scripts/stress_test/novelty/` directory contains IME paper-specific analyses with their own test suite
- **Combined corpus**: The `results/combined/` directory contains merged market and syndicate data ready for embedding
- **Vector index**: The `results/index/` directory contains the vector store for semantic retrieval
- **PDF extraction**: ~622 structured JSON files from the dual-LLM extraction pipeline
- **IME paper**: The `IME/` directory contains LaTeX tables and figures for the IME paper submission
- **docs/**: Contains methodology documentation and validation artefacts (spreadsheets, CSV)
- **Timestamped stress test runs**: Historical runs stored in `results/stress_test_YYYYMMDD_HHMM/` directories (gitignored)
