"""
Synthetic Scenario Generation v2 - Anchor-Based Approach with Full Audit Trail

For each historical example:
1. Use it as an anchor
2. Find k similar neighbours for few-shot context
3. Generate 10 synthetic scenarios via multiple LLM calls
4. Allow severity extrapolation (not locked to anchor's bin)
5. Randomize few-shot order + add random token for diversity
6. Capture FULL AUDIT TRAIL for every scenario:
   - Anchor details
   - Few-shot examples used
   - Generated output
   - LLM assessment of distributional validity
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
from dataclasses import asdict
from datetime import datetime
import time
import hashlib
import random
import re

from openai import OpenAI

from config import (
    GenerationConfig, DEFAULT_GENERATION_CONFIG,
    HistoricalMovement, SyntheticScenario, CauseCategory,
    LLOYDS_LOBS, LOB_TO_INDEX,
    FewShotExample, LLMAssessment, ScenarioAuditRecord
)

logger = logging.getLogger(__name__)


# =============================================================================
# LOB Normalization (from v1)
# =============================================================================

LOB_NORMALIZATION = {
    'property': 'Property', 'commercial property': 'Property', 
    'industrial property': 'Property', 'homeowners': 'Property',
    'business interruption': 'Property', 'construction': 'Property',
    'engineering': 'Property', 'terrorism': 'Property', 'war': 'Property',
    'agriculture': 'Property', 'agricultural': 'Property',
    'event cancellation': 'Property',
    
    'casualty': 'Casualty', 'general liability': 'Casualty',
    'liability': 'Casualty', 'product liability': 'Casualty',
    'environmental liability': 'Casualty', 'environmental': 'Casualty',
    'employers liability': 'Casualty', 'workers compensation': 'Casualty',
    "workers' compensation": 'Casualty', 'medical malpractice': 'Casualty',
    'healthcare liability': 'Casualty', 'pharmaceutical': 'Casualty',
    
    'marine': 'Marine', 'hull': 'Marine', 'cargo': 'Marine',
    'marine liability': 'Marine',
    
    'energy': 'Energy', 'oil & gas': 'Energy', 'offshore': 'Energy',
    'power generation': 'Energy',
    
    'motor': 'Motor', 'auto': 'Motor', 'automobile': 'Motor',
    'commercial auto': 'Motor', 'auto liability': 'Motor',
    
    'aviation': 'Aviation', 'aerospace': 'Aviation', 'airline': 'Aviation',
    
    'reinsurance - property': 'Reinsurance - Property',
    'reinsurance property': 'Reinsurance - Property',
    'property reinsurance': 'Reinsurance - Property',
    'reinsurance - casualty': 'Reinsurance - Casualty',
    'reinsurance casualty': 'Reinsurance - Casualty',
    'casualty reinsurance': 'Reinsurance - Casualty',
    'reinsurance - specialty': 'Reinsurance - Specialty',
    'reinsurance specialty': 'Reinsurance - Specialty',
    'specialty reinsurance': 'Reinsurance - Specialty',
    'reinsurance': 'Reinsurance - Property',
    
    'professional lines': 'Professional Lines',
    'professional liability': 'Professional Lines',
    'professional indemnity': 'Professional Lines',
    'd&o': 'Professional Lines', 'directors & officers': 'Professional Lines',
    'directors and officers': 'Professional Lines',
    'e&o': 'Professional Lines', 'errors & omissions': 'Professional Lines',
    'errors and omissions': 'Professional Lines',
    'employment practices liability': 'Professional Lines',
    'financial lines': 'Professional Lines',
    'financial institutions': 'Professional Lines',
    'technology e&o': 'Professional Lines',
    'political risk': 'Professional Lines', 'trade credit': 'Professional Lines',
    'credit': 'Professional Lines', 'surety': 'Professional Lines',
    'specialty': 'Professional Lines',
    
    'accident & health': 'Accident & Health',
    'accident and health': 'Accident & Health',
    'health': 'Accident & Health', 'life': 'Accident & Health',
    'travel': 'Accident & Health', 'personal accident': 'Accident & Health',
    'annuities': 'Accident & Health',
    
    'cyber': 'Cyber', 'cybersecurity': 'Cyber', 'technology': 'Cyber',
}


def normalize_lob(lob_name: str) -> str:
    """Normalize a LOB name to standard Lloyd's LOB."""
    if not lob_name:
        return 'Aggregate'
    if lob_name in LLOYDS_LOBS:
        return lob_name
    lower = lob_name.lower().strip()
    if lower in LOB_NORMALIZATION:
        return LOB_NORMALIZATION[lower]
    for key, value in LOB_NORMALIZATION.items():
        if key in lower or lower in key:
            return value
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
# Robust JSON Parsing (from v1)
# =============================================================================

def parse_json_robust(content: str) -> List[Dict]:
    """Parse JSON with repair logic for common LLM output issues."""
    content = content.strip()
    
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
    
    # Try regex extraction
    scenarios = extract_scenarios_regex(content)
    if scenarios:
        return scenarios
    
    return []


def repair_truncated_json(content: str) -> Optional[str]:
    """Attempt to repair truncated JSON."""
    open_brackets = content.count('[') - content.count(']')
    open_braces = content.count('{') - content.count('}')
    
    if open_brackets > 0 or open_braces > 0:
        last_complete = find_last_complete_object(content)
        if last_complete:
            return last_complete
        
        repaired = content.rstrip().rstrip(',')
        quote_count = repaired.count('"') - repaired.count('\\"')
        if quote_count % 2 == 1:
            repaired += '"'
        repaired += '}' * open_braces
        repaired += ']' * open_brackets
        return repaired
    
    return content


def find_last_complete_object(content: str) -> Optional[str]:
    """Find the position of the last complete JSON object in an array."""
    matches = list(re.finditer(r'\}\s*(?=[,\]])', content))
    if not matches:
        return None
    
    for match in reversed(matches):
        candidate = content[:match.end()]
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
    scenarios = []
    pattern = r'\{[^{}]*"(?:scenario_name|severity_ratio)"[^{}]*\}'
    matches = re.findall(pattern, content, re.DOTALL)
    
    for match in matches:
        try:
            obj = json.loads(match)
            scenarios.append(obj)
        except json.JSONDecodeError:
            try:
                fixed = match.replace("'", '"')
                fixed = re.sub(r',\s*}', '}', fixed)
                obj = json.loads(fixed)
                scenarios.append(obj)
            except json.JSONDecodeError:
                continue
    return scenarios


