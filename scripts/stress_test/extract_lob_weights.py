"""
LOB Weight Extraction from Lloyd's Syndicate Reports
=====================================================

Extracts line of business (LOB) weights from syndicate annual reports.
These weights represent the actual portfolio mix by class of business,
derived from tables such as:
- Gross Written Premium by Class
- Net Earned Premium by Class  
- Technical Provisions by Segment
- Segmental Analysis
- Analysis of Underwriting Result

This is essential for proper LOB-level severity calculations.

Usage:
    python extract_lob_weights.py extract --pdf-dir syndicate_reports/pdf --output lob_weights.json
    python extract_lob_weights.py merge --lob-weights lob_weights.json --corpus unified_corpus.json --output enhanced_corpus.json
    python extract_lob_weights.py single --pdf path/to/report.pdf

Author: Colin Priest
Date: December 2024
"""

import json
import re
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field, asdict
from collections import defaultdict
import argparse

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# Try to import PDF libraries
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


# =============================================================================
# Standard LOB Categories (aligned with Lloyd's market reporting)
# =============================================================================

STANDARD_LOBS = [
    "Property",
    "Casualty", 
    "Marine",
    "Energy",
    "Motor",
    "Aviation",
    "Accident & Health",
    "Life",
    "Professional Lines",
    "Reinsurance - Property",
    "Reinsurance - Casualty",
    "Reinsurance - Specialty",
    "Cyber",
    "Aggregate",
]

# Mapping from various names found in reports to standard LOBs
LOB_MAPPING = {
    # Property variants
    "property": "Property",
    "property direct": "Property",
    "property d&f": "Property",
    "fire": "Property",
    "property and fire": "Property",
    "property & fire": "Property",
    "property treaty": "Reinsurance - Property",
    "property reinsurance": "Reinsurance - Property",
    "property ri": "Reinsurance - Property",
    "catastrophe": "Reinsurance - Property",
    "cat": "Reinsurance - Property",
    
    # Casualty variants
    "casualty": "Casualty",
    "casualty direct": "Casualty",
    "liability": "Casualty",
    "general liability": "Casualty",
    "casualty treaty": "Reinsurance - Casualty",
    "casualty reinsurance": "Reinsurance - Casualty",
    "casualty ri": "Reinsurance - Casualty",
    "us casualty": "Casualty",
    "uk casualty": "Casualty",
    "international casualty": "Casualty",
    
    # Marine variants
    "marine": "Marine",
    "marine hull": "Marine",
    "marine cargo": "Marine",
    "marine liability": "Marine",
    "marine direct": "Marine",
    "marine reinsurance": "Marine",
    "ocean marine": "Marine",
    "inland marine": "Marine",
    "yacht": "Marine",
    "specie": "Marine",
    
    # Energy variants
    "energy": "Energy",
    "energy offshore": "Energy",
    "energy onshore": "Energy",
    "upstream energy": "Energy",
    "downstream energy": "Energy",
    "power generation": "Energy",
    "oil and gas": "Energy",
    "oil & gas": "Energy",
    
    # Motor variants
    "motor": "Motor",
    "auto": "Motor",
    "automobile": "Motor",
    "commercial auto": "Motor",
    "personal auto": "Motor",
    "motor fleet": "Motor",
    
    # Aviation variants
    "aviation": "Aviation",
    "aerospace": "Aviation",
    "airline": "Aviation",
    "aviation hull": "Aviation",
    "aviation liability": "Aviation",
    "general aviation": "Aviation",
    "space": "Aviation",
    
    # A&H variants
    "accident & health": "Accident & Health",
    "accident and health": "Accident & Health",
    "a&h": "Accident & Health",
    "accident": "Accident & Health",
    "health": "Accident & Health",
    "personal accident": "Accident & Health",
    "medical": "Accident & Health",
    "travel": "Accident & Health",
    
    # Professional Lines variants
    "professional lines": "Professional Lines",
    "professional liability": "Professional Lines",
    "d&o": "Professional Lines",
    "directors and officers": "Professional Lines",
    "directors & officers": "Professional Lines",
    "e&o": "Professional Lines",
    "errors and omissions": "Professional Lines",
    "errors & omissions": "Professional Lines",
    "pi": "Professional Lines",
    "professional indemnity": "Professional Lines",
    "financial lines": "Professional Lines",
    "financial institutions": "Professional Lines",
    "management liability": "Professional Lines",
    
    # Reinsurance variants
    "reinsurance": "Reinsurance - Property",
    "treaty": "Reinsurance - Property",
    "treaty reinsurance": "Reinsurance - Property",
    "facultative": "Reinsurance - Property",
    "retrocession": "Reinsurance - Property",
    "specialty reinsurance": "Reinsurance - Specialty",
    
    # Cyber variants
    "cyber": "Cyber",
    "cyber liability": "Cyber",
    "technology": "Cyber",
    "tech e&o": "Cyber",
    
    # Life variants
    "life": "Life",
    "life insurance": "Life",
    
    # Other / Aggregate
    "other": "Aggregate",
    "miscellaneous": "Aggregate",
    "contingency": "Aggregate",
    "political risk": "Aggregate",
    "credit": "Aggregate",
    "surety": "Aggregate",
    "war": "Aggregate",
    "terrorism": "Aggregate",
}


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class LOBWeightExtraction:
    """Extracted LOB weights for a single syndicate-year."""
    syndicate: int
    year: int
    
    # LOB weights from different sources
    weights_by_gwp: Dict[str, float] = field(default_factory=dict)  # Gross Written Premium
    weights_by_nep: Dict[str, float] = field(default_factory=dict)  # Net Earned Premium
    weights_by_reserves: Dict[str, float] = field(default_factory=dict)  # Technical Provisions
    weights_by_capacity: Dict[str, float] = field(default_factory=dict)  # Stamp Capacity allocation
    
    # Best available weights (computed)
    best_weights: Dict[str, float] = field(default_factory=dict)
    weight_source: str = ""  # 'gwp', 'nep', 'reserves', 'capacity', 'none'
    
    # Raw extracted data (for debugging)
    raw_tables: List[Dict] = field(default_factory=list)
    
    # Metadata
    extraction_confidence: str = "low"  # high/medium/low
    extraction_notes: List[str] = field(default_factory=list)
    source_file: str = ""
    tables_found: int = 0
    
    def to_dict(self) -> Dict:
        return asdict(self)
    
    def has_weights(self) -> bool:
        return bool(self.best_weights)
    
    def compute_best_weights(self):
        """Select the best available LOB weights."""
        # Priority: GWP > NEP > Reserves > Capacity
        if self.weights_by_gwp:
            self.best_weights = self.weights_by_gwp.copy()
            self.weight_source = "gwp"
        elif self.weights_by_nep:
            self.best_weights = self.weights_by_nep.copy()
            self.weight_source = "nep"
        elif self.weights_by_reserves:
            self.best_weights = self.weights_by_reserves.copy()
            self.weight_source = "reserves"
        elif self.weights_by_capacity:
            self.best_weights = self.weights_by_capacity.copy()
            self.weight_source = "capacity"
        else:
            self.weight_source = "none"
        
        # Assess confidence
        if self.best_weights and len(self.best_weights) >= 2:
            total = sum(self.best_weights.values())
            if 0.95 <= total <= 1.05:
                self.extraction_confidence = "high"
            elif 0.8 <= total <= 1.2:
                self.extraction_confidence = "medium"
            else:
                self.extraction_confidence = "low"
        elif self.best_weights:
            self.extraction_confidence = "low"


