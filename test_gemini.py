"""LLM PDF/HTML extraction: Gemini vs GPT-5-mini with inline adjudication.

Extracts structured reserve data from each Lloyd's syndicate report using two
independent LLMs (Gemini and GPT), compares outputs field-by-field, and when
they disagree on material fields, immediately pauses to adjudicate:

  1. Sends the PDF to a third model (Claude) for targeted verification
  2. Presents the finding to the human operator
  3. Human approves, overrides (pick a model or enter custom value), or stops
  4. All decisions are recorded in the audit trail

Usage:
    python test_gemini.py              # run with inline adjudication on failures
    python test_gemini.py --clean      # wipe outputs, re-run from scratch
    python test_gemini.py --batch      # old behaviour: no interactive adjudication
"""

import os
import re
import sys
import json
import base64
import hashlib
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv
from google import genai
from google.genai.types import GenerateContentConfig
from openai import OpenAI

from adjudicate import (
    ask_human,
    build_verification_prompt,
    call_adjudicator,
    sanitize_for_json,
    determine_correct_model,
    present_adjudication,
    present_report_decision,
    load_disagreement_log,
    save_disagreement_log,
    load_rejection_log,
    save_rejection_log,
    ADJUDICATOR_MODEL,
)

load_dotenv()

# Pricing per 1M tokens (USD)
PRICING = {
    "gemini-2.5-flash": {"input": 0.30, "output": 2.50},
    "gemini-3-flash":   {"input": 0.50, "output": 3.00},
    "gpt-5-mini":       {"input": 0.25, "output": 2.00},
}

# Standard Lloyd's LOBs (from config.py)
LLOYDS_LOBS = [
    "Property", "Casualty", "Marine", "Energy", "Motor",
    "Aviation", "Reinsurance - Property", "Reinsurance - Casualty",
    "Reinsurance - Specialty", "Professional Lines", "Accident & Health",
    "Cyber", "Aggregate", "Treaty",
]

# Standard causal categories (from config.py CauseCategory enum)
CAUSAL_CATEGORIES = [
    "Natural catastrophe events",
    "Man-made catastrophe / large losses",
    "Social inflation / litigation trends",
    "Economic inflation / claims cost inflation",
    "Regulatory changes",
    "Court rulings / legal developments",
    "Ogden discount rate",
    "COVID-19 / pandemic effects",
    "Geopolitical events",
    "Favorable claims development",
    "Adverse claims development",
    "Reinsurance recoveries",
    "IBNR recalibration",
    "Reserve methodology change",
    "Large loss development",
    "Other",
]

REPORTS_DIR = Path("syndicate_reports/pdfs")
OUTPUT_DIR = Path("pdf_extraction")
HTML_PDF_CACHE = Path("pdf_extraction/html_converted")
SPEC_DIR = Path("pdf_extraction/spec")
AUDIT_DIR = Path("pdf_extraction/audit")

GEMINI_MODEL = "gemini-2.5-flash"
OPENAI_MODEL = "gpt-5-mini"

# Frozen spec versions -- bump these when spec files change
PROMPT_VERSION = "1.6"
FIELD_DEFINITIONS_VERSION = "1.0"
TOLERANCE_RULES_VERSION = "1.0"


def convert_html_to_pdf(html_path):
    """Convert HTML file to PDF using Playwright. Returns path to cached PDF."""
    HTML_PDF_CACHE.mkdir(parents=True, exist_ok=True)
    pdf_path = HTML_PDF_CACHE / f"{html_path.stem}.pdf"
    if pdf_path.exists():
        print(f"  Using cached PDF: {pdf_path.name}")
        return pdf_path

    print(f"  Converting {html_path.name} to PDF via Playwright...")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(f"file:///{html_path.resolve().as_posix()}")
        page.pdf(path=str(pdf_path), format="A4", print_background=True)
        browser.close()
    print(f"  Converted: {pdf_path.name} ({pdf_path.stat().st_size / 1024:.0f} KB)")
    return pdf_path


def discover_reports():
    """Find all syndicate report files (PDF and HTML), sorted by name."""
    files = sorted(
        f for f in REPORTS_DIR.iterdir()
        if f.suffix.lower() in (".pdf", ".html", ".htm")
        and f.stem.startswith("syndicate_")
    )
    return files


def parse_report_filename(report_path):
    """Extract syndicate number and year from filename."""
    parts = report_path.stem.split("_")
    return int(parts[1]), int(parts[2])


