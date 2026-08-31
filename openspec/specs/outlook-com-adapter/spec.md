# Outlook COM Adapter Specification

## Purpose

Isolate all Outlook COM access behind a single adapter interface (protocol) so
tool logic and its tests never depend on `win32com` being importable — required
because the dev/CI host is WSL2 Linux while the runtime target is Windows.

## Requirements

### Requirement: Adapter Interface

The system MUST define an adapter interface (e.g. a `Protocol`/ABC) exposing
`search(from, to, subject) -> list[EventSummary]` and
`get_event(entry_id) -> EventDetail`. Both the real (`win32com`-backed) and fake
(test) implementations MUST satisfy this interface.

#### Scenario: Fake adapter satisfies the interface

- GIVEN a fake adapter implementing `search()` and `get_event()` per the protocol
- WHEN a tool is called with the fake adapter injected
- THEN the tool code runs unchanged, with no reference to `win32com` on the call path

### Requirement: Lazy COM Import

The real adapter implementation MUST import `win32com.client` lazily, inside its
own module/functions — never at the top level of `server.py`, `tools/`, or
`models/` modules — so the test suite runs on Linux without `win32com` installed.

#### Scenario: Test suite runs without win32com installed

- GIVEN this WSL2 dev environment where `import win32com` fails
- WHEN `python3.12 -m pytest -q` runs the full suite using only the fake adapter
- THEN all tests pass and no test triggers a `win32com` import

### Requirement: Per-Thread COM Initialization

Every real Outlook adapter (`OutlookCalendarAdapter`, `OutlookTaskAdapter`,
`OutlookMailAdapter`) MUST call `pythoncom.CoInitialize()` on the current
thread before issuing any COM `Dispatch()` call. `pythoncom` MUST be
imported lazily, inside the adapter's own dispatch helper — never at the
top level of `server.py`, `tools/`, or `models/` modules — mirroring the
existing `win32com.client` lazy-import requirement. This is required
because FastMCP dispatches tool calls across a worker-thread pool, and COM
apartments are thread-local: a thread that has never called
`CoInitialize()` fails any COM call with
`(-2147221008, 'CoInitialize has not been called.', ...)`.
`CoInitialize()` MUST NOT be paired with a matching `CoUninitialize()` in
the adapter, since FastMCP worker threads are long-lived and reused across
calls, and `CoInitialize()` is idempotent per thread (a repeat call on an
already-initialized thread returns `S_FALSE` and is harmless).

#### Scenario: CoInitialize called before Dispatch on search

- GIVEN a fake `pythoncom` module injected into `sys.modules` with a mock
  `CoInitialize`, and a fake `win32com.client` module with a mock
  `Dispatch`
- WHEN a real adapter's `search()` method is called
- THEN `pythoncom.CoInitialize()` is called before
  `win32com.client.Dispatch("Outlook.Application")`

#### Scenario: CoInitialize called before Dispatch on a get call

- GIVEN a fake `pythoncom` module injected into `sys.modules` with a mock
  `CoInitialize`, and a fake `win32com.client` module with a mock
  `Dispatch`
- WHEN a real adapter's get method (`get_event`/`get_task`/`get_message`)
  is called
- THEN `pythoncom.CoInitialize()` is called before
  `win32com.client.Dispatch("Outlook.Application")`

#### Scenario: pythoncom not imported at module level

- GIVEN this WSL2 dev environment where `import pythoncom` fails (module
  not installed)
- WHEN the adapter module (`tools/outlook_adapter.py`,
  `tools/task_adapter.py`, or `tools/mail_adapter.py`) is imported/reloaded
  with `pythoncom` absent from `sys.modules`
- THEN the import succeeds and `pythoncom` is not added to `sys.modules`

#### Scenario: Failed pythoncom import still maps to OutlookUnavailableError

- GIVEN `pythoncom` is not importable on this platform
- WHEN a real adapter's `search()` or get method is called
- THEN the adapter raises `OutlookUnavailableError`, not a bare
  `ImportError`

### Requirement: Real Adapter COM Access

