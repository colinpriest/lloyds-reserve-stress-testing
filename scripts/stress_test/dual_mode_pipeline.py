#!/usr/bin/env python3
"""
Dual-Mode Pipeline for Academic Rigor
======================================

Runs data preparation in both STRICT and ESTIMATED modes in parallel,
producing detailed comparison diagnostics for academic papers.

This ensures:
1. Strict mode results can be used as primary findings
2. Estimated mode provides sensitivity analysis
3. Statistical tests compare distributions between modes
4. Full transparency for academic reviewers

Usage:
    python dual_mode_pipeline.py --corpus results/combined/unified_corpus.json
    python dual_mode_pipeline.py --corpus results/combined/unified_corpus.json --output-dir results/stress_test
"""

import sys
from pathlib import Path
_script_dir = Path(__file__).resolve().parent
if str(_script_dir) not in sys.path:
    sys.path.insert(0, str(_script_dir))

import json
import logging
import argparse
from datetime import datetime
from dataclasses import dataclass, asdict, field
from typing import List, Dict, Optional, Tuple, Any
from concurrent.futures import ThreadPoolExecutor, as_completed
import statistics

# Statistical tests
from scipy import stats
import numpy as np

from data_preparation import (
    prepare_historical_data, PreparationDiagnostics, SeverityMode,
    analyze_coverage
)
from filtering_diagnostics import FilteringDiagnostics

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@dataclass
class ModeResult:
    """Result from running one mode."""
    mode: str
    movements: List[Dict]
    diagnostics: PreparationDiagnostics
    severity_values: List[float]
    coverage: Dict[str, Dict]
    output_path: str


@dataclass
class ComparisonTest:
    """Result of comparing two modes."""
    test_name: str
    description: str
    strict_value: Any
    estimated_value: Any
    difference: Any
    p_value: Optional[float]
    is_significant: bool
    interpretation: str


@dataclass
class DualModeReport:
    """Complete report comparing strict and estimated modes."""
    generated_at: str
    corpus_path: str

    # Mode results
    strict_count: int
    estimated_count: int
    recovery_count: int
    recovery_percentage: float

    # Severity distribution comparison
    strict_severity_stats: Dict[str, float]
    estimated_severity_stats: Dict[str, float]

    # Coverage comparison
    strict_coverage: Dict
    estimated_coverage: Dict

    # Statistical tests
    comparison_tests: List[ComparisonTest]

    # Recommendations
    recommendations: List[str]

    def to_dict(self) -> Dict:
        d = asdict(self)
        d['comparison_tests'] = [asdict(t) for t in self.comparison_tests]
        return d


def run_mode(
    corpus_path: str,
    output_path: str,
    mode: str,
    direction: str = 'strengthening'
) -> ModeResult:
    """Run data preparation in a specific mode."""
    logger.info(f"Running {mode} mode...")

    movements, diagnostics = prepare_historical_data(
        corpus_path,
        output_path,
        direction,
        severity_mode=mode,
        return_diagnostics=True
    )

    severity_values = [
        m.severity_ratio for m in movements
        if m.severity_ratio is not None and m.severity_ratio > 0
    ]

    coverage = analyze_coverage(movements)

    return ModeResult(
        mode=mode,
        movements=[m.__dict__ if hasattr(m, '__dict__') else m for m in movements],
        diagnostics=diagnostics,
        severity_values=severity_values,
        coverage=coverage,
        output_path=output_path
    )


def compute_severity_stats(values: List[float]) -> Dict[str, float]:
    """Compute descriptive statistics for severity values."""
    if not values:
        return {
            'count': 0, 'mean': 0, 'median': 0, 'std': 0,
            'min': 0, 'max': 0, 'p25': 0, 'p75': 0, 'p95': 0
        }

    values = sorted(values)
    n = len(values)

    return {
        'count': n,
        'mean': statistics.mean(values),
        'median': statistics.median(values),
        'std': statistics.stdev(values) if n > 1 else 0,
        'min': min(values),
        'max': max(values),
        'p25': values[int(n * 0.25)] if n >= 4 else values[0],
        'p75': values[int(n * 0.75)] if n >= 4 else values[-1],
        'p95': values[int(n * 0.95)] if n >= 20 else values[-1],
    }


