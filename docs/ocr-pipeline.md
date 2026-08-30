# OCR and Table Extraction Pipeline

This document describes the deterministic extraction pipeline that
converts syndicate report PDFs into structured JSON containing claims
development triangles, line-of-business breakdowns, and provisions
data.  The pipeline is implemented across two files:

- **`table_extraction.py`** -- page scanning, API-based table
  extraction, grid/text parsing
- **`test_gemini.py`** -- LLM-based extraction, PYD computation,
  cross-validation, and orchestration

---

## 1  Architecture overview

```
PDF input
  |
  v
+-----------------------------------------------+
| Step 0: Inception year check (soft)            |
|   is_early_year_syndicate()                    |
|     Lookup syndicate_inception_years.json       |
|     If missing: query Perplexity API            |
|     Flag if report_year < inception_year + 2    |
|     (does NOT skip -- validated by triangle)    |
|   Cost: $0 (or ~$0.001 per Perplexity call)    |
+-----------------------------------------------+
  |
  v
+-----------------------------------------------+
| Step 1: Page scanning                          |
|   _is_scanned_pdf()                            |
|     |-> native text (PyMuPDF)                  |
|     |-> OCR (Tesseract) with rotation handling |
|   _classify_page() tags each page:             |
|     claims_triangle | premium_mix |            |
|     pl_account | provisions | balance_sheet    |
|   Returns: (matches, texts, method,            |
|             rotated_pages)                     |
+-----------------------------------------------+
  |
  v
+-----------------------------------------------+
| Step 2: Deterministic table extraction         |
|   _extract_pages_to_pdf() -> slim PDF          |
|     (rotation normalised, subset of pages)     |
|   Send to backend:                             |
|     Azure Document Intelligence (default)      |
|     Nutrient.io                                |
|     Adobe PDF Extract                          |
+-----------------------------------------------+
  |
  v
+-----------------------------------------------+
| Step 3: Grid parsing                           |
|   _parse_nutrient_triangle()                   |
|     UW year detection, dev row collection,     |
|     section-break detection (paid claims),     |
|     currency/unit/type inference               |
|   Fallback: _parse_transposed_triangle()       |
|     Grid parser for "Dev Year 1,2,3...",       |
|     "Underlying Pure Year", and                |
|     "Year of account" formats                  |
|   Fallback: _parse_triangle_from_text()        |
|     Text-based parser for columnar layouts     |
|   Fallback: _parse_transposed_triangle_from_text() |
|     Text parser for concatenated transposed    |
|   _parse_nutrient_provisions()                 |
|     Prior year claims movement                 |
|     ("Claims outstanding" column detection)    |
|   _parse_opening_claims_outstanding()          |
|     Opening gross claims from provisions note  |
|   _parse_balance_sheet_claims_outstanding()    |
|     Opening gross claims from balance sheet    |
|     liabilities (fallback if provisions empty) |
+-----------------------------------------------+
  |
  v
+-----------------------------------------------+
| Step 4: PYD computation (Python, not LLM)      |
|   compute_pyd_from_triangle()                  |
|     Loss ratio triangle detection (reject)     |
|     Year-value contamination detection          |
|     Summary-row stripping                      |
|     Diagonal extraction                        |
|     Unit auto-detection and conversion         |
|     Ratio sanity check (release > -100%)       |
+-----------------------------------------------+
  |
  v
+-----------------------------------------------+
| Step 4a: Loss ratio triangle PYD               |
|   _extract_pyd_from_loss_ratio_triangle()      |
|     Parse cumulative loss ratio grid            |
|     Find "Total ultimate losses" row            |
|     Compute PYD per UW year from ratio changes  |
|     Gross/net section separation                |
|     "ae" aggregate column handling              |
|   Result is managed-level (fallback only)       |
+-----------------------------------------------+
  |
  v
+-----------------------------------------------+
| Step 4b: Triangle vs provisions cross-check    |
|   If triangle PYD and provisions PYD disagree  |
|   in sign: prefer provisions (measures actual  |
|   balance-sheet reserve movement, not diagonal  |
|   development which can include emergence)     |
+-----------------------------------------------+
  |
  v
+-----------------------------------------------+
| Step 4c: Provisions PYD fallback               |
|   If no triangle PYD found:                    |
|     Use provisions movement note               |
|     (gross prior year claims development)      |
|   Runs before no_triangle_data check           |
+-----------------------------------------------+
  |
  v
+-----------------------------------------------+
| Step 4d: Narrative PYD parsers                 |
|   If still no PYD:                             |
|     _extract_pyd_from_provisions_text()        |
|     _parse_pyd_from_pl_narrative()             |
|     _parse_pyd_from_yoa_narrative()            |
|     _parse_pyd_from_general_narrative()        |
|   Cascade: first match wins                    |
+-----------------------------------------------+
  |
  v
+-----------------------------------------------+
| Step 5: Dual-LLM cross-validation             |
|   Gemini + GPT extract independently           |
|   _normalize_currency_fields() on each result  |
|     (remap _usd_m/_eur_m → _gbp_m)            |
|   verify_triangles() resolves disagreements    |
|   RAG triangle PYD overrides LLM values        |
|     (except loss ratio: fallback only)         |
|   RAG balance sheet opening overrides reserves |
|     (proactive: both models, always)           |
|   Net-of-reinsurance PYD fallback if null      |
|   Zero-opening override (PYD=0 if opening=0)  |
|   Direction forced from resolved PYD sign      |
+-----------------------------------------------+
  |
  v
+-----------------------------------------------+
| Step 6: Report classification                  |
|   first_year_syndicate: triangle has <3 UW years |
|   no_triangle_data: no triangle + no text      |
|   Normal: full extraction with PYD             |
+-----------------------------------------------+
  |
  v
JSON output: pdf_extraction/syndicate_NNNN_YYYY.json
```

---

## 2  Scanned PDF detection

**Function**: `_is_scanned_pdf(pdf_path, sample_pages=5)`
(`table_extraction.py`)

The pipeline first determines whether the PDF contains embedded text
or is a set of scanned page images.

1. Open the PDF with PyMuPDF.
2. Skip page 0 (often a disclaimer/cover page).
3. Extract text from pages 1 through `sample_pages` using PyMuPDF's
   native `get_text()` (no OCR).
4. Sum the character count across all sampled pages.
5. If total characters < `_MIN_TEXT_THRESHOLD` (200) per page on
   average, classify as **scanned**.

**Result**: scanned PDFs route to `_find_pages_ocr()`;
native-text PDFs route to `_find_pages_native()`.

---

## 3  Page classification

**Function**: `_classify_page(text)` (`table_extraction.py`)

Each page is tagged with zero or more content categories based on
keyword matching.  A category is assigned when **2 or more** of its
keywords appear in the page text (case-insensitive).

**Whitespace normalisation**: Before keyword matching,
`_classify_page()` applies two normalisations:

1. **NBSP**: replaces U+00A0 (non-breaking space) with regular
   spaces.  PyMuPDF often emits these, causing keywords like
   `"year later"` to fail against `"year\xa0later"`.
2. **Newlines**: replaces `\n` with spaces.  PyMuPDF's columnar
   text extraction often splits multi-word phrases across lines
   (e.g. `"years\nlater"`), preventing keywords like
   `"years later"` from matching.  This was discovered on
   syndicate 1919/2018 where the triangle page had zero keyword
   hits because every instance of "X years later" was split.

| Category          | Keywords (subset)                                                    |
|-------------------|----------------------------------------------------------------------|
| `claims_triangle` | "claims development", "development table", "cumulative gross claims", "year later", "years later", "development year", "year of account", "underlying pure year", "incurred at end of underwriting", "ultimate contract outstanding claims", "gross of reinsurance", "net of reinsurance", "12 months", "24 months", "gross claims liabilities", "total ultimate losses" |
| `provisions`      | "provision for claims", "prior year", "movement in prior", "gross provision" |
| `pl_account`      | "technical account", "profit and loss", "claims incurred"            |
| `premium_mix`     | "segmental analysis", "analysis of underwriting result", "analysis of the underwriting result", "class of business", "by class of business", "accident and health", "marine aviation", "third party liability", "reinsurance", "gross premiums written", "commissions on direct insurance" |
| `balance_sheet`   | "statement of financial position", "balance sheet", "total assets", "total liabilities", "technical provisions", "claims outstanding", "gross technical provisions" |

The `balance_sheet` category was added in v2.8 to ensure the
Statement of Financial Position page is included in the slim PDF.
Without it, LLMs could not find the opening gross claims
outstanding figure (e.g. syndicate 2003/2019 had Gemini reading
1,227m and GPT reading 5,466m instead of the correct 5,921m,
because the Balance Sheet page only matched 1 keyword in
`provisions` and needed 2+ to qualify).

The `premium_mix` category was extended to include
`"segmental analysis"`, `"analysis of underwriting result"`,
`"class of business"`, and `"by class of business"`.
Without these, monoline syndicates (e.g. syndicate 2357/Nephila,
pure reinsurance) failed page classification: their segmental
analysis page contained only one regulatory LOB name
("reinsurance"), giving just 1 keyword hit -- below the ≥2
threshold.  Adding the section heading as a keyword ensures
the page is tagged, sent to Azure for table extraction, and
included in the slim PDF for LLMs.

The `"class of business"` keywords also capture **divisional
tables** in the Managing Agent's Report (e.g. "Gross written
premium income by class of business...") which often provide a
more granular breakdown than the regulatory segmental analysis
note.  For example, syndicate 2357/2015's regulatory note has a
single "Reinsurance" LOB, but the Managing Agent's Report breaks
this into "Property Catastrophe Reinsurance", "Reinsurance",
and "Weather".

