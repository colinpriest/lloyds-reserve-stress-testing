"""
Stress Test Pipeline - Dash Interface

A user-friendly interface for building and querying the Lloyd's reserve stress test library.

Usage:
    python app_dash.py
    
Then open http://localhost:8050 in your browser.
"""

import os
import sys
import re
import json
import subprocess
import threading
import queue
import time
import glob
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict

import dash
from dash import dcc, html, Input, Output, State, callback_context
from dash.exceptions import PreventUpdate
import dash_bootstrap_components as dbc

# Try to import tkinter for native file dialogs
try:
    import tkinter as tk
    from tkinter import filedialog
    HAS_TKINTER = True
except ImportError:
    HAS_TKINTER = False
    print("Warning: tkinter not available. File dialogs will use text input only.")


# =============================================================================
# Constants
# =============================================================================

LOBS = [
    "Property", "Casualty", "Marine", "Energy", "Motor", "Aviation",
    "Reinsurance - Property", "Reinsurance - Casualty", "Reinsurance - Specialty",
    "Professional Lines", "Accident & Health", "Cyber"
]

PRESETS = {
    "custom": {},
    "balanced": {"Property": 25, "Casualty": 25, "Marine": 15, "Professional Lines": 15, "Motor": 10, "Cyber": 10},
    "property": {"Property": 50, "Reinsurance - Property": 20, "Casualty": 15, "Marine": 10, "Energy": 5},
    "casualty": {"Casualty": 40, "Professional Lines": 25, "Motor": 20, "Accident & Health": 15},
    "specialty": {"Marine": 25, "Aviation": 20, "Energy": 25, "Cyber": 15, "Professional Lines": 15},
    "reinsurance": {"Reinsurance - Property": 35, "Reinsurance - Casualty": 35, "Reinsurance - Specialty": 30}
}


# =============================================================================
# Path Utilities
# =============================================================================

def get_script_dir() -> Path:
    """Get the directory containing this script."""
    return Path(__file__).parent.resolve()


def get_project_root() -> Path:
    """Get the project root directory."""
    return get_script_dir().parent.parent


def find_newest_library() -> Optional[str]:
    """Find the most recently created stress test library folder."""
    project_root = get_project_root()
    results_dir = project_root / "results"
    
    if not results_dir.exists():
        return None
    
    # Find all stress_test_* directories
    pattern = str(results_dir / "stress_test_*")
    candidates = glob.glob(pattern)
    
    # Filter to those with scenario_library.json
    valid = []
    for path in candidates:
        if (Path(path) / "scenario_library.json").exists():
            valid.append(path)
    
    if not valid:
        # Check for stress_test_v2
        v2_path = results_dir / "stress_test_v2"
        if (v2_path / "scenario_library.json").exists():
            return str(v2_path.relative_to(project_root))
        return None
    
    # Sort by modification time (newest first)
    valid.sort(key=lambda x: os.path.getmtime(x), reverse=True)
    
    # Return relative path
    try:
        return str(Path(valid[0]).relative_to(project_root))
    except ValueError:
        return valid[0]


# =============================================================================
# GPD State Persistence
# =============================================================================

GPD_STATE_FILENAME = "gpd_analysis_state.json"


def compute_data_hash(corpus_path: str) -> Optional[str]:
    """Compute a hash of the historical data to detect changes."""
    import hashlib
    
    try:
        project_root = get_project_root()
        full_path = project_root / corpus_path
        
        if not full_path.exists():
            return None
        
        with open(full_path, 'r') as f:
            data = json.load(f)
        
        # Hash based on number of movements and severity values
        movements = data.get('movements', [])
        severities = sorted([
            m.get('severity_ratio', 0) 
            for m in movements 
            if m.get('severity_ratio')
        ])
        
        hash_input = f"{len(movements)}:{len(severities)}:{sum(severities):.6f}"
        return hashlib.md5(hash_input.encode()).hexdigest()[:12]
        
    except Exception as e:
        print(f"Error computing data hash: {e}")
        return None


def find_gpd_state_file() -> Optional[Path]:
    """Find the most recent GPD state file."""
    project_root = get_project_root()
    results_dir = project_root / "results"
    
    if not results_dir.exists():
        return None
    
    # Check for state file in results directory
    state_path = results_dir / GPD_STATE_FILENAME
    if state_path.exists():
        return state_path
    
    # Check in stress test directories
    pattern = str(results_dir / "stress_test_*" / GPD_STATE_FILENAME)
    candidates = glob.glob(pattern)
    
    if candidates:
        # Return most recent
        candidates.sort(key=lambda x: os.path.getmtime(x), reverse=True)
        return Path(candidates[0])
    
    return None


def load_gpd_state(state_path: Path) -> Optional[Dict]:
    """Load saved GPD state from file."""
    try:
        with open(state_path, 'r') as f:
            state = json.load(f)
        return state
    except Exception as e:
        print(f"Error loading GPD state: {e}")
        return None


def save_gpd_state(
    results: Dict,
    plots: Dict,
    corpus_path: str,
    severity_mode: str,
    output_dir: Optional[str] = None
) -> Optional[Path]:
    """
    Save GPD analysis state for later use.
    
    Args:
        results: GPD diagnostics results dict
        plots: Dict mapping plot names to file paths
        corpus_path: Path to the corpus file used
        severity_mode: Selected severity mode
        output_dir: Optional output directory (default: results/)
        
    Returns:
        Path to saved state file
    """
    project_root = get_project_root()
    
    if output_dir:
        save_dir = project_root / output_dir
    else:
        save_dir = project_root / "results"
    
    save_dir.mkdir(parents=True, exist_ok=True)
    state_path = save_dir / GPD_STATE_FILENAME
    
    # Compute data hash
    data_hash = compute_data_hash(corpus_path)
    
    state = {
        'version': '1.0',
        'saved_at': datetime.now().isoformat(),
        'corpus_path': corpus_path,
        'data_hash': data_hash,
        'severity_mode': severity_mode,
        'results': results,
        'plots': plots,
    }
    
    try:
        with open(state_path, 'w') as f:
            json.dump(state, f, indent=2, default=str)
        return state_path
    except Exception as e:
        print(f"Error saving GPD state: {e}")
        return None


def check_gpd_state_validity(state: Dict, corpus_path: str) -> Dict:
    """
    Check if saved GPD state is still valid for the given corpus.
    
    Returns:
        Dict with 'valid' (bool), 'reason' (str), 'warnings' (list)
    """
    result = {'valid': True, 'reason': '', 'warnings': []}
    
    if not state:
        result['valid'] = False
        result['reason'] = "No saved state found"
        return result
    
    # Check if corpus path matches
    saved_corpus = state.get('corpus_path', '')
    if saved_corpus != corpus_path:
        result['warnings'].append(f"Corpus path changed: {saved_corpus} → {corpus_path}")
    
    # Check data hash
    current_hash = compute_data_hash(corpus_path)
    saved_hash = state.get('data_hash')
    
    if current_hash and saved_hash:
        if current_hash != saved_hash:
            result['valid'] = False
            result['reason'] = "Historical data has changed since GPD was fitted"
            return result
    
    # Check if results exist
    if not state.get('results'):
        result['valid'] = False
        result['reason'] = "No GPD results in saved state"
        return result
    
    # Check timestamp
    saved_at = state.get('saved_at')
    if saved_at:
        try:
            saved_time = datetime.fromisoformat(saved_at)
            age_days = (datetime.now() - saved_time).days
            if age_days > 30:
                result['warnings'].append(f"GPD analysis is {age_days} days old")
        except:
            pass
    
    return result


def open_file_dialog(title: str = "Select File", filetypes: list = None) -> Optional[str]:
    """Open a native file dialog and return selected path."""
    if not HAS_TKINTER:
        return None
    
    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)
    
    if filetypes is None:
        filetypes = [("JSON files", "*.json"), ("All files", "*.*")]
    
    filepath = filedialog.askopenfilename(
        title=title,
        filetypes=filetypes,
        initialdir=str(get_project_root())
    )
    
    root.destroy()
    
    if filepath:
        try:
            return str(Path(filepath).relative_to(get_project_root()))
        except ValueError:
            return filepath
    return None


def open_folder_dialog(title: str = "Select Folder") -> Optional[str]:
    """Open a native folder dialog and return selected path."""
    if not HAS_TKINTER:
        return None
    
    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)
    
    folderpath = filedialog.askdirectory(
        title=title,
        initialdir=str(get_project_root())
    )
    
    root.destroy()
    
    if folderpath:
        try:
            return str(Path(folderpath).relative_to(get_project_root()))
        except ValueError:
            return folderpath
    return None


# =============================================================================
# Process Runner
# =============================================================================

class ProcessRunner:
    """Run subprocess with real-time output capture."""
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self.output_lines = []
        self.return_code = None
        self.running = False
        self._lock = threading.Lock()
    
    def run(self, cmd: List[str], cwd: str = None):
        """Start process in background thread."""
        with self._lock:
            self.output_lines = []
            self.return_code = None
            self.running = True
        
        thread = threading.Thread(target=self._run_process, args=(cmd, cwd))
        thread.daemon = True
        thread.start()
    
    def _run_process(self, cmd: List[str], cwd: str):
        """Run the process and capture output."""
        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                cwd=cwd or str(get_project_root())
            )
            
            for line in iter(process.stdout.readline, ''):
                line = line.rstrip()
                with self._lock:
                    self.output_lines.append(line)
            
            process.stdout.close()
            with self._lock:
                self.return_code = process.wait()
            
        except Exception as e:
            with self._lock:
                self.output_lines.append(f"Error: {str(e)}")
                self.return_code = -1
        
        finally:
            with self._lock:
                self.running = False
    
    def get_output(self) -> str:
        """Get all output as a string."""
        with self._lock:
            return "\n".join(self.output_lines)
    
    def is_running(self) -> bool:
        with self._lock:
            return self.running
    
    def get_return_code(self) -> Optional[int]:
        with self._lock:
            return self.return_code


# Global process runner
runner = ProcessRunner()


# =============================================================================
# Validation
# =============================================================================

def validate_library_size(scenarios_per_anchor: int, target_size: int, n_anchors: int) -> Dict:
    """Validate that the combination of parameters is feasible."""
    if scenarios_per_anchor is None or target_size is None:
        return {'valid': False, 'message': "Please enter valid parameters"}
    
    raw_scenarios = scenarios_per_anchor * n_anchors
    
    if target_size > raw_scenarios:
        return {
            'valid': False,
            'message': f"Target size ({target_size:,}) exceeds raw scenarios ({raw_scenarios:,}). "
                      f"Either increase 'Scenarios per Anchor' to at least {(target_size // n_anchors) + 1}, "
                      f"or reduce 'Target Library Size'."
        }
    
    if target_size < 100:
        return {'valid': False, 'message': "Target library size should be at least 100."}
    
    sample_rate = target_size / raw_scenarios
    if sample_rate < 0.3:
        return {
            'valid': True,
            'message': f"Note: Only {sample_rate:.0%} of generated scenarios will be kept."
        }
    
    return {'valid': True, 'message': f"Will generate {raw_scenarios:,} raw scenarios, sample to {target_size:,}."}


# =============================================================================
# Dash App
# =============================================================================

app = dash.Dash(
    __name__,
    external_stylesheets=[dbc.themes.BOOTSTRAP],
    suppress_callback_exceptions=True
)

app.title = "Lloyd's Stress Test Generator"


# =============================================================================
# Helper Functions
# =============================================================================

def get_lob_id(lob):
    """Convert LOB name to valid HTML id."""
    return f"lob-{lob.lower().replace(' ', '-').replace('&', 'and')}"


def create_path_input(id_prefix: str, label: str, default_value: str, placeholder: str) -> dbc.Row:
    """Create a path input with browse button."""
    return dbc.Row([
        dbc.Col([
            dbc.Label(label, className="fw-bold"),
            dbc.InputGroup([
                dbc.Input(
                    id=f"{id_prefix}-input",
                    value=default_value,
                    placeholder=placeholder,
                    type="text"
                ),
                dbc.Button(
                    "Browse...",
                    id=f"{id_prefix}-browse",
                    color="secondary",
                    outline=True,
                    n_clicks=0
                )
            ])
        ])
    ], className="mb-3")


def create_lob_sliders():
    """Create LOB weight sliders with explicit IDs."""
    rows = []
    for i in range(0, len(LOBS), 3):
        cols = []
        for j in range(3):
            if i + j < len(LOBS):
                lob = LOBS[i + j]
                lob_id = get_lob_id(lob)
                default = PRESETS["balanced"].get(lob, 0)
                cols.append(
                    dbc.Col([
                        dbc.Label(lob, style={'fontSize': '12px'}),
                        dcc.Slider(
                            id=lob_id,
                            min=0,
                            max=100,
                            step=5,
                            value=default,
                            marks={0: '0', 50: '50', 100: '100'},
                            tooltip={'placement': 'bottom', 'always_visible': False}
                        )
                    ], md=4)
                )
        rows.append(dbc.Row(cols, className="mb-2"))
    return html.Div(rows)


# =============================================================================
# Layout
# =============================================================================

def get_data_extraction_status() -> Dict:
    """Get current status of data extraction pipeline."""
    project_root = get_project_root()
    status = {
        'pdfs_downloaded': 0,
        'pdfs_total_expected': 0,
        'syndicates_downloaded': set(),
        'years_available': set(),
        'quality_classified': False,
        'quality_report_date': None,
        'quality_breakdown': {},
        'movements_extracted': 0,
        'extraction_date': None,
        'size_metrics_count': 0,
        'size_metrics_date': None,
        'corpus_movements': 0,
        'corpus_with_severity': 0,
        'corpus_date': None,
        'prepared_movements': 0,
        'prepared_date': None,
    }

    # Check PDFs
    pdf_dir = project_root / "syndicate_reports" / "pdfs"
    if pdf_dir.exists():
        pdfs = list(pdf_dir.glob("syndicate_*.pdf"))
        status['pdfs_downloaded'] = len(pdfs)
        for pdf in pdfs:
            match = re.match(r'syndicate_(\d+)_(\d{4})\.pdf', pdf.name)
            if match:
                status['syndicates_downloaded'].add(int(match.group(1)))
                status['years_available'].add(int(match.group(2)))

    # Check quality report
    quality_path = project_root / "syndicate_reports" / "quality_report.json"
    if quality_path.exists():
        status['quality_classified'] = True
        status['quality_report_date'] = datetime.fromtimestamp(
            quality_path.stat().st_mtime
        ).strftime('%Y-%m-%d %H:%M')
        try:
            with open(quality_path, 'r', encoding='utf-8') as f:
                qdata = json.load(f)
            # Quality breakdown is in summary.by_quality
            status['quality_breakdown'] = qdata.get('summary', {}).get('by_quality', {})
        except:
            pass

    # Check syndicate movements
    movements_path = project_root / "results" / "syndicate" / "standardized_syndicate_movements.json"
    if movements_path.exists():
        status['extraction_date'] = datetime.fromtimestamp(
            movements_path.stat().st_mtime
        ).strftime('%Y-%m-%d %H:%M')
        try:
            with open(movements_path, 'r', encoding='utf-8') as f:
                mdata = json.load(f)
            status['movements_extracted'] = len(mdata.get('movements', []))
        except:
            pass

    # Check size metrics
    size_path = project_root / "size_metrics.json"
    if size_path.exists():
        status['size_metrics_date'] = datetime.fromtimestamp(
            size_path.stat().st_mtime
        ).strftime('%Y-%m-%d %H:%M')
        try:
            with open(size_path, 'r', encoding='utf-8') as f:
                sdata = json.load(f)
            status['size_metrics_count'] = sdata.get('records_with_size_data', 0)
        except:
            pass

    # Check unified corpus
    corpus_path = project_root / "results" / "combined" / "unified_corpus.json"
    if corpus_path.exists():
        status['corpus_date'] = datetime.fromtimestamp(
            corpus_path.stat().st_mtime
        ).strftime('%Y-%m-%d %H:%M')
        try:
            with open(corpus_path, 'r', encoding='utf-8') as f:
                cdata = json.load(f)
            movements = cdata.get('movements', [])
            status['corpus_movements'] = len(movements)
            status['corpus_with_severity'] = sum(
                1 for m in movements if m.get('severity_ratio') is not None
            )
        except:
            pass

    # Check prepared data
    prepared_path = project_root / "results" / "stress_test" / "prepared_data.json"
    if prepared_path.exists():
        status['prepared_date'] = datetime.fromtimestamp(
            prepared_path.stat().st_mtime
        ).strftime('%Y-%m-%d %H:%M')
        try:
            with open(prepared_path, 'r', encoding='utf-8') as f:
                pdata = json.load(f)
            status['prepared_movements'] = len(pdata.get('movements', []))
        except:
            pass

    # Check filtering bias (run diagnostics on corpus)
    status['filtering_bias'] = None
    status['filtering_retention'] = 0
    status['filtering_biased_fields'] = []
    corpus_path = project_root / "results" / "combined" / "unified_corpus.json"
    if corpus_path.exists() and status['corpus_movements'] > 0:
        try:
            from filtering_diagnostics import FilteringDiagnostics
            diag = FilteringDiagnostics(str(corpus_path))
            diag.load_corpus()
            report = diag.generate_report()

            status['filtering_retention'] = report.overall_retention_rate
            status['filtering_biased_fields'] = [
                t.dimension for t in report.bias_tests if t.significant
            ]
            status['filtering_bias'] = {
                'total': report.total_movements,
                'after_filter': report.final_count,
                'retention_pct': round(report.overall_retention_rate * 100, 1),
                'biased_fields': status['filtering_biased_fields'],
                'stages': [
                    {
                        'name': s.stage_name,
                        'input': s.input_count,
                        'output': s.output_count,
                        'dropped': s.dropped_count,
                        'reasons': s.reasons
                    }
                    for s in report.stages
                ],
                'bias_tests': [
                    {
                        'name': t.test_name,
                        'field': t.dimension,
                        'significant': t.significant,
                        'p_value': t.p_value,
                        'interpretation': t.interpretation
                    }
                    for t in report.bias_tests
                ]
            }
        except Exception as e:
            status['filtering_bias'] = {'error': str(e)}

    # Convert sets to counts for JSON serialization
    status['syndicates_count'] = len(status['syndicates_downloaded'])
    status['years_count'] = len(status['years_available'])
    status['syndicates_downloaded'] = sorted(list(status['syndicates_downloaded']))
    status['years_available'] = sorted(list(status['years_available']))

    return status