# =============================================================================
# LOB Name Standardization
# =============================================================================

def standardize_lob_name(raw_name: str) -> str:
    """Map raw LOB/class name to standard Lloyd's category."""
    if not raw_name:
        return "Aggregate"
    
    # Clean the name
    normalized = raw_name.lower().strip()
    normalized = re.sub(r'[^\w\s&]', '', normalized)
    normalized = re.sub(r'\s+', ' ', normalized)
    
    # Direct lookup
    if normalized in LOB_MAPPING:
        return LOB_MAPPING[normalized]
    
    # Check if already standard
    for std_lob in STANDARD_LOBS:
        if std_lob.lower() == normalized:
            return std_lob
    
    # Partial matching
    for key, value in LOB_MAPPING.items():
        if key in normalized or normalized in key:
            return value
    
    # Keyword-based matching
    if any(kw in normalized for kw in ['property', 'fire', 'homeowner']):
        if 'reinsurance' in normalized or 'treaty' in normalized:
            return "Reinsurance - Property"
        return "Property"
    
    if any(kw in normalized for kw in ['casualty', 'liability', 'gl']):
        if 'reinsurance' in normalized or 'treaty' in normalized:
            return "Reinsurance - Casualty"
        return "Casualty"
    
    if any(kw in normalized for kw in ['marine', 'cargo', 'hull', 'yacht']):
        return "Marine"
    
    if any(kw in normalized for kw in ['motor', 'auto', 'vehicle']):
        return "Motor"
    
    if any(kw in normalized for kw in ['aviation', 'aerospace', 'airline']):
        return "Aviation"
    
    if any(kw in normalized for kw in ['energy', 'oil', 'gas', 'power']):
        return "Energy"
    
    if any(kw in normalized for kw in ['cyber', 'tech']):
        return "Cyber"
    
    if any(kw in normalized for kw in ['professional', 'd&o', 'e&o', 'indemnity']):
        return "Professional Lines"
    
    if any(kw in normalized for kw in ['accident', 'health', 'a&h', 'medical']):
        return "Accident & Health"
    
    if any(kw in normalized for kw in ['reinsurance', 'treaty', 'ri']):
        return "Reinsurance - Property"
    
    logger.debug(f"Could not map LOB '{raw_name}' to standard category")
    return "Aggregate"


