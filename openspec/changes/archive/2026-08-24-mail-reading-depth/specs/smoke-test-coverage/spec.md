# Delta for Smoke Test Coverage

## MODIFIED Requirements

### Requirement: Per-Family Live Steps and Search-and-Chain

After `initialize`/`tools/list`, one live step runs per family:
`calendar_search`; `task_search` with no filters (valid — all optional);
`mail_search folder="inbox"` with a date bound; `mail_search
folder="sent"` with a date bound; `mail_search folder="drafts"` with a date
bound. A single pure helper drives all five: >=1 hit chains the matching
detail call (`calendar_get_event`/`task_get_task`/`mail_get_message`) on
the first hit's `entryId`; 0 hits is PASS with a "no items to chain" note,
per the existing rule — unchanged for the new `mail-drafts` family. A
handshake failure short-circuits all families as outright FAILED.
`EXPECTED_TOOLS` and the three verdict strings are unaffected by this
addition.
(Previously: four families — `calendar`, `task`, `mail/inbox`, `mail/sent`
— no `mail-drafts` family.)

#### Scenario: Search hit chains the detail call

- GIVEN a stub server whose `mail_search(folder="inbox", ...)` returns one hit with `entryId="E1"`
- WHEN the helper runs for the mail/inbox family
- THEN `mail_get_message` is called with `entryId="E1"` and the family result is PASS

#### Scenario: Empty search result passes without chaining

- GIVEN a stub server whose `task_search()` returns zero hits
- WHEN the helper runs for the task family
- THEN no detail call is made and the family result is PASS with a "no items to chain" note

#### Scenario: Initialize failure short-circuits all families

- GIVEN a fake server that returns a JSON-RPC error for `initialize`
- WHEN the smoke test runs
- THEN the run FAILS before any family step runs

#### Scenario: mail-drafts family with zero hits passes without chaining

- GIVEN a stub server whose `mail_search(folder="drafts", ...)` returns zero hits
- WHEN the helper runs for the `mail-drafts` family
- THEN no `mail_get_message` call is made and the family result is PASS with a "no items to chain" note

#### Scenario: mail-drafts family with a hit chains mail_get_message

- GIVEN a stub server whose `mail_search(folder="drafts", ...)` returns one hit with `entryId="D1"`
- WHEN the helper runs for the `mail-drafts` family
- THEN `mail_get_message` is called with `entryId="D1"` and the family result is PASS
