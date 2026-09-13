#!/usr/bin/env python3
"""Scan syndicate annual reports for an inward transfer of PRIOR-YEAR liabilities that is
not reinsurance to close.

Why this exists. The gross claims development triangle is read as this syndicate's own
re-estimation of its own older years: the diagonal comparison assumes the reserves being
compared belong to the same book. Reinsurance to close breaks that assumption, which is
why `ritc_scanner.py` exists and why the fitted model carries a separate RITC regime.

RITC is not the only transaction that breaks it. A loss portfolio transfer, a novation, a
commutation, or a quota share written over prior years moves another party's claims into
(or out of) the triangle just as effectively, and the RITC scanner correctly does not flag
them because they are not reinsurance to close. Round 56 found 81 records whose extraction
notes claim such a transfer and which carry no RITC flag, so the event is neither detected
nor modelled.

This scanner is a sibling of the RITC one and deliberately shares its machinery: the same
page-text loading with the OCR fallback, the same inward/outward classification, the same
event-year rule, the same boilerplate rejection and the same propagation of an event to
the year it takes effect. Only the vocabulary differs. That way a change to how direction
or effective year is decided applies to both, and the two scans are comparable.

What it does NOT do: decide anything about the sample. It records events with their
evidence so the owner can choose -- exclude the affected records, give them an RITC-style
adjustment, or accept them with a stated limitation. Nothing here changes an adopted
figure.

Output: pdf_extraction/portfolio_transfer_scan.json, keyed "{syndicate}_{year}", in the
same shape as ritc_scan.json with `transfer_occurred` in place of `ritc_occurred`.

Usage:
    python scripts/portfolio_transfer_scanner.py            scan every report
    python scripts/portfolio_transfer_scanner.py --limit 20 a sample, for checking
"""
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import ritc_scanner as rs  # noqa: E402

PROJECT_ROOT = HERE.parent
REPORTS_DIR = PROJECT_ROOT / "syndicate_reports" / "pdfs"
OUT_PATH = PROJECT_ROOT / "pdf_extraction" / "portfolio_transfer_scan.json"

#: The transactions. `quota share` alone is ordinary outwards reinsurance on the current
#: book and is far too common to flag, so it is admitted only in prior-year company (see
#: PRIOR below). The others name a transfer of an existing book by construction.
#: Each alternative is bounded, and each takes the plural. Without the leading boundary
#: `novat(?:ion|ed|e)` matches inside "innovation" and "renovation", which is what flagged
#: syndicate 1971's strategy page ("as an innovation leader in the sharing economy space")
#: (R185). Without the plural the trailing boundary blocks "quota shares", which is how
#: 1971/2023 -- "accepted 80% and 90% quota shares of the run-off of the 2019 and 2020
#: years of account" -- stopped being detected when the boundary went in (R186).
TRANSFER_TERM = (r"(?:\bloss portfolio transfers?\b|\bLPTs?\b|\bportfolio transfers?\b|"
                 r"\bnovat(?:ions?|ed|es?)\b|\bcommut(?:ations?|ed|es?)\b|"
                 r"\bquota[- ]shares?\b)")

#: Terms that name a transfer of an EXISTING BOOK by construction. These qualify
#: themselves: nobody novates or commutes next year's premium.
SELF_QUALIFYING = (r"(?:\bloss portfolio transfers?\b|\bLPTs?\b|"
                   r"\bportfolio transfers?\b|\bnovat(?:ions?|ed|es?)\b|"
                   r"\bcommut(?:ations?|ed|es?)\b)")

#: A quota share is the ordinary form of reinsurance on CURRENT business, so it counts
#: only when what it moves is a book of liabilities. 6125/2016 -- a special purpose
#: arrangement that "assumes business by way of variable rate quota share arrangements
#: from Syndicate 4000" -- is the case this excludes; 3500/2021, whose evidence is "the
#: transfer to Syndicate 3500 of gross and net technical provisions" and names no year at
#: all, is the case a prior-year word would have wrongly excluded (round 56).
#: A hyphenated liability word keeps its meaning when a line break splits it: 1971/2023's text
#: layer gives "quota shares of the run- off of the 2019 and 2020 years of account", which
#: `run[- ]?off` did not match, and R201's rescan dropped the record (R203).
LIABILITY_OBJECT = (r"(?:technical provisions?|liabilit(?:y|ies)|reserves?|"
                    r"run(?:-\s?|\s)?off|"
                    r"prior(?:-\s?|\s)(?:year|period|underwriting year)s?|back(?:-\s?|\s)years?|"
                    r"older years?|\d{4}(?: and prior| & prior)|years? of account)")

