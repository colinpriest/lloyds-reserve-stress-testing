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

try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None
    logging.getLogger(__name__).warning("PyMuPDF (fitz) not installed — text-based triangle fallback unavailable")
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# Bump this when extraction logic changes to invalidate cached table grids
_CACHE_VERSION = 6  # v6: fix uw-year regex in _classify_table_content (non-capturing group);
                    #     add "underlying pure year" as triangle title keyword;
                    #     add "underlying pure year" + dev-period labels as transposed-triangle signal


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
    opening_gross_claims_outstanding: Optional[float] = None

    def to_dict(self) -> dict:
        d = {}
        if self.gross_prior_year_claims is not None:
            d["gross_prior_year_claims"] = self.gross_prior_year_claims
        if self.ri_share_prior_year is not None:
            d["ri_share_prior_year"] = self.ri_share_prior_year
        if self.net_prior_year_claims is not None:
            d["net_prior_year_claims"] = self.net_prior_year_claims
        if self.opening_gross_claims_outstanding is not None:
            d["opening_gross_claims_outstanding"] = self.opening_gross_claims_outstanding
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
    relevant_pages: list[int] = field(default_factory=list)
    rotated_pages: set[int] = field(default_factory=set)


# ── Public API ────────────────────────────────────────────────────────────

