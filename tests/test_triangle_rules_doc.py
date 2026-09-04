"""The README's triangle rules are the implemented rules.

Round 51 of the paper review found the README saying the most recent underwriting
year must be within two years of the report year (the code accepts five) and that
only the most recent underwriting year is excluded from the PYD sum (the code, and
the manuscript, exclude two). The rules now live in two constants in
table_extraction.py, used by every parser and the PYD step, and the README's
statements are checked against them here.

Run:  python -m pytest tests/test_triangle_rules_doc.py -q
"""
import io
import os
import re

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(rel):
    return io.open(os.path.join(HERE, rel), encoding="utf-8", errors="replace").read()


def _constants():
    src = _read("table_extraction.py")
    lag = int(re.search(r"^MAX_UW_YEAR_LAG = (\d+)", src, re.M).group(1))
    excl = int(re.search(r"^PYD_EXCLUDED_RECENT_UW_YEARS = (\d+)", src, re.M).group(1))
    return lag, excl


def test_the_readme_states_the_uw_year_window():
    lag, _ = _constants()
    readme = _read("README.md")
    assert "report_year - %d <= max_uw_year <= report_year" % lag in readme
    assert "within %d years of `report_year`" % lag in readme
    assert "within 2 years of the report year" not in readme


def test_the_readme_states_the_excluded_recent_years():
    _, excl = _constants()
    readme = _read("README.md")
    assert "uw_year <= report_year - %d" % excl in readme
    assert "PYD_EXCLUDED_RECENT_UW_YEARS = %d" % excl in readme
    assert "except the most recent\n" not in readme


def test_the_code_uses_the_constants_not_literals():
    for rel in ("table_extraction.py", "test_gemini.py"):
        src = _read(rel)
        assert "report_year - 5" not in src, rel
        assert "uw_year >= report_year - 1" not in src, rel
    assert "MAX_UW_YEAR_LAG" in _read("test_gemini.py")
    assert "PYD_EXCLUDED_RECENT_UW_YEARS" in _read("test_gemini.py")
