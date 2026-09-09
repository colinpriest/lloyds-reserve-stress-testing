"""Scan syndicate annual reports for RITC (reinsurance to close) occurrence.

For each syndicate-year, decide whether the syndicate ACCEPTED another syndicate's
or year of account's liabilities by reinsurance to close with effect in that
calendar year. That is the event that distorts prior-year development: the accepted
reserves develop in the year while the opening reserve they are measured against
excludes them. An outgoing closure into another syndicate, the routine closure of
the syndicate's own years into its own next year, an illustrative-share results
table, and the accounting-policy description of RITC are not that event.

Every RITC sentence is classified as an event (round 54):

    direction    inward (accepted, take-on, received, reinsured INTO this
                 syndicate), outward (premium payable, closed INTO another
                 syndicate), internal (into the syndicate's own year of account),
                 or unclear
    event_year   the calendar year the transaction takes effect: a date in the
                 sentence ("effective 1 January 2021" -> 2021; "at 31 December
                 2019" -> 2020, the opening of the next year); with no date, the
                 report year, unless the sentence is prospective ("will", "is to
                 accept", "intention", a post-balance-sheet note), when the
                 event has no year of its own and flags nothing

A syndicate-year is flagged when an inward event is effective in that year, read
from ANY of the syndicate's reports (the 2020 report's "effective 1 January 2021,
the Syndicate accepted ..." flags 2021, not 2020). Confidence is strong when the
inward event carries an acceptance verb or a dated inward transfer, weak when it
rests on an amount-adjacent inward cue only.

Output: pdf_extraction/ritc_scan.json keyed "{syndicate}_{year}":
    {
      "detection": "successful" | "failed",
      "ritc_occurred": true | false,       # inward event effective this year
      "confidence": "strong" | "weak",
      "evidence": "<text snippet of the deciding event>",
      "section": "<note/section heading>",
      "page": <int>,
      "direction": "inward" | ...,          # of the deciding event
      "event_year": <int>,
      "evidence_report": "{syndicate}_{year}" of the report the event was read from
      "events": [ {page, direction, event_year, prospective, counterparty,
                   strength, snippet, section}, ... ],   # every RITC sentence
      "failure_reason": "..."              # only when detection failed
    }

Usage:
    python scripts/ritc_scanner.py                 # scan all reports, resumable
    python scripts/ritc_scanner.py --rescan        # re-scan everything
    python scripts/ritc_scanner.py --single 1176_2022
"""

import argparse
import json
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import fitz  # PyMuPDF

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PDF_DIR = PROJECT_ROOT / "syndicate_reports" / "pdfs"
OCR_CACHE_DIR = PROJECT_ROOT / "pdf_extraction" / "ocr_page_cache"
OUTPUT_PATH = PROJECT_ROOT / "pdf_extraction" / "ritc_scan.json"
LOG_PATH = PROJECT_ROOT / "pdf_extraction" / "ritc_scan.log"

MIN_DOC_CHARS = 500  # below this the PDF is treated as scanned/no text

# Sentences that speak of a reinsurance to close. Each is classified below by
# direction and effective year; the pattern class no longer decides the flag.
RITC_TERM = r"(?:reinsurance[- ]to[- ]close|reinsured[- ]to[- ]close|\bRITC\b)"
SENTENCE_PATTERNS = [
    ("premium_flow", RITC_TERM + r"[^.]{0,60}?premium|premium[^.]{0,60}?" + RITC_TERM),
    ("acceptance", r"accept(?:ed|s|ing)?[^.]{0,120}?" + RITC_TERM),
    ("acceptance", RITC_TERM + r"[^.]{0,120}?(?:accepted|assumed|acquired|received|take[- ]?on|received)"),
    ("acceptance", r"(?:accepted|assumed|acquired)[^.]{0,120}?(?:by way of|through|under|via) (?:a )?" + RITC_TERM),
    ("counterparty", RITC_TERM + r"[^.]{0,80}?syndicate\s*\d+"),
    ("counterparty", r"syndicate\s*\d+[^.]{0,80}?" + RITC_TERM),
    ("closure", r"year(?:s)? of account[^.]{0,80}?" + RITC_TERM),
    ("closure", RITC_TERM + r"[^.]{0,80}?year(?:s)? of account"),
    ("closure", r"closed by " + RITC_TERM),
    ("amount", RITC_TERM + r"[^.]{0,150}?[£$€]\s?[\d,]+"),
    ("amount", r"[£$€]\s?[\d,]+[^.]{0,150}?" + RITC_TERM),
    ("amount", r"\bRITC\b[^.]{0,100}?[\d,]{4,}"),
]

