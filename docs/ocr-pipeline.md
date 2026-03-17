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
| Step 0: Inception year check                   |
|   is_early_year_syndicate()                    |
|     Lookup syndicate_inception_years.json       |
|     If missing: query Perplexity API            |
|     Skip if report_year < inception_year + 2    |
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
|     pl_account | provisions                    |
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
|     Grid parser for "Dev Year 1,2,3..." format |
|   Fallback: _parse_triangle_from_text()        |
|     Text-based parser for columnar layouts     |
|   Fallback: _parse_transposed_triangle_from_text() |
|     Text parser for concatenated transposed    |
+-----------------------------------------------+
  |
  v
+-----------------------------------------------+
| Step 4: PYD computation (Python, not LLM)      |
|   compute_pyd_from_triangle()                  |
|     Year-value contamination detection          |
|     Summary-row stripping                      |
|     Diagonal extraction                        |
|     Unit auto-detection and conversion         |
|     Ratio sanity check (release > -100%)       |
+-----------------------------------------------+
  |
  v
+-----------------------------------------------+
| Step 5: Dual-LLM cross-validation             |
|   Gemini + GPT extract independently           |
|   verify_triangles() resolves disagreements    |
|   RAG triangle PYD overrides LLM values        |
+-----------------------------------------------+
  |
  v
+-----------------------------------------------+
| Step 6: Report classification                  |
|   early_year: report_year < inception + 2       |
|   first_year_syndicate: < 3 UW years in triangle|
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
| `claims_triangle` | "claims development", "development table", "cumulative gross claims", "year later", "years later", "development year", "year of account", "ultimate contract outstanding claims", "gross of reinsurance", "net of reinsurance" |
| `provisions`      | "provision for claims", "prior year", "movement in prior", "gross provision" |
| `pl_account`      | "technical account", "profit and loss", "claims incurred"            |
| `premium_mix`     | "accident and health", "marine aviation", "third party liability", "reinsurance" |

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

### 5.2  Atomic file writes (Windows)

PyMuPDF's `fitz.save()` can fail on Windows when the target file
is locked by another process.  The pipeline works around this with
a temp-file-then-rename pattern:

1. Write to a `tempfile.mkstemp()` in the same directory.
2. Attempt `Path(tmp).replace(output)` (atomic on same
   filesystem).
3. Fall back to delete-then-rename if `replace()` fails.
4. Last resort: `shutil.copy2()` + delete temp.

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
6. If fewer than 3 UW years, return `"new_syndicate"` (first-year
   syndicate detection).
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

1. **Marker detection**: require both `"development year"` and
   `"year of account"` in the text (case-insensitive).
2. **Extract after "Year of Account"**: take the text following
   the `"Year of Account"` marker.
3. **Truncate at stop markers**: cut the text at the first
   occurrence of "current estimate", "cumulative payment",
   "cumulative gross payment", "cumulative net payment",
   "gross claims reserve", "net claims reserve",
   "gross unearned", "net unearned", or
   "estimate of cumulative net".  This prevents collecting
   values from the paid-claims or net triangle sections.
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

**Sanity gate**: before applying, the RAG PYD is checked
against opening reserves.  If `pyd / opening_reserves < -100%`
(i.e. a release exceeding the entire opening balance), the
RAG PYD is discarded and the pipeline falls back to
`verify_triangles()` for LLM-based resolution.  This catches
cases where a non-triangle table (e.g. segmental analysis)
was misidentified as a claims triangle by the API backend.

This unconditional override is necessary because LLMs sometimes
extract PYD from the wrong source (e.g. P&L "gross change in
provision" which includes current-year claims movements, or
"net provision for claims outstanding" which is after
reinsurance).  These wrong-source values can be numerically
close to the correct triangle PYD by coincidence, so a
tolerance-based check would let them through.

When the LLM value differs from the RAG value by >= 0.5m,
the override is recorded in `data_quality_notes`:

