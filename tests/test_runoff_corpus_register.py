"""Fourth cycle of round 62 (1 October 2026): what the corpus's filings say about a syndicate's own run-off, year by year.

The author's in-sample decision (option A) excludes a syndicate-year whose own filing states that the syndicate was in
run-off for the whole year, unless the model assigns it to the assumed-business regime. The exclusion needs one thing from
the extraction: for every syndicate-year whose filing speaks of the syndicate itself running off or ceasing to underwrite,
the filing's words, the page and the file they are on, and a category. `pdf_extraction/audit/runoff_corpus_register.json`
holds that for 111 syndicate-years:

  WHOLE     in run-off, or ceased underwriting, from the start of the year or before: a run-off year
  PART      the run-off begins during the year
  AFTER     the run-off begins at or after the year end; the syndicate was underwriting during the year
  NOTCOUNT  not counted: the filing's words do not settle it, or the statement is about another entity

These tests hold the register to its own rules (a category has to agree with the date the filing gives), to the filings (each
quote is printed on the page it cites, in the file whose hash the register holds), to the premium register
(`runoff_register.json`, the nine records the premium rule reads), whose entries it copies where the two overlap, and to the
corpus itself. The first version of the register (88 entries) was checked only against its own words, and its words were run-off
words, so it could not show that Syndicate 1209's 2016 and 2017 filings, which never say run-off, were missing. The statement
forms in `scripts/runoff_statement_forms.py` say what a filing says when its syndicate has stopped or will stop, in whatever
words; every filing of the corpus that a form matches has to be an entry, or its matching sentences have to be in the register's
`scan_reviewed` list with the reason each is not the syndicate's own run-off, and every form has to be needed by a statement the
register holds. The one entry whose own words no form matches is listed below (OBLIQUE).

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
import runoff_statement_forms as forms  # noqa: E402

CORPUS = ROOT / "pdf_extraction" / "audit" / "runoff_corpus_register.json"
PREMIUM = ROOT / "pdf_extraction" / "audit" / "runoff_register.json"
CATEGORIES = ("WHOLE", "PART", "AFTER", "NOTCOUNT")
FIELDS = {"stem", "syndicate", "year", "category", "runoff_from", "source_file", "source_sha256", "source_page",
          "source_page_printed", "evidence", "other_statements", "note_quotes", "note"}
#: the fields of a scan_reviewed record: a filing a statement form matches that is not an entry, with the sentences it matches
SCAN_FIELDS = {"stem", "syndicate", "year", "source_sha256", "statements", "reason"}
#: what a scan_reviewed reason says the matching sentence is about, if it is not the syndicate's own run-off: "<kind>: <what it says>"
KINDS = ("another entity", "class or line", "office or channel", "not a stop")
#: the fields a corpus entry copies from the premium register where the two hold the same record
COPIED = ("runoff_from", "source_file", "source_sha256", "source_page", "source_page_printed", "evidence",
          "other_statements", "note_quotes", "note")
#: what the filing's words say when they say the syndicate is in run-off or has ceased to write
RUNOFF_WORDS = re.compile(r"run-?\s?off|ceased (to )?(underwrit|trad|writ)|cease (to )?(underwrit|writ)|"
                          r"no longer (underwrit|writ)|cessation", re.I)
#: the WHOLE entries without a start date. Each says in its own words that the syndicate is in run-off (3500 has been a run-off
#: vehicle since it was formed in 2003, 6124 was established in 2015 as a special legacy syndicate, 2255/2015 is the author's
#: decision); a WHOLE entry that is not dated and not in this set has to be argued for here.
UNDATED_WHOLE = {"syndicate_2008_2021", "syndicate_2008_2023", "syndicate_2255_2015", "syndicate_3330_2017", "syndicate_3330_2018",
                 "syndicate_3500_2015", "syndicate_3500_2018", "syndicate_3500_2019", "syndicate_3500_2021", "syndicate_3500_2022",
                 "syndicate_3500_2023", "syndicate_6124_2015"}
#: the seven readings re-read in the fourth cycle, with their verdicts. A different verdict is the author's decision.
RE_READ = {"syndicate_2088_2019": "AFTER", "syndicate_2468_2020": "PART", "syndicate_1884_2023": "NOTCOUNT",
           "syndicate_1884_2024": "NOTCOUNT", "syndicate_1254_2022": "NOTCOUNT", "syndicate_1254_2023": "NOTCOUNT",
           "syndicate_1975_2021": "AFTER"}
#: the four readings of deferred item 2 of the review of 2 October 2026, with their verdicts (6131/2021 discontinues the SPA from the
#: 2022 year of account; the three 2016 quota-share SPAs say that Syndicate 2003 will not continue its purchase for 2017)
DEFERRED_2 = {"syndicate_6131_2021": "AFTER", "syndicate_6112_2016": "NOTCOUNT", "syndicate_6119_2016": "NOTCOUNT",
              "syndicate_6121_2016": "NOTCOUNT"}
COUNTS = {"WHOLE": 43, "PART": 9, "AFTER": 40, "NOTCOUNT": 19}
#: the premium register's entries that are not corpus entries: a live syndicate whose negative premium is a return premium
NOT_IN_CORPUS = {"syndicate_3623_2018"}
#: the entry whose own words no statement form matches: it says the syndicate "will no longer write new follow capacity insurance
#: business at Lloyd's", and the forms cannot tell a class ("follow capacity" business) from the whole of a syndicate's book, so a
#: stop of this kind is found only where it is in other words too. A listed entry's words must still match no form, so the list
#: shrinks when a form learns to read them.
OBLIQUE = {"syndicate_4321_2023"}
#: the cited pages whose text layer shows no printed page at the head or foot (a number set in a graphic, a converted page, a scan):
#: their printed page was read from the rendered page, and two of them (2008/2019 page 6, 2088/2019 page 15) are pages on which
#: the text layer shows a different number. Every other cited page shows its printed page in its text, which the test below holds
#: the register to.
READ_FROM_THE_PAGE = {
    ("syndicate_1209_2016", 4), ("syndicate_1209_2016", 5), ("syndicate_1209_2016", 6), ("syndicate_1840_2024", 15),
    ("syndicate_1840_2024", 37), ("syndicate_1880_2024", 9), ("syndicate_1882_2016", 4), ("syndicate_1882_2016", 5),
    ("syndicate_1994_2024", 25), ("syndicate_2007_2018", 7), ("syndicate_2007_2019", 5), ("syndicate_2007_2019", 8),
    ("syndicate_2008_2016", 6), ("syndicate_2008_2018", 6), ("syndicate_2008_2019", 6), ("syndicate_2088_2019", 4),
    ("syndicate_2088_2019", 15), ("syndicate_2468_2019", 9), ("syndicate_3210_2016", 5), ("syndicate_3210_2017", 6),
    ("syndicate_3210_2018", 5), ("syndicate_557_2022", 5), ("syndicate_6124_2015", 4), ("syndicate_6130_2018", 4),
}


def _load():
    return json.loads(CORPUS.read_text(encoding="utf-8"))


def _records():
    return _load()["records"]


def _nine():
    return {r["stem"]: r for r in json.loads(PREMIUM.read_text(encoding="utf-8"))["records"]}


def _norm(text):
    """The text with the hyphen variants and ligatures a filing's text layer prints (U+2010 to U+2014, the minus sign, the soft
    hyphen, ff, fi, fl, ffi, ffl) written plainly."""
    return forms.normalise(text)


def _says_stopped(words):
    """Whether the words say that a syndicate is in run-off or has stopped, or will stop, underwriting: run-off words, or a statement form."""
    return bool(RUNOFF_WORDS.search(words)) or forms.says_stopped(words)


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
            + [(s["page"], s["page_printed"], s["quote"]) for s in r["other_statements"] + r.get("note_quotes", [])])


def _folio_candidates(text):
    """The integers a page shows at its head or its foot (its first 14 and last 10 whitespace-separated tokens) and in a
    'Page N' footer: its printed page, where the text layer carries one."""
    tokens = text.split()
    found = set()
    for chunk in (tokens[:14], tokens[-10:]):
        for token in chunk:
            token = token.strip("|.,:;()[]")
            if re.fullmatch(r"\d{1,3}", token):
                found.add(int(token))
    for m in re.finditer(r"Page\s*\|?\s*(\d{1,3})", text[:400] + " " + text[-400:], re.I):
        found.add(int(m.group(1)))
    return found


def test_the_register_is_one_reading_per_syndicate_year_with_its_category_and_its_counts():
    data = _load()
    assert set(data) == {"purpose", "recorded", "categories", "premium_register", "sources", "scope", "records", "reviewed_not_run_off",
                         "scan_reviewed"}
    assert tuple(data["categories"]) == CATEGORIES
    records = data["records"]
    stems = [r["stem"] for r in records]
    assert len(stems) == len(set(stems)) == 111
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
    year end; every reading except NOTCOUNT says in the filing's words (run-off words, or one of the statement forms of
    scripts/runoff_statement_forms.py, for a filing that never says run-off) that the syndicate is in run-off or has stopped
    underwriting; a NOTCOUNT entry says why in its note."""
    for r in _records():
        t, frm, words = r["year"], r["runoff_from"], _norm(" ".join(q for _, _, q in _citations(r)))
        if r["category"] != "NOTCOUNT":
            assert _says_stopped(words), r["stem"]
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