# Direction cues, evaluated on the sentence around the match. OWN is replaced by
# the syndicate's own number; OTHER matches any syndicate number but the own one.
# Constructions that settle the direction on their own: an acceptance OF another
# syndicate's business, or another syndicate's business closing INTO this one
INWARD_SETTLED = [
    r"(?:accept(?:ed|s|ing)?|assum(?:e[ds]?|ing)|acquir(?:e[ds]?|ing)|(?:take[- ]?on|took on|taking on)(?! (?:the )?management))[^.]{0,120}?(?:of|from) (?:the )?(?:liabilities|reserves|business|portfolio|run-off|\d{4}(?: and prior| & prior)? (?:years? of account|underwriting years?|pure year))?[^.]{0,60}?syndicates?\s*OTHER",
    r"transfer(?:red)? to (?:the |this )?syndicates?\s*(?:OWN\b|\b(?!s?\s*\d))[^.]{0,20}?of (?:gross|net|the )?[^.]{0,40}?(?:technical provisions|liabilities|reserves)",
    r"(?:accept(?:ed|s|ing)?|assum(?:e[ds]?|ing)|acquir(?:e[ds]?|ing))[^.]{0,60}?" + RITC_TERM + r"[^.]{0,60}?(?:of|from) syndicates?\s*OTHER",
    r"syndicates?\s*OTHER[^.]{0,120}?" + RITC_TERM + r"[^.]{0,80}?(?:into|to) (?:the |this )?syndicate\b(?!s?\s*\d)",
    r"syndicates?\s*OTHER[^.]{0,120}?(?:into|to) (?:the |its |this )?(?:\d{4} )?(?:underwriting )?year of account of (?:the |host )?syndicates?\s*OWN\b",
    r"(?:of|from) syndicates?\s*OTHER[^.]{0,80}?(?:transferred|reinsured) (?:in)?to (?:the |this )?syndicates?\s*(?:OWN\b|\b(?!\d))",
    r"(?:reinsured|reinsurance) to close (?:premium )?(?:received|receivable)[^.]{0,60}?(?:from|in respect of|relating to) syndicates?\s*OTHER",
    r"\bwas accepted as an? RITC\b",
    # a premium paid or payable TO this syndicate is a premium it receives
    r"(?:pay|paid|payable|pays)[^.]{0,60}?" + RITC_TERM + r"[^.]{0,40}?premium[^.]{0,40}?to (?:the |this )?syndicates?\s*OWN\b",
    r"(?:pay|paid|payable|pays)[^.]{0,60}?" + RITC_TERM + r"[^.]{0,40}?premium[^.]{0,40}?to (?:the |this )?syndicate\b(?!s?\s*\d)",
    r"\bRITC take[- ]?on\b|\btake[- ]?on (?:balance|reserves)\b|\binwards? RITC\b|\btake[- ]?on balances? of the RITC\b",
]
# ... or this syndicate's business closing INTO, or assumed BY, another syndicate
OUTWARD_SETTLED = [
    r"(?:assumed|accepted|acquired|reinsured|written|reinsured to close) by syndicates?\s*OTHER",
    r"(?:closed?|closure|closing|reinsured?|reinsurance|transferr?(?:ed|ing)?|" + RITC_TERM + r")[^.]{0,80}?(?:into|to) (?:the [^.]{0,60}?|an? (?:external )?(?:party|third party)[^.]{0,20}?)?syndicates?\s*OTHER(?![^.]{0,60}?(?:into|to) (?:the |this )?syndicates?\s*OWN)",
    r"premium payable(?! to (?:the |this )?syndicate\b(?!s?\s*\d))",
    r"payable by (?:the )?(?:syndicate|members?)",
    r"externally " + RITC_TERM + r"|closed? externally",
    r"closed? by way of an external " + RITC_TERM + r"|external " + RITC_TERM + r" agreement",
]
INWARD_CUES = [
    r"accept(?:ed|s|ing)?\b[^.]{0,80}?" + RITC_TERM,
    r"\bwas accepted as an? RITC\b",
    RITC_TERM + r"[^.]{0,40}?(?:received|receivable)\b",
    r"\binwards? " + RITC_TERM,
    r"\b(?:take[- ]?on|took on|taking on)\b(?! (?:the )?management)",
    r"(?:acquire[ds]?|acquiring|assum(?:e[ds]?|ing))[^.]{0,120}?" + RITC_TERM,
    RITC_TERM + r"[^.]{0,120}?(?:acquire[ds]?|assum(?:e[ds]?|ing))[^.]{0,40}?(?:liabilities|reserves|portfolio|book|business|division)",
    r"transferr?ed (?:in)?to (?:the |this )?syndicate\b(?!\s*\d)",
    r"transfer to syndicate\s*OWN\b",
    r"(?:into|to|with) (?:the |this )?syndicate\s*OWN\b",
    r"(?:into|to) (?:the |its |this )?(?:syndicate'?s )?(?:\d{4} )?(?:underwriting )?year of account of (?:the |host )?syndicate\s*OWN\b",
    r"reinsured (?:in)?to (?:the |this )?syndicate\b(?!\s*\d)",
    r"(?:of|from) syndicate\s*OTHER[^.]{0,80}?(?:into|to) (?:the |its |this )?(?:syndicate'?s |own )?(?:\d{4} )?year",
    RITC_TERM + r" (?:of|from) (?:the )?(?:\d{4}(?: and prior)? (?:years? of account|underwriting years?) of )?syndicate\s*OTHER",
    r"the " + RITC_TERM + r" of (?:the )?(?:liabilities|reserves) of syndicate\s*OTHER",
    RITC_TERM + r" of (?:the )?(?:liabilities|reserves|\d{4}(?: and prior)? (?:years? of account|underwriting years?)) of syndicate\s*OTHER",
    r"syndicate\s*OTHER[^.]{0,60}?" + RITC_TERM + r"[^.]{0,60}?(?:into|to) (?:the |this )?syndicate\b(?!\s*\d)",
]
OUTWARD_CUES = [
    r"premium payable",
    r"payable by (?:the )?(?:syndicate|members?)",
    r"(?:closed?|closure|closing|reinsured?|reinsurance)[^.]{0,80}?(?:into|to) (?:the [^.]{0,60}?)?syndicate\s*OTHER",
    RITC_TERM + r"[^.]{0,40}?(?:into|to) (?:the [^.]{0,60}?)?syndicate\s*OTHER",
    r"(?:reinsured|closed) to close by syndicate\s*OTHER",
    r"by syndicate\s*OTHER\b",
    r"transferr?(?:ed|ing)?[^.]{0,80}?(?:through|by way of|via|by) (?:a )?" + RITC_TERM + r"[^.]{0,60}?to (?:an? external party|syndicate\s*OTHER)",
    r"externally " + RITC_TERM + r"|external " + RITC_TERM + r"[^.]{0,80}?to an external party|closed? externally",
    r"ceded[^.]{0,60}?" + RITC_TERM,
    r"(?:into|to) (?:the |this )?syndicate\s*OTHER'?s?\b",
]
INTERNAL_CUES = [
    r"(?:into|to) (?:the |its |this )?(?:syndicate'?s |own )?(?:\d{4} |following |next |subsequent |succeeding )(?:underwriting )?year(?:s)? of account\b(?![^.]{0,40}?of (?:host )?syndicate)",
    r"(?:into|to) (?:the |its )?(?:following|next|subsequent|succeeding) (?:underwriting )?year",
    r"from (?:an |the )?earlier (?:underwriting )?y\s?ears? of account",
    r"(?:received|receivable) from (?:the |an )?(?:earlier|previous|prior) (?:underwriting )?years?",
    r"(?:into|to) (?:the |its |this )?syndicate'?s (?:own )?(?:\d{4} )?(?:underwriting )?year",
    r"reinsured to close into (?:the |its )?(?:\d{4} )?year",
    r"(?:between|of) (?:the |its )?own years? of account",
]
# The same sentence describing a transaction that has not taken effect at the
# balance-sheet date: an intention, or a post-balance-sheet event.
PROSPECTIVE_CUES = [
    r"\bwill\b", r"\bis to accept\b", r"\bintend(?:s|ed)?\b|\bintention\b", r"\bexpected to\b",
    r"\bpost[- ]balance[- ]sheet\b", r"\bsubsequent to the (?:balance sheet|year end)\b",
    r"\bafter the (?:balance sheet|year end|reporting date)\b", r"\bproposed\b", r"\bis anticipated\b",
]
# Accounting-policy and illustrative-share contexts: never an occurrence.
BOILERPLATE_HINTS = [
    "accounting policy", "accounting policies", "basis of preparation",
    "is a contract", "represents a contract", "premium payable to close an underwriting year",
    "the amount charged as", "estimation techniques", "critical accounting",
    "determined by the managing agent, generally", "generally closed by reinsurance",
    "results for illustrative share", "illustrative share", "results for £10,000",
    "not included in premiums written as the net value",
]
MONTHS = r"(?:january|february|march|april|may|june|july|august|september|october|november|december)"
DATE_RE = re.compile(
    r"(?P<day>\d{1,2})(?:st|nd|rd|th)?\s+(?P<month>" + MONTHS + r")\s+(?P<year>(?:19|20)\d\d)"
    r"|(?P<month2>" + MONTHS + r")\s+(?P<year2>(?:19|20)\d\d)"
    r"|(?:effective|with effect from|as (?:at|from|of)|from|during|in|at the end of|at)\s+(?P<year3>(?:19|20)\d\d)\b",
    re.I)

