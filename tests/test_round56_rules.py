"""The four rules the consolidated review of 11 September 2026 required (R138-R141).

Each test plants the defect the review found, from the filing that carried it, and
requires the corrected rule to reject it. Where a filing's own arithmetic settles the
right answer, that is the assertion, so a rule that merely stops producing the wrong
number does not pass.

  R138  `2010 & prior years` is a cohort's cumulative incurred total, and became
        1274/2019's prior-year development because the provisions parser matched any
        row containing `prior` and a `year`, and the cross-validator treated a sign
        disagreement as proof the provisions note was the movement.
  R139  `After 12 months` named no development-period pattern, so 2003/2015's grid was
        handed to the positional text parser, which read the row labels as money and an
        empty cohort column's dashes as a leading row of zeros -- and the staircase
        scorer gave the result 1.00.
  R140  1618/2023 prints incurred claims as outflows, so differencing the presented
        values reversed the sign of a 3.7m adverse movement.
  R141  5820/2016's 60.2 and 60.3 carry a superscript footnote 1, which the table
        backend flattened into the cell text as 60.21 and 60.31.
"""
import io
import json
import os
import shutil
import pathlib
import sys

import ast
import inspect

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import table_extraction as te            # noqa: E402
import test_gemini as tg                 # noqa: E402

PDFS = os.path.join(ROOT, "syndicate_reports", "pdfs")
AZURE = os.path.join(ROOT, "pdf_extraction", "azure_output")


def _cached_grid(stem, page, needle):
    """One grid as the table backend recorded it, or a skip when the clone has no cache."""
    path = os.path.join(AZURE, "%s_azure.json" % stem)
    if not os.path.exists(path):
        pytest.skip("no committed Azure cache for %s in this clone" % stem)
    with open(path, encoding="utf-8") as fh:
        tables = json.load(fh).get("tables") or []
    for t in tables:
        if not isinstance(t, dict) or not t.get("grid"):
            continue
        if page is not None and t.get("orig_page") != page:
            continue
        if needle in json.dumps(t["grid"]):
            return t["grid"]
    pytest.skip("%s: no cached grid carrying %r" % (stem, needle))


# ── R138: a cohort row is not a movement row ────────────────────────────────

class TestCohortRowIsNotAMovement:

    def test_the_1274_2019_triangle_yields_no_provisions_movement(self):
        """The grid that supplied +602.8m is a development triangle, and its
        `2010 & prior years` row is that cohort's cumulative incurred total."""
        grid = _cached_grid("syndicate_1274_2019", None, "2010 & prior years")
        prov = te._parse_nutrient_provisions(grid, 2019)
        assert prov is None or prov.gross_prior_year_claims is None, (
            "a cohort row was read as a prior-year movement: %s"
            % (prov.to_dict() if prov else None))

    @pytest.mark.parametrize("label", [
        "2010 & prior years", "2010 and prior", "2015 & Prior Years",
        "prior years", "Prior Years", "(2010) & prior",
    ])
    def test_every_spelling_of_a_cohort_label_is_recognised(self, label):
        assert te.COHORT_LABEL.search(label.strip().lower()), label

    @pytest.mark.parametrize("label", [
        "claims incurred in prior underwriting years",
        "movement in prior year's provision",
        "prior year claims development",
    ])
    def test_a_genuine_movement_row_label_is_not_a_cohort_label(self, label):
        assert not te.COHORT_LABEL.search(label.strip().lower()), label

    def test_a_movement_note_records_that_it_is_one(self):
        """The semantics are recorded, not merely used: the caller has to be able to
        require them before letting a provisions figure override a triangle."""
        grid = [
            ["", "2023 Gross", "Reinsurance", "Net"],
            ["Movement in provision for claims outstanding", "", "", ""],
            ["Brought forward at 1 January", "1,000", "(200)", "800"],
            ["Claims incurred in prior underwriting years", "78,241", "(1,000)", "77,241"],
        ]
        prov = te._parse_nutrient_provisions(grid, 2023)
        assert prov is not None and prov.gross_prior_year_claims is not None
        sem = prov.movement_semantics
        assert sem["table_is_movement_note"] is True
        assert sem["column_bound_to_report_year"] is True
        assert "prior underwriting years" in sem["row_label"].lower()

    def test_a_triangle_is_not_a_movement_note(self):
        grid = [
            ["Pure underwriting year", "2010 & Prior", "2021", "2022", "2023"],
            ["After 12 months", "", "100", "110", "120"],
            ["After 24 months", "", "150", "160", ""],
            ["2010 & prior years", "602,757", "", "", ""],
        ]
        prov = te._parse_nutrient_provisions(grid, 2023)
        assert prov is None or prov.gross_prior_year_claims is None, (
            prov.to_dict() if prov else None)


# ── R139: every cell bound to a year and an age ─────────────────────────────

class TestTriangleCellBinding:

    def test_2003_2015_parses_from_its_own_grid(self):
        """The filing's mature 2011-2013 columns give 25,217 thousand:
        (1,632,929-1,626,368)+(1,417,912-1,387,589)+(1,340,757-1,352,424)."""
        grid = _cached_grid("syndicate_2003_2015", 41, "After 12 months")
        tri, details = te._parse_nutrient_triangle(grid, 2015)
        assert isinstance(tri, te.TriangleData), details
        assert tri.cell_binding == "header"
        assert tri.row_labels and tri.row_labels[0].lower().startswith("after 12")
        pyd, _d = tg.compute_pyd_from_triangle(tri.to_dict(), 2015)
        assert pyd == pytest.approx(25.217, abs=0.001), pyd

    @pytest.mark.parametrize("label", ["After 12 months", "after 24 months",
                                       "After twelve months"])
    def test_a_months_label_names_a_development_period(self, label):
        """The single missing pattern. Without it the grid parser found no development
        rows at all and the page went to the positional text parser."""
        grid = [
            ["Pure underwriting year", "2011", "2012", "2013"],
            [label, "100", "110", "120"],
            ["After 36 months", "150", "160", ""],
            ["After 48 months", "170", "", ""],
        ]
        tri, details = te._parse_nutrient_triangle(grid, 2013)
        assert isinstance(tri, te.TriangleData), "%s: %s" % (label, details)

    def test_the_text_parser_declines_a_leading_row_of_zeros(self):
        text = "\n".join([
            "2011 2012 2013 2014 2015",
            "- - - - -",
            "884348", "804948", "718532", "786671", "723602",
            "1583052", "1395594", "1352424", "1508444",
        ])
        tri, why = te._parse_triangle_from_text(text, 2015)
        assert tri is None, why
        assert "zero" in why.lower(), why

    def test_the_structure_score_rejects_a_fabricated_zero_row(self):
        """It scored 1.00 on 2003/2015 because the shape was right and only the
        contents were wrong."""
        rows = [[0.0, 0.0, 0.0, 0.0, 0.0],
                [0.0, 0.0, 12.0, 884348.0, None],
                [804948.0, 718532.0, 786671.0, None, None],
                [723602.0, 24.0, None, None, None],
                [1583052.0, None, None, None, None]]
        assert tg._validate_triangle_structure([2011, 2012, 2013, 2014, 2015],
                                               rows, 2015) == 0.0

    def test_a_real_staircase_still_scores(self):
        rows = [[1.0, 2.0, 3.0], [4.0, 5.0, None], [6.0, None, None]]
        assert tg._validate_triangle_structure([2011, 2012, 2013], rows, 2013) > 0.5


