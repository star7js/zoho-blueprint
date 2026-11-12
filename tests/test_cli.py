from __future__ import annotations

import pytest

from tests.conftest import BP_URL, DEAL, QUALIFY, state_body
from zoho_blueprint.cli import main


def test_state_command_prints_transitions(mocked, monkeypatch, capsys):
    monkeypatch.setenv("ZOHO_ACCESS_TOKEN", "t")
    mocked.get(BP_URL, json=state_body("Qualification", [QUALIFY]))

    assert main(["state", "Deals", DEAL]) == 0

    out = capsys.readouterr().out
    assert "Sales Process: Stage = 'Qualification'" in out
    assert "'Qualify' -> 'Needs Analysis'" in out
    assert "Decision_Maker" in out


def test_errors_print_and_exit_nonzero(mocked, monkeypatch, capsys):
    monkeypatch.setenv("ZOHO_ACCESS_TOKEN", "t")
    mocked.get(
        BP_URL,
        status=400,
        json={
            "code": "RECORD_NOT_IN_PROCESS",
            "details": {},
            "message": "record not in process",
            "status": "error",
        },
    )

    assert main(["state", "Deals", DEAL]) == 1
    assert "RECORD_NOT_IN_PROCESS" in capsys.readouterr().err


def test_missing_credentials_say_what_to_set(monkeypatch):
    for name in ("ZOHO_ACCESS_TOKEN", "ZOHO_CLIENT_ID", "ZOHO_CLIENT_SECRET", "ZOHO_REFRESH_TOKEN"):
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(SystemExit, match="ZOHO_ACCESS_TOKEN"):
        main(["state", "Deals", DEAL])
