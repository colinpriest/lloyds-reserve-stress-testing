"""Test: Azure AI Document Intelligence for Lloyd's syndicate table extraction.

Strategy:
1. PyMuPDF scans all pages for keywords (native PDFs)
2. If scanned PDF detected, fall back to Tesseract OCR per page
3. Extract only relevant pages into a slim PDF
4. Send the slim PDF to Azure Document Intelligence (prebuilt-layout)
5. Parse and display results (triangle, LOB, provisions)

Usage:
    python test_azure.py [pdf_path]

Requires:
    DOCUMENTINTELLIGENCE_ENDPOINT and DOCUMENTINTELLIGENCE_API_KEY in .env
"""

import os
import re
import json
import sys
import time
from pathlib import Path

import fitz  # PyMuPDF
from dotenv import load_dotenv
from azure.core.credentials import AzureKeyCredential
from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.ai.documentintelligence.models import DocumentContentFormat

load_dotenv()

# Lazy imports for OCR
pdf2image = None
pytesseract = None


def ensure_ocr_imports():
    global pdf2image, pytesseract
    if pdf2image is None:
        import pdf2image as _pdf2image
        import pytesseract as _pytesseract
        pdf2image = _pdf2image
        pytesseract = _pytesseract
        tesseract_path = Path("C:/Program Files/Tesseract-OCR/tesseract.exe")
        if tesseract_path.exists():
            pytesseract.pytesseract.tesseract_cmd = str(tesseract_path)


# -- Page identification keywords (same as Nutrient approach) ---------------

