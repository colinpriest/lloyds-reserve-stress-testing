"""
Phase 2: Portfolio-Specific Scenario Selection and Fine-Tuning

Given a user's portfolio specification:
1. Convert return period to severity using GPD
2. Filter scenario library by severity band and complexity
3. Select diverse scenarios matching portfolio LOB exposure
4. Fine-tune scenarios to exact portfolio (zero out unexposed LOBs)
5. Generate chain-of-thought explanations with historical analogues
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
from typing import List, Dict, Tuple, Optional
from collections import defaultdict
import hashlib

from openai import OpenAI

from config import (
    QueryConfig, DEFAULT_QUERY_CONFIG,
    PortfolioSpec, SyntheticScenario, StressScenario,
    HistoricalMovement, LLOYDS_LOBS, LOB_TO_INDEX
)
from evt_threshold import GPDFit, return_period_to_severity
from joint_embedding import JointEmbeddingSpace

logger = logging.getLogger(__name__)


# =============================================================================
# Scenario Filtering and Selection
# =============================================================================

def filter_scenarios_by_criteria(scenarios: List[SyntheticScenario],
                                 target_severity: float,
                                 target_complexity: float,
                                 portfolio_lobs: List[str],
                                 config: QueryConfig) -> List[SyntheticScenario]:
    """
    Filter scenarios by severity, complexity, and LOB compatibility.
    
    If target_severity exceeds library max, returns highest severity scenarios
    (to be scaled up during fine-tuning).
    """
    # Check if we're extrapolating beyond library max
    max_severity = max(s.severity_ratio for s in scenarios)
    extrapolating = target_severity > max_severity * 1.1  # 10% buffer
    
    if extrapolating:
        logger.info(f"Target {target_severity:.1%} exceeds library max {max_severity:.1%} - using highest severity scenarios")
        # Use high severity scenarios (top 20% or above 50%)
        severity_threshold = max(0.5, np.percentile([s.severity_ratio for s in scenarios], 80))
    
    candidates = []
    
    for s in scenarios:
        # Severity check
        if extrapolating:
            # When extrapolating, take high-severity scenarios
            if s.severity_ratio < severity_threshold:
                continue
        else:
            # Normal case: within tolerance band
            if not (target_severity - config.severity_tolerance <= s.severity_ratio <= 
                    target_severity + config.severity_tolerance):
                continue
        
        # Complexity check
        if not (target_complexity - config.complexity_tolerance <= s.complexity_score <=
                target_complexity + config.complexity_tolerance):
            continue
        
        # LOB compatibility: scenario must affect at least one portfolio LOB
        scenario_lobs = set(s.lob_breakdown.keys()) if s.lob_breakdown else set()
        if not scenario_lobs & set(portfolio_lobs):
            # No overlap - penalise heavily but don't exclude entirely
            # (might be a market-wide scenario)
            if s.cause_category not in ['Pandemic', 'Regulatory', 'Economic',
                                         'Pandemic / systemic events',
                                         'Regulatory / legal changes',
                                         'Economic inflation / claims cost increases']:
                continue
        
        candidates.append(s)
    
    return candidates


def select_diverse_scenarios(candidates: List[SyntheticScenario],
                             n_scenarios: int,
                             require_cause_diversity: bool = True) -> List[SyntheticScenario]:
    """
    Select diverse scenarios from candidates.
    
    Ensures variety in:
    - Cause categories
    - Affected LOBs
    - Source historical years (from generation)
    """
    if len(candidates) <= n_scenarios:
        return candidates
    
    selected = []
    causes_seen = set()
    
    # First pass: one per cause category
    for s in candidates:
        if s.cause_category not in causes_seen:
            selected.append(s)
            causes_seen.add(s.cause_category)
            if len(selected) >= n_scenarios:
                break
    
    # Second pass: fill remaining with most different scenarios
    if len(selected) < n_scenarios:
        remaining = [s for s in candidates if s not in selected]
        
        # Sort by diversity score (different LOBs from already selected)
        def diversity_score(s):
            selected_lobs = set()
            for sel in selected:
                selected_lobs.update(sel.lob_breakdown.keys())
            
            new_lobs = set(s.lob_breakdown.keys()) - selected_lobs
            return len(new_lobs)
        
        remaining.sort(key=diversity_score, reverse=True)
        
        for s in remaining:
            selected.append(s)
            if len(selected) >= n_scenarios:
                break
    
    return selected


# =============================================================================
# Portfolio Fine-Tuning
# =============================================================================

def fine_tune_scenario(scenario: SyntheticScenario,
                       portfolio: PortfolioSpec,
                       target_severity: float) -> Tuple[Dict[str, float], Dict]:
    """
    Fine-tune scenario to exact portfolio:
    1. Zero out LOBs with 0% portfolio exposure
    2. Rebalance severity to maintain target
    3. Track adjustments for audit trail
    
    Returns:
        (adjusted_lob_impacts, adjustment_audit)
    """
    adjustments = {
        'zeroed_lobs': [],
        'original_total': 0,
        'adjusted_total': 0,
        'scaling_factor': 1.0
    }
    
    original_breakdown = scenario.lob_breakdown or {}
    
    # Calculate original total severity
    original_total = sum(abs(v) for v in original_breakdown.values())
    adjustments['original_total'] = original_total
    
    # Zero out unexposed LOBs
    adjusted = {}
    for lob, severity in original_breakdown.items():
        if portfolio.lob_weights.get(lob, 0) > 0:
            adjusted[lob] = severity
        else:
            adjustments['zeroed_lobs'].append(lob)
    
    # Calculate new total
    new_total = sum(abs(v) for v in adjusted.values())
    
    # Rebalance to maintain target severity
    if new_total > 0 and original_total > 0:
        scaling_factor = target_severity / (new_total + 1e-10)
        for lob in adjusted:
            adjusted[lob] *= scaling_factor
        adjustments['scaling_factor'] = scaling_factor
    else:
        # Distribute evenly across exposed LOBs
        exposed_lobs = [l for l in portfolio.lob_weights if portfolio.lob_weights[l] > 0]
        per_lob = target_severity / len(exposed_lobs) if exposed_lobs else 0
        adjusted = {l: per_lob for l in exposed_lobs}
    
    adjustments['adjusted_total'] = sum(abs(v) for v in adjusted.values())
    
    return adjusted, adjustments


def compute_portfolio_impact(lob_impacts: Dict[str, float],
                             portfolio: PortfolioSpec) -> float:
    """
    Compute weighted portfolio impact.
    
    Impact = Σ(LOB_weight × LOB_severity)
    """
    impact = 0.0
    for lob, severity in lob_impacts.items():
        weight = portfolio.lob_weights.get(lob, 0)
        impact += weight * severity
    return impact


# =============================================================================
# Chain-of-Thought Explanation
# =============================================================================

def generate_explanation(scenario: SyntheticScenario,
                         portfolio: PortfolioSpec,
                         return_period: int,
                         target_severity: float,
                         lob_impacts: Dict[str, float],
                         historical_analogues: List[Dict],
                         client: OpenAI) -> str:
    """
    Generate chain-of-thought explanation using LLM.
    """
    # Format analogues
    analogues_text = ""
    for i, h in enumerate(historical_analogues[:3], 1):
        analogues_text += f"""
