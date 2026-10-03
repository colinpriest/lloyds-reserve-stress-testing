"""scripts/page_vision_calls.py buys the page-vision readings Colin authorised on 3 October 2026, and nothing else.

The calls themselves are a PC step (the filings and the key are not in a cloud checkout). These tests hold the script to the
census it serves, to the driver's own choice of pages, and to its guards, with the driver's RAG step stubbed.

Run:  python -m pytest tests/test_page_vision_calls.py -q
"""
import inspect
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import page_vision_calls as pvc  # noqa: E402

CENSUS = ROOT / "pdf_extraction" / "audit" / "stage2_triangle_census.json"


def test_the_records_are_the_censuss_refused_rag_figures_with_no_cached_vision():
    """Every record the census says keeps a refused triangle's figure because page vision has no cached entry is either
    called here or has its figure in the analysis register; no other record is called."""
    census = json.loads(CENSUS.read_text(encoding="utf-8"))
    stuck = {e["stem"] for e in census["entries"] if e["block"] == "rag_triangle" and e.get("vision_pages_cached") == []
             and any(r.get("source") == "rag_triangle" for r in e["routes"].values())}
    assert set(pvc.STEMS) | set(pvc.REGISTERED_ELSEWHERE) == stuck
    assert not set(pvc.STEMS) & set(pvc.REGISTERED_ELSEWHERE)
    assert len(pvc.STEMS) == 6


def test_the_pages_are_the_ones_the_rag_step_sends():
    tri = [(3, "Claims development gross of reinsurance"), (4, "Net claims development table"), (9, "gross")]
    assert pvc.vision_pages(tri) == [3]
    assert pvc.vision_pages([(5, "Gross and net claims development"), (6, "gross")]) == [5, 6]
    import test_gemini as tg
    src = inspect.getsource(tg.extract_pyd_from_relevant_pages)
    assert "for page_num, page_text in tri_pages[:2]:" in src, "the RAG step's page choice changed: change vision_pages"
    assert 'if "net" in page_text.lower() and "gross" not in page_text.lower():' in src


class _Driver:
    """The parts of test_gemini the script uses, with the RAG step returning a fixed cost and every other model call
    failing the test."""
    TRIANGLE_EXTRACT_PROMPT = "prompt {report_year}"

    def __init__(self, cost):
        self.cost, self.calls = cost, []

    def extract_text_from_pdf(self, pdf):
        return [(7, "claims development gross")], "stub"

    def find_relevant_pages(self, pages, year):
        return {"triangle_pages": pages, "reserve_pages": []}

    def _llm_cache_key(self, *a, **k):
        return "no-such-entry"

    def extract_pyd_from_relevant_pages(self, pdf, year):
        self.calls.append((pdf, year))
        return {"cost": self.cost, "method": "none", "pyd": None, "pyd_details": None}

    def extract_with_gemini(self, *a, **k):
        raise AssertionError("a document-level model call")

    extract_with_openai = extract_with_gemini


@pytest.fixture
def online(monkeypatch):
    monkeypatch.delenv("LLOYDS_EXTRACTION_OFFLINE", raising=False)
    monkeypatch.delenv("LLOYDS_ALLOW_TABLE_BACKEND_CALLS", raising=False)
    monkeypatch.setenv("GOOGLE_API_KEY", "not-a-key")


def test_the_spend_cap_stops_before_the_next_record(online, tmp_path):
    drv = _Driver(cost=0.6)
    rec = pvc.run(drv, pvc.STEMS, 1.0, pdf_for=lambda s: tmp_path / (s + ".pdf"), log_path=tmp_path / "log.json")
    assert len(drv.calls) == 2 and rec["spent_usd"] == pytest.approx(1.2)
    logged = json.loads((tmp_path / "log.json").read_text(encoding="utf-8"))
    assert [r["stem"] for r in logged["records"]] == pvc.STEMS[:2] and logged["records"][0]["pages"] == [7]


def test_every_record_is_called_within_the_cap(online, tmp_path):
    drv = _Driver(cost=0.01)
    pvc.run(drv, pvc.STEMS, 1.0, pdf_for=lambda s: tmp_path / (s + ".pdf"), log_path=tmp_path / "log.json")
    assert [int(y) for _, y in drv.calls] == [int(s.rsplit("_", 1)[1]) for s in pvc.STEMS]


@pytest.mark.parametrize("var,value", [("LLOYDS_EXTRACTION_OFFLINE", "1"), ("LLOYDS_ALLOW_TABLE_BACKEND_CALLS", "1"),
                                       ("GOOGLE_API_KEY", "")])
def test_the_run_refuses_offline_a_table_backend_call_or_no_key(online, monkeypatch, tmp_path, var, value):
    monkeypatch.setenv(var, value)
    drv = _Driver(cost=0.01)
    with pytest.raises(SystemExit):
        pvc.run(drv, pvc.STEMS, 1.0, pdf_for=lambda s: tmp_path / (s + ".pdf"), log_path=tmp_path / "log.json")
    assert drv.calls == [] and not (tmp_path / "log.json").exists()
