"""The triangle reader places each current estimate on the report-year diagonal (review of 2 October 2026, M-1).

compute_pyd_from_triangle took each mature column's last filled cell as its current estimate, wherever it lay.
6112/2016's stray "7" one row past the 2013 column's staircase turned +0.893m into -19.264m (-41.6% of opening
reserves, the second most negative ratio in the working sample); 1967/2014's year-of-account results note was
read as a triangle; four more grids lost or gained a cell the same way, and 2791/2015's "139.326" was 139,326
with its separator read as a decimal point. The reader now places each current estimate by the column's own
age, checks it against the table's printed current-estimate row (which the parser now keeps), and refuses a
grid it cannot place.

Closing checks (the review's): the seven committed grids are refused or give the filing's figure; and no
committed triangle has a current estimate off its staircase, except the ones scripts/triangle_census.py lists
in pdf_extraction/audit/stage2_triangle_census.json for the PC to read and regenerate.

Run:  python -m pytest tests/test_triangle_diagonal.py -q
"""
import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import table_extraction as te  # noqa: E402
import test_gemini as tg  # noqa: E402
import triangle_census as tc  # noqa: E402

CENSUS = ROOT / "pdf_extraction" / "audit" / "stage2_triangle_census.json"
DIAGONAL = "not on the report-year diagonal"

#: (stem, the figure on the committed grid, the figure with the printed row the committed Azure cache gives);
#: None is a refusal. The filing figures are the review's: 6112/2016 read on page 32 (+0.893m), 1910/2019's
#: printed current estimate 53.9 on page 36 (5.5), 2791/2015's 139,326 (-2.131, the analysis's confirmed
#: figure), 6111/2015's grid without its mixed-unit total row (+0.490), 5000/2017's 2011 cohort kept (24.0).
SEVEN = (
    ("syndicate_6112_2016", None, 0.893),
    ("syndicate_1967_2014", None, None),
    ("syndicate_6111_2015", 0.49, 0.49),
    ("syndicate_5000_2017", 24.0, 24.0),
    ("syndicate_3624_2023", None, None),
    ("syndicate_1910_2019", None, 5.5),
    ("syndicate_2791_2015", None, -2.131),
)
#: grids the review flagged and read on the page as right: their committed figures stand
RIGHT = (("syndicate_727_2017", 2.966), ("syndicate_318_2021", -20.6), ("syndicate_510_2020", 20.0),
         ("syndicate_1110_2023", None))


def _record(stem):
    return json.loads((ROOT / "pdf_extraction" / (stem + ".json")).read_text(encoding="utf-8"))


def _rag(stem):
    rec = _record(stem)
    return next(b["_rag_triangle"] for b in rec["models"].values() if isinstance(b.get("_rag_triangle"), dict))


def _year(stem):
    return int(stem.rsplit("_", 1)[1])


def _read(tri, year):
    return tg.compute_pyd_from_triangle(copy.deepcopy(tri), year)


def _replayed(stem):
    """The committed grid with the printed row the parser keeps from the committed Azure cache, or None."""
    tri = _rag(stem)
    printed = tc.printed_row(stem, _year(stem), tri)
    return None if printed is None else dict(tri, current_estimate_row=printed)


@pytest.mark.parametrize("stem,committed,replayed", SEVEN)
def test_the_seven_grids_are_refused_or_give_the_filings_figure(stem, committed, replayed):
    v, why = _read(_rag(stem), _year(stem))
    assert v == committed, (stem, v, why)
    tri = _replayed(stem)
    if replayed is not None and replayed != committed:
        assert tri is not None, (stem, "the committed Azure cache no longer gives the printed row")
    if tri is not None:
        v2, why2 = _read(tri, _year(stem))
        assert v2 == replayed, (stem, v2, why2)


def test_6112_2016_is_the_page():
    """+0.893m: (20,980 - 21,377) + (20,407 - 20,650) + (24,752 - 23,219) GBP000, +1.93% of 46.298m."""
    v, why = _read(_replayed("syndicate_6112_2016"), 2016)
    assert v == pytest.approx(0.893) and abs(v / 46.298 * 100 - 1.93) < 0.005, why
    assert "-243.000" in why and "beyond the staircase" in why


