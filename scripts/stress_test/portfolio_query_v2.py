"""
Portfolio Query v2 - Neighbour-Based Empirical Return Periods

Query approach:
1. Find 500 nearest neighbours to portfolio in embedding space
2. Compute empirical severity distribution from those 500
3. Return period → percentile of neighbour distribution
4. Return top scenarios at that severity with diverse causes
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
from collections import defaultdict, Counter
import hashlib

from openai import OpenAI

from config import (
    QueryConfig, DEFAULT_QUERY_CONFIG,
    PortfolioSpec, SyntheticScenario, StressScenario,
    HistoricalMovement, LLOYDS_LOBS, LOB_TO_INDEX
)
from evt_threshold import GPDFit, return_period_to_severity

logger = logging.getLogger(__name__)


# =============================================================================
# Neighbour-Based Query
# =============================================================================

class NeighbourBasedQuery:
    """
    Query scenarios using neighbour-based empirical distribution.
    
    Steps:
    1. Find k nearest neighbours by PORTFOLIO SIMILARITY (LOB mix + complexity)
    2. ADJUST each neighbour's severity for the query portfolio's LOB mix
    3. Build empirical severity distribution from adjusted severities
    4. Map return period to severity via percentile
    5. Select diverse scenarios at that severity
    
    Key insight: Neighbours are similar by portfolio, NOT by severity.
    This lets us ask "what severities do portfolios like mine experience?"
    
    Severity adjustment: Even similar portfolios have different LOB weights.
    We adjust each scenario's severity to reflect how the QUERY portfolio
    would experience that scenario, based on LOB-level severity factors.
    """
    
    def __init__(self,
                 scenarios: List[SyntheticScenario],
                 embedding_space=None,  # Optional, not used for neighbour search
                 gpd_fit: GPDFit = None,
                 config: QueryConfig = None):
        self.scenarios = scenarios
        self.embedding_space = embedding_space  # Kept for potential future use
        self.gpd_fit = gpd_fit
        self.config = config or DEFAULT_QUERY_CONFIG
        self.client = OpenAI()
        
        # Index scenarios by LOB vectors for portfolio similarity search
        self._build_scenario_index()
        
        # Compute LOB-level severity factors from library
        self._compute_lob_severity_factors()
    
    def _build_scenario_index(self):
        """Build index of scenario LOB vectors for portfolio-based lookup."""
        self.scenario_lob_vectors = []
        self.scenario_complexities = []
        self.valid_scenarios = []
        
        for s in self.scenarios:
            # Build LOB vector for this scenario
            lob_vector = np.zeros(len(LLOYDS_LOBS))
            if s.lob_breakdown:
                total = sum(s.lob_breakdown.values())
                if total > 0:
                    for lob, weight in s.lob_breakdown.items():
                        if lob in LOB_TO_INDEX:
                            lob_vector[LOB_TO_INDEX[lob]] = weight / total
            
            # Only include if has LOB exposure
            if np.sum(lob_vector) > 0:
                self.scenario_lob_vectors.append(lob_vector)
                self.scenario_complexities.append(s.complexity_score or 100)
                self.valid_scenarios.append(s)
        
        if self.scenario_lob_vectors:
            self.scenario_lob_vectors = np.array(self.scenario_lob_vectors)
            self.scenario_complexities = np.array(self.scenario_complexities)
        else:
            self.scenario_lob_vectors = np.array([]).reshape(0, len(LLOYDS_LOBS))
            self.scenario_complexities = np.array([])
        
        logger.info(f"Indexed {len(self.valid_scenarios)} scenarios with LOB vectors")
    
    def _compute_lob_severity_factors(self):
        """
        Compute average severity per LOB from the scenario library.
        
        For each LOB, computes weighted average severity where weight is the
        LOB's presence in each scenario. This gives us a "severity loading"
        factor for each LOB.
        
        These factors are used to adjust scenario severities when the query
        portfolio has a different LOB mix than the scenario's LOB mix.
        """
        # Initialize accumulators
        lob_severity_sum = np.zeros(len(LLOYDS_LOBS))
        lob_weight_sum = np.zeros(len(LLOYDS_LOBS))
        
        for s in self.valid_scenarios:
            if not s.lob_breakdown or s.severity_ratio is None:
                continue
            
            total = sum(s.lob_breakdown.values())
            if total <= 0:
                continue
            
            for lob, weight in s.lob_breakdown.items():
                if lob in LOB_TO_INDEX:
                    idx = LOB_TO_INDEX[lob]
                    normalized_weight = weight / total
                    lob_severity_sum[idx] += s.severity_ratio * normalized_weight
                    lob_weight_sum[idx] += normalized_weight
        
        # Compute average severity per LOB
        self.lob_severity_factors = np.zeros(len(LLOYDS_LOBS))
        for i in range(len(LLOYDS_LOBS)):
            if lob_weight_sum[i] > 0:
                self.lob_severity_factors[i] = lob_severity_sum[i] / lob_weight_sum[i]
            else:
                # Default to overall average if no data for this LOB
                all_severities = [s.severity_ratio for s in self.valid_scenarios if s.severity_ratio]
                self.lob_severity_factors[i] = np.mean(all_severities) if all_severities else 0.10
        
        # Log LOB severity factors
        logger.info("LOB Severity Factors (from library):")
        for i, lob in enumerate(LLOYDS_LOBS):
            if lob_weight_sum[i] > 0:
                logger.info(f"  {lob}: {self.lob_severity_factors[i]:.1%} (n={lob_weight_sum[i]:.0f})")
    
    def _compute_portfolio_severity_loading(self, lob_weights: Dict[str, float]) -> float:
        """
        Compute severity loading for a portfolio based on its LOB mix.
        
        This is the weighted average of LOB severity factors using the
        portfolio's LOB weights.
        """
        loading = 0.0
        total_weight = 0.0
        
        for lob, weight in lob_weights.items():
            if lob in LOB_TO_INDEX and weight > 0:
                idx = LOB_TO_INDEX[lob]
                loading += self.lob_severity_factors[idx] * weight
                total_weight += weight
        
        if total_weight > 0:
            return loading / total_weight
        return np.mean(self.lob_severity_factors)  # Fallback to overall average
    
    def _adjust_severities_for_portfolio(self,
                                         neighbours: List[Tuple[SyntheticScenario, float]],
                                         portfolio: PortfolioSpec) -> List[Tuple[SyntheticScenario, float, float]]:
        """
        Adjust each neighbour's severity for the query portfolio's LOB mix.
        
        Even though neighbours have similar LOB mixes, they're not identical.
        This adjustment scales each scenario's severity based on how the
        query portfolio's LOB weights differ from the scenario's LOB weights.
        
        adjustment = query_loading / scenario_loading
        adjusted_severity = raw_severity × adjustment
        
        Returns:
            List of (scenario, distance, adjusted_severity) tuples
        """
        # Compute query portfolio's severity loading
        query_loading = self._compute_portfolio_severity_loading(portfolio.lob_weights)
        
        logger.info(f"Query portfolio severity loading: {query_loading:.1%}")
        
        adjusted = []
        adjustment_factors = []
        
        for scenario, distance in neighbours:
            # Compute scenario's severity loading
            if scenario.lob_breakdown:
                scenario_loading = self._compute_portfolio_severity_loading(scenario.lob_breakdown)
            else:
                scenario_loading = query_loading  # No adjustment if no LOB data
            
            # Compute adjustment factor
            if scenario_loading > 0:
                adjustment = query_loading / scenario_loading
            else:
                adjustment = 1.0
            
            # Apply adjustment to severity
            raw_severity = scenario.severity_ratio
            adjusted_severity = raw_severity * adjustment
            
            adjusted.append((scenario, distance, adjusted_severity))
            adjustment_factors.append(adjustment)
        
        # Log adjustment statistics
        adjustments = np.array(adjustment_factors)
        logger.info(f"Severity adjustment factors: "
                   f"min={adjustments.min():.2f}, median={np.median(adjustments):.2f}, max={adjustments.max():.2f}")
        
        # Compare raw vs adjusted severities
        raw_sevs = np.array([s.severity_ratio for s, d in neighbours])
        adj_sevs = np.array([adj_sev for s, d, adj_sev in adjusted])
        logger.info(f"Raw severities:      median={np.median(raw_sevs):.1%}, 99th={np.percentile(raw_sevs, 99):.1%}")
        logger.info(f"Adjusted severities: median={np.median(adj_sevs):.1%}, 99th={np.percentile(adj_sevs, 99):.1%}")
        
        return adjusted

    def find_neighbours(self, 
                        portfolio: PortfolioSpec, 
                        k: int = 500) -> List[Tuple[SyntheticScenario, float]]:
        """
        Find k nearest neighbours by PORTFOLIO SIMILARITY only.
        
        Similarity based on:
        1. LOB mix (cosine similarity of LOB weight vectors)
        2. Portfolio complexity
        
        NOT based on severity or cause - we want to find what severities
        similar portfolios experienced.
        
        Returns list of (scenario, distance) tuples sorted by distance.
        """
        if len(self.scenario_lob_vectors) == 0:
            logger.warning("No indexed scenarios available")
            return []
        
        # Build portfolio LOB vector
        portfolio_lob_vector = np.zeros(len(LLOYDS_LOBS))
        for lob, weight in portfolio.lob_weights.items():
            if lob in LOB_TO_INDEX:
                portfolio_lob_vector[LOB_TO_INDEX[lob]] = weight
        
        # Normalize
        portfolio_norm = np.linalg.norm(portfolio_lob_vector)
        if portfolio_norm > 0:
            portfolio_lob_vector = portfolio_lob_vector / portfolio_norm
        
        # Compute cosine similarity for LOB mix
        scenario_norms = np.linalg.norm(self.scenario_lob_vectors, axis=1, keepdims=True)
        scenario_norms = np.where(scenario_norms > 0, scenario_norms, 1)  # Avoid division by zero
        normalized_scenarios = self.scenario_lob_vectors / scenario_norms
        
        cosine_similarities = normalized_scenarios @ portfolio_lob_vector
        
        # Convert to distance (1 - similarity)
        lob_distances = 1 - cosine_similarities
        
        # Compute complexity distance (normalized)
        complexity_range = max(self.scenario_complexities.max() - self.scenario_complexities.min(), 1)
        complexity_distances = np.abs(self.scenario_complexities - portfolio.complexity_score) / complexity_range
        
        # Combined distance: weighted average (LOB more important)
        # LOB weight: 0.8, Complexity weight: 0.2
        combined_distances = 0.8 * lob_distances + 0.2 * complexity_distances
        
        # Sort by distance
        sorted_indices = np.argsort(combined_distances)
        
        # Return top k
        neighbours = []
        for i in sorted_indices[:k]:
            neighbours.append((self.valid_scenarios[i], combined_distances[i]))
        
        # Log statistics about neighbours found
        if neighbours:
            neighbour_severities = [s.severity_ratio for s, d in neighbours]
            logger.info(f"Neighbour severity range: {min(neighbour_severities):.1%} - {max(neighbour_severities):.1%}")
        
        return neighbours
    
    def compute_empirical_severity(self,
                                   adjusted_neighbours: List[Tuple[SyntheticScenario, float, float]],
                                   return_period: int) -> Tuple[float, np.ndarray]:
        """
        Compute severity from empirical distribution of ADJUSTED portfolio-similar neighbours.
        
        Logic:
        - We have N scenarios affecting portfolios similar to ours
        - Their severities have been ADJUSTED for the query portfolio's LOB mix
        - The adjusted severities form an empirical distribution
        - 1-in-X return period = (1 - 1/X) percentile of that distribution
        - E.g., 1-in-100 = 99th percentile
        
        This is more realistic than GPD extrapolation because:
        - Severity comes from actual scenarios, not formula extrapolation
        - The scenarios are relevant to THIS portfolio type
        - Severity is adjusted for the exact LOB mix of the query portfolio
        
        Args:
            adjusted_neighbours: List of (scenario, distance, adjusted_severity) tuples
            return_period: Return period in years
        
        Returns:
            (target_severity, all_adjusted_severities)
        """
        # Use adjusted severities (third element of tuple)
        severities = np.array([adj_sev for s, d, adj_sev in adjusted_neighbours])
        
        # Return period to percentile
        # 1-in-N means we expect to exceed this once in N years
        # So (N-1)/N of observations should be below this = (1 - 1/N) percentile
        percentile = 100 * (1 - 1 / return_period)
        
        target_severity = np.percentile(severities, percentile)
        
        logger.info(f"Portfolio-similar scenarios (adjusted): n={len(severities)}")
        logger.info(f"  Adjusted severity range: {severities.min():.1%} to {severities.max():.1%}")
        logger.info(f"  Median: {np.median(severities):.1%}, Mean: {severities.mean():.1%}")
        logger.info(f"  {return_period}-year return period = {percentile:.1f}th percentile = {target_severity:.1%}")
        
        return target_severity, severities
    
    def select_scenarios_at_severity(self,
                                     adjusted_neighbours: List[Tuple[SyntheticScenario, float, float]],
                                     target_severity: float,
                                     n_scenarios: int = 5,
                                     tolerance: float = 0.05) -> List[SyntheticScenario]:
        """
        Select diverse scenarios near target severity.
        
        Uses ADJUSTED severity for filtering (target_severity was computed from adjusted values).
        
        Ensures diversity across:
        - Cause categories
        - LOB exposure
        - Source anchors
        """
        # Filter to severity band using ADJUSTED severity
        candidates = []
        for s, d, adj_sev in adjusted_neighbours:
            if abs(adj_sev - target_severity) <= tolerance:
                candidates.append((s, d, adj_sev))
        
        # Expand tolerance if needed
        if len(candidates) < n_scenarios:
            expanded_tolerance = tolerance * 2
            candidates = []
            for s, d, adj_sev in adjusted_neighbours:
                if abs(adj_sev - target_severity) <= expanded_tolerance:
                    candidates.append((s, d, adj_sev))
            logger.info(f"Expanded tolerance to {expanded_tolerance:.1%}: {len(candidates)} candidates")
        
        # Still not enough? Take closest to target adjusted severity
        if len(candidates) < n_scenarios:
            by_severity_diff = sorted(adjusted_neighbours, key=lambda x: abs(x[2] - target_severity))
            candidates = by_severity_diff[:max(n_scenarios * 3, 20)]
            logger.info(f"Using {len(candidates)} closest by adjusted severity")
        
        # Select for diversity BY CAUSE CATEGORY (not by LOB)
        # Each scenario is already a holistic multi-peril event affecting multiple LOBs
        selected = []
        causes_seen = set()
        
        # First pass: one scenario per cause category (sorted by portfolio distance)
        # This ensures we get diverse types of scenarios (cat, pandemic, social inflation, etc.)
        for s, d, adj_sev in sorted(candidates, key=lambda x: x[1]):  # By distance
            if len(selected) >= n_scenarios:
                break
            if s.cause_category not in causes_seen:
                selected.append(s)
                causes_seen.add(s.cause_category)
        
        # Second pass: fill remaining slots with best portfolio matches
        # Don't diversify by LOB - each holistic scenario already affects multiple LOBs
        for s, d, adj_sev in sorted(candidates, key=lambda x: x[1]):
            if len(selected) >= n_scenarios:
                break
            if s not in selected:
                selected.append(s)
        
        return selected
    
    def generate_explanation(self,
                             scenario: SyntheticScenario,
                             portfolio: PortfolioSpec,
                             return_period: int,
                             target_severity: float,
                             lob_impacts: Dict[str, float]) -> str:
        """Generate explanation for scenario."""
        portfolio_text = ", ".join([
            f"{lob}: {w:.0%}" for lob, w in portfolio.lob_weights.items() if w > 0
        ])
        
        impacts_text = ", ".join([
            f"{lob}: {sev:.1%}" for lob, sev in lob_impacts.items() if sev > 0
        ])
        
        prompt = f"""Explain this stress test scenario for a board presentation (150-200 words):