def build_prompt(syndicate_num, report_year):
    """Build the shared extraction prompt."""
    return f"""Extract reserve data from this Lloyd's syndicate annual report and return ONLY valid JSON (no markdown fences).

Use these EXACT standard Lloyd's lines of business names where applicable:
{json.dumps(LLOYDS_LOBS)}

Use these standard causal categories:
{json.dumps(CAUSAL_CATEGORIES)}

Return this JSON structure:

{{
  "syndicate": {syndicate_num},
  "year": {report_year},
  "opening_reserves_gbp_m": <opening GROSS CLAIMS OUTSTANDING (also called "gross claims reserves") at start of year, in millions as a number. This is ONLY the claims reserve — do NOT include provisions for unearned premiums. Look in the Technical Reserves note or Balance Sheet for "Gross claims outstanding" or "Claims outstanding - gross amount". null if not found>,
  "opening_reserves_page": <page number where found>,
  "opening_reserves_confidence": <0.0 to 1.0>,
  "prior_year_development_gbp_m": <amount in millions as a SIGNED number: NEGATIVE for releases, POSITIVE for strengthenings/deteriorations. IMPORTANT: Use the figure from the "Movement in prior year's provision for claims outstanding" note or the narrative text that explicitly states the prior year release/strengthening amount (e.g. "released £77.4m of technical reserves in respect of prior periods"). Do NOT use the "Movement in provision" line from the Technical Reserves reconciliation table, which includes current year movements. null if not found>,
  "prior_year_development_pct": <as percentage of opening gross claims outstanding, NEGATIVE for releases, POSITIVE for strengthenings, null if not calculable>,
  "direction": "<release|strengthening|flat|mixed>",
  "prior_year_movement_page": <page number>,
  "prior_year_movement_confidence": <0.0 to 1.0>,
  "exact_reserve_text": "<copy VERBATIM the sentence(s) from the document that describe the prior year reserve movement>",
  "primary_causes": ["<map each cause to the closest standard causal category above>"],
  "specific_events": ["<named events e.g. 'Hurricane Ian 2022', empty list if none>"],
  "specific_years_affected": [<list of prior accident years mentioned as affected, empty list if none>],
  "prior_year_events": [
    {{
      "event_name": "<name of the event, e.g. 'Hurricane Katrina', 'Deepwater Horizon', 'Ogden rate change'>",
      "event_year": <year the event occurred>,
      "impact_description": "<how this event affected reserves, e.g. 'adverse development on 2011 Thai floods', 'release of reserves following benign claims experience'>",
      "lobs_affected": ["<standard Lloyd's LOB names affected>"],
      "amount_gbp_m": <signed impact in millions if quantified: negative=release, positive=strengthening, null if not quantified>,
      "confidence": <0.0 to 1.0>
    }}
  ],
  "named_events": [
    {{
      "event_name": "<specific name of the event, e.g. 'Hurricane Odile', 'Sewol ferry disaster', 'Japan snowfall'>",
      "event_year": <year the event occurred>,
      "event_type": "<natural_catastrophe|man_made|liability|political|other>",
      "net_loss_gbp_m": <net loss to the syndicate in millions if quantified, null if not>,
      "loss_description": "<how the report describes the impact, e.g. 'contained within catastrophe budget', 'net loss below £10m'>",
      "lobs_affected": ["<standard Lloyd's LOB names affected>"],
      "page": <page number where mentioned>,
      "confidence": <0.0 to 1.0>
    }}
  ],
  "standardized_narrative": "<one paragraph summary of the reserve movement, its causes, and affected lines>",
  "raw_causal_phrases": ["<copy exact causal phrases from the document verbatim>"],
  "lob_movements": [
    {{
      "line_of_business": "<standard Lloyd's LOB name from list above>",
      "direction": "<release|strengthening>",
      "amount_gbp_m": <signed amount in millions: negative=release, positive=strengthening, null if not quantified>,
      "percentage": <signed percentage if available, null otherwise>,
      "confidence": <0.0 to 1.0>
    }}
  ],
  "gross_premiums_written_gbp_m": <total in millions as a number>,
  "gross_premium_mix": [
    {{
      "line_of_business": "<EXACT regulatory/statutory class name as printed in the Segmental Analysis note — copy verbatim, e.g. 'Marine, aviation and transport', 'Fire and other damage to property', 'Third party liability', 'Miscellaneous', 'Reinsurance'. Do NOT rename or map these to standard Lloyd's LOBs>",
      "amount_gbp_m": <amount in millions as a number>,
      "percentage_of_total": <percentage as a number e.g. 47.6>
    }}
  ],
  "gross_premium_page": <page number>,
  "gross_premium_confidence": <0.0 to 1.0>,
  "currency": "<GBP, USD, or EUR - whichever the report's financial statements are denominated in. Report the amounts in the NATIVE currency, do NOT convert to GBP>",
  "data_quality_notes": "<any caveats about data availability or extraction uncertainty>"
}}

Rules:
- All monetary amounts MUST be plain numbers in millions (no currency symbols, no 'm' suffix)
- Releases are NEGATIVE (e.g. a £77.4m release = -77.4)
- Strengthenings/deteriorations are POSITIVE (e.g. a £10m strengthening = 10.0)
- For confidence: 1.0 = explicitly stated, 0.8 = calculated from stated values, 0.5 = inferred, 0.0 = not found
- Map line of business names to the standard Lloyd's LOBs where possible. If a syndicate has a "Treaty" division (reinsurance accepted), map it to "Treaty" — do NOT split it into Reinsurance - Property/Casualty/Specialty unless the report explicitly breaks it down by those sub-categories.
- Map causes to the standard causal categories where possible
- For exact_reserve_text: copy verbatim, do not paraphrase
- IMPORTANT — opening_reserves_gbp_m: Use ONLY gross claims outstanding (claims reserves). Do NOT include unearned premium provisions. These are different items in the balance sheet / technical reserves note.
- IMPORTANT — prior_year_development_gbp_m: The correct source is the note titled "Movement in prior year's provision for claims outstanding" or the narrative text that explicitly quantifies the prior year release/strengthening (e.g. "released £X of technical reserves in respect of prior periods"). Do NOT use the "Movement in provision" row from the Technical Reserves reconciliation table — that row includes BOTH current year AND prior year movements combined.
- IMPORTANT — sign convention for "surplus/(deficit)" language: When a report says "A surplus/(deficit) run-off deviation of (X) million", the PARENTHESES around the number indicate a DEFICIT. A deficit means prior reserves were INSUFFICIENT, which is ADVERSE development = STRENGTHENING (POSITIVE sign). Example: "surplus/(deficit) of (3.0) million" means a 3.0m deficit = prior_year_development_gbp_m: +3.0, direction: "strengthening". Conversely, an unparenthesized number means a surplus = release = NEGATIVE sign.
- IMPORTANT — gross_premium_mix: Use the REGULATORY segmental analysis from the Notes to the Accounts. Copy the line of business names EXACTLY as printed (e.g. "Marine, aviation and transport", "Fire and other damage to property", "Third party liability", "Miscellaneous", "Reinsurance"). Do NOT rename them to standard Lloyd's LOB names. Do NOT split combined categories into separate entries. Do NOT use the underwriter's internal divisional breakdown.
- IMPORTANT — gross_premium_mix with "Direct insurance" and "Reinsurance acceptances" sub-tables: Some segmental analysis notes split gross premiums into "Direct insurance" and "Reinsurance acceptances" sub-tables, each with their own LOB categories (e.g. both may have "Fire and other damage to property"). In this case, list the individual Direct insurance categories with their amounts, then add a SINGLE consolidated "Reinsurance acceptances" line with the total of all reinsurance accepted premiums. Do NOT list the individual reinsurance sub-categories separately (they would create duplicate LOB names). The total should still equal gross_premiums_written_gbp_m.
- IMPORTANT — gross_premium_mix: prefer DIVISIONAL TOTALS over regulatory sub-categories. When the report contains BOTH a regulatory segmental analysis (with fine-grained statutory classes like "Marine, aviation and transport", "Fire and other damage to property") AND a divisional/business class summary (e.g. "Marine", "Property", "Specialty", "Political Lines", "Treaty"), use the DIVISIONAL summary. The divisional breakdown aggregates across direct and reinsurance business to give the TOTAL premium per business class, which is what we need. The regulatory segmental analysis often shows only the direct insurance component for each statutory class, understating the true LOB total. Each entry in gross_premium_mix should represent the TOTAL premium for that business class (direct + reinsurance combined). The amounts must still sum to gross_premiums_written_gbp_m.
- prior_year_events: List specific named events from years BEFORE the report year ({report_year}) that the document mentions as affecting claims or reserves. For a {report_year} report, any event from {report_year - 1} or earlier is a prior year event. Look in the Technical Reserves note for "{report_year - 1} events" subsections — these are prior year events. Also look in the Underwriter's Report for references to events from prior years (e.g. deterioration on older losses). Include both adverse and favourable impacts.
- named_events: List ALL specific named catastrophe events, large losses, and significant incidents mentioned ANYWHERE in the document — including the Technical Reserves note (which often has "{report_year-1} events" and "{report_year} events" subsections), the Underwriter's Report divisional reviews, and the Managing Agent's Report. Include events from both the current year AND prior years. Look for: hurricanes, typhoons, earthquakes, floods, snowfall, hailstorms, tornadoes, vessel losses, industrial accidents, terrorist attacks, and any other specifically named loss events. Empty list only if genuinely no named events appear in the document."""


