# Delta for Outlook COM Adapter

## ADDED Requirements

### Requirement: DASL `@SQL=` Restrict Date Literals, Not Jet Bracket Syntax

`OutlookCalendarAdapter.search()`'s `Items.Restrict()` date-range clause
MUST compare `_dasl_datetime()`'s ISO-ordered literal via DASL `@SQL=`
syntax against the quoted property URNs `"urn:schemas:calendar:dtstart"`
and `"urn:schemas:calendar:dtend"`, never Jet's bare bracket-property
syntax (`[Start] >= '...'`). Live evidence (BUG-004, 2026-08-26) showed
that even an ISO-ordered literal is still misparsed by Jet under an es-ES
Outlook client when compared via bracket syntax: the lower bound's day was
read as transposed whenever it was `<= 12`, inverting the range and
returning `[]` with no error. DASL `@SQL=` date-literal comparisons against
a quoted property URN are documented as culture-invariant.

#### Scenario: Restrict() clause uses DASL @SQL= syntax with quoted property URNs

- GIVEN a mocked `win32com.client` module
- WHEN `OutlookCalendarAdapter().search(date_from, date_to)` builds its `Restrict()` clause
- THEN the emitted string starts with `@SQL="urn:schemas:calendar:dtstart" >=`
- AND contains `"urn:schemas:calendar:dtend" <=`
- AND never contains the bare bracket form `[Start]` or `[End]`

#### Scenario: Lower bound with day <= 12 is not transposed

- GIVEN a mocked `win32com.client` module whose Calendar folder's `Items` are seeded with an event on 2026-01-08 and one on 2026-02-06
- WHEN `OutlookCalendarAdapter().search(date_from=2026-01-08T00:00:00, date_to=2026-02-08T23:59:59)` is called
- THEN both events are returned (an inverted-range misread would have excluded the 2026-01-08 event or returned nothing at all)

### Requirement: Ascending Sort Before Restrict, Required for Recurrence Expansion

`OutlookCalendarAdapter.search()` MUST set `items.IncludeRecurrences = True`,
then call `items.Sort("[Start]", False)` (ascending), strictly before calling
`items.Restrict()`. Outlook COM only expands a recurring series into its
individual occurrences through `Restrict()`/`Find()` when the source
`Items` collection was sorted ascending by `[Start]` first; a descending
sort (introduced by the search-result-caps change, BUG-002, purely as an
early-stop optimization) silently breaks recurrence expansion — every
occurrence of every recurring series is dropped from the `Restrict()`
output, while one-off (non-recurring) items are unaffected (BUG-005 part
2, 2026-08-26 live evidence). Newest-first output order (still required)
is produced by sorting the collected, `Restrict()`-bounded match list in
Python after the boundary re-check and subject filter, rather than relying
on descending COM-source order for an iteration early-stop.

#### Scenario: IncludeRecurrences, ascending Sort, then Restrict, in that order

- GIVEN a mocked `win32com.client` module
- WHEN `OutlookCalendarAdapter().search(date_from, date_to)` is called
- THEN `items.IncludeRecurrences` is `True`
- AND `items.Sort` is called with `("[Start]", False)`
- AND `items.Sort` is called before `items.Restrict`

#### Scenario: Recurring series' occurrences are all returned, newest-first

- GIVEN a mocked, ascending-ordered `Restrict()` result containing four occurrences of a recurring series plus one one-off event, all within the search window
- WHEN `OutlookCalendarAdapter().search(date_from, date_to)` is called
- THEN all five items are returned
- AND they are ordered newest-first by `start`

### Requirement: Boundary Re-Check Is Skippable for Auto-Filled Windows

`OutlookCalendarAdapter.search()` MUST accept an `enforce_date_bounds`
keyword (default `True`). When `False`, the Python-side boundary re-check
(`start < date_from or end > date_to`) MUST be skipped entirely — only the
subject filter (and whatever `Restrict()` itself returned) determines the
result. `date_from`/`date_to` still bound the `Restrict()` call regardless
of this flag, so `IncludeRecurrences` expansion stays bounded. The tool
layer passes `False` only for a request whose `from`/`to` were both
omitted by the caller and auto-filled from `lookback_days` (BUG-005 part
1, 2026-08-26 live evidence: a subject-only query for an event provably
visible via a date-bounded query returned nothing, because the
auto-filled window excluded the event's actual date).

#### Scenario: enforce_date_bounds=False returns a subject match outside the window

- GIVEN a mocked `Restrict()` result containing one item whose `Start`/`End` fall entirely outside `date_from`/`date_to`
- WHEN `OutlookCalendarAdapter().search(date_from, date_to, subject=<that item's subject>, enforce_date_bounds=False)` is called
- THEN the item is returned

#### Scenario: enforce_date_bounds=True (the default) still drops out-of-window items

- GIVEN the same mocked `Restrict()` result as above
- WHEN `OutlookCalendarAdapter().search(date_from, date_to, subject=<that item's subject>)` is called (no `enforce_date_bounds` override)
- THEN the item is dropped by the boundary re-check
