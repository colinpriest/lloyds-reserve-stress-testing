r"""One admissibility rule, and every triangle parser reaching it (round 61).

Five parsers used to decide for themselves whether a syndicate was too young for prior-year
development, and they did not agree:

  * ``_parse_nutrient_triangle``            the usable-cohort rule
  * ``_parse_transposed_triangle``          ``len(uw_years) < 3`` alone
  * ``_parse_transposed_triangle_from_text````len(uw_years) < 3`` alone
  * ``_parse_triangle_from_text``           the same count, but it rejected the page outright
  * ``test_gemini._parse_triangle_xlsx``    the same count, plus its own ``report_year - 2``
                                            staleness cut and the count read before the year range

All five now call ``table_extraction.triangle_admissibility``. These tests hold the rule to its
boundaries, prove it cannot change what the nutrient parser used to accept, pin every parser to it,
and fail if any parser grows its own copy again.

Run:  python -m pytest tests/test_triangle_admissibility.py -q
"""
import inspect
import io
import itertools
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pytest  # noqa: E402

import table_extraction as te  # noqa: E402
import test_gemini as tg  # noqa: E402
from table_extraction import (MAX_UW_YEAR_LAG, PYD_EXCLUDED_RECENT_UW_YEARS,  # noqa: E402
                              TRIANGLE_NEW_SYNDICATE, TRIANGLE_PARSE, TRIANGLE_REJECT,
                              triangle_admissibility)

LAG, RECENT = MAX_UW_YEAR_LAG, PYD_EXCLUDED_RECENT_UW_YEARS
#: every parser that reaches a young/reject/parse verdict, and where it lives
PARSERS = (
    ("table_extraction", "_parse_nutrient_triangle"),
    ("table_extraction", "_parse_transposed_triangle"),
    ("table_extraction", "_parse_transposed_triangle_from_text"),
    ("table_extraction", "_parse_triangle_from_text"),
    ("test_gemini", "_parse_triangle_xlsx"),
)


def _source(module, name):
    mod = {"table_extraction": te, "test_gemini": tg}[module]
    return inspect.getsource(getattr(mod, name))


def _code_lines(text):
    """{line number: the executable part of that line}, with comments and strings removed.

    A rule lives in code. Comments record the rule this round deleted, docstrings explain it, and
    the extraction prompts tell a model in words which underwriting years to sum -- all three
    mention report_year - 2 legitimately and none of them is a second copy of the rule. An
    interpolation inside a prompt f-string is text for a model too, and Python tokenises its
    expressions as code, so an f-string is skipped whole. Tokenising is what makes the scan
    generalise: it does not depend on my guessing which wordings to excuse.
    """
    import tokenize
    lines = {}
    depth = 0
    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            name = tokenize.tok_name.get(tok.type, "")
            if name == "FSTRING_START":
                depth += 1
                continue
            if name == "FSTRING_END":
                depth = max(0, depth - 1)
                continue
            if depth or tok.type in (tokenize.COMMENT, tokenize.STRING):
                continue
            if tok.type in (tokenize.NEWLINE, tokenize.NL, tokenize.INDENT,
                            tokenize.DEDENT, tokenize.ENDMARKER):
                continue
            lines[tok.start[0]] = lines.get(tok.start[0], "") + tok.string
    except (tokenize.TokenError, IndentationError, SyntaxError):
        # an unparsable source is not evidence of anything; scan it raw rather than pass silently
        return {i + 1: line for i, line in enumerate(text.splitlines())}
    return lines


def _code_only(text):
    """The same, as one string, for the per-function checks where line numbers do not matter."""
    return "\n".join(_code_lines(text).get(i, "") for i in range(1, text.count("\n") + 2))


