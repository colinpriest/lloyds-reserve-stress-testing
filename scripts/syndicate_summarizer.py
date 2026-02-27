#!/usr/bin/env python3
"""
Syndicate Report Summarizer
===========================
Uses OpenAI ChatGPT API to standardize Lloyd's syndicate reserve commentary.

Input: quality_report.json (from quality_classifier.py)
Output: Standardized reserve movements by syndicate-year-LOB

Focuses on VERY_HIGH and HIGH quality reports which contain:
- VERY_HIGH: LoB breakdown + causal narratives
- HIGH: LoB breakdown only
"""

import os
import re
import json
import time
import hashlib
import logging
import argparse
from dataclasses import dataclass, asdict, field
from typing import List, Dict, Optional, Any
from datetime import datetime
from pathlib import Path

import requests

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class SyndicateReserveMovement:
    """Standardized reserve movement for a single syndicate-year-LOB."""
    syndicate: int
    year: int
    line_of_business: str
    direction: str  # 'release', 'strengthening', 'flat', 'mixed'
    percentage: Optional[float] = None
    amount_gbp_m: Optional[float] = None
    amount_usd_m: Optional[float] = None  # Many syndicates report in USD
    primary_causes: List[str] = field(default_factory=list)
    specific_events: List[str] = field(default_factory=list)
    specific_years_affected: List[int] = field(default_factory=list)  # e.g., [2019, 2020, 2021]
    standardized_narrative: str = ""
    confidence: str = "medium"  # high/medium/low
    data_quality_notes: str = ""
    # Audit trail
    raw_reserve_section: str = ""
    raw_strategic_report: str = ""
    raw_causal_phrases: List[str] = field(default_factory=list)
    source_file: str = ""
    content_hash: str = ""
    standardized_at: str = ""
    standardization_model: str = ""


@dataclass
class SyndicateSummary:
    """Aggregate summary for a syndicate across all years."""
    syndicate: int
    years_covered: List[int] = field(default_factory=list)
    dominant_lobs: List[str] = field(default_factory=list)
    typical_direction: str = ""  # Overall tendency
    movements: List[SyndicateReserveMovement] = field(default_factory=list)
    total_release_gbp_m: float = 0.0
    total_strengthening_gbp_m: float = 0.0
    recurring_causes: List[str] = field(default_factory=list)


# =============================================================================
# Main Summarizer Class
# =============================================================================

