"""
Step 4: Stratified Synthetic Scenario Generation

Generates synthetic scenarios across severity × complexity grid:
- For each cell, retrieve k=7 diverse neighbours
- Few-shot prompt includes examples showing diversification effects
- Generate 5× scenarios per cell for over-generation
"""

import sys
from pathlib import Path
_script_dir = Path(__file__).resolve().parent
if str(_script_dir) not in sys.path:
    sys.path.insert(0, str(_script_dir))

import json
import logging
import numpy as np
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from collections import defaultdict
import time
import hashlib

from openai import OpenAI

from config import (
    GenerationConfig, DEFAULT_GENERATION_CONFIG,
    HistoricalMovement, SyntheticScenario, CauseCategory,
    LLOYDS_LOBS, LOB_TO_INDEX
)
from joint_embedding import JointEmbeddingSpace

logger = logging.getLogger(__name__)


# =============================================================================
# LOB Normalization
# =============================================================================

# Map variant LOB names to standard Lloyd's LOBs
LOB_NORMALIZATION = {
    # Property variants
    'property': 'Property',
    'commercial property': 'Property',
    'industrial property': 'Property',
    'homeowners': 'Property',
    'business interruption': 'Property',
    
    # Casualty variants
    'casualty': 'Casualty',
    'general liability': 'Casualty',
    'liability': 'Casualty',
    'product liability': 'Casualty',
    'environmental liability': 'Casualty',
    'environmental': 'Casualty',
    'employers liability': 'Casualty',
    'workers compensation': 'Casualty',
    "workers' compensation": 'Casualty',
    'medical malpractice': 'Casualty',
    'healthcare liability': 'Casualty',
    
    # Marine variants
    'marine': 'Marine',
    'hull': 'Marine',
    'cargo': 'Marine',
    'marine liability': 'Marine',
    
    # Energy variants
    'energy': 'Energy',
    'oil & gas': 'Energy',
    'offshore': 'Energy',
    'power generation': 'Energy',
    
    # Motor variants
    'motor': 'Motor',
    'auto': 'Motor',
    'automobile': 'Motor',
    'commercial auto': 'Motor',
    'auto liability': 'Motor',
    
    # Aviation variants
    'aviation': 'Aviation',
    'aerospace': 'Aviation',
    'airline': 'Aviation',
    
    # Reinsurance variants
    'reinsurance - property': 'Reinsurance - Property',
    'reinsurance property': 'Reinsurance - Property',
    'property reinsurance': 'Reinsurance - Property',
    'reinsurance - casualty': 'Reinsurance - Casualty',
    'reinsurance casualty': 'Reinsurance - Casualty',
    'casualty reinsurance': 'Reinsurance - Casualty',
    'reinsurance - specialty': 'Reinsurance - Specialty',
    'reinsurance specialty': 'Reinsurance - Specialty',
    'specialty reinsurance': 'Reinsurance - Specialty',
    'reinsurance': 'Reinsurance - Property',  # Default
    
    # Professional Lines variants
    'professional lines': 'Professional Lines',
    'professional liability': 'Professional Lines',
    'professional indemnity': 'Professional Lines',
    'd&o': 'Professional Lines',
    'directors & officers': 'Professional Lines',
    'directors and officers': 'Professional Lines',
    'e&o': 'Professional Lines',
    'errors & omissions': 'Professional Lines',
    'errors and omissions': 'Professional Lines',
    'employment practices liability': 'Professional Lines',
    'financial lines': 'Professional Lines',
    'financial institutions': 'Professional Lines',
    'technology e&o': 'Professional Lines',
    
    # Accident & Health variants
    'accident & health': 'Accident & Health',
    'accident and health': 'Accident & Health',
    'health': 'Accident & Health',
    'life': 'Accident & Health',
    'travel': 'Accident & Health',
    'personal accident': 'Accident & Health',
    
    # Cyber variants
    'cyber': 'Cyber',
    'cybersecurity': 'Cyber',
    'technology': 'Cyber',
    
    # Specialty / Other -> map to closest
    'political risk': 'Professional Lines',
    'trade credit': 'Professional Lines',
    'credit': 'Professional Lines',
    'surety': 'Professional Lines',
    'terrorism': 'Property',
    'war': 'Property',
    'construction': 'Property',
    'engineering': 'Property',
    'event cancellation': 'Property',
    'agriculture': 'Property',
    'agricultural': 'Property',
    'specialty': 'Professional Lines',
    'annuities': 'Accident & Health',
    'pharmaceutical': 'Casualty',
    'industrial': 'Property',
}


