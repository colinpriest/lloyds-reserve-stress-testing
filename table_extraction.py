"""Unified table extraction from Lloyd's syndicate report PDFs.

Supports multiple backends (priority order):
  - azure: Azure AI Document Intelligence (default) — prebuilt-layout model
  - nutrient: Nutrient.io API — targeted page extraction
  - adobe: Adobe PDF Extract API — full document extraction with xlsx tables

Each backend extracts:
  1. Claims development triangle (gross and/or net)
  2. Line of business (LOB) premium/claims breakdown
  3. Claims provisions movement (prior year development)

Usage:
    from table_extraction import extract_tables, TableBackend

    result = extract_tables(pdf_path, report_year, backend=TableBackend.NUTRIENT)
    # result.triangle, result.lob, result.provisions
"""

import json
import logging
import os
import re
import sys
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

import fitz  # PyMuPDF
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# Bump this when extraction logic changes to invalidate cached table grids
_CACHE_VERSION = 3


# ── Data structures ───────────────────────────────────────────────────────

class TableBackend(Enum):
    NUTRIENT = "nutrient"
    ADOBE = "adobe"
    AZURE = "azure"


@dataclass
class TriangleData:
    """Claims development triangle extracted from a syndicate report."""
    type: str  # "gross" or "net"
    currency: str  # "GBP", "USD", "EUR"
    units: str  # "millions", "thousands"
    underwriting_years: list[int] = field(default_factory=list)
    development_rows: list[list] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "currency": self.currency,
            "units": self.units,
            "underwriting_years": self.underwriting_years,
            "development_rows": self.development_rows,
        }


@dataclass
class LOBData:
    """Line of business breakdown from segmental analysis."""
    gross_premium_mix: list[dict] = field(default_factory=list)
    gross_premiums_written_gbp_m: float = 0.0
    claims_incurred_by_lob: Optional[list[dict]] = None
    currency: str = "GBP"
    method: str = "nutrient"

    def to_dict(self) -> dict:
        return {
            "gross_premium_mix": self.gross_premium_mix,
            "gross_premiums_written_gbp_m": self.gross_premiums_written_gbp_m,
            "claims_incurred_by_lob": self.claims_incurred_by_lob,
            "currency": self.currency,
            "method": self.method,
        }


@dataclass
class ProvisionsData:
    """Claims provisions movement (prior year development)."""
    gross_prior_year_claims: Optional[float] = None
    ri_share_prior_year: Optional[float] = None
    net_prior_year_claims: Optional[float] = None

    def to_dict(self) -> dict:
        d = {}
        if self.gross_prior_year_claims is not None:
            d["gross_prior_year_claims"] = self.gross_prior_year_claims
        if self.ri_share_prior_year is not None:
            d["ri_share_prior_year"] = self.ri_share_prior_year
        if self.net_prior_year_claims is not None:
            d["net_prior_year_claims"] = self.net_prior_year_claims
        return d


@dataclass
class ExtractionResult:
    """Combined result from table extraction."""
    triangle: Optional[TriangleData] = None
    triangle_details: Optional[str] = None
    lob: Optional[LOBData] = None
    provisions: Optional[ProvisionsData] = None
    first_year_syndicate: bool = False
    method: str = "none"
    elapsed_s: float = 0.0


# ── Public API ────────────────────────────────────────────────────────────

def extract_tables(
    pdf_path: Path,
    report_year: int,
    backend: TableBackend = TableBackend.AZURE,
    cache_dir: Optional[Path] = None,
) -> ExtractionResult:
    """Extract triangle, LOB, and provisions tables from a syndicate report PDF.

    Args:
        pdf_path: Path to the syndicate report PDF.
        report_year: The reporting year (e.g. 2018).
        backend: Which extraction backend to use.
        cache_dir: Directory for caching extraction results. Defaults to
                   pdf_extraction/<backend>_output/.

    Returns:
        ExtractionResult with triangle, lob, provisions data.
    """
    if cache_dir is None:
        cache_dir = Path("pdf_extraction") / f"{backend.value}_output"
    cache_dir.mkdir(parents=True, exist_ok=True)

    if backend == TableBackend.NUTRIENT:
        return _extract_nutrient(pdf_path, report_year, cache_dir)
    elif backend == TableBackend.ADOBE:
        return _extract_adobe(pdf_path, report_year, cache_dir)
    elif backend == TableBackend.AZURE:
        return _extract_azure(pdf_path, report_year, cache_dir)
    else:
        raise ValueError(f"Unknown backend: {backend}")


# ── Nutrient backend ──────────────────────────────────────────────────────

# Keywords for identifying relevant pages
_PAGE_KEYWORDS = {
    "claims_triangle": [
        "claims development", "development table",
        "gross ultimate claims", "underwriting year",
        "cumulative claims incurred", "cumulative gross claims",
        "outstanding claims provision",
        "year later", "years later", "months later",
    ],
    "provisions": [
        "provision for claims", "claims outstanding",
        "prior year", "movement in prior", "gross provision",
    ],
    "pl_account": [
        "technical account", "profit and loss",
        "gross premiums written", "earned premiums", "claims incurred",
    ],
    "premium_mix": [
        "accident and health", "marine aviation",
        "fire and other damage", "third party liability",
        "reinsurance", "miscellaneous",
    ],
}

_MIN_TEXT_THRESHOLD = 200  # chars per page to consider native text


def _is_scanned_pdf(pdf_path: Path, sample_pages: int = 5) -> bool:
    """Check if PDF is scanned by testing text extraction on early pages."""
    doc = fitz.open(pdf_path)
    total_chars = 0
    pages_checked = min(sample_pages, len(doc))
    for i in range(1, pages_checked):  # skip page 0 (disclaimer)
        total_chars += len(doc[i].get_text().strip())
    doc.close()
    return total_chars < _MIN_TEXT_THRESHOLD * max(1, pages_checked - 1)


def _classify_page(text: str) -> set[str]:
    """Return set of matching categories for a page's text."""
    text_lower = text.lower()
    categories = set()
    for category, keywords in _PAGE_KEYWORDS.items():
        hits = sum(1 for kw in keywords if kw.lower() in text_lower)
        if hits >= 2:
            categories.add(category)
    return categories


