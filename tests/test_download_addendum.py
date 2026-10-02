"""The list of the corpus filings that have no ledger row (review of 2 October 2026, P-28; the author's decision, option B).

The ledger, syndicate_reports/download_status.json, has one row for each row of the workbook and none for 33 corpus filings,
which an earlier pass collected before the downloader existed (tests/test_download_ledger.py). The author decided on 2 October
2026 that the ledger gains no rows: the 33 are listed apart, with the web address Lloyd's site gave for each on a re-fetch and the
size and SHA-256 of the corpus copy, in syndicate_reports/download_addendum.json (built by scripts/build_download_addendum.py).

These tests hold that list to the corpus and the ledger (it names exactly the corpus filings that have no ledger row), to its own
rules (every entry is well formed and the header's counts are the entries'), to the files (every corpus copy is the file its entry
fingerprints; this needs the filings, which are not committed) and to the documents (the audit page and the README name the list,
and the page's counts and date are the list's). The well-formedness rules are themselves held to defective entries.

Run:  python -m pytest tests/test_download_addendum.py -q
"""
import calendar
import datetime
import functools
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlparse

import pytest

from test_download_ledger import _corpus, _ledger, _listed, _off_ledger_item

ROOT = Path(__file__).resolve().parents[1]
ADDENDUM = ROOT / "syndicate_reports" / "download_addendum.json"
FILES = ROOT / "syndicate_reports" / "pdfs"
README = ROOT / "README.md"
NAME = "syndicate_reports/download_addendum.json"

COPY_STATES = ("matches", "differs", "not found")
REQUIRED = {"stem", "syndicate", "year", "file", "source_url", "size_bytes", "sha256", "lloyds_copy"}
OPTIONAL = {"source_note", "lloyds_size_bytes", "lloyds_sha256", "note", "earlier_copy"}
HEADER_TEXTS = ("purpose", "why_not_in_the_ledger", "fingerprint")


@functools.lru_cache(maxsize=None)
def _addendum():
    return json.loads(ADDENDUM.read_text(encoding="utf-8"))


