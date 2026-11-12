from __future__ import annotations

import json

import pytest
import responses

from tests.conftest import BASE, BP_URL, CLOSE, DEAL, PROPOSE, QUALIFY, state_body
from zoho_blueprint import (
    BlueprintClient,
    MandatoryFieldsMissing,
    PartialSave,
    RecordInBlueprint,
    RecordNotInProcess,
    RefreshTokenAuth,
    TransitionNotAvailable,
    ZohoAPIError,
)

SUCCESS = {
    "code": "SUCCESS",
    "details": {},
    "message": "transition updated successfully",
    "status": "success",
}


def test_get_state_parses_process_and_transitions(mocked, client):
    mocked.get(BP_URL, json=state_body("Qualification", [QUALIFY, CLOSE]))

    state = client.get_state("Deals", DEAL)

    assert state.process_name == "Sales Process"
    assert state.field_api_name == "Stage"
    assert state.state == "Qualification"
    assert state.transition_names == ["Qualify", "Close Won"]
    qualify = state.transition("Qualify")
    assert qualify is not None and qualify.next_state == "Needs Analysis"
    assert [f.api_name for f in qualify.fields] == ["Budget_Notes", "Decision_Maker"]
    assert not any(f.reported_mandatory for f in qualify.fields)
    assert mocked.calls[0].request.headers["Authorization"] == "Zoho-oauthtoken test-token"


def test_execute_by_name_looks_up_the_transition_and_sends_its_id(mocked, client):
    mocked.get(BP_URL, json=state_body("Qualification", [QUALIFY]))
    mocked.put(BP_URL, json=SUCCESS)

    result = client.execute("Deals", DEAL, "Qualify", {"Budget_Notes": "Confirmed"})

    assert result["code"] == "SUCCESS"
    assert json.loads(mocked.calls[1].request.body) == {
        "blueprint": [{"transition_id": QUALIFY["id"], "data": {"Budget_Notes": "Confirmed"}}]
    }


def test_execute_unknown_transition_names_what_is_available(mocked, client):
    mocked.get(BP_URL, json=state_body("Qualification", [QUALIFY, CLOSE]))

    with pytest.raises(TransitionNotAvailable) as raised:
        client.execute("Deals", DEAL, "Send Proposal")

    assert raised.value.state == "Qualification"
    assert raised.value.available == ["Qualify", "Close Won"]


@pytest.mark.parametrize(
    "body",
    [
        {
            "code": "MANDATORY_NOT_FOUND",
            "details": {"api_name": "Decision_Maker"},
            "message": "mandatory param missing",
            "status": "error",
        },
        {
            "code": "INVALID_DATA",
            "details": {"api_name": "Decision_Maker"},
            "message": "mandatory param missing",
            "status": "error",
        },
    ],
    ids=["MANDATORY_NOT_FOUND", "INVALID_DATA"],
)
def test_missing_required_fields_raise_with_the_field_names(mocked, client, body):
    """The GET reported every field as optional; the PUT says otherwise."""
    mocked.get(BP_URL, json=state_body("Qualification", [QUALIFY]))
    mocked.put(BP_URL, status=400, json=body)

    with pytest.raises(MandatoryFieldsMissing) as raised:
        client.execute("Deals", DEAL, "Qualify", {"Budget_Notes": "Confirmed"})

    assert raised.value.fields == ["Decision_Maker"]
    assert raised.value.status == 400
    assert "Decision_Maker" in str(raised.value)


def test_partial_save_is_an_error_not_a_success(mocked, client):
    mocked.get(BP_URL, json=state_body("Qualification", [QUALIFY]))
    mocked.put(
        BP_URL,
        json={
            "code": "SUCCESS",
            "details": {},
            "message": "transition saved partially",
            "status": "success",
        },
    )

    with pytest.raises(PartialSave) as raised:
        client.execute("Deals", DEAL, "Qualify")

    assert raised.value.transition == "Qualify"


def test_walk_runs_each_transition_in_order(mocked, client):
    mocked.get(BP_URL, json=state_body("Qualification", [QUALIFY]))
    mocked.put(BP_URL, json=SUCCESS)
    mocked.get(BP_URL, json=state_body("Needs Analysis", [PROPOSE]))
    mocked.put(BP_URL, json=SUCCESS)
    mocked.get(BP_URL, json=state_body("Proposal/Price Quote", [CLOSE]))

    final = client.walk(
        "Deals", DEAL, ["Qualify", "Send Proposal"], {"Qualify": {"Budget_Notes": "Confirmed"}}
    )

    assert final.state == "Proposal/Price Quote"
    puts = [json.loads(c.request.body) for c in mocked.calls if c.request.method == "PUT"]
    assert puts == [
        {"blueprint": [{"transition_id": QUALIFY["id"], "data": {"Budget_Notes": "Confirmed"}}]},
        {"blueprint": [{"transition_id": PROPOSE["id"], "data": {}}]},
    ]


