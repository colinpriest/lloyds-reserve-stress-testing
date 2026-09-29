"""Count the models' own claims triangles in the committed records, and measure the one-column rule on
them (round 62; verification review of round 62, item 5).

docs/ocr-pipeline.md 9.6 said that "of the models' own 1,596 triangles two change" under the
one-column staircase rule; the script that counted them was never committed, and a recount found 1,547
in the same records. The two counts are of different things: 1,596 blocks carry a `_claims_triangle`
whose type is not "none", and 1,547 of those hold at least one development row. This script counts
both, and the one-column triangles among them, in the records of the working tree or of a commit, and
evaluates `compute_pyd_from_triangle` on each under the current scorer and under the scorer before
round 62, which gave any one-column grid 0.0 (`_validate_triangle_structure` returned 0.0 for fewer
than two columns; its multi-column branch is unchanged).

What it counts: every committed record `pdf_extraction/syndicate_<n>_<year>.json` that has a
`models` block, and in it each model block's `_claims_triangle` (the triangle the model returned,
which `verify_triangles` recomputes). Stubs, unread records and the page-vision triangles of the RAG
step are not model triangles and are not counted.

    python scripts/count_model_triangles.py            # the working tree's records
    python scripts/count_model_triangles.py --at 11b1bc36   # the records of a commit

Prints a JSON summary. Nothing calls a model: only pure functions of test_gemini are used.
"""
from __future__ import annotations

import argparse
import copy
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _is_record(name: str) -> bool:
    parts = Path(name).stem.split("_")
    return (Path(name).suffix == ".json" and len(parts) == 3 and parts[0] == "syndicate"
            and parts[1].isdigit() and parts[2].isdigit())


def records_in_tree() -> dict:
    return {p.stem: json.loads(p.read_text(encoding="utf-8"))
            for p in sorted((ROOT / "pdf_extraction").glob("syndicate_*_*.json")) if _is_record(p.name)}


def records_at(commit: str) -> dict:
    """The committed records of `commit`, read from git objects (the working tree is not touched)."""
    names = subprocess.run(["git", "-C", str(ROOT), "ls-tree", "--name-only", commit, "pdf_extraction/"],
                           capture_output=True, text=True, check=True).stdout.split()
    names = [n for n in names if _is_record(Path(n).name)]
    batch = subprocess.run(["git", "-C", str(ROOT), "cat-file", "--batch"],
                           input="".join("%s:%s\n" % (commit, n) for n in names).encode("utf-8"),
                           capture_output=True, check=True).stdout
    out, pos = {}, 0
    for name in names:
        header_end = batch.index(b"\n", pos)
        size = int(batch[pos:header_end].split()[2])
        body = batch[header_end + 1:header_end + 1 + size]
        out[Path(name).stem] = json.loads(body.decode("utf-8"))
        pos = header_end + 1 + size + 1
    return out


def _pre_round_62_scorer(current):
    """The scorer before round 62: 0.0 for fewer than two columns, else the (unchanged) current one."""
    def score(uw_years, rows, report_year):
        if len(uw_years) < 2:
            return 0.0
        return current(uw_years, rows, report_year)
    return score


def count(records: dict) -> dict:
    import test_gemini as tg

    current = tg._validate_triangle_structure
    before = _pre_round_62_scorer(current)

    def pyd(tri, year, scorer):
        tg._validate_triangle_structure = scorer
        try:
            return tg.compute_pyd_from_triangle(copy.deepcopy(tri), year)[0]
        finally:
            tg._validate_triangle_structure = current

    n_records = n_blocks = n_triangles = n_with_rows = 0
    one_column, changed = [], []
    for stem, d in sorted(records.items()):
        models = d.get("models")
        if not isinstance(models, dict) or not models:
            continue
        n_records += 1
        year = int(stem.split("_")[2])
        for name, block in sorted(models.items()):
            n_blocks += 1
            tri = block.get("_claims_triangle") if isinstance(block, dict) else None
            if not isinstance(tri, dict) or tri.get("type") in (None, "none"):
                continue
            n_triangles += 1
            if not tri.get("development_rows"):
                continue
            n_with_rows += 1
            if len(tri.get("underwriting_years") or []) == 1:
                one_column.append("%s %s" % (stem, name))
            now, then = pyd(tri, year, current), pyd(tri, year, before)
            if now != then:
                changed.append({"record": stem, "model": name, "before_round_62": then, "now": now})
    return {"records_with_models": n_records, "model_blocks": n_blocks,
            "claims_triangles": n_triangles, "claims_triangles_with_development_rows": n_with_rows,
            "one_column": one_column, "figure_changed_by_the_one_column_rule": changed}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--at", default="", help="count the records of this commit instead of the working tree")
    args = ap.parse_args()
    records = records_at(args.at) if args.at else records_in_tree()
    result = {"records_of": args.at or "working tree", "n_records": len(records), **count(records)}
    print(json.dumps(result, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