# =============================================================================
# Anchor-Based Generation
# =============================================================================

def format_example_for_prompt(movement: HistoricalMovement, include_severity: bool = True) -> str:
    """Format a historical movement as a few-shot example."""
    lob_vec = movement.lob_vector or [0] * len(LLOYDS_LOBS)
    nonzero_lobs = [(LLOYDS_LOBS[i], v) for i, v in enumerate(lob_vec) if v > 0]
    
    if movement.complexity_score < 50:
        diversification = "monoline/concentrated"
    elif movement.complexity_score < 150:
        diversification = "moderately concentrated"
    elif movement.complexity_score < 300:
        diversification = "moderately diversified"
    else:
        diversification = "highly diversified"
    
    events = ', '.join(movement.specific_events[:3]) if movement.specific_events else 'N/A'
    causes = ', '.join(movement.primary_causes[:2]) if movement.primary_causes else 'N/A'
    
    severity_line = f"Severity: {movement.severity_ratio:.1%} adverse development\n" if include_severity else ""
    
    return f"""Year: {movement.year}
Syndicate: {movement.syndicate or 'N/A'}
Portfolio: {diversification} (complexity={movement.complexity_score:.0f})
LOB: {movement.line_of_business}
{severity_line}Causes: {causes}
Events: {events}
Narrative: {movement.narrative or 'N/A'}"""


def build_anchor_prompt(
    anchor: HistoricalMovement,
    neighbours: List[HistoricalMovement],
    n_scenarios: int,
    random_seed: int,
    call_index: int,
    extrapolation_factor: float = 2.0,  # Allow up to 2x anchor severity
    request_extrapolation: bool = False,  # If True, require severities above historical max
    max_historical_severity: float = None  # Historical maximum for extrapolation calls
) -> str:
    """
    Build prompt for anchor-based generation.
    
    - Anchor is the primary example
    - Neighbours provide context (shuffled for diversity)
    - Random seed adds variation across calls
    - Allow severity extrapolation up to extrapolation_factor × anchor
    - If request_extrapolation=True, generate scenarios ABOVE historical max
    """
    # Shuffle neighbours for this call
    shuffled_neighbours = neighbours.copy()
    random.seed(random_seed + call_index)
    random.shuffle(shuffled_neighbours)
    
    # Format anchor (primary example)
    anchor_text = format_example_for_prompt(anchor, include_severity=True)
    
    # Format neighbours (context examples) - don't show severity to avoid anchoring
    neighbours_text = "\n\n---\n\n".join([
        format_example_for_prompt(n, include_severity=False) 
        for n in shuffled_neighbours[:5]
    ])
    
    # Severity range: allow extrapolation up to extrapolation_factor × anchor
    # CRITICAL: anchor MUST have a valid severity ratio - no silent fallbacks
    if anchor.severity_ratio is None or anchor.severity_ratio <= 0:
        raise ValueError(f"Anchor {anchor.id} has no valid severity_ratio: {anchor.severity_ratio}")
    anchor_sev = anchor.severity_ratio
    
    if request_extrapolation and max_historical_severity:
        # For extrapolation calls: require severities ABOVE historical max
        sev_lo = max_historical_severity * 1.0  # Start at historical max
        sev_hi = min(3.0, max_historical_severity * 2.0)  # Up to 2x historical max
        extrapolation_instruction = f"""
⚠️ EXTRAPOLATION REQUIRED ⚠️
The maximum historical severity observed is {max_historical_severity:.0%}.
For this call, you MUST generate scenarios with severity ABOVE {max_historical_severity:.0%}.
Target range: {sev_lo:.0%} to {sev_hi:.0%}

These are extreme "tail risk" scenarios representing 1-in-50 to 1-in-200 year events.
Think of the worst plausible combinations of adverse factors."""
    else:
        # Normal call - standard extrapolation range
        sev_lo = max(0.01, anchor_sev * 0.3)
        sev_hi = min(3.0, anchor_sev * extrapolation_factor)
        
        # For higher severity anchors, push extrapolation more
        if anchor_sev > 0.30:
            sev_hi = min(3.0, anchor_sev * (extrapolation_factor + 0.5))
        
        extrapolation_instruction = ""
    
    # Complexity from anchor
    complexity = anchor.complexity_score or 100
    
    if complexity < 50:
        portfolio_desc = "monoline or highly concentrated portfolios"
    elif complexity < 150:
        portfolio_desc = "moderately concentrated portfolios"
    elif complexity < 300:
        portfolio_desc = "moderately diversified portfolios"
    else:
        portfolio_desc = "well diversified portfolios"
    
    prompt = f"""You are an expert actuarial analyst generating stress test scenarios for Lloyd's of London insurance syndicates.

TASK: Generate {n_scenarios} diverse, plausible adverse reserve development scenarios inspired by the anchor example below.
{extrapolation_instruction}
ANCHOR EXAMPLE (primary inspiration):

{anchor_text}

SIMILAR HISTORICAL EXAMPLES (for context):

{neighbours_text}

GENERATION PARAMETERS:
- Severity range: {sev_lo:.0%} to {sev_hi:.0%} adverse prior-year development
- Portfolio type: {portfolio_desc} (complexity ~{complexity:.0f})
- Variation seed: {random_seed + call_index} (for diversity)

CRITICAL REQUIREMENTS:

1. SEVERITY SPREAD: Generate scenarios ACROSS THE FULL RANGE from {sev_lo:.0%} to {sev_hi:.0%}.
   - Include at least one LOW severity scenario ({sev_lo:.0%}-{(sev_lo + (sev_hi-sev_lo)*0.33):.0%})
   - Include at least one MEDIUM severity scenario ({(sev_lo + (sev_hi-sev_lo)*0.33):.0%}-{(sev_lo + (sev_hi-sev_lo)*0.66):.0%})
   - Include at least one HIGH severity scenario ({(sev_lo + (sev_hi-sev_lo)*0.66):.0%}-{sev_hi:.0%})
   DO NOT cluster all scenarios around the same severity!

2. LOBs: Use ONLY these Lloyd's lines of business:
   Property, Casualty, Marine, Energy, Motor, Aviation,
   Reinsurance - Property, Reinsurance - Casualty, Reinsurance - Specialty,
   Professional Lines, Accident & Health, Cyber

3. CAUSE DIVERSITY: Vary root causes across scenarios:
   - Natural catastrophe
   - Social inflation / litigation trends
   - Economic inflation / claims cost increases
   - Regulatory / legal changes
   - Large loss / man-made events
   - Pandemic / systemic events
   - Attritional deterioration

4. HIGH SEVERITY SCENARIOS: For scenarios above {anchor_sev:.0%}:
   - MUST combine multiple adverse factors (e.g., cat event + social inflation + economic factors)
   - Each scenario should be a HOLISTIC multi-peril event, not a single isolated peril
   - Reference extreme historical precedents (Hurricane Andrew + asbestos, COVID + social inflation)
   - Consider systemic/correlated events affecting multiple LOBs simultaneously
   - Example: "A major hurricane season coincides with judicial inflation and economic uncertainty"

5. LOB BREAKDOWN: Each scenario should affect MULTIPLE lines of business.
   - Most real adverse developments affect several LOBs simultaneously
   - Split severity across affected LOBs realistically (don't concentrate in one LOB)
   - Example: A pandemic scenario affects Property (BI), Casualty (liability), A&H, and Professional Lines

6. NARRATIVES: 2-3 sentences each, specific and plausible.
   CRITICAL: Do NOT use specific years (e.g., "2023", "2024", "in 2019").
   Instead use relative/hypothetical language:
   - "A major hurricane strikes..." (not "Hurricane in 2023...")
   - "Following a series of court rulings..." (not "2024 court rulings...")
   - "A prolonged period of inflation..." (not "2023-2024 inflation...")
   Scenarios should be forward-looking stress tests, not historical event descriptions.

OUTPUT FORMAT (JSON array):
```json
[
  {{
    "scenario_name": "Short title describing the holistic scenario",
    "severity_ratio": 0.XX,
    "cause_category": "Category from list",
    "lob_breakdown": {{"Property": 0.XX, "Casualty": 0.XX, "Marine": 0.XX}},
    "specific_events": ["Event 1 affecting LOB A", "Event 2 affecting LOB B", "Event 3 affecting multiple LOBs"],
    "narrative": "Holistic narrative tying multiple events together..."
  }}
]
```

NOTE: lob_breakdown should typically include 2-4 affected LOBs, not just one.
specific_events should list 2-4 distinct adverse developments that combine to create the scenario.

Generate exactly {n_scenarios} scenarios with VARIED severities now:"""
    
    return prompt


