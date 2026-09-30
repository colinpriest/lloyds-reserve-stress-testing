"""Fourth cycle of round 62 (1 October 2026): what the corpus's filings say about a syndicate's own run-off, year by year.

The author's in-sample decision (option A) excludes a syndicate-year whose own filing states that the syndicate was in
run-off for the whole year, unless the model assigns it to the assumed-business regime. The exclusion needs one thing from
the extraction: for every syndicate-year whose filing speaks of the syndicate itself running off or ceasing to underwrite,
the filing's words, the page and the file they are on, and a category. `pdf_extraction/audit/runoff_corpus_register.json`
holds that for 88 syndicate-years:

  WHOLE     in run-off, or ceased underwriting, from the start of the year or before: a run-off year
  PART      the run-off begins during the year
  AFTER     the run-off begins at or after the year end; the syndicate was underwriting during the year
  NOTCOUNT  not counted: the filing's words do not settle it, or the statement is about another entity

These tests hold the register to its own rules (a category has to agree with the date the filing gives), to the filings (each
quote is printed on the page it cites, in the file whose hash the register holds) and to the premium register
(`runoff_register.json`, the nine records the premium rule reads), whose entries it copies where the two overlap.

Seven readings differ from the first reading of the corpus (30 September 2026), and their verdicts are pinned below: 2088/2019
wrote business throughout 2019 and the run-off follows; 2468/2020's run-off began on 6 January 2020; 1884/2023 and 1884/2024
never say the syndicate is in run-off and say it underwrites reinsurance to close and legacy reinsurance; 1254/2022 and
1254/2023 describe a portfolio and a kind of syndicate; 1975/2021 says the decision is to cease underwriting after 2022.

Run:  python -m pytest tests/test_runoff_corpus_register.py -q
"""
import hashlib
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import finalize_structural_eligibility_audit as fin  # noqa: E402

CORPUS = ROOT / "pdf_extraction" / "audit" / "runoff_corpus_register.json"
PREMIUM = ROOT / "pdf_extraction" / "audit" / "runoff_register.json"
CATEGORIES = ("WHOLE", "PART", "AFTER", "NOTCOUNT")
FIELDS = {"stem", "syndicate", "year", "category", "runoff_from", "source_file", "source_sha256", "source_page",
          "source_page_printed", "evidence", "other_statements", "note_quotes", "note"}
#: the fields a corpus entry copies from the premium register where the two hold the same record
COPIED = ("runoff_from", "source_file", "source_sha256", "source_page", "source_page_printed", "evidence",
          "other_statements", "note_quotes", "note")
#: what the filing's words say when they say the syndicate is in run-off or has ceased to write
RUNOFF_WORDS = re.compile(r"run-?\s?off|ceased (to )?(underwrit|trad|writ)|cease (to )?(underwrit|writ)|"
                          r"no longer (underwrit|writ)|cessation", re.I)
#: the WHOLE entries without a start date. Each says in its own words that the syndicate is in run-off (3500 has been a run-off
#: vehicle since it was formed in 2003, 6124 was established in 2015 as a special legacy syndicate, 2255/2015 is the author's
#: decision); a WHOLE entry that is not dated and not in this set has to be argued for here.
UNDATED_WHOLE = {"syndicate_2008_2023", "syndicate_2255_2015", "syndicate_3330_2018", "syndicate_3500_2018",
                 "syndicate_3500_2019", "syndicate_3500_2021", "syndicate_3500_2022", "syndicate_3500_2023",
                 "syndicate_6124_2015"}
#: the seven readings re-read in the fourth cycle, with their verdicts. A different verdict is the author's decision.
RE_READ = {"syndicate_2088_2019": "AFTER", "syndicate_2468_2020": "PART", "syndicate_1884_2023": "NOTCOUNT",
           "syndicate_1884_2024": "NOTCOUNT", "syndicate_1254_2022": "NOTCOUNT", "syndicate_1254_2023": "NOTCOUNT",
           "syndicate_1975_2021": "AFTER"}
COUNTS = {"WHOLE": 37, "PART": 8, "AFTER": 27, "NOTCOUNT": 16}
#: the premium register's entries that are not corpus entries: a live syndicate whose negative premium is a return premium
NOT_IN_CORPUS = {"syndicate_3623_2018"}


def _load():
    return json.loads(CORPUS.read_text(encoding="utf-8"))


def _records():
    return _load()["records"]


def _nine():
    return {r["stem"]: r for r in json.loads(PREMIUM.read_text(encoding="utf-8"))["records"]}


def _norm(text):
    """Hyphen variants and ligatures written as they print."""
    for bad, good in (("‐", "-"), ("‑", "-"), ("‒", "-"), ("–", "-"), ("—", "-"), ("−", "-"),
                      ("­", ""), ("ﬁ", "fi"), ("ﬂ", "fl")):
        text = text.replace(bad, good)
    return text


