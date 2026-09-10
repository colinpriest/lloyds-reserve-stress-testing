"""The change log is the records, not a note about them.

Round 55 re-extracted 53 records under two corrected rules. The account of that change
lived only in a working note outside both repositories, so a reader of the committed
data could not tell which records had moved or why (review B2-02). `docs/extraction-
changelog.md` is now generated from the records themselves; these tests hold it to
that: the document must be exactly what the generator produces from the current tree,
its stem list must be exactly the set of records that differ from the previous pin, and
the unservable list must be the recorded one rather than a list typed beside it.
"""
import io
import json
import os
import re
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import extraction_changelog as CL                                   # noqa: E402

DOC = os.path.join(ROOT, "docs", "extraction-changelog.md")
STEM = re.compile(r"^\| `(syndicate_\d+_\d{4})` \|", re.M)


def _have_pin():
    out = subprocess.run(["git", "-C", ROOT, "cat-file", "-e", CL.DEFAULT_SINCE + "^{commit}"],
                         capture_output=True)
    return out.returncode == 0


pytestmark = pytest.mark.skipif(not _have_pin(),
                                reason="the previous pin is not in this clone")


def _doc():
    if not os.path.exists(DOC):
        pytest.skip("the change log has not been generated in this tree")
    return io.open(DOC, encoding="utf-8").read()


def test_the_document_is_what_the_records_produce():
    """--check regenerates from the tree and compares; a stale document fails."""
    assert CL.main.__module__
    argv = sys.argv[:]
    sys.argv = ["extraction_changelog.py", "--check"]
    try:
        assert CL.main() == 0
    finally:
        sys.argv = argv


def test_the_stem_list_is_the_set_of_records_that_moved():
    rows, _ = CL.survey(CL.DEFAULT_SINCE)
    assert rows, "no record differs from the pin; the log would be vacuous"
    assert sorted(STEM.findall(_doc())) == sorted(r["stem"] for r in rows)


def test_the_stated_count_is_the_number_of_rows():
    doc = _doc()
    m = re.search(r"\*\*(\d+) record\(s\) differ", doc)
    assert m, "the log does not state how many records differ"
    assert int(m.group(1)) == len(STEM.findall(doc))


def test_the_adopted_figure_move_count_is_the_rows_own():
    rows, _ = CL.survey(CL.DEFAULT_SINCE)
    moved = sum(1 for r in rows if r["pyd_old"] != r["pyd_new"])
    m = re.search(r"adopted figure moves in (\d+) of them", _doc())
    assert m and int(m.group(1)) == moved


def test_the_unservable_list_is_the_recorded_one():
    p = os.path.join(ROOT, "pdf_extraction", "audit", "offline_unservable.json")
    if not os.path.exists(p):
        pytest.skip("no unservable record in this tree")
    stems = json.load(io.open(p, encoding="utf-8"))["stems"]
    doc = _doc()
    if not stems:
        assert "could not be replayed offline" not in doc
        return
    listed = re.findall(r"^- `(syndicate_\d+_\d{4})`$", doc, re.M)
    assert sorted(listed) == sorted(stems)


def test_every_row_names_a_committed_record():
    for stem in STEM.findall(_doc()):
        assert os.path.exists(os.path.join(ROOT, "pdf_extraction", stem + ".json")), stem