def create_data_extraction_tab():
    """Create the Data Extraction tab content."""
    return dbc.Container([
        html.H4("📥 Data Extraction Pipeline", className="mt-3 mb-3"),
        html.P("Download syndicate reports, extract reserve movements, and prepare data for stress testing."),

        html.Hr(),

        # Status Cards
        html.H5("📊 Current Status", className="mb-3"),

        dbc.Row([
            # PDF Downloads Status
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("1. PDF Downloads", className="bg-primary text-white"),
                    dbc.CardBody([
                        html.Div(id="extraction-pdf-status", children=[
                            html.P("Loading...", className="text-muted")
                        ])
                    ])
                ], className="h-100")
            ], md=4),

            # Quality Classification Status
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("2. Quality Classification", className="bg-info text-white"),
                    dbc.CardBody([
                        html.Div(id="extraction-quality-status", children=[
                            html.P("Loading...", className="text-muted")
                        ])
                    ])
                ], className="h-100")
            ], md=4),

            # Movement Extraction Status
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("3. Movement Extraction", className="bg-success text-white"),
                    dbc.CardBody([
                        html.Div(id="extraction-movements-status", children=[
                            html.P("Loading...", className="text-muted")
                        ])
                    ])
                ], className="h-100")
            ], md=4),
        ], className="mb-3"),

        dbc.Row([
            # Size Metrics Status
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("4. Size Metrics", className="bg-warning text-dark"),
                    dbc.CardBody([
                        html.Div(id="extraction-size-status", children=[
                            html.P("Loading...", className="text-muted")
                        ])
                    ])
                ], className="h-100")
            ], md=4),

            # Corpus Status
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("5. Unified Corpus", className="bg-secondary text-white"),
                    dbc.CardBody([
                        html.Div(id="extraction-corpus-status", children=[
                            html.P("Loading...", className="text-muted")
                        ])
                    ])
                ], className="h-100")
            ], md=4),

            # Prepared Data Status
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("6. Prepared Data", className="bg-dark text-white"),
                    dbc.CardBody([
                        html.Div(id="extraction-prepared-status", children=[
                            html.P("Loading...", className="text-muted")
                        ])
                    ])
                ], className="h-100")
            ], md=4),
        ], className="mb-3"),

        # Filtering Bias Row
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("7. Data Filtering Pipeline", className="bg-danger text-white"),
                    dbc.CardBody([
                        html.Div(id="extraction-bias-status", children=[
                            html.P("Loading...", className="text-muted")
                        ])
                    ])
                ], className="h-100")
            ], md=6),

            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("Severity Data Bias Tests", className="bg-light"),
                    dbc.CardBody([
                        html.P("Tests if severity data filter introduces systematic bias:", className="text-muted small mb-2"),
                        html.Div(id="extraction-bias-details", children=[
                            html.P("Run filtering diagnostics to see bias tests", className="text-muted small")
                        ]),
                        dbc.Button(
                            "Generate Full Report",
                            id="extraction-bias-report-btn",
                            color="outline-danger",
                            size="sm",
                            className="mt-2"
                        )
                    ])
                ], className="h-100")
            ], md=6),
        ], className="mb-4"),

        # Refresh Status Button
        dbc.Button(
            "🔄 Refresh Status",
            id="extraction-refresh-btn",
            color="outline-secondary",
            size="sm",
            className="mb-4"
        ),

        html.Hr(),

        # Action Buttons
        html.H5("🚀 Actions", className="mb-3"),

        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        html.H6("Download Syndicate Reports"),
                        html.P("Fetch new/missing PDF reports from Lloyd's website.",
                               className="text-muted small"),
                        dbc.Button(
                            "📥 Download Reports",
                            id="extraction-download-btn",
                            color="primary",
                            className="w-100"
                        )
                    ])
                ])
            ], md=4),

            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        html.H6("Extract All Details"),
                        html.P("Run quality classification + ChatGPT extraction + size metrics.",
                               className="text-muted small"),
                        dbc.Button(
                            "🔍 Extract Details",
                            id="extraction-extract-btn",
                            color="info",
                            className="w-100"
                        )
                    ])
                ])
            ], md=4),

            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        html.H6("Merge & Prepare Data"),
                        html.P("Merge corpus with size metrics and prepare for generation.",
                               className="text-muted small"),
                        dbc.Button(
                            "🔗 Merge & Prepare",
                            id="extraction-merge-btn",
                            color="success",
                            className="w-100"
                        )
                    ])
                ])
            ], md=4),
        ], className="mb-4"),

        # Individual Step Buttons (collapsible)
        dbc.Accordion([
            dbc.AccordionItem([
                html.P("Run individual pipeline steps:", className="mb-3"),
                dbc.Row([
                    dbc.Col([
                        dbc.Button("1. Quality Classification Only", id="extraction-quality-btn",
                                  color="outline-info", size="sm", className="w-100 mb-2")
                    ], md=3),
                    dbc.Col([
                        dbc.Button("2. ChatGPT Extraction Only", id="extraction-chatgpt-btn",
                                  color="outline-info", size="sm", className="w-100 mb-2")
                    ], md=3),
                    dbc.Col([
                        dbc.Button("3. Size Metrics Only", id="extraction-sizemetrics-btn",
                                  color="outline-warning", size="sm", className="w-100 mb-2")
                    ], md=3),
                    dbc.Col([
                        dbc.Button("4. Corpus Merge Only", id="extraction-corpusmerge-btn",
                                  color="outline-secondary", size="sm", className="w-100 mb-2")
                    ], md=3),
                ]),
            ], title="Advanced: Individual Steps"),
        ], className="mb-4", start_collapsed=True),

        html.Hr(),

        # Console Output
        html.H5("📺 Console Output", className="mb-2"),
        html.Pre(
            id="extraction-console",
            children="Click an action button to start...",
            style={
                'width': '100%',
                'height': '400px',
                'overflowY': 'auto',
                'fontFamily': 'Consolas, monospace',
                'fontSize': '12px',
                'backgroundColor': '#1e1e1e',
                'color': '#d4d4d4',
                'padding': '10px',
                'borderRadius': '5px',
                'whiteSpace': 'pre-wrap',
                'wordWrap': 'break-word'
            }
        ),

        # Interval for updating console and status
        dcc.Interval(
            id="extraction-interval",
            interval=500,
            disabled=True
        ),

        # Stores
        dcc.Store(id="extraction-running-store", data=False),
        dcc.Store(id="extraction-output-store", data=""),
        dcc.Store(id="extraction-status-store", data={}),

    ], fluid=True)


def create_build_tab():
    """Create the Build Library tab content."""
    return dbc.Container([
        html.H4("🏗️ Build Scenario Library", className="mt-3 mb-3"),
        html.P("Generate a library of synthetic stress scenarios from historical Lloyd's data."),
        
        html.Hr(),
        
        # Input/Output paths
        html.H5("📁 Paths", className="mb-3"),
        create_path_input(
            "corpus", 
            "Historical Corpus Path",
            "results/combined/unified_corpus.json",
            "Path to unified_corpus.json"
        ),
        create_path_input(
            "output",
            "Output Directory", 
            f"results/stress_test_{datetime.now().strftime('%Y%m%d_%H%M')}",
            "Directory for output files"
        ),
        
        html.Hr(),
        
        # Generation Parameters
        html.H5("⚙️ Generation Parameters", className="mb-3"),
        
        dbc.Row([
            dbc.Col([
                dbc.Label("Scenarios per Anchor"),
                dbc.Input(
                    id="scenarios-per-anchor",
                    type="number",
                    value=10,
                    min=1,
                    max=50,
                    step=1
                ),
                dbc.FormText("Number of scenarios per historical example")
            ], md=4),
            
            dbc.Col([
                dbc.Label("Target Library Size"),
                dbc.Input(
                    id="target-size",
                    type="number",
                    value=2000,
                    min=100,
                    max=10000,
                    step=100
                ),
                dbc.FormText("Final library size after GPD sampling")
            ], md=4),
            
            dbc.Col([
                dbc.Label("Extrapolation Factor"),
                dbc.Input(
                    id="extrapolation-factor",
                    type="number",
                    value=2.5,
                    min=1.0,
                    max=5.0,
                    step=0.5
                ),
                dbc.FormText("Max severity multiplier")
            ], md=4),
        ], className="mb-3"),
        
        # LLM Model selection
        dbc.Row([
            dbc.Col([
                dbc.Label("LLM Model"),
                dbc.Select(
                    id="llm-model",
                    options=[
                        {"label": "gpt-4o-mini (fast, cheap)", "value": "gpt-4o-mini"},
                        {"label": "gpt-4o (better quality, 50x more expensive)", "value": "gpt-4o"},
                    ],
                    value="gpt-4o-mini"
                ),
                dbc.FormText("Model for scenario generation (~$0.50 vs ~$20 per run)")
            ], md=4),
        ], className="mb-3"),
        
        # Validation message
        dbc.Alert(
            id="validation-message",
            color="info",
            is_open=True,
            className="mb-3"
        ),
        
        # GPD info - dynamic based on whether GPD analysis is done
        html.Div(id="build-gpd-info", children=[
            dbc.Alert([
                html.Strong("GPD Analysis: "),
                "Run GPD Diagnostics tab first to configure severity distribution, or build will use auto-detection."
            ], color="info", className="mb-3")
        ]),
        
        # Severity mode (synced from GPD tab)
        dbc.Row([
            dbc.Col([
                dbc.Label("Severity Mode"),
                dbc.Select(
                    id="build-severity-mode",
                    options=[
                        {"label": "Auto (from GPD analysis)", "value": "auto"},
                        {"label": "Constrained (xi < 0.5)", "value": "constrained"},
                        {"label": "Unconstrained", "value": "unconstrained"},
                        {"label": "Unconstrained (max removed)", "value": "unconstrained_no_max"},
                        {"label": "Empirical (capped at historical max)", "value": "empirical"},
                    ],
                    value="auto"
                ),
                dbc.FormText("Severity distribution for sampling")
            ], md=4),
        ], className="mb-3"),
        
        html.Hr(),
        
        # LLM Assessments
        html.H5("🔍 LLM Assessments", className="mb-3"),
        html.P("Optionally have an LLM assess whether generated scenarios are plausible."),
        
        dbc.RadioItems(
            id="assessment-mode",
            options=[
                {"label": "No assessments (fastest)", "value": "none"},
                {"label": "Sample of scenarios (10%)", "value": "sample"},
                {"label": "All scenarios (slow, expensive)", "value": "all"},
                {"label": "Tail scenarios only (≥50yr return period)", "value": "tail"},
            ],
            value="none",
            className="mb-3"
        ),
        
        html.Hr(),
        
        # Run button and status
        dbc.Row([
            dbc.Col([
                dbc.Button(
                    "🚀 Build Library",
                    id="build-button",
                    color="primary",
                    size="lg",
                    className="w-100"
                )
            ], md=4),
            dbc.Col([
                html.Div(id="build-status", className="mt-2")
            ], md=8)
        ], className="mb-3"),
        
        # Console output
        html.H5("📺 Console Output", className="mt-4 mb-2"),
        html.Pre(
            id="build-console",
            children="Click 'Build Library' to start...",
            style={
                'width': '100%',
                'height': '400px',
                'overflowY': 'auto',
                'fontFamily': 'Consolas, monospace',
                'fontSize': '12px',
                'backgroundColor': '#1e1e1e',
                'color': '#d4d4d4',
                'padding': '10px',
                'borderRadius': '5px',
                'whiteSpace': 'pre-wrap',
                'wordWrap': 'break-word'
            }
        ),
        
        # Interval for updating console
        dcc.Interval(
            id="build-interval",
            interval=500,
            disabled=True
        ),
        
        # Store for tracking build state
        dcc.Store(id="build-running-store", data=False),
        dcc.Store(id="build-output-store", data="")
        
    ], fluid=True)


def create_gpd_tab():
    """Create the GPD Diagnostics tab content."""
    return dbc.Container([
        html.H4("📊 GPD Diagnostics", className="mt-3 mb-3"),
        html.P("Fit and validate the GPD model on historical data before generating scenarios."),
        
        html.Hr(),
        
        # Previous GPD fit section
        dbc.Card([
            dbc.CardHeader([
                html.I(className="fas fa-history me-2"),
                "Previous GPD Analysis"
            ]),
            dbc.CardBody([
                html.Div(id="gpd-previous-fit-info", children=[
                    html.P("Checking for saved GPD analysis...", className="text-muted")
                ]),
                dbc.Row([
                    dbc.Col([
                        dbc.Button(
                            "🔄 Load Previous Fit",
                            id="gpd-load-previous-btn",
                            color="info",
                            disabled=True,
                            className="me-2"
                        ),
                        dbc.Button(
                            "💾 Save Current Fit",
                            id="gpd-save-btn",
                            color="success",
                            disabled=True,
                            className="me-2"
                        ),
                    ], md=8),
                    dbc.Col([
                        html.Div(id="gpd-save-status", className="text-muted small")
                    ], md=4),
                ]),
            ])
        ], className="mb-4", id="gpd-previous-fit-card"),
        
        html.Hr(),
        
        # Data source
        html.H5("📁 Historical Data", className="mb-3"),
        create_path_input(
            "gpd-corpus",
            "Corpus Path",
            "results/combined/unified_corpus.json",
            "Path to historical corpus JSON file"
        ),
        
        html.Hr(),
        
        # Threshold settings
        html.H5("⚙️ Threshold Settings", className="mb-3"),
        dbc.Row([
            dbc.Col([
                dbc.Label("Threshold Selection"),
                dbc.RadioItems(
                    id="gpd-threshold-mode",
                    options=[
                        {"label": "Automatic (multi-method consensus)", "value": "auto"},
                        {"label": "Manual override", "value": "manual"},
                    ],
                    value="auto",
                    inline=True
                ),
            ], md=6),
            dbc.Col([
                dbc.Label("Manual Threshold Percentile"),
                dbc.Input(
                    id="gpd-manual-threshold",
                    type="number",
                    value=80,
                    min=50,
                    max=95,
                    step=5,
                    disabled=True
                ),
                dbc.FormText("Only used when manual mode selected")
            ], md=3),
            dbc.Col([
                dbc.Label("Percentile Range (Auto)"),
                html.Div([
                    dbc.Input(
                        id="gpd-range-min",
                        type="number",
                        value=80,
                        min=70,
                        max=95,
                        step=5,
                        style={"width": "80px", "display": "inline-block"}
                    ),
                    html.Span(" to ", className="mx-2"),
                    dbc.Input(
                        id="gpd-range-max",
                        type="number",
                        value=99,
                        min=85,
                        max=99,
                        step=1,
                        style={"width": "80px", "display": "inline-block"}
                    ),
                ]),
                dbc.FormText("Search range for threshold selection (80-99)")
            ], md=3),
        ], className="mb-3"),
        
        # Fit button
        dbc.Row([
            dbc.Col([
                dbc.Button(
                    "📊 Fit GPD & Generate Diagnostics",
                    id="gpd-fit-button",
                    color="primary",
                    size="lg",
                    className="w-100"
                ),
            ], md=4),
            dbc.Col([
                html.Div(id="gpd-fit-status", className="mt-2")
            ], md=8),
        ], className="mb-4"),
        
        html.Hr(),
        
        # Results section (initially hidden)
        html.Div(id="gpd-results-section", children=[
            html.H5("📈 Diagnostic Results", className="mb-3"),
            
            # Summary stats
            dbc.Card([
                dbc.CardHeader("GPD Fit Summary"),
                dbc.CardBody(id="gpd-summary-card")
            ], className="mb-3"),
            
            # Warnings
            html.Div(id="gpd-warnings-div", className="mb-3"),
            
            # Diagnostic plots
            html.H6("Diagnostic Plots", className="mb-2"),
            dbc.Tabs([
                dbc.Tab(label="Summary", tab_id="plot-summary"),
                dbc.Tab(label="Histogram", tab_id="plot-histogram"),
                dbc.Tab(label="Parameter Stability", tab_id="plot-stability"),
                dbc.Tab(label="Mean Residual Life", tab_id="plot-mrl"),
                dbc.Tab(label="QQ Plot", tab_id="plot-qq"),
                dbc.Tab(label="Tail Comparison", tab_id="plot-tail"),
                dbc.Tab(label="Return Levels", tab_id="plot-return"),
                dbc.Tab(label="4-Mode QQ", tab_id="plot-4mode-qq"),
                dbc.Tab(label="4-Mode Return", tab_id="plot-4mode-return"),
                dbc.Tab(label="4-Mode Tail", tab_id="plot-4mode-tail"),
                dbc.Tab(label="Empirical CDF", tab_id="plot-empirical-detail"),
                dbc.Tab(label="4-Mode Summary", tab_id="plot-4mode-summary"),
            ], id="gpd-plot-tabs", active_tab="plot-summary"),
            
            html.Div(id="gpd-plot-display", className="mt-3", style={
                "textAlign": "center",
                "minHeight": "400px"
            }),
            
            html.Hr(),
            
            # Return periods table
            html.H6("Return Period Estimates - All 4 Modes", className="mb-2"),
            html.Div(id="gpd-return-periods-table"),
            
            html.Hr(),
            
            # Severity mode selector
            html.H6("Select Severity Mode for Generation", className="mb-2"),
            dbc.Row([
                dbc.Col([
                    dbc.Select(
                        id="severity-mode-select",
                        options=[
                            {"label": "Auto (Recommended)", "value": "auto"},
                            {"label": "1. Constrained (xi < 0.5)", "value": "constrained"},
                            {"label": "2. Unconstrained", "value": "unconstrained"},
                            {"label": "3. Unconstrained (max removed)", "value": "unconstrained_no_max"},
                            {"label": "4. Empirical (data percentiles)", "value": "empirical"},
                        ],
                        value="auto",
                    ),
                ], md=6),
                dbc.Col([
                    html.Div(id="severity-mode-recommendation", className="text-info")
                ], md=6),
            ], className="mb-3"),
            
            html.Hr(),
            
            # Action buttons
            dbc.Row([
                dbc.Col([
                    dbc.Button(
                        "Accept & Continue to Build",
                        id="gpd-accept-button",
                        color="success",
                        size="lg",
                        className="w-100"
                    ),
                ], md=4),
                dbc.Col([
                    dbc.Button(
                        "Re-fit with Different Settings",
                        id="gpd-refit-button",
                        color="secondary",
                        size="lg",
                        className="w-100"
                    ),
                ], md=4),
            ], className="mb-3"),
        ], style={"display": "none"}),
        
        # Console output
        html.H5("📋 Console Output", className="mt-4 mb-2"),
        html.Pre(
            id="gpd-console",
            children="Click 'Fit GPD' to start...",
            style={
                'height': '300px',
                'overflowY': 'auto',
                'backgroundColor': '#1e1e1e',
                'color': '#d4d4d4',
                'padding': '10px',
                'borderRadius': '5px',
                'whiteSpace': 'pre-wrap',
                'wordWrap': 'break-word'
            }
        ),
        
        # Interval for updating
        dcc.Interval(
            id="gpd-interval",
            interval=500,
            disabled=True
        ),
        
        # Stores
        dcc.Store(id="gpd-running-store", data=False),
        dcc.Store(id="gpd-output-store", data=""),
        dcc.Store(id="gpd-results-store", data=None),
        dcc.Store(id="gpd-plots-store", data=None),
        dcc.Store(id="gpd-saved-state-path", data=None),  # Path to saved GPD state file
        dcc.Store(id="gpd-data-hash", data=None),  # Hash of historical data for change detection
        
    ], fluid=True)


def create_diagnostics_tab():
    """Create the Library Diagnostics tab content."""
    newest_lib = find_newest_library()
    
    return dbc.Container([
        html.H4("🔬 Library Diagnostics", className="mt-3 mb-3"),
        html.P("Validate synthetic scenario library quality against historical data."),
        
        html.Hr(),
        
        # Library selection
        dbc.Row([
            dbc.Col([
                dbc.Label("Scenario Library"),
                dbc.Input(
                    id="diag-library-input",
                    type="text",
                    value=newest_lib or "",
                    placeholder="Path to scenario library directory or JSON"
                )
            ], md=8),
            dbc.Col([
                dbc.Label("Bootstrap Iterations"),
                dbc.Input(
                    id="diag-bootstrap-n",
                    type="number",
                    value=500,
                    min=100,
                    max=2000,
                    step=100
                )
            ], md=4),
        ], className="mb-3"),
        
        # Run diagnostics button
        dbc.Row([
            dbc.Col([
                dbc.Button(
                    "🔬 Run Diagnostics",
                    id="run-diagnostics-btn",
                    color="primary",
                    size="lg",
                    className="w-100"
                )
            ], md=3),
            dbc.Col([
                dbc.Button(
                    "📄 Generate Report",
                    id="generate-diag-report-btn",
                    color="success",
                    size="lg",
                    className="w-100",
                    disabled=True
                )
            ], md=3),
            dbc.Col([
                html.Div(id="diag-status", className="mt-2")
            ], md=6)
        ], className="mb-3"),
        
        html.Hr(),
        
        # Results section
        html.Div(id="diag-results-section", children=[
            # Overall score card
            dbc.Row([
                dbc.Col([
                    dbc.Card([
                        dbc.CardHeader("Overall Score", className="bg-primary text-white"),
                        dbc.CardBody([
                            html.H1(id="diag-overall-score", children="-", 
                                   className="text-center display-3"),
                            html.P(id="diag-overall-grade", children="Grade: -", 
                                  className="text-center text-muted")
                        ])
                    ])
                ], md=3),
                dbc.Col([
                    dbc.Card([
                        dbc.CardHeader("Component Scores"),
                        dbc.CardBody(id="diag-component-scores")
                    ])
                ], md=9),
            ], className="mb-4"),
            
            # Diagnostic visualizations
            dbc.Tabs([
                dbc.Tab([
                    html.Div(id="diag-severity-content", 
                            style={"minHeight": "500px"})
                ], label="📊 Severity", tab_id="diag-severity"),
                
                dbc.Tab([
                    html.Div(id="diag-semantic-content",
                            style={"minHeight": "500px"})
                ], label="🔤 Semantic", tab_id="diag-semantic"),
                
                dbc.Tab([
                    html.Div(id="diag-cause-content",
                            style={"minHeight": "500px"})
                ], label="📋 Cause Distribution", tab_id="diag-cause"),
                
                dbc.Tab([
                    html.Div(id="diag-lob-content",
                            style={"minHeight": "500px"})
                ], label="🏢 LOB Coverage", tab_id="diag-lob"),
                
                dbc.Tab([
                    html.Div(id="diag-coherence-content",
                            style={"minHeight": "400px"})
                ], label="🔗 Coherence", tab_id="diag-coherence"),
            ], id="diag-tabs", active_tab="diag-severity"),
            
            # Recommendations
            html.Hr(),
            html.H5("💡 Recommendations"),
            html.Div(id="diag-recommendations"),
            
        ], style={"display": "none"}),
        
        # Console output (collapsible)
        dbc.Accordion([
            dbc.AccordionItem([
                html.Pre(
                    id="diag-console",
                    children="Click 'Run Diagnostics' to start...",
                    style={
                        'width': '100%',
                        'height': '300px',
                        'overflowY': 'auto',
                        'fontFamily': 'Consolas, monospace',
                        'fontSize': '11px',
                        'backgroundColor': '#1e1e1e',
                        'color': '#d4d4d4',
                        'padding': '10px',
                        'borderRadius': '5px',
                        'whiteSpace': 'pre-wrap',
                        'wordWrap': 'break-word'
                    }
                ),
            ], title="📺 Console Output", item_id="diag-console-item"),
        ], id="diag-console-accordion", start_collapsed=True, className="mt-3"),
        
        # Report status
        html.Div(id="diag-report-status", className="mt-3"),
        
        # Stores
        dcc.Store(id="diag-results-store", data=None),
        dcc.Store(id="diag-running-store", data=False),
        dcc.Interval(id="diag-interval", interval=500, disabled=True),
        
    ], fluid=True)


