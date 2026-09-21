r"""The transfer scanner's rules, held down by tests rather than by a rescan.

PLAN.md states a closing check for each of R169, R170, R174, R175, R180 and R181, and until
now every one of them was prose: the evidence was "the corpus rescan reports 11 flags",
which is agreement with the data the rules were written against. That is why two of those
rules shipped with defects the corpus happened not to exercise -- R175's strong-evidence
gate withdrew a plain novation, and `_install()` left the shared scanner mutated for the
rest of the process.

The sentences here are constructed, not drawn from the corpus, precisely so that they test
the rule rather than the sample. Where a real filing is quoted it is named.
"""
import json
import os
import re
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, ROOT)

import ritc_scanner as rs                      # noqa: E402
import portfolio_transfer_scanner as pt        # noqa: E402

#: The shared scanner's attributes `_install()` is allowed to touch.
SHARED = ("RITC_TERM", "SENTENCE_PATTERNS", "TERMLESS_PATTERNS", "INWARD_SETTLED",
          "OUTWARD_SETTLED", "INWARD_CUES", "OUTWARD_CUES")


def _snapshot():
    # `hasattr`: an older scanner without TERMLESS_PATTERNS still runs this file, so that
    # the M02 tests below fail on their assertions there rather than in this fixture
    return {n: (list(getattr(rs, n)) if isinstance(getattr(rs, n), list)
                else getattr(rs, n)) for n in SHARED if hasattr(rs, n)}


@pytest.fixture(autouse=True)
def _leave_the_shared_scanner_as_we_found_it():
    """Every test here restores `ritc_scanner`, whatever it does in between.

    `tests/test_ritc_scanner.py` imports the same module object, so a test that leaves the
    transfer vocabulary installed would change what that file asserts, in test order and
    without an error (R181)."""
    before = _snapshot()
    yield
    for name, value in before.items():
        setattr(rs, name, value)
    pt._PRISTINE.clear()


class TestR169_TheDirectionVocabularyFollowsTheTerm:
    """`classify_sentence` reads INWARD_SETTLED and its siblings, which `ritc_scanner`
    builds at import by concatenating the RITC literal into each pattern. Repointing
    RITC_TERM alone left 20 of 51 direction patterns unable to match a novation."""

    def test_no_direction_pattern_still_carries_the_ritc_literal(self):
        original = rs.RITC_TERM
        pt._install()
        left = [p for n in ("INWARD_SETTLED", "OUTWARD_SETTLED", "INWARD_CUES",
                            "OUTWARD_CUES")
                for p in getattr(rs, n) if original in p]
        assert left == [], left

    def test_the_patterns_that_carried_it_now_carry_the_transfer_term(self):
        original = rs.RITC_TERM
        counts = {n: sum(1 for p in getattr(rs, n) if original in p)
                  for n in ("INWARD_SETTLED", "OUTWARD_SETTLED", "INWARD_CUES",
                            "OUTWARD_CUES")}
        # measured on this corpus; R202 added the acceptance from an unnamed syndicate
        assert sum(counts.values()) == 21, counts
        pt._install()
        after = {n: sum(1 for p in getattr(rs, n) if pt.TRANSFER_TERM in p)
                 for n in counts}
        assert after == counts, (counts, after)

    def test_a_generic_pattern_is_left_alone(self):
        """Only the patterns that embedded the term are rebuilt; the rest must not move."""
        before = [p for p in rs.INWARD_CUES if rs.RITC_TERM not in p]
        pt._install()
        after = [p for p in rs.INWARD_CUES if pt.TRANSFER_TERM not in p]
        assert before == after

    def test_a_second_install_changes_nothing(self):
        pt._install()
        once = _snapshot()
        pt._install()
        assert _snapshot() == once


class TestR181_TheSharedScannerIsPutBack:
    """The mutation is scoped, because another test module imports the same object."""

    def test_restore_returns_every_attribute(self):
        before = _snapshot()
        pt._install()
        assert _snapshot() != before, "the install changed nothing, so this proves nothing"
        pt._restore()
        assert _snapshot() == before

    def test_restore_covers_the_patterns_assigned_outright(self):
        """SENTENCE_PATTERNS is a list of tuples, so the rebuild loop skips it while the
        install overwrites it anyway. It was the one attribute restore missed."""
        before = list(rs.SENTENCE_PATTERNS)
        pt._install()
        assert rs.SENTENCE_PATTERNS is pt.SENTENCE_PATTERNS
        pt._restore()
        assert rs.SENTENCE_PATTERNS == before

    def test_pristine_is_emptied_so_a_later_install_recaptures(self):
        pt._install()
        pt._restore()
        assert pt._PRISTINE == {}


