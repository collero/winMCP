# Tasks: Subject-Only Search Window Contract Hotfix

## Phase 0: Baseline

- [x] 0.1 Run `.venv/bin/python3.12 -m pytest -q`; record baseline pass count. (486 passed)

## Phase 1: Config + Settings Accessors

- [x] 1.1 `config/settings.yaml`: add `calendar_subject_search_lookback_days: 90`
      and `calendar_subject_search_lookahead_days: 365`, documented in the
      header comment block alongside the existing `lookback_days` note.
- [x] 1.2 `tools/settings.py`: add `calendar_subject_search_lookback_days()`
      and `calendar_subject_search_lookahead_days()`, live-read via
      `load_settings()`, mirroring `resolve_search_limit()`'s discipline.

## Phase 2: Schema — `SearchWindow` + `window_applied` (Strict TDD)

- [x] 2.1 `models/schemas.py`: add `SearchWindow` (`date_from`/`date_to`,
      aliases `from`/`to`); `CalendarSearchResult` gains
      `window_applied: SearchWindow | None` (alias `windowApplied`, default
      `None`).

## Phase 3: Tool Layer — Subject-Search Window + Honesty (Strict TDD)

- [x] 3.1 RED `tests/test_calendar_tools.py`: rewrite
      `test_search_defaults_missing_bounds_using_lookback_window` ->
      `test_search_defaults_missing_bounds_using_subject_search_window`
      (frozen `_now`, asserts the new 90-back/365-forward window and
      `window_applied`); add `window_applied is None` assertion to
      `test_search_explicit_bounds_enforce_date_bounds_true`; add
      `window_applied is not None` assertion to
      `test_search_empty_result_returns_empty_list`; add
      `test_search_subject_only_finds_past_and_future_occurrences_under_new_defaults`
      (frozen `_now`, seeds one event ~60 days back and one 1 day forward,
      both found by subject alone); replace the flaky
      `test_search_subject_taken_from_date_query_result_is_findable_by_subject`
      with `test_search_subject_self_consistency_outside_default_window`
      (date query's window deliberately outside the subject-search
      default — seeds an event 400 days out, beyond the 365-day default —
      so the assertion cannot pass by luck). Confirmed all 4 touched/added
      tests fail against current code (`_now` attribute missing;
      `window_applied` absent from the old 7-day-only window shape).
- [x] 3.2 GREEN `tools/calendar.py`: add `_now()` seam (replaces the inline
      `datetime.now(timezone.utc)` call, mockable via
      `mocker.patch("tools.calendar._now", ...)`); add
      `_subject_search_window()` (symmetric, forward-leaning, reads the new
      config keys); `calendar_search` branches on `explicit_date_bounds` —
      explicit-bounds path unchanged (`_normalize_search_bounds()`);
      subject-only path calls `_subject_search_window()` and constructs a
      `SearchWindow` passed through as `CalendarSearchResult.window_applied`.
      Confirm all tests pass. (`tests/test_calendar_tools.py`: 23/23.)

## Phase 4: Tool Description

- [x] 4.1 `server.py`: `_calendar_search`'s docstring documents the default
      subject-search window (90 back / 365 forward, configurable) and that
      explicit `from`/`to` override it entirely, since the docstring is the
      only contract an agent caller ever sees.

## Phase 5: Full Suite

- [x] 5.1 Run `.venv/bin/python3.12 -m pytest -q`; confirm zero regressions
      against the Phase 0 baseline + all new tests green. (516 passed —
      baseline 486 plus this change's net contribution and concurrent
      file-search-track additions landed in the same working tree.)

## Phase 6: Specs + Archive

- [x] 6.1 Append the new requirement + scenarios to
      `openspec/specs/calendar-search/spec.md`.
- [x] 6.2 Record this change's proposal/tasks/apply-progress + delta spec
      under
      `openspec/changes/archive/2026-08-26-subject-window-contract-hotfix/`,
      mirroring the prior 2026-08-26 hotfix archives' style.