logger = logging.getLogger(__name__)


def setup_logging() -> None:
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    fh = logging.FileHandler(LOG_PATH, mode='a', encoding='utf-8')
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S'))
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))
    root.addHandler(fh)
    root.addHandler(ch)


def load_page_texts(report_path: Path) -> Optional[List[str]]:
    """Extract per-page text. Uses the OCR page cache when the PDF has no
    text layer and cached OCR results exist. Returns None if no usable text."""
    if report_path.suffix.lower() in ('.html', '.htm'):
        from bs4 import BeautifulSoup
        with open(report_path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
        # iXBRL reports are XHTML with an XML declaration — use the XML
        # parser for those; plain HTML otherwise
        parser = 'lxml-xml' if content.lstrip().startswith('<?xml') else 'lxml'
        soup = BeautifulSoup(content, parser)
        for tag in soup(['script', 'style']):
            tag.decompose()
        text = soup.get_text(separator='\n', strip=True)
        return [text] if len(text) >= MIN_DOC_CHARS else None

    doc = fitz.open(report_path)
    try:
        pages = [page.get_text() for page in doc]
    finally:
        doc.close()

    if sum(len(p) for p in pages) >= MIN_DOC_CHARS:
        return pages

    # Try OCR page cache (populated by the extraction pipeline):
    # one JSON per report, a list of {"page": <1-based int>, "text": str}
    cache_file = OCR_CACHE_DIR / f"{report_path.stem}.json"
    if cache_file.exists():
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                entries = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"OCR cache unreadable for {report_path.name}: {e}")
            entries = []
        page_map: Dict[int, str] = {}
        for e in entries:
            if isinstance(e, dict) and isinstance(e.get('page'), int):
                page_map[e['page']] = e.get('text') or ''
        if page_map:
            n = max(page_map)
            ocr_pages = [page_map.get(i, '') for i in range(1, n + 1)]
            if sum(len(p) for p in ocr_pages) >= MIN_DOC_CHARS:
                return ocr_pages
    return None