PRIOR = r"(?:" + SELF_QUALIFYING + r"|" + LIABILITY_OBJECT + r")"

SENTENCE_PATTERNS = [
    ("acceptance", r"accept(?:ed|s|ing)?[^.]{0,120}?" + TRANSFER_TERM),
    ("acceptance", TRANSFER_TERM + r"[^.]{0,120}?(?:accepted|assumed|acquired|received|take[- ]?on)"),
    ("acceptance", r"(?:assum(?:e[ds]?|ing)|acquir(?:e[ds]?|ing))[^.]{0,120}?" + TRANSFER_TERM),
    ("prior_scope", TRANSFER_TERM + r"[^.]{0,120}?" + PRIOR),
    ("prior_scope", PRIOR + r"[^.]{0,120}?" + TRANSFER_TERM),
    ("counterparty", TRANSFER_TERM + r"[^.]{0,80}?syndicate\s*\d+"),
    ("counterparty", r"syndicate\s*\d+[^.]{0,80}?" + TRANSFER_TERM),
    ("amount", TRANSFER_TERM + r"[^.]{0,150}?[£$€]\s?[\d,]+"),
    ("amount", r"[£$€]\s?[\d,]+[^.]{0,150}?" + TRANSFER_TERM),
]

#: A sentence must mention prior-year scope somewhere to count at all. The patterns above
#: catch the phrasing; this is the backstop that keeps a current-year quota share out.
PRIOR_RE = re.compile(PRIOR, re.I)
TERM_RE = re.compile(TRANSFER_TERM, re.I)
SELF_RE = re.compile(SELF_QUALIFYING, re.I)
OBJECT_RE = re.compile(LIABILITY_OBJECT, re.I)


#: What the sentence is about when it is NOT about moving claims. A novation of a
#: managing agent agreement changes who runs the syndicate (2488/2016); a quota share
#: described by the classes of business it covers is this year's reinsurance programme
#: (6125/2016 and 6125/2018, a special purpose arrangement reinsuring another syndicate's
#: current book as its normal operation).
#: A liability word that is the head of a named class of business rather than a stock of
#: obligations. "ibott General Liability class" is a line; "the liabilities of syndicate
#: 1969" is a book. Structural, so a class name this corpus has not shown yet still fails
#: the test: a named class is qualified in front or classified behind (R174).
CLASS_OF_BUSINESS = re.compile(
    r"(?:[A-Z][a-z]+\s+)?Liabilit(?:y|ies)\s+(?:class|account|line|book|binder|treaty)"
    r"|(?:general|public|employers?|products?|professional|motor|marine|aviation|cyber|"
    r"casualty|excess|primary|umbrella)\s+liabilit(?:y|ies)"
    r"|liabilit(?:y|ies)\s+(?:class|account|line|binder|treaty)",
    re.I)

#: A year of account named as a label is a cohort, not a stock of obligations. 6103 labels
#: its quota share of Syndicate 2791's current book that way every year -- "UNDERWRITER'S
#: REPORT 2014 Year of Account", "for the 2016 & 2017 years of account its business was
#: written by way of a 10% quota share" -- and the bare label let each such sentence count as
#: a book transfer once R194 read it as inward (R201). A qualified year of account keeps its
#: meaning: "2017 and prior years of account", "prior years of account", "open years of
#: account" and "the run-off of the 2019 year of account" each still name a book.
YEAR_OF_ACCOUNT_LABEL = re.compile(
    r"(?<!prior )(?<!open )(?<!older )(?<!closed )(?<!earlier )(?<!previous )"
    r"\b(?:(?:19|20)\d\d\s*(?:(?:&|and|to|-)\s*(?:19|20)\d\d\s*)?)?years? of account\b",
    re.I)

NOT_A_BOOK = re.compile(
    r"assumed the management|management of (?:the )?syndicate|managing agent(?:cy)? "
    r"agreement|agency agreement|deed of novation of the manag|"
    r"assumes business|cessions? from [^.]{0,40}on the following types of business",
    re.I)


def _is_a_book_transfer(snippet):
    """Does this sentence move a book of claims?

    Checked before anything else, because a novation of an *agreement* carries a
    self-qualifying word and moves nothing (round 56)."""
    if NOT_A_BOOK.search(snippet):
        return False
    if SELF_RE.search(snippet):
        return True
    if not TERM_RE.search(snippet):
        return False
    # The liability word has to denote a stock of obligations. Strip the occurrences that
    # are the name of a line of business before asking whether any object survives (R174).
    stripped = CLASS_OF_BUSINESS.sub(" ", snippet)
    # ... and the year-of-account labels, which name a cohort (R201)
    stripped = YEAR_OF_ACCOUNT_LABEL.sub(" ", stripped)
    return bool(OBJECT_RE.search(stripped))


