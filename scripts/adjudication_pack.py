#!/usr/bin/env python3
"""Lay out everything needed to adjudicate one record by hand, the same way every time.

The error-rate study (protocol fixed 11 September 2026, before any record was drawn) asks
for a verdict on each sampled record against the syndicate's own filing, recorded with the
page and the arithmetic that settles it. Eighty of those by hand go wrong in a predictable
way: the evidence looked at for record 3 is not the evidence looked at for record 60, and
the verdicts stop being comparable.

So the evidence pack is generated, not assembled by eye. For a stem this prints, in a fixed
order:

  * the adopted figure the loader would use, with its currency, units and basis;
  * the route that produced it -- the deterministic triangle, the model values, and which
    of them the override gate adopted -- so a wrong figure can be attributed;
  * the stored triangle as a grid, with each column's underwriting year and each row's
    development label;
  * the estimator's own per-year steps and total, printed as it reports them -- the pack
    derives no arithmetic of its own (R196);
  * where the stored triangle is not the adopted figure's source, which source it is (R197);
  * every sentence in the filing that speaks about prior-year movement, with its page, so
    the narrative figure can be read rather than searched for.

It reads committed records and committed caches. It makes no API call, and it states no
verdict: the verdict is the reader's, and this only makes the same evidence available for
each record.

Usage:
    python scripts/adjudication_pack.py syndicate_1274_2019
    python scripts/adjudication_pack.py --stems error-rate-sample.json --out packs/
"""
import argparse
import copy
import io
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

EXTRACTED = ROOT / "pdf_extraction"
PDFS = ROOT / "syndicate_reports" / "pdfs"
#: records whose stored triangle is not the source of their adopted figure (R197)
OVERRULED = EXTRACTED / "audit" / "triangle_overruled_by_sign_veto.json"

#: Sentences that speak about the movement of older years' reserves.
MOVEMENT = re.compile(
    r"prior[- ]year|prior year(?:s)?|earlier year|older year|"
    r"release[ds]?\b|redundan|strengthen|deteriorat|adverse development|"
    r"favourable development|favorable development|run[- ]off (?:profit|result|deviation)",
    re.I)


def _load(stem):
    p = EXTRACTED / ("%s.json" % stem)
    if not p.exists():
        raise SystemExit("no committed record for %s" % stem)
    return json.load(io.open(str(p), encoding="utf-8"))


def _fmt(x, nd=1):
    if x is None:
        return "--"
    if isinstance(x, (int, float)):
        return ("%%.%df" % nd) % x
    return str(x)


def _triangle_block(tri, report_year):
    """The stored grid, then the estimator's own account of it, verbatim.

    The first version re-derived the steps -- the last two filled cells of each column,
    summed -- and flagged a disagreement with the estimator. That was a second
    implementation, and a different one: the estimator skips a column whose previous
    development age is empty and works on its own cleaned copy of the grid, so 1991/2018
    summed to -137.7m in the pack against the estimator's -25.6m and was flagged when
    nothing disagreed (R196). The pack now derives nothing. The estimator gets a deep copy
    because it records decisions on the triangle it is given."""
    if not tri:
        return ["  (no triangle stored)"]
    import test_gemini as tg

    out = []
    uw = list(tri.get("underwriting_years") or [])
    rows = [list(r) for r in (tri.get("development_rows") or [])]
    labels = tri.get("row_labels") or []
    out.append("  basis=%s  currency=%s  units=%s  binding=%s  report_year=%s"
               % (tri.get("type"), tri.get("currency"), tri.get("units"),
                  tri.get("cell_binding"), report_year))
    out.append("    %-22s" % "development" + "".join("%10s" % y for y in uw))
    for i, row in enumerate(rows):
        label = labels[i] if i < len(labels) else "row %d" % (i + 1)
        out.append("    %-22s" % str(label)[:22] + "".join("%10s" % _fmt(v) for v in row))
    try:
        pyd, details = tg.compute_pyd_from_triangle(copy.deepcopy(tri), report_year)
    except Exception as exc:
        out.append("  the estimator could not be run here (%s)" % exc)
        return out
    out.append("")
    if pyd is None:
        out.append("  *** THE CURRENT RULES REJECT THIS TRIANGLE: %s ***" % details)
        out.append("  *** a record carrying a triangle-routed figure from it predates the rule ***")
        return out
    out.append("  the estimator's steps, as it reports them (a row number counts from 0):")
    out.extend("  " + line.rstrip() for line in str(details).splitlines() if line.strip())
    return out


