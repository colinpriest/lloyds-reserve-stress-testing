"""Round 62 (review of 29 September 2026, MAT-2): a one-column triangle is read for its movement.

From round 56 (b72a995f) until round 62 the structure check scored every one-column triangle 0.00
against the 0.50 the pipeline requires, so `compute_pyd_from_triangle` refused it however complete
it was. The RAG step then found no figure, and the record was written as having no claims
development triangle, with neither model run. Two filings were lost that way, and they are the
corpus's only one-column table triangles:

  * 2468/2022, the extraction guide's own worked example: UW2020, 29,267 -> 28,431 -> 28,278
    (GBP000), -0.153m;
  * 2255/2015: UW2011, 413,254 / 396,398 / 413,058 / 347,848 / 330,725 (GBP000), -17.123m.

Until now the suite tested only the parser on these grids, which admitted them all along. These
tests go through `compute_pyd_from_triangle` and through the RAG step itself, where the record's
status is decided, and they pin each condition of the one-column rule, including the ones that
must still refuse. The multi-column threshold the check was built for (780/2018) is unchanged.

Run:  python -m pytest tests/test_single_cohort_triangles.py -q
"""
import copy
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import table_extraction as te  # noqa: E402
import test_gemini as tg  # noqa: E402
from test_triangle_admissibility import GRID_2468_2022  # noqa: E402

#: syndicate 2255's 2015 filing, table 14 of its cached Azure extraction, verbatim (page 39,
#: "Claims development table (continued)"). One underwriting year, 2011, printed gross and net.
GRID_2255_2015 = [
    ["Underwriting year", "2011 GROSS", "2011 NET"],
    ["", "£'000", "£'000"],
    ["Estimate of cumulative claims incurred:", "", ""],
    ["At end of underwriting year, 31 December 2011", "413,254", "196,833"],
    ["12 months later, 31 December 2012", "396,398", "190,056"],
    ["24 months later, 31 December 2013", "413,058", "179,143"],
    ["36 months later, 31 December 2014", "347,848", "152,523"],
    ["48 months later, 31 December 2015", "330,725", "138,294"],
    ["Current estimate of cumulative claims incurred", "330,725", "138,294"],
    ["Cumulative claims paid", "", ""],
    ["At end of underwriting year, 31 December 2011", "33,574", "23,640"],
    ["12 months later, 31 December 2012", "53,023", "35,432"],
    ["24 months later, 31 December 2013", "62,894", "39,780"],
    ["36 months later, 31 December 2014", "78,512", "44,177"],
    ["48 months later, 31 December 2015", "85,434", "47,030"],
    ["Cumulative payments to date", "85,434", "47,030"],
    ["Outstanding claims provision at 31 December 2015 at original exchange rates", "245,291", "91,264"],
    ["Foreign exchange adjustment", "5", "0"],
    ["Total outstanding claims provision per the statement of financial position", "245,286", "91,264"],
    ["% Surplus of initial reserve", "20%", "29.7%"],
]


def _parsed(grid, year):
    res, details = te._parse_nutrient_triangle(grid, year)
    assert isinstance(res, te.TriangleData), details
    return res


# ------------------------------------------------------------ the two filings, end to end

@pytest.mark.parametrize("grid,year,uw,figure", [
    (GRID_2468_2022, 2022, [2020], -0.153),
    (GRID_2255_2015, 2015, [2011], -17.123),
])
def test_the_filings_figure_is_computed_from_its_one_column_triangle(grid, year, uw, figure):
    tri = _parsed(grid, year)
    assert [int(y) for y in tri.underwriting_years] == uw
    assert tri.type == "gross"
    pyd, details = tg.compute_pyd_from_triangle(tri.to_dict(), year)
    assert pyd == pytest.approx(figure, abs=5e-4), details
    assert "Structure score: 1.00" in details