# ── R140: presentation sign normalised before differencing ──────────────────

class TestOutflowPresentation:

    def test_1618_2023_is_an_adverse_3_7m_movement(self):
        """The filing prints 2021 as (123.0), (266.9), (270.6): the estimate grew from
        266.9 to 270.6, so the movement is +3.7m, not -3.7m."""
        tri = {"type": "gross", "currency": "USD", "units": "millions",
               "underwriting_years": [2021, 2022, 2023],
               "development_rows": [[-123.0, -274.1, -254.9],
                                    [-266.9, -479.5, None],
                                    [-270.6, None, None]]}
        pyd, details = tg.compute_pyd_from_triangle(tri, 2023)
        assert pyd == pytest.approx(3.7, abs=0.001), (pyd, details)
        assert tri.get("presentation_sign") == "outflow"

    def test_an_ordinary_triangle_is_left_alone(self):
        tri = {"type": "gross", "currency": "USD", "units": "millions",
               "underwriting_years": [2021, 2022, 2023],
               "development_rows": [[123.0, 274.1, 254.9],
                                    [266.9, 479.5, None],
                                    [270.6, None, None]]}
        pyd, _d = tg.compute_pyd_from_triangle(tri, 2023)
        assert pyd == pytest.approx(3.7, abs=0.001), pyd
        assert "presentation_sign" not in tri

    def test_a_release_presented_as_an_outflow_stays_a_release(self):
        """Normalising the sign must not turn every movement adverse."""
        tri = {"type": "gross", "currency": "USD", "units": "millions",
               "underwriting_years": [2021, 2022, 2023],
               "development_rows": [[-123.0, -274.1, -254.9],
                                    [-266.9, -479.5, None],
                                    [-260.6, None, None]]}
        pyd, _d = tg.compute_pyd_from_triangle(tri, 2023)
        assert pyd == pytest.approx(-6.3, abs=0.001), pyd

    def test_a_mixed_sign_triangle_is_not_normalised(self):
        """Only a grid that is wholly non-positive is an outflow presentation."""
        tri = {"type": "gross", "currency": "USD", "units": "millions",
               "underwriting_years": [2021, 2022, 2023],
               "development_rows": [[-123.0, 274.1, -254.9],
                                    [-266.9, 479.5, None],
                                    [-270.6, None, None]]}
        tg.compute_pyd_from_triangle(tri, 2023)
        assert "presentation_sign" not in tri


# ── R141: a proven footnote marker, removed ─────────────────────────────────

class TestSuperscriptFootnotes:

    FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures",
                           "footnote_spans_5820_2016.json")

    def _corrections(self, stem):
        """The corrections the typography proves, from the committed fixture.

        The filings are not redistributed with this repository, so a test that reads one
        skips everywhere except the machine that has them -- silently, which is how a
        repair goes unverified while its suite reports green. The fixture carries the
        spans themselves, so the rule is exercised in any clone (R178)."""
        assert stem == "syndicate_5820_2016", stem
        fx = json.load(io.open(self.FIXTURE, encoding="utf-8"))
        return te.footnote_corrections_from_lines(fx["lines"])

    def test_the_fixture_says_what_the_whole_filing_says(self):
        """Where the filing is present, the fixture has to agree with it exactly, so it
        cannot drift away from its source unnoticed."""
        pdf = os.path.join(PDFS, "syndicate_5820_2016.pdf")
        if not os.path.exists(pdf):
            pytest.skip("source filing is not in this clone; the fixture stands alone")
        if te.fitz is None:
            pytest.skip("PyMuPDF not installed")
        assert te.superscript_footnote_corrections(pdf) == \
            self._corrections("syndicate_5820_2016")

    def test_5820_2016_markers_are_found_from_the_typography(self):
        c = self._corrections("syndicate_5820_2016")
        assert c.get("60.21") == "60.2", c
        assert c.get("60.31") == "60.3", c
        assert c.get("58.51") == "58.5", c

    def test_the_corrected_grid_gives_the_filings_own_arithmetic(self):
        """The filing shows 1.9+3.2+7.7+25.6 = 38.4m; the corrupted cells gave 38.38."""
        grid = _cached_grid("syndicate_5820_2016", None, "58.51")
        c = self._corrections("syndicate_5820_2016")
        fixed = te.apply_footnote_corrections(grid, c)
        tri, details = te._parse_nutrient_triangle(fixed, 2016)
        assert isinstance(tri, te.TriangleData), details
        pyd, _d = tg.compute_pyd_from_triangle(tri.to_dict(), 2016)
        assert pyd == pytest.approx(38.4, abs=0.001), pyd

    def test_a_genuine_two_decimal_cell_is_not_truncated(self):
        """The rule is evidence, not precision: nothing is stripped without a
        superscript span behind it."""
        grid = [["x", "60.21", "12.34"]]
        assert te.apply_footnote_corrections(grid, {}) == grid
        assert te.apply_footnote_corrections(grid, {"60.21": "60.2"}) == [["x", "60.2", "12.34"]]


