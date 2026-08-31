# Proposal: Datetime Timezone-Comparison Hotfix

## Intent

`calendar_search` and `mail_search` fail on real Outlook with:

```
Error calling tool 'mail_search': can't compare offset-naive and
offset-aware datetimes
```

`task_search` and file tools were reported unaffected. Invisible to the
Linux dev suite (451 tests, all green) — only surfaced on real Windows
QA.

## Root Cause

Two Python-side datetime comparisons were added by recent changes:

1. the outlook-date-locale-fix change's boundary re-check (comparing
   parsed request bounds against item `Start`/`End`/`ReceivedTime`, as
   defense-in-depth against DASL `Restrict()` locale surprises), and
2. the search-result-caps change's newest-first sort keys + early-stop
   iteration.

On real Windows, pywintypes.datetime COM properties (`item.Start`,
`item.End`, `ReceivedTime`, `SentOn`, `LastModificationTime`) come back
**timezone-aware** with a fixed offset. But `SearchRequest.date_from`/
`date_to` and `MailSearchRequest.date_from`/`date_to`
(`models/schemas.py`) have **no tz-aware validator** — a caller (or the
`_normalize_search_bounds` lookback-fill path, when the client's own JSON
payload used a naive ISO string) can hand the adapter a **naive**
`date_from`/`date_to`. `_to_aware()` in `tools/outlook_adapter.py`/
`tools/mail_adapter.py` was applied to the COM-side value (`item.Start`,
`ReceivedTime`, etc.) but never to the request-bound side of the same
comparison, so an aware `start`/`ReceivedTime` compared directly against
a naive `date_from`/`date_to` raised `TypeError: can't compare
offset-naive and offset-aware datetimes`.

The dev-host fakes never modeled this: every fake COM item fixture in
`tests/test_outlook_adapter.py`/`tests/test_mail_adapter.py` used a
**naive** `Start`/`End`/`ReceivedTime` (simulating Outlook's local time),
and every request bound in those tests was **already timezone-aware**
(`tzinfo=timezone.utc`) — so both sides always ended up aware after
`_to_aware()`, and the mismatched-naive-side bug was structurally
impossible to hit. The internally-consistent fakes hid a real-world gap.

`task_adapter.py`'s `_passes_due_date_filter` has the *identical* latent
defect (`due_date` normalized to aware via `_to_aware`, `date_from`/
`date_to` left as-is) — `TaskSearchRequest.date_from`/`date_to` also carry
no tz-aware validator. `task_search` was reported working in the field
only because that QA session didn't exercise it with an explicit
`dueFrom`/`dueTo` bound, not because the code path is actually safe. This
hotfix fixes it too, defensively, for consistency.

## Fix

Normalize **both sides** of every Python-side datetime comparison/sort
through the same per-module `_to_aware(value, tz)` helper already
established by the codebase (design.md's "Duplicate the fix per module,
not extract a shared helper" precedent from the BUG-003 locale fix) —
consistency over novelty, no new abstraction introduced:

- `tools/outlook_adapter.py::OutlookCalendarAdapter.search()`: normalize
  `date_from`/`date_to` via `_to_aware(_, tz)` immediately after computing
  `tz`, before the boundary re-check loop.
- `tools/mail_adapter.py::_matches_date_bounds()`: normalize `date_from`/
  `date_to` via `_to_aware(_, tz)` at the same site as the item-side
  `date_value` normalization. This single function is the shared boundary
  re-check for every folder (`inbox`/`sent`/`drafts` as defense-in-depth,
  `folder_path` as its only date filter), so one fix covers all paths.
- `tools/task_adapter.py::OutlookTaskAdapter.search()`: same normalization
  for `date_from`/`date_to`, defensively, even though this path wasn't the
  reported failure.

`_to_aware()` is a no-op when the value is already aware, so this is safe
regardless of which side (or neither) was naive.

## Risk

Low. Purely additive normalization inside existing comparison sites; no
change to public interfaces, return shapes, or error taxonomy. Does not
touch `_dasl_datetime()`/DASL literal construction (which only reads
wall-clock fields via `strftime`, unaffected by tzinfo).

## Rollback

Redeploy the previous zip. No data migration, no config/schema change.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `tools/outlook_adapter.py` | Modified | `search()`: normalize `date_from`/`date_to` to aware before the boundary re-check |
| `tools/mail_adapter.py` | Modified | `_matches_date_bounds()`: normalize `date_from`/`date_to` to aware before comparing |
| `tools/task_adapter.py` | Modified | `search()`: same normalization, defensive (not the reported failure) |
| `tests/test_outlook_adapter.py` | Modified | New tests: aware item vs naive bound; naive all-day item vs aware bound |
| `tests/test_mail_adapter.py` | Modified | New tests: aware `ReceivedTime` vs naive bound (inbox); aware items vs naive bound through the `folder_path` sort path |
| `tests/test_task_adapter.py` | Modified | New defensive test: aware `DueDate` vs naive bound |
| `openspec/specs/outlook-com-adapter/spec.md` | Modified | New "Timezone-Aware Boundary Comparisons" requirement |
| `openspec/specs/outlook-mail-adapter/spec.md` | Modified | New "Timezone-Aware Boundary Comparisons" requirement |

## Success Criteria

- [x] `calendar_search`'s and `mail_search`'s Python-side boundary checks
      never compare a naive datetime against an aware one
- [x] `task_search`'s due-date filter fixed defensively, same pattern
- [x] Full test suite green: 451 pre-existing tests + 5 new, zero
      regressions
