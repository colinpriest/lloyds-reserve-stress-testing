"""The forms in which a filing says that its syndicate has stopped, or will stop, underwriting (round 62, fourth cycle, 1 October 2026).

`pdf_extraction/audit/runoff_corpus_register.json` holds one entry for every syndicate-year whose filing says that the syndicate
itself is in run-off or has stopped underwriting. It was first built from the filings that say "run-off" and "ceased underwriting".
Syndicate 1209's 2016 and 2017 filings say neither: they say that 2015 was the syndicate's last year of participation, that all new
and renewed business will be written in Syndicate 2003 and that "there is no active underwriter". The register missed them, and
the tests, which asked only that an entry's own words contain run-off words, could not see that they were missing.

Keyword and pattern scans can miss oblique wording, as both 1209 years show. The forms below are the defence: each is a sentence-
level pattern for one way a filing says that the syndicate has stopped (or will stop), and tests/test_runoff_corpus_register.py
holds the register to them in both directions:

  * every filing of the corpus that a form matches is a register entry, or its matching sentences are in the register's
    `scan_reviewed` list, each with the reason it is not the syndicate's own run-off (another entity, a class or line, an office
    or channel, not a stop);
  * every form is needed: some statement in the register is matched by that form and by no other.

A form states what is said, not who says it: a match is a statement to read, not a verdict. For the run-off forms the syndicate
itself has to be named as the subject (`SUBJ`), so that a line of business or a service company in run-off is not matched; the two
forms that name a stop (`ceased to ...`, `no longer ...`) are not hypothetical or negated and name no class, line, channel or place
as the thing stopped. What the forms cannot see is listed in tests/test_runoff_corpus_register.py (OBLIQUE).

To add a form: write it with `_form(...)` below, add a sentence it matches (and one it must leave alone) to FORM_CASES and a record
that needs it to WITNESSES in the test file, make sure every sentence it can match holds a TRIGGER word, run this script, read each
sentence it lists and either add an entry or add the filing to `scan_reviewed` with its reason.

Usage:  python scripts/runoff_statement_forms.py     prints the corpus's matching sentences that the register does not account for
"""
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTER = ROOT / "pdf_extraction" / "audit" / "runoff_corpus_register.json"

#: hyphen variants, the soft hyphen and ligatures as a filing's text layer prints them, written plainly
_PRINTED = {0x2010: "-", 0x2011: "-", 0x2012: "-", 0x2013: "-", 0x2014: "-", 0x2212: "-", 0x00AD: None,
            0xFB00: "ff", 0xFB01: "fi", 0xFB02: "fl", 0xFB03: "ffi", 0xFB04: "ffl"}
#: a sentence ends at . ; : ! ? and the next one starts with a capital, a bullet, a bracket or a quotation mark
_SPLIT = re.compile(r"(?<=[.;:!?])\s+(?=[A-Z" + chr(0x2022) + r"(\"'])")

RO = r"run(?:-|\s)?\s?off"
#: the syndicate itself named: "the Syndicate", "Syndicate 3334", "SPA 6123"
SUBJ = r"(?:\b(?:the|this|our)\s+syndicate\b|\bsyndicate\s+\d{2,4}\b|\bSPA\s+\d{3,4}\b|\bthe\s+SPA\b)"
GAP = r"[^.;:]{0,160}?"
PLACE = r"(?:placed|place|put|placing|putting|entered|enter|entering|enters|went|go|going|goes|moved|moving|move)"
STOP_VERB = r"(?:ceased|ceasing|will\s+cease|(?:decided|decision|resolved|agreed)\s+to\s+cease|to\s+cease|cease[sd]?)"
STOP_WHAT = r"(?:underwrit(?:e|ing)|writ(?:e|ing)|trad(?:e|ing)|accept(?:ing)?|transact(?:ing)?)"
#: what may stand between the verb and the end of the statement for it to be about the whole book: never a class, a line, a channel or a place
OBJ = (r"(?:\s+(?:new|any|all|further|future|insurance|or\s+renewal|and\s+renewal|new\s+or\s+renewal)){0,3}"
       r"(?:\s+(?:business|risks?|insurance\s+business))?"
       r"(?:\s+(?:the\s+)?(?:whole\s+account\s+)?quota\s+share(?:\s+re-?insurance)?(?:\s+of\s+(?:\w+\s+)?syndicate\s+\d+)?)?"
       r"(?:\s+re-?insurance(?:\s+of\s+(?:\w+\s+)?syndicate\s+\d+))?"
       r"(?:\s+(?:through\s+)?(?:the|this)\s+syndicate|\s+through\s+syndicate\s+\d+)?")