# ── the offline guard the replay found missing ──────────────────────────────

class TestOfflineCoversAdjudication:

    def test_the_adjudicator_refuses_to_call_an_api_offline(self, monkeypatch):
        """An `--offline` replay reached the adjudicator and bought inference, which is
        the opposite of what the flag promises (R148)."""
        import adjudicate
        monkeypatch.setenv("LLOYDS_EXTRACTION_OFFLINE", "1")
        monkeypatch.setattr(adjudicate, "_adj_cache_load",
                            lambda key: (None, 0, 0, False))
        with pytest.raises(RuntimeError) as exc:
            adjudicate.call_adjudicator("nonexistent.pdf", "prompt", None,
                                        syndicate_num=1200, report_year=2017,
                                        field="gross_premiums_written_gbp_m")
        assert "offline" in str(exc.value).lower(), str(exc.value)


class TestStaircaseZerosAndStructureThreshold:
    """Found by adjudicating the largest movements the corrected rules produced, not by
    reading the review: a dash beyond the staircase was read as a zero estimate, and the
    structure score the guide said rejects a triangle rejected nothing."""

    #: 780/2018's grid, in the filing's millions, with the upper-right dashes as the
    #: backend recorded them.
    #:
    #: Where -21.3 comes from, so that it is the filing's arithmetic and not a number
    #: copied out of a run. The estimator takes each prior underwriting year's last
    #: development step and drops the PYD_EXCLUDED_RECENT_UW_YEARS = 2 most recent years,
    #: so for a 2018 report the years are 2011 to 2016:
    #:
    #:   2011  233.6 - 240.5 = -6.9      2014  122.9 - 121.0 = +1.9
    #:   2012  120.6 - 122.0 = -1.4      2015  168.6 - 173.5 = -4.9
    #:   2013   97.6 - 101.9 = -4.3      2016  193.8 - 199.5 = -5.7
    #:
    #:   -6.9 - 1.4 - 4.3 + 1.9 - 4.9 - 5.7 = -21.3
    #:
    #: The filing's narrative on page 1 reports prior-year reserve releases of $20.5m. That
    #: is corroboration of the sign and the size, not a tie-out: the narrative does not
    #: state its basis, and 2017 alone moves +66.5, so which years it counts changes the
    #: figure far more than the 0.8 difference. The test asserts the grid's arithmetic.
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

    def _tri(self, rows, uy, units="millions"):
        return {"type": "gross", "currency": "USD", "units": units,
                "underwriting_years": list(uy), "development_rows": [list(r) for r in rows]}

    def test_780_2018_reproduces_the_diagonal_of_its_own_grid(self):
        pyd, details = tg.compute_pyd_from_triangle(
            self._tri(self.GRID_780_2018, self.UY_780_2018), 2018)
        assert pyd == pytest.approx(-21.3, abs=0.001), (pyd, details)
        assert "beyond the staircase" in details

    def test_the_uncorrected_grid_would_have_given_a_false_release(self):
        """What the defect produced, so the test fails if the repair is removed."""
        rows = tg._null_zeros_beyond_the_staircase(
            self.UY_780_2018, self.GRID_780_2018, 2018)
        assert rows[1][7] is None and rows[6][2] is None
        assert rows[0][7] == 104.2, "a cell inside the staircase must not be touched"
        assert rows[7][0] == 233.6

    def test_a_genuine_zero_inside_the_staircase_survives(self):
        """Nil claims activity in a real development period is a real zero."""
        rows = [[10.0, 20.0, 30.0], [0.0, 25.0, None], [12.0, None, None]]
        out = tg._null_zeros_beyond_the_staircase([2011, 2012, 2013], rows, 2013)
        assert out[1][0] == 0.0, out

    def test_the_structure_threshold_is_enforced(self):
        """The guide has always said a triangle below the threshold is rejected."""
        # A full rectangle: every column filled to the bottom, so only the two oldest
        # are within a row of the staircase the shape should have.
        bad = [[float(10 * r + c) for c in range(6)] for r in range(6)]
        pyd, why = tg.compute_pyd_from_triangle(
            self._tri(bad, [2011, 2012, 2013, 2014, 2015, 2016]), 2016)
        assert pyd is None
        assert "structure score" in why, why

    def test_the_threshold_is_the_one_the_guide_states(self):
        guide = os.path.join(ROOT, "docs", "ocr-pipeline.md")
        if not os.path.exists(guide):
            pytest.skip("the OCR guide is not in this clone")
        with open(guide, encoding="utf-8") as fh:
            text = fh.read()
        want = "structure score < %s are rejected" % tg.MIN_TRIANGLE_STRUCTURE_SCORE
        assert want in text, want


