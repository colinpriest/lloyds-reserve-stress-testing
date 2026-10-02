"""Build syndicate_reports/download_addendum.json: the corpus filings that have no row in the download ledger.

The ledger, syndicate_reports/download_status.json, has one row for each row of the workbook
(syndicate_reports/Lloyds_Syndicates_2014_2024.xlsx), written by scripts/download_from_xlsx.py. Some corpus filings are not
rows of the workbook: an earlier pass with scripts/lloyds_scraper.py collected them before the downloader existed, so the
ledger has no row for them and never had one. The author decided on 2 October 2026 to leave the ledger as it is and to list
them apart. This script builds that list: for each filing, the web address Lloyd's site gave for it on a re-fetch and the size
and SHA-256 of the corpus copy. tests/test_download_addendum.py holds the list to the corpus, the ledger and the files.

The filings listed are the corpus filings (the committed extraction records pdf_extraction/syndicate_N_YYYY.json) that are
not keys of the ledger.

The input is a folder holding compare.json, which the comparison of the re-fetch with the corpus writes: a list with one object
for each listed filing,

    {"stem": "780_2019", "syndicate": 780, "year": 2019,
     "source_url": the address the scraper found, or null,
     "fresh":  the copy fetched from that address, or null: {"file", "size_bytes", "sha256", "pages"},
     "corpus": the corpus copy when the comparison was made: {"file", "size_bytes", "sha256", "pages"}}

(other keys are not read). The re-fetch itself is scripts/lloyds_scraper.py --syndicates N --years Y1,Y2 --output <folder>/N,
one run for each syndicate with that syndicate's listed years (the scraper rewrites its output folder's metadata/reports.json,
so each syndicate has a folder of its own, and none is pointed at syndicate_reports/; it also writes lloyds_scraper.log to the
working directory). Each fresh copy is then compared with the corpus copy by SHA-256. This script re-reads every corpus copy and
stops if one is neither the file compare.json compared nor that filing's fresh copy, so the list is never built from a comparison
that is out of date. A corpus copy that is the fresh copy, where compare.json compared another file, was replaced by Lloyd's file
after the comparison: it is listed as matching, and the copy it replaced is kept as earlier_copy (the size and SHA-256 that
compare.json gives), with a note on which of the two the filing's extraction record was made from. compare.json must therefore be
the one made before the replacement. When the folder also holds the fresh copies (<folder>/<syndicate>/pdfs/<file>), a corpus copy
that is the first bytes of its fresh copy (a download cut short) is said so.

Usage:  python scripts/build_download_addendum.py <folder> --fetched 2026-10-02 [--output PATH] [--earlier-copy N_YYYY=PATH ...]
        (--earlier-copy names a replaced corpus copy that is kept: the build checks it against compare.json, and says so if it is the
        first bytes of the file that replaced it, a download cut short)
"""
import argparse
import datetime
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "syndicate_reports" / "download_status.json"
CORPUS_FILES = ROOT / "syndicate_reports" / "pdfs"
OUTPUT = ROOT / "syndicate_reports" / "download_addendum.json"
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November",
          "December")


def long_date(iso):
    """'2026-10-02' as '2 October 2026'."""
    d = datetime.date.fromisoformat(iso)
    return "%d %s %d" % (d.day, MONTHS[d.month - 1], d.year)


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def stem_key(stem):
    return tuple(int(x) for x in stem.split("_"))


def off_ledger_stems():
    """The corpus filings that are not keys of the ledger, as 'N_YYYY', in syndicate and year order."""
    corpus = {p.stem[len("syndicate_"):] for p in (ROOT / "pdf_extraction").glob("syndicate_*.json")
              if re.fullmatch(r"syndicate_\d+_\d{4}", p.stem)}
    ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
    return sorted(corpus - set(ledger), key=stem_key)


