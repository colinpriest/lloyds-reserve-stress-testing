"""Scan syndicate annual reports for RITC (reinsurance to close) occurrence.

For each syndicate-year report, determine whether an RITC transaction occurred
in the reporting year (typically acceptance of another syndicate's or year of
account's liabilities, which distorts prior year development), and record the
section/note heading and page the evidence came from.

Every syndicate's accounting-policy note describes RITC generically; that
boilerplate is NOT evidence of an occurrence. Occurrence requires transaction
language (premium payable/receivable, portfolio accepted/assumed, named
counterparty syndicate) — see STRONG_PATTERNS.

Output: pdf_extraction/ritc_scan.json keyed "{syndicate}_{year}":
    {
      "detection": "successful" | "failed",
      "ritc_occurred": true | false,       # only when detection successful
      "confidence": "strong" | "weak",
      "evidence": "<text snippet>",
      "section": "<note/section heading>",
      "page": <int>,
      "failure_reason": "..."              # only when detection failed
    }

Usage:
    python scripts/ritc_scanner.py                 # scan all reports, resumable
    python scripts/ritc_scanner.py --rescan        # re-scan everything
    python scripts/ritc_scanner.py --single 1176_2022
"""

import argparse
import json
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import fitz  # PyMuPDF

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PDF_DIR = PROJECT_ROOT / "syndicate_reports" / "pdfs"
OCR_CACHE_DIR = PROJECT_ROOT / "pdf_extraction" / "ocr_page_cache"
OUTPUT_PATH = PROJECT_ROOT / "pdf_extraction" / "ritc_scan.json"
LOG_PATH = PROJECT_ROOT / "pdf_extraction" / "ritc_scan.log"

MIN_DOC_CHARS = 500  # below this the PDF is treated as scanned/no text

# Transaction language: strong evidence an RITC occurred this year.
# Classes control how hits are interpreted:
#   premium_flow  - RITC premium line items: external only when found in the
#                   whole-syndicate annual accounts (not the closed-YOA
#                   statements), or when another syndicate is named
#   acceptance    - portfolio acceptance/assumption wording: same rule
#   counterparty  - names a syndicate: external only if it is NOT this one
#   closure       - own year-of-account closure wording: routine unless
#                   another syndicate is named
STRONG_PATTERNS = [
    # premium flows
    ("premium_flow", r"reinsurance to close premium (?:payable|receivable|paid|received)"),
    ("premium_flow", r"premium (?:payable|receivable|paid|received) (?:on|in respect of|for) the reinsurance to close"),
    ("premium_flow", r"RITC premium"),
    # portfolio acceptance / assumption
    ("acceptance", r"accepted the reinsurance to close"),
    ("acceptance", r"(?:accepted|assumed|acquired) (?:the )?(?:liabilities|reserves|loss reserves|a portfolio)[^.]{0,120}?(?:by way of|through|under|via) (?:a )?reinsurance to close"),
    ("acceptance", r"by way of (?:a )?reinsurance to close[^.]{0,120}?(?:accepted|assumed|acquired|transferred)"),
    # named counterparty
    ("counterparty", r"reinsurance to close (?:of|into|from|with) syndicate\s+\d+"),
    ("counterparty", r"RITC (?:of|into|from|with) syndicate\s+\d+"),
    # closure of a year of account
    ("closure", r"(?:20\d\d|19\d\d)(?: and prior)? year(?:s)? of account (?:was|were|has been|have been) (?:closed|reinsured to close)"),
    ("closure", r"closed by reinsurance to close"),
]

# Weak signals: RITC mentioned with amounts/movement context, but wording
# doesn't match a strong pattern. Flagged for review.
WEAK_PATTERNS = [
    r"reinsurance to close[^.]{0,150}?[£$€]\s?[\d,]+",
    r"[£$€]\s?[\d,]+[^.]{0,150}?reinsurance to close",
    r"\bRITC\b[^.]{0,100}?[\d,]{4,}",
]

# Boilerplate context: mentions inside accounting-policy definitions.
BOILERPLATE_HINTS = [
    "accounting policy", "accounting policies", "basis of preparation",
    "is a contract", "represents a contract", "premium payable to close an underwriting year",
    "the amount charged as", "estimation techniques", "critical accounting",
]

logger = logging.getLogger(__name__)


def setup_logging() -> None:
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    fh = logging.FileHandler(LOG_PATH, mode='a', encoding='utf-8')
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S'))
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))
    root.addHandler(fh)
    root.addHandler(ch)


