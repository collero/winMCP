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
`search(folder, folder_path, date_from, date_to, subject, sender) ->
list[MessageSummary]` and `get_message(entry_id, include_html_body=False)
-> MessageDetail`. `folder`/`folder_path` are each optional; the caller
(`tools/mail.py`) enforces exactly one before invoking the adapter.
`MessageDetail` MUST carry `attachment_names` and an optional `html_body`.
Both `OutlookMailAdapter` and `FakeMailAdapter` MUST satisfy this protocol.

#### Scenario: Fake adapter satisfies the interface

- GIVEN a `FakeMailAdapter` implementing the updated `MailPort`
- WHEN a tool is called with the fake injected, using either `folder` or `folder_path`, with or without `include_html_body`
- THEN the tool runs unchanged, with no `win32com` reference on the call path

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

On Windows, `OutlookMailAdapter` connects via
`win32com.client.Dispatch("Outlook.Application")` and `GetNamespace("MAPI")`.
For a named `folder`, `_FOLDER_MAP` resolves: `GetDefaultFolder(6)` for
`"inbox"`, `GetDefaultFolder(5)` for `"sent"`, and
`GetDefaultFolder(drafts_folder_id)` (default `16`, `olFolderDrafts`) for
`"drafts"`, where `drafts_folder_id` comes from `config/settings.yaml` via
`tools/settings.py::load_settings()`. For `folder_path`, the adapter walks
`/`-delimited segments by exact name from the default store's top-level
folder — never the namespace root — staying in that store's subtree; any
unresolved segment raises `MailFolderNotFoundError`. For a mapped `folder`,
when `date_from`/`date_to` are given, the adapter DASL `Restrict()`s on a
single field: `[ReceivedTime]` (inbox), `[SentOn]` (sent), or
`[LastModificationTime]` (drafts). For a `folder_path`-resolved folder, the
adapter MUST NOT call `Restrict()` at all — a custom folder's reliable
date field is unknown ahead of time, and `LastModificationTime` misbehaves
for filed mail (moving an old message bumps it) — instead it fetches the
full `Items` collection and applies `date_from`/`date_to` per item in
Python via the same `_resolve_date()` fallback chain used by
`get_message()` (`ReceivedTime` → `SentOn` → `LastModificationTime`; see
Date Resolution Fallback Chain, below). In both cases, `subject`/`sender`
are then applied as Python substring filters over the surviving items.

#### Scenario: Inbox search restricts on ReceivedTime

- GIVEN a mocked `win32com.client` module whose Inbox `Items.Restrict()` returns a fixed collection for a `[ReceivedTime]` DASL clause
- WHEN `OutlookMailAdapter.search(folder="inbox", ...)` is called with a date range
- THEN `Restrict()` is called with a `[ReceivedTime]` clause and `subject`/`sender` are filtered in Python after

#### Scenario: Sent search restricts on SentOn

- GIVEN a mocked module whose Sent Items `Items.Restrict()` returns a fixed collection for a `[SentOn]` DASL clause
- WHEN `OutlookMailAdapter.search(folder="sent", ...)` is called with a date range
- THEN `Restrict()` is called with a `[SentOn]` clause, built from the given range

#### Scenario: Drafts resolves via GetDefaultFolder(drafts_folder_id) and restricts on LastModificationTime

- GIVEN a mocked module whose `GetDefaultFolder(16)` returns Drafts (`drafts_folder_id` unset, default `16`), and `Items.Restrict()` asserts a `[LastModificationTime]` clause
- WHEN `OutlookMailAdapter.search(folder="drafts", ...)` is called with a date range
- THEN the adapter calls `GetDefaultFolder(16)` and `Restrict()` with a `[LastModificationTime]` clause

#### Scenario: folder_path traverses named subfolders within the default store

- GIVEN a mocked module whose default store's top folder has `Folders["Proyectos"]["2026"]`
- WHEN `OutlookMailAdapter.search(folder_path="Proyectos/2026")` is called
- THEN the adapter walks `Folders["Proyectos"]` then `["2026"]` from the store's top folder, never the namespace root

#### Scenario: folder_path search skips Restrict() and filters dates via the fallback chain

- GIVEN a mocked module whose resolved `folder_path` folder's `Items.Restrict()` is not configured (calling it fails the test) and whose full `Items` collection has 2 items with a populated `ReceivedTime` in range and 1 item with `ReceivedTime=None`/`SentOn=None` but a `LastModificationTime` in range
- WHEN `OutlookMailAdapter.search(folder_path="Proyectos/2026", ...)` is called with a `date_from`/`date_to` range
- THEN `Items.Restrict()` is never called, and all 3 items are returned — 2 selected via `ReceivedTime`, 1 via the `LastModificationTime` fallback

#### Scenario: Missing folder_path segment raises MailFolderNotFoundError

