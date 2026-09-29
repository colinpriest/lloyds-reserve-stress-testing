"""Replay the deterministic step of every committed record from its own caches, and compare (round 62).

Why this exists (review of 29 September 2026, MAT-2 and R7-02): 1884/2022 and 3330/2018 were written
by code the round-56 workers had loaded before a rule landed, and the catch-up that followed measured
only records that carried a stored RAG triangle -- which these two, emptied by the old rule, did not.
Nothing compared the committed corpus with what the current code does on the committed caches, so
two records sat for a fortnight in a form no code would write. A run cannot certify its own scope;
this check compares every record, stubs and unread records included, with an offline replay.

For each committed record the RAG step (test_gemini.extract_pyd_from_relevant_pages) is replayed
offline (LLOYDS_EXTRACTION_OFFLINE=1: a cache miss is an error, never a call) and compared with the
record's deterministic content:
  * its class: an unread record must replay unread; a stub written before the models must replay as
    first-year; every other record must reach the models;
  * a figure the record took from the RAG step (route rag_*) must be the replay's figure and route;
  * a stored RAG triangle must be the replay's (underwriting years).
Declared exceptions: the records in pdf_extraction/audit/redecision_pending.json, which the current
code decides differently and which wait for the models, and those in offline_unservable.json, which
have no usable table cache. A declared record that now matches is reported too (the declaration is
stale).

Separately, every unread record's cached table grids are parsed: none may hold a gross triangle with
a usable cohort that yields a figure, unless the record is declared.

    python scripts/replay_corpus_check.py [--workers N] [--stems a,b,...] [--write]

--write records the full run in pdf_extraction/audit/corpus_replay_check.json, with the hashes of
the code it ran and of the record content it compared, which tests/test_corpus_replay.py holds to
the current code and records: a record extracted again after the run needs a new run. Exit 1 on any
undeclared mismatch or stale declaration. The full corpus takes about a quarter of an hour on 14
workers; the source filings are needed (they are not committed).
"""
from __future__ import annotations

import argparse
import contextlib
import datetime
import hashlib
import io
import json
import os
import sys
from multiprocessing import Pool
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "pdf_extraction" / "audit" / "corpus_replay_check.json"
PENDING = ROOT / "pdf_extraction" / "audit" / "redecision_pending.json"
UNSERVABLE = ROOT / "pdf_extraction" / "audit" / "offline_unservable.json"
CODE = ("test_gemini.py", "table_extraction.py")

_tg = _te = None


