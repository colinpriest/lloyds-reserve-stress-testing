"""Write the reviewed economic-eligibility audit for every pre-model stub, the one it retained and the
unread records it restated.

95 records since the third cycle of round 62 (30 September 2026): the 70 first-year stubs committed
before it, 1985/2024 among them since its re-extraction of 29 September 2026 found UW2023-2024 only;
1840/2022, retained as an observed zero; and 24 records the pipeline had written as having no
deterministic reading (its parsers found no figure and the models were not run) whose filings state
that the syndicate began underwriting in the report year (18) or the year before (6), so that no
underwriting year up to t-2 can exist (the author's decision D2, 30 September 2026). Those 24 are read
from their filing pages like the rest and restated as first-year stubs by
``restate_record_status.py --audited-unread``; their ledger records carry ``start_statements``, the
filing's own words on when the syndicate began, each checked to be printed on the page it cites.

The underwriting-year lists below are transcribed from the filing pages captured by
``audit_structural_eligibility.py``.  They are deliberately separate from the old
``first_year_syndicate`` flag: the flag chooses the records to review, never their
economic eligibility.  Re-running this script verifies the inventory, source hashes,
page evidence and the mature-cohort arithmetic before writing JSON and CSV ledgers.

Round 62 (review of 29 September 2026, M-10): the ledger's per-record facts are read from
``structural_eligibility_transcription.json``, transcribed from the filing pages, and this
script checks each against the page it cites before writing it. ``source_page`` is the page
that prints the claims development table's year headers (it had been whichever page an
excerpt scorer preferred, often the directors' report); ``triangle_basis`` is the basis as
printed (it had been one constant string); and every record carries its opening gross claims
outstanding at 1 January of the report year with its currency, unit, page and printed line (16
of 70 had one, two of them the closing balance and nine in US dollars in a field read as GBP).
The value stays in ``opening_gross_reserve_gbp_m`` by the project's convention that a ``_gbp_m``
field holds millions of the record's own currency, which ``opening_gross_reserve_currency`` names.
"""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUDIT_DIR = ROOT / "pdf_extraction" / "audit"
CANDIDATES = AUDIT_DIR / "structural_eligibility_candidates.json"
TRANSCRIPTION = AUDIT_DIR / "structural_eligibility_transcription.json"
OUT_JSON = AUDIT_DIR / "structural_eligibility_audit.json"
OUT_CSV = AUDIT_DIR / "structural_eligibility_audit.csv"
HEADING_WORDS = ("underwriting year", "year of account", "pure underwriting", "estimate of")
#: the ledger's extraction_status of an unread record the audit restated as a first-year stub
UNREAD_RECORD_CONFIRMED = "unread_record_confirmed_structural_by_source_page_audit"
#: the declared reason a record has no opening: the syndicate began in the report year, so none exists to print
FIRST_YEAR_NO_OPENING = "first_year_filing_prints_no_opening"

