"""Round 62 (review of 29 September 2026, MAT-2, R7-02 and test upgrade 2): every committed record is
what the current code produces from its own caches.

1884/2022 and 3330/2018 sat for a fortnight as records no current code would write: the replay that
followed a rule change covered only the records that still carried a triangle. These tests hold the
corpus to an offline replay of the deterministic step (scripts/replay_corpus_check.py):

  * the committed full run (pdf_extraction/audit/corpus_replay_check.json) is of the current code and
    records -- its hashes are this tree's table_extraction.py, and test_gemini.py or a version of it
    that differs only in code the replay cannot run, and the content the check compared in every
    committed record -- and found no undeclared mismatch, no stale declaration and no unread record
    holding a usable gross triangle;
  * a documented subset (SUBSET below) is replayed here, in the default suite (the full corpus takes
    about a quarter of an hour on 14 workers, so it is the script's job, not the suite's);
  * no unread record's cached grids hold a gross triangle with a usable cohort that yields a figure,
    unless it is waiting for the models (redecision_pending.json).

Run:  python -m pytest tests/test_corpus_replay.py -q
      python scripts/replay_corpus_check.py --workers 14 --write      (the full run)
"""
import ast
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import replay_corpus_check as rcc  # noqa: E402

#: The subset replayed by default: the review's named records, declared records, and stubs, unread
#: records and models records spread across the corpus, each of whose replays took at most three
#: seconds in the round-62 full run (a scanned filing's OCR rotation pass takes half a minute).
SUBSET = sorted(set("""
syndicate_2468_2022 syndicate_1884_2022 syndicate_3330_2018 syndicate_4747_2024 syndicate_1902_2024
syndicate_2689_2024 syndicate_2880_2024 syndicate_4242_2024 syndicate_1840_2022
syndicate_1884_2016 syndicate_1206_2019 syndicate_5820_2019
syndicate_1084_2020 syndicate_1183_2023 syndicate_1218_2024 syndicate_1400_2014 syndicate_1492_2021
syndicate_1274_2014 syndicate_1347_2023 syndicate_1609_2021
syndicate_1699_2022 syndicate_1975_2019 syndicate_2232_2024 syndicate_3622_2018 syndicate_1922_2024
syndicate_1322_2023 syndicate_1416_2022 syndicate_1609_2022 syndicate_1618_2022 syndicate_1699_2023
syndicate_1840_2020 syndicate_1971_2020 syndicate_1980_2019 syndicate_2019_2021
syndicate_2358_2022 syndicate_5886_2018 syndicate_6131_2019
""".split()))


def _report():
    return json.loads(rcc.REPORT.read_text(encoding="utf-8"))


#: where the replay enters test_gemini.py: replay_corpus_check.replay() calls the first two, and its
#: grid checks call the third
REPLAY_ENTRY_POINTS = ("extract_pyd_from_relevant_pages", "convert_html_to_pdf", "compute_pyd_from_triangle")


def _replayed_version(name, digest):
    """`name` as the full run hashed it: the committed version whose LF-normalised sha256 is
    `digest`, read from git; None if no commit holds it."""
    commits = subprocess.run(["git", "-C", str(ROOT), "log", "--format=%H", "--", name],
                             capture_output=True, text=True, check=True).stdout.split()
    for commit in commits:
        blob = subprocess.run(["git", "-C", str(ROOT), "show", "%s:%s" % (commit, name)],
                              capture_output=True, check=True).stdout.replace(b"\r\n", b"\n")
        if hashlib.sha256(blob).hexdigest() == digest:
            return blob.decode("utf-8")
    return None


def _names(node):
    return ({n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
            | {n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)})


