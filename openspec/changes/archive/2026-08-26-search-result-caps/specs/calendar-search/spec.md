# Delta for calendar-search

## ADDED Requirements

### Requirement: Result Limit Parameter

The `calendar_search` tool MUST accept an optional `limit` (integer)
request parameter bounding the number of `EventSummary` rows returned.
When omitted, `limit` defaults to `50`. When provided and less than or
equal to `0`, the tool MUST reject the call as a `ValueError` before any
adapter call. When provided and greater than `200`, the tool MUST clamp
it to `200` (never reject) — matching `mail_search`/`task_search` and
`file_search`'s existing cap convention. The adapter MUST apply the
(defaulted/clamped) limit at the source — bounding item iteration over
the mocked/real `Items` collection — never fetching an unbounded set and
truncating client-side.

#### Scenario: Wide window is bounded to the default limit

- GIVEN a mocked `win32com.client` calendar `Items` collection seeded with 240 events across a 3-month window all matching the search bounds
- WHEN `calendar_search` is called with `from`/`to` spanning that 3-month window, `limit` omitted
- THEN at most 50 `EventSummary` items are returned
- AND `results_truncated` is `true`

#### Scenario: limit above hard max is clamped, not rejected

- GIVEN a mocked adapter seeded with 300 matching events
- WHEN `calendar_search` is called with a valid `from`/`to`, `limit=500`
- THEN the adapter's `search()` is invoked with a limit of `200`, not `500`, and no error is raised

#### Scenario: Non-positive limit is rejected

- WHEN `calendar_search` is called with `subject="x"`, `limit=-1`
- THEN the tool raises a `ValueError` before calling the adapter

### Requirement: Newest-First Ordering

`calendar_search` results MUST be ordered newest-first by `start`, so
that when the cap truncates results the returned page is the most
recent, most useful subset. (The adapter's existing `Sort("[Start]")`
ascending call, if retained, MUST be paired with a reversal or
equivalent so the tool-visible order is newest-first.)

#### Scenario: Out-of-order source items are returned newest-first

- GIVEN a mocked calendar `Items` collection seeded with 3 events starting out of chronological order (e.g. Aug 10, Aug 1, Aug 20), all matching the search filter
- WHEN `calendar_search` is called with a `from`/`to` window covering all three
- THEN the returned `EventSummary` list is ordered Aug 20, Aug 10, Aug 1 (newest first)

## MODIFIED Requirements

### Requirement: Search Output Shape

The tool MUST return a list of objects containing exactly `entryId`,
`subject`, `start`, and `end` (ISO 8601 strings). It MUST NOT include
the event body — this is unchanged by this change and MUST NOT
regress; the body remains available only via `calendar_get_event`. The
response MUST additionally convey a `results_truncated` boolean value
that is `true` when the effective `limit` cut the true match count, and
`false` (or absent, treated as falsy) otherwise. The exact response
shape carrying `results_truncated` alongside the row list is an
implementation decision left to `design.md`.
(Previously: returned a plain list with no truncation signal and no
documented cap.)

#### Scenario: Empty result set

- GIVEN a fake adapter whose `search()` returns an empty list for the given filters
- WHEN `calendar_search` is called with `subject="Nonexistent"`
- THEN the tool returns an empty result with `results_truncated` falsy, not an error

#### Scenario: Under-cap search is not marked truncated

- GIVEN a mocked calendar `Items` collection seeded with 26 events matching the search window
- WHEN `calendar_search` is called with that window and `limit=50`
- THEN all 26 `EventSummary` items are returned
- AND `results_truncated` is `false`

#### Scenario: Rows never carry body content

- GIVEN a mocked calendar `Items` collection seeded with an event that has a large body/notes property
- WHEN `calendar_search` is called with a filter matching that event
- THEN the returned `EventSummary` contains no body field of any kind
