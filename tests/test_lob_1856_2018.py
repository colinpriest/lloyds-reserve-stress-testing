"""Round 58 (review finding M03): 1856/2018's business mix is its whole segmental table.

The filing's Note 2 "Segmental Analysis" (PDF page 27) prints seven 2018 classes: six direct
classes under "Direct insurance:", then "Total Direct" 23,198, "Reinsurance" 120,770 and an
unlabelled grand total of 143,968. The record carried three of them, 14.2m:

  * the table step never read the grid: its "Net technical provisions" column tags it
    "provisions", and the premium gate excluded every such grid;
  * called on it, the row parser took "Total Direct" for the table's total and refused the
    complete classes as a double count;
  * the page-text fallback's fixed patterns found three classes and wrote their sum as the
    premium written, which the driver then copied over both models' 143.968.

Fully offline: the committed Azure cache (table index 2 is the page-27 grid) and the filing's
own page-27 text layer (tests/fixtures/syndicate_1856_2018_p27_segmental.txt). Two tests run
the Azure step on a two-page fixture PDF against a cache built here; the last two replay the
driver from the committed caches and need the source filings, which are not committed, so
they skip without them.

Run:  python -m pytest tests/test_lob_1856_2018.py -q
"""
import io
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import table_extraction as te  # noqa: E402

CACHE = ROOT / "pdf_extraction" / "azure_output" / "syndicate_1856_2018_azure.json"
PAGE_TEXT = ROOT / "tests" / "fixtures" / "syndicate_1856_2018_p27_segmental.txt"
TOTAL = 143.968     # the table's grand total, the income statement's and the models' readings
YEAR = 2018


def _tables():
    return json.load(io.open(CACHE, encoding="utf-8"))["tables"]


def _segmental():
    """Table index 2 and its categories as the Azure step sees them."""
    t = _tables()[2]
    return t["grid"], set(t["categories"]) | te._classify_table_content(t["grid"])


def _page_text():
    return io.open(PAGE_TEXT, encoding="utf-8").read()


def test_the_premium_gate_admits_the_page_27_grid():
    grid, cats = _segmental()
    # the fixture is the page-27 segmental table, tagged "provisions" for its last column
    cells = " ".join(" ".join(r) for r in grid)
    assert grid[0][0].strip() == str(YEAR) and "gross premiums written" in te._grid_text_lower(grid)
    assert "120,770" in cells and "143,968" in cells and "Total Direct" in cells
    assert {"premium_mix", "provisions"} <= cats
    assert te._admits_premium_grid(grid, cats)


def test_the_row_parser_reads_all_seven_classes():
    grid, _ = _segmental()
    lob = te._parse_nutrient_lob(grid, YEAR)
    assert lob is not None
    mix = {e["line_of_business"]: e["amount_gbp_m"] for e in lob.gross_premium_mix}
    assert len(mix) == 7, sorted(mix)
    assert mix["Reinsurance"] == pytest.approx(120.770, abs=5e-4)
    assert mix["Marine"] == pytest.approx(0.074, abs=5e-4)      # stored unrounded, not 0.1
    assert not any(te._is_total_label(name.lower()) for name in mix)
    assert sum(mix.values()) == pytest.approx(TOTAL, abs=5e-4)
    assert lob.class_sum == pytest.approx(TOTAL, abs=5e-4)
    assert lob.table_total == pytest.approx(TOTAL, abs=5e-4)
    assert lob.gross_premiums_written_gbp_m == pytest.approx(TOTAL, abs=5e-4)


def test_the_text_fallback_mix_is_refused_or_reconciles():
    """The page-text fallback still reads three classes (14.244m); it must never present
    their sum as the premium written, and the step must refuse it unless it reconciles
    with a gross premiums written figure the tables print (143.968)."""
    readings = te.gross_premiums_written_readings(
        [(t["grid"], t["orig_page"]) for t in _tables()], YEAR)
    assert any(r["value_m"] == pytest.approx(TOTAL, abs=5e-4) for r in readings), readings
    lob = te._parse_lob_from_text(_page_text(), YEAR)
    if lob is None:
        return
    assert lob.gross_premiums_written_gbp_m is None
    reading = te.reconciling_reading(lob.class_sum, readings)
    if reading is not None:
        assert lob.class_sum == pytest.approx(TOTAL, rel=0.02)
    else:
        assert abs(lob.class_sum - TOTAL) > 0.02 * TOTAL


# ------------------------------------------------------- the Azure step, end to end

INCOME_STATEMENT = 1    # "Gross premiums written | 2 | 143,968 | 91,378" in the committed cache


