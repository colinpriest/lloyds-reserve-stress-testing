r"""Every record in the corpus was produced by the same extraction specification.

Round 56 re-extracted the corpus at prompt 2.13 and reported success: 962 records attempted,
8 already current, 14 workers, all exit 0. The corpus holds 1,065 records. Nothing compared
those two numbers, so 95 records sat outside the run and the corpus ended split across five
prompt versions -- 957 at 2.13, 90 at 2.10, 13 at 2.6, and one each at 2.7, 2.8, 2.9 and the
withdrawn 2.12.

The cause was a stem list built from `syndicate_reports/pdfs/*.pdf`. Every 2024 filing in
this corpus was published as HTML and is stored as `.html` in that same directory, so the
glob dropped the entire 2024 reporting year -- from which the working sample draws 79 of its
920 observations. A refit would have fitted one specification's output beside another's.

A run that reports its own success against its own stem list cannot detect a stem list that
is missing records. This compares the corpus against itself instead.
"""
import glob
import io
import json
import os

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: Records that cannot be brought to the current specification without a paid backend call,
#: which the owner's standing instruction is to skip. Listing them by name is the point: a
#: record that falls behind for any OTHER reason has to fail this test.
#:
#: Two different facts, kept apart. Most have no committed cache at all. 1100/2024 has one,
#: in the legacy list format that carries no page or category information, so the guard
#: refuses it -- and a skip list built by testing whether a FILE EXISTS missed it, which is
#: how it reached the end of a run still at prompt 2.6.
NO_CACHE = {
    "syndicate_2357_2014", "syndicate_2689_2017", "syndicate_2689_2018",
    "syndicate_2786_2016", "syndicate_2786_2017", "syndicate_2988_2017",
    "syndicate_2988_2018", "syndicate_3268_2018", "syndicate_3268_2019",
}
UNUSABLE_CACHE = {
    "syndicate_1100_2024",      # legacy list format; the only one in the corpus
}
CACHELESS = NO_CACHE | UNUSABLE_CACHE


def _records():
    out = {}
    for q in sorted(glob.glob(os.path.join(ROOT, "pdf_extraction", "syndicate_*.json"))):
        stem = os.path.basename(q)[:-5]
        if stem.count("_") != 2:
            continue
        try:
            int(stem.rsplit("_", 1)[1])
        except ValueError:
            continue          # a summary file, not a record
        try:
            out[stem] = json.load(io.open(q, encoding="utf-8"))
        except (OSError, ValueError):
            out[stem] = None
    return out


def _current_version():
    src = io.open(os.path.join(ROOT, "test_gemini.py"), encoding="utf-8").read()
    line = next(l for l in src.splitlines() if l.startswith("PROMPT_VERSION"))
    return line.split('"')[1]


class TestTheCorpusIsOneSpecification:

    def test_every_record_parses(self):
        bad = [s for s, d in _records().items() if d is None]
        assert bad == [], bad

    def test_every_record_is_at_the_current_prompt_version(self):
        """The check the round-56 run did not have.

        A record left on an older prompt is a record the current specification never
        produced, and a sample that mixes them is not one sample."""
        cur = _current_version()
        behind = {}
        for stem, d in _records().items():
            v = (d.get("spec") or {}).get("prompt_version")
            if v != cur:
                behind.setdefault(v, []).append(stem)
        unexplained = {v: [s for s in stems if s not in CACHELESS]
                       for v, stems in behind.items()}
        unexplained = {v: s for v, s in unexplained.items() if s}
        assert not unexplained, (
            "records are not at prompt %s and are not in the cacheless list: %s"
            % (cur, {v: (s[:8] + ["..."] if len(s) > 8 else s)
                     for v, s in unexplained.items()}))

    def test_the_withdrawn_prompt_produced_no_surviving_record(self):
        """2.12 was run over roughly 470 records and withdrawn. The register says no record
        produced under it is retained, and this is what holds that sentence true."""
        left = [s for s, d in _records().items()
                if (d.get("spec") or {}).get("prompt_version") == "2.12"]
        assert left == [], left

    def _cache_state(self, stem):
        """(exists, usable). Usable means the guard would serve it, not that a file is
        there: a legacy list cache carries no page or category information and is refused."""
        q = os.path.join(ROOT, "pdf_extraction", "azure_output", "%s_azure.json" % stem)
        if not os.path.exists(q):
            return False, False
        try:
            return True, isinstance(json.load(io.open(q, encoding="utf-8")), dict)
        except (OSError, ValueError):
            return True, False

    def test_the_skip_list_is_still_accurate(self):
        """An allowance that has stopped being true is an allowance that hides a defect.

        Each named record must really be unservable. Asked as "does a file exist?" this
        passed while 1100/2024 -- which has a file, in a format the guard refuses -- ran to
        the end of a corpus run still at prompt 2.6."""
        servable = [s for s in sorted(CACHELESS) if self._cache_state(s)[1]]
        assert servable == [], (
            "these records can be served from the committed cache, so they can be brought "
            "to the current specification and should leave the skip list: %s" % servable)

    def test_the_two_reasons_are_kept_apart(self):
        """No cache and an unreadable cache are different facts about a record."""
        for stem in sorted(NO_CACHE):
            exists, _usable = self._cache_state(stem)
            assert not exists, ("%s has a cache file, so it belongs in UNUSABLE_CACHE with "
                                "the reason, not in NO_CACHE" % stem)
        for stem in sorted(UNUSABLE_CACHE):
            exists, usable = self._cache_state(stem)
            assert exists and not usable, (
                "%s is listed as having an unusable cache; it %s" %
                (stem, "has none at all" if not exists else "is in fact servable"))

    def test_a_filing_exists_for_every_record(self):
        """The corpus and the filings are the same set.

        The 2024 filings are `.html` in the reports directory; globbing `*.pdf` is what
        dropped them from the round-56 stem list."""
        reports = os.path.join(ROOT, "syndicate_reports", "pdfs")
        if not os.path.isdir(reports):
            pytest.skip("the filings are not in this clone")
        have = {os.path.splitext(f)[0] for f in os.listdir(reports)
                if f.lower().endswith((".pdf", ".html", ".htm"))}
        missing = sorted(set(_records()) - have)
        assert missing == [], missing

    def test_the_reports_directory_is_not_all_pdfs(self):
        """The control for the test above: if every filing were a PDF, that test would pass
        whether or not it looked beyond `*.pdf`, and would not be holding anything down."""
        reports = os.path.join(ROOT, "syndicate_reports", "pdfs")
        if not os.path.isdir(reports):
            pytest.skip("the filings are not in this clone")
        html = [f for f in os.listdir(reports) if f.lower().endswith((".html", ".htm"))]
        assert html, ("no filing in this corpus is HTML, so the stem-list defect this "
                      "suite exists for can no longer be reproduced here")