# Filing-page transcription.  Template columns that contain only dashes are not
# underwriting cohorts; 2358/2022 is the one filing that prints legacy year headings
# beside an all-dash block, and its note below records that distinction explicitly.
REVIEWED_UW_YEARS = {
    "syndicate_1100_2024.json": [2024],
    "syndicate_1322_2023.json": [2023],
    "syndicate_1322_2024.json": [2023, 2024],
    "syndicate_1347_2023.json": [2023],
    "syndicate_1416_2022.json": [2021, 2022],
    "syndicate_1492_2015.json": [2015],
    "syndicate_1492_2016.json": [2015, 2016],
    "syndicate_1609_2021.json": [2021],
    "syndicate_1609_2022.json": [2021, 2022],
    "syndicate_1618_2021.json": [2021],
    "syndicate_1618_2022.json": [2021, 2022],
    "syndicate_1686_2014.json": [2014],
    "syndicate_1686_2015.json": [2014, 2015],
    "syndicate_1699_2022.json": [2022],
    "syndicate_1699_2023.json": [2022, 2023],
    "syndicate_1729_2014.json": [2014],
    "syndicate_1796_2021.json": [2021],
    "syndicate_1796_2022.json": [2021, 2022],
    "syndicate_1840_2020.json": [2020],
    "syndicate_1840_2021.json": [2020, 2021],
    "syndicate_1840_2022.json": [2020, 2021, 2022],
    "syndicate_1856_2017.json": [2016, 2017],
    "syndicate_1884_2015.json": [2015],
    "syndicate_1884_2016.json": [2015, 2016],
    "syndicate_1892_2019.json": [2019],
    "syndicate_1892_2020.json": [2019, 2020],
    "syndicate_1902_2022.json": [2022],
    "syndicate_1902_2023.json": [2022, 2023],
    "syndicate_1922_2024.json": [2024],
    "syndicate_1925_2024.json": [2024],
    "syndicate_1947_2018.json": [2018],
    "syndicate_1971_2019.json": [2019],
    "syndicate_1971_2020.json": [2019, 2020],
    "syndicate_1975_2018.json": [2018],
    "syndicate_1975_2019.json": [2018, 2019],
    "syndicate_1980_2019.json": [2018, 2019],
    "syndicate_1985_2023.json": [2023],
    "syndicate_1985_2024.json": [2023, 2024],
    "syndicate_1988_2022.json": [2021, 2022],
    "syndicate_1991_2014.json": [2013, 2014],
    "syndicate_2014_2014.json": [2014],
    "syndicate_2019_2020.json": [2020],
    "syndicate_2019_2021.json": [2020, 2021],
    "syndicate_2024_2024.json": [2024],
    "syndicate_2288_2020.json": [2020],
    "syndicate_2288_2021.json": [2020, 2021],
    "syndicate_2357_2014.json": [2013, 2014],
    "syndicate_2358_2022.json": [2022],
    "syndicate_2358_2023.json": [2022, 2023],
    "syndicate_2689_2017.json": [2017],
    "syndicate_2689_2018.json": [2017, 2018],
    "syndicate_2786_2016.json": [2016],
    "syndicate_2786_2017.json": [2016, 2017],
    "syndicate_2880_2022.json": [2022],
    "syndicate_2880_2023.json": [2022, 2023],
    "syndicate_2988_2017.json": [2017],
    "syndicate_2988_2018.json": [2017, 2018],
    "syndicate_3268_2018.json": [2018],
    "syndicate_3268_2019.json": [2018, 2019],
    "syndicate_3456_2023.json": [2022, 2023],
    "syndicate_3902_2017.json": [2017],
    "syndicate_4321_2022.json": [2022],
    "syndicate_4321_2023.json": [2022, 2023],
    "syndicate_4747_2021.json": [2020, 2021],
    "syndicate_5183_2023.json": [2022, 2023],
    "syndicate_5623_2018.json": [2018],
    "syndicate_5623_2019.json": [2018, 2019],
    "syndicate_5886_2017.json": [2017],
    "syndicate_5886_2018.json": [2017, 2018],
    "syndicate_6050_2015.json": [2015],
    "syndicate_6050_2016.json": [2015, 2016],
    "syndicate_6113_2014.json": [2013, 2014],
    "syndicate_6115_2014.json": [2013, 2014],
    "syndicate_6117_2014.json": [2014],
    "syndicate_6119_2014.json": [2014],
    "syndicate_6119_2015.json": [2014, 2015],
    "syndicate_6120_2015.json": [2015],
    "syndicate_6121_2015.json": [2015],
    "syndicate_6121_2016.json": [2015, 2016],
    "syndicate_6123_2015.json": [2015],
    "syndicate_6123_2016.json": [2015, 2016],
    "syndicate_6124_2015.json": [2015],
    "syndicate_6125_2016.json": [2016],
    "syndicate_6126_2016.json": [2016],
    "syndicate_6126_2017.json": [2016, 2017],
    "syndicate_6129_2016.json": [2016],
    "syndicate_6129_2017.json": [2016, 2017],
    "syndicate_6130_2016.json": [2016],
    "syndicate_6131_2018.json": [2018],
    "syndicate_6131_2019.json": [2018, 2019],
    "syndicate_6132_2018.json": [2018],
    "syndicate_6132_2019.json": [2018, 2019],
    "syndicate_6133_2018.json": [2018],
    "syndicate_6134_2018.json": [2018],
    "syndicate_6136_2023.json": [2023],
}


def source_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def page_texts(source: Path) -> list[str]:
    """The filing's page texts: the converted PDF for an HTML filing, and the committed OCR page
    cache for a page that has no text layer."""
    import fitz

    pdf = source if source.suffix.lower() == ".pdf" else (
        ROOT / "pdf_extraction" / "html_converted" / f"{source.stem}.pdf")
    with fitz.open(pdf) as doc:
        texts = [page.get_text() for page in doc]
    cache = ROOT / "pdf_extraction" / "ocr_page_cache" / f"{source.stem}.json"
    if cache.exists():
        cached = {int(e["page"]) - 1: e.get("text", "")
                  for e in json.loads(cache.read_text(encoding="utf-8"))}
        texts = [t if len(t.strip()) > 50 else cached.get(i, t) for i, t in enumerate(texts)]
    return texts


