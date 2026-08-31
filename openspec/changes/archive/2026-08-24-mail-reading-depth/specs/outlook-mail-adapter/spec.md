# Delta for Outlook Mail Adapter

## MODIFIED Requirements

### Requirement: Adapter Interface

The system MUST define a `MailPort` `Protocol` exposing
`search(folder, folder_path, date_from, date_to, subject, sender) ->
list[MessageSummary]` and `get_message(entry_id, include_html_body=False)
-> MessageDetail`. `folder`/`folder_path` are each optional; the caller
(`tools/mail.py`) enforces exactly one before invoking the adapter.
`MessageDetail` MUST carry `attachment_names` and an optional `html_body`.
Both `OutlookMailAdapter` and `FakeMailAdapter` MUST satisfy this protocol.
(Previously: `search(folder, ...)` required `folder`, no `folder_path`;
`get_message(entry_id)` had no `include_html_body`; `MessageDetail` had no
`attachment_names`/`html_body`.)

#### Scenario: Fake adapter satisfies the interface

- GIVEN a `FakeMailAdapter` implementing the updated `MailPort`
- WHEN a tool is called with the fake injected, using either `folder` or `folder_path`, with or without `include_html_body`
- THEN the tool runs unchanged, with no `win32com` reference on the call path

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
(Previously: only `inbox`/`sent` mapped via `GetDefaultFolder`; no
`drafts`, no `folder_path` traversal, no `[LastModificationTime]` case, no
Python-side date filtering.)

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

### Requirement: COM Failure Mapping

Any failure dispatching Outlook, accessing MAPI, resolving a named folder,
or restricting/iterating items MUST raise `OutlookUnavailableError`; an
unresolved `entryId` MUST raise `MessageNotFoundError`; an unresolved
`folder_path` segment MUST raise `MailFolderNotFoundError`
(`CalendarToolError` subclass, code `mail_folder_not_found`) — never a
bare, unhandled COM exception.
(Previously: only `OutlookUnavailableError`/`MessageNotFoundError`; no
`MailFolderNotFoundError`.)

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
(Previously: scoped to `search()`/`get_message()` item access only; now
explicitly covers traversal and the new attachment/HTMLBody reads.)

#### Scenario: get_message issues no mutating COM calls

- GIVEN a mocked mail item that asserts if `Save`, `Move`, `Delete`, or `UnRead` assignment is invoked
- WHEN `OutlookMailAdapter.get_message()` is called with `include_html_body=True` and attachments present
- THEN no mutating member is invoked on the item, its `Attachments` collection, or any folder traversed

## ADDED Requirements

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
