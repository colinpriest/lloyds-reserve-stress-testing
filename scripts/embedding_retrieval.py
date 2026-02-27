#!/usr/bin/env python3
"""
Embedding and Retrieval System for Lloyd's Reserve Stress Testing
==================================================================

Creates embeddings for historical reserve movements and provides
retrieval functionality for stress test scenario generation.

Components:
1. EmbeddingGenerator - Creates embeddings using OpenAI API
2. VectorStore - Stores and retrieves embeddings with FAISS
3. StressTestRetriever - High-level retrieval interface

Usage:
    # Build index
    python scripts/embedding_retrieval.py build
    
    # Query similar scenarios
    python scripts/embedding_retrieval.py query "Property cat losses from hurricanes"
    
    # Interactive mode
    python scripts/embedding_retrieval.py interactive
"""

import os
import json
import logging
import argparse
import pickle
import numpy as np
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Any
from dataclasses import dataclass, asdict
from datetime import datetime
import time

# OpenAI for embeddings
from openai import OpenAI

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# =============================================================================
# Configuration
# =============================================================================

@dataclass
class EmbeddingConfig:
    """Configuration for embedding generation."""
    model: str = "text-embedding-3-small"  # OpenAI embedding model
    dimensions: int = 1536  # Output dimensions
    batch_size: int = 100  # Batch size for API calls
    max_retries: int = 3
    retry_delay: float = 1.0


# =============================================================================
# Embedding Generator
# =============================================================================

