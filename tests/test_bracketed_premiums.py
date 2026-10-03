"""P-29 (review of 2 October 2026, R5-F4): a class premium printed in brackets is a negative premium.

Every reader stored a bracketed class premium as positive. 1414/2016's "Motor (other) (294)" was +0.294, so the
classes summed to 574.063 against the table's 573.475, and the class took weight in the mix that the analysis gives
no negative class (its mix_reconciles sums the classes with their signs; build_weight_vector weights the positive
ones). The table readers now keep the sign of a bracketed class among positive classes; a column printed wholly in
brackets is a presentation of outflows and is read as positive, as before.

The verified cases are the review's, read from the committed Azure Document Intelligence cache:
1414/2016 Motor (other) (294); 4472/2019 Motor (third-party liability) (3.0); 1967/2020 Aviation (4,079);
1686/2019 Aviation (4,503).

Run:  python -m pytest tests/test_bracketed_premiums.py -q
"""
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import table_extraction as te  # noqa: E402

AZURE = ROOT / "pdf_extraction" / "azure_output"

# stem, the cache's page index, the class, its amount in the table's units after the units rule, the table's total
VERIFIED = [
    ("syndicate_1414_2016", 32, "Motor (other)", -0.294, 573.475),
    ("syndicate_4472_2019", 5, "Motor (third-party liability)", -3.0, 1687.2),
    ("syndicate_1967_2020", 27, "Aviation", -4.079, 417.528),
    ("syndicate_1686_2019", 14, "Aviation", -4.503, 1142.575),
]


def _tables(stem):
    with open(AZURE / ("%s_azure.json" % stem), encoding="utf-8") as fh:
        return json.load(fh)["tables"]


def _parse_page(stem, page):
    year = int(stem.rsplit("_", 1)[1])
    for t in _tables(stem):
        if t.get("orig_page") == page and te._admits_premium_grid(t["grid"], t.get("categories") or []):
            lob = te._parse_nutrient_lob(t["grid"], year, page_text="", refusals=[])
            if lob is not None:
                return lob
    return None


def _record_totals(stem):
    with open(ROOT / "pdf_extraction" / ("%s.json" % stem), encoding="utf-8") as fh:
        rec = json.load(fh)
    return [b.get("gross_premiums_written_gbp_m") for b in rec["models"].values()]


@pytest.mark.parametrize("stem,page,cls,amount,total", VERIFIED, ids=[v[0] for v in VERIFIED])
def test_the_verified_bracketed_class_is_negative_and_the_classes_sum_to_the_total(stem, page, cls, amount, total):
    lob = _parse_page(stem, page)
    assert lob is not None, "%s: the premium table on page index %d no longer parses" % (stem, page)
    mix = {m["line_of_business"]: m["amount_gbp_m"] for m in lob.gross_premium_mix}
    assert mix.get(cls) == pytest.approx(amount), (stem, cls, mix.get(cls))
    # only the bracketed class is negative
    assert [k for k, v in mix.items() if v < 0] == [cls]
    assert lob.table_total == pytest.approx(total)
    assert lob.class_sum == pytest.approx(total, abs=1e-6)
    assert sum(mix.values()) == pytest.approx(total, abs=1e-6)


@pytest.mark.parametrize("stem,page", [(v[0], v[1]) for v in VERIFIED], ids=[v[0] for v in VERIFIED])
def test_the_signed_mix_passes_the_override_gate_with_the_records_totals(stem, page):
    """The record's models read the table's total; the signed classes reconcile with it."""
    import test_gemini as tg
    lob = _parse_page(stem, page)
    ok, why = tg._lob_override_gate(lob.to_dict(), _record_totals(stem))
    assert ok, why


def test_a_sign_does_not_change_the_units():
    """780/2020's classes ($'000) sum to 8,309 with Motor's (1,537) and to 11,383 without the sign; the units come
    from the sizes, so Motor is -1.537 on the scale the record has always had, not -1,537."""
    lob = _parse_page("syndicate_780_2020", 15)
    mix = {m["line_of_business"]: m["amount_gbp_m"] for m in lob.gross_premium_mix}
    assert mix["Motor"] == pytest.approx(-1.537)
    assert mix["Accident and health"] == pytest.approx(2.853)
    assert lob.class_sum == pytest.approx(8.309)


def test_an_unlabelled_row_equal_to_the_signed_classes_is_the_total():
    """3330/2014 prints its totals on unlabelled rows: 58 under the direct classes, (33) among them, and 78 under
    all of them. The 78 is read as the table's total."""
    lob = _parse_page("syndicate_3330_2014", 15)
    mix = {m["line_of_business"]: m["amount_gbp_m"] for m in lob.gross_premium_mix}
    assert mix["Fire and other damage to property"] == pytest.approx(-33.0)
    assert lob.table_total == pytest.approx(78.0)
    assert lob.class_sum == pytest.approx(78.0)


def test_classes_summing_to_a_negative_premium_are_refused():
    """2468/2021 is in run-off: most of its classes are returns and its total is "(2,190)". It is no mix."""
    refusals = []
    year = 2021
    for t in _tables("syndicate_2468_2021"):
        if t.get("orig_page") == 22:
            assert te._parse_nutrient_lob(t["grid"], year, page_text="", refusals=refusals) is None
    assert any("negative premium" in r for r in refusals), refusals


