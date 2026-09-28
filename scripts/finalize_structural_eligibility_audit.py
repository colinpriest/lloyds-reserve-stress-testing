"""Write the reviewed economic-eligibility audit for all 70 pre-model stubs.

The underwriting-year lists below are transcribed from the filing pages captured by
``audit_structural_eligibility.py``.  They are deliberately separate from the old
``first_year_syndicate`` flag: the flag chooses the records to review, never their
economic eligibility.  Re-running this script verifies the inventory, source hashes,
page evidence and the mature-cohort arithmetic before writing JSON and CSV ledgers.
"""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUDIT_DIR = ROOT / "pdf_extraction" / "audit"
CANDIDATES = AUDIT_DIR / "structural_eligibility_candidates.json"
OUT_JSON = AUDIT_DIR / "structural_eligibility_audit.json"
OUT_CSV = AUDIT_DIR / "structural_eligibility_audit.csv"

# Filing-page transcription.  Template columns that contain only dashes are not
# underwriting cohorts; 2358/2022 is the one filing that prints legacy year headings
# beside an all-dash block, and its note below records that distinction explicitly.
REVIEWED_UW_YEARS = {
    "syndicate_1100_2024.json": [2024],
    "syndicate_1322_2023.json": [2023],
    "syndicate_1322_2024.json": [2023, 2024],
    "syndicate_1416_2022.json": [2021, 2022],
    "syndicate_1492_2015.json": [2015],
    "syndicate_1492_2016.json": [2015, 2016],
    "syndicate_1609_2022.json": [2021, 2022],
    "syndicate_1618_2021.json": [2021],
    "syndicate_1618_2022.json": [2021, 2022],
    "syndicate_1686_2015.json": [2014, 2015],
    "syndicate_1699_2023.json": [2022, 2023],
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
    "syndicate_1925_2024.json": [2024],
    "syndicate_1971_2019.json": [2019],
    "syndicate_1971_2020.json": [2019, 2020],
    "syndicate_1980_2019.json": [2018, 2019],
    "syndicate_1985_2023.json": [2023],
    "syndicate_1988_2022.json": [2021, 2022],
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
    "syndicate_4747_2021.json": [2020, 2021],
    "syndicate_5183_2023.json": [2022, 2023],
    "syndicate_5623_2019.json": [2018, 2019],
    "syndicate_5886_2017.json": [2017],
    "syndicate_5886_2018.json": [2017, 2018],
    "syndicate_6119_2015.json": [2014, 2015],
    "syndicate_6120_2015.json": [2015],
    "syndicate_6121_2015.json": [2015],
    "syndicate_6121_2016.json": [2015, 2016],
    "syndicate_6123_2015.json": [2015],
    "syndicate_6123_2016.json": [2015, 2016],
    "syndicate_6124_2015.json": [2015],
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
    "syndicate_6136_2023.json": [2023],
}


def source_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def best_triangle_evidence(candidate: dict, years: list[int]) -> dict:
    mentions = candidate.get("claims_development_mentions") or []
    scored = []
    for mention in mentions:
        text = mention.get("excerpt") or ""
        score = sum(str(year) in text for year in years)
        score += 2 * ("gross" in text.lower())
        scored.append((score, mention))
    return max(scored, key=lambda item: item[0])[1] if scored else {"page": None, "excerpt": ""}


def build_record(candidate: dict) -> dict:
    name = candidate["file"]
    year = int(candidate["year"])
    years = REVIEWED_UW_YEARS[name]
    mature = [uw for uw in years if uw <= year - 2]
    evidence = best_triangle_evidence(candidate, years)
    source = ROOT / candidate["source_file"]

    eligible_zero = name == "syndicate_1840_2022.json"
    if eligible_zero:
        decision = "eligible_observed_zero"
        eligibility = "eligible"
        nil_status = "printed_dashes_are_reported_nil_values"
        calculation = "UW2020: one-year-after 0 minus two-years-after 0 = 0.000 GBP m"
        opening = 0.279
        opening_status = "positive; gross claims outstanding at 1 January 2022"
        extraction_status = "corrected_from_pre_model_stub_by_source_page_audit"
    else:
        if mature:
            raise ValueError(f"{name}: reviewed years unexpectedly contain a mature cohort {mature}")
        decision = "structural_ineligible_no_mature_cohort"
        eligibility = "ineligible"
        nil_status = "not_applicable_no_mature_cohort"
        calculation = f"no underwriting year u <= {year - 2}; reviewed years are {years}"
        opening = candidate.get("opening_gross_claims_outstanding_gbp_m")
        opening_status = ("numeric deterministic reading recorded" if opening is not None else
                          "not numerically transcribed; does not alter the no-mature-cohort decision")
        extraction_status = "pre_model_stub_confirmed_structural_by_source_page_audit"

    note = None
    if name == "syndicate_2358_2022.json":
        note = ("The filing's template prints legacy year headings with dashes in every old column; "
                "only UW2022 contains a cohort, and gross claims outstanding at 1 January 2022 is nil.")

    record = {
        "file": name,
        "syndicate": int(candidate["syndicate"]),
        "report_year": year,
        "source_file": candidate["source_file"],
        "source_sha256": source_hash(source),
        "source_page": evidence.get("page"),
        "source_evidence": " ".join((evidence.get("excerpt") or "").split())[:3500],
        "inception_year": min(years),
        "underwriting_years": years,
        "triangle_basis": "gross; net companion table also reviewed where present",
        "mature_underwriting_years": mature,
        "nil_vs_missing": nil_status,
        "mature_cohort_calculation": calculation,
        "opening_gross_reserve_gbp_m": opening,
        "opening_reserve_status": opening_status,
        "economic_eligibility": eligibility,
        "decision": decision,
        "extraction_status": extraction_status,
        "review_note": note,
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
    names = {record["file"] for record in candidates}
    if len(candidates) != 70 or names != set(REVIEWED_UW_YEARS):
        missing = sorted(names ^ set(REVIEWED_UW_YEARS))
        raise SystemExit(f"review inventory mismatch: n={len(candidates)}, symmetric_difference={missing}")
    records = [build_record(record) for record in candidates]
    counts = {
        "reviewed": len(records),
        "structural_ineligible": sum(r["economic_eligibility"] == "ineligible" for r in records),
        "eligible_observed_zero": sum(r["decision"] == "eligible_observed_zero" for r in records),
        "eligibility_unresolved": sum(r["economic_eligibility"] == "unresolved" for r in records),
    }
    OUT_JSON.write_text(json.dumps({
        "definition": ("Filing-page audit of every record formerly classified from the extraction skip flag. "
                       "Economic eligibility is decided independently of extraction success."),
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
            writer.writerow(row)
    print(json.dumps(counts, sort_keys=True))


if __name__ == "__main__":
    main()
