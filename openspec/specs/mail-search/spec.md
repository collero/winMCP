# Mail Search Specification

## Purpose

Lightweight, read-only search over the user's default Outlook Inbox or Sent
Items folder, returning a minimal message list so a client can locate an
item before fetching full detail via `mail_get_message`. No mailbox state
(read flags, folders, items) is ever mutated by this tool.

## Requirements

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

### Requirement: Default Date Bounds When Filtering by Subject/Sender Only

When `subject` and/or `sender` is provided but `dateFrom` and/or `dateTo` is
omitted, `mail_search` MUST fill the missing bound(s) from
`config/settings.yaml`'s `mail_lookback_days` (read via
`tools/settings.py::load_settings()`, default `90` when the key is absent)
so the adapter's `Restrict()` always receives concrete bounds — never an
open-ended date filter. `mail_lookback_days` is a distinct, live setting
from calendar's `lookback_days` (default `7`); it MUST NOT be conflated
with it. Bound-filling mirrors `tools/calendar.py::_normalize_search_bounds`:
when both `dateFrom`/`dateTo` are omitted, the range is
`[now - mail_lookback_days, now]`; when only `dateFrom` is omitted, it is
`[dateTo - mail_lookback_days, dateTo]`; when only `dateTo` is omitted, it
is `[dateFrom, now]`. Unlike the settings.yaml folder-id entries (dead,
never read), `mail_lookback_days` MUST be read on every qualifying call.

#### Scenario: Subject-only search fills both bounds from mail_lookback_days

- GIVEN `config/settings.yaml` has no `mail_lookback_days` key (default `90` applies) and a fake adapter seeded with a message subject "Factura agosto"
- WHEN `mail_search` is called with `folder="inbox"`, `subject="factura"` only (`dateFrom`/`dateTo` omitted)
- THEN the adapter's `search()` is invoked with a concrete `date_from`/`date_to` range spanning `[now - 90 days, now]`

#### Scenario: Sender-only search with a configured mail_lookback_days

- GIVEN `config/settings.yaml` sets `mail_lookback_days: 30` and a fake adapter seeded with one sent message
- WHEN `mail_search` is called with `folder="sent"`, `sender="ana"` only (`dateFrom`/`dateTo` omitted)
- THEN the adapter's `search()` is invoked with a concrete range spanning `[now - 30 days, now]`, not calendar's `lookback_days`

#### Scenario: Only dateFrom given fills dateTo with now

- GIVEN a fake adapter seeded with messages, `mail_lookback_days` unset (default `90`)
- WHEN `mail_search` is called with `folder="inbox"`, `subject="factura"`, `dateFrom=2026-08-01T00:00:00` (`dateTo` omitted)
- THEN the adapter's `search()` is invoked with `date_from=2026-08-01T00:00:00` and `date_to` equal to the current time, not left open-ended

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

#### Scenario: Sent-folder search filters on SentOn via mocked Restrict

- GIVEN a mocked `win32com.client` module whose Sent Items folder's `Items.Restrict()` is configured to assert its DASL clause references `[SentOn]`
- WHEN `mail_search` is called with `folder="sent"`, `dateFrom=2026-08-01T00:00:00`, `dateTo=2026-08-31T23:59:59`
- THEN the mocked `Restrict()` is called with a `[SentOn]` clause, not `[ReceivedTime]`

#### Scenario: Drafts-folder search filters on LastModificationTime

- GIVEN a mocked `win32com.client` module whose Drafts folder's `Items.Restrict()` is configured to assert its DASL clause references `[LastModificationTime]`
- WHEN `mail_search` is called with `folder="drafts"`, `dateFrom=2026-08-01T00:00:00`, `dateTo=2026-08-31T23:59:59`
- THEN the mocked `Restrict()` is called with a `[LastModificationTime]` clause

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

### Requirement: Sender Filter Is Folder-Dependent

For `folder="inbox"`, the `sender` filter MUST match against the message's
`SenderName` or `SenderEmailAddress`. For `folder="sent"`, it MUST match
against the `To`/recipient names of the message, since Outlook does not
populate a meaningful "sender" for items the user sent.

#### Scenario: Sender filter matches recipient on sent folder

- GIVEN a fake adapter seeded with one sent message addressed `To="ana.gomez@example.com"`
- WHEN `mail_search` is called with `folder="sent"`, `sender="ana.gomez"`
- THEN that message is included in the results

#### Scenario: Sender filter matches SenderName on inbox folder

- GIVEN a fake adapter seeded with one inbox message with `SenderName="Ana Gómez"`
- WHEN `mail_search` is called with `folder="inbox"`, `sender="ana"`
- THEN that message is included in the results

### Requirement: Result Limit Parameter

The `mail_search` tool MUST accept an optional `limit` (integer) request
parameter bounding the number of `MessageSummary` rows returned. When
omitted, `limit` defaults to `50`. When provided and less than or equal
to `0`, the tool MUST reject the call as a `ValueError` before any
adapter call. When provided and greater than `200`, the tool MUST clamp
it to `200` (never reject) — `200` is the hard maximum, matching
`file_search`'s existing cap convention. The adapter MUST apply the
(defaulted/clamped) limit at the source — bounding item iteration/COM
retrieval — never fetching an unbounded set and truncating client-side.

#### Scenario: Default limit applied when omitted

- GIVEN a mocked `win32com.client` Inbox `Items` collection seeded with 120 messages all matching `subject="a"`
- WHEN `mail_search` is called with `folder="inbox"`, `subject="a"`, `limit` omitted
- THEN exactly 50 `MessageSummary` items are returned

