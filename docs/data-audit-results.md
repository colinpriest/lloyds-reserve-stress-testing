# Data Audit Results — Syndicate-Year Coverage

> **Status: historical snapshot (6 July 2026).**
> The totals and RITC scan below were not regenerated after later extraction and
> classification changes. Do not use this page as the current construction record.
> Current machine-generated counts, populations and provenance are in
> `syndicate_reports/coverage/coverage_report.md` and its companion
> `coverage_status.json` / `.xlsx`; rebuild them with
> `python scripts/build_coverage_status.py`.

Audit date: 2026-07-06 (historical; superseded by the generated coverage report)
Retrieval denominator: `syndicate_reports/Lloyds_Syndicates_2014_2024.xlsx` (1,125 rows, 2014–2024). This is the broader **year-of-account candidate list**, not the active-market denominator. That is **1,045** active syndicate-years: 572 for 2014–2019 from the workbook's SFCR column and 473 for 2020–2024 from Lloyd's official lists of active syndicates (the workbook's per-year sheets). The workbook's own note directs use of its SFCR column, which totals 972; the active-market denominator follows it for 2014–2019 only. (Corrected on 2 October 2026: this line gave the analysis's count from before Syndicate 33 was restored to the 2020–2024 lists, and attributed it to the SFCR column.) The coverage percentages below are against the 1,125 candidate rows.
Machine-readable detail: `syndicate_reports/coverage/coverage_status.xlsx` / `.json`
Rebuild with: `python scripts/build_coverage_status.py`

## Definitions

A syndicate-year is **fully successful** when all four of the following succeeded:

- **(a)** report downloaded
- **(b)** gross prior-year development (PYD) extracted
- **(c)** gross LoB mix extracted
- **(d)** gross opening claims reserves extracted

RITC occurrence is reported alongside but is not part of the full-success definition.
Every extracted value in `coverage_status.xlsx` carries the name of the table or
section it was sourced from (e.g. *"Claims development table (gross), '17. Claims
development tables', p.36 — computed from triangle diagonals"*).

## Global reconciliation

| Step | Change | Running total |
|---|---:|---:|
| Rows in spreadsheet (year-of-account candidate list, not the active denominator) | | 1,125 |
| Less: report unavailable (not published online / download failed) | −93 | 1,032 |
| Reports downloaded | | 1,032 |
| Less: not yet through extraction pipeline | 0 | 1,032 |
| Less: first/second-year syndicate (no PYD possible) | −72 | 960 |
| Less: no claims triangle or reserve text in report | −68 | 892 |
| Less: other field failures (PYD/LoB/opening not all extracted) | −45 | 847 |
| **Fully successful syndicate-years (a+b+c+d)** | | **847 (75.3%)** |

## By year: candidate-list rows vs full success, with failure modes

The **Candidates** column counts rows of the year-of-account candidate list (1,125 in total), not active syndicate-years. The active-market denominator is **1,045** (see above).

| Year | Candidates | Downloaded | Unavailable | PYD ok | LoB ok | Opening ok | **Full success** | fail: PYD | fail: LoB | fail: opening | 1st-yr excl | no-triangle excl | RITC occurred |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2014 | 105 | 94 | 11 | 53 | 78 | 60 | **52** | 41 | 16 | 34 | 4 | 28 | 8 |
| 2015 | 110 | 101 | 9 | 89 | 96 | 83 | **82** | 12 | 5 | 18 | 9 | 2 | 7 |
| 2016 | 112 | 97 | 15 | 86 | 92 | 86 | **85** | 11 | 5 | 11 | 5 | 5 | 9 |
| 2017 | 108 | 96 | 12 | 85 | 90 | 86 | **84** | 11 | 6 | 10 | 6 | 3 | 12 |
| 2018 | 112 | 103 | 9 | 85 | 92 | 82 | **81** | 18 | 11 | 21 | 8 | 9 | 14 |
| 2019 | 105 | 95 | 10 | 80 | 88 | 82 | **78** | 15 | 7 | 13 | 9 | 2 | 17 |
| 2020 | 98 | 87 | 11 | 77 | 81 | 80 | **77** | 10 | 6 | 7 | 5 | 2 | 16 |
| 2021 | 92 | 88 | 4 | 77 | 82 | 78 | **76** | 11 | 6 | 10 | 7 | 1 | 18 |
| 2022 | 93 | 89 | 4 | 76 | 84 | 77 | **76** | 13 | 5 | 12 | 9 | 2 | 19 |
| 2023 | 95 | 91 | 4 | 78 | 88 | 80 | **78** | 13 | 3 | 11 | 9 | 2 | 15 |
| 2024 | 95 | 91 | 4 | 78 | 80 | 78 | **78** | 13 | 11 | 13 | 1 | 12 | 14 |
| **Total** | **1,125** | **1,032** | **93** | **864** | **951** | **872** | **847** | | | | **72** | **68** | **162** |

Failure-mode columns count downloaded reports only; a report can fail more than one
field, so failure modes do not sum to (downloaded − full success). The per-syndicate
equivalent of this table (across all ~180 syndicates) is the `by_syndicate` sheet of
`coverage_status.xlsx`.

## Download audit

- 1,032 / 1,125 downloaded (91.7%). Per-row status, resolved source URL, and failure
  reason are in `syndicate_reports/download_status.json`.
- The 93 unavailable syndicate-years are concentrated: syndicates **566, 626, 1036,
  1886, 2122, 4473** have no reports on the Lloyd's site for *any* year (7 each),
  and **1955, 5555, 218, 2084** account for most of the rest. These appear never to
  have been published in the online archive; the pre-2014 request route
  (lloyds-mrd-returnqueries@lloyds.com) may cover some.
- Unavailability is flat across years (4–15 per year), i.e. not a recency problem.

## Extraction audit

- 1,065 extraction JSONs (`pdf_extraction/syndicate_{N}_{YYYY}.json`), one per
  filing. That is 33 more than the 1,032 downloads recorded above. No downloaded
  record lacks an extraction.
- The 33 are not rows of the workbook, so `syndicate_reports/download_status.json`
  has no row for them, and never had one. (`already_present` is the detail of 588
  rows the ledger records as downloaded: files already on disk when the downloader
  ran.) They are 1100/2024, 1110/2018, 1110/2020, 1110/2021, 1110/2023, 1110/2024,
  1206/2018, 1206/2019, 1209/2016, 1209/2017, 1400/2014, 1400/2015, 1840/2023,
  1840/2024, 1861/2021, 1861/2022, 1882/2017, 1882/2018, 1884/2019, 1884/2020,
  1884/2022, 1884/2023, 1884/2024, 2007/2019, 2243/2014, 2468/2021, 2468/2022,
  2526/2017, 3210/2017, 3210/2018, 5820/2019, 780/2019 and 780/2020. Their records
  were committed between 12 and 19 March 2026, before
  `scripts/download_from_xlsx.py` existed (6 July 2026). They were collected by the
  earlier pass with `scripts/lloyds_scraper.py` (the review of 2 October 2026 found them
  in its local, uncommitted `syndicate_reports/metadata/reports.json`). Neither the workbook nor the
  ledger holds their source URLs, so the documented re-download route does not
  reproduce them. (A Lloyd's URL for three of them, 1206/2019, 1400/2015 and
  2243/2014, appears in `market_commentary/discovered_sources.json`.) Their file
  fingerprints (size and SHA-256) and, where one was found, their source addresses
  are in `syndicate_reports/download_addendum.json`, which
  `scripts/build_download_addendum.py` builds from a re-fetch of 2 October 2026 with
  `scripts/lloyds_scraper.py`. The scraper found an address for 17 of the 33, and the
  file Lloyd's serves at the address is, byte for byte, the corpus copy for 17 of
  them; it differs for 0. (3210/2018 is one of the 17 since its replacement,
  below.) It found no address for the other 16. The corpus copy of
  3210/2018 was replaced on 2 October 2026: its earlier copy (8,380,416 bytes, which
  opened with no page) was a cut-short download of Lloyd's file, and the list keeps
  that copy's size and SHA-256 as `earlier_copy`. By the run-off corpus register
  (`pdf_extraction/audit/runoff_corpus_register.json`), 29 of them
  are run-off years (28 WHOLE, 1 PART: 1110/2024); 1884/2023 and 1884/2024 are
  NOTCOUNT; 1110/2023 was reviewed and states no run-off; 1100/2024 has no entry.
  (3210/2018 is a scan: its run-off reading is from local OCR text, as README item 9
  says.) The coverage report reconciles
  the 1,125 workbook rows (1,032 downloaded), not the 1,065 filings. (Corrected on 2
  October 2026. This item said the ledger flagged the 33 as already present, and
  called the difference a gap of 3.1% in the ledger's completeness.)
- PYD provenance hierarchy: deterministic absolute-amount claims-development-triangle
  computation (ordinarily authoritative and overriding LLMs -- but where the gross
  provisions movement disagrees with it in sign, provisions overrides the triangle)
  → a managed- or group-level loss-ratio triangle, which fills a blank narrative
  value and overrides a syndicate-specific one only where their directions
  contradict → claims-provisions movement note → dual-LLM cross-validated text
  extraction; on every deterministic route the figure is vetoed where the two
  models agree on the opposite sign, or where it exceeds 50% of opening reserves
  while both model movements are below 10%, unless it is the figure two readings of
  the filing confirmed (`pdf_extraction/audit/triangle_figures_confirmed_by_hand.json`),
  which is applied over that veto for that record and that figure only. The canonical
  numbered rule is `ocr-pipeline.md` section 10.3. The chosen source for each value
  is named in the
  coverage table.
- Dual-LLM validation (Gemini + GPT; a numeric field is flagged where the two readings
  differ by more than 0.5% of the larger **and** by more than 0.05 in absolute terms,
  `check_tolerance` in `test_gemini.py`; see the README for the exempt fields):
  in the two extraction runs covering the 372 newly added reports, 337 passed
  validation and 35 passed with unresolved cross-LLM discrepancies (logged in
  `pdf_extraction/audit/disagreement_log.json`; adjudicate with `adjudicate.py`).
- Exclusion classes: 72 first/second-year syndicate-years (premiums still earning
  through — PYD undefined) and 68 with no claims triangle and no reserve movement
  text (mostly run-off years and scanned 2014 reports).
- 2014 is the weakest year (52/105 fully successful): scanned, image-only PDFs
  defeat both the table APIs and the text-based triangle parser most often there.

## RITC audit

Scanner: `scripts/ritc_scanner.py`, results in `pdf_extraction/ritc_scan.json`.
Detects **external** RITC (acceptance of another syndicate's / year of account's
liabilities — the case that distorts PYD). Routine inter-YOA closure of a
syndicate's own years and accounting-policy boilerplate are excluded.

| Result | Count |
|---|---:|
| External RITC occurred — strong confidence | 88 |
| External RITC occurred — weak confidence (flagged for review) | 74 |
| No external RITC | 900 |
| Detection failed (no text layer, never OCR'd) | 3 |

Each occurrence records the evidence snippet, the note/section heading (e.g.
*"17. Related Parties"*), and the page number.

## Known caveats

1. **Weak-confidence RITC flags** (74) matched amount-adjacent RITC wording outside
   recognised transaction phrasing — worth manual review before use as a modelling
   exclusion flag.
2. **LLM-cited page numbers**: where a value came from LLM text extraction (not a
   deterministic table), the page number is as cited by the LLM and labelled
   "(LLM-cited page)" in the source string.
3. **35 unresolved cross-LLM discrepancies** remain adjudicable; resolving them can
   recover part of the 45 "other field failures" in the waterfall.
4. **3 reports** could not be scanned for RITC (no text layer and excluded from the
   extraction pipeline before OCR ran).
