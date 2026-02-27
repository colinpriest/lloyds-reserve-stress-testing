"""
HTML Report Generator for Stress Test Scenarios

Generates professional HTML reports with:
- Executive summary
- Scenario details with narratives
- Audit trail showing derivation from historical data
- LLM commentary on plausibility
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)


@dataclass
class ScenarioAuditInfo:
    """Audit information for a scenario."""
    scenario_id: str
    anchor_id: str
    anchor_narrative: str
    anchor_severity: float
    anchor_lob: str
    anchor_year: int
    few_shot_examples: List[Dict]  # List of {id, narrative, severity, lob, distance}
    distributional_probability: float
    confidence: str
    derivation_reasoning: str


def generate_derivation_commentary(
    scenario: Dict,
    anchor: Dict,
    few_shot_examples: List[Dict],
    client,  # OpenAI client
    existing_reasoning: str = ""
) -> str:
    """Generate LLM commentary explaining how scenario was derived."""
    
    # Separate by selection type
    similarity_examples = [ex for ex in few_shot_examples if ex.get('selection_reason', 'similarity') == 'similarity']
    diversity_examples = [ex for ex in few_shot_examples if ex.get('selection_reason') == 'diversity']
    
    similarity_text = "\n".join([
        f"  - [{ex.get('year', 'N/A')} {ex.get('lob', 'N/A')}]: {ex.get('narrative', 'N/A')[:200]}... (severity: {ex.get('severity', 0):.1%})"
        for ex in similarity_examples
    ])
    
    diversity_text = "\n".join([
        f"  - [{ex.get('year', 'N/A')} {ex.get('lob', 'N/A')}]: {ex.get('narrative', 'N/A')[:200]}... (severity: {ex.get('severity', 0):.1%})"
        for ex in diversity_examples
    ])
    
    existing_context = ""
    if existing_reasoning:
        existing_context = f"""
EXISTING ANALYSIS (from generation-time assessment):
{existing_reasoning}

Build on this analysis with additional context:"""
    
    prompt = f"""Explain how this synthetic stress scenario was derived from historical data (2-3 paragraphs):

GENERATED SCENARIO:
- Name: {scenario.get('name', 'N/A')}
- Severity: {scenario.get('severity_ratio', 0):.1%}
- Narrative: {scenario.get('narrative', 'N/A')}
- LOB Impacts: {scenario.get('lob_breakdown', scenario.get('lob_impacts', {}))}
- Key Events: {scenario.get('causal_chain', 'N/A')}

PRIMARY HISTORICAL ANCHOR:
- Year: {anchor.get('year', 'N/A')}
- LOB: {anchor.get('lob', 'N/A')}
- Severity: {anchor.get('severity', 0):.1%}
- Narrative: {anchor.get('narrative', 'N/A')}

SIMILAR HISTORICAL EXAMPLES (same LOB/theme - used to maintain realistic patterns):
{similarity_text if similarity_text.strip() else "None available."}

CONTRASTIVE EXAMPLES (different LOB/causes - used to calibrate severity-to-narrative relationships):
{diversity_text if diversity_text.strip() else "None available."}
{existing_context}
Explain:
1. How the scenario draws from and extends the historical anchor
2. What elements were combined from the similar examples to create a holistic multi-peril scenario
3. How the contrastive examples helped calibrate the relationship between severity levels and narrative content
4. Why this combination of perils and severity is plausible and internally consistent
5. Any extrapolation beyond historical experience and its justification

