"""
Step 2: Joint Semantic-Numeric Embedding Space

Creates a 3D latent space where:
- Dimension 1: Severity axis
- Dimension 2: Causality/semantic axis  
- Dimension 3: Portfolio structure axis

Uses orthogonally regularised MLP to ensure dimensions capture distinct information.
"""

import sys
from pathlib import Path
_script_dir = Path(__file__).resolve().parent
if str(_script_dir) not in sys.path:
    sys.path.insert(0, str(_script_dir))

import json
import logging
import numpy as np
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
import pickle

from config import (
    EmbeddingConfig, HistoricalMovement, LLOYDS_LOBS,
    DEFAULT_EMBEDDING_CONFIG
)

logger = logging.getLogger(__name__)


# =============================================================================
# Text Embedding (using sentence-transformers)
# =============================================================================

class TextEmbedder:
    """Generate text embeddings using sentence-transformers."""
    
    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self.model_name = model_name
        self.model = None
        # For fallback mode
        self._tfidf_vectorizer = None
        self._svd_model = None
        self._fitted = False
    
    def _load_model(self):
        """Lazy load the model."""
        if self.model is None:
            try:
                from sentence_transformers import SentenceTransformer
                self.model = SentenceTransformer(self.model_name)
                logger.info(f"Loaded sentence transformer: {self.model_name}")
            except ImportError:
                logger.warning("sentence-transformers not installed, using fallback")
                self.model = "fallback"
    
    def embed(self, texts: List[str]) -> np.ndarray:
        """Generate embeddings for a list of texts."""
        self._load_model()
        
        if self.model == "fallback":
            return self._tfidf_embed(texts)
        
        embeddings = self.model.encode(texts, show_progress_bar=len(texts) > 10)
        return np.array(embeddings)
    
    def _tfidf_embed(self, texts: List[str]) -> np.ndarray:
        """TF-IDF fallback embedding."""
        import warnings
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.decomposition import TruncatedSVD
        
        # Fit on first batch, then transform subsequent
        if not self._fitted or len(texts) > 10:
            # (Re)fit on this batch if it's large enough
            self._tfidf_vectorizer = TfidfVectorizer(max_features=1000, min_df=1, max_df=0.95)
            tfidf = self._tfidf_vectorizer.fit_transform(texts)
            
            n_components = min(384, tfidf.shape[1] - 1, tfidf.shape[0] - 1)
            n_components = max(n_components, 1)
            
            with warnings.catch_warnings():
                warnings.filterwarnings('ignore', category=RuntimeWarning)
                self._svd_model = TruncatedSVD(n_components=n_components, random_state=42)
                reduced = self._svd_model.fit_transform(tfidf)
            
            self._fitted = True
        else:
            # Transform using fitted models
            tfidf = self._tfidf_vectorizer.transform(texts)
            reduced = self._svd_model.transform(tfidf)
        
        # Pad to 384 if needed
        if reduced.shape[1] < 384:
            padding = np.zeros((reduced.shape[0], 384 - reduced.shape[1]))
            reduced = np.hstack([reduced, padding])
        
        return reduced
    
    def _tfidf_fallback(self, texts: List[str]) -> np.ndarray:
        """Deprecated: use _tfidf_embed instead."""
        return self._tfidf_embed(texts)


# =============================================================================
# Orthogonally Regularised Projection Network
# =============================================================================

