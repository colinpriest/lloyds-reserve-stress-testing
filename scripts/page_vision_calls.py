"""Buy the page-vision readings the stage-2 replay needs, and nothing else (PC only; a paid step).

The stage-2 reader (review of 2 October 2026, M-1) refuses the table triangles of six records whose figure comes from that
triangle, and none of them has a committed page-vision entry under the current prompt, so their offline regeneration stops on
a cache miss and the record keeps the figure the reader refuses (`pdf_extraction/audit/stage2_triangle_census.json`). Colin
authorised paid Gemini page-vision calls for these six on 3 October 2026. The three 382 records the census also lists
(2015-2017) carry figures in the analysis's confirmed-figures register and are not called.

This script runs only the RAG step of the driver (`test_gemini.extract_pyd_from_relevant_pages`) for those records: the table
backends are served from the committed caches (`LLOYDS_ALLOW_TABLE_BACKEND_CALLS` must not be set), and the step's one paid
call is Gemini page vision on at most two gross triangle pages per record (`extract_triangle_with_retry`, which saves each
reading to `pdf_extraction/llm_cache`). No document-level model call is made: the driver makes those outside this step. The
offline regeneration then serves the new entries. Whether a reading gives a figure is the reader's to say: a refused reading
leaves the record to the later routes, as for 3334/2017 and 3500/2018.

Usage (on the PC, with the filings and GOOGLE_API_KEY):
    python scripts/page_vision_calls.py --dry-run          # the pages each record would send, and whether each is cached
    python scripts/page_vision_calls.py --max-cost 1.00    # make the calls; stop before a record once the cap is passed
"""
import argparse
import io
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

#: the records Colin authorised the calls for (3 October 2026)
STEMS = ["syndicate_1400_2014", "syndicate_1967_2014", "syndicate_2999_2022", "syndicate_3002_2021",
         "syndicate_3622_2023", "syndicate_3624_2023"]
#: the census's other refused records on the rag_triangle route, whose figures the analysis register holds
REGISTERED_ELSEWHERE = ["syndicate_382_2015", "syndicate_382_2016", "syndicate_382_2017"]
LOG = ROOT / "pdf_extraction" / "audit" / "page_vision_calls.json"


def vision_pages(tri_pages):
    """The pages the RAG step sends to page vision: the first two triangle pages, less one whose text says net and not
    gross (`extract_pyd_from_relevant_pages`, step 3)."""
    return [pn for pn, text in tri_pages[:2] if not ("net" in text.lower() and "gross" not in text.lower())]


def source_pdf(stem):
    with io.open(ROOT / "pdf_extraction" / ("%s.json" % stem), encoding="utf-8") as fh:
        return ROOT / str(json.load(fh)["source_file"]).replace("\\", "/")


def plan(tg, stems, pdf_for=source_pdf):
    """[(stem, year, pdf, [(page, cached)])] from each filing's own page text; no call."""
    out = []
    for stem in stems:
        year = int(stem.rsplit("_", 1)[1])
        syn = int(stem.split("_")[1])
        pdf = pdf_for(stem)
        pages, _ = tg.extract_text_from_pdf(pdf)
        tri = tg.find_relevant_pages(pages, year)["triangle_pages"]
        prompt = tg.TRIANGLE_EXTRACT_PROMPT.replace("{report_year}", str(year))
        listed = []
        for page in vision_pages(tri):
            key = tg._llm_cache_key("gemini-2.5-flash", prompt, syn, year, page_num=page)
            listed.append((page, (ROOT / "pdf_extraction" / "llm_cache" / (key + ".json")).exists()))
        out.append((stem, year, pdf, listed))
    return out


def run(tg, stems, max_cost, pdf_for=source_pdf, log_path=LOG):
    """Run the RAG step for each record until the spend passes `max_cost`; write what was bought to `log_path`."""
    if os.getenv("LLOYDS_EXTRACTION_OFFLINE") == "1":
        raise SystemExit("LLOYDS_EXTRACTION_OFFLINE=1: the page-vision calls cannot be made offline; unset it for this run")
    if os.getenv("LLOYDS_ALLOW_TABLE_BACKEND_CALLS") == "1":
        raise SystemExit("LLOYDS_ALLOW_TABLE_BACKEND_CALLS=1 would let the table step re-bill a backend; unset it")
    if not os.getenv("GOOGLE_API_KEY"):
        raise SystemExit("GOOGLE_API_KEY is not set")
    spent, rows = 0.0, []
    for stem, year, pdf, pages in plan(tg, stems, pdf_for):
        if spent > max_cost:
            print("  spend cap $%.2f passed ($%.4f): stopping before %s" % (max_cost, spent, stem))
            break
        result = tg.extract_pyd_from_relevant_pages(pdf, year)
        cost = float(result.get("cost") or 0)
        spent += cost
        rows.append({"stem": stem, "pages": [p for p, _ in pages], "cached_before": [p for p, c in pages if c],
                     "cost_usd": round(cost, 6), "method": result.get("method"), "pyd": result.get("pyd"),
                     "details": result.get("pyd_details")})
        print("  %s: pages %s, $%.4f, method %s, pyd %s" % (stem, [p for p, _ in pages], cost, result.get("method"),
                                                          result.get("pyd")))
    record = {"purpose": "The paid page-vision calls Colin authorised on 3 October 2026 for the six records whose table "
                         "triangle the stage-2 reader refuses and whose replay stopped on a cache miss "
                         "(scripts/page_vision_calls.py).",
              "run_at": datetime.now(timezone.utc).isoformat(), "max_cost_usd": max_cost,
              "spent_usd": round(spent, 6), "records": rows}
    with io.open(log_path, "w", encoding="utf-8", newline="") as fh:
        fh.write(json.dumps(record, indent=1) + "\n")
    print("spent $%.4f on %d record(s); wrote %s" % (spent, len(rows), log_path))
    return record


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max-cost", type=float, default=1.00)
    args = ap.parse_args(argv)
    import test_gemini as tg
    if args.dry_run:
        for stem, _year, pdf, pages in plan(tg, STEMS):
            print("%s (%s): %s" % (stem, pdf.name, ", ".join("p%d%s" % (p, " cached" if c else "") for p, c in pages)
                                   or "no triangle page"))
        return None
    return run(tg, STEMS, args.max_cost)


if __name__ == "__main__":
    main()
