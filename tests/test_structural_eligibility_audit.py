"""The filing-page audit separates economic eligibility from extraction skips.

Round 62 (review of 29 September 2026, M-10, E-1, E-2 and test upgrade 5): the ledger is recomputed
here for all 95 records -- the usable cohort from the transcribed years, the decision from it, the
opening with its currency against the filing page, and the year headers against the page the ledger
cites -- and the one retained eligible record is held to the generator that writes it. The ledger
must also cover every committed stub by name: 1985/2024 became one when it was extracted again on
29 September 2026, and nothing had said the audit did not cover it.

Third cycle (30 September 2026, D2): 24 records the pipeline had written as having no deterministic
reading state in their filings that the syndicate began underwriting in the report year or the year
before. They are in the ledger with the filing's own words (`start_statements`), each held here to
the page it cites in the file the ledger hashed, and a record with no printed opening must declare why.
"""
import functools
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import test_gemini as pipeline  # noqa: E402

AUDIT = ROOT / "pdf_extraction" / "audit"


def _audit():
    return json.loads((AUDIT / "structural_eligibility_audit.json").read_text(encoding="utf-8"))


def _records():
    return {r["file"]: r for r in _audit()["records"]}


def test_all_pre_model_stubs_have_source_reviewed_decisions():
    audit = _audit()
    assert audit["counts"] == {
        "reviewed": 95,
        "structural_ineligible": 94,
        "eligible_observed_zero": 1,
        "eligibility_unresolved": 0,
    }
    assert len(audit["records"]) == 95
    assert all((r["source_page"] or r["source_file"].endswith((".html", ".htm")))
               and r["source_sha256"] for r in audit["records"])


def test_the_audit_covers_every_committed_stub_by_name():
    """The records the audit script selects -- every committed first-year stub, and every record the
    audit has transcribed (the stub it retained, the unread records it restated) -- are the ledger's and
    the transcription's, name for name: a stub the audit has not transcribed, or a transcribed record
    with no committed file, would make the two differ."""
    import audit_structural_eligibility as sel
    selected = {path.name for path, _ in sel.structural_records()}
    tr = json.loads((AUDIT / "structural_eligibility_transcription.json").read_text(encoding="utf-8"))["records"]
    assert selected == set(_records()) == set(tr) == sel.expected_names()
    assert "syndicate_1985_2024.json" in selected and len(selected) == 95
    # every committed stub is audited: the selection's stubs are all in the ledger
    stubs = {path.name for path, rec in sel.structural_records() if rec.get("first_year_syndicate") is True}
    assert len(stubs) == 94 and stubs <= set(_records())


def test_the_decision_is_recomputed_from_the_years_for_every_record():
    for name, r in _records().items():
        t = r["report_year"]
        mature = [u for u in r["underwriting_years"] if u <= t - 2]
        assert r["mature_underwriting_years"] == mature, name
        if mature:
            assert r["decision"] == "eligible_observed_zero" and r["economic_eligibility"] == "eligible", name
        else:
            assert r["decision"] == "structural_ineligible_no_mature_cohort", name
            assert r["economic_eligibility"] == "ineligible", name


#: the records whose filings print no opening gross claims outstanding: three from before the third
#: cycle, and seven of the 24 unread records the audit restated (their syndicates began in the report
#: year, and their balance sheets carry one column)
NO_OPENING = {
    "syndicate_1492_2015.json", "syndicate_1618_2021.json", "syndicate_2357_2014.json",
    "syndicate_1686_2014.json", "syndicate_1729_2014.json", "syndicate_1975_2018.json", "syndicate_2014_2014.json",
    "syndicate_3902_2017.json", "syndicate_6117_2014.json", "syndicate_6119_2014.json",
}
FIRST_YEAR_NO_OPENING = "first_year_filing_prints_no_opening"
#: the one record whose filing prints no claims outstanding balance at all (note 4: no claims were
#: notified), so it has no opening although its syndicate began a year before the report year: named
#: here with its reason, and accepted only as that
NO_BALANCE_PRINTED = {"syndicate_2357_2014.json": "filing_prints_no_claims_outstanding_balance"}


