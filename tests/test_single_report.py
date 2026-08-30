"""Quick test: extract syndicate_2987_2018 with both models and check triangle verification.

Expected correct answer from GROSS claims development triangle:
  2011: 838.8 - 840.5 = -1.7
  2012: 961.7 - 972.7 = -11.0
  2013: 984.0 - 998.2 = -14.2
  2014: 1132.4 - 1143.1 = -10.7
  2015: 1056.1 - 1071.9 = -15.8
  2016: 1354.3 - 1229.5 = +124.8
  Total = +71.4 (strengthening)
"""

import os
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

report_path = Path("syndicate_reports/pdfs/syndicate_2987_2018.pdf")


def run_single_report():
    """Paid dual-model extraction of one report; needs the source PDF
    and both API keys. Kept out of module scope so pytest collection
    never executes it."""
    from test_gemini import process_one_report, GEMINI_MODEL, OPENAI_MODEL


    print("=" * 70)
    print("TEST: syndicate_2987_2018 -- checking PYD extraction + triangle verification")
    print("Expected: ~+71.4 (strengthening) from GROSS triangle")
    print("=" * 70)

    output_data, passed, discrepancies, hard_failures = process_one_report(report_path)

    for model_name in [GEMINI_MODEL, OPENAI_MODEL]:
        m = output_data["models"][model_name]
        print(f"\n{model_name}:")
        print(f"  prior_year_development_gbp_m: {m.get('prior_year_development_gbp_m')}")
        print(f"  direction:                     {m.get('direction')}")
        print(f"  exact_reserve_text:            {str(m.get('exact_reserve_text', ''))[:200]}")
        tri = m.get("_claims_triangle", {})
        if tri and tri.get("type") != "none":
            print(f"  _claims_triangle.type:         {tri.get('type')}")
            print(f"  _claims_triangle.uw_years:     {tri.get('underwriting_years')}")
            rows = tri.get("development_rows", [])
            print(f"  _claims_triangle rows:         {len(rows)} development rows")
            for i, row in enumerate(rows):
                labels = ["End of UW yr", "1yr later", "2yr later", "3yr later",
                          "4yr later", "5yr later", "6yr later", "7yr later", "8yr later"]
                label = labels[i] if i < len(labels) else f"row{i}"
                print(f"    {label}: {row}")
        else:
            print(f"  _claims_triangle: none/missing")
        notes = m.get("data_quality_notes", "")
        if "CODE OVERRIDE" in notes:
            print(f"  *** CODE OVERRIDE APPLIED ***")

    print(f"\nHard failures: {len(hard_failures)}")
    for hf in hard_failures:
        print(f"  {hf['field']}: {hf.get(GEMINI_MODEL, '')} vs {hf.get(OPENAI_MODEL, '')}")

    # Verify expected value
    for model_name in [GEMINI_MODEL, OPENAI_MODEL]:
        pyd = output_data["models"][model_name].get("prior_year_development_gbp_m")
        if pyd is not None and abs(float(pyd) - 71.4) < 5:
            print(f"\nOK: {model_name} PYD is close to expected +71.4: {pyd}")
        elif pyd is not None:
            print(f"\nWRONG: {model_name} PYD is {pyd}, expected ~+71.4")
        else:
            print(f"\nNULL: {model_name} PYD is null")


def test_single_report_extraction():
    import pytest
    if not report_path.exists():
        pytest.skip("source PDF not in the repository (reports are not committed)")
    if not (os.environ.get("GEMINI_API_KEY") and os.environ.get("OPENAI_API_KEY")):
        pytest.skip("paid extraction API keys not configured")
    run_single_report()


if __name__ == "__main__":
    run_single_report()