def normalize_lob(lob_name: str) -> str:
    """Normalize a LOB name to standard Lloyd's LOB."""
    if not lob_name:
        return 'Aggregate'
    
    # Check if already standard
    if lob_name in LLOYDS_LOBS:
        return lob_name
    
    # Try lowercase lookup
    lower = lob_name.lower().strip()
    if lower in LOB_NORMALIZATION:
        return LOB_NORMALIZATION[lower]
    
    # Try partial matching
    for key, value in LOB_NORMALIZATION.items():
        if key in lower or lower in key:
            return value
    
    # Default to Aggregate for unknown
    logger.debug(f"Unknown LOB '{lob_name}' mapped to 'Aggregate'")
    return 'Aggregate'


def normalize_lob_breakdown(lob_breakdown: Dict[str, float]) -> Dict[str, float]:
    """Normalize all LOBs in a breakdown dict."""
    if not lob_breakdown:
        return {}
    
    normalized = {}
    for lob, value in lob_breakdown.items():
        std_lob = normalize_lob(lob)
        if std_lob in normalized:
            normalized[std_lob] += value
        else:
            normalized[std_lob] = value
    
    return normalized


# =============================================================================
# Robust JSON Parsing
# =============================================================================

def parse_json_robust(content: str) -> List[Dict]:
    """
    Parse JSON with repair logic for common LLM output issues:
    - Truncated responses
    - Unterminated strings
    - Missing closing brackets
    """
    content = content.strip()
    
    # Try direct parsing first
    try:
        result = json.loads(content)
        if isinstance(result, list):
            return result
        elif isinstance(result, dict) and 'scenarios' in result:
            return result['scenarios']
        elif isinstance(result, dict):
            return [result]
        return []
    except json.JSONDecodeError:
        pass
    
    # Try to repair truncated JSON
    repaired = repair_truncated_json(content)
    if repaired:
        try:
            result = json.loads(repaired)
            if isinstance(result, list):
                return result
            return []
        except json.JSONDecodeError:
            pass
    
    # Try to extract individual scenario objects using regex
    scenarios = extract_scenarios_regex(content)
    if scenarios:
        return scenarios
    
    return []


def repair_truncated_json(content: str) -> Optional[str]:
    """Attempt to repair truncated JSON by closing open brackets."""
    # Count brackets
    open_brackets = content.count('[') - content.count(']')
    open_braces = content.count('{') - content.count('}')
    
    # If we have unclosed structures, try to close them
    if open_brackets > 0 or open_braces > 0:
        # Find the last complete object
        last_complete = find_last_complete_object(content)
        if last_complete:
            return last_complete
        
        # Otherwise, try closing brackets
        repaired = content.rstrip().rstrip(',')
        
        # Close any open strings (rough heuristic)
        quote_count = repaired.count('"') - repaired.count('\\"')
        if quote_count % 2 == 1:
            repaired += '"'
        
        # Close braces and brackets
        repaired += '}' * open_braces
        repaired += ']' * open_brackets
        
        return repaired
    
    return content


def find_last_complete_object(content: str) -> Optional[str]:
    """Find the position of the last complete JSON object in an array."""
    # Look for pattern: }, followed by optional whitespace, then ] or ,
    import re
    
    # Find all positions where an object ends
    matches = list(re.finditer(r'\}\s*(?=[,\]])', content))
    
    if not matches:
        return None
    
    # Try progressively from the last match
    for match in reversed(matches):
        candidate = content[:match.end()]
        # Ensure it starts with [ and close it
        if candidate.strip().startswith('['):
            test = candidate.rstrip().rstrip(',') + ']'
            try:
                json.loads(test)
                return test
            except json.JSONDecodeError:
                continue
    
    return None


def extract_scenarios_regex(content: str) -> List[Dict]:
    """Extract scenario objects using regex as fallback."""
    import re
    
    scenarios = []
    
    # Pattern to match individual scenario objects
    # Look for objects with scenario_name or severity_ratio keys
    pattern = r'\{[^{}]*"(?:scenario_name|severity_ratio)"[^{}]*\}'
    
    matches = re.findall(pattern, content, re.DOTALL)
    
    for match in matches:
        try:
            obj = json.loads(match)
            scenarios.append(obj)
        except json.JSONDecodeError:
            # Try to repair this individual object
            try:
                # Fix common issues
                fixed = match.replace("'", '"')
                fixed = re.sub(r',\s*}', '}', fixed)  # Remove trailing commas
                obj = json.loads(fixed)
                scenarios.append(obj)
            except json.JSONDecodeError:
                continue
    
    return scenarios