@pytest.fixture
def rag_step(monkeypatch):
    """extract_pyd_from_relevant_pages with the table step returning the given triangle and no
    other input: no text pages, no provisions, no reserve text. What the step reports is then
    decided by the triangle alone."""
    def run(tri, year):
        monkeypatch.setattr(tg, "extract_tables", lambda *a, **k: te.ExtractionResult(
            triangle=copy.deepcopy(tri), method="azure", relevant_pages=[21]))
        monkeypatch.setattr(tg, "extract_text_from_pdf", lambda p: ([], "none"))
        return tg.extract_pyd_from_relevant_pages(Path("syndicate_2468_2022.pdf"), year)
    return run


def test_the_rag_step_reports_the_figure_and_not_an_absent_triangle(rag_step):
    """The level at which the record's status is decided: a figure, from the triangle, so the
    models run -- not no_triangle_data, which skips them."""
    r = rag_step(_parsed(GRID_2468_2022, 2022), 2022)
    assert r["pyd"] == pytest.approx(-0.153, abs=5e-4)
    assert r["pyd_from_triangle"] is True and r["method"] == "azure"
    assert r["no_triangle_data"] is False and r["first_year_syndicate"] is False
    assert r["triangle"]["underwriting_years"] == [2020]


def test_a_models_own_one_column_triangle_is_computed_too():
    """verify_triangles scores the models' triangles with the same function: a one-column
    triangle that fills a blank model value is applied, as a multi-column one would be."""
    tri = {"type": "gross", "units": "thousands", "underwriting_years": [2020],
           "development_rows": [[29267], [28431], [28278]]}
    g = {"prior_year_development_gbp_m": None, "opening_reserves_gbp_m": 312.493, "_claims_triangle": tri}
    o = {"prior_year_development_gbp_m": None, "opening_reserves_gbp_m": 312.493,
         "_claims_triangle": {"type": "none"}}
    rg, ro, _msgs = tg.verify_triangles(g, o, "gemini-2.5-flash", "gpt-5-mini", 2022)
    for r in (rg, ro):
        assert r["prior_year_development_gbp_m"] == pytest.approx(-0.153, abs=5e-4)
        assert r["_pyd_route"]["source"] == "code_triangle"


# ------------------------------------------------------------ each condition of the rule

ROWS_2468 = [[29267.0], [28431.0], [28278.0]]


def test_a_full_usable_column_scores_one():
    assert tg._validate_triangle_structure([2020], copy.deepcopy(ROWS_2468), 2022) == 1.0


def test_a_cohort_too_recent_for_a_previous_diagonal_scores_zero():
    # the same column in a 2021 report: 2020 > 2021 - PYD_EXCLUDED_RECENT_UW_YEARS
    assert tg._validate_triangle_structure([2020], [[29267.0], [28431.0]], 2021) == 0.0


def test_a_column_short_of_its_own_age_scores_zero():
    """Two rows for a cohort three years old: the last value is not the report-year diagonal,
    and differencing it would give an earlier year's movement."""
    assert tg._validate_triangle_structure([2020], [[29267.0], [28431.0]], 2022) == 0.0
    pyd, details = tg.compute_pyd_from_triangle(
        {"type": "gross", "units": "thousands", "underwriting_years": [2020],
         "development_rows": [[29267.0], [28431.0]]}, 2022)
    assert pyd is None and "structure score 0.00" in details


def test_a_column_deeper_than_its_own_age_scores_zero():
    """A fourth value for a three-year-old cohort is not an estimate (a summary row read as a
    development row): differencing it against the one above would give zero."""
    rows = copy.deepcopy(ROWS_2468) + [[28278.0]]
    assert tg._validate_triangle_structure([2020], rows, 2022) == 0.0


def test_a_missing_previous_diagonal_scores_zero():
    """With no value above the last one there is nothing to difference against; scored 1.0 the
    column would reach compute's 'no usable UW years', which the table route reads as a young
    syndicate."""
    assert tg._validate_triangle_structure([2020], [[29267.0], [None], [28278.0]], 2022) == 0.0


