# Exposure Adjustment Methodology

This document describes how the stress testing system adjusts historical Lloyd's
reserve blowout data for differences in **syndicate size** and **lines of business
(LoB) mix** between the source syndicates in the historical corpus and the target
portfolio being stress-tested.

The adjustments operate along two orthogonal dimensions:

1. **LoB mix standardisation** — re-expresses every historical observation in the
   target portfolio's LoB basis so that severity comparisons are like-for-like.
2. **Portfolio size adjustment** — scales severity using an empirical power-law
   relationship between portfolio size and reserve volatility.

Both adjustments preserve the causal narrative and regime information attached to
each historical scenario.

---

## 1  Definitions and Notation

| Symbol | Meaning |
|--------|---------|
| $\ell$ | A line of business (LoB), e.g. Property, Casualty |
| $\mathcal{L}$ | The set of 13 standard Lloyd's LoB categories |
| $w^{(q)}_\ell$ | Weight of LoB $\ell$ in the **query** (target) portfolio, $\sum_\ell w^{(q)}_\ell = 1$ |
| $w^{(s)}_\ell$ | Weight of LoB $\ell$ in a **source** syndicate-year |
| $R^{(s)}$ | Total reserves (£m) for a source syndicate-year |
| $R^{(s)}_\ell$ | Reserves attributable to LoB $\ell$ in the source, $R^{(s)}_\ell = R^{(s)} \cdot w^{(s)}_\ell$ |
| $M^{(s)}_\ell$ | Signed reserve movement (£m) for LoB $\ell$ in the source (+ve = strengthening) |
| $s_\ell$ | LoB-level severity ratio, $s_\ell = M^{(s)}_\ell / R^{(s)}_\ell$ |
| $R^{(q)}$ | Total reserves (£m) for the query portfolio |
| $R_{\text{ref}}$ | Reference portfolio size (£m), default 500 |
| $\beta_\ell$ | Size-adjustment exponent for LoB $\ell$ |
| $\bar{\beta}$ | Overall (average) size-adjustment exponent |

---

## 2  Severity Ratio: The Base Measure

The fundamental unit of reserve stress is the **severity ratio** — the reserve
movement expressed as a fraction of opening reserves.

### 2.1  Syndicate-level severity

When only aggregate data are available, severity is computed as:

$$
S = \frac{M}{R}
$$

where $M$ is the signed reserve movement (£m) and $R$ is the opening reserve
base (£m), determined from the best available source in priority order:

1. Prior-year reserves (`prior_reserves_gbp_m`)
2. Technical provisions (`technical_provisions_gbp_m`)
3. Claims outstanding (`claims_outstanding_gbp_m`)
4. Stamp capacity (`stamp_capacity_gbp_m`)

The sign convention is:

- **Strengthening** (adverse development): $M > 0$, so $S > 0$
- **Release** (favourable development): $M < 0$, so $S < 0$

Severity ratios are **winsorised** at the 1st and 99th percentiles to limit the
influence of outliers.

### 2.2  Dual raw severity metrics

The analysis table computes two parallel raw severity measures:

| Metric | Symbol | Computation | Source |
|--------|--------|-------------|--------|
| **Raw-A** (aggregate) | $S_{\text{raw-A}}$ | $M_{\text{total}} / R^{(s)}$ | Total signed movement divided by reserve base |
| **Raw-B** (LoB-weighted) | $S_{\text{raw-B}}$ | $\mathbf{w}^{(s)} \cdot \mathbf{s}_\ell$ | Dot product of source weights and LoB severities |

Raw-A is preferred when a precomputed `severity_ratio` field exists in the corpus;
Raw-B reconstructs severity from the LoB decomposition.  Both are carried through
analysis to allow sensitivity comparisons.

### 2.3  LoB-level severity

For the LoB-mix adjustment to work, severity must be computed at the LoB level.
The LoB reserves are derived from the syndicate total reserves and the LoB
weight:

$$
R^{(s)}_\ell = R^{(s)} \cdot \max\!\bigl(w^{(s)}_\ell,\; 0.01\bigr)
$$

The 1% floor prevents division by near-zero exposures. The LoB severity is then:

$$
s_\ell = \frac{M^{(s)}_\ell}{R^{(s)}_\ell}
$$

LoB severities are **capped** at $\pm 5.0$ (i.e. $\pm 500\%$) to guard against
unrealistic values arising from very small LoB exposures in the source data.
When multiple records exist for the same LoB within a syndicate-year, the record
with the largest absolute movement amount is retained.

Unobserved LOBs (those without movement data) are assigned a severity of 0.0
(no movement assumed).

---

## 3  Lines of Business Mix Adjustment

### 3.1  The problem

Historical reserve blowout observations come from syndicates whose LoB
composition may differ markedly from the target portfolio. A syndicate writing
80% Property and 20% Casualty is not directly comparable to a portfolio that is
40% Property and 60% Casualty — even if the same market event affected both.

### 3.2  LoB weight extraction

For each syndicate-year in the corpus, LoB weights $w^{(s)}_\ell$ are extracted
from the syndicate's annual report using a priority cascade:

1. **Segmental Analysis** (Note 4) — the most authoritative breakdown
2. **Gross Written Premium by class** — a volume-based proxy
3. **Net Earned Premium by segment**
4. **Technical Provisions by segment**
5. **Stamp Capacity allocation**

Raw class names from syndicate reports (approximately 80 observed variants) are
mapped to 13 standard Lloyd's LoB categories through exact matching, partial
pattern matching, and keyword-based heuristics:

