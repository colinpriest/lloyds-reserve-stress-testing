"""Human-in-the-loop adjudication of LLM extraction disagreements.

For each hard failure, sends the PDF to a third model (Claude) for
verification, then presents findings to the human operator for approval.
Nothing is recorded without explicit human sign-off.

The operator can:
  - approve the adjudicator's recommendation
  - override with a specific model's value (one-off manual adjustment)
  - stop the script to make substantive changes

When systematic patterns emerge across multiple reports, proposes prompt
fixes -- again requiring human approval before recording or applying.

Usage:
    python adjudicate.py                    # interactive adjudication
    python adjudicate.py --report syndicate_1110_2020   # single report
    python adjudicate.py --dry-run          # preview without calling LLMs
    python adjudicate.py --propose-fixes    # analyse patterns, propose prompt updates
    python adjudicate.py --accept 1.6       # mark a proposed prompt fix as accepted
"""

import os
import re
import sys
import json
import base64
import hashlib
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

REPORTS_DIR = Path("syndicate_reports/pdfs")
OUTPUT_DIR = Path("pdf_extraction")
HTML_PDF_CACHE = Path("pdf_extraction/html_converted")
AUDIT_DIR = Path("pdf_extraction/audit")
SPEC_DIR = Path("pdf_extraction/spec")

GEMINI_MODEL = "gemini-2.5-flash"
OPENAI_MODEL = "gpt-5-mini"
ADJUDICATOR_MODEL = "claude-sonnet-4-6"

# ---------------------------------------------------------------------------
# Adjudicator LLM output caching
# ---------------------------------------------------------------------------
ADJ_CACHE_DIR = Path("pdf_extraction/llm_cache")


def _adj_cache_key(syndicate_num: int, report_year: int,
                   field: str, prompt_text: str) -> str:
    """Build a deterministic cache key for adjudicator calls.

    Hash = SHA-256 of (ADJUDICATOR_MODEL, syndicate, year, field, prompt).
    """
    parts = [ADJUDICATOR_MODEL, str(syndicate_num), str(report_year),
             field, prompt_text]
    blob = "|".join(parts).encode("utf-8")
    return "adj_" + hashlib.sha256(blob).hexdigest()


def _adj_cache_load(cache_key: str):
    """Load cached adjudicator result. Returns (data, tokens_in, tokens_out, True) or (None, 0, 0, False)."""
    path = ADJ_CACHE_DIR / f"{cache_key}.json"
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                envelope = json.load(f)
            meta = envelope.get("_cache_meta", {})
            return (envelope["data"],
                    meta.get("tokens_in", 0),
                    meta.get("tokens_out", 0),
                    True)
        except (json.JSONDecodeError, OSError, KeyError):
            pass
    return None, 0, 0, False


def _adj_cache_save(cache_key: str, data, tokens_in: int, tokens_out: int,
                    *, syndicate_num: int = 0, report_year: int = 0,
                    field: str = ""):
    """Persist adjudicator result to cache."""
    ADJ_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    envelope = {
        "_cache_meta": {
            "model": ADJUDICATOR_MODEL,
            "syndicate": syndicate_num,
            "year": report_year,
            "field": field,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "cached_at": datetime.now(timezone.utc).isoformat(),
        },
        "data": data,
    }
    with open(ADJ_CACHE_DIR / f"{cache_key}.json", "w", encoding="utf-8") as f:
        json.dump(envelope, f, indent=2, ensure_ascii=True)


# ---------------------------------------------------------------------------
# Human interaction
# ---------------------------------------------------------------------------

def ask_human(prompt, valid_choices=None):
    """Prompt the human operator and return their input.

    If valid_choices is given, keeps asking until the input matches one.
    """
    while True:
        try:
            response = input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  Interrupted by user.")
            sys.exit(1)
        if valid_choices is None:
            return response
        if response.lower() in [c.lower() for c in valid_choices]:
            return response.lower()
        print(f"    Invalid choice. Options: {', '.join(valid_choices)}")


def present_adjudication(report_stem, field, gemini_val, gpt_val, adj_result, confidence, evidence, correct_model, reason, context_lines=None):
    """Present the adjudicator's finding and ask the human what to do.

    Args:
        context_lines: Optional list of strings showing supporting field values
                       from both models (e.g. opening_reserves, pyd amounts).

    Returns one of:
        ("approve", correct_model)    -- accept adjudicator recommendation
        ("override", model_name)      -- use a specific model's value
        ("override_value", value)     -- use a custom value
        ("exclude", reason)           -- exclude this report entirely
        ("stop", None)                -- halt the script
    """
    print()
    print(f"    {'~' * 60}")
    print(f"    ADJUDICATOR FINDING for {report_stem} / {field}")
    print(f"    {'~' * 60}")
    print(f"    Gemini says:      {gemini_val}")
    print(f"    GPT says:         {gpt_val}")
    if context_lines:
        print(f"    --- Supporting context (from both models) ---")
        for line in context_lines:
            print(f"    {line}")
        print(f"    ---")
    print(f"    Adjudicator says: {adj_result}")
    print(f"    Confidence:       {confidence}")
    print(f"    Evidence:         {evidence}")
    print(f"    Recommendation:   {correct_model} -- {reason}")
    print()
    print(f"    What would you like to do?")
    print(f"      [a] Approve adjudicator recommendation")
    print(f"      [g] Override: use Gemini value")
    print(f"      [o] Override: use GPT value")
    print(f"      [v] Override: enter a custom value")
    print(f"      [x] Exclude this report entirely")
    print(f"      [s] Stop script (to make substantive changes)")
    print()

    choice = ask_human("    Your decision: ", ["a", "g", "o", "v", "x", "s"])

    if choice == "a":
        return ("approve", correct_model)
    elif choice == "g":
        return ("override", GEMINI_MODEL)
    elif choice == "o":
        return ("override", OPENAI_MODEL)
    elif choice == "v":
        custom = ask_human("    Enter custom value: ")
        return ("override_value", custom)
    elif choice == "x":
        reason = ask_human("    Reason for exclusion: ")
        return ("exclude", reason)
    elif choice == "s":
        return ("stop", None)
    else:
        logger.warning(f"Unrecognised adjudication choice: {choice!r}")
        return ("stop", None)


