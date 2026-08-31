#!/usr/bin/env python3
"""Documentation tests for the PYD provenance hierarchy.

Two rounds of review found the same thing: canonical section 10.3 was corrected and a
public summary somewhere else went on stating the superseded rule. The last round left
a "clarification" beside the balance-sheet override saying the section-10.3
qualification is "triangle-versus-provisions, not triangle-versus-LLM" -- false for a
loss-ratio triangle, where an AGREEING syndicate-specific narrative value is retained.

So this file tests two invariants rather than two sentences.

SCOPE. Any sentence claiming deterministic authority OVER an LLM must name the scope
that makes it true -- an absolute-amount triangle -- or carry the loss-ratio
conditional. The check is sentence-bounded on purpose: a qualification in the
neighbouring paragraph does not excuse an absolute claim, because a reader quoting the
sentence gets the wrong rule. That is the failure mode a +-260-character window let
through in the manuscript's own detector.

COUNTS. The canonical numbered list is the only place the number of steps lives. Any
document that types a count is checked against that list, so adding a step cannot leave
"five-step" behind in a README.

Run:  python -m pytest tests/test_docs_hierarchy.py -q
"""
import io
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CANONICAL = os.path.join(ROOT, "docs", "ocr-pipeline.md")

# documents a reader of the repository actually meets
PUBLIC_DOCS = ("README.md", "CLAUDE.md", "docs/ocr-pipeline.md",
               "docs/data-audit-results.md")

WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
         "seven": 7, "eight": 8, "nine": 9, "ten": 10}

# An authority CLAIM asserts a rule; the noun "override" describes a mechanic that
# has already been ruled on ("the override is recorded in data_quality_notes"), so
# only the verb and the adjectival forms count. This is what separates the rule
# statements a reader could quote from the pipeline's own bookkeeping prose.
AUTHORITY = re.compile(
    r"(authoritative|overrides\b|overriding|replaces|takes precedence|"
    r"prevails? over|ground truth)", re.I)
SUBJECT = re.compile(r"(triangle|\bPYD\b|deterministic)", re.I)
LLM_OBJECT = re.compile(r"(llm|narrative|text extraction|gemini|gpt)", re.I)
# the scope that makes such a claim true, or the branch that qualifies it
SCOPE = re.compile(r"(absolute[- ]amount|loss[- ]ratio)", re.I)


def _read(rel):
    p = os.path.join(ROOT, rel.replace("/", os.sep))
    return io.open(p, encoding="utf-8", errors="replace").read()


def _read_or_skip(rel):
    """CLAUDE.md is gitignored and absent from a clean clone; every other entry is
    tracked. Skipping keeps the gate honest in a clone instead of erroring there."""
    p = os.path.join(ROOT, rel.replace("/", os.sep))
    if not os.path.exists(p):
        pytest.skip("%s is not present in this checkout (local-only file)" % rel)
    return _read(rel)


def _sentences(text):
    """Flattened sentences. Markdown wraps mid-sentence, so join lines first; bullets
    and headings end a unit as surely as a full stop does."""
    units = []
    for block in re.split(r"\n\s*(?:[-*+]|\d+\.)\s|\n\s*\n|\n#+ ", text):
        flat = " ".join(block.split())
        for part in re.split(r"(?<=[.:;])\s+", flat):
            if part.strip():
                units.append(part.strip())
    return units


def unscoped_authority_claims(text):
    """Sentences asserting deterministic authority over an LLM without naming scope."""
    out = []
    for s in _sentences(text):
        if (AUTHORITY.search(s) and SUBJECT.search(s) and LLM_OBJECT.search(s)
                and not SCOPE.search(s)):
            out.append(s)
    return out


def canonical_steps():
    """The numbered steps of the canonical hierarchy, from section 10.3 itself."""
    text = _read("docs/ocr-pipeline.md")
    i = text.index("hierarchy; every other document defers to it.")
    tail = text[i:]
    steps, expect, current = [], 1, None
    for line in tail.splitlines()[1:]:
        m = re.match(r"^(\d+)\.\s+(.*)$", line)
        if m and int(m.group(1)) == expect:
            if current is not None:
                steps.append(current)
            current, expect = m.group(2), expect + 1
        elif current is not None:
            if line.startswith("   ") or not line.strip():
                # continuation lines are indented; a blank line inside the list is
                # tolerated, an unindented one ends it
                if line.strip():
                    current += " " + line.strip()
            else:
                break
    if current is not None:
        steps.append(current)
    return steps


class TestCanonicalHierarchy:
    """The canonical list is well-formed and states both loss-ratio branches."""

    def test_the_numbered_list_parses(self):
        steps = canonical_steps()
        assert len(steps) >= 5, steps

    def test_loss_ratio_step_states_both_branches(self):
        flat = " ".join(" ".join(canonical_steps()).split()).lower()
        assert "loss-ratio triangle" in flat
        assert "fills an llm blank" in flat, "the blank-filling branch is not stated"
        assert "contradict" in flat, "the direction-contradiction branch is not stated"
        assert "never overrides an absolute-amount triangle" in flat

    def test_provisions_sign_override_survives(self):
        flat = " ".join(" ".join(canonical_steps()).split()).lower()
        assert "signs disagree" in flat and "provisions movement is" in flat


class TestTypedStepCounts:
    """A typed count of a numbered list drifts the moment the list changes."""

    def test_no_document_types_a_stale_step_count(self):
        n = len(canonical_steps())
        bad = []
        for rel in PUBLIC_DOCS:
            if not os.path.exists(os.path.join(ROOT, rel.replace("/", os.sep))):
                continue
            flat = " ".join(_read(rel).split())
            for m in re.finditer(r"(?i)\b(\w+)[- ]step\b", flat):
                window = flat[max(0, m.start() - 120):m.end() + 120]
                if not re.search(r"(?i)hierarchy|provenance|10\.3|rule", window):
                    continue
                stated = WORDS.get(m.group(1).lower())
                if stated is None and m.group(1).isdigit():
                    stated = int(m.group(1))
                if stated is not None and stated != n:
                    bad.append("%s: %r but the canonical list has %d"
                               % (rel, m.group(0), n))
        assert not bad, bad


class TestAuthorityClaimsAreScoped:
    """Finding R4: an unscoped triangle-over-LLM claim is false for loss ratios."""

    @pytest.mark.parametrize("rel", PUBLIC_DOCS)
    def test_public_document_scopes_its_authority_claims(self, rel):
        bad = unscoped_authority_claims(_read_or_skip(rel))
        assert not bad, "%s: %s" % (rel, bad[:3])

    def test_detector_fires_on_the_withdrawn_clarification(self):
        """The exact sentence this round removed must not be re-introducible."""
        assert unscoped_authority_claims(
            "the deterministic extraction is authoritative over LLMs (for PYD, within "
            "the section 10.3 hierarchy: the qualification there is "
            "triangle-versus-provisions, not triangle-versus-LLM).")

    def test_detector_fires_on_a_paraphrase(self):
        assert unscoped_authority_claims(
            "The triangle PYD always takes precedence over the narrative value.")

    def test_detector_accepts_a_scoped_claim(self):
        assert not unscoped_authority_claims(
            "An absolute-amount triangle PYD overrides any LLM-extracted figure.")

    def test_a_qualification_in_the_next_sentence_does_not_excuse_an_absolute(self):
        """Sentence-bounded, not window-bounded: block contamination is the bug."""
        assert unscoped_authority_claims(
            "The triangle PYD overrides the LLM value. A loss-ratio triangle is a "
            "conditional fallback, and an absolute-amount triangle is not.")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