def _collapse(text):
    return " ".join(text.split())


def _quoted_in(note):
    """The phrases a note puts in single quotes. An apostrophe inside a word neither opens nor closes one."""
    return re.findall(r"(?<![A-Za-z0-9])'(.+?)'(?![A-Za-z0-9])", note)


def _years(text):
    return [int(y) for y in re.findall(r"\b(?:19|20)\d\d\b", text or "")]


def _undated(r):
    return r["runoff_from"] is None or r["runoff_from"].startswith("not stated")


def _citations(r):
    """(page, printed page, quote) for everything the entry cites."""
    return ([(r["source_page"], r["source_page_printed"], r["evidence"])]
            + [(s["page"], s["page_printed"], s["quote"]) for s in r["other_statements"] + r["note_quotes"]])


def test_the_register_is_one_reading_per_syndicate_year_with_its_category_and_its_counts():
    data = _load()
    assert set(data) == {"purpose", "recorded", "categories", "premium_register", "sources", "records", "reviewed_not_run_off"}
    assert tuple(data["categories"]) == CATEGORIES
    records = data["records"]
    stems = [r["stem"] for r in records]
    assert len(stems) == len(set(stems)) == 88
    assert stems == [s for _, s in sorted(((r["syndicate"], r["year"]), r["stem"]) for r in records)], "sorted by syndicate and year"
    for r in records:
        assert set(r) == FIELDS, r["stem"]
        assert r["stem"] == "syndicate_%d_%d" % (r["syndicate"], r["year"])
        assert r["category"] in CATEGORIES, r["stem"]
        assert r["runoff_from"] is None or (isinstance(r["runoff_from"], str) and r["runoff_from"].strip()), r["stem"]
    got = {c: sum(r["category"] == c for r in records) for c in CATEGORIES}
    assert got == COUNTS, got
    # every entry belongs to a committed record of the same filing
    for r in records:
        path = ROOT / "pdf_extraction" / (r["stem"] + ".json")
        assert path.exists(), r["stem"]
        source = json.loads(path.read_text(encoding="utf-8"))["source_file"].replace("\\", "/")
        assert source == r["source_file"], (r["stem"], source, r["source_file"])


def test_each_entry_carries_its_words_its_page_its_printed_page_and_its_hash():
    for r in _records():
        assert isinstance(r["evidence"], str) and r["evidence"].strip(), r["stem"]
        assert isinstance(r["source_page"], int) and not isinstance(r["source_page"], bool) and r["source_page"] >= 1, r["stem"]
        assert re.fullmatch(r"[0-9a-f]{64}", r["source_sha256"]), r["stem"]
        assert re.fullmatch(r"[1-9][0-9]{0,2}", str(r["source_page_printed"])), r["stem"]
        for q in r["other_statements"] + r["note_quotes"]:
            assert set(q) == {"page", "page_printed", "quote"} and q["page"] >= 1 and q["quote"].strip(), r["stem"]
            assert re.fullmatch(r"[1-9][0-9]{0,2}", str(q["page_printed"])), r["stem"]
        for page, printed, _ in _citations(r):
            assert 1 <= int(printed) <= page, (r["stem"], page, printed)
        if r["note"] is not None:
            assert isinstance(r["note"], str) and r["note"].strip(), r["stem"]


def test_a_category_agrees_with_the_words_and_the_date_the_filing_gives():
    """WHOLE starts on or before the first day of the year; PART starts after it, in the year; AFTER starts at or after the
    year end; every reading except NOTCOUNT is in the filing's run-off words; a NOTCOUNT entry says why in its note."""
    for r in _records():
        t, frm, words = r["year"], r["runoff_from"], _norm(" ".join(q for _, _, q in _citations(r)))
        if r["category"] != "NOTCOUNT":
            assert RUNOFF_WORDS.search(words), r["stem"]
        if r["category"] == "NOTCOUNT":
            assert r["note"] and len(r["note"]) > 40, r["stem"]
        if r["category"] == "WHOLE" and not _undated(r):
            y = _years(frm)[-1]
            assert y < t or (y == t and re.match(r"(1 January|January|the %d year of account)" % t, frm)), (r["stem"], frm)
        if r["category"] == "PART":
            assert frm and _years(frm) and _years(frm)[-1] == t, (r["stem"], frm)
            assert not re.match(r"(1 January|1st January|January 1)", frm), (r["stem"], frm)
        if r["category"] == "AFTER":
            assert frm and _years(frm), (r["stem"], frm)
            y = _years(frm)[-1]
            assert y > t or (y == t and re.search(r"31 December|end of|after the", frm)), (r["stem"], frm)
    assert {r["stem"] for r in _records() if r["category"] == "WHOLE" and _undated(r)} == UNDATED_WHOLE