class TestTheExpensiveBackendIsOptIn:
    """Document intelligence is the costly call. It must not be reachable by default."""

    KEYS = ("LLOYDS_EXTRACTION_OFFLINE", "LLOYDS_TABLE_BACKENDS_FROM_CACHE",
            "LLOYDS_ALLOW_TABLE_BACKEND_CALLS")

    def test_a_plain_run_serves_table_backends_from_cache(self, monkeypatch):
        for k in self.KEYS:
            monkeypatch.delenv(k, raising=False)
        assert te._table_cache_only() is True

    def test_only_the_named_opt_in_permits_a_call(self, monkeypatch):
        for k in self.KEYS:
            monkeypatch.delenv(k, raising=False)
        monkeypatch.setenv("LLOYDS_ALLOW_TABLE_BACKEND_CALLS", "1")
        assert te._table_cache_only() is False

    def test_a_miss_is_an_error_rather_than_a_call(self, monkeypatch):
        for k in self.KEYS:
            monkeypatch.delenv(k, raising=False)
        with pytest.raises(RuntimeError) as exc:
            te._table_cache_guard("Azure Document Intelligence for X.pdf")
        assert "LLOYDS_ALLOW_TABLE_BACKEND_CALLS" in str(exc.value)

    def _pdf_and_stale_cache(self, tmp_path, monkeypatch):
        """A real one-page PDF and a cache for it whose version is stale.

        A stale `_cache_version` is the condition that used to unlink the cache and
        re-extract all 1,066 records. `_extract_azure` reads the PDF before it reads the
        cache, so the PDF has to exist -- with a missing file the call fails earlier and a
        deletion test passes without testing anything."""
        fitz = pytest.importorskip("fitz")
        # `_find_relevant_pages` and `_extract_azure` write the OCR page cache through a
        # path relative to the working directory. Run from the repository root, this
        # fixture wrote syndicate_9999_2020.json into the real pdf_extraction/
        # ocr_page_cache/, where `git status` showed it after the round-56 replay. It runs
        # from tmp_path now, as tests/test_offline_replay.py already did (R192).
        (tmp_path / "pdf_extraction" / "ocr_page_cache").mkdir(parents=True, exist_ok=True)
        monkeypatch.chdir(tmp_path)
        # Built from the classifier's own vocabulary: a page needs two keywords from one
        # category to be relevant, and a fixture that hard-codes them goes stale silently
        # the next time the vocabulary moves.
        category = sorted(te._PAGE_KEYWORDS)[0]
        words = list(te._PAGE_KEYWORDS[category])[:4]
        assert len(words) >= 2, "the classifier needs two keywords to match a page"
        doc = fitz.open()
        page = doc.new_page()
        y = 120
        for word in words:
            page.insert_text((72, y), str(word), fontsize=10)
            y += 18
        # enough body text that the PDF reads as native rather than scanned
        for i in range(12):
            page.insert_text((72, y), "Gross claims incurred after %d months 1,234" % (12 * (i + 1)),
                             fontsize=9)
            y += 14
        pdf = tmp_path / "syndicate_9999_2020.pdf"
        doc.save(str(pdf))
        matches, _texts, _method, _rot = te._find_relevant_pages(pdf)
        assert matches, ("the fixture PDF matched no page category, so it would never "
                         "reach the cache and this test would pass vacuously")
        cache_dir = tmp_path / "azure_output"
        cache_dir.mkdir()
        cache = cache_dir / "syndicate_9999_2020_azure.json"
        payload = {"_cache_version": te._CACHE_VERSION - 1, "tables": [],
                   "pages_sent": [1], "batch_mode": False}
        io.open(str(cache), "w", encoding="utf-8").write(json.dumps(payload))
        return pdf, cache_dir, cache

    def test_no_code_path_deletes_a_committed_backend_cache(self, tmp_path, monkeypatch):
        """A cache file is a committed, publicly cited artefact. A run that unlinks one
        and then fails has destroyed evidence and produced nothing.

        Every deletion primitive is made to raise, so this holds however the call is
        spelled -- the previous form of this test grepped for the literal
        `cache_file.unlink()` and a rename would have defeated it."""
        for k in self.KEYS:
            monkeypatch.delenv(k, raising=False)
        pdf, cache_dir, cache = self._pdf_and_stale_cache(tmp_path, monkeypatch)
        before = io.open(str(cache), "rb").read()

        def refuse(*a, **k):
            raise AssertionError("a committed backend cache was deleted")

        monkeypatch.setattr(pathlib.Path, "unlink", refuse)
        monkeypatch.setattr(os, "remove", refuse)
        monkeypatch.setattr(os, "unlink", refuse)
        monkeypatch.setattr(shutil, "rmtree", refuse)
        # A stale cache is served rather than refused: a committed cache written by an
        # older code version is still the evidence (R159). What must not happen is the
        # unlink that used to precede re-extraction.
        te._extract_azure(pdf, 2020, cache_dir)
        assert cache.exists(), "the stale cache was removed"
        assert io.open(str(cache), "rb").read() == before, "the stale cache was rewritten"

    def test_a_cache_that_is_absent_is_an_error_rather_than_a_call(self, tmp_path,
                                                                  monkeypatch):
        """The guard fires on a missing cache, which is the record that would otherwise
        reach a paid extraction."""
        for k in self.KEYS:
            monkeypatch.delenv(k, raising=False)
        pdf, cache_dir, cache = self._pdf_and_stale_cache(tmp_path, monkeypatch)
        cache.unlink()
        with pytest.raises(RuntimeError) as exc:
            te._extract_azure(pdf, 2020, cache_dir)
        assert "LLOYDS_ALLOW_TABLE_BACKEND_CALLS" in str(exc.value), str(exc.value)

    def test_the_fixture_leaves_the_repository_cache_alone(self, tmp_path, monkeypatch):
        """The control for R192: the repository's cache must not gain the fixture's page.

        Asserted on the one file the fixture would write, not on a directory listing. The
        polluted file was already present when this was written, so a listing taken
        before and after would have matched with the fix or without it."""
        for k in self.KEYS:
            monkeypatch.delenv(k, raising=False)
        polluted = os.path.join(ROOT, "pdf_extraction", "ocr_page_cache",
                                "syndicate_9999_2020.json")
        assert not os.path.exists(polluted), (
            "the repository already holds the fixture's OCR cache; move it out first, or "
            "this control cannot tell whether the fixture writes it")
        pdf, cache_dir, _cache = self._pdf_and_stale_cache(tmp_path, monkeypatch)
        te._extract_azure(pdf, 2020, cache_dir)
        assert not os.path.exists(polluted), "the fixture wrote into the repository's cache"
        assert (tmp_path / "pdf_extraction" / "ocr_page_cache").is_dir()

    def test_the_prompt_version_cannot_reach_the_backend_cache_key(self, tmp_path,
                                                                   monkeypatch):
        """Correcting the model prompt must cost model calls and nothing else: the two
        caches are keyed independently, which is why one can be re-run without the other.

        Computed under two prompt versions rather than read off the source text."""
        for k in self.KEYS:
            monkeypatch.delenv(k, raising=False)
        monkeypatch.setattr(tg, "PROMPT_VERSION", "9.98")
        first = tg._llm_cache_key("gpt-5-mini", "a prompt", 9999, 2020)
        monkeypatch.setattr(tg, "PROMPT_VERSION", "9.99")
        second = tg._llm_cache_key("gpt-5-mini", "a prompt", 9999, 2020)
        assert first != second, "the model cache does not follow the prompt version"

        # The same two versions must leave the expensive backend's cache alone. Its key is
        # the file stem, the cache version and the page set; nothing about the prompt.
        pdf, cache_dir, cache = self._pdf_and_stale_cache(tmp_path, monkeypatch)
        seen = set()
        for version in ("9.98", "9.99"):
            monkeypatch.setattr(tg, "PROMPT_VERSION", version)
            te._extract_azure(pdf, 2020, cache_dir)
            seen.add(tuple(sorted(q.name for q in cache_dir.iterdir())))
        assert len(seen) == 1, ("the backend cache file set moved with the prompt "
                                "version: %s" % seen)
        assert cache.exists()