def code_hashes() -> dict:
    """sha256 of each pipeline source with line endings normalised, as a clone of any platform has it."""
    return {name: hashlib.sha256((ROOT / name).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
            for name in CODE}


def committed_records() -> dict:
    out = {}
    for path in sorted((ROOT / "pdf_extraction").glob("syndicate_*_*.json")):
        parts = path.stem.split("_")
        if len(parts) == 3 and parts[1].isdigit() and parts[2].isdigit():
            out[path.stem] = json.loads(path.read_text(encoding="utf-8"))
    return out


def declared() -> tuple[set, set]:
    pending = {r["stem"] for r in json.loads(PENDING.read_text(encoding="utf-8"))["records"]} if PENDING.exists() else set()
    unservable = set()
    if UNSERVABLE.exists():
        unservable = set(json.loads(UNSERVABLE.read_text(encoding="utf-8")).get("no_usable_cache_not_attempted") or [])
    return pending, unservable


def _init():
    global _tg, _te
    os.environ["LLOYDS_EXTRACTION_OFFLINE"] = "1"
    os.environ.pop("LLOYDS_ALLOW_TABLE_BACKEND_CALLS", None)
    os.chdir(ROOT)
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    import table_extraction as te
    import test_gemini as tg
    _tg, _te = tg, te


def _filing(stem: str):
    for ext in (".pdf", ".html", ".htm"):
        p = Path("syndicate_reports") / "pdfs" / (stem + ext)
        if (ROOT / p).exists():
            return p
    return None


def replay(stem: str) -> dict:
    """The RAG step's outcome for one filing, offline."""
    if _tg is None:
        _init()
    tg = _tg
    year = int(stem.split("_")[2])
    path = _filing(stem)
    if path is None:
        return {"stem": stem, "error": "source filing not present"}
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            actual = tg.convert_html_to_pdf(path) if path.suffix.lower() in (".html", ".htm") else path
            res = tg.extract_pyd_from_relevant_pages(actual, year)
    except Exception as exc:  # a cache miss, a refused conversion: the record cannot be replayed
        return {"stem": stem, "error": "%s: %s" % (type(exc).__name__, str(exc)[:300])}
    tri = res.get("triangle") or {}
    return {"stem": stem, "pyd": res.get("pyd"), "method": res.get("method"),
            "pyd_from_triangle": bool(res.get("pyd_from_triangle")),
            "first_year": bool(res.get("first_year_syndicate")),
            "first_year_reserve_text": bool(res.get("first_year_reserve_text")),
            "no_triangle_data": bool(res.get("no_triangle_data")),
            "triangle_years": [int(y) for y in (tri.get("underwriting_years") or [])]}


def committed_class(d: dict) -> str:
    if d.get("no_triangle_data"):
        return "unread"
    if d.get("first_year_syndicate") and "models" not in d:
        return "stub_after_models" if d.get("first_year_evidence") else "stub_before_models"
    if "source-page-audit" in (d.get("models") or {}):
        return "reviewed_audit"
    return "models"


def replay_class(x: dict) -> str:
    if "error" in x:
        return "error"
    if x["first_year"] and not x["first_year_reserve_text"]:
        return "stub_before_models"
    if x["no_triangle_data"]:
        return "unread"
    return "models"


EXPECTED = {"unread": {"unread"}, "stub_before_models": {"stub_before_models"},
            "stub_after_models": {"models"}, "models": {"models"},
            "reviewed_audit": {"stub_before_models"}}


def compare(d: dict, x: dict) -> list:
    """The ways the replay differs from the committed record's deterministic content."""
    cc, rc = committed_class(d), replay_class(x)
    if rc not in EXPECTED[cc]:
        return ["class: committed %s, replay %s%s" % (cc, rc, (" (%s)" % x["error"][:120]) if rc == "error" else
                                                     (" (figure %s, %s)" % (x.get("pyd"), x.get("method"))))]
    out = []
    if cc == "models":
        for name, block in d["models"].items():
            route = block.get("_pyd_route") or {}
            src = str(route.get("source") or "")
            if src.startswith("rag_"):
                meth = src[4:]
                same_value = x["pyd"] is not None and abs(float(x["pyd"]) - float(route.get("value"))) < 5e-4
                same_route = (meth == "triangle" and x["pyd_from_triangle"]) or meth == x["method"]
                if not (same_value and same_route):
                    out.append("%s: route %s %s, replay %s %s" % (name, src, route.get("value"), x["method"], x["pyd"]))
        stored = next((b.get("_rag_triangle") for b in d["models"].values() if b.get("_rag_triangle")), None)
        if stored and [int(y) for y in stored.get("underwriting_years") or []] != x["triangle_years"]:
            out.append("stored RAG triangle %s, replay %s" % (stored.get("underwriting_years"), x["triangle_years"]))
    return out


def compared_content(d: dict) -> dict:
    """What compare() reads of a committed record: its class, the figures it took from the RAG step,
    and its stored RAG triangle's years."""
    cc = committed_class(d)
    out = {"class": cc}
    if cc == "models":
        routes = {}
        for name, block in d["models"].items():
            route = block.get("_pyd_route") or {}
            if str(route.get("source") or "").startswith("rag_"):
                routes[name] = [str(route.get("source")), route.get("value")]
        stored = next((b.get("_rag_triangle") for b in d["models"].values() if b.get("_rag_triangle")), None)
        out["rag_routes"] = routes
        out["rag_triangle_years"] = [int(y) for y in stored.get("underwriting_years") or []] if stored else None
    return out


def records_hash(records: dict) -> str:
    """sha256 of every record's compared content: a record extracted again after the full run changes
    it, and the run no longer describes the corpus (a run cannot certify records written after it)."""
    blob = json.dumps({s: compared_content(d) for s, d in sorted(records.items())}, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def usable_gross_grids(stem: str) -> list:
    """Cached table grids of a filing that parse as a gross triangle with a usable cohort and yield a
    figure: what an unread record must not hold."""
    if _tg is None:
        _init()
    tg, te = _tg, _te
    cache = ROOT / "pdf_extraction" / "azure_output" / (stem + "_azure.json")
    if not cache.exists():
        return []
    year = int(stem.split("_")[2])
    data = json.loads(cache.read_text(encoding="utf-8"))
    tables = data.get("tables") if isinstance(data, dict) else data
    found = []
    for i, t in enumerate(tables or []):
        grid = t.get("grid") if isinstance(t, dict) else None
        if not isinstance(grid, list):
            continue
        res, _ = te._parse_nutrient_triangle(grid, year)
        if not isinstance(res, te.TriangleData) or res.type != "gross":
            continue
        if not any(int(y) <= year - te.PYD_EXCLUDED_RECENT_UW_YEARS for y in res.underwriting_years):
            continue
        pyd, _ = tg.compute_pyd_from_triangle(res.to_dict(), year)
        if pyd is not None:
            found.append({"table": i, "years": [int(y) for y in res.underwriting_years], "pyd": pyd})
    return found


def check(stems=None, workers=1) -> dict:
    records = committed_records()
    stems = sorted(stems or records)
    pending, unservable = declared()
    if workers > 1:
        with Pool(workers, initializer=_init) as pool:
            replays = {x["stem"]: x for x in pool.imap_unordered(replay, stems, chunksize=1)}
    else:
        replays = {s: replay(s) for s in stems}
    undeclared, declared_seen, stale, by_class = [], [], [], {}
    for s in stems:
        d, x = records[s], replays[s]
        diffs = compare(d, x)
        key = "%s -> %s" % (committed_class(d), replay_class(x))
        by_class[key] = by_class.get(key, 0) + 1
        if s in pending or s in unservable:
            if diffs:
                declared_seen.append({"stem": s, "differs": diffs})
            else:
                stale.append(s)
        elif diffs:
            undeclared.append({"stem": s, "differs": diffs})
    grids = []
    for s in stems:
        if committed_class(records[s]) == "unread" and s not in pending:
            g = usable_gross_grids(s)
            if g:
                grids.append({"stem": s, "grids": g})
    return {"n_records": len(records), "n_replayed": len(stems), "records_sha256": records_hash(records),
            "by_class": dict(sorted(by_class.items())),
            "undeclared_mismatches": undeclared, "stale_declarations": stale,
            "declared_mismatches": declared_seen,
            "unread_records_with_a_usable_gross_grid": grids}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--stems", default="")
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    stems = [s for s in args.stems.split(",") if s] or None
    result = check(stems, args.workers)
    pending, unservable = declared()
    report = {
        "purpose": ("Every committed record compared with an offline replay of the deterministic step on its "
                    "own caches (scripts/replay_corpus_check.py); the code it ran is hashed."),
        "recorded": datetime.date.today().isoformat(),
        "code_sha256_lf": code_hashes(),
        "declared_pending": sorted(pending),
        "declared_unservable": sorted(unservable),
        **result,
    }
    print(json.dumps({k: report[k] for k in ("n_records", "n_replayed", "by_class")}, indent=1))
    for key in ("undeclared_mismatches", "stale_declarations", "unread_records_with_a_usable_gross_grid"):
        print("%s: %d" % (key, len(report[key])))
        for row in report[key][:40]:
            print("   ", row)
    if args.write:
        if stems:
            raise SystemExit("--write records a full run only")
        REPORT.write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8", newline="\n")
        print("wrote", REPORT)
    bad = report["undeclared_mismatches"] or report["stale_declarations"] or report["unread_records_with_a_usable_gross_grid"]
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