def test_the_readings_re_read_in_the_fourth_cycle_keep_their_verdicts_and_their_reasons():
    by = {r["stem"]: r for r in _records()}
    for stem, verdict in RE_READ.items():
        assert by[stem]["category"] == verdict, stem
        assert by[stem]["note"] and "Re-read on 1 October 2026" in by[stem]["note"], stem
    # 2088/2019: the syndicate's principal activity during the year was underwriting, and the run-off follows the year
    r = by["syndicate_2088_2019"]
    assert any("principal activity during the year continued to be" in s["quote"] for s in r["other_statements"])
    # 2468/2020: a run-off that begins on 6 January is part-year by the date the filing gives
    assert "6 January 2020" in by["syndicate_2468_2020"]["runoff_from"]
    # 1884/2023 and 1884/2024: no statement that the syndicate is in run-off; it says it underwrites RITC and legacy reinsurance
    for stem in ("syndicate_1884_2023", "syndicate_1884_2024"):
        assert "underwrites Reinsurance to Close" in by[stem]["evidence"] and not RUNOFF_WORDS.search(_norm(by[stem]["evidence"])), stem


def test_a_note_quotes_only_what_the_entry_cites():
    """Each phrase a note puts in single quotes is inside a quote the entry cites."""
    for r in _records():
        cited = [_collapse(_norm(q)) for _, _, q in _citations(r)]
        for phrase in _quoted_in(r["note"] or ""):
            assert any(_collapse(_norm(phrase)) in c for c in cited), (r["stem"], phrase)
        for q in r["note_quotes"]:
            assert _collapse(q["quote"]) in _collapse(r["note"]), (r["stem"], q["quote"])


def test_the_premium_register_and_this_one_hold_the_same_words_for_the_same_records():
    """One reading of a filing, not two: the premium register's entries that are also entries here are copies, in_runoff is
    true exactly for WHOLE and PART, and the premium register's other records are the ones that are live."""
    corpus = {r["stem"]: r for r in _records()}
    nine = _nine()
    assert set(nine) - set(corpus) == NOT_IN_CORPUS
    assert len(set(nine) & set(corpus)) == 8
    for stem, n in nine.items():
        if stem in NOT_IN_CORPUS:
            assert n["in_runoff"] is False, stem
            continue
        c = corpus[stem]
        for field in COPIED:
            assert c[field] == n[field], (stem, field)
        assert n["in_runoff"] is (c["category"] in ("WHOLE", "PART")), stem


def test_the_reviewed_record_states_no_run_off_and_is_no_entry():
    data = _load()
    stems = {r["stem"] for r in data["records"]}
    reviewed = data["reviewed_not_run_off"]
    assert [r["stem"] for r in reviewed] == ["syndicate_1110_2023"]
    for r in reviewed:
        assert set(r) == {"stem", "syndicate", "year", "source_file", "source_sha256", "source_page", "source_page_printed",
                          "evidence", "other_statements", "reason"}, r["stem"]
        assert r["stem"] not in stems
        assert r["reason"].strip() and re.fullmatch(r"[0-9a-f]{64}", r["source_sha256"])
        for _, _, quote in [(r["source_page"], r["source_page_printed"], r["evidence"])] + [
                (s["page"], s["page_printed"], s["quote"]) for s in r["other_statements"]]:
            assert not RUNOFF_WORDS.search(_norm(quote)), (r["stem"], quote)
        # the syndicate's next filing is the one that dates the run-off
        assert {x["stem"]: x["category"] for x in data["records"]}["syndicate_1110_2024"] == "PART"


def _filings_present(entries):
    return [r for r in entries if (ROOT / r["source_file"]).exists()]


def test_each_quote_is_on_the_page_it_cites_in_the_file_with_that_hash():
    """Verbatim, white space aside; ' ... ' marks words left out. Needs the filings, which are not committed (the converted
    PDF stands for an HTML filing). The reviewed record's quotes are held to their pages too."""
    data = _load()
    entries = data["records"] + data["reviewed_not_run_off"]
    present = _filings_present(entries)
    if not present:
        pytest.skip("source filings not present in this checkout")
    for r in present:
        source = ROOT / r["source_file"]
        assert hashlib.sha256(source.read_bytes()).hexdigest() == r["source_sha256"], r["stem"]
        texts = fin.page_texts(source)
        cited = [(r["source_page"], r["evidence"])] + [
            (s["page"], s["quote"]) for s in r["other_statements"] + r.get("note_quotes", [])]
        for page, quote in cited:
            assert 1 <= page <= len(texts), (r["stem"], page)
            assert fin.quote_on_page(quote, texts[page - 1]), (r["stem"], page, quote)
