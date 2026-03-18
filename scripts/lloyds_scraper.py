#!/usr/bin/env python3
"""
Lloyd's Syndicate Report Scraper
================================
Downloads annual reports for Lloyd's syndicates (2014-2024) from lloyds.com

Usage:
    python lloyds_scraper.py [--syndicates 1209,2488] [--years 2020,2021,2022]
    python lloyds_scraper.py --all  # Scrape all syndicates, all years
"""

import os
import re
import sys
import json
import time
import argparse
import logging
from pathlib import Path
from datetime import datetime
from urllib.parse import urljoin
from dataclasses import dataclass, asdict
from typing import Optional, List, Dict, Tuple

import requests
from bs4 import BeautifulSoup

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('lloyds_scraper.log')
    ]
)
logger = logging.getLogger(__name__)

# Import syndicate numbers
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'data'))
from syndicate_numbers import ALL_SYNDICATES, ONLINE_YEARS, LIFE_SYNDICATES


@dataclass
class ReportInfo:
    """Information about a single syndicate report."""
    syndicate: int
    year: int
    title: str
    pdf_url: str
    local_path: Optional[str] = None
    download_status: str = 'pending'
    file_size: Optional[int] = None
    download_time: Optional[str] = None
    error: Optional[str] = None


class LloydsScraper:
    """Scraper for Lloyd's syndicate annual reports."""

    BASE_URL = "https://www.lloyds.com/about-lloyds/investor-relations/syndicate-reports-and-accounts"
    SEARCH_API_URL = "https://www.lloyds.com/query-dynamic-tables"

    # Direct PDF URL patterns (ordered by likelihood of success) - used as fallback
    PDF_URL_PATTERNS = [
        # Primary pattern for 2015-2023
        "https://assets.lloyds.com/assets/pdf-syndicate-reports-and-accounts-{year}-{syndicate}-a/1/{year}_{syndicate}_a.pdf",
        # Alternative with different filename format
        "https://assets.lloyds.com/assets/pdf-syndicate-reports-and-accounts-{year}-{syndicate}-a/1/pdf-syndicate-reports-and-accounts-{year}_{syndicate}_a.pdf",
        # 2014 specific pattern
        "https://assets.lloyds.com/assets/pdf-{year}-{syndicate}-a/1/pdf-{year}-{syndicate}-a.pdf",
        # Pattern with leading zeros for 3-digit syndicates
        "https://assets.lloyds.com/assets/pdf-syndicate-reports-and-accounts-{year}-{syndicate:04d}-a/1/{year}_{syndicate:04d}_a.pdf",
    ]
    
    HEADERS = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
    }
    
    def __init__(self, output_dir: str = "./output", delay: float = 1.0):
        """
        Initialize scraper.
        
        Args:
            output_dir: Directory to save downloaded reports
            delay: Delay between requests in seconds (be respectful)
        """
        self.output_dir = Path(output_dir)
        self.pdf_dir = self.output_dir / "pdfs"
        self.metadata_dir = self.output_dir / "metadata"
        self.delay = delay
        self.session = requests.Session()
        self.session.headers.update(self.HEADERS)
        
        # Create directories
        self.pdf_dir.mkdir(parents=True, exist_ok=True)
        self.metadata_dir.mkdir(parents=True, exist_ok=True)
        
        # Track results
        self.reports: List[ReportInfo] = []
        self.errors: List[Dict] = []
    
    def construct_pdf_urls(self, syndicate: int, year: int) -> List[str]:
        """Construct possible PDF URLs for a syndicate-year combination."""
        urls = []
        for pattern in self.PDF_URL_PATTERNS:
            try:
                url = pattern.format(year=year, syndicate=syndicate)
                urls.append(url)
            except (KeyError, ValueError):
                continue
        return urls

    def search_syndicate_pages(self, syndicate: int) -> List[str]:
        """
        Search for all syndicate report pages using Lloyd's search API.

        Returns list of page URLs for the syndicate.
        """
        try:
            params = {
                'Query': str(syndicate),
                'Type': 'Syndicate',
                'Page': '1',
                'HideFields': 'year'
            }
            response = self.session.get(self.SEARCH_API_URL, params=params, timeout=30)

            if response.status_code != 200:
                logger.debug(f"Search API returned status {response.status_code}")
                return []

            # Parse HTML response to extract page URLs
            soup = BeautifulSoup(response.text, 'html.parser')
            page_urls = []

            for link in soup.find_all('a', href=True):
                href = link['href']
                # Look for syndicate report page links
                if '/syndicate-reports-and-accounts/' in href and str(syndicate) in href:
                    # Make absolute URL if needed
                    if href.startswith('/'):
                        href = f"https://www.lloyds.com{href}"
                    page_urls.append(href)

            # Deduplicate
            page_urls = list(set(page_urls))
            logger.debug(f"Found {len(page_urls)} page URLs for syndicate {syndicate}")
            return page_urls

        except requests.RequestException as e:
            logger.warning(f"Search API request failed: {e}")
            return []

    def scrape_syndicate_page(self, page_url: str, syndicate: int) -> List[ReportInfo]:
        """
        Scrape a syndicate report page to extract PDF/HTML download links.

        Returns list of ReportInfo objects for reports found on the page.
        """
        reports = []
        try:
            response = self.session.get(page_url, timeout=30)
            if response.status_code != 200:
                logger.debug(f"Failed to fetch page {page_url}: status {response.status_code}")
                return []

            soup = BeautifulSoup(response.text, 'html.parser')

            # Find all links to assets.lloyds.com (PDF and HTML downloads)
            for link in soup.find_all('a', href=True):
                href = link['href']

                # Only process asset links
                if 'assets.lloyds.com' not in href:
                    continue

                # Check if it's a report file
                if not any(ext in href.lower() for ext in ['.pdf', '.html']):
                    continue

                # Extract year from URL or link text
                text = link.get_text(strip=True)
                year = self._extract_year(text, href)

                if year is None:
                    continue

                # Skip if year not in target range
                if year not in ONLINE_YEARS:
                    continue

                # Check if it's an annual or combined report (not underwriting year)
                # Annual reports end in -a, combined reports end in -c
                is_annual_or_combined = (
                    'annual' in text.lower() or
                    'combined' in text.lower() or
                    f'{syndicate}a' in href.lower() or
                    f'{syndicate}_a' in href.lower() or
                    f'-{syndicate}-a' in href.lower() or
                    f'{syndicate}c' in href.lower() or
                    f'{syndicate}_c' in href.lower() or
                    f'-{syndicate}-c' in href.lower()
                )

                if not is_annual_or_combined:
                    continue

                report = ReportInfo(
                    syndicate=syndicate,
                    year=year,
                    title=text if text else f"Syndicate {syndicate} Annual Accounts {year}",
                    pdf_url=href
                )
                reports.append(report)
                logger.debug(f"Found report: Syndicate {syndicate}, Year {year}, URL: {href}")

        except requests.RequestException as e:
            logger.warning(f"Failed to scrape page {page_url}: {e}")

        # Deduplicate by year (keep first match)
        seen_years = set()
        unique_reports = []
        for r in reports:
            if r.year not in seen_years:
                unique_reports.append(r)
                seen_years.add(r.year)

        return unique_reports
    
    def try_direct_download(self, syndicate: int, year: int) -> Optional[ReportInfo]:
        """
        Try to download PDF directly using constructed URLs.
        
        Returns ReportInfo if successful, None otherwise.
        """
        urls = self.construct_pdf_urls(syndicate, year)
        
        for url in urls:
            try:
                logger.debug(f"Trying URL: {url}")
                # Use GET with range header to check if file exists without downloading fully
                response = self.session.get(
                    url, 
                    timeout=15, 
                    allow_redirects=True,
                    headers={'Range': 'bytes=0-1024'},  # Only get first 1KB
                    stream=True
                )
                
                # Check for success (200 OK or 206 Partial Content)
                if response.status_code in (200, 206):
                    content_type = response.headers.get('Content-Type', '')
                    if 'pdf' in content_type.lower() or 'octet-stream' in content_type.lower():
                        # URL exists and is a PDF
                        report = ReportInfo(
                            syndicate=syndicate,
                            year=year,
                            title=f"Syndicate {syndicate} Annual Accounts {year}",
                            pdf_url=url
                        )
                        logger.info(f"Found PDF: {url}")
                        return report
                    
            except requests.RequestException as e:
                logger.debug(f"Failed to check {url}: {e}")
                continue
        
        return None
        
    def get_syndicate_page_url(self, syndicate: int) -> str:
        """Get the Lloyd's page URL for a syndicate."""
        # Lloyd's uses format: /syndicate-reports-and-accounts/{earliest_year}-{syndicate}
        # We'll try common patterns
        return f"{self.BASE_URL}/{syndicate}"
    
    def fetch_syndicate_page(self, syndicate: int) -> Optional[str]:
        """
        Fetch the syndicate's report listing page.
        
        Lloyd's pages can be accessed via multiple URL patterns.
        """
        # Try different URL patterns
        url_patterns = [
            f"{self.BASE_URL}/{syndicate}",
            f"{self.BASE_URL}/2014-{syndicate}",
            f"{self.BASE_URL}/2006-{syndicate}",  # Some older syndicates
        ]
        
        for url in url_patterns:
            try:
                logger.debug(f"Trying URL: {url}")
                response = self.session.get(url, timeout=30)
                
                if response.status_code == 200:
                    # Check if page has report links
                    if 'syndicate' in response.text.lower() and 'annual' in response.text.lower():
                        logger.info(f"Found syndicate {syndicate} page at {url}")
                        return response.text
                        
            except requests.RequestException as e:
                logger.debug(f"Failed to fetch {url}: {e}")
                continue
        
        logger.warning(f"Could not find page for syndicate {syndicate}")
        return None
    
    def parse_report_links(self, html: str, syndicate: int) -> List[ReportInfo]:
        """
        Parse HTML page to extract PDF report links.
        
        Returns list of ReportInfo objects for each found report.
        """
        soup = BeautifulSoup(html, 'html.parser')
        reports = []
        
        # Find all links to PDFs and HTMLs (2024+ use iXBRL HTML)
        for link in soup.find_all('a', href=True):
            href = link['href']
            text = link.get_text(strip=True)
            
            # Check if it's a report link
            if not any(ext in href.lower() for ext in ['.pdf', '.html']):
                continue
            
            # Skip if not from assets.lloyds.com
            if 'assets.lloyds.com' not in href:
                continue
            
            # Try to extract year from link text or URL
            year = self._extract_year(text, href)
            if year is None:
                continue
            
            # Skip if year not in our target range
            if year not in ONLINE_YEARS:
                continue
            
            # Determine report type
            title = text if text else f"Syndicate {syndicate} - {year}"
            
            # Only want annual accounts (not underwriting year accounts)
            # Look for 'annual' in title, or 'SRA{syndicate}a' pattern in URL
            is_annual = (
                'annual' in title.lower() or 
                'combined' in title.lower() or
                f'SRA{syndicate}a' in href or
                f'sra{syndicate}a' in href.lower() or
                re.search(rf'{syndicate}.*annual', href, re.I)
            )
            
            if not is_annual:
                # Check URL pattern - 'a' suffix typically indicates annual
                if not re.search(rf'/{year}[_-]{syndicate}[_-]?a', href, re.I):
                    if not re.search(rf'SRA{syndicate}a', href, re.I):
                        continue
            
            report = ReportInfo(
                syndicate=syndicate,
                year=year,
                title=title,
                pdf_url=href
            )
            reports.append(report)
            logger.debug(f"Found report: Syndicate {syndicate}, Year {year}")
        
        # Deduplicate by year (keep first/best match)
        seen_years = set()
        unique_reports = []
        for r in reports:
            if r.year not in seen_years:
                unique_reports.append(r)
                seen_years.add(r.year)
        
        return unique_reports
    
    def _extract_year(self, text: str, url: str) -> Optional[int]:
        """Extract year from link text or URL."""
        # Try text first
        year_match = re.search(r'20(1[4-9]|2[0-4])', text)
        if year_match:
            return int(year_match.group())
        
        # Try URL
        year_match = re.search(r'20(1[4-9]|2[0-4])', url)
        if year_match:
            return int(year_match.group())
        
        return None
    
    def download_report(self, report: ReportInfo) -> bool:
        """
        Download a single report PDF.
        
        Returns True if successful.
        """
        # Construct local filename
        ext = '.html' if '.html' in report.pdf_url.lower() else '.pdf'
        filename = f"syndicate_{report.syndicate}_{report.year}{ext}"
        local_path = self.pdf_dir / filename
        
        # Skip if already downloaded
        if local_path.exists():
            report.local_path = str(local_path)
            report.download_status = 'exists'
            report.file_size = local_path.stat().st_size
            logger.info(f"Already exists: {filename}")
            return True
        
        try:
            logger.info(f"Downloading: {filename}")
            response = self.session.get(report.pdf_url, timeout=60, stream=True)
            response.raise_for_status()
            
            # Save to temp file first, then rename on success (atomic download)
            import tempfile
            tmp_fd, tmp_path = tempfile.mkstemp(dir=str(self.pdf_dir), suffix='.tmp')
            try:
                with os.fdopen(tmp_fd, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
                Path(tmp_path).replace(local_path)
            except Exception:
                Path(tmp_path).unlink(missing_ok=True)
                raise

            report.local_path = str(local_path)
            report.download_status = 'success'
            report.file_size = local_path.stat().st_size
            report.download_time = datetime.now().isoformat()
            
            logger.info(f"Downloaded: {filename} ({report.file_size:,} bytes)")
            return True
            
        except requests.RequestException as e:
            report.download_status = 'failed'
            report.error = str(e)
            logger.error(f"Failed to download {filename}: {e}")
            return False
    
    def scrape_syndicate(self, syndicate: int, years: Optional[List[int]] = None) -> List[ReportInfo]:
        """
        Scrape all available reports for a single syndicate.

        Uses three approaches in order:
        1. Search API to find syndicate pages, then scrape each page for PDF links
        2. Fall back to direct PDF URL construction
        3. Fall back to legacy page scraping

        Returns list of ReportInfo objects.
        """
        if syndicate in LIFE_SYNDICATES:
            logger.info(f"Skipping life syndicate {syndicate}")
            return []

        logger.info(f"Processing syndicate {syndicate}")

        if years is None:
            years = ONLINE_YEARS

        reports = []
        found_years = set()

        # Approach 1: Use search API to find all syndicate pages
        page_urls = self.search_syndicate_pages(syndicate)
        if page_urls:
            logger.info(f"Found {len(page_urls)} page(s) via search API for syndicate {syndicate}")
            for page_url in page_urls:
                page_reports = self.scrape_syndicate_page(page_url, syndicate)
                for r in page_reports:
                    if r.year in years and r.year not in found_years:
                        reports.append(r)
                        found_years.add(r.year)
                time.sleep(0.3)  # Small delay between page requests

        # Approach 2: Try direct URL construction for missing years
        missing_years = [y for y in years if y not in found_years]
        if missing_years:
            logger.debug(f"Trying direct URLs for missing years: {missing_years}")
            for year in missing_years:
                report = self.try_direct_download(syndicate, year)
                if report:
                    reports.append(report)
                    found_years.add(year)
                    logger.debug(f"Found via direct URL: Syndicate {syndicate}, Year {year}")
                time.sleep(0.2)

        # Approach 3: If still nothing found, try legacy page scraping
        if not reports:
            logger.info(f"API and direct URLs failed, trying legacy page scraping for syndicate {syndicate}")
            html = self.fetch_syndicate_page(syndicate)
            if html:
                page_reports = self.parse_report_links(html, syndicate)
                page_reports = [r for r in page_reports if r.year in years]
                reports.extend(page_reports)

        logger.info(f"Found {len(reports)} reports for syndicate {syndicate}")

        # Download each report
        for report in reports:
            self.download_report(report)
            time.sleep(self.delay)  # Rate limiting

        self.reports.extend(reports)
        return reports
    
    def scrape_all(self, syndicates: Optional[List[int]] = None, 
                   years: Optional[List[int]] = None) -> Dict:
        """
        Scrape reports for all specified syndicates.
        
        Args:
            syndicates: List of syndicate numbers (default: all)
            years: List of years to filter (default: all available)
            
        Returns:
            Summary statistics dictionary
        """
        if syndicates is None:
            syndicates = [s for s in ALL_SYNDICATES if s not in LIFE_SYNDICATES]
        
        total = len(syndicates)
        logger.info(f"Starting scrape of {total} syndicates")
        
        for i, syndicate in enumerate(syndicates, 1):
            logger.info(f"Progress: {i}/{total} ({100*i/total:.1f}%)")
            
            try:
                reports = self.scrape_syndicate(syndicate, years=years)
                
            except Exception as e:
                logger.error(f"Error processing syndicate {syndicate}: {e}")
                self.errors.append({
                    'syndicate': syndicate,
                    'error': str(e),
                    'timestamp': datetime.now().isoformat()
                })
            
            # Save progress periodically
            if i % 10 == 0:
                self.save_metadata()
            
            time.sleep(self.delay)
        
        # Final save
        self.save_metadata()
        
        return self.get_summary()
    
    def save_metadata(self):
        """Save scraping metadata and results."""
        # Save reports metadata
        reports_data = [asdict(r) for r in self.reports]
        reports_file = self.metadata_dir / "reports.json"
        with open(reports_file, 'w') as f:
            json.dump(reports_data, f, indent=2)
        
        # Save errors
        errors_file = self.metadata_dir / "errors.json"
        with open(errors_file, 'w') as f:
            json.dump(self.errors, f, indent=2)
        
        # Save summary
        summary = self.get_summary()
        summary_file = self.metadata_dir / "summary.json"
        with open(summary_file, 'w') as f:
            json.dump(summary, f, indent=2)
        
        logger.info(f"Metadata saved to {self.metadata_dir}")
    
    def get_summary(self) -> Dict:
        """Get summary statistics."""
        successful = [r for r in self.reports if r.download_status in ('success', 'exists')]
        failed = [r for r in self.reports if r.download_status == 'failed']
        
        # Count by year
        by_year = {}
        for r in successful:
            by_year[r.year] = by_year.get(r.year, 0) + 1
        
        # Count by syndicate
        syndicates_found = len(set(r.syndicate for r in successful))
        
        return {
            'total_reports_found': len(self.reports),
            'successful_downloads': len(successful),
            'failed_downloads': len(failed),
            'syndicates_found': syndicates_found,
            'by_year': dict(sorted(by_year.items())),
            'total_errors': len(self.errors),
            'timestamp': datetime.now().isoformat()
        }


def main():
    parser = argparse.ArgumentParser(description="Scrape Lloyd's syndicate reports")
    parser.add_argument('--syndicates', type=str, help='Comma-separated syndicate numbers')
    parser.add_argument('--years', type=str, help='Comma-separated years')
    parser.add_argument('--all', action='store_true', help='Scrape all syndicates')
    parser.add_argument('--output', type=str, default='./output', help='Output directory')
    parser.add_argument('--delay', type=float, default=1.5, help='Delay between requests (seconds)')
    
    args = parser.parse_args()
    
    # Parse syndicates
    syndicates = None
    if args.syndicates:
        syndicates = [int(s.strip()) for s in args.syndicates.split(',')]
    
    # Parse years
    years = None
    if args.years:
        years = [int(y.strip()) for y in args.years.split(',')]
    
    # Create scraper and run
    scraper = LloydsScraper(output_dir=args.output, delay=args.delay)
    
    if args.all or syndicates:
        summary = scraper.scrape_all(syndicates=syndicates, years=years)
        
        print("\n" + "="*60)
        print("SCRAPING COMPLETE")
        print("="*60)
        print(f"Total reports found: {summary['total_reports_found']}")
        print(f"Successful downloads: {summary['successful_downloads']}")
        print(f"Failed downloads: {summary['failed_downloads']}")
        print(f"Unique syndicates: {summary['syndicates_found']}")
        print(f"\nReports by year:")
        for year, count in summary['by_year'].items():
            print(f"  {year}: {count}")
    else:
        print("Use --all to scrape all syndicates, or --syndicates to specify specific ones")
        print("Example: python lloyds_scraper.py --syndicates 1209,2488 --years 2020,2021")


if __name__ == "__main__":
    main()