```
[RAG OVERRIDE: Model said PYD=17.22, RAG triangle computed
17.581. Using RAG value.]
```

When the difference is < 0.5m, the RAG value still replaces
the LLM value but is logged as "confirmed" rather than
"overridden" (no note added to `data_quality_notes`).

---

## 11  Report classification

Reports are classified before expensive API calls to save cost.
Two independent checks run in sequence; the first to match wins.

### 11.1  Inception year check (Step 0)

**Functions**: `is_early_year_syndicate()`, `get_inception_year()`,
`_lookup_inception_year_perplexity()` (`test_gemini.py`)

Before any PDF reading or API calls, the pipeline checks whether
the report falls within the syndicate's first two underwriting
years.  A syndicate needs at least 3 development periods before
prior year development can be meaningfully separated from current
year activity.

**Decision rule**: skip when `report_year < inception_year + 2`.

**Inception year lookup** (in priority order):

1. **Local cache** -- `pdf_extraction/syndicate_inception_years.json`
   stores `{"syndicate_number": first_uw_year}` pairs.  Populated
   from claims development triangles (earliest UW year across all
   reports for a syndicate).
2. **Perplexity API** -- if a syndicate is not in the cache, the
   pipeline queries Perplexity (`sonar` model) with:
   *"What year did Lloyd's of London syndicate N first begin
   underwriting insurance?"*
   The response is parsed for a 4-digit year and saved to the cache.
   Cost: ~$0.001 per query; each syndicate is queried at most once.
3. **Triangle detection** -- if the RAG-lite extraction later finds
   a triangle with <= 2 UW years, the pipeline updates the cache
   with `inception_year = report_year - 1` as a conservative
   estimate (for syndicates not already in the cache).

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
  "1084": 2011,
  "1322": 2022,
  "1609": 2021,
  "1991": 2013
}
```

### 11.2  First-year syndicate (triangle-based detection)

If the inception year check did not skip the report, the RAG-lite
extraction runs and may detect a triangle with fewer than 3
underwriting years.  This is a second line of defence for
syndicates not yet in the inception cache.

- Triangle with < 3 UW years -> `first_year_syndicate = True`
- The inception cache is updated with the estimated inception year
- LLM extraction is **skipped** (saves API cost)
- LOB breakdown is still extracted if available
- Output JSON: `{"first_year_syndicate": true, ...}`

### 11.3  No-triangle-data exclusion

Reports where no claims triangle and no reserve movement text
can be found **and** the report is not in the first two UW years:

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
| `pdf_extraction/syndicate_inception_years.json`| First UW year per syndicate    | Edit file directly; auto-updated by Perplexity lookups |
| `pdf_extraction/azure_output/`                 | Azure API table grids          | `_CACHE_VERSION`, page set, batch mode  |
| `pdf_extraction/nutrient_output/`              | Nutrient API responses         | `_CACHE_VERSION` bump                   |
| `pdf_extraction/adobe_output/`                 | Adobe PDF Extract results      | `_CACHE_VERSION` bump                   |
| `pdf_extraction/llm_cache/`                    | LLM API responses              | SHA-256 of prompt content               |
| `pdf_extraction/ocr_page_cache/`               | Tesseract OCR text per page    | Delete file to re-OCR                   |

LLM cache keys are computed from `(model, prompt_version,
prompt_text, syndicate, year)`.  Changing the prompt text or
bumping `PROMPT_VERSION` auto-invalidates affected entries.

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
    "gpt-4.1-mini": { "...same fields..." }
  },
  "validation": {
    "passed": true,
    "total_discrepancies": 2,
    "within_tolerance": 2,
    "hard_failures": 0
  }
}
```

### 14.2  First-year syndicate (inception year skip)

When the inception year check identifies the report as being in
the first two underwriting years:

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

When detected by the triangle check (fewer than 3 UW years):

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

---

## 15  Troubleshooting

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
