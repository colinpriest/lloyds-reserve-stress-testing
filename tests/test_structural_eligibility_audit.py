"""The filing-page audit separates economic eligibility from extraction skips."""
import json

import pytest

import test_gemini as pipeline


def _audit():
    return json.loads(pipeline.STRUCTURAL_ELIGIBILITY_AUDIT.read_text(encoding="utf-8"))


def test_all_pre_model_stubs_have_source_reviewed_decisions():
    audit = _audit()
    assert audit["counts"] == {
        "reviewed": 70,
        "structural_ineligible": 69,
        "eligible_observed_zero": 1,
        "eligibility_unresolved": 0,
    }
    assert len(audit["records"]) == 70
    assert all((r["source_page"] or r["source_file"].endswith((".html", ".htm")))
               and r["source_sha256"] for r in audit["records"])


def test_mature_nil_cohort_with_positive_reserve_is_an_observed_zero():
    record = next(r for r in _audit()["records"]
                  if r["file"] == "syndicate_1840_2022.json")
    assert record["mature_underwriting_years"] == [2020]
    assert record["opening_gross_reserve_gbp_m"] == pytest.approx(0.279)
    assert record["economic_eligibility"] == "eligible"
    assert record["decision"] == "eligible_observed_zero"
    assert record["nil_vs_missing"] == "printed_dashes_are_reported_nil_values"
    assert "= 0.000 GBP m" in record["mature_cohort_calculation"]

    extracted = pipeline._reviewed_eligible_record(
        pipeline.REPORTS_DIR / "syndicate_1840_2022.pdf", 1840, 2022)
    block = extracted["models"]["source-page-audit"]
    assert block["prior_year_development_gbp_m"] == 0.0
    assert block["prior_year_development_pct"] == 0.0
    assert block["opening_reserves_gbp_m"] > 0
    assert block["_rag_triangle"]["development_rows"][1][0] == 0.0
    assert block["_rag_triangle"]["development_rows"][2][0] == 0.0
