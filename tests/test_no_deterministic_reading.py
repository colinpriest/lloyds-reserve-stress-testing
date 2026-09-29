"""Round 62 (review of 29 September 2026, MAT-2): a record the parsers could not read says so, and says
the models were not run.

The reason these records carried -- "No claims development triangle or reserve movement text found
in report" -- stated a fact about the filing that the code only knew about its parsers: 2468/2022 and
2255/2015 print one-column triangles the structure check refused, and ten 2024 HTML filings print
tables their conversion had lost. process_one_report then skipped both models, and the record did
not say so. It now writes status "no_deterministic_reading", models_run false and a reason that
describes the parsers; a first-year stub says whether the models ran before it was written; and the
committed records carry the restated fields, except those listed for a new extraction.

Run:  python -m pytest tests/test_no_deterministic_reading.py -q
"""
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import test_gemini as tg  # noqa: E402
import restate_record_status as restate  # noqa: E402

#: an assertion about the filing that the code cannot make
ABSENCE = re.compile(r"no claims development triangle.{0,80}found in (the )?report", re.I)


@pytest.fixture
def no_reading_report(monkeypatch, tmp_path):
    """process_one_report on a report the RAG step could not read; any model call fails the test."""
    pdf = tmp_path / "syndicate_9999_2019.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%fixture\n")
    monkeypatch.setattr(tg, "extract_pyd_from_relevant_pages", lambda path, year: {
        "triangle": None, "pyd": None, "pyd_details": None, "pyd_from_triangle": False,
        "reserve_text": "", "method": "none", "cost": 0, "adobe_lob": None, "adobe_provisions": None,
        "first_year_syndicate": False, "first_year_reserve_text": False, "no_triangle_data": True,
        "relevant_pages": [], "rotated_pages": set()})

    def no_model(*a, **k):
        raise AssertionError("a model was called for a report with no deterministic reading")
    monkeypatch.setattr(tg, "extract_with_gemini", no_model)
    monkeypatch.setattr(tg, "extract_with_openai", no_model)
    monkeypatch.setattr(tg, "_save_inception_years", lambda inc: None)
    return pdf


def test_the_record_says_what_was_read_and_that_no_model_ran(no_reading_report):
    kind, rec = tg.process_one_report(no_reading_report, inception_cache={})
    assert kind == "no_triangle_data"
    assert rec["status"] == tg.NO_DETERMINISTIC_READING == "no_deterministic_reading"
    assert rec["models_run"] is False
    assert rec["no_triangle_data"] is True and rec["excluded"] is True   # the keys its readers use
    assert rec["exclusion_reason"] == tg.NO_DETERMINISTIC_READING_REASON
    assert "models" not in rec


def test_the_reason_describes_the_parsers_not_the_filing():
    reason = tg.NO_DETERMINISTIC_READING_REASON
    assert not ABSENCE.search(reason)
    assert "parsers" in reason and "not the filing" in reason and "models were not run" in reason
    assert reason.isascii()          # the driver writes records with ensure_ascii


def test_a_first_year_stub_says_whether_the_models_ran():
    before = tg._first_year_record(Path("syndicate_9999_2016.pdf"), 9999, 2016, {}, {9999: 2015}, set())
    assert before["models_run"] is False and before["reason"] == tg.FIRST_YEAR_REASON
    after = tg._first_year_record(Path("syndicate_9999_2016.pdf"), 9999, 2016, {}, {9999: 2015}, set(),
                                  evidence={"triangle_underwriting_years": {}}, models_run=True)
    assert after["models_run"] is True and after["first_year_evidence"]


def test_the_post_model_stub_is_written_with_models_run_true():
    src = Path(tg.__file__).read_text(encoding="utf-8")
    start = src.index("def process_one_report(")
    body = src[start:src.index("\ndef ", start + 10)] if "\ndef " in src[start + 10:] else src[start:]
    call = body[body.index("model_figures_not_stated"):]
    assert re.match(r'[^)]*\},\s*models_run=True\)', call, re.S), "the stub written after the models"