GRID = [
    ["", "Gross premiums written", "Gross premiums earned", "Gross claims incurred"],
    ["", "£000", "£000", "£000"],
    ["Marine aviation and transport", "40,000", "39,000", "(20,000)"],
    ["Motor", "(500)", "(400)", "100"],
    ["Third party liability", "60,000", "58,000", "(30,000)"],
    ["Total", "99,500", "96,600", "(49,900)"],
]


def test_a_bracketed_class_among_positive_classes_keeps_its_sign():
    lob = te._parse_nutrient_lob(GRID, 2020)
    mix = {m["line_of_business"]: m["amount_gbp_m"] for m in lob.gross_premium_mix}
    assert mix == {"Marine aviation and transport": 40.0, "Motor": -0.5, "Third party liability": 60.0}
    assert lob.table_total == pytest.approx(99.5)


def test_a_column_printed_wholly_in_brackets_is_read_as_positive():
    grid = [[c if i != 1 or r < 2 else "(%s)" % c for i, c in enumerate(row)] for r, row in enumerate(GRID)]
    grid[3][1] = "(500)"
    grid[2][1], grid[4][1], grid[5][1] = "(40,000)", "(60,000)", "(101,500)"
    lob = te._parse_nutrient_lob(grid, 2020)
    mix = {m["line_of_business"]: m["amount_gbp_m"] for m in lob.gross_premium_mix}
    assert mix == {"Marine aviation and transport": 40.0, "Motor": 0.5, "Third party liability": 60.0}


def test_the_transposed_reader_keeps_the_sign():
    grid = [
        ["2020", "Marine $m", "Motor $m", "Property $m", "Total $m"],
        ["Gross premiums written", "40.0", "(0.5)", "60.0", "99.5"],
        ["Net premiums written", "30.0", "(0.4)", "50.0", "79.6"],
    ]
    lob = te._parse_transposed_lob(grid, 2020, te._grid_text_lower(grid))
    mix = {m["line_of_business"]: m["amount_gbp_m"] for m in lob.gross_premium_mix}
    assert mix["Motor"] == pytest.approx(-0.5)
    assert lob.class_sum == pytest.approx(99.5)


TEXT = """Particulars of business written 2016 Gross premiums written Gross premiums earned Gross claims incurred
Accident and health 1,200 1,100 (500)
Motor (294) (184) 3,655
Fire and other damage to property 20,000 21,000 (12,000)
Third party liability 5,000 4,000 (2,000)
2015 Accident and health 900"""


def test_the_page_text_reader_keeps_a_bracket_and_not_a_hyphen():
    lob = te._parse_lob_from_text(TEXT, 2016)
    mix = {m["line_of_business"]: m["amount_gbp_m"] for m in lob.gross_premium_mix}
    assert mix["Motor"] == pytest.approx(-0.294)
    lob = te._parse_lob_from_text(TEXT.replace("(294) (184)", "-294 184"), 2016)
    mix = {m["line_of_business"]: m["amount_gbp_m"] for m in lob.gross_premium_mix}
    assert mix["Motor"] == pytest.approx(0.294)


def _gwp_col(grid):
    for i, c in enumerate(grid[0]):
        low = str(c).lower()
        if "written" in low and "premium" in low:
            return i
    return None


def test_no_committed_premium_table_reads_a_bracketed_class_as_positive():
    """Over every committed Azure table the premium reader admits: where a class's premium cell is printed in
    brackets and another class's is not, the class is negative in the mix (the generalised check: the review's
    four were found by a sum that exceeded the total by twice a class)."""
    checked, wrong = 0, []
    for path in sorted(AZURE.glob("syndicate_*_azure.json")):
        stem = path.name[:-len("_azure.json")]
        m = re.search(r"_(\d{4})$", stem)
        if not m:
            continue
        with open(path, encoding="utf-8") as fh:
            cache = json.load(fh)
        if not isinstance(cache, dict):
            continue
        for t in cache.get("tables", []):
            grid = t.get("grid") or []
            if not grid or not te._admits_premium_grid(grid, t.get("categories") or []):
                continue
            col = _gwp_col(grid)
            lob = te._parse_nutrient_lob(grid, int(m.group(1)), page_text="", refusals=[])
            if col is None or lob is None or lob.method == "nutrient_transposed":
                continue
            # each class against its own row, in order: a label can recur (direct and reinsurance "Aviation")
            rows = [(str(r[0]).strip(), str(r[col]).strip()) for r in grid[1:] if r and col < len(r)]
            cells, at = [], 0
            for e in lob.gross_premium_mix:
                j = next((j for j in range(at, len(rows)) if rows[j][0] == e["line_of_business"]), None)
                cells.append((e, rows[j][1] if j is not None else ""))
                at = j + 1 if j is not None else at
            if not any(re.fullmatch(r"[\d,.]*[1-9][\d,.]*", c) for _, c in cells):
                continue
            for e, c in cells:
                if re.fullmatch(r"\([\d,.]+\)", c) and te._clean_cell(c):
                    checked += 1
                    if e["amount_gbp_m"] >= 0:
                        wrong.append((stem, t.get("orig_page"), e["line_of_business"], c, e["amount_gbp_m"]))
    assert checked >= 40, "only %d bracketed classes found: the scan has stopped seeing them" % checked
    assert not wrong, wrong
