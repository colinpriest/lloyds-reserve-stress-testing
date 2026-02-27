#!/usr/bin/env python3
"""
ChatGPT Summarization & Standardization Module
==============================================
Uses OpenAI ChatGPT API to:
1. Summarize scraped reserve commentary
2. Standardize wording across sources for each line of business
3. Extract structured data (direction, %, amounts, causes)
4. Generate consistent training data for LLM stress testing

ChatGPT is used for SUMMARIZATION - Perplexity is used for SOURCE DISCOVERY.
"""

import os
import re
import json
import time
import logging
from dataclasses import dataclass, asdict, field
from typing import List, Dict, Optional, Any, Tuple
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
import requests

# Load environment variables from .env file
load_dotenv()

logger = logging.getLogger(__name__)


@dataclass
class StandardizedReserveMovement:
    """Standardized reserve movement record with full audit trail."""
    year: int
    line_of_business: str
    direction: str  # 'release', 'strengthening', 'flat'
    percentage: Optional[float] = None
    amount_gbp_m: Optional[float] = None
    primary_causes: List[str] = field(default_factory=list)
    specific_events: List[str] = field(default_factory=list)
    standardized_narrative: str = ""
    source_urls: List[str] = field(default_factory=list)
    confidence: str = "medium"
    # Audit trail - keep ALL raw extracts
    raw_extracts: List[str] = field(default_factory=list)
    source_files: List[str] = field(default_factory=list)  # Paths to full text files
    source_hashes: List[str] = field(default_factory=list)  # SHA256 hashes of sources
    standardized_at: str = ""
    standardization_model: str = ""  # e.g., "gpt-4-turbo"


@dataclass
class LOBSummary:
    """Complete summary for a line of business."""
    line_of_business: str
    year: int
    executive_summary: str
    movement: StandardizedReserveMovement
    trend_vs_prior_years: str
    market_context: str
    forward_looking: str
    sources_used: int


