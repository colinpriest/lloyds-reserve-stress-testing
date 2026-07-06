"""Download syndicate reports listed in Lloyds_syndicates_2014_2024.xlsx.

For each syndicate-year row in the spreadsheet:
  - if the report file already exists locally -> status "report downloaded" (already_present)
  - if the URL is a direct PDF -> download it
  - if the URL is a Lloyd's SRA landing page -> scrape the page for the
    year-matched annual/combined accounts asset link, then download it
  - on failure -> status "report unavailable" with the error reason

Progress is recorded in syndicate_reports/download_status.json keyed by
"{syndicate}_{year}" so the script is fully resumable: rows already resolved
as downloaded are skipped on re-run. Failed rows are retried only with
--retry-failed.

Usage:
    python scripts/download_from_xlsx.py                # process everything pending
    python scripts/download_from_xlsx.py --limit 100    # bounded batch (resumable)
    python scripts/download_from_xlsx.py --retry-failed # re-attempt unavailable rows
"""

import argparse
import json
import logging
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd
import requests
from bs4 import BeautifulSoup

PROJECT_ROOT = Path(__file__).resolve().parent.parent
XLSX_PATH = PROJECT_ROOT / "syndicate_reports" / "Lloyds_syndicates_2014_2024.xlsx"
PDF_DIR = PROJECT_ROOT / "syndicate_reports" / "pdfs"
STATUS_PATH = PROJECT_ROOT / "syndicate_reports" / "download_status.json"
LOG_PATH = PROJECT_ROOT / "syndicate_reports" / "download_from_xlsx.log"

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5',
}

logger = logging.getLogger(__name__)


def setup_logging() -> None:
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    fh = logging.FileHandler(LOG_PATH, mode='a', encoding='utf-8')
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'))
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))
    root.addHandler(fh)
    root.addHandler(ch)