SCENARIO: {scenario.cause_category}
- Events: {', '.join(scenario.specific_events[:3]) if scenario.specific_events else 'N/A'}
- Severity: {target_severity:.1%} adverse development ({return_period}-year return period)
- Original narrative: {scenario.narrative}

PORTFOLIO:
- Total reserves: £{portfolio.total_reserves_gbp_m:.0f}m
- LOB mix: {portfolio_text}
- Complexity: {portfolio.complexity_score:.0f}

LOB IMPACTS: {impacts_text}

Provide:
1. What triggers this scenario
2. Why this portfolio is exposed
3. Key uncertainties

IMPORTANT: Do NOT reference specific years (e.g., "in 2023", "2024 event"). 
Use hypothetical/forward-looking language as this is a stress test, not a historical description."""

        try:
            response = self.client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "You are a senior actuary writing stress test documentation. Write in hypothetical terms without referencing specific calendar years."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=500
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.warning(f"Failed to generate explanation: {e}")
            return scenario.narrative or "No narrative available."
    
    def query(self,
              portfolio: PortfolioSpec,
              return_period: int,
              n_scenarios: int = 5,
              n_neighbours: int = 500) -> List[StressScenario]:
        """
        Main query method.
        
        Process:
        1. Find n_neighbours scenarios with similar PORTFOLIO (LOB mix + complexity)
        2. ADJUST each scenario's severity for the query portfolio's LOB mix
        3. Compute return period severity from ADJUSTED distribution
        4. Select diverse scenarios at that severity level
        
        Args:
            portfolio: Portfolio specification (LOB weights, reserves, complexity)
            return_period: Return period in years (e.g., 100 for 1-in-100)
            n_scenarios: Number of scenarios to return
            n_neighbours: Number of portfolio-similar scenarios to consider
        
        Returns:
            List of stress scenarios with explanations
        """
        portfolio_desc = ", ".join(f"{l}:{w:.0%}" for l, w in portfolio.lob_weights.items() if w > 0)
        logger.info(f"Querying: £{portfolio.total_reserves_gbp_m:.0f}m portfolio [{portfolio_desc}]")
        logger.info(f"Complexity: {portfolio.complexity_score:.0f}, Return period: {return_period}y")
        
        # Step 1: Find portfolio-similar neighbours (by LOB mix, NOT by severity)
        neighbours = self.find_neighbours(portfolio, n_neighbours)
        
        if not neighbours:
            logger.error("No similar portfolios found in library")
            return []
        
        logger.info(f"Found {len(neighbours)} portfolio-similar scenarios")
        
        # Step 2: ADJUST severities for query portfolio's LOB mix
        # Each scenario's severity is scaled based on how the query portfolio's
        # LOB weights compare to the scenario's LOB weights
        adjusted_neighbours = self._adjust_severities_for_portfolio(neighbours, portfolio)
        
        # Step 3: Compute empirical severity from ADJUSTED distribution
        target_severity, all_severities = self.compute_empirical_severity(
            adjusted_neighbours, return_period
        )
        
        # Step 4: Select diverse scenarios at that severity (using adjusted severities)
        selected = self.select_scenarios_at_severity(
            adjusted_neighbours, target_severity, n_scenarios
        )
        
        logger.info(f"Selected {len(selected)} scenarios at {target_severity:.1%} adjusted severity")
        
        # Step 4: Build output scenarios with explanations
        stress_scenarios = []
        
        for i, scenario in enumerate(selected):
            logger.info(f"Processing scenario {i+1}/{len(selected)}: {scenario.cause_category}")
            
            # Compute LOB impacts for this portfolio
            lob_impacts = self._compute_lob_impacts(scenario, portfolio, target_severity)
            
            # Portfolio impact
            portfolio_impact = sum(
                lob_impacts.get(lob, 0) * portfolio.lob_weights.get(lob, 0)
                for lob in set(lob_impacts.keys()) | set(portfolio.lob_weights.keys())
            )
            
            # Generate explanation
            explanation = self.generate_explanation(
                scenario, portfolio, return_period, target_severity, lob_impacts
            )
            
            # Create output
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
                causal_chain=f"{scenario.cause_category}: {', '.join(scenario.specific_events[:3]) if scenario.specific_events else 'N/A'}",
                historical_analogues=[],
                explanation=explanation,
                confidence_level=1 - 1/return_period,
                source_scenarios=[scenario.id]
            )
            
            stress_scenarios.append(stress)
        
        return stress_scenarios
    
    def _compute_lob_impacts(self,
                             scenario: SyntheticScenario,
                             portfolio: PortfolioSpec,
                             target_severity: float) -> Dict[str, float]:
        """Compute LOB-level impacts adjusted for portfolio."""
        if not scenario.lob_breakdown:
            # Distribute evenly
            exposed_lobs = [l for l, w in portfolio.lob_weights.items() if w > 0]
            per_lob = target_severity / len(exposed_lobs) if exposed_lobs else 0
            return {l: per_lob for l in exposed_lobs}
        
        # Scale scenario LOB breakdown to target severity
        original_total = sum(abs(v) for v in scenario.lob_breakdown.values())
        if original_total == 0:
            original_total = 1
        
        scale = target_severity / original_total
        
        impacts = {}
        for lob, sev in scenario.lob_breakdown.items():
            if portfolio.lob_weights.get(lob, 0) > 0:
                impacts[lob] = sev * scale
        
        # Rebalance if some LOBs were removed
        if impacts:
            current_total = sum(impacts.values())
            if current_total > 0:
                rebalance = target_severity / current_total
                impacts = {l: v * rebalance for l, v in impacts.items()}
        
        return impacts


# =============================================================================
# Convenience Functions
# =============================================================================

def create_portfolio(lob_weights: Dict[str, float],
                     total_reserves: float) -> PortfolioSpec:
    """Create a portfolio specification."""
    # Normalize weights
    total = sum(lob_weights.values())
    if total > 0:
        lob_weights = {k: v/total for k, v in lob_weights.items()}
    
    # Compute complexity (reserves × (1 - HHI))
    hhi = sum(w**2 for w in lob_weights.values())
    complexity = total_reserves * (1 - hhi)
    
    # Create LOB vector (used for logging only - PortfolioSpec computes its own)
    lob_vector = [0.0] * len(LLOYDS_LOBS)
    for lob, weight in lob_weights.items():
        if lob in LOB_TO_INDEX:
            lob_vector[LOB_TO_INDEX[lob]] = weight
    
    # PortfolioSpec only takes lob_weights and total_reserves_gbp_m
    # Other values (lob_vector, hhi, complexity_score) are computed properties
    return PortfolioSpec(
        total_reserves_gbp_m=total_reserves,
        lob_weights=lob_weights
    )


def query_scenarios(scenarios: List[SyntheticScenario],
                    embedding_space,
                    lob_weights: Dict[str, float],
                    total_reserves: float,
                    return_period: int = 100,
                    n_scenarios: int = 5,
                    n_neighbours: int = 500) -> List[StressScenario]:
    """
    Convenience function for querying scenarios.
    """
    portfolio = create_portfolio(lob_weights, total_reserves)
    
    engine = NeighbourBasedQuery(scenarios, embedding_space)
    
    return engine.query(portfolio, return_period, n_scenarios, n_neighbours)
