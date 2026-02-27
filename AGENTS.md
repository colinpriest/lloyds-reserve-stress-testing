# Lloyd's Reserve Stress Testing

A comprehensive Python toolkit for collecting, analyzing, and stress-testing insurance reserve data from Lloyd's of London using LLMs, Extreme Value Theory (EVT), and semantic-numeric joint embeddings for academic research.

## Quick Summary

This project enables quantitative stress testing of insurance reserve movements by:
1. **Scraping** syndicate reports and market commentary (2014-2024)
2. **Classifying** quality of reserve commentary (4-tier system)
3. **Standardizing** reserve movements using ChatGPT summarization
4. **Embedding** historical narratives in joint semantic-numeric space
5. **Generating** synthetic stress scenarios via EVT and LLMs
6. **Querying** portfolio-specific scenarios by return period

## Tech Stack

| Layer | Technology | Version | Purpose |
|-------|------------|---------|---------|
| Language | Python | 3.8+ | Core implementation |
| Web Scraping | requests, BeautifulSoup4, lxml | Latest | Download and parse PDFs and web pages |
| PDF Processing | PyMuPDF, pdfplumber, pdf2image | 1.23.0+ | Extract text from PDFs |
| Data Processing | pandas | 2.0.0+ | Tabular data manipulation |
| LLM APIs | openai | 1.0.0+ | ChatGPT summarization |
| LLM APIs | requests | 2.31.0+ | Perplexity API (custom implementation) |
| Embeddings | sentence-transformers | Latest | Semantic text embedding |
| ML/Statistics | scikit-learn, scipy, statsmodels | Latest | EVT, clustering, statistics |
| Vector Index | FAISS | Latest | Semantic similarity search |
| Visualization | matplotlib, plotly, altair | Latest | Analysis and diagnostics |
| UI Framework | streamlit, dash | Latest | Web interfaces for queries |
| OCR | pytesseract, Pillow | Latest | Scanned PDF text extraction |
| Rate Limiting | ratelimit | 2.2.1+ | API rate limit compliance |

## Quick Start

### Prerequisites

```bash
# System requirements
Python 3.8+
Poppler utilities (for PDF processing)
  - Windows: download from https://github.com/oschwartz10612/poppler-windows/releases
  - Linux: sudo apt-get install poppler-utils
  - macOS: brew install poppler

# Optional: OCR for scanned PDFs
Tesseract OCR
  - Windows: conda install -c conda-forge tesseract
  - Linux: sudo apt-get install tesseract-ocr
  - macOS: brew install tesseract

# API Keys required
.env file with:
  PERPLEXITY_API_KEY=...      # Source discovery
  OPENAI_API_KEY=...          # ChatGPT summarization
  GOOGLE_API_KEY=...          # Optional: enhanced search
  GOOGLE_CSE_ID=...           # Optional: custom search engine
```

### Installation & Setup

```bash
# Clone and enter directory
git clone [repository-url]
cd lloyds_reserve_stress_testing

# Create virtual environment
python -m venv venv
source venv/bin/activate      # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Verify setup
python -c "import requests, pandas, openai; print('✓ Dependencies OK')"
```

### First Run: End-to-End Pipeline

```bash
# Step 1: Download syndicate reports (takes 2-4 hours)
python scripts/lloyds_scraper.py --all --output ./syndicate_reports --delay 1.5

# Step 2: Classify quality (takes 30-60 min depending on volume)
python scripts/quality_classifier.py --pdf-dir ./syndicate_reports/pdfs --output ./syndicate_reports/quality_report.json

# Step 3: Scrape market commentary from official sources
python scripts/market_commentary_scraper.py --years 2022 2023 2024

# Step 4: Discover additional sources with Perplexity
python scripts/perplexity_discovery.py --years 2022 2023 2024

# Step 5: Summarize and standardize with ChatGPT
python scripts/chatgpt_summarizer.py --input market_commentary/market_commentary.json

# Step 6: Prepare data for stress testing
python scripts/merge_corpus.py --syndicate results/syndicate/ --market results/market/

# Step 7: Build stress test library (runs full pipeline)
python scripts/stress_test/pipeline.py build --corpus results/combined/unified_corpus.json --output results/stress_test/

# Step 8: Query for specific portfolio
python scripts/stress_test/pipeline.py query --library results/stress_test/validated_scenario_library.json --reserves 200 --return-period 100 --lobs Property Casualty
```