| # | Standard LoB |
|---|-------------|
| 1 | Property |
| 2 | Casualty |
| 3 | Marine |
| 4 | Energy |
| 5 | Motor |
| 6 | Aviation |
| 7 | Reinsurance — Property |
| 8 | Reinsurance — Casualty |
| 9 | Reinsurance — Specialty |
| 10 | Professional Lines |
| 11 | Accident & Health |
| 12 | Cyber |
| 13 | Aggregate |

When no segmental data are available, weights fall back to movement-amount-based
proportions:

$$
w^{(s)}_\ell = \frac{\sum_j \lvert M^{(s)}_{\ell,j}\rvert}{\sum_{\ell'}\sum_j \lvert M^{(s)}_{\ell',j}\rvert}
$$

If no amounts are available either, `weight_source` is set to `"none"`.

### 3.3  Portfolio severity standardisation

Once LoB-level severities $s_\ell$ have been computed for the source
syndicate-year, the **portfolio severity** is re-expressed in the query
portfolio's LoB basis by taking the weighted sum:

$$
S_{\text{raw}} = \sum_{\ell \in \mathcal{L}} w^{(q)}_\ell \cdot s_\ell
$$

This is the critical step: regardless of the source syndicate's own LoB mix,
every scenario's severity is projected onto the **query portfolio's weight
vector**. A source syndicate that was 80% Property contributes its Property
severity at whatever weight Property has in the *target* portfolio.

NaN values in the LoB severity vector are treated as 0.0 (no movement for that
LoB).

### 3.4  Hierarchical matching

Not every source syndicate covers every LoB in the query portfolio. The system
uses a three-priority hierarchical matching strategy to assemble scenario
components, all drawn from the **same calendar year** to preserve correlation
structure:

| Priority | Strategy | Correlation preserved |
|----------|----------|-----------------------|
| 1 | **Single syndicate** covers all (or most) query LoB | Full intra-syndicate correlation |
| 2 | **Primary + supplements** — best single syndicate plus same-year specialists for gaps | Inter-LoB market correlation (same year) |
| 3 | **Full synthetic** — each LoB sourced from a different same-year specialist | Temporal correlation only |

#### Exposure sufficiency rule

To prevent a 1% LoB exposure in the source from representing a 30% weight in the
query, a minimum source weight is enforced:

$$
w^{(s)}_{\ell,\,\min} = \max\!\Bigl(0.01,\;\min\!\bigl(0.10,\;0.25 \cdot w^{(q)}_\ell\bigr)\Bigr)
$$

A source syndicate is only allowed to supply LoB $\ell$ if
$w^{(s)}_\ell \ge w^{(s)}_{\ell,\,\min}$.

#### Coverage fraction

The coverage fraction of a constructed scenario is:

$$
C = \sum_{\ell \,\in\, \text{matched}} w^{(q)}_\ell
$$

Scenarios with $C$ below a configurable minimum (default 0.50) are discarded.

### 3.5  Concentration measure

The Herfindahl–Hirschman Index (HHI) measures LoB concentration in a syndicate:

$$
\text{HHI} = \sum_\ell \bigl(w^{(s)}_\ell\bigr)^2
$$

A value near 1 indicates a mono-line syndicate; a value near $1/|\mathcal{L}|$
indicates maximum diversification. The HHI is used in portfolio complexity
scoring:

$$
\text{Complexity} = R \times (1 - \text{HHI})
$$

---

## 4  Portfolio Size Adjustment

### 4.1  Motivation

Larger Lloyd's syndicates tend to exhibit lower reserve volatility per unit of
exposure. This arises from:

- **Diversification across policies** — risk-specific randomness averages out.
- **Diversification across LoB** — larger syndicates tend to write more lines.
- **Operational sophistication** — larger syndicates tend to have better
  reserving processes.

A stress observation from a £50m syndicate cannot be applied to a £2bn portfolio
without adjustment — the implied severity would be unrealistically high.

### 4.2  The power-law model

The size-severity relationship is modelled as a power law:

$$
S_{\text{adjusted}} = S_{\text{raw}} \cdot \left(\frac{R^{(q)}}{R_{\text{ref}}}\right)^{\!\beta}
$$

where:

- $S_{\text{raw}}$ is the LoB-standardised portfolio severity from §3.3
- $R^{(q)}$ is the query portfolio's total reserves (£m)
- $R_{\text{ref}}$ is the reference portfolio size (default £500m, set to the
  median syndicate size in the training data)
- $\beta$ is the size-adjustment exponent

The **adjustment factor** applied multiplicatively to severity is therefore:

$$
A = \left(\frac{R^{(q)}}{R_{\text{ref}}}\right)^{\!\beta}
$$

Guard rails: if either $R^{(q)} \le 0$ or $R_{\text{ref}} \le 0$, the
adjustment factor defaults to 1.0 (no adjustment).

**Interpretation of $\beta$:**

| $\beta$ value | Meaning |
|---------------|---------|
| $\beta < 0$ | Larger portfolios have **lower** severity — diversification benefit |
| $\beta = 0$ | Size has no effect on severity |
| $\beta > 0$ | Larger portfolios have **higher** severity (unusual, but observed for certain reinsurance lines) |

### 4.3  LoB-weighted composite exponent

Because different lines of business exhibit different size-sensitivity, the
system uses a LoB-weighted composite exponent for mixed portfolios:

$$
\beta_{\text{weighted}} = \frac{\sum_\ell w^{(q)}_\ell \cdot \beta_\ell}{\sum_\ell w^{(q)}_\ell}
$$

If all weights sum to zero, the overall default coefficient $\bar{\beta}$ is
returned.

The complete size-adjusted severity is:

$$
\boxed{S_{\text{adjusted}} = \left(\sum_\ell w^{(q)}_\ell \cdot s_\ell\right) \cdot \left(\frac{R^{(q)}}{R_{\text{ref}}}\right)^{\!\beta_{\text{weighted}}}}
$$

