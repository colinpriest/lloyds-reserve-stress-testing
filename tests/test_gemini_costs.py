"""Gemini's thinking tokens are priced, in the cost a record carries and in the run's spend cap
(round 62, second cycle, 30 September 2026).

The whole-document Gemini call priced usage_metadata.prompt_token_count at the input rate and
candidates_token_count at the output rate. Gemini 2.5 returns its thinking tokens apart, in
thoughts_token_count, and bills them as output, so every Gemini cost the pipeline recorded ran low:
the twelve Gemini responses of the re-extraction of 29 September 2026 carried 76,473 thinking tokens
that no cost counted (pdf_extraction/audit/redecision_pending.json, extracted.cost). The spend cap
LLOYDS_MAX_RUN_COST_USD reads the same recorded totals, so it tripped late or not at all.

No model is called here. The Gemini client is a stand-in whose response carries a synthetic usage
object -- the installed SDK's own GenerateContentResponseUsageMetadata, so the field names are the
SDK's -- the response cache is neither read nor written, sockets are refused, and the rates are the
code's own table (test_gemini.PRICING); no rate is typed in this file.

Run:  python -m pytest tests/test_gemini_costs.py -q
"""
import ast
import json
import socket
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from google.genai import types

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import test_gemini as tg  # noqa: E402

MODEL = "gemini-2.5-flash"
PROMPT, RESPONSE, THINKING = 12_000, 1_000, 9_000


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("a test of the cost formula reached for the network")
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


def _usage(thinking):
    return types.GenerateContentResponseUsageMetadata(
        prompt_token_count=PROMPT, candidates_token_count=RESPONSE, thoughts_token_count=thinking,
        total_token_count=PROMPT + RESPONSE + (thinking or 0))


def _whole_document_call(monkeypatch, tmp_path, thinking):
    """extract_with_gemini with a stand-in client: what it records for one response."""
    calls = []

    class Models:
        def generate_content(self, **kwargs):
            calls.append("generate_content")
            return SimpleNamespace(text=json.dumps({"syndicate": 9999, "year": 2020}),
                                   usage_metadata=_usage(thinking))

    class Files:
        def upload(self, **kwargs):
            calls.append("upload")
            return SimpleNamespace(name="files/stand-in")

    class Client:
        def __init__(self, api_key=None):
            self.models, self.files = Models(), Files()

    saved = []
    monkeypatch.setattr(tg, "genai", SimpleNamespace(Client=Client))
    monkeypatch.setattr(tg, "_llm_lookup", lambda *a, **k: (None, False, None))
    monkeypatch.setattr(tg, "_llm_cache_save", lambda key, data, **k: saved.append(data))
    monkeypatch.setattr(tg, "_offline_guard", lambda what: None)   # the client is a stand-in
    report = tmp_path / "syndicate_9999_2020.pdf"
    report.write_bytes(b"%PDF-1.4\n%stand-in\n")
    data = tg.extract_with_gemini(report, report.read_bytes(), "stand-in-hash", 9999, 2020, model=MODEL)
    assert calls == ["upload", "generate_content"] and saved == [data]
    return data["_extraction_meta"]


def test_a_gemini_response_is_priced_with_its_thinking_tokens(monkeypatch, tmp_path):
    rates = tg.PRICING[MODEL]
    meta = _whole_document_call(monkeypatch, tmp_path, THINKING)
    assert meta["thinking_tokens"] == THINKING
    assert meta["cost_usd"] == round((PROMPT * rates["input"] + (RESPONSE + THINKING) * rates["output"]) / 1e6, 6)
    # the thinking tokens are billed at the output rate: exactly that much above a response without them
    without = _whole_document_call(monkeypatch, tmp_path, None)
    assert without["thinking_tokens"] == 0
    assert without["cost_usd"] == round((PROMPT * rates["input"] + RESPONSE * rates["output"]) / 1e6, 6)
    assert meta["cost_usd"] - without["cost_usd"] == pytest.approx(THINKING * rates["output"] / 1e6, abs=2e-6)


def test_the_spend_cap_trips_on_the_thinking_tokens(monkeypatch, tmp_path):
    """The run total the cap reads is the records' total_cost_usd, the sum of the two models' recorded
    costs. A cap set between the cost without the thinking tokens and the cost with them is reached
    only because they are now counted."""
    with_thinking = _whole_document_call(monkeypatch, tmp_path, THINKING)["cost_usd"]
    without = _whole_document_call(monkeypatch, tmp_path, 0)["cost_usd"]
    gpt = 0.0          # the other model's recorded cost; any value shifts both totals alike
    cap = (with_thinking + without) / 2 + gpt
    monkeypatch.setenv("LLOYDS_MAX_RUN_COST_USD", repr(cap))
    assert tg._spend_cap_reached(with_thinking + gpt) == (cap, True)
    assert tg._spend_cap_reached(without + gpt) == (cap, False)
    monkeypatch.delenv("LLOYDS_MAX_RUN_COST_USD")
    assert tg._spend_cap_reached(10 ** 6) == (0.0, False)          # no cap set: never reached


def test_the_driver_stops_on_the_cap_the_function_decides():
    """The driver's loop (the `__main__` block) asks _spend_cap_reached and keeps no copy of the rule:
    it reads LLOYDS_MAX_RUN_COST_USD nowhere else. Read from the syntax tree, so a comment cannot
    satisfy it."""
    tree = ast.parse(Path(tg.__file__).read_text(encoding="utf-8"))
    main = next(n for n in tree.body if isinstance(n, ast.If) and "__main__" in ast.dump(n.test))
    calls = [n for n in ast.walk(main) if isinstance(n, ast.Call)]
    assert any(isinstance(c.func, ast.Name) and c.func.id == "_spend_cap_reached" for c in calls)
    reads = [c for c in calls if isinstance(c.func, ast.Attribute) and c.func.attr == "getenv"
             and any(isinstance(a, ast.Constant) and a.value == "LLOYDS_MAX_RUN_COST_USD" for a in c.args)]
    assert reads == []


def test_the_readme_says_which_recorded_costs_leave_out_the_thinking_tokens():
    """Costs recorded before the change keep their old value, and nothing may rewrite them (the
    records and the audit files are as the analysis imported them), so the README says which ones
    leave the thinking tokens out, and points at the register's cost block, which counts them for
    the re-extraction of 29 September 2026."""
    flat = " ".join((ROOT / "README.md").read_text(encoding="utf-8").split())
    assert "Costs recorded before 30 September 2026, when `_gemini_cost_usd` came in, leave out Gemini's " \
           "thinking tokens" in flat
    assert "`_extraction_meta.cost_usd`" in flat and "`total_cost_usd`" in flat and "LLOYDS_MAX_RUN_COST_USD" in flat
    assert "the `extracted.cost` block of `pdf_extraction/audit/redecision_pending.json`" in flat
    cost = json.loads((ROOT / "pdf_extraction" / "audit" / "redecision_pending.json").read_text(
        encoding="utf-8"))["extracted"]["cost"]
    assert cost["gemini_tokens_not_priced"] > 0 and cost["page_vision_cost_usd"] == "not recorded"
