# Lloyd's Reserve Data Collection & Extraction

A Python toolkit for collecting, extracting, and standardizing insurance reserve data from Lloyd's of London syndicate reports and market commentary, to support academic research on insurance reserve movements.

## Quick Summary

This project builds research-ready reserve datasets by:
1. **Scraping** syndicate annual reports and market commentary (2014-2024)
2. **Classifying** quality of reserve commentary (4-tier system)
3. **Extracting** structured reserve data (prior year development, LOB breakdowns, claims triangles) from syndicate PDFs using a RAG-lite pipeline (deterministic table extraction + dual-LLM verification)
4. **Standardizing** market reserve movements using ChatGPT summarization
5. **Merging** syndicate and market data into a unified corpus

## Tech Stack

| Layer | Technology | Version | Purpose |
|-------|------------|---------|---------|
| Language | Python | 3.8+ | Core implementation |
| Web Scraping | requests, BeautifulSoup4, lxml | Latest | Download and parse PDFs and web pages |
| PDF Processing | PyMuPDF, pdfplumber, pdf2image | 1.23.0+ | Extract text from PDFs |
| Table Extraction | Azure Document Intelligence (default), Nutrient, Adobe PDF Extract | Latest | Deterministic table/triangle extraction |
| Data Processing | pandas | 2.0.0+ | Tabular data manipulation |
| LLM APIs | openai (GPT), Gemini | 1.0.0+ | Dual-LLM extraction + ChatGPT summarization |
| LLM APIs | requests | 2.31.0+ | Perplexity API (custom implementation) |
| Visualization | matplotlib | Latest | Diagnostics |
| OCR | pytesseract, Pillow | Latest | Scanned PDF text extraction |
| Rate Limiting | ratelimit | 2.2.1+ | API rate limit compliance |

## Setup

- Python 3.8+, `pip install -r requirements.txt` (use a venv)
- System dependencies: Poppler (PDF rendering); Tesseract OCR (optional, for scanned PDFs)
- API keys go in a local `.env` file (gitignored) — see Environment Variables below

## End-to-End Pipeline

Commands in pipeline order:

```bash
# 1. Download syndicate reports (2-4 hours for all; or --syndicates 1209,2488 --years 2020,2021)
python scripts/lloyds_scraper.py --all --output ./syndicate_reports --delay 1.5

# 2. Classify reserve commentary quality (add --single-file <pdf> for one report)
python scripts/quality_classifier.py --pdf-dir ./syndicate_reports/pdfs --output ./syndicate_reports/quality_report.json

# 2a. OCR scanned PDFs if text extraction fails
python scripts/ocr_scanned_pdfs.py --pdf-dir ./syndicate_reports/pdfs

# 3. Extract structured reserve data (Azure backend default; also: nutrient, adobe)
python test_gemini.py --table-backend azure
python test_gemini.py --syndicates 1110 --years 2022   # specific reports
python test_gemini.py --batch                          # non-interactive, no human adjudication

# 3a. Rebuild coverage/audit outputs after new downloads or extractions
python scripts/build_coverage_status.py

# 4. Scrape market commentary from official sources
python scripts/market_commentary_scraper.py --years 2022 2023 2024

# 5. Discover additional sources with Perplexity
python scripts/perplexity_discovery.py --years 2022 2023 2024

# 6. Summarize/standardize with ChatGPT
python scripts/chatgpt_summarizer.py --input market_commentary/market_commentary.json
python scripts/syndicate_summarizer.py --input ./syndicate_reports

# 7. Merge syndicate + market data into unified corpus
python scripts/merge_corpus.py --syndicate results/syndicate/ --market results/market/
```

## Project Structure

Key locations (full tree: [file_and_folder_structure.md](file_and_folder_structure.md)):