@pytest.mark.parametrize("stem,figure", RIGHT)
def test_grids_read_as_right_keep_their_figures(stem, figure):
    rec = _record(stem)
    route = next(b["_pyd_route"] for b in rec["models"].values() if (b.get("_pyd_route") or {}).get("source"))
    figure = route["value"] if figure is None else figure
    for tri in [t for t in (_rag(stem), _replayed(stem)) if t is not None]:
        v, why = _read(tri, _year(stem))
        assert v == pytest.approx(figure), (stem, v, why)


def _grid(rows, years, units="millions", printed=None):
    tri = {"type": "gross", "units": units, "units_evidence": "header", "underwriting_years": list(years),
           "development_rows": [list(r) for r in rows]}
    if printed is not None:
        tri["current_estimate_row"] = list(printed)
    return tri


# A clean 2015-2019 grid at t=2019: 2015 is aged 5 (rows 0-4), 2019 one row.
CLEAN = [[100, 110, 120, 130, 140], [150, 160, 170, 180, None], [155, 158, 175, None, None],
         [152, 157, None, None, None], [151, None, None, None, None]]
YEARS = (2015, 2016, 2017, 2018, 2019)


def test_a_clean_grid_is_read_as_before():
    v, why = _read(_grid(CLEAN, YEARS), 2019)
    assert v == pytest.approx(-1 - 1 + 5), why


def test_a_stray_cell_beyond_the_staircase_is_refused_or_placed_by_the_printed_row():
    rows = copy.deepcopy(CLEAN)
    rows[4][1] = 7          # 2016's column one row past its age
    v, why = _read(_grid(rows, YEARS), 2019)
    assert v is None and DIAGONAL in why and "beyond" in why
    v, why = _read(_grid(rows, YEARS, printed=[151, 157, 175, 180, 140]), 2019)
    assert v == pytest.approx(3.0), why


def test_a_column_short_of_its_diagonal_is_refused_or_read_from_the_printed_row():
    rows = copy.deepcopy(CLEAN)
    rows[4][0] = None       # 2015's deepest cell lost
    v, why = _read(_grid(rows, YEARS), 2019)
    assert v is None and "short of" in why
    v, why = _read(_grid(rows, YEARS, printed=[151, 157, 175, 180, 140]), 2019)
    assert v == pytest.approx(3.0), why
    assert "the diagonal cell is missing" in why


def test_a_printed_row_that_contradicts_the_diagonal_cell_refuses_the_grid():
    v, why = _read(_grid(CLEAN, YEARS, printed=[149, 157, 175, 180, 140]), 2019)
    assert v is None and "is not the diagonal cell" in why


def test_a_misaligned_printed_row_is_not_used():
    """A value that cannot be a reading of its column (two cells run together) means the row is not aligned."""
    v, why = _read(_grid(CLEAN, YEARS, printed=[151157, 175, 180, 140, None]), 2019)
    assert v == pytest.approx(3.0), why


def test_a_grid_that_starts_one_year_later_is_read_one_row_up():
    rows = [r for r in copy.deepcopy(CLEAN)[1:]] + [[None] * 5]
    rows = [[r[0], r[1], r[2], r[3], None] for r in rows]      # every column one row short, no report-year column
    v, why = _read(_grid(rows, YEARS), 2019)
    assert v is not None, why


def test_a_movement_table_is_refused():
    """382's tables print the first year's estimate and each later year's movement; the printed row is the sum."""
    rows = [[100, 110, 120, 130, 140], [10, -5, 8, 4, None], [-3, 2, -1, None, None], [1, -1, None, None, None],
            [-2, None, None, None, None]]
    v, why = _read(_grid(rows, YEARS, printed=[106, 106, 127, 134, 140]), 2019)
    assert v is None and ("negative values" in why or "movements" in why), why


def test_a_results_table_read_as_a_triangle_is_refused():
    rows = [[-2339, 0, 0, 0, 0, 0], [1629, None, None, None, None, None], [201, None, None, None, None, None],
            [0, None, None, None, None, None], [-5831, None, None, None, None, None],
            [3251, None, None, None, None, None]]
    v, why = _read(_grid(rows, range(2009, 2015), units="thousands"), 2014)
    assert v is None and "negative values" in why


def test_an_implausible_step_is_refused():
    rows = copy.deepcopy(CLEAN)
    rows[4][0] = 1.51       # 151 read with its separator as a decimal point
    v, why = _read(_grid(rows, YEARS), 2019)
    assert v is None and "not one estimate developing" in why


