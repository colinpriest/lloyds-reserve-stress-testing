"""Round 62 (review of 29 September 2026, test upgrade 19): one named test for each branch of the
development-figure precedence (docs/ocr-pipeline.md section 10.3), at its boundaries.

  * the provisions sign override in the RAG step, and its three exceptions: a figure that is not an
    affirmed movement note, a column not bound to the report year (R138), and a zero figure;
  * the managed-level loss-ratio branch: fill a blank, keep an agreeing figure, override a
    contradicting one, and a flat figure that overrides nothing;
  * the veto: two agreeing model signs against the figure, and the 50% / 10% magnitude rule at its
    edges; fewer than two model values never veto;
  * the hand-confirmed-figures exception, to half a thousand, and its register's own rule;
  * nil against missing cells: a printed nil ([18, 0, 0]) is a zero movement, a missing cell
    ([18, None, None]) is no movement at all; and an all-dash mature column.

Each test names the branch it pins; each was mutation-checked against the code it names.

Run:  python -m pytest tests/test_precedence_branches.py -q
"""
import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import table_extraction as te  # noqa: E402
import test_gemini as tg  # noqa: E402

# ------------------------------------------------------------ the provisions sign override (RAG step)

#: a three-column gross triangle giving +3.0m (2018: 103 - 100) in a 2020 report
TRI = te.TriangleData(type="gross", currency="GBP", units="millions", units_evidence="header",
                      underwriting_years=[2018, 2019, 2020],
                      development_rows=[[90.0, 60.0, 30.0], [100.0, 70.0, None], [103.0, None, None]])
AFFIRMED = {"table_is_movement_note": True, "column_bound_to_report_year": True,
            "row_label": "Claims incurred in respect of prior years"}


@pytest.fixture
def rag(monkeypatch):
    def run(provisions=None, triangle=TRI, method="azure"):
        monkeypatch.setattr(tg, "extract_tables", lambda *a, **k: te.ExtractionResult(
            triangle=copy.deepcopy(triangle), provisions=copy.deepcopy(provisions), method=method,
            relevant_pages=[5]))
        monkeypatch.setattr(tg, "extract_text_from_pdf", lambda p: ([], "none"))
        return tg.extract_pyd_from_relevant_pages(Path("syndicate_9999_2020.pdf"), 2020)
    return run


def _prov(gross, **semantics):
    return te.ProvisionsData(gross_prior_year_claims=gross,
                             movement_semantics=dict(AFFIRMED, **semantics))


def test_sign_override_provisions_replace_a_triangle_of_the_other_sign(rag):
    r = rag(_prov(-5.0))
    assert r["pyd"] == -5.0 and r["method"] == "provisions" and r["pyd_from_triangle"] is False


def test_sign_override_needs_an_affirmed_movement_note(rag):
    r = rag(_prov(-5.0, table_is_movement_note=False))
    assert r["pyd"] == pytest.approx(3.0) and r["pyd_from_triangle"] is True


def test_sign_override_needs_the_report_year_column_R138(rag):
    r = rag(_prov(-5.0, column_bound_to_report_year=False))
    assert r["pyd"] == pytest.approx(3.0) and r["pyd_from_triangle"] is True


def test_sign_override_a_zero_provisions_figure_overrides_nothing(rag):
    r = rag(_prov(0.0))
    assert r["pyd"] == pytest.approx(3.0) and r["pyd_from_triangle"] is True


def test_sign_override_an_agreeing_sign_leaves_the_triangle(rag):
    r = rag(_prov(+9.0))
    assert r["pyd"] == pytest.approx(3.0) and r["method"] == "azure"


def test_sign_override_does_not_apply_to_a_page_vision_triangle(rag):
    """The check runs only for a triangle from a table backend (azure, nutrient, adobe)."""
    src = Path(tg.__file__).read_text(encoding="utf-8")
    assert 'result["method"] in ("azure", "nutrient", "adobe")' in src


# ------------------------------------------------------------ the loss-ratio branch

def test_loss_ratio_fills_a_blank_model_value():
    r = {"prior_year_development_gbp_m": None, "opening_reserves_gbp_m": 200.0}
    assert tg._apply_loss_ratio_fallback(r, -4.0, "g") == "filled_blank"
    assert r["prior_year_development_gbp_m"] == -4.0 and "MANAGED LEVEL" in r["data_quality_notes"]


def test_loss_ratio_keeps_an_agreeing_syndicate_figure():
    r = {"prior_year_development_gbp_m": -1.5}
    assert tg._apply_loss_ratio_fallback(r, -4.0, "g") == "kept_agreement"
    assert r["prior_year_development_gbp_m"] == -1.5


def test_loss_ratio_overrides_a_contradicting_direction():
    r = {"prior_year_development_gbp_m": 2.0, "opening_reserves_gbp_m": 100.0}
    assert tg._apply_loss_ratio_fallback(r, -4.0, "g") == "overrode_contradiction"
    assert r["prior_year_development_gbp_m"] == -4.0 and r["direction"] == "release"