BOUND = (r"(?=\s*(?:$|[,.;:)]|\s(?:with|on|at|from|in|after|since|by|as|following|during|when|effective|before|until|"
         r"through\s+syndicate|and|which|because|due|having|so|to\s+the)\b|\sfor\s+the\s+20\d\d))")
#: hypothetical, negated or conditional wording earlier in the same clause: "do not intend to cease underwriting", "unless ..."
HEDGE = re.compile(r"\b(?:intend|intends|intended|intention|unless|whether|could|may|might|should|if|possible|no\s+realistic\s+alternative|"
                   r"not\s+(?:been\s+)?(?:able|going)|do\s+not|does\s+not|did\s+not|have\s+not|has\s+not)\b", re.I)

FORMS = {}
HEDGED = set()


def _form(name, pattern, hedged=False):
    FORMS[name] = re.compile(pattern, re.I)
    if hedged:
        HEDGED.add(name)


#: "Syndicate 3500 is in runoff"; "the Syndicate is now in run-off"
_form("in_run_off", SUBJ + GAP + r"\b(?:is|was|are|were|has\s+been|had\s+been|being|now|remains?|remained|continues\s+to\s+be)\s+(?:now\s+|also\s+|currently\s+|already\s+)?in\s+(?:a\s+|an\s+)?(?:\w+\s+)?" + RO)
#: "the Syndicate was placed into run-off"; "decision to place the Syndicate into run-off"; "the Syndicate would enter voluntary run off"
_form("put_into_run_off", (SUBJ + GAP + r"\b" + PLACE + r"\s+(?:\w+\s+){0,4}?(?:in|into|in\s+to)\s+(?:a\s+|an\s+)?(?:\w+\s+)?" + RO + "|"
                           + r"\b" + PLACE + r"\s+[^.;:]{0,80}?" + SUBJ + r"[^.;:]{0,60}?\s(?:in|into|in\s+to)\s+(?:a\s+|an\s+)?(?:\w+\s+)?" + RO + "|"
                           + SUBJ + GAP + r"\benter(?:s|ed|ing)?\s+(?:a\s+|an\s+)?(?:\w+\s+)?" + RO))
#: "the principal activity of Syndicate 3500 is the run-off of its existing liabilities"; "specialises in run-off"; "managed as a run-off syndicate"; "a run-off closure plan"
_form("run_off_of_its_business", (SUBJ + GAP + r"\b(?:is|was)\s+(?:the\s+)?" + RO + r"\s+of\b|"
                                  + SUBJ + GAP + r"\bspecialis(?:es|ed|ing)\s+in\s+" + RO + "|"
                                  + SUBJ + GAP + r"\b(?:as|is|be|being)\s+(?:a\s+|an\s+)" + RO + r"\s+syndicate\b|"
                                  + SUBJ + GAP + r"\b(?:continues?\s+to|will|to)\s+" + RO + r"\s+(?:its|the|all|their)\b|"
                                  + RO + r"\s+closure\s+plan\b"))
