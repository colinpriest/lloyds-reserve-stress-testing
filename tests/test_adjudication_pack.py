r"""The adjudication pack shows the estimator's own account of a triangle, and derives nothing.

The pack lays out the evidence for each hand adjudication in the error-rate study. Its first
version summed the last two filled cells of each column and flagged a disagreement with the
estimator. That was a second implementation of the estimator, and a different one. It flagged
every thousands-denominated grid and every outflow triangle until those were patched, and then
1991/2018, which it summed to -137.7m against the estimator's -25.6m because the estimator
skips a column whose previous development age is empty (R196).

So the pack prints the stored grid and the estimator's per-year lines verbatim. The tests use
one grid whose answer is shown by hand in tests/test_round56_rules.py: 780/2018, -21.3m,
presented in millions, in thousands, as an outflow, with a hole the estimator skips, and broken
so the rules reject it. A planted estimator answer checks that the pack prints the estimator's
account whole, and the register tests check that an overruled triangle is named (R197).
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import adjudication_pack as pack  # noqa: E402
import test_gemini                # noqa: E402

#: 780/2018 as the backend recorded it: millions, upper-right dashes as zeros.
GRID_780_2018 = [
    [236.6, 108.6, 88.5, 76.4, 75.1, 79.4, 160.5, 104.2],
    [269.0, 144.5, 124.1, 132.0, 160.1, 199.5, 227.0, 0.0],
    [182.1, 135.2, 115.7, 131.1, 173.5, 193.8, 0.0, 0.0],
    [204.5, 132.3, 106.2, 121.0, 168.6, 0.0, 0.0, 0.0],
    [263.9, 120.9, 101.9, 122.9, 0.0, 0.0, 0.0, 0.0],
    [242.2, 122.0, 97.6, 0.0, 0.0, 0.0, 0.0, 0.0],
    [240.5, 120.6, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    [233.6, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
]
UY_780_2018 = [2011, 2012, 2013, 2014, 2015, 2016, 2017, 2018]


def _tri(rows, units):
    return {"type": "gross", "currency": "USD", "units": units, "cell_binding": "header",
            "underwriting_years": list(UY_780_2018),
            "development_rows": [list(r) for r in rows]}


def _text(tri):
    return "\n".join(pack._triangle_block(tri, 2018))


class TestThePackShowsTheEstimatorsOwnSteps:

    def test_the_steps_and_the_total_are_the_estimators(self):
        out = _text(_tri(GRID_780_2018, "millions"))
        assert "Total PYD = -21.300m" in out, out
        assert "  2011:" in out and "  2016:" in out, out
        assert "sum to" not in out and "DISAGREE" not in out and "REJECT" not in out, out

    def test_a_thousands_triangle_is_converted_by_the_estimator(self):
        rows = [[v * 1000.0 for v in r] for r in GRID_780_2018]
        out = _text(_tri(rows, "thousands"))
        assert "converted from thousands to millions" in out, out
        assert "Total PYD = -21.300m" in out, out

    def test_an_outflow_triangle_is_reversed_by_the_estimator(self):
        rows = [[-v for v in r] for r in GRID_780_2018]
        out = _text(_tri(rows, "millions"))
        assert "outflow" in out, out
        assert "Total PYD = -21.300m" in out, out

    def test_a_column_the_estimator_skips_is_shown_skipped(self):
        """1991/2018's case, constructed: the age before a column's latest is empty. The
        estimator skips the column; the first pack stepped over the hole to the cell above
        and reported a disagreement that did not exist."""
        rows = [list(r) for r in GRID_780_2018]
        rows[2][4] = None
        out = _text(_tri(rows, "millions"))
        assert "2015: skipped (no previous diagonal at row 2)" in out, out
        assert "sum to" not in out and "DISAGREE" not in out, out

    def test_a_rejected_triangle_says_so(self):
        """2008/2021: the current rules reject the grid, and that is the finding."""
        rows = [[0.0] * len(UY_780_2018)] + [list(r) for r in GRID_780_2018[1:]]
        out = _text(_tri(rows, "millions"))
        assert "REJECT" in out, out
        assert "Total PYD" not in out, out

    def test_the_estimators_account_is_printed_whole(self, monkeypatch):
        """The positive control. A pack that printed its own arithmetic, or cut the
        estimator's note short as the first version did at 220 characters, fails here."""
        lines = ["  %d: planted step %d" % (2000 + i, i) for i in range(14)]
        planted = "\n".join(lines) + "\n  Total PYD = +99.000m (14 UW years)"
        monkeypatch.setattr(test_gemini, "compute_pyd_from_triangle",
                            lambda tri, year: (99.0, planted))
        out = _text(_tri(GRID_780_2018, "millions"))
        missing = [ln for ln in lines if ln not in out]
        assert not missing, (missing, out)
        assert "Total PYD = +99.000m" in out, out