#### Scenario: Oversized subject search is bounded and flagged

- GIVEN a mocked `win32com.client` Inbox `Items` collection seeded with 1000 messages matching `subject="a"`
- WHEN `mail_search` is called with `folder="inbox"`, `subject="a"` (`limit` omitted, default 50 applies)
- THEN the response is bounded to 50 rows
- AND `results_truncated` is `true`

#### Scenario: limit above hard max is clamped, not rejected

- GIVEN a mocked adapter seeded with 500 matching messages
- WHEN `mail_search` is called with `folder="inbox"`, `subject="a"`, `limit=10000`
- THEN the adapter's `search()` is invoked with a limit of `200`, not `10000`, and no error is raised

#### Scenario: Non-positive limit is rejected

- WHEN `mail_search` is called with `folder="inbox"`, `subject="a"`, `limit=0`
- THEN the tool raises a `ValueError` before calling the adapter

### Requirement: Newest-First Ordering

`mail_search` results MUST be ordered newest-first by the same `date`
field used in `MessageSummary` (`ReceivedTime` for `inbox`,
`SentOn` for `sent`), so that when the cap truncates results the
returned page is the most recent, most useful subset.

#### Scenario: Out-of-order source items are returned newest-first

- GIVEN a mocked Inbox `Items` collection seeded with 3 messages received out of chronological order (e.g. Aug 10, Aug 1, Aug 20)
- WHEN `mail_search` is called with `folder="inbox"`, `subject` matching all three
- THEN the returned `MessageSummary` list is ordered Aug 20, Aug 10, Aug 1 (newest first)

### Requirement: Search Output Shape

The tool MUST return `MessageSummary` objects containing `entryId`,
`subject`, `sender` (display name), `senderAddress`, `date` (a single
ISO 8601 timestamp normalized from `ReceivedTime` for `inbox` or
`SentOn` for `sent`), and `hasAttachments` (boolean). It MUST NOT
include the message body — this is unchanged by this change and MUST
NOT regress; bodies remain available only via `mail_get_message`. The
response MUST additionally convey a `results_truncated` boolean value
that is `true` when the effective `limit` cut the true match count, and
`false` (or absent, treated as falsy) otherwise. The exact response
shape carrying `results_truncated` alongside the row list is an
implementation decision left to `design.md`.

#### Scenario: Empty result set

- GIVEN a fake adapter whose `search()` returns an empty list for the given filters
- WHEN `mail_search` is called with `folder="inbox"`, `subject="Nonexistent"`
- THEN the tool returns an empty result with `results_truncated` falsy, not an error

#### Scenario: Filterless-of-cap search is not marked truncated

- GIVEN a mocked Inbox `Items` collection seeded with 10 messages matching `subject="factura"`
- WHEN `mail_search` is called with `folder="inbox"`, `subject="factura"`, `limit=50`
- THEN all 10 `MessageSummary` items are returned
- AND `results_truncated` is `false`

#### Scenario: Rows never carry body content

- GIVEN a mocked Inbox `Items` collection seeded with a message that has a large `Body` property
- WHEN `mail_search` is called with `folder="inbox"`, `subject` matching that message
- THEN the returned `MessageSummary` contains no body field of any kind

### Requirement: Outlook Unavailable

The tool MUST surface a clear, catchable error (not an unhandled crash) when
the underlying adapter cannot reach Outlook.

#### Scenario: COM dispatch failure

- GIVEN a fake adapter configured to raise `OutlookUnavailableError` from `search()`
  (simulating `win32com.client.Dispatch("Outlook.Application")` failing because
  Outlook is not installed or not running)
- WHEN `mail_search` is called with any valid filter
- THEN the tool returns an MCP tool error whose message identifies Outlook as unavailable

### Requirement: Inverted Date Range Is Rejected, Not Silently Empty

If both `dateFrom` and `dateTo` are given (or resolved, after the
`mail_lookback_days` default-fill for an omitted bound) and `dateFrom` is
after `dateTo`, `mail_search` MUST raise before calling the adapter, rather
than returning an empty result. The error message MUST echo both resolved
bounds. This guards against a class of failure (BUG-004, 2026-08-26) where
a locale-transposed lower bound silently inverted a range and returned `[]`
with no error and `resultsTruncated: false`.

#### Scenario: Explicit inverted range raises instead of returning empty

- GIVEN a `mail_search` request with `dateFrom=2026-06-10` and `dateTo=2026-06-01`
- WHEN `mail_search` is called
- THEN it raises an error (surfaced as an `invalid_request` MCP tool error) whose message contains both `2026-06-10` and `2026-06-01`
- AND the adapter's `search()` is never called

### Requirement: Wider Ranges Are a Superset of Contained Narrower Ranges

For a fixed filter set, a `mail_search` call over a date range MUST return a
result set that is a superset of every result set returned by a call whose
date range is fully contained within the first. This property held even
under the locale-transposition bug for ranges whose bounds happened to be
symmetric or unambiguous (day >= 13), which is exactly why prior manual
smoke tests missed BUG-003/BUG-004 — this scenario exercises the property
generically, varying the lower bound's day across both `<= 12` and `>= 13`.

#### Scenario: A range's results are a superset of every contained sub-range's results

- GIVEN a fake adapter seeded with one message per day across a full month
- WHEN `mail_search` is called once with the full-month range and once with a narrower range fully inside it (both with the same `subject` filter)
- THEN every message returned by the narrower-range call is also present in the full-month call's results