class TestR174_ANamedClassOfBusinessIsNotABook:
    """"ibott General Liability class" is a line of business. The liability word in it is
    part of a name, not a stock of obligations (found in syndicate 1971's filings)."""

    def test_a_quota_share_of_a_named_class_is_not_a_transfer(self):
        assert pt._is_a_book_transfer(
            "The syndicate will write a 90% quota share reinsurance of the ibott Rover "
            "class and ibott General Liability class written by Syndicate 1969.") is False

    def test_an_employers_liability_account_is_a_class_too(self):
        assert pt._is_a_book_transfer(
            "The syndicate writes a quota share of the Employers Liability account.") is False

    def test_a_real_book_of_liabilities_still_passes(self):
        assert pt._is_a_book_transfer(
            "The syndicate accepted a loss portfolio transfer of the 2015 and prior "
            "liabilities of Syndicate 1234.") is True

    def test_a_quota_share_over_a_book_of_provisions_still_passes(self):
        assert pt._is_a_book_transfer(
            "A quota share reinsurance of the technical provisions of the 2016 and prior "
            "years of account was assumed.") is True


class TestR175_R180_WhatCountsAsEvidence:
    """A flag needs the term tied to something. `counterparty` and `amount` say only that
    a transfer word stands near a syndicate number or a sum of money."""

    def _classes(self, sentence, own="9999", other="1234"):
        return sorted({c for c, p in pt.SENTENCE_PATTERNS
                       if re.search(p.replace("OWN", own).replace("OTHER", other),
                                    sentence, re.I)})

    def _would_flag(self, sentence):
        """The rule `scan_all` applies, read off the same two tests it uses."""
        if not pt._is_a_book_transfer(sentence):
            return False
        classes = self._classes(sentence)
        return (bool({"prior_scope", "acceptance"} & set(classes))
                or bool(pt.SELF_RE.search(sentence)))

    BOILERPLATE = ("Apollo's Syndicate 1971 is poised for top and bottom-line growth, as "
                   "an innovation leader in the sharing economy space; The loss of $1.2m "
                   "in 2019 reflects the slower earnings recognition of written premiums "
                   "in the calendar year relative to net operating expenses incurred; The "
                   "2019 portfolio is split across several subclasses with a quota share.")

    def test_a_bullet_list_of_strategy_prose_is_not_a_transfer(self):
        """1971/2019 and 1971/2020, the two records this round withdrew.

        Two separate things made this fire. The shared scanner splits sentences on full
        stops and a bullet list has none, so the whole block became one sentence in which
        any term matched any syndicate number and any amount (R175). And the term that
        matched was "novation" inside "innovation" (R185). Either alone is enough to flag
        it; the test asserts the outcome, and the two tests below isolate the causes."""
        assert self._would_flag(self.BOILERPLATE) is False

    def test_innovation_is_not_a_novation(self):
        """R185. Without a word boundary the term matches inside ordinary English."""
        for ordinary in ("as an innovation leader in the sharing economy space",
                         "the renovation of the underwriting room was completed"):
            assert pt.SELF_RE.search(ordinary) is None, ordinary
            assert pt.TERM_RE.search(ordinary) is None, ordinary

    def test_the_boundary_does_not_cost_the_plural(self):
        """R186. The trailing boundary blocked "quota shares", and 1971/2023 -- "accepted
        80% and 90% quota shares of the run-off of the 2019 and 2020 years of account" --
        stopped being detected. The unbounded form had matched the plural by accident; the
        bounded form has to match it on purpose."""
        for plural in ("accepted 80% and 90% quota shares of the run-off of the 2019 and "
                       "2020 years of account",
                       "the novations of the 2016 and prior book",
                       "two commutations of prior-year liabilities",
                       "two LPTs were completed in the year"):
            assert pt.TERM_RE.search(plural) is not None, plural

    def test_a_real_novation_still_matches(self):
        """The control: the boundary must not cost the word itself."""
        for real in ("the liabilities were novated to Syndicate 1234",
                     "a novation of the 2015 and prior book",
                     "the treaty was commuted in 2019"):
            assert pt.SELF_RE.search(real) is not None, real

    def test_weak_classes_alone_do_not_flag(self):
        """R175. A sentence built to produce a counterparty and an amount and nothing
        else -- the rule is exercised whatever the real filing happens to say."""
        s = ("The syndicate placed a quota share with Syndicate 1234 for GBP12.5m during "
             "the year.")
        classes = self._classes(s)
        assert classes, "this sentence was supposed to produce weak classes"
        assert not ({"prior_scope", "acceptance"} & set(classes)), classes
        assert self._would_flag(s) is False

    def test_a_plain_novation_with_only_a_counterparty_still_flags(self):
        """R180. `_is_a_book_transfer` accepts a self-qualifying term on its own, so the
        evidence gate has to as well, or the ordinary way a filing reports a novation is
        withdrawn for carrying no second phrase."""
        s = ("Syndicate 9999 novated its book to Syndicate 1234 for GBP45.2m with effect "
             "from 1 January 2020.")
        assert self._classes(s) == ["counterparty"], self._classes(s)
        assert self._would_flag(s) is True

    def test_a_plain_loss_portfolio_transfer_still_flags(self):
        s = ("The syndicate entered into a loss portfolio transfer with Syndicate 1234 "
             "for GBP45.2m.")
        assert self._would_flag(s) is True

    def test_a_commutation_of_prior_liabilities_flags(self):
        assert self._would_flag(
            "The 2016 and prior liabilities were commuted with Syndicate 1234.") is True

    def test_a_current_year_quota_share_with_a_counterparty_does_not_flag(self):
        """The case the rule exists for: quota share is ordinary current-business
        language, so a counterparty beside it is not evidence of a prior-year transfer."""
        s = "The syndicate purchased a 30% quota share from Syndicate 1234."
        assert "prior_scope" not in self._classes(s)
        assert self._would_flag(s) is False