def compare_modes(
    strict_result: ModeResult,
    estimated_result: ModeResult
) -> List[ComparisonTest]:
    """Run statistical tests comparing the two modes."""
    tests = []

    # Test 1: Sample size comparison
    strict_n = len(strict_result.movements)
    estimated_n = len(estimated_result.movements)
    recovery = estimated_n - strict_n
    recovery_pct = (recovery / strict_n * 100) if strict_n > 0 else 0

    tests.append(ComparisonTest(
        test_name='sample_size',
        description='Compares sample sizes between modes',
        strict_value=strict_n,
        estimated_value=estimated_n,
        difference=recovery,
        p_value=None,
        is_significant=recovery > 0,
        interpretation=f"Estimated mode recovers {recovery} additional movements ({recovery_pct:.1f}% increase)"
    ))

    # Test 2: Mann-Whitney U test for severity distributions
    if strict_result.severity_values and estimated_result.severity_values:
        # Only compare the overlapping movements vs new ones
        # Get severities of movements that are in estimated but not strict
        strict_ids = set()
        for m in strict_result.movements:
            if isinstance(m, dict):
                key = (m.get('syndicate'), m.get('year'), m.get('lob'))
            else:
                key = (m.syndicate, m.year, m.lob)
            strict_ids.add(key)

        new_movements_severities = []
        for m in estimated_result.movements:
            if isinstance(m, dict):
                key = (m.get('syndicate'), m.get('year'), m.get('lob'))
                sev = m.get('severity_ratio')
            else:
                key = (m.syndicate, m.year, m.lob)
                sev = m.severity_ratio

            if key not in strict_ids and sev is not None and sev > 0:
                new_movements_severities.append(sev)

        if new_movements_severities and len(new_movements_severities) >= 5:
            stat, p_value = stats.mannwhitneyu(
                strict_result.severity_values,
                new_movements_severities,
                alternative='two-sided'
            )

            strict_median = statistics.median(strict_result.severity_values)
            new_median = statistics.median(new_movements_severities)

            tests.append(ComparisonTest(
                test_name='mann_whitney_severity',
                description='Tests if recovered movements have different severity distribution',
                strict_value=f"median={strict_median:.3f}",
                estimated_value=f"median={new_median:.3f} (new movements)",
                difference=f"{new_median - strict_median:.3f}",
                p_value=float(p_value),
                is_significant=p_value < 0.05,
                interpretation=(
                    f"Recovered movements have {'significantly different' if p_value < 0.05 else 'similar'} "
                    f"severity distribution (p={p_value:.4f}). New median: {new_median:.3f} vs strict median: {strict_median:.3f}"
                )
            ))

    # Test 3: Kolmogorov-Smirnov test for full distributions
    if len(strict_result.severity_values) >= 10 and len(estimated_result.severity_values) >= 10:
        stat, p_value = stats.ks_2samp(
            strict_result.severity_values,
            estimated_result.severity_values
        )

        tests.append(ComparisonTest(
            test_name='ks_distribution',
            description='Kolmogorov-Smirnov test comparing full severity distributions',
            strict_value=f"n={len(strict_result.severity_values)}",
            estimated_value=f"n={len(estimated_result.severity_values)}",
            difference=f"D={stat:.4f}",
            p_value=float(p_value),
            is_significant=p_value < 0.05,
            interpretation=(
                f"Distributions are {'significantly different' if p_value < 0.05 else 'statistically similar'} "
                f"(KS statistic={stat:.4f}, p={p_value:.4f})"
            )
        ))

    # Test 4: Year coverage comparison
    strict_years = set(strict_result.coverage.get('by_year', {}).keys())
    estimated_years = set(estimated_result.coverage.get('by_year', {}).keys())
    new_years = estimated_years - strict_years

    tests.append(ComparisonTest(
        test_name='year_coverage',
        description='Compares year coverage between modes',
        strict_value=f"{len(strict_years)} years",
        estimated_value=f"{len(estimated_years)} years",
        difference=f"+{len(new_years)} new years" if new_years else "No new years",
        p_value=None,
        is_significant=len(new_years) > 0,
        interpretation=f"Estimated mode covers years: {sorted(estimated_years)}. New years: {sorted(new_years) if new_years else 'None'}"
    ))

    # Test 5: LOB coverage comparison
    strict_lobs = set(strict_result.coverage.get('by_lob', {}).keys())
    estimated_lobs = set(estimated_result.coverage.get('by_lob', {}).keys())
    new_lobs = estimated_lobs - strict_lobs

    tests.append(ComparisonTest(
        test_name='lob_coverage',
        description='Compares LOB coverage between modes',
        strict_value=f"{len(strict_lobs)} LOBs",
        estimated_value=f"{len(estimated_lobs)} LOBs",
        difference=f"+{len(new_lobs)} new LOBs" if new_lobs else "No new LOBs",
        p_value=None,
        is_significant=len(new_lobs) > 0,
        interpretation=f"New LOBs in estimated mode: {list(new_lobs) if new_lobs else 'None'}"
    ))

    # Test 6: Syndicate diversity comparison
    strict_synd = strict_result.diagnostics.unique_syndicates
    estimated_synd = estimated_result.diagnostics.unique_syndicates

    tests.append(ComparisonTest(
        test_name='syndicate_diversity',
        description='Compares syndicate diversity between modes',
        strict_value=f"{strict_synd} syndicates",
        estimated_value=f"{estimated_synd} syndicates",
        difference=f"+{estimated_synd - strict_synd}",
        p_value=None,
        is_significant=estimated_synd > strict_synd,
        interpretation=f"Estimated mode includes {estimated_synd - strict_synd} additional syndicates"
    ))

    return tests