def _flat(text: str) -> str:
    return " ".join(text.split())


def quote_on_page(quote: str, page_text: str) -> bool:
    """Whether `quote` is printed on the page: white space collapsed, a ' ... ' standing for words left
    out, every fragment present and in order. A start statement, the opening line and the table heading
    of an unread record the audit restated are held to it; nothing else in the ledger is."""
    flat, at = _flat(page_text), 0
    for fragment in quote.split(" ... "):
        fragment = _flat(fragment)
        found = flat.find(fragment, at) if fragment else -1
        if found < 0:
            return False
        at = found + len(fragment)
    return True


def page_evidence(text: str) -> str:
    """The page's text from the table's heading on, so the stored excerpt shows the year headers."""
    flat = _flat(text)
    starts = [flat.lower().find(w) for w in HEADING_WORDS if flat.lower().find(w) >= 0]
    start = max(0, min(starts) - 200) if starts else 0
    return flat[start:start + 3500]


def transcribed_facts(name: str, tr: dict, years: list[int], texts: list[str]) -> dict:
    """The transcription's facts for one filing, each checked against the page it cites."""
    if tr.get("triangle_page_index") is not None:
        page, printed = tr["triangle_page_index"], tr.get("triangle_page_printed")
        if sorted(tr.get("header_years") or []) != sorted(years):
            raise ValueError(f"{name}: transcribed header years {tr.get('header_years')} are not {years}")
    else:
        # no claims development table is printed: the page that shows the years the syndicate traded
        page, printed = tr["years_page_index"], tr.get("years_page_printed")
    flat = _flat(texts[page])
    missing = [y for y in years if str(y) not in flat]
    if missing:
        raise ValueError(f"{name}: page {page + 1} does not print the year(s) {missing}")
    value = tr.get("opening_printed")
    if tr.get("opening_page_index") is not None and value not in (None, "-", "0", "nil"):
        if str(value).strip("()").strip() not in _flat(texts[tr["opening_page_index"]]):
            raise ValueError(f"{name}: page {tr['opening_page_index'] + 1} does not print {value!r}")
    opening_page = tr.get("opening_page_index")
    exemption = tr.get("opening_exemption")
    if tr.get("opening_m") is None and not exemption:
        raise ValueError(f"{name}: no opening is printed and no exemption is declared")
    if tr.get("opening_m") is not None and exemption:
        raise ValueError(f"{name}: an opening is printed and an exemption is declared")
    starts = None
    if tr.get("start_statements"):
        # an unread record the audit restated: what the filing says about when the syndicate began, the
        # opening line and the table heading are each checked to be printed on the page they cite
        starts = []
        for s in tr["start_statements"]:
            if not quote_on_page(s["quote"], texts[s["page_index"]]):
                raise ValueError(f"{name}: page {s['page_index'] + 1} does not print the start statement {s['quote']!r}")
            starts.append({"page": s["page_index"] + 1, "page_printed": s["page_printed"], "quote": s["quote"]})
        if opening_page is not None and not quote_on_page(tr["opening_quote"], texts[opening_page]):
            raise ValueError(f"{name}: page {opening_page + 1} does not print the opening line {tr['opening_quote']!r}")
        if tr.get("triangle_page_index") is not None and not quote_on_page(tr["basis_quote"], texts[tr["triangle_page_index"]]):
            raise ValueError(f"{name}: page {tr['triangle_page_index'] + 1} does not print the table heading")
    return {
        "start_statements": starts,
        "opening_gross_reserve_exemption": exemption,
        "source_page": page + 1,
        "source_page_printed": printed,
        "source_evidence": page_evidence(texts[page]),
        "triangle_basis": tr["basis"],
        "triangle_basis_quote": tr.get("basis_quote"),
        "opening_gross_reserve_gbp_m": tr.get("opening_m"),
        "opening_gross_reserve_currency": tr.get("opening_currency"),
        "opening_gross_reserve_printed": value,
        "opening_gross_reserve_unit": tr.get("opening_unit"),
        "opening_gross_reserve_page": None if opening_page is None else opening_page + 1,
        "opening_gross_reserve_page_printed": tr.get("opening_page_printed"),
        "opening_gross_reserve_quote": tr.get("opening_quote"),
        "opening_reserve_status": (("read from the filing: " if tr.get("opening_m") is not None
                                    else "not printed: ") + str(tr.get("opening_source") or "")),
        "transcription_notes": tr.get("notes"),
    }


