"""Behavioural tests for the conditional loss-ratio PYD hierarchy."""

from test_gemini import _apply_loss_ratio_fallback


def test_loss_ratio_fills_blank_narrative():
    result = {"prior_year_development_gbp_m": None,
              "opening_reserves_gbp_m": 200.0}

    branch = _apply_loss_ratio_fallback(result, -20.0, "test-model")

    assert branch == "filled_blank"
    assert result["prior_year_development_gbp_m"] == -20.0
    assert result["prior_year_development_pct"] == -10.0
    assert result["direction"] == "release"
    assert "MANAGED LEVEL" in result["data_quality_notes"]


def test_loss_ratio_retains_agreeing_syndicate_narrative():
    result = {"prior_year_development_gbp_m": -7.5,
              "opening_reserves_gbp_m": 200.0,
              "direction": "release"}

    branch = _apply_loss_ratio_fallback(result, -20.0, "test-model")

    assert branch == "kept_agreement"
    assert result["prior_year_development_gbp_m"] == -7.5
    assert result["direction"] == "release"


def test_loss_ratio_overrides_sign_contradicting_narrative():
    result = {"prior_year_development_gbp_m": 7.5,
              "opening_reserves_gbp_m": 200.0,
              "direction": "strengthening"}

    branch = _apply_loss_ratio_fallback(result, -20.0, "test-model")

    assert branch == "overrode_contradiction"
    assert result["prior_year_development_gbp_m"] == -20.0
    assert result["prior_year_development_pct"] == -10.0
    assert result["direction"] == "release"
    assert "RAG DIRECTION OVERRIDE" in result["data_quality_notes"]
