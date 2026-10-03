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
| Step 0: First-year check (RAG-lite, no API)   |
|   extract_pyd_from_relevant_pages()           |
|     No triangle cohort up to t-2 and no       |
|     reserve text -> first-year stub           |
|   Checked again after the models (11.1);      |
|   the inception-year lookup was removed       |
|   in round 58                                 |
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
|   Managed-level conditional fallback: fill an   |
|   LLM blank; override only a contrary direction |
+-----------------------------------------------+
  |
  v
+-----------------------------------------------+
| Step 4b: Triangle vs provisions cross-check   |
|   Only from an affirmed movement note whose   |
|   column is bound to the report year (R138):  |
|   if its gross prior-year movement and the    |
|   triangle PYD disagree in sign, prefer       |
|   provisions (the balance-sheet movement, not |
|   diagonal development, which can include     |
|   emergence); otherwise the triangle stands   |
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
|   Triangle PYD prevails (see 10.3 sign rule)   |
|     (loss ratio uses conditional fallback)     |
|   RAG balance-sheet opening is considered      |
|     for both models; apply only under the       |
|     agreement/unit/tie-break rule (section     |
|     10.6), otherwise retain model values and   |
|     record the conflict                         |
|   Net-of-reinsurance PYD fallback if null      |
|   Zero-opening override (PYD=0 if opening=0)  |
|   Direction forced from resolved PYD sign      |
+-----------------------------------------------+
  |
  v
+-----------------------------------------------+
| Step 6: Report classification                  |
|   first_year_syndicate: no usable cohort up to |
|     t-2; decided BEFORE the models, or after   |
|     them on the reserve text (see 11.1, 11.2)  |
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
- **Paid tier (S0)**: all relevant pages sent in a single API call.
  This is the default (`AZURE_PAID = True` in `test_gemini.py`), and it
  is the tier that processed the corpus; it reduces the number of API
  round-trips from `ceil(N/2)` to 1, which is faster for reports with
  many relevant pages (typically 4--8).
- **Free tier (F0)**: 2 pages per API call.  Pages are split into
  batches of 2 and sent sequentially.  Selected with the `--azure-free`
  CLI flag, which sets `azure_paid=False` on `extract_tables()`.
- Retry policy: 3 retries with 1-second backoff (max 10 seconds).
- Timeout: 120-second polling deadline per batch.
- Tables are extracted with row/column structure.
- Results cached in `pdf_extraction/azure_output/`.

**Usage**:

```bash
# Paid tier (default): all relevant pages in one request
python test_gemini.py

# Free tier: batches of 2 pages
python test_gemini.py --azure-free
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
2. Exclude cells containing `"prior"` or `"&"` as individual UW years.
   An aggregated older cohort ("2010 and prior", "2010 &" over
   "prior", "2010" beside "and prior", "Before" over "2011") is read
   across its column's first three header rows (R209).  Its column
   becomes the triangle's oldest column, under the cohort's anchor
   year, when that anchor is the year before the oldest single year
   and the column carries development in at least two rows; the
   triangle records it as `aggregated_cohort`.  The cohort's
   development belongs to the numerator (underwriting years up to
   report year minus 2).  A year cell inside the label ("2011" under
   "Before") is not an underwriting year of its own, and a cohort
   column with no development (a reserve line, dashes) is dropped.
   So is a cohort column printed by development age.  A column that
   runs by calendar year holds at most report year minus anchor
   plus 1 values (its anchor's staircase limit); an aggregate of
   several years printed by age runs deeper (4242/2021's
   "2015 & Prior" reaches "Ten Years Later"), and its last step is
   not a movement in the report year.  "All prior years", "Earlier"
   and "YYYY ae" are not read as cohort labels ("2013 ae" binds as
   the single year 2013).  Section 12.2 describes the layouts.
3. Sort by year and record column indices.
   **A date's year in a data column's header cell is not a cohort**
   (round 62, `_DATE_YEAR`). When a data column's cell holds exactly
   two years and one of them completes a printed date ("31 December
   2018"), the date is the title's and the other year is the column's
   cohort. Azure merged 3330/2018's net-table title "Net claims
   development as at 31 December 2018" into its first cohort's cell
   ("December 2018\n2011"); read as two cohorts, the cell shifted every
   column of the table by one, and the misread grid, which carried more
   filled cells than the gross table beside it, won the page: +0.208m,
   twice UW2012's net step, where the filing's gross development is
   -1.384m. The rule is limited to data columns because in the label
   column the first year of a merged header row stands in for the label
   column itself and the offsets depend on it (609/2018's whole header
   in one cell; 5820/2019's "At 31 December 2019 2017 Year of Account").
   Over all 23,175 cached Azure grids it changes the parse of that one
   grid (`tests/test_header_date_years.py`).
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
   year has enough development history, and from round 62 the PYD
   step reads them too (section 9.6).
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

#### 7.7.1  Which axis carries the classes (round 52)

Many segmental analyses are **transposed**: the classes run across
the header and the profit-and-loss items down the first column
(Beazley 2623/623: `2015 | Marine $m | Political risks &
contingency $m | Property $m | Reinsurance $m | Specialty lines $m`,
rows `Gross premiums written`, `Net premiums written`, ...).  The
row-wise parser returned those rows as classes, so 23 committed
records carried mixes such as "Gross premiums written 268.8 / Net
premiums written 239.0".  `_parse_transposed_lob()` now reads such a
table from its gross-premiums-written row with the header cells as
the classes; it needs two or more classes, at least one a recognised
class of business, and ignores note, year, units and "restated"
columns so an ordinary profit-and-loss statement is never read as a
mix.  Three further rules follow from the same review:

* a row-wise mix in which half or more of the labels are
  profit-and-loss items (`_is_pl_label`; "Pecuniary loss" and "Legal
  expenses" are classes and are not caught) is rejected;
* the prose fallback (`_parse_lob_from_text`) must find at least two
  classes -- a single line is a stray sentence, not a mix (2623/2015
  had returned one class at 4.0m for a 1.5bn book);
* the driver applied a deterministic mix over the models' when it
  had two or more classes or its single class agreed with a
  model-read premium total within 25%.  Round 58 replaced that rule
  (section 7.7.2).

#### 7.7.2  Partial tables and the reconciliation gate (round 58)

The frozen review of 21 September 2026 (M03) found 1856/2018's mix
to be three of its seven classes (14.2m of a 143.968m table): the
text fallback had read part of the segmental note, the driver wrote
the part's sum over both models' premium totals, and every later
check compared the mix with its own sum.  A census found 147 such
partial mixes.  Round 58 changed four things.

* **The gate** (`_lob_override_gate`): a deterministic mix replaces
  the models' mix only when its classes sum, within 2%, to a gross
  premiums written total one of the models read, whatever the number
  of classes.  Otherwise the models' mix is kept and the refusal is
  recorded as `[LOB NOT APPLIED: ...]`.  With no model total there is
  nothing to reconcile with, and the models' mix is kept.
* **Only the mix is applied.**  Each model keeps the premium total it
  read; the table's printed total (`table_total`) and its class sum
  (`class_sum`) are kept beside its mix in `_adobe_lob`, whether the
  mix was applied or not.  The text fallback writes no total, and a
  text mix is adopted only when its class sum reconciles within 2%
  with a premium total the filing prints
  (`gross_premiums_written_readings`, `reconciling_reading`).
* **The grid's own total.**  An unlabelled row equal to two or more
  classes above it, with no class after it, is the grand total (the
  largest such row wins, so "Total Direct" no longer stands for it);
  so is a profit-and-loss row carrying the class sum
  (`_sums_classes_above`; 780/2015's "Net technical result" had been
  read as an eighth class).  A printed total more than 2% from the
  class sum, with or without the RITC rows, refuses the grid; so do
  classes that carry no premium.  Only unlabelled, section or total
  rows are dropped as subtotals (`_drop_subtotal_rows`), a label-only
  row takes the amounts on the row beneath it, "2023 (Restated)" and
  "2023*" open the comparative section (`_year_section_divider`), and
  amounts are stored unrounded.
* **Tagging.**  A grid tagged both premium mix and provisions is read
  as a premium grid when its first rows say "gross premiums written"
  (`_admits_premium_grid`; 1856/2018's note carried a "Net technical
  provisions" column).

Known limits: the table parser takes its unit from the amounts'
magnitude, so a small syndicate's £'000 table can read as £m (the
gate refuses such a table in a model record; first-year stubs have
no gate); and a printed total with a leading currency sign
("£ 430,858") is not read as `table_total`.

#### 7.7.3  Bracketed class premiums (P-29)

Until the review of 2 October 2026 every table reader stored a class
premium printed in brackets as positive.  1414/2016's "Motor (other)
(294)" was +0.294: its classes summed to 574.063 against the table's
573.475, and the class took weight in a mix where the analysis gives
a negative class none.  A class printed in brackets among positive
classes now keeps its sign, in the row reader, the transposed reader
and the page-text reader (`_keep_bracket_signs`); a column printed
wholly in brackets is a presentation of outflows and is read as
positive, as before.  In page text a bracket is a sign and a hyphen
is not.  With the signs:

* the classes sum to the printed total (1414/2016's 573.475,
  4472/2019's 1,687.2, 1967/2020's 417.528, 1686/2019's 1,142.575).
  The gate had applied
  those four tables' mixes already, within its 2%, with the bracketed
  class's sign wrong; it now also applies six it had kept out, whose
  unsigned classes were further from the models' total (780/2020,
  1110/2017, 1882/2017, 1884/2021, 1884/2022 and 2468/2020);
* an unlabelled row equal to the classes with their signs is a total
  (`_sums_classes_above`: 3330/2014's 78);
* the units are read from the classes' sizes, so a sign does not
  change them (`_units_size`: 780/2020's classes sum to 8,309 $'000
  with Motor's (1,537) and to 11,383 without);
* classes whose signed sum is negative are refused: 2468/2021's
  run-off table, total (2,190), is no mix.

`tests/test_bracketed_premiums.py` holds the review's four records to
their tables, and checks every committed premium grid the reader
admits: a class printed in brackets among positive classes is read
negative.  The records were regenerated offline on 3 October 2026 (section 9.1): of the 141 regenerated, 82 now carry a
bracketed class with its sign, and each of the review's four sums to its table's total (1414/2016's classes sum to 573.475,
not 574.063).  The 82 are counted by position in the stored mix: a record is counted when, at some position of a model block's
mix (or of a stub's mix), the class was positive in the record of 5a6883d0 and is the same size and negative in the
regenerated one.  An earlier count of 81 keyed the classes by name and so missed 1955/2021, whose mix holds two classes
named Aviation (the first, "(160)" under Direct Insurance on page 42, is the bracketed one; the second, 3,985, is a
Reinsurance class).

#### 7.7.4  Year-of-account and calendar-year columns (P-30)

Ark's managing agent's report (syndicates 4020, 3902 and 6105) prints
each class's premium by year of account and by calendar year: "2015
YOA estimate | 2014 YOA estimate | 2013 YOA estimate | 2015 Cal. Year
| Restated 2014 Cal. year".  The grid names no premium and its first
header year is a comparative's, so the parser read none of these
tables and the mixes were the models'.  6105/2015's adopted reading
took the 2015 year-of-account column (43,178) where the premiums
written are the calendar year's (43,859, the income statement's
figure), and 3902/2019's took the year-of-account column scaled to
the calendar total.  `_yoa_calendar_column` now names the report
year's calendar-year column when the header prints year-of-account
columns, whichever header row carries the year and the label; the
gate holds the mix to a model's total before it is applied.  The
rule reads 20 committed grids, all Ark's, and in each the classes
sum to the calendar column's total, which is the premium every model
read (`tests/test_yoa_calendar_column.py`).  Regenerated on 3 October 2026,
20 of the 21 Ark records carry the table's mix (6 did before).  A record carries it when a model block's stored mix equals
the mix its table step read, class by class and amount by amount, and a stub carries it when it stores a mix; 3902/2017, a
stub with no mix, is the one that does not.  Of the 21 stored mixes, 14 are the same before and after and 7 differ, and
what moved in the 7 is counted three ways.  The class amounts moved in 5 (3902/2019, 3902/2023, 4020/2019, 6105/2014 and
6105/2015).  The class names or amounts moved in 6, which adds 4020/2014, whose class names changed and whose amounts did
not.  The mix differs in 7 only if the stub 4020/2015 is counted, whose mix is newly stored (it held none).  6105/2015's
calendar column sums to 43.859 where the adopted reading's year-of-account column gave 43.178, and 3902/2019's gemini reading,
scaled from the year-of-account column, now reads 42.498, 22.16 and 24.797.

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

The first non-null result is considered downstream for both LLMs.  It is applied
only when the agreement, resolved-unit, or tie-break rule in section 10.6 permits
the override.  Otherwise the model values are retained and the conflicting table
amount is recorded for audit.  For example, a resolved table value of 200 against
agreeing model values 100 and 100 follows this no-override branch.

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
| d = 1  | 3 (2016, 2017, 2019) |
| d = 2  | 2 (2016, 2017)       |

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
For each underwriting year column u (mature: u <= report_year - 2):
  current_estimate  = the cell on the report-year diagonal, row report_year - u
                      (row 0 is the end of the underwriting year)
  previous_estimate = the cell one row above it (the previous diagonal)
  pyd_for_year      = current_estimate - previous_estimate
```