# ------------------------------------------------------------------------- the rule itself ----
class TestTheRule:
    def test_a_cohort_at_t_minus_two_is_usable_however_few_columns_there_are(self):
        verdict, detail = triangle_admissibility([2020], 2022)
        assert verdict == TRIANGLE_PARSE, detail
        assert detail is None

    def test_a_single_recent_cohort_is_a_young_syndicate(self):
        verdict, detail = triangle_admissibility([2022], 2022)
        assert verdict == TRIANGLE_NEW_SYNDICATE
        assert "1 UW year(s)" in detail and "2022-2022" in detail

    def test_two_recent_cohorts_are_still_a_young_syndicate(self):
        verdict, _d = triangle_admissibility([2021, 2022], 2022)
        assert verdict == TRIANGLE_NEW_SYNDICATE

    def test_the_boundary_is_exactly_report_year_minus_the_excluded_years(self):
        ry = 2022
        assert triangle_admissibility([ry - RECENT], ry)[0] == TRIANGLE_PARSE
        assert triangle_admissibility([ry - RECENT + 1], ry)[0] == TRIANGLE_NEW_SYNDICATE

    def test_no_years_at_all_is_a_rejection_not_a_young_syndicate(self):
        verdict, detail = triangle_admissibility([], 2022)
        assert verdict == TRIANGLE_REJECT
        assert "no underwriting years" in detail

    def test_a_year_after_the_report_year_is_rejected(self):
        verdict, detail = triangle_admissibility([2020, 2021, 2023], 2022)
        assert verdict == TRIANGLE_REJECT
        assert "> report year" in detail

    def test_the_lag_boundary_is_exactly_max_uw_year_lag(self):
        ry = 2022
        assert triangle_admissibility([ry - LAG], ry)[0] == TRIANGLE_PARSE
        assert triangle_admissibility([ry - LAG - 1], ry)[0] == TRIANGLE_REJECT

    def test_the_verdict_does_not_depend_on_how_many_columns_a_triangle_has(self):
        """Two sets with the same oldest and newest year reach the same verdict, whatever sits
        between them. This is the property the old rule did not have."""
        for ry in (2016, 2022):
            for oldest in range(ry - LAG, ry + 1):
                sparse = [oldest, ry] if oldest != ry else [ry]
                dense = sorted(set(range(oldest, ry + 1)))
                assert triangle_admissibility(sparse, ry)[0] == \
                    triangle_admissibility(dense, ry)[0], (ry, oldest)

    def test_three_or_more_distinct_years_can_never_be_a_young_syndicate(self):
        """Why the rule needs no column count: three distinct years no later than the report year
        cannot all fall inside the most recent PYD_EXCLUDED_RECENT_UW_YEARS, so every triangle the
        nutrient parser used to accept on its count alone still reaches PARSE. Enumerated rather
        than argued."""
        for ry in (2014, 2018, 2024):
            pool = range(ry - LAG, ry + 1)
            for size in range(RECENT + 1, len(list(pool)) + 1):
                for combo in itertools.combinations(pool, size):
                    assert triangle_admissibility(list(combo), ry)[0] == TRIANGLE_PARSE, combo

    def test_duplicated_years_do_not_change_the_verdict(self):
        assert triangle_admissibility([2022, 2022, 2022], 2022)[0] == TRIANGLE_NEW_SYNDICATE
        assert triangle_admissibility([2020, 2020], 2022)[0] == TRIANGLE_PARSE

    def test_years_given_as_strings_are_read_as_years(self):
        assert triangle_admissibility(["2020", "2021"], 2022)[0] == TRIANGLE_PARSE


# --------------------------------------------------------------------- every parser uses it ----
class TestEveryParserUsesIt:
    @pytest.mark.parametrize("module,name", PARSERS)
    def test_the_parser_calls_the_shared_rule(self, module, name):
        src = _source(module, name)
        assert "triangle_admissibility(" in src, \
            "%s.%s decides for itself again" % (module, name)

    @pytest.mark.parametrize("module,name", PARSERS)
    def test_the_parser_keeps_no_column_count_of_its_own(self, module, name):
        """The rule the round removed, in the form each parser wrote it."""
        src = _code_only(_source(module, name))
        assert not re.search(r"len\(uw_years\)\s*<\s*3", src), \
            "%s.%s tests the raw underwriting-year count again" % (module, name)
        assert not re.search(r"report_year\s*-\s*2\b", src), \
            "%s.%s hard-codes a two-year cut-off again" % (module, name)

    @pytest.mark.parametrize("module,name", PARSERS)
    def test_the_parser_does_not_apply_the_cohort_test_itself(self, module, name):
        src = _code_only(_source(module, name))
        assert "PYD_EXCLUDED_RECENT_UW_YEARS" not in src, \
            "%s.%s applies the cohort test itself instead of calling the rule" % (module, name)

    def test_no_other_source_in_the_repository_keeps_a_copy(self):
        """Driven from the repository, not from a list of parsers I happened to find: any source
        that tests an underwriting-year count against 3, or cuts off at report_year - 2, is either
        the rule itself or a copy of it."""
        offenders = []
        for dirpath, dirnames, filenames in os.walk(ROOT):
            dirnames[:] = [d for d in dirnames
                           if d not in {".git", "__pycache__", "pdf_extraction", "syndicate_reports",
                                        "results", "data", "docs", "combined", "market_commentary"}]
            for fn in sorted(filenames):
                if not fn.endswith(".py"):
                    continue
                rel = os.path.relpath(os.path.join(dirpath, fn), ROOT).replace("\\", "/")
                if rel == "tests/test_triangle_admissibility.py":
                    continue
                with io.open(os.path.join(dirpath, fn), encoding="utf-8",
                             errors="replace") as fh:
                    text = fh.read()
                for lineno, code in sorted(_code_lines(text).items()):
                    if re.search(r"len\(uw_years\)<3|report_year-2\b", code):
                        offenders.append("%s:%d  %s" % (rel, lineno, code[:70]))
        assert not offenders, "these sources keep their own copy of the rule: %s" % offenders