class TestR193_TheSignVetoHoldsWhateverTheTrianglesShape:
    """R164 let a header-bound, gross, well-shaped triangle skip the sign veto, on the ground
    that two models reading one prompt are one opinion counted twice. R193 withdrew it
    (owner's decision, 13 September 2026): shape says nothing about whether the diagonal is
    the syndicate's own development, and 73 records carried a figure only because of it."""

    #: 1183/2022 as the filing prints it: gross earned ultimates in $m, ten underwriting
    #: years, a clean staircase. The diagonal gives +74.9m. It is the case R164 was written
    #: for, so it is the case the veto must now hold on.
    UW = [2013, 2014, 2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022]
    ROWS = [
        [304.9, 310.3, 266.9, 264.3, 473.8, 316.1, 279.8, 291.4, 375.4, 450.2],
        [554.5, 571.2, 500.2, 567.5, 765.5, 634.8, 727.9, 550.1, 810.1, None],
        [532.7, 607.9, 511.6, 594.2, 786.8, 722.0, 752.0, 583.3, None, None],
        [529.2, 585.8, 522.5, 594.6, 780.1, 731.9, 756.5, None, None, None],
        [527.5, 596.4, 536.9, 605.4, 771.8, 797.2, None, None, None, None],
        [519.8, 583.2, 524.6, 615.7, 763.5, None, None, None, None, None],
        [495.4, 563.3, 518.7, 615.5, None, None, None, None, None, None],
        [482.1, 573.7, 537.8, None, None, None, None, None, None, None],
        [485.0, 540.6, None, None, None, None, None, None, None, None],
        [479.4, None, None, None, None, None, None, None, None, None],
    ]

    def _tri(self, **over):
        t = {"type": "gross", "currency": "USD", "units": "millions",
             "cell_binding": "header", "underwriting_years": list(self.UW),
             "development_rows": [list(r) for r in self.ROWS]}
        t.update(over)
        return t

    def test_the_filings_own_triangle_gives_74_9(self):
        """The estimator is not what changed: the triangle still computes to +74.9m."""
        pyd, details = tg.compute_pyd_from_triangle(self._tri(), 2022)
        assert pyd == pytest.approx(74.9, abs=0.001), (pyd, details)

    def test_a_well_shaped_gross_triangle_does_not_beat_two_agreeing_models(self):
        """Both models said -57.8 against the triangle's +74.9. Their figure stands; whether
        it belongs in the gross sample is the analysis's basis rule to decide."""
        ok, why = tg._pyd_override_gate(74.9, [-57.8, -57.8], 1806.7)
        assert ok is False
        assert "opposite sign" in why

    def test_3010_2022_keeps_the_figure_its_provisions_note_prints(self):
        """The regression that decided the revert, with the inputs its record carries: the
        filing's provisions note prints gross 'Change in prior year provisions 146,569'
        (GBP000), both models read 146.569, and the exempted triangle gave -10.926 on
        opening reserves of 118.866."""
        ok, why = tg._pyd_override_gate(-10.926, [146.569, 146.569], 118.866)
        assert ok is False, why
        assert "-10.926m" in why

    def test_the_gate_takes_no_triangle(self):
        """The exemption came in as keyword arguments carrying the triangle. With none, a
        call site has nothing to pass and the veto cannot depend on shape."""
        params = inspect.signature(tg._pyd_override_gate).parameters
        assert not [p for p in params if "triangle" in p or p == "report_year"], list(params)

    def test_the_magnitude_veto_is_untouched(self):
        ok, why = tg._pyd_override_gate(900.0, [1.0, 1.0], 1000.0)
        assert ok is False and "opening reserves" in (why or "")

    def test_a_figure_the_models_agree_with_is_still_applied(self):
        """Control: the veto is about opposition to both models, not about triangles."""
        assert tg._pyd_override_gate(74.9, [70.0, 80.0], 1806.7) == (True, None)


class TestR167_TriangleBasisFromItsOwnHeading:
    """A triangle's `type` label came from a grid-wide default -- gross unless "net" appears
    and "gross" appears nowhere -- so a net block on a grid that mentions gross anywhere was
    labelled gross. Round 55 fixed this for the transposed parser (B2-05); the main grid
    parser was missed. The label is load-bearing: the analysis reads the route's
    `triangle_type` to decide a figure's basis."""

    def _grid(self):
        """A page printing the gross triangle above the net one, as filings do."""
        return [
            ["Pure underwriting year", "2018", "2019", "2020", "2021"],
            ["Estimate of gross claims incurred:", "", "", "", ""],
            ["After 12 months", "100", "110", "120", "130"],
            ["After 24 months", "150", "160", "170", ""],
            ["After 36 months", "180", "190", "", ""],
            ["Net of reinsurance", "", "", "", ""],
            ["Estimate of net claims incurred:", "", "", "", ""],
            ["After 12 months", "70", "77", "84", "91"],
            ["After 24 months", "105", "112", "119", ""],
            ["After 36 months", "126", "133", "", ""],
        ]

    def test_a_net_block_is_not_labelled_gross(self):
        """The whole grid contains the word 'gross', so the old default said gross."""
        net_only = self._grid()[5:]
        net_only.insert(0, ["Pure underwriting year", "2018", "2019", "2020", "2021"])
        tri, details = te._parse_nutrient_triangle(net_only, 2021)
        assert isinstance(tri, te.TriangleData), details
        assert tri.type == "net", (tri.type, details)

    def test_a_gross_block_is_still_gross(self):
        gross_only = [self._grid()[0]] + self._grid()[1:5]
        tri, details = te._parse_nutrient_triangle(gross_only, 2021)
        assert isinstance(tri, te.TriangleData), details
        assert tri.type == "gross", (tri.type, details)

