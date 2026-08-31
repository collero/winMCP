# Design: DASL Date Restrict + Recurrence-Expansion Hotfix

## Decision: DASL `@SQL=` Restrict, quoted property URN, not Jet bracket syntax

Outlook's `Items.Restrict()` accepts two syntaxes: Jet SQL-like bracket
properties (`[Start] >= '...'`) and DASL (`@SQL="urn:..." >= '...'`). Jet's
bracket form parses its date-literal operand through the Outlook client's
configured locale even when the literal is ISO-ordered — this is BUG-004's
root cause, confirmed by live es-ES evidence: identical upper bound,
`from=2026-01-19` (day >= 13, unswappable) returns rows, `from=2026-01-08`
(day <= 12, swappable) returns `[]`. DASL `@SQL=` comparisons against a
quoted property URN are documented as culture-invariant regardless of
client locale. We therefore switch both adapters' date-range `Restrict()`
clause to `@SQL=` syntax, keeping `_dasl_datetime()`'s existing
`"%Y-%m-%d %H:%M"` literal format (already correct — the bug was the
comparison syntax, not the literal's shape).

Property URNs used: `"urn:schemas:calendar:dtstart"`/`"...dtend"` for
calendar; `"urn:schemas:httpmail:datereceived"` (inbox),
`"urn:schemas:httpmail:datesent"` (sent), and the MAPI property-tag form
`"http://schemas.microsoft.com/mapi/proptag/0x30080040"` (`PR_LAST_
MODIFICATION_TIME`) for drafts, which has no `httpmail` schema equivalent.
`Sort()` keeps the bracket property name (`"[Start]"`, `"[ReceivedTime]"`,
etc.) in both adapters — sorting by property name parses no date literal,
so it carries none of this locale risk.

This cannot be verified against real Outlook from this Linux dev host (no
`win32com`); coverage is mocked-COM assertions on the exact `Restrict()`
string, per the project's standing rule that all COM scenarios specify
mocked behavior.

## Decision: Ascending Sort before Restrict; newest-first re-sort in Python

Outlook COM's `IncludeRecurrences = True` only expands a recurring series
into individual occurrences when `Restrict()`/`Find()` runs against a
source collection sorted ascending by the date field first — documented
Outlook COM behavior. The search-result-caps change (BUG-002) flipped
calendar's `Sort("[Start]", ...)` to descending purely to let the
post-filter loop early-stop once it had seen `limit + 1` newest-first
matches. That traded away recurrence expansion for an iteration
optimization without noticing the interaction — BUG-005 part 2.

Fix: `items.Sort("[Start]", False)` (ascending), unconditionally, before
`Restrict()`. Since the source order is no longer newest-first, the
early-stop-during-iteration optimization is dropped entirely for the
calendar adapter: `search()` now collects every `Restrict()`-bounded,
boundary/subject-filtered match, then sorts that (expected-small, since
`Restrict()` already bounds the window) list by `start` descending in
Python, then slices to `limit + 1` (the "+1 peek" convention is
preserved — only the mechanism producing it changed).

Mail's adapter is unaffected: it has no `IncludeRecurrences` requirement,
so its existing descending `Sort()` + iteration early-stop is untouched.

## Decision: `enforce_date_bounds` flag skips the boundary re-check for auto-filled windows

BUG-005 part 1's live evidence ("AGC-COS", "inAtlas", "Cumpleanos" — a
subject search returns `[]` for subjects a date-bounded query on the same
build just returned) is explained by `tools/calendar.py`'s existing
design: a subject-only request (no explicit `from`/`to`) still resolves
concrete `date_from`/`date_to` via `_normalize_search_bounds()`'s
`lookback_days` default-fill, purely because `CalendarPort.search()`
requires non-optional bounds. Those auto-filled bounds then feed the
adapter's Python-side boundary re-check unconditionally, which drops any
match whose real date falls outside that backward-looking window — even
though the caller never supplied a date filter and has no way to know one
was silently applied.

Fix: `CalendarPort.search()` gains `enforce_date_bounds: bool = True`.
`date_from`/`date_to` still bound the `Restrict()` call unconditionally
(required so `IncludeRecurrences` expansion stays bounded — an unbounded
`Restrict()`-less iteration with `IncludeRecurrences=True` never
terminates), but when `False`, the Python-side boundary re-check after
`Restrict()` is skipped — only the subject filter (and whatever
`Restrict()` itself returned) determines the result. `tools/calendar.py`
passes `enforce_date_bounds=(request.date_from is not None or
request.date_to is not None)` — `False` only for a genuinely
subject-only request. `calendar_get_notes` is unaffected (always passes
explicit day bounds, so the default `True` applies).

Deliberately NOT changed: `lookback_days`'/`mail_lookback_days`'
backward-looking *direction* or default *value* — an existing test
(`test_search_defaults_missing_bounds_using_lookback_window`) fixes this
at exactly 7 days, and widening or reversing it was explicitly out of
scope for this hotfix.

## Decision: Inverted-range guard at the tool layer, not the adapter

`calendar_search`/`mail_search`/`task_search` now raise a plain
`ValueError` (mapped by `server.py::_map_error` to an `[invalid_request]`
MCP tool error, the same mechanism already used for the "at least one
filter" rule) whenever the resolved `from > to`, echoing both bounds in
the message. Checked at the tool layer (after `_normalize_search_bounds`
for calendar/mail, directly on the request for tasks, which has no
lookback-fill) rather than in the adapter/fake, since it is a pure
input-validation concern independent of which adapter answers the call —
and because raising here means the adapter (real or fake) is never
invoked with a nonsensical range in the first place.

## Open Questions / Follow-Ups

- The DASL property URN for `SentOn` (`"urn:schemas:httpmail:datesent"`)
  and the MAPI property-tag form for `LastModificationTime` are the
  standard, documented choices, but — like the rest of this change — are
  unverifiable against a real es-ES Outlook client from this dev host.
  Recommend a manual live-Outlook smoke test post-deploy, mirroring the
  `outlook-date-locale-fix` change's own deferred follow-up.
- `IncludeRecurrences` + ascending `Sort()` is documented Outlook COM
  behavior but likewise cannot be exercised against a real recurring
  series here; mocked-COM sequence assertions (`Sort()` args, call order
  relative to `Restrict()`) are the strongest verification available on
  this platform.