# =============================================================================
# Table Extraction
# =============================================================================

class LOBTableExtractor:
    """Extracts LOB breakdown tables from PDF reports."""
    
    # Patterns to identify relevant tables
    TABLE_HEADER_PATTERNS = [
        re.compile(r'gross\s+written\s+premium', re.IGNORECASE),
        re.compile(r'net\s+(?:written|earned)\s+premium', re.IGNORECASE),
        re.compile(r'premium\s+by\s+(?:class|segment|line)', re.IGNORECASE),
        re.compile(r'(?:class|segment(?:al)?|line)\s+(?:of\s+business\s+)?analysis', re.IGNORECASE),
        re.compile(r'underwriting\s+result\s+by\s+(?:class|segment)', re.IGNORECASE),
        re.compile(r'technical\s+provisions?\s+by\s+(?:class|segment)', re.IGNORECASE),
        re.compile(r'claims?\s+(?:outstanding\s+)?by\s+(?:class|segment)', re.IGNORECASE),
        re.compile(r'capacity\s+by\s+(?:class|segment)', re.IGNORECASE),
    ]
    
    # Patterns to identify currency values
    VALUE_PATTERN = re.compile(r'[£$]?\s*([\d,]+(?:\.\d+)?)\s*(?:m|million)?', re.IGNORECASE)
    PERCENTAGE_PATTERN = re.compile(r'([\d.]+)\s*%')
    
    def __init__(self):
        self.use_pymupdf = HAS_PYMUPDF
        self.use_pdfplumber = HAS_PDFPLUMBER
        
        if not (self.use_pymupdf or self.use_pdfplumber):
            raise ImportError("Need either PyMuPDF (fitz) or pdfplumber for PDF extraction")
    
    def extract_from_pdf(self, pdf_path: str, syndicate: int, year: int) -> LOBWeightExtraction:
        """Extract LOB weights from a PDF report."""
        result = LOBWeightExtraction(syndicate=syndicate, year=year, source_file=pdf_path)
        
        try:
            if self.use_pdfplumber:
                self._extract_with_pdfplumber(pdf_path, result)
            elif self.use_pymupdf:
                self._extract_with_pymupdf(pdf_path, result)
        except Exception as e:
            result.extraction_notes.append(f"Extraction error: {str(e)}")
            logger.warning(f"Failed to extract from {pdf_path}: {e}")
        
        result.compute_best_weights()
        return result
    
    def _extract_with_pdfplumber(self, pdf_path: str, result: LOBWeightExtraction):
        """Extract using pdfplumber (better table detection)."""
        with pdfplumber.open(pdf_path) as pdf:
            for page_num, page in enumerate(pdf.pages):
                # Get page text to check for relevant sections
                text = page.extract_text() or ""
                
                # Check if this page might have LOB breakdown
                is_relevant = any(p.search(text) for p in self.TABLE_HEADER_PATTERNS)
                
                if not is_relevant:
                    continue
                
                # Extract tables from this page
                tables = page.extract_tables()
                
                for table in tables:
                    if not table or len(table) < 2:
                        continue
                    
                    parsed = self._parse_table(table, text)
                    if parsed:
                        result.raw_tables.append({
                            'page': page_num + 1,
                            'data': parsed
                        })
                        result.tables_found += 1
                        self._categorize_weights(parsed, result)
    
    def _extract_with_pymupdf(self, pdf_path: str, result: LOBWeightExtraction):
        """Extract using PyMuPDF (fallback)."""
        doc = fitz.open(pdf_path)
        
        for page_num in range(len(doc)):
            page = doc[page_num]
            text = page.get_text()
            
            # Check if this page might have LOB breakdown
            is_relevant = any(p.search(text) for p in self.TABLE_HEADER_PATTERNS)
            
            if not is_relevant:
                continue
            
            # Try to extract table-like structures
            # PyMuPDF doesn't have native table extraction, so we use text parsing
            tables = self._extract_tables_from_text(text)
            
            for table in tables:
                parsed = self._parse_table(table, text)
                if parsed:
                    result.raw_tables.append({
                        'page': page_num + 1,
                        'data': parsed
                    })
                    result.tables_found += 1
                    self._categorize_weights(parsed, result)
        
        doc.close()
    
    def _extract_tables_from_text(self, text: str) -> List[List[List[str]]]:
        """Extract table-like structures from text (fallback for PyMuPDF)."""
        tables = []
        lines = text.split('\n')
        
        current_table = []
        in_table = False
        
        for line in lines:
            # Check if line looks like a table row (multiple values)
            parts = re.split(r'\s{2,}|\t', line.strip())
            
            # Look for lines with LOB names and numbers
            has_lob = any(standardize_lob_name(p) != "Aggregate" or p.lower() in LOB_MAPPING for p in parts if len(p) > 2)
            has_numbers = any(self.VALUE_PATTERN.search(p) for p in parts)
            
            if has_lob and has_numbers:
                in_table = True
                current_table.append(parts)
            elif in_table:
                # Check if this is a continuation or end of table
                if has_numbers or (len(parts) > 1 and any(p.strip() for p in parts)):
                    current_table.append(parts)
                else:
                    if len(current_table) >= 2:
                        tables.append(current_table)
                    current_table = []
                    in_table = False
        
        if current_table and len(current_table) >= 2:
            tables.append(current_table)
        
        return tables
    
    def _parse_table(self, table: List[List[str]], context: str) -> Optional[Dict[str, float]]:
        """Parse a table to extract LOB -> value mapping."""
        if not table or len(table) < 2:
            return None
        
        lob_values = {}
        
        for row in table:
            if not row:
                continue
            
            # Try to identify LOB name and value in this row
            lob_name = None
            value = None
            
            for cell in row:
                if not cell:
                    continue
                
                cell_str = str(cell).strip()
                
                # Check if this cell is a LOB name
                std_lob = standardize_lob_name(cell_str)
                if std_lob != "Aggregate" or cell_str.lower() in LOB_MAPPING:
                    lob_name = std_lob
                    continue
                
                # Check if this cell is a value
                if value is None:
                    # Try percentage first
                    pct_match = self.PERCENTAGE_PATTERN.search(cell_str)
                    if pct_match:
                        value = float(pct_match.group(1)) / 100
                        continue
                    
                    # Try currency value
                    val_match = self.VALUE_PATTERN.search(cell_str)
                    if val_match:
                        try:
                            value = float(val_match.group(1).replace(',', ''))
                        except ValueError:
                            pass
            
            if lob_name and value is not None and value > 0:
                # Aggregate values for same LOB
                if lob_name in lob_values:
                    lob_values[lob_name] += value
                else:
                    lob_values[lob_name] = value
        
        if not lob_values or len(lob_values) < 2:
            return None
        
        # Convert to weights if values are absolute (not percentages)
        total = sum(lob_values.values())
        if total > 2:  # Likely absolute values, not percentages
            lob_values = {k: v / total for k, v in lob_values.items()}
        elif total < 0.5:  # Likely needs scaling
            lob_values = {k: v / total for k, v in lob_values.items()}
        
        return lob_values
    
    def _categorize_weights(self, weights: Dict[str, float], result: LOBWeightExtraction):
        """Categorize extracted weights by source type."""
        # For now, just add to GWP (most common source)
        # Could be enhanced to detect source from context
        if not result.weights_by_gwp:
            result.weights_by_gwp = weights.copy()
        else:
            # Merge (prefer existing)
            for lob, weight in weights.items():
                if lob not in result.weights_by_gwp:
                    result.weights_by_gwp[lob] = weight