class TestR168_StaircaseLimitFromTheYearNotThePosition:
    """14 of 828 stored triangles have non-consecutive underwriting years. The positional
    formula gave every column older than a gap the wrong limit."""

    def test_a_gapped_year_list_gets_the_true_ages(self):
        """1110/2020 as stored: 2018 is missing."""
        assert tg._staircase_limit([2015, 2016, 2017, 2019, 2020], 2020) == [6, 5, 4, 2, 1]

    def test_a_consecutive_list_is_unchanged(self):
        assert tg._staircase_limit([2018, 2019, 2020, 2021, 2022], 2022) == [5, 4, 3, 2, 1]

    def test_a_run_off_syndicate_is_unchanged(self):
        """max underwriting year before the report year: the ages simply run higher."""
        assert tg._staircase_limit([2015, 2016, 2017], 2020) == [6, 5, 4]

    def test_a_real_value_beyond_the_positional_limit_survives(self):
        """The column before the gap reaches one development period further than its
        position implies. A genuine estimate there must not be nulled."""
        uw = [2015, 2016, 2017, 2019, 2020]
        rows = [[10.0, 20.0, 30.0, 40.0, 50.0],
                [11.0, 21.0, 31.0, 41.0, None],
                [12.0, 22.0, 32.0, None, None],
                [13.0, 23.0, None, None, None],
                [14.0, 24.0, None, None, None],
                [15.0, None, None, None, None]]
        out = tg._null_zeros_beyond_the_staircase(uw, rows, 2020)
        assert out[5][0] == 15.0, "a real sixth-period value for 2015 was discarded"

    def test_a_zero_beyond_a_gapped_column_is_still_nulled(self):
        uw = [2015, 2016, 2017, 2019, 2020]
        rows = [[10.0, 20.0, 30.0, 40.0, 50.0],
                [11.0, 21.0, 31.0, 0.0, 0.0],
                [12.0, 22.0, 32.0, 0.0, 0.0]]
        out = tg._null_zeros_beyond_the_staircase(uw, rows, 2020)
        assert out[1][4] is None and out[2][3] is None, out


class TestR189_ATriangleSmallerThanItsTwinIsTheNetOne:
    """Two filings print gross and net with the same years, units and shape and label
    neither readably. The selection score gives 1000 for type == "gross", so in 2015/2023
    the net triangle won BECAUSE it had been mislabelled gross."""

    def _candidates(self, stem, year):
        cache = os.path.join(ROOT, "pdf_extraction", "azure_output",
                             "%s_azure.json" % stem)
        if not os.path.exists(cache):
            pytest.skip("the committed cache for %s is not in this clone" % stem)
        tabs = json.load(io.open(cache, encoding="utf-8")).get("tables") or []
        out = []
        for tab in tabs:
            g = tab.get("grid")
            if not g:
                continue
            p, _d = te._parse_nutrient_triangle(g, year)
            if isinstance(p, te.TriangleData):
                out.append(p)
        assert out, "no triangle parsed from %s; this test would prove nothing" % stem
        return out

    def _chosen(self, cands):
        best, score = None, -1
        for c in cands:
            s = ((1000 if c.type == "gross" else 0) + len(c.underwriting_years) * 10
                 + sum(1 for r in c.development_rows for v in r if v is not None))
            if s > score:
                best, score = c, s
        return best

    def test_2015_2023_is_relabelled_net(self):
        """Gross 2018 column 87,854; net 62,479. The "Net" heading is a label-only row at
        the foot of the GROSS table, orphaned when the backend split the two."""
        cands = self._candidates("syndicate_2015_2023", 2023)
        best = self._chosen(cands)
        assert best.type == "gross", "the defect is gone; this test no longer reproduces it"
        assert best.development_rows[0][0] == 62479.0, best.development_rows[0][:3]
        out, note = te.relabel_if_smaller_than_its_twin(best, cands)
        assert out.type == "net", note
        assert note and "R189" in note

    def test_1882_2016_is_relabelled_net(self):
        """Both tables carry identical labels and neither names a basis."""
        cands = self._candidates("syndicate_1882_2016", 2016)
        best = self._chosen(cands)
        assert best.type == "gross"
        out, note = te.relabel_if_smaller_than_its_twin(best, cands)
        assert out.type == "net", note

    def _tri(self, rows, type_="gross", units="millions"):
        return te.TriangleData(
            type=type_, currency="GBP", units=units, units_evidence="header",
            underwriting_years=[2018, 2019, 2020],
            development_rows=[list(r) for r in rows])

    def test_an_outflow_presentation_is_not_relabelled(self):
        """457 and 218 present their triangles as outflows, where the GROSS figure is the
        more negative one. A signed comparison called nine of their correct records
        suspect; this is the control that keeps the rule off them."""
        gross = self._tri([[-208.0, -153.0, -143.0], [-269.0, -190.0, None],
                           [-280.0, None, None]])
        net = self._tri([[-194.0, -150.0, -135.0], [-250.0, -180.0, None],
                         [-260.0, None, None]])
        out, note = te.relabel_if_smaller_than_its_twin(gross, [gross, net])
        assert out.type == "gross", note

    def test_a_twin_twenty_times_larger_is_a_different_quantity(self):
        """6104 pairs a syndicate's share against a whole account. That is not a gross and
        net view of one book, and the band has to exclude it."""
        share = self._tri([[17.6, 27.7, 13.4], [25.0, 30.0, None], [28.0, None, None]])
        whole = self._tri([[337.6, 371.4, 249.2], [500.0, 600.0, None],
                           [560.0, None, None]])
        out, note = te.relabel_if_smaller_than_its_twin(share, [share, whole])
        assert out.type == "gross", note

    def test_too_few_shared_cells_decides_nothing(self):
        thin_a = self._tri([[10.0, None, None], [None, None, None], [None, None, None]])
        thin_b = self._tri([[14.0, None, None], [None, None, None], [None, None, None]])
        out, note = te.relabel_if_smaller_than_its_twin(thin_a, [thin_a, thin_b])
        assert out.type == "gross", note

    def test_a_genuine_gross_triangle_with_a_net_twin_is_left_alone(self):
        """The positive control: the larger of the pair keeps its label."""
        gross = self._tri([[100.0, 110.0, 120.0], [150.0, 160.0, None],
                           [180.0, None, None]])
        net = self._tri([[70.0, 77.0, 84.0], [105.0, 112.0, None], [126.0, None, None]],
                        type_="net")
        out, note = te.relabel_if_smaller_than_its_twin(gross, [gross, net])
        assert out.type == "gross", note
        assert note is None



