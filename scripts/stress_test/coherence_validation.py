"""
Step 7: Coherence Validation

Validates that generated narratives are coherent with their assigned severities:
1. Regression-based validator (predict severity from text)
2. Keyword-severity matching
3. Complexity-LOB consistency
"""

import sys
from pathlib import Path
_script_dir = Path(__file__).resolve().parent
if str(_script_dir) not in sys.path:
    sys.path.insert(0, str(_script_dir))

import numpy as np
import logging
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass
import re
from collections import defaultdict

from config import ValidationConfig, DEFAULT_VALIDATION_CONFIG, SyntheticScenario, LLOYDS_LOBS

logger = logging.getLogger(__name__)


# =============================================================================
# Keyword-Based Severity Matching
# =============================================================================

HIGH_SEVERITY_KEYWORDS = [
    'catastrophic', 'devastating', 'unprecedented', 'extreme', 'severe',
    'massive', 'major', 'significant', 'substantial', 'dramatic',
    'surge', 'spike', 'explosion', 'crisis', 'emergency',
    'worst', 'largest', 'historic', 'record', 'exceptional'
]

MODERATE_SEVERITY_KEYWORDS = [
    'notable', 'considerable', 'meaningful', 'material', 'elevated',
    'increased', 'higher', 'worsening', 'deteriorating', 'adverse'
]

LOW_SEVERITY_KEYWORDS = [
    'minor', 'modest', 'small', 'limited', 'marginal',
    'slight', 'mild', 'minimal', 'routine', 'typical'
]


def keyword_severity_score(text: str) -> float:
    """
    Score text based on severity keywords.
    
    Returns value in [0, 1] where higher = more severe language.
    """
    text_lower = text.lower()
    
    high_count = sum(1 for k in HIGH_SEVERITY_KEYWORDS if k in text_lower)
    mod_count = sum(1 for k in MODERATE_SEVERITY_KEYWORDS if k in text_lower)
    low_count = sum(1 for k in LOW_SEVERITY_KEYWORDS if k in text_lower)
    
    # Weighted score
    total = high_count + mod_count + low_count
    if total == 0:
        return 0.5  # Neutral
    
    score = (high_count * 1.0 + mod_count * 0.5 + low_count * 0.0) / total
    return score


def check_keyword_coherence(scenario: SyntheticScenario,
                            severity_percentile: float) -> Tuple[bool, str]:
    """
    Check if keyword severity matches numeric severity percentile.
    
    Args:
        scenario: Scenario to check
        severity_percentile: Percentile rank of scenario's severity (0-100)
    
    Returns:
        (is_coherent, reason)
    """
    keyword_score = keyword_severity_score(scenario.narrative)
    
    # High severity (top tercile) should have high keyword score
    if severity_percentile >= 66:
        if keyword_score < 0.3:
            return False, f"High severity ({severity_percentile:.0f}th percentile) but low severity keywords"
    
    # Low severity (bottom tercile) should not have high keyword score
    if severity_percentile <= 33:
        if keyword_score > 0.7:
            return False, f"Low severity ({severity_percentile:.0f}th percentile) but high severity keywords"
    
    return True, "OK"


# =============================================================================
# Regression-Based Validator
# =============================================================================

class RegressionValidator:
    """
    Predicts severity from narrative text using TF-IDF + Gradient Boosting.
    """
    
    def __init__(self, zscore_threshold: float = 2.5):
        self.zscore_threshold = zscore_threshold
        self.vectorizer = None
        self.model = None
        self.residual_std = None
    
    def fit(self, texts: List[str], severities: np.ndarray):
        """Train the validator on historical data."""
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.ensemble import GradientBoostingRegressor
        
        logger.info("Training regression validator...")
        
        # TF-IDF vectorization
        self.vectorizer = TfidfVectorizer(
            max_features=1000,
            ngram_range=(1, 2),
            stop_words='english'
        )
        X = self.vectorizer.fit_transform(texts)
        
        # Gradient Boosting regressor
        self.model = GradientBoostingRegressor(
            n_estimators=100,
            max_depth=4,
            random_state=42
        )
        self.model.fit(X.toarray(), severities)
        
        # Compute residual std using cross-validated predictions to avoid train/predict leak
        from sklearn.model_selection import cross_val_predict
        cv_predictions = cross_val_predict(self.model, X.toarray(), severities, cv=5)
        residuals = severities - cv_predictions
        self.residual_std = np.std(residuals)
        
        logger.info(f"Validator trained. Residual std: {self.residual_std:.4f}")
    
    def predict(self, text: str) -> float:
        """Predict severity from text."""
        X = self.vectorizer.transform([text])
        return self.model.predict(X.toarray())[0]
    
    def check_coherence(self, scenario: SyntheticScenario) -> Tuple[bool, float, str]:
        """
        Check if scenario's severity is coherent with its narrative.
        
        Returns:
            (is_coherent, zscore, reason)
        """
        predicted = self.predict(scenario.narrative)
        actual = scenario.severity_ratio
        
        zscore = abs(actual - predicted) / self.residual_std
        
        if zscore > self.zscore_threshold:
            return False, zscore, f"Z-score {zscore:.2f} exceeds threshold"
        
        return True, zscore, "OK"


