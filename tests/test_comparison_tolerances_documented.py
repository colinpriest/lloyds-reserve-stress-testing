r"""The documented model-agreement tolerances are the ones the comparator applies (frozen review of 24 September
2026, D05).

Three public descriptions disagreed with the code and with each other: the analysis appendix said a material
disagreement was a PYD percentage differing by more than 0.5 percentage points, while the README and the OCR guide
gave a field-by-field table (+-1.0pp for the percentage, +-2.0m or 5% for the amount, +-5% for opening reserves).
check_tolerance flags a numeric field when the two values differ by more than 0.5% of the larger AND by more than
0.05 absolute, whatever the field, with text, list, page and confidence fields exempt and a gross-premium-mix
percentage re-tested on absolute values within 5%. Each of the three rules the tables gave is contradicted by an
example the code decides the other way.

These tests read the documents' own numbers and field lists against the constants, and walk the review's three
examples through the executed comparator.

Run:  python -m pytest tests/test_comparison_tolerances_documented.py -q
"""
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import test_gemini as tg  # noqa: E402

DOCS = ("README.md", os.path.join("docs", "ocr-pipeline.md"))
#: The fields check_tolerance exempts by name prefix, which the documents list.
EXEMPT_PREFIXES = ("named_events", "prior_year_events", "raw_causal_phrases", "specific_events",
                   "specific_years_affected", "lob_movements", "primary_causes")
OLD_TABLE = (re.compile(r"Within \+/?-? ?1\.0pp"), re.compile(r"Within ±1\.0pp"),
             re.compile(r"Within \+/- 2\.0m or 5%"), re.compile(r"Within ±2\.0m or ±5%"))


def _flat(path):
    with io.open(os.path.join(ROOT, path), encoding="utf-8") as fh:
        return " ".join(fh.read().split())


def test_the_documents_print_the_constants_the_code_uses():
    rel = "%g%%" % (100 * tg.COMPARISON_REL_TOL)          # 0.5%
    mix = "%g%%" % (100 * tg.MIX_PERCENTAGE_REL_TOL)      # 5%
    abs_tol = "%g" % tg.COMPARISON_ABS_TOL                # 0.05
    for path in DOCS:
        flat = _flat(path)
        assert ("more than **%s of the larger**" % rel) in flat, path
        assert ("more than **%s** in absolute terms" % abs_tol) in flat, path
        assert ("within **%s** (`MIX_PERCENTAGE_REL_TOL`)" % mix) in flat, path
        assert "`_is_numeric_near`" in flat and "`COMPARISON_REL_TOL`" in flat, path


def test_the_documents_list_every_exempt_field_the_code_exempts():
    for path in DOCS:
        flat = _flat(path)
        for field in EXEMPT_PREFIXES:
            assert ("`%s`" % field) in flat, "%s does not list `%s`" % (path, field)
        assert "`page` or `confidence`" in flat, path


def test_no_document_keeps_the_field_by_field_table_the_code_never_applied():
    for path in DOCS:
        flat = _flat(path)
        for pattern in OLD_TABLE:
            assert not pattern.search(flat), "%s still prints %s" % (path, pattern.pattern)


def test_the_documents_say_a_flag_is_not_a_dropped_record():
    for path in DOCS:
        flat = _flat(path)
        assert "comparison-stage flag, not a rejected record" in flat, path
        assert "`resolve_computed_fields`" in flat and "disagreement log" in flat, path


def _flag(field, a, b):
    """Whether check_tolerance calls this pair a hard failure, through the executed comparator."""
    d = [{"field": field, "type": "value_difference", "gemini": a, "gpt": b}]
    _passed, _tolerated, hard = tg.check_tolerance(d, "gemini", "gpt")
    return bool(hard)


def test_the_three_examples_the_public_tables_decided_the_other_way():
    """Each contradicts at least one of the rules the old tables gave."""
    assert _flag("prior_year_development_pct", 10.0, 10.2)        # the table tolerated +-1.0pp
    assert _flag("prior_year_development_gbp_m", 100.0, 101.0)    # the table tolerated +-2.0m or 5%
    assert _flag("opening_reserves_gbp_m", 100.0, 103.0)          # the table tolerated +-5%


def test_a_pair_inside_both_tolerances_is_not_flagged():
    assert not _flag("opening_reserves_gbp_m", 100.0, 100.4)      # 0.4% of the larger: under the relative tolerance
    assert not _flag("prior_year_development_gbp_m", 0.0, 0.04)   # 0.04 absolute: under the absolute tolerance
    assert not _flag("prior_year_development_gbp_m", None, 0.0)   # a missing value and zero are one value


def test_a_mix_percentage_is_re_tested_on_absolute_values():
    assert not _flag("gross_premium_mix[0].percentage_of_total", 88.0, -87.43)
    assert _flag("gross_premium_mix[0].percentage_of_total", 88.0, -70.0)
