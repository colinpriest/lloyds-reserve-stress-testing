lloyds_reserve_stress_testing/
│
├── .env                                    # API keys (gitignored)
├── .gitignore
├── requirements.txt                        # Python dependencies
├── README.md
├── file_and_folder_structure.md            # This file
├── simulation-workflow.md                  # Simulation workflow documentation
│
├── data/
│   ├── syndicate_numbers.py                # List of syndicate numbers to scrape
│   └── __init__.py
│
├── syndicate_reports/                      # Syndicate report outputs
│   ├── pdfs/                               # Downloaded PDF and HTML files
│   │   └── syndicate_NNNN_YYYY.pdf         # ~581 PDFs, ~40 HTMLs
│   ├── metadata/
│   │   ├── reports.json                    # Metadata for all found reports
│   │   ├── summary.json                     # Summary statistics
│   │   └── errors.json                      # Any errors encountered
│   └── quality_report.json                 # Quality classification output
│
├── market_commentary/                      # Market commentary outputs
│   ├── pdfs/
│   │   ├── lloyds_official/                # Lloyd's official annual reports (2014-2024)
│   │   │   └── lloyds_annual_report_YYYY.pdf
│   │   └── am_best/                         # AM Best rating reports
│   │       └── am_best_lloyds_YYYY.pdf
│   ├── full_text/                          # Full extracted text (audit trail)
│   │   ├── lloyds_official/
│   │   │   └── lloyds_annual_report_YYYY.txt
│   │   ├── am_best/
│   │   │   └── am_best_lloyds_YYYY.txt
│   │   └── trade_press/                     # Trade press articles
│   │       ├── Artemis_YYYY_####.txt
│   │       ├── Insurance_Journal_YYYY_####.txt
│   │       ├── Insurance_Times_YYYY_####.txt
│   │       └── Reinsurance_News_YYYY_####.txt
│   ├── market_commentary.json              # Main scraped data (truncated content)
│   ├── audit_manifest.json                 # File manifest with hashes
│   ├── discovered_sources.json             # Perplexity discovery results
│   └── discovered_sources_urls.json        # Extracted URLs from discovery
│
├── results/
│   ├── market/                             # ChatGPT market commentary outputs
│   │   ├── standardized_movements_YYYY.json # Standardized reserve movements by year
│   │   ├── lob_summaries_YYYY.json          # Line of business summaries by year
│   │   └── market_report_YYYY.md             # Human-readable market reports by year
│   ├── syndicate/                          # ChatGPT syndicate outputs
│   │   ├── standardized_syndicate_movements.json
│   │   ├── syndicate_summary.json
│   │   ├── year_summary.json
│   │   └── lob_summary.json
│   ├── combined/                            # Merged corpus for embedding
│   │   ├── unified_corpus.json              # Combined market + syndicate data
│   │   ├── corpus_by_lob.json               # Corpus organized by line of business
│   │   ├── corpus_by_year.json              # Corpus organized by year
│   │   ├── corpus_summary.json              # Summary statistics
│   │   ├── embedding_inputs.json            # Prepared inputs for embedding
│   │   └── training_pairs.json               # Training pairs for model
│   └── index/                              # Vector index for retrieval
│       ├── vector_store.pkl                 # Pickled vector store
│       └── index_config.json                # Index configuration
│
├── scripts/
│   ├── lloyds_scraper.py                   # Main scraper for downloading syndicate PDFs
│   ├── quality_classifier.py               # Quality classification of syndicate reserve commentary
│   ├── ocr_scanned_pdfs.py                 # OCR processing for scanned PDFs
│   ├── syndicate_summarizer.py              # ChatGPT summarization for syndicate reports
│   ├── market_commentary_scraper.py        # Market commentary scraper
│   ├── chatgpt_summarizer.py               # ChatGPT summarization for market commentary
│   ├── perplexity_discovery.py             # Source discovery via Perplexity API
│   ├── merge_corpus.py                      # Merge market and syndicate data into unified corpus
│   ├── embedding_retrieval.py              # Embedding and retrieval functionality
│   ├── portfolio_query.py                  # Portfolio query functionality
│   ├── analyse_strengthenings.py           # Analysis of reserve strengthenings
│   └── stress_test/                        # Stress testing pipeline
│       ├── __init__.py
│       ├── README.md                        # Stress test documentation
│       ├── config.py                        # Configuration settings
│       ├── pipeline.py                      # Main stress test pipeline
│       ├── data_preparation.py              # Data preparation for stress testing
│       ├── joint_embedding.py               # Joint semantic-numeric embedding
│       ├── synthetic_generation.py          # Synthetic scenario generation
│       ├── evt_threshold.py                 # EVT threshold calculation
│       ├── importance_sampling.py           # Importance sampling for rare events
│       ├── coherence_validation.py         # Coherence validation of generated scenarios
│       ├── coverage_validation.py           # Coverage validation
│       ├── visualization.py                 # Visualization utilities
│       ├── evt_visualization.py             # EVT-specific visualizations
│       └── portfolio_query.py              # Portfolio query for stress testing
│
└── analysis/                               # Analysis outputs (gitignored)
    └── quality.json                         # Quality analysis results

## Notes

- **PDFs and HTMLs are gitignored**: The actual report files are not tracked in git
- **Analysis outputs are gitignored**: Generated analysis files are excluded
- **.env is gitignored**: API keys are stored locally and not committed
- **Script naming**: Scripts currently use original names (not yet renamed to syndicate_*/market_* prefixes)
- **Stress test module**: The `scripts/stress_test/` directory contains the complete stress testing pipeline
- **Combined corpus**: The `results/combined/` directory contains merged market and syndicate data ready for embedding
- **Vector index**: The `results/index/` directory contains the vector store for semantic retrieval
