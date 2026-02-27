#!/usr/bin/env python3
"""
Lloyd's Market Commentary Scraper
=================================
Scrapes market-level reserve commentary from multiple sources:
- Lloyd's Annual Reports (official)
- Lloyd's Half Year Reports
- AM Best Lloyd's Reports
- Alpha Insurance Analysts
- Trade Press (Reinsurance News, Artemis, Insurance Journal, Insurance Times)
- Rating Agency Reports (Moody's, S&P, Fitch summaries)
- Broker Reports (Gallagher Re, Aon, etc.)

Then uses Perplexity API to summarize by line of business with citations.
"""

import os
import re
import json
import time
import logging
import hashlib
from pathlib import Path
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional, List, Dict, Any
from urllib.parse import urljoin, urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed

from dotenv import load_dotenv
import requests

# Load environment variables from .env file
load_dotenv()
from bs4 import BeautifulSoup

# Optional imports - gracefully handle if not installed
try:
    import pdfplumber
    PDF_SUPPORT = True
except ImportError:
    PDF_SUPPORT = False
    print("Warning: pdfplumber not installed. PDF extraction disabled.")

try:
    import fitz  # PyMuPDF
    PYMUPDF_SUPPORT = True
except ImportError:
    PYMUPDF_SUPPORT = False


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@dataclass
class CommentarySource:
    """Represents a single source of market commentary."""
    source_type: str  # 'lloyds_official', 'am_best', 'trade_press', 'broker', 'rating_agency'
    source_name: str
    url: str
    year: int
    period: str  # 'annual', 'interim', 'quarterly'
    content: str = ""  # Truncated for JSON output
    extracted_at: str = ""
    content_hash: str = ""  # SHA256 of full content for verification
    lines_of_business: Dict[str, str] = field(default_factory=dict)
    reserve_movements: List[Dict] = field(default_factory=list)
    causal_statements: List[str] = field(default_factory=list)
    # Audit trail fields
    full_text_file: str = ""  # Path to full text file
    pdf_file: str = ""  # Path to original PDF (if applicable)
    content_length: int = 0  # Full content length in characters
    extraction_method: str = ""  # 'pdfplumber', 'beautifulsoup', etc.
    

@dataclass
class LineOfBusinessSummary:
    """Summary of reserve commentary for a specific line of business."""
    line_of_business: str
    year: int
    prior_year_movement_pct: Optional[float] = None
    direction: str = ""  # 'release', 'strengthening', 'flat'
    amount_gbp_m: Optional[float] = None
    causal_factors: List[str] = field(default_factory=list)
    sources: List[str] = field(default_factory=list)
    confidence: str = ""  # 'high', 'medium', 'low'