def _find_relevant_pages(pdf_path: Path) -> tuple[dict, dict, str]:
    """Find relevant pages using PyMuPDF (native) or Tesseract (scanned).

    Returns (page_matches, page_texts, method).
    """
    scanned = _is_scanned_pdf(pdf_path)

    if scanned:
        logger.info(f"Scanned PDF detected, using Tesseract OCR")
        return _find_pages_ocr(pdf_path)
    else:
        return _find_pages_native(pdf_path)


def _find_pages_native(pdf_path: Path) -> tuple[dict, dict, str]:
    """Scan pages with PyMuPDF text extraction."""
    doc = fitz.open(pdf_path)
    page_matches = {}
    page_texts = {}
    for page_num in range(len(doc)):
        text = doc[page_num].get_text()
        page_texts[page_num] = text
        categories = _classify_page(text)
        if categories:
            page_matches[page_num] = categories
    doc.close()
    return page_matches, page_texts, "pymupdf"


def _find_pages_ocr(pdf_path: Path) -> tuple[dict, dict, str]:
    """Scan pages with Tesseract OCR for scanned PDFs."""
    try:
        from pdf2image import convert_from_path
        import pytesseract as _pytesseract
        # Set Tesseract path if not in PATH
        tesseract_path = Path("C:/Program Files/Tesseract-OCR/tesseract.exe")
        if tesseract_path.exists():
            _pytesseract.pytesseract.tesseract_cmd = str(tesseract_path)
    except ImportError:
        logger.warning("pdf2image/pytesseract not installed, cannot OCR scanned PDF")
        return {}, {}, "none"

    page_matches = {}
    page_texts = {}

    images = convert_from_path(str(pdf_path), dpi=200)
    for page_num, image in enumerate(images):
        text = _pytesseract.image_to_string(image)
        page_texts[page_num] = text
        categories = _classify_page(text)
        if categories:
            page_matches[page_num] = categories
        if (page_num + 1) % 10 == 0:
            logger.info(f"  OCR'd {page_num + 1}/{len(images)} pages")

    return page_matches, page_texts, "tesseract"


def _extract_pages_to_pdf(pdf_path: Path, page_numbers: list[int], output_path: Path):
    """Create a new PDF containing only the specified pages."""
    src = fitz.open(pdf_path)
    dst = fitz.open()
    for page_num in sorted(page_numbers):
        dst.insert_pdf(src, from_page=page_num, to_page=page_num)
    dst.save(str(output_path))
    dst.close()
    src.close()


def _call_nutrient_api(pdf_path: Path, api_key: str) -> dict:
    """Send a PDF to Nutrient.io and return parsed JSON response."""
    import requests

    instructions = {
        "parts": [{"file": "document"}],
        "output": {
            "type": "json-content",
            "plainText": False,
            "structuredText": False,
            "keyValuePairs": False,
            "tables": True,
        },
    }

    with open(pdf_path, "rb") as f:
        response = requests.post(
            "https://api.nutrient.io/build",
            headers={"Authorization": f"Bearer {api_key}"},
            files={"document": (pdf_path.name, f, "application/pdf")},
            data={"instructions": json.dumps(instructions)},
            timeout=300,
        )

    if not response.ok:
        raise RuntimeError(
            f"Nutrient API error {response.status_code}: {response.text[:300]}"
        )

    return response.json()


def _cells_to_grid(cells: list) -> list[list[str]]:
    """Convert Nutrient cells array to a 2D grid of strings."""
    if not cells:
        return []
    max_row = max(c["rowIndex"] for c in cells) + 1
    max_col = max(c["columnIndex"] for c in cells) + 1
    grid = [["" for _ in range(max_col)] for _ in range(max_row)]
    for cell in cells:
        text = cell.get("text", "").replace("\r\n", " ").replace("\r", " ").strip()
        grid[cell["rowIndex"]][cell["columnIndex"]] = text
    return grid


def _clean_cell(text: str):
    """Clean a cell value: strip whitespace, parse numbers, handle parenthesized negatives."""
    if not text or not text.strip():
        return None
    s = text.strip().replace(",", "").replace(" ", "")
    # Accounting-style negatives: (123.4) -> -123.4
    m = re.match(r'^\(([0-9.]+)\)$', s)
    if m:
        try:
            return -float(m.group(1))
        except ValueError:
            pass
    try:
        return float(s)
    except ValueError:
        return text.strip()


def _grid_text_lower(grid: list[list[str]]) -> str:
    """Flatten grid into a single lowercase searchable string."""
    return " ".join(" ".join(row) for row in grid).lower()


# ── Text-based triangle parser (fallback when API misses the table) ──────

def _extract_numbers(num_strings: list[str]) -> list[float]:
    """Convert string number matches to floats, handling commas and parens."""
    values = []
    for num_str in num_strings:
        neg = num_str.startswith("(") or num_str.startswith("-(")
        clean = num_str.replace("(", "").replace(")", "").replace(",", "")
        if clean.startswith("-"):
            neg = True
            clean = clean[1:]
        try:
            val = float(clean)
            if neg:
                val = -val
            values.append(val)
        except ValueError:
            continue
    return values