class TestThePackNamesTheAdoptedFiguresSource:
    """R197: a record that keeps an overruled triangle says so."""

    REGISTER = {
        "sign_veto_overrides": {"records": [
            {"stem": "syndicate_2001_2022", "adopted_gbp_m": -256.3,
             "overruled_triangle_gbp_m": 969.6,
             "source_of_adopted_figure": "the filing's provisions note"}]},
        "rejected_by_current_rules": {"records": [
            {"stem": "syndicate_2008_2021", "adopted_gbp_m": 383.9,
             "why_the_current_rules_reject_the_stored_triangle": "planted reason"}]},
    }

    def _use(self, tmp_path, monkeypatch):
        p = tmp_path / "overruled.json"
        p.write_text(json.dumps(self.REGISTER), encoding="utf-8")
        monkeypatch.setattr(pack, "OVERRULED", p)

    def test_an_overruled_triangle_is_named(self, tmp_path, monkeypatch):
        self._use(tmp_path, monkeypatch)
        text = "\n".join(pack._source_note("syndicate_2001_2022"))
        assert "OVERRULED" in text and "+969.6m" in text and "-256.3m" in text, text
        assert "provisions note" in text, text

    def test_a_rejected_triangle_is_named(self, tmp_path, monkeypatch):
        self._use(tmp_path, monkeypatch)
        text = "\n".join(pack._source_note("syndicate_2008_2021"))
        assert "planted reason" in text, text

    def test_a_record_outside_the_register_gets_no_note(self, tmp_path, monkeypatch):
        self._use(tmp_path, monkeypatch)
        assert pack._source_note("syndicate_1234_2020") == []

    def test_a_missing_register_is_not_an_error(self, tmp_path, monkeypatch):
        monkeypatch.setattr(pack, "OVERRULED", tmp_path / "absent.json")
        assert pack._source_note("syndicate_2001_2022") == []



class TestR207_AnHtmlFilingIsReadFromItsConvertedPdf:
    """A report filed as HTML has no PDF under syndicate_reports/pdfs; the driver converts it to
    pdf_extraction/html_converted/<stem>.pdf, and the record's page numbers refer to that file."""

    def _pdf(self, path, text):
        import fitz
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), text)
        doc.save(str(path))
        doc.close()

    def test_the_converted_pdf_is_read(self, tmp_path, monkeypatch):
        filed = tmp_path / "pdfs"
        filed.mkdir()
        extracted = tmp_path / "pdf_extraction"
        (extracted / "html_converted").mkdir(parents=True)
        (filed / "syndicate_9999_2024.html").write_text("<html></html>", encoding="utf-8")
        self._pdf(extracted / "html_converted" / "syndicate_9999_2024.pdf",
                  "The prior year releases amounted to 12.3m in the year to 31 December.")
        monkeypatch.setattr(pack, "PDFS", filed)
        monkeypatch.setattr(pack, "EXTRACTED", extracted)
        text = "\n".join(pack._narrative("syndicate_9999_2024", 5))
        assert "converted" in text, text
        assert "12.3m" in text, text
        assert "not in this checkout" not in text, text

    def test_a_filing_in_neither_place_says_so(self, tmp_path, monkeypatch):
        monkeypatch.setattr(pack, "PDFS", tmp_path / "pdfs")
        monkeypatch.setattr(pack, "EXTRACTED", tmp_path / "pdf_extraction")
        text = "\n".join(pack._narrative("syndicate_9999_2024", 5))
        assert "not in this checkout" in text, text
