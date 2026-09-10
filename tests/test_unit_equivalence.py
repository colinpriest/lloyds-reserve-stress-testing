"""Round 55 (T03, T02): the percentage-against-monetary decision rests on unit
evidence, not magnitude, so the same claims triangle in millions and in thousands
gives the same movement; a percentage triangle still takes the loss-ratio route; the
magnitude heuristic survives only for a triangle whose unit was never read. The
extraction prompt states one business-mix hierarchy, the claims-incurred identity
without premiums, and a loss-ratio route that needs underwriting-year premiums.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import table_extraction as te  # noqa: E402
import test_gemini as tg  # noqa: E402

REPORT_YEAR = 2014


def _triangle(scale, units, **extra):
    """A gross triangle whose usable years (2010, 2011, 2012) each develop by +5m
    between the previous diagonal and the current estimate: +15m in total."""
    rows = [
        [100.0, 80.0, 60.0, 40.0, 20.0],   # after one year
        [105.0, 85.0, 65.0, 45.0, None],   # after two years
        [110.0, 90.0, 70.0, None, None],   # after three years
        [115.0, 95.0, None, None, None],
        [120.0, None, None, None, None],
    ]
    d = {"type": "gross", "currency": "GBP", "units": units,
         "underwriting_years": [2010, 2011, 2012, 2013, 2014],
         "development_rows": [[None if v is None else v * scale for v in r] for r in rows]}
    d.update(extra)
    return d


def test_millions_and_thousands_give_the_same_movement():
    pyd_m, det_m = tg.compute_pyd_from_triangle(_triangle(1.0, "millions"), REPORT_YEAR)
    pyd_k, det_k = tg.compute_pyd_from_triangle(_triangle(1000.0, "thousands"), REPORT_YEAR)
    assert pyd_m is not None, det_m
    assert pyd_k is not None, det_k
    assert abs(pyd_m - 15.0) < 1e-6 and abs(pyd_k - 15.0) < 1e-6


def test_an_evidenced_millions_triangle_is_not_rejected_on_magnitude():
    pyd, det = tg.compute_pyd_from_triangle(_triangle(1.0, "millions", units_evidence="header"),
                                            REPORT_YEAR)
    assert pyd is not None and abs(pyd - 15.0) < 1e-6, det


def test_a_percentage_triangle_takes_the_loss_ratio_route():
    pyd, det = tg.compute_pyd_from_triangle(_triangle(1.0, "percentage"), REPORT_YEAR)
    assert pyd is None and "loss ratio" in det and "percentages" in det


def test_the_magnitude_heuristic_applies_only_to_an_unread_unit():
    pyd, det = tg.compute_pyd_from_triangle(_triangle(1.0, "millions", units_evidence="default"),
                                            REPORT_YEAR)
    assert pyd is None and "magnitude heuristic" in det
    # a default-unit triangle whose values exceed 200 is money as before
    pyd2, det2 = tg.compute_pyd_from_triangle(_triangle(10.0, "millions", units_evidence="default"),
                                              REPORT_YEAR)
    assert pyd2 is not None and abs(pyd2 - 150.0) < 1e-6, det2


def test_triangle_units_reads_the_table_evidence():
    small = [[66.0, 43.0], [67.0, 45.0]]
    big = [[1200.0, 900.0], [1300.0, 950.0]]
    assert te._triangle_units("gross claims development £'000 2012 2013", big) == ("thousands", "header")
    assert te._triangle_units("gross claims development £m 2012 2013", small) == ("millions", "header")
    assert te._triangle_units("gross ratios 12 months 24 months %", small) == ("percentage", "header")
    # both marker classes: the monetary unit with evidence 'conflict', never a decision by magnitude
    assert te._triangle_units("gross ratios total ultimate losses ($m)", small) == ("millions", "conflict")
    assert te._triangle_units("gross claims development £m combined ratio 95%", small) == ("millions", "conflict")
    assert te._triangle_units("gross claims development £'000 100%", big) == ("thousands", "conflict")
    assert te._triangle_units("claims development 2012 2013", small) == ("millions", "default")


def test_parsed_triangles_carry_their_unit_evidence():
    tri = te.TriangleData(type="gross", currency="GBP", units="millions",
                          underwriting_years=[2012], development_rows=[[1.0]])
    assert tri.units_evidence == "default"
    assert tri.to_dict()["units_evidence"] == "default"


# ---- T02: the prompt states one hierarchy, one identity, one fallback rule
def _prompt_text():
    src = (ROOT / "test_gemini.py").read_text(encoding="utf-8")
    return src


def test_prompt_has_one_business_mix_hierarchy():
    src = _prompt_text()
    assert "prefer DIVISIONAL TOTALS over regulatory sub-categories" not in src
    assert "these often provide a more granular divisional breakdown" not in src
    assert "when the report has NO segmental analysis note" in src
    assert "Never merge the two sources" in src


def test_prompt_defines_claims_incurred_without_premiums():
    src = _prompt_text()
    assert "premiums earned minus claims paid minus reserve changes" not in src
    assert "claims paid in the year plus the change in the gross provision" in src


def test_prompt_loss_ratio_route_requires_year_premiums():
    src = _prompt_text()
    assert "use the total gross premiums as an approximation" not in src
    assert "loss-ratio table without underwriting-year premiums" in src


def test_prompt_version_moved_with_the_rules():
    src = _prompt_text()
    m = re.search(r'^PROMPT_VERSION = "(\d+)\.(\d+)"', src, re.M)
    assert m and (int(m.group(1)), int(m.group(2))) >= (2, 11)
    assert (ROOT / "docs" / "prompt-history.md").exists()


def test_conflict_evidence_keeps_the_magnitude_heuristic_and_nothing_more():
    # small values under conflicting markers: rejected by the heuristic, named as such
    pyd, det = tg.compute_pyd_from_triangle(_triangle(1.0, "millions", units_evidence="conflict"), REPORT_YEAR)
    assert pyd is None and "ratio marker beside the monetary one" in det
    # large values under conflicting markers: money, in the stated unit
    pyd_m, _ = tg.compute_pyd_from_triangle(_triangle(10.0, "millions", units_evidence="conflict"), REPORT_YEAR)
    pyd_k, _ = tg.compute_pyd_from_triangle(_triangle(10000.0, "thousands", units_evidence="conflict"), REPORT_YEAR)
    assert pyd_m is not None and pyd_k is not None and abs(pyd_m - pyd_k) < 1e-6


def test_an_evidenced_unit_is_not_relabelled_by_magnitude():
    # values above 10,000 in an evidenced millions triangle stay millions (round 55, B15)
    pyd, det = tg.compute_pyd_from_triangle(_triangle(200.0, "millions", units_evidence="header"), REPORT_YEAR)
    assert pyd is not None and abs(pyd - 3000.0) < 1e-6, det


def test_adjudicator_prompt_defines_claims_incurred_without_premiums():
    src = (ROOT / "adjudicate.py").read_text(encoding="utf-8")
    assert "premiums earned minus" not in src
    assert "claims paid in the year plus the change in the gross claims" in src


def test_prompt_version_register_ends_at_the_current_version():
    import json
    reg = json.loads((ROOT / "pdf_extraction" / "spec" / "prompt_versions.json").read_text(encoding="utf-8"))
    src = _prompt_text()
    cur = re.search(r'^PROMPT_VERSION = "([0-9.]+)"', src, re.M).group(1)
    assert reg["versions"][-1]["version"] == cur
    assert all(re.fullmatch(r"\d+\.\d+", v["version"]) for v in reg["versions"])


def test_offline_replay_leaves_the_committed_record_and_fails_loudly():
    src = _prompt_text()
    assert "existing_output.unlink()" not in src
    assert 'if run_errored and os.getenv("LLOYDS_EXTRACTION_OFFLINE") == "1":' in src


def test_transposed_grid_keeps_the_first_block_when_years_repeat():
    """A gross block followed by a net block under one header (510/557/1880,
    2020-2023) is one triangle, the first; the development is not the sum of both."""
    header = ["Year of Account", "End of first year", "One year later", "Two years later", "Claims Paid"]
    gross = [["Gross of reinsurance", "", "", "", ""],
             ["2012", "100", "110", "112", "(90)"],
             ["2013", "80", "90", "", "(70)"],
             ["2014", "60", "", "", "(20)"]]
    net = [["Net of reinsurance", "", "", "", ""],
           ["2012", "90", "95", "96", "(80)"],
           ["2013", "70", "78", "", "(60)"],
           ["2014", "50", "", "", "(15)"]]
    tri, details = te._parse_transposed_triangle([header] + gross + net, 2014)
    assert tri is not None and tri.underwriting_years == [2012, 2013, 2014], details
    assert tri.type == "gross"
    pyd, det = tg.compute_pyd_from_triangle(dict(tri.to_dict(), units="millions", units_evidence="header"), 2014)
    # 2012 is the only usable year: 112 - 110 = +2 on the gross block alone
    assert pyd is not None and abs(pyd - 2.0) < 1e-6, det


def _values(tri):
    """Every stored value, whatever the transposition."""
    return {v for row in tri.development_rows for v in row if isinstance(v, (int, float))}


def test_transposed_grid_types_the_block_it_captured():
    """A page with the gross block above the net block gives the gross triangle; a page
    with the net block first gives a net one, labelled net (round 55, review B2-05).
    The assertion is which block was captured -- by a value unique to it -- and how the
    triangle is typed, not which columns this parser keeps."""
    header = ["Year of Account", "End of first year", "One year later", "Two years later"]
    gross = [["Gross of reinsurance", "", "", ""],
             ["2012", "100", "110", "112"],
             ["2013", "80", "90", "91"],
             ["2014", "60", "61", "62"]]
    net = [["Net of reinsurance", "", "", ""],
           ["2012", "40", "41", "42"],
           ["2013", "43", "44", "45"],
           ["2014", "46", "47", "48"]]
    first, _ = te._parse_transposed_triangle([header] + gross + net, 2014)
    assert first.type == "gross"
    assert _values(first) & {110.0, 112.0} and not (_values(first) & {41.0, 44.0, 47.0})
    second, _ = te._parse_transposed_triangle([header] + net + gross, 2014)
    assert second.type == "net"
    assert _values(second) & {41.0, 44.0, 47.0} and not (_values(second) & {110.0, 112.0})


def test_transposed_grid_stops_at_the_next_basis_block_even_with_a_new_year():
    """The net block may reach further back than the gross block, so its extra year is
    not a repeat; the basis heading is what stops the capture."""
    header = ["Year of Account", "End of first year", "One year later", "Two years later"]
    grid = ([header]
            + [["Gross of reinsurance", "", "", ""], ["2012", "100", "110", "112"],
               ["2013", "80", "90", "91"], ["2014", "60", "61", "62"]]
            + [["Net of reinsurance", "", "", ""], ["2011", "150", "151", "152"],
               ["2012", "40", "41", "42"], ["2013", "43", "44", "45"]])
    tri, _ = te._parse_transposed_triangle(grid, 2014)
    assert tri.type == "gross" and tri.underwriting_years == [2012, 2013, 2014]
    assert not (_values(tri) & {150.0, 151.0, 152.0})