def present_report_decision(report_stem, syndicate_num, report_year, report_results):
    """After adjudicating all fields for a report, ask what to do with it.

    Returns one of:
        ("include", override_model)   -- include in dataset, use override_model for disputed fields
        ("exclude", reason)           -- reject from dataset
        ("stop", None)                -- halt the script
    """
    resolved_types = ("approve", "override", "override_value", "auto_accept")
    resolved = [r for r in report_results if r.get("decision_type") in resolved_types]
    unresolved = [r for r in report_results if r.get("decision_type") not in resolved_types]

    print()
    print(f"    {'~' * 60}")
    print(f"    REPORT DECISION: {report_stem}")
    print(f"    {'~' * 60}")
    print(f"    Resolved fields:   {len(resolved)}")

    for r in resolved:
        model = r.get("final_model", "custom")
        print(f"      {r['field']}: use {model} (value: {r.get('final_value', '?')})")

    if unresolved:
        print(f"    Unresolved fields:  {len(unresolved)}")
        for r in unresolved:
            print(f"      {r['field']}: {r.get('status', '?')}")

    print()
    print(f"    What would you like to do with this report?")
    print(f"      [i] Include in dataset (with overrides above)")
    print(f"      [x] Exclude from dataset")
    print(f"      [s] Stop script")
    print()

    choice = ask_human("    Your decision: ", ["i", "x", "s"])

    if choice == "i":
        return ("include", None)
    elif choice == "x":
        reason = ask_human("    Reason for exclusion: ")
        return ("exclude", reason)
    elif choice == "s":
        return ("stop", None)


def present_prompt_proposal(proposal, fix):
    """Present a prompt fix proposal and ask for approval.

    Returns one of:
        ("approve", None)     -- accept and record the proposal
        ("reject", None)      -- skip this proposal
        ("edit", instruction) -- accept with edited instruction text
        ("stop", None)        -- halt the script
    """
    print()
    print(f"    {'~' * 60}")
    print(f"    PROMPT FIX PROPOSAL")
    print(f"    {'~' * 60}")
    print(f"    Field:       {proposal['field']}")
    print(f"    Wrong model: {proposal['wrong_model']}")
    print(f"    Occurrences: {proposal['count']} reports")
    print(f"    Reports:     {', '.join(proposal['reports'])}")
    print()
    print(f"    Proposed instruction:")
    print(f"      {fix['instruction']}")
    print()
    print(f"    Description: {fix['description']}")
    print(f"    Rationale:   {fix['rationale']}")
    print()
    print(f"    What would you like to do?")
    print(f"      [a] Approve this prompt fix")
    print(f"      [e] Edit the instruction text, then approve")
    print(f"      [r] Reject (skip this proposal)")
    print(f"      [s] Stop script")
    print()

    choice = ask_human("    Your decision: ", ["a", "e", "r", "s"])

    if choice == "a":
        return ("approve", None)
    elif choice == "e":
        print(f"    Current instruction:")
        print(f"      {fix['instruction']}")
        edited = ask_human("    Enter edited instruction:\n      ")
        return ("edit", edited)
    elif choice == "r":
        return ("reject", None)
    elif choice == "s":
        return ("stop", None)


# ---------------------------------------------------------------------------
# PDF and LLM utilities
# ---------------------------------------------------------------------------

def find_source_pdf(report_stem):
    """Find the source PDF/HTML for a report stem."""
    for ext in (".pdf", ".html", ".htm"):
        path = REPORTS_DIR / f"{report_stem}{ext}"
        if path.exists():
            if ext in (".html", ".htm"):
                cached = HTML_PDF_CACHE / f"{report_stem}.pdf"
                if cached.exists():
                    return cached
            return path
    return None


CURRENCY_NOTE = (
    "CURRENCY: Report all monetary amounts in the report's NATIVE currency "
    "(GBP, USD, or EUR — whichever the financial statements use). "
    "Do NOT convert to GBP. Do NOT return null just because the report uses USD or EUR. "
    "The field name says 'gbp_m' but it accepts any currency — the 'currency' field "
    "records which currency was used."
)