Write in professional actuarial language suitable for a board report. Focus on the logic of the combination."""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a senior actuary explaining stress test methodology to a board of directors. Focus on explaining why the combination of events is realistic and well-calibrated."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=700,
            temperature=0.3
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"Failed to generate derivation commentary: {e}")
        if existing_reasoning:
            return existing_reasoning
        return f"Commentary generation failed: {e}"


def load_audit_trail(library_dir: Path) -> Dict:
    """Load generation audit trail from library directory."""
    audit_path = library_dir / "generation_audit_trail.json"
    if audit_path.exists():
        with open(audit_path, 'r') as f:
            return json.load(f)
    return {}


def get_scenario_audit_info(
    scenario_id: str,
    audit_trail: Dict,
    library_data: Dict
) -> Optional[Dict]:
    """Get audit information for a specific scenario."""
    
    # The scenario_id in query results is from source_scenarios which contains original generation IDs
    # Find in audit trail records
    for record in audit_trail.get('records', []):
        if record.get('scenario_id') == scenario_id:
            return record
    
    # Try to find in library by ID and get source neighbours
    for s in library_data.get('scenarios', []):
        if s.get('id') == scenario_id:
            # Look up audit record by source_neighbours
            source_neighbours = s.get('source_neighbours', [])
            for neighbour_id in source_neighbours:
                for record in audit_trail.get('records', []):
                    if record.get('scenario_id') == neighbour_id:
                        return record
            
            return {
                'scenario_id': scenario_id,
                'source_neighbours': source_neighbours,
            }
    
    return None


def extract_audit_for_scenario(source_scenarios: List[str], audit_trail: Dict) -> Optional[Dict]:
    """Extract audit info from source scenario IDs."""
    for source_id in source_scenarios:
        for record in audit_trail.get('records', []):
            if record.get('scenario_id') == source_id:
                return record
    return None


HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Stress Test Report - {title}</title>
    <style>
        :root {{
            --primary: #1a365d;
            --secondary: #2c5282;
            --accent: #3182ce;
            --success: #38a169;
            --warning: #d69e2e;
            --danger: #e53e3e;
            --light: #f7fafc;
            --dark: #1a202c;
        }}
        
        * {{
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }}
        
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            line-height: 1.6;
            color: var(--dark);
            background: var(--light);
        }}
        
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
        }}
        
        header {{
            background: linear-gradient(135deg, var(--primary), var(--secondary));
            color: white;
            padding: 40px 20px;
            margin-bottom: 30px;
        }}
        
        header h1 {{
            font-size: 2.5em;
            margin-bottom: 10px;
        }}
        
        header .subtitle {{
            font-size: 1.2em;
            opacity: 0.9;
        }}
        
        .executive-summary {{
            background: white;
            border-radius: 10px;
            padding: 30px;
            margin-bottom: 30px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }}
        
        .executive-summary h2 {{
            color: var(--primary);
            border-bottom: 3px solid var(--accent);
            padding-bottom: 10px;
            margin-bottom: 20px;
        }}
        
        .portfolio-summary {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-bottom: 20px;
        }}
        
        .stat-card {{
            background: var(--light);
            padding: 20px;
            border-radius: 8px;
            text-align: center;
        }}
        
        .stat-card .value {{
            font-size: 2em;
            font-weight: bold;
            color: var(--primary);
        }}
        
        .stat-card .label {{
            color: #666;
            font-size: 0.9em;
        }}
        
        .scenario {{
            background: white;
            border-radius: 10px;
            margin-bottom: 30px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            overflow: hidden;
        }}
        
        .scenario-header {{
            background: var(--primary);
            color: white;
            padding: 20px 30px;
        }}
        
        .scenario-header h3 {{
            font-size: 1.5em;
            margin-bottom: 5px;
        }}
        
        .scenario-header .meta {{
            opacity: 0.9;
            font-size: 0.95em;
        }}
        
        .scenario-body {{
            padding: 30px;
        }}
        
        .section {{
            margin-bottom: 25px;
        }}
        
        .section h4 {{
            color: var(--secondary);
            font-size: 1.1em;
            margin-bottom: 10px;
            display: flex;
            align-items: center;
            gap: 8px;
        }}
        
        .section h4::before {{
            content: '';
            width: 4px;
            height: 20px;
            background: var(--accent);
            border-radius: 2px;
        }}
        
        .narrative {{
            background: #f0f4f8;
            padding: 20px;
            border-radius: 8px;
            border-left: 4px solid var(--accent);
            font-style: italic;
        }}
        
        .lob-impacts {{
            display: grid;
            gap: 10px;
        }}
        
        .lob-bar {{
            display: flex;
            align-items: center;
            gap: 10px;
        }}
        
        .lob-bar .name {{
            width: 180px;
            font-weight: 500;
        }}
        
        .lob-bar .bar-container {{
            flex: 1;
            background: #e2e8f0;
            border-radius: 4px;
            height: 24px;
            overflow: hidden;
        }}
        
        .lob-bar .bar {{
            height: 100%;
            background: linear-gradient(90deg, var(--accent), var(--secondary));
            border-radius: 4px;
            display: flex;
            align-items: center;
            justify-content: flex-end;
            padding-right: 8px;
            color: white;
            font-size: 0.85em;
            font-weight: 500;
            min-width: 50px;
        }}
        
        .events-list {{
            list-style: none;
            padding: 0;
        }}
        
        .events-list li {{
            padding: 8px 0;
            border-bottom: 1px solid #e2e8f0;
            display: flex;
            align-items: flex-start;
            gap: 10px;
        }}
        
        .events-list li:last-child {{
            border-bottom: none;
        }}
        
        .events-list li::before {{
            content: '⚡';
        }}
        
        .audit-trail {{
            background: #fffbeb;
            border: 1px solid #f6e05e;
            border-radius: 8px;
            padding: 20px;
        }}
        
        .audit-trail h5 {{
            color: var(--warning);
            margin-bottom: 15px;
        }}
        
        .historical-anchor {{
            background: white;
            padding: 15px;
            border-radius: 6px;
            margin-bottom: 15px;
        }}
        
        .historical-anchor .label {{
            font-size: 0.85em;
            color: #666;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}
        
        .probability-badge {{
            display: inline-block;
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 0.85em;
            font-weight: 500;
        }}
        
        .probability-high {{
            background: #c6f6d5;
            color: #276749;
        }}
        
        .probability-medium {{
            background: #fefcbf;
            color: #975a16;
        }}
        
        .probability-low {{
            background: #fed7d7;
            color: #c53030;
        }}
        
        .derivation-commentary {{
            background: #ebf8ff;
            border: 1px solid #90cdf4;
            border-radius: 8px;
            padding: 20px;
            margin-top: 15px;
        }}
        
        .derivation-commentary h5 {{
            color: var(--accent);
            margin-bottom: 10px;
        }}
        
        .few-shot-examples {{
            margin-top: 15px;
        }}
        
        .example-group {{
            margin-top: 10px;
            margin-bottom: 8px;
        }}
        
        .example {{
            background: white;
            padding: 12px;
            border-radius: 6px;
            margin-bottom: 10px;
            font-size: 0.9em;
            border-left: 3px solid #cbd5e0;
        }}
        
        .example-similarity {{
            border-left-color: #3182ce;
            background: #ebf8ff;
        }}
        
        .example-diversity {{
            border-left-color: #805ad5;
            background: #faf5ff;
        }}
        
        .example .meta {{
            color: #666;
            font-size: 0.85em;
            margin-top: 5px;
        }}
        
        .badge {{
            display: inline-block;
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 0.75em;
            font-weight: 600;
            margin-right: 8px;
        }}
        
        .badge-similarity {{
            background: #bee3f8;
            color: #2a69ac;
        }}
        
        .badge-diversity {{
            background: #e9d8fd;
            color: #6b46c1;
        }}
        
        footer {{
            text-align: center;
            padding: 30px;
            color: #666;
            font-size: 0.9em;
        }}
        
        @media print {{
            body {{
                background: white;
            }}
            
            .scenario {{
                break-inside: avoid;
            }}
            
            header {{
                background: var(--primary) !important;
                -webkit-print-color-adjust: exact;
            }}
        }}
    </style>
</head>
<body>
    <header>
        <div class="container">
            <h1>🏛️ Stress Test Report</h1>
            <div class="subtitle">{subtitle}</div>
        </div>
    </header>
    
    <div class="container">
        <section class="executive-summary">
            <h2>Executive Summary</h2>
            
            <div class="portfolio-summary">
                <div class="stat-card">
                    <div class="value">£{total_reserves:.0f}m</div>
                    <div class="label">Total Reserves</div>
                </div>
                <div class="stat-card">
                    <div class="value">{return_period}-year</div>
                    <div class="label">Return Period</div>
                </div>
                <div class="stat-card">
                    <div class="value">{n_scenarios}</div>
                    <div class="label">Scenarios Analysed</div>
                </div>
                <div class="stat-card">
                    <div class="value">{avg_severity:.1%}</div>
                    <div class="label">Average Severity</div>
                </div>
            </div>
            
            <h4 style="margin-top: 20px; color: var(--secondary);">Portfolio Composition</h4>
            <p>{portfolio_composition}</p>
            
            <h4 style="margin-top: 20px; color: var(--secondary);">Key Findings</h4>
            <p>{key_findings}</p>
        </section>
        
        {scenarios_html}
    </div>
    
    <footer>
        <p>Generated on {generation_date} | Lloyd's Reserve Stress Test Generator v2</p>
        <p>This report is for internal risk management purposes only.</p>
    </footer>
</body>
</html>
"""


