"""The OCR documentation must state the program's own Azure tier default and flag.

Round 48 of the paper review found docs/ocr-pipeline.md saying the free F0 tier
was the default and that `--azure-paid` selected S0, while test_gemini.py defaults
to the paid S0 tier and offers `--azure-free` to disable it. The default and the
flag are read here from the program source, not typed, so the document is checked
against whatever the program actually does.

Run:  python -m pytest tests/test_azure_tier_doc.py -q
"""
import io
import os
import re

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROGRAM = os.path.join(HERE, "test_gemini.py")
DOC = os.path.join(HERE, "docs", "ocr-pipeline.md")


def _read(path):
    return io.open(path, encoding="utf-8", errors="replace").read()


def program_default_and_flag():
    src = _read(PROGRAM)
    m = re.search(r"^AZURE_PAID\s*=\s*(True|False)", src, re.M)
    assert m, "test_gemini.py no longer declares AZURE_PAID"
    paid_default = m.group(1) == "True"
    flags = set(re.findall(r'"(--azure-(?:free|paid))"', src))
    return paid_default, flags


def test_the_document_states_the_programs_default_tier():
    paid_default, flags = program_default_and_flag()
    doc = _read(DOC)
    sec = doc[doc.index("Azure Document Intelligence"):]
    paid_bullet = re.search(r"\*\*Paid tier \(S0\)\*\*[^\n]*(?:\n  [^\n]*)*", sec).group(0)
    free_bullet = re.search(r"\*\*Free tier \(F0\)\*\*[^\n]*(?:\n  [^\n]*)*", sec).group(0)
    if paid_default:
        assert "default" in paid_bullet and "default" not in free_bullet
    else:
        assert "default" in free_bullet and "default" not in paid_bullet


def test_the_document_names_the_flag_the_program_accepts():
    paid_default, flags = program_default_and_flag()
    doc = _read(DOC)
    for flag in ("--azure-free", "--azure-paid"):
        if flag in flags:
            assert flag in doc, "%s is accepted by the program but undocumented" % flag
        else:
            assert flag not in doc, "%s is documented but the program does not accept it" % flag


def test_the_usage_examples_match_the_default():
    paid_default, flags = program_default_and_flag()
    doc = _read(DOC)
    block = re.search(r"```bash\n(# .*?tier.*?)```", doc, re.S)
    assert block, "the Azure usage example block is missing"
    lines = [ln.strip() for ln in block.group(1).splitlines() if ln.strip()]
    bare = [ln for ln in lines if ln.startswith("python test_gemini.py") and "--azure" not in ln]
    assert bare, "no bare (default) invocation in the usage example"
    comment_before_bare = lines[lines.index(bare[0]) - 1].lower()
    assert ("paid" in comment_before_bare) == paid_default, comment_before_bare