This is the **central formula** of the exposure adjustment system.

---

## 5  Estimation of Size Coefficients

The LoB-specific exponents $\beta_\ell$ are estimated empirically from the
Lloyd's syndicate corpus using a two-stage procedure.

### 5.1  Stage 1: Overall coefficient via event fixed effects

The overall size coefficient $\bar{\beta}$ is estimated by OLS regression with
event fixed effects:

$$
s_i = \alpha + \bar{\beta} \cdot \ln(R_i) + \sum_e \gamma_e \cdot \mathbf{1}[\text{event}_i = e] + \varepsilon_i
$$

where:

- $s_i$ is the severity ratio for observation $i$
- $R_i$ is the portfolio size (reserves) for observation $i$
- $\text{event}_i = (\text{year}_i, \text{cause\_category}_i)$ identifies the
  common market event
- $\gamma_e$ are event fixed effects
- $\mathbf{1}[\cdot]$ is the indicator function

The event fixed effects control for confounding: certain events may
disproportionately affect syndicates of particular sizes. By absorbing event-level
variation, the coefficient $\bar{\beta}$ isolates the pure size effect.

**Identification requirement:** An event must involve at least `min_events`
syndicates (default 3) to be included.

**Fallback:** If the event fixed-effects regression fails (e.g. collinearity), a
simple OLS on $\ln(R)$ alone is used.

### 5.2  Stage 2: LoB-specific coefficients with hierarchical shrinkage

Individual LoB coefficients are estimated by running separate regressions for
each LoB:

$$
s_{i,\ell} = \alpha_\ell + \beta_\ell \cdot \ln(R_i) + \varepsilon_{i,\ell}
\quad \text{for all } i \text{ in LoB } \ell
$$

requiring at least `min_obs_per_lob` observations (default 10).

#### Empirical Bayes shrinkage

Raw LoB estimates can be noisy for lines with sparse data. The system applies
James–Stein-type empirical Bayes shrinkage toward the overall coefficient:

**Step 1.** Estimate between-LoB variance:

$$
\tau^2 = \operatorname{Var}\!\bigl(\{\hat{\beta}_\ell\}_\ell\bigr)
$$

**Step 2.** For each LoB $\ell$ with sampling variance $\sigma^2_\ell$ (the
squared standard error of $\hat{\beta}_\ell$), compute the shrinkage factor:

$$
\lambda_\ell = \frac{\tau^2}{\tau^2 + \sigma^2_\ell}
$$

**Step 3.** The shrunk estimate is:

$$
\beta^*_\ell = \lambda_\ell \cdot \hat{\beta}_\ell + (1 - \lambda_\ell) \cdot \bar{\beta}
$$

**Interpretation:**

- When $\sigma^2_\ell$ is small (precise estimate), $\lambda_\ell \to 1$ and the
  LoB-specific estimate dominates.
- When $\sigma^2_\ell$ is large (imprecise), $\lambda_\ell \to 0$ and the
  estimate is pulled toward the overall mean $\bar{\beta}$.
- For LoB with fewer than `min_obs_per_lob` observations, the standard error is
  artificially inflated ($2\times$ the overall SE), ensuring strong shrinkage
  toward the overall coefficient.

This prevents overfitting on small LoB samples while still allowing data-rich
lines (e.g. Property, Casualty) to express their own size-sensitivity.

---

## 6  Default Parameter Values

When insufficient data are available for fitting, or as starting values, the
system uses the following empirically estimated defaults:

### 6.1  Overall coefficient

$$
\bar{\beta} = -0.24
$$

### 6.2  LoB-specific coefficients

| Line of Business | $\beta_\ell$ | Interpretation |
|------------------|:-----------:|----------------|
| Property | $-0.49$ | Strongest diversification benefit |
| Aggregate | $-0.34$ | Strong diversification |
| Casualty | $-0.30$ | Strong diversification |
| Energy | $-0.05$ | Weak diversification |
| Professional Lines | $-0.03$ | Minimal size effect |
| Reinsurance — Casualty | $-0.02$ | Minimal size effect |
| Aviation | $-0.02$ | Minimal size effect |
| Motor | $-0.02$ | Minimal size effect |
| Cyber | $-0.02$ | Minimal size effect |
| Accident & Health | $-0.01$ | Negligible size effect |
| Marine | $-0.01$ | Negligible size effect |
| Reinsurance — Specialty | $0.00$ | No size effect |
| Reinsurance — Property | $+0.02$ | Slight reverse effect |

### 6.3  Reference size

$$
R_{\text{ref}} = \text{£}500\text{m}
$$

Set to the approximate median syndicate total reserves in the training data.

---

## 7  Worked Example

Consider a query portfolio with:

- $R^{(q)} = 200$ £m
- $w^{(q)}_{\text{Property}} = 0.60$, $w^{(q)}_{\text{Casualty}} = 0.40$

And a source scenario from a syndicate-year yielding LoB severities:

- $s_{\text{Property}} = 0.15$ (15% adverse)
- $s_{\text{Casualty}} = 0.08$ (8% adverse)

**Step 1: LoB-standardised severity**

$$
S_{\text{raw}} = 0.60 \times 0.15 + 0.40 \times 0.08 = 0.090 + 0.032 = 0.122
$$

**Step 2: Composite size exponent**

$$
\beta_{\text{weighted}} = \frac{0.60 \times (-0.49) + 0.40 \times (-0.30)}{0.60 + 0.40} = \frac{-0.294 + (-0.120)}{1.0} = -0.414
$$

**Step 3: Size adjustment factor**