class TestR170_TheDroppedCountIsWhatWasDropped:
    """The field read a key nothing sets, so `or 0` reported nothing dropped on all 199
    records where the filter removed something."""

    def test_the_field_is_not_hardwired_to_zero(self):
        import io
        import json
        p = os.path.join(ROOT, "pdf_extraction", "portfolio_transfer_scan.json")
        if not os.path.exists(p):
            pytest.skip("the scan output is not in this clone")
        d = json.load(io.open(p, encoding="utf-8"))
        seen = [v.get("n_events_dropped_as_current_year") for v in d.values()
                if v.get("n_events_dropped_as_current_year") is not None]
        assert seen, "no record records a drop count at all"
        assert any(x > 0 for x in seen), \
            "every drop count is zero, which is what the defect looked like"


class TestTheAdjudicationRegisterMatchesTheScan:
    """The manuscript's count rests on a register of hand adjudications. A register that
    has drifted from the scan is worse than none: it reads as evidence and is not."""

    REGISTER = os.path.join(ROOT, "pdf_extraction", "audit",
                            "portfolio_transfer_adjudication.json")
    SCAN = os.path.join(ROOT, "pdf_extraction", "portfolio_transfer_scan.json")

    def _both(self):
        import io as _io
        import json
        for q in (self.REGISTER, self.SCAN):
            if not os.path.exists(q):
                pytest.skip("%s is not in this clone" % os.path.basename(q))
        return (json.load(_io.open(self.REGISTER, encoding="utf-8")),
                json.load(_io.open(self.SCAN, encoding="utf-8")))

    def test_every_flag_is_adjudicated_and_nothing_else_is(self):
        reg, scan = self._both()
        flagged = {k for k, v in scan.items() if v.get("transfer_occurred")}
        listed = {r["stem"] for r in reg["records"]}
        assert listed == flagged, (
            "only in the scan: %s; only in the register: %s"
            % (sorted(flagged - listed), sorted(listed - flagged)))

    def test_every_adjudication_quotes_the_filing(self):
        reg, _scan = self._both()
        for r in reg["records"]:
            assert r.get("filing_says", "").strip(), r["stem"]
            assert r.get("page"), r["stem"]
            assert r.get("direction") in ("inward", "outward", "both"), r["stem"]
            assert r.get("arrangement") in ("discrete", "standing"), r["stem"]

    def test_the_summary_counts_match_the_records(self):
        """The first draft of the register said 8 inward against 9 records."""
        reg, _scan = self._both()
        recs, s = reg["records"], reg["summary"]
        assert s["flagged"] == len(recs)
        assert s["inward"] + s["outward"] + s["both"] == len(recs)
        assert s["standing_arrangements"] + s["discrete_transactions"] == len(recs)
        for key, want in (("inward", "inward"), ("outward", "outward"), ("both", "both")):
            assert s[key] == sum(1 for r in recs if r["direction"] == want), key