_DANGLING_ENDINGS = (
    'the', 'a', 'an', 'of', 'for', 'and', 'or', 'to', 'in', 'on', 'by',
    'with', 'from', 'as', 'at', 'is', 'are', 'was', 'were', 'its',
)


def _looks_like_heading(line: str) -> bool:
    """Heuristic: is this line a standalone note/section heading rather than
    a fragment of wrapped body text?"""
    # Explicit note / numbered headings always qualify
    if re.match(r'^(note\s+\d+\b|\d{1,2}[\.\)]\s+[A-Z])', line, re.I):
        return True
    if len(line) > 70:
        return False
    words = line.split()
    if not words or len(words) > 8:
        return False
    # Wrapped body text usually ends mid-phrase
    if words[-1].lower().rstrip(':,') in _DANGLING_ENDINGS:
        return False
    if line.endswith((',', ';', '-')):
        return False
    # All-caps titles qualify
    if line.upper() == line and any(c.isalpha() for c in line):
        return True
    # Title-ish: starts capitalised, majority of significant words capitalised
    if not line[0].isupper():
        return False
    caps = sum(1 for w in words if w[0].isupper())
    return caps / len(words) >= 0.5


def find_section_heading(page_text: str, match_pos: int) -> Optional[str]:
    """Find the nearest note/section heading above a match position."""
    before = page_text[:match_pos]
    lines = [ln.strip() for ln in before.split('\n')]
    for line in reversed(lines):
        if not line:
            continue
        # Numeric-only or page-number-ish lines are not headings
        if re.fullmatch(r'[\d,.\s()%£$€-]+', line):
            continue
        low = line.lower()
        # Skip obvious running headers/footers
        if low.startswith(('syndicate ', 'annual report', 'annual accounts',
                           'report and accounts', 'year ended',
                           'notes to the', 'for the year ended')):
            continue
        if _looks_like_heading(line):
            return line
    return None


def is_boilerplate_context(page_text: str, match_pos: int) -> bool:
    """Check whether a match sits inside accounting-policy boilerplate."""
    lo = max(0, match_pos - 1500)
    context = page_text[lo:match_pos + 500].lower()
    return any(h in context for h in BOILERPLATE_HINTS)