def build_verification_prompt(field, gemini_value, gpt_value, syndicate_num, report_year):
    """Build a targeted prompt to verify a specific disputed field."""

    if field == "direction":
        return (
            f"This is a Lloyd's syndicate {syndicate_num} annual report for year-end {report_year}.\n\n"
            f"Two LLMs disagree on the DIRECTION of prior year reserve development:\n"
            f"  - Model A says: {gemini_value}\n"
            f"  - Model B says: {gpt_value}\n\n"
            f"BEFORE YOU START — SOURCES YOU MUST IGNORE (these are NOT reserve movements):\n"
            f"  ✗ 'Claims incurred in prior underwriting years' or 'Claims incurred in relation to "
            f"prior underwriting years' from the Profit & Loss Account / Technical Account. "
            f"Despite containing the words 'prior underwriting years', this row shows CLAIMS INCURRED "
            f"(a P&L accounting item), NOT the reserve movement. It includes premiums earned minus "
            f"claims paid minus reserve changes all combined. IGNORE IT COMPLETELY.\n"
            f"  ✗ 'Movement in provision' from Reserves Reconciliation (includes current + prior)\n"
            f"  ✗ Closing reserve balances (balance sheet figures, not movements)\n"
            f"  ✗ Current year loss ratios, catastrophe loss ratios, or combined ratios\n"
            f"  ✗ Year-of-account PROFIT/LOSS results (e.g. 'a loss to capital providers of £17.7m')\n\n"
            f"NOW — find the prior year reserve direction from THESE correct sources "
            f"(in priority order):\n"
            f"  1. The 'Movement in prior year's provision for claims outstanding' note\n"
            f"  2. The Managing Agent's / Underwriter's Report narrative about prior year reserves\n"
            f"  3. Year-of-account result breakdown: e.g. 'The result is a profit of £X, of which "
            f"a loss of £Y is attributable to the {report_year} YOA, a profit of £Z is attributable "
            f"to the {report_year - 1} YOA'. The non-current-year components ({report_year - 1} and "
            f"prior) indicate prior year development direction.\n"
            f"  4. Year of account closure language (e.g. 'profit for the closed year' or "
            f"'improvement on forecast' = release; 'deterioration' = strengthening)\n"
            f"  5. GROSS claims development triangle — compare bottom row to previous diagonal "
            f"for UW years <= {report_year - 2}. Net decrease = release, net increase = strengthening.\n\n"
            f"Did prior year reserves RELEASE (surplus -- reserves were more than needed) "
            f"or STRENGTHEN (deficit -- reserves were insufficient, additional provision needed)?\n\n"
            f"If the report mentions 'mixed' or has BOTH releases and strengthenings across "
            f"different lines of business, use 'mixed'.\n\n"
            f"IMPORTANT: If the report uses 'surplus/(deficit)' language:\n"
            f"  - Parenthesized numbers like (3.0) = deficit = STRENGTHENING\n"
            f"  - Unparenthesized numbers like 3.0 = surplus = RELEASE\n\n"
            f"Reply with ONLY valid JSON:\n"
            f'{{"field": "direction", "correct_value": "<release|strengthening|flat|mixed>", '
            f'"evidence": "<verbatim quote from document>", '
            f'"page": <page number>, '
            f'"confidence": <0.0-1.0>}}'
        )

    if field == "prior_year_development_gbp_m":
        return (
            f"This is a Lloyd's syndicate {syndicate_num} annual report for year-end {report_year}.\n\n"
            f"Two LLMs disagree on the prior year development amount (in GBP/USD/EUR millions):\n"
            f"  - Model A says: {gemini_value}\n"
            f"  - Model B says: {gpt_value}\n\n"
            f"BEFORE YOU START — SOURCES YOU MUST COMPLETELY IGNORE:\n"
            f"  ✗ 'Claims incurred in prior underwriting years' or 'Claims incurred in relation to "
            f"prior underwriting years' from the Profit & Loss Account / Technical Account. "
            f"Despite containing the words 'prior underwriting years', this is CLAIMS INCURRED "
            f"(a P&L accounting line item), NOT the prior year reserve movement. It combines "
            f"premiums earned, claims paid, and reserve changes into one figure. "
            f"Example to REJECT: 'Claims incurred in relation to prior underwriting years "
            f"789.7 (617.6) 172.1' — these are gross/reinsurance/net claims incurred, not reserve "
            f"movements. IGNORE THIS ROW COMPLETELY.\n"
            f"  ✗ 'Movement in provision' from Reserves Reconciliation — includes current + prior combined\n"
            f"  ✗ Closing reserve balances / net technical provisions — balance sheet figures, not movements\n"
            f"  ✗ Changes in booked ultimates for specific named events — one event's estimate change, "
            f"not total portfolio prior year development\n"
            f"  ✗ Year-of-account PROFIT/LOSS results — e.g. 'a loss to capital providers from the "
            f"2017 and Prior Years of Account of £17.7m'. This is the overall underwriting PROFIT result, "
            f"NOT the reserve movement.\n\n"
            f"Find the prior year development amount. Use the GROSS figure (insurance liabilities), "
            f"NOT the net figure (after reinsurer's share). When a note shows 'Insurance liabilities', "
            f"'Reinsurer's share', and 'Net liabilities' columns, use the 'Insurance liabilities' column. "
            f"If a note only shows NET figures (e.g. 'increased net technical reserves by £X'), "
            f"skip it and use the GROSS claims development triangle (source 4) instead.\n\n"
            f"Look in THESE correct sources (STRICT priority order — "
            f"use the FIRST source you find, but ONLY if it shows the GROSS figure):\n"
            f"  1. 'Movement in prior year's provision for claims outstanding' note — or any note "
            f"that explicitly states 'calendar year movements arising from prior years' provision "
            f"(only if it shows the GROSS / Insurance liabilities figure)\n"
            f"  2. Narrative text that explicitly states the amount (e.g. 'released £X in respect "
            f"of prior periods')\n"
            f"  3. Year-of-account result breakdown: e.g. 'The result is a profit of £X, of which "
            f"a loss of £Y is attributable to {report_year} YOA, a profit of £Z is attributable to "
            f"the {report_year - 1} YOA and a loss of £W is attributable to {report_year - 2} & "
            f"prior'. Sum the non-current-year components: prior_year_development = Z + (-W). "
            f"A net profit on prior years = release (negative sign).\n"
            f"  4. GROSS Claims Development Table (triangle): "
            f"Must use the GROSS triangle, NOT the net triangle. "
            f"Compare each UW year's 'Current estimate' "
            f"(bottom row) to its estimate from the previous diagonal (one row up in same column). "
            f"EXCLUDE the two most recent UW years ({report_year} and {report_year - 1}). "
            f"Sum the differences for UW years <= {report_year - 2}. "
            f"Decrease = release (negative), increase = strengthening (positive). "
            f"WORKED EXAMPLE (year-end 2022): "
            f"2017 UW year: current=420.8, previous diagonal=422.6 → change=-1.8; "
            f"2018: current=390.3, previous=394.1 → -3.8; "
            f"2019: current=280.5, previous=277.6 → +2.9; "
            f"2020: current=236.6, previous=228.8 → +7.8; "
            f"Total = -1.8 + (-3.8) + 2.9 + 7.8 = +5.1 (strengthening). "
            f"CAUTION: Exclude any 'X and prior' aggregate column — only use individual UW year columns. "
            f"CAUTION: If RITC (Reinsurance to Close) of another syndicate occurred, "
            f"the triangle is distorted — prefer narrative or movement notes instead.\n"
            f"  5. Loss Ratio Development Table (fallback if no absolute claims triangle): "
            f"If the report shows a GROSS loss ratio development table (percentages, not £m), "
            f"compute Δ loss ratio for each UW year (current minus previous diagonal, excluding "
            f"{report_year} and {report_year - 1}), then multiply each by that UW year's gross "
            f"premiums to get £m. Sum across all older UW years. Example: if 2008 UW year "
            f"loss ratio changed from 67% to 66% = -1%, and gross premiums were £100m, "
            f"contribution = -1% × 100 = -£1.0m (release).\n\n"
            f"Sign convention:\n"
            f"  - NEGATIVE = release (reserves were sufficient, surplus returned)\n"
            f"  - POSITIVE = strengthening (reserves were insufficient, additional provision)\n\n"
            f"IMPORTANT: If the report uses 'surplus/(deficit)' language:\n"
            f"  - Parenthesized numbers like (3.0) = deficit = POSITIVE (strengthening)\n"
            f"  - Unparenthesized numbers like 3.0 = surplus = NEGATIVE (release)\n\n"
            f"{CURRENCY_NOTE}\n\n"
            f"CRITICAL: If you can compute a value from the triangle or any other source, "
            f"you MUST return that value as correct_value — do NOT return null. "
            f"Only return null if the document genuinely does not contain enough information "
            f"to determine or compute the prior year development amount.\n\n"
            f"Reply with ONLY valid JSON:\n"
            f'{{"field": "prior_year_development_gbp_m", "correct_value": <signed number or null>, '
            f'"evidence": "<verbatim quote from document>", '
            f'"page": <page number>, '
            f'"confidence": <0.0-1.0>}}'
        )

    if field == "prior_year_development_pct":
        return (
            f"This is a Lloyd's syndicate {syndicate_num} annual report for year-end {report_year}.\n\n"
            f"Two LLMs disagree on the prior year development percentage:\n"
            f"  - Model A says: {gemini_value}\n"
            f"  - Model B says: {gpt_value}\n\n"
            f"This is calculated as: prior_year_development_gbp_m / opening_reserves_gbp_m * 100.\n"
            f"If you can find both the prior year development amount and the opening gross claims "
            f"outstanding, compute the percentage. Sign convention matches the amount "
            f"(negative = release, positive = strengthening).\n\n"
            f"{CURRENCY_NOTE}\n\n"
            f"Reply with ONLY valid JSON:\n"
            f'{{"field": "prior_year_development_pct", "correct_value": <signed number or null>, '
            f'"evidence": "<calculation showing amount / opening reserves>", '
            f'"page": <page number>, '
            f'"confidence": <0.0-1.0>}}'
        )

    if field == "currency":
        return (
            f"This is a Lloyd's syndicate {syndicate_num} annual report for year-end {report_year}.\n\n"
            f"Two LLMs disagree on the reporting currency:\n"
            f"  - Model A says: {gemini_value}\n"
            f"  - Model B says: {gpt_value}\n\n"
            f"Look at the financial statements (Income Statement, Balance Sheet). "
            f"What currency are the amounts denominated in? "
            f"Look for 'GBP', 'USD', 'EUR', or currency symbols.\n\n"
            f"Reply with ONLY valid JSON:\n"
            f'{{"field": "currency", "correct_value": "<GBP|USD|EUR>", '
            f'"evidence": "<verbatim quote showing currency>", '
            f'"page": <page number>, '
            f'"confidence": <0.0-1.0>}}'
        )

    if field == "opening_reserves_gbp_m":
        return (
            f"This is a Lloyd's syndicate {syndicate_num} annual report for year-end {report_year}.\n\n"
            f"Two LLMs disagree on the opening gross claims outstanding:\n"
            f"  - Model A says: {gemini_value}\n"
            f"  - Model B says: {gpt_value}\n\n"
            f"Find the GROSS CLAIMS OUTSTANDING at the start of the year (i.e. prior year-end balance).\n\n"
            f"This is ONLY claims reserves — do NOT include 'Provision for unearned premiums'.\n\n"
            f"Use these sources in STRICT priority order — use the FIRST available:\n"
            f"  1. BALANCE SHEET / Statement of Financial Position — find 'Claims outstanding' "
            f"(or 'Gross claims outstanding' or 'Claims outstanding - gross amount') in the LIABILITIES "
            f"section under 'Technical provisions'. Use the PRIOR YEAR comparative column "
            f"(e.g. in a {report_year} report, use the {report_year - 1} column). "
            f"WARNING: Do NOT use the 'Reinsurers' share of claims outstanding' from the ASSETS side — "
            f"that is the reinsurance recoverable, a completely different figure.\n"
            f"  2. Technical Reserves / Claims Provisions note — 'At 1 January' or "
            f"'At beginning of year' in the GROSS / Insurance liabilities column. "
            f"NOTE: This may differ from the Balance Sheet by small amounts due to accounting "
            f"adjustments — the Balance Sheet figure is authoritative.\n\n"
            f"{CURRENCY_NOTE}\n\n"
            f"Reply with ONLY valid JSON:\n"
            f'{{"field": "opening_reserves_gbp_m", "correct_value": <number or null>, '
            f'"evidence": "<verbatim quote from document>", '
            f'"page": <page number>, '
            f'"confidence": <0.0-1.0>}}'
        )

    if field == "gross_premiums_written_gbp_m":
        return (
            f"This is a Lloyd's syndicate {syndicate_num} annual report for year-end {report_year}.\n\n"
            f"Two LLMs disagree on total gross premiums written:\n"
            f"  - Model A says: {gemini_value}\n"
            f"  - Model B says: {gpt_value}\n\n"
            f"Find the total gross premiums written in the Income Statement / "
            f"Profit and Loss Technical Account.\n\n"
            f"{CURRENCY_NOTE}\n\n"
            f"Reply with ONLY valid JSON:\n"
            f'{{"field": "gross_premiums_written_gbp_m", "correct_value": <number>, '
            f'"evidence": "<verbatim quote from document>", '
            f'"page": <page number>, '
            f'"confidence": <0.0-1.0>}}'
        )

    if field.startswith("gross_premium_mix["):
        lob_name = field.split("[")[1].rstrip("]").split(".")[0]
        sub_field = field.split(".")[-1] if "." in field else "presence"
        return (
            f"This is a Lloyd's syndicate {syndicate_num} annual report for year-end {report_year}.\n\n"
            f"Two LLMs disagree on the gross premium mix entry for '{lob_name}':\n"
            f"  - Model A says: {gemini_value}\n"
            f"  - Model B says: {gpt_value}\n\n"
            f"Find the Segmental Analysis note (regulatory/statutory classes). "
            f"Look for the line of business '{lob_name}' and its {sub_field}.\n\n"
            f"{CURRENCY_NOTE}\n\n"
            f"Reply with ONLY valid JSON:\n"
            f'{{"field": "{field}", "correct_value": <value>, '
            f'"evidence": "<verbatim quote from document>", '
            f'"page": <page number>, '
            f'"confidence": <0.0-1.0>}}'
        )

    # Fallback
    return (
        f"This is a Lloyd's syndicate {syndicate_num} annual report for year-end {report_year}.\n\n"
        f"Two LLMs disagree on the field '{field}':\n"
        f"  - Model A says: {gemini_value}\n"
        f"  - Model B says: {gpt_value}\n\n"
        f"Find the correct value in the document.\n\n"
        f"Reply with ONLY valid JSON:\n"
        f'{{"field": "{field}", "correct_value": <value>, '
        f'"evidence": "<verbatim quote from document>", '
        f'"page": <page number>, '
        f'"confidence": <0.0-1.0>}}'
    )


