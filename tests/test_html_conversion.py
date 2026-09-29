"""Round 62 (review of 29 September 2026, MAT-2): an HTML filing's PDF conversion must carry its text.

Ten 2024 filings were written as having no claims development triangle because their conversion to
PDF kept text on the first eight to twelve pages only. They are pdf2htmlEX documents, which carry a
subset web font for every few pages; Chromium loads a web font when it first needs one, and under
Playwright 1.48 (Chromium 130) the print taken as soon as the page had loaded drew no text for pages
whose font was not yet in. Eighteen more conversions lost whole pages or 1-15% of their characters.
The pipeline classifies pages from the PDF's text, so a lost page is a lost note.

convert_html_to_pdf now loads every font before printing, fetches nothing the filing references,
and refuses a conversion -- new or cached -- that carries less text than the filing: fewer pages
with text than page containers with text, or under MIN_CONVERTED_TEXT_SHARE of the characters.

Run:  python -m pytest tests/test_html_conversion.py -q
"""
import inspect
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import test_gemini as tg  # noqa: E402

fitz = pytest.importorskip("fitz", reason="PyMuPDF builds the fixture PDFs")

PAGE = ('<div id="pf{n:x}" class="pf w0 h0"><div class="pc pc{n:x} w0 h0">'
        '<div class="t m0 x0 h1 y0 ff1 fs0">{text}</div></div></div>')


def _html(tmp_path, pages, name="syndicate_9999_2024.html"):
    body = "".join(PAGE.format(n=i + 1, text=t) for i, t in enumerate(pages))
    p = tmp_path / name
    p.write_text("<html><head><style>.pf{}</style></head><body><div id=\"page-container\">%s</div>"
                 "</body></html>" % body, encoding="utf-8")
    return p


def _pdf(tmp_path, pages, name="converted.pdf"):
    doc = fitz.open()
    for t in pages:
        page = doc.new_page()
        if t:
            page.insert_text((72, 72), t, fontsize=9)
    p = tmp_path / name
    doc.save(str(p))
    doc.close()
    return p


TEXTS = ["Claims development one year later 15,355", "Balance sheet claims outstanding 44,678",
         "Notes to the financial statements prior year"]


def test_page_containers_are_counted_from_the_source(tmp_path):
    html = _html(tmp_path, TEXTS + ["&#160;&#160;"])
    pages, with_text, chars = tg.html_page_text(html)
    assert (pages, with_text) == (4, 3), "a page of &#160; spacers is not a page with text"
    assert chars == sum(len("".join(t.split())) for t in TEXTS)


def test_html_without_page_containers_is_not_checked(tmp_path):
    p = tmp_path / "plain.html"
    p.write_text("<html><body><p>Claims development</p></body></html>", encoding="utf-8")
    assert tg.html_page_text(p) == (0, 0, 0)
    assert tg.conversion_lost_text(p, _pdf(tmp_path, [""])) is None


def test_a_whole_conversion_passes(tmp_path):
    assert tg.conversion_lost_text(_html(tmp_path, TEXTS), _pdf(tmp_path, TEXTS)) is None


def test_a_conversion_that_lost_pages_is_refused(tmp_path):
    """The 1902/2024 shape: every page printed, most of them with no text drawn."""
    why = tg.conversion_lost_text(_html(tmp_path, TEXTS), _pdf(tmp_path, [TEXTS[0], "", ""]))
    assert why and "text on 1 page(s)" in why


def test_a_conversion_that_lost_characters_is_refused(tmp_path):
    """The 4242/2024 shape: every page has text, a share of it is missing."""
    short = [TEXTS[0], TEXTS[1], "Notes"]
    why = tg.conversion_lost_text(_html(tmp_path, TEXTS), _pdf(tmp_path, short))
    assert why and "of the filing's page text" in why


def test_a_cached_conversion_that_lost_text_is_not_used(tmp_path, monkeypatch):
    monkeypatch.setattr(tg, "HTML_PDF_CACHE", tmp_path / "html_converted")
    (tmp_path / "html_converted").mkdir()
    html = _html(tmp_path, TEXTS)
    _pdf(tmp_path / "html_converted", [TEXTS[0], "", ""], name=html.stem + ".pdf")
    with pytest.raises(RuntimeError, match="lost text"):
        tg.convert_html_to_pdf(html)
    # a whole one is used as it is
    _pdf(tmp_path / "html_converted", TEXTS, name=html.stem + ".pdf")
    assert tg.convert_html_to_pdf(html) == tmp_path / "html_converted" / (html.stem + ".pdf")


def test_the_converter_loads_the_fonts_and_fetches_nothing_before_printing():
    src = inspect.getsource(tg.convert_html_to_pdf)
    assert "page.route(" in src and "route.abort()" in src
    assert src.index("page.route(") < src.index("page.goto(")
    assert src.index("_LOAD_ALL_FONTS") < src.index("page.pdf(")
    assert "f.load()" in tg._LOAD_ALL_FONTS and "document.fonts.ready" in tg._LOAD_ALL_FONTS
    # a new conversion is checked before it is cached
    assert src.index("conversion_lost_text(html_path, part)") < src.index("os.replace(part, pdf_path)")


def test_every_local_conversion_carries_its_filings_text():
    """The inputs the corpus is extracted from. The filings and their conversions are not committed,
    so this runs where they are present; 28 of the 95 committed-run conversions fail it."""
    htmls = sorted((ROOT / "syndicate_reports" / "pdfs").glob("*.html"))
    conv = ROOT / "pdf_extraction" / "html_converted"
    pairs = [(h, conv / (h.stem + ".pdf")) for h in htmls if (conv / (h.stem + ".pdf")).exists()]
    if not pairs:
        pytest.skip("source filings not present in this checkout")
    lost = {h.stem: why for h, p in pairs for why in [tg.conversion_lost_text(h, p)] if why}
    assert not lost, lost
