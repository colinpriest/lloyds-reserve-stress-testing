"""
Interactive script to manually override the status of a syndicate extraction JSON.

Usage:
    python manual_override.py
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

EXTRACTION_DIR = Path("pdf_extraction")

STATUSES = {
    "1": {
        "name": "Extracted",
        "description": "Normal extraction with cross-validated data",
        "fields": {
            "excluded": False,
            "no_triangle_data": False,
            "first_year_syndicate": False,
            "manual_override_status": "extracted",
        },
        "remove_fields": ["exclusion_reason"],
    },
    "2": {
        "name": "Excluded",
        "description": "No usable data — recommend non-inclusion in analysis",
        "fields": {
            "excluded": True,
            "no_triangle_data": True,
            "manual_override_status": "excluded",
        },
    },
    "3": {
        "name": "First Year Syndicate",
        "description": "Too few underwriting years for PYD analysis",
        "fields": {
            "first_year_syndicate": True,
            "manual_override_status": "first_year_syndicate",
        },
    },
    "4": {
        "name": "In Run-off",
        "description": "Syndicate in run-off — no new business being written",
        "fields": {
            "manual_override_status": "in_runoff",
        },
    },
    "5": {
        "name": "Skipped",
        "description": "Deliberately skipped — not relevant for analysis",
        "fields": {
            "excluded": True,
            "manual_override_status": "skipped",
        },
    },
    "6": {
        "name": "Incomplete",
        "description": "Extraction exists but is known to be incomplete or unreliable",
        "fields": {
            "manual_override_status": "incomplete",
        },
    },
    "7": {
        "name": "Needs Re-extraction",
        "description": "Flagged for re-extraction in a future pipeline run",
        "fields": {
            "manual_override_status": "needs_reextraction",
        },
    },
    "8": {
        "name": "Manual Review Required",
        "description": "Data present but requires human review before use",
        "fields": {
            "manual_override_status": "manual_review_required",
        },
    },
}


def get_current_status(data):
    """Determine the current status from the JSON data."""
    if data.get("manual_override_status"):
        for key, status in STATUSES.items():
            if status["fields"].get("manual_override_status") == data["manual_override_status"]:
                return status["name"]
        return f"Custom: {data['manual_override_status']}"
    if data.get("first_year_syndicate"):
        return "First Year Syndicate"
    if data.get("no_triangle_data") or data.get("excluded"):
        return "Excluded"
    if "models" in data and data.get("validation", {}).get("passed"):
        return "Extracted (validated)"
    if "models" in data:
        return "Extracted"
    return "Unknown"


def display_current_file(filepath, data):
    """Show a summary of the current file state."""
    syndicate = data.get("syndicate") or next(
        (v.get("syndicate") for v in data.get("models", {}).values() if isinstance(v, dict)),
        "?"
    )
    year = data.get("year") or next(
        (v.get("year") for v in data.get("models", {}).values() if isinstance(v, dict)),
        "?"
    )
    status = get_current_status(data)
    validation = data.get("validation", {})

    print(f"\n{'=' * 60}")
    print(f"  File:       {filepath.name}")
    print(f"  Syndicate:  {syndicate}")
    print(f"  Year:       {year}")
    print(f"  Status:     {status}")
    if validation:
        print(f"  Validation: {'PASSED' if validation.get('passed') else 'FAILED'} "
              f"({validation.get('hard_failures', '?')} hard failures)")
    if data.get("exclusion_reason"):
        print(f"  Reason:     {data['exclusion_reason']}")
    if data.get("manual_override_reason"):
        print(f"  Override:   {data['manual_override_reason']}")
    print(f"{'=' * 60}")


def main():
    print("\n=== Lloyd's Extraction Manual Override ===\n")

    # Step 1: Get syndicate number
    syndicate = input("Enter syndicate number: ").strip()
    if not syndicate.isdigit():
        print("Error: syndicate number must be numeric.")
        sys.exit(1)

    # Step 2: Get year
    year = input("Enter report year (2014-2024): ").strip()
    if not year.isdigit() or not (2014 <= int(year) <= 2024):
        print("Error: year must be between 2014 and 2024.")
        sys.exit(1)

    # Step 3: Find the file
    filename = f"syndicate_{syndicate}_{year}.json"
    filepath = EXTRACTION_DIR / filename

    if not filepath.exists():
        print(f"\nFile not found: {filepath}")
        create = input("Create a new override file? (y/n): ").strip().lower()
        if create != "y":
            print("Aborted.")
            sys.exit(0)
        data = {
            "extraction_timestamp": datetime.now(timezone.utc).isoformat(),
            "spec": {
                "prompt_version": "manual",
                "field_definitions_version": "1.0",
                "tolerance_rules_version": "1.0",
            },
            "source_file": f"syndicate_reports/pdfs/syndicate_{syndicate}_{year}.pdf",
            "syndicate": int(syndicate),
            "year": int(year),
        }
    else:
        with open(filepath, "r") as f:
            data = json.load(f)

    # Show current state
    display_current_file(filepath, data)

    # Step 4: Show status choices
    print("\nAvailable statuses:\n")
    for key, status in STATUSES.items():
        print(f"  [{key}] {status['name']}")
        print(f"      {status['description']}")
    print(f"\n  [0] Cancel — make no changes")

    choice = input("\nSelect new status: ").strip()

    if choice == "0":
        print("No changes made.")
        sys.exit(0)

    if choice not in STATUSES:
        print(f"Error: invalid choice '{choice}'.")
        sys.exit(1)

    selected = STATUSES[choice]

    # Step 5: Ask for optional reason
    reason = input(f"\nReason for override (optional, press Enter to skip): ").strip()

    # Step 6: Apply changes
    for field, value in selected["fields"].items():
        data[field] = value

    for field in selected.get("remove_fields", []):
        data.pop(field, None)

    data["manual_override_timestamp"] = datetime.now(timezone.utc).isoformat()
    if reason:
        data["manual_override_reason"] = reason

    # Step 7: Confirm
    print(f"\n--- Confirm Override ---")
    print(f"  File:       {filepath.name}")
    print(f"  New status: {selected['name']}")
    if reason:
        print(f"  Reason:     {reason}")
    print(f"  Fields set: {selected['fields']}")

    confirm = input("\nApply this override? (y/n): ").strip().lower()
    if confirm != "y":
        print("Aborted. No changes made.")
        sys.exit(0)

    # Step 8: Write
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2)

    print(f"\nOverride applied to {filepath}")


if __name__ == "__main__":
    main()
