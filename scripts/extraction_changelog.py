#!/usr/bin/env python3
"""Write docs/extraction-changelog.md: every committed record whose extraction differs
from a named earlier commit, with the figure, the basis evidence and the route on both
sides.

Why this exists. Round 55 (the review of 10 September 2026) corrected two extraction
rules -- the percentage-against-monetary decision (T03) and the transposed parser's
handling of a page carrying a gross and a net block under one header -- and re-extracted
the records those rules touch. The change was large (dozens of records, tens of adopted
figures) and its only account was a working note outside both repositories, so a reader
of the committed data could not tell which records had moved or why. The log is
generated from the records themselves, never typed.

Run:  python scripts/extraction_changelog.py [--since <commit>]
      python scripts/extraction_changelog.py --check    (exit 1 if the document is stale)
"""
import glob
import io
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RECORDS = os.path.join(ROOT, "pdf_extraction")
OUT = os.path.join(ROOT, "docs", "extraction-changelog.md")
DEFAULT_SINCE = "7334497"
VOLATILE = {"extraction_timestamp", "total_cost_usd", "total_tokens", "_cache_meta",
            "cached_at", "elapsed_s", "timestamp", "_extraction_meta"}
FIELDS = ("prior_year_development_gbp_m", "prior_year_development_pct",
          "opening_reserves_gbp_m", "gross_premiums_written_gbp_m", "gross_premium_mix",
          "_claims_triangle", "_rag_triangle", "_adobe_lob", "_adobe_provisions",
          "data_quality_notes", "currency", "direction")
OVERRIDE_TAG = re.compile(r"\[(?:RAG|CODE|RAG DIRECTION) OVERRIDE:")


def git(*args):
    return subprocess.run(["git", "-C", ROOT, *args], capture_output=True).stdout


def strip(o):
    if isinstance(o, dict):
        return {k: strip(v) for k, v in o.items() if k not in VOLATILE}
    if isinstance(o, list):
        return [strip(v) for v in o]
    return o


def canonical(rec):
    """The block a reader would take as the record's own values: the first model key,
    which is the loader's canonical choice when validation passed."""
    models = rec.get("models") or {}
    return models[sorted(models)[0]] if models else {}


def route_of(m):
    r = m.get("_pyd_route") or {}
    if r:
        return "%s (%s)" % (r.get("source", "?"), r.get("triangle_type") or "?")
    notes = m.get("data_quality_notes") or ""
    notes = notes if isinstance(notes, str) else " ".join(map(str, notes))
    return "deterministic override (note)" if OVERRIDE_TAG.search(notes) else "model"


def survey(since):
    rows, unreplayable = [], []
    for f in sorted(glob.glob(os.path.join(RECORDS, "syndicate_*.json"))):
        stem = os.path.basename(f)[:-5]
        if not re.fullmatch(r"syndicate_\d+_\d{4}", stem):
            continue
        blob = git("show", "%s:pdf_extraction/%s.json" % (since, stem))
        if not blob:
            continue
        try:
            old = json.loads(blob.decode("utf-8"))
            new = json.load(io.open(f, encoding="utf-8"))
        except ValueError:
            continue
        if strip(old) == strip(new):
            continue
        changed = [fld for fld in FIELDS
                   if strip(canonical(old).get(fld)) != strip(canonical(new).get(fld))]
        co, cn = canonical(old), canonical(new)
        rows.append({"stem": stem,
                     "pyd_old": co.get("prior_year_development_gbp_m"),
                     "pyd_new": cn.get("prior_year_development_gbp_m"),
                     "route_old": route_of(co), "route_new": route_of(cn),
                     "fields": changed})
    return rows, unreplayable


def render(rows, since, unservable):
    L = []
    A = L.append
    A("# Extraction change log")
    A("")
    A("> **Generated file — do not edit.** Written by `scripts/extraction_changelog.py` "
      "by comparing every committed record with the same record at commit `%s`." % since)
    A("")
    A("Round 55 (the external review of 10 September 2026) corrected two extraction rules "
      "and re-extracted the records they touch, offline from the committed response and "
      "table caches. The rules were: the percentage-against-monetary decision, which now "
      "rests on the table's own unit evidence before any magnitude heuristic (finding T03); "
      "and the transposed-grid parser, which now captures one basis block of a page that "
      "prints a gross and a net triangle under one header, and labels it by that block's "
      "own heading. The route by which each record's development figure was adopted is now "
      "recorded on the record (`_pyd_route`) instead of being inferred from a sentence in "
      "its notes.")
    A("")
    A("**%d record(s) differ from `%s`.** The adopted figure moves in %d of them."
      % (len(rows), since, sum(1 for r in rows if r["pyd_old"] != r["pyd_new"])))
    A("")
    A("| Record | Development, before | after | Route, before | after | Fields that differ |")
    A("|---|---:|---:|---|---|---|")
    for r in rows:
        A("| `%s` | %s | %s | %s | %s | %s |"
          % (r["stem"], r["pyd_old"], r["pyd_new"], r["route_old"], r["route_new"],
             ", ".join(f.lstrip("_") for f in r["fields"]) or "provenance only"))
    A("")
    if unservable:
        A("## Stems that could not be replayed offline")
        A("")
        A("These reports' page-level caches are absent or in the superseded format, so the "
          "corrected rules could not be applied to them without fresh paid inference. Their "
          "committed records stand unchanged, and the driver exits non-zero rather than "
          "deleting them.")
        A("")
        for s in unservable:
            A("- `%s`" % s)
        A("")
    return "\n".join(L) + "\n"


def main():
    since = DEFAULT_SINCE
    if "--since" in sys.argv:
        since = sys.argv[sys.argv.index("--since") + 1]
    unservable_path = os.path.join(ROOT, "pdf_extraction", "audit", "offline_unservable.json")
    unservable = []
    if os.path.exists(unservable_path):
        unservable = json.load(io.open(unservable_path, encoding="utf-8")).get("stems", [])
    rows, _ = survey(since)
    text = render(rows, since, unservable)
    if "--check" in sys.argv:
        cur = io.open(OUT, encoding="utf-8").read() if os.path.exists(OUT) else ""
        if cur != text:
            print("docs/extraction-changelog.md is stale; run scripts/extraction_changelog.py")
            return 1
        print("docs/extraction-changelog.md is current (%d record(s))" % len(rows))
        return 0
    io.open(OUT, "w", encoding="utf-8", newline="\n").write(text)
    print("wrote docs/extraction-changelog.md: %d record(s), %d adopted-figure move(s)"
          % (len(rows), sum(1 for r in rows if r["pyd_old"] != r["pyd_new"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
