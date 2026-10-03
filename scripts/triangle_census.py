"""The triangle census of the diagonal check (review of 2 October 2026, M-1; stage 2 of the fix cycle).

compute_pyd_from_triangle took each mature column's last filled cell as its current estimate, wherever the
cell lay. Since stage 2 it places the current estimate on the report-year diagonal, checks it against the
table's printed current-estimate row where the table has one, and refuses a grid it cannot place
(test_gemini._diagonal_cells). This script runs the reader before and after that change over every committed
triangle, on the same inputs, and lists each one whose figure changes or is refused:

  * the RAG triangle of each record (`_rag_triangle`, the table step's grid; one per record), read as
    committed and, where the committed Azure cache re-parses to the same grid, with the printed
    current-estimate row the parser now keeps, which is what an offline replay of the record will see;
  * each model's own triangle (`_claims_triangle`), which verify_triangles recomputes (the code_triangle
    route).

For each RAG triangle the new reader refuses, the census says what an offline replay will then do. It walks the
page-vision step with the pipeline's own code, the call that renders and sends a page replaced by a recorder
(`walk_page_vision`; it needs the filings, a PC step): the step passes to page vision only if the text-based page
finder selects a triangle page, and reaches none for 1967/2014 (its filing prints no claims development table) and
1991/2018 (its gross triangle, on PDF page 30, matches one of the finder's patterns where two are needed); such a
record, with no figure from the later routes and no reserve text, would be written as no deterministic reading.
Where a page is reached, page vision is served by the replay only from a committed page-level cache entry under the
current prompt. With none, the call is a cache miss, the replay stops for that record and the committed record keeps
its figure until the call is made (a paid step). With one, the census reads the served triangle with the new reader
too (`vision_outcomes`): where it refuses that as well, the record falls to the later routes with no call (3334/2017
and 3500/2018, whose figures are the models' readings already); where it accepts it, that is the figure, right or wrong
(2999/2022's served reading is the page's table shifted one column, and gives +858.1 where the page gives +370.5).

The records are not regenerated here (a PC step); tests/test_triangle_diagonal.py holds the census to the
reader and the committed records, so the census has to be written again when either changes.

Usage:
    python scripts/triangle_census.py                     # print the census
    python scripts/triangle_census.py --write             # write pdf_extraction/audit/stage2_triangle_census.json
    python scripts/triangle_census.py --before <rev>      # the reader before the change (default f4fdf559)
"""
import argparse
import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("LLOYDS_EXTRACTION_OFFLINE", "1")
import table_extraction as te  # noqa: E402
import test_gemini as tg  # noqa: E402

OUT = ROOT / "pdf_extraction" / "audit" / "stage2_triangle_census.json"
AZURE = ROOT / "pdf_extraction" / "azure_output"
BEFORE = "f4fdf559"
RECORD = re.compile(r"^syndicate_(\d+)_(\d{4})$")


def records():
    """[(stem, syndicate, year, record)] for every committed extraction record."""
    out = []
    for path in sorted((ROOT / "pdf_extraction").glob("syndicate_*_[0-9][0-9][0-9][0-9].json")):
        m = RECORD.match(path.stem)
        if m:
            out.append((path.stem, int(m.group(1)), int(m.group(2)),
                        json.loads(path.read_text(encoding="utf-8"))))
    return out


