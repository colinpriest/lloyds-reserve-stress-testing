r"""The documented first-year rule is the executed one (frozen review of 25 September 2026, D02).

The mechanism was repaired in round 58 and is tested in tests/test_first_year_after_models.py. The
summaries were not, and three of them still described the rule that round 58 deleted:

  * README.md: "Syndicates in their first or second year ... have fewer than 3 underwriting years in
    their triangle. These are automatically detected and skipped", with LLM extraction "skipped
    entirely" -- the raw column count, and no mention of the decision taken after the models;
  * docs/ocr-pipeline.md's step-6 flowchart: "first_year_syndicate: triangle has <3 UW years";
  * docs/ocr-pipeline.md's dashboard table: a record with no `models` key was "never sent to LLMs",
    which 1884/2016 falsifies -- it has no `models` block and both models' figures in
    `first_year_evidence`;
  * docs/ocr-pipeline.md's no-triangle section: `no_triangle_data` "only used for reports outside the
    first two underwriting years", an inception-based distinction that went with the lookup.

So these tests hold every current document to the executed conditions, and walk the review's closure
examples through the executed function.

Run:  python -m pytest tests/test_first_year_documented.py -q
"""
import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pytest  # noqa: E402

import test_gemini as tg  # noqa: E402
from table_extraction import PYD_EXCLUDED_RECENT_UW_YEARS  # noqa: E402


def _all_docs():
    """Every current prose document. A stale summary can sit anywhere, and the point of D02 is that
    the corrected subsection did not stop three other places from contradicting it."""
    out = ["README.md"]
    docs = os.path.join(ROOT, "docs")
    for name in sorted(os.listdir(docs)):
        if name.endswith(".md"):
            out.append(os.path.join("docs", name))
    return tuple(out)


ALL_DOCS = _all_docs()
#: the summaries the review found, as patterns
RETIRED = (
    re.compile(r"(are )?automatically detected and skipped", re.I),
    re.compile(r"only used for reports outside the first two underwriting years", re.I),
    re.compile(r"reports in the first two years are classified as `?first_year_syndicate`?", re.I),
    re.compile(r"skips LLM extraction entirely", re.I),
)
#: The raw count of underwriting years may be mentioned only where the usable-cohort condition is
#: mentioned with it. Both spellings, because the README wrote it out and the flowchart abbreviated it,
#: and a pattern that stops at a full stop misses "... in their triangle. These are automatically
#: detected and skipped", which is how the claim was phrased.
RAW_COUNT = re.compile(r"<\s*3 UW years|(fewer|less) than (3|three) underwriting years", re.I)
#: "never sent to LLMs" is TRUE of a no_triangle_data record and FALSE of a first-year stub, so what
#: makes it a defect is applying it to a first-year classification.
NO_API = re.compile(r"never sent to LLMs", re.I)


def _flat(path):
    with io.open(os.path.join(ROOT, path), encoding="utf-8") as fh:
        return " ".join(fh.read().split())


@pytest.mark.parametrize("path", ALL_DOCS)
def test_no_document_keeps_a_retired_first_year_summary(path):
    flat = _flat(path)
    for pattern in RETIRED:
        # every match, not the first: a document can restate the same claim twice
        for m in pattern.finditer(flat):
            window = flat[max(0, m.start() - 340):m.end() + 240]
            # Two exemptions. A sentence that reports the wording as retired is the repair, not a
            # violation. And "never sent to LLMs" is TRUE of a no_triangle_data record: that branch
            # returns before the slim PDF is built, which
            # test_no_triangle_data_really_does_precede_the_models pins. It is false only of a
            # first-year stub, which may be written after both models have read the reserve text.
            assert re.search(r"used to|no longer|went with|this paragraph|superseded|does not mean|"
                             r"cannot be used to infer|retired|D02|no.triangle.data", window, re.I), \
                "%s still states %r: %s" % (path, pattern.pattern, window[:240])


@pytest.mark.parametrize("path", ALL_DOCS)
def test_the_raw_column_count_is_never_stated_as_the_rule_on_its_own(path):
    flat = _flat(path)
    for m in RAW_COUNT.finditer(flat):
        window = flat[max(0, m.start() - 260):m.end() + 260]
        assert re.search(r"usable", window, re.I), \
            "%s states the raw UW-year count without the usable-cohort condition: %s" \
            % (path, window[:220])


@pytest.mark.parametrize("path", ALL_DOCS)
def test_no_document_reads_a_first_year_classification_as_proof_of_no_api_call(path):
    """The dashboard claim, precisely: "never sent to LLMs" is true of a no_triangle_data record and
    false of a first-year stub, so the defect is the two being described together. A window exemption
    for no_triangle_data is not enough here -- the status row lists BOTH conditions."""
    flat = _flat(path)
    for m in NO_API.finditer(flat):
        window = flat[max(0, m.start() - 400):m.end() + 400]
        assert not re.search(r"first.year", window, re.I), \
            ("%s says a report was never sent to LLMs within sight of a first-year classification, "
             "which 1884/2016 falsifies: %s" % (path, window[:260]))


def test_the_two_full_descriptions_state_the_usable_cohort_rule():
    """The rule is about a cohort up to t-2, not about how many columns the triangle has."""
    for path in ("README.md", os.path.join("docs", "ocr-pipeline.md")):
        flat = _flat(path)
        assert re.search(r"uw_year\s*<=\s*report_year\s*-\s*%d|cohort up to `?t-%d`?|"
                         r"up to t-%d" % (PYD_EXCLUDED_RECENT_UW_YEARS,
                                          PYD_EXCLUDED_RECENT_UW_YEARS,
                                          PYD_EXCLUDED_RECENT_UW_YEARS), flat, re.I), path
        assert re.search(r"usable (mature )?cohorts?", flat, re.I), path