## Project Structure

```
lloyds_reserve_stress_testing/
├── .env                                    # API keys (gitignored)
├── .gitignore
├── requirements.txt                        # Python dependencies
├── README.md                               # Full documentation
├── CLAUDE.md                               # This file
├── file_and_folder_structure.md           # Detailed structure reference
├── simulation-workflow.md                  # Technical stress test architecture
│
├── data/
│   ├── syndicate_numbers.py                # ALL_SYNDICATES list (~300 syndicates)
│   └── __init__.py
│
├── syndicate_reports/                      # Syndicate report outputs
│   ├── pdfs/                               # Downloaded PDF/HTML files (~600+)
│   ├── metadata/
│   │   ├── reports.json                    # Metadata for all found reports
│   │   ├── summary.json                    # Summary statistics
│   │   └── errors.json                     # Download errors
│   └── quality_report.json                 # Classification results (VERY_HIGH/HIGH/MEDIUM/LOW)
│
├── market_commentary/                      # Market commentary outputs
│   ├── pdfs/
│   │   ├── lloyds_official/                # Lloyd's Annual Reports (2014-2024)
│   │   └── am_best/                        # Rating agency reports
│   ├── full_text/                          # Extracted text (audit trail)
│   │   ├── lloyds_official/
│   │   ├── am_best/
│   │   └── trade_press/
│   ├── market_commentary.json              # Scraped data with reserve movements
│   ├── audit_manifest.json                 # File hashes for verification
│   ├── discovered_sources.json             # Perplexity discovery results
│   └── discovered_sources_urls.json        # Extracted URLs
│
├── results/
│   ├── market/                             # ChatGPT market outputs
│   │   ├── standardized_movements_YYYY.json
│   │   ├── lob_summaries_YYYY.json
│   │   └── market_report_YYYY.md
│   ├── syndicate/                          # ChatGPT syndicate outputs
│   │   ├── standardized_syndicate_movements.json
│   │   ├── syndicate_summary.json
│   │   ├── year_summary.json
│   │   └── lob_summary.json
│   ├── combined/                           # Unified corpus for stress testing
│   │   ├── unified_corpus.json             # Market + syndicate merged
│   │   ├── corpus_by_lob.json              # Organized by line of business
│   │   ├── corpus_by_year.json             # Organized by year
│   │   ├── corpus_summary.json             # Summary statistics
│   │   ├── embedding_inputs.json           # Prepared for embedding
│   │   └── training_pairs.json             # Training pairs for model
│   ├── stress_test/                        # Stress test outputs
│   │   ├── validated_scenario_library.json # Final synthetic scenarios
│   │   ├── gpd_fit.json                    # EVT GPD parameters
│   │   ├── portfolio_stress_scenarios.json # Query results
│   │   ├── diagnostics/                    # Plots and analysis
│   │   └── logs/
│   └── index/                              # Vector index
│       ├── vector_store.pkl                # FAISS index
│       └── index_config.json
│
├── scripts/
│   ├── lloyds_scraper.py                   # Syndicate report downloader
│   ├── quality_classifier.py               # Reserve commentary classifier
│   ├── ocr_scanned_pdfs.py                 # OCR for image-based PDFs
│   ├── syndicate_summarizer.py             # ChatGPT syndicate summary
│   ├── market_commentary_scraper.py        # Official market source scraper
│   ├── chatgpt_summarizer.py               # ChatGPT market summary
│   ├── perplexity_discovery.py             # Perplexity source discovery
│   ├── merge_corpus.py                     # Merge market + syndicate data
│   ├── embedding_retrieval.py              # Embedding and retrieval
│   ├── portfolio_query.py                  # Portfolio-specific queries
│   ├── analyse_strengthenings.py           # Analysis utilities
│   └── stress_test/                        # Stress testing pipeline
│       ├── __init__.py
│       ├── config.py                       # Constants and config classes
│       ├── pipeline.py                     # Main orchestrator (build & query phases)
│       ├── data_preparation.py             # Severity/complexity scoring
│       ├── joint_embedding.py              # Semantic-numeric embedding space
│       ├── evt_threshold.py                # GPD threshold selection
│       ├── synthetic_generation.py         # LLM scenario generation
│       ├── importance_sampling.py          # GPD-weighted sampling
│       ├── coherence_validation.py         # Scenario validation
│       ├── coverage_validation.py          # Coverage validation
│       ├── visualization.py                # General plots
│       ├── evt_visualization.py            # EVT-specific plots
│       └── README.md                       # Module-specific docs
│
├── analysis/                               # Analysis outputs (gitignored)
│   └── quality.json
│
└── .claude/
    └── [configuration files - Step 2 & 3]
```

