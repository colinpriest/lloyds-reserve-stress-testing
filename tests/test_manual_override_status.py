"""A legacy status flag does not prove the filing's inception year."""

import json
from pathlib import Path

from manual_override import get_current_status


def test_2357_legacy_stub_does_not_display_unknown_inception_as_first_year():
    root = Path(__file__).resolve().parents[1]
    data = json.loads((root / "pdf_extraction" / "syndicate_2357_2014.json").read_text(encoding="utf-8"))
    assert get_current_status(data) == "No development table; eligibility unresolved"
    assert get_current_status({**data, "manual_override_status": "excluded"}) == "Excluded"
    assert get_current_status({**data, "syndicate": 2358}) == "First Year Syndicate"
    assert get_current_status({**data, "inception_year": 2014}) == "First Year Syndicate"
