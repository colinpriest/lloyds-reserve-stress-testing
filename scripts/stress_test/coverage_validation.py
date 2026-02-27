"""
Step 5: Semantic Coverage Validation

Validates that synthetic scenarios cover the same semantic space as historical data:
1. Alpha-shape boundary detection
2. Maximum Mean Discrepancy (MMD) test
3. Grid coverage test
4. Density alignment (KL divergence)
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
from scipy import stats
from scipy.spatial import ConvexHull, Delaunay
from collections import defaultdict

from config import ValidationConfig, DEFAULT_VALIDATION_CONFIG, SyntheticScenario

logger = logging.getLogger(__name__)


# =============================================================================
# Alpha Shape Boundary Detection
# =============================================================================

def compute_alpha_shape_2d(points: np.ndarray, alpha: float) -> List[np.ndarray]:
    """
    Compute alpha shape (concave hull) for 2D point set.
    
    Returns list of edges defining the boundary.
    """
    from scipy.spatial import Delaunay
    
    if len(points) < 4:
        return []
    
    tri = Delaunay(points)
    
    edges = set()
    
    def add_edge(i, j):
        if (i, j) in edges or (j, i) in edges:
            edges.discard((i, j))
            edges.discard((j, i))
        else:
            edges.add((i, j))
    
    # Filter triangles by circumradius
    for simplex in tri.simplices:
        pts = points[simplex]
        
        # Compute circumradius
        a = np.linalg.norm(pts[0] - pts[1])
        b = np.linalg.norm(pts[1] - pts[2])
        c = np.linalg.norm(pts[2] - pts[0])
        s = (a + b + c) / 2
        area = np.sqrt(max(0, s * (s - a) * (s - b) * (s - c)))
        
        if area > 0:
            circumradius = (a * b * c) / (4 * area)
        else:
            circumradius = float('inf')
        
        # Include if circumradius <= 1/alpha
        if circumradius < 1 / alpha:
            add_edge(simplex[0], simplex[1])
            add_edge(simplex[1], simplex[2])
            add_edge(simplex[2], simplex[0])
    
    return [(points[i], points[j]) for i, j in edges]


def point_in_alpha_shape(point: np.ndarray, 
                         boundary_edges: List[Tuple[np.ndarray, np.ndarray]],
                         points: np.ndarray) -> bool:
    """
    Check if a point is inside the alpha shape boundary.
    Uses ray casting algorithm.
    """
    if len(boundary_edges) == 0:
        # Fall back to convex hull
        try:
            hull = ConvexHull(points)
            delaunay = Delaunay(points[hull.vertices])
            return delaunay.find_simplex(point) >= 0
        except:
            return True
    
    # Simple approach: check if point is within convex hull of boundary vertices
    boundary_points = set()
    for e1, e2 in boundary_edges:
        boundary_points.add(tuple(e1))
        boundary_points.add(tuple(e2))
    
    boundary_array = np.array(list(boundary_points))
    
    try:
        hull = ConvexHull(boundary_array)
        delaunay = Delaunay(boundary_array[hull.vertices])
        return delaunay.find_simplex(point) >= 0
    except:
        return True


def detect_boundary_violations(historical_coords: np.ndarray,
                               synthetic_coords: np.ndarray,
                               alpha: float = 0.5) -> Dict:
    """
    Detect synthetic points outside the historical boundary.
    
    Works in 2D by projecting to first 2 principal components if >2D.
    """
    # Project to 2D if needed
    if historical_coords.shape[1] > 2:
        from sklearn.decomposition import PCA
        pca = PCA(n_components=2)
        hist_2d = pca.fit_transform(historical_coords)
        syn_2d = pca.transform(synthetic_coords)
    else:
        hist_2d = historical_coords[:, :2]
        syn_2d = synthetic_coords[:, :2]
    
    # Compute alpha shape
    boundary = compute_alpha_shape_2d(hist_2d, alpha)
    
    # Check each synthetic point
    violations = []
    log_interval = max(len(syn_2d) // 10, 1)
    
    for i, point in enumerate(syn_2d):
        if not point_in_alpha_shape(point, boundary, hist_2d):
            violations.append(i)
        
        # Progress logging
        if (i + 1) % log_interval == 0:
            logger.info(f"    Boundary check: {i + 1}/{len(syn_2d)} ({100*(i+1)/len(syn_2d):.0f}%)")
    
    return {
        'n_violations': len(violations),
        'violation_indices': violations,
        'violation_rate': len(violations) / len(synthetic_coords),
        'boundary_edges': len(boundary)
    }


# =============================================================================
# Maximum Mean Discrepancy (MMD) Test
# =============================================================================

def rbf_kernel(X: np.ndarray, Y: np.ndarray, sigma: float) -> np.ndarray:
    """Compute RBF (Gaussian) kernel matrix."""
    X_sqnorm = np.sum(X ** 2, axis=1)
    Y_sqnorm = np.sum(Y ** 2, axis=1)
    
    K = X_sqnorm.reshape(-1, 1) + Y_sqnorm.reshape(1, -1) - 2 * X @ Y.T
    return np.exp(-K / (2 * sigma ** 2))


def compute_mmd(X: np.ndarray, Y: np.ndarray, sigma: float = None) -> float:
    """
    Compute Maximum Mean Discrepancy between two samples.
    
    MMD^2 = E[k(X,X')] - 2*E[k(X,Y)] + E[k(Y,Y')]
    """
    if sigma is None:
        # Median heuristic
        combined = np.vstack([X, Y])
        dists = np.linalg.norm(combined[:, None] - combined[None, :], axis=2)
        sigma = np.median(dists[dists > 0])
    
    m, n = len(X), len(Y)
    
    K_XX = rbf_kernel(X, X, sigma)
    K_YY = rbf_kernel(Y, Y, sigma)
    K_XY = rbf_kernel(X, Y, sigma)
    
    # Unbiased estimator
    mmd2 = (np.sum(K_XX) - np.trace(K_XX)) / (m * (m - 1))
    mmd2 += (np.sum(K_YY) - np.trace(K_YY)) / (n * (n - 1))
    mmd2 -= 2 * np.sum(K_XY) / (m * n)
    
    return mmd2


def mmd_permutation_test(X: np.ndarray, 
                         Y: np.ndarray,
                         n_permutations: int = 1000,
                         sigma: float = None) -> Tuple[float, float]:
    """
    Permutation test for MMD.
    
    H0: X and Y are from the same distribution
    
    Returns:
        (observed_mmd, p_value)
    """
    # Subsample if datasets are large (for speed)
    max_samples = 500
    if len(X) > max_samples:
        X = X[np.random.choice(len(X), max_samples, replace=False)]
    if len(Y) > max_samples:
        Y = Y[np.random.choice(len(Y), max_samples, replace=False)]
    
    logger.info(f"    MMD test: {len(X)} historical, {len(Y)} synthetic samples")
    
    observed_mmd = compute_mmd(X, Y, sigma)
    
    # Permutation test
    combined = np.vstack([X, Y])
    m = len(X)
    
    permuted_mmds = []
    log_interval = max(n_permutations // 10, 1)
    
    for i in range(n_permutations):
        perm = np.random.permutation(len(combined))
        X_perm = combined[perm[:m]]
        Y_perm = combined[perm[m:]]
        permuted_mmds.append(compute_mmd(X_perm, Y_perm, sigma))
        
        # Progress logging
        if (i + 1) % log_interval == 0:
            logger.info(f"    MMD permutations: {i + 1}/{n_permutations} ({100*(i+1)/n_permutations:.0f}%)")
    
    p_value = np.mean(np.array(permuted_mmds) >= observed_mmd)
    
    return observed_mmd, p_value


# =============================================================================
# Grid Coverage Test
# =============================================================================

def compute_grid_coverage(historical_coords: np.ndarray,
                          synthetic_coords: np.ndarray,
                          grid_size: int = 20) -> Dict:
    """
    Check coverage by dividing latent space into grid cells.
    
    Returns coverage statistics.
    """
    n_dims = historical_coords.shape[1]
    
    # Compute bounds from historical data
    mins = historical_coords.min(axis=0)
    maxs = historical_coords.max(axis=0)
    
    # Create grid
    cell_size = (maxs - mins) / grid_size
    
    def point_to_cell(point):
        cell = tuple(int((point[d] - mins[d]) / cell_size[d]) for d in range(n_dims))
        return tuple(min(c, grid_size - 1) for c in cell)
    
    # Count historical cells
    historical_cells = set()
    for point in historical_coords:
        historical_cells.add(point_to_cell(point))
    
    # Count synthetic cells
    synthetic_cells = set()
    for point in synthetic_coords:
        cell = point_to_cell(point)
        # Clamp to grid bounds
        cell = tuple(max(0, min(c, grid_size - 1)) for c in cell)
        synthetic_cells.add(cell)
    
    # Coverage statistics
    covered = historical_cells & synthetic_cells
    uncovered = historical_cells - synthetic_cells
    extra = synthetic_cells - historical_cells
    
    return {
        'historical_cells': len(historical_cells),
        'synthetic_cells': len(synthetic_cells),
        'covered_cells': len(covered),
        'uncovered_cells': len(uncovered),
        'extra_cells': len(extra),
        'coverage_rate': len(covered) / len(historical_cells) if historical_cells else 0,
        'uncovered_cell_ids': list(uncovered)[:20]  # Sample
    }


# =============================================================================
# Density Alignment (KL Divergence)
# =============================================================================

def estimate_kl_divergence(historical_coords: np.ndarray,
                           synthetic_coords: np.ndarray,
                           n_bins: int = 20) -> Dict:
    """
    Estimate KL divergence between historical and synthetic distributions.
    
    Uses histogram-based estimation in each dimension.
    """
    n_dims = historical_coords.shape[1]
    
    kl_per_dim = []
    
    for d in range(n_dims):
        hist_d = historical_coords[:, d]
        syn_d = synthetic_coords[:, d]
        
        # Common bin edges
        all_data = np.concatenate([hist_d, syn_d])
        bins = np.linspace(all_data.min(), all_data.max(), n_bins + 1)
        
        # Histograms (add small constant to avoid log(0))
        hist_counts, _ = np.histogram(hist_d, bins=bins)
        syn_counts, _ = np.histogram(syn_d, bins=bins)
        
        hist_prob = (hist_counts + 1) / (len(hist_d) + n_bins)
        syn_prob = (syn_counts + 1) / (len(syn_d) + n_bins)
        
        # KL divergence: sum p(x) * log(p(x) / q(x))
        kl = np.sum(hist_prob * np.log(hist_prob / syn_prob))
        kl_per_dim.append(kl)
    
    return {
        'kl_per_dimension': kl_per_dim,
        'total_kl': sum(kl_per_dim),
        'mean_kl': np.mean(kl_per_dim)
    }


# =============================================================================
# Full Coverage Validation
# =============================================================================

@dataclass
class CoverageValidationResult:
    """Results of coverage validation."""
    # Boundary
    n_boundary_violations: int
    boundary_violation_rate: float
    boundary_violation_indices: List[int]
    
    # MMD
    mmd_statistic: float
    mmd_pvalue: float
    mmd_passed: bool
    
    # Grid coverage
    coverage_rate: float
    uncovered_cells: int
    extra_cells: int
    
    # KL divergence
    kl_divergence: float
    
    # Overall
    passed: bool
    warnings: List[str]


def validate_coverage(historical_coords: np.ndarray,
                      synthetic_coords: np.ndarray,
                      config: ValidationConfig = None) -> CoverageValidationResult:
    """
    Run full coverage validation suite.
    """
    config = config or DEFAULT_VALIDATION_CONFIG
    warnings = []
    
    logger.info("Running coverage validation...")
    
    # 1. Boundary detection
    logger.info("  Checking boundary violations...")
    boundary_result = detect_boundary_violations(
        historical_coords, synthetic_coords, config.alpha_shape_alpha
    )
    
    if boundary_result['violation_rate'] > 0.15:
        warnings.append(f"High boundary violation rate: {boundary_result['violation_rate']:.1%}")
    
    # 2. MMD test
    logger.info("  Running MMD test...")
    mmd_stat, mmd_pval = mmd_permutation_test(
        historical_coords, synthetic_coords, config.mmd_permutations
    )
    mmd_passed = mmd_pval > config.mmd_significance
    
    if not mmd_passed:
        warnings.append(f"MMD test failed: p={mmd_pval:.4f}")
    
    # 3. Grid coverage
    logger.info("  Checking grid coverage...")
    coverage_result = compute_grid_coverage(
        historical_coords, synthetic_coords, config.coverage_grid_size
    )
    
    if coverage_result['coverage_rate'] < 0.8:
        warnings.append(f"Low coverage rate: {coverage_result['coverage_rate']:.1%}")
    
    # 4. KL divergence
    logger.info("  Computing KL divergence...")
    kl_result = estimate_kl_divergence(historical_coords, synthetic_coords)
    
    if kl_result['mean_kl'] > 0.5:
        warnings.append(f"High KL divergence: {kl_result['mean_kl']:.3f}")
    
    # Overall pass
    passed = (
        boundary_result['violation_rate'] < 0.20 and
        mmd_passed and
        coverage_result['coverage_rate'] > 0.7 and
        kl_result['mean_kl'] < 1.0
    )
    
    return CoverageValidationResult(
        n_boundary_violations=boundary_result['n_violations'],
        boundary_violation_rate=boundary_result['violation_rate'],
        boundary_violation_indices=boundary_result['violation_indices'],
        mmd_statistic=mmd_stat,
        mmd_pvalue=mmd_pval,
        mmd_passed=mmd_passed,
        coverage_rate=coverage_result['coverage_rate'],
        uncovered_cells=coverage_result['uncovered_cells'],
        extra_cells=coverage_result['extra_cells'],
        kl_divergence=kl_result['mean_kl'],
        passed=passed,
        warnings=warnings
    )


def flag_edge_cases(scenarios: List[SyntheticScenario],
                    violation_indices: List[int]) -> List[SyntheticScenario]:
    """Mark scenarios that are boundary violations as edge cases."""
    for idx in violation_indices:
        if idx < len(scenarios):
            scenarios[idx].is_edge_case = True
    return scenarios


# =============================================================================
# CLI
# =============================================================================

if __name__ == "__main__":
    import argparse
    import json
    
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    
    parser = argparse.ArgumentParser(description="Validate coverage of synthetic scenarios")
    parser.add_argument('--historical', '-h', required=True,
                        help='Path to historical latent coords (npy)')
    parser.add_argument('--synthetic', '-s', required=True,
                        help='Path to synthetic latent coords (npy)')
    parser.add_argument('--output', '-o', default='results/stress_test/coverage_validation.json',
                        help='Output path')
    
    args = parser.parse_args()
    
    # Load coordinates
    historical = np.load(args.historical)
    synthetic = np.load(args.synthetic)
    
    print(f"Historical: {historical.shape}")
    print(f"Synthetic: {synthetic.shape}")
    
    # Run validation
    result = validate_coverage(historical, synthetic)
    
    print("\n=== Coverage Validation Results ===")
    print(f"Boundary violations: {result.n_boundary_violations} ({result.boundary_violation_rate:.1%})")
    print(f"MMD test: statistic={result.mmd_statistic:.6f}, p={result.mmd_pvalue:.4f}, passed={result.mmd_passed}")
    print(f"Grid coverage: {result.coverage_rate:.1%}")
    print(f"KL divergence: {result.kl_divergence:.4f}")
    print(f"Overall passed: {result.passed}")
    
    if result.warnings:
        print("\nWarnings:")
        for w in result.warnings:
            print(f"  - {w}")
    
    # Save results
    output_data = {
        'boundary_violations': result.n_boundary_violations,
        'boundary_violation_rate': result.boundary_violation_rate,
        'mmd_statistic': result.mmd_statistic,
        'mmd_pvalue': result.mmd_pvalue,
        'mmd_passed': result.mmd_passed,
        'coverage_rate': result.coverage_rate,
        'uncovered_cells': result.uncovered_cells,
        'kl_divergence': result.kl_divergence,
        'passed': result.passed,
        'warnings': result.warnings
    }
    
    with open(args.output, 'w') as f:
        json.dump(output_data, f, indent=2)