$$
A = \left(\frac{200}{500}\right)^{-0.414} = 0.4^{-0.414} = e^{-0.414 \ln 0.4} = e^{-0.414 \times (-0.9163)} = e^{0.3793} \approx 1.461
$$

**Step 4: Adjusted severity**

$$
S_{\text{adjusted}} = 0.122 \times 1.461 \approx 0.178 \quad (17.8\%)
$$

The smaller portfolio (£200m vs. £500m reference) receives a **higher** adjusted
severity, reflecting reduced diversification benefit.

---

## 8  Configuration and Parameters

### 8.1  Fitting parameters

| Parameter | Default | Description |
|-----------|:-------:|-------------|
| `min_obs_per_lob` | 10 | Minimum observations to fit a LoB-specific coefficient |
| `min_events` | 3 | Minimum syndicates per event for inclusion in event-FE regression |
| `reference_size_m` | 500.0 | Reference portfolio size (£m); set to training-data median when fitted |

### 8.2  Query-time parameters

| Parameter | Default | Description |
|-----------|:-------:|-------------|
| `min_coverage` | 0.50 | Minimum fraction of query LoB weight that must be covered |
| `coverage_cap` | 0.90 | Cap on coverage score used in stochastic primary selection |
| `tau` (softmax temperature) | 0.15 | Controls randomness in primary syndicate selection |
| `top_k` | 5 | Number of specialist candidates considered per LoB gap |
| `max_severity` | 5.0 | Cap on absolute LoB severity ($\pm 500\%$) |
| `severity_winsorisation` | [1%, 99%] | Quantile bounds for winsorising raw severity ratios |

### 8.3  Exposure sufficiency

The minimum source LoB weight required to represent a query LoB:

$$
w^{(s)}_{\ell,\,\min} = \max\!\bigl(0.01,\;\min(0.10,\;0.25 \cdot w^{(q)}_\ell)\bigr)
$$

Examples:

| Query weight $w^{(q)}_\ell$ | Minimum source weight |
|:---:|:---:|
| 5% | 1.25% (floored to 1%) |
| 10% | 2.5% |
| 30% | 7.5% |
| 50% | 10% (capped) |
| 80% | 10% (capped) |

---

## 9  Analysis Table Construction

The unified analysis table (`analysis_table.py`) merges three data sources into
a single DataFrame with one row per syndicate-year observation.

### 9.1  Data sources

| Source | File | Contents |
|--------|------|----------|
| Historical corpus | `enhanced_corpus.json` | Reserve movements with severity ratios, directions, narratives |
| LoB weights | `lob_weights.json` | Extracted LoB weight vectors per syndicate-year |
| Size metrics | `size_metrics.json` | Reserve bases, technical provisions, stamp capacity |

### 9.2  Reserve base determination

The reserve base $R^{(s)}$ is determined by a priority cascade across both
corpus and size metrics:

| Priority | Field | Source |
|:---:|-------|--------|
| 1 | `prior_reserves_gbp_m` | Corpus |
| 2 | `technical_provisions_gbp_m` | Size metrics |
| 3 | `claims_outstanding_gbp_m` | Size metrics |
| 4 | `stamp_capacity_gbp_m` | Corpus or size metrics |

### 9.3  Computed columns per row

| Column | Computation |
|--------|-------------|
| `R_s` | Reserve base (£m), from priority cascade |
| `R_s_source` | Which field provided the reserve base |
| `w_s` | LoB weights dict |
| `w_s_array` | 13-element normalised array aligned to `LLOYDS_LOBS` |
| `s_lob` | 13-element LoB severity array (capped at ±5.0) |
| `S_raw_a` | Aggregate severity: total movement / reserves |
| `S_raw_b` | LoB-reconstructed severity: dot(w_s, s_lob) |
| `HHI_s` | Herfindahl–Hirschman Index |
| `n_lobs` | Count of LOBs with observed movements |
| `lob_present_mask` | Boolean mask of which LOBs have data |
| `cause_category` | Classified cause (from keyword matching) |
| `event_id` | `"{year}_{cause_category}"` for fixed-effects grouping |
| `cap_binding` | Dict of LOBs where severity hit the ±5.0 cap |
| `data_quality_flags` | Dict: `weight_source`, `extraction_confidence`, `R_s_source` |

### 9.4  Query-specific columns

For each target portfolio, `add_query_columns()` appends:

| Column | Computation |
|--------|-------------|
| `S_std_{name}` | $\mathbf{w}^{(q)} \cdot \mathbf{s}_\ell$ — mix-standardised severity |
| `beta_weighted_{name}` | Composite $\beta$ for this portfolio's LoB mix |
| `S_adj_{name}` | $S_{\text{std}} \times (R^{(q)} / R_{\text{ref}})^{\beta_{\text{weighted}}}$ |

### 9.5  Subset definitions

The analysis table supports named subsets for different analysis contexts:

| Subset | Filter | Purpose |
|--------|--------|---------|
| **DENSE** | Years 2014–2019 | High-density panel (many syndicates per year) |
| **MID** | Years 2020–2023 | Mid-density panel |
| **FULL** | Years 2014–2023 | All complete years |
| **BALANCED_K8** | 2014–2023, syndicates in ≥ 8 years | Balanced panel for trend analysis |
| **BALANCED_K6** | 2014–2023, syndicates in ≥ 6 years | Relaxed balanced panel |
| **BALANCED_ALL** | 2014–2023, syndicates in all years | Strictly balanced panel |
| **2024** | Year 2024 only | Partial year (Raw-A only) |

Each subset returns a `CoverageStats` dataclass documenting:
- `n_observations`, `n_syndicates`
- `syndicates_per_year_min`, `syndicates_per_year_max`
- `year_range`
- `exclusion_rules` applied
- `cap_binding_rates`

