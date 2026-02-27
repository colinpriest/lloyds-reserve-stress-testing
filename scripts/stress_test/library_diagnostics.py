"""
Library Diagnostics Module

Comprehensive validation and diagnostics for generated scenario libraries:
- Severity distribution comparison (synthetic vs historical)
- Semantic coverage analysis with embeddings
- Statistical tests with bootstrap (handles different sample sizes)
- Coherence analysis
- Cause category distribution
- LOB coverage analysis

Generates:
- Interactive Plotly visualizations
- Statistical test results
- HTML diagnostic reports
"""

import json
import logging
import numpy as np
import pandas as pd
from pathlib import Path
from typing import List, Dict, Tuple, Optional, Any
from dataclasses import dataclass, field, asdict
from datetime import datetime
from collections import Counter
import warnings

# Statistical and ML imports
from scipy import stats
from scipy.spatial.distance import cdist
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.decomposition import PCA
from sklearn.cluster import KMeans
from sklearn.metrics.pairwise import rbf_kernel, cosine_similarity
from sklearn.neighbors import NearestNeighbors

logger = logging.getLogger(__name__)


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class SeverityDiagnostics:
    """Severity distribution diagnostics."""
    # Basic stats
    historical_n: int
    synthetic_n: int
    historical_mean: float
    synthetic_mean: float
    historical_std: float
    synthetic_std: float
    historical_median: float
    synthetic_median: float
    historical_min: float
    historical_max: float
    synthetic_min: float
    synthetic_max: float
    
    # Percentiles
    historical_percentiles: Dict[str, float]
    synthetic_percentiles: Dict[str, float]
    
    # Statistical tests
    ks_statistic: float
    ks_pvalue: float
    mmd_statistic: float
    mmd_pvalue: float  # Bootstrap p-value
    js_divergence: float
    
    # Pass/fail
    ks_pass: bool
    mmd_pass: bool
    js_pass: bool
    overall_pass: bool


@dataclass
class SemanticDiagnostics:
    """Semantic coverage diagnostics."""
    # Coverage metrics
    mean_cosine_similarity: float
    mmd_statistic: float
    mmd_pvalue: float  # Bootstrap p-value
    js_divergence: Optional[float]
    
    # Cluster analysis
    n_clusters: int
    cluster_coverage: float  # % of historical clusters covered
    cluster_distribution_distance: float
    
    # Outlier analysis
    outlier_rate: float  # % of synthetic that are outliers
    
    # Diversity
    historical_diversity: float
    synthetic_diversity: float
    diversity_ratio: float
    
    # Pass/fail
    cosine_pass: bool
    mmd_pass: bool
    cluster_pass: bool
    outlier_pass: bool
    diversity_pass: bool
    overall_pass: bool


@dataclass
class CauseDistributionDiagnostics:
    """Cause category distribution diagnostics."""
    historical_distribution: Dict[str, float]
    synthetic_distribution: Dict[str, float]
    chi_square_statistic: float
    chi_square_pvalue: float
    js_divergence: float
    missing_categories: List[str]
    over_represented: List[str]
    under_represented: List[str]
    overall_pass: bool


@dataclass
class LOBCoverageDiagnostics:
    """Line of Business coverage diagnostics."""
    historical_lobs: List[str]
    synthetic_lobs: List[str]
    missing_lobs: List[str]
    coverage_rate: float
    lob_frequency_historical: Dict[str, int]
    lob_frequency_synthetic: Dict[str, int]
    chi_square_pvalue: float
    overall_pass: bool


@dataclass
class CoherenceDiagnostics:
    """Text-numeric coherence diagnostics."""
    coherence_rate: float
    n_coherent: int
    n_incoherent: int
    mean_z_score: float
    incoherent_examples: List[Dict]
    overall_pass: bool


@dataclass
class LibraryDiagnosticsResult:
    """Complete library diagnostics result."""
    timestamp: str
    library_path: str
    
    # Component diagnostics
    severity: SeverityDiagnostics
    semantic: SemanticDiagnostics
    cause_distribution: CauseDistributionDiagnostics
    lob_coverage: LOBCoverageDiagnostics
    coherence: CoherenceDiagnostics
    
    # Overall scores
    severity_score: float
    semantic_score: float
    cause_score: float
    lob_score: float
    coherence_score: float
    overall_score: float
    overall_grade: str
    
    # Recommendations
    recommendations: List[str]


# =============================================================================
# Statistical Tests
# =============================================================================

def compute_mmd(X: np.ndarray, Y: np.ndarray, gamma: float = 1.0) -> float:
    """
    Compute Maximum Mean Discrepancy between two samples.
    
    MMD(P, Q) = E[k(x,x')] - 2E[k(x,y)] + E[k(y,y')]
    """
    K_XX = rbf_kernel(X, X, gamma=gamma)
    K_YY = rbf_kernel(Y, Y, gamma=gamma)
    K_XY = rbf_kernel(X, Y, gamma=gamma)
    
    n = len(X)
    m = len(Y)
    
    # Unbiased estimator
    np.fill_diagonal(K_XX, 0)
    np.fill_diagonal(K_YY, 0)
    
    mmd = (K_XX.sum() / (n * (n - 1)) + 
           K_YY.sum() / (m * (m - 1)) - 
           2 * K_XY.sum() / (n * m))
    
    return max(0, mmd)