def _sentence_around(text: str, start: int, end: int, before: int = 300, after: int = 400) -> Tuple[int, int]:
    """The sentence containing [start, end): back to the previous full stop that is
    followed by whitespace, forward to the next one, but never more than `before`
    characters before the match or `after` after it. Tables carry no full stops, so
    an unbounded window on a notes page swallowed a whole reconciliation table and
    its footnotes, and the date nearest the first RITC term in that window was a
    table row's, not the footnote's (round 54)."""
    lo = start
    while lo > 0 and start - lo < before:
        if text[lo - 1] == "." and text[lo:lo + 1].isspace():
            break
        lo -= 1
    hi = end
    while hi < len(text) and hi - end < after:
        if text[hi] == "." and (hi + 1 >= len(text) or text[hi + 1].isspace()):
            hi += 1
            break
        hi += 1
    return lo, hi


def _display_snippet(sent: str, anchor: int, before: int = 160, after: int = 240) -> str:
    """The evidence a reader sees: the matched wording with its surroundings,
    starting at a sentence or footnote boundary where one lies within `before`
    characters (a table's numbers before the footnote are not evidence)."""
    s = re.sub(r"\s+", " ", sent)
    a = len(re.sub(r"\s+", " ", sent[:anchor]))
    lo = max(0, a - before)
    m = None
    for m in re.finditer(r"(?:\. |: |\d \d{4} RITC|Note \d+ )", s[lo:a]):
        pass
    if m is not None:
        lo = lo + m.start() + (2 if m.group(0) in (". ", ": ") else 0)
    return s[lo:a + after].strip()[:400]


def _sub_own(pattern: str, own: Optional[str]) -> str:
    """OWN -> this syndicate's number; OTHER -> any other number."""
    own_re = re.escape(own.lstrip("0")) if own else r"(?!x)x"
    other_re = r"(?!0*%s\b)\d+" % own_re if own else r"\d+"
    return (pattern.replace("syndicate\s*OTHER", "syndicates?\s*OTHER")
            .replace("syndicate\s*OWN", "syndicates?\s*OWN")
            .replace("OTHER", other_re).replace("OWN", r"0*" + own_re))


def _any(cues: List[str], sent: str, own: Optional[str]) -> Optional[str]:
    for c in cues:
        if re.search(_sub_own(c, own), sent, re.I):
            return c
    return None


def _all_others(sent: str, own: Optional[str]) -> List[str]:
    out = []
    for m in re.finditer(r"syndicates?\s*(?:no\.?\s*)?(\d+)", sent, re.I):
        n = m.group(1).lstrip("0")
        if (own is None or n != own.lstrip("0")) and n not in out:
            out.append(n)
    return out


def _named_other(sent: str, own: Optional[str]) -> Optional[str]:
    for m in re.finditer(r"syndicates?\s*(?:no\.?\s*)?(\d+)", sent, re.I):
        n = m.group(1).lstrip("0")
        if own is None or n != own.lstrip("0"):
            return n
    return None


def _event_year(sent: str, report_year: int, anchor: Optional[int] = None) -> Tuple[Optional[int], bool, bool]:
    """(effective year, dated, prospective). A dated sentence takes its year from
    the date nearest the matched RITC wording (within 250 characters of it):
    '31 December Y' is the opening of Y+1. An undated prospective sentence has no
    year of its own."""
    prospective = any(re.search(p, sent, re.I) for p in PROSPECTIVE_CUES)
    if anchor is None:
        term = re.search(RITC_TERM, sent, re.I)
        anchor = term.start() if term else 0
    best, best_d = None, None
    for m in DATE_RE.finditer(sent):
        if abs(m.start() - anchor) > 250:
            continue
        # a statement or page heading's period-end date is not an event date
        if re.search(r"(?:year|period|months)\s+ended\s*$|\bpage \d+ of \d+\s*$|"
                     r"(?:accounts|report|statements|financial statements)\s*$", sent[max(0, m.start() - 24):m.start()], re.I):
            continue
        y = int(m.group("year") or m.group("year2") or m.group("year3"))
        day = m.group("day")
        month = (m.group("month") or m.group("month2") or "").lower()
        if day and int(day) == 31 and month == "december":
            y += 1
        d = abs(m.start() - anchor)
        if best is None or d < best_d:
            best, best_d = y, d
    if best is not None:
        return best, True, prospective
    if prospective:
        return None, False, True
    return report_year, False, False


