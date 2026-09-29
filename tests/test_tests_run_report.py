"""Round 62 (review of 29 September 2026, S-1 and test upgrade 8): the suite record is current.

tests-run-report.json is written by scripts/record_tests.py and is what the manuscript's checklist
count is generated from. A record can go stale exactly as a typed count does, so this test fails when
the committed record is dirty, not green, inconsistent with itself, or no longer the size of the suite.
While the recorder itself is running, the record is the thing being written and this test skips for
that declared reason; every other run checks it.

Run:  python -m pytest tests/test_tests_run_report.py -q
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import conftest  # noqa: E402

RECORD = ROOT / "tests-run-report.json"
WRITING = "the suite record is being written by scripts/record_tests.py"


def _collected_now():
    env = dict(os.environ, LLOYDS_EXTRACTION_OFFLINE="1", PYTHONIOENCODING="utf-8")
    env.pop("LLOYDS_ALLOW_PAID_API", None)
    r = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider"],
                       cwd=str(ROOT), env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return int(re.search(r"(\d+) tests? collected", r.stdout + r.stderr).group(1))


def test_the_suite_record_is_clean_green_and_current():
    if os.environ.get("LLOYDS_RECORDING_SUITE") == "1":
        pytest.skip(WRITING)
    assert RECORD.exists(), "no suite record: run python scripts/record_tests.py on a clean tree"
    rec = json.loads(RECORD.read_text(encoding="utf-8"))
    # worktree_dirty_src is the key the manuscript's gate reads (paper/audit_numbers.py)
    assert rec["worktree_dirty_src"] is False, rec.get("worktree_dirty_paths")
    assert {"commit", "passed", "skipped", "failed", "collected", "skipped_reasons"} <= set(rec)
    assert rec["failed"] == 0 and rec["errors"] == 0 and rec["exit_code"] == 0, rec["summary_line"]
    # a module skipped whole at collection is a skipped outcome but not a collected item; the record
    # names how many, and a fresh collection must account for exactly that many
    cs = rec["collection_skipped"]
    assert 0 <= cs <= rec["skipped"], rec
    outcomes = rec["passed"] + rec["failed"] + rec["errors"] + rec["skipped"]
    assert outcomes - _collected_now() == cs, (outcomes, cs)
    assert sum(rec["skipped_reasons"].values()) == rec["skipped"]
    for where, n in rec["skipped_reasons"].items():
        assert conftest.declared(where.split(": ", 1)[1]), where
    subprocess.run(["git", "-C", str(ROOT), "cat-file", "-e", rec["commit"] + "^{commit}"], check=True)
    assert _collected_now() == rec["collected"], (
        "the suite has changed size since the record was written: run python scripts/record_tests.py")


#: what the manuscript's gate counts as a test file (paper/audit_numbers.py, upstream_test_record);
#: test_gemini.py matches it too, so a change to the pipeline also makes the record stale
TEST_FILE = re.compile(r"(^|/)tests?/|test_[^/]*\.py$|_test\.py$|conftest\.py$")


def test_no_test_file_changed_since_the_suite_record_was_made():
    """Verification review of round 62, test gap: the test above checks that the record's commit
    exists and that the suite still has its size, so a test edited after the record -- same count,
    different assertions -- passed it. The manuscript's gate checks what this one now does: the
    record's commit is an ancestor of HEAD, and no test file differs between that commit and the
    tree that is running, committed or not."""
    if os.environ.get("LLOYDS_RECORDING_SUITE") == "1":
        pytest.skip(WRITING)
    rec = json.loads(RECORD.read_text(encoding="utf-8"))
    anc = subprocess.run(["git", "-C", str(ROOT), "merge-base", "--is-ancestor", rec["commit"], "HEAD"],
                         capture_output=True)
    assert anc.returncode == 0, "the suite was recorded at %s, which is not an ancestor of HEAD" % rec["commit"]
    changed = subprocess.run(["git", "-C", str(ROOT), "diff", "--name-only", rec["commit"]],
                             capture_output=True, text=True, check=True).stdout.split()
    stale = [f for f in changed if TEST_FILE.search(f)]
    assert not stale, ("test file(s) changed after the suite was recorded at %s: %s; run "
                       "python scripts/record_tests.py on a clean tree" % (rec["commit"][:12], stale[:5]))