def create_query_tab():
    """Create the Query Scenarios tab content."""
    newest_lib = find_newest_library()
    
    return dbc.Container([
        html.H4("🔍 Query Stress Scenarios", className="mt-3 mb-3"),
        html.P("Find stress scenarios tailored to your portfolio."),
        
        html.Hr(),
        
        # Library selection
        html.H5("📚 Library", className="mb-3"),
        create_path_input(
            "library",
            "Library Path",
            newest_lib or "results/stress_test_v2",
            "Path to scenario library directory"
        ),
        
        dbc.Alert(
            id="library-status",
            is_open=True,
            className="mb-3"
        ),
        
        html.Hr(),
        
        # Portfolio configuration
        html.H5("💼 Portfolio Configuration", className="mb-3"),
        
        dbc.Row([
            dbc.Col([
                dbc.Label("Total Reserves (£m)"),
                dbc.Input(
                    id="total-reserves",
                    type="number",
                    value=500,
                    min=10,
                    max=10000,
                    step=50
                )
            ], md=3),
            
            dbc.Col([
                dbc.Label("Return Period (years)"),
                dbc.Select(
                    id="return-period",
                    options=[
                        {"label": "10-year", "value": "10"},
                        {"label": "25-year", "value": "25"},
                        {"label": "50-year", "value": "50"},
                        {"label": "100-year", "value": "100"},
                        {"label": "200-year", "value": "200"},
                    ],
                    value="100"
                )
            ], md=3),
            
            dbc.Col([
                dbc.Label("Number of Scenarios"),
                dbc.Input(
                    id="n-scenarios",
                    type="number",
                    value=5,
                    min=1,
                    max=20,
                    step=1
                )
            ], md=3),
            
            dbc.Col([
                dbc.Label("Neighbour Pool"),
                dbc.Input(
                    id="n-neighbours",
                    type="number",
                    value=500,
                    min=100,
                    max=1000,
                    step=100
                )
            ], md=3),
        ], className="mb-3"),
        
        html.Hr(),
        
        # LOB weights
        html.H5("📊 Line of Business Weights", className="mb-3"),
        
        dbc.Row([
            dbc.Col([
                dbc.Label("Preset Portfolio"),
                dbc.Select(
                    id="portfolio-preset",
                    options=[
                        {"label": "Custom", "value": "custom"},
                        {"label": "Balanced", "value": "balanced"},
                        {"label": "Property-Heavy", "value": "property"},
                        {"label": "Casualty-Heavy", "value": "casualty"},
                        {"label": "Specialty", "value": "specialty"},
                        {"label": "Reinsurance", "value": "reinsurance"},
                    ],
                    value="balanced"
                )
            ], md=4),
        ], className="mb-3"),
        
        # LOB sliders
        create_lob_sliders(),
        
        # Portfolio summary
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("Portfolio Summary"),
                    dbc.CardBody(id="portfolio-summary")
                ])
            ], md=6),
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("Concentration Metrics"),
                    dbc.CardBody(id="portfolio-metrics")
                ])
            ], md=6),
        ], className="mb-3 mt-3"),
        
        html.Hr(),
        
        # JIT Assessment option
        html.H5("🔍 Query-Time Assessment", className="mb-3"),
        dbc.Checkbox(
            id="query-jit-assessment",
            label="Run LLM assessment on returned scenarios (adds ~30s per scenario)",
            value=False,
            className="mb-3"
        ),
        
        html.Hr(),
        
        # Run button
        dbc.Row([
            dbc.Col([
                dbc.Button(
                    "🔍 Find Scenarios",
                    id="query-button",
                    color="primary",
                    size="lg",
                    className="w-100"
                )
            ], md=3),
            dbc.Col([
                dbc.Button(
                    "📄 Generate Report",
                    id="generate-report-btn",
                    color="success",
                    size="lg",
                    className="w-100",
                    disabled=True
                )
            ], md=3),
            dbc.Col([
                html.Div(id="query-status", className="mt-2")
            ], md=6)
        ], className="mb-3"),
        
        html.Hr(),
        
        # Scenario Results Section (initially hidden)
        html.Div(id="query-results-section", children=[
            html.H5("📊 Stress Scenarios", className="mb-3"),
            html.Div(id="query-results-cards"),
            
            # Report generation status
            html.Div(id="report-generation-status", className="mt-3"),
        ], style={"display": "none"}),
        
        html.Hr(),
        
        # Console output (collapsible)
        dbc.Accordion([
            dbc.AccordionItem([
                html.Pre(
                    id="query-console",
                    children="Click 'Find Scenarios' to start...",
                    style={
                        'width': '100%',
                        'height': '300px',
                        'overflowY': 'auto',
                        'fontFamily': 'Consolas, monospace',
                        'fontSize': '11px',
                        'backgroundColor': '#1e1e1e',
                        'color': '#d4d4d4',
                        'padding': '10px',
                        'borderRadius': '5px',
                        'whiteSpace': 'pre-wrap',
                        'wordWrap': 'break-word'
                    }
                ),
            ], title="📺 Console Output", item_id="console"),
        ], id="query-console-accordion", start_collapsed=True, className="mt-3"),
        
        dcc.Interval(
            id="query-interval",
            interval=500,
            disabled=True
        ),
        
        dcc.Store(id="query-running-store", data=False),
        dcc.Store(id="query-output-store", data=""),
        dcc.Store(id="query-results-store", data=None),  # Store query results
        dcc.Store(id="query-params-store", data=None),   # Store query parameters
        
    ], fluid=True)


def create_portfolio_analysis_tab():
    """Create the Portfolio Analysis tab for even-year sampling and bootstrap."""
    newest_lib = find_newest_library()

    return dbc.Container([
        html.H4("📈 Portfolio Analysis", className="mt-3 mb-3"),
        html.P("Analyze portfolio return levels with unbiased year sampling and bootstrap confidence intervals."),

        html.Hr(),

        # Library selection
        html.H5("📚 Corpus Source", className="mb-3"),
        create_path_input(
            "analysis-corpus",
            "Historical Corpus Path",
            "results/combined/unified_corpus.json",
            "Path to unified_corpus.json"
        ),

        html.Hr(),

        # Portfolio configuration
        html.H5("💼 Query Portfolio", className="mb-3"),

        dbc.Row([
            dbc.Col([
                dbc.Label("Portfolio Size (£m)"),
                dbc.Input(
                    id="analysis-portfolio-size",
                    type="number",
                    value=500,
                    min=10,
                    max=10000,
                    step=50
                )
            ], md=3),

            dbc.Col([
                dbc.Label("Min Coverage"),
                dbc.Input(
                    id="analysis-min-coverage",
                    type="number",
                    value=0.3,
                    min=0.1,
                    max=0.9,
                    step=0.1
                ),
                dbc.FormText("Minimum LoB coverage fraction")
            ], md=3),
        ], className="mb-3"),

        # LOB weights - reuse preset and sliders
        html.H6("Line of Business Weights", className="mb-2"),
        dbc.Row([
            dbc.Col([
                dbc.Label("Preset Portfolio"),
                dbc.Select(
                    id="analysis-portfolio-preset",
                    options=[
                        {"label": "Custom", "value": "custom"},
                        {"label": "Balanced", "value": "balanced"},
                        {"label": "Property-Heavy", "value": "property"},
                        {"label": "Casualty-Heavy", "value": "casualty"},
                        {"label": "Specialty", "value": "specialty"},
                        {"label": "Reinsurance", "value": "reinsurance"},
                    ],
                    value="balanced"
                )
            ], md=4),
        ], className="mb-3"),

        # Simple weight inputs (more compact than sliders)
        dbc.Row([
            dbc.Col([
                dbc.Label("Property %"),
                dbc.Input(id="analysis-lob-property", type="number", value=25, min=0, max=100, step=5)
            ], md=2),
            dbc.Col([
                dbc.Label("Casualty %"),
                dbc.Input(id="analysis-lob-casualty", type="number", value=25, min=0, max=100, step=5)
            ], md=2),
            dbc.Col([
                dbc.Label("Marine %"),
                dbc.Input(id="analysis-lob-marine", type="number", value=15, min=0, max=100, step=5)
            ], md=2),
            dbc.Col([
                dbc.Label("Prof Lines %"),
                dbc.Input(id="analysis-lob-proflines", type="number", value=15, min=0, max=100, step=5)
            ], md=2),
            dbc.Col([
                dbc.Label("Motor %"),
                dbc.Input(id="analysis-lob-motor", type="number", value=10, min=0, max=100, step=5)
            ], md=2),
            dbc.Col([
                dbc.Label("Cyber %"),
                dbc.Input(id="analysis-lob-cyber", type="number", value=10, min=0, max=100, step=5)
            ], md=2),
        ], className="mb-3"),

        html.Hr(),

        # Analysis mode tabs
        dbc.Tabs([
            # Even-Year Sampling Tab
            dbc.Tab([
                html.Div([
                    html.H5("📊 Even-Year Sampling Analysis", className="mt-3 mb-3"),
                    html.P([
                        "Generate return level estimates with ",
                        html.Strong("equal weight per calendar year"),
                        " to avoid sampling bias from years with better data coverage."
                    ], className="text-muted"),

                    dbc.Row([
                        dbc.Col([
                            dbc.Label("Draws per Year"),
                            dbc.Input(
                                id="even-year-n-per-year",
                                type="number",
                                value=200,
                                min=50,
                                max=1000,
                                step=50
                            ),
                            dbc.FormText("Number of scenario draws per year")
                        ], md=3),

                        dbc.Col([
                            dbc.Label("Min Success per Year"),
                            dbc.Input(
                                id="even-year-min-success",
                                type="number",
                                value=10,
                                min=1,
                                max=100,
                                step=5
                            ),
                            dbc.FormText("Years with fewer valid draws excluded")
                        ], md=3),

                        dbc.Col([
                            dbc.Label("Random Seed"),
                            dbc.Input(
                                id="even-year-seed",
                                type="number",
                                value=42,
                                min=0,
                                step=1
                            ),
                            dbc.FormText("For reproducibility")
                        ], md=3),
                    ], className="mb-3"),

                    # Sampling configuration (advanced)
                    dbc.Accordion([
                        dbc.AccordionItem([
                            dbc.Row([
                                dbc.Col([
                                    dbc.Label("Coverage Cap"),
                                    dbc.Input(id="even-year-coverage-cap", type="number", value=0.9, min=0.5, max=1.0, step=0.1),
                                    dbc.FormText("Max coverage score for selection")
                                ], md=3),
                                dbc.Col([
                                    dbc.Label("Temperature (τ)"),
                                    dbc.Input(id="even-year-tau", type="number", value=0.15, min=0.01, max=1.0, step=0.05),
                                    dbc.FormText("Softmax temperature (lower=greedier)")
                                ], md=3),
                                dbc.Col([
                                    dbc.Label("Top-K Specialists"),
                                    dbc.Input(id="even-year-top-k", type="number", value=5, min=1, max=20, step=1),
                                    dbc.FormText("Candidates for specialist selection")
                                ], md=3),
                            ]),
                        ], title="⚙️ Advanced Sampling Configuration")
                    ], start_collapsed=True, className="mb-3"),

                    # Run button
                    dbc.Row([
                        dbc.Col([
                            dbc.Button(
                                "🔄 Run Even-Year Analysis",
                                id="run-even-year-btn",
                                color="primary",
                                size="lg",
                                className="w-100"
                            )
                        ], md=4),
                        dbc.Col([
                            html.Div(id="even-year-status", className="mt-2")
                        ], md=8)
                    ], className="mb-3"),

                    # Results section
                    html.Div(id="even-year-results-section", children=[
                        html.Hr(),
                        html.H5("📈 Results", className="mb-3"),

                        # Summary cards
                        dbc.Row([
                            dbc.Col([
                                dbc.Card([
                                    dbc.CardHeader("Years Included"),
                                    dbc.CardBody(html.H3(id="even-year-years-count", children="-"))
                                ])
                            ], md=2),
                            dbc.Col([
                                dbc.Card([
                                    dbc.CardHeader("Total Scenarios"),
                                    dbc.CardBody(html.H3(id="even-year-scenarios-count", children="-"))
                                ])
                            ], md=2),
                            dbc.Col([
                                dbc.Card([
                                    dbc.CardHeader("Avg Coverage"),
                                    dbc.CardBody(html.H3(id="even-year-avg-coverage", children="-"))
                                ])
                            ], md=2),
                        ], className="mb-3"),

                        # Return level quantiles table
                        html.H6("Return Level Estimates", className="mb-2"),
                        html.Div(id="even-year-quantiles-table"),

                        # Per-year stats
                        dbc.Accordion([
                            dbc.AccordionItem([
                                html.Div(id="even-year-per-year-stats")
                            ], title="📋 Per-Year Statistics")
                        ], start_collapsed=True, className="mt-3"),

                        # Export button
                        dbc.Row([
                            dbc.Col([
                                dbc.Button(
                                    "💾 Export Results (JSON)",
                                    id="even-year-export-btn",
                                    color="success",
                                    outline=True,
                                    className="mt-3"
                                )
                            ], md=3),
                        ]),
                        html.Div(id="even-year-export-status"),

                    ], style={"display": "none"}),

                ], className="p-3")
            ], label="Even-Year Sampling", tab_id="analysis-even-year"),

            # Year-Block Bootstrap Tab
            dbc.Tab([
                html.Div([
                    html.H5("📊 Year-Block Bootstrap", className="mt-3 mb-3"),
                    html.P([
                        "Quantify ",
                        html.Strong("uncertainty in return-level estimates"),
                        " by resampling calendar years with replacement. Provides confidence intervals."
                    ], className="text-muted"),

                    dbc.Row([
                        dbc.Col([
                            dbc.Label("Bootstrap Replicates (B)"),
                            dbc.Input(
                                id="bootstrap-B",
                                type="number",
                                value=200,
                                min=50,
                                max=1000,
                                step=50
                            ),
                            dbc.FormText("More = narrower CIs, slower")
                        ], md=3),

                        dbc.Col([
                            dbc.Label("Draws per Year"),
                            dbc.Input(
                                id="bootstrap-n-per-year",
                                type="number",
                                value=100,
                                min=50,
                                max=500,
                                step=50
                            ),
                            dbc.FormText("Draws per year per replicate")
                        ], md=3),

                        dbc.Col([
                            dbc.Label("Random Seed"),
                            dbc.Input(
                                id="bootstrap-seed",
                                type="number",
                                value=42,
                                min=0,
                                step=1
                            ),
                            dbc.FormText("For reproducibility")
                        ], md=3),
                    ], className="mb-3"),

                    dbc.Alert([
                        html.Strong("⏱️ Runtime Note: "),
                        "Bootstrap with B=200 and n_per_year=100 typically takes 2-5 minutes depending on portfolio complexity."
                    ], color="info", className="mb-3"),

                    # Run button
                    dbc.Row([
                        dbc.Col([
                            dbc.Button(
                                "🔄 Run Year-Block Bootstrap",
                                id="run-bootstrap-btn",
                                color="primary",
                                size="lg",
                                className="w-100"
                            )
                        ], md=4),
                        dbc.Col([
                            html.Div(id="bootstrap-status", className="mt-2")
                        ], md=8)
                    ], className="mb-3"),

                    # Progress indicator
                    html.Div(id="bootstrap-progress", style={"display": "none"}, children=[
                        dbc.Progress(id="bootstrap-progress-bar", value=0, striped=True, animated=True, className="mb-3"),
                        html.P(id="bootstrap-progress-text", className="text-muted text-center")
                    ]),

                    # Results section
                    html.Div(id="bootstrap-results-section", children=[
                        html.Hr(),
                        html.H5("📈 Bootstrap Results", className="mb-3"),

                        # Summary cards
                        dbc.Row([
                            dbc.Col([
                                dbc.Card([
                                    dbc.CardHeader("Replicates"),
                                    dbc.CardBody(html.H3(id="bootstrap-replicates-count", children="-"))
                                ])
                            ], md=2),
                            dbc.Col([
                                dbc.Card([
                                    dbc.CardHeader("Feasible Years"),
                                    dbc.CardBody(html.H3(id="bootstrap-years-count", children="-"))
                                ])
                            ], md=2),
                        ], className="mb-3"),

                        # Return levels with CIs table
                        html.H6("Return Levels with Confidence Intervals", className="mb-2"),
                        html.Div(id="bootstrap-ci-table"),

                        # CI visualization
                        html.H6("Confidence Interval Visualization", className="mt-4 mb-2"),
                        html.Div(id="bootstrap-ci-chart"),

                        # Bootstrap distribution (optional detail)
                        dbc.Accordion([
                            dbc.AccordionItem([
                                html.Div(id="bootstrap-distribution-detail")
                            ], title="📊 Bootstrap Distribution Details")
                        ], start_collapsed=True, className="mt-3"),

                        # Export buttons
                        dbc.Row([
                            dbc.Col([
                                dbc.Button(
                                    "💾 Export Results (JSON)",
                                    id="bootstrap-export-json-btn",
                                    color="success",
                                    outline=True,
                                    className="mt-3 me-2"
                                ),
                                dbc.Button(
                                    "📄 Export CIs (CSV)",
                                    id="bootstrap-export-csv-btn",
                                    color="info",
                                    outline=True,
                                    className="mt-3"
                                )
                            ], md=6),
                        ]),
                        html.Div(id="bootstrap-export-status"),

                    ], style={"display": "none"}),

                ], className="p-3")
            ], label="Year-Block Bootstrap", tab_id="analysis-bootstrap"),

        ], id="analysis-tabs", active_tab="analysis-even-year"),

        html.Hr(),

        # Console output
        dbc.Accordion([
            dbc.AccordionItem([
                html.Pre(
                    id="analysis-console",
                    children="Select an analysis method and click Run...",
                    style={
                        'width': '100%',
                        'height': '300px',
                        'overflowY': 'auto',
                        'fontFamily': 'Consolas, monospace',
                        'fontSize': '11px',
                        'backgroundColor': '#1e1e1e',
                        'color': '#d4d4d4',
                        'padding': '10px',
                        'borderRadius': '5px',
                        'whiteSpace': 'pre-wrap',
                        'wordWrap': 'break-word'
                    }
                ),
            ], title="📺 Console Output", item_id="analysis-console-item"),
        ], start_collapsed=True, className="mt-3"),

        # Stores
        dcc.Store(id="even-year-results-store", data=None),
        dcc.Store(id="bootstrap-results-store", data=None),
        dcc.Store(id="analysis-running-store", data=False),
        dcc.Interval(id="analysis-interval", interval=1000, disabled=True),

    ], fluid=True)


# Main layout
app.layout = dbc.Container([
    dbc.NavbarSimple(
        brand="Lloyd's Reserve Stress Test Generator",
        brand_href="#",
        color="primary",
        dark=True,
        className="mb-4"
    ),

    dbc.Tabs([
        dbc.Tab(create_data_extraction_tab(), label="📥 Data Extraction", tab_id="extraction"),
        dbc.Tab(create_gpd_tab(), label="📊 GPD Diagnostics", tab_id="gpd"),
        dbc.Tab(create_build_tab(), label="🏗️ Build Library", tab_id="build"),
        dbc.Tab(create_diagnostics_tab(), label="🔬 Library Diagnostics", tab_id="diagnostics"),
        dbc.Tab(create_query_tab(), label="🔍 Query Scenarios", tab_id="query"),
        dbc.Tab(create_portfolio_analysis_tab(), label="📈 Portfolio Analysis", tab_id="analysis"),
    ], id="tabs", active_tab="extraction", persistence=True, persistence_type="session"),
    
    # Hidden store for newest library
    dcc.Store(id="newest-library-store", data=find_newest_library()),
    
], fluid=True)


# =============================================================================
# Callbacks - File Dialogs
# =============================================================================

@app.callback(
    Output("corpus-input", "value"),
    Input("corpus-browse", "n_clicks"),
    State("corpus-input", "value"),
    prevent_initial_call=True
)
def browse_corpus(n_clicks, current_value):
    if n_clicks and n_clicks > 0:
        result = open_file_dialog("Select Historical Corpus", [("JSON files", "*.json")])
        if result:
            return result
    return current_value


@app.callback(
    Output("output-input", "value"),
    Input("output-browse", "n_clicks"),
    State("output-input", "value"),
    prevent_initial_call=True
)
def browse_output(n_clicks, current_value):
    if n_clicks and n_clicks > 0:
        result = open_folder_dialog("Select Output Directory")
        if result:
            return result
    return current_value


@app.callback(
    Output("library-input", "value"),
    Input("library-browse", "n_clicks"),
    Input("newest-library-store", "data"),
    State("library-input", "value"),
    prevent_initial_call=True
)
def browse_library(n_clicks, newest_lib, current_value):
    ctx = callback_context
    if not ctx.triggered:
        raise PreventUpdate
    
    trigger_id = ctx.triggered[0]['prop_id'].split('.')[0]
    
    if trigger_id == "library-browse" and n_clicks and n_clicks > 0:
        result = open_folder_dialog("Select Library Directory")
        if result:
            return result
    elif trigger_id == "newest-library-store" and newest_lib:
        return newest_lib
    
    return current_value


# =============================================================================
# Callbacks - GPD State Persistence
# =============================================================================