def classify_sentence(sent: str, own: Optional[str], report_year: int, anchor: Optional[int] = None) -> dict:
    """One RITC sentence as an event: direction, effective year, counterparty.
    `anchor` is the offset of the matched RITC wording within `sent`.

    Precedence: a construction that settles the direction (an acceptance OF another
    syndicate's business; this syndicate's business closing INTO or assumed BY
    another) beats a bare cue; a bare inward cue counts only with a counterparty
    or a take-on/inwards wording (a generic "exposure accepted via RITC" line,
    repeated in every report, names nothing and flags nothing); "received" or
    "receivable" alone is the next year of account's routine acceptance."""
    if anchor is not None:
        anchor = len(re.sub(r"\s+", " ", sent[:anchor]).lstrip())
    s = re.sub(r"\s+", " ", sent).strip()
    other = _named_other(s, own)
    others = _all_others(s, own)
    self_ref = bool(re.search(r"\b(?:the|this|our) syndicate\b(?!s?\s*\d)|\bwe\b|\bour\b|^\s*(?:it|its)\b|"
                              r"\bits (?:\d{4} )?(?:underwriting )?year of account|"
                              r"\bthe \d{4} (?:underwriting )?year of account (?:has |had )?(?:accepted|assumed|acquired)", s, re.I)
                    or (own and re.search(r"syndicates?\s*0*%s\b" % re.escape(own.lstrip("0")), s, re.I)))
    if re.search(r"\bno element of\b|\bdoes not (?:participate|form|include)|\bdid not (?:accept|enter)|\bno (?:RITC|reinsurance to close) (?:contracts?|transactions?)[^.]{0,40}?(?:were|was) (?:underwritten|entered|accepted)", s, re.I):
        year, dated, prospective = _event_year(s, report_year, anchor)
        return {"direction": "negated", "event_year": None, "dated": dated,
                "prospective": prospective, "counterparty": other}
    if len(others) >= 2 and not self_ref:
        # a managing agent's disclosure of its other syndicates' transactions
        # ("Asta reinsured to close Syndicate 1980 into Riverstone Syndicate 3500")
        return {"direction": "third_party", "event_year": None, "dated": False,
                "prospective": False, "counterparty": other}
    in_settled = _any(INWARD_SETTLED, s, own)
    out_settled = _any(OUTWARD_SETTLED, s, own)
    internal = _any(INTERNAL_CUES, s, own)
    inward = _any(INWARD_CUES, s, own)
    outward = _any(OUTWARD_CUES, s, own)
    if in_settled and not out_settled:
        direction = "inward"
    elif out_settled and not in_settled:
        direction = "outward"
    elif in_settled and out_settled:
        # both: "the 2017 and prior years of Syndicate 6133 reinsured to close into
        # the syndicate ... transferred to Syndicate 1994": the acceptance names its
        # object, the closure names its destination; take the one nearer the anchor
        a = anchor or 0
        di = min((abs(m.start() - a) for c in INWARD_SETTLED for m in re.finditer(_sub_own(c, own), s, re.I)), default=10**6)
        do = min((abs(m.start() - a) for c in OUTWARD_SETTLED for m in re.finditer(_sub_own(c, own), s, re.I)), default=10**6)
        direction = "inward" if di <= do else "outward"
    elif internal and other is None:
        direction = "internal"
    elif inward and (other is not None or re.search(r"take[- ]?on|inwards? RITC", s, re.I)):
        # a bare inward cue with a counterparty but no acceptance construction: a
        # heading, a fragment, a historical mention. Recorded, never a flag.
        direction = "unclear"
    elif outward:
        direction = "outward"
    elif inward or internal:
        direction = "unclear"
    else:
        direction = "unclear"
    year, dated, prospective = _event_year(s, report_year, anchor)
    if not dated:
        # a receiving year of account named without a date: at Lloyd's a year of
        # account closes at 36 months, so business reinsured INTO the Y year of
        # account arrives at the start of Y+2 ("Syndicate 807 ... reinsured to close
        # into the 2012 year of account of Syndicate 510" happened for 2014, and
        # the sentence recurs in every later report of Syndicate 510)
        m = re.search(r"(?:into|to) (?:the |its |this )?(?:[^.]{0,40}?syndicates?\s*\d+'?s )?(?:syndicate'?s )?((?:19|20)\d\d) (?:underwriting )?year of account", s, re.I)
        if m and direction in ("inward", "outward", "internal"):
            year, dated = int(m.group(1)) + 2, "yoa"
    return {"direction": direction, "event_year": year, "dated": dated,
            "prospective": prospective, "counterparty": other}


