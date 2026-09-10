# Extraction change log

> **Generated file — do not edit.** Written by `scripts/extraction_changelog.py` by comparing every committed record with the same record at commit `7334497`.

Round 55 (the external review of 10 September 2026) corrected two extraction rules and re-extracted the records they touch, offline from the committed response and table caches. The rules were: the percentage-against-monetary decision, which now rests on the table's own unit evidence before any magnitude heuristic (finding T03); and the transposed-grid parser, which now captures one basis block of a page that prints a gross and a net triangle under one header, and labels it by that block's own heading. The route by which each record's development figure was adopted is now recorded on the record (`_pyd_route`) instead of being inferred from a sentence in its notes.

**53 record(s) differ from `7334497`.** The adopted figure moves in 21 of them.

| Record | Development, before | after | Route, before | after | Fields that differ |
|---|---:|---:|---|---|---|
| `syndicate_1209_2015` | -37.6 | -37.6 | model | model | rag_triangle, data_quality_notes |
| `syndicate_1218_2018` | -22.744 | -22.744 | model | rag_triangle (gross) | rag_triangle |
| `syndicate_1218_2020` | 21.936 | 21.936 | model | rag_triangle (gross) | rag_triangle |
| `syndicate_1301_2015` | -13.6 | -5.8 | model | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, rag_triangle, data_quality_notes |
| `syndicate_1301_2017` | 77.1 | 7.6 | model | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, rag_triangle, data_quality_notes |
| `syndicate_1416_2023` | 2.065 | 2.065 | deterministic override (note) | rag_triangle (gross) | rag_triangle |
| `syndicate_1458_2015` | -1.113 | -1.113 | deterministic override (note) | rag_triangle (gross) | rag_triangle |
| `syndicate_1458_2016` | -3.834 | -3.834 | deterministic override (note) | rag_triangle (gross) | rag_triangle |
| `syndicate_1729_2018` | 5.443 | 5.443 | model | rag_triangle (gross) | rag_triangle |
| `syndicate_1729_2021` | 3.217 | 3.217 | model | rag_triangle (gross) | rag_triangle |
| `syndicate_1880_2019` | 20.9 | 20.9 | model | rag_triangle (gross) | rag_triangle |
| `syndicate_1880_2020` | 1.7 | 0.4 | model | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, rag_triangle |
| `syndicate_1880_2021` | None | -24.8 | model | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, opening_reserves_gbp_m, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes, currency, direction |
| `syndicate_1880_2022` | -53.1 | -19.7 | deterministic override (note) | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, rag_triangle, data_quality_notes |
| `syndicate_1880_2023` | 20.2 | 18.0 | deterministic override (note) | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, rag_triangle, data_quality_notes |
| `syndicate_1945_2019` | 3.856 | 3.856 | deterministic override (note) | rag_triangle (gross) | rag_triangle |
| `syndicate_1945_2020` | -36.1 | -36.1 | model | rag_triangle (gross) | rag_triangle |
| `syndicate_1945_2022` | -13.831 | -13.831 | deterministic override (note) | rag_triangle (gross) | rag_triangle |
| `syndicate_1969_2016` | 2.3 | 13.5 | deterministic override (note) | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, rag_triangle, data_quality_notes |
| `syndicate_2689_2020` | 11.224 | 11.224 | model | rag_triangle (gross) | rag_triangle |
| `syndicate_3002_2018` | 3.332 | 3.332 | deterministic override (note) | rag_triangle (gross) | rag_triangle |
| `syndicate_308_2015` | -0.3 | -0.3 | model | model | rag_triangle |
| `syndicate_308_2016` | -0.8 | -0.8 | model | model | rag_triangle, data_quality_notes |
| `syndicate_308_2017` | 0.8 | 2.4 | model | deterministic override (note) | prior_year_development_gbp_m, prior_year_development_pct, data_quality_notes |
| `syndicate_308_2018` | -1.6 | -1.6 | model | model | provenance only |
| `syndicate_318_2015` | -13.978 | -13.978 | deterministic override (note) | deterministic override (note) | rag_triangle, data_quality_notes |
| `syndicate_318_2017` | -13.025 | -13.025 | deterministic override (note) | deterministic override (note) | rag_triangle, data_quality_notes |
| `syndicate_3330_2017` | -0.99 | -0.99 | model | rag_triangle (gross) | rag_triangle |
| `syndicate_3622_2023` | -1.2857 | -4.8 | model | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, rag_triangle, data_quality_notes |
| `syndicate_4242_2015` | -1.342 | -1.342 | deterministic override (note) | rag_triangle (gross) | rag_triangle |
| `syndicate_4747_2022` | 2.343 | 2.343 | model | rag_triangle (gross) | rag_triangle |
| `syndicate_510_2020` | 13.0 | 20.0 | deterministic override (note) | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, rag_triangle, data_quality_notes |
| `syndicate_510_2021` | -84.0 | -81.0 | deterministic override (note) | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, rag_triangle, data_quality_notes |
| `syndicate_510_2022` | -241.0 | -128.0 | deterministic override (note) | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, rag_triangle, data_quality_notes |
| `syndicate_510_2023` | 171.1 | 135.9 | deterministic override (note) | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, rag_triangle, data_quality_notes |
| `syndicate_557_2014` | -0.7 | -1.4 | model | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, claims_triangle, rag_triangle, data_quality_notes |
| `syndicate_557_2015` | -2.4 | -2.4 | model | model | rag_triangle |
| `syndicate_557_2016` | -2.0 | -2.0 | model | model | rag_triangle |
| `syndicate_557_2017` | -3.7 | -1.5 | model | deterministic override (note) | prior_year_development_gbp_m, prior_year_development_pct, data_quality_notes |
| `syndicate_557_2019` | -5.2 | -3.4 | model | deterministic override (note) | prior_year_development_gbp_m, prior_year_development_pct, rag_triangle, data_quality_notes |
| `syndicate_557_2020` | -0.4 | -0.4 | model | rag_triangle (gross) | rag_triangle |
| `syndicate_557_2021` | -1.3 | -1.2 | model | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, rag_triangle |
| `syndicate_557_2022` | -7.257 | -4.5 | model | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, rag_triangle, data_quality_notes |
| `syndicate_5820_2015` | 10.4 | 10.4 | model | rag_triangle (gross) | rag_triangle |
| `syndicate_5820_2016` | 11.8 | 38.38 | deterministic override (note) | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, rag_triangle, data_quality_notes |
| `syndicate_5820_2017` | 9.0 | 6.79 | deterministic override (note) | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, rag_triangle, data_quality_notes |
| `syndicate_6104_2024` | -16.07 | -16.07 | model | rag_triangle (gross) | rag_triangle |
| `syndicate_6107_2023` | -4.7 | -11.6 | model | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, gross_premium_mix, claims_triangle, rag_triangle, data_quality_notes |
| `syndicate_6107_2024` | -0.946 | -0.946 | deterministic override (note) | rag_triangle (gross) | rag_triangle |
| `syndicate_6117_2023` | -2.5 | -2.5 | model | rag_triangle (gross) | rag_triangle |
| `syndicate_6131_2020` | 1.259 | 1.259 | model | rag_triangle (gross) | rag_triangle |
| `syndicate_727_2022` | -5.836 | -5.836 | deterministic override (note) | rag_triangle (gross) | rag_triangle |
| `syndicate_958_2015` | -4.935 | -4.935 | model | rag_triangle (gross) | rag_triangle |

## Stems that could not be replayed offline

These reports' page-level caches are absent or in the superseded format, so the corrected rules could not be applied to them without fresh paid inference. Their committed records stand unchanged, and the driver exits non-zero rather than deleting them.

- `syndicate_1301_2016`
- `syndicate_1969_2015`
- `syndicate_2988_2021`
- `syndicate_2988_2022`
- `syndicate_2988_2023`
- `syndicate_6117_2017`
- `syndicate_6117_2018`
- `syndicate_6117_2019`
- `syndicate_6117_2020`
- `syndicate_6117_2021`
- `syndicate_623_2016`
- `syndicate_623_2019`

