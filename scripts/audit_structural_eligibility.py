"""Build source-evidence candidates for the first-year/structural filing audit.

This script never treats the extraction pipeline's ``first_year_syndicate`` flag as
an eligibility decision.  It reopens every source, records the cached deterministic
triangle and provisions evidence, and identifies filings that need a page-level
nil-versus-missing decision.  The reviewed decisions live in
``pdf_extraction/audit/structural_eligibility_audit.csv``; this script supplies the
reproducible source inventory used to make and test them.

Run from the repository root::

    python scripts/audit_structural_eligibility.py
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import test_gemini as pipeline  # noqa: E402


RECORD_DIR = ROOT / "pdf_extraction"
OUTPUT = RECORD_DIR / "audit" / "structural_eligibility_candidates.json"
KEYWORDS = re.compile(
    r"claims development|technical provisions|claims outstanding|underwriting year|"
    r"prior year|prior underwriting|inception|commenced underwriting",
    re.I,
)
INCEPTION_TERMS = re.compile(
    r"commenced underwriting|began underwriting|established for the|first year of underwriting|"
    r"first year of account|second year of underwriting|second year of account|new syndicate",
    re.I,
)
TRIANGLE_TERMS = re.compile(r"claims development(?: table| tables)?|underwriting year", re.I)


TRANSCRIPTION = RECORD_DIR / "audit" / "structural_eligibility_transcription.json"


def structural_records() -> list[tuple[Path, dict]]:
    """Return the records under audit: the committed first-year stubs, and every record the audit has
    transcribed. The second set matters twice. A stub the audit has decided eligible is written from
    the ledger and is no longer a stub (1840/2022, whose printed nil was retained in 11b1bc36): before
    round 62 only the stubs were selected, so once 1840/2022 was retained the script found 69 and
    refused to run on the committed corpus. And an unread record the audit restates as a stub (third
    cycle of round 62: 24 records whose filings state that the syndicate began in the report year or
    the year before) is transcribed before it is restated, so it must be selectable while it is still
    written as having no deterministic reading."""
    audited = expected_names()
    records = []
    for path in sorted(RECORD_DIR.glob("syndicate_*_*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if record.get("first_year_syndicate") is True or path.name in audited:
            records.append((path, record))
    return records


def expected_names() -> set:
    """The records whose filing pages have been transcribed: the selection is the committed stubs
    and these, and it must reproduce them by name, so a stub that has not been transcribed, or a
    transcribed record with no committed file, stops the script. A record is added to the audit by
    transcribing its pages first: the re-extraction of 29 September 2026 made 1985/2024 a stub (its
    triangle holds UW2023-2024 only), and the audit went from 70 records to 71; the 24 unread records
    of the third cycle took it to 95. Before that this compared a count with the ledger's."""
    return set(json.loads(TRANSCRIPTION.read_text(encoding="utf-8"))["records"])


def source_path(record: dict) -> Path:
    raw = str(record.get("source_file", "")).replace("\\", "/")
    return ROOT / raw


def relevant_text_pages(path: Path) -> list[dict]:
    """Compact, page-numbered source excerpts for human review."""
    if path.suffix.lower() not in {".pdf"}:
        text = re.sub(r"<[^>]+>", " ", path.read_text(encoding="utf-8", errors="ignore"))
        text = " ".join(text.split())
        hits = [m.start() for m in KEYWORDS.finditer(text)]
        return [
            {"page": None, "excerpt": text[max(0, i - 300):i + 1200]}
            for i in hits[:8]
        ]

    import fitz

    out = []
    with fitz.open(path) as doc:
        for page_index, page in enumerate(doc):
            text = page.get_text("text")
            if not KEYWORDS.search(text):
                continue
            compact = " ".join(text.split())
            out.append({"page": page_index + 1, "excerpt": compact[:5000]})
    return out


def source_text_pages(path: Path) -> list[dict]:
    """Page text, preferring the committed OCR cache for scanned filings."""
    cache = RECORD_DIR / "ocr_page_cache" / f"{path.stem}.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    if path.suffix.lower() != ".pdf":
        text = re.sub(r"<[^>]+>", " ", path.read_text(encoding="utf-8", errors="ignore"))
        return [{"page": None, "text": " ".join(text.split())}]
    import fitz
    with fitz.open(path) as doc:
        return [{"page": i + 1, "text": page.get_text("text")}
                for i, page in enumerate(doc)]


def evidence_windows(path: Path) -> dict:
    """Compact page-numbered windows around inception and triangle language."""
    out = {"inception_mentions": [], "claims_development_mentions": []}
    for page in source_text_pages(path):
        text = " ".join(str(page.get("text") or "").split())
        for key, pattern in (("inception_mentions", INCEPTION_TERMS),
                             ("claims_development_mentions", TRIANGLE_TERMS)):
            match = pattern.search(text)
            if not match:
                continue
            start = max(0, match.start() - 400)
            out[key].append({"page": page.get("page"),
                             "excerpt": text[start:match.start() + 3000]})
    return out


