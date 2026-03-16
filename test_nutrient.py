"""
Test: Nutrient.io PDF API with targeted page extraction.

Strategy:
1. PyMuPDF scans all pages for keywords (native PDFs)
2. If scanned PDF detected, fall back to Tesseract OCR per page
3. Extract only relevant pages into a slim PDF
4. Send the slim PDF to Nutrient for high-quality table extraction
5. Analyse and display results

Usage:
    python test_nutrient.py [pdf_path]

Requires:
    NUTRIENT_API_KEY in .env
    Tesseract OCR + Poppler (for scanned PDFs only)
"""

import os
import json
import re
import sys
import time
from pathlib import Path

import fitz  # PyMuPDF
from dotenv import load_dotenv
import requests

load_dotenv()

# Lazy imports for OCR (only needed for scanned PDFs)
pdf2image = None
pytesseract = None


def ensure_ocr_imports():
    """Import OCR libraries on demand."""
    global pdf2image, pytesseract
    if pdf2image is None:
        import pdf2image as _pdf2image
        import pytesseract as _pytesseract
        pdf2image = _pdf2image
        pytesseract = _pytesseract
        # Set Tesseract path if not in PATH
        tesseract_path = Path("C:/Program Files/Tesseract-OCR/tesseract.exe")
        if tesseract_path.exists():
            pytesseract.pytesseract.tesseract_cmd = str(tesseract_path)


# ── Page identification keywords ──────────────────────────────────────────

PAGE_KEYWORDS = {
    "claims_triangle": [
        "claims development",
        "development table",
        "gross ultimate claims",
        "underwriting year",
    ],
    "provisions": [
        "provision for claims",
        "claims outstanding",
        "prior year",
        "movement in prior",
        "gross provision",
    ],
    "pl_account": [
        "technical account",
        "profit and loss",
        "gross premiums written",
        "earned premiums",
        "claims incurred",
    ],
    "premium_mix": [
        "accident and health",
        "marine aviation",
        "fire and other damage",
        "third party liability",
        "reinsurance",
        "miscellaneous",
    ],
    "reserve_commentary": [
        "prior year development",
        "reserve release",
        "reserve strength",
        "favourable development",
        "adverse development",
        "catastroph",
        "IBNR",
        "large loss",
    ],
}

MIN_TEXT_THRESHOLD = 200  # chars per page to consider native text


def classify_page(text: str) -> set[str]:
    """Return set of matching categories for a page's text."""
    text_lower = text.lower()
    categories = set()
    for category, keywords in PAGE_KEYWORDS.items():
        hits = sum(1 for kw in keywords if kw.lower() in text_lower)
        if hits >= 2:
            categories.add(category)
    return categories


def is_scanned_pdf(pdf_path: Path, sample_pages: int = 5) -> bool:
    """Check if PDF is scanned (image-based) by testing text extraction."""
    doc = fitz.open(pdf_path)
    total_chars = 0
    pages_checked = min(sample_pages, len(doc))
    for i in range(1, pages_checked):  # skip page 0 (often a disclaimer)
        total_chars += len(doc[i].get_text().strip())
    doc.close()
    return total_chars < MIN_TEXT_THRESHOLD * (pages_checked - 1)


def find_relevant_pages_native(pdf_path: Path) -> tuple[dict, dict]:
    """Scan pages with PyMuPDF text extraction (fast, for native PDFs)."""
    doc = fitz.open(pdf_path)
    page_matches = {}
    page_texts = {}

    for page_num in range(len(doc)):
        text = doc[page_num].get_text()
        page_texts[page_num] = text
        categories = classify_page(text)
        if categories:
            page_matches[page_num] = categories

    doc.close()
    return page_matches, page_texts


