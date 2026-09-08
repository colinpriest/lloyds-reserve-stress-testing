"""Round 53 (review finding T01): the advertised offline replay runs without credentials.

`_extract_azure` used to read DOCUMENTINTELLIGENCE_ENDPOINT and _API_KEY at its first
statement and return an empty result when either was missing. Locating the relevant
pages and replaying the committed cache need no service access, so the workflow the
README advertises -- supply the source reports, set LLOYDS_EXTRACTION_OFFLINE=1, and
re-derive the deterministic tables from committed caches -- failed for want of
variables it never used. Six of the round-52 binding tests failed credential-free and
passed once placeholder values were supplied.

These tests build their own one-page PDF and their own cache, so they need neither the
uncommitted filings nor the network:

  * with both credential variables removed and a valid cache, extraction does the work
    instead of bailing out at a credential gate;
  * with both removed and no cache, it produces nothing rather than inventing content;
  * the credentials are not read before the cache branch (a source check, so the
    ordering cannot regress silently on a machine that happens to have them set).

Run:  python -m pytest tests/test_offline_replay.py -q
"""
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import table_extraction as te  # noqa: E402

fitz = pytest.importorskip("fitz", reason="PyMuPDF builds the fixture PDF")

CREDENTIALS = ("DOCUMENTINTELLIGENCE_ENDPOINT", "DOCUMENTINTELLIGENCE_API_KEY")

# text that _find_relevant_pages classifies, so the fixture reaches the cache branch
PAGE_TEXT = (
    "Notes to the financial statements\n"
    "Claims development table\n"
    "Gross claims development\n"
    "Underwriting year 2019 2020 2021 2022\n"
    "Estimate of ultimate gross claims 100.0 110.0 120.0 130.0\n"
)

GRID = [["Underwriting year", "2019", "2020"],
        ["Estimate of ultimate gross claims", "100.0", "110.0"]]


@pytest.fixture
def no_credentials(monkeypatch, tmp_path):
    for name in CREDENTIALS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LLOYDS_EXTRACTION_OFFLINE", "1")
    # the driver writes its OCR page cache to a repository-relative path, so the
    # test runs from tmp_path and leaves the repository's cache untouched
    (tmp_path / "pdf_extraction" / "ocr_page_cache").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def fixture_pdf(tmp_path):
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), PAGE_TEXT, fontsize=9)
    path = tmp_path / "syndicate_9999_2024.pdf"
    doc.save(str(path))
    doc.close()
    return path


def _write_cache(pdf_path, cache_dir, pages):
    """A cache in the current format for the pages the scan actually found."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "_cache_version": te._CACHE_VERSION,
        "_pages_hash": "_".join(str(p) for p in sorted(pages)),
        "_batch_mode": "free",
        "_page_mapping": "ascending-v1",
        "tables": [{"grid": GRID, "orig_page": sorted(pages)[0],
                    "categories": ["claims_triangle"]}],
    }
    (cache_dir / (pdf_path.stem + "_azure.json")).write_text(
        json.dumps(payload), encoding="utf-8")
    return payload


def _relevant_pages(pdf_path):
    matches, _texts, _how, _rot = te._find_relevant_pages(pdf_path)
    return sorted(matches)


def test_a_committed_cache_replays_with_no_credentials(no_credentials, fixture_pdf, tmp_path):
    pages = _relevant_pages(fixture_pdf)
    if not pages:
        pytest.skip("the fixture page was not classified as relevant on this build")
    cache_dir = tmp_path / "azure_output"
    _write_cache(fixture_pdf, cache_dir, pages)

    for name in CREDENTIALS:
        assert name not in os.environ

    result = te._extract_azure(fixture_pdf, 2024, cache_dir)
    # before the fix this returned a bare ExtractionResult() from the credential
    # check, so no method was recorded and the page scan had not run
    assert result.method == "azure", "extraction bailed out before doing any work"
    assert result.relevant_pages, "no relevant pages: the credential gate fired first"


def test_a_cache_miss_without_credentials_does_not_invent_a_result(
        no_credentials, fixture_pdf, tmp_path):
    pages = _relevant_pages(fixture_pdf)
    if not pages:
        pytest.skip("the fixture page was not classified as relevant on this build")
    empty_cache = tmp_path / "no_cache"
    empty_cache.mkdir()
    try:
        result = te._extract_azure(fixture_pdf, 2024, empty_cache)
    except Exception:
        return                      # refused outright, which is the required behaviour
    assert result.triangle is None and not result.provisions, (
        "a cache miss with no credentials produced extracted content")


def test_credentials_are_not_read_before_the_cache_branch():
    """The ordering itself, so it cannot regress on a machine that has the variables."""
    src = (ROOT / "table_extraction.py").read_text(encoding="utf-8")
    start = src.index("def _extract_azure(")
    nxt = src.find("\ndef ", start + 10)
    body = src[start:] if nxt == -1 else src[start:nxt]
    cache_branch = body.index("if not cache_valid:")
    for name in CREDENTIALS:
        first = body.find(name)
        assert first == -1 or first > cache_branch, (
            "%s is read before the cache branch of _extract_azure" % name)
