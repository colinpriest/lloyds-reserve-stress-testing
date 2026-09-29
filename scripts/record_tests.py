"""Run the extraction suite and record the result in tests-run-report.json (round 62).

Why this exists: the manuscript's submission checklist stated the extraction suite's count by hand
("537 passed"), and it was 539 at the commit it cited (review of 29 September 2026, S-1). No count
is typed any more: this script runs the suite the documented way, from the repository root, and
writes the commit, the dirty flag, the counts and every skip with its reason. The checklist count is
generated from the record, and tests/test_tests_run_report.py fails when the record is not clean,
not green, or no longer the size of the suite.

The suite runs offline: LLOYDS_EXTRACTION_OFFLINE=1, and LLOYDS_ALLOW_PAID_API and
LLOYDS_ALLOW_TABLE_BACKEND_CALLS are removed from its environment, so a cache miss is an error and
the paid test skips for its declared reason. Record a clean tree: a dirty one is recorded as dirty.

Run:  python scripts/record_tests.py
"""
from __future__ import annotations

import datetime
import json
import os
import platform
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECORD = ROOT / "tests-run-report.json"
SUMMARY = re.compile(r"(?P<n>\d+) (?P<kind>passed|failed|skipped|errors?|deselected|xfailed|xpassed)")
SKIP_LINE = re.compile(r"^SKIPPED \[(\d+)\] (\S+?):\d+: (.*)$")


def git(*args):
    return subprocess.run(["git", "-C", str(ROOT)] + list(args), capture_output=True, text=True,
                          check=True).stdout.strip()


def suite_env():
    env = dict(os.environ)
    env["LLOYDS_EXTRACTION_OFFLINE"] = "1"
    # tests/test_tests_run_report.py cannot check the record this run is writing; it skips for that
    # declared reason here and checks the record on every other run
    env["LLOYDS_RECORDING_SUITE"] = "1"
    env.pop("LLOYDS_ALLOW_PAID_API", None)
    env.pop("LLOYDS_ALLOW_TABLE_BACKEND_CALLS", None)
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def collected():
    r = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider"],
                       cwd=str(ROOT), env=suite_env(), capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    m = re.search(r"(\d+) tests? collected", r.stdout + r.stderr)
    if not m:
        raise SystemExit("could not read the collection count:\n" + (r.stdout + r.stderr)[-2000:])
    return int(m.group(1))


def run():
    cmd = [sys.executable, "-m", "pytest", "-q", "-rs", "-p", "no:cacheprovider"]
    r = subprocess.run(cmd, cwd=str(ROOT), env=suite_env(), capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    out = r.stdout + r.stderr
    last = [l for l in out.splitlines() if re.search(r"\d+ (passed|failed)", l)]
    if not last:
        raise SystemExit("could not read the pytest summary:\n" + out[-2000:])
    counts = {"passed": 0, "failed": 0, "skipped": 0, "errors": 0, "deselected": 0}
    for m in SUMMARY.finditer(last[-1]):
        kind = "errors" if m.group("kind").startswith("error") else m.group("kind")
        counts[kind] = counts.get(kind, 0) + int(m.group("n"))
    skips = {}
    for line in out.splitlines():
        m = SKIP_LINE.match(line.strip())
        if m:
            key = "%s: %s" % (m.group(2).replace("\\", "/"), m.group(3).strip())
            skips[key] = skips.get(key, 0) + int(m.group(1))
    return r.returncode, counts, dict(sorted(skips.items())), " ".join(cmd[1:]), last[-1].strip()


def main():
    head = git("rev-parse", "HEAD")
    dirty = [l for l in git("status", "--porcelain").splitlines() if not l.endswith(RECORD.name)]
    n_collected = collected()
    code, counts, skips, command, summary = run()
    record = {
        "purpose": ("The extraction suite's result at a commit, written by scripts/record_tests.py; the "
                    "manuscript's checklist count is generated from it and not typed."),
        "commit": head,
        "dirty": bool(dirty),
        "dirty_paths": dirty[:50],
        "recorded_at_utc": datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat(),
        "command": "python " + command + "   (from the repository root; LLOYDS_EXTRACTION_OFFLINE=1)",
        "python": platform.python_version(),
        "platform": platform.platform(),
        "collected": n_collected,
        "passed": counts["passed"],
        "failed": counts["failed"],
        "errors": counts["errors"],
        "skipped": counts["skipped"],
        "skipped_reasons": skips,
        "exit_code": code,
        "summary_line": summary,
    }
    RECORD.write_text(json.dumps(record, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({k: record[k] for k in ("commit", "dirty", "collected", "passed", "failed",
                                              "errors", "skipped")}))
    return 0 if code == 0 and not dirty else 1


if __name__ == "__main__":
    sys.exit(main())
