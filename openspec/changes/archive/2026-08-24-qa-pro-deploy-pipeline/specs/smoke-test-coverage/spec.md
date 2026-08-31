# Smoke Test Coverage Specification

## Purpose

`deploy/smoke_test.py` (run via `test.bat`, real `.venv`, real Outlook) is
the last gate before manual validation. It MUST exercise every registered
tool family, not just calendar, with pure verdict logic unit-testable via
a duck-typed fake server — no subprocess, no Outlook.

## Requirements

### Requirement: Expected Tool Set Matches Registered Tools

`EXPECTED_TOOLS` MUST equal the 7 registered tools: `calendar_search`,
`calendar_get_event`, `calendar_get_notes`, `task_search`, `task_get_task`,
`mail_search`, `mail_get_message`. `tools/list` MUST be validated against
this set; a missing tool fails the step, extras are only noted.

#### Scenario: A registered tool is missing from tools/list

- GIVEN a fake server whose `tools/list` response omits `mail_get_message`
- WHEN the tools/list step validates the response
- THEN the step fails, naming `mail_get_message` as missing

### Requirement: Per-Family Live Steps and Search-and-Chain

After `initialize`/`tools/list`, one live step runs per family:
`calendar_search`; `task_search` with no filters (valid — all optional);
`mail_search folder="inbox"` with a date bound; `mail_search
folder="sent"` with a date bound. A single pure helper drives all four:
>=1 hit chains the matching detail call
(`calendar_get_event`/`task_get_task`/`mail_get_message`) on the first
hit's `entryId`; 0 hits is PASS with a "no items to chain" note. A
handshake failure short-circuits all families as outright FAILED.

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

### Requirement: Per-Family Verdict Classification

Each family resolves to PASS, WARN, or FAIL:

| Condition | Result |
|---|---|
| Error text matches `OUTLOOK_UNAVAILABLE_HINTS` | WARN |
| Any other error, malformed response, or missing tool | FAIL |
| Otherwise | PASS |

#### Scenario: Outlook-unavailable error yields WARN, not FAIL

- GIVEN a stub server whose `mail_search(folder="sent", ...)` errors with "win32com is not available"
- WHEN the helper runs for the mail/sent family
- THEN the family result is WARN, and a different error message (e.g. "Restrict() DASL syntax error") yields FAIL instead

### Requirement: Pure Aggregate Verdict Function

A pure `aggregate_verdict(family_results)` function (no I/O) computes the
overall verdict per this table; `family_results` is a dict mapping family
name to that family's verdict value (`"pass"`/`"warning"`/`"fail"`); the
three returned strings MUST be preserved verbatim — `test.bat`/install
docs depend on them.

| family_results values | verdict |
|---|---|
| any FAIL present | `SMOKE TEST FAILED` |
| no FAIL, any WARN | `SMOKE TEST PASSED WITH WARNINGS` |
| all PASS | `SMOKE TEST PASSED` |

#### Scenario: Any FAIL wins over WARN

- GIVEN family results with verdict values `pass`, `warning`, and `fail` present
- WHEN `aggregate_verdict` is called
- THEN it returns `"SMOKE TEST FAILED"`

#### Scenario: WARN with no FAIL degrades the verdict

- GIVEN family results with verdict values `pass` and `warning` present, and no `fail`
- WHEN `aggregate_verdict` is called
- THEN it returns `"SMOKE TEST PASSED WITH WARNINGS"`

### Requirement: Human-Eyeball-Friendly Output

Console output MUST print one line per family result plus a single final
verdict line, matching the existing calendar-step format.

#### Scenario: Output includes one line per family and a final verdict

- GIVEN a completed run with 4 family results
- WHEN the script prints its summary
- THEN it prints one line per family, then one of the three verdict strings last

### Requirement: Live Execution Is Manual-Verification-Only

Running `smoke_test.py` against real `WinMCP.bat`/Outlook is NOT
unit-testable here. Only `aggregate_verdict` and the search-and-chain
helper are unit-tested (stdlib, Linux-runnable, stub-driven, no win32com).

#### Scenario: Manual verification on the Windows target

- GIVEN a real Windows machine with WinMCP installed and Outlook running
- WHEN a human double-clicks `test.bat`
- THEN they confirm the 4 family lines and final verdict visually — verified manually, not by pytest