def _statement_lists(node):
    """Every statement list under node: bodies, else-branches and finally-blocks."""
    for child in ast.walk(node):
        for field in ("body", "orelse", "finalbody"):
            block = getattr(child, field, None)
            if isinstance(block, list) and block and isinstance(block[0], ast.stmt):
                yield block


def _assigned(stmt, key):
    """The value that `result[key] = value` assigns in this statement, else None."""
    if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
        t = stmt.targets[0]
        if (isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name) and t.value.id == "result"
                and isinstance(t.slice, ast.Constant) and t.slice.value == key):
            return stmt.value
    return None


class TestR208_TheRouteNamesWhatProducedTheFigure:
    """The driver recorded route source "rag_triangle" for every figure its RAG step returned, and
    the triangle's keys whenever the step had kept one; its annotation said "RAG triangle computed"
    and its log "PYD confirmed by RAG triangle" whatever the method. 58 records named a triangle
    that did not produce their figure -- the provisions note, provisions text, a narrative parser,
    or a triangle the in-RAG sign check had overruled -- and the loader read 8 of them as
    cohort-enforced and took 33 bases from a triangle that was not the figure's."""

    TRI = {"type": "net", "units": "thousands", "source_page": 12, "underwriting_years": [2014, 2015]}

    @staticmethod
    def _module():
        return ast.parse(io.open(os.path.join(ROOT, "test_gemini.py"), encoding="utf-8").read())

    def _function(self, name):
        for node in self._module().body:
            if isinstance(node, ast.FunctionDef) and node.name == name:
                return node
        raise AssertionError("no function %s in test_gemini.py" % name)

    def test_a_provisions_figure_names_its_method_and_no_triangle(self):
        """1206/2014: 'No triangle, but found 3 reserve text page(s)', then 'Using provisions PYD as
        fallback: +31.600m'."""
        got = tg._rag_figure_source({"pyd": 31.6, "method": "provisions", "triangle": None,
                                     "pyd_from_triangle": False})
        assert got == ("rag_provisions", "RAG provisions", None)

    def test_a_kept_triangle_is_not_named_when_it_did_not_produce_the_figure(self):
        """1221/2016 (the in-RAG sign check used the provisions note) and 6125/2017 (a first-year
        triangle with no usable years, then the provisions fallback) keep a triangle their figure
        did not come from."""
        got = tg._rag_figure_source({"pyd": 3.1, "method": "provisions", "triangle": dict(self.TRI),
                                     "pyd_from_triangle": False})
        assert got[0] == "rag_provisions" and got[2] is None, got

    def test_a_triangles_figure_names_the_triangle(self):
        tri = dict(self.TRI)
        got = tg._rag_figure_source({"pyd": -13.9, "method": "azure", "triangle": tri, "pyd_from_triangle": True})
        assert got == ("rag_triangle", "RAG triangle", tri)

    def test_a_result_that_does_not_say_is_not_taken_for_a_triangle(self):
        got = tg._rag_figure_source({"pyd": 5.0, "method": "azure", "triangle": dict(self.TRI)})
        assert got[0] != "rag_triangle" and got[2] is None, got

    def test_every_figure_the_rag_step_assigns_says_whether_a_triangle_produced_it(self):
        fn = self._function("extract_pyd_from_relevant_pages")
        seen = 0
        for block in _statement_lists(fn):
            figures = [s for s in block if _assigned(s, "pyd") is not None]
            if not figures:
                continue
            flags = [v for v in (_assigned(s, "pyd_from_triangle") for s in block) if v is not None]
            where = "test_gemini.py line %d" % figures[0].lineno
            assert len(flags) == 1, "%s assigns a figure without saying whether a triangle produced it" % where
            assert isinstance(flags[0], ast.Constant) and isinstance(flags[0].value, bool), where
            keeps_triangle = any(v is not None and not (isinstance(v, ast.Constant) and v.value is None)
                                 for v in (_assigned(s, "triangle") for s in block))
            assert flags[0].value is keeps_triangle, "%s: flag %s, triangle assigned beside it %s" % (
                where, flags[0].value, keeps_triangle)
            seen += 1
        # two triangle paths (the table backend, LLM vision) and eight others
        assert seen >= 10, seen

    def test_the_rag_step_starts_from_no_triangle(self):
        fn = self._function("extract_pyd_from_relevant_pages")
        for node in ast.walk(fn):
            if (isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
                    and node.targets[0].id == "result" and isinstance(node.value, ast.Dict)):
                keys = {k.value: v for k, v in zip(node.value.keys, node.value.values) if isinstance(k, ast.Constant)}
                assert "pyd_from_triangle" in keys, sorted(keys)
                assert isinstance(keys["pyd_from_triangle"], ast.Constant) and keys["pyd_from_triangle"].value is False
                return
        raise AssertionError("the RAG step's result dict was not found")

    def test_no_route_or_annotation_names_a_triangle_unconditionally(self):
        mod = self._module()
        calls = [n for n in ast.walk(mod) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                 and n.func.id == "_record_pyd_route"]
        assert len(calls) >= 2, len(calls)
        for c in calls:
            source = c.args[1] if len(c.args) > 1 else None
            triangle = c.args[4] if len(c.args) > 4 else next((k.value for k in c.keywords if k.arg == "triangle"), None)
            assert not (isinstance(source, ast.Constant) and source.value == "rag_triangle"), \
                "line %d names a triangle whatever produced the figure" % c.lineno
            assert triangle is None or "rag_result" not in ast.unparse(triangle), \
                "line %d passes the RAG step's triangle whatever produced the figure" % c.lineno
        literals = [v.value for n in ast.walk(mod) if isinstance(n, ast.JoinedStr) for v in n.values
                    if isinstance(v, ast.Constant) and isinstance(v.value, str)]
        named = [s for s in literals if "RAG triangle computed" in s or "by RAG triangle" in s or "from RAG triangle" in s]
        assert not named, named
        apply_step = [f for f in mod.body if isinstance(f, ast.FunctionDef) and any(
            isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name) and n.targets[0].id == "rag_method"
            for n in ast.walk(f))]
        assert len(apply_step) == 1, [f.name for f in apply_step]
        tri_type = [n for n in ast.walk(apply_step[0]) if isinstance(n, ast.Assign)
                    and isinstance(n.targets[0], ast.Name) and n.targets[0].id == "rag_tri_type"]
        assert tri_type and all("rag_result" not in ast.unparse(n.value) for n in tri_type), \
            "the net-triangle note must follow the triangle that produced the figure"