def sanitize_ascii(obj):
    """Recursively replace non-ASCII characters with ASCII equivalents."""
    if isinstance(obj, str):
        # Common Unicode → ASCII replacements
        obj = obj.replace("\u00a3", "GBP ")  # £
        obj = obj.replace("\u20ac", "EUR ")   # €
        obj = obj.replace("\u0024", "$")      # $
        obj = obj.replace("\u2013", "-")      # en dash
        obj = obj.replace("\u2014", "-")      # em dash
        obj = obj.replace("\u2018", "'")      # left single quote
        obj = obj.replace("\u2019", "'")      # right single quote
        obj = obj.replace("\u201c", '"')      # left double quote
        obj = obj.replace("\u201d", '"')      # right double quote
        obj = obj.replace("\u2026", "...")     # ellipsis
        obj = obj.replace("\u00b1", "+/-")    # plus-minus
        obj = obj.replace("\u00d7", "x")      # multiplication sign
        # Strip any remaining non-ASCII
        obj = re.sub(r'[^\x00-\x7F]', '', obj)
        return obj
    elif isinstance(obj, dict):
        return {sanitize_ascii(k): sanitize_ascii(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [sanitize_ascii(item) for item in obj]
    return obj


def add_metadata(data, model, report_path, content_hash):
    """Add pipeline metadata to extraction result."""
    data["source_type"] = "syndicate"
    data["source_file"] = str(report_path)
    data["content_hash"] = content_hash
    data["standardized_at"] = datetime.now(timezone.utc).isoformat()
    data["standardization_model"] = model
    return data


def parse_json_response(text):
    """Parse JSON from LLM response, stripping markdown fences if present."""
    raw = text.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    return json.loads(raw)


def extract_with_gemini(report_path, file_bytes, content_hash, syndicate_num, report_year, model=GEMINI_MODEL):
    """Extract using Google Gemini."""
    print(f"  [{model}] Uploading {report_path.name}...")
    client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))
    uploaded_file = client.files.upload(file=report_path)

    print(f"  [{model}] Extracting...")
    response = client.models.generate_content(
        model=model,
        contents=[uploaded_file, build_prompt(syndicate_num, report_year)],
        config=GenerateContentConfig(temperature=0.0),
    )

    data = sanitize_ascii(parse_json_response(response.text))
    data = add_metadata(data, model, report_path, content_hash)

    usage = response.usage_metadata
    input_tokens = usage.prompt_token_count
    output_tokens = usage.candidates_token_count
    total_tokens = usage.total_token_count

    prices = PRICING[model]
    cost = input_tokens * prices["input"] / 1_000_000 + output_tokens * prices["output"] / 1_000_000

    data["_extraction_meta"] = {
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "cost_usd": round(cost, 6),
    }

    print(f"  [{model}] Done. {input_tokens:,} in / {output_tokens:,} out. ${cost:.6f}")
    return data


def extract_with_openai(report_path, file_bytes, content_hash, syndicate_num, report_year, model=OPENAI_MODEL):
    """Extract using OpenAI GPT with file upload."""
    print(f"  [{model}] Sending {report_path.name}...")
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    file_b64 = base64.b64encode(file_bytes).decode("utf-8")
    suffix = report_path.suffix.lower()
    if suffix == ".pdf":
        mime = "application/pdf"
    else:
        mime = "text/html"

    response = client.responses.create(
        model=model,
        input=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_file",
                        "filename": report_path.name,
                        "file_data": f"data:{mime};base64,{file_b64}",
                    },
                    {
                        "type": "input_text",
                        "text": build_prompt(syndicate_num, report_year),
                    },
                ],
            }
        ],
    )

    data = sanitize_ascii(parse_json_response(response.output_text))
    data = add_metadata(data, model, report_path, content_hash)

    input_tokens = response.usage.input_tokens
    output_tokens = response.usage.output_tokens
    total_tokens = input_tokens + output_tokens

    prices = PRICING[model]
    cost = input_tokens * prices["input"] / 1_000_000 + output_tokens * prices["output"] / 1_000_000

    data["_extraction_meta"] = {
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "cost_usd": round(cost, 6),
    }

    print(f"  [{model}] Done. {input_tokens:,} in / {output_tokens:,} out. ${cost:.6f}")
    return data