def _stem(entry):
    return entry["stem"].replace("syndicate_", "")


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _is_sha256(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _is_count(value):
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _lloyds_https(url):
    """An https address on lloyds.com or one of its subdomains (not a look-alike such as notlloyds.com)."""
    parts = urlparse(url)
    host = parts.hostname or ""
    return parts.scheme == "https" and (host == "lloyds.com" or host.endswith(".lloyds.com"))


def _entry_problems(e):
    """What is wrong with one entry, as plain statements; empty when it is well formed."""
    bad = []
    keys = set(e)
    if REQUIRED - keys:
        bad.append("missing keys %s" % sorted(REQUIRED - keys))
    if keys - REQUIRED - OPTIONAL:
        bad.append("unexpected keys %s" % sorted(keys - REQUIRED - OPTIONAL))
    if bad:
        return bad
    m = re.fullmatch(r"syndicate_(\d+)_(\d{4})", e["stem"])
    if not m:
        bad.append("stem %r is not syndicate_N_YYYY" % e["stem"])
    elif (int(m.group(1)), int(m.group(2))) != (e["syndicate"], e["year"]):
        bad.append("syndicate and year are not the stem's")
    if not (isinstance(e["file"], str) and re.fullmatch(re.escape(e["stem"]) + r"\.(pdf|html?)", e["file"])):
        bad.append("file %r is not the stem with .pdf or .html" % e["file"])
    url, note = e["source_url"], e.get("source_note")
    if url is None:
        if not (isinstance(note, str) and note.strip()):
            bad.append("no address and no source_note saying so")
    else:
        if not (isinstance(url, str) and _lloyds_https(url)):
            bad.append("source_url %r is not an https address on lloyds.com" % (url,))
        if note is not None:
            bad.append("an address and a source_note")
    if not _is_count(e["size_bytes"]):
        bad.append("size_bytes %r is not a positive whole number" % (e["size_bytes"],))
    if not _is_sha256(e["sha256"]):
        bad.append("sha256 %r is not 64 hexadecimal digits" % (e["sha256"],))
    state, extra = e["lloyds_copy"], {"lloyds_size_bytes", "lloyds_sha256"} & keys
    if state not in COPY_STATES:
        bad.append("lloyds_copy %r is not one of %s" % (state, COPY_STATES))
    elif state == "not found":
        if url is not None:
            bad.append("lloyds_copy is 'not found' but there is an address")
        if extra:
            bad.append("lloyds_copy is 'not found' but there is a Lloyd's fingerprint")
    else:
        if url is None:
            bad.append("lloyds_copy is %r but there is no address" % state)
        if state == "matches" and extra:
            bad.append("lloyds_copy is 'matches' but there is a Lloyd's fingerprint")
        if state == "differs":
            if extra != {"lloyds_size_bytes", "lloyds_sha256"}:
                bad.append("lloyds_copy is 'differs' without the Lloyd's size and SHA-256")
            elif not (_is_count(e["lloyds_size_bytes"]) and _is_sha256(e["lloyds_sha256"])):
                bad.append("the Lloyd's size or SHA-256 is malformed")
            elif e["lloyds_sha256"] == e["sha256"]:
                bad.append("lloyds_copy is 'differs' but the SHA-256 is the corpus copy's")
    if "note" in keys and not (isinstance(e["note"], str) and e["note"].strip()):
        bad.append("note is empty")
    if "earlier_copy" in keys:
        # a corpus copy that was replaced by Lloyd's file: the entry says which copy it was, and that the file is now Lloyd's
        early = e["earlier_copy"]
        if not (isinstance(early, dict) and set(early) == {"size_bytes", "sha256"}):
            bad.append("earlier_copy is not a size and a SHA-256")
        elif not (_is_count(early["size_bytes"]) and _is_sha256(early["sha256"])):
            bad.append("the earlier copy's size or SHA-256 is malformed")
        elif early["sha256"] == e["sha256"]:
            bad.append("the earlier copy has the corpus copy's own SHA-256")
        if state != "matches":
            bad.append("earlier_copy, but lloyds_copy is %r: a replaced copy is Lloyd's file" % state)
        if "note" not in keys:
            bad.append("earlier_copy without a note on it")
    return bad


def test_the_list_is_the_corpus_filings_with_no_ledger_row():
    """Exactly those filings, each once, and the audit page lists the same ones."""
    stems = [_stem(e) for e in _addendum()["filings"]]
    assert len(stems) == len(set(stems)), sorted(s for s in set(stems) if stems.count(s) > 1)
    off = _corpus() - set(_ledger())
    assert set(stems) == off, {"listed, but with a ledger row or no record": sorted(set(stems) - off),
                               "no ledger row, but not listed": sorted(off - set(stems))}
    assert _listed(_off_ledger_item()[1]) == off


def test_the_header_says_what_the_list_is_and_its_counts_are_the_entries():
    data = _addendum()
    for key in HEADER_TEXTS:
        assert isinstance(data[key], str) and data[key].strip(), key
    assert "record of what the extraction read" in data["fingerprint"]
    assert set(data["lloyds_copy"]) == set(COPY_STATES) and all(data["lloyds_copy"].values())
    refetch = data["refetch"]
    datetime.date.fromisoformat(refetch["date"])
    assert refetch["route"].strip()
    entries = data["filings"]
    states = [e["lloyds_copy"] for e in entries]
    assert data["counts"] == {"filings": len(entries), "matches": states.count("matches"),
                              "differs": states.count("differs"), "not_found": states.count("not found")}, data["counts"]
    if any("earlier_copy" in e for e in entries):
        assert "earlier_copy" in data["fingerprint"], "the header does not say that a replaced copy has an earlier copy"


def test_every_entry_is_well_formed():
    entries = _addendum()["filings"]
    assert entries, "the list is empty"
    found = {e["stem"]: _entry_problems(e) for e in entries if _entry_problems(e)}
    assert not found, found
    urls = [e["source_url"] for e in entries if e["source_url"]]
    assert len(urls) == len(set(urls)), "two filings share one address: %s" % sorted(u for u in set(urls) if urls.count(u) > 1)


GOOD = {"stem": "syndicate_9901_2099", "syndicate": 9901, "year": 2099, "file": "syndicate_9901_2099.pdf",
        "source_url": "https://assets.lloyds.com/assets/example.pdf", "size_bytes": 10, "sha256": "a" * 64,
        "lloyds_copy": "matches"}
GOOD_DIFFERS = dict(GOOD, lloyds_copy="differs", lloyds_size_bytes=20, lloyds_sha256="b" * 64)
GOOD_NOT_FOUND = dict(GOOD, source_url=None, source_note="No address was found.", lloyds_copy="not found")
GOOD_REPLACED = dict(GOOD, earlier_copy={"size_bytes": 5, "sha256": "c" * 64}, note="This file replaced an earlier corpus copy.")


def _without(entry, *keys):
    return {k: v for k, v in entry.items() if k not in keys}


#: (what is wrong, the entry, a word the report of it contains)
DEFECTS = [
    ("an address that is not https", dict(GOOD, source_url="http://assets.lloyds.com/assets/example.pdf"), "https"),
    ("another host", dict(GOOD, source_url="https://assets.example.com/assets/example.pdf"), "lloyds.com"),
    ("a look-alike host", dict(GOOD, source_url="https://notlloyds.com/assets/example.pdf"), "lloyds.com"),
    ("lloyds.com as a prefix", dict(GOOD, source_url="https://lloyds.com.example.org/example.pdf"), "lloyds.com"),
    ("an empty address", dict(GOOD, source_url=""), "lloyds.com"),
    ("no address and no note", _without(GOOD_NOT_FOUND, "source_note"), "source_note"),
    ("no address and a blank note", dict(GOOD_NOT_FOUND, source_note="  "), "source_note"),
    ("an address and a note", dict(GOOD, source_note="No address was found."), "source_note"),
    ("a SHA-256 of 63 digits", dict(GOOD, sha256="a" * 63), "sha256"),
    ("a SHA-256 in capitals", dict(GOOD, sha256="A" * 64), "sha256"),
    ("a SHA-256 that is not hexadecimal", dict(GOOD, sha256="g" * 64), "sha256"),
    ("a size of zero", dict(GOOD, size_bytes=0), "size_bytes"),
    ("a negative size", dict(GOOD, size_bytes=-5), "size_bytes"),
    ("a size that is true", dict(GOOD, size_bytes=True), "size_bytes"),
    ("a size that is text", dict(GOOD, size_bytes="10"), "size_bytes"),
    ("a state the list does not use", dict(GOOD, lloyds_copy="identical"), "lloyds_copy"),
    ("differs without the Lloyd's fingerprint", dict(GOOD, lloyds_copy="differs"), "differs"),
    ("differs with the corpus copy's own SHA-256", dict(GOOD_DIFFERS, lloyds_sha256="a" * 64), "differs"),
    ("differs with a malformed Lloyd's SHA-256", dict(GOOD_DIFFERS, lloyds_sha256="b" * 10), "malformed"),
    ("matches with a Lloyd's fingerprint", dict(GOOD, lloyds_size_bytes=20, lloyds_sha256="b" * 64), "matches"),
    ("not found with an address", dict(GOOD, lloyds_copy="not found"), "not found"),
    ("matches with no address", dict(GOOD_NOT_FOUND, lloyds_copy="matches"), "no address"),
    ("a stem that is not the file's", dict(GOOD, file="syndicate_9902_2099.pdf"), "file"),
    ("a year that is not the stem's", dict(GOOD, year=2098), "stem"),
    ("a missing key", _without(GOOD, "sha256"), "missing"),
    ("an unknown key", dict(GOOD, comment="x"), "unexpected"),
    ("an empty note", dict(GOOD_DIFFERS, note=" "), "note"),
    ("an earlier copy that is not a size and a SHA-256", dict(GOOD_REPLACED, earlier_copy="x"), "not a size and a SHA-256"),
    ("an earlier copy with an extra key", dict(GOOD_REPLACED, earlier_copy={"size_bytes": 5, "sha256": "c" * 64, "file": "x"}),
     "not a size and a SHA-256"),
    ("an earlier copy with no size", dict(GOOD_REPLACED, earlier_copy={"sha256": "c" * 64}), "not a size and a SHA-256"),
    ("an earlier copy with a size of zero", dict(GOOD_REPLACED, earlier_copy={"size_bytes": 0, "sha256": "c" * 64}), "earlier copy's size"),
    ("an earlier copy with a short SHA-256", dict(GOOD_REPLACED, earlier_copy={"size_bytes": 5, "sha256": "c" * 10}), "earlier copy's size"),
    ("an earlier copy that is the corpus copy", dict(GOOD_REPLACED, earlier_copy={"size_bytes": 5, "sha256": "a" * 64}), "own SHA-256"),
    ("an earlier copy on an entry that is not Lloyd's file", dict(GOOD_REPLACED, lloyds_copy="differs", lloyds_size_bytes=20,
                                                                     lloyds_sha256="b" * 64), "a replaced copy is Lloyd's file"),
    ("an earlier copy with no note", _without(GOOD_REPLACED, "note"), "without a note"),
]


def test_the_well_formedness_checks_pass_good_entries_and_catch_each_defect():
    """The control for the test above: a check that cannot fail proves nothing, so each rule is run on an entry broken in
    exactly that way, and the report must name it."""
    for good in (GOOD, GOOD_DIFFERS, GOOD_NOT_FOUND, GOOD_REPLACED):
        assert _entry_problems(good) == [], good
    assert len(DEFECTS) >= 35
    for what, entry, word in DEFECTS:
        problems = _entry_problems(entry)
        assert problems, "not caught: %s" % what
        assert any(word in p for p in problems), (what, word, problems)


def test_every_corpus_file_is_the_one_its_entry_fingerprints():
    """Each entry's size and SHA-256 are those of the file in syndicate_reports/pdfs. Needs the filings."""
    if not FILES.exists():
        pytest.skip("source filings not present in this checkout")
    for e in _addendum()["filings"]:
        path = FILES / e["file"]
        assert path.is_file(), "the corpus has no %s" % e["file"]
        assert path.stat().st_size == e["size_bytes"], (e["file"], path.stat().st_size, e["size_bytes"])
        assert _sha256(path) == e["sha256"], e["file"]


def _long(d):
    """A date as the documents write it: 2 October 2026."""
    return "%d %s %d" % (d.day, calendar.month_name[d.month], d.year)


def test_the_audit_page_names_the_list_and_states_its_counts_and_date():
    """The item on the filings the ledger does not hold says where the list is, when they were looked up again, how the file at
    each address compares (and which filings differ, if any) and which corpus copy was replaced: every figure is the list's own."""
    _, item = _off_ledger_item()
    assert NAME in item, "the audit page's item does not name the list"
    data = _addendum()
    counts, entries = data["counts"], data["filings"]
    m = re.search(r"found an address for (\d+) of the (\d+)", item)
    assert m, "the item does not say for how many an address was found"
    assert (int(m.group(1)), int(m.group(2))) == (counts["matches"] + counts["differs"], counts["filings"]), m.group(0)
    m = re.search(r"is, byte for byte, the corpus copy for (\d+) of them; it differs for (\d+)(?:, ([^.]*?) whose)?", item)
    assert m, "the item does not say how many of the files match and how many differ"
    differs = {"%s/%s" % (e["syndicate"], e["year"]) for e in entries if e["lloyds_copy"] == "differs"}
    named = set(re.findall(r"\b(\d{2,4}/20\d\d)\b", m.group(3) or ""))
    assert (int(m.group(1)), int(m.group(2)), named) == (counts["matches"], counts["differs"], differs), m.group(0)
    m = re.search(r"found no address for the other (\d+)", item)
    assert m and int(m.group(1)) == counts["not_found"], (m and m.group(0), counts["not_found"])
    refetched = datetime.date.fromisoformat(data["refetch"]["date"])
    assert "re-fetch of %s" % _long(refetched) in item
    replaced = {"%s/%s" % (e["syndicate"], e["year"]): e for e in entries if "earlier_copy" in e}
    m = re.search(r"The corpus copy of ((?:\d{2,4}/20\d\d(?:,? and |, )?)+) (?:was|were) replaced on (\d{1,2} [A-Za-z]+ \d{4})", item)
    if replaced:
        assert m, "the item does not say which corpus copy was replaced"
        assert set(re.findall(r"\d{2,4}/20\d\d", m.group(1))) == set(replaced), (m.group(0), sorted(replaced))
        assert m.group(2) == _long(refetched), m.group(0)
        for label, e in replaced.items():
            assert "{:,}".format(e["earlier_copy"]["size_bytes"]) in item, (label, "the earlier copy's size")
        assert ("cut-short download" in item) == all("cut short" in e["note"] for e in replaced.values()), (
            "the item calls the earlier copy a cut-short download, or not, against the list's note")
    else:
        assert not m, "the item names a replaced corpus copy that the list does not"


def test_a_replaced_copys_note_is_what_the_files_and_the_extraction_record_say():
    """An entry whose corpus copy replaced another says in its note when, how long the earlier copy was (and, when it is the first
    bytes of this file, how long this one is) and which of the two its filing's extraction record was made from: the record's own
    date against the replacement's. Each is checked here against the entry and the committed record."""
    data = _addendum()
    replaced_on = datetime.date.fromisoformat(data["refetch"]["date"])
    seen = 0
    for e in data["filings"]:
        if "earlier_copy" not in e:
            continue
        seen += 1
        note = " ".join(e["note"].split())
        assert "replaced an earlier corpus copy on %s" % _long(replaced_on) in note, e["stem"]
        assert "{:,} bytes".format(e["earlier_copy"]["size_bytes"]) in note, e["stem"]
        if "a download cut short" in note:
            assert "the first {:,} bytes of this file ({:,} bytes)".format(e["earlier_copy"]["size_bytes"], e["size_bytes"]) in note, e["stem"]
            assert e["earlier_copy"]["size_bytes"] < e["size_bytes"], e["stem"]
        record = json.loads((ROOT / "pdf_extraction" / (e["stem"] + ".json")).read_text(encoding="utf-8"))
        written = datetime.date.fromisoformat(record["extraction_timestamp"][:10])
        assert "written on %s" % _long(written) in note, (e["stem"], "the note does not give the record's date")
        before = "before the replacement, so it was made from the earlier copy" in note
        after = "after the replacement" in note
        assert (before, after) == ((True, False) if written < replaced_on else (False, True)), (e["stem"], written, replaced_on)
    assert seen, "no entry has an earlier copy, so this test checked nothing"


def test_the_readme_download_step_points_to_the_list():
    text = " ".join(README.read_text(encoding="utf-8").split())
    start = text.index("#### 1. Download syndicate reports")
    step = text[start:text.index("####", start + 10)]
    assert NAME in step, "step 1 of the README's Quick Start does not point to the list of the filings the ledger lacks"
