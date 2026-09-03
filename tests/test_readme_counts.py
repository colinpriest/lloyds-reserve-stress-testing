"""The README's file counts must be the repository's own counts.

Round 40 of the paper review found the README quoting 1,065 extraction files in
its dataset table while the project tree below still said "~622 files" -- a
hand-maintained count from an earlier corpus that nothing ever compared with the
directory it described.

Two rules, so the drift cannot recur:

  * every extraction-file count the README states must equal the on-disk count
    of syndicate_{N}_{YYYY}.json files (strictly matched -- cache files such as
    *_azure.json and reference files such as syndicate_inception_years.json are
    not report extractions);
  * the ASCII project tree carries NO numeric file counts at all: it points at
    the dataset table, which is the one place a count may live.

Run:  python -m pytest tests/test_readme_counts.py -q
"""
import io
import os
import re

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
README = os.path.join(HERE, "README.md")
EXTRACTION_DIR = os.path.join(HERE, "pdf_extraction")


def _read(path):
    return io.open(path, encoding="utf-8", errors="replace").read()


def _on_disk_count():
    rx = re.compile(r"^syndicate_\d+_\d{4}\.json$")
    return sum(1 for f in os.listdir(EXTRACTION_DIR) if rx.match(f))


def test_every_stated_extraction_count_matches_the_directory():
    text = _read(README)
    stated = [int(m.group(1).replace(",", ""))
              for m in re.finditer(r"([\d,]{4,})\s+(?:PDF/HTML|JSON)\s+files",
                                   text)]
    assert stated, "the dataset table no longer states the corpus size"
    disk = _on_disk_count()
    for n in stated:
        assert n == disk, (n, disk)
    assert len(set(stated)) == 1, \
        "the README states two different corpus sizes: %s" % stated


TREE_DOC = os.path.join(HERE, "file_and_folder_structure.md")


def test_the_complete_directory_tree_carries_no_hand_counts():
    """The README calls file_and_folder_structure.md the complete directory tree;
    round 47 found it still saying ~581 PDFs / ~40 HTMLs from the first collection.
    The same one-place rule applies: no numeric file counts in a tree."""
    text = _read(TREE_DOC)
    hits = re.findall(r"[~\u2248]?\s*\d[\d,]*\+?\s*(?:files?|PDFs?|HTMLs?|JSONs?)\b",
                      text)
    assert not hits, "hand-maintained counts in the directory tree: %s" % hits


def test_the_project_tree_carries_no_hand_counts():
    """The tree said ~622 while the table said 1,065; counts live in one place."""
    text = _read(README)
    trees = re.findall(r"```[^`]*?├──[^`]*?```", text, re.S)
    assert trees, "expected the ASCII project tree"
    for block in trees:
        hits = re.findall(r"[~≈]?\s*\d[\d,]*\+?\s*files?", block)
        assert not hits, "hand-maintained counts in the project tree: %s" % hits