# =============================================================================
# Complexity-LOB Consistency
# =============================================================================

def check_complexity_lob_consistency(scenario: SyntheticScenario) -> Tuple[bool, str]:
    """
    Check that complexity score is consistent with LOB breakdown.
    
    - High complexity → multiple LOBs affected
    - Low complexity → concentrated in 1-2 LOBs
    """
    lob_breakdown = scenario.lob_breakdown
    if not lob_breakdown:
        return True, "No LOB breakdown"
    
    # Count affected LOBs (non-zero)
    affected_lobs = [lob for lob, sev in lob_breakdown.items() if sev > 0]
    n_affected = len(affected_lobs)
    
    # Compute HHI from breakdown
    total_sev = sum(abs(v) for v in lob_breakdown.values())
    if total_sev > 0:
        weights = [abs(v) / total_sev for v in lob_breakdown.values() if v != 0]
        hhi = sum(w ** 2 for w in weights)
    else:
        hhi = 1.0
    
    complexity = scenario.complexity_score
    
    # Consistency checks
    if complexity < 50:  # Monoline
        if n_affected > 2:
            return False, f"Low complexity ({complexity:.0f}) but {n_affected} LOBs affected"
    
    if complexity > 300:  # Highly diversified
        if n_affected < 3:
            return False, f"High complexity ({complexity:.0f}) but only {n_affected} LOBs affected"
        if hhi > 0.7:
            return False, f"High complexity ({complexity:.0f}) but concentrated HHI ({hhi:.2f})"
    
    return True, "OK"


# =============================================================================
# Full Coherence Validation
# =============================================================================

@dataclass
class CoherenceValidationResult:
    """Results of coherence validation for a single scenario."""
    scenario_id: str
    is_coherent: bool
    
    # Individual checks
    keyword_coherent: bool
    keyword_reason: str
    
    regression_coherent: bool
    regression_zscore: float
    regression_reason: str
    
    lob_coherent: bool
    lob_reason: str


