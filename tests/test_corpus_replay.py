"""Round 62 (review of 29 September 2026, MAT-2, R7-02 and test upgrade 2): every committed record is
what the current code produces from its own caches.

1884/2022 and 3330/2018 sat for a fortnight as records no current code would write: the replay that
followed a rule change covered only the records that still carried a triangle. These tests hold the
corpus to an offline replay of the deterministic step (scripts/replay_corpus_check.py):

  * the committed full run (pdf_extraction/audit/corpus_replay_check.json) is of the current code and
    records -- its hashes are this tree's test_gemini.py and table_extraction.py and the content the
    check compared in every committed record -- and found no undeclared mismatch, no stale
    declaration and no unread record holding a usable gross triangle;
  * a documented subset (SUBSET below) is replayed here, in the default suite (the full corpus takes
    about a quarter of an hour on 14 workers, so it is the script's job, not the suite's);
  * no unread record's cached grids hold a gross triangle with a usable cohort that yields a figure,
    unless it is waiting for the models (redecision_pending.json).

Run:  python -m pytest tests/test_corpus_replay.py -q
      python scripts/replay_corpus_check.py --workers 14 --write      (the full run)
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import replay_corpus_check as rcc  # noqa: E402

#: The subset replayed by default: the review's named records, declared records, and stubs, unread
#: records and models records spread across the corpus, each of whose replays took at most three
#: seconds in the round-62 full run (a scanned filing's OCR rotation pass takes half a minute).
SUBSET = sorted(set("""
syndicate_2468_2022 syndicate_1884_2022 syndicate_3330_2018 syndicate_4747_2024 syndicate_1902_2024
syndicate_2689_2024 syndicate_2880_2024 syndicate_4242_2024 syndicate_1840_2022
syndicate_1884_2016 syndicate_1206_2019 syndicate_5820_2019
syndicate_1084_2020 syndicate_1183_2023 syndicate_1218_2024 syndicate_1400_2014 syndicate_1492_2021
syndicate_1274_2014 syndicate_1347_2023 syndicate_1609_2021
syndicate_1699_2022 syndicate_1975_2019 syndicate_2232_2024 syndicate_3622_2018 syndicate_1922_2024
syndicate_1322_2023 syndicate_1416_2022 syndicate_1609_2022 syndicate_1618_2022 syndicate_1699_2023
syndicate_1840_2020 syndicate_1971_2020 syndicate_1980_2019 syndicate_2019_2021
syndicate_2358_2022 syndicate_5886_2018 syndicate_6131_2019
""".split()))


def _report():
    return json.loads(rcc.REPORT.read_text(encoding="utf-8"))


def test_the_committed_full_replay_is_of_this_code_and_found_nothing_undeclared():
    assert rcc.REPORT.exists(), "run: python scripts/replay_corpus_check.py --workers 14 --write"
    rep = _report()
    assert rep["code_sha256_lf"] == rcc.code_hashes(), (
        "the pipeline code changed after the full replay: run scripts/replay_corpus_check.py --write again")
    records = rcc.committed_records()
    assert rep["records_sha256"] == rcc.records_hash(records), (
        "a committed record changed after the full replay: run scripts/replay_corpus_check.py --write again")
    assert rep["n_records"] == rep["n_replayed"] == len(records)
    assert rep["undeclared_mismatches"] == [], rep["undeclared_mismatches"][:5]
    assert rep["stale_declarations"] == []
    assert rep["unread_records_with_a_usable_gross_grid"] == []
    pending, unservable = rcc.declared()
    assert rep["declared_pending"] == sorted(pending) and rep["declared_unservable"] == sorted(unservable)
    # every declared record did differ, and nothing else did
    assert {d["stem"] for d in rep["declared_mismatches"]} == pending | unservable


def test_a_replay_of_the_subset_is_the_committed_corpus():
    have = [s for s in SUBSET if rcc._filing(s) is not None]
    if not have:
        pytest.skip("source filings not present in this checkout")
    result = rcc.check(have, workers=4)
    assert result["undeclared_mismatches"] == [], result["undeclared_mismatches"]
    assert result["stale_declarations"] == [], result["stale_declarations"]


def test_no_unread_record_holds_a_usable_gross_triangle_in_its_cache():
    """Committed caches only, so this runs in any checkout. The check must be able to find one: the
    one-column triangle 2468/2022's committed Azure cache holds (UW2020, -0.153m) is found."""
    control = rcc.usable_gross_grids("syndicate_2468_2022")
    assert any(g["years"] == [2020] and g["pyd"] == pytest.approx(-0.153, abs=5e-4) for g in control), control
    pending, _ = rcc.declared()
    found = []
    for stem, d in rcc.committed_records().items():
        if rcc.committed_class(d) == "unread" and stem not in pending:
            g = rcc.usable_gross_grids(stem)
            if g:
                found.append((stem, g))
    assert found == []


def test_the_one_column_triangle_of_2468_2022_is_read_and_its_record_accounted_for():
    """The current code reads 2468/2022's one-column triangle (-0.153m, from the Azure grid). Its
    committed record is either declared as waiting for the models, and then still differs from the
    replay -- a rule that stopped reading it would show here -- or not declared, and then is exactly
    what the replay gives."""
    if rcc._filing("syndicate_2468_2022") is None:
        pytest.skip("source filings not present in this checkout")
    x = rcc.replay("syndicate_2468_2022")
    assert x["pyd"] == pytest.approx(-0.153, abs=5e-4) and x["method"] == "azure"
    d = rcc.committed_records()["syndicate_2468_2022"]
    pending, _ = rcc.declared()
    if "syndicate_2468_2022" in pending:
        assert rcc.compare(d, x), "the committed record already equals the replay: update the pending list"
    else:
        assert rcc.compare(d, x) == [], "the committed record is not what the current code writes"
