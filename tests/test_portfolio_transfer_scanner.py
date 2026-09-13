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
SHARED = ("RITC_TERM", "SENTENCE_PATTERNS", "INWARD_SETTLED", "OUTWARD_SETTLED",
          "INWARD_CUES", "OUTWARD_CUES")


def _snapshot():
    return {n: (list(getattr(rs, n)) if isinstance(getattr(rs, n), list)
                else getattr(rs, n)) for n in SHARED}


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

    #: 1856/2018's two events, as the scan recorded them.
    QUOTA_SHARE = ("The Whole Account Lloyd's Quota Share consists of business written by "
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
