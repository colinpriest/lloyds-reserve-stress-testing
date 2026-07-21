lloyds_reserve_stress_testing/
│
├── .env                                    # API keys (gitignored)
├── .gitignore
├── requirements.txt                        # Python dependencies
├── README.md
├── CLAUDE.md                               # AI assistant context (gitignored, local only)
├── AGENTS.md                               # Agent instructions (gitignored, local only)
├── file_and_folder_structure.md            # This file
│
├── table_extraction.py                     # Deterministic table extraction (triangle, LOB, provisions)
├── test_gemini.py                          # Main extraction pipeline (RAG-lite + dual-LLM)
├── adjudicate.py                           # LLM disagreement adjudication
├── manual_override.py                      # Manual override for extraction results
│
├── tests/                                  # Ad-hoc test / experiment scripts
│   ├── test_azure.py                       # Azure Document Intelligence testing
│   ├── test_nutrient.py                    # Nutrient.io API testing
│   ├── test_adobe.py                       # Adobe PDF Extract testing
│   ├── test_single_report.py               # Single report extraction testing (run from project root)
│   └── temp.py                             # Ad-hoc testing
│
├── data/
│   ├── syndicate_numbers.py                # List of syndicate numbers to scrape (~300)
│   └── __init__.py
│
├── docs/                                   # Documentation and validation files
│   ├── data-construction.md                # Data construction methodology
│   ├── data-audit-results.md               # Data audit summary
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
├── syndicate_reports/                      # Syndicate report outputs (gitignored PDFs/HTMLs)
│   ├── Lloyds_syndicates_2014_2024.xlsx    # Syndicate-year denominator with report URLs
│   ├── pdfs/                               # Downloaded PDF and HTML files
│   │   └── syndicate_NNNN_YYYY.pdf         # ~581 PDFs, ~40 HTMLs
│   ├── metadata/
│   │   ├── reports.json                    # Metadata for all found reports
│   │   ├── summary.json                    # Summary statistics
│   │   └── errors.json                     # Any errors encountered
│   ├── coverage/                           # Coverage/audit outputs
│   │   ├── coverage_status.xlsx            # Per-syndicate-year status (multiple sheets)
│   │   ├── coverage_status.json            # Full detail incl. LoB mixes
│   │   └── coverage_report.md              # Written coverage summary
│   ├── download_status.json                # Per-row download ledger
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
│   ├── syndicate_NNNN_YYYY.json            # Structured extraction results (one per syndicate-year)
│   ├── ritc_scan.json                      # RITC occurrence flags (evidence/section/page)
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
│   └── combined/                           # Merged market + syndicate corpus
│       ├── unified_corpus.json             # Combined market + syndicate data
│       ├── corpus_by_lob.json              # Corpus organized by line of business
│       ├── corpus_by_year.json             # Corpus organized by year
│       └── corpus_summary.json             # Summary statistics
│
├── scripts/
│   ├── lloyds_scraper.py                   # Main scraper for downloading syndicate PDFs
│   ├── download_from_xlsx.py               # xlsx-driven report downloader
│   ├── quality_classifier.py               # Quality classification of syndicate reserve commentary
│   ├── ocr_scanned_pdfs.py                 # OCR processing for scanned PDFs
│   ├── build_coverage_status.py            # Build coverage/audit outputs
│   ├── syndicate_summarizer.py             # ChatGPT summarization for syndicate reports
│   ├── market_commentary_scraper.py        # Market commentary scraper
│   ├── chatgpt_summarizer.py               # ChatGPT summarization for market commentary
│   ├── perplexity_discovery.py             # Source discovery via Perplexity API
│   ├── merge_corpus.py                     # Merge market and syndicate data into unified corpus
│   └── analyse_strengthenings.py           # Analysis of reserve strengthenings
│
└── analysis/                               # Analysis outputs (gitignored)
    └── quality.json                        # Quality analysis results

## Notes

- **PDFs and HTMLs are gitignored**: The actual report files are not tracked in git
- **Analysis outputs are gitignored**: Generated analysis files are excluded
- **.env is gitignored**: API keys are stored locally and not committed
- **PDF extraction**: Structured JSON files (one per syndicate-year) from the dual-LLM extraction pipeline; Azure is the default table backend that processes the corpus
- **Coverage/audit**: `syndicate_reports/coverage/` holds per-syndicate-year status, source attribution, and reconciliations; rebuild with `scripts/build_coverage_status.py`
- **Combined corpus**: The `results/combined/` directory contains merged market and syndicate data
- **docs/**: Contains methodology documentation and validation artefacts (spreadsheets, CSV)