### 9.6  Cap-binding diagnostics

The `compute_cap_binding_stats()` function computes:

| Statistic | Description |
|-----------|-------------|
| `pct_capped_pos_5` | % of LoB-level severities hitting +5.0 cap |
| `pct_capped_neg_5` | % of LoB-level severities hitting −5.0 cap |
| `pct_floor_weight_1pct` | % of LoB weights floored at the 1% minimum |
| `by_year` | Per-year breakdown of all three rates |

### 9.7  Merge audit diagnostics

The `audit_merge()` function checks post-merge data quality:

| Check | Warning threshold |
|-------|:-:|
| `pct_missing_R_s` | > 10% |
| `pct_missing_w_s` | > 10% |
| `pct_missing_S_raw_a` | > 10% |
| `pct_missing_S_raw_b` | (reported) |
| `pct_missing_cause` | (reported) |

Also reports `R_s_source_dist` (distribution of reserve base sources) and
`weight_source_dist` (distribution of LoB weight sources).

---

## 10  Cause Classification

Each syndicate-year observation is classified into a cause category using keyword
matching against `primary_causes` and `standardized_narrative` fields:

| Category | Keywords |
|----------|----------|
| `natural_cat` | catastrophe, cat, hurricane, flood, earthquake, wildfire, storm, typhoon |
| `man_made` | man-made, explosion, fire, collision |
| `social_inflation` | social inflation, litigation, nuclear verdict |
| `economic_inflation` | economic inflation, claims cost, cost inflation |
| `covid` | covid, pandemic |
| `ogden` | ogden |
| `adverse_dev` | adverse, deterioration, prior year, strengthening |
| `large_loss` | large loss, large claim |
| `reinsurance` | reinsurance, recoveries |
| `court_rulings` | court, ruling, legal |
| `ibnr` | ibnr, incurred but not reported |
| `regulatory` | regulatory, regulation, solvency |
| `methodology` | methodology, reserving approach, assumption |
| `geopolitical` | geopolitical, sanctions, war |

The cause category is combined with the year to form an `event_id`
(`"{year}_{cause_category}"`) used for event fixed-effects grouping in the
size-coefficient estimation.

---

## 11  Diagnostics, Visualisations, and Statistical Tests

### 11.1  Novelty analysis framework

The exposure adjustment system is validated through five novelty analyses
(numbered N0–N4), each producing JSON results consumed by the IME paper
generator.

#### N0 — Sampling Robustness

Tests whether key metrics are stable under 10% leave-out resampling (200
iterations, DENSE subset):

| Metric tested | Description |
|---------------|-------------|
| `p95_slope` | 95th-percentile trend slope |
| `beta` | Size-severity elasticity $\hat{\beta}$ |
| `var995` | VaR 99.5% |

Each metric reports: point estimate, bootstrap standard deviation, coefficient
of variation (CV), and a stability flag (CV < threshold).

#### N1 — Tail Trend Analysis

Compares yearly 95th-percentile severity between raw and mix-standardised series:

- OLS trend regression on yearly p95 values
- Slope comparison: mix-standardisation should reduce (or eliminate) spurious
  trends caused by changing LoB composition over time
- Computed for DENSE and FULL subsets

#### N2 — Tail Stability

Assesses whether the severity tail is stable across time periods or exhibits
structural breaks.

#### N3 — Size Validation

Estimates the size-severity elasticity using multiple model specifications:

| Model | Specification | Purpose |
|-------|---------------|---------|
| **M0** | Simple OLS: $s_i = \alpha + \beta \ln R_i$ | Baseline (no controls) |
| **M1** | Event FE: $s_i = \alpha + \beta \ln R_i + \gamma_e$ | Controls for common events |
| **M2** | Event FE on $\log|S|$: $\log|s_i| = \alpha + \beta \ln R_i + \gamma_e$ | Log-scale severity |
| **M3** | Event FE on $\log S^2$: $\log s_i^2 = \alpha + \beta \ln R_i + \gamma_e$ | Variance-scale severity |

Also produces LoB-level $\beta$ estimates with raw values, standard errors,
James–Stein shrunk values, and shrinkage factors $\lambda_\ell$.

#### N4 — Capital Distortion

Quantifies the capital impact of omitting exposure adjustments, comparing four
severity distributions for each test portfolio:

| Distribution | Formula | Description |
|-------------|---------|-------------|
| $S_{\text{naive}}$ | Raw severity $S_{\text{raw-A}}$ | No adjustments |
| $S_{\text{mix}}$ | $\mathbf{w}^{(q)} \cdot \mathbf{s}_\ell$ | Mix-standardised only |
| $S_{\text{size}}$ | $S_{\text{raw-A}} \times (R^{(q)} / R_{\text{ref}})^{\bar{\beta}}$ | Size-adjusted only (overall $\beta$) |
| $S_{\text{mixsize}}$ | $(\mathbf{w}^{(q)} \cdot \mathbf{s}_\ell) \times (R^{(q)} / R_{\text{ref}})^{\beta_w}$ | Full adjustment |

VaR 99% and VaR 99.5% are computed for each distribution.

**Attribution effects:**
- Mix effect = $\text{VaR}(S_{\text{mix}}) - \text{VaR}(S_{\text{naive}})$
- Size effect = $\text{VaR}(S_{\text{mixsize}}) - \text{VaR}(S_{\text{mix}})$

### 11.2  Bootstrap confidence intervals

Cluster bootstrap (syndicate-level) is used for inference on VaR estimates:

1. Sample syndicates with replacement (preserving within-syndicate correlation)
2. Within each replicate, re-project all four severity distributions from
   $\mathbf{s}_\ell$ and $\mathbf{w}^{(q)}$
