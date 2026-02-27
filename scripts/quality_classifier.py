#!/usr/bin/env python3
"""
Lloyd's Reserve Commentary Quality Classifier
==============================================
Analyzes extracted text from syndicate reports and classifies the quality
of reserve movement commentary as VERY_HIGH, HIGH, MEDIUM, or LOW.

Quality Criteria:
- VERY_HIGH: Clear split by line of business WITH clear causal descriptions
             (e.g., "Marine: £36.1m release due to favourable large loss experience")
- HIGH: Split by line of business, but lacking clarity on root causes
        (e.g., "Marine: £36.1m release" with division breakdown but generic explanation)
- MEDIUM: Some reserve commentary with direction/amounts but no clear LoB breakdown
- LOW: Minimal commentary, boilerplate text, or extraction failed

Key indicators for classification:
1. Line of business breakdown (primary factor for HIGH/VERY_HIGH)
2. Quantified movements by class (£m per division)
3. Causal explanations (differentiates VERY_HIGH from HIGH)
4. Specific root cause terms (catastrophe, attritional, inflation, etc.)

Note: Causal descriptions will be supplemented with annual market commentaries,
so lack of specific causes does not rule out a report - LoB breakdown is key.
"""

import os
import re
import json
import logging
from pathlib import Path
from dataclasses import dataclass, asdict, field
from typing import Optional, List, Dict, Tuple
from collections import defaultdict

# Try PDF extraction libraries
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

# OCR support for scanned PDFs
try:
    import pytesseract
    from pdf2image import convert_from_path
    HAS_OCR = True

    # Auto-detect Tesseract in conda environment
    tesseract_found = False
    script_dir = Path(__file__).parent

    # Try CONDA_PREFIX first
    conda_prefix = os.environ.get('CONDA_PREFIX', '')
    if conda_prefix:
        tesseract_path = os.path.join(conda_prefix, 'Library', 'bin', 'tesseract.exe')
        tessdata_path = os.path.join(conda_prefix, 'share', 'tessdata')
        if os.path.exists(tesseract_path):
            pytesseract.pytesseract.tesseract_cmd = tesseract_path
            if os.path.exists(tessdata_path):
                os.environ['TESSDATA_PREFIX'] = tessdata_path  # Process-local only
            tesseract_found = True

    # Fallback: check common conda locations relative to script
    if not tesseract_found:
        conda_configs = [
            (script_dir / '.conda' / 'Library' / 'bin' / 'tesseract.exe',
             script_dir / '.conda' / 'share' / 'tessdata'),
            (Path(r'C:\Program Files\Tesseract-OCR\tesseract.exe'),
             Path(r'C:\Program Files\Tesseract-OCR\tessdata')),
        ]
        for tesseract_path, tessdata_path in conda_configs:
            if tesseract_path.exists():
                pytesseract.pytesseract.tesseract_cmd = str(tesseract_path)
                if tessdata_path.exists():
                    os.environ['TESSDATA_PREFIX'] = str(tessdata_path)  # Process-local only
                tesseract_found = True
                break

except ImportError:
    HAS_OCR = False


logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


# Lloyd's regulatory class categories
INSURANCE_CLASSES = [
    'marine', 'aviation', 'transport', 'property', 'fire', 'damage',
    'third party liability', 'liability', 'casualty', 'motor', 
    'accident', 'health', 'miscellaneous', 'reinsurance', 'pecuniary loss',
    'credit', 'guarantee', 'legal expenses'
]

# Causal explanation indicators
CAUSAL_INDICATORS = [
    'favourable', 'favorable', 'adverse', 'positive', 'negative',
    'experience', 'development', 'emergence', 'deterioration', 'improvement',
    'driven by', 'due to', 'primarily', 'mainly', 'resulted from', 'as a result',
    'reflecting', 'arising from', 'attributable to', 'caused by',
    'ibnr', 'incurred but not reported', 'case reserves', 'redundancy',
    'strengthening', 'release', 'surplus', 'deficit', 'shortfall',
    'better than expected', 'worse than expected', 'exceed', 'below',
    'claims development', 'loss development', 'reserve movement'
]

