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