def test_both_full_descriptions_distinguish_the_two_decision_points():
    for path in ("README.md", os.path.join("docs", "ocr-pipeline.md")):
        flat = _flat(path)
        assert re.search(r"before the models", flat, re.I), path
        assert re.search(r"after (both )?(the )?models", flat, re.I), path
        assert "first_year_evidence" in flat, path


def test_the_readme_says_a_missing_models_key_does_not_mean_no_api_call():
    flat = _flat("README.md")
    assert re.search(r"no `models` key does not mean the models were never called", flat, re.I)
    assert "syndicate_1884_2016.json" in flat


def test_no_triangle_data_really_does_precede_the_models():
    """The exemption above is only sound if that branch returns before the models are called.

    It does: process_one_report returns ("no_triangle_data", ...) before the slim PDF is built, so for
    those records "never sent to LLMs" is a true statement and the first-year stub is the case the
    dashboard claim got wrong.
    """
    import inspect
    src = inspect.getsource(tg.process_one_report)
    i_no_data = src.index('return "no_triangle_data"')
    i_slim = src.index("Build slim PDF")
    assert i_no_data < i_slim, \
        "no_triangle_data no longer returns before the models, so the documents' claim is now false"


def test_the_dashboard_table_describes_retained_structure_not_api_usage():
    flat = _flat(os.path.join("docs", "ocr-pipeline.md"))
    assert re.search(r"STRUCTURE THAT WAS RETAINED", flat), \
        "the status table must say it describes what was retained"
    assert re.search(r"cannot be used to infer API usage", flat, re.I)


# ------------------------------------------------------------------ the executed rule ------
def _no_mature(rag_years, model_years, report_year):
    """_no_mature_cohort through its real signature."""
    rag = {"triangle": {"underwriting_years": list(rag_years)}} if rag_years else {}
    results = [("model_%d" % i, {"_claims_triangle": {"type": "gross",
                                                      "underwriting_years": list(ys)}})
               for i, ys in enumerate(model_years)]
    return tg._no_mature_cohort(rag, results, report_year)


class TestTheClosureExamples:
    """The five cases the review asked for, through the executed function."""

    def test_one_old_cohort_is_mature_and_produces_development(self):
        young, triangles = _no_mature([2020], [], 2022)
        assert triangles, "the triangle must be seen"
        assert not young, "2020 <= 2022 - 2, so this cohort is usable however few columns there are"

    def test_two_recent_cohorts_are_not_mature(self):
        young, _t = _no_mature([2021, 2022], [], 2022)
        assert young

    def test_a_report_with_no_triangle_at_all_is_not_taken_to_be_young(self):
        young, triangles = _no_mature([], [], 2022)
        assert triangles == {}
        assert not young, "a report without any triangle must not be classified first-year on that account"

    def test_a_model_triangle_alone_is_enough_to_decide(self):
        young, triangles = _no_mature([], [[2015, 2016]], 2016)
        assert len(triangles) == 1
        assert young

    def test_one_mature_cohort_anywhere_is_enough_to_keep_the_record(self):
        young, _t = _no_mature([2015, 2016], [[2014, 2015, 2016]], 2016)
        assert not young, "2014 <= 2016 - 2, so the record holds a usable cohort"

    @pytest.mark.parametrize("parser,checks_usability", [
        ("_parse_nutrient_triangle", True),
        ("_parse_transposed_triangle", False),
        ("_parse_transposed_triangle_from_text", False),
    ])
    def test_which_triangle_parsers_check_usability_is_pinned(self, parser, checks_usability):
        """The three parsers do not agree, and the guide now says so. Pinned so that a future change
        to either behaviour is a deliberate one: aligning them would admit filings the corpus does not
        hold, which is a change to the sample and not a documentation repair
        (round 60, found while closing D02).
        """
        import table_extraction as te
        import inspect
        src = inspect.getsource(getattr(te, parser))
        body = src[src.index("len(uw_years) < 3"):]
        window = body[:400]
        assert ("PYD_EXCLUDED_RECENT_UW_YEARS" in window) == checks_usability, \
            "%s's usable-cohort behaviour changed; the guide's §11.2 describes the old one" % parser

    def test_the_guide_records_that_the_parsers_disagree(self):
        flat = _flat(os.path.join("docs", "ocr-pipeline.md"))
        assert "_parse_transposed_triangle()" in flat and "_parse_nutrient_triangle" in flat
        assert re.search(r"other two triangle parsers do not make that distinction", flat, re.I)

    def test_the_1884_2016_stub_is_the_post_model_kind(self):
        """The record the dashboard claim falsified: no models block, both models' figures kept."""
        path = os.path.join(ROOT, "pdf_extraction", "syndicate_1884_2016.json")
        if not os.path.exists(path):
            pytest.skip("syndicate_1884_2016.json is not present in this checkout")
        rec = json.load(io.open(path, encoding="utf-8"))
        assert rec.get("first_year_syndicate") is True
        assert "models" not in rec
        ev = rec["first_year_evidence"]
        assert set(ev["triangle_underwriting_years"]) >= {"rag"}
        assert len(ev["model_figures_not_stated"]) == 2, \
            "the stub records what both models gave, which is how we know they ran"
        for years in ev["triangle_underwriting_years"].values():
            assert all(y > rec["year"] - PYD_EXCLUDED_RECENT_UW_YEARS for y in years)