def bootstrap_mmd_pvalue(X: np.ndarray, Y: np.ndarray, 
                         observed_mmd: float,
                         n_bootstrap: int = 1000,
                         gamma: float = 1.0) -> Tuple[float, np.ndarray]:
    """
    Compute p-value for MMD using permutation bootstrap.
    
    Handles different sample sizes by pooling and resampling.
    """
    n, m = len(X), len(Y)
    pooled = np.vstack([X, Y])
    
    null_mmds = []
    
    for i in range(n_bootstrap):
        # Permute pooled data
        perm = np.random.permutation(n + m)
        X_perm = pooled[perm[:n]]
        Y_perm = pooled[perm[n:]]
        
        mmd_perm = compute_mmd(X_perm, Y_perm, gamma=gamma)
        null_mmds.append(mmd_perm)
        
        if (i + 1) % 200 == 0:
            logger.debug(f"Bootstrap MMD: {i+1}/{n_bootstrap}")
    
    null_mmds = np.array(null_mmds)
    p_value = (null_mmds >= observed_mmd).mean()
    
    return p_value, null_mmds


def compute_js_divergence(P: np.ndarray, Q: np.ndarray, n_bins: int = 50) -> float:
    """
    Compute Jensen-Shannon divergence between two distributions.
    Uses histogram-based density estimation.
    """
    # Combine range
    combined = np.concatenate([P, Q])
    bins = np.linspace(combined.min(), combined.max(), n_bins + 1)
    
    # Compute histograms (as probability distributions)
    p_hist, _ = np.histogram(P, bins=bins, density=True)
    q_hist, _ = np.histogram(Q, bins=bins, density=True)
    
    # Add small epsilon to avoid log(0)
    eps = 1e-10
    p_hist = p_hist + eps
    q_hist = q_hist + eps
    
    # Normalize
    p_hist = p_hist / p_hist.sum()
    q_hist = q_hist / q_hist.sum()
    
    # JS divergence
    m = 0.5 * (p_hist + q_hist)
    js = 0.5 * (stats.entropy(p_hist, m) + stats.entropy(q_hist, m))
    
    return js