# =============================================================================
# Alternative: Text-based extraction
# =============================================================================

class TextBasedLOBExtractor:
    """
    Extract LOB weights from text when table extraction fails.
    Handles Lloyd's standard formats including:
    - Segmental Analysis tables
    - Premium by class tables
    - "Property 45%, Casualty 30%, Marine 25%"
    - "Property £45m, Casualty £30m"
    """
    
    # Pattern to find LOB with percentage or value
    LOB_VALUE_PATTERN = re.compile(
        r'(property|casualty|marine|energy|motor|aviation|'
        r'accident\s*&?\s*health|professional\s+lines?|'
        r'reinsurance|cyber|liability|d&o|e&o|pi|'
        r'fire|hull|cargo|treaty|direct)'
        r'[^£$%\d]*'
        r'(?:£|\$)?\s*([\d,]+(?:\.\d+)?)\s*(?:m(?:illion)?|%)?',
        re.IGNORECASE
    )
    
    # Lloyd's standard segmental analysis class names
    # Note: More specific patterns should come before general ones
    # Avoid patterns that match column headers like "Reinsurance balance"
    SEGMENTAL_CLASSES = {
        'accident and health': 'Accident & Health',
        'motor (other classes)': 'Motor',
        'marine aviation and transport': 'Marine',  # Combined class
        'marine, aviation and transport': 'Marine',
        'fire and other damage to property': 'Property',
        'fire and other damage': 'Property',
        'third party liability': 'Casualty',
        'third-party liability': 'Casualty',
        'pecuniary loss': 'Professional Lines',
        'reinsurance acceptances': 'Reinsurance - Property',
        'other': 'Aggregate',
        'miscellaneous': 'Aggregate',
        'life': 'Life',
        # Note: Removed generic patterns like 'reinsurance', 'motor', 'property', 'liability'
        # as they match column headers
    }
    
    def extract_from_text(self, text: str, syndicate: int, year: int) -> LOBWeightExtraction:
        """Extract LOB weights from document text."""
        result = LOBWeightExtraction(syndicate=syndicate, year=year)
        
        # Try segmental analysis extraction first
        segmental_weights = self._extract_segmental_analysis(text)
        if segmental_weights:
            result.weights_by_gwp = segmental_weights
            result.extraction_notes.append("Extracted from Segmental Analysis")
            result.compute_best_weights()
            return result
        
        # Fall back to pattern matching
        matches = self.LOB_VALUE_PATTERN.findall(text)
        
        if not matches:
            return result
        
        lob_values = defaultdict(float)
        
        for lob_raw, value_str in matches:
            lob = standardize_lob_name(lob_raw)
            try:
                value = float(value_str.replace(',', ''))
                lob_values[lob] += value
            except ValueError:
                continue
        
        if len(lob_values) < 2:
            return result
        
        # Convert to weights
        total = sum(lob_values.values())
        if total > 0:
            weights = {k: v / total for k, v in lob_values.items()}
            result.weights_by_gwp = weights
            result.extraction_notes.append("Extracted from text patterns")
        
        result.compute_best_weights()
        return result
    
    def _extract_segmental_analysis(self, text: str) -> Optional[Dict[str, float]]:
        """
        Extract LOB weights from Lloyd's standard Segmental Analysis section.
        
        Handles PDF text where class names and values are on separate lines:
        Line N:   'Accident and health'
        Line N+1: '(14)'
        Line N+2: '(14)'
        ...
        """
        # Find the actual Note 4 SEGMENTAL ANALYSIS section
        segmental_match = re.search(
            r'(?:^|\n)\s*4\s*\n?\s*SEGMENTAL\s+ANALYSIS',
            text,
            re.IGNORECASE | re.MULTILINE
        )
        
        if not segmental_match:
            segmental_match = re.search(
                r'NOTE\s+4[:\s]+SEGMENTAL\s+ANALYSIS',
                text,
                re.IGNORECASE
            )
        
        if not segmental_match:
            return None
        
        # Get text after the header
        start_pos = segmental_match.end()
        section_text = text[start_pos:start_pos + 2500]  # Limit to ~2500 chars to stay in Note 4
        
        lines = section_text.split('\n')
        lob_values = {}
        
        # Find where data starts: after the FIRST set of £000's lines
        # Pattern is: header rows, then £000's rows (6 columns), then data
        data_start = 0
        found_first_pounds = False
        for i, line in enumerate(lines):
            if "000" in line and "£" in line:
                found_first_pounds = True
            elif found_first_pounds and "000" not in line:
                # First line after £000's block
                data_start = i
                break
        
        if not found_first_pounds:
            return None
        
        i = data_start
        while i < len(lines):
            line = lines[i].strip()
            
            # Skip empty lines
            if not line:
                i += 1
                continue
            
            # Stop at data Total row (has numbers after it)
            if line.lower() == 'total':
                if i + 1 < len(lines):
                    next_line = lines[i + 1].strip()
                    if re.match(r'^[\d,\(\)\-]+$', next_line):
                        break
                i += 1
                continue
            
            # Skip any remaining header-like lines
            if any(h in line.lower() for h in ['£000', 'premiums', 'claims', 'expenses']):
                i += 1
                continue
            
            line_lower = line.lower()
            
            # Check for multi-line class name (e.g., "Marine aviation and" + "transport")
            combined_line = line
            if i + 1 < len(lines):
                next_line = lines[i + 1].strip()
                # If next line is NOT a number/dash, it might be continuation
                if next_line and not re.match(r'^[\d\(\)\-\—,.\s£$]+$', next_line) and len(next_line) < 20:
                    combined_lower = (line + ' ' + next_line).lower()
                    for class_pattern in self.SEGMENTAL_CLASSES.keys():
                        if combined_lower.startswith(class_pattern):
                            combined_line = line + ' ' + next_line
                            i += 1
                            break
            
            line_lower = combined_line.lower()
            
            # Try to match against known class names
            matched_lob = None
            for class_pattern, std_lob in self.SEGMENTAL_CLASSES.items():
                if line_lower.startswith(class_pattern):
                    matched_lob = std_lob
                    break
            
            if matched_lob:
                # Find the first numeric value in subsequent lines (Gross premiums written column)
                value = None
                for j in range(1, 8):
                    if i + j >= len(lines):
                        break
                    num_line = lines[i + j].strip()
                    num_line_lower = num_line.lower()
                    
                    # Stop if we hit another class name (including partial multi-line ones)
                    # Check both full patterns and first-word patterns
                    is_another_class = any(num_line_lower.startswith(cp) for cp in self.SEGMENTAL_CLASSES.keys())
                    # Also check for starts of multi-line class names
                    if num_line_lower.startswith('marine') or num_line_lower.startswith('fire') or \
                       num_line_lower.startswith('third') or num_line_lower.startswith('reinsurance'):
                        is_another_class = True
                    
                    if is_another_class:
                        break
                    
                    if num_line in ['—', '-', '']:
                        continue
                    
                    # Match number with optional parentheses
                    num_match = re.match(r'^\(?([\d,]+)\)?$', num_line)
                    if num_match:
                        try:
                            value = float(num_match.group(1).replace(',', ''))
                            break
                        except ValueError:
                            continue
                
                if value is not None and value > 0:
                    if matched_lob in lob_values:
                        lob_values[matched_lob] += value
                    else:
                        lob_values[matched_lob] = value
            
            i += 1
        
        if len(lob_values) < 2:
            return None
        
        # Convert to weights
        total = sum(lob_values.values())
        if total <= 0:
            return None
        
        weights = {k: v / total for k, v in lob_values.items()}
        
        return weights


