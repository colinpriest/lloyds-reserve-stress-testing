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
import build_coverage_status as bcs  # noqa: E402
import replay_corpus_check as rcc  # noqa: E402
import restate_record_status as restate  # noqa: E402

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


def _stub_rows():
    """(row, expected text, stem, restated by the audit) for every coverage row of a first-year stub. A stub the
    pipeline wrote says no eligible mature cohort and no stated prior-year development figure, which its rule tested;
    one the structural audit restated from an unread record says only what the audit read."""
    records = rcc.committed_records()
    for row in json.loads(COVERAGE.read_text(encoding="utf-8"))["rows"]:
        stem = "syndicate_%s_%s" % (row["syndicate"], row["year"])
        d = records.get(stem)
        if d is not None and row["exclusion_class"] == "first_year_syndicate":
            audited = d.get("reason") == restate.AUDITED_UNREAD_STUB_REASON
            special = d.get("reason") == restate.AUDITED_2357_REASON
            expected = (bcs.AUDITED_2357_ROW_REASON if special else
                        bcs.AUDITED_UNREAD_ROW_REASON if audited else bcs.FIRST_YEAR_ROW_REASON)
            yield row, expected, stem, audited


def test_a_stub_row_says_what_was_read_and_no_more_and_the_builder_writes_the_same():
    """Fourth cycle of round 62: the row text of the 24 unread filings the audit restated said "no stated prior-year
    development figure", which the audit had not looked for (it read the start statement, the development table and the
    opening balance; the parsers found no figure and the models were not run). The committed row is the builder's own
    output for its record, so a change to the text or to the rule that chooses it without a rebuild fails here."""
    counts = {True: 0, False: 0}
    for row, expected, stem, audited in _stub_rows():
        counts[audited] += 1
        assert row["pyd_failure_reason"] == expected and row["opening_failure_reason"] == expected, stem
        fresh = bcs.analyse_extraction(int(row["syndicate"]), int(row["year"]), None, None)   # a stub returns before any page is read
        assert fresh["pyd_failure_reason"] == expected and fresh["opening_failure_reason"] == expected, stem
        assert fresh["exclusion_class"] == "first_year_syndicate", stem
    assert counts == {True: 24, False: 69}, counts
    assert "no stated" not in bcs.AUDITED_UNREAD_ROW_REASON
    assert "did not look for a stated one" in bcs.AUDITED_UNREAD_ROW_REASON
    assert "inherited history remains unresolved" in bcs.AUDITED_UNREAD_ROW_REASON
    assert "no stated prior-year development figure" in bcs.FIRST_YEAR_ROW_REASON


def test_the_report_waterfall_keeps_the_24_apart_from_the_stubs_the_pipeline_wrote():
    lines = (ROOT / "syndicate_reports" / "coverage" / "coverage_report.md").read_text(encoding="utf-8").splitlines()

    def cells(prefix):
        (line,) = [l for l in lines if l.startswith("| " + prefix)]
        label, change, running = [c.strip() for c in line.strip().strip("|").split("|")]
        return label, int(change), int(running)

    before = cells("Less: not yet through extraction pipeline")
    pipeline = cells("Less: other legacy extraction stubs")
    audited = cells("Less: unread stubs reviewed by the structural audit")
    n = {True: 0, False: 0}
    for _, _, _, is_audited in _stub_rows():
        n[is_audited] += 1
    assert (pipeline[1], audited[1]) == (-n[False], -n[True]) == (-69, -24)
    assert pipeline[2] == before[2] + pipeline[1] and audited[2] == pipeline[2] + audited[1]
    assert "not sought" in audited[0] and "structural audit" in audited[0]
    assert "evidence varies" in pipeline[0] and "no stated" not in pipeline[0]


def test_2357_coverage_output_reports_unknown_scope_without_changing_class():
    """A legacy stub with no printed triangle must not assert that one was read."""
    from openpyxl import load_workbook

    rows = json.loads(COVERAGE.read_text(encoding="utf-8"))["rows"]
    row, = [r for r in rows if (r["syndicate"], r["year"]) == (2357, 2014)]
    fresh = bcs.analyse_extraction(2357, 2014, None, None)
    assert row["exclusion_class"] == fresh["exclusion_class"] == "first_year_syndicate"
    for key in ("pyd_failure_reason", "opening_failure_reason", "lob_failure_reason"):
        assert row[key] == fresh[key]
    assert "no claims development table" in fresh["pyd_failure_reason"]
    assert "mature outcome remain unresolved" in fresh["pyd_failure_reason"]
    assert "no LOB mix in the extraction stub" == fresh["lob_failure_reason"]
    book = load_workbook(ROOT / "syndicate_reports" / "coverage" / "coverage_status.xlsx", read_only=True)
    detail = book["syndicate_years"]
    rows = detail.iter_rows(values_only=True)
    header = {v: i for i, v in enumerate(next(rows))}
    all_rows = list(rows)
    matching = [r for r in all_rows if (r[header["syndicate"]], r[header["year"]]) == (2357, 2014)]
    assert len(matching) == 1
    for key in ("pyd_failure_reason", "opening_failure_reason", "lob_failure_reason"):
        assert matching[0][header[key]] == fresh[key]
    audited_keys = {(row["syndicate"], row["year"]) for row, _, _, audited in _stub_rows() if audited}
    audited_rows = [r for r in all_rows if (r[header["syndicate"]], r[header["year"]]) in audited_keys]
    assert len(audited_rows) == len(audited_keys) == 24
    for r in audited_rows:
        assert r[header["pyd_failure_reason"]] == bcs.AUDITED_UNREAD_ROW_REASON
        assert r[header["opening_failure_reason"]] == bcs.AUDITED_UNREAD_ROW_REASON
    steps = list(book["reconciliation"].iter_rows(values_only=True))
    assert sum(row[0] == bcs.LEGACY_STUB_WATERFALL_LABEL for row in steps) == 1
    assert sum(row[0] == bcs.AUDITED_UNREAD_WATERFALL_LABEL for row in steps) == 1
    book.close()