def _shrink_pdf(pdf_path, max_size_mb=20, max_pages=100, page_hints=None):
    """Shrink a PDF to fit within Claude API limits.

    Handles two constraints:
    1. File size: compresses images if PDF > max_size_mb
    2. Page count: trims to relevant pages if PDF > max_pages

    If the PDF is already within both limits, returns it unchanged.

    Args:
        pdf_path: Path to the PDF file.
        max_size_mb: Maximum file size in MB.
        max_pages: Maximum number of pages (Claude API limit = 100).
        page_hints: Optional list of 1-indexed page numbers to prioritize
                     when trimming. A window of pages around hints is kept.

    Returns:
        bytes of the (possibly modified) PDF.
    """
    import fitz  # PyMuPDF

    with open(pdf_path, "rb") as f:
        pdf_bytes = f.read()

    max_bytes = max_size_mb * 1024 * 1024

    # Check page count first
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    total_pages = len(doc)

    if total_pages > max_pages:
        print(f"    PDF has {total_pages} pages (limit {max_pages}), trimming...")
        if page_hints:
            # Keep ±5 pages around each hint, plus first 10 and last 10 pages
            pages_to_keep = set(range(min(10, total_pages)))  # First 10
            pages_to_keep.update(range(max(0, total_pages - 10), total_pages))  # Last 10
            for p in page_hints:
                p0 = p - 1  # Convert to 0-indexed
                for offset in range(-5, 6):
                    idx = p0 + offset
                    if 0 <= idx < total_pages:
                        pages_to_keep.add(idx)
        else:
            # No hints: take first 50 and last 50 pages
            pages_to_keep = set(range(min(50, total_pages)))
            pages_to_keep.update(range(max(0, total_pages - 50), total_pages))

        pages_to_keep = sorted(pages_to_keep)[:max_pages]

        new_doc = fitz.open()
        for pg in pages_to_keep:
            new_doc.insert_pdf(doc, from_page=pg, to_page=pg)

        pdf_bytes = new_doc.tobytes(garbage=4, deflate=True)
        print(f"    Trimmed to {len(pages_to_keep)} pages ({len(pdf_bytes) / (1024*1024):.1f} MB)")
        new_doc.close()

    doc.close()

    if len(pdf_bytes) < max_bytes:
        return pdf_bytes

    original_mb = len(pdf_bytes) / (1024 * 1024)
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")

    # Strategy 1: Remove images entirely (text is what matters for adjudication)
    for page in doc:
        image_list = page.get_images(full=True)
        for img in image_list:
            xref = img[0]
            try:
                # Replace image with a tiny 1x1 white pixel
                doc.xref_set_key(xref, "Width", "1")
                doc.xref_set_key(xref, "Height", "1")
                doc.xref_set_key(xref, "BitsPerComponent", "8")
                doc.xref_set_key(xref, "ColorSpace", "/DeviceGray")
                doc.xref_set_key(xref, "Filter", "")
                doc.update_stream(xref, b"\xff")  # Single white pixel
            except Exception:
                pass  # Skip images that can't be modified

    # Save with garbage collection and deflation
    compressed = doc.tobytes(
        garbage=4,       # Maximum garbage collection
        deflate=True,    # Compress streams
        clean=True,      # Clean up redundant content
    )
    doc.close()

    compressed_mb = len(compressed) / (1024 * 1024)
    print(f"    PDF compressed: {original_mb:.1f} MB -> {compressed_mb:.1f} MB")

    if len(compressed) < max_bytes:
        return compressed

    # Strategy 2: If still too large, remove all non-text content more aggressively
    # by rebuilding with just text extracted per page
    print(f"    Still too large ({compressed_mb:.1f} MB), trying text-only rebuild...")
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    new_doc = fitz.open()

    for page in doc:
        # Create a new page with same dimensions
        rect = page.rect
        new_page = new_doc.new_page(width=rect.width, height=rect.height)
        # Extract and insert text blocks
        blocks = page.get_text("dict")["blocks"]
        for block in blocks:
            if block["type"] == 0:  # Text block
                for line in block["lines"]:
                    for span in line["spans"]:
                        try:
                            new_page.insert_text(
                                fitz.Point(span["origin"][0], span["origin"][1]),
                                span["text"],
                                fontsize=span["size"],
                            )
                        except Exception:
                            pass

    rebuilt = new_doc.tobytes(garbage=4, deflate=True)
    rebuilt_mb = len(rebuilt) / (1024 * 1024)
    print(f"    Text-only rebuild: {rebuilt_mb:.1f} MB")
    doc.close()
    new_doc.close()
    return rebuilt


