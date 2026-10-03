"""The corpus scans and the offline-unservable list agree with the corpus (review of 2 October 2026, stage 2 item 10).

The review of the stage-1 follow-up (f4fdf559) found two gaps that no test needed the filings to close:

  * `pdf_extraction/ritc_scan.json` and `pdf_extraction/portfolio_transfer_scan.json` are read by the analysis. Each has to
    hold exactly the corpus's records, its own counts (`_meta`, where it has one) have to be its entries', and an entry that
    says detection failed has to be a filing that yields no text. Until f4fdf559 both said detection failed for 3210/2018,
    whose committed OCR page cache gives it text, and the transfer scan counted one failure.
  * `pdf_extraction/audit/offline_unservable.json` lists the records an offline replay cannot serve. Its `stems` and
    `no_usable_cache_not_attempted` have to be the committed records with no usable table cache: no Azure Document
    Intelligence cache, or one in the superseded list format the table step refuses.

Run:  python -m pytest tests/test_scans_and_unservable_list.py -q
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
EXTRACTION = ROOT / "pdf_extraction"
SCANS = ("ritc_scan.json", "portfolio_transfer_scan.json")


def _records():
    return sorted(p.stem for p in EXTRACTION.glob("syndicate_*_[0-9][0-9][0-9][0-9].json"))


def _scan(name):
    with open(EXTRACTION / name, encoding="utf-8") as fh:
        return json.load(fh)


def test_the_corpus_is_the_1065_records():
    assert len(_records()) == 1065


@pytest.mark.parametrize("name", SCANS)
def test_each_scan_holds_exactly_the_corpus_and_its_counts_are_its_entries(name):
    scan = _scan(name)
    entries = {k: v for k, v in scan.items() if k != "_meta"}
    corpus = {s[len("syndicate_"):] for s in _records()}
    assert set(entries) == corpus, ("not in the corpus: %s; not scanned: %s"
                                    % (sorted(set(entries) - corpus)[:10], sorted(corpus - set(entries))[:10]))
    for key, e in entries.items():
        assert e.get("detection") in ("successful", "failed"), (name, key, e.get("detection"))
    meta = scan.get("_meta")
    if meta is not None:
        assert meta["n_reports"] == len(entries), name
        assert meta["n_flagged"] == sum(1 for e in entries.values() if e.get("transfer_occurred") is True), name
        assert meta["n_detection_failed"] == sum(1 for e in entries.values() if e.get("detection") == "failed"), name


def _page_texts(stem):
    """The filing's page texts, from its committed OCR page cache where it has one, else from the filing; None when
    neither is here."""
    cache = EXTRACTION / "ocr_page_cache" / ("%s.json" % stem)
    if cache.exists():
        with open(cache, encoding="utf-8") as fh:
            return [e.get("text", "") for e in json.load(fh)]
    with open(EXTRACTION / ("%s.json" % stem), encoding="utf-8") as fh:
        source = ROOT / str(json.load(fh)["source_file"]).replace("\\", "/")
    if not source.exists():
        return None
    sys.path.insert(0, str(ROOT / "scripts"))
    import finalize_structural_eligibility_audit as fin
    return fin.page_texts(source)


def test_an_entry_that_says_detection_failed_is_a_filing_with_no_text():
    """A failed detection is a filing the scanners could not read. The check needs the filing (or its committed OCR page
    cache) only when such an entry exists; none does since f4fdf559."""
    failed = sorted({(name, key) for name in SCANS for key, e in _scan(name).items()
                     if key != "_meta" and e.get("detection") == "failed"})
    absent = []
    for name, key in failed:
        texts = _page_texts("syndicate_" + key)
        if texts is None:
            absent.append(key)
            continue
        assert not any(t.strip() for t in texts), ("%s says detection failed for %s, whose pages yield text" % (name, key))
    if absent:
        pytest.skip("source filings not present in this checkout")


def _no_usable_table_cache():
    out = []
    for stem in _records():
        cache = EXTRACTION / "azure_output" / ("%s_azure.json" % stem)
        if not cache.exists():
            out.append(stem)
            continue
        with open(cache, encoding="utf-8") as fh:
            if not isinstance(json.load(fh), dict):
                out.append(stem)
    return out


def test_the_unservable_list_is_the_records_with_no_usable_table_cache():
    with open(EXTRACTION / "audit" / "offline_unservable.json", encoding="utf-8") as fh:
        unservable = json.load(fh)
    uncached = _no_usable_table_cache()
    assert len(uncached) == 11, uncached
    assert sorted(unservable["stems"]) == uncached
    assert sorted(unservable["no_usable_cache_not_attempted"]) == uncached
