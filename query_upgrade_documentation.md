# query_upgrade_documentation.md — Specification for unbiased year sampling + year-block bootstrap (hierarchical query)

This document specifies an upgrade to the **hierarchical query engine** (`scripts/stress_test/portfolio_query_hierarchical.py`) so that:

1. **Calendar years are sampled evenly** (each year contributes equal weight to the simulated severity distribution), and  
2. **Within-year scenario construction is not dominated by large / multi-line syndicates** via deterministic “max coverage” selection, and  
3. The engine supports **year-block bootstrap** to quantify uncertainty in return-level estimates without assuming syndicate-years are independent “time draws”.

The goal is to preserve your existing modelling choices (same-year supplementation; LoB exposure sufficiency; LoB-basis standardisation; size scaling) while removing avoidable **sampling bias** and adding **robust uncertainty estimation**.

---

## 1) Definitions

### 1.1 Query portfolio specification

- `X = (lob_weights, portfolio_size_m)` where:
  - `lob_weights` is a normalised dict `LOB -> weight` that sums to 1.
  - `portfolio_size_m` is a size proxy in £m.

### 1.2 Constructed scenario draw

A single draw produces:

- `portfolio_severity_raw`
- `portfolio_severity_adjusted` (after size scaling)
- `coverage_fraction`
- `components` (LoB -> source syndicate-year)
- `coherence_label` (`high`/`medium` as currently used)
- narrative text (deterministic or LLM-assisted)

### 1.3 Return-level interpretation (unchanged)

For a simulated annual portfolio-year severity distribution, the model-implied T-year return level is the percentile:

- `p = 1 - 1/T`
- example: T=200 → p=0.995

This spec does **not** change that interpretation; it changes how the distribution is sampled and how uncertainty is quantified.

---

## 2) Problems with the current sampling behaviour (to be corrected)

### 2.1 Implicit reweighting of years
If the engine:
- samples a year,
- attempts scenario construction,
- rejects/resamples until coverage >= `min_coverage`,

then years with higher feasibility (better LoB disclosure / easier gap fill) are **over-represented** in the final sample.

### 2.2 Deterministic within-year selection biases
If the engine always chooses:
- primary syndicate-year = argmax coverage,
- specialist syndicate-year = argmax LoB weight,

then outcomes are biased toward:
- multi-line syndicates (high coverage),
- (often) larger syndicates or syndicates with richer disclosure,
- a narrow subset of syndicates per year (reduced diversity).

---

## 3) Upgrade A — Even-year sampling via “per-year batches” + weighted quantiles

### 3.1 Design principle
To ensure **even year weighting**, do **not** sample “years then accept/reject draws”. Instead:

1) Enumerate a set of years `Y = {y1, …, yK}` to include in the simulation (see feasibility in §3.4).  
2) For each year `y` generate a fixed number of draws `n_per_year`.  
3) Combine all draws using **equal total weight per year**.

This guarantees that the simulated distribution is the *equal-weight mixture over years*:
\[
\hat F(s \mid X) = \frac{1}{K} \sum_{y \in Y} \hat F_y(s \mid X)
\]
where `F_y` is the within-year constructed severity distribution induced by stochastic primary/supplementation selection.

### 3.2 API changes

Add (or extend) a method on `PortfolioQueryEngine`:

```python
def query_summary_even_years(
    self,
    lob_weights: Dict[str, float],
    portfolio_size_m: float,
    n_per_year: int = 200,
    percentiles: Tuple[float, ...] = (0.5, 0.75, 0.9, 0.95, 0.99, 0.995),
    min_coverage: float = 0.3,
    seed: int | None = None,
    year_set: Optional[List[int]] = None,
    feasibility_mode: str = "feasible_years",
    min_success_per_year: int = 1,
) -> QuerySummary
```

Where:

- `n_per_year`: number of draws generated for each year included.
- `year_set`: optional explicit year list to use (for experiments / bootstrap replicates).
- `feasibility_mode`: how to define `Y` (see §3.4).
- `min_success_per_year`: if a year yields fewer than this many valid draws, it is excluded (and logged) *before* mixing.

### 3.3 Output changes (required for auditability)

Extend the returned summary with:

- `years_included`: list of years used in the mixture
- `years_excluded`: `{year: reason}`
- `per_year_stats`: for each year:
  - `attempted`: draws attempted
  - `valid`: draws with `coverage_fraction >= min_coverage`
  - `valid_rate`
  - `primary_selection_counts`: distribution of primary syndicate-year IDs chosen
  - `supplementation_counts`: counts of supplementary picks per LoB (optional)
- `weights`: description of year weights (should state “equal total weight per year”)

### 3.4 Year feasibility definition (so “even sampling” is explicit)

Because some years may not contain enough information to construct scenarios for a given query portfolio, define one of the following modes.

**Recommended default: `feasible_years`**