Until the review of 2 October 2026 the current estimate was the column's last filled cell, wherever it
lay. 6112/2016's 2013 column carried a stray "7" one row past its 48-month estimate and the figure was
-19.264m where the filing shows +0.893m; 1967/2014's year-of-account results note was read as a
triangle; 1910/2019 lost its deepest row; 2791/2015 read 139,326 as 139.326. Now
(`_diagonal_cells` in `test_gemini.py`):

- a grid that starts one year later is read one row up throughout (that reading places more mature
  columns' last cells on their diagonal than the plain one); an empty row inside the grid is dropped;
- cells beyond a column's staircase are not estimates: the column is read only when the table's printed
  current estimate is its staircase cell; a column one row short is read only when the printed current
  estimate is the missing cell, which then stands in for it; otherwise the grid is refused;
- the printed current-estimate row ("Current estimate of cumulative claims", "Estimated total
  losses", "Total ultimate losses") is kept by `_parse_nutrient_triangle` as `current_estimate_row`;
  a summary row stripped from the grid (section 9.2) stands in for it. A printed estimate that is not
  the diagonal cell refuses the grid, unless the two are one figure a factor of 1,000 apart (2791/2015)
  or the printed value is the column's sum (a table of yearly movements, refused: 382's tables); a row
  with a value that cannot be a reading of its column (two cells run together) is not used;
- a negative cell in a mature column refuses the grid (a cumulative estimate is not negative; a grid
  printed wholly as outflows is normalised first);
- a step whose smaller estimate is under 2% of the larger refuses the grid (`MIN_STEP_RATIO`);
- a column with nothing after its first cell is read as before: nothing to difference.

`scripts/triangle_census.py` runs the reader before and after this change over every committed grid and
writes `pdf_extraction/audit/stage2_triangle_census.json`; `tests/test_triangle_diagonal.py` holds it to
the reader and the records.

**Regenerated on 3 October 2026** (the PC steps; `python test_gemini.py --stems <list> --offline --table-backend azure`,
from the committed caches, no call). The RAG step was first run offline over all 1,065 filings under the
pre-stage-2 code (f4fdf559) and under this one, on the same inputs, and the 157 records whose result differs, or that
the census or the brief names, were predicted; 141 were regenerated. Eight moved their development figure, each as
predicted: 1910/2019 5.0 to 5.5, 2007/2016 61.3 to 54.8, 2007/2017 -22.0 to -44.5, 2791/2015 -141.318 to -2.131,
5000/2017 25.0 to 24.0, 6111/2015 0.0 to 0.49, 6112/2016 -19.264 to -0.9 (the table's +0.893 has the opposite sign to
both models' -0.9 and is vetoed, section 10.3) and 727/2019 6.785 to 8.894. 94 moved their business mix (7.7.3, 7.7.4).
Thirteen records reach the page-vision step on the refused triangle, for which no response was cached under the current
prompt (1400/2014, 2010/2014, 2121/2019, 2999/2022, 3002/2021, 3622/2023, 3624/2023 and 382's 2015 to 2020): offline that
is a cache miss and the record keeps its committed figure. Three more would be written as no deterministic reading and
leave the working sample: 1967/2014 and 1991/2018 reach no page-vision step (1967/2014's filing prints no claims development
table; 1991/2018's gross triangle, on PDF page 30, matches one of the page finder's patterns where it needs two), and
3500/2018's served page is refused too, with no reserve text or loss-ratio grid behind it. None of the 16 was regenerated at
that point; each was declared in `redecision_pending.json`. The census then counted 15 refused triangles with no committed
page-vision entry (its `rag_replay_stops_on_a_cache_miss`, which said that the replay stops on a cache miss for every one);
13 of them reach that step, and 1967/2014 and 1991/2018 do not. It now walks the step with the pipeline's own code and counts
the three apart: `rag_refused_with_no_cached_vision_page` (the 15, then), `rag_replay_stops_on_a_cache_miss` (the 13) and
`rag_refused_reaching_no_page_vision` (the 2).

**Option B: the page-vision calls (3 October 2026, 16:40 to 16:44).** The author chose to pay for the page-vision calls of the
pages the step reaches, and the main session made them. Each is one call of the pipeline's own page-vision step (one page
image to gemini-2.5-flash, prompt 2.13, unchanged since 15 March 2026), one attempt per page, 12 pages of 11 of the 13
records. 2121/2019 (page 56) and 3622/2023 (page 36) were left out: a response to the same prompt text from an older driver
version (2.8, cached on 18 March 2026, and 2.10, on 5 July 2026) is cached for each, and an unchanged prompt is not run
again. 12 attempts, 12 results, every response parsed and cached (12 files in `pdf_extraction/llm_cache/`): 44,541 tokens
(prompt 6,648, response 8,477, thinking 29,416) and an estimated US$0.0967 at the pipeline's price table (the prompt at
the input rate, the response and thinking tokens at the output rate; it is not a provider's bill). No run manifest holds
them (`run_manifest.json` records runs of `test_gemini.py`); the table below does. Each reading was compared with its page,
cell by cell, against the page's own text:

| Record | Page | Tokens | Est. US$ | The reading against its page |
|---|---|---|---|---|
| 1400/2014 | 8 | 2,749 | 0.005654 | no triangle: the page is the key performance indicators, and the reading says so |
| 2010/2014 | 20 | 2,955 | 0.006169 | agrees in 28 cells: the gross loss-ratio triangle, in percent |
| 2999/2022 | 48 | 6,851 | 0.015909 | **disagrees in all 55 cells**: see below |
| 3002/2021 | 38 | 3,004 | 0.006291 | agrees in 55 cells |
| 3624/2023 | 38 | 4,699 | 0.010529 | agrees in 55 cells |
| 382/2015 | 46 | 3,716 | 0.008071 | agrees in 66 cells: a table of yearly movements, transcribed as printed |
| 382/2016 | 46 | 4,169 | 0.009204 | agrees in 66 cells (movements) |
| 382/2017 | 47 | 4,052 | 0.008911 | agrees in 66 cells (movements) |
| 382/2018 | 46 | 4,381 | 0.009734 | agrees in 66 cells (movements) |
| 382/2019 | 46 | 3,277 | 0.006974 | agrees in 66 cells (movements) |
| 382/2020 | 46 | 1,489 | 0.002504 | no triangle: the page is the movement in technical provisions, and the reading says so |
| 382/2020 | 47 | 3,199 | 0.006779 | agrees in 66 cells (movements) |

2999/2022's reading drops the page's first column (2013, 262.7 down to 599.4) and puts every later column under the year
before: its "2013" column is the page's 2014 (189.1 down to 709.6), all 45 cells of the page's other nine columns are one
column to the left, and its "2022" column is blank. The 2021 cohort's first development (504.3 to 990.1, +485.8) therefore
sits among the mature columns. The reader finds each of its eight mature columns ending one row short of its report-year
diagonal, takes the grid for one that starts a year late (the offset rule of `_diagonal_cells`), reads it one row up and
accepts it: +858.1, where the page's own grid gives +370.5 (the last cell of every column is the printed current
estimate). The entry is cached because it is what the call returned; the record is not rebuilt from it, and the page's
figure, +370.5, is on the list for stage 3. The shape that let it through is a blank newest column under a one-column shift;
the reader does not test for it (a change to the reader belongs to a later stage).

Ten of the 11 records were then regenerated offline from the readings, each after its figure, route and mix had been
predicted, and every prediction held. Figures are the two models' (gemini-2.5-flash; gpt-5-mini where it differs):

- 3002/2021: -11.426 to -9.478, the page reading's figure (route `rag_triangle`); the mix is the models' own, unchanged.
- 3624/2023: 74.995 to 71.809 (route `rag_triangle`); the table's mix, whose class sum goes from 246.875 to 246.455.
- 382/2015: -15.848 to 15.637 (gemini-2.5-flash) and -3.686 (gpt-5-mini); 382/2016: -50.211 to -8.932; 382/2017: 49.14 to
  59.798 and 7.663. The reader refuses 382's movement tables (negative cells), so these records' figures become the models'
  own readings (route `model_reading`), and the two models disagree for 2015 and 2017. 382/2017's mix sum goes from 320.587
  to 319.553. 382/2018 (13.51 and 5.82), 382/2019 (173.514 and 12.549) and 382/2020 (7.269) keep their figures and route;
  382/2019's mix sum goes from 316.458 to 316.334.
- 2010/2014: the loss-ratio triangle is refused as not a claims triangle, and the record keeps its figures (-0.917 and none).
- 1400/2014: its stored triangle was a net one-column grid of yearly results (15,660, 13,362, 201, 0, -3,833 and -6,131,
  £000), which the reader refuses, and its page held no triangle, so with no figure from any other route and no reserve
  text it is written as no deterministic reading (unread, the models not run). Its figure, -2.298, and its six-class mix are
  gone, and it has left the working sample.

They left `redecision_pending.json`. Six of the 16 remain declared, each keeping its committed form: 2999/2022 (above);
2121/2019 and 3622/2023, whose only response is from an older driver version, which the cache does not serve (read through
the reader offline it gives +57.034 and -4.8; serving it needs a cache lookup across driver versions, a later stage's
decision); and 1967/2014, 1991/2018 and 3500/2018, each of which would be written as no deterministic reading and leave the
working sample, a decision for the author (1400/2014 was written so, as its page held no triangle).

The 2 most recent UW years are excluded because they have
insufficient development history (only 1 or 2 data points).

### 9.2  Summary row detection and stripping

LLMs (and some API backends) sometimes include a "Current
estimate of cumulative claims incurred" summary row at the
bottom of the triangle.  This row duplicates the last non-null
value from each column.

**Detection**: if the last row is fully filled and >= 70% of its
values match the last non-null above (or the same figure a factor of
1,000 apart: 6111/2015's total row prints 65.779 under 65,779), it is a summary
row. Zeros beyond the staircase are read as no data before this test
(5000/2017's last development row matched the dash-zeros above it and
was stripped). The stripped row is the table's current-estimate row,
and section 9.1 reads it as one.

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

- **PYD = 0** is stored: a software convention for a record that
  carries no prior-year reserves, not a finding that no development
  occurred
- **PYD% = 0%** is what the pipeline stores: development of zero on
  reserves of zero is 0/0, undefined, and the stored zero is a software
  convention for a record that carries no prior-year reserves. Zero opening
  reserves do not themselves establish that no subsequent development occurred;
  the analysis excludes such records on the reserve test (opening reserves
  below 0.1m), not on this value
- **Non-zero RAG PYD is rejected**: when opening reserves = 0
  and the RAG triangle computes a non-trivial PYD
  (|PYD| > 0.1m), it is discarded.  This catches cases where
  the deterministic extraction picked up a **net** triangle
  (which may have large movements) instead of the gross
  triangle (which has no prior year claims).

All PYD% calculations use a three-way branch:

```python
if pyd == 0:
    pyd_pct = 0.0        # stored convention: 0/0 is undefined
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

Real claims development triangles rarely contain values that look like
calendar years, but the monetary ranges overlap the year range
(thousands: 1,000--500,000 plainly contains 1980--2030), so the rejection
below is a heuristic that can reject a genuine amount printed as a bare
four-digit year-like number, not an impossibility argument.

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

Triangles with structure score < 0.5 are rejected. Until round 56 that
sentence described nothing: `compute_pyd_from_triangle()` computed the
score, printed it and used the triangle anyway, and 780/2018 supplied a
-225.1m "release" at a score of 0.38. The threshold now lives in
`MIN_TRIANGLE_STRUCTURE_SCORE` and the function returns no figure below
it; `tests/test_round56_rules.py` reads the constant out of the code and
checks this sentence against it.

The score is taken **after** one repair, not before it. A cell beyond its
column's development age cannot hold an estimate, so an exact zero there
is a dash the backend read as nil and is set to no-data
(`_null_zeros_beyond_the_staircase`). 780/2018's grid carried 22 of them,
and the diagonal walk had been differencing `0.0` against a real estimate.
Scoring before the repair would reject the grid instead of reading it.

**A one-column triangle is scored on its own staircase** (round 62,
`_single_cohort_staircase`). The column-by-column comparison above has
nothing to compare one column with, and the function used to return 0.0
for any grid with fewer than two columns. That clause dates from March;
it cost nothing until round 56 made the score binding, and from then on
every one-column triangle was refused however complete it was. The corpus
holds two, and both were written as reports with no triangle, with
neither model run: 2468/2022 (UW2020: 29,267, 28,431, 28,278 in £'000,
-0.153m) and 2255/2015 (UW2011, 330,725 - 347,848 = -17.123m). A single
column now scores 1.0 when all four hold, and 0.0 otherwise:

- its underwriting year is a usable cohort, `u <= t - PYD_EXCLUDED_RECENT_UW_YEARS`;
- it has at least two filled development rows;
- its last filled row sits exactly at the column's own age,
  `depth == t - u + 1` (the limit `_staircase_limit` gives it), so the
  latest value is the report-year diagonal and not an earlier estimate or
  a summary row printed below the column;
- the row above that is filled, so a previous diagonal exists.

Measured on the committed caches over all 1,065 filings, with only this
function swapped: the RAG step reports a different outcome for those two
filings and no other, and `depth <= t - u + 1` in place of equality
changes nothing.  The models' own triangles are each model block's
`_claims_triangle` in the committed records, and
`scripts/count_model_triangles.py` counts them.  In the records before
round 62 (11b1bc36), 1,596 blocks carry a claims triangle, 1,547 of them
with development rows and three with one column (GPT's, for 1206/2019,
1980/2018 and 5820/2019), and the figure changes for two -- 5820/2019,
where the RAG figure is applied first, and 1206/2019, where the code
figure (+7.824m) meets the same sign veto as the RAG figure did and the
adopted figure stays as it is.  In the records
now, 1,570 hold development rows and seven have one column: those three,
and both models' triangles of 2468/2022 and 2255/2015, extracted again on
29 September 2026, whose figures (-0.153m, -17.123m) are the RAG step's.
`tests/test_single_cohort_triangles.py` holds each condition and these
counts.

### 9.7  Percentage against monetary triangles

**Function**: `compute_pyd_from_triangle()`, unit check;
`_triangle_units()` in `table_extraction.py`.

Some syndicates (notably Beazley syndicate 2623) present claims
development as **cumulative loss ratios** (percentages) rather
than absolute cumulative claims amounts, and a claims triangle
reported in millions can have every value below 200 as well, so
magnitude alone cannot tell the two apart.  The decision is made
from the triangle's own unit evidence first (round 55, T03):

- a ratio or percent marker in the table text makes the triangle
  a **percentage** table (`units = "percentage"`), which takes the
  loss-ratio route of section 9.8 and is never read as money;
- a thousands or millions marker in the table text gives that
  monetary unit with `units_evidence = "header"`, and the model
  prompts return an explicit `millions|thousands|percentage`; an
  evidenced monetary triangle is never rejected on magnitude, so
  the same triangle in millions and in thousands gives the same
  movement;
- when the text carries both a monetary marker and a ratio or
  percent marker (a ratio grid beside a monetary total row; a
  monetary triangle on a page that mentions a combined ratio) the
  monetary unit is kept with `units_evidence = "conflict"`, and the
  magnitude heuristic below still applies, so the equivalence above
  is guaranteed only for a table whose unit evidence is unambiguous;
- only for `units_evidence` of `"default"` or `"conflict"` does
  the magnitude heuristic apply: if all of at least four non-null
  values lie in 0--200 the triangle is read as a loss-ratio table
  and rejected with a note naming the heuristic.  That fallback is a
  heuristic with false positives, not a proof.

```
triangle has all 21 values in 0-200 range (max=66.5) with no
evidenced unit — read as a loss ratio triangle by the magnitude
heuristic, not a claims development triangle
```

`tests/test_unit_equivalence.py` holds the million/thousand
equivalence, the percentage route and the default-unit fallback.

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
Accordingly, the loss ratio PYD is a **conditional fallback**:
it fills an LLM blank and otherwise retains an LLM-extracted
syndicate-level value, unless that value's direction contradicts
the deterministic loss-ratio result (see section 10.3).

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

### 10.1  Comparison tolerances

The two readings are then compared field by field. A numeric field is a **discrepancy** when the values
differ by more than **0.5% of the larger** *and* by more than **0.05** in absolute terms
(`_is_numeric_near`, from `COMPARISON_REL_TOL` and `COMPARISON_ABS_TOL` in `test_gemini.py`); a missing
value and zero are the same value. Exempt from it are text differences, any field whose name carries
`page` or `confidence`, and the list fields `named_events`, `prior_year_events`, `raw_causal_phrases`,
`specific_events`, `specific_years_affected`, `lob_movements` and `primary_causes`. A `gross_premium_mix`
percentage that fails is compared again on absolute values within **5%** (`MIX_PERCENTAGE_REL_TOL`),
because a negative written premium leaves its sign convention ambiguous.

A discrepancy is a comparison-stage flag, not a rejected record: `resolve_computed_fields` settles the
derived fields next, and what remains is written to the disagreement log and counted in the record's
`hard_failures`.

### 10.2  Triangle PYD resolution

When both models extract triangles:

1. Compute PYD from each triangle in Python.
2. Score each triangle's structure.
3. **Both agree** (difference < 1m): use average, apply to both.
4. **Disagree**: pick the triangle with better structure score.
   If scores are similar (+/- 0.1), skip both (insufficient
   confidence).
5. **Only one has triangle**: use it if it passes sanity checks.

### 10.3  RAG override priority (canonical PYD hierarchy)

This section is the canonical statement of the PYD source
hierarchy; every other document defers to it.

1. When the deterministic table extraction produces a valid
   triangle PYD, it is ordinarily authoritative.
2. Where the gross claims-provisions movement is also
   available, the two are compared (section 11.3.1).
3. **If the provisions table is an affirmed movement note whose
   column is bound to the report year (R138), and the two signs
   disagree, the provisions movement is authoritative and
   overrides the triangle**; the override is recorded in
   `data_quality_notes`. Without both conditions the triangle
   stands whatever the sign: 1274/2019's `2010 & prior years`
   cumulative total displaced a correct -6.619m before R138. This matters most for
   RITC acceptors, where the triangle tracks only organic
   development (see the RITC caveat below).
4. Otherwise the absolute-amount triangle PYD replaces both
   LLM-extracted values -- however close an LLM value is -- and any
   LLM override is logged, subject to the round-52 gate: the
   deterministic figure is **not applied** when both LLM values
   agree in sign with each other and it has the opposite sign, or
   when it implies a movement above 50% of opening reserves while
   both LLM values imply under 10% (`_pyd_override_gate`).  The
   models' values then stand and a `[RAG PYD NOT APPLIED]` note
   records the figure.  The corrected page binding of round 52
   exposed deterministic figures that were a wrong-year provisions
   column or a mis-columned triangle; the gate is the safeguard.
   The same gate guards the earlier code recomputation from the
   models' own extracted triangles (`verify_triangles`, note prefix
   `[CODE PYD NOT APPLIED]`): 1084/2022 and 510/2018 had reached
   the record by that path (+581.7m and +429.3m against two models
   agreeing on a release) once the RAG triangle was blocked.  A
   deterministic figure therefore displaces two agreeing model
   values by none of the three routes, with one exception: a
   figure two readings of the filing confirmed by hand is applied
   over this gate (R213; the precedence table below).
5. Where no absolute-amount triangle yields a PYD, a
   loss-ratio triangle is a conditional deterministic fallback.
   Because it is ordinarily managed- or group-level, it fills an
   LLM blank and otherwise retains the syndicate-specific LLM
   value, unless the two directions contradict; a contradiction
   is resolved in favour of the deterministic loss-ratio result.
   It never overrides an absolute-amount triangle.
6. When no deterministic source is available, the reconciled
   dual-LLM text extraction is used.

**Precedence of the checks on a deterministic development figure.**
The rows are in the order `process_one_report` applies them to the
figure from an absolute-amount RAG triangle.  This table is the one
statement of which figure wins; the README's summary points here.

| Order | Check | Outcome | Note written | Code |
|---|---|---|---|---|
| 1 | Sanity: the figure implies more than +200% of opening reserves, or is non-zero against zero opening reserves | discarded; the model values stand | printed | `process_one_report` |
| 2 | Hand confirmation: the figure equals, to half a thousand, one that two readings of the filing confirmed (`pdf_extraction/audit/triangle_figures_confirmed_by_hand.json`; an entry needs two readings, pages, a quote and the figure, or it is refused) | applied over the check in row 3, for that record and that figure only | `[RAG PYD APPLIED OVER THE SIGN VETO ...]` | `_rag_veto`, `_hand_confirmed_figure` |
| 3 | Model agreement: both model values agree in sign and the figure has the opposite sign, or the figure implies above 50% of opening while both models imply under 10% | not applied; the model values stand | `[RAG PYD NOT APPLIED ...]` (`[CODE PYD NOT APPLIED ...]` on the code recomputation route) | `_pyd_override_gate` |
| 4 | Otherwise | the figure replaces both model values, however close they are | the override is logged | `process_one_report` |

The gross claims-provisions comparison (items 2-3 above,
section 11.3.1) and the loss-ratio fallback (item 5) are separate
from these rows: a loss-ratio triangle never passes row 4, and it
never overrides an absolute-amount triangle.

An absolute-amount RAG triangle is computed deterministically
from the claims development table and takes precedence over an
LLM-extracted figure **unless a gate rejects it**.  Its authority
is therefore conditional, on four counts and not one:

* a gross provisions movement whose sign disagrees with the
  triangle overrides the triangle, but only from an affirmed
  movement note whose column is bound to the report year (R138,
  section 11.3.1);
* `_pyd_override_gate` withholds the triangle value when both
  model values agree in sign with each other and the triangle has
  the opposite sign, or when the triangle implies a movement above
  50% of opening reserves while both model values imply under 10%;
* that veto is itself lifted where the figure equals, to half a
  thousand, one two readings of the filing confirmed in
  `pdf_extraction/audit/triangle_figures_confirmed_by_hand.json`, for that
  record and that figure only, and the note says so (`_rag_veto`;
  row 2 of the precedence table in section 10.3);
* a loss-ratio triangle is a conditional fallback, never an
  override: see the exception below.

When the gate withholds the triangle the model value is retained,
and what that value's basis rests on changes with it. Agreement of
two model signs is evidence about the sign, not about whether the
figure is gross or net: a gross and a net movement can share a
sign. The basis of a retained model value is therefore whatever
the models state for it, which the analysis reads before it treats
any figure as gross (round 53).

**Exception -- loss ratio triangles**: when the RAG PYD comes
from a loss ratio triangle (`method = "loss_ratio_triangle"`),
it is treated as a **conditional fallback**.  Loss ratio triangles are
typically at managed/group level (e.g. "Beazley managed level")
rather than syndicate level.  The managed-level PYD can differ
from the syndicate-share figure in both magnitude and
direction.

- If an LLM extracts a PYD value from narrative text (e.g.
  "the syndicate released prior year reserves of $150.8m"),
  that syndicate-level value is **kept when its direction agrees**
  with the loss-ratio result. If their directions contradict, the
  deterministic loss-ratio result overrides it and the direction
  override is logged.
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

This override (for non-loss-ratio triangles, and subject to the
gate above) is necessary because LLMs sometimes extract PYD from the
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

**Source decision rule** (the conditional form of the canonical
hierarchy in section 10.3; this table is not an unconditional
ranking):

| Step | Source | Applies when | Gross/Net |
|------|--------|--------------|-----------|
| 1 | Deterministic *absolute-amount* triangle PYD, from a table on a page bound to the requested syndicate (section 10.8) | A valid triangle was parsed and neither veto withholds it. **Closed-year exception:** the page may be in the annual accounts *or* in an underwriting-year (closed-year) section — a claims-development triangle there is the same syndicate's triangle and is admitted, while a provisions movement, opening reserve or business mix in that section is not (`_closed_year()`, section 10.8). **Unit veto:** the triangle's own unit evidence decides percentage against monetary before any magnitude test (section 9.7); a percentage triangle takes the loss-ratio route instead. **Conflict veto:** `_pyd_override_gate` withholds a deterministic figure that has the opposite sign to two agreeing model values, or that implies above 50% of opening reserves while both models imply under 10%, unless the figure is one two readings of the filing confirmed (`pdf_extraction/audit/triangle_figures_confirmed_by_hand.json`, row 2 of the precedence table in section 10.3), which is applied over that veto | Gross |
| 1a | Deterministic gross provisions movement | Only when the provisions table affirms itself as a movement note *and* the column carries the report year in its own header, and then only where its sign disagrees with the triangle (section 11.3.1). A sign disagreement on its own is not evidence that the figure is a movement: `2010 & prior years` in a development triangle is a cohort's cumulative incurred total and is refused outright | Gross |
| 2 | LLM-extracted "Movement in prior year's provision" note | No deterministic source of steps 1 and 1a, or the gate withheld one | As stated by the models; gross only where they say so |
| 3 | LLM-extracted narrative text | As step 2 | As stated by the models; a narrative value declared net, or whose basis the filing does not state, is not admitted to the gross sample |
| 4 | Deterministic *loss-ratio* triangle PYD | Fills a blank LLM value; overrides a syndicate-specific LLM value only when their directions contradict; never overrides an absolute-amount triangle | Gross |
| 5 | LLM-extracted year-of-account result breakdown | No gross source | Net* |
| 6 | Narrative text net-of-reinsurance figure (parsed post-hoc, section 10.4) | Both LLM values are null and the narrative quantifies a net movement | Net |

\* Year-of-account results are inherently net of reinsurance.
The analysis repository records the basis of every figure it
uses and admits only gross-basis records to its working sample.

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

**Rationale**: the triangle-computed PYD is ordinarily the
prevailing source for the magnitude and sign of reserve
development (subject to the provisions sign-disagreement rule
of section 10.3).  The LLM `direction` field is a textual
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

#### 10.6.1  Proactive conditional RAG resolution (both models)

After LLM extraction completes, the pipeline checks whether
`_adobe_provisions` contains an `opening_gross_claims_outstanding`
value (from sections 7.8.2 or 7.8.3).

If available, the RAG value is considered only after its unit is
resolved. Evidenced units are necessary but not sufficient: the
two-of-three decision in step 2 determines whether it is applied
(round 52, review finding M01):

1. The table parser scales the figure from the table's header
   rows, then the page text, then the document's unit declaration
   ("amounts are rounded to the nearest thousand", `$'000` note
   headers on two or more pages), and only then from magnitude (a
   value above 50,000 cannot be millions for any syndicate).  The
   source is recorded in `opening_provenance.unit_source`
   (`header`, `page`, `document`, `magnitude`, `unresolved`),
   with the raw value, multiplier, page, entity and table kind.
2. The figure is then applied by a two-of-three rule
   (`_resolve_rag_opening`): it must agree with at least one model
   value within 2% at scale 1, or with every model value at x1000
   or /1000 (then it is rescaled, whatever the unit source said:
   2988/2024's table read 347,898 under a mistaken document
   declaration), or the two model values must disagree with each
   other by more than 5% (the table breaks the tie, the earlier
   behaviour; 2357/2016 is the example).  When both models agree
   with each other and the table contradicts them at every scale --
   a wrong column (382/2018), a wrong entity, a sign flip -- the
   models stand and a `[RAG OPENING NOT APPLIED]` note records the
   table value.  The disagreement fallback of 10.6.2 goes through
   the same rule.  A negative or zero opening balance is a misread
   column and is never returned by the parsers.
3. When applied, both models' `opening_reserves_gbp_m` are set to
   the RAG value, `prior_year_development_pct` is recomputed, and
   an override differing from the LLM value by >= 0.5m is logged
   as `[RAG OVERRIDE]`; `opening_reserves_provenance` carries the
   applied value and the unit resolution.

The frozen review's case: syndicate 1416/2024's cached provisions
table had lost its `US$000` marker, the parser treated 46,378 as
millions and overrode the models' correct 46.378, and the
syndicate entered the analysis with £37bn of reserves.  With the
document declaration on the accounting-policies page the value
resolves to 46.378; without it the models' agreement would have
decided; with neither, nothing would have been overridden.

Opening-reserve resolution is conditional, not deterministic-table
authority. An explicit-unit table value of 200 against two agreeing
model values of 100 and 100 is recorded but not applied: agreement at
scale 1, compatible unit rescaling, or model disagreement is still
required. For PYD, deterministic authority is scoped, within the
section 10.3 hierarchy, to an **absolute-amount** triangle, and it is
qualified three times over: triangle-versus-provisions;
triangle-versus-model through
`_pyd_override_gate`, which withholds the deterministic figure
against two agreeing model signs or an implausible magnitude; and
the hand confirmation that lifts that veto where the figure is one
two readings of the filing confirmed (`pdf_extraction/audit/triangle_figures_confirmed_by_hand.json`, section 10.3).  A
**loss-ratio** triangle is a conditional fallback instead: being
managed- or group-level it fills a blank narrative value and
overrides a syndicate-specific one only where the two directions
contradict.

**Log messages**:

```
  [gemini-2.5-flash] Opening reserves confirmed by RAG balance sheet: 12.121 -> 12.121m
  [gpt-5-mini] Opening reserves overridden by RAG balance sheet: 78.049 -> 12.121m
```

#### 10.6.2  Disagreement fallback resolution

**Function**: `resolve_computed_fields()` (`test_gemini.py`)

If the proactive override did not fire (no RAG value was
available at that stage) and the two LLMs' `opening_reserves_gbp_m`
is a **hard failure** of the comparison stage, the pipeline
re-checks `opening_gross_claims_outstanding` from the provisions
dict.

A hard failure is what `check_tolerance()` does not tolerate: for a
numeric field, values differing by more than `COMPARISON_REL_TOL`
(0.5%) of the larger **and** by more than `COMPARISON_ABS_TOL`
(0.05, in the field's own units --- £m for a reserve figure). Both
must be exceeded, so £100.0m against £100.04m is tolerated on the
absolute tolerance alone and £100m against £103m is a hard failure.
The 5% this paragraph used to name was a superseded threshold
(frozen review of 25 September 2026, M03); the 5% that remains in
force at step 10.5 is `MIX_PERCENTAGE_REL_TOL`, which is a different
rule for premium-mix percentages, and the 2% and 5% in §10.5.1 are
the RAG opening resolution's own two-of-three thresholds
(`RAG_OPENING_REL_TOL`, `RAG_MODEL_DISAGREEMENT_TOL`). A hard failure
is logged for adjudication and **excludes no record**: see §10.7.

If available, the RAG value is sent through the same two-of-three
rule in section 10.6.1. It overrides both models and the hard failure
is reclassified as auto-resolved only when that rule applies it; two
agreeing models retain their value against a contradictory table at
every compatible scale. This path handles cases where the RAG value
was injected late (e.g. from a reserves movement note for RITC
syndicates).

#### 10.6.3  Rationale and common LLM errors

LLMs frequently confuse opening reserves with other balance
sheet figures:

| Wrong source | What it actually is |
|--------------|---------------------|
| Member's balances | Equity, not claims reserves |
| Total technical provisions | Includes unearned premiums |
| Net claims outstanding | After reinsurance deduction |
| Reinsurers' share (assets) | Only the ceded portion |

The provisions-movement parser reads the **current-year** gross
column: the block whose own header cells carry the report year,
else the first gross block (movement notes print the current year
first and the comparative after it).  Before round 52 it took the
last gross column, the prior-year comparative.

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

### 10.8  Entity binding and section kind (combined filings)

Some managing agents file one document for several syndicates
(Tokio Marine Kiln: syndicates 510, 557 and 308 for 2014-2019;
Hiscox: 33 and 6104 for 2014-2024; a dozen special-purpose
syndicates filed with their hosts), and most filings append
three-year *underwriting-year* (closed-year) accounts after the
annual accounts.  Before round 52 the backends took the first
matching table in the document, so 510/2018 and 510/2019 carried
syndicate 557's reserves and 6104/2015, 2016, 2018 and 2024
carried syndicate 33's (review finding M02).

Every page is now assigned an **entity** (the syndicate whose
section it belongs to) and a **section kind** (`annual` or
`underwriting_year`) by `page_sections()` in
`table_extraction.py`:

1. A filing that prints a chapter index on its pages (the
   HTML-converted Hiscox filings: "Chapter 3 / 59 / Hiscox
   Syndicate 6104 / annual accounts") is sectioned by each page's
   printed page number against that index.
2. Otherwise a same-line section marker decides -- "Syndicate 510
   Annual accounts under UK GAAP", "Hiscox Syndicate 33 annual
   accounts", "Syndicate 510 Underwriting year accounts" -- when
   it heads its line.  A list such as "Syndicates 510, 557 and
   308" or "Syndicates 0033 and 6104" names every member and is
   never a marker; a cross-reference inside a sentence is not one.
3. A page without a marker that names exactly one relevant
   syndicate (the requested one, or a companion with markers on
   two or more pages) takes that syndicate; every other page
   inherits the previous page's entity.
4. The kind is decided by the page's own evidence: a marker of
   underwriting-year kind, a title line "Underwriting year
   accounts", or a statement heading for a closed year of account
   or a 36-month period.  A policy note that mentions closed years
   does not make its page a closed-year page.

A table on a companion syndicate's page is never admitted.  A
table in an underwriting-year (closed-year) section is not admitted
as a provisions movement, opening reserve or business mix; a
claims-development triangle in that section is the same syndicate's
triangle and is admitted.  Which admitted triangle is used is the
backend's rule: the Azure path keeps the first admitted triangle
unless a later one is gross over net or carries more underwriting
years, without consulting the section; the Adobe path additionally
scores the annual-accounts section above a closed-year one
(`_closed_year()` in both backends); the counts
of skipped tables and the entity/page map are recorded in the
output under `_entity_binding`, and every admitted table carries
`source_page` and `entity`.  When no admitted table yields a
figure, the reconciled dual-LLM values stand (they were read
from the whole document with the syndicate named in the prompt,
and for the combined filings above they were correct).

#### 10.8.1  Cached page mapping

The slim PDF sent to Azure is assembled in ascending page order,
but caches written before round 52 recorded each table's page
through the priority-sorted batch, so their `orig_page` values are
scrambled whenever priority order differs from page order.  New
caches record pages through the order actually sent
(`_page_mapping: ascending-v1`); legacy caches are remapped on
load by reconstructing the batches as sent
(`remap_cached_page`) and the result is verified against the
page whose text contains the table's own numbers
(`locate_table_page`).  The committed caches are the record of
the Azure run and are not re-fetched.

#### 10.8.2  Offline re-extraction

`python test_gemini.py --single syndicate_NNNN_YYYY --offline`
re-runs a record from the committed LLM and table-backend
caches; any cache miss aborts the run instead of calling an
external API (`LLOYDS_EXTRACTION_OFFLINE=1`), so a
re-extraction changes only what the parsing rules change.  In
offline mode a cache whose relevant-page set no longer matches the
current page classifier is still used, with table pages located
from their own numbers.

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

Reports are classified before expensive API calls to save cost. A report is first-year when nothing in it shows
development on mature cohorts or a disclosed prior-year movement. That is decided from the report itself: its
triangles before the models run (11.2), and its triangles and reserve text after they have (11.1).

### 11.1  First-year reports (round 58)

**Functions**: `_no_mature_cohort()`, `_figure_in_text()`, `_first_year_record()` (`test_gemini.py`)

Until round 58 the pipeline also looked up the syndicate's first underwriting year (`is_early_year_syndicate()`,
the cache below, and a Perplexity query on a cache miss) and flagged a report when
`report_year < inception_year + 2`. The flag never skipped a report on its own: the triangle check overrode it. Its
one effect was the cache correction that lowered a cached year to a triangle's earliest cohort, which moved 1884 from
2015 back to 2012 on a triangle carrying cohorts reinsured to close into it. The check, the lookup and the
correction were deleted in round 58 (the frozen review of 21 September 2026, M01).

**After the models** (`process_one_report()`, after `verify_triangles` and the net narrative fallback), a report is
written as a first-year stub when all three hold:

- the RAG step (triangle, provisions or narrative) returned no development figure;
- no triangle in the record, the RAG step's or either model's own, holds an underwriting year up to t-2;
- no model's figure is printed in either block's reserve text (`_figure_in_text()`).

The stub carries its reason and the evidence: the triangles' underwriting years and the figures the models gave.
1884/2016 is written this way: its triangles hold 2015 and 2016 only, one model left the figure blank and the other
took the 2015 year's closing outstanding less the whole opening outstanding (+15.044m), a figure its filing never
prints. 6130/2017 is kept: both models read "$267k of technical reserves in respect of prior periods" from its
filing.

**The inception cache** (`pdf_extraction/syndicate_inception_years.json`) is kept as a record and no step reads it
for a decision. Every path that writes it only adds a syndicate it does not know: the start-up backfill in
`_load_inception_years()` (a stored stub's `inception_year`, or the earliest underwriting year of the stored
records' triangles), the triangle learner (the triangle's earliest underwriting year) and `_first_year_record()`
(report_year - 1). None changes a known year, and syndicates in `_manual_overrides` are never changed. The years
the removed correction lowered stay as it left them (1884: 2012; the syndicate began underwriting in 2015).

### 11.2  First-year syndicate (triangle-based detection, before the models)

The RAG-lite extraction runs first and may detect a triangle with fewer than 3 underwriting years.

Every parser applies one rule, `table_extraction.triangle_admissibility()`, which uses
**usable cohorts** and never a column count:

- A UW year is "usable" for PYD if `uw_year <= report_year - PYD_EXCLUDED_RECENT_UW_YEARS`
  (i.e. there is a previous diagonal to compare against)
- No usable year in the triangle → `new_syndicate`, and `first_year_syndicate = True`
- A usable year, however few columns the triangle has
  → the triangle is parsed normally and PYD is computed. That is true of
  the PYD step only from round 62: until then `compute_pyd_from_triangle()`
  scored every one-column triangle 0.00 and refused it after the parser had
  admitted it (§9.6)
- A most recent UW year after the report year, or more than `MAX_UW_YEAR_LAG` behind it
  → not this report year's triangle at all

**Until round 61 the five parsers disagreed.** `_parse_nutrient_triangle()` applied the rule above.
`_parse_transposed_triangle()` and `_parse_transposed_triangle_from_text()` returned `new_syndicate`
on `len(uw_years) < 3` alone, so a two-column triangle whose earlier cohort *is* usable was
classified young by them and parsed by the nutrient parser. `_parse_triangle_from_text()` used the
same count to reject the page outright, with no first-year signal at all. And
`test_gemini._parse_triangle_xlsx()` used the count, read it *before* validating the year range, cut
triangles off at `report_year - 2` where the others allow `MAX_UW_YEAR_LAG`, and would not call a
triangle young unless its most recent UW year equalled the report year. A sixth copy of the rule sat
in the `tests/test_azure.py` diagnostic. All of them now call the shared function, and
`tests/test_triangle_admissibility.py` fails if any of them grows a count of its own again --- the
test tokenises every source in the repository, so a copy in a new file is caught too.

Three or more distinct UW years no later than the report year cannot all fall inside the most recent
`PYD_EXCLUDED_RECENT_UW_YEARS`, so for every triangle the nutrient parser used to accept the shared
rule reaches the same verdict; that is enumerated, not argued, in the same test file.

**What the alignment changed on this corpus: nothing that any route reports.** Replayed over the
caches, filing by filing: the Azure path reports the same triangle for all 1,055 cached filings, and
the Adobe path for all 55. The page-text parser returns `new_syndicate` for 111 pages it used to
reject, which raises no flag, because both of its call sites act only on a `TriangleData` --- making
them act on the string would change which records the corpus holds, and is not part of aligning a
rule. So no record was re-extracted and no committed figure moved. The flag is not final in any case:
§11.1 decides after the models, over every triangle in the record, on the same usable-cohort rule.

That measurement stopped at the parser's verdict, and so did the tests written with it, which is
why it missed what the next step did (review of 29 September 2026, MAT-2). The two one-column
triangles the parsers admit, 2468/2022 and 2255/2015, then met the structure score in
`compute_pyd_from_triangle()`, scored 0.00 and yielded no figure, so both records were written as
having no triangle and neither model was run. Round 62 scores a one-column triangle on its own
staircase (§9.6); `tests/test_single_cohort_triangles.py` goes through the PYD step and the RAG
step, not only the parser.

**Two defects the replay exposed and did not close.** Both are recorded here with the measurement
that found them, and both are pinned by tests so that a change to either is deliberate.

1. *The categoriser admits tables that are not triangles, and no version of the rule notices.*
   Syndicate 308's 2018 filing, table 9, is a "Syndicate annual accounting result" table whose
   columns are three syndicate numbers (510, 557, 308) and whose rows are years of account. The
   old rule called it a young syndicate; the aligned rule parses it into a candidate. It loses the
   Azure path's score to the filing's real triangle, which is why the alignment changed nothing,
   and `tests/test_triangle_admissibility.py` pins that margin.

   A staircase test was the obvious repair and does not work. Built and measured three ways, at the
   level that decides what a route reports: as a veto on an absolute height (a cohort may not carry
   more than `report_year - y + 1` development values) it refuses a correct triangle in 30 Azure
   filings and 9 Adobe ones, 2088/2015's 0.465m among them, which is both models' figure exactly; as
   a veto on the steps (a newer cohort must show strictly fewer values, which survives extra summary
   rows where the height does not) it changes 38 Azure, 4 Adobe and 66 text filings, because real
   triangles break strict decrease often enough through missing cells, merged rows and "& prior"
   aggregates; weighted above the other scoring terms it changes 16 filings, and in eight of those
   the incumbent triangle agreed with both models to the digit (1955/2019's 44.2m, 2012/2016's
   9.38m, 318/2020's -13.0m) while the step-clean grid it promotes does not, so a well-shaped table
   is not the same thing as the right table; and as a tie-break below every other term it changes
   nothing at all. It is therefore not in the code. What would identify 308/2018's table is its
   header -- columns labelled with syndicate numbers rather than development periods -- which is a
   question for the categoriser, not for a shape test (round 61).
2. *The Adobe path takes the first parsable fragment, not the best one.* Adobe splits a wide table,
   so a fragment can be a piece of a triangle: 2987/2021 holds both a 2012-2019 triangle and a
   2012-2018 piece of it, and the piece computes -255.5m where the full one gives the -88.9m both
   models read. Scoring the candidates as the Azure path scores its own (gross, then more UW years,
   then more complete) was tried and reverted: it changes what the route reports for 10 of the 55
   filings, and in 2987/2020 and 2987/2022 it moves the route's triangle *away* from the models'
   figure (150.3 → 68.0 and 157.9 → 60.9) while in 1861/2015 it moves towards it. Those three
   cannot be adjudicated from the caches.

**Ordering.** `_parse_triangle_xlsx()` asks "is this a triangle?" before "is the syndicate young?",
because it is tried on every fragment Adobe wrote: without that order, 134 fragments carrying one
stray year in a header read as evidence of a young syndicate. The grid parsers ask in the other
order, because they only see grids the categoriser tagged `claims_triangle` and a young syndicate's
triangle can carry fewer than two development rows.

Swapping them was measured at the level that decides, and it is not worth doing. The table route's
first-year flag would drop for 132 filings and be raised for none, so the direction is uniformly
towards better-founded reasons; but 96 of those 132 already hold a figure from another route, so
nothing about them changes. The 31 that are committed first-year stubs would be re-decided, and for
30 of them the outcome cannot be predicted from the caches at all: their committed model responses
carry no triangle, so the post-model rule would not call them young and the reserve-text steps would
decide instead. Each would have to be read individually and the model refitted, and no committed
figure is demonstrably wrong today. So the order stands as it is, with this measurement as the
reason (round 61).

Those counts are the round-61 corpus's (26 September 2026) and were not measured again. Since then
every first-year stub has been read against its filing pages
(`pdf_extraction/audit/structural_eligibility_audit.json`, 95 records): 94 hold no cohort up to
`t-2`, and 1840/2022's printed nil was retained as an eligible zero. The committed stubs' exclusion
therefore rests on that audit, not on this flag. The corpus holds 94 stubs: 69 of the 70 the
measurement saw, 1985/2024, which became a stub when it was extracted again on 29 September 2026
(its tables hold UW2023 and UW2024 only), and 24 that were unread records until 30 September 2026
(below). The audit's script refuses to run when a committed stub has not been transcribed, and
`tests/test_structural_eligibility_audit.py` fails in that case too.

**Unread records the audit restated as stubs** (third cycle of round 62, D2). The deterministic step
still cannot call a report without a triangle young (`_no_mature_cohort()`, 11.4), and that is
unchanged. 24 records the pipeline writes as having no deterministic reading state in their filings that
the syndicate began underwriting in the report year (18) or the year before (6), and none prints an
older cohort, so no underwriting year up to `t-2` can exist. The move lives in the audit and in the
records, not in the code: the ledger holds each one's own words (`start_statements`: page, printed page
and quote, each checked against the page of the file whose hash the ledger holds), and
`scripts/restate_record_status.py --audited-unread` writes the record as a stub the way
`_first_year_record` does, with its own reason (`AUDITED_UNREAD_STUB_REASON`), keeping the business mix
the table step found. The pipeline would still write these filings as unread, and the replay check
expects exactly that (11.4).

- Began in the report year (18): 1347/2023, 1609/2021, 1686/2014, 1699/2022, 1729/2014, 1796/2021,
  1922/2024, 1947/2018, 1975/2018, 2014/2014, 3902/2017, 4321/2022, 5623/2018, 6050/2015, 6117/2014,
  6119/2014, 6125/2016 and 6134/2018.
- Began in the year before (6): 1975/2019, 1991/2014, 4321/2023, 6050/2016, 6113/2014 and 6115/2014.
- Ten of the 24 print a young development table (1609/2021, 1699/2022, 1796/2021, 1922/2024, 1975/2019,
  3902/2017, 4321/2022, 4321/2023, 5623/2018 and 6050/2016); the other 14 print none. The audit read each
  filing's start statement, its development table where it prints one, and its opening balance. It did
  not look for a stated prior-year development figure: the parsers found none and the models were not
  run. The coverage report's row text for the 24 says that, and no longer says there is none.
- Two were read with care. 2014/2014 says the syndicate has "its origins in Special Purpose Syndicate
  6110", and 3902/2017 that it replaced "the Incidental Syndicate that previously operated within
  Syndicate 4020". Neither filing prints an older cohort: 2014/2014 has no comparative column and no
  development table, and calls 2014 "Syndicate 2014's first underwriting year"; 3902/2017's single-cohort
  table reconciles to the balance sheet's gross claims liabilities, so no older cohort is in its accounts.
- The scan that found the 24 was repeated over the other 21 unread filings, all pages: none states a
  start in the report year or the year before. One of the 21, 3210/2018, could not be read when it was
  made: its local PDF was a cut-short download that opened with no page. Lloyd's file, fetched on 2 October
  2026 and read from its OCR page cache, states no start either: the audit's inception terms
  (`INCEPTION_TERMS` in `scripts/audit_structural_eligibility.py`) match nothing in its 44 pages, and the
  filing says that the syndicate ceased to write new business at 31 December 2016.
- A restated filing that prints no opening balance says why (`opening_gross_reserve_exemption`): its
  syndicate began in the report year, so no claims outstanding at 1 January exist to print, and the test
  accepts the declaration for a first-year filing only.

**Example**: syndicate 2468/2022 has a single-column triangle
(UW year 2020).  Since 2020 ≤ 2022 − 2 = 2020, the year is
usable.  The pipeline extracts the triangle (29,267 → 28,431 →
28,278 in £'000) and, from round 62, computes PYD = −0.153m (a
release).  The record committed in round 56 was written before
that, by the rule that refused the triangle, and said it had no
triangle; it was extracted again with the models on 29 September
2026 and now carries −0.153m from the triangle.

When `first_year_syndicate` is triggered and the reserve-text steps found nothing either (Step 4 cleared the flag
and Steps 5-5e found no figure, `first_year_reserve_text`), the models still run and the decision is taken after
them (11.1). Otherwise:

- LLM extraction is **skipped** (saves API cost)
- LOB breakdown is still extracted if available
- The inception cache gains report_year - 1 for a syndicate it does not know
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
disagree in sign and the provisions figure is an affirmed
movement note whose column is bound to the report year (R138),
provisions takes precedence (section 11.3.1).  The difference is logged but not
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

**Cross-validation rule**: when both are available, the
provisions table is an affirmed movement note
(`movement_semantics.table_is_movement_note`), its column carries
the report year in its own header (`column_bound_to_report_year`)
and the two **disagree in sign** (one is a release, the other a
strengthening), the provisions figure is preferred (R138).
Without both conditions the triangle stands: a sign disagreement
on its own is as consistent with the figure not being a movement
at all, and 1274/2019's `2010 & prior years` cumulative incurred
total displaced a correct -6.619m on that reasoning.  With them,
a sign disagreement is a strong signal that the triangle diagonal is
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
4. The provisions table is an affirmed movement note and its
   column is bound to the report year (`movement_semantics`;
   R138); otherwise the triangle stands

**Example** (syndicate 780/2016):

The triangle diagonal PYD is +24.9m (cumulative claims estimates
rose for 2011--2014 UW years), but the provisions note reports
gross prior year claims movement of −15.6m (a release).  Before
R138 the sign disagreement triggered the override, and −15.6m
was used.  Since R138 it does not: the note is an affirmed
movement note, but its column does not carry the report year in
its own header (`column_bound_to_report_year` is false), so the
provisions figure does not replace the triangle.  The triangle's
+24.9m is withheld by the conflict veto instead, because both
models read a release (−15.6m and −17.1m), and the record carries
the models' −15.6m, stated in the reserve text (route
`model_reading`).

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

### 11.4  No deterministic reading (`no_triangle_data`)

When the RAG step returns no development figure (no triangle figure,
no provisions or narrative figure), no reserve-movement text and no
loss-ratio grid, and did not find a first-year triangle, the report is
classified separately from the eligible-cohort rule:

- `no_triangle_data = True` (the historical key), `excluded = True`,
  `status = "no_deterministic_reading"`, `models_run = False`, and
  `exclusion_reason` = `NO_DETERMINISTIC_READING_REASON`
  (`test_gemini.py`)
- the models are **not run** (`process_one_report()` returns before the
  slim PDF is built)
- no figure is obtained, so the report is not in the analysis

**This is a statement about the parsers, not about the filing.** Until
round 62 the reason read "No claims development triangle or reserve
movement text found in report", and this section said the case was
"common in run-off syndicate reports from years when no triangle was
published". The review of 29 September 2026 (MAT-2) read the filings
and found claims development tables in filings written this way. The
round-62 measurement (the RAG step replayed on the committed caches,
every filing) finds thirteen that the current code reads, or takes to
the page-vision step:

- 2468/2022 and 2255/2015, one-column triangles the structure check
  refused (§9.6);
- 1884/2022 and 3330/2018, written by a superseded staircase rule
  (below);
- nine 2024 HTML filings whose conversion to PDF had kept text on its
  first eight to twelve pages only (§13.1): 4747/2024's triangle is read
  from the page text, and 1902, 1985, 1988, 2525, 2689, 2880, 3456 and
  5183/2024 reach the page-vision step. 1922/2024's conversion lost its
  notes too, but its table holds a single 2024 cohort and the parsers
  still do not read it.

Those thirteen were extracted again with the models on 29 September
2026 (`pdf_extraction/audit/redecision_pending.json`, `extracted`);
every other record written this way carries the restated status and
reason (`scripts/restate_record_status.py`), and says the models were
not run.  Of the 45 that were left, 24 state in their filings that the
syndicate began in the report year or the year before and were restated as
first-year stubs on 30 September 2026 (11.2); 21 remained unread, and 1400/2014
made 22 on 3 October 2026 (9.1); two of the 21 still print a table the parsers do not read, and a third,
3210/2018, whose table no backend has read (below).

**Important**: which of the two flags a report gets does not depend
on the syndicate's age.  The inception-based distinction this
paragraph used to draw --- reports inside the first two underwriting
years classified as `first_year_syndicate` even with no triangle ---
went with the inception lookup in round 58, and nothing reads an
inception year for a decision now.  A report with **no triangle at
all** is not taken to be young on that account: `_no_mature_cohort()`
requires at least one triangle before it can say a record holds no
usable cohort, so a report without one is classified
`no_triangle_data` whatever the syndicate's age.  A report *with* a
triangle whose cohorts all fall after `t-2` is the first-year stub
(§11.1, §11.2; frozen review of 25 September 2026, D02).  A filing that
*states* the syndicate began in the report year or the year before is
young whatever the parsers read, and that decision is the filing-page
audit's, recorded in the ledger and in the record (§11.2), not this
function's.

**Two records the current code would not write** (review of 29
September 2026, R7-02).  1884/2022 and 3330/2018 are committed as
no-triangle records, yet the table step on their committed caches
reads a triangle in both: 1884/2022 gives +9.1m, and 3330/2018 gives
-1.384m from round 62 (+0.208m before, from a misread net table,
§7.1).  Both were written on 11 September 2026 by the round-56 run,
whose workers loaded their code at 20:10, before R168 -- the staircase
limit read from each column's own year -- landed at 21:47
(`pdf_extraction/audit/r167_r168_catchup.json`).  Both triangles skip
underwriting years ([2013-2018, 2022]; [2011, 2012, 2018]).  The
positional staircase scored them 0.14 and 0.00 against the 0.50 that
the same round had just made binding, so the table triangle and (for
1884/2022) the page-vision triangle were refused, and with no reserve
text the records were written as having no triangle.  Swapping that
one scorer into today's code reproduces both records exactly.  The
catch-up that followed re-derived the records that carried a stored
RAG triangle, and these two carried none, so nothing re-derived them;
round 221 found that they no longer reproduced and left them.  They
were extracted again with the models on 29 September 2026 and now
carry +9.1m and −1.384m from their triangles.

What let them sit is the scope of the check, not the rule: a replay
measured on the records a rule still touches cannot see the records
an earlier version of it emptied.  `scripts/replay_corpus_check.py`
now replays the deterministic step for every committed record -- stubs
and unread records included -- on its own caches and compares the
class, the RAG figure and route, and the stored triangle; the records
waiting for the models (`pdf_extraction/audit/redecision_pending.json`)
and those without a usable table cache (`offline_unservable.json`) are the
only declared exceptions (the pending list also holds the 16 records of section 9.1), and a declaration that no longer differs is
reported as stale.  The 24 unread records the audit restated as stubs are
not exceptions but a class (`audited_unread_stub`, read from the ledger's
`extraction_status`): their replay must still be `unread`, and their cached
grids are held to the same test as the unread records', so a parser that
came to read one shows as a mismatch and the audit's decision is looked at
again.  The full run is recorded, with hashes of the code
it ran and of the record content it compared, in
`pdf_extraction/audit/corpus_replay_check.json`, and
`tests/test_corpus_replay.py` fails when a record, `table_extraction.py`,
the driver `scripts/replay_corpus_check.py`, a repository module
`test_gemini.py` imports (`adjudicate.py`), or code in `test_gemini.py`
that the replay runs changes without a new full run, and replays a
subset in the default suite.  "Code the replay runs" is read from the
code and compared as syntax with the version the run hashed, which is
found in git by its hash: every module-level statement, and every
function and class the trace reaches.  The trace starts from the
replay's entry points (`extract_pyd_from_relevant_pages`,
`convert_html_to_pdf`, `compute_pyd_from_triangle`, and the four
functions `table_extraction.py` imports from `test_gemini.py` for its
Adobe backend), every name a module-level statement mentions and every
decorated definition, and follows every name a reached definition
mentions -- its decorators and defaults, attribute names and string
constants included -- so it over-reaches rather than misses.  A lookup
it cannot follow (`globals()`, `vars()`, `eval`, `importlib`,
`sys.modules`, or `getattr` with a computed name) in reached code or at
module level makes every definition reachable; the current code has
none.  A change confined to the model calls, their cost accounting or
the extraction run's own `__main__` block in `test_gemini.py` leaves the
run standing (round 62, second cycle: Gemini's thinking tokens priced
in `extract_with_gemini`).

