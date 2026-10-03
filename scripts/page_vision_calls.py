"""The page-vision calls this script was written for were made on 3 October 2026; nothing may still be bought (PC only; a paid step).

Why it was written. The stage-2 reader (review of 2 October 2026, M-1) refuses the table triangles of records whose figure came from that
triangle, and a record with no committed page-vision entry under the current prompt stops its offline regeneration on a cache miss and keeps
the figure the reader refuses (`pdf_extraction/audit/stage2_triangle_census.json`). Colin authorised paid Gemini page-vision calls for six
such records on 3 October 2026 (1400/2014, 1967/2014, 2999/2022, 3002/2021, 3622/2023, 3624/2023), and this script was written, in the
cloud, for those six.

What was done instead. The calls were made the same day, 16:40 to 16:44, by the PC launcher and not by this script, on Colin's "full B": 12
pages of 11 records, 12 attempts, 12 responses parsed and cached under the current prompt (PROMPT_VERSION 2.13), 44,541 tokens, an estimated
US$0.0967. Of the six, 1400/2014, 2999/2022, 3002/2021 and 3624/2023 were bought; 1967/2014 had no page to send, and 3622/2023 had an older
response to the same prompt text. The launcher also bought 2010/2014 and 382/2015 to 2020, which this script never named for buying. The
census was written again afterwards (5b3a0354). docs/ocr-pipeline.md section 9.1 holds the page-by-page table; the launcher's ledger
(optb_ledger.jsonl, on the PC under D:/tmp/r62/stage2pc) is not committed.

Where each record stands. The census counts four refused triangles with no cached page-vision entry (`rag_refused_with_no_cached_vision_page`),
and none of the four may be bought:
  * OLDER_RESPONSE, 2121/2019 (page 56) and 3622/2023 (page 36). A response to the same page prompt, from an older driver version (2.8, cached on
    18 March 2026; 2.10, on 5 July 2026), is in the cache. The cache key includes the version, so it is not served, but the prompt text is the
    same (the key recomputed from the older version and today's text is the cached file's name). Colin's rule is that an unchanged prompt is not
    run again, and a cache version is not a prompt version. Serving the older response is a later stage's decision.
  * NO_PAGE, 1967/2014 and 1991/2018. The page finder selects no triangle page, so there is no page to send (1967/2014's filing prints no claims
    development table; 1991/2018's gross triangle, on PDF page 30, matches one of the finder's two patterns where it needs two).
The other records this script names are not stuck any more:
  * SERVED: the 12 pages above, now cached under the current prompt.
  * MISREAD: 2999/2022's page reading is the page shifted one column. It is cached and is not used: the record keeps its committed figure and is
    declared in `pdf_extraction/audit/redecision_pending.json` (docs/ocr-pipeline.md section 9.1).
  * REGISTERED_ELSEWHERE: 382/2015 to 2017 hold figures in the analysis's confirmed-figures register (data/pyd_confirmed_figures.json there);
    their pages were bought as well.
So STEMS, what may still be bought, is empty, and a run with nothing to buy makes no call and writes no log. A record is added to STEMS only if the
census counts it as stuck, it has a page to send, the cache holds no response to the same prompt text, and Colin authorises the call.

How a call is made, if one is ever authorised again. This script runs only the RAG step of the driver (`test_gemini.extract_pyd_from_relevant_pages`)
for the records in STEMS: the table backends are served from the committed caches (`LLOYDS_ALLOW_TABLE_BACKEND_CALLS` must not be set), and the
step's one paid call is Gemini page vision on at most two gross triangle pages per record (`extract_triangle_with_retry`, which saves each reading
to `pdf_extraction/llm_cache`). No document-level model call is made: the driver makes those outside this step. Whether a reading gives a figure is
the reader's to say: a refused reading leaves the record to the later routes, as for 3334/2017 and 3500/2018.

Usage (on the PC, with the filings and GOOGLE_API_KEY):
    python scripts/page_vision_calls.py --dry-run          # the pages each record in STEMS would send, and whether each is cached
    python scripts/page_vision_calls.py --max-cost 1.00    # make the calls; stop before a record once the cap is passed
With STEMS empty, as it is, both only say that nothing may be bought.
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

#: what may still be bought: nothing. A record goes here only if the census counts it as stuck (no cached page-vision entry under the current
#: prompt), it has a page to send, the cache holds no response to the same prompt text, and Colin authorises the call. It held the six records
#: Colin authorised on 3 October 2026 until the calls were made that day.
STEMS = []
#: bought on 3 October 2026 (Colin's "full B": 12 pages of 11 records, US$0.0967) and cached under the current prompt: {stem: the pages sent}.
#: 1400/2014, 2999/2022, 3002/2021 and 3624/2023 were among the six this script named; 2010/2014 and 382/2015 to 2020 were not named for buying
SERVED = {"syndicate_1400_2014": [8], "syndicate_2010_2014": [20], "syndicate_2999_2022": [48], "syndicate_3002_2021": [38],
          "syndicate_3624_2023": [38], "syndicate_382_2015": [46], "syndicate_382_2016": [46], "syndicate_382_2017": [47],
          "syndicate_382_2018": [46], "syndicate_382_2019": [46], "syndicate_382_2020": [46, 47]}
#: a response to the same page prompt text is cached under an older driver version, so it is not served, and an unchanged prompt is not run
#: again (a cache version is not a prompt version): {stem: (the page, the older version)}
OLDER_RESPONSE = {"syndicate_2121_2019": (56, "2.8"), "syndicate_3622_2023": (36, "2.10")}
#: the page finder selects no triangle page, so page vision has nothing to send
NO_PAGE = ["syndicate_1967_2014", "syndicate_1991_2018"]
#: the reading is the page shifted one column: cached, and not used
MISREAD = ["syndicate_2999_2022"]
#: the census's other refused records on the rag_triangle route, whose figures the analysis register holds (their pages were bought as well)
REGISTERED_ELSEWHERE = ["syndicate_382_2015", "syndicate_382_2016", "syndicate_382_2017"]
LOG = ROOT / "pdf_extraction" / "audit" / "page_vision_calls.json"
NOTHING_TO_BUY = "Nothing may still be bought: STEMS is empty (the module docstring says where each record stands)."


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
    """Run the RAG step for each record until the spend passes `max_cost`; write what was bought to `log_path`. With no record to buy it
    refuses before anything else: no call, and no log."""
    if not stems:
        raise SystemExit(NOTHING_TO_BUY)
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
    record = {"purpose": "The paid page-vision calls scripts/page_vision_calls.py made for the records in its STEMS, each authorised by "
                         "Colin (the calls of 3 October 2026 were made that day by the PC launcher: see the script's docstring).",
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
    if not STEMS:
        print(NOTHING_TO_BUY)
        return None
    import test_gemini as tg
    if args.dry_run:
        for stem, _year, pdf, pages in plan(tg, STEMS):
            print("%s (%s): %s" % (stem, pdf.name, ", ".join("p%d%s" % (p, " cached" if c else "") for p, c in pages)
                                   or "no triangle page"))
        return None
    return run(tg, STEMS, args.max_cost)


if __name__ == "__main__":
    main()