# ---------------------------------------------------------------------------
# Comparison logic
# ---------------------------------------------------------------------------

SKIP_FIELDS = {
    "source_type", "source_file", "content_hash",
    "standardized_at", "standardization_model", "_extraction_meta",
}


def compare_results(a, b, model_a, model_b):
    """Compare two extraction results and return discrepancies."""
    discrepancies = []
    all_keys = sorted(set(list(a.keys()) + list(b.keys())) - SKIP_FIELDS)

    for key in all_keys:
        val_a = a.get(key, "<MISSING>")
        val_b = b.get(key, "<MISSING>")

        if key in ("lob_movements", "gross_premium_mix"):
            _compare_list_of_dicts(key, val_a, val_b, model_a, model_b, discrepancies)
        elif key in ("primary_causes", "specific_events", "specific_years_affected", "raw_causal_phrases"):
            _compare_lists(key, val_a, val_b, model_a, model_b, discrepancies)
        elif key in ("exact_reserve_text", "standardized_narrative", "data_quality_notes"):
            if str(val_a).strip() != str(val_b).strip():
                discrepancies.append({
                    "field": key, "type": "text_difference",
                    model_a: _truncate(str(val_a), 120),
                    model_b: _truncate(str(val_b), 120),
                })
        else:
            if val_a != val_b:
                discrepancies.append({
                    "field": key, "type": "value_mismatch",
                    model_a: val_a, model_b: val_b,
                })

    return discrepancies


def check_tolerance(discrepancies, model_a, model_b):
    """Classify discrepancies as tolerated or hard failures. Returns (passed, tolerated, hard_failures)."""
    hard_failures = []
    tolerated = []
    for d in discrepancies:
        field = d["field"]
        is_tolerated = (
            d["type"] == "text_difference"
            or any(t in field for t in ("page", "confidence", "Page", "Confidence"))
            or any(field.startswith(p) for p in (
                "named_events", "prior_year_events", "raw_causal_phrases",
                "specific_events", "specific_years_affected",
                "lob_movements", "primary_causes",
            ))
            or _is_numeric_near(d.get(model_a), d.get(model_b), rel_tol=0.005)
        )
        if is_tolerated:
            tolerated.append(d)
        else:
            hard_failures.append(d)

    return len(hard_failures) == 0, tolerated, hard_failures


def resolve_computed_fields(hard_failures, result_a, result_b, model_a, model_b):
    """Auto-resolve derived fields when the inputs they depend on agree.

    prior_year_development_pct = prior_year_development_gbp_m / opening_reserves_gbp_m * 100

    If both models agree on the numerator and denominator, compute the correct
    percentage and mark whichever model is closer as tolerated.

    Returns (remaining_hard_failures, auto_resolved).
    """
    remaining = []
    resolved = []

    for d in hard_failures:
        if d["field"] == "prior_year_development_pct":
            pyd_a = result_a.get("prior_year_development_gbp_m")
            pyd_b = result_b.get("prior_year_development_gbp_m")
            open_a = result_a.get("opening_reserves_gbp_m")
            open_b = result_b.get("opening_reserves_gbp_m")

            # Both models must agree on the inputs (within tolerance)
            if (pyd_a is not None and pyd_b is not None
                    and open_a is not None and open_b is not None
                    and _is_numeric_near(pyd_a, pyd_b)
                    and _is_numeric_near(open_a, open_b)
                    and float(open_a) != 0):
                computed = round(float(pyd_a) / float(open_a) * 100, 2)
                print(f"  Auto-resolved prior_year_development_pct: "
                      f"{pyd_a} / {open_a} * 100 = {computed}%")

                # Check which model is closer
                val_a = d.get(model_a)
                val_b = d.get(model_b)
                try:
                    err_a = abs(float(val_a) - computed) if val_a is not None else 999
                    err_b = abs(float(val_b) - computed) if val_b is not None else 999
                except (TypeError, ValueError):
                    err_a = err_b = 999

                closer = model_a if err_a <= err_b else model_b
                closer_val = val_a if err_a <= err_b else val_b
                print(f"    Computed: {computed}, {model_a}: {val_a}, {model_b}: {val_b}")
                print(f"    {closer} is closer (error: {min(err_a, err_b):.4f})")

                d["auto_resolved"] = True
                d["computed_value"] = computed
                d["closer_model"] = closer
                resolved.append(d)
                continue

        remaining.append(d)

    return remaining, resolved