PAGE_KEYWORDS = {
    "claims_triangle": [
        "claims development", "development table",
        "gross ultimate claims", "underwriting year",
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

MIN_TEXT_THRESHOLD = 200


def classify_page(text: str) -> set[str]:
    text_lower = text.lower()
    categories = set()
    for category, keywords in PAGE_KEYWORDS.items():
        hits = sum(1 for kw in keywords if kw.lower() in text_lower)
        if hits >= 2:
            categories.add(category)
    return categories


def is_scanned_pdf(pdf_path: Path, sample_pages: int = 5) -> bool:
    doc = fitz.open(pdf_path)
    total_chars = 0
    pages_checked = min(sample_pages, len(doc))
    for i in range(1, pages_checked):
        total_chars += len(doc[i].get_text().strip())
    doc.close()
    return total_chars < MIN_TEXT_THRESHOLD * (pages_checked - 1)


def find_relevant_pages_native(pdf_path: Path) -> tuple[dict, dict]:
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
        if (page_num + 1) % 10 == 0:
            print(f"    ...OCR'd {page_num + 1}/{len(images)} pages")
    return page_matches, page_texts


def extract_pages_to_pdf(pdf_path: Path, page_numbers: list[int], output_path: Path):
    src = fitz.open(pdf_path)
    dst = fitz.open()
    for page_num in sorted(page_numbers):
        dst.insert_pdf(src, from_page=page_num, to_page=page_num)
    dst.save(str(output_path))
    dst.close()
    src.close()


# -- Azure Document Intelligence -------------------------------------------

def analyze_with_azure(pdf_path: Path, endpoint: str, api_key: str) -> dict:
    """Send PDF to Azure Document Intelligence prebuilt-layout model."""
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
    result = poller.result()
    return result


def azure_table_to_grid(table) -> list[list[str]]:
    """Convert Azure DocumentTable to a 2D grid."""
    grid = [["" for _ in range(table.column_count)] for _ in range(table.row_count)]
    for cell in table.cells:
        grid[cell.row_index][cell.column_index] = cell.content.strip()
    return grid


def get_table_page_nums(table) -> list[int]:
    """Get 1-indexed page numbers where this table appears."""
    if not table.bounding_regions:
        return []
    return sorted({r.page_number for r in table.bounding_regions})


# -- Table classification ---------------------------------------------------

def classify_table_by_content(grid: list[list[str]]) -> set[str]:
    """Classify a table by its content (keywords in cells)."""
    flat = " ".join(" ".join(row) for row in grid).lower()
    cats = set()

    # Claims triangle: has UW years + development periods
    uw_years = re.findall(r'\b(19|20)\d{2}\b', flat)
    dev_patterns = ["at end", "year later", "years later", "one year", "two year"]
    if len(uw_years) >= 3 and any(p in flat for p in dev_patterns):
        cats.add("claims_triangle")

    # LOB / premium mix
    lob_kws = ["accident and health", "marine aviation", "marine, aviation",
                "fire and other damage", "third party liability",
                "miscellaneous", "reinsurance"]
    lob_hits = sum(1 for kw in lob_kws if kw in flat)
    if lob_hits >= 3:
        cats.add("premium_mix")

    # Provisions
    if "prior" in flat and ("claim" in flat or "provision" in flat):
        if any(kw in flat for kw in ["gross", "net", "reinsur"]):
            cats.add("provisions")

    return cats


# -- Parsing (shared with Nutrient approach) ---------------------------------

def clean_cell(text: str):
    if not text or not text.strip():
        return None
    s = text.strip().replace(",", "").replace(" ", "")
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


def parse_triangle(grid: list[list[str]], report_year: int):
    """Parse a claims development triangle from a grid."""
    if len(grid) < 4 or len(grid[0]) < 3:
        return None, "too small"

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
        return None, "no UW years"

    pairs = sorted(zip(uw_years, uw_col_indices))
    uw_years = [p[0] for p in pairs]
    uw_col_indices = [p[1] for p in pairs]

    if max(uw_years) != report_year:
        return None, f"max UW year {max(uw_years)} != report year {report_year}"

    if len(uw_years) < 3:
        return "new_syndicate", f"{len(uw_years)} UW year(s)"

    dev_period_patterns = [
        r"at\s+end", r"year\s+later", r"years?\s+later",
        r"^\d+\s+year", r"^(one|two|three|four|five|six|seven|eight|nine|ten)\b",
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
                val = clean_cell(row[col_idx])
                values.append(val if isinstance(val, (int, float)) else None)
            else:
                values.append(None)
        dev_rows.append(values)

    if len(dev_rows) < 2:
        return None, f"only {len(dev_rows)} dev rows"

    flat = " ".join(" ".join(row) for row in grid).lower()
    currency = "GBP" if ("gbp" in flat or chr(163) in flat or "£" in flat) else "USD"
    if "eur" in flat or chr(8364) in flat:
        currency = "EUR"

    units = "thousands" if ("'000" in flat or re.search(r"[$£]'?000", flat)) else "millions"

    tri_type = "net" if ("net" in flat and "gross" not in flat) else "gross"

    return {
        "type": tri_type,
        "currency": currency,
        "units": units,
        "underwriting_years": uw_years,
        "development_rows": dev_rows,
    }, f"{len(uw_years)} UW years, {len(dev_rows)} dev periods"


def parse_lob(grid: list[list[str]], report_year: int):
    """Parse LOB / segmental analysis table."""
    flat = " ".join(" ".join(row) for row in grid).lower()
    lob_kws = ["accident and health", "motor", "marine aviation", "marine, aviation",
                "fire and other damage", "third party liability", "miscellaneous",
                "reinsurance", "energy", "casualty", "property", "pecuniary"]
    lob_hits = sum(1 for kw in lob_kws if kw in flat)
    if lob_hits < 3:
        return None

    # Find GWP column
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
                gwp_col = i

    if gwp_col is None and len(grid[0]) >= 3:
        gwp_col = 1
        if len(grid[0]) >= 4:
            claims_col = 3

    if gwp_col is None:
        return None

    section_headers = {"direct insurance", "direct insurance:", "direct",
                       "reinsurance acceptances", "reinsurance acceptances:"}
    total_labels = {"total", "sub-total", "subtotal", "grand total", "direct insurance"}

    lob_entries = []
    claims_entries = []
    total_gwp = 0.0

    for row in grid[1:]:
        if not row or not row[0].strip():
            continue
        label = row[0].strip()
        label_lower = label.lower().rstrip(":")

        if label_lower in section_headers:
            continue

        is_total = label_lower in total_labels
        if is_total:
            if gwp_col < len(row):
                val = clean_cell(row[gwp_col])
                if isinstance(val, (int, float)):
                    total_gwp = abs(val)
            continue

        gwp_val = None
        if gwp_col < len(row):
            val = clean_cell(row[gwp_col])
            if isinstance(val, (int, float)):
                gwp_val = abs(val)

        claims_val = None
        if claims_col is not None and claims_col < len(row):
            val = clean_cell(row[claims_col])
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

    return {
        "gross_premium_mix": lob_entries,
        "gross_premiums_written_gbp_m": total_gwp_m,
        "claims_incurred_by_lob": claims_entries if claims_entries else None,
        "method": "azure",
    }


def parse_provisions(grid: list[list[str]], report_year: int):
    """Parse provisions movement table."""
    flat = " ".join(" ".join(row) for row in grid).lower()
    if "prior" not in flat:
        return None

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

    if gross_col is None and len(grid[0]) >= 4:
        gross_col, ri_col, net_col = 1, 2, 3

    for row in grid:
        label = row[0].lower() if row else ""
        if "prior" in label and ("claim" in label or "underwriting" in label or "year" in label):
            result = {}
            has_data = False
            for key, col in [
                ("gross_prior_year_claims", gross_col),
                ("ri_share_prior_year", ri_col),
                ("net_prior_year_claims", net_col),
            ]:
                if col is not None and col < len(row):
                    val = clean_cell(row[col])
                    if isinstance(val, (int, float)):
                        if abs(val) > 10_000:
                            val = round(val / 1_000, 1)
                        result[key] = val
                        has_data = True
            if has_data:
                return result

    return None


# -- Pretty printing ---------------------------------------------------------

def print_grid(grid: list[list[str]], max_col_width: int = 30, indent: int = 4):
    if not grid:
        print(" " * indent + "(empty)")
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
        print(" " * indent + " | ".join(cells_str))


# -- Main --------------------------------------------------------------------

def main():
    endpoint = os.getenv("DOCUMENTINTELLIGENCE_ENDPOINT")
    api_key = os.getenv("DOCUMENTINTELLIGENCE_API_KEY")
    if not endpoint or not api_key or api_key == "PASTE_YOUR_KEY_HERE":
        print("Missing DOCUMENTINTELLIGENCE_ENDPOINT or DOCUMENTINTELLIGENCE_API_KEY in .env")
        raise SystemExit(1)

    if len(sys.argv) > 1:
        pdf_path = Path(sys.argv[1])
    else:
        pdf_path = Path("syndicate_reports/pdfs/syndicate_2987_2018.pdf")

    if not pdf_path.exists():
        print(f"PDF not found: {pdf_path}")
        raise SystemExit(1)

    # Parse report year from filename (last 4-digit number, e.g. syndicate_2987_2016 -> 2016)
    year_matches = re.findall(r'(\d{4})', pdf_path.stem)
    report_year = int(year_matches[-1]) if year_matches else 2018

    output_dir = Path("pdf_extraction/azure_output")
    output_dir.mkdir(parents=True, exist_ok=True)

    # -- Step 1: Detect scanned vs native, find relevant pages --
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

    # -- Step 2: Send pages to Azure in batches of 2 (F0 tier limit) --
    # Prioritize: claims_triangle > premium_mix > provisions > pl_account
    relevant_pages = sorted(page_matches.keys())

    # Group pages by priority
    priority_order = ["claims_triangle", "premium_mix", "provisions", "pl_account"]
    page_priority = {}
    for page_num in relevant_pages:
        cats = page_matches[page_num]
        best_priority = len(priority_order)
        for cat in cats:
            if cat in priority_order:
                best_priority = min(best_priority, priority_order.index(cat))
        page_priority[page_num] = best_priority

    # Sort pages by priority, then send in batches of 2
    sorted_pages = sorted(relevant_pages, key=lambda p: page_priority[p])
    batch_size = 2  # Azure F0 tier limit
    batches = [sorted_pages[i:i+batch_size] for i in range(0, len(sorted_pages), batch_size)]

    all_tables = []  # (table_object, orig_page_num, categories)
    api_time = 0.0

    for batch_idx, batch_pages in enumerate(batches):
        batch_cats = set()
        for p in batch_pages:
            batch_cats.update(page_matches[p])
        cat_str = ", ".join(sorted(batch_cats))

        slim_pdf = output_dir / f"{pdf_path.stem}_slim_batch{batch_idx}.pdf"
        extract_pages_to_pdf(pdf_path, batch_pages, slim_pdf)
        slim_size = slim_pdf.stat().st_size / 1024
        orig_pages_str = ", ".join(str(p+1) for p in batch_pages)
        print(f"\n  Batch {batch_idx+1}/{len(batches)}: pages {orig_pages_str} [{cat_str}] ({slim_size:.0f} KB)")

        print(f"    Sending to Azure...")
        t1 = time.time()
        try:
            azure_result = analyze_with_azure(slim_pdf, endpoint, api_key)
            batch_time = time.time() - t1
            api_time += batch_time

            n_tables = len(azure_result.tables) if azure_result.tables else 0
            n_pages_extracted = len(azure_result.pages) if azure_result.pages else 0
            content_len = len(azure_result.content) if azure_result.content else 0
            print(f"    Azure: {n_tables} tables, {n_pages_extracted} pages, "
                  f"{content_len} chars in {batch_time:.1f}s")

            # Save markdown for this batch
            if azure_result.content:
                md_file = output_dir / f"{pdf_path.stem}_batch{batch_idx}_markdown.md"
                with open(md_file, "w", encoding="utf-8") as f:
                    f.write(azure_result.content)

            # Collect tables with their original page mappings
            if azure_result.tables:
                for table in azure_result.tables:
                    # Map slim page back to original
                    table_pages = get_table_page_nums(table)
                    for tp in table_pages:
                        slim_idx = tp - 1  # 1-indexed to 0-indexed
                        if slim_idx < len(batch_pages):
                            orig_page = batch_pages[slim_idx]
                            cats = page_matches.get(orig_page, set())
                            all_tables.append((table, orig_page, cats))
                            break
                    else:
                        # Fallback: assign to first page of batch
                        orig_page = batch_pages[0]
                        cats = page_matches.get(orig_page, set())
                        all_tables.append((table, orig_page, cats))

        except Exception as e:
            batch_time = time.time() - t1
            api_time += batch_time
            print(f"    FAILED: {e}")

        slim_pdf.unlink(missing_ok=True)

    # -- Step 3: Display and parse tables --
    print(f"\n{'='*70}")
    print(f"AZURE TABLES (found {len(all_tables)} tables across {len(batches)} batches)")
    print(f"{'='*70}")

    best_triangle = None
    best_triangle_details = None
    best_lob = None
    best_lob_count = 0
    best_provisions = None

    for i, (table, orig_page, cats) in enumerate(all_tables):
        grid = azure_table_to_grid(table)
        table_cats = classify_table_by_content(grid)
        all_cats = cats | table_cats

        n_rows = len(grid)
        n_cols = max((len(r) for r in grid), default=0)
        cat_str = ", ".join(sorted(all_cats)) if all_cats else "unclassified"
        print(f"\n  Table {i+1} ({n_rows}x{n_cols}) on orig page {orig_page+1} [{cat_str}]")

        # Only print tables with recognized categories
        if all_cats:
            print_grid(grid)

        # Try parsing
        if "claims_triangle" in all_cats and best_triangle is None:
            tri, details = parse_triangle(grid, report_year)
            if tri == "new_syndicate":
                print(f"    -> NEW SYNDICATE: {details}")
            elif isinstance(tri, dict):
                best_triangle = tri
                best_triangle_details = details
                print(f"    -> TRIANGLE: {details}")

        if "premium_mix" in all_cats:
            lob = parse_lob(grid, report_year)
            if lob and len(lob["gross_premium_mix"]) > best_lob_count:
                best_lob = lob
                best_lob_count = len(lob["gross_premium_mix"])
                print(f"    -> LOB: {len(lob['gross_premium_mix'])} classes, "
                      f"GWP={lob['gross_premiums_written_gbp_m']}m")

        if "provisions" in all_cats and best_provisions is None:
            prov = parse_provisions(grid, report_year)
            if prov:
                best_provisions = prov
                g = prov.get("gross_prior_year_claims")
                print(f"    -> PROVISIONS: gross PY claims = {g}")

    # -- Step 5: Summary --
    print(f"\n{'='*70}")
    print(f"EXTRACTION SUMMARY")
    print(f"{'='*70}")
    print(f"  Report: {pdf_path.name} (year {report_year})")
    print(f"  Scan method: {extraction_method}")
    print(f"  Relevant pages: {len(relevant_pages)} of {total_pages}")
    print(f"  Azure batches: {len(batches)} (2 pages each, F0 tier)")
    print(f"  Azure tables found: {len(all_tables)}")
    print(f"  Scan time: {scan_time:.1f}s, API time: {api_time:.1f}s")
    print()

    if best_triangle:
        print(f"  TRIANGLE: {best_triangle_details}")
        print(f"    Type: {best_triangle['type']}, Currency: {best_triangle['currency']}, "
              f"Units: {best_triangle['units']}")
        print(f"    UW years: {best_triangle['underwriting_years']}")
        print(f"    Dev rows: {len(best_triangle['development_rows'])}")
        for j, row in enumerate(best_triangle['development_rows']):
            print(f"      Row {j}: {row}")
    else:
        print("  TRIANGLE: not found")

    print()
    if best_lob:
        print(f"  LOB: {len(best_lob['gross_premium_mix'])} classes, "
              f"GWP={best_lob['gross_premiums_written_gbp_m']}m")
        for entry in best_lob["gross_premium_mix"]:
            print(f"    {entry['line_of_business']}: "
                  f"{entry['amount_gbp_m']}m ({entry['percentage_of_total']}%)")
    else:
        print("  LOB: not found")

    print()
    if best_provisions:
        print(f"  PROVISIONS: {best_provisions}")
    else:
        print("  PROVISIONS: not found")


if __name__ == "__main__":
    main()