# =============================================================================
# Few-Shot Example Selection
# =============================================================================

def select_diverse_examples(
    neighbours: List[Tuple[HistoricalMovement, float]],
    target_complexity: float,
    min_years: int = 3
) -> List[HistoricalMovement]:
    """
    Select diverse examples from neighbours that demonstrate:
    - Range of complexity scores (to show diversification effect)
    - Multiple years
    - Different cause types
    """
    if not neighbours:
        return []
    
    movements = [m for m, _ in neighbours]
    
    # Sort by complexity to show range
    by_complexity = sorted(movements, key=lambda m: m.complexity_score)
    
    selected = []
    years_seen = set()
    causes_seen = set()
    
    # Strategy: interleave low, high, and target complexity examples
    # to teach the LLM about diversification effects
    
    # 1. Include lowest complexity example (monoline)
    if by_complexity:
        selected.append(by_complexity[0])
        years_seen.add(by_complexity[0].year)
        causes_seen.add(by_complexity[0].primary_causes[0] if by_complexity[0].primary_causes else 'unknown')
    
    # 2. Include highest complexity example (diversified)
    if len(by_complexity) > 1:
        selected.append(by_complexity[-1])
        years_seen.add(by_complexity[-1].year)
        if by_complexity[-1].primary_causes:
            causes_seen.add(by_complexity[-1].primary_causes[0])
    
    # 3. Include example closest to target complexity
    if len(by_complexity) > 2:
        closest = min(movements, key=lambda m: abs(m.complexity_score - target_complexity))
        if closest not in selected:
            selected.append(closest)
            years_seen.add(closest.year)
    
    # 4. Fill remaining slots with year/cause diversity
    remaining = [m for m in movements if m not in selected]
    for m in remaining:
        if len(selected) >= 7:
            break
        
        # Prefer different years and causes
        new_year = m.year not in years_seen
        new_cause = (m.primary_causes[0] if m.primary_causes else 'unknown') not in causes_seen
        
        if new_year or new_cause or len(selected) < min_years:
            selected.append(m)
            years_seen.add(m.year)
            if m.primary_causes:
                causes_seen.add(m.primary_causes[0])
    
    return selected


def format_example_for_prompt(movement: HistoricalMovement) -> str:
    """Format a historical movement as a few-shot example."""
    
    # Compute HHI from LOB vector (approximation)
    lob_vec = movement.lob_vector or [0] * len(LLOYDS_LOBS)
    nonzero_lobs = [(LLOYDS_LOBS[i], v) for i, v in enumerate(lob_vec) if v > 0]
    
    if movement.complexity_score < 50:
        diversification = "monoline/concentrated"
    elif movement.complexity_score < 150:
        diversification = "moderately diversified"
    elif movement.complexity_score < 300:
        diversification = "well diversified"
    else:
        diversification = "highly diversified"
    
    events = ', '.join(movement.specific_events[:3]) if movement.specific_events else 'N/A'
    causes = ', '.join(movement.primary_causes[:2]) if movement.primary_causes else 'N/A'
    
    return f"""Year: {movement.year}
Syndicate: {movement.syndicate or 'N/A'}
Portfolio: {diversification} (complexity={movement.complexity_score:.0f})
LOB: {movement.line_of_business}
Severity: {movement.severity_ratio:.1%} adverse development
Causes: {causes}
Events: {events}
Narrative: {movement.narrative or 'N/A'}"""


# =============================================================================
# Prompt Construction
# =============================================================================

