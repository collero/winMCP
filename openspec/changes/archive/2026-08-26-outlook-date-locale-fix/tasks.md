# Tasks: Fix Locale-Ambiguous Date Filters in Outlook Restrict() Calls

## Phase 0: Baseline

- [x] 0.1 Run `.venv/bin/python3.12 -m pytest -q`; record baseline pass count. (306 passed)

## Phase 1: Calendar Adapter (Strict TDD)

- [x] 1.1 RED `tests/test_outlook_adapter.py`: add
      `test_dasl_datetime_emits_iso_ordered_literal` (asserts
      `_dasl_datetime(datetime(2026,3,12,0,0))` == `"2026-03-12 00:00"`,
      not matching `\d{2}/\d{2}/\d{4}`),
      `test_search_transposition_prone_range_returns_only_bound_days`
      (mocked items on 06-08/06-09/09-04; `search(2026-06-06, 2026-06-09)`
      excludes 09-04),
      `test_search_full_month_crossing_range_excludes_december` (mocked
      March/April items + one 2026-12-03 item; `search(2026-03-12,
      2026-04-12)` excludes it),
      `test_search_control_range_day_ge_13_unchanged` (mocked 06-22..06-25
      items; `search(2026-06-20, 2026-06-25)` unchanged). Confirm the
      first three fail against current code. (Confirmed: 3 failed, 1
      passed.)
- [x] 1.2 GREEN `tools/outlook_adapter.py`: change `_dasl_datetime()` to
      `strftime("%Y-%m-%d %H:%M")`; add a Python-side boundary re-check in
      `search()` after `Restrict()` dropping any item whose `Start`/`End`
      falls outside `[date_from, date_to]`. Update the pre-existing
      `test_search_builds_dasl_restrict_and_converts_tz` literal assertion
      (`"07/27/2026"` → `"2026-07-27"`). Confirm all 1.1 tests + full
      existing file pass. (18/18 passed.)
- [x] 1.3 REFACTOR: update `_dasl_datetime`'s docstring/comments referencing
      the old format; no behavior change. (Done as part of 1.2's edit —
      docstring rewritten in place.)

## Phase 2: Mail Adapter (Strict TDD, mirrors Phase 1)

- [x] 2.1 RED `tests/test_mail_adapter.py`: add
      `test_dasl_datetime_emits_iso_ordered_literal`,
      `test_search_transposition_prone_range_returns_only_bound_days`
      (`folder="inbox"`, `[ReceivedTime]`, same 06-06/06-09 shape),
      `test_search_full_month_crossing_range_excludes_december`
      (`folder="sent"`, `[SentOn]`, same 03-12/04-12 shape),
      `test_search_control_range_day_ge_13_unchanged`. Confirm the first
      three fail against current code. (Confirmed: 3 failed, 1 passed.)
- [x] 2.2 GREEN `tools/mail_adapter.py`: mirror 1.2's format fix; add the
      same boundary re-check for `folder`-mapped searches (inbox/sent/
      drafts) after `Restrict()`, comparing against the already-resolved
      `ReceivedTime`/`SentOn`/`LastModificationTime`. Leave `folder_path`
      searches untouched (already Python-filtered, no `Restrict()`).
      Confirm all 2.1 tests + full existing file pass. (34/34 passed.)
- [x] 2.3 REFACTOR: update the "Mirrors `tools/outlook_adapter.py`" docstring
      note if the format comment drifted. (Done as part of 2.2's edit.)

## Phase 3: Cross-Module Consistency

- [x] 3.1 Add `test_calendar_and_mail_dasl_datetime_emit_identical_literal`
      (new tests file or appended to `tests/test_outlook_adapter.py`):
      import both `_dasl_datetime` functions, assert identical output for
      the same input, per design.md's "duplicate but mirror" decision.
      (Appended to tests/test_outlook_adapter.py; passes.)

## Phase 4: Full Suite

- [x] 4.1 Run `.venv/bin/python3.12 -m pytest -q`; confirm zero regressions
      against the Phase 0 baseline + all new tests green. (See
      apply-progress.md for the exact final summary line — full suite
      green, 9 new tests added across the two adapter test files.)
- [x] 4.2 Note in the PR/verify report that live-Outlook (es-ES) manual
      confirmation of Case 1/Case 4 from the original bug report is
      recommended post-deploy (design.md's non-blocking Open Question) —
      not required for this change's green suite. (Recorded — see
      apply-progress.md; not attempted from this Linux dev host per
      instructions.)