def test_every_record_has_its_opening_read_from_the_filing_with_its_currency():
    """16 of 70 records had an opening, two of them the closing balance and nine US dollars in a
    field read as GBP (M-10). Now every record states what the filing prints, or that it prints none."""
    recs = _records()
    for name, r in recs.items():
        status = r["opening_reserve_status"]
        assert status.startswith(("read from the filing: ", "not printed: ")), name
        if r["opening_gross_reserve_gbp_m"] is None:
            assert status.startswith("not printed: "), name
            continue
        assert r["opening_gross_reserve_currency"] in ("GBP", "USD", "EUR", "CAD"), name
        assert r["opening_gross_reserve_page"] and r["opening_gross_reserve_quote"], name
    assert {n for n, r in recs.items() if r["opening_gross_reserve_gbp_m"] is None} == NO_OPENING
    assert len(recs) - len(NO_OPENING) == 85       # 68 before the third cycle, and 17 of the 24 restated records
    # the two the review found: a closing balance recorded as the opening
    assert recs["syndicate_2019_2020.json"]["opening_gross_reserve_gbp_m"] == 0.0
    assert recs["syndicate_2019_2021.json"]["opening_gross_reserve_gbp_m"] == pytest.approx(278.4)
    assert recs["syndicate_2019_2021.json"]["opening_gross_reserve_currency"] == "USD"
    assert recs["syndicate_1980_2019.json"]["opening_gross_reserve_currency"] == "USD"
    # added in round 62, when its re-extraction made it a stub: note 5's 18,356 USD000 (filing page 36)
    assert recs["syndicate_1985_2024.json"]["opening_gross_reserve_gbp_m"] == pytest.approx(18.356)
    assert recs["syndicate_1985_2024.json"]["opening_gross_reserve_currency"] == "USD"
    assert recs["syndicate_1985_2024.json"]["opening_gross_reserve_page"] == 36


def test_a_missing_opening_is_a_declared_exemption_of_a_first_year_filing():
    """Third cycle of round 62 (FIX3, E2): a record whose filing prints no opening says why, and the
    reason is accepted only where it can be true. A syndicate that began in the report year has no
    claims outstanding at 1 January to print; the one record that does not fit (2357/2014, which began
    a year earlier but prints no claims balance at all) is named with its own reason. A record with a
    printed opening declares nothing."""
    recs = _records()
    assert {n for n, r in recs.items() if r["opening_gross_reserve_gbp_m"] is None} == NO_OPENING
    for name, r in recs.items():
        declared = r.get("opening_gross_reserve_exemption")
        if name not in NO_OPENING:
            assert declared is None, name
            continue
        if name in NO_BALANCE_PRINTED:
            assert declared == NO_BALANCE_PRINTED[name], name
            assert r["triangle_basis"] == "no claims development table printed", name
            assert r["inception_year"] == r["report_year"] - 1, name
        else:
            assert declared == FIRST_YEAR_NO_OPENING, name
            assert r["inception_year"] == r["report_year"], name     # a first-year filing


def test_the_ledger_is_the_transcription():
    tr = json.loads((AUDIT / "structural_eligibility_transcription.json").read_text(encoding="utf-8"))["records"]
    for name, r in _records().items():
        t = tr[name]
        assert r["opening_gross_reserve_gbp_m"] == t["opening_m"], name
        assert r["opening_gross_reserve_currency"] == t["opening_currency"], name
        assert r["triangle_basis"] == t["basis"], name
        page = t["triangle_page_index"] if t["triangle_page_index"] is not None else t["years_page_index"]
        assert r["source_page"] == page + 1, name
        assert r.get("opening_gross_reserve_exemption") == t.get("opening_exemption"), name
        assert [(s["page"], s["page_printed"], s["quote"]) for s in r.get("start_statements") or []] == [
            (s["page_index"] + 1, s["page_printed"], s["quote"]) for s in t.get("start_statements") or []], name


@functools.lru_cache(maxsize=None)
def _texts_of(source_file):
    import finalize_structural_eligibility_audit as fin
    return tuple(fin.page_texts(ROOT / source_file))


