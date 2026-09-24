r"""Every current description of the model-agreement veto carries its exception (frozen review of 24 September 2026,
M03).

R213 added one: a deterministic figure that equals, to half a thousand, a figure two readings of the filing
confirmed in pdf_extraction/audit/triangle_figures_confirmed_by_hand.json is applied OVER the veto, for that record
and that figure only. The precedence table in section 10.3 said so; the README said it twice without the exception,
and the OCR guide three more times, one of them counting the qualifications ("twice over") and so contradicting its
own table.

The R221 test that guarded this looked for one sentence ("never displaces two agreeing model values"), which is a
blacklist of the phrasing a reviewer had already objected to. This sweeps instead: any block of either document
that DESCRIBES the veto must also carry its exception, and a block is a paragraph, a bullet or a whole table. A
block the document itself marks as a record of an earlier round is exempt, and says so in its own words.

Run:  python -m pytest tests/test_veto_exception_documented.py -q
"""
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import test_gemini as tg  # noqa: E402

DOCS = ("README.md", os.path.join("docs", "ocr-pipeline.md"))

#: A block describes the veto if it names the gate, names the veto, or states both of its two conditions.
DESCRIBES = (re.compile(r"_pyd_override_gate"),
             re.compile(r"model-agreement veto"),
             re.compile(r"opposite sign.{0,300}?50%", re.S),
             re.compile(r"agree (?:with each other )?on the opposite sign", re.S))

#: It carries the exception if it names the register, the confirmation, the function that applies it, or the row of
#: the precedence table that states it. A bare pointer to section 10.3 is not enough: the provisions hierarchy cites
#: that section too, so it would exempt a block that never mentions the exception at all.
EXEMPTS = (re.compile(r"triangle_figures_confirmed_by_hand\.json"),
           re.compile(r"two readings of the filing confirmed"),
           re.compile(r"[Hh]and confirmation"),
           re.compile(r"_rag_veto"),
           re.compile(r"row 2 of the precedence table"))

#: A block the document itself marks as the record of an earlier round is a quotation, not a current description.
HISTORICAL = re.compile(r"\b(superseded|withdrawn|before round \d+|round \d+ record|historic(al)?)\b", re.I)


def _blocks(path):
    with io.open(os.path.join(ROOT, path), encoding="utf-8") as fh:
        text = fh.read()
    for block in re.split(r"\n\s*\n", text):
        if block.strip():
            yield block


def test_every_block_that_describes_the_veto_carries_its_exception():
    missing = []
    checked = 0
    for path in DOCS:
        for block in _blocks(path):
            flat = " ".join(block.split())
            if not any(p.search(flat) for p in DESCRIBES):
                continue
            checked += 1
            if HISTORICAL.search(flat):
                continue
            if not any(p.search(flat) for p in EXEMPTS):
                missing.append("%s: %s" % (path, flat[:160]))
    assert checked >= 5, "only %d blocks describe the veto; the sweep is looking in the wrong place" % checked
    assert not missing, "the veto is described without its exception in:\n  " + "\n  ".join(missing)


def test_no_document_counts_the_qualifications_without_counting_that_one():
    """A count of the qualifications is a claim about how many there are."""
    for path in DOCS:
        for block in _blocks(path):
            flat = " ".join(block.split())
            m = re.search(r"qualified (\w+) (?:times )?over", flat)
            if m:
                assert any(p.search(flat) for p in EXEMPTS), "%s counts the qualifications as %r without the " \
                                                             "hand confirmation: %s" % (path, m.group(1), flat[:160])


def test_the_code_still_lifts_the_veto_only_for_a_confirmed_figure():
    """The documents are being checked against behaviour, so the behaviour is asserted here too."""
    assert tg._rag_veto(+5.0, [-3.0, -2.5], 100.0, confirmed=5.0)[0] is True
    assert tg._rag_veto(+5.0, [-3.0, -2.5], 100.0, confirmed=None)[0] is False
    assert tg._rag_veto(+5.0, [-3.0, -2.5], 100.0, confirmed=4.0)[0] is False


def test_the_register_holds_only_entries_with_their_evidence():
    """Three records, each with two readings, pages, a quote and a figure: what the documents say it holds."""
    import json
    path = os.path.join(ROOT, "pdf_extraction", "audit", "triangle_figures_confirmed_by_hand.json")
    with io.open(path, encoding="utf-8") as fh:
        reg = json.load(fh)
    records = reg["records"] if isinstance(reg, dict) and "records" in reg else reg
    entries = [v for k, v in records.items() if not k.startswith("_")] if isinstance(records, dict) else records
    assert len(entries) == 3
    for e in entries:
        assert len(e.get("readings", [])) >= 2 and e.get("pages") and e.get("quote")
        assert isinstance(e.get("figure_m"), (int, float))