**Unread filings that print a table the parsers do not read**
(verification review of round 62, N-V-E-4).  Two of the 22 records still
with no deterministic reading print a claims development table that the
parsers turn into no figure; a third, 3210/2018, prints one that they have not
read (last bullet).  Their committed caches and filing pages say why each
stays unread:

- 3500/2015: its Azure cache holds a gross triangle of five cohorts
  (2006-2010, £000) whose first estimates sit three to five years
  into development (2006 and 2010 are blank), so the multi-column
  staircase rule scores the grid 0.00 and refuses it.  It is the one
  unread filing whose cached gross grids with a usable cohort are all
  refused by the structure score, and the replay check reports it
  (`unread_records_whose_gross_grids_the_structure_score_refuses` in
  `corpus_replay_check.json`).  It stays unread because the
  multi-column rule is unchanged: it is the rule the 0.50 threshold was
  built for (780/2018, §9.6).  A rule that scored such a grid on its
  own staircase is UNTESTED until it is measured on fixed inputs over
  the whole corpus, as the one-column rule was.
- 3622/2018: its cache holds gross and net grids of loss ratios by
  development period (2009-2018) at the managing agent's managed
  level, with the syndicate's share shown for the liabilities only.
  `compute_pyd_from_triangle` refuses them as percentages before any
  structure score, and the page-text loss-ratio parser reads the
  latest year of the printed header as 2011 and returns nothing.  A
  change to either is UNTESTED.