#: The shared scanner's pattern lists as imported, before anything is repointed.
#: Kept so that `_install()` is idempotent and so a test can assert what it changed.
_PRISTINE = {}


def _retermed(pattern, old_term, new_term):
    """The same pattern with the scanned-for term swapped."""
    return pattern.replace(old_term, new_term)


def _install():
    """Point the shared machinery at this vocabulary.

    `scan_report` reads SENTENCE_PATTERNS and RITC_TERM as live module globals, so
    repointing those two swaps the detection vocabulary. The direction lists are a
    different matter: `ritc_scanner` builds INWARD_SETTLED, OUTWARD_SETTLED, INWARD_CUES
    and OUTWARD_CUES at import time by concatenating the RITC literal into each pattern,
    and `classify_sentence` consults them. 20 of those 51 patterns embed the literal and
    so could never match a novation or a commutation, which left direction classification
    running on the 31 generic patterns alone (R169).

    Every module-level list of patterns that embeds the term is rebuilt, rather than the
    four found today, so a list added to the shared scanner later cannot go quietly dead
    here.

    This writes onto the loaded `ritc_scanner` module, which Python caches in `sys.modules`
    and `tests/test_ritc_scanner.py` imports as the same object. The file on disk is
    untouched -- the RITC flag is load-bearing for the sample and keeps its own vocabulary
    -- but the runtime state is not, so `_restore()` exists and `scan_all` calls it in a
    finally. Without that, one pytest session that touched both scanners would classify
    RITC direction with transfer vocabulary, silently and in test order (R181)."""
    original_term = _PRISTINE.setdefault("RITC_TERM", rs.RITC_TERM)
    for name in dir(rs):
        if not name.isupper():
            continue
        value = _PRISTINE.get(name, getattr(rs, name))
        if not isinstance(value, list) or not value:
            continue
        if not any(isinstance(p, str) and original_term in p for p in value):
            continue
        _PRISTINE.setdefault(name, value)
        setattr(rs, name, [_retermed(p, original_term, TRANSFER_TERM)
                           if isinstance(p, str) else p for p in value])
    # Record what these two displace. The loop above captures only lists whose strings
    # embed the term, and SENTENCE_PATTERNS is a list of (class, pattern) tuples, so it
    # was overwritten without ever being captured and `_restore()` could not put it back.
    _PRISTINE.setdefault("SENTENCE_PATTERNS", rs.SENTENCE_PATTERNS)
    rs.SENTENCE_PATTERNS = SENTENCE_PATTERNS
    rs.RITC_TERM = TRANSFER_TERM


def _restore():
    """Put the shared scanner back exactly as it was imported."""
    for name, value in _PRISTINE.items():
        setattr(rs, name, value)
    _PRISTINE.clear()


def scan_all(limit=None):
    _install()
    try:
        return _scan_all_installed(limit)
    finally:
        _restore()


def _scan_all_installed(limit=None):
    reports = sorted(REPORTS_DIR.glob("*.pdf"))
    if limit:
        reports = reports[:limit]
    results = {}
    for i, path in enumerate(reports, 1):
        try:
            res = rs.scan_report(path)
        except Exception as exc:                      # a single unreadable filing
            res = {"detection": "failed", "failure_reason": "%s: %s" % (type(exc).__name__, exc)}
        key = path.stem.replace("syndicate_", "")
        # Rename the decision field so nothing downstream can confuse the two scans.
        if "ritc_occurred" in res:
            res["transfer_occurred"] = res.pop("ritc_occurred")
        # Drop an event whose sentence does not move a book of claims: the shared patterns
        # are permissive about counterparties and amounts, and an ordinary current-year
        # quota share must not become a flag.
        before = list(res.get("events") or [])
        kept = [ev for ev in before if _is_a_book_transfer(ev.get("snippet") or "")]
        if len(kept) != len(before):
            # Count what was actually dropped (R170).
            res["n_events_dropped_as_current_year"] = len(before) - len(kept)
        res["events"] = kept
        if res.get("detection") == "successful":
            _decide_on(res, kept, int(key.rsplit("_", 1)[1]), any_mention=bool(before))
        results[key] = res
        if i % 100 == 0:
            print("  %d/%d" % (i, len(reports)), flush=True)
    try:
        rs.propagate(results)
    except Exception as exc:
        print("  propagation skipped: %s" % exc)
    # `propagate()` rebuilds a record from `ritc_scanner._decide`, which names the flag
    # `ritc_occurred`. Rename it and gate it on the events it rests on -- the other reports'
    # inward events for that year -- or a propagated transfer would carry the RITC field and
    # no transfer flag at all (R200).
    by_synd = {}
    for k, r in results.items():
        for e in r.get("events") or []:
            by_synd.setdefault(k.split("_")[0], []).append((k, e))
    for k, r in results.items():
        if "ritc_occurred" not in r:
            continue
        r["transfer_occurred"] = r.pop("ritc_occurred")
        others = [e for kk, e in by_synd.get(k.split("_")[0], []) if kk != k]
        _apply_the_evidence_gate(r, _basis(others, int(k.split("_")[1])))
    return results


