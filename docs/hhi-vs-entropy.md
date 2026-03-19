# HHI vs Entropy for LoB Diversification Measurement

This document records the rationale for using the Herfindahl-Hirschman Index
(HHI) rather than Shannon entropy as the concentration measure in the portfolio
complexity score.

---

## 1  Definitions

Given a portfolio with LoB weight vector $\mathbf{w} = (w_1, \ldots, w_n)$
where $\sum_i w_i = 1$:

| Measure | Formula | Range |
|---------|---------|-------|
| **HHI** | $\text{HHI} = \sum_i w_i^2$ | $[1/n,\; 1]$ |
| **Shannon entropy** | $H = -\sum_i w_i \ln w_i$ | $[0,\; \ln n]$ |

Both are maximally concentrated for a monoline portfolio ($w_1 = 1$) and
maximally diversified for an equal-weight portfolio ($w_i = 1/n$), but with
opposite orientation: HHI increases with concentration while entropy increases
with diversification.

---

## 2  Sensitivity Comparison

The key behavioural difference is how each measure responds to rebalancing among
small allocations versus large ones.

| Portfolio | Weights | HHI | 1 - HHI | Entropy | $H / \ln 4$ |
|-----------|---------|:---:|:-------:|:-------:|:--------:|
| A (concentrated) | (70%, 10%, 10%, 10%) | 0.52 | 0.48 | 1.01 | 0.73 |
| B (moderate) | (40%, 30%, 20%, 10%) | 0.30 | 0.70 | 1.28 | 0.92 |
| C (equal) | (25%, 25%, 25%, 25%) | 0.25 | 0.75 | 1.39 | 1.00 |

**HHI** is quadratic in the weights, so it is dominated by the largest
allocation.  Redistributing weight among small LoB tails barely moves HHI.

**Entropy** is logarithmic, giving proportionally more credit to splitting small
allocations.  Moving from B to C (spreading 10% more evenly) shifts normalised
entropy from 0.92 to 1.00, an 8% change.  HHI moves only from 0.70 to 0.75
(7%).

The gap widens for portfolios with many small LoB exposures: entropy treats a
1% allocation to 5 LOBs very differently from 5% to 1 LoB, while HHI is nearly
indifferent to either.

---

## 3  Why HHI is Preferred for Reserve Risk

### 3.1  Reserve risk is dominated by large exposures

In Lloyd's reserve development, the dominant LoB drives the vast majority of
prior-year development.  A syndicate writing 70% Property and 30% across three
other lines behaves essentially like a near-monoline Property book for reserve
stress purposes.  HHI's quadratic weighting naturally captures this: it assigns
a concentration score of 0.52 to portfolio A above, correctly reflecting that
70% of the reserve risk sits in one line.

Entropy would assign A a normalised score of 0.73 (out of 1.0), suggesting
meaningful diversification exists despite the heavy concentration -- an
overstatement for reserve risk purposes.

### 3.2  Entropy overweights tail diversification

Splitting 10% of reserves across 3 LOBs versus 2 LOBs changes the entropy
measurably but does not materially reduce reserve deterioration risk.  Small LoB
allocations contribute noise rather than genuine diversification benefit to
reserve outcomes.  HHI is nearly insensitive to such rearrangements, which is
the correct behaviour.

### 3.3  HHI has a direct actuarial interpretation

HHI equals the probability that two randomly selected pounds of reserve come
from the same LoB.  This maps naturally to correlated reserve deterioration: when
HHI is high, a single-LoB reserve shock affects most of the portfolio.

Entropy's information-theoretic interpretation (average surprise per LoB
observation) lacks a direct connection to reserve risk mechanics.

### 3.4  Complexity score interaction

The complexity score is defined as:

$$
\text{Complexity} = R \times (1 - \text{HHI})
$$

This has clean boundary behaviour:

- **Monoline** ($\text{HHI} = 1$): Complexity $= 0$ regardless of size.
  A pure Property book at any size has zero structural diversification.
- **Equal-weight** ($\text{HHI} = 1/n$): Complexity $\approx R$, scaling
  linearly with reserves.

An entropy-based equivalent would be $R \times H / \ln n$, which is well-defined
but produces a less intuitive scale: a monoline portfolio maps to 0 (correct),
but the transition from concentrated to diversified is logarithmically compressed,
understating the jump in diversification benefit that occurs when a dominant LoB
drops below ~50%.

---

## 4  When Entropy Might Be Preferred

Entropy would be the better choice if:

1. **Many small LoB exposures create meaningful diversification** even when one
   LoB dominates.  This is plausible for premium risk (where frequency
   diversification matters) but less so for reserve risk (where severity
   correlation dominates).

2. **The analysis is information-theoretic** -- e.g., measuring the
   predictability or information content of a portfolio's LoB structure rather
   than its risk concentration.

3. **All LoB exposures are of similar magnitude** -- in this regime HHI and
   entropy are nearly monotonically related and the choice is immaterial.

---

## 5  Decision

**HHI is used throughout the pipeline** for LoB concentration and complexity
scoring.  The rationale is:

- Reserve risk at Lloyd's is empirically dominated by the largest 1-2 LoB
  exposures, not by tail diversification across many small lines.
- HHI's quadratic sensitivity correctly weights large concentrations.
- The complexity score $R \times (1 - \text{HHI})$ has clean, interpretable
  boundary behaviour.
- HHI's probabilistic interpretation (same-LoB collision probability) connects
  directly to correlated reserve deterioration.

This choice is implemented in:

- `scripts/stress_test/data_preparation.py` -- historical complexity scoring
- `scripts/stress_test/config.py` -- complexity bin definitions
- `scripts/stress_test/novelty/common/analysis_table.py` -- HHI column
- `pdf_extraction/progress_report.html` -- dashboard box plots