def test_zeros_beyond_the_staircase_do_not_make_a_development_row_a_summary_row():
    """5000/2017: a last row [228, 0, ..., 0] under dash-zeros was stripped as a summary, losing 2011's 228."""
    rows = [[100, 90, 80, 70], [120, 95, 85, 0], [128, 97, 0, 0], [128, 0, 0, 0]]
    v, why = _read(_grid(rows, (2014, 2015, 2016, 2017)), 2017)
    assert v == pytest.approx(0 + 2), why


def test_the_parser_keeps_the_printed_current_estimate_row():
    """6112/2016's note 10 in the committed Azure cache: "Estimated total losses 20,980 | 20,407 | 24,752 | 22,870 |
    13,820" under the development rows."""
    cache = json.loads((ROOT / "pdf_extraction" / "azure_output" / "syndicate_6112_2016_azure.json")
                       .read_text(encoding="utf-8"))
    rows = []
    for entry in cache["tables"]:
        res, _ = te._parse_nutrient_triangle(entry["grid"], 2016)
        if isinstance(res, te.TriangleData) and res.current_estimate_row:
            rows.append(res.to_dict()["current_estimate_row"])
    assert [20980.0, 20407.0, 24752.0, 22870.0, 13820.0] in rows, rows


# --- the corpus -------------------------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def census():
    return json.loads(CENSUS.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def corpus():
    """{(stem, block): (fingerprint, outcome, outcome with the printed row or None, routes)} for every committed
    triangle, read by the current reader."""
    out = {}
    for stem, _syn, year, rec in tc.records():
        for name, tri, routes in tc.blocks(rec):
            new = tc.read(tg.compute_pyd_from_triangle, tri, year)
            replayed = None
            if name == "rag_triangle":
                printed = tc.printed_row(stem, year, tri)
                if printed is not None:
                    replayed = tc.read(tg.compute_pyd_from_triangle, dict(tri, current_estimate_row=printed), year)
            out[(stem, name)] = (tc.fingerprint(tri), new, replayed, routes)
    return out


def test_the_census_is_what_the_reader_gives_on_the_committed_grids(census, corpus):
    assert census["entries"], "the census is empty"
    for e in census["entries"]:
        key = (e["stem"], e["block"])
        assert key in corpus, (key, "the census names a triangle no committed record holds: write it again")
        fp, new, replayed, _ = corpus[key]
        assert fp == e["grid"], (key, "the committed grid changed: run scripts/triangle_census.py --write")
        assert tc._outcome(*new) == e["after"], key
        if "after_with_printed_row" in e:
            assert replayed is not None and tc._outcome(*replayed) == e["after_with_printed_row"], key


def test_no_committed_triangle_is_off_its_diagonal_unless_the_census_lists_it(census, corpus):
    """The closing check: a committed triangle the reader refuses for its diagonal, or a triangle figure the
    record carries that the reader no longer gives, is in the census, awaiting the PC's reading and an offline
    regeneration."""
    listed = {(e["stem"], e["block"]) for e in census["entries"]}
    off = []
    for key, (_fp, new, replayed, routes) in corpus.items():
        final = replayed if replayed is not None else new
        if final[0] is None and (DIAGONAL in final[1] or "negative values" in final[1]
                                 or "not one estimate developing" in final[1] or "movements" in final[1]):
            off.append(key)
            continue
        if key[1] == "rag_triangle":
            for route in routes.values():
                if route.get("source") == "rag_triangle" and final[0] is not None \
                        and abs(final[0] - route["value"]) > 0.0005:
                    off.append(key)
    unlisted = sorted(k for k in off if k not in listed)
    assert not unlisted, ("%d committed triangles are off their diagonal or no longer give their figure and are not "
                          "in the census: %s" % (len(unlisted), unlisted[:8]))


def test_the_census_counts_are_its_entries(census):
    rag = [e for e in census["entries"] if e["block"] == "rag_triangle"]
    c = census["counts"]
    assert c["rag_triangle_entries"] == len(rag)
    assert c["claims_triangle_entries"] == len(census["entries"]) - len(rag)
    assert c["rag_refused_on_replay"] == sum(
        1 for e in rag if "refused" in (e.get("after_with_printed_row") or e["after"]))
    assert c["rag_replay_stops_on_a_cache_miss"] == sum(1 for e in rag if e.get("vision_pages_cached") == [])
