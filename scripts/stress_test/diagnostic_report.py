"""
Library Diagnostics HTML Report Generator

Generates comprehensive HTML reports for library diagnostics with:
- Executive summary
- Embedded interactive visualizations
- Statistical test results
- Recommendations
"""

import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional
import logging

logger = logging.getLogger(__name__)


REPORT_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Library Diagnostics Report</title>
    <script src="https://cdn.plot.ly/plotly-2.26.0.min.js"></script>
    <style>
        :root {{
            --primary: #1a365d;
            --secondary: #2c5282;
            --accent: #3182ce;
            --pass: #38a169;
            --fail: #e53e3e;
            --warning: #d69e2e;
            --light: #f7fafc;
            --dark: #1a202c;
        }}
        
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            line-height: 1.6;
            color: var(--dark);
            background: var(--light);
        }}
        
        .container {{ max-width: 1400px; margin: 0 auto; padding: 20px; }}
        
        header {{
            background: linear-gradient(135deg, var(--primary), var(--secondary));
            color: white;
            padding: 40px 20px;
            margin-bottom: 30px;
        }}
        
        header h1 {{ font-size: 2.5em; margin-bottom: 10px; }}
        header .subtitle {{ font-size: 1.1em; opacity: 0.9; }}
        
        .grade-badge {{
            display: inline-block;
            font-size: 3em;
            font-weight: bold;
            padding: 15px 30px;
            border-radius: 15px;
            margin-left: 30px;
        }}
        
        .grade-A {{ background: #c6f6d5; color: #276749; }}
        .grade-B {{ background: #9ae6b4; color: #276749; }}
        .grade-C {{ background: #fefcbf; color: #975a16; }}
        .grade-D {{ background: #fed7aa; color: #c05621; }}
        .grade-F {{ background: #fed7d7; color: #c53030; }}
        
        .summary-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }}
        
        .stat-card {{
            background: white;
            padding: 25px;
            border-radius: 12px;
            text-align: center;
            box-shadow: 0 2px 10px rgba(0,0,0,0.08);
            border-left: 4px solid var(--accent);
        }}
        
        .stat-card .value {{
            font-size: 2.2em;
            font-weight: bold;
            color: var(--primary);
        }}
        
        .stat-card .label {{
            color: #666;
            font-size: 0.9em;
            margin-top: 5px;
        }}
        
        .stat-card.pass {{ border-left-color: var(--pass); }}
        .stat-card.fail {{ border-left-color: var(--fail); }}
        .stat-card.warning {{ border-left-color: var(--warning); }}
        
        .section {{
            background: white;
            border-radius: 12px;
            padding: 30px;
            margin-bottom: 30px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.08);
        }}
        
        .section h2 {{
            color: var(--primary);
            border-bottom: 3px solid var(--accent);
            padding-bottom: 10px;
            margin-bottom: 20px;
            display: flex;
            align-items: center;
            gap: 10px;
        }}
        
        .section h2::before {{
            font-size: 1.2em;
        }}
        
        .plot-container {{
            width: 100%;
            min-height: 400px;
            margin: 20px 0;
            border: 1px solid #e2e8f0;
            border-radius: 8px;
            overflow: hidden;
        }}
        
        .plot-container iframe {{
            width: 100%;
            height: 500px;
            border: none;
        }}
        
        .test-table {{
            width: 100%;
            border-collapse: collapse;
            margin: 20px 0;
        }}
        
        .test-table th {{
            background: var(--primary);
            color: white;
            padding: 12px 15px;
            text-align: left;
            font-weight: 500;
        }}
        
        .test-table td {{
            padding: 12px 15px;
            border-bottom: 1px solid #e2e8f0;
        }}
        
        .test-table tr:hover {{ background: #f7fafc; }}
        
        .badge {{
            display: inline-block;
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 0.85em;
            font-weight: 500;
        }}
        
        .badge-pass {{ background: #c6f6d5; color: #276749; }}
        .badge-fail {{ background: #fed7d7; color: #c53030; }}
        .badge-warning {{ background: #fefcbf; color: #975a16; }}
        
        .recommendations {{
            list-style: none;
            padding: 0;
        }}
        
        .recommendations li {{
            padding: 15px;
            margin: 10px 0;
            background: #f7fafc;
            border-left: 4px solid var(--accent);
            border-radius: 0 8px 8px 0;
        }}
        
        .recommendations li.critical {{
            border-left-color: var(--fail);
            background: #fff5f5;
        }}
        
        .tabs {{
            display: flex;
            border-bottom: 2px solid #e2e8f0;
            margin-bottom: 20px;
        }}
        
        .tab {{
            padding: 12px 24px;
            cursor: pointer;
            border: none;
            background: none;
            font-size: 1em;
            color: #666;
            border-bottom: 3px solid transparent;
            margin-bottom: -2px;
            transition: all 0.2s;
        }}
        
        .tab:hover {{ color: var(--primary); }}
        .tab.active {{
            color: var(--primary);
            border-bottom-color: var(--accent);
            font-weight: 500;
        }}
        
        .tab-content {{ display: none; }}
        .tab-content.active {{ display: block; }}
        
        footer {{
            text-align: center;
            padding: 30px;
            color: #666;
            font-size: 0.9em;
            border-top: 1px solid #e2e8f0;
            margin-top: 40px;
        }}
        
        @media print {{
            .tabs {{ display: none; }}
            .tab-content {{ display: block !important; page-break-inside: avoid; }}
            .plot-container {{ height: auto; }}
        }}
    </style>
</head>
<body>
    <header>
        <div class="container">
            <div style="display: flex; align-items: center; justify-content: space-between;">
                <div>
                    <h1>📊 Library Diagnostics Report</h1>
                    <div class="subtitle">
                        {library_path}<br>
                        Generated: {timestamp}
                    </div>
                </div>
                <div class="grade-badge grade-{grade}">{grade}</div>
            </div>
        </div>
    </header>
    
    <div class="container">
        <!-- Executive Summary -->
        <section class="section">
            <h2>📋 Executive Summary</h2>
            
            <div class="summary-grid">
                <div class="stat-card {overall_class}">
                    <div class="value">{overall_score:.0f}</div>
                    <div class="label">Overall Score</div>
                </div>
                <div class="stat-card {severity_class}">
                    <div class="value">{severity_score:.0f}</div>
                    <div class="label">Severity</div>
                </div>
                <div class="stat-card {semantic_class}">
                    <div class="value">{semantic_score:.0f}</div>
                    <div class="label">Semantic</div>
                </div>
                <div class="stat-card {cause_class}">
                    <div class="value">{cause_score:.0f}</div>
                    <div class="label">Cause Dist</div>
                </div>
                <div class="stat-card {lob_class}">
                    <div class="value">{lob_score:.0f}</div>
                    <div class="label">LOB Coverage</div>
                </div>
                <div class="stat-card {coherence_class}">
                    <div class="value">{coherence_score:.0f}</div>
                    <div class="label">Coherence</div>
                </div>
            </div>
            
            <h3>Key Findings</h3>
            <p>{key_findings}</p>
        </section>
        
        <!-- Tabbed Diagnostics -->
        <section class="section">
            <h2>🔬 Detailed Diagnostics</h2>
            
            <div class="tabs">
                <button class="tab active" onclick="showTab('severity')">Severity</button>
                <button class="tab" onclick="showTab('semantic')">Semantic</button>
                <button class="tab" onclick="showTab('cause')">Cause Distribution</button>
                <button class="tab" onclick="showTab('lob')">LOB Coverage</button>
                <button class="tab" onclick="showTab('coherence')">Coherence</button>
            </div>
            
            <!-- Severity Tab -->
            <div id="severity-tab" class="tab-content active">
                <h3>Severity Distribution Analysis</h3>
                {severity_content}
            </div>
            
            <!-- Semantic Tab -->
            <div id="semantic-tab" class="tab-content">
                <h3>Semantic Coverage Analysis</h3>
                {semantic_content}
            </div>
            
            <!-- Cause Tab -->
            <div id="cause-tab" class="tab-content">
                <h3>Cause Category Distribution</h3>
                {cause_content}
            </div>
            
            <!-- LOB Tab -->
            <div id="lob-tab" class="tab-content">
                <h3>Line of Business Coverage</h3>
                {lob_content}
            </div>
            
            <!-- Coherence Tab -->
            <div id="coherence-tab" class="tab-content">
                <h3>Text-Numeric Coherence</h3>
                {coherence_content}
            </div>
        </section>
        
        <!-- Recommendations -->
        <section class="section">
            <h2>💡 Recommendations</h2>
            <ul class="recommendations">
                {recommendations_html}
            </ul>
        </section>
    </div>
    
    <footer>
        <p>Lloyd's Reserve Stress Test Generator | Library Diagnostics Report</p>
        <p>This report is for internal risk management purposes only.</p>
    </footer>
    
    <script>
        function showTab(tabName) {{
            // Hide all tabs
            document.querySelectorAll('.tab-content').forEach(tab => {{
                tab.classList.remove('active');
            }});
            document.querySelectorAll('.tab').forEach(btn => {{
                btn.classList.remove('active');
            }});
            
            // Show selected tab
            document.getElementById(tabName + '-tab').classList.add('active');
            event.target.classList.add('active');
        }}
    </script>
</body>
</html>
"""


SEVERITY_TEMPLATE = """
<div class="plot-container">
    {plot_html}
</div>

<h4>Statistical Test Results</h4>
<table class="test-table">
    <thead>
        <tr>
            <th>Test</th>
            <th>Statistic</th>
            <th>P-Value</th>
            <th>Threshold</th>
            <th>Result</th>
        </tr>
    </thead>
    <tbody>
        <tr>
            <td>Kolmogorov-Smirnov</td>
            <td>{ks_stat:.4f}</td>
            <td>{ks_pval:.4f}</td>
            <td>p ≥ 0.05</td>
            <td><span class="badge {ks_badge}">{ks_result}</span></td>
        </tr>
        <tr>
            <td>Bootstrap MMD</td>
            <td>{mmd_stat:.4f}</td>
            <td>{mmd_pval:.4f}</td>
            <td>≤ 0.10 or p ≥ 0.05</td>
            <td><span class="badge {mmd_badge}">{mmd_result}</span></td>
        </tr>
        <tr>
            <td>Jensen-Shannon Divergence</td>
            <td>{js_stat:.4f}</td>
            <td>N/A</td>
            <td>≤ 0.15</td>
            <td><span class="badge {js_badge}">{js_result}</span></td>
        </tr>
    </tbody>
</table>

<h4>Distribution Summary</h4>
<table class="test-table">
    <thead>
        <tr>
            <th>Metric</th>
            <th>Historical (n={hist_n})</th>
            <th>Synthetic (n={synth_n})</th>
        </tr>
    </thead>
    <tbody>
        <tr><td>Mean</td><td>{hist_mean:.2%}</td><td>{synth_mean:.2%}</td></tr>
        <tr><td>Std Dev</td><td>{hist_std:.2%}</td><td>{synth_std:.2%}</td></tr>
        <tr><td>Median</td><td>{hist_median:.2%}</td><td>{synth_median:.2%}</td></tr>
        <tr><td>Min</td><td>{hist_min:.2%}</td><td>{synth_min:.2%}</td></tr>
        <tr><td>Max</td><td>{hist_max:.2%}</td><td>{synth_max:.2%}</td></tr>
        <tr><td>99th Percentile</td><td>{hist_p99:.2%}</td><td>{synth_p99:.2%}</td></tr>
    </tbody>
</table>
"""


SEMANTIC_TEMPLATE = """
<div class="plot-container">
    {plot_html}
</div>

<h4>Coverage Metrics</h4>
<table class="test-table">
    <thead>
        <tr>
            <th>Metric</th>
            <th>Value</th>
            <th>Threshold</th>
            <th>Result</th>
        </tr>
    </thead>
    <tbody>
        <tr>
            <td>Mean Cosine Similarity</td>
            <td>{cosine_sim:.4f}</td>
            <td>≥ 0.60</td>
            <td><span class="badge {cosine_badge}">{cosine_result}</span></td>
        </tr>
        <tr>
            <td>Bootstrap MMD</td>
            <td>{mmd_stat:.4f} (p={mmd_pval:.4f})</td>
            <td>≤ 0.10 or p ≥ 0.05</td>
            <td><span class="badge {mmd_badge}">{mmd_result}</span></td>
        </tr>
        <tr>
            <td>Cluster Coverage</td>
            <td>{cluster_cov:.1%}</td>
            <td>≥ 80%</td>
            <td><span class="badge {cluster_badge}">{cluster_result}</span></td>
        </tr>
        <tr>
            <td>Outlier Rate</td>
            <td>{outlier_rate:.1%}</td>
            <td>≤ 20%</td>
            <td><span class="badge {outlier_badge}">{outlier_result}</span></td>
        </tr>
        <tr>
            <td>Diversity Ratio</td>
            <td>{diversity_ratio:.3f}</td>
            <td>0.70 - 1.30</td>
            <td><span class="badge {diversity_badge}">{diversity_result}</span></td>
        </tr>
    </tbody>
</table>

<h4>Interpretation</h4>
<p>{interpretation}</p>
"""


CAUSE_TEMPLATE = """
<div class="plot-container">
    {plot_html}
</div>

<h4>Distribution Analysis</h4>
<table class="test-table">
    <thead>
        <tr>
            <th>Test</th>
            <th>Statistic</th>
            <th>P-Value</th>
            <th>Result</th>
        </tr>
    </thead>
    <tbody>
        <tr>
            <td>Chi-Square Goodness of Fit</td>
            <td>{chi_stat:.4f}</td>
            <td>{chi_pval:.4f}</td>
            <td><span class="badge {chi_badge}">{chi_result}</span></td>
        </tr>
        <tr>
            <td>JS Divergence</td>
            <td>{js_stat:.4f}</td>
            <td>N/A</td>
            <td><span class="badge {js_badge}">{js_result}</span></td>
        </tr>
    </tbody>
</table>

{issues_html}
"""


LOB_TEMPLATE = """
<div class="plot-container">
    {plot_html}
</div>

<h4>Coverage Summary</h4>
<table class="test-table">
    <thead>
        <tr>
            <th>Metric</th>
            <th>Value</th>
        </tr>
    </thead>
    <tbody>
        <tr><td>Historical LOBs</td><td>{hist_lobs}</td></tr>
        <tr><td>Synthetic LOBs</td><td>{synth_lobs}</td></tr>
        <tr><td>Coverage Rate</td><td>{coverage:.1%}</td></tr>
        <tr><td>Missing LOBs</td><td>{missing}</td></tr>
    </tbody>
</table>
"""


COHERENCE_TEMPLATE = """
<h4>Coherence Summary</h4>
<table class="test-table">
    <thead>
        <tr>
            <th>Metric</th>
            <th>Value</th>
            <th>Threshold</th>
            <th>Result</th>
        </tr>
    </thead>
    <tbody>
        <tr>
            <td>Coherence Rate</td>
            <td>{coherence_rate:.1%}</td>
            <td>≥ 70%</td>
            <td><span class="badge {coherence_badge}">{coherence_result}</span></td>
        </tr>
        <tr>
            <td>Coherent Scenarios</td>
            <td>{n_coherent}</td>
            <td>-</td>
            <td>-</td>
        </tr>
        <tr>
            <td>Incoherent Scenarios</td>
            <td>{n_incoherent}</td>
            <td>-</td>
            <td>-</td>
        </tr>
        <tr>
            <td>Mean Z-Score</td>
            <td>{mean_z:.2f}</td>
            <td>-</td>
            <td>-</td>
        </tr>
    </tbody>
</table>

{examples_html}
"""


def generate_diagnostics_report(
    diagnostics_result,
    plot_paths: Dict[str, str],
    output_path: str
) -> str:
    """
    Generate comprehensive HTML diagnostics report.
    
    Args:
        diagnostics_result: LibraryDiagnosticsResult object
        plot_paths: Dict mapping plot names to file paths
        output_path: Output HTML file path
    
    Returns:
        Path to generated report
    """
    results = diagnostics_result
    
    # Score class helper
    def score_class(score):
        if score >= 70:
            return 'pass'
        elif score >= 60:
            return 'warning'
        else:
            return 'fail'
    
    # Badge helper
    def badge(passed):
        return 'badge-pass' if passed else 'badge-fail'
    
    def result_text(passed):
        return '✓ PASS' if passed else '✗ FAIL'
    
    # Generate severity content
    if results.severity:
        sev = results.severity
        severity_content = SEVERITY_TEMPLATE.format(
            plot_html=_embed_plot(plot_paths.get('severity')),
            ks_stat=sev.ks_statistic,
            ks_pval=sev.ks_pvalue,
            ks_badge=badge(sev.ks_pass),
            ks_result=result_text(sev.ks_pass),
            mmd_stat=sev.mmd_statistic,
            mmd_pval=sev.mmd_pvalue,
            mmd_badge=badge(sev.mmd_pass),
            mmd_result=result_text(sev.mmd_pass),
            js_stat=sev.js_divergence,
            js_badge=badge(sev.js_pass),
            js_result=result_text(sev.js_pass),
            hist_n=sev.historical_n,
            synth_n=sev.synthetic_n,
            hist_mean=sev.historical_mean,
            synth_mean=sev.synthetic_mean,
            hist_std=sev.historical_std,
            synth_std=sev.synthetic_std,
            hist_median=sev.historical_median,
            synth_median=sev.synthetic_median,
            hist_min=sev.historical_min,
            synth_min=sev.synthetic_min,
            hist_max=sev.historical_max,
            synth_max=sev.synthetic_max,
            hist_p99=sev.historical_percentiles.get('99', 0),
            synth_p99=sev.synthetic_percentiles.get('99', 0)
        )
    else:
        severity_content = "<p>Severity diagnostics not available.</p>"
    
    # Generate semantic content
    if results.semantic:
        sem = results.semantic
        
        # Interpretation
        interpretation_parts = []
        if sem.cosine_pass:
            interpretation_parts.append("Synthetic narratives are semantically similar to historical ones.")
        else:
            interpretation_parts.append("Synthetic narratives differ significantly from historical ones.")
        
        if sem.cluster_pass:
            interpretation_parts.append(f"Good topic coverage ({sem.cluster_coverage:.0%} of clusters represented).")
        else:
            interpretation_parts.append(f"Some topics are under-represented ({sem.cluster_coverage:.0%} coverage).")
        
        if sem.outlier_pass:
            interpretation_parts.append(f"Low outlier rate ({sem.outlier_rate:.0%}).")
        else:
            interpretation_parts.append(f"High outlier rate ({sem.outlier_rate:.0%}) - many synthetic scenarios are semantic outliers.")
        
        semantic_content = SEMANTIC_TEMPLATE.format(
            plot_html=_embed_plot(plot_paths.get('semantic')),
            cosine_sim=sem.mean_cosine_similarity,
            cosine_badge=badge(sem.cosine_pass),
            cosine_result=result_text(sem.cosine_pass),
            mmd_stat=sem.mmd_statistic,
            mmd_pval=sem.mmd_pvalue,
            mmd_badge=badge(sem.mmd_pass),
            mmd_result=result_text(sem.mmd_pass),
            cluster_cov=sem.cluster_coverage,
            cluster_badge=badge(sem.cluster_pass),
            cluster_result=result_text(sem.cluster_pass),
            outlier_rate=sem.outlier_rate,
            outlier_badge=badge(sem.outlier_pass),
            outlier_result=result_text(sem.outlier_pass),
            diversity_ratio=sem.diversity_ratio,
            diversity_badge=badge(sem.diversity_pass),
            diversity_result=result_text(sem.diversity_pass),
            interpretation=" ".join(interpretation_parts)
        )
    else:
        semantic_content = "<p>Semantic diagnostics not available.</p>"
    
    # Generate cause content
    if results.cause_distribution:
        cause = results.cause_distribution
        
        issues_parts = []
        if cause.missing_categories:
            issues_parts.append(f"<p><strong>Missing categories:</strong> {', '.join(cause.missing_categories)}</p>")
        if cause.over_represented:
            issues_parts.append(f"<p><strong>Over-represented:</strong> {', '.join(cause.over_represented)}</p>")
        if cause.under_represented:
            issues_parts.append(f"<p><strong>Under-represented:</strong> {', '.join(cause.under_represented)}</p>")
        
        cause_content = CAUSE_TEMPLATE.format(
            plot_html=_embed_plot(plot_paths.get('cause')),
            chi_stat=cause.chi_square_statistic,
            chi_pval=cause.chi_square_pvalue,
            chi_badge=badge(cause.chi_square_pvalue >= 0.05),
            chi_result=result_text(cause.chi_square_pvalue >= 0.05),
            js_stat=cause.js_divergence,
            js_badge=badge(cause.js_divergence <= 0.20),
            js_result=result_text(cause.js_divergence <= 0.20),
            issues_html="<h4>Distribution Issues</h4>" + "".join(issues_parts) if issues_parts else ""
        )
    else:
        cause_content = "<p>Cause distribution diagnostics not available.</p>"
    
    # Generate LOB content
    if results.lob_coverage:
        lob = results.lob_coverage
        lob_content = LOB_TEMPLATE.format(
            plot_html=_embed_plot(plot_paths.get('lob')),
            hist_lobs=len(lob.historical_lobs),
            synth_lobs=len(lob.synthetic_lobs),
            coverage=lob.coverage_rate,
            missing=', '.join(lob.missing_lobs) if lob.missing_lobs else 'None'
        )
    else:
        lob_content = "<p>LOB coverage diagnostics not available.</p>"
    
    # Generate coherence content
    if results.coherence:
        coh = results.coherence
        
        # Examples
        if coh.incoherent_examples:
            examples_html = "<h4>Incoherent Examples</h4>"
            for ex in coh.incoherent_examples[:3]:
                examples_html += f"""
                <div style="background: #fff5f5; padding: 15px; margin: 10px 0; border-radius: 8px; border-left: 4px solid #e53e3e;">
                    <strong>Severity:</strong> {ex.get('severity', 0):.1%}<br>
                    <strong>Narrative:</strong> {ex.get('narrative', 'N/A')}<br>
                    <strong>Issue:</strong> {ex.get('reason', 'N/A')}
                </div>
                """
        else:
            examples_html = "<p>No incoherent examples found.</p>"
        
        coherence_content = COHERENCE_TEMPLATE.format(
            coherence_rate=coh.coherence_rate,
            coherence_badge=badge(coh.overall_pass),
            coherence_result=result_text(coh.overall_pass),
            n_coherent=coh.n_coherent,
            n_incoherent=coh.n_incoherent,
            mean_z=coh.mean_z_score,
            examples_html=examples_html
        )
    else:
        coherence_content = "<p>Coherence diagnostics not available.</p>"
    
    # Generate recommendations HTML
    recs_html = ""
    for rec in results.recommendations:
        critical = 'critical' if any(w in rec.lower() for w in ['fail', 'missing', 'high', 'poor', 'low']) else ''
        recs_html += f'<li class="{critical}">{rec}</li>'
    
    # Key findings
    key_findings_parts = []
    if results.severity and results.severity.overall_pass:
        key_findings_parts.append("Severity distribution matches historical data well.")
    elif results.severity:
        key_findings_parts.append("Severity distribution shows significant differences from historical data.")
    
    if results.semantic and results.semantic.overall_pass:
        key_findings_parts.append("Good semantic coverage of historical themes.")
    elif results.semantic:
        key_findings_parts.append("Semantic coverage needs improvement.")
    
    key_findings = " ".join(key_findings_parts) if key_findings_parts else "Analysis complete."
    
    # Generate final report
    html = REPORT_TEMPLATE.format(
        library_path=results.library_path,
        timestamp=results.timestamp,
        grade=results.overall_grade,
        overall_score=results.overall_score,
        severity_score=results.severity_score,
        semantic_score=results.semantic_score,
        cause_score=results.cause_score,
        lob_score=results.lob_score,
        coherence_score=results.coherence_score,
        overall_class=score_class(results.overall_score),
        severity_class=score_class(results.severity_score),
        semantic_class=score_class(results.semantic_score),
        cause_class=score_class(results.cause_score),
        lob_class=score_class(results.lob_score),
        coherence_class=score_class(results.coherence_score),
        key_findings=key_findings,
        severity_content=severity_content,
        semantic_content=semantic_content,
        cause_content=cause_content,
        lob_content=lob_content,
        coherence_content=coherence_content,
        recommendations_html=recs_html
    )
    
    # Write file
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)
    
    logger.info(f"Generated diagnostics report: {output_path}")
    return str(output_path)


def _embed_plot(plot_path: Optional[str]) -> str:
    """Embed a plot file or return placeholder."""
    if plot_path and Path(plot_path).exists():
        # Read the plot HTML and extract just the plotly div
        with open(plot_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # For simplicity, embed as iframe
        return f'<iframe src="{Path(plot_path).name}" style="width:100%; height:500px; border:none;"></iframe>'
    else:
        return '<div style="padding: 50px; text-align: center; color: #666;">Plot not available</div>'


def generate_full_diagnostics_report(
    library_path: str,
    corpus_path: Optional[str] = None,
    output_dir: str = None,
    n_bootstrap: int = 500
) -> str:
    """
    Convenience function to run diagnostics and generate full report.
    
    Args:
        library_path: Path to scenario library
        corpus_path: Path to historical corpus (optional)
        output_dir: Output directory (default: library_dir/diagnostics)
        n_bootstrap: Bootstrap iterations for MMD
    
    Returns:
        Path to generated report
    """
    from library_diagnostics import LibraryDiagnostics
    from diagnostic_visualizer import DiagnosticVisualizer
    
    library_path = Path(library_path)
    
    if output_dir:
        output_dir = Path(output_dir)
    else:
        if library_path.is_file():
            output_dir = library_path.parent / "diagnostics"
        else:
            output_dir = library_path / "diagnostics"
    
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Run diagnostics
    logger.info("Running library diagnostics...")
    diag = LibraryDiagnostics(
        library_path=str(library_path),
        corpus_path=corpus_path,
        n_bootstrap=n_bootstrap
    )
    
    results = diag.run_all_diagnostics()
    
    # Save results JSON
    diag.save_results(results, str(output_dir / "diagnostics_results.json"))
    
    # Generate visualizations
    logger.info("Generating visualizations...")
    viz = DiagnosticVisualizer(
        diagnostics_result=results,
        hist_severities=diag.hist_severities,
        synth_severities=diag.synth_severities,
        hist_embeddings=diag.hist_embeddings,
        synth_embeddings=diag.synth_embeddings
    )
    
    plot_paths = viz.generate_all_plots(str(output_dir))
    
    # Generate HTML report
    logger.info("Generating HTML report...")
    report_path = generate_diagnostics_report(
        diagnostics_result=results,
        plot_paths=plot_paths,
        output_path=str(output_dir / "diagnostics_report.html")
    )
    
    logger.info(f"Full diagnostics report generated: {report_path}")
    
    return report_path


if __name__ == "__main__":
    import argparse
    
    logging.basicConfig(level=logging.INFO)
    
    parser = argparse.ArgumentParser(description="Generate library diagnostics report")
    parser.add_argument("--library", "-l", required=True, help="Path to scenario library")
    parser.add_argument("--corpus", "-c", help="Path to historical corpus")
    parser.add_argument("--output", "-o", help="Output directory")
    parser.add_argument("--bootstrap", "-b", type=int, default=500, help="Bootstrap iterations")
    
    args = parser.parse_args()
    
    report_path = generate_full_diagnostics_report(
        library_path=args.library,
        corpus_path=args.corpus,
        output_dir=args.output,
        n_bootstrap=args.bootstrap
    )
    
    print(f"\nReport generated: {report_path}")
    print(f"Open in browser: file://{Path(report_path).absolute()}")
