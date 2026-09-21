"""Round 58 (review finding M01): a first-year report is not adopted as development.

1884/2016's syndicate began underwriting in April 2015; every triangle the report holds, the
RAG step's and both models', covers 2015 and 2016 only, so no cohort u <= t-2 exists and the
filing discloses no prior-year movement. The record reached the working sample as +15.044m:
gpt-5-mini's closing-minus-opening arithmetic (21,372 - 6,328), gemini null. Two branches of
the RAG step cleared the first-year flag and nothing set it again, verify_triangles threw away
only its own computation, and the model reading carried no route to say what it was.

The repair decides after the models: when no triangle has a mature cohort, no deterministic
route produced a figure and no model figure is printed in the reserve text, the record is the
first-year stub. Young syndicates whose filings do disclose a prior-year movement keep it:
6130/2017 ("released $267k of technical reserves in respect of prior periods", read by both
models), 6125/2017 and 1996/2024 (the provisions note, a deterministic route).

The replays run process_one_report offline from the committed caches and need the source
filings, which are not committed; without them they skip. Nothing is written to the repository:
the slim PDFs go to a temporary directory and the inception-year cache is not saved.

Run:  python -m pytest tests/test_first_year_after_models.py -q
"""
import io
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import table_extraction as te  # noqa: E402
import test_gemini as tg  # noqa: E402

RESERVE_TEXT = ("Claims outstanding\nAt 1 January 2016 (6,328)\nClaims incurred in current underwriting "
                "year (50,467)\nClaims paid during the year 16,500\nAt 31 December 2016 (44,009)\n")


# ------------------------------------------------------------ the RAG step's flag

@pytest.fixture
def rag_step(monkeypatch):
    """extract_pyd_from_relevant_pages with every input mocked: a table triangle with no
    usable year (2015-2016 in a 2016 report), one page of reserve text, and narrative
    parsers that find what they are told to."""
    def run(parser_figure=None):
        tri = te.TriangleData(type="gross", currency="GBP", units="thousands",
                              underwriting_years=[2015, 2016],
                              development_rows=[[8331.0, 28437.0], [33578.0, None]])
        monkeypatch.setattr(tg, "extract_tables",
                            lambda *a, **k: te.ExtractionResult(triangle=tri, method="azure", relevant_pages=[3]))
        monkeypatch.setattr(tg, "extract_text_from_pdf", lambda p: ([(1, "cover"), (2, RESERVE_TEXT)], "pymupdf"))
        monkeypatch.setattr(tg, "find_relevant_pages",
                            lambda pages, year: {"triangle_pages": [], "reserve_pages": [(2, RESERVE_TEXT)]})
        monkeypatch.setattr(tg, "_extract_pyd_from_reserves_movement", lambda pages, year: None)
        monkeypatch.setattr(tg, "_extract_pyd_from_provisions_text", lambda text: (None, None))
        monkeypatch.setattr(tg, "_parse_pyd_from_pl_narrative", lambda text: (None, None))
        monkeypatch.setattr(tg, "_parse_pyd_from_yoa_narrative", lambda text: (None, None))
        monkeypatch.setattr(tg, "_parse_pyd_from_general_narrative",
                            lambda text: (parser_figure, "narrative") if parser_figure is not None else (None, None))
        return tg.extract_pyd_from_relevant_pages(Path("syndicate_1884_2016.pdf"), 2016)
    return run


def test_the_first_year_flag_is_set_again_when_the_parsers_find_nothing(rag_step):
    r = rag_step()
    assert r["pyd"] is None
    assert r["first_year_syndicate"] is True
    assert r["first_year_reserve_text"] is True     # the models still read the text
    assert r["no_triangle_data"] is False
    # control: a parser that finds a figure leaves the flag cleared and the figure in place
    r = rag_step(parser_figure=-0.267)
    assert r["first_year_syndicate"] is False and r["pyd"] == -0.267


# ------------------------------------------------------------ the decision's parts

def test_a_figure_is_stated_only_when_the_text_prints_it():
    assert tg._figure_in_text(-0.267, "During 2017 the Syndicate released $267k of technical reserves")
    assert tg._figure_in_text(3.1, "Change in prior year provisions 3,138")
    assert tg._figure_in_text(1.2, "an overall surplus of GBP 1.2m on prior year reserves")
    assert tg._figure_in_text(0.0, "Movement in prior years: nil")
    # 1884/2016: the block's text names only the 2015 year of account
    assert not tg._figure_in_text(15.044, "with the 2015 year of account suffering deterioration")
    assert not tg._figure_in_text(2.015, "the 2015 year of account")          # a year is not an amount
    assert not tg._figure_in_text(3.0, "a release of GBP 2.6m")
    assert not tg._figure_in_text(1.0, "")