# ------------------------------------------------------- structure before age, where it is due ----
class TestStructureBeforeAge:
    def test_the_xlsx_parser_proves_the_table_is_a_triangle_before_calling_it_young(self):
        """_parse_triangle_xlsx is tried on every fragment Adobe wrote, most of which are not
        triangles, so it may not say "young" until the development rows prove one. Without this,
        134 fragments carrying a stray year in a header read as evidence of a young syndicate."""
        src = _source("test_gemini", "_parse_triangle_xlsx")
        i_rows = src.index("if len(dev_rows) < 2:")
        i_young = src.index("TRIANGLE_NEW_SYNDICATE")
        assert i_rows < i_young, \
            "the xlsx parser calls a syndicate young before it knows the table is a triangle"

    @pytest.mark.parametrize("name", ["_parse_nutrient_triangle", "_parse_transposed_triangle"])
    def test_the_grid_parsers_may_decide_age_first_because_the_grid_was_categorised(self, name):
        """The other side of the same coin, pinned so that swapping the order becomes a deliberate
        act: these parsers only see grids the categoriser tagged claims_triangle, and a young
        syndicate's triangle can carry fewer than two development rows, so requiring structure
        first would suppress the detection they exist for. Measured in round 61: it would
        re-decide 32 of the 70 committed first-year stubs."""
        src = _source("table_extraction", name)
        i_young = src.index("TRIANGLE_NEW_SYNDICATE")
        i_rows = src.index("if len(dev_rows) < 2:")
        assert i_young < i_rows, \
            "%s now asks for structure first; that re-decides committed first-year stubs" % name

    def test_the_text_route_does_not_raise_the_first_year_flag(self):
        """_parse_triangle_from_text returns "new_syndicate" for 111 pages that it used to reject.
        Its two call sites act only on a TriangleData, so nothing is flagged by that; making them
        flag it would change which records the corpus holds."""
        for fn_name in ("_extract_nutrient", "_extract_azure"):
            fn = getattr(te, fn_name, None)
            if fn is None:
                pytest.fail("%s is gone; the text fallback's call sites must be re-checked" % fn_name)
            src = inspect.getsource(fn)
            i = src.index("_parse_triangle_from_text(")
            window = src[i:i + 700]
            assert "isinstance(tri_result, TriangleData)" in window, \
                "%s no longer gates the text fallback on a TriangleData" % fn_name
            assert "first_year_syndicate" not in window, \
                "%s now raises the first-year flag from the text route" % fn_name


# ------------------------------------------------------------------------ through the parsers ----
def _grid(rows):
    return [[("" if c is None else str(c)) for c in row] for row in rows]


#: syndicate 2468's 2022 filing, table 4 of its cached Azure extraction, verbatim. One
#: underwriting year, 2020, and 2020 <= 2022 - 2, so the cohort is usable: the guide's worked
#: example of a single-column triangle that yields development.
GRID_2468_2022 = [
    ["Underwriting Year", "2020", "Total"],
    ["", "£'000", "£'000"],
    ["Estimate of cumulative gross claims", "", ""],
    ["At the end of the first year", "29,267", "29,267"],
    ["- One year later", "28,431", "28,431"],
    ["- Two years later", "28,278", "28,278"],
    ["- Three years later", "-", "-"],
    ["- Four years later", "-", "-"],
    ["- Five years later", "-", "-"],
    ["Current estimate of cumulative claims", "28,278", "28,278"],
    ["Cumulative payments to date", "17,078", "17,078"],
    ["Liability recognised in the balance sheet", "11,200", "11,200"],
]

