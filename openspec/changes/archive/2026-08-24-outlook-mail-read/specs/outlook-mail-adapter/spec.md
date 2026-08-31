# Outlook Mail Adapter Specification

## Purpose

Isolate all Outlook Inbox/Sent Items COM access behind a single adapter
interface (`MailPort`), mirroring `outlook-tasks-adapter`, so tool logic and
its tests never depend on `win32com` being importable on the WSL2 Linux
dev/CI host. The adapter is strictly read-only: it MUST NOT send, move,
delete, or otherwise mutate any mailbox item or folder.

## Requirements

### Requirement: Adapter Interface

The system MUST define a `MailPort` `Protocol` exposing
`search(folder, date_from, date_to, subject, sender) -> list[MessageSummary]`
and `get_message(entry_id) -> MessageDetail`, where `folder` is required
(`"inbox"` or `"sent"`) and `date_from`/`date_to`/`subject`/`sender` are
independently optional. Both `OutlookMailAdapter` and `FakeMailAdapter`
MUST satisfy it.

#### Scenario: Fake adapter satisfies the interface

- GIVEN a `FakeMailAdapter` implementing `search()` and `get_message()` per `MailPort`
- WHEN a tool is called with the fake adapter injected
- THEN the tool code runs unchanged, with no reference to `win32com` on the call path

### Requirement: Lazy COM Import

`OutlookMailAdapter` MUST import `win32com.client` lazily, inside its own
module/functions — never at the top level of `server.py`, `tools/`, or
`models/` modules — so the test suite runs on Linux without `win32com`
installed.

#### Scenario: Test suite runs without win32com installed

- GIVEN this WSL2 dev environment where `import win32com` fails
- WHEN `python3.12 -m pytest -q` runs the full suite using only `FakeMailAdapter`
- THEN all tests pass and no test triggers a `win32com` import

### Requirement: Real Adapter COM Access Per Folder

On Windows, `OutlookMailAdapter` MUST connect via
`win32com.client.Dispatch("Outlook.Application")`, `GetNamespace("MAPI")`,
and resolve the folder via `GetDefaultFolder(6)` (`olFolderInbox`) for
`folder="inbox"` or `GetDefaultFolder(5)` (`olFolderSentMail`) for
`folder="sent"`. When `date_from`/`date_to` are given, it MUST DASL
`Restrict()` on `[ReceivedTime]` (inbox) or `[SentOn]` (sent), then apply
`subject`/`sender` as case-insensitive Python substring filters over the
result.

#### Scenario: Inbox search restricts on ReceivedTime

- GIVEN a mocked `win32com.client` module whose Inbox folder's `Items.Restrict()` returns a fixed collection when called with a `[ReceivedTime]` DASL clause
- WHEN `OutlookMailAdapter.search()` is called with `folder="inbox"` and a `date_from`/`date_to` range
- THEN the adapter calls `Restrict()` with a `[ReceivedTime]` clause built from the given range
- AND applies `subject`/`sender` filtering in Python over the restricted items

#### Scenario: Sent search restricts on SentOn

- GIVEN a mocked `win32com.client` module whose Sent Items folder's `Items.Restrict()` returns a fixed collection when called with a `[SentOn]` DASL clause
- WHEN `OutlookMailAdapter.search()` is called with `folder="sent"` and a `date_from`/`date_to` range
- THEN the adapter calls `Restrict()` with a `[SentOn]` clause built from the given range

### Requirement: Non-MailItem Guard

While iterating a folder's `Items`, `OutlookMailAdapter` MUST skip any entry
whose `Class` is not `43` (`olMail`) — e.g. meeting requests, receipts, or
report items mixed into Inbox/Sent — without raising, so a single
non-message entry never aborts a search.

#### Scenario: Mixed-class Items collection skips non-mail entries

- GIVEN a mocked `win32com.client` module whose Inbox folder's `Items` collection contains 4 entries: 3 with `Class=43` and 1 meeting-request item with `Class=53`
- WHEN `OutlookMailAdapter.search()` is called with `folder="inbox"` and a valid filter matching all mail entries
- THEN the adapter returns exactly 3 `MessageSummary` items
- AND raises no exception while skipping the `Class=53` entry

### Requirement: COM Datetime Normalization

Outlook COM (`pywintypes.datetime`) returns naive datetimes in the Outlook
profile's local timezone. `OutlookMailAdapter` MUST attach a timezone to any
naive `ReceivedTime`/`SentOn` value using `tools/settings.py`'s
`local_timezone()` before it reaches `MessageSummary`/`MessageDetail`;
already-aware values pass through unchanged. Applied identically in
`search()` and `get_message()`.

#### Scenario: Naive COM datetime is converted to aware local time

- GIVEN a mocked `win32com.client` module returning a mail item with a naive `ReceivedTime`
- WHEN `OutlookMailAdapter.search()` is called with `folder="inbox"`
- THEN the returned `MessageSummary.date` is timezone-aware, using the offset from `tools/settings.py::local_timezone()`

### Requirement: COM Failure Mapping

Any failure dispatching Outlook, accessing MAPI, resolving the folder, or
restricting/iterating items MUST raise `OutlookUnavailableError`; an
unresolved `entryId` MUST raise `MessageNotFoundError` — never a bare,
unhandled COM exception.

#### Scenario: Dispatch failure raises a typed error

- GIVEN `win32com.client.Dispatch("Outlook.Application")` raises (Outlook not installed/running) — simulated via a mocked `win32com.client` module whose `Dispatch` raises
- WHEN `OutlookMailAdapter.search()` or `get_message()` is called
- THEN the adapter raises `OutlookUnavailableError`, not a bare/unhandled COM exception

#### Scenario: Unknown entryId raises MessageNotFoundError

- GIVEN a mocked `win32com.client` module whose `GetItemFromID()` raises for an unknown entryId
- WHEN `OutlookMailAdapter.get_message("BAD-ID")` is called
- THEN the adapter raises `MessageNotFoundError` with code `message_not_found`

### Requirement: Read-Only Contract

`OutlookMailAdapter` MUST NOT call any mutating COM member (`Send`, `Move`,
`Delete`, `Save`, or assigning `UnRead`) on any item or folder it touches,
in `search()`, `get_message()`, or item iteration.

#### Scenario: get_message issues no mutating COM calls

- GIVEN a mocked `win32com.client` module whose returned mail item asserts if `Save`, `Move`, `Delete`, or `UnRead` assignment is invoked
- WHEN `OutlookMailAdapter.get_message()` is called for a valid entryId
- THEN no mutating member is invoked on the mocked item

### Requirement: Adapter Selection at Runtime

The server MUST select the real adapter only when `win32com` is importable
at startup/first use; otherwise mail tool calls MUST fail with a clear
runtime error, not a module-import-time crash.

#### Scenario: win32com not importable

- GIVEN the server runs on a host without `win32com` installed (e.g. this Linux dev host)
- WHEN a mail tool invokes the adapter
- THEN the tool returns a clear error stating the Outlook mail adapter is
  unavailable on this platform, and the server process itself does not
  crash at import time