def test_the_deferred_readings_of_the_second_of_october_keep_their_verdicts_and_their_reasons():
    """Review of 2 October 2026, deferred item 2. 6131/2021 says in its own words that the SPA is discontinued from the 2022 year of
    account, after a year in which it wrote: AFTER. 6112, 6119 and 6121 (2016) say that Syndicate 2003, which buys the whole account
    quota share they write, will not continue that purchase for 2017: a sentence about the host's purchase decision, which no form
    reads as a stop and which the filing does not turn into a statement about the SPA, so NOTCOUNT and the note says why (the notes called
    the host "another entity" until 3 October 2026, and do not now). A different verdict is the author's decision."""
    by = {r["stem"]: r for r in _records()}
    for stem, verdict in DEFERRED_2.items():
        assert by[stem]["category"] == verdict, stem
    r = by["syndicate_6131_2021"]
    assert r["source_page"] == 7 and "discontinue the SPA for the 2022 year of account onwards" in r["evidence"]
    assert "2022 year of account" in r["runoff_from"] and forms.says_stopped(r["evidence"])
    assert any("For the 2021 Year of Account, the SPA assumes 60%" in s["quote"] for s in r["other_statements"])
    for stem in DEFERRED_2:
        if DEFERRED_2[stem] != "NOTCOUNT":
            continue
        r = by[stem]
        assert "Syndicate 2003 will not continue its whole account quota share purchase with the SPA" in r["evidence"], stem
        assert not forms.says_stopped(r["evidence"]) and r["runoff_from"] is None, stem
        assert "the host's purchase decision, which the filing does not turn into a statement about the SPA" in r["note"], stem
        assert "another entity" not in r["note"] and "so it is not AFTER" in r["note"], stem