class TestR194_WrittenByNamesTheWriter:
    """"Written by syndicate N" means N wrote the business; "assumed by syndicate N" means N
    took the liabilities. The shared outward list treated them as one, and 1884/2022's
    inward loss portfolio transfer was classed outward on it (R194)."""

    INWARD = [
        # from the filings named, with the typographic quotation marks around LPT and
        # Hiscox dropped; 2008/2021's sentence runs on past the syndicate number
        ("1884", 2022, "During 2022, the Syndicate completed a Loss Portfolio Transfer (LPT) of "
                       "certain classes written by Syndicate 33 in the 2018 and prior YOAs."),
        # verbatim
        ("1884", 2023, "The LPTS cover various classes of business written by Syndicate 33 for "
                       "the 2019 and prior YOAs."),
        ("2008", 2021, "In June 2021, Syndicate 2008 completed a Loss Portfolio Transfer (LPT) "
                       "with Hiscox Ltd (Hiscox), pursuant to which the Syndicate has reinsured a "
                       "diversified portfolio of legacy insurance business underwritten by "
                       "Hiscox Syndicate 3624."),
        # constructed
        ("5678", 2020, "The Syndicate novated the liabilities written by Syndicate 1234 for the "
                       "2015 and prior years of account."),
    ]

    def test_a_transfer_of_business_another_syndicate_wrote_is_inward(self):
        pt._install()
        wrong = [(own, year, rs.classify_sentence(s, own, year)["direction"])
                 for own, year, s in self.INWARD]
        assert all(d == "inward" for _o, _y, d in wrong), wrong

    def test_assumed_by_another_syndicate_is_still_outward(self):
        """Control: the constructions that do mean outward are untouched."""
        s = "The 2019 year of account of the Syndicate was reinsured to close by Syndicate 5000."
        assert rs.classify_sentence(s, "1234", 2021)["direction"] == "outward"

    def test_business_this_syndicate_wrote_is_not_made_inward(self):
        """Control: OTHER excludes the syndicate's own number, so its own business written
        by itself and transferred away stays outward."""
        s = ("The Syndicate transferred the liabilities written by Syndicate 1234 to "
             "Syndicate 5000.")
        assert rs.classify_sentence(s, "1234", 2021)["direction"] != "inward"

    def test_an_acceptance_naming_the_writing_syndicate_is_still_inward(self):
        """Control: an RITC acceptance that names the syndicate whose years it takes, which
        the RITC flag relies on."""
        s = ("The Syndicate accepted the reinsurance to close of the 2016 and prior years of "
             "account written by Syndicate 1234.")
        assert rs.classify_sentence(s, "5678", 2019)["direction"] == "inward"


class TestR199_BusinessTheSyndicateAlsoWroteIsNotInward:
    """R194's construction read a writer list that continues with the reporting syndicate's
    own number as business another syndicate wrote."""

    #: 1861/2021's sentence as the scanner holds it (typographic quotation marks around
    #: RiverStone dropped; the scanner's snippet ends mid-sentence).
    CANOPIUS = ("In December 2021 CMA entered into a Loss Portfolio Transfer Reinsurance (LPT) "
                "agreement with RiverStone Managing Agency Limited (RiverStone) covering the "
                "majority of classes of business no longer written by Syndicates 4444 (2020 & "
                "prior years of account) and 1861 (2020 year")

    def test_the_syndicates_own_business_is_not_inward(self):
        pt._install()
        assert rs.classify_sentence(self.CANOPIUS, "1861", 2021)["direction"] != "inward"

    def test_a_list_of_other_writers_is_still_inward(self):
        """Control: a list of writers none of which is the syndicate itself."""
        pt._install()
        s = ("The Syndicate completed a loss portfolio transfer of classes written by "
             "Syndicates 33 and 3624.")
        assert rs.classify_sentence(s, "2008", 2021)["direction"] == "inward"


def _fake_reports(tmp_path, monkeypatch, by_key):
    """Run the transfer scanner over constructed scan_report results, one per key."""
    for key in by_key:
        (tmp_path / ("syndicate_%s.pdf" % key)).write_bytes(b"")
    monkeypatch.setattr(pt, "REPORTS_DIR", tmp_path)
    monkeypatch.setattr(rs, "scan_report",
                        lambda path: json.loads(json.dumps(by_key[path.stem.replace("syndicate_", "")])))
    try:
        return pt.scan_all()
    finally:
        pt._restore()


def _event(direction, year, pclass, snippet, dated=False):
    return {"direction": direction, "event_year": year, "dated": dated, "prospective": False,
            "counterparty": None, "page": 6, "pattern_class": pclass,
            "strength": "strong" if direction == "inward" else "weak",
            "snippet": snippet, "section": "s"}