def _print_field_context(field, gem_data, gpt_data):
    """Print supporting fields from both models to give the human context.

    For example, if the disputed field is prior_year_development_pct, show
    both models' opening_reserves and prior_year_development_gbp_m so the
    human can verify the calculation.
    """
    # Map disputed fields to the related fields the human needs to see
    context_map = {
        "prior_year_development_pct": [
            "opening_reserves_gbp_m",
            "prior_year_development_gbp_m",
        ],
        "prior_year_development_gbp_m": [
            "opening_reserves_gbp_m",
            "direction",
            "exact_reserve_text",
        ],
        "direction": [
            "prior_year_development_gbp_m",
            "exact_reserve_text",
        ],
    }

    # For gross_premium_mix sub-fields, show the total premiums
    field_base = field.split("[")[0]
    if field_base == "gross_premium_mix":
        context_map[field] = ["gross_premiums_written_gbp_m", "currency"]

    related = context_map.get(field) or context_map.get(field_base)
    if not related:
        return

    print(f"    --- Supporting context ---")
    for rf in related:
        g_val = gem_data.get(rf)
        o_val = gpt_data.get(rf)
        agree = ""
        if g_val is not None and o_val is not None:
            if _is_numeric_near(g_val, o_val):
                agree = " (AGREE)"
            elif str(g_val).strip().lower() == str(o_val).strip().lower():
                agree = " (AGREE)"
            else:
                agree = " (DISAGREE)"
        # Truncate long text fields
        g_str = str(g_val)[:120] if g_val is not None else "null"
        o_str = str(o_val)[:120] if o_val is not None else "null"
        print(f"    {rf}{agree}:")
        print(f"      Gemini: {g_str}")
        print(f"      GPT:    {o_str}")
    print(f"    ---")


def print_discrepancies(discrepancies, model_a, model_b):
    """Print discrepancies to console."""
    if not discrepancies:
        print("    No discrepancies.")
        return
    for i, d in enumerate(discrepancies, 1):
        print(f"    {i}. [{d['type']}] {d['field']}")
        if d["type"] == "list_extra":
            print(f"       Only in {d['only_in']}: {_truncate(str(d['value']), 100)}")
        elif d["type"] == "text_difference":
            print(f"       {model_a}: {d[model_a]}")
            print(f"       {model_b}: {d[model_b]}")
        else:
            print(f"       {model_a}: {d.get(model_a, '')}")
            print(f"       {model_b}: {d.get(model_b, '')}")


def _compare_lists(field, a, b, model_a, model_b, discrepancies):
    """Compare two lists of strings (set-based for unordered lists)."""
    if not isinstance(a, list):
        a = []
    if not isinstance(b, list):
        b = []

    set_a = set(str(x) for x in a)
    set_b = set(str(x) for x in b)

    for item in sorted(set_a - set_b):
        discrepancies.append({
            "field": field, "type": "list_extra",
            "only_in": model_a, "value": item,
        })
    for item in sorted(set_b - set_a):
        discrepancies.append({
            "field": field, "type": "list_extra",
            "only_in": model_b, "value": item,
        })


def _is_zero_entry(item):
    """Check if a premium mix / LOB movement entry has zero or null amounts."""
    amt = item.get("amount_gbp_m", 0) or 0
    pct = item.get("percentage_of_total", 0) or 0
    return abs(float(amt)) < 0.01 and abs(float(pct)) < 0.01


def _is_subtotal_entry(item):
    """Check if an entry is a subtotal row (e.g. 'Total direct insurance')."""
    lob = str(item.get("line_of_business", "")).lower()
    return lob.startswith("total") or lob.startswith("sub-total") or lob.startswith("subtotal")


def _compare_list_of_dicts(field, a, b, model_a, model_b, discrepancies):
    """Compare two lists of dicts by matching on line_of_business key."""
    if not isinstance(a, list):
        a = []
    if not isinstance(b, list):
        b = []

    key_field = "line_of_business"
    index_a = {item.get(key_field, f"__idx{i}"): item for i, item in enumerate(a)}
    index_b = {item.get(key_field, f"__idx{i}"): item for i, item in enumerate(b)}

    all_keys = sorted(set(list(index_a.keys()) + list(index_b.keys())))
    for k in all_keys:
        if k not in index_a:
            # Tolerate if the extra entry has zero amount or is a subtotal row
            if _is_zero_entry(index_b[k]) or _is_subtotal_entry(index_b[k]):
                continue
            discrepancies.append({
                "field": f"{field}[{k}]", "type": "list_extra",
                "only_in": model_b, "value": json.dumps(index_b[k]),
            })
        elif k not in index_b:
            if _is_zero_entry(index_a[k]) or _is_subtotal_entry(index_a[k]):
                continue
            discrepancies.append({
                "field": f"{field}[{k}]", "type": "list_extra",
                "only_in": model_a, "value": json.dumps(index_a[k]),
            })
        else:
            item_a, item_b = index_a[k], index_b[k]
            for sub_key in sorted(set(list(item_a.keys()) + list(item_b.keys()))):
                va = item_a.get(sub_key, "<MISSING>")
                vb = item_b.get(sub_key, "<MISSING>")
                if va != vb:
                    discrepancies.append({
                        "field": f"{field}[{k}].{sub_key}",
                        "type": "value_mismatch",
                        model_a: va, model_b: vb,
                    })


def _truncate(s, max_len):
    """Truncate string for display."""
    return s[:max_len] + "..." if len(s) > max_len else s


def _is_numeric_near(a, b, rel_tol=0.005, abs_tol=0.05):
    """Check if two values are both numeric and within tolerance.

    Uses relative tolerance for large values, absolute tolerance for near-zero.
    """
    try:
        # Treat None/null vs 0.0 as equivalent (both mean "not found / zero")
        a_is_none = a is None or a == "None"
        b_is_none = b is None or b == "None"
        if a_is_none and b_is_none:
            return True
        if a_is_none:
            a = 0.0
        if b_is_none:
            b = 0.0
        fa, fb = float(a), float(b)
        if fa == fb:
            return True
        diff = abs(fa - fb)
        if diff <= abs_tol:
            return True
        denom = max(abs(fa), abs(fb), 1e-9)
        return diff / denom <= rel_tol
    except (TypeError, ValueError):
        return False