class EmbeddingGenerator:
    """Generate embeddings using OpenAI API."""
    
    def __init__(self, config: EmbeddingConfig = None):
        self.config = config or EmbeddingConfig()
        self.client = OpenAI()  # Uses OPENAI_API_KEY env var
        self.total_tokens = 0
        self.api_calls = 0
    
    def generate_single(self, text: str) -> List[float]:
        """Generate embedding for a single text."""
        for attempt in range(self.config.max_retries):
            try:
                response = self.client.embeddings.create(
                    model=self.config.model,
                    input=text
                )
                self.api_calls += 1
                self.total_tokens += response.usage.total_tokens
                return response.data[0].embedding
            except Exception as e:
                if attempt < self.config.max_retries - 1:
                    logger.warning(f"Embedding API error (attempt {attempt + 1}): {e}")
                    time.sleep(self.config.retry_delay * (attempt + 1))
                else:
                    raise
    
    def generate_batch(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for a batch of texts."""
        embeddings = []
        
        for i in range(0, len(texts), self.config.batch_size):
            batch = texts[i:i + self.config.batch_size]
            
            for attempt in range(self.config.max_retries):
                try:
                    response = self.client.embeddings.create(
                        model=self.config.model,
                        input=batch
                    )
                    self.api_calls += 1
                    self.total_tokens += response.usage.total_tokens
                    
                    # Extract embeddings in order
                    batch_embeddings = [d.embedding for d in response.data]
                    embeddings.extend(batch_embeddings)
                    
                    logger.info(f"  Embedded batch {i//self.config.batch_size + 1}: {len(batch)} texts")
                    break
                    
                except Exception as e:
                    if attempt < self.config.max_retries - 1:
                        logger.warning(f"Batch embedding error (attempt {attempt + 1}): {e}")
                        time.sleep(self.config.retry_delay * (attempt + 1))
                    else:
                        raise
            
            # Rate limiting
            time.sleep(0.1)
        
        return embeddings


# =============================================================================
# Vector Store (FAISS-based)
# =============================================================================

class VectorStore:
    """
    Simple vector store using FAISS for similarity search.
    Falls back to numpy if FAISS not available.
    """
    
    def __init__(self, dimensions: int = 1536):
        self.dimensions = dimensions
        self.embeddings = None  # numpy array
        self.metadata = []  # List of metadata dicts
        self.use_faiss = False
        self.index = None
        
        # Try to import FAISS
        try:
            import faiss
            self.faiss = faiss
            self.use_faiss = True
            logger.info("Using FAISS for vector search")
        except ImportError:
            logger.info("FAISS not available, using numpy for vector search")
    
    def add(self, embeddings: List[List[float]], metadata: List[Dict]):
        """Add embeddings with metadata to the store."""
        new_embeddings = np.array(embeddings, dtype=np.float32)
        
        if self.embeddings is None:
            self.embeddings = new_embeddings
            self.metadata = metadata
        else:
            self.embeddings = np.vstack([self.embeddings, new_embeddings])
            self.metadata.extend(metadata)
        
        # Rebuild FAISS index if using it
        if self.use_faiss:
            self._build_faiss_index()
    
    def _build_faiss_index(self):
        """Build FAISS index for fast similarity search."""
        if self.embeddings is None or len(self.embeddings) == 0:
            return
        
        # Normalize embeddings for cosine similarity
        normalized = self.embeddings / np.linalg.norm(self.embeddings, axis=1, keepdims=True)
        
        # Create index
        self.index = self.faiss.IndexFlatIP(self.dimensions)  # Inner product (cosine after normalization)
        self.index.add(normalized)
    
    def search(self, query_embedding: List[float], k: int = 10) -> List[Tuple[Dict, float]]:
        """
        Search for k most similar embeddings.
        Returns list of (metadata, similarity_score) tuples.
        """
        if self.embeddings is None or len(self.embeddings) == 0:
            return []
        
        query = np.array([query_embedding], dtype=np.float32)
        query = query / np.linalg.norm(query)  # Normalize
        
        if self.use_faiss and self.index is not None:
            # FAISS search
            scores, indices = self.index.search(query, min(k, len(self.metadata)))
            results = [(self.metadata[idx], float(score)) for idx, score in zip(indices[0], scores[0]) if idx >= 0]
        else:
            # Numpy fallback - cosine similarity
            normalized = self.embeddings / np.linalg.norm(self.embeddings, axis=1, keepdims=True)
            similarities = np.dot(normalized, query.T).flatten()
            top_indices = np.argsort(similarities)[::-1][:k]
            results = [(self.metadata[idx], float(similarities[idx])) for idx in top_indices]
        
        return results
    
    def save(self, path: str):
        """Save vector store to disk."""
        data = {
            'embeddings': self.embeddings,
            'metadata': self.metadata,
            'dimensions': self.dimensions
        }
        with open(path, 'wb') as f:
            pickle.dump(data, f)
        logger.info(f"Saved vector store to {path} ({len(self.metadata)} vectors)")
    
    def load(self, path: str):
        """Load vector store from disk."""
        with open(path, 'rb') as f:
            data = pickle.load(f)
        
        self.embeddings = data['embeddings']
        self.metadata = data['metadata']
        self.dimensions = data['dimensions']
        
        if self.use_faiss:
            self._build_faiss_index()
        
        logger.info(f"Loaded vector store from {path} ({len(self.metadata)} vectors)")


# =============================================================================
# Stress Test Retriever
# =============================================================================

class StressTestRetriever:
    """
    High-level retrieval interface for stress test scenarios.
    """
    
    def __init__(self, vector_store: VectorStore, embedding_generator: EmbeddingGenerator):
        self.store = vector_store
        self.embedder = embedding_generator
    
    def retrieve(self, 
                 query: str, 
                 k: int = 10,
                 filters: Dict = None) -> List[Dict]:
        """
        Retrieve similar historical scenarios.
        
        Args:
            query: Natural language query (e.g., "Hurricane losses in property reinsurance")
            k: Number of results to return
            filters: Optional filters (e.g., {"direction": "strengthening", "lob": "Property"})
        
        Returns:
            List of matching movements with similarity scores
        """
        # Generate query embedding
        query_embedding = self.embedder.generate_single(query)
        
        # Search (get more than k to allow for filtering)
        search_k = k * 3 if filters else k
        results = self.store.search(query_embedding, k=search_k)
        
        # Apply filters
        if filters:
            filtered = []
            for metadata, score in results:
                match = True
                for key, value in filters.items():
                    if isinstance(value, list):
                        if metadata.get(key) not in value:
                            match = False
                            break
                    elif metadata.get(key) != value:
                        match = False
                        break
                if match:
                    filtered.append((metadata, score))
            results = filtered[:k]
        else:
            results = results[:k]
        
        # Format output
        output = []
        for metadata, score in results:
            result = dict(metadata)
            result['similarity_score'] = round(score, 4)
            output.append(result)
        
        return output
    
    def retrieve_by_lob(self, lob: str, direction: str = None, k: int = 10) -> List[Dict]:
        """Retrieve scenarios for a specific line of business."""
        query = f"Reserve {direction or 'movement'} for {lob} insurance"
        filters = {"line_of_business": lob}
        if direction:
            filters["direction"] = direction
        return self.retrieve(query, k=k, filters=filters)
    
    def retrieve_by_event_type(self, event_type: str, k: int = 10) -> List[Dict]:
        """Retrieve scenarios by event type (e.g., 'hurricane', 'pandemic', 'inflation')."""
        query = f"Reserve strengthening due to {event_type}"
        return self.retrieve(query, k=k, filters={"direction": "strengthening"})
    
    def retrieve_for_stress_test(self,
                                  lob: str,
                                  severity: str = "severe",
                                  k: int = 5) -> List[Dict]:
        """
        Retrieve scenarios suitable for stress test generation.
        
        Args:
            lob: Line of business
            severity: "moderate", "severe", or "extreme"
            k: Number of scenarios to return
        """
        severity_queries = {
            "moderate": f"Minor reserve strengthening for {lob}",
            "severe": f"Significant reserve deterioration for {lob} due to catastrophe or adverse development",
            "extreme": f"Major reserve strengthening for {lob} from multiple catastrophes or systemic events"
        }
        
        query = severity_queries.get(severity, severity_queries["severe"])
        return self.retrieve(query, k=k, filters={"direction": "strengthening", "line_of_business": lob})


# =============================================================================
# Index Builder
# =============================================================================

def build_index(corpus_path: str, output_dir: str):
    """
    Build embedding index from unified corpus.
    
    Args:
        corpus_path: Path to unified_corpus.json
        output_dir: Directory to save index files
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    # Load corpus
    logger.info(f"Loading corpus from {corpus_path}")
    with open(corpus_path, 'r', encoding='utf-8') as f:
        corpus = json.load(f)
    
    movements = corpus['movements']
    logger.info(f"Loaded {len(movements)} movements")
    
    # Prepare texts for embedding
    texts = []
    metadata = []
    
    for m in movements:
        # Use pre-generated embedding text, or construct one
        text = m.get('embedding_text', '')
        if not text:
            # Construct embedding text
            parts = [f"{m.get('year', '')} {m.get('line_of_business', '')}"]
            if m.get('direction'):
                parts.append(f"reserve {m['direction']}")
            if m.get('primary_causes'):
                parts.append(f"due to {', '.join(m['primary_causes'][:3])}")
            if m.get('specific_events'):
                parts.append(f"including {', '.join(m['specific_events'][:5])}")
            if m.get('standardized_narrative'):
                parts.append(m['standardized_narrative'])
            text = ' '.join(parts)
        
        texts.append(text)
        
        # Store metadata (without large fields)
        meta = {
            'id': m.get('id', ''),
            'source_type': m.get('source_type', ''),
            'year': m.get('year'),
            'line_of_business': m.get('line_of_business', ''),
            'direction': m.get('direction', ''),
            'percentage': m.get('percentage'),
            'amount_gbp_m': m.get('amount_gbp_m'),
            'amount_usd_m': m.get('amount_usd_m'),
            'primary_causes': m.get('primary_causes', []),
            'specific_events': m.get('specific_events', []),
            'standardized_narrative': m.get('standardized_narrative', ''),
            'syndicate': m.get('syndicate'),
            'confidence': m.get('confidence', ''),
            'embedding_text': text
        }
        metadata.append(meta)
    
    # Generate embeddings
    logger.info("Generating embeddings...")
    embedder = EmbeddingGenerator()
    embeddings = embedder.generate_batch(texts)
    
    logger.info(f"Generated {len(embeddings)} embeddings")
    logger.info(f"  API calls: {embedder.api_calls}")
    logger.info(f"  Total tokens: {embedder.total_tokens}")
    
    # Build vector store
    logger.info("Building vector store...")
    store = VectorStore(dimensions=len(embeddings[0]))
    store.add(embeddings, metadata)
    
    # Save
    store_path = output_path / 'vector_store.pkl'
    store.save(str(store_path))
    
    # Save config
    config = {
        'created_at': datetime.now().isoformat(),
        'corpus_path': corpus_path,
        'total_movements': len(movements),
        'embedding_model': embedder.config.model,
        'dimensions': len(embeddings[0]),
        'api_calls': embedder.api_calls,
        'total_tokens': embedder.total_tokens
    }
    
    config_path = output_path / 'index_config.json'
    with open(config_path, 'w') as f:
        json.dump(config, f, indent=2)
    
    logger.info(f"Index built successfully!")
    logger.info(f"  Vector store: {store_path}")
    logger.info(f"  Config: {config_path}")
    
    return store


def load_retriever(index_dir: str) -> StressTestRetriever:
    """Load retriever from saved index."""
    index_path = Path(index_dir)
    
    store = VectorStore()
    store.load(str(index_path / 'vector_store.pkl'))
    
    embedder = EmbeddingGenerator()
    
    return StressTestRetriever(store, embedder)


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Embedding and retrieval system for stress test scenarios"
    )
    subparsers = parser.add_subparsers(dest='command', help='Command to run')
    
    # Build command
    build_parser = subparsers.add_parser('build', help='Build embedding index')
    build_parser.add_argument(
        '--corpus', '-c',
        default='results/combined/unified_corpus.json',
        help='Path to unified corpus JSON'
    )
    build_parser.add_argument(
        '--output', '-o',
        default='results/index',
        help='Output directory for index files'
    )
    
    # Query command
    query_parser = subparsers.add_parser('query', help='Query similar scenarios')
    query_parser.add_argument('query_text', help='Query text')
    query_parser.add_argument(
        '--index', '-i',
        default='results/index',
        help='Index directory'
    )
    query_parser.add_argument(
        '--k', '-k',
        type=int, default=5,
        help='Number of results'
    )
    query_parser.add_argument(
        '--direction', '-d',
        choices=['strengthening', 'release', 'mixed'],
        help='Filter by direction'
    )
    query_parser.add_argument(
        '--lob', '-l',
        help='Filter by line of business'
    )
    
    # Interactive command
    interactive_parser = subparsers.add_parser('interactive', help='Interactive query mode')
    interactive_parser.add_argument(
        '--index', '-i',
        default='results/index',
        help='Index directory'
    )
    
    args = parser.parse_args()
    
    if args.command == 'build':
        build_index(args.corpus, args.output)
    
    elif args.command == 'query':
        retriever = load_retriever(args.index)
        
        filters = {}
        if args.direction:
            filters['direction'] = args.direction
        if args.lob:
            filters['line_of_business'] = args.lob
        
        results = retriever.retrieve(args.query_text, k=args.k, filters=filters if filters else None)
        
        print(f"\n{'='*60}")
        print(f"Query: {args.query_text}")
        print(f"Results: {len(results)}")
        print(f"{'='*60}\n")
        
        for i, r in enumerate(results, 1):
            print(f"[{i}] Score: {r['similarity_score']}")
            print(f"    Year: {r['year']} | LOB: {r['line_of_business']} | Direction: {r['direction']}")
            if r.get('syndicate'):
                print(f"    Syndicate: {r['syndicate']}")
            if r.get('amount_gbp_m') or r.get('amount_usd_m'):
                amt = f"£{r['amount_gbp_m']}m" if r.get('amount_gbp_m') else f"${r['amount_usd_m']}m"
                print(f"    Amount: {amt}")
            print(f"    Causes: {', '.join(r.get('primary_causes', []))}")
            if r.get('specific_events'):
                print(f"    Events: {', '.join(r['specific_events'][:5])}")
            print(f"    Narrative: {r.get('standardized_narrative', '')[:200]}...")
            print()
    
    elif args.command == 'interactive':
        retriever = load_retriever(args.index)
        
        print("\n" + "="*60)
        print("Stress Test Scenario Retriever - Interactive Mode")
        print("="*60)
        print("\nCommands:")
        print("  <query>              - Free text search")
        print("  /lob <name>          - Search by line of business")
        print("  /event <type>        - Search by event type")
        print("  /stress <lob>        - Get stress test scenarios for LOB")
        print("  /quit                - Exit")
        print()
        
        while True:
            try:
                query = input("Query> ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            
            if not query:
                continue
            
            if query == '/quit':
                break
            
            elif query.startswith('/lob '):
                lob = query[5:].strip()
                results = retriever.retrieve_by_lob(lob, direction='strengthening', k=5)
            
            elif query.startswith('/event '):
                event = query[7:].strip()
                results = retriever.retrieve_by_event_type(event, k=5)
            
            elif query.startswith('/stress '):
                lob = query[8:].strip()
                results = retriever.retrieve_for_stress_test(lob, severity='severe', k=5)
            
            else:
                results = retriever.retrieve(query, k=5)
            
            print(f"\nFound {len(results)} results:\n")
            for i, r in enumerate(results, 1):
                print(f"[{i}] {r['year']} {r['line_of_business']} ({r['direction']}) - Score: {r['similarity_score']}")
                if r.get('specific_events'):
                    print(f"    Events: {', '.join(r['specific_events'][:3])}")
                print(f"    {r.get('standardized_narrative', '')[:150]}...")
                print()
    
    else:
        parser.print_help()


if __name__ == "__main__":
    main()