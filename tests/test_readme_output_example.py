"""E-3 (review of 2 October 2026, R9-05): the README's output examples are the committed records they name.

The README's worked example named syndicate_1110_2022.pdf and showed opening reserves of 850.2, a development of
1.07% and a prompt version of 2025-03-10-v3. The record holds 221.885, 4.09% and 2.13: the example's ratio was the
record's development over a wrong reserve, 3.8 times too small. Its other two examples named 1110/2019 as a report
the deterministic step could not read (the record has both models' readings) and gave 1322/2023 a premium mix it
does not have. Each example now names its record, and every value it shows must be the record's.

Run:  python -m pytest tests/test_readme_output_example.py -q
"""
import io
import json
import os
import re

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
README = os.path.join(HERE, "README.md")


def _examples():
    with io.open(README, encoding="utf-8") as fh:
        text = fh.read()
    start = text.index("### Output Format")
    section = text[start:text.index("\n## ", start)]
    return [json.loads(b) for b in re.findall(r"```json\n(.*?)\n```", section, re.S)]


def _stem(example):
    if "source_file" in example:
        name = re.split(r"[\\/]", example["source_file"])[-1]
        return name[:-len(".pdf")]
    return "syndicate_%s_%s" % (example["syndicate"], example["year"])


def _placeholder(v):
    return isinstance(v, str) and v.startswith("...")


def _differences(shown, record, path="$"):
    """Every value the example shows that is not the record's. A string beginning "..." stands for what is
    left out, and a key "..." for the rest of a block."""
    if _placeholder(shown):
        return []
    if isinstance(shown, dict):
        if not isinstance(record, dict):
            return ["%s: a block where the record has %r" % (path, record)]
        out = []
        for k, v in shown.items():
            if k == "...":
                continue
            if k not in record:
                out.append("%s.%s: not in the record" % (path, k))
            else:
                out.extend(_differences(v, record[k], "%s.%s" % (path, k)))
        return out
    if isinstance(shown, list):
        if shown and all(_placeholder(x) for x in shown):
            return [] if isinstance(record, list) else ["%s: a list where the record has %r" % (path, record)]
        if not isinstance(record, list) or len(shown) != len(record):
            return ["%s: %d items where the record has %r" % (path, len(shown), record)]
        out = []
        for i, (a, b) in enumerate(zip(shown, record)):
            out.extend(_differences(a, b, "%s[%d]" % (path, i)))
        return out
    if type(shown) is not type(record) or shown != record:
        return ["%s: %r where the record has %r" % (path, shown, record)]
    return []


def test_the_section_holds_the_three_examples():
    stems = [_stem(e) for e in _examples()]
    assert stems == ["syndicate_1110_2022", "syndicate_1322_2023", "syndicate_4020_2015"], stems


def test_every_value_an_example_shows_is_its_records():
    for example in _examples():
        stem = _stem(example)
        path = os.path.join(HERE, "pdf_extraction", stem + ".json")
        assert os.path.exists(path), "%s names no committed record" % stem
        with io.open(path, encoding="utf-8") as fh:
            record = json.load(fh)
        diffs = _differences(example, record)
        assert not diffs, "%s: %s" % (stem, diffs)


def test_the_worked_examples_ratio_is_its_development_over_its_reserve():
    """The quantity the example illustrates: 9.082 over 221.885 is 4.09%, not 1.07%."""
    block = _examples()[0]["models"]["gemini-2.5-flash"]
    pct = 100.0 * block["prior_year_development_gbp_m"] / block["opening_reserves_gbp_m"]
    assert round(pct, 2) == block["prior_year_development_pct"]
