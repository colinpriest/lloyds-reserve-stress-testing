"""P-30 (review of 2 October 2026, R5-F5): a class table printed by year of account and by calendar year is read
from the report year's calendar-year column.

Ark's managing agent's report (syndicates 4020, 3902 and 6105) prints each class's premium as "2015 YOA estimate |
2014 YOA estimate | 2013 YOA estimate | 2015 Cal. Year | Restated 2014 Cal. year". The table parser read none of
these tables (its grid names no premium, and its header's first year is a comparative's), so their mixes were the
models' readings. For 6105/2015 the adopted reading took the 2015 year-of-account column (43,178) where the gross
premiums written are the calendar year's (43,859, the income statement's figure); for 3902/2019 it took the
year-of-account column scaled to the calendar total. `_yoa_calendar_column` names the report year's calendar-year
column, and the gate (`_lob_override_gate`) holds the mix to a model's total before it is applied.

Run:  python -m pytest tests/test_yoa_calendar_column.py -q
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import table_extraction as te  # noqa: E402

AZURE = ROOT / "pdf_extraction" / "azure_output"
RECORDS = ROOT / "pdf_extraction"


def _grid(stem, page):
    with open(AZURE / ("%s_azure.json" % stem), encoding="utf-8") as fh:
        tables = json.load(fh)["tables"]
    year = int(stem.rsplit("_", 1)[1])
    found = [t["grid"] for t in tables
             if t.get("orig_page") == page and te._yoa_calendar_column(t["grid"], year) is not None]
    assert len(found) == 1, (stem, page, len(found))
    return found[0]


def _model_totals(stem):
    with open(RECORDS / ("%s.json" % stem), encoding="utf-8") as fh:
        rec = json.load(fh)
    return [b.get("gross_premiums_written_gbp_m") for b in (rec.get("models") or {}).values()]


def test_6105_2015_is_read_from_the_2015_calendar_year_column():
    grid = _grid("syndicate_6105_2015", 7)
    assert te._yoa_calendar_column(grid, 2015) == 4
    lob = te._parse_nutrient_lob(grid, 2015)
    mix = {m["line_of_business"]: m["amount_gbp_m"] for m in lob.gross_premium_mix}
    # the review's calendar-column figures (the year-of-account column prints 5,094 and 10,555)
    assert mix["Accident & Health"] == pytest.approx(5.365)
    assert mix["Specialty Programmes"] == pytest.approx(11.973)
    assert mix["Package Programmes"] == pytest.approx(2.595)
    assert len(mix) == 15
    assert lob.table_total == pytest.approx(43.859)
    assert lob.class_sum == pytest.approx(43.859)


def test_the_calendar_mix_passes_the_gate_with_the_records_totals():
    import test_gemini as tg
    lob = te._parse_nutrient_lob(_grid("syndicate_6105_2015", 7), 2015)
    ok, why = tg._lob_override_gate(lob.to_dict(), _model_totals("syndicate_6105_2015"))
    assert ok, why
    assert _model_totals("syndicate_6105_2015") == [43.859, 43.859]


def _ark_tables():
    """Every committed grid the rule reads: (stem, page, grid, column)."""
    out = []
    for path in sorted(AZURE.glob("syndicate_*_azure.json")):
        stem = path.name[:-len("_azure.json")]
        with open(path, encoding="utf-8") as fh:
            cache = json.load(fh)
        if not isinstance(cache, dict):
            continue
        year = int(stem.rsplit("_", 1)[1])
        for t in cache.get("tables", []):
            col = te._yoa_calendar_column(t.get("grid") or [], year)
            if col is not None:
                out.append((stem, t.get("orig_page"), t["grid"], col))
    return out


def test_every_year_of_account_and_calendar_table_reads_the_premium_the_models_read():
    """The rule's reach, and the generalised check: over every committed grid it reads, the classes sum to the
    calendar column's printed total, and that total is the gross premiums written each model read (the column
    is the premium written, whatever the grid calls it)."""
    tables = _ark_tables()
    stems = sorted({s for s, _, _, _ in tables})
    syndicates = sorted({int(s.split("_")[1]) for s in stems})
    assert syndicates == [3902, 4020, 6105], syndicates
    assert len(stems) == 20, stems
    checked = 0
    for stem, page, grid, col in tables:
        year = int(stem.rsplit("_", 1)[1])
        lob = te._parse_nutrient_lob(grid, year)
        assert lob is not None, (stem, page)
        assert lob.table_total is not None and lob.class_sum == pytest.approx(lob.table_total, abs=1e-6), (stem, page)
        totals = [v for v in _model_totals(stem) if isinstance(v, (int, float))]
        for v in totals:
            assert v == pytest.approx(lob.table_total, abs=0.0015), (stem, page, v, lob.table_total)
            checked += 1
    assert checked >= 30


HEAD = [
    ["", "2020", "2019", "2018", "2020", "2019 Cal year"],
    ["", "YOA Estimate", "YOA Estimate", "YOA Closed", "Cal year", ""],
    ["", "£'000", "£'000", "£'000", "£'000", "£'000"],
    ["Marine & Energy", "41,105", "51,155", "35,747", "42,498", "52,080"],
    ["Property", "24,566", "23,556", "22,840", "22,160", "22,941"],
    ["Specialty", "20,348", "22,337", "17,752", "24,797", "22,215"],
    ["", "86,019", "97,048", "76,339", "89,455", "97,236"],
]


def test_the_year_and_the_label_on_separate_rows_name_the_report_years_column():
    assert te._yoa_calendar_column(HEAD, 2020) == 4
    lob = te._parse_nutrient_lob(HEAD, 2020)
    assert [m["amount_gbp_m"] for m in lob.gross_premium_mix] == [42.498, 22.16, 24.797]


def test_the_prior_years_calendar_column_is_not_the_report_years():
    # the 2019 report would read the 2019 calendar column; a 2021 report finds none
    assert te._yoa_calendar_column(HEAD, 2019) == 5
    assert te._yoa_calendar_column(HEAD, 2021) is None


def test_a_table_without_year_of_account_columns_is_left_to_the_other_rules():
    grid = [row[:1] + row[4:] for row in HEAD]
    assert te._yoa_calendar_column(grid, 2020) is None


def test_two_calendar_columns_for_the_report_year_are_ambiguous():
    grid = [row + [row[4]] for row in HEAD]
    assert te._yoa_calendar_column(grid, 2020) is None
