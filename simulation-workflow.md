You're right on all counts. Let me fix these properly:

**CORRECTED ARCHITECTURE**

```
┌─────────────────────────────────────────────────────────────────────────┐
│ STEP 1: HISTORICAL DATA PREPARATION                                     │
│                                                                         │
│ For each historical movement, compute:                                  │
│                                                                         │
│ a) Severity ratio: PYD / Opening Reserves                              │
│                                                                         │
│ b) Portfolio complexity score (single metric):                          │
│    - Total reserves (R)                                                │
│    - LOB concentration: HHI = Σ(w_i²) where w_i = LOB weight           │
│    - Complexity = R × (1 - HHI)                                        │
│                                                                         │
│    Examples:                                                            │
│    £500m monoline Property: HHI=1.0, Complexity = 500 × 0 = 0          │
│    £500m split 50/50:      HHI=0.5, Complexity = 500 × 0.5 = 250       │
│    £100m split 25% × 4:    HHI=0.25, Complexity = 100 × 0.75 = 75      │
│                                                                         │
│ c) Text embedding (all-MiniLM-L6-v2, 384d)                             │
│                                                                         │
│ d) LOB vector: 13-dim one-hot for affected LOBs                        │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ STEP 2: JOINT EMBEDDING SPACE                                           │
│                                                                         │
│ Input vector: [text_embedding ∥ severity_norm ∥ complexity_norm ∥ LOB] │
│              (384d            + 1d            + 1d              + 13d)  │
│                                                                         │
│ Orthogonally regularised MLP → 3D latent space:                        │
│   - Dim 1: Severity axis                                               │
│   - Dim 2: Causality/semantic axis                                     │
│   - Dim 3: Portfolio structure axis                                    │
│                                                                         │
│ Loss = L_contrastive + λ × L_orthogonality                             │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ STEP 3: GPD THRESHOLD SELECTION (Proper EVT)                            │
│                                                                         │
│ Three diagnostic methods, seek consensus:                               │
│                                                                         │
│ a) Mean Residual Life (MRL) plot:                                      │
│    - Plot E[X - u | X > u] vs u                                        │
│    - Valid threshold: where MRL becomes approximately linear           │
│                                                                         │
│ b) Parameter stability plot:                                           │
│    - Fit GPD at range of thresholds                                    │
│    - Valid threshold: where ξ and modified σ* = σ - ξu stabilise       │
│                                                                         │
│ c) Anderson-Darling goodness-of-fit:                                   │
│    - Test GPD fit at candidate thresholds                              │
│    - Valid threshold: where A-D p-value > 0.05                         │
│                                                                         │
│ Threshold u = consensus across methods (e.g., u = 8% severity)         │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ STEP 4: STRATIFIED SYNTHETIC GENERATION                                 │
│                                                                         │
│ Target: generate synthetic scenarios to fill severity × complexity grid │
│                                                                         │
│ Severity bins (5% width): [0-5%], [5-10%], [10-15%], ..., [45-50%+]    │
│ Complexity bins: [0-100], [100-300], [300-600], [600+]                 │
│                                                                         │
│ For each (severity_bin, complexity_bin) cell:                          │
│                                                                         │
│   1. Retrieve k=7 historical neighbours in latent space that:          │
│      - Fall within or near this cell                                   │
│      - INCLUDE DIVERSITY: at least 3 different years                   │
│      - INCLUDE DIVERSITY: range of complexity scores within bin        │
│                                                                         │
│   2. Few-shot prompt includes examples showing:                         │
│      - How complexity affects severity interpretation                  │
│      - "£50m monoline saw 25% adverse vs £400m diversified saw 12%     │
│        from same hurricane season - diversification reduced impact"    │
│                                                                         │
│   3. Generate 5× scenarios per cell                                    │
│                                                                         │
│   4. Each synthetic scenario outputs:                                  │
│      - Narrative                                                       │
│      - Severity %                                                      │
│      - Complexity score                                                │
│      - LOB breakdown                                                   │
│      - Cause category                                                  │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ STEP 5: SEMANTIC COVERAGE VALIDATION                                    │
│                                                                         │
│ Project all synthetic scenarios into latent space                       │
│                                                                         │
│ a) Boundary detection (alpha-shape):                                   │
│    - Compute alpha-shape of historical point cloud                     │
│    - Identify convex hull + density-based boundary                     │
│    - Flag synthetic points outside boundary as "edge cases"            │
│                                                                         │
│ b) Distributional test (MMD):                                          │
│    - Maximum Mean Discrepancy between historical and synthetic         │
│    - Permutation test for p-value                                      │
│    - Reject if p < 0.05 (distributions differ significantly)           │
│                                                                         │
│ c) Coverage test:                                                       │
│    - Divide latent space into grid cells                               │
│    - Check synthetic data covers all cells historical data covers      │
│    - Flag gaps where synthetic is absent but historical exists         │
│                                                                         │
│ d) Density alignment:                                                  │
│    - KDE on historical vs synthetic in latent space                    │
│    - Visual inspection + KL divergence                                 │
│                                                                         │
│ Action: regenerate for cells with poor coverage or edge cases          │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ STEP 6: IMPORTANCE-SAMPLED SEVERITY DISTRIBUTION                        │
│                                                                         │
│ Goal: final library matches GPD-implied severity distribution           │
│                                                                         │
│ For each 5% severity bin:                                               │
│                                                                         │
│   1. Compute target count from GPD:                                    │
│      - P(severity in bin) from fitted GPD                              │
│      - target_n = total_library_size × P(bin)                          │
│                                                                         │
│   2. Current count: synthetic + historical in bin                      │
│                                                                         │
│   3. Importance weight = target_n / current_n                          │
│                                                                         │
│   4. Sample with replacement using weights                             │
│      - Undersample over-represented bins                               │
│      - Oversample under-represented bins (with jittering)              │
│                                                                         │
│ Result: library severity distribution matches GPD tail                  │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ STEP 7: COHERENCE VALIDATION                                            │
│                                                                         │
│ a) Regression-based validator:                                         │
│    - Train GB regressor: TF-IDF(narrative) → severity                  │
│    - Flag scenarios where |actual - predicted| > 2.5 σ                 │
│                                                                         │
│ b) Keyword-severity matching:                                          │
│    - High severity must have "severe", "catastrophic", "unprecedented" │
│    - Low severity must not have these terms                            │
│                                                                         │
│ c) Complexity-LOB consistency:                                         │
│    - High complexity score → multiple LOBs affected                    │
│    - Low complexity score → concentrated in 1-2 LOBs                   │
│                                                                         │
│ Output: validated_scenario_library.json                                 │
└─────────────────────────────────────────────────────────────────────────┘
```