- GIVEN a mocked module whose `Folders["Proyectos"]` has no `"NoExiste"` subfolder
- WHEN `OutlookMailAdapter.search(folder_path="Proyectos/NoExiste")` is called
- THEN the adapter raises `MailFolderNotFoundError` (code `mail_folder_not_found`) naming the failing segment, not a bare COM exception

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

### Requirement: Timezone-Aware Boundary Comparisons

`_matches_date_bounds()` — the shared boundary re-check used by every
`OutlookMailAdapter.search()` folder path (defense-in-depth for
inbox/sent/drafts after `Restrict()`; the only date filter for
`folder_path`) — MUST normalize `date_from`/`date_to` to timezone-aware
datetimes via `_to_aware()` before comparing them against the item's
already-normalized date value. `MailSearchRequest.date_from`/`date_to`
(`models/schemas.py`) carry no tz-aware validator, so a caller-supplied
bound MAY be naive even though a real Outlook COM `ReceivedTime`/`SentOn`/
`LastModificationTime` (`pywintypes.datetime`) is already timezone-aware
with a fixed offset — comparing a naive value against an aware one raises
`TypeError: can't compare offset-naive and offset-aware datetimes`,
uncaught, which surfaces to the MCP client as a raw tool-call failure
rather than a typed error. This bug reached real Windows/Outlook (the
2026-08-26 datetime-tz hotfix) without being caught by the pre-fix test
suite, since every fake COM item fixture used a naive date value and every
request bound in tests was timezone-aware — the inverse combination
(aware item, naive bound) was never exercised.

#### Scenario: Aware COM ReceivedTime vs naive request bound does not raise

- GIVEN a mocked `win32com.client` module whose Inbox folder's `Items` include a message with a timezone-aware (fixed-offset) `ReceivedTime`, simulating a real `pywintypes.datetime`
- WHEN `OutlookMailAdapter.search(folder="inbox", date_from=..., date_to=...)` is called with naive (no `tzinfo`) `date_from`/`date_to`
- THEN no `TypeError` is raised, and the message is returned when its aware `ReceivedTime` falls within the normalized bounds

#### Scenario: folder_path search sorts aware items against a naive bound without raising

- GIVEN a mocked `folder_path` target folder whose `Items` include messages with timezone-aware (fixed-offset) `ReceivedTime` values
- WHEN `OutlookMailAdapter.search(folder_path=..., date_from=..., date_to=...)` is called with naive `date_from`/`date_to`
- THEN no `TypeError` is raised during the boundary check or the subsequent Python-side newest-first sort, and matching messages are returned newest-first

### Requirement: COM Failure Mapping

Any failure dispatching Outlook, accessing MAPI, resolving a named folder,
or restricting/iterating items MUST raise `OutlookUnavailableError`; an
unresolved `entryId` MUST raise `MessageNotFoundError`; an unresolved
`folder_path` segment MUST raise `MailFolderNotFoundError`
(`CalendarToolError` subclass, code `mail_folder_not_found`) — never a
bare, unhandled COM exception.

#### Scenario: Dispatch failure raises a typed error

- GIVEN a mocked `win32com.client` module whose `Dispatch("Outlook.Application")` raises
- WHEN `OutlookMailAdapter.search()` or `get_message()` is called
- THEN the adapter raises `OutlookUnavailableError`, not a bare COM exception

#### Scenario: Unknown entryId raises MessageNotFoundError

- GIVEN a mocked module whose `GetItemFromID()` raises for an unknown entryId
- WHEN `OutlookMailAdapter.get_message("BAD-ID")` is called
- THEN the adapter raises `MessageNotFoundError` with code `message_not_found`

