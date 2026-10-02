# GitHub Repository

https://github.com/colinpriest/lloyds-reserve-stress-testing

- Default branch: `main`
- Clone: `git clone https://github.com/colinpriest/lloyds-reserve-stress-testing.git`

Note: raw syndicate report PDFs/HTML (`syndicate_reports/pdfs/`) are not tracked
in the repository. `python scripts/download_from_xlsx.py` downloads the 1,032 found for the rows
of the workbook `syndicate_reports/Lloyds_Syndicates_2014_2024.xlsx`; the other 33 came from an
earlier collection pass, and neither the workbook nor the ledger holds their source URLs
(README, Quick Start step 1).
All extracted structured data, audit outputs, and the download ledger are tracked
(see the "Data Locations" section of the README).