def append_to_disagreement_log(report_stem, hard_failures):
    """Append hard failure entries to the disagreement log for later manual adjudication."""
    log_path = AUDIT_DIR / "disagreement_log.json"
    with open(log_path, "r") as f:
        log = json.load(f)

    existing_ids = {e["id"] for e in log["entries"]}
    next_num = max(
        (int(e["id"].split("-")[1]) for e in log["entries"] if e["id"].startswith("RUN-")),
        default=0,
    ) + 1

    for d in hard_failures:
        entry_id = f"RUN-{next_num:04d}"
        if any(
            e["report"] == report_stem and e["field"] == d["field"]
            and e["status"] != "pending_review"
            for e in log["entries"]
        ):
            continue  # already adjudicated in a prior dev entry
        # Skip if already logged as pending for this report+field
        if any(
            e["report"] == report_stem and e["field"] == d["field"]
            for e in log["entries"]
        ):
            continue

        entry = {
            "id": entry_id,
            "report": report_stem,
            "field": d["field"],
            "gemini_value": d.get(GEMINI_MODEL, d.get("only_in", "")),
            "gpt_value": d.get(OPENAI_MODEL, d.get("value", "")),
            "correct_model": None,
            "manual_verification": None,
            "action": None,
            "prompt_version_before": PROMPT_VERSION,
            "prompt_version_after": None,
            "status": "pending_review",
            "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        }
        log["entries"].append(entry)
        next_num += 1

    with open(log_path, "w") as f:
        json.dump(log, f, indent=2)


def write_run_manifest(run_stats):
    """Write the final run manifest summarising this extraction run."""
    manifest = {
        "run_id": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "run_timestamp": datetime.now(timezone.utc).isoformat(),
        "spec": {
            "prompt_version": PROMPT_VERSION,
            "field_definitions_version": FIELD_DEFINITIONS_VERSION,
            "tolerance_rules_version": TOLERANCE_RULES_VERSION,
        },
        "models": {
            "model_a": GEMINI_MODEL,
            "model_b": OPENAI_MODEL,
        },
        "corpus": {
            "reports_dir": str(REPORTS_DIR),
            "total_reports_found": run_stats["total_found"],
            "reports_processed_this_run": run_stats["processed"],
            "reports_passed": run_stats["passed"],
            "reports_failed": run_stats["failed"],
            "reports_errored": run_stats["errored"],
            "reports_skipped_already_done": run_stats["already_done"],
        },
        "costs": {
            "total_tokens": run_stats["total_tokens"],
            "total_cost_usd": round(run_stats["total_cost"], 4),
        },
        "output_dir": str(OUTPUT_DIR),
    }

    manifest_path = AUDIT_DIR / "run_manifest.json"
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"  Run manifest written: {manifest_path}")