def test_walk_stops_at_a_step_that_is_not_available(mocked, client):
    mocked.get(BP_URL, json=state_body("Qualification", [QUALIFY]))
    mocked.put(BP_URL, json=SUCCESS)
    mocked.get(BP_URL, json=state_body("Needs Analysis", [PROPOSE]))

    with pytest.raises(TransitionNotAvailable) as raised:
        client.walk("Deals", DEAL, ["Qualify", "Close Won"])

    assert raised.value.state == "Needs Analysis"
    assert raised.value.available == ["Send Proposal"]


def test_record_not_in_process(mocked, client):
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

    with pytest.raises(RecordNotInProcess):
        client.get_state("Deals", DEAL)


def test_error_inside_data_list_is_raised(mocked, client):
    """Record APIs put errors in the first item of ``data``."""
    url = f"{BASE}/Deals/{DEAL}"
    mocked.put(
        url,
        status=202,
        json={
            "data": [
                {
                    "code": "RECORD_IN_BLUEPRINT",
                    "details": {},
                    "message": "record in blueprint",
                    "status": "error",
                }
            ]
        },
    )

    with pytest.raises(RecordInBlueprint):
        client.request("PUT", f"/Deals/{DEAL}", json={"data": [{"Stage": "Closed Won"}]})


def test_unknown_http_error_keeps_status(mocked, client):
    mocked.get(BP_URL, status=500, body="oops")

    with pytest.raises(ZohoAPIError) as raised:
        client.get_state("Deals", DEAL)

    assert raised.value.status == 500


def test_iter_records_follows_page_tokens(mocked, client):
    url = f"{BASE}/Deals"
    mocked.get(
        url,
        json={
            "data": [{"id": "1"}, {"id": "2"}],
            "info": {"more_records": True, "next_page_token": "abc"},
        },
    )
    mocked.get(url, json={"data": [{"id": "3"}], "info": {"more_records": False}})

    ids = [r["id"] for r in client.iter_records("Deals", ["Stage"])]

    assert ids == ["1", "2", "3"]
    assert "page_token=abc" in mocked.calls[1].request.url


def test_204_is_an_empty_result(mocked, client):
    mocked.get(f"{BASE}/Deals/{DEAL}/Stage_History", status=204)

    assert client.stage_history(DEAL) == []


TOKEN_URL = "https://accounts.zoho.com/oauth/v2/token"


def test_refresh_token_auth_caches_until_invalidated(mocked):
    mocked.post(TOKEN_URL, json={"access_token": "first", "expires_in": 3600})
    mocked.post(TOKEN_URL, json={"access_token": "second", "expires_in": 3600})
    auth = RefreshTokenAuth("id", "secret", "refresh")

    assert auth() == "first"
    assert auth() == "first"
    auth.invalidate()
    assert auth() == "second"


def test_expired_token_is_refreshed_and_the_request_retried(mocked):
    mocked.post(TOKEN_URL, json={"access_token": "stale", "expires_in": 3600})
    mocked.get(
        BP_URL,
        status=401,
        json={
            "code": "INVALID_TOKEN",
            "details": {},
            "message": "invalid oauth token",
            "status": "error",
        },
    )
    mocked.post(TOKEN_URL, json={"access_token": "fresh", "expires_in": 3600})
    mocked.get(BP_URL, json=state_body("Qualification", []))
    client = BlueprintClient(RefreshTokenAuth("id", "secret", "refresh"))

    assert client.get_state("Deals", DEAL).state == "Qualification"
    gets = [c for c in mocked.calls if c.request.method == "GET"]
    assert gets[-1].request.headers["Authorization"] == "Zoho-oauthtoken fresh"


def test_failed_refresh_raises(mocked):
    mocked.post(TOKEN_URL, status=400, json={"error": "invalid_code"})

    with pytest.raises(ZohoAPIError) as raised:
        RefreshTokenAuth("id", "secret", "refresh")()

    assert raised.value.code == "invalid_code"


def test_api_domain_and_version_are_configurable():
    with responses.RequestsMock() as rsps:
        rsps.get(
            f"https://www.zohoapis.eu/crm/v7/Deals/{DEAL}/actions/blueprint",
            json=state_body("Qualification", []),
        )
        BlueprintClient("t", api_domain="https://www.zohoapis.eu/", version="v7").get_state(
            "Deals", DEAL
        )