## Architecture Overview

### Two-Phase Workflow

**PHASE 1: Scenario Library Construction (one-time, ~2 hours)**

The system builds a validated library of synthetic stress scenarios from historical data:

1. **Data Preparation**: Compute severity ratios (PYD % of reserves) and complexity scores (portfolio diversification)
2. **Joint Embedding**: Project historical narratives into 3D latent space (severity axis, semantic axis, structure axis)
3. **EVT Threshold Selection**: Find optimal GPD threshold using MRL plot, parameter stability, and A-D goodness-of-fit
4. **Stratified Generation**: LLM generates synthetic scenarios filling severity × complexity grid with few-shot prompts
5. **Semantic Coverage Validation**: Ensure synthetic scenarios maintain semantic diversity
6. **Importance Sampling**: Re-weight scenarios to match GPD tail distribution
7. **Coherence Validation**: Verify scenario narratives align with economic logic

Output: `validated_scenario_library.json` (hundreds of scenarios with narrative + metrics)

**PHASE 2: Portfolio Query (per-request, <5 seconds)**

Given a portfolio and return period, retrieve and customize stress scenarios:

1. **Return Period → Severity**: Convert (e.g., 100-year → 8% severity threshold)
2. **Scenario Filtering**: Retrieve scenarios matching portfolio's LOB composition
3. **Portfolio Fine-tuning**: Adjust severity/impact based on portfolio reserves and concentration
4. **Narrative Generation**: Create explanatory text for selected scenarios

Output: `portfolio_stress_scenarios.json` (5-10 scenarios with explanations)

### Key Modules

| Module | Location | Purpose |
|--------|----------|---------|
| **Syndicate Scraper** | `scripts/lloyds_scraper.py` | Download annual reports from Lloyd's website (~600 PDFs) |
| **Quality Classifier** | `scripts/quality_classifier.py` | Score reserve commentary quality (VERY_HIGH/HIGH/MEDIUM/LOW) |
| **Market Scraper** | `scripts/market_commentary_scraper.py` | Extract official market sources |
| **Perplexity Discovery** | `scripts/perplexity_discovery.py` | Find trade press and rating agency sources |
| **ChatGPT Summarizers** | `scripts/chatgpt_summarizer.py`, `syndicate_summarizer.py` | Standardize commentary into structured JSON |
| **Data Preparation** | `scripts/stress_test/data_preparation.py` | Compute severity ratios and complexity scores |
| **Joint Embedding** | `scripts/stress_test/joint_embedding.py` | Build semantic-numeric embedding space |
| **EVT Threshold** | `scripts/stress_test/evt_threshold.py` | Fit GPD and select optimal threshold |
| **Synthetic Generation** | `scripts/stress_test/synthetic_generation.py` | Generate scenarios via LLM |
| **Pipeline Orchestrator** | `scripts/stress_test/pipeline.py` | Coordinate full workflow (build & query) |

## Development Guidelines

### Code Style (Python)

- **File naming**: `snake_case` (e.g., `lloyds_scraper.py`, `quality_classifier.py`)
- **Function naming**: `snake_case` with verb prefix (e.g., `extract_text()`, `fit_gpd()`)
- **Variable naming**: `snake_case` (e.g., `pdf_url`, `severity_ratio`)
- **Constants**: `SCREAMING_SNAKE_CASE` (e.g., `DEFAULT_YEARS`, `LLOYDS_LOBS`)
- **Classes/Dataclasses**: `PascalCase` (e.g., `ReportInfo`, `SyntheticScenario`)

### Import Organization

