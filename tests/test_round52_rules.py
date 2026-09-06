"""Round 52, second set: the rules added after the first offline re-extraction exposed
that a correctly bound deterministic figure can still be the wrong column or scale.

  * the provisions-movement parser reads the CURRENT-year gross column (1221/2023: the
    current-year change is 78,241; the comparative block, which the parser took before,
    is 194,595);
  * movement rows may be negative (a release), opening balances may not;
  * a table-derived opening reserve is applied by the two-of-three rule (agrees with a
    model at some scale, or the models disagree with each other), never against two
    agreeing models (382/2018's wrong-year column; 2988/2024's x1000 under a mistaken
    document declaration);
  * a deterministic development figure is not applied against two agreeing model signs,
    nor when it implies a movement above half the reserves while both models read under
    ten percent.
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import table_extraction as te  # noqa: E402
from test_gemini import _resolve_rag_opening, _pyd_override_gate  # noqa: E402

CACHE = ROOT / "pdf_extraction" / "azure_output"


def _grid_with(stem, needle):
    for t in json.load(open(CACHE / f"{stem}_azure.json"))["tables"]:
        if needle in te._grid_text_lower(t["grid"]):
            return t["grid"]
    raise AssertionError("no cached table with %r for %s" % (needle, stem))


def test_provisions_parser_reads_the_current_year_gross_column():
    grid = _grid_with("syndicate_1221_2023", "change in prior underwriting")
    prov = te._parse_nutrient_provisions(grid, 2023, page_text="", doc_unit=None)
    assert prov is not None and abs(prov.gross_prior_year_claims - 78.2) < 0.15, prov.gross_prior_year_claims


def test_provisions_parser_takes_the_first_block_when_only_the_comparative_is_unlabelled():
    grid = _grid_with("syndicate_2010_2023", "change in prior year provi")
    prov = te._parse_nutrient_provisions(grid, 2023, page_text="", doc_unit=None)
    assert prov is not None and abs(prov.gross_prior_year_claims - 16.0) < 0.15, prov.gross_prior_year_claims


def test_movement_rows_may_be_negative_but_opening_balances_may_not():
    rel = te.resolve_units(-30753.0, 0.001, table_kind="provisions_movement_row")
    assert rel is not None and rel.value_m == -30.753
    assert te.resolve_units(-441400.0, 0.001, table_kind="balance_sheet_liabilities") is None
    assert te.resolve_units(-441.4, None, "", None, table_kind="provisions_movement") is None
    assert te.resolve_units(46378.0, 0.001, table_kind="provisions_movement").value_m == 46.378


class TestTwoOfThreeOpeningRule:
    def test_agreeing_model_at_scale_one_is_applied(self):
        assert _resolve_rag_opening(12.121, {"unit_source": "header", "raw_value": 12121.0}, [12.121, 78.049])[0] == 12.121

    def test_x1000_agreement_rescales_even_with_a_document_declaration(self):
        """2988/2024: the table gave 347,898 under a mistaken document unit; both models read 347.898."""
        v, label, note = _resolve_rag_opening(347898.0, {"unit_source": "document", "raw_value": 347898.0}, [347.898, 347.898])
        assert v == 347.898 and label == "model-agreement:thousands"

    def test_wrong_column_against_two_agreeing_models_is_not_applied(self):
        """382/2018: the parser read the prior-year column (343.077); both models read 425.362."""
        v, label, note = _resolve_rag_opening(343.077, {"unit_source": "header", "raw_value": 343077.0, "page": 30}, [425.362, 425.362])
        assert v is None and "NOT APPLIED" in note and "disagrees with both model values" in note

    def test_models_that_disagree_let_the_table_break_the_tie(self):
        """2357/2016: Gemini 7.806 and GPT 23.463 (both wrong), table 0.017 (right)."""
        v, label, note = _resolve_rag_opening(0.017, {"unit_source": "header", "raw_value": 17.0}, [7.806, 23.463])
        assert v == 0.017 and label.endswith("tie-break")

    def test_unresolved_unit_with_no_agreement_is_not_applied(self):
        v, label, note = _resolve_rag_opening(46378.0, {"unit_source": "unresolved", "raw_value": 46378.0}, [1548.7, 1500.0])
        assert v is None


class TestBusinessMix:
    """Third-batch review: 2623/2015's segmental table is transposed (classes across the
    header); the row-wise parser had read its profit-and-loss rows as classes, the
    round-52 parser rejected it and a text fallback returned one class at 4.0m."""

    def test_transposed_segmental_table_is_read_from_its_premiums_row(self):
        grids = [t["grid"] for t in json.load(open(CACHE / "syndicate_2623_2015_azure.json"))["tables"]
                 if "gross premiums written" in te._grid_text_lower(t["grid"])
                 and "specialty lines" in te._grid_text_lower(t["grid"]) and str(t["grid"][0][0]).strip() == "2015"]
        assert grids, "the cached 2623/2015 segmental table is expected in the committed cache"
        lob = te._parse_nutrient_lob(grids[0], 2015, page_text="segmental analysis")
        assert lob is not None and lob.method == "nutrient_transposed"
        names = [e["line_of_business"] for e in lob.gross_premium_mix]
        assert names == ["Marine", "Political risks & contingency", "Property", "Reinsurance", "Specialty lines"], names
        assert abs(lob.gross_premiums_written_gbp_m - 1730.2) < 0.05
        assert all(not te._is_pl_label(n) for n in names)

    def test_comparative_transposed_table_is_rejected(self):
        """The 2623/2015 filing prints the 2014 table beside the 2015 one; batch 4 took it."""
        grids = [t["grid"] for t in json.load(open(CACHE / "syndicate_2623_2015_azure.json"))["tables"]
                 if "gross premiums written" in te._grid_text_lower(t["grid"])
                 and "specialty lines" in te._grid_text_lower(t["grid"]) and str(t["grid"][0][0]).strip() == "2014"]
        assert grids
        assert te._parse_nutrient_lob(grids[0], 2015, page_text="segmental analysis") is None
        lob = te._parse_nutrient_lob(grids[0], 2014, page_text="segmental analysis")
        assert lob is not None and abs(lob.gross_premiums_written_gbp_m - 1702.7) < 0.05

    def test_profit_and_loss_rows_are_not_a_mix(self):
        grid = [["", "2018", "2017"], ["Gross premiums written", "268.8", "324.7"],
                ["Net premiums written", "239.0", "289.5"], ["Gross earned premiums", "288.3", "316.6"],
                ["Marine", "12.0", "11.0"]]
        assert te._parse_nutrient_lob(grid, 2018, page_text="segmental analysis") is None

    def test_ordinary_profit_and_loss_table_is_not_transposed(self):
        grid = [["", "Notes", "2015 £000", "Restated 2014 £000"],
                ["Gross premiums written", "3", "1,234", "1,100"], ["Outward reinsurance premiums", "", "(200)", "(180)"]]
        assert te._parse_transposed_lob(grid, 2015, te._grid_text_lower(grid)) is None

    def test_pecuniary_loss_and_legal_expenses_are_classes(self):
        assert not te._is_pl_label("Pecuniary loss") and not te._is_pl_label("Legal expenses")
        assert te._is_pl_label("Net premiums written") and te._is_pl_label("Balance on the technical account")

    def test_driver_gate_on_the_deterministic_mix(self):
        from test_gemini import _lob_override_gate
        two = {"gross_premium_mix": [{"line_of_business": "Marine"}, {"line_of_business": "Property"}], "gross_premiums_written_gbp_m": 100.0}
        assert _lob_override_gate(two, [None, None]) == (True, None)
        one_bad = {"gross_premium_mix": [{"line_of_business": "Third party liability"}], "gross_premiums_written_gbp_m": 4.0}
        ok, why = _lob_override_gate(one_bad, [1499.6, 1520.0])
        assert not ok and "LOB NOT APPLIED" in why
        one_spa = {"gross_premium_mix": [{"line_of_business": "Property"}], "gross_premiums_written_gbp_m": 30.4}
        assert _lob_override_gate(one_spa, [29.9, 31.0])[0]


class TestDevelopmentOverrideGate:
    def test_opposite_sign_to_two_agreeing_models_is_blocked(self):
        ok, note = _pyd_override_gate(-34.9, [78.2, 70.0], 910.0)
        assert not ok and "opposite sign" in note

    def test_gross_magnitude_against_two_small_model_values_is_blocked(self):
        """2121/2019: a mis-columned triangle gave +231.1 on GBP 411m; both models read +3.7."""
        ok, note = _pyd_override_gate(231.1, [3.7, 3.7], 411.0)
        assert not ok and "of opening reserves" in note

    def test_models_that_disagree_in_sign_do_not_block(self):
        assert _pyd_override_gate(17.3, [-7.2, 12.0], 1548.7) == (True, None)

    def test_a_single_model_value_does_not_block(self):
        assert _pyd_override_gate(-25.8, [None, -25.782], 3400.0) == (True, None)


class TestCodeTriangleOverrideGate:
    """The third deterministic path: verify_triangles recomputes development from the
    models' own triangles.  1084/2022 reached the record as +581.7 against both models
    at -85.9 by this path after the RAG triangle had been blocked; the same gate applies."""

    TRI = {"type": "gross", "underwriting_years": [2019, 2020], "development_rows": [[1.0, 2.0], [3.0, None]]}

    def _results(self, pyd_g, pyd_o, tri_o=True):
        g = {"_claims_triangle": dict(self.TRI), "prior_year_development_gbp_m": pyd_g,
             "opening_reserves_gbp_m": 2896.5, "data_quality_notes": "g"}
        o = {"_claims_triangle": dict(self.TRI) if tri_o else {"type": "none"},
             "prior_year_development_gbp_m": pyd_o, "opening_reserves_gbp_m": 2896.5, "data_quality_notes": "o"}
        return g, o

    @pytest.fixture(autouse=True)
    def _fixed_triangle(self, monkeypatch):
        import test_gemini
        monkeypatch.setattr(test_gemini, "compute_pyd_from_triangle", lambda tri, year: (581.7, "fixed"))
        monkeypatch.setattr(test_gemini, "_validate_triangle_structure", lambda uw, rows, year: 0.9)

    def test_agreed_triangles_are_not_applied_against_two_agreeing_opposite_signs(self):
        from test_gemini import verify_triangles
        g, o = self._results(-85.9, -85.9)
        g2, o2, msgs = verify_triangles(g, o, "gemini", "gpt", 2022)
        assert g2["prior_year_development_gbp_m"] == -85.9 and o2["prior_year_development_gbp_m"] == -85.9
        assert "CODE PYD NOT APPLIED" in g2["data_quality_notes"] and "CODE PYD NOT APPLIED" in o2["data_quality_notes"]

    def test_models_that_disagree_in_sign_are_overridden_as_before(self):
        from test_gemini import verify_triangles
        g, o = self._results(-85.9, 12.0)
        g2, o2, msgs = verify_triangles(g, o, "gemini", "gpt", 2022)
        assert g2["prior_year_development_gbp_m"] == 581.7 and o2["prior_year_development_gbp_m"] == 581.7

    def test_single_triangle_is_gated_too(self):
        from test_gemini import verify_triangles
        g, o = self._results(-7.2, -7.2, tri_o=False)
        g2, o2, msgs = verify_triangles(g, o, "gemini", "gpt", 2018)
        assert g2["prior_year_development_gbp_m"] == -7.2 and "CODE PYD NOT APPLIED" in o2["data_quality_notes"]

    def test_a_missing_model_value_is_filled(self):
        from test_gemini import verify_triangles
        g, o = self._results(None, -85.9)
        g2, o2, msgs = verify_triangles(g, o, "gemini", "gpt", 2022)
        assert g2["prior_year_development_gbp_m"] == 581.7
