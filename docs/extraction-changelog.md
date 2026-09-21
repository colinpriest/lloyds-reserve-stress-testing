# Extraction change log

> **Generated file — do not edit.** Written by `scripts/extraction_changelog.py` by comparing every committed record with the same record at commit `7334497`.

Round 55 (the external review of 10 September 2026) corrected two extraction rules and re-extracted the records they touch, offline from the committed response and table caches. The rules were: the percentage-against-monetary decision, which now rests on the table's own unit evidence before any magnitude heuristic (finding T03); and the transposed-grid parser, which now captures one basis block of a page that prints a gross and a net triangle under one header, and labels it by that block's own heading. The route by which each record's development figure was adopted is now recorded on the record (`_pyd_route`) instead of being inferred from a sentence in its notes.

**1055 record(s) differ from `7334497`.** The adopted figure moves in 212 of them.

| Record | Development, before | after | Route, before | after | Fields that differ |
|---|---:|---:|---|---|---|
| `syndicate_1084_2014` | -77.4 | -77.4 | model | model_reading (?) | gross_premiums_written_gbp_m, adobe_lob, data_quality_notes |
| `syndicate_1084_2015` | -95.7 | -95.7 | model | model_reading (?) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1084_2016` | -95.7 | -95.7 | model | model_reading (?) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_1084_2017` | -38.9 | -38.9 | deterministic override (note) | rag_triangle (gross) | claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1084_2018` | -134.0 | -134.0 | deterministic override (note) | rag_triangle (gross) | gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1084_2019` | -86.5 | -86.5 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1084_2020` | -74.5 | -74.5 | model | model_reading (?) | prior_year_development_pct, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1084_2021` | -206.2 | -206.2 | deterministic override (note) | rag_triangle (gross) | claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1084_2022` | -85.9 | -85.9 | model | model_reading (?) | prior_year_development_pct, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1084_2023` | -47.8 | -47.8 | deterministic override (note) | rag_triangle (gross) | gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1084_2024` | -25.8 | -25.8 | model | rag_provisions (?) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_1110_2014` | -6.4 | -1.3 | model | model_reading (?) | prior_year_development_gbp_m, prior_year_development_pct, data_quality_notes |
| `syndicate_1110_2015` | 0.453 | 0.453 | deterministic override (note) | rag_triangle (net) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_1110_2016` | 8.277 | 8.277 | model | rag_triangle (net) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1110_2017` | -1.845 | -1.845 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1110_2018` | -3.5 | -3.5 | model | model_reading (?) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, adobe_lob, data_quality_notes |
| `syndicate_1110_2019` | -1.7 | -0.2 | model | model_reading (?) | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, adobe_lob, data_quality_notes |
| `syndicate_1110_2020` | 2.728 | 2.728 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1110_2021` | 55.171 | 55.171 | deterministic override (note) | rag_triangle (gross) | opening_reserves_gbp_m, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1110_2022` | 9.082 | 9.082 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1110_2023` | 38.784 | 38.784 | model | rag_triangle (gross) | gross_premium_mix, claims_triangle, rag_triangle, data_quality_notes |
| `syndicate_1110_2024` | 64.979 | 64.979 | deterministic override (note) | rag_triangle (gross) | claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_1176_2014` | -9.5 | -9.5 | model | model_reading (?) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, adobe_lob, data_quality_notes |
| `syndicate_1176_2015` | -5.749 | -5.749 | deterministic override (note) | rag_triangle (net) | gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1176_2016` | -2.851 | -2.851 | model | rag_triangle (gross) | gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1176_2017` | -7.232 | -7.232 | model | rag_triangle (gross) | gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1176_2018` | -5.082 | -5.082 | deterministic override (note) | rag_triangle (gross) | gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1176_2019` | -8.44 | -8.44 | deterministic override (note) | rag_triangle (gross) | gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1176_2020` | -7.549 | -7.549 | deterministic override (note) | rag_triangle (gross) | gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1176_2021` | -7.647 | -7.647 | deterministic override (note) | rag_triangle (gross) | gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1176_2022` | -8.097 | -8.097 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1176_2023` | -7.56 | -7.56 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1176_2024` | -6.286 | -6.286 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_1183_2014` | -85.8 | -85.8 | model | model_reading (?) | prior_year_development_pct, claims_triangle, adobe_lob, data_quality_notes, currency |
| `syndicate_1183_2015` | -61.5 | -61.5 | model | rag_triangle (gross) | gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1183_2016` | 31.8 | 31.8 | model | rag_triangle (gross) | claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1183_2017` | -23.2 | -23.2 | deterministic override (note) | rag_triangle (gross) | gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1183_2018` | -89.0 | 33.8 | model | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, claims_triangle, rag_triangle, adobe_lob, data_quality_notes, direction |
| `syndicate_1183_2019` | 20.0 | -18.5 | deterministic override (note) | code_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes, direction |
| `syndicate_1183_2020` | -40.9 | -42.8 | model | model_reading (?) | prior_year_development_gbp_m, prior_year_development_pct, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1183_2021` | 47.1 | 47.1 | model | rag_triangle (gross) | claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1183_2022` | 74.9 | -57.8 | deterministic override (note) | model_reading (?) | prior_year_development_gbp_m, prior_year_development_pct, claims_triangle, rag_triangle, adobe_lob, data_quality_notes, direction |
| `syndicate_1183_2023` | -29.4 | -29.4 | deterministic override (note) | rag_triangle (gross) | claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1183_2024` | 371.19 | 371.19 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1200_2014` | -18.0 | -18.0 | model | model_reading (?) | prior_year_development_pct, opening_reserves_gbp_m, gross_premiums_written_gbp_m, gross_premium_mix, adobe_lob, data_quality_notes |
| `syndicate_1200_2015` | 6.6 | 0.5 | deterministic override (note) | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_1200_2016` | 20.0 | 20.0 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_1200_2017` | 40.5 | 44.9 | deterministic override (note) | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, gross_premium_mix, claims_triangle, rag_triangle, data_quality_notes |
| `syndicate_1200_2018` | 85.5 | 85.5 | deterministic override (note) | rag_triangle (gross) | gross_premium_mix, claims_triangle, rag_triangle, data_quality_notes |
| `syndicate_1200_2019` | 107.6 | 107.6 | deterministic override (note) | rag_triangle (gross) | gross_premium_mix, claims_triangle, rag_triangle, data_quality_notes |
| `syndicate_1200_2020` | 54.4 | 54.4 | deterministic override (note) | rag_triangle (gross) | gross_premium_mix, claims_triangle, rag_triangle, data_quality_notes |
| `syndicate_1200_2021` | 28.0 | 28.0 | deterministic override (note) | rag_triangle (gross) | gross_premium_mix, claims_triangle, rag_triangle, data_quality_notes |
| `syndicate_1200_2022` | -17.1 | -17.1 | deterministic override (note) | rag_triangle (gross) | gross_premium_mix, claims_triangle, rag_triangle, data_quality_notes |
| `syndicate_1200_2023` | 27.5 | 27.5 | deterministic override (note) | rag_triangle (gross) | gross_premium_mix, claims_triangle, rag_triangle, data_quality_notes |
| `syndicate_1200_2024` | 38.761 | 38.761 | deterministic override (note) | rag_triangle (gross) | gross_premium_mix, claims_triangle, rag_triangle, data_quality_notes |
| `syndicate_1206_2014` | 31.6 | 31.6 | deterministic override (note) | rag_provisions (?) | gross_premiums_written_gbp_m, gross_premium_mix, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_1206_2015` | 25.063 | 25.063 | deterministic override (note) | rag_triangle (gross) | gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_1206_2016` | 2.951 | 2.951 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_1206_2017` | 20.956 | 20.956 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1206_2018` | 21.374 | 21.374 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1206_2019` | -1.0 | -1.0 | model | model_reading (?) | gross_premium_mix, rag_triangle, data_quality_notes |
| `syndicate_1209_2014` | 0.3 | 0.3 | model | model_reading (?) | gross_premiums_written_gbp_m, gross_premium_mix, adobe_lob, data_quality_notes |
| `syndicate_1209_2015` | -37.6 | -37.6 | model | model_reading (?) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1209_2016` | 11.649 | -19.0 | model | model_reading (?) | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes, direction |
| `syndicate_1209_2017` | 21.389 | 21.389 | deterministic override (note) | rag_triangle (gross) | gross_premium_mix, claims_triangle, rag_triangle, data_quality_notes |
| `syndicate_1218_2014` | -10.9 | -10.9 | model | model_reading (?) | prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, adobe_lob, data_quality_notes |
| `syndicate_1218_2015` | -0.46 | -0.46 | model | rag_triangle (gross) | prior_year_development_pct, opening_reserves_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1218_2016` | -8.941 | -8.941 | deterministic override (note) | rag_triangle (gross) | gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1218_2017` | -3.14 | -3.14 | deterministic override (note) | rag_triangle (gross) | claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1218_2018` | -22.744 | -22.744 | model | rag_triangle (gross) | gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1218_2019` | 30.531 | 30.531 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1218_2020` | 21.936 | 21.936 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1218_2021` | -13.095 | -13.095 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1218_2022` | 32.627 | 32.627 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1218_2023` | -39.494 | -39.494 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1218_2024` | -13.922 | -13.922 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions |
| `syndicate_1221_2014` | None | None | model | model | provenance only |
| `syndicate_1221_2015` | -1.727 | -1.727 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_1221_2016` | 88.2 | 88.2 | model | rag_provisions (?) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_1221_2017` | 2.036 | 2.036 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_1221_2018` | 35.191 | 35.191 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_1221_2019` | 72.266 | 72.266 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_1221_2020` | 52.497 | 52.497 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_1221_2021` | 8.482 | 8.482 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_1221_2022` | 84.511 | 84.511 | deterministic override (note) | rag_triangle (gross) | gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_1221_2023` | 78.2 | 78.2 | model | rag_provisions (?) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_1221_2024` | 97.477 | 97.477 | model | model_reading (?) | claims_triangle, rag_triangle, data_quality_notes |
| `syndicate_1225_2014` | None | None | model | model | provenance only |
| `syndicate_1225_2015` | -5.0 | -5.0 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1225_2016` | 12.1 | -27.8 | deterministic override (note) | model_reading (?) | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes, direction |
| `syndicate_1225_2017` | -14.0 | -14.0 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1225_2018` | -9.1 | -9.1 | model | rag_triangle (gross) | prior_year_development_pct, opening_reserves_gbp_m, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1225_2019` | 7.8 | 7.8 | deterministic override (note) | rag_triangle (gross) | gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1225_2020` | 22.1 | 22.1 | model | rag_triangle (gross) | gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1225_2021` | 8.1 | 8.1 | deterministic override (note) | rag_triangle (gross) | gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1225_2022` | 18.6 | 18.6 | deterministic override (note) | rag_triangle (gross) | gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1225_2023` | 19.7 | 19.7 | deterministic override (note) | rag_triangle (gross) | gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1225_2024` | -8.958 | -8.958 | deterministic override (note) | rag_triangle (gross) | gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1254_2022` | -4.7 | -4.7 | model | model_reading (?) | prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, adobe_lob, data_quality_notes |
| `syndicate_1254_2023` | 10.525 | 10.525 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1274_2014` | None | None | model | model | provenance only |
| `syndicate_1274_2015` | 23.366 | 23.366 | model | rag_triangle (gross) | claims_triangle, rag_triangle, data_quality_notes |
| `syndicate_1274_2016` | 57.503 | 57.503 | model | rag_triangle (gross) | claims_triangle, rag_triangle, data_quality_notes |
| `syndicate_1274_2017` | 24.766 | 24.766 | model | rag_triangle (gross) | prior_year_development_pct, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1274_2018` | 84.32 | 294.748 | deterministic override (note) | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1274_2019` | 602.8 | -6.619 | deterministic override (note) | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes, direction |
| `syndicate_1274_2020` | 130.209 | 130.209 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_1274_2021` | 72.645 | 72.645 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_1274_2022` | 41.013 | 41.013 | deterministic override (note) | rag_triangle (gross) | prior_year_development_pct, opening_reserves_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_1274_2023` | 58.692 | 58.692 | deterministic override (note) | rag_triangle (gross) | gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_1274_2024` | 53.399 | 53.399 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1301_2014` | -6.2 | -6.2 | model | model_reading (?) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, adobe_lob, data_quality_notes |
| `syndicate_1301_2015` | -13.6 | -5.8 | model | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_1301_2016` | -13.5 | -1.6 | model | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_1301_2017` | 77.1 | 7.6 | model | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_1301_2018` | 37.1 | 37.1 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_1301_2019` | 45.7 | 45.7 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_1301_2020` | -5.3 | -5.3 | model | rag_provisions (?) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_1301_2021` | 15.5 | 15.5 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_1301_2022` | -33.6 | -33.6 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1301_2023` | 22.1 | 22.1 | model | rag_triangle (gross) | gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1301_2024` | -59.1 | -59.1 | model | rag_provisions (?) | gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_1322_2023` | None | None | model | model | provenance only |
| `syndicate_1322_2024` | None | None | model | model | provenance only |
| `syndicate_1347_2023` | None | None | model | model | provenance only |
| `syndicate_1400_2014` | None | -2.298 | model | rag_triangle (net) | prior_year_development_gbp_m, prior_year_development_pct, opening_reserves_gbp_m, gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_provisions, data_quality_notes, currency, direction |
| `syndicate_1400_2015` | -19.171 | -19.171 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1414_2014` | -5.2 | -5.2 | model | model_reading (?) | gross_premiums_written_gbp_m, gross_premium_mix, adobe_lob, data_quality_notes |
| `syndicate_1414_2015` | -13.749 | -13.749 | deterministic override (note) | rag_triangle (gross) | gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1414_2016` | -0.195 | -0.195 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1414_2017` | 9.151 | 9.151 | model | rag_triangle (gross) | gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1414_2018` | 24.798 | 24.798 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1414_2019` | -39.717 | -39.717 | model | rag_triangle (gross) | gross_premium_mix, claims_triangle, rag_triangle, data_quality_notes |
| `syndicate_1414_2020` | 36.394 | 36.394 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1414_2021` | 66.053 | 66.053 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1414_2022` | 94.65 | 94.65 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1414_2023` | 70.631 | 70.631 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1414_2024` | -15.6 | -15.6 | model | rag_provisions (?) | gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_1416_2022` | None | None | model | model | provenance only |
| `syndicate_1416_2023` | 2.065 | 2.065 | deterministic override (note) | rag_triangle (gross) | claims_triangle, rag_triangle, data_quality_notes |
| `syndicate_1416_2024` | -0.302 | -0.302 | model | rag_triangle (gross) | gross_premium_mix, claims_triangle, rag_triangle, data_quality_notes |
| `syndicate_1458_2014` | -8.7 | -8.7 | model | model_reading (?) | gross_premiums_written_gbp_m, gross_premium_mix, adobe_lob |
| `syndicate_1458_2015` | -1.113 | -1.113 | deterministic override (note) | rag_triangle (gross) | opening_reserves_gbp_m, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1458_2016` | -3.834 | -3.834 | deterministic override (note) | rag_triangle (gross) | gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1458_2017` | 24.637 | 24.637 | model | rag_triangle (gross) | opening_reserves_gbp_m, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1458_2018` | 45.431 | 45.431 | model | rag_triangle (gross) | gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1458_2019` | 59.558 | 59.558 | deterministic override (note) | rag_triangle (gross) | opening_reserves_gbp_m, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1458_2020` | 46.528 | -6.6 | deterministic override (note) | model_reading (?) | prior_year_development_gbp_m, prior_year_development_pct, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes, direction |
| `syndicate_1458_2021` | 57.601 | 57.601 | model | rag_triangle (gross) | opening_reserves_gbp_m, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1458_2022` | 7.562 | -63.2 | deterministic override (note) | model_reading (?) | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes, direction |
| `syndicate_1458_2023` | -89.6 | -89.6 | model | model_reading (?) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1458_2024` | -33.258 | -33.258 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_1492_2015` | None | None | model | model | provenance only |
| `syndicate_1492_2016` | None | None | model | model | provenance only |
| `syndicate_1492_2017` | -0.434 | -0.434 | model | rag_triangle (gross) | gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1492_2018` | -36.501 | 6.246 | model | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, claims_triangle, rag_triangle, adobe_lob, data_quality_notes, direction |
| `syndicate_1492_2019` | 10.889 | 10.889 | model | rag_triangle (gross) | gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1492_2020` | 9.086 | 9.086 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1492_2021` | 5.614 | 5.614 | model | rag_triangle (gross) | gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1492_2022` | 3.669 | -26.741 | deterministic override (note) | model_reading (?) | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes, direction |
| `syndicate_1492_2023` | -14.766 | -14.766 | model | rag_triangle (gross) | gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1492_2024` | -15.7 | -15.7 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_1609_2021` | None | None | model | model | provenance only |
| `syndicate_1609_2022` | None | None | model | model | provenance only |
| `syndicate_1609_2023` | 11.657 | 11.657 | model | rag_triangle (gross) | gross_premium_mix, claims_triangle, rag_triangle, data_quality_notes |
| `syndicate_1609_2024` | -0.185 | -0.185 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions |
| `syndicate_1618_2021` | None | None | model | model | provenance only |
| `syndicate_1618_2022` | None | None | model | model | provenance only |
| `syndicate_1618_2023` | 208.5 | 3.7 | model | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1618_2024` | -13.21 | -13.21 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1686_2014` | None | None | model | model | provenance only |
| `syndicate_1686_2015` | None | None | model | model | provenance only |
| `syndicate_1686_2016` | -1.165 | -1.165 | model | rag_triangle (gross) | gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1686_2017` | 21.711 | 21.711 | deterministic override (note) | rag_triangle (gross) | gross_premium_mix, claims_triangle, rag_triangle, data_quality_notes |
| `syndicate_1686_2018` | 16.628 | 16.628 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1686_2019` | 2.876 | 2.876 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1686_2020` | 54.007 | 54.007 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1686_2021` | 105.521 | -397.3 | model | model_reading (?) | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes, direction |
| `syndicate_1686_2022` | -21.386 | -21.386 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1686_2023` | 116.166 | 116.166 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1686_2024` | -155.7 | -155.7 | model | rag_provisions (?) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_1699_2022` | None | None | model | model | provenance only |
| `syndicate_1699_2023` | None | None | model | model | provenance only |
| `syndicate_1699_2024` | -8.2 | -8.2 | model | rag_provisions (?) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_1729_2014` | None | None | model | model | provenance only |
| `syndicate_1729_2015` | None | -1.2 | model | model_reading (?) | prior_year_development_gbp_m, prior_year_development_pct, opening_reserves_gbp_m, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, adobe_lob, data_quality_notes, currency, direction |
| `syndicate_1729_2016` | 0.822 | 0.822 | deterministic override (note) | rag_triangle (gross) | claims_triangle, rag_triangle, data_quality_notes |
| `syndicate_1729_2017` | 0.441 | 0.441 | model | rag_triangle (gross) | gross_premium_mix, claims_triangle, rag_triangle, data_quality_notes |
| `syndicate_1729_2018` | 5.443 | 5.443 | model | rag_triangle (gross) | gross_premium_mix, claims_triangle, rag_triangle, data_quality_notes |
| `syndicate_1729_2019` | 7.713 | 7.713 | deterministic override (note) | rag_triangle (gross) | gross_premium_mix, claims_triangle, rag_triangle, data_quality_notes |
| `syndicate_1729_2020` | 7.305 | 7.305 | model | rag_triangle (gross) | claims_triangle, rag_triangle, data_quality_notes |
| `syndicate_1729_2021` | 3.217 | 3.217 | model | rag_triangle (gross) | claims_triangle, rag_triangle, data_quality_notes |
| `syndicate_1729_2022` | 14.707 | 14.707 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1729_2023` | 16.766 | 16.766 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1729_2024` | 77.918 | 77.918 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1796_2021` | None | None | model | model | provenance only |
| `syndicate_1796_2022` | None | None | model | model | provenance only |
| `syndicate_1796_2023` | -0.056 | -0.056 | model | rag_triangle (net) | gross_premium_mix, claims_triangle, rag_triangle, data_quality_notes |
| `syndicate_1796_2024` | 1.8 | 1.824 | model | model_reading (?) | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_1840_2020` | None | None | model | model | provenance only |
| `syndicate_1840_2021` | None | None | model | model | provenance only |
| `syndicate_1840_2022` | None | None | model | model | provenance only |
| `syndicate_1840_2023` | 0.095 | 0.095 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1840_2024` | 0.05 | 0.05 | model | rag_triangle (gross) | prior_year_development_pct, opening_reserves_gbp_m, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_1856_2017` | None | None | model | model | provenance only |
| `syndicate_1856_2018` | 59.638 | 59.638 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1856_2019` | 0.557 | 0.557 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1856_2020` | -62.513 | -62.513 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1856_2021` | -16.186 | -16.186 | model | rag_triangle (gross) | prior_year_development_pct, opening_reserves_gbp_m, gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1856_2022` | 1.525 | 1.525 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1856_2023` | 20.1 | 20.1 | model | rag_triangle (gross) | claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1856_2024` | 140.888 | 140.888 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1861_2014` | -6.4 | -6.4 | model | model_reading (?) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, adobe_lob, data_quality_notes |
| `syndicate_1861_2015` | -4.908 | -4.908 | deterministic override (note) | rag_triangle (gross) | gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_1861_2016` | 24.745 | 24.745 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_1861_2017` | 36.585 | 36.585 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_1861_2018` | 8.684 | 8.684 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1861_2019` | 22.179 | 22.179 | deterministic override (note) | rag_triangle (gross) | gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1861_2020` | 7.9 | 7.9 | model | model_reading (?) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1861_2021` | 34.519 | 34.519 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1861_2022` | 7.156 | 7.156 | model | rag_triangle (gross) | gross_premium_mix, claims_triangle, rag_triangle, data_quality_notes |
| `syndicate_1880_2014` | -13.6 | -13.6 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1880_2015` | -5.8 | -5.8 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1880_2016` | -16.4 | -16.4 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1880_2017` | 2.0 | 2.0 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1880_2018` | 7.6 | -13.8 | deterministic override (note) | model_reading (?) | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes, direction |
| `syndicate_1880_2019` | 20.9 | 20.9 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1880_2020` | 1.7 | -14.029 | model | model_reading (?) | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes, direction |
| `syndicate_1880_2021` | None | -24.8 | model | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, opening_reserves_gbp_m, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes, currency, direction |
| `syndicate_1880_2022` | -53.1 | -19.7 | deterministic override (note) | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1880_2023` | 20.2 | 18.0 | deterministic override (note) | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1880_2024` | 24.73 | 24.73 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_1882_2014` | None | None | model | model | provenance only |
| `syndicate_1882_2015` | 12.863 | 12.863 | model | rag_triangle (net) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1882_2016` | 9.798 | 9.798 | deterministic override (note) | rag_triangle (net) | opening_reserves_gbp_m, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1882_2017` | 17.581 | 17.581 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1882_2018` | 10.653 | 10.653 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, data_quality_notes, currency |
| `syndicate_1884_2015` | None | None | model | model | provenance only |
| `syndicate_1884_2016` | None | None | model | model | provenance only |
| `syndicate_1884_2017` | 0.557 | -0.557 | deterministic override (note) | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes, direction |
| `syndicate_1884_2018` | 1.947 | -1.947 | deterministic override (note) | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes, direction |
| `syndicate_1884_2019` | 11.703 | 11.703 | model | rag_triangle (gross) | gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1884_2020` | 0.816 | -0.816 | deterministic override (note) | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes, direction |
| `syndicate_1884_2021` | -20.1 | -20.1 | model | rag_triangle (gross) | gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1884_2022` | -30.088 | None | model | model | prior_year_development_gbp_m, prior_year_development_pct, opening_reserves_gbp_m, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes, currency, direction |
| `syndicate_1884_2023` | 36.0 | 36.0 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1884_2024` | 46.489 | 46.489 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_1892_2019` | None | None | model | model | provenance only |
| `syndicate_1892_2020` | None | None | model | model | provenance only |
| `syndicate_1892_2021` | -1.994 | -1.994 | deterministic override (note) | rag_triangle (gross) | rag_triangle, data_quality_notes |
| `syndicate_1892_2022` | -1.858 | -1.858 | model | rag_triangle (gross) | gross_premium_mix, rag_triangle, data_quality_notes |
| `syndicate_1892_2023` | -1.827 | -1.827 | model | rag_triangle (gross) | gross_premium_mix, claims_triangle, rag_triangle, data_quality_notes |
| `syndicate_1892_2024` | -2.576 | -2.576 | model | rag_triangle (gross) | gross_premium_mix, rag_triangle, adobe_provisions, data_quality_notes |
| `syndicate_1897_2014` | None | None | model | model | opening_reserves_gbp_m, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, data_quality_notes, currency, direction |
| `syndicate_1897_2015` | -2.279 | -2.279 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1897_2016` | 27.506 | 27.506 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1897_2017` | 7.032 | 7.032 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1897_2018` | 15.449 | 15.449 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1897_2019` | 11.964 | 11.964 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1902_2022` | None | None | model | model | provenance only |
| `syndicate_1902_2023` | None | None | model | model | provenance only |
| `syndicate_1902_2024` | None | None | model | model | provenance only |
| `syndicate_1910_2014` | -1.3 | -1.3 | model | model_reading (?) | gross_premium_mix, data_quality_notes |
| `syndicate_1910_2015` | -6.283 | -6.283 | model | rag_triangle (gross) | claims_triangle, rag_triangle, data_quality_notes |
| `syndicate_1910_2016` | -8.28 | -8.28 | model | rag_triangle (gross) | gross_premium_mix, claims_triangle, rag_triangle, data_quality_notes |
| `syndicate_1910_2017` | -5.3 | -5.3 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1910_2018` | 1.91 | 1.91 | deterministic override (note) | rag_triangle (gross) | gross_premium_mix, claims_triangle, rag_triangle, data_quality_notes |
| `syndicate_1910_2019` | 5.0 | 5.0 | deterministic override (note) | rag_triangle (gross) | opening_reserves_gbp_m, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1910_2020` | -22.3 | -22.3 | deterministic override (note) | rag_triangle (gross) | gross_premium_mix, data_quality_notes |
| `syndicate_1910_2021` | -24.0 | -24.0 | deterministic override (note) | rag_triangle (gross) | data_quality_notes |
| `syndicate_1910_2022` | 10.1 | 10.1 | deterministic override (note) | rag_triangle (gross) | claims_triangle, rag_triangle, data_quality_notes |
| `syndicate_1910_2023` | -10.6 | -10.6 | model | rag_triangle (gross) | gross_premium_mix, claims_triangle, rag_triangle, data_quality_notes |
| `syndicate_1910_2024` | -45.34 | -45.34 | model | model_reading (?) | prior_year_development_pct, gross_premium_mix, rag_triangle, data_quality_notes |
| `syndicate_1919_2014` | 12.5 | 12.5 | model | model_reading (?) | gross_premiums_written_gbp_m, gross_premium_mix, adobe_lob, data_quality_notes |
| `syndicate_1919_2015` | -10.323 | -10.323 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1919_2016` | -11.948 | -11.948 | model | rag_triangle (gross) | opening_reserves_gbp_m, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1919_2017` | -6.661 | -6.661 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1919_2018` | 38.627 | 38.627 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1919_2019` | 92.577 | 64.2 | deterministic override (note) | model_reading (?) | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, adobe_lob, data_quality_notes |
| `syndicate_1919_2020` | 37.404 | 37.404 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1919_2021` | 90.984 | 90.984 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1919_2022` | 82.221 | 82.221 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1919_2023` | -33.959 | -33.959 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1919_2024` | 99.541 | 99.541 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_1922_2024` | None | None | model | model | provenance only |
| `syndicate_1925_2024` | None | None | model | model | provenance only |
| `syndicate_1945_2014` | -4.7 | -4.7 | model | rag_general_narrative (?) | gross_premiums_written_gbp_m, gross_premium_mix, adobe_lob, data_quality_notes |
| `syndicate_1945_2015` | -3.863 | -3.863 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_1945_2016` | -10.776 | -10.776 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_1945_2017` | 11.689 | 11.689 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_1945_2018` | 8.067 | 8.067 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_1945_2019` | 3.856 | 3.856 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_1945_2020` | -36.1 | -36.1 | model | rag_provisions (?) | gross_premium_mix, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_1945_2021` | 31.7 | 31.7 | model | rag_provisions (?) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_1945_2022` | -13.831 | -13.84 | deterministic override (note) | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_1945_2023` | -4.997 | -5.034 | deterministic override (note) | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_1945_2024` | -64.7 | -64.7 | model | rag_provisions (?) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_1947_2018` | None | None | model | model | provenance only |
| `syndicate_1947_2019` | None | 1.8 | model | rag_provisions_text (?) | prior_year_development_gbp_m, prior_year_development_pct, opening_reserves_gbp_m, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes, currency, direction |
| `syndicate_1947_2020` | -3.502 | -3.502 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1947_2021` | -4.633 | -4.633 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1947_2022` | -14.449 | -14.449 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1947_2023` | 4.675 | 4.675 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1947_2024` | 9.412 | 9.412 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_1955_2014` | 11.1 | 11.1 | model | model_reading (?) | gross_premiums_written_gbp_m, gross_premium_mix, adobe_lob, data_quality_notes |
| `syndicate_1955_2015` | -290.0 | 11.444 | model | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, gross_premium_mix, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes, direction |
| `syndicate_1955_2018` | 18.5 | 16.7 | deterministic override (note) | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_1955_2019` | 65.8 | 44.2 | deterministic override (note) | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_1955_2020` | 10.7 | 15.9 | deterministic override (note) | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, gross_premium_mix, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_1955_2021` | 14.944 | 14.944 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1955_2022` | 30.511 | 30.511 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1955_2023` | 6.565 | 6.565 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, adobe_lob, data_quality_notes |
| `syndicate_1955_2024` | -30.3 | -30.3 | model | rag_provisions (?) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_1967_2014` | 9.082 | 9.082 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1967_2015` | 7.95 | 7.95 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1967_2016` | 21.18 | 21.18 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1967_2017` | 11.417 | 11.417 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1967_2018` | 31.226 | 31.226 | deterministic override (note) | rag_triangle (gross) | gross_premium_mix, claims_triangle, rag_triangle, adobe_lob |
| `syndicate_1967_2019` | 14.041 | 14.041 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1967_2020` | 63.974 | 63.974 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1967_2021` | 16.809 | 16.809 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1967_2022` | 45.457 | 45.457 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1967_2023` | -1.0 | -1.0 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1967_2024` | 6.853 | 6.853 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_1969_2014` | 0.3 | -2.4 | model | model_reading (?) | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes, direction |
| `syndicate_1969_2015` | -1.8 | -1.8 | model | rag_triangle (gross) | gross_premium_mix, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_1969_2016` | 2.3 | 13.5 | deterministic override (note) | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_1969_2017` | 9.5 | 9.5 | deterministic override (note) | rag_triangle (gross) | gross_premium_mix, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_1969_2018` | 80.1 | 80.1 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_1969_2019` | 39.9 | 39.9 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_1969_2020` | -21.7 | 12.3 | model | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, gross_premium_mix, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes, direction |
| `syndicate_1969_2021` | 26.8 | 26.8 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1969_2022` | -7.883 | 29.6 | model | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes, direction |
| `syndicate_1969_2023` | 50.8 | 50.8 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1969_2024` | 107.7 | 107.7 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes, currency |
| `syndicate_1971_2019` | None | None | model | model | provenance only |
| `syndicate_1971_2020` | None | None | model | model | provenance only |
| `syndicate_1971_2021` | 13.504 | 13.504 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, data_quality_notes |
| `syndicate_1971_2022` | 25.471 | 25.471 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1971_2023` | 17.675 | 17.675 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1971_2024` | 10.055 | 10.055 | deterministic override (note) | rag_triangle (gross) | gross_premium_mix, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_1975_2018` | None | None | model | model | provenance only |
| `syndicate_1975_2019` | None | None | model | model | provenance only |
| `syndicate_1975_2020` | 11.431 | 11.431 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1975_2021` | -9.539 | -9.539 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1975_2022` | -39.136 | -39.136 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1980_2018` | None | 30.4 | model | rag_provisions (?) | prior_year_development_gbp_m, prior_year_development_pct, opening_reserves_gbp_m, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, adobe_lob, adobe_provisions, data_quality_notes, currency, direction |
| `syndicate_1980_2019` | None | None | model | model | provenance only |
| `syndicate_1985_2023` | None | None | model | model | provenance only |
| `syndicate_1985_2024` | None | None | model | model | provenance only |
| `syndicate_1988_2022` | None | None | model | model | provenance only |
| `syndicate_1988_2023` | 5.647 | 5.647 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_1988_2024` | None | None | model | model | provenance only |
| `syndicate_1991_2014` | None | None | model | model | provenance only |
| `syndicate_1991_2015` | 11.24 | 11.24 | deterministic override (note) | rag_triangle (gross) | claims_triangle, rag_triangle, data_quality_notes |
| `syndicate_1991_2016` | 23.157 | 23.157 | deterministic override (note) | rag_triangle (gross) | gross_premium_mix, rag_triangle, data_quality_notes |
| `syndicate_1991_2017` | 27.876 | 27.876 | deterministic override (note) | rag_triangle (gross) | gross_premium_mix, claims_triangle, rag_triangle, data_quality_notes |
| `syndicate_1991_2018` | 75.974 | 75.974 | model | model_reading (?) | gross_premium_mix, rag_triangle, data_quality_notes |
| `syndicate_1991_2019` | 58.418 | 58.418 | model | rag_triangle (gross) | claims_triangle, rag_triangle, data_quality_notes |
| `syndicate_1991_2020` | 114.371 | 114.371 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob |
| `syndicate_1994_2021` | None | None | model | model | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_1994_2024` | 22.3 | 22.3 | model | rag_provisions (?) | gross_premiums_written_gbp_m, gross_premium_mix, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_1996_2024` | -0.1 | -0.1 | model | rag_provisions (?) | gross_premiums_written_gbp_m, gross_premium_mix, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_2001_2014` | 0.6 | -8.2 | model | model_reading (?) | prior_year_development_gbp_m, prior_year_development_pct, adobe_lob, data_quality_notes, direction |
| `syndicate_2001_2015` | -22.8 | -22.8 | deterministic override (note) | rag_triangle (gross) | gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_2001_2016` | -69.6 | -69.6 | model | rag_provisions (?) | gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_2001_2017` | 111.3 | 111.3 | deterministic override (note) | rag_triangle (gross) | claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_2001_2018` | 175.0 | 175.0 | deterministic override (note) | rag_triangle (gross) | claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_2001_2019` | 51.4 | 51.4 | model | rag_provisions (?) | claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_2001_2020` | -11.5 | -11.5 | model | rag_provisions (?) | rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_2001_2021` | -67.7 | -67.7 | model | rag_provisions (?) | rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_2001_2022` | -256.3 | -256.3 | model | rag_provisions (?) | rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_2001_2023` | -3.3 | -3.3 | deterministic override (note) | rag_triangle (gross) | opening_reserves_gbp_m, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_2001_2024` | 247.711 | 247.711 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_2003_2014` | -169.1 | -169.1 | model | model_reading (?) | prior_year_development_pct, opening_reserves_gbp_m, gross_premiums_written_gbp_m, gross_premium_mix, adobe_lob, data_quality_notes |
| `syndicate_2003_2015` | 927.601 | -8.4 | deterministic override (note) | model_reading (?) | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes, direction |
| `syndicate_2003_2016` | -167.2 | -167.2 | model | model_reading (?) | gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_2003_2017` | 91.0 | 91.0 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_2003_2018` | 419.0 | 419.0 | deterministic override (note) | rag_triangle (gross) | prior_year_development_pct, opening_reserves_gbp_m, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_2003_2019` | 200.0 | 200.0 | deterministic override (note) | rag_triangle (gross) | gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_2003_2020` | 369.0 | 369.0 | deterministic override (note) | rag_triangle (gross) | gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_2007_2014` | -26.8 | -26.8 | model | model_reading (?) | gross_premiums_written_gbp_m, gross_premium_mix, adobe_lob, data_quality_notes |
| `syndicate_2007_2015` | -2.0 | -2.0 | deterministic override (note) | code_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_2007_2016` | 61.3 | 61.3 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_2007_2017` | -22.0 | -22.0 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_2007_2018` | 29.57 | 29.57 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_2007_2019` | 8.358 | 8.358 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_2008_2014` | -9.715 | -9.714936 | model | model_reading (?) | prior_year_development_gbp_m, gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_2008_2015` | -8.2 | -8.2 | model | rag_provisions (?) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_2008_2016` | -12.896 | -12.896 | model | model_reading (?) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_2008_2018` | 0.002 | 0.002 | model | model_reading (?) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_2008_2019` | 14.053 | 249.0 | model | rag_provisions (?) | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_2008_2021` | 383.9 | 383.9 | model | rag_provisions (?) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_2008_2023` | 79.213 | 79.213 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_2010_2014` | -28.0 | -0.917 | model | model_reading (?) | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_2010_2015` | -117.0 | 9.646 | deterministic override (note) | rag_provisions_text (?) | prior_year_development_gbp_m, prior_year_development_pct, opening_reserves_gbp_m, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes, direction |
| `syndicate_2010_2016` | -36.0 | 12.007 | deterministic override (note) | rag_provisions_text (?) | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes, direction |
| `syndicate_2010_2017` | 30.0 | 52.141 | deterministic override (note) | rag_provisions_text (?) | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_2010_2018` | 179.8 | 179.777 | model | model_reading (?) | prior_year_development_gbp_m, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_2010_2019` | 132.7 | -18.659 | model | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes, direction |
| `syndicate_2010_2020` | 64.0 | 63.984 | model | model_reading (?) | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_2010_2021` | 24.1 | 24.139 | model | model_reading (?) | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_2010_2022` | 88.7 | 88.663 | model | model_reading (?) | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_2010_2023` | 16.0 | 15.992 | model | model_reading (?) | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_2010_2024` | 42.907 | 42.907 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_2012_2014` | -8.0 | -8.0 | model | model_reading (?) | gross_premiums_written_gbp_m, gross_premium_mix, adobe_lob, data_quality_notes |
| `syndicate_2012_2015` | 16.385 | 16.385 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_2012_2016` | 9.38 | 9.38 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_2012_2017` | 7.274 | 7.274 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_2012_2018` | 10.5 | 10.5 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_2012_2019` | -2.458 | -2.458 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_2014_2014` | None | None | model | model | provenance only |
| `syndicate_2014_2015` | -6.9 | -6.9 | model | rag_provisions (?) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_2014_2016` | -0.3 | -0.3 | model | rag_provisions (?) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_2014_2017` | -1.2 | 4.024 | model | code_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, gross_premium_mix, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes, direction |
| `syndicate_2014_2018` | 18.438 | 18.438 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_2014_2019` | -0.021 | 35.337 | model | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes, direction |
| `syndicate_2015_2014` | -2.6 | -2.6 | model | model_reading (?) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, adobe_lob, data_quality_notes |
| `syndicate_2015_2015` | 8.492 | 8.492 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_2015_2016` | 20.057 | 20.057 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_2015_2017` | 12.802 | 12.802 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_2015_2018` | 37.316 | 37.316 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_2015_2019` | 30.341 | 30.341 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_2015_2020` | -3.048 | -3.048 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_2015_2021` | 12.037 | -5.7 | deterministic override (note) | model_reading (?) | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes, direction |
| `syndicate_2015_2022` | 3.421 | 3.421 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_2015_2023` | -5.6 | 20.593 | model | rag_triangle (net) | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes, direction |
| `syndicate_2015_2024` | 35.139 | 35.139 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_2019_2020` | None | None | model | model | provenance only |
| `syndicate_2019_2021` | None | None | model | model | provenance only |
| `syndicate_2019_2022` | -4.2 | -4.2 | deterministic override (note) | rag_triangle (gross) | gross_premium_mix, claims_triangle, rag_triangle, data_quality_notes |
| `syndicate_2019_2023` | -38.7 | -38.7 | model | rag_triangle (gross) | rag_triangle, data_quality_notes |
| `syndicate_2019_2024` | -32.59 | -32.59 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, rag_triangle, adobe_provisions, data_quality_notes |
| `syndicate_2024_2024` | 0.0 | None | model | model | prior_year_development_gbp_m, prior_year_development_pct, opening_reserves_gbp_m, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, adobe_provisions, data_quality_notes, currency, direction |
| `syndicate_2088_2014` | None | None | model | model | provenance only |
| `syndicate_2088_2015` | 20.144 | 0.465 | deterministic override (note) | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_2088_2016` | -1.1 | -1.1 | model | model_reading (?) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_2088_2017` | -29.778 | -0.8 | deterministic override (note) | model_reading (?) | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_2088_2018` | 4.242 | 10.856 | deterministic override (note) | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_2088_2019` | 12.214 | 12.214 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_2121_2014` | -1.922 | -1.922 | model | model_reading (?) | gross_premium_mix, claims_triangle, data_quality_notes |
| `syndicate_2121_2015` | 1.776 | 1.619 | model | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, rag_triangle, data_quality_notes |
| `syndicate_2121_2016` | -8.089 | -9.403 | deterministic override (note) | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, claims_triangle, rag_triangle, data_quality_notes |
| `syndicate_2121_2017` | -1.038 | -1.038 | deterministic override (note) | rag_triangle (gross) | gross_premium_mix, claims_triangle, rag_triangle, data_quality_notes |
| `syndicate_2121_2018` | 27.589 | 27.589 | deterministic override (note) | rag_triangle (gross) | claims_triangle, rag_triangle, data_quality_notes |
| `syndicate_2121_2019` | 3.7 | 3.7 | model | model_reading (?) | claims_triangle, rag_triangle, data_quality_notes |
| `syndicate_2121_2020` | 43.9 | 43.9 | deterministic override (note) | rag_triangle (gross) | claims_triangle, rag_triangle, data_quality_notes |
| `syndicate_2121_2021` | -8.5 | -10.6 | model | model_reading (?) | prior_year_development_gbp_m, prior_year_development_pct, gross_premium_mix, claims_triangle, rag_triangle, data_quality_notes |
| `syndicate_2121_2022` | 38.4 | 36.2 | deterministic override (note) | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, rag_triangle, data_quality_notes |
| `syndicate_2121_2023` | 24.4 | 24.0 | deterministic override (note) | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, claims_triangle, rag_triangle, data_quality_notes |
| `syndicate_2121_2024` | -8.1 | 29.6 | model | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes, direction |
| `syndicate_218_2015` | 11.244 | -11.244 | model | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes, direction |
| `syndicate_218_2016` | 56.55 | 88.896 | deterministic override (note) | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_218_2017` | -29.643 | -41.916 | deterministic override (note) | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_218_2018` | -90.66 | -116.005 | deterministic override (note) | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_218_2019` | -42.4 | -29.0 | deterministic override (note) | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_218_2020` | -19.9 | -24.5 | deterministic override (note) | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_2232_2014` | -22.5 | -22.5 | model | model_reading (?) | gross_premiums_written_gbp_m, gross_premium_mix, adobe_lob, data_quality_notes |
| `syndicate_2232_2015` | -5.961 | -5.961 | deterministic override (note) | rag_triangle (net) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_2232_2016` | -8.006 | -8.006 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_2232_2017` | 12.763 | 12.763 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_2232_2018` | 1.949 | 1.949 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_2232_2019` | 12.79 | 12.79 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_2232_2020` | 55.227 | 55.227 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_2232_2021` | 7.572 | 7.572 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_2232_2022` | -14.204 | -14.204 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_2232_2023` | -12.667 | -12.667 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_2232_2024` | None | None | model | model | provenance only |
| `syndicate_2243_2014` | -3.3 | -3.3 | model | model_reading (?) | gross_premiums_written_gbp_m, gross_premium_mix, adobe_lob, data_quality_notes |
| `syndicate_2255_2015` | -17.123 | None | deterministic override (note) | model | prior_year_development_gbp_m, prior_year_development_pct, opening_reserves_gbp_m, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes, currency, direction |
| `syndicate_2288_2020` | None | None | model | model | provenance only |
| `syndicate_2288_2021` | None | None | model | model | provenance only |
| `syndicate_2357_2015` | 0.0 | 0.0 | model | zero_opening_reserves (?) | gross_premium_mix, rag_triangle, data_quality_notes |
| `syndicate_2357_2016` | 0.0 | 0.0 | deterministic override (note) | rag_triangle (gross) | opening_reserves_gbp_m, claims_triangle, rag_triangle, data_quality_notes |
| `syndicate_2357_2017` | 0.0 | 0.0 | deterministic override (note) | rag_triangle (gross) | rag_triangle, data_quality_notes |
| `syndicate_2357_2018` | -2.757 | -2.757 | deterministic override (note) | rag_triangle (gross) | rag_triangle, data_quality_notes |
| `syndicate_2357_2019` | 36.245 | 36.245 | model | rag_triangle (gross) | gross_premium_mix, claims_triangle, rag_triangle, data_quality_notes |
| `syndicate_2357_2020` | 31.663 | 31.663 | deterministic override (note) | rag_triangle (gross) | claims_triangle, rag_triangle, data_quality_notes |
| `syndicate_2357_2021` | 2.322 | 2.322 | model | rag_triangle (gross) | rag_triangle, data_quality_notes |
| `syndicate_2357_2022` | 30.736 | 30.736 | deterministic override (note) | rag_triangle (gross) | rag_triangle, data_quality_notes |
| `syndicate_2357_2023` | -72.99 | -72.99 | deterministic override (note) | rag_triangle (gross) | rag_triangle, data_quality_notes |
| `syndicate_2357_2024` | -64.757 | -64.757 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_2358_2022` | None | None | model | model | provenance only |
| `syndicate_2358_2023` | None | None | model | model | provenance only |
| `syndicate_2358_2024` | 6.894 | 6.894 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_2468_2014` | None | 27.7 | model | model_reading (?) | prior_year_development_gbp_m, prior_year_development_pct, opening_reserves_gbp_m, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, adobe_lob, adobe_provisions, data_quality_notes, currency, direction |
| `syndicate_2468_2015` | 32.168 | 32.168 | model | rag_triangle (gross) | gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_2468_2016` | 123.63 | 158.048 | deterministic override (note) | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_2468_2017` | -41.328 | -53.783 | deterministic override (note) | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, opening_reserves_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_2468_2018` | 18.37 | 18.37 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_2468_2019` | 45.776 | 45.776 | model | rag_triangle (gross) | prior_year_development_pct, opening_reserves_gbp_m, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_2468_2020` | 71.205 | 71.205 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_2468_2021` | -61.996 | -61.996 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_2468_2022` | -0.153 | None | deterministic override (note) | model | prior_year_development_gbp_m, prior_year_development_pct, opening_reserves_gbp_m, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes, currency, direction |
| `syndicate_2488_2014` | -103.741 | -103.7 | model | model_reading (?) | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, adobe_lob, data_quality_notes |
| `syndicate_2488_2015` | -57.087 | -57.087 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_2488_2016` | -26.755 | -26.755 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_2488_2017` | -31.728 | -31.728 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_2488_2018` | -42.793 | -42.793 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_2488_2019` | -2.959 | -2.959 | deterministic override (note) | rag_triangle (gross) | gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_2525_2014` | -24.8 | -24.8 | model | model_reading (?) | gross_premium_mix |
| `syndicate_2525_2015` | -5.018 | -5.018 | deterministic override (note) | rag_triangle (gross) | gross_premium_mix, rag_triangle, data_quality_notes |
| `syndicate_2525_2016` | -19.2 | -19.2 | model | model_reading (?) | prior_year_development_pct, gross_premium_mix, rag_triangle, data_quality_notes |
| `syndicate_2525_2017` | -16.817 | -16.817 | deterministic override (note) | rag_triangle (gross) | rag_triangle, data_quality_notes |
| `syndicate_2525_2018` | -10.773 | -10.773 | deterministic override (note) | rag_triangle (gross) | gross_premium_mix, rag_triangle |
| `syndicate_2525_2019` | -18.6 | -18.6 | model | model_reading (?) | prior_year_development_pct, gross_premium_mix, rag_triangle, data_quality_notes |
| `syndicate_2525_2020` | -2.247 | -2.247 | deterministic override (note) | rag_triangle (gross) | rag_triangle, data_quality_notes |
| `syndicate_2525_2021` | -6.244 | -6.244 | deterministic override (note) | rag_triangle (gross) | gross_premium_mix, rag_triangle, data_quality_notes |
| `syndicate_2525_2022` | -2.587 | -2.587 | deterministic override (note) | rag_triangle (gross) | rag_triangle, data_quality_notes |
| `syndicate_2525_2023` | -17.045 | -17.045 | model | rag_triangle (gross) | gross_premium_mix, claims_triangle, rag_triangle, data_quality_notes |
| `syndicate_2525_2024` | None | None | model | model | provenance only |
| `syndicate_2526_2014` | 31.7 | None | model | model | prior_year_development_gbp_m, prior_year_development_pct, opening_reserves_gbp_m, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, data_quality_notes, currency, direction |
| `syndicate_2526_2015` | 37.668 | 37.668 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_2526_2016` | 40.834 | 40.834 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_2526_2017` | -15.079 | -15.079 | deterministic override (note) | rag_triangle (gross) | gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_260_2014` | -1.274 | -1.274 | model | model_reading (?) | gross_premiums_written_gbp_m, gross_premium_mix, adobe_lob, data_quality_notes |
| `syndicate_2623_2014` | None | -149.6 | model | model_reading (?) | prior_year_development_gbp_m, prior_year_development_pct, gross_premium_mix, adobe_lob, data_quality_notes |
| `syndicate_2623_2015` | -177.6 | -177.6 | model | model_reading (?) | gross_premium_mix, claims_triangle, adobe_lob, data_quality_notes |
| `syndicate_2623_2016` | -72.117 | -180.2 | model | model_reading (?) | prior_year_development_gbp_m, prior_year_development_pct, claims_triangle, adobe_lob, data_quality_notes |
| `syndicate_2623_2017` | -31.028 | -176.9 | model | model_reading (?) | prior_year_development_gbp_m, prior_year_development_pct, claims_triangle, adobe_lob, data_quality_notes |
| `syndicate_2623_2018` | -110.0 | -110.0 | model | model_reading (?) | claims_triangle, adobe_lob, data_quality_notes |
| `syndicate_2623_2019` | -15.9 | -7.441 | model | deterministic override (note) | prior_year_development_gbp_m, prior_year_development_pct, adobe_lob, data_quality_notes |
| `syndicate_2623_2020` | 65.868 | 65.868 | deterministic override (note) | deterministic override (note) | claims_triangle, adobe_lob, data_quality_notes |
| `syndicate_2623_2021` | -106.358 | -150.8 | model | model_reading (?) | prior_year_development_gbp_m, prior_year_development_pct, claims_triangle, adobe_lob, data_quality_notes |
| `syndicate_2623_2022` | 126.516 | 126.516 | model | deterministic override (note) | claims_triangle, adobe_lob, data_quality_notes |
| `syndicate_2623_2023` | -472.2 | -472.2 | deterministic override (note) | rag_triangle (gross) | claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_2623_2024` | -182.07 | -182.07 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_2689_2019` | 0.967 | 0.967 | model | rag_triangle (gross) | claims_triangle, rag_triangle, data_quality_notes |
| `syndicate_2689_2020` | 11.224 | 11.224 | model | rag_triangle (gross) | claims_triangle, rag_triangle, data_quality_notes |
| `syndicate_2689_2021` | -8.013 | -8.013 | model | rag_triangle (gross) | rag_triangle, data_quality_notes |
| `syndicate_2689_2022` | 2.438 | 2.438 | model | model_reading (?) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_2689_2023` | 42.378 | 42.378 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_2689_2024` | None | None | model | model | provenance only |
| `syndicate_2786_2018` | 1.552 | 1.552 | deterministic override (note) | rag_triangle (gross) | gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_2786_2019` | 27.719 | 27.719 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_2786_2020` | 13.801 | 13.801 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_2786_2021` | 1.08 | 1.08 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_2786_2022` | -22.96 | -22.96 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_2786_2023` | 1.381 | 1.381 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_2786_2024` | 5.989 | 5.989 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_2791_2014` | -46.836 | -22.8 | deterministic override (note) | model_reading (?) | prior_year_development_gbp_m, prior_year_development_pct, gross_premium_mix, adobe_provisions, data_quality_notes |
| `syndicate_2791_2015` | -141.318 | -141.318 | deterministic override (note) | rag_triangle (gross) | gross_premium_mix, claims_triangle, rag_triangle, data_quality_notes |
| `syndicate_2791_2016` | -6.954 | -6.954 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, data_quality_notes, currency |
| `syndicate_2791_2017` | -11.35 | -11.35 | deterministic override (note) | rag_triangle (gross) | gross_premium_mix, claims_triangle, rag_triangle, data_quality_notes |
| `syndicate_2791_2018` | -9.783 | -9.783 | deterministic override (note) | rag_triangle (gross) | gross_premium_mix, claims_triangle, rag_triangle, data_quality_notes |
| `syndicate_2791_2020` | -9.611 | -9.611 | deterministic override (note) | rag_triangle (net) | gross_premium_mix, claims_triangle, rag_triangle, data_quality_notes |
| `syndicate_2791_2021` | -18.541 | -18.541 | deterministic override (note) | rag_triangle (net) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle |
| `syndicate_2791_2022` | -8.245 | -17.497 | deterministic override (note) | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, gross_premium_mix, claims_triangle, rag_triangle, data_quality_notes |
| `syndicate_2791_2023` | -28.21 | -35.529 | deterministic override (note) | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, gross_premium_mix, claims_triangle, rag_triangle, data_quality_notes |
| `syndicate_2791_2024` | -27.986 | -36.191 | deterministic override (note) | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_2880_2022` | None | None | model | model | provenance only |
| `syndicate_2880_2023` | None | None | model | model | provenance only |
| `syndicate_2880_2024` | None | None | model | model | provenance only |
| `syndicate_2987_2014` | None | None | model | model | provenance only |
| `syndicate_2987_2015` | 33.8 | 33.8 | model | rag_triangle (gross) | claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_2987_2016` | 56.8 | 56.8 | deterministic override (note) | rag_triangle (gross) | claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_2987_2017` | 107.3 | 107.3 | deterministic override (note) | rag_triangle (gross) | claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_2987_2018` | 71.4 | 71.4 | model | rag_triangle (gross) | claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_2987_2019` | -17.8 | -17.8 | deterministic override (note) | rag_triangle (gross) | claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_2987_2020` | 150.3 | 150.3 | model | rag_triangle (gross) | claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_2987_2021` | 42.6 | -88.9 | deterministic override (note) | model_reading (?) | prior_year_development_gbp_m, prior_year_development_pct, claims_triangle, rag_triangle, adobe_lob, data_quality_notes, direction |
| `syndicate_2987_2022` | 157.9 | 157.9 | deterministic override (note) | rag_triangle (gross) | claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_2987_2023` | 234.1 | -23.0 | deterministic override (note) | model_reading (?) | prior_year_development_gbp_m, prior_year_development_pct, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes, direction |
| `syndicate_2987_2024` | 170.224 | 170.224 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_2988_2019` | 4.806 | 4.806 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_2988_2020` | 3.155 | 3.155 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_2988_2021` | 57.9 | 6.6 | model | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_2988_2022` | 62.2 | 0.1 | deterministic override (note) | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_2988_2023` | -2.4 | 4.5 | model | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, rag_triangle, adobe_lob, data_quality_notes, direction |
| `syndicate_2988_2024` | -2.854 | -2.854 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_2999_2014` | -36.411 | -36.411 | model | model_reading (?) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, adobe_lob, data_quality_notes |
| `syndicate_2999_2015` | -12.894 | -12.894 | model | rag_triangle (net) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_2999_2016` | 151.649 | 151.649 | deterministic override (note) | rag_triangle (net) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_2999_2017` | -29.295 | -29.295 | model | rag_triangle (net) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_2999_2018` | 83.185 | 83.185 | deterministic override (note) | rag_triangle (net) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_2999_2019` | 116.5 | 116.5 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_2999_2020` | 113.5 | 113.5 | model | rag_triangle (gross) | prior_year_development_pct, opening_reserves_gbp_m, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes, currency |
| `syndicate_2999_2021` | 166.2 | 166.2 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_2999_2022` | 375.6 | 375.6 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_2999_2023` | 11.4 | 11.4 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes, currency |
| `syndicate_2999_2024` | 140.599 | 140.599 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_3000_2014` | -33.6 | -33.6 | model | model_reading (?) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_3000_2015` | -12.617 | -12.617 | model | rag_triangle (gross) | gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_3000_2016` | -19.13 | -57.6 | model | model_reading (?) | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_3000_2017` | -8.1 | -8.1 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_3000_2018` | -40.938 | 17.88 | model | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes, direction |
| `syndicate_3000_2019` | 18.609 | 18.609 | deterministic override (note) | rag_triangle (gross) | gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_3000_2020` | 24.636 | 24.636 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_3000_2021` | -177.163 | -28.1 | model | model_reading (?) | prior_year_development_gbp_m, prior_year_development_pct, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_3000_2022` | -25.4 | 112.626 | model | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes, direction |
| `syndicate_3000_2023` | -25.271 | -25.271 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_3000_2024` | 136.6 | 136.6 | model | rag_provisions (?) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_3002_2014` | None | None | model | model | provenance only |
| `syndicate_3002_2015` | -0.65 | -1.035 | model | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, gross_premium_mix, claims_triangle, rag_triangle, data_quality_notes |
| `syndicate_3002_2016` | -0.802 | -0.802 | deterministic override (note) | rag_triangle (gross) | gross_premium_mix, rag_triangle, data_quality_notes |
| `syndicate_3002_2017` | -3.3 | -3.3 | model | model_reading (?) | rag_triangle, data_quality_notes |
| `syndicate_3002_2018` | 3.332 | 3.332 | deterministic override (note) | rag_triangle (gross) | gross_premium_mix, rag_triangle, data_quality_notes |
| `syndicate_3002_2019` | -3.1 | -3.1 | model | model_reading (?) | gross_premium_mix, rag_triangle, data_quality_notes |
| `syndicate_3002_2020` | 1.241 | 3.9 | deterministic override (note) | model_reading (?) | prior_year_development_gbp_m, prior_year_development_pct, rag_triangle, data_quality_notes |
| `syndicate_3002_2021` | -11.426 | -11.426 | deterministic override (note) | rag_triangle (gross) | gross_premium_mix, rag_triangle, data_quality_notes |
| `syndicate_3002_2022` | 2.557 | 2.557 | deterministic override (note) | rag_triangle (gross) | gross_premium_mix, rag_triangle, data_quality_notes |
| `syndicate_3002_2023` | -4.0 | -3.058 | model | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, gross_premium_mix, claims_triangle, rag_triangle, data_quality_notes |
| `syndicate_3002_2024` | 7.9 | 7.9 | model | rag_provisions (?) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_3010_2014` | -8.252 | -8.188 | model | model_reading (?) | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, adobe_lob, data_quality_notes |
| `syndicate_3010_2015` | 11.732 | 11.732 | deterministic override (note) | rag_provisions_text (?) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, adobe_lob, data_quality_notes |
| `syndicate_3010_2016` | 15.95 | 15.95 | deterministic override (note) | rag_provisions_text (?) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, adobe_lob, data_quality_notes |
| `syndicate_3010_2017` | 11.676 | -3.3 | model | model_reading (?) | prior_year_development_gbp_m, prior_year_development_pct, gross_premium_mix, claims_triangle, adobe_lob, data_quality_notes, direction |
| `syndicate_3010_2018` | 20.1 | 20.101 | model | model_reading (?) | prior_year_development_gbp_m, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_3010_2019` | 25.5 | 25.459 | model | model_reading (?) | prior_year_development_gbp_m, prior_year_development_pct, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_3010_2020` | 31.4 | 31.375 | model | model_reading (?) | prior_year_development_gbp_m, prior_year_development_pct, gross_premium_mix, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_3010_2021` | 32.9 | 32.945 | model | model_reading (?) | prior_year_development_gbp_m, prior_year_development_pct, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_3010_2022` | 146.6 | 146.569 | model | model_reading (?) | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes, currency |
| `syndicate_3010_2023` | 95.6 | 95.571 | model | model_reading (?) | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_3010_2024` | 137.884 | 137.884 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_308_2015` | -0.3 | -0.3 | model | model_reading (?) | rag_triangle, data_quality_notes |
| `syndicate_308_2016` | -0.8 | 0.2 | model | model_reading (?) | prior_year_development_gbp_m, prior_year_development_pct, claims_triangle, rag_triangle, data_quality_notes, direction |
| `syndicate_308_2017` | 0.8 | 2.4 | model | code_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, opening_reserves_gbp_m, gross_premium_mix, claims_triangle, data_quality_notes |
| `syndicate_308_2018` | -1.6 | -1.6 | model | model_reading (?) | gross_premium_mix, data_quality_notes |
| `syndicate_318_2014` | -40.977 | 45.795 | model | model_reading (?) | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, adobe_lob, data_quality_notes, direction |
| `syndicate_318_2015` | -13.978 | -13.978 | deterministic override (note) | code_triangle (gross) | gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_318_2016` | -13.996 | -13.996 | deterministic override (note) | code_triangle (gross) | gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_318_2017` | -13.025 | -13.025 | deterministic override (note) | code_triangle (gross) | gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_318_2018` | -14.241 | -14.241 | deterministic override (note) | code_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_318_2019` | -3.8 | -3.8 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_318_2020` | -13.0 | -13.0 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_318_2021` | -20.6 | -20.6 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_318_2022` | -1.1 | -1.1 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_318_2023` | -12.2 | -12.2 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_318_2024` | -67.098 | -67.098 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_3210_2014` | -34.49 | -34.49 | model | rag_pl_narrative (?) | gross_premiums_written_gbp_m, gross_premium_mix, adobe_lob, data_quality_notes |
| `syndicate_3210_2015` | -32.926 | -32.926 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes, currency |
| `syndicate_3210_2016` | 7.779 | 7.779 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_3210_2017` | 51.648 | 51.648 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_3210_2018` | None | None | model | model | provenance only |
| `syndicate_3268_2020` | 4.216 | 4.216 | deterministic override (note) | rag_triangle (gross) | gross_premium_mix, rag_triangle, adobe_provisions, data_quality_notes |
| `syndicate_3268_2021` | 1.5 | -0.008 | deterministic override (note) | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, gross_premium_mix, rag_triangle, adobe_provisions, data_quality_notes, direction |
| `syndicate_3330_2014` | -2.6 | None | model | model | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, adobe_lob, data_quality_notes |
| `syndicate_3330_2017` | -0.99 | -0.99 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_3330_2018` | 0.208 | None | model | model | prior_year_development_gbp_m, prior_year_development_pct, opening_reserves_gbp_m, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes, currency, direction |
| `syndicate_3334_2014` | 5.8 | 5.8 | model | rag_yoa_narrative (?) | gross_premiums_written_gbp_m, gross_premium_mix, adobe_lob, data_quality_notes |
| `syndicate_3334_2015` | 6.295 | 6.295 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, adobe_lob, data_quality_notes |
| `syndicate_3334_2016` | 23.23 | 23.23 | model | rag_triangle (gross) | gross_premium_mix, claims_triangle, rag_triangle, data_quality_notes |
| `syndicate_3334_2017` | 5.129 | 5.129 | model | model_reading (?) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes, currency |
| `syndicate_3334_2018` | 55.671 | -37.982 | model | model_reading (?) | prior_year_development_gbp_m, prior_year_development_pct, gross_premium_mix, adobe_lob, data_quality_notes, direction |
| `syndicate_3334_2019` | 28.504 | 28.504 | deterministic override (note) | rag_triangle (gross) | gross_premium_mix, claims_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_33_2014` | None | -140.4 | model | model_reading (?) | prior_year_development_gbp_m, prior_year_development_pct, opening_reserves_gbp_m, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, adobe_lob, adobe_provisions, data_quality_notes, currency, direction |
| `syndicate_33_2015` | -86.114 | -118.31 | deterministic override (note) | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_33_2016` | -72.914 | -72.914 | deterministic override (note) | rag_triangle (gross) | gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_33_2017` | -68.84 | -68.84 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_33_2018` | -90.932 | -90.932 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_33_2019` | 61.038 | 61.038 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_33_2020` | -124.701 | -124.701 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_33_2021` | -223.23 | -223.23 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_33_2022` | -281.129 | -281.129 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_33_2023` | -125.639 | -125.639 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_33_2024` | -54.95 | -54.95 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_3456_2023` | None | None | model | model | provenance only |
| `syndicate_3456_2024` | None | None | model | model | provenance only |
| `syndicate_3500_2015` | 0.937 | None | deterministic override (note) | model | prior_year_development_gbp_m, prior_year_development_pct, opening_reserves_gbp_m, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes, currency, direction |
| `syndicate_3500_2018` | None | 25.157 | model | model_reading (?) | prior_year_development_gbp_m, prior_year_development_pct, opening_reserves_gbp_m, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes, currency, direction |
| `syndicate_3500_2019` | 26.444 | 26.444 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_3500_2021` | 109.086 | 109.086 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_3500_2022` | -291.756 | -291.756 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_3500_2023` | -47.666 | -47.666 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_3622_2014` | None | None | model | model | provenance only |
| `syndicate_3622_2015` | None | None | model | model | data_quality_notes, direction |
| `syndicate_3622_2016` | -1.5614 | -2.4486 | model | model_reading (?) | prior_year_development_gbp_m, prior_year_development_pct, gross_premium_mix, claims_triangle, data_quality_notes |
| `syndicate_3622_2017` | None | None | model | model | claims_triangle, data_quality_notes |
| `syndicate_3622_2018` | None | None | model | model | provenance only |
| `syndicate_3622_2019` | None | 1.1 | model | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, claims_triangle, rag_triangle, data_quality_notes |
| `syndicate_3622_2020` | -0.688 | -0.688 | model | model | claims_triangle, data_quality_notes |
| `syndicate_3622_2021` | -2.333 | -2.333 | model | model | gross_premium_mix, claims_triangle, data_quality_notes |
| `syndicate_3622_2022` | -1.59 | -1.59 | model | model | claims_triangle, data_quality_notes |
| `syndicate_3622_2023` | -1.2857 | -4.8 | model | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, claims_triangle, rag_triangle, data_quality_notes |
| `syndicate_3622_2024` | -6.871 | -6.871 | deterministic override (note) | rag_triangle (gross) | gross_premium_mix, rag_triangle, adobe_provisions, data_quality_notes |
| `syndicate_3623_2014` | -4.6 | -4.6 | model | model_reading (?) | claims_triangle, data_quality_notes |
| `syndicate_3623_2015` | 79.54 | 79.54 | deterministic override (note) | deterministic override (note) | data_quality_notes |
| `syndicate_3623_2016` | 2.6 | 2.6 | model | model_reading (?) | data_quality_notes |
| `syndicate_3623_2017` | 2.721 | 2.721 | deterministic override (note) | deterministic override (note) | gross_premium_mix, claims_triangle |
| `syndicate_3623_2018` | -2.312 | -2.312 | deterministic override (note) | deterministic override (note) | gross_premium_mix, claims_triangle, data_quality_notes |
| `syndicate_3623_2019` | 6.8 | 6.8 | model | model_reading (?) | data_quality_notes |
| `syndicate_3623_2020` | -8.8 | -8.8 | model | model_reading (?) | claims_triangle, adobe_lob, data_quality_notes |
| `syndicate_3623_2021` | -36.9 | -36.9 | model | model_reading (?) | claims_triangle, adobe_lob, data_quality_notes |
| `syndicate_3623_2022` | -8.6 | -8.6 | model | model_reading (?) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, adobe_lob, data_quality_notes |
| `syndicate_3623_2024` | -56.671 | -56.671 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_3624_2014` | None | None | model | model | provenance only |
| `syndicate_3624_2015` | -0.912 | 5.025 | deterministic override (note) | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes, direction |
| `syndicate_3624_2016` | -17.0 | -16.973 | model | model_reading (?) | prior_year_development_gbp_m, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_3624_2017` | -6.0 | -5.977 | model | model_reading (?) | prior_year_development_gbp_m, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_3624_2018` | -21.8 | -21.778 | model | model_reading (?) | prior_year_development_gbp_m, gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_3624_2019` | 84.299 | 84.299 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_3624_2020` | 121.954 | 121.954 | deterministic override (note) | rag_triangle (gross) | gross_premium_mix, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_3624_2021` | -23.921 | -23.921 | deterministic override (note) | rag_triangle (gross) | gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_3624_2022` | 83.186 | 83.186 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_3624_2023` | 74.995 | 74.995 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_3624_2024` | -2.022 | -2.022 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_382_2014` | 0.172 | -0.172 | model | model_reading (?) | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, adobe_lob, data_quality_notes, direction |
| `syndicate_382_2015` | -15.848 | -15.848 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_382_2016` | -50.211 | -50.211 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_382_2017` | 49.14 | 49.14 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_382_2018` | -1.546 | 13.51 | deterministic override (note) | model_reading (?) | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes, direction |
| `syndicate_382_2019` | -22.898 | 173.514 | deterministic override (note) | model_reading (?) | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes, direction |
| `syndicate_382_2020` | 7.3 | 7.269 | model | model_reading (?) | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_382_2021` | 20.409 | -8.554 | deterministic override (note) | model_reading (?) | prior_year_development_gbp_m, prior_year_development_pct, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes, direction |
| `syndicate_382_2022` | 34.169 | 34.169 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_382_2023` | -7.893 | -7.893 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_382_2024` | -16.9 | -16.9 | model | rag_provisions (?) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_386_2014` | 23.233 | 23.233 | model | model_reading (?) | gross_premiums_written_gbp_m, gross_premium_mix, adobe_lob, data_quality_notes |
| `syndicate_386_2015` | -7.197 | -7.197 | deterministic override (note) | rag_triangle (net) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_386_2016` | -10.443 | -10.443 | deterministic override (note) | rag_triangle (net) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_386_2017` | 19.206 | 19.206 | model | rag_triangle (net) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_386_2018` | -15.884 | -15.884 | deterministic override (note) | rag_triangle (net) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_386_2019` | 93.1 | 93.1 | deterministic override (note) | rag_triangle (gross) | gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_386_2020` | 43.9 | 43.9 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_386_2021` | -1.7 | -1.7 | model | rag_triangle (gross) | gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_386_2022` | 103.8 | 103.8 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_386_2023` | 60.4 | 60.4 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_386_2024` | 48.491 | 48.491 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_3902_2017` | None | None | model | model | provenance only |
| `syndicate_3902_2018` | None | 4.3 | model | rag_provisions (?) | prior_year_development_gbp_m, prior_year_development_pct, opening_reserves_gbp_m, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, adobe_provisions, data_quality_notes, currency, direction |
| `syndicate_3902_2019` | -1.2 | -1.2 | model | rag_provisions (?) | gross_premium_mix, claims_triangle, rag_triangle, adobe_provisions, data_quality_notes |
| `syndicate_3902_2020` | -8.2 | -8.2 | model | rag_provisions (?) | claims_triangle, rag_triangle, adobe_provisions, data_quality_notes |
| `syndicate_3902_2021` | -6.5 | -6.5 | model | rag_provisions (?) | claims_triangle, rag_triangle, adobe_provisions, data_quality_notes |
| `syndicate_3902_2022` | -39.0 | -39.0 | model | rag_provisions (?) | gross_premiums_written_gbp_m, gross_premium_mix, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_3902_2023` | -6.5 | -6.5 | model | rag_provisions (?) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_3902_2024` | -12.1 | -12.1 | model | rag_provisions (?) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_4000_2014` | 5.3 | -27.7 | model | model_reading (?) | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, adobe_lob, data_quality_notes, direction |
| `syndicate_4000_2015` | 6.714 | 6.714 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_4000_2016` | 52.527 | 52.527 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_4000_2017` | 18.119 | 18.119 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_4000_2018` | 17.538 | 17.538 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_4000_2019` | 38.404 | 38.404 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_4000_2020` | 62.326 | 62.326 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_4000_2021` | 33.463 | 33.463 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_4000_2022` | -15.0 | -15.0 | model | model_reading (?) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_4000_2023` | -18.865 | -18.865 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_4000_2024` | -3.3 | -3.3 | model | rag_provisions (?) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_4020_2014` | -27.6 | -27.6 | model | model_reading (?) | gross_premium_mix, data_quality_notes |
| `syndicate_4020_2015` | None | None | model | model | provenance only |
| `syndicate_4020_2016` | 18.492 | 25.303 | deterministic override (note) | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, gross_premium_mix, claims_triangle, rag_triangle, data_quality_notes |
| `syndicate_4020_2017` | 17.285 | 21.188 | deterministic override (note) | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, claims_triangle, rag_triangle, data_quality_notes |
| `syndicate_4020_2018` | 54.639 | 43.863 | deterministic override (note) | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, opening_reserves_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, data_quality_notes |
| `syndicate_4020_2019` | -4.0 | -4.0 | model | rag_provisions (?) | gross_premium_mix, claims_triangle, adobe_provisions, data_quality_notes |
| `syndicate_4020_2020` | -8.9 | -8.9 | model | rag_provisions (?) | gross_premium_mix, adobe_provisions, data_quality_notes |
| `syndicate_4020_2021` | -22.6 | -22.6 | model | rag_provisions (?) | prior_year_development_pct, opening_reserves_gbp_m, gross_premium_mix, claims_triangle, adobe_provisions, data_quality_notes |
| `syndicate_4020_2022` | -48.6 | -48.6 | model | rag_provisions (?) | gross_premiums_written_gbp_m, gross_premium_mix, adobe_lob, adobe_provisions |
| `syndicate_4020_2023` | -36.4 | -36.4 | model | rag_provisions (?) | gross_premiums_written_gbp_m, gross_premium_mix, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_4020_2024` | -43.5 | -43.5 | model | rag_provisions (?) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_4141_2014` | 4.1 | 4.1 | model | model_reading (?) | gross_premiums_written_gbp_m, gross_premium_mix, adobe_lob, data_quality_notes |
| `syndicate_4141_2015` | 2.422 | 2.422 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_4141_2016` | 4.277 | 4.277 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_4141_2017` | -13.375 | -13.375 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_4141_2018` | -8.846 | -8.846 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_4141_2019` | 19.889 | 19.889 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_4141_2020` | 17.915 | 17.915 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_4141_2021` | 26.687 | 26.687 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_4141_2022` | -16.697 | -16.697 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_4141_2023` | -14.554 | -14.554 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_4141_2024` | -9.184 | -9.184 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_4242_2014` | None | None | model | model | provenance only |
| `syndicate_4242_2015` | -1.342 | -1.342 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_4242_2016` | -0.083 | -0.083 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_4242_2017` | 0.816 | 0.816 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_4242_2018` | 28.627 | 28.627 | deterministic override (note) | rag_triangle (gross) | gross_premium_mix, claims_triangle, rag_triangle, data_quality_notes |
| `syndicate_4242_2019` | 14.898 | 14.898 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_4242_2020` | 13.147 | 13.147 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_4242_2021` | 9.493 | 9.493 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_4242_2022` | -44.371 | -44.371 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_4242_2023` | -7.19 | -7.19 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_4242_2024` | -260.296 | None | model | model | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_4321_2022` | None | None | model | model | provenance only |
| `syndicate_4321_2023` | None | None | model | model | provenance only |
| `syndicate_435_2014` | None | None | model | model | gross_premiums_written_gbp_m, gross_premium_mix, adobe_lob, data_quality_notes |
| `syndicate_435_2015` | -9.756 | -9.756 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_435_2016` | -44.233 | -44.233 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_435_2017` | -30.689 | -30.689 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_435_2018` | -4.551 | -4.551 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_435_2019` | -56.786 | -56.786 | model | rag_triangle (gross) | gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_435_2020` | -62.278 | -62.278 | model | rag_triangle (gross) | gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_435_2021` | -96.222 | -96.222 | model | rag_triangle (gross) | gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_435_2022` | -43.811 | -43.811 | deterministic override (note) | rag_triangle (gross) | gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_435_2023` | -34.385 | -34.385 | model | rag_triangle (gross) | gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_435_2024` | -73.863 | -73.863 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, currency |
| `syndicate_4444_2014` | -21.933 | -21.933 | model | model_reading (?) | prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, adobe_lob, data_quality_notes |
| `syndicate_4444_2015` | -13.896 | -13.896 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_4444_2016` | -18.882 | 4.362 | model | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes, direction |
| `syndicate_4444_2017` | 118.224 | 118.224 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_4444_2018` | 88.583 | 88.583 | deterministic override (note) | rag_triangle (gross) | gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_4444_2019` | -49.463 | 12.465 | model | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes, direction |
| `syndicate_4444_2020` | 20.059 | -20.059 | model | model_reading (?) | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, adobe_lob, data_quality_notes, direction |
| `syndicate_4444_2021` | 24.866 | -41.7 | deterministic override (note) | model_reading (?) | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, adobe_lob, data_quality_notes, direction |
| `syndicate_4444_2022` | -50.092 | 435.491 | model | code_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, adobe_lob, data_quality_notes, direction |
| `syndicate_4444_2023` | -11.115 | 48.207 | model | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes, currency, direction |
| `syndicate_4444_2024` | -89.1 | -89.1 | model | rag_provisions (?) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_4472_2014` | -36.839 | -36.839 | model | model_reading (?) | adobe_lob, data_quality_notes |
| `syndicate_4472_2015` | -24.3 | -24.3 | deterministic override (note) | rag_triangle (gross) | claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_4472_2016` | 26.1 | 26.1 | model | rag_triangle (gross) | claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_4472_2017` | 95.2 | 95.2 | model | rag_triangle (gross) | gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_4472_2018` | 87.9 | 87.9 | model | rag_triangle (gross) | claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_4472_2019` | 226.2 | 226.2 | deterministic override (note) | rag_triangle (gross) | claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_4472_2020` | 373.3 | 373.3 | model | rag_triangle (gross) | rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_4472_2021` | -166.7 | -498.9 | model | model_reading (?) | prior_year_development_gbp_m, prior_year_development_pct, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_4472_2022` | -1.5 | -1.5 | deterministic override (note) | rag_triangle (gross) | claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_4472_2023` | 249.0 | 249.0 | deterministic override (note) | rag_triangle (gross) | claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_4472_2024` | 216.776 | 216.776 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_44_2014` | None | None | model | model | provenance only |
| `syndicate_44_2015` | -1.249 | -1.249 | model | model_reading (?) | gross_premium_mix, claims_triangle, rag_triangle, data_quality_notes |
| `syndicate_44_2016` | -1.011 | -1.011 | model | rag_triangle (gross) | rag_triangle, data_quality_notes |
| `syndicate_44_2017` | -0.321 | -0.321 | model | rag_triangle (gross) | gross_premium_mix, claims_triangle, rag_triangle, data_quality_notes |
| `syndicate_44_2018` | -1.178 | -1.178 | model | rag_triangle (gross) | gross_premium_mix, rag_triangle, adobe_provisions, data_quality_notes |
| `syndicate_457_2014` | -27.7 | -27.7 | model | model_reading (?) | gross_premiums_written_gbp_m, gross_premium_mix, adobe_lob, data_quality_notes |
| `syndicate_457_2015` | -8.592 | 8.592 | model | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes, direction |
| `syndicate_457_2016` | -40.3 | -31.781 | model | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_457_2017` | 71.388 | -71.388 | model | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes, direction |
| `syndicate_457_2018` | -27.0 | -60.126 | model | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_457_2019` | 65.581 | -65.581 | deterministic override (note) | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes, direction |
| `syndicate_457_2020` | -45.0 | -44.183 | model | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_457_2021` | -68.4 | -80.854 | model | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_457_2022` | -68.297 | -68.771 | model | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_457_2023` | -86.961 | -66.885 | model | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes, currency |
| `syndicate_457_2024` | 11.797 | 11.797 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_4711_2014` | None | None | model | model | gross_premiums_written_gbp_m, gross_premium_mix, adobe_lob, data_quality_notes, direction |
| `syndicate_4711_2015` | -54.854 | -54.854 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_4711_2017` | -11.233 | -11.233 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_4711_2018` | 82.874 | 82.874 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_4711_2019` | 59.303 | 59.303 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_4711_2020` | 12.438 | 12.438 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_4711_2021` | 143.492 | 143.492 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_4711_2022` | 32.612 | 32.612 | deterministic override (note) | rag_triangle (gross) | gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_4711_2023` | 77.144 | 77.144 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_4711_2024` | -78.7 | -78.7 | model | rag_provisions (?) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_4747_2021` | None | None | model | model | provenance only |
| `syndicate_4747_2022` | 2.343 | 2.343 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_4747_2023` | 5.947 | 5.947 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_4747_2024` | None | None | model | model | provenance only |
| `syndicate_5000_2014` | -22.9 | -22.954 | model | model_reading (?) | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, adobe_lob, data_quality_notes |
| `syndicate_5000_2015` | 14.0 | 14.0 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_5000_2016` | -24.0 | -24.0 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_5000_2017` | -183.0 | 25.0 | deterministic override (note) | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes, direction |
| `syndicate_5000_2018` | 38.47 | 38.47 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_5000_2019` | 68.19 | 68.19 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_5000_2020` | 8.4 | 8.4 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_5000_2021` | 24.6 | 24.6 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_5000_2022` | 43.4 | 43.4 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_5000_2023` | 14.7 | 14.7 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_5000_2024` | -7.0 | -7.0 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_510_2014` | -31.4 | -48.4 | deterministic override (note) | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_510_2015` | 0.1 | 0.1 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_510_2016` | 1.8 | 1.8 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_510_2017` | -10.2 | -10.2 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_510_2018` | -7.2 | -7.2 | model | model_reading (?) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_510_2019` | -34.0 | -34.0 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_510_2020` | 13.0 | 20.0 | deterministic override (note) | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_510_2021` | -84.0 | -81.0 | deterministic override (note) | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_510_2022` | -241.0 | -128.0 | deterministic override (note) | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_510_2023` | 171.1 | 135.9 | deterministic override (note) | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_510_2024` | 217.598 | 217.598 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_5151_2014` | -19.8 | -19.8 | model | model_reading (?) | gross_premiums_written_gbp_m, gross_premium_mix, adobe_lob, data_quality_notes |
| `syndicate_5151_2015` | -17.969 | -35.856 | deterministic override (note) | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_5151_2016` | -24.7 | -24.7 | model | model_reading (?) | gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_5151_2017` | -11.492 | -12.014 | deterministic override (note) | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, gross_premium_mix, claims_triangle, rag_triangle, data_quality_notes |
| `syndicate_5151_2018` | -11.1 | -11.1 | model | model_reading (?) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_5151_2019` | 2.1 | 6.185 | model | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_5151_2020` | -5.2 | -5.2 | model | model_reading (?) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_5183_2023` | None | None | model | model | provenance only |
| `syndicate_5183_2024` | None | None | model | model | provenance only |
| `syndicate_557_2014` | -0.7 | -1.5 | model | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, claims_triangle, rag_triangle, data_quality_notes |
| `syndicate_557_2015` | -2.4 | -0.5 | model | model_reading (?) | prior_year_development_gbp_m, prior_year_development_pct, rag_triangle, data_quality_notes |
| `syndicate_557_2016` | -2.0 | -2.0 | model | model_reading (?) | prior_year_development_pct, rag_triangle, data_quality_notes |
| `syndicate_557_2017` | -3.7 | -1.6 | model | code_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, opening_reserves_gbp_m, adobe_lob, data_quality_notes |
| `syndicate_557_2018` | -9.6 | -1.7 | model | model_reading (?) | prior_year_development_gbp_m, prior_year_development_pct, data_quality_notes |
| `syndicate_557_2019` | -5.2 | -2.3 | model | rag_general_narrative (?) | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_557_2020` | -0.4 | -0.4 | model | rag_triangle (gross) | rag_triangle, data_quality_notes |
| `syndicate_557_2021` | -1.3 | -1.2 | model | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, rag_triangle, data_quality_notes |
| `syndicate_557_2022` | -7.257 | -4.5 | model | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, rag_triangle, data_quality_notes |
| `syndicate_5623_2018` | None | None | model | model | provenance only |
| `syndicate_5623_2019` | None | None | model | model | provenance only |
| `syndicate_5623_2020` | None | None | model | model | opening_reserves_gbp_m, claims_triangle, data_quality_notes |
| `syndicate_5623_2021` | -1.7803 | -1.7803 | model | model_reading (?) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, data_quality_notes |
| `syndicate_5623_2022` | -2.8 | -10.0 | model | model_reading (?) | prior_year_development_gbp_m, prior_year_development_pct, claims_triangle, adobe_lob, data_quality_notes |
| `syndicate_5623_2023` | -29.1 | -29.1 | deterministic override (note) | rag_triangle (gross) | claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_5623_2024` | -20.46 | -20.46 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_5678_2014` | -16.2 | -16.2 | model | model_reading (?) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, adobe_lob, data_quality_notes |
| `syndicate_5678_2015` | 0.0 | 5.3 | deterministic override (note) | rag_provisions (?) | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes, direction |
| `syndicate_5678_2016` | 0.861 | 0.861 | deterministic override (note) | rag_triangle (gross) | gross_premium_mix, rag_triangle, adobe_provisions, data_quality_notes |
| `syndicate_5678_2017` | 0.33 | 0.33 | deterministic override (note) | rag_triangle (gross) | gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_5678_2018` | -4.969 | -4.969 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes, currency |
| `syndicate_5678_2019` | 14.148 | 14.148 | deterministic override (note) | rag_triangle (gross) | gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_5820_2014` | -6.471 | -9.4 | model | model_reading (?) | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_5820_2015` | 10.4 | 10.4 | model | rag_triangle (gross) | gross_premium_mix, rag_triangle, data_quality_notes |
| `syndicate_5820_2016` | 11.8 | 38.4 | deterministic override (note) | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_5820_2017` | 9.0 | 6.8 | deterministic override (note) | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_5820_2019` | 21.237 | 21.237 | deterministic override (note) | rag_triangle (gross) | gross_premium_mix, claims_triangle, rag_triangle, data_quality_notes |
| `syndicate_5886_2017` | None | None | model | model | provenance only |
| `syndicate_5886_2018` | None | None | model | model | provenance only |
| `syndicate_5886_2019` | 6.485 | 6.485 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_5886_2020` | -1.552 | -1.552 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_5886_2021` | 6.325 | 6.325 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_5886_2022` | 3.475 | 3.475 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_5886_2023` | 3.894 | 3.894 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_5886_2024` | -1.552 | -1.552 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_6050_2015` | None | None | model | model | provenance only |
| `syndicate_6050_2016` | None | None | model | model | provenance only |
| `syndicate_6050_2017` | None | None | model | model | claims_triangle, data_quality_notes |
| `syndicate_609_2014` | -41.2 | -41.2 | model | model_reading (?) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_609_2015` | -47.968 | -47.968 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_609_2016` | -47.547 | -47.547 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_609_2017` | -70.442 | -70.442 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_609_2018` | -34.13 | -34.13 | deterministic override (note) | rag_triangle (gross) | gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_609_2019` | -45.496 | -45.496 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_609_2020` | -26.598 | -26.598 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes, currency |
| `syndicate_609_2021` | -18.753 | -18.753 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_609_2022` | 11.071 | 11.071 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_609_2023` | 153.241 | 153.241 | deterministic override (note) | rag_triangle (gross) | prior_year_development_pct, opening_reserves_gbp_m, gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_609_2024` | 194.623 | 194.623 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_6103_2014` | -3.891 | None | model | model | prior_year_development_gbp_m, prior_year_development_pct, opening_reserves_gbp_m, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, currency, direction |
| `syndicate_6103_2015` | -0.036 | -0.036 | deterministic override (note) | rag_triangle (gross) | gross_premium_mix, claims_triangle, rag_triangle, data_quality_notes |
| `syndicate_6103_2016` | -0.7 | -0.7 | model | model_reading (?) | gross_premium_mix, data_quality_notes |
| `syndicate_6103_2017` | -0.2 | 0.01 | model | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, gross_premium_mix, claims_triangle, rag_triangle, data_quality_notes, direction |
| `syndicate_6103_2018` | 0.06 | 0.06 | model | rag_triangle (gross) | rag_triangle, data_quality_notes |
| `syndicate_6103_2019` | 0.629 | 0.629 | deterministic override (note) | rag_triangle (gross) | gross_premium_mix, rag_triangle, data_quality_notes |
| `syndicate_6103_2020` | 0.628 | 0.628 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, data_quality_notes, currency |
| `syndicate_6103_2021` | 2.193 | 2.193 | deterministic override (note) | rag_triangle (gross) | rag_triangle, data_quality_notes |
| `syndicate_6103_2022` | 3.313 | 3.313 | deterministic override (note) | rag_triangle (gross) | gross_premium_mix, rag_triangle, data_quality_notes |
| `syndicate_6103_2023` | -1.735 | -1.735 | deterministic override (note) | rag_triangle (gross) | rag_triangle, data_quality_notes |
| `syndicate_6103_2024` | -2.044 | -2.044 | deterministic override (note) | rag_triangle (gross) | rag_triangle, data_quality_notes |
| `syndicate_6104_2014` | -22.6 | -22.6 | model | model_reading (?) | gross_premiums_written_gbp_m, gross_premium_mix, data_quality_notes |
| `syndicate_6104_2015` | -3.092 | -3.686 | deterministic override (note) | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, gross_premium_mix, claims_triangle, rag_triangle, adobe_provisions, data_quality_notes |
| `syndicate_6104_2016` | -2.7 | -2.694 | model | model_reading (?) | prior_year_development_gbp_m, prior_year_development_pct, rag_triangle, adobe_provisions, data_quality_notes |
| `syndicate_6104_2017` | -3.4 | -3.4 | deterministic override (note) | rag_triangle (gross) | claims_triangle, rag_triangle, adobe_provisions, data_quality_notes |
| `syndicate_6104_2018` | -3.489 | -3.489 | deterministic override (note) | rag_triangle (gross) | rag_triangle, adobe_provisions, data_quality_notes |
| `syndicate_6104_2019` | 0.801 | 0.801 | deterministic override (note) | rag_triangle (gross) | rag_triangle, adobe_provisions, data_quality_notes |
| `syndicate_6104_2020` | -6.479 | -6.479 | deterministic override (note) | rag_triangle (gross) | claims_triangle, rag_triangle, adobe_provisions, data_quality_notes |
| `syndicate_6104_2021` | -22.115 | -22.115 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_provisions, data_quality_notes |
| `syndicate_6104_2022` | -9.315 | -9.315 | deterministic override (note) | rag_triangle (gross) | rag_triangle, adobe_provisions, data_quality_notes |
| `syndicate_6104_2023` | -13.374 | -13.374 | deterministic override (note) | rag_triangle (gross) | claims_triangle, rag_triangle, adobe_provisions, data_quality_notes |
| `syndicate_6104_2024` | -16.07 | -16.07 | model | rag_triangle (gross) | gross_premium_mix, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_6105_2014` | -1.0 | -1.0 | model | model_reading (?) | gross_premium_mix, claims_triangle, data_quality_notes |
| `syndicate_6105_2015` | 0.284 | 0.284 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_6107_2014` | -4.103 | -4.103 | model | rag_general_narrative (?) | gross_premium_mix, claims_triangle, data_quality_notes |
| `syndicate_6107_2015` | -4.3 | -4.3 | model | model_reading (?) | gross_premium_mix, data_quality_notes |
| `syndicate_6107_2016` | -11.6 | -11.6 | model | model_reading (?) | gross_premium_mix, claims_triangle, data_quality_notes |
| `syndicate_6107_2017` | -19.2695 | -19.2695 | model | model_reading (?) | prior_year_development_pct, opening_reserves_gbp_m, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, data_quality_notes |
| `syndicate_6107_2018` | -12.1795 | -12.18 | model | model_reading (?) | prior_year_development_gbp_m, gross_premium_mix, claims_triangle, data_quality_notes |
| `syndicate_6107_2019` | None | None | model | model | gross_premium_mix, claims_triangle, data_quality_notes |
| `syndicate_6107_2020` | 2.3603 | None | model | model | prior_year_development_gbp_m, prior_year_development_pct, claims_triangle, data_quality_notes, direction |
| `syndicate_6107_2021` | None | -11.9 | model | model_reading (?) | prior_year_development_gbp_m, gross_premium_mix, claims_triangle, data_quality_notes, direction |
| `syndicate_6107_2022` | -8.545 | -8.545 | deterministic override (note) | deterministic override (note) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, adobe_lob, data_quality_notes |
| `syndicate_6107_2023` | -4.7 | 4.1 | model | model_reading (?) | prior_year_development_gbp_m, prior_year_development_pct, gross_premium_mix, claims_triangle, rag_triangle, data_quality_notes, direction |
| `syndicate_6107_2024` | -0.946 | -0.946 | deterministic override (note) | rag_triangle (gross) | prior_year_development_pct, opening_reserves_gbp_m, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_provisions, data_quality_notes |
| `syndicate_6111_2014` | None | None | model | model | provenance only |
| `syndicate_6111_2015` | 39.043 | 0.0 | deterministic override (note) | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes, direction |
| `syndicate_6111_2016` | 3.599 | 3.599 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_6111_2017` | 19.038 | 19.038 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_6111_2018` | 21.059 | 21.059 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_6112_2014` | None | None | model | model | provenance only |
| `syndicate_6112_2015` | 9.895 | 0.248 | deterministic override (note) | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_6112_2016` | -19.264 | -19.264 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_6113_2014` | None | None | model | model | provenance only |
| `syndicate_6115_2014` | None | None | model | model | provenance only |
| `syndicate_6117_2014` | None | None | model | model | provenance only |
| `syndicate_6117_2015` | -1.8 | -1.8 | model | model_reading (?) | data_quality_notes |
| `syndicate_6117_2016` | 3.07 | 3.07 | deterministic override (note) | rag_triangle (gross) | rag_triangle, data_quality_notes |
| `syndicate_6117_2017` | None | 5.5 | model | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, opening_reserves_gbp_m, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_provisions, data_quality_notes, currency, direction |
| `syndicate_6117_2018` | None | -6.2 | model | model_reading (?) | prior_year_development_gbp_m, prior_year_development_pct, opening_reserves_gbp_m, gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_provisions, data_quality_notes, currency, direction |
| `syndicate_6117_2019` | None | -4.4 | model | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, opening_reserves_gbp_m, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, data_quality_notes, currency, direction |
| `syndicate_6117_2020` | None | -0.8 | model | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, opening_reserves_gbp_m, gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, data_quality_notes, currency, direction |
| `syndicate_6117_2021` | None | -14.0 | model | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, opening_reserves_gbp_m, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, data_quality_notes, currency, direction |
| `syndicate_6117_2022` | -25.7 | -25.7 | model | rag_triangle (gross) | rag_triangle, data_quality_notes |
| `syndicate_6117_2023` | -2.5 | -2.5 | model | rag_triangle (gross) | rag_triangle, data_quality_notes |
| `syndicate_6117_2024` | -5.786 | -5.786 | model | model_reading (?) | prior_year_development_pct, claims_triangle, data_quality_notes |
| `syndicate_6118_2014` | None | None | model | model | gross_premium_mix, claims_triangle, data_quality_notes |
| `syndicate_6118_2015` | 2.287 | 3.61 | deterministic override (note) | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_6118_2016` | 6.256 | 6.256 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_6118_2017` | -25.532 | -25.532 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_6118_2018` | 7.579 | 7.579 | model | rag_triangle (gross) | gross_premium_mix, rag_triangle, adobe_provisions, data_quality_notes |
| `syndicate_6119_2014` | None | None | model | model | provenance only |
| `syndicate_6119_2015` | None | None | model | model | provenance only |
| `syndicate_6119_2016` | -0.2 | 0.69 | model | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes, direction |
| `syndicate_6120_2015` | None | None | model | model | provenance only |
| `syndicate_6121_2015` | None | None | model | model | provenance only |
| `syndicate_6121_2016` | None | None | model | model | provenance only |
| `syndicate_6123_2015` | None | None | model | model | provenance only |
| `syndicate_6123_2016` | None | None | model | model | provenance only |
| `syndicate_6123_2017` | -0.383 | -0.383 | deterministic override (note) | rag_triangle (gross) | rag_triangle, data_quality_notes |
| `syndicate_6123_2018` | 9.135 | 9.135 | model | rag_triangle (gross) | rag_triangle, data_quality_notes |
| `syndicate_6123_2019` | 4.915 | 4.915 | deterministic override (note) | rag_triangle (gross) | gross_premium_mix, rag_triangle, data_quality_notes |
| `syndicate_6124_2015` | None | None | model | model | provenance only |
| `syndicate_6125_2016` | None | None | model | model | provenance only |
| `syndicate_6125_2017` | 3.1 | 3.1 | model | rag_provisions (?) | rag_triangle, adobe_provisions, data_quality_notes |
| `syndicate_6125_2018` | 0.274 | 0.274 | deterministic override (note) | rag_triangle (gross) | rag_triangle, adobe_provisions, data_quality_notes |
| `syndicate_6125_2019` | -0.805 | -0.805 | deterministic override (note) | rag_triangle (gross) | gross_premium_mix, rag_triangle, adobe_provisions, data_quality_notes |
| `syndicate_6125_2020` | 0.9 | 0.934 | model | model_reading (?) | prior_year_development_gbp_m, prior_year_development_pct, rag_triangle, adobe_provisions, data_quality_notes |
| `syndicate_6126_2016` | None | None | model | model | provenance only |
| `syndicate_6126_2017` | None | None | model | model | provenance only |
| `syndicate_6129_2016` | None | None | model | model | provenance only |
| `syndicate_6129_2017` | None | None | model | model | provenance only |
| `syndicate_6129_2018` | None | -6.7 | model | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, opening_reserves_gbp_m, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes, currency, direction |
| `syndicate_6130_2016` | None | None | model | model | provenance only |
| `syndicate_6130_2017` | -0.267 | -0.267 | model | model_reading (?) | prior_year_development_pct, adobe_lob, data_quality_notes |
| `syndicate_6130_2018` | 0.229 | 0.229 | model | model_reading (?) | gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_6131_2018` | None | None | model | model | provenance only |
| `syndicate_6131_2019` | None | None | model | model | provenance only |
| `syndicate_6131_2020` | 1.259 | 1.259 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_6131_2021` | 5.617 | 5.617 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_6132_2018` | None | None | model | model | provenance only |
| `syndicate_6132_2019` | None | None | model | model | provenance only |
| `syndicate_6132_2020` | 0.495 | 0.495 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_6132_2021` | 2.558 | 2.558 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_6133_2018` | 0.0 | None | model | model | prior_year_development_gbp_m, opening_reserves_gbp_m, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, data_quality_notes, currency, direction |
| `syndicate_6133_2019` | -16.145 | -12.197 | model | model_reading (?) | prior_year_development_gbp_m, prior_year_development_pct, gross_premium_mix, data_quality_notes |
| `syndicate_6133_2020` | -2.172 | -2.172 | deterministic override (note) | rag_triangle (gross) | gross_premium_mix, claims_triangle, rag_triangle, data_quality_notes |
| `syndicate_6133_2021` | -2.119 | -2.119 | deterministic override (note) | rag_triangle (gross) | rag_triangle, data_quality_notes |
| `syndicate_6134_2018` | None | None | model | model | provenance only |
| `syndicate_6134_2019` | 3.0 | 3.0 | model | model_reading (?) | gross_premiums_written_gbp_m, gross_premium_mix, adobe_lob, data_quality_notes |
| `syndicate_6134_2020` | 1.505 | 1.505 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_6134_2021` | -3.3 | -3.3 | model | model_reading (?) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_6134_2022` | -3.1 | 11.563 | model | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes, direction |
| `syndicate_6134_2023` | -18.6 | -18.6 | model | model_reading (?) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_6134_2024` | -12.5 | -12.5 | model | model_reading (?) | gross_premium_mix, claims_triangle, rag_triangle, data_quality_notes |
| `syndicate_6136_2023` | None | None | model | model | provenance only |
| `syndicate_623_2014` | -33.9 | -17.3 | model | code_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, claims_triangle, adobe_lob, data_quality_notes |
| `syndicate_623_2015` | -40.3 | -40.3 | model | model_reading (?) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, adobe_lob, data_quality_notes |
| `syndicate_623_2016` | -40.8 | -40.8 | model | model_reading (?) | gross_premium_mix, claims_triangle, data_quality_notes |
| `syndicate_623_2017` | -39.7 | -39.7 | model | model_reading (?) | claims_triangle, adobe_lob |
| `syndicate_623_2018` | -25.1 | -25.1 | model | model_reading (?) | gross_premium_mix, claims_triangle, data_quality_notes |
| `syndicate_623_2019` | 11.0 | -3.7 | model | model_reading (?) | prior_year_development_gbp_m, prior_year_development_pct, gross_premium_mix, claims_triangle, data_quality_notes, direction |
| `syndicate_623_2020` | 0.0 | -16.5 | deterministic override (note) | model_reading (?) | prior_year_development_gbp_m, prior_year_development_pct, claims_triangle, data_quality_notes, direction |
| `syndicate_623_2021` | -33.1 | -33.1 | model | model_reading (?) | gross_premium_mix, claims_triangle, data_quality_notes |
| `syndicate_623_2022` | 27.771 | 27.771 | deterministic override (note) | deterministic override (note) | claims_triangle, adobe_lob, data_quality_notes |
| `syndicate_623_2023` | -103.6 | -103.6 | deterministic override (note) | rag_triangle (gross) | rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_623_2024` | -39.967 | -39.967 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_727_2014` | -16.7 | -16.7 | model | model_reading (?) | gross_premiums_written_gbp_m, gross_premium_mix, adobe_lob, data_quality_notes |
| `syndicate_727_2015` | -5.676 | -5.676 | deterministic override (note) | rag_triangle (gross) | rag_triangle, adobe_provisions, data_quality_notes |
| `syndicate_727_2016` | -7.098 | -7.098 | deterministic override (note) | rag_triangle (gross) | rag_triangle, adobe_provisions, data_quality_notes |
| `syndicate_727_2017` | -16.0 | 2.966 | deterministic override (note) | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes, direction |
| `syndicate_727_2018` | -0.148 | -0.148 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_727_2019` | 6.785 | 6.785 | deterministic override (note) | rag_triangle (gross) | gross_premium_mix, claims_triangle, rag_triangle, data_quality_notes |
| `syndicate_727_2020` | -3.319 | -3.319 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_727_2021` | -10.157 | -10.157 | deterministic override (note) | rag_triangle (gross) | rag_triangle, data_quality_notes |
| `syndicate_727_2022` | -5.836 | -5.836 | deterministic override (note) | rag_triangle (gross) | rag_triangle, data_quality_notes |
| `syndicate_727_2023` | -0.431 | -0.431 | deterministic override (note) | rag_triangle (gross) | gross_premium_mix, claims_triangle, rag_triangle, data_quality_notes |
| `syndicate_727_2024` | 16.599 | 16.599 | deterministic override (note) | rag_triangle (gross) | gross_premium_mix, rag_triangle, data_quality_notes |
| `syndicate_779_2014` | 0.3 | 0.3 | model | model_reading (?) | rag_triangle, data_quality_notes |
| `syndicate_779_2015` | 9.4 | 2.5 | deterministic override (note) | model_reading (?) | prior_year_development_gbp_m, prior_year_development_pct, rag_triangle, adobe_provisions, data_quality_notes |
| `syndicate_779_2016` | 0.7 | 0.7 | model | model_reading (?) | gross_premium_mix, rag_triangle, adobe_provisions, data_quality_notes |
| `syndicate_780_2014` | -0.009 | -0.009 | deterministic override (note) | rag_general_narrative (?) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, adobe_lob, data_quality_notes |
| `syndicate_780_2015` | -20.251 | -20.251 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_780_2016` | -15.6 | -15.6 | model | model_reading (?) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_780_2017` | -1.5 | -1.6 | model | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes |
| `syndicate_780_2018` | 35.2 | -21.3 | model | rag_triangle (gross) | prior_year_development_gbp_m, prior_year_development_pct, gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, adobe_provisions, data_quality_notes, direction |
| `syndicate_780_2019` | -42.395 | -42.395 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_780_2020` | -12.336 | -12.336 | deterministic override (note) | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, rag_triangle, adobe_lob, data_quality_notes |
| `syndicate_958_2014` | -17.295 | -17.295 | model | model_reading (?) | gross_premiums_written_gbp_m, gross_premium_mix, adobe_lob, data_quality_notes |
| `syndicate_958_2015` | -4.935 | -4.935 | model | rag_triangle (gross) | gross_premiums_written_gbp_m, gross_premium_mix, claims_triangle, rag_triangle, adobe_lob, data_quality_notes |

## Stems that could not be replayed offline

These reports' page-level caches are absent or in the superseded format, so the corrected rules could not be applied to them without fresh paid inference. Their committed records stand unchanged, and the driver exits non-zero rather than deleting them.

- `syndicate_1100_2024`
- `syndicate_2357_2014`
- `syndicate_2689_2017`
- `syndicate_2689_2018`
- `syndicate_2786_2016`
- `syndicate_2786_2017`
- `syndicate_2988_2017`
- `syndicate_2988_2018`
- `syndicate_3268_2018`
- `syndicate_3268_2019`