Analogue {i}: {h.get('syndicate', 'Unknown')} ({h.get('year', 'N/A')})
- Severity: {h.get('severity_ratio', 0):.1%}
- Portfolio: complexity={h.get('complexity_score', 0):.0f}
- Cause: {', '.join(h.get('primary_causes', [])[:2])}
- Events: {', '.join(h.get('specific_events', [])[:2])}
"""
    
    # Format portfolio
    portfolio_text = ", ".join([
        f"{lob}: {w:.0%}" for lob, w in portfolio.lob_weights.items() if w > 0
    ])
    
    # Format LOB impacts
    impacts_text = ", ".join([
        f"{lob}: {sev:.1%}" for lob, sev in lob_impacts.items() if sev > 0
    ])
    
    prompt = f"""You are an expert insurance actuary explaining a stress test scenario to a board of directors.

SCENARIO DETAILS:
- Return period: {return_period}-year event (1-in-{return_period} probability)
- Target severity: {target_severity:.1%} adverse prior-year development
- Scenario type: {scenario.cause_category}
- Scenario narrative: {scenario.narrative}
- Events: {', '.join(scenario.specific_events[:3])}

PORTFOLIO CONTEXT:
- Total reserves: £{portfolio.total_reserves_gbp_m:.0f}m
- LOB mix: {portfolio_text}
- Portfolio complexity: {portfolio.complexity_score:.0f}