#: 6126/2017 (review of the stage-2 commits, 3 October 2026). The filing says that the SPA has no 2018 year of account, that its property book is written
#: through a dedicated syndicate which the SPA is converting to, and that the SPA received approval to transition to a full independent syndicate status. It was
#: listed in scan_reviewed as a change of vehicle that is not a stop. It is an AFTER entry: the SPA wrote for 2017 (gross written premium 42,496 in GBP000), and
#: 2017 is its own last year of account, as the year each of 1209/2015, 2088/2019, 2007/2018 and 6133/2021 covers is its last although its business went on in
#: another syndicate. The filing gives no date. Two filings of the dedicated syndicate, Syndicate 3268, that the entry's note cites: (stem, PDF page, the words)
SYNDICATE_3268_PAGES = (
    ("syndicate_3268_2018", 5, "2018 was Agora\u2019s first year as a full syndicate having been an SPA of Skuld 1897 for the previous two years."),
    ("syndicate_3268_2019", 33, "The \u00a32.5m claims fund is to cover anticipated claims payments in relation to SPA 6126 YOA 2016 which was accepted as an RITC "
                                "into Syndicate 3268 on 1 January 2019."),
)


def test_6126_2017_is_an_after_entry_for_the_change_of_vehicle_and_no_longer_a_reviewed_statement():
    """The entry is AFTER, dated by the year of account (the filing gives no date); it says in its own words that the SPA has no 2018 year of account, holds the
    words that show the SPA wrote for 2017 and the words for the change of vehicle, and is no longer in scan_reviewed, where it stood as 'not a stop'."""
    data = _load()
    by = {r["stem"]: r for r in data["records"]}
    assert "syndicate_6126_2017" not in {r["stem"] for r in data["scan_reviewed"]}
    r = by["syndicate_6126_2017"]
    assert r["category"] == "AFTER" and r["runoff_from"].startswith("after the 2017 year of account") and "gives no date" in r["runoff_from"]
    assert (r["source_page"], r["source_page_printed"]) == (8, "5")
    assert "The SPA does not have a 2018 Year of Account" in r["evidence"] and forms.says_stopped(r["evidence"])
    others = " ".join(q["quote"] for q in r["other_statements"])
    assert "transition to a full independent syndicate status" in others, "the change of vehicle"
    assert "gross written premium of \u00a342.5m" in others and "For the 2017 Year of account the SPA assumes 85.5%" in others, "the SPA wrote for 2017"
    for words in ("Syndicate 3268", "PDF page 5", "PDF page 33", "42,496", "1209/2015, 2088/2019, 2007/2018 and 6133/2021"):
        assert words in r["note"], words


def test_the_pages_of_syndicate_3268_that_the_6126_2017_note_cites_say_so():
    """The note's two citations of Syndicate 3268's filings are held to their pages as the entries' quotes are (a note_quote can only be from the entry's own
    filing). Needs the filings."""
    sources = dict(forms.corpus_sources())
    if not all(sources[stem].exists() for stem, _, _ in SYNDICATE_3268_PAGES):
        pytest.skip("source filing not present in this checkout")
    for stem, page, words in SYNDICATE_3268_PAGES:
        texts = fin.page_texts(sources[stem])
        assert 1 <= page <= len(texts), (stem, page)
        assert fin.quote_on_page(words, texts[page - 1]), (stem, page, words)


def test_lloyds_candidate_list_has_no_2017_row_for_the_three_2016_spas_while_6111_runs_to_2018():
    """The three notes say that Lloyd's candidate list of syndicate-years (syndicate_reports/Lloyds_Syndicates_2014_2024.xlsx) has no 2017 row for 6112, 6119 or
    6121, while its rows for 6111, which the same managing agent ran, go to 2018. The file is committed, so the claim is held to it. It is not the filings' own
    words, which is why the entries stay NOTCOUNT."""
    import openpyxl
    path = ROOT / "syndicate_reports" / "Lloyds_Syndicates_2014_2024.xlsx"
    assert path.is_file(), "the candidate list is committed"
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    rows = list(wb["All Data"].iter_rows(values_only=True))
    wb.close()
    assert rows[0][:3] == ("Reporting Year", "Syndicate", "Managing Agent"), rows[0]
    listed = {(int(y), int(s)): agent for y, s, agent, *_ in rows[1:] if y is not None}
    for s in (6112, 6119, 6121):
        assert (2016, s) in listed and (2017, s) not in listed, s
    assert max(y for y, s in listed if s == 6111) == 2018
    assert len({listed[k] for k in listed if k[1] in (6111, 6112, 6119, 6121)}) == 1, "the same managing agent"
    by = {r["stem"]: r for r in _records()}
    for s in (6112, 6119, 6121):
        note = by["syndicate_%d_2016" % s]["note"]
        assert "syndicate_reports/Lloyds_Syndicates_2014_2024.xlsx" in note and "has no 2017 row for %d" % s in note, s
        assert "rows for 6111, which the same managing agent ran, go to 2018" in note and "stays NOTCOUNT" in note, s


def _readme_item_9():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    start = text.index("9. **Run-off corpus register**")
    return " ".join(text[start:text.index("\n", start)].split())


