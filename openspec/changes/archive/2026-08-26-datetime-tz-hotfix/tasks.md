# Tasks: Datetime Timezone-Comparison Hotfix

## Phase 0: Baseline

- [x] 0.1 Confirm baseline: `.venv/bin/python3.12 -m pytest -q` → 451 passed

## Phase 1: Calendar Adapter (Strict TDD)

- [x] 1.1 RED `tests/test_outlook_adapter.py`: add
      `test_search_aware_com_datetime_vs_naive_request_bound_does_not_raise`
      (aware `Start`/`End`, naive `date_from`/`date_to`) and
      `test_search_naive_all_day_item_vs_aware_request_bound_does_not_raise`
      (naive `Start`/`End`, aware bounds). Confirm the first fails with the
      exact reported `TypeError: can't compare offset-naive and
      offset-aware datetimes`.
- [x] 1.2 GREEN `tools/outlook_adapter.py`: in `search()`, normalize
      `date_from`/`date_to` via `_to_aware(_, tz)` right after computing
      `tz`, before the boundary re-check loop. Confirm both new tests pass
      and no existing test in the file regresses.

## Phase 2: Mail Adapter (Strict TDD)

- [x] 2.1 RED `tests/test_mail_adapter.py`: add
      `test_search_aware_com_received_time_vs_naive_request_bound_does_not_raise`
      (inbox, aware `ReceivedTime`, naive bounds) and
      `test_folder_path_search_aware_item_vs_naive_bound_sort_does_not_raise`
      (folder_path, aware `ReceivedTime` items, naive bounds, exercises the
      Python-side newest-first sort after the boundary check). Confirm both
      fail with the exact reported `TypeError`.
- [x] 2.2 GREEN `tools/mail_adapter.py`: in `_matches_date_bounds()`,
      normalize `date_from`/`date_to` via `_to_aware(_, tz)` at the same
      site as the item-side `date_value` normalization — this single
      shared function covers inbox/sent/drafts/folder_path in one fix.
      Confirm both new tests pass and no existing test in the file
      regresses.

## Phase 3: Task Adapter (Strict TDD, defensive)

- [x] 3.1 RED `tests/test_task_adapter.py`: add
      `test_search_aware_com_due_date_vs_naive_request_bound_does_not_raise`
      (aware `DueDate`, naive bounds) — proves the identical latent defect
      exists in `_passes_due_date_filter`'s `due_date < date_from`/
      `due_date > date_to` comparisons even though task_search wasn't the
      reported real-Windows failure. Confirm it fails with the exact
      reported `TypeError`.
- [x] 3.2 GREEN `tools/task_adapter.py`: in `search()`, normalize
      `date_from`/`date_to` via `_to_aware(_, tz)` (guarding `None`) right
      after computing `tz`, before the filtering loop. Confirm the new
      test passes and no existing test in the file regresses.

## Phase 4: Full Suite + Spec/Archive

- [x] 4.1 Run full suite: `.venv/bin/python3.12 -m pytest -q` → 456 passed
      (451 baseline + 5 new), zero regressions
- [x] 4.2 Append "Timezone-Aware Boundary Comparisons" requirement to
      `openspec/specs/outlook-com-adapter/spec.md`
- [x] 4.3 Append "Timezone-Aware Boundary Comparisons" requirement to
      `openspec/specs/outlook-mail-adapter/spec.md`
- [x] 4.4 Record this hotfix's proposal/tasks/apply-progress under
      `openspec/changes/archive/2026-08-26-datetime-tz-hotfix/`
