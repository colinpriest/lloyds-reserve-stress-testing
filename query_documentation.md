
### `query_documentation.md` — Query-time scenario construction and interpretation (reworded)

This document explains, in implementation-level detail, how the **query-time scenario engines** construct stress scenarios for a **target portfolio specification** (LoB mix + portfolio size) by:

* selecting and combining historical **syndicate–year** LoB observations,
* optionally **supplementing missing LoBs** using same-calendar-year “specialist” syndicates,
* expressing each constructed scenario directly in the  **query portfolio’s LoB basis** ,
* applying an explicit **size adjustment** (hierarchical engine only), and
* producing a  **simulated distribution of portfolio-year severities** , with optional narrative text for interpretability.

Primary implementation: `scripts/stress_test/portfolio_query_hierarchical.py`.

For completeness, an older **synthetic-library Phase 2 query** is included as an appendix. It is not the recommended approach when you require explicit “merged + supplemented” (multi-syndicate) scenarios.

---

## 1) Where the query logic lives

There are two query engines in this repo:

* **Hierarchical (historical-corpus) query (PRIMARY)**
  * File: `scripts/stress_test/portfolio_query_hierarchical.py`
  * Input: an enhanced historical corpus, groupable by **(syndicate, calendar year, LoB)** (typically `results/combined/enhanced_corpus.json`).
  * Output: `ConstructedScenario` objects. Each constructed scenario is assembled from **one chosen calendar year’s** corpus slice, and may be sourced from:
    * a single syndicate-year (preferred when it has high LoB coverage), and/or
    * multiple syndicate-years from the **same calendar year** to supplement missing LoBs.
  * Key property: supports **explicit LoB gap-filling (“supplementation”)** and produces a **single merged narrative** describing the constructed scenario.
* **Synthetic-library query (APPENDIX / alternative)**
  * File: `scripts/stress_test/portfolio_query.py`
  * Key limitation: does not merge multiple historical sources into one scenario; it adjusts single scenarios by zeroing LoBs and rescaling.

The rest of this document focuses on the hierarchical query engine.

---

## 2) Hierarchical query: end-to-end algorithm

This section maps directly to `scripts/stress_test/portfolio_query_hierarchical.py`.

### 2.1 Inputs and unit of analysis

Inputs (query specification):

* **Query LoB weights** : `lob_weights: Dict[str, float]` (normalised to sum to 1 in `PortfolioQueryEngine.query()`).
* **Portfolio size** : `portfolio_size_m` (a size proxy in £m; used only for size adjustment).

**Unit of analysis (important):**

* A single Monte Carlo draw from the hierarchical query engine represents a  **constructed portfolio-year outcome for the query portfolio** , expressed as a severity ratio.
* The engine **conditions scenario construction on a chosen calendar year** (all components are sourced from that same year). This year-conditioning is used to preserve **calendar-year regime coherence** when combining LoBs across syndicates.
* The engine is not constructing a “market observation” for a year. It constructs a **query-portfolio scenario** using historical syndicate-year components taken from a common calendar-year slice.

### 2.2 Corpus preparation (computing LoB-level severities)

`CorpusPreparator.load_and_prepare()` loads the JSON corpus with `movements` and converts it into a `SyndicateYear` object for each (syndicate, year).

Key logic (`_process_syndicate_year()`):

* **Total reserves for a syndicate-year** (`total_reserves_gbp_m`) are taken from the first available of:
  * `prior_reserves_gbp_m`, `technical_provisions_gbp_m`, `claims_outstanding_gbp_m`, `stamp_capacity_gbp_m`.
  * If none exist or are non-positive, that syndicate-year is dropped.
* **LoB weights within the syndicate-year** (`lob_weights`) are determined by:
  * Prefer `m['lob_weights']` if present (segmental analysis extraction).
  * Else fallback to weights proportional to absolute movement amounts per LoB.
  * Else fallback to equal weights.
* **LoB reserves** and **LoB severity** per movement:
  * If precomputed fields exist (`lob_severity_ratio` and `lob_reserves_gbp_m`), they are used directly.
  * Else, LoB reserves are estimated as:
    * `lob_reserves = total_reserves * max(lob_weight, 0.01)` (1% floor).
  * Severity sign convention:
    * `release` → negative movement
    * `strengthening` → positive movement
    * otherwise keep sign as given
  * LoB severity is computed as:
    * `lob_severity = signed_movement / lob_reserves`
  * **Capping** : absolute severities are capped at ±5.0 (±500%) to prevent tiny-exposure artefacts dominating.
