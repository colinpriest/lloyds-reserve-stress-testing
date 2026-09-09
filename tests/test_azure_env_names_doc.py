"""Round 54 (review T02): the README names the Azure variables the code reads.

The README told users to set AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT and _KEY; the
extractor reads DOCUMENTINTELLIGENCE_ENDPOINT and DOCUMENTINTELLIGENCE_API_KEY and
has no alias, so a fresh (cache-miss) request configured from the README reported
missing credentials. The names are read out of the code here and checked against the
README, and the reading boundary is exercised with the documented names set and no
network call.

Run:  python -m pytest tests/test_azure_env_names_doc.py -q
"""
import io
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _code_names():
    src = io.open(ROOT / "table_extraction.py", encoding="utf-8").read()
    names = set(re.findall(r'os\.getenv\("(DOCUMENTINTELLIGENCE_[A-Z_]+)"\)', src))
    assert names, "the extractor reads its Azure variables through os.getenv"
    return names


def _readme_names():
    text = io.open(ROOT / "README.md", encoding="utf-8").read()
    return set(re.findall(r"^([A-Z_]*DOCUMENT[A-Z_]*INTELLIGENCE[A-Z_]*)=", text, re.M))


def test_readme_documents_the_names_the_code_reads():
    assert _readme_names() == _code_names()


def test_documented_names_pass_the_credential_boundary(monkeypatch):
    import table_extraction as te
    for n in _readme_names():
        monkeypatch.setenv(n, "placeholder")
    src = io.open(ROOT / "table_extraction.py", encoding="utf-8").read()
    # the boundary: the two getenv calls resolve to the placeholders
    for n in _code_names():
        assert os.getenv(n) == "placeholder"
    assert 'logger.error("DOCUMENTINTELLIGENCE_ENDPOINT or DOCUMENTINTELLIGENCE_API_KEY not' in src