def _parse_triangle_from_text(text: str, report_year: int):
    """Parse a claims development triangle from raw page text.

    Fallback for when Azure/Nutrient API doesn't detect the table structure.
    Looks for a row of UW years followed by rows of numeric development values.

    Returns (TriangleData, details_str) or (None, reason).
    """
    lines = text.split("\n")
    lines = [l.strip() for l in lines if l.strip()]

    # Step 1: Find UW years — either all on one line or on consecutive lines
    header_idx = None
    header_end_idx = None
    uw_years = []

    # Strategy A: years on one line (e.g., "2014  2015  2016  2017")
    for i, line in enumerate(lines):
        years_on_line = re.findall(r'\b((?:19|20)\d{2})\b', line)
        years_on_line = [int(y) for y in years_on_line
                         if 1990 <= int(y) <= 2030
                         and "prior" not in line[max(0, line.find(str(y))-10):line.find(str(y))].lower()]
        seen = set()
        unique_years = []
        for y in years_on_line:
            if y not in seen:
                seen.add(y)
                unique_years.append(y)
        if len(unique_years) >= 3:
            header_idx = i
            header_end_idx = i
            uw_years = sorted(unique_years)
            break

    # Strategy B: years on consecutive lines (PyMuPDF columnar extraction)
    if not uw_years:
        for i, line in enumerate(lines):
            m = re.match(r'^(19|20)\d{2}$', line)
            if m:
                # Found a year on its own line — collect consecutive year lines
                year_run = [int(line)]
                j = i + 1
                while j < len(lines):
                    m2 = re.match(r'^(19|20)\d{2}$', lines[j])
                    if m2:
                        year_run.append(int(lines[j]))
                        j += 1
                    elif lines[j].lower() == "total":
                        j += 1  # skip "Total" column header
                        break
                    else:
                        break
                if len(year_run) >= 3:
                    uw_years = sorted(year_run)
                    header_idx = i
                    header_end_idx = j - 1
                    break

    if not uw_years or len(uw_years) < 3:
        return None, "no UW year header found in page text"

    # Check max year is within range
    if max(uw_years) > report_year or max(uw_years) < report_year - 2:
        return None, f"max UW year {max(uw_years)} outside range for report year {report_year}"

    n_cols = len(uw_years)

    # Step 2: Parse development rows after the header
    # Each row should have a label + numeric values aligned with the year columns
    dev_period_patterns = [
        r"at\s+end", r"at\s+the\s+end", r"end\s+of\s+underwriting",
        r"year\s+later", r"years?\s+later",
        r"after\s+\w+\s+years?",
        r"\d+\s+months?\s+later",
        r"^(one|two|three|four|five|six|seven|eight|nine|ten)\b",
        r"^\d+\s+year",
    ]
    # Labels that signal the END of development rows (summary/total section)
    stop_labels = [
        "current estimate of cum",     # "Current estimate of cumulative claims incurred"
        "cumulative .* payment",        # "Cumulative gross claims payments to date"
        "less gross claims paid",
        "less net claims paid",
        "less claims paid",
        "gross outstanding claims",
        "net outstanding claims",
        "outstanding .* provision",     # but NOT "outstanding claims provision" in title
    ]

    # Step 3: Collect all numeric values after the year headers.
    # In columnar PDF text, values appear one per line. We collect them
    # sequentially and group into rows of n_cols. Stop at summary keywords.
    # Dev period label patterns — lines matching these are labels, not values
    label_patterns = dev_period_patterns + [
        r"estimate\s+(of\s+)?cumulative",
    ]

    all_values = []
    for line in lines[header_end_idx + 1:]:
        line_lower = line.lower().strip()
        if not line_lower:
            continue
        # Stop at summary/total rows
        if any(re.search(p, line_lower) for p in stop_labels):
            break
        # Skip development period labels (e.g., "12 months later")
        if any(re.search(p, line_lower) for p in label_patterns):
            continue
        # Skip non-numeric text lines (continuation of multi-line labels)
        if re.match(r'^[a-z]', line_lower) and not re.search(r'\d{2,}', line):
            continue
        # Extract numbers from this line
        nums = re.findall(r'[\-]?[\d,]+\.?\d*|\([\d,]+\.?\d*\)', line)
        new_vals = _extract_numbers(nums)
        all_values.extend(new_vals)

    # Group values into rows. Development period d (0 = end of UW year) has
    # a value for each UW year Y where (report_year - Y) >= d.
    # This correctly handles gaps in UW years (e.g., missing 2021).
    max_dev_periods = report_year - min(uw_years) + 1
    dev_rows = []
    idx = 0
    for d in range(max_dev_periods):
        expected = sum(1 for y in uw_years if report_year - y >= d)
        if expected < 1:
            break
        if idx + expected > len(all_values):
            remaining = len(all_values) - idx
            if remaining > 0:
                row_vals = list(all_values[idx:idx + remaining])
                # Right-align: these are the OLDEST years' values
                row = [None] * (n_cols - len(row_vals)) + row_vals \
                      if len(row_vals) < n_cols else row_vals[:n_cols]
                # Actually left-align: values correspond to oldest→newest
                row = list(all_values[idx:idx + remaining])
                row += [None] * (n_cols - len(row))
                dev_rows.append(row[:n_cols])
                idx += remaining
            break
        row = list(all_values[idx:idx + expected])
        row += [None] * (n_cols - len(row))
        dev_rows.append(row[:n_cols])
        idx += expected

    if len(dev_rows) < 2:
        return None, f"only {len(dev_rows)} development rows found in text"

    # Detect currency and units
    text_lower = text.lower()
    currency = "USD"
    if "gbp" in text_lower or "£" in text_lower:
        currency = "GBP"
    elif "eur" in text_lower or "€" in text_lower:
        currency = "EUR"

    units = "millions"
    if "£'000" in text_lower or "£000" in text_lower or "'000" in text_lower:
        units = "thousands"

    # Detect type (gross vs net)
    tri_type = "gross" if "gross" in text_lower else "net"

    triangle = TriangleData(
        type=tri_type,
        currency=currency,
        units=units,
        underwriting_years=[str(y) for y in uw_years],
        development_rows=dev_rows,
    )

    details = (f"{tri_type} {len(uw_years)} UW years "
               f"({min(uw_years)}-{max(uw_years)}), "
               f"{len(dev_rows)} dev rows, {units}, {currency}")
    return triangle, details


# ── Nutrient: parse triangle ─────────────────────────────────────────────

