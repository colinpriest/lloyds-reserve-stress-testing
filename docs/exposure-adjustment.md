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

### 2.2  LoB-level severity

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

If no amounts are available either, equal weights are assigned across the
observed LoB set.

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
scoring.

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

## 9  Data Flow Summary

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

## 10  Key Source Files

| File | Role |
|------|------|
| `scripts/stress_test/config.py` | Standard LoB categories, cause classifications |
| `scripts/stress_test/extract_lob_weights.py` | Extracts LoB weights from syndicate annual reports |
| `scripts/stress_test/data_preparation.py` | Computes severity ratios, portfolio profiles, HHI |
| `scripts/stress_test/portfolio_size_adjustment.py` | Fits and applies the size-adjustment power-law model |
| `scripts/stress_test/portfolio_query_hierarchical.py` | Query engine: hierarchical matching, LoB standardisation, size adjustment |
| `lob_weights.json` | Pre-extracted LoB weights by syndicate-year |
| `size_metrics.json` | Reserve and capacity metrics by syndicate-year |