def _signed(x):
    return "%+.1fm" % x if isinstance(x, (int, float)) else "--"


def _source_note(stem):
    """Where the adopted figure came from, when the record's own route note does not say.

    31 records keep a triangle the pipeline overruled: it disagreed in sign with the filing's
    provisions note, the note's figure was adopted, and the route still reads "rag_triangle
    ... confirmed by the model value". An adjudicator who recomputed the stored triangle would
    score a correct figure as an error (R197)."""
    try:
        reg = json.load(io.open(str(OVERRULED), encoding="utf-8"))
    except (OSError, ValueError):
        return []
    out = []
    for r in (reg.get("sign_veto_overrides") or {}).get("records") or []:
        if r.get("stem") != stem:
            continue
        source = r.get("source_of_adopted_figure")
        if source and source != "not established":
            out.append("  *** the stored triangle was OVERRULED: it gives %s, which disagreed in "
                       "sign with %s; the adopted %s is that figure ***"
                       % (_signed(r.get("overruled_triangle_gbp_m")), source,
                          _signed(r.get("adopted_gbp_m"))))
        else:
            out.append("  *** the stored triangle gives %s but %s was adopted, and the source of "
                       "the adopted figure is not established ***"
                       % (_signed(r.get("overruled_triangle_gbp_m")), _signed(r.get("adopted_gbp_m"))))
        out.append("  (audit/triangle_overruled_by_sign_veto.json)")
    for r in (reg.get("rejected_by_current_rules") or {}).get("records") or []:
        if r.get("stem") == stem:
            out.append("  *** the current rules reject the stored triangle: %s ***"
                       % r.get("why_the_current_rules_reject_the_stored_triangle"))
    return out


def _cited_pages(rec):
    """The pages the extraction itself pointed at, and their neighbours."""
    want = set()
    for m in (rec.get("models") or {}).values():
        route = m.get("_pyd_route") or {}
        for v in (m.get("prior_year_movement_page"), m.get("opening_reserves_page"),
                  route.get("triangle_source_page")):
            try:
                n = int(v)
            except (TypeError, ValueError):
                continue
            want.update((n - 1, n, n + 1))
    return sorted(p for p in want if p >= 1)


def _ocr_page(doc, pno):
    """Tesseract on one page, the way the extraction reads a scanned filing."""
    try:
        import pytesseract
        from PIL import Image
    except Exception:
        return None
    try:
        pix = doc[pno - 1].get_pixmap(dpi=200)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        return pytesseract.image_to_string(img)
    except Exception:
        return None


def _narrative(stem, limit=14, rec=None):
    """Sentences in the filing that speak about prior-year movement, with pages.

    The committed Azure cache holds `tables` only, so the text comes from the filing. A
    good share of this corpus is image-only, and a filing with no text layer must say so:
    reporting "no sentence mentions prior-year movement" for a scanned document is a false
    statement that would send an adjudicator to the wrong verdict."""
    pdf = PDFS / ("%s.pdf" % stem)
    source_note = []
    if not pdf.exists():
        # a report filed as HTML is read from the PDF the driver converted it to, whose pages
        # are the ones the record cites (R207)
        converted = EXTRACTED / "html_converted" / ("%s.pdf" % stem)
        if not converted.exists():
            return ["  (the filing is not in this checkout; the narrative cannot be shown)"]
        pdf = converted
        source_note = ["  the report was filed as HTML; read from the PDF the extraction converted "
                       "it to (%s)" % converted.name]
    try:
        import fitz
    except Exception:
        return ["  (PyMuPDF is unavailable; the narrative cannot be shown)"]
    doc = fitz.open(str(pdf))
    try:
        native = {p + 1: (doc[p].get_text() or "") for p in range(doc.page_count)}
        has_text = sum(len(v) for v in native.values()) > 200
        how = "the filing's own text layer"
        pages = native
        note = []
        if not has_text:
            cited = _cited_pages(rec or {}) or list(range(1, min(6, doc.page_count + 1)))
            cited = [p for p in cited if p <= doc.page_count]
            note.append("  this filing is image-only (%d pages, no text layer), so the "
                        "pages the" % doc.page_count)
            note.append("  extraction cited were read by OCR: %s"
                        % ", ".join(str(p) for p in cited))
            pages = {}
            for p in cited:
                got = _ocr_page(doc, p)
                if got is None:
                    return note + ["  OCR is unavailable here (pytesseract or Pillow "
                                   "missing), so the narrative cannot be shown; adjudicate "
                                   "this record against the page images directly"]
                pages[p] = got
            how = "OCR of the cited pages"
        out, seen = source_note + list(note), 0
        out.append("  read from: %s" % how)
        for page in sorted(pages):
            flat = " ".join((pages[page] or "").split())
            for sent in re.split(r"(?<=[.;])\s+", flat):
                if len(sent) < 30 or not MOVEMENT.search(sent):
                    continue
                if not re.search(r"\d", sent):
                    continue
                out.append("  p%-4s %s" % (page, sent[:300]))
                seen += 1
                if seen >= limit:
                    out.append("  ... (truncated; raise --narrative to see more)")
                    return out
        if not seen:
            out.append("  no sentence on the pages read speaks about prior-year movement"
                       " -- this is a statement about those pages, not about the filing")
        return out
    finally:
        doc.close()


