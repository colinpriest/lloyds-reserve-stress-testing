"""Round 55 (T02): the prompt-history document is the generator's current output, and
the survey it is written from reads the caches and records rather than typed counts."""
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import prompt_history as ph  # noqa: E402


def test_document_is_current():
    assert (ROOT / "docs" / "prompt-history.md").exists()
    assert ph.render(ph.survey()) == io.open(ROOT / "docs" / "prompt-history.md", encoding="utf-8").read()


def test_survey_reads_the_committed_state():
    s = ph.survey()
    assert s["current_prompt_version"] == ph.current_version()
    assert s["records"] > 1000 and s["stems_with_a_cache"] > 900
    assert s["cache_files"] == sum(s["versions"].values())
    # every committed cache predates the current prompt: nothing was regenerated
    assert s["caches_at_current_version"] == 0
    assert ph._ver(s["newest_cached_version"]) < ph._ver(s["current_prompt_version"])


def test_render_names_the_routes_and_the_version():
    s = ph.survey()
    text = ph.render(s)
    assert "version **%s**" % s["current_prompt_version"] in text
    assert "loss-ratio fallback applied" in text and "Loss-ratio route" in text
    assert "Generated file" in text