def _parse_nutrient_triangle(grid: list[list[str]], report_year: int):
    """Parse a Nutrient table grid as a claims development triangle.

    Returns (TriangleData, details_str) or (None, reason) or ("new_syndicate", details).
    """
    if len(grid) < 4 or len(grid[0]) < 3:
        return None, "too small for triangle"

    # Find underwriting year columns from header rows (check first 3 rows)
    uw_years = []
    uw_col_indices = []
    for row_idx in range(min(3, len(grid))):
        for col_idx, val in enumerate(grid[row_idx]):
            m = re.search(r'\b(19|20)\d{2}\b', val)
            if m:
                year = int(m.group())
                if 1990 <= year <= 2030 and "prior" not in val.lower() and "&" not in val:
                    if year not in uw_years:
                        uw_years.append(year)
                        uw_col_indices.append(col_idx)

    if len(uw_years) < 1:
        return None, "no underwriting years found"

    # Sort by year
    pairs = sorted(zip(uw_years, uw_col_indices))
    uw_years = [p[0] for p in pairs]
    uw_col_indices = [p[1] for p in pairs]

    # Max UW year must be recent (within 2 years of report year) but need not
    # equal it — run-off syndicates stop writing new business before the report date.
    if max(uw_years) > report_year:
        return None, f"max UW year {max(uw_years)} > report year {report_year}"
    if max(uw_years) < report_year - 2:
        return None, f"max UW year {max(uw_years)} too old for report year {report_year}"

    if len(uw_years) < 3:
        return "new_syndicate", f"{len(uw_years)} UW year(s) ({min(uw_years)}-{max(uw_years)})"

    # Parse development rows — only keep rows that look like development periods
    dev_period_patterns = [
        r"at\s+end", r"at\s+the\s+end", r"end\s+of\s+underwriting",
        r"year\s+later", r"years?\s+later",
        r"^\d+\s+year", r"^(one|two|three|four|five|six|seven|eight|nine|ten)\b",
        r"after\s+\w+\s+years?",               # "After one year", "After two years"
        r"\d+\s+months?\s+later",               # "12 months later", "24 months later"
        r"estimate.*end\s+of\s+underwriting",   # "Estimate of cumulative...end of underwriting year"
    ]
    skip_labels = [
        "current estimate", "cumulative payment", "cumulative claim",
        "outstanding", "provision", "gross outstanding", "net outstanding",
    ]

    dev_rows = []
    for row in grid:
        label = row[0].lower().strip() if row else ""
        if not label:
            continue
        if any(s in label for s in skip_labels):
            continue
        is_dev_row = any(re.search(p, label) for p in dev_period_patterns)
        if not is_dev_row:
            continue

        values = []
        for col_idx in uw_col_indices:
            if col_idx < len(row):
                val = _clean_cell(row[col_idx])
                values.append(val if isinstance(val, (int, float)) else None)
            else:
                values.append(None)
        dev_rows.append(values)

    if len(dev_rows) < 2:
        return None, f"only {len(dev_rows)} development rows"

    # Detect currency from grid text
    flat = _grid_text_lower(grid)
    currency = "USD"
    if "gbp" in flat or chr(163) in flat or "£" in flat:
        currency = "GBP"
    elif "eur" in flat or chr(8364) in flat:
        currency = "EUR"

    # Detect units
    units = "millions"
    if re.search(r"[£$]'?000", flat) or "'000" in flat:
        units = "thousands"

    # Detect gross vs net
    tri_type = "gross"
    if "net" in flat and "gross" not in flat:
        tri_type = "net"

    tri = TriangleData(
        type=tri_type, currency=currency, units=units,
        underwriting_years=uw_years, development_rows=dev_rows,
    )
    details = f"Nutrient triangle: {len(uw_years)} UW years, {len(dev_rows)} dev rows"
    return tri, details


# ── Nutrient: parse LOB ──────────────────────────────────────────────────

# Standard Lloyd's regulatory LOB names
_LOB_KEYWORDS = [
    "accident and health", "motor", "marine aviation", "marine, aviation",
    "fire and other damage", "third party liability", "miscellaneous",
    "reinsurance", "energy", "casualty", "aviation", "property",
    "pecuniary", "credit", "suretyship", "specialty", "transport",
]

_SECTION_HEADERS = {
    "direct insurance", "direct insurance:", "direct",
    "reinsurance acceptances", "reinsurance acceptances:",
}
_TOTAL_LABELS = {"total", "sub-total", "subtotal", "grand total", "direct insurance"}


def _parse_nutrient_lob(grid: list[list[str]], report_year: int):
    """Parse a Nutrient table grid as a segmental analysis / LOB breakdown.

    Returns LOBData or None.
    """
    flat = _grid_text_lower(grid)

    # Must contain multiple LOB keywords
    lob_hits = sum(1 for kw in _LOB_KEYWORDS if kw in flat)
    if lob_hits < 3:
        return None

    # Check this is for the report year (not a comparative)
    # Look at header row for year
    header_text = " ".join(grid[0]) if grid else ""
    for yr in range(report_year - 10, report_year + 2):
        if str(yr) in header_text:
            if yr != report_year:
                return None  # comparative table
            break

    # Find GWP column — look for "premiums" + "written" or positional
    gwp_col = None
    claims_col = None
    if grid and len(grid[0]) >= 2:
        for i, val in enumerate(grid[0]):
            val_lower = val.lower()
            if "written" in val_lower and "premium" in val_lower and gwp_col is None:
                gwp_col = i
            elif "claim" in val_lower and ("incurred" in val_lower or "gross" in val_lower):
                claims_col = i
            elif "earned" in val_lower and "premium" in val_lower and gwp_col is None:
                gwp_col = i  # fallback to earned

    # Positional fallback
    if gwp_col is None and len(grid[0]) >= 3:
        gwp_col = 1
        if len(grid[0]) >= 4:
            claims_col = 3

    if gwp_col is None:
        return None

    # Detect currency
    currency = "USD"
    if "gbp" in flat or chr(163) in flat or "£" in flat:
        currency = "GBP"
    elif "eur" in flat or chr(8364) in flat:
        currency = "EUR"

    # Parse LOB rows
    lob_entries = []
    claims_entries = []
    total_gwp = 0.0

    for row in grid[1:]:
        if not row or not row[0].strip():
            continue
        label = row[0].strip()
        label_lower = label.lower().rstrip(":")

        # Skip section headers
        if label_lower in _SECTION_HEADERS:
            continue

        # Handle totals
        is_total = label_lower in _TOTAL_LABELS
        if is_total:
            if gwp_col < len(row):
                val = _clean_cell(row[gwp_col])
                if isinstance(val, (int, float)):
                    total_gwp = abs(val)
            continue

        # Get GWP value
        gwp_val = None
        if gwp_col < len(row):
            val = _clean_cell(row[gwp_col])
            if isinstance(val, (int, float)):
                gwp_val = abs(val)

        # Get claims value
        claims_val = None
        if claims_col is not None and claims_col < len(row):
            val = _clean_cell(row[claims_col])
            if isinstance(val, (int, float)):
                claims_val = val

        if gwp_val is not None and gwp_val > 0:
            lob_entries.append({"line_of_business": label, "amount_raw": gwp_val})
        elif claims_val is not None:
            lob_entries.append({"line_of_business": label, "amount_raw": 0.0})

        if claims_val is not None:
            claims_entries.append({"line_of_business": label, "amount_raw": claims_val})

    if not lob_entries:
        return None

    # Auto-detect units from magnitude
    if total_gwp == 0:
        total_gwp = sum(e["amount_raw"] for e in lob_entries)

    units_divisor = 1.0
    if total_gwp > 10_000_000:
        units_divisor = 1_000_000.0
    elif total_gwp > 10_000:
        units_divisor = 1_000.0

    total_gwp_m = round(total_gwp / units_divisor, 1) if units_divisor != 1.0 else round(total_gwp, 1)

    for e in lob_entries:
        raw = e.pop("amount_raw")
        e["amount_gbp_m"] = round(raw / units_divisor, 1) if units_divisor != 1.0 else round(raw, 1)
        e["percentage_of_total"] = round(e["amount_gbp_m"] / total_gwp_m * 100, 1) if total_gwp_m > 0 else 0

    for e in claims_entries:
        raw = e.pop("amount_raw")
        e["amount_gbp_m"] = round(raw / units_divisor, 1) if units_divisor != 1.0 else round(raw, 1)

    return LOBData(
        gross_premium_mix=lob_entries,
        gross_premiums_written_gbp_m=total_gwp_m,
        claims_incurred_by_lob=claims_entries if claims_entries else None,
        currency=currency,
        method="nutrient",
    )