def build_anchor_prompt_with_metadata(
    anchor: HistoricalMovement,
    neighbours: List[HistoricalMovement],
    n_scenarios: int,
    random_seed: int,
    call_index: int,
    extrapolation_factor: float = 2.0,
    request_extrapolation: bool = False,
    max_historical_severity: float = None
) -> Tuple[str, Tuple[float, float]]:
    """
    Build prompt for anchor-based generation, returning metadata for audit trail.
    
    Returns:
        (prompt, (sev_lo, sev_hi))
    """
    # Compute severity range
    # CRITICAL: anchor MUST have a valid severity ratio - no silent fallbacks
    if anchor.severity_ratio is None or anchor.severity_ratio <= 0:
        raise ValueError(f"Anchor {anchor.id} has no valid severity_ratio: {anchor.severity_ratio}")
    anchor_sev = anchor.severity_ratio
    
    if request_extrapolation and max_historical_severity:
        sev_lo = max_historical_severity * 1.0
        sev_hi = min(3.0, max_historical_severity * 2.0)
    else:
        sev_lo = max(0.01, anchor_sev * 0.3)
        sev_hi = min(3.0, anchor_sev * extrapolation_factor)
        if anchor_sev > 0.30:
            sev_hi = min(3.0, anchor_sev * (extrapolation_factor + 0.5))
    
    # Build prompt using the standard function
    prompt = build_anchor_prompt(
        anchor, neighbours, n_scenarios, random_seed, call_index,
        extrapolation_factor, request_extrapolation, max_historical_severity
    )
    
    return prompt, (sev_lo, sev_hi)