SCENARIO_TEMPLATE = """
<section class="scenario">
    <div class="scenario-header">
        <h3>Scenario {index}: {name}</h3>
        <div class="meta">
            Return Period: {return_period}-year | 
            Total Severity: {severity:.1%} |
            Portfolio Impact: {portfolio_impact:.1%}
        </div>
    </div>
    
    <div class="scenario-body">
        <div class="section">
            <h4>Narrative</h4>
            <div class="narrative">{narrative}</div>
        </div>
        
        <div class="section">
            <h4>Key Events</h4>
            <ul class="events-list">
                {events_html}
            </ul>
        </div>
        
        <div class="section">
            <h4>Line of Business Impacts</h4>
            <div class="lob-impacts">
                {lob_impacts_html}
            </div>
        </div>
        
        <div class="section">
            <h4>Analysis</h4>
            <p>{explanation}</p>
        </div>
        
        <div class="section">
            <h4>Audit Trail & Derivation</h4>
            <div class="audit-trail">
                <h5>📜 Historical Basis</h5>
                
                <div class="historical-anchor">
                    <div class="label">Primary Historical Anchor</div>
                    <p><strong>{anchor_year} - {anchor_lob}</strong></p>
                    <p>{anchor_narrative}</p>
                    <p class="meta">Original Severity: {anchor_severity:.1%}</p>
                </div>
                
                <div class="few-shot-examples">
                    <div class="label">Historical Examples Used for Generation</div>
                    {examples_html}
                </div>
                
                <div style="margin-top: 15px;">
                    <span class="label">Distributional Probability: </span>
                    <span class="probability-badge probability-{probability_class}">{probability:.0%}</span>
                    <span style="margin-left: 10px; color: #666;">({confidence} confidence)</span>
                </div>
            </div>
            
            <div class="derivation-commentary">
                <h5>💡 Derivation Commentary</h5>
                <p>{derivation_commentary}</p>
            </div>
        </div>
    </div>
</section>
"""