- A year `y` is *feasible* if at least one constructed draw can reach `coverage_fraction >= min_coverage` using same-year supplementation under the current rules.
- Implementation: run a cheap feasibility pre-check per year (see §3.4.1) or attempt a small number of trial draws.

Interpretation to document:
- “Return levels are conditional on the set of calendar years in the corpus that are feasible for constructing a scenario for the query portfolio under the model rules.”

**Alternative: `all_years_with_missing` (optional)**
- Include all years but allow incomplete coverage:
  - keep partial scenarios and record `coverage_fraction`.
  - compute return levels either:
    - on full draws (with explicit caveat), or
    - on weighted/adjusted severities (not recommended unless you define a principled adjustment).
This mode is only recommended if you have a defensible missing-LoB imputation.

#### 3.4.1 Feasibility pre-check (implementation detail)

Add:

```python
def year_feasibility(year: int, query_lob_weights: Dict[str, float], min_coverage: float) -> bool
```

Cheap check options (choose one):

- **Deterministic check (fast):**
  - compute max achievable coverage by union of LoBs that satisfy the exposure sufficiency rule within year.
  - if max coverage < min_coverage → infeasible.
- **Trial-draw check (robust):**
  - run `t` stochastic construction attempts (e.g., t=10) and accept year if any succeeds.

---

## 4) Upgrade B — Stochastic within-year selection to reduce size / multi-line dominance

### 4.1 Replace “argmax” with probabilistic selection

#### 4.1.1 Primary syndicate-year selection
Currently: choose the single syndicate-year with maximum coverage score.

Upgrade: sample a primary from a candidate set with probabilities derived from **coverage**, with temperature/capping to avoid dominance.

Specification:

- Candidate set: syndicate-years in year `y` with `coverage_score >= primary_min_coverage` (existing threshold).
- Define base score:
  - `score_i = clip(coverage_score_i, 0, coverage_cap) ** alpha`
- Convert to probabilities with softmax temperature `tau`:
  - `p_i ∝ exp(score_i / tau)`
- Default parameters:
  - `coverage_cap = 0.9`
  - `alpha = 1.0`
  - `tau = 0.1` (lower = more “greedy”, higher = more uniform)

**Important:** do **not** include raw size in the primary selection probability by default. If size matching is desired, make it an explicit optional feature (see §4.3).

#### 4.1.2 Specialist selection for missing LoBs
Currently: choose the candidate with highest `synd.lob_weights[lob]` subject to sufficiency.

Upgrade: select specialists stochastically among the top candidates.

Specification:

- Candidate set for LoB `ℓ`: syndicate-years meeting `min_source_weight(w_q)` for that LoB.
- Choose among top `k` by source LoB weight (e.g., k=5) using:
  - `p_j ∝ (source_lob_weight_j) ** alpha_spec`
- Default: `k=5`, `alpha_spec=1.0`.

This preserves the idea of “specialist” but avoids deterministic re-use of the same syndicate.

### 4.2 Reproducibility requirement
All stochastic selections must be driven by a passed `seed` (or derived deterministic seed per query), and the engine must log:

- `seed`
- `sampling_config` (all parameters above)

### 4.3 Optional explicit size-matching (off by default)
If you later decide the base-year analogues should be size-similar (even though a size adjustment is applied), implement size matching as an explicit kernel factor:

- `k_size = exp(- (log(size_i) - log(size_target))^2 / (2*sigma^2))`

and include it multiplicatively in the probability score. This should remain off by default because it changes the interpretation of “year mixture”.

---

## 5) How to compute return levels from even-year samples

### 5.1 Weighted quantiles (must support unequal per-year valid counts)
Even if you generate `n_per_year` attempts, some years may yield fewer valid draws. To keep **equal year weight**, use weights:

- For year `y` with `m_y` valid draws:
  - each draw weight = `1 / (K * m_y)`

Return level `q_p` is then the **weighted p-quantile** of `portfolio_severity_adjusted`.

### 5.2 Minimum per-year validity rule
To avoid extreme weights from a year with only 1 valid draw:

- enforce `m_y >= min_success_per_year` (default 10 recommended for production reporting; default 1 for development),
- otherwise exclude year and report in `years_excluded`.

---

## 6) Upgrade C — Year-block bootstrap (uncertainty estimation)

### 6.1 Purpose
Quantify uncertainty in return levels due to having only a limited set of distinct calendar years, without pretending syndicate-years are independent time draws.

### 6.2 Bootstrap unit and procedure
**Bootstrap unit:** calendar year.

For each replicate `b = 1..B`:

1) Sample `K` years with replacement from the available year list (or feasible year list for the query portfolio).  
   - Denote sampled multiset `Y_b`, which may contain repeated years.
2) For each year instance in `Y_b`, generate `n_per_year` draws using the upgraded stochastic construction rules.
3) Combine all draws with **equal weight per sampled year instance**:
   - if a year appears twice in `Y_b`, it receives double weight in that replicate (as standard bootstrap).