* **One observation per LoB per syndicate-year** :
* If multiple movements exist for the same LoB, the engine keeps the one with the largest absolute LoB severity.

Output: each `SyndicateYear` contains `lob_observations[lob] -> LOBObservation` with `lob_severity` and supporting narrative/causes.

### 2.3 Hierarchical matching: filtering + supplementation (same-year only)

Scenario construction happens in `HierarchicalMatcher.construct_scenario_for_year(year, query_lob_weights)`.

Definitions:

* **Required LoBs** are those with query weight > 0.
* **Coverage score** of a syndicate-year is:
  * the sum of query weights for LoBs that syndicate-year contains.

Filtering / gating rules:

* The matcher picks a **primary syndicate-year** if it covers at least `min_coverage` of the query weights (default in matcher is 0.5; the public `query()` call separately enforces `min_coverage` at the scenario level, default 0.3).
* Per-LoB exposure sufficiency rule (prevents “using a tiny LoB slice to represent a major portfolio exposure”):
  * For each query LoB weight (w_q), the source syndicate must have LoB weight at least:
    [
    w_\text{min}(w_q)=\max(0.01,;\min(0.10,;0.25\times w_q))
    ]
  * In code this is `min_source_weight(query_weight)`.

Supplementation (gap filling) rules:

* **Priority 1 (single-syndicate coverage)** :
* choose the syndicate-year with maximal coverage score;
* include each LoB it has **only if** the exposure sufficiency rule passes.
* **Priority 2/3 (same-year specialists)** :
* for each remaining (unmatched) LoB, select a “specialist” syndicate-year from the same calendar year:
  * specialist is the candidate with the highest `synd.lob_weights[lob]`, subject to meeting `w_min(w_q)`.
* add that LoB as a `ScenarioComponent(match_type='supplementary')`.

Result: a dict `LOB -> ScenarioComponent` covering as much of the query mix as possible while preventing unrealistic “micro-exposures” from being used to represent material portfolio exposures.

### 2.4 Merging and standardising to the query LoB mix

Once components exist, `PortfolioQueryEngine.query()` computes a **portfolio severity** directly in the query’s LoB space:

[
\text{portfolio_severity_raw}=\sum_{\ell \in \text{components}} w_\ell^\text{(query)} \times s_\ell
]

Where:

* (w_\ell^\text{(query)}) is the query weight for LoB (\ell)
* (s_\ell) is the LoB severity (a ratio) taken from historical (or computed) LoB reserves for the source syndicate-year.

This is the key “LoB standardisation”: every constructed scenario is expressed as a weighted combination in  **the query portfolio’s LoB basis** , regardless of which syndicate(s) supplied components.

Coverage enforcement at scenario level:

* Coverage fraction = sum of query weights of LoBs present in `components`.
* The scenario is accepted only if `coverage_fraction >= min_coverage` (default 0.3 in `query()`), otherwise it is discarded and the engine resamples.

### 2.5 Dependence/coherence metadata (not “market correlation”)

The matcher labels a simple coherence indicator:

* **`high`** : all components come from a single syndicate-year (best preserves intra-syndicate joint behaviour across LoBs).
* **`medium`** : components come from multiple syndicate-years within the same calendar year (preserves calendar-year regime coherence, but does not preserve intra-syndicate LoB dependence).

This metadata is descriptive; it does not change severities.

### 2.6 Scenario narrative construction (merged scenario text)

`NarrativeSynthesizer.synthesize()` produces the merged scenario text:

* If all components are from one syndicate, the header says “based on Syndicate X in year Y”.
* If multiple syndicates were used, the header says “based on calendar year Y experience (combined from N syndicates)”.
* LoBs are ordered by query weight (largest first).
* For each LoB, the synthesiser includes:
  * LoB share in the query portfolio (e.g. “60% of portfolio”),
  * severity magnitude and direction (“adverse” if severity > 0, else “favorable”),
  * a short snippet of the underlying narrative (truncated),
  * top cause phrases if available.