class TestR200_TheFlagRestsOnTheEventsThatSurvive:

    #: Two of 1856/2018's events as the scan recorded them before R200. The flag rested on the
    #: first, which describes current business and which the book filter drops, so the flag
    #: must not survive it. That is the rule tested here, and it holds. The record itself is
    #: not current business: the same page says that 15.4% of Syndicate 1955's 2015 and prior
    #: reserves were transferred into 1856's 2016 year of account, an inward transfer told
    #: without a transaction noun, which TestM02 below reads (M02).
    QUOTA_SHARE =("The Whole Account Lloyd's Quota Share consists of business written by "
                   "Syndicate 1955 on a whole account net basis.")
    CASH = "This was driven by the receipt of cash from the quota share of the 1955 2015 & Prior RITC."

    def _report(self, first_snippet):
        return {"detection": "successful", "ritc_occurred": True, "confidence": "strong",
                "evidence": first_snippet, "page": 6, "direction": "inward",
                "event_year": 2018, "n_strong_hits": 1, "n_weak_hits": 0,
                "events": [_event("inward", 2018, "prior_scope", first_snippet),
                           _event("unclear", 2018, "prior_scope", self.CASH)]}

    def test_a_flag_whose_event_was_dropped_is_not_kept(self, tmp_path, monkeypatch):
        out = _fake_reports(tmp_path, monkeypatch, {"9999_2018": self._report(self.QUOTA_SHARE)})
        r = out["9999_2018"]
        assert r["transfer_occurred"] is False, r
        assert r["n_events_dropped_as_current_year"] == 1, r

    def test_a_flag_whose_event_survives_is_kept(self, tmp_path, monkeypatch):
        """Control: the same report with a sentence that does move a book."""
        book = "The Syndicate accepted a loss portfolio transfer of the 2015 and prior liabilities of Syndicate 1955."
        out = _fake_reports(tmp_path, monkeypatch, {"9999_2018": self._report(book)})
        assert out["9999_2018"]["transfer_occurred"] is True, out["9999_2018"]

    def test_a_propagated_flag_carries_the_transfer_field(self, tmp_path, monkeypatch):
        """`propagate()` rebuilds a record with `ritc_occurred`; the transfer scan must not
        be left holding that field instead of its own."""
        accepted = ("The Syndicate accepted a loss portfolio transfer from Syndicate 1234 with "
                    "effect from 1 January 2020.")
        earlier = {"detection": "successful", "ritc_occurred": False, "confidence": "strong",
                   "evidence": "x", "page": None,
                   "events": [_event("inward", 2020, "acceptance", accepted, dated=True)]}
        later = {"detection": "successful", "ritc_occurred": False, "confidence": "strong",
                 "evidence": "no RITC reference in report", "page": None, "events": []}
        out = _fake_reports(tmp_path, monkeypatch, {"9999_2019": earlier, "9999_2020": later})
        r = out["9999_2020"]
        assert "ritc_occurred" not in r, r
        assert r["transfer_occurred"] is True, r


class TestR201_AYearOfAccountLabelIsNotABook:

    #: 6103's sentences as the scan holds them (typographic apostrophes dropped).
    LABELLED = [
        "UNDERWRITERS REPORT 2014 Year of Account Capacity 30 million All the syndicates "
        "business was written by way of a 20% quota share of all US property catastrophe "
        "business (other than terrorism and retrocession business) written by Syndicate 2791.",
        "For the 2016 & 2017 years of account its business was written by way of a 10% quota "
        "share and for 2018 this increased to 30% of all US property catastrophe business "
        "(other than terrorism and retrocession business) written by Syndicate 2791.",
        "From the 2018 year of account its business was written by way of a 30% quota share "
        "of all US property catastrophe business (other than terrorism and retrocession "
        "business) written by Syndicate 2791.",
    ]

    def test_a_quota_share_labelled_by_year_of_account_is_not_a_book(self):
        wrong = [s for s in self.LABELLED if pt._is_a_book_transfer(s)]
        assert not wrong, wrong

    def test_a_qualified_year_of_account_still_names_a_book(self):
        """Controls: prior scope and run-off keep the sentence a book transfer."""
        for s in ("accepted 80% and 90% quota shares of the run-off of the 2019 and 2020 "
                  "years of account",
                  "a quota share of the 2017 and prior years of account of Syndicate 1234",
                  "a quota share of the prior years of account of Syndicate 1234",
                  "accepted a quota share of the open years of account of Syndicate 1234"):
            assert pt._is_a_book_transfer(s), s


class TestR203_ALineBreakHyphenDoesNotEndARunOff:
    """R201's rescan lost 1971/2023: its text layer breaks "run-off" across a line as "run-
    off", which `run[- ]?off` did not match."""

    #: 1971/2023's sentence as its text layer gives it, the hyphen and space kept.
    IBOTT = ("The 2021 year of account accepted 80% and 90% quota shares of the run- off of the "
             "2019 and 2020 years of account respectively for the ibott classes from Syndicate "
             "1969 under the quota share agreement for the 2021 year of account.")

    def test_1971_2023_is_a_book_transfer(self):
        assert pt._is_a_book_transfer(self.IBOTT)

    def test_each_hyphenated_liability_word_survives_a_line_break(self):
        """Constructed so that the split word is the only liability word in the sentence."""
        for s in ("accepted a quota share of the run- off of Syndicate 1234",
                  "accepted a quota share of the prior- year claims of Syndicate 1234",
                  "accepted a quota share of the back- years of Syndicate 1234"):
            assert pt._is_a_book_transfer(s), s

    def test_the_unbroken_forms_still_match(self):
        """Control."""
        for s in ("accepted a quota share of the run-off of Syndicate 1234",
                  "accepted a quota share of the run off of Syndicate 1234",
                  "accepted a quota share of the runoff of Syndicate 1234",
                  "accepted a quota share of the prior year claims of Syndicate 1234"):
            assert pt._is_a_book_transfer(s), s


