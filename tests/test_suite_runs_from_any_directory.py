"""The suite's verdict does not depend on where pytest is started (verification review of round 62,
test gap E-6).

The pipeline resolves its caches from the working directory (test_gemini's REPORTS_DIR, OUTPUT_DIR,
LLM_CACHE_DIR, table_extraction's default cache_dir), and before round 62 six round-52 binding
replays failed when pytest was started anywhere but the repository root. conftest.py now runs every
test from the root; nothing held that in place, since the recorded suite runs from the root and stays
green without it. Here a binding test module is run from another directory, in a subprocess, and must
pass. The run includes a test that needs no source filing and checks the working directory itself, so
it is not vacuous in a clone without the filings (where the binding replays skip, for their declared
reason).

Run:  python -m pytest tests/test_suite_runs_from_any_directory.py -q
"""
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import test_gemini as tg  # noqa: E402

HERE = "tests/test_suite_runs_from_any_directory.py"
CWD_TEST = "test_the_pipelines_relative_paths_resolve_at_the_repository_root"


def test_the_pipelines_relative_paths_resolve_at_the_repository_root():
    """What every test is given: the root as its working directory, so the pipeline's relative cache
    paths name the committed caches."""
    assert Path.cwd().resolve() == ROOT.resolve()
    assert not tg.LLM_CACHE_DIR.is_absolute() and any(tg.LLM_CACHE_DIR.glob("*.json"))
    assert (tg.AUDIT_DIR / "redecision_pending.json").is_file()


def test_a_binding_module_passes_when_pytest_starts_in_another_directory(tmp_path):
    env = dict(os.environ)
    env["LLOYDS_EXTRACTION_OFFLINE"] = "1"          # a cache miss is an error, never a call
    env.pop("LLOYDS_ALLOW_TABLE_BACKEND_CALLS", None)
    env.pop("LLOYDS_ALLOW_PAID_API", None)
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                        str(ROOT / "tests" / "test_round52_binding.py"),
                        "%s::%s" % (ROOT / HERE, CWD_TEST)],
                       cwd=str(tmp_path), env=env, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    out = r.stdout + r.stderr
    assert r.returncode == 0, out[-3000:]
    assert not re.search(r"\d+ (failed|errors?)\b", out), out[-3000:]
    passed = re.search(r"(\d+) passed", out)
    # the working-directory test ran and passed, and so did the binding module's own tests
    assert passed and int(passed.group(1)) >= 2, out[-3000:]
    assert Path.cwd().resolve() == ROOT.resolve()