def test_no_mature_cohort_needs_a_young_triangle_and_no_mature_one():
    young = {"type": "gross", "underwriting_years": [2015, 2016]}
    mature = {"type": "gross", "underwriting_years": [2012, 2013, 2014, 2015, 2016]}
    rag = {"triangle": dict(young)}
    ok, tris = tg._no_mature_cohort(rag, [("g", {"_claims_triangle": dict(young)}),
                                          ("o", {"_claims_triangle": dict(young)})], 2016)
    assert ok and tris == {"rag": [2015, 2016], "g": [2015, 2016], "o": [2015, 2016]}
    assert not tg._no_mature_cohort(rag, [("g", {"_claims_triangle": dict(mature)})], 2016)[0]
    # no triangle at all is no evidence of youth (2010/2014, 5678/2014)
    assert not tg._no_mature_cohort({"triangle": None}, [("g", {"_claims_triangle": {"type": "none"}})], 2014)[0]


def test_a_code_triangle_figure_records_its_route():
    """A FILL used to leave neither a route nor a note, so it read as the model's own figure."""
    r, _msg = tg._apply_triangle_pyd({"prior_year_development_gbp_m": None, "opening_reserves_gbp_m": 100.0},
                                     -5.0, "gpt-5-mini", "details", "FILL from GPT triangle")
    assert r["_pyd_route"]["source"] == "code_triangle" and r["_pyd_route"]["value"] == -5.0
    assert "model_value" not in r["_pyd_route"]
    r, _msg = tg._apply_triangle_pyd({"prior_year_development_gbp_m": 2.0, "opening_reserves_gbp_m": 100.0},
                                     -5.0, "gpt-5-mini", "details", "OVERRIDE from GPT triangle",
                                     triangle={"type": "gross", "units": "millions"})
    assert r["_pyd_route"]["model_value"] == 2.0 and r["_pyd_route"]["triangle_type"] == "gross"


# ------------------------------------------------------------ offline replays

def _filing(stem):
    for ext in (".pdf", ".html", ".htm"):
        p = ROOT / "syndicate_reports" / "pdfs" / (stem + ext)
        if p.exists():
            return p
    return None


def _committed_inception():
    d = json.load(io.open(ROOT / "pdf_extraction" / "syndicate_inception_years.json", encoding="utf-8"))
    return {int(k): int(v) for k, v in d.items() if not k.startswith("_")}


@pytest.fixture
def replay(monkeypatch, tmp_path):
    monkeypatch.setenv("LLOYDS_EXTRACTION_OFFLINE", "1")
    monkeypatch.delenv("LLOYDS_ALLOW_TABLE_BACKEND_CALLS", raising=False)
    monkeypatch.chdir(ROOT)                          # the driver's cache paths are repository-relative
    monkeypatch.setattr(tg, "OUTPUT_DIR", tmp_path)  # the slim PDFs are written here
    saved = []
    monkeypatch.setattr(tg, "_save_inception_years", lambda inc: saved.append(dict(inc)))

    def run(stem, inception=None):
        pdf = _filing(stem)
        if pdf is None or not (ROOT / "pdf_extraction" / "azure_output" / f"{stem}_azure.json").exists():
            pytest.skip("the source filing or its table cache is not in this checkout")
        inc = _committed_inception() if inception is None else dict(inception)
        return tg.process_one_report(pdf, inc), saved
    return run


def test_1884_2016_is_written_as_the_first_year_stub(replay):
    res, _saved = replay("syndicate_1884_2016")
    assert isinstance(res, tuple) and res[0] == "first_year", "the report was adopted with models"
    stub = res[1]
    assert stub["first_year_syndicate"] is True and "models" not in stub
    ev = stub["first_year_evidence"]
    years = [y for ys in ev["triangle_underwriting_years"].values() for y in ys]
    assert years and all(y > 2016 - 2 for y in years)
    assert ev["model_figures_not_stated"]["gpt-5-mini"] == pytest.approx(15.044)
    assert ev["model_figures_not_stated"]["gemini-2.5-flash"] is None


@pytest.mark.parametrize("stem,figure,source", [
    ("syndicate_6130_2017", -0.267, "model_reading"),
    ("syndicate_6125_2017", 3.1, "rag_provisions"),
    ("syndicate_1996_2024", -0.1, "rag_provisions"),
])
def test_a_young_syndicate_keeps_its_disclosed_movement(replay, stem, figure, source):
    res, _saved = replay(stem)
    assert isinstance(res, tuple) and len(res) == 4, "written as %s" % (res[0] if isinstance(res, tuple) else res)
    output = res[0]
    for name, block in output["models"].items():
        assert block["prior_year_development_gbp_m"] == pytest.approx(figure), name
        route = block.get("_pyd_route") or {}
        assert route.get("source") == source, (name, route)
        if source == "model_reading":
            assert route.get("stated") is True, (name, route)


def test_the_inception_year_is_learned_only_where_it_is_missing(replay):
    """No lookup for a syndicate the cache lacks (the deleted check called Perplexity, an
    error offline), a triangle's first year fills a missing entry, and a known year is never
    lowered: a later triangle can carry cohorts reinsured to close into the syndicate."""
    res, saved = replay("syndicate_1856_2018", inception={})
    assert isinstance(res, tuple)
    assert saved and saved[-1].get(1856) == 2016
    saved.clear()
    res, saved = replay("syndicate_1856_2018", inception={1856: 2017})
    assert not any(s.get(1856) != 2017 for s in saved), saved