3. Compute VaR 99.5% and attribution effects per replicate
4. Report 2.5th and 97.5th percentiles as 95% confidence intervals

Default: $B = 500$ replicates, seed = 42.

### 11.3  Local-donor sensitivity analysis

Tests whether exposure adjustment results are driven by mix-dissimilar donors
by progressively restricting the donor pool using Hellinger distance:

**Hellinger distance between LoB weight vectors:**

$$
H(\mathbf{w}^{(s)}, \mathbf{w}^{(q)}) = \frac{1}{\sqrt{2}} \left\|\sqrt{\mathbf{w}^{(s)}} - \sqrt{\mathbf{w}^{(q)}}\right\|_2
$$

At each distance threshold $H_{\max} \in \{0.30, 0.40, \ldots, 1.0\}$:
- Retain only donors with $H \le H_{\max}$
- Compute VaR 99.5% for both raw and adjusted severity
- Report donor count at each threshold

**Key insight:** As the donor pool is restricted to mix-similar syndicates
(lower $H_{\max}$), the raw VaR should converge toward the adjusted VaR —
confirming that the adjustment correctly removes the LoB-mix distortion.

### 11.4  Test portfolios

All diagnostics are run on a grid of 6 test portfolios:

| Name | LoB mix | Size (£m) |
|------|---------|:---------:|
| Property-heavy small | Property 60%, Casualty 20%, Marine 10%, Prof Lines 10% | 200 |
| Property-heavy medium | (same mix) | 500 |
| Property-heavy large | (same mix) | 2,000 |
| Casualty-heavy small | Casualty 50%, Prof Lines 20%, Property 15%, Reins-Cas 15% | 200 |
| Casualty-heavy medium | (same mix) | 500 |
| Casualty-heavy large | (same mix) | 2,000 |

A market-average mix (volume-weighted from the DENSE subset) is also computed
dynamically for comparison.

---

## 12  IME Paper Outputs

The script `IME-paper-table-figures.py` reads the novelty analysis results and
the analysis table, and writes all outputs into the `IME/` subfolder.  All
figures are saved in both PDF and PNG format at 300 DPI.

### 12.1  Tables (LaTeX)

| Output file | Content | Data source |
|-------------|---------|-------------|
| `table1_corpus_summary.tex` | Corpus summary: years covered, total observations, unique syndicates, syndicates per year (dense vs sparse), balanced-panel count, partial-year 2024 count, median reserves, LoB categories | Analysis table |
| `table2_size_elasticity.tex` | Size-severity elasticity $\hat{\beta}$ across 5 model specifications (M0–M3 on DENSE + M1 on BALANCED_K8), with standard errors and p-values (significance stars) | N3 results |
| `table3_sampling_robustness.tex` | Sampling robustness under 10% leave-out: point estimate, bootstrap SD, CV%, stability verdict for p95 slope, $\beta$, and VaR 99.5% | N0 results |
| `table4_capital_distortion.tex` | Capital distortion: VaR 99% and VaR 99.5% for Raw/Mix-adjusted/Size-adjusted/Full adjustment across 6 portfolios, with 95% syndicate-cluster bootstrap CIs, plus mix and size attribution effects with CIs | N4 results + live bootstrap |
| `table5_local_donor_sensitivity.tex` | Local-donor sensitivity: VaR 99.5% (raw and adjusted) at each Hellinger-distance threshold ($H \le 0.40$ to $1.0$), with donor counts, for Property-heavy and Casualty-heavy at £500m | Live analysis |

### 12.2  Figures