4) Compute return levels (e.g., 95%, 99%, 99.5%) for that replicate.

Repeat across `B` replicates to produce a bootstrap distribution of return levels.

### 6.3 API addition

Add:

```python
def query_summary_year_block_bootstrap(
    self,
    lob_weights: Dict[str, float],
    portfolio_size_m: float,
    percentiles: Tuple[float, ...],
    B: int = 500,
    n_per_year: int = 200,
    min_coverage: float = 0.3,
    seed: int | None = None,
    feasibility_mode: str = "feasible_years",
) -> BootstrapSummary
```

### 6.4 Outputs
Return:

- `point_estimate`: quantiles from full-data `query_summary_even_years`
- `bootstrap_quantiles`: list of `{p: value}` per replicate
- for each percentile `p`:
  - `ci_90 = [q_0.05, q_0.95]`
  - `ci_95 = [q_0.025, q_0.975]`
  - `std_err`
  - `bias = mean(q_boot) - q_point` (optional)

Include diagnostic fields:
- bootstrap year samples (optional; can be large—store hashed summary instead)
- excluded years rates if feasibility is used

### 6.5 How to use bootstrap results in reporting
- Report return level as: `q_p (point estimate)` with a year-block interval.
- If intervals are wide:
  - keep the point estimate, but explicitly caveat “limited distinct calendar years”.
- For conservative stress testing:
  - use an upper CI bound (e.g., 95% upper) as the severity calibration.

---

## 7) Implementation plan (files, classes, tests)

### 7.1 Files to change / add

1) `scripts/stress_test/portfolio_query_hierarchical.py`
   - Add `query_summary_even_years(...)`
   - Add `query_summary_year_block_bootstrap(...)`
   - Refactor selection logic to support stochastic primary/specialist selection (parameterised; seedable)
   - Add logging / diagnostics outputs described above

2) (Optional) `scripts/stress_test/sampling_utils.py` (new)
   - weighted quantile implementation
   - stable RNG / seed utilities
   - feasibility pre-check utilities

3) Tests (new or extend)
   - `tests/test_even_year_sampling.py`
     - verifies year contribution is equal (within tolerance)
     - verifies deterministic output for a fixed seed
   - `tests/test_bootstrap.py`
     - verifies bootstrap output shape, monotonicity, non-degenerate CIs

### 7.2 Acceptance criteria

- **Even-year weighting**: across large runs, each year contributes ~equal total weight to the final distribution.
- **No rejection bias**: the algorithm must not “resample until success” without correcting weights.
- **Reduced deterministic dominance**: within a year, primary syndicate selection is not always the same; distribution is reproducible given a seed.
- **Bootstrap works end-to-end**: outputs CIs; no crashes when years are repeated; diagnostics included.

---

## 8) Notes on “bias by syndicate size etc.”
This upgrade removes two major *algorithmic* sources of bias:

- deterministic max-coverage primary selection (often correlated with size / multi-line status),
- deterministic max-weight specialist selection.

It does not claim that the underlying historical corpus is unbiased. Any corpus bias (e.g., disclosure quality correlated with size) should still be stated as a limitation. The diagnostics (`primary_selection_counts`, excluded years) are intended to make such biases visible.

---

## 9) Recommended default configuration (practical)
- `feasibility_mode = "feasible_years"`
- `min_coverage = 0.3` (as currently)
- `n_per_year = 200` (increase if runtime allows; you want stable 99.5%)
- `min_success_per_year = 20` (for published numbers; lower for development)
- primary selection: `coverage_cap=0.9, alpha=1.0, tau=0.15`
- specialist selection: `top_k=5, alpha_spec=1.0`
- bootstrap: `B=500` (or 200 for dev), same `n_per_year`

---

## 10) Pseudocode summary

### 10.1 Even-year summary (core change)
```
years = choose_year_set(feasibility_mode)
results = []

for year in years:
    year_draws = []
    for j in range(n_per_year):
        scenario = construct_scenario_for_year_stochastic(year, X, seed=seed)
        if scenario.coverage >= min_coverage:
            year_draws.append(scenario.severity_adjusted)

    if len(year_draws) < min_success_per_year:
        exclude year (log)
        continue

    assign weight 1/(K * len(year_draws)) to each draw in year_draws
    results.extend((value, weight))

return weighted_quantiles(results, percentiles)
```

### 10.2 Year-block bootstrap
```
point = query_summary_even_years(full_corpus)

for b in 1..B:
    sampled_years = sample_with_replacement(years, size=len(years))
    # repeated years appear multiple times and thus get more weight in this replicate
    replicate = query_summary_even_years(corpus restricted to sampled_years, year_set=sampled_years, ...)
    store replicate quantiles

return point + CI from bootstrap distribution
```
