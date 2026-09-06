"""Round 52 (review findings M01/M02): entity binding, section kind, cached-page
remapping and unit resolution in table_extraction.py, and the driver's rule for when a
table-derived opening reserve may override the model values.

The fixtures are trimmed page texts of four real filings (tests/fixtures/round52_page_texts.json):
  * syndicate_510_2018   Tokio Marine Kiln combined filing (510, 557, 308) with
                         underwriting-year accounts appended;
  * syndicate_6104_2016  Hiscox combined filing (33 first, then 6104);
  * syndicate_6104_2024  the HTML-converted Hiscox filing with a chapter index on
                         every page;
  * syndicate_1416_2024  a single-syndicate HTML filing whose balance-sheet table
                         lost its thousands marker.
The cached Azure grids (pdf_extraction/azure_output) are committed and used directly.
The five reserve records the frozen review verified against the filed accounts are
the planted examples: 1416/2024 US$46.378m, 510/2018 and 510/2019 must not take
syndicate 557's reserves, 6104/2016 £13.540m and 6104/2024 US$53.081m must not take
syndicate 33's.
"""
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import table_extraction as te  # noqa: E402

FIX = json.load(open(ROOT / "tests" / "fixtures" / "round52_page_texts.json", encoding="utf-8"))
CACHE = ROOT / "pdf_extraction" / "azure_output"
PDFS = ROOT / "syndicate_reports" / "pdfs"
HTMLPDF = ROOT / "pdf_extraction" / "html_converted"


def texts(stem):
    return {int(k): v for k, v in FIX[stem]["pages"].items()}


def cached_tables(stem):
    return json.load(open(CACHE / f"{stem}_azure.json"))["tables"]


# ---------------------------------------------------------------- mentions & markers

def test_syndicate_lists_name_every_member_and_never_form_a_marker():
    text = ("Hiscox Syndicates 0033 and 6104 Report and Accounts 2024\n"
            "For Syndicates 510, 557 and 308 managed by Tokio Marine Kiln\n")
    counts = te._mention_counts(text)
    assert counts == {33: 1, 6104: 1, 510: 1, 557: 1, 308: 1}
    assert te._section_markers(text) == []


def test_two_digit_syndicate_numbers_and_year_of_account_phrases():
    assert te._mention_counts("Hiscox Syndicate 33 annual accounts") == {33: 1}
    # "syndicate 2022 underwriting account" is a year of account, not syndicate 2022
    assert te._mention_counts("audit of the syndicate 2022 underwriting account") == {}
    assert te._mention_counts("Syndicate 12 months") == {}


def test_section_markers_head_their_line():
    assert te._section_markers("Syndicate 510   Annual accounts under UK GAAP") == [(510, "annual")]
    assert te._section_markers("Syndicate 510   Underwriting year accounts") == [(510, "underwriting_year")]
    assert te._section_markers("Balance sheet - liabilities Hiscox Syndicate 6104 annual accounts") == [(6104, "annual")]
    # a cross-reference inside a sentence is not a section marker
    sentence = ("The quota share arrangement is described in note 12 of the accounts, and further "
                "detail on the reinsurance programme is set out in the Hiscox Syndicate 0033 annual accounts of the year")
    assert te._section_markers(sentence) == []


# ---------------------------------------------------------------- sections

def test_combined_filing_sections_follow_the_syndicate_headings():
    secs = te.page_sections(texts("syndicate_510_2018"), 510)
    # 1-based pages 40-50 are syndicate 510's annual accounts, 66-74 syndicate 557's
    assert all(secs[p - 1][0] == 510 for p in (40, 42, 44, 50))
    assert all(secs[p - 1][0] == 557 for p in (66, 68, 74))
    # the balance-sheet page without a running header inherits its section
    assert secs[41 - 1][0] == 510 and secs[67 - 1][0] == 557
    # the closed-year (underwriting year) accounts are a different section kind
    assert secs[124 - 1] == (510, "underwriting_year")
    assert secs[44 - 1][1] == "annual"