def inspect_record(record_path: Path, record: dict) -> dict:
    syndicate, year = int(record["syndicate"]), int(record["year"])
    source = source_path(record)
    result = {
        "file": record_path.name,
        "syndicate": syndicate,
        "year": year,
        "source_file": str(source.relative_to(ROOT)).replace("\\", "/"),
        "source_exists": source.exists(),
        "source_kind": source.suffix.lower().lstrip("."),
        "stored_reason": record.get("reason"),
        "stored_inception_year": record.get("inception_year"),
        "source_pages": [],
    }
    if not source.exists():
        result["candidate_status"] = "source_missing"
        return result

    result["source_pages"] = relevant_text_pages(source)
    result.update(evidence_windows(source))
    if source.suffix.lower() != ".pdf":
        result["candidate_status"] = "manual_review_html"
        return result

    try:
        rag = pipeline.extract_pyd_from_relevant_pages(source, year)
    except RuntimeError as exc:
        # a table-cache miss: refused in cache-only mode, and in offline mode as a call it would make
        if "table backends are cache-only" not in str(exc) and not (
                "offline mode" in str(exc) and "Document Intelligence" in str(exc)):
            raise
        result["candidate_status"] = "manual_review_no_table_cache"
        result["table_cache_error"] = str(exc)
        return result
    triangle = rag.get("triangle") or {}
    years = [int(v) for v in triangle.get("underwriting_years", [])]
    mature = sorted(v for v in years if v <= year - pipeline.PYD_EXCLUDED_RECENT_UW_YEARS)
    provisions = rag.get("adobe_provisions") or {}
    result.update({
        "triangle_basis": triangle.get("type"),
        "triangle_page": triangle.get("source_page"),
        "triangle_underwriting_years": years,
        "triangle_development_rows": triangle.get("development_rows"),
        "triangle_row_labels": triangle.get("row_labels"),
        "mature_underwriting_years": mature,
        "pipeline_pyd_gbp_m": rag.get("pyd"),
        "pipeline_pyd_details": rag.get("pyd_details"),
        "pipeline_method": rag.get("method"),
        "opening_gross_claims_outstanding_gbp_m": (
            rag.get("opening_reserves_from_movement")
            if rag.get("opening_reserves_from_movement") is not None
            else provisions.get("opening_gross_claims_outstanding")
        ),
        "provisions_gross_prior_year_claims_gbp_m": provisions.get("gross_prior_year_claims"),
        "provisions_page": provisions.get("source_page"),
    })
    if rag.get("pyd") is not None:
        result["candidate_status"] = "eligible_observed"
    elif mature:
        result["candidate_status"] = "manual_review_nil_vs_missing"
    elif years:
        result["candidate_status"] = "no_mature_underwriting_year"
    else:
        result["candidate_status"] = "manual_review_no_parsed_triangle"
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--evidence-only", action="store_true",
                        help="refresh source evidence in an existing candidate file without table extraction")
    args = parser.parse_args()

    # This audit is cache-only and must not invoke page-image model inference.
    pipeline.HAS_PDF2IMAGE = False
    rows = structural_records()
    names, expected = {path.name for path, _ in rows}, expected_names()
    if names != expected:
        raise SystemExit("the committed records under audit are not the transcribed ones: "
                         f"not transcribed {sorted(names - expected)}, not selected {sorted(expected - names)}")
    existing = {}
    if args.evidence_only:
        if not args.output.exists():
            raise SystemExit("--evidence-only requires an existing candidate file")
        existing = {r["file"]: r for r in json.loads(
            args.output.read_text(encoding="utf-8"))["records"]}
    candidates = []
    for index, (path, record) in enumerate(rows, 1):
        print(f"[{index:02d}/{len(rows)}] {path.name}")
        if args.evidence_only:
            result = existing[path.name]
            result.update(evidence_windows(source_path(record)))
            candidates.append(result)
        else:
            candidates.append(inspect_record(path, record))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps({
            "definition": (
                "Source-evidence candidates for all committed first-year stubs and the unread records the audit "
                "restated; statuses are triage labels, not inferential eligibility decisions."
            ),
            "n_records": len(candidates),
            "records": candidates,
        }, indent=2) + "\n", encoding="utf-8")

    payload = {
        "definition": (
            "Source-evidence candidates for all committed first-year stubs and the unread records the audit "
            "restated; statuses are triage labels, not inferential eligibility decisions."
        ),
        "n_records": len(candidates),
        "records": candidates,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
