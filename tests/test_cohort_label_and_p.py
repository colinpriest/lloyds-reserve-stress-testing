"""P-31 (review of 2 October 2026, R5-F6): "2010&P" is an aggregated older cohort.

Syndicate 2007 labels its cohort through 2010 "2010&P" (2007/2016, 2007/2017). `_COHORT_HEADER` asked for "prior",
"before" or "earlier" after the connector, so the column was dropped and the stored triangles start at 2011. The
column develops by calendar year (row k is the end of 2010 + k), so under the report-year diagonal (M-1) its step in
2016 is six-years-later 1,716.6 less five-years-later 1,723.1, and in 2017 seven-years-later 1,632.1 less 1,654.6.
The review recomputed 2007/2016 +61.3 -> +54.8 and 2007/2017 -22.0 -> -44.5.

Run:  python -m pytest tests/test_cohort_label_and_p.py -q
"""
import io
import json
import os
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import table_extraction as te  # noqa: E402
import test_gemini as tg  # noqa: E402

AZURE = ROOT / "pdf_extraction" / "azure_output"


@pytest.mark.parametrize("label", ["2010&P", "2010&P £m", "2010 & P", "2010+P", "2010 & prior", "2010 and prior",
                                   "2010 & Prior years", "2010 and earlier"])
def test_every_spelling_names_the_cohort_through_2010(label):
    m = te._COHORT_HEADER.search(label)
    assert m and m.group("through") == "2010", label


@pytest.mark.parametrize("label", ["2015 & P&L", "2015 & PY", "2016"])
def test_a_label_that_is_not_a_cohort_is_not_read_as_one(label):
    m = te._COHORT_HEADER.search(label)
    assert not (m and m.group("through")), label


def _grid(stem, index):
    path = AZURE / ("%s_azure.json" % stem)
    assert path.exists(), "the committed cache for %s is missing; this test proves nothing without it" % stem
    return json.load(io.open(path, encoding="utf-8"))["tables"][index]["grid"]


CASES = [
    # stem, the cached table the stored triangle came from, the cohort's report-year and previous cells, the figure
    ("syndicate_2007_2016", 9, 1716.6, 1723.1, 54.8),
    ("syndicate_2007_2017", 6, 1632.1, 1654.6, -44.5),
]


@pytest.mark.parametrize("stem,index,current,previous,figure", CASES, ids=[c[0] for c in CASES])
def test_the_2010_and_p_column_is_the_2010_cohort_and_enters_the_figure(stem, index, current, previous, figure):
    year = int(stem.rsplit("_", 1)[1])
    grid = _grid(stem, index)
    assert str(grid[0][1]).startswith("2010&P"), "not the table this case is about: %r" % grid[0][1]
    tri, details = te._parse_nutrient_triangle(grid, year)
    assert isinstance(tri, te.TriangleData), details
    d = tri.to_dict()
    assert d.get("aggregated_cohort", {}).get("anchor") == 2010, d.get("aggregated_cohort")
    assert d["underwriting_years"][0] == 2010, d["underwriting_years"]
    col = [r[0] for r in d["development_rows"]]
    e = year - 2010
    assert col[e] == pytest.approx(current) and col[e - 1] == pytest.approx(previous), col
    pyd, why = tg.compute_pyd_from_triangle(d, year)
    assert pyd == pytest.approx(figure, abs=0.001), why


def test_the_stored_triangles_are_these_tables_without_the_cohort():
    """The records hold the 2011-onward reading of the same tables, and its figure, until they are regenerated."""
    for stem, index, _, _, _ in CASES:
        with io.open(ROOT / "pdf_extraction" / ("%s.json" % stem), encoding="utf-8") as fh:
            rec = json.load(fh)
        stored = next(b["_rag_triangle"] for b in rec["models"].values() if b.get("_rag_triangle"))
        year = int(stem.rsplit("_", 1)[1])
        tri, _ = te._parse_nutrient_triangle(_grid(stem, index), year)
        d = tri.to_dict()
        assert stored["underwriting_years"] == d["underwriting_years"][1:]
        # the single years' cells are the stored ones; the cohort alone reaches the deepest row
        rows = [r[1:] for r in d["development_rows"]]
        while rows and all(v is None for v in rows[-1]):
            rows.pop()
        assert rows == stored["development_rows"]


_YEAR_THEN_P = re.compile(r"\b(?:19|20)\d\d\s*(?:&|and|\+)\s*p", re.I)


def test_every_committed_header_cell_of_a_year_and_prior_is_read_as_a_cohort():
    """The generalised check: over every committed triangle grid, each header cell that prints a year, a
    connector and a word for the earlier years ("& prior", "and prior", "&P") is a cohort label."""
    seen, missed = 0, []
    for path in sorted(AZURE.glob("syndicate_*_azure.json")):
        cache = json.load(io.open(path, encoding="utf-8"))
        if not isinstance(cache, dict):
            continue
        for i, t in enumerate(cache.get("tables", [])):
            if "claims_triangle" not in (t.get("categories") or []):
                continue
            for row in (t.get("grid") or [])[:3]:
                for cell in row[1:]:
                    if _YEAR_THEN_P.search(str(cell)):
                        seen += 1
                        if not te._COHORT_HEADER.search(str(cell)):
                            missed.append((path.name, i, cell))
    assert seen >= 300, "only %d cohort header cells found: the scan has stopped seeing them" % seen
    assert not missed, missed