def load_page_texts(report_path: Path) -> Optional[List[str]]:
    """Extract per-page text. Uses the OCR page cache when the PDF has no
    text layer and cached OCR results exist. Returns None if no usable text."""
    if report_path.suffix.lower() in ('.html', '.htm'):
        from bs4 import BeautifulSoup
        with open(report_path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
        # iXBRL reports are XHTML with an XML declaration — use the XML
        # parser for those; plain HTML otherwise
        parser = 'lxml-xml' if content.lstrip().startswith('<?xml') else 'lxml'
        soup = BeautifulSoup(content, parser)
        for tag in soup(['script', 'style']):
            tag.decompose()
        text = soup.get_text(separator='\n', strip=True)
        return [text] if len(text) >= MIN_DOC_CHARS else None

    doc = fitz.open(report_path)
    try:
        pages = [page.get_text() for page in doc]
    finally:
        doc.close()

    if sum(len(p) for p in pages) >= MIN_DOC_CHARS:
        return pages

    # Try OCR page cache (populated by the extraction pipeline):
    # one JSON per report, a list of {"page": <1-based int>, "text": str}
    cache_file = OCR_CACHE_DIR / f"{report_path.stem}.json"
    if cache_file.exists():
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                entries = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"OCR cache unreadable for {report_path.name}: {e}")
            entries = []
        page_map: Dict[int, str] = {}
        for e in entries:
            if isinstance(e, dict) and isinstance(e.get('page'), int):
                page_map[e['page']] = e.get('text') or ''
        if page_map:
            n = max(page_map)
            ocr_pages = [page_map.get(i, '') for i in range(1, n + 1)]
            if sum(len(p) for p in ocr_pages) >= MIN_DOC_CHARS:
                return ocr_pages
    return None


_DANGLING_ENDINGS = (
    'the', 'a', 'an', 'of', 'for', 'and', 'or', 'to', 'in', 'on', 'by',
    'with', 'from', 'as', 'at', 'is', 'are', 'was', 'were', 'its',
)


def _looks_like_heading(line: str) -> bool:
    """Heuristic: is this line a standalone note/section heading rather than
    a fragment of wrapped body text?"""
    # Explicit note / numbered headings always qualify
    if re.match(r'^(note\s+\d+\b|\d{1,2}[\.\)]\s+[A-Z])', line, re.I):
        return True
    if len(line) > 70:
        return False
    words = line.split()
    if not words or len(words) > 8:
        return False
    # Wrapped body text usually ends mid-phrase
    if words[-1].lower().rstrip(':,') in _DANGLING_ENDINGS:
        return False
    if line.endswith((',', ';', '-')):
        return False
    # All-caps titles qualify
    if line.upper() == line and any(c.isalpha() for c in line):
        return True
    # Title-ish: starts capitalised, majority of significant words capitalised
    if not line[0].isupper():
        return False
    caps = sum(1 for w in words if w[0].isupper())
    return caps / len(words) >= 0.5


def find_section_heading(page_text: str, match_pos: int) -> Optional[str]:
    """Find the nearest note/section heading above a match position."""
    before = page_text[:match_pos]
    lines = [ln.strip() for ln in before.split('\n')]
    for line in reversed(lines):
        if not line:
            continue
        # Numeric-only or page-number-ish lines are not headings
        if re.fullmatch(r'[\d,.\s()%£$€-]+', line):
            continue
        low = line.lower()
        # Skip obvious running headers/footers
        if low.startswith(('syndicate ', 'annual report', 'annual accounts',
                           'report and accounts', 'year ended',
                           'notes to the', 'for the year ended')):
            continue
        if _looks_like_heading(line):
            return line
    return None


def is_boilerplate_context(page_text: str, match_pos: int) -> bool:
    """Check whether a match sits inside accounting-policy boilerplate."""
    lo = max(0, match_pos - 1500)
    context = page_text[lo:match_pos + 500].lower()
    return any(h in context for h in BOILERPLATE_HINTS)


