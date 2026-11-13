# zoho-blueprint

Run Zoho CRM Blueprint transitions properly from Python, and find the records that skipped them.

## The problem

A [Blueprint](https://www.zoho.com/crm/tutorials/blueprint/overview.html) is how a Zoho CRM org enforces its sales process: each move from one stage to the next asks for the right fields, runs its checks, stamps its dates and fires its automations.

But when code creates a Deal through the API, it can set the Stage straight to "Closed Won", and Zoho accepts it. The Deal lands at the end of the process with none of that done: no required fields, no checks, no dates, no automations. Nothing errors. Your reports are just quietly wrong, and from Closed Won only an admin can move the Deal back.

Integrations, import scripts and AI agents that log deals fall into this easily, because creating a record is the obvious API call and the Blueprint's own API makes doing it properly awkward:

- it reports a transition's fields as optional, then refuses to run the transition without them;
- a transition that didn't happen can come back as a success ("transition saved partially");
- each step is a separate call, so moving a record through five stages is five rounds of looking up IDs and fields.

## What this does

- **`walk()`** moves a record through its transitions in order, the way a person clicking through Zoho would, so every check and automation runs.
- **Clear errors** when Zoho refuses: which fields are missing, whether a save was only partial, which transitions are available from where the record is.
- **`zoho-blueprint audit`** finds the Deals that were created past the start of the process, and which fields they're missing, so you can fix them.

It's for developers and consultants who write to Zoho CRM from code: integrations, sync jobs, imports, voice or AI agents that log deals.

> Unofficial. Not affiliated with or endorsed by Zoho Corporation.

## Install

```bash
pip install zoho-blueprint
```

Python 3.10+. The only dependency is `requests`.

## Quick start

```python
from zoho_blueprint import BlueprintClient, RefreshTokenAuth

auth = RefreshTokenAuth(client_id, client_secret, refresh_token)  # refreshes hourly tokens for you
zoho = BlueprintClient(auth)  # api_domain="https://www.zohoapis.eu" for other data centers

state = zoho.get_state("Deals", deal_id)
print(state.state)  # "Qualification"
print(state.transition_names)  # ["Qualify", "Close Lost"]

# Run one transition by name, with the fields it needs
zoho.execute("Deals", deal_id, "Qualify", {"Budget_Notes": "Confirmed"})

# Or walk a record through several, the way a person would in the UI
zoho.walk(
    "Deals",
    deal_id,
    ["Qualify", "Send Proposal", "Close Won"],
    data={"Qualify": {"Budget_Notes": "Confirmed"}, "Close Won": {"Won_Date": "2026-03-05"}},
)
```

Every step's checks, date stamps and after-actions run, exactly as they would for a person clicking through.

A plain access token works too: `BlueprintClient("1000.abc...")`.

## Clear errors

| Zoho says | You get |
| --- | --- |
| `MANDATORY_NOT_FOUND` / "mandatory param missing" | `MandatoryFieldsMissing`, with `.fields` when Zoho names them |
| "transition saved partially" (sent as a success) | `PartialSave`: the data was saved but the record did not move |
| The transition isn't available from this state | `TransitionNotAvailable`, with `.state` and `.available` |
| `RECORD_NOT_IN_PROCESS` | `RecordNotInProcess` |
| `RECORD_IN_BLUEPRINT` (a plain update touched a Blueprint field) | `RecordInBlueprint` |
| `RECORD_LOCKED` | `RecordLocked` |
| Anything else | `ZohoAPIError`, with `.code`, `.message`, `.details` and `.status` |

All of them derive from `ZohoBlueprintError`. An expired access token is refreshed and the request retried once.

## Find records that skipped the Blueprint

A Deal's Stage History records the stage it was created at as its oldest row. If that isn't your Blueprint's entry stage, the Deal was created directly at a later stage and never went through the transitions before it.

```bash
export ZOHO_CLIENT_ID=... ZOHO_CLIENT_SECRET=... ZOHO_REFRESH_TOKEN=...
zoho-blueprint audit --entry-stage "Qualification" --days 90 \
    --expected-fields '{"Closed Won": ["Won_Date", "Payment_Status"]}' \
    --skip-name-containing TEST
```

```
42 deals audited
current stage                         walked  direct
Closed Lost                                6       1
Closed Won                                21      14

Most recent direct create: 2026-03-09

deal id               created     created at                        now                               missing
1000000000000000123   2026-03-09  Closed Won                        Closed Won                        Won_Date, Payment_Status
...
```

It only reads, and prints Deal ids, not names or amounts. It makes one Stage History request per Deal, so mind your API credits on a long window. From Python, use `audit_deals()` and `report()`.

To see a record's state and its transitions' fields:

```bash
zoho-blueprint state Deals 1000000000000000123
```

## Things to know about the Blueprint API

These are why this library exists.

1. **Creating a record past the entry stage skips the Blueprint.** `POST /Deals` with `"Stage": "Closed Won"` succeeds, and the Deal sits in the Blueprint at Closed Won with none of the transitions' required fields, checks, date stamps or after-actions done. Updating Stage afterwards is refused with `RECORD_IN_BLUEPRINT`, so only creates are unguarded. Create records at the entry stage and use `walk()`.
2. **Don't trust the GET's `mandatory` flags.** The fields Zoho returns for a transition can all report as not mandatory while executing it is refused with "mandatory param missing". `TransitionField.reported_mandatory` keeps what the GET said, under that name on purpose. Treat `MandatoryFieldsMissing` as the truth.
3. **A partial save looks like a success.** If you send fewer fields than a transition needs, Zoho can answer `"transition saved partially"` with a success status ([docs](https://www.zoho.com/crm/developer/docs/api/v8/update-blueprint.html)). The record does not move. This library raises `PartialSave`.
4. **One transition per request.** The update endpoint runs a single transition at a time, so multi-step moves are a sequence of calls; `walk()` re-reads the record between steps.

Behavior observed on API v8 in 2026. If Zoho changes any of it, please open an issue.

## Limitations

- **The audit covers Deals only.** It relies on the Deals Stage History, which other modules don't have.
- **`walk()` follows the path you give it.** It doesn't work out a route between two states for you.
- **Attachments and checklists** on transitions aren't handled yet; only field data is sent.
- **Synchronous only**, built on `requests`.
- **Zoho can change the API's behavior.** The quirks above were observed on API v8 in 2026.

## Scopes

Reading state needs `ZohoCRM.modules.{module}.READ`; running transitions needs `ZohoCRM.modules.{module}.UPDATE` (or `ZohoCRM.modules.ALL`). The audit reads Deals and their Stage History.

## Development

```bash
uv sync
uv run pytest
uv run ruff check && uv run ruff format --check
uv run mypy
```

Tests run offline against recorded response shapes from Zoho's public docs. No Zoho account needed.

## License

MIT