def test_loss_ratio_a_flat_figure_overrides_nothing():
    r = {"prior_year_development_gbp_m": 2.0}
    assert tg._apply_loss_ratio_fallback(r, 0.0, "g") == "kept_agreement"
    assert r["prior_year_development_gbp_m"] == 2.0


# ------------------------------------------------------------ the veto

def test_veto_two_agreeing_model_signs_against_the_figure():
    ok, why = tg._pyd_override_gate(+5.0, [-1.0, -2.0], 100.0)
    assert not ok and "opposite sign" in why


def test_veto_models_that_disagree_with_each_other_do_not_veto():
    assert tg._pyd_override_gate(+5.0, [-1.0, +2.0], 100.0) == (True, None)


def test_veto_a_zero_model_value_is_no_sign():
    assert tg._pyd_override_gate(+5.0, [0.0, -2.0], 100.0) == (True, None)


def test_veto_fewer_than_two_model_values_never_veto():
    assert tg._pyd_override_gate(+500.0, [None, -2.0], 100.0) == (True, None)


@pytest.mark.parametrize("figure,models,vetoed", [
    (50.0, [5.0, 5.0], False),       # exactly half the opening is not above it
    (50.01, [5.0, 5.0], True),       # just above half, both models under ten percent
    (50.01, [10.0, 5.0], False),     # a model at exactly ten percent is not under it
    (50.01, [9.99, 9.99], True),
    (-60.0, [-5.0, -5.0], True),     # magnitude, either sign
])
def test_veto_the_fifty_and_ten_percent_boundaries(figure, models, vetoed):
    ok, why = tg._pyd_override_gate(figure, models, 100.0)
    assert ok is (not vetoed), (figure, models, why)
    if vetoed:
        assert "% of opening reserves" in why


# ------------------------------------------------------------ the hand-confirmed exception

@pytest.mark.parametrize("figure,confirmed,lifted", [
    (-6.619, -6.619, True),
    (-6.619, -6.6194, True),         # within half a thousand
    (0.0, 0.0004, True),
    (0.0, 0.0005, False),            # exactly half a thousand is not within it
    (-6.619, -6.6195, False),
    (-6.619, None, False),
])
def test_hand_confirmation_is_to_half_a_thousand(figure, confirmed, lifted):
    assert tg._lifted_by_hand_confirmation(figure, confirmed) is lifted


def test_hand_confirmed_figure_is_applied_over_the_sign_veto():
    ok, why = tg._rag_veto(+5.0, [-1.0, -2.0], 100.0, 5.0)
    assert ok and "APPLIED OVER THE SIGN VETO" in why
    ok, why = tg._rag_veto(+5.0, [-1.0, -2.0], 100.0, 4.0)       # another figure: the veto stands
    assert not ok


def test_hand_confirmed_register_needs_two_readings_pages_and_a_quote(tmp_path):
    reg = tmp_path / "confirmed.json"
    reg.write_text(json.dumps({"records": [{"stem": "syndicate_9999_2020", "figure_m": 1.0,
                                            "readings": ["one"], "pages": [3], "quote": "x"}]}),
                   encoding="utf-8")
    with pytest.raises(ValueError, match="two readings"):
        tg._hand_confirmed_figure(9999, 2020, path=reg)
    assert tg._hand_confirmed_figure(9999, 2021, path=reg) is None


def test_the_committed_register_lifts_its_three_records():
    for syn, yr in ((3624, 2015), (1225, 2022), (2010, 2019)):
        assert isinstance(tg._hand_confirmed_figure(syn, yr), float)


# ------------------------------------------------------------ nil against missing cells

def _tri(rows, years=(2020, 2021, 2022), units="thousands"):
    return {"type": "gross", "units": units, "units_evidence": "header",
            "underwriting_years": list(years), "development_rows": [list(r) for r in rows]}


def test_printed_nil_cells_are_a_zero_movement():
    """1840/2022's mature cohort as printed: 18, then nil, then nil (GBP000)."""
    pyd, details = tg.compute_pyd_from_triangle(_tri([[18, 2364, 190], [0, 3407, None], [0, None, None]]), 2022)
    assert pyd == 0.0, details


def test_missing_cells_are_no_movement_at_all():
    """The same cohort with its later cells missing ([18, None, None]): nothing to difference, so no
    figure -- and the reason names no usable year, which the table step reads as a young syndicate."""
    pyd, details = tg.compute_pyd_from_triangle(_tri([[18, 2364, 190], [None, 3407, None], [None, None, None]]), 2022)
    assert pyd is None and "no usable UW years" in details


def test_an_all_dash_mature_column_counts_as_no_claims_activity():
    """A mature column with no value at all is read as nil development and counted; the figure is
    the other mature column's movement."""
    rows = [[None, 100.0, 60.0, 30.0], [None, 110.0, 70.0, None], [None, 115.0, None, None],
            [None, None, None, None]]
    pyd, details = tg.compute_pyd_from_triangle(_tri(rows, years=(2017, 2018, 2019, 2020), units="millions"), 2020)
    assert pyd == pytest.approx(5.0), details
    assert "2017: all-zero column (no claims activity), PYD=0" in details
