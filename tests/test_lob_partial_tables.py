"""Round 58 (review finding M03): a premium table is read whole or refused.

A census of the corpus found 147 records whose adopted class total fell below 80% of a
premium total two independent readings agree on. The row parser lost classes in four ways
and then made the loss look reconciled:

  * a "Reinsurance acceptances" row that carries a premium was skipped as a section header
    (the sole cause in 98 records, one of the causes in 4 more);
  * an unlabelled grand total was skipped, so "Total Direct" was taken for the table's
    total and a complete table was refused as a double count (1856/2018);
  * a class whose premium came within 0.6% of the classes above it was dropped as a
    subtotal (3000/2020 and 2988/2022, Third party liability);
  * a table total more than 10% above the classes was overwritten with their sum.

Also here: a label printed on the row above its amounts (2088/2017, 5886/2024), a
comparative section opened by "2023 (Restated)" or "2023*" (1176/2024, 1880/2024, 510/2024),
a total printed on a result line (780/2014-2018), a grid whose classes carry no premium
(1322/2024, 2468/2022, 2999/2018), amounts stored unrounded, the text fallback's total, and
the driver's gate on the models' totals. Each grid is synthetic and in the layout the cached
Azure tables have.

Run:  python -m pytest tests/test_lob_partial_tables.py -q
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import table_extraction as te  # noqa: E402

HEAD = ["", "Gross premiums written", "Gross premiums earned", "Gross claims incurred"]
SEG = "segmental analysis"


def _mix(lob):
    return {e["line_of_business"]: e["amount_gbp_m"] for e in lob.gross_premium_mix}


def test_section_header_rule():
    """A "Reinsurance acceptances" row with a premium is a class; a header row with no
    amount ("Direct insurance:", "Reinsurance acceptances:") is still skipped."""
    grid = [HEAD,
            ["Direct insurance:", "", "", ""],
            ["Marine", "100.0", "90.0", "(50.0)"],
            ["Property", "200.0", "180.0", "(120.0)"],
            ["Total direct insurance", "300.0", "270.0", "(170.0)"],
            ["Reinsurance acceptances", "700.0", "650.0", "(400.0)"],
            ["Total", "1,000.0", "920.0", "(570.0)"]]
    lob = te._parse_nutrient_lob(grid, 2022, page_text=SEG)
    assert lob is not None
    assert _mix(lob) == {"Marine": 100.0, "Property": 200.0, "Reinsurance acceptances": 700.0}
    assert lob.gross_premiums_written_gbp_m == pytest.approx(1000.0)

    headers_only = [HEAD,
                    ["Direct insurance:", "", "", ""],
                    ["Marine", "100.0", "90.0", "(50.0)"],
                    ["Reinsurance acceptances:", "", "", ""],
                    ["Property", "45.0", "44.0", "(38.0)"],
                    ["Total", "145.0", "134.0", "(88.0)"]]
    lob = te._parse_nutrient_lob(headers_only, 2022, page_text=SEG)
    assert lob is not None and set(_mix(lob)) == {"Marine", "Property"}


def test_grand_total_rule():
    """An unlabelled row equal to the classes above it, with no class after it, is the
    table's total; "Total Direct" is a subtotal and must not stand for it (1856/2018)."""
    grid = [["2018", "Gross premiums written", "Gross claims incurred"],
            ["Marine", "10.0", "(5.0)"],
            ["Aviation", "20.0", "(8.0)"],
            ["Total Direct", "30.0", "(13.0)"],
            ["Reinsurance", "70.0", "(40.0)"],
            ["", "100.0", "(53.0)"]]
    lob = te._parse_nutrient_lob(grid, 2018, page_text=SEG)
    assert lob is not None
    assert _mix(lob) == {"Marine": 10.0, "Aviation": 20.0, "Reinsurance": 70.0}
    assert lob.gross_premiums_written_gbp_m == pytest.approx(100.0)

    # an unlabelled subtotal that classes follow is not the total; with no printed total
    # the mix is kept and its total left unset, never set to the classes' sum
    subtotal = [["", "Gross premiums written"],
                ["Marine", "10.0"],
                ["Aviation", "20.0"],
                ["", "30.0"],
                ["Reinsurance", "70.0"]]
    lob = te._parse_nutrient_lob(subtotal, 2018, page_text=SEG)
    assert lob is not None and set(_mix(lob)) == {"Marine", "Aviation", "Reinsurance"}
    assert lob.gross_premiums_written_gbp_m is None