def call_adjudicator(pdf_path, prompt, page_hints=None,
                     syndicate_num=0, report_year=0, field=""):
    """Send PDF + verification prompt to Claude for adjudication.

    Args:
        pdf_path: Path to the PDF file.
        prompt: The verification prompt.
        page_hints: Optional list of 1-indexed page numbers relevant to the
                     disputed field (used to trim large/long PDFs).
        syndicate_num: Syndicate number (for cache key).
        report_year: Report year (for cache key).
        field: Field name being adjudicated (for cache key).

    Results are cached in pdf_extraction/llm_cache/ keyed by
    (ADJUDICATOR_MODEL, syndicate, year, field, prompt_text).
    """
    # Check cache first
    if syndicate_num and report_year and field:
        cache_key = _adj_cache_key(syndicate_num, report_year, field, prompt)
        cached_data, cached_in, cached_out, hit = _adj_cache_load(cache_key)
        if hit:
            print(f"    [{ADJUDICATOR_MODEL}] Cache hit for {field}")
            return cached_data, cached_in, cached_out
    else:
        cache_key = None

    import anthropic

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY environment variable is not set — required for adjudication")
    client = anthropic.Anthropic(api_key=api_key)

    pdf_bytes = _shrink_pdf(pdf_path, page_hints=page_hints)
    pdf_b64 = base64.b64encode(pdf_bytes).decode("utf-8")

    response = client.messages.create(
        model=ADJUDICATOR_MODEL,
        max_tokens=2048,
        system="You are a financial data extraction validator. Reply with ONLY valid JSON — no reasoning, no explanation, no text before or after the JSON object.",
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": pdf_b64,
                        },
                    },
                    {
                        "type": "text",
                        "text": prompt,
                    },
                ],
            }
        ],
    )

    raw = response.content[0].text.strip()
    tokens_in = response.usage.input_tokens
    tokens_out = response.usage.output_tokens

    def _return_and_cache(parsed):
        """Save to cache (if key available) and return."""
        if cache_key:
            _adj_cache_save(cache_key, parsed, tokens_in, tokens_out,
                            syndicate_num=syndicate_num, report_year=report_year,
                            field=field)
        return parsed, tokens_in, tokens_out

    # Try direct parse first
    try:
        return _return_and_cache(json.loads(raw))
    except json.JSONDecodeError:
        pass

    # Strip markdown fences (```json ... ``` or ``` ... ```)
    if "```" in raw:
        # Find content between first ``` and last ```
        parts = raw.split("```")
        for part in parts[1:]:
            # Skip the language tag if present (e.g. "json\n")
            candidate = part.strip()
            if candidate.lower().startswith("json"):
                candidate = candidate[4:].strip()
            try:
                return _return_and_cache(json.loads(candidate))
            except json.JSONDecodeError:
                continue

    # Try to find JSON object anywhere in the response
    # Try both first { and last { in case the model outputs reasoning before JSON
    import re
    brace_positions = [m.start() for m in re.finditer(r'\{', raw)]
    brace_end = raw.rfind("}")

    for brace_start in brace_positions:
        if brace_end <= brace_start:
            continue
        candidate = raw[brace_start:brace_end + 1]
        # Direct parse
        try:
            return _return_and_cache(json.loads(candidate))
        except json.JSONDecodeError:
            pass
        # Fix trailing commas
        fixed = re.sub(r',\s*([}\]])', r'\1', candidate)
        try:
            return _return_and_cache(json.loads(fixed))
        except json.JSONDecodeError:
            pass
        # Strip non-ASCII
        cleaned = fixed.encode("ascii", "ignore").decode("ascii")
        try:
            return _return_and_cache(json.loads(cleaned))
        except json.JSONDecodeError:
            pass
        # Fix unescaped control characters
        cleaned2 = re.sub(r'[\x00-\x1f\x7f]', ' ', cleaned)
        try:
            return _return_and_cache(json.loads(cleaned2))
        except json.JSONDecodeError:
            pass

    raise ValueError(f"Could not parse JSON from adjudicator response: {raw[:500]}")


def sanitize_for_json(obj):
    """Replace non-ASCII characters with ASCII equivalents."""
    if isinstance(obj, str):
        obj = obj.replace("\u00a3", "GBP ")
        obj = obj.replace("\u20ac", "EUR ")
        obj = obj.replace("\u2013", "-")
        obj = obj.replace("\u2014", "-")
        obj = obj.replace("\u2018", "'")
        obj = obj.replace("\u2019", "'")
        obj = obj.replace("\u201c", '"')
        obj = obj.replace("\u201d", '"')
        obj = re.sub(r'[^\x00-\x7F]', '', obj)
    return obj