class AnchorBasedGenerator:
    """
    Generates synthetic scenarios using each historical example as an anchor.
    
    For each anchor:
    - Find k neighbours for few-shot context
    - Make multiple LLM calls with shuffled examples + random tokens
    - Generate total of scenarios_per_anchor synthetic scenarios
    
    Edge Case Handling:
    - Anchors above 80th percentile severity are "edge cases"
    - For edge cases, 50% of LLM calls request severity ABOVE historical max
    - This ensures the library has scenarios to match GPD tail samples
    
    Full Audit Trail:
    - Every generated scenario has a complete audit record
    - Includes anchor, few-shot examples, LLM output, and validity assessment
    """
    
    def __init__(self,
                 historical_movements: List[HistoricalMovement],
                 embedding_space,  # JointEmbeddingSpace
                 config: GenerationConfig = None,
                 enable_audit: bool = True):
        self.movements = historical_movements
        self.embedding_space = embedding_space
        self.config = config or DEFAULT_GENERATION_CONFIG
        self.client = OpenAI()
        self.enable_audit = enable_audit
        
        # Generation parameters
        self.scenarios_per_anchor = 10
        self.scenarios_per_call = 5  # Generate 5 per call, 2 calls per anchor
        self.k_neighbours = 7
        
        # Edge case parameters
        self.edge_case_percentile = 80  # Anchors above this are edge cases
        self.extrapolation_prob = 0.5   # 50% of edge case calls request extrapolation
        
        # Compute severity distribution
        self.severities = np.array([m.severity_ratio for m in self.movements if m.severity_ratio])
        self.max_severity = self.severities.max() if len(self.severities) > 0 else 1.0
        self.edge_case_threshold = np.percentile(self.severities, self.edge_case_percentile) if len(self.severities) > 0 else 0.5
        
        logger.info(f"Severity distribution: min={self.severities.min():.1%}, "
                   f"median={np.median(self.severities):.1%}, max={self.max_severity:.1%}")
        logger.info(f"Edge case threshold ({self.edge_case_percentile}th pct): {self.edge_case_threshold:.1%}")
        
        # Statistics
        self.total_scenarios = 0
        self.api_calls = 0
        self.total_tokens = 0
        self.failed_anchors = 0
        self.edge_case_anchors = 0
        self.extrapolation_calls = 0
        self.retried_calls = 0  # Counts retry attempts (not including initial attempt)
        
        # Audit trail storage
        self.audit_records: List[ScenarioAuditRecord] = []
    
    def is_edge_case(self, anchor: HistoricalMovement) -> bool:
        """Check if anchor is an edge case (high severity)."""
        if anchor.severity_ratio is None:
            return False
        return anchor.severity_ratio >= self.edge_case_threshold
    
    def find_neighbours_with_distances(self, anchor: HistoricalMovement, k: int = 7) -> List[Tuple[HistoricalMovement, float]]:
        """Find k nearest neighbours to anchor in embedding space, returning distances for audit."""
        anchor_idx = None
        for i, m in enumerate(self.movements):
            if m.id == anchor.id:
                anchor_idx = i
                break
        
        if anchor_idx is None:
            return [(m, 0.0) for m in self._find_by_attributes(anchor, k)]
        
        if self.embedding_space and hasattr(self.embedding_space, 'latent_coords'):
            anchor_coords = self.embedding_space.latent_coords[anchor_idx]
            
            distances = []
            for i, m in enumerate(self.movements):
                if i != anchor_idx:
                    dist = np.linalg.norm(self.embedding_space.latent_coords[i] - anchor_coords)
                    distances.append((m, float(dist)))
            
            distances.sort(key=lambda x: x[1])
            return distances[:k]
        
        return [(m, 0.0) for m in self._find_by_attributes(anchor, k)]
    
    def find_neighbours(self, anchor: HistoricalMovement, k: int = 7) -> List[HistoricalMovement]:
        """Find k nearest neighbours (convenience method without distances)."""
        return [m for m, d in self.find_neighbours_with_distances(anchor, k)]
    
    def _find_by_attributes(self, anchor: HistoricalMovement, k: int) -> List[HistoricalMovement]:
        """Fallback: find neighbours by attribute similarity."""
        candidates = []
        for m in self.movements:
            if m.id == anchor.id:
                continue
            
            score = 0
            if m.line_of_business == anchor.line_of_business:
                score += 2
            if anchor.severity_ratio and m.severity_ratio:
                sev_diff = abs(m.severity_ratio - anchor.severity_ratio)
                score += max(0, 1 - sev_diff)
            if anchor.complexity_score and m.complexity_score:
                comp_diff = abs(m.complexity_score - anchor.complexity_score) / 100
                score += max(0, 1 - comp_diff)
            
            candidates.append((m, score))
        
        candidates.sort(key=lambda x: -x[1])
        return [m for m, s in candidates[:k]]
    
    def generate_for_anchor(self, anchor: HistoricalMovement) -> List[SyntheticScenario]:
        """Generate synthetic scenarios for a single anchor with full audit trail."""
        # CRITICAL: Validate anchor has required data
        if anchor.severity_ratio is None or anchor.severity_ratio <= 0:
            logger.warning(f"Skipping anchor {anchor.id}: no valid severity_ratio "
                          f"(got {anchor.severity_ratio})")
            return []

        neighbours_with_dist = self.find_neighbours_with_distances(anchor, self.k_neighbours)
        neighbours = [m for m, d in neighbours_with_dist]

        if len(neighbours) < 3:
            logger.warning(f"Insufficient neighbours for anchor {anchor.id}")
            return []
        
        # Find diversity candidates (different LOB or different causes)
        diversity_candidates = self._find_diversity_candidates(anchor, neighbours_with_dist)
        
        all_scenarios = []
        random_seed = hash(anchor.id) % 10000
        is_edge = self.is_edge_case(anchor)
        
        if is_edge:
            self.edge_case_anchors += 1
        
        # Make multiple calls for diversity
        n_calls = (self.scenarios_per_anchor + self.scenarios_per_call - 1) // self.scenarios_per_call
        
        for call_idx in range(n_calls):
            # For edge cases, decide if this call should request extrapolation
            request_extrapolation = False
            if is_edge and random.random() < self.extrapolation_prob:
                request_extrapolation = True
                self.extrapolation_calls += 1
            
            # Select neighbours with mix of similarity and diversity
            # 3-4 similarity examples + 1-2 diversity examples
            random.seed(random_seed + call_idx)
            
            # Shuffle similarity neighbours
            similarity_pool = neighbours_with_dist.copy()
            random.shuffle(similarity_pool)
            similarity_selected = similarity_pool[:4]  # Top 4 similar
            
            # Add 1-2 diversity examples if available
            diversity_selected = []
            if diversity_candidates:
                div_pool = diversity_candidates.copy()
                random.shuffle(div_pool)
                diversity_selected = div_pool[:min(2, len(div_pool))]
            
            # Combine with reason labels: (movement, distance, reason)
            used_neighbours_with_reason = [
                (m, d, "similarity") for m, d in similarity_selected
            ] + [
                (m, d, "diversity") for m, d in diversity_selected
            ]
            
            # Shuffle the combined list for prompt variety
            random.shuffle(used_neighbours_with_reason)
            used_neighbours_with_reason = used_neighbours_with_reason[:5]  # Limit to 5
            
            prompt, severity_range = build_anchor_prompt_with_metadata(
                anchor, [m for m, d, r in used_neighbours_with_reason], 
                self.scenarios_per_call,
                random_seed, call_idx,
                request_extrapolation=request_extrapolation,
                max_historical_severity=self.max_severity
            )
            
            scenarios, raw_outputs = self._call_llm_with_audit(
                prompt, anchor, call_idx, 
                used_neighbours_with_reason, severity_range, 
                request_extrapolation, random_seed
            )
            all_scenarios.extend(scenarios)
            
            # Rate limiting
            if call_idx < n_calls - 1:
                time.sleep(0.5)
        
        return all_scenarios[:self.scenarios_per_anchor]
    
    def _find_diversity_candidates(self, 
                                    anchor: HistoricalMovement,
                                    neighbours_with_dist: List[Tuple[HistoricalMovement, float]]) -> List[Tuple[HistoricalMovement, float]]:
        """
        Find diversity candidates - movements that are somewhat similar but differ
        in key aspects (different LOB, different cause category).
        
        These help the LLM generate more varied scenarios.
        """
        diversity_candidates = []
        used_ids = {anchor.id} | {m.id for m, d in neighbours_with_dist[:5]}
        
        for m in self.movements:
            if m.id in used_ids:
                continue
            
            # Different LOB but similar severity
            lob_different = m.line_of_business != anchor.line_of_business
            
            # Different cause category
            anchor_causes = set(anchor.primary_causes[:3]) if anchor.primary_causes else set()
            m_causes = set(m.primary_causes[:3]) if m.primary_causes else set()
            cause_different = len(anchor_causes & m_causes) == 0
            
            # Severity in similar range (within 2x)
            if anchor.severity_ratio and m.severity_ratio:
                severity_similar = 0.3 <= (m.severity_ratio / anchor.severity_ratio) <= 3.0
            else:
                severity_similar = True
            
            # Pick if different LOB OR different causes, but similar severity
            if (lob_different or cause_different) and severity_similar:
                # Calculate approximate distance
                if hasattr(self, 'embedding_space') and self.embedding_space:
                    try:
                        anchor_idx = next(i for i, mov in enumerate(self.movements) if mov.id == anchor.id)
                        m_idx = next(i for i, mov in enumerate(self.movements) if mov.id == m.id)
                        dist = np.linalg.norm(
                            self.embedding_space.latent_coords[anchor_idx] - 
                            self.embedding_space.latent_coords[m_idx]
                        )
                    except (StopIteration, AttributeError):
                        dist = 1.0
                else:
                    dist = 1.0
                
                diversity_candidates.append((m, float(dist)))
        
        # Sort by distance (prefer closer diversity candidates)
        diversity_candidates.sort(key=lambda x: x[1])
        return diversity_candidates[:10]  # Return top 10 candidates
    
    def _call_llm_with_audit(self,
                             prompt: str,
                             anchor: HistoricalMovement,
                             call_idx: int,
                             used_neighbours_with_reason: List[Tuple[HistoricalMovement, float, str]],
                             severity_range: Tuple[float, float],
                             request_extrapolation: bool,
                             random_seed: int) -> Tuple[List[SyntheticScenario], List[Dict]]:
        """Make LLM call with full audit trail capture and retry logic.

        Args:
            used_neighbours_with_reason: List of (movement, distance, selection_reason) tuples
                where selection_reason is 'similarity' or 'diversity'

        Retries up to 2 times with exponential backoff to avoid bias towards
        easier-to-generate anchors.
        """
        timestamp = datetime.utcnow().isoformat()

        max_retries = 2
        base_delay = 1.0  # seconds

        for attempt in range(max_retries + 1):
            start_time = time.time()

            try:
                response = self.client.chat.completions.create(
                    model=self.config.llm_model,
                    messages=[
                        {"role": "system", "content": "You are an expert insurance actuary. Always respond with valid JSON array."},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.8,
                    max_tokens=self.config.max_tokens
                )

                generation_time_ms = int((time.time() - start_time) * 1000)
                self.api_calls += 1
                self.total_tokens += response.usage.total_tokens

                content = response.choices[0].message.content

                # Extract JSON
                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0]
                elif "```" in content:
                    content = content.split("```")[1].split("```")[0]

                scenarios_data = parse_json_robust(content)

                if not scenarios_data:
                    # Parse failure - retry with backoff
                    if attempt < max_retries:
                        delay = base_delay * (2 ** attempt)
                        self.retried_calls += 1
                        time.sleep(delay)
                        continue
                    else:
                        # Only log after all retries exhausted
                        return [], []

                # Break out of retry loop on success
                break

            except Exception as e:
                # API failure - retry with backoff
                if attempt < max_retries:
                    delay = base_delay * (2 ** attempt)
                    self.retried_calls += 1
                    time.sleep(delay)
                    continue
                else:
                    # Only log after all retries exhausted
                    return [], []

        # Convert to SyntheticScenario objects and create audit records
        scenarios = []
        raw_outputs = []

        for i, s in enumerate(scenarios_data):
            try:
                scenario_id = hashlib.md5(
                    f"{anchor.id}_{call_idx}_{i}_{s.get('scenario_name', '')}".encode()
                ).hexdigest()[:12]

                normalized_lob = normalize_lob_breakdown(s.get('lob_breakdown', {}))

                # Get severity from LLM output, with validated fallback to anchor
                llm_severity = s.get('severity_ratio')
                if llm_severity is not None and llm_severity > 0:
                    sev = llm_severity
                else:
                    # Fall back to anchor severity (already validated as non-null)
                    sev = anchor.severity_ratio
                    logger.debug(f"LLM didn't return severity for scenario {i}, using anchor: {sev:.2%}")

                is_extrapolated = sev > self.max_severity

                # Complexity: use anchor's or skip if missing
                complexity = anchor.complexity_score
                if complexity is None or complexity <= 0:
                    complexity = 100.0  # Minimal default for complexity only
                    logger.debug(f"Anchor {anchor.id} has no complexity, using minimal default")

                scenario = SyntheticScenario(
                    id=f"syn_{scenario_id}",
                    severity_ratio=sev,
                    complexity_score=complexity,
                    lob_breakdown=normalized_lob,
                    cause_category=s.get('cause_category', 'Other'),
                    specific_events=s.get('specific_events', []),
                    narrative=s.get('narrative', ''),
                    source_neighbours=[anchor.id],
                    generation_bin=None,
                    is_edge_case=is_extrapolated
                )
                scenarios.append(scenario)
                raw_outputs.append(s)
                self.total_scenarios += 1

                # Create audit record
                if self.enable_audit:
                    few_shot_examples = [
                        FewShotExample(
                            id=m.id,
                            syndicate=m.syndicate,
                            year=m.year,
                            severity_ratio=m.severity_ratio,
                            line_of_business=m.line_of_business,
                            narrative=m.narrative[:500] if m.narrative else "",
                            primary_causes=m.primary_causes[:3] if m.primary_causes else [],
                            distance_to_anchor=d,
                            selection_reason=reason
                        )
                        for m, d, reason in used_neighbours_with_reason
                    ]

                    audit_record = ScenarioAuditRecord(
                        scenario_id=scenario.id,
                        anchor_id=anchor.id,
                        generation_timestamp=timestamp,
                        call_index=call_idx,
                        anchor_syndicate=anchor.syndicate,
                        anchor_year=anchor.year,
                        anchor_severity=anchor.severity_ratio,
                        anchor_lob=anchor.line_of_business,
                        anchor_narrative=anchor.narrative[:500] if anchor.narrative else "",
                        anchor_causes=anchor.primary_causes[:5] if anchor.primary_causes else [],
                        few_shot_examples=few_shot_examples,
                        prompt_severity_range=severity_range,
                        extrapolation_requested=request_extrapolation,
                        random_seed=random_seed + call_idx,
                        generated_scenario=s,
                        parsed_severity=sev,
                        parsed_lob_breakdown=normalized_lob,
                        parsed_cause_category=s.get('cause_category', 'Other'),
                        parsed_narrative=s.get('narrative', '')[:500],
                        model_used=self.config.llm_model,
                        temperature=0.8,
                        generation_time_ms=generation_time_ms
                    )

                    self.audit_records.append(audit_record)

            except Exception as e:
                logger.debug(f"Error parsing scenario: {e}")
                continue

        return scenarios, raw_outputs
    
    def assess_scenario_validity(self, audit_record: ScenarioAuditRecord) -> LLMAssessment:
        """
        Use LLM to assess whether a generated scenario is from the same
        local distribution as the anchor and few-shot examples.
        """
        # Build assessment prompt with enhanced audit info
        few_shot_lines = []
        for ex in audit_record.few_shot_examples[:5]:
            syndicate_info = f"{ex.syndicate} ({ex.year})" if ex.syndicate else f"({ex.year})"
            severity_str = f"{ex.severity_ratio:.1%}" if ex.severity_ratio else "N/A"
            reason_tag = f"[{ex.selection_reason.upper()}]"
            few_shot_lines.append(
                f"  {reason_tag} {ex.id}: {syndicate_info}, {ex.line_of_business}, "
                f"{severity_str} severity, causes: {', '.join(ex.primary_causes[:2])}"
            )
        few_shot_summary = "\n".join(few_shot_lines)
        
        # Anchor syndicate/year info
        anchor_syndicate_info = f"{audit_record.anchor_syndicate} ({audit_record.anchor_year})" if audit_record.anchor_syndicate else f"({audit_record.anchor_year})"
        anchor_severity_str = f"{audit_record.anchor_severity:.1%}" if audit_record.anchor_severity else "N/A"
        
        prompt = f"""Assess whether this generated stress scenario is statistically plausible given its source anchor and context.

ANCHOR SCENARIO (primary inspiration):
- ID: {audit_record.anchor_id}
- Source: {anchor_syndicate_info}
- LOB: {audit_record.anchor_lob}
- Severity: {anchor_severity_str}
- Causes: {', '.join(audit_record.anchor_causes[:3])}
- Narrative: {audit_record.anchor_narrative[:300]}...

FEW-SHOT EXAMPLES (context - [SIMILARITY] = chosen for closeness to anchor, [DIVERSITY] = chosen for variation):
{few_shot_summary}

GENERATED SCENARIO:
- Severity: {audit_record.parsed_severity:.1%}
- LOBs: {', '.join(f'{k}:{v:.0%}' for k, v in audit_record.parsed_lob_breakdown.items())}
- Cause: {audit_record.parsed_cause_category}
- Narrative: {audit_record.parsed_narrative[:300]}...

GENERATION CONTEXT:
- Severity range requested: {audit_record.prompt_severity_range[0]:.1%} to {audit_record.prompt_severity_range[1]:.1%}
- Extrapolation requested: {audit_record.extrapolation_requested}

Provide your assessment in JSON format:
{{
    "distributional_probability": 0.XX,  // P(scenario from same local distribution as anchor), 0-1
    "confidence": "high/medium/low",
    "reasoning": "Explain how this scenario relates to anchor and few-shot examples...",
    "key_similarities": ["similarity 1", "similarity 2", ...],
    "key_differences": ["difference 1", "difference 2", ...],
    "extrapolation_type": "interpolation/mild_extrapolation/strong_extrapolation",
    "risk_factors": ["potential issue 1", "potential issue 2", ...]
}}"""

        try:
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are an expert actuary assessing synthetic scenario validity. Respond with valid JSON only."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.2,
                max_tokens=1000
            )
            
            content = response.choices[0].message.content
            
            # Parse JSON
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]
            
            assessment_data = json.loads(content)
            
            return LLMAssessment(
                distributional_probability=assessment_data.get('distributional_probability', 0.5),
                confidence=assessment_data.get('confidence', 'medium'),
                reasoning=assessment_data.get('reasoning', ''),
                key_similarities=assessment_data.get('key_similarities', []),
                key_differences=assessment_data.get('key_differences', []),
                extrapolation_type=assessment_data.get('extrapolation_type', 'interpolation'),
                risk_factors=assessment_data.get('risk_factors', [])
            )
            
        except Exception as e:
            logger.warning(f"Failed to assess scenario {audit_record.scenario_id}: {e}")
            return LLMAssessment(
                distributional_probability=0.5,
                confidence='low',
                reasoning=f"Assessment failed: {str(e)}",
                key_similarities=[],
                key_differences=[],
                extrapolation_type='unknown',
                risk_factors=['Assessment could not be completed']
            )
    
    def assess_all_scenarios(self, sample_rate: float = 0.1, max_assessments: int = 100):
        """
        Run LLM assessment on a sample of generated scenarios.
        
        Args:
            sample_rate: Fraction of scenarios to assess (default 10%)
            max_assessments: Maximum number of assessments to run
        """
        if not self.audit_records:
            logger.warning("No audit records to assess")
            return
        
        # Select sample
        n_to_assess = min(max_assessments, int(len(self.audit_records) * sample_rate))
        indices = random.sample(range(len(self.audit_records)), n_to_assess)
        
        logger.info(f"Assessing {n_to_assess} scenarios for validity...")
        
        for i, idx in enumerate(indices):
            if (i + 1) % 10 == 0:
                logger.info(f"  Progress: {i+1}/{n_to_assess}")
            
            audit_record = self.audit_records[idx]
            assessment = self.assess_scenario_validity(audit_record)
            audit_record.assessment = assessment
            
            time.sleep(0.3)  # Rate limiting
        
        # Report summary
        assessed = [r for r in self.audit_records if r.assessment is not None]
        if assessed:
            probs = [r.assessment.distributional_probability for r in assessed]
            logger.info(f"\nAssessment Summary ({len(assessed)} scenarios):")
            logger.info(f"  Distributional probability: min={min(probs):.2f}, median={np.median(probs):.2f}, max={max(probs):.2f}")
            
            extrapolation_types = defaultdict(int)
            for r in assessed:
                extrapolation_types[r.assessment.extrapolation_type] += 1
            logger.info(f"  Extrapolation types: {dict(extrapolation_types)}")
    
    def assess_tail_scenarios(self, threshold: float):
        """
        Run LLM assessment only on tail scenarios (severity >= threshold).
        
        Args:
            threshold: Severity threshold (e.g., 50yr return period severity)
        """
        if not self.audit_records:
            logger.warning("No audit records to assess")
            return
        
        # Find tail scenarios
        tail_indices = []
        for i, record in enumerate(self.audit_records):
            parsed = record.generated_output.get('parsed', {}) if record.generated_output else {}
            severity = parsed.get('severity', 0)
            if severity >= threshold:
                tail_indices.append(i)
        
        logger.info(f"Found {len(tail_indices)} tail scenarios (severity ≥ {threshold:.1%})")
        logger.info(f"Assessing {len(tail_indices)} tail scenarios for validity...")
        
        for i, idx in enumerate(tail_indices):
            if (i + 1) % 10 == 0:
                logger.info(f"  Progress: {i+1}/{len(tail_indices)}")
            
            audit_record = self.audit_records[idx]
            assessment = self.assess_scenario_validity(audit_record)
            audit_record.assessment = assessment
            
            time.sleep(0.3)  # Rate limiting
        
        # Report summary
        assessed = [r for r in self.audit_records if r.assessment is not None]
        if assessed:
            probs = [r.assessment.distributional_probability for r in assessed]
            logger.info(f"\nTail Assessment Summary ({len(assessed)} scenarios):")
            logger.info(f"  Distributional probability: min={min(probs):.2f}, median={np.median(probs):.2f}, max={max(probs):.2f}")
            
            extrapolation_types = defaultdict(int)
            for r in assessed:
                extrapolation_types[r.assessment.extrapolation_type] += 1
            logger.info(f"  Extrapolation types: {dict(extrapolation_types)}")

    def generate_all(self, progress_interval: int = 10) -> List[SyntheticScenario]:
        """Generate scenarios for all anchors with full audit trail."""
        # Suppress verbose HTTP logging from OpenAI's httpx
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("openai").setLevel(logging.WARNING)

        all_scenarios = []
        n_anchors = len(self.movements)
        target_total = n_anchors * self.scenarios_per_anchor

        logger.info(f"Generating {target_total} scenarios from {n_anchors} anchors "
                   f"({self.scenarios_per_anchor}/anchor)...")

        for i, anchor in enumerate(self.movements):
            # Progress logging - show percentage
            if (i + 1) % progress_interval == 0 or i == n_anchors - 1:
                pct = 100 * (i + 1) / n_anchors
                logger.info(f"Progress: {pct:.0f}% ({i + 1}/{n_anchors} anchors), "
                           f"{self.total_scenarios} scenarios")

            scenarios = self.generate_for_anchor(anchor)

            if not scenarios:
                self.failed_anchors += 1
                logger.warning(f"Anchor {anchor.id} failed after all retries")

            all_scenarios.extend(scenarios)

        # Final summary only
        scenario_severities = np.array([s.severity_ratio for s in all_scenarios])
        n_above_max = np.sum(scenario_severities > self.max_severity) if len(scenario_severities) > 0 else 0

        logger.info(f"\n{'='*60}")
        logger.info(f"GENERATION COMPLETE")
        logger.info(f"{'='*60}")
        logger.info(f"Scenarios: {self.total_scenarios} (target: {target_total})")
        logger.info(f"Yield: {100*self.total_scenarios/target_total:.0f}%")
        logger.info(f"Failed anchors: {self.failed_anchors}/{n_anchors}")
        logger.info(f"Retries: {self.retried_calls}")
        if len(scenario_severities) > 0:
            logger.info(f"Severity: {scenario_severities.min():.1%} - {scenario_severities.max():.1%} "
                       f"({n_above_max} above historical max)")
        logger.info(f"API calls: {self.api_calls}, Tokens: {self.total_tokens:,}")
        logger.info(f"{'='*60}")
        
        return all_scenarios
    
    def save_audit_trail(self, output_path: str):
        """Save complete audit trail to JSON file."""
        if not self.audit_records:
            logger.warning("No audit records to save")
            return
        
        # Convert to serializable format
        def audit_to_dict(record: ScenarioAuditRecord) -> Dict:
            d = {
                'scenario_id': record.scenario_id,
                'anchor_id': record.anchor_id,
                'generation_timestamp': record.generation_timestamp,
                'call_index': record.call_index,
                'anchor': {
                    'syndicate': record.anchor_syndicate,
                    'year': record.anchor_year,
                    'severity': record.anchor_severity,
                    'lob': record.anchor_lob,
                    'narrative': record.anchor_narrative,
                    'causes': record.anchor_causes
                },
                'few_shot_examples': [
                    {
                        'id': ex.id,
                        'syndicate': ex.syndicate,
                        'year': ex.year,
                        'severity_ratio': ex.severity_ratio,
                        'line_of_business': ex.line_of_business,
                        'narrative': ex.narrative,
                        'primary_causes': ex.primary_causes,
                        'distance_to_anchor': ex.distance_to_anchor,
                        'selection_reason': ex.selection_reason  # 'similarity' or 'diversity'
                    }
                    for ex in record.few_shot_examples
                ],
                'generation_params': {
                    'severity_range': record.prompt_severity_range,
                    'extrapolation_requested': record.extrapolation_requested,
                    'random_seed': record.random_seed,
                    'model': record.model_used,
                    'temperature': record.temperature,
                    'generation_time_ms': record.generation_time_ms
                },
                'generated_output': {
                    'raw': record.generated_scenario,
                    'parsed': {
                        'severity': record.parsed_severity,
                        'lob_breakdown': record.parsed_lob_breakdown,
                        'cause_category': record.parsed_cause_category,
                        'narrative': record.parsed_narrative
                    }
                }
            }
            
            # Add assessment if present
            if record.assessment:
                d['assessment'] = {
                    'distributional_probability': record.assessment.distributional_probability,
                    'confidence': record.assessment.confidence,
                    'reasoning': record.assessment.reasoning,
                    'key_similarities': record.assessment.key_similarities,
                    'key_differences': record.assessment.key_differences,
                    'extrapolation_type': record.assessment.extrapolation_type,
                    'risk_factors': record.assessment.risk_factors
                }
            
            return d
        
        # Count selection reasons for metadata
        similarity_count = sum(
            1 for r in self.audit_records 
            for ex in r.few_shot_examples 
            if ex.selection_reason == 'similarity'
        )
        diversity_count = sum(
            1 for r in self.audit_records 
            for ex in r.few_shot_examples 
            if ex.selection_reason == 'diversity'
        )
        
        audit_data = {
            'metadata': {
                'total_scenarios': len(self.audit_records),
                'total_anchors': len(self.movements),
                'edge_case_threshold': self.edge_case_threshold,
                'max_historical_severity': self.max_severity,
                'generation_model': self.config.llm_model,
                'few_shot_selection': {
                    'similarity_examples': similarity_count,
                    'diversity_examples': diversity_count,
                    'total_examples': similarity_count + diversity_count
                }
            },
            'records': [audit_to_dict(r) for r in self.audit_records]
        }
        
        with open(output_path, 'w') as f:
            json.dump(audit_data, f, indent=2, default=str)
        
        logger.info(f"Saved {len(self.audit_records)} audit records to {output_path}")
        logger.info(f"  Few-shot examples: {similarity_count} similarity, {diversity_count} diversity")