@app.callback(
    Output("gpd-previous-fit-info", "children"),
    Output("gpd-load-previous-btn", "disabled"),
    Output("gpd-saved-state-path", "data"),
    Input("gpd-corpus-input", "value"),
    Input("tabs", "active_tab")
)
def check_gpd_saved_state(corpus_path, active_tab):
    """Check for saved GPD state when corpus path changes or tab is selected."""
    if active_tab != "gpd":
        raise PreventUpdate
    
    state_path = find_gpd_state_file()
    
    if not state_path:
        return (
            html.P("No saved GPD analysis found. Run GPD diagnostics to create one.", 
                   className="text-muted mb-0"),
            True,  # Disable load button
            None
        )
    
    # Load and validate state
    state = load_gpd_state(state_path)
    if not state:
        return (
            html.P("Found corrupted GPD state file.", className="text-warning mb-0"),
            True,
            None
        )
    
    validity = check_gpd_state_validity(state, corpus_path)
    
    # Format timestamp
    saved_at = state.get('saved_at', 'Unknown')
    try:
        saved_time = datetime.fromisoformat(saved_at)
        time_str = saved_time.strftime("%Y-%m-%d %H:%M")
    except:
        time_str = saved_at
    
    # Get key info from state
    results = state.get('results', {})
    severity_mode = state.get('severity_mode', 'auto')
    
    # Build info display
    info_items = [
        html.Strong("Saved GPD Analysis Found"),
        html.Br(),
        html.Small(f"Saved: {time_str}", className="text-muted"),
        html.Br(),
        html.Small(f"Severity mode: {severity_mode}", className="text-muted"),
    ]
    
    if validity['valid']:
        info_items.extend([
            html.Br(),
            html.Span("✅ Data unchanged - safe to load", className="text-success")
        ])
        btn_disabled = False
    else:
        info_items.extend([
            html.Br(),
            html.Span(f"⚠️ {validity['reason']}", className="text-warning")
        ])
        btn_disabled = True
    
    if validity['warnings']:
        for warning in validity['warnings']:
            info_items.extend([html.Br(), html.Small(f"⚠️ {warning}", className="text-warning")])
    
    return (
        html.Div(info_items, className="mb-2"),
        btn_disabled,
        str(state_path) if not btn_disabled else None
    )


@app.callback(
    Output("gpd-results-store", "data", allow_duplicate=True),
    Output("gpd-plots-store", "data", allow_duplicate=True),
    Output("gpd-results-section", "style", allow_duplicate=True),
    Output("severity-mode-select", "value", allow_duplicate=True),
    Output("gpd-console", "children", allow_duplicate=True),
    Output("gpd-save-btn", "disabled", allow_duplicate=True),
    Input("gpd-load-previous-btn", "n_clicks"),
    State("gpd-saved-state-path", "data"),
    prevent_initial_call=True
)
def load_previous_gpd_state(n_clicks, state_path):
    """Load previously saved GPD state."""
    if not n_clicks or not state_path:
        raise PreventUpdate
    
    state = load_gpd_state(Path(state_path))
    if not state:
        return (
            dash.no_update, dash.no_update, dash.no_update, 
            dash.no_update, "Error: Could not load saved state", dash.no_update
        )
    
    results = state.get('results')
    plots = state.get('plots', {})
    severity_mode = state.get('severity_mode', 'auto')
    
    console_msg = f"""
=== Loaded Previous GPD Analysis ===
Saved: {state.get('saved_at', 'Unknown')}
Corpus: {state.get('corpus_path', 'Unknown')}
Severity mode: {severity_mode}

GPD fit loaded successfully.
You can now proceed to "Accept & Continue to Build".
"""
    
    return (
        results,
        plots,
        {"display": "block"},  # Show results section
        severity_mode,
        console_msg,
        False  # Enable save button
    )


@app.callback(
    Output("gpd-save-status", "children"),
    Input("gpd-save-btn", "n_clicks"),
    State("gpd-results-store", "data"),
    State("gpd-plots-store", "data"),
    State("gpd-corpus-input", "value"),
    State("severity-mode-select", "value"),
    prevent_initial_call=True
)
def save_current_gpd_state(n_clicks, results, plots, corpus_path, severity_mode):
    """Save current GPD state to file."""
    if not n_clicks or not results:
        raise PreventUpdate
    
    save_path = save_gpd_state(results, plots, corpus_path, severity_mode)
    
    if save_path:
        return html.Span([
            html.I(className="fas fa-check text-success me-1"),
            f"Saved to {save_path.name}"
        ], className="text-success small")
    else:
        return html.Span("Save failed", className="text-danger small")


@app.callback(
    Output("gpd-save-btn", "disabled"),
    Input("gpd-results-store", "data")
)
def enable_save_button(results):
    """Enable save button when GPD results are available."""
    return results is None


# =============================================================================
# Callbacks - Validation
# =============================================================================

@app.callback(
    Output("validation-message", "children"),
    Output("validation-message", "color"),
    Output("build-button", "disabled"),
    Input("scenarios-per-anchor", "value"),
    Input("target-size", "value"),
    State("corpus-input", "value")
)
def validate_params(scenarios_per_anchor, target_size, corpus_path):
    # Get actual anchor count from prepared data - NO HARDCODED DEFAULTS
    n_anchors = None
    prepared_path = get_project_root() / "results" / "stress_test" / "prepared_data.json"

    if prepared_path.exists():
        try:
            with open(prepared_path, 'r') as f:
                pdata = json.load(f)
            n_anchors = len(pdata.get('movements', []))
        except Exception as e:
            logger.warning(f"Failed to read prepared_data.json: {e}")

    if n_anchors is None:
        # Try to count from corpus directly (estimate)
        if corpus_path:
            corpus_full = get_project_root() / corpus_path
            if corpus_full.exists():
                try:
                    with open(corpus_full, 'r') as f:
                        corpus = json.load(f)
                    # Estimate: strengthening movements with severity data
                    movements = corpus.get('movements', [])
                    n_anchors = sum(1 for m in movements
                                   if m.get('direction') == 'strengthening'
                                   and (m.get('severity_ratio') or
                                        (m.get('amount_gbp_m') and m.get('prior_reserves_gbp_m'))))
                except:
                    pass

    if n_anchors is None or n_anchors == 0:
        return {
            'valid': False,
            'message': "Cannot determine anchor count. Prepare data first or check corpus path."
        }

    result = validate_library_size(scenarios_per_anchor, target_size, n_anchors)

    if result['valid']:
        color = "warning" if "Note:" in result['message'] else "success"
        return result['message'], color, False
    else:
        return result['message'], "danger", True


@app.callback(
    Output("library-status", "children"),
    Output("library-status", "color"),
    Output("query-button", "disabled"),
    Input("library-input", "value")
)
def check_library(library_path):
    if not library_path:
        return "Please specify a library path", "warning", True
    
    lib_path = get_project_root() / library_path
    scenario_file = lib_path / "scenario_library.json"
    
    if scenario_file.exists():
        try:
            with open(scenario_file, 'r') as f:
                data = json.load(f)
            n_scenarios = len(data.get('scenarios', []))
            return f"✅ Library found: {n_scenarios:,} scenarios", "success", False
        except Exception as e:
            return f"Warning: Error reading library: {e}", "warning", True
    else:
        return "❌ Library not found. Build a library first or check the path.", "danger", True


# Refresh library path when switching to Query tab
@app.callback(
    Output("newest-library-store", "data"),
    Output("diag-library-input", "value", allow_duplicate=True),
    Input("tabs", "active_tab"),
    prevent_initial_call=True
)
def refresh_library_on_tab_switch(active_tab):
    """Refresh the newest library when switching to Query or Diagnostics tabs."""
    if active_tab in ["query", "diagnostics"]:
        newest = find_newest_library()
        if newest:
            return newest, newest
    raise PreventUpdate


# =============================================================================
# Callbacks - LOB Presets
# =============================================================================

# Create explicit outputs for all LOB sliders
@app.callback(
    [Output(get_lob_id(lob), "value") for lob in LOBS],
    Input("portfolio-preset", "value"),
    prevent_initial_call=True
)
def update_lob_from_preset(preset):
    if preset == "custom":
        raise PreventUpdate
    
    preset_data = PRESETS.get(preset, {})
    return [preset_data.get(lob, 0) for lob in LOBS]


# =============================================================================
# Callbacks - Portfolio Summary
# =============================================================================

@app.callback(
    Output("portfolio-summary", "children"),
    Output("portfolio-metrics", "children"),
    [Input(get_lob_id(lob), "value") for lob in LOBS]
)
def update_portfolio_summary(*values):
    # Build weights dict
    weights = {}
    for lob, val in zip(LOBS, values):
        if val and val > 0:
            weights[lob] = val
    
    # Normalize
    total = sum(weights.values()) if weights else 0
    if total > 0:
        weights_norm = {k: v/total for k, v in weights.items()}
    else:
        weights_norm = {"Property": 1.0}
    
    # Summary list
    summary_items = []
    for lob, w in sorted(weights_norm.items(), key=lambda x: -x[1]):
        summary_items.append(html.Li(f"{lob}: {w:.1%}"))
    
    # Metrics
    hhi = sum(w**2 for w in weights_norm.values())
    n_lobs = len(weights_norm)
    
    if hhi < 0.2:
        concentration_text = "Well diversified"
        concentration_class = "text-success"
    elif hhi < 0.5:
        concentration_text = "Moderately concentrated"
        concentration_class = "text-warning"
    else:
        concentration_text = "Highly concentrated"
        concentration_class = "text-danger"
    
    metrics = [
        html.P(f"Lines of Business: {n_lobs}"),
        html.P(f"HHI (concentration): {hhi:.3f}"),
        html.P(concentration_text, className=f"fw-bold {concentration_class}")
    ]
    
    return html.Ul(summary_items), html.Div(metrics)


# =============================================================================
# Callbacks - GPD Diagnostics
# =============================================================================

# Enable/disable manual threshold input based on mode
@app.callback(
    Output("gpd-manual-threshold", "disabled"),
    Input("gpd-threshold-mode", "value")
)
def toggle_manual_threshold(mode):
    return mode != "manual"


# Start GPD fitting
@app.callback(
    Output("gpd-running-store", "data"),
    Output("gpd-interval", "disabled"),
    Output("gpd-fit-status", "children"),
    Output("gpd-fit-button", "children"),
    Input("gpd-fit-button", "n_clicks"),
    State("gpd-corpus-input", "value"),
    State("gpd-range-min", "value"),
    State("gpd-range-max", "value"),
    State("gpd-running-store", "data"),
    prevent_initial_call=True
)
def start_gpd_fit(n_clicks, corpus, pct_min, pct_max, is_running):
    if not n_clicks or is_running or runner.is_running():
        raise PreventUpdate
    
    # Create temp output directory for GPD diagnostics
    from datetime import datetime
    output_dir = f"results/gpd_diagnostics_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    
    # Run GPD command
    script_path = get_script_dir() / "pipeline_v2.py"
    cmd = [
        sys.executable, str(script_path), "gpd",
        "--corpus", corpus,
        "--output", output_dir,
        "--percentile-min", str(pct_min),
        "--percentile-max", str(pct_max)
    ]
    
    runner.run(cmd)
    
    return True, False, dbc.Spinner(size="sm", children=" Fitting GPD..."), "Fitting..."


# Update GPD console and show results
@app.callback(
    Output("gpd-console", "children"),
    Output("gpd-output-store", "data"),
    Output("gpd-running-store", "data", allow_duplicate=True),
    Output("gpd-interval", "disabled", allow_duplicate=True),
    Output("gpd-fit-status", "children", allow_duplicate=True),
    Output("gpd-fit-button", "children", allow_duplicate=True),
    Output("gpd-results-section", "style"),
    Output("gpd-results-store", "data"),
    Output("gpd-plots-store", "data"),
    Input("gpd-interval", "n_intervals"),
    State("gpd-running-store", "data"),
    prevent_initial_call=True
)
def update_gpd_console(n_intervals, is_running):
    output_text = runner.get_output() or "Waiting for output..."
    
    if runner.is_running():
        return (output_text, output_text, True, False, 
                dbc.Spinner(size="sm", children=" Fitting GPD..."), "Fitting...",
                {"display": "none"}, None, None)
    else:
        return_code = runner.get_return_code()
        
        if return_code == 0:
            # Find the output directory from console output
            output_dir = None
            for line in output_text.split('\n'):
                if 'Output directory:' in line:
                    output_dir = line.split('Output directory:')[1].strip()
                    break
            
            # Load diagnostics and plot paths
            results_data = None
            plots_data = None
            
            if output_dir:
                from pathlib import Path
                output_path = get_project_root() / output_dir
                
                # Load diagnostics JSON
                diag_file = output_path / "gpd_diagnostics.json"
                if diag_file.exists():
                    with open(diag_file) as f:
                        results_data = json.load(f)
                
                # Get plot paths (relative to project root for serving)
                plots_data = {
                    'summary': str(output_path / "gpd_00_summary.png"),
                    'histogram': str(output_path / "gpd_01_histogram.png"),
                    'stability': str(output_path / "gpd_02_parameter_stability.png"),
                    'mrl': str(output_path / "gpd_03_mean_residual_life.png"),
                    'qq': str(output_path / "gpd_04_qq_plot.png"),
                    'tail': str(output_path / "gpd_05_tail_comparison.png"),
                    'return': str(output_path / "gpd_06_return_levels.png"),
                    'output_dir': output_dir
                }
                
                # Add all additional plots if they exist
                additional_plots = {
                    'qq_comparison': output_path / "gpd_07_qq_comparison.png",
                    'tail_comparison_both': output_path / "gpd_08_tail_comparison_both.png",
                    'return_level_comparison': output_path / "gpd_09_return_level_comparison.png",
                    'comparison_summary': output_path / "gpd_10_comparison_summary.png",
                    'qq_4mode': output_path / "gpd_11_qq_4mode.png",
                    'return_periods_4mode': output_path / "gpd_12_return_periods_4mode.png",
                    'tail_4mode': output_path / "gpd_13_tail_4mode.png",
                    'summary_4mode': output_path / "gpd_14_summary_4mode.png",
                    'empirical_detail': output_path / "gpd_15_empirical_detail.png"
                }
                for key, path in additional_plots.items():
                    if path.exists():
                        plots_data[key] = str(path)
            
            return (output_text, output_text, False, True,
                    html.Span("✅ GPD fit complete!", className="text-success fw-bold"),
                    "📊 Fit GPD & Generate Diagnostics",
                    {"display": "block"}, results_data, plots_data)
        else:
            return (output_text, output_text, False, True,
                    html.Span(f"❌ GPD fit failed (code {return_code})", className="text-danger fw-bold"),
                    "📊 Fit GPD & Generate Diagnostics",
                    {"display": "none"}, None, None)


# Update GPD summary card
@app.callback(
    Output("gpd-summary-card", "children"),
    Input("gpd-results-store", "data")
)
def update_gpd_summary(results):
    if not results:
        return "No results yet. Click 'Fit GPD' to generate diagnostics."
    
    # Check if unconstrained differs significantly
    unconstrained_shape = results.get('unconstrained_shape')
    constrained_shape = results.get('final_shape', 0)
    shape_diff = unconstrained_shape - constrained_shape if unconstrained_shape else 0
    significant_diff = abs(shape_diff) > 0.05
    
    # Check if thresholds differ
    unc_threshold = results.get('unconstrained_threshold')
    unc_threshold_pct = results.get('unconstrained_threshold_percentile')
    con_threshold = results.get('selected_threshold', 0)
    threshold_diff = abs(unc_threshold - con_threshold) > 0.01 if unc_threshold else False
    
    return html.Div([
        dbc.Row([
            dbc.Col([
                html.Strong("Data: "),
                html.Span(f"n={results['n_total']}, range=[{results['data_min']:.1%}, {results['data_max']:.1%}]")
            ], md=6),
            dbc.Col([
                html.Strong("Skewness: "),
                html.Span(f"{results['data_skewness']:.2f}"),
                html.Strong(", Kurtosis: ", className="ms-3"),
                html.Span(f"{results['data_kurtosis']:.2f}")
            ], md=6),
        ], className="mb-2"),
        html.Hr(),
        
        # Header row
        dbc.Row([
            dbc.Col(html.Strong(""), md=4),
            dbc.Col(html.Strong("Constrained (xi < 0.5)"), md=4, className="text-center"),
            dbc.Col(html.Strong("Unconstrained"), md=4, className="text-center"),
        ], className="mb-1"),
        
        # Threshold row - now shows both
        dbc.Row([
            dbc.Col(html.Strong("Threshold:"), md=4),
            dbc.Col(html.Span(f"{results['selected_threshold']:.1%} ({results['selected_percentile']:.0f}th)"), 
                    md=4, className="text-center"),
            dbc.Col([
                html.Span(f"{unc_threshold:.1%} ({unc_threshold_pct:.0f}th)" if unc_threshold else "N/A",
                         className="text-warning fw-bold" if threshold_diff else "")
            ], md=4, className="text-center"),
        ], className="mb-1"),
        
        # Exceedances row
        dbc.Row([
            dbc.Col(html.Strong("Exceedances:"), md=4),
            dbc.Col(html.Span(f"{results['final_n_exceedances']}"), md=4, className="text-center"),
            dbc.Col(html.Span(f"{results.get('unconstrained_n_exceedances', 'N/A')}"), md=4, className="text-center"),
        ], className="mb-1"),
        
        # Shape row
        dbc.Row([
            dbc.Col(html.Strong("Shape (xi):"), md=4),
            dbc.Col([
                html.Span(f"{results['final_shape']:.4f}", 
                         className="text-danger fw-bold" if results['final_shape'] >= 0.49 else "")
            ], md=4, className="text-center"),
            dbc.Col([
                html.Span(f"{unconstrained_shape:.4f}" if unconstrained_shape else "N/A",
                         className="text-warning fw-bold" if significant_diff else "")
            ], md=4, className="text-center"),
        ], className="mb-1"),
        
        # Scale row
        dbc.Row([
            dbc.Col(html.Strong("Scale (sigma):"), md=4),
            dbc.Col(html.Span(f"{results['final_scale']:.4f}"), md=4, className="text-center"),
            dbc.Col(html.Span(f"{results.get('unconstrained_scale', 0):.4f}" if results.get('unconstrained_scale') else "N/A"), 
                    md=4, className="text-center"),
        ], className="mb-1"),
        
        # KS p-value row
        dbc.Row([
            dbc.Col(html.Strong("KS p-value:"), md=4),
            dbc.Col([
                html.Span(f"{results['ks_pvalue']:.4f}",
                         className="text-danger fw-bold" if results['ks_pvalue'] < 0.05 else "text-success")
            ], md=4, className="text-center"),
            dbc.Col([
                html.Span(f"{results.get('unconstrained_ks_pvalue', 0):.4f}" if results.get('unconstrained_ks_pvalue') else "N/A",
                         className="text-danger fw-bold" if results.get('unconstrained_ks_pvalue', 1) < 0.05 else "text-success")
            ], md=4, className="text-center"),
        ], className="mb-1"),
        
        # AD statistic row
        dbc.Row([
            dbc.Col(html.Strong("AD statistic:"), md=4),
            dbc.Col([
                html.Span(f"{results['ad_statistic']:.2f}",
                         className="text-danger fw-bold" if results['ad_statistic'] > 2.5 else "")
            ], md=4, className="text-center"),
            dbc.Col([
                html.Span(f"{results.get('unconstrained_ad_statistic', 0):.2f}" if results.get('unconstrained_ad_statistic') else "N/A",
                         className="text-danger fw-bold" if results.get('unconstrained_ad_statistic', 0) > 2.5 else "")
            ], md=4, className="text-center"),
        ], className="mb-1"),
        
        html.Hr(),
        
        # Exceedances
        dbc.Row([
            dbc.Col([
                html.Strong("Exceedances: "),
                html.Span(f"{results['final_n_exceedances']}")
            ], md=6),
            dbc.Col([
                html.Span(
                    f"Shape difference: {shape_diff:+.3f}" if significant_diff else "Constraint not binding",
                    className="text-warning fw-bold" if significant_diff else "text-muted"
                )
            ], md=6),
        ]),
    ])


# Update GPD warnings
@app.callback(
    Output("gpd-warnings-div", "children"),
    Input("gpd-results-store", "data")
)
def update_gpd_warnings(results):
    if not results or not results.get('warnings'):
        return None
    
    return dbc.Alert([
        html.Strong("Warnings:"),
        html.Ul([html.Li(w) for w in results['warnings']])
    ], color="warning")


# Update return periods table with all 4 modes
@app.callback(
    Output("gpd-return-periods-table", "children"),
    Input("gpd-results-store", "data")
)
def update_return_periods_table(results):
    if not results:
        return None
    
    # Get data for all 4 modes
    constrained = results.get('constrained', {})
    unconstrained = results.get('unconstrained', {})
    unconstrained_no_max = results.get('unconstrained_no_max', {})
    rp_data_emp = results.get('empirical_return_periods', {})
    
    # Fallback to legacy fields if new structure not present
    if not constrained:
        constrained = {'return_periods': results.get('return_period_severities', {})}
    if not unconstrained:
        unconstrained = {'return_periods': results.get('unconstrained_return_periods', {})}
    
    rows = []
    for rp in ['10', '25', '50', '100', '200', '500']:
        # Get values from each mode
        emp_val = rp_data_emp.get(rp) if rp_data_emp else None
        con_val = constrained.get('return_periods', {}).get(rp) if constrained else None
        unc_val = unconstrained.get('return_periods', {}).get(rp) if unconstrained else None
        unm_val = unconstrained_no_max.get('return_periods', {}).get(rp) if unconstrained_no_max else None
        
        # Format each value
        emp_str = f"{float(emp_val)*100:.1f}%" if emp_val else "-"
        con_str = f"{float(con_val)*100:.1f}%" if con_val else "-"
        unc_str = f"{float(unc_val)*100:.1f}%" if unc_val else "-"
        unm_str = f"{float(unm_val)*100:.1f}%" if unm_val else "-"
        
        rows.append(html.Tr([
            html.Td(f"{rp}-year"),
            html.Td(emp_str, className="text-primary"),
            html.Td(con_str, className="text-danger"),
            html.Td(unc_str, className="text-success"),
            html.Td(unm_str, className="text-info"),
        ]))
    
    return dbc.Table([
        html.Thead(html.Tr([
            html.Th("Return Period"), 
            html.Th("Empirical", className="text-primary"),
            html.Th("Constrained", className="text-danger"), 
            html.Th("Unconstrained", className="text-success"),
            html.Th("Unc (no max)", className="text-info")
        ])),
        html.Tbody(rows)
    ], bordered=True, hover=True, size="sm", className="w-auto")