class ChatGPTSummarizer:
    """
    Uses OpenAI ChatGPT to summarize and standardize reserve commentary.
    
    Key functions:
    1. Standardize terminology across different sources
    2. Extract structured data from narrative text
    3. Generate consistent LOB summaries
    4. Create training data for stress test LLM
    """
    
    MODELS = {
        "fast": "gpt-3.5-turbo",
        "balanced": "gpt-4-turbo",
        "best": "gpt-4o",
    }
    
    # Standard LOB names (for consistent output)
    STANDARD_LOB_NAMES = {
        # Reinsurance
        "reinsurance_property": "Reinsurance - Property",
        "reinsurance_casualty": "Reinsurance - Casualty",
        "reinsurance_specialty": "Reinsurance - Specialty",
        # Direct/Insurance
        "property": "Property (Direct)",
        "casualty": "Casualty (Direct)",
        "marine_aviation_transport": "Marine, Aviation & Transport",
        "energy": "Energy",
        "motor": "Motor",
    }
    
    # Standard causal categories
    CAUSAL_CATEGORIES = [
        "Social inflation / litigation trends",
        "Economic inflation / claims cost inflation",
        "Natural catastrophe events",
        "Man-made catastrophe / large losses",
        "Court rulings / legal developments",
        "Regulatory changes",
        "Ogden discount rate",
        "COVID-19 / pandemic effects",
        "Geopolitical events (Ukraine, etc.)",
        "Reinsurance market factors",
        "Favorable claims development",
        "Adverse claims development",
        "IBNR recalibration",
        "Management margin release",
    ]
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OpenAI API key required. Set OPENAI_API_KEY env var.")
        
        self.api_url = "https://api.openai.com/v1/chat/completions"
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        })
    
    def _call_api(self, 
                  system_prompt: str,
                  user_prompt: str, 
                  model: str = "balanced",
                  temperature: float = 0.2,
                  response_format: Optional[Dict] = None) -> str:
        """Make API call to OpenAI."""
        
        payload = {
            "model": self.MODELS.get(model, self.MODELS["balanced"]),
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": temperature,
            "max_tokens": 2000,
        }
        
        if response_format:
            payload["response_format"] = response_format
        
        try:
            response = self.session.post(self.api_url, json=payload, timeout=60)
            response.raise_for_status()
            return response.json()['choices'][0]['message']['content']
        except Exception as e:
            logger.error(f"OpenAI API error: {e}")
            raise
    
    def standardize_lob_commentary(self, 
                                   raw_texts: List[str],
                                   lob: str,
                                   year: int,
                                   source_urls: List[str] = None,
                                   source_files: List[str] = None,
                                   source_hashes: List[str] = None) -> StandardizedReserveMovement:
        """
        Take raw commentary extracts and standardize into consistent format.
        
        Args:
            raw_texts: List of raw text extracts mentioning this LOB
            lob: Line of business name
            year: Year of the commentary
            source_urls: URLs of sources
            source_files: Paths to full text files (for audit)
            source_hashes: SHA256 hashes of source content (for audit)
        """
        
        system_prompt = """You are an expert actuarial analyst standardizing Lloyd's market reserve commentary.

Your task is to extract and standardize information from multiple sources into a consistent format.

STANDARDIZATION RULES:
1. Direction: Use ONLY 'release' (favorable/redundancy), 'strengthening' (adverse/deficiency), or 'flat'
2. Percentages: Express as prior year development as % of net earned premium (e.g., "3.6%")
3. Amounts: Express in GBP millions (e.g., "£322m")
4. Causes: Map to standard categories:
   - "Social inflation / litigation trends"
   - "Economic inflation / claims cost inflation"  
   - "Natural catastrophe events"
   - "Man-made catastrophe / large losses"
   - "Court rulings / legal developments"
   - "Regulatory changes"
   - "Ogden discount rate"
   - "COVID-19 / pandemic effects"
   - "Geopolitical events (Ukraine, etc.)"
   - "Favorable claims development"
   - "Adverse claims development"
   - "IBNR recalibration"
   - "Management margin release"

5. Events: List specific named events (e.g., "Hurricane Ian (2022)", "FCA BI test case")

OUTPUT FORMAT (JSON):
{
    "direction": "release|strengthening|flat",
    "percentage": 3.6,
    "amount_gbp_m": 322,
    "primary_causes": ["cause1", "cause2"],
    "specific_events": ["event1", "event2"],
    "standardized_narrative": "One paragraph summary in consistent actuarial language",
    "confidence": "high|medium|low",
    "data_quality_notes": "Any caveats about data availability"
}

If data is missing or conflicting, note it in data_quality_notes and set confidence accordingly."""

        # Combine raw texts - keep all for context but send limited to API
        combined_text = "\n\n---SOURCE---\n\n".join(raw_texts[:5])  # Limit to 5 for API
        
        user_prompt = f"""Standardize the following reserve commentary for:
Line of Business: {lob}
Year: {year}

RAW EXTRACTS FROM MULTIPLE SOURCES:
{combined_text}

Extract and standardize into JSON format. If sources conflict, note the discrepancy."""

        model_used = self.MODELS.get("balanced", "gpt-4-turbo")
        
        response = self._call_api(
            system_prompt, 
            user_prompt, 
            model="balanced",
            response_format={"type": "json_object"}
        )
        
        # Parse response
        try:
            data = json.loads(response)
        except json.JSONDecodeError:
            # Try to extract JSON from response
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
            else:
                data = {}
        
        return StandardizedReserveMovement(
            year=year,
            line_of_business=self.STANDARD_LOB_NAMES.get(lob.lower().replace(' ', '_'), lob),
            direction=data.get('direction', 'unknown'),
            percentage=data.get('percentage'),
            amount_gbp_m=data.get('amount_gbp_m'),
            primary_causes=data.get('primary_causes', []),
            specific_events=data.get('specific_events', []),
            standardized_narrative=data.get('standardized_narrative', ''),
            source_urls=source_urls or [],
            confidence=data.get('confidence', 'medium'),
            # Full audit trail - keep ALL raw extracts
            raw_extracts=raw_texts,  # Keep all, not truncated
            source_files=source_files or [],
            source_hashes=source_hashes or [],
            standardized_at=datetime.now().isoformat(),
            standardization_model=model_used
        )
    
    def generate_lob_summary(self,
                             movement: StandardizedReserveMovement,
                             historical_context: List[StandardizedReserveMovement] = None) -> LOBSummary:
        """Generate comprehensive summary for a line of business."""
        
        system_prompt = """You are writing a professional actuarial summary of Lloyd's market reserve development.

Write in clear, precise actuarial language suitable for:
- Academic papers on reserve stress testing
- Regulatory submissions
- Board reports

Structure:
1. Executive Summary (2-3 sentences): Key finding and magnitude
2. Trend vs Prior Years: How does this compare to recent history
3. Market Context: What market conditions explain this
4. Forward Looking: What to watch for

Use specific numbers where available. Be objective and balanced."""

        # Build context
        historical_text = ""
        if historical_context:
            historical_text = "\n".join([
                f"- {h.year}: {h.direction} of {h.percentage}% ({', '.join(h.primary_causes[:2])})"
                for h in historical_context
            ])
        
        user_prompt = f"""Generate a professional summary for:

LINE OF BUSINESS: {movement.line_of_business}
YEAR: {movement.year}

STANDARDIZED DATA:
- Direction: {movement.direction}
- Percentage: {movement.percentage}% of NEP
- Amount: £{movement.amount_gbp_m}m
- Primary causes: {', '.join(movement.primary_causes)}
- Specific events: {', '.join(movement.specific_events)}

HISTORICAL CONTEXT:
{historical_text if historical_text else "Not available"}

Generate:
1. executive_summary (2-3 sentences)
2. trend_vs_prior_years (1-2 sentences)
3. market_context (2-3 sentences)  
4. forward_looking (1-2 sentences)"""

        response = self._call_api(system_prompt, user_prompt, model="balanced")
        
        # Parse sections from response
        sections = self._parse_summary_sections(response)
        
        return LOBSummary(
            line_of_business=movement.line_of_business,
            year=movement.year,
            executive_summary=sections.get('executive_summary', ''),
            movement=movement,
            trend_vs_prior_years=sections.get('trend_vs_prior_years', ''),
            market_context=sections.get('market_context', ''),
            forward_looking=sections.get('forward_looking', ''),
            sources_used=len(movement.source_urls)
        )
    
    def _parse_summary_sections(self, response: str) -> Dict[str, str]:
        """Parse numbered sections from response."""
        sections = {}
        
        patterns = [
            (r'executive[_ ]?summary[:\s]*([^0-9]+?)(?=\d\.|$)', 'executive_summary'),
            (r'trend[_ ]?vs[_ ]?prior[_ ]?years?[:\s]*([^0-9]+?)(?=\d\.|$)', 'trend_vs_prior_years'),
            (r'market[_ ]?context[:\s]*([^0-9]+?)(?=\d\.|$)', 'market_context'),
            (r'forward[_ ]?looking[:\s]*([^0-9]+?)(?=\d\.|$)', 'forward_looking'),
        ]
        
        for pattern, key in patterns:
            match = re.search(pattern, response, re.IGNORECASE | re.DOTALL)
            if match:
                sections[key] = match.group(1).strip()
        
        # Fallback: split by numbers
        if not sections:
            parts = re.split(r'\d+\.', response)
            if len(parts) >= 4:
                sections = {
                    'executive_summary': parts[1].strip() if len(parts) > 1 else '',
                    'trend_vs_prior_years': parts[2].strip() if len(parts) > 2 else '',
                    'market_context': parts[3].strip() if len(parts) > 3 else '',
                    'forward_looking': parts[4].strip() if len(parts) > 4 else '',
                }
        
        return sections
    
    def batch_standardize(self,
                          scraped_data: Dict[str, Any],
                          year: int) -> Dict[str, StandardizedReserveMovement]:
        """
        Process all scraped data for a year and standardize by LOB.
        
        Args:
            scraped_data: Output from market_commentary_scraper
            year: Year to process
        """
        
        # Group extracts by LOB with full audit trail
        lob_extracts = {lob: [] for lob in self.STANDARD_LOB_NAMES.values()}
        lob_urls = {lob: [] for lob in self.STANDARD_LOB_NAMES.values()}
        lob_files = {lob: [] for lob in self.STANDARD_LOB_NAMES.values()}
        lob_hashes = {lob: [] for lob in self.STANDARD_LOB_NAMES.values()}
        
        for source in scraped_data.get('sources', []):
            if source.get('year') != year:
                continue
            
            source_url = source.get('url', '')
            source_file = source.get('full_text_file', '')
            source_hash = source.get('content_hash', '')
            
            # Map source LOB mentions to standard names
            for raw_lob, extracts in source.get('lines_of_business', {}).items():
                std_lob = self._map_to_standard_lob(raw_lob)
                if std_lob:
                    lob_extracts[std_lob].extend(extracts)
                    if source_url and source_url not in lob_urls[std_lob]:
                        lob_urls[std_lob].append(source_url)
                    if source_file and source_file not in lob_files[std_lob]:
                        lob_files[std_lob].append(source_file)
                    if source_hash and source_hash not in lob_hashes[std_lob]:
                        lob_hashes[std_lob].append(source_hash)
            
            # Also add causal statements
            for stmt in source.get('causal_statements', []):
                # Try to identify which LOB this relates to
                for std_lob in self.STANDARD_LOB_NAMES.values():
                    if any(term in stmt.lower() for term in std_lob.lower().split()):
                        lob_extracts[std_lob].append(stmt)
                        if source_url and source_url not in lob_urls[std_lob]:
                            lob_urls[std_lob].append(source_url)
                        if source_file and source_file not in lob_files[std_lob]:
                            lob_files[std_lob].append(source_file)
                        if source_hash and source_hash not in lob_hashes[std_lob]:
                            lob_hashes[std_lob].append(source_hash)
                        break
        
        # Standardize each LOB
        results = {}
        for lob, extracts in lob_extracts.items():
            if not extracts:
                continue
            
            logger.info(f"Standardizing {lob} ({len(extracts)} extracts from {len(lob_files[lob])} files)...")
            
            try:
                movement = self.standardize_lob_commentary(
                    extracts,
                    lob,
                    year,
                    source_urls=lob_urls[lob],
                    source_files=lob_files[lob],
                    source_hashes=lob_hashes[lob]
                )
                results[lob] = movement
                
                time.sleep(1)  # Rate limiting
                
            except Exception as e:
                logger.error(f"Error standardizing {lob}: {e}")
                continue
        
        return results
    
    def _map_to_standard_lob(self, raw_lob: str) -> Optional[str]:
        """Map various LOB names to standard names."""
        
        raw_lower = raw_lob.lower()
        
        mappings = [
            (['reinsurance', 'property', 'cat'], "Reinsurance - Property"),
            (['reinsurance', 'casualty', 'liability'], "Reinsurance - Casualty"),
            (['reinsurance', 'special', 'marine'], "Reinsurance - Specialty"),
            (['property', 'direct', 'fire'], "Property (Direct)"),
            (['casualty', 'direct', 'liability', 'professional'], "Casualty (Direct)"),
            (['marine', 'aviation', 'transport', 'mat'], "Marine, Aviation & Transport"),
            (['energy', 'oil', 'gas', 'power'], "Energy"),
            (['motor', 'auto', 'vehicle'], "Motor"),
        ]
        
        for keywords, std_name in mappings:
            if any(kw in raw_lower for kw in keywords):
                return std_name
        
        return None
    
    def generate_stress_test_training_data(self,
                                           movements: List[StandardizedReserveMovement]) -> List[Dict]:
        """
        Generate training examples for stress test LLM.
        
        Format suitable for fine-tuning or few-shot prompting.
        """
        
        system_prompt = """You are generating training data for an LLM that creates reserve stress test scenarios.

For each standardized reserve movement, generate:
1. A "scenario prompt" - what a user might ask
2. A "scenario response" - the stress test narrative

The response should:
- Match the severity (percentage/amount) of the input
- Include the causal factors mentioned
- Be written in actuarial regulatory language
- Be suitable for ORSA/SCR documentation

OUTPUT FORMAT (JSON):
{
    "prompt": "Generate a {direction} scenario for {LOB} of approximately {X}%",
    "response": "The scenario narrative...",
    "metadata": {
        "lob": "...",
        "direction": "...",
        "severity_pct": X,
        "causes": [...]
    }
}"""

        training_data = []
        
        for movement in movements:
            user_prompt = f"""Generate training example from:

LOB: {movement.line_of_business}
Year: {movement.year}
Direction: {movement.direction}
Percentage: {movement.percentage}%
Amount: £{movement.amount_gbp_m}m
Causes: {', '.join(movement.primary_causes)}
Events: {', '.join(movement.specific_events)}
Narrative: {movement.standardized_narrative}"""

            try:
                response = self._call_api(
                    system_prompt, 
                    user_prompt,
                    model="balanced",
                    response_format={"type": "json_object"}
                )
                
                data = json.loads(response)
                data['source_year'] = movement.year
                data['source_lob'] = movement.line_of_business
                training_data.append(data)
                
                time.sleep(0.5)
                
            except Exception as e:
                logger.error(f"Error generating training data: {e}")
                continue
        
        return training_data