(`MailFolderNotFoundError`'s raise path is exercised by the "Missing
folder_path segment" scenario above — same error/code, not duplicated here.)

### Requirement: Read-Only Contract

`OutlookMailAdapter` MUST NOT call any mutating COM member (`Send`, `Move`,
`Delete`, `Save`, or assigning `UnRead`) on any item/folder it touches, in
`search()`, `get_message()`, folder/path traversal, attachment name
enumeration, or `HTMLBody`/plain-`Body` reads.

#### Scenario: get_message issues no mutating COM calls

- GIVEN a mocked mail item that asserts if `Save`, `Move`, `Delete`, or `UnRead` assignment is invoked
- WHEN `OutlookMailAdapter.get_message()` is called with `include_html_body=True` and attachments present
- THEN no mutating member is invoked on the item, its `Attachments` collection, or any folder traversed

### Requirement: Attachment Filename Enumeration

`get_message()` MUST populate `MessageDetail.attachment_names` by
enumerating `Attachments` using Outlook's 1-indexed access
(`Attachments.Item(i).FileName` for `i` in `1..Attachments.Count`),
returning `[]` when `Attachments.Count` is `0`. Detail-only:
`MessageSummary` MUST NOT include it; `hasAttachments` still reflects
`Attachments.Count > 0` unchanged.

#### Scenario: Enumerates filenames in 1-indexed order

- GIVEN a mocked mail item with `Attachments.Count=2`, `Item(1).FileName="factura.pdf"`, `Item(2).FileName="anexo.docx"`
- WHEN `get_message()` is called for that item
- THEN `attachment_names` equals `["factura.pdf", "anexo.docx"]`

#### Scenario: No attachments yields an empty list

- GIVEN a mocked mail item whose `Attachments.Count` is `0`
- WHEN `get_message()` is called for that item
- THEN `attachment_names` equals `[]` and `hasAttachments` is `false`

### Requirement: HTMLBody Read Only When Requested

`get_message()` MUST read `MailItem.HTMLBody` only when called with
`include_html_body=True`; otherwise it MUST NOT access `HTMLBody`, and
`html_body` MUST be `None`. `Body` MUST always be read into `body`,
independent of `include_html_body`.

#### Scenario: HTMLBody is not accessed by default

- GIVEN a mocked mail item whose `HTMLBody` property raises `AssertionError` if accessed
- WHEN `get_message()` is called without `include_html_body`
- THEN no error is raised and `html_body` is `None`

#### Scenario: HTMLBody is read when requested

- GIVEN a mocked mail item with `Body="Texto plano"`, `HTMLBody="<p>Texto plano</p>"`
- WHEN `get_message(include_html_body=True)` is called
- THEN `html_body` equals `"<p>Texto plano</p>"` and `body` still equals `"Texto plano"`

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

### Requirement: Date Resolution Fallback Chain

For items whose folder-appropriate timestamp may be absent (drafts, and
any `folder_path` folder), `OutlookMailAdapter` MUST resolve the item's
date via: `ReceivedTime` if present, else `SentOn`, else
`LastModificationTime`. The first non-null value is timezone-normalized
per the existing COM Datetime Normalization rule, identically in
`search()` and `get_message()`. For `folder_path`-resolved folders, this
resolved value is also the criterion `date_from`/`date_to` are compared
against in Python, since `Restrict()` is skipped for those folders (see
Real Adapter COM Access Per Folder, above).

#### Scenario: Draft with no ReceivedTime/SentOn falls back to LastModificationTime

- GIVEN a mocked Drafts item with `ReceivedTime=None`, `SentOn=None`, a valid naive `LastModificationTime`
- WHEN the adapter resolves that item's date
- THEN the returned date equals the timezone-normalized `LastModificationTime`

#### Scenario: Custom folder item with ReceivedTime present uses it first

- GIVEN a mocked `folder_path` item with a populated `ReceivedTime`
- WHEN the adapter resolves that item's date
- THEN the returned date equals the timezone-normalized `ReceivedTime`, not `SentOn`/`LastModificationTime`

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

### Requirement: DASL `@SQL=` Restrict Date Literals, Not Jet Bracket Syntax

`OutlookMailAdapter.search()`'s `Items.Restrict()` date-range clause (for
`folder="inbox"`/`"sent"`/`"drafts"`) MUST compare `_dasl_datetime()`'s
ISO-ordered literal via DASL `@SQL=` syntax against a quoted property
URN — `"urn:schemas:httpmail:datereceived"` for inbox,
`"urn:schemas:httpmail:datesent"` for sent, and the MAPI property-tag URN
`"http://schemas.microsoft.com/mapi/proptag/0x30080040"` (
`PR_LAST_MODIFICATION_TIME`) for drafts — never Jet's bare
bracket-property syntax (`[ReceivedTime] >= '...'`). Live evidence
(BUG-004, 2026-08-26) showed that even an ISO-ordered literal is still
misparsed by Jet under an es-ES Outlook client when compared via bracket
syntax: the lower bound's day was read as transposed whenever it was
`<= 12`, inverting the range and returning `[]` with no error. This
applies only to `folder`-mapped searches; `folder_path` searches already
skip `Restrict()` entirely and are unaffected. `Sort()` (used to establish
newest-first COM-source order for the early-stop convention) keeps using
the bracket property name — sorting by property carries no date-literal
locale risk.

#### Scenario: Inbox Restrict() clause uses DASL @SQL= syntax with a quoted property URN

- GIVEN a mocked `win32com.client` module
- WHEN `OutlookMailAdapter().search(folder="inbox", date_from, date_to)` builds its `Restrict()` clause
- THEN the emitted string starts with `@SQL="urn:schemas:httpmail:datereceived" >=`
- AND never contains the bare bracket form `[ReceivedTime]`

#### Scenario: Lower bound with day <= 12 is not transposed

- GIVEN a mocked `win32com.client` module whose Inbox `Items` are seeded with a message on 2026-01-08 and one on 2026-02-06
- WHEN `OutlookMailAdapter().search(folder="inbox", date_from=2026-01-08T00:00:00, date_to=2026-02-08T23:59:59)` is called
- THEN both messages are returned (an inverted-range misread would have excluded the 2026-01-08 message or returned nothing at all)
