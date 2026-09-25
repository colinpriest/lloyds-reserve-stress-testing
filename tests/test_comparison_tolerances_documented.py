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

#: The two documents that state the policy in full.
DOCS = ("README.md", os.path.join("docs", "ocr-pipeline.md"))


def _all_docs():
    """Every current prose document, because a stale tolerance can sit anywhere: docs/data-audit-results.md carried
    the field-by-field table too, and neither the review nor a hand-listed pair of files saw it (R222)."""
    out = ["README.md"]
    for name in sorted(os.listdir(os.path.join(ROOT, "docs"))):
        if name.endswith(".md"):
            out.append(os.path.join("docs", name))
    return tuple(out)


ALL_DOCS = _all_docs()
#: The fields check_tolerance exempts by name prefix, which the documents list.
EXEMPT_PREFIXES = ("named_events", "prior_year_events", "raw_causal_phrases", "specific_events",
                   "specific_years_affected", "lob_movements", "primary_causes")
OLD_TABLE = (re.compile(r"Within \+/?-? ?1\.0pp"), re.compile(r"Within ±1\.0pp"),
             re.compile(r"Within \+/- 2\.0m or 5%"), re.compile(r"Within ±2\.0m or ±5%"),
             re.compile(r"field tolerances ±?2\.0m"), re.compile(r"±5% reserves"),
             re.compile(r"differ by > ?0\.5pp"))


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
    for path in ALL_DOCS:
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


# ---------------------------------------------------------- one definition, not several ------
#: Every module that compares two readings must take the tolerances from the module that applies
#: them. scripts/build_coverage_status.py did not: it carried "PYD +/-2.0m or +/-5%, opening reserves
#: +/-5%" as EXECUTED constants and attributed them to the README, so the coverage table's "LLM
#: cross-validated" provenance label was decided on a rule no stage of the pipeline applies. The
#: frozen review of 25 September 2026 named two prose sites and not this one, which is why the rule
#: below is about where a tolerance may be DEFINED rather than about a list of files (round 60).
TOL_NAME = re.compile(r"^([A-Z_]*(?:REL|ABS)_TOL)\s*=", re.M)
IMPORTED = re.compile(r"=\s*(COMPARISON_(ABS|REL)_TOL|MIX_PERCENTAGE_REL_TOL|"
                      r"RAG_(OPENING_REL|MODEL_DISAGREEMENT)_TOL)\s*$")


def _py_files():
    out = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames
                       if d not in ("__pycache__", ".git", ".pytest_cache", "venv", ".venv",
                                    "syndicate_reports", "pdf_extraction", "node_modules")]
        for fn in filenames:
            if fn.endswith(".py"):
                out.append(os.path.relpath(os.path.join(dirpath, fn), ROOT))
    return sorted(out)


def test_a_comparison_tolerance_is_defined_only_where_it_is_applied():
    """A tolerance constant is defined in test_gemini.py and nowhere else; every other module imports
    it. A literal copy is how the coverage table drifted away from the comparator."""
    offenders = []
    for rel in _py_files():
        if rel == "test_gemini.py" or rel.startswith("tests" + os.sep):
            continue
        src = io.open(os.path.join(ROOT, rel), encoding="utf-8", errors="replace").read()
        for m in TOL_NAME.finditer(src):
            end = src.find("\n", m.start())
            line = src[m.start():end if end != -1 else len(src)]
            if IMPORTED.search(line.rstrip()):
                continue        # an assignment from the imported constant is the repair
            offenders.append("%s: %s" % (rel, line.strip()))
    assert not offenders, ("a comparison tolerance is defined outside test_gemini.py:\n"
                          + "\n".join(offenders))


def test_the_coverage_script_takes_its_tolerances_from_the_comparator():
    rel = os.path.join("scripts", "build_coverage_status.py")
    src = io.open(os.path.join(ROOT, rel), encoding="utf-8").read()
    assert "from test_gemini import COMPARISON_ABS_TOL, COMPARISON_REL_TOL" in src, rel
    for name in ("PYD_ABS_TOL", "PYD_REL_TOL", "RESERVES_ABS_TOL", "RESERVES_REL_TOL"):
        assert re.search(r"^%s = COMPARISON_(ABS|REL)_TOL$" % name, src, re.M), name
    # and the opening-reserves call must pass an absolute tolerance, not None
    assert "values_agree(op_gem, op_gpt, RESERVES_ABS_TOL, RESERVES_REL_TOL)" in src
    assert "values_agree(pyd_gem, pyd_gpt, PYD_ABS_TOL, PYD_REL_TOL)" in src


def test_the_rag_opening_stage_has_its_own_named_thresholds():
    """The 2% and 5% of the RAG opening resolution are a DIFFERENT stage and are still in force. They
    are named so a document stating them can be checked against the code, and so that a sweep for the
    retired comparison-stage numbers cannot quietly rewrite them."""
    assert tg.RAG_OPENING_REL_TOL == 0.02
    assert tg.RAG_MODEL_DISAGREEMENT_TOL == 0.05
    src = io.open(os.path.join(ROOT, "test_gemini.py"), encoding="utf-8").read()
    body = src[src.index("def _resolve_rag_opening"):]
    body = body[:body.index("\n\n\n")]
    assert "tol=RAG_OPENING_REL_TOL" in body
    assert "RAG_MODEL_DISAGREEMENT_TOL" in body
    assert "tol=0.02" not in body and ", 0.05)" not in body


def test_the_guide_states_the_hard_failure_rule_and_not_the_retired_five_percent():
    """M03's own site: §10.6.2 called a reserve difference beyond 5% the hard-failure threshold."""
    flat = _flat(os.path.join("docs", "ocr-pipeline.md"))
    i = flat.index("Disagreement fallback resolution")
    section = flat[i:i + 2400]
    assert "`COMPARISON_REL_TOL`" in section and "`COMPARISON_ABS_TOL`" in section
    assert "0.5%" in section and "0.05" in section
    assert "beyond the 5% tolerance" not in section, \
        "the retired 5% hard-failure threshold is back in 10.6.2"
    assert re.search(r"excludes no record", section, re.I), \
        "the section must still say a hard failure excludes no record"
    assert "MIX_PERCENTAGE_REL_TOL" in section and "RAG_OPENING_REL_TOL" in section, \
        "the section must distinguish the other stages' own thresholds by name"
