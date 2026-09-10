#!/usr/bin/env python3
"""Write docs/prompt-history.md: which prompt version governed each committed model
response, and how many records rest on the routes the round-55 prompt change touched.

Round 55 (review of 10 September 2026, T02) corrected three defects in the extraction
prompt (one business-mix hierarchy, the claims-incurred definition, a loss-ratio route
that needs underwriting-year premiums) and moved PROMPT_VERSION to 2.11. Every committed
response cache was produced under an earlier version, and regenerating a record under
the corrected prompt needs fresh paid model inference, which was not authorised. This
document is therefore the record of what the old prompt governed; it is generated from
the caches and the records, never typed.

Run:  python scripts/prompt_history.py           (writes docs/prompt-history.md)
      python scripts/prompt_history.py --check   (exit 1 if the document is stale)
"""
import collections
import glob
import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "pdf_extraction", "llm_cache")
RECORDS = os.path.join(ROOT, "pdf_extraction")
OUT = os.path.join(ROOT, "docs", "prompt-history.md")

MANAGED = re.compile(r"\[MANAGED LEVEL: PYD from loss ratio triangle", re.I)
LR_TOTAL = re.compile(r"loss.ratio", re.I)
APPROX = re.compile(r"approximat|total (?:gross )?premium", re.I)


def current_version():
    src = io.open(os.path.join(ROOT, "test_gemini.py"), encoding="utf-8").read()
    return re.search(r'^PROMPT_VERSION = "([0-9.]+)"', src, re.M).group(1)


def _ver(v):
    try:
        return tuple(int(x) for x in str(v).split("."))
    except ValueError:
        return (0,)


def survey():
    """Counts from the committed caches and records."""
    versions = collections.Counter()
    stems = set()
    for f in glob.glob(os.path.join(CACHE, "*.json")):
        try:
            meta = json.load(io.open(f, encoding="utf-8")).get("_cache_meta") or {}
        except (ValueError, OSError):
            continue
        versions[str(meta.get("prompt_version") or "unversioned")] += 1
        if meta.get("syndicate") and meta.get("year"):
            stems.add((int(meta["syndicate"]), int(meta["year"])))
    n_records = 0
    managed = set()
    lr_mentioned = set()
    lr_approx = set()
    for f in sorted(glob.glob(os.path.join(RECORDS, "syndicate_*.json"))):
        if not re.fullmatch(r"syndicate_\d+_\d{4}\.json", os.path.basename(f)):
            continue  # the inception-year index and a backend dump share the prefix
        try:
            rec = json.load(io.open(f, encoding="utf-8"))
        except (ValueError, OSError):
            continue
        n_records += 1
        stem = os.path.basename(f)[:-5]
        for m in (rec.get("models") or {}).values():
            raw_notes = m.get("data_quality_notes") or ""
            notes = raw_notes if isinstance(raw_notes, str) else " ".join(str(x) for x in raw_notes)
            if MANAGED.search(notes):
                managed.add(stem)
            if LR_TOTAL.search(notes):
                lr_mentioned.add(stem)
                if APPROX.search(notes):
                    lr_approx.add(stem)
    cur = current_version()
    newest_cached = max(versions, key=_ver) if versions else "none"
    return {"current_prompt_version": cur, "cache_files": sum(versions.values()),
            "versions": dict(sorted(versions.items(), key=lambda kv: _ver(kv[0]))),
            "newest_cached_version": newest_cached,
            "caches_at_current_version": versions.get(cur, 0),
            "stems_with_a_cache": len(stems), "records": n_records,
            "records_loss_ratio_fallback_applied": sorted(managed),
            "records_mentioning_a_loss_ratio_table": len(lr_mentioned),
            "records_loss_ratio_with_a_premium_approximation": sorted(lr_approx)}


