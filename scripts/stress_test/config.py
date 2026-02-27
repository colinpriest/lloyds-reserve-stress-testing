"""
Configuration and constants for stress test generation system.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional
from enum import Enum


# =============================================================================
# Lloyd's Lines of Business
# =============================================================================

LLOYDS_LOBS = [
    "Property",
    "Casualty", 
    "Marine",
    "Energy",
    "Motor",
    "Aviation",
    "Reinsurance - Property",
    "Reinsurance - Casualty",
    "Reinsurance - Specialty",
    "Professional Lines",
    "Accident & Health",
    "Cyber",
    "Aggregate"  # For movements that span multiple LOBs
]

LOB_TO_INDEX = {lob: i for i, lob in enumerate(LLOYDS_LOBS)}
INDEX_TO_LOB = {i: lob for i, lob in enumerate(LLOYDS_LOBS)}


# =============================================================================
# Cause Categories
# =============================================================================

class CauseCategory(Enum):
    NATURAL_CAT = "Natural catastrophe events"
    MAN_MADE = "Man-made catastrophe / large losses"
    SOCIAL_INFLATION = "Social inflation / litigation trends"
    ECONOMIC_INFLATION = "Economic inflation / claims cost inflation"
    REGULATORY = "Regulatory changes"
    COVID = "COVID-19 / pandemic effects"
    OGDEN = "Ogden discount rate"
    ADVERSE_DEV = "Adverse claims development"
    LARGE_LOSS = "Large loss development"
    REINSURANCE = "Reinsurance recoveries"
    COURT_RULINGS = "Court rulings / legal developments"
    IBNR = "IBNR recalibration"
    METHODOLOGY = "Reserve methodology change"
    GEOPOLITICAL = "Geopolitical events"
    OTHER = "Other"


CAUSE_KEYWORDS = {
    CauseCategory.NATURAL_CAT: [
        'hurricane', 'typhoon', 'cyclone', 'earthquake', 'flood', 'wildfire',
        'storm', 'tornado', 'hail', 'catastrophe', 'nat cat', 'derecho'
    ],
    CauseCategory.MAN_MADE: [
        'explosion', 'fire', 'collision', 'grounding', 'terrorism', 'riot'
    ],
    CauseCategory.SOCIAL_INFLATION: [
        'social inflation', 'litigation', 'jury', 'verdict', 'settlement',
        'nuclear verdict', 'plaintiff', 'attorney'
    ],
    CauseCategory.ECONOMIC_INFLATION: [
        'inflation', 'cost increase', 'supply chain', 'material cost',
        'labor cost', 'wage'
    ],
    CauseCategory.COVID: [
        'covid', 'pandemic', 'coronavirus', 'event cancellation', 'bi claims'
    ],
    CauseCategory.OGDEN: [
        'ogden', 'discount rate', 'periodic payment'
    ],
    CauseCategory.GEOPOLITICAL: [
        'ukraine', 'russia', 'war', 'sanction', 'political risk'
    ]
}


# =============================================================================
# Configuration Classes
# =============================================================================

@dataclass
class EmbeddingConfig:
    """Configuration for embedding generation."""
    text_model: str = "all-MiniLM-L6-v2"  # Sentence transformer
    text_dim: int = 384
    latent_dim: int = 3  # Severity, Causality, Portfolio structure
    hidden_dim: int = 128
    orthogonality_lambda: float = 0.1
    contrastive_margin: float = 0.5
    learning_rate: float = 0.001
    epochs: int = 100
    batch_size: int = 32


@dataclass 
class EVTConfig:
    """Configuration for extreme value theory analysis."""
    # Threshold selection
    threshold_candidates: int = 20  # Number of thresholds to evaluate
    min_exceedances: int = 30  # Minimum observations above threshold
    
    # GPD constraints
    max_shape: float = 0.5  # ξ < 0.5 for finite variance
    
    # Goodness of fit
    ad_significance: float = 0.05  # Anderson-Darling p-value threshold
    
    # Bootstrap
    n_bootstrap: int = 1000


@dataclass
class GenerationConfig:
    """Configuration for synthetic scenario generation."""
    # Severity bins (5% width)
    severity_bins: List[tuple] = field(default_factory=lambda: [
        (0.00, 0.05), (0.05, 0.10), (0.10, 0.15), (0.15, 0.20),
        (0.20, 0.25), (0.25, 0.30), (0.30, 0.35), (0.35, 0.40),
        (0.40, 0.50), (0.50, 0.75), (0.75, 1.00), (1.00, 1.50)
    ])
    
    # Complexity bins
    complexity_bins: List[tuple] = field(default_factory=lambda: [
        (0, 50), (50, 150), (150, 300), (300, 500), (500, 1000)
    ])
    
    # Generation parameters
    scenarios_per_cell: int = 5
    overgeneration_factor: int = 5  # Generate 5× more, then filter
    k_neighbours: int = 7
    min_years_diversity: int = 3
    
    # LLM settings
    llm_model: str = "gpt-4o-mini"
    llm_temperature: float = 0.7
    max_tokens: int = 4000  # Increased to avoid truncation


@dataclass
class ValidationConfig:
    """Configuration for validation."""
    # Semantic coverage
    alpha_shape_alpha: float = 0.5
    mmd_permutations: int = 500  # Reduced from 1000 for speed
    mmd_significance: float = 0.05
    coverage_grid_size: int = 20
    
    # Coherence
    coherence_zscore_threshold: float = 2.5
    
    # Importance sampling
    target_library_size: int = 2000


@dataclass
class QueryConfig:
    """Configuration for portfolio queries."""
    severity_tolerance: float = 0.10  # ±10% severity band (increased from 3%)
    complexity_tolerance: float = 100  # ±100 complexity score (increased from 50)
    min_scenarios: int = 5
    max_scenarios: int = 10
    cause_diversity: bool = True


# =============================================================================
# Data Structures
# =============================================================================

@dataclass
class HistoricalMovement:
    """Structured historical reserve movement."""
    id: str
    source_type: str  # 'syndicate' or 'market'
    year: int
    syndicate: Optional[str]
    line_of_business: str
    direction: str  # 'strengthening' or 'release'
    severity_ratio: Optional[float]  # PYD / Opening reserves
    amount_gbp_m: Optional[float]
    amount_usd_m: Optional[float]
    primary_causes: List[str]
    specific_events: List[str]
    narrative: str
    
    # Computed fields
    lob_vector: Optional[List[float]] = None
    complexity_score: Optional[float] = None
    text_embedding: Optional[List[float]] = None
    latent_coords: Optional[List[float]] = None


@dataclass
class SyntheticScenario:
    """Generated synthetic stress scenario."""
    id: str
    severity_ratio: float
    complexity_score: float
    lob_breakdown: Dict[str, float]  # LOB -> severity contribution
    cause_category: str
    specific_events: List[str]
    narrative: str
    
    # Generation metadata
    source_neighbours: List[str]  # IDs of historical neighbours used
    generation_bin: tuple  # (severity_bin, complexity_bin)
    
    # Validation metadata
    text_embedding: Optional[List[float]] = None
    latent_coords: Optional[List[float]] = None
    coherence_score: Optional[float] = None
    is_edge_case: bool = False


@dataclass
class PortfolioSpec:
    """User portfolio specification for querying."""
    lob_weights: Dict[str, float]  # LOB -> weight (must sum to 1)
    total_reserves_gbp_m: float
    
    @property
    def hhi(self) -> float:
        """Herfindahl-Hirschman Index of LOB concentration."""
        return sum(w ** 2 for w in self.lob_weights.values())
    
    @property
    def complexity_score(self) -> float:
        """Portfolio complexity = R × (1 - HHI)."""
        return self.total_reserves_gbp_m * (1 - self.hhi)
    
    @property
    def lob_vector(self) -> List[float]:
        """13-dimensional LOB weight vector."""
        return [self.lob_weights.get(lob, 0.0) for lob in LLOYDS_LOBS]


@dataclass
class StressScenario:
    """Final stress test scenario for output."""
    id: str
    name: str
    return_period: int
    severity_ratio: float
    
    # Portfolio-adjusted impacts
    portfolio_impact: float  # Weighted severity for this portfolio
    lob_impacts: Dict[str, float]  # LOB -> severity (0 for unexposed LOBs)
    
    # Narrative and explanation
    narrative: str
    causal_chain: str = ""
    historical_analogues: List[Dict] = field(default_factory=list)
    explanation: str = ""  # v2: renamed from chain_of_thought
    
    # Audit trail
    confidence_level: float = 0.99
    source_scenarios: List[str] = field(default_factory=list)
    
    # Legacy fields (for v1 compatibility)
    chain_of_thought: str = ""
    source_scenario_id: str = ""
    fine_tuning_applied: Dict = field(default_factory=dict)


@dataclass
class FewShotExample:
    """A few-shot example used in generation prompt."""
    id: str
    syndicate: Optional[str]  # Syndicate name (e.g., "Beazley 2623")
    year: int  # Report year
    severity_ratio: Optional[float]
    line_of_business: str
    narrative: str
    primary_causes: List[str]
    distance_to_anchor: float  # Embedding space distance
    selection_reason: str  # 'similarity' or 'diversity' - why this example was chosen


@dataclass
class LLMAssessment:
    """LLM's assessment of a generated scenario's validity."""
    distributional_probability: float  # P(scenario from same local distribution as anchor)
    confidence: str  # 'high', 'medium', 'low'
    reasoning: str  # Explanation of how scenario relates to anchor/examples
    key_similarities: List[str]  # Aspects similar to anchor
    key_differences: List[str]  # Aspects that diverge from anchor
    extrapolation_type: str  # 'interpolation', 'mild_extrapolation', 'strong_extrapolation'
    risk_factors: List[str]  # Potential issues with this scenario


@dataclass
class ScenarioAuditRecord:
    """
    Complete audit trail for a single generated scenario.
    
    Captures everything needed to understand and reproduce the generation:
    - What anchor was used
    - What few-shot examples were provided
    - What the LLM generated
    - LLM's assessment of the scenario's validity
    """
    # Identifiers
    scenario_id: str
    anchor_id: str
    generation_timestamp: str
    call_index: int  # Which LLM call (0, 1, ...) for this anchor
    
    # Anchor details
    anchor_syndicate: Optional[str]  # Syndicate name (e.g., "Beazley 2623")
    anchor_year: int  # Report year
    anchor_severity: Optional[float]
    anchor_lob: str
    anchor_narrative: str
    anchor_causes: List[str]
    
    # Few-shot examples (neighbours) - labeled with selection reason
    few_shot_examples: List[FewShotExample]
    
    # Generation parameters
    prompt_severity_range: tuple  # (min, max) requested
    extrapolation_requested: bool
    random_seed: int
    
    # Generated output
    generated_scenario: Dict  # Raw LLM output (JSON)
    parsed_severity: float
    parsed_lob_breakdown: Dict[str, float]
    parsed_cause_category: str
    parsed_narrative: str
    
    # LLM assessment
    assessment: Optional[LLMAssessment] = None
    
    # Metadata
    model_used: str = "gpt-4o-mini"
    temperature: float = 0.8
    generation_time_ms: int = 0


# =============================================================================
# Default Configurations
# =============================================================================

DEFAULT_EMBEDDING_CONFIG = EmbeddingConfig()
DEFAULT_EVT_CONFIG = EVTConfig()
DEFAULT_GENERATION_CONFIG = GenerationConfig()
DEFAULT_VALIDATION_CONFIG = ValidationConfig()
DEFAULT_QUERY_CONFIG = QueryConfig()
