"""scripts/page_vision_calls.py was written for the page-vision readings Colin authorised on 3 October 2026. They were bought that day, and it buys
nothing more.

The calls were made by the PC launcher (the filings and the key are not in a cloud checkout). These tests hold the script's account of where each
record stands to the census, to the committed cache and to the driver's own choice of pages, and hold its guards: nothing may still be bought, and a
run with nothing to buy makes no call and writes no log. The driver's RAG step is stubbed.

Until the calls the script listed six records to buy, and the first test held that list to the census (`len(STEMS) == 6`). The calls changed the
committed state: four of the six are served, 1967/2014 has no page to send and 3622/2023 has an older response to the same prompt text. So STEMS is
empty (`len(STEMS) == 0`), and the first test holds the lists that say why each record the census still counts as stuck is not bought.

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
PENDING = ROOT / "pdf_extraction" / "audit" / "redecision_pending.json"
#: six synthetic records for the mechanism tests (the cap, the guards). They stand for nothing in the census, and the live list, STEMS, is empty
SIX = ["syndicate_9001_2014", "syndicate_9002_2015", "syndicate_9003_2016", "syndicate_9004_2017", "syndicate_9005_2018",
       "syndicate_9006_2019"]


def _census():
    return json.loads(CENSUS.read_text(encoding="utf-8"))


def _stuck(census):
    """The census's own count, `rag_refused_with_no_cached_vision_page`: the refused rag_triangle entries with no committed page-vision entry
    under the current prompt."""
    return {e["stem"] for e in census["entries"] if e["block"] == "rag_triangle" and e.get("vision_pages_cached") == []}


def _key(tg, monkeypatch, version, stem, page):
    """The driver's own cache key for the page prompt under `version` (it hashes the version with the prompt text)."""
    syn, year = (int(x) for x in stem.split("_")[1:])
    monkeypatch.setattr(tg, "PROMPT_VERSION", version)
    prompt = tg.TRIANGLE_EXTRACT_PROMPT.replace("{report_year}", str(year))
    return tg._llm_cache_key("gemini-2.5-flash", prompt, syn, year, page_num=page)


def test_the_records_are_the_censuss_refused_rag_figures_with_no_cached_vision():
    """Every record the census still counts as a refused triangle with no cached page-vision entry is named here with the reason it is not
    bought (or is one that may still be bought), and no other record is: a new stuck record that no list names fails this, and so does a
    list that names a record the census no longer counts."""
    census = _census()
    stuck = _stuck(census)
    assert len(stuck) == census["counts"]["rag_refused_with_no_cached_vision_page"]
    named = set(pvc.STEMS) | set(pvc.OLDER_RESPONSE) | set(pvc.NO_PAGE)
    assert named == stuck, sorted(named ^ stuck)
    # one reason for each, and none for the registered-elsewhere records
    assert len(pvc.STEMS) + len(pvc.OLDER_RESPONSE) + len(pvc.NO_PAGE) == len(named)
    assert not set(pvc.STEMS) & set(pvc.REGISTERED_ELSEWHERE)
    # nothing may still be bought: STEMS held six until the calls of 3 October 2026 (the committed state changed, and this followed it)
    assert len(pvc.STEMS) == 0