def generate_html_report(
    scenarios: List[Dict],
    portfolio: Dict,
    return_period: int,
    library_dir: Path,
    output_path: Path,
    client=None  # OpenAI client for commentary generation
) -> Path:
    """
    Generate HTML report for stress test scenarios.
    
    Args:
        scenarios: List of StressScenario dicts
        portfolio: Portfolio specification dict
        return_period: Return period in years
        library_dir: Path to scenario library directory
        output_path: Path for output HTML file
        client: OpenAI client (optional, for generating commentary)
    
    Returns:
        Path to generated HTML file
    """
    logger.info(f"Generating HTML report with {len(scenarios)} scenarios")
    
    # Load audit trail
    audit_trail = load_audit_trail(library_dir)
    
    # Load library data
    library_path = library_dir / "scenario_library.json"
    library_data = {}
    if library_path.exists():
        with open(library_path, 'r') as f:
            library_data = json.load(f)
    
    # Build scenario HTML
    scenarios_html = []
    
    for i, scenario in enumerate(scenarios, 1):
        # Get audit info from source scenarios
        source_ids = scenario.get('source_scenarios', [])
        audit_info = extract_audit_for_scenario(source_ids, audit_trail)
        
        # If not found by source_scenarios, try to find by matching in library
        if not audit_info:
            # Try matching by narrative similarity
            scenario_narrative = scenario.get('narrative', '')[:100]
            for record in audit_trail.get('records', []):
                parsed_narrative = record.get('generated_output', {}).get('parsed', {}).get('narrative', '')
                if scenario_narrative and parsed_narrative and scenario_narrative[:50] in parsed_narrative:
                    audit_info = record
                    break
        
        # Extract anchor info from audit
        if audit_info:
            anchor = audit_info.get('anchor', {})
            anchor_year = anchor.get('year', 'N/A')
            anchor_lob = anchor.get('lob', 'N/A')
            anchor_narrative = anchor.get('narrative', 'Historical anchor information not available.')
            anchor_severity = anchor.get('severity', 0) or 0
            
            # Few shot examples - include selection_reason
            few_shot_raw = audit_info.get('few_shot_examples', [])
            few_shot = []
            for ex in few_shot_raw:
                few_shot.append({
                    'id': ex.get('id', 'N/A'),
                    'narrative': ex.get('narrative', 'N/A'),
                    'severity': ex.get('severity_ratio', 0) or 0,
                    'lob': ex.get('line_of_business', 'N/A'),
                    'year': ex.get('year', 'N/A'),
                    'distance': ex.get('distance_to_anchor', 0) or 0,
                    'selection_reason': ex.get('selection_reason', 'similarity'),  # 'similarity' or 'diversity'
                    'causes': ex.get('primary_causes', [])
                })
            
            # Assessment info
            assessment = audit_info.get('assessment', {})
            probability = assessment.get('distributional_probability', 0.5) if assessment else 0.5
            confidence = assessment.get('confidence', 'medium') if assessment else 'medium'
            
            # Reasoning from assessment
            audit_reasoning = assessment.get('reasoning', '') if assessment else ''
        else:
            anchor_year = 'N/A'
            anchor_lob = 'N/A'
            anchor_narrative = 'Audit trail not available for this scenario.'
            anchor_severity = 0
            few_shot = []
            probability = 0.5
            confidence = 'unknown'
            audit_reasoning = ''
        
        # Probability class for styling
        if probability >= 0.7:
            probability_class = 'high'
        elif probability >= 0.4:
            probability_class = 'medium'
        else:
            probability_class = 'low'
        
        # Generate derivation commentary
        if client and audit_info:
            derivation_commentary = generate_derivation_commentary(
                scenario, 
                audit_info.get('anchor', {}),
                few_shot,
                client,
                existing_reasoning=audit_reasoning
            )
        elif audit_reasoning:
            # Use existing assessment reasoning if no client
            derivation_commentary = audit_reasoning
        else:
            derivation_commentary = scenario.get('explanation', 'Commentary not available.')
        
        # Build events HTML
        events = scenario.get('causal_chain', '').split(', ') if scenario.get('causal_chain') else []
        if not events or events == ['']:
            events = scenario.get('specific_events', ['No specific events listed'])
        events_html = '\n'.join([f'<li>{event}</li>' for event in events[:5]])
        
        # Build LOB impacts HTML
        lob_impacts = scenario.get('lob_impacts', {})
        max_impact = max(lob_impacts.values()) if lob_impacts else 1
        lob_impacts_html = []
        for lob, impact in sorted(lob_impacts.items(), key=lambda x: -x[1]):
            if impact > 0:
                width = min(100, (impact / max_impact) * 100)
                lob_impacts_html.append(f'''
                <div class="lob-bar">
                    <span class="name">{lob}</span>
                    <div class="bar-container">
                        <div class="bar" style="width: {width}%">{impact:.1%}</div>
                    </div>
                </div>
                ''')
        lob_impacts_html = '\n'.join(lob_impacts_html)
        
        # Build examples HTML - show ALL examples, grouped by type
        similarity_examples = [ex for ex in few_shot if ex.get('selection_reason', 'similarity') == 'similarity']
        diversity_examples = [ex for ex in few_shot if ex.get('selection_reason') == 'diversity']
        
        examples_html = []
        
        # Similarity examples section
        if similarity_examples:
            examples_html.append(f'<div class="example-group"><strong>Similar Examples ({len(similarity_examples)}):</strong></div>')
            for ex in similarity_examples:
                causes_str = ', '.join(ex.get('causes', [])[:2]) if ex.get('causes') else ''
                examples_html.append(f'''
                <div class="example example-similarity">
                    <p>{ex.get('narrative', 'N/A')[:300]}{'...' if len(ex.get('narrative', '')) > 300 else ''}</p>
                    <div class="meta">
                        <span class="badge badge-similarity">SIMILARITY</span>
                        {ex.get('year', 'N/A')} | {ex.get('lob', 'N/A')} | 
                        Severity: {ex.get('severity', 0):.1%} | 
                        Distance: {ex.get('distance', 0):.3f}
                        {' | Causes: ' + causes_str if causes_str else ''}
                    </div>
                </div>
                ''')
        
        # Diversity/Contrastive examples section
        if diversity_examples:
            examples_html.append(f'<div class="example-group" style="margin-top: 15px;"><strong>Contrastive Examples ({len(diversity_examples)}):</strong><br><small style="color: #666;">Different LOB/causes to train severity-input relationships</small></div>')
            for ex in diversity_examples:
                causes_str = ', '.join(ex.get('causes', [])[:2]) if ex.get('causes') else ''
                examples_html.append(f'''
                <div class="example example-diversity">
                    <p>{ex.get('narrative', 'N/A')[:300]}{'...' if len(ex.get('narrative', '')) > 300 else ''}</p>
                    <div class="meta">
                        <span class="badge badge-diversity">CONTRASTIVE</span>
                        {ex.get('year', 'N/A')} | {ex.get('lob', 'N/A')} | 
                        Severity: {ex.get('severity', 0):.1%} | 
                        Distance: {ex.get('distance', 0):.3f}
                        {' | Causes: ' + causes_str if causes_str else ''}
                    </div>
                </div>
                ''')
        
        if not examples_html:
            examples_html = ['<p>No historical examples available.</p>']
        
        examples_html = '\n'.join(examples_html)
        
        # Render scenario
        scenario_html = SCENARIO_TEMPLATE.format(
            index=i,
            name=scenario.get('name', 'Unknown'),
            return_period=return_period,
            severity=scenario.get('severity_ratio', 0),
            portfolio_impact=scenario.get('portfolio_impact', 0),
            narrative=scenario.get('narrative', 'No narrative available.'),
            events_html=events_html,
            lob_impacts_html=lob_impacts_html,
            explanation=scenario.get('explanation', 'No analysis available.'),
            anchor_year=anchor_year,
            anchor_lob=anchor_lob,
            anchor_narrative=anchor_narrative,
            anchor_severity=anchor_severity,
            examples_html=examples_html,
            probability=probability,
            probability_class=probability_class,
            confidence=confidence,
            derivation_commentary=derivation_commentary
        )
        
        scenarios_html.append(scenario_html)
    
    # Build portfolio composition text
    lob_weights = portfolio.get('lob_weights', {})
    portfolio_composition = ', '.join([
        f"{lob}: {weight:.0%}" for lob, weight in lob_weights.items() if weight > 0
    ])
    
    # Calculate stats
    avg_severity = sum(s.get('severity_ratio', 0) for s in scenarios) / len(scenarios) if scenarios else 0
    
    # Key findings
    cause_categories = [s.get('name', '').split(' ')[-1] for s in scenarios]
    key_findings = (
        f"The analysis identified {len(scenarios)} plausible stress scenarios at the "
        f"{return_period}-year return period level. These scenarios span multiple risk "
        f"categories including {', '.join(set(cause_categories)[:4])}. "
        f"Average severity across scenarios is {avg_severity:.1%}, with portfolio-weighted "
        f"impacts reflecting the LOB mix."
    )
    
    # Render full report
    html = HTML_TEMPLATE.format(
        title=f"{return_period}-Year Stress Test",
        subtitle=f"Portfolio: £{portfolio.get('total_reserves_gbp_m', 0):.0f}m | Generated {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        total_reserves=portfolio.get('total_reserves_gbp_m', 0),
        return_period=return_period,
        n_scenarios=len(scenarios),
        avg_severity=avg_severity,
        portfolio_composition=portfolio_composition,
        key_findings=key_findings,
        scenarios_html='\n'.join(scenarios_html),
        generation_date=datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    )
    
    # Write file
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)
    
    logger.info(f"Generated HTML report: {output_path}")
    return output_path