# =============================================================================
# Quantile-Based Importance Sampling
# =============================================================================

def compute_quantile_bins(severities: np.ndarray, n_bins: int = 20) -> List[Tuple[float, float]]:
    """
    Compute severity bins based on quantiles of the distribution.
    Each bin contains 5% of observations (for 20 bins).
    """
    percentiles = np.linspace(0, 100, n_bins + 1)
    thresholds = np.percentile(severities, percentiles)
    
    bins = []
    for i in range(n_bins):
        bins.append((thresholds[i], thresholds[i + 1]))
    
    return bins


def sample_for_coverage(scenarios: List[SyntheticScenario],
                        quantile_bins: List[Tuple[float, float]],
                        min_per_bin: int = 50) -> List[SyntheticScenario]:
    """
    Sample scenarios to ensure minimum coverage per quantile bin.
    
    For bins with insufficient scenarios, oversample.
    For bins with excess, undersample to balance.
    """
    # Assign scenarios to bins
    bin_assignments = defaultdict(list)
    
    for s in scenarios:
        for i, (lo, hi) in enumerate(quantile_bins):
            if lo <= s.severity_ratio <= hi:
                bin_assignments[i].append(s)
                break
        else:
            # Beyond all bins - assign to highest
            bin_assignments[len(quantile_bins) - 1].append(s)
    
    # Report coverage
    logger.info("Pre-sampling bin coverage:")
    for i, (lo, hi) in enumerate(quantile_bins):
        count = len(bin_assignments[i])
        status = "✓" if count >= min_per_bin else "✗"
        logger.info(f"  Bin {i+1} ({lo:.1%}-{hi:.1%}): {count} scenarios {status}")
    
    # Sample
    sampled = []
    
    for i, (lo, hi) in enumerate(quantile_bins):
        bin_scenarios = bin_assignments[i]
        
        if len(bin_scenarios) == 0:
            logger.warning(f"Bin {i+1} ({lo:.1%}-{hi:.1%}) has no scenarios!")
            continue
        
        if len(bin_scenarios) >= min_per_bin:
            # Undersample to target
            selected = random.sample(bin_scenarios, min_per_bin)
        else:
            # Oversample with replacement
            selected = random.choices(bin_scenarios, k=min_per_bin)
        
        sampled.extend(selected)
    
    logger.info(f"Sampled {len(sampled)} scenarios ({min_per_bin} per bin × {len(quantile_bins)} bins)")
    
    return sampled