def pack(stem, narrative=14):
    rec = _load(stem)
    report_year = int(stem.rsplit("_", 1)[1])
    L = []
    L.append("=" * 78)
    L.append("ADJUDICATION PACK  %s" % stem)
    L.append("=" * 78)
    L.append("  source: %s" % rec.get("source_file"))
    spec = rec.get("spec") or {}
    L.append("  prompt version %s (driver %s)"
             % (spec.get("prompt_version"), spec.get("driver_prompt_version")))

    models = rec.get("models") or {}
    L.append("")
    L.append("WHAT EACH MODEL SAID, AND WHAT THE ROUTE ADOPTED")
    adopted = set()
    for name, m in sorted(models.items()):
        route = m.get("_pyd_route") or {}
        L.append("  %s" % name)
        L.append("      prior-year development   %-10s  (page %s, confidence %s)"
                 % (_fmt(m.get("prior_year_development_gbp_m")),
                    m.get("prior_year_movement_page"),
                    m.get("prior_year_movement_confidence")))
        L.append("      opening reserves         %-10s  (page %s, %s)"
                 % (_fmt(m.get("opening_reserves_gbp_m")),
                    m.get("opening_reserves_page"),
                    m.get("opening_reserves_provenance")))
        L.append("      currency %s   basis/direction %s" % (m.get("currency"),
                                                             m.get("direction")))
        if route:
            L.append("      route: source=%s adopted=%s model_said=%s%s"
                     % (route.get("source"), _fmt(route.get("value")),
                        _fmt(route.get("model_value")),
                        "  [" + str(route.get("note")) + "]" if route.get("note") else ""))
            L.append("      triangle: type=%s units=%s (%s) from page %s"
                     % (route.get("triangle_type"), route.get("triangle_units"),
                        route.get("triangle_units_evidence"),
                        route.get("triangle_source_page")))
            adopted.add(route.get("value"))
    if len(adopted) > 1:
        L.append("  *** the models' routes adopted different figures: %s ***"
                 % sorted(x for x in adopted if x is not None))
    L.extend(_source_note(stem))

    L.append("")
    L.append("STORED TRIANGLE AND THE ARITHMETIC BEHIND THE ADOPTED FIGURE")
    tri = None
    for _n, m in sorted(models.items()):
        tri = m.get("_rag_triangle") or m.get("_claims_triangle")
        if tri:
            break
    L.extend(_triangle_block(tri, report_year))

    L.append("")
    L.append("WHAT THE FILING SAYS ABOUT PRIOR-YEAR MOVEMENT")
    L.extend(_narrative(stem, narrative, rec))

    L.append("")
    L.append("VERDICT (by hand: correct | error | undeterminable)")
    L.append("  the page and the arithmetic that settles it:")
    L.append("")
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("stem", nargs="?")
    ap.add_argument("--stems", help="a JSON list of stems")
    ap.add_argument("--out", help="write one .txt per stem into this directory")
    ap.add_argument("--narrative", type=int, default=14)
    a = ap.parse_args(argv)

    stems = []
    if a.stems:
        stems = json.load(io.open(a.stems, encoding="utf-8"))
        if isinstance(stems, dict):
            stems = stems.get("stems") or sorted(stems)
    elif a.stem:
        stems = [a.stem]
    else:
        ap.error("give a stem or --stems")

    if a.out:
        os.makedirs(a.out, exist_ok=True)
    for stem in stems:
        text = pack(stem, a.narrative)
        if a.out:
            io.open(os.path.join(a.out, "%s.txt" % stem), "w",
                    encoding="utf-8", newline="").write(text + "\n")
        else:
            print(text)
    if a.out:
        print("%d pack(s) written to %s" % (len(stems), a.out))
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
