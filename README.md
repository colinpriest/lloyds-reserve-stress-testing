# Lloyd's Reserve Stress Testing Data Collection Toolkit

A comprehensive Python toolkit for collecting and analyzing Lloyd's of London reserve commentary data from multiple sources to support academic research on insurance reserve stress testing using LLMs and Extreme Value Theory (EVT).

## Overview

This toolkit provides two complementary data collection pipelines:

1. **Syndicate Report Scraper** - Downloads and classifies quality of individual syndicate annual reports (2014-2024)
2. **Market Commentary Scraper & Analyzer** - Discovers, scrapes, and standardizes market-wide reserve commentary from multiple sources

Together, these tools enable research on using LLMs with EVT for insurance reserve stress testing by providing:
- **Syndicate-level data**: Detailed line-of-business breakdowns and causal explanations from individual syndicate reports
- **Market-level data**: Standardized reserve movements and causal narratives from official reports, rating agencies, and trade press

## Architecture

**Two-LLM Design for Market Commentary:**

- **Perplexity** → Source Discovery (web search with citations)
- **ChatGPT** → Summarization & Standardization (consistent text generation)

This separation leverages each LLM's strengths:
- Perplexity excels at finding current sources with real-time web search
- ChatGPT excels at consistent formatting and structured extraction

## Installation

### Python Dependencies

```bash
# Create virtual environment (recommended)
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### OCR Dependencies (for Scanned PDFs)

The syndicate classifier includes OCR support for scanned PDFs that cannot be processed with standard text extraction. To enable OCR:

1. **Install Tesseract OCR:**
   - **Windows**: Download from [GitHub releases](https://github.com/UB-Mannheim/tesseract/wiki) or use conda: `conda install -c conda-forge tesseract`
   - **Linux**: `sudo apt-get install tesseract-ocr` (or equivalent)
   - **macOS**: `brew install tesseract`

2. **Install Poppler** (required by pdf2image):
   - **Windows**: Download from [GitHub releases](https://github.com/oschwartz10612/poppler-windows/releases)
   - **Linux**: `sudo apt-get install poppler-utils`
   - **macOS**: `brew install poppler`

The classifier will automatically detect Tesseract in common installation locations (conda environments, Windows default paths, etc.). If OCR libraries are not available, the classifier will fall back to standard text extraction methods (PyMuPDF, pdfplumber) and log a warning.

### Configuration

#### Environment Variables

Create a `.env` file in the project root with your API keys:

```bash
# Required for market commentary source discovery
PERPLEXITY_API_KEY=your-perplexity-api-key

# Required for summarization
OPENAI_API_KEY=your-openai-api-key

# Optional: For enhanced Google search discovery
GOOGLE_API_KEY=your-google-api-key
GOOGLE_CSE_ID=your-custom-search-engine-id
```

**Note:** The `.env` file is already included in `.gitignore` to keep your API keys secure.

## Quick Start

### Syndicate Reports Pipeline

#### 1. Test with a few syndicates

```bash
# Test with known HIGH quality syndicate (1209) from feasibility assessment
python scripts/syndicate_scraper.py --syndicates 1209,2488,1274 --output ./syndicate_reports

# Check results
cat ./syndicate_reports/metadata/summary.json
```

#### 2. Full scrape of all syndicates

```bash
# Download all available reports (takes 2-4 hours)
python scripts/syndicate_scraper.py --all --output ./syndicate_reports --delay 1.5

# This will:
# - Check ~300 syndicates
# - Attempt to download ~11 years per syndicate (2014-2024)
# - Save PDFs to ./syndicate_reports/pdfs/
# - Save metadata to ./syndicate_reports/metadata/
```

#### 3. Classify quality of downloaded reports

```bash
# After downloading, classify quality
python scripts/syndicate_quality_classifier.py --pdf-dir ./syndicate_reports/pdfs --output ./syndicate_reports/quality_report.json

# View summary
cat ./syndicate_reports/quality_report.json | python -m json.tool | head -50
```

### Market Commentary Pipeline

#### Step 1: Discover Sources (Perplexity)

```bash
# Discover sources for specific years
python scripts/perplexity_discovery.py --years 2022 2023 2024

# Discover sources for a specific LOB
python scripts/perplexity_discovery.py --years 2023 --lob "casualty_reinsurance"