def test_hiscox_2016_sections_and_six104_pages():
    secs = te.page_sections(texts("syndicate_6104_2016"), 6104)
    assert all(secs[p - 1][0] == 33 for p in (14, 15, 16))
    assert all(secs[p - 1][0] == 6104 for p in (56, 57, 58))


def test_html_filing_is_sectioned_by_its_chapter_index():
    tx = texts("syndicate_6104_2024")
    chapters = te.chapter_index(tx)
    assert chapters == [(2, 33, "annual"), (43, 33, "underwriting_year"),
                        (59, 6104, "annual"), (82, 6104, "underwriting_year")]
    secs = te.page_sections(tx, 6104)
    assert secs[33 - 1] == (33, "annual")          # syndicate 33's balance sheet
    assert secs[145 - 1] == (6104, "annual")       # syndicate 6104's balance sheet
    assert secs[165 - 1] == (6104, "annual")       # 6104's claims development note
    assert secs[189 - 1] == (6104, "underwriting_year")


def test_single_syndicate_filing_has_no_companions_and_no_closed_year_pages():
    secs = te.page_sections(texts("syndicate_1416_2024"), 1416)
    assert {e for e, _ in secs.values()} <= {None, 1416}
    # an accounting policy that mentions closed years of account is not a closed-year page
    assert secs[31 - 1][1] == "annual" and secs[33 - 1][1] == "annual"


# ---------------------------------------------------------------- cached-page remap

def test_remap_undoes_the_priority_order_mapping():
    # ascending pages 3, 11, 12 were sent in that order; the priority order was 11, 3, 12
    batches = [[11, 3, 12]]
    assert te.remap_cached_page(11, batches) == 3
    assert te.remap_cached_page(3, batches) == 11
    assert te.remap_cached_page(12, batches) == 12
    assert te.remap_cached_page(99, batches) == 99


def test_locate_table_page_by_its_numbers():
    tx = texts("syndicate_510_2018")
    grid = [["Division", "Gross premium written"], ["Property & Special Lines", "764,233"],
            ["Marine & Special Risks", "204,078"], ["Accident & Health", "126,975"]]
    located = te.locate_table_page(grid, tx, list(tx))
    assert located == 44 - 1                    # the segmental analysis is on page 44
    assert te.locate_table_page([["a", "1"]], tx, list(tx)) is None


# ---------------------------------------------------------------- units

def test_unit_resolution_order_and_unresolved_value():
    assert te.resolve_units(46378.0, 0.001).unit_source == "header"
    assert te.resolve_units(46378.0, None, "Balance sheet US$'000").to_dict()["value_m"] == 46.378
    assert te.resolve_units(46378.0, None, "", 0.001).unit_source == "document"
    big = te.resolve_units(1548723.0, None, "", None)
    assert big.unit_source == "magnitude" and big.value_m == 1548.723
    small = te.resolve_units(46378.0, None, "$", None)
    assert small.unit_source == "unresolved" and small.unit_multiplier is None and small.value_m == 46378.0


def test_1416_2024_cached_table_needs_the_document_declaration():
    """The cached provisions table carries only '$'; the filing's accounting policy says
    amounts are rounded to the nearest thousand.  Without that declaration the value is
    unresolved (and the driver will not let it override the model); with it, 46.378."""
    grids = [t["grid"] for t in cached_tables("syndicate_1416_2024")
             if "balance at 1 january" in te._grid_text_lower(t["grid"])
             and "46,378" in " ".join(" ".join(r) for r in t["grid"])]
    assert grids, "the cached 1416/2024 provisions table is expected in the committed cache"
    oc = te._parse_opening_claims_outstanding(grids[0], 2024, page_text="$", doc_unit=None)
    assert oc.unit_source == "unresolved" and oc.value_m == 46378.0
    doc_unit = te.document_unit_hint(texts("syndicate_1416_2024"))
    assert doc_unit == 0.001
    oc = te._parse_opening_claims_outstanding(grids[0], 2024, page_text="$", doc_unit=doc_unit)
    assert oc.unit_source == "document" and oc.value_m == 46.378


