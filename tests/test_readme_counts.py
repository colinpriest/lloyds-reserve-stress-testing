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
import subprocess

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


# --- review of 2 October 2026 (E-2 / R9-04 / R11-13) -----------------------------------------------------------------
# The README's "Expected Results" table kept the first plan's estimates (~300 syndicates, ~3,300 syndicate-years, "500-800"
# downloads, ~85-140 usable reports) beside the measured 1,065, and its Quick Start and Suggested Workflow still sent a
# reader to `lloyds_scraper.py --all`, which scrapes lloyds.com for its own syndicate list, not the workbook's rows. The
# corpus is the workbook's downloads plus 33 filings of an earlier pass; its size is a count, never an estimate.

#: a word that makes a number a count of the corpus or of what it was drawn from
CORPUS_WORD = re.compile(r"\b(reports?|downloads?|syndicates?|syndicate-years?|filings?|records?|files?)\b", re.I)
#: an approximate count: "~N", "about N", "approximately N", or a range "N-M" that is not a span of years or a date
APPROX = re.compile(r"[~≈]\s*\d|\b(?i:about|approximately|roughly)\s+\d|"
                    r"(?<![\d.,-])(\d+(?:,\d{3})*)\s*[-–]\s*(\d+(?:,\d{3})*)(?![\d-])")
YEAR = re.compile(r"^(19|20)\d\d$")


def _approximate_counts(text):
    out = []
    for i, line in enumerate(text.splitlines(), 1):
        if not CORPUS_WORD.search(line):
            continue
        for m in APPROX.finditer(line):
            a, b = m.group(1), m.group(2)
            if a and b and YEAR.match(a) and (YEAR.match(b) or len(b) == 2):
                continue        # 2014-2024, 2014-19
            out.append("%d: %s" % (i, line.strip()[:120]))
    return out


def test_no_document_estimates_the_corpus():
    for path in (README, TREE_DOC):
        hits = _approximate_counts(_read(path))
        assert not hits, "%s gives approximate counts of the corpus: %s" % (os.path.basename(path), hits)


def test_the_documented_download_route_is_the_workbook_downloader():
    """Quick Start step 1 and the Suggested Workflow download with scripts/download_from_xlsx.py; neither document presents the
    earlier scraper as the way to obtain the corpus."""
    text = _read(README)
    for heading in ("#### 1. Download syndicate reports", "1. **Download syndicate reports**"):
        start = text.index(heading)
        block = re.search(r"```bash\n(.*?)```", text[start:], re.S)
        assert block and "scripts/download_from_xlsx.py" in block.group(1), (heading, block and block.group(1))
        assert "lloyds_scraper.py" not in block.group(1), heading
    # every tracked file, code included (the dashboard's download button ran the scraper), but the scraper's own usage line
    # and this file
    out = subprocess.run(["git", "-C", HERE, "grep", "-l", "-I", "-F", "lloyds_scraper.py --all", "--", ".",
                          ":!pdf_extraction", ":!scripts/lloyds_scraper.py", ":!tests/test_readme_counts.py"],
                         capture_output=True, text=True)
    assert out.returncode in (0, 1), out.stderr
    assert not out.stdout.split(), "the earlier scraper is given as the way to obtain the corpus: %s" % out.stdout.split()
    for path in (README, TREE_DOC):
        doc = _read(path)
        assert "Expected downloads" not in doc, os.path.basename(path)
        lines = [l for l in doc.splitlines() if re.search(r"lloyds_scraper\.py\s+#", l)]
        assert lines, (os.path.basename(path), "the tree no longer lists lloyds_scraper.py")
        for line in lines:
            assert not re.search(r"#\s*(Main|Syndicate report downloader)", line), (os.path.basename(path), line)


def test_every_count_of_filings_is_the_corpus_size():
    """A count of filings or files with four digits or more is the corpus size. Its parts (the 1,032 downloads and the 33
    earlier filings) are stated as parts ("1,032 of the corpus's 1,065 filings"), never as "N filings" on their own."""
    disk = _on_disk_count()
    text = " ".join(_read(README).split())
    for m in re.finditer(r"([\d,]{5,})\s+(?:PDF/HTML |JSON )?(?:filings|files)\b", text):
        assert int(m.group(1).replace(",", "")) == disk, (m.group(0), disk)