def compute_cluster_metrics(X_real: np.ndarray, X_synth: np.ndarray, 
                           n_clusters: int = 10) -> Dict[str, float]:
    """
    Compute cluster-based coverage metrics.
    """
    # Fit clusters on real data
    kmeans = KMeans(n_clusters=min(n_clusters, len(X_real) // 5), 
                    random_state=42, n_init=10)
    real_clusters = kmeans.fit_predict(X_real)
    
    # Predict clusters for synthetic
    synth_clusters = kmeans.predict(X_synth)
    
    # Cluster distribution
    real_dist = np.bincount(real_clusters, minlength=kmeans.n_clusters) / len(X_real)
    synth_dist = np.bincount(synth_clusters, minlength=kmeans.n_clusters) / len(X_synth)
    
    # Coverage: how many real clusters have synthetic representation
    real_cluster_counts = Counter(real_clusters)
    synth_cluster_counts = Counter(synth_clusters)
    
    covered_clusters = sum(1 for c in real_cluster_counts if synth_cluster_counts.get(c, 0) > 0)
    coverage = covered_clusters / len(real_cluster_counts)
    
    # Distribution distance (L1)
    distribution_distance = np.abs(real_dist - synth_dist).sum() / 2
    
    return {
        'n_clusters': kmeans.n_clusters,
        'coverage': coverage,
        'distribution_distance': distribution_distance,
        'real_distribution': real_dist.tolist(),
        'synth_distribution': synth_dist.tolist()
    }


def compute_outlier_rate(X_real: np.ndarray, X_synth: np.ndarray,
                         threshold_percentile: float = 95) -> float:
    """
    Compute rate of synthetic samples that are outliers.
    
    An outlier is a synthetic sample whose distance to nearest real sample
    exceeds the threshold_percentile of real-to-real distances.
    """
    # Fit nearest neighbors on real data
    nn = NearestNeighbors(n_neighbors=min(5, len(X_real)), metric='cosine')
    nn.fit(X_real)
    
    # Real-to-real distances (for threshold)
    real_distances, _ = nn.kneighbors(X_real)
    real_nn_dists = real_distances[:, 1]  # Exclude self (distance 0)
    threshold = np.percentile(real_nn_dists, threshold_percentile)
    
    # Synthetic-to-real distances
    synth_distances, _ = nn.kneighbors(X_synth)
    synth_nn_dists = synth_distances[:, 0]  # Nearest real neighbor
    
    # Outlier rate
    outliers = (synth_nn_dists > threshold).sum()
    outlier_rate = outliers / len(X_synth)
    
    return outlier_rate


def compute_diversity(X: np.ndarray, sample_size: int = 500) -> float:
    """
    Compute average pairwise cosine distance as diversity measure.
    """
    if len(X) > sample_size:
        idx = np.random.choice(len(X), sample_size, replace=False)
        X = X[idx]
    
    # Pairwise cosine distances
    cos_sim = cosine_similarity(X)
    np.fill_diagonal(cos_sim, 0)
    
    # Average distance (1 - similarity)
    n = len(X)
    avg_distance = (1 - cos_sim).sum() / (n * (n - 1))
    
    return avg_distance


# =============================================================================
# Main Diagnostics Class
# =============================================================================

class LibraryDiagnostics:
    """
    Comprehensive diagnostics for generated scenario libraries.
    """
    
    # Thresholds
    THRESHOLDS = {
        # Severity
        'ks_pvalue': 0.05,  # p >= 0.05 to pass
        'mmd_severity': 0.10,
        'js_severity': 0.15,
        
        # Semantic
        'cosine_similarity': 0.60,  # >= 0.60 to pass
        'mmd_semantic': 0.10,
        'cluster_coverage': 0.80,  # >= 80% clusters covered
        'cluster_distance': 0.30,
        'outlier_rate': 0.20,  # <= 20% outliers
        'diversity_ratio_low': 0.70,
        'diversity_ratio_high': 1.30,
        
        # Cause distribution
        'cause_chi_pvalue': 0.05,
        'cause_js': 0.20,
        
        # LOB
        'lob_coverage': 0.90,  # >= 90% LOBs covered
        
        # Coherence
        'coherence_rate': 0.70,  # >= 70% coherent
    }
    
    def __init__(self, 
                 library_path: str,
                 corpus_path: Optional[str] = None,
                 n_bootstrap: int = 500):
        """
        Initialize diagnostics.
        
        Args:
            library_path: Path to scenario library JSON
            corpus_path: Path to historical corpus JSON (optional, will try to find)
            n_bootstrap: Number of bootstrap iterations for MMD p-value
        """
        self.library_path = Path(library_path)
        self.n_bootstrap = n_bootstrap
        
        # Load library
        if self.library_path.is_file():
            with open(self.library_path, 'r') as f:
                self.library_data = json.load(f)
            self.library_dir = self.library_path.parent
        else:
            with open(self.library_path / "scenario_library.json", 'r') as f:
                self.library_data = json.load(f)
            self.library_dir = self.library_path
        
        self.scenarios = self.library_data.get('scenarios', [])
        logger.info(f"Loaded {len(self.scenarios)} synthetic scenarios")
        
        # Load corpus
        if corpus_path:
            self.corpus_path = Path(corpus_path)
        else:
            # Try to find corpus
            search_paths = [
                self.library_dir / "unified_corpus.json",
                self.library_dir.parent / "combined" / "unified_corpus.json",
                self.library_dir.parent / "unified_corpus.json",
                self.library_dir.parent.parent / "results" / "combined" / "unified_corpus.json",
            ]
            
            # Also search in common locations relative to script
            script_dir = Path(__file__).parent
            project_root = script_dir.parent.parent
            search_paths.extend([
                project_root / "results" / "combined" / "unified_corpus.json",
                project_root / "data" / "unified_corpus.json",
            ])
            
            self.corpus_path = None
            for candidate in search_paths:
                if candidate.exists():
                    self.corpus_path = candidate
                    break
            
            if self.corpus_path is None:
                searched = "\n  - ".join(str(p) for p in search_paths[:4])
                raise FileNotFoundError(
                    f"Could not find historical corpus. Searched:\n  - {searched}\n\n"
                    f"Please specify --corpus or ensure unified_corpus.json exists."
                )
        
        with open(self.corpus_path, 'r') as f:
            self.corpus_data = json.load(f)
        
        self.historical = self.corpus_data.get('movements', [])
        logger.info(f"Loaded {len(self.historical)} historical movements")
        
        # Extract data
        self._extract_data()
        
        # Compute embeddings
        self._compute_embeddings()
    
    def _extract_data(self):
        """Extract relevant fields from data."""
        # Synthetic severities and narratives
        self.synth_severities = []
        self.synth_narratives = []
        self.synth_causes = []
        self.synth_lobs = []
        
        for s in self.scenarios:
            sev = s.get('severity_ratio')
            if sev is not None:
                self.synth_severities.append(sev)
            
            narrative = s.get('narrative', '')
            if narrative:
                self.synth_narratives.append(narrative)
            
            cause = s.get('cause_category', 'Unknown')
            self.synth_causes.append(cause)
            
            # LOBs from breakdown
            lob_breakdown = s.get('lob_breakdown', {})
            for lob in lob_breakdown.keys():
                self.synth_lobs.append(lob)
        
        # Historical severities and narratives
        self.hist_severities = []
        self.hist_narratives = []
        self.hist_causes = []
        self.hist_lobs = []
        
        for h in self.historical:
            sev = h.get('severity_ratio')
            if sev is not None and h.get('direction') == 'strengthening':
                self.hist_severities.append(sev)
            
            narrative = h.get('narrative', '')
            if narrative:
                self.hist_narratives.append(narrative)
            
            causes = h.get('primary_causes', [])
            if causes:
                self.hist_causes.append(causes[0])  # Primary cause
            
            lob = h.get('line_of_business')
            if lob:
                self.hist_lobs.append(lob)
        
        self.synth_severities = np.array(self.synth_severities)
        self.hist_severities = np.array(self.hist_severities)
        
        logger.info(f"Extracted: {len(self.synth_severities)} synth severities, "
                   f"{len(self.hist_severities)} hist severities")
        logger.info(f"Extracted: {len(self.synth_narratives)} synth narratives, "
                   f"{len(self.hist_narratives)} hist narratives")
    
    def _compute_embeddings(self):
        """Compute TF-IDF embeddings for narratives."""
        logger.info("Computing TF-IDF embeddings...")
        
        # Combine all narratives for vectorizer fitting
        all_narratives = self.hist_narratives + self.synth_narratives
        
        if len(all_narratives) < 10:
            logger.warning("Insufficient narratives for embedding analysis")
            self.hist_embeddings = None
            self.synth_embeddings = None
            return

        # Check that both lists have content
        if len(self.hist_narratives) == 0:
            logger.warning("No historical narratives available for embedding analysis")
            self.hist_embeddings = None
            self.synth_embeddings = None
            return

        if len(self.synth_narratives) == 0:
            logger.warning("No synthetic narratives available for embedding analysis")
            self.hist_embeddings = None
            self.synth_embeddings = None
            return

        # TF-IDF vectorization
        self.vectorizer = TfidfVectorizer(
            max_features=500,
            ngram_range=(1, 2),
            stop_words='english',
            min_df=2,
            max_df=0.95
        )

        try:
            self.vectorizer.fit(all_narratives)

            self.hist_embeddings = self.vectorizer.transform(self.hist_narratives).toarray()
            self.synth_embeddings = self.vectorizer.transform(self.synth_narratives).toarray()

            logger.info(f"Embeddings: historical={self.hist_embeddings.shape}, "
                       f"synthetic={self.synth_embeddings.shape}")
        except Exception as e:
            logger.error(f"Embedding computation failed: {e}")
            self.hist_embeddings = None
            self.synth_embeddings = None
    
    def run_severity_diagnostics(self) -> SeverityDiagnostics:
        """Run severity distribution diagnostics."""
        logger.info("Running severity diagnostics...")
        
        hist = self.hist_severities
        synth = self.synth_severities
        
        if len(hist) == 0 or len(synth) == 0:
            logger.warning("Insufficient severity data")
            return None
        
        # Basic stats
        percentiles = [10, 25, 50, 75, 90, 95, 99]
        hist_pctl = {str(p): float(np.percentile(hist, p)) for p in percentiles}
        synth_pctl = {str(p): float(np.percentile(synth, p)) for p in percentiles}
        
        # KS test
        ks_stat, ks_pval = stats.ks_2samp(hist, synth)
        
        # MMD with bootstrap p-value
        hist_2d = hist.reshape(-1, 1)
        synth_2d = synth.reshape(-1, 1)
        
        mmd_stat = compute_mmd(hist_2d, synth_2d, gamma=1.0)
        mmd_pval, _ = bootstrap_mmd_pvalue(
            hist_2d, synth_2d, mmd_stat, 
            n_bootstrap=self.n_bootstrap
        )
        
        # JS divergence
        js_div = compute_js_divergence(hist, synth)
        
        # Pass/fail
        ks_pass = ks_pval >= self.THRESHOLDS['ks_pvalue']
        mmd_pass = mmd_stat <= self.THRESHOLDS['mmd_severity'] or mmd_pval >= 0.05
        js_pass = js_div <= self.THRESHOLDS['js_severity']
        
        return SeverityDiagnostics(
            historical_n=len(hist),
            synthetic_n=len(synth),
            historical_mean=float(hist.mean()),
            synthetic_mean=float(synth.mean()),
            historical_std=float(hist.std()),
            synthetic_std=float(synth.std()),
            historical_median=float(np.median(hist)),
            synthetic_median=float(np.median(synth)),
            historical_min=float(hist.min()),
            historical_max=float(hist.max()),
            synthetic_min=float(synth.min()),
            synthetic_max=float(synth.max()),
            historical_percentiles=hist_pctl,
            synthetic_percentiles=synth_pctl,
            ks_statistic=float(ks_stat),
            ks_pvalue=float(ks_pval),
            mmd_statistic=float(mmd_stat),
            mmd_pvalue=float(mmd_pval),
            js_divergence=float(js_div),
            ks_pass=ks_pass,
            mmd_pass=mmd_pass,
            js_pass=js_pass,
            overall_pass=ks_pass and mmd_pass and js_pass
        )
    
    def run_semantic_diagnostics(self) -> SemanticDiagnostics:
        """Run semantic coverage diagnostics."""
        logger.info("Running semantic diagnostics...")
        
        if self.hist_embeddings is None or self.synth_embeddings is None:
            logger.warning("No embeddings available for semantic diagnostics")
            return None
        
        X_real = self.hist_embeddings
        X_synth = self.synth_embeddings
        
        # Mean cosine similarity (synthetic to nearest real)
        cos_sim = cosine_similarity(X_synth, X_real)
        mean_cos_sim = cos_sim.max(axis=1).mean()
        
        # MMD with bootstrap
        mmd_stat = compute_mmd(X_real, X_synth, gamma=1.0)
        mmd_pval, _ = bootstrap_mmd_pvalue(
            X_real, X_synth, mmd_stat,
            n_bootstrap=self.n_bootstrap
        )
        
        # JS divergence (on PCA-reduced embeddings)
        try:
            pca = PCA(n_components=min(10, X_real.shape[1]))
            X_real_pca = pca.fit_transform(X_real)
            X_synth_pca = pca.transform(X_synth)
            
            # Compute JS on first PC
            js_div = compute_js_divergence(X_real_pca[:, 0], X_synth_pca[:, 0])
        except:
            js_div = None
        
        # Cluster metrics
        cluster_metrics = compute_cluster_metrics(X_real, X_synth)
        
        # Outlier rate
        outlier_rate = compute_outlier_rate(X_real, X_synth)
        
        # Diversity
        hist_diversity = compute_diversity(X_real)
        synth_diversity = compute_diversity(X_synth)
        diversity_ratio = synth_diversity / hist_diversity if hist_diversity > 0 else 1.0
        
        # Pass/fail
        cosine_pass = mean_cos_sim >= self.THRESHOLDS['cosine_similarity']
        mmd_pass = mmd_stat <= self.THRESHOLDS['mmd_semantic'] or mmd_pval >= 0.05
        cluster_pass = (cluster_metrics['coverage'] >= self.THRESHOLDS['cluster_coverage'] and
                       cluster_metrics['distribution_distance'] <= self.THRESHOLDS['cluster_distance'])
        outlier_pass = outlier_rate <= self.THRESHOLDS['outlier_rate']
        diversity_pass = (self.THRESHOLDS['diversity_ratio_low'] <= diversity_ratio <= 
                         self.THRESHOLDS['diversity_ratio_high'])
        
        return SemanticDiagnostics(
            mean_cosine_similarity=float(mean_cos_sim),
            mmd_statistic=float(mmd_stat),
            mmd_pvalue=float(mmd_pval),
            js_divergence=float(js_div) if js_div else None,
            n_clusters=cluster_metrics['n_clusters'],
            cluster_coverage=float(cluster_metrics['coverage']),
            cluster_distribution_distance=float(cluster_metrics['distribution_distance']),
            outlier_rate=float(outlier_rate),
            historical_diversity=float(hist_diversity),
            synthetic_diversity=float(synth_diversity),
            diversity_ratio=float(diversity_ratio),
            cosine_pass=cosine_pass,
            mmd_pass=mmd_pass,
            cluster_pass=cluster_pass,
            outlier_pass=outlier_pass,
            diversity_pass=diversity_pass,
            overall_pass=cosine_pass and mmd_pass and cluster_pass and outlier_pass and diversity_pass
        )
    
    def run_cause_diagnostics(self) -> CauseDistributionDiagnostics:
        """Run cause category distribution diagnostics."""
        logger.info("Running cause distribution diagnostics...")
        
        if not self.hist_causes or not self.synth_causes:
            return None
        
        # Count distributions
        hist_counts = Counter(self.hist_causes)
        synth_counts = Counter(self.synth_causes)
        
        all_categories = set(hist_counts.keys()) | set(synth_counts.keys())
        
        # Normalize to distributions
        hist_total = sum(hist_counts.values())
        synth_total = sum(synth_counts.values())
        
        hist_dist = {c: hist_counts.get(c, 0) / hist_total for c in all_categories}
        synth_dist = {c: synth_counts.get(c, 0) / synth_total for c in all_categories}
        
        # Chi-square test
        observed = [synth_counts.get(c, 0) for c in all_categories]
        expected_freq = [hist_dist.get(c, 0) for c in all_categories]
        expected = [f * synth_total for f in expected_freq]
        
        # Avoid zero expected values
        valid_idx = [i for i, e in enumerate(expected) if e > 0]
        if len(valid_idx) > 1:
            obs_valid = [observed[i] for i in valid_idx]
            exp_valid = [expected[i] for i in valid_idx]
            # Rescale expected to match observed sum (required for chi-square)
            obs_sum = sum(obs_valid)
            exp_sum = sum(exp_valid)
            if exp_sum > 0 and obs_sum > 0:
                exp_valid = [e * obs_sum / exp_sum for e in exp_valid]
            chi2, chi_pval = stats.chisquare(obs_valid, exp_valid)
        else:
            chi2, chi_pval = 0, 1.0
        
        # JS divergence
        p = np.array([hist_dist.get(c, 1e-10) for c in all_categories])
        q = np.array([synth_dist.get(c, 1e-10) for c in all_categories])
        p = p / p.sum()
        q = q / q.sum()
        m = 0.5 * (p + q)
        js_div = 0.5 * (stats.entropy(p, m) + stats.entropy(q, m))
        
        # Missing categories
        missing = [c for c in hist_counts if synth_counts.get(c, 0) == 0]
        
        # Over/under represented
        over_rep = []
        under_rep = []
        for c in all_categories:
            h = hist_dist.get(c, 0)
            s = synth_dist.get(c, 0)
            if h > 0:
                ratio = s / h
                if ratio > 1.5:
                    over_rep.append(c)
                elif ratio < 0.5:
                    under_rep.append(c)
        
        overall_pass = chi_pval >= self.THRESHOLDS['cause_chi_pvalue'] or js_div <= self.THRESHOLDS['cause_js']
        
        return CauseDistributionDiagnostics(
            historical_distribution=hist_dist,
            synthetic_distribution=synth_dist,
            chi_square_statistic=float(chi2),
            chi_square_pvalue=float(chi_pval),
            js_divergence=float(js_div),
            missing_categories=missing,
            over_represented=over_rep,
            under_represented=under_rep,
            overall_pass=overall_pass
        )
    
    def run_lob_diagnostics(self) -> LOBCoverageDiagnostics:
        """Run LOB coverage diagnostics."""
        logger.info("Running LOB coverage diagnostics...")
        
        hist_lobs_set = set(self.hist_lobs)
        synth_lobs_set = set(self.synth_lobs)
        
        missing = list(hist_lobs_set - synth_lobs_set)
        coverage = len(hist_lobs_set & synth_lobs_set) / len(hist_lobs_set) if hist_lobs_set else 1.0
        
        hist_freq = dict(Counter(self.hist_lobs))
        synth_freq = dict(Counter(self.synth_lobs))
        
        # Chi-square test (if enough data)
        all_lobs = list(hist_lobs_set | synth_lobs_set)
        if len(all_lobs) > 1:
            observed = [synth_freq.get(l, 0) for l in all_lobs]
            hist_total = sum(hist_freq.values())
            synth_total = sum(synth_freq.values())
            expected = [(hist_freq.get(l, 0) / hist_total) * synth_total for l in all_lobs]
            
            valid_idx = [i for i, e in enumerate(expected) if e > 0]
            if len(valid_idx) > 1:
                obs_valid = [observed[i] for i in valid_idx]
                exp_valid = [expected[i] for i in valid_idx]
                _, chi_pval = stats.chisquare(obs_valid, exp_valid)
            else:
                chi_pval = 1.0
        else:
            chi_pval = 1.0
        
        overall_pass = coverage >= self.THRESHOLDS['lob_coverage']
        
        return LOBCoverageDiagnostics(
            historical_lobs=list(hist_lobs_set),
            synthetic_lobs=list(synth_lobs_set),
            missing_lobs=missing,
            coverage_rate=coverage,
            lob_frequency_historical=hist_freq,
            lob_frequency_synthetic=synth_freq,
            chi_square_pvalue=chi_pval,
            overall_pass=overall_pass
        )
    
    def run_coherence_diagnostics(self) -> CoherenceDiagnostics:
        """Run text-numeric coherence diagnostics."""
        logger.info("Running coherence diagnostics...")
        
        # Keywords for severity matching
        high_severity_words = [
            'catastrophic', 'severe', 'major', 'significant', 'substantial',
            'critical', 'extreme', 'devastating', 'massive', 'extensive',
            'adverse', 'higher', 'increased', 'rising', 'elevated', 'unprecedented'
        ]
        
        low_severity_words = [
            'minor', 'small', 'slight', 'minimal', 'negligible', 'routine',
            'limited', 'modest', 'marginal', 'stable', 'manageable',
            'decreased', 'lower', 'reduced', 'declining', 'favorable'
        ]
        
        coherent = 0
        incoherent = 0
        incoherent_examples = []
        z_scores = []
        
        # Normalize severities
        if len(self.synth_severities) == 0:
            return None
        
        sev_min = self.synth_severities.min()
        sev_max = self.synth_severities.max()
        sev_range = sev_max - sev_min if sev_max > sev_min else 1
        
        for i, scenario in enumerate(self.scenarios):
            sev = scenario.get('severity_ratio')
            narrative = scenario.get('narrative', '').lower()
            
            if sev is None or not narrative:
                continue
            
            # Normalize severity
            norm_sev = (sev - sev_min) / sev_range
            
            # Count severity words
            high_count = sum(1 for w in high_severity_words if w in narrative)
            low_count = sum(1 for w in low_severity_words if w in narrative)
            net_severity = high_count - low_count
            
            # Coherence check
            is_coherent = True
            reason = ""
            
            if norm_sev >= 0.66:  # High severity
                if net_severity < -2:  # Strong low language
                    is_coherent = False
                    reason = f"High severity ({sev:.1%}) but low-severity language"
            elif norm_sev <= 0.33:  # Low severity
                if net_severity > 2:  # Strong high language
                    is_coherent = False
                    reason = f"Low severity ({sev:.1%}) but high-severity language"
            
            # Z-score (simplified)
            expected_net = (norm_sev - 0.5) * 6  # Scale to roughly -3 to +3
            z = abs(net_severity - expected_net) / 2.0
            z_scores.append(z)
            
            if is_coherent:
                coherent += 1
            else:
                incoherent += 1
                if len(incoherent_examples) < 5:
                    incoherent_examples.append({
                        'scenario_id': scenario.get('id', f'scenario_{i}'),
                        'severity': sev,
                        'narrative': narrative[:200] + '...' if len(narrative) > 200 else narrative,
                        'reason': reason,
                        'z_score': z
                    })
        
        total = coherent + incoherent
        coherence_rate = coherent / total if total > 0 else 1.0
        mean_z = np.mean(z_scores) if z_scores else 0
        
        overall_pass = coherence_rate >= self.THRESHOLDS['coherence_rate']
        
        return CoherenceDiagnostics(
            coherence_rate=coherence_rate,
            n_coherent=coherent,
            n_incoherent=incoherent,
            mean_z_score=mean_z,
            incoherent_examples=incoherent_examples,
            overall_pass=overall_pass
        )
    
    def run_all_diagnostics(self) -> LibraryDiagnosticsResult:
        """Run all diagnostics and compute overall scores."""
        logger.info("="*60)
        logger.info("RUNNING LIBRARY DIAGNOSTICS")
        logger.info("="*60)
        
        # Run each diagnostic
        severity = self.run_severity_diagnostics()
        semantic = self.run_semantic_diagnostics()
        cause = self.run_cause_diagnostics()
        lob = self.run_lob_diagnostics()
        coherence = self.run_coherence_diagnostics()
        
        # Compute scores (0-100)
        def compute_score(diagnostics, weights: Dict[str, float]) -> float:
            if diagnostics is None:
                return 50.0  # Neutral score if not available
            
            score = 0
            total_weight = 0
            
            for attr, weight in weights.items():
                val = getattr(diagnostics, attr, None)
                if val is not None:
                    if isinstance(val, bool):
                        score += 100 * weight if val else 0
                    else:
                        # Normalize numeric values
                        score += min(100, max(0, val * 100)) * weight
                    total_weight += weight
            
            return score / total_weight if total_weight > 0 else 50.0
        
        # Severity score
        if severity:
            severity_components = [
                severity.ks_pass,
                severity.mmd_pass,
                severity.js_pass
            ]
            severity_score = sum(c * 100/3 for c in severity_components)
        else:
            severity_score = 50.0
        
        # Semantic score
        if semantic:
            semantic_components = [
                semantic.cosine_pass,
                semantic.mmd_pass,
                semantic.cluster_pass,
                semantic.outlier_pass,
                semantic.diversity_pass
            ]
            semantic_score = sum(c * 100/5 for c in semantic_components)
        else:
            semantic_score = 50.0
        
        # Cause score
        cause_score = 100.0 if cause and cause.overall_pass else 50.0
        
        # LOB score
        lob_score = lob.coverage_rate * 100 if lob else 50.0
        
        # Coherence score
        coherence_score = coherence.coherence_rate * 100 if coherence else 50.0
        
        # Overall score (weighted average)
        weights = {
            'severity': 0.25,
            'semantic': 0.30,
            'cause': 0.15,
            'lob': 0.15,
            'coherence': 0.15
        }
        
        overall_score = (
            weights['severity'] * severity_score +
            weights['semantic'] * semantic_score +
            weights['cause'] * cause_score +
            weights['lob'] * lob_score +
            weights['coherence'] * coherence_score
        )
        
        # Grade
        if overall_score >= 90:
            grade = 'A'
        elif overall_score >= 80:
            grade = 'B'
        elif overall_score >= 70:
            grade = 'C'
        elif overall_score >= 60:
            grade = 'D'
        else:
            grade = 'F'
        
        # Generate recommendations
        recommendations = []
        
        if severity and not severity.overall_pass:
            if not severity.ks_pass:
                recommendations.append("Severity distribution differs from historical (KS test). "
                                      "Consider adjusting GPD parameters or regenerating.")
            if not severity.mmd_pass:
                recommendations.append(f"Severity MMD too high ({severity.mmd_statistic:.4f}). "
                                      "Synthetic severities may not match historical distribution.")
        
        if semantic and not semantic.overall_pass:
            if not semantic.cosine_pass:
                recommendations.append(f"Low semantic similarity ({semantic.mean_cosine_similarity:.2f}). "
                                      "Narratives may be too different from historical.")
            if not semantic.cluster_pass:
                recommendations.append(f"Poor cluster coverage ({semantic.cluster_coverage:.0%}). "
                                      "Some historical themes not represented.")
            if not semantic.outlier_pass:
                recommendations.append(f"High outlier rate ({semantic.outlier_rate:.0%}). "
                                      "Many synthetic scenarios are semantic outliers.")
        
        if cause and not cause.overall_pass:
            if cause.missing_categories:
                recommendations.append(f"Missing cause categories: {', '.join(cause.missing_categories)}")
        
        if lob and not lob.overall_pass:
            if lob.missing_lobs:
                recommendations.append(f"Missing LOBs: {', '.join(lob.missing_lobs)}")
        
        if coherence and not coherence.overall_pass:
            recommendations.append(f"Low coherence rate ({coherence.coherence_rate:.0%}). "
                                  "Text-severity mismatches detected.")
        
        if not recommendations:
            recommendations.append("Library quality looks good! No critical issues detected.")
        
        result = LibraryDiagnosticsResult(
            timestamp=datetime.now().isoformat(),
            library_path=str(self.library_path),
            severity=severity,
            semantic=semantic,
            cause_distribution=cause,
            lob_coverage=lob,
            coherence=coherence,
            severity_score=severity_score,
            semantic_score=semantic_score,
            cause_score=cause_score,
            lob_score=lob_score,
            coherence_score=coherence_score,
            overall_score=overall_score,
            overall_grade=grade,
            recommendations=recommendations
        )
        
        logger.info(f"\nOVERALL SCORE: {overall_score:.1f}/100 (Grade {grade})")
        
        return result
    
    def save_results(self, results: LibraryDiagnosticsResult, output_path: str):
        """Save diagnostics results to JSON."""
        def deep_convert(obj, seen=None):
            """Recursively convert objects to JSON-serializable types."""
            if seen is None:
                seen = set()

            # Check for circular reference using id
            obj_id = id(obj)
            if obj_id in seen:
                return "<circular reference>"

            if isinstance(obj, dict):
                seen.add(obj_id)
                return {k: deep_convert(v, seen) for k, v in obj.items()}
            elif isinstance(obj, (list, tuple)):
                seen.add(obj_id)
                return [deep_convert(item, seen) for item in obj]
            elif isinstance(obj, np.ndarray):
                return obj.tolist()
            elif isinstance(obj, (np.float32, np.float64, np.floating)):
                return float(obj)
            elif isinstance(obj, (np.int32, np.int64, np.integer)):
                return int(obj)
            elif isinstance(obj, (np.bool_,)):
                return bool(obj)
            elif hasattr(obj, '__dataclass_fields__'):
                seen.add(obj_id)
                return deep_convert(asdict(obj), seen)
            elif isinstance(obj, (str, int, float, bool, type(None))):
                return obj
            else:
                # Try to convert to string as fallback
                try:
                    return str(obj)
                except:
                    return f"<unserializable: {type(obj).__name__}>"

        # Convert results to dict first
        results_dict = asdict(results)
        # Deep convert to handle any remaining non-serializable types
        serializable = deep_convert(results_dict)

        with open(output_path, 'w') as f:
            json.dump(serializable, f, indent=2)

        logger.info(f"Saved diagnostics to {output_path}")


# =============================================================================
# CLI
# =============================================================================

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Run library diagnostics")
    parser.add_argument("--library", "-l", required=True, help="Path to scenario library")
    parser.add_argument("--corpus", "-c", help="Path to historical corpus")
    parser.add_argument("--output", "-o", help="Output JSON path")
    parser.add_argument("--bootstrap", "-b", type=int, default=500, 
                       help="Bootstrap iterations for MMD")
    
    args = parser.parse_args()
    
    logging.basicConfig(level=logging.INFO)
    
    diag = LibraryDiagnostics(
        library_path=args.library,
        corpus_path=args.corpus,
        n_bootstrap=args.bootstrap
    )
    
    results = diag.run_all_diagnostics()
    
    if args.output:
        diag.save_results(results, args.output)
    
    # Print summary
    print("\n" + "="*60)
    print("LIBRARY DIAGNOSTICS SUMMARY")
    print("="*60)
    print(f"\nOverall Score: {results.overall_score:.1f}/100 (Grade {results.overall_grade})")
    print(f"\nComponent Scores:")
    print(f"  Severity Distribution: {results.severity_score:.1f}/100")
    print(f"  Semantic Coverage:     {results.semantic_score:.1f}/100")
    print(f"  Cause Distribution:    {results.cause_score:.1f}/100")
    print(f"  LOB Coverage:          {results.lob_score:.1f}/100")
    print(f"  Coherence:             {results.coherence_score:.1f}/100")
    print(f"\nRecommendations:")
    for rec in results.recommendations:
        print(f"  • {rec}")