def _scan_pages(tmp_path, monkeypatch, pages_by_key):
    """Run the transfer scanner over constructed page texts, one list of pages per key. Only
    the text is constructed: `scan_report`, `classify_sentence`, the book filter, the decision,
    propagation and the evidence gate all run as they do on the corpus."""
    for key in pages_by_key:
        (tmp_path / ("syndicate_%s.pdf" % key)).write_bytes(b"")
    monkeypatch.setattr(pt, "REPORTS_DIR", tmp_path)
    monkeypatch.setattr(rs, "load_page_texts",
                        lambda path: pages_by_key[path.stem.replace("syndicate_", "")])
    try:
        return pt.scan_all()
    finally:
        pt._restore()


class TestM02_OldReservesMovedInAreATransfer:
    """1856/2018: a share of another syndicate's prior-year reserves moved into this syndicate's
    year of account, told with a verb and no transaction noun. No pattern of either scanner
    could capture it, although the classifier reads it right (M02).

    Each control scans the old-reserve sentence as well and asserts that it flags: a control
    that passes because the new path is dead proves nothing."""

    #: 1856/2018 p6 as its text layer gives it, line breaks kept. The first paragraph is the
    #: current-business quota share that R200's flag once rested on.
    PAGE6 = ("Whole Account Lloyd’s Quota Share \nThe Whole Account Lloyd’s Quota Share "
             "consists of business written by Syndicate 1955 on a whole account net basis.  This is "
             "\nnet of reinsurance spend, claims and expenses.  The percentage of the cession is "
             "9.72% (2017 15.4%). In 2018 this class \ngenerated gross written premium of "
             "£66.9m (2016: £34.1m).  The increase in the year was due to 15.4% of the "
             "2015 and prior \nyear of account of reserves from Syndicate 1955 being transferred "
             "into the 2016 year of account of Syndicate 1856. \nProperty Insurance \n")
    MOVED_IN = "being transferred into the 2016 year of account of Syndicate 1856"
    CURRENT = "consists of business written by Syndicate 1955"

    @staticmethod
    def _inward(r):
        return [e for e in r["events"] if e["direction"] == "inward"]

    def test_old_reserves_moved_in_flag_the_report_year(self, tmp_path, monkeypatch):
        r = _scan_pages(tmp_path, monkeypatch, {"1856_2018": [self.PAGE6]})["1856_2018"]
        assert r["transfer_occurred"] is True, r
        assert r["confidence"] == "strong", r
        ev = self._inward(r)
        assert len(ev) == 1 and self.MOVED_IN in ev[0]["snippet"], r
        assert ev[0]["pattern_class"] == "moved_in", ev
        assert (ev[0]["event_year"], ev[0]["dated"], ev[0]["counterparty"]) == (2018, "yoa", "1955"), ev
        assert self.MOVED_IN in r["evidence"], r

    def test_the_current_business_quota_share_beside_it_does_not(self, tmp_path, monkeypatch):
        r = _scan_pages(tmp_path, monkeypatch, {"1856_2018": [self.PAGE6]})["1856_2018"]
        assert r["transfer_occurred"] is True, r
        assert not [e for e in r["events"] if self.CURRENT in e["snippet"]], r
        assert r["n_events_dropped_as_current_year"] == 1, r

    def test_the_ceding_syndicates_own_reserves_going_out_are_not_inward(self, tmp_path, monkeypatch):
        """Direction control. In Syndicate 1955's report the same words move ITS reserves out,
        into 1856; beside them, 1955/2018 p5's own account of the cession."""
        ceded = ("During 2018, in line with the terms of the 2016 YoA QS contract with 1856, the "
                 "Syndicate ceded 15.4% of its whole\naccount technical reserves, on the 2015 and "
                 "prior years of account.")
        out = _scan_pages(tmp_path, monkeypatch,
                          {"1856_2018": [self.PAGE6], "1955_2018": [self.PAGE6, ceded]})
        assert out["1856_2018"]["transfer_occurred"] is True, out["1856_2018"]
        r = out["1955_2018"]
        assert r["transfer_occurred"] is False, r
        assert not self._inward(r), r

    def test_1856_2020s_quota_share_labelled_by_years_of_account_stays_unflagged(
            self, tmp_path, monkeypatch):
        """1856/2020 p22 as its text layer gives it (the filing prints it in the basis of
        preparation, which the boilerplate filter skips; here it is classified). "2018 and prior
        years of account" labels a quota share of 1955's current business, in the year that
        quota share was commuted; a widening that took the label for a book flagged it."""
        p22 = ("The Syndicate has a whole account Quota Share contract consisting of \nbusiness "
               "written by syndicate 1955 on a net basis (Net of reinsurance spend, claims and "
               "expenses) for 2018 and \nprior years of account. During the year, the syndicate "
               "commuted the 2017 and prior years whole account Quota \nShare with syndicate 1955 "
               "resulting in a premium refund of £49m, that has been settled during the year. ")
        out = _scan_pages(tmp_path, monkeypatch, {"1856_2018": [self.PAGE6], "1856_2020": [p22]})
        assert out["1856_2018"]["transfer_occurred"] is True, out["1856_2018"]
        r = out["1856_2020"]
        assert r["transfer_occurred"] is False, r
        assert not [e for e in r["events"] if e["pattern_class"] == "moved_in"], r

    def test_1971_2020s_named_class_stays_unflagged(self, tmp_path, monkeypatch):
        """1971/2020 p6, p7 and p8 as its text layer gives them: a quota share of the current
        book of named classes of Syndicate 1969. "General Liability class" is a line of
        business, not a stock of claims. With every event dropped, the evidence says so, rather
        than blaming accounting-policy boilerplate."""
        pages = [
            "For 2020, its business is written by way of a 90% quota share reinsurance of the ibott "
            "(Insuring Businesses \nof Tomorrow, Today) Rover class and the ibott General Liability "
            "class written by Syndicate 1969. ",
            "The syndicate will write a 90% quota share reinsurance of the ibott Rover \nclass and "
            "ibott General Liability class written by Syndicate 1969. ",
            "The business is written by Syndicate 1969 then ceded as a 90% quota share to the "
            "syndicate. "]
        out = _scan_pages(tmp_path, monkeypatch, {"1856_2018": [self.PAGE6], "1971_2020": pages})
        assert out["1856_2018"]["transfer_occurred"] is True, out["1856_2018"]
        r = out["1971_2020"]
        assert r["transfer_occurred"] is False, r
        assert r["evidence"] == "every event found was dropped by the book-transfer filter", r

    def test_what_moves_in_has_to_be_named_as_reserves(self, tmp_path, monkeypatch):
        """The two controls above carry a transfer term, so they never reach the termless path.
        These do. The construction always names a year of account, the one received into, so a
        year-of-account word can never be what moves. Capacity and renewal rights move current
        business, not claims: neither sentence may flag."""
        moved = ["Capacity of Syndicate 1234 was transferred into the 2016 year of account of "
                 "Syndicate 5678.",
                 "The renewal rights to the business of Syndicate 1234 were transferred into the "
                 "2016 year of account of Syndicate 5678."]
        out = _scan_pages(tmp_path, monkeypatch, {"1856_2018": [self.PAGE6], "5678_2018": moved})
        assert out["1856_2018"]["transfer_occurred"] is True, out["1856_2018"]
        r = out["5678_2018"]
        assert r["transfer_occurred"] is False, r
        assert r["n_events_dropped_as_current_year"] == 2, r

    def test_a_named_class_moved_in_is_not_reserves_either(self, tmp_path, monkeypatch):
        """R174's strip holds on the termless path: "Employers Liability account" names a line
        of business, and it is the only liability word here."""
        moved = ["The Employers Liability account of Syndicate 1234 was transferred into the 2016 "
                 "year of account of Syndicate 5678."]
        out = _scan_pages(tmp_path, monkeypatch, {"1856_2018": [self.PAGE6], "5678_2018": moved})
        assert out["1856_2018"]["transfer_occurred"] is True, out["1856_2018"]
        r = out["5678_2018"]
        assert r["transfer_occurred"] is False, r
        assert r["n_events_dropped_as_current_year"] == 1, r

    def test_a_sentence_naming_reinsurance_to_close_is_left_to_the_ritc_scan(
            self, tmp_path, monkeypatch):
        """Syndicate 435's take-on of Syndicate 2255 as three of its reports' text layers give
        it: 2018 p5 whole, 2019 p6 with a line break inside "reinsurance to close", and 2017
        with the sentence split by the page break after "A reinsurance to close". It names its
        transaction, so the termless path does not read it: the RITC scan flags 435/2018, and
        a transfer flag would only repeat that one."""
        p5_2018 = ("the United Kingdom. A reinsurance to close arrangement\nof Syndicate 2255 was "
                   "carried out as at 31 December\n2017; its assets and liabilities were transferred "
                   "to\nSyndicate 435 on 1 January 2018. This transaction\nadded")
        p6_2019 = ("As noted in the 2018 Annual Report a reinsurance \nto close arrangement of "
                   "Syndicate 2255 was \ncarried out as at 31 December 2017; its assets \nand "
                   "liabilities were transferred to Syndicate 435 \non 1 January 2018. This "
                   "transaction added £83.8m \nto premiums written")
        p6_2017 = ("principal activity is the transaction of reinsurance\nbusiness in the United "
                   "Kingdom. A reinsurance to close\nReport of the Directors of the Managing Agent "
                   "\n31 December 2017\n")
        p7_2017 = ("4\narrangement of Syndicate 2255 was carried out as at \n31 December 2017; its "
                   "assets and liabilities were\ntransferred to Syndicate 435 on 1 January 2018. "
                   "\nThis transaction was subject to careful scrutiny")
        out = _scan_pages(tmp_path, monkeypatch, {
            "1856_2018": [self.PAGE6], "435_2017": [p6_2017, p7_2017], "435_2018": [p5_2018],
            "435_2019": [p6_2019]})
        assert out["1856_2018"]["transfer_occurred"] is True, out["1856_2018"]
        for key in ("435_2017", "435_2018", "435_2019"):
            r = out[key]
            assert r["transfer_occurred"] is False, (key, r)
            assert not [e for e in r["events"] if e["pattern_class"] == "moved_in"], (key, r)
        monkeypatch.setattr(rs, "load_page_texts", lambda path: [p5_2018])
        assert rs.scan_report(tmp_path / "syndicate_435_2018.pdf")["ritc_occurred"] is True

    def test_a_later_report_telling_it_flags_the_year_it_happened(self, tmp_path, monkeypatch):
        """Propagation, and the evidence gate after it: the 2018 flag rests on a termless event
        read from the 2019 report, which the gate has to count as evidence."""
        later = ("In 2018, 15.4% of the 2015 and prior year of account reserves from Syndicate 1955 "
                 "were transferred into the 2016 year of account of Syndicate 1856.")
        out = _scan_pages(tmp_path, monkeypatch,
                          {"1856_2018": ["Nothing relevant on this page."], "1856_2019": [later]})
        r = out["1856_2018"]
        assert r["transfer_occurred"] is True, r
        assert r["evidence_report"] == "1856_2019", r
        assert out["1856_2019"]["transfer_occurred"] is False, out["1856_2019"]

    def test_only_the_transfer_scan_carries_the_termless_patterns(self):
        """The RITC flag enters the sample without hand adjudication, so the RITC scan keeps its
        own vocabulary and has no termless path. The transfer scan installs its patterns for the
        scan and takes them out again (R181)."""
        assert rs.TERMLESS_PATTERNS == []
        pt._install()
        assert rs.TERMLESS_PATTERNS is pt.TERMLESS_PATTERNS and pt.TERMLESS_PATTERNS
        pt._restore()
        assert rs.TERMLESS_PATTERNS == []