- 3210/2018: Lloyd's file, fetched on 2 October 2026, is a scan whose
  OCR page cache is committed, and page 41 prints a gross and a net claims
  development table by underwriting year (2011 to 2016, £000), every cohort
  of it up to t-2.  The record was written on 11 September 2026 from the
  earlier local copy, a cut-short download that opened with no page, so the
  parsers had nothing to read, and it is unchanged.  No table backend has
  read the new file: no grid of it is committed (`backend_cache_absent.json`
  lists it), and reading it needs a paid table extraction, which has not
  been authorised.  A paid read of the claims table on page 41 (a PDF
  page; printed 39) would not bring 3210/2018 into the working sample, because it is a whole run-off year
  (WHOLE in `runoff_corpus_register.json`) under the whole-year run-off
  rule.  So it has not been bought.  No figure has been taken from the table.

1400/2014 joined the unread records on 3 October 2026 and is not one of these three.  Its stored triangle was a net
one-column grid of yearly results, which the diagonal rule refuses (a column of negative values), and the one page-vision
call for it (PDF page 8, option B, section 9.1) returned no triangle: the page is the key performance indicators.  No
other route finds a figure, so it is written as no deterministic reading, and the record's reason says what that means:
it describes the parsers, not the filing, which may print a claims development table they could not read.