# Update severity mode recommendation display
@app.callback(
    Output("severity-mode-recommendation", "children"),
    Input("gpd-results-store", "data")
)
def update_severity_recommendation(results):
    if not results:
        return None
    
    recommended = results.get('recommended_mode', 'constrained')
    reason = results.get('recommendation_reason', '')
    
    return html.Div([
        html.Strong(f"Recommended: {recommended.upper()}"),
        html.Br(),
        html.Small(reason, className="text-muted")
    ])


# Display GPD diagnostic plot based on selected tab
@app.callback(
    Output("gpd-plot-display", "children"),
    Input("gpd-plot-tabs", "active_tab"),
    State("gpd-plots-store", "data")
)
def display_gpd_plot(active_tab, plots_data):
    if not plots_data:
        return html.P("No plots available. Run GPD fitting first.", className="text-muted")
    
    # Map tab to plot file
    tab_to_plot = {
        'plot-summary': 'summary',
        'plot-histogram': 'histogram',
        'plot-stability': 'stability',
        'plot-mrl': 'mrl',
        'plot-qq': 'qq',
        'plot-tail': 'tail',
        'plot-return': 'return',
        'plot-4mode-qq': 'qq_4mode',
        'plot-4mode-return': 'return_periods_4mode',
        'plot-4mode-tail': 'tail_4mode',
        'plot-empirical-detail': 'empirical_detail',
        'plot-4mode-summary': 'summary_4mode',
    }
    
    plot_key = tab_to_plot.get(active_tab, 'summary')
    plot_path = plots_data.get(plot_key)
    
    if not plot_path:
        return html.P("This plot is not available.", className="text-muted")
    
    if plot_path:
        from pathlib import Path
        full_path = get_project_root() / plot_path
        if full_path.exists():
            # Read and encode image
            import base64
            with open(full_path, 'rb') as f:
                encoded = base64.b64encode(f.read()).decode('utf-8')
            return html.Img(
                src=f"data:image/png;base64,{encoded}",
                style={'maxWidth': '100%', 'height': 'auto'}
            )
    
    return html.P(f"Plot not found: {plot_path}", className="text-danger")


# Accept GPD and switch to Build tab
@app.callback(
    Output("tabs", "active_tab", allow_duplicate=True),
    Output("corpus-input", "value", allow_duplicate=True),
    Output("gpd-save-status", "children", allow_duplicate=True),
    Input("gpd-accept-button", "n_clicks"),
    State("gpd-corpus-input", "value"),
    State("gpd-results-store", "data"),
    State("gpd-plots-store", "data"),
    State("severity-mode-select", "value"),
    prevent_initial_call=True
)
def accept_gpd_and_switch(n_clicks, corpus_path, results, plots, severity_mode):
    if not n_clicks:
        raise PreventUpdate
    
    # Auto-save GPD state when accepting
    save_status = ""
    if results:
        save_path = save_gpd_state(results, plots, corpus_path, severity_mode)
        if save_path:
            save_status = html.Span([
                html.I(className="fas fa-check text-success me-1"),
                f"Auto-saved to {save_path.name}"
            ], className="text-success small")
    
    # Switch to build tab and copy corpus path
    return "build", corpus_path, save_status


# Restore GPD console from store
@app.callback(
    Output("gpd-console", "children", allow_duplicate=True),
    Input("tabs", "active_tab"),
    State("gpd-output-store", "data"),
    prevent_initial_call=True
)
def restore_gpd_console(active_tab, stored_output):
    if active_tab == "gpd" and stored_output:
        return stored_output
    raise PreventUpdate


# Sync GPD state to Build tab
@app.callback(
    Output("build-gpd-info", "children"),
    Output("build-severity-mode", "value"),
    Input("tabs", "active_tab"),
    Input("gpd-results-store", "data"),
    State("severity-mode-select", "value")
)
def sync_gpd_to_build(active_tab, gpd_results, severity_mode):
    """Update Build tab with GPD analysis info on tab switch."""
    if active_tab != "build":
        raise PreventUpdate
    
    if gpd_results:
        # GPD analysis is done - show summary
        recommended = gpd_results.get('recommended_mode', 'auto')
        
        # Use selected mode if set, otherwise recommended
        display_mode = severity_mode if severity_mode and severity_mode != 'auto' else recommended
        
        info_content = _build_gpd_info_alert(gpd_results, display_mode, recommended)
        return info_content, severity_mode or "auto"
    else:
        # No GPD analysis - check for saved state
        state_path = find_gpd_state_file()
        if state_path:
            state = load_gpd_state(state_path)
            if state:
                saved_at = state.get('saved_at', 'Unknown')
                try:
                    saved_time = datetime.fromisoformat(saved_at)
                    time_str = saved_time.strftime("%Y-%m-%d %H:%M")
                except:
                    time_str = saved_at
                
                info_content = dbc.Alert([
                    html.Strong("💾 Saved GPD Analysis Available"),
                    html.Br(),
                    html.Small(f"From: {time_str}. Go to GPD Diagnostics tab to load it.", 
                               className="text-muted")
                ], color="info", className="mb-3")
                
                return info_content, state.get('severity_mode', 'auto')
        
        # No GPD analysis at all
        info_content = dbc.Alert([
            html.Strong("GPD Analysis: "),
            "Run GPD Diagnostics tab first to configure severity distribution, or build will use auto-detection."
        ], color="warning", className="mb-3")
        
        return info_content, "auto"


def _build_gpd_info_alert(gpd_results, display_mode, recommended):
    """Build the GPD info alert for the Build tab."""
    if display_mode == 'empirical':
        # Empirical data is at the top level of gpd_results
        data_max = gpd_results.get('data_max', 0)
        n_total = gpd_results.get('n_total', 0)
        
        return dbc.Alert([
            html.Strong("✅ GPD Analysis Loaded"),
            html.Br(),
            html.Small([
                f"Mode: {display_mode} | ",
                f"Historical max: {data_max:.1%} | ",
                f"n={n_total} | ",
                f"Recommended: {recommended}"
            ], className="text-muted")
        ], color="success", className="mb-3")
    else:
        # Get from appropriate GPD mode
        mode_data = gpd_results.get(display_mode, gpd_results.get('constrained', {}))
        if mode_data:
            shape = mode_data.get('shape', 0)
            threshold = mode_data.get('threshold', 0)
            threshold_pct = mode_data.get('threshold_percentile', 0)
        else:
            # Fallback to legacy fields
            shape = gpd_results.get('final_shape', 0)
            threshold = gpd_results.get('selected_threshold', 0)
            threshold_pct = gpd_results.get('selected_percentile', 0)
        
        return dbc.Alert([
            html.Strong("✅ GPD Analysis Loaded"),
            html.Br(),
            html.Small([
                f"Mode: {display_mode} | ",
                f"Threshold: {threshold:.1%} ({threshold_pct:.0f}th pctl) | ",
                f"Shape (ξ): {shape:.4f} | ",
                f"Recommended: {recommended}"
            ], className="text-muted")
        ], color="success", className="mb-3")


# Update info when severity mode changes in Build tab
@app.callback(
    Output("build-gpd-info", "children", allow_duplicate=True),
    Input("build-severity-mode", "value"),
    State("gpd-results-store", "data"),
    prevent_initial_call=True
)
def update_build_info_on_mode_change(severity_mode, gpd_results):
    """Update the GPD info display when user changes severity mode in Build tab."""
    if not gpd_results:
        raise PreventUpdate
    
    recommended = gpd_results.get('recommended_mode', 'auto')
    display_mode = severity_mode if severity_mode and severity_mode != 'auto' else recommended
    
    return _build_gpd_info_alert(gpd_results, display_mode, recommended)


# =============================================================================
# Callbacks - Build Process
# =============================================================================

@app.callback(
    Output("build-running-store", "data"),
    Output("build-interval", "disabled"),
    Output("build-status", "children"),
    Output("build-button", "children"),
    Input("build-button", "n_clicks"),
    State("corpus-input", "value"),
    State("output-input", "value"),
    State("scenarios-per-anchor", "value"),
    State("target-size", "value"),
    State("extrapolation-factor", "value"),
    State("llm-model", "value"),
    State("assessment-mode", "value"),
    State("build-severity-mode", "value"),
    State("build-running-store", "data"),
    prevent_initial_call=True
)
def start_build(n_clicks, corpus, output, scenarios_per_anchor, 
                target_size, extrapolation_factor, llm_model, assessment_mode, 
                severity_mode, is_running):
    if not n_clicks:
        raise PreventUpdate
    
    if is_running or runner.is_running():
        raise PreventUpdate
    
    # Start build process
    script_path = get_script_dir() / "pipeline_v2.py"
    cmd = [
        sys.executable, str(script_path), "build",
        "--corpus", corpus,
        "--output", output,
        "--scenarios-per-anchor", str(scenarios_per_anchor),
        "--extrapolation-factor", str(extrapolation_factor),
        "--target-size", str(target_size),
        "--model", llm_model
    ]
    
    # Add severity mode
    if severity_mode and severity_mode != "auto":
        cmd.extend(["--severity-mode", severity_mode])
    
    # Handle assessment mode
    if assessment_mode == "sample":
        cmd.extend(["--run-assessments", "--assessment-mode", "sample"])
    elif assessment_mode == "all":
        cmd.extend(["--run-assessments", "--assessment-mode", "all"])
    elif assessment_mode == "tail":
        cmd.extend(["--run-assessments", "--assessment-mode", "tail"])
    
    runner.run(cmd)
    
    return True, False, dbc.Spinner(size="sm", children=" Building..."), "Building..."


@app.callback(
    Output("build-console", "children"),
    Output("build-output-store", "data"),
    Output("build-running-store", "data", allow_duplicate=True),
    Output("build-interval", "disabled", allow_duplicate=True),
    Output("build-status", "children", allow_duplicate=True),
    Output("build-button", "children", allow_duplicate=True),
    Output("newest-library-store", "data", allow_duplicate=True),
    Input("build-interval", "n_intervals"),
    State("build-running-store", "data"),
    State("output-input", "value"),
    prevent_initial_call=True
)
def update_build_console(n_intervals, is_running, output_dir):
    output_text = runner.get_output() or "Waiting for output..."
    
    if runner.is_running():
        return output_text, output_text, True, False, dbc.Spinner(size="sm", children=" Building..."), "Building...", dash.no_update
    else:
        # Process finished
        return_code = runner.get_return_code()
        if return_code == 0:
            newest = find_newest_library()
            return (output_text, output_text, False, True, 
                    html.Span("✅ Build complete!", className="text-success fw-bold"),
                    "🚀 Build Library", newest or dash.no_update)
        else:
            return (output_text, output_text, False, True,
                    html.Span(f"❌ Build failed (code {return_code})", className="text-danger fw-bold"),
                    "🚀 Build Library", dash.no_update)


# Restore build output from store on tab switch
@app.callback(
    Output("build-console", "children", allow_duplicate=True),
    Input("tabs", "active_tab"),
    State("build-output-store", "data"),
    prevent_initial_call=True
)
def restore_build_output(active_tab, stored_output):
    if active_tab == "build" and stored_output:
        return stored_output
    raise PreventUpdate


# =============================================================================
# Callbacks - Query Process
# =============================================================================

@app.callback(
    Output("query-running-store", "data"),
    Output("query-interval", "disabled"),
    Output("query-status", "children"),
    Output("query-button", "children"),
    Output("query-params-store", "data"),
    Input("query-button", "n_clicks"),
    State("library-input", "value"),
    State("total-reserves", "value"),
    State("return-period", "value"),
    State("n-scenarios", "value"),
    State("n-neighbours", "value"),
    State("query-jit-assessment", "value"),
    [State(get_lob_id(lob), "value") for lob in LOBS],
    State("query-running-store", "data"),
    prevent_initial_call=True
)
def start_query(n_clicks, library, reserves, return_period, n_scenarios, 
                n_neighbours, jit_assessment, *args):
    # Last arg is is_running, rest are LOB values
    lob_values = args[:-1]
    is_running = args[-1]
    
    if not n_clicks:
        raise PreventUpdate
    
    if is_running or runner.is_running():
        raise PreventUpdate
    
    # Validate library exists
    if not library:
        return False, True, html.Span("❌ Please specify a library path", className="text-danger"), "🔍 Find Scenarios", None
    
    # Resolve library path (could be relative to project root)
    library_path = Path(library)
    if not library_path.is_absolute():
        library_path = get_project_root() / library
    
    library_json = library_path / "scenario_library.json" if library_path.is_dir() else library_path
    
    if not library_json.exists():
        return False, True, html.Div([
            html.Span("❌ No scenario library found at this path", className="text-danger fw-bold"),
            html.Br(),
            html.Small(f"Checked: {library_json}", className="text-muted"),
            html.Br(),
            html.Small("Please build a library first using the Build tab, or check the path.", className="text-muted")
        ]), "🔍 Find Scenarios", None
    
    # Use absolute path for library_path
    library_abs = str(library_path)
    
    # Build weights
    weights = {}
    for lob, val in zip(LOBS, lob_values):
        if val and val > 0:
            weights[lob] = val
    
    # Normalize
    total = sum(weights.values()) if weights else 0
    if total > 0:
        weights = {k: v/total for k, v in weights.items()}
    else:
        weights = {"Property": 1.0}
    
    # Store query params for later use
    query_params = {
        "library": library_abs,
        "reserves": reserves,
        "return_period": int(return_period),
        "n_scenarios": n_scenarios,
        "weights": weights
    }
    
    # Create output file for results JSON
    results_path = library_path / "query_results.json"
    
    # Build command
    script_path = get_script_dir() / "pipeline_v2.py"
    cmd = [
        sys.executable, str(script_path), "query",
        "--library", library_abs,
        "--reserves", str(reserves),
        "--return-period", str(return_period),
        "--n-scenarios", str(n_scenarios),
        "--n-neighbours", str(n_neighbours),
        "--output", str(results_path)  # Save results to JSON
    ]
    
    # Add LOB weights
    for lob, weight in weights.items():
        cmd.extend(["--lob", lob, str(weight)])
    
    # JIT assessment flag
    if jit_assessment:
        cmd.append("--assess-results")
    
    runner.run(cmd)
    
    return True, False, dbc.Spinner(size="sm", children=" Querying..."), "Querying...", query_params


@app.callback(
    Output("query-console", "children"),
    Output("query-output-store", "data"),
    Output("query-running-store", "data", allow_duplicate=True),
    Output("query-interval", "disabled", allow_duplicate=True),
    Output("query-status", "children", allow_duplicate=True),
    Output("query-button", "children", allow_duplicate=True),
    Output("query-results-store", "data"),
    Output("generate-report-btn", "disabled"),
    Output("query-results-section", "style"),
    Output("query-results-cards", "children"),
    Input("query-interval", "n_intervals"),
    State("query-running-store", "data"),
    State("query-params-store", "data"),
    prevent_initial_call=True
)
def update_query_console(n_intervals, is_running, query_params):
    output_text = runner.get_output() or "Waiting for output..."
    
    if runner.is_running():
        return (output_text, output_text, True, False, 
                dbc.Spinner(size="sm", children=" Querying..."), "Querying...",
                dash.no_update, True, {"display": "none"}, dash.no_update)
    else:
        return_code = runner.get_return_code()
        
        # Try to load results from JSON file
        results_data = None
        results_cards = []
        
        if return_code == 0 and query_params:
            try:
                results_path = Path(query_params["library"]) / "query_results.json"
                if results_path.exists():
                    with open(results_path, 'r') as f:
                        results_data = json.load(f)
                    
                    # Build scenario cards
                    results_cards = build_scenario_cards(results_data, query_params)
            except Exception as e:
                print(f"Error loading results: {e}")
        
        if return_code == 0:
            show_results = {"display": "block"} if results_data else {"display": "none"}
            return (output_text, output_text, False, True,
                    html.Span("✅ Query complete!", className="text-success fw-bold"),
                    "🔍 Find Scenarios",
                    results_data,
                    False if results_data else True,  # Enable report button if we have results
                    show_results,
                    results_cards)
        else:
            # Try to extract meaningful error from output
            error_msg = "Query failed"
            if "FileNotFoundError" in output_text:
                if "scenario_library.json" in output_text:
                    error_msg = "No scenario library found. Please build a library first."
                elif "embedding_space" in output_text:
                    error_msg = "Embedding space not found in library."
                else:
                    error_msg = "File not found. Check console for details."
            elif "No such file or directory" in output_text:
                error_msg = "Library path does not exist. Check the path and try again."
            elif "ModuleNotFoundError" in output_text:
                error_msg = "Missing Python dependency. Check console for details."
            elif "JSONDecodeError" in output_text:
                error_msg = "Invalid library file. The scenario_library.json may be corrupted."
            elif "KeyError" in output_text:
                error_msg = "Library format error. Required field missing."
            elif "TypeError" in output_text:
                error_msg = "Library format error. Check console for details."
            elif "AttributeError" in output_text:
                error_msg = "Code error. Check console for details."
            elif "ImportError" in output_text:
                error_msg = "Import error. Check dependencies."
            
            return (output_text, output_text, False, True,
                    html.Div([
                        html.Span(f"❌ {error_msg}", className="text-danger fw-bold"),
                        html.Br(),
                        html.Small(f"Exit code: {return_code}. See console for details.", className="text-muted")
                    ]),
                    "🔍 Find Scenarios",
                    None, True, {"display": "none"}, [])


def build_scenario_cards(scenarios: list, query_params: dict) -> list:
    """Build visual cards for each scenario."""
    cards = []
    
    for i, s in enumerate(scenarios, 1):
        # Build LOB impact bars
        lob_impacts = s.get("lob_impacts", {})
        max_impact = max(lob_impacts.values()) if lob_impacts else 1
        
        impact_bars = []
        for lob, impact in sorted(lob_impacts.items(), key=lambda x: -x[1]):
            if impact > 0:
                width_pct = min(100, (impact / max_impact) * 100)
                impact_bars.append(
                    html.Div([
                        html.Span(lob, style={"width": "150px", "display": "inline-block", "fontWeight": "500"}),
                        html.Div([
                            html.Div(
                                f"{impact:.1%}",
                                style={
                                    "width": f"{width_pct}%",
                                    "backgroundColor": "#3182ce",
                                    "color": "white",
                                    "padding": "2px 8px",
                                    "borderRadius": "4px",
                                    "fontSize": "0.85em",
                                    "minWidth": "50px",
                                    "textAlign": "right"
                                }
                            )
                        ], style={"flex": "1", "backgroundColor": "#e2e8f0", "borderRadius": "4px"})
                    ], style={"display": "flex", "alignItems": "center", "gap": "10px", "marginBottom": "5px"})
                )
        
        # Causal chain / events
        causal_chain = s.get("causal_chain", "")
        events = causal_chain.split(", ") if causal_chain else []
        
        # Build card
        card = dbc.Card([
            dbc.CardHeader([
                html.H5(f"Scenario {i}: {s.get('name', 'Unknown')}", className="mb-0"),
                html.Small(f"Return Period: {s.get('return_period', query_params.get('return_period', 100))}-year | Severity: {s.get('severity_ratio', 0):.1%}")
            ], style={"backgroundColor": "#1a365d", "color": "white"}),
            dbc.CardBody([
                # Narrative
                html.Div([
                    html.H6("📋 Narrative", className="text-primary"),
                    html.P(s.get("narrative", "No narrative available."), 
                           style={"backgroundColor": "#f0f4f8", "padding": "15px", 
                                  "borderRadius": "8px", "borderLeft": "4px solid #3182ce",
                                  "fontStyle": "italic"})
                ], className="mb-3"),
                
                # Key Events
                html.Div([
                    html.H6("⚡ Key Events", className="text-primary"),
                    html.Ul([html.Li(e) for e in events[:5]] if events else [html.Li("N/A")])
                ], className="mb-3") if events else None,
                
                # LOB Impacts
                html.Div([
                    html.H6("📊 Line of Business Impacts", className="text-primary"),
                    html.Div(impact_bars)
                ], className="mb-3"),
                
                # Analysis (collapsible)
                dbc.Accordion([
                    dbc.AccordionItem([
                        html.P(s.get("explanation", "No analysis available."))
                    ], title="💡 Detailed Analysis")
                ], start_collapsed=True, className="mb-2"),
                
                # Audit info preview (if available)
                html.Div([
                    html.Small([
                        html.Strong("Source: "),
                        ", ".join(s.get("source_scenarios", [])[:2]) or "N/A"
                    ], className="text-muted")
                ])
            ])
        ], className="mb-4", style={"boxShadow": "0 2px 10px rgba(0,0,0,0.1)"})
        
        cards.append(card)
    
    return cards