# =============================================================================
# Main Extraction Pipeline
# =============================================================================

class LOBWeightPipeline:
    """Main pipeline for extracting LOB weights from syndicate reports."""
    
    def __init__(self):
        self.table_extractor = LOBTableExtractor()
        self.text_extractor = TextBasedLOBExtractor()
    
    def extract_from_directory(self, pdf_dir: str, output_path: str) -> Dict[str, Any]:
        """Extract LOB weights from all PDFs in directory."""
        pdf_dir = Path(pdf_dir)
        results = {}
        stats = {
            'total_files': 0,
            'successful': 0,
            'failed': 0,
            'by_confidence': defaultdict(int)
        }
        
        pdf_files = list(pdf_dir.glob('*.pdf'))
        logger.info(f"Found {len(pdf_files)} PDF files")
        
        for pdf_path in pdf_files:
            stats['total_files'] += 1
            
            # Parse syndicate and year from filename
            syndicate, year = self._parse_filename(pdf_path.name)
            if syndicate is None or year is None:
                logger.warning(f"Could not parse syndicate/year from {pdf_path.name}")
                stats['failed'] += 1
                continue
            
            # Extract
            try:
                result = self.table_extractor.extract_from_pdf(str(pdf_path), syndicate, year)
                
                # If table extraction failed, try text-based
                if not result.has_weights():
                    with open(pdf_path, 'rb') as f:
                        if HAS_PYMUPDF:
                            doc = fitz.open(pdf_path)
                            text = ""
                            for page in doc:
                                text += page.get_text()
                            doc.close()
                        elif HAS_PDFPLUMBER:
                            with pdfplumber.open(pdf_path) as pdf:
                                text = "\n".join(page.extract_text() or "" for page in pdf.pages)
                        else:
                            text = ""
                    
                    if text:
                        text_result = self.text_extractor.extract_from_text(text, syndicate, year)
                        if text_result.has_weights():
                            result = text_result
                
                key = f"{syndicate}_{year}"
                results[key] = result.to_dict()
                
                if result.has_weights():
                    stats['successful'] += 1
                    stats['by_confidence'][result.extraction_confidence] += 1
                else:
                    stats['failed'] += 1
                
                if stats['total_files'] % 50 == 0:
                    logger.info(f"Processed {stats['total_files']} files...")
                    
            except Exception as e:
                logger.error(f"Error processing {pdf_path}: {e}")
                stats['failed'] += 1
        
        # Save results
        output_data = {
            'extractions': results,
            'stats': dict(stats)
        }
        
        with open(output_path, 'w') as f:
            json.dump(output_data, f, indent=2)
        
        logger.info(f"\nExtraction complete:")
        logger.info(f"  Total files: {stats['total_files']}")
        logger.info(f"  Successful: {stats['successful']}")
        logger.info(f"  Failed: {stats['failed']}")
        logger.info(f"  By confidence: {dict(stats['by_confidence'])}")
        logger.info(f"  Saved to: {output_path}")
        
        return output_data
    
    def _parse_filename(self, filename: str) -> Tuple[Optional[int], Optional[int]]:
        """Parse syndicate number and year from filename."""
        # Pattern: syndicate_1234_2023.pdf
        match = re.search(r'syndicate[_\s]*(\d+)[_\s]*(\d{4})', filename, re.IGNORECASE)
        if match:
            return int(match.group(1)), int(match.group(2))
        
        # Pattern: syn_1234_2023.pdf
        match = re.search(r'syn[_\s]*(\d+)[_\s]*(\d{4})', filename, re.IGNORECASE)
        if match:
            return int(match.group(1)), int(match.group(2))
        
        # Pattern: 1234_2023.pdf
        match = re.search(r'(\d{3,4})[_\s]*(\d{4})', filename)
        if match:
            return int(match.group(1)), int(match.group(2))
        
        return None, None
    
    def merge_with_corpus(self, lob_weights_path: str, corpus_path: str, output_path: str) -> Dict[str, Any]:
        """Merge extracted LOB weights into corpus."""
        
        # Load LOB weights
        with open(lob_weights_path, 'r') as f:
            lob_data = json.load(f)
        
        extractions = lob_data.get('extractions', {})
        logger.info(f"Loaded {len(extractions)} LOB weight extractions")
        
        # Load corpus
        with open(corpus_path, 'r') as f:
            corpus = json.load(f)
        
        movements = corpus.get('movements', [])
        logger.info(f"Loaded {len(movements)} movements from corpus")
        
        # Create lookup by syndicate-year
        weights_lookup = {}
        for key, extraction in extractions.items():
            best_weights = extraction.get('best_weights', {})
            if best_weights:
                syndicate = extraction.get('syndicate')
                year = extraction.get('year')
                if syndicate and year:
                    weights_lookup[(str(syndicate), int(year))] = {
                        'weights': best_weights,
                        'source': extraction.get('weight_source', 'unknown'),
                        'confidence': extraction.get('extraction_confidence', 'low')
                    }
        
        logger.info(f"Found {len(weights_lookup)} syndicate-years with LOB weights")
        
        # Merge into movements
        enhanced_count = 0
        for m in movements:
            syndicate = str(m.get('syndicate', ''))
            year = m.get('year')
            
            if not syndicate or not year:
                continue
            
            key = (syndicate, int(year))
            if key in weights_lookup:
                weight_data = weights_lookup[key]
                m['lob_weights'] = weight_data['weights']
                m['lob_weights_source'] = weight_data['source']
                m['lob_weights_confidence'] = weight_data['confidence']
                
                # Compute LOB-specific reserves if we have total reserves
                total_reserves = (
                    m.get('prior_reserves_gbp_m') or
                    m.get('technical_provisions_gbp_m') or
                    m.get('claims_outstanding_gbp_m')
                )
                
                if total_reserves:
                    lob = m.get('line_of_business', 'Aggregate')
                    lob_weight = weight_data['weights'].get(lob, 0)
                    
                    if lob_weight > 0:
                        m['lob_reserves_gbp_m'] = total_reserves * lob_weight
                        m['lob_weight'] = lob_weight
                        
                        # Compute proper LOB-level severity
                        movement = m.get('amount_gbp_m')
                        if movement is not None:
                            lob_reserves = m['lob_reserves_gbp_m']
                            direction = m.get('direction', 'mixed')
                            
                            if direction == 'release':
                                signed_movement = -abs(movement)
                            elif direction == 'strengthening':
                                signed_movement = abs(movement)
                            else:
                                signed_movement = movement
                            
                            m['lob_severity_ratio'] = signed_movement / lob_reserves
                
                enhanced_count += 1
        
        logger.info(f"Enhanced {enhanced_count} movements with LOB weights")
        
        # Save enhanced corpus
        corpus['movements'] = movements
        corpus['lob_weights_merged'] = True
        corpus['lob_weights_count'] = enhanced_count
        
        with open(output_path, 'w') as f:
            json.dump(corpus, f, indent=2)
        
        logger.info(f"Saved enhanced corpus to {output_path}")
        
        return {
            'movements_total': len(movements),
            'movements_enhanced': enhanced_count,
            'syndicate_years_with_weights': len(weights_lookup)
        }


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="Extract LOB weights from Lloyd's syndicate reports")
    subparsers = parser.add_subparsers(dest='command', help='Commands')
    
    # Extract command
    extract_parser = subparsers.add_parser('extract', help='Extract LOB weights from PDFs')
    extract_parser.add_argument('--pdf-dir', '-p', required=True, help='Directory containing syndicate PDFs')
    extract_parser.add_argument('--output', '-o', default='lob_weights.json', help='Output JSON file')
    
    # Merge command
    merge_parser = subparsers.add_parser('merge', help='Merge LOB weights into corpus')
    merge_parser.add_argument('--lob-weights', '-l', required=True, help='LOB weights JSON file')
    merge_parser.add_argument('--corpus', '-c', required=True, help='Corpus JSON file')
    merge_parser.add_argument('--output', '-o', required=True, help='Output enhanced corpus file')
    
    # Single file command
    single_parser = subparsers.add_parser('single', help='Extract from single PDF')
    single_parser.add_argument('--pdf', '-p', required=True, help='PDF file path')
    single_parser.add_argument('--syndicate', '-s', type=int, help='Syndicate number (if not in filename)')
    single_parser.add_argument('--year', '-y', type=int, help='Year (if not in filename)')
    
    args = parser.parse_args()
    
    if args.command == 'extract':
        pipeline = LOBWeightPipeline()
        pipeline.extract_from_directory(args.pdf_dir, args.output)
        
    elif args.command == 'merge':
        pipeline = LOBWeightPipeline()
        result = pipeline.merge_with_corpus(args.lob_weights, args.corpus, args.output)
        print(f"\nMerge complete:")
        print(f"  Total movements: {result['movements_total']}")
        print(f"  Enhanced: {result['movements_enhanced']}")
        print(f"  Syndicate-years with weights: {result['syndicate_years_with_weights']}")
        
    elif args.command == 'single':
        extractor = LOBTableExtractor()
        text_extractor = TextBasedLOBExtractor()
        
        # Get syndicate/year
        syndicate = args.syndicate
        year = args.year
        
        if syndicate is None or year is None:
            pipeline = LOBWeightPipeline()
            syndicate, year = pipeline._parse_filename(Path(args.pdf).name)
        
        if syndicate is None:
            syndicate = 0
        if year is None:
            year = 0
        
        # Try table extraction first
        result = extractor.extract_from_pdf(args.pdf, syndicate, year)
        
        # If table extraction failed, try text-based extraction
        if not result.has_weights():
            try:
                if HAS_PYMUPDF:
                    import fitz
                    doc = fitz.open(args.pdf)
                    text = ""
                    for page in doc:
                        text += page.get_text()
                    doc.close()
                elif HAS_PDFPLUMBER:
                    import pdfplumber
                    with pdfplumber.open(args.pdf) as pdf:
                        text = "\n".join(page.extract_text() or "" for page in pdf.pages)
                else:
                    text = ""
                
                if text:
                    text_result = text_extractor.extract_from_text(text, syndicate, year)
                    if text_result.has_weights():
                        result = text_result
                        result.extraction_notes.append("Used text-based extraction (table extraction failed)")
            except Exception as e:
                result.extraction_notes.append(f"Text extraction also failed: {e}")
        
        print(f"\nExtraction result for {args.pdf}:")
        print(f"  Syndicate: {result.syndicate}")
        print(f"  Year: {result.year}")
        print(f"  Tables found: {result.tables_found}")
        print(f"  Has weights: {result.has_weights()}")
        print(f"  Weight source: {result.weight_source}")
        print(f"  Confidence: {result.extraction_confidence}")
        
        if result.best_weights:
            print(f"\n  LOB Weights:")
            for lob, weight in sorted(result.best_weights.items(), key=lambda x: -x[1]):
                print(f"    {lob}: {weight:.1%}")
        
        if result.extraction_notes:
            print(f"\n  Notes: {result.extraction_notes}")
    
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
