"""Restate the status fields of committed records that carry no model block, and nothing else.

Round 62 (review of 29 September 2026, MAT-2). Two kinds of record carry no `models` block:

* **No deterministic reading** (`no_triangle_data`). Their reason read "No claims development
  triangle or reserve movement text found in report" -- a statement about the filing that the code
  only knew about its parsers. They are restated with the status, the `models_run` flag and the
  reason `test_gemini.process_one_report` now writes (NO_DETERMINISTIC_READING,
  NO_DETERMINISTIC_READING_REASON).
* **First-year stubs.** Their reasons were written by three generations of the rule, among them the
  inception-year rule removed in round 58. They are restated with FIRST_YEAR_REASON and the
  `models_run` flag (true only where the stub carries `first_year_evidence`, the models having run).
  A stub the inception-year rule wrote was never read by the table step -- there is no usable table
  cache to read it from: nine of the ten have no Azure cache, and 1100/2024's is in the superseded list
  format the table step refuses -- and its reason says so and names the filing-page audit that decided
  it instead.

A record listed in `pdf_extraction/audit/redecision_pending.json` is to be extracted again with the
models, and is left exactly as it is.

Every file is checked after it is written: parsed, it must equal the original with only the restated
keys changed, and every changed line of text must be one of those keys' lines. The file keeps its
indentation, ASCII escaping and line endings.

Usage:
    python scripts/restate_record_status.py --no-reading   [--check]
    python scripts/restate_record_status.py --first-year   [--check]

--check changes nothing: it lists the records that are not yet in the restated form and exits 1 if
there are any.
"""
from __future__ import annotations

import argparse
import difflib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import test_gemini as tg  # noqa: E402

RECORDS = ROOT / "pdf_extraction"
PENDING = RECORDS / "audit" / "redecision_pending.json"
AUDIT = RECORDS / "audit" / "structural_eligibility_audit.json"
#: the reason the removed inception-year rule wrote, recognised by its own wording
INCEPTION_RULE_WORDING = "began underwriting in"


def pending_stems() -> set:
    if not PENDING.exists():
        return set()
    return {r["stem"] for r in json.loads(PENDING.read_text(encoding="utf-8"))["records"]}


def audited_decisions() -> dict:
    if not AUDIT.exists():
        return {}
    return {r["file"]: r for r in json.loads(AUDIT.read_text(encoding="utf-8"))["records"]}


def records():
    for path in sorted(RECORDS.glob("syndicate_*_*.json")):
        parts = path.stem.split("_")
        if len(parts) != 3 or not parts[1].isdigit() or not parts[2].isdigit():
            continue
        yield path


def _insert_after(data: dict, anchor: str, new: dict) -> dict:
    """The record with `new` keys set; keys not yet present go right after `anchor`."""
    out = {}
    for k, v in data.items():
        if k in new:
            continue
        out[k] = v
        if k == anchor:
            for nk, nv in new.items():
                out[nk] = nv
    for nk, nv in new.items():
        out.setdefault(nk, nv)
    return out


def restated_no_reading(data: dict) -> dict:
    new = {"status": tg.NO_DETERMINISTIC_READING, "models_run": False,
           "exclusion_reason": tg.NO_DETERMINISTIC_READING_REASON}
    out = _insert_after(data, "excluded", {k: new[k] for k in ("status", "models_run")})
    out["exclusion_reason"] = new["exclusion_reason"]
    return out


#: the reason a stub the inception-year rule wrote is restated with. "No usable cache": nine of the
#: ten have no Azure cache, and 1100/2024's is in the superseded list format, which the table step
#: refuses (table_extraction: a cache that is not a dict is not usable).
AUDITED_INCEPTION_STUB_REASON = (
    "No underwriting year old enough for prior year development (u <= t-2) in the filing's "
    "claims development table, as read on its pages in "
    "pdf_extraction/audit/structural_eligibility_audit.json. The record was written by the "
    "inception-year rule removed in round 58; the table step has no usable cache for this filing, "
    "and neither it nor the models has read its reserve text.")