# Movement direction indicators
DIRECTION_INDICATORS = {
    'positive': ['release', 'surplus', 'favourable', 'favorable', 'better', 'positive', 
                 'reduction', 'redundancy', 'profit'],
    'negative': ['strengthening', 'deficit', 'adverse', 'deterioration', 'worse', 
                 'negative', 'increase', 'shortfall', 'loss']
}

# Section title patterns for reserve commentary (Notes to Financial Statements)
RESERVE_SECTION_PATTERNS = [
    r'movement in prior year.*provision',
    r'prior year.*provision.*claims',
    r'claims development',
    r'reserve.*movement',
    r'prior.*year.*reserve',
    r'changes in.*provision',
    r'technical provisions',
    r'note.*claims outstanding',
    # New patterns for better extraction
    r'claims\s+incurred',                           # Claims incurred sections
    r'large\s+loss(?:es)?',                         # Large losses sections
    r'significant\s+(?:claims|events|losses)',      # Significant events
    r'(?:net|gross)\s+claims\s+(?:incurred|ratio)', # Claims ratio sections
    r'prior\s+year\s+(?:surplus|deficit)',          # Prior year results
    r'run[- ]?off\s+(?:result|business)',           # Run-off sections
]

# Strategic Report section patterns (contains more detailed narrative)
STRATEGIC_REPORT_PATTERNS = [
    r'strategic report',
    r'managing agent.{0,20}report',
    r'report of the directors',
    r'business review',
    r'underwriting review',
    r'claims review',
    r'prior year development',
    r'prior year releases',
    r'reserve releases',
    # New patterns for better extraction
    r'claims\s+incurred',                           # Claims incurred in directors report
    r'large\s+loss(?:es)?',                         # Large losses narrative
    r'catastroph(?:e|ic)\s+(?:events?|losses?)',    # Catastrophe sections
    r'year\s+of\s+account',                         # Year of account analysis
    r'(?:2\d{3})\s+year\s+of\s+account',            # Specific YoA (e.g., "2012 year of account")
    r'notable\s+(?:claims|events|losses)',          # Notable events
    r'major\s+(?:claims|losses|events)',            # Major claims
    r'review\s+of\s+(?:the\s+)?business',           # Review of business section
    r'underwriting\s+result',                       # Underwriting results
]

# Specific root cause indicators (more informative than generic "favourable development")
SPECIFIC_CAUSAL_TERMS = [
    # Catastrophe events
    'catastrophe', 'cat loss', 'nat cat', 'natural catastrophe',
    'hurricane', 'typhoon', 'cyclone', 'flood', 'earthquake', 'wildfire', 'hailstorm',
    # Specific named events
    'covid', 'pandemic', 'ukraine', 'russia',
    # Claims-specific causes
    'attritional', 'large loss', 'severity', 'frequency',
    'litigation', 'legal', 'court', 'settlement', 'verdict',
    'asbestos', 'latent', 'abuse', 'pollution', 'environmental',
    # Economic/regulatory factors
    'inflation', 'social inflation', 'economic inflation',
    'ogden', 'discount rate', 'ppwo',
    # Reserving actions
    'redundancy', 'commutation', 'run-off', 'closure',
    'ibnr reduction', 'case reserve',
]


@dataclass
class QualityAssessment:
    """Assessment result for a single report."""
    syndicate: int
    year: int
    quality: str  # HIGH, MEDIUM, LOW, or ERROR
    confidence: float  # 0-1

    # Evidence
    has_dedicated_section: bool = False
    has_strategic_report: bool = False
    class_breakdown_found: bool = False
    causal_language_found: bool = False
    quantified_movements: bool = False
    has_specific_causes: bool = False  # True if specific root cause terms found

    # Extracted content
    reserve_section_text: str = ""
    strategic_report_text: str = ""  # Narrative from Strategic Report
    large_loss_section_text: str = ""  # Sections about large losses and events
    classes_mentioned: List[str] = field(default_factory=list)
    causal_phrases: List[str] = field(default_factory=list)
    monetary_amounts: List[str] = field(default_factory=list)
    specific_causal_terms: List[str] = field(default_factory=list)  # Specific root causes found

    # Metadata
    file_path: str = ""
    total_pages: int = 0
    extraction_method: str = ""
    error: Optional[str] = None

    def to_dict(self) -> Dict:
        return asdict(self)


