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


def present_adjudication(report_stem, field, gemini_val, gpt_val, adj_result, confidence, evidence, correct_model, reason):
    """Present the adjudicator's finding and ask the human what to do.

    Returns one of:
        ("approve", correct_model)    -- accept adjudicator recommendation
        ("override", model_name)      -- use a specific model's value
        ("override_value", value)     -- use a custom value
        ("stop", None)                -- halt the script
    """
    print()
    print(f"    {'~' * 60}")
    print(f"    ADJUDICATOR FINDING for {report_stem} / {field}")
    print(f"    {'~' * 60}")
    print(f"    Gemini says:      {gemini_val}")
    print(f"    GPT says:         {gpt_val}")
    print(f"    Adjudicator says: {adj_result}")
    print(f"    Confidence:       {confidence}")
    print(f"    Evidence:         {evidence[:200]}")
    print(f"    Recommendation:   {correct_model} -- {reason}")
    print()
    print(f"    What would you like to do?")
    print(f"      [a] Approve adjudicator recommendation")
    print(f"      [g] Override: use Gemini value")
    print(f"      [o] Override: use GPT value")
    print(f"      [v] Override: enter a custom value")
    print(f"      [s] Stop script (to make substantive changes)")
    print()

    choice = ask_human("    Your decision: ", ["a", "g", "o", "v", "s"])

    if choice == "a":
        return ("approve", correct_model)
    elif choice == "g":
        return ("override", GEMINI_MODEL)
    elif choice == "o":
        return ("override", OPENAI_MODEL)
    elif choice == "v":
        custom = ask_human("    Enter custom value: ")
        return ("override_value", custom)
    elif choice == "s":
        return ("stop", None)


def present_report_decision(report_stem, syndicate_num, report_year, report_results):
    """After adjudicating all fields for a report, ask what to do with it.

    Returns one of:
        ("include", override_model)   -- include in dataset, use override_model for disputed fields
        ("exclude", reason)           -- reject from dataset
        ("stop", None)                -- halt the script
    """
    resolved = [r for r in report_results if r.get("decision_type") in ("approve", "override", "override_value")]
    unresolved = [r for r in report_results if r.get("decision_type") not in ("approve", "override", "override_value")]

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


def build_verification_prompt(field, gemini_value, gpt_value, syndicate_num, report_year):
    """Build a targeted prompt to verify a specific disputed field."""

    if field == "direction":
        return (
            f"This is a Lloyd's syndicate {syndicate_num} annual report for year-end {report_year}.\n\n"
            f"Two LLMs disagree on the DIRECTION of prior year reserve development:\n"
            f"  - Model A says: {gemini_value}\n"
            f"  - Model B says: {gpt_value}\n\n"
            f"Find the section discussing prior year reserve movement (usually in the "
            f"'Movement in prior year's provision for claims outstanding' note, or in the "
            f"Managing Agent's / Underwriter's Report). The key question:\n\n"
            f"Did prior year reserves RELEASE (surplus -- reserves were more than needed) "
            f"or STRENGTHEN (deficit -- reserves were insufficient, additional provision needed)?\n\n"
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
            f"Find the 'Movement in prior year's provision for claims outstanding' note, "
            f"or the narrative text that explicitly states the prior year release/strengthening amount.\n\n"
            f"Sign convention:\n"
            f"  - NEGATIVE = release (reserves were sufficient, surplus returned)\n"
            f"  - POSITIVE = strengthening (reserves were insufficient, additional provision)\n\n"
            f"IMPORTANT: If the report uses 'surplus/(deficit)' language:\n"
            f"  - Parenthesized numbers like (3.0) = deficit = POSITIVE (strengthening)\n"
            f"  - Unparenthesized numbers like 3.0 = surplus = NEGATIVE (release)\n\n"
            f"Do NOT use the 'Movement in provision' row from the Technical Reserves "
            f"reconciliation table -- that includes current year movements.\n\n"
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
            f"Find the GROSS CLAIMS OUTSTANDING at the start of the year (i.e. prior year-end). "
            f"This is ONLY claims reserves -- do NOT include unearned premium provisions. "
            f"Look in the Technical Reserves note or Balance Sheet for 'Claims outstanding - gross amount' "
            f"or 'Gross claims outstanding'.\n\n"
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


def call_adjudicator(pdf_path, prompt):
    """Send PDF + verification prompt to Claude for adjudication."""
    import anthropic

    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    with open(pdf_path, "rb") as f:
        pdf_bytes = f.read()
    pdf_b64 = base64.b64encode(pdf_bytes).decode("utf-8")

    response = client.messages.create(
        model=ADJUDICATOR_MODEL,
        max_tokens=1024,
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

    # Try direct parse first
    try:
        return json.loads(raw), tokens_in, tokens_out
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
                return json.loads(candidate), tokens_in, tokens_out
            except json.JSONDecodeError:
                continue

    # Try to find JSON object anywhere in the response
    brace_start = raw.find("{")
    brace_end = raw.rfind("}")
    if brace_start != -1 and brace_end > brace_start:
        try:
            return json.loads(raw[brace_start:brace_end + 1]), tokens_in, tokens_out
        except json.JSONDecodeError:
            pass

    raise ValueError(f"Could not parse JSON from adjudicator response: {raw[:300]}")


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
                result, tokens_in, tokens_out = call_adjudicator(pdf_path, prompt)
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
        fix = json.loads(raw)

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