def generate_recommendations(
    strict_result: ModeResult,
    estimated_result: ModeResult,
    tests: List[ComparisonTest]
) -> List[str]:
    """Generate academic recommendations based on comparison."""
    recommendations = []

    strict_n = len(strict_result.movements)
    estimated_n = len(estimated_result.movements)
    recovery_pct = ((estimated_n - strict_n) / strict_n * 100) if strict_n > 0 else 0

    # Check severity distribution test
    ks_test = next((t for t in tests if t.test_name == 'ks_distribution'), None)
    mw_test = next((t for t in tests if t.test_name == 'mann_whitney_severity'), None)

    # Recommendation 1: Primary vs sensitivity analysis
    if recovery_pct > 20:
        recommendations.append(
            f"SIGNIFICANT RECOVERY: Estimated mode recovers {recovery_pct:.0f}% more data. "
            "Consider using strict mode for primary results and estimated mode for robustness checks."
        )
    elif recovery_pct > 10:
        recommendations.append(
            f"MODERATE RECOVERY: Estimated mode recovers {recovery_pct:.0f}% more data. "
            "Report both analyses for completeness."
        )
    else:
        recommendations.append(
            f"LIMITED RECOVERY: Estimated mode only recovers {recovery_pct:.0f}% more data. "
            "Strict mode results are likely sufficient."
        )

    # Recommendation 2: Distribution similarity
    if ks_test and not ks_test.is_significant:
        recommendations.append(
            "DISTRIBUTIONS SIMILAR: The K-S test shows no significant difference between "
            "strict and estimated severity distributions. Results are likely robust."
        )
    elif ks_test and ks_test.is_significant:
        recommendations.append(
            "DISTRIBUTIONS DIFFER: The K-S test shows significant differences. "
            "Document this in the methodology and interpret estimated results cautiously."
        )

    # Recommendation 3: New movement characteristics
    if mw_test:
        if mw_test.is_significant:
            recommendations.append(
                f"RECOVERED MOVEMENTS DIFFER: New movements in estimated mode have "
                f"significantly different severity profiles. Document the estimation method thoroughly."
            )
        else:
            recommendations.append(
                "RECOVERED MOVEMENTS SIMILAR: New movements have similar severity profiles "
                "to the strict sample. Estimated mode results are likely reliable."
            )

    # Recommendation 4: Academic disclosure
    recommendations.append(
        "ACADEMIC DISCLOSURE: For academic papers, report:\n"
        f"  - Primary analysis: Strict mode (n={strict_n})\n"
        f"  - Sensitivity analysis: Estimated mode (n={estimated_n})\n"
        "  - All statistical comparisons between modes"
    )

    # Recommendation 5: Limitation acknowledgment
    strict_retention = strict_result.diagnostics.final_count / strict_result.diagnostics.total_corpus
    if strict_retention < 0.2:
        recommendations.append(
            f"LOW RETENTION WARNING: Strict mode retains only {strict_retention:.1%} of corpus. "
            "Acknowledge potential selection bias in limitations section."
        )

    return recommendations