On Windows, the real adapter MUST connect via
`win32com.client.Dispatch("Outlook.Application")`, `GetNamespace("MAPI")`, and
`GetDefaultFolder(9)` (default Calendar folder) to satisfy `search()` and
`get_event()`.

#### Scenario: Dispatch failure raises a typed error

- GIVEN `win32com.client.Dispatch("Outlook.Application")` raises (Outlook not
  installed or not running) — simulated in tests via a fake adapter configured
  to raise `OutlookUnavailableError` from `search()`/`get_event()`
- WHEN either adapter method is called
- THEN the adapter raises `OutlookUnavailableError` (or a documented subclass),
  not a bare/unhandled COM exception, so calling tools can map it to an MCP error

### Requirement: Adapter Selection at Runtime

The server MUST select the real adapter only when `win32com` is importable at
startup/first use; otherwise tool calls MUST fail with a clear runtime error
rather than crashing at module import time.

#### Scenario: win32com not importable

- GIVEN the server runs on a host without `win32com` installed (e.g. this Linux dev host)
- WHEN a tool invokes the adapter
- THEN the tool returns a clear error stating the Outlook adapter is unavailable
  on this platform, and the server process itself does not crash at import time

### Requirement: Configurable Folder Ids

Every real Outlook adapter (`OutlookCalendarAdapter`, `OutlookTaskAdapter`,
`OutlookMailAdapter`) MUST resolve the Outlook `GetDefaultFolder()` id(s) it
uses from `config/settings.yaml` (via `tools/settings.py::load_settings()`)
at COM-access time — i.e., freshly on each `search()`/get-method call, not
cached at construction or module-import time — falling back to the
documented default when the corresponding key is absent from settings or
settings.yaml is unreadable:

- `OutlookCalendarAdapter` reads `calendar_folder_id` (default `9`,
  olFolderCalendar).
- `OutlookTaskAdapter` reads `tasks_folder_id` (default `13`,
  olFolderTasks).
- `OutlookMailAdapter` reads `inbox_folder_id` (default `6`, olFolderInbox)
  when resolving the inbox folder, and `sent_folder_id` (default `5`,
  olFolderSentMail) when resolving the sent folder.

#### Scenario: Configured calendar folder id is used

- GIVEN a fake `win32com.client` module injected into `sys.modules`, and
  `tools.outlook_adapter.load_settings` mocked to return
  `{"calendar_folder_id": 42}`
- WHEN `OutlookCalendarAdapter().search(...)` is called
- THEN `namespace.GetDefaultFolder(42)` is called, not the hardcoded
  default

#### Scenario: Absent calendar folder id key falls back to the default

- GIVEN a fake `win32com.client` module injected into `sys.modules`, and
  `tools.outlook_adapter.load_settings` mocked to return `{}`
- WHEN `OutlookCalendarAdapter().search(...)` is called
- THEN `namespace.GetDefaultFolder(9)` is called

#### Scenario: Configured tasks folder id is used

- GIVEN a fake `win32com.client` module injected into `sys.modules`, and
  `tools.task_adapter.load_settings` mocked to return
  `{"tasks_folder_id": 99}`
- WHEN `OutlookTaskAdapter().search()` is called
- THEN `namespace.GetDefaultFolder(99)` is called, not the hardcoded
  default

#### Scenario: Absent tasks folder id key falls back to the default

- GIVEN a fake `win32com.client` module injected into `sys.modules`, and
  `tools.task_adapter.load_settings` mocked to return `{}`
- WHEN `OutlookTaskAdapter().search()` is called
- THEN `namespace.GetDefaultFolder(13)` is called

#### Scenario: Configured inbox/sent folder ids are used

- GIVEN a fake `win32com.client` module injected into `sys.modules`, and
  `tools.mail_adapter.load_settings` mocked to return
  `{"inbox_folder_id": 61, "sent_folder_id": 51}`
- WHEN `OutlookMailAdapter().search(MailFolder.INBOX, ...)` is called
- THEN `namespace.GetDefaultFolder(61)` is called
- WHEN `OutlookMailAdapter().search(MailFolder.SENT, ...)` is called
- THEN `namespace.GetDefaultFolder(51)` is called