def test_a_page_of_50_characters_or_fewer_is_scanned_like_any_other_and_the_texts_say_so():
    """Review of the stage-2 commits, 3 October 2026: the scope and README item 9 said that the 333 pages that hold 50 characters or fewer are read by no form.
    scan_page has no length floor: a statement on a page that short is found. What those pages hold is, for the most part, a cover title, a running head, a page
    number, a blank-page notice or a printer's line (also a web address, and on one page a string of OCR noise); none has a sentence a form matches."""
    short = "The Syndicate is in run-off."
    assert len(short) <= 50
    assert [name for name, _, _ in forms.scan_page(short)] == ["in_run_off"], "scan_page reads a page of 50 characters or fewer"
    for where, words in (("the register's scope", _load()["scope"]), ("README item 9", _readme_item_9())):
        assert "so no form reads them" not in words, where
        assert "333 more hold 50 characters or fewer (such as a cover title, a running head, a page number, a blank-page notice or a printer's line), too little to " \
               "carry a statement: the scan reads them like any other page, and none of them has a sentence a form matches" in words, where


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
            assert not _says_stopped(_norm(quote)), (r["stem"], quote)
        # the syndicate's next filing is the one that dates the run-off
        assert {x["stem"]: x["category"] for x in data["records"]}["syndicate_1110_2024"] == "PART"


def _statements():
    """(stem, quote) for every quote the register holds: the entries' and the scan_reviewed statements'."""
    data = _load()
    out = [(r["stem"], q) for r in data["records"] for _, _, q in _citations(r)]
    return out + [(r["stem"], s["quote"]) for r in data["scan_reviewed"] for s in r["statements"]]


def _sentence_forms(quote):
    """[(sentence, [the forms that match it])] for the sentences of the quote that some form matches."""
    out = []
    for s in forms.sentences(forms.flat(quote)):
        names = [n for n in forms.FORMS if forms.match(n, s)]
        if names:
            out.append((s, names))
    return out


def test_the_scan_reviewed_list_is_well_formed_and_holds_only_statements_a_form_matches():
    """scan_reviewed: the filings a statement form matches that are not entries, with the sentences matched and why each is not
    the syndicate's own run-off. A statement no form matches would be dead weight."""
    data = _load()
    entries = {r["stem"] for r in data["records"]} | {r["stem"] for r in data["reviewed_not_run_off"]}
    reviewed = data["scan_reviewed"]
    stems = [r["stem"] for r in reviewed]
    assert stems == [s for _, s in sorted(((r["syndicate"], r["year"]), r["stem"]) for r in reviewed)], "sorted by syndicate and year"
    assert len(stems) == len(set(stems)) == 66, "66 filings"
    assert sum(len(r["statements"]) for r in reviewed) == 84, "the 66 filings hold 84 statements"
    assert len(forms.corpus_sources()) == 1065, "the corpus the scan covers is the 1,065 committed extraction records"
    for r in reviewed:
        assert set(r) == SCAN_FIELDS, r["stem"]
        assert r["stem"] == "syndicate_%d_%d" % (r["syndicate"], r["year"]), r["stem"]
        assert r["stem"] not in entries, r["stem"]
        assert (ROOT / "pdf_extraction" / (r["stem"] + ".json")).exists(), r["stem"]
        assert re.fullmatch(r"[0-9a-f]{64}", r["source_sha256"]), r["stem"]
        kind, _, why = r["reason"].partition(": ")
        assert kind in KINDS and len(why.strip()) >= 20, (r["stem"], r["reason"])
        assert r["statements"], r["stem"]
        pages = [s["page"] for s in r["statements"]]
        assert pages == sorted(pages), r["stem"]
        for s in r["statements"]:
            assert set(s) == {"page", "quote"} and isinstance(s["page"], int) and s["page"] >= 1, r["stem"]
            assert s["quote"].strip() and forms.says_stopped(s["quote"]), (r["stem"], s["quote"])


def test_the_forms_match_every_entrys_own_words_except_the_oblique_ones():
    """The forms are held to the register in one direction here: the words of every entry that says the syndicate is in run-off
    or has stopped are matched by a form, except an OBLIQUE entry's, which must still be matched by none."""
    for r in _records():
        if r["category"] == "NOTCOUNT":
            continue
        matched = [q for _, _, q in _citations(r) if forms.says_stopped(q)]
        if r["stem"] in OBLIQUE:
            assert not matched, ("a form matches this entry's words now: take it off OBLIQUE", r["stem"])
        else:
            assert matched, ("no statement form matches any of this entry's words", r["stem"])
    assert OBLIQUE <= {r["stem"] for r in _records()}


#: for each form, a record whose own words need it: one of that record's sentences is matched by that form and by no other, so
#: dropping the form leaves the record's sentence unread. no_longer_writing's is a scan_reviewed record: no entry needs it alone
WITNESSES = {
    "in_run_off": "syndicate_2526_2017",
    "put_into_run_off": "syndicate_308_2017",
    "run_off_of_its_business": "syndicate_780_2019",
    "ceased_to_write": "syndicate_260_2014",
    "no_longer_writing": "syndicate_1969_2021",
    "last_year_of_participation": "syndicate_1209_2016",
    "no_active_underwriter": "syndicate_1209_2016",
    "business_written_in_another_syndicate": "syndicate_1209_2015",
    "no_business_in_a_year": "syndicate_1882_2017",
}