def render(s):
    L = []
    A = L.append
    A("# Prompt history: which prompt governed the committed extraction")
    A("")
    A("> **Generated file — do not edit.** Written by `scripts/prompt_history.py` from the "
      "committed response caches and records.")
    A("")
    A("The extraction prompt in `test_gemini.py` is at version **%s**. The review of 10 September "
      "2026 (T02) found three defects in the prompt as it stood at 2.10 and earlier: it asked "
      "for the regulatory segmental classes, forbade the divisional breakdown and then preferred "
      "divisional totals; it defined gross claims incurred with premiums earned; and its "
      "loss-ratio route let total premium stand in for missing underwriting-year premiums. "
      "Version 2.11 states one business-mix hierarchy (the segmental note; the divisional summary "
      "only when there is none; never merged), the claims-incurred identity (paid claims plus the "
      "change in the gross claims provision), and a loss-ratio route that returns null without "
      "underwriting-year premiums." % s["current_prompt_version"])
    A("")
    A("## What the committed responses were produced under")
    A("")
    A("| Prompt version | Cached responses |")
    A("|---|---:|")
    for v, n in s["versions"].items():
        A("| %s | %s |" % (v, format(n, ",")))
    A("")
    A("%s cached responses cover %s syndicate-years; the corpus holds %s records. The newest "
      "version any cache carries is **%s**; **%d** caches were produced under the current "
      "version %s. Every committed record therefore rests on responses produced under the "
      "old prompt rules." % (format(s["cache_files"], ","), format(s["stems_with_a_cache"], ","),
                             format(s["records"], ","), s["newest_cached_version"],
                             s["caches_at_current_version"], s["current_prompt_version"]))
    A("")
    A("## Which records the changed routes touched")
    A("")
    A("- **Business mix.** Since round 54 the premium mix is read from the annual segmental "
      "table by the deterministic pass, and a model's mix is admitted only when its classes "
      "reconcile with the record's own premium within 10% (`_parse_nutrient_lob`, the loader's "
      "reconciliation in the analysis repository). The prompt's conflicting mix instructions "
      "therefore governed only the model's fallback mix.")
    A("- **Claims incurred.** The corrected sentence explains what not to use; it changes no "
      "extracted value.")
    approx = s["records_loss_ratio_with_a_premium_approximation"]
    A("- **Loss-ratio route.** %d record(s) mention a loss ratio in a model's data-quality "
      "notes, in any context; %d of them carry a note that also mentions an approximation or a "
      "total premium%s, the records where the old fallback could have substituted total "
      "premium for underwriting-year premiums; %d record(s) had the deterministic loss-ratio "
      "fallback applied at managed or group level%s. A record whose adopted figure rests on "
      "the loss-ratio route can be regenerated only by fresh model inference under version "
      "%s, which needs the source reports and paid API access."
      % (s["records_mentioning_a_loss_ratio_table"],
         len(approx),
         (" (%s)" % ", ".join(approx)) if 0 < len(approx) <= 20 else "",
         len(s["records_loss_ratio_fallback_applied"]),
         (" (%s)" % ", ".join(s["records_loss_ratio_fallback_applied"])
          if s["records_loss_ratio_fallback_applied"] else ""),
         s["current_prompt_version"]))
    A("")
    A("## Replay")
    A("")
    A("Offline replay (`--offline`) serves a cache miss at the current version from the "
      "committed entry for the same model, syndicate and year at the newest cached version "
      "(`_llm_cache_by_meta`), and records that version in `_served_from`; so a replayed record "
      "is reproducible and still carries the old prompt's responses. No record has been "
      "described as revalidated under version %s." % s["current_prompt_version"])
    A("")
    return "\n".join(L) + "\n"


def main():
    text = render(survey())
    if "--check" in sys.argv:
        cur = io.open(OUT, encoding="utf-8").read() if os.path.exists(OUT) else ""
        if cur != text:
            print("docs/prompt-history.md is stale; run scripts/prompt_history.py")
            return 1
        print("docs/prompt-history.md is current")
        return 0
    io.open(OUT, "w", encoding="utf-8", newline="\n").write(text)
    print("wrote docs/prompt-history.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