def run_dual_mode_pipeline(
    corpus_path: str,
    output_dir: str,
    direction: str = 'strengthening'
) -> DualModeReport:
    """
    Run complete dual-mode pipeline.

    Args:
        corpus_path: Path to unified corpus
        output_dir: Directory for output files
        direction: Movement direction filter

    Returns:
        DualModeReport with complete comparison
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    logger.info("=" * 60)
    logger.info("DUAL-MODE PIPELINE")
    logger.info("=" * 60)
    logger.info(f"Corpus: {corpus_path}")
    logger.info(f"Output: {output_dir}")
    logger.info(f"Direction: {direction}")
    logger.info("")

    # Run both modes in parallel
    logger.info("Running strict and estimated modes in parallel...")

    with ThreadPoolExecutor(max_workers=2) as executor:
        strict_future = executor.submit(
            run_mode,
            corpus_path,
            str(output_path / "prepared_data_strict.json"),
            'strict',
            direction
        )
        estimated_future = executor.submit(
            run_mode,
            corpus_path,
            str(output_path / "prepared_data_estimated.json"),
            'estimated',
            direction
        )

        strict_result = strict_future.result()
        estimated_result = estimated_future.result()

    logger.info(f"\nStrict mode: {len(strict_result.movements)} movements")
    logger.info(f"Estimated mode: {len(estimated_result.movements)} movements")

    # Compute statistics
    strict_stats = compute_severity_stats(strict_result.severity_values)
    estimated_stats = compute_severity_stats(estimated_result.severity_values)

    # Run comparison tests
    logger.info("\nRunning statistical comparisons...")
    comparison_tests = compare_modes(strict_result, estimated_result)

    # Generate recommendations
    recommendations = generate_recommendations(
        strict_result, estimated_result, comparison_tests
    )

    # Create report
    strict_n = len(strict_result.movements)
    estimated_n = len(estimated_result.movements)

    report = DualModeReport(
        generated_at=datetime.now().isoformat(),
        corpus_path=corpus_path,
        strict_count=strict_n,
        estimated_count=estimated_n,
        recovery_count=estimated_n - strict_n,
        recovery_percentage=((estimated_n - strict_n) / strict_n * 100) if strict_n > 0 else 0,
        strict_severity_stats=strict_stats,
        estimated_severity_stats=estimated_stats,
        strict_coverage=strict_result.coverage,
        estimated_coverage=estimated_result.coverage,
        comparison_tests=comparison_tests,
        recommendations=recommendations
    )

    # Save report
    report_path = output_path / "dual_mode_comparison.json"
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(report.to_dict(), f, indent=2, default=str)

    logger.info(f"\nReport saved to: {report_path}")

    # Also save the strict result as the default prepared_data.json
    # (strict is the academic default)
    import shutil
    default_path = output_path / "prepared_data.json"
    shutil.copy(strict_result.output_path, default_path)
    logger.info(f"Default prepared_data.json uses strict mode")

    return report


def print_report(report: DualModeReport):
    """Print formatted report to console."""
    print("\n" + "=" * 70)
    print("DUAL-MODE COMPARISON REPORT")
    print("=" * 70)
    print(f"Generated: {report.generated_at}")
    print(f"Corpus: {report.corpus_path}")
    print("")

    # Summary
    print("SUMMARY")
    print("-" * 40)
    print(f"Strict mode:    {report.strict_count} movements")
    print(f"Estimated mode: {report.estimated_count} movements")
    print(f"Recovery:       +{report.recovery_count} ({report.recovery_percentage:.1f}%)")
    print("")

    # Severity statistics
    print("SEVERITY STATISTICS")
    print("-" * 40)
    print(f"{'Metric':<15} {'Strict':>12} {'Estimated':>12}")
    print("-" * 40)
    for key in ['count', 'mean', 'median', 'std', 'min', 'max', 'p95']:
        s_val = report.strict_severity_stats.get(key, 0)
        e_val = report.estimated_severity_stats.get(key, 0)
        if isinstance(s_val, float):
            print(f"{key:<15} {s_val:>12.4f} {e_val:>12.4f}")
        else:
            print(f"{key:<15} {s_val:>12} {e_val:>12}")
    print("")

    # Statistical tests
    print("STATISTICAL COMPARISONS")
    print("-" * 40)
    for test in report.comparison_tests:
        sig = "[SIGNIFICANT]" if test.is_significant else "[not significant]"
        p_str = f"p={test.p_value:.4f}" if test.p_value is not None else ""
        print(f"\n{test.test_name}: {sig} {p_str}")
        print(f"  Strict: {test.strict_value}")
        print(f"  Estimated: {test.estimated_value}")
        print(f"  -> {test.interpretation}")
    print("")

    # Recommendations
    print("RECOMMENDATIONS FOR ACADEMIC USE")
    print("-" * 40)
    for i, rec in enumerate(report.recommendations, 1):
        print(f"\n{i}. {rec}")
    print("")

    print("=" * 70)
    print("END OF REPORT")
    print("=" * 70)


def main():
    parser = argparse.ArgumentParser(
        description="Run dual-mode pipeline comparing strict and estimated severity modes",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
This script runs data preparation in both strict and estimated modes,
producing detailed comparison diagnostics for academic papers.

The output includes:
  - prepared_data_strict.json: Strict mode results
  - prepared_data_estimated.json: Estimated mode results
  - prepared_data.json: Default file (copies strict mode)
  - dual_mode_comparison.json: Full comparison report

EXAMPLES:
  python dual_mode_pipeline.py -c results/combined/unified_corpus.json
  python dual_mode_pipeline.py -c results/combined/unified_corpus.json --output-dir results/stress_test
        """
    )
    parser.add_argument('--corpus', '-c', default='results/combined/unified_corpus.json',
                       help='Path to unified corpus')
    parser.add_argument('--output-dir', '-o', default='results/stress_test',
                       help='Output directory for results')
    parser.add_argument('--direction', '-d', default='strengthening',
                       choices=['strengthening', 'release', 'all'],
                       help='Movement direction filter (default: strengthening)')
    parser.add_argument('--quiet', '-q', action='store_true',
                       help='Suppress detailed output')

    args = parser.parse_args()

    report = run_dual_mode_pipeline(
        args.corpus,
        args.output_dir,
        args.direction
    )

    if not args.quiet:
        print_report(report)

    # Exit with appropriate code
    if report.recovery_count > 0:
        print(f"\n[OK] Dual-mode pipeline complete. Recovered {report.recovery_count} additional movements in estimated mode.")
    else:
        print("\n[!] Warning: Estimated mode did not recover additional movements.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
