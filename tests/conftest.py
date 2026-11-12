"""Shared fixtures. Response bodies follow the shapes in Zoho's public API docs;
every id and value is made up."""

from __future__ import annotations

from typing import Any

import pytest
import responses

from zoho_blueprint import BlueprintClient

BASE = "https://www.zohoapis.com/crm/v8"
DEAL = "1000000000000000001"
BP_URL = f"{BASE}/Deals/{DEAL}/actions/blueprint"


def state_body(state: str, transitions: list[dict[str, Any]]) -> dict[str, Any]:
    """A GET /{module}/{id}/actions/blueprint body."""
    return {
        "blueprint": {
            "process_info": {
                "name": "Sales Process",
                "api_name": "Stage",
                "field_name": "Stage",
                "field_value": state,
                "id": "2000000000000000001",
            },
            "transitions": transitions,
        }
    }


def transition(
    tid: str, name: str, next_state: str, fields: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    return {
        "id": tid,
        "name": name,
        "next_field_value": next_state,
        "criteria_matched": True,
        "type": "manual",
        "next_transitions": [],
        "fields": fields or [],
    }


def text_field(api_name: str, label: str, mandatory: bool = False) -> dict[str, Any]:
    return {
        "api_name": api_name,
        "display_label": label,
        "data_type": "text",
        "system_mandatory": False,
        "mandatory": mandatory,
        "read_only": False,
        "_type": "field",
    }


QUALIFY = transition(
    "3000000000000000001",
    "Qualify",
    "Needs Analysis",
    [text_field("Budget_Notes", "Budget Notes"), text_field("Decision_Maker", "Decision Maker")],
)
PROPOSE = transition("3000000000000000002", "Send Proposal", "Proposal/Price Quote")
CLOSE = transition("3000000000000000003", "Close Won", "Closed Won")


@pytest.fixture
def mocked() -> Any:
    with responses.RequestsMock(assert_all_requests_are_fired=True) as rsps:
        yield rsps


@pytest.fixture
def client() -> BlueprintClient:
    return BlueprintClient("test-token")
