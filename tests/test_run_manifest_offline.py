"""An offline run calls no API, and its run-manifest entry says so (stage 2 PC follow-up, review of 3 October 2026).

write_run_manifest recorded the tokens and the cost of an offline run under "costs" with nothing to tell them from a
charge. They are not one: a run made with --offline reads cached responses, and its totals are the sums of what those
responses recorded when they were made. The five runs of 3 October 2026 (the dry run that stopped on 13 page-vision
cache misses and the four regeneration workers; the wrapper logs of all five show 0 network connection attempts) recorded
US$4.35 and 8.0 million tokens that way, and none was spend. An entry now carries "offline"; an offline run's costs also
carry "new_spend_usd": 0.0 and a "basis" that says what the totals are, and the five entries of that day carry the same
marks.

Run:  python -m pytest tests/test_run_manifest_offline.py -q
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import test_gemini as tg  # noqa: E402

STATS = {"total_found": 1065, "already_done": 0, "processed": 3, "passed": 3, "failed": 0, "errored": 0,
         "skipped_first_year": 0, "skipped_no_data": 0, "total_tokens": 123456, "total_cost": 1.23456}


def _written(tmp_path, monkeypatch, offline):
    """The entry write_run_manifest appends to a manifest in an empty directory, with LLOYDS_EXTRACTION_OFFLINE set or not."""
    monkeypatch.setattr(tg, "AUDIT_DIR", tmp_path)
    if offline:
        monkeypatch.setenv("LLOYDS_EXTRACTION_OFFLINE", "1")
    else:
        monkeypatch.delenv("LLOYDS_EXTRACTION_OFFLINE", raising=False)
    tg.write_run_manifest(dict(STATS))
    return json.loads((tmp_path / "run_manifest.json").read_text(encoding="utf-8"))["runs"][-1]


def test_an_offline_run_is_marked_and_its_cost_is_not_new_spend(tmp_path, monkeypatch):
    e = _written(tmp_path, monkeypatch, offline=True)
    assert e["offline"] is True
    assert e["costs"]["new_spend_usd"] == 0.0
    assert "no new spend" in e["costs"]["basis"] and "cached responses" in e["costs"]["basis"]
    # the totals themselves are kept as the writer always wrote them
    assert e["costs"]["total_tokens"] == 123456 and e["costs"]["total_cost_usd"] == 1.2346


def test_a_run_that_may_call_an_api_is_not_marked_offline(tmp_path, monkeypatch):
    e = _written(tmp_path, monkeypatch, offline=False)
    assert e["offline"] is False
    assert "new_spend_usd" not in e["costs"] and "basis" not in e["costs"]
    assert e["costs"]["total_cost_usd"] == 1.2346


def test_the_runs_of_3_october_2026_are_marked_offline_in_the_committed_manifest():
    runs = json.loads((ROOT / "pdf_extraction" / "audit" / "run_manifest.json").read_text(encoding="utf-8"))["runs"]
    day = [r for r in runs if r["run_id"].startswith("20261003")]
    assert len(day) >= 5, [r["run_id"] for r in day]
    for r in day:
        assert r["offline"] is True and r["costs"]["new_spend_usd"] == 0.0, r["run_id"]
    # from that day on every entry says whether it was offline, and an entry marked offline is marked in full
    assert all(isinstance(r.get("offline"), bool) for r in runs if r["run_id"] >= "20261003")
    for r in runs:
        if r.get("offline") is True:
            assert r["costs"].get("new_spend_usd") == 0.0 and r["costs"].get("basis"), r["run_id"]
