# Calendar Search Specification

## Purpose

Lightweight search over the user's default Outlook calendar folder, returning a
minimal event list (`entryId`, `subject`, `start`, `end`) so a client can locate an
item before fetching full detail.

## Requirements

### Requirement: Search Input Parameters

The `calendar_search` tool MUST accept `from` (ISO 8601 datetime, optional), `to`
(ISO 8601 datetime, optional), and `subject` (string, optional, case-insensitive
substring match). At least one of `from`/`to` or `subject` MUST be provided; the
tool MUST reject a call with all three parameters omitted to avoid an unbounded
folder scan.

#### Scenario: Valid range and subject provided

- GIVEN a fake adapter seeded with 3 events on 2026-07-27, one subject "Tareas (bloque)"
- WHEN `calendar_search` is called with `from=2026-07-27T00:00:00`, `to=2026-07-27T23:59:59`, `subject="tareas"`
- THEN the adapter's `search()` is invoked with the normalized range and subject filter
- AND exactly one `EventSummary` is returned

#### Scenario: No filters provided is rejected

- GIVEN no adapter interaction has occurred yet
- WHEN `calendar_search` is called with `from`, `to`, and `subject` all omitted
- THEN the tool MUST return an error before calling the adapter, stating a filter is required

### Requirement: Search Output Shape

The tool MUST return a list of objects containing exactly `entryId`, `subject`,
`start`, and `end` (ISO 8601 strings). It MUST NOT include the event body.

#### Scenario: Empty result set

- GIVEN a fake adapter whose `search()` returns an empty list for the given filters
- WHEN `calendar_search` is called with `subject="Nonexistent"`
- THEN the tool returns an empty list, not an error

### Requirement: Outlook Unavailable

The tool MUST surface a clear, catchable error (not an unhandled crash) when the
underlying adapter cannot reach Outlook.

#### Scenario: COM dispatch failure

- GIVEN a fake adapter configured to raise `OutlookUnavailableError` from `search()`
  (simulating `win32com.client.Dispatch("Outlook.Application")` failing because
  Outlook is not installed or not running)
- WHEN `calendar_search` is called with any valid filter
- THEN the tool returns an MCP tool error whose message identifies Outlook as unavailable
