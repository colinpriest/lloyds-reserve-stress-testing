"""The canonical PYD hierarchy and the code decide alike (frozen review of 21 September 2026, D03).

docs/ocr-pipeline.md section 10.3 said a deterministic figure "never displaces two agreeing model
values", while _rag_veto applies a figure two readings of the filing confirmed over that veto (R213).
These tests walk a confirmed override and an ordinary veto through the code, and check that the
documentation's precedence table states both decisions.
"""
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import test_gemini as tg  # noqa: E402


def _doc():
    return io.open(os.path.join(ROOT, "docs", "ocr-pipeline.md"), encoding="utf-8").read()


def test_a_confirmed_figure_is_applied_over_two_agreeing_models():
    ok, note = tg._rag_veto(+5.0, [-3.0, -2.5], 100.0, confirmed=5.0)
    assert ok is True and "APPLIED OVER THE SIGN VETO" in note


def test_an_unconfirmed_figure_is_vetoed_by_two_agreeing_models():
    ok, note = tg._rag_veto(+5.0, [-3.0, -2.5], 100.0, confirmed=None)
    assert ok is False and "NOT APPLIED" in note


def test_a_confirmation_of_another_figure_does_not_lift_the_veto():
    ok, _note = tg._rag_veto(+5.0, [-3.0, -2.5], 100.0, confirmed=4.0)
    assert ok is False


def test_the_documented_precedence_states_both_decisions():
    doc = _doc()
    section = doc[doc.index("### 10.3"):doc.index("### 10.4") if "### 10.4" in doc else None]
    assert "triangle_figures_confirmed_by_hand.json" in section
    assert "`_rag_veto`" in section and "`_pyd_override_gate`" in section
    table = [l for l in section.splitlines() if l.startswith("| ")]
    order = [l.split("|")[2].strip().split(":")[0] for l in table[1:] if l.split("|")[1].strip().isdigit()]
    assert order.index("Hand confirmation") < order.index("Model agreement"), order


def test_no_unqualified_never_remains_in_the_hierarchy():
    flat = " ".join(_doc().split())
    for m in re.finditer(r"never displaces two agreeing model values[^.]*\.", flat):
        assert "exception" in m.group(0) or "confirmed" in m.group(0), m.group(0)
    flat_readme = " ".join(io.open(os.path.join(ROOT, "README.md"), encoding="utf-8").read().split())
    assert "triangle_figures_confirmed_by_hand.json" in flat_readme


#: a README statement that the provisions movement overrides, or is authoritative over, a triangle
SIGN_OVERRIDE = re.compile(r"provisions[^.;]{0,100}?\b(overrides?|is authoritative|wins)\b|"
                           r"sign disagreement the provisions movement overrides", re.I)


def test_every_readme_statement_of_the_sign_override_states_its_conditions():
    """Verification review of round 62, N-V-E-5: round 62 gave the sign-override bullet the R138
    conditions -- an affirmed movement note, a column bound to the report year, a non-zero figure --
    but the troubleshooting entry (and the summary bullet on triangle authority) still said a
    provisions movement of the other sign overrides the triangle, full stop, so a reader would expect
    an unbound provisions figure to override. Every README line that states the override carries the
    conditions (R138, or the affirmed movement row bound to the report year)."""
    readme = io.open(os.path.join(ROOT, "README.md"), encoding="utf-8").read()
    stating = [line for line in readme.splitlines() if SIGN_OVERRIDE.search(" ".join(line.split()))]
    assert len(stating) >= 3, stating      # the summary, the hierarchy bullet, troubleshooting
    for line in stating:
        flat = " ".join(line.split())
        assert "R138" in flat and re.search(r"affirmed movement (note|row)", flat), flat[:200]


#: a statement in docs/ocr-pipeline.md that the provisions movement overrides, or is preferred to, a triangle
DOC_SIGN_OVERRIDE = re.compile(
    r"provisions[^.;]{0,160}?\b(overrides?|is authoritative|takes precedence|is preferred)\b"
    r"|\bprefer(red)?\b[^.;]{0,40}\bprovisions\b", re.I)


def _doc_statements():
    """The units of docs/ocr-pipeline.md that state a rule: each paragraph, or each item of a list, outside the
    fenced blocks, and the flow diagram's Step 4b box. A fenced log line shows output and states no rule."""
    doc = _doc()
    box = re.search(r"\| Step 4b:.*?\n\+-+\+", doc, re.S)
    units = [" ".join(box.group(0).replace("|", " ").split())] if box else []
    prose = re.sub(r"```.*?```", "\n\n", doc, flags=re.S)
    for para in re.split(r"\n\s*\n", prose):
        for item in re.split(r"\n(?=\s*(?:[*-]|\d+\.)\s)", para):
            units.append(" ".join(item.split()))
    return units


def test_every_doc_statement_of_the_sign_override_states_its_conditions():
    """Review of 2 October 2026, E-5 (R11-12): section 10.3, the canonical hierarchy, said a provisions movement
    of the other sign "is authoritative and overrides the triangle", and so did section 10.4's list, the RITC
    caveat, section 11.3.1's rule and trigger list, the change history and the flow diagram; only the
    precedence table's row 1a gave R138's conditions, which the code has applied since 13 September 2026 (an
    affirmed movement note whose column is bound to the report year). Every statement of the override in the
    canonical document carries them, as every README line already must."""
    units = _doc_statements()
    assert any(u.startswith("Step 4b:") for u in units), "the flow diagram's Step 4b box was not found"
    stating = [u for u in units if DOC_SIGN_OVERRIDE.search(u)]
    # the diagram, 10.3 item 3, 10.4's list, the RITC caveat, 11.3.1's rule and the change history
    assert len(stating) >= 6, stating
    for u in stating:
        assert "R138" in u and re.search(r"affirmed movement note", u) and "report year" in u, u[:240]
    # and section 11.3.1's list of when the cross-check runs names them
    triggers = re.search(r"\*\*Trigger conditions\*\*.*?(?=\n\n\*\*)", _doc(), re.S).group(0)
    assert "R138" in triggers and "affirmed movement note" in " ".join(triggers.split()), triggers


def test_resolved_table_value_does_not_override_two_agreeing_model_values():
    value, label, note = tg._resolve_rag_opening(
        200.0,
        {"unit_source": "header", "raw_value": 200.0, "page": 1},
        [100.0, 100.0],
    )
    assert value is None and label == "header"
    assert "NOT APPLIED" in note and "model value is retained" in note


def test_reserve_overview_exposes_the_conditional_and_no_override_branches():
    doc = _doc()
    flow = doc[doc.index("Step 5: Dual-LLM"):doc.index("Step 6: Report classification")]
    assert "apply only under the" in flow
    assert "otherwise retain model values" in flow
    summary = doc[doc.index("**Priority chain**"):doc.index("**Why pl_account")]
    assert "only when the agreement, resolved-unit, or tie-break rule" in summary
    assert "no-override branch" in summary
    assert "both models, always" not in doc
    assert "applied proactively to both LLMs" not in doc
