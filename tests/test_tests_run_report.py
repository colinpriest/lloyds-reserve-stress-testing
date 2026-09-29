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
    assert rec["passed"] + rec["skipped"] == rec["collected"], rec
    assert sum(rec["skipped_reasons"].values()) == rec["skipped"]
    for where, n in rec["skipped_reasons"].items():
        assert conftest.declared(where.split(": ", 1)[1]), where
    subprocess.run(["git", "-C", str(ROOT), "cat-file", "-e", rec["commit"] + "^{commit}"], check=True)
    assert _collected_now() == rec["collected"], (
        "the suite has changed size since the record was written: run python scripts/record_tests.py")
