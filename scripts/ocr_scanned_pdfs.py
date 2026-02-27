#!/usr/bin/env python3
"""
OCR Scanned PDFs
================
Processes scanned PDFs that couldn't be extracted with normal text extraction.
Saves extracted text to a cache file for reuse by the quality classifier.
"""

import os
import json
import logging
from pathlib import Path
from datetime import datetime

import fitz  # PyMuPDF

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# OCR setup
try:
    import pytesseract
    from pdf2image import convert_from_path
    HAS_OCR = True

    # Auto-detect Tesseract in conda environment
    conda_prefix = os.environ.get('CONDA_PREFIX', '')
    if conda_prefix:
        tesseract_path = os.path.join(conda_prefix, 'Library', 'bin', 'tesseract.exe')
        tessdata_path = os.path.join(conda_prefix, 'share', 'tessdata')
        if os.path.exists(tesseract_path):
            pytesseract.pytesseract.tesseract_cmd = tesseract_path
            if os.path.exists(tessdata_path):
                os.environ['TESSDATA_PREFIX'] = tessdata_path
            logger.info(f"Using Tesseract from: {tesseract_path}")
except ImportError:
    HAS_OCR = False
    logger.error("OCR not available - install pytesseract and pdf2image")


def identify_scanned_pdfs(pdf_dir: str, threshold: int = 500) -> list:
    """Identify PDFs that need OCR (less than threshold chars extracted)."""
    pdf_dir = Path(pdf_dir)
    scanned = []

    files = list(pdf_dir.glob("*.pdf"))
    logger.info(f"Checking {len(files)} PDFs...")

    for pdf_path in files:
        try:
            doc = fitz.open(str(pdf_path))
            text = ""
            for page in doc:
                text += page.get_text()
            doc.close()

            if len(text.strip()) < threshold:
                scanned.append(pdf_path.name)
        except Exception as e:
            logger.warning(f"Error checking {pdf_path.name}: {e}")
            scanned.append(pdf_path.name)  # Include errors in OCR list

    return scanned


def ocr_pdf(pdf_path: str, dpi: int = 150) -> str:
    """Run OCR on a PDF and return extracted text."""
    if not HAS_OCR:
        raise RuntimeError("OCR not available")

    try:
        # Convert PDF to images
        images = convert_from_path(pdf_path, dpi=dpi)

        text = ""
        for i, image in enumerate(images):
            page_text = pytesseract.image_to_string(image, lang='eng')
            text += f"\n--- Page {i+1} ---\n"
            text += page_text

            if (i + 1) % 10 == 0:
                logger.debug(f"  OCR progress: {i+1}/{len(images)} pages")

        return text

    except Exception as e:
        logger.error(f"OCR failed for {pdf_path}: {e}")
        return ""


def process_scanned_pdfs(pdf_dir: str, output_file: str = "ocr_cache.json",
                         dpi: int = 150, resume: bool = True):
    """
    Process all scanned PDFs with OCR and save results to cache.

    Args:
        pdf_dir: Directory containing PDFs
        output_file: JSON file to save OCR results
        dpi: Resolution for PDF to image conversion (lower = faster)
        resume: If True, skip files already in cache
    """
    if not HAS_OCR:
        logger.error("Cannot run OCR - pytesseract or pdf2image not installed")
        return

    pdf_dir = Path(pdf_dir)
    output_path = pdf_dir.parent / output_file

    # Load existing cache if resuming
    cache = {}
    if resume and output_path.exists():
        with open(output_path, 'r') as f:
            cache = json.load(f)
        logger.info(f"Loaded {len(cache)} entries from existing cache")

    # Identify scanned PDFs
    scanned = identify_scanned_pdfs(str(pdf_dir))
    logger.info(f"Found {len(scanned)} scanned PDFs needing OCR")

    # Filter out already processed
    if resume:
        to_process = [f for f in scanned if f not in cache]
        logger.info(f"Skipping {len(scanned) - len(to_process)} already processed")
    else:
        to_process = scanned

    logger.info(f"Processing {len(to_process)} PDFs with OCR (DPI={dpi})")
    logger.info("Estimated time: ~1-2 minutes per PDF")

    start_time = datetime.now()

    for i, filename in enumerate(to_process):
        pdf_path = pdf_dir / filename
        logger.info(f"[{i+1}/{len(to_process)}] Processing {filename}...")

        try:
            text = ocr_pdf(str(pdf_path), dpi=dpi)

            if text:
                cache[filename] = {
                    'text': text,
                    'char_count': len(text),
                    'processed_at': datetime.now().isoformat(),
                    'dpi': dpi
                }
                logger.info(f"  Extracted {len(text)} chars")
            else:
                cache[filename] = {
                    'text': '',
                    'char_count': 0,
                    'error': 'OCR returned empty',
                    'processed_at': datetime.now().isoformat()
                }
                logger.warning(f"  OCR returned empty text")

            # Save after each file (in case of interruption)
            with open(output_path, 'w') as f:
                json.dump(cache, f)

        except Exception as e:
            cache[filename] = {
                'text': '',
                'char_count': 0,
                'error': str(e),
                'processed_at': datetime.now().isoformat()
            }
            logger.error(f"  Error: {e}")

        # Progress estimate
        elapsed = (datetime.now() - start_time).total_seconds()
        avg_time = elapsed / (i + 1)
        remaining = avg_time * (len(to_process) - i - 1)
        logger.info(f"  Avg: {avg_time:.1f}s/file, Est. remaining: {remaining/60:.1f} min")

    # Final save
    with open(output_path, 'w') as f:
        json.dump(cache, f)

    elapsed = (datetime.now() - start_time).total_seconds()
    logger.info(f"\nCompleted! Total time: {elapsed/60:.1f} minutes")
    logger.info(f"Cache saved to: {output_path}")

    # Summary
    successful = sum(1 for v in cache.values() if v['char_count'] > 0)
    logger.info(f"Successfully OCR'd: {successful}/{len(cache)}")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="OCR scanned PDFs")
    parser.add_argument('--pdf-dir', default='lloyds_data/pdfs',
                        help='Directory containing PDF files')
    parser.add_argument('--output', default='ocr_cache.json',
                        help='Output cache file name')
    parser.add_argument('--dpi', type=int, default=150,
                        help='OCR resolution (lower=faster, default 150)')
    parser.add_argument('--no-resume', action='store_true',
                        help='Start fresh, ignore existing cache')
    parser.add_argument('--list-only', action='store_true',
                        help='Only list scanned PDFs, do not process')

    args = parser.parse_args()

    if args.list_only:
        scanned = identify_scanned_pdfs(args.pdf_dir)
        print(f"\nFound {len(scanned)} scanned PDFs:")
        for f in scanned:
            print(f"  {f}")
    else:
        process_scanned_pdfs(
            args.pdf_dir,
            args.output,
            dpi=args.dpi,
            resume=not args.no_resume
        )


if __name__ == "__main__":
    main()