class TestR209_TheAggregatedCohortIsInTheNumerator:
    """The grid parser skipped any header cell containing 'prior' or '&', so an aggregated older
    cohort ('2010 and prior') never became a column, and a label split across cells was misbound.
    Its development belongs to underwriting years up to t-2. Each case is the committed Azure table
    the stored triangle came from, and each expected figure is the filing's own, from the error-rate
    study's second reading."""

    @staticmethod
    def _grid(stem, index):
        cache = os.path.join(ROOT, "pdf_extraction", "azure_output", "%s_azure.json" % stem)
        assert os.path.exists(cache), "the committed cache for %s is missing; this test proves nothing without it" % stem
        return json.load(io.open(cache, encoding="utf-8"))["tables"][index]["grid"]

    def _parse(self, stem, index):
        year = int(stem.rsplit("_", 1)[1])
        tri, details = te._parse_nutrient_triangle(self._grid(stem, index), year)
        assert isinstance(tri, te.TriangleData), details
        pyd, why = tg.compute_pyd_from_triangle(tri.to_dict(), year)
        assert pyd is not None, why
        return tri, pyd

    CASES = [
        # stem, cached table, anchor, the filing's figure; the header layout in the comment
        ("syndicate_3624_2015", 17, 2010, 5.025),     # '2010 and prior' in one cell
        ("syndicate_4020_2016", 22, 2010, 25.303),    # '2010 and prior', printed last
        ("syndicate_218_2017", 3, 2010, -41.916),     # '2010' beside 'and prior'; figures under 'and prior'
        ("syndicate_218_2020", 3, 2010, -24.5),       # '2010 &' over 'prior'
        ("syndicate_4020_2017", 26, 2010, 21.188),    # '2010 &' over '2011', beside 'prior'
    ]

    @pytest.mark.parametrize("stem,index,anchor,figure", CASES)
    def test_the_cohort_column_enters_the_sum(self, stem, index, anchor, figure):
        tri, pyd = self._parse(stem, index)
        assert anchor in tri.underwriting_years, tri.underwriting_years
        assert pyd == pytest.approx(figure, abs=0.001), (pyd, tri.underwriting_years)
        agg = tri.to_dict().get("aggregated_cohort")
        assert agg and agg.get("anchor") == anchor, agg

    def test_before_2011_does_not_take_the_2011_column(self):
        """2121/2020: 'Before' over '2011' heads the older cohort's column, which prints no
        development; the real 2011 column holds 61.1 to 188.6. Its step is 0.0, so the figure
        stays +43.9, but 2011 must be read from its own column."""
        tri, pyd = self._parse("syndicate_2121_2020", 16)
        i = tri.underwriting_years.index(2011)
        assert tri.development_rows[0][i] == pytest.approx(61.1), [r[i] for r in tri.development_rows]
        assert 2010 not in tri.underwriting_years, tri.underwriting_years
        assert pyd == pytest.approx(43.9, abs=0.001)

    CONTROLS = [
        ("syndicate_435_2023", 13, -34.385),    # '2013 and prior' prints no development
        ("syndicate_1967_2022", 9, 45.457),     # no older cohort column
        ("syndicate_510_2024", 17, 217.598),    # the '2014 and prior' reserve is another table
    ]

    @pytest.mark.parametrize("stem,index,figure", CONTROLS)
    def test_a_table_without_cohort_development_does_not_move(self, stem, index, figure):
        tri, pyd = self._parse(stem, index)
        assert pyd == pytest.approx(figure, abs=0.001), (pyd, tri.underwriting_years)
        assert not tri.to_dict().get("aggregated_cohort"), tri.to_dict().get("aggregated_cohort")



class TestR209_ACohortPrintedByDevelopmentAgeIsNotACalendarColumn:
    """R209 takes an aggregated cohort's last step as its movement in the report year. That holds for a
    column that runs by calendar year, which holds at most report_year - anchor + 1 values. 4242 prints
    its older years by development age: '2015 & Prior' reaches 'Ten Years Later' in a 2021 report. R209
    inserted that column, the estimator refused the whole triangle, and the record fell to the uncached
    LLM-vision reader. The by-age column stays out, and the single years are read as they were before
    R209. Each case is the committed Azure table the stored triangle came from."""

    CASES = [
        # stem, cached table, the cohort's anchor, the single years' figure
        ("syndicate_4242_2021", 11, 2015, 9.493),
        ("syndicate_4242_2022", 13, 2016, -44.371),
        ("syndicate_4242_2023", 11, 2017, -7.19),
    ]

    @pytest.mark.parametrize("stem,index,anchor,figure", CASES)
    def test_the_by_age_column_stays_out_and_the_triangle_is_read(self, stem, index, anchor, figure):
        year = int(stem.rsplit("_", 1)[1])
        cache = os.path.join(ROOT, "pdf_extraction", "azure_output", "%s_azure.json" % stem)
        assert os.path.exists(cache), "the committed cache for %s is missing; this test proves nothing without it" % stem
        grid = json.load(io.open(cache, encoding="utf-8"))["tables"][index]["grid"]
        assert any("%d & Prior" % anchor in str(cell) for row in grid[:3] for cell in row), "not the table this case is about"
        tri, details = te._parse_nutrient_triangle(grid, year)
        assert isinstance(tri, te.TriangleData), details
        assert not tri.to_dict().get("aggregated_cohort"), tri.to_dict().get("aggregated_cohort")
        assert min(tri.underwriting_years) == anchor + 1, tri.underwriting_years
        pyd, why = tg.compute_pyd_from_triangle(tri.to_dict(), year)
        assert pyd == pytest.approx(figure, abs=0.001), why