class MarketReportGenerator:
    """Generates comprehensive market reports using ChatGPT."""
    
    def __init__(self, summarizer: ChatGPTSummarizer):
        self.summarizer = summarizer
    
    def generate_annual_report(self,
                               year: int,
                               lob_summaries: Dict[str, LOBSummary]) -> str:
        """Generate a complete annual market report."""
        
        system_prompt = """You are writing a professional Lloyd's market reserve development report.

Structure:
1. Executive Summary - Overall market direction, key themes
2. Line of Business Analysis - Each LOB with numbers
3. Causal Factor Analysis - Thematic deep dives
4. Forward-Looking Commentary - Areas of concern

Write in professional actuarial language. Use specific numbers.
Format as Markdown with clear headers."""

        # Build LOB section
        lob_text = ""
        for lob, summary in lob_summaries.items():
            lob_text += f"""
### {lob}
- Direction: {summary.movement.direction}
- Movement: {summary.movement.percentage}% (£{summary.movement.amount_gbp_m}m)
- Primary causes: {', '.join(summary.movement.primary_causes)}
- Summary: {summary.executive_summary}
"""
        
        user_prompt = f"""Generate a comprehensive Lloyd's market reserve report for {year}.

LINE OF BUSINESS DATA:
{lob_text}

Include:
1. Executive summary synthesizing across all LOBs
2. Analysis of each LOB (use the data provided)
3. Thematic analysis of causal factors
4. Forward-looking concerns

Format as professional Markdown report."""

        response = self.summarizer._call_api(
            system_prompt, 
            user_prompt, 
            model="best",
            temperature=0.3
        )
        
        # Add header and metadata
        report = f"""# Lloyd's Market Reserve Development Report {year}

*Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}*
*Sources: Standardized from multiple market commentary sources*

---

{response}

---

## Data Sources

This report synthesizes data from:
- Lloyd's Annual Report {year}
- Lloyd's Half Year Report {year}
- AM Best Lloyd's Rating Report
- Trade press (Reinsurance News, Artemis, Insurance Journal)
- Broker and analyst commentary

## Methodology

Reserve movements were extracted from multiple sources and standardized using:
1. Perplexity API for source discovery
2. Web scraping for content extraction
3. ChatGPT for standardization and summarization

All percentages are prior year development as % of net earned premium unless otherwise stated.
"""
        
        return report