# ── Nutrient: parse provisions ────────────────────────────────────────────

def _parse_nutrient_provisions(grid: list[list[str]], report_year: int):
    """Parse a Nutrient table grid for claims provisions movement.

    Returns ProvisionsData or None.
    """
    flat = _grid_text_lower(grid)
    if "prior" not in flat:
        return None

    # Detect column layout from header
    gross_col = ri_col = net_col = None
    if grid:
        for i, val in enumerate(grid[0]):
            h = val.lower()
            if "gross" in h:
                gross_col = i
            elif "reinsur" in h or "share" in h or "ceded" in h:
                ri_col = i
            elif "net" in h:
                net_col = i

    # Positional fallback
    if gross_col is None and len(grid[0]) >= 4:
        gross_col, ri_col, net_col = 1, 2, 3

    # Find "prior year" row
    for row in grid:
        label = row[0].lower() if row else ""
        if "prior" in label and ("claim" in label or "underwriting" in label or "year" in label):
            result = ProvisionsData()
            has_data = False

            for attr, col in [
                ("gross_prior_year_claims", gross_col),
                ("ri_share_prior_year", ri_col),
                ("net_prior_year_claims", net_col),
            ]:
                if col is not None and col < len(row):
                    val = _clean_cell(row[col])
                    if isinstance(val, (int, float)):
                        # Auto-detect units from magnitude
                        if abs(val) > 10_000:
                            val = round(val / 1_000, 1)
                        setattr(result, attr, val)
                        has_data = True

            if has_data:
                return result

    return None


# ── Nutrient: main extraction ─────────────────────────────────────────────

def _extract_nutrient(pdf_path: Path, report_year: int, cache_dir: Path) -> ExtractionResult:
    """Extract tables using Nutrient.io API with targeted page selection."""
    api_key = os.getenv("NUTRIENT_API_KEY")
    if not api_key:
        logger.error("NUTRIENT_API_KEY not set")
        return ExtractionResult()

    result = ExtractionResult(method="nutrient")
    t0 = time.time()

    # Step 1: Find relevant pages
    print(f"  [Nutrient] Scanning {pdf_path.name}...")
    page_matches, page_texts, scan_method = _find_relevant_pages(pdf_path)

    doc = fitz.open(pdf_path)
    total_pages = len(doc)
    doc.close()

    print(f"  [Nutrient] {total_pages} pages scanned via {scan_method}, "
          f"{len(page_matches)} relevant pages found")

    if not page_matches:
        print(f"  [Nutrient] No relevant pages found")
        result.elapsed_s = time.time() - t0
        return result

    for page_num in sorted(page_matches):
        cats = ", ".join(sorted(page_matches[page_num]))
        print(f"    Page {page_num + 1}: [{cats}]")

    # Step 2: Extract relevant pages into slim PDF
    relevant_pages = sorted(page_matches.keys())
    slim_pdf = cache_dir / f"{pdf_path.stem}_slim.pdf"
    _extract_pages_to_pdf(pdf_path, relevant_pages, slim_pdf)
    slim_size = slim_pdf.stat().st_size / 1024
    print(f"  [Nutrient] Slim PDF: {len(relevant_pages)} pages, {slim_size:.0f} KB")

    # Step 3: Call Nutrient API (with caching)
    cache_file = cache_dir / f"{pdf_path.stem}_nutrient.json"
    if cache_file.exists():
        print(f"  [Nutrient] Using cached result")
        with open(cache_file) as f:
            nutrient_result = json.load(f)
    else:
        print(f"  [Nutrient] Sending to API...")
        try:
            nutrient_result = _call_nutrient_api(slim_pdf, api_key)
            with open(cache_file, "w") as f:
                json.dump(nutrient_result, f, indent=2, ensure_ascii=True)
            print(f"  [Nutrient] API completed")
        except Exception as e:
            print(f"  [Nutrient] API failed: {e}")
            slim_pdf.unlink(missing_ok=True)
            result.elapsed_s = time.time() - t0
            return result

    slim_pdf.unlink(missing_ok=True)

    # Step 4: Parse Nutrient tables
    pages = nutrient_result.get("pages", [])
    page_index_to_orig = {i: p for i, p in enumerate(relevant_pages)}

    best_triangle = None
    best_triangle_details = None
    best_lob = None
    best_lob_count = 0
    best_provisions = None

    for slim_idx, page in enumerate(pages):
        orig_page = page_index_to_orig.get(slim_idx, -1)
        cats = page_matches.get(orig_page, set())

        for table in page.get("tables", []):
            cells = table.get("cells", [])
            grid = _cells_to_grid(cells)
            if len(grid) < 2:
                continue

            # Try triangle (on triangle-tagged pages)
            if "claims_triangle" in cats and best_triangle is None:
                tri_result, details = _parse_nutrient_triangle(grid, report_year)
                if tri_result == "new_syndicate":
                    result.first_year_syndicate = True
                    result.triangle_details = details
                    print(f"  [Nutrient] NEW SYNDICATE: {details}")
                elif isinstance(tri_result, TriangleData):
                    n_years = len(tri_result.underwriting_years)
                    # Prefer gross over net, and more years over fewer
                    if (best_triangle is None
                            or (tri_result.type == "gross" and best_triangle.type != "gross")
                            or n_years > len(best_triangle.underwriting_years)):
                        best_triangle = tri_result
                        best_triangle_details = details
                        print(f"  [Nutrient] Triangle: {details}")

            # Try LOB (on premium_mix-tagged pages)
            if "premium_mix" in cats:
                lob = _parse_nutrient_lob(grid, report_year)
                if lob and len(lob.gross_premium_mix) > best_lob_count:
                    best_lob = lob
                    best_lob_count = len(lob.gross_premium_mix)

            # Try provisions (on provisions-tagged pages)
            if "provisions" in cats and best_provisions is None:
                prov = _parse_nutrient_provisions(grid, report_year)
                if prov:
                    best_provisions = prov

    # Text-based triangle fallback
    if best_triangle is None:
        for page_num in sorted(page_matches):
            if "claims_triangle" not in page_matches[page_num]:
                continue
            text = page_texts.get(page_num, "")
            if not text:
                continue
            tri_result, details = _parse_triangle_from_text(text, report_year)
            if isinstance(tri_result, TriangleData):
                n_years = len(tri_result.underwriting_years)
                if (best_triangle is None
                        or (tri_result.type == "gross" and best_triangle.type != "gross")
                        or n_years > len(best_triangle.underwriting_years)):
                    best_triangle = tri_result
                    best_triangle_details = f"{details} (from page text)"
                    print(f"  [Nutrient] Text fallback triangle: {details}")

    result.triangle = best_triangle
    result.triangle_details = best_triangle_details or result.triangle_details
    result.lob = best_lob
    result.provisions = best_provisions
    # Valid triangle trumps new_syndicate flag from a partial/different table
    if best_triangle is not None:
        result.first_year_syndicate = False
    result.elapsed_s = time.time() - t0

    # Summary
    parts = []
    if best_triangle:
        parts.append(f"triangle={len(best_triangle.underwriting_years)} UW years")
    if best_lob:
        parts.append(f"LOB={len(best_lob.gross_premium_mix)} classes, "
                     f"GWP={best_lob.gross_premiums_written_gbp_m}m")
    if best_provisions:
        g = best_provisions.gross_prior_year_claims
        if g is not None:
            parts.append(f"provisions gross={g:+.1f}m")
    if parts:
        print(f"  [Nutrient] Extracted: {'; '.join(parts)} ({result.elapsed_s:.1f}s)")
    else:
        print(f"  [Nutrient] No structured data extracted ({result.elapsed_s:.1f}s)")

    return result