def _committed():
    for path in sorted((ROOT / "pdf_extraction").glob("syndicate_*_*.json")):
        parts = path.stem.split("_")
        if len(parts) == 3 and parts[1].isdigit() and parts[2].isdigit():
            yield path, json.loads(path.read_text(encoding="utf-8"))


def test_every_committed_unread_record_is_restated_or_listed_for_a_new_extraction():
    pending = restate.pending_stems()
    restated, waiting = [], []
    for path, d in _committed():
        if "models" in d or not d.get("no_triangle_data"):
            continue
        if path.stem in pending:
            waiting.append(path.stem)
            continue
        assert d.get("status") == tg.NO_DETERMINISTIC_READING, path.name
        assert d.get("models_run") is False, path.name
        assert d.get("exclusion_reason") == tg.NO_DETERMINISTIC_READING_REASON, path.name
        assert not ABSENCE.search(json.dumps(d)), path.name
        restated.append(path.stem)
    # round 62: the 13 waiting records were extracted again with the models on 29 September 2026
    # (12 now carry a figure, 1985/2024 became a first-year stub), so 45 are restated and none waits
    assert len(restated) == 45 and not waiting, (len(restated), waiting)


def test_the_restatement_is_complete_and_changes_nothing_else():
    """The script's own check mode: nothing left to restate, and it would verify any change."""
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "restate_record_status.py"), "--no-reading",
                        "--check"], capture_output=True, text=True, cwd=str(ROOT))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "0 to restate" in r.stdout, r.stdout


def test_every_committed_first_year_stub_carries_the_current_reason_and_models_run():
    """The stubs carried three generations of wording, ten of them the inception-year rule's, which
    round 58 removed (review of 29 September 2026, E-3). Each now says why it is a stub and whether
    the models ran."""
    audited = {r["file"]: r for r in json.loads(
        (ROOT / "pdf_extraction" / "audit" / "structural_eligibility_audit.json").read_text(encoding="utf-8"))["records"]}
    n = 0
    for path, d in _committed():
        if "models" in d or not d.get("first_year_syndicate"):
            continue
        n += 1
        assert d["models_run"] is bool(d.get("first_year_evidence")), path.name
        assert "Syndicate too new" not in d["reason"], path.name
        assert "within the first two underwriting years" not in d["reason"], path.name
        if d["reason"] != tg.FIRST_YEAR_REASON:
            # the inception-year rule's stubs: decided by the filing-page audit, and saying so
            assert audited[path.name]["decision"] == "structural_ineligible_no_mature_cohort", path.name
            assert "structural_eligibility_audit.json" in d["reason"], path.name
    # 69 before round 62's re-extraction; 1985/2024's triangle holds 2023-2024 only (filing p50)
    assert n == 70


def test_the_stub_restatement_is_complete():
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "restate_record_status.py"), "--first-year",
                        "--check"], capture_output=True, text=True, cwd=str(ROOT))
    assert r.returncode == 0 and "0 to restate" in r.stdout, r.stdout + r.stderr


def test_the_pending_list_is_what_the_committed_records_are_waiting_for():
    reg = json.loads((ROOT / "pdf_extraction" / "audit" / "redecision_pending.json").read_text(encoding="utf-8"))
    stems = [r["stem"] for r in reg["records"]]
    assert len(stems) == len(set(stems))
    records = dict((p.stem, d) for p, d in _committed())
    for r in reg["records"]:
        d = records[r["stem"]]
        # still in its committed, pre-round-62 form: the new extraction has not been made
        if r["committed"] == "no_triangle_data":
            assert d.get("no_triangle_data") and "status" not in d, r["stem"]
            assert ABSENCE.search(d["exclusion_reason"]), r["stem"]
        else:
            assert "models" in d, r["stem"]
        assert r["current_code_offline"], r["stem"]
