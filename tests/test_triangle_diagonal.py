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
#: 6112/2016, 1910/2019 and 2791/2015 were regenerated offline on 3 October 2026 (stage 2, the PC steps): their
#: committed grids now carry the printed row, so the committed grid gives the filing's figure where, before, it was
#: refused (None). 3624/2023 was regenerated offline the same day from its page-vision reading (PDF page 38, one call of
#: option B, checked against the page cell by cell): its committed grid now gives +71.809, the figure the reviews read from
#: the page. 1967/2014 keeps its committed grid, which the reader refuses: it would be written as no deterministic reading
#: (it is declared in pdf_extraction/audit/redecision_pending.json).
SEVEN = (
    ("syndicate_6112_2016", 0.893, 0.893),
    ("syndicate_1967_2014", None, None),
    ("syndicate_6111_2015", 0.49, 0.49),
    ("syndicate_5000_2017", 24.0, 24.0),
    ("syndicate_3624_2023", 71.809, 71.809),
    ("syndicate_1910_2019", 5.5, 5.5),
    ("syndicate_2791_2015", -2.131, -2.131),
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


def test_6112_2016_gives_the_tables_figure_and_the_record_carries_the_filings_stated_one():
    """+0.893m is the table's figure (PDF page 32): (20,980 - 21,377) + (20,407 - 20,650) + (24,752 - 23,219) GBP000, +1.93% of 46.298m. It is the table's, and
    not the filing's last word: note 5 (PDF page 30) states the opposite direction, a favorable run-off deviation (prior accident year decrease) of 0.9m. The record
    carries the stated figure, -0.9 (a release), with the table's figure not applied: it has the opposite sign to both models' readings."""
    v, why = _read(_replayed("syndicate_6112_2016"), 2016)
    assert v == pytest.approx(0.893) and abs(v / 46.298 * 100 - 1.93) < 0.005, why
    assert "-243.000" in why and "beyond the staircase" in why
    for block in _record("syndicate_6112_2016")["models"].values():
        assert block["_pyd_route"]["source"] == "model_reading" and block["_pyd_route"]["value"] == pytest.approx(-0.9)
        assert "RAG PYD NOT APPLIED: deterministic figure +0.893m has the opposite sign to both model values" in str(block["data_quality_notes"])


def test_6112_2016s_note_5_states_the_opposite_direction_on_its_page():
    """The words that make the test above say "the table's figure": note 5 of the filing, PDF page 30. Needs the filing."""
    import finalize_structural_eligibility_audit as fin
    source = ROOT / "syndicate_reports" / "pdfs" / "syndicate_6112_2016.pdf"
    if not source.exists():
        pytest.skip("source filing not present in this checkout")
    words = "A favorable run-off deviation (prior accident year decrease) of \u00a30.9m (2015: adverse run-off deviation of \u00a31.9m) was experienced during the year"
    assert fin.quote_on_page(words, fin.page_texts(source)[30 - 1])


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


def test_a_stand_in_for_a_missing_diagonal_cell_must_be_a_plausible_step():
    """Review of the stage-2 branch, F5 (a): the printed value that stands in for a missing diagonal cell is held to
    the step rule. A printed value that is the column's sum is kept as a reading of the column, and here it would
    stand in as a step from 1 to 104."""
    rows = copy.deepcopy(CLEAN)
    for r, v in enumerate([100, 2, 1, 1, None]):
        rows[r][0] = v      # 2015's column one row short, its last cell 1
    v, why = _read(_grid(rows, YEARS, printed=[104, 157, 175, 180, 140]), 2019)
    assert v is None and "not one estimate developing" in why, why


def test_a_stripped_summary_row_stands_in_for_the_printed_row():
    """F5 (b): a summary row repeating each column's last cell is stripped from the grid and read as the table's
    current-estimate row (section 9.2). 2015's column is one row short, and its printed estimate is its last cell,
    so it does not place the missing diagonal cell: the refusal names the printed estimate."""
    rows = copy.deepcopy(CLEAN)
    rows[4][0] = None
    rows.append([152, 157, 175, 180, 140])
    v, why = _read(_grid(rows, YEARS), 2019)
    assert v is None and "printed current estimate (152" in why and "short of" in why, why


def test_a_printed_row_of_an_outflow_grid_is_normalised_with_it():
    """F5 (c): a grid printed wholly as outflows is normalised before differencing, and so is its printed row: the
    stray cell beyond 2016's staircase is placed by the printed row, as in the grid printed as positives."""
    rows = copy.deepcopy(CLEAN)
    rows[4][1] = 7
    neg = [[-v if v is not None else None for v in r] for r in rows]
    v, why = _read(_grid(neg, YEARS, printed=[-151, -157, -175, -180, -140]), 2019)
    assert v == pytest.approx(3.0), why


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
    # every movement positive: no negative cell refuses it, and the printed sum names it a movements table
    rows = [[100, 110, 120, 130, 140], [10, 5, 8, 4, None], [3, 2, 1, None, None], [1, 1, None, None, None],
            [2, None, None, None, None]]
    v, why = _read(_grid(rows, YEARS, printed=[116, 118, 129, 134, 140]), 2019)
    assert v is None and "movements by development year" in why, why


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
    # the refused triangles with no committed page-vision entry (15 before the census walked the step, when it said that the replay stops on a cache miss for every one of
    # them): of these, the ones that reach page vision on pages with no committed entry stop on a cache miss (13 then), and the ones that reach no page-vision step do not (2)
    assert c["rag_refused_with_no_cached_vision_page"] == sum(1 for e in rag if e.get("vision_pages_cached") == [])
    assert c["rag_replay_stops_on_a_cache_miss"] == sum(1 for e in rag if e.get("vision_pages_walked") and not (
        set(e["vision_pages_walked"]) & set(e["vision_pages_cached"])))
    assert c["rag_refused_reaching_no_page_vision"] == sum(1 for e in rag if e.get("vision_pages_walked") == [])
    assert c["rag_refused_with_no_cached_vision_page"] == c["rag_replay_stops_on_a_cache_miss"] + c["rag_refused_reaching_no_page_vision"]
    assert c["rag_replay_vision_refused_too"] == sum(1 for e in rag if e.get("vision_outcomes") and not any(
        "value" in o for o in e["vision_outcomes"].values()))


def test_each_served_page_vision_triangle_is_read_as_the_census_says(census):
    """Review of the stage-2 branch, F4: for a refused table triangle whose page vision the replay serves from the
    committed cache, the census reads the served triangle with the reader too. 3334/2017's page 47 and 3500/2018's
    page 24 are refused as well, so those records fall to the later routes with no call. 2999/2022's page 48 (one call of
    option B, 3 October 2026) is accepted, and wrongly: see test_2999_2022_page_reading_is_the_page_shifted_one_column.

    3334/2017 was regenerated offline on 3 October 2026 (stage 2, the PC steps): its record no longer stores the
    refused triangle, so the census no longer lists it, and its figure is the models' reading (5.129). 3500/2018's later
    routes find nothing (no reserve text, no loss-ratio grid), so regenerating it would write it as no deterministic
    reading and take it out of the working sample: it is not regenerated, and is declared in redecision_pending.json."""
    served = [e for e in census["entries"] if e["block"] == "rag_triangle" and e.get("vision_pages_cached")]
    assert sorted(e["stem"] for e in served) == ["syndicate_2999_2022", "syndicate_3500_2018"]
    for e in served:
        syn, year = (int(x) for x in e["stem"].split("_")[1:])
        assert sorted(e["vision_outcomes"]) == sorted(str(p) for p in e["vision_pages_cached"]), e["stem"]
        for page in e["vision_pages_cached"]:
            tri = tc.served_vision(syn, year, page)
            assert tri is not None, (e["stem"], page, "the served entry is not committed")
            assert e["vision_outcomes"][str(page)] == tc._outcome(*tc.read(tg.compute_pyd_from_triangle, tri, year))
        if e["stem"] == "syndicate_3500_2018":
            assert "the reader refuses what it holds too" in e["replay"], e["replay"]
        else:
            assert "the reader gives 858.1 from it" in e["replay"], e["replay"]
    # 3334/2017: the served page is still refused, and the regenerated record carries no triangle of the table step's
    served_47 = tc.served_vision(3334, 2017, 47)
    assert served_47 is not None, "3334/2017's page-47 entry is not committed"
    v, why = tc.read(tg.compute_pyd_from_triangle, served_47, 2017)
    assert v is None and DIAGONAL in why, (v, why)
    for block in _record("syndicate_3334_2017")["models"].values():
        assert not block.get("_rag_triangle")
        assert block["_pyd_route"]["source"] == "model_reading" and block["_pyd_route"]["value"] == pytest.approx(5.129)


#: 2999/2022's gross table on PDF page 48 (cohorts 2013 to 2022, GBP millions; one row per development year): the page's own figures, read from its text layer on
#: 3 October 2026 and checked against the rendered page
PAGE_2999_2022 = [
    [262.7, 189.1, 226.3, 355.6, 628.5, 404.5, 321.2, 381.7, 504.3, 587.0],
    [520.6, 466.7, 543.8, 684.6, 1004.7, 752.3, 717.6, 703.3, 990.1, None],
    [595.7, 605.7, 636.3, 789.7, 1184.7, 832.2, 843.3, 879.2, None, None],
    [615.0, 608.8, 667.3, 785.3, 1191.2, 846.1, 877.5, None, None, None],
    [576.2, 654.2, 655.5, 785.3, 1207.6, 906.5, None, None, None, None],
    [591.2, 660.2, 688.8, 812.9, 1253.9, None, None, None, None, None],
    [599.5, 682.4, 693.4, 838.1, None, None, None, None, None, None],
    [602.8, 702.0, 716.1, None, None, None, None, None, None, None],
    [601.2, 709.6, None, None, None, None, None, None, None, None],
    [599.4, None, None, None, None, None, None, None, None, None],
]


def test_2999_2022_page_reading_is_the_page_shifted_one_column_and_the_record_is_not_rebuilt_from_it(census):
    """The page-vision reading of page 48 (one call, option B, 3 October 2026) disagrees with the page in every cell: it leaves out the page's first column (2013) and puts
    each later column under the year before, so its "2013" column is the page's 2014 and its "2022" column is blank. Every cell of the page's columns 2 to 10 is one column to
    the left. The blank newest column lets the reader take it for a grid that starts a year late: it reads one row up, and gives +858.1 (the 2021 cohort's first
    development, 504.3 to 990.1, lands among the mature columns) where the page gives +370.5. So the record is not rebuilt from it: it keeps its committed figure, 375.6 (from the
    table triangle the reader now refuses), and is declared in redecision_pending.json until the page's figure is registered."""
    served = tc.served_vision(2999, 2022, 48)
    assert served is not None, "page 48's entry is not committed"
    reading = served["development_rows"]
    assert len(reading) == 10 and all(len(r) == 10 for r in reading)
    shifted = 0
    for k, page_row in enumerate(PAGE_2999_2022):
        for c in range(9):
            assert reading[k][c] == page_row[c + 1], (k, c, reading[k][c], page_row[c + 1])
            shifted += page_row[c + 1] is not None
    assert shifted == 45 and all(row[9] is None for row in reading), "45 cells, all one column left; the newest column blank"
    assert [r[0] for r in reading if r[0] is not None] == [r[1] for r in PAGE_2999_2022 if r[1] is not None], "its 2013 column is the page's 2014"
    page_v, page_why = _read(_grid(PAGE_2999_2022, range(2013, 2023)), 2022)
    assert page_v == pytest.approx(370.5), page_why
    reading_v, _ = _read(served, 2022)
    assert reading_v == pytest.approx(858.1), "the reader accepts the shifted reading: when that changes, the census and the pending list are to be read again"
    entry = next(e for e in census["entries"] if e["stem"] == "syndicate_2999_2022" and e["block"] == "rag_triangle")
    assert entry["vision_outcomes"]["48"] == {"value": reading_v} and "the reader gives 858.1 from it" in entry["replay"]
    for block in _record("syndicate_2999_2022")["models"].values():
        assert block["_pyd_route"]["source"] == "rag_triangle" and block["_pyd_route"]["value"] == pytest.approx(375.6), "the record keeps its committed figure"
    pending = json.loads((ROOT / "pdf_extraction" / "audit" / "redecision_pending.json").read_text(encoding="utf-8"))
    why = next(r["why"] for r in pending["records"] if r["stem"] == "syndicate_2999_2022")
    assert "drops the page's first column" in why and "+858.1" in why and "+370.5" in why, why


def test_the_census_names_the_refused_triangles_that_reach_no_page_vision_step(census):
    """1967/2014 and 1991/2018 do not stop on a cache miss: the page finder selects no triangle page for either (1967/2014 prints no claims development table; 1991/2018's
    gross triangle, PDF page 30, matches one of the finder's patterns where two are needed), so the replay reaches no page-vision step, and each would be written as no
    deterministic reading. 2121/2019 and 3622/2023 reach a page that has no entry under the current prompt: those two stop on a cache miss."""
    rag = {e["stem"]: e for e in census["entries"] if e["block"] == "rag_triangle" and "vision_pages_walked" in e}
    assert {s: e["vision_pages_walked"] for s, e in rag.items()} == {
        "syndicate_1967_2014": [], "syndicate_1991_2018": [], "syndicate_2121_2019": [56], "syndicate_2999_2022": [48],
        "syndicate_3500_2018": [24], "syndicate_3622_2023": [36]}
    for stem in ("syndicate_1967_2014", "syndicate_1991_2018"):
        e = rag[stem]
        assert e["reaches_page_vision"] is False and e["vision_pages_cached"] == []
        assert "reaches no page-vision step" in e["replay"] and "cache miss" not in e["replay"], stem
        assert "no deterministic reading" in e["replay"], stem
    for stem in ("syndicate_2121_2019", "syndicate_3622_2023"):
        e = rag[stem]
        assert e["reaches_page_vision"] is True and e["vision_pages_cached"] == []
        assert "stops for this record on a cache miss" in e["replay"], stem
    c = census["counts"]
    assert (c["rag_refused_with_no_cached_vision_page"], c["rag_replay_stops_on_a_cache_miss"], c["rag_refused_reaching_no_page_vision"]) == (4, 2, 2)


def test_the_census_walk_is_the_page_vision_step_the_pipeline_takes(census):
    """The census walks the pipeline's own page-vision step (the call that renders a page and sends it replaced by a recorder), so what it says is reached is what the
    pipeline reaches. Held to the filings here: the walk gives each census entry's pages again. Needs the filings (a PC step)."""
    rag = [e for e in census["entries"] if e["block"] == "rag_triangle" and "vision_pages_walked" in e]
    assert len(rag) == 6
    for e in rag:
        syn, year = (int(x) for x in e["stem"].split("_")[1:])
        walk = tc.walk_page_vision(e["stem"], year)
        if walk is None:
            pytest.skip("source filing not present in this checkout")
        walked, ends = walk
        assert walked == e["vision_pages_walked"], e["stem"]
        assert e["reaches_page_vision"] is bool(walked), e["stem"]
        if not walked:
            assert ends["no_triangle_data"] is ("no deterministic reading" in e["replay"]), e["stem"]
