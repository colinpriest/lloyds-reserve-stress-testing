"""The prompt-history document is the generator's current output, the survey it is written from
reads the caches and records rather than typed counts, and its prose follows the survey (R204)."""
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
    assert s["caches_at_current_version"] == s["versions"].get(s["current_prompt_version"], 0)
    # every record is counted once, under its own prompt version
    assert s["records_at_current_version"] + len(s["records_below_current"]) == s["records"]
    assert all(v != s["current_prompt_version"] for _stem, v in s["records_below_current"])
    assert [e["version"] for e in s["version_log"]][-1] == s["current_prompt_version"]


def _survey(**over):
    s = {"current_prompt_version": "9.9", "cache_files": 10, "versions": {"9.8": 4, "9.9": 6},
         "newest_cached_version": "9.9", "caches_at_current_version": 6,
         "stems_with_a_cache": 5, "records": 7, "records_at_current_version": 5,
         "records_below_current": [("syndicate_1_2020", "9.8"), ("syndicate_2_2020", "9.8")],
         "records_served_from_another_version": [],
         "records_loss_ratio_fallback_applied": [], "records_mentioning_a_loss_ratio_table": 0,
         "records_loss_ratio_with_a_premium_approximation": [],
         "version_log": [{"version": "9.9", "date": "2099-01-01", "description": "planted"}]}
    s.update(over)
    return s


def test_the_prose_follows_the_survey_when_records_are_at_the_current_version():
    """The round-55 prose said every record rests on the old prompt whatever the counts were."""
    text = ph.render(_survey())
    assert "rests on responses produced under the old prompt rules" not in text
    assert "5 records were written under the current version 9.9" in text
    assert "syndicate_1_2020 (9.8)" in text


def test_the_prose_follows_the_survey_when_none_are():
    text = ph.render(_survey(records_at_current_version=0, caches_at_current_version=0,
                             versions={"9.8": 10},
                             records_below_current=[("syndicate_%d_2020" % i, "9.8") for i in range(7)]))
    assert "0 records were written under the current version 9.9" in text


def test_a_response_served_from_another_version_is_counted():
    text = ph.render(_survey(records_served_from_another_version=[("syndicate_3_2020", "m", "9.8")]))
    assert "1 committed model response carries `_served_from`" in text
    assert "No committed model response carries one" not in ph.render(
        _survey(records_served_from_another_version=[("syndicate_3_2020", "m", "9.8")]))


def test_an_amended_version_is_printed_with_its_amendment():
    """2.13's description says the override gate "was fixed"; R193 reverted the fix, and a
    document that printed the description without the amendment would repeat the claim."""
    log = [{"version": "9.9", "date": "2099-01-01", "description": "planted",
            "amended": {"date": "2099-02-02", "note": "the planted fix was reverted"}}]
    text = ph.render(_survey(version_log=log))
    assert "*Amended 2099-02-02:* the planted fix was reverted" in text


def test_render_names_the_routes_and_the_version():
    s = ph.survey()
    text = ph.render(s)
    assert "version **%s**" % s["current_prompt_version"] in text
    assert "loss-ratio fallback applied" in text and "Loss-ratio route" in text
    assert "Generated file" in text