# Restore query output from store on tab switch
@app.callback(
    Output("query-console", "children", allow_duplicate=True),
    Input("tabs", "active_tab"),
    State("query-output-store", "data"),
    prevent_initial_call=True
)
def restore_query_output(active_tab, stored_output):
    if active_tab == "query" and stored_output:
        return stored_output
    raise PreventUpdate


# Generate HTML Report callback
@app.callback(
    Output("report-generation-status", "children"),
    Output("generate-report-btn", "children"),
    Input("generate-report-btn", "n_clicks"),
    State("query-results-store", "data"),
    State("query-params-store", "data"),
    prevent_initial_call=True
)
def generate_report(n_clicks, results_data, query_params):
    if not n_clicks or not results_data or not query_params:
        raise PreventUpdate
    
    try:
        from report_generator import generate_html_report
        from datetime import datetime
        
        library_dir = Path(query_params["library"])
        return_period = query_params["return_period"]
        
        # Build portfolio dict
        portfolio = {
            "total_reserves_gbp_m": query_params["reserves"],
            "lob_weights": query_params["weights"]
        }
        
        # Generate report filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_filename = f"stress_test_report_{return_period}Y_{timestamp}.html"
        report_path = library_dir / report_filename
        
        # Try to get OpenAI client for commentary
        client = None
        try:
            from openai import OpenAI
            client = OpenAI()
        except:
            pass
        
        # Generate report
        generate_html_report(
            scenarios=results_data,
            portfolio=portfolio,
            return_period=return_period,
            library_dir=library_dir,
            output_path=report_path,
            client=client
        )
        
        return (
            dbc.Alert([
                html.H5("✅ Report Generated!", className="alert-heading"),
                html.P([
                    "Report saved to: ",
                    html.Code(str(report_path))
                ]),
                html.Hr(),
                html.P([
                    "Open in browser: ",
                    html.A(f"file://{report_path.absolute()}", 
                           href=f"file://{report_path.absolute()}", 
                           target="_blank",
                           className="alert-link")
                ], className="mb-0")
            ], color="success", className="mt-3"),
            "📄 Generate Report"
        )
        
    except Exception as e:
        import traceback
        return (
            dbc.Alert([
                html.H5("❌ Report Generation Failed", className="alert-heading"),
                html.P(str(e)),
                html.Pre(traceback.format_exc(), style={"fontSize": "0.8em"})
            ], color="danger", className="mt-3"),
            "📄 Generate Report"
        )


# =============================================================================
# Callbacks - Library Diagnostics
# =============================================================================

@app.callback(
    Output("diag-running-store", "data"),
    Output("diag-interval", "disabled"),
    Output("diag-status", "children"),
    Output("run-diagnostics-btn", "children"),
    Input("run-diagnostics-btn", "n_clicks"),
    State("diag-library-input", "value"),
    State("diag-bootstrap-n", "value"),
    State("diag-running-store", "data"),
    prevent_initial_call=True
)
def start_diagnostics(n_clicks, library_path, n_bootstrap, is_running):
    if not n_clicks or is_running:
        raise PreventUpdate
    
    if not library_path:
        return False, True, dbc.Alert("Please specify library path", color="warning"), "🔬 Run Diagnostics"
    
    # Resolve library path (could be relative to project root)
    lib_path = Path(library_path)
    if not lib_path.is_absolute():
        lib_path = get_project_root() / library_path
    
    # Check if library exists
    scenario_file = lib_path / "scenario_library.json" if lib_path.is_dir() else lib_path
    if lib_path.is_dir():
        scenario_file = lib_path / "scenario_library.json"
    else:
        scenario_file = lib_path
        lib_path = lib_path.parent
    
    if not scenario_file.exists():
        return False, True, dbc.Alert(
            f"Library not found: {scenario_file}. Build a library first.", 
            color="danger"
        ), "🔬 Run Diagnostics"
    
    # Run diagnostics in background using subprocess
    script_path = get_script_dir() / "library_diagnostics.py"
    output_path = lib_path / "diagnostics_results.json"
    
    cmd = [
        sys.executable, str(script_path),
        "--library", str(lib_path),
        "--bootstrap", str(n_bootstrap or 500),
        "--output", str(output_path)
    ]
    
    runner.run(cmd)
    
    return True, False, dbc.Spinner(size="sm", children=" Running diagnostics..."), "Running..."


@app.callback(
    Output("diag-console", "children"),
    Output("diag-running-store", "data", allow_duplicate=True),
    Output("diag-interval", "disabled", allow_duplicate=True),
    Output("diag-status", "children", allow_duplicate=True),
    Output("run-diagnostics-btn", "children", allow_duplicate=True),
    Output("diag-results-store", "data"),
    Output("generate-diag-report-btn", "disabled"),
    Output("diag-results-section", "style"),
    Output("diag-overall-score", "children"),
    Output("diag-overall-grade", "children"),
    Output("diag-component-scores", "children"),
    Output("diag-recommendations", "children"),
    Output("diag-severity-content", "children"),
    Output("diag-semantic-content", "children"),
    Output("diag-cause-content", "children"),
    Output("diag-lob-content", "children"),
    Output("diag-coherence-content", "children"),
    Input("diag-interval", "n_intervals"),
    State("diag-running-store", "data"),
    State("diag-library-input", "value"),
    prevent_initial_call=True
)
def update_diagnostics_console(n_intervals, is_running, library_path):
    output_text = runner.get_output() or "Waiting for output..."
    
    if runner.is_running():
        return (output_text, True, False, 
                dbc.Spinner(size="sm", children=" Running diagnostics..."), "Running...",
                dash.no_update, True, {"display": "none"},
                dash.no_update, dash.no_update, dash.no_update, dash.no_update,
                dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update)
    
    return_code = runner.get_return_code()
    
    if return_code == 0 and library_path:
        # Resolve library path
        lib_path = Path(library_path)
        if not lib_path.is_absolute():
            lib_path = get_project_root() / library_path
        
        # Try to load results
        try:
            results_path = lib_path / "diagnostics_results.json"
            if results_path.exists():
                with open(results_path, 'r') as f:
                    results = json.load(f)
                
                # Build component scores display
                component_scores = build_component_scores_display(results)
                
                # Build recommendations
                recs = results.get('recommendations', [])
                recs_html = [dbc.Alert(rec, color="info", className="py-2") for rec in recs[:5]]
                
                # Build severity content
                severity_content = build_severity_display(results.get('severity'))
                semantic_content = build_semantic_display(results.get('semantic'))
                cause_content = build_cause_display(results.get('cause_distribution'))
                lob_content = build_lob_display(results.get('lob_coverage'))
                coherence_content = build_coherence_display(results.get('coherence'))
                
                grade = results.get('overall_grade', '-')
                score = results.get('overall_score', 0)
                
                return (output_text, False, True,
                        html.Span("✅ Diagnostics complete!", className="text-success fw-bold"),
                        "🔬 Run Diagnostics",
                        results,
                        False,  # Enable report button
                        {"display": "block"},
                        f"{score:.0f}",
                        f"Grade: {grade}",
                        component_scores,
                        recs_html,
                        severity_content,
                        semantic_content,
                        cause_content,
                        lob_content,
                        coherence_content)
        except Exception as e:
            print(f"Error loading diagnostics results: {e}")
            import traceback
            traceback.print_exc()
    
    # Extract error message from output if possible
    error_msg = "Diagnostics failed"
    if "FileNotFoundError" in output_text:
        if "scenario_library.json" in output_text:
            error_msg = "No scenario library found. Build a library first."
        elif "unified_corpus.json" in output_text or "historical corpus" in output_text:
            error_msg = "Historical corpus not found. Ensure unified_corpus.json exists."
        else:
            error_msg = "File not found. Check console for details."
    elif "No such file or directory" in output_text:
        error_msg = "Library path does not exist."
    elif "ModuleNotFoundError" in output_text:
        error_msg = "Missing Python dependency. Check console."
    elif "JSONDecodeError" in output_text:
        error_msg = "Invalid JSON file. Check library format."
    elif return_code is not None and return_code != 0:
        error_msg = f"Diagnostics failed (exit code {return_code}). Check console."
    
    return (output_text, False, True,
            html.Div([
                html.Span(f"❌ {error_msg}", className="text-danger fw-bold"),
                html.Br(),
                html.Small("See console output below for details.", className="text-muted")
            ]),
            "🔬 Run Diagnostics",
            None, True, {"display": "none"},
            "-", "Grade: -", None, None,
            None, None, None, None, None)


def build_component_scores_display(results):
    """Build component scores display cards."""
    scores = [
        ("Severity", results.get('severity_score', 0)),
        ("Semantic", results.get('semantic_score', 0)),
        ("Cause Dist", results.get('cause_score', 0)),
        ("LOB Coverage", results.get('lob_score', 0)),
        ("Coherence", results.get('coherence_score', 0)),
    ]
    
    cards = []
    for name, score in scores:
        color = "success" if score >= 70 else ("warning" if score >= 60 else "danger")
        cards.append(
            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        html.H4(f"{score:.0f}", className="text-center mb-0"),
                        html.Small(name, className="text-muted")
                    ], className="py-2 text-center")
                ], color=color, outline=True)
            ], width=True)
        )
    
    return dbc.Row(cards, className="g-2")


def build_severity_display(severity, hist_severities=None, synth_severities=None):
    """Build severity diagnostics display with embedded Plotly visualization."""
    if not severity:
        return html.P("Severity diagnostics not available.")
    
    content = []
    
    # Add embedded histogram if we have raw data
    if hist_severities is not None and synth_severities is not None:
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
        
        # Create histogram comparison
        fig = make_subplots(rows=1, cols=2, 
                          subplot_titles=('Distribution Comparison', 'CDF Comparison'))
        
        # Histogram
        all_sev = list(hist_severities) + list(synth_severities)
        bins_edges = list(np.linspace(min(all_sev), max(all_sev), 30))
        
        fig.add_trace(
            go.Histogram(x=hist_severities, name=f'Historical (n={len(hist_severities)})',
                        marker_color='#3182ce', opacity=0.6, nbinsx=30,
                        hovertemplate='Severity: %{x:.2%}<br>Count: %{y}<extra>Historical</extra>'),
            row=1, col=1
        )
        fig.add_trace(
            go.Histogram(x=synth_severities, name=f'Synthetic (n={len(synth_severities)})',
                        marker_color='#e53e3e', opacity=0.6, nbinsx=30,
                        hovertemplate='Severity: %{x:.2%}<br>Count: %{y}<extra>Synthetic</extra>'),
            row=1, col=1
        )
        
        # CDF
        hist_sorted = sorted(hist_severities)
        synth_sorted = sorted(synth_severities)
        hist_cdf = [i/len(hist_sorted) for i in range(1, len(hist_sorted)+1)]
        synth_cdf = [i/len(synth_sorted) for i in range(1, len(synth_sorted)+1)]
        
        fig.add_trace(
            go.Scatter(x=hist_sorted, y=hist_cdf, name='Historical CDF',
                      mode='lines', line=dict(color='#3182ce', width=2)),
            row=1, col=2
        )
        fig.add_trace(
            go.Scatter(x=synth_sorted, y=synth_cdf, name='Synthetic CDF',
                      mode='lines', line=dict(color='#e53e3e', width=2)),
            row=1, col=2
        )
        
        fig.update_layout(
            height=350,
            barmode='overlay',
            showlegend=True,
            legend=dict(orientation='h', y=1.1),
            margin=dict(t=50, b=40)
        )
        fig.update_xaxes(title_text="Severity Ratio", row=1, col=1)
        fig.update_xaxes(title_text="Severity Ratio", row=1, col=2)
        fig.update_yaxes(title_text="Count", row=1, col=1)
        fig.update_yaxes(title_text="Cumulative Probability", row=1, col=2)
        
        content.append(dcc.Graph(figure=fig, config={'displayModeBar': True}))
    
    # Test results table with CI info
    mmd_ci = f"[{severity.get('mmd_ci_lower', 0):.4f}, {severity.get('mmd_ci_upper', 0):.4f}]" if severity.get('mmd_ci_lower') else "N/A"
    
    tests = [
        ("Bootstrap MMD", severity.get('mmd_statistic', 0), mmd_ci, severity.get('mmd_pvalue', 0), severity.get('mmd_pass', False)),
        ("KS Test", severity.get('ks_statistic', 0), "N/A", severity.get('ks_pvalue', 0), severity.get('ks_pass', False)),
        ("JS Divergence", severity.get('js_divergence', 0), "N/A", None, severity.get('js_pass', False)),
    ]
    
    table_rows = []
    for name, stat, ci, pval, passed in tests:
        badge_color = "success" if passed else "danger"
        badge_text = "✓ PASS" if passed else "✗ FAIL"
        pval_str = f"{pval:.4f}" if pval is not None else "N/A"
        table_rows.append(
            html.Tr([
                html.Td(name),
                html.Td(f"{stat:.4f}"),
                html.Td(ci),
                html.Td(pval_str),
                html.Td(dbc.Badge(badge_text, color=badge_color))
            ])
        )
    
    content.append(html.H6("Statistical Tests with Bootstrap CIs", className="mt-3"))
    content.append(dbc.Table([
        html.Thead(html.Tr([html.Th("Test"), html.Th("Statistic"), html.Th("95% CI"), html.Th("P-Value"), html.Th("Result")])),
        html.Tbody(table_rows)
    ], bordered=True, hover=True, size="sm"))
    
    # Stats comparison
    stats = [
        ("N (samples)", severity.get('historical_n', 0), severity.get('synthetic_n', 0)),
        ("Mean", f"{severity.get('historical_mean', 0):.2%}", f"{severity.get('synthetic_mean', 0):.2%}"),
        ("Std Dev", f"{severity.get('historical_std', 0):.2%}", f"{severity.get('synthetic_std', 0):.2%}"),
        ("Median", f"{severity.get('historical_median', 0):.2%}", f"{severity.get('synthetic_median', 0):.2%}"),
        ("Max", f"{severity.get('historical_max', 0):.2%}", f"{severity.get('synthetic_max', 0):.2%}"),
    ]
    
    stats_rows = [html.Tr([html.Td(name), html.Td(str(hist)), html.Td(str(synth))]) for name, hist, synth in stats]
    
    content.append(html.H6("Distribution Summary", className="mt-4"))
    content.append(dbc.Table([
        html.Thead(html.Tr([html.Th("Metric"), html.Th("Historical"), html.Th("Synthetic")])),
        html.Tbody(stats_rows)
    ], bordered=True, hover=True, size="sm"))
    
    return html.Div(content)


def build_semantic_display(semantic, hist_embeddings=None, synth_embeddings=None):
    """Build semantic diagnostics display with embedded Plotly visualization."""
    if not semantic:
        return html.P("Semantic diagnostics not available.")
    
    content = []
    
    # Add embedded 2D embedding plot if we have raw data
    if hist_embeddings is not None and synth_embeddings is not None:
        import plotly.graph_objects as go
        from sklearn.decomposition import PCA
        
        # PCA for 2D
        pca = PCA(n_components=2)
        hist_2d = pca.fit_transform(hist_embeddings)
        synth_2d = pca.transform(synth_embeddings)
        
        fig = go.Figure()
        
        # Historical density contour
        fig.add_trace(
            go.Histogram2dContour(
                x=hist_2d[:, 0], y=hist_2d[:, 1],
                name='Historical density',
                colorscale='Blues',
                showscale=False,
                contours=dict(coloring='fill'),
                opacity=0.4
            )
        )
        
        # Historical scatter
        fig.add_trace(
            go.Scatter(
                x=hist_2d[:, 0], y=hist_2d[:, 1],
                mode='markers',
                name=f'Historical (n={len(hist_embeddings)})',
                marker=dict(color='#3182ce', size=5, opacity=0.6)
            )
        )
        
        # Synthetic scatter
        fig.add_trace(
            go.Scatter(
                x=synth_2d[:, 0], y=synth_2d[:, 1],
                mode='markers',
                name=f'Synthetic (n={len(synth_embeddings)})',
                marker=dict(color='#e53e3e', size=7, symbol='x', opacity=0.7)
            )
        )
        
        fig.update_layout(
            title=f"Embedding Space Coverage (PCA - {pca.explained_variance_ratio_.sum():.1%} variance)",
            height=400,
            showlegend=True,
            legend=dict(orientation='h', y=1.1),
            margin=dict(t=60, b=40)
        )
        fig.update_xaxes(title_text="PC1")
        fig.update_yaxes(title_text="PC2")
        
        content.append(dcc.Graph(figure=fig, config={'displayModeBar': True}))
    
    # Metrics table with quality badges
    metrics = [
        ("Mean Cosine Similarity", semantic.get('mean_cosine_similarity', 0), "≥ 0.60", semantic.get('cosine_pass', False)),
        ("Bootstrap MMD", f"{semantic.get('mmd_statistic', 0):.4f} (p={semantic.get('mmd_pvalue', 0):.4f})", "≤ 0.10", semantic.get('mmd_pass', False)),
        ("Cluster Coverage", f"{semantic.get('cluster_coverage', 0):.1%}", "≥ 80%", semantic.get('cluster_pass', False)),
        ("Outlier Rate", f"{semantic.get('outlier_rate', 0):.1%}", "≤ 20%", semantic.get('outlier_pass', False)),
        ("Diversity Ratio", f"{semantic.get('diversity_ratio', 0):.3f}", "0.70-1.30", semantic.get('diversity_pass', False)),
    ]
    
    table_rows = []
    for name, value, threshold, passed in metrics:
        badge_color = "success" if passed else "danger"
        badge_text = "✓ PASS" if passed else "✗ FAIL"
        table_rows.append(
            html.Tr([
                html.Td(name),
                html.Td(str(value) if not isinstance(value, float) else f"{value:.4f}"),
                html.Td(threshold),
                html.Td(dbc.Badge(badge_text, color=badge_color))
            ])
        )
    
    content.append(html.H6("Semantic Coverage Metrics", className="mt-3"))
    content.append(dbc.Table([
        html.Thead(html.Tr([html.Th("Metric"), html.Th("Value"), html.Th("Threshold"), html.Th("Result")])),
        html.Tbody(table_rows)
    ], bordered=True, hover=True, size="sm"))
    
    return html.Div(content)


def build_cause_display(cause):
    """Build cause distribution display with embedded Plotly visualization."""
    if not cause:
        return html.P("Cause distribution diagnostics not available.")
    
    content = []
    
    # Create bar chart if we have distribution data
    hist_dist = cause.get('historical_distribution', {})
    synth_dist = cause.get('synthetic_distribution', {})
    
    if hist_dist and synth_dist:
        import plotly.graph_objects as go
        
        categories = sorted(set(hist_dist.keys()) | set(synth_dist.keys()))
        hist_vals = [hist_dist.get(c, 0) for c in categories]
        synth_vals = [synth_dist.get(c, 0) for c in categories]
        
        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=categories, y=hist_vals,
            name='Historical',
            marker_color='#3182ce',
            text=[f'{v:.1%}' for v in hist_vals],
            textposition='outside'
        ))
        fig.add_trace(go.Bar(
            x=categories, y=synth_vals,
            name='Synthetic',
            marker_color='#e53e3e',
            text=[f'{v:.1%}' for v in synth_vals],
            textposition='outside'
        ))
        
        fig.update_layout(
            title="Cause Category Distribution Comparison",
            height=350,
            barmode='group',
            showlegend=True,
            legend=dict(orientation='h', y=1.1),
            margin=dict(t=60, b=80),
            xaxis_tickangle=45
        )
        fig.update_yaxes(title_text="Proportion")
        
        content.append(dcc.Graph(figure=fig, config={'displayModeBar': True}))
    
    # Statistics
    chi_pass = cause.get('chi_square_pvalue', 0) >= 0.05
    js_pass = cause.get('js_divergence', 0) <= 0.20
    
    content.append(html.H6("Statistical Tests", className="mt-3"))
    content.append(dbc.Table([
        html.Thead(html.Tr([html.Th("Test"), html.Th("Value"), html.Th("Threshold"), html.Th("Result")])),
        html.Tbody([
            html.Tr([
                html.Td("Chi-Square"),
                html.Td(f"{cause.get('chi_square_statistic', 0):.4f} (p={cause.get('chi_square_pvalue', 0):.4f})"),
                html.Td("p ≥ 0.05"),
                html.Td(dbc.Badge("✓ PASS" if chi_pass else "✗ FAIL", color="success" if chi_pass else "danger"))
            ]),
            html.Tr([
                html.Td("JS Divergence"),
                html.Td(f"{cause.get('js_divergence', 0):.4f}"),
                html.Td("≤ 0.20"),
                html.Td(dbc.Badge("✓ PASS" if js_pass else "✗ FAIL", color="success" if js_pass else "danger"))
            ])
        ])
    ], bordered=True, hover=True, size="sm"))
    
    if cause.get('missing_categories'):
        content.append(dbc.Alert([
            html.Strong("⚠️ Missing Categories: "),
            ", ".join(cause['missing_categories'])
        ], color="warning", className="mt-3"))
    
    if cause.get('over_represented'):
        content.append(html.P([
            html.Strong("Over-represented: "),
            ", ".join(cause['over_represented'])
        ], className="text-warning"))
    
    if cause.get('under_represented'):
        content.append(html.P([
            html.Strong("Under-represented: "),
            ", ".join(cause['under_represented'])
        ], className="text-info"))
    
    return html.Div(content)