Three additional keywords were added to handle **image-based
segmental analysis tables** (e.g. syndicate 5151/2018).  When
the segmental analysis table is embedded as an image rather than
native PDF text, PyMuPDF extracts only the surrounding prose --
the section heading and a brief footer -- not the table data
itself.  The original keyword `"analysis of underwriting result"`
failed to match because the actual PDF text reads "An analysis
of **the** underwriting result".  Adding the variant
`"analysis of the underwriting result"` fixes the mismatch.
The keywords `"gross premiums written"` and `"commissions on
direct insurance"` provide additional hits from the prose that
commonly surrounds segmental analysis tables (e.g. "Commissions
on direct insurance gross premiums during 2018 were...").
Together these ensure the page reaches the >=2 keyword threshold
and is sent to Azure, whose prebuilt-layout model performs OCR
on embedded images and can extract the table structure.

The full keyword lists are in `_PAGE_KEYWORDS`
(`table_extraction.py`).

---

## 4  OCR page scanning with rotation handling

**Function**: `_find_pages_ocr(pdf_path)` (`table_extraction.py`)

**Returns**: `(page_matches, page_texts, "tesseract", rotated_pages)`

Scanned syndicate reports present three challenges:

1. **No embedded text** -- Tesseract OCR must be run on rendered page
   images.
2. **Incorrect `/Rotate` flags** -- some syndicates (e.g. 1458/2017,
   1458/2018) have landscape pages with `/Rotate=270` on content that
   is already correctly oriented, causing renderers to produce
   upside-down images.
3. **Physically rotated content** -- some syndicates (e.g. 1729/2023)
   print landscape tables sideways within portrait pages, with no
   `/Rotate` flag at all.  The content itself is rotated 90 degrees
   on the scan.

### 4.1  First pass: normal orientation

1. Open the PDF with PyMuPDF.
2. For each page, **remove the `/Rotate` flag** with
   `page.set_rotation(0)`.  This prevents incorrect rotation flags
   from inverting the rendered image.
3. Render the page at 200 DPI: `page.get_pixmap(dpi=200)`.
4. Convert the pixmap to a PIL `Image` (via PNG bytes in a
   `BytesIO` buffer).
5. Run Tesseract: `pytesseract.image_to_string(image)`.
6. Classify the OCR text with `_classify_page()`.

Previous versions used Poppler (`pdf2image.convert_from_path`) for
rendering, but Poppler honours the `/Rotate` flag, which produced
upside-down images for the affected reports.  PyMuPDF allows explicit
control over rotation before rendering.

### 4.2  Second pass: rotation retry

After the first pass, some pages may remain unclassified because
their content is **physically rotated 90 degrees** within the page
(i.e. the text itself is sideways, independent of any PDF rotation
flag).  This is common in scanned syndicate reports where the
claims development triangle is printed as a landscape table within
a portrait-sized page (e.g. syndicate 1729/2023 pages 44--45).

Normal-orientation OCR on these pages produces garbage text (e.g.
`"~9z3'89e sie |Je swilejo Bupueys}no ssou6"`) that does not match
any page-classification keywords.  Rotating the image 90 degrees
before OCR yields correct readable text.

**Trigger condition**: all unclassified, non-blank pages (text
length >= 20 characters) are retried.  The retry is not gated on
a text-quality heuristic because garbage OCR from rotated pages
can score misleadingly high on quality metrics -- reversed
alphanumeric strings still contain many long "words" and clean
characters.

For each candidate page:

1. Re-render the page at 200 DPI (reusing `page.get_pixmap()`).
2. Rotate the PIL image 90 degrees clockwise:
   `image.rotate(-90, expand=True)`.
3. Run Tesseract on the rotated image.
4. Classify the rotated text with `_classify_page()`.
5. If the rotated text produces **any** valid page categories,
   adopt the rotated text and record the page number in the
   `rotated_pages` set.

The `rotated_pages` set is returned from `_find_pages_ocr()` as
a fourth return value and passed downstream to
`_extract_pages_to_pdf()` so that the same rotation correction is
applied to the slim PDF sent to Azure/Nutrient/Adobe.

**Cost note**: the second pass re-renders and re-OCRs every
unclassified non-blank page, which can be substantial for large
scanned PDFs (e.g. 45 pages for a 51-page PDF).  This cost is
acceptable because it only applies to scanned PDFs, runs once per
report, and the OCR cache prevents re-processing on subsequent
pipeline runs.

### 4.3  OCR cache

`test_gemini.py` maintains a separate OCR cache at
`pdf_extraction/ocr_page_cache/syndicate_NNNN_YYYY.json`.  This
stores the per-page OCR text to avoid re-running Tesseract on
subsequent pipeline runs.  Delete the cache file to force re-OCR.

### 4.4  Tesseract path resolution

The pipeline checks `C:/Program Files/Tesseract-OCR/tesseract.exe`
(Windows default) and sets `pytesseract.tesseract_cmd` if found.
On Linux/macOS, Tesseract must be in `PATH`.

---

## 5  Slim PDF creation and rotation normalisation

**Function**: `_extract_pages_to_pdf(pdf_path, page_numbers,
output_path, rotated_pages)` (`table_extraction.py`)

Before calling the table extraction API, the pipeline creates a
**slim PDF** containing only the relevant pages.  This reduces API
cost by 80--90%.

### 5.1  Rotation normalisation

Two kinds of rotation are handled:

1. **Incorrect `/Rotate` flag** (e.g. `rotation=270` on content
   that is already upright).  All pages in the slim PDF have their
   rotation flag removed: `page.set_rotation(0)`.

2. **Physically rotated content** (pages in the `rotated_pages`
   set from the OCR scanner).  These are re-rendered as images
   and re-inserted with correct orientation:
   - Remove `/Rotate` flag and render at 200 DPI via
     `page.get_pixmap()`.
   - Convert to PIL `Image` and rotate 90 degrees clockwise
     (`image.rotate(-90, expand=True)`).
   - Save rotated image as PNG.
   - Create a new page in the output PDF with swapped
     width/height (`dst.new_page(width=w_pt, height=h_pt)`).
   - Insert the rotated PNG image via `new_page.insert_image()`.
   - The resulting page is image-based (no embedded text), but
     the API backend (Azure DI) can read the correctly oriented
     content.

### 5.2  Page index reconciliation (off-by-one fix)

`table_extraction.py` uses **0-indexed** page numbers throughout
(matching PyMuPDF's `doc[page_num]`).  `test_gemini.py`'s
`extract_text_from_pdf()` returns **1-indexed** page numbers
(`pages.append((i + 1, text))`).

When merging text-based page numbers (from `find_relevant_pages`)
into the API-based page set (from `table_extraction`), the
1-indexed numbers must be converted to 0-indexed:

```python
text_page_nums = set(pn - 1 for pn, _ in tri_pages + res_pages)
existing = set(result["relevant_pages"])
result["relevant_pages"] = sorted(existing | text_page_nums)
```

Without this conversion, reserve narrative pages (e.g. page 4
containing "released prior year reserves of $180.2m") were
included as page 4 instead of page 3 in the slim PDF, causing
the wrong page to be sent to LLMs.  This was discovered on
syndicate 2623/2016 where both Gemini and GPT said "no prior
year development figure found" despite the narrative being on
page 4 of the original PDF.

### 5.3  Reserve page detection patterns

`find_relevant_pages()` uses `RESERVE_MOVEMENT_PATTERNS` to
identify pages containing reserve narrative text.  A page needs
to match **2 or more** patterns to qualify.  Key patterns:

- `r"prior\s+year[\u2019\u2018']?s?\s+(reserve|claim|development|movement|provision|business)"`
  -- matches both "prior year reserve" and possessive forms like
  "prior year's business" used by run-off syndicates.  The
  apostrophe character class `[\u2019\u2018']` handles both ASCII
  `'` and Unicode curly quotes (`\u2019` right single quotation
  mark, `\u2018` left single quotation mark) that PyMuPDF
  sometimes emits from older PDFs.  Added after syndicate
  2121/2014 page 31 ("prior year\u2019s provision") failed to match
  the original ASCII-only `'?` pattern.
- `r"reserve\s+(release|strengthen|deteriorat|surplus|deficit)"`
- `r"run.?off\s+(surplus|deficit|deviation|result|improvement|deterioration|release|strengthening)"`
  -- the run-off directional terms were expanded after syndicate
  2243/2014 was missed; its text used "run-off improvement" which
  the original list (surplus|deficit|deviation|result) did not cover
- `r"prior\s+year.*release"` / `r"prior\s+year.*strengthen"`
- `r"released?\s+prior\s+year\s+reserve"` -- added for
  Beazley's phrasing ("released prior year reserves of $75.1m")
  where "released" precedes "prior year"
- `r"release\s+of\s+.{0,30}prior\s+year"` -- catches "release of
  prior year reserves" and also "release of £4.7m of prior year
  reserves" where an amount appears between "release of" and
  "prior year".  Widened from the original `release\s+of\s+
  prior\s+year` after syndicate 1945/2014 was incorrectly
  excluded -- its text "a release of £4.7m of prior year
  reserves" matched only 1 pattern (below the threshold of 2)
  because the amount "£4.7m of" broke the adjacency requirement
- `r"relating\s+to\s+prior\s+(year|underwriting)"` -- catches
  run-off syndicate language like "relating to prior year's
  business"
- `r"prior\s+years?\s+of\s+account.*?(surplus|improve|deteriorat|profit|loss)"`
  -- catches Lloyd's-specific language where reserve development
  is described in terms of "years of account" rather than "prior
  year reserves".  Added after syndicate 2121/2014 page 7 --
  "Reserves in respect of the 2011 and prior years of account
  continue to improve and develop satisfactorily, generating a
  surplus of £2.2 million." -- matched only 1 pattern without this.
- `r"(improvement|deterioration)\s+(for|in|of|on|relating)"` --
  catches directional reserve language without the word "reserve"
  or "run-off", e.g. "improvement for Syndicate 2243".  The `of`
  alternative was added after syndicate 2121/2014 page 31 --
  "An overall improvement of £1,922,000 on prior year's
  provisions" -- failed to match because the original pattern
  lacked `of` in its alternatives
- `r"(better|worse)\s+than\s+expected\s+(claims|loss|experience)"`
  -- catches expectation-based causal phrases like "better than
  expected claims experience"

The last two patterns were added after syndicate 2623/2020
failed to find its reserve narrative page (page 4), which
matched only 1 pattern (`prior year reserve`) because
"released" appeared before "prior year" in the sentence.

The run-off and expectation patterns were added after syndicate
2243/2014 was incorrectly excluded.  Its reserve text -- "The
run-off improvement for Syndicate 2243 relating to prior year's
business was £3.3m.  This was mainly attributable to the
Construction class which improved by £2.6m following better than
expected claims experience in 2014." -- matched **zero** of the
original 13 patterns because it used none of the standard UK
insurance phrasing ("favourable development", "reserve release",
etc.).  With the expanded pattern set this text matches 4
patterns.

Three further pattern fixes were made after syndicate 2121/2014
was incorrectly excluded as `no_triangle_data`.  Its page 7
describes a £2.2m surplus on prior years of account and page 31
has a provisions note reporting £1,922,000 improvement -- but
both pages scored only 1 (below the threshold of 2) because:

1. **Unicode apostrophe** -- page 31's "prior year\u2019s
   provision" used a Unicode right single quotation mark
   (`\u2019`), which the ASCII `'?` in the original pattern did
   not match.  Fix: widen to `[\u2019\u2018']?`.
2. **Missing `of` alternative** -- "improvement of £1,922,000"
   did not match `(improvement|deterioration)\s+(for|in|on|
   relating)` because `of` was absent.  Fix: add `of` to the
   alternatives.
3. **"Prior years of account" language** -- page 7's "prior years
   of account continue to improve" is standard Lloyd's phrasing
   but matched no existing pattern.  Fix: add a new pattern
   `prior\s+years?\s+of\s+account.*?(surplus|improve|deteriorat|
   profit|loss)`.

With these fixes page 7 scores 2 and page 31 scores 3.

### 5.4  Atomic file writes (Windows)

PyMuPDF's `fitz.save()` can fail on Windows when the target file
is locked by another process.  The pipeline works around this with
a temp-file-then-rename pattern:

1. Write to a `tempfile.mkstemp()` in the same directory.
2. Attempt `Path(tmp).replace(output)` (atomic on same
   filesystem).
3. Fall back to delete-then-rename if `replace()` fails.
4. Last resort: `shutil.copy2()` + delete temp.

### 5.5  Oversized slim PDF compression

Scanned PDFs (e.g. syndicate 5000/2014) contain full-page raster
images as their page content.  When `_extract_pages_to_pdf()` copies
10 such pages into the slim PDF, the result can be 100+ MB -- far
larger than the original PDF (2.4 MB) because PyMuPDF's
`insert_pdf()` preserves the raw embedded images without
recompression.

The Gemini Files API accepts the upload but `generate_content()`
rejects the request with `400 INVALID_ARGUMENT` when the content
exceeds its processing limit.

**Fix**: after writing the slim PDF, check its size against a 20 MB
threshold (`MAX_SLIM_PDF_BYTES`).  If exceeded, re-render every page
as a compressed JPEG image:

1. Open the oversized slim PDF with PyMuPDF.
2. For each page, render at 150 DPI via `page.get_pixmap(dpi=150)`.
3. Convert to PIL `Image` and save as JPEG at 75% quality.
4. Create a new page in a fresh PDF and insert the JPEG image.
5. Overwrite the temp file with the compressed version.

This reduces the slim PDF from ~100 MB to ~2--5 MB while preserving
sufficient image quality for LLM text extraction.  The compression
is safe because these are already image-based pages -- no searchable
text layer is lost.

Discovered on syndicate 5000/2014 (29 scanned pages, 10 relevant)
where the 102 MB slim PDF caused a Gemini `400 INVALID_ARGUMENT`
error.

---

## 6  Table extraction backends

**Function**: `extract_tables(pdf_path, report_year, backend,
azure_paid=False)` (`table_extraction.py`)

Three backends are supported for deterministic table extraction.
All return an `ExtractionResult` containing `triangle`, `lob`,
and `provisions` fields.

| Backend     | API                               | Speed    | Cost          |
|-------------|-----------------------------------|----------|---------------|
| **Azure**   | Azure AI Document Intelligence    | 2--5 s   | ~$0.01/page   |
| **Nutrient**| Nutrient.io                       | 5--10 s  | ~$0.05/doc    |
| **Adobe**   | Adobe PDF Extract API             | 30--60 s | ~$0.05/doc    |

Azure is the default.  The backend is selected via the
`--table-backend` CLI argument or `TABLE_BACKEND` constant.

### 6.1  Azure Document Intelligence

- Model: `prebuilt-layout`
- **Free tier (F0)**: 2 pages per API call.  Pages are split into
  batches of 2 and sent sequentially.  This is the default.
- **Paid tier (S0)**: all relevant pages sent in a single API call.
  Enabled with the `--azure-paid` CLI flag, which sets
  `azure_paid=True` on `extract_tables()`.  Reduces the number of
  API round-trips from `ceil(N/2)` to 1, which is faster for
  reports with many relevant pages (typically 4--8).
- Retry policy: 3 retries with 1-second backoff (max 10 seconds).
- Timeout: 120-second polling deadline per batch.
- Tables are extracted with row/column structure.
- Results cached in `pdf_extraction/azure_output/`.

**Usage**:

```bash
# Free tier (default): batches of 2 pages
python test_gemini.py

# Paid tier: all relevant pages in one request
python test_gemini.py --azure-paid
```

The cache key includes a `_batch_mode` field (`"paid"` or `"free"`)
so that switching between free and paid tier invalidates the cache
and forces re-extraction.  This is necessary because Azure may
detect different tables when processing 2 pages at a time versus
all pages in one request.  Caches created before this field was
added (missing `_batch_mode`) are accepted as-is for backward
compatibility, but new caches always include it.

### 6.2  Cache versioning

**Constant**: `_CACHE_VERSION` (`table_extraction.py`)

Each cached extraction result stores its cache version.  When
`_CACHE_VERSION` is bumped (after changes to extraction logic),
all stale caches are automatically re-extracted.  The cache is
validated on load against three keys:

```python
if cached_ver != _CACHE_VERSION:       # code version changed
    # re-extract from API
if cached_pages != pages_hash:         # page classification changed
    # re-extract from API
if cached_batch != batch_mode:         # free/paid tier changed
    # re-extract from API
```

---

## 7  Grid parsing

**Function**: `_parse_nutrient_triangle(grid, report_year)`
(`table_extraction.py`)

This function parses a 2D table grid (from any backend) into a
`TriangleData` object.  Despite the name, it is used for all
backends (Azure, Nutrient, Adobe).

### 7.1  Underwriting year detection

1. Scan the first 3 rows for 4-digit years matching
   `\b(19|20)\d{2}\b`.
2. Exclude cells containing `"prior"` or `"&"` (aggregate columns
   like "2010 & prior" are not individual UW years).
3. Sort by year and record column indices.
4. **Report year label exclusion**: if a year appears in column 0
   of the grid header, equals the `report_year`, and the cell
   contains only that year string (no other context), it is
   skipped.  This prevents misidentifying table title labels like
   "2021" as underwriting years (e.g. syndicate 1884/2021 where
   Azure returns `['2021', '2011 & prior', '2012', ...]`).
5. Validate: `max(uw_years)` must be within **5 years** of
   `report_year` (accommodates run-off syndicates and syndicates
   with year gaps whose last UW year may significantly precede the
   report year, e.g. syndicate 1884/2021 with max UW year 2018).
6. If fewer than 3 UW years, check whether any year is old enough
   for PYD computation (`uw_year <= report_year - 2`).  If no
   usable years exist, return `"new_syndicate"`.  If usable years
   exist (e.g. syndicate 2468/2022 with UW year 2020), the triangle
   is parsed normally — single-column triangles are valid when the
   year has enough development history.
7. If **no** UW years are found in headers, fall through to the
   transposed triangle parser (section 7.6).

### 7.2  Development row collection

Rows are classified by matching the first cell (label) against
development-period patterns:

```
"at end", "at the end", "end of underwriting"
"year later", "years later"
"^\d+ year", "^(one|two|three|...)"
"\d+ months later"
"^year\s+\d+"   (Year of Account format: "Year 1", "Year 2", ...)
```

**Skip labels** cause a row to be skipped (but collection
continues):

```
"current estimate", "cumulative payment", "outstanding", "provision"
```

**Section break labels** cause collection to **stop** (rows after
these are paid-claims or reserve-summary data, not development
periods):

```
"paid claims", "claims paid", "gross paid", "net paid",
"less gross", "less net",
"cumulative claims paid", "cumulative payments",
"cumulative gross payments", "cumulative net payments",
"claims reserve", "gross claims reserve", "net claims reserve",
"gross reserve", "net reserve",
"current estimate",
"estimate of cumulative net"
```

The `"claims paid"` and `"less gross"` / `"less net"` entries
handle rows like "Less gross claims paid" and "Less net claims
paid" that appear in run-off syndicate triangles (e.g. syndicate
1840).  Without these, the split-label continuation logic can
absorb the paid-claims row's values into the preceding
development row when that row has all-None values (dashes).

The `"cumulative gross payments"` and `"cumulative net payments"`
entries handle combined gross+net tables (e.g. syndicate 1492)
where the section header is "Cumulative gross payments to date"
rather than just "Cumulative payments".  The `"estimate of
cumulative net"` entry catches the start of a net incurred-claims
section that follows the gross section in the same table.

The text-based fallback parser (`_parse_triangle_from_text()`)
uses the same dev-period patterns plus additional stop labels for
the Year of Account format: `"cumulative claims paid"` and
`"outstanding claims reserve"`.  These appear as summary rows
immediately following the development data in Year of Account
triangles (e.g. syndicate 1880).

**"& prior" rows** (e.g. "2010 & prior years 621,803") are
skipped -- they are aggregate values, not development periods.

For each qualifying row, numeric values are extracted from the
column positions identified in step 7.1 using the
`_clean_cell_triangle()` helper, which handles accounting
conventions with triangle-specific dash semantics:

- **Parenthesised negatives**: `(123.4)` -> `-123.4`
- **Comma separators**: `2,364` -> `2364.0`
- **Standalone dashes as None**: `-`, `–` (en-dash), `—`
  (em-dash), `nil` -> `None`.  In a claims development triangle,
  a dash means "no data yet" -- the UW year has not reached that
  development period.  This is distinct from the financial-
  statement convention (see below).
- **Azure annotations**: `:unselected:` and `:selected:` suffixes
  (Azure Document Intelligence checkbox markers) are stripped
  before parsing.

**Two cell cleaners**: the codebase has two cell-value parsers:

| Function                | Dash semantics | Used by                    |
|-------------------------|----------------|----------------------------|
| `_clean_cell()`         | dash -> `0.0`  | LOB tables, provisions     |
| `_clean_cell_triangle()`| dash -> `None` | Triangle dev rows (all parsers) |

The distinction matters because in a **financial statement** (LOB
breakdown, provisions movement), a dash means nil/zero per UK
accounting convention.  But in a **triangle**, a dash means the
cell is below the staircase diagonal -- there is no data for that
UW year at that development period.  Treating these as `0.0`
would corrupt PYD computation by making the parser think claims
went to zero when in fact no observation exists yet.

**Example** (syndicate 1880/2024, UW year 2023): the "two years
later" row has a dash in the 2023 column because only one year
of development has elapsed.  With `_clean_cell()`, this would be
`0.0`, causing PYD to compute `0 - 172677 = -172677` (a massive
spurious release).  With `_clean_cell_triangle()`, it is `None`,
and the PYD computation correctly ignores this cell.

**Note**: the separate `_clean_cell()` (dash = zero) remains
necessary for LOB tables and provisions tables.  It is also used
by the **text-based** triangle fallback parser
(`_parse_triangle_from_text()`) which has its own dash handling
via regex number extraction (dashes are simply not matched by
the number regex and are skipped).  The text-based parser also
has explicit standalone-dash detection for row alignment purposes
(section 8.2.1).

### 7.2.1  Split-label row merging

Azure Document Intelligence (and occasionally other backends)
sometimes splits a multi-line cell label across two grid rows.
The most common case is the first development period label:

```
Row 1: ["at end of underwriting", "", "", "", ...]   (label part)
Row 2: ["year",                  "50,568", "81,021", ...]  (values)
```

The label `"at end of underwriting year"` is split into
`"at end of underwriting"` (matches dev-period pattern, but all
value cells are empty) and `"year"` (has the actual values, but
doesn't match any dev-period pattern on its own).

Without handling, this produces an all-None first development row
(the "at end" values are lost), which causes
`compute_pyd_from_triangle()` to fail with "oldest column has N-1
filled rows, expected N — likely shifted/misaligned".

**Fix**: after extracting values for a matched dev-period row,
if all values are `None`, the parser peeks at the next grid row.
If the next row:

1. Does **not** match any dev-period pattern itself,
2. Is **not** a section break or skip label, and
3. Has at least one non-empty value in the UW year columns,

then it is treated as a **continuation** of the split label, and
its values are used instead.  The continuation row is marked as
consumed so it is not re-processed in the main loop.

**Affected syndicates**: syndicate 1880/2024 (and potentially
other HTML-sourced reports where Playwright PDF conversion
produces multi-line cell text that Azure splits across rows).

### 7.2.2  Trailing all-null row stripping

After collecting all development rows, trailing rows where every
value is `None` are removed.  These occur when the triangle
includes development period labels (e.g. "After five years") for
periods that have no data yet because the triangle only covers a
few UW years.

Without this stripping, the trailing nulls inflate the row count
past the validation limit in `compute_pyd_from_triangle()`, which
checks `n_rows > report_year - min(uw_years) + 2`.  For example,
syndicate 1492/2018 has 4 UW years but 6 development rows
(including 2 all-null trailing rows for "After four years" and
"After five years").  The expected max is 5 rows, so the
unstripped triangle would be rejected.

### 7.3  Why section breaks matter

Many syndicate reports present both incurred claims and paid claims
in a **single Azure-detected table**.  Without section-break
detection, both sets of development rows would be collected,
doubling the row count (e.g. 20 rows instead of 10 for syndicate
1274/2020).  The paid-claims rows contain negative values that
corrupt the PYD computation.

### 7.4  Currency, unit, and type inference

After collecting development rows, the parser infers:

- **Currency**: scan grid text for "gbp"/"GBP"/"£" (GBP),
  "eur"/"EUR"/"€" (EUR), else USD.
- **Units**: if `[£$]'?000` or `'000` found, `"thousands"`;
  else default `"millions"`.
- **Type**: if `"net"` in text and `"gross"` not in text,
  `"net"`; else `"gross"`.  Gross triangles are preferred.

### 7.5  Year of Account format

Some syndicates (e.g. syndicate 1880) present their claims
development triangle using "Year of Account" column headers and
"Year N" row labels instead of the standard "12 months later" /
"1 year later" convention.

**Example** (syndicate 1880/2016):

```
Year of Account  2011    2012    2013    2014    2015    2016
                 £m      £m      £m      £m      £m      £m
Year 1           627.0   180.9   71.6    59.1    51.1    82.1
Year 2           631.8   206.0   98.5    97.9    90.7
Year 3           564.8   208.8   101.7   94.1
Year 4           558.4   205.7   97.9
Year 5           551.5   203.5
Year 6           544.9
Cumulative claims paid    537.9   172.2   76.7    62.7    28.8    11.1
Outstanding claims reserve  7.0    31.3   21.2    31.4    61.9    71.0
```

This is structurally identical to the standard format (UW years
as columns, dev periods as rows) -- only the row labels differ.
The `^year\s+\d+` pattern in `dev_period_patterns` matches
"Year 1", "Year 2", etc.  The summary rows ("Cumulative claims
paid", "Outstanding claims reserve") are caught by the existing
`skip_labels` (which includes `"outstanding"`) and
`section_break_patterns` (which includes
`"cumulative claims paid"`).

Azure Document Intelligence correctly detects the year columns
from headers like "2011 £m" because the UW year regex
`\b(19|20)\d{2}\b` matches the year portion regardless of
trailing currency/unit annotations.

### 7.6  Transposed triangle parsing (grid)

**Function**: `_parse_transposed_triangle(grid, report_year)`
(`table_extraction.py`)

Some syndicates (e.g. syndicate 1856) present their claims
development triangle in a **transposed** format where development
periods (1, 2, 3, ...) are column headers and underwriting years
are row labels.  This is the opposite of the standard format
(UW years as columns, dev periods as rows).

### 7.6.1  Format A: with "Development Year" header

**Detection**: the first header cell contains "Development Year"
and subsequent cells are integers `1, 2, 3, ...` or "Total".

**Parsing steps**:

1. Read column headers to determine the number of development
   periods.  Strip any "Total" column.
2. Read subsequent rows.  Each row's first cell is a 4-digit UW
   year; remaining cells are numeric values for each dev period.
3. **Transpose** the grid: swap rows and columns so the output
   matches the standard format (UW years as columns, dev periods
   as rows).
4. Trim trailing all-None rows (dev periods with no data for any
   UW year).
5. Infer currency, units, and type from grid text.

**Example** (syndicate 1856/2020):

```
Input grid (transposed format):
  Development Year  1        2        3        4        5     Total
  2016              57,083   59,022   95,617   95,099   45,248  ...
  2017              68,123   68,905   83,118   80,073   ...     ...
  ...

Output (standard format):
  UW years: [2016, 2017, 2018, 2019, 2020]
  Row 0: [57083, 68123, 89034, 75690, 112408]  (dev period 1)
  Row 1: [59022, 68905, 89119, 77204, None]     (dev period 2)
  ...
```

### 7.6.2  Format B: headerless (Azure table split)

**Cause**: Azure Document Intelligence sometimes splits a table's
header row and data body into two separate tables.  The header
table (e.g. `["Underlying Pure Year", "Incurred at end of
underwriting", "1 year later", ...]`) has only 2 rows and is
rejected as "too small".  The data table starts with a currency
row (`["", "$000", "$000", ...]`) followed by UW year rows --
but has no descriptive header.

**Detection**: no "Development Year" header is found, but 3 or
more rows have a bare 4-digit year in column 0.

**Parsing steps**:

1. Count rows with a 4-digit year in column 0.  Require >= 3.
2. Use all columns except column 0 as development period columns.
3. **Cumulative Payments stripping**: if the last column is fully
   populated (every UW year has a non-null value) while the
   second-to-last column has at least one null, the last column
   is a "Cumulative Payments" column, not a development period.
   Strip it before transposing.
4. Continue with the same transpose/trim/infer steps as Format A.

**Example** (syndicate 1919/2018):

```
Azure extracts two tables from the same page:

Table 1 (header only, 2 rows -- rejected as too small):
  Underlying Pure Year | Incurred at end of underwriting | 1 year later | ...

Table 2 (data body, 9 rows -- parsed as headerless transposed):
         $000     $000     $000     $000     ...  $000
  2011   175,847  299,981  286,324  279,754  ...  257,282  <-- last col = Cumulative Payments
  2012   107,509  228,009  259,497  251,951  ...  230,096
  ...
  2018   157,771  -        -        -        ...  12,645

After stripping Cumulative Payments column and transposing:
  UW years: [2011, 2012, ..., 2018]
  Row 0: [175847, 107509, ..., 157771]  (end of UW year)
  Row 1: [299981, 228009, ..., None]    (1 year later)
  ...
```

This function is invoked as a fallback from `_parse_nutrient_triangle()`
when no UW years are found in the column headers (step 7.1.6).

### 7.6.3  Format C: "Underlying Pure Year" header

**Cause**: some syndicates (e.g. syndicate 1919) use non-standard
labels for their transposed triangle.  Instead of "Development Year"
with numeric column headers (1, 2, 3, ...), they use:

- **Row label**: "Underlying Pure Year" (instead of "Year of Account")
- **First dev column**: "Incurred at end of underwriting year"
  (instead of dev period 1)
- **Subsequent columns**: "1 year later", "2 years later", etc.
  (instead of bare integers)
- **Last column**: "Cumulative Payments" (stripped before parsing)

**Detection**: the first header cell contains "Underlying Pure Year"
or "underlying".  Subsequent cells are matched against the patterns
`"incurred"`, `"end of underwriting"`, `"year later"`, and
`"years later"`.  Columns matching `"cumulative"` or `"total"` are
excluded.

**Parsing steps**:

1. Identify development period columns by matching column headers
   against the patterns above.
2. Parse UW year rows and extract numeric values (same as Format A).
3. Transpose, trim, and infer currency/units/type as usual.

**Example** (syndicate 1919/2018):

```
Input grid (Format C):
  Underlying Pure Year | Incurred at end... | 1 year later | 2 years later | ... | Cumulative Payments
  2011                 | 175,847            | 299,981      | 286,324       | ... | 257,282
  2012                 | 107,509            | 228,009      | 259,497       | ... | 230,096
  ...
  2018                 | 157,771            | -            | -             | ... | 12,645

Output (standard format, after stripping Cumulative Payments):
  UW years: [2011, 2012, ..., 2018]
  Row 0: [175847, 107509, ..., 157771]  (incurred at end of UW year)
  Row 1: [299981, 228009, ..., None]    (1 year later)
  ...
```

### 7.6.4  Format D: "Year of account" header (Lloyd's YOA)

**Cause**: many Lloyd's syndicates (e.g. syndicate 780) present
their claims development triangle in a "Year of account" format
where the first header cell is "Year of account" and subsequent
column headers are development period labels:

- "At the end of calendar year" (first development period)
- "One year later", "Two years later", ... (subsequent periods)
- "Cumulative payments" (summary column -- not a dev period)
- "Estimated balance to pay" (summary column -- not a dev period)

These tables are frequently presented in **landscape/rotated**
orientation in the PDF.  Azure Document Intelligence successfully
extracts the table grid from rotated pages, but the parser must
correctly identify which columns are development periods and which
are summary columns.

**Detection**: the first header cell contains "year of account"
(case-insensitive).  Subsequent cells are matched against the
patterns `"end of calendar"`, `"at the end"`, `"year later"`,
`"years later"`, and `"months later"`.  Columns matching
`"cumulative"`, `"total"`, `"estimated"`, or `"balance"` are
excluded.

**Why this matters**: without this detection, the parser falls
through to headerless mode (Format B), which includes all columns
as development periods.  The "Cumulative payments" and "Estimated
balance to pay" columns then become extra development rows after
transposing, causing the triangle to have too many rows (e.g. 8
rows for a 6-year span) and fail `compute_pyd_from_triangle()`'s
row count validation.

**Example** (syndicate 780/2016):

```
Input grid (Format D):
  Year of account | At the end of calendar year | One year later | ... | Five years later | Cumulative payments | Estimated balance to pay
  2010 & prior    | -       | -       | ... | -       | -         | 203.2
  2011            | 134.2   | 224.3   | ... | 236.9   | (208.9)   | 28.0
  2012            | 44.8    | 94.9    | ... | -       | (93.9)    | 15.1
  ...
  2016            | 29.2    | -       | ... | -       | (18.4)    | 10.8

Output (after excluding Cumulative payments / Estimated balance, transposing):
  UW years: [2011, 2012, 2013, 2014, 2015, 2016]
  Row 0: [134.2, 44.8, 37.9, 29.5, 21.0, 29.2]  (at end of cal year)
  Row 1: [224.3, 94.9, 78.1, 84.2, 113.2, None]  (one year later)
  ...
  Row 5: [236.9, None, None, None, None, None]    (five years later)
```

**Note**: the "2010 & prior" row is skipped because it does not
match the `r'^(19|20)\d{2}$'` year pattern.  The "Total gross
claims outstanding" row is also excluded.

### 7.7  LOB grid parsing (monoline threshold)

**Function**: `_parse_nutrient_lob(grid, report_year, page_text)`
(`table_extraction.py`)

Tables tagged as `premium_mix` are parsed for LOB (line of
business) breakdowns.  The parser validates a table as a
segmental analysis by counting how many `_LOB_KEYWORDS` appear
in the grid text.

**Normal syndicates** (3+ LOBs): require `lob_hits >= 3` to
avoid false positives from non-LOB tables that happen to
contain words like "reinsurance" or "property".

**Monoline syndicates** (1-2 LOBs): when the **page text**
(not just the grid) contains an explicit LOB table signal --
`"segmental analysis"`, `"class of business"`, or
`"analysis of underwriting result"` -- the threshold drops to
`lob_hits >= 1`.  This is necessary because the signal phrase
often appears as a section heading above the table, outside the
grid that Azure/Nutrient returns.

The `page_text` parameter is the full OCR/PyMuPDF text of the
page containing the grid, passed through from the page scan.

**Example**: syndicate 2357/2015 (Nephila, pure reinsurance).
The regulatory segmental analysis on page 25 has a single row:
"Reinsurance: $73,098k".  The grid text contains "reinsurance"
(1 LOB keyword), insufficient for the normal threshold of 3.
But the page text contains "segmental analysis", so the
threshold drops to 1 and the single-LOB breakdown is accepted.

### 7.8  Provisions and balance sheet grid parsing

**Functions**: `_parse_nutrient_provisions(grid, report_year)`,
`_parse_opening_claims_outstanding(grid, report_year)`,
`_parse_balance_sheet_claims_outstanding(grid, report_year)`
(`table_extraction.py`)

Tables tagged as `provisions` or `balance_sheet` are parsed for
three pieces of data:

#### 7.8.1  Prior year claims movement

`_parse_nutrient_provisions()` searches for a row whose label
contains `"prior"` and one of `"claim"`, `"underwriting"`, or
`"year"`.  It extracts gross, reinsurance share, and net amounts
from the corresponding columns.  Column positions are detected
from header keywords (`"gross"`, `"reinsur"`/`"share"`/`"ceded"`,
`"net"`), with a positional fallback to columns 1/2/3 if headers
are not found.

**"Claims outstanding" column detection**: some provisions tables
(e.g. syndicate 780) use a non-standard column layout:

```
31 December 2016 | Provision for unearned premiums | Claims outstanding | Total
```

In this layout, Gross/Reinsurers' share/Net are section headers
(rows), not column headers.  The actual gross claims PYD is in
the "Claims outstanding" column, not column 1 ("Provision for
unearned premiums", which is typically "-" or 0 for prior year
claims).  The parser detects "claims outstanding" in any column
header and uses that column as `gross_col` instead of the default
positional fallback.

Without this detection, the positional fallback assigns
`gross_col=1` (unearned premiums) which returns 0.0 for the
prior year row, masking the actual gross claims PYD.

Values exceeding 10,000 in absolute terms are assumed to be in
thousands and divided by 1,000 to convert to millions.

#### 7.8.2  Opening gross claims outstanding (provisions note)

`_parse_opening_claims_outstanding()` extracts the gross claims
outstanding at the start of the reporting year from provisions
movement tables or balance sheet notes.

**Detection**: the function requires both `"claims outstanding"`
and one of `"balance"`, `"1 january"`, or `"brought forward"` to
appear in the grid text.

**Two layout patterns** are handled:

**Pattern A — "Claims outstanding" as a row label** (section header):

1. Scan rows for a `"claims outstanding"` section header in
   column 0.
2. Within that section, find the `"balance at 1 january"`,
   `"brought forward"`, or `"at 1 january"` row.
3. Extract the value from the gross column.
4. Stop parsing if a different section (`"unearned premium"`,
   `"deferred acquisition"`, `"total"`) is encountered.

**Pattern B — "Claims outstanding" as a column header**:

Some syndicates (e.g. 780) present the provisions movement as a
columnar table where "Claims outstanding" is a column header,
not a row label:

```
31 December 2016 | Provision for unearned premiums | Claims outstanding | Total
                 | $                               | $                  | $
Gross            |                                 |                    |
At 1 January 2016| 109.3                           | 348.5              | 457.8
```

Pattern A fails here because no row has "claims outstanding" in
column 0.  Pattern B handles this by:

1. Scanning header rows (0--2) for a cell containing "claims
   outstanding" to identify the column index.
2. Walking rows within the "Gross" section (stopping at
   "Reinsurer", "Net", or "At 31 December").
3. Finding the "At 1 January" / "Brought forward" row and
   extracting the value from the identified column.

**Example**: syndicate 780/2016 has a provisions movement table
(Azure Table 11, page 31) with "Claims outstanding" as column 2.
The "At 1 January 2016" row has value 348.5 in that column.
Both LLMs extracted wrong values: Gemini 348.5 (correct from
balance sheet), GPT 345.2 (net closing total from page 26) /
313.8 (closing gross claims outstanding, not opening).  The
RAG-extracted `348.5m` is the correct opening gross claims
outstanding.

**Unit detection**: the function checks headers (rows 0--3) for
`"'000"`, `"000s"`, or `"thousand"`.  If found, the extracted
value is divided by 1,000 to convert to millions.  Values
exceeding 50,000 in absolute terms are assumed thousands.

**Column detection** (Pattern A only): looks for a header cell
containing `"gross"` (excluding `"net"`).  Falls back to
column 1.

**Example (Pattern A)**: syndicate 2357/2016 has a Technical
Provisions note (page 24) with:

```
Claims outstanding
  Balance at 1 January    17    -    17    -    -    -
  Change in claims ...    25,791    (3,018)    22,773    ...
```

The table is in `$'000`, so `17` → `$0.017m`.  Both LLMs
extracted wrong values for opening reserves (Gemini: 7.806m
from total technical provisions, GPT: 23.463m from member's
balances).  The RAG-extracted `0.017m` is the correct gross
claims outstanding at 1 January 2016.

#### 7.8.3  Opening gross claims outstanding (balance sheet)

`_parse_balance_sheet_claims_outstanding()` is a fallback that
extracts gross claims outstanding from the **Statement of
Financial Position** (balance sheet) when the provisions note
parser (7.8.2) returns nothing.

**Detection**: the function requires:

- `"technical provision"` in the grid text (identifies the
  liabilities section)
- `"claims outstanding"` as a **row label** (column 0) -- this
  distinguishes it from provisions movement tables where "Claims
  outstanding" appears as a column header
- Absence of `"reinsurer"` in the grid text -- this rejects the
  ASSETS-side table (reinsurers' share of claims outstanding)

**Two table patterns** are handled, covering 186/186 observed
balance sheet tables across all syndicates:

| Pattern | Prevalence | Layout |
|---------|------------|--------|
| **A: values on row** | 181/186 syndicates | `Claims outstanding  15  327,771  314,395` |
| **B: sub-header + gross** | 2/186 syndicates (4242) | `Claims outstanding` (header) then `Gross amount  14  30,740  12,121` |
| **C: header only** | 3/186 syndicates | `Claims outstanding` as column header in provisions tables (skipped) |

**Prior year column detection**:

1. Scan header rows (0--3) for a cell containing
   `str(report_year - 1)`.  If found, use that column index.
2. If no year match, identify the `"Notes"` column and collect
   all numeric values excluding the label (column 0) and notes
   column.  The last numeric value is taken as the prior year
   comparative.

**Unit detection**: checks header rows for:

- Thousands: `'000`, `\u2019000`, `000s`, `thousand`, `£000`,
  `$000` → divide by 1,000
- Millions: `£m`, `$m`, `million` → no conversion
- Neither detected: values > 50,000 are assumed thousands (no
  syndicate has >£50bn reserves); values ≤ 50,000 assumed
  already in millions

**Example**: syndicate 4242/2016 has a Statement of Financial
Position with separate ASSETS and LIABILITIES tables.  The
LIABILITIES table (Azure Table 3) contains:

```
MEMBERS' BALANCE AND LIABILITIES
  Technical provisions
    Claims outstanding
      Gross amount    14    30,740    12,121
```

The table is in `$'000`.  The prior year column (2015) value is
12,121 → `$12.121m`.  Both LLMs originally returned wrong
values: Gemini 12.121 (correct), GPT 78.049 (total technical
provisions including unearned premiums 65,928 + claims 12,121).
The ASSETS-side table showing `Claims outstanding: 911` is the
reinsurers' share and is correctly rejected by the
`"reinsurer"` filter.

**Integration**: the extracted value is stored as
`ProvisionsData.opening_gross_claims_outstanding` and included
in the `_adobe_provisions` metadata on both LLM result dicts.

**Priority chain**: the pipeline tries opening claims extraction
in this order:

1. `_parse_opening_claims_outstanding()` on provisions/balance
   sheet tagged tables (provisions movement note)
2. `_parse_balance_sheet_claims_outstanding()` on balance sheet
   **and pl_account** tagged tables (Statement of Financial
   Position liabilities)
3. Reserves movement note opening (RITC syndicates)

The first non-null result is used.  Downstream, the RAG value
is applied proactively to both LLMs (section 10.6).

**Why pl_account tables are included in step 2**: scanned PDFs
sometimes cause the page classifier to assign `pl_account`
instead of `balance_sheet` to the balance sheet page.  For
example, syndicate 780/2016 has its liabilities balance sheet
on page 12 (0-indexed 11), but the OCR-based page scanner
classified it as `[pl_account, premium_mix]`.  The balance
sheet parser's own structural checks (`"technical provision"`
in text, `"claims outstanding"` as row label, absence of
`"reinsurer"`) are sufficient to reject non-balance-sheet
tables, so the broader category match is safe.

---

## 8  Text-based triangle fallback

**Function**: `_parse_triangle_from_text(text, report_year)`
(`table_extraction.py`)

When the API backend does not detect a table (common with
certain PDF layouts), this function parses the triangle directly
from raw PyMuPDF page text.

### 8.1  Year header detection

Two strategies:

**Strategy A** -- years on a single line (e.g.
`"2014 2015 2016 2017"`).  Search for lines with >= 3 year
matches.  Exclude lines containing `"prior"`.

**Strategy B** -- consecutive lines (PyMuPDF columnar output).
Look for standalone year lines (`^(19|20)\d{2}$`).  Collect
consecutive year lines until a non-year line or `"total"`.

**Strategy C** -- transposed triangle in concatenated text.
Delegates to `_parse_transposed_triangle_from_text()` (section
8.3).  Invoked when Strategies A and B find no UW years.

### 8.2  Row grouping formula

For each development period `d` (0 = end of UW year, 1 = one
year later, ...), the expected number of values is:

```
count = sum(1 for y in uw_years if report_year - y >= d)
```

This correctly handles year gaps.  For example, if UW years are
`[2016, 2017, 2019, 2020]` and `report_year = 2020`:

| Period | Expected values |
|--------|----------------|
| d = 0  | 4 (all years)  |
| d = 1  | 2 (2016, 2017) |
| d = 2  | 1 (2016)       |

Run-off syndicates have extra development rows:
`extra_dev_years = report_year - max(uw_years)`.

### 8.2.1  Standalone dashes as zero in text parsing

Lines containing only dashes (no digits) are recognised as zero
values.  This prevents row misalignment in the grouped-values
approach.  For example, syndicate 1840's PyMuPDF text for UW year
2020 may produce:

```
18        (end of UW year)
-         (one year later — claims went to zero)
3,407     (one year later for UW 2021)
```

Without dash handling, the parser extracts `[18, 3407]` and
misattributes `3407` to UW year 2020's second development period.
With dash handling, `[18, 0, 3407]` is extracted and values are
correctly grouped per UW year.

### 8.3  Transposed triangle from text

**Function**: `_parse_transposed_triangle_from_text(text,
report_year)` (`table_extraction.py`)

When the API backend detects no table and the standard text-based
parser (Strategies A/B) finds no UW year headers, this function
handles the transposed format where PyMuPDF concatenates all text
without spaces.

**Typical input** (syndicate 1856/2019, PyMuPDF output):

```
...Development Year12345TotalYear of Account201657,73559,926117,918...
```

**Parsing steps**:

1. **Marker detection**: the text is whitespace-normalised
   (all `\s+` collapsed to single spaces) before searching for
   markers, because PyMuPDF often splits multi-word labels across
   lines (e.g. `"Underlying\nPure\nYear"`).  The function requires
   both a **development period marker** and a **UW year label
   marker**:
   - Standard: `"development year"` + `"year of account"`
   - Alternative (e.g. syndicate 1919): `"incurred at end of
     underwriting"` + `"underlying pure year"`
   Positions found in the normalised text are mapped back to the
   original text using a regex search for the phrase with flexible
   whitespace between words.
2. **Extract after UW year label**: take the text following the
   matched UW year label (`"Year of Account"` or
   `"Underlying Pure Year"`).
3. **Truncate at stop markers**: cut the text at the first
   occurrence of "current estimate", "cumulative payment",
   "cumulative gross payment", "cumulative net payment",
   "gross claims reserve", "net claims reserve",
   "gross unearned", "net unearned",
   "estimate of cumulative net", or **"net of reinsurance"**
   (the last prevents collecting values from a net triangle on the
   same page).
4. **Find UW years**: match `(19|20)\d{2}` in the after-YoA text.
   Deduplicate (a year appearing twice means both gross and net
   sections were captured -- only keep the first occurrence).
5. **Extract numbers per year**: for each UW year, extract
   comma-formatted numbers using `\d{1,3}(?:,\d{3})*`.  This
   regex correctly splits concatenated numbers like
   `"57,73559,926117,918"` into `["57,735", "59,926", "117,918"]`
   by respecting comma-formatting boundaries.
6. **Trim Total column**: compute the expected number of dev
   periods as `report_year - year + 1` and truncate extra values
   (the Total column).
7. **Transpose**: convert from row-per-year to
   row-per-dev-period format.
8. **Type inference**: default to `"gross"` unless the context
   explicitly contains `"net"` without `"gross"`.

**Why `\d{1,3}(?:,\d{3})*`?**

Standard `[\d,]+` would capture `"57,73559,926"` as a single
match.  The comma-aware regex requires that commas only appear
at valid thousand-separator positions, correctly splitting at
number boundaries.

---

## 9  PYD computation

**Function**: `compute_pyd_from_triangle(triangle_data,
report_year)` (`test_gemini.py`)

PYD (Prior Year Development) is computed in **Python** (not by
LLMs) to eliminate arithmetic errors.

### 9.0  UW year tolerance and row count validation

Before computing PYD, the function validates the triangle
structure:

1. **UW year range**: `max(uw_years)` must be within **5 years**
   of `report_year` (i.e. `report_year - 5 <= max_uw <=
   report_year`).  The 5-year tolerance supports run-off syndicates
   and syndicates with year gaps (e.g. syndicate 1884/2021 with max
   UW year 2018, or syndicate 1884/2022 with UW years
   [2013..2018, 2022]).

2. **Row count validation**: uses the development span rather than
   column count.  The maximum expected rows is:

   ```
   expected_max_rows = report_year - min(uw_years) + 2
   ```

   The `+2` provides tolerance for edge cases.  This formula
   correctly handles year-gap triangles where the number of
   development rows can exceed the number of UW year columns.
   For example, syndicate 1884/2022 has 7 UW year columns
   [2013..2018, 2022] but 10 development rows (span = 2022 -
   2013 = 9, plus tolerance).

### 9.0.1  Trailing all-null row stripping

Before any validation or computation, `compute_pyd_from_triangle()`
strips trailing rows where every value is `None`.  This is a safety
net complementing the same logic in `_parse_nutrient_triangle()`
(section 7.2.2) -- it handles cases where the triangle arrives from
a different parser (text-based fallback, LLM extraction) that did
not strip trailing nulls.

### 9.1  Diagonal extraction

For each UW year column (excluding the 2 most recent):

```
current_estimate  = last non-null value in column
previous_estimate = value one row above current_estimate
pyd_for_year      = current_estimate - previous_estimate
```

The 2 most recent UW years are excluded because they have
insufficient development history (only 1 or 2 data points).

### 9.2  Summary row detection and stripping

LLMs (and some API backends) sometimes include a "Current
estimate of cumulative claims incurred" summary row at the
bottom of the triangle.  This row duplicates the last non-null
value from each column.

**Detection**: if the last row is fully filled and >= 70% of its
values match the last non-null above, it is a summary row.

**Action**:
- If column 0 has a **different** value (real development data
  merged with summary), null only the matching columns.
- Otherwise, strip the entire row.

### 9.3  Unit auto-detection

When header-based unit detection is ambiguous or garbled, the
pipeline examines value magnitudes in the first two rows:

| Max value range       | Inferred units | Divisor    |
|-----------------------|----------------|------------|
| > 1,000,000           | Full currency  | 1,000,000  |
| > 10,000              | Thousands      | 1,000      |
| <= 10,000             | Millions       | 1          |

Auto-detection triggers when the unit string is **not** one
of the known values (`"thousands"`, `"full"`, `"percentage"`).
This catches both the default `"millions"` case and garbled
strings like `"units"` returned by some API backends.

### 9.4  Ratio sanity check

After computing PYD, the ratio `pyd / opening_reserves * 100`
is checked.  If the ratio is less than -100%, the result is
discarded -- releasing more than 100% of opening reserves
indicates a unit mismatch or misaligned triangle.

Strengthenings (positive PYD) are **not** capped at 100%.
A syndicate can legitimately strengthen reserves by more than
its opening balance -- for example if multiple catastrophe
events hit simultaneously, prior year reserves may be
increased beyond the opening figure.

The -100% check is applied in three places:

1. `_apply_triangle_pyd()` -- checks **before** setting the
   computed PYD on the result dict, preserving the original
   LLM value on rejection.
2. The RAG override path in `process_single_report()` --
   validates the RAG PYD against opening reserves before
   applying it.  When rejected, falls back to LLM-extracted
   triangles via `verify_triangles()`.
3. `_passes_sanity()` inside `verify_triangles()` -- gates
   whether a single-model triangle can be trusted.

### 9.4.1  Zero opening reserves edge case

Some syndicates (e.g. syndicate 2357/Nephila in early years)
have zero gross claims outstanding at the start of the year
and a claims development triangle that is entirely
dashes/zeros for prior underwriting years.  In this case:

- **PYD = 0** (no prior year reserves → no development)
- **PYD% = 0%** (not undefined -- zero development of zero
  reserves is definitionally zero percent)
- **Non-zero RAG PYD is rejected**: when opening reserves = 0
  and the RAG triangle computes a non-trivial PYD
  (|PYD| > 0.1m), it is discarded.  This catches cases where
  the deterministic extraction picked up a **net** triangle
  (which may have large movements) instead of the gross
  triangle (which has no prior year claims).

All PYD% calculations use a three-way branch:

```python
if pyd == 0:
    pyd_pct = 0.0        # definitionally zero
elif opening > 0:
    pyd_pct = pyd / opening * 100
else:
    pyd_pct = None        # can't compute (shouldn't reach here)
```

This applies in `_apply_triangle_pyd()`, the RAG override
path, the net fallback path, and `_passes_sanity()`.

**Post-LLM zero-opening override**: after all PYD resolution
(RAG override, triangle verification, net fallback), if
**both** models agree that opening reserves = 0, the pipeline
forces PYD = 0.0, PYD% = 0.0, and direction = "flat" on both
models.  This catches cases where an LLM misinterprets
current-year claims activity as prior year development
(e.g. GPT extracting $17k from the provisions movement note
as PYD for syndicate 2357/2015, when there were zero prior
year reserves to develop).

### 9.5  Year-value contamination detection

**Function**: `compute_pyd_from_triangle()`, year-like value
check.

When Azure (or another backend) misidentifies a segmental
analysis table or P&L breakdown as a claims development
triangle, the extracted "development rows" contain calendar
year numbers (e.g. 2001, 2013, 2014) alongside actual claims
amounts.  PYD computed from such data is nonsensical --
for example `0.1 - 2013.0 = -2012.9`.

The pipeline counts how many non-null values in the triangle
fall in the range 1980--2030 and are exact integers.  If more
than 15% of all values are year-like, the triangle is rejected:

```
triangle has 8/17 values that look like calendar years
(1980-2030) — likely a misidentified segmental table
```

Real claims development triangles never contain year numbers
as data values -- cumulative claims amounts are either very
small (millions: 1--500) or very large (thousands: 1,000--
500,000), neither of which overlaps with calendar years.

**Example**: syndicate 2001/2014 had an Azure-extracted table
from the segmental analysis page with UW years ["2001",
"2013", "2014"].  The data rows contained year labels mixed
with LOB premium amounts, producing a PYD of -2012.9m
(-130.96%).  The year-value check now rejects this triangle
before PYD computation.

### 9.6  Structure validation

`_validate_triangle_structure()` scores the triangle 0.0--1.0
based on the expected staircase fill pattern:

- Column `i` should have approximately `n_cols - i +
  extra_dev_years` filled values, where `extra_dev_years =
  max(0, report_year - max_uw_year)`.  This accounts for run-off
  syndicates whose triangles have more development rows than UW
  year columns (e.g. syndicate 1840/2024 has 3 UW years but 5
  development rows because claims continued developing 2 years
  after the last UW year).
- Allow +/- 1 tolerance for edge cases.
- Return `matches / total_checks`.

Triangles with structure score < 0.5 are rejected.

### 9.7  Loss ratio triangle detection

**Function**: `compute_pyd_from_triangle()`, loss-ratio value
check.

Some syndicates (notably Beazley syndicate 2623) present claims
development as **cumulative loss ratios** (percentages) rather
than absolute cumulative claims amounts.  When Azure or another
backend extracts such a table, every value in the grid is between
0 and 200 -- far too small to be claims amounts but consistent
with loss ratio percentages.

The pipeline counts non-null values in the 0--200 range.  If
**all** values fall in this range and the maximum value is <= 200,
the triangle is rejected:

```
triangle has all 21 values in 0-200 range (max=66.5)
— likely a loss ratio triangle, not a claims development triangle
```

The check requires at least 4 non-null values to avoid
false-positives on very sparse triangles.

Loss ratio triangles are handled separately by
`_extract_pyd_from_loss_ratio_triangle()` (section 9.8).

### 9.8  Loss ratio triangle PYD extraction

**Function**: `_extract_pyd_from_loss_ratio_triangle(page_text,
report_year)` (`test_gemini.py`)

When the standard claims triangle parser rejects a table as a
loss ratio triangle, this function attempts to extract PYD
from the loss ratio development grid combined with a "Total
ultimate losses" row.

#### 9.8.1  Header detection and page acceptance

The parser accepts a page if it contains **any** of these
header signals:

- `"claims development"` (standard header)
- `"gross ratios"` (Beazley 623 format)
- Both `"12 months"` and `"24 months"` (development period
  labels implying a triangle is present)

**Net-only page rejection**: if the page contains `"net ratios"`
but neither `"gross ratios"` nor `"gross claims development"`,
it is rejected as a net-only loss ratio page.  This prevents
the parser from reading a net triangle when the gross section
is on a different page.

#### 9.8.2  Applicability

This parser activates as Step 3b in the pipeline, after LLM
vision fails and before reserve text collection.  It only runs
when:

1. No PYD has been obtained from earlier steps (Azure triangle,
   LLM vision).
2. Triangle pages have been found by `find_relevant_pages()`.
3. The report is not classified as `first_year_syndicate`.

**Important**: the loss ratio triangle is typically at
**managed/group level** (e.g. "Beazley managed level"), not
syndicate level.  The computed PYD may differ significantly
from the syndicate-share figure in the narrative text.
Accordingly, the loss ratio PYD is marked as **fallback only**:
it fills in LLM blanks but never overrides an LLM-extracted
syndicate-level value (see section 10.3).

**Known syndicates using loss ratio triangles**: Beazley
syndicates 623 and 2623.  Syndicate 623 uses "Gross ratios" /
"Net ratios" headers; syndicate 2623 uses "Gross Claims
Development" / "Net Claims Development" headers.

#### 9.8.3  Gross/net section separation

Many reports (e.g. 2623/2016) place both gross and net claims
development on the **same page**.  The parser must only use the
gross section.  Four safeguards ensure this:

1. **Header-level rejection**: pages with `"net ratios"` but no
   `"gross ratios"` or `"gross claims development"` are rejected
   outright (see section 9.8.1).
2. **Ratio collection stop labels**: `"net claims development"`,
   `"net ratios"`, `"underwriting year - net"` (and spacing
   variants) are in the stop-labels list, so ratio parsing halts
   before the net section.
3. **Ultimates search bounded**: the "Total ultimate losses"
   search scans only lines before the first occurrence of
   "Net Claims Development".
4. **Page filtering (Step 3b)**: when concatenating multi-page
   triangle text, pages that contain `"net ratios"` but neither
   `"gross ratios"` nor `"gross claims development"` are excluded.

#### 9.8.4  UW year detection

Two strategies handle different PyMuPDF output formats:

- **Strategy A**: years on a single header line (e.g.
  `"2010ae  2011  2012  2013"`).
- **Strategy B**: years on consecutive lines (columnar PyMuPDF
  output, e.g. `"2011ae"` / `"2012"` / `"2013"` / ...).

Both strategies detect the `"ae"` suffix (meaning "and earlier")
which marks aggregate columns.  The regex
`r'\b((?:19|20)\d{2})\s*(ae?)?\b'` (Strategy A) and
`r'^((?:19|20)\d{2})\s*(ae?)?$'` (Strategy B) match both
`"2011ae"` and `"2012 ae"` (with or without a space before the
suffix).  Aggregate columns are tracked in an `ae_columns` set
and excluded from ratio grouping but included in the ultimates
column count.

**Note**: the space-tolerant regex was added to handle
syndicate 623 (Beazley), which renders "2012 ae" with a space
in PyMuPDF columnar output.

#### 9.8.5  Ratio grid parsing

After the year header, the parser collects numeric values from
the loss ratio grid:

1. Skip `%` header lines and development period labels ("12
   months", "24 months", etc.).
2. Stop at summary rows ("total ultimate", "gross claims liab",
   "net claims development", "net ratios",
   "underwriting year - net").
3. Filter values to the 0--200 range (valid loss ratios).
4. Group values into development rows based on the expected
   count per period: for period `d`, expect
   `count(UW years where report_year - year >= d)` values.

**Important**: the expected count per development row uses only
the `uw_years` list (excluding ae columns), not all columns.
Aggregate "ae" columns have no ratio data in the grid — they
only contribute a value in the "Total ultimate losses" row.
Using `all_years_sorted` (which includes ae columns) would
over-count expected values per row and consume ratios from
subsequent development periods.

#### 9.8.6  "Total ultimate losses" detection

The label may span 1--4 lines in columnar PyMuPDF output:

```
"Total ultimate losses ($m)  8,061.0  756.9 ..."   (one line)
"Total"  /  "ultimate"  /  "losses"  /  "($m)"     (four lines)
```

A state machine accumulates label tokens: state 0 (nothing) →
state 1 (seen "total") → state 2 (seen "ultimate") → start
collecting values.  Values on the same line as the label are
included.  Collection stops at "less paid", "less unearned",
"gross claims liab", or "net claims".

The collected values include `n_cols_total` entries (including
the `ae` aggregate column).  Aggregate columns are filtered out
to align with the ratio-bearing UW years.

When no "Total ultimate losses" row is found (e.g. 2623/2016,
2623/2017 which only have "Gross claims liabilities"), the
parser returns `None` and PYD falls through to LLM narrative
extraction.

#### 9.8.7  PYD computation

For each UW year (excluding the two most recent):

```
pyd_j = total_ultimate_j * (current_ratio - prev_ratio)
        / current_ratio
```

Where `current_ratio` is the last non-null value in the column
and `prev_ratio` is the value one row above.  Total PYD is the
sum across all usable UW years.

**Example** (2623/2021):

```
Loss ratio triangle: 10 UW years (2012-2021), 10 dev rows
  2012: ratio 45.8% -> 45.6% (chg -0.2pp), ult=698.2m, pyd=-3.062m
  2019: ratio 74.8% -> 69.5% (chg -5.3pp), ult=1686.4m, pyd=-128.603m
  Total PYD = -106.358m (8 UW years)
```

Note: the narrative for 2021 says "$150.8m release" at syndicate
level, while the loss ratio triangle gives -106.4m at managed
level.  The LLM narrative value is preferred (see section 10.3).

**Example** (623/2022 — "Gross ratios" header with ae column):

```
Loss ratio triangle: 10 UW years (2012ae, 2013-2022), 11 dev rows
  Header format: "Gross ratios" (not "claims development")
  ae column "2012 ae" has ultimate=1880.4m but NO ratio data
  2013: ratio 63.3% -> 62.2% (chg -1.1pp), ult=512.0m, pyd=-9.058m
  2020: ratio 66.6% -> 65.5% (chg -1.1pp), ult=1680.8m, pyd=-28.239m
  Total PYD = +27.771m (8 UW years, gross strengthening)
```

Note: the narrative reports net PYD of -$9.3m (release) while
the gross loss ratio triangle gives +$27.8m (strengthening).
Reinsurance absorbed the gross strengthening and produced a
net release.  The pipeline correctly uses the gross figure.

---

## 10  Dual-LLM cross-validation

**Function**: `verify_triangles()` (`test_gemini.py`)

After deterministic extraction, Gemini and GPT independently
extract all structured fields from the PDF.  Their outputs are
compared field-by-field.

### 10.1  Field tolerances

| Field                           | Tolerance              |
|---------------------------------|------------------------|
| `prior_year_development_gbp_m`  | Within +/- 2.0m or 5%  |
| `opening_reserves_gbp_m`        | Within +/- 5%          |
| `gross_premiums_written_gbp_m`  | Within +/- 5%          |
| `prior_year_development_pct`    | Within +/- 1.0pp       |
| `direction`                     | Exact match            |
| `gross_premium_mix`             | Fuzzy LOB names, +/- 10% amounts |

### 10.2  Triangle PYD resolution

When both models extract triangles:

1. Compute PYD from each triangle in Python.
2. Score each triangle's structure.
3. **Both agree** (difference < 1m): use average, apply to both.
4. **Disagree**: pick the triangle with better structure score.
   If scores are similar (+/- 0.1), skip both (insufficient
   confidence).
5. **Only one has triangle**: use it if it passes sanity checks.

### 10.3  RAG override priority

When the deterministic table extraction produces a valid PYD,
it **always replaces** both LLM-extracted values -- regardless
of how close the LLM value is to the triangle value.  The RAG
triangle is computed deterministically from the claims
development table and is authoritative over any LLM-extracted
figure.

**Exception -- loss ratio triangles**: when the RAG PYD comes
from a loss ratio triangle (`method = "loss_ratio_triangle"`),
it is treated as **fallback only**.  Loss ratio triangles are
typically at managed/group level (e.g. "Beazley managed level")
rather than syndicate level.  The managed-level PYD can differ
from the syndicate-share figure in both magnitude and
direction.

- If an LLM extracts a PYD value from narrative text (e.g.
  "the syndicate released prior year reserves of $150.8m"),
  that syndicate-level value is **kept** -- the loss ratio
  PYD does not override it.
- If both LLMs return null PYD, the loss ratio PYD is used
  as a fallback, with a `data_quality_notes` annotation:

  ```
  [MANAGED LEVEL: PYD from loss ratio triangle is at
  managed/group level, not syndicate share. May differ
  from syndicate-level figure.]
  ```

**Sanity gate**: before applying, the RAG PYD is checked
against opening reserves.  If `pyd / opening_reserves < -100%`
(i.e. a release exceeding the entire opening balance), the
RAG PYD is discarded and the pipeline falls back to
`verify_triangles()` for LLM-based resolution.  This catches
cases where a non-triangle table (e.g. segmental analysis)
was misidentified as a claims triangle by the API backend.

This unconditional override (for non-loss-ratio triangles)
is necessary because LLMs sometimes extract PYD from the
wrong source (e.g. P&L "gross change in provision" which
includes current-year claims movements, or "net provision
for claims outstanding" which is after reinsurance).  These
wrong-source values can be numerically close to the correct
triangle PYD by coincidence, so a tolerance-based check would
let them through.

When the LLM value differs from the RAG value by >= 0.5m,
the override is recorded in `data_quality_notes`:

```
[RAG OVERRIDE: Model said PYD=17.22, RAG triangle computed
17.581. Using RAG value.]
```

When the difference is < 0.5m, the RAG value still replaces
the LLM value but is logged as "confirmed" rather than
"overridden" (no note added to `data_quality_notes`).

### 10.4  Net-of-reinsurance PYD fallback

**Function**: `_parse_net_pyd_from_text()` (`test_gemini.py`)

Some reports (especially smaller or older syndicates) only
disclose prior year reserve movements **net of reinsurance**
in their narrative text, with no gross movement note, no
gross claims development triangle, and no loss ratio table.
Previously these reports would have `prior_year_development_gbp_m:
null` despite both LLMs finding and quoting the net figure
in `exact_reserve_text`.

The pipeline now applies a last-resort fallback **after** all
other PYD sources have been tried (RAG triangle, LLM-extracted
triangles, provisions note):

1. Check whether both LLMs returned `prior_year_development_gbp_m:
   null`.
2. Check whether `exact_reserve_text` contains a quantified
   reserve movement (e.g. "reserve release of GBP 1.3m net of
   reinsurance").
3. Parse the amount and sign from the narrative text using
   `_parse_net_pyd_from_text()`.
4. If successful, fill in the PYD value and compute the
   percentage against opening reserves.

**Source priority chain** (highest to lowest):

| Priority | Source | Gross/Net |
|----------|--------|-----------|
| 1 | RAG deterministic triangle PYD | Gross |
| 2 | LLM-extracted "Movement in prior year's provision" note | Gross |
| 3 | LLM-extracted narrative text (gross amount) | Gross |
| 4 | LLM-extracted year-of-account result breakdown | Net* |
| 5 | LLM-extracted loss ratio development table | Gross |
| 6 | Narrative text net-of-reinsurance figure (parsed post-hoc) | Net |

\* Year-of-account results are inherently net of reinsurance.

When the net fallback is used, a `[NET FALLBACK]` note is
appended to `data_quality_notes`:

```
[NET FALLBACK: No gross PYD available. Using net-of-reinsurance
figure (-1.300m) from narrative text.]
```

**Supported text patterns** (case-insensitive):

- "reserve release of GBP 1.3m"
- "release of £1.3m"
- "strengthening of GBP 2.9m"
- "GBP 1.3m net release"
- "£2.9m strengthening"

Sign is determined from context words near the match
("release"/"surplus" → negative, "strengthening"/"deterioration"
→ positive).  If context is ambiguous, the `direction` field
from the LLM extraction is used as tiebreaker.

**Example**: syndicate 1910/2014 reports "a reserve release of
GBP 1.3m (2013: strengthening GBP 2.9m) net of reinsurance was
made from prior year reserves."  No gross triangle or movement
note exists.  The fallback parser extracts -1.3 (release) and
computes -1.86% of the £69.876m opening reserves.

### 10.5  Direction forcing from PYD

After all PYD resolution (RAG override, triangle verification,
net fallback, zero-opening override), the pipeline forces the
`direction` field on **both** models to match the resolved PYD
sign:

| PYD value | Forced direction |
|-----------|------------------|
| `0`       | `"flat"`         |
| `< 0`     | `"release"`      |
| `> 0`     | `"strengthening"`|

This runs **before** the comparison/tolerance check
(`compare_results`), so any LLM-reported direction that
contradicts the PYD is overridden before it can cause a hard
failure.

**Rationale**: the triangle-computed PYD is the authoritative
source of truth for the magnitude and sign of reserve
development.  The LLM `direction` field is a textual
interpretation that can be wrong (e.g. GPT reporting
"strengthening" when PYD = 0 for a zero-claims syndicate).
Forcing direction from PYD eliminates these spurious
disagreements.

Previously, direction disagreements (e.g. `null` vs `"flat"`)
were handled by `resolve_computed_fields()` after the
comparison.  That auto-resolution remains as a safety net for
cases where PYD is null on both models, but the upstream
direction-forcing step handles the common case.

### 10.6  Opening reserves from RAG provisions / balance sheet

The pipeline applies RAG-extracted opening reserves at **two
stages**: proactively before cross-validation, and as a fallback
during disagreement resolution.

#### 10.6.1  Proactive RAG override (both models)

After LLM extraction completes, the pipeline checks whether
`_adobe_provisions` contains an `opening_gross_claims_outstanding`
value (from sections 7.8.2 or 7.8.3).

If available, the RAG value **overrides both models regardless
of whether they agree**:

1. Both models' `opening_reserves_gbp_m` are set to the RAG
   value.
2. `prior_year_development_pct` is recomputed using the
   corrected opening reserves.
3. If the override differs from the LLM value by >= 0.5m, a
   `[RAG OVERRIDE]` note is appended to `data_quality_notes`.

This is analogous to the RAG triangle PYD override (section 9)
-- the deterministic extraction is authoritative over LLMs.

**Log messages**:

```
  [gemini-2.5-flash] Opening reserves confirmed by RAG balance sheet: 12.121 -> 12.121m
  [gpt-5-mini] Opening reserves overridden by RAG balance sheet: 78.049 -> 12.121m
```

#### 10.6.2  Disagreement fallback resolution

**Function**: `resolve_computed_fields()` (`test_gemini.py`)

If the proactive override did not fire (no RAG value was
available at that stage) and the two LLMs disagree on
`opening_reserves_gbp_m` beyond the 5% tolerance (a hard
failure), the pipeline re-checks `opening_gross_claims_outstanding`
from the provisions dict.

If available, the RAG value overrides both models and the hard
failure is reclassified as auto-resolved.  This path handles
cases where the RAG value was injected late (e.g. from a
reserves movement note for RITC syndicates).

#### 10.6.3  Rationale and common LLM errors

LLMs frequently confuse opening reserves with other balance
sheet figures:

| Wrong source | What it actually is |
|--------------|---------------------|
| Member's balances | Equity, not claims reserves |
| Total technical provisions | Includes unearned premiums |
| Net claims outstanding | After reinsurance deduction |
| Reinsurers' share (assets) | Only the ceded portion |

The RAG value comes from one of two deterministic sources:

1. **Provisions movement note** (section 7.8.2): the "Balance at
   1 January" row within the "Claims outstanding" section.
2. **Balance sheet liabilities** (section 7.8.3): the prior year
   column of "Claims outstanding -- Gross amount" under
   "Technical provisions" in the Statement of Financial Position.

Both are definitive sources for gross opening claims reserves.

**Example 1** (provisions note): syndicate 2357/2016.  Gemini
extracted 7.806m (total technical provisions = unearned premiums
7,789 + claims outstanding 17, in $'000).  GPT extracted 23.463m
(member's balances).  RAG provisions note gives $0.017m.

```
Auto-resolved opening_reserves_gbp_m using RAG provisions table: 0.017m
  gemini-2.5-flash: 7.806, gpt-5-mini: 23.463, RAG: 0.017
```

**Example 2** (balance sheet): syndicate 4242/2016.  Gemini
extracted 12.121m (correct).  GPT extracted 78.049m (total
technical provisions including unearned premiums).  RAG balance
sheet gives $12.121m from the LIABILITIES-side "Claims
outstanding -- Gross amount" prior year column.

```
  [gemini-2.5-flash] Opening reserves confirmed by RAG balance sheet: 12.121 -> 12.121m
  [gpt-5-mini] Opening reserves overridden by RAG balance sheet: 78.049 -> 12.121m
```

### 10.7  Currency field normalization

**Function**: `_normalize_currency_fields()` (`test_gemini.py`)

The LLM prompt uses `_gbp_m` as the canonical field suffix for
**all** monetary fields regardless of the report's actual
currency.  A separate `currency` field records the true
denomination (GBP, USD, or EUR).  This convention keeps
downstream comparison and auto-resolution logic simple -- all
monetary fields have a single, predictable name.

However, some LLMs (notably Gemini) rename the fields to match
the report's currency.  For a USD-denominated syndicate, Gemini
may return `opening_reserves_usd_m` instead of
`opening_reserves_gbp_m`, `prior_year_development_usd_m`
instead of `prior_year_development_gbp_m`, etc.  When the other
LLM (GPT) follows the schema correctly, the field-by-field
comparison sees `<MISSING>` vs a value for each currency
variant, producing spurious hard failures even though both
models extracted the same number.

**Normalization** runs immediately after LLM extraction and
before any RAG override, triangle verification, or
cross-validation:

1. Scan all top-level keys for `_usd_m` or `_eur_m` suffixes.
2. For each match, rename to the corresponding `_gbp_m` key
   (e.g. `opening_reserves_usd_m` → `opening_reserves_gbp_m`).
   If the `_gbp_m` key already has a value, the variant is
   simply removed (the canonical value takes precedence).
3. Repeat for nested list-of-dicts fields: `lob_movements`,
   `named_events`, `prior_year_events`, `gross_premium_mix`
   (e.g. `amount_usd_m` → `amount_gbp_m`,
   `net_loss_eur_m` → `net_loss_gbp_m`).

**Log message** (only when renaming occurs):

```
  [gemini-2.5-flash] Normalized currency field names → _gbp_m
```

**Example**: syndicate 623/2015 (USD-denominated Beazley
syndicate).  Before the fix, Gemini returned:

| Field (Gemini) | Field (GPT) | Result |
|----------------|-------------|--------|
| `opening_reserves_usd_m: 705.7` | `opening_reserves_gbp_m: 705.7` | Hard failure (MISSING vs value on each variant) |
| `prior_year_development_usd_m: -40.3` | `prior_year_development_gbp_m: -40.3` | Hard failure |
| `gross_premiums_written_usd_m: 379.8` | `gross_premiums_written_gbp_m: 329.3` | Hard failure |

After normalization, Gemini's fields are remapped to `_gbp_m`:

| Field | Gemini | GPT | Result |
|-------|--------|-----|--------|
| `opening_reserves_gbp_m` | 705.7 | 705.7 | Match |
| `prior_year_development_gbp_m` | -40.3 | -40.3 | Match |
| `gross_premiums_written_gbp_m` | 379.8 | 329.3 | Real discrepancy (USD amount vs Adobe LOB GBP amount) |

The first two spurious hard failures are eliminated.  The
third is a genuine discrepancy (Gemini extracted the USD GWP
from the report narrative while GPT/Adobe extracted the GBP
equivalent from the segmental analysis).

---

## 11  Report classification

Reports are classified before expensive API calls to save cost.
Two independent checks run in sequence; the first to match wins.

### 11.1  Inception year check (Step 0)

**Functions**: `is_early_year_syndicate()`, `get_inception_year()`,
`_lookup_inception_year_perplexity()` (`test_gemini.py`)

Before PDF reading, the pipeline checks whether the report falls
within the syndicate's first two underwriting years.  A syndicate
needs at least 3 development periods before prior year development
can be meaningfully separated from current year activity.

**Decision rule**: flag (but do not skip) when
`report_year < inception_year + 2`.  The flag is stored in
`inception_skip` and validated against the actual triangle in
the RAG extraction step.  If the triangle contradicts the cache
(i.e. it has UW years older than the cached inception year), the
cache is corrected and extraction proceeds normally.  This
prevents incorrect Perplexity lookups from permanently blocking
reports that have valid triangles.

**Manual overrides**: syndicates listed in the `_manual_overrides`
array in the cache file are protected from all automatic updates.
Neither Perplexity lookups, triangle backfill, nor cache correction
will overwrite their inception year.  Use this for syndicates where
the automatically-determined inception year is known to be wrong
and has been manually corrected.  See "Cache file format" below.

**Inception year lookup** (in priority order):

1. **Local cache** -- `pdf_extraction/syndicate_inception_years.json`
   stores `{"syndicate_number": first_uw_year}` pairs.  Populated
   from claims development triangles (earliest UW year across all
   reports for a syndicate).
2. **Perplexity API** -- if a syndicate is not in the cache, the
   pipeline queries Perplexity (`sonar` model) with a structured
   JSON request.  The prompt asks for a JSON object:
   ```json
   {
     "syndicate_number": 2001,
     "first_underwriting_year": 1997,
     "confidence": "high",
     "source": "Lloyd's syndicate directory"
   }
   ```
   The prompt explicitly warns that syndicate numbers are not
   necessarily the same as inception years.  Validation checks:
   - **Confidence filter**: answers with `"confidence": "low"` are
     rejected.  Medium and high confidence answers are accepted.
   - **Range check**: year must be between 1688 and 2030.
   - **Sanity check vs reports on disk**: if the returned year is
     later than the earliest report we have for the syndicate, the
     answer is clearly wrong (a syndicate can't have reports before
     it started).  In that case, the pipeline falls back to
     `earliest_report_year - 2` as a conservative estimate.
   - **JSON parse fallback**: if Perplexity returns free text
     instead of JSON, a regex extracts the first 4-digit year.
   Cost: ~$0.001 per query; each syndicate is queried at most once.
3. **Triangle detection** -- if the RAG-lite extraction later finds
   a triangle with <= 2 UW years, the pipeline updates the cache
   with `inception_year = report_year - 1` as a conservative
   estimate (for syndicates not already in the cache and not in
   `_manual_overrides`).

**When the inception year is unknown** and Perplexity is
unavailable (no API key, network error), the check is skipped and
the report proceeds to normal extraction.

**Cache file format** (`syndicate_inception_years.json`):

```json
{
  "_meta": {
    "description": "First underwriting year for each syndicate...",
    "source": "Auto-populated from triangles + Perplexity lookups",
    "last_updated": "2026-03-17"
  },
  "_manual_overrides": [1110, 2001],
  "1084": 2011,
  "1110": 2012,
  "1322": 2022,
  "1609": 2021,
  "1991": 2013,
  "2001": 1993
}
```

The `_manual_overrides` array lists syndicate numbers whose inception
years have been manually verified and must not be changed by any
automated process.  To protect a syndicate:

1. Correct its inception year value in the JSON file
2. Add its syndicate number to the `_manual_overrides` array

All automated update paths (`_load_inception_years()` backfill,
`get_inception_year()` Perplexity lookup, triangle correction in
`process_single_report()`, and triangle learning) check this list
before writing.

### 11.2  First-year syndicate (triangle-based detection)

The RAG-lite extraction always runs (regardless of the inception
year flag) and may detect a triangle with fewer than 3
underwriting years.  This is a second line of defence for
syndicates not yet in the inception cache.

**Cache correction**: if the inception cache flagged the report
for skipping but the RAG extraction finds a triangle with usable
UW years, the cache is corrected to `min(underwriting_years)` and
extraction proceeds normally.  Syndicates in `_manual_overrides`
are never corrected -- extraction still proceeds (the skip flag
is cleared) but the cached inception year is preserved.

Correction log (normal syndicate):
```
[Inception] Cache said inception=2018 (would skip),
but triangle shows UW years back to 2011 -- correcting cache
```

Correction log (manual override syndicate):
```
[Inception] Triangle shows UW years back to 2011,
but syndicate 1110 has manual override (2012) -- keeping manual value, not skipping
```

The check uses **usable years**, not raw UW year count:

- A UW year is "usable" for PYD if `uw_year <= report_year - 2`
  (i.e. there is a previous diagonal to compare against)
- If the triangle has < 3 UW years **and** no usable years exist
  → `first_year_syndicate = True`
- If the triangle has < 3 UW years **but** usable years exist
  → the triangle is parsed normally and PYD is computed

**Example**: syndicate 2468/2022 has a single-column triangle
(UW year 2020).  Since 2020 ≤ 2022 − 2 = 2020, the year is
usable.  The pipeline extracts the triangle (29,267 → 28,431 →
28,278 in £'000) and computes PYD = −0.153m (a release).

When `first_year_syndicate` is triggered:

- The inception cache is updated with the estimated inception year
- LLM extraction is **skipped** (saves API cost)
- LOB breakdown is still extracted if available
- Output JSON: `{"first_year_syndicate": true, ...}`

### 11.3  Provisions PYD fallback

Before checking for `no_triangle_data`, the pipeline attempts to
use the **provisions movement note** as a PYD source.  If no
triangle PYD was computed (Step 4) and the report is not a
first-year syndicate, the pipeline checks for a gross prior year
claims development figure extracted from the provisions note
(`_parse_nutrient_provisions()`, section 7.8).

If `adobe_provisions.gross_prior_year_claims` is available, it is
used as the PYD value with `method: "provisions"` and
`pyd_details: "from provisions movement note"`.  This prevents
reports from being excluded when a valid provisions note exists
but no claims development triangle was found.

**Example**: syndicate 2791/2024 has no claims development
triangle in the report (Azure detected only P&L/premium tables),
but the provisions movement note on page 49 discloses gross
prior year claims development of −27.986m.  Without this
fallback, the report would be flagged as `no_triangle_data` and
excluded.

**RITC caveat**: for syndicates that accept Reinsurance to Close
(RITC) from other syndicates, the provisions note PYD may differ
significantly from a triangle-derived PYD.  The provisions note
includes RITC-acquired reserves in the prior year movement,
while the triangle only tracks organic development.  When both
sources are available and agree in sign, the triangle PYD takes
precedence (per RAG authority rules in section 10).  When they
disagree in sign, provisions takes precedence (per the cross-
validation in section 11.3.1).  The difference is logged but not
treated as an error.

**Example**: syndicate 2791/2024 accepted RITC from syndicate
6103.  Both LLMs independently extracted PYD ≈ −67.6m (matching
the provisions note including RITC), but the RAG triangle
computed −28.0m (organic development only).  The RAG triangle
value was used, and the RITC distortion was noted in
`data_quality_notes`.

### 11.3.1  Triangle vs provisions cross-validation (Step 4b)

After both triangle PYD and provisions PYD are extracted, the
pipeline cross-validates them.  The triangle diagonal PYD and the
provisions gross PYD can measure different things:

- **Triangle diagonal PYD** (`compute_pyd_from_triangle()`):
  computes the change in cumulative claims estimates between the
  current and previous diagonals.  Excludes the two most recent
  UW years.  For Lloyd's "Year of account" triangles, the
  diagonal differences for semi-mature years (2--3 years old) can
  include significant normal premium-earning development, not just
  reserve re-estimation.

- **Provisions gross PYD** (`_parse_nutrient_provisions()`):
  extracts the "prior year" movement from the provisions note on
  the balance sheet.  This directly measures the change in gross
  claims outstanding attributable to prior years as disclosed in
  the accounts.

**Cross-validation rule**: when both are available and they
**disagree in sign** (one is a release, the other a
strengthening), the provisions figure is preferred.  A sign
disagreement is a strong signal that the triangle diagonal is
contaminated by normal emergence in immature years, or that the
triangle is missing prior-year aggregate rows that contribute to
the provisions figure.

The override is logged:

```
[Azure] Triangle PYD (+24.900m) disagrees in sign with provisions (-15.6m) -- using provisions
```

When they agree in sign (both positive or both negative), the
triangle PYD is kept regardless of magnitude difference.  The
triangle is still considered the primary source because it is
computed deterministically from the raw data.

**Trigger conditions**: the cross-check only runs when:

1. `result["pyd"]` is not None (triangle PYD was computed)
2. `result["method"]` is a table-extraction method (`"azure"`,
   `"nutrient"`, or `"adobe"`)
3. Provisions `gross_prior_year_claims` is available and non-zero

**Example** (syndicate 780/2016):

The triangle diagonal PYD is +24.9m (cumulative claims estimates
rose for 2011--2014 UW years), but the provisions note reports
gross prior year claims movement of −15.6m (a release).  The
sign disagreement triggers the override, and −15.6m is used.
Both LLMs independently extracted −15.6m and −17.1m, confirming
the provisions figure.

**Example** (syndicate 33/2024):

The triangle diagonal PYD is −53.2m (release) and provisions is
−183.8m (also a release).  Same sign, so no override -- the
triangle PYD is kept.  The magnitude difference is expected
because provisions includes development from the two most recent
UW years that the triangle excludes.

### 11.3.2  Narrative PYD parsers (Step 4d)

After the provisions PYD fallback, the pipeline runs four
text-based parsers in cascade order on reserve movement pages.
Each parser targets a different phrasing convention used across
Lloyd's syndicate reports.  The first parser to return a value
wins.

| Parser | Method tag | Required keywords | Pattern |
|--------|-----------|-------------------|---------|
| `_extract_pyd_from_provisions_text()` | `provisions_text` | provisions-style table text | Tabular "prior year" claims rows |
| `_parse_pyd_from_pl_narrative()` | `pl_narrative` | "includes" + "prior" | "includes £34,490k of releases in respect of prior accident years" |
| `_parse_pyd_from_yoa_narrative()` | `yoa_narrative` | "prior year" + "movement" | "Prior year movements of £5.8m" |
| `_parse_pyd_from_general_narrative()` | `general_narrative` | "prior year" | "release of £4.7m of prior year reserves" |

The **general narrative parser** is a catch-all added after
syndicate 1945/2014 was incorrectly excluded as
`no_triangle_data`.  The report's reserve text -- "As a result
of favourable experience during 2014, there has been a release
of £4.7m of prior year reserves" -- did not match either the
P&L narrative parser (no "includes" keyword) or the YOA
narrative parser (no "movement" keyword).

The general parser matches two pattern families:

- **Pattern A**: `{release/strengthening} of £AMOUNT ... prior year`
  - "a release of £4.7m of prior year reserves"
  - "strengthening of £12.3m in prior year claims reserves"
- **Pattern B**: `£AMOUNT ... {release/strengthening} ... prior year`
  - "£4.7m release on prior year reserves"

Sign convention: "release" → negative (favourable),
"strengthening"/"adverse development" → positive (adverse).

Unit detection follows the same logic as the P&L and YOA
parsers: explicit `k`/`m` suffix, or context-based detection
from `'000`/`thousands` keywords on the page.

**Example**: syndicate 1945/2014 -- PYD = −4.700m (release),
extracted from "release of £4.7m of prior year reserves" via
`method: "general_narrative"`.  Both LLMs independently
confirmed the same value.

### 11.4  No-triangle-data exclusion

Reports where no claims triangle, no provisions PYD, and no
reserve movement text can be found **and** the report is not in
the first two UW years:

- `no_triangle_data = True`, `excluded = True`
- LLM extraction is **skipped**
- Recommended for non-inclusion in downstream analysis
- Common in run-off syndicate reports from years when no
  triangle was published

**Important**: `no_triangle_data` is only used for reports
outside the first two underwriting years.  Reports in the first
two years are classified as `first_year_syndicate` instead, even
if no triangle is found, because the absence of data is expected
and the reason is known (insufficient underwriting history).

---

## 12  Run-off syndicate handling

Run-off syndicates (e.g. syndicate 1110) stopped writing new
business but their claims continue developing.  Their triangles
differ from active syndicates:

- **Fewer UW year columns** than active syndicates.
- **More development rows than columns** (claims continue
  developing after the last UW year).
- **Max UW year < report year** (e.g. max UW year 2022 in a
  2023 report).

The pipeline accommodates this with:

```python
extra_dev_years = report_year - max_uw_year
min_uw = min(uw_years)
expected_max_rows = report_year - min_uw + 2  # development span + tolerance
```

The max UW year validation accepts any value within **5 years** of
the report year: `report_year - 5 <= max_uw_year <= report_year`.
This supports syndicates with extended gaps between their last UW
year and the report year (e.g. syndicate 1884 which stopped writing
in 2018 but resumed in 2022, producing a gap in UW years).

### 12.1  Year-gap triangles

Some syndicates have non-contiguous UW years due to periods of
inactivity.  Syndicate 1884, for example, is a legacy reinsurer
that stopped writing policies in 2019--2021 and resumed in 2022.
Its triangles have columns like [2014, 2015, 2016, 2017, 2018,
2022, 2023] with the gap years absent.

These triangles have more development rows than UW year columns
because the oldest UW years span the full development period
including the gap years.  For syndicate 1884/2023, there are 7
UW year columns but 10 development rows (span = 2023 - 2014 =
9, plus the end-of-year row).  The row count validation uses
`report_year - min(uw_years)` (the development span) rather than
`len(uw_years)` (the column count) to correctly validate these
triangles.

**PYD computation with gap years**: the two most recent UW years
are excluded as usual.  For syndicate 1884/2023 this means UW
years 2022 and 2023 are excluded -- 2022 has only 2 development
periods (still an open YOA, not prior year development) and 2023
has only 1.  PYD is computed from UW years 2014--2018 only.

### 12.2  Aggregate columns ("2013 & prior")

Gap-year syndicates often include an aggregate column (e.g.
"2013 & prior") that groups all UW years before the triangle's
individual columns.  This column has **no values in the
development rows** -- only a value in the summary row
("Cumulative estimate of gross cumulative claims cost").

**Impact on Azure extraction**: Azure Document Intelligence
correctly detects this column as part of the table grid, but
when `compute_pyd_from_triangle()` validates the triangle, the
aggregate column (as column 0) has `col0_filled = 0`, which is
far below `expected_col0 = min(n_rows, n_cols)`.  This triggers
the validation failure: `"oldest column has 0 filled rows,
expected N -- likely shifted/misaligned"`.

**Fallback path**: the failed Azure PYD triggers the LLM vision
fallback.  Gemini receives the triangle page as an image, reads
the triangle excluding the aggregate column, and computes PYD
from the diagonal differences.  The resulting PYD is used as the
RAG triangle value.

This is the expected flow for gap-year syndicates with aggregate
columns -- the aggregate column is not a real UW year and should
not be included in PYD computation.  The LLM vision correctly
handles this by treating the aggregate column as metadata rather
than a development column.

---

## 13  Caching strategy

| Cache location                                 | Content                        | Invalidation                            |
|------------------------------------------------|--------------------------------|-----------------------------------------|
| `pdf_extraction/syndicate_inception_years.json`| First UW year per syndicate    | Edit file directly; auto-updated by Perplexity lookups. Add syndicate to `_manual_overrides` to prevent auto-updates |
| `pdf_extraction/azure_output/`                 | Azure API table grids          | `_CACHE_VERSION`, page set, batch mode  |
| `pdf_extraction/nutrient_output/`              | Nutrient API responses         | `_CACHE_VERSION` bump                   |
| `pdf_extraction/adobe_output/`                 | Adobe PDF Extract results      | `_CACHE_VERSION` bump                   |
| `pdf_extraction/llm_cache/`                    | LLM API responses              | SHA-256 of prompt content               |
| `pdf_extraction/ocr_page_cache/`               | Tesseract OCR text per page    | Delete file to re-OCR                   |

LLM cache keys are computed from `(model, prompt_version,
prompt_text + content_hash, syndicate, year)`.  Changing the
prompt text, bumping `PROMPT_VERSION`, or changing the slim
PDF page set (which changes `content_hash`) auto-invalidates
affected entries.

**v2.10 content_hash fix**: prior to v2.10, the LLM cache
key did not include the slim PDF content hash.  This meant
that changes to the page set (e.g. the off-by-one fix that
added reserve narrative pages to the slim PDF) did not
invalidate the LLM cache -- stale responses from the old
slim PDF were served.  The fix appends the SHA-256 content
hash of the slim PDF to `prompt_text` before hashing,
ensuring any change to the slim PDF invalidates the cache.

**Azure cache and page set changes**: Azure caches also store
a `_pages_hash` derived from the set of relevant page numbers.
When page classification changes (e.g. adding the
`balance_sheet` category), the page set changes for affected
reports, automatically invalidating their Azure cache without
needing a `_CACHE_VERSION` bump.

**v2.8 cache invalidation**: `PROMPT_VERSION` was bumped from
2.7 to 2.8 when the `balance_sheet` page category was added.
This forces LLM re-extraction so Gemini and GPT receive the
updated slim PDF containing the Balance Sheet page.

---

## 14  Output format

### 14.1  Normal report

```json
{
  "extraction_timestamp": "2025-03-15T10:30:00+00:00",
  "source_file": "syndicate_reports/pdfs/syndicate_1274_2020.pdf",
  "models": {
    "gemini-2.5-flash": {
      "syndicate_number": 1274,
      "report_year": 2020,
      "opening_reserves_gbp_m": 850.2,
      "prior_year_development_gbp_m": 130.209,
      "prior_year_development_pct": 15.31,
      "direction": "strengthening",
      "gross_premiums_written_gbp_m": 573.3,
      "gross_premium_mix": [...],
      "_rag_triangle": {
        "type": "gross",
        "currency": "USD",
        "units": "thousands",
        "underwriting_years": [2011, 2012, ..., 2020],
        "development_rows": [["...NxN matrix..."]]
      }
    },
    "gpt-5-mini": { "...same fields..." }
  },
  "validation": {
    "passed": true,
    "total_discrepancies": 2,
    "within_tolerance": 2,
    "hard_failures": 0
  }
}
```

### 14.2  First-year syndicate

When the triangle-based detection confirms the report is from a
syndicate with fewer than 3 usable underwriting years (the
inception year cache alone no longer triggers a skip -- see
section 11.1):

```json
{
  "first_year_syndicate": true,
  "reason": "Syndicate 1991 began underwriting in 2013; report year 2014 is within the first two underwriting years - insufficient development history for prior year development analysis",
  "syndicate": 1991,
  "year": 2014,
  "inception_year": 2013,
  "gross_premium_mix": ["...if available..."]
}
```

When detected by the triangle check (no usable UW years for PYD):

```json
{
  "first_year_syndicate": true,
  "reason": "Syndicate too new -- insufficient underwriting years for prior year development analysis",
  "syndicate": 1322,
  "year": 2023,
  "gross_premium_mix": ["...if available..."]
}
```

Reports reclassified by the retrospective correction script also
include a `reclassified_from` field indicating the previous status
(`"no_triangle_data"` or `"normal_extraction"`).

### 14.3  No-triangle-data exclusion

```json
{
  "no_triangle_data": true,
  "excluded": true,
  "exclusion_reason": "No claims development triangle or reserve movement text found",
  "syndicate": 1110,
  "year": 2019
}
```

### 14.4  Excluded after extraction

Reports that were fully extracted (have a `models` key with LLM
outputs) but subsequently excluded during adjudication or manual
review.  These retain the full extraction data alongside the
exclusion flags:

```json
{
  "extraction_timestamp": "2026-03-17T07:51:30+00:00",
  "source_file": "syndicate_reports/pdfs/syndicate_1897_2014.pdf",
  "models": {
    "gemini-2.5-flash": { "...full extraction..." },
    "gpt-5-mini": { "...full extraction..." }
  },
  "validation": { "passed": false, "hard_failures": 2, "..." : "..." },
  "excluded": true,
  "exclusion_reason": "The 1897 report for 2014 does not disclose prior year claim movements",
  "exclusion_date": "2026-03-17"
}
```

The key distinction from 14.3 is that these reports **have**
`models` -- the extraction ran but the result was rejected.
Common causes include unresolvable LLM disagreements where the
underlying report does not contain sufficient reserve data.

---

## 15  Progress report dashboard

The file `pdf_extraction/progress_report.html` provides a
browser-based monitoring dashboard that reads JSON output files
and source PDFs via the File System Access API.

### 15.1  Report status categories

Each completed JSON file is classified into one of three
statuses based on its structure:

| Status | Condition | Badge colour | Description |
|--------|-----------|--------------|-------------|
| **Skipped** | No `models` key (has `first_year_syndicate`, `no_triangle_data`, or `reason`) | Yellow | Report was never sent to LLMs -- auto-detected as first-year syndicate or no-triangle-data via triangle inspection.  No API cost incurred (except table extraction). |
| **Excluded** | Has `models` key AND `excluded: true` | Purple | Extraction ran but the report was excluded during adjudication or manual review.  API cost was incurred. |
| **Extracted** | Has `models` key, no `excluded` flag | Green/Red | Normal extraction result.  Shown as "Reliable" (green) if both PYD and premium mix are present, or "Incomplete" (red) otherwise. |

**Console INCOMPLETE warning**: After writing each JSON file,
`test_gemini.py` checks whether the extraction has both PYD %
and a non-empty premium mix.  If either is missing, a
`>> INCOMPLETE: missing <fields>` line is printed to the
console so the operator sees the same status that the dashboard
will show, without needing to open `progress_report.html`.

**Note**: reports with both `no_triangle_data: true` and
`excluded: true` but **no** `models` key are classified as
Skipped, not Excluded.  The `excluded` flag on these files is a
legacy artefact from the no-triangle-data detection path --
the report was never sent to LLMs.

### 15.2  Dashboard cards

| Card | Metric | Denominator |
|------|--------|-------------|
| Completed | Count of all JSON files | Total PDFs in source folder |
| Progress | % complete | Total PDFs |
| Elapsed Time | Wall time from first to latest extraction timestamp | -- |
| Est. Remaining | `(avg_time_per_report) * remaining_count` | -- |
| Reliable Data | % of extracted (non-skipped, non-excluded) reports with both PYD and premium data | Extracted count |
| Total Cost | Sum of `total_cost_usd` across all reports | -- |
| Skipped | % of completed reports that are skipped | Completed count |
| Excluded | % of completed reports that are excluded after extraction | Completed count |

### 15.3  Syndicate/year resolution for excluded reports

Excluded reports with `models` typically lack top-level
`syndicate` and `year` fields (these are inside the model
objects).  The dashboard resolves these in priority order:

1. Top-level `data.syndicate` / `data.year`
2. First model object's `.syndicate` / `.year`
3. Filename regex: `syndicate_(\d+)_(\d{4}).json`

---

## 16  Troubleshooting

### Triangle has too many development rows

**Symptom**: 20 rows instead of 10.

**Cause**: the API extracted both the incurred-claims and
paid-claims sections as a single table.

**Fix**: section-break detection in `_parse_nutrient_triangle()`
stops collection at "Cumulative claims paid", "Gross paid claims
position", or "Current estimate" labels.

### Combined gross+net table not split correctly

**Symptom**: triangle has double the expected development rows
(e.g. 12 rows for a 5-column triangle), and PYD computation
produces nonsensical values.

**Cause**: the API backend detected a single table spanning both
the gross incurred-claims section and the net incurred-claims (or
paid-claims) section.  The section boundary label (e.g.
"Cumulative gross payments to date" or "Estimate of cumulative
net claims incurred") did not match any existing section-break
pattern.

**Fix**: section-break patterns in `_parse_nutrient_triangle()`
include `"cumulative gross payments"`, `"cumulative net payments"`,
and `"estimate of cumulative net"` to handle combined tables
(e.g. syndicate 1492/2018--2023).

### Triangle not found on rotated page

**Symptom**: Azure returns no table for a page containing a
landscape claims triangle.

**Cause**: the page has an incorrect `/Rotate` flag (e.g.
`rotation=270`), or the content is physically rotated 90 degrees
on a scanned page (e.g. syndicate 1729/2023 pages 44--45 where
the claims development table is printed sideways).

**Fix**: `_find_pages_ocr()` retries unclassified pages with 90
degree rotation and records them in the `rotated_pages` set.
`_extract_pages_to_pdf()` then re-renders these pages as
correctly oriented images before sending to Azure.  For incorrect
`/Rotate` flags, the flag is simply removed with
`page.set_rotation(0)`.

### OCR text is garbled / reversed

**Symptom**: Tesseract produces reversed text like
`"Ve / LLoz sjunosoy"`.

**Cause**: Poppler rendered the page upside-down due to an
incorrect `/Rotate` flag.

**Fix**: the OCR scanner uses PyMuPDF (with `set_rotation(0)`)
instead of Poppler for page rendering, and retries unclassified
pages with 90-degree rotation.

### PYD ratio exceeds -100%

**Symptom**: `_apply_triangle_pyd()` reports "PYD ratio -250%
< -100%" or RAG override path reports "< -100% — likely
misidentified table. Discarding RAG PYD."

**Cause**: one of:
- Unit mismatch (e.g. triangle in individual pounds but
  treated as millions).
- Misaligned triangle (segmental analysis table
  misidentified as a claims triangle, with year numbers
  mixed into data rows -- see section 9.5).
- Garbled unit string from API backend (e.g. `"units"`
  instead of `"thousands"` -- see section 9.3).

**Fix**: the pipeline applies three layers of defence:
1. Year-value contamination check rejects garbled triangles
   at `compute_pyd_from_triangle()` (section 9.5).
2. `_apply_triangle_pyd()` checks the ratio **before**
   setting the PYD, preserving the original LLM value.
3. RAG override path validates the PYD against opening
   reserves and falls back to `verify_triangles()` on
   failure (section 10.3).

### Garbled unit string causes million-fold PYD inflation

**Symptom**: PYD values in the millions (e.g. 46,527,508m)
with percentages like 4,426,905%.

**Cause**: the API backend returned a non-standard unit
string (e.g. `"units"`) that did not match the auto-detection
trigger condition (`units == "millions"`).  Raw values in
thousands were treated as millions without conversion.

**Fix**: unit auto-detection now triggers for any unit string
not in the known set (`"thousands"`, `"full"`, `"percentage"`),
catching garbled strings.  See section 9.3.

### Transposed triangle not detected

**Symptom**: triangle extraction returns `None` for a syndicate
that uses "Development Year 1, 2, 3..." column format (e.g.
syndicate 1856).

**Cause**: the standard UW-year-as-column parser does not
recognise development period numbers as UW years, so falls
through to no-data.

**Fix**: `_parse_nutrient_triangle()` now falls back to
`_parse_transposed_triangle()` when no UW years are found in
column headers.  The text-based parser has Strategy C
(`_parse_transposed_triangle_from_text()`) for cases where the
API detects no table at all.

### "Underlying Pure Year" triangle not detected

**Symptom**: triangle extraction returns `no_triangle_data` for
a syndicate that uses non-standard labels like "Underlying Pure
Year" and "Incurred at end of underwriting year" (e.g. syndicate
1919).

**Cause**: three independent issues compounded:

1. **Page keywords**: `_PAGE_KEYWORDS['claims_triangle']` did not
   include "underlying pure year" or "incurred at end of
   underwriting", so the page was not tagged for triangle
   extraction (though other keywords like "year later" and "gross
   of reinsurance" could still match if present).

2. **Text-based parser markers**: `_parse_transposed_triangle_from_text()`
   only checked for `"development year"` + `"year of account"`.
   PyMuPDF splits "Underlying Pure Year" across lines as
   `"Underlying\nPure\nYear"`, so even a simple string search
   fails.  The function now normalises whitespace before marker
   detection and supports the alternative marker pair.

3. **Grid-based parser headers**: `_parse_transposed_triangle()`
   only checked for `"Development Year"` in the first header cell.
   The "Underlying Pure Year" header was not recognised.

4. **Units detection**: `$000` was not matched by the unit
   detection regex in the text-based parsers (only `£000`/`£'000`/
   `'000` were checked).  This caused USD-denominated triangles in
   thousands to be treated as millions.

**Fix** (cache version 6):

- Added `"underlying pure year"` and `"incurred at end of
  underwriting"` to `_PAGE_KEYWORDS['claims_triangle']`.
- `_parse_transposed_triangle_from_text()` now normalises
  whitespace (`\s+` → ` `) before searching for markers, and
  supports `"underlying pure year"` as an alternative to
  `"year of account"` and `"incurred at end of underwriting"`
  as an alternative to `"development year"`.  Added
  `"net of reinsurance"` as a section stop marker.
- `_parse_transposed_triangle()` recognises "Underlying Pure Year"
  as a header (Format C, section 7.6.3) and parses
  "X year(s) later" / "Incurred at end..." as dev period columns.
- Units detection in text-based parsers now uses regex
  `[£$]'?000` instead of hard-coded `£000`/`£'000` strings,
  correctly matching `$000`.

### "Year of Account" triangle not detected

**Symptom**: triangle extraction returns 0 development rows for
a syndicate that uses "Year 1", "Year 2", "Year 3" row labels
instead of "12 months later" / "1 year later" (e.g. syndicate
1880).

**Cause**: the dev-period pattern list did not include a regex
for "Year N" labels.  The parser only matched standard formats
like "at end of underwriting year", "one year later", "12 months
later", etc.

**Fix**: added `r"^year\s+\d+"` to `dev_period_patterns` in both
`_parse_nutrient_triangle()` (grid parser) and
`_parse_triangle_from_text()` (text-based fallback).  Also added
`"cumulative claims paid"` and `"outstanding claims reserve"` to
the text parser's `stop_labels` for this format's summary rows.

### Concatenated numbers in PyMuPDF text

**Symptom**: numbers like `"57,73559,926117,918"` are captured
as a single value instead of three separate values.

**Cause**: PyMuPDF extracts text without spaces between adjacent
table cells.  The standard `[\d,]+` regex captures the entire
concatenated string.

**Fix**: use `\d{1,3}(?:,\d{3})*` which respects
comma-formatting boundaries and correctly splits at number
boundaries.

### Triangle rejected for too many rows (trailing nulls)

**Symptom**: `compute_pyd_from_triangle()` rejects a valid
triangle with "n_rows (6) > expected_max_rows (5)".

**Cause**: the triangle includes development period labels
(e.g. "After four years", "After five years") with all-null
values because the triangle only covers a few UW years.  These
trailing empty rows inflate the row count past the validation
threshold.

**Fix**: both `_parse_nutrient_triangle()` and
`compute_pyd_from_triangle()` strip trailing all-null rows
before validation.

### Oldest column rejected due to dashes in run-off triangles

**Symptom**: `compute_pyd_from_triangle()` rejects a valid
run-off syndicate triangle with "oldest column has N filled
rows, expected M -- likely shifted/misaligned", or the report
is excluded with `no_triangle_data: true`.

**Cause**: run-off syndicates (e.g. syndicate 1840) may have
UW year columns where cumulative claims went to zero, shown as
`-` (dash) in the PDF.  `_clean_cell_triangle()` correctly
treats dashes as `None` (no data in triangle context), but this
makes the oldest column appear sparse.  The old validation
required `col0_filled >= min(n_rows, n_cols)`, which rejected
legitimate run-off triangles where the oldest UW year has only
one development period with a real value.

**Example**: syndicate 1840/2023, UW year 2020 had initial
claims of 19 (thousands) that resolved to zero:

```
                 2020   2021   2022
End of UW yr:     19  2,244    188
One year after:    -  3,284  1,247
Two years after:   -  3,379
Three years after: -
```

The 2020 column has `col0_filled = 1` (only the first row).
The old guard required `min(3, 3) = 3`, so it rejected the
triangle.  PYD should be `3379 - 3284 = 95` (thousands) =
+0.095m from UW year 2021.

**Fix** (two parts):

1. The `col0_filled` validation in
   `compute_pyd_from_triangle()` now requires only
   `col0_filled >= 1` (at least one real value).  A completely
   empty oldest column still signals misalignment, but a column
   with a single entry is accepted -- the staircase structure
   validator provides the remaining structural checks.

2. "Less gross claims paid" was not caught by
   `section_break_patterns` in `_parse_nutrient_triangle()`.
   The split-label continuation logic absorbed the paid-claims
   row's values into the "Three years after" row (which had
   all-None values due to dashes), adding a spurious fourth dev
   row.  Adding `"claims paid"`, `"less gross"`, and
   `"less net"` to the section break list fixed this.

### Run-off triangle structure score is 0.0

**Symptom**: `_validate_triangle_structure()` returns 0.0 for a
run-off syndicate triangle that looks correct.

**Cause**: the structure validator expected `n_cols - col_idx`
filled values per column, but run-off syndicates have extra
development rows (more rows than columns).  Every column had
more filled values than expected, exceeding the ±1 tolerance.

**Fix**: `_validate_triangle_structure()` now adds
`extra_dev_years = report_year - max_uw_year` to the expected
fill count for each column.

### Pages not classified due to whitespace issues

**Symptom**: Azure returns 0 relevant pages for a report that
clearly contains a claims development triangle.
`_classify_page()` matches no keywords.

**Cause**: two whitespace issues in PyMuPDF output can prevent
keyword matching:

1. **Non-breaking spaces**: PyMuPDF emits U+00A0 instead of
   regular ASCII spaces, so `"year\xa0later"` does not match
   the keyword `"year later"`.
2. **Line-split phrases**: PyMuPDF's columnar extraction splits
   multi-word phrases across lines (e.g. `"years\nlater"`),
   preventing multi-word keywords from matching.  This affected
   syndicate 1919/2018 where the triangle page had 14 instances
   of "later" but zero keyword hits.

**Fix**: `_classify_page()` normalises both non-breaking spaces
and newlines to regular spaces before keyword matching:
`text.replace("\u00a0", " ").replace("\n", " ")`.

### Bare year labels in column 0 misidentified as UW year headers

**Symptom**: Azure triangle has extra UW years, or valid triangles
are rejected as "too old" because row-label years (e.g. "2011",
"2012" in a transposed triangle's data rows) are picked up as
column header years.

**Cause**: `_parse_nutrient_triangle()` scans the first 3 rows
for 4-digit years in any column.  In headerless transposed
triangles (Format B, section 7.6.2), data rows start within the
first 3 rows and have bare UW years in column 0.  These years are
treated as column headers, producing wrong results.  For example,
finding years 2011 and 2012 in the first 3 rows causes rejection
with "max UW year 2012 too old for report year 2018".

**Fix**: `_parse_nutrient_triangle()` skips **any** bare year in
column 0 (where the cell contains only the year string with no
other context).  Previously only the report year was skipped;
now all bare year labels are skipped, correctly treating them as
row labels rather than column headers.

### Azure PYD fails on gap-year triangle with aggregate column

**Symptom**: Azure extracts the triangle table with 8 UW years
but no `[Azure] Triangle PYD:` line appears in the log.  LLM
vision fallback produces the PYD instead.

**Cause**: the triangle includes an aggregate column ("2013 &
prior") that has no values in the development rows -- only a
summary-row total.  Azure detects this as UW year column 0, but
`compute_pyd_from_triangle()` rejects the triangle because
`col0_filled = 0` fails the oldest-column fill-count check.

**Example**: syndicate 1884/2023 has Azure-detected UW years
["2013 & prior", 2014, 2015, 2016, 2017, 2018, 2022, 2023].
The "2013 & prior" column has value 810.4 only in the
"Cumulative estimate" summary row, not in any development row.

**Resolution**: this is expected behaviour.  The LLM vision
fallback correctly reads the triangle from the page image,
excludes the aggregate column, and computes PYD from UW years
2014--2018 (excluding the two most recent: 2022 and 2023).

### Row count validation fails for year-gap triangle

**Symptom**: `compute_pyd_from_triangle()` rejects a valid
triangle with "triangle has N rows but only M columns".

**Cause**: syndicates with non-contiguous UW years (e.g.
[2013..2018, 2022]) have more development rows than columns.
The old formula `n_cols + extra_dev_years + 1` was too strict
because it assumed contiguous UW years.

**Fix**: replaced with development-span formula:
`report_year - min(uw_years) + 2`, which correctly accounts
for the full development span including gap years.

### Azure API hangs

**Symptom**: pipeline blocks indefinitely on
`poller.result()`.

**Cause**: Azure SDK's internal retry/backoff can stall.

**Fix**: manual polling loop with 120-second deadline,
interruptible by Ctrl+C.

### Azure splits triangle header and data into separate tables

**Symptom**: Azure detects tables on the triangle page but
`_parse_nutrient_triangle()` finds no valid triangle.  The log
shows "Possible new syndicate (1 UW year(s))" despite the report
having a full multi-year triangle.

**Cause**: Azure Document Intelligence splits a single triangle
table into two separate grids: one containing only the header
row(s) (e.g. "Underlying Pure Year", "1 year later", ...) and
another containing the data rows (UW years with numeric values).
The header table is too small (< 4 rows) to parse.  The data
table has no descriptive header, so `_parse_nutrient_triangle()`
finds no UW years in header rows and the existing
`_parse_transposed_triangle()` rejects it because it lacks a
"Development Year" header.

**Example**: syndicate 1919/2018 -- the triangle on page 41 uses
"Underlying Pure Year" as its header and has UW years 2011--2018
as row labels with development periods as columns, plus a
"Cumulative Payments" column.

**Fix**: `_parse_transposed_triangle()` now supports a
**headerless format** (Format B, section 7.6.2).  When no
"Development Year" header is found, it checks if 3+ rows have
bare 4-digit years in column 0.  If so, all remaining columns
are treated as development periods.  A fully-populated last
column is detected and stripped as "Cumulative Payments" (the
second-to-last column must have at least one null to confirm
the triangle staircase shape).

### PYD is null despite narrative text quoting a figure

**Symptom**: both LLMs return `prior_year_development_gbp_m:
null`, but `exact_reserve_text` contains a clear amount like
"reserve release of GBP 1.3m net of reinsurance".

**Cause**: the report only discloses the prior year movement
**net of reinsurance** (no gross movement note, no gross
triangle, no loss ratio table).  The LLM prompt historically
instructed models to return null when only a net figure was
available.

**Fix**: two changes:
1. The LLM prompt now includes **Source 6** (last resort):
   use the net-of-reinsurance figure when no gross source
   exists, flagged in `data_quality_notes`.
2. Post-processing in `process_single_report()` runs
   `_parse_net_pyd_from_text()` after all other PYD sources.
   If both models still have null PYD but valid
   `exact_reserve_text`, the parser extracts the net amount
   and fills it in with a `[NET FALLBACK]` annotation.

**Example**: syndicate 1910/2014 -- "a reserve release of
GBP 1.3m net of reinsurance" -> `prior_year_development_gbp_m:
-1.3`, `prior_year_development_pct: -1.86`.

### Loss ratio triangle PYD disagrees with narrative

**Symptom**: the loss ratio triangle computes a PYD at managed
level (e.g. +65.9m strengthening) but the narrative says the
syndicate released reserves (e.g. -$75.1m release).

**Cause**: Beazley syndicate 2623 (and similar group-managed
syndicates) present claims development at the **Beazley managed
level**, not the syndicate 2623 share.  The syndicate's share
of claims varies by underwriting year and line of business, so
managed-level PYD can differ from syndicate-level PYD in both
magnitude and direction.

**Resolution**: the pipeline marks loss ratio triangle PYD as
**fallback only** (`rag_is_fallback_only = True`).  When both
LLMs extract a syndicate-level PYD from the narrative text,
their value is kept and the managed-level figure is logged but
not applied.  The loss ratio PYD only fills in LLM blanks.

**Affected syndicates**: 2623/2016 through 2623/2022.

### Azure extracts loss ratios as claims triangle

**Symptom**: Azure finds a triangle on the claims development
page but PYD makes no sense (e.g. -11.2m when the narrative
says -180.2m).

**Cause**: Azure extracted the cumulative loss ratio grid
(percentages like 66.5, 64.6, 63.4) as if they were absolute
claims amounts in millions.

**Fix**: `compute_pyd_from_triangle()` now checks if all
non-null values are in the 0--200 range.  If so, the triangle
is rejected as a loss ratio table.  The loss ratio parser
(`_extract_pyd_from_loss_ratio_triangle`) handles it separately.

### Perplexity returns syndicate number as inception year

**Symptom**: log shows `"WARNING: Perplexity returned syndicate
number N as inception year -- ignoring"` for syndicates whose
number coincidentally equals their actual inception year (e.g.
syndicate 2001 genuinely started underwriting in 2001).

**Cause**: the old free-text parser had a heuristic that rejected
any Perplexity response where the parsed year equalled the
syndicate number, on the assumption that Perplexity was echoing
the number.  This rejected 17 syndicates in the 1980--2021 range
whose numbers happen to match their true inception year.

**Fix**: `_lookup_inception_year_perplexity()` was rewritten to
request **structured JSON output** from Perplexity instead of
free text.  The prompt asks for:
```json
{
  "syndicate_number": 2001,
  "first_underwriting_year": 1997,
  "confidence": "high",
  "source": "Lloyd's syndicate directory"
}
```
The syndicate-number-echo heuristic was removed.  Instead,
quality control is handled by:
- **Confidence filtering**: `"low"` confidence answers are
  rejected; `"medium"` and `"high"` are accepted.
- **Range validation**: year must be 1688--2030.
- **Sanity check vs reports on disk**: year must not be later
  than the earliest report we have for the syndicate.
- **JSON parse fallback**: if Perplexity returns free text,
  a regex extracts the first 4-digit year.

### Unicode characters cause charmap codec error on Windows

**Symptom**: `'charmap' codec can't encode character '\u2192'`
crashes the pipeline on Windows when printing RAG override
messages.

**Cause**: print statements contained Unicode characters
(U+2192 RIGHTWARDS ARROW, U+2014 EM DASH) that the Windows
console code page (cp1252) cannot encode.

**Fix**: replaced Unicode arrows and em-dashes with ASCII
equivalents (`->` and `--`) in all print/log statements in
`test_gemini.py` and `table_extraction.py`.

### LLMs extract wrong opening reserves

**Symptom**: Gemini and GPT return different (wrong) values for
`opening_reserves_gbp_m`.  For example, syndicate 2003/2019 had
Gemini reading 1,227m and GPT reading 5,466m instead of the
correct 5,921m ($5,921,697 thousands from the Technical
Provisions note).

**Cause**: the Balance Sheet / Statement of Financial Position
page was not included in the slim PDF sent to the LLMs.  The
page contained "Claims outstanding" (1 keyword hit in
`provisions`) but needed 2+ hits to be classified.  Without
this page, the LLMs could not find the gross technical
provisions opening balance and fell back to other figures
(e.g. reinsurers' share of claims outstanding, or net
provisions).

**Fix** (v2.8): added a `balance_sheet` category to
`_PAGE_KEYWORDS` in `table_extraction.py` with keywords:
"statement of financial position", "balance sheet",
"total assets", "total liabilities", "technical provisions",
"claims outstanding", "gross technical provisions".
Bumped `PROMPT_VERSION` from 2.7 to 2.8 to invalidate LLM
caches.

**Additional fix**: even with the balance sheet page included,
LLMs can still confuse opening reserves with other figures
(member's balances, total technical provisions including
unearned premiums).  The pipeline now extracts the opening
gross claims outstanding deterministically from the Technical
Provisions movement note (section 7.8.2) and uses it to
auto-resolve `opening_reserves_gbp_m` hard failures
(section 10.6).

### Auto-accepted fields shown as "Unresolved" in report decision

**Symptom**: after the adjudication loop resolves all hard
failures (including auto-computed `prior_year_development_pct`),
`present_report_decision()` displays auto-accepted fields as
"Unresolved" and prompts for a manual include/exclude decision.

**Cause**: `present_report_decision()` in `adjudicate.py` only
counted `("approve", "override", "override_value")` as resolved
decision types.  Fields resolved via `"auto_accept"` (immaterial
differences, auto-computed percentages) were classified as
unresolved.

**Fix**: added `"auto_accept"` to the resolved decision types
in `present_report_decision()`.

### Gemini returns malformed JSON with unquoted property names

**Symptom**: `parse_json_response()` fails with "Expecting
property name enclosed in double quotes" and the pipeline
retries up to 3 times before crashing.

**Cause**: Gemini occasionally outputs JavaScript-style JSON
with unquoted property names (e.g. `{ syndicate_number: 2357 }`
instead of `{ "syndicate_number": 2357 }`).  The existing JSON
repair logic handled trailing commas and `//` comments but not
unquoted keys.

**Fix**: `parse_json_response()` now applies two additional
repair strategies:

1. **Multi-line comment removal**: strips `/* ... */` blocks.
2. **Unquoted property name quoting**: converts
   `{ key: "value" }` to `{ "key": "value" }` using the regex
   `(?<=[\{,])\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*:`.  This matches
   identifiers after `{` or `,` that are not already quoted,
   and wraps them in double quotes.  Already-quoted keys are
   unaffected because the lookbehind requires `{` or `,`
   immediately before the identifier.

### Combined gross+net triangle: "Total Ultimate" section boundary

**Symptom**: triangle has double the expected development rows
(e.g. 20 rows for a 10-column triangle).  PYD computation
produces wrong values because net incurred-claims rows are
mixed into the gross triangle.

**Cause**: the Azure-detected table spans both the gross and
net incurred-claims sections, separated by a "Total Ultimate
losses" summary row and a "Less cumulative paid claims" header.
Neither label matched existing `section_break_patterns`, so the
parser collected all rows from both sections.

**Example**: syndicate 2791/2020 page 59 has a single Azure
table grid containing:
```
[Gross incurred claims - 10 development rows]
Total Ultimate losses    610,982  ...
Less cumulative paid claims
[Paid claims - 10 rows]
Net incurred claims
[Net incurred claims - 10 rows]
```

The parser collected 20+ development rows instead of 10.

**Fix**: added `"total ultimate"` and `"less cumulative"` to
`section_break_patterns` in `_parse_nutrient_triangle()`.  These
match "Total Ultimate losses" (summary row separating gross from
paid section) and "Less cumulative paid claims" (header starting
the paid-claims section).

### Report excluded despite having provisions PYD

**Symptom**: report flagged as `no_triangle_data` and excluded,
even though the provisions movement note contains a valid gross
prior year claims development figure.

**Cause**: the pipeline checked for `no_triangle_data` (no
triangle + no reserve text) before consulting the provisions
note.  Reports with a provisions PYD but no triangle were
incorrectly excluded.

**Example**: syndicate 2791/2024 has no claims development
triangle (Azure detected only P&L/premium tables on the
misclassified `claims_triangle` pages), but provisions data
on page 49 shows gross prior year claims development of
−27.986m.

**Fix**: added a provisions PYD fallback step (Step 4c) in
`process_one_report()` that runs **before** the
`no_triangle_data` check.  If no triangle PYD exists and the
report has `adobe_provisions.gross_prior_year_claims`, that
value is used as the PYD with `method: "provisions"`.  See
section 11.3 for details and RITC caveats.

### Incorrect inception year causes reports to be skipped

**Symptom**: report flagged as `first_year_syndicate` with
`"reason": "Syndicate N began underwriting in YYYY"`, but the
PDF contains a full claims development triangle with UW years
going back much further.  Example: syndicate 1980/2018 was
skipped with `inception_year: 2018` despite the triangle
showing UW years 2011--2017.

**Cause**: the inception year check (Step 0) ran before any PDF
reading and trusted the `syndicate_inception_years.json` cache
blindly.  If Perplexity returned the wrong year (or the cache
was populated from a different report's partial data), the
pipeline returned `first_year_syndicate` without ever opening
the PDF or inspecting the triangle.

**Fix**: the inception year check is now a **soft flag** rather
than a hard skip.  The pipeline always proceeds to RAG-lite
extraction (Step 1--4).  After the triangle is extracted, the
pipeline compares the triangle's earliest UW year against the
cached inception year.  If the triangle contradicts the cache:

1. The cache is corrected to `min(underwriting_years)`
2. `inception_skip` is cleared
3. Extraction proceeds normally

This ensures the triangle (ground truth) always takes precedence
over the inception cache (heuristic).  See section 11.1 for
the updated decision rule.

**If automatic correction keeps reverting a manually-set value**:
add the syndicate number to the `_manual_overrides` array in
`syndicate_inception_years.json`.  This protects the entry from
all automated updates (Perplexity, triangle backfill, cache
correction).  See section 11.1 "Manual overrides".

### Image-based segmental analysis table not extracted

**Symptom**: `gross_premium_mix` is empty (`[]`) for both LLMs
despite the PDF containing a full segmental analysis table.
Example: syndicate 5151/2018 -- the segmental analysis on page 28
has 12 LOB classes but neither model extracted them.

**Cause**: the segmental analysis table is embedded as an image
(PNG) rather than native PDF text.  PyMuPDF extracts only the
surrounding prose ("5. Segmental analysis / An analysis of the
underwriting result before investment return is set out below:")
but not the table data.  The page failed `_classify_page()`
because:

1. Only 1 keyword matched: `"segmental analysis"` (needs >=2)
2. `"analysis of underwriting result"` did not match because
   the actual text reads "analysis of **the** underwriting
   result" (extra article)

Since the page was never tagged as `premium_mix`, it was not
sent to Azure Document Intelligence and was not included in the
slim PDF.

**Fix**: added three new keywords to `_PAGE_KEYWORDS["premium_mix"]`:

- `"analysis of the underwriting result"` -- matches the variant
  phrasing with the article "the"
- `"gross premiums written"` -- appears on income statement pages
  that overlap with LOB data
- `"commissions on direct insurance"` -- appears in the prose
  footer of segmental analysis pages (e.g. "Commissions on
  direct insurance gross premiums during 2018 were...")

With these keywords, page 28 now gets 3 hits and is sent to
Azure.  Azure's prebuilt-layout model performs OCR on embedded
images and successfully extracts the 12-class LOB table.  The
Azure cache auto-invalidates because the relevant page set
changes (page 27 is now included), producing a different
`_pages_hash`.

### Rotated "Year of account" triangle produces PYD = 0

**Symptom**: a Lloyd's syndicate (e.g. 780/2016) with a
landscape-oriented claims development triangle shows PYD = 0.0m
[flat], despite the report clearly containing prior year reserve
releases.  The log shows:

```
[Azure] Extracted: triangle=6 UW years
[RAG] No triangle, but found 3 reserve text page(s)
[RAG] Using provisions PYD as fallback: +0.000m
```

**Root cause** (three interacting bugs):

1. **Triangle parser did not recognise "Year of account" header**.
   The table uses "Year of account" as its first header cell, but
   `_parse_transposed_triangle()` only recognised "Development
   Year" and "Underlying Pure Year".  It fell through to
   headerless mode (Format B), which included the "Cumulative
   payments" and "Estimated balance to pay" columns as development
   periods.  After transposing, the triangle had 8 development
   rows for a 6-year span, causing `compute_pyd_from_triangle()`
   to reject it ("triangle has 8 rows but span is only
   2011--2016 -- likely includes summary rows or is misaligned").

2. **Provisions parser picked wrong column for gross PYD**.
   The provisions table had headers `"Provision for unearned
   premiums | Claims outstanding | Total"` instead of the expected
   `"Gross | Reinsurers' share | Net"`.  The positional fallback
   assigned `gross_col=1` ("Provision for unearned premiums"),
   which showed "-" (→ 0.0) for the prior year row.  The actual
   gross claims PYD was in column 2 ("Claims outstanding") at
   −15.6m.

3. **RAG override propagated the zero**.  With provisions
   `gross_prior_year_claims = 0.0`, both LLMs' correct values
   (−15.6m and −17.1m) were overridden to 0.0.

**Fixes** (three changes):

1. Added "Year of account" header detection in
   `_parse_transposed_triangle()` (Format D, section 7.6.4).
   Development period columns are now identified from header
   labels ("end of calendar", "year later", etc.) and summary
   columns ("cumulative", "estimated", "balance") are excluded.

2. Added "Claims outstanding" column detection in
   `_parse_nutrient_provisions()` (section 7.8.1).  When a column
   header contains "claims outstanding", it is used as `gross_col`
   instead of the default positional fallback.

3. Added triangle vs provisions cross-validation (Step 4b,
   section 11.3.1).  When both triangle PYD and provisions gross
   PYD are available and disagree in sign, provisions is preferred
   because it directly measures balance-sheet reserve movement.

**Result**: PYD for syndicate 780/2016 changed from 0.0m to
−15.6m (−4.5% of $348m reserves, release), confirmed by both
LLMs.

### Gemini 400 INVALID_ARGUMENT on scanned syndicate PDF

**Symptom**: `extract_with_gemini()` fails with `400
INVALID_ARGUMENT` after a successful file upload.  The log shows
the slim PDF is orders of magnitude larger than the original:

```
[LLM] Slim PDF: 10 pages, 102107 KB (full report: 2449 KB)
[gemini-2.5-flash] Upload done (21.4s). Extracting...
ERROR: 400 INVALID_ARGUMENT
```

**Root cause**: the source PDF is fully scanned (all 29 pages are
raster images).  `_extract_pages_to_pdf()` copies pages via
`insert_pdf()`, which preserves the raw embedded images without
recompression.  10 pages of high-resolution scans produce a 100+ MB
slim PDF -- well beyond Gemini's content processing limit.

**Fix**: added an automatic compression step in
`_extract_pages_to_pdf()` (section 5.5).  After writing the slim
PDF, if it exceeds `MAX_SLIM_PDF_BYTES` (20 MB), every page is
re-rendered at 150 DPI and saved as a JPEG at 75% quality.  This
reduces the file to ~2--5 MB while preserving sufficient image
quality for LLM text extraction.

Discovered on syndicate 5000/2014 (29 scanned pages, 10 relevant,
102 MB slim PDF → Gemini 400 error).