def validate_coherence(scenarios: List[SyntheticScenario],
                       historical_texts: List[str] = None,
                       historical_severities: np.ndarray = None,
                       config: ValidationConfig = None) -> Tuple[List[CoherenceValidationResult], Dict]:
    """
    Run full coherence validation suite.
    
    Args:
        scenarios: Scenarios to validate
        historical_texts: Historical narratives for training regression validator
        historical_severities: Historical severity ratios
        config: Validation configuration
    
    Returns:
        (list of per-scenario results, summary statistics)
    """
    config = config or DEFAULT_VALIDATION_CONFIG
    
    logger.info(f"Validating coherence of {len(scenarios)} scenarios...")
    
    # Train regression validator if historical data provided
    regression_validator = None
    if historical_texts is not None and historical_severities is not None:
        regression_validator = RegressionValidator(config.coherence_zscore_threshold)
        regression_validator.fit(historical_texts, historical_severities)
    
    # Compute severity percentiles for keyword checking
    severities = np.array([s.severity_ratio for s in scenarios])
    percentiles = {s.id: 100 * np.mean(severities <= s.severity_ratio) for s in scenarios}
    
    # Validate each scenario
    results = []
    
    for scenario in scenarios:
        # Keyword check
        kw_coherent, kw_reason = check_keyword_coherence(
            scenario, percentiles[scenario.id]
        )
        
        # Regression check
        if regression_validator:
            reg_coherent, reg_zscore, reg_reason = regression_validator.check_coherence(scenario)
        else:
            reg_coherent, reg_zscore, reg_reason = True, 0.0, "Skipped"
        
        # LOB consistency check
        lob_coherent, lob_reason = check_complexity_lob_consistency(scenario)
        
        # Overall coherence
        is_coherent = kw_coherent and reg_coherent and lob_coherent
        
        results.append(CoherenceValidationResult(
            scenario_id=scenario.id,
            is_coherent=is_coherent,
            keyword_coherent=kw_coherent,
            keyword_reason=kw_reason,
            regression_coherent=reg_coherent,
            regression_zscore=reg_zscore,
            regression_reason=reg_reason,
            lob_coherent=lob_coherent,
            lob_reason=lob_reason
        ))
        
        # Update scenario coherence score
        scenario.coherence_score = 1.0 if is_coherent else 0.0
    
    # Summary statistics
    n_coherent = sum(1 for r in results if r.is_coherent)
    n_kw_fail = sum(1 for r in results if not r.keyword_coherent)
    n_reg_fail = sum(1 for r in results if not r.regression_coherent)
    n_lob_fail = sum(1 for r in results if not r.lob_coherent)
    
    summary = {
        'total_scenarios': len(scenarios),
        'coherent_count': n_coherent,
        'coherence_rate': n_coherent / len(scenarios),
        'keyword_failures': n_kw_fail,
        'regression_failures': n_reg_fail,
        'lob_failures': n_lob_fail
    }
    
    logger.info(f"Coherence validation complete:")
    logger.info(f"  Coherent: {n_coherent}/{len(scenarios)} ({summary['coherence_rate']:.1%})")
    logger.info(f"  Keyword failures: {n_kw_fail}")
    logger.info(f"  Regression failures: {n_reg_fail}")
    logger.info(f"  LOB failures: {n_lob_fail}")
    
    return results, summary


def filter_incoherent(scenarios: List[SyntheticScenario],
                      results: List[CoherenceValidationResult],
                      mode: str = 'remove') -> List[SyntheticScenario]:
    """
    Filter out or flag incoherent scenarios.
    
    Args:
        scenarios: Original scenarios
        results: Coherence validation results
        mode: 'remove' to filter out, 'flag' to mark
    
    Returns:
        Filtered/flagged scenarios
    """
    result_map = {r.scenario_id: r for r in results}
    
    if mode == 'remove':
        return [s for s in scenarios if result_map[s.id].is_coherent]
    elif mode == 'flag':
        for s in scenarios:
            if not result_map[s.id].is_coherent:
                s.is_edge_case = True
        return scenarios
    else:
        return scenarios


# =============================================================================
# CLI
# =============================================================================

if __name__ == "__main__":
    import argparse
    import json
    
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    
    parser = argparse.ArgumentParser(description="Validate coherence of synthetic scenarios")
    parser.add_argument('--scenarios', '-s', required=True,
                        help='Path to synthetic scenarios JSON')
    parser.add_argument('--historical', '-h',
                        help='Path to historical data JSON (for regression validator)')
    parser.add_argument('--output', '-o', default='results/stress_test/coherence_validation.json',
                        help='Output path')
    
    args = parser.parse_args()
    
    # Load scenarios
    with open(args.scenarios, 'r') as f:
        scenarios_data = json.load(f)
    scenarios = [SyntheticScenario(**s) for s in scenarios_data['scenarios']]
    
    # Load historical data if provided
    historical_texts = None
    historical_severities = None
    if args.historical:
        with open(args.historical, 'r') as f:
            hist_data = json.load(f)
        historical_texts = [m['narrative'] or '' for m in hist_data['movements']]
        historical_severities = np.array([m['severity_ratio'] for m in hist_data['movements']])
    
    # Validate
    results, summary = validate_coherence(
        scenarios, historical_texts, historical_severities
    )
    
    # Print failures
    print("\n=== Incoherent Scenarios ===")
    for r in results:
        if not r.is_coherent:
            print(f"\n{r.scenario_id}:")
            if not r.keyword_coherent:
                print(f"  Keyword: {r.keyword_reason}")
            if not r.regression_coherent:
                print(f"  Regression: {r.regression_reason} (Z={r.regression_zscore:.2f})")
            if not r.lob_coherent:
                print(f"  LOB: {r.lob_reason}")
    
    # Save results
    output_data = {
        'summary': summary,
        'results': [vars(r) for r in results]
    }
    
    with open(args.output, 'w') as f:
        json.dump(output_data, f, indent=2)
    
    print(f"\nSaved results to {args.output}")
