#!/usr/bin/env python3
"""
Syndicate Size Metrics Extractor
================================
Extracts portfolio size metrics from Lloyd's syndicate annual reports.

This supplements the existing corpus by extracting financial data that
wasn't captured by the reserve commentary extraction:
- Stamp capacity
- Gross/net written premiums
- Technical provisions (total reserves)
- Claims outstanding
- Combined ratios

These metrics are essential for portfolio size diversification analysis.

Input: Directory of syndicate PDFs (same as used by quality_classifier.py)
Output: syndicate_size_metrics.json with size data by syndicate-year

Usage:
    python extract_size_metrics.py --pdf-dir ./lloyds_data/pdfs --output size_metrics.json
"""

import os
import re
import json
import logging
import argparse
from pathlib import Path
from dataclasses import dataclass, asdict, field
from typing import Optional, List, Dict, Tuple, Any
from collections import defaultdict

# PDF extraction libraries
try:
    import fitz  # PyMuPDF
    HAS_PYMUPDF = True
except ImportError:
    HAS_PYMUPDF = False

try:
    import pdfplumber
    HAS_PDFPLUMBER = True
except ImportError:
    HAS_PDFPLUMBER = False

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class SyndicateSizeMetrics:
    """Size metrics for a single syndicate-year."""
    syndicate: int
    year: int
    
    # Capacity metrics
    stamp_capacity_gbp_m: Optional[float] = None
    stamp_capacity_usd_m: Optional[float] = None
    
    # Premium metrics
    gross_written_premium_gbp_m: Optional[float] = None
    gross_written_premium_usd_m: Optional[float] = None
    net_written_premium_gbp_m: Optional[float] = None
    net_written_premium_usd_m: Optional[float] = None
    net_earned_premium_gbp_m: Optional[float] = None
    net_earned_premium_usd_m: Optional[float] = None
    
    # Reserve/provision metrics (these are the key size indicators)
    technical_provisions_gbp_m: Optional[float] = None
    technical_provisions_usd_m: Optional[float] = None
    claims_outstanding_gbp_m: Optional[float] = None
    claims_outstanding_usd_m: Optional[float] = None
    prior_year_reserves_gbp_m: Optional[float] = None  # Opening position
    prior_year_reserves_usd_m: Optional[float] = None
    
    # Ratio metrics (useful for context)
    combined_ratio_pct: Optional[float] = None
    claims_ratio_pct: Optional[float] = None
    expense_ratio_pct: Optional[float] = None
    
    # Extraction metadata
    reporting_currency: str = "GBP"  # Primary currency used in report
    extraction_confidence: str = "medium"  # high/medium/low
    extraction_notes: List[str] = field(default_factory=list)
    source_file: str = ""
    pages_searched: int = 0
    
    def to_dict(self) -> Dict:
        return asdict(self)
    
    def has_size_data(self) -> bool:
        """Check if we extracted any meaningful size data."""
        return any([
            self.stamp_capacity_gbp_m,
            self.stamp_capacity_usd_m,
            self.gross_written_premium_gbp_m,
            self.gross_written_premium_usd_m,
            self.technical_provisions_gbp_m,
            self.technical_provisions_usd_m,
            self.claims_outstanding_gbp_m,
            self.claims_outstanding_usd_m,
        ])
    
    def get_best_size_estimate(self) -> Optional[float]:
        """
        Return the best available size estimate in GBP millions.
        Priority: technical_provisions > claims_outstanding > stamp_capacity > GWP
        """
        # Technical provisions is the most relevant for reserve analysis
        if self.technical_provisions_gbp_m:
            return self.technical_provisions_gbp_m
        if self.technical_provisions_usd_m:
            return self.technical_provisions_usd_m * 0.8  # Rough USD->GBP
        
        # Claims outstanding is a close proxy
        if self.claims_outstanding_gbp_m:
            return self.claims_outstanding_gbp_m
        if self.claims_outstanding_usd_m:
            return self.claims_outstanding_usd_m * 0.8
        
        # Stamp capacity gives sense of scale
        if self.stamp_capacity_gbp_m:
            return self.stamp_capacity_gbp_m
        if self.stamp_capacity_usd_m:
            return self.stamp_capacity_usd_m * 0.8
        
        # GWP as last resort
        if self.gross_written_premium_gbp_m:
            return self.gross_written_premium_gbp_m
        if self.gross_written_premium_usd_m:
            return self.gross_written_premium_usd_m * 0.8
        
        return None