# ── Adobe backend (delegates to existing functions in test_gemini.py) ─────

def _extract_adobe(pdf_path: Path, report_year: int, cache_dir: Path) -> ExtractionResult:
    """Extract tables using Adobe PDF Extract API.

    Uses targeted-page approach: identifies relevant pages first, then sends
    only those pages to Adobe (which charges per page).

    Wraps the existing Adobe functions in test_gemini.py.
    """
    result = ExtractionResult(method="adobe")
    t0 = time.time()

    try:
        from test_gemini import (
            adobe_extract_pdf,
            find_triangle_in_adobe_output,
            find_lob_in_adobe_output,
            find_provisions_movement_in_adobe,
        )
    except ImportError as e:
        logger.error(f"Cannot import Adobe functions: {e}")
        return result

    # Step 1: Find relevant pages (same approach as Nutrient/Azure)
    print(f"  [Adobe] Scanning {pdf_path.name}...")
    page_matches, page_texts, scan_method = _find_relevant_pages(pdf_path)

    if not page_matches:
        print(f"  [Adobe] No relevant pages found")
        result.elapsed_s = time.time() - t0
        return result

    relevant_pages = sorted(page_matches.keys())
    print(f"  [Adobe] {len(relevant_pages)} relevant pages found via {scan_method}")

    # Step 2: Create slim PDF with only relevant pages
    slim_pdf = cache_dir / f"{pdf_path.stem}_slim.pdf"

    # Check if Adobe already processed this (cached output exists)
    report_out = cache_dir / f"{pdf_path.stem}_slim"
    if not (report_out / "structuredData.json").exists():
        _extract_pages_to_pdf(pdf_path, relevant_pages, slim_pdf)
        slim_size = slim_pdf.stat().st_size / 1024
        orig_size = pdf_path.stat().st_size / 1024
        print(f"  [Adobe] Slim PDF: {len(relevant_pages)} pages, {slim_size:.0f} KB "
              f"(vs {orig_size:.0f} KB original)")

    # Step 3: Send slim PDF to Adobe
    adobe_dir = adobe_extract_pdf(slim_pdf, output_dir=cache_dir)
    slim_pdf.unlink(missing_ok=True)

    if not adobe_dir:
        result.elapsed_s = time.time() - t0
        return result

    # Triangle
    tri_data, details = find_triangle_in_adobe_output(adobe_dir, report_year)
    if tri_data == "new_syndicate":
        result.first_year_syndicate = True
        result.triangle_details = details
    elif tri_data:
        result.triangle = TriangleData(**tri_data)
        result.triangle_details = details

    # LOB
    lob_data = find_lob_in_adobe_output(adobe_dir, report_year)
    if lob_data:
        result.lob = LOBData(
            gross_premium_mix=lob_data["gross_premium_mix"],
            gross_premiums_written_gbp_m=lob_data["gross_premiums_written_gbp_m"],
            claims_incurred_by_lob=lob_data.get("claims_incurred_by_lob"),
            currency=lob_data["currency"],
            method="adobe",
        )

    # Provisions
    prov_data = find_provisions_movement_in_adobe(adobe_dir, report_year)
    if prov_data:
        result.provisions = ProvisionsData(
            gross_prior_year_claims=prov_data.get("gross_prior_year_claims"),
            ri_share_prior_year=prov_data.get("ri_share_prior_year"),
            net_prior_year_claims=prov_data.get("net_prior_year_claims"),
        )

    result.elapsed_s = time.time() - t0

    parts = []
    if result.triangle:
        parts.append(f"triangle={len(result.triangle.underwriting_years)} UW years")
    if result.lob:
        parts.append(f"LOB={len(result.lob.gross_premium_mix)} classes")
    if result.provisions:
        parts.append("provisions")
    if parts:
        print(f"  [Adobe] Extracted: {'; '.join(parts)} ({result.elapsed_s:.1f}s)")
    else:
        print(f"  [Adobe] No structured data extracted ({result.elapsed_s:.1f}s)")

    return result