class SyndicateSummarizer:
    """
    Standardizes syndicate reserve commentary using ChatGPT.
    
    Input: quality_report.json from quality_classifier.py
    Output: Standardized movements by syndicate-year with LoB breakdown
    """
    
    MODELS = {
        "fast": "gpt-3.5-turbo",
        "balanced": "gpt-4-turbo",
        "best": "gpt-4o",
    }
    
    # Standard Lloyd's LOB categories (aligned with Lloyd's market reporting)
    # These are the ONLY valid output categories
    STANDARD_LOBS = [
        "Reinsurance - Property",
        "Reinsurance - Casualty",
        "Reinsurance - Specialty",
        "Property",
        "Casualty",
        "Marine",
        "Aviation",
        "Energy",
        "Motor",
        "Accident & Health",
        "Professional Lines",
        "Cyber",
        "Aggregate",  # For reports without LOB breakdown
    ]
    
    # Mapping from syndicate division names to standard LOBs
    LOB_MAPPING = {
        # Reinsurance variations
        "treaty": "Reinsurance - Property",  # Default treaty to property, ChatGPT may override
        "treaty reinsurance": "Reinsurance - Property",
        "property treaty": "Reinsurance - Property",
        "casualty treaty": "Reinsurance - Casualty",
        "liability treaty": "Reinsurance - Casualty",
        "specialty treaty": "Reinsurance - Specialty",
        "reinsurance": "Reinsurance - Property",  # Default
        "reinsurance property": "Reinsurance - Property",
        "reinsurance casualty": "Reinsurance - Casualty",
        "reinsurance specialty": "Reinsurance - Specialty",
        "cat reinsurance": "Reinsurance - Property",
        "catastrophe reinsurance": "Reinsurance - Property",
        "retrocession": "Reinsurance - Property",
        
        # Property variations
        "property": "Property",
        "property direct": "Property",
        "property insurance": "Property",
        "commercial property": "Property",
        "uk property": "Property",
        "us property": "Property",
        "international property": "Property",
        "property division": "Property",
        "fire": "Property",
        "theft": "Property",
        
        # Casualty / Liability variations
        "casualty": "Casualty",
        "casualty direct": "Casualty",
        "liability": "Casualty",
        "general liability": "Casualty",
        "professional liability": "Professional Lines",
        "public liability": "Casualty",
        "employers liability": "Casualty",
        "products liability": "Casualty",
        "us casualty": "Casualty",
        "uk casualty": "Casualty",
        "international casualty": "Casualty",
        "casualty division": "Casualty",
        
        # Marine variations
        "marine": "Marine",
        "marine hull": "Marine",
        "marine cargo": "Marine",
        "marine liability": "Marine",
        "ocean marine": "Marine",
        "inland marine": "Marine",
        "marine division": "Marine",
        "hull": "Marine",
        "cargo": "Marine",
        "specie": "Marine",
        "fine art": "Marine",
        "war": "Marine",
        "marine aviation transport": "Marine",  # MAT combined
        "mat": "Marine",  # MAT combined - default to Marine
        "transport": "Marine",
        
        # Aviation variations
        "aviation": "Aviation",
        "aviation hull": "Aviation",
        "aviation liability": "Aviation",
        "aerospace": "Aviation",
        "aviation division": "Aviation",
        "space": "Aviation",
        "satellite": "Aviation",
        "general aviation": "Aviation",
        "airline": "Aviation",
        
        # Energy variations
        "energy": "Energy",
        "energy offshore": "Energy",
        "energy onshore": "Energy",
        "upstream energy": "Energy",
        "downstream energy": "Energy",
        "oil and gas": "Energy",
        "power generation": "Energy",
        "energy division": "Energy",
        "offshore": "Energy",
        "onshore": "Energy",
        
        # Motor variations
        "motor": "Motor",
        "uk motor": "Motor",
        "motor fleet": "Motor",
        "motor division": "Motor",
        "auto": "Motor",
        "automobile": "Motor",
        "vehicle": "Motor",
        
        # Accident & Health variations
        "accident health": "Accident & Health",
        "accident and health": "Accident & Health",
        "a&h": "Accident & Health",
        "accident": "Accident & Health",
        "health": "Accident & Health",
        "personal accident": "Accident & Health",
        "travel": "Accident & Health",
        "medical": "Accident & Health",
        "life": "Accident & Health",
        
        # Professional Lines variations
        "professional lines": "Professional Lines",
        "financial lines": "Professional Lines",
        "d&o": "Professional Lines",
        "directors and officers": "Professional Lines",
        "e&o": "Professional Lines",
        "errors and omissions": "Professional Lines",
        "professional indemnity": "Professional Lines",
        "pi": "Professional Lines",
        "management liability": "Professional Lines",
        "financial institutions": "Professional Lines",
        "crime": "Professional Lines",
        "fidelity": "Professional Lines",
        
        # Cyber variations
        "cyber": "Cyber",
        "cyber liability": "Cyber",
        "technology": "Cyber",
        "tech": "Cyber",
        "data breach": "Cyber",
        
        # Credit & Political Risk -> map to Specialty reinsurance
        "credit": "Reinsurance - Specialty",
        "credit risk": "Reinsurance - Specialty",
        "political risk": "Reinsurance - Specialty",
        "trade credit": "Reinsurance - Specialty",
        "surety": "Reinsurance - Specialty",
        "bond": "Reinsurance - Specialty",
        
        # Other specialty -> map appropriately
        "terrorism": "Reinsurance - Specialty",
        "contingency": "Reinsurance - Specialty",
        "special risks": "Reinsurance - Specialty",
        "specialty": "Reinsurance - Specialty",
        "bloodstock": "Reinsurance - Specialty",
        "kidnap ransom": "Reinsurance - Specialty",
        "k&r": "Reinsurance - Specialty",
        
        # UK Division typically means UK-focused lines
        "uk division": "Property",  # Most common, but ChatGPT should override based on context
        "uk": "Property",
        "london market": "Property",
        
        # Aggregate / Unknown
        "aggregate": "Aggregate",
        "total": "Aggregate",
        "all classes": "Aggregate",
        "overall": "Aggregate",
        "mixed": "Aggregate",
    }
    
    # Standard causal categories (same as market summarizer for consistency)
    CAUSAL_CATEGORIES = [
        "Social inflation / litigation trends",
        "Economic inflation / claims cost inflation",
        "Natural catastrophe events",
        "Man-made catastrophe / large losses",
        "Court rulings / legal developments",
        "Regulatory changes",
        "Ogden discount rate",
        "COVID-19 / pandemic effects",
        "Geopolitical events",
        "Favorable claims development",
        "Adverse claims development",
        "IBNR recalibration",
        "Management margin release",
        "Reinsurance recoveries",
        "Subrogation recoveries",
        "Commutation",
        "Reserve methodology change",
        "Large loss development",
        "Attritional claims better than expected",
        "Attritional claims worse than expected",
    ]
    
    def __init__(self, api_key: Optional[str] = None, model: str = "balanced"):
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OpenAI API key required. Set OPENAI_API_KEY env var.")
        
        self.model = model
        self.api_url = "https://api.openai.com/v1/chat/completions"
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        })
        
        # Track API usage
        self.api_calls = 0
        self.total_tokens = 0
    
    def _call_api(self,
                  system_prompt: str,
                  user_prompt: str,
                  model: str = None,
                  temperature: float = 0.2,
                  response_format: Optional[Dict] = None,
                  max_tokens: int = 2000) -> str:
        """Make API call to OpenAI."""
        
        model_name = self.MODELS.get(model or self.model, self.MODELS["balanced"])
        
        payload = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        
        if response_format:
            payload["response_format"] = response_format
        
        try:
            response = self.session.post(self.api_url, json=payload, timeout=90)
            response.raise_for_status()
            result = response.json()
            
            self.api_calls += 1
            if 'usage' in result:
                self.total_tokens += result['usage'].get('total_tokens', 0)
            
            return result['choices'][0]['message']['content']
            
        except requests.exceptions.Timeout:
            logger.error("OpenAI API timeout")
            raise
        except requests.exceptions.HTTPError as e:
            logger.error(f"OpenAI API HTTP error: {e}")
            logger.error(f"Response: {e.response.text if e.response else 'No response'}")
            raise
        except Exception as e:
            logger.error(f"OpenAI API error: {e}")
            raise
    
    def load_quality_report(self, filepath: str) -> Dict:
        """Load quality_report.json."""
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def filter_usable_reports(self, 
                              quality_report: Dict,
                              min_quality: str = "HIGH") -> List[Dict]:
        """
        Filter reports to usable quality levels.
        
        Args:
            quality_report: Loaded quality_report.json
            min_quality: Minimum quality level ("VERY_HIGH", "HIGH", "MEDIUM")
        
        Returns:
            List of report entries meeting quality threshold
        """
        quality_levels = {
            "VERY_HIGH": 4,
            "HIGH": 3,
            "MEDIUM": 2,
            "LOW": 1,
            "ERROR": 0,
        }
        
        min_level = quality_levels.get(min_quality, 3)
        
        usable = []
        # Handle both 'reports' and 'assessments' keys
        reports_list = quality_report.get('reports', quality_report.get('assessments', []))
        for report in reports_list:
            report_level = quality_levels.get(report.get('quality', 'ERROR'), 0)
            if report_level >= min_level:
                usable.append(report)
        
        logger.info(f"Filtered to {len(usable)} reports at {min_quality} or above")
        return usable
    
    # Keywords that MUST be captured if present in source text
    # Format: keyword -> earliest year it's relevant (None = always relevant)
    MUST_CAPTURE_KEYWORDS = {
        # Named hurricanes with year they occurred
        'hurricanes': {
            'harvey': 2017, 'irma': 2017, 'maria': 2017,
            'florence': 2018, 'michael': 2018,
            'laura': 2020, 'zeta': 2020, 'sally': 2020, 'delta': 2020,
            'ida': 2021, 'ian': 2022, 'dorian': 2019,
            'sandy': 2012, 'katrina': 2005, 'matthew': 2016,
            'helene': 2024, 'milton': 2024,
            'haiyan': 2013, 'nargis': 2008, 'ike': 2008,
        },
        # Other natural catastrophes (no year filter - generic terms)
        'catastrophes': {
            'wildfire': None, 'california fire': None, 'earthquake': None,
            'tsunami': None, 'typhoon': None, 'derecho': None,
            'winter storm': None, 'freeze': None, 'hailstorm': None,
            'convective storm': None, 'flood': None, 'cyclone': None,
            'bushfire': None, 'tornado': None,
        },
        # Man-made events with years
        'man_made': {
            'tripoli': 2014, 'tripoli airport': 2014,
            'ukraine': 2022, 'russia': 2022,
            'grenfell': 2017, 'costa concordia': 2012, 'deepwater horizon': 2010,
            'boeing 737': 2019, 'boeing max': 2019,
            'tianjin': 2015, 'beirut': 2020,
            # Aviation disasters
            'malaysian airlines': 2014, 'mh370': 2014, 'mh17': 2014,
            'sewol': 2014, 'sewol ferry': 2014,
            'germanwings': 2015,
            # Mining/industrial
            'mining': None, 'landslide': None, 'mine collapse': None,
            'explosion': None, 'refinery': None, 'plant explosion': None,
            # Construction
            'construction loss': None, 'construction claim': None,
            'contractor': None, 'power claim': None,
        },
        # Systemic/regulatory (no year filter)
        'systemic': {
            'ogden': None, 'discount rate': None, 'covid': 2020,
            'pandemic': 2020, 'social inflation': None,
            'litigation trend': None, 'court ruling': None,
            'fca test case': 2020, 'business interruption': 2020,
            'nuclear': None, 'asbestos': None, 'pfas': None, 'opioid': None,
            'abuse': None, 'molestation': None, 'sexual abuse': None,
        },
        # Economic (no year filter)
        'economic': {
            'claims inflation': None, 'wage inflation': None,
            'medical inflation': None, 'supply chain': 2020,
            'economic inflation': None, 'cost inflation': None,
        },
        # Reinsurance/transaction specific
        'transactions': {
            'ritc': None, 'reinsurance to close': None,
            'adc': None, 'adverse development cover': None,
            'lpt': None, 'loss portfolio transfer': None,
            'commutation': None,
        }
    }
    
    # Context words - keyword must appear near one of these to be flagged
    RESERVE_CONTEXT_WORDS = [
        'reserve', 'reserves', 'provision', 'provisions',
        'claim', 'claims', 'loss', 'losses', 'incurred',
        'strengthening', 'strengthened', 'deterioration', 'deteriorated',
        'release', 'released', 'redundancy', 'deficiency',
        'adverse', 'favourable', 'favorable', 'development',
        'prior year', 'run-off', 'runoff', 'ibnr',
        'cat', 'catastrophe', 'catastrophic',
        'impact', 'impacted', 'affected', 'arising from',
        'due to', 'driven by', 'result of', 'caused by'
    ]
    
    # Words that indicate the keyword is NOT about a specific event
    EXCLUSION_CONTEXT = [
        'marine war class', 'war risk class', 'war and terror',
        'war terrorism', 'war & terrorism', 'war risks',
        'flood risk', 'flood zone', 'flood model', 'flood exposure',
        'earthquake zone', 'earthquake model', 'earthquake exposure',
        'tornado model', 'cyclone model', 'hurricane model',
        'named storm', 'named storms'  # Generic reference to cat models
    ]
    
    # Few-shot examples for the prompt
    FEW_SHOT_EXAMPLES = """
EXAMPLE 1 - GOOD EXTRACTION (Specific events captured):

SOURCE TEXT:
"The net claims ratio reflects another year of heightened catastrophe experience, with the largest events being Hurricanes Florence and Michael as well as the California wildfires. Prior year reserves were strengthened by £45.2m primarily on the Property treaty book."

GOOD OUTPUT:
{
    "movements": [{
        "line_of_business": "Reinsurance - Property",
        "direction": "strengthening",
        "amount_gbp_m": 45.2,
        "primary_causes": ["Natural catastrophe events"],
        "specific_events": ["Hurricane Florence", "Hurricane Michael", "California wildfires"],
        "narrative": "Reserve strengthening of £45.2m on Property treaty driven by Hurricanes Florence and Michael and California wildfires."
    }]
}

BAD OUTPUT (loses detail):
{
    "movements": [{
        "line_of_business": "Reinsurance - Property",
        "direction": "strengthening",
        "amount_gbp_m": 45.2,
        "primary_causes": ["Adverse claims development"],
        "specific_events": [],
        "narrative": "Strengthening due to adverse claims development."
    }]
}

---

EXAMPLE 2 - GOOD EXTRACTION (Ogden rate impact):

SOURCE TEXT:
"The surplus on direct business was driven by the Property class offset by a deterioration on the Liability class due to the impact of the Ogden table changes announced in 2017, resulting in a £12.3m strengthening."

GOOD OUTPUT:
{
    "movements": [{
        "line_of_business": "Casualty",
        "direction": "strengthening",
        "amount_gbp_m": 12.3,
        "primary_causes": ["Ogden discount rate"],
        "specific_events": ["Ogden table changes 2017"],
        "narrative": "Liability reserves strengthened by £12.3m due to Ogden discount rate table changes announced in 2017."
    }]
}

---

EXAMPLE 3 - GOOD EXTRACTION (COVID + multiple cats):

SOURCE TEXT:
"2020 experienced deterioration across multiple classes. COVID-19 impacted Contingency and Event Cancellation reserves by $35m. Additionally, natural catastrophe events including Hurricanes Laura, Zeta, Sally and Delta and the Midwest Derecho contributed $28m of strengthening to Property reserves."

GOOD OUTPUT:
{
    "movements": [
        {
            "line_of_business": "Reinsurance - Specialty",
            "direction": "strengthening",
            "amount_usd_m": 35,
            "primary_causes": ["COVID-19 / pandemic effects"],
            "specific_events": ["COVID-19 event cancellation claims"],
            "narrative": "COVID-19 pandemic drove $35m strengthening on Contingency and Event Cancellation business."
        },
        {
            "line_of_business": "Property",
            "direction": "strengthening",
            "amount_usd_m": 28,
            "primary_causes": ["Natural catastrophe events"],
            "specific_events": ["Hurricane Laura", "Hurricane Zeta", "Hurricane Sally", "Hurricane Delta", "Midwest Derecho"],
            "narrative": "Natural catastrophe events in 2020 including four named hurricanes and Midwest Derecho drove $28m property reserve strengthening."
        }
    ]
}

---

EXAMPLE 4 - GOOD EXTRACTION (Social inflation / litigation):

SOURCE TEXT:
"US Casualty reserves were strengthened by $42m reflecting the continued impact of social inflation trends and adverse litigation outcomes, particularly in commercial auto and general liability classes."

GOOD OUTPUT:
{
    "movements": [{
        "line_of_business": "Casualty",
        "direction": "strengthening",
        "amount_usd_m": 42,
        "primary_causes": ["Social inflation / litigation trends"],
        "specific_events": ["US social inflation", "Commercial auto litigation", "General liability litigation"],
        "narrative": "US Casualty strengthening of $42m driven by social inflation trends and adverse litigation outcomes in commercial auto and general liability."
    }]
}
"""

    def _extract_keywords_from_text(self, text: str, report_year: int = None) -> Dict[str, List[str]]:
        """
        Extract must-capture keywords found in source text.
        
        Only flags keywords that:
        1. Appear near reserve/claims context words
        2. Are relevant for the report year (e.g., Hurricane Ian only for 2022+)
        3. Are not in exclusion context (e.g., "marine war class")
        """
        text_lower = text.lower()
        found = {category: [] for category in self.MUST_CAPTURE_KEYWORDS}
        
        # Check for exclusion context - if present, skip those keywords
        exclusion_matches = []
        for exclusion in self.EXCLUSION_CONTEXT:
            if exclusion in text_lower:
                exclusion_matches.append(exclusion)
        
        for category, keywords_dict in self.MUST_CAPTURE_KEYWORDS.items():
            for keyword, min_year in keywords_dict.items():
                # Skip if keyword requires a minimum year and report is earlier
                if min_year is not None and report_year is not None:
                    if report_year < min_year:
                        continue
                
                if keyword not in text_lower:
                    continue
                
                # Check if keyword is part of an exclusion phrase
                is_excluded = False
                for exclusion in exclusion_matches:
                    if keyword in exclusion:
                        is_excluded = True
                        break
                
                if is_excluded:
                    continue
                
                # Check if keyword appears near reserve context
                # Find all positions of the keyword
                keyword_positions = []
                start = 0
                while True:
                    pos = text_lower.find(keyword, start)
                    if pos == -1:
                        break
                    keyword_positions.append(pos)
                    start = pos + 1
                
                # Check if any occurrence is near a context word
                context_window = 150  # characters
                has_context = False
                
                for pos in keyword_positions:
                    # Get surrounding text
                    window_start = max(0, pos - context_window)
                    window_end = min(len(text_lower), pos + len(keyword) + context_window)
                    surrounding = text_lower[window_start:window_end]
                    
                    # Check for context words
                    for context_word in self.RESERVE_CONTEXT_WORDS:
                        if context_word in surrounding:
                            has_context = True
                            break
                    
                    if has_context:
                        break
                
                if has_context:
                    found[category].append(keyword)
        
        return found

    def standardize_single_report(self, report: Dict) -> List[SyndicateReserveMovement]:
        """
        Standardize a single syndicate report into structured movements.
        
        Returns list of movements (one per LOB mentioned).
        """
        syndicate = report.get('syndicate')
        year = report.get('year')
        quality = report.get('quality')
        
        # Combine available text
        reserve_text = report.get('reserve_section_text', '') or ''
        strategic_text = report.get('strategic_report_text', '') or ''
        large_loss_text = report.get('large_loss_section_text', '') or ''  # New: large loss sections
        causal_phrases = report.get('causal_phrases', []) or []
        classes_mentioned = report.get('classes_mentioned', []) or []
        monetary_amounts = report.get('monetary_amounts', []) or []

        # Pre-extract keywords to include in prompt - now includes large_loss_text
        combined_for_keywords = reserve_text + " " + strategic_text + " " + large_loss_text + " " + " ".join(causal_phrases)
        found_keywords = self._extract_keywords_from_text(combined_for_keywords, report_year=year)

        # Build keyword hints for prompt - make them MANDATORY to address
        keyword_hints = []
        all_found_keywords = []
        for category, keywords in found_keywords.items():
            if keywords:
                keyword_hints.append(f"  - {category.upper()}: {', '.join(keywords)}")
                all_found_keywords.extend(keywords)
        keyword_section = "\n".join(keyword_hints) if keyword_hints else "  (none detected)"

        # Build combined context - increased limits for more complete extraction
        combined_text = f"""
RESERVE SECTION (Notes to Financial Statements):
{reserve_text[:12000]}

STRATEGIC REPORT / DIRECTORS REPORT EXCERPTS:
{strategic_text[:8000]}

LARGE LOSS AND MAJOR EVENTS SECTIONS:
{large_loss_text[:6000]}

PRE-EXTRACTED CAUSAL PHRASES:
{chr(10).join(causal_phrases[:15])}

CLASSES OF BUSINESS MENTIONED:
{', '.join(classes_mentioned)}

MONETARY AMOUNTS FOUND:
{', '.join(monetary_amounts[:30])}
"""
        
        # If we have keywords, use keyword-centric prompt
        if all_found_keywords:
            system_prompt = f"""You are an expert actuarial analyst standardizing Lloyd's syndicate reserve commentary.

TASK: Extract reserve movements from this syndicate report. Specific events have been detected in the text that MUST be captured.

CRITICAL EXTRACTION REQUIREMENTS:

1. LARGE LOSS EVENTS: Look for sections mentioning "large losses", "significant claims",
   "major events", or specific named events. Extract ALL named events including:
   - Catastrophe names (Hurricane Harvey, Typhoon Hagibis, California wildfires)
   - Aviation incidents (Malaysian Airlines MH370/MH17, Sewol Ferry)
   - Industrial losses (mining landslide, refinery explosion, construction claims)
   - Named transactions (RITC, ADC, commutations)

2. TABLE PARSING: If you see a table showing movements by line of business like:
   "Marine £14.9m, War £14.9m, Property £14.9m, Energy £11.4m"
   Extract EACH line as a separate movement with its specific amount.

3. YEAR OF ACCOUNT ANALYSIS: Look in "Year of Account" sections for specific claims
   descriptions like "mining landslide", "contractor's liability", "power claims".

4. CLAIMS INCURRED SECTIONS: Look in "Report of the Directors - Claims incurred" or
   "Underwriting Review" for drivers like "claims inflation", "casualty deterioration".

5. NEVER use generic causes like "Adverse claims development" if the source text
   mentions specific events, transactions, or named losses. The specific cause is
   ALWAYS more valuable than a generic one.

MANDATORY KEYWORD HANDLING:
The following keywords were detected in the source text. For EACH keyword, you must:
1. Find where it appears in context
2. Determine which reserve movement it relates to
3. Include it in the specific_events field of that movement
4. Reference it in the narrative

If a keyword appears in the source but is NOT related to reserve movements (e.g., appears only in risk model descriptions), you MUST note this in the keyword_disposition field.

DETECTED KEYWORDS THAT MUST BE ADDRESSED:
{', '.join(all_found_keywords)}

{self.FEW_SHOT_EXAMPLES}

LINE OF BUSINESS MAPPING:
- "Reinsurance - Property" (treaty property, cat reinsurance, retrocession)
- "Reinsurance - Casualty" (treaty casualty, liability treaty)
- "Reinsurance - Specialty" (credit, political risk, surety, terrorism, contingency)
- "Property" (direct property, UK property, commercial property)
- "Casualty" (direct casualty, liability, general liability)
- "Marine" (marine hull, cargo, specie, war, transport)
- "Aviation" (aviation hull, aerospace, space)
- "Energy" (offshore, onshore, upstream, downstream)
- "Motor" (UK motor, fleet, auto)
- "Accident & Health" (A&H, personal accident, travel)
- "Professional Lines" (D&O, E&O, PI, financial lines)
- "Cyber" (cyber liability, technology)
- "Aggregate" (ONLY if no LOB breakdown available)

STANDARD CAUSE CATEGORIES:
{chr(10).join(f'- "{c}"' for c in self.CAUSAL_CATEGORIES)}

OUTPUT FORMAT (JSON):
{{
    "keyword_disposition": {{
        "<keyword1>": "Included in Property movement - caused £45m strengthening",
        "<keyword2>": "Included in Marine movement - referenced in narrative",
        "<keyword3>": "NOT reserve-related - only appears in catastrophe model description"
    }},
    "movements": [
        {{
            "line_of_business": "standard category",
            "direction": "release|strengthening|flat|mixed",
            "percentage": null or number,
            "amount_gbp_m": null or number,
            "amount_usd_m": null or number,
            "primary_causes": ["category from list above"],
            "specific_events": ["MUST include detected keywords that relate to this movement"],
            "specific_years_affected": [2019, 2020],
            "narrative": "Detailed narrative that explicitly mentions the specific events"
        }}
    ],
    "overall_direction": "release|strengthening|flat|mixed",
    "overall_amount_m": null or number,
    "overall_currency": "GBP|USD",
    "confidence": "high|medium|low",
    "data_quality_notes": "Any caveats"
}}

CRITICAL: 
- You MUST populate keyword_disposition for EVERY keyword listed above
- Every keyword must either appear in a movement's specific_events OR be explained as not reserve-related
- Do NOT use generic causes like "Adverse claims development" when specific events are available"""

        else:
            # No keywords detected - use simpler prompt but still with extraction guidance
            system_prompt = f"""You are an expert actuarial analyst standardizing Lloyd's syndicate reserve commentary.

TASK: Extract and standardize prior year reserve movements from this syndicate report.

CRITICAL EXTRACTION REQUIREMENTS:

1. LARGE LOSS EVENTS: Carefully search for sections mentioning "large losses", "significant claims",
   "major events". Extract ALL named events you find including:
   - Natural catastrophe names (hurricanes, typhoons, earthquakes, wildfires)
   - Aviation/marine incidents (plane crashes, ship losses, ferry disasters)
   - Industrial losses (mining, construction, power plant, refinery)
   - Named transactions (RITC, ADC, commutations, loss portfolio transfers)

2. TABLE PARSING: If you see a table showing movements by line of business like:
   "Marine £14.9m, War £14.9m, Property £14.9m, Energy £11.4m"
   Extract EACH line as a separate movement with its specific amount.

3. YEAR OF ACCOUNT ANALYSIS: Look in "Year of Account" sections for specific claims
   descriptions (e.g., "mining landslide", "contractor's liability", "construction loss").

4. CLAIMS INCURRED SECTIONS: Look in "Report of the Directors", "Claims incurred", or
   "Underwriting Review" sections for specific drivers of reserve movements.

5. PREFER SPECIFIC OVER GENERIC: NEVER use generic causes like "Adverse claims development"
   if you can find ANY specific event, loss name, or transaction in the source text.
   Specific events are ALWAYS more valuable than generic descriptions.

{self.FEW_SHOT_EXAMPLES}

LINE OF BUSINESS MAPPING:
- "Reinsurance - Property" (treaty property, cat reinsurance, retrocession)
- "Reinsurance - Casualty" (treaty casualty, liability treaty)
- "Reinsurance - Specialty" (credit, political risk, surety, terrorism, contingency)
- "Property" (direct property, UK property, commercial property)
- "Casualty" (direct casualty, liability, general liability)
- "Marine" (marine hull, cargo, specie, war, transport)
- "Aviation" (aviation hull, aerospace, space)
- "Energy" (offshore, onshore, upstream, downstream)
- "Motor" (UK motor, fleet, auto)
- "Accident & Health" (A&H, personal accident, travel)
- "Professional Lines" (D&O, E&O, PI, financial lines)
- "Cyber" (cyber liability, technology)
- "Aggregate" (ONLY if no LOB breakdown available)

STANDARD CAUSE CATEGORIES:
{chr(10).join(f'- "{c}"' for c in self.CAUSAL_CATEGORIES)}

OUTPUT FORMAT (JSON):
{{
    "movements": [
        {{
            "line_of_business": "standard category",
            "direction": "release|strengthening|flat|mixed",
            "percentage": null or number,
            "amount_gbp_m": null or number,
            "amount_usd_m": null or number,
            "primary_causes": ["category from list above"],
            "specific_events": ["IMPORTANT: Include ANY named events, losses, or transactions found"],
            "specific_years_affected": [2019, 2020],
            "narrative": "Detailed narrative that MUST mention specific events if found in source"
        }}
    ],
    "overall_direction": "release|strengthening|flat|mixed",
    "overall_amount_m": null or number,
    "overall_currency": "GBP|USD",
    "confidence": "high|medium|low",
    "data_quality_notes": "Any caveats"
}}"""

        user_prompt = f"""Standardize reserve commentary for:
Syndicate: {syndicate}
Year: {year}
Quality: {quality}

{"MANDATORY - Address each of these detected keywords:" if all_found_keywords else ""}
{keyword_section if all_found_keywords else ""}

SOURCE TEXT:
{combined_text}

Extract all prior year reserve movements. {"For EACH keyword listed above, either include it in specific_events or explain why it's not reserve-related in keyword_disposition." if all_found_keywords else ""}"""

        try:
            response = self._call_api(
                system_prompt,
                user_prompt,
                model=self.model,
                response_format={"type": "json_object"},
                max_tokens=2500  # Increased for more detailed output
            )
            
            data = json.loads(response)
            
        except json.JSONDecodeError as e:
            logger.error(f"JSON parse error for syndicate {syndicate} year {year}: {e}")
            # Try to extract JSON from response
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                try:
                    data = json.loads(json_match.group())
                except:
                    data = {"movements": [], "confidence": "low", "data_quality_notes": "Parse error"}
            else:
                data = {"movements": [], "confidence": "low", "data_quality_notes": "Parse error"}
        except Exception as e:
            logger.error(f"API error for syndicate {syndicate} year {year}: {e}")
            data = {"movements": [], "confidence": "low", "data_quality_notes": str(e)}
        
        # Convert to SyndicateReserveMovement objects
        movements = []
        content_hash = hashlib.sha256(combined_text.encode()).hexdigest()
        
        for m in data.get('movements', []):
            movement = SyndicateReserveMovement(
                syndicate=syndicate,
                year=year,
                line_of_business=self._standardize_lob_name(m.get('line_of_business', 'Unknown')),
                direction=m.get('direction', 'unknown'),
                percentage=m.get('percentage'),
                amount_gbp_m=m.get('amount_gbp_m'),
                amount_usd_m=m.get('amount_usd_m'),
                primary_causes=m.get('primary_causes', []),
                specific_events=m.get('specific_events', []),
                specific_years_affected=m.get('specific_years_affected', []),
                standardized_narrative=m.get('narrative', ''),
                confidence=data.get('confidence', 'medium'),
                data_quality_notes=data.get('data_quality_notes', ''),
                # Audit trail
                raw_reserve_section=reserve_text,
                raw_strategic_report=strategic_text,
                raw_causal_phrases=causal_phrases,
                source_file=report.get('file_path', ''),
                content_hash=content_hash,
                standardized_at=datetime.now().isoformat(),
                standardization_model=self.MODELS.get(self.model, self.model)
            )
            movements.append(movement)
        
        # If no movements extracted but we have data, create aggregate entry
        if not movements and (reserve_text or strategic_text):
            movements.append(SyndicateReserveMovement(
                syndicate=syndicate,
                year=year,
                line_of_business="Aggregate",
                direction=data.get('overall_direction', 'unknown'),
                amount_gbp_m=data.get('overall_amount_m') if data.get('overall_currency') == 'GBP' else None,
                amount_usd_m=data.get('overall_amount_m') if data.get('overall_currency') == 'USD' else None,
                confidence=data.get('confidence', 'low'),
                data_quality_notes=data.get('data_quality_notes', 'No LoB breakdown available'),
                raw_reserve_section=reserve_text,
                raw_strategic_report=strategic_text,
                raw_causal_phrases=causal_phrases,
                source_file=report.get('file_path', ''),
                content_hash=content_hash,
                standardized_at=datetime.now().isoformat(),
                standardization_model=self.MODELS.get(self.model, self.model)
            ))
        
        # Check keyword disposition if we had keywords to capture
        if all_found_keywords:
            keyword_disposition = data.get('keyword_disposition', {})
            
            # Log how keywords were handled
            not_reserve_related = []
            included_in_movements = []
            unaddressed = []
            
            for kw in all_found_keywords:
                disposition = keyword_disposition.get(kw, '')
                if not disposition:
                    # Check if keyword appears in any movement's specific_events
                    found_in_events = False
                    for m in data.get('movements', []):
                        events_lower = [e.lower() for e in m.get('specific_events', [])]
                        narrative_lower = m.get('narrative', '').lower()
                        if kw in events_lower or kw in ' '.join(events_lower) or kw in narrative_lower:
                            found_in_events = True
                            break
                    
                    if found_in_events:
                        included_in_movements.append(kw)
                    else:
                        unaddressed.append(kw)
                elif 'not reserve' in disposition.lower() or 'not related' in disposition.lower():
                    not_reserve_related.append(kw)
                else:
                    included_in_movements.append(kw)
            
            if not_reserve_related:
                logger.info(f"  Keywords not reserve-related: {not_reserve_related}")
            
            if unaddressed:
                logger.warning(f"  Syndicate {syndicate} ({year}): Unaddressed keywords: {unaddressed}")
                # Add to data quality notes
                missed_str = f"AUDIT: Unaddressed keywords: {', '.join(unaddressed)}"
                for m in movements:
                    existing_notes = m.data_quality_notes or ""
                    m.data_quality_notes = f"{existing_notes} {missed_str}".strip()
        
        return movements
    
    def _standardize_lob_name(self, raw_name: str) -> str:
        """Map raw LOB/division name to standard Lloyd's category."""
        if not raw_name:
            return "Aggregate"
        
        # Normalize: lowercase, remove special chars, collapse whitespace
        normalized = raw_name.lower().strip()
        normalized = re.sub(r'[^a-z0-9\s&]', '', normalized)
        normalized = re.sub(r'\s+', ' ', normalized).strip()
        
        # Direct lookup
        if normalized in self.LOB_MAPPING:
            return self.LOB_MAPPING[normalized]
        
        # Try with underscores instead of spaces
        normalized_underscore = normalized.replace(' ', '_')
        if normalized_underscore in self.LOB_MAPPING:
            return self.LOB_MAPPING[normalized_underscore]
        
        # Check if raw_name is already a standard LOB
        for std_lob in self.STANDARD_LOBS:
            if std_lob.lower() == normalized or std_lob.lower().replace(' - ', ' ') == normalized:
                return std_lob
        
        # Keyword-based matching (order matters - more specific first)
        keyword_rules = [
            # Reinsurance patterns
            (["treaty", "reinsurance", "retro"], ["casualty", "liability"], "Reinsurance - Casualty"),
            (["treaty", "reinsurance", "retro"], ["property", "cat", "catastrophe"], "Reinsurance - Property"),
            (["treaty", "reinsurance", "retro"], ["specialty", "special"], "Reinsurance - Specialty"),
            (["treaty", "reinsurance"], [], "Reinsurance - Property"),  # Default treaty
            
            # Direct lines - specific first
            (["professional", "d&o", "e&o", "indemnity", "financial lines"], [], "Professional Lines"),
            (["cyber", "technology", "data breach"], [], "Cyber"),
            (["accident", "health", "a&h", "personal accident", "travel"], [], "Accident & Health"),
            (["motor", "auto", "vehicle"], [], "Motor"),
            (["aviation", "aerospace", "airline", "space"], [], "Aviation"),
            (["energy", "offshore", "onshore", "oil", "gas", "power"], [], "Energy"),
            (["marine", "hull", "cargo", "specie", "war", "transport"], [], "Marine"),
            (["casualty", "liability", "gl"], [], "Casualty"),
            (["property", "fire", "commercial"], [], "Property"),
            
            # Specialty
            (["credit", "political", "surety", "bond", "terrorism", "contingency", "kidnap", "bloodstock"], [], "Reinsurance - Specialty"),
        ]
        
        for required_keywords, exclude_keywords, mapped_lob in keyword_rules:
            has_required = any(kw in normalized for kw in required_keywords)
            has_excluded = any(kw in normalized for kw in exclude_keywords) if exclude_keywords else False
            if has_required and not has_excluded:
                return mapped_lob
        
        # If still no match, return Aggregate with logging
        logger.warning(f"Could not map LOB '{raw_name}' to standard category, using 'Aggregate'")
        return "Aggregate"
    
    def batch_standardize(self,
                          quality_report: Dict,
                          min_quality: str = "HIGH",
                          max_reports: Optional[int] = None,
                          years: Optional[List[int]] = None) -> List[SyndicateReserveMovement]:
        """
        Batch process all usable reports.
        
        Args:
            quality_report: Loaded quality_report.json
            min_quality: Minimum quality level
            max_reports: Optional limit for testing
            years: Optional filter by years
        
        Returns:
            List of all standardized movements
        """
        reports = self.filter_usable_reports(quality_report, min_quality)
        
        # Filter by years if specified
        if years:
            reports = [r for r in reports if r.get('year') in years]
            logger.info(f"Filtered to {len(reports)} reports for years {years}")
        
        # Limit for testing
        if max_reports:
            reports = reports[:max_reports]
            logger.info(f"Limited to {max_reports} reports for processing")
        
        all_movements = []
        errors = []
        unaddressed_keywords = []
        
        for i, report in enumerate(reports):
            syndicate = report.get('syndicate')
            year = report.get('year')
            
            logger.info(f"Processing {i+1}/{len(reports)}: Syndicate {syndicate} ({year})")
            
            try:
                movements = self.standardize_single_report(report)
                all_movements.extend(movements)
                
                # Track unaddressed keywords
                for m in movements:
                    if m.data_quality_notes and 'AUDIT: Unaddressed keywords' in m.data_quality_notes:
                        unaddressed_keywords.append({
                            'syndicate': syndicate,
                            'year': year,
                            'lob': m.line_of_business,
                            'notes': m.data_quality_notes
                        })
                
                logger.info(f"  -> Extracted {len(movements)} movement(s)")
                
                # Rate limiting
                time.sleep(0.5)
                
            except Exception as e:
                logger.error(f"  -> Error: {e}")
                errors.append({
                    'syndicate': syndicate,
                    'year': year,
                    'error': str(e)
                })
                continue
        
        logger.info(f"\nBatch complete:")
        logger.info(f"  Processed: {len(reports)} reports")
        logger.info(f"  Movements extracted: {len(all_movements)}")
        logger.info(f"  Errors: {len(errors)}")
        logger.info(f"  Unaddressed keywords: {len(unaddressed_keywords)}")
        logger.info(f"  API calls: {self.api_calls}")
        logger.info(f"  Total tokens: {self.total_tokens}")
        
        return all_movements, errors
    
    def save_results(self,
                     movements: List[SyndicateReserveMovement],
                     errors: List[Dict],
                     output_dir: str,
                     include_raw: bool = False):
        """
        Save standardized results.
        
        Args:
            movements: List of standardized movements
            errors: List of processing errors
            output_dir: Output directory
            include_raw: Whether to include raw text in output (large file)
        """
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        
        # Prepare movements for JSON
        movements_data = []
        for m in movements:
            entry = asdict(m)
            if not include_raw:
                # Remove large raw text fields for compact output
                entry['raw_reserve_section'] = f"[{len(m.raw_reserve_section)} chars - see audit file]"
                entry['raw_strategic_report'] = f"[{len(m.raw_strategic_report)} chars - see audit file]"
            movements_data.append(entry)
        
        # Main output file
        main_output = {
            'generated_at': datetime.now().isoformat(),
            'total_movements': len(movements),
            'total_errors': len(errors),
            'api_calls': self.api_calls,
            'model_used': self.MODELS.get(self.model, self.model),
            'movements': movements_data
        }
        
        main_path = output_path / 'standardized_syndicate_movements.json'
        with open(main_path, 'w', encoding='utf-8') as f:
            json.dump(main_output, f, indent=2, ensure_ascii=False)
        logger.info(f"Saved main output to {main_path}")
        
        # Full audit file with raw text
        if include_raw:
            audit_path = output_path / 'standardized_syndicate_movements_full_audit.json'
            with open(audit_path, 'w', encoding='utf-8') as f:
                json.dump({'movements': [asdict(m) for m in movements]}, f, indent=2, ensure_ascii=False)
            logger.info(f"Saved full audit to {audit_path}")
        
        # Errors file
        if errors:
            errors_path = output_path / 'standardization_errors.json'
            with open(errors_path, 'w', encoding='utf-8') as f:
                json.dump(errors, f, indent=2)
            logger.info(f"Saved errors to {errors_path}")
        
        # Summary by syndicate
        syndicate_summary = {}
        for m in movements:
            key = m.syndicate
            if key not in syndicate_summary:
                syndicate_summary[key] = {
                    'syndicate': key,
                    'years': set(),
                    'lobs': set(),
                    'total_movements': 0,
                    'releases': 0,
                    'strengthenings': 0,
                }
            syndicate_summary[key]['years'].add(m.year)
            syndicate_summary[key]['lobs'].add(m.line_of_business)
            syndicate_summary[key]['total_movements'] += 1
            if m.direction == 'release':
                syndicate_summary[key]['releases'] += 1
            elif m.direction == 'strengthening':
                syndicate_summary[key]['strengthenings'] += 1
        
        # Convert sets to lists for JSON
        for key in syndicate_summary:
            syndicate_summary[key]['years'] = sorted(syndicate_summary[key]['years'])
            syndicate_summary[key]['lobs'] = sorted(syndicate_summary[key]['lobs'])
        
        summary_path = output_path / 'syndicate_summary.json'
        with open(summary_path, 'w', encoding='utf-8') as f:
            json.dump(list(syndicate_summary.values()), f, indent=2)
        logger.info(f"Saved syndicate summary to {summary_path}")
        
        # Summary by LOB
        lob_summary = {}
        for m in movements:
            key = m.line_of_business
            if key not in lob_summary:
                lob_summary[key] = {
                    'line_of_business': key,
                    'total_movements': 0,
                    'releases': 0,
                    'strengthenings': 0,
                    'syndicates': set(),
                    'causes': {},
                }
            lob_summary[key]['total_movements'] += 1
            lob_summary[key]['syndicates'].add(m.syndicate)
            if m.direction == 'release':
                lob_summary[key]['releases'] += 1
            elif m.direction == 'strengthening':
                lob_summary[key]['strengthenings'] += 1
            for cause in m.primary_causes:
                lob_summary[key]['causes'][cause] = lob_summary[key]['causes'].get(cause, 0) + 1
        
        # Convert sets to counts for JSON
        for key in lob_summary:
            lob_summary[key]['syndicate_count'] = len(lob_summary[key]['syndicates'])
            del lob_summary[key]['syndicates']
        
        lob_path = output_path / 'lob_summary.json'
        with open(lob_path, 'w', encoding='utf-8') as f:
            json.dump(list(lob_summary.values()), f, indent=2)
        logger.info(f"Saved LOB summary to {lob_path}")
        
        # Summary by year
        year_summary = {}
        for m in movements:
            key = m.year
            if key not in year_summary:
                year_summary[key] = {
                    'year': key,
                    'total_movements': 0,
                    'releases': 0,
                    'strengthenings': 0,
                    'syndicates': set(),
                }
            year_summary[key]['total_movements'] += 1
            year_summary[key]['syndicates'].add(m.syndicate)
            if m.direction == 'release':
                year_summary[key]['releases'] += 1
            elif m.direction == 'strengthening':
                year_summary[key]['strengthenings'] += 1
        
        for key in year_summary:
            year_summary[key]['syndicate_count'] = len(year_summary[key]['syndicates'])
            del year_summary[key]['syndicates']
        
        year_path = output_path / 'year_summary.json'
        with open(year_path, 'w', encoding='utf-8') as f:
            json.dump(sorted(year_summary.values(), key=lambda x: x['year']), f, indent=2)
        logger.info(f"Saved year summary to {year_path}")
        
        return main_path


