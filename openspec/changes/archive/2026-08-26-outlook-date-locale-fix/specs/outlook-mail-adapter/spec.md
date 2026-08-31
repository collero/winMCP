# Delta for Outlook Mail Adapter

## ADDED Requirements

### Requirement: Locale-Invariant Restrict Date Literals

`OutlookMailAdapter`'s `_dasl_datetime()` MUST emit an `Items.Restrict()`
date-bound literal (for `[ReceivedTime]`, `[SentOn]`, or
`[LastModificationTime]` clauses on mapped `folder` searches) whose
calendar-date interpretation is identical regardless of the Outlook
client's configured locale, mirroring the fix and format applied to
`tools/outlook_adapter.py::_dasl_datetime()` (same design.md
locale-invariance evidence). The literal MUST NOT rely on an ambiguous
`MM/DD/YYYY`-vs-`DD/MM/YYYY` numeric order. `folder_path`-resolved
searches are unaffected — they already skip `Restrict()` entirely and
filter dates in Python.

#### Scenario: Transposition-prone range returns only its own bound days

- GIVEN a mocked `win32com.client` module whose Inbox `Items` are seeded with messages received on 2026-06-08, 2026-06-09, and 2026-09-04
- WHEN `OutlookMailAdapter().search(folder="inbox", date_from=2026-06-06T00:00:00, date_to=2026-06-09T23:59:59)` builds its `[ReceivedTime]` `Restrict()` clause
- THEN the emitted literal for each bound encodes day `06`/`09` unambiguously (chosen invariant format, not `MM/DD`/`DD/MM`)
- AND the returned messages are only those from 2026-06-08 and 2026-06-09 — the 2026-09-04 message is excluded

#### Scenario: Full-month-crossing range is not misread as a two-day window

- GIVEN a mocked `win32com.client` module whose Sent Items `Items` are seeded with messages spanning March and April 2026, and one message on 2026-12-03
- WHEN `OutlookMailAdapter().search(folder="sent", date_from=2026-03-12T00:00:00, date_to=2026-04-12T00:00:00)` builds its `[SentOn]` `Restrict()` clause
- THEN the emitted literals encode month `03`/day `12` and month `04`/day `12` respectively, in the chosen invariant order
- AND the returned messages span March-April 2026 and exclude the 2026-12-03 message

#### Scenario: Already-safe range (day >= 13) keeps returning correct results

- GIVEN a mocked `win32com.client` module whose Inbox `Items` are seeded with messages between 2026-06-22 and 2026-06-25
- WHEN `OutlookMailAdapter().search(folder="inbox", date_from=2026-06-20T00:00:00, date_to=2026-06-25T23:59:59)` is called
- THEN the returned messages are unchanged from pre-fix behavior: 2026-06-22 through 2026-06-25

#### Scenario: Emitted literal is identical regardless of assumed locale

- GIVEN a fixed `datetime` value passed to the mail adapter's `_dasl_datetime()`
- WHEN the function is invoked twice, simulating an `es-ES`-style (`DD/MM`) and an `en-US`-style (`MM/DD`) locale assumption
- THEN both invocations return the exact same string, identical in format to `tools/outlook_adapter.py::_dasl_datetime()`'s output for the same input, and that string does not match the ambiguous `\d{2}/\d{2}/\d{4}` pattern used by the pre-fix implementation