Three more filings were on this list before the third cycle: 1699/2022,
1975/2019 and 1922/2024.  Their caches hold no triangle grid, and the
filings print young tables only: a single 2022 cohort (1699/2022),
cohorts 2018 and 2019 (1975/2019), and a single 2024 cohort of $26k
(1922/2024).  None holds a cohort up to t-2, and each states that the
syndicate began in the report year or the year before, so on 30 September
2026 they became audited first-year stubs (§11.2), with 21 other unread
records. Of those 21, seven print young development tables too (1609/2021,
1796/2021, 3902/2017, 4321/2022, 4321/2023, 5623/2018 and 6050/2016) and 14
print no table (1347/2023, 1686/2014, 1729/2014, 1947/2018, 1975/2018,
1991/2014, 2014/2014, 6050/2015, 6113/2014, 6115/2014, 6117/2014, 6119/2014,
6125/2016 and 6134/2018).

`tests/test_corpus_replay.py` holds the reported list to the committed
caches and requires this section to name every filing on it, and the three
that moved.

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

Many triangles print their oldest underwriting years as one
aggregate column ("2010 and prior", "Before 2011", "Pre-2011",
Syndicate 2007's "2010&P").  The grid parser reads its label across
the column's first three header rows.  "2010&P" was not read until
the review of 2 October 2026 (P-31): the column was dropped, and
2007/2016's figure was +61.3m where its cohort's step of -6.5m makes
it +54.8m, and 2007/2017's -22.0m where it is -44.5m
(`tests/test_cohort_label_and_p.py`); both records were regenerated on 3 October 2026 and carry +54.8m and -44.5m.
What it does next depends on what the column holds
(R209):

- **Development by calendar year**: one value per calendar year
  up to the report year, as under 218/2017's "2010" beside
  "and prior".  The column becomes the triangle's oldest column
  under its anchor year, and its last step is part of the
  numerator (underwriting years up to report year minus 2).
- **No development**: a value only in a summary row, as in
  1884/2023's "2013 & prior" beside "Cumulative estimate".  The
  column is dropped.  Before R209 a label split across header
  cells bound its year to such a column.  "2013" over "&" over
  "prior" left an empty oldest year.  "Before 2011" took the year
  2011 from its own column, whose development was then lost as a
  duplicate (2121/2015, 5151/2015).
- **Development by age**: 4242/2021's "2015 & Prior" runs to
  "Ten Years Later" in a 2021 report, falling as fewer of the
  aggregated years reach each age.  Its last step mixes years at
  different ages and is not a movement in the report year.  A
  calendar column holds at most report year minus anchor plus 1
  values, so a deeper column is dropped.

Other paths still exclude an aggregate column.  The LLM prompts
tell the models to: the extraction prompt's `_claims_triangle`,
the page-triangle vision prompt (`TRIANGLE_EXTRACT_PROMPT`) and
the adjudicator's prompt.  The Adobe xlsx parser skips one.  These
paths supply a figure only where the deterministic triangle is
not used.  In the corpus that happens for 3624/2015 and 2007/2015.
There a table figure opposite in sign to two agreeing model
values is not applied.  The triangle cross-check then adopts the
models' own triangles, which omit the cohort.  A prompt is part
of every cached response's key, so changing one means
re-extracting every report.

---

## 13  Caching strategy

| Cache location                                 | Content                        | Invalidation                            |
|------------------------------------------------|--------------------------------|-----------------------------------------|
| `pdf_extraction/syndicate_inception_years.json`| First UW year per syndicate    | A record only: no step reads it for a decision since round 58 (11.1). Learned from triangles; add a syndicate to `_manual_overrides` to protect a verified year |
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

### 13.1  HTML filings: the converted PDF (round 62)

The 95 filings for 2024 are HTML. `convert_html_to_pdf()` prints each
to `pdf_extraction/html_converted/` with Playwright, and every later
step reads that PDF: the page classifier reads its text, the table
backend and the models read its pages. The converted PDFs are not
committed (`*.pdf` is ignored), so each machine makes its own.

**What went wrong.** 53 of the filings are pdf2htmlEX documents, which
carry a subset web font for every few pages. Chromium loads a web font
when it first needs it, and a print taken as soon as the page had
loaded drew no text on pages whose font was not yet in. The corpus was
converted under two environments: 59 files were printed by Chromium 130
and 36 by Chromium 145 (each PDF's producer field says which; on the
extraction machine those are the builds of Playwright 1.48, installed
for the system Python, and 1.58, the repository's `.conda`
environment). Of the 59, ten kept text on their first
eight to twelve pages only -- 1902, 1922, 1985, 1988, 2525, 2689, 2880,
3456, 4747 and 5183/2024, every one of them then written as having no
triangle -- and eighteen more lost whole pages or 1-15% of their
characters (4242/2024 lost its claims development table's labels, and
1416/2024's and 2988/2024's balance-sheet tables their thousands
markers, which is why round 52 had to resolve their units from the
document declaration or the models). None of the 36 lost anything.

**What the converter does now.** It fetches nothing the filing
references, loads every font the document declares before printing,
and refuses a conversion, new or cached, that carries less text than
the filing (`conversion_lost_text()`): fewer PDF pages with text than
page containers with text, or under `MIN_CONVERTED_TEXT_SHARE` (0.99)
of the characters. Every conversion made this way carries at least
0.9985 of its filing's page text; the 28 that failed were replaced on
the extraction machine (the Chromium-130 files are kept aside).

**What that changes**, measured by replaying the RAG step on the
committed caches with the new conversions: 4747/2024's triangle is read
from the page text (-11.116m); eight of the ten reach the page-vision
step on the newly visible triangle page, for which no response is
cached; 1922/2024 prints a single 2024 cohort and is still not read;
4242/2024 (a models record) reaches the page-vision step too. Every
other HTML record's RAG outcome is unchanged, and 1416/2024 and
2988/2024 keep their opening figures with the unit now read from the
page. `tests/test_html_conversion.py` holds the check.

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

Stubs written before round 58 by the inception-year check, which
was removed then (section 11.1), carried this form until round 62,
when `scripts/restate_record_status.py --first-year` restated them:
none of the ten has a usable table cache (nine have no Azure cache,
and 1100/2024's is in the superseded list format the table step
refuses), so their reason now names the filing-page audit that
decided them (`pdf_extraction/audit/structural_eligibility_audit.json`):

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

For a current stub, the report contains one or more triangles but no
underwriting year at or before $t-2$, and no prior-year figure is
stated in the reserve text:

```json
{
  "first_year_syndicate": true,
  "reason": "No underwriting year old enough for prior year development in the report's triangles, and no prior-year figure stated in its reserve text",
  "models_run": false,
  "syndicate": 1322,
  "year": 2023,
  "gross_premium_mix": ["...if available..."]
}
```

Reports reclassified by the retrospective correction script also
include a `reclassified_from` field indicating the previous status
(`"no_triangle_data"` or `"normal_extraction"`).

### 14.3  No deterministic reading (`no_triangle_data`)

```json
{
  "no_triangle_data": true,
  "excluded": true,
  "status": "no_deterministic_reading",
  "models_run": false,
  "exclusion_reason": "No deterministic reading: the table, page-text and narrative parsers found no prior-year figure, no reserve-movement text and no loss-ratio triangle they could use. This describes the parsers, not the filing, which may still print a claims development table they could not read. The models were not run, so no figure was obtained and the report is not in the analysis.",
  "syndicate": 1110,
  "year": 2019
}
```

Records written before round 62 said "No claims development triangle
or reserve movement text found in report"; those not listed for a new
extraction were restated to the form above by
`scripts/restate_record_status.py`, which changes no other field
(§11.4).

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
| **No model block retained** | No `models` key (has `first_year_syndicate`, `no_triangle_data`, or `reason`) | Yellow | The record keeps no model output: it was classified as a first-year stub or as no-triangle-data. This describes the STRUCTURE THAT WAS RETAINED and not whether the models ran. A first-year stub may be written *after* both models have read the reserve text (11.1), in which case their figures are in `first_year_evidence` and the API cost was incurred. |
| **Excluded** | Has `models` key AND `excluded: true` | Purple | Extraction ran but the report was excluded during adjudication or manual review.  API cost was incurred. |
| **Extracted** | Has `models` key, no `excluded` flag | Green/Red | Normal extraction result.  Shown as "Reliable" (green) if both PYD and premium mix are present, or "Incomplete" (red) otherwise. |

A status is read off the retained structure, so it cannot be used to infer API usage. A stub that
carries `first_year_evidence` was decided after the models ran; one without it was skipped before
them (frozen review of 25 September 2026, D02). Since round 62 every record without a model block
also says so in a field: `models_run` is `false` for a no-deterministic-reading record and a stub
written before the models, and `true` for a stub written after them.

**Console INCOMPLETE warning**: After writing each JSON file,
`test_gemini.py` checks whether the extraction has both PYD %
and a non-empty premium mix.  If either is missing, a
`>> INCOMPLETE: missing <fields>` line is printed to the
console so the operator sees the same status that the dashboard
will show, without needing to open `progress_report.html`.

**Note**: reports with both `no_triangle_data: true` and
`excluded: true` but **no** `models` key are classified as
Skipped, not Excluded.  The `excluded` flag on these files is a
legacy artefact from the no-deterministic-reading path --
the report was never sent to LLMs (`models_run: false`).

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

### Aggregate column read as an empty oldest year, or refused

**Symptom (before R209)**: the stored triangle's oldest year has
no value in any development row.  Syndicate 1884/2023 stored
[2013, 2014, 2015, 2016, 2017, 2018, 2022, 2023] with 2013 empty.

**Cause**: the label "2013 & prior" runs down its column ("2013"
over "&" over "prior").  The parser skipped the cells holding "&"
and "prior", and bound 2013 to a column that prints only a
summary-row total (810.4, "Cumulative estimate").

**Resolution**: R209 reads the label across the header rows and
drops a cohort column with no development (section 12.2).  The
figure does not change: the empty column never gave a step.

**Symptom (R209 as first written)**: no `[Azure] Triangle PYD:`
line, then `[RAG] 1 triangle page(s) found, trying LLM vision...`
for a report whose table triangle was read before (4242/2021).

**Cause**: an aggregate column printed by development age was
inserted as the cohort's column.  It runs past its anchor's
staircase, so `compute_pyd_from_triangle()` refuses the triangle
("has 11 rows but span is only 2015-2021").

**Resolution**: the depth limit in section 7.1 drops such a
column, and the table triangle is read again.

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
**conditional fallback** (`rag_is_fallback_only = True`).  It fills
an LLM blank. When an LLM extracts a syndicate-level PYD from the
narrative, that value is kept if its direction agrees with the
managed-level result; a direction contradiction is resolved in
favour of the deterministic loss-ratio result and logged.

**Affected syndicates**: 2623/2016 through 2623/2022.

### Azure extracts loss ratios as claims triangle

**Symptom**: Azure finds a triangle on the claims development
page but PYD makes no sense (e.g. -11.2m when the narrative
says -180.2m).

**Cause**: Azure extracted the cumulative loss ratio grid
(percentages like 66.5, 64.6, 63.4) as if they were absolute
claims amounts in millions.

**Fix**: the decision is made from the triangle's own unit
evidence first, and only then from magnitude — the full rule is
section 9.7, and this entry follows it.  A ratio or percent marker
in the table text makes the triangle a percentage table, which
takes the loss-ratio route (`_extract_pyd_from_loss_ratio_triangle`)
and is never read as money.  A thousands or millions marker gives
that monetary unit with `units_evidence = "header"`, and **an
evidenced monetary triangle is never rejected on magnitude**.  The
0--200 test applies only where the unit evidence is `"default"` or
`"conflict"`, and it is a heuristic with false positives.

Do **not** reject a triangle because its values are small.  A gross
triangle in millions and the same triangle in thousands must give
the same movement:

```
units = "millions",  header "GBP m"      units = "thousands", header "GBP 000"
  at end of UW year      44.7              at end of UW year      44,700
  one year later         77.6              one year later         77,600
  two years later        65.8              two years later        65,800
  three years later      63.0              three years later      63,000
  four years later       64.5              four years later       64,500
  five years later       66.4              five years later       66,400
  -> movement 66.4 - 64.5 = +1.9m          -> 66,400 - 64,500 = +1,900k = +1.9m
```

Every value of the left-hand grid lies in 0--200; rejecting it as a
loss-ratio table is the failure this rule exists to prevent.
`tests/test_unit_equivalence.py` holds the equivalence.

### Perplexity returns syndicate number as inception year

Historical: the Perplexity inception lookup was removed in round 58 (section 11.1).

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

Historical: the inception-year check, its soft flag and its cache correction were removed in round 58 (section 11.1).

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
   because it directly measures balance-sheet reserve movement;
   since R138, only where the provisions table is an affirmed
   movement note whose column is bound to the report year.

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