def corpus_copy(stem):
    """The one file of the corpus that is the filing."""
    found = [p for p in (CORPUS_FILES / ("syndicate_%s%s" % (stem, ext)) for ext in (".pdf", ".html", ".htm")) if p.exists()]
    if len(found) != 1:
        raise SystemExit("%s: %d files in %s (the filings are not committed; build the list where they are)"
                         % (stem, len(found), CORPUS_FILES))
    return found[0]


def first_bytes_of(path, other):
    """Whether `path` is the first bytes of `other`, and shorter."""
    if not other.exists() or path.stat().st_size >= other.stat().st_size:
        return False
    with open(path, "rb") as a, open(other, "rb") as b:
        for block in iter(lambda: a.read(1 << 20), b""):
            if b.read(len(block)) != block:
                return False
    return True


def record_date(stem):
    """The date the filing's extraction record was written (its extraction_timestamp), as YYYY-MM-DD, or None."""
    path = ROOT / "pdf_extraction" / ("syndicate_%s.json" % stem)
    stamp = json.loads(path.read_text(encoding="utf-8")).get("extraction_timestamp") if path.exists() else None
    return stamp[:10] if isinstance(stamp, str) and re.match(r"\d{4}-\d{2}-\d{2}", stamp) else None


def replaced_note(stem, earlier, pages, fetched, size=None, cut_short=False):
    """What a reader needs about a corpus copy that replaced another: the earlier copy (said to be the first bytes of this file,
    a download cut short, only when the build was given the earlier file and checked it), and which of the two the filing's
    extraction record was made from (by its date against the replacement's)."""
    if cut_short:
        note = ("This file replaced an earlier corpus copy on %s. The earlier copy was the first {:,} bytes of this file ({:,} "
                "bytes): a download cut short%s.".format(earlier["size_bytes"], size)
                % (long_date(fetched), ", and it opened with no page" if pages == 0 else ""))
    else:
        note = ("This file replaced an earlier corpus copy on %s. The earlier copy was {:,} bytes%s.".format(earlier["size_bytes"])
                % (long_date(fetched), " and opened with no page" if pages == 0 else ""))
    written = record_date(stem)
    if written and written < fetched:
        note += (" The extraction record of this filing was written on %s, before the replacement, so it was made from the earlier "
                 "copy." % long_date(written))
    elif written:
        note += " The extraction record of this filing was written on %s, after the replacement." % long_date(written)
    return note


def header(fetched):
    return {
        "purpose": ("The corpus filings that have no row in the download ledger (syndicate_reports/download_status.json). For "
                    "each: the web address Lloyd's site gave for it when it was looked up again (the re-fetch below), the size and "
                    "SHA-256 of the file in the corpus, and whether the file Lloyd's serves is that file. Built by "
                    "scripts/build_download_addendum.py; tests/test_download_addendum.py holds it to the corpus, the ledger and "
                    "the files."),
        "why_not_in_the_ledger": ("The ledger has one row for each row of the workbook "
                                  "(syndicate_reports/Lloyds_Syndicates_2014_2024.xlsx), written by scripts/download_from_xlsx.py. "
                                  "These filings are not rows of the workbook: an earlier pass with scripts/lloyds_scraper.py "
                                  "collected them, and their extraction records were committed between 12 and 19 March 2026, "
                                  "before the downloader and the ledger existed (6 July 2026). So the ledger has no row for them "
                                  "and never had one. They are listed here, and not added to the ledger, by the author's decision "
                                  "of 2 October 2026."),
        "refetch": {
            "date": fetched,
            "route": ("scripts/lloyds_scraper.py, the earlier scraper that collected these filings, run on %s for each syndicate "
                      "and the years listed here, with its output in a new folder outside the repository (one folder for each "
                      "syndicate, because the scraper rewrites its output folder's metadata/reports.json). source_url is the "
                      "address the scraper recorded for the filing (pdf_url). Each file it downloaded was compared with the "
                      "corpus copy by SHA-256." % long_date(fetched)),
        },
        "fingerprint": ("size_bytes and sha256 are the size and the SHA-256 of the corpus copy, syndicate_reports/pdfs/<file>. The "
                        "corpus copy's SHA-256 is the record of what the extraction read (for an HTML filing, the file the "
                        "extraction's converted PDF was made from), except for an entry with earlier_copy: its corpus copy "
                        "replaced an earlier one, whose size and SHA-256 earlier_copy gives, and its note says which of the two "
                        "the extraction record was made from. source_url says where Lloyd's served a file on the re-fetch date, "
                        "and lloyds_copy says whether that file is the corpus copy."),
        "lloyds_copy": {
            "matches": "the file at source_url on the re-fetch date is, byte for byte, the corpus copy (the same SHA-256)",
            "differs": ("the file at source_url differs from the corpus copy; lloyds_size_bytes and lloyds_sha256 are those of "
                        "the file Lloyd's served"),
            "not found": ("the scraper found no address for the filing on the re-fetch date, so source_url is null and "
                          "source_note says so; the filing may still be published, since the scraper looks only for the pages "
                          "and file addresses it knows"),
        },
    }