#### Scenario: Absent inbox/sent folder id keys fall back to the defaults

- GIVEN a fake `win32com.client` module injected into `sys.modules`, and
  `tools.mail_adapter.load_settings` mocked to return `{}`
- WHEN `OutlookMailAdapter().search(MailFolder.INBOX, ...)` is called
- THEN `namespace.GetDefaultFolder(6)` is called
- WHEN `OutlookMailAdapter().search(MailFolder.SENT, ...)` is called
- THEN `namespace.GetDefaultFolder(5)` is called

#### Scenario: settings.yaml declares every folder-id key live

- GIVEN the real, unmocked `config/settings.yaml`
- WHEN it is loaded via `tools.settings.load_settings()`
- THEN `calendar_folder_id` (`9`), `tasks_folder_id` (`13`),
  `inbox_folder_id` (`6`), and `sent_folder_id` (`5`) are all present with
  their documented default values

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

### Requirement: Timezone-Aware Boundary Comparisons

`OutlookCalendarAdapter.search()`'s Python-side boundary re-check (the
"Python-side post-filter as defense-in-depth" comparison of `item.Start`/
`item.End` against `date_from`/`date_to`) MUST normalize both sides of the
comparison to timezone-aware datetimes via `_to_aware()` before comparing.
`SearchRequest.date_from`/`date_to` (`models/schemas.py`) carry no
tz-aware validator, so a caller-supplied bound MAY be naive even though a
real Outlook COM `item.Start`/`item.End` (`pywintypes.datetime`) is already
timezone-aware with a fixed offset — comparing a naive value against an
aware one raises `TypeError: can't compare offset-naive and
offset-aware datetimes`, uncaught, which surfaces to the MCP client as a
raw tool-call failure rather than a typed error. This bug reached real
Windows/Outlook (calendar/mail-side of the 2026-08-26 datetime-tz hotfix)
without being caught by the pre-fix test suite, since every fake COM item
fixture used a naive `Start`/`End` and every request bound in tests was
timezone-aware — the inverse combination (aware item, naive bound) was
never exercised.

#### Scenario: Aware COM datetime vs naive request bound does not raise

- GIVEN a mocked `win32com.client` module whose Calendar folder's `Items` include an event with a timezone-aware (fixed-offset) `Start`/`End`, simulating a real `pywintypes.datetime`
- WHEN `OutlookCalendarAdapter().search(date_from, date_to)` is called with naive (no `tzinfo`) `date_from`/`date_to`
- THEN no `TypeError` is raised, and the event is returned when its aware `Start`/`End` falls within the normalized bounds

#### Scenario: Naive all-day item vs aware request bound does not raise

- GIVEN a mocked `win32com.client` module whose Calendar folder's `Items` include an all-day event with naive `Start`/`End`
- WHEN `OutlookCalendarAdapter().search(date_from, date_to)` is called with timezone-aware `date_from`/`date_to`
- THEN no `TypeError` is raised, and the event is returned when its normalized `Start`/`End` falls within the given bounds

### Requirement: DASL `@SQL=` Restrict Date Literals, Not Jet Bracket Syntax

`OutlookCalendarAdapter.search()`'s `Items.Restrict()` date-range clause
MUST compare `_dasl_datetime()`'s ISO-ordered literal via DASL `@SQL=`
syntax against the quoted property URNs `"urn:schemas:calendar:dtstart"`
and `"urn:schemas:calendar:dtend"`, never Jet's bare bracket-property
syntax (`[Start] >= '...'`). Live evidence (BUG-004, 2026-08-26) showed
that even an ISO-ordered literal is still misparsed by Jet under an es-ES
Outlook client when compared via bracket syntax: the lower bound's day was
read as transposed whenever it was `<= 12`, inverting the range and
returning `[]` with no error. DASL `@SQL=` date-literal comparisons against
a quoted property URN are documented as culture-invariant.

#### Scenario: Restrict() clause uses DASL @SQL= syntax with quoted property URNs

