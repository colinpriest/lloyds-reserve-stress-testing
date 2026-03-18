#!/usr/bin/env python3
"""
Merge Corpus Script
===================
Combines syndicate-level reserve movements with market-level commentary
into a unified corpus for embedding and stress test generation.

Inputs:
- results/syndicate/standardized_syndicate_movements.json (syndicate-year-LOB movements)
- results/market/standardized_movements_*.json (market-year-LOB movements)

Output:
- results/combined/unified_corpus.json (all movements in consistent schema)
- results/combined/corpus_by_lob.json (grouped by LOB for retrieval)
- results/combined/corpus_by_year.json (grouped by year)
- results/combined/training_pairs.json (prompt/response pairs for LLM)
- results/combined/embedding_inputs.json (text for embedding model)
"""

import os
import json
import logging
import argparse
import hashlib
from dataclasses import dataclass, asdict, field
from typing import List, Dict, Optional, Any
from datetime import datetime
from pathlib import Path
from collections import defaultdict

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# =============================================================================
# Unified Schema
# =============================================================================

@dataclass
class UnifiedReserveMovement:
    """
    Unified schema for both syndicate and market reserve movements.
    """
    # Identity
    id: str  # Unique identifier
    source_type: str  # 'syndicate' or 'market'
    
    # Core data
    year: int
    line_of_business: str
    direction: str  # 'release', 'strengthening', 'flat', 'mixed'
    
    # Quantification (nullable)
    percentage: Optional[float] = None
    amount_gbp_m: Optional[float] = None
    amount_usd_m: Optional[float] = None
    
    # Causal information
    primary_causes: List[str] = field(default_factory=list)
    specific_events: List[str] = field(default_factory=list)
    specific_years_affected: List[int] = field(default_factory=list)
    
    # Narrative
    standardized_narrative: str = ""
    
    # Metadata
    confidence: str = "medium"
    data_quality_notes: str = ""
    
    # Source-specific fields
    syndicate: Optional[int] = None  # For syndicate movements
    source_urls: List[str] = field(default_factory=list)  # For market movements
    
    # Audit trail
    source_file: str = ""
    content_hash: str = ""
    merged_at: str = ""
    
    # Embedding text (generated)
    embedding_text: str = ""


# =============================================================================
# Standard Categories
# =============================================================================

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
    "Aggregate",
]

