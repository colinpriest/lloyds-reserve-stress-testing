"""The extraction suite recorder preserves failure diagnostics."""
from types import SimpleNamespace

import pytest

from scripts import record_tests


@pytest.mark.parametrize("code,output,expected", [
    (1, "FAILED tests/test_example.py::test_bad\n1 failed, 2 passed in 1s\n", True),
    (0, "2 passed in 1s\n", False),
])
def test_recorder_prints_pytest_output_only_for_failures(monkeypatch, capsys, code, output, expected):
    monkeypatch.setattr(record_tests.subprocess, "run", lambda *a, **k: SimpleNamespace(
        returncode=code, stdout=output, stderr=""))
    actual_code, counts, _, _, _ = record_tests.run()
    assert actual_code == code
    assert counts["failed"] == (1 if code else 0)
    emitted = capsys.readouterr().err
    assert ("FAILED tests/test_example.py::test_bad" in emitted) is expected