# =============================================================================
# Main Entry Point
# =============================================================================

def generate_anchor_based_scenarios(
    historical_movements: List[HistoricalMovement],
    embedding_space,
    config: GenerationConfig = None,
    scenarios_per_anchor: int = 10
) -> Tuple[List[SyntheticScenario], Dict]:
    """
    Main entry point for anchor-based generation.
    
    Returns:
        (scenarios, stats)
    """
    generator = AnchorBasedGenerator(historical_movements, embedding_space, config)
    generator.scenarios_per_anchor = scenarios_per_anchor
    
    scenarios = generator.generate_all()
    
    stats = {
        'n_anchors': len(historical_movements),
        'scenarios_per_anchor': scenarios_per_anchor,
        'total_scenarios': generator.total_scenarios,
        'failed_anchors': generator.failed_anchors,
        'api_calls': generator.api_calls,
        'retried_calls': generator.retried_calls,
        'total_tokens': generator.total_tokens
    }
    
    return scenarios, stats


def apply_quantile_sampling(
    scenarios: List[SyntheticScenario],
    historical_severities: np.ndarray,
    n_bins: int = 20,
    min_per_bin: int = 50
) -> Tuple[List[SyntheticScenario], List[Tuple[float, float]]]:
    """
    Apply quantile-based importance sampling.
    
    Returns:
        (sampled_scenarios, quantile_bins)
    """
    quantile_bins = compute_quantile_bins(historical_severities, n_bins)
    sampled = sample_for_coverage(scenarios, quantile_bins, min_per_bin)
    return sampled, quantile_bins
