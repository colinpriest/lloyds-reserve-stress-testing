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

import pytest

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
    """Return each legacy stub's row and its independently audited expected scope."""
    records = rcc.committed_records()
    audit = json.loads((ROOT / "pdf_extraction" / "audit" / "structural_eligibility_audit.json").read_text(encoding="utf-8"))
    audited_records = {r["file"]: r for r in audit["records"]}
    for row in json.loads(COVERAGE.read_text(encoding="utf-8"))["rows"]:
        stem = "syndicate_%s_%s" % (row["syndicate"], row["year"])
        d = records.get(stem)
        if d is not None and row["exclusion_class"] == "first_year_syndicate":
            entry = audited_records.get(stem + ".json", {})
            audited = entry.get("extraction_status") == restate.UNREAD_RECORD_CONFIRMED
            special = stem == "syndicate_2357_2014"
            expected = (bcs.AUDITED_2357_ROW_REASON if special else
                        bcs.AUDITED_UNREAD_ROW_REASON if audited else
                        entry.get("review_note") or bcs.FIRST_YEAR_ROW_REASON)
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
    assert "consult the source filing" in bcs.FIRST_YEAR_ROW_REASON


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
    by_key = {(r[header["syndicate"]], r[header["year"]]): r for r in all_rows}
    for source_row, _, _, _ in _stub_rows():
        key = (source_row["syndicate"], source_row["year"])
        fresh_row = bcs.analyse_extraction(*key, None, None)
        for field in ("pyd_failure_reason", "opening_failure_reason", "lob_failure_reason"):
            assert by_key[key][header[field]] == fresh_row[field], (key, field)
    steps = list(book["reconciliation"].iter_rows(values_only=True))
    assert sum(row[0] == bcs.LEGACY_STUB_WATERFALL_LABEL for row in steps) == 1
    assert sum(row[0] == bcs.AUDITED_UNREAD_WATERFALL_LABEL for row in steps) == 1
    book.close()


def test_audit_backed_legacy_reasons_follow_actual_source_evidence():
    """A disclosed inherited cohort or unread outcome cannot become an absence claim."""
    checks = {
        (3268, 2019): ("UW2016", "not established"),
        (6124, 2015): ("quota share", "not established"),
        (1980, 2019): ("2014-2017", "not established"),
        (2786, 2016): ("inherited liabilities", "not been established"),
    }
    for key, phrases in checks.items():
        row = bcs.analyse_extraction(*key, None, None)
        assert row["exclusion_class"] == "first_year_syndicate"
        assert all(phrase in row["pyd_failure_reason"] for phrase in phrases), key
        assert "no stated prior-year development figure" not in row["pyd_failure_reason"]


def test_legacy_routing_uses_audit_identity_not_reason_prose(tmp_path, monkeypatch):
    """Edits to a stub's free-form reason cannot turn its uncertain evidence into an absence claim."""
    audit = tmp_path / "audit"
    audit.mkdir()
    (audit / "structural_eligibility_audit.json").write_bytes(
        (ROOT / "pdf_extraction" / "audit" / "structural_eligibility_audit.json").read_bytes())
    for syndicate, year in ((2357, 2014), (1686, 2014), (3268, 2019)):
        name = f"syndicate_{syndicate}_{year}.json"
        data = json.loads((ROOT / "pdf_extraction" / name).read_text(encoding="utf-8"))
        data["reason"] = "A benign edited reason unrelated to audit classification."
        (tmp_path / name).write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(bcs, "EXTRACTION_DIR", tmp_path)
    bcs.audited_stub_records.cache_clear()
    try:
        special = bcs.analyse_extraction(2357, 2014, None, None)
        unread = bcs.analyse_extraction(1686, 2014, None, None)
        mature = bcs.analyse_extraction(3268, 2019, None, None)
        assert special["pyd_failure_reason"] == bcs.AUDITED_2357_ROW_REASON
        assert unread["pyd_failure_reason"] == bcs.AUDITED_UNREAD_ROW_REASON
        assert "UW2016" in mature["pyd_failure_reason"]
        rows = json.loads(COVERAGE.read_text(encoding="utf-8"))["rows"]
        assert bcs.count_audited_unread_rows(rows) == 24
    finally:
        bcs.audited_stub_records.cache_clear()


def test_missing_or_invalid_audit_cannot_silently_claim_ineligibility(tmp_path, monkeypatch):
    data = json.loads((ROOT / "pdf_extraction" / "syndicate_2357_2014.json").read_text(encoding="utf-8"))
    (tmp_path / "syndicate_2357_2014.json").write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(bcs, "EXTRACTION_DIR", tmp_path)
    bcs.audited_stub_records.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="without the structural audit ledger"):
            bcs.analyse_extraction(2357, 2014, None, None)
        audit = tmp_path / "audit"
        audit.mkdir()
        (audit / "structural_eligibility_audit.json").write_text("not JSON", encoding="utf-8")
        with pytest.raises(RuntimeError, match="without the structural audit ledger"):
            bcs.analyse_extraction(2357, 2014, None, None)
        ledger = json.loads((ROOT / "pdf_extraction" / "audit" / "structural_eligibility_audit.json").read_text(encoding="utf-8"))
        ledger["records"] = [r for r in ledger["records"] if r["file"] != "syndicate_2357_2014.json"]
        ledger["counts"]["reviewed"] = len(ledger["records"])
        (audit / "structural_eligibility_audit.json").write_text(json.dumps(ledger), encoding="utf-8")
        with pytest.raises(RuntimeError, match="has no structural audit record"):
            bcs.analyse_extraction(2357, 2014, None, None)
    finally:
        bcs.audited_stub_records.cache_clear()


@pytest.mark.parametrize("mutation", ["missing_status", "unknown_status", "wrong_status", "wrong_decision"])
def test_malformed_audited_status_cannot_silently_change_rows_or_waterfall(tmp_path, monkeypatch, mutation):
    """A real unread record must not become an ordinary stub through a damaged audit."""
    name = "syndicate_1686_2014.json"
    (tmp_path / name).write_bytes((ROOT / "pdf_extraction" / name).read_bytes())
    audit_dir = tmp_path / "audit"
    audit_dir.mkdir()
    ledger = json.loads((ROOT / "pdf_extraction" / "audit" / "structural_eligibility_audit.json").read_text(encoding="utf-8"))
    record = next(r for r in ledger["records"] if r["file"] == name)
    if mutation == "missing_status":
        record.pop("extraction_status")
    elif mutation == "unknown_status":
        record["extraction_status"] = "unsupported_status"
    elif mutation == "wrong_status":
        record["extraction_status"] = "pre_model_stub_audited_no_disclosed_mature_diagonal"
    else:
        record["decision"] = "eligible_observed_zero"
    (audit_dir / "structural_eligibility_audit.json").write_text(json.dumps(ledger), encoding="utf-8")
    monkeypatch.setattr(bcs, "EXTRACTION_DIR", tmp_path)
    bcs.audited_stub_records.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="without the structural audit ledger"):
            bcs.analyse_extraction(1686, 2014, None, None)
        with pytest.raises(RuntimeError, match="without the structural audit ledger"):
            bcs.count_audited_unread_rows([{"syndicate": 1686, "year": 2014,
                                           "exclusion_class": "first_year_syndicate"}])
    finally:
        bcs.audited_stub_records.cache_clear()