def find_relevant_pages_ocr(pdf_path: Path) -> tuple[dict, dict]:
    """Scan pages with Tesseract OCR (slower, for scanned PDFs)."""
    ensure_ocr_imports()

    page_matches = {}
    page_texts = {}

    print("  Converting PDF pages to images...")
    images = pdf2image.convert_from_path(str(pdf_path), dpi=200)
    print(f"  Running OCR on {len(images)} pages...")

    for page_num, image in enumerate(images):
        text = pytesseract.image_to_string(image)
        page_texts[page_num] = text
        categories = classify_page(text)
        if categories:
            page_matches[page_num] = categories

        # Progress indicator every 10 pages
        if (page_num + 1) % 10 == 0:
            print(f"    ...OCR'd {page_num + 1}/{len(images)} pages")

    return page_matches, page_texts


def extract_pages_to_pdf(pdf_path: Path, page_numbers: list[int], output_path: Path):
    """Create a new PDF containing only the specified pages."""
    src = fitz.open(pdf_path)
    dst = fitz.open()
    for page_num in sorted(page_numbers):
        dst.insert_pdf(src, from_page=page_num, to_page=page_num)
    dst.save(str(output_path))
    dst.close()
    src.close()


# ── Nutrient API ──────────────────────────────────────────────────────────

def extract_nutrient(pdf_path: Path, api_key: str) -> dict:
    """Extract tables from a PDF using Nutrient.io API."""
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


# ── Table rendering ───────────────────────────────────────────────────────

def cells_to_grid(cells: list) -> list[list[str]]:
    """Convert Nutrient cells array to a 2D grid of strings."""
    if not cells:
        return []
    max_row = max(c["rowIndex"] for c in cells) + 1
    max_col = max(c["columnIndex"] for c in cells) + 1
    grid = [["" for _ in range(max_col)] for _ in range(max_row)]
    for cell in cells:
        text = cell.get("text", "").replace("\r\n", " | ").strip()
        grid[cell["rowIndex"]][cell["columnIndex"]] = text
    return grid


def print_table(grid: list[list[str]], max_col_width: int = 40):
    """Pretty-print a 2D grid."""
    if not grid:
        print("    (empty)")
        return
    n_cols = max(len(row) for row in grid)
    widths = [0] * n_cols
    for row in grid:
        for i, val in enumerate(row):
            widths[i] = max(widths[i], min(len(val), max_col_width))
    for row in grid:
        cells_str = []
        for i, val in enumerate(row):
            w = widths[i] if i < len(widths) else max_col_width
            cells_str.append(val[:w].ljust(w))
        print("    " + " | ".join(cells_str))


# ── Main ──────────────────────────────────────────────────────────────────

