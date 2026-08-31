# Tasks: DASL Date Restrict + Recurrence-Expansion Hotfix

## Phase 0: Baseline

- [x] 0.1 Run `.venv/bin/python3.12 -m pytest -q`; record baseline pass count. (456 passed)

## Phase 1: Calendar Adapter — DASL Restrict, Ascending Sort, enforce_date_bounds (Strict TDD)

- [x] 1.1 RED `tests/test_outlook_adapter.py`: update
      `test_search_builds_dasl_restrict_and_converts_tz`'s Sort/Restrict
      assertions to the new ascending/DASL shape; add
      `test_search_sort_ascending_called_before_restrict_for_recurrence_expansion`,
      `test_search_recurring_series_occurrences_returned_newest_first`,
      `test_search_subject_only_default_window_skips_boundary_recheck`.
      Confirm all four fail against current code. (Confirmed: 4 failed.)
- [x] 1.2 GREEN `tools/outlook_adapter.py`: `CalendarPort.search()` gains
      `enforce_date_bounds: bool = True`; `Sort("[Start]", False)`
      (ascending) before `Restrict()`; `Restrict()` clause switched to
      `@SQL="urn:schemas:calendar:dtstart"`/`"...dtend"`; boundary
      re-check gated on `enforce_date_bounds`; early-stop-during-iteration
      removed, replaced by collect-then-sort-descending-then-slice.
      Updated the pre-existing `test_search_early_stops_after_limit_plus_
      one_matches` (renamed
      `test_search_bounds_result_to_limit_plus_one_no_early_stop_iteration`)
      to reflect the new full-consumption behavior. Confirm all tests
      pass. (26/26 passed.)

## Phase 2: Mail Adapter — DASL Restrict (Strict TDD)

- [x] 2.1 RED `tests/test_mail_adapter.py`: update the three existing
      `restrict_arg` assertions (`test_inbox_search_restricts_on_received_time`,
      `test_sent_search_restricts_on_sent_on`,
      `test_drafts_search_uses_get_default_folder_16_and_restricts_on_last_modification_time`)
      to the new DASL shape. Confirm all three fail. (Confirmed: 3 failed.)
- [x] 2.2 GREEN `tools/mail_adapter.py`: `_FOLDER_MAP` gains a 4th element
      (quoted DASL property URN per folder); `Restrict()` clause switched
      to `@SQL=<urn> >= '...' AND <urn> <= '...'`; `Sort()` unchanged
      (bracket form, descending). Fixed the resulting `_resolve_folder_id()`
      3-tuple unpack (now 4-tuple). Confirm all tests pass. (43/43 passed.)

## Phase 3: FakeCalendarAdapter mirrors enforce_date_bounds

- [x] 3.1 `tools/fake_adapter.py`: `search()` gains `enforce_date_bounds:
      bool = True`; the date-overlap check is skipped when `False`.
      Confirm `tests/test_fake_adapter.py` unaffected (all pre-existing
      calls pass `enforce_date_bounds` implicitly as `True`).

## Phase 4: Tool-Layer — enforce_date_bounds threading + inverted-range guard (Strict TDD)

- [x] 4.1 RED/GREEN `tools/calendar.py`: thread
      `enforce_date_bounds=(request.date_from is not None or
      request.date_to is not None)` into `adapter.search()`; add the
      `date_from > date_to` guard (raises `ValueError` echoing both
      bounds) after `_normalize_search_bounds()`. Updated
      `test_search_valid_range_and_subject`'s exact `spy.assert_called_
      once_with(...)` to include the new kwarg. Added: `test_search_
      explicit_bounds_enforce_date_bounds_true`, `test_search_inverted_
      range_raises_value_error_echoing_both_bounds`, `test_search_
      subject_only_finds_event_far_outside_default_lookback_window`,
      `test_search_subject_taken_from_date_query_result_is_findable_by_
      subject`, `test_search_wider_range_is_superset_of_narrower_
      contained_range`, `test_search_recurring_series_all_occurrences_
      returned_within_window`. All pass. (31/31 in
      `tests/test_calendar_tools.py` + `tests/test_fake_adapter.py`.)
- [x] 4.2 RED/GREEN `tools/mail.py`: same inverted-range guard (no
      `enforce_date_bounds` — mail's subject/sender filters were
      confirmed working in the live evidence, out of scope). Added
      `test_search_inverted_range_raises_value_error_echoing_both_bounds`,
      `test_search_wider_range_is_superset_of_narrower_contained_range`.
      All pass.
- [x] 4.3 RED/GREEN `tools/tasks.py`: same inverted-range guard on
      `request.date_from`/`date_to` directly (no lookback-fill exists for
      tasks). Added `test_search_inverted_range_raises_value_error_
      echoing_both_bounds`. All pass.

## Phase 5: Full Suite

- [x] 5.1 Run `.venv/bin/python3.12 -m pytest -q`; confirm zero
      regressions against the Phase 0 baseline + all new tests green.
      (476 passed — 20 new tests, 456 baseline unchanged.)

## Phase 6: Specs

- [x] 6.1 Append new requirements/scenarios to `openspec/specs/
      calendar-search/spec.md`, `mail-search/spec.md`,
      `outlook-com-adapter/spec.md`, `outlook-mail-adapter/spec.md`.
- [x] 6.2 Record this change's proposal/design/tasks/apply-progress under
      `openspec/changes/archive/2026-08-26-date-dasl-and-recurrence-hotfix/`,
      including delta spec copies, mirroring the two prior 2026-08-26
      hotfix archives' style.