# ── Azure backend ────────────────────────────────────────────────────────

def _azure_table_to_grid(table) -> list[list[str]]:
    """Convert Azure DocumentTable to a 2D grid."""
    grid = [["" for _ in range(table.column_count)] for _ in range(table.row_count)]
    for cell in table.cells:
        grid[cell.row_index][cell.column_index] = cell.content.strip()
    return grid


def _call_azure_api(pdf_path: Path, endpoint: str, api_key: str):
    """Send PDF to Azure Document Intelligence prebuilt-layout model.

    Returns the Azure AnalyzeResult object.
    """
    from azure.core.credentials import AzureKeyCredential
    from azure.ai.documentintelligence import DocumentIntelligenceClient

    client = DocumentIntelligenceClient(
        endpoint=endpoint,
        credential=AzureKeyCredential(api_key),
    )

    with open(pdf_path, "rb") as f:
        poller = client.begin_analyze_document(
            "prebuilt-layout",
            body=f,
            content_type="application/pdf",
        )
    return poller.result()


def _classify_table_content(grid: list[list[str]]) -> set[str]:
    """Classify a table by its cell content (keywords and structure)."""
    flat = _grid_text_lower(grid)
    cats = set()

    # ── Claims triangle detection ───────────────────────────────────────
    # Detect from: (a) year count + dev periods, (b) title keywords, (c) row labels
    uw_years = re.findall(r'\b(19|20)\d{2}\b', flat)
    dev_patterns = [
        "at end", "year later", "years later", "one year", "two year",
        "after one", "after two", "after three", "after four", "after five",
        "months later", "month later",
    ]
    # Title/header keywords that strongly indicate a triangle
    triangle_title_kw = [
        "claims development", "cumulative claims incurred",
        "cumulative gross claims", "cumulative net claims",
        "development table", "development triangle",
        "outstanding claims provision",
    ]
    has_dev_periods = any(p in flat for p in dev_patterns)
    has_triangle_title = any(kw in flat for kw in triangle_title_kw)

    if len(uw_years) >= 3 and (has_dev_periods or has_triangle_title):
        cats.add("claims_triangle")
    elif has_triangle_title and len(uw_years) >= 1:
        # Title is strong evidence even with fewer detected years
        cats.add("claims_triangle")

    # Negative: sensitivity/assumption tables are NOT triangles
    sensitivity_kw = ["change in assumptions", "impact on", "severity", "frequency"]
    if sum(1 for kw in sensitivity_kw if kw in flat) >= 2:
        cats.discard("claims_triangle")
        cats.add("_not_triangle")  # prevent page-level tag from overriding

    # ── LOB / premium mix ───────────────────────────────────────────────
    lob_hits = sum(1 for kw in _LOB_KEYWORDS if kw in flat)
    if lob_hits >= 3:
        cats.add("premium_mix")

    # ── Provisions ──────────────────────────────────────────────────────
    if "prior" in flat and ("claim" in flat or "provision" in flat):
        if any(kw in flat for kw in ["gross", "net", "reinsur"]):
            cats.add("provisions")

    return cats