def build_generation_prompt(
    target_severity_bin: Tuple[float, float],
    target_complexity_bin: Tuple[float, float],
    examples: List[HistoricalMovement],
    n_scenarios: int = 5
) -> str:
    """
    Build the LLM prompt for scenario generation.
    """
    sev_lo, sev_hi = target_severity_bin
    comp_lo, comp_hi = target_complexity_bin
    
    # Format examples
    examples_text = "\n\n---\n\n".join([
        format_example_for_prompt(ex) for ex in examples
    ])
    
    # Complexity interpretation
    if comp_hi <= 50:
        portfolio_desc = "monoline or highly concentrated portfolios (single LOB dominates)"
        diversification_note = "These portfolios have minimal diversification benefit, so a single event can cause large swings."
    elif comp_hi <= 150:
        portfolio_desc = "moderately concentrated portfolios (2-3 main LOBs)"
        diversification_note = "Some diversification benefit exists, but concentration in a few LOBs means correlated events still cause significant impact."
    elif comp_hi <= 300:
        portfolio_desc = "moderately diversified portfolios (3-5 LOBs)"
        diversification_note = "Diversification provides meaningful protection, requiring either very large single events or correlated multi-LOB events to cause this severity."
    else:
        portfolio_desc = "well diversified portfolios (5+ LOBs)"
        diversification_note = "Strong diversification means only market-wide or systemic events (pandemic, extreme cat season, major regulatory change) typically cause this severity."
    
    prompt = f"""You are an expert actuarial analyst generating stress test scenarios for Lloyd's of London insurance syndicates.

Your task: Generate {n_scenarios} diverse, plausible adverse reserve development scenarios that could affect {portfolio_desc}.

TARGET PARAMETERS:
- Severity: {sev_lo:.0%} to {sev_hi:.0%} adverse prior-year development (as % of opening reserves)
- Portfolio complexity: {comp_lo:.0f} to {comp_hi:.0f} (where complexity = Total Reserves × (1 - HHI))
- {diversification_note}

HISTORICAL EXAMPLES at similar severity/complexity:

{examples_text}

GENERATION REQUIREMENTS:

1. SEVERITY CALIBRATION: Each scenario must result in {sev_lo:.0%} to {sev_hi:.0%} total adverse development.

2. LOB BREAKDOWN: You MUST use ONLY these Lloyd's lines of business (use exact names):
   - Property
   - Casualty  
   - Marine
   - Energy
   - Motor
   - Aviation
   - Reinsurance - Property
   - Reinsurance - Casualty
   - Reinsurance - Specialty
   - Professional Lines
   - Accident & Health
   - Cyber

   Specify each affected LOB's severity contribution. Sum of (LOB weight × LOB severity) ≈ total severity.

3. CAUSE DIVERSITY: Generate scenarios with DIFFERENT root causes:
   - Natural catastrophe (hurricane, earthquake, wildfire, flood)
   - Social inflation / litigation trends
   - Economic inflation / claims cost increases
   - Regulatory / legal changes (Ogden, court rulings)
   - Large loss / man-made events
   - Pandemic / systemic events
   - Attritional deterioration

4. NARRATIVE QUALITY: Each narrative should:
   - Describe the triggering event(s)
   - Explain the causal chain from event to reserve impact
   - Be specific about mechanisms and jurisdictions (but NOT specific calendar years)
   - Be plausible given historical precedents
   - Be 2-3 sentences (concise)
   - Use hypothetical/forward-looking language (e.g., "A major hurricane strikes..." not "Hurricane in 2023...")

5. TEMPORAL REALISM: Reference relative time periods (recent accident years, older long-tail years) but do NOT use specific calendar years like 2023, 2024, etc.

OUTPUT FORMAT (JSON array of {n_scenarios} scenarios):
```json
[
  {{
    "scenario_name": "Short descriptive title",
    "severity_ratio": 0.XX,
    "cause_category": "Category from list above",
    "lob_breakdown": {{
      "Property": 0.XX,
      "Casualty": 0.XX
    }},
    "specific_events": ["Event 1", "Event 2"],
    "affected_years": ["recent", "prior_5_years"],
    "narrative": "Concise narrative (2-3 sentences)..."
  }}
]
```

Generate exactly {n_scenarios} scenarios now:"""
    
    return prompt


# =============================================================================
# Synthetic Scenario Generator
# =============================================================================

