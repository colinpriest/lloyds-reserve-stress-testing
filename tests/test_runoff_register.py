"""Third cycle of round 62 (30 September 2026, D1): a run-off year is a year the filing says the syndicate is
in run-off, not a year with a premium at or below zero.

The loader treated a development figure with an adopted gross premium of exactly zero as a run-off year.
Eight more records carry a negative premium, and an independent review read their filings: 3623/2018 is a
live Beazley syndicate whose negative premium is a return premium under a reinsurance contract, and
5183/2024's filing puts its run-off at 1 January 2025. A premium sign is not a run-off test. The author's
rule (D1, option A, refined): a record whose development figure is kept and whose adopted premium is at or
below zero is a run-off year when its own filing states the syndicate is in run-off in that year.

`pdf_extraction/audit/runoff_register.json` records that reading for the nine records the rule concerns, with
the filing's own words, page and file hash. These tests hold the register to the records (which nine), to
its own verdicts, and to the filings (each quote is printed on the page it cites, in the file whose hash the
register holds).

Run:  python -m pytest tests/test_runoff_register.py -q
"""
import hashlib
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import finalize_structural_eligibility_audit as fin  # noqa: E402

REGISTER = ROOT / "pdf_extraction" / "audit" / "runoff_register.json"
#: what the filing's words say when they say the syndicate is in run-off or has ceased to write
RUNOFF_WORDS = re.compile(r"run-?\s?off|ceased (to )?(underwrit|trad|write)", re.I)
#: the verdicts, by the filings: three are not run-off years. 2255/2015 is ambiguous (it "continues to run-off
#: its portfolio of liabilities" and expects to "continue to write business"), 3623/2018 is a live syndicate
#: with a return premium and 5183/2024's run-off begins on 1 January 2025. A different verdict is the
#: author's decision, so it fails here.
NOT_IN_RUNOFF = {"syndicate_2255_2015", "syndicate_3623_2018", "syndicate_5183_2024"}


def _register():
    return json.loads(REGISTER.read_text(encoding="utf-8"))["records"]


def _committed():
    for path in sorted((ROOT / "pdf_extraction").glob("syndicate_*_*.json")):
        parts = path.stem.split("_")
        if len(parts) == 3 and parts[1].isdigit() and parts[2].isdigit():
            yield path.stem, json.loads(path.read_text(encoding="utf-8"))


def _with_a_premium_at_or_below_zero():
    """The records that carry a development figure and a gross premium reading at or below zero."""
    out = {}
    for stem, d in _committed():
        blocks = [m for m in (d.get("models") or {}).values() if isinstance(m, dict)]
        if any(m.get("prior_year_development_pct") is not None for m in blocks) and any(
                isinstance(m.get("gross_premiums_written_gbp_m"), (int, float)) and m["gross_premiums_written_gbp_m"] <= 0
                for m in blocks):
            out[stem] = blocks
    return out


def test_the_register_covers_every_record_with_a_development_figure_and_a_premium_at_or_below_zero():
    """Nine records, and the register has exactly them: a record that comes to carry a premium at or below
    zero with a development figure needs its filing read before it is treated either way."""
    found = _with_a_premium_at_or_below_zero()
    stems = [r["stem"] for r in _register()]
    assert len(stems) == len(set(stems)) == 9
    assert set(stems) == set(found), sorted(set(stems) ^ set(found))


def test_each_entry_states_its_premium_and_its_verdict_from_the_record_and_the_filing():
    found = _with_a_premium_at_or_below_zero()
    fields = {"stem", "syndicate", "year", "premium_adopted_gbp_m", "premium_currency", "in_runoff", "runoff_from",
              "source_file", "source_sha256", "source_page", "source_page_printed", "evidence", "other_statements", "note"}
    for r in _register():
        assert set(r) == fields, r["stem"]
        assert r["stem"] == "syndicate_%d_%d" % (r["syndicate"], r["year"])
        # the premium is the record's own, and both models agree on it
        readings = {m.get("gross_premiums_written_gbp_m") for m in found[r["stem"]]}
        currencies = {m.get("currency") for m in found[r["stem"]]}
        assert readings == {r["premium_adopted_gbp_m"]} and currencies == {r["premium_currency"]}, r["stem"]
        assert r["premium_adopted_gbp_m"] <= 0, r["stem"]
        assert isinstance(r["in_runoff"], bool) and r["evidence"].strip() and r["note"].strip(), r["stem"]
        assert (r["stem"] in NOT_IN_RUNOFF) is (not r["in_runoff"]), r["stem"]
        if r["in_runoff"]:
            # the filing says so, and says from when
            assert r["runoff_from"] and RUNOFF_WORDS.search(r["evidence"]), r["stem"]
        assert r["source_page"] >= 1 and r["source_page_printed"], r["stem"]
        assert re.fullmatch(r"[0-9a-f]{64}", r["source_sha256"]), r["stem"]
    assert sum(r["in_runoff"] for r in _register()) == 6


def test_each_quote_is_on_the_page_it_cites_in_the_file_with_that_hash():
    """Verbatim, white space aside; ' ... ' marks words left out. Needs the filings, which are not committed
    (the converted PDF stands for an HTML filing)."""
    present = [r for r in _register() if (ROOT / r["source_file"]).exists()]
    if not present:
        pytest.skip("source filings not present in this checkout")
    for r in present:
        source = ROOT / r["source_file"]
        assert hashlib.sha256(source.read_bytes()).hexdigest() == r["source_sha256"], r["stem"]
        texts = fin.page_texts(source)
        cited = [(r["source_page"], r["evidence"])] + [(s["page"], s["quote"]) for s in r["other_statements"]]
        for page, quote in cited:
            assert 1 <= page <= len(texts), (r["stem"], page)
            assert fin.quote_on_page(quote, texts[page - 1]), (r["stem"], page, quote)
