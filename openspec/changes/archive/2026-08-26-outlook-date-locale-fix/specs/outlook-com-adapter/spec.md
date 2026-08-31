# Delta for Outlook COM Adapter

## ADDED Requirements

### Requirement: Locale-Invariant Restrict Date Literals

`OutlookCalendarAdapter._dasl_datetime()` MUST emit an `Items.Restrict()`
date-bound literal whose calendar-date interpretation is identical
regardless of the Outlook client's configured locale. The literal MUST
NOT rely on any ambiguous `MM/DD/YYYY`-vs-`DD/MM/YYYY` numeric order; it
MUST use a format Outlook's Jet/DASL engine parses the same way under
every locale (e.g. an ISO-ordered `yyyy-mm-dd HH:MM` literal, per the
locale-invariance evidence recorded in this change's design.md). Building
the literal MUST NOT depend on any locale-sensitive `strftime` directive
(day/month name or order) whose rendered output changes with the
process's or machine's locale setting.

#### Scenario: Transposition-prone range returns only its own bound days

- GIVEN a mocked `win32com.client` module whose Calendar folder's `Items` are seeded with events on 2026-06-08, 2026-06-09, and 2026-09-04
- WHEN `OutlookCalendarAdapter().search(date_from=2026-06-06T00:00:00, date_to=2026-06-09T23:59:59)` builds its `Restrict()` clause
- THEN the emitted literal for each bound encodes day `06`/`09` unambiguously (asserted via the chosen invariant format, not a `MM/DD` or `DD/MM` string)
- AND the returned events are only 2026-06-08 and 2026-06-09 — the 2026-09-04 event is excluded

#### Scenario: Full-month-crossing range is not misread as a two-day window

- GIVEN a mocked `win32com.client` module whose Calendar folder's `Items` are seeded with events spanning March and April 2026, and one event on 2026-12-03
- WHEN `OutlookCalendarAdapter().search(date_from=2026-03-12T00:00:00, date_to=2026-04-12T00:00:00)` builds its `Restrict()` clause
- THEN the emitted literals encode month `03`/day `12` and month `04`/day `12` respectively, in the chosen invariant order
- AND the returned events span March-April 2026 and exclude the 2026-12-03 event

#### Scenario: Already-safe range (day >= 13) keeps returning correct results

- GIVEN a mocked `win32com.client` module whose Calendar folder's `Items` are seeded with events between 2026-06-22 and 2026-06-25
- WHEN `OutlookCalendarAdapter().search(date_from=2026-06-20T00:00:00, date_to=2026-06-25T23:59:59)` is called
- THEN the returned events are unchanged from pre-fix behavior: 2026-06-22 through 2026-06-25

#### Scenario: Emitted literal is identical regardless of assumed locale

- GIVEN a fixed `datetime` value passed to `_dasl_datetime()`
- WHEN the function is invoked twice, simulating an `es-ES`-style (`DD/MM`) and an `en-US`-style (`MM/DD`) locale assumption (the literal itself carries no locale-sensitive component, so no actual OS locale switch is needed to prove this)
- THEN both invocations return the exact same string, and that string does not match the ambiguous `\d{2}/\d{2}/\d{4}` pattern used by the pre-fix implementation