def process_one_report(report_path):
    """Process a single report with both models. Returns (output_data, passed, hard_failures)."""
    syndicate_num, report_year = parse_report_filename(report_path)

    # Convert HTML to PDF if needed
    actual_path = report_path
    if report_path.suffix.lower() in (".html", ".htm"):
        actual_path = convert_html_to_pdf(report_path)

    with open(actual_path, "rb") as f:
        file_bytes = f.read()
    content_hash = hashlib.sha256(file_bytes).hexdigest()

    # Extract with both models (use converted PDF path but keep original as source)
    result_gemini = extract_with_gemini(
        actual_path, file_bytes, content_hash, syndicate_num, report_year
    )
    result_openai = extract_with_openai(
        actual_path, file_bytes, content_hash, syndicate_num, report_year
    )

    # Compare
    discrepancies = compare_results(result_gemini, result_openai, GEMINI_MODEL, OPENAI_MODEL)
    passed, tolerated, hard_failures = check_tolerance(discrepancies, GEMINI_MODEL, OPENAI_MODEL)

    # Auto-resolve computed fields: prior_year_development_pct can be derived
    # from opening_reserves_gbp_m and prior_year_development_gbp_m when those agree.
    hard_failures, auto_resolved = resolve_computed_fields(
        hard_failures, result_gemini, result_openai, GEMINI_MODEL, OPENAI_MODEL
    )
    tolerated.extend(auto_resolved)
    passed = len(hard_failures) == 0

    # Cost
    meta_g = result_gemini.get("_extraction_meta", {})
    meta_o = result_openai.get("_extraction_meta", {})
    total_cost = meta_g.get("cost_usd", 0) + meta_o.get("cost_usd", 0)
    total_tokens = meta_g.get("total_tokens", 0) + meta_o.get("total_tokens", 0)

    output_data = {
        "extraction_timestamp": datetime.now(timezone.utc).isoformat(),
        "spec": {
            "prompt_version": PROMPT_VERSION,
            "field_definitions_version": FIELD_DEFINITIONS_VERSION,
            "tolerance_rules_version": TOLERANCE_RULES_VERSION,
        },
        "source_file": str(report_path),
        "models": {
            GEMINI_MODEL: result_gemini,
            OPENAI_MODEL: result_openai,
        },
        "total_cost_usd": round(total_cost, 6),
        "total_tokens": total_tokens,
        "validation": {
            "passed": passed,
            "total_discrepancies": len(discrepancies),
            "within_tolerance": len(tolerated),
            "hard_failures": len(hard_failures),
            "hard_failure_details": [
                {
                    "field": d["field"],
                    "type": d["type"],
                    GEMINI_MODEL: d.get(GEMINI_MODEL, d.get("only_in", "")),
                    OPENAI_MODEL: d.get(OPENAI_MODEL, d.get("value", "")),
                }
                if d["type"] != "list_extra"
                else {
                    "field": d["field"],
                    "type": d["type"],
                    "only_in": d["only_in"],
                    "value": d["value"],
                }
                for d in hard_failures
            ],
        },
    }

    return output_data, passed, discrepancies, hard_failures


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)

    # Print spec versions at startup
    print(f"Prompt version: {PROMPT_VERSION}")
    print(f"Field definitions: {FIELD_DEFINITIONS_VERSION}")
    print(f"Tolerance rules: {TOLERANCE_RULES_VERSION}")
    print(f"Models: {GEMINI_MODEL} vs {OPENAI_MODEL}")
    print()

    reports = discover_reports()
    print(f"Found {len(reports)} reports in {REPORTS_DIR}")

    # --clean flag: delete all existing outputs to force re-run under current spec
    if "--clean" in sys.argv:
        existing = list(OUTPUT_DIR.glob("syndicate_*.json"))
        if existing:
            print(f"  --clean: deleting {len(existing)} existing output files...")
            for f in existing:
                f.unlink()
            print(f"  Deleted. All reports will be re-processed.")

    # Skip already-processed reports
    already_done = {f.stem for f in OUTPUT_DIR.glob("syndicate_*.json")}
    to_process = [r for r in reports if r.stem not in already_done]
    print(f"Already processed: {len(already_done)}, remaining: {len(to_process)}")

    if not to_process:
        print("Nothing to do.")
        sys.exit(0)

    # Running totals
    run_total_cost = 0.0
    run_total_tokens = 0
    run_processed = 0
    run_passed = 0
    run_failed = 0
    run_errored = 0

    for i, report_path in enumerate(to_process, 1):
        syndicate_num, report_year = parse_report_filename(report_path)
        print(f"\n{'=' * 70}")
        print(f"[{i}/{len(to_process)}] Syndicate {syndicate_num} / {report_year}  ({report_path.name})")
        print(f"{'=' * 70}")

        try:
            output_data, passed, discrepancies, hard_failures = process_one_report(report_path)
        except Exception as e:
            print(f"  ERROR: {e}")
            print(f"  Skipping {report_path.name} and continuing...")
            run_errored += 1
            continue

        run_processed += 1
        run_total_cost += output_data["total_cost_usd"]
        run_total_tokens += output_data["total_tokens"]

        # Write output JSON
        output_file = OUTPUT_DIR / f"{report_path.stem}.json"
        with open(output_file, "w") as f:
            json.dump(output_data, f, indent=2)

        status = "PASSED" if passed else "FAILED"
        print(f"  Validation: {status}  ({len(discrepancies)} discrepancies, {len(hard_failures)} hard failures)")
        print(f"  Written: {output_file}")

        if not passed:
            run_failed += 1
            print(f"\n  HARD FAILURES:")
            print_discrepancies(hard_failures, GEMINI_MODEL, OPENAI_MODEL)

            batch_mode = "--batch" in sys.argv

            if batch_mode:
                # Old behaviour: log and continue (no interactive adjudication)
                append_to_disagreement_log(
                    report_path.stem,
                    output_data["validation"]["hard_failure_details"],
                )
                if "--stop-on-failure" in sys.argv:
                    print(f"\n  STOPPING -- hard failure on {report_path.name}")
                    break
                else:
                    print(f"  (batch mode -- continuing)")
            else:
                # --- Inline adjudication (human-in-the-loop) ---
                dis_log = load_disagreement_log()
                rej_log = load_rejection_log()

                # Find source PDF for adjudicator
                actual_pdf = report_path
                if report_path.suffix.lower() in (".html", ".htm"):
                    cached = HTML_PDF_CACHE / f"{report_path.stem}.pdf"
                    if cached.exists():
                        actual_pdf = cached

                report_results = []
                stopped = False

                for d in output_data["validation"]["hard_failure_details"]:
                    field = d["field"]
                    gemini_val = d.get(GEMINI_MODEL, d.get("only_in", ""))
                    gpt_val = d.get(OPENAI_MODEL, d.get("value", ""))

                    # Skip if already adjudicated in a prior run
                    already = any(
                        e["report"] == report_path.stem and e["field"] == field
                        and e["status"] not in ("pending_review",)
                        for e in dis_log["entries"]
                    )
                    if already:
                        print(f"\n  [{field}] Already adjudicated, skipping")
                        continue

                    print(f"\n  [{field}]")
                    print(f"    Gemini: {gemini_val}")
                    print(f"    GPT:    {gpt_val}")

                    # Show supporting context from both models
                    gem_data = output_data["models"][GEMINI_MODEL]
                    gpt_data = output_data["models"][OPENAI_MODEL]
                    _print_field_context(field, gem_data, gpt_data)

                    prompt = build_verification_prompt(
                        field, gemini_val, gpt_val, syndicate_num, report_year
                    )
                    print(f"    Sending to {ADJUDICATOR_MODEL}...")

                    try:
                        result, tokens_in, tokens_out = call_adjudicator(actual_pdf, prompt)
                    except Exception as e:
                        print(f"    ERROR calling adjudicator: {e}")
                        print(f"    You can still make a manual decision.")
                        print(f"      [g] Use Gemini value")
                        print(f"      [o] Use GPT value")
                        print(f"      [s] Stop script")
                        choice = ask_human("    Your decision: ", ["g", "o", "s"])
                        if choice == "s":
                            save_disagreement_log(dis_log)
                            save_rejection_log(rej_log)
                            print(f"\n  Logs saved. Stopping.")
                            write_run_manifest({
                                "total_found": len(reports),
                                "already_done": len(already_done),
                                "processed": run_processed,
                                "passed": run_passed,
                                "failed": run_failed,
                                "errored": run_errored,
                                "total_tokens": run_total_tokens,
                                "total_cost": run_total_cost,
                                "stopped_early": True,
                            })
                            sys.exit(0)
                        final_model = GEMINI_MODEL if choice == "g" else OPENAI_MODEL
                        final_value = gemini_val if choice == "g" else gpt_val
                        report_results.append({
                            "field": field,
                            "decision_type": "override",
                            "final_model": final_model,
                            "final_value": final_value,
                        })
                        continue

                    adj_cost = tokens_in * 3.0 / 1_000_000 + tokens_out * 15.0 / 1_000_000
                    run_total_cost += adj_cost
                    run_total_tokens += tokens_in + tokens_out

                    adj_value = result.get("correct_value")
                    evidence = sanitize_for_json(str(result.get("evidence", "")))
                    confidence = result.get("confidence", 0.0)

                    correct_model, reason = determine_correct_model(
                        field, adj_value, gemini_val, gpt_val
                    )

                    decision_type, decision_data = present_adjudication(
                        report_path.stem, field, gemini_val, gpt_val,
                        adj_value, confidence, evidence, correct_model, reason,
                    )

                    if decision_type == "stop":
                        save_disagreement_log(dis_log)
                        save_rejection_log(rej_log)
                        print(f"\n  Logs saved. Stopping.")
                        write_run_manifest({
                            "total_found": len(reports),
                            "already_done": len(already_done),
                            "processed": run_processed,
                            "passed": run_passed,
                            "failed": run_failed,
                            "errored": run_errored,
                            "total_tokens": run_total_tokens,
                            "total_cost": run_total_cost,
                            "stopped_early": True,
                        })
                        sys.exit(0)

                    # Determine final model/value
                    if decision_type == "approve":
                        final_model = decision_data
                        final_value = adj_value
                        human_reason = "Approved adjudicator recommendation"
                        status = "resolved_model_error"
                    elif decision_type == "override":
                        final_model = decision_data
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
                    })

                    # Update disagreement log immediately
                    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                    existing_entry = None
                    for e in dis_log["entries"]:
                        if e["report"] == report_path.stem and e["field"] == field:
                            existing_entry = e
                            break

                    if existing_entry:
                        existing_entry["correct_model"] = final_model if final_model != "neither" else None
                        existing_entry["manual_verification"] = (
                            f"Adjudicated by {ADJUDICATOR_MODEL}: {evidence}"
                        )
                        existing_entry["adjudicator_value"] = adj_value
                        existing_entry["adjudicator_confidence"] = confidence
                        existing_entry["human_decision"] = human_reason
                        existing_entry["final_value"] = sanitize_for_json(str(final_value))
                        existing_entry["action"] = human_reason
                        existing_entry["status"] = status
                        existing_entry["date"] = now
                    else:
                        next_adj_num = max(
                            (int(e["id"].split("-")[1])
                             for e in dis_log["entries"]
                             if e["id"].startswith("ADJ-")),
                            default=0,
                        ) + 1
                        new_entry = {
                            "id": f"ADJ-{next_adj_num:04d}",
                            "report": report_path.stem,
                            "field": field,
                            "gemini_value": sanitize_for_json(str(gemini_val)),
                            "gpt_value": sanitize_for_json(str(gpt_val)),
                            "correct_model": final_model if final_model != "neither" else None,
                            "adjudicator_value": adj_value,
                            "adjudicator_confidence": confidence,
                            "final_value": sanitize_for_json(str(final_value)),
                            "manual_verification": f"Adjudicated by {ADJUDICATOR_MODEL}: {evidence}",
                            "human_decision": human_reason,
                            "action": human_reason,
                            "prompt_version_before": PROMPT_VERSION,
                            "prompt_version_after": None,
                            "status": status,
                            "date": now,
                        }
                        dis_log["entries"].append(new_entry)

                    save_disagreement_log(dis_log)
                    print(f"    Recorded: {human_reason}")

                # Report-level decision (if any fields were adjudicated)
                if report_results:
                    report_decision, report_data = present_report_decision(
                        report_path.stem, syndicate_num, report_year, report_results
                    )

                    if report_decision == "stop":
                        save_disagreement_log(dis_log)
                        save_rejection_log(rej_log)
                        print(f"\n  Logs saved. Stopping.")
                        write_run_manifest({
                            "total_found": len(reports),
                            "already_done": len(already_done),
                            "processed": run_processed,
                            "passed": run_passed,
                            "failed": run_failed,
                            "errored": run_errored,
                            "total_tokens": run_total_tokens,
                            "total_cost": run_total_cost,
                            "stopped_early": True,
                        })
                        sys.exit(0)

                    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")

                    # Remove any prior entry for this report in rejection log
                    rej_log["entries"] = [
                        e for e in rej_log["entries"]
                        if e["report"] != report_path.stem
                    ]

                    if report_decision == "include":
                        overrides = {}
                        for r in report_results:
                            overrides[r["field"]] = {
                                "model": r.get("final_model"),
                                "value": sanitize_for_json(str(r.get("final_value", ""))),
                            }
                        rej_log["entries"].append({
                            "report": report_path.stem,
                            "syndicate": syndicate_num,
                            "year": report_year,
                            "rejected": False,
                            "reason": "Included with human-approved overrides for disputed fields",
                            "overrides": overrides,
                            "status": "included_with_override",
                            "human_approved": True,
                            "date": now,
                        })
                    elif report_decision == "exclude":
                        rej_log["entries"].append({
                            "report": report_path.stem,
                            "syndicate": syndicate_num,
                            "year": report_year,
                            "rejected": True,
                            "reason": report_data,
                            "status": "excluded",
                            "human_approved": True,
                            "date": now,
                        })

                    save_rejection_log(rej_log)
                    print(f"  Rejection log updated for {report_path.stem}")
        else:
            run_passed += 1

    # Summary
    print(f"\n{'=' * 70}")
    print("RUN SUMMARY")
    print(f"{'=' * 70}")
    print(f"  Processed:  {run_processed}")
    print(f"  Passed:     {run_passed}")
    print(f"  Failed:     {run_failed}")
    print(f"  Errored:    {run_errored}")
    print(f"  Remaining:  {len(to_process) - run_processed - run_errored}")
    print(f"  Tokens:     {run_total_tokens:,}")
    print(f"  Cost:       ${run_total_cost:.4f}")

    # Write run manifest
    write_run_manifest({
        "total_found": len(reports),
        "already_done": len(already_done),
        "processed": run_processed,
        "passed": run_passed,
        "failed": run_failed,
        "errored": run_errored,
        "total_tokens": run_total_tokens,
        "total_cost": run_total_cost,
    })