There is an optional `synthesize_with_llm()` path, but by default it falls back to deterministic synthesis unless an LLM client is provided.

---

## 3) Size adjustment: how it is applied at query time (hierarchical engine)

The hierarchical engine applies a **multiplicative size adjustment factor** to the portfolio severity:

[
\text{portfolio_severity_adjusted}=\text{portfolio_severity_raw}\times \left(\frac{R}{R_\text{ref}}\right)^{\beta(\mathbf{w})}
]

Where:

* (R) is `portfolio_size_m` (in £m).
* (R_\text{ref}) is `DEFAULT_REFERENCE_SIZE_M` (500.0 by default in `portfolio_query_hierarchical.py`).
* (\beta(\mathbf{w})) is a **LoB-mix-weighted size coefficient** computed as:
  [
  \beta(\mathbf{w})=\frac{\sum_\ell w_\ell \beta_\ell}{\sum_\ell w_\ell}
  ]
  with (\beta_\ell) taken from `DEFAULT_SIZE_COEFFICIENTS` (falling back to `DEFAULT_OVERALL_COEFFICIENT` if the LoB is unknown).

Interpretation:

* (\beta<0) means larger portfolios have smaller severity (diversification effect).
* The coefficient is LoB-dependent (e.g. Property may be more negative than Marine), so the size scaling depends on the query LoB mix.

---

## 4) How the size / LoB adjustment coefficients were parameterised (fitting script)

The coefficients used by the hierarchical query engine are hard-coded defaults, but they are documented as “from empirical analysis” and match the defaults in:

* `scripts/stress_test/portfolio_size_adjustment.py`

That file both:

* defines default coefficients, and
* contains code to **refit** them from an enhanced corpus.

### 4.1 Data inputs used for fitting

`PortfolioSizeAdjuster.fit(corpus_path=...)` loads `movements` from an enhanced corpus and builds a regression dataset with:

* `severity_ratio`: movement severity (winsorised at 1st/99th percentiles)
* `size`: a size proxy selected from the first available of:
  * `prior_reserves_gbp_m`, `technical_provisions_gbp_m`, `claims_outstanding_gbp_m`, `stamp_capacity_gbp_m`, `gross_premium_gbp_m`
* `log_size = log(size)`
* `lob` (line of business)
* `cause_category` (first item in `primary_causes` list)
* `year`

It then identifies “common events” using:

* `event_key = year + '_' + cause_category`
* events are kept only if at least `min_events` syndicates are present (default 3)

The reference size (R_\text{ref}) is set to the **median** size in the fitting dataset (`model.reference_size_m = median(size)`).

### 4.2 Overall size effect: event fixed-effects regression (Approach 1)

To reduce confounding (“different events occur in different parts of the size distribution”), the fitter estimates an overall size coefficient using event fixed effects:

[
\text{severity_ratio} = \alpha + \beta\log(\text{size}) + \sum_{e\in\mathcal{E}} \gamma_e \mathbf{1}[\text{event}=e] + \varepsilon
]

Implementation detail:

* event dummies are created with `drop_first=True` to avoid collinearity.
* model is fit via `statsmodels.OLS`.
* if FE fitting fails, it falls back to a simple OLS on `log_size` only.

The fitted (\beta) becomes `model.overall_coefficient`.

### 4.3 LoB-specific coefficients + empirical-Bayes shrinkage (Approach 3)

The fitter estimates LoB-specific size effects by running per-LoB regressions:

[
\text{severity_ratio} = \alpha_\ell + \beta_\ell\log(\text{size}) + \varepsilon_\ell
]

Only LoBs with at least `min_obs_per_lob` observations (default 10) get their own regression; otherwise they fall back to the overall coefficient.

Then it applies a simple empirical-Bayes shrinkage toward the overall coefficient:

* Let (\tau^2) be the between-LoB variance of the raw (\beta_\ell) estimates.
* Let (\sigma_\ell^2) be the within-LoB variance (from the squared standard error of (\beta_\ell)).
* Shrinkage weight:
  [
  \lambda_\ell = \frac{\tau^2}{\tau^2+\sigma_\ell^2}
  ]
