"""
Filtering Diagnostics Module

Analyzes data filtering pipeline to:
1. Identify where data points are lost
2. Test for systematic bias in filtering
3. Provide options for using more data with appropriate warnings

This is critical for academic rigor - we must understand if filtering
introduces bias into the final dataset.
"""

import json
import logging
from collections import defaultdict
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
import numpy as np
from scipy import stats

logger = logging.getLogger(__name__)


@dataclass
class FilteringStage:
    """Statistics for a single filtering stage."""
    stage_name: str
    input_count: int
    output_count: int
    dropped_count: int
    drop_rate: float
    reasons: Dict[str, int]  # reason -> count


@dataclass
class BiasTestResult:
    """Result of a bias test."""
    test_name: str
    dimension: str
    statistic: float
    p_value: float
    interpretation: str
    significant: bool  # p < 0.05
    details: Dict[str, Any]


@dataclass
class FilteringReport:
    """Complete filtering diagnostics report."""
    corpus_path: str
    total_movements: int
    final_count: int
    overall_retention_rate: float

    # Stage-by-stage breakdown
    stages: List[FilteringStage]

    # Bias tests
    bias_tests: List[BiasTestResult]
    overall_bias_assessment: str

    # Data recovery options
    recovery_options: List[Dict[str, Any]]

    def to_dict(self) -> Dict:
        return {
            'corpus_path': self.corpus_path,
            'total_movements': self.total_movements,
            'final_count': self.final_count,
            'overall_retention_rate': self.overall_retention_rate,
            'stages': [asdict(s) for s in self.stages],
            'bias_tests': [asdict(t) for t in self.bias_tests],
            'overall_bias_assessment': self.overall_bias_assessment,
            'recovery_options': self.recovery_options
        }


