"""The OCR page caches, pdf_extraction/ocr_page_cache/syndicate_NNNN_YYYY.json, and the one filing the run-off register reads from its
cache alone: 3210/2018, fetched again on 2 October 2026 (README item 9).

A cache is the Tesseract text of a scanned filing, page by page: a list of {"page": a 1-based number, "text": the page's text}. Three
readers rely on it: table_extraction._find_pages_ocr (which takes a cache only if it has as many entries as the filing has pages),
test_gemini.extract_text_from_pdf, and the audit's page reader (finalize_structural_eligibility_audit.page_texts: for a page whose
text layer holds 50 characters or fewer, the cache's text of that page). The 203 caches committed before 2 October 2026 share one
format, and so does the cache that table_extraction._find_pages_ocr wrote for 3210/2018 on that day, with the local Tesseract and no
network. These tests hold every cache to that format (with a control that feeds the check malformed caches), each cache to its
filing's page count where the filing is present, and 3210/2018 to being read from its cache.

Run:  python -m pytest tests/test_ocr_page_cache.py -q
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import finalize_structural_eligibility_audit as fin  # noqa: E402

CACHES = ROOT / "pdf_extraction" / "ocr_page_cache"
FILINGS = ROOT / "syndicate_reports" / "pdfs"


def _caches():
    return sorted(CACHES.glob("syndicate_*.json"))


def _format_problems(raw):
    """What is wrong with one cache's bytes, as plain statements; empty when it has the format every committed cache has: a list
    of {page, text} numbered 1..n, a string for each page's text, and exactly what json.dump writes by default (pure ASCII, on one
    line)."""
    try:
        rows = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        return ["not JSON (%s)" % type(exc).__name__]
    if not (isinstance(rows, list) and rows):
        return ["not a non-empty list"]
    if not all(isinstance(r, dict) and set(r) == {"page", "text"} for r in rows):
        return ["an element is not exactly {page, text}"]
    bad = []
    if not all(type(r["page"]) is int for r in rows) or [r["page"] for r in rows] != list(range(1, len(rows) + 1)):
        bad.append("the pages are not the integers 1..n in order")
    if not all(isinstance(r["text"], str) for r in rows):
        bad.append("a page's text is not a string")
    elif not any(r["text"].strip() for r in rows):
        bad.append("no page has any text")
    if not all(b < 128 for b in raw):
        bad.append("the file is not pure ASCII")
    if b"\n" in raw or b"\r" in raw:
        bad.append("the file is not on one line")
    if not bad and json.dumps(rows) != raw.decode("ascii"):
        bad.append("the file is not what json.dump writes by default")
    return bad


def test_every_ocr_page_cache_has_the_format_the_committed_ones_share():
    files = _caches()
    assert len(files) >= 204, "the committed caches are 203 and 3210/2018's: %d" % len(files)
    found = {p.name: _format_problems(p.read_bytes()) for p in files}
    assert not {k: v for k, v in found.items() if v}, {k: v for k, v in found.items() if v}


GOOD_ROWS = [{"page": 1, "text": "Syndicate 3210"}, {"page": 2, "text": "Report of the Directors\n"}]
GOOD = json.dumps(GOOD_ROWS).encode("ascii")

#: (what is wrong, the bytes, a word the report of it contains)
DEFECTS = [
    ("not JSON", b"[{", "not JSON"),
    ("bytes that are not UTF-8", b"\xff\xfe", "not JSON"),
    ("an empty list", b"[]", "non-empty"),
    ("an object, not a list", json.dumps({"1": "text"}).encode(), "non-empty list"),
    ("an element with an extra key", json.dumps([dict(GOOD_ROWS[0], file="x")]).encode(), "exactly"),
    ("an element with no text", json.dumps([{"page": 1}]).encode(), "exactly"),
    ("pages that start at 0", json.dumps([{"page": 0, "text": "a"}, {"page": 1, "text": "b"}]).encode(), "1..n"),
    ("pages out of order", json.dumps([{"page": 2, "text": "a"}, {"page": 1, "text": "b"}]).encode(), "1..n"),
    ("a page missing", json.dumps([{"page": 1, "text": "a"}, {"page": 3, "text": "b"}]).encode(), "1..n"),
    ("a page number that is text", json.dumps([{"page": "1", "text": "a"}]).encode(), "1..n"),
    ("a page number that is true", json.dumps([{"page": True, "text": "a"}]).encode(), "1..n"),
    ("a page number that is a float", json.dumps([{"page": 1.0, "text": "a"}]).encode(), "1..n"),
    ("a page's text that is null", json.dumps([{"page": 1, "text": None}]).encode(), "not a string"),
    ("every page blank", json.dumps([{"page": 1, "text": " \n"}, {"page": 2, "text": ""}]).encode(), "no page has any text"),
    ("non-ASCII written out", json.dumps(GOOD_ROWS + [{"page": 3, "text": "£5m"}], ensure_ascii=False).encode("utf-8"), "ASCII"),
    ("two lines", json.dumps(GOOD_ROWS, indent=1).encode(), "one line"),
    ("a carriage return", GOOD.replace(b"]", b"]\r"), "one line"),
    ("other separators", json.dumps(GOOD_ROWS, separators=(",", ":")).encode(), "json.dump writes"),
]


def test_the_format_check_passes_a_good_cache_and_catches_each_way_one_can_be_malformed():
    """The control for the test above: each rule is run on bytes broken in exactly that way, and the report must name it."""
    assert _format_problems(GOOD) == []
    assert len(DEFECTS) >= 18
    for what, raw, word in DEFECTS:
        problems = _format_problems(raw)
        assert problems, "not caught: %s" % what
        assert any(word in p for p in problems), (what, word, problems)


def test_each_cache_has_as_many_entries_as_its_filing_has_pages():
    """table_extraction._find_pages_ocr takes a cache only when it has one entry for each page of the filing; any other length is
    a cache nothing uses. Needs the filings."""
    fitz = pytest.importorskip("fitz", reason="PyMuPDF not installed")
    pairs = [(c, FILINGS / (c.stem + ".pdf")) for c in _caches() if (FILINGS / (c.stem + ".pdf")).exists()]
    if not pairs:
        pytest.skip("source filings not present in this checkout")
    for cache, pdf in pairs:
        with fitz.open(pdf) as doc:
            assert doc.page_count == len(json.loads(cache.read_text(encoding="utf-8"))), cache.name
    assert len(pairs) >= 150, len(pairs)


def test_3210_2018_is_read_from_its_ocr_page_cache():
    """Lloyd's file for 3210/2018 is a scan: no page has a text layer, so the audit's page reader returns the cache's text of
    every page, and every page has some. (Before 2 October 2026 the local file was a cut-short download that opened with no
    page, and the filing was read as nothing.) Needs the filing."""
    fitz = pytest.importorskip("fitz", reason="PyMuPDF not installed")
    pdf = FILINGS / "syndicate_3210_2018.pdf"
    if not pdf.exists():
        pytest.skip("source filings not present in this checkout")
    cache = json.loads((CACHES / "syndicate_3210_2018.json").read_text(encoding="utf-8"))
    with fitz.open(pdf) as doc:
        layer = [len(page.get_text().strip()) for page in doc]
    assert len(layer) == len(cache) > 0, (len(layer), len(cache))
    assert max(layer) <= 50, "a page has a text layer, so the reader would not take the cache's text there: %s" % layer
    texts = fin.page_texts(pdf)
    assert texts == [row["text"] for row in cache], "the reader does not return the cache's text, page for page"
    assert all(t.strip() for t in texts), [i + 1 for i, t in enumerate(texts) if not t.strip()]


def test_the_pipeline_doc_says_of_3210_2018_what_the_cache_and_the_committed_files_show():
    """docs/ocr-pipeline.md (11.2 and 11.4) says what Lloyd's complete file shows that the cut-short copy could not: the audit's
    inception terms match nothing in its pages; page 41 prints a gross and a net claims development table of the underwriting years
    2011 to 2016, every cohort of it up to t-2; and no table backend has read it, so its record, written on 11 September 2026 from the
    earlier copy, is unchanged. Committed files only, so it runs in any checkout."""
    import re

    import audit_structural_eligibility as audit   # its INCEPTION_TERMS are the inception wording the doc names

    texts = [row["text"] for row in json.loads((CACHES / "syndicate_3210_2018.json").read_text(encoding="utf-8"))]
    doc = " ".join((ROOT / "docs" / "ocr-pipeline.md").read_text(encoding="utf-8").split())
    # 11.2: no start statement
    assert [p for p, t in enumerate(texts, 1) if audit.INCEPTION_TERMS.search(" ".join(t.split()))] == []
    assert "(`INCEPTION_TERMS` in `scripts/audit_structural_eligibility.py`) match nothing in its %d pages" % len(texts) in doc
    assert "ceased to write new business at 31 December 2016" in " ".join(texts[4].split())
    assert "3210/2018, could not be read when it was made: its local PDF was a cut-short download that opened with no page" in doc
    # 11.4: page 41's two tables
    page41 = " ".join(texts[40].split())
    assert "Claims development" in page41
    headers = re.findall(r"((?:20\d\d ){6})Total", page41)
    assert len(headers) == 2, "page 41 does not print two tables (gross and net) of six underwriting years each: %s" % headers
    years = sorted({int(y) for h in headers for y in h.split()})
    assert (years[0], years[-1]) == (2011, 2016) and years[-1] <= 2018 - 2, years
    assert "page 41 prints a gross and a net claims development table by underwriting year (%d to %d, £000), every cohort of it up to t-2" % (
        years[0], years[-1]) in doc
    absent = json.loads((ROOT / "pdf_extraction" / "audit" / "backend_cache_absent.json").read_text(encoding="utf-8"))["records"]
    assert "syndicate_3210_2018" in {r["stem"] for r in absent}, "a table backend cache exists, or the audit file is stale"
    record = json.loads((ROOT / "pdf_extraction" / "syndicate_3210_2018.json").read_text(encoding="utf-8"))
    assert record["extraction_timestamp"].startswith("2026-09-11") and record["status"] == "no_deterministic_reading"
    assert "The record was written on 11 September 2026 from the earlier local copy" in doc