def main():
    """Main entry point."""
    import argparse
    
    logging.basicConfig(level=logging.INFO)
    
    parser = argparse.ArgumentParser(description="Summarize Lloyd's commentary using ChatGPT")
    parser.add_argument("--input", required=True, help="Input JSON from scraper")
    parser.add_argument("--years", nargs="+", type=int, default=None,
                        help="Years to process (default: all years found in input)")
    parser.add_argument("--output-dir", default="./standardized", help="Output directory")
    parser.add_argument("--generate-training", action="store_true",
                        help="Generate stress test training data")

    args = parser.parse_args()

    # Load scraped data
    with open(args.input, 'r', encoding='utf-8') as f:
        scraped_data = json.load(f)

    # Determine years to process
    if args.years:
        years_to_process = args.years
    else:
        # Extract all unique years from the scraped data
        years_to_process = sorted(set(
            source.get('year') for source in scraped_data.get('sources', [])
            if source.get('year')
        ))
        if not years_to_process:
            years_to_process = list(range(2014, 2025))

    summarizer = ChatGPTSummarizer()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    all_movements = {}
    all_training_data = []

    for year in years_to_process:
        print(f"\n{'='*60}")
        print(f"Processing year {year}")
        print(f"{'='*60}")

        # Standardize all LOBs for this year
        logger.info(f"Standardizing commentary for {year}...")
        movements = summarizer.batch_standardize(scraped_data, year)

        if not movements:
            logger.warning(f"No data found for year {year}, skipping...")
            continue

        all_movements[year] = movements

        # Generate summaries
        summaries = {}
        for lob, movement in movements.items():
            logger.info(f"Generating summary for {lob}...")
            summaries[lob] = summarizer.generate_lob_summary(movement)

        # Save standardized movements
        movements_path = output_dir / f"standardized_movements_{year}.json"
        with open(movements_path, 'w') as f:
            json.dump({lob: asdict(m) for lob, m in movements.items()}, f, indent=2)
        logger.info(f"Saved movements to {movements_path}")

        # Save summaries
        summaries_path = output_dir / f"lob_summaries_{year}.json"
        with open(summaries_path, 'w') as f:
            json.dump({lob: asdict(s) for lob, s in summaries.items()}, f, indent=2)
        logger.info(f"Saved summaries to {summaries_path}")

        # Generate report
        report_gen = MarketReportGenerator(summarizer)
        report = report_gen.generate_annual_report(year, summaries)

        report_path = output_dir / f"market_report_{year}.md"
        with open(report_path, 'w') as f:
            f.write(report)
        logger.info(f"Saved report to {report_path}")

        # Collect training data if requested
        if args.generate_training:
            training_data = summarizer.generate_stress_test_training_data(list(movements.values()))
            all_training_data.extend(training_data)

            # Also save per-year training data
            training_path = output_dir / f"training_data_{year}.json"
            with open(training_path, 'w') as f:
                json.dump(training_data, f, indent=2)
            logger.info(f"Saved training data to {training_path}")

        print(f"\n=== Year {year} Summary ===")
        print(f"Processed {len(movements)} lines of business")
        for lob, movement in movements.items():
            print(f"  {lob}: {movement.direction} {movement.percentage}%")

    # Save combined training data if requested
    if args.generate_training and all_training_data:
        combined_training_path = output_dir / "training_data_all_years.json"
        with open(combined_training_path, 'w') as f:
            json.dump(all_training_data, f, indent=2)
        logger.info(f"Saved combined training data to {combined_training_path}")

    # Final summary
    print(f"\n{'='*60}")
    print(f"=== Final Summary ===")
    print(f"{'='*60}")
    print(f"Processed {len(all_movements)} years: {list(all_movements.keys())}")
    print(f"Output directory: {output_dir.absolute()}")


if __name__ == "__main__":
    main()
