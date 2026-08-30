# Data Construction

> **Status: historical.**
> This describes the earlier 621-report / 435-accepted quality-classifier corpus and a
> single-model GPT-4o standardisation. The current pipeline retrieves 1,065 filings and
> uses a dual-model design (`gemini-2.5-flash` and `gpt-5-mini`) with deterministic
> table extraction taking precedence. See `README.md` and `docs/data-audit-results.md`
> for the current construction, and the manuscript for the modelling corpus.


This document specifies exactly how the analysis table is built from
the unified corpus, LoB weight extractions, and size metrics.  Every
decision rule is stated once; the code references point to
`scripts/stress_test/novelty/common/analysis_table.py` unless noted
otherwise.

---

## 0  Upstream extraction pipeline

### 0.1  Report collection and screening

The corpus was built in two stages:

1. **Candidate collection.**  Annual syndicate reports (SFCRs and
   Annual Reports to Members) for 2014--2024 were downloaded from
   Lloyd's public filings.  621 reports were successfully retrieved
   across approximately 80 syndicates.

2. **Quality screening.**  Each report was classified by an automated
   quality classifier (`scripts/quality_classifier.py`) into four
   tiers based on the depth of reserve commentary:

   | Tier       | Criteria                                      | Count | Share |
   |------------|-----------------------------------------------|------:|------:|
   | VERY\_HIGH | LoB breakdown + specific causal descriptions  |   416 |  67%  |
   | HIGH       | LoB breakdown, generic causality              |    19 |   3%  |
   | MEDIUM     | Some reserve commentary, no LoB breakdown     |   166 |  27%  |
   | LOW        | Minimal or boilerplate commentary              |    19 |   3%  |
   | ERROR      | Extraction failed                             |     1 |  <1%  |

   **Accepted for LoB extraction:** VERY\_HIGH and HIGH (435 reports,
   70% acceptance rate).

   **Screened out:** MEDIUM, LOW, and ERROR (186 reports, 30%).
   These reports were retained in the screening log
   (`docs/validation/rejection_log.xlsx`) with rejection reasons
   but did not contribute LoB-level data to the corpus.

   The 30% rejection rate reflects application of a structured
   screening protocol.  The most common rejection reasons are:

   | Reason                          | Count | Share of rejected |
   |---------------------------------|------:|------------------:|
   | Insufficient reserve disclosure |   146 |  78%              |
   | Missing LoB breakdown           |    39 |  21%              |
   | Extraction failure              |     1 |   1%              |

   The full rejection log with per-report reasons is in
   `docs/validation/rejection_log.xlsx`.

### 0.2  Text extraction

Three extraction methods are attempted in priority order:

1. **PyMuPDF** (primary): structured text extraction from native PDFs.
2. **pdfplumber** (fallback): used when PyMuPDF yields insufficient
   text (< 500 characters of reserve section content).
3. **OCR** (pytesseract + pdf2image): used for scanned PDFs where
   both text extractors fail.

The method actually used is recorded in `extraction_method` per report.

### 0.3  ChatGPT standardisation

Reserve movements were standardised using GPT-4o
(`scripts/syndicate_summarizer.py`).  For each accepted report, the
LLM receives the extracted reserve section text and produces a
structured JSON record per LoB with:

- **Direction**: `release` (favourable), `strengthening` (adverse),
  `flat`, or `mixed`.
- **Amounts**: GBP millions where disclosed.
- **Causes**: mapped to a standard taxonomy of 20 cause categories
  (e.g.\ "Social inflation / litigation trends",
  "Natural catastrophe events", "IBNR recalibration").
- **Confidence**: `high`, `medium`, or `low` (LLM self-assessed).

The standardisation prompt enforces consistent naming of LoBs and
cause categories.  The full prompt text is in the source file.

**Corpus confidence distribution** (827 movements):

| Confidence | Count | Share |
|------------|------:|------:|
| high       |   773 |  93%  |
| low        |    37 |   5%  |
| medium     |    17 |   2%  |

### 0.4  LoB weight extraction

LoB weights are extracted separately from report tables
(`scripts/stress_test/extract_lob_weights.py`) by parsing GWP, NEP,
reserve, or capacity breakdown tables.

**Weight source priority:**

| Priority | Source           | Field in output    |
|----------|------------------|--------------------|
| 1        | GWP tables       | `weights_by_gwp`   |
| 2        | NEP tables       | `weights_by_nep`   |
| 3        | Reserve tables   | `weights_by_reserves` |
| 4        | Capacity tables  | `weights_by_capacity` |