def build_record(candidate: dict, tr: dict) -> dict:
    name = candidate["file"]
    year = int(candidate["year"])
    years = REVIEWED_UW_YEARS[name]
    mature = [uw for uw in years if uw <= year - 2]
    source = ROOT / candidate["source_file"]
    facts = transcribed_facts(name, tr, years, page_texts(source))

    eligible_zero = name == "syndicate_1840_2022.json"
    if eligible_zero:
        decision = "eligible_observed_zero"
        eligibility = "eligible"
        nil_status = "printed_dashes_are_reported_nil_values"
        # the report year's movement: two years after less one year after (both printed nil)
        calculation = "UW2020: two-years-after 0 minus one-year-after 0 = 0.000 GBP m"
        if facts["opening_gross_reserve_gbp_m"] != 0.279:
            raise ValueError(f"{name}: the audited opening 0.279 is not the transcribed one")
        extraction_status = "corrected_from_pre_model_stub_by_source_page_audit"
    else:
        if mature:
            raise ValueError(f"{name}: reviewed years unexpectedly contain a mature cohort {mature}")
        decision = "structural_ineligible_no_mature_cohort"
        eligibility = "ineligible"
        nil_status = "not_applicable_no_mature_cohort"
        calculation = f"no underwriting year u <= {year - 2}; reviewed years are {years}"
        extraction_status = "pre_model_stub_confirmed_structural_by_source_page_audit"
        if facts["start_statements"]:
            # an unread record: the filing says when the syndicate began, and no year before t-1 is printed
            if min(years) not in (year, year - 1) or max(years) != year:
                raise ValueError(f"{name}: a syndicate that began in {min(years)} is not a first-year filing of {year}")
            extraction_status = UNREAD_RECORD_CONFIRMED

    if facts["opening_gross_reserve_exemption"] == FIRST_YEAR_NO_OPENING and min(years) != year:
        raise ValueError(f"{name}: the first-year exemption is declared for a syndicate that began in {min(years)}, not {year}")

    note = None
    if name == "syndicate_2358_2022.json":
        note = ("The filing's template prints legacy year headings with dashes in every old column; "
                "only UW2022 contains a cohort, and gross claims outstanding at 1 January 2022 is nil.")
    if name == "syndicate_2357_2014.json":
        note = ("The filing prints no claims development table and no claims outstanding balance: note 4 "
                "says no claims were notified. It trades in 2013 and 2014 only (page 5), so no cohort up "
                "to 2012 exists.")
    if name == "syndicate_2014_2014.json":
        note = ("Read with care: the filing says the syndicate has 'its origins in Special Purpose Syndicate 6110', and also "
                "that it 'commenced underwriting at Lloyd's on 1 January 2014' and that 2014 is 'Syndicate 2014's first "
                "underwriting year'. It prints no older cohort: no comparative column, no claims development table, and "
                "members' balances that open at nil.")
    if name == "syndicate_3902_2017.json":
        note = ("Read with care: the filing says the syndicate began underwriting on the 2017 YOA, 'replacing the Incidental "
                "Syndicate that previously operated within Syndicate 4020'. Its loss development table holds a single 2017 "
                "column and reconciles to the balance sheet's gross claims liabilities (30,259), so no older cohort is in "
                "this syndicate's accounts.")

    record = {
        "file": name,
        "syndicate": int(candidate["syndicate"]),
        "report_year": year,
        "source_file": candidate["source_file"],
        "source_sha256": source_hash(source),
        "source_page": facts["source_page"],
        "source_page_printed": facts["source_page_printed"],
        "source_evidence": facts["source_evidence"],
        "inception_year": min(years),
        "underwriting_years": years,
        **({"start_statements": facts["start_statements"]} if facts["start_statements"] else {}),
        "triangle_basis": facts["triangle_basis"],
        "triangle_basis_quote": facts["triangle_basis_quote"],
        "mature_underwriting_years": mature,
        "nil_vs_missing": nil_status,
        "mature_cohort_calculation": calculation,
        "opening_gross_reserve_gbp_m": facts["opening_gross_reserve_gbp_m"],
        "opening_gross_reserve_currency": facts["opening_gross_reserve_currency"],
        "opening_gross_reserve_printed": facts["opening_gross_reserve_printed"],
        "opening_gross_reserve_unit": facts["opening_gross_reserve_unit"],
        "opening_gross_reserve_page": facts["opening_gross_reserve_page"],
        "opening_gross_reserve_page_printed": facts["opening_gross_reserve_page_printed"],
        "opening_gross_reserve_quote": facts["opening_gross_reserve_quote"],
        "opening_reserve_status": facts["opening_reserve_status"],
        **({"opening_gross_reserve_exemption": facts["opening_gross_reserve_exemption"]}
           if facts["opening_gross_reserve_exemption"] else {}),
        "economic_eligibility": eligibility,
        "decision": decision,
        "extraction_status": extraction_status,
        "review_note": note,
        "transcription_notes": facts["transcription_notes"],
    }
    if eligible_zero:
        record["audited_source_fields"] = {
            "opening_reserves_gbp_m": 0.279,
            "opening_reserves_page": 38,
            "prior_year_development_gbp_m": 0.0,
            "prior_year_development_pct": 0.0,
            "prior_year_movement_page": 39,
            "gross_premiums_written_gbp_m": 3.676,
            "gross_premium_page": 33,
            "gross_premium_mix": [
                {"line_of_business": "Fire and other damage to property",
                 "amount_gbp_m": 3.375, "percentage_of_total": 91.8},
                {"line_of_business": "Third party liability",
                 "amount_gbp_m": 0.301, "percentage_of_total": 8.2},
                {"line_of_business": "Reinsurance",
                 "amount_gbp_m": 0.0, "percentage_of_total": 0.0},
            ],
            "triangle": {
                "type": "gross", "currency": "GBP", "units": "thousands",
                "source_page": 39, "underwriting_years": [2020, 2021, 2022],
                "development_rows": [[18.0, 2364.0, 190.0],
                                     [0.0, 3407.0, None], [0.0, None, None]],
                "row_labels": ["At end of underwriting year", "One year after", "Two years after"],
            },
        }
    return record