1. Standard library (os, sys, json, logging, etc.)
2. Third-party packages (requests, pandas, openai, etc.)
3. Relative imports (from data_preparation import ...)
4. Type hints: from typing import ... (with TYPE_CHECKING for circular imports)

### Key Patterns

**Dataclass for structured data:**
```python
from dataclasses import dataclass, field
from typing import List, Dict, Optional

@dataclass
class SyntheticScenario:
    severity_pct: float
    complexity_score: float
    narrative: str
    lob_breakdown: Dict[str, float]
    cause_category: str
    confidence: float
```

**Logging for debugging:**
```python
import logging
logger = logging.getLogger(__name__)
logger.info(f"Processing {num_reports} reports")
logger.error(f"Failed to extract: {error}")
```

**Error handling with graceful fallback:**
```python
try:
    text = extract_with_pymupdf(pdf_path)
except Exception as e:
    logger.warning(f"PyMuPDF failed, trying pdfplumber: {e}")
    text = extract_with_pdfplumber(pdf_path)
```

**JSON I/O with Path:**
```python
from pathlib import Path
import json

output_file = Path(output_dir) / "results.json"
output_file.parent.mkdir(parents=True, exist_ok=True)

with open(output_file, 'w') as f:
    json.dump(data, f, indent=2)
```

## Available Commands

### Data Collection

```bash
# Download syndicate reports (all or specific)
python scripts/lloyds_scraper.py --all --output ./syndicate_reports --delay 1.5
python scripts/lloyds_scraper.py --syndicates 1209,2488,1274 --years 2020,2021,2022

# Classify report quality
python scripts/quality_classifier.py --pdf-dir ./syndicate_reports/pdfs
python scripts/quality_classifier.py --pdf-dir ./syndicate_reports/pdfs --single-file ./syndicate_reports/pdfs/syndicate_1209_2016.pdf

# OCR scanned PDFs
python scripts/ocr_scanned_pdfs.py --pdf-dir ./syndicate_reports/pdfs

# Scrape market commentary
python scripts/market_commentary_scraper.py --years 2022 2023 2024
python scripts/perplexity_discovery.py --years 2023 --lob "casualty_reinsurance"
```

### Data Processing

```bash
# Summarize with ChatGPT
python scripts/chatgpt_summarizer.py --input market_commentary/market_commentary.json
python scripts/syndicate_summarizer.py --input ./syndicate_reports

# Merge data sources
python scripts/merge_corpus.py --syndicate results/syndicate/ --market results/market/
```

### Stress Testing

```bash
# Build scenario library (Phase 1: ~2 hours)
python scripts/stress_test/pipeline.py build --corpus results/combined/unified_corpus.json --output results/stress_test/

# Query for specific portfolio (Phase 2: <5 seconds)
python scripts/stress_test/pipeline.py query \
  --library results/stress_test/validated_scenario_library.json \
  --gpd results/stress_test/gpd_fit.json \
  --reserves 200 \
  --return-period 100 \
  --lobs Property Casualty

# With optional fine-tuning
python scripts/stress_test/pipeline.py query \
  --library results/stress_test/validated_scenario_library.json \
  --gpd results/stress_test/gpd_fit.json \
  --reserves 500 \
  --return-period 200 \
  --lobs "Reinsurance - Property" "Reinsurance - Casualty" \
  --concentration 0.3 \
  --output custom_scenarios.json
```

## Environment Variables

| Variable | Required | Description | Example |
|----------|----------|-------------|---------|
| `PERPLEXITY_API_KEY` | Yes | Perplexity API for source discovery | pplx-... |
| `OPENAI_API_KEY` | Yes | ChatGPT for summarization | sk-proj-... |
| `GOOGLE_API_KEY` | No | Google Custom Search | AIza... |
| `GOOGLE_CSE_ID` | No | Custom Search Engine ID | 164801ff... |
| `ANTHROPIC_API_KEY` | No | Claude API (future use) | sk-ant-... |

**⚠️ SECURITY**: Store API keys in local `.env` file (never commit). File is gitignored.

## Quality Classification System

Syndicate reports are classified into 4 tiers based on reserve commentary quality:

| Tier | Criteria | Example |
|------|----------|---------|
| **VERY_HIGH** | LoB breakdown + clear causality | "Marine: £36.1m release due to favourable large loss experience" |
| **HIGH** | LoB breakdown (generic causality) | "Marine: £36.1m release; Property: £5.3m release" |
| **MEDIUM** | Some reserve commentary, no LoB breakdown | "Overall reserve release of £54.7m due to favourable experience" |
| **LOW** | Minimal/boilerplate or extraction failed | Generic discussion without quantified details |

**Key metrics**: LoB breakdown is primary factor; causal clarity is secondary.

## Data Schema

### Historical Movement (from corpus)

```json
{
  "syndicate": 1209,
  "year": 2023,
  "opening_reserves": 450.0,
  "prior_year_development": -18.5,
  "severity_pct": 4.11,
  "lines_of_business": {"Property": 0.35, "Casualty": 0.65},
  "narrative": "Property releases due to favourable claims experience...",
  "causal_category": "Social inflation / litigation trends",
  "source": "syndicate_reports/pdfs/syndicate_1209_2023.pdf"
}
```

### Synthetic Scenario (from library)

```json
{
  "scenario_id": "synthetic_0042",
  "severity_pct": 8.7,
  "complexity_score": 245.0,
  "narrative": "Economic inflation-driven strengthening across property portfolio...",
  "lob_breakdown": {"Property": 0.45, "Casualty": 0.35, "Marine": 0.20},
  "cause_category": "Economic inflation / claims cost inflation",
  "confidence": 0.82,
  "source_historical_examples": [
    "syndicate_1209_2022",
    "syndicate_2488_2021"
  ]
}
```

### Portfolio Query Result

```json
{
  "portfolio": {
    "reserves": 500,
    "return_period": 100,
    "lines_of_business": {"Property": 0.40, "Casualty": 0.60}
  },
  "scenarios": [
    {
      "scenario_id": "synthetic_0042",
      "severity_pct": 8.7,
      "narrative_original": "...",
      "narrative_portfolio_tuned": "For a £500m portfolio with 60% Casualty exposure...",
      "lob_impact": {"Property": "9.2%", "Casualty": "8.1%"}
    }
  ]
}
```

## Testing

- **Unit tests**: Not currently organized; `temp.py` used for ad-hoc testing
- **Integration tests**: Full pipeline tested via command-line runs
- **Coverage**: Focus on scrapers, classifiers, and stress test generation
- **Validation**: Quality classifier tested against manually-labeled reports

## Deployment & Usage

### Local Development

```bash
# Virtual environment with all dependencies
python -m venv venv && source venv/bin/activate && pip install -r requirements.txt

# Test individual components
python scripts/lloyds_scraper.py --syndicates 1209 --years 2023
python scripts/quality_classifier.py --single-file ./syndicate_reports/pdfs/syndicate_1209_2023.pdf
```

### Stress Testing Pipeline

```bash
# Full end-to-end (requires ~6 hours for complete data + 2 hours for library)
./scripts/stress_test/pipeline.py build --corpus results/combined/unified_corpus.json
./scripts/stress_test/pipeline.py query --library results/stress_test/validated_scenario_library.json --reserves 200 --return-period 100
```

### Web Interface (Future)

```bash
# Streamlit interface for portfolio queries
streamlit run scripts/stress_test/app.py
```

## Additional Resources

- **Full documentation**: @README.md
- **Detailed structure**: @file_and_folder_structure.md
- **Stress test architecture**: @simulation-workflow.md
- **Stress test module**: @scripts/stress_test/README.md
- **Syndicate numbers data**: @data/syndicate_numbers.py
- **API Keys security**: See `.env.example` pattern (never commit `.env`)

## Key Research Parameters

These values in `scripts/stress_test/config.py` control the stress testing behavior:

```python
LLOYDS_LOBS = [
    "Property", "Casualty", "Marine", "Energy", "Motor",
    "Aviation", "Reinsurance - Property", "Reinsurance - Casualty",
    "Reinsurance - Specialty", "Professional Lines", "Accident & Health",
    "Cyber", "Aggregate"
]

# Severity grid for synthetic generation
SEVERITY_BINS = [0-5%, 5-10%, 10-15%, ..., 45-50%+]

# Complexity bins (portfolio diversification score)
COMPLEXITY_BINS = [0-100, 100-300, 300-600, 600+]

# EVT tail model
GPD_PARAMETERS = {
    "shape": ξ,
    "scale": σ,
    "threshold": u
}
```