def generate_query_report(
    scenarios: List,  # List of StressScenario objects
    portfolio,  # PortfolioSpec object
    return_period: int,
    library_dir: Path,
    output_path: Path,
    client=None
) -> Path:
    """
    Convenience function to generate report from query results.
    
    Converts dataclass objects to dicts for the main generator.
    """
    from dataclasses import asdict
    
    # Convert to dicts
    scenario_dicts = [asdict(s) if hasattr(s, '__dataclass_fields__') else s for s in scenarios]
    portfolio_dict = asdict(portfolio) if hasattr(portfolio, '__dataclass_fields__') else portfolio
    
    return generate_html_report(
        scenarios=scenario_dicts,
        portfolio=portfolio_dict,
        return_period=return_period,
        library_dir=library_dir,
        output_path=output_path,
        client=client
    )


if __name__ == "__main__":
    # Test with sample data
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python report_generator.py <library_dir>")
        sys.exit(1)
    
    library_dir = Path(sys.argv[1])
    
    # Load library
    with open(library_dir / "scenario_library.json", 'r') as f:
        data = json.load(f)
    
    # Sample scenarios
    scenarios = data.get('scenarios', [])[:5]
    
    # Sample portfolio
    portfolio = {
        'total_reserves_gbp_m': 500,
        'lob_weights': {
            'Property': 0.25,
            'Casualty': 0.25,
            'Marine': 0.15,
            'Motor': 0.10,
            'Professional Lines': 0.15,
            'Cyber': 0.10
        }
    }
    
    output_path = library_dir / "stress_test_report.html"
    
    generate_html_report(
        scenarios=scenarios,
        portfolio=portfolio,
        return_period=100,
        library_dir=library_dir,
        output_path=output_path
    )
    
    print(f"Generated report: {output_path}")