STANDARD_CAUSES = [
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


# =============================================================================
# Merge Functions
# =============================================================================

def load_syndicate_movements(filepath: str) -> List[Dict]:
    """Load syndicate movements from standardized output."""
    logger.info(f"Loading syndicate movements from {filepath}")
    
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    movements = data.get('movements', [])
    logger.info(f"Loaded {len(movements)} syndicate movements")
    return movements


def load_market_movements(market_dir: str) -> List[Dict]:
    """Load market movements from all year files."""
    logger.info(f"Loading market movements from {market_dir}")
    
    market_path = Path(market_dir)
    movements = []
    
    # Find all standardized_movements_*.json files
    for filepath in sorted(market_path.glob("standardized_movements_*.json")):
        logger.info(f"  Loading {filepath.name}")
        with open(filepath, 'r', encoding='utf-8') as f:
            year_data = json.load(f)
        
        # Market files are keyed by LOB
        for lob, movement in year_data.items():
            if isinstance(movement, dict):
                movement['_source_file'] = str(filepath)
                movements.append(movement)
    
    logger.info(f"Loaded {len(movements)} market movements")
    return movements


def generate_id(source_type: str, year: int, lob: str, syndicate: int = None) -> str:
    """Generate unique ID for a movement."""
    if source_type == 'syndicate':
        base = f"syn_{syndicate}_{year}_{lob}"
    else:
        base = f"mkt_{year}_{lob}"
    
    # Create short hash for uniqueness
    hash_suffix = hashlib.md5(base.encode()).hexdigest()[:8]
    return f"{base.lower().replace(' ', '_').replace('-', '_')}_{hash_suffix}"


def safe_float(value) -> Optional[float]:
    """Safely convert value to float."""
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def safe_int(value) -> Optional[int]:
    """Safely convert value to int."""
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def generate_embedding_text(movement: Dict, source_type: str) -> str:
    """
    Generate text suitable for embedding.
    Combines key information into a coherent narrative.
    """
    parts = []
    
    # Year and LOB context
    year = movement.get('year', '')
    lob = movement.get('line_of_business', '')
    direction = movement.get('direction', '')
    
    if source_type == 'syndicate':
        syndicate = movement.get('syndicate', '')
        parts.append(f"Lloyd's Syndicate {syndicate} {year} {lob}:")
    else:
        parts.append(f"Lloyd's Market {year} {lob}:")
    
    # Direction and magnitude - safely convert types
    pct = safe_float(movement.get('percentage'))
    amount_gbp = safe_float(movement.get('amount_gbp_m'))
    amount_usd = safe_float(movement.get('amount_usd_m'))
    
    if direction == 'release':
        direction_text = "Prior year reserve release"
    elif direction == 'strengthening':
        direction_text = "Prior year reserve strengthening"
    elif direction == 'mixed':
        direction_text = "Mixed prior year development"
    else:
        direction_text = "Prior year development"
    
    if pct:
        parts.append(f"{direction_text} of {pct}%")
    elif amount_gbp:
        parts.append(f"{direction_text} of £{amount_gbp}m")
    elif amount_usd:
        parts.append(f"{direction_text} of ${amount_usd}m")
    else:
        parts.append(direction_text)
    
    # Causes
    causes = movement.get('primary_causes', [])
    if causes:
        parts.append(f"driven by {', '.join(causes[:3])}")
    
    # Specific events
    events = movement.get('specific_events', [])
    if events:
        parts.append(f"including {', '.join(events[:3])}")
    
    # Narrative if available
    narrative = movement.get('standardized_narrative', '')
    if narrative:
        parts.append(f"- {narrative}")
    
    return ' '.join(parts)


def convert_syndicate_movement(movement: Dict) -> UnifiedReserveMovement:
    """Convert syndicate movement to unified schema."""
    
    unified = UnifiedReserveMovement(
        id=generate_id('syndicate', movement.get('year'), 
                       movement.get('line_of_business'), 
                       movement.get('syndicate')),
        source_type='syndicate',
        year=safe_int(movement.get('year')) or 0,
        line_of_business=movement.get('line_of_business', 'Aggregate'),
        direction=movement.get('direction', 'unknown'),
        percentage=safe_float(movement.get('percentage')),
        amount_gbp_m=safe_float(movement.get('amount_gbp_m')),
        amount_usd_m=safe_float(movement.get('amount_usd_m')),
        primary_causes=movement.get('primary_causes', []),
        specific_events=movement.get('specific_events', []),
        specific_years_affected=movement.get('specific_years_affected', []),
        standardized_narrative=movement.get('standardized_narrative', ''),
        confidence=movement.get('confidence', 'medium'),
        data_quality_notes=movement.get('data_quality_notes', ''),
        syndicate=safe_int(movement.get('syndicate')),
        source_file=movement.get('source_file', ''),
        content_hash=movement.get('content_hash', ''),
        merged_at=datetime.now().isoformat(),
        embedding_text=generate_embedding_text(movement, 'syndicate')
    )
    
    return unified


def convert_market_movement(movement: Dict) -> UnifiedReserveMovement:
    """Convert market movement to unified schema."""
    
    unified = UnifiedReserveMovement(
        id=generate_id('market', movement.get('year'), 
                       movement.get('line_of_business')),
        source_type='market',
        year=safe_int(movement.get('year')) or 0,
        line_of_business=movement.get('line_of_business', 'Aggregate'),
        direction=movement.get('direction', 'unknown'),
        percentage=safe_float(movement.get('percentage')),
        amount_gbp_m=safe_float(movement.get('amount_gbp_m')),
        amount_usd_m=safe_float(movement.get('amount_usd_m')),
        primary_causes=movement.get('primary_causes', []),
        specific_events=movement.get('specific_events', []),
        specific_years_affected=[],  # Market data typically doesn't have this
        standardized_narrative=movement.get('standardized_narrative', ''),
        confidence=movement.get('confidence', 'medium'),
        data_quality_notes=movement.get('data_quality_notes', ''),
        source_urls=movement.get('source_urls', []),
        source_file=movement.get('_source_file', ''),
        content_hash='',
        merged_at=datetime.now().isoformat(),
        embedding_text=generate_embedding_text(movement, 'market')
    )
    
    return unified


def generate_training_pair(movement: UnifiedReserveMovement) -> Dict:
    """
    Generate a training pair (prompt/response) for LLM fine-tuning.
    """
    # Build prompt - handle potential string types
    try:
        pct = float(movement.percentage) if movement.percentage else None
    except (ValueError, TypeError):
        pct = None
    
    try:
        gbp = float(movement.amount_gbp_m) if movement.amount_gbp_m else None
    except (ValueError, TypeError):
        gbp = None
    
    try:
        usd = float(movement.amount_usd_m) if movement.amount_usd_m else None
    except (ValueError, TypeError):
        usd = None
    
    if pct:
        severity = f"{abs(pct)}%"
    elif gbp:
        severity = f"£{abs(gbp)}m"
    elif usd:
        severity = f"${abs(usd)}m"
    else:
        severity = "material"
    
    prompt = f"Generate a {movement.direction} stress scenario for {movement.line_of_business} reserves of approximately {severity}."
    
    # Build response
    response_parts = []
    
    if movement.source_type == 'syndicate':
        response_parts.append(f"Based on historical experience from Lloyd's Syndicate {movement.syndicate} ({movement.year}):")
    else:
        response_parts.append(f"Based on Lloyd's market experience ({movement.year}):")
    
    response_parts.append(movement.standardized_narrative or f"Prior year {movement.direction} on {movement.line_of_business} business.")
    
    if movement.primary_causes:
        response_parts.append(f"Key drivers: {', '.join(movement.primary_causes)}.")
    
    if movement.specific_events:
        response_parts.append(f"Specific events: {', '.join(movement.specific_events)}.")
    
    return {
        "prompt": prompt,
        "response": " ".join(response_parts),
        "metadata": {
            "source_id": movement.id,
            "source_type": movement.source_type,
            "year": movement.year,
            "lob": movement.line_of_business,
            "direction": movement.direction,
            "severity_pct": movement.percentage,
            "severity_gbp_m": movement.amount_gbp_m,
            "causes": movement.primary_causes,
        }
    }


def merge_size_metrics_into_corpus(corpus_data: Dict, size_metrics_path: Path) -> int:
    """
    Merge size metrics into corpus movements in-place.

    Args:
        corpus_data: Corpus dictionary with 'movements' key
        size_metrics_path: Path to size_metrics.json

    Returns:
        Number of movements enhanced
    """
    if not size_metrics_path.exists():
        logger.info(f"No size metrics found at {size_metrics_path}, skipping merge")
        return 0

    # Load size metrics
    with open(size_metrics_path, 'r', encoding='utf-8') as f:
        size_data = json.load(f)

    # Create lookup by syndicate-year
    size_lookup = {}
    for m in size_data.get('metrics', []):
        key = (m['syndicate'], m['year'])
        if m.get('technical_provisions_gbp_m') or m.get('stamp_capacity_gbp_m'):
            size_lookup[key] = m

    logger.info(f"Loaded {len(size_lookup)} syndicate-years with size data")

    # Enhance movements with size data
    movements = corpus_data.get('movements', [])
    enhanced_count = 0

    for movement in movements:
        syndicate = movement.get('syndicate')
        year = movement.get('year')

        if syndicate and year:
            key = (syndicate, year)
            if key in size_lookup:
                size_info = size_lookup[key]

                # Add size fields to movement
                movement['prior_reserves_gbp_m'] = (
                    size_info.get('technical_provisions_gbp_m') or
                    size_info.get('claims_outstanding_gbp_m')
                )
                movement['stamp_capacity_gbp_m'] = size_info.get('stamp_capacity_gbp_m')
                movement['gross_premium_gbp_m'] = size_info.get('gross_written_premium_gbp_m')
                movement['reporting_currency'] = size_info.get('reporting_currency', 'GBP')

                # Calculate severity ratio if we have both movement and reserves
                if movement.get('amount_gbp_m') and movement.get('prior_reserves_gbp_m'):
                    amount = movement['amount_gbp_m']
                    reserves = movement['prior_reserves_gbp_m']
                    if reserves > 0:
                        # Adjust sign based on direction
                        if movement.get('direction') == 'strengthening':
                            movement['severity_ratio'] = amount / reserves
                        elif movement.get('direction') == 'release':
                            movement['severity_ratio'] = -amount / reserves

                enhanced_count += 1

    if enhanced_count > 0:
        corpus_data['size_data_merged_at'] = datetime.now().isoformat()
        corpus_data['movements_with_size_data'] = enhanced_count
        logger.info(f"Enhanced {enhanced_count} movements with size data")

    return enhanced_count


def merge_corpus(
    syndicate_file: str,
    market_dir: str,
    output_dir: str,
    min_confidence: str = "low",
    auto_merge_size_metrics: bool = True
) -> Dict[str, Any]:
    """
    Main merge function.

    Args:
        syndicate_file: Path to syndicate movements JSON
        market_dir: Path to market results directory
        output_dir: Output directory for merged corpus
        min_confidence: Minimum confidence level to include
        auto_merge_size_metrics: Auto-merge size_metrics.json if found

    Returns:
        Summary statistics
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    # Load data
    syndicate_movements = load_syndicate_movements(syndicate_file)
    market_movements = load_market_movements(market_dir)
    
    # Convert to unified schema
    unified_movements = []
    
    confidence_levels = {"high": 3, "medium": 2, "low": 1}
    min_conf_level = confidence_levels.get(min_confidence, 1)
    
    # Process syndicate movements
    for m in syndicate_movements:
        conf_level = confidence_levels.get(m.get('confidence', 'low'), 1)
        if conf_level >= min_conf_level:
            unified = convert_syndicate_movement(m)
            unified_movements.append(unified)
    
    logger.info(f"Converted {len([m for m in unified_movements if m.source_type == 'syndicate'])} syndicate movements")
    
    # Process market movements
    for m in market_movements:
        conf_level = confidence_levels.get(m.get('confidence', 'low'), 1)
        if conf_level >= min_conf_level:
            unified = convert_market_movement(m)
            unified_movements.append(unified)
    
    logger.info(f"Converted {len([m for m in unified_movements if m.source_type == 'market'])} market movements")
    logger.info(f"Total unified movements: {len(unified_movements)}")
    
    # Generate outputs
    
    # 1. Main unified corpus
    unified_data = {
        "generated_at": datetime.now().isoformat(),
        "total_movements": len(unified_movements),
        "syndicate_movements": len([m for m in unified_movements if m.source_type == 'syndicate']),
        "market_movements": len([m for m in unified_movements if m.source_type == 'market']),
        "movements": [asdict(m) for m in unified_movements]
    }

    # Auto-merge size metrics if available
    size_metrics_enhanced = 0
    if auto_merge_size_metrics:
        # Look for size_metrics.json in common locations
        size_metrics_paths = [
            output_path / "size_metrics.json",
            output_path.parent / "size_metrics.json",
            output_path.parent / "stress_test" / "size_metrics.json",
            Path("results/stress_test/size_metrics.json"),
            Path("results/size_metrics.json"),
            Path("size_metrics.json"),
        ]

        for size_path in size_metrics_paths:
            if size_path.exists():
                logger.info(f"Found size metrics at {size_path}, auto-merging...")
                size_metrics_enhanced = merge_size_metrics_into_corpus(unified_data, size_path)
                break
        else:
            logger.info("No size_metrics.json found for auto-merge (this is OK if not extracted yet)")

    unified_path = output_path / "unified_corpus.json"
    with open(unified_path, 'w', encoding='utf-8') as f:
        json.dump(unified_data, f, indent=2, ensure_ascii=False)
    logger.info(f"Saved unified corpus to {unified_path}")
    
    # 2. Corpus grouped by LOB
    by_lob = defaultdict(list)
    for m in unified_movements:
        by_lob[m.line_of_business].append(asdict(m))
    
    lob_data = {
        "generated_at": datetime.now().isoformat(),
        "lobs": dict(by_lob)
    }
    
    lob_path = output_path / "corpus_by_lob.json"
    with open(lob_path, 'w', encoding='utf-8') as f:
        json.dump(lob_data, f, indent=2, ensure_ascii=False)
    logger.info(f"Saved LOB corpus to {lob_path}")
    
    # 3. Corpus grouped by year
    by_year = defaultdict(list)
    for m in unified_movements:
        by_year[m.year].append(asdict(m))
    
    year_data = {
        "generated_at": datetime.now().isoformat(),
        "years": {str(k): v for k, v in sorted(by_year.items())}
    }
    
    year_path = output_path / "corpus_by_year.json"
    with open(year_path, 'w', encoding='utf-8') as f:
        json.dump(year_data, f, indent=2, ensure_ascii=False)
    logger.info(f"Saved year corpus to {year_path}")
    
    # 4. Training pairs
    training_pairs = []
    for m in unified_movements:
        if m.direction in ['release', 'strengthening'] and m.standardized_narrative:
            pair = generate_training_pair(m)
            training_pairs.append(pair)
    
    training_data = {
        "generated_at": datetime.now().isoformat(),
        "total_pairs": len(training_pairs),
        "pairs": training_pairs
    }
    
    training_path = output_path / "training_pairs.json"
    with open(training_path, 'w', encoding='utf-8') as f:
        json.dump(training_data, f, indent=2, ensure_ascii=False)
    logger.info(f"Saved {len(training_pairs)} training pairs to {training_path}")
    
    # 5. Embedding inputs (just the text)
    embedding_inputs = []
    for m in unified_movements:
        embedding_inputs.append({
            "id": m.id,
            "text": m.embedding_text,
            "year": m.year,
            "lob": m.line_of_business,
            "direction": m.direction,
            "source_type": m.source_type
        })
    
    embedding_data = {
        "generated_at": datetime.now().isoformat(),
        "total_inputs": len(embedding_inputs),
        "inputs": embedding_inputs
    }
    
    embedding_path = output_path / "embedding_inputs.json"
    with open(embedding_path, 'w', encoding='utf-8') as f:
        json.dump(embedding_data, f, indent=2, ensure_ascii=False)
    logger.info(f"Saved embedding inputs to {embedding_path}")
    
    # 6. Summary statistics
    summary = {
        "generated_at": datetime.now().isoformat(),
        "total_movements": len(unified_movements),
        "by_source": {
            "syndicate": len([m for m in unified_movements if m.source_type == 'syndicate']),
            "market": len([m for m in unified_movements if m.source_type == 'market']),
        },
        "by_direction": {
            "release": len([m for m in unified_movements if m.direction == 'release']),
            "strengthening": len([m for m in unified_movements if m.direction == 'strengthening']),
            "mixed": len([m for m in unified_movements if m.direction == 'mixed']),
            "flat": len([m for m in unified_movements if m.direction == 'flat']),
            "unknown": len([m for m in unified_movements if m.direction not in ['release', 'strengthening', 'mixed', 'flat']]),
        },
        "by_lob": {lob: len(movements) for lob, movements in by_lob.items()},
        "by_year": {str(year): len(movements) for year, movements in sorted(by_year.items())},
        "by_confidence": {
            "high": len([m for m in unified_movements if m.confidence == 'high']),
            "medium": len([m for m in unified_movements if m.confidence == 'medium']),
            "low": len([m for m in unified_movements if m.confidence == 'low']),
        },
        "training_pairs_generated": len(training_pairs),
        "unique_syndicates": len(set(m.syndicate for m in unified_movements if m.syndicate)),
        "year_range": {
            "min": min((m.year for m in unified_movements), default=None),
            "max": max((m.year for m in unified_movements), default=None),
        },
        "size_metrics_enhanced": size_metrics_enhanced,
        "causes_frequency": {},
    }
    
    # Count cause frequency
    cause_counts = defaultdict(int)
    for m in unified_movements:
        for cause in m.primary_causes:
            cause_counts[cause] += 1
    summary["causes_frequency"] = dict(sorted(cause_counts.items(), key=lambda x: -x[1]))
    
    summary_path = output_path / "corpus_summary.json"
    with open(summary_path, 'w', encoding='utf-8') as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    logger.info(f"Saved summary to {summary_path}")
    
    return summary


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Merge syndicate and market reserve movements into unified corpus"
    )
    parser.add_argument(
        "--syndicate-file", "-s",
        default="results/syndicate/standardized_syndicate_movements.json",
        help="Path to syndicate movements JSON"
    )
    parser.add_argument(
        "--market-dir", "-m",
        default="results/market",
        help="Path to market results directory"
    )
    parser.add_argument(
        "--output-dir", "-o",
        default="results/combined",
        help="Output directory for merged corpus"
    )
    parser.add_argument(
        "--min-confidence",
        choices=["high", "medium", "low"],
        default="low",
        help="Minimum confidence level to include (default: low = all)"
    )
    parser.add_argument(
        "--no-size-metrics",
        action="store_true",
        help="Disable automatic merging of size_metrics.json"
    )

    args = parser.parse_args()
    
    # Check inputs exist
    if not Path(args.syndicate_file).exists():
        logger.error(f"Syndicate file not found: {args.syndicate_file}")
        return
    
    if not Path(args.market_dir).exists():
        logger.error(f"Market directory not found: {args.market_dir}")
        return
    
    # Run merge
    summary = merge_corpus(
        args.syndicate_file,
        args.market_dir,
        args.output_dir,
        args.min_confidence,
        auto_merge_size_metrics=not args.no_size_metrics
    )

    # Print summary
    print(f"\n{'='*60}")
    print("CORPUS MERGE COMPLETE")
    print(f"{'='*60}")
    print(f"Total movements: {summary['total_movements']}")
    print(f"  Syndicate: {summary['by_source']['syndicate']}")
    print(f"  Market: {summary['by_source']['market']}")
    print(f"\nBy direction:")
    print(f"  Releases: {summary['by_direction']['release']}")
    print(f"  Strengthenings: {summary['by_direction']['strengthening']}")
    print(f"  Mixed: {summary['by_direction']['mixed']}")
    print(f"\nYear range: {summary['year_range']['min']} - {summary['year_range']['max']}")
    print(f"Unique syndicates: {summary['unique_syndicates']}")
    print(f"Training pairs generated: {summary['training_pairs_generated']}")

    # Size metrics info
    size_enhanced = summary.get('size_metrics_enhanced', 0)
    if size_enhanced > 0:
        print(f"\nSize metrics merged: {size_enhanced} movements enhanced with reserve data")
    else:
        print(f"\nSize metrics: Not merged (run extract_size_metrics.py first)")

    print(f"\nOutput directory: {args.output_dir}")
    print(f"\nTop 10 causes:")
    for cause, count in list(summary['causes_frequency'].items())[:10]:
        print(f"  {cause}: {count}")


if __name__ == "__main__":
    main()