def determine_correct_model(field, adjudicator_value, gemini_value, gpt_value):
    """Determine which model (if either) matches the adjudicator's answer."""
    if adjudicator_value is None:
        return "neither", "Adjudicator returned null"

    if isinstance(adjudicator_value, str):
        adj_lower = adjudicator_value.strip().lower()
        if str(gemini_value).strip().lower() == adj_lower:
            return GEMINI_MODEL, f"Adjudicator agrees: {adjudicator_value}"
        if str(gpt_value).strip().lower() == adj_lower:
            return OPENAI_MODEL, f"Adjudicator agrees: {adjudicator_value}"
        return "neither", f"Adjudicator says {adjudicator_value}, neither model matches"

    try:
        adj_f = float(adjudicator_value)
        gem_none = gemini_value is None or gemini_value == "None"
        gpt_none = gpt_value is None or gpt_value == "None"

        if not gem_none:
            gem_f = float(gemini_value)
            if gem_f == adj_f or (abs(gem_f - adj_f) <= max(0.05, abs(adj_f) * 0.005)):
                return GEMINI_MODEL, f"Adjudicator agrees: {adjudicator_value}"

        if not gpt_none:
            gpt_f = float(gpt_value)
            if gpt_f == adj_f or (abs(gpt_f - adj_f) <= max(0.05, abs(adj_f) * 0.005)):
                return OPENAI_MODEL, f"Adjudicator agrees: {adjudicator_value}"

        if adj_f == 0.0 and (gem_none or gpt_none):
            if gem_none:
                return GEMINI_MODEL, "Both null/zero -- equivalent"
            return OPENAI_MODEL, "Both null/zero -- equivalent"

        return "neither", f"Adjudicator says {adjudicator_value}, neither model matches"
    except (TypeError, ValueError):
        return "neither", f"Could not compare: adjudicator={adjudicator_value}"


# ---------------------------------------------------------------------------
# Log I/O
# ---------------------------------------------------------------------------

def load_json(path):
    with open(path, "r") as f:
        return json.load(f)


def save_json(data, path):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def load_disagreement_log():
    return load_json(AUDIT_DIR / "disagreement_log.json")


def save_disagreement_log(log):
    save_json(log, AUDIT_DIR / "disagreement_log.json")


def load_rejection_log():
    return load_json(AUDIT_DIR / "rejection_log.json")


def save_rejection_log(log):
    save_json(log, AUDIT_DIR / "rejection_log.json")


# ---------------------------------------------------------------------------
# Collect failures
# ---------------------------------------------------------------------------

def collect_failures_from_outputs(filter_report=None):
    """Scan extraction outputs and collect all hard failures grouped by report."""
    failures_by_report = {}

    for output_file in sorted(OUTPUT_DIR.glob("syndicate_*.json")):
        if filter_report and output_file.stem != filter_report:
            continue

        with open(output_file, "r") as f:
            data = json.load(f)

        validation = data.get("validation", {})
        if validation.get("passed", True):
            continue

        details = validation.get("hard_failure_details", [])
        if not details:
            continue

        failures_by_report[output_file.stem] = {
            "output_file": output_file,
            "details": details,
        }

    return failures_by_report


# ---------------------------------------------------------------------------
# Main adjudication loop (human-in-the-loop)
# ---------------------------------------------------------------------------

