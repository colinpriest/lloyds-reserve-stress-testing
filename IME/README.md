# IME/ : superseded archival material

> **WARNING: everything in this folder is superseded archival material from an earlier method.**
> The six figures (`figure1_tail_trend.png` to `figure6_local_donor.png`), the five tables
> (`table1_corpus_summary.tex` to `table5_local_donor_sensitivity.tex`), the worked example
> (`appendix_worked_example.tex`) and `local_donor_sensitivity.json` were produced for an earlier
> paper by the earlier line-level projection and power-law mix adjustment. They are **not**
> results of the current paper or of its operator (robust Bayesian pooling of size and
> concentration, Student-t errors, two-regime RITC tail). Do **not** use them, quote them or
> compare them with the current paper's tables and figures as if they described the current method.

## Where the current method and results are

- The current paper, and the analysis repository commit it pins (named in the paper's Data
  Availability Statement).
- The analysis repository: <https://github.com/colinpriest/lloyds-exposure-composition-analysis>
  (see its `docs/current-results.md`).

## Why the files are kept

They are retained as a record of the earlier stage. The generating script is
`IME-paper-table-figures.py` at the repository root; `docs/exposure-adjustment.md` (itself marked
superseded) describes the earlier method.

## Known defect in the historical worked example

`appendix_worked_example.tex` shows uncapped Property severities of 11.50 and 6.13, which become
equal only after both are capped at 5.00. The example's original text said the raw difference was
entirely attributable to mix and that the underlying event severity was identical. That is not
shown by the example: the comparison isolates mix only under the cap. The text has been corrected
in place; no number in it was changed. This is a defect of the historical example, not of the
current operator.

Each `.tex` file starts with a LaTeX comment repeating this archival warning. The `.png` figures
cannot carry one, so this file is their label.