## Common Issues

**"ModuleNotFoundError: No module named 'openai'"**
→ Install dependencies: `pip install -r requirements.txt`

**"Failed to extract text from PDF"**
→ Older PDFs may be scanned; run OCR: `python scripts/ocr_scanned_pdfs.py`

**"API rate limit exceeded"**
→ Increase delay in scraper: `python scripts/lloyds_scraper.py --delay 3.0`

**"Poppler not found"**
→ Install system dependency (see Prerequisites section above)

**"FAISS index not found"**
→ Build index first: `python scripts/stress_test/pipeline.py build ...`


## Skill Usage Guide

When working on tasks involving these technologies, invoke the corresponding skill:

| Skill | Invoke When |
|-------|-------------|
| scikit-learn | Implements machine learning models, EVT fitting, and statistical analysis for scenarios |
| scipy | Handles statistical distributions, EVT calculations, and numerical methods |
| sentence-transformers | Manages semantic text embeddings and similarity calculations for narratives |
| python | Manages Python 3.8+ code, imports, and script execution for data science workflows |
| requests | Handles HTTP requests for web scraping and API interactions |
| openai | Integrates ChatGPT API for reserve commentary summarization and scenario generation |
| pandas | Processes tabular reserve data, LOB breakdowns, and statistical aggregations |
| beautifulsoup4 | Parses HTML and XML content from scraped web pages and PDFs |
| pymupdf | Extracts text and metadata from PDF syndicate reports and market documents |
| faiss | Manages vector indexing and semantic similarity search for scenario retrieval |
| pdfplumber | Alternative PDF text extraction with table parsing for financial data |
| matplotlib | Generates diagnostic plots for EVT analysis and embedding space visualization |
| plotly | Creates interactive visualizations for stress test results and coverage analysis |
| altair | Builds declarative visualization specifications for exploratory data analysis |
| streamlit | Develops web interfaces for portfolio query interactions and result display |
| pillow | Processes image files for OCR preprocessing and visual analysis |
| pytesseract | Performs OCR text extraction from scanned PDF images |
| ratelimit | Enforces API rate limiting and request throttling for web scrapers |
| statsmodels | Provides statistical modeling and hypothesis testing for EVT validation |
| json | Serializes and deserializes structured data schemas for scenarios and corpus |
| logging | Configures debugging output and audit trails for pipeline execution |


## Skill Usage Guide

When working on tasks involving these technologies, invoke the corresponding skill:

| Skill | Invoke When |
|-------|-------------|
| scikit-learn | Implements machine learning models, EVT fitting, and statistical analysis for scenarios |
| scipy | Handles statistical distributions, EVT calculations, and numerical methods |
| sentence-transformers | Manages semantic text embeddings and similarity calculations for narratives |
| python | Manages Python 3.8+ code, imports, and script execution for data science workflows |
| requests | Handles HTTP requests for web scraping and API interactions |
| openai | Integrates ChatGPT API for reserve commentary summarization and scenario generation |
| pandas | Processes tabular reserve data, LOB breakdowns, and statistical aggregations |
| beautifulsoup4 | Parses HTML and XML content from scraped web pages and PDFs |
| pymupdf | Extracts text and metadata from PDF syndicate reports and market documents |
| faiss | Manages vector indexing and semantic similarity search for scenario retrieval |
| pdfplumber | Alternative PDF text extraction with table parsing for financial data |
| matplotlib | Generates diagnostic plots for EVT analysis and embedding space visualization |
| plotly | Creates interactive visualizations for stress test results and coverage analysis |
| altair | Builds declarative visualization specifications for exploratory data analysis |
| streamlit | Develops web interfaces for portfolio query interactions and result display |
| pillow | Processes image files for OCR preprocessing and visual analysis |
| pytesseract | Performs OCR text extraction from scanned PDF images |
| ratelimit | Enforces API rate limiting and request throttling for web scrapers |
| statsmodels | Provides statistical modeling and hypothesis testing for EVT validation |
| json | Serializes and deserializes structured data schemas for scenarios and corpus |
| logging | Configures debugging output and audit trails for pipeline execution |