def build(folder, fetched, earlier_files=None):
    """The list, as a dict, from folder/compare.json and the corpus copies. earlier_files ({'N_YYYY': path}) are the corpus copies
    that were replaced, if they are kept: each is checked against the size and SHA-256 compare.json gives, and said to be the
    first bytes of the file that replaced it where it is."""
    earlier_files = dict(earlier_files or {})
    rows = json.loads((folder / "compare.json").read_text(encoding="utf-8"))
    by_stem = {}
    for row in rows:
        if row["stem"] in by_stem:
            raise SystemExit("compare.json has two rows for %s" % row["stem"])
        by_stem[row["stem"]] = row
    stems = off_ledger_stems()
    if set(by_stem) != set(stems):
        raise SystemExit("compare.json is not for the filings that have no ledger row: only in compare.json %s; only in the "
                         "corpus %s" % (sorted(set(by_stem) - set(stems), key=stem_key), sorted(set(stems) - set(by_stem), key=stem_key)))
    out = header(fetched)
    entries = []
    for stem in stems:
        row, path = by_stem[stem], corpus_copy(stem)
        syndicate, year = stem_key(stem)
        if (row.get("syndicate"), row.get("year")) != (syndicate, year):
            raise SystemExit("%s: compare.json gives syndicate %s, year %s" % (stem, row.get("syndicate"), row.get("year")))
        size, sha = path.stat().st_size, sha256_of(path)
        compared, fresh = row.get("corpus") or {}, row.get("fresh")
        earlier = None
        if (compared.get("size_bytes"), compared.get("sha256")) != (size, sha):
            if fresh and (fresh.get("size_bytes"), fresh.get("sha256")) == (size, sha) and compared.get("size_bytes") and compared.get("sha256"):
                earlier = {"size_bytes": compared["size_bytes"], "sha256": compared["sha256"]}   # replaced by Lloyd's file since
            else:
                raise SystemExit("%s: the corpus copy is neither the file compare.json compared nor its fresh copy (now %d bytes, "
                                 "SHA-256 %s): run the comparison again" % (stem, size, sha))
        url = row.get("source_url")
        if bool(url) != bool(fresh):
            raise SystemExit("%s: compare.json has %s: the re-fetch is not complete" % (
                stem, "an address and no fresh copy" if url else "a fresh copy and no address"))
        entry = {"stem": "syndicate_" + stem, "syndicate": syndicate, "year": year, "file": path.name,
                 "source_url": url or None}
        if not url:
            entry["source_note"] = ("The scraper (scripts/lloyds_scraper.py) found no address for this filing on Lloyd's site "
                                    "on %s." % long_date(fetched))
        entry["size_bytes"], entry["sha256"] = size, sha
        if not fresh:
            entry["lloyds_copy"] = "not found"
        elif fresh["sha256"] == sha:
            entry["lloyds_copy"] = "matches"
        else:
            entry["lloyds_copy"] = "differs"
            entry["lloyds_size_bytes"], entry["lloyds_sha256"] = fresh["size_bytes"], fresh["sha256"]
            if first_bytes_of(path, folder / str(syndicate) / "pdfs" / fresh["file"]):
                entry["note"] = ("The corpus copy is the first {:,} bytes of the file Lloyd's serves ({:,} bytes): the download "
                                 "was cut short{}.".format(size, fresh["size_bytes"],
                                                           ", and the copy opens with no page" if compared.get("pages") == 0 else ""))
        if earlier:
            kept, cut = earlier_files.pop(stem, None), False
            if kept is not None:
                if (kept.stat().st_size, sha256_of(kept)) != (earlier["size_bytes"], earlier["sha256"]):
                    raise SystemExit("%s: %s is not the earlier copy compare.json gives (%d bytes, SHA-256 %s)"
                                     % (stem, kept, earlier["size_bytes"], earlier["sha256"]))
                cut = first_bytes_of(kept, path)
            else:
                print("note: %s: the corpus copy is the fresh copy, where compare.json compared another file; it is listed as "
                      "replaced, and the earlier copy (%d bytes, SHA-256 %s) is compare.json's word, not checked against a file "
                      "(give it with --earlier-copy)" % (stem, earlier["size_bytes"], earlier["sha256"]), file=sys.stderr)
            entry["earlier_copy"] = earlier
            entry["note"] = replaced_note(stem, earlier, compared.get("pages"), fetched, size, cut)
        entries.append(entry)
    if earlier_files:
        raise SystemExit("--earlier-copy was given for %s, which is not a corpus copy that was replaced" % sorted(earlier_files))
    tally = {kind: sum(1 for e in entries if e["lloyds_copy"] == kind) for kind in ("matches", "differs", "not found")}
    out["counts"] = {"filings": len(entries), "matches": tally["matches"], "differs": tally["differs"],
                     "not_found": tally["not found"]}
    out["filings"] = entries
    return out