def test_each_reason_holds_in_the_census_and_in_the_cache(monkeypatch):
    """The reasons are checked, not only named: no triangle page in the census, an older response to the same prompt text in the cache (the older
    entry's key is what the driver computes for the older version and today's text, and the current version has none), the 12 bought pages in the
    cache under the current prompt, and the misread page cached and declared pending."""
    import test_gemini as tg
    current = tg.PROMPT_VERSION
    entry = {e["stem"]: e for e in _census()["entries"] if e["block"] == "rag_triangle"}
    cache = ROOT / "pdf_extraction" / "llm_cache"

    def cached(version, stem, page):
        return (cache / (_key(tg, monkeypatch, version, stem, page) + ".json")).exists()

    for stem in pvc.NO_PAGE:
        assert entry[stem]["reaches_page_vision"] is False and entry[stem]["vision_pages_walked"] == [], stem
    for stem, (page, version) in pvc.OLDER_RESPONSE.items():
        assert version != current, stem
        assert entry[stem]["vision_pages_walked"] == [page] and entry[stem]["vision_pages_cached"] == [], stem
        assert not cached(current, stem, page), stem
        assert cached(version, stem, page), stem
    for stem, pages in pvc.SERVED.items():
        for page in pages:
            assert cached(current, stem, page), (stem, page)
    assert (len(pvc.SERVED), sum(len(p) for p in pvc.SERVED.values())) == (11, 12), "docs/ocr-pipeline.md section 9.1: 12 pages of 11 records"
    pending = {r["stem"] for r in json.loads(PENDING.read_text(encoding="utf-8"))["records"]}
    for stem in pvc.MISREAD:
        assert stem in pending and entry[stem]["vision_pages_cached"] == pvc.SERVED[stem], stem
    assert set(pvc.REGISTERED_ELSEWHERE) <= set(pvc.SERVED), "their pages were bought as well"


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
    rec = pvc.run(drv, SIX, 1.0, pdf_for=lambda s: tmp_path / (s + ".pdf"), log_path=tmp_path / "log.json")
    assert len(drv.calls) == 2 and rec["spent_usd"] == pytest.approx(1.2)
    logged = json.loads((tmp_path / "log.json").read_text(encoding="utf-8"))
    assert [r["stem"] for r in logged["records"]] == SIX[:2] and logged["records"][0]["pages"] == [7]


def test_every_record_is_called_within_the_cap(online, tmp_path):
    drv = _Driver(cost=0.01)
    pvc.run(drv, SIX, 1.0, pdf_for=lambda s: tmp_path / (s + ".pdf"), log_path=tmp_path / "log.json")
    assert [int(y) for _, y in drv.calls] == [int(s.rsplit("_", 1)[1]) for s in SIX]


@pytest.mark.parametrize("var,value", [("LLOYDS_EXTRACTION_OFFLINE", "1"), ("LLOYDS_ALLOW_TABLE_BACKEND_CALLS", "1"),
                                       ("GOOGLE_API_KEY", "")])
def test_the_run_refuses_offline_a_table_backend_call_or_no_key(online, monkeypatch, tmp_path, var, value):
    monkeypatch.setenv(var, value)
    drv = _Driver(cost=0.01)
    with pytest.raises(SystemExit) as refused:
        pvc.run(drv, SIX, 1.0, pdf_for=lambda s: tmp_path / (s + ".pdf"), log_path=tmp_path / "log.json")
    assert pvc.NOTHING_TO_BUY not in str(refused.value), "refused for its own reason, not for want of a record"
    assert drv.calls == [] and not (tmp_path / "log.json").exists()


def test_with_nothing_to_buy_a_run_makes_no_call_and_writes_no_log(online, tmp_path):
    """The live list is empty. Run with every guard satisfied (online, no table-backend call, a key), the run still refuses, before the
    driver is touched: no call, and no log with a purpose that claims calls were made."""
    assert pvc.STEMS == []
    drv = _Driver(cost=0.01)
    with pytest.raises(SystemExit) as refused:
        pvc.run(drv, pvc.STEMS, 1.0, pdf_for=lambda s: tmp_path / (s + ".pdf"), log_path=tmp_path / "log.json")
    assert str(refused.value) == pvc.NOTHING_TO_BUY
    assert drv.calls == [] and not (tmp_path / "log.json").exists()


class _NoDriver:
    """Stands for test_gemini in sys.modules: any use of it other than the import machinery's own look-ups fails the test."""

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        raise AssertionError("the driver was used: " + name)


@pytest.mark.parametrize("argv", [[], ["--dry-run"], ["--max-cost", "5"]])
def test_the_command_with_nothing_to_buy_says_so_and_does_not_load_the_driver(online, monkeypatch, capsys, argv):
    monkeypatch.setitem(sys.modules, "test_gemini", _NoDriver())
    assert pvc.main(argv) is None
    assert capsys.readouterr().out.strip() == pvc.NOTHING_TO_BUY
