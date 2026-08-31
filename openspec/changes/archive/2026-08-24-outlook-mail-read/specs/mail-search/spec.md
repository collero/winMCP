# Mail Search Specification

## Purpose

Lightweight, read-only search over the user's default Outlook Inbox or Sent
Items folder, returning a minimal message list so a client can locate an
item before fetching full detail via `mail_get_message`. No mailbox state
(read flags, folders, items) is ever mutated by this tool.

## Requirements

### Requirement: Search Input Parameters

The `mail_search` tool MUST accept `folder` (string enum, required: one of
`inbox`, `sent`), `dateFrom` (ISO 8601 datetime, optional), `dateTo` (ISO
8601 datetime, optional), `subject` (string, optional, case-insensitive
substring match), and `sender` (string, optional, case-insensitive substring
match). At least one of `dateFrom`/`dateTo`/`subject`/`sender` MUST be
provided; the tool MUST reject a call with all four omitted (raised as a
`ValueError` before any adapter call is made), mirroring `calendar_search`'s
mandatory-filter rule, to avoid an unbounded folder scan.

#### Scenario: Valid folder and date range provided

- GIVEN a fake adapter seeded with 3 inbox messages received on 2026-08-10, one subject "Factura agosto"
- WHEN `mail_search` is called with `folder="inbox"`, `dateFrom=2026-08-10T00:00:00`, `dateTo=2026-08-10T23:59:59`
- THEN the adapter's `search()` is invoked with `folder="inbox"` and the given range
- AND all 3 `MessageSummary` items are returned

#### Scenario: All optional filters omitted is rejected

- GIVEN no adapter interaction has occurred yet
- WHEN `mail_search` is called with `folder="inbox"` and `dateFrom`/`dateTo`/`subject`/`sender` all omitted
- THEN the tool raises a `ValueError` before calling the adapter, stating a filter is required

#### Scenario: Missing folder is rejected

- WHEN `mail_search` is called without a `folder` value
- THEN the tool rejects the call as invalid input before calling the adapter

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

When `dateFrom`/`dateTo` are given, the underlying adapter MUST filter via a
DASL `Restrict()` on `[ReceivedTime]` for `folder="inbox"` or `[SentOn]` for
`folder="sent"`. `subject` and `sender` are applied as case-insensitive
Python-side substring filters after retrieval, never via DASL.

#### Scenario: Sent-folder search filters on SentOn via mocked Restrict

- GIVEN a mocked `win32com.client` module whose Sent Items folder's `Items.Restrict()` is configured to assert its DASL clause references `[SentOn]`
- WHEN `mail_search` is called with `folder="sent"`, `dateFrom=2026-08-01T00:00:00`, `dateTo=2026-08-31T23:59:59`
- THEN the mocked `Restrict()` is called with a `[SentOn]` clause, not `[ReceivedTime]`

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

### Requirement: Search Output Shape

The tool MUST return a list of `MessageSummary` objects containing
`entryId`, `subject`, `sender` (display name), `senderAddress`, `date` (a
single ISO 8601 timestamp normalized from `ReceivedTime` for `inbox` or
`SentOn` for `sent`), and `hasAttachments` (boolean). It MUST NOT include the
message body.

#### Scenario: Empty result set

- GIVEN a fake adapter whose `search()` returns an empty list for the given filters
- WHEN `mail_search` is called with `folder="inbox"`, `subject="Nonexistent"`
- THEN the tool returns an empty list, not an error

### Requirement: Outlook Unavailable

The tool MUST surface a clear, catchable error (not an unhandled crash) when
the underlying adapter cannot reach Outlook.

#### Scenario: COM dispatch failure

- GIVEN a fake adapter configured to raise `OutlookUnavailableError` from `search()`
  (simulating `win32com.client.Dispatch("Outlook.Application")` failing because
  Outlook is not installed or not running)
- WHEN `mail_search` is called with any valid filter
- THEN the tool returns an MCP tool error whose message identifies Outlook as unavailable
