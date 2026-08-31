# Delta for Calendar Search

## ADDED Requirements

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