def adjudicate_all(filter_report=None, dry_run=False):
    """Interactive adjudication with human approval at every step."""
    failures = collect_failures_from_outputs(filter_report)

    if not failures:
        print("No hard failures found in extraction outputs.")
        return

    total_disputes = sum(len(v["details"]) for v in failures.values())
    print(f"Found {total_disputes} hard failures across {len(failures)} reports")
    print()

    if dry_run:
        for report_stem, info in failures.items():
            print(f"  {report_stem}:")
            for d in info["details"]:
                print(f"    {d['field']}: {d.get('type', '?')}")
        return

    dis_log = load_disagreement_log()
    rej_log = load_rejection_log()

    # Already-adjudicated entries (skip these)
    adjudicated = {
        (e["report"], e["field"])
        for e in dis_log["entries"]
        if e["status"] not in ("pending_review",)
    }

    total_cost = 0.0
    total_tokens = 0
    stopped = False

    for report_stem, info in failures.items():
        if stopped:
            break

        parts = report_stem.split("_")
        syndicate_num = int(parts[1])
        report_year = int(parts[2])

        pdf_path = find_source_pdf(report_stem)
        if pdf_path is None:
            print(f"  WARNING: No PDF found for {report_stem}, skipping")
            continue

        print(f"\n{'=' * 70}")
        print(f"Adjudicating: {report_stem}  ({len(info['details'])} disputes)")
        print(f"  PDF: {pdf_path.name}")
        print(f"{'=' * 70}")

        report_results = []

        for d in info["details"]:
            field = d["field"]

            if (report_stem, field) in adjudicated:
                print(f"  [{field}] Already adjudicated, skipping")
                continue

            gemini_val = d.get(GEMINI_MODEL, d.get("only_in", ""))
            gpt_val = d.get(OPENAI_MODEL, d.get("value", ""))

            print(f"\n  [{field}]")
            print(f"    Gemini: {gemini_val}")
            print(f"    GPT:    {gpt_val}")

            prompt = build_verification_prompt(
                field, gemini_val, gpt_val, syndicate_num, report_year
            )

            print(f"    Sending to {ADJUDICATOR_MODEL}...")
            try:
                result, tokens_in, tokens_out = call_adjudicator(
                    pdf_path, prompt,
                    syndicate_num=syndicate_num, report_year=report_year,
                    field=field,
                )
            except Exception as e:
                print(f"    ERROR calling adjudicator: {e}")
                print(f"    You can still make a manual decision.")
                print(f"      [g] Use Gemini value")
                print(f"      [o] Use GPT value")
                print(f"      [s] Stop script")
                choice = ask_human("    Your decision: ", ["g", "o", "s"])
                if choice == "s":
                    stopped = True
                    break
                final_model = GEMINI_MODEL if choice == "g" else OPENAI_MODEL
                final_value = gemini_val if choice == "g" else gpt_val
                report_results.append({
                    "field": field,
                    "decision_type": "override",
                    "final_model": final_model,
                    "final_value": final_value,
                    "human_reason": f"Manual override after adjudicator error: {e}",
                })
                continue

            total_tokens += tokens_in + tokens_out
            cost = tokens_in * 3.0 / 1_000_000 + tokens_out * 15.0 / 1_000_000
            total_cost += cost

            adj_value = result.get("correct_value")
            evidence = sanitize_for_json(str(result.get("evidence", "")))
            confidence = result.get("confidence", 0.0)

            correct_model, reason = determine_correct_model(
                field, adj_value, gemini_val, gpt_val
            )

            # Present to human and get decision
            decision_type, decision_data = present_adjudication(
                report_stem, field, gemini_val, gpt_val,
                adj_value, confidence, evidence, correct_model, reason,
            )

            if decision_type == "stop":
                # Save what we have so far before stopping
                save_disagreement_log(dis_log)
                save_rejection_log(rej_log)
                print(f"\n  Logs saved. Stopping.")
                print(f"  Re-run adjudicate.py to continue where you left off.")
                sys.exit(0)

            # Determine final model and value based on human decision
            if decision_type == "approve":
                final_model = decision_data  # correct_model from adjudicator
                final_value = adj_value
                human_reason = "Approved adjudicator recommendation"
                status = "resolved_model_error"
            elif decision_type == "override":
                final_model = decision_data  # GEMINI_MODEL or OPENAI_MODEL
                final_value = gemini_val if decision_data == GEMINI_MODEL else gpt_val
                human_reason = f"Human override: chose {final_model}"
                status = "resolved_human_override"
            elif decision_type == "override_value":
                final_model = "human"
                final_value = decision_data
                human_reason = f"Human provided custom value: {decision_data}"
                status = "resolved_human_override"

            report_results.append({
                "field": field,
                "decision_type": decision_type,
                "final_model": final_model,
                "final_value": final_value,
                "adjudicator_value": adj_value,
                "adjudicator_confidence": confidence,
                "evidence": evidence,
                "human_reason": human_reason,
            })

            # Update disagreement log immediately (so progress is saved)
            existing_entry = None
            for e in dis_log["entries"]:
                if e["report"] == report_stem and e["field"] == field:
                    existing_entry = e
                    break

            now = datetime.now(timezone.utc).strftime("%Y-%m-%d")

            if existing_entry:
                existing_entry["correct_model"] = final_model if final_model != "neither" else None
                existing_entry["manual_verification"] = (
                    f"Adjudicated by {ADJUDICATOR_MODEL}: {evidence}"
                )
                existing_entry["adjudicator_value"] = adj_value
                existing_entry["adjudicator_confidence"] = confidence
                existing_entry["human_decision"] = human_reason
                existing_entry["final_value"] = final_value
                existing_entry["action"] = human_reason
                existing_entry["status"] = status
                existing_entry["date"] = now
            else:
                next_num = max(
                    (int(e["id"].split("-")[1])
                     for e in dis_log["entries"]
                     if e["id"].startswith("ADJ-")),
                    default=0,
                ) + 1
                new_entry = {
                    "id": f"ADJ-{next_num:04d}",
                    "report": report_stem,
                    "field": field,
                    "gemini_value": gemini_val,
                    "gpt_value": gpt_val,
                    "correct_model": final_model if final_model != "neither" else None,
                    "adjudicator_value": adj_value,
                    "adjudicator_confidence": confidence,
                    "final_value": final_value,
                    "manual_verification": f"Adjudicated by {ADJUDICATOR_MODEL}: {evidence}",
                    "human_decision": human_reason,
                    "action": human_reason,
                    "prompt_version_before": None,
                    "prompt_version_after": None,
                    "status": status,
                    "date": now,
                }
                dis_log["entries"].append(new_entry)

            # Save after each field (so we don't lose progress)
            save_disagreement_log(dis_log)
            print(f"    Recorded: {human_reason}")

        if stopped:
            break

        # Report-level decision
        if not report_results:
            continue

        report_decision, report_data = present_report_decision(
            report_stem, syndicate_num, report_year, report_results
        )

        if report_decision == "stop":
            save_disagreement_log(dis_log)
            save_rejection_log(rej_log)
            print(f"\n  Logs saved. Stopping.")
            sys.exit(0)

        now = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # Remove any existing entry for this report in rejection log
        rej_log["entries"] = [
            e for e in rej_log["entries"] if e["report"] != report_stem
        ]

        if report_decision == "include":
            # Build override map
            overrides = {}
            for r in report_results:
                overrides[r["field"]] = {
                    "model": r.get("final_model"),
                    "value": r.get("final_value"),
                }
            rej_entry = {
                "report": report_stem,
                "syndicate": syndicate_num,
                "year": report_year,
                "rejected": False,
                "reason": "Included with human-approved overrides for disputed fields",
                "overrides": overrides,
                "status": "included_with_override",
                "human_approved": True,
                "date": now,
            }
            rej_log["entries"].append(rej_entry)

        elif report_decision == "exclude":
            rej_entry = {
                "report": report_stem,
                "syndicate": syndicate_num,
                "year": report_year,
                "rejected": True,
                "reason": report_data,  # human-provided reason
                "status": "excluded",
                "human_approved": True,
                "date": now,
            }
            rej_log["entries"].append(rej_entry)

        save_rejection_log(rej_log)
        print(f"  Rejection log updated for {report_stem}")

    # Final save
    save_disagreement_log(dis_log)
    save_rejection_log(rej_log)

    print(f"\n{'=' * 70}")
    print("ADJUDICATION SUMMARY")
    print(f"{'=' * 70}")
    print(f"  Reports reviewed: {len(failures)}")
    print(f"  Total tokens:     {total_tokens:,}")
    print(f"  Total cost:       ${total_cost:.4f}")
    print(f"  Disagreement log: {AUDIT_DIR / 'disagreement_log.json'}")
    print(f"  Rejection log:    {AUDIT_DIR / 'rejection_log.json'}")


# ---------------------------------------------------------------------------
# Pattern analysis and prompt fix proposals (human-in-the-loop)
# ---------------------------------------------------------------------------

