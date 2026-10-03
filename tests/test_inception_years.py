"""Syndicate 2014's first underwriting year (review of 2 October 2026, deferred item 4; stage 2, the PC steps).

pdf_extraction/syndicate_inception_years.json said "2014": 2009. Syndicate 2014's own filings say it commenced underwriting at Lloyd's on
1 January 2014, and that the 2014 year of account is its first underwriting year; none of its six filings in the corpus (2014 to 2019)
mentions 2009. The correction and its quotes are in `_meta.corrections`, not in a new top-level key: test_gemini._load_inception_years reads
every top-level key but `_meta` and `_manual_overrides` as a syndicate number, and _save_inception_years rewrites the file from `_meta`,
`_manual_overrides` and the numeric keys, so an extra top-level key would break the first and be dropped by the second.

Run:  python -m pytest tests/test_inception_years.py -q
"""
import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
REGISTRY = ROOT / "pdf_extraction" / "syndicate_inception_years.json"


def _registry():
    return json.loads(REGISTRY.read_text(encoding="utf-8"))


def test_the_pipeline_can_read_every_key_the_registry_holds():
    """What _load_inception_years reads: every top-level key but _meta and _manual_overrides is a syndicate number with a year."""
    data = _registry()
    syndicates = {int(k): int(v) for k, v in data.items() if k not in ("_meta", "_manual_overrides")}
    assert 2014 in syndicates and len(syndicates) >= 150


def test_syndicate_2014_began_in_2014_and_the_registry_names_the_words_that_say_so():
    data = _registry()
    assert data["2014"] == 2014
    fixes = data["_meta"]["corrections"]
    assert [(c["syndicate"], c["was"], c["now"]) for c in fixes] == [(2014, 2009, 2014)]
    for c in fixes:
        assert data[str(c["syndicate"])] == c["now"]
        assert c["quotes"] and all(set(q) == {"file", "sha256", "page", "quote"} for q in c["quotes"])
        assert any("commenced underwriting" in q["quote"] and "1 January 2014" in q["quote"] for q in c["quotes"])


def test_each_quote_is_on_its_page_in_the_file_with_that_hash():
    """Verbatim, white space aside (the register's own test). Needs the filings, which are not committed."""
    import finalize_structural_eligibility_audit as fin
    for c in _registry()["_meta"]["corrections"]:
        for q in c["quotes"]:
            source = ROOT / q["file"]
            if not source.exists():
                pytest.skip("the source filing is not in this checkout")
            assert hashlib.sha256(source.read_bytes()).hexdigest() == q["sha256"], q["file"]
            texts = fin.page_texts(source)
            assert 1 <= q["page"] <= len(texts), (q["file"], q["page"])
            assert fin.quote_on_page(q["quote"], texts[q["page"] - 1]), (q["file"], q["page"], q["quote"])