class SourceRegistry:
    """Registry of all known commentary sources by year."""
    
    # Lloyd's Official Sources - multiple URL patterns per year (first working URL will be used)
    # URLs verified via web search December 2024
    LLOYDS_ANNUAL_REPORTS = {
        2024: [
            "https://assets.lloyds.com/media/530f990a-cdf1-4f3c-b776-4908cba51966/Lloyd's-Annual-Report-2024.pdf",
        ],
        2023: [
            "https://assets.lloyds.com/media/3bda2895-4700-47fc-9117-515a62ee36ed/Lloyd's%20Annual%20Report%202023.pdf",
            "https://assets.lloyds.com/media/84f9eb1b-3a7b-47ab-8780-8fd56c2175c2/Lloyd's%20Annual%20Report%202023.pdf",
        ],
        2022: [
            "https://assets.lloyds.com/media/5070d2bd-3819-4e31-b1e3-c67c656e5eb8/Lloyds-Annual-Report_2022.pdf",
        ],
        2021: [
            "https://assets.lloyds.com/media/81b1778b-e821-4424-b21e-26e0bf095f10/Lloyds_AR21_220323.pdf",
            "https://assets.lloyds.com/media/b9275229-7bee-477f-96a0-6b415f3e7d2b/Lloyds_AR_210409_NO_sig.pdf",
        ],
        2020: [
            "https://assets.lloyds.com/media/dd1c24e5-6ff0-42b5-9aab-eab29fa7f401/Lloyd's%20of%20London_AR_%20210701.pdf",
        ],
        2019: [
            "https://assets.lloyds.com/media/56a6076a-d43c-4e48-b314-53f80025647e/lloyds_annual_report_2019_-_strategic_report.b5815ef96250.pdf",
        ],
        2018: [
            "https://assets.lloyds.com/assets/pdf-annual-report-2018-annual-report-market-results/1/pdf-annual-report-2018-Annual-Report-Market-Results.pdf",
        ],
        2017: [
            "https://assets.lloyds.com/assets/pdf-annual-report-2017-ar2017-annual-report-2017/1/pdf-annual-report-2017-AR2017-Annual-Report-2017.pdf",
        ],
        2016: [
            "https://assets.lloyds.com/media/b08e3c05-3e5e-4e79-89e7-fe30ca6eaf6c/Lloyds%20AR%202016%20(1).pdf",
        ],
        2015: [
            "https://assets.lloyds.com/media/77352402-2355-4d7a-ba75-258232064494/Lloyds%20AR%202015%20(1).pdf",
        ],
        2014: [
            "https://assets.lloyds.com/media/406289ac-37bf-498d-ada3-c28f1b2a08d0/Lloyds%20AR%202014.pdf",
        ],
    }
    
    LLOYDS_ANALYST_PRESENTATIONS = {
        2024: "https://assets.lloyds.com/media/lloyds-2024-analyst-presentation.pdf",
        2023: "https://assets.lloyds.com/media/lloyds-2023-analyst-presentation.pdf",
        2022: "https://assets.lloyds.com/media/lloyds-2022-analyst-presentation.pdf",
        2018: "https://assets.lloyds.com/media/dddca19c-36c6-4a29-80ba-324aa3fdfee2/pdf-annual-report-2018-Lloyds-2018-Annual-Results-Analyst-Presentation-FINAL.PDF",
        2015: "https://assets.lloyds.com/media/933c6929-71d8-463d-a08a-a1ecec20d62b/2015-Annual-Results-Presentation.pdf",
        2014: "https://assets.lloyds.com/media/e8d35e99-52ed-4961-900c-f23b9c51d9ee/AR2014_Analyst-Presentation.pdf",
    }
    
    # AM Best Lloyd's Reports (these need to be discovered dynamically)
    AM_BEST_BASE = "https://web.ambest.com/docs/default-source/ratings/"
    
    # Trade Press Sources
    TRADE_PRESS_SOURCES = [
        {
            "name": "Reinsurance News",
            "base_url": "https://www.reinsurancene.ws",
            "search_pattern": "/tag/lloyds/",
            "type": "trade_press"
        },
        {
            "name": "Artemis",
            "base_url": "https://www.artemis.bm",
            "search_pattern": "/news/?s=lloyd%27s+results",
            "type": "trade_press"
        },
        {
            "name": "Insurance Journal",
            "base_url": "https://www.insurancejournal.com",
            "search_pattern": "/search/?q=lloyd%27s+market+results",
            "type": "trade_press"
        },
        {
            "name": "Insurance Times",
            "base_url": "https://www.insurancetimes.co.uk",
            "search_pattern": "/topics/london-market",
            "type": "trade_press"
        },
        {
            "name": "Insurance Business Mag",
            "base_url": "https://www.insurancebusinessmag.com",
            "search_pattern": "/uk/news/breaking-news/",
            "type": "trade_press"
        },
    ]
    
    # Broker/Analyst Reports
    BROKER_REPORTS = {
        "Gallagher Re": {
            2022: "https://www.ajg.com/gallagherre/-/media/files/gallagher/gallagherre/gallagher-re-lloyds-market-report-2022.pdf",
        },
        "Alpha Insurance Analysts": {
            "base_url": "https://www.aianalysts.com",
            "search_pattern": "/category/lloyds/",
        },
        "PNO Insurance": {
            "base_url": "https://pno.com.au",
            "search_pattern": "/insights/lloyds-of-london-annual-results",
        }
    }
    
    # Lines of Business to track
    LINES_OF_BUSINESS = [
        "Reinsurance - Property",
        "Reinsurance - Casualty", 
        "Reinsurance - Specialty",
        "Property",
        "Casualty",
        "Marine, Aviation and Transport",
        "Energy",
        "Motor",
    ]