class SyntheticScenarioGenerator:
    """
    Generates synthetic stress scenarios using LLM with historical examples.
    """
    
    def __init__(self, 
                 embedding_space: JointEmbeddingSpace,
                 config: GenerationConfig = None):
        self.embedding_space = embedding_space
        self.config = config or DEFAULT_GENERATION_CONFIG
        self.client = OpenAI()
        
        # Track generation statistics
        self.total_scenarios = 0
        self.api_calls = 0
        self.total_tokens = 0
    
    def generate_for_cell(self,
                          severity_bin: Tuple[float, float],
                          complexity_bin: Tuple[float, float]) -> List[SyntheticScenario]:
        """
        Generate scenarios for a single (severity, complexity) cell.
        """
        sev_mid = (severity_bin[0] + severity_bin[1]) / 2
        comp_mid = (complexity_bin[0] + complexity_bin[1]) / 2
        
        # Create target point in latent space
        # We need a representative text embedding - use empty/generic
        generic_text = f"Reserve strengthening of {sev_mid:.0%} due to adverse development"
        target_coords = self.embedding_space.project(
            generic_text, sev_mid, comp_mid, [0.0] * len(LLOYDS_LOBS)
        )
        
        # Find diverse neighbours
        neighbours = self.embedding_space.find_neighbours(
            target_coords,
            k=self.config.k_neighbours * 2,  # Get more, then filter
            severity_band=(severity_bin[0] * 0.5, severity_bin[1] * 1.5),  # Wider band for retrieval
            complexity_band=(complexity_bin[0] * 0.5, max(complexity_bin[1] * 1.5, complexity_bin[0] + 100)),
            min_years=self.config.min_years_diversity
        )
        
        if len(neighbours) < 3:
            # Not enough examples, expand search
            neighbours = self.embedding_space.find_neighbours(
                target_coords, k=self.config.k_neighbours, min_years=2
            )
        
        # Select diverse examples
        examples = select_diverse_examples(
            neighbours[:self.config.k_neighbours * 2],
            comp_mid,
            min_years=self.config.min_years_diversity
        )[:self.config.k_neighbours]
        
        if not examples:
            logger.warning(f"No examples found for cell {severity_bin}, {complexity_bin}")
            return []
        
        # Build prompt
        prompt = build_generation_prompt(
            severity_bin, complexity_bin, examples,
            n_scenarios=self.config.scenarios_per_cell * self.config.overgeneration_factor
        )
        
        # Call LLM with retry logic
        max_retries = 2
        scenarios_data = []
        
        for attempt in range(max_retries + 1):
            try:
                # On retry, request fewer scenarios
                if attempt > 0:
                    n_scenarios_retry = max(5, self.config.scenarios_per_cell)
                    prompt = build_generation_prompt(
                        severity_bin, complexity_bin, examples,
                        n_scenarios=n_scenarios_retry
                    )
                    logger.info(f"Retry {attempt}: requesting {n_scenarios_retry} scenarios")
                
                response = self.client.chat.completions.create(
                    model=self.config.llm_model,
                    messages=[
                        {"role": "system", "content": "You are an expert insurance actuary generating stress test scenarios. Always respond with valid JSON array. Keep narratives concise (2-3 sentences)."},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=self.config.llm_temperature,
                    max_tokens=self.config.max_tokens
                )
                
                self.api_calls += 1
                self.total_tokens += response.usage.total_tokens
                
                # Parse response
                content = response.choices[0].message.content
                
                # Extract JSON from response
                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0]
                elif "```" in content:
                    content = content.split("```")[1].split("```")[0]
                
                # Try to parse JSON with repair
                scenarios_data = parse_json_robust(content)
                
                if scenarios_data:
                    logger.debug(f"Parsed {len(scenarios_data)} scenarios on attempt {attempt + 1}")
                    break
                else:
                    logger.warning(f"Attempt {attempt + 1}: Failed to parse JSON for cell {severity_bin}, {complexity_bin}")
                    
            except Exception as e:
                logger.warning(f"Attempt {attempt + 1} error: {e}")
                if attempt == max_retries:
                    logger.error(f"All attempts failed for cell {severity_bin}, {complexity_bin}")
                    return []
        
        if not scenarios_data:
            return []
        
        # Convert to SyntheticScenario objects
        scenarios = []
        for i, s in enumerate(scenarios_data):
            try:
                # Generate unique ID
                scenario_id = hashlib.md5(
                    f"{severity_bin}_{complexity_bin}_{i}_{s.get('scenario_name', '')}".encode()
                ).hexdigest()[:12]
                
                # Normalize LOB breakdown to standard Lloyd's LOBs
                raw_lob_breakdown = s.get('lob_breakdown', {})
                normalized_lob_breakdown = normalize_lob_breakdown(raw_lob_breakdown)
                
                scenario = SyntheticScenario(
                    id=f"syn_{scenario_id}",
                    severity_ratio=s.get('severity_ratio', sev_mid),
                    complexity_score=comp_mid,
                    lob_breakdown=normalized_lob_breakdown,
                    cause_category=s.get('cause_category', 'Other'),
                    specific_events=s.get('specific_events', []),
                    narrative=s.get('narrative', ''),
                    source_neighbours=[ex.id for ex in examples],
                    generation_bin=(severity_bin, complexity_bin)
                )
                
                scenarios.append(scenario)
                self.total_scenarios += 1
                
            except Exception as e:
                logger.warning(f"Error parsing scenario {i}: {e}")
                continue
        
        return scenarios
    
    def generate_all(self) -> List[SyntheticScenario]:
        """
        Generate scenarios for all cells in the severity × complexity grid.
        """
        all_scenarios = []
        
        severity_bins = self.config.severity_bins
        complexity_bins = self.config.complexity_bins
        
        total_cells = len(severity_bins) * len(complexity_bins)
        cell_idx = 0
        
        for sev_bin in severity_bins:
            for comp_bin in complexity_bins:
                cell_idx += 1
                logger.info(f"Generating cell {cell_idx}/{total_cells}: "
                           f"severity={sev_bin}, complexity={comp_bin}")
                
                scenarios = self.generate_for_cell(sev_bin, comp_bin)
                all_scenarios.extend(scenarios)
                
                logger.info(f"  -> Generated {len(scenarios)} scenarios")
                
                # Rate limiting
                time.sleep(0.5)
        
        logger.info(f"\nGeneration complete:")
        logger.info(f"  Total scenarios: {self.total_scenarios}")
        logger.info(f"  API calls: {self.api_calls}")
        logger.info(f"  Total tokens: {self.total_tokens}")
        
        return all_scenarios
    
    def save_scenarios(self, scenarios: List[SyntheticScenario], output_path: str):
        """Save generated scenarios to JSON."""
        output_data = {
            'scenarios': [vars(s) for s in scenarios],
            'metadata': {
                'total_scenarios': len(scenarios),
                'api_calls': self.api_calls,
                'total_tokens': self.total_tokens,
                'config': {
                    'severity_bins': self.config.severity_bins,
                    'complexity_bins': self.config.complexity_bins,
                    'scenarios_per_cell': self.config.scenarios_per_cell,
                    'overgeneration_factor': self.config.overgeneration_factor
                }
            }
        }
        
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, indent=2, default=str)
        
        logger.info(f"Saved {len(scenarios)} scenarios to {output_path}")