def _page_texts(r):
    return list(_texts_of(r["source_file"]))


def _present():
    present = [r for r in _records().values() if (ROOT / r["source_file"]).exists()]
    if not present:
        pytest.skip("source filings not present in this checkout")
    return present


#: a currency marker, by the currency it names ("C$" is removed from the dollar count below)
CURRENCY_MARKERS = {
    "GBP": re.compile(r"£|\bGBP\b|\bsterling\b|\bpounds?\b", re.I),
    "USD": re.compile(r"(?<![A-Za-z])(US)?\$|\bUSD\b|\bUS dollars?\b|\bdollars?\b", re.I),
    "EUR": re.compile(r"€|\bEUR\b|\beuros?\b", re.I),
    "CAD": re.compile(r"\bC\$|\bCAD\b|\bCanadian dollars?\b", re.I),
}
#: where a filing declares the currency its accounts are in
CURRENCY_DECLARATION = re.compile(r"(presentation(al)? currency|functional currency|reporting currency|"
                                  r"presented in|are stated in|expressed in|reported in)[^.]{0,120}", re.I)


def _currency_markers(text):
    flat = " ".join(text.split())
    found = {c: len(p.findall(flat)) for c, p in CURRENCY_MARKERS.items()}
    found["USD"] = max(0, found["USD"] - found["CAD"])
    return {c: n for c, n in found.items() if n}


def _declared_currencies(texts):
    out = set()
    for text in texts:
        for m in CURRENCY_DECLARATION.finditer(" ".join(text.split())):
            out |= {c for c, p in CURRENCY_MARKERS.items() if p.search(m.group(0))}
    return out


def test_each_opening_currency_is_the_one_its_filing_prints():
    """Verification review of round 62, test gap U5-4: the currency was checked only for membership
    of {GBP, USD, EUR, CAD} and pinned for three records, so a wrong currency on any other record
    passed. Now the opening's currency must be the one its page prints most often; a page that prints
    no currency marker defers to the currency the filing declares its accounts in; and a page that
    prints another currency is accepted only where the transcription records the conflict and the
    declaration agrees with the ledger (5183/2023: note 4 headed GBP'000 in USD accounts; 6050/2015: the
    page also prints note 8's directors' remuneration in pounds). Measured on the committed ledger: 82 of
    its 85 openings by their page, 1100/2024 by its declaration (Euro accounts), and 5183/2023 and
    6050/2015 by their recorded conflicts."""
    how = {}
    for r in _present():
        if r["opening_gross_reserve_gbp_m"] is None:
            continue
        cur, texts = r["opening_gross_reserve_currency"], _page_texts(r)
        page = _currency_markers(texts[r["opening_gross_reserve_page"] - 1])
        if page and max(page, key=page.get) == cur:
            how[r["file"]] = "page"
        elif not page:
            assert cur in _declared_currencies(texts), (r["file"], cur, "no marker on the page")
            how[r["file"]] = "declaration"
        else:
            assert "currency conflict" in str(r.get("transcription_notes")).lower(), (r["file"], cur, page)
            assert cur in _declared_currencies(texts), (r["file"], cur, page)
            how[r["file"]] = "recorded conflict"
    if len(how) == 85:      # every filing present: the measured split holds
        assert sorted(k for k, v in how.items() if v != "page") == [
            "syndicate_1100_2024.json", "syndicate_5183_2023.json", "syndicate_6050_2015.json"], how


#: a development-row label of a claims development table. "At end of reporting period" (1796/2021) and
#: "1 year" (3902/2017, whose table has one column at one year of development) joined the list in the
#: third cycle; with both, the measurement in the test below is unchanged (70 of 71 then, and the same
#: 16 of the old ledger's pages).
DEVELOPMENT_LABEL = re.compile(
    r"at (the )?end of (the )?(first |pure )?(underwriting|reporting|accident|financial)? ?year|"
    r"at (the )?end of (the )?reporting period|\b1 year\b|"
    r"\b(one|two|three|1|2|3) years? later\b|\bafter (one|two|1|2) years?\b|\b12 months\b|"
    r"development (year|period)", re.I)


