from __future__ import annotations

from datetime import datetime, timezone

from tests.conftest import BASE
from zoho_blueprint import audit_deals, classify, created_stage, report

ENTRY = "Qualification"
EXPECTED = {"Closed Won": ["Proposal_Date", "Won_Date"]}


def row(stage, at):
    return {"Stage": stage, "Last_Modified_Time": at}


def test_created_stage_is_the_oldest_row_whatever_the_order():
    history = [
        row("Closed Won", "2026-03-05T10:00:00+00:00"),
        row("Qualification", "2026-03-01T10:00:00+00:00"),
    ]
    assert created_stage(history) == "Qualification"
    assert created_stage([]) is None


def test_deal_that_walked_the_blueprint_is_not_direct():
    record = {
        "id": "1",
        "Stage": "Closed Won",
        "Created_Time": "2026-03-01T10:00:00+00:00",
        "Proposal_Date": "2026-03-03",
        "Won_Date": "2026-03-05",
    }
    history = [
        row("Qualification", "2026-03-01T10:00:00+00:00"),
        row("Closed Won", "2026-03-05T10:00:00+00:00"),
    ]

    audited = classify(record, history, ENTRY, EXPECTED)

    assert audited.direct is False
    assert audited.missing == []


def test_deal_created_at_closed_won_is_direct_and_lists_empty_fields():
    record = {"id": "2", "Stage": "Closed Won", "Created_Time": "2026-03-02T10:00:00+00:00"}

    audited = classify(record, [row("Closed Won", "2026-03-02T10:00:00+00:00")], ENTRY, EXPECTED)

    assert audited.direct is True
    assert audited.created_at_stage == "Closed Won"
    assert audited.missing == ["Proposal_Date", "Won_Date"]


def test_deal_created_late_then_moved_is_still_direct():
    record = {"id": "3", "Stage": "Closed Won", "Created_Time": "2026-03-02T10:00:00+00:00"}
    history = [
        row("Closed Won", "2026-03-04T10:00:00+00:00"),
        row("Negotiation/Review", "2026-03-02T10:00:00+00:00"),
    ]

    assert classify(record, history, ENTRY).created_at_stage == "Negotiation/Review"
    assert classify(record, history, ENTRY).direct is True


def test_no_history_is_not_called_direct():
    assert classify({"id": "4", "Stage": "Closed Won"}, [], ENTRY).direct is False


def test_report_lists_direct_creates_newest_first():
    rows = [
        classify(
            {"id": "5", "Stage": "Closed Won", "Created_Time": "2026-03-02T00:00:00Z"},
            [row("Closed Won", "2026-03-02T00:00:00Z")],
            ENTRY,
        ),
        classify(
            {"id": "6", "Stage": "Closed Lost", "Created_Time": "2026-03-09T00:00:00Z"},
            [row("Closed Lost", "2026-03-09T00:00:00Z")],
            ENTRY,
        ),
        classify(
            {"id": "7", "Stage": "Closed Won", "Created_Time": "2026-03-10T00:00:00Z"},
            [row("Qualification", "2026-03-10T00:00:00Z")],
            ENTRY,
        ),
    ]

    text = report(rows)

    assert "3 deals audited" in text
    assert "Most recent direct create: 2026-03-09" in text
    listed = [line.split()[0] for line in text.split("missing", 1)[1].splitlines() if line.strip()]
    assert listed == ["6", "5"]


def test_report_with_no_direct_creates():
    rows = [classify({"id": "8", "Stage": ENTRY}, [row(ENTRY, "2026-03-01T00:00:00Z")], ENTRY)]
    assert "No direct creates" in report(rows)


def test_audit_deals_reads_history_stops_at_cutoff_and_skips_names(mocked, client):
    mocked.get(
        f"{BASE}/Deals",
        json={
            "data": [
                {
                    "id": "10",
                    "Deal_Name": "Acme renewal",
                    "Stage": "Closed Won",
                    "Created_Time": "2026-03-10T09:00:00+00:00",
                },
                {
                    "id": "11",
                    "Deal_Name": "TEST - ignore",
                    "Stage": "Closed Won",
                    "Created_Time": "2026-03-09T09:00:00+00:00",
                },
                {
                    "id": "12",
                    "Deal_Name": "Globex",
                    "Stage": "Qualification",
                    "Created_Time": "2026-03-08T09:00:00+00:00",
                },
                {
                    "id": "13",
                    "Deal_Name": "Too old",
                    "Stage": "Closed Won",
                    "Created_Time": "2026-01-01T09:00:00+00:00",
                },
            ],
            "info": {"more_records": False},
        },
    )
    mocked.get(
        f"{BASE}/Deals/10/Stage_History",
        json={"data": [row("Closed Won", "2026-03-10T09:00:00+00:00")]},
    )
    mocked.get(
        f"{BASE}/Deals/12/Stage_History",
        json={"data": [row("Qualification", "2026-03-08T09:00:00+00:00")]},
    )

    rows = audit_deals(client, ENTRY, datetime(2026, 3, 1, tzinfo=timezone.utc), EXPECTED, "test")

    assert [(r.id, r.direct) for r in rows] == [("10", True), ("12", False)]
    assert rows[0].missing == ["Proposal_Date", "Won_Date"]
    fields = mocked.calls[0].request.url
    assert "Proposal_Date" in fields and "Won_Date" in fields