#: the earlier wordings of that reason, restated to the current one. Round 62 wrote "has no cache",
#: which was not true of 1100/2024 (verification review of round 62, N-V-E-2).
PREVIOUS_AUDITED_INCEPTION_STUB_REASONS = (
    "No underwriting year old enough for prior year development (u <= t-2) in the filing's "
    "claims development table, as read on its pages in "
    "pdf_extraction/audit/structural_eligibility_audit.json. The record was written by the "
    "inception-year rule removed in round 58; the table step has no cache for this filing, "
    "and neither it nor the models has read its reserve text.",
)


def first_year_reason(data: dict, audited: dict, name: str) -> str:
    reason = str(data.get("reason") or "")
    if (INCEPTION_RULE_WORDING not in reason and reason != AUDITED_INCEPTION_STUB_REASON
            and reason not in PREVIOUS_AUDITED_INCEPTION_STUB_REASONS):
        return tg.FIRST_YEAR_REASON
    decision = (audited.get(name) or {}).get("decision")
    if decision != "structural_ineligible_no_mature_cohort":
        raise SystemExit("%s: written by the inception-year rule and not decided by the filing-page audit"
                         % name)
    return AUDITED_INCEPTION_STUB_REASON


def restated_first_year(data: dict, audited: dict, name: str) -> dict:
    new = {"reason": first_year_reason(data, audited, name),
           "models_run": bool(data.get("first_year_evidence"))}
    out = _insert_after(data, "reason", {"models_run": new["models_run"]})
    out["reason"] = new["reason"]
    return out


def dump(data: dict, newline: str) -> bytes:
    return json.dumps(data, indent=2, ensure_ascii=True).replace("\n", newline).encode("ascii")


def verify(before: bytes, after: bytes, keys: set, name: str) -> None:
    old, new = json.loads(before), json.loads(after)
    strip = lambda d: {k: v for k, v in d.items() if k not in keys}  # noqa: E731
    if strip(old) != strip(new):
        raise SystemExit("%s: a field other than %s would change" % (name, sorted(keys)))
    a = before.decode("ascii").splitlines()
    b = after.decode("ascii").splitlines()
    for line in difflib.ndiff(a, b):
        if line[:2] in ("- ", "+ ") and not any(line[2:].lstrip().startswith('"%s":' % k) for k in keys):
            raise SystemExit("%s: the text diff touches a line outside %s: %r" % (name, sorted(keys), line))


def main() -> int:
    ap = argparse.ArgumentParser()
    kind = ap.add_mutually_exclusive_group(required=True)
    kind.add_argument("--no-reading", action="store_true")
    kind.add_argument("--first-year", action="store_true")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    skip = pending_stems()
    audited = audited_decisions()
    changed, current, left = [], 0, []
    for path in records():
        raw = path.read_bytes()
        data = json.loads(raw)
        if "models" in data:
            continue
        if args.no_reading and data.get("no_triangle_data"):
            keys = {"status", "models_run", "exclusion_reason"}
            new = restated_no_reading(data)
        elif args.first_year and data.get("first_year_syndicate"):
            keys = {"reason", "models_run"}
            new = restated_first_year(data, audited, path.name)
        else:
            continue
        if path.stem in skip:
            left.append(path.stem)
            continue
        newline = "\r\n" if b"\r\n" in raw else "\n"
        out = dump(new, newline)
        if out == raw:
            current += 1
            continue
        verify(raw, out, keys, path.name)
        changed.append(path.stem)
        if not args.check:
            path.write_bytes(out)
    what = "no-deterministic-reading" if args.no_reading else "first-year"
    print("%s records: %d already restated, %d %s, %d left for a new extraction (%s)"
          % (what, current, len(changed), "to restate" if args.check else "restated", len(left),
             PENDING.name))
    for s in changed:
        print("   ", s)
    return 1 if (args.check and changed) else 0


if __name__ == "__main__":
    sys.exit(main())