def _years_as_a_header(flat, years, span=160):
    """The years printed as a header row: in ascending or descending order, each within `span`
    characters of the one before."""
    for order in (sorted(years), sorted(years, reverse=True)):
        ys = [str(y) for y in order]
        for m in re.finditer(re.escape(ys[0]), flat):
            pos, ok = m.end(), True
            for y in ys[1:]:
                n = flat.find(y, pos, pos + span)
                if n < 0:
                    ok = False
                    break
                pos = n + len(y)
            if ok:
                return True
    return False


def test_the_cited_page_is_the_page_that_holds_the_triangle():
    """Verification review of round 62, test gap U5-5: source_page passed if every underwriting year
    occurred anywhere on the page, which the old ledger's pages -- the ones R7 found were not the
    triangle page -- did for 67 of 68 records. The cited page must now print a development-row label
    and the years as a header row. Measured: every record of the committed ledger with a triangle page
    passes, and of the old ledger's (11b1bc36) pages only the 16 it shares with this one do. A record
    whose filing prints no triangle (2357/2014) cites the page that prints its years instead."""
    tr = json.loads((AUDIT / "structural_eligibility_transcription.json").read_text(encoding="utf-8"))["records"]
    checked = 0
    for r in _present():
        if tr[r["file"]]["triangle_page_index"] is None:
            continue
        flat = " ".join(_page_texts(r)[r["source_page"] - 1].split())
        assert DEVELOPMENT_LABEL.search(flat), (r["file"], r["source_page"], "no development-row label")
        assert _years_as_a_header(flat, r["underwriting_years"]), (r["file"], r["source_page"], "no year header")
        checked += 1
    assert checked >= 1


def test_each_cited_page_prints_what_the_ledger_says():
    """The year headers are on source_page, the opening is on its page, and the source is the file
    the ledger hashed. Needs the filings, which are not committed."""
    import hashlib
    recs = _records()
    present = [r for r in recs.values() if (ROOT / r["source_file"]).exists()]
    if not present:
        pytest.skip("source filings not present in this checkout")
    for r in present:
        assert hashlib.sha256((ROOT / r["source_file"]).read_bytes()).hexdigest() == r["source_sha256"], r["file"]
        texts = _page_texts(r)
        page = " ".join(texts[r["source_page"] - 1].split())
        assert all(str(y) in page for y in r["underwriting_years"]), r["file"]
        printed = r["opening_gross_reserve_printed"]
        if r["opening_gross_reserve_page"] and printed not in (None, "-", "0", "nil"):
            opening_page = " ".join(texts[r["opening_gross_reserve_page"] - 1].split())
            assert str(printed).strip("()").strip() in opening_page, r["file"]


def test_mature_nil_cohort_with_positive_reserve_is_an_observed_zero():
    record = _records()["syndicate_1840_2022.json"]
    assert record["mature_underwriting_years"] == [2020]
    assert record["opening_gross_reserve_gbp_m"] == pytest.approx(0.279)
    assert record["opening_gross_reserve_currency"] == "GBP"
    assert record["economic_eligibility"] == "eligible"
    assert record["decision"] == "eligible_observed_zero"
    assert record["nil_vs_missing"] == "printed_dashes_are_reported_nil_values"
    assert record["mature_cohort_calculation"].startswith("UW2020: two-years-after 0 minus one-year-after 0")
    assert "= 0.000 GBP m" in record["mature_cohort_calculation"]

    extracted = pipeline._reviewed_eligible_record(
        pipeline.REPORTS_DIR / "syndicate_1840_2022.pdf", 1840, 2022)
    block = extracted["models"]["source-page-audit"]
    assert block["prior_year_development_gbp_m"] == 0.0
    assert block["prior_year_development_pct"] == 0.0
    assert block["opening_reserves_gbp_m"] > 0
    assert block["_rag_triangle"]["development_rows"][1][0] == 0.0
    assert block["_rag_triangle"]["development_rows"][2][0] == 0.0