def test_each_form_is_needed_by_the_record_it_was_written_for():
    data = _load()
    by = {r["stem"]: r for r in data["records"]}
    reviewed = {r["stem"]: r for r in data["scan_reviewed"]}
    for form, stem in WITNESSES.items():
        quotes = [q for _, _, q in _citations(by[stem])] if stem in by else [s["quote"] for s in reviewed[stem]["statements"]]
        alone = [s for q in quotes for s, names in _sentence_forms(q) if names == [form]]
        assert alone, "no sentence of %s is matched by the form %s and by that form alone" % (stem, form)
    assert set(WITNESSES) == set(forms.FORMS), sorted(set(forms.FORMS) ^ set(WITNESSES))


#: sentences and the forms that match them: what each form is for, and what it leaves alone (a line, a class, another year of
#: account, hypothetical wording, a going concern paragraph)
FORM_CASES = [
    ("The Syndicate is now in run-off.", ["in_run_off"]),
    ("The Hull line is now in run-off.", []),
    ("The Managing Agent has put the Syndicate into run-off with agreement of the Lloyd's Capacity Transfer Panel.", ["put_into_run_off"]),
    ("A set of run-off accounts has been prepared for the 2012 year of account which was placed in to run-off at 31 December 2014.", []),
    ("The principal activity of Syndicate 3500 is the run-off of its existing liabilities.", ["run_off_of_its_business"]),
    ("Syndicate 260 ceased underwriting business with effect from 31 December 2014", ["ceased_to_write"]),
    ("The Syndicate has ceased underwriting.", ["ceased_to_write"]),
    ("The Syndicate ceased underwriting Aviation business.", []),
    ("In 2016 the Syndicate ceased underwriting Aviation business.", []),
    ("The directors do not intend to cease underwriting or to cease its operations.", []),
    ("Unless the Syndicate ceases to underwrite, the going concern basis is used.", []),
    ("The Syndicate will no longer underwrite property treaty and marine hull.", []),
    ("From 31 December 2016 the Syndicate is no longer underwriting new business and is now in run-off.", ["in_run_off", "no_longer_writing"]),
    ("The Syndicate's last year of account participation is 2015.", ["last_year_of_participation"]),
    ("In 2016, there is no active underwriter.", ["no_active_underwriter"]),
    ("All new and renewed business of the Syndicate will be written in Syndicate 2003.", ["business_written_in_another_syndicate"]),
    ("The syndicate did not underwrite in 2017.", ["no_business_in_a_year"]),
    ("The Syndicate will not be writing new business for the 2022 year of account.", ["no_business_in_a_year"]),
    ("The Syndicate is not writing new business for 2022.", ["no_business_in_a_year"]),
    ("All new and renewing business will be transacted through Syndicate 2003.", ["business_written_in_another_syndicate"]),
    ("We will not underwrite business if we do not believe pricing is at a level that will meet our targeted returns.", []),
    ("Chubb will not underwrite risks related to the construction and operation of new coal-fired plants.", []),
    # FOLLOWUP5 item 1 (review of 2 October 2026, deferred 1): each widening reads a sentence and leaves its neighbour alone
    ("The Syndicate no longer writes new business.", ["no_longer_writing"]),
    ("The Syndicate no longer writes marine hull business.", []),
    ("The Syndicate stopped underwriting at the end of 2019.", ["ceased_to_write"]),
    ("The Syndicate stopped underwriting cargo business.", []),
    ("The Syndicate discontinued writing new business with effect from 1 January 2020.", ["ceased_to_write"]),
    ("The Syndicate discontinued writing its Australian property book.", []),
    ("The Syndicate withdrew from underwriting at 31 December 2018.", ["ceased_to_write"]),
    ("The Syndicate withdrew from underwriting in the Japanese market.", []),
    ("The Syndicate was closed to new business from 1 January 2021.", ["ceased_to_write"]),
    ("The marine account was closed to new business.", []),
    ("The Syndicate ceased all underwriting activities on 31 December 2019.", ["ceased_to_write"]),
    ("The Syndicate ceased all underwriting activities in Dubai.", []),
    ("The Syndicate is dormant.", ["in_run_off"]),
    ("The Syndicate's dormant claims were reviewed in the year.", []),
    ("The Syndicate is winding down its remaining liabilities.", ["in_run_off"]),
    ("The Syndicate is winding down its aviation account.", []),
    ("The Syndicate is being run off.", ["in_run_off"]),
    ("The aviation account is being run off.", []),
    ("Syndicate 1234 is a run-off vehicle.", ["run_off_of_its_business"]),
    ("The group established a run-off vehicle for its legacy books.", []),
    ("Syndicate 1234 merged into Syndicate 5678 on 1 January 2018.", ["business_written_in_another_syndicate"]),
    ("The two managing agents merged into one company.", []),
    ("The Syndicate's last underwriting year was 2018.", ["last_year_of_participation"]),
    ("The last underwriting year was a difficult one for the market.", []),
    ("2019 is the Syndicate's final year of account.", ["last_year_of_participation"]),
    ("The final year of account result was a profit.", []),
    ("The Syndicate has not written any new business since 2017.", ["no_business_in_a_year"]),
    ("The Syndicate has not written any cyber business since 2017.", []),
    ("The Syndicate did not write any new business during the year.", ["no_business_in_a_year"]),
    ("The Syndicate did not write any new marine business during the year.", []),
    ("The Syndicate does not have a 2020 underwriting year of account.", ["no_business_in_a_year"]),
    ("The Syndicate does not have a material exposure to the 2020 underwriting year of account.", []),
    # ... and the over-match on places, offices and classes is gone, while a month or a year still bounds a stop
    ("The Syndicate ceased underwriting new business in Dubai.", []),
    ("During the year it was decided to cease underwriting from the service company office in Singapore.", []),
    ("The Syndicate has taken action to cease underwriting in non-performing classes.", []),
    ("Coverholder operations in Sydney ceased to underwrite on behalf of the syndicate.", []),
    ("The Syndicate ceased underwriting new business in December 2016.", ["ceased_to_write"]),
    ("The Syndicate ceased underwriting new business in 2016.", ["ceased_to_write"]),
    # review of the stage-2 branch: the new wordings with the Syndicate as subject, about a class, a coverholder, an account,
    # a subsidiary or a place, are left alone (F1); Lloyd's and the Lloyd's market end a stop (F2)
    ("The Syndicate's marine hull class was closed to new business in 2015.", []),
    ("The Syndicate's Treaty account is closed to new business.", []),
    ("The Syndicate's coverholder in Dubai is dormant.", []),
    ("The Syndicate owns XYZ Services Ltd, which is dormant.", []),
    ("The Syndicate's managing agent is dormant.", []),
    ("The Syndicate is winding down its operations in Canada.", []),
    ("The Syndicate no longer accepts business from coverholder X.", []),
    ("The Syndicate's last underwriting year was 2018 for the marine line.", []),
    ("The Syndicate does not have a 2020 underwriting year of account for its Treaty line.", []),
    ("The Syndicate's aviation account is being run off.", []),
    ("The Syndicate's marine account merged into Syndicate 5678.", []),
    ("The Syndicate has not written any new business since 2017 through its Bermuda platform.", []),
    ("The Syndicate, managed by Ark Syndicate Management Limited, is dormant.", ["in_run_off"]),
    ("Syndicate 1234 ceased underwriting in Lloyd's with effect from 31 December 2017.", ["ceased_to_write"]),
    ("The Syndicate decided to cease underwriting in Lloyd's.", ["ceased_to_write"]),
    ("The Syndicate ceased underwriting in the Lloyd's market at the end of 2015.", ["ceased_to_write"]),
    # review of 2 October 2026, deferred item 2: a filing that discontinues the syndicate or its SPA itself, by year of account or from
    # a date, is read; the same words about an account, a class, a coverholder or a hypothetical are left alone
    ("The decision has been made to discontinue the SPA for the 2022 year of account onwards.", ["ceased_to_write"]),
    ("The Managing Agent decided to discontinue Syndicate 1234 with effect from 1 January 2020.", ["ceased_to_write"]),
    ("The SPA was discontinued for the 2020 year of account.", ["ceased_to_write"]),
    ("The decision has been made to discontinue the SPA's Treaty account for the 2022 year of account.", []),
    ("The decision has been made to discontinue the SPA for the Marine class.", []),
    ("The Managing Agent may discontinue the SPA for the 2022 year of account if capacity is not renewed.", []),
    ("The Managing Agent has decided to discontinue its coverholder in Dubai from 2020.", []),
    ("The Syndicate's Treaty account was discontinued for the 2020 year of account.", []),
    ("The decision has been made to discontinue the SPA for the 2022 year of account in the Singapore office.", []),
    ("The Managing Agent has decided to discontinue the SPA for reporting purposes.", []),
]