def scan_report(report_path: Path) -> dict:
    pages = load_page_texts(report_path)
    if pages is None:
        return {
            'detection': 'failed',
            'failure_reason': 'no extractable text (likely scanned PDF without OCR cache)',
        }

    own_syndicate = None
    m_own = re.match(r'syndicate_(\d+)_', report_path.name)
    if m_own:
        own_syndicate = m_own.group(1)

    # Combined reports append the underwriting-year (closed YOA) accounts at
    # the end, where RITC between the syndicate's own years is routine.
    # Locate the start of that section: "36 months ended" is the closed-YOA
    # statement marker; the section headings are also distinctive.
    first_uw_page = None
    for page_no, text in enumerate(pages, start=1):
        if re.search(r'underwriting year (?:distribution )?accounts'
                     r'|36 months ended'
                     r'|closed year of account', text, re.I):
            first_uw_page = page_no
            break

    strong_hits: List[Tuple[int, str, str, Optional[str]]] = []
    weak_hits: List[Tuple[int, str, str, Optional[str]]] = []
    routine_hits = 0
    any_mention = False

    for page_no, text in enumerate(pages, start=1):
        if not re.search(r'reinsurance to close|\bRITC\b', text, re.I):
            continue
        any_mention = True

        is_uw_year_page = (
            (first_uw_page is not None and page_no >= first_uw_page)
            or len(re.findall(r'year of account', text, re.I)) >= 2)

        for pclass, pattern in STRONG_PATTERNS:
            for m in re.finditer(pattern, text, re.I):
                snippet = re.sub(r'\s+', ' ', text[max(0, m.start() - 80):m.end() + 120]).strip()

                named = re.search(r'syndicate\s+(\d+)', snippet, re.I)
                names_other = named is not None and named.group(1) != own_syndicate

                if pclass == 'counterparty':
                    external = names_other
                elif pclass == 'closure':
                    external = names_other
                else:  # premium_flow / acceptance
                    external = names_other or not is_uw_year_page

                if not external:
                    routine_hits += 1
                    continue

                heading = find_section_heading(text, m.start())
                strong_hits.append((page_no, pattern, snippet, heading))

        for pattern in WEAK_PATTERNS:
            for m in re.finditer(pattern, text, re.I):
                if is_boilerplate_context(text, m.start()):
                    continue
                if is_uw_year_page:
                    routine_hits += 1
                    continue
                snippet = re.sub(r'\s+', ' ', text[max(0, m.start() - 80):m.end() + 120]).strip()
                heading = find_section_heading(text, m.start())
                weak_hits.append((page_no, pattern, snippet, heading))

    if strong_hits:
        # Prefer a hit with an identified heading
        best = next((h for h in strong_hits if h[3]), strong_hits[0])
        return {
            'detection': 'successful',
            'ritc_occurred': True,
            'confidence': 'strong',
            'evidence': best[2][:400],
            'section': best[3] or f'p.{best[0]} (heading not identified)',
            'page': best[0],
            'n_strong_hits': len(strong_hits),
        }
    if weak_hits:
        best = next((h for h in weak_hits if h[3]), weak_hits[0])
        return {
            'detection': 'successful',
            'ritc_occurred': True,
            'confidence': 'weak',
            'evidence': best[2][:400],
            'section': best[3] or f'p.{best[0]} (heading not identified)',
            'page': best[0],
            'n_weak_hits': len(weak_hits),
        }
    if routine_hits:
        evidence = ('routine inter-YOA RITC only (underwriting-year accounts '
                    'or own-syndicate closure); no external RITC found')
    elif any_mention:
        evidence = 'RITC mentioned only in accounting-policy boilerplate'
    else:
        evidence = 'no RITC reference in report'
    return {
        'detection': 'successful',
        'ritc_occurred': False,
        'confidence': 'strong' if (not any_mention or routine_hits) else 'weak',
        'evidence': evidence,
        'section': 'whole document scan',
        'page': None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan reports for RITC occurrence")
    parser.add_argument("--rescan", action="store_true",
                        help="Re-scan reports already in the output file")
    parser.add_argument("--single", type=str, default=None,
                        help="Scan a single report, e.g. 1176_2022")
    args = parser.parse_args()

    setup_logging()

    results: Dict[str, dict] = {}
    if OUTPUT_PATH.exists():
        with open(OUTPUT_PATH, 'r', encoding='utf-8') as f:
            results = json.load(f)

    reports = sorted(
        p for p in PDF_DIR.iterdir()
        if re.match(r'syndicate_\d+_\d{4}\.(pdf|html?)$', p.name, re.I))
    if args.single:
        reports = [p for p in reports if args.single in p.name]
        if not reports:
            logger.error(f"No report matching {args.single}")
            return 1

    scanned = 0
    for report_path in reports:
        m = re.match(r'syndicate_(\d+)_(\d{4})', report_path.name)
        key = f"{m.group(1)}_{m.group(2)}"
        if key in results and not args.rescan:
            continue
        try:
            result = scan_report(report_path)
        except Exception as e:
            logger.error(f"Scan crashed for {report_path.name}: {e}")
            result = {'detection': 'failed', 'failure_reason': f'scan error: {e}'}
        result['scanned_at'] = datetime.now(timezone.utc).isoformat()
        result['file'] = report_path.name
        results[key] = result
        scanned += 1
        if scanned % 50 == 0:
            logger.info(f"Scanned {scanned} reports...")
            with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
                json.dump(results, f, indent=2, ensure_ascii=False)

    with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    n_occ = sum(1 for v in results.values() if v.get('ritc_occurred') is True)
    n_strong = sum(1 for v in results.values()
                   if v.get('ritc_occurred') is True and v.get('confidence') == 'strong')
    n_no = sum(1 for v in results.values() if v.get('ritc_occurred') is False)
    n_fail = sum(1 for v in results.values() if v.get('detection') == 'failed')
    logger.info(f"Scanned {scanned} new reports this run. Totals: "
                f"{n_occ} RITC occurred ({n_strong} strong), "
                f"{n_no} no RITC, {n_fail} detection failed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