def _separator_agnostic(obj):
    """The record with every `source_file` path written with forward slashes: the generator writes
    str(Path), which is `syndicate_reports\\pdfs\\...` on Windows and `syndicate_reports/pdfs/...`
    elsewhere."""
    if isinstance(obj, dict):
        return {k: (v.replace("\\", "/") if k == "source_file" and isinstance(v, str) else _separator_agnostic(v))
                for k, v in obj.items()}
    if isinstance(obj, list):
        return [_separator_agnostic(v) for v in obj]
    return obj


def test_the_retained_record_is_its_generators_output_and_claims_no_model_work():
    """E-1: the committed 1840/2022 record differed from its generator and said "[RAG OVERRIDE: Model
    said PYD=0.000m ...]" with model confidences of 1.0 and passed validation, though no model ran.
    The comparison is separator-agnostic (verification review of round 62): the committed record was
    written on Windows, and the generator's output is compared as a Windows and as a POSIX machine
    would produce it."""
    from pathlib import PurePosixPath, PureWindowsPath
    committed = json.loads((ROOT / "pdf_extraction" / "syndicate_1840_2022.json").read_text(encoding="utf-8"))
    committed.pop("extraction_timestamp")
    for flavour in (PureWindowsPath, PurePosixPath):
        generated = json.loads(json.dumps(pipeline.sanitize_json_ascii(pipeline._reviewed_eligible_record(
            flavour("syndicate_reports", "pdfs", "syndicate_1840_2022.pdf"), 1840, 2022))))
        generated.pop("extraction_timestamp")
        assert _separator_agnostic(committed) == _separator_agnostic(generated), flavour.__name__
    block = committed["models"]["source-page-audit"]
    assert committed["models_run"] is False and committed["validation"]["models_run"] is False
    assert "passed" not in committed["validation"]
    assert not [k for k in block if k.endswith("_confidence")]
    assert "RAG OVERRIDE" not in block["data_quality_notes"] and "Model said" not in block["data_quality_notes"]
    assert block["direction"] == "flat"


# ---------------------------------------------------------------------------------------------------------------
# Third cycle of round 62 (30 September 2026, D2): the unread records the audit restated as first-year stubs
# ---------------------------------------------------------------------------------------------------------------

#: what a start statement says: that the syndicate began, was established or approved to start, or is in
#: its first or second year
STARTED = re.compile(r"commenc|began|establish|incept|first (year|underwriting|financial)|second year|"
                     r"approved by lloyd|start underwriting|launched", re.I)


def _restated():
    import finalize_structural_eligibility_audit as fin
    return {n: r for n, r in _records().items() if r["extraction_status"] == fin.UNREAD_RECORD_CONFIRMED}


def test_the_unread_records_the_audit_restated_state_when_the_syndicate_began():
    """24 records were written as having no deterministic reading; their filings state that the syndicate
    began in the report year (18) or the year before (6), so no underwriting year up to t-2 can exist.
    Each is in the ledger with the filing's own words, and nothing else in the ledger carries them."""
    recs, restated = _records(), _restated()
    assert len(restated) == 24
    assert sum(r["inception_year"] == r["report_year"] for r in restated.values()) == 18
    assert sum(r["inception_year"] == r["report_year"] - 1 for r in restated.values()) == 6
    for name, r in restated.items():
        t = r["report_year"]
        assert r["decision"] == "structural_ineligible_no_mature_cohort" and r["mature_underwriting_years"] == [], name
        assert r["underwriting_years"] in ([t], [t - 1, t]), name
        assert r["start_statements"], name
        for s in r["start_statements"]:
            assert s["page"] >= 1 and s["page_printed"] and s["quote"].strip(), (name, s)
        # at least one statement says that the syndicate began (the others may support it: a reporting period
        # that opens after 1 January, no comparative year)
        assert any(STARTED.search(s["quote"]) for s in r["start_statements"]), name
        # a statement about a start in the year before the report says so on the page the record cites
        assert any(str(r["inception_year"]) in s["quote"] or r["inception_year"] == t for s in r["start_statements"]), name
    assert all("start_statements" not in r for n, r in recs.items() if n not in restated)