def changes_the_replay_can_reach(old_src, new_src, entry_points=REPLAY_ENTRY_POINTS):
    """What differs between two versions of a module in code the replay could run: a changed
    module-level statement (the `__main__` block aside, which an import does not run), or a changed,
    added or removed function or class that the entry points reach. Reach is followed by name over
    both versions -- every name a reached definition mentions, and every name a module-level
    statement mentions -- so it can only over-reach. Comments are not code: they are not compared."""
    def split(src):
        defs, stmts = {}, []
        for node in ast.parse(src).body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                defs[node.name] = node
            elif not (isinstance(node, ast.If) and "__main__" in ast.dump(node.test)):
                stmts.append(node)
        return defs, stmts
    (old_defs, old_stmts), (new_defs, new_stmts) = split(old_src), split(new_src)
    changed = []
    if [ast.dump(s) for s in old_stmts] != [ast.dump(s) for s in new_stmts]:
        changed.append("a module-level statement")
    reached, todo = set(), list(entry_points) + [n for s in old_stmts + new_stmts for n in _names(s)]
    while todo:
        name = todo.pop()
        if name in reached or (name not in old_defs and name not in new_defs):
            continue
        reached.add(name)
        for d in (old_defs.get(name), new_defs.get(name)):
            if d is not None:
                todo.extend(_names(d))
    for name in sorted(reached):
        if name not in old_defs or name not in new_defs or ast.dump(old_defs[name]) != ast.dump(new_defs[name]):
            changed.append(name)
    return changed


def test_a_change_the_replay_cannot_run_is_told_from_one_it_can():
    """The rule the next test applies to test_gemini.py, on small modules whose answer is known."""
    old = ("RATE = 2\n\ndef entry(x):\n    return helper(x) * RATE\n\ndef helper(x):\n    return x + 1\n\n"
           "def live_call(x):\n    return x * 3\n\nif __name__ == '__main__':\n    live_call(1)\n")
    same = changes_the_replay_can_reach
    assert same(old, old.replace("return x * 3", "return x * 4"), ("entry",)) == []
    assert same(old, old + "\ndef new_cost(x):\n    return x\n", ("entry",)) == []
    assert same(old, old + "# a comment\n", ("entry",)) == []
    assert same(old, old.replace("live_call(1)", "live_call(2)"), ("entry",)) == []
    assert same(old, old.replace("return x + 1", "return x + 2"), ("entry",)) == ["helper"]
    assert same(old, old.replace("RATE = 2", "RATE = 3"), ("entry",)) == ["a module-level statement"]
    assert same(old, old.replace("return helper(x) * RATE", "return new(x)") + "\ndef new(x):\n    return x\n",
                ("entry",)) == ["entry", "new"]
    assert same(old, old.replace("def helper", "def helped"), ("entry",)) == ["helper"]


def test_the_committed_full_replay_is_of_this_code_and_found_nothing_undeclared():
    assert rcc.REPORT.exists(), "run: python scripts/replay_corpus_check.py --workers 14 --write"
    rep = _report()
    hashes = rcc.code_hashes()
    for name, digest in sorted(rep["code_sha256_lf"].items()):
        if hashes[name] == digest:
            continue
        # table_extraction.py is the deterministic step throughout, so any change to it needs a new
        # run. test_gemini.py also holds the model calls, their cost accounting and the driver, which
        # the replay never runs: a change confined to those does not change what it decided (round 62,
        # second cycle: Gemini's thinking tokens priced in extract_with_gemini).
        assert name == "test_gemini.py", (
            "%s changed after the full replay: run scripts/replay_corpus_check.py --write again" % name)
        replayed = _replayed_version(name, digest)
        assert replayed is not None, "the code the full replay ran is in no commit: run the replay again"
        reached = changes_the_replay_can_reach(replayed, (ROOT / name).read_text(encoding="utf-8"))
        assert reached == [], (
            "test_gemini.py changed after the full replay in code the replay runs (%s): run "
            "scripts/replay_corpus_check.py --write again" % ", ".join(reached))
    records = rcc.committed_records()
    assert rep["records_sha256"] == rcc.records_hash(records), (
        "a committed record changed after the full replay: run scripts/replay_corpus_check.py --write again")
    assert rep["n_records"] == rep["n_replayed"] == len(records)
    assert rep["undeclared_mismatches"] == [], rep["undeclared_mismatches"][:5]
    assert rep["stale_declarations"] == []
    assert rep["unread_records_with_a_usable_gross_grid"] == []
    pending, unservable = rcc.declared()
    assert rep["declared_pending"] == sorted(pending) and rep["declared_unservable"] == sorted(unservable)
    # every declared record did differ, and nothing else did
    assert {d["stem"] for d in rep["declared_mismatches"]} == pending | unservable