def analyse_patterns():
    """Analyse adjudicated disagreements for systematic patterns.

    Groups failures by (field, wrong_model). When >= 2 reports share the same
    failure type, asks Claude to draft a prompt fix, then presents it to the
    human for approval before recording.
    """
    dis_log = load_disagreement_log()

    resolved = [
        e for e in dis_log["entries"]
        if e["status"] in ("resolved_model_error", "resolved_human_override", "resolved_prompt_fix")
        and e.get("correct_model")
    ]

    if not resolved:
        print("No resolved disagreements to analyse.")
        return

    patterns = defaultdict(list)
    for e in resolved:
        field_base = e["field"].split("[")[0]
        wrong_model = (
            OPENAI_MODEL if e["correct_model"] == GEMINI_MODEL
            else GEMINI_MODEL if e["correct_model"] == OPENAI_MODEL
            else "unknown"
        )
        if wrong_model == "unknown":
            continue
        key = (field_base, wrong_model)
        patterns[key].append(e)

    print(f"{'=' * 70}")
    print("PATTERN ANALYSIS")
    print(f"{'=' * 70}")
    print()

    pv_path = SPEC_DIR / "prompt_versions.json"
    prompt_versions = load_json(pv_path)

    existing_triggers = set()
    for v in prompt_versions["versions"]:
        if v.get("reports_triggering_change"):
            for r in v["reports_triggering_change"]:
                existing_triggers.add(r)

    proposals = []
    for (field_base, wrong_model), entries in sorted(patterns.items()):
        reports = [e["report"] for e in entries]
        new_reports = [r for r in reports if r not in existing_triggers]

        print(f"  Pattern: {field_base} -- {wrong_model} wrong in {len(entries)} cases")
        print(f"    Reports: {', '.join(reports)}")

        if len(entries) < 2:
            print(f"    -> Isolated incident, no prompt fix needed")
            print()
            continue

        if not new_reports:
            print(f"    -> All reports already triggered a prompt fix")
            print()
            continue

        print(f"    -> SYSTEMATIC: {len(entries)} occurrences, {len(new_reports)} new")
        proposals.append({
            "field": field_base,
            "wrong_model": wrong_model,
            "count": len(entries),
            "reports": reports,
            "new_reports": new_reports,
            "entries": entries,
        })
        print()

    if not proposals:
        print("No new systematic patterns found. Prompt is stable.")
        return

    print(f"\nGenerating {len(proposals)} prompt fix proposal(s)...\n")

    import anthropic
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    current_version = prompt_versions["versions"][-1]["version"]
    next_major, next_minor = current_version.rsplit(".", 1)
    next_version = f"{next_major}.{int(next_minor) + 1}"

    for proposal in proposals:
        examples = []
        for e in proposal["entries"][:5]:
            examples.append(
                f"  Report: {e['report']}\n"
                f"    Field: {e['field']}\n"
                f"    {GEMINI_MODEL}: {e.get('gemini_value', '?')}\n"
                f"    {OPENAI_MODEL}: {e.get('gpt_value', '?')}\n"
                f"    Correct: {e.get('correct_model', '?')}\n"
                f"    Evidence: {str(e.get('manual_verification', '?'))[:200]}"
            )

        meta_prompt = (
            f"You are helping improve an LLM extraction prompt for Lloyd's syndicate reports.\n\n"
            f"The following systematic error has been identified -- {proposal['wrong_model']} "
            f"gets the field '{proposal['field']}' wrong in {proposal['count']} reports:\n\n"
            + "\n\n".join(examples) +
            f"\n\nThe current extraction prompt already includes instructions about this field. "
            f"Based on the pattern of errors, draft a SHORT (1-3 sentence) additional instruction "
            f"that would prevent this specific class of error.\n\n"
            f"Reply with ONLY valid JSON:\n"
            f'{{"instruction": "<the prompt addition>", '
            f'"description": "<1-line description of the fix>", '
            f'"rationale": "<why the current prompt is insufficient>"}}'
        )

        response = client.messages.create(
            model=ADJUDICATOR_MODEL,
            max_tokens=512,
            messages=[{"role": "user", "content": meta_prompt}],
        )

        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        try:
            fix = json.loads(raw)
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse Claude prompt-fix JSON: {e}\nRaw: {raw[:200]}")
            continue

        # Present to human for approval
        decision_type, decision_data = present_prompt_proposal(proposal, fix)

        if decision_type == "stop":
            save_json(prompt_versions, pv_path)
            save_disagreement_log(dis_log)
            print(f"\n  Logs saved. Stopping.")
            sys.exit(0)

        if decision_type == "reject":
            print(f"    Proposal rejected, skipping.")
            continue

        # Apply edits if the human modified the instruction
        if decision_type == "edit":
            fix["instruction"] = decision_data
            fix["description"] = fix["description"] + " (human-edited)"

        # Record the approved proposal
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        new_version_entry = {
            "version": next_version,
            "date": now,
            "description": fix["description"],
            "changes": fix["instruction"],
            "trigger": fix["rationale"],
            "reports_triggering_change": proposal["new_reports"],
            "status": "approved",
            "proposed_by": ADJUDICATOR_MODEL,
            "human_approved": True,
            "human_approved_date": now,
        }
        prompt_versions["versions"].append(new_version_entry)

        # Update disagreement log entries
        for e in proposal["entries"]:
            for log_entry in dis_log["entries"]:
                if log_entry["report"] == e["report"] and log_entry["field"] == e["field"]:
                    log_entry["prompt_fix_proposed"] = next_version
                    log_entry["proposed_instruction"] = fix["instruction"]
                    log_entry["human_approved_fix"] = True

        print(f"    Approved as version {next_version}")

        # Bump for next proposal
        next_minor_int = int(next_version.rsplit(".", 1)[1]) + 1
        next_version = f"{next_major}.{next_minor_int}"

    save_json(prompt_versions, pv_path)
    save_disagreement_log(dis_log)

    print(f"\n  Prompt versions updated: {pv_path}")
    print(f"  Disagreement log updated: {AUDIT_DIR / 'disagreement_log.json'}")
    print()
    print(f"  Next steps for each approved fix:")
    print(f"    1. Add the instruction to build_prompt() in test_gemini.py")
    print(f"    2. Bump PROMPT_VERSION in test_gemini.py to match")
    print(f"    3. Delete affected output files and re-run test_gemini.py")


def apply_prompt_fix(version):
    """Mark a proposed prompt fix as accepted and list reports to re-extract."""
    pv_path = SPEC_DIR / "prompt_versions.json"
    prompt_versions = load_json(pv_path)

    target = None
    for v in prompt_versions["versions"]:
        if v["version"] == version:
            target = v
            break

    if target is None:
        print(f"Version {version} not found in prompt_versions.json")
        return

    if target.get("status") not in ("proposed", "approved"):
        print(f"Version {version} status is '{target.get('status')}' -- nothing to do")
        return

    target["status"] = "accepted"
    target["accepted_date"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    save_json(prompt_versions, pv_path)

    print(f"Version {version} marked as accepted.")
    print(f"Affected reports to re-extract:")
    for r in target.get("reports_triggering_change", []):
        print(f"  {r}")
    print()
    print(f"Next steps:")
    print(f"  1. Add the instruction to build_prompt() in test_gemini.py:")
    print(f"     {target['changes']}")
    print(f"  2. Set PROMPT_VERSION = '{version}' in test_gemini.py")
    print(f"  3. Delete affected output files and re-run:")
    for r in target.get("reports_triggering_change", []):
        output = OUTPUT_DIR / f"{r}.json"
        print(f"     del {output}")
    print(f"     python test_gemini.py")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    propose_fixes = "--propose-fixes" in sys.argv
    filter_report = None

    for i, arg in enumerate(sys.argv):
        if arg == "--report" and i + 1 < len(sys.argv):
            filter_report = sys.argv[i + 1]
        if arg == "--accept" and i + 1 < len(sys.argv):
            apply_prompt_fix(sys.argv[i + 1])
            sys.exit(0)

    if propose_fixes:
        analyse_patterns()
    else:
        adjudicate_all(filter_report=filter_report, dry_run=dry_run)