def build_lob_display(lob):
    """Build LOB coverage display."""
    if not lob:
        return html.P("LOB coverage diagnostics not available.")
    
    content = [
        html.H6("Coverage Summary", className="mt-3"),
        html.P([
            html.Strong("Coverage Rate: "),
            f"{lob.get('coverage_rate', 0):.1%}"
        ]),
        html.P([
            html.Strong("Historical LOBs: "),
            str(len(lob.get('historical_lobs', [])))
        ]),
        html.P([
            html.Strong("Synthetic LOBs: "),
            str(len(lob.get('synthetic_lobs', [])))
        ]),
    ]
    
    if lob.get('missing_lobs'):
        content.append(dbc.Alert([
            html.Strong("Missing LOBs: "),
            ", ".join(lob['missing_lobs'])
        ], color="danger"))
    else:
        content.append(dbc.Alert("All historical LOBs covered!", color="success"))
    
    return html.Div(content)


def build_coherence_display(coherence):
    """Build coherence display."""
    if not coherence:
        return html.P("Coherence diagnostics not available.")
    
    content = [
        html.H6("Coherence Summary", className="mt-3"),
        html.P([
            html.Strong("Coherence Rate: "),
            f"{coherence.get('coherence_rate', 0):.1%}",
            dbc.Badge("✓ PASS" if coherence.get('overall_pass', False) else "✗ FAIL",
                     color="success" if coherence.get('overall_pass', False) else "danger",
                     className="ms-2")
        ]),
        html.P([
            html.Strong("Coherent: "), str(coherence.get('n_coherent', 0)),
            " | ",
            html.Strong("Incoherent: "), str(coherence.get('n_incoherent', 0))
        ]),
    ]
    
    # Show incoherent examples
    examples = coherence.get('incoherent_examples', [])
    if examples:
        content.append(html.H6("Incoherent Examples", className="mt-3"))
        for ex in examples[:3]:
            content.append(
                dbc.Card([
                    dbc.CardBody([
                        html.P([html.Strong("Severity: "), f"{ex.get('severity', 0):.1%}"]),
                        html.P([html.Strong("Issue: "), ex.get('reason', 'N/A')]),
                        html.Small(ex.get('narrative', '')[:200] + "...", className="text-muted")
                    ])
                ], className="mb-2", color="danger", outline=True)
            )
    
    return html.Div(content)


# Generate diagnostics report
@app.callback(
    Output("diag-report-status", "children"),
    Output("generate-diag-report-btn", "children"),
    Input("generate-diag-report-btn", "n_clicks"),
    State("diag-results-store", "data"),
    State("diag-library-input", "value"),
    prevent_initial_call=True
)
def generate_diagnostics_report_callback(n_clicks, results, library_path):
    if not n_clicks or not results or not library_path:
        raise PreventUpdate
    
    try:
        from diagnostic_report import generate_full_diagnostics_report
        from datetime import datetime
        
        output_dir = Path(library_path) / "diagnostics"
        
        report_path = generate_full_diagnostics_report(
            library_path=library_path,
            output_dir=str(output_dir),
            n_bootstrap=100  # Fewer for report (already computed)
        )
        
        return (
            dbc.Alert([
                html.H5("✅ Diagnostics Report Generated!", className="alert-heading"),
                html.P([
                    "Report saved to: ",
                    html.Code(report_path)
                ]),
                html.Hr(),
                html.P([
                    "Open in browser: ",
                    html.A(f"file://{Path(report_path).absolute()}", 
                           href=f"file://{Path(report_path).absolute()}", 
                           target="_blank",
                           className="alert-link")
                ], className="mb-0")
            ], color="success"),
            "📄 Generate Report"
        )
    except Exception as e:
        import traceback
        return (
            dbc.Alert([
                html.H5("❌ Report Generation Failed", className="alert-heading"),
                html.P(str(e)),
                html.Pre(traceback.format_exc(), style={"fontSize": "0.8em"})
            ], color="danger"),
            "📄 Generate Report"
        )


# =============================================================================
# Callbacks - Portfolio Analysis (Even-Year Sampling & Bootstrap)
# =============================================================================

# Portfolio preset callback for analysis tab
@app.callback(
    Output("analysis-lob-property", "value"),
    Output("analysis-lob-casualty", "value"),
    Output("analysis-lob-marine", "value"),
    Output("analysis-lob-proflines", "value"),
    Output("analysis-lob-motor", "value"),
    Output("analysis-lob-cyber", "value"),
    Input("analysis-portfolio-preset", "value"),
    prevent_initial_call=True
)
def update_analysis_lob_from_preset(preset):
    """Update LOB weights from preset selection."""
    if preset == "custom":
        raise PreventUpdate

    preset_data = PRESETS.get(preset, {})
    return (
        preset_data.get("Property", 0),
        preset_data.get("Casualty", 0),
        preset_data.get("Marine", 0),
        preset_data.get("Professional Lines", 0),
        preset_data.get("Motor", 0),
        preset_data.get("Cyber", 0),
    )


def build_lob_weights_from_inputs(property_pct, casualty_pct, marine_pct, proflines_pct, motor_pct, cyber_pct):
    """Build normalized LOB weights dict from input percentages."""
    raw_weights = {
        "Property": property_pct or 0,
        "Casualty": casualty_pct or 0,
        "Marine": marine_pct or 0,
        "Professional Lines": proflines_pct or 0,
        "Motor": motor_pct or 0,
        "Cyber": cyber_pct or 0,
    }
    total = sum(raw_weights.values())
    if total > 0:
        return {k: v / total for k, v in raw_weights.items() if v > 0}
    return {"Property": 1.0}


# Run Even-Year Sampling Analysis
@app.callback(
    Output("even-year-status", "children"),
    Output("even-year-results-section", "style"),
    Output("even-year-results-store", "data"),
    Output("even-year-years-count", "children"),
    Output("even-year-scenarios-count", "children"),
    Output("even-year-avg-coverage", "children"),
    Output("even-year-quantiles-table", "children"),
    Output("even-year-per-year-stats", "children"),
    Output("analysis-console", "children"),
    Input("run-even-year-btn", "n_clicks"),
    State("analysis-corpus-input", "value"),
    State("analysis-portfolio-size", "value"),
    State("analysis-min-coverage", "value"),
    State("analysis-lob-property", "value"),
    State("analysis-lob-casualty", "value"),
    State("analysis-lob-marine", "value"),
    State("analysis-lob-proflines", "value"),
    State("analysis-lob-motor", "value"),
    State("analysis-lob-cyber", "value"),
    State("even-year-n-per-year", "value"),
    State("even-year-min-success", "value"),
    State("even-year-seed", "value"),
    State("even-year-coverage-cap", "value"),
    State("even-year-tau", "value"),
    State("even-year-top-k", "value"),
    prevent_initial_call=True
)
def run_even_year_analysis(n_clicks, corpus_path, portfolio_size, min_coverage,
                           prop, cas, mar, prof, mot, cyb,
                           n_per_year, min_success, seed,
                           coverage_cap, tau, top_k):
    """Run even-year sampling analysis."""
    if not n_clicks:
        raise PreventUpdate

    import io
    import sys
    from contextlib import redirect_stdout

    console_output = io.StringIO()

    try:
        with redirect_stdout(console_output):
            print("=" * 60)
            print("Even-Year Sampling Analysis")
            print("=" * 60)
            print(f"\nCorpus: {corpus_path}")
            print(f"Portfolio size: £{portfolio_size}m")
            print(f"Min coverage: {min_coverage}")

            # Build LOB weights
            lob_weights = build_lob_weights_from_inputs(prop, cas, mar, prof, mot, cyb)
            print(f"\nLOB weights: {lob_weights}")

            # Import the query engine
            from portfolio_query_hierarchical import (
                PortfolioQueryEngine, SamplingConfig
            )

            # Initialize and load corpus
            full_corpus_path = get_project_root() / corpus_path
            print(f"\nLoading corpus from: {full_corpus_path}")
            engine = PortfolioQueryEngine()
            engine.load_corpus(str(full_corpus_path))
            print(f"Loaded corpus successfully")

            # Build sampling config
            sampling_config = SamplingConfig(
                coverage_cap=coverage_cap or 0.9,
                tau=tau or 0.15,
                top_k=top_k or 5,
            )
            print(f"Sampling config: coverage_cap={sampling_config.coverage_cap}, tau={sampling_config.tau}, top_k={sampling_config.top_k}")

            # Run even-year sampling
            print(f"\nRunning even-year sampling (n_per_year={n_per_year}, min_success={min_success})...")
            result = engine.query_summary_even_years(
                lob_weights=lob_weights,
                portfolio_size_m=portfolio_size,
                n_per_year=n_per_year or 200,
                min_coverage=min_coverage or 0.3,
                seed=seed,
                min_success_per_year=min_success or 10,
                sampling_config=sampling_config,
            )

            print(f"\nResults:")
            print(f"  Years included: {len(result.years_included)}")
            print(f"  Years excluded: {len(result.years_excluded)}")
            print(f"  Total scenarios: {result.n_scenarios}")

            # Format results for display
            years_count = str(len(result.years_included))
            scenarios_count = str(result.n_scenarios)
            avg_cov = f"{result.coverage.get('mean', 0):.1%}"

            # Build quantiles table
            quantile_rows = []
            percentile_to_return = {0.5: "2-year", 0.75: "4-year", 0.9: "10-year",
                                    0.95: "20-year", 0.99: "100-year", 0.995: "200-year"}
            for p, rp in percentile_to_return.items():
                raw_val = result.severity_raw.get('quantiles', {}).get(p, 0)
                adj_val = result.severity_adjusted.get('quantiles', {}).get(p, 0)
                quantile_rows.append(html.Tr([
                    html.Td(rp),
                    html.Td(f"{p:.1%}"),
                    html.Td(f"{raw_val:.1%}"),
                    html.Td(f"{adj_val:.1%}"),
                ]))

            quantiles_table = dbc.Table([
                html.Thead(html.Tr([
                    html.Th("Return Period"),
                    html.Th("Percentile"),
                    html.Th("Raw Severity"),
                    html.Th("Size-Adjusted"),
                ])),
                html.Tbody(quantile_rows)
            ], bordered=True, hover=True, size="sm")

            # Build per-year stats
            per_year_rows = []
            for year in sorted(result.years_included):
                stats = result.per_year_stats.get(year)
                if stats:
                    per_year_rows.append(html.Tr([
                        html.Td(str(year)),
                        html.Td(str(stats.attempted)),
                        html.Td(str(stats.valid)),
                        html.Td(f"{stats.valid_rate:.1%}"),
                    ]))

            per_year_table = dbc.Table([
                html.Thead(html.Tr([
                    html.Th("Year"),
                    html.Th("Attempted"),
                    html.Th("Valid"),
                    html.Th("Success Rate"),
                ])),
                html.Tbody(per_year_rows)
            ], bordered=True, hover=True, size="sm", striped=True)

            # Add excluded years info
            excluded_info = []
            if result.years_excluded:
                excluded_info.append(html.H6("Excluded Years", className="mt-3"))
                excluded_items = [html.Li(f"{y}: {reason}") for y, reason in result.years_excluded.items()]
                excluded_info.append(html.Ul(excluded_items))

            per_year_content = html.Div([per_year_table] + excluded_info)

            # Prepare results data for export
            results_data = {
                "years_included": result.years_included,
                "years_excluded": result.years_excluded,
                "n_scenarios": result.n_scenarios,
                "severity_raw": result.severity_raw,
                "severity_adjusted": result.severity_adjusted,
                "coverage": result.coverage,
                "sampling_config": result.sampling_config,
                "seed": result.seed,
                "weights_description": result.weights_description,
            }

            print("\n✅ Analysis complete!")

        return (
            html.Span("✅ Analysis complete!", className="text-success fw-bold"),
            {"display": "block"},
            results_data,
            years_count,
            scenarios_count,
            avg_cov,
            quantiles_table,
            per_year_content,
            console_output.getvalue()
        )

    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        console_output.write(f"\n❌ Error: {str(e)}\n{error_trace}")

        return (
            html.Span(f"❌ Error: {str(e)}", className="text-danger fw-bold"),
            {"display": "none"},
            None,
            "-", "-", "-",
            None,
            None,
            console_output.getvalue()
        )


# Run Year-Block Bootstrap
@app.callback(
    Output("bootstrap-status", "children"),
    Output("bootstrap-results-section", "style"),
    Output("bootstrap-results-store", "data"),
    Output("bootstrap-replicates-count", "children"),
    Output("bootstrap-years-count", "children"),
    Output("bootstrap-ci-table", "children"),
    Output("bootstrap-ci-chart", "children"),
    Output("bootstrap-distribution-detail", "children"),
    Output("analysis-console", "children", allow_duplicate=True),
    Input("run-bootstrap-btn", "n_clicks"),
    State("analysis-corpus-input", "value"),
    State("analysis-portfolio-size", "value"),
    State("analysis-min-coverage", "value"),
    State("analysis-lob-property", "value"),
    State("analysis-lob-casualty", "value"),
    State("analysis-lob-marine", "value"),
    State("analysis-lob-proflines", "value"),
    State("analysis-lob-motor", "value"),
    State("analysis-lob-cyber", "value"),
    State("bootstrap-B", "value"),
    State("bootstrap-n-per-year", "value"),
    State("bootstrap-seed", "value"),
    prevent_initial_call=True
)
def run_bootstrap_analysis(n_clicks, corpus_path, portfolio_size, min_coverage,
                           prop, cas, mar, prof, mot, cyb,
                           B, n_per_year, seed):
    """Run year-block bootstrap analysis."""
    if not n_clicks:
        raise PreventUpdate

    import io
    import sys
    from contextlib import redirect_stdout

    console_output = io.StringIO()

    try:
        with redirect_stdout(console_output):
            print("=" * 60)
            print("Year-Block Bootstrap Analysis")
            print("=" * 60)
            print(f"\nCorpus: {corpus_path}")
            print(f"Portfolio size: £{portfolio_size}m")
            print(f"Bootstrap replicates: {B}")
            print(f"Draws per year: {n_per_year}")

            # Build LOB weights
            lob_weights = build_lob_weights_from_inputs(prop, cas, mar, prof, mot, cyb)
            print(f"\nLOB weights: {lob_weights}")

            # Import the query engine
            from portfolio_query_hierarchical import PortfolioQueryEngine

            # Initialize and load corpus
            full_corpus_path = get_project_root() / corpus_path
            print(f"\nLoading corpus from: {full_corpus_path}")
            engine = PortfolioQueryEngine()
            engine.load_corpus(str(full_corpus_path))
            print(f"Loaded corpus successfully")

            # Run bootstrap
            print(f"\nRunning year-block bootstrap (B={B}, this may take a few minutes)...")
            result = engine.query_summary_year_block_bootstrap(
                lob_weights=lob_weights,
                portfolio_size_m=portfolio_size,
                B=B or 200,
                n_per_year=n_per_year or 100,
                min_coverage=min_coverage or 0.3,
                seed=seed,
            )

            print(f"\nResults:")
            print(f"  Replicates completed: {result.n_replicates}")
            print(f"  Feasible years: {len(result.feasible_years)}")

            # Format results
            replicates_count = str(result.n_replicates)
            years_count = str(len(result.feasible_years))

            # Build CI table
            ci_rows = []
            percentile_to_return = {0.5: "2-year", 0.75: "4-year", 0.9: "10-year",
                                    0.95: "20-year", 0.99: "100-year", 0.995: "200-year"}

            for p, rp in percentile_to_return.items():
                point_est = result.point_estimate.get(p, 0)
                ci_data = result.confidence_intervals.get(p, {})
                ci_90 = ci_data.get('ci_90', [0, 0])
                ci_95 = ci_data.get('ci_95', [0, 0])
                std_err = ci_data.get('std_err', 0)

                ci_rows.append(html.Tr([
                    html.Td(rp),
                    html.Td(f"{point_est:.1%}"),
                    html.Td(f"[{ci_90[0]:.1%}, {ci_90[1]:.1%}]"),
                    html.Td(f"[{ci_95[0]:.1%}, {ci_95[1]:.1%}]"),
                    html.Td(f"{std_err:.2%}"),
                ]))

            ci_table = dbc.Table([
                html.Thead(html.Tr([
                    html.Th("Return Period"),
                    html.Th("Point Estimate"),
                    html.Th("90% CI"),
                    html.Th("95% CI"),
                    html.Th("Std Error"),
                ])),
                html.Tbody(ci_rows)
            ], bordered=True, hover=True, size="sm")

            # Build CI chart using Plotly
            import plotly.graph_objects as go

            return_periods = list(percentile_to_return.values())
            point_estimates = [result.point_estimate.get(p, 0) * 100 for p in percentile_to_return.keys()]
            ci_lower = [result.confidence_intervals.get(p, {}).get('ci_95', [0, 0])[0] * 100
                       for p in percentile_to_return.keys()]
            ci_upper = [result.confidence_intervals.get(p, {}).get('ci_95', [0, 0])[1] * 100
                       for p in percentile_to_return.keys()]

            fig = go.Figure()

            # Add CI band
            fig.add_trace(go.Scatter(
                x=return_periods + return_periods[::-1],
                y=ci_upper + ci_lower[::-1],
                fill='toself',
                fillcolor='rgba(49, 130, 206, 0.2)',
                line=dict(color='rgba(49, 130, 206, 0)'),
                name='95% CI',
                showlegend=True
            ))

            # Add point estimates
            fig.add_trace(go.Scatter(
                x=return_periods,
                y=point_estimates,
                mode='lines+markers',
                name='Point Estimate',
                line=dict(color='#3182ce', width=3),
                marker=dict(size=10)
            ))

            fig.update_layout(
                title="Return Levels with 95% Confidence Intervals",
                xaxis_title="Return Period",
                yaxis_title="Severity (%)",
                height=400,
                showlegend=True,
                legend=dict(orientation='h', y=1.1)
            )

            ci_chart = dcc.Graph(figure=fig, config={'displayModeBar': True})

            # Bootstrap distribution detail
            dist_detail = html.Div([
                html.P(f"Bootstrap replicates: {result.n_replicates}"),
                html.P(f"Feasible years: {result.feasible_years}"),
                html.P(f"Seed: {result.seed}"),
            ])

            # Prepare results data for export
            results_data = {
                "point_estimate": {str(k): v for k, v in result.point_estimate.items()},
                "confidence_intervals": {str(k): v for k, v in result.confidence_intervals.items()},
                "n_replicates": result.n_replicates,
                "feasible_years": result.feasible_years,
                "excluded_years": result.excluded_years,
                "seed": result.seed,
            }

            print("\n✅ Bootstrap analysis complete!")

        return (
            html.Span("✅ Bootstrap complete!", className="text-success fw-bold"),
            {"display": "block"},
            results_data,
            replicates_count,
            years_count,
            ci_table,
            ci_chart,
            dist_detail,
            console_output.getvalue()
        )

    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        console_output.write(f"\n❌ Error: {str(e)}\n{error_trace}")

        return (
            html.Span(f"❌ Error: {str(e)}", className="text-danger fw-bold"),
            {"display": "none"},
            None,
            "-", "-",
            None,
            None,
            None,
            console_output.getvalue()
        )


# Export even-year results
@app.callback(
    Output("even-year-export-status", "children"),
    Input("even-year-export-btn", "n_clicks"),
    State("even-year-results-store", "data"),
    State("analysis-corpus-input", "value"),
    prevent_initial_call=True
)
def export_even_year_results(n_clicks, results_data, corpus_path):
    """Export even-year results to JSON."""
    if not n_clicks or not results_data:
        raise PreventUpdate

    try:
        from datetime import datetime

        # Determine output path
        corpus_dir = Path(corpus_path).parent if corpus_path else get_project_root() / "results"
        output_dir = get_project_root() / corpus_dir
        output_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = output_dir / f"even_year_results_{timestamp}.json"

        with open(output_path, 'w') as f:
            json.dump(results_data, f, indent=2, default=str)

        return dbc.Alert([
            html.Strong("✅ Exported: "),
            html.Code(str(output_path))
        ], color="success", className="mt-2")

    except Exception as e:
        return dbc.Alert(f"❌ Export failed: {str(e)}", color="danger", className="mt-2")


# Export bootstrap results (JSON)
@app.callback(
    Output("bootstrap-export-status", "children"),
    Input("bootstrap-export-json-btn", "n_clicks"),
    State("bootstrap-results-store", "data"),
    State("analysis-corpus-input", "value"),
    prevent_initial_call=True
)
def export_bootstrap_json(n_clicks, results_data, corpus_path):
    """Export bootstrap results to JSON."""
    if not n_clicks or not results_data:
        raise PreventUpdate

    try:
        from datetime import datetime

        corpus_dir = Path(corpus_path).parent if corpus_path else get_project_root() / "results"
        output_dir = get_project_root() / corpus_dir
        output_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = output_dir / f"bootstrap_results_{timestamp}.json"

        with open(output_path, 'w') as f:
            json.dump(results_data, f, indent=2, default=str)

        return dbc.Alert([
            html.Strong("✅ Exported: "),
            html.Code(str(output_path))
        ], color="success", className="mt-2")

    except Exception as e:
        return dbc.Alert(f"❌ Export failed: {str(e)}", color="danger", className="mt-2")