- GIVEN a mocked `win32com.client` module
- WHEN `OutlookCalendarAdapter().search(date_from, date_to)` builds its `Restrict()` clause
- THEN the emitted string starts with `@SQL="urn:schemas:calendar:dtstart" >=`
- AND contains `"urn:schemas:calendar:dtend" <=`
- AND never contains the bare bracket form `[Start]` or `[End]`

#### Scenario: Lower bound with day <= 12 is not transposed

- GIVEN a mocked `win32com.client` module whose Calendar folder's `Items` are seeded with an event on 2026-01-08 and one on 2026-02-06
- WHEN `OutlookCalendarAdapter().search(date_from=2026-01-08T00:00:00, date_to=2026-02-08T23:59:59)` is called
- THEN both events are returned (an inverted-range misread would have excluded the 2026-01-08 event or returned nothing at all)

### Requirement: Ascending Sort Before Restrict, Required for Recurrence Expansion

`OutlookCalendarAdapter.search()` MUST set `items.IncludeRecurrences = True`,
then call `items.Sort("[Start]", False)` (ascending), strictly before calling
`items.Restrict()`. Outlook COM only expands a recurring series into its
individual occurrences through `Restrict()`/`Find()` when the source
`Items` collection was sorted ascending by `[Start]` first; a descending
sort (introduced by the search-result-caps change, BUG-002, purely as an
early-stop optimization) silently breaks recurrence expansion — every
occurrence of every recurring series is dropped from the `Restrict()`
output, while one-off (non-recurring) items are unaffected (BUG-005 part
2, 2026-08-26 live evidence). Newest-first output order (still required)
is produced by sorting the collected, `Restrict()`-bounded match list in
Python after the boundary re-check and subject filter, rather than relying
on descending COM-source order for an iteration early-stop.

#### Scenario: IncludeRecurrences, ascending Sort, then Restrict, in that order

- GIVEN a mocked `win32com.client` module
- WHEN `OutlookCalendarAdapter().search(date_from, date_to)` is called
- THEN `items.IncludeRecurrences` is `True`
- AND `items.Sort` is called with `("[Start]", False)`
- AND `items.Sort` is called before `items.Restrict`

#### Scenario: Recurring series' occurrences are all returned, newest-first

- GIVEN a mocked, ascending-ordered `Restrict()` result containing four occurrences of a recurring series plus one one-off event, all within the search window
- WHEN `OutlookCalendarAdapter().search(date_from, date_to)` is called
- THEN all five items are returned
- AND they are ordered newest-first by `start`

### Requirement: Boundary Re-Check Is Skippable for Auto-Filled Windows

`OutlookCalendarAdapter.search()` MUST accept an `enforce_date_bounds`
keyword (default `True`). When `False`, the Python-side boundary re-check
(`start < date_from or end > date_to`) MUST be skipped entirely — only the
subject filter (and whatever `Restrict()` itself returned) determines the
result. `date_from`/`date_to` still bound the `Restrict()` call regardless
of this flag, so `IncludeRecurrences` expansion stays bounded. The tool
layer passes `False` only for a request whose `from`/`to` were both
omitted by the caller and auto-filled from `lookback_days` (BUG-005 part
1, 2026-08-26 live evidence: a subject-only query for an event provably
visible via a date-bounded query returned nothing, because the
auto-filled window excluded the event's actual date).

#### Scenario: enforce_date_bounds=False returns a subject match outside the window

- GIVEN a mocked `Restrict()` result containing one item whose `Start`/`End` fall entirely outside `date_from`/`date_to`
- WHEN `OutlookCalendarAdapter().search(date_from, date_to, subject=<that item's subject>, enforce_date_bounds=False)` is called
- THEN the item is returned

#### Scenario: enforce_date_bounds=True (the default) still drops out-of-window items

- GIVEN the same mocked `Restrict()` result as above
- WHEN `OutlookCalendarAdapter().search(date_from, date_to, subject=<that item's subject>)` is called (no `enforce_date_bounds` override)
- THEN the item is dropped by the boundary re-check