# =============================================================================
# Extraction Patterns
# =============================================================================

class ExtractionPatterns:
    """Regex patterns for extracting financial metrics."""
    
    # Currency amount patterns
    # Matches: £450.3m, £1,234.5m, $500m, £450.3 million, (£450.3m), £450.3m*
    GBP_AMOUNT = re.compile(
        r'£\s*([\d,]+(?:\.\d+)?)\s*(?:m|million|mn)',
        re.IGNORECASE
    )
    USD_AMOUNT = re.compile(
        r'\$\s*([\d,]+(?:\.\d+)?)\s*(?:m|million|mn)',
        re.IGNORECASE
    )
    
    # Also match amounts in tables without currency symbol but with context
    NUMERIC_MILLIONS = re.compile(
        r'(?<!\d)([\d,]+(?:\.\d+)?)\s*(?:m|million|mn)?\b',
        re.IGNORECASE
    )
    
    # Percentage patterns
    PERCENTAGE = re.compile(
        r'([\d]+(?:\.\d+)?)\s*%',
        re.IGNORECASE
    )
    
    # Section header patterns
    STRATEGIC_REPORT = re.compile(
        r'strategic\s+report|managing\s+agent.?s?\s+report|business\s+review',
        re.IGNORECASE
    )
    BALANCE_SHEET = re.compile(
        r'balance\s+sheet|statement\s+of\s+financial\s+position',
        re.IGNORECASE
    )
    PROFIT_LOSS = re.compile(
        r'profit\s+and\s+loss|income\s+statement|statement\s+of\s+(?:comprehensive\s+)?income',
        re.IGNORECASE
    )
    TECHNICAL_ACCOUNT = re.compile(
        r'technical\s+account|underwriting\s+account',
        re.IGNORECASE
    )
    
    # Key metric patterns (context + amount)
    STAMP_CAPACITY = re.compile(
        r'(?:stamp|underwriting)\s+capacity[:\s]*(?:of\s+)?(?:£|\$)?\s*([\d,]+(?:\.\d+)?)\s*(?:m|million)?',
        re.IGNORECASE
    )
    
    GROSS_WRITTEN_PREMIUM = re.compile(
        r'gross\s+(?:written\s+)?premium[s]?[:\s]*(?:£|\$)?\s*([\d,]+(?:\.\d+)?)',
        re.IGNORECASE
    )
    
    NET_WRITTEN_PREMIUM = re.compile(
        r'net\s+(?:written\s+)?premium[s]?[:\s]*(?:£|\$)?\s*([\d,]+(?:\.\d+)?)',
        re.IGNORECASE
    )
    
    TECHNICAL_PROVISIONS = re.compile(
        r'technical\s+provisions?[:\s]*(?:£|\$)?\s*([\d,]+(?:\.\d+)?)',
        re.IGNORECASE
    )
    
    CLAIMS_OUTSTANDING = re.compile(
        r'(?:claims?\s+outstanding|provision\s+for\s+claims|claims?\s+reserves?)[:\s]*(?:£|\$)?\s*([\d,]+(?:\.\d+)?)',
        re.IGNORECASE
    )
    
    COMBINED_RATIO = re.compile(
        r'combined\s+(?:operating\s+)?ratio[:\s]*([\d]+(?:\.\d+)?)\s*%?',
        re.IGNORECASE
    )
    
    CLAIMS_RATIO = re.compile(
        r'(?:net\s+)?claims?\s+ratio[:\s]*([\d]+(?:\.\d+)?)\s*%?',
        re.IGNORECASE
    )
    
    EXPENSE_RATIO = re.compile(
        r'expense\s+ratio[:\s]*([\d]+(?:\.\d+)?)\s*%?',
        re.IGNORECASE
    )


# =============================================================================
# Main Extractor Class
# =============================================================================