# Output: market_commentary/discovered_sources.json, market_commentary/discovered_sources_urls.json
```

#### Step 2: Scrape Discovered Sources

```bash
# Scrape all sources (uses discovered URLs + known URLs)
python scripts/market_scraper.py --years 2022 2023 2024

# Or provide discovered URLs explicitly
python scripts/market_scraper.py --urls market_commentary/discovered_sources_urls.json
```

#### Step 3: Summarize with ChatGPT

```bash
# Standardize and summarize scraped data
python scripts/market_summarizer.py --input market_commentary/market_commentary.json --year 2023

# Generate stress test training data
python scripts/market_summarizer.py --input market_commentary/market_commentary.json --year 2023 --generate-training

# Output: results/market/standardized_movements_2023.json, results/market/lob_summaries_2023.json, results/market/market_report_2023.md
```

### Full Pipeline

```bash
# Run complete pipeline
./scripts/run_pipeline.sh --years 2023 --discover --summarize

# Or step by step:
python scripts/perplexity_discovery.py --years 2023 --output market_commentary/discovered.json
python scripts/market_scraper.py --years 2023 --output-dir ./market_commentary
python scripts/market_summarizer.py --input ./market_commentary/market_commentary.json --year 2023 --output-dir ./results/market
```

## File Structure

```
lloyds_reserve_stress_testing/
│
├── .env                                    # API keys
├── .gitignore
├── requirements.txt                        # Python dependencies
├── README.md
│
├── data/
│   ├── syndicate_numbers.py                # List of syndicate numbers to scrape
│   └── __init__.py
│
├── syndicate_reports/                      # Syndicate report outputs
│   ├── pdfs/                               # Downloaded PDF files
│   │   ├── syndicate_1209_2016.pdf
│   │   ├── syndicate_1209_2017.pdf
│   │   └── ...
│   ├── metadata/
│   │   ├── reports.json                    # Metadata for all found reports
│   │   ├── errors.json                     # Any errors encountered
│   │   └── summary.json                    # Summary statistics
│   ├── ocr_cache.json
│   └── quality_report.json                 # Quality classification results
│
├── market_commentary/                      # Market commentary outputs
│   ├── pdfs/
│   │   ├── lloyds_official/
│   │   │   ├── lloyds_annual_report_2024.pdf
│   │   │   └── ...
│   │   └── am_best/
│   │       └── ...
│   ├── full_text/                          # Full extracted text (audit trail)
│   │   ├── lloyds_official/
│   │   ├── am_best/
│   │   └── trade_press/
│   ├── market_commentary.json              # Main scraped data
│   ├── audit_manifest.json                 # File manifest with hashes
│   ├── discovered_sources.json
│   └── discovered_sources_urls.json
│
├── results/
│   ├── market/                             # ChatGPT market commentary outputs
│   │   ├── standardized_movements_YYYY.json
│   │   ├── lob_summaries_YYYY.json
│   │   └── market_report_YYYY.md
│   ├── syndicate/                          # ChatGPT syndicate outputs
│   │   ├── standardized_movements.json
│   │   └── audit_manifest.json
│   └── combined/                           # Merged for embedding (future)
│
├── scripts/
│   ├── syndicate_scraper.py                # Main scraper for downloading PDFs
│   ├── syndicate_quality_classifier.py     # Quality classification of reserve commentary
│   ├── syndicate_ocr.py                    # OCR processing for scanned PDFs
│   ├── syndicate_summarizer.py             # ChatGPT summarization for syndicates
│   ├── market_scraper.py                   # Market commentary scraper
│   ├── market_summarizer.py                # ChatGPT summarization for market commentary
│   ├── perplexity_discovery.py             # Source discovery via Perplexity
│   └── run_pipeline.sh                     # Full pipeline script
│
└── analysis/                               # Analysis outputs
    └── quality.json
```

## Usage Examples

### Syndicate Scraper Options

```bash
# Specific syndicates only
python scripts/syndicate_scraper.py --syndicates 1209,2488,1274,2232

# Specific years only
python scripts/syndicate_scraper.py --all --years 2020,2021,2022,2023

# Custom delay between requests (seconds)
python scripts/syndicate_scraper.py --all --delay 2.0

# Custom output directory
python scripts/syndicate_scraper.py --all --output /path/to/output
```

### Syndicate Classifier Options

```bash
# Classify single file
python scripts/syndicate_quality_classifier.py --pdf-dir ./syndicate_reports/pdfs --single-file ./syndicate_reports/pdfs/syndicate_1209_2016.pdf

