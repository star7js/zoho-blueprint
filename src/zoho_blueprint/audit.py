"""Find Deals that skipped their Blueprint.

Zoho accepts a Deal created with its Stage already at a later value, such as
"Closed Won", even while a Blueprint governs Deals. Such a Deal never ran the
transitions before that stage, so their checks, required fields, date stamps
and after-actions never happened.

A Deal's Stage History records the stage it was created at as its oldest row.
A Deal that entered the Blueprint properly starts at the entry stage; one
that starts anywhere else was created directly at that stage.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from zoho_blueprint.client import BlueprintClient


@dataclass(frozen=True)
class AuditRow:
    """One Deal, as the audit sees it."""

    id: str
    created: str
    stage: str | None
    created_at_stage: str | None
    direct: bool
    missing: list[str] = field(default_factory=list)


def created_stage(history: Iterable[Mapping[str, Any]]) -> str | None:
    """The stage a Deal was created at: its oldest Stage History row."""
    rows = [row for row in history if row.get("Stage")]
    if not rows:
        return None
    rows.sort(key=lambda row: str(row.get("Last_Modified_Time") or ""))
    return str(rows[0]["Stage"])


def classify(
    record: Mapping[str, Any],
    history: Iterable[Mapping[str, Any]],
    entry_stage: str,
    expected_fields: Mapping[str, Sequence[str]] | None = None,
) -> AuditRow:
    """Audit one Deal.

    Args:
        record: The Deal, with at least ``id``, ``Stage`` and ``Created_Time``.
        history: The Deal's Stage History rows.
        entry_stage: The stage a Deal should be created at.
        expected_fields: For each stage, fields a Deal that reached it through
            the Blueprint would have filled. Empty ones are listed in
            ``missing``.
    """
    first = created_stage(history)
    stage = record.get("Stage")
    expected = (expected_fields or {}).get(str(stage), ())
    return AuditRow(
        id=str(record.get("id")),
        created=str(record.get("Created_Time") or "")[:10],
        stage=stage,
        created_at_stage=first,
        direct=first is not None and first != entry_stage,
        missing=[name for name in expected if not record.get(name)],
    )


def audit_deals(
    client: BlueprintClient,
    entry_stage: str,
    since: datetime,
    expected_fields: Mapping[str, Sequence[str]] | None = None,
    skip_name_containing: str | None = None,
) -> list[AuditRow]:
    """Audit every Deal created since a date. Reads only; writes nothing.

    Makes one Stage History request per Deal, so mind your API credits on a
    large window.

    Args:
        since: Deals created before this are not read. Give it a time zone,
            or it is compared with Zoho's local times as if it had theirs.
        skip_name_containing: Deals whose name contains this text, in any
            case, are left out (test records, say).
    """
    expected_fields = expected_fields or {}
    wanted = {"Deal_Name", "Stage", "Created_Time"}
    for names in expected_fields.values():
        wanted.update(names)
    cutoff = since.isoformat(timespec="seconds")[:19]
    skip = (skip_name_containing or "").upper()

    rows: list[AuditRow] = []
    for record in client.iter_records("Deals", sorted(wanted)):
        if str(record.get("Created_Time") or "")[:19] < cutoff:
            break
        if skip and skip in str(record.get("Deal_Name") or "").upper():
            continue
        history = client.stage_history(str(record["id"]))
        rows.append(classify(record, history, entry_stage, expected_fields))
    return rows


def report(rows: Sequence[AuditRow]) -> str:
    """A plain-text report: counts per stage, then each direct create."""
    lines = [f"{len(rows)} deals audited", f"{'current stage':<36}{'walked':>8}{'direct':>8}"]
    for stage in sorted({row.stage or "?" for row in rows}):
        here = [row for row in rows if (row.stage or "?") == stage]
        direct = sum(row.direct for row in here)
        lines.append(f"{stage:<36}{len(here) - direct:>8}{direct:>8}")

    direct_rows = sorted((r for r in rows if r.direct), key=lambda r: r.created, reverse=True)
    if not direct_rows:
        lines.append("\nNo direct creates: every deal entered the Blueprint at the entry stage.")
        return "\n".join(lines)
    lines.append(f"\nMost recent direct create: {direct_rows[0].created}")
    lines.append(f"\n{'deal id':<22}{'created':<12}{'created at':<34}{'now':<34}missing")
    for row in direct_rows:
        lines.append(
            f"{row.id:<22}{row.created:<12}{(row.created_at_stage or '?'):<34}"
            f"{(row.stage or '?'):<34}{', '.join(row.missing) or '-'}"
        )
    return "\n".join(lines)
