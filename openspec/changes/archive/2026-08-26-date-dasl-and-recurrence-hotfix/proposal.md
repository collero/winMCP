# Proposal: DASL Date Restrict + Recurrence-Expansion Hotfix

## Intent

Two live-Outlook bug reports (es-ES, 2026-08-26) against the just-promoted
`outlook-date-locale-fix` build:

**BUG-004 (CRITICAL)**: the ISO-literal date fix only actually protected the
*upper* bound in practice. The *lower* bound of a `calendar_search`/
`mail_search` date range still silently transposes day/month whenever its
day is `<= 12`, under Jet's bracket-property `Restrict()` syntax
(`[Start] >= '2026-01-08 00:00'` parses as `2026-08-01` on this es-ES
client). A transposed lower bound INVERTS the range (lower > upper), and
`Items.Restrict()` then returns nothing — silently. `calendar
2026-03-12..2026-04-12` returns `[]` instead of March/April events;
`mail 2026-01-08..2026-02-08` returns `[]` while `mail
2026-01-19..2026-02-08` (identical upper bound, unswappable lower bound)
returns real rows. The earlier fix's Python-side boundary re-check only
ever narrows an *over*-inclusive Restrict() result; it cannot rescue an
*inverted* one, since there is nothing to narrow.

**BUG-005 (HIGH)**: two further `calendar_search` regressions, both
introduced by the search-result-caps change (BUG-002): (a) a `subject`-only
query returns `[]` for subjects a date-bounded query on the same build just
returned; (b) every occurrence of every recurring series (standing
meetings) vanished from every window, while one-off events survived.
Re-reading `tools/outlook_adapter.py::search()` confirms: the
search-result-caps change flipped `items.Sort("[Start]", True)` to
descending for an iteration early-stop, but Outlook COM's
`IncludeRecurrences` expansion (documented behavior) only runs through
`Restrict()`/`Find()` when the source collection was sorted ascending
first — descending silently drops every recurring occurrence. Separately,
a subject-only request's `date_from`/`date_to` are auto-filled from
`lookback_days` purely to bound the Restrict()/recurrence-expansion query;
the existing boundary re-check then also uses them as a strict filter,
dropping a real match whose actual date sits outside that auto-filled
window even though the caller never asked for a date filter at all.

## Scope

- `tools/outlook_adapter.py` (`OutlookCalendarAdapter`, `CalendarPort`,
  `_dasl_datetime`) — DASL `@SQL=` Restrict syntax, ascending Sort +
  Python-side newest-first re-sort, `enforce_date_bounds` skip.
- `tools/mail_adapter.py` (`OutlookMailAdapter`, `_FOLDER_MAP`,
  `_dasl_datetime`) — DASL `@SQL=` Restrict syntax for inbox/sent/drafts.
- `tools/fake_adapter.py` (`FakeCalendarAdapter`) — mirrors
  `enforce_date_bounds`.
- `tools/calendar.py`, `tools/mail.py`, `tools/tasks.py` — inverted-range
  guard (`from > to` raises `invalid_request`, never returns `[]`);
  `tools/calendar.py` additionally threads `enforce_date_bounds` based on
  whether the caller supplied any explicit `from`/`to`.
- `openspec/specs/{calendar-search,mail-search,outlook-com-adapter,
  outlook-mail-adapter}/spec.md` — new requirements/scenarios.
- Out of scope: `tools/task_adapter.py` (Python-side filtering only, no
  `Restrict()`, unaffected by either bug); mail's `subject`/`sender`
  filters (confirmed working in the live evidence, untouched).

## Non-Goals

- No change to `mail_lookback_days`/`lookback_days` default *values* or
  their backward-looking direction — only whether the boundary re-check
  they feed is enforced.
- No live-Outlook (es-ES) manual verification from this Linux dev host —
  all COM scenarios below are mocked, per project convention.