def test_the_forms_read_the_sentences_they_were_written_for_and_leave_the_others():
    for sentence, expected in FORM_CASES:
        got = [n for n in forms.FORMS if forms.match(n, sentence)]
        assert got == expected, (sentence, got, expected)


def test_a_hit_is_covered_only_by_a_statement_that_holds_its_words_on_the_same_page():
    """forms.unaccounted: a filing that is an entry or reviewed apart needs nothing; otherwise every hit needs a scan_reviewed
    statement on its own page that holds the hit's matching words."""
    hit = {"page": 5, "form": "ceased_to_write", "sentence": "Syndicate 9 ceased to trade on 31 December 2016.", "span": "ceased to trade"}
    holds = {"page": 5, "quote": "of 2016. Syndicate 9 ceased to trade on 31 December 2016. The next"}
    assert forms.covered(hit, [holds])
    assert not forms.covered(hit, [dict(holds, page=6)]), "a statement on another page does not hold the hit"
    assert not forms.covered(hit, [dict(holds, quote="of 2016. Syndicate 9 ceased writing on 31 December 2016.")]), "other words"
    register = {"records": [{"stem": "syndicate_1_2015"}], "reviewed_not_run_off": [{"stem": "syndicate_2_2015"}],
                "scan_reviewed": [{"stem": "syndicate_3_2015", "statements": [holds]}]}
    hits = {s: [hit] for s in ("syndicate_1_2015", "syndicate_2_2015", "syndicate_3_2015", "syndicate_4_2015")}
    assert [h["stem"] for h in forms.unaccounted(register, hits)] == ["syndicate_4_2015"]
    hits["syndicate_3_2015"] = [hit, dict(hit, page=7)]
    assert [(h["stem"], h["page"]) for h in forms.unaccounted(register, hits)] == [("syndicate_3_2015", 7), ("syndicate_4_2015", 5)]


def test_the_scan_trigger_lets_through_every_statement_the_register_holds():
    """The scan tries the forms only on sentences that hold a TRIGGER word, to read 1,065 filings in minutes: no statement the
    register holds, and no FORM_CASES sentence, that a form matches may be one the trigger would have skipped."""
    for stem, quote in _statements() + [(sentence, sentence) for sentence, expected in FORM_CASES if expected]:
        for sentence, _ in _sentence_forms(quote):
            assert forms.TRIGGER.search(sentence), (stem, sentence)