* Shrunk coefficient:
  [
  \beta_\ell^\text{(shrunk)} = \lambda_\ell\beta_\ell + (1-\lambda_\ell)\beta
  ]

These shrunk coefficients are used as `lob_coefficients` and can be copied into the hierarchical engine’s coefficient table.

### 4.4 Where the size data comes from (metrics extraction)

The corpus can be “enhanced” with better size proxies using:

* `scripts/stress_test/extract_size_metrics.py` (extracts technical provisions / claims outstanding / stamp capacity / premiums from PDFs/HTML)

and then merged into the corpus by `extract_size_metrics.py merge`, which populates (by syndicate-year):

* `prior_reserves_gbp_m` (from technical provisions or claims outstanding),
* `stamp_capacity_gbp_m`,
* `gross_premium_gbp_m`,

and (when possible) computes `severity_ratio = amount_gbp_m / prior_reserves_gbp_m` with sign based on direction.

---

## 5) Return periods in the hierarchical engine (how to interpret the simulated severity distribution)

The hierarchical engine does not compute EVT/GPD return levels directly. Instead, it produces an empirical severity distribution via `query_summary()`:

* repeatedly construct scenarios for the query portfolio by selecting/supplementing same-year syndicate-year LoB components,
* compute `portfolio_severity_adjusted` for each draw,
* report percentiles (50/75/90/95/99/99.5 by default).

**Interpretation (model-implied annual return levels):**

* Treat each constructed draw as one **portfolio-year outcome** for the query portfolio under the model’s scenario-construction rules.
* Under this modelling assumption, a return period (T) corresponds to exceedance probability (1/T), so the (T)-year level corresponds to percentile (p = 1 - 1/T).

Examples:

* 1-in-20 → 95th percentile
* 1-in-100 → 99th percentile
* 1-in-200 → 99.5th percentile

If you interpret the sampling scheme as implying more than one relevant “observation” per year, adjust accordingly (same logic as (n_\text{obs/year}) in EVT mapping). Otherwise, the default interpretation is “per portfolio-year”.

---

# Appendix A — Synthetic-library query (legacy/alternative; kept for completeness)

(Existing content retained below; wording in this appendix describes the Phase 2 synthetic-library approach rather than the hierarchical engine.)

---

## A2) Key data objects and what they mean

### A2.1 `SyntheticScenario` (library element)

Defined in `scripts/stress_test/config.py`.

Core fields used at query time:

* **`severity_ratio`** : scenario’s total adverse development as a *ratio* (e.g., 0.12 = 12%).
* **`complexity_score`** : the “portfolio complexity” value the scenario was generated for (see below).
* **`lob_breakdown`** : dict `LOB -> severity contribution`. This is treated as *per-LOB severity numbers* (same unit as `severity_ratio`).
* **`cause_category`** ,  **`specific_events`** ,  **`narrative`** : scenario semantics.

Important: the library generation step already normalises LoB names (see Section A5).

### A2.2 `PortfolioSpec` (query input)

Defined in `scripts/stress_test/config.py`.

* **`lob_weights`** : dict `LOB -> weight`, expected to sum to 1 after normalisation.
* **`total_reserves_gbp_m`** : portfolio size in £m.

Derived quantities:

* **HHI** : (\text{HHI}=\sum_i w_i^2)
* **Portfolio complexity** :
  [
  \text{complexity} = R \times (1-\text{HHI})
  ]
  where (R) is total reserves in £m.

Complexity is used as a *size + diversification proxy* to prefer scenarios generated for portfolios of similar scale and concentration.

### A2.3 `StressScenario` (query output)

Defined in `scripts/stress_test/config.py`. Key fields:

* **`return_period`** : user-requested (T) in years.
* **`severity_ratio`** : target return-period severity used for calibration (ratio).
* **`lob_impacts`** : final, portfolio-standardised per-LOB severities (ratio).
* **`portfolio_impact`** : weighted portfolio impact = (\sum_i w_i \times \text{lob_impacts}_i).
* **`narrative`** : scenario narrative text (carried from library).
* **`chain_of_thought`** : explanation text generated at query time via LLM (despite the name, it’s output text).
* **`historical_analogues`** : nearest historical movements in latent space (if embedding space available).
* **`fine_tuning_applied`** : audit trail of how LoBs were zeroed/scaled.

---