#: "ceased underwriting new business with effect from the end of 2013"; "ceased to trade on 31 December 2016"; "decision to cease underwriting through Syndicate 3334"
_form("ceased_to_write", STOP_VERB + r"\s+(?:to\s+)?(?:actively\s+)?" + STOP_WHAT + OBJ + BOUND, hedged=True)
#: "the Syndicate is no longer underwriting new business"
_form("no_longer_writing", r"\bno\s+longer\s+(?:actively\s+)?(?:underwrit(?:e|ing)|writ(?:e|ing)|accept(?:ing)?|transact(?:ing)?)" + OBJ + BOUND, hedged=True)
#: "2015 year of account is the Syndicate's last year of participation"; "2019 was the final year in which SPA 6123 wrote new business"
_form("last_year_of_participation", r"(?:last|final)\s+(?:underwriting\s+)?(?:year\s+of\s+account\s+|year\s+of\s+underwriting\s+|year\s+)?(?:of\s+)?participation|(?:last|final)\s+year\s+in\s+which\s+(?:the\s+syndicate|syndicate\s+\d+|SPA\s+\d+)")
#: "In 2016, there is no active underwriter."; "is not a live underwriter of new policies"
_form("no_active_underwriter", r"no\s+active\s+underwriter|not\s+a\s+live\s+underwriter")
#: "All new and renewed business of the Syndicate will be written in Syndicate 2003"
_form("business_written_in_another_syndicate", r"(?:all|any)\s+(?:new|future|renewal)\b[^.]{0,60}\bbusiness\b[^.]{0,80}\b(?:will|would|is|are|has been|have been|shall)\s+(?:now\s+)?(?:be\s+)?(?:written|underwritten|placed|transacted|renewed|accepted)\b[^.]{0,40}\b(?:in|through|on|via|into)\s+(?:Lloyd.?s\s+)?Syndicate\s+\d+")
#: "The syndicate did not underwrite in 2017."; "The Syndicate will not be participating in the 2016 year of account."; "will not be writing new business for the 2022 year of account"
_form("no_business_in_a_year", (r"\bdid\s+not\s+(?:underwrite|write|participate|accept)\s+(?:any\s+|new\s+)?(?:business\s+|risks?\s+)?(?:in|on|for|during)\s+(?:the\s+)?(?:20\d\d|calendar\s+year|year)|"
                                r"\bdid\s+not\s+(?:underwrite|write)\s+any\s+(?:business|risks?|policies)\b|"
                                r"\b(?:will\s+)?not\s+(?:be\s+)?(?:participating|writing|underwriting)\s+(?:in|new\s+business\s+for)\s+(?:the\s+)?20\d\d|"
                                + SUBJ + GAP + r"\b(?:written|writing|wrote|underwritten|accepted)\s+no\s+(?:new\s+)?business"))

#: a sentence is tried against the forms only if it holds one of these words (the scan reads every page of 1,065 filings). Each
#: form's own opening words are here, so that a sentence a form can match is never skipped: run-off (the three run-off forms),
#: ceas and no longer (the two stopped forms), participat, final year and last year (last_year_of_participation),
#: active/live underwriter, all/any new (business_written_in_another_syndicate) and did not, will not, not writing, written no
#: and its kin (no_business_in_a_year). The tests hold every statement the register has, and every FORM_CASES sentence, to it.
TRIGGER = re.compile(r"run(?:-|\s)?\s?off|ceas|no\s+longer|participat|active\s+underwriter|live\s+underwriter|did\s+not|will\s+not|"
                     r"not\s+(?:be\s+)?(?:writing|underwriting)|final\s+year|last\s+year|(?:all|any)\s+(?:new|future|renewal)|"
                     r"written\s+no|wrote\s+no|writing\s+no|underwritten\s+no|accepted\s+no", re.I)


def normalise(text):
    """The text with the characters a filing's text layer prints in place of plain ones written plainly."""
    return text.translate(_PRINTED)


def flat(text):
    """Normalised, with white space collapsed: the text the forms are matched against."""
    return " ".join(normalise(text).split())


def sentences(flat_text):
    return _SPLIT.split(flat_text)


def match(form, sentence):
    """The form's match in the sentence, or None. A hedged form is not hypothetical, negated or conditional in its own clause."""
    m = FORMS[form].search(sentence)
    if m and form in HEDGED:
        clause_start = max(sentence.rfind(c, 0, m.start()) for c in (",", ";", ":", "."))
        if HEDGE.search(sentence[clause_start + 1:m.start()]):
            return None
    return m


def forms_matching(text):
    """The names of the forms that match some sentence of the text, in the order of FORMS."""
    sents = sentences(flat(text))
    return [name for name in FORMS if any(match(name, s) for s in sents)]


def says_stopped(text):
    return bool(forms_matching(text))


def scan_page(text):
    """[(form, sentence, span)] for every sentence of the page that a form matches."""
    f = flat(text)
    if not TRIGGER.search(f):
        return []
    out = []
    for s in sentences(f):
        if not TRIGGER.search(s):
            continue
        for name in FORMS:
            m = match(name, s)
            if m:
                out.append((name, s, m.group(0)))
    return out


