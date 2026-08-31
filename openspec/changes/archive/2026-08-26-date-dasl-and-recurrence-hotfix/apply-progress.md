# Apply Progress: DASL Date Restrict + Recurrence-Expansion Hotfix

**Status**: Complete — all 6 phases (see `tasks.md`) done under Strict TDD.

## Summary

Fixed BUG-004 (lower-bound date transposition, silent empty ranges) and
BUG-005 (calendar subject-only search returning nothing; recurring series
vanishing) from live es-ES Outlook evidence gathered against the
`outlook-date-locale-fix` + `search-result-caps` build.

## Root Causes Confirmed

- **BUG-004**: `Items.Restrict()`'s bracket-property Jet syntax
  (`[Start] >= '...'`) still locale-parses an ISO-ordered date literal
  under es-ES — the earlier `outlook-date-locale-fix` change fixed the
  literal's *format* but not the *comparison syntax* that parses it.
  Fixed by switching both adapters to DASL `@SQL=` syntax against a
  quoted property URN.
- **BUG-005 part 2 (recurrence loss)**: confirmed by re-reading
  `tools/outlook_adapter.py::search()` — the search-result-caps change
  (BUG-002) flipped `items.Sort("[Start]", True)` (descending) for an
  iteration early-stop optimization, which breaks Outlook COM's
  documented requirement that `IncludeRecurrences` expansion needs an
  ascending Sort() before Restrict(). Fixed by reverting to ascending
  Sort() and moving the newest-first ordering + `limit + 1` bound to a
  post-collection Python sort/slice.
- **BUG-005 part 1 (subject-only search)**: confirmed by reading
  `tools/calendar.py::_normalize_search_bounds()` + `tools/
  outlook_adapter.py::search()`'s boundary re-check — a subject-only
  request's auto-filled `lookback_days` window was being enforced as a
  strict date filter on results, even though the caller supplied no date
  bound at all. Fixed by adding `enforce_date_bounds` (default `True`),
  threaded as `False` only when the tool-layer request had no explicit
  `from`/`to`.

## Files Changed

- `tools/outlook_adapter.py` — `CalendarPort.search()` protocol +
  `OutlookCalendarAdapter.search()`: DASL Restrict, ascending Sort,
  `enforce_date_bounds`, Python-side newest-first re-sort.
- `tools/mail_adapter.py` — `_FOLDER_MAP` (4th element: DASL property
  URN), `OutlookMailAdapter.search()`'s Restrict() clause, `_resolve_
  folder_id()`'s tuple unpack.
- `tools/fake_adapter.py` — `FakeCalendarAdapter.search()`: mirrors
  `enforce_date_bounds`.
- `tools/calendar.py` — `enforce_date_bounds` threading, inverted-range
  guard.
- `tools/mail.py`, `tools/tasks.py` — inverted-range guard.
- `tests/test_outlook_adapter.py`, `tests/test_mail_adapter.py`,
  `tests/test_calendar_tools.py`, `tests/test_mail_tools.py`,
  `tests/test_tasks_tools.py` — updated existing assertions for the new
  DASL/Sort shape; added regression tests (superset containment, subject
  self-consistency, recurrence, inverted-range guard, mocked-COM sequence
  assertions).
- `openspec/specs/{calendar-search,mail-search,outlook-com-adapter,
  outlook-mail-adapter}/spec.md` — new requirements/scenarios.

## Test Result

`.venv/bin/python3.12 -m pytest -q` → **476 passed** (456 baseline + 20
new: 4 in `test_outlook_adapter.py` net after 1 rewrite, 0 net new in
`test_mail_adapter.py` (3 rewrites, 0 additions), 6 in
`test_calendar_tools.py`, 2 in `test_mail_tools.py`, 1 in
`test_tasks_tools.py`, plus the calendar-adapter additions above).

## Risks

- The DASL property URNs for `SentOn` (`urn:schemas:httpmail:datesent`)
  and `LastModificationTime` (MAPI property-tag form) are the standard,
  documented choices but unverified against a real es-ES Outlook client —
  same platform limitation as the prior `outlook-date-locale-fix` change.
  Recommend a manual live-Outlook smoke test post-deploy.
- Dropping the calendar adapter's iteration early-stop (now a full
  `Restrict()`-bounded collect + Python sort) trades a small amount of
  work for correctness; `Restrict()` already bounds the window, so this
  is expected to be inexpensive in practice, but was not benchmarked
  against a real, large calendar.
- `enforce_date_bounds=False` relies on the tool layer's own
  "explicit vs auto-filled bounds" determination being correct; a future
  change adding another way to reach `calendar_search` without going
  through `tools/calendar.py::calendar_search()` would need to reason
  about this flag explicitly.