def extract_tables(
    pdf_path: Path,
    report_year: int,
    backend: TableBackend = TableBackend.AZURE,
    cache_dir: Optional[Path] = None,
    azure_paid: bool = False,
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
        return _extract_azure(pdf_path, report_year, cache_dir, azure_paid=azure_paid)
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
        "development year", "year of account",
        "underlying pure year", "incurred at end of underwriting",
        "ultimate contract outstanding claims",
        "gross of reinsurance", "net of reinsurance",
        # Beazley-style loss ratio triangles use "12 months", "24 months" etc.
        # as development period labels instead of "X years later"
        "12 months", "24 months",
        "gross claims liabilities", "total ultimate losses",
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
        "segmental analysis", "analysis of underwriting result",
        "analysis of the underwriting result",
        "class of business", "by class of business",
        "accident and health", "marine aviation",
        "fire and other damage", "third party liability",
        "reinsurance", "miscellaneous",
        "gross premiums written", "commissions on direct insurance",
    ],
    "balance_sheet": [
        "statement of financial position", "balance sheet",
        "total assets", "total liabilities",
        "technical provisions", "claims outstanding",
        "gross technical provisions",
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
    # Normalise non-breaking spaces (U+00A0) that PyMuPDF often emits,
    # collapse newlines to spaces so multi-word keywords match even
    # when PyMuPDF splits them across lines (e.g. "years\nlater"),
    # and collapse runs of whitespace to single spaces so column-layout
    # PDFs match (e.g. "Accident and  health" → "accident and health")
    text_lower = re.sub(r'\s+', ' ', text.replace("\u00a0", " ")).lower()
    categories = set()
    for category, keywords in _PAGE_KEYWORDS.items():
        hits = sum(1 for kw in keywords if kw.lower() in text_lower)
        if hits >= 2:
            categories.add(category)
    return categories


def _find_relevant_pages(pdf_path: Path) -> tuple[dict, dict, str, set]:
    """Find relevant pages using PyMuPDF (native) or Tesseract (scanned).

    Returns (page_matches, page_texts, method, rotated_pages).
    rotated_pages is a set of page numbers whose content is physically rotated
    90° clockwise on the page (common in scanned syndicate reports with
    landscape tables).  These pages need rotation before sending to APIs.
    """
    scanned = _is_scanned_pdf(pdf_path)

    if scanned:
        logger.info(f"Scanned PDF detected, using Tesseract OCR")
        return _find_pages_ocr(pdf_path)
    else:
        matches, texts, method = _find_pages_native(pdf_path)
        return matches, texts, method, set()


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


def _ocr_text_quality(text: str) -> float:
    """Score OCR text quality from 0.0 (garbage) to 1.0 (clean).

    Rotated scanned pages produce gibberish when OCR'd in the wrong
    orientation — lots of short "words", high non-alpha ratio, etc.
    """
    words = text.split()
    if len(words) < 3:
        return 0.0
    # Fraction of words that are ≥3 characters (real words)
    long_words = sum(1 for w in words if len(w) >= 3)
    long_frac = long_words / len(words)
    # Fraction of characters that are alphanumeric or common punctuation
    clean_chars = sum(1 for c in text if c.isalnum() or c in ' .,;:()-£$%\n\t')
    clean_frac = clean_chars / max(1, len(text))
    return (long_frac + clean_frac) / 2


def _find_pages_ocr(pdf_path: Path) -> tuple[dict, dict, str, set]:
    """Scan pages with Tesseract OCR for scanned PDFs.

    Uses PyMuPDF to render page images (with rotation normalised to 0)
    then Tesseract to extract text.  This avoids Poppler's incorrect
    handling of /Rotate flags on some scanned syndicate reports that
    causes landscape pages to render upside-down.

    When normal-orientation OCR produces garbage text, the image is
    re-tried at 90° and 270° rotations to handle pages where the
    content is physically rotated (e.g. landscape claims triangles
    in scanned syndicate reports).

    Returns (page_matches, page_texts, "tesseract", rotated_pages).
    rotated_pages is a set of page numbers that needed rotation.
    """
    try:
        import pytesseract as _pytesseract
        from PIL import Image
        from io import BytesIO
        # Set Tesseract path if not in PATH
        tesseract_path = Path("C:/Program Files/Tesseract-OCR/tesseract.exe")
        if tesseract_path.exists():
            _pytesseract.pytesseract.tesseract_cmd = str(tesseract_path)
    except ImportError:
        logger.warning("pytesseract/Pillow not installed, cannot OCR scanned PDF")
        return {}, {}, "none", set()

    page_matches = {}
    page_texts = {}
    rotated_pages = set()  # pages that needed rotation for correct OCR

    doc = fitz.open(pdf_path)
    n_pages = len(doc)
    # First pass: OCR all pages in normal orientation
    for page_num in range(n_pages):
        page = doc[page_num]
        # Remove incorrect /Rotate flags before rendering.  Some scanned PDFs
        # have landscape pages with rotation=270 that renders content upside-down.
        if page.rotation != 0:
            page.set_rotation(0)
        pix = page.get_pixmap(dpi=200)
        image = Image.open(BytesIO(pix.tobytes("png")))
        text = _pytesseract.image_to_string(image)
        page_texts[page_num] = text
        categories = _classify_page(text)
        if categories:
            page_matches[page_num] = categories
        if (page_num + 1) % 10 == 0:
            logger.info(f"  OCR'd {page_num + 1}/{n_pages} pages")

    # Second pass: re-scan unclassified non-blank pages at 90° CW rotation.
    # Some scanned syndicate reports have landscape claims development
    # tables physically rotated on the page.  Normal OCR produces garbage
    # for these; rotating the image 90° yields correct readable text.
    #
    # Only retries pages that weren't already classified in the first pass,
    # so the extra cost is bounded by the number of "mystery" pages.
    unclassified = [p for p in range(n_pages)
                    if p not in page_matches and len(page_texts[p].strip()) >= 20]
    if unclassified:
        logger.info(f"  Rotation scan: retrying {len(unclassified)} unclassified pages")
        for page_num in unclassified:
            page = doc[page_num]
            if page.rotation != 0:
                page.set_rotation(0)
            pix = page.get_pixmap(dpi=200)
            image = Image.open(BytesIO(pix.tobytes("png")))
            rotated_img = image.rotate(-90, expand=True)  # 90° CW
            rot_text = _pytesseract.image_to_string(rotated_img)
            rot_categories = _classify_page(rot_text)
            if rot_categories:
                # Rotation found relevant content — use rotated text
                page_texts[page_num] = rot_text
                page_matches[page_num] = rot_categories
                rotated_pages.add(page_num)
                cats_str = ", ".join(sorted(rot_categories))
                logger.info(f"  Page {page_num + 1}: content physically rotated 90°, "
                            f"found [{cats_str}] after rotation")
        if rotated_pages:
            logger.info(f"  Rotation scan complete: found {len(rotated_pages)} rotated pages")

    doc.close()

    return page_matches, page_texts, "tesseract", rotated_pages


def _extract_pages_to_pdf(
    pdf_path: Path,
    page_numbers: list[int],
    output_path: Path,
    rotated_pages: set[int] | None = None,
):
    """Create a new PDF containing only the specified pages.

    Parameters
    ----------
    rotated_pages : set of page numbers whose content is physically rotated
        90° clockwise on the scanned page.  For these pages the rendered
        image is re-drawn rotated so that API backends (Azure DI, etc.)
        receive correctly oriented content.
    """
    import tempfile
    # Write to a temp file first, then rename — avoids fitz.save failure
    # on Windows when the target path is locked by another process.
    try:
        output_path.unlink(missing_ok=True)
    except OSError:
        pass
    if rotated_pages is None:
        rotated_pages = set()

    src = fitz.open(pdf_path)
    dst = fitz.open()

    for page_num in sorted(page_numbers):
        if page_num in rotated_pages:
            # Page content is physically rotated 90° CW on the scan.
            # Re-render at high DPI, rotate the image, and insert as a
            # new image-based page so Azure DI sees correctly oriented content.
            src_page = src[page_num]
            if src_page.rotation != 0:
                src_page.set_rotation(0)
            pix = src_page.get_pixmap(dpi=200)
            from PIL import Image
            from io import BytesIO
            img = Image.open(BytesIO(pix.tobytes("png")))
            img_rotated = img.rotate(-90, expand=True)  # 90° CW
            buf = BytesIO()
            img_rotated.save(buf, format="PNG")
            buf.seek(0)
            # Create a new page matching the rotated dimensions
            w_pt = img_rotated.width * 72 / 200  # convert pixels back to points
            h_pt = img_rotated.height * 72 / 200
            new_page = dst.new_page(width=w_pt, height=h_pt)
            new_page.insert_image(
                fitz.Rect(0, 0, w_pt, h_pt),
                stream=buf.read(),
            )
            logger.info(f"  Rotated page {page_num + 1} for API submission")
        else:
            dst.insert_pdf(src, from_page=page_num, to_page=page_num)

    # Normalise rotated pages: some scanned syndicate reports have landscape
    # pages with incorrect /Rotate flags (e.g. rotation=270 on content that
    # is already correctly oriented).  Removing the flag lets Azure DI read
    # the raw page content, which is the correct orientation for these PDFs.
    for page in dst:
        if page.rotation != 0:
            page.set_rotation(0)
    # Save to temp file in the same directory, then rename (atomic on same FS)
    fd, tmp_path = tempfile.mkstemp(suffix=".pdf", dir=str(output_path.parent))
    os.close(fd)
    dst.save(tmp_path)
    dst.close()
    src.close()

    # If the slim PDF is too large (e.g. scanned pages with huge embedded
    # images), re-render every page as a compressed JPEG image at 150 DPI.
    # This keeps the file under the Gemini API size limit (~20 MB).
    MAX_SLIM_PDF_BYTES = 20 * 1024 * 1024  # 20 MB
    if os.path.getsize(tmp_path) > MAX_SLIM_PDF_BYTES:
        logger.info(
            f"  Slim PDF too large ({os.path.getsize(tmp_path) / 1024 / 1024:.1f} MB), "
            f"compressing pages as JPEG..."
        )
        from PIL import Image
        from io import BytesIO
        big = fitz.open(tmp_path)
        compressed = fitz.open()
        for page in big:
            pix = page.get_pixmap(dpi=150)
            img = Image.open(BytesIO(pix.tobytes("png")))
            buf = BytesIO()
            img.save(buf, format="JPEG", quality=75)
            buf.seek(0)
            w_pt = pix.width * 72 / 150
            h_pt = pix.height * 72 / 150
            new_page = compressed.new_page(width=w_pt, height=h_pt)
            new_page.insert_image(
                fitz.Rect(0, 0, w_pt, h_pt),
                stream=buf.read(),
            )
        # Save to a second temp file — cannot overwrite tmp_path while
        # big still holds it open (Windows file locking).
        fd2, tmp2 = tempfile.mkstemp(suffix=".pdf", dir=str(output_path.parent))
        os.close(fd2)
        compressed.save(tmp2)
        compressed.close()
        big.close()
        # Replace the original oversized temp with the compressed one
        Path(tmp_path).unlink(missing_ok=True)
        Path(tmp2).rename(tmp_path)
        logger.info(
            f"  Compressed slim PDF: {os.path.getsize(tmp_path) / 1024 / 1024:.1f} MB"
        )

    try:
        Path(tmp_path).replace(output_path)
    except OSError:
        # On Windows, replace can fail if the target is locked.
        # Fall back to remove-then-rename.
        try:
            output_path.unlink(missing_ok=True)
            Path(tmp_path).rename(output_path)
        except OSError:
            # Last resort: just use the temp file directly
            import shutil
            shutil.copy2(tmp_path, str(output_path))
            Path(tmp_path).unlink(missing_ok=True)


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
    """Clean a cell value: strip whitespace, parse numbers, handle parenthesized negatives.

    Standalone dashes (-, –, —) are treated as 0.0 per UK accounting convention
    where a dash in a financial statement means nil/zero.
    """
    if not text or not text.strip():
        return None
    # Strip Azure Document Intelligence annotations (e.g., ":unselected:", ":selected:")
    s = re.sub(r':(?:un)?selected:', '', text).strip()
    if not s:
        return None
    s = s.replace(",", "").replace(" ", "")
    # Standalone dash = nil/zero in accounting context
    if s in ("-", "\u2013", "\u2014", "nil", "Nil"):
        return 0.0
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


def _clean_cell_triangle(text: str):
    """Clean a triangle cell value — same as _clean_cell but treats dashes as None.

    In a claims development triangle, a dash means "no data yet" (the UW year
    hasn't reached that development period), not "zero claims".
    """
    if not text or not text.strip():
        return None
    s = re.sub(r':(?:un)?selected:', '', text).strip()
    if not s:
        return None
    s = s.replace(",", "").replace(" ", "")
    # Standalone dash = no data in triangle context
    if s in ("-", "\u2013", "\u2014", "nil", "Nil"):
        return None
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


def _parse_transposed_triangle_from_text(text: str, report_year: int):
    """Parse a transposed triangle from concatenated page text.

    Handles the format where "Development Year 1 2 3 ... Total" is a header
    and UW years are row labels, but everything is concatenated without spaces
    (common in certain PyMuPDF extractions).

    Pattern: "...Year of Account201657,73559,926117,918..."
    """
    text_lower = text.lower()
    # Normalize whitespace for marker detection (PyMuPDF often inserts \n mid-phrase)
    text_norm = re.sub(r'\s+', ' ', text_lower)

    # Must contain development period marker AND UW year row marker
    # Standard format: "Development Year" + "Year of Account"
    # Alt format (e.g. syndicate 1919): "Incurred at end of underwriting year" + "Underlying Pure Year"
    dev_year_pos = text_norm.find("development year")
    yoa_pos = text_norm.find("year of account")

    # Try alternative markers if standard ones not found
    if dev_year_pos == -1:
        # "Incurred at end of underwriting year" acts as the first dev period column
        dev_year_pos = text_norm.find("incurred at end of underwriting")
    if yoa_pos == -1:
        yoa_pos = text_norm.find("underlying pure year")

    if dev_year_pos == -1 or yoa_pos == -1:
        return None, "no transposed triangle markers found"

    # Map position in normalized text back to original text.
    # Build a mapping from normalized-text positions to original-text positions.
    # Since we collapsed whitespace, find the marker phrase in the original text
    # by searching for the words with flexible whitespace between them.
    def _find_in_original(phrase, start_hint=0):
        """Find a phrase in original text allowing flexible whitespace."""
        words = phrase.split()
        pattern = r'\s+'.join(re.escape(w) for w in words)
        m = re.search(pattern, text_lower[start_hint:])
        if m:
            return start_hint + m.start(), start_hint + m.end()
        return None, None

    if "year of account" in text_norm[yoa_pos:yoa_pos + 25]:
        yoa_start, yoa_end = _find_in_original("year of account")
    else:
        yoa_start, yoa_end = _find_in_original("underlying pure year")

    if yoa_start is None:
        return None, "could not locate UW year label in original text"

    after_yoa = text[yoa_end:]

    # Truncate at the first stop marker to avoid picking up a second triangle
    # (e.g., gross triangle followed by net triangle on same page)
    section_stop_patterns = [
        "current estimate", "cumulative payment",
        "cumulative gross payment", "cumulative net payment",
        "gross claims reserve", "net claims reserve",
        "gross unearned", "net unearned",
        "estimate of cumulative net",
        "net of reinsurance",  # stop before net triangle on same page
    ]
    section_end = len(after_yoa)
    for sp in section_stop_patterns:
        sp_pos = after_yoa.lower().find(sp)
        if sp_pos != -1 and sp_pos < section_end:
            section_end = sp_pos
    after_yoa = after_yoa[:section_end]

    # Find all UW year + values sequences
    # UW years appear as 4-digit numbers that are plausible years (2010-2030)
    # followed by comma-formatted numbers
    uw_years = []
    year_values = {}  # {year: [values]}

    # Split on year boundaries: find all years in the text
    year_positions = list(re.finditer(r'((?:19|20)\d{2})', after_yoa))
    valid_year_positions = []
    for mp in year_positions:
        yr = int(mp.group(1))
        if 1990 <= yr <= 2030 and yr <= report_year:
            # Skip duplicate years (same year already found)
            if yr not in [v[2] for v in valid_year_positions]:
                valid_year_positions.append((mp.start(), mp.end(), yr))

    if len(valid_year_positions) < 2:
        return None, "not enough UW years found"

    for i, (start, end, year) in enumerate(valid_year_positions):
        # Find the end of this row's data
        if i + 1 < len(valid_year_positions):
            row_text = after_yoa[end:valid_year_positions[i + 1][0]]
        else:
            # Last year — take remaining text (already truncated at stop marker)
            row_text = after_yoa[end:]

        # Extract numbers from this row — use comma-formatted number regex
        # to correctly split concatenated values like "57,73559,926117,918"
        nums = re.findall(r'\(\d{1,3}(?:,\d{3})*\)|\d{1,3}(?:,\d{3})*', row_text)
        values = _extract_numbers(nums)
        if values:
            uw_years.append(year)
            year_values[year] = values

    if len(uw_years) < 2:
        return None, "not enough UW year rows found"

    uw_years = sorted(uw_years)

    # Validate year range
    if max(uw_years) > report_year:
        return None, f"max UW year {max(uw_years)} > report year {report_year}"
    if max(uw_years) < report_year - 5:
        return None, f"max UW year {max(uw_years)} too old for report year {report_year}"

    if len(uw_years) < 3:
        return "new_syndicate", f"{len(uw_years)} UW year(s)"

    # Strip Total column: each UW year Y should have at most
    # (report_year - Y + 1) development values. If there's an extra value
    # (the Total column), remove it.
    for y in uw_years:
        expected_devs = report_year - y + 1
        if len(year_values[y]) > expected_devs:
            year_values[y] = year_values[y][:expected_devs]

    # Build transposed triangle: dev_rows[d][y] = year_values[y][d]
    max_dev = max(len(year_values[y]) for y in uw_years)
    dev_rows = []
    for d in range(max_dev):
        row = []
        for y in uw_years:
            vals = year_values[y]
            if d < len(vals):
                row.append(vals[d])
            else:
                row.append(None)
        dev_rows.append(row)

    if len(dev_rows) < 2:
        return None, f"only {len(dev_rows)} development rows"

    # Detect currency and units
    currency = "USD"
    if "gbp" in text_lower or "£" in text_lower:
        currency = "GBP"
    elif "eur" in text_lower or "€" in text_lower:
        currency = "EUR"

    units = "millions"
    if re.search(r"[£$]'?000", text_lower) or "'000" in text_lower:
        units = "thousands"

    # Detect type — check context before the triangle header for gross/net
    # Default to gross since gross triangles typically appear first
    context_start = max(0, yoa_start - 300)
    context = text_lower[context_start:yoa_start + 50]
    if "net" in context and "gross" not in context:
        tri_type = "net"
    else:
        tri_type = "gross"

    triangle = TriangleData(
        type=tri_type, currency=currency, units=units,
        underwriting_years=uw_years, development_rows=dev_rows,
    )
    details = (f"{tri_type} {len(uw_years)} UW years "
               f"({min(uw_years)}-{max(uw_years)}), "
               f"{len(dev_rows)} dev rows (transposed text), {units}, {currency}")
    return triangle, details


def _year_has_prior_context(line: str, year_str: str) -> bool:
    """Check if a year in a line is qualified with 'prior' (e.g. '2011 and prior').

    Checks both before and after the year position in the line.
    """
    pos = line.find(year_str)
    if pos < 0:
        return False
    # Check 15 chars before and 20 chars after the year for "prior"
    before = line[max(0, pos - 15):pos].lower()
    after = line[pos + len(year_str):pos + len(year_str) + 20].lower()
    return "prior" in before or "prior" in after


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
        years_on_line = re.findall(r'\b((?:19|20)\d{2})(?:\d(?!\d)|\b)', line)
        years_on_line = [int(y) for y in years_on_line
                         if 1990 <= int(y) <= 2030
                         and not _year_has_prior_context(line, str(y))]
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

    # Strategy C: Transposed triangle in concatenated text
    # Pattern: "Development Year 123456Total...Year of Account201657,73559,926..."
    # where UW years are row labels and dev periods 1,2,3... are columns
    if not uw_years:
        result = _parse_transposed_triangle_from_text(text, report_year)
        if result[0] is not None:
            return result

    if not uw_years or len(uw_years) < 3:
        return None, "no UW year header found in page text"

    # Check max year is within range
    if max(uw_years) > report_year or max(uw_years) < report_year - 5:
        return None, f"max UW year {max(uw_years)} outside range for report year {report_year}"

    n_cols = len(uw_years)

    # Step 2: Parse development rows after the header
    # Each row should have a label + numeric values aligned with the year columns
    dev_period_patterns = [
        r"at\s+end", r"at\s+the\s+end", r"end\s+of\s+underwriting",
        r"year\s+later", r"years?\s+later",
        r"after\s+\w+\s+years?",
        r"\d+\s+months?\s+later",
        r"^\d+\s+months?\b",                    # "12 months", "24 months" (without "later")
        r"^(one|two|three|four|five|six|seven|eight|nine|ten)\b",
        r"^\d+\s+year",
        r"^year\s+\d+",                         # "Year 1", "Year 2", ... (Year of Account format)
    ]
    # Labels that signal the END of development rows (summary/total section)
    stop_labels = [
        "current estimate of cum",     # "Current estimate of cumulative claims incurred"
        "cumulative .* payment",        # "Cumulative gross claims payments to date"
        "cumulative claims paid",       # "Cumulative claims paid" (Year of Account format)
        "less gross claims paid",
        "less net claims paid",
        "less claims paid",
        "gross outstanding claims",
        "net outstanding claims",
        "outstanding claims reserve",   # "Outstanding claims reserve" (Year of Account format)
        "outstanding .* provision",     # but NOT "outstanding claims provision" in title
        "estimated total",             # "Estimated total losses" summary row
        "paid claims",                 # "Paid claims" section break
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
        # Extract numbers from this line, treating standalone dashes as zero
        # (accounting convention: dash = nil/zero)
        nums = re.findall(r'[\-]?[\d,]+\.?\d*|\([\d,]+\.?\d*\)', line)
        new_vals = _extract_numbers(nums)
        # If the line is just a dash (or dashes), treat each as zero
        if not new_vals:
            dash_count = len(re.findall(r'(?<!\d)[-\u2013\u2014](?!\d)', line.strip()))
            if dash_count > 0 and not re.search(r'\d', line):
                new_vals = [0.0] * dash_count
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
    if re.search(r"[£$]'?000", text_lower) or "'000" in text_lower:
        units = "thousands"

    # Detect type (gross vs net)
    tri_type = "gross" if "gross" in text_lower else "net"

    triangle = TriangleData(
        type=tri_type,
        currency=currency,
        units=units,
        underwriting_years=[int(y) for y in uw_years],
        development_rows=dev_rows,
    )

    details = (f"{tri_type} {len(uw_years)} UW years "
               f"({min(uw_years)}-{max(uw_years)}), "
               f"{len(dev_rows)} dev rows, {units}, {currency}")
    return triangle, details


def _extract_row_values(row, uw_col_indices, ghost_cols):
    """Extract values from a grid row, checking ghost columns when primary is empty.

    Args:
        row: grid row (list of cell strings)
        uw_col_indices: list of column indices for each UW year
        ghost_cols: dict {uw_year_index: ghost_col_index} for columns with
                    data split across primary and adjacent columns
    Returns:
        list of numeric values (or None) for each UW year
    """
    values = []
    for yi, col_idx in enumerate(uw_col_indices):
        val = None
        if col_idx < len(row):
            v = _clean_cell_triangle(row[col_idx])
            if isinstance(v, (int, float)):
                val = v
        # If primary column is empty and this UW year has a ghost column, try it
        if val is None and yi in ghost_cols:
            g_col = ghost_cols[yi]
            if g_col < len(row):
                v = _clean_cell_triangle(row[g_col])
                if isinstance(v, (int, float)):
                    val = v
        values.append(val)
    return values


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
    # Track cells that contain multiple years (e.g. "2022 2023" merged into
    # one Azure grid cell).  These need special handling during data extraction:
    # the cell's value applies to the FIRST year, and the next grid column
    # contains the SECOND year's value.
    _multi_year_cols = {}  # {col_idx: [year1, year2, ...]}
    for row_idx in range(min(3, len(grid))):
        for col_idx, val in enumerate(grid[row_idx]):
            # Match 4-digit years, allowing optional trailing footnote
            # markers (e.g. "20171" where "1" is a superscript reference).
            # Strip the footnote by capturing only the year digits.
            matches = re.findall(r'\b((?:19|20)\d{2})(?:\d(?!\d)|\b)', val)
            if not matches:
                continue
            if "prior" in val.lower() or "&" in val:
                continue
            years_in_cell = []
            for m in matches:
                year = int(m)
                if 1990 <= year <= 2030:
                    # Skip bare year labels in column 0 — these are row labels
                    # (e.g. UW year row "2011" in a transposed triangle, or
                    # report year "2021" as table title), not column headers
                    if col_idx == 0 and val.strip() == str(year):
                        continue
                    years_in_cell.append(year)
            if len(years_in_cell) > 1:
                # Multiple years merged into one cell — assign to consecutive
                # columns starting at col_idx.  The actual data for the 2nd+
                # year will be in the next grid column(s).
                _multi_year_cols[col_idx] = years_in_cell
                for offset, year in enumerate(years_in_cell):
                    if year not in uw_years:
                        uw_years.append(year)
                        uw_col_indices.append(col_idx + offset)
            else:
                for year in years_in_cell:
                    if year not in uw_years:
                        uw_years.append(year)
                        uw_col_indices.append(col_idx)

    if len(uw_years) < 1:
        # Try transposed format (Development Year 1,2,3... with UW years as rows)
        return _parse_transposed_triangle(grid, report_year)

    # Sort by year
    pairs = sorted(zip(uw_years, uw_col_indices))
    uw_years = [p[0] for p in pairs]
    uw_col_indices = [p[1] for p in pairs]

    # ── Ghost-column detection ───────────────────────────────────────
    # Azure sometimes inserts an extra empty column between two UW year
    # headers (e.g. "2015 $000", "", "2016 $000").  When that happens,
    # data for the first year may appear at EITHER the mapped col OR
    # col+1 (the ghost column), varying row by row.  We record which
    # UW years have a ghost column so that the data extraction loop can
    # check both columns per row and use whichever has data.
    _uw_col_set = set(uw_col_indices)
    _ghost_cols = {}  # {uw_year_index: ghost_col_index}
    for yi, col_idx in enumerate(uw_col_indices):
        ghost_col = col_idx + 1
        if ghost_col in _uw_col_set:
            continue  # adjacent column already belongs to another UW year
        # Check if any data rows have values at ghost_col
        has_ghost_data = False
        for row in grid:
            if len(row) <= ghost_col:
                continue
            v_ghost = _clean_cell_triangle(row[ghost_col]) if ghost_col < len(row) else None
            if isinstance(v_ghost, (int, float)):
                has_ghost_data = True
                break
        if has_ghost_data:
            # Verify the ghost column header is empty (confirming it's a phantom)
            ghost_header_empty = all(
                grid[r][ghost_col].strip() == "" if r < len(grid) and ghost_col < len(grid[r]) else True
                for r in range(min(3, len(grid)))
            )
            if ghost_header_empty:
                _ghost_cols[yi] = ghost_col
                logger.info(f"Ghost column detected: UW year {uw_years[yi]} has data at "
                           f"both col {col_idx} and col {ghost_col}")

    # Max UW year must be recent (within 5 years of report year) but need not
    # equal it — run-off syndicates stop writing new business before the report date.
    if max(uw_years) > report_year:
        return None, f"max UW year {max(uw_years)} > report year {report_year}"
    if max(uw_years) < report_year - 5:
        return None, f"max UW year {max(uw_years)} too old for report year {report_year}"

    if len(uw_years) < 3:
        # Check if any UW year is old enough to have usable PYD
        # (i.e., at least 2 years before the report year so there's a
        # previous diagonal to compare against).  Single-column triangles
        # with enough development rows ARE valid for PYD computation.
        usable = [y for y in uw_years if y <= report_year - 2]
        if not usable:
            return "new_syndicate", f"{len(uw_years)} UW year(s) ({min(uw_years)}-{max(uw_years)})"
        # Fall through to parse the triangle normally

    # Parse development rows — only keep rows that look like development periods
    dev_period_patterns = [
        r"at\s+end", r"at\s+the\s+end", r"end\s+of\s+underwriting",
        r"year\s+later", r"years?\s+later",
        r"^\d+\s+year", r"^(one|two|three|four|five|six|seven|eight|nine|ten)\b",
        r"after\s+\w+\s+years?",               # "After one year", "After two years"
        r"\d+\s+months?\s+later",               # "12 months later", "24 months later"
        r"^\d+\s+months?\b",                    # "12 months", "24 months" (without "later")
        r"estimate.*end\s+of\s+underwriting",   # "Estimate of cumulative...end of underwriting year"
        r"^year\s+\d+",                         # "Year 1", "Year 2", ... (Year of Account format)
    ]
    skip_labels = [
        "current estimate", "cumulative payment", "cumulative claim",
        "estimated total",
        "outstanding", "provision", "gross outstanding", "net outstanding",
    ]
    # Section headers that mark end of the incurred-claims triangle.
    # If we've already collected dev rows and hit one of these, stop.
    section_break_patterns = [
        "paid claims", "claims paid", "gross paid", "net paid",
        "less gross", "less net",  # "Less gross claims paid", "Less net claims paid"
        "cumulative claims paid", "cumulative payments",
        "cumulative gross payments", "cumulative net payments",
        "claims reserve", "gross claims reserve", "net claims reserve",
        "gross reserve", "net reserve",
        "current estimate",  # summary row signals end of dev rows
        "estimated total",   # "Estimated total losses" summary row
        "estimate of cumulative net",  # start of net section in combined gross+net tables
        "total ultimate",    # "Total Ultimate losses" summary row before paid/net section
        "less cumulative",   # "Less cumulative paid claims" — starts paid section
        "cumulative",        # bare "Cumulative" (Azure splits "Cumulative payments" across rows)
        "payment",           # bare "payments" row (continuation of split "Cumulative payments")
        "balance to pay",    # "Estimated balance to pay" section below triangle
    ]

    dev_rows = []
    collecting = False  # True once we've started finding dev rows
    # Track rows consumed as continuation of a split label (skip them in main loop)
    consumed_as_continuation = set()
    for row_i, row in enumerate(grid):
        if row_i in consumed_as_continuation:
            continue
        label = row[0].lower().strip() if row else ""
        if not label:
            continue
        # Check for section break (paid claims section, reserve summary, etc.)
        if collecting and any(s in label for s in section_break_patterns):
            break
        if any(s in label for s in skip_labels):
            continue
        # Check for "& prior" aggregate rows — skip them (not a dev period)
        if "prior" in label and ("&" in label or "and" in label):
            continue
        is_dev_row = any(re.search(p, label) for p in dev_period_patterns)
        if not is_dev_row:
            continue
        collecting = True

        values = _extract_row_values(row, uw_col_indices, _ghost_cols)

        # Handle split-label rows: Azure/OCR sometimes splits a multi-line
        # cell label across two or three grid rows (e.g. "At end of" /
        # "underwriting" / "year one" with values on the last row).  When
        # the matched dev-period row has all-empty values, scan up to 3
        # subsequent rows for continuation data.
        if all(v is None for v in values):
            for lookahead in range(1, 4):  # check next 1-3 rows
                if row_i + lookahead >= len(grid):
                    break
                next_row = grid[row_i + lookahead]
                next_label = next_row[0].lower().strip() if next_row else ""
                # Stop scanning if we hit a section break or skip label
                next_is_break = any(s in next_label for s in section_break_patterns)
                next_is_skip = any(s in next_label for s in skip_labels)
                if next_is_break or next_is_skip:
                    break
                next_values = _extract_row_values(next_row, uw_col_indices, _ghost_cols)
                if any(v is not None for v in next_values):
                    values = next_values
                    # Mark all intermediate rows as consumed
                    for skip_i in range(1, lookahead + 1):
                        consumed_as_continuation.add(row_i + skip_i)
                    break
                # If this row matches a dev pattern on its own but has no
                # data, it's a genuine new dev period — stop scanning.
                # (Rows with data were already handled above.)
                next_is_dev = any(re.search(p, next_label) for p in dev_period_patterns)
                if next_is_dev:
                    break

        dev_rows.append(values)

    # Strip trailing all-null rows (development periods with no data yet,
    # e.g. "After five years" when the triangle only covers 4 UW years)
    while dev_rows and all(v is None for v in dev_rows[-1]):
        dev_rows.pop()

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
    details = f"{len(uw_years)} UW years, {len(dev_rows)} dev rows"
    return tri, details


def _parse_transposed_triangle(grid: list[list[str]], report_year: int):
    """Parse a transposed triangle where dev periods are columns and UW years are rows.

    Format A: headers are "Development Year  1  2  3  4  5  6  Total"
    and rows are "2016  57,083  59,022  95,617  95,099  45,248  <blank>  45,248"

    Format B (headerless): Azure sometimes splits header from data, so the grid
    has no descriptive header — just a currency row ("$000") followed by UW year
    rows with numeric values forming the triangle.

    Returns (TriangleData, details_str) or (None, reason).
    """
    if len(grid) < 4 or len(grid[0]) < 3:
        return None, "too small for transposed triangle"

    # Detect transposed format: first header cell contains "Development Year"
    # or "Underlying Pure Year" (alt format with "X year(s) later" columns)
    # or "Year of account" (Lloyd's YOA format with "One year later" columns)
    # and subsequent cells are integers 1,2,3... or "Total" or "X year(s) later"
    header = grid[0]
    header0_lower = header[0].lower().strip()
    has_dev_year_header = "development year" in header0_lower
    has_pure_year_header = "underlying pure year" in header0_lower or "underlying" in header0_lower
    has_yoa_header = "year of account" in header0_lower

    dev_col_indices = []
    if has_dev_year_header:
        # Verify columns are dev period numbers (1, 2, 3, ...)
        for col_idx in range(1, len(header)):
            val = header[col_idx].strip()
            if val.isdigit() and 1 <= int(val) <= 20:
                dev_col_indices.append(col_idx)
            elif val.lower() == "total":
                break  # stop before Total column

        if len(dev_col_indices) < 2:
            return None, "not enough development period columns"
    elif has_pure_year_header or has_yoa_header:
        # Alt format: columns are "Incurred at end of underwriting year",
        # "1 year later", "2 years later", ..., "Cumulative Payments"
        # OR Lloyd's YOA format: "At the end of calendar year",
        # "One year later", ..., "Cumulative payments", "Estimated balance to pay"
        for col_idx in range(1, len(header)):
            val = header[col_idx].strip().lower()
            if ("incurred" in val or "end of underwriting" in val
                    or "end of calendar" in val or "at the end" in val
                    or "year later" in val or "years later" in val
                    or "months later" in val):
                dev_col_indices.append(col_idx)
            elif ("cumulative" in val or "total" in val
                      or "estimated" in val or "balance" in val):
                break  # stop before Cumulative Payments / Estimated balance columns

        if len(dev_col_indices) < 2:
            return None, "not enough development period columns (pure year/YOA format)"
    else:
        # Headerless format: check if rows have UW years as labels.
        # First count how many rows have a 4-digit year in column 0.
        year_row_count = 0
        for row in grid:
            if row and re.match(r'^(19|20)\d{2}$', row[0].strip()):
                year_row_count += 1
        if year_row_count < 3:
            return None, "not a transposed triangle (no 'Development Year' header and < 3 year rows)"
        # Use all columns except col 0 (year label) as dev period columns,
        # but exclude the last column if it looks like "Cumulative Payments"
        # (detected by checking if last col values are always <= the max of
        # other columns for each row — skip that heuristic, just include all).
        # We'll strip the last column later if it's a payments column.
        n_cols = len(grid[0])
        dev_col_indices = list(range(1, n_cols))

    # Find UW year rows — look for rows where col 0 is a 4-digit year
    uw_years = []
    uw_row_indices = []
    skip_labels = [
        "current estimate", "cumulative payment", "cumulative claim",
        "gross claims reserve", "net claims reserve", "gross unearned",
        "net unearned", "year of account", "underlying pure year",
        "underlying", "incurred at end",
    ]
    for row_idx in range(1, len(grid)):
        label = grid[row_idx][0].strip()
        label_lower = label.lower()
        # Skip currency/header rows and summary rows
        if not label or any(s in label_lower for s in skip_labels):
            continue
        m = re.match(r'^(19|20)\d{2}$', label)
        if m:
            year = int(label)
            if 1990 <= year <= 2030:
                uw_years.append(year)
                uw_row_indices.append(row_idx)

    if len(uw_years) < 1:
        return None, "no underwriting years found in row labels"

    # Validate year range
    if max(uw_years) > report_year:
        return None, f"max UW year {max(uw_years)} > report year {report_year}"
    if max(uw_years) < report_year - 5:
        return None, f"max UW year {max(uw_years)} too old for report year {report_year}"

    if len(uw_years) < 3:
        return "new_syndicate", f"{len(uw_years)} UW year(s) ({min(uw_years)}-{max(uw_years)})"

    # Extract values: each UW year row has values for dev periods 1..N
    # Transpose into standard format: dev_rows[d] = [val_for_year0, val_for_year1, ...]
    n_dev = len(dev_col_indices)
    n_years = len(uw_years)

    # Build a matrix: raw_data[year_idx][dev_idx]
    raw_data = []
    for row_idx in uw_row_indices:
        row = grid[row_idx]
        vals = []
        for col_idx in dev_col_indices:
            if col_idx < len(row):
                val = _clean_cell_triangle(row[col_idx])
                vals.append(val if isinstance(val, (int, float)) else None)
            else:
                vals.append(None)
        raw_data.append(vals)

    # In headerless mode, the last column may be "Cumulative Payments" — a
    # column where every UW year has a value (no Nones).  A proper triangle
    # column has decreasing non-null counts per UW year, so the last dev
    # column should have only 1 non-null value (the oldest year).  If the
    # last column is fully populated, strip it.
    if not has_dev_year_header and raw_data:
        last_col_vals = [row[-1] for row in raw_data if row]
        # Last column fully populated = likely cumulative payments, not dev period
        if all(v is not None for v in last_col_vals) and len(last_col_vals) >= 3:
            # Also check the second-to-last column has at least one None
            second_last = [row[-2] for row in raw_data if len(row) >= 2]
            if any(v is None for v in second_last):
                for row in raw_data:
                    row.pop()

    # Transpose: dev_rows[d][y] = raw_data[y][d]
    max_dev = max(len(vals) for vals in raw_data)
    dev_rows = []
    for d in range(max_dev):
        row = []
        for y_idx in range(n_years):
            if d < len(raw_data[y_idx]):
                row.append(raw_data[y_idx][d])
            else:
                row.append(None)
        dev_rows.append(row)

    # Trim trailing all-None rows
    while dev_rows and all(v is None for v in dev_rows[-1]):
        dev_rows.pop()

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
    details = f"{len(uw_years)} UW years, {len(dev_rows)} dev rows (transposed)"
    return tri, details


# ── Nutrient: parse LOB ──────────────────────────────────────────────────

# Standard Lloyd's regulatory LOB names
_LOB_KEYWORDS = [
    "accident and health", "motor", "marine aviation", "marine, aviation",
    "fire and other damage", "third party liability", "miscellaneous",
    "reinsurance", "energy", "casualty", "aviation", "property",
    "pecuniary", "credit", "suretyship", "specialty", "transport",
    "property catastrophe", "weather", "cyber", "liability",
]

_SECTION_HEADERS = {
    "direct insurance", "direct insurance:", "direct",
    "reinsurance acceptances", "reinsurance acceptances:",
}
_TOTAL_LABELS = {"total", "sub-total", "subtotal", "grand total", "direct insurance"}

# Row labels that should be skipped — not real LOBs.
# RITC (reinsurance to close) rows inflate the total and are not a line of business.
_SKIP_ROW_LABELS = {
    "movements in respect of ritc received",
    "movements in respect of ritc receivable",
    "reinsurance to close premium received",
    "reinsurance to close premium receivable",
    "reinsurance to close premium payable",
    "reinsurance to close",
    "ritc received",
    "ritc payable",
}


def _parse_nutrient_lob(grid: list[list[str]], report_year: int,
                        page_text: str = ""):
    """Parse a Nutrient table grid as a segmental analysis / LOB breakdown.

    Returns LOBData or None.
    ``page_text`` is the full text of the page containing this table,
    used to detect explicit LOB table signals (e.g. "segmental analysis",
    "class of business") that may appear above the table, not in the grid.
    """
    flat = _grid_text_lower(grid)
    combined = flat + " " + page_text.lower()

    # Must contain multiple LOB keywords — but lower the bar for tables
    # that are explicitly identified as segmental analysis or class-of-
    # business tables (monoline syndicates may have only 1-2 LOBs)
    lob_hits = sum(1 for kw in _LOB_KEYWORDS if kw in flat)
    is_explicit_lob_table = any(
        sig in combined for sig in ("segmental analysis", "class of business",
                                    "analysis of underwriting result")
    )
    min_lob_hits = 1 if is_explicit_lob_table else 3
    if lob_hits < min_lob_hits:
        return None

    # Reject tables that are not segmental analysis:
    # (a) Provisions movement tables with date/movement row labels
    # (b) Reinsurance-to-close (RITC) tables
    # (c) Members' balances / balance sheet tables
    _NON_LOB_TABLE_SIGNALS = [
        "at 1 january", "at 31 december", "at 1 jan", "at 31 dec",
        "exchange adjustment", "movement in provision",
        "movement in prior", "at start of", "at end of",
        "reinsurance to close", "members' balances",
        "payments of profit", "total comprehensive income",
        "deferred acquisition costs",
    ]
    non_lob_hits = sum(
        1 for sig in _NON_LOB_TABLE_SIGNALS if sig in flat
    )
    if non_lob_hits >= 2:
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

    # Track year sections — segmental analysis tables often have both
    # report year (2022) and prior year (2021) rows.  Only collect data
    # from the report year section.
    in_report_year_section = True  # default if no year row seen
    seen_any_year_row = False

    for row in grid[1:]:
        if not row or not row[0].strip():
            continue
        label = row[0].strip()
        label_lower = label.lower().rstrip(":")

        # Detect year section dividers (bare year in first column, rest empty)
        if re.match(r'^(19|20)\d{2}$', label):
            rest_empty = all(not c.strip() for c in row[1:])
            if rest_empty:
                seen_any_year_row = True
                in_report_year_section = (int(label) == report_year)
                continue

        if seen_any_year_row and not in_report_year_section:
            continue

        # Skip section headers
        if label_lower in _SECTION_HEADERS:
            continue

        # Skip RITC and other non-LOB rows
        if label_lower in _SKIP_ROW_LABELS:
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

    # Recalculate total from LOB entries — the "Total" row in the table may
    # include RITC or other skipped rows, making it larger than the sum of
    # the LOB entries we actually kept.
    lob_sum = sum(e["amount_raw"] for e in lob_entries)
    if total_gwp == 0 or total_gwp > lob_sum * 1.1:
        total_gwp = lob_sum

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


# ── Text-based LOB fallback ───────────────────────────────────────────────

# Canonical LOB patterns for text-based extraction (order matters — longer
# patterns first to avoid partial matches)
_TEXT_LOB_PATTERNS = [
    ("Accident and health", re.compile(r'accident\s+and\s+health', re.I)),
    ("Fire and other damage to property", re.compile(r'fire\s+and\s+other\s+damage\s+to\s+property', re.I)),
    ("Marine aviation and transport", re.compile(r'marine[\s,]+aviation', re.I)),
    ("Third party liability", re.compile(r'third\s+party\s+liability', re.I)),
    ("Pecuniary loss", re.compile(r'pecuniary\s+loss', re.I)),
    ("Motor", re.compile(r'\bmotor\b(?:\s+vehicle)?', re.I)),
    ("Credit and suretyship", re.compile(r'credit\s+and\s+suretyship', re.I)),
    ("Reinsurance", re.compile(r'\breinsurance\s+accept(?:ed|ances)', re.I)),
    ("Property", re.compile(r'\bproperty\b(?:\s+(?:direct|insurance|catastrophe))?', re.I)),
    ("Casualty", re.compile(r'\bcasualty\b', re.I)),
    ("Energy", re.compile(r'\benergy\b', re.I)),
    ("Miscellaneous", re.compile(r'\bmiscellaneous\b', re.I)),
]

# Numbers that follow a LOB label — may be parenthesised negatives
_NUM_RE = re.compile(r'[(\-]?\d[\d,]*(?:\.\d+)?[)]?')


def _parse_lob_from_text(text: str, report_year: int) -> Optional[LOBData]:
    """Parse LOB breakdown from raw page text when API table extraction fails.

    Targets the standard Lloyd's "Particulars of business written" /
    "Type of business" note, which lists LOB names followed by columns of
    numbers (GWP, GEP, claims incurred, expenses, RI balance, total).

    The first number after each LOB name is treated as GWP (Gross Premiums
    Written) and the third (if present) as claims incurred.

    Returns LOBData or None.
    """
    # Collapse whitespace for reliable multi-word matching
    norm = re.sub(r'\s+', ' ', text.replace('\u00a0', ' '))
    norm_lower = norm.lower()

    # Must have LOB signals
    lob_hits = sum(1 for _, pat in _TEXT_LOB_PATTERNS if pat.search(norm_lower))
    if lob_hits < 2:
        return None

    # Find the report-year section — look for the year in a header context
    # The table typically has "2015" on a line near "premiums written"
    # We want the section for report_year, not the comparative year
    year_str = str(report_year)
    sections = []
    # Split on year boundaries to isolate the report-year table from the
    # comparative table (e.g. 2015 section vs 2014 section)
    parts = re.split(r'(?=\b' + year_str + r'\b)', norm)
    for part in parts:
        if year_str in part[:40]:  # year near start of section
            sections.append(part)

    # If no year-specific section found, use the full text but only if
    # the report year appears somewhere
    if not sections:
        if year_str not in norm:
            return None
        sections = [norm]

    # Use the first (report-year) section
    section = sections[0]

    # Also try to cut off at the comparative year or "Geographical analysis"
    for stop_signal in [str(report_year - 1), "geographical analysis", "Geographical analysis"]:
        idx = section.find(stop_signal, 40)  # skip first 40 chars (header)
        if idx > 0:
            section = section[:idx]
            break

    # Detect currency
    currency = "GBP"
    if "$" in section or "usd" in section.lower():
        currency = "USD"
    elif "€" in section.lower() or "eur" in section.lower():
        currency = "EUR"

    # Extract LOB entries — track matched spans to avoid overlapping matches
    # (e.g. "Property" matching within "Fire and other damage to property")
    lob_entries = []
    claims_entries = []
    matched_spans = []  # (start, end) of already-matched LOB names

    for lob_name, pattern in _TEXT_LOB_PATTERNS:
        m = pattern.search(section)
        if not m:
            continue
        # Skip if this match overlaps with an already-matched (longer) pattern
        if any(m.start() < prev_end and m.end() > prev_start
               for prev_start, prev_end in matched_spans):
            continue
        matched_spans.append((m.start(), m.end()))
        # Get text after the LOB name match to find numbers
        after = section[m.end():]
        # Collect numbers — stop at the next LOB name or section header
        numbers = []
        pos = 0
        for nm in _NUM_RE.finditer(after):
            # Stop if we've gone past ~200 chars (into next LOB row)
            if nm.start() > 200:
                break
            # Stop if we hit another LOB name
            snippet_to_num = after[pos:nm.start()].lower()
            if any(p.search(snippet_to_num) for _, p in _TEXT_LOB_PATTERNS):
                break
            raw = nm.group().replace(',', '').replace('(', '-').replace(')', '')
            try:
                numbers.append(float(raw))
            except ValueError:
                continue
            pos = nm.end()

        if not numbers:
            continue

        gwp = abs(numbers[0])
        claims = numbers[2] if len(numbers) >= 3 else None

        if gwp > 0:
            lob_entries.append({"line_of_business": lob_name, "amount_raw": gwp})
        if claims is not None:
            claims_entries.append({"line_of_business": lob_name, "amount_raw": claims})

    if not lob_entries:
        return None

    # Auto-detect units from magnitude
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
        method="text_fallback",
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
    claims_outstanding_col = None
    if grid:
        for i, val in enumerate(grid[0]):
            h = val.lower()
            if "gross" in h:
                gross_col = i
            elif "reinsur" in h or "share" in h or "ceded" in h:
                ri_col = i
            elif "net" in h:
                net_col = i
            # Track "Claims outstanding" column separately — some tables
            # have "Provision for unearned premiums | Claims outstanding | Total"
            # layout where gross/RI/net are section headers (rows) rather than
            # column headers.  In this layout, "Claims outstanding" is where
            # the actual gross claims PYD lives.
            if "claims outstanding" in h or ("claims" in h and "outstanding" in h):
                claims_outstanding_col = i

    # Positional fallback
    if gross_col is None and len(grid[0]) >= 4:
        # If header has "Claims outstanding" as a column, use it for gross
        # instead of the default positional col 1 (which may be unearned premiums).
        if claims_outstanding_col is not None:
            gross_col = claims_outstanding_col
            # "Total" column (usually last) serves as net_col
            net_col = len(grid[0]) - 1 if len(grid[0]) > claims_outstanding_col + 1 else None
        else:
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


def _parse_balance_sheet_claims_outstanding(grid: list[list[str]], report_year: int) -> Optional[float]:
    """Extract gross claims outstanding from the balance sheet LIABILITIES section.

    Looks for "Claims outstanding" under "Technical provisions" in the liabilities
    section and returns the PRIOR YEAR comparative column value in millions.

    This is the primary deterministic source for opening_reserves_gbp_m, since the
    prior year balance sheet figure equals the opening position for the current year.

    Returns the opening gross claims outstanding in millions, or None.
    """
    flat = _grid_text_lower(grid)

    # Must be a balance sheet with technical provisions
    if "technical provision" not in flat:
        return None

    # Must have "claims outstanding" as a ROW label (not just a column header
    # in a provisions movement table)
    has_claims_row = False
    for row in grid:
        if row and "claims outstanding" in row[0].lower():
            has_claims_row = True
            break
    if not has_claims_row:
        return None

    # Skip assets-side tables (reinsurers' share)
    if "reinsurer" in flat:
        return None

    # Detect units from header rows
    # Common patterns: £'000, $'000, £000, $000, '000, 000s, thousands, £m, $m
    in_thousands = False
    in_millions = False
    for row in grid[:4]:
        row_text = " ".join(row).lower()
        if any(kw in row_text for kw in ("'000", "\u2019000", "000s", "thousand",
                                          "£000", "$000", "\u00a3000")):
            in_thousands = True
            break
        if any(kw in row_text for kw in ("£m", "$m", "million")):
            in_millions = True
            break

    # Identify the prior year column and notes column from header
    prior_year_col = None
    notes_col = None
    for row in grid[:4]:
        for i, val in enumerate(row):
            v = str(val).lower().strip()
            if v in ("notes", "note"):
                notes_col = i
            if str(report_year - 1) in v and prior_year_col is None:
                prior_year_col = i
        if prior_year_col is not None:
            break

    def _extract_prior_year_value(row: list[str]) -> Optional[float]:
        """Extract the prior year numeric value from a row."""
        if prior_year_col is not None and prior_year_col < len(row):
            val = _clean_cell(row[prior_year_col])
            if isinstance(val, (int, float)):
                return val
        # Fallback: collect all numeric values, skip notes column, take last
        numerics = []
        for i, cell in enumerate(row):
            if i == 0:
                continue  # label column
            if i == notes_col:
                continue
            val = _clean_cell(cell)
            if isinstance(val, (int, float)):
                numerics.append(val)
        # Prior year is the last numeric column in the row
        if len(numerics) >= 2:
            return numerics[-1]
        return None

    def _to_millions(val: float) -> float:
        """Convert raw value to millions based on detected units."""
        if in_thousands:
            return round(val / 1_000, 3)
        if in_millions:
            return round(val, 3)
        # No unit detected — infer from magnitude.  Claims outstanding values
        # >50,000 are almost certainly in thousands (no syndicate has >£50bn
        # reserves).  Values 50–50,000 are ambiguous but likely already in
        # millions for most syndicates.
        if abs(val) > 50_000:
            return round(val / 1_000, 3)
        return round(val, 3)

    # Walk through rows looking for "Claims outstanding" in the liabilities section
    for j, row in enumerate(grid):
        label = row[0].lower().strip() if row else ""
        if "claims outstanding" not in label:
            continue

        # Pattern A (181/186 syndicates): values directly on the row
        val = _extract_prior_year_value(row)
        if val is not None and val > 0:
            return _to_millions(val)

        # Pattern B (e.g. syndicate 4242): "Claims outstanding" is a sub-header,
        # next row has "Gross amount" with the values
        if j + 1 < len(grid):
            next_row = grid[j + 1]
            next_label = next_row[0].lower().strip() if next_row else ""
            if "gross" in next_label:
                val = _extract_prior_year_value(next_row)
                if val is not None and val > 0:
                    return _to_millions(val)

    return None


def _parse_opening_claims_outstanding(grid: list[list[str]], report_year: int) -> Optional[float]:
    """Extract opening gross claims outstanding from a provisions movement table.

    Looks for the "Balance at 1 January" row within a "Claims outstanding" section
    and returns the gross column value in millions.

    Returns the opening gross claims outstanding in millions, or None.
    """
    flat = _grid_text_lower(grid)
    if "claims outstanding" not in flat:
        return None
    if "balance" not in flat and "1 january" not in flat and "brought forward" not in flat:
        return None

    # Detect units from header rows (£'000, $'000, $000, £000, thousands, etc.)
    in_thousands = False
    for row in grid[:4]:
        row_text = " ".join(row).lower()
        if any(kw in row_text for kw in ("'000", "\u2019000", "000s", "thousand",
                                          "£000", "$000", "\u00a3000")):
            in_thousands = True
            break

    # Detect column layout from header rows — look for "Gross" column
    # Also detect the current year column (report_year values are in the
    # first set of columns, prior year in the second set for side-by-side tables)
    gross_col = None
    for row in grid[:3]:
        for i, val in enumerate(row):
            h = val.lower()
            if "gross" in h and "net" not in h:
                gross_col = i
                break
        if gross_col is not None:
            break

    # Positional fallback: first numeric column after label
    if gross_col is None:
        gross_col = 1

    # --- Pattern A: "Claims outstanding" is a ROW label (section header) ---
    # Find the claims outstanding section, then the "Balance at 1 January" row
    in_claims_section = False
    for row in grid:
        label = row[0].lower().strip() if row else ""

        # Detect section headers
        if "claims outstanding" in label and not any(
            kw in label for kw in ("unearned", "provision for unearned")
        ):
            in_claims_section = True
            continue

        # Exit claims outstanding section when we hit another section
        if in_claims_section and any(
            kw in label for kw in ("unearned premium", "deferred acquisition", "total")
        ):
            break

        # Look for opening balance row within claims outstanding section
        if in_claims_section and any(
            kw in label for kw in ("balance at 1 january", "brought forward", "at 1 january")
        ):
            if gross_col < len(row):
                val = _clean_cell(row[gross_col])
                if isinstance(val, (int, float)):
                    if in_thousands:
                        val = round(val / 1_000, 3)
                    elif abs(val) > 50_000:
                        # Magnitude fallback: no syndicate has >£50bn
                        # reserves, so values > 50,000 are in thousands
                        val = round(val / 1_000, 3)
                    return val

    # --- Pattern B: "Claims outstanding" is a COLUMN header ---
    # Some syndicates (e.g. 780) present provisions movement as a columnar
    # table where headers are:
    #   ['31 December YYYY', 'Provision for unearned premiums', 'Claims outstanding', 'Total']
    # and rows are:
    #   ['Gross', '', '', '']
    #   ['At 1 January YYYY', '109.3', '348.5', '457.8']
    claims_col = None
    for row in grid[:3]:
        for i, val in enumerate(row):
            if "claims outstanding" in val.lower() and "unearned" not in val.lower():
                claims_col = i
                break
        if claims_col is not None:
            break

    if claims_col is not None:
        # Find "At 1 January" or "Brought forward" in the Gross section
        in_gross = False
        for row in grid:
            label = row[0].lower().strip() if row else ""
            if "gross" == label or label.startswith("gross"):
                in_gross = True
                continue
            # Stop at reinsurers' share or net section
            if in_gross and any(
                kw in label for kw in ("reinsurer", "net", "at 31 december")
            ):
                break
            if in_gross and any(
                kw in label for kw in ("at 1 january", "balance at 1 january",
                                       "brought forward")
            ):
                if claims_col < len(row):
                    val = _clean_cell(row[claims_col])
                    if isinstance(val, (int, float)):
                        if in_thousands:
                            val = round(val / 1_000, 3)
                        elif abs(val) > 50_000:
                            val = round(val / 1_000, 3)
                        return val

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
    page_matches, page_texts, scan_method, rotated_pages = _find_relevant_pages(pdf_path)

    doc = fitz.open(pdf_path)
    total_pages = len(doc)
    doc.close()

    result.relevant_pages = sorted(page_matches.keys())
    result.rotated_pages = rotated_pages

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
    _extract_pages_to_pdf(pdf_path, relevant_pages, slim_pdf, rotated_pages)
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
    opening_claims = None

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
                lob = _parse_nutrient_lob(grid, report_year,
                                          page_text=page_texts.get(page_num, ""))
                if lob and len(lob.gross_premium_mix) > best_lob_count:
                    best_lob = lob
                    best_lob_count = len(lob.gross_premium_mix)

            # Try provisions (on provisions-tagged pages)
            if "provisions" in cats and best_provisions is None:
                prov = _parse_nutrient_provisions(grid, report_year)
                if prov:
                    best_provisions = prov

            # Extract opening claims outstanding
            if opening_claims is None and any(
                t in cats for t in ("provisions", "balance_sheet")
            ):
                oc = _parse_opening_claims_outstanding(grid, report_year)
                if oc is not None:
                    opening_claims = oc

            # Extract opening claims from balance sheet liabilities section.
            # Also try pl_account tables: scanned PDFs sometimes misclassify
            # the balance sheet page as pl_account.
            if opening_claims is None and any(
                t in cats for t in ("balance_sheet", "pl_account")
            ):
                oc = _parse_balance_sheet_claims_outstanding(grid, report_year)
                if oc is not None:
                    opening_claims = oc

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

    # Text-based LOB fallback
    if best_lob is None:
        for page_num in sorted(page_matches):
            if "premium_mix" not in page_matches[page_num]:
                continue
            text = page_texts.get(page_num, "")
            if not text:
                continue
            lob = _parse_lob_from_text(text, report_year)
            if lob and len(lob.gross_premium_mix) > best_lob_count:
                lob.method = "nutrient_text_fallback"
                best_lob = lob
                best_lob_count = len(lob.gross_premium_mix)
                print(f"  [Nutrient] Text fallback LOB: {len(lob.gross_premium_mix)} classes, "
                      f"GWP={lob.gross_premiums_written_gbp_m}m")

    result.triangle = best_triangle
    result.triangle_details = best_triangle_details or result.triangle_details
    result.lob = best_lob
    result.provisions = best_provisions
    # Attach opening claims outstanding to provisions data
    if opening_claims is not None:
        if result.provisions is None:
            result.provisions = ProvisionsData()
        result.provisions.opening_gross_claims_outstanding = opening_claims
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
    page_matches, page_texts, scan_method, rotated_pages = _find_relevant_pages(pdf_path)

    relevant_pages = sorted(page_matches.keys())
    result.relevant_pages = relevant_pages
    result.rotated_pages = rotated_pages

    if not page_matches:
        print(f"  [Adobe] No relevant pages found")
        result.elapsed_s = time.time() - t0
        return result
    print(f"  [Adobe] {len(relevant_pages)} relevant pages found via {scan_method}")

    # Step 2: Create slim PDF with only relevant pages
    slim_pdf = cache_dir / f"{pdf_path.stem}_slim.pdf"

    # Check if Adobe already processed this (cached output exists)
    report_out = cache_dir / f"{pdf_path.stem}_slim"
    if not (report_out / "structuredData.json").exists():
        _extract_pages_to_pdf(pdf_path, relevant_pages, slim_pdf, rotated_pages)
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
    from azure.core.pipeline.policies import RetryPolicy

    # Configure with short retry backoff so Ctrl+C isn't blocked for minutes
    # by the SDK's default retry sleep.
    retry_policy = RetryPolicy(
        retry_total=3,
        retry_backoff_factor=1,
        retry_backoff_max=10,
    )
    client = DocumentIntelligenceClient(
        endpoint=endpoint,
        credential=AzureKeyCredential(api_key),
        retry_policy=retry_policy,
    )

    with open(pdf_path, "rb") as f:
        poller = client.begin_analyze_document(
            "prebuilt-layout",
            body=f,
            content_type="application/pdf",
        )
    # Poll manually so Ctrl+C can interrupt during the wait.
    # Timeout after 120 seconds to avoid indefinite hangs.
    deadline = time.time() + 120
    while not poller.done():
        if time.time() > deadline:
            raise TimeoutError("Azure Document Intelligence API timed out after 120s")
        time.sleep(1)
    return poller.result()


def _classify_table_content(grid: list[list[str]]) -> set[str]:
    """Classify a table by its cell content (keywords and structure)."""
    flat = _grid_text_lower(grid)
    cats = set()

    # ── Claims triangle detection ───────────────────────────────────────
    # Detect from: (a) year count + dev periods, (b) title keywords, (c) row labels
    # Use a non-capturing group so findall returns full 4-digit years, not just
    # the prefix ('19' or '20').  A capturing group like (19|20) causes findall
    # to return only the captured fragment, so len(uw_years) is always 0 for
    # data-only tables whose years appear as e.g. "2011", "2012", ...
    uw_years = re.findall(r'\b(?:19|20)\d{2}\b', flat)
    dev_patterns = [
        "at end", "year later", "years later", "one year", "two year",
        "after one", "after two", "after three", "after four", "after five",
        "months later", "month later",
        "12 months", "24 months", "36 months", "48 months",
        "60 months", "72 months", "84 months",
    ]
    # Title/header keywords that strongly indicate a triangle
    triangle_title_kw = [
        "claims development", "cumulative claims incurred",
        "cumulative gross claims", "cumulative net claims",
        "development table", "development triangle",
        "outstanding claims provision",
        # "Underlying Pure Year" is used by some syndicates (e.g. 1919) as the
        # row-label header in a transposed triangle instead of "Year of Account"
        "underlying pure year",
    ]
    has_dev_periods = any(p in flat for p in dev_patterns)
    # Edge case: syndicate 3902 uses bare "1 year", "2 years", "3 years" as
    # dev-period labels (no "later" suffix) with "Gross claims" / "Net claims"
    # as the table heading instead of a standard triangle title.
    if not has_dev_periods and ("gross claims" in flat or "net claims" in flat):
        if re.search(r'\b[1-9]\s+years?\b', flat):
            has_dev_periods = True
    has_triangle_title = any(kw in flat for kw in triangle_title_kw)

    # Detect transposed format: "Development Year 1 2 3 ..." with "Year of Account"
    # Also handle "Underlying Pure Year" as an equivalent row-label header
    has_transposed = (
        ("development year" in flat and "year of account" in flat)
        or ("underlying pure year" in flat and ("year later" in flat or "years later" in flat))
    )

    if len(uw_years) >= 3 and (has_dev_periods or has_triangle_title or has_transposed):
        cats.add("claims_triangle")
    elif has_transposed and len(uw_years) >= 1:
        cats.add("claims_triangle")
    elif has_triangle_title and len(uw_years) >= 1:
        # Title is strong evidence even with fewer detected years
        cats.add("claims_triangle")
    elif has_dev_periods and has_triangle_title:
        # Header-only split table: dev period labels present but UW years in a
        # separate sibling table (Azure sometimes splits a single triangle into
        # a header grid and a data grid).  Tag it so the data grid gets tried.
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


def _extract_azure(pdf_path: Path, report_year: int, cache_dir: Path,
                    azure_paid: bool = False) -> ExtractionResult:
    """Extract tables using Azure AI Document Intelligence.

    Uses the same targeted-page approach: PyMuPDF/Tesseract identifies
    relevant pages, then sends them in batches to Azure (F0 tier = 2 pages
    per request; paid S0 tier sends all relevant pages in one request).
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
    page_matches, page_texts, scan_method, rotated_pages = _find_relevant_pages(pdf_path)

    doc = fitz.open(pdf_path)
    total_pages = len(doc)
    doc.close()

    result.relevant_pages = sorted(page_matches.keys())
    result.rotated_pages = rotated_pages

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
    priority_order = ["claims_triangle", "premium_mix", "provisions", "pl_account", "balance_sheet"]
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
    batch_size = len(sorted_pages) if azure_paid else 2  # paid S0: all at once; F0: 2 pages
    batches = [sorted_pages[i:i+batch_size] for i in range(0, len(sorted_pages), batch_size)]

    # Check for cached Azure results — cache key includes relevant pages
    # and batch mode so cache invalidates if either changes
    pages_hash = "_".join(str(p) for p in sorted(relevant_pages))
    batch_mode = "paid" if azure_paid else "free"
    cache_file = cache_dir / f"{pdf_path.stem}_azure.json"
    all_grids = []  # (grid, orig_page, categories)

    cache_valid = False
    if cache_file.exists():
        with open(cache_file) as f:
            cached = json.load(f)
        # Validate cache: must match code version, page set, and batch mode
        cached_ver = cached.get("_cache_version") if isinstance(cached, dict) else None
        cached_pages = cached.get("_pages_hash") if isinstance(cached, dict) else None
        cached_batch = cached.get("_batch_mode") if isinstance(cached, dict) else None
        if not isinstance(cached, dict) or cached_ver != _CACHE_VERSION:
            cache_file.unlink()
            reason = "legacy format" if not isinstance(cached, dict) else "code changed"
            print(f"  [Azure] Cache invalidated ({reason}) — re-extracting")
        elif cached_pages != pages_hash:
            cache_file.unlink()
            print(f"  [Azure] Cache invalidated (page set changed) -- re-extracting")
        elif cached_batch is not None and cached_batch != batch_mode:
            cache_file.unlink()
            print(f"  [Azure] Cache invalidated (batch mode changed: {cached_batch} -> {batch_mode}) -- re-extracting")
        else:
            cache_valid = True
            print(f"  [Azure] Using cached result")
            for entry in cached.get("tables", []):
                grid = entry["grid"]
                orig_page = entry["orig_page"]
                cats = set(entry["categories"])
                # Re-apply content classification to pick up new rules
                # (e.g. bare "N year(s)" dev-period labels for syndicate 3902)
                content_cats = _classify_table_content(grid)
                cats = cats | content_cats
                if "_not_triangle" in content_cats:
                    cats.discard("claims_triangle")
                    cats.discard("_not_triangle")
                all_grids.append((grid, orig_page, cats))

    if not cache_valid:
        # Clean up any leftover slim PDFs from previous interrupted runs
        for stale in cache_dir.glob(f"{pdf_path.stem}_slim*.pdf"):
            try:
                stale.unlink()
            except OSError:
                pass

        # Send pages to Azure API in batches of 2
        for batch_idx, batch_pages in enumerate(batches):
            batch_cats = set()
            for p in batch_pages:
                batch_cats.update(page_matches[p])
            cat_str = ", ".join(sorted(batch_cats))

            slim_pdf = cache_dir / f"{pdf_path.stem}_slim_b{batch_idx}.pdf"
            _extract_pages_to_pdf(pdf_path, batch_pages, slim_pdf, rotated_pages)
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

            # Clean up temp PDF; on Windows the Azure SDK may still hold a
            # handle briefly, so retry once after a short delay.
            try:
                slim_pdf.unlink(missing_ok=True)
            except PermissionError:
                time.sleep(0.5)
                try:
                    slim_pdf.unlink(missing_ok=True)
                except PermissionError:
                    pass  # will be cleaned up on next run or manually

        # Cache extracted grids for reuse (versioned)
        cache_data = {
            "_cache_version": _CACHE_VERSION,
            "_pages_hash": pages_hash,
            "_batch_mode": batch_mode,
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
    best_triangle_score = -1
    best_lob = None
    best_lob_count = 0
    best_provisions = None
    opening_claims = None

    def _triangle_completeness(tri: TriangleData) -> int:
        """Count non-null values in the triangle — higher is better."""
        count = 0
        for row in tri.development_rows:
            for v in row:
                if v is not None:
                    count += 1
        return count

    for grid, orig_page, cats in all_grids:
        if "claims_triangle" in cats:
            tri_result, details = _parse_nutrient_triangle(grid, report_year)
            if tri_result == "new_syndicate":
                result.first_year_syndicate = True
                result.triangle_details = details
            elif isinstance(tri_result, TriangleData):
                n_years = len(tri_result.underwriting_years)
                completeness = _triangle_completeness(tri_result)
                # Score: prefer gross, then more UW years, then more complete
                score = (
                    (1000 if tri_result.type == "gross" else 0)
                    + n_years * 10
                    + completeness
                )
                if score > best_triangle_score:
                    best_triangle = tri_result
                    best_triangle_details = details
                    best_triangle_score = score

        if "premium_mix" in cats and "provisions" not in cats:
            pt = page_texts.get(orig_page, "")
            lob = _parse_nutrient_lob(grid, report_year, page_text=pt)
            if lob:
                # Score: strongly prefer tables with explicit segmental analysis
                # signals (header with "premiums written") over incidental matches.
                header_text = " ".join(grid[0]).lower() if grid else ""
                has_gwp_header = "premium" in header_text and ("written" in header_text or "earned" in header_text)
                # Prefer tables with year-section dividers (statutory accounts
                # format with "2022" / "2021" rows) — these are the canonical
                # segmental analysis tables and correctly scope to report year.
                has_year_sections = any(
                    re.match(r'^(19|20)\d{2}$', row[0].strip())
                    and all(not c.strip() for c in row[1:])
                    for row in grid[1:] if row and row[0].strip()
                )
                lob_score = (
                    len(lob.gross_premium_mix)
                    + (100 if has_gwp_header else 0)
                    + (200 if has_year_sections else 0)
                )
                if lob_score > best_lob_count:
                    best_lob = lob
                    best_lob.method = "azure"
                    best_lob_count = lob_score

        if "provisions" in cats and best_provisions is None:
            prov = _parse_nutrient_provisions(grid, report_year)
            if prov:
                best_provisions = prov

        # Extract opening claims outstanding from provisions/balance_sheet tables
        if opening_claims is None and any(
            t in cats for t in ("provisions", "balance_sheet")
        ):
            oc = _parse_opening_claims_outstanding(grid, report_year)
            if oc is not None:
                opening_claims = oc

        # Extract opening claims from balance sheet liabilities section.
        # Also try pl_account tables: scanned PDFs sometimes misclassify
        # the balance sheet page as pl_account.
        if opening_claims is None and any(
            t in cats for t in ("balance_sheet", "pl_account")
        ):
            oc = _parse_balance_sheet_claims_outstanding(grid, report_year)
            if oc is not None:
                opening_claims = oc

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

    # Step 5: Text-based LOB fallback — if Azure didn't find a LOB table,
    # try parsing from the raw page text on premium_mix pages
    if best_lob is None:
        for page_num in sorted(page_matches):
            if "premium_mix" not in page_matches[page_num]:
                continue
            text = page_texts.get(page_num, "")
            if not text:
                continue
            lob = _parse_lob_from_text(text, report_year)
            if lob and len(lob.gross_premium_mix) > best_lob_count:
                lob.method = "azure_text_fallback"
                best_lob = lob
                best_lob_count = len(lob.gross_premium_mix)
                print(f"  [Azure] Text fallback LOB: {len(lob.gross_premium_mix)} classes, "
                      f"GWP={lob.gross_premiums_written_gbp_m}m")

    result.triangle = best_triangle
    result.triangle_details = best_triangle_details or result.triangle_details
    result.lob = best_lob
    result.provisions = best_provisions
    # Attach opening claims outstanding to provisions data
    if opening_claims is not None:
        if result.provisions is None:
            result.provisions = ProvisionsData()
        result.provisions.opening_gross_claims_outstanding = opening_claims
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