class SizeMetricsExtractor:
    """Extracts size metrics from Lloyd's syndicate annual reports."""
    
    def __init__(self):
        self.patterns = ExtractionPatterns()
        self.stats = {
            'total_processed': 0,
            'successful_extractions': 0,
            'failed_extractions': 0,
            'metrics_by_field': defaultdict(int)
        }
    
    def extract_text_from_pdf(self, pdf_path: str) -> Tuple[str, int]:
        """
        Extract text from PDF file.
        Returns (text, page_count)
        """
        if HAS_PYMUPDF:
            try:
                doc = fitz.open(pdf_path)
                pages = []
                for page in doc:
                    pages.append(page.get_text())
                page_count = len(doc)
                doc.close()
                return "\n\n--- PAGE BREAK ---\n\n".join(pages), page_count
            except Exception as e:
                logger.warning(f"PyMuPDF extraction failed for {pdf_path}: {e}")
        
        if HAS_PDFPLUMBER:
            try:
                with pdfplumber.open(pdf_path) as pdf:
                    pages = []
                    for page in pdf.pages:
                        page_text = page.extract_text()
                        if page_text:
                            pages.append(page_text)
                    return "\n\n--- PAGE BREAK ---\n\n".join(pages), len(pdf.pages)
            except Exception as e:
                logger.warning(f"pdfplumber extraction failed for {pdf_path}: {e}")
        
        return "", 0
    
    def extract_text_from_html(self, html_path: str) -> Tuple[str, int]:
        """Extract text from HTML file (for 2024 iXBRL reports)."""
        try:
            from bs4 import BeautifulSoup
            with open(html_path, 'r', encoding='utf-8') as f:
                soup = BeautifulSoup(f.read(), 'html.parser')
                text = soup.get_text(separator='\n')
                return text, 1
        except Exception as e:
            logger.warning(f"HTML extraction failed for {html_path}: {e}")
            return "", 0
    
    def parse_amount(self, text: str, pattern: re.Pattern, 
                     currency: str = "GBP") -> Optional[float]:
        """
        Extract a monetary amount using the given pattern.
        Returns value in millions.
        """
        match = pattern.search(text)
        if match:
            try:
                # Remove commas and convert
                value_str = match.group(1).replace(',', '')
                value = float(value_str)
                
                # Check if already in millions or needs conversion
                # Most Lloyd's reports use millions
                if value > 10000:  # Probably in thousands, convert to millions
                    value = value / 1000
                
                return value
            except (ValueError, IndexError):
                pass
        return None
    
    def find_section(self, text: str, pattern: re.Pattern, 
                     context_chars: int = 5000) -> str:
        """Find a section of text matching the pattern with surrounding context."""
        match = pattern.search(text)
        if match:
            start = max(0, match.start() - 200)
            end = min(len(text), match.end() + context_chars)
            return text[start:end]
        return ""
    
    def detect_currency(self, text: str) -> str:
        """Detect the primary reporting currency used."""
        gbp_count = len(re.findall(r'£', text[:10000]))
        usd_count = len(re.findall(r'\$', text[:10000]))
        
        # Also check for explicit statements
        if re.search(r'reporting\s+currency[:\s]+(?:us\s+)?dollar|functional\s+currency[:\s]+usd', 
                     text[:5000], re.IGNORECASE):
            return "USD"
        if re.search(r'reporting\s+currency[:\s]+(?:pounds?\s+)?sterling|functional\s+currency[:\s]+gbp', 
                     text[:5000], re.IGNORECASE):
            return "GBP"
        
        return "USD" if usd_count > gbp_count * 1.5 else "GBP"
    
    def extract_from_strategic_report(self, text: str, metrics: SyndicateSizeMetrics):
        """Extract metrics from Strategic Report section."""
        section = self.find_section(text, self.patterns.STRATEGIC_REPORT, 8000)
        if not section:
            return
        
        # Stamp capacity
        match = self.patterns.STAMP_CAPACITY.search(section)
        if match:
            try:
                value = float(match.group(1).replace(',', ''))
                if value > 10000:
                    value = value / 1000
                if '£' in section[max(0, match.start()-20):match.start()+5]:
                    metrics.stamp_capacity_gbp_m = value
                else:
                    metrics.stamp_capacity_usd_m = value
                metrics.extraction_notes.append(f"Stamp capacity from strategic report: {value}m")
            except (ValueError, IndexError):
                pass
        
        # Gross written premium
        match = self.patterns.GROSS_WRITTEN_PREMIUM.search(section)
        if match:
            try:
                value = float(match.group(1).replace(',', ''))
                if value > 10000:
                    value = value / 1000
                if metrics.reporting_currency == "GBP":
                    metrics.gross_written_premium_gbp_m = value
                else:
                    metrics.gross_written_premium_usd_m = value
            except (ValueError, IndexError):
                pass
        
        # Combined ratio
        match = self.patterns.COMBINED_RATIO.search(section)
        if match:
            try:
                metrics.combined_ratio_pct = float(match.group(1))
            except (ValueError, IndexError):
                pass
        
        # Claims ratio
        match = self.patterns.CLAIMS_RATIO.search(section)
        if match:
            try:
                metrics.claims_ratio_pct = float(match.group(1))
            except (ValueError, IndexError):
                pass
    
    def extract_from_balance_sheet(self, text: str, metrics: SyndicateSizeMetrics):
        """Extract metrics from Balance Sheet."""
        section = self.find_section(text, self.patterns.BALANCE_SHEET, 6000)
        if not section:
            return
        
        # Technical provisions (total)
        match = self.patterns.TECHNICAL_PROVISIONS.search(section)
        if match:
            try:
                value = float(match.group(1).replace(',', ''))
                if value > 10000:
                    value = value / 1000
                if metrics.reporting_currency == "GBP":
                    metrics.technical_provisions_gbp_m = value
                else:
                    metrics.technical_provisions_usd_m = value
                metrics.extraction_notes.append(f"Technical provisions from balance sheet: {value}m")
            except (ValueError, IndexError):
                pass
        
        # Claims outstanding
        match = self.patterns.CLAIMS_OUTSTANDING.search(section)
        if match:
            try:
                value = float(match.group(1).replace(',', ''))
                if value > 10000:
                    value = value / 1000
                if metrics.reporting_currency == "GBP":
                    metrics.claims_outstanding_gbp_m = value
                else:
                    metrics.claims_outstanding_usd_m = value
            except (ValueError, IndexError):
                pass
    
    def extract_from_profit_loss(self, text: str, metrics: SyndicateSizeMetrics):
        """Extract metrics from Profit & Loss / Technical Account."""
        # Try technical account first (Lloyd's specific)
        section = self.find_section(text, self.patterns.TECHNICAL_ACCOUNT, 6000)
        if not section:
            section = self.find_section(text, self.patterns.PROFIT_LOSS, 6000)
        if not section:
            return
        
        # Gross written premium
        if not metrics.gross_written_premium_gbp_m and not metrics.gross_written_premium_usd_m:
            match = self.patterns.GROSS_WRITTEN_PREMIUM.search(section)
            if match:
                try:
                    value = float(match.group(1).replace(',', ''))
                    if value > 10000:
                        value = value / 1000
                    if metrics.reporting_currency == "GBP":
                        metrics.gross_written_premium_gbp_m = value
                    else:
                        metrics.gross_written_premium_usd_m = value
                except (ValueError, IndexError):
                    pass
        
        # Net written premium
        match = self.patterns.NET_WRITTEN_PREMIUM.search(section)
        if match:
            try:
                value = float(match.group(1).replace(',', ''))
                if value > 10000:
                    value = value / 1000
                if metrics.reporting_currency == "GBP":
                    metrics.net_written_premium_gbp_m = value
                else:
                    metrics.net_written_premium_usd_m = value
            except (ValueError, IndexError):
                pass
    
    def extract_from_full_text(self, text: str, metrics: SyndicateSizeMetrics):
        """
        Fallback extraction searching entire document.
        Used when section-specific extraction fails.
        """
        # Try to find stamp capacity anywhere
        if not metrics.stamp_capacity_gbp_m and not metrics.stamp_capacity_usd_m:
            match = self.patterns.STAMP_CAPACITY.search(text)
            if match:
                try:
                    value = float(match.group(1).replace(',', ''))
                    if value > 10000:
                        value = value / 1000
                    # Check context for currency
                    context = text[max(0, match.start()-50):match.end()+20]
                    if '$' in context:
                        metrics.stamp_capacity_usd_m = value
                    else:
                        metrics.stamp_capacity_gbp_m = value
                    metrics.extraction_notes.append(f"Stamp capacity from full text search: {value}m")
                except (ValueError, IndexError):
                    pass
        
        # Look for capacity in different formats
        if not metrics.stamp_capacity_gbp_m and not metrics.stamp_capacity_usd_m:
            # Pattern: "Syndicate 1234 has capacity of £450m"
            cap_patterns = [
                re.compile(r'capacity\s+of\s+£([\d,]+(?:\.\d+)?)\s*m', re.IGNORECASE),
                re.compile(r'capacity[:\s]+£([\d,]+(?:\.\d+)?)\s*m', re.IGNORECASE),
                re.compile(r'£([\d,]+(?:\.\d+)?)\s*m(?:illion)?\s+capacity', re.IGNORECASE),
            ]
            for pattern in cap_patterns:
                match = pattern.search(text)
                if match:
                    try:
                        value = float(match.group(1).replace(',', ''))
                        metrics.stamp_capacity_gbp_m = value
                        metrics.extraction_notes.append(f"Stamp capacity (alt pattern): £{value}m")
                        break
                    except (ValueError, IndexError):
                        pass
        
        # Look for technical provisions in notes
        if not metrics.technical_provisions_gbp_m and not metrics.technical_provisions_usd_m:
            # Note section often has "Technical provisions" table
            note_match = re.search(
                r'(?:note|provision)[^£$]*(?:technical\s+provisions?|claims?\s+outstanding)[^£$]*'
                r'(?:£|\$)\s*([\d,]+(?:\.\d+)?)',
                text, re.IGNORECASE
            )
            if note_match:
                try:
                    value = float(note_match.group(1).replace(',', ''))
                    if value > 10000:
                        value = value / 1000
                    context = text[max(0, note_match.start()-20):note_match.end()+5]
                    if '$' in context:
                        metrics.technical_provisions_usd_m = value
                    else:
                        metrics.technical_provisions_gbp_m = value
                except (ValueError, IndexError):
                    pass
    
    def extract_table_data(self, text: str, metrics: SyndicateSizeMetrics):
        """
        Attempt to extract data from formatted tables.
        Lloyd's reports often have consistent table structures.
        """
        # Look for key financial summary tables
        # Pattern: metric name followed by numbers (possibly across years)
        
        table_patterns = [
            # "Gross written premium    423.7    398.2"
            (r'Gross\s+written\s+premium[s]?\s+([\d,]+(?:\.\d+)?)', 'gwp'),
            (r'Net\s+written\s+premium[s]?\s+([\d,]+(?:\.\d+)?)', 'nwp'),
            (r'Technical\s+provisions?\s+([\d,]+(?:\.\d+)?)', 'tp'),
            (r'Claims\s+outstanding\s+([\d,]+(?:\.\d+)?)', 'co'),
            (r'Stamp\s+capacity\s+([\d,]+(?:\.\d+)?)', 'cap'),
        ]
        
        for pattern_str, field_type in table_patterns:
            pattern = re.compile(pattern_str, re.IGNORECASE)
            matches = pattern.findall(text)
            if matches:
                try:
                    # Take first (current year) value
                    value = float(matches[0].replace(',', ''))
                    if value > 10000:
                        value = value / 1000
                    
                    if field_type == 'gwp' and not metrics.gross_written_premium_gbp_m:
                        if metrics.reporting_currency == "GBP":
                            metrics.gross_written_premium_gbp_m = value
                        else:
                            metrics.gross_written_premium_usd_m = value
                    elif field_type == 'nwp' and not metrics.net_written_premium_gbp_m:
                        if metrics.reporting_currency == "GBP":
                            metrics.net_written_premium_gbp_m = value
                        else:
                            metrics.net_written_premium_usd_m = value
                    elif field_type == 'tp' and not metrics.technical_provisions_gbp_m:
                        if metrics.reporting_currency == "GBP":
                            metrics.technical_provisions_gbp_m = value
                        else:
                            metrics.technical_provisions_usd_m = value
                    elif field_type == 'co' and not metrics.claims_outstanding_gbp_m:
                        if metrics.reporting_currency == "GBP":
                            metrics.claims_outstanding_gbp_m = value
                        else:
                            metrics.claims_outstanding_usd_m = value
                    elif field_type == 'cap' and not metrics.stamp_capacity_gbp_m:
                        if metrics.reporting_currency == "GBP":
                            metrics.stamp_capacity_gbp_m = value
                        else:
                            metrics.stamp_capacity_usd_m = value
                except (ValueError, IndexError):
                    pass
    
    def assess_confidence(self, metrics: SyndicateSizeMetrics):
        """Assess extraction confidence based on what was found."""
        score = 0
        
        # Weight by importance and reliability
        if metrics.technical_provisions_gbp_m or metrics.technical_provisions_usd_m:
            score += 3
        if metrics.claims_outstanding_gbp_m or metrics.claims_outstanding_usd_m:
            score += 2
        if metrics.stamp_capacity_gbp_m or metrics.stamp_capacity_usd_m:
            score += 2
        if metrics.gross_written_premium_gbp_m or metrics.gross_written_premium_usd_m:
            score += 1
        if metrics.combined_ratio_pct:
            score += 1
        
        if score >= 5:
            metrics.extraction_confidence = "high"
        elif score >= 2:
            metrics.extraction_confidence = "medium"
        else:
            metrics.extraction_confidence = "low"
    
    def extract_from_file(self, file_path: str, syndicate: int, year: int) -> SyndicateSizeMetrics:
        """Extract all metrics from a single file."""
        metrics = SyndicateSizeMetrics(
            syndicate=syndicate,
            year=year,
            source_file=file_path
        )
        
        # Extract text
        if file_path.lower().endswith('.pdf'):
            text, page_count = self.extract_text_from_pdf(file_path)
        elif file_path.lower().endswith(('.html', '.htm')):
            text, page_count = self.extract_text_from_html(file_path)
        else:
            metrics.extraction_notes.append(f"Unsupported file type: {file_path}")
            return metrics
        
        if not text:
            metrics.extraction_notes.append("Failed to extract text from file")
            return metrics
        
        metrics.pages_searched = page_count
        
        # Detect currency
        metrics.reporting_currency = self.detect_currency(text)
        
        # Extract from specific sections
        self.extract_from_strategic_report(text, metrics)
        self.extract_from_balance_sheet(text, metrics)
        self.extract_from_profit_loss(text, metrics)
        
        # Try table extraction
        self.extract_table_data(text, metrics)
        
        # Fallback to full text search
        self.extract_from_full_text(text, metrics)
        
        # Assess confidence
        self.assess_confidence(metrics)
        
        return metrics
    
    def parse_filename(self, filename: str) -> Tuple[Optional[int], Optional[int]]:
        """
        Parse syndicate number and year from filename.
        Expected format: syndicate_XXXX_YYYY.pdf
        """
        # Try standard format
        match = re.search(r'syndicate[_\s]*(\d+)[_\s]*(\d{4})', filename, re.IGNORECASE)
        if match:
            return int(match.group(1)), int(match.group(2))
        
        # Try alternate format: XXXX_YYYY.pdf
        match = re.search(r'(\d{3,4})[_\s]+(\d{4})', filename)
        if match:
            return int(match.group(1)), int(match.group(2))
        
        # Try to find any 4-digit year and 3-4 digit syndicate
        year_match = re.search(r'(20\d{2})', filename)
        synd_match = re.search(r'(\d{3,4})', filename)
        if year_match and synd_match:
            return int(synd_match.group(1)), int(year_match.group(1))
        
        return None, None
    
    def process_directory(self, pdf_dir: str) -> List[SyndicateSizeMetrics]:
        """Process all PDF files in directory."""
        pdf_path = Path(pdf_dir)
        if not pdf_path.exists():
            logger.error(f"Directory not found: {pdf_dir}")
            return []
        
        # Find all PDF and HTML files
        files = list(pdf_path.glob("*.pdf")) + list(pdf_path.glob("*.html"))
        logger.info(f"Found {len(files)} files to process")
        
        results = []
        
        for file_path in sorted(files):
            syndicate, year = self.parse_filename(file_path.name)
            
            if not syndicate or not year:
                logger.warning(f"Could not parse syndicate/year from: {file_path.name}")
                continue
            
            logger.info(f"Processing: Syndicate {syndicate} Year {year}")
            
            try:
                metrics = self.extract_from_file(str(file_path), syndicate, year)
                results.append(metrics)
                
                self.stats['total_processed'] += 1
                if metrics.has_size_data():
                    self.stats['successful_extractions'] += 1
                    
                    # Track which fields we extracted
                    if metrics.stamp_capacity_gbp_m or metrics.stamp_capacity_usd_m:
                        self.stats['metrics_by_field']['stamp_capacity'] += 1
                    if metrics.gross_written_premium_gbp_m or metrics.gross_written_premium_usd_m:
                        self.stats['metrics_by_field']['gross_written_premium'] += 1
                    if metrics.technical_provisions_gbp_m or metrics.technical_provisions_usd_m:
                        self.stats['metrics_by_field']['technical_provisions'] += 1
                    if metrics.claims_outstanding_gbp_m or metrics.claims_outstanding_usd_m:
                        self.stats['metrics_by_field']['claims_outstanding'] += 1
                else:
                    self.stats['failed_extractions'] += 1
                    
            except Exception as e:
                logger.error(f"Error processing {file_path}: {e}")
                self.stats['failed_extractions'] += 1
        
        return results
    
    def print_stats(self):
        """Print extraction statistics."""
        print("\n" + "=" * 60)
        print("EXTRACTION STATISTICS")
        print("=" * 60)
        print(f"Total files processed: {self.stats['total_processed']}")
        print(f"Successful extractions: {self.stats['successful_extractions']}")
        print(f"Failed extractions: {self.stats['failed_extractions']}")
        
        if self.stats['total_processed'] > 0:
            success_rate = self.stats['successful_extractions'] / self.stats['total_processed']
            print(f"Success rate: {success_rate:.1%}")
        
        print("\nMetrics extracted by field:")
        for field, count in sorted(self.stats['metrics_by_field'].items()):
            print(f"  {field}: {count}")
        print("=" * 60)