**PHASE 2: PORTFOLIO QUERY**

```
┌─────────────────────────────────────────────────────────────────────────┐
│ INPUT                                                                   │
│                                                                         │
│ Portfolio:                                                              │
│   LOB weights: {Property: 60%, Casualty: 40%, Marine: 0%, ...}         │
│   Total reserves: £200m                                                │
│                                                                         │
│ Query portfolio complexity = 200 × (1 - (0.6² + 0.4²)) = 200 × 0.48    │
│                            = 96                                        │
│                                                                         │
│ Return period: 100 years                                                │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ STEP A: RETURN PERIOD → SEVERITY                                        │
│                                                                         │
│ From fitted GPD: 100-year → severity = 18.5%                           │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ STEP B: FILTER LIBRARY                                                  │
│                                                                         │
│ 1. Severity band: 18.5% ± 3%                                           │
│                                                                         │
│ 2. Complexity band: 96 ± 50 (similar diversification profile)          │
│                                                                         │
│ 3. LOB compatibility:                                                  │
│    - Scenario must affect at least one LOB in portfolio                │
│    - Penalise scenarios that ONLY affect LOBs not in portfolio         │
│                                                                         │
│ 4. Cause diversity:                                                     │
│    - Select from different cause categories                            │
│    - Not 5 hurricane scenarios                                         │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ STEP C: FINE-TUNE FOR EXACT PORTFOLIO                                   │
│                                                                         │
│ For each selected scenario:                                             │
│                                                                         │
│ 1. Zero out LOBs with 0% exposure (Marine in this example)             │
│                                                                         │
│ 2. Rebalance to maintain total severity:                               │
│    - Original: Property -15%, Casualty -8%, Marine -5% = 18.5% total   │
│    - Adjusted: Property -17%, Casualty -10%, Marine 0% = 18.5% total   │
│                                                                         │
│ 3. Weight by portfolio LOB weights:                                    │
│    - Portfolio impact = Σ(LOB_weight × LOB_severity)                   │
│    - = 60% × 17% + 40% × 10% = 10.2% + 4% = 14.2% portfolio impact    │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ STEP D: CHAIN-OF-THOUGHT EXPLANATION                                    │
│                                                                         │
│ LLM receives:                                                           │
│                                                                         │
│ 1. The selected scenario                                               │
│ 2. Historical analogues at similar severity AND complexity:            │
│    - "Syndicate 1183 (2017): £180m reserves, 65% Property/35% Marine,  │
│       complexity=63, saw 22% adverse from HIM hurricanes"              │
│    - "Syndicate 2121 (2020): £420m reserves, diversified across 6 LOBs,│
│       complexity=315, saw 14% adverse from COVID - diversification     │
│       reduced single-LOB concentration risk"                           │
│                                                                         │
│ 3. Instructions:                                                        │
│    - Explain why this severity is appropriate for 100-year event       │
│    - Compare portfolio structure to historical analogues               │
│    - Note diversification effect relative to examples                  │
│                                                                         │
│ Output: documented scenario with reasoning chain                        │
└─────────────────────────────────────────────────────────────────────────┘
```