LOB-LEVEL IMPACTS (after portfolio adjustment):
{impacts_text}

HISTORICAL ANALOGUES:
{analogues_text}

TASK: Explain this stress scenario in a clear, logical chain-of-thought format:

1. WHY THIS SEVERITY IS APPROPRIATE:
   - How does the {return_period}-year return period translate to this severity?
   - Reference the historical analogues to validate the magnitude.

2. CAUSAL MECHANISM:
   - What triggers this scenario?
   - How does the trigger propagate to reserve deterioration?
   - Which LOBs are most affected and why?

3. PORTFOLIO IMPACT:
   - How does your portfolio's LOB mix affect exposure to this scenario?
   - Compare to historical analogues with similar/different portfolio structures.
   - Note any diversification benefits or concentration risks.

4. KEY UNCERTAINTIES:
   - What could make this scenario better or worse?
   - What are the main assumptions?

IMPORTANT: Do not reference specific calendar years (e.g., "2023", "2024"). 
Use hypothetical/forward-looking language as this is a stress test projection.

Provide a clear, professional explanation (300-500 words):"""

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You are a senior actuarial expert providing clear, factual stress test documentation. Write in hypothetical terms without referencing specific calendar years."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.3,
        max_tokens=1000
    )
    
    return response.choices[0].message.content


# =============================================================================
# Portfolio Query Engine
# =============================================================================

class PortfolioQueryEngine:
    """
    Main engine for portfolio-specific stress test queries.
    """
    
    def __init__(self,
                 scenario_library: List[SyntheticScenario],
                 gpd_fit: GPDFit,
                 embedding_space: JointEmbeddingSpace = None,
                 config: QueryConfig = None):
        self.scenarios = scenario_library
        self.gpd_fit = gpd_fit
        self.embedding_space = embedding_space
        self.config = config or DEFAULT_QUERY_CONFIG
        self.client = OpenAI()
    
    def query(self,
              portfolio: PortfolioSpec,
              return_period: int,
              n_scenarios: int = None) -> List[StressScenario]:
        """
        Generate stress scenarios for a specific portfolio.
        
        Args:
            portfolio: Portfolio specification (LOB weights, total reserves)
            return_period: Return period in years (e.g., 100 for 1-in-100)
            n_scenarios: Number of scenarios to generate (default from config)
        
        Returns:
            List of portfolio-specific stress scenarios
        """
        n_scenarios = n_scenarios or self.config.min_scenarios
        
        logger.info(f"Querying scenarios for portfolio: £{portfolio.total_reserves_gbp_m:.0f}m, "
                   f"complexity={portfolio.complexity_score:.0f}")
        
        # Step A: Return period to severity
        target_severity = return_period_to_severity(self.gpd_fit, return_period)
        logger.info(f"Return period {return_period}y → severity {target_severity:.1%}")
        
        # Step B: Filter library
        portfolio_lobs = [l for l, w in portfolio.lob_weights.items() if w > 0]
        
        candidates = filter_scenarios_by_criteria(
            self.scenarios,
            target_severity,
            portfolio.complexity_score,
            portfolio_lobs,
            self.config
        )
        logger.info(f"Found {len(candidates)} candidate scenarios")
        
        if len(candidates) < n_scenarios:
            # Expand search with wider tolerances
            wider_config = QueryConfig(
                severity_tolerance=self.config.severity_tolerance * 3,
                complexity_tolerance=self.config.complexity_tolerance * 3
            )
            candidates = filter_scenarios_by_criteria(
                self.scenarios,
                target_severity,
                portfolio.complexity_score,
                portfolio_lobs,
                wider_config
            )
            logger.info(f"Expanded search: {len(candidates)} candidates")
        
        if len(candidates) < n_scenarios:
            # Very wide search - ignore complexity
            logger.info("Very wide search - relaxing complexity constraint")
            very_wide_config = QueryConfig(
                severity_tolerance=self.config.severity_tolerance * 5,
                complexity_tolerance=10000  # Effectively no limit
            )
            candidates = filter_scenarios_by_criteria(
                self.scenarios,
                target_severity,
                portfolio.complexity_score,
                portfolio_lobs,
                very_wide_config
            )
            logger.info(f"Very wide search: {len(candidates)} candidates")
        
        # Select diverse scenarios
        selected = select_diverse_scenarios(
            candidates, n_scenarios, self.config.cause_diversity
        )
        logger.info(f"Selected {len(selected)} diverse scenarios")
        
        # Step C & D: Fine-tune and generate explanations
        stress_scenarios = []
        
        for i, scenario in enumerate(selected):
            logger.info(f"Processing scenario {i+1}/{len(selected)}: {scenario.cause_category}")
            
            # Fine-tune for portfolio
            lob_impacts, adjustments = fine_tune_scenario(
                scenario, portfolio, target_severity
            )
            
            # Compute portfolio impact
            portfolio_impact = compute_portfolio_impact(lob_impacts, portfolio)
            
            # Find historical analogues
            analogues = self._find_analogues(scenario, portfolio)
            
            # Generate explanation
            explanation = generate_explanation(
                scenario, portfolio, return_period, target_severity,
                lob_impacts, analogues, self.client
            )
            
            # Create output scenario
            scenario_id = hashlib.md5(
                f"{portfolio.total_reserves_gbp_m}_{return_period}_{scenario.id}".encode()
            ).hexdigest()[:10]
            
            stress = StressScenario(
                id=f"stress_{scenario_id}",
                name=f"{return_period}Y {scenario.cause_category}",
                return_period=return_period,
                severity_ratio=target_severity,
                portfolio_impact=portfolio_impact,
                lob_impacts=lob_impacts,
                narrative=scenario.narrative,
                causal_chain=f"{scenario.cause_category}: {', '.join(scenario.specific_events[:3])}",
                historical_analogues=analogues,
                chain_of_thought=explanation,
                source_scenario_id=scenario.id,
                fine_tuning_applied=adjustments
            )
            
            stress_scenarios.append(stress)
        
        return stress_scenarios
    
    def _find_analogues(self,
                        scenario: SyntheticScenario,
                        portfolio: PortfolioSpec,
                        k: int = 3) -> List[Dict]:
        """Find historical analogues for a scenario."""
        if self.embedding_space is None:
            return []
        
        # Find neighbours at similar severity and complexity
        neighbours = self.embedding_space.find_neighbours(
            np.array(scenario.latent_coords) if scenario.latent_coords else np.zeros(3),
            k=k,
            severity_band=(scenario.severity_ratio * 0.5, scenario.severity_ratio * 1.5),
            complexity_band=(portfolio.complexity_score * 0.5, portfolio.complexity_score * 1.5)
        )
        
        return [
            {
                'id': m.id,
                'syndicate': m.syndicate,
                'year': m.year,
                'severity_ratio': m.severity_ratio,
                'complexity_score': m.complexity_score,
                'primary_causes': m.primary_causes,
                'specific_events': m.specific_events,
                'narrative': m.narrative[:200] + '...' if m.narrative else ''
            }
            for m, _ in neighbours
        ]
    
    def save_results(self, scenarios: List[StressScenario], output_path: str):
        """Save stress scenarios to JSON."""
        output_data = {
            'scenarios': [vars(s) for s in scenarios]
        }
        
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, indent=2, default=str)
        
        logger.info(f"Saved {len(scenarios)} stress scenarios to {output_path}")


# =============================================================================
# CLI
# =============================================================================

if __name__ == "__main__":
    import argparse
    
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    
    parser = argparse.ArgumentParser(description="Query stress scenarios for a portfolio")
    parser.add_argument('--library', '-l', required=True,
                        help='Path to scenario library JSON')
    parser.add_argument('--gpd', '-g', required=True,
                        help='Path to GPD fit JSON')
    parser.add_argument('--embedding-space', '-e',
                        help='Path to embedding space directory')
    parser.add_argument('--reserves', '-r', type=float, required=True,
                        help='Total reserves in GBP millions')
    parser.add_argument('--lob', action='append', nargs=2, metavar=('LOB', 'WEIGHT'),
                        help='LOB and weight (can specify multiple times)')
    parser.add_argument('--return-period', '-p', type=int, default=100,
                        help='Return period in years')
    parser.add_argument('--n-scenarios', '-n', type=int, default=5,
                        help='Number of scenarios to generate')
    parser.add_argument('--output', '-o', default='results/stress_test/portfolio_scenarios.json',
                        help='Output path')
    
    args = parser.parse_args()
    
    # Build portfolio spec
    lob_weights = {}
    if args.lob:
        for lob, weight in args.lob:
            lob_weights[lob] = float(weight)
    else:
        # Default portfolio
        lob_weights = {
            'Property': 0.4,
            'Casualty': 0.3,
            'Marine': 0.2,
            'Professional Lines': 0.1
        }
    
    # Normalise weights
    total = sum(lob_weights.values())
    lob_weights = {k: v / total for k, v in lob_weights.items()}
    
    portfolio = PortfolioSpec(
        lob_weights=lob_weights,
        total_reserves_gbp_m=args.reserves
    )
    
    print(f"\n=== Portfolio ===")
    print(f"Reserves: £{portfolio.total_reserves_gbp_m:.0f}m")
    print(f"HHI: {portfolio.hhi:.3f}")
    print(f"Complexity: {portfolio.complexity_score:.0f}")
    print("LOB weights:")
    for lob, w in portfolio.lob_weights.items():
        print(f"  {lob}: {w:.0%}")
    
    # Load data
    with open(args.library, 'r') as f:
        library_data = json.load(f)
    scenarios = [SyntheticScenario(**s) for s in library_data['scenarios']]
    
    with open(args.gpd, 'r') as f:
        gpd_data = json.load(f)
    gpd_fit = GPDFit(**gpd_data)
    
    # Load embedding space if provided
    embedding_space = None
    if args.embedding_space:
        embedding_space = JointEmbeddingSpace.load(args.embedding_space)
    
    # Query
    engine = PortfolioQueryEngine(scenarios, gpd_fit, embedding_space)
    results = engine.query(portfolio, args.return_period, args.n_scenarios)
    
    # Print results
    print(f"\n=== {args.return_period}-Year Stress Scenarios ===")
    for i, s in enumerate(results, 1):
        print(f"\n--- Scenario {i}: {s.name} ---")
        print(f"Severity: {s.severity_ratio:.1%}")
        print(f"Portfolio impact: {s.portfolio_impact:.1%}")
        print(f"LOB impacts:")
        for lob, impact in s.lob_impacts.items():
            print(f"  {lob}: {impact:.1%}")
        print(f"\nNarrative: {s.narrative[:300]}...")
        print(f"\nExplanation: {s.chain_of_thought[:500]}...")
    
    # Save
    engine.save_results(results, args.output)