# =============================================================================
# CLI Entry Point
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Standardize Lloyd's syndicate reserve commentary using ChatGPT"
    )
    parser.add_argument(
        "--input", "-i",
        required=True,
        help="Path to quality_report.json"
    )
    parser.add_argument(
        "--output-dir", "-o",
        default="./results/syndicate",
        help="Output directory (default: ./results/syndicate)"
    )
    parser.add_argument(
        "--min-quality",
        choices=["VERY_HIGH", "HIGH", "MEDIUM"],
        default="HIGH",
        help="Minimum quality level to process (default: HIGH)"
    )
    parser.add_argument(
        "--years",
        type=int,
        nargs="+",
        help="Filter to specific years (e.g., --years 2022 2023 2024)"
    )
    parser.add_argument(
        "--max-reports",
        type=int,
        help="Maximum reports to process (for testing)"
    )
    parser.add_argument(
        "--model",
        choices=["fast", "balanced", "best"],
        default="balanced",
        help="Model to use (default: balanced = gpt-4-turbo)"
    )
    parser.add_argument(
        "--include-raw",
        action="store_true",
        help="Include raw text in output (creates large file)"
    )
    
    args = parser.parse_args()
    
    # Load quality report
    logger.info(f"Loading quality report from {args.input}")
    with open(args.input, 'r', encoding='utf-8') as f:
        quality_report = json.load(f)
    
    logger.info(f"Loaded {len(quality_report.get('reports', quality_report.get('assessments', [])))} reports")
    
    # Initialize summarizer
    summarizer = SyndicateSummarizer(model=args.model)
    
    # Process
    movements, errors = summarizer.batch_standardize(
        quality_report,
        min_quality=args.min_quality,
        max_reports=args.max_reports,
        years=args.years
    )
    
    # Save results
    summarizer.save_results(
        movements,
        errors,
        args.output_dir,
        include_raw=args.include_raw
    )
    
    # Print summary
    print(f"\n{'='*60}")
    print("SYNDICATE SUMMARIZATION COMPLETE")
    print(f"{'='*60}")
    print(f"Reports processed: {len(quality_report.get('reports', quality_report.get('assessments', []))) if not args.max_reports else min(args.max_reports, len(quality_report.get('reports', quality_report.get('assessments', []))))}")
    print(f"Movements extracted: {len(movements)}")
    print(f"Errors: {len(errors)}")
    print(f"Output directory: {args.output_dir}")
    print(f"API calls made: {summarizer.api_calls}")
    print(f"Total tokens used: {summarizer.total_tokens}")


if __name__ == "__main__":
    main()