def test_subtotal_rule():
    """A labelled class is never a subtotal, whatever it equals; a row labelled as a
    section ("Direct") that equals the classes above it is one."""
    grid = [["", "Gross premiums written"],
            ["Marine", "40.0"],
            ["Aviation", "60.0"],
            ["Third party liability", "100.0"],     # = Marine + Aviation, and a class
            ["Total", "200.0"]]
    lob = te._parse_nutrient_lob(grid, 2022, page_text=SEG)
    assert lob is not None
    assert _mix(lob) == {"Marine": 40.0, "Aviation": 60.0, "Third party liability": 100.0}

    entries = [{"line_of_business": "Marine", "amount_raw": 40.0},
               {"line_of_business": "Aviation", "amount_raw": 60.0},
               {"line_of_business": "Direct", "amount_raw": 100.0},
               {"line_of_business": "Third party liability", "amount_raw": 100.0}]
    kept, dropped = te._drop_subtotal_rows(entries)
    assert [e["line_of_business"] for e in dropped] == ["Direct"]
    assert [e["line_of_business"] for e in kept] == ["Marine", "Aviation", "Third party liability"]

    # a total's label split over two rows is still a total (1618/2024: "Total Direct" with
    # no amount, then "Insurance 564,073"), and the class under it is still a class
    split = [HEAD,
             ["Accident and health", "4,166", "5,479", "(1,241)"],
             ["Third party liability", "164,870", "160,852", "(103,494)"],
             ["Total Direct", "", "", ""],
             ["Insurance", "169,036", "166,331", "(104,735)"],
             ["Reinsurance acceptances", "236,900", "242,782", "(160,350)"],
             ["Total", "405,936", "409,113", "(265,085)"]]
    lob = te._parse_nutrient_lob(split, 2024, page_text=SEG)
    assert lob is not None
    assert _mix(lob) == {"Accident and health": 4.166, "Third party liability": 164.87,
                         "Reinsurance acceptances": 236.9}

    # a label that ends in "Total" is a total ("Direct Total", "Reinsurance Total": 1955/2021)
    trailing = [HEAD,
                ["Direct Insurance", "", "", ""],
                ["Accident and health", "2,945", "2,863", "(9,342)"],
                ["Third party liability", "82,859", "74,735", "(42,115)"],
                ["Direct Total", "85,804", "77,598", "(51,457)"],
                ["Reinsurance", "", "", ""],
                ["Property", "85,101", "83,674", "(48,390)"],
                ["Reinsurance Total", "85,101", "83,674", "(48,390)"],
                ["Total", "170,905", "161,272", "(99,847)"]]
    lob = te._parse_nutrient_lob(trailing, 2021, page_text=SEG)
    assert lob is not None
    assert _mix(lob) == {"Accident and health": 2.945, "Third party liability": 82.859, "Property": 85.101}


def test_a_result_line_carrying_the_class_sum_is_the_total():
    """780/2015 printed its grand total on the "Net technical result" line, and the mix
    took it for an eighth class, counting every premium twice. A profit-and-loss row whose
    premium is the sum of the classes above it is the total; a class row equal to the
    classes above it is still a class."""
    grid = [["", "Gross premiums written", "Gross premiums earned", "Total"],
            ["", "$000", "$000", "$000"],
            ["2015", "", "", ""],
            ["Direct insurance", "", "", ""],
            ["Accident and health", "51,320", "34,901", "(6,163)"],
            ["Marine aviation and transport", "32,554", "32,523", "(5,339)"],
            ["Fire and other damage to property", "72,627", "54,537", "(9,315)"],
            ["", "156,501", "121,961", "(20,817)"],
            ["Reinsurance acceptances", "83,534", "87,717", "17,023"],
            ["Net technical result", "240,035", "209,678", "(3,794)"],
            ["Investment return", "", "", "(2,361)"]]
    lob = te._parse_nutrient_lob(grid, 2015, page_text=SEG)
    assert lob is not None
    assert _mix(lob) == {"Accident and health": 51.32, "Marine aviation and transport": 32.554,
                         "Fire and other damage to property": 72.627, "Reinsurance acceptances": 83.534}
    assert lob.gross_premiums_written_gbp_m == pytest.approx(240.035)
    assert lob.class_sum == pytest.approx(240.035)

    reinsurance = [["", "Gross premiums written"],
                   ["Marine", "40.0"], ["Aviation", "60.0"], ["Reinsurance", "100.0"]]
    lob = te._parse_nutrient_lob(reinsurance, 2022, page_text=SEG)
    assert lob is not None
    assert _mix(lob) == {"Marine": 40.0, "Aviation": 60.0, "Reinsurance": 100.0}
    assert lob.gross_premiums_written_gbp_m is None


def test_classes_without_premium_are_refused():
    """1322/2024's "Additional analysis" grid has claims by class and no premium; read as a
    mix of three zero classes it displaced the text's mix. It is refused, with a reason."""
    grid = [["", "Gross premiums written", "Gross claims incurred"],
            ["Specialties", "", "(1,200)"],
            ["Energy", "-", "(300)"],
            ["Property", "", "(450)"]]
    why = []
    assert te._parse_nutrient_lob(grid, 2024, page_text=SEG, refusals=why) is None
    assert why == ["3 classes carry no premium"]