def main():
    api_key = os.getenv("NUTRIENT_API_KEY")
    if not api_key:
        print("Missing NUTRIENT_API_KEY in .env")
        raise SystemExit(1)

    if len(sys.argv) > 1:
        pdf_path = Path(sys.argv[1])
    else:
        pdf_path = Path("syndicate_reports/pdfs/syndicate_2987_2018.pdf")

    if not pdf_path.exists():
        print(f"PDF not found: {pdf_path}")
        raise SystemExit(1)

    output_dir = Path("pdf_extraction/nutrient_output")
    output_dir.mkdir(parents=True, exist_ok=True)

    # ── Step 1: Detect if scanned, then find relevant pages ──
    print(f"Scanning {pdf_path.name}...")
    scanned = is_scanned_pdf(pdf_path)

    if scanned:
        print(f"  Scanned PDF detected - using Tesseract OCR")
        t0 = time.time()
        page_matches, page_texts = find_relevant_pages_ocr(pdf_path)
        scan_time = time.time() - t0
        extraction_method = "tesseract"
    else:
        print(f"  Native text PDF - using PyMuPDF")
        t0 = time.time()
        page_matches, page_texts = find_relevant_pages_native(pdf_path)
        scan_time = time.time() - t0
        extraction_method = "pymupdf"

    doc = fitz.open(pdf_path)
    total_pages = len(doc)
    doc.close()

    print(f"  {total_pages} pages scanned via {extraction_method} in {scan_time:.1f}s")
    print(f"  {len(page_matches)} pages matched keywords:")
    for page_num in sorted(page_matches):
        cats = ", ".join(sorted(page_matches[page_num]))
        preview = page_texts[page_num].replace("\n", " ").strip()[:80]
        print(f"    Page {page_num + 1}: [{cats}] {preview}...")

    if not page_matches:
        print("  No relevant pages found!")
        raise SystemExit(1)

    # ── Step 2: Extract matching pages into slim PDF ──
    relevant_pages = sorted(page_matches.keys())
    slim_pdf = output_dir / f"{pdf_path.stem}_slim.pdf"
    extract_pages_to_pdf(pdf_path, relevant_pages, slim_pdf)
    slim_size = slim_pdf.stat().st_size / 1024
    orig_size = pdf_path.stat().st_size / 1024
    print(f"\n  Slim PDF: {len(relevant_pages)} pages, {slim_size:.0f} KB "
          f"(vs {orig_size:.0f} KB original, {slim_size/orig_size*100:.0f}% of size)")

    # ── Step 3: Send slim PDF to Nutrient ──
    cache_file = output_dir / f"{pdf_path.stem}_nutrient.json"
    if cache_file.exists():
        print(f"\n  Using cached Nutrient result from {cache_file}")
        with open(cache_file) as f:
            nutrient_result = json.load(f)
    else:
        print(f"\n  Sending slim PDF to Nutrient API...")
        t1 = time.time()
        nutrient_result = extract_nutrient(slim_pdf, api_key)
        api_time = time.time() - t1
        with open(cache_file, "w") as f:
            json.dump(nutrient_result, f, indent=2)
        print(f"  Nutrient API completed in {api_time:.1f}s")

    # Clean up slim PDF
    slim_pdf.unlink(missing_ok=True)

    # ── Step 4: Display Nutrient tables ──
    page_index_to_orig = {i: p + 1 for i, p in enumerate(relevant_pages)}

    pages = nutrient_result.get("pages", [])
    print(f"\n{'='*70}")
    print(f"NUTRIENT TABLES (from {len(pages)} extracted pages)")
    print(f"{'='*70}")

    for slim_idx, page in enumerate(pages):
        orig_page = page_index_to_orig.get(slim_idx, "?")
        cats = ", ".join(sorted(page_matches.get(relevant_pages[slim_idx], set())))
        tables = page.get("tables", [])

        if not tables:
            continue

        print(f"\n  Original Page {orig_page} [{cats}]: {len(tables)} table(s)")

        for j, table in enumerate(tables):
            cells = table.get("cells", [])
            grid = cells_to_grid(cells)
            conf = table.get("confidence", "?")
            n_rows = len(grid)
            n_cols = max((len(r) for r in grid), default=0)
            print(f"\n    Table {j+1} ({n_rows}x{n_cols}, confidence={conf}%)")
            print_table(grid)

    # ── Step 5: Show text for commentary pages ──
    print(f"\n{'='*70}")
    print(f"RESERVE COMMENTARY (from {extraction_method} text)")
    print(f"{'='*70}")

    for page_num in sorted(page_matches):
        cats = page_matches[page_num]
        if "reserve_commentary" in cats or "provisions" in cats:
            text = page_texts[page_num].strip()
            if len(text) > 50:
                print(f"\n  Page {page_num + 1} [{', '.join(sorted(cats))}]:")
                for para in text.split("\n\n"):
                    para_lower = para.lower()
                    if any(kw in para_lower for kw in [
                        "prior year", "reserve", "provision", "development",
                        "release", "strengthen", "catastroph", "ibnr",
                        "adverse", "favourable", "large loss",
                    ]):
                        print(f"    {para.strip()[:300]}")
                        print()


if __name__ == "__main__":
    main()