@pytest.fixture
def filing(tmp_path, monkeypatch):
    """A two-page stand-in for the filing: a cover page, then the page-27 text layer (a
    one-page PDF would be taken for a scanned filing and sent to OCR)."""
    fitz = pytest.importorskip("fitz", reason="PyMuPDF builds the fixture PDF")
    monkeypatch.setenv("LLOYDS_EXTRACTION_OFFLINE", "1")
    monkeypatch.delenv("LLOYDS_ALLOW_TABLE_BACKEND_CALLS", raising=False)
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "Arcus Syndicate 1856 annual report and accounts 2018", fontsize=9)
    page = doc.new_page(height=2600)      # 224 text lines at 6pt, none clipped
    page.insert_text((36, 36), _page_text().replace("’", "'"), fontsize=6)
    path = tmp_path / "syndicate_1856_2018.pdf"
    doc.save(str(path))
    doc.close()
    matches, _texts, _how, _rot = te._find_relevant_pages(path)
    if 1 not in matches or "premium_mix" not in matches[1]:
        pytest.skip("the fixture page was not classified as a premium page on this build")
    return path, sorted(matches)


def _cache(tmp_path, pdf, pages, tables):
    cache_dir = tmp_path / "azure_output"
    cache_dir.mkdir()
    payload = {"_cache_version": te._CACHE_VERSION, "_pages_hash": "_".join(str(p) for p in pages),
               "_batch_mode": "paid", "_page_mapping": "ascending-v1", "tables": tables}
    (cache_dir / (pdf.stem + "_azure.json")).write_text(json.dumps(payload), encoding="utf-8")
    return cache_dir


def test_the_azure_step_takes_the_segmental_grid(filing, tmp_path):
    pdf, pages = filing
    t = _tables()
    cache_dir = _cache(tmp_path, pdf, pages, [
        {"grid": t[INCOME_STATEMENT]["grid"], "orig_page": 1, "categories": ["pl_account"]},
        {"grid": t[2]["grid"], "orig_page": 1, "categories": t[2]["categories"]}])
    result = te._extract_azure(pdf, YEAR, cache_dir)
    assert result.lob is not None
    assert len(result.lob.gross_premium_mix) == 7
    assert result.lob.class_sum == pytest.approx(TOTAL, abs=5e-4)


def test_the_azure_step_refuses_the_partial_text_mix(filing, tmp_path):
    """With no premium grid in the cache the step falls back to the page text, reads three
    classes and must refuse them against the income statement's 143,968."""
    pdf, pages = filing
    t = _tables()
    cache_dir = _cache(tmp_path, pdf, pages, [
        {"grid": t[INCOME_STATEMENT]["grid"], "orig_page": 1, "categories": ["pl_account"]}])
    result = te._extract_azure(pdf, YEAR, cache_dir)
    assert result.lob is None or result.lob.class_sum == pytest.approx(TOTAL, rel=0.02), (
        result.lob and result.lob.to_dict())


# ------------------------------------------------------- the driver, replayed offline

@pytest.fixture
def replay(monkeypatch, tmp_path):
    """process_one_report from the committed caches, needing the source filing (not
    committed; the test skips without it). Nothing is written to the repository."""
    import test_gemini as tg
    monkeypatch.setenv("LLOYDS_EXTRACTION_OFFLINE", "1")
    monkeypatch.delenv("LLOYDS_ALLOW_TABLE_BACKEND_CALLS", raising=False)
    monkeypatch.chdir(ROOT)
    monkeypatch.setattr(tg, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(tg, "_save_inception_years", lambda inc: None)

    def run(stem):
        pdf = ROOT / "syndicate_reports" / "pdfs" / (stem + ".pdf")
        if not pdf.exists():
            pytest.skip("the source filing is not in this checkout")
        inception = json.load(io.open(ROOT / "pdf_extraction" / "syndicate_inception_years.json", encoding="utf-8"))
        res = tg.process_one_report(pdf, {int(k): int(v) for k, v in inception.items() if not k.startswith("_")})
        assert isinstance(res, tuple) and len(res) == 4
        return res[0]["models"]
    return run


def test_the_driver_applies_the_whole_table(replay):
    for name, block in replay("syndicate_1856_2018").items():
        mix = {e["line_of_business"]: e["amount_gbp_m"] for e in block["gross_premium_mix"]}
        assert len(mix) == 7 and sum(mix.values()) == pytest.approx(TOTAL, abs=5e-4), (name, mix)
        assert block["gross_premiums_written_gbp_m"] == pytest.approx(TOTAL, abs=5e-4), name
        assert "[LOB NOT APPLIED" not in (block.get("data_quality_notes") or "")


def test_the_driver_keeps_each_models_premium_written(replay):
    """The table's total goes under _adobe_lob only. 1856/2018's models both read exactly the
    table's 143.968, so 1209/2014 shows it: gemini read 302.0, gpt-5-mini 302.014, the
    segmental table prints 302.014, and each block keeps its own reading."""
    models = replay("syndicate_1209_2014")
    assert models["gemini-2.5-flash"]["gross_premiums_written_gbp_m"] == pytest.approx(302.0, abs=5e-4)
    assert models["gpt-5-mini"]["gross_premiums_written_gbp_m"] == pytest.approx(302.014, abs=5e-4)
    for block in models.values():
        lob = block["_adobe_lob"]
        assert lob["gross_premiums_written_gbp_m"] == pytest.approx(302.014, abs=5e-4)
        assert lob["class_sum"] == pytest.approx(302.014, abs=5e-4)
        assert block["gross_premium_mix"] == lob["gross_premium_mix"]