def test_refuse_never_overwrite_rule():
    """A table total more than 2% from its classes refuses the mix, with a reason; within
    2% the printed total is kept as printed, beside the class sum."""
    partial = [["", "Gross premiums written"],
               ["Marine", "10.0"],
               ["Property", "20.0"],
               ["Total", "100.0"]]
    assert te._parse_nutrient_lob(partial, 2022, page_text=SEG) is None
    why = []
    assert te._parse_nutrient_lob(partial, 2022, page_text=SEG, refusals=why) is None
    assert why and "30" in why[0] and "100" in why[0]

    close = [row[:] for row in partial]
    close[3][1] = "30.5"
    lob = te._parse_nutrient_lob(close, 2022, page_text=SEG)
    assert lob is not None
    assert lob.gross_premiums_written_gbp_m == pytest.approx(30.5)
    assert lob.class_sum == pytest.approx(30.0)

    transposed = [["2015", "Marine $m", "Property $m", "Total $m"],
                  ["Gross premiums written", "10.0", "20.0", "100.0"]]
    assert te._parse_transposed_lob(transposed, 2015, te._grid_text_lower(transposed)) is None


def test_a_label_printed_above_its_amounts_is_merged():
    grid = [HEAD,
            ["Fire and other damage to property", "", "", ""],
            ["", "68.587", "56.416", "(60.310)"],
            ["Accident and health", "57.081", "38.957", "(24.505)"],
            ["Total", "125.668", "95.373", "(84.815)"]]
    lob = te._parse_nutrient_lob(grid, 2017, page_text=SEG)
    assert lob is not None
    assert _mix(lob) == {"Fire and other damage to property": 68.587, "Accident and health": 57.081}


def test_a_premium_printed_below_its_class_row_is_merged():
    grid = [HEAD,
            ["Accident & Health", "22.497", "19.776", "(11.800)"],
            ["Credit and suretyship", "", "29.473", "(9.860)"],
            ["", "33.147", "", ""],
            ["Total", "55.644", "49.249", "(21.660)"]]
    lob = te._parse_nutrient_lob(grid, 2024, page_text=SEG)
    assert lob is not None and _mix(lob)["Credit and suretyship"] == pytest.approx(33.147)


@pytest.mark.parametrize("divider", ["2023 (Restated)", "2023*"])
def test_a_year_prefixed_row_opens_the_comparative(divider):
    grid = [HEAD,
            ["2024", "", "", ""],
            ["Marine", "45.0", "43.0", "(4.0)"],
            ["Reinsurance acceptances", "55.0", "50.0", "(16.0)"],
            ["Total", "100.0", "93.0", "(20.0)"],
            [divider, "", "", ""],
            ["Fire and other damage to property", "78.98", "71.32", "(6.2)"],
            ["Total", "78.98", "71.32", "(6.2)"]]
    lob = te._parse_nutrient_lob(grid, 2024, page_text=SEG)
    assert lob is not None
    assert _mix(lob) == {"Marine": 45.0, "Reinsurance acceptances": 55.0}


def test_amounts_are_stored_unrounded():
    grid = [["2018", "Gross premiums written"], ["", "£'000"],
            ["Marine", "74"], ["Aviation", "4,490"], ["Reinsurance", "120,770"],
            ["Total", "125,334"]]
    lob = te._parse_nutrient_lob(grid, 2018, page_text=SEG)
    assert lob is not None
    assert _mix(lob) == {"Marine": 0.074, "Aviation": 4.49, "Reinsurance": 120.77}
    assert lob.gross_premiums_written_gbp_m == 125.334


def test_the_text_fallback_writes_no_total():
    text = ("2018 Fire and other damage to property 6,520 4,157 (4,690) "
            "Third party liability 6,348 3,689 (4,295) 2017")
    lob = te._parse_lob_from_text(text, 2018)
    assert lob is not None
    assert lob.gross_premiums_written_gbp_m is None
    assert lob.class_sum == pytest.approx(12.868)


def test_a_text_mix_reconciles_only_with_a_printed_premium():
    readings = te.gross_premiums_written_readings(
        [([["", "Notes", "2018 £000", "2017 £000"],
           ["Gross premiums written", "2", "143,968", "91,378"]], 13)], 2018)
    assert [r["value_m"] for r in readings] == [143.968]
    assert te.reconciling_reading(14.244, readings) is None
    assert te.reconciling_reading(143.968, readings)["value_m"] == 143.968
    assert te.reconciling_reading(141.2, readings) is not None       # 1.9% short
    assert te.reconciling_reading(140.9, readings) is None           # 2.1% short


def test_the_driver_gate_reconciles_the_class_sum_with_the_models_totals():
    """1856/2018's shape: three classes, 14.2m, against both models' 143.968m, refused
    although it has more than one class; the complete seven-class mix is applied."""
    from test_gemini import _lob_override_gate

    def mix(pairs):
        return {"gross_premium_mix": [{"line_of_business": n, "amount_gbp_m": a} for n, a in pairs]}
    partial = mix((("Fire and other damage to property", 6.52), ("Third party liability", 6.348),
                   ("Energy", 1.376)))
    ok, why = _lob_override_gate(partial, [143.968, 143.968])
    assert not ok and "LOB NOT APPLIED" in why
    full = mix((("Marine", 0.074), ("Aviation", 4.49), ("Energy-Marine", 1.376), ("Energy Non-Marine", 4.39),
                ("Fire and Other damage to Property", 6.52), ("Third party liability", 6.348),
                ("Reinsurance", 120.77)))
    assert _lob_override_gate(full, [143.968, 143.968]) == (True, None)