The selected source is recorded in `weight_source`.

**Extraction confidence** is determined by whether extracted weights
sum to approximately 1.0:

| Confidence | Rule                        | Count | Share |
|------------|-----------------------------|------:|------:|
| high       | $0.95 \leq \sum w \leq 1.05$ |   423 |  73%  |
| low        | sum outside range, or no weights |   158 |  27%  |

Low-confidence extractions are **not excluded**.  They enter the
analysis table with `extraction_confidence = "low"` in the quality
flags and contribute to analyses where their data is non-null.  This
is a deliberate design choice: excluding low-confidence rows would
reduce sample size without clear evidence that the weights are wrong
(many low-confidence cases arise from rounding in source tables
rather than extraction errors).

**Weight source distribution** (581 syndicate-years):

| Source | Count | Share |
|--------|------:|------:|
| GWP    |   442 |  76%  |
| none   |   139 |  24%  |

### 0.5  Known error types

The extraction pipeline is subject to the following error categories:

| Error type                 | Description                                             | Mitigation                       |
|----------------------------|---------------------------------------------------------|----------------------------------|
| Field omission             | A disclosed field was not captured by the LLM           | Audit sample + confidence flags  |
| Reserve-base mismatch      | Wrong reserve figure used as denominator                | Four-level cascade + `R_s_source` audit |
| LoB mapping error          | Syndicate LoB name mapped to wrong canonical LoB        | 13-element canonical basis + manual spot checks |
| Transcription/numeric error| Amount transcribed incorrectly from PDF                 | Content hash + SHA-256 audit trail |
| Ambiguous disclosure       | Report language unclear on direction or amount          | LLM confidence flag + cap/floor rules |

### 0.6  Retrospective validation

A stratified sample validation is documented separately.  The
validation script (`scripts/stress_test/create_validation_sample.py`)
draws a stratified sample from the frozen corpus, outputs an Excel
workbook for manual audit, and computes error rates.  See Section 9.

---

## 1  Unit of observation

Each row is a **syndicate-year** pair `(syndicate_id, year)`.  When
the corpus contains multiple LoB-level movement records for the same
syndicate-year they are merged into a single row.  The LoB detail is
preserved in vector columns (`w_s_array`, `s_lob`, `lob_present_mask`)
rather than as separate rows.

A syndicate-year enters the table if at least one movement record
exists in the unified corpus for that pair.  No imputation is
performed for syndicate-years with no corpus entry.

---

## 2  Signed severity (reserve deterioration)

Two aggregate severity measures are computed for every row.

### Raw-A: total-movement ratio

$$
S_{\text{raw},A} \;=\; \frac{M_{\text{total}}}{R_s}
$$

where $M_{\text{total}} = \sum_\ell \text{signed}(\text{amount}_\ell)$ across
all LoB records in the syndicate-year.

Sign convention:

| Direction      | Sign of amount |
|----------------|----------------|
| Strengthening  | $+|a|$         |
| Release        | $-|a|$         |

If a precomputed `severity_ratio` field exists in the corpus record it
takes priority over the amount-based calculation.

### Raw-B: LoB-weighted severity

$$
S_{\text{raw},B} \;=\; \mathbf{w}_s \cdot \mathbf{s}_{\text{lob}}
  \;=\; \sum_{\ell=1}^{13} w_{s,\ell}\, s_\ell
$$

where $\mathbf{w}_s$ is the syndicate's LoB weight vector and
$\mathbf{s}_{\text{lob}}$ is the per-LoB severity vector (Section 5).

Raw-B is only defined when both $\mathbf{w}_s$ and at least one
non-zero $s_\ell$ are available.

### Reserve base $R_s$

$R_s$ is determined by a four-level priority cascade:

| Priority | Field                         | Source           |
|----------|-------------------------------|------------------|
| 1        | `prior_reserves_gbp_m`        | Unified corpus   |
| 2        | `technical_provisions_gbp_m`  | size\_metrics    |
| 3        | `claims_outstanding_gbp_m`    | size\_metrics    |
| 4        | `stamp_capacity_gbp_m`        | Corpus or size\_metrics |

The field that was actually used is recorded in `R_s_source` for audit.

---

## 3  Event definition (event fixed effects)

An **event** is the combination of calendar year and cause category:

```
event_id = f"{year}_{cause_category}"
```

Cause categories are assigned by keyword matching against
`primary_causes` and `standardized_narrative` fields.  The keyword
dictionary defines 14 categories:

| Category           | Example keywords                              |
|--------------------|-----------------------------------------------|
| natural\_cat       | catastrophe, hurricane, flood, earthquake     |
| man\_made          | explosion, fire, collision                    |
| social\_inflation  | social inflation, litigation, nuclear verdict |
| economic\_inflation| economic inflation, claims cost               |
| covid              | covid, pandemic                               |
| ogden              | ogden                                         |
| adverse\_dev       | adverse, deterioration, strengthening         |
| large\_loss        | large loss, large claim                       |
| reinsurance        | reinsurance, recoveries                       |
| court\_rulings     | court, ruling, legal                          |
| ibnr               | ibnr, incurred but not reported               |
| regulatory         | regulatory, regulation, solvency              |
| methodology        | methodology, reserving approach               |
| geopolitical       | geopolitical, sanctions, war                  |

Keywords are matched case-insensitively.  The first matching category
wins.  Syndicate-years matching no keyword receive `cause_category =
"other"`.

The event-FE models (Novelty 3) absorb `event_id` as a factor,
removing year-level shocks that hit all syndicates simultaneously
(e.g.\ Hurricane Irma in 2017).

---

## 4  LoB weight attribution

### Source priority

| Priority | Source                | Variable          |
|----------|-----------------------|-------------------|
| 1        | Extracted from report | `best_weights`    |
| 2        | Movement amounts      | `movement_amounts`|
| 3        | None available        | `none`            |

**Priority 1** uses the `best_weights` field from `lob_weights.json`,
which is extracted by the quality classifier from each syndicate
report's LoB breakdown tables.

**Priority 2** falls back to normalising by absolute movement amounts
when no extracted weights exist:

$$
w_{s,\ell} = \frac{|a_\ell|}{\sum_k |a_k|}
$$

In both cases the weight vector is normalised to sum to 1.

### Incomplete disclosures

When a syndicate discloses movements for only a subset of its LoBs,
the undisclosed LoBs receive $s_\ell = 0$ (no movement assumed) and
retain whatever weight the extraction or fallback produced.  The
`lob_present_mask` boolean vector records which LoBs had explicit
movement data.

---

## 5  Segmentation changes

