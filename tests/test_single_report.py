"""Extraction of syndicate_2987_2018 end to end, and the one test that may call the paid APIs.

Review of 29 September 2026, E-5: this file ran a paid dual-model extraction whenever keys were
set, asserted nothing, and checked GEMINI_API_KEY where the pipeline reads GOOGLE_API_KEY. Now:

* test_single_report_extraction is marked `paid_api` and runs only when the operator opts in with
  LLOYDS_ALLOW_PAID_API=1 (and the filing and the keys the pipeline reads are present). Without the
  opt-in it skips for a declared reason (conftest.py SKIP_BUDGET), so `pytest -q` never contacts a
  paid service, and `pytest -m "not paid_api"` deselects it outright.
* test_the_offline_replay_gives_the_filings_figure runs by default: the same record replayed
  offline from the committed caches, which costs nothing.

Both assert the figure. Expected, from the GROSS claims development triangle (filing page 41,
USD millions):
  2011: 838.8 - 840.5 = -1.7        2014: 1132.4 - 1143.1 = -10.7
  2012: 961.7 - 972.7 = -11.0       2015: 1056.1 - 1071.9 = -15.8
  2013: 984.0 - 998.2 = -14.2       2016: 1354.3 - 1229.5 = +124.8
  Total = +71.4 (strengthening); the committed record holds +71.4 in both blocks, route rag_triangle.

Run:  python -m pytest tests/test_single_report.py -q
      LLOYDS_ALLOW_PAID_API=1 python -m pytest tests/test_single_report.py -m paid_api -q   (paid)
"""
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

REPORT = ROOT / "syndicate_reports" / "pdfs" / "syndicate_2987_2018.pdf"
EXPECTED = 71.4
#: the declared skip reasons (conftest.py SKIP_BUDGET matches them)
OPT_IN = "paid extraction is opt-in: set LLOYDS_ALLOW_PAID_API=1 to run it"
NO_FILING = "source filing not present in this checkout"


def _assert_the_figure(output):
    import test_gemini as tg
    for name in (tg.GEMINI_MODEL, tg.OPENAI_MODEL):
        block = output["models"][name]
        assert block["prior_year_development_gbp_m"] == pytest.approx(EXPECTED, abs=0.05), name
        assert (block.get("_pyd_route") or {}).get("source") == "rag_triangle", name
        assert block.get("direction") == "strengthening", name


def run_single_report(report_path=REPORT, output_dir=None):
    """process_one_report on the filing; returns its output record. Kept out of module scope so
    collection never executes it. Nothing is written to the repository: the slim PDF goes to
    `output_dir` and the inception cache is not saved."""
    import test_gemini as tg
    saved = (tg.OUTPUT_DIR, tg._save_inception_years)
    try:
        if output_dir is not None:
            tg.OUTPUT_DIR = Path(output_dir)
        tg._save_inception_years = lambda inc: None
        result = tg.process_one_report(Path(report_path), inception_cache={})
    finally:
        tg.OUTPUT_DIR, tg._save_inception_years = saved
    assert isinstance(result, tuple) and len(result) == 4, result
    return result[0]


@pytest.mark.paid_api
def test_single_report_extraction(tmp_path):
    if os.environ.get("LLOYDS_ALLOW_PAID_API") != "1":
        pytest.skip(OPT_IN)
    if not REPORT.exists():
        pytest.skip(NO_FILING)
    if not (os.environ.get("GOOGLE_API_KEY") and os.environ.get("OPENAI_API_KEY")):
        pytest.fail("LLOYDS_ALLOW_PAID_API=1 but GOOGLE_API_KEY and OPENAI_API_KEY are not both set")
    _assert_the_figure(run_single_report(output_dir=tmp_path))


def test_the_offline_replay_gives_the_filings_figure(tmp_path, monkeypatch):
    if not REPORT.exists() or not (ROOT / "pdf_extraction" / "azure_output" / (REPORT.stem + "_azure.json")).exists():
        pytest.skip(NO_FILING)
    monkeypatch.setenv("LLOYDS_EXTRACTION_OFFLINE", "1")
    monkeypatch.delenv("LLOYDS_ALLOW_TABLE_BACKEND_CALLS", raising=False)
    _assert_the_figure(run_single_report(output_dir=tmp_path))


def test_the_paid_test_is_opt_in(monkeypatch, tmp_path):
    """Without LLOYDS_ALLOW_PAID_API=1 the paid test skips before it touches anything, whatever
    keys the environment holds."""
    marks = {m.name for m in getattr(test_single_report_extraction, "pytestmark", [])}
    assert "paid_api" in marks
    monkeypatch.delenv("LLOYDS_ALLOW_PAID_API", raising=False)
    monkeypatch.setenv("GOOGLE_API_KEY", "set")
    monkeypatch.setenv("OPENAI_API_KEY", "set")
    with pytest.raises(pytest.skip.Exception, match="opt-in"):
        test_single_report_extraction(tmp_path)


if __name__ == "__main__":
    if os.environ.get("LLOYDS_ALLOW_PAID_API") != "1":
        sys.exit(OPT_IN)
    _assert_the_figure(run_single_report())
    print("OK: both blocks hold %+.1f from the gross triangle" % EXPECTED)