class MarketCommentaryScraper:
    """Main scraper class for Lloyd's market commentary."""
    
    def __init__(self, output_dir: str = "./market_commentary_data", 
                 perplexity_api_key: Optional[str] = None):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.perplexity_api_key = perplexity_api_key or os.environ.get("PERPLEXITY_API_KEY")
        self.session = self._create_session()
        self.sources: List[CommentarySource] = []
        self.registry = SourceRegistry()
        
    def _create_session(self) -> requests.Session:
        """Create a requests session with appropriate headers."""
        session = requests.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
        })
        return session
    
    def _download_pdf(self, url: str, save_path: Path, quiet: bool = False) -> bool:
        """Download a PDF file.

        Args:
            url: URL to download from
            save_path: Path to save the file
            quiet: If True, don't log errors for 404s (useful when trying multiple URLs)
        """
        try:
            response = self.session.get(url, timeout=60, stream=True)
            response.raise_for_status()

            with open(save_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            logger.info(f"Downloaded: {save_path.name}")
            return True
        except requests.exceptions.HTTPError as e:
            if not quiet:
                logger.error(f"Failed to download {url}: {e}")
            return False
        except Exception as e:
            if not quiet:
                logger.error(f"Failed to download {url}: {e}")
            return False
    
    def _extract_pdf_text(self, pdf_path: Path) -> str:
        """Extract text from a PDF file."""
        if not PDF_SUPPORT:
            logger.warning("PDF support not available")
            return ""
        
        try:
            text_parts = []
            with pdfplumber.open(pdf_path) as pdf:
                for page in pdf.pages:
                    text = page.extract_text()
                    if text:
                        text_parts.append(text)
            return "\n\n".join(text_parts)
        except Exception as e:
            logger.error(f"Failed to extract text from {pdf_path}: {e}")
            return ""
    
    def _extract_reserve_commentary(self, text: str) -> Dict[str, Any]:
        """Extract reserve-related commentary from text."""
        results = {
            "prior_year_movements": [],
            "causal_statements": [],
            "lob_mentions": {},
            "quantified_amounts": []
        }
        
        # Patterns for prior year reserve movements
        movement_patterns = [
            r'prior year (?:reserve )?(?:releases?|strengthening|development|movements?) of (?:£|GBP |USD |\$)?(\d+(?:\.\d+)?)\s*(?:m|million|bn|billion)?',
            r'(?:released|strengthened|reserved) (?:£|GBP |USD |\$)?(\d+(?:\.\d+)?)\s*(?:m|million|bn|billion)? (?:from|on|for) prior year',
            r'(\d+(?:\.\d+)?)\s*%\s*(?:prior year|PY)\s*(?:release|strengthening|development)',
            r'prior year movement (?:was )?(?:a )?(?:release|strengthening) of (\d+(?:\.\d+)?)\s*%',
        ]
        
        for pattern in movement_patterns:
            matches = re.finditer(pattern, text, re.IGNORECASE)
            for match in matches:
                context_start = max(0, match.start() - 200)
                context_end = min(len(text), match.end() + 200)
                context = text[context_start:context_end]
                results["prior_year_movements"].append({
                    "match": match.group(0),
                    "value": match.group(1),
                    "context": context
                })
        
        # Causal language patterns
        causal_patterns = [
            r'(?:driven by|due to|arising from|as a result of|reflecting|following)[^.]{10,150}',
            r'(?:favourable|adverse|positive|negative) (?:experience|development|claims)[^.]{10,150}',
            r'(?:social inflation|litigation|court ruling|regulatory|Ogden|economic inflation)[^.]{10,150}',
            r'(?:catastrophe|hurricane|flood|earthquake|wildfire)[^.]{10,150}(?:reserve|claim|loss)',
            r'(?:COVID|pandemic|lockdown)[^.]{10,150}(?:reserve|claim|release)',
        ]
        
        for pattern in causal_patterns:
            matches = re.finditer(pattern, text, re.IGNORECASE)
            for match in matches:
                statement = match.group(0).strip()
                if len(statement) > 30:  # Filter out too-short matches
                    results["causal_statements"].append(statement)
        
        # Line of business mentions
        for lob in self.registry.LINES_OF_BUSINESS:
            lob_pattern = re.escape(lob).replace(r'\ ', r'\s+')
            mentions = re.findall(f'{lob_pattern}[^.]*\.', text, re.IGNORECASE)
            if mentions:
                results["lob_mentions"][lob] = mentions[:5]  # Limit to 5 mentions per LOB
        
        # Quantified amounts with context
        amount_pattern = r'(?:£|GBP |USD |\$)(\d+(?:\.\d+)?)\s*(?:m|million|bn|billion)[^.]{0,100}(?:reserve|release|strengthen|prior year)'
        matches = re.finditer(amount_pattern, text, re.IGNORECASE)
        for match in matches:
            results["quantified_amounts"].append({
                "amount": match.group(1),
                "context": match.group(0)
            })
        
        return results
    
    def scrape_lloyds_official(self, years: List[int] = None) -> List[CommentarySource]:
        """Scrape Lloyd's official annual reports."""
        if years is None:
            years = list(self.registry.LLOYDS_ANNUAL_REPORTS.keys())

        sources = []
        pdf_dir = self.output_dir / "pdfs" / "lloyds_official"
        pdf_dir.mkdir(parents=True, exist_ok=True)

        # Create full text directory for audit trail
        fulltext_dir = self.output_dir / "full_text" / "lloyds_official"
        fulltext_dir.mkdir(parents=True, exist_ok=True)

        for year in years:
            if year not in self.registry.LLOYDS_ANNUAL_REPORTS:
                logger.warning(f"No Lloyd's report URL for year {year}")
                continue

            url_list = self.registry.LLOYDS_ANNUAL_REPORTS[year]
            # Handle both old format (single string) and new format (list of strings)
            if isinstance(url_list, str):
                url_list = [url_list]

            pdf_path = pdf_dir / f"lloyds_annual_report_{year}.pdf"
            fulltext_path = fulltext_dir / f"lloyds_annual_report_{year}.txt"

            # Download if not exists - try multiple URLs
            working_url = None
            if not pdf_path.exists():
                for url in url_list:
                    if self._download_pdf(url, pdf_path, quiet=True):
                        working_url = url
                        break
                if not working_url:
                    logger.warning(f"Lloyd's report for {year} not found at any known URL")
                    continue
            else:
                working_url = url_list[0]  # Use first URL as reference
            
            # Extract text
            text = self._extract_pdf_text(pdf_path)
            if not text:
                continue

            # Save full text for audit trail
            with open(fulltext_path, 'w', encoding='utf-8') as f:
                f.write(f"# Source: {working_url}\n")
                f.write(f"# Extracted: {datetime.now().isoformat()}\n")
                f.write(f"# PDF: {pdf_path}\n")
                f.write(f"# Length: {len(text)} characters\n")
                f.write("#" + "="*70 + "\n\n")
                f.write(text)

            # Extract reserve commentary
            commentary = self._extract_reserve_commentary(text)

            source = CommentarySource(
                source_type="lloyds_official",
                source_name=f"Lloyd's Annual Report {year}",
                url=working_url,
                year=year,
                period="annual",
                content=text[:50000],  # Truncated for JSON - full text in file
                extracted_at=datetime.now().isoformat(),
                content_hash=hashlib.sha256(text.encode()).hexdigest(),
                lines_of_business=commentary["lob_mentions"],
                reserve_movements=commentary["prior_year_movements"],
                causal_statements=commentary["causal_statements"],
                # Audit trail
                full_text_file=str(fulltext_path.relative_to(self.output_dir)),
                pdf_file=str(pdf_path.relative_to(self.output_dir)),
                content_length=len(text),
                extraction_method="pdfplumber"
            )
            sources.append(source)
            logger.info(f"Processed Lloyd's {year}: {len(commentary['causal_statements'])} causal statements found")
            logger.info(f"  Full text saved to: {fulltext_path}")
        
        return sources
    
    def scrape_trade_press(self, years: List[int] = None) -> List[CommentarySource]:
        """Scrape trade press sources for Lloyd's market commentary."""
        if years is None:
            years = list(range(2014, 2025))
        
        sources = []
        
        # Create full text directory for audit trail
        fulltext_dir = self.output_dir / "full_text" / "trade_press"
        fulltext_dir.mkdir(parents=True, exist_ok=True)
        
        article_counter = 0
        
        for source_config in self.registry.TRADE_PRESS_SOURCES:
            logger.info(f"Scraping {source_config['name']}...")
            
            try:
                # Search for Lloyd's results articles
                search_url = source_config['base_url'] + source_config['search_pattern']
                response = self.session.get(search_url, timeout=30)
                
                if response.status_code != 200:
                    logger.warning(f"Failed to access {source_config['name']}: {response.status_code}")
                    continue
                
                soup = BeautifulSoup(response.text, 'html.parser')
                
                # Find article links (generic pattern - may need customization per source)
                article_links = []
                for a in soup.find_all('a', href=True):
                    href = a['href']
                    # Skip anchor-only links, javascript links, and other non-HTTP links
                    if href.startswith('#') or href.startswith('javascript:') or href.startswith('mailto:'):
                        continue
                    text = a.get_text().lower()
                    if any(term in text for term in ['lloyd', 'result', 'profit', 'reserve']):
                        if href.startswith('/'):
                            href = source_config['base_url'] + href
                        # Only add if it's a valid HTTP(S) URL
                        if href.startswith('http://') or href.startswith('https://'):
                            article_links.append(href)
                
                # Deduplicate
                article_links = list(set(article_links))[:20]  # Limit to 20 articles
                
                for article_url in article_links:
                    try:
                        article_response = self.session.get(article_url, timeout=30)
                        if article_response.status_code != 200:
                            continue
                        
                        article_soup = BeautifulSoup(article_response.text, 'html.parser')
                        
                        # Extract article text
                        article_text = ""
                        for tag in article_soup.find_all(['p', 'article', 'div'], class_=re.compile(r'content|article|body')):
                            article_text += tag.get_text() + "\n"
                        
                        if len(article_text) < 200:
                            continue
                        
                        # Try to extract year from URL or content
                        year_match = re.search(r'20(1[4-9]|2[0-4])', article_url + article_text[:500])
                        article_year = int("20" + year_match.group(1)) if year_match else 2024
                        
                        # Extract reserve commentary
                        commentary = self._extract_reserve_commentary(article_text)
                        
                        if commentary["causal_statements"] or commentary["prior_year_movements"]:
                            article_counter += 1
                            
                            # Save full text for audit trail
                            safe_name = re.sub(r'[^\w\-]', '_', source_config['name'])
                            fulltext_path = fulltext_dir / f"{safe_name}_{article_year}_{article_counter:04d}.txt"
                            
                            with open(fulltext_path, 'w', encoding='utf-8') as f:
                                f.write(f"# Source: {article_url}\n")
                                f.write(f"# Publisher: {source_config['name']}\n")
                                f.write(f"# Extracted: {datetime.now().isoformat()}\n")
                                f.write(f"# Length: {len(article_text)} characters\n")
                                f.write("#" + "="*70 + "\n\n")
                                f.write(article_text)
                            
                            source = CommentarySource(
                                source_type="trade_press",
                                source_name=source_config['name'],
                                url=article_url,
                                year=article_year,
                                period="article",
                                content=article_text[:10000],  # Truncated - full text in file
                                extracted_at=datetime.now().isoformat(),
                                content_hash=hashlib.sha256(article_text.encode()).hexdigest(),
                                lines_of_business=commentary["lob_mentions"],
                                reserve_movements=commentary["prior_year_movements"],
                                causal_statements=commentary["causal_statements"],
                                # Audit trail
                                full_text_file=str(fulltext_path.relative_to(self.output_dir)),
                                pdf_file="",  # HTML source, no PDF
                                content_length=len(article_text),
                                extraction_method="beautifulsoup"
                            )
                            sources.append(source)
                        
                        time.sleep(1)  # Rate limiting
                        
                    except Exception as e:
                        logger.error(f"Error processing {article_url}: {e}")
                        continue
                
            except Exception as e:
                logger.error(f"Error scraping {source_config['name']}: {e}")
                continue
        
        return sources
    
    def scrape_alpha_insurance_analysts(self) -> List[CommentarySource]:
        """Scrape Alpha Insurance Analysts blog posts."""
        sources = []
        base_url = "https://www.aianalysts.com"
        
        try:
            # Try to get the Lloyd's category page
            response = self.session.get(f"{base_url}/category/lloyds/", timeout=30)
            if response.status_code != 200:
                # Try alternative paths
                response = self.session.get(f"{base_url}/?s=lloyd%27s", timeout=30)
            
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')
                
                # Find blog post links
                for article in soup.find_all('article'):
                    link = article.find('a', href=True)
                    if link:
                        article_url = link['href']
                        if not article_url.startswith('http'):
                            article_url = base_url + article_url
                        
                        try:
                            article_response = self.session.get(article_url, timeout=30)
                            if article_response.status_code == 200:
                                article_soup = BeautifulSoup(article_response.text, 'html.parser')
                                content = article_soup.find('div', class_=re.compile(r'entry|content|post'))
                                if content:
                                    text = content.get_text()
                                    commentary = self._extract_reserve_commentary(text)
                                    
                                    year_match = re.search(r'20(1[4-9]|2[0-4])', article_url + text[:500])
                                    article_year = int("20" + year_match.group(1)) if year_match else 2024
                                    
                                    source = CommentarySource(
                                        source_type="analyst",
                                        source_name="Alpha Insurance Analysts",
                                        url=article_url,
                                        year=article_year,
                                        period="article",
                                        content=text[:10000],
                                        extracted_at=datetime.now().isoformat(),
                                        content_hash=hashlib.md5(text.encode()).hexdigest(),
                                        lines_of_business=commentary["lob_mentions"],
                                        reserve_movements=commentary["prior_year_movements"],
                                        causal_statements=commentary["causal_statements"]
                                    )
                                    sources.append(source)
                            
                            time.sleep(1)
                        except Exception as e:
                            logger.error(f"Error processing Alpha article: {e}")
                            continue
                            
        except Exception as e:
            logger.error(f"Error scraping Alpha Insurance Analysts: {e}")
        
        return sources
    
    def scrape_am_best(self, years: List[int] = None) -> List[CommentarySource]:
        """Attempt to scrape AM Best Lloyd's reports."""
        sources = []

        if years is None:
            years = list(range(2020, 2025))

        # Generate URL patterns to try for each year
        # AM Best URLs have changed over time and use different paths, so we try multiple patterns
        # Also try Lloyd's-hosted copies of AM Best reports
        def get_am_best_url_patterns(year: int) -> List[str]:
            patterns = [
                # AM Best events folder (used for 2024)
                f"https://web.ambest.com/docs/default-source/events/best's-rating-of-lloyd's-{year}.pdf",
                # AM Best ratings folder (used for 2022 and earlier)
                f"https://web.ambest.com/docs/default-source/ratings/best's-ratings-of-lloyd's-{year}.pdf",
                f"https://web.ambest.com/docs/default-source/ratings/best's-rating-of-lloyd's-{year}.pdf",
                # URL encoded versions
                f"https://web.ambest.com/docs/default-source/ratings/bests-ratings-of-lloyds-{year}.pdf",
                f"https://web.ambest.com/docs/default-source/events/bests-rating-of-lloyds-{year}.pdf",
            ]
            # Add Lloyd's-hosted AM Best reports as fallback
            if year == 2024:
                patterns.append("https://assets.lloyds.com/media/53bdb2d5-b3d1-4e75-94be-2ace936e3e35/AM%20Best%20report%20-%20Lloyd%27s%20upgrade.pdf")
            return patterns

        pdf_dir = self.output_dir / "pdfs" / "am_best"
        pdf_dir.mkdir(parents=True, exist_ok=True)

        # Create full text directory for audit trail
        fulltext_dir = self.output_dir / "full_text" / "am_best"
        fulltext_dir.mkdir(parents=True, exist_ok=True)

        for year in years:
            url_patterns = get_am_best_url_patterns(year)

            pdf_path = pdf_dir / f"am_best_lloyds_{year}.pdf"
            fulltext_path = fulltext_dir / f"am_best_lloyds_{year}.txt"

            try:
                # Try to download from multiple URL patterns
                downloaded = False
                working_url = None
                if not pdf_path.exists():
                    for url in url_patterns:
                        if self._download_pdf(url, pdf_path, quiet=True):
                            working_url = url
                            downloaded = True
                            break
                    if not downloaded:
                        logger.warning(f"AM Best report for {year} not found at any known URL")
                        continue
                else:
                    working_url = url_patterns[0]  # Use first pattern as reference
                
                text = self._extract_pdf_text(pdf_path)
                if not text:
                    continue
                
                # Save full text for audit trail
                with open(fulltext_path, 'w', encoding='utf-8') as f:
                    f.write(f"# Source: {working_url}\n")
                    f.write(f"# Extracted: {datetime.now().isoformat()}\n")
                    f.write(f"# PDF: {pdf_path}\n")
                    f.write(f"# Length: {len(text)} characters\n")
                    f.write("#" + "="*70 + "\n\n")
                    f.write(text)

                commentary = self._extract_reserve_commentary(text)

                source = CommentarySource(
                    source_type="rating_agency",
                    source_name=f"AM Best Lloyd's Report {year}",
                    url=working_url,
                    year=year,
                    period="annual",
                    content=text[:30000],  # Truncated for JSON - full text in file
                    extracted_at=datetime.now().isoformat(),
                    content_hash=hashlib.sha256(text.encode()).hexdigest(),
                    lines_of_business=commentary["lob_mentions"],
                    reserve_movements=commentary["prior_year_movements"],
                    causal_statements=commentary["causal_statements"],
                    # Audit trail
                    full_text_file=str(fulltext_path.relative_to(self.output_dir)),
                    pdf_file=str(pdf_path.relative_to(self.output_dir)),
                    content_length=len(text),
                    extraction_method="pdfplumber"
                )
                sources.append(source)
                logger.info(f"Processed AM Best {year}: {len(commentary['causal_statements'])} causal statements")
                logger.info(f"  Full text saved to: {fulltext_path}")
                
            except Exception as e:
                logger.error(f"Error processing AM Best {year}: {e}")
                continue
        
        return sources
    
    def scrape_all(self, years: List[int] = None) -> List[CommentarySource]:
        """Run all scrapers and combine results."""
        all_sources = []
        
        logger.info("=== Starting Lloyd's Market Commentary Scrape ===")
        
        # Lloyd's Official
        logger.info("Scraping Lloyd's official reports...")
        all_sources.extend(self.scrape_lloyds_official(years))
        
        # AM Best
        logger.info("Scraping AM Best reports...")
        all_sources.extend(self.scrape_am_best(years))
        
        # Alpha Insurance Analysts
        logger.info("Scraping Alpha Insurance Analysts...")
        all_sources.extend(self.scrape_alpha_insurance_analysts())
        
        # Trade Press
        logger.info("Scraping trade press...")
        all_sources.extend(self.scrape_trade_press(years))
        
        self.sources = all_sources
        logger.info(f"=== Scrape complete: {len(all_sources)} sources collected ===")
        
        return all_sources
    
    def save_results(self, filename: str = "market_commentary.json"):
        """Save scraped results to JSON with audit trail."""
        output_path = self.output_dir / filename
        
        # Convert to serializable format
        data = {
            "scraped_at": datetime.now().isoformat(),
            "total_sources": len(self.sources),
            "audit_trail": {
                "output_directory": str(self.output_dir.absolute()),
                "full_text_directory": str((self.output_dir / "full_text").absolute()),
                "pdf_directory": str((self.output_dir / "pdfs").absolute()),
                "hash_algorithm": "sha256",
                "note": "Full original text stored in full_text_directory. content field in sources is truncated."
            },
            "sources_by_type": {},
            "sources_by_year": {},
            "sources": [asdict(s) for s in self.sources]
        }
        
        # Count by type and year
        for source in self.sources:
            stype = source.source_type
            syear = source.year
            data["sources_by_type"][stype] = data["sources_by_type"].get(stype, 0) + 1
            data["sources_by_year"][str(syear)] = data["sources_by_year"].get(str(syear), 0) + 1
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        logger.info(f"Saved results to {output_path}")
        logger.info(f"  Total sources: {len(self.sources)}")
        logger.info(f"  Full text files: {self.output_dir / 'full_text'}")
        logger.info(f"  PDF files: {self.output_dir / 'pdfs'}")
        
        # Also save audit manifest
        self._save_audit_manifest()
        
        return output_path
    
    def _save_audit_manifest(self):
        """Save a manifest of all files for audit purposes."""
        manifest_path = self.output_dir / "audit_manifest.json"
        
        manifest = {
            "generated_at": datetime.now().isoformat(),
            "total_sources": len(self.sources),
            "files": []
        }
        
        for source in self.sources:
            entry = {
                "source_name": source.source_name,
                "url": source.url,
                "year": source.year,
                "content_hash": source.content_hash,
                "content_length": source.content_length,
                "full_text_file": source.full_text_file,
                "pdf_file": source.pdf_file,
                "extracted_at": source.extracted_at,
                "extraction_method": source.extraction_method
            }
            manifest["files"].append(entry)
        
        with open(manifest_path, 'w', encoding='utf-8') as f:
            json.dump(manifest, f, indent=2)
        
        logger.info(f"Saved audit manifest to {manifest_path}")


class PerplexitySummarizer:
    """Uses Perplexity API to summarize market commentary by line of business."""
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.api_url = "https://api.perplexity.ai/chat/completions"
        
    def _call_perplexity(self, prompt: str, model: str = "llama-3.1-sonar-large-128k-online") -> Dict:
        """Make a call to Perplexity API."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": """You are an expert insurance analyst specializing in Lloyd's of London market analysis. 
                    When summarizing reserve movements, always:
                    1. Cite specific sources with URLs where possible
                    2. Quantify movements in £ or % where data is available
                    3. Identify causal factors (social inflation, catastrophes, court rulings, etc.)
                    4. Distinguish between market-level and syndicate-level commentary"""
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            "temperature": 0.2,
            "top_p": 0.9,
            "return_citations": True,
            "search_domain_filter": [
                "lloyds.com",
                "reinsurancene.ws",
                "artemis.bm",
                "insurancejournal.com",
                "ambest.com",
                "insurancebusinessmag.com"
            ],
            "search_recency_filter": "year"
        }
        
        response = requests.post(self.api_url, headers=headers, json=payload, timeout=60)
        response.raise_for_status()
        return response.json()
    
    def summarize_by_line_of_business(self, year: int) -> Dict[str, LineOfBusinessSummary]:
        """Get Perplexity to summarize reserve commentary for each LOB."""
        summaries = {}
        
        lines_of_business = [
            "Property Reinsurance",
            "Casualty Reinsurance", 
            "Specialty Reinsurance",
            "Direct Property",
            "Direct Casualty",
            "Marine Aviation and Transport",
            "Energy",
            "Motor"
        ]
        
        for lob in lines_of_business:
            prompt = f"""Summarize the Lloyd's of London market {year} reserve development and prior year movements 
            specifically for {lob} business.
            
            Please include:
            1. The direction of prior year movement (release or strengthening) and percentage if available
            2. Quantified amounts in GBP millions
            3. Specific causal factors driving the movements (e.g., social inflation, specific catastrophe events, 
               court rulings, COVID-19 effects, changes in Ogden rate, etc.)
            4. How this compares to the overall market average
            5. Any forward-looking concerns or themes mentioned by Lloyd's, AM Best, or market analysts
            
            Focus on market-level commentary from Lloyd's annual reports, AM Best Lloyd's reports, 
            and specialist insurance trade press. Cite your sources."""
            
            try:
                response = self._call_perplexity(prompt)
                content = response['choices'][0]['message']['content']
                citations = response.get('citations', [])
                
                # Parse the response to extract structured data
                summary = LineOfBusinessSummary(
                    line_of_business=lob,
                    year=year,
                    sources=citations
                )
                
                # Extract direction
                if 'release' in content.lower():
                    summary.direction = 'release'
                elif 'strengthen' in content.lower():
                    summary.direction = 'strengthening'
                else:
                    summary.direction = 'mixed'
                
                # Extract percentage if present
                pct_match = re.search(r'(\d+(?:\.\d+)?)\s*%', content)
                if pct_match:
                    summary.prior_year_movement_pct = float(pct_match.group(1))
                
                # Extract amount if present
                amount_match = re.search(r'(?:£|GBP\s*)(\d+(?:\.\d+)?)\s*(?:m|million)', content, re.IGNORECASE)
                if amount_match:
                    summary.amount_gbp_m = float(amount_match.group(1))
                
                # Extract causal factors (simple extraction)
                causal_keywords = [
                    'social inflation', 'catastrophe', 'hurricane', 'flood', 'COVID',
                    'court ruling', 'Ogden', 'litigation', 'economic inflation',
                    'claims development', 'IBNR', 'reinsurance'
                ]
                for keyword in causal_keywords:
                    if keyword.lower() in content.lower():
                        summary.causal_factors.append(keyword)
                
                # Add the full response as context
                summary.sources.append(f"Perplexity summary: {content[:500]}...")
                
                summaries[lob] = summary
                logger.info(f"Summarized {lob}: {summary.direction}, {summary.prior_year_movement_pct}%")
                
                time.sleep(2)  # Rate limiting
                
            except Exception as e:
                logger.error(f"Error summarizing {lob}: {e}")
                continue
        
        return summaries
    
    def generate_market_report(self, year: int) -> str:
        """Generate a comprehensive market report for a given year."""
        prompt = f"""Generate a comprehensive Lloyd's of London market reserve development report for {year}.
        
        Structure the report as follows:
        
        ## Executive Summary
        - Overall market prior year reserve movement (direction and percentage)
        - Key themes driving reserve development
        - Notable differences between lines of business
        
        ## Line of Business Analysis
        For each major line (Reinsurance Property, Reinsurance Casualty, Reinsurance Specialty, 
        Direct Property, Direct Casualty, Marine/Aviation/Transport, Energy, Motor):
        - Prior year movement percentage
        - Direction (release or strengthening)
        - Quantified amounts where available
        - Specific causal factors
        
        ## Causal Factor Deep Dive
        - Social inflation impact (especially US casualty)
        - Natural catastrophe reserve development
        - COVID-19 related movements
        - Economic inflation impact
        - Court rulings and regulatory changes
        
        ## Forward Looking Commentary
        - Areas of concern flagged by Lloyd's oversight
        - Rating agency perspectives
        - Expected themes for future years
        
        Cite all sources with URLs. Focus on Lloyd's official communications, AM Best Lloyd's reports,
        and credible insurance trade press."""
        
        try:
            response = self._call_perplexity(prompt, model="llama-3.1-sonar-large-128k-online")
            content = response['choices'][0]['message']['content']
            citations = response.get('citations', [])
            
            # Append citations
            report = content + "\n\n## Sources\n"
            for i, citation in enumerate(citations, 1):
                report += f"{i}. {citation}\n"
            
            return report
            
        except Exception as e:
            logger.error(f"Error generating market report: {e}")
            return f"Error generating report: {e}"


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Scrape Lloyd's market commentary")
    parser.add_argument("--years", nargs="+", type=int, default=None,
                        help="Years to scrape (default: all available)")
    parser.add_argument("--output-dir", default="./market_commentary_data",
                        help="Output directory for scraped data")
    parser.add_argument("--perplexity-key", default=None,
                        help="Perplexity API key (or set PERPLEXITY_API_KEY env var)")
    parser.add_argument("--summarize", action="store_true",
                        help="Use Perplexity to generate LOB summaries")
    parser.add_argument("--report-year", type=int, default=None,
                        help="Generate a full market report for this year")
    
    args = parser.parse_args()
    
    # Run scraper
    scraper = MarketCommentaryScraper(
        output_dir=args.output_dir,
        perplexity_api_key=args.perplexity_key
    )
    
    sources = scraper.scrape_all(years=args.years)
    scraper.save_results()
    
    # Perplexity summarization
    if args.summarize or args.report_year:
        api_key = args.perplexity_key or os.environ.get("PERPLEXITY_API_KEY")
        if not api_key:
            logger.error("Perplexity API key required for summarization")
            return
        
        summarizer = PerplexitySummarizer(api_key)
        
        if args.summarize:
            for year in (args.years or [2023, 2022]):
                summaries = summarizer.summarize_by_line_of_business(year)
                
                # Save summaries
                summary_path = Path(args.output_dir) / f"lob_summaries_{year}.json"
                with open(summary_path, 'w') as f:
                    json.dump({lob: asdict(s) for lob, s in summaries.items()}, f, indent=2)
                logger.info(f"Saved LOB summaries to {summary_path}")
        
        if args.report_year:
            report = summarizer.generate_market_report(args.report_year)
            report_path = Path(args.output_dir) / f"market_report_{args.report_year}.md"
            with open(report_path, 'w') as f:
                f.write(report)
            logger.info(f"Saved market report to {report_path}")


if __name__ == "__main__":
    main()
