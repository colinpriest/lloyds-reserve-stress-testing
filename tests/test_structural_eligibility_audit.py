"""The filing-page audit separates economic eligibility from extraction skips.

Round 62 (review of 29 September 2026, M-10, E-1, E-2 and test upgrade 5): the ledger is recomputed
here for all 70 records -- the usable cohort from the transcribed years, the decision from it, the
opening with its currency against the filing page, and the year headers against the page the ledger
cites -- and the one retained eligible record is held to the generator that writes it.
"""
import json
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
        "reviewed": 70,
        "structural_ineligible": 69,
        "eligible_observed_zero": 1,
        "eligibility_unresolved": 0,
    }
    assert len(audit["records"]) == 70
    assert all((r["source_page"] or r["source_file"].endswith((".html", ".htm")))
               and r["source_sha256"] for r in audit["records"])


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
    assert sum(r["opening_gross_reserve_gbp_m"] is not None for r in recs.values()) == 67
    # the two the review found: a closing balance recorded as the opening
    assert recs["syndicate_2019_2020.json"]["opening_gross_reserve_gbp_m"] == 0.0
    assert recs["syndicate_2019_2021.json"]["opening_gross_reserve_gbp_m"] == pytest.approx(278.4)
    assert recs["syndicate_2019_2021.json"]["opening_gross_reserve_currency"] == "USD"
    assert recs["syndicate_1980_2019.json"]["opening_gross_reserve_currency"] == "USD"


def test_the_ledger_is_the_transcription():
    tr = json.loads((AUDIT / "structural_eligibility_transcription.json").read_text(encoding="utf-8"))["records"]
    for name, r in _records().items():
        t = tr[name]
        assert r["opening_gross_reserve_gbp_m"] == t["opening_m"], name
        assert r["opening_gross_reserve_currency"] == t["opening_currency"], name
        assert r["triangle_basis"] == t["basis"], name
        page = t["triangle_page_index"] if t["triangle_page_index"] is not None else t["years_page_index"]
        assert r["source_page"] == page + 1, name


def _page_texts(r):
    import finalize_structural_eligibility_audit as fin
    return fin.page_texts(ROOT / r["source_file"])


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


def test_the_retained_record_is_its_generators_output_and_claims_no_model_work():
    """E-1: the committed 1840/2022 record differed from its generator and said "[RAG OVERRIDE: Model
    said PYD=0.000m ...]" with model confidences of 1.0 and passed validation, though no model ran."""
    committed = json.loads((ROOT / "pdf_extraction" / "syndicate_1840_2022.json").read_text(encoding="utf-8"))
    generated = json.loads(json.dumps(pipeline.sanitize_json_ascii(pipeline._reviewed_eligible_record(
        pipeline.REPORTS_DIR / "syndicate_1840_2022.pdf", 1840, 2022))))
    for d in (committed, generated):
        d.pop("extraction_timestamp")
    assert committed == generated
    block = committed["models"]["source-page-audit"]
    assert committed["models_run"] is False and committed["validation"]["models_run"] is False
    assert "passed" not in committed["validation"]
    assert not [k for k in block if k.endswith("_confidence")]
    assert "RAG OVERRIDE" not in block["data_quality_notes"] and "Model said" not in block["data_quality_notes"]
    assert block["direction"] == "flat"