def fingerprint(grid):
    return hashlib.sha256(json.dumps(grid, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def blocks(rec):
    """[(block name, triangle dict, the record's route for it)]: the one RAG grid, then each model's triangle."""
    out, seen = [], set()
    models = rec.get("models") or {}
    for model, b in models.items():
        t = b.get("_rag_triangle")
        if isinstance(t, dict) and t.get("development_rows"):
            key = json.dumps(t, sort_keys=True)
            if key not in seen:
                seen.add(key)
                out.append(("rag_triangle", t, {m: (bb.get("_pyd_route") or {}) for m, bb in models.items()}))
    for model, b in models.items():
        t = b.get("_claims_triangle")
        if isinstance(t, dict) and t.get("development_rows") and t.get("type") not in ("none", None):
            out.append(("claims_triangle:" + model, t, {model: (b.get("_pyd_route") or {})}))
    return out


def read(reader, tri, year):
    """(value, None) or (None, reason)."""
    try:
        v, why = reader(copy.deepcopy(tri), year)
    except Exception as exc:  # the reader never raised on a committed grid; say so if it starts to
        return None, "raised %s: %s" % (type(exc).__name__, exc)
    return (v, None) if v is not None else (None, why)


def printed_row(stem, year, tri):
    """The printed current-estimate row the parser now keeps, from the committed Azure cache table that
    re-parses to the committed grid, or None."""
    path = AZURE / ("%s_azure.json" % stem)
    if not path.exists():
        return None
    try:
        cache = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    for entry in cache.get("tables", []):
        res, _ = te._parse_nutrient_triangle(entry.get("grid") or [], year)
        if isinstance(res, te.TriangleData) and res.underwriting_years == tri.get("underwriting_years") \
                and res.development_rows == tri.get("development_rows"):
            return res.current_estimate_row
    return None


_PAGE_KEYS = None


def cached_vision_pages(syndicate, year):
    """The pages whose page-vision triangle the offline replay can serve: the committed page-level entries
    for the filing whose cache key is the one the current prompt makes."""
    global _PAGE_KEYS
    if _PAGE_KEYS is None:
        _PAGE_KEYS = {}
        for path in (ROOT / "pdf_extraction" / "llm_cache").glob("*.json"):
            try:
                meta = json.loads(path.read_text(encoding="utf-8")).get("_cache_meta") or {}
            except (OSError, ValueError):
                continue
            page = meta.get("page", meta.get("page_num"))
            if page is not None:
                _PAGE_KEYS.setdefault((meta.get("syndicate"), meta.get("year")), []).append((page, path.stem))
    prompt = tg.TRIANGLE_EXTRACT_PROMPT.replace("{report_year}", str(year))
    out = []
    for page, key in sorted(_PAGE_KEYS.get((syndicate, year), [])):
        if tg._llm_cache_key("gemini-2.5-flash", prompt, syndicate, year, page_num=page) == key:
            out.append(page)
    return out


def served_vision(syndicate, year, page):
    """The page-vision triangle the offline replay serves for a page: the committed entry under the current prompt's
    key, or None."""
    prompt = tg.TRIANGLE_EXTRACT_PROMPT.replace("{report_year}", str(year))
    path = ROOT / "pdf_extraction" / "llm_cache" / (
        tg._llm_cache_key("gemini-2.5-flash", prompt, syndicate, year, page_num=page) + ".json")
    try:
        data = json.loads(path.read_text(encoding="utf-8")).get("data")
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def vision_outcomes(syndicate, year, pages):
    """{page: the reader's outcome on the served page-vision triangle} (review of the stage-2 branch, F4: the census
    said the replay serves these pages, and the reader refuses what they hold too)."""
    out = {}
    for page in pages:
        tri = served_vision(syndicate, year, page)
        out[str(page)] = _outcome(*read(tg.compute_pyd_from_triangle, tri, year)) if tri else {
            "refused": "the served entry holds no triangle"}
    return out


def filing_path(stem):
    for ext in (".pdf", ".html", ".htm"):
        p = ROOT / "syndicate_reports" / "pdfs" / (stem + ext)
        if p.exists():
            return p
    return None


def walk_page_vision(stem, year):
    """(the pages the page-vision step would send for this filing, and what the RAG step ends with if no page returns a triangle), or None
    when the filing is not in this checkout. It is the pipeline's own walk (test_gemini.extract_pyd_from_relevant_pages, offline, on the
    committed caches) with the call that renders a page and sends it replaced by a recorder: nothing is rendered or sent, and a page that is
    cached is walked like one that is not."""
    path = filing_path(stem)
    if path is None:
        return None
    seen = []

    def recorder(pdf_path, page_num, report_year, model="gemini-2.5-flash"):
        seen.append(int(page_num))
        return None, 0

    real = tg.extract_triangle_from_page
    tg.extract_triangle_from_page = recorder
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            actual = tg.convert_html_to_pdf(path) if path.suffix.lower() in (".html", ".htm") else path
            res = tg.extract_pyd_from_relevant_pages(actual, year)
    finally:
        tg.extract_triangle_from_page = real
    return sorted(set(seen)), {"pyd": res.get("pyd"), "method": res.get("method"), "no_triangle_data": bool(res.get("no_triangle_data"))}


def reader_at(rev):
    """compute_pyd_from_triangle as it was at `rev`, imported from that commit's test_gemini.py."""
    src = subprocess.run(["git", "-C", str(ROOT), "show", "%s:test_gemini.py" % rev], capture_output=True,
                         text=True, encoding="utf-8", check=True).stdout
    tmp = Path(tempfile.mkdtemp()) / "test_gemini_before.py"
    tmp.write_text(src, encoding="utf-8")
    spec = importlib.util.spec_from_file_location("test_gemini_before", tmp)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.compute_pyd_from_triangle


def _outcome(v, why):
    return {"value": v} if v is not None else {"refused": why}


def census(before):
    entries = []
    for stem, syn, year, rec in records():
        for name, tri, routes in blocks(rec):
            old = read(before, tri, year)
            new = read(tg.compute_pyd_from_triangle, tri, year)
            printed = printed_row(stem, year, tri) if name == "rag_triangle" else None
            replayed = None
            if printed is not None:
                replayed = read(tg.compute_pyd_from_triangle, dict(tri, current_estimate_row=printed), year)
            final = replayed if replayed is not None else new
            if old == new and old == final:
                continue
            entry = {
                "stem": stem, "block": name, "grid": fingerprint(tri),
                "before": _outcome(*old), "after": _outcome(*new),
                "routes": {m: {k: r.get(k) for k in ("source", "value", "model_value") if r.get(k) is not None}
                           for m, r in routes.items()},
            }
            if printed is not None:
                entry["printed_current_estimate_row"] = printed
                entry["after_with_printed_row"] = _outcome(*replayed)
            if name == "rag_triangle" and final[0] is None:
                pages = cached_vision_pages(syn, year)
                outcomes = vision_outcomes(syn, year, pages) if pages else None
                walk = walk_page_vision(stem, year)
                if walk is None:
                    sys.exit("%s: its filing is not in this checkout, and the census walks the page-vision step on the filings (a PC step)" % stem)
                walked, ends = walk
                served = sorted(set(walked) & set(pages))
                if served:
                    read_ok = [o["value"] for p, o in outcomes.items() if "value" in o and int(p) in served]
                    entry["replay"] = (
                        "the table triangle is refused; page vision serves page(s) %s from the committed cache under "
                        "the current prompt, and %s" % (served, (
                            "the reader gives %s from it" % read_ok[0] if read_ok else
                            "the reader refuses what it holds too, so the record falls to the later routes (loss "
                            "ratio, provisions, narrative and the models) with no call")))
                elif walked:
                    entry["replay"] = (
                        "the table triangle is refused; the step reaches page vision on page(s) %s, for which there is no committed entry "
                        "under the current prompt, so the offline replay stops for this record on a cache miss and the record keeps its "
                        "figure" % walked)
                else:
                    entry["replay"] = (
                        "the table triangle is refused and the step reaches no page-vision step (the page finder selects no triangle "
                        "page for the filing); %s" % (
                            "it ends with no figure, no reserve text and no loss-ratio grid, so the record would be written as no "
                            "deterministic reading (unread, the models not run) and leave the working sample" if ends["no_triangle_data"] else
                            "it ends with %s by the %s route" % (ends["pyd"], ends["method"])))
                entry["vision_pages_walked"] = walked
                entry["reaches_page_vision"] = bool(walked)
                entry["vision_pages_cached"] = pages
                if outcomes:
                    entry["vision_outcomes"] = outcomes
            entries.append(entry)
    return entries


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--before", default=BEFORE)
    args = ap.parse_args()
    entries = census(reader_at(args.before))
    rag = [e for e in entries if e["block"] == "rag_triangle"]
    out = {
        "purpose": ("Every committed triangle whose deterministic figure the stage-2 reader changes or refuses, "
                    "read before and after the change on the same grid (review of 2 October 2026, M-1). The PC "
                    "reads the flagged filings' pages and regenerates the records offline; "
                    "tests/test_triangle_diagonal.py holds this file to the reader and the records."),
        "reader_before": args.before,
        "written_by": "scripts/triangle_census.py --write",
        "counts": {
            "rag_triangle_entries": len(rag),
            "rag_refused_on_replay": sum(1 for e in rag if "refused" in (e.get("after_with_printed_row")
                                                                          or e["after"])),
            "rag_refused_with_no_cached_vision_page": sum(1 for e in rag if e.get("vision_pages_cached") == []),
            "rag_replay_stops_on_a_cache_miss": sum(1 for e in rag if e.get("vision_pages_walked") and not (
                set(e["vision_pages_walked"]) & set(e["vision_pages_cached"]))),
            "rag_refused_reaching_no_page_vision": sum(1 for e in rag if e.get("vision_pages_walked") == []),
            "rag_replay_vision_refused_too": sum(1 for e in rag if e.get("vision_outcomes") and not any(
                "value" in o for o in e["vision_outcomes"].values())),
            "claims_triangle_entries": len(entries) - len(rag),
        },
        "entries": entries,
    }
    text = json.dumps(out, indent=1, ensure_ascii=False) + "\n"
    if args.write:
        with io.open(OUT, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        print("wrote %s: %s" % (OUT.relative_to(ROOT), out["counts"]))
    else:
        print(text)


if __name__ == "__main__":
    main()