| Output file | Content | Colour coding |
|-------------|---------|---------------|
| `figure1_tail_trend.{pdf,png}` | Raw vs mix-standardised 95th-percentile severity trend over time. Solid markers for dense years (2014–2019), hollow for extended years (2020+), dashed connection. OLS regression lines over dense range. Annotated with slope reduction percentage. | Blue (#2166ac) = raw, Red (#b2182b) = standardised |
| `figure2_mean_excess.{pdf,png}` | Mean Excess Function $E[S - u \mid S > u]$ for raw vs standardised severity (positive values only). Thresholds from 5th to 85th percentile, minimum 5 exceedances per threshold. | Blue = raw, Red = standardised |
| `figure3_size_severity.{pdf,png}` | Log-log scatter of reserve size vs absolute severity. Background scatter (grey, faint) with 15 quantile-binned means and IQR error bars. Fitted regression line from M1 (event FE) with $\hat{\beta}$ and p-value. | Blue bins, Red regression line |
| `figure4_capital_decomposition.{pdf,png}` | Stacked bar decomposition of Raw VaR 99.5% into: adjusted VaR (red base), size effect (green if credit, orange if penalty), mix effect removed (gold). One bar per portfolio (6 total). Annotated with adjusted VaR values and mix reduction in pp. Horizontal dashed line at Raw VaR level. | Red (#b2182b) = adjusted, Green (#4daf4a) = size credit, Orange (#ff7f0e) = size penalty, Gold (#ffd700) = mix effect |
| `figure5_lob_shrinkage.{pdf,png}` | Horizontal dot plot: raw LoB-level $\hat{\beta}_\ell$ with 95% CI error bars, shrunk $\tilde{\beta}_\ell$ (diamond markers), arrows showing shrinkage direction/magnitude. Annotated with $\lambda_\ell$ values. Grand mean reference line. | Blue = raw CI, Red = shrunk estimates |
| `figure6_local_donor.{pdf,png}` | Two-panel (Property-heavy, Casualty-heavy): raw vs adjusted VaR 99.5% as Hellinger threshold tightens ($x$-axis inverted). Three size markers (circle = £200m, square = £500m, diamond = £2bn). Donor-count annotations on £500m series. | Blue = raw VaR, Red = adjusted VaR |

### 12.3  Additional JSON output

| Output file | Content |
|-------------|---------|
| `local_donor_sensitivity.json` | Full results of local-donor analysis: thresholds, per-portfolio donor counts, raw and adjusted VaR 99%/99.5% at each threshold |

---

## 13  Progress Report Dashboard

The file `pdf_extraction/progress_report.html` is a browser-based real-time
monitoring dashboard for the PDF extraction pipeline (`test_gemini.py`).  It
uses the File System Access API to read JSON output files directly from disk
without a server.

### 13.1  Summary cards

| Card | Value | Description |
|------|-------|-------------|
| **Completed** | Count | Number of JSON files processed vs total PDFs |
| **Progress** | Percentage | Completion rate |
| **Elapsed Time** | HH:MM:SS | Span from first to latest extraction timestamp |
| **Est. Remaining** | HH:MM:SS | Based on average time per report |
| **Reliable Data** | Percentage | Active reliable reports as % of all completed (excludes run-off) |
| **Total Cost** | USD | Sum of `total_cost_usd` across all extraction JSONs |
| **Skipped** | Percentage | First-year / no-triangle reports as % of completed |
| **Excluded** | Percentage | Manually excluded reports as % of completed |

### 13.2  PYD statistics cards

| Card | Value |
|------|-------|
| **Mean PYD %** | Arithmetic mean with sign (+/−), coloured red (adverse) or green (favourable) |
| **Std Dev** | Standard deviation in percentage points, with min–max range |
| **99.5% Quantile** | 1-in-200 worst case, via linear interpolation |

### 13.3  Histograms

#### PYD % Distribution Histogram

- **Bin width**: 5 percentage points
- **Range**: extends from the minimum observed PYD% to 100%, snapped to bin boundaries
- **Overflow bin**: a single `> 100%` bin (purple) for extreme values
- **Colour coding**: red (#e74c3c) for strengthening bins ($\ge 0$%), green (#27ae60) for release bins ($< 0$%)
- **Display**: horizontal bar chart with counts per bin
- **Trimming**: empty bins at edges are trimmed (with 2-bin padding)

#### Complete Reports by Year

- Horizontal bar chart showing count of active reliable reports per year (excluding run-off and excluded)
- All years in the range are shown (including zeros) for a continuous timeline
- Green bars (#238636)

### 13.4  Box plots

The dashboard renders four canvas-based box plots showing the relationship
between PYD% and various portfolio characteristics.  All use identical visual
styling: blue boxes (#58a6ff fill, #1f6feb33 background), white median lines,
whiskers at $Q_1 - 1.5 \times \text{IQR}$ and $Q_3 + 1.5 \times \text{IQR}$,
and coloured outlier dots (red for positive, green for negative).  A dashed
zero line provides a visual reference.  Each box is annotated with its sample
count (`n=...`).  Minimum 10 data points required.

| Box plot | X-axis | Decile labels | Data requirement |
|----------|--------|---------------|------------------|
| **PYD % by Opening Reserves Decile** | Opening reserves (£m), 10 equal-count deciles | Range in £m (e.g. "52m–180m" or "1.2bn–3.4bn") | `openingReserves > 0` and `pydPct` both non-null |
| **PYD % by Premium HHI Decile** | Herfindahl–Hirschman Index (0 = diversified, 1 = monoline), 10 deciles | Range as decimals (e.g. "0.22–0.35") | `hhi` and `pydPct` both non-null |
| **PYD % by Complexity Score Decile** | Complexity $= R \times (1 - \text{HHI})$, 10 deciles | Range in raw units (e.g. "42–180" or "1.2k–3.4k") | `complexity` and `pydPct` both non-null |
| **PYD % by Report Year** | Calendar year (one box per year, not decile-based) | Year labels (e.g. "2014", "2015") | Year and `pydPct` both non-null, minimum 2 years |

All four box plots use symmetric Y-axis limits ($\pm y_{\text{max}} \times 1.15$
where $y_{\text{max}}$ is the largest absolute whisker or outlier value).

**HHI computation** (in JavaScript, from `gross_premium_mix`):

$$
\text{HHI} = \sum_\ell \left(\frac{p_\ell}{\sum_{\ell'} p_{\ell'}}\right)^2
$$

where $p_\ell$ is the `percentage_of_total` for each LoB in the premium mix.

**Complexity computation**: $\text{Complexity} = R \times (1 - \text{HHI})$
where $R$ is `opening_reserves_gbp_m`.

---

## 14  Data Quality Column Tags in progress_report.html

The **Data Quality** column in the completed reports table classifies each
extraction JSON file from `pdf_extraction/syndicate_NNNN_YYYY.json` into one
of five mutually exclusive tags:

### 14.1  Classification rules

```
For each JSON file in pdf_extraction/:

1. Is the file manually excluded?
   (data.excluded === true AND
    (data.manual_override_status === 'excluded' OR data.models exists))
   → Tag: EXCLUDED

2. Is the file skipped (no models)?
   (NOT excluded AND data.models absent AND
    (data.first_year_syndicate OR data.reason OR data.no_triangle_data))
   → Tag: SKIPPED

3. Otherwise, the file has models (extractedCount++). Check reliability:

   a. hasReliablePyd = (prior_year_development_pct !== null)
      [resolved across all model outputs — first non-null wins]

   b. hasReliablePremium = (gross_premium_mix.length > 0 AND
                            gross_premiums_written_gbp_m > 0)

   c. isRunoff = (hasReliablePyd AND NOT hasReliablePremium AND
                  gross_premiums_written_gbp_m === 0)

   d. isReliable = (hasReliablePyd AND (hasReliablePremium OR isRunoff))

   Result:
   - If isRunoff → Tag: IN RUNOFF
   - If isReliable → Tag: RELIABLE
   - Otherwise → Tag: INCOMPLETE
```

### 14.2  Tag definitions

| Tag | Badge CSS class | Colour | Meaning |
|-----|----------------|--------|---------|
| **Reliable** | `.badge.reliable` | Green | PYD% extracted successfully AND either (a) premium mix with GPW > 0 available, or (b) syndicate is in run-off with GPW = 0. Full data available for downstream analysis. |
| **In Runoff** | `.badge.runoff` | Blue | PYD% available but GPW = 0 and no premium mix — run-off syndicate with no new business but valid reserve development data. Counted separately from active reliable reports. |
| **Incomplete** | `.badge.unreliable` | Red | Models were extracted but either PYD% is missing or premium mix is incomplete. May lack key fields for downstream analysis. |
| **Skipped** | `.badge.skipped` | Yellow | No LLM extraction was performed. Reasons: first/second-year syndicate (< 3 UW years), no claims development triangle found, no reserve movement text found. Minimal audit JSON written. |
| **Excluded** | `.badge.excluded` | Purple | Manually excluded from analysis via `manual_override_status: 'excluded'`, or post-extraction exclusion (`excluded: true` with models present). Reason recorded in `manual_override_reason` or `exclusion_reason`. |

### 14.3  Additional row annotations

| Annotation | Badge CSS class | Condition | Meaning |
|------------|----------------|-----------|---------|
| **1st yr UW** | `.badge.uw1` | `report_year - inception_year === 0` | Syndicate's first underwriting year report — no prior year development possible |
| **2nd yr UW** | `.badge.uw2` | `report_year - inception_year === 1` | Syndicate's second underwriting year report — limited prior year development |

Inception years are loaded from `syndicate_inception_years.json` in the output
directory.

### 14.4  Validation column

| Badge | Condition | Meaning |
|-------|-----------|---------|
| **Pass** | `validation.passed === true` | Dual-LLM cross-validation passed (all discrepancies within tolerance) |
| **Fail (N)** | `validation.passed === false` | N hard failures in cross-validation (fields outside tolerance) |
| **N/A** | Skipped or excluded | No validation performed |

### 14.5  Reliable Data % computation

The "Reliable Data" card percentage is computed as:

$$
\text{Reliable\%} = \frac{\text{reliableCount} - \text{runoffCount}}{\text{totalCompleted}} \times 100
$$

Run-off syndicates are counted as reliable but excluded from the "active
reliable" metric, so the denominator is all completed reports (including
skipped and excluded).

---

## 15  Data Flow Summary

```
                          HISTORICAL CORPUS
                          ─────────────────
                          Syndicate annual reports
                                   │
                    ┌──────────────┼──────────────┐
                    ▼              ▼              ▼
              LoB Weights     Reserve Base    Movements
              (Segmental      (Balance        (PYD by LoB)
               Analysis)       Sheet)
                    │              │              │
                    └──────┬───────┘              │
                           ▼                      │
                    R_ℓ = R · w_ℓ                 │
                           │                      │
                           └──────────┬───────────┘
                                      ▼
                              s_ℓ = M_ℓ / R_ℓ
                           LoB-level severity
                                      │
                    ┌─────────────────┼─────────────────┐
                    ▼                                    ▼
           HIERARCHICAL MATCHING               SIZE COEFFICIENT
           (same-year components)               ESTIMATION
                    │                           (event-FE + shrinkage)
                    │                                    │
                    ▼                                    ▼
        S_raw = Σ w_ℓ^(q) · s_ℓ              β_weighted = Σ w_ℓ^(q) · β_ℓ
                    │                                    │
                    └──────────────┬─────────────────────┘
                                   ▼
                    S_adj = S_raw · (R^(q) / R_ref)^β_weighted
                                   │
                                   ▼
                          SCENARIO LIBRARY
                     (severity distribution +
                      causal narratives)
```

---

## 16  Key Source Files

| File | Role |
|------|------|
| `scripts/stress_test/config.py` | Standard LoB categories (`LLOYDS_LOBS`, `LOB_TO_INDEX`), cause classifications |
| `scripts/stress_test/extract_lob_weights.py` | Extracts LoB weights from syndicate annual reports |
| `scripts/stress_test/data_preparation.py` | Computes severity ratios, portfolio profiles, HHI, complexity scores |
| `scripts/stress_test/portfolio_size_adjustment.py` | `PortfolioSizeAdjuster` class: fits and applies the size-adjustment power-law model, default coefficients |
| `scripts/stress_test/portfolio_query_hierarchical.py` | Query engine: hierarchical matching, LoB standardisation, size adjustment |
| `scripts/stress_test/novelty/common/severity_projection.py` | Pure-math functions: `project_severity()`, `composite_beta()`, `size_adjustment_factor()`, `adjusted_severity()`, `cap_severity()` |
| `scripts/stress_test/novelty/common/analysis_table.py` | `build_analysis_table()`, `add_query_columns()`, `get_subset()`, `compute_cap_binding_stats()`, `audit_merge()` |
| `scripts/stress_test/novelty/common/query_portfolios.py` | Test portfolio definitions (`PROPERTY_HEAVY`, `CASUALTY_HEAVY`, `SIZES_M`), `compute_market_average_mix()` |
| `IME-paper-table-figures.py` | Generates LaTeX tables (5) and figures (6) for the IME paper into `IME/` |
| `pdf_extraction/progress_report.html` | Real-time extraction monitoring dashboard with data quality tags |
| `lob_weights.json` | Pre-extracted LoB weights by syndicate-year |
| `size_metrics.json` | Reserve and capacity metrics by syndicate-year |
