"""Every file the coverage and download scripts name exists with its exact case (review of 2 October 2026,
E-1 / R9-02).

scripts/build_coverage_status.py and scripts/download_from_xlsx.py opened the denominator workbook with a
lower-case s in "syndicates", while git tracks syndicate_reports/Lloyds_Syndicates_2014_2024.xlsx. Windows does
not tell the two apart, so both documented commands ran on the PC and stopped with FileNotFoundError on any
case-sensitive clone. The .gitignore line that keeps the workbook tracked, the README, the directory tree and the
historical audit page carried the same spelling.

Two rules:

  * every path the two scripts name -- the path constants they open and every file name in their text -- is a
    tracked path spelled as git tracks it, or one of the declared paths a clone does not carry (the filings and
    the downloader's log), which must then be gitignored;
  * no tracked code or document names a tracked path in another case. When this test was written that rule found
    the eight sites of the workbook's name and nothing else.

Run:  python -m pytest tests/test_paths_exact_case.py -q
"""
import ast
import functools
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ("scripts/build_coverage_status.py", "scripts/download_from_xlsx.py")
#: paths the scripts name that a clone does not carry, with why; each must be gitignored
NOT_IN_A_CLONE = {
    "syndicate_reports/pdfs": "the filings: published by Lloyd's and not committed",
    "syndicate_reports/download_from_xlsx.log": "the downloader's own log, written when it runs",
}
#: a file name with an extension, alone or after its directories; not part of a template ({syndicate}) or a URL
FILE_NAME = re.compile(r"(?<![\w{}/.:-])((?:[\w.-]+/)*[\w-][\w.-]*\.(?:xlsx|json|md|csv|log|py|txt|ini))\b")
#: tracked trees the case scan leaves out: the 1,065 records, the backend caches and the market source texts (the audit
#: registers and logs under pdf_extraction/audit/ are read)
SCAN_SKIP = ("pdf_extraction/", "market_commentary/full_text/")
SCAN_READ = ("pdf_extraction/audit/",)
#: code, documents, and the data files a path can hide in (a retracted claim once survived in a JSON log)
SCAN_SUFFIXES = (".py", ".md", ".ini", ".json", ".yml", ".yaml", ".toml", ".cfg", ".txt", ".sh", ".csv")


@functools.lru_cache(maxsize=None)
def _tracked():
    out = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z"], capture_output=True, check=True).stdout
    return tuple(p for p in out.decode("utf-8").split("\0") if p)


@functools.lru_cache(maxsize=None)
def _names():
    """Every tracked file, and every directory that holds one, as git spells it."""
    names = set(_tracked())
    for t in _tracked():
        parts = t.split("/")
        names.update("/".join(parts[:i]) for i in range(1, len(parts)))
    return frozenset(names)


@functools.lru_cache(maxsize=None)
def _basenames():
    return frozenset(os.path.basename(t) for t in _tracked())


def _exists_exactly(rel):
    """Whether the path is on disk with every component in this case (os.listdir gives the stored case on Windows too)."""
    cur = ROOT
    for part in rel.split("/"):
        try:
            if part not in os.listdir(cur):
                return False
        except OSError:
            return False
        cur = cur / part
    return True


def _ignored(rel):
    return subprocess.run(["git", "-C", str(ROOT), "check-ignore", "-q", rel]).returncode == 0


def _source(script):
    return (ROOT / script).read_text(encoding="utf-8")


def _path_constants(src):
    """{NAME: repository-relative path} for the module-level NAME = ROOT / "a" / "b" assignments, where ROOT is the
    script's Path(__file__)...parent.parent (the repository root)."""
    tree = ast.parse(src)
    env, out = {}, {}

    def value(node):
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            left, right = value(node.left), value(node.right)
            if left is None or right is None:
                return None
            return right if left == "" else left + "/" + right
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.Name):
            return env.get(node.id)
        return None

    for node in tree.body:
        if not (isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)):
            continue
        name, text = node.targets[0].id, ast.get_source_segment(src, node.value) or ""
        if "__file__" in text:
            assert text.replace(" ", "").endswith((".parent.parent", ".parents[1]")), (
                "%s is not the repository root, so the paths built on it cannot be read here: %s" % (name, text))
            env[name] = ""
        elif isinstance(node.value, ast.BinOp):
            v = value(node.value)
            if v is not None:
                env[name] = out[name] = v
    return out


def _declared_or_tracked(rel):
    """Why the named path is in order, or None: a tracked path in git's spelling, or a declared path a clone lacks."""
    if rel in NOT_IN_A_CLONE:
        return "declared"
    if "/" in rel:
        return "tracked" if rel in _names() else None
    if rel in _basenames() or rel in {os.path.basename(p) for p in NOT_IN_A_CLONE}:
        return "tracked"
    return None


def test_every_path_constant_of_the_two_scripts_exists_with_its_exact_case():
    used = set()
    for script in SCRIPTS:
        constants = _path_constants(_source(script))
        assert "XLSX_PATH" in constants, (script, "the workbook constant is not where this test reads it")
        for name, rel in constants.items():
            if rel in NOT_IN_A_CLONE:
                used.add(rel)
                continue
            assert rel in _names(), (script, name, rel, "not a tracked path in this spelling")
            assert _exists_exactly(rel), (script, name, rel, "not on disk in this spelling")
    for rel in NOT_IN_A_CLONE:
        assert rel in used, (rel, "declared absent from a clone, but no path constant of the scripts names it")
        assert _ignored(rel), (rel, "declared absent from a clone, but git does not ignore it")
        assert rel.lower() not in {n.lower() for n in _names()}, (rel, "declared absent from a clone, but git tracks it")


def test_every_file_the_two_scripts_name_in_their_text_is_spelled_as_tracked():
    for script in SCRIPTS:
        named = sorted(set(m for m in FILE_NAME.findall(_source(script)) if "{" not in m))
        assert named, (script, "no file name found; the pattern no longer reads the script")
        wrong = [rel for rel in named if _declared_or_tracked(rel) is None]
        assert not wrong, (script, "names files that are neither tracked in this spelling nor declared", wrong)


def test_no_tracked_code_or_document_names_a_tracked_path_in_another_case():
    names = _names()
    folded = {}
    for n in names:
        folded.setdefault(n.lower(), set()).add(n)
    bases = {}
    for b in _basenames():
        bases.setdefault(b.lower(), set()).add(b)
    scanned = [t for t in _tracked() if (t.endswith(SCAN_SUFFIXES) or t == ".gitignore")
               and (not t.startswith(SCAN_SKIP) or t.startswith(SCAN_READ))]
    assert len(scanned) > 100, "the scan found almost nothing to read: %d files" % len(scanned)
    wrong = []
    for rel in scanned:
        try:
            text = (ROOT / rel).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for i, line in enumerate(text.splitlines(), 1):
            for tok in re.findall(r"[\w./-]+", line):
                tok = tok.strip("./")
                if "/" in tok:
                    if tok not in names and tok.lower() in folded:
                        wrong.append("%s:%d %s (git: %s)" % (rel, i, tok, sorted(folded[tok.lower()])))
                elif re.search(r"\.[A-Za-z]{2,4}$", tok):
                    if tok not in _basenames() and tok.lower() in bases:
                        wrong.append("%s:%d %s (git: %s)" % (rel, i, tok, sorted(bases[tok.lower()])))
    assert not wrong, "paths spelled in another case than git tracks them: %s" % wrong