def test_a_single_filled_row_scores_zero():
    assert tg._validate_triangle_structure([2020], [[None], [None], [28278.0]], 2022) == 0.0


def test_a_leading_zero_estimate_still_scores_zero():
    """R139's check applies to one column too: no filing estimates nil incurred claims at the end
    of the underwriting year."""
    assert tg._validate_triangle_structure([2020], [[0.0], [28431.0], [28278.0]], 2022) == 0.0


def test_a_label_that_is_not_a_year_scores_zero():
    assert tg._validate_triangle_structure(["2020 & prior"], copy.deepcopy(ROWS_2468), 2022) == 0.0


def test_the_multi_column_threshold_is_unchanged():
    """The grids the threshold was built to refuse are multi-column (780/2018 at 0.38): a
    rectangle where a staircase belongs still scores below it and is still refused."""
    years = [2014, 2015, 2016, 2017, 2018]
    rows = [[100.0 + 10 * c + r for c in range(5)] for r in range(5)]   # every cell filled
    score = tg._validate_triangle_structure(years, copy.deepcopy(rows), 2018)
    assert score == pytest.approx(0.4)          # columns aged 5, 4 fit within one; 3, 2, 1 do not
    assert score < tg.MIN_TRIANGLE_STRUCTURE_SCORE
    pyd, details = tg.compute_pyd_from_triangle(
        {"type": "gross", "units": "millions", "units_evidence": "header",
         "underwriting_years": years, "development_rows": rows}, 2018)
    assert pyd is None and "below the 0.50" in details
    # and a genuine staircase still scores one
    stair = [[100.0, 110.0, 120.0], [101.0, 111.0, None], [102.0, None, None]]
    assert tg._validate_triangle_structure([2016, 2017, 2018], stair, 2018) == 1.0


NUMBER_WORDS = {2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight"}


def test_the_documented_counts_of_the_models_triangles_are_the_scripts():
    """Verification review of round 62, item 5: docs 9.6 said "of the models' own 1,596 triangles
    two change", counted by a script that was never committed, and a recount of the same records
    found 1,547. Both were right about different things: 1,596 model blocks carry a claims triangle,
    1,547 of them with development rows. scripts/count_model_triangles.py counts both, in the
    records before round 62 (11b1bc36, read from git) and in the records now, and measures the
    one-column rule on them; the section's numbers and names are its output."""
    sys.path.insert(0, str(ROOT / "scripts"))
    import count_model_triangles as cmt
    doc = (ROOT / "docs" / "ocr-pipeline.md").read_text(encoding="utf-8").replace("\r\n", "\n")
    section = " ".join(doc[doc.index("\n### 9.6 "):doc.index("\n### 9.7 ")].split())
    then, now = cmt.count(cmt.records_at("11b1bc36")), cmt.count(cmt.records_in_tree())
    assert ("%s blocks carry a claims triangle, %s of them with development rows and %s with one column"
            % (format(then["claims_triangles"], ","), format(then["claims_triangles_with_development_rows"], ","),
               NUMBER_WORDS[len(then["one_column"])])) in section
    changed = sorted({r["record"] for r in then["figure_changed_by_the_one_column_rule"]})
    assert changed == ["syndicate_1206_2019", "syndicate_5820_2019"]
    assert "the figure changes for %s" % NUMBER_WORDS[len(changed)] in section
    for stem in [s.split()[0] for s in then["one_column"]]:
        assert "%s/%s" % tuple(stem.split("_")[1:]) in section, stem
    assert ("%s hold development rows and %s have one column"
            % (format(now["claims_triangles_with_development_rows"], ","), NUMBER_WORDS[len(now["one_column"])])
            ) in section
    new = sorted({s.split()[0] for s in now["one_column"]} - {s.split()[0] for s in then["one_column"]})
    assert new == ["syndicate_2255_2015", "syndicate_2468_2022"]
    for stem in new:
        assert "%s/%s" % tuple(stem.split("_")[1:]) in section, stem