class FilteringDiagnostics:
    """Analyze filtering pipeline for bias and data loss."""

    def __init__(self, corpus_path: str):
        self.corpus_path = corpus_path
        self.movements: List[Dict] = []
        self.stages: List[FilteringStage] = []
        self.bias_tests: List[BiasTestResult] = []

    def load_corpus(self) -> 'FilteringDiagnostics':
        """Load corpus data."""
        with open(self.corpus_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self.movements = data.get('movements', [])
        logger.info(f"Loaded {len(self.movements)} movements from corpus")
        return self

    def analyze_filtering_pipeline(self,
                                   direction_filter: str = 'strengthening') -> 'FilteringDiagnostics':
        """
        Analyze each stage of the filtering pipeline.

        Mirrors the logic in data_preparation.py to show where data is lost.
        """
        movements = self.movements

        # Stage 1: Direction filter
        if direction_filter != 'all':
            direction_counts = defaultdict(int)
            for m in movements:
                direction_counts[m.get('direction', 'unknown')] += 1

            filtered = [m for m in movements if m.get('direction') == direction_filter]

            self.stages.append(FilteringStage(
                stage_name='direction_filter',
                input_count=len(movements),
                output_count=len(filtered),
                dropped_count=len(movements) - len(filtered),
                drop_rate=(len(movements) - len(filtered)) / len(movements) if movements else 0,
                reasons={f"direction={k}": v for k, v in direction_counts.items()
                        if k != direction_filter}
            ))
            movements = filtered

        # Stage 2: Severity data availability
        severity_reasons = defaultdict(int)
        movements_with_severity = []

        for m in movements:
            has_sev = m.get('severity_ratio') is not None
            has_amount = m.get('amount_gbp_m') is not None and m.get('amount_gbp_m') != 0
            has_reserves = m.get('prior_reserves_gbp_m') is not None and m.get('prior_reserves_gbp_m') > 0

            if has_sev:
                movements_with_severity.append(m)
            elif has_amount and has_reserves:
                movements_with_severity.append(m)
            else:
                # Categorize why it was dropped
                if not has_amount and not has_reserves:
                    severity_reasons['missing_both_amount_and_reserves'] += 1
                elif not has_amount:
                    severity_reasons['missing_amount_gbp_m'] += 1
                elif not has_reserves:
                    severity_reasons['missing_prior_reserves_gbp_m'] += 1
                elif m.get('prior_reserves_gbp_m', 0) <= 0:
                    severity_reasons['zero_or_negative_reserves'] += 1
                else:
                    severity_reasons['unknown_severity_issue'] += 1

        self.stages.append(FilteringStage(
            stage_name='severity_data_filter',
            input_count=len(movements),
            output_count=len(movements_with_severity),
            dropped_count=len(movements) - len(movements_with_severity),
            drop_rate=(len(movements) - len(movements_with_severity)) / len(movements) if movements else 0,
            reasons=dict(severity_reasons)
        ))
        movements = movements_with_severity

        # Stage 3: Syndicate/Year validity
        profile_reasons = defaultdict(int)
        valid_movements = []

        for m in movements:
            syn = m.get('syndicate')
            year = m.get('year')

            if not syn:
                profile_reasons['missing_syndicate'] += 1
            elif not year:
                profile_reasons['missing_year'] += 1
            else:
                valid_movements.append(m)

        if profile_reasons:
            self.stages.append(FilteringStage(
                stage_name='syndicate_year_filter',
                input_count=len(movements),
                output_count=len(valid_movements),
                dropped_count=len(movements) - len(valid_movements),
                drop_rate=(len(movements) - len(valid_movements)) / len(movements) if movements else 0,
                reasons=dict(profile_reasons)
            ))

        return self

    def test_for_bias(self) -> 'FilteringDiagnostics':
        """
        Run statistical tests to detect bias in filtering.

        Tests whether filtered-out data differs systematically from retained data
        across key dimensions (year, LOB, syndicate size).
        """
        # Get retained vs dropped movements
        retained = self._get_retained_movements()
        dropped = self._get_dropped_movements()

        if not retained or not dropped:
            logger.warning("Cannot test for bias: insufficient data in one group")
            return self

        # Test 1: Year distribution bias
        self._test_year_bias(retained, dropped)

        # Test 2: LOB distribution bias
        self._test_lob_bias(retained, dropped)

        # Test 3: Amount size bias (if larger movements more likely to have data)
        self._test_amount_bias(retained, dropped)

        # Test 4: Syndicate concentration bias
        self._test_syndicate_concentration(retained, dropped)

        return self

    def _get_retained_movements(self) -> List[Dict]:
        """Get movements that pass all filters."""
        movements = self.movements

        # Apply filters
        movements = [m for m in movements if m.get('direction') == 'strengthening']
        movements = [m for m in movements if
                    m.get('severity_ratio') is not None or
                    (m.get('amount_gbp_m') and m.get('prior_reserves_gbp_m', 0) > 0)]
        movements = [m for m in movements if m.get('syndicate') and m.get('year')]

        return movements

    def _get_dropped_movements(self) -> List[Dict]:
        """Get strengthening movements that were dropped."""
        all_strengthening = [m for m in self.movements
                           if m.get('direction') == 'strengthening']
        retained_ids = {m.get('id') for m in self._get_retained_movements()}

        return [m for m in all_strengthening if m.get('id') not in retained_ids]

    def _test_year_bias(self, retained: List[Dict], dropped: List[Dict]):
        """Test if filtering creates bias by year."""
        retained_years = [m.get('year') for m in retained if m.get('year')]
        dropped_years = [m.get('year') for m in dropped if m.get('year')]

        if not retained_years or not dropped_years:
            return

        # Chi-square test on year distribution
        all_years = sorted(set(retained_years + dropped_years))

        retained_counts = {y: retained_years.count(y) for y in all_years}
        dropped_counts = {y: dropped_years.count(y) for y in all_years}

        # Compute expected counts under null hypothesis (no bias)
        total_retained = len(retained_years)
        total_dropped = len(dropped_years)
        total = total_retained + total_dropped

        observed_retained = [retained_counts.get(y, 0) for y in all_years]
        observed_dropped = [dropped_counts.get(y, 0) for y in all_years]

        # Chi-square test
        observed = np.array([observed_retained, observed_dropped])
        try:
            chi2, p_value, dof, expected = stats.chi2_contingency(observed)

            # Identify which years are over/under-represented
            over_represented = []
            under_represented = []

            for i, year in enumerate(all_years):
                if observed_retained[i] > 0 and expected[0][i] > 0:
                    ratio = observed_retained[i] / expected[0][i]
                    if ratio > 1.5:
                        over_represented.append((year, ratio))
                    elif ratio < 0.67:
                        under_represented.append((year, ratio))

            self.bias_tests.append(BiasTestResult(
                test_name='chi_square_year',
                dimension='year',
                statistic=float(chi2),
                p_value=float(p_value),
                interpretation=f"Tests whether year distribution differs between retained and dropped. "
                              f"Over-represented years: {over_represented[:3]}. "
                              f"Under-represented years: {under_represented[:3]}",
                significant=p_value < 0.05,
                details={
                    'degrees_of_freedom': int(dof),
                    'n_years': len(all_years),
                    'over_represented': over_represented,
                    'under_represented': under_represented
                }
            ))
        except Exception as e:
            logger.warning(f"Year bias test failed: {e}")

    def _test_lob_bias(self, retained: List[Dict], dropped: List[Dict]):
        """Test if filtering creates bias by line of business."""
        retained_lobs = [m.get('line_of_business', 'Unknown') for m in retained]
        dropped_lobs = [m.get('line_of_business', 'Unknown') for m in dropped]

        if not retained_lobs or not dropped_lobs:
            return

        # Get all LOBs
        all_lobs = sorted(set(retained_lobs + dropped_lobs))

        retained_counts = {l: retained_lobs.count(l) for l in all_lobs}
        dropped_counts = {l: dropped_lobs.count(l) for l in all_lobs}

        observed = np.array([
            [retained_counts.get(l, 0) for l in all_lobs],
            [dropped_counts.get(l, 0) for l in all_lobs]
        ])

        # Remove columns with all zeros
        col_sums = observed.sum(axis=0)
        valid_cols = col_sums > 0
        observed = observed[:, valid_cols]
        valid_lobs = [l for l, v in zip(all_lobs, valid_cols) if v]

        try:
            chi2, p_value, dof, expected = stats.chi2_contingency(observed)

            # Identify bias
            lob_bias = {}
            for i, lob in enumerate(valid_lobs):
                if expected[0][i] > 0:
                    ratio = observed[0][i] / expected[0][i]
                    if abs(ratio - 1.0) > 0.3:
                        lob_bias[lob] = float(ratio)

            self.bias_tests.append(BiasTestResult(
                test_name='chi_square_lob',
                dimension='line_of_business',
                statistic=float(chi2),
                p_value=float(p_value),
                interpretation=f"Tests whether LOB distribution differs between retained and dropped. "
                              f"Biased LOBs (ratio != 1): {lob_bias}",
                significant=p_value < 0.05,
                details={
                    'degrees_of_freedom': int(dof),
                    'n_lobs': len(valid_lobs),
                    'lob_bias_ratios': lob_bias
                }
            ))
        except Exception as e:
            logger.warning(f"LOB bias test failed: {e}")

    def _test_amount_bias(self, retained: List[Dict], dropped: List[Dict]):
        """Test if larger movements are more likely to be retained."""
        retained_amounts = [abs(m.get('amount_gbp_m', 0)) for m in retained
                          if m.get('amount_gbp_m') is not None]
        dropped_amounts = [abs(m.get('amount_gbp_m', 0)) for m in dropped
                         if m.get('amount_gbp_m') is not None]

        if len(retained_amounts) < 5 or len(dropped_amounts) < 5:
            return

        # Mann-Whitney U test (non-parametric comparison of distributions)
        try:
            statistic, p_value = stats.mannwhitneyu(
                retained_amounts, dropped_amounts, alternative='two-sided'
            )

            retained_median = float(np.median(retained_amounts))
            dropped_median = float(np.median(dropped_amounts))

            self.bias_tests.append(BiasTestResult(
                test_name='mann_whitney_amount',
                dimension='amount_gbp_m',
                statistic=float(statistic),
                p_value=float(p_value),
                interpretation=f"Tests whether retained movements have different amounts than dropped. "
                              f"Retained median: £{retained_median:.1f}m, "
                              f"Dropped median: £{dropped_median:.1f}m",
                significant=p_value < 0.05,
                details={
                    'retained_median': retained_median,
                    'dropped_median': dropped_median,
                    'retained_mean': float(np.mean(retained_amounts)),
                    'dropped_mean': float(np.mean(dropped_amounts)),
                    'n_retained': len(retained_amounts),
                    'n_dropped': len(dropped_amounts)
                }
            ))
        except Exception as e:
            logger.warning(f"Amount bias test failed: {e}")

    def _test_syndicate_concentration(self, retained: List[Dict], dropped: List[Dict]):
        """Test if filtering concentrates data in fewer syndicates."""
        retained_synd = [str(m.get('syndicate')) for m in retained if m.get('syndicate')]
        dropped_synd = [str(m.get('syndicate')) for m in dropped if m.get('syndicate')]

        if not retained_synd or not dropped_synd:
            return

        # Compute HHI (Herfindahl-Hirschman Index) for concentration
        def compute_hhi(items):
            counts = defaultdict(int)
            for item in items:
                counts[item] += 1
            total = len(items)
            return sum((c/total)**2 for c in counts.values())

        retained_hhi = compute_hhi(retained_synd)
        all_strengthening_synd = [str(m.get('syndicate')) for m in self.movements
                                  if m.get('direction') == 'strengthening' and m.get('syndicate')]
        original_hhi = compute_hhi(all_strengthening_synd) if all_strengthening_synd else 0

        # Higher HHI = more concentrated
        concentration_increase = retained_hhi / original_hhi if original_hhi > 0 else 1.0

        n_syndicates_retained = len(set(retained_synd))
        n_syndicates_original = len(set(all_strengthening_synd))

        self.bias_tests.append(BiasTestResult(
            test_name='syndicate_concentration',
            dimension='syndicate',
            statistic=float(concentration_increase),
            p_value=float('nan'),  # Not a statistical test
            interpretation=f"Measures if filtering concentrates data in fewer syndicates. "
                          f"HHI increased by {(concentration_increase-1)*100:.1f}% "
                          f"(from {n_syndicates_original} to {n_syndicates_retained} syndicates)",
            significant=concentration_increase > 1.2,  # >20% increase is concerning
            details={
                'original_hhi': float(original_hhi),
                'retained_hhi': float(retained_hhi),
                'concentration_ratio': float(concentration_increase),
                'n_syndicates_original': n_syndicates_original,
                'n_syndicates_retained': n_syndicates_retained
            }
        ))

    def suggest_recovery_options(self) -> List[Dict[str, Any]]:
        """
        Suggest options for recovering more data with appropriate warnings.
        """
        options = []

        # Option 1: Extract size metrics from PDFs
        dropped_for_reserves = sum(
            s.reasons.get('missing_prior_reserves_gbp_m', 0) +
            s.reasons.get('missing_both_amount_and_reserves', 0)
            for s in self.stages if s.stage_name == 'severity_data_filter'
        )

        if dropped_for_reserves > 0:
            options.append({
                'option': 'extract_size_metrics',
                'potential_recovery': dropped_for_reserves,
                'description': 'Extract reserve data from syndicate annual reports',
                'command': 'python extract_size_metrics.py --pdfs lloyds_data/pdfs --output results/stress_test/size_metrics.json',
                'risk': 'LOW - Uses actual reported data',
                'academic_acceptable': True
            })

        # Option 2: Estimate reserves (with warning)
        dropped_no_reserves = sum(
            s.reasons.get('missing_prior_reserves_gbp_m', 0)
            for s in self.stages if s.stage_name == 'severity_data_filter'
        )

        if dropped_no_reserves > 0:
            options.append({
                'option': 'estimate_reserves',
                'potential_recovery': dropped_no_reserves,
                'description': 'Estimate reserves using industry ratios (movement is approx 5-15% of reserves)',
                'command': 'Use --allow-estimated-severity flag',
                'risk': 'MEDIUM - Introduces estimation error',
                'academic_acceptable': 'CONDITIONAL - Must document estimation method and run sensitivity analysis',
                'sensitivity_required': True
            })

        # Option 3: Include releases
        release_count = sum(1 for m in self.movements if m.get('direction') == 'release')
        if release_count > 0:
            options.append({
                'option': 'include_releases',
                'potential_recovery': release_count,
                'description': 'Include release movements (negative severity) in analysis',
                'command': 'Use --direction all',
                'risk': 'LOW - Uses actual data but changes analysis scope',
                'academic_acceptable': True,
                'note': 'Releases represent different risk dynamics than strengthenings'
            })

        # Option 4: Market-level data augmentation
        market_count = sum(1 for m in self.movements if m.get('source_type') == 'market')
        if market_count > 0:
            options.append({
                'option': 'include_market_level',
                'potential_recovery': market_count,
                'description': 'Include aggregate market-level movements',
                'risk': 'LOW - Less granular but actual reported data',
                'academic_acceptable': True
            })

        return options

    def generate_report(self) -> FilteringReport:
        """Generate complete filtering diagnostics report."""
        # Analyze pipeline
        self.analyze_filtering_pipeline()

        # Test for bias
        self.test_for_bias()

        # Get recovery options
        recovery = self.suggest_recovery_options()

        # Compute final count
        retained = self._get_retained_movements()

        # Overall bias assessment
        significant_bias = [t for t in self.bias_tests if t.significant]
        if not significant_bias:
            assessment = "GOOD: No statistically significant bias detected in filtering"
        elif len(significant_bias) == 1:
            assessment = f"CAUTION: Bias detected in {significant_bias[0].dimension}. Review details."
        else:
            dims = [t.dimension for t in significant_bias]
            assessment = f"WARNING: Multiple biases detected ({', '.join(dims)}). " \
                        f"Results may not generalize. Consider recovery options."

        return FilteringReport(
            corpus_path=self.corpus_path,
            total_movements=len(self.movements),
            final_count=len(retained),
            overall_retention_rate=len(retained) / len(self.movements) if self.movements else 0,
            stages=self.stages,
            bias_tests=self.bias_tests,
            overall_bias_assessment=assessment,
            recovery_options=recovery
        )


def run_filtering_diagnostics(corpus_path: str, output_path: Optional[str] = None) -> FilteringReport:
    """
    Run complete filtering diagnostics on a corpus.

    Args:
        corpus_path: Path to unified_corpus.json
        output_path: Optional path to save report JSON

    Returns:
        FilteringReport with full diagnostics
    """
    diag = FilteringDiagnostics(corpus_path)
    diag.load_corpus()
    report = diag.generate_report()

    # Print summary
    print("\n" + "=" * 70)
    print("FILTERING DIAGNOSTICS REPORT")
    print("=" * 70)
    print(f"\nCorpus: {corpus_path}")
    print(f"Total movements: {report.total_movements}")
    print(f"After filtering: {report.final_count}")
    print(f"Retention rate: {report.overall_retention_rate:.1%}")

    print("\n--- FILTERING STAGES ---")
    for stage in report.stages:
        print(f"\n{stage.stage_name}:")
        print(f"  Input: {stage.input_count} -> Output: {stage.output_count}")
        print(f"  Dropped: {stage.dropped_count} ({stage.drop_rate:.1%})")
        if stage.reasons:
            print("  Reasons:")
            for reason, count in sorted(stage.reasons.items(), key=lambda x: -x[1]):
                print(f"    - {reason}: {count}")

    print("\n--- BIAS TESTS ---")
    for test in report.bias_tests:
        sig_marker = "[!] " if test.significant else "[OK] "
        print(f"\n{sig_marker}{test.test_name} ({test.dimension}):")
        print(f"  Statistic: {test.statistic:.4f}, p-value: {test.p_value:.4f}")
        print(f"  {test.interpretation}")

    print(f"\n--- OVERALL ASSESSMENT ---")
    print(f"  {report.overall_bias_assessment}")

    print("\n--- DATA RECOVERY OPTIONS ---")
    for opt in report.recovery_options:
        print(f"\n  {opt['option']} (potential: +{opt['potential_recovery']} movements)")
        print(f"    {opt['description']}")
        print(f"    Risk: {opt['risk']}")
        print(f"    Academic acceptable: {opt.get('academic_acceptable', 'Unknown')}")

    print("\n" + "=" * 70)

    # Save if requested
    if output_path:
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(report.to_dict(), f, indent=2, default=str)
        print(f"\nReport saved to: {output_path}")

    return report


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s')

    parser = argparse.ArgumentParser(description="Analyze filtering pipeline for bias")
    parser.add_argument('--corpus', '-c', default='results/combined/unified_corpus.json',
                       help='Path to unified corpus')
    parser.add_argument('--output', '-o', help='Output path for JSON report')

    args = parser.parse_args()

    run_filtering_diagnostics(args.corpus, args.output)