```
table_extraction.py          # Deterministic table extraction (triangle, LOB, provisions)
test_gemini.py               # Main extraction pipeline (RAG-lite + dual-LLM)
adjudicate.py                # LLM disagreement adjudication
manual_override.py           # Manual override for extraction results
data/syndicate_numbers.py    # ALL_SYNDICATES list (~300 syndicates)
scripts/                     # Scrapers, classifiers, summarizers, corpus merge
tests/                       # Ad-hoc test scripts (run from project root)
docs/                        # Methodology docs + validation artefacts
syndicate_reports/           # Downloaded PDFs (gitignored), metadata, coverage/audit, quality_report.json
market_commentary/           # Market PDFs, full text audit trail, scraped JSON
pdf_extraction/              # Per-report extraction JSON, API caches, LLM cache, audit logs
results/                     # ChatGPT outputs (market/, syndicate/) + combined/unified_corpus.json
```

## Architecture Overview

### Data Collection & Extraction Workflow

**1. Syndicate reports.** Download annual reports (2014-2024) from Lloyd's, classify reserve
commentary quality, then extract structured reserve fields (prior year development, opening
reserves, LOB mix, claims triangle) from each PDF.

**2. RAG-lite PDF extraction.** Each syndicate PDF is processed through layered extraction:
- **Page classification** (PyMuPDF / Tesseract OCR) tags relevant pages
- **Deterministic table extraction** (Azure by default; Nutrient/Adobe optional) pulls the
  claims development triangle, LOB breakdown, and provisions movement
- **Triangle post-processing** in Python computes prior year development from diagonal
  differences (no LLM arithmetic)
- **Dual-LLM verification**: Gemini and GPT independently extract the same fields, compared
  field-by-field with tolerance rules; the deterministic triangle PYD overrides the LLMs when
  available
- Output: `pdf_extraction/syndicate_NNNN_YYYY.json`

See [README.md](README.md) for the full extraction-pipeline reference.

**3. Market commentary.** Perplexity discovers sources; the market scraper collects official
reports, rating agencies, and trade press; ChatGPT standardizes reserve movements into
structured JSON.

**4. Corpus merge.** `merge_corpus.py` combines syndicate and market data into
`results/combined/unified_corpus.json`.

### Key Modules

| Module | Location | Purpose |
|--------|----------|---------|
| **Syndicate Scraper** | `scripts/lloyds_scraper.py`, `scripts/download_from_xlsx.py` | Download annual reports from Lloyd's website |
| **Quality Classifier** | `scripts/quality_classifier.py` | Score reserve commentary quality (VERY_HIGH/HIGH/MEDIUM/LOW) |
| **PDF Extraction Pipeline** | `test_gemini.py` | RAG-lite + dual-LLM extraction of reserve fields |
| **Table Extraction** | `table_extraction.py` | Deterministic triangle/LOB/provisions extraction (Azure/Nutrient/Adobe) |
| **Coverage/Audit** | `scripts/build_coverage_status.py` | Per-syndicate-year status, source attribution, reconciliation |
| **Market Scraper** | `scripts/market_commentary_scraper.py` | Extract official market sources |
| **Perplexity Discovery** | `scripts/perplexity_discovery.py` | Find trade press and rating agency sources |
| **ChatGPT Summarizers** | `scripts/chatgpt_summarizer.py`, `syndicate_summarizer.py` | Standardize commentary into structured JSON |
| **Corpus Merge** | `scripts/merge_corpus.py` | Merge syndicate + market data into unified corpus |

## Development Guidelines

### Code Style (Python)

- **File naming**: `snake_case` (e.g., `lloyds_scraper.py`, `quality_classifier.py`)
- **Function naming**: `snake_case` with verb prefix (e.g., `extract_text()`, `compute_pyd()`)
- **Variable naming**: `snake_case` (e.g., `pdf_url`, `opening_reserves`)
- **Constants**: `SCREAMING_SNAKE_CASE` (e.g., `DEFAULT_YEARS`, `PROMPT_VERSION`)
- **Classes/Dataclasses**: `PascalCase` (e.g., `ReportInfo`, `ExtractionResult`)

### Conventions

- Use `@dataclass` for structured records (e.g. `ReserveMovement`, `ExtractionResult`); monetary fields use the `_gbp_m` suffix regardless of actual currency (a separate `currency` field records the true denomination)
- Module-level `logger = logging.getLogger(__name__)` for debug/audit output
- Graceful fallback chains for extraction (PyMuPDF → pdfplumber → OCR), logging each failure
- JSON I/O via `pathlib.Path` with `parent.mkdir(parents=True, exist_ok=True)`
- Imports: stdlib, then third-party, then local

