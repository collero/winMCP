# Apply Progress: Subject-Only Search Window Contract Hotfix

**Status**: Complete — all 6 phases (see `tasks.md`) done under Strict TDD.

## Summary

Fixed BUG-008: `calendar_search`'s subject-only path silently applied the
backward-only `lookback_days` window (needed to bound the adapter's
Restrict()/recurrence-expansion query — that part is structurally correct
and untouched), which meant a subject-only search could never see a future
appointment and returned `[]`/`resultsTruncated: false` indistinguishable
from "no such appointment" whenever a real match fell outside the window.

## Root Cause Confirmed

`tools/calendar.py::_normalize_search_bounds()` filled a fully-omitted
`from`/`to` pair (the subject-only case — guaranteed by `calendar_search`'s
own "at least one filter" guard) with `now - lookback_days` .. `now`: a
backward-only span that never reaches the future and, for anything older
than `lookback_days` (default 7), never reaches far enough back either.
The response carried no signal that a window had been applied at all.

## Fix

- New dedicated config pair (`calendar_subject_search_lookback_days`
  default 90, `calendar_subject_search_lookahead_days` default 365) used
  ONLY for the fully-omitted subject-only case; the partial-explicit-range
  fallback (only one of `from`/`to` given) keeps using `lookback_days`
  unchanged.
- New `SearchWindow` schema + `CalendarSearchResult.window_applied`
  (alias `windowApplied`), populated only when the tool auto-applied a
  window to a subject-only request — never for an explicit-bounds request.
- New `tools/calendar._now()` seam replacing the inline
  `datetime.now(timezone.utc)` call, so tests freeze "now" deterministically
  instead of depending on wall-clock timing.
- `server.py`'s `calendar_search` tool description now documents the
  default window and that explicit `from`/`to` override it.

## Files Changed

- `config/settings.yaml` — two new keys + doc comment.
- `tools/settings.py` — `calendar_subject_search_lookback_days()`/
  `calendar_subject_search_lookahead_days()`.
- `models/schemas.py` — `SearchWindow`; `CalendarSearchResult.window_applied`.
- `tools/calendar.py` — `_now()` seam; `_subject_search_window()`;
  `calendar_search()` branches explicit-bounds vs. subject-only window
  resolution and threads `window_applied` through.
- `server.py` — `_calendar_search` docstring.
- `tests/test_calendar_tools.py` — rewrote the lookback-window test to the
  new subject-search window shape; added `window_applied` assertions to
  the explicit-bounds and empty-result tests; added the past+tomorrow
  regression test; replaced the flaky self-consistency test with the
  amended out-of-window version.
- `openspec/specs/calendar-search/spec.md` — new requirement + 4 scenarios.

## Test Result

`.venv/bin/python3.12 -m pytest -q` -> **516 passed**. `tests/test_calendar_tools.py`
alone: 23/23 passed. Baseline at Phase 0 was 486; the full-suite total
includes this change's net contribution to `test_calendar_tools.py` plus
unrelated concurrent additions to the file-search test files landed in the
same working tree by another agent (out of this change's scope — confirmed
by per-file test counts, not by inspecting that agent's diff).

## Risks

- The new default window (90 back / 365 forward) is a judgment call from
  the live verifier's recommendation, not a value tied to any measured
  Outlook performance characteristic — a very large personal calendar
  could make the real adapter's `Restrict()` query for a subject-only
  search noticeably slower than before (previously bounded to at most 7
  days). Not benchmarked against a real Outlook profile.
- `windowApplied`'s absence-vs-null-vs-populated distinction depends on
  every current and future caller of `calendar_search()` routing through
  this one function; a future direct-adapter caller bypassing
  `tools/calendar.py` would need to reason about this explicitly, same
  caveat as the existing `enforce_date_bounds` flag.