def write(path, data):
    """LF line endings on every platform, as the repository's tracked text files have."""
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(json.dumps(data, indent=1, ensure_ascii=False) + "\n")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Build the list of the corpus filings that have no ledger row.")
    ap.add_argument("folder", type=Path, help="the folder holding compare.json (and, if kept, the fresh copies)")
    ap.add_argument("--fetched", required=True, help="the date of the re-fetch, YYYY-MM-DD")
    ap.add_argument("--output", type=Path, default=OUTPUT, help="where to write the list (default: %(default)s)")
    ap.add_argument("--earlier-copy", action="append", default=[], metavar="N_YYYY=PATH",
                    help="the corpus copy of that filing that was replaced, if it is kept; may be repeated")
    args = ap.parse_args(argv)
    try:
        datetime.date.fromisoformat(args.fetched)
    except ValueError:
        ap.error("--fetched must be a date, YYYY-MM-DD")
    earlier_files = {}
    for item in args.earlier_copy:
        stem, _, where = item.partition("=")
        if not re.fullmatch(r"\d+_\d{4}", stem) or not Path(where).is_file():
            ap.error("--earlier-copy must be N_YYYY=PATH, with PATH a file: %r" % item)
        earlier_files[stem] = Path(where)
    data = build(args.folder, args.fetched, earlier_files)
    write(args.output, data)
    c = data["counts"]
    print("wrote %s: %d filings; the file at Lloyd's address matches the corpus copy for %d and differs for %d; no address "
          "found for %d; %d corpus copies replaced since the comparison" % (
              args.output, c["filings"], c["matches"], c["differs"], c["not_found"],
              sum(1 for e in data["filings"] if "earlier_copy" in e)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
