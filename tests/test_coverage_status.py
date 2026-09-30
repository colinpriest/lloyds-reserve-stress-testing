"""The committed coverage outputs describe the committed records (verification review of round 62,
N-V-E-3).

syndicate_reports/coverage/ (coverage_status.json, .xlsx, coverage_report.md) was built at 13:17 on
29 September 2026, before the re-extraction of that afternoon, and was not built again: eleven rows
(2255/2015, 3330/2018 and nine 2024 filings) still classed as reports with no triangle records that
now carry a figure or are first-year stubs, and the report's waterfall and success count were stale
with them. A derived output is rebuilt after the last change to its inputs; this holds the rows to the
records they are built from, so a record changed without a rebuild fails here.

Run:  python -m pytest tests/test_coverage_status.py -q
      python scripts/build_coverage_status.py        (the rebuild, offline, about half an hour)
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import replay_corpus_check as rcc  # noqa: E402

COVERAGE = ROOT / "syndicate_reports" / "coverage" / "coverage_status.json"
#: the coverage row's exclusion_class for each record class (scripts/build_coverage_status.py)
ROW_CLASS = {"unread": "no_triangle_data", "stub_before_models": "first_year_syndicate",
             "stub_after_models": "first_year_syndicate", "models": None, "reviewed_audit": None,
             "audited_unread_stub": "first_year_syndicate"}


def test_every_coverage_row_is_classed_as_its_record_is():
    records = rcc.committed_records()
    rows = json.loads(COVERAGE.read_text(encoding="utf-8"))["rows"]
    assert len(rows) == 1125
    seen = {}
    for row in rows:
        stem = "syndicate_%s_%s" % (row["syndicate"], row["year"])
        d = records.get(stem)
        if d is None:
            assert row["extraction_file_exists"] is False, stem
            continue
        assert row["extraction_file_exists"] is True, stem
        cls = rcc.committed_class(d)
        assert row["exclusion_class"] == ROW_CLASS[cls], (stem, row["exclusion_class"], cls)
        if cls == "unread":   # the row carries the record's own reason, not a superseded sentence
            assert row["pyd_failure_reason"] == d["exclusion_reason"], stem
        seen[cls] = seen.get(cls, 0) + 1
    # every class the corpus holds is exercised by the table
    assert (seen.get("unread") and seen.get("models") and seen.get("stub_before_models")
            and seen.get("audited_unread_stub")), seen