def test_the_two_careful_reads_are_first_year_filings_that_print_no_older_cohort():
    """2014/2014 has 'origins in Special Purpose Syndicate 6110' and 3902/2017 replaced 'the Incidental
    Syndicate'; either could have printed the older syndicate's cohorts. The ledger says what each
    filing does say, and the note explains why neither prints one."""
    restated = _restated()
    for name, phrase, years in (("syndicate_2014_2014.json", "Special Purpose Syndicate 6110", [2014]),
                                ("syndicate_3902_2017.json", "Incidental Syndicate", [2017])):
        r = restated[name]
        assert r["underwriting_years"] == years, name
        assert any(phrase in s["quote"] for s in r["start_statements"]), name
        assert r["review_note"], name
        assert phrase.split()[-1] in r["review_note"] and "Read with care" in r["review_note"], name


def test_each_restated_record_prints_what_the_ledger_quotes():
    """Every start statement, the opening line and the table heading of the 24 is printed on the page it
    cites, in the file whose hash the ledger holds (verbatim, white space aside; ' ... ' marks words left
    out). Needs the filings, which are not committed."""
    import hashlib
    import finalize_structural_eligibility_audit as fin
    checked = 0
    for r in _present():
        if r["extraction_status"] != fin.UNREAD_RECORD_CONFIRMED:
            continue
        assert hashlib.sha256((ROOT / r["source_file"]).read_bytes()).hexdigest() == r["source_sha256"], r["file"]
        texts = _page_texts(r)
        for s in r["start_statements"]:
            assert fin.quote_on_page(s["quote"], texts[s["page"] - 1]), (r["file"], s["page"], s["quote"])
        assert fin.quote_on_page(r["opening_gross_reserve_quote"], texts[r["opening_gross_reserve_page"] - 1]), r["file"]
        if r["triangle_basis"] != "no claims development table printed":
            assert fin.quote_on_page(r["triangle_basis_quote"], texts[r["source_page"] - 1]), r["file"]
        checked += 1
    if not checked:
        pytest.skip("source filings not present in this checkout")


def _year_run(flat, length=3, span=40):
    """Consecutive calendar years, ascending or descending, each within `span` characters of the one before:
    the header of a claims development table that prints `length` cohorts."""
    years = [(m.start(), int(m.group())) for m in re.finditer(r"\b(?:19|20)\d\d\b", flat)]
    for i in range(len(years) - length + 1):
        window = years[i:i + length]
        ys = [y for _, y in window]
        near = all(window[k + 1][0] - window[k][0] <= span for k in range(length - 1))
        if near and (ys == list(range(ys[0], ys[0] + length)) or ys == list(range(ys[0], ys[0] - length, -1))):
            return ys
    return None


def _development_header_run(text):
    """Three or more consecutive years in a header on a page that prints a development-row label: what a
    claims development table with an older cohort looks like."""
    flat = " ".join(text.split())
    return _year_run(flat) if DEVELOPMENT_LABEL.search(flat) else None


def test_no_restated_filing_prints_a_cohort_older_than_the_ledger_says():
    """The claim behind the decision, tested on every page of the 24 filings: none prints three or more
    consecutive years in a header on a page with a development-row label, so no development table holds
    a cohort the ledger does not list (six of the 24 print two cohorts, the syndicate's two years). A page
    that lists the directors' shareholdings for 2015, 2016 and 2017 (3902/2017) is no such table. The
    control is a filing that does print them: 1840/2022's table has UW2020-2022."""
    import finalize_structural_eligibility_audit as fin
    control = ROOT / "syndicate_reports" / "pdfs" / "syndicate_1840_2022.pdf"
    present = _present()
    assert control.exists(), "the control filing is missing"
    found = [_development_header_run(t) for t in fin.page_texts(control)]
    assert any(run and sorted(run) == [2020, 2021, 2022] for run in found), "the check cannot find a three-cohort header"
    for r in present:
        if r["extraction_status"] != fin.UNREAD_RECORD_CONFIRMED:
            continue
        for page, text in enumerate(_page_texts(r), 1):
            run = _development_header_run(text)
            assert run is None, (r["file"], page, run)
