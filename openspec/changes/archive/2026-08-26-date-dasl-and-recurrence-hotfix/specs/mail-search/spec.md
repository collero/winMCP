# Delta for Mail Search

## ADDED Requirements

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