# Export bootstrap CIs to CSV
@app.callback(
    Output("bootstrap-export-status", "children", allow_duplicate=True),
    Input("bootstrap-export-csv-btn", "n_clicks"),
    State("bootstrap-results-store", "data"),
    State("analysis-corpus-input", "value"),
    prevent_initial_call=True
)
def export_bootstrap_csv(n_clicks, results_data, corpus_path):
    """Export bootstrap confidence intervals to CSV."""
    if not n_clicks or not results_data:
        raise PreventUpdate

    try:
        from datetime import datetime
        import csv

        corpus_dir = Path(corpus_path).parent if corpus_path else get_project_root() / "results"
        output_dir = get_project_root() / corpus_dir
        output_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = output_dir / f"bootstrap_ci_{timestamp}.csv"

        percentile_to_return = {"0.5": "2-year", "0.75": "4-year", "0.9": "10-year",
                                "0.95": "20-year", "0.99": "100-year", "0.995": "200-year"}

        with open(output_path, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(["Return_Period", "Percentile", "Point_Estimate",
                            "CI_90_Lower", "CI_90_Upper", "CI_95_Lower", "CI_95_Upper", "Std_Error"])

            for p_str, rp in percentile_to_return.items():
                point_est = results_data.get("point_estimate", {}).get(p_str, 0)
                ci_data = results_data.get("confidence_intervals", {}).get(p_str, {})
                ci_90 = ci_data.get('ci_90', [0, 0])
                ci_95 = ci_data.get('ci_95', [0, 0])
                std_err = ci_data.get('std_err', 0)

                writer.writerow([rp, p_str, point_est, ci_90[0], ci_90[1],
                                ci_95[0], ci_95[1], std_err])

        return dbc.Alert([
            html.Strong("✅ CSV Exported: "),
            html.Code(str(output_path))
        ], color="success", className="mt-2")

    except Exception as e:
        return dbc.Alert(f"❌ CSV Export failed: {str(e)}", color="danger", className="mt-2")


# =============================================================================
# Callbacks - Data Extraction Tab
# =============================================================================

# Global queue for extraction output
extraction_output_queue = queue.Queue()
extraction_process = None


@app.callback(
    [Output("extraction-pdf-status", "children"),
     Output("extraction-quality-status", "children"),
     Output("extraction-movements-status", "children"),
     Output("extraction-size-status", "children"),
     Output("extraction-corpus-status", "children"),
     Output("extraction-prepared-status", "children"),
     Output("extraction-bias-status", "children"),
     Output("extraction-bias-details", "children"),
     Output("extraction-status-store", "data")],
    [Input("extraction-refresh-btn", "n_clicks"),
     Input("tabs", "active_tab"),
     Input("extraction-interval", "n_intervals")],
    prevent_initial_call=False
)
def update_extraction_status(n_clicks, active_tab, n_intervals):
    """Update all status cards with current pipeline status."""
    status = get_data_extraction_status()

    # PDF Status
    pdf_content = [
        html.H3(f"{status['pdfs_downloaded']}", className="text-primary mb-0"),
        html.P("PDFs Downloaded", className="small text-muted mb-1"),
        html.P(f"{status['syndicates_count']} syndicates", className="small mb-0"),
        html.P(f"Years: {min(status['years_available']) if status['years_available'] else 'N/A'}-"
               f"{max(status['years_available']) if status['years_available'] else 'N/A'}",
               className="small text-muted mb-0"),
    ]

    # Quality Status
    if status['quality_classified']:
        qb = status['quality_breakdown']
        quality_content = [
            html.H3("[OK]", className="text-success mb-0"),
            html.P("Classified", className="small text-muted mb-1"),
            html.P(f"VERY_HIGH: {qb.get('VERY_HIGH', 0)}", className="small mb-0"),
            html.P(f"HIGH: {qb.get('HIGH', 0)} | MED: {qb.get('MEDIUM', 0)}",
                   className="small text-muted mb-0"),
            html.P(f"Updated: {status['quality_report_date']}", className="small text-muted mb-0"),
        ]
    else:
        quality_content = [
            html.H3("-", className="text-muted mb-0"),
            html.P("Not Run", className="small text-muted mb-1"),
            html.P("Run quality classification first", className="small text-warning mb-0"),
        ]

    # Movements Status
    if status['movements_extracted'] > 0:
        movements_content = [
            html.H3(f"{status['movements_extracted']}", className="text-success mb-0"),
            html.P("Movements", className="small text-muted mb-1"),
            html.P(f"Updated: {status['extraction_date']}", className="small text-muted mb-0"),
        ]
    else:
        movements_content = [
            html.H3("-", className="text-muted mb-0"),
            html.P("Not Extracted", className="small text-muted mb-1"),
            html.P("Run ChatGPT extraction", className="small text-warning mb-0"),
        ]

    # Size Metrics Status
    if status['size_metrics_count'] > 0:
        size_content = [
            html.H3(f"{status['size_metrics_count']}", className="text-warning mb-0"),
            html.P("Records with Size Data", className="small text-muted mb-1"),
            html.P(f"Updated: {status['size_metrics_date']}", className="small text-muted mb-0"),
        ]
    else:
        size_content = [
            html.H3("-", className="text-muted mb-0"),
            html.P("Not Extracted", className="small text-muted mb-1"),
            html.P("Run size metrics extraction", className="small text-warning mb-0"),
        ]

    # Corpus Status
    if status['corpus_movements'] > 0:
        sev_pct = (status['corpus_with_severity'] / status['corpus_movements'] * 100
                   if status['corpus_movements'] > 0 else 0)
        corpus_content = [
            html.H3(f"{status['corpus_movements']}", className="text-info mb-0"),
            html.P("Total Movements", className="small text-muted mb-1"),
            html.P(f"With severity: {status['corpus_with_severity']} ({sev_pct:.0f}%)",
                   className="small mb-0"),
            html.P(f"Updated: {status['corpus_date']}", className="small text-muted mb-0"),
        ]
    else:
        corpus_content = [
            html.H3("-", className="text-muted mb-0"),
            html.P("Not Created", className="small text-muted mb-1"),
            html.P("Run corpus merge", className="small text-warning mb-0"),
        ]

    # Prepared Data Status
    if status['prepared_movements'] > 0:
        prepared_content = [
            html.H3(f"{status['prepared_movements']}", className="text-info mb-0"),
            html.P("Ready for Generation", className="small text-muted mb-1"),
            html.P("[OK] Data prepared", className="small text-success mb-0"),
            html.P(f"Updated: {status['prepared_date']}", className="small text-muted mb-0"),
        ]
    else:
        prepared_content = [
            html.H3("-", className="text-muted mb-0"),
            html.P("Not Prepared", className="small text-muted mb-1"),
            html.P("Run data preparation", className="small text-warning mb-0"),
        ]

    # Filtering Bias Status
    bias_info = status.get('filtering_bias')
    if bias_info and 'error' not in bias_info:
        n_biases = len(bias_info.get('biased_fields', []))
        stages = bias_info.get('stages', [])

        # Find the two key stages
        direction_stage = next((s for s in stages if s['name'] == 'direction_filter'), None)
        severity_stage = next((s for s in stages if s['name'] == 'severity_data_filter'), None)

        # Calculate retention for severity stage only (where bias matters)
        if severity_stage:
            severity_retention_pct = round(100 * severity_stage['output'] / severity_stage['input'], 1) if severity_stage['input'] > 0 else 0
        else:
            severity_retention_pct = bias_info.get('retention_pct', 0)

        if n_biases == 0:
            bias_class = "text-success"
            bias_icon = "[OK]"
        elif n_biases <= 2:
            bias_class = "text-warning"
            bias_icon = "[!]"
        else:
            bias_class = "text-danger"
            bias_icon = "[!!]"

        # Build stage-by-stage breakdown
        stage_elements = []
        if direction_stage:
            stage_elements.append(
                html.P([
                    html.Strong("1. Direction filter: ", className="text-info"),
                    f"{direction_stage['input']} → {direction_stage['output']} ",
                    html.Span("(intentional)", className="text-muted")
                ], className="small mb-1")
            )
        if severity_stage:
            stage_elements.append(
                html.P([
                    html.Strong("2. Severity data: ", className="text-warning"),
                    f"{severity_stage['input']} → {severity_stage['output']} ",
                    html.Span(f"({severity_retention_pct}% retained)", className="text-muted")
                ], className="small mb-0")
            )

        bias_content = [
            html.H3(f"{bias_icon} {n_biases} biases", className=f"{bias_class} mb-0"),
            html.P(f"Data filter retention: {severity_retention_pct}%", className="small text-muted mb-1"),
        ] + stage_elements

        # Bias details
        bias_details = []
        for test in bias_info.get('bias_tests', []):
            if test['significant']:
                p_val = test['p_value']
                p_str = f"p={p_val:.4f}" if p_val and p_val == p_val else "p=N/A"
                bias_details.append(
                    html.Div([
                        html.Strong(f"[!] {test['field']}", className="text-danger"),
                        html.Span(f" ({p_str})", className="text-muted small"),
                        html.P(test['interpretation'][:100] + "..." if len(test['interpretation']) > 100 else test['interpretation'],
                               className="small text-muted mb-1")
                    ])
                )

        if not bias_details:
            bias_details = [html.P("No significant biases detected", className="text-success small")]
    elif bias_info and 'error' in bias_info:
        bias_content = [
            html.H3("[?]", className="text-warning mb-0"),
            html.P("Error running diagnostics", className="small text-muted mb-1"),
            html.P(str(bias_info['error'])[:50], className="small text-danger mb-0"),
        ]
        bias_details = [html.P(f"Error: {bias_info['error']}", className="text-danger small")]
    else:
        bias_content = [
            html.H3("-", className="text-muted mb-0"),
            html.P("Not Analyzed", className="small text-muted mb-1"),
            html.P("Create corpus first", className="small text-warning mb-0"),
        ]
        bias_details = [html.P("Run filtering diagnostics to see bias tests", className="text-muted small")]

    return (
        pdf_content,
        quality_content,
        movements_content,
        size_content,
        corpus_content,
        prepared_content,
        bias_content,
        bias_details,
        status
    )


def run_extraction_command(command: str, description: str):
    """Run an extraction command in a subprocess and capture output."""
    global extraction_process

    project_root = get_project_root()

    # Clear the queue
    while not extraction_output_queue.empty():
        try:
            extraction_output_queue.get_nowait()
        except queue.Empty:
            break

    extraction_output_queue.put(f"[{datetime.now().strftime('%H:%M:%S')}] Starting: {description}\n")
    extraction_output_queue.put(f"Command: {command}\n")
    extraction_output_queue.put("-" * 60 + "\n")

    try:
        extraction_process = subprocess.Popen(
            command,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            cwd=str(project_root)
        )

        for line in iter(extraction_process.stdout.readline, ''):
            extraction_output_queue.put(line)

        extraction_process.wait()
        return_code = extraction_process.returncode

        extraction_output_queue.put("-" * 60 + "\n")
        if return_code == 0:
            extraction_output_queue.put(f"[{datetime.now().strftime('%H:%M:%S')}] ✓ Completed successfully\n")
        else:
            extraction_output_queue.put(f"[{datetime.now().strftime('%H:%M:%S')}] ✗ Failed with code {return_code}\n")

    except Exception as e:
        extraction_output_queue.put(f"\n❌ Error: {str(e)}\n")

    extraction_output_queue.put("__DONE__")


@app.callback(
    [Output("extraction-console", "children"),
     Output("extraction-interval", "disabled"),
     Output("extraction-running-store", "data"),
     Output("extraction-output-store", "data")],
    [Input("extraction-download-btn", "n_clicks"),
     Input("extraction-extract-btn", "n_clicks"),
     Input("extraction-merge-btn", "n_clicks"),
     Input("extraction-quality-btn", "n_clicks"),
     Input("extraction-chatgpt-btn", "n_clicks"),
     Input("extraction-sizemetrics-btn", "n_clicks"),
     Input("extraction-corpusmerge-btn", "n_clicks"),
     Input("extraction-interval", "n_intervals")],
    [State("extraction-running-store", "data"),
     State("extraction-output-store", "data")],
    prevent_initial_call=True
)
def handle_extraction_actions(
    n_download, n_extract, n_merge,
    n_quality, n_chatgpt, n_sizemetrics, n_corpusmerge,
    n_intervals,
    is_running, current_output
):
    """Handle all extraction action buttons and console updates."""
    global extraction_process

    ctx = callback_context
    if not ctx.triggered:
        raise PreventUpdate

    trigger_id = ctx.triggered[0]['prop_id'].split('.')[0]

    # If interval triggered, update console from queue
    if trigger_id == "extraction-interval":
        new_output = current_output or ""
        done = False

        while not extraction_output_queue.empty():
            try:
                line = extraction_output_queue.get_nowait()
                if line == "__DONE__":
                    done = True
                else:
                    new_output += line
            except queue.Empty:
                break

        if done:
            return new_output, True, False, new_output
        else:
            return new_output, False, True, new_output

    # If already running, don't start another process
    if is_running:
        return current_output or "Process already running...", False, True, current_output

    # Determine which command to run
    command = None
    description = None
    project_root = get_project_root()

    if trigger_id == "extraction-download-btn":
        command = "python scripts/lloyds_scraper.py --all"
        description = "Downloading syndicate reports from Lloyd's website"

    elif trigger_id == "extraction-extract-btn":
        # Combined extraction: quality (if needed) + chatgpt + size metrics
        # Skip quality classification if quality_report.json already exists
        quality_report = get_project_root() / "syndicate_reports" / "quality_report.json"
        if quality_report.exists():
            # Quality report exists - skip to ChatGPT extraction
            command = (
                "python scripts/syndicate_summarizer.py --input syndicate_reports/quality_report.json && "
                "python scripts/stress_test/extract_size_metrics.py extract "
                "--pdf-dir syndicate_reports/pdfs --output size_metrics.json"
            )
            description = "Running extraction pipeline (ChatGPT + size metrics) - quality report exists"
        else:
            # Need to run quality classification first
            command = (
                "python scripts/quality_classifier.py --pdf-dir syndicate_reports/pdfs && "
                "python scripts/syndicate_summarizer.py --input syndicate_reports/quality_report.json && "
                "python scripts/stress_test/extract_size_metrics.py extract "
                "--pdf-dir syndicate_reports/pdfs --output size_metrics.json"
            )
            description = "Running full extraction pipeline (quality + ChatGPT + size metrics)"

    elif trigger_id == "extraction-merge-btn":
        # Merge corpus + prepare data
        command = (
            "python scripts/merge_corpus.py "
            "--syndicate-file results/syndicate/standardized_syndicate_movements.json "
            "--market-dir results/market "
            "--output-dir results/combined && "
            "python scripts/stress_test/data_preparation.py "
            "--corpus results/combined/unified_corpus.json "
            "--output results/stress_test/prepared_data.json "
            "--direction strengthening"
        )
        description = "Merging corpus and preparing data for generation"

    elif trigger_id == "extraction-quality-btn":
        command = "python scripts/quality_classifier.py --pdf-dir syndicate_reports/pdfs"
        description = "Running quality classification"

    elif trigger_id == "extraction-chatgpt-btn":
        command = "python scripts/syndicate_summarizer.py --input syndicate_reports/quality_report.json"
        description = "Running ChatGPT extraction"

    elif trigger_id == "extraction-sizemetrics-btn":
        command = (
            "python scripts/stress_test/extract_size_metrics.py extract "
            "--pdf-dir syndicate_reports/pdfs --output size_metrics.json"
        )
        description = "Extracting size metrics from PDFs"

    elif trigger_id == "extraction-corpusmerge-btn":
        command = (
            "python scripts/merge_corpus.py "
            "--syndicate-file results/syndicate/standardized_syndicate_movements.json "
            "--market-dir results/market "
            "--output-dir results/combined"
        )
        description = "Merging corpus files"

    if command:
        # Start the command in a thread
        thread = threading.Thread(
            target=run_extraction_command,
            args=(command, description),
            daemon=True
        )
        thread.start()

        return f"Starting: {description}...\n", False, True, ""

    raise PreventUpdate


@app.callback(
    Output("extraction-console", "children", allow_duplicate=True),
    Input("extraction-bias-report-btn", "n_clicks"),
    State("extraction-status-store", "data"),
    prevent_initial_call=True
)
def generate_bias_report(n_clicks, status):
    """Generate a detailed filtering bias report."""
    if not n_clicks:
        raise PreventUpdate

    bias_info = status.get('filtering_bias')
    if not bias_info or 'error' in bias_info:
        return "Error: No filtering bias data available. Refresh status first."

    # Build detailed report
    lines = []
    lines.append("=" * 70)
    lines.append("DATA FILTERING PIPELINE REPORT")
    lines.append("=" * 70)
    lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")

    # Find stages
    stages = bias_info.get('stages', [])
    direction_stage = next((s for s in stages if s['name'] == 'direction_filter'), None)
    severity_stage = next((s for s in stages if s['name'] == 'severity_data_filter'), None)

    # Summary with clear stage breakdown
    lines.append("PIPELINE SUMMARY")
    lines.append("-" * 40)
    lines.append(f"Total corpus movements: {bias_info['total']}")
    lines.append("")

    if direction_stage:
        lines.append("Stage 1: DIRECTION FILTER (intentional)")
        lines.append(f"  {direction_stage['input']} -> {direction_stage['output']} movements")
        lines.append(f"  Purpose: Study focuses on 'strengthening' movements only")
        lines.append(f"  Dropped: {direction_stage['dropped']} non-strengthening movements")
        lines.append("")

    if severity_stage:
        sev_retention = (severity_stage['output'] / severity_stage['input'] * 100) if severity_stage['input'] > 0 else 0
        lines.append("Stage 2: SEVERITY DATA FILTER (bias concern)")
        lines.append(f"  {severity_stage['input']} -> {severity_stage['output']} movements")
        lines.append(f"  Retention: {sev_retention:.1f}%")
        lines.append(f"  Dropped: {severity_stage['dropped']} movements lacking severity data")
        lines.append("")

    lines.append(f"Final dataset: {bias_info['after_filter']} movements")
    lines.append(f"Significant biases detected: {', '.join(bias_info['biased_fields']) or 'None'}")
    lines.append("")

    # Filtering stages - detailed breakdown
    lines.append("DETAILED STAGE BREAKDOWN")
    lines.append("-" * 40)
    for stage in stages:
        drop_pct = (stage['dropped'] / stage['input'] * 100) if stage['input'] > 0 else 0
        stage_type = "(INTENTIONAL)" if stage['name'] == 'direction_filter' else "(BIAS TESTED)"
        lines.append(f"\n{stage['name']} {stage_type}:")
        lines.append(f"  Input: {stage['input']} -> Output: {stage['output']}")
        lines.append(f"  Dropped: {stage['dropped']} ({drop_pct:.1f}%)")
        if stage.get('reasons'):
            lines.append("  Reasons:")
            for reason, count in stage['reasons'].items():
                lines.append(f"    - {reason}: {count}")
    lines.append("")

    # Bias tests
    lines.append("SEVERITY DATA FILTER BIAS TESTS")
    lines.append("-" * 40)
    lines.append("(Tests whether Stage 2 filter introduces systematic bias)")
    lines.append("")
    for test in bias_info.get('bias_tests', []):
        sig_marker = "[SIGNIFICANT]" if test['significant'] else "[not significant]"
        p_val = test['p_value']
        p_str = f"p={p_val:.6f}" if p_val and p_val == p_val else "p=N/A"
        lines.append(f"\n{test['name']} ({test['field']}):")
        lines.append(f"  {sig_marker} {p_str}")
        lines.append(f"  {test['interpretation']}")
    lines.append("")

    # Academic implications
    lines.append("ACADEMIC IMPLICATIONS")
    lines.append("-" * 40)
    n_sig = len([t for t in bias_info.get('bias_tests', []) if t['significant']])
    if n_sig == 0:
        lines.append("No significant biases detected. The filtered sample appears")
        lines.append("representative of the original corpus.")
    elif n_sig <= 2:
        lines.append("Some biases detected. Consider:")
        lines.append("  1. Document these biases in the methodology section")
        lines.append("  2. Run sensitivity analysis with different filters")
        lines.append("  3. Use estimated severity mode to increase sample size")
    else:
        lines.append("[!] Multiple significant biases detected!")
        lines.append("The filtered sample may not be representative.")
        lines.append("Strong recommendations:")
        lines.append("  1. Use --severity-mode estimated to recover more data")
        lines.append("  2. Consider including release movements (direction=release)")
        lines.append("  3. Run extract_size_metrics.py to add reserve data")
        lines.append("  4. Document all biases in limitations section")
        lines.append("  5. Run comparison analysis between strict and estimated modes")
    lines.append("")

    lines.append("=" * 70)
    lines.append("END OF REPORT")
    lines.append("=" * 70)

    return "\n".join(lines)


# =============================================================================
# Main
# =============================================================================

if __name__ == "__main__":
    print("="*60)
    print("Lloyd's Reserve Stress Test Generator")
    print("="*60)
    print(f"\nProject root: {get_project_root()}")
    print(f"Newest library: {find_newest_library() or 'None found'}")
    print(f"\nStarting server at http://localhost:8050")
    print("Press Ctrl+C to stop\n")
    
    # Run without debug mode to avoid Dash devtools errors
    # Set debug=True only if you need hot-reloading during development
    app.run(debug=False, port=8050)