def test_the_scope_the_register_states_names_the_forms_and_the_oblique_entries():
    scope = _load()["scope"]
    assert "scripts/runoff_statement_forms.py" in scope and "scan_reviewed" in scope
    assert "oblique wording" in scope
    for stem in OBLIQUE:
        assert stem.replace("syndicate_", "").replace("_", "/") in scope, stem


def test_the_register_and_the_readme_claim_the_words_and_the_pages_the_forms_read():
    """FOLLOWUP5 item 3 (review of 2 October 2026, deferred 3): the register's purpose and README item 9 said an entry is kept
    for a filing that says so "in whatever words it uses", and the scope said the forms read every filing. The claim reaches
    the words the statement forms read and those the readers found, on every readable page: a page with no text layer and no
    text in the committed OCR page cache is not read."""
    data = _load()
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    start = text.index("9. **Run-off corpus register**")
    item = " ".join(text[start:text.index("\n", start)].split())
    for where, words in (("the register's purpose", data["purpose"]), ("README item 9", item)):
        assert "whatever words" not in words, where
        assert "in the words the statement forms read, and those the readers found" in words, where
    for where, words in (("the register's scope", data["scope"]), ("README item 9", item)):
        # what is scanned, and what the entries are complete over
        assert "every readable page of every filing of the corpus" in words.lower(), where
        assert "complete over every readable page of the corpus" in words, where
        assert "complete over every filing of the corpus" not in words, where


def test_the_readme_states_the_counts_the_register_holds():
    """README item 9 gives the register's counts: the entries, each category and the scan_reviewed filings are the file's own."""
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    start = text.index("9. **Run-off corpus register**")
    item = text[start:text.index("\n", start)]
    data = _load()
    assert "for each of the %d syndicate-years" % len(data["records"]) in item
    for cat in CATEGORIES:
        m = re.search(r"%s \([^()]*; (\d+)\)" % cat, item)
        assert m and int(m.group(1)) == sum(r["category"] == cat for r in data["records"]), cat
    m = re.search(r"`scan_reviewed` list \((\d+) filings, which hold (\d+) statements", item)
    assert m and int(m.group(1)) == len(data["scan_reviewed"]), "the README counts filings here"
    assert int(m.group(2)) == sum(len(r["statements"]) for r in data["scan_reviewed"]), "and then the statements they hold"


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


def test_each_printed_page_is_the_folio_its_page_shows():
    """A printed page the register states is the number the page itself prints, wherever the text layer carries it (all but
    the 24 pages in READ_FROM_THE_PAGE, which were read from the rendered page). Needs the filings."""
    data = _load()
    entries = data["records"] + data["reviewed_not_run_off"]
    present = _filings_present(entries)
    if not present:
        pytest.skip("source filings not present in this checkout")
    checked = 0
    for r in present:
        texts = fin.page_texts(ROOT / r["source_file"])
        for page, printed, _ in _citations(r):
            if (r["stem"], page) in READ_FROM_THE_PAGE:
                continue
            assert int(printed) in _folio_candidates(texts[page - 1]), (r["stem"], page, printed)
            checked += 1
    assert checked >= 100, checked


def test_each_scan_reviewed_quote_is_on_its_page_in_the_file_with_that_hash():
    """The scan_reviewed statements are held to their pages as the entries' quotes are. Needs the filings."""
    sources = dict(forms.corpus_sources())
    reviewed = _load()["scan_reviewed"]
    if not all(sources[r["stem"]].exists() for r in reviewed):
        pytest.skip("source filings not present in this checkout")
    for r in reviewed:
        source = sources[r["stem"]]
        assert hashlib.sha256(source.read_bytes()).hexdigest() == r["source_sha256"], r["stem"]
        texts = fin.page_texts(source)
        for s in r["statements"]:
            assert 1 <= s["page"] <= len(texts), (r["stem"], s["page"])
            assert fin.quote_on_page(s["quote"], texts[s["page"] - 1]), (r["stem"], s["page"], s["quote"])


@pytest.fixture(scope="module")
def corpus_scan():
    """{"hits": {stem: [hit, ...]}, "textless": [stem, ...]} for every filing of the corpus, read as the audit reads them (the
    source filings of the 1,065 committed extraction records: the converted PDF for an HTML filing, the committed OCR page cache
    for a page without a text layer). A filing is read once; the hits and the filings that yield no text both come from it."""
    sources = forms.corpus_sources()
    if not all(path.exists() for _, path in sources):
        pytest.skip("source filings not present in this checkout")
    return forms.read_corpus(sources, fin.page_texts)


@pytest.fixture(scope="module")
def corpus_hits(corpus_scan):
    return corpus_scan["hits"]


def test_every_filing_yields_text_or_is_declared_unreadable(corpus_scan):
    """A filing that yields no text passes every form vacuously: 3210/2018's damaged file did, while the README said every
    filing was scanned (review of 2 October 2026, E-6). The filings with no text are exactly the declared ones: a new one fails
    here, and so does a declared one that yields text (after a fresh download), so the list and the README stay true."""
    assert sorted(corpus_scan["textless"]) == sorted(forms.UNREADABLE), (
        "filings with no text: %s; declared in runoff_statement_forms.UNREADABLE: %s"
        % (sorted(corpus_scan["textless"]), sorted(forms.UNREADABLE)))