def _extract_azure(pdf_path: Path, report_year: int, cache_dir: Path) -> ExtractionResult:
    """Extract tables using Azure AI Document Intelligence.

    Uses the same targeted-page approach: PyMuPDF/Tesseract identifies
    relevant pages, then sends them in batches to Azure (F0 tier = 2 pages
    per request; S0 tier handles full documents).
    """
    endpoint = os.getenv("DOCUMENTINTELLIGENCE_ENDPOINT")
    api_key = os.getenv("DOCUMENTINTELLIGENCE_API_KEY")
    if not endpoint or not api_key:
        logger.error("DOCUMENTINTELLIGENCE_ENDPOINT or DOCUMENTINTELLIGENCE_API_KEY not set")
        return ExtractionResult()

    result = ExtractionResult(method="azure")
    t0 = time.time()

    # Step 1: Find relevant pages
    print(f"  [Azure] Scanning {pdf_path.name}...")
    page_matches, page_texts, scan_method = _find_relevant_pages(pdf_path)

    doc = fitz.open(pdf_path)
    total_pages = len(doc)
    doc.close()

    print(f"  [Azure] {total_pages} pages scanned via {scan_method}, "
          f"{len(page_matches)} relevant pages found")

    if not page_matches:
        print(f"  [Azure] No relevant pages found")
        result.elapsed_s = time.time() - t0
        return result

    for page_num in sorted(page_matches):
        cats = ", ".join(sorted(page_matches[page_num]))
        print(f"    Page {page_num + 1}: [{cats}]")

    # Step 2: Sort pages by priority and send in batches of 2
    priority_order = ["claims_triangle", "premium_mix", "provisions", "pl_account"]
    page_priority = {}
    relevant_pages = sorted(page_matches.keys())
    for page_num in relevant_pages:
        cats = page_matches[page_num]
        best_priority = len(priority_order)
        for cat in cats:
            if cat in priority_order:
                best_priority = min(best_priority, priority_order.index(cat))
        page_priority[page_num] = best_priority

    sorted_pages = sorted(relevant_pages, key=lambda p: page_priority[p])
    batch_size = 2  # Azure F0 tier limit
    batches = [sorted_pages[i:i+batch_size] for i in range(0, len(sorted_pages), batch_size)]

    # Check for cached Azure results — cache key includes relevant pages
    # so cache invalidates if page classification changes
    pages_hash = "_".join(str(p) for p in sorted(relevant_pages))
    cache_file = cache_dir / f"{pdf_path.stem}_azure.json"
    all_grids = []  # (grid, orig_page, categories)

    cache_valid = False
    if cache_file.exists():
        with open(cache_file) as f:
            cached = json.load(f)
        # Validate cache: must match code version and page set
        cached_ver = cached.get("_cache_version") if isinstance(cached, dict) else None
        cached_pages = cached.get("_pages_hash") if isinstance(cached, dict) else None
        if not isinstance(cached, dict) or cached_ver != _CACHE_VERSION:
            cache_file.unlink()
            reason = "legacy format" if not isinstance(cached, dict) else "code changed"
            print(f"  [Azure] Cache invalidated ({reason}) — re-extracting")
        elif cached_pages != pages_hash:
            cache_file.unlink()
            print(f"  [Azure] Cache invalidated (page set changed) — re-extracting")
        else:
            cache_valid = True
            print(f"  [Azure] Using cached result")
            for entry in cached.get("tables", []):
                grid = entry["grid"]
                orig_page = entry["orig_page"]
                cats = set(entry["categories"])
                all_grids.append((grid, orig_page, cats))

    if not cache_valid:
        # Send pages to Azure API in batches of 2
        for batch_idx, batch_pages in enumerate(batches):
            batch_cats = set()
            for p in batch_pages:
                batch_cats.update(page_matches[p])
            cat_str = ", ".join(sorted(batch_cats))

            slim_pdf = cache_dir / f"{pdf_path.stem}_slim_b{batch_idx}.pdf"
            _extract_pages_to_pdf(pdf_path, batch_pages, slim_pdf)
            pages_str = ", ".join(str(p+1) for p in batch_pages)
            print(f"  [Azure] Batch {batch_idx+1}/{len(batches)}: pages {pages_str} [{cat_str}]")

            try:
                azure_result = _call_azure_api(slim_pdf, endpoint, api_key)
                n_tables = len(azure_result.tables) if azure_result.tables else 0
                print(f"    {n_tables} tables found")

                if azure_result.tables:
                    for table in azure_result.tables:
                        grid = _azure_table_to_grid(table)
                        if len(grid) < 2:
                            continue
                        # Map slim page to original
                        orig_page = batch_pages[0]
                        if table.bounding_regions:
                            for br in table.bounding_regions:
                                slim_idx = br.page_number - 1
                                if slim_idx < len(batch_pages):
                                    orig_page = batch_pages[slim_idx]
                                    break

                        page_cats = page_matches.get(orig_page, set())
                        content_cats = _classify_table_content(grid)
                        combined_cats = page_cats | content_cats
                        # Content-level negative signals override page-level tags
                        if "_not_triangle" in content_cats:
                            combined_cats.discard("claims_triangle")
                            combined_cats.discard("_not_triangle")
                        all_grids.append((grid, orig_page, combined_cats))

            except Exception as e:
                print(f"    FAILED: {e}")

            slim_pdf.unlink(missing_ok=True)

        # Cache extracted grids for reuse (versioned)
        cache_data = {
            "_cache_version": _CACHE_VERSION,
            "_pages_hash": pages_hash,
            "tables": [
                {"grid": grid, "orig_page": orig_page, "categories": sorted(cats)}
                for grid, orig_page, cats in all_grids
            ],
        }
        with open(cache_file, "w") as f:
            json.dump(cache_data, f, indent=2, ensure_ascii=True)

    # Step 3: Parse tables
    best_triangle = None
    best_triangle_details = None
    best_lob = None
    best_lob_count = 0
    best_provisions = None

    for grid, orig_page, cats in all_grids:
        if "claims_triangle" in cats and best_triangle is None:
            tri_result, details = _parse_nutrient_triangle(grid, report_year)
            if tri_result == "new_syndicate":
                result.first_year_syndicate = True
                result.triangle_details = details
            elif isinstance(tri_result, TriangleData):
                n_years = len(tri_result.underwriting_years)
                if (best_triangle is None
                        or (tri_result.type == "gross" and best_triangle.type != "gross")
                        or n_years > len(best_triangle.underwriting_years)):
                    best_triangle = tri_result
                    best_triangle_details = details

        if "premium_mix" in cats:
            lob = _parse_nutrient_lob(grid, report_year)
            if lob and len(lob.gross_premium_mix) > best_lob_count:
                best_lob = lob
                best_lob.method = "azure"
                best_lob_count = len(lob.gross_premium_mix)

        if "provisions" in cats and best_provisions is None:
            prov = _parse_nutrient_provisions(grid, report_year)
            if prov:
                best_provisions = prov

    # Step 4: Text-based triangle fallback — if Azure didn't find a triangle
    # table, try parsing from the raw page text on claims_triangle pages
    if best_triangle is None:
        for page_num in sorted(page_matches):
            if "claims_triangle" not in page_matches[page_num]:
                continue
            text = page_texts.get(page_num, "")
            if not text:
                continue
            tri_result, details = _parse_triangle_from_text(text, report_year)
            if isinstance(tri_result, TriangleData):
                n_years = len(tri_result.underwriting_years)
                if (best_triangle is None
                        or (tri_result.type == "gross" and best_triangle.type != "gross")
                        or n_years > len(best_triangle.underwriting_years)):
                    best_triangle = tri_result
                    best_triangle_details = f"{details} (from page text)"
                    print(f"  [Azure] Text fallback triangle: {details}")

    result.triangle = best_triangle
    result.triangle_details = best_triangle_details or result.triangle_details
    result.lob = best_lob
    result.provisions = best_provisions
    # Valid triangle trumps new_syndicate flag from a partial/different table
    if best_triangle is not None:
        result.first_year_syndicate = False
    result.elapsed_s = time.time() - t0

    # Summary
    parts = []
    if best_triangle:
        parts.append(f"triangle={len(best_triangle.underwriting_years)} UW years")
    if best_lob:
        parts.append(f"LOB={len(best_lob.gross_premium_mix)} classes, "
                     f"GWP={best_lob.gross_premiums_written_gbp_m}m")
    if best_provisions:
        g = best_provisions.gross_prior_year_claims
        if g is not None:
            parts.append(f"provisions gross={g:+.1f}m")
    if parts:
        print(f"  [Azure] Extracted: {'; '.join(parts)} ({result.elapsed_s:.1f}s)")
    else:
        print(f"  [Azure] No structured data extracted ({result.elapsed_s:.1f}s)")

    return result
