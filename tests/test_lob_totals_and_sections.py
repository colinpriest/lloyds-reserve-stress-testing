"""Round 54 (review finding M01): a closed-year segmental table and its grand total
do not become a business mix.

Syndicate 623's 2022 annual report appends the closed 2020 year-of-account accounts;
every page carries the running header "Beazley Syndicate 623 annual accounts". The
closed-year "Analysis of underwriting result" (direct classes, reinsurance classes,
"Total Direct and Reinsurance accepted 609.6") was admitted as the annual mix: the
running header outranked the page's own closed-year heading, the kind did not carry
forward, and the total label was not in the exact set the parser dropped. The record
carried a 609.6 grand total beside 542.5 of classes on a 67.1 "total".

Run:  python -m pytest tests/test_lob_totals_and_sections.py -q
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import table_extraction as te  # noqa: E402

HEADER = "Beazley  Syndicate 623 annual accounts 2022\n"


def _pages(*bodies):
    return {i: HEADER + b for i, b in enumerate(bodies)}


class TestSectionKindCarriesForward:
    def test_running_header_does_not_make_closed_year_pages_annual(self):
        pages = _pages(
            "Report of the directors\nSyndicate 623 underwrites ...",
            "Balance sheet\nclosed at 31 December 2022\nNotes\n2020 year of\naccount\n$m\nAssets",
            "Cash flow statement\n2020 year of account for the 36 months ended 31 December 2022\n$m",
            "1 Accounting policies\nBasis of preparation\nThese underwriting accounts have been prepared in accordance",
            "3 Analysis of underwriting result\nGross premiums written\nMarine 70.4\nTotal Direct 542.5",
        )
        kinds = [te.page_sections(pages, 623)[p][1] for p in sorted(pages)]
        assert kinds == ["annual", "underwriting_year", "underwriting_year",
                         "underwriting_year", "underwriting_year"]

    def test_kind_returns_to_annual_on_an_effective_marker(self):
        pages = _pages(
            "Syndicate 623 underwriting year accounts\n2020 year of account",
            "3 Analysis of underwriting result\nGross premiums written",
            "Syndicate 6107 annual accounts\nReport of the directors",
            "Balance sheet\nat 31 December 2022",
        )
        kinds = [te.page_sections(pages, 623)[p][1] for p in sorted(pages)]
        assert kinds == ["underwriting_year", "underwriting_year", "annual", "annual"]

    def test_a_filing_without_closed_year_accounts_stays_annual(self):
        pages = _pages("Report", "Balance sheet\nat 31 December 2022", "Notes")
        assert all(k == "annual" for _, k in te.page_sections(pages, 623).values())


CLOSED_YEAR_GRID = [
    ["", "Gross premiums written", "Gross premiums earned", "Gross claims incurred"],
    ["Direct insurance:", "", "", ""],
    ["Marine aviation and transport", "70.4", "68.0", "(34.2)"],
    ["Fire and other damage to property", "112.5", "110.0", "(85.6)"],
    ["Third party liability", "340.3", "330.0", "(265.5)"],
    ["Miscellaneous", "19.3", "19.0", "(47.0)"],
    ["Total direct", "542.5", "527.0", "(432.3)"],
    ["Reinsurance acceptances:", "", "", ""],
    ["Fire and other damage to property", "45.3", "44.0", "(38.6)"],
    ["Third party liability", "21.8", "21.0", "(12.8)"],
    ["Total reinsurance accepted", "67.1", "65.0", "(51.4)"],
    ["Total Direct and Reinsurance accepted", "609.6", "592.0", "(483.7)"],
]


class TestTotalRows:
    def test_total_labels_of_every_wording_are_dropped(self):
        lob = te._parse_nutrient_lob(CLOSED_YEAR_GRID, 2022, page_text="segmental analysis")
        assert lob is not None
        names = [e["line_of_business"].lower() for e in lob.gross_premium_mix]
        assert not any(n.startswith("total") for n in names)
        assert len(lob.gross_premium_mix) == 6
        assert abs(lob.gross_premiums_written_gbp_m - 609.6) < 0.05
        assert abs(sum(e["amount_gbp_m"] for e in lob.gross_premium_mix) - 609.6) < 0.05

    def test_an_unlabelled_subtotal_is_dropped(self):
        grid = [
            ["", "Gross premiums written"],
            ["Marine", "70.4"],
            ["Property", "112.5"],
            ["Liability", "340.3"],
            ["Direct", "523.2"],          # = 70.4 + 112.5 + 340.3
            ["Property", "45.3"],
            ["Liability", "21.8"],
            ["Total", "590.3"],
        ]
        lob = te._parse_nutrient_lob(grid, 2022, page_text="segmental analysis")
        assert lob is not None
        assert [e["amount_gbp_m"] for e in lob.gross_premium_mix] == [70.4, 112.5, 340.3, 45.3, 21.8]

    def test_classes_exceeding_the_table_total_are_not_a_mix(self):
        grid = [
            ["", "Gross premiums written"],
            ["Marine", "70.4"],
            ["Property", "112.5"],
            ["Liability", "340.3"],
            ["Aviation", "400.0"],        # a comparative column read as a class
            ["Total", "523.2"],
        ]
        assert te._parse_nutrient_lob(grid, 2022, page_text="segmental analysis") is None

    def test_is_total_label(self):
        for l in ("total", "total direct", "total direct insurance", "total - direct",
                  "total direct and reinsurance accepted", "sub-total", "subtotal",
                  "grand total", "total reinsurance accepted"):
            assert te._is_total_label(l), l
        for l in ("marine", "property total loss", "third party liability"):
            assert not te._is_total_label(l), l