def test_a_replay_of_the_subset_is_the_committed_corpus():
    have = [s for s in SUBSET if rcc._filing(s) is not None]
    if not have:
        pytest.skip("source filings not present in this checkout")
    result = rcc.check(have, workers=4)
    assert result["undeclared_mismatches"] == [], result["undeclared_mismatches"]
    assert result["stale_declarations"] == [], result["stale_declarations"]


def test_no_unread_record_holds_a_usable_gross_triangle_in_its_cache():
    """Committed caches only, so this runs in any checkout. The check must be able to find one: the
    one-column triangle 2468/2022's committed Azure cache holds (UW2020, -0.153m) is found."""
    control = rcc.usable_gross_grids("syndicate_2468_2022")
    assert any(g["years"] == [2020] and g["pyd"] == pytest.approx(-0.153, abs=5e-4) for g in control), control
    pending, _ = rcc.declared()
    found = []
    for stem, d in rcc.committed_records().items():
        if rcc.committed_class(d) == "unread" and stem not in pending:
            g = rcc.usable_gross_grids(stem)
            if g:
                found.append((stem, g))
    assert found == []


def _section(number: str) -> str:
    text = (ROOT / "docs" / "ocr-pipeline.md").read_text(encoding="utf-8").replace("\r\n", "\n")
    start = text.index("\n### %s " % number)
    return text[start:text.index("\n## ", start + 1)]


def test_the_unread_filings_whose_gross_grids_the_structure_score_refuses_are_reported_and_named():
    """Verification review of round 62, N-V-E-4. The check above sees only grids that yield a figure,
    so a grid the structure score refuses -- the MAT-2 failure mode -- is invisible to it: 3500/2015
    holds a gross five-cohort triangle the multi-column rule scores 0.00, and it passed every clause.
    The replay now reports the unread filings whose gross grids with a usable cohort are all refused
    by the structure score. Committed caches only: the committed full run's list is the one the caches
    give, 3500/2015's grid is found (the positive control), and docs 11.4 names every filing listed and
    the four other unread filings it says print a table the parsers do not read, none of which holds a
    grid either check can see."""
    control = rcc.structure_refused_gross_grids("syndicate_3500_2015")
    assert control == [{"table": 3, "years": [2006, 2007, 2008, 2009, 2010], "structure_score": 0.0}], control
    pending, _ = rcc.declared()
    found = []
    for stem, d in sorted(rcc.committed_records().items()):
        if rcc.committed_class(d) == "unread" and stem not in pending:
            g = rcc.structure_refused_gross_grids(stem)
            if g:
                found.append({"stem": stem, "grids": g})
    assert _report()["unread_records_whose_gross_grids_the_structure_score_refuses"] == found
    section = _section("11.4")
    others = ["syndicate_3622_2018", "syndicate_1699_2022", "syndicate_1975_2019", "syndicate_1922_2024"]
    for stem in [r["stem"] for r in found] + others:
        assert "%s/%s" % tuple(stem.split("_")[1:]) in section, stem
    records = rcc.committed_records()
    for stem in others:
        assert rcc.committed_class(records[stem]) == "unread", stem
        assert rcc.structure_refused_gross_grids(stem) == [] and rcc.usable_gross_grids(stem) == [], stem


def test_the_one_column_triangle_of_2468_2022_is_read_and_its_record_accounted_for():
    """The current code reads 2468/2022's one-column triangle (-0.153m, from the Azure grid). Its
    committed record is either declared as waiting for the models, and then still differs from the
    replay -- a rule that stopped reading it would show here -- or not declared, and then is exactly
    what the replay gives."""
    if rcc._filing("syndicate_2468_2022") is None:
        pytest.skip("source filings not present in this checkout")
    x = rcc.replay("syndicate_2468_2022")
    assert x["pyd"] == pytest.approx(-0.153, abs=5e-4) and x["method"] == "azure"
    d = rcc.committed_records()["syndicate_2468_2022"]
    pending, _ = rcc.declared()
    if "syndicate_2468_2022" in pending:
        assert rcc.compare(d, x), "the committed record already equals the replay: update the pending list"
    else:
        assert rcc.compare(d, x) == [], "the committed record is not what the current code writes"