class OrthogonalProjectionNetwork:
    """
    MLP that projects high-dimensional input to low-dimensional latent space
    with orthogonal regularisation to separate dimensions.
    
    Architecture:
        Input: [text_embedding(384) || severity_norm(1) || complexity_norm(1) || lob_vector(13)]
        -> Hidden layer (128 units, ReLU)
        -> Output layer (3 units, linear)
    
    Loss: L_contrastive + λ × L_orthogonality
    """
    
    def __init__(self, config: EmbeddingConfig = None):
        self.config = config or DEFAULT_EMBEDDING_CONFIG
        
        # Input dimension: 384 (text) + 1 (severity) + 1 (complexity) + 13 (LOB)
        self.input_dim = self.config.text_dim + 1 + 1 + len(LLOYDS_LOBS)
        self.hidden_dim = self.config.hidden_dim
        self.output_dim = self.config.latent_dim
        
        # Initialize weights
        rng = np.random.RandomState(42)
        self.W1 = rng.randn(self.input_dim, self.hidden_dim) * 0.1
        self.b1 = np.zeros(self.hidden_dim)
        self.W2 = rng.randn(self.hidden_dim, self.output_dim) * 0.1
        self.b2 = np.zeros(self.output_dim)
        
        # Normalisation parameters (set during fit)
        self.severity_mean = 0.0
        self.severity_std = 1.0
        self.complexity_mean = 0.0
        self.complexity_std = 1.0
    
    def _relu(self, x: np.ndarray) -> np.ndarray:
        return np.maximum(0, x)
    
    def _relu_grad(self, x: np.ndarray) -> np.ndarray:
        return (x > 0).astype(float)
    
    def forward(self, X: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """Forward pass, returns (hidden, output)."""
        hidden = self._relu(X @ self.W1 + self.b1)
        output = hidden @ self.W2 + self.b2
        return hidden, output
    
    def project(self, X: np.ndarray) -> np.ndarray:
        """Project input to latent space."""
        _, output = self.forward(X)
        return output
    
    def _orthogonality_loss(self) -> float:
        """Frobenius norm of W2^T W2 - I."""
        gram = self.W2.T @ self.W2
        identity = np.eye(self.output_dim)
        return np.sum((gram - identity) ** 2)
    
    def _contrastive_loss(self,
                          embeddings: np.ndarray,
                          labels: np.ndarray) -> Tuple[float, np.ndarray]:
        """
        Supervised contrastive loss (vectorized).
        Positive pairs: same severity bin — minimize distance.
        Negative pairs: different severity bins — hinge loss on distance.

        Returns:
            (loss_value, gradient w.r.t. embeddings)
        """
        from scipy.spatial.distance import pdist, squareform

        n = len(embeddings)
        # Pairwise squared distances (n, n)
        dists_sq = squareform(pdist(embeddings, 'sqeuclidean'))
        dists = np.sqrt(np.maximum(dists_sq, 1e-12))

        # Masks for positive and negative pairs (upper triangle only)
        same_label = labels[:, None] == labels[None, :]
        upper = np.triu(np.ones((n, n), dtype=bool), k=1)
        pos_mask = same_label & upper
        neg_mask = (~same_label) & upper

        # Loss: positive pairs = squared distance, negative pairs = hinge
        margin = self.config.contrastive_margin
        hinge_vals = np.maximum(0, margin - dists)

        loss = np.sum(dists_sq[pos_mask]) + np.sum(hinge_vals[neg_mask] ** 2)
        count = np.sum(upper)
        loss = loss / max(count, 1)

        # Gradient w.r.t. embeddings
        grad = np.zeros_like(embeddings)
        # Positive pair gradient: d/d(e_i) of ||e_i - e_j||^2 = 2(e_i - e_j)
        for i in range(n):
            pos_j = np.where(pos_mask[i])[0]
            if len(pos_j) > 0:
                grad[i] += 2 * np.sum(embeddings[i] - embeddings[pos_j], axis=0)

            # Negative pair gradient: d/d(e_i) of max(0, m - ||e_i-e_j||)^2
            neg_j = np.where(neg_mask[i])[0]
            if len(neg_j) > 0:
                diff = embeddings[i] - embeddings[neg_j]
                d = dists[i, neg_j]
                active = hinge_vals[i, neg_j] > 0
                if np.any(active):
                    coeff = -2 * hinge_vals[i, neg_j][active] / d[active]
                    grad[i] += np.sum(coeff[:, None] * diff[active], axis=0)

        grad /= max(count, 1)
        return loss, grad
    
    def fit(self, 
            movements: List[HistoricalMovement],
            text_embeddings: np.ndarray) -> 'OrthogonalProjectionNetwork':
        """
        Train the projection network.
        """
        logger.info("Training orthogonal projection network...")
        
        # Extract features
        severities = np.array([m.severity_ratio for m in movements])
        complexities = np.array([m.complexity_score for m in movements])
        lob_vectors = np.array([m.lob_vector for m in movements])
        
        # Normalise numeric features
        self.severity_mean = severities.mean()
        self.severity_std = severities.std() + 1e-8
        self.complexity_mean = complexities.mean()
        self.complexity_std = complexities.std() + 1e-8
        
        sev_norm = (severities - self.severity_mean) / self.severity_std
        comp_norm = (complexities - self.complexity_mean) / self.complexity_std
        
        # Construct input matrix
        X = np.hstack([
            text_embeddings,
            sev_norm.reshape(-1, 1),
            comp_norm.reshape(-1, 1),
            lob_vectors
        ])
        
        # Create severity bin labels for contrastive loss
        severity_bins = (severities * 10).astype(int)  # 10% bins
        
        # Training loop (simple gradient descent)
        lr = self.config.learning_rate
        lam = self.config.orthogonality_lambda
        
        for epoch in range(self.config.epochs):
            # Forward pass
            pre_relu = X @ self.W1 + self.b1
            hidden = self._relu(pre_relu)
            output = hidden @ self.W2 + self.b2

            # Compute losses
            contrastive, d_output = self._contrastive_loss(output, severity_bins)
            orthogonality = self._orthogonality_loss()
            total_loss = contrastive + lam * orthogonality

            # Backward pass: contrastive gradient through network
            # d_output is (n, output_dim) gradient w.r.t. output embeddings
            d_b2 = np.sum(d_output, axis=0)
            d_W2_contrastive = hidden.T @ d_output

            # Backprop through ReLU
            d_hidden = d_output @ self.W2.T
            d_pre_relu = d_hidden * self._relu_grad(pre_relu)
            d_W1 = X.T @ d_pre_relu
            d_b1 = np.sum(d_pre_relu, axis=0)

            # Orthogonality gradient w.r.t. W2
            gram = self.W2.T @ self.W2
            identity = np.eye(self.output_dim)
            ortho_grad = 4 * self.W2 @ (gram - identity)

            # Update all parameters
            self.W1 -= lr * d_W1
            self.b1 -= lr * d_b1
            self.W2 -= lr * (d_W2_contrastive + lam * ortho_grad)
            self.b2 -= lr * d_b2

            # Re-orthogonalize W2 periodically using SVD
            if epoch % 10 == 0:
                U, _, Vt = np.linalg.svd(self.W2, full_matrices=False)
                self.W2 = U @ Vt

            if epoch % 20 == 0:
                logger.info(f"Epoch {epoch}: loss={total_loss:.4f} "
                           f"(contrastive={contrastive:.4f}, ortho={orthogonality:.4f})")
        
        logger.info("Training complete")
        return self
    
    def prepare_input(self,
                      text_embedding: np.ndarray,
                      severity: float,
                      complexity: float,
                      lob_vector: List[float]) -> np.ndarray:
        """Prepare a single input vector."""
        sev_norm = (severity - self.severity_mean) / self.severity_std
        comp_norm = (complexity - self.complexity_mean) / self.complexity_std
        
        return np.hstack([
            text_embedding,
            [sev_norm],
            [comp_norm],
            lob_vector
        ])
    
    def save(self, path: str):
        """Save network parameters."""
        data = {
            'config': self.config,
            'W1': self.W1, 'b1': self.b1,
            'W2': self.W2, 'b2': self.b2,
            'severity_mean': self.severity_mean,
            'severity_std': self.severity_std,
            'complexity_mean': self.complexity_mean,
            'complexity_std': self.complexity_std
        }
        with open(path, 'wb') as f:
            pickle.dump(data, f)
        logger.info(f"Saved projection network to {path}")
    
    def load(self, path: str) -> 'OrthogonalProjectionNetwork':
        """Load network parameters."""
        with open(path, 'rb') as f:
            data = pickle.load(f)
        
        self.config = data['config']
        self.W1 = data['W1']
        self.b1 = data['b1']
        self.W2 = data['W2']
        self.b2 = data['b2']
        self.severity_mean = data['severity_mean']
        self.severity_std = data['severity_std']
        self.complexity_mean = data['complexity_mean']
        self.complexity_std = data['complexity_std']
        
        logger.info(f"Loaded projection network from {path}")
        return self


# =============================================================================
# Joint Embedding Space
# =============================================================================

class JointEmbeddingSpace:
    """
    Complete joint semantic-numeric embedding space.
    """
    
    def __init__(self, config: EmbeddingConfig = None):
        self.config = config or DEFAULT_EMBEDDING_CONFIG
        self.text_embedder = TextEmbedder(self.config.text_model)
        self.projection_net = OrthogonalProjectionNetwork(self.config)
        
        # Store embedded data
        self.movements: List[HistoricalMovement] = []
        self.text_embeddings: Optional[np.ndarray] = None
        self.latent_coords: Optional[np.ndarray] = None
    
    def fit(self, movements: List[HistoricalMovement]) -> 'JointEmbeddingSpace':
        """
        Fit the embedding space on historical movements.
        """
        logger.info(f"Fitting joint embedding space on {len(movements)} movements")
        self.movements = movements
        
        # Generate text embeddings
        logger.info("Generating text embeddings...")
        texts = [m.narrative or f"{m.line_of_business} {' '.join(m.primary_causes)}" 
                 for m in movements]
        self.text_embeddings = self.text_embedder.embed(texts)
        logger.info(f"Text embedding shape: {self.text_embeddings.shape}")
        
        # Train projection network
        self.projection_net.fit(movements, self.text_embeddings)
        
        # Project all movements to latent space
        logger.info("Projecting to latent space...")
        inputs = []
        for i, m in enumerate(movements):
            inp = self.projection_net.prepare_input(
                self.text_embeddings[i],
                m.severity_ratio,
                m.complexity_score,
                m.lob_vector
            )
            inputs.append(inp)
        
        inputs = np.array(inputs)
        self.latent_coords = self.projection_net.project(inputs)
        
        # Store latent coords in movements
        for i, m in enumerate(movements):
            m.text_embedding = self.text_embeddings[i].tolist()
            m.latent_coords = self.latent_coords[i].tolist()
        
        logger.info(f"Latent space shape: {self.latent_coords.shape}")
        
        return self
    
    def project(self, 
                text: str, 
                severity: float, 
                complexity: float,
                lob_vector: List[float]) -> np.ndarray:
        """Project a new point into the latent space."""
        text_emb = self.text_embedder.embed([text])[0]
        inp = self.projection_net.prepare_input(text_emb, severity, complexity, lob_vector)
        return self.projection_net.project(inp.reshape(1, -1))[0]
    
    def find_neighbours(self,
                        target_coords: np.ndarray,
                        k: int = 7,
                        severity_band: Tuple[float, float] = None,
                        complexity_band: Tuple[float, float] = None,
                        min_years: int = 3) -> List[Tuple[HistoricalMovement, float]]:
        """
        Find k nearest neighbours with diversity constraints.
        
        Args:
            target_coords: Target point in latent space
            k: Number of neighbours
            severity_band: Optional (min, max) severity filter
            complexity_band: Optional (min, max) complexity filter
            min_years: Minimum different years in result
        """
        # Filter candidates
        candidates = []
        for i, m in enumerate(self.movements):
            # Severity filter
            if severity_band:
                if not (severity_band[0] <= m.severity_ratio <= severity_band[1]):
                    continue
            
            # Complexity filter
            if complexity_band:
                if not (complexity_band[0] <= m.complexity_score <= complexity_band[1]):
                    continue
            
            dist = np.linalg.norm(self.latent_coords[i] - target_coords)
            candidates.append((m, dist, i))
        
        if not candidates:
            logger.warning("No candidates found within filters")
            return []
        
        # Sort by distance
        candidates.sort(key=lambda x: x[1])
        
        # Select with year diversity
        selected = []
        years_seen = set()
        
        for m, dist, _ in candidates:
            if len(selected) >= k:
                break
            
            # Check year diversity
            if len(years_seen) < min_years or m.year in years_seen or len(selected) < min_years:
                selected.append((m, dist))
                years_seen.add(m.year)
        
        # If not enough diversity, just take closest
        if len(selected) < k:
            for m, dist, _ in candidates:
                if (m, dist) not in selected:
                    selected.append((m, dist))
                if len(selected) >= k:
                    break
        
        return selected[:k]
    
    def get_latent_bounds(self) -> Dict[str, Tuple[float, float]]:
        """Get bounds of the latent space."""
        return {
            'dim1': (self.latent_coords[:, 0].min(), self.latent_coords[:, 0].max()),
            'dim2': (self.latent_coords[:, 1].min(), self.latent_coords[:, 1].max()),
            'dim3': (self.latent_coords[:, 2].min(), self.latent_coords[:, 2].max())
        }
    
    def save(self, output_dir: str):
        """Save the embedding space."""
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        
        # Save projection network
        self.projection_net.save(str(output_path / 'projection_network.pkl'))
        
        # Save text embeddings
        np.save(str(output_path / 'text_embeddings.npy'), self.text_embeddings)
        
        # Save latent coordinates
        np.save(str(output_path / 'latent_coords.npy'), self.latent_coords)
        
        # Save movement data (without embeddings to save space)
        movements_data = []
        for m in self.movements:
            d = vars(m).copy()
            d.pop('text_embedding', None)
            d.pop('latent_coords', None)
            movements_data.append(d)
        
        with open(output_path / 'movements.json', 'w') as f:
            json.dump(movements_data, f, indent=2, default=str)
        
        logger.info(f"Saved embedding space to {output_dir}")
    
    @classmethod
    def load(cls, input_dir: str) -> 'JointEmbeddingSpace':
        """Load a saved embedding space."""
        input_path = Path(input_dir)
        
        space = cls()
        space.projection_net.load(str(input_path / 'projection_network.pkl'))
        space.text_embeddings = np.load(str(input_path / 'text_embeddings.npy'))
        space.latent_coords = np.load(str(input_path / 'latent_coords.npy'))
        
        with open(input_path / 'movements.json', 'r') as f:
            movements_data = json.load(f)
        
        space.movements = [HistoricalMovement(**d) for d in movements_data]
        
        # Restore embeddings
        for i, m in enumerate(space.movements):
            m.text_embedding = space.text_embeddings[i].tolist()
            m.latent_coords = space.latent_coords[i].tolist()
        
        logger.info(f"Loaded embedding space from {input_dir}")
        return space


# =============================================================================
# CLI
# =============================================================================

if __name__ == "__main__":
    import argparse
    
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    
    parser = argparse.ArgumentParser(description="Build joint embedding space")
    parser.add_argument('--input', '-i', default='results/stress_test/prepared_data.json',
                        help='Path to prepared data')
    parser.add_argument('--output', '-o', default='results/stress_test/embedding_space',
                        help='Output directory')
    
    args = parser.parse_args()
    
    # Load prepared data
    with open(args.input, 'r') as f:
        data = json.load(f)
    
    movements = [HistoricalMovement(**d) for d in data['movements']]
    
    # Build embedding space
    space = JointEmbeddingSpace()
    space.fit(movements)
    space.save(args.output)
    
    # Print summary
    bounds = space.get_latent_bounds()
    print("\n=== Latent Space Bounds ===")
    for dim, (lo, hi) in bounds.items():
        print(f"  {dim}: [{lo:.3f}, {hi:.3f}]")