def test_a_filing_with_no_text_is_found_whatever_way_it_is_damaged(tmp_path):
    """The control for the test above, on generated files read the way the corpus fixture reads the corpus
    (runoff_statement_forms.read_corpus with the audit's own page reader): a whole filing yields text and its run-off
    sentence; a truncated one opens with a page that holds none; a page with nothing printed holds none either."""
    fitz = pytest.importorskip("fitz", reason="PyMuPDF builds the fixture PDFs")
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "The Syndicate ceased to write new business at 31 December 2016.")
    whole = doc.tobytes()
    doc.close()
    blank = fitz.open()
    blank.new_page()
    files = {"syndicate_9901_2099": whole, "syndicate_9902_2099": whole[: len(whole) // 2], "syndicate_9903_2099": blank.tobytes()}
    blank.close()
    sources = []
    for stem, data in files.items():
        path = tmp_path / (stem + ".pdf")
        path.write_bytes(data)
        sources.append((stem, path))
    read = forms.read_corpus(sources, fin.page_texts)
    assert read["textless"] == ["syndicate_9902_2099", "syndicate_9903_2099"], read["textless"]
    assert list(read["hits"]) == ["syndicate_9901_2099"], "the whole filing's run-off sentence is not found"
    assert forms.without_text({"syndicate_9904_2099": []}) == ["syndicate_9904_2099"], "a file that opens with no page"
    # the corpus test's comparison, on these files: undeclared filings with no text are reported
    assert sorted(read["textless"]) != sorted(forms.UNREADABLE)


#: the OCR page cache that 3210/2018's page text comes from: its file is a scan with no text layer
OCR_CACHE_3210_2018 = "pdf_extraction/ocr_page_cache/syndicate_3210_2018.json"


def test_the_readme_and_the_register_name_every_unreadable_filing():
    """README item 9 and the register's scope say the forms read every filing that yields text. With a filing declared
    unreadable, both name it. With none declared, as since 2 October 2026, both say that every filing yields text and name no
    filing as one that does not, and both say how the one filing that was fetched again that day is read: 3210/2018's earlier
    copy was a cut-short download that opened with no page, and Lloyd's file is a scan whose page text is a committed OCR page
    cache, which has to be there. Before 2 October 2026 both said every filing of the corpus was scanned, and 3210/2018 had been
    read as nothing."""
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    start = text.index("9. **Run-off corpus register**")
    item = text[start:text.index("\n", start)]
    scope = _load()["scope"]
    labels = [stem.replace("syndicate_", "").replace("_", "/") for stem in forms.UNREADABLE]
    for where, words in (("README item 9", item), ("the register's scope", scope)):
        assert "complete over the whole corpus" not in words, (where, "claims the whole corpus")
        assert "yields text" in words, (where, "does not limit the claim to the filings that yield text")
        for label in labels:
            assert label in words, (where, "does not name the unreadable filing", label)
        if not labels:
            assert "every filing yields text" in words, (where, "does not say that every filing yields text")
            assert "yields none" not in words, (where, "still says that a filing yields no text")
            assert "3210/2018 was fetched again on 2 October 2026" in words, (where, "does not say 3210/2018 was fetched again")
            assert "cut-short download" in words, (where, "does not say why")
            assert OCR_CACHE_3210_2018 in words, (where, "does not name the OCR page cache the filing's text comes from")
    if not labels:
        assert (ROOT / OCR_CACHE_3210_2018).is_file(), "the OCR page cache that item 9 and the scope name is not committed"


def test_the_counts_this_file_states_in_its_own_text_are_the_registers_and_the_lists():
    """The module docstring says how many syndicate-years the register holds, and the folio test's docstring how many cited pages
    were read from the rendered page: each is the file's own count, so neither drifts when an entry is added."""
    assert "holds that for %d syndicate-years" % len(_records()) in " ".join(__doc__.split())
    folio = " ".join(test_each_printed_page_is_the_folio_its_page_shows.__doc__.split())
    assert "all but the %d pages in READ_FROM_THE_PAGE" % len(READ_FROM_THE_PAGE) in folio


def test_every_filing_a_form_matches_is_an_entry_or_has_its_matching_sentences_reviewed(corpus_hits):
    """The register's completeness, checked against the corpus and not against the list that built it: a filing that a statement
    form matches is an entry (or the record reviewed apart), or every sentence the forms match in it is in scan_reviewed on
    its page, with the reason it is not the syndicate's own run-off. Needs the filings; takes about three minutes."""
    todo = forms.unaccounted(_load(), corpus_hits)
    filings = sorted({h["stem"] for h in todo}, key=lambda s: tuple(int(x) for x in s.replace("syndicate_", "").split("_")))
    shown = ["%s p%d [%s] %s" % (h["stem"], h["page"], h["form"], h["sentence"][:140]) for h in todo[:12]]
    assert not todo, ("%d matching sentences in %d filings are in no entry and are not reviewed: %s. Read each: if it is the "
                      "syndicate's own run-off, add an entry; otherwise add it to scan_reviewed with its reason. `python "
                      "scripts/runoff_statement_forms.py` lists them all. The first: %s" % (len(todo), len(filings), filings, shown))
    assert len(corpus_hits) >= 150, "the scan found almost nothing: %d filings" % len(corpus_hits)


def test_no_scan_reviewed_statement_is_stale(corpus_hits):
    """Every scan_reviewed statement still holds a sentence a form matches in that filing, on that page: the list and the forms
    stay in step (a form dropped or narrowed leaves its statements unread, and this fails naming the filing)."""
    for r in _load()["scan_reviewed"]:
        mine = corpus_hits.get(r["stem"], [])
        for s in r["statements"]:
            assert any(h["page"] == s["page"] and h["span"] in forms.flat(s["quote"]) for h in mine), (
                r["stem"], s["page"], s["quote"][:90])