def scan_filing(texts):
    """[{"page", "form", "sentence", "span"}] for the filing's page texts (page 1 is texts[0])."""
    return [{"page": p, "form": f_, "sentence": s, "span": sp} for p, t in enumerate(texts, 1) for f_, s, sp in scan_page(t)]


def covered(hit, statements):
    """Whether a reviewed statement (a dict with page and quote) on the hit's page holds the hit's matching words."""
    return any(st["page"] == hit["page"] and hit["span"] in flat(st["quote"]) for st in statements)


def corpus_sources():
    """[(stem, source path)] for every committed extraction record: the corpus."""
    out = []
    for path in sorted((ROOT / "pdf_extraction").glob("syndicate_*_[0-9][0-9][0-9][0-9].json")):
        rec = json.loads(path.read_text(encoding="utf-8"))
        out.append((path.stem, ROOT / str(rec["source_file"]).replace("\\", "/")))
    return out


#: The filings of the corpus that yield no text, with why. The forms read nothing in them, so the register's completeness does
#: not reach them; tests/test_runoff_corpus_register.py holds this list to the corpus in both directions (review of 2 October
#: 2026, E-6: the README said every filing was scanned, and a filing with no page passed the scan unread).
UNREADABLE = {
    "syndicate_3210_2018": ("the local file is damaged: it opens with no page. Syndicate 3210 has been in run-off since "
                            "31 December 2016 (its 2017 entry is WHOLE) and the record carries no development figure. "
                            "A fresh download of the filing is the repair. It is not a row of the workbook, so "
                            "scripts/download_from_xlsx.py cannot fetch it. Fetch it by hand from Lloyd's, or with "
                            "scripts/lloyds_scraper.py --syndicates 3210 --years 2018 --output <a new folder>, and copy "
                            "<folder>/pdfs/syndicate_3210_2018.pdf over the damaged file (the scraper skips a file that "
                            "exists, and rewrites its output folder's metadata/reports.json, so it is not pointed at "
                            "syndicate_reports/)."),
}


def without_text(texts_by_stem):
    """The stems whose page texts hold no text at all: a damaged file opens with no page, or with pages that hold none."""
    return sorted(stem for stem, texts in texts_by_stem.items() if not any(t.strip() for t in texts))


def read_corpus(sources, page_texts):
    """{"hits": {stem: [hit, ...]}, "textless": [stem, ...]} for [(stem, source path)], each filing read once with
    `page_texts` (the audit's reader, finalize_structural_eligibility_audit.page_texts)."""
    hits, textless = {}, []
    for stem, source in sources:
        texts = page_texts(source)
        textless += without_text({stem: texts})
        found = scan_filing(texts)
        if found:
            hits[stem] = found
    return {"hits": hits, "textless": sorted(textless)}


def unaccounted(register, hits_by_stem):
    """The hits not accounted for: those of a filing that is neither an entry nor reviewed apart, and that no scan_reviewed statement covers."""
    entries = {r["stem"] for r in register["records"]} | {r["stem"] for r in register["reviewed_not_run_off"]}
    reviewed = {r["stem"]: r["statements"] for r in register.get("scan_reviewed", [])}
    return [dict(h, stem=stem) for stem, hits in hits_by_stem.items() if stem not in entries
            for h in hits if not covered(h, reviewed.get(stem, []))]


def main():
    os.environ.setdefault("LLOYDS_EXTRACTION_OFFLINE", "1")
    sys.path.insert(0, str(ROOT / "scripts"))
    import finalize_structural_eligibility_audit as fin
    register = json.loads(REGISTER.read_text(encoding="utf-8"))
    sources = corpus_sources()
    read = read_corpus(sources, fin.page_texts)
    hits, textless = read["hits"], read["textless"]
    todo = unaccounted(register, hits)
    by = defaultdict(list)
    for h in todo:
        by[h["stem"]].append(h)
    print("filings scanned: %d; with a matching sentence: %d; not accounted for: %d filings, %d sentences"
          % (len(sources), len(hits), len(by), len(todo)))
    print("filings with no text: %s (declared unreadable: %s)" % (textless or "none", sorted(UNREADABLE) or "none"))
    for stem, lst in by.items():
        print(stem)
        for h in lst:
            print("   p%d [%s] %s" % (h["page"], h["form"], h["sentence"][:300]))


if __name__ == "__main__":
    main()
