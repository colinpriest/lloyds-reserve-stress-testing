"""Round 62 (review of 29 September 2026, test upgrade 9): the suite's skip budget.

conftest.py declares every reason a test may skip for, with why; any other skip fails the run. These
tests hold the mechanism end to end (a generated suite with one declared and one undeclared skip, run
in its own process) and hold the declarations to the skips the suite's own sources can raise.

Run:  python -m pytest tests/test_skip_budget.py -q
"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import conftest  # noqa: E402

GENERATED = '''
import pytest

def test_declared():
    pytest.skip("source filing not present in this checkout")

def test_undeclared():
    pytest.skip("the network was slow today")

def test_runs():
    assert True
'''


def test_an_undeclared_skip_fails_the_run(tmp_path):
    (tmp_path / "conftest.py").write_text((ROOT / "conftest.py").read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "test_generated.py").write_text(GENERATED, encoding="utf-8")
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(tmp_path)],
                       cwd=str(tmp_path), capture_output=True, text=True)
    out = r.stdout + r.stderr
    assert r.returncode == 1, out
    assert re.search(r"1 failed, 1 passed, 1 skipped", out), out
    assert "undeclared skip: 'the network was slow today'" in out, out


def test_every_skip_the_suite_can_raise_is_declared_or_marks_a_broken_checkout():
    """Every literal skip reason in the test sources either matches a declaration or names a
    committed artefact (which a checkout always has, so its skip rightly fails)."""
    committed = re.compile(r"(is not|are not|not) (present )?in this (clone|checkout|tree)|not (been )?generated|"
                           r"no (committed|register|unservable)|no cached grid|could not import", re.I)
    reasons = []
    for path in sorted((ROOT / "tests").glob("test_*.py")):
        if path.name == Path(__file__).name:
            continue            # this file's generated suite skips on purpose
        src = path.read_text(encoding="utf-8")
        for m in re.finditer(r'(?:pytest\.skip|reason=)\(?\s*"([^"]+)"', src):
            reasons.append((path.name, m.group(1)))
    assert len(reasons) > 20
    for name, reason in reasons:
        text = reason.replace("%s", "X").replace("%r", "'X'")
        assert conftest.declared(text) or committed.search(text), (name, reason)


def test_the_declared_reasons_match_the_suites_own_wording():
    for reason in ("optional Adobe PDF Services SDK not installed",
                   "optional Azure Document Intelligence SDK not installed",
                   "paid extraction is opt-in: set LLOYDS_ALLOW_PAID_API=1 to run it",
                   "source filing not present in this checkout",
                   "the source filing or its table cache is not in this checkout",
                   "the filings are not in this clone",
                   "source PDF not in the repository (reports are not committed)",
                   "the fixture page was not classified as relevant on this build"):
        assert conftest.declared(reason), reason
    for reason in ("the scan output is not in this clone", "no register committed",
                   "syndicate_1884_2016.json is not present in this checkout", "flaky"):
        assert not conftest.declared(reason), reason