Syndicates occasionally change their LoB segmentation between years
(e.g.\ splitting "Casualty" into "Casualty" and "Professional
Lines").  No attempt is made to retrospectively harmonise
segmentations.  Each year's weight vector $\mathbf{w}_s$ and severity
vector $\mathbf{s}_{\text{lob}}$ reflect that year's disclosed
structure.

The 13-element canonical LoB vector (from `config.py: LLOYDS_LOBS`)
serves as the common basis.  Extracted weights are mapped to this
basis; LoBs not mentioned receive weight zero.  If a syndicate
reports a coarser grouping (e.g.\ "Reinsurance" without the
Property/Casualty/Specialty split), the full amount is attributed to
the best-matching canonical LoB.

Because the standardised severity $S_{\text{std}} = \mathbf{w}_q
\cdot \mathbf{s}_{\text{lob}}$ is a dot product against a fixed query
portfolio $\mathbf{w}_q$, changes in the syndicate's own weight
vector do not directly affect the standardised measure---only the
per-LoB severity values $s_\ell$ matter.

---

## 6  Flooring rule for near-zero exposures

When computing per-LoB severity, the syndicate's LoB weight is floored
at 1%:

$$
s_\ell = \frac{\text{signed\_amount}_\ell}{R_s \times \max(w_{s,\ell},\; 0.01)}
$$

**Rationale.**  Without the floor, a syndicate disclosing a small
movement in an LoB with near-zero extracted weight (e.g.\
$w_{s,\ell} = 0.001$) would produce an implausibly large severity
ratio.  The 1% floor caps the denominator deflation, ensuring that
LoB reserves are at least $0.01 \times R_s$.

The `pct_floor_weight_1pct` diagnostic reports the fraction of
LoB-level entries where the floor was binding
($0 < w_{s,\ell} < 0.011$).  Typical rates are 2--5% of LoB entries.

---

## 7  Cap rule for extreme LoB severities

After computing the raw LoB severity, values are clipped symmetrically:

$$
s_\ell \leftarrow \text{clip}(s_\ell,\; -5.0,\; +5.0)
$$

A severity of $\pm 5.0$ means the LoB movement was five times the
estimated LoB reserves---almost certainly a data artefact from weight
misestimation rather than a genuine signal.

**Diagnostics.**  When $|s_\ell| \geq 5.0$ the uncapped value is
recorded in the `cap_binding` dictionary.  The overall binding rates
(`pct_capped_pos_5`, `pct_capped_neg_5`) are reported per year and
aggregated.  Typical rates are 0.1--0.6% of LoB entries, confirming
the cap rarely binds.

When a syndicate has multiple movement records for the same LoB within
a year, the record with the largest $|\text{capped severity}|$ is
retained.

---

## 8  Quality flags and inclusion/exclusion

Each row carries a `data_quality_flags` dictionary:

| Flag                    | Values                                        | Meaning                        |
|-------------------------|-----------------------------------------------|--------------------------------|
| `weight_source`         | `best_weights`, `movement_amounts`, `none`    | How LoB weights were obtained  |
| `extraction_confidence` | `high`, `medium`, `low`, `none`               | Classifier's self-assessed confidence |
| `R_s_source`            | `prior_reserves_gbp_m`, `technical_provisions_gbp_m`, etc. | Which reserve base was used    |

### Inclusion rules

A syndicate-year enters the analysis table if:

1. At least one movement record exists in the unified corpus.
2. At least one of $R_s$ or movement amount is non-null.

Quality-tier screening is applied upstream (Section 0.1): only
VERY\_HIGH and HIGH reports enter the unified corpus.  MEDIUM, LOW,
and ERROR reports are excluded at the extraction stage and therefore
have no movement records in the corpus.  No additional quality-tier
filter is applied at the analysis-table stage.

### Effective exclusion via missingness

Rows with $R_s = \text{NaN}$ have $S_{\text{raw},A} = \text{NaN}$ and
are excluded from analyses that require finite severity.  Rows with
`weight_source = "none"` have $S_{\text{raw},B} = \text{NaN}$ and are
excluded from LoB-weighted analyses.

The `n_valid` field in each novelty analysis output reports how many
rows survived after dropping NaN values for the relevant severity
column.

---

## 9  Retrospective validation protocol

### 9.1  Frozen dataset

The dataset used in this paper is frozen as
`docs/validation/syndicate_corpus_v1.0.csv`.  The file header records:

- Row count, number of unique syndicates, year range
- SHA-256 hash of the file contents
- Generation timestamp

The frozen file is produced by
`scripts/stress_test/create_validation_sample.py --freeze`.

### 9.2  Validation sample

A stratified random sample of 50 syndicate-year rows is drawn for
manual audit.  Stratification ensures coverage across:

- **Year bands**: early (2014--2016), middle (2017--2019), late
  (2020--2024)
- **Reserve size**: small ($R_s < 200$m), medium (200--800m),
  large ($> 800$m)
- **High deterioration**: top decile of $|S_{\text{raw},A}|$
- **Unusual LoB mix**: top decile of LoB weight entropy

The sample includes 10 screened-out (MEDIUM/LOW) reports so the
validator can confirm rejection decisions.

### 9.3  Validation sheet

The output workbook (`docs/validation/validation_sample.xlsx`)
contains columns:

| Column | Description |
|--------|-------------|
| `row_id` | Frozen-file row index |
| `syndicate` | Syndicate number |
| `year` | Report year |
| `quality_tier` | VERY\_HIGH / HIGH / MEDIUM / LOW |
| `source_document` | PDF filename |
| `source_page` | Page reference (if available) |
| `extracted_reserve` | $R_s$ as extracted |
| `validated_reserve` | Manual check value |
| `extracted_deterioration` | $S_{\text{raw},A}$ as extracted |
| `validated_deterioration` | Manual check value |
| `extracted_lob` | LoB weights as extracted |
| `validated_lob` | Manual check weights |
| `error_type` | From taxonomy below, or blank |
| `material_error_yn` | Y/N |
| `notes` | Free text |

### 9.4  Error taxonomy

| Code | Error type                | Definition |
|------|---------------------------|------------|
| FO   | Field omission            | A disclosed field was not captured |
| RB   | Reserve-base mismatch     | Wrong reserve figure used as $R_s$ |
| LM   | LoB mapping error         | Syndicate LoB mapped to wrong canonical LoB |
| TE   | Transcription/numeric     | Amount incorrectly transcribed from source |
| AD   | Ambiguous disclosure      | Source language genuinely unclear |

### 9.5  Error rate reporting

After manual audit, compute:

- **Field-level error rate**: fraction of checked fields with any
  error (FO, RB, LM, TE, or AD).
- **Material error rate**: fraction of rows where the error changes
  the sign or magnitude of $S_{\text{raw},A}$ by $> 20\%$.
- **Breakdown by error type**: counts per taxonomy code.

These rates are reported in the paper's data-quality appendix.
