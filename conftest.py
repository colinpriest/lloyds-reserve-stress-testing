"""Suite-wide settings for the extraction repository (round 62, review of 29 September 2026).

1. **The working directory.** Every test runs with the repository root as its working directory, and
   the root is importable. The pipeline resolves its caches from the working directory
   (table_extraction.extract_tables' default cache_dir, the OCR page cache, test_gemini's
   REPORTS_DIR, OUTPUT_DIR, LLM_CACHE_DIR and the audit paths), as the driver is documented to run
   from the root. Before this file the suite's verdict depended on where pytest was started: from
   any other directory six round-52 binding replays found no committed Azure cache and failed (E-6).
   A test that needs another directory takes it with monkeypatch.chdir, which runs after the fixture
   here and is undone when the test ends.

2. **The skip budget.** A test may skip only for a reason declared in SKIP_BUDGET, with why that skip
   is acceptable; any other skip is reported as a failure. A skipping test is not a test, and a new
   skip has to be argued for here rather than pass unnoticed (test upgrade 9). Reasons that describe
   a committed artefact missing "in this clone" are deliberately not declared: in a checkout of the
   repository those artefacts are present, so such a skip means the checkout is broken.

3. **Paid calls.** Tests marked `paid_api` run only with LLOYDS_ALLOW_PAID_API=1 (they skip otherwise,
   for a declared reason); `pytest -m "not paid_api"` deselects them.
"""
import os
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
# at import, so that module-level paths read during collection resolve against the root as well
os.chdir(ROOT)

#: (pattern matched against the skip reason, why that skip is acceptable)
SKIP_BUDGET = (
    (r"^optional (Adobe PDF Services|Azure Document Intelligence) SDK not installed$",
     "optional paid table backends; their SDKs are not requirements of the offline suite"),
    (r"^paid extraction is opt-in: set LLOYDS_ALLOW_PAID_API=1 to run it$",
     "a paid call is never made by default"),
    (r"^(the )?source (filing|filings|PDF)( or its table cache)? (is |are )?not (present )?in (this checkout|the repository)"
     r"|^the (source )?filings? (is|are) not in this clone|^source filing is not in this clone; the fixture stands alone$"
     r"|^the source filing is not in this checkout$",
     "the filings are published by Lloyd's and are not committed; tests that read them run where they are"),
    (r"^\S+ is not present in this checkout \(local-only file\)$",
     "local-only files named by the documentation hierarchy are not committed"),
    (r"^PyMuPDF (builds the fixture PDFs?|not installed)$",
     "PyMuPDF is a requirement; the skip only guards a partial environment"),
    (r"^the fixture page was not classified as (relevant|a premium page) on this build$",
     "a generated fixture page whose classification depends on the PDF library's text extraction"),
    (r"^the suite record is being written by scripts/record_tests\.py$",
     "a record cannot check itself while it is being written; every other run checks it"),
)
_DECLARED = [(re.compile(p), why) for p, why in SKIP_BUDGET]


def skip_reason(report):
    """The reason text of a skipped test or collector report."""
    lr = report.longrepr
    if isinstance(lr, tuple) and len(lr) == 3:
        text = str(lr[2])
    else:
        text = str(lr or "")
    return re.sub(r"^Skipped:\s*", "", text.strip())


def declared(reason):
    return any(p.search(reason) for p, _ in _DECLARED)


def _enforce(report):
    if report.skipped and not hasattr(report, "wasxfail"):
        reason = skip_reason(report)
        if not declared(reason):
            report.outcome = "failed"
            report.longrepr = ("undeclared skip: %r. A skip must be declared in conftest.SKIP_BUDGET with why "
                               "it is acceptable, or the test must run." % reason)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    _enforce(outcome.get_result())


@pytest.hookimpl(hookwrapper=True)
def pytest_make_collect_report(collector):
    outcome = yield
    _enforce(outcome.get_result())


@pytest.fixture(autouse=True)
def _run_from_the_repository_root(monkeypatch):
    monkeypatch.chdir(ROOT)