def scan_report(report_path: Path) -> dict:
    """Every RITC sentence of one report as an event, and the report-year flag from
    its own inward events. Cross-report propagation is applied in main()."""
    pages = load_page_texts(report_path)
    if pages is None:
        return {
            'detection': 'failed',
            'failure_reason': 'no extractable text (likely scanned PDF without OCR cache)',
        }
    own_syndicate, report_year = None, None
    m_own = re.match(r'syndicate_(\d+)_(\d{4})', report_path.name)
    if m_own:
        own_syndicate, report_year = m_own.group(1), int(m_own.group(2))

    # Combined reports append the underwriting-year (closed YOA) accounts at
    # the end, where RITC between the syndicate's own years is routine.
    first_uw_page = None
    for page_no, text in enumerate(pages, start=1):
        if re.search(r'underwriting year (?:distribution )?accounts'
                     r'|36 months ended'
                     r'|closed year of account', text, re.I):
            first_uw_page = page_no
            break

    events: List[dict] = []
    any_mention = False
    seen = set()
    for page_no, text in enumerate(pages, start=1):
        if not re.search(RITC_TERM, text, re.I):
            continue
        any_mention = True
        is_uw_year_page = (
            (first_uw_page is not None and page_no >= first_uw_page)
            or len(re.findall(r'year of account', text, re.I)) >= 2)
        for pclass, pattern in SENTENCE_PATTERNS:
            for m in re.finditer(pattern, text, re.I):
                lo, hi = _sentence_around(text, m.start(), m.end())
                key = (page_no, lo // 40)
                if key in seen:
                    continue
                seen.add(key)
                if is_boilerplate_context(text, m.start()):
                    continue
                sent = text[lo:hi]
                ev = classify_sentence(sent, own_syndicate, report_year or 0, anchor=m.start() - lo)
                # inside the closed-year accounts, an own-year closure is routine,
                # and a premium "receivable" with no other syndicate named is the
                # next year of account's routine acceptance of this one
                if is_uw_year_page and (ev["direction"] in ("internal", "unclear")
                                        or (ev["direction"] == "inward"
                                            and not (ev["counterparty"] is not None
                                                     and _any(INWARD_SETTLED, re.sub(r"\s+", " ", sent), own_syndicate)))):
                    continue
                strength = ("strong" if ev["direction"] == "inward"
                            and (ev["dated"] is True or _any(INWARD_SETTLED, re.sub(r"\s+", " ", sent), own_syndicate))
                            else "weak")
                ev.update({
                    "page": page_no,
                    "pattern_class": pclass,
                    "strength": strength,
                    "snippet": _display_snippet(sent, m.start() - lo),
                    "section": find_section_heading(text, m.start()) or f'p.{page_no} (heading not identified)',
                })
                events.append(ev)

    # an undated sentence naming a counterparty inherits the year of a dated
    # event for the same counterparty in this report ("the premium received in
    # respect of Syndicate 1318 was ..." beside "agreed on 6 February 2014")
    dated_years = {}
    for e in events:
        if e["dated"] and e["counterparty"] and e["direction"] == "inward" and not e["prospective"]:
            dated_years.setdefault(e["counterparty"], e["event_year"])
    for e in events:
        if not e["dated"] and e["counterparty"] in dated_years:
            e["event_year"], e["dated"] = dated_years[e["counterparty"]], "inherited"
    # an undated inward sentence naming no counterparty describes the report's
    # dated acceptance when the dated inward events agree on one year
    years = set(dated_years.values())
    if len(years) == 1:
        (y0,) = years
        for e in events:
            if not e["dated"] and e["counterparty"] is None and e["direction"] == "inward":
                e["event_year"], e["dated"] = y0, "inherited"
    result = _decide(events, report_year, any_mention)
    result["events"] = events
    return result


def _decide(events: List[dict], year: Optional[int], any_mention: bool, source: Optional[str] = None) -> dict:
    """The flag for one syndicate-year from a list of events (its own report's, or
    every report's for that syndicate): an inward event effective in that year."""
    inward = [e for e in events if e["direction"] == "inward" and e["event_year"] == year
              and not e.get("prospective")]
    if inward:
        strong = [e for e in inward if e["strength"] == "strong"]

        def _rank(e):
            s = e["snippet"]
            digits = sum(c.isdigit() for c in s) / max(1, len(s))
            verb = 1 if re.search(r"accept|take[- ]?on|acquir|assum|inwards", s, re.I) else 0
            return (e["strength"] == "strong", verb, e["dated"] is True, bool(e["dated"]), -digits)
        best = max(inward, key=_rank)
        out = {
            'detection': 'successful',
            'ritc_occurred': True,
            'confidence': 'strong' if strong else 'weak',
            'evidence': best["snippet"],
            'section': best["section"],
            'page': best["page"],
            'direction': 'inward',
            'event_year': year,
            'n_strong_hits': len(strong),
            'n_weak_hits': len(inward) - len(strong),
        }
        if source:
            out['evidence_report'] = source
        return out
    kinds = {e["direction"] for e in events}
    if events:
        if kinds & {"outward"}:
            evidence = 'RITC mentioned: outgoing closure into another syndicate, no acceptance effective this year'
        elif kinds & {"internal"}:
            evidence = 'routine inter-YOA RITC only (own-syndicate closure); no external acceptance found'
        elif any(e["direction"] == "inward" for e in events):
            evidence = 'an acceptance is described but takes effect in another year (see events)'
        else:
            evidence = 'RITC mentioned without a classifiable direction (see events)'
        confidence = 'weak' if any(e["direction"] in ("unclear",) for e in events) else 'strong'
    elif any_mention:
        evidence, confidence = 'RITC mentioned only in accounting-policy boilerplate', 'strong'
    else:
        evidence, confidence = 'no RITC reference in report', 'strong'
    return {
        'detection': 'successful',
        'ritc_occurred': False,
        'confidence': confidence,
        'evidence': evidence,
        'section': 'whole document scan',
        'page': None,
    }


def propagate(results: Dict[str, dict]) -> int:
    """A syndicate-year is flagged by an inward event effective that year in ANY of
    the syndicate's reports. Returns the number of keys whose flag changed."""
    by_synd: Dict[str, List[Tuple[str, dict]]] = {}
    for key, r in results.items():
        s = key.split("_")[0]
        for e in r.get("events") or []:
            by_synd.setdefault(s, []).append((key, e))
    changed = 0
    for key, r in results.items():
        if r.get("detection") != "successful":
            continue
        s, y = key.split("_")[0], int(key.split("_")[1])
        own_inward = [e for e in (r.get("events") or [])
                      if e["direction"] == "inward" and e["event_year"] == y and not e.get("prospective")]
        if own_inward:
            continue
        others = [(k, e) for k, e in by_synd.get(s, []) if k != key
                  and e["direction"] == "inward" and e["event_year"] == y and not e.get("prospective")]
        if others:
            k0, e0 = others[0]
            new = _decide([e for _, e in others], y, True, source=k0)
            new["events"] = r.get("events") or []
            new["scanned_at"] = r.get("scanned_at")
            new["file"] = r.get("file")
            if not r.get("ritc_occurred"):
                changed += 1
            results[key] = new
    return changed


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan reports for RITC occurrence")
    parser.add_argument("--rescan", action="store_true",
                        help="Re-scan reports already in the output file")
    parser.add_argument("--single", type=str, default=None,
                        help="Scan a single report, e.g. 1176_2022")
    args = parser.parse_args()

    setup_logging()

    results: Dict[str, dict] = {}
    if OUTPUT_PATH.exists():
        with open(OUTPUT_PATH, 'r', encoding='utf-8') as f:
            results = json.load(f)

    reports = sorted(
        p for p in PDF_DIR.iterdir()
        if re.match(r'syndicate_\d+_\d{4}\.(pdf|html?)$', p.name, re.I))
    if args.single:
        reports = [p for p in reports if args.single in p.name]
        if not reports:
            logger.error(f"No report matching {args.single}")
            return 1

    scanned = 0
    for report_path in reports:
        m = re.match(r'syndicate_(\d+)_(\d{4})', report_path.name)
        key = f"{m.group(1)}_{m.group(2)}"
        if key in results and not args.rescan:
            continue
        try:
            result = scan_report(report_path)
        except Exception as e:
            logger.error(f"Scan crashed for {report_path.name}: {e}")
            result = {'detection': 'failed', 'failure_reason': f'scan error: {e}'}
        result['scanned_at'] = datetime.now(timezone.utc).isoformat()
        result['file'] = report_path.name
        results[key] = result
        scanned += 1
        if scanned % 50 == 0:
            logger.info(f"Scanned {scanned} reports...")
            with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
                json.dump(results, f, indent=2, ensure_ascii=False)

    n_prop = propagate(results)
    with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    logger.info(f"Cross-report propagation flagged {n_prop} syndicate-year(s) from another report's dated acceptance")

    n_occ = sum(1 for v in results.values() if v.get('ritc_occurred') is True)
    n_strong = sum(1 for v in results.values()
                   if v.get('ritc_occurred') is True and v.get('confidence') == 'strong')
    n_no = sum(1 for v in results.values() if v.get('ritc_occurred') is False)
    n_fail = sum(1 for v in results.values() if v.get('detection') == 'failed')
    logger.info(f"Scanned {scanned} new reports this run. Totals: "
                f"{n_occ} RITC occurred ({n_strong} strong), "
                f"{n_no} no RITC, {n_fail} detection failed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