#: syndicate 308's 2018 filing, table 9, verbatim -- the grid the round-60 review's three filings
#: turn on. It is NOT a claims triangle: its columns are three syndicate numbers (510, 557, 308)
#: and its rows are years of account. The categoriser tagged it claims_triangle all the same.
GRID_308_2018_TABLE_9 = [
    ["2017", "Syndicate annual accounting result", "", ""],
    ["Year of account", "510", "557", "308"],
    ["", "£'000s", "£'000s", "£'000s"],
    ["2017", "(183,451)", "(14,326)", "(13,950)"],
    ["2016", "35,705", "1,771", "(8,875)"],
    ["2015 & prior", "48,915", "2,034", "(511)"],
    ["", "(98,831)", "(10,521)", "(23,336)"],
]


class TestThroughTheParsers:
    """The verdicts that matter, on grids taken verbatim from the cached corpus."""

    def test_a_single_column_triangle_with_a_usable_cohort_is_parsed(self):
        res, details = te._parse_nutrient_triangle(GRID_2468_2022, 2022)
        assert isinstance(res, te.TriangleData), details
        assert sorted(int(y) for y in res.underwriting_years) == [2020]
        assert len(res.development_rows) >= 2, details

    def test_the_same_triangle_read_two_years_earlier_is_a_young_syndicate(self):
        """The same grid in a 2020 report: 2020 > 2020 - 2, so no cohort has a previous diagonal."""
        res, details = te._parse_nutrient_triangle(GRID_2468_2022, 2020)
        assert res == "new_syndicate", details
        assert "2020-2020" in details

    def test_the_nutrient_and_transposed_parsers_no_longer_disagree_on_the_308_grid(self):
        """What the alignment actually did to the round-60 divergence: both parsers now reach the
        same verdict on the grid, where before one called it young and the other parsed it."""
        nutrient, n_det = te._parse_nutrient_triangle(GRID_308_2018_TABLE_9, 2018)
        transposed, t_det = te._parse_transposed_triangle(GRID_308_2018_TABLE_9, 2018)
        assert not isinstance(nutrient, str), n_det
        assert not isinstance(transposed, str), t_det

    def test_the_308_grid_is_admitted_as_a_candidate_and_must_keep_losing_on_score(self):
        """An unclosed defect, pinned rather than hidden (round 61).

        This grid is an accounting-result table, not a triangle, and no version of the
        admissibility rule says so: the old one called it a young syndicate and raised the
        first-year flag, the aligned one parses it into a candidate. It loses the Azure path's
        score to the filing's real triangle -- which is why aligning the rule changed nothing any
        route reported, for all 1,055 cached filings -- and this test records the margin. A
        staircase test (a UW year may not carry more than report_year - y + 1 development values;
        2017 carries three in a 2018 report) would reject it outright, and is the repair, but it
        is a new rule with its own corpus measurement rather than part of this alignment."""
        res, details = te._parse_transposed_triangle(GRID_308_2018_TABLE_9, 2018)
        assert isinstance(res, te.TriangleData), details
        years = sorted(int(y) for y in res.underwriting_years)
        assert years == [2016, 2017]
        n_values = sum(1 for row in res.development_rows for v in row if v is not None)
        score = ((1000 if res.type == "gross" else 0) + len(years) * 10 + n_values)
        assert score == 1026, ("the bogus candidate's score moved; re-check that the filing's real "
                              "triangle still outscores it (round 61 measured 1026)")
        assert len(years) == 2, "two underwriting years is what keeps this candidate cheap"

    def test_a_fragment_with_one_stray_year_and_no_development_rows_is_not_a_triangle(self):
        """What the xlsx parser must keep saying: not a triangle, and not a young syndicate."""
        grid = _grid([
            ["Note 14", "2015", "2014"],
            ["Gross written premium", "12,345", "11,000"],
            ["Net earned premium", "11,000", "10,500"],
            ["Profit", "500", "400"],
        ])
        res, details = te._parse_nutrient_triangle(grid, 2016)
        assert not isinstance(res, te.TriangleData), details
