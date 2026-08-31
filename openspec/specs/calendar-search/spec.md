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

### Requirement: Outlook Unavailable

The tool MUST surface a clear, catchable error (not an unhandled crash) when the
underlying adapter cannot reach Outlook.

#### Scenario: COM dispatch failure

- GIVEN a fake adapter configured to raise `OutlookUnavailableError` from `search()`
  (simulating `win32com.client.Dispatch("Outlook.Application")` failing because
  Outlook is not installed or not running)
- WHEN `calendar_search` is called with any valid filter
- THEN the tool returns an MCP tool error whose message identifies Outlook as unavailable

### Requirement: Inverted Date Range Is Rejected, Not Silently Empty

If both `from` and `to` are given (or resolved, after the `lookback_days`
default-fill for an omitted bound) and `from` is after `to`, `calendar_search`
MUST raise before calling the adapter, rather than returning an empty result.
The error message MUST echo both resolved bounds. This guards against a
class of failure (BUG-004, 2026-08-26) where a locale-transposed lower bound
silently inverted a range and returned `[]` with no error and
`resultsTruncated: false` — the most misleading possible wrong answer.

#### Scenario: Explicit inverted range raises instead of returning empty

- GIVEN a `calendar_search` request with `from=2026-06-10` and `to=2026-06-01`
- WHEN `calendar_search` is called
- THEN it raises an error (surfaced as an `invalid_request` MCP tool error) whose message contains both `2026-06-10` and `2026-06-01`
- AND the adapter's `search()` is never called

### Requirement: Subject-Only Search Must Find Matches Outside the Default Lookback Window

A `calendar_search` request that supplies `subject` but neither `from` nor
`to` MUST still find a matching event even when that event's date falls
outside the `lookback_days`-derived default window used to bound the
adapter's date-range query. The auto-filled window exists only to bound the
adapter's `Restrict()`/recurrence-expansion query — it MUST NOT act as an
implicit date filter on a request the caller never bounded by date. An
explicit `from`/`to` (even alongside `subject`) is unaffected and continues
to filter strictly.

#### Scenario: Subject-only query finds an event far outside the lookback window

- GIVEN a fake adapter seeded with one event whose subject is "AGC-COS" and whose date is years outside the default `lookback_days` window
- WHEN `calendar_search` is called with `subject="AGC-COS"` and no `from`/`to`
- THEN the event is returned

#### Scenario: Subject taken from a date-bounded result is findable by subject alone

- GIVEN a fake adapter seeded with events, one of which a date-bounded `calendar_search` call returns
- WHEN a second `calendar_search` call is made using only that result's `subject`
- THEN the same event is returned by the subject-only call

### Requirement: Subject-Only Search Uses a Symmetric, Forward-Leaning Default Window, Reported Honestly

BUG-008 hotfix (2026-08-26): a `calendar_search` request that supplies
`subject` but neither `from` nor `to` MUST auto-apply a dedicated,
symmetric, forward-leaning default window —
`calendar_subject_search_lookback_days` (default `90`) days back and
`calendar_subject_search_lookahead_days` (default `365`) days forward
from now — rather than the backward-only `lookback_days` window used to
fill a *partially* explicit range. A backward-only default can never
answer "when is my next X?", the most common calendar question there is.

The tool MUST report the window it actually applied via an optional
`windowApplied` field (`{"from": ..., "to": ...}`) on the response,
populated ONLY when the request was subject-only and a window was
therefore auto-applied — never when explicit `from`/`to` were supplied.
`resultsTruncated` MUST NOT be overloaded to signal this; an empty
subject-only result MUST still carry `windowApplied` so a caller can
distinguish "no such appointment" from "outside a window it was never
told about". An explicit `from`/`to` (even alongside `subject`) always
takes full precedence over this default and MAY widen or narrow the
search — caller-controlled, unchanged from existing behavior.

#### Scenario: Subject-only search finds an appointment months in the past

- GIVEN a fake adapter seeded with an event dated 60 days before a frozen "now", matching subject "Cumpleanos Ada"
- WHEN `calendar_search` is called with `subject="Cumpleanos Ada"` and no `from`/`to`
- THEN the event is returned

#### Scenario: Subject-only search finds an appointment tomorrow

- GIVEN a fake adapter seeded with an event dated 1 day after a frozen "now", matching subject "AGC-COS"
- WHEN `calendar_search` is called with `subject="AGC-COS"` and no `from`/`to`
- THEN the event is returned

#### Scenario: Subject-only search reports the window it applied

- GIVEN a fake adapter seeded with no events
- WHEN `calendar_search` is called with `subject="Nonexistent"` and no `from`/`to`
- THEN the response's `results` list is empty
- AND the response's `windowApplied` field is populated with the resolved `from`/`to` bounds

#### Scenario: Explicit-bounds search never reports a window

- WHEN `calendar_search` is called with explicit `from`/`to` (with or without `subject`)
- THEN the response's `windowApplied` field is absent/null
