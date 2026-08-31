# OneNote Search Specification

## Purpose

Full-text search over OneNote page content via `OneNote.Application`'s
`FindPages`, letting a caller locate a page before fetching its full
detail via `onenote_get_page`. Read-only: no page/section/notebook state
is ever mutated.

## Requirements

### Requirement: Search Input/Output

The `onenote_search` tool MUST accept `query` (string, required,
non-empty) and MUST return a list of `PageSummary` objects, each with
`pageId`, `title`, `notebookName`, `sectionName`, and
`lastModifiedDateTime` (ISO 8601, optional — omitted when the bridge does
not report it for a row).

#### Scenario: Successful search returns matching pages

- GIVEN a fake adapter whose `search("factura")` returns two
  `PageSummary` rows from different notebooks
- WHEN `onenote_search` is called with `query="factura"`
- THEN both `PageSummary` rows are returned with their
  `pageId`/`title`/`notebookName`/`sectionName`

#### Scenario: Empty query is rejected before any adapter call

- WHEN `onenote_search` is called with `query=""` (or omitted)
- THEN the tool raises a `ValueError` before calling the adapter

### Requirement: Empty Result Is Not an Error

A `query` with zero matches MUST return an empty list, not an error.

#### Scenario: No matches

- GIVEN a fake adapter whose `search("noexiste")` returns `[]`
- WHEN `onenote_search` is called with `query="noexiste"`
- THEN the tool returns an empty list, not an error

### Requirement: Result Limit Parameter

The tool MUST accept an optional `limit` (integer), defaulting to `50`
when omitted and clamped to a hard maximum of `200` when it exceeds it
(never rejected above the max), mirroring `mail_search`'s cap convention.
A `limit` of `0` or below MUST be rejected as a `ValueError` before any
adapter call.

#### Scenario: Default limit is applied when omitted

- GIVEN a fake adapter seeded with 80 matching pages
- WHEN `onenote_search` is called with `query="a"`, `limit` omitted
- THEN at most 50 `PageSummary` rows are returned

#### Scenario: Oversized limit is clamped, not rejected

- WHEN `onenote_search` is called with `query="a"`, `limit=10000`
- THEN the adapter's `search()` is invoked with a limit of `200`, and no
  error is raised

### Requirement: OneNote Unavailable

The tool MUST surface `OneNoteUnavailableError` (code `onenote_unavailable`)
as a clear MCP tool error, not an unhandled crash, when the adapter cannot
reach OneNote/the bridge.

#### Scenario: Bridge failure

- GIVEN a fake adapter configured to raise `OneNoteUnavailableError` from
  `search()` (simulating the PowerShell bridge failing to spawn or
  OneNote not installed)
- WHEN `onenote_search` is called with any valid `query`
- THEN the tool returns an MCP tool error with code `onenote_unavailable`
