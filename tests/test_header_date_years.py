"""Round 62: a year that completes a printed date in a data column's header is not a cohort.

3330/2018 prints its net claims development table under the title "Net claims development as at
31 December 2018", and Azure merged the end of the title into the first cohort's header cell:
"December 2018\\n2011". The parser read the cell as two cohorts, 2018 and 2011, and assigned them
to consecutive columns, so every column of the table shifted: 2011 and 2012 both took the 2012
column and 2018 took 2011's. Its row label says "gross" (the filing's own wording under the net
title), and with more filled cells than the real gross table the misread grid won the page. The
RAG step then reported +0.208m -- twice UW2012's net step -- where the filing's gross development
is (57,009 - 58,573) + (11,909 - 11,729) = -1.384m.

The repair reads a date's year as the table's date only in a data column holding exactly one other
year. In the label column the first year of a merged header row stands in for the label column
itself, and the parser's column offsets depend on it (609/2018, 5820/2019): those grids parse as
before. Measured over all 23,175 cached Azure grids, the parse of this one grid changes and no
other.

Run:  python -m pytest tests/test_header_date_years.py -q
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import table_extraction as te  # noqa: E402
import test_gemini as tg  # noqa: E402

#: 3330/2018, cached Azure tables 12 (gross) and 13 (net), verbatim; the pound sign as the cache
#: holds it is immaterial to the parse
GRID_3330_2018_GROSS = [
    ["Pure Underwriting year", "2011", "2012", "2018", "Total"],
    ["Estimate of gross claims incurred", "£000", "£000", "£000", "£000"],
    ["After one year", "62,882", "18,836", "244,154", ""],
    ["After two years", "54,217", "13,480", "", ""],
    ["After three years", "60,179", "10,264", "", ""],
    ["After four years", "65,409", "9,568", "", ""],
    ["After five years", "58,422", "11,719", "", ""],
    ["After six years", "59,652", "11,729", "", ""],
    ["After seven years", "58,573", "11,909", "", ""],
    ["After eight years", "57,009", "", "", ""],
    ["Less gross claims paid", "48,247", "9,191", "215,437", ""],
    ["Gross reserves", "8,762", "2,718", "28,717", "40,197"],
]
GRID_3330_2018_NET = [
    ["Net claims development as at 31\nPure Underwriting year", "December 2018\n2011", "2012", "2018", "Total"],
    ["Estimate of gross claims incurred", "£000", "£000", "£000", "£000"],
    ["After one year", "44,695", "15,597", "224,383", ""],
    ["After two years", "38,620", "10,917", "", ""],
    ["After three years", "44,971", "7,426", "", ""],
    ["After four years", "50,751", "7,105", "", ""],
    ["After five years", "44,550", "9,139", "", ""],
    ["After six years", "46,646", "9,220", "", ""],
    ["After seven years", "45,613", "9,324", "", ""],
    ["After eight years", "43,923", "", "", ""],
    ["Less net claims paid", "36,429", "6,960", "200,718", ""],
    ["Net reserves", "7,494", "2,364", "23,665", "33,523"],
]
#: 609/2018 table 14 (first rows): the whole header merged into the label column's cell
GRID_609_2018_HEAD = [
    ["December 2018 in all cases. 2011 2012 2013 2014 2015 2016 2017 2018 Total Analysis of claims "
     "development - gross £'000 £'000 £'000 £'000 £'000 £'000 £'000 "
     "£'000 £'000", "", "", "", "", "", "", "", "", ""],
    ["Estimate of ultimate gross claims:", "", "", "", "", "", "", "", "", ""],
    ["at end of underwriting year", "293,338", "260,206", "261,835", "259,108", "278,817", "287,485",
     "375,693", "320,329", ""],
    ["one year later", "265,295", "218,283", "255,899", "230,079", "266,593", "264,798", "357,530", "", ""],
    ["two years later", "256,327", "200,908", "230,729", "213,445", "239,888", "240,599", "", "", ""],
]
#: 5820/2019 table 6: one year of account, the date and the cohort in the label column's cell
GRID_5820_2019 = [
    ["At 31 December 2019 2017 Year of Account", "Gross of reinsurance", "Net of reinsurance",
     "1Gross of reinsurance including unearned premium", "1Net of reinsurance including unearned premium"],
    ["", "£'000", "£'000", "£'000", "£'000"],
    ["At end of underwriting year", "39,717", "18,583", "128,785", "104,477"],
    ["One year later", "69,073", "51,743", "113,968", "95,420"],
    ["Two years later", "90,310", "71,792", "115,906", "97,336"],
    ["Gross ultimate claims on premium earned to date", "90,310", "71,792", "-", "-"],
    ["Cumulative payments", "(70,682)", "(58,252)", "-", "-"],
    ["Estimated balance to pay", "19,628", "13,540", "-", "-"],
]


def _parse(grid, year):
    res, details = te._parse_nutrient_triangle(grid, year)
    assert isinstance(res, te.TriangleData), details
    return res


def _column(tri, year):
    k = [int(y) for y in tri.underwriting_years].index(year)
    return [row[k] for row in tri.development_rows]


def test_a_date_in_a_data_columns_header_cell_is_not_a_second_cohort():
    tri = _parse(GRID_3330_2018_NET, 2018)
    assert [int(y) for y in tri.underwriting_years] == [2011, 2012, 2018]
    assert _column(tri, 2011) == [44695.0, 38620.0, 44971.0, 50751.0, 44550.0, 46646.0, 45613.0, 43923.0]
    assert _column(tri, 2012)[:7] == [15597.0, 10917.0, 7426.0, 7105.0, 9139.0, 9220.0, 9324.0]
    assert _column(tri, 2018)[0] == 224383.0


def test_3330_2018_gross_table_gives_the_filings_development():
    pyd, details = tg.compute_pyd_from_triangle(_parse(GRID_3330_2018_GROSS, 2018).to_dict(), 2018)
    assert pyd == pytest.approx(-1.384, abs=5e-4), details


def test_the_two_tables_no_longer_contest_the_page_on_a_misread_grid():
    """The Azure path keeps the gross table when the net one is read correctly: the two tie on
    basis, cohorts and filled cells, and the first admitted stays."""
    gross, net = _parse(GRID_3330_2018_GROSS, 2018), _parse(GRID_3330_2018_NET, 2018)
    filled = lambda t: sum(1 for r in t.development_rows for v in r if v is not None)  # noqa: E731
    assert filled(net) == filled(gross) == 16
    best, _note = te.relabel_if_smaller_than_its_twin(gross, [gross, net])
    assert best is gross and best.type == "gross"


def test_a_label_column_header_keeps_its_offsets():
    """609/2018: the whole header row sits in the label column's cell; the date's year stands in
    for the label column and 2011 lands on the first data column, as before."""
    tri = _parse(GRID_609_2018_HEAD, 2018)
    assert [int(y) for y in tri.underwriting_years][:2] == [2011, 2012]
    assert _column(tri, 2011) == [293338.0, 265295.0, 256327.0]
    assert _column(tri, 2017)[:2] == [375693.0, 357530.0]


def test_a_year_of_account_title_in_the_label_column_parses_as_before():
    """5820/2019: 'At 31 December 2019 2017 Year of Account' -- its gross column is the 2017 year
    of account, and its RAG figure (+21.237m, applied) must not move."""
    tri = _parse(GRID_5820_2019, 2019)
    assert [int(y) for y in tri.underwriting_years] == [2017, 2019]
    assert _column(tri, 2017) == [39717.0, 69073.0, 90310.0]
    pyd, details = tg.compute_pyd_from_triangle(tri.to_dict(), 2019)
    assert pyd == pytest.approx(21.237, abs=5e-4), details


def test_3330_2018_through_the_table_step(monkeypatch):
    """The deciding level: the table step on the committed Azure cache reports the gross table.
    Needs the source filing, which is not committed."""
    pdf = ROOT / "syndicate_reports" / "pdfs" / "syndicate_3330_2018.pdf"
    if not pdf.exists():
        pytest.skip("source filing not present in this checkout")
    monkeypatch.setenv("LLOYDS_EXTRACTION_OFFLINE", "1")
    r = te.extract_tables(pdf, 2018, backend=te.TableBackend.AZURE, azure_paid=True,
                          cache_dir=ROOT / "pdf_extraction" / "azure_output")
    assert r.triangle is not None and r.triangle.type == "gross"
    assert [int(y) for y in r.triangle.underwriting_years] == [2011, 2012, 2018]
    pyd, details = tg.compute_pyd_from_triangle(r.triangle.to_dict(), 2018)
    assert pyd == pytest.approx(-1.384, abs=5e-4), details