def main() -> None:
    candidates = json.loads(CANDIDATES.read_text(encoding="utf-8"))["records"]
    transcription = json.loads(TRANSCRIPTION.read_text(encoding="utf-8"))["records"]
    names = {record["file"] for record in candidates}
    if len(candidates) != len(REVIEWED_UW_YEARS) or names != set(REVIEWED_UW_YEARS) or set(transcription) != names:
        missing = sorted((names ^ set(REVIEWED_UW_YEARS)) | (names ^ set(transcription)))
        raise SystemExit(f"review inventory mismatch: n={len(candidates)}, symmetric_difference={missing}")
    records = [build_record(record, transcription[record["file"]]) for record in candidates]
    counts = {
        "reviewed": len(records),
        "structural_ineligible": sum(r["economic_eligibility"] == "ineligible" for r in records),
        "eligible_observed_zero": sum(r["decision"] == "eligible_observed_zero" for r in records),
        "eligibility_unresolved": sum(r["economic_eligibility"] == "unresolved" for r in records),
    }
    OUT_JSON.write_text(json.dumps({
        "definition": ("Filing-page audit of every record formerly classified from the extraction skip flag, and of the "
                       "unread records whose filings state that the syndicate began underwriting in the report year or "
                       "the year before. Economic eligibility is decided independently of extraction success."),
        "mature_cohort_rule": "u <= report_year - 2",
        "counts": counts,
        "records": records,
    }, indent=2) + "\n", encoding="utf-8")
    fields = list(dict.fromkeys(key for record in records for key in record))
    with OUT_CSV.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for record in records:
            row = {**record,
                   "underwriting_years": ";".join(map(str, record["underwriting_years"])),
                   "mature_underwriting_years": ";".join(map(str, record["mature_underwriting_years"]))}
            if row.get("audited_source_fields") is not None:
                row["audited_source_fields"] = json.dumps(row["audited_source_fields"], sort_keys=True)
            if row.get("start_statements") is not None:
                row["start_statements"] = json.dumps(row["start_statements"], sort_keys=True)
            writer.writerow(row)
    print(json.dumps(counts, sort_keys=True))


if __name__ == "__main__":
    main()