def load_status() -> Dict[str, dict]:
    if STATUS_PATH.exists():
        with open(STATUS_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def save_status(status: Dict[str, dict]) -> None:
    tmp = STATUS_PATH.with_suffix('.json.tmp')
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(status, f, indent=2, ensure_ascii=False)
    tmp.replace(STATUS_PATH)


def local_report_path(syndicate: int, year: int) -> Optional[Path]:
    """Return the existing local report file for a syndicate-year, if any."""
    for ext in ('.pdf', '.html', '.htm'):
        p = PDF_DIR / f"syndicate_{syndicate}_{year}{ext}"
        if p.exists() and p.stat().st_size > 0:
            return p
    return None


def is_pdf_content(first_bytes: bytes) -> bool:
    return first_bytes[:5] == b'%PDF-'


def download_asset(session: requests.Session, url: str, syndicate: int,
                   year: int) -> Tuple[Path, int]:
    """Download an assets.lloyds.com report file. Returns (path, size).

    Raises on HTTP errors or if the payload is neither a PDF nor HTML.
    """
    response = session.get(url, timeout=60, stream=True)
    response.raise_for_status()

    chunks: List[bytes] = []
    for chunk in response.iter_content(chunk_size=8192):
        chunks.append(chunk)
    content = b''.join(chunks)

    if is_pdf_content(content):
        ext = '.pdf'
    elif (content.lstrip(b'\xef\xbb\xbf \t\r\n')[:1] == b'<'
          and b'.pdf' not in url.lower().encode()):
        # iXBRL HTML report (2024 onwards) — only accept if URL was an HTML asset
        if '.html' in url.lower() or '.htm' in url.lower():
            ext = '.html'
        else:
            raise ValueError(
                f"Response is HTML but URL is not an HTML asset "
                f"(likely an error/redirect page): {url}")
    else:
        raise ValueError(f"Unrecognised content (not PDF, not HTML) from {url}")

    if len(content) < 10_000:
        raise ValueError(
            f"File suspiciously small ({len(content)} bytes) from {url}")

    local_path = PDF_DIR / f"syndicate_{syndicate}_{year}{ext}"
    tmp = local_path.with_suffix(local_path.suffix + '.tmp')
    with open(tmp, 'wb') as f:
        f.write(content)
    tmp.replace(local_path)
    return local_path, len(content)


def candidate_asset_urls(syndicate: int, year: int, xlsx_url: str,
                         url_type: str) -> List[str]:
    """Ordered candidate asset URLs for a syndicate-year.

    The spreadsheet URL comes first (when it is a direct asset link), followed
    by known Lloyd's asset naming patterns: annual (-a) preferred over
    combined (-c), zero-padded syndicate numbers preferred (verified working
    for syndicates absent from the non-padded namespace).
    """
    urls: List[str] = []
    if url_type == 'Direct PDF':
        urls.append(xlsx_url)
        # -a <-> -c variant of the spreadsheet URL
        if '-c/' in xlsx_url or '_c.pdf' in xlsx_url:
            urls.append(xlsx_url.replace('-c/', '-a/').replace('_c.pdf', '_a.pdf'))
        elif '-a/' in xlsx_url or '_a.pdf' in xlsx_url:
            urls.append(xlsx_url.replace('-a/', '-c/').replace('_a.pdf', '_c.pdf'))

    for suffix in ('a', 'c'):
        urls.extend([
            f"https://assets.lloyds.com/assets/pdf-syndicate-reports-and-accounts-"
            f"{year}-{syndicate:04d}-{suffix}/1/{year}_{syndicate:04d}_{suffix}.pdf",
            f"https://assets.lloyds.com/assets/pdf-syndicate-reports-and-accounts-"
            f"{year}-{syndicate}-{suffix}/1/{year}_{syndicate}_{suffix}.pdf",
            f"https://assets.lloyds.com/assets/pdf-syndicate-reports-and-accounts-"
            f"{year}-{syndicate}-{suffix}/1/pdf-syndicate-reports-and-accounts-"
            f"{year}_{syndicate}_{suffix}.pdf",
            f"https://assets.lloyds.com/assets/pdf-2006-{syndicate}-{year}-"
            f"{syndicate:04d}-{suffix}/1/pdf-2006-{syndicate}-{year}_{syndicate:04d}_{suffix}.pdf",
            f"https://assets.lloyds.com/assets/pdf-{year}-{syndicate}-{suffix}/1/"
            f"pdf-{year}-{syndicate}-{suffix}.pdf",
        ])

    # Deduplicate, preserving order
    seen = set()
    unique = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            unique.append(u)
    return unique


def probe_url(session: requests.Session, url: str) -> bool:
    """Cheaply check whether an asset URL serves a PDF (Range request)."""
    try:
        r = session.get(url, timeout=15, allow_redirects=True,
                        headers={'Range': 'bytes=0-1024'}, stream=True)
        if r.status_code in (200, 206):
            ctype = r.headers.get('Content-Type', '').lower()
            return 'pdf' in ctype or 'octet-stream' in ctype or 'html' in ctype
    except requests.RequestException:
        pass
    return False


SRA_BASE = "https://www.lloyds.com/about-lloyds/investor-relations/syndicate-reports-and-accounts"


def discover_sra_page(session: requests.Session, syndicate: int,
                      delay: float) -> Optional[str]:
    """Find a syndicate's SRA landing page(s) by probing slug prefixes.

    Lloyd's slugs are '{era_year}-{syndicate}' (e.g. 2006-33, 2015-218). A
    syndicate can have multiple era pages, and recent-year links use
    unguessable /media/{guid}/ asset URLs, so ALL matching pages are fetched
    and their HTML concatenated. Returns None if no page exists.
    """
    pages: List[str] = []
    for prefix in range(2006, 2025):
        url = f"{SRA_BASE}/{prefix}-{syndicate}"
        try:
            time.sleep(delay / 3)
            r = session.get(url, timeout=20)
        except requests.RequestException as e:
            logger.debug(f"SRA probe failed {url}: {e}")
            continue
        # Real pages carry report asset links (either /assets/ or /media/)
        if r.status_code == 200 and 'assets.lloyds.com' in r.text:
            logger.info(f"Found SRA page for syndicate {syndicate}: {prefix}-{syndicate}")
            pages.append(r.text)
    return '\n'.join(pages) if pages else None


def extract_year_from_link(text: str, href: str) -> Optional[int]:
    m = re.search(r'20(1[4-9]|2[0-4])', text)
    if m:
        return int(m.group())
    m = re.search(r'20(1[4-9]|2[0-4])', href)
    if m:
        return int(m.group())
    return None


def find_asset_on_sra_page(page_html: str, syndicate: int,
                           year: int) -> Optional[str]:
    """Find the annual/combined accounts asset link for a given year on an SRA page."""
    soup = BeautifulSoup(page_html, 'html.parser')
    candidates: List[Tuple[int, str]] = []  # (priority, href)

    for link in soup.find_all('a', href=True):
        href = link['href']
        if 'assets.lloyds.com' not in href:
            continue
        if not any(ext in href.lower() for ext in ('.pdf', '.html', '.htm')):
            continue
        text = link.get_text(strip=True)
        link_year = extract_year_from_link(text, href)
        if link_year != year:
            continue

        low = (text + ' ' + href).lower()
        # Standalone underwriting-year accounts are not wanted — but combined
        # annual + underwriting year accounts ARE (post-2019 links are titled
        # "Combined annual and underwriting year accounts YYYY")
        tl = text.lower()
        if 'underwriting year' in tl and not ('annual' in tl or 'combined' in tl):
            continue

        # Priority: annual (-a) > combined (-c) > anything else year-matched
        if ('annual' in low or f'-{syndicate}-a' in low
                or f'{syndicate}_a' in low or f'{syndicate}a.' in low):
            priority = 0
        elif ('combined' in low or f'-{syndicate}-c' in low
                or f'{syndicate}_c' in low or f'{syndicate}c.' in low):
            priority = 1
        else:
            priority = 2
        candidates.append((priority, href))

    if not candidates:
        return None
    candidates.sort(key=lambda c: c[0])
    return candidates[0][1]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download syndicate reports listed in the coverage xlsx")
    parser.add_argument("--limit", type=int, default=None,
                        help="Max number of downloads to attempt this run")
    parser.add_argument("--retry-failed", action="store_true",
                        help="Re-attempt rows previously flagged unavailable")
    parser.add_argument("--delay", type=float, default=1.5,
                        help="Delay between HTTP requests (seconds)")
    args = parser.parse_args()

    setup_logging()

    df = pd.read_excel(XLSX_PATH, sheet_name='All Data')
    df.columns = ['year', 'syndicate', 'agent', 'url', 'url_type']
    df = df.sort_values(['year', 'syndicate']).reset_index(drop=True)

    status = load_status()
    session = requests.Session()
    session.headers.update(HEADERS)
    # Per-syndicate SRA page HTML cache (one page lists all years).
    # None = discovery attempted, no page found.
    sra_page_cache: Dict[int, Optional[str]] = {}

    attempted = 0
    downloaded = 0
    unavailable = 0
    skipped = 0

    for _, row in df.iterrows():
        syndicate = int(row['syndicate'])
        year = int(row['year'])
        key = f"{syndicate}_{year}"
        url = str(row['url']).strip()
        url_type = str(row['url_type']).strip()

        # Already present on disk -> record and move on (no HTTP)
        existing = local_report_path(syndicate, year)
        if existing is not None:
            prev = status.get(key, {})
            if prev.get('status') != 'report downloaded':
                status[key] = {
                    'status': 'report downloaded',
                    'detail': 'already_present' if prev.get('detail') != 'downloaded_this_run'
                              else prev.get('detail'),
                    'file': existing.name,
                    'file_size': existing.stat().st_size,
                    'source_url': prev.get('source_url', url),
                    'timestamp': prev.get('timestamp',
                                          datetime.now(timezone.utc).isoformat()),
                }
            skipped += 1
            continue

        prev = status.get(key, {})
        if prev.get('status') == 'report unavailable' and not args.retry_failed:
            unavailable += 1
            continue

        if args.limit is not None and attempted >= args.limit:
            continue
        attempted += 1

        try:
            asset_url = None

            # Strategy 1: spreadsheet direct URL — single cheap probe
            if url_type == 'Direct PDF':
                time.sleep(args.delay / 3)
                if probe_url(session, url):
                    asset_url = url

            # Strategy 2: syndicate SRA landing page (cached; one page lists
            # all years). Slug discovered by probing prefix years, falling
            # back to the spreadsheet's SRA URL if it responds.
            if asset_url is None:
                if syndicate not in sra_page_cache:
                    page_html = None
                    if url_type != 'Direct PDF':
                        time.sleep(args.delay / 3)
                        try:
                            resp = session.get(url, timeout=30)
                            if (resp.status_code == 200
                                    and 'assets.lloyds.com' in resp.text):
                                page_html = resp.text
                        except requests.RequestException:
                            pass
                    if page_html is None:
                        page_html = discover_sra_page(session, syndicate, args.delay)
                    sra_page_cache[syndicate] = page_html
                page_html = sra_page_cache[syndicate]
                if page_html is not None:
                    asset_url = find_asset_on_sra_page(page_html, syndicate, year)

            # Strategy 3: probe known direct asset URL patterns
            if asset_url is None:
                for candidate in candidate_asset_urls(syndicate, year, url, url_type):
                    if candidate == url and url_type == 'Direct PDF':
                        continue  # already probed in strategy 1
                    time.sleep(args.delay / 3)
                    if probe_url(session, candidate):
                        asset_url = candidate
                        break

            if asset_url is None:
                raise ValueError(
                    "No working asset URL found (direct URL, SRA page scrape, "
                    "and all known URL patterns failed)")

            time.sleep(args.delay)
            local_path, size = download_asset(session, asset_url, syndicate, year)
            status[key] = {
                'status': 'report downloaded',
                'detail': 'downloaded_this_run',
                'file': local_path.name,
                'file_size': size,
                'source_url': asset_url,
                'timestamp': datetime.now(timezone.utc).isoformat(),
            }
            downloaded += 1
            logger.info(f"[{downloaded}] Downloaded {local_path.name} ({size:,} bytes)")

        except Exception as e:
            status[key] = {
                'status': 'report unavailable',
                'detail': str(e)[:500],
                'source_url': url,
                'timestamp': datetime.now(timezone.utc).isoformat(),
            }
            unavailable += 1
            logger.warning(f"Unavailable {key}: {e}")

        if attempted % 10 == 0:
            save_status(status)

    save_status(status)

    total = len(df)
    done = sum(1 for v in status.values() if v['status'] == 'report downloaded')
    failed = sum(1 for v in status.values() if v['status'] == 'report unavailable')
    pending = total - done - failed
    logger.info(
        f"Run complete: attempted={attempted}, downloaded={downloaded}, "
        f"already-present-skips={skipped}, unavailable-this-run-or-skipped={unavailable}")
    logger.info(
        f"Overall ledger: {done}/{total} downloaded, {failed} unavailable, "
        f"{pending} not yet attempted")
    return 0 if pending == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
