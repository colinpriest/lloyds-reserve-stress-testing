"""
Library Diagnostics Visualizations

Creates interactive Plotly visualizations for library diagnostics:
- Severity distribution comparison
- Semantic coverage maps
- Cause category distributions
- LOB coverage analysis
- Statistical test results
"""

import numpy as np
import pandas as pd
from pathlib import Path
from typing import List, Dict, Optional, Any
import json
import logging

try:
    import plotly.graph_objects as go
    import plotly.express as px
    from plotly.subplots import make_subplots
    PLOTLY_AVAILABLE = True
except ImportError:
    PLOTLY_AVAILABLE = False

from sklearn.decomposition import PCA

logger = logging.getLogger(__name__)


class DiagnosticVisualizer:
    """
    Creates visualizations for library diagnostics.
    """
    
    # Color scheme
    COLORS = {
        'historical': '#3182ce',  # Blue
        'synthetic': '#e53e3e',   # Red
        'pass': '#38a169',        # Green
        'fail': '#e53e3e',        # Red
        'warning': '#d69e2e',     # Yellow
        'neutral': '#718096',     # Gray
    }
    
    def __init__(self, diagnostics_result, 
                 hist_severities: np.ndarray = None,
                 synth_severities: np.ndarray = None,
                 hist_embeddings: np.ndarray = None,
                 synth_embeddings: np.ndarray = None):
        """
        Initialize visualizer with diagnostics results and raw data.
        """
        if not PLOTLY_AVAILABLE:
            raise ImportError("Plotly required for visualizations: pip install plotly")
        
        self.results = diagnostics_result
        self.hist_severities = hist_severities
        self.synth_severities = synth_severities
        self.hist_embeddings = hist_embeddings
        self.synth_embeddings = synth_embeddings
    
    def plot_severity_comparison(self, output_path: str = None) -> go.Figure:
        """
        Create severity distribution comparison visualization.
        
        Includes:
        - Overlaid histograms
        - KDE curves
        - Percentile comparison table
        - Statistical test results
        """
        sev = self.results.severity
        
        if sev is None:
            return self._create_placeholder("Severity data not available")
        
        # Create subplots
        fig = make_subplots(
            rows=2, cols=2,
            subplot_titles=(
                'Severity Distribution Comparison',
                'Percentile Comparison',
                'CDF Comparison',
                'Statistical Tests'
            ),
            specs=[
                [{"type": "xy"}, {"type": "xy"}],
                [{"type": "xy"}, {"type": "table"}]
            ],
            vertical_spacing=0.12,
            horizontal_spacing=0.1
        )
        
        # 1. Histogram comparison
        if self.hist_severities is not None and self.synth_severities is not None:
            # Determine common bins
            all_sev = np.concatenate([self.hist_severities, self.synth_severities])
            bins = np.linspace(all_sev.min(), all_sev.max(), 40)
            
            # Historical histogram
            hist_counts, _ = np.histogram(self.hist_severities, bins=bins, density=True)
            bin_centers = (bins[:-1] + bins[1:]) / 2
            
            fig.add_trace(
                go.Bar(
                    x=bin_centers, y=hist_counts,
                    name='Historical',
                    marker_color=self.COLORS['historical'],
                    opacity=0.6,
                    width=(bins[1] - bins[0]) * 0.8
                ),
                row=1, col=1
            )
            
            # Synthetic histogram
            synth_counts, _ = np.histogram(self.synth_severities, bins=bins, density=True)
            
            fig.add_trace(
                go.Bar(
                    x=bin_centers, y=synth_counts,
                    name='Synthetic',
                    marker_color=self.COLORS['synthetic'],
                    opacity=0.6,
                    width=(bins[1] - bins[0]) * 0.8
                ),
                row=1, col=1
            )
        
        # 2. Percentile comparison
        percentiles = ['10', '25', '50', '75', '90', '95', '99']
        hist_pctl = [sev.historical_percentiles.get(p, 0) for p in percentiles]
        synth_pctl = [sev.synthetic_percentiles.get(p, 0) for p in percentiles]
        
        fig.add_trace(
            go.Scatter(
                x=percentiles, y=hist_pctl,
                name='Historical',
                mode='lines+markers',
                line=dict(color=self.COLORS['historical'], width=2),
                marker=dict(size=8)
            ),
            row=1, col=2
        )
        
        fig.add_trace(
            go.Scatter(
                x=percentiles, y=synth_pctl,
                name='Synthetic',
                mode='lines+markers',
                line=dict(color=self.COLORS['synthetic'], width=2),
                marker=dict(size=8)
            ),
            row=1, col=2
        )
        
        # 3. CDF comparison
        if self.hist_severities is not None and self.synth_severities is not None:
            hist_sorted = np.sort(self.hist_severities)
            synth_sorted = np.sort(self.synth_severities)
            
            hist_cdf = np.arange(1, len(hist_sorted) + 1) / len(hist_sorted)
            synth_cdf = np.arange(1, len(synth_sorted) + 1) / len(synth_sorted)
            
            fig.add_trace(
                go.Scatter(
                    x=hist_sorted, y=hist_cdf,
                    name='Historical CDF',
                    mode='lines',
                    line=dict(color=self.COLORS['historical'], width=2)
                ),
                row=2, col=1
            )
            
            fig.add_trace(
                go.Scatter(
                    x=synth_sorted, y=synth_cdf,
                    name='Synthetic CDF',
                    mode='lines',
                    line=dict(color=self.COLORS['synthetic'], width=2)
                ),
                row=2, col=1
            )
        
        # 4. Statistical tests table
        test_data = [
            ['KS Test', f'{sev.ks_statistic:.4f}', f'{sev.ks_pvalue:.4f}', 
             '✓ PASS' if sev.ks_pass else '✗ FAIL'],
            ['MMD', f'{sev.mmd_statistic:.4f}', f'{sev.mmd_pvalue:.4f}',
             '✓ PASS' if sev.mmd_pass else '✗ FAIL'],
            ['JS Divergence', f'{sev.js_divergence:.4f}', 'N/A',
             '✓ PASS' if sev.js_pass else '✗ FAIL'],
        ]
        
        fig.add_trace(
            go.Table(
                header=dict(
                    values=['<b>Test</b>', '<b>Statistic</b>', '<b>P-Value</b>', '<b>Result</b>'],
                    fill_color='#1a365d',
                    font=dict(color='white', size=12),
                    align='center',
                    height=30
                ),
                cells=dict(
                    values=list(zip(*test_data)),
                    fill_color=[['white', 'white', 'white'],
                               ['white', 'white', 'white'],
                               ['white', 'white', 'white'],
                               [self.COLORS['pass'] if 'PASS' in r else self.COLORS['fail'] 
                                for r in [d[3] for d in test_data]]],
                    font=dict(size=11),
                    align='center',
                    height=25
                )
            ),
            row=2, col=2
        )
        
        # Update layout
        fig.update_layout(
            title=dict(
                text=f"<b>Severity Distribution Diagnostics</b><br>"
                     f"<sup>Historical: n={sev.historical_n} | Synthetic: n={sev.synthetic_n}</sup>",
                x=0.5
            ),
            height=700,
            showlegend=True,
            legend=dict(x=0.5, y=1.02, orientation='h', xanchor='center'),
            barmode='overlay'
        )
        
        fig.update_xaxes(title_text="Severity Ratio", row=1, col=1)
        fig.update_yaxes(title_text="Density", row=1, col=1)
        fig.update_xaxes(title_text="Percentile", row=1, col=2)
        fig.update_yaxes(title_text="Severity Ratio", row=1, col=2)
        fig.update_xaxes(title_text="Severity Ratio", row=2, col=1)
        fig.update_yaxes(title_text="Cumulative Probability", row=2, col=1)
        
        if output_path:
            fig.write_html(output_path, include_plotlyjs='cdn')
            logger.info(f"Saved severity comparison to {output_path}")
        
        return fig
    
    def plot_semantic_coverage(self, output_path: str = None) -> go.Figure:
        """
        Create semantic coverage visualization.
        
        Includes:
        - 2D embedding space (PCA)
        - Density contours
        - Outlier highlighting
        - Coverage statistics
        """
        sem = self.results.semantic
        
        if sem is None or self.hist_embeddings is None or self.synth_embeddings is None:
            return self._create_placeholder("Semantic data not available")
        
        # PCA reduction
        pca = PCA(n_components=2)
        hist_2d = pca.fit_transform(self.hist_embeddings)
        synth_2d = pca.transform(self.synth_embeddings)
        
        # Create subplots
        fig = make_subplots(
            rows=2, cols=2,
            subplot_titles=(
                'Embedding Space Coverage',
                'Semantic Metrics',
                'Cluster Distribution',
                'Statistical Tests'
            ),
            specs=[
                [{"type": "xy"}, {"type": "bar"}],
                [{"type": "bar"}, {"type": "table"}]
            ],
            vertical_spacing=0.15,
            horizontal_spacing=0.1
        )
        
        # 1. Embedding scatter
        fig.add_trace(
            go.Scatter(
                x=hist_2d[:, 0], y=hist_2d[:, 1],
                mode='markers',
                name='Historical',
                marker=dict(
                    color=self.COLORS['historical'],
                    size=6,
                    opacity=0.5
                )
            ),
            row=1, col=1
        )
        
        fig.add_trace(
            go.Scatter(
                x=synth_2d[:, 0], y=synth_2d[:, 1],
                mode='markers',
                name='Synthetic',
                marker=dict(
                    color=self.COLORS['synthetic'],
                    size=6,
                    opacity=0.5,
                    symbol='x'
                )
            ),
            row=1, col=1
        )
        
        # Add density contour for historical
        fig.add_trace(
            go.Histogram2dContour(
                x=hist_2d[:, 0], y=hist_2d[:, 1],
                name='Historical Density',
                colorscale='Blues',
                showscale=False,
                contours=dict(coloring='none'),
                line=dict(color=self.COLORS['historical'], width=1),
                opacity=0.5
            ),
            row=1, col=1
        )
        
        # 2. Metrics bar chart
        metrics = [
            ('Cosine Sim', sem.mean_cosine_similarity, sem.cosine_pass, 0.60),
            ('Cluster Cov', sem.cluster_coverage, sem.cluster_pass, 0.80),
            ('1-Outlier', 1 - sem.outlier_rate, sem.outlier_pass, 0.80),
            ('Diversity', min(1, sem.diversity_ratio), sem.diversity_pass, 0.70),
        ]
        
        fig.add_trace(
            go.Bar(
                x=[m[0] for m in metrics],
                y=[m[1] for m in metrics],
                marker_color=[self.COLORS['pass'] if m[2] else self.COLORS['fail'] for m in metrics],
                text=[f'{m[1]:.2f}' for m in metrics],
                textposition='outside',
                name='Score'
            ),
            row=1, col=2
        )
        
        # Add threshold line
        fig.add_hline(y=0.6, line_dash="dash", line_color="gray", row=1, col=2)
        
        # 3. Cluster distribution comparison (placeholder - would need actual cluster data)
        # For now, show diversity comparison
        fig.add_trace(
            go.Bar(
                x=['Historical', 'Synthetic'],
                y=[sem.historical_diversity, sem.synthetic_diversity],
                marker_color=[self.COLORS['historical'], self.COLORS['synthetic']],
                text=[f'{sem.historical_diversity:.3f}', f'{sem.synthetic_diversity:.3f}'],
                textposition='outside',
                name='Diversity'
            ),
            row=2, col=1
        )
        
        # 4. Statistical tests table
        test_data = [
            ['Mean Cosine Sim', f'{sem.mean_cosine_similarity:.4f}', '≥0.60',
             '✓ PASS' if sem.cosine_pass else '✗ FAIL'],
            ['MMD', f'{sem.mmd_statistic:.4f}', '≤0.10',
             '✓ PASS' if sem.mmd_pass else '✗ FAIL'],
            ['MMD P-Value', f'{sem.mmd_pvalue:.4f}', '≥0.05',
             '✓ PASS' if sem.mmd_pvalue >= 0.05 else '✗ FAIL'],
            ['Cluster Coverage', f'{sem.cluster_coverage:.2%}', '≥80%',
             '✓ PASS' if sem.cluster_pass else '✗ FAIL'],
            ['Outlier Rate', f'{sem.outlier_rate:.2%}', '≤20%',
             '✓ PASS' if sem.outlier_pass else '✗ FAIL'],
            ['Diversity Ratio', f'{sem.diversity_ratio:.3f}', '0.70-1.30',
             '✓ PASS' if sem.diversity_pass else '✗ FAIL'],
        ]
        
        fig.add_trace(
            go.Table(
                header=dict(
                    values=['<b>Metric</b>', '<b>Value</b>', '<b>Threshold</b>', '<b>Result</b>'],
                    fill_color='#1a365d',
                    font=dict(color='white', size=11),
                    align='center',
                    height=28
                ),
                cells=dict(
                    values=list(zip(*test_data)),
                    fill_color='white',
                    font=dict(size=10),
                    align='center',
                    height=24
                )
            ),
            row=2, col=2
        )
        
        # Update layout
        overall_status = "✓ PASS" if sem.overall_pass else "✗ FAIL"
        status_color = self.COLORS['pass'] if sem.overall_pass else self.COLORS['fail']
        
        fig.update_layout(
            title=dict(
                text=f"<b>Semantic Coverage Diagnostics</b> "
                     f"<span style='color:{status_color}'>{overall_status}</span>",
                x=0.5
            ),
            height=750,
            showlegend=True,
            legend=dict(x=0.5, y=1.02, orientation='h', xanchor='center')
        )
        
        fig.update_xaxes(title_text="PC1", row=1, col=1)
        fig.update_yaxes(title_text="PC2", row=1, col=1)
        fig.update_yaxes(title_text="Score", row=1, col=2)
        fig.update_yaxes(title_text="Avg Pairwise Distance", row=2, col=1)
        
        if output_path:
            fig.write_html(output_path, include_plotlyjs='cdn')
            logger.info(f"Saved semantic coverage to {output_path}")
        
        return fig
    
    def plot_cause_distribution(self, output_path: str = None) -> go.Figure:
        """
        Create cause category distribution comparison.
        """
        cause = self.results.cause_distribution
        
        if cause is None:
            return self._create_placeholder("Cause distribution data not available")
        
        # Get categories sorted by historical frequency
        categories = sorted(cause.historical_distribution.keys(), 
                           key=lambda x: cause.historical_distribution.get(x, 0),
                           reverse=True)
        
        hist_vals = [cause.historical_distribution.get(c, 0) for c in categories]
        synth_vals = [cause.synthetic_distribution.get(c, 0) for c in categories]
        
        fig = make_subplots(
            rows=1, cols=2,
            subplot_titles=('Distribution Comparison', 'Divergence Analysis'),
            column_widths=[0.6, 0.4]
        )
        
        # Grouped bar chart
        fig.add_trace(
            go.Bar(
                x=categories,
                y=hist_vals,
                name='Historical',
                marker_color=self.COLORS['historical'],
                text=[f'{v:.1%}' for v in hist_vals],
                textposition='outside'
            ),
            row=1, col=1
        )
        
        fig.add_trace(
            go.Bar(
                x=categories,
                y=synth_vals,
                name='Synthetic',
                marker_color=self.COLORS['synthetic'],
                text=[f'{v:.1%}' for v in synth_vals],
                textposition='outside'
            ),
            row=1, col=1
        )
        
        # Divergence lollipop chart
        divergences = [synth_vals[i] - hist_vals[i] for i in range(len(categories))]
        colors = [self.COLORS['pass'] if abs(d) < 0.1 else 
                  (self.COLORS['warning'] if abs(d) < 0.2 else self.COLORS['fail'])
                  for d in divergences]
        
        fig.add_trace(
            go.Scatter(
                x=divergences,
                y=categories,
                mode='markers',
                marker=dict(color=colors, size=12),
                name='Divergence'
            ),
            row=1, col=2
        )
        
        # Add lines to zero
        for i, (d, c) in enumerate(zip(divergences, categories)):
            fig.add_shape(
                type='line',
                x0=0, x1=d, y0=c, y1=c,
                line=dict(color=colors[i], width=2),
                row=1, col=2
            )
        
        # Add zero line
        fig.add_vline(x=0, line_dash="dash", line_color="gray", row=1, col=2)
        
        # Update layout
        status = "✓ PASS" if cause.overall_pass else "✗ FAIL"
        status_color = self.COLORS['pass'] if cause.overall_pass else self.COLORS['fail']
        
        fig.update_layout(
            title=dict(
                text=f"<b>Cause Category Distribution</b> "
                     f"<span style='color:{status_color}'>{status}</span><br>"
                     f"<sup>JS Divergence: {cause.js_divergence:.4f} | "
                     f"Chi² p-value: {cause.chi_square_pvalue:.4f}</sup>",
                x=0.5
            ),
            height=500,
            barmode='group',
            showlegend=True,
            legend=dict(x=0.5, y=1.05, orientation='h', xanchor='center')
        )
        
        fig.update_xaxes(tickangle=45, row=1, col=1)
        fig.update_yaxes(title_text="Proportion", row=1, col=1)
        fig.update_xaxes(title_text="Difference (Synth - Hist)", row=1, col=2)
        
        if output_path:
            fig.write_html(output_path, include_plotlyjs='cdn')
            logger.info(f"Saved cause distribution to {output_path}")
        
        return fig
    
    def plot_lob_coverage(self, output_path: str = None) -> go.Figure:
        """
        Create LOB coverage visualization.
        """
        lob = self.results.lob_coverage
        
        if lob is None:
            return self._create_placeholder("LOB coverage data not available")
        
        # Get all LOBs
        all_lobs = sorted(set(lob.historical_lobs) | set(lob.synthetic_lobs))
        
        hist_counts = [lob.lob_frequency_historical.get(l, 0) for l in all_lobs]
        synth_counts = [lob.lob_frequency_synthetic.get(l, 0) for l in all_lobs]
        
        # Normalize
        hist_total = sum(hist_counts) or 1
        synth_total = sum(synth_counts) or 1
        hist_pct = [c / hist_total for c in hist_counts]
        synth_pct = [c / synth_total for c in synth_counts]
        
        fig = go.Figure()
        
        fig.add_trace(
            go.Bar(
                x=all_lobs,
                y=hist_pct,
                name='Historical',
                marker_color=self.COLORS['historical'],
                text=[f'{p:.1%}' for p in hist_pct],
                textposition='outside'
            )
        )
        
        fig.add_trace(
            go.Bar(
                x=all_lobs,
                y=synth_pct,
                name='Synthetic',
                marker_color=self.COLORS['synthetic'],
                text=[f'{p:.1%}' for p in synth_pct],
                textposition='outside'
            )
        )
        
        # Highlight missing LOBs
        for i, l in enumerate(all_lobs):
            if l in lob.missing_lobs:
                fig.add_annotation(
                    x=l, y=max(hist_pct[i], synth_pct[i]) + 0.05,
                    text="⚠️ MISSING",
                    showarrow=False,
                    font=dict(color=self.COLORS['fail'], size=10)
                )
        
        # Update layout
        status = "✓ PASS" if lob.overall_pass else "✗ FAIL"
        status_color = self.COLORS['pass'] if lob.overall_pass else self.COLORS['fail']
        
        fig.update_layout(
            title=dict(
                text=f"<b>Line of Business Coverage</b> "
                     f"<span style='color:{status_color}'>{status}</span><br>"
                     f"<sup>Coverage: {lob.coverage_rate:.0%} | "
                     f"Missing: {', '.join(lob.missing_lobs) or 'None'}</sup>",
                x=0.5
            ),
            height=450,
            barmode='group',
            xaxis_tickangle=45,
            yaxis_title="Proportion",
            showlegend=True,
            legend=dict(x=0.5, y=1.05, orientation='h', xanchor='center')
        )
        
        if output_path:
            fig.write_html(output_path, include_plotlyjs='cdn')
            logger.info(f"Saved LOB coverage to {output_path}")
        
        return fig
    
    def plot_overall_summary(self, output_path: str = None) -> go.Figure:
        """
        Create overall summary dashboard.
        """
        fig = make_subplots(
            rows=2, cols=2,
            subplot_titles=(
                'Overall Quality Score',
                'Component Scores',
                'Pass/Fail Summary',
                'Recommendations'
            ),
            specs=[
                [{"type": "indicator"}, {"type": "bar"}],
                [{"type": "table"}, {"type": "table"}]
            ],
            vertical_spacing=0.15,
            horizontal_spacing=0.1
        )
        
        # 1. Overall score gauge
        fig.add_trace(
            go.Indicator(
                mode="gauge+number+delta",
                value=self.results.overall_score,
                title={'text': f"Grade: {self.results.overall_grade}"},
                gauge={
                    'axis': {'range': [0, 100]},
                    'bar': {'color': self._score_to_color(self.results.overall_score)},
                    'steps': [
                        {'range': [0, 60], 'color': '#fed7d7'},
                        {'range': [60, 70], 'color': '#fefcbf'},
                        {'range': [70, 80], 'color': '#c6f6d5'},
                        {'range': [80, 100], 'color': '#9ae6b4'}
                    ],
                    'threshold': {
                        'line': {'color': 'black', 'width': 2},
                        'thickness': 0.75,
                        'value': 70
                    }
                }
            ),
            row=1, col=1
        )
        
        # 2. Component scores bar chart
        components = ['Severity', 'Semantic', 'Cause', 'LOB', 'Coherence']
        scores = [
            self.results.severity_score,
            self.results.semantic_score,
            self.results.cause_score,
            self.results.lob_score,
            self.results.coherence_score
        ]
        
        fig.add_trace(
            go.Bar(
                x=components,
                y=scores,
                marker_color=[self._score_to_color(s) for s in scores],
                text=[f'{s:.0f}' for s in scores],
                textposition='outside'
            ),
            row=1, col=2
        )
        
        fig.add_hline(y=70, line_dash="dash", line_color="gray", row=1, col=2,
                     annotation_text="Pass Threshold")
        
        # 3. Pass/fail table
        pass_fail_data = []
        
        if self.results.severity:
            pass_fail_data.extend([
                ['Severity - KS Test', '✓' if self.results.severity.ks_pass else '✗'],
                ['Severity - MMD', '✓' if self.results.severity.mmd_pass else '✗'],
                ['Severity - JS Div', '✓' if self.results.severity.js_pass else '✗'],
            ])
        
        if self.results.semantic:
            pass_fail_data.extend([
                ['Semantic - Cosine', '✓' if self.results.semantic.cosine_pass else '✗'],
                ['Semantic - MMD', '✓' if self.results.semantic.mmd_pass else '✗'],
                ['Semantic - Cluster', '✓' if self.results.semantic.cluster_pass else '✗'],
                ['Semantic - Outlier', '✓' if self.results.semantic.outlier_pass else '✗'],
            ])
        
        if self.results.cause_distribution:
            pass_fail_data.append(
                ['Cause Distribution', '✓' if self.results.cause_distribution.overall_pass else '✗']
            )
        
        if self.results.lob_coverage:
            pass_fail_data.append(
                ['LOB Coverage', '✓' if self.results.lob_coverage.overall_pass else '✗']
            )
        
        if self.results.coherence:
            pass_fail_data.append(
                ['Coherence', '✓' if self.results.coherence.overall_pass else '✗']
            )
        
        fig.add_trace(
            go.Table(
                header=dict(
                    values=['<b>Check</b>', '<b>Status</b>'],
                    fill_color='#1a365d',
                    font=dict(color='white', size=11),
                    align='center'
                ),
                cells=dict(
                    values=list(zip(*pass_fail_data)) if pass_fail_data else [[], []],
                    fill_color=[['white'] * len(pass_fail_data),
                               [self.COLORS['pass'] if '✓' in r[1] else self.COLORS['fail'] 
                                for r in pass_fail_data]],
                    font=dict(size=10),
                    align='center'
                )
            ),
            row=2, col=1
        )
        
        # 4. Recommendations table
        recs = self.results.recommendations[:5]  # Top 5
        
        fig.add_trace(
            go.Table(
                header=dict(
                    values=['<b>Recommendations</b>'],
                    fill_color='#1a365d',
                    font=dict(color='white', size=11),
                    align='left'
                ),
                cells=dict(
                    values=[recs],
                    fill_color='#f7fafc',
                    font=dict(size=10),
                    align='left',
                    height=35
                )
            ),
            row=2, col=2
        )
        
        # Update layout
        fig.update_layout(
            title=dict(
                text=f"<b>Library Diagnostics Summary</b><br>"
                     f"<sup>Generated: {self.results.timestamp}</sup>",
                x=0.5
            ),
            height=800,
            showlegend=False
        )
        
        fig.update_yaxes(title_text="Score (0-100)", row=1, col=2)
        
        if output_path:
            fig.write_html(output_path, include_plotlyjs='cdn')
            logger.info(f"Saved overall summary to {output_path}")
        
        return fig
    
    def _score_to_color(self, score: float) -> str:
        """Convert score to color."""
        if score >= 80:
            return self.COLORS['pass']
        elif score >= 70:
            return '#68d391'  # Light green
        elif score >= 60:
            return self.COLORS['warning']
        else:
            return self.COLORS['fail']
    
    def _create_placeholder(self, message: str) -> go.Figure:
        """Create placeholder figure with message."""
        fig = go.Figure()
        fig.add_annotation(
            x=0.5, y=0.5,
            text=message,
            showarrow=False,
            font=dict(size=16, color='gray'),
            xref='paper', yref='paper'
        )
        fig.update_layout(
            height=300,
            xaxis=dict(visible=False),
            yaxis=dict(visible=False)
        )
        return fig
    
    def generate_all_plots(self, output_dir: str) -> Dict[str, str]:
        """
        Generate all diagnostic plots to output directory.
        
        Returns dict of plot names to file paths.
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        plots = {}
        
        # Summary
        path = str(output_dir / "diagnostics_summary.html")
        self.plot_overall_summary(path)
        plots['summary'] = path
        
        # Severity
        path = str(output_dir / "severity_comparison.html")
        self.plot_severity_comparison(path)
        plots['severity'] = path
        
        # Semantic
        path = str(output_dir / "semantic_coverage.html")
        self.plot_semantic_coverage(path)
        plots['semantic'] = path
        
        # Cause distribution
        path = str(output_dir / "cause_distribution.html")
        self.plot_cause_distribution(path)
        plots['cause'] = path
        
        # LOB coverage
        path = str(output_dir / "lob_coverage.html")
        self.plot_lob_coverage(path)
        plots['lob'] = path
        
        logger.info(f"Generated {len(plots)} diagnostic plots to {output_dir}")
        
        return plots