# Full classification with custom output
python scripts/syndicate_quality_classifier.py --pdf-dir ./syndicate_reports/pdfs --output ./analysis/quality.json
```

## Quality Classification Criteria

The syndicate classifier uses a 4-tier system based on line-of-business (LoB) breakdown and causal clarity:

| Quality             | Criteria                                                                  | Example                                                                                                                          |
| ------------------- | ------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| **VERY_HIGH**       | Clear split by line of business WITH clear causal descriptions            | "Marine: £36.1m release due to favourable large loss experience; Property: £5.3m strengthening from inflation impacts"         |
| **HIGH**            | Split by line of business, but lacking clarity on root causes             | "Marine: £36.1m release; Property: £5.3m release; Aviation: £12.4m surplus" (with division breakdown but generic explanation) |
| **MEDIUM**          | Some reserve commentary with direction/amounts but no clear LoB breakdown | "Overall reserve release of £54.7m due to favourable experience" (no class-specific breakdown)                                  |
| **LOW**             | Minimal commentary, boilerplate text, or extraction failed                | General reserve discussion without class-specific details or quantified movements                                                |

**Key Classification Factors:**

- **Primary factor**: Line of business breakdown (multiple classes with amounts) → determines HIGH/VERY_HIGH vs MEDIUM/LOW
- **Secondary factor**: Causal clarity (specific root cause terms like "catastrophe", "inflation", "IBNR reductions") → differentiates VERY_HIGH from HIGH

## Expected Results

### Syndicate Reports

Based on feasibility assessment (13 reports sampled):

| Metric                             | Estimate                                                        |
| ---------------------------------- | --------------------------------------------------------------- |
| Total syndicates to check          | ~300                                                            |
| Available years online             | 11 (2014-2024)                                                  |
| Potential syndicate-years          | ~3,300                                                          |
| Expected downloads                 | 500-800 (not all syndicates active all years)                   |
| Usable reports (HIGH or VERY_HIGH) | ~85-140 (reports with LoB breakdown)                            |
| VERY_HIGH quality rate             | ~5-10% (reports with LoB breakdown + clear causal descriptions) |

With pre-2014 data from Lloyd's (if obtained):
- Additional 20-30 years potentially available
- Could increase HIGH quality count to 200-500

### Market Commentary

| Metric                  | Source                | Availability |
| ----------------------- | --------------------- | ------------ |
| Prior year movement %   | Lloyd's Annual Report | 2014-2024    |
| Prior year movement £m  | Lloyd's Annual Report | 2014-2024    |
| Combined ratio          | Lloyd's Annual Report | 2014-2024    |
| Attritional loss ratio  | Lloyd's Annual Report | 2014-2024    |
| Major claims ratio      | Lloyd's Annual Report | 2014-2024    |
| LOB-specific movements  | Lloyd's Annual Report | 2017-2024    |
| Causal narratives       | Multiple sources      | Variable     |

## Output Formats

### Syndicate Quality Report

```json
{
  "summary": {
    "total_assessed": 500,
    "by_quality": {
      "VERY_HIGH": 25,
      "HIGH": 60,
      "MEDIUM": 200,
      "LOW": 200,
      "ERROR": 15
    },
    "usable_reports": 85,
    "usable_rate": 0.17,
    "good_quality_syndicates": [
      {
        "syndicate": 1209,
        "very_high_reports": 3,
        "high_reports": 5,
        "total_reports": 10,
        "years": [2014, 2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023]
      }
    ]
  },
  "assessments": [
    {
      "syndicate": 1209,
      "year": 2016,
      "quality": "VERY_HIGH",
      "confidence": 0.85,
      "has_dedicated_section": true,
      "has_strategic_report": true,
      "class_breakdown_found": true,
      "causal_language_found": true,
      "quantified_movements": true,
      "has_specific_causes": true,
      "classes_mentioned": ["marine", "aviation", "property", "third party liability"],
      "causal_phrases": ["favourable experience", "IBNR reductions", "adverse development"],
      "monetary_amounts": ["£37.6m", "£54.7m", "£5.3m", "£23.4m"],
      "specific_causal_terms": ["IBNR reductions", "inflation"],
      "extraction_method": "pymupdf",
      "total_pages": 45
    }
  ]
}
```

### Market Commentary Data Schema

#### CommentarySource

```json
{
  "source_type": "lloyds_official|am_best|trade_press|broker|rating_agency",
  "source_name": "Lloyd's Annual Report 2023",
  "url": "https://...",
  "year": 2023,
  "period": "annual|interim|quarterly|article",
  "content": "...",
  "extracted_at": "2024-01-15T10:30:00",
  "content_hash": "md5hash",
  "lines_of_business": {
    "Casualty": ["relevant excerpts..."],
    "Property": ["relevant excerpts..."]
  },
  "reserve_movements": [
    {
      "match": "prior year release of 3.6%",
      "value": "3.6",
      "context": "surrounding text..."
    }
  ],
  "causal_statements": [
    "driven by favourable claims experience...",
    "strengthening reflecting social inflation concerns..."
  ]
}
```

#### ReserveMovementSummary

```json
{
  "line_of_business": "Reinsurance Casualty",
  "year": 2023,
  "direction": "release|strengthening|mixed",
  "percentage": 2.9,
  "amount_gbp_m": 322.0,
  "causal_factors": [
    "Social inflation / litigation trends",
    "Economic / claims inflation"
  ],
  "specific_events": [
    "Hurricane Ian (2022)",
    "Ukraine conflict"
  ],
  "forward_looking_concerns": [
    "US liability exposure remains elevated..."
  ],
  "confidence": "high|medium|low",
  "sources": [
    {"url": "https://lloyds.com/..."}
  ]
}
```

## Audit Trail

The scrapers maintain complete audit trails:

1. **Original PDFs**: Stored in respective `pdfs/` directories, unchanged
2. **Full Text**: Complete extracted text stored in `full_text/` with headers:
   ```
   # Source: https://...
   # Extracted: 2024-01-15T10:30:00
   # PDF: pdfs/lloyds_official/lloyds_annual_report_2023.pdf
   # Length: 245000 characters
   #======================================================================

   [full extracted text]
   ```
3. **Content Hashes**: SHA256 hash of full content for verification
4. **Audit Manifest**: `audit_manifest.json` with all files and hashes

### Standardization Audit Trail

The ChatGPT summarizers preserve source references:

```json
{
  "line_of_business": "Reinsurance - Casualty",
  "year": 2023,
  "direction": "release",
  "percentage": 2.9,
  "standardized_narrative": "...",
  "raw_extracts": ["full extract 1...", "full extract 2..."],
  "source_files": ["full_text/lloyds_official/...", "full_text/am_best/..."],
  "source_hashes": ["sha256:abc...", "sha256:def..."],
  "source_urls": ["https://...", "https://..."],
  "standardized_at": "2024-01-15T10:30:00",
  "standardization_model": "gpt-4-turbo"
}
```

This allows you to:
- Verify content hasn't changed (hash comparison)
- Trace any standardized output back to original text
- Reproduce the analysis with the exact same inputs

## Source Categories (Market Commentary)

### Lloyd's Official (Highest Quality)

- Annual Reports: Detailed LOB commentary in "Market Results" section
- Analyst Presentations: Summarized metrics with management commentary
- Half Year Reports: Interim reserve development updates
- Aggregate Accounts: Technical financial data

### Rating Agencies

- **AM Best**: Lloyd's-specific annual reports with reserve analysis
- **Fitch/S&P/Moody's**: Market commentary in rating rationales

### Trade Press

- **Reinsurance News**: Breaking news on results
- **Artemis**: Focus on catastrophe and ILS angles
- **Insurance Journal**: US-focused Lloyd's coverage
- **Insurance Times UK**: Detailed UK market analysis
- **Insurance Business Mag**: International perspectives

### Broker/Analyst Reports

- **Gallagher Re**: Annual Lloyd's market reports
- **Alpha Insurance Analysts**: Detailed syndicate and market analysis
- **PNO Insurance**: Australian broker perspective

## Causal Factor Categories

The system identifies these causal categories:

1. **Social Inflation**: US litigation trends, nuclear verdicts, attorney advertising
2. **Economic Inflation**: Claims cost inflation, wage inflation, material costs
3. **Catastrophe Events**: Named hurricanes, floods, wildfires, earthquakes
4. **Regulatory/Legal**: Court rulings (e.g., FCA BI test case), Ogden rate changes
5. **Geopolitical**: Ukraine conflict, sanctions, political violence
6. **Pandemic**: COVID-19 BI claims, contingency, event cancellation
7. **Market Factors**: Reinsurance availability, pricing adequacy, reserve margins

## Troubleshooting

### Common Issues

**"Failed to download" errors**

- Lloyd's servers may be slow; increase `--delay` to 3-5 seconds
- Some syndicates may have ceased operations; check errors.json

**"Failed to extract text" errors**

- Some older PDFs may be scanned images requiring OCR
- Ensure Tesseract OCR and Poppler are installed (see Installation section)
- The classifier automatically attempts OCR when standard text extraction fails
- Check the `extraction_method` field in the assessment output to see which method was used

**Low quality classification on known-good reports**

- Check if text extraction worked (view `reserve_section_text` in output)
- Some syndicates use non-standard section titles

**Network Issues**

- The scraper respects rate limits with configurable delay. If you encounter 429 errors, increase the delay.

**API Limits**

- Perplexity has rate limits (~100 requests/day on free tier)
- Consider batching requests or upgrading API tier

**Paywall Content**

- Some trade press requires subscriptions
- The scraper will log which sources require authentication

## Pre-2014 Data

Reports for years 1983-2013 are held by Lloyd's and available on request.

Contact: lloyds-mrd-returnqueries@lloyds.com

When requesting, mention:
- Academic research purpose
- Specific syndicates of interest (if known)
- Years required
- Expected data format (PDF preferred)

## Research Applications

### For Reserve Stress Testing Paper

This data enables:
- Empirical calibration of reserve movement distributions
- Causal narrative extraction for scenario generation
- Line-of-business conditioning based on market commentary
- Validation of generated scenarios against historical patterns

### Suggested Workflow

1. **Scrape syndicate reports**:
   ```bash
   python scripts/syndicate_scraper.py --all --output ./syndicate_reports
   python scripts/syndicate_quality_classifier.py --pdf-dir ./syndicate_reports/pdfs
   ```

2. **Scrape market commentary**:
   ```bash
   python scripts/market_scraper.py --years 2014 2015 2016 2017 2018 2019 2020 2021 2022 2023 2024
   ```

3. **Generate summaries**:
   ```bash
   python scripts/market_summarizer.py --input market_commentary/market_commentary.json --year 2023
   ```

4. **Identify usable syndicates** from `quality_report.json` (look for `good_quality_syndicates` with HIGH or VERY_HIGH reports)

5. **Filter to consistent performers** - syndicates with LoB breakdown (HIGH/VERY_HIGH) across multiple years

6. **Prioritize VERY_HIGH reports** - these have both LoB breakdown and clear causal descriptions

7. **Extract reserve commentary** using the `reserve_section_text` and `strategic_report_text` fields

8. **Process for your methodology** - joint semantic-numeric embedding

**Note**: Reports classified as HIGH or VERY_HIGH have line-of-business breakdowns, which is the primary requirement. VERY_HIGH reports additionally have clear causal descriptions, but HIGH reports can be supplemented with annual market commentaries for causal context.

### Key Syndicates from Feasibility Assessment

- **Syndicate 1209**: Consistently HIGH/VERY_HIGH quality with detailed LoB breakdown and causal explanations
- **Syndicate 2488**: HIGH quality (LoB breakdown but may need market commentary for causal context)
- **Syndicate 1274**: MEDIUM quality (some reserve commentary but no clear LoB breakdown)
- **Syndicate 2232**: LOW quality (embedded commentary without structure)

## Limitations

- **Paywall content**: Some trade press requires subscriptions
- **PDF quality**: OCR errors possible in older reports
- **Causal depth**: Most sources provide thematic rather than specific causation
- **Timeliness**: Some sources update quarterly, not continuously
- **API limits**: Perplexity has rate limits (~100 requests/day on free tier)

## Contributing

To add new sources:

1. Add URL patterns to `SourceRegistry` in `market_scraper.py`
2. Add extraction patterns for new source formats
3. Update `CURATED_SOURCES` in `perplexity_discovery.py`

## License

For academic research use only. Lloyd's syndicate reports are copyright of respective managing agents.

## References

- Lloyd's Annual Reports: https://www.lloyds.com/about-lloyds/investor-relations/financial-results
- AM Best Lloyd's Methodology: https://www.ambest.com/ratings/methodology
- CAS E-Forum: https://www.casact.org/publications/e-forum