def _basis(events, year):
    """The events a flag for `year` rests on: inward, effective that year, not prospective --
    the same selection `ritc_scanner._decide` makes."""
    return [ev for ev in events if ev.get("direction") == "inward"
            and ev.get("event_year") == year and not ev.get("prospective")]


def _apply_the_evidence_gate(res, basis):
    """`counterparty` and `amount` say only that a transfer word stands near a syndicate
    number or a money amount. For RITC that is evidence, because the term is itself a
    prior-year term; for "quota share" it is not (R175). A self-qualifying term is evidence
    on its own: nobody novates or commutes next year's premium (R180). The gate reads the
    events the flag rests on, not every event the report produced (R200)."""
    if not res.get("transfer_occurred"):
        return
    strong = [ev for ev in basis
              if (ev.get("pattern_class") or "") in ("prior_scope", "acceptance")
              or SELF_RE.search(ev.get("snippet") or "")]
    if not strong:
        res["transfer_occurred"] = False
        res["confidence"] = None
        res["evidence"] = None
        res["withdrawn_as_weak_evidence"] = sorted(
            {ev.get("pattern_class") for ev in basis if ev.get("pattern_class")})


#: The fields `ritc_scanner._decide` writes, so a decision replaces them all.
_DECISION_FIELDS = ("ritc_occurred", "transfer_occurred", "confidence", "evidence", "section",
                    "page", "direction", "event_year", "n_strong_hits", "n_weak_hits",
                    "evidence_report")


def _decide_on(res, kept, year, any_mention):
    """Decide the flag from the events that survived the book-transfer filter.

    `scan_report` decides on every event it found, and this scanner then drops the ones that
    do not move a book of claims. The flag used to be reset only when nothing survived or
    nothing strong survived, so it could rest on a dropped event: 1856/2018 was flagged on a
    whole-account quota share of Syndicate 1955's current business, which the filter dropped
    (R200). The decision is the RITC scan's own `_decide`, run on what survived."""
    decided = rs._decide(kept, year, any_mention)
    for field in _DECISION_FIELDS:
        res.pop(field, None)
    decided["transfer_occurred"] = decided.pop("ritc_occurred")
    res.update(decided)
    _apply_the_evidence_gate(res, _basis(kept, year))


def main():
    limit = None
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])
    results = scan_all(limit)
    flagged = [k for k, v in results.items() if v.get("transfer_occurred")]
    failed = [k for k, v in results.items() if v.get("detection") == "failed"]
    payload = dict(sorted(results.items()))
    payload["_meta"] = {
        "purpose": ("An inward transfer of prior-year liabilities that is not reinsurance "
                    "to close: a loss portfolio transfer, novation, commutation or a quota "
                    "share written over prior years. Such a transfer puts another party's "
                    "claims into the gross development triangle, so the diagonal is not "
                    "purely this syndicate's own re-estimation."),
        "sibling": ("Shares ritc_scanner.py's page-text loading, direction and event-year "
                    "classification, boilerplate rejection and propagation; only the "
                    "vocabulary differs."),
        "decides_nothing": ("This flag changes no adopted figure. It exists so the records "
                            "can be excluded, adjusted like RITC, or accepted with a stated "
                            "limitation -- an owner's decision, recorded separately."),
        "n_reports": len(results),
        "n_flagged": len(flagged),
        "n_detection_failed": len(failed),
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8", newline="") as fh:
        json.dump(payload, fh, indent=1, ensure_ascii=False)
        fh.write("\n")
    print("scanned %d report(s): %d flagged, %d detection failure(s)"
          % (len(results), len(flagged), len(failed)))
    print("wrote %s" % OUT_PATH)
    return 0


if __name__ == "__main__":
    sys.exit(main())
