# Delta for Mail Search

## MODIFIED Requirements

### Requirement: Search Input Parameters

The `mail_search` tool MUST accept `folder` (string enum, optional: one of
`inbox`, `sent`, `drafts`), `folderPath` (string, optional, `/`-delimited
path resolved relative to the default mail store's folder tree), `dateFrom`
(ISO 8601 datetime, optional), `dateTo` (ISO 8601 datetime, optional),
`subject` (string, optional, case-insensitive substring match), and `sender`
(string, optional, case-insensitive substring match). Exactly one of
`folder`/`folderPath` MUST be provided; a call providing both or neither
MUST be rejected as a `ValueError` before any adapter call. Independently,
at least one of `dateFrom`/`dateTo`/`subject`/`sender` MUST still be
provided; the tool MUST reject a call with all four omitted (`ValueError`,
pre-adapter), mirroring `calendar_search`'s mandatory-filter rule, to avoid
an unbounded scan. This filter rule is unchanged and applies on top of,
not instead of, the folder/folderPath exclusivity rule.
(Previously: `folder` was a required enum of `inbox`/`sent` only, no
`folderPath`, no exclusivity rule.)

#### Scenario: Valid folder and date range provided

- GIVEN a fake adapter seeded with 3 inbox messages received on 2026-08-10, one subject "Factura agosto"
- WHEN `mail_search` is called with `folder="inbox"`, `dateFrom=2026-08-10T00:00:00`, `dateTo=2026-08-10T23:59:59`
- THEN the adapter's `search()` is invoked with `folder="inbox"` and the given range
- AND all 3 `MessageSummary` items are returned

#### Scenario: All optional filters omitted is rejected

- GIVEN no adapter interaction has occurred yet
- WHEN `mail_search` is called with `folder="inbox"` and `dateFrom`/`dateTo`/`subject`/`sender` all omitted
- THEN the tool raises a `ValueError` before calling the adapter, stating a filter is required

#### Scenario: Neither or both of folder/folderPath is rejected

- WHEN `mail_search` is called with `folder` and `folderPath` both omitted, or both provided together
- THEN the tool raises a `ValueError` before calling the adapter, stating exactly one of `folder`/`folderPath` is required

#### Scenario: folderPath alone satisfies the exclusivity rule

- GIVEN a fake adapter that resolves `folderPath="Proyectos/2026"` to a folder seeded with one message
- WHEN `mail_search` is called with `folderPath="Proyectos/2026"` and `subject="factura"`
- THEN the adapter's `search()` is invoked for the resolved folder and the message is returned

#### Scenario: Backward-compatible folder=inbox/sent calls are unchanged

- GIVEN a fake adapter seeded exactly as in the pre-existing inbox/sent fixtures
- WHEN `mail_search` is called with `folder="inbox"` or `folder="sent"` plus any previously valid filter
- THEN behavior matches before this change: same validation order, same adapter call, same result shape

### Requirement: Folder-Dependent Date Filtering

When `dateFrom`/`dateTo` are given for a mapped `folder`, the underlying
adapter MUST filter via a single-field DASL `Restrict()`: `[ReceivedTime]`
for `folder="inbox"`, `[SentOn]` for `folder="sent"`, or
`[LastModificationTime]` for `folder="drafts"` (Draft items are never sent
and have no reliable `SentOn`/`ReceivedTime`). For a `folderPath`-resolved
custom folder, the adapter MUST NOT use DASL `Restrict()` at all — a
custom folder's reliable date field is unknown ahead of time — and instead
applies `dateFrom`/`dateTo` per item in Python via its date-fallback chain
(`ReceivedTime` → `SentOn` → `LastModificationTime`; see
`outlook-mail-adapter`). `subject` and `sender` are applied as
case-insensitive Python-side substring filters after date filtering,
never via DASL.
(Previously: only `[ReceivedTime]` for inbox and `[SentOn]` for sent were
defined; no drafts or folderPath case.)

#### Scenario: Sent-folder search filters on SentOn via mocked Restrict

- GIVEN a mocked `win32com.client` module whose Sent Items folder's `Items.Restrict()` is configured to assert its DASL clause references `[SentOn]`
- WHEN `mail_search` is called with `folder="sent"`, `dateFrom=2026-08-01T00:00:00`, `dateTo=2026-08-31T23:59:59`
- THEN the mocked `Restrict()` is called with a `[SentOn]` clause, not `[ReceivedTime]`

#### Scenario: Drafts-folder search filters on LastModificationTime

- GIVEN a mocked `win32com.client` module whose Drafts folder's `Items.Restrict()` is configured to assert its DASL clause references `[LastModificationTime]`
- WHEN `mail_search` is called with `folder="drafts"`, `dateFrom=2026-08-01T00:00:00`, `dateTo=2026-08-31T23:59:59`
- THEN the mocked `Restrict()` is called with a `[LastModificationTime]` clause

## ADDED Requirements

### Requirement: folderPath Resolution Failure

When `folderPath` is provided and any path segment fails to resolve to a
subfolder of the default store, `mail_search` MUST surface a clear,
catchable error with code `mail_folder_not_found` (mapped from the
adapter's `MailFolderNotFoundError`), never an unhandled crash or a silent
empty result.

#### Scenario: Unknown path segment yields a typed error

- GIVEN a fake adapter configured so `folderPath="Proyectos/NoExiste"` raises `MailFolderNotFoundError` (code `mail_folder_not_found`)
- WHEN `mail_search` is called with `folderPath="Proyectos/NoExiste"` and a valid `subject`
- THEN the tool returns an MCP tool error with code `mail_folder_not_found` naming the failing segment
