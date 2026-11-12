"""Command line: ``zoho-blueprint state`` and ``zoho-blueprint audit``.

Credentials come from the environment: either ZOHO_ACCESS_TOKEN, or
ZOHO_CLIENT_ID, ZOHO_CLIENT_SECRET and ZOHO_REFRESH_TOKEN (with
ZOHO_ACCOUNTS_URL for data centers outside the US). ZOHO_API_DOMAIN sets
the API domain.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone

from zoho_blueprint.audit import audit_deals, report
from zoho_blueprint.client import (
    DEFAULT_ACCOUNTS_URL,
    DEFAULT_API_DOMAIN,
    BlueprintClient,
    RefreshTokenAuth,
    TokenProvider,
)
from zoho_blueprint.errors import ZohoBlueprintError


def _client() -> BlueprintClient:
    env = os.environ
    token: str | TokenProvider
    if env.get("ZOHO_ACCESS_TOKEN"):
        token = env["ZOHO_ACCESS_TOKEN"]
    else:
        missing = [
            k
            for k in ("ZOHO_CLIENT_ID", "ZOHO_CLIENT_SECRET", "ZOHO_REFRESH_TOKEN")
            if not env.get(k)
        ]
        if missing:
            raise SystemExit(f"set ZOHO_ACCESS_TOKEN, or {', '.join(missing)}")
        token = RefreshTokenAuth(
            env["ZOHO_CLIENT_ID"],
            env["ZOHO_CLIENT_SECRET"],
            env["ZOHO_REFRESH_TOKEN"],
            env.get("ZOHO_ACCOUNTS_URL") or DEFAULT_ACCOUNTS_URL,
        )
    return BlueprintClient(token, env.get("ZOHO_API_DOMAIN") or DEFAULT_API_DOMAIN)


def _state(args: argparse.Namespace) -> None:
    state = _client().get_state(args.module, args.record_id)
    print(f"{state.process_name}: {state.field_api_name} = {state.state!r}")
    for transition in state.transitions:
        note = "" if transition.criteria_matched else "  (criteria not met)"
        print(f"\n{transition.name!r} -> {transition.next_state!r}{note}")
        for f in transition.fields:
            flag = "reported mandatory" if f.reported_mandatory else ""
            print(f"    {f.api_name or f.label}  [{f.data_type}]  {flag}".rstrip())


def _audit(args: argparse.Namespace) -> None:
    expected = json.loads(args.expected_fields) if args.expected_fields else None
    since = datetime.now(timezone.utc) - timedelta(days=args.days)
    rows = audit_deals(_client(), args.entry_stage, since, expected, args.skip_name_containing)
    print(f"Deals created in the last {args.days} days, entry stage {args.entry_stage!r}\n")
    print(report(rows))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="zoho-blueprint", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    state = commands.add_parser("state", help="show a record's state and available transitions")
    state.add_argument("module", help="module API name, such as Deals")
    state.add_argument("record_id")
    state.set_defaults(run=_state)

    audit = commands.add_parser("audit", help="find Deals created past the Blueprint's entry stage")
    audit.add_argument(
        "--entry-stage",
        required=True,
        help='the stage Deals should start at, such as "Qualification"',
    )
    audit.add_argument(
        "--days", type=int, default=60, help="look-back window by Created_Time (default 60)"
    )
    audit.add_argument(
        "--expected-fields",
        help=(
            "JSON of stage -> fields a Deal there should have, "
            'such as \'{"Closed Won": ["Payment_Date"]}\''
        ),
    )
    audit.add_argument(
        "--skip-name-containing", help="leave out Deals whose name contains this, such as TEST"
    )
    audit.set_defaults(run=_audit)

    args = parser.parse_args(argv)
    try:
        args.run(args)
    except ZohoBlueprintError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