class TestM02_TheTransferScanReadsEveryFiling:
    """The 2024 filings are HTML. The transfer scan globbed *.pdf, so it never read any of the
    95 (M02). It now reads the RITC scan's file list, through the RITC scan's HTML route."""

    def test_it_lists_what_the_ritc_scan_lists(self, tmp_path, monkeypatch):
        for name in ("syndicate_1111_2020.pdf", "syndicate_2222_2024.html",
                     "syndicate_3333_2024.htm", "notes.txt"):
            (tmp_path / name).write_bytes(b"")
        monkeypatch.setattr(pt, "REPORTS_DIR", tmp_path)
        monkeypatch.setattr(rs, "load_page_texts", lambda path: ["Nothing relevant on this page."])
        try:
            out = pt.scan_all()
        finally:
            pt._restore()
        assert set(out) == {"1111_2020", "2222_2024", "3333_2024"}, sorted(out)
        assert set(out) == {p.stem.replace("syndicate_", "") for p in rs.list_reports(tmp_path)}

    def test_an_html_filing_is_read(self, tmp_path, monkeypatch):
        """No text is patched in: the filing goes through `ritc_scanner.load_page_texts`."""
        paragraphs = [TestM02_OldReservesMovedInAreATransfer.PAGE6.replace("\n", " ")] + [
            "Filler paragraph %d says nothing of interest." % i for i in range(12)]
        (tmp_path / "syndicate_1856_2018.html").write_text(
            "<html><body>%s</body></html>" % "".join("<p>%s</p>" % s for s in paragraphs),
            encoding="utf-8")
        monkeypatch.setattr(pt, "REPORTS_DIR", tmp_path)
        try:
            out = pt.scan_all()
        finally:
            pt._restore()
        r = out["1856_2018"]
        assert r["detection"] == "successful", r
        assert r["transfer_occurred"] is True, r
        assert r["page"] == 1 and "being transferred into" in r["evidence"], r