# =============================================================================
# CLI
# =============================================================================

if __name__ == "__main__":
    import argparse
    
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    
    parser = argparse.ArgumentParser(description="Generate synthetic stress scenarios")
    parser.add_argument('--embedding-space', '-e', default='results/stress_test/embedding_space',
                        help='Path to embedding space directory')
    parser.add_argument('--output', '-o', default='results/stress_test/synthetic_scenarios.json',
                        help='Output path')
    parser.add_argument('--scenarios-per-cell', '-n', type=int, default=5,
                        help='Scenarios to generate per cell')
    
    args = parser.parse_args()
    
    # Load embedding space
    embedding_space = JointEmbeddingSpace.load(args.embedding_space)
    
    # Configure generation
    config = GenerationConfig(scenarios_per_cell=args.scenarios_per_cell)
    
    # Generate scenarios
    generator = SyntheticScenarioGenerator(embedding_space, config)
    scenarios = generator.generate_all()
    
    # Save
    generator.save_scenarios(scenarios, args.output)
    
    # Summary
    print(f"\n=== Generation Summary ===")
    print(f"Total scenarios: {len(scenarios)}")
    
    # By severity bin
    by_severity = defaultdict(int)
    for s in scenarios:
        bin_label = f"{int(s.generation_bin[0][0] * 100)}-{int(s.generation_bin[0][1] * 100)}%"
        by_severity[bin_label] += 1
    
    print("\nBy severity bin:")
    for k, v in sorted(by_severity.items()):
        print(f"  {k}: {v}")
    
    # By cause
    by_cause = defaultdict(int)
    for s in scenarios:
        by_cause[s.cause_category] += 1
    
    print("\nBy cause category:")
    for k, v in sorted(by_cause.items(), key=lambda x: -x[1]):
        print(f"  {k}: {v}")