# =============================================================================
# Output Functions
# =============================================================================

def save_results(results: List[SyndicateSizeMetrics], output_path: str):
    """Save extraction results to JSON."""
    output = {
        'generated_at': __import__('datetime').datetime.now().isoformat(),
        'total_records': len(results),
        'records_with_size_data': sum(1 for r in results if r.has_size_data()),
        'metrics': [r.to_dict() for r in results]
    }
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2)
    
    logger.info(f"Results saved to: {output_path}")


def merge_with_corpus(size_metrics_path: str, corpus_path: str, output_path: str):
    """
    Merge size metrics into existing unified corpus.
    Creates enhanced corpus with size data joined by syndicate-year.
    """
    # Load size metrics
    with open(size_metrics_path, 'r') as f:
        size_data = json.load(f)
    
    # Create lookup by syndicate-year
    size_lookup = {}
    for m in size_data.get('metrics', []):
        key = (m['syndicate'], m['year'])
        if m.get('technical_provisions_gbp_m') or m.get('stamp_capacity_gbp_m'):
            size_lookup[key] = m
    
    logger.info(f"Loaded {len(size_lookup)} syndicate-years with size data")
    
    # Load corpus
    with open(corpus_path, 'r') as f:
        corpus = json.load(f)
    
    # Enhance movements with size data
    movements = corpus.get('movements', [])
    enhanced_count = 0
    
    for movement in movements:
        syndicate = movement.get('syndicate')
        year = movement.get('year')
        
        if syndicate and year:
            key = (syndicate, year)
            if key in size_lookup:
                size_info = size_lookup[key]
                
                # Add size fields to movement
                movement['prior_reserves_gbp_m'] = (
                    size_info.get('technical_provisions_gbp_m') or
                    size_info.get('claims_outstanding_gbp_m')
                )
                movement['stamp_capacity_gbp_m'] = size_info.get('stamp_capacity_gbp_m')
                movement['gross_premium_gbp_m'] = size_info.get('gross_written_premium_gbp_m')
                movement['reporting_currency'] = size_info.get('reporting_currency', 'GBP')
                
                # Calculate severity ratio if we have both movement and reserves
                if movement.get('amount_gbp_m') and movement.get('prior_reserves_gbp_m'):
                    amount = movement['amount_gbp_m']
                    reserves = movement['prior_reserves_gbp_m']
                    if reserves > 0:
                        # Adjust sign based on direction
                        if movement.get('direction') == 'strengthening':
                            movement['severity_ratio'] = amount / reserves
                        elif movement.get('direction') == 'release':
                            movement['severity_ratio'] = -amount / reserves
                
                enhanced_count += 1
    
    logger.info(f"Enhanced {enhanced_count} movements with size data")
    
    # Save enhanced corpus
    corpus['size_data_merged_at'] = __import__('datetime').datetime.now().isoformat()
    corpus['movements_with_size_data'] = enhanced_count
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(corpus, f, indent=2)
    
    logger.info(f"Enhanced corpus saved to: {output_path}")
    
    return enhanced_count


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Extract size metrics from Lloyd's syndicate annual reports"
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Commands')
    
    # Extract command
    extract_parser = subparsers.add_parser('extract', help='Extract metrics from PDFs')
    extract_parser.add_argument(
        '--pdf-dir', '-d',
        required=True,
        help='Directory containing syndicate PDF files'
    )
    extract_parser.add_argument(
        '--output', '-o',
        default='syndicate_size_metrics.json',
        help='Output JSON file path'
    )
    
    # Merge command
    merge_parser = subparsers.add_parser('merge', help='Merge metrics into corpus')
    merge_parser.add_argument(
        '--size-metrics', '-s',
        required=True,
        help='Path to syndicate_size_metrics.json'
    )
    merge_parser.add_argument(
        '--corpus', '-c',
        required=True,
        help='Path to unified_corpus.json'
    )
    merge_parser.add_argument(
        '--output', '-o',
        required=True,
        help='Output path for enhanced corpus'
    )
    
    # Single file command (for testing)
    single_parser = subparsers.add_parser('single', help='Extract from single file')
    single_parser.add_argument('file', help='Path to PDF file')
    single_parser.add_argument('--syndicate', '-s', type=int, help='Syndicate number')
    single_parser.add_argument('--year', '-y', type=int, help='Report year')
    
    args = parser.parse_args()
    
    if args.command == 'extract':
        extractor = SizeMetricsExtractor()
        results = extractor.process_directory(args.pdf_dir)
        save_results(results, args.output)
        extractor.print_stats()
        
    elif args.command == 'merge':
        count = merge_with_corpus(args.size_metrics, args.corpus, args.output)
        print(f"\nMerged size data for {count} movements")
        
    elif args.command == 'single':
        extractor = SizeMetricsExtractor()
        
        # Parse syndicate/year from filename if not provided
        syndicate = args.syndicate
        year = args.year
        if not syndicate or not year:
            syndicate, year = extractor.parse_filename(Path(args.file).name)
        
        if not syndicate or not year:
            print("Could not determine syndicate/year. Please provide --syndicate and --year")
            return
        
        metrics = extractor.extract_from_file(args.file, syndicate, year)
        
        print("\n" + "=" * 60)
        print(f"EXTRACTION RESULTS: Syndicate {syndicate} Year {year}")
        print("=" * 60)
        print(f"Reporting currency: {metrics.reporting_currency}")
        print(f"Extraction confidence: {metrics.extraction_confidence}")
        print(f"Pages searched: {metrics.pages_searched}")
        print()
        print("Size Metrics:")
        print(f"  Stamp capacity (GBP): {metrics.stamp_capacity_gbp_m}")
        print(f"  Stamp capacity (USD): {metrics.stamp_capacity_usd_m}")
        print(f"  GWP (GBP): {metrics.gross_written_premium_gbp_m}")
        print(f"  GWP (USD): {metrics.gross_written_premium_usd_m}")
        print(f"  Technical provisions (GBP): {metrics.technical_provisions_gbp_m}")
        print(f"  Technical provisions (USD): {metrics.technical_provisions_usd_m}")
        print(f"  Claims outstanding (GBP): {metrics.claims_outstanding_gbp_m}")
        print(f"  Claims outstanding (USD): {metrics.claims_outstanding_usd_m}")
        print()
        print(f"  Best size estimate (GBP m): {metrics.get_best_size_estimate()}")
        print()
        print("Ratios:")
        print(f"  Combined ratio: {metrics.combined_ratio_pct}%")
        print(f"  Claims ratio: {metrics.claims_ratio_pct}%")
        print()
        print("Extraction notes:")
        for note in metrics.extraction_notes:
            print(f"  - {note}")
        print("=" * 60)
        
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