def test_mix_table_needs_a_premium_column():
    grid = [["", "Property", "Marine", "Aviation", "Syndicate 510"], ["", "£m", "£m", "£m", "£m"],
            ["Underwriting profit/(loss)", "(13.7)", "2.1", "7.1", "46.7"],
            ["Allocated capacity", "546.7", "184.0", "45.4", "1,061.8"]]
    assert te._parse_nutrient_lob(grid, 2018, page_text="segmental analysis class of business") is None


# ---------------------------------------------------------------- driver rule

def test_driver_applies_a_table_value_only_with_unit_evidence_or_model_agreement():
    from test_gemini import _resolve_rag_opening
    unresolved = {"unit_source": "unresolved", "raw_value": 46378.0, "page": 33, "table_kind": "provisions_movement"}
    assert _resolve_rag_opening(46378.0, unresolved, [46.378, 46.378]) == (46.378, "model-agreement:thousands", None)
    # an unresolved value that agrees with a model at scale 1 is applied as it stands
    assert _resolve_rag_opening(46.378, {"unit_source": "unresolved", "raw_value": 46.378}, [46.378, 46.4])[0] == 46.378
    value, label, note = _resolve_rag_opening(46378.0, unresolved, [1548.723, 1548.723])
    assert value is None and "NOT APPLIED" in note
    # a resolved table value that contradicts two agreeing models is not applied (two-of-three rule):
    # 557's balance sheet figure must not override syndicate 510's agreed 1,548.723
    assert _resolve_rag_opening(36.321, {"unit_source": "header", "raw_value": 36321.0}, [1548.723, 1548.723])[0] is None
    assert _resolve_rag_opening(12.5, None, [12.5])[0] == 12.5


# ---------------------------------------------------------------- integration (PDFs present)

def _filing(stem):
    pdf = PDFS / f"{stem}.pdf"
    if pdf.exists():
        return pdf
    conv = HTMLPDF / f"{stem}.pdf"
    return conv if conv.exists() else None


@pytest.mark.parametrize("stem,year,expect", [
    ("syndicate_1416_2024", 2024, {"opening": 46.378, "opening_source": "document", "entity": 1416}),
    ("syndicate_510_2018", 2018, {"opening": None, "triangle_entity": 510, "lob_gwp": 1376.7}),
    ("syndicate_510_2019", 2019, {"opening": None, "triangle_entity": 510}),
    ("syndicate_6104_2016", 2016, {"opening": 13.54, "entity": 6104}),
    ("syndicate_6104_2024", 2024, {"opening": 53.081, "entity": 6104, "triangle_entity": 6104}),
    ("syndicate_33_2024", 2024, {"opening": 3503.85, "entity": 33}),
])
def test_reference_filings_bind_to_the_requested_syndicate(stem, year, expect, monkeypatch):
    pdf = _filing(stem)
    if pdf is None or not (CACHE / f"{stem}_azure.json").exists():
        pytest.skip("source filing not present in this checkout")
    monkeypatch.setenv("LLOYDS_EXTRACTION_OFFLINE", "1")
    r = te.extract_tables(pdf, year, backend=te.TableBackend.AZURE, azure_paid=True)
    prov = r.provisions.to_dict() if r.provisions else {}
    assert prov.get("opening_gross_claims_outstanding") == expect["opening"]
    if expect.get("opening_source"):
        assert prov["opening_provenance"]["unit_source"] == expect["opening_source"]
    if expect.get("entity"):
        assert prov["opening_provenance"]["entity"] == expect["entity"]
    if expect.get("triangle_entity"):
        assert r.triangle is not None and r.triangle.entity == expect["triangle_entity"]
    if expect.get("lob_gwp"):
        assert r.lob is not None and r.lob.gross_premiums_written_gbp_m == expect["lob_gwp"]
    # a companion syndicate's table is never selected
    for obj in (r.triangle, r.lob, r.provisions):
        if obj is not None and getattr(obj, "entity", None) is not None:
            assert obj.entity == r.requested_syndicate