class ReserveCommentaryClassifier:
    """Classifies quality of reserve commentary in Lloyd's syndicate reports."""

    def __init__(self, ocr_cache_path: str = None):
        """
        Initialize classifier.

        Args:
            ocr_cache_path: Path to OCR cache JSON file (from ocr_scanned_pdfs.py).
                           If provided, cached OCR text will be used for scanned PDFs.
        """
        # Compile regex patterns
        self.section_patterns = [re.compile(p, re.IGNORECASE) for p in RESERVE_SECTION_PATTERNS]
        self.strategic_patterns = [re.compile(p, re.IGNORECASE) for p in STRATEGIC_REPORT_PATTERNS]
        self.amount_pattern = re.compile(r'[$£€][\d,]+(?:\.\d+)?(?:\s*(?:m|million|k|thousand|bn|billion))?', re.IGNORECASE)

        # Load OCR cache if provided
        self.ocr_cache = {}
        if ocr_cache_path and os.path.exists(ocr_cache_path):
            try:
                with open(ocr_cache_path, 'r') as f:
                    self.ocr_cache = json.load(f)
                logger.info(f"Loaded OCR cache with {len(self.ocr_cache)} entries")
            except Exception as e:
                logger.warning(f"Failed to load OCR cache: {e}")
        
    def extract_text_from_pdf(self, pdf_path: str, use_ocr: bool = True) -> Tuple[str, str, int]:
        """
        Extract text from PDF file.

        Args:
            pdf_path: Path to PDF file
            use_ocr: Whether to use OCR for scanned PDFs (default True)

        Returns (text, extraction_method, page_count)
        """
        text = ""
        page_count = 0
        method = "none"
        filename = os.path.basename(pdf_path)

        # Try PyMuPDF first (fastest)
        if HAS_PYMUPDF:
            try:
                doc = fitz.open(pdf_path)
                page_count = len(doc)
                for page in doc:
                    text += page.get_text()
                doc.close()
                method = "pymupdf"
            except Exception as e:
                logger.warning(f"PyMuPDF extraction failed: {e}")

        # Try pdfplumber if PyMuPDF yielded no text
        if not text.strip() and HAS_PDFPLUMBER:
            try:
                with pdfplumber.open(pdf_path) as pdf:
                    page_count = len(pdf.pages)
                    for page in pdf.pages:
                        page_text = page.extract_text()
                        if page_text:
                            text += page_text + "\n"
                    method = "pdfplumber"
            except Exception as e:
                logger.warning(f"pdfplumber extraction failed: {e}")

        # Use OCR cache or live OCR if text extraction yielded very little text (likely scanned PDF)
        if use_ocr and len(text.strip()) < 500:
            # First check OCR cache (much faster than live OCR)
            if filename in self.ocr_cache:
                cached = self.ocr_cache[filename]
                if cached.get('text') and cached.get('char_count', 0) > 0:
                    text = cached['text']
                    method = "ocr_cache"
                    logger.debug(f"Using cached OCR for {filename}")
            # Fall back to live OCR if available and no cache
            elif HAS_OCR:
                ocr_text, ocr_pages = self.extract_text_with_ocr(pdf_path)
                if ocr_text:
                    text = ocr_text
                    page_count = ocr_pages
                    method = "ocr"

        return text, method, page_count

    def extract_text_with_ocr(self, pdf_path: str, dpi: int = 200) -> Tuple[str, int]:
        """
        Extract text from PDF using OCR (for scanned documents).

        Args:
            pdf_path: Path to PDF file
            dpi: Resolution for PDF to image conversion (default 200)

        Returns (text, page_count)
        """
        if not HAS_OCR:
            logger.warning("OCR not available - install pytesseract and pdf2image")
            return "", 0

        try:
            logger.info(f"Running OCR on {pdf_path}...")
            # Convert PDF pages to images
            images = convert_from_path(pdf_path, dpi=dpi)

            text = ""
            for i, image in enumerate(images):
                # Run OCR on each page
                page_text = pytesseract.image_to_string(image, lang='eng')
                text += page_text + "\n"

                # Log progress for large documents
                if (i + 1) % 10 == 0:
                    logger.debug(f"OCR progress: {i + 1}/{len(images)} pages")

            logger.info(f"OCR complete: extracted {len(text)} chars from {len(images)} pages")
            return text, len(images)

        except Exception as e:
            logger.warning(f"OCR extraction failed: {e}")
            return "", 0
    
    def extract_text_from_html(self, html_path: str) -> Tuple[str, str, int]:
        """Extract text from HTML file (for 2024 iXBRL reports)."""
        try:
            from bs4 import BeautifulSoup
            with open(html_path, 'r', encoding='utf-8') as f:
                soup = BeautifulSoup(f.read(), 'html.parser')
                text = soup.get_text(separator='\n')
                return text, "html", 1
        except Exception as e:
            logger.warning(f"HTML extraction failed: {e}")
            return "", "none", 0
    
    def find_reserve_section(self, text: str) -> str:
        """
        Find and extract the reserve commentary section from the text.
        
        Looks for sections titled "Movement in Prior Year's Provision for Claims"
        or similar, typically in Notes to Financial Statements.
        """
        # Normalize text
        text_lower = text.lower()
        
        # Try each section pattern
        for pattern in self.section_patterns:
            match = pattern.search(text)
            if match:
                # Extract surrounding context (up to 6000 chars after match for full tables)
                start = max(0, match.start() - 300)
                end = min(len(text), match.end() + 6000)
                section = text[start:end]
                
                # Try to find section boundaries
                # Look for next "Note X" or section header
                next_note = re.search(r'\n\s*(?:Note\s+\d+|\d+\.\s+[A-Z])', section[500:])
                if next_note:
                    section = section[:500 + next_note.start()]
                
                return section
        
        # Fallback: search for key phrases
        for phrase in ['prior year', 'claims outstanding', 'reserve']:
            idx = text_lower.find(phrase)
            if idx > 0:
                start = max(0, idx - 200)
                end = min(len(text), idx + 2000)
                return text[start:end]

        return ""

    def find_strategic_report(self, text: str) -> str:
        """
        Find and extract reserve-related narrative from Strategic Report section.

        The Strategic Report/Managing Agent's Report typically contains more
        detailed explanations of reserve movements than the Notes section.
        """
        text_lower = text.lower()
        sections = []

        # Find Strategic Report section boundaries
        for pattern in self.strategic_patterns:
            for match in pattern.finditer(text):
                start = match.start()
                # Extract up to 8000 chars after match for more complete narratives
                end = min(len(text), start + 8000)
                section = text[start:end]

                # Look for end of section (next major heading or Notes)
                end_match = re.search(r'\n\s*(?:Notes to|Financial Statements|Statement of|Independent Auditor)', section[500:])
                if end_match:
                    section = section[:500 + end_match.start()]

                sections.append(section)

        if not sections:
            return ""

        # Combine all sections and look for reserve-related content
        combined = "\n".join(sections)

        # Extract paragraphs mentioning reserves, prior year, or claims
        reserve_paragraphs = []
        paragraphs = re.split(r'\n\s*\n', combined)

        for para in paragraphs:
            para_lower = para.lower()
            if any(term in para_lower for term in ['prior year', 'reserve', 'release', 'strengthen', 'claims ratio', 'loss ratio', 'attritional', 'catastrophe']):
                reserve_paragraphs.append(para.strip())

        return "\n\n".join(reserve_paragraphs[:10])  # Return up to 10 relevant paragraphs

    def find_large_loss_section(self, text: str) -> str:
        """
        Extract sections specifically about large losses and major events.

        These sections often contain named catastrophe events, specific claims,
        and other details that explain reserve movements.
        """
        patterns = [
            r'large\s+loss(?:es)?\s+(?:included|were|comprised|totall?(?:ed|ing))',
            r'significant\s+(?:claims|events|losses)\s+(?:included|were|during)',
            r'major\s+(?:claims|losses|events)',
            r'catastroph(?:e|ic)\s+(?:events?|losses?|claims?)',
            r'notable\s+(?:claims|events|losses)',
            r'(?:largest|major|significant)\s+(?:individual\s+)?(?:claims?|losses?)',
            r'(?:named\s+)?(?:storms?|hurricanes?|typhoons?|earthquakes?|wildfires?)',
            r'(?:man-made|man made)\s+(?:losses?|events?|catastrophe)',
            r'attritional\s+(?:claims?|losses?)',
            r'prior\s+year(?:s)?\s+(?:large\s+)?loss(?:es)?',
        ]

        sections = []
        for pattern in patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                # Get context around the match (200 chars before, 2000 chars after)
                start = max(0, match.start() - 200)
                end = min(len(text), match.end() + 2000)
                section = text[start:end]

                # Try to find sentence/paragraph boundaries
                # Look for paragraph break or next section
                para_end = re.search(r'\n\s*\n|\n\s*(?:\d+\.|[A-Z][a-z]+\s+[A-Z])', section[500:])
                if para_end:
                    section = section[:500 + para_end.start()]

                if section.strip() and section not in sections:
                    sections.append(section.strip())

        # Deduplicate overlapping sections
        unique_sections = []
        for section in sections:
            is_subset = False
            for existing in unique_sections:
                if section in existing or existing in section:
                    is_subset = True
                    # Keep the longer one
                    if len(section) > len(existing):
                        unique_sections.remove(existing)
                        unique_sections.append(section)
                    break
            if not is_subset:
                unique_sections.append(section)

        return "\n\n---\n\n".join(unique_sections[:8])  # Return up to 8 sections

    def extract_specific_causal_terms(self, text: str) -> List[str]:
        """
        Extract specific root cause terms from text.

        These indicate informative explanations beyond generic phrases
        like "favourable development".
        """
        text_lower = text.lower()
        found = []

        for term in SPECIFIC_CAUSAL_TERMS:
            if term in text_lower:
                found.append(term)

        return list(set(found))

    def extract_classes(self, text: str) -> List[str]:
        """Extract insurance class mentions from text."""
        text_lower = text.lower()
        found = []
        
        for cls in INSURANCE_CLASSES:
            if cls in text_lower:
                found.append(cls)
        
        return list(set(found))
    
    def extract_causal_phrases(self, text: str) -> List[str]:
        """Extract phrases containing causal language."""
        phrases = []
        text_lower = text.lower()
        
        # Split into sentences
        sentences = re.split(r'[.;]', text)
        
        for sentence in sentences:
            sentence_lower = sentence.lower()
            for indicator in CAUSAL_INDICATORS:
                if indicator in sentence_lower:
                    phrases.append(sentence.strip()[:200])  # Truncate long sentences
                    break
        
        return phrases[:10]  # Return up to 10 phrases
    
    def extract_monetary_amounts(self, text: str) -> List[str]:
        """Extract monetary amounts from text."""
        amounts = self.amount_pattern.findall(text)
        return amounts[:20]  # Return up to 20 amounts
    
    def classify_quality(self, assessment: QualityAssessment) -> str:
        """
        Determine quality classification based on evidence.

        Returns: 'VERY_HIGH', 'HIGH', 'MEDIUM', or 'LOW'

        Classification logic:
        - VERY_HIGH: Line of business breakdown + clear causal descriptions
        - HIGH: Line of business breakdown (causal clarity not required)
        - MEDIUM: Some reserve commentary but no clear LoB breakdown
        - LOW: Minimal/boilerplate content

        Primary factor: Line of business breakdown (multiple classes with amounts)
        Secondary factor: Causal clarity (differentiates VERY_HIGH from HIGH)
        """
        combined_text = (assessment.reserve_section_text + " " + assessment.strategic_report_text).lower()

        # Check for line of business breakdown (primary factor)
        has_lob_breakdown = (
            len(assessment.classes_mentioned) >= 2 and
            len(assessment.monetary_amounts) >= 2 and
            (assessment.has_dedicated_section or assessment.has_strategic_report)
        )

        # Check for clear causal descriptions (secondary factor)
        has_causal_clarity = (
            len(assessment.specific_causal_terms) >= 2 or
            (len(assessment.specific_causal_terms) >= 1 and len(assessment.causal_phrases) >= 3)
        )

        # Check for basic reserve content
        has_reserve_content = (
            assessment.has_dedicated_section or
            assessment.has_strategic_report or
            len(assessment.monetary_amounts) >= 1
        )

        # Check for direction indicators with class context
        has_direction_context = False
        if combined_text.strip():
            for direction in ['favourable', 'favorable', 'adverse', 'release', 'strengthening']:
                for cls in INSURANCE_CLASSES:
                    if direction in combined_text and cls in combined_text:
                        has_direction_context = True
                        break
                if has_direction_context:
                    break

        # Classification decision tree
        if has_lob_breakdown:
            if has_causal_clarity:
                return 'VERY_HIGH'
            else:
                return 'HIGH'
        elif has_reserve_content and has_direction_context:
            return 'MEDIUM'
        elif has_reserve_content:
            return 'MEDIUM'
        else:
            return 'LOW'
    
    def calculate_confidence(self, assessment: QualityAssessment) -> float:
        """Calculate confidence in the classification."""
        confidence = 0.5  # Base confidence

        # Increase if we found clear evidence
        if assessment.has_dedicated_section:
            confidence += 0.1

        if assessment.has_strategic_report:
            confidence += 0.1

        if len(assessment.classes_mentioned) >= 2:
            confidence += 0.1

        if len(assessment.causal_phrases) >= 2:
            confidence += 0.05

        if len(assessment.reserve_section_text) > 500:
            confidence += 0.05

        # Specific causal terms are strong evidence of quality
        if len(assessment.specific_causal_terms) >= 2:
            confidence += 0.1

        return min(1.0, confidence)
    
    def assess_report(self, file_path: str, syndicate: int, year: int) -> QualityAssessment:
        """
        Assess quality of reserve commentary in a single report.
        
        Args:
            file_path: Path to PDF or HTML file
            syndicate: Syndicate number
            year: Report year
            
        Returns:
            QualityAssessment object
        """
        assessment = QualityAssessment(
            syndicate=syndicate,
            year=year,
            quality='ERROR',
            confidence=0.0,
            file_path=file_path
        )
        
        # Determine file type and extract text
        if file_path.lower().endswith('.pdf'):
            text, method, pages = self.extract_text_from_pdf(file_path)
        elif file_path.lower().endswith('.html'):
            text, method, pages = self.extract_text_from_html(file_path)
        else:
            assessment.error = f"Unsupported file type: {file_path}"
            return assessment
        
        assessment.extraction_method = method
        assessment.total_pages = pages
        
        if not text:
            assessment.error = "Failed to extract text from file"
            return assessment

        # Find reserve section from Notes to Financial Statements
        reserve_section = self.find_reserve_section(text)
        assessment.reserve_section_text = reserve_section[:8000]  # Increased limit
        assessment.has_dedicated_section = len(reserve_section) > 200

        # Find Strategic Report section (often contains more detailed narrative)
        strategic_section = self.find_strategic_report(text)
        assessment.strategic_report_text = strategic_section[:10000]  # Increased limit
        assessment.has_strategic_report = len(strategic_section) > 200

        # Find Large Loss sections (contains named events like hurricanes, specific claims)
        large_loss_section = self.find_large_loss_section(text)
        assessment.large_loss_section_text = large_loss_section[:6000]

        # Combine all sections for evidence extraction
        combined_text = reserve_section + "\n\n" + strategic_section + "\n\n" + large_loss_section
        search_text = combined_text if combined_text.strip() else text[:40000]

        # Extract evidence from combined text
        assessment.classes_mentioned = self.extract_classes(search_text)
        assessment.causal_phrases = self.extract_causal_phrases(search_text)
        assessment.monetary_amounts = self.extract_monetary_amounts(search_text)
        assessment.specific_causal_terms = self.extract_specific_causal_terms(search_text)

        assessment.class_breakdown_found = len(assessment.classes_mentioned) >= 2
        assessment.causal_language_found = len(assessment.causal_phrases) >= 2
        assessment.quantified_movements = len(assessment.monetary_amounts) >= 2
        assessment.has_specific_causes = len(assessment.specific_causal_terms) >= 1

        # Classify quality
        assessment.quality = self.classify_quality(assessment)
        assessment.confidence = self.calculate_confidence(assessment)

        return assessment
    
    def assess_directory(self, pdf_dir: str, output_path: str = None) -> Dict:
        """
        Assess all reports in a directory.
        
        Args:
            pdf_dir: Directory containing PDF/HTML files
            output_path: Path to save results JSON
            
        Returns:
            Summary statistics
        """
        pdf_dir = Path(pdf_dir)
        assessments = []
        
        # Find all PDF and HTML files
        files = list(pdf_dir.glob("*.pdf")) + list(pdf_dir.glob("*.html"))
        logger.info(f"Found {len(files)} files to assess")
        
        for file_path in files:
            # Parse syndicate and year from filename
            # Expected format: syndicate_NNNN_YYYY.pdf
            match = re.search(r'syndicate_(\d+)_(\d{4})', file_path.name)
            if not match:
                logger.warning(f"Could not parse filename: {file_path.name}")
                continue
            
            syndicate = int(match.group(1))
            year = int(match.group(2))
            
            logger.info(f"Assessing: Syndicate {syndicate}, Year {year}")
            assessment = self.assess_report(str(file_path), syndicate, year)
            assessments.append(assessment)
        
        # Generate summary
        summary = self.generate_summary(assessments)
        
        # Save results
        if output_path:
            results = {
                'summary': summary,
                'assessments': [a.to_dict() for a in assessments]
            }
            with open(output_path, 'w') as f:
                json.dump(results, f, indent=2)
            logger.info(f"Results saved to {output_path}")
        
        return summary
    
    def generate_summary(self, assessments: List[QualityAssessment]) -> Dict:
        """Generate summary statistics from assessments."""
        by_quality = defaultdict(list)
        by_year = defaultdict(lambda: defaultdict(int))
        by_syndicate = defaultdict(lambda: {'quality_counts': defaultdict(int), 'years': []})

        for a in assessments:
            by_quality[a.quality].append(a)
            by_year[a.year][a.quality] += 1
            by_syndicate[a.syndicate]['quality_counts'][a.quality] += 1
            by_syndicate[a.syndicate]['years'].append(a.year)

        # Find syndicates with good LoB breakdown (HIGH or VERY_HIGH)
        good_quality_syndicates = []
        for syn, data in by_syndicate.items():
            very_high_count = data['quality_counts'].get('VERY_HIGH', 0)
            high_count = data['quality_counts'].get('HIGH', 0)
            good_count = very_high_count + high_count
            total = sum(data['quality_counts'].values())
            if total > 0 and good_count / total >= 0.5:
                good_quality_syndicates.append({
                    'syndicate': syn,
                    'very_high_reports': very_high_count,
                    'high_reports': high_count,
                    'total_reports': total,
                    'years': sorted(data['years'])
                })

        good_quality_syndicates.sort(key=lambda x: (x['very_high_reports'], x['high_reports']), reverse=True)

        # Count usable reports (HIGH or better = has LoB breakdown)
        usable_count = len(by_quality['VERY_HIGH']) + len(by_quality['HIGH'])

        return {
            'total_assessed': len(assessments),
            'by_quality': {
                'VERY_HIGH': len(by_quality['VERY_HIGH']),
                'HIGH': len(by_quality['HIGH']),
                'MEDIUM': len(by_quality['MEDIUM']),
                'LOW': len(by_quality['LOW']),
                'ERROR': len(by_quality['ERROR'])
            },
            'by_year': {str(k): dict(v) for k, v in sorted(by_year.items())},
            'good_quality_syndicates': good_quality_syndicates[:30],
            'usable_reports': usable_count,  # Reports with LoB breakdown
            'usable_rate': usable_count / len(assessments) if assessments else 0
        }


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Classify Lloyd's reserve commentary quality")
    parser.add_argument('--pdf-dir', required=True, help='Directory containing PDF files')
    parser.add_argument('--output', default='quality_report.json', help='Output JSON file')
    parser.add_argument('--single-file', help='Assess single file instead of directory')
    parser.add_argument('--ocr-cache', help='Path to OCR cache JSON file (from ocr_scanned_pdfs.py)')

    args = parser.parse_args()

    # Auto-detect OCR cache if not specified
    ocr_cache_path = args.ocr_cache
    if not ocr_cache_path:
        # Look for ocr_cache.json in parent of pdf_dir (default location)
        pdf_dir = Path(args.pdf_dir)
        default_cache = pdf_dir.parent / 'ocr_cache.json'
        if default_cache.exists():
            ocr_cache_path = str(default_cache)
            logger.info(f"Auto-detected OCR cache: {ocr_cache_path}")

    classifier = ReserveCommentaryClassifier(ocr_cache_path=ocr_cache_path)
    
    if args.single_file:
        # Parse syndicate and year from filename
        match = re.search(r'syndicate_(\d+)_(\d{4})', args.single_file)
        if match:
            syndicate, year = int(match.group(1)), int(match.group(2))
        else:
            syndicate, year = 0, 0
        
        assessment = classifier.assess_report(args.single_file, syndicate, year)

        print(f"\nQuality Assessment")
        print("=" * 50)
        print(f"Syndicate: {assessment.syndicate}")
        print(f"Year: {assessment.year}")
        print(f"Quality: {assessment.quality}")
        print(f"Confidence: {assessment.confidence:.2f}")
        print(f"\nEvidence:")
        print(f"  - Dedicated reserve section: {assessment.has_dedicated_section}")
        print(f"  - Strategic report found: {assessment.has_strategic_report}")
        print(f"  - Classes mentioned: {assessment.classes_mentioned}")
        print(f"  - Causal phrases: {len(assessment.causal_phrases)}")
        print(f"  - Monetary amounts: {len(assessment.monetary_amounts)}")
        print(f"  - Specific root causes: {assessment.specific_causal_terms}")
        
    else:
        summary = classifier.assess_directory(args.pdf_dir, args.output)

        print("\n" + "=" * 60)
        print("QUALITY CLASSIFICATION SUMMARY")
        print("=" * 60)
        print(f"Total reports assessed: {summary['total_assessed']}")
        print(f"\nQuality distribution:")
        for quality, count in summary['by_quality'].items():
            pct = 100 * count / summary['total_assessed'] if summary['total_assessed'] > 0 else 0
            print(f"  {quality}: {count} ({pct:.1f}%)")

        print(f"\nUsable reports (with LoB breakdown): {summary['usable_reports']} ({summary['usable_rate']:.1%})")
        print(f"\nTop syndicates with LoB breakdown:")
        for syn in summary['good_quality_syndicates'][:10]:
            vh = syn['very_high_reports']
            h = syn['high_reports']
            print(f"  Syndicate {syn['syndicate']}: {vh} VERY_HIGH, {h} HIGH / {syn['total_reports']} total")


if __name__ == "__main__":
    main()