## Environment Variables

| Variable | Required | Description | Example |
|----------|----------|-------------|---------|
| `PERPLEXITY_API_KEY` | Yes | Perplexity API for source discovery | pplx-... |
| `OPENAI_API_KEY` | Yes | GPT extraction + ChatGPT summarization | sk-proj-... |
| `GEMINI_API_KEY` | Yes | Gemini extraction | ... |
| `AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT` | Yes | Table extraction (default backend) | https://... |
| `AZURE_DOCUMENT_INTELLIGENCE_KEY` | Yes | Azure Document Intelligence key | ... |
| `NUTRIENT_API_KEY` | No | Nutrient.io table backend (optional) | ... |
| `ADOBE_PDF_SERVICES_CLIENT_ID` | No | Adobe PDF Extract backend (optional) | ... |
| `ADOBE_PDF_SERVICES_CLIENT_SECRET` | No | Adobe PDF Extract secret (optional) | ... |
| `GOOGLE_API_KEY` | No | Google Custom Search | AIza... |
| `GOOGLE_CSE_ID` | No | Custom Search Engine ID | 164801ff... |

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

### Reserve Movement (from corpus)

```json
{
  "syndicate": 1209,
  "year": 2023,
  "opening_reserves": 450.0,
  "prior_year_development": -18.5,
  "lines_of_business": {"Property": 0.35, "Casualty": 0.65},
  "narrative": "Property releases due to favourable claims experience...",
  "causal_category": "Social inflation / litigation trends",
  "source": "syndicate_reports/pdfs/syndicate_1209_2023.pdf"
}
```

See [README.md](README.md) for the full `pdf_extraction/syndicate_NNNN_YYYY.json` extraction
output schema (dual-LLM outputs, RAG triangle, validation results).

## Testing

- **Unit tests**: Not formally organized; ad-hoc test scripts under `tests/`
- **Integration tests**: Full pipeline tested via command-line runs
- **Coverage**: Focus on scrapers, classifiers, and PDF extraction
- **Validation**: Quality classifier and extraction tested against manually-labeled reports (`docs/validation/`)

## Additional Resources

Read these on demand — do not assume their content from this file alone:

- **Full documentation**: [README.md](README.md) — extraction pipeline reference, output schemas, data locations, audit trail
- **Detailed structure**: [file_and_folder_structure.md](file_and_folder_structure.md)
- **Data construction methodology**: [docs/data-construction.md](docs/data-construction.md)
- **OCR/extraction pipeline internals**: [docs/ocr-pipeline.md](docs/ocr-pipeline.md) — page classification, triangle parsers, PYD computation, troubleshooting
- **Syndicate numbers data**: [data/syndicate_numbers.py](data/syndicate_numbers.py) — `ALL_SYNDICATES` (~300 syndicates), 2014-2024
- **API Keys security**: See `.env.example` pattern (never commit `.env`)

## Common Issues

**"ModuleNotFoundError: No module named 'openai'"**
→ Install dependencies: `pip install -r requirements.txt`

**"Failed to extract text from PDF"**
→ Older PDFs may be scanned; run OCR: `python scripts/ocr_scanned_pdfs.py`

**"No triangle found" / "no_triangle_data"**
→ Some run-off syndicate reports genuinely lack a claims triangle; check the Azure cached output

**"API rate limit exceeded"**
→ Increase delay in scraper: `python scripts/lloyds_scraper.py --delay 3.0`

**"Poppler not found"**
→ Install system dependency (see Prerequisites section above)

**Stale extraction cache**
→ Bump `_CACHE_VERSION` in `table_extraction.py` to invalidate cached table extractions;
delete `pdf_extraction/llm_cache/` to force LLM re-extraction

## Skill Usage

When a task involves one of the project's installed technology skills (python, requests, beautifulsoup4, pymupdf, pdfplumber, pytesseract, pillow, openai, pandas, matplotlib, ratelimit, json, logging), invoke that skill before writing code. The skill descriptions in the session's skill list say when each applies.
