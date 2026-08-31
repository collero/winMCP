# Tasks: Live Folder-Id Configuration for All Outlook Adapters

## Phase 0: Baseline

- [x] 0.1 Confirm baseline: `.venv/bin/python3.12 -m pytest -q` -> 165 passed

## Phase 1: Calendar Adapter (Strict TDD)

- [x] 1.1 RED `tests/test_outlook_adapter.py`: add
      `test_search_uses_configured_calendar_folder_id` (mocks
      `tools.outlook_adapter.load_settings` -> `{"calendar_folder_id": 42}`,
      asserts `GetDefaultFolder(42)`) and
      `test_search_absent_calendar_folder_id_falls_back_to_default_9`
      (mocks `load_settings` -> `{}`, asserts `GetDefaultFolder(9)`).
      Confirm both fail against current hardcoded-constant code.
- [x] 1.2 GREEN `tools/outlook_adapter.py`: replace the `__init__`-cached
      `self._folder_id` with a `_resolve_folder_id()` method that calls
      `load_settings()` at COM-access time (falling back to
      `_DEFAULT_CALENDAR_FOLDER_ID` on a missing key or unreadable
      settings), and call it from `search()`. Confirm the 2 new tests pass
      and no existing test in the file regresses.
- [x] 1.3 Add `test_settings_yaml_declares_calendar_folder_id_9` (literal-key
      convention, mirrors `test_mail_tools.py`'s `mail_lookback_days` test).

## Phase 2: Task Adapter (Strict TDD)

- [x] 2.1 RED `tests/test_task_adapter.py`: mirror 1.1
      (`test_search_uses_configured_tasks_folder_id`,
      `test_search_absent_tasks_folder_id_falls_back_to_default_13`).
      Confirm RED.
- [x] 2.2 GREEN `tools/task_adapter.py`: same fix as 1.2, mirrored
      (`tasks_folder_id`, default `13`). Confirm GREEN, no regressions.
- [x] 2.3 Add `test_settings_yaml_declares_tasks_folder_id_13`.

## Phase 3: Mail Adapter (Strict TDD)

- [x] 3.1 RED `tests/test_mail_adapter.py`: add
      `test_search_uses_configured_inbox_and_sent_folder_ids` and
      `test_search_absent_folder_ids_fall_back_to_defaults_6_and_5`,
      covering both `MailFolder.INBOX`/`MailFolder.SENT`. Confirm RED.
- [x] 3.2 GREEN `tools/mail_adapter.py`: add a module-level
      `_resolve_folder_id(folder)` helper that reads
      `inbox_folder_id`/`sent_folder_id` from settings at COM-access time
      (falling back to `_FOLDER_MAP`'s default id), and use it in
      `search()` instead of the static `_FOLDER_MAP` lookup id. Update the
      stale "settings.yaml folder ids omitted" comment to record the
      reversal. Confirm GREEN, no regressions.
- [x] 3.3 Add `test_settings_yaml_declares_inbox_and_sent_folder_ids`
      (asserts both keys are absent-no-more, present with defaults `6`/`5`
      — requires task 4.1 first).

## Phase 4: Config, Docs, Metadata

- [x] 4.1 `config/settings.yaml`: add `inbox_folder_id: 6` and
      `sent_folder_id: 5` with doc comments matching the file's existing
      style.
- [x] 4.2 `README.md` "Configuration" section: document the two new keys;
      add a closing note that every settings.yaml key is now live.
- [x] 4.3 `pyproject.toml`: update `[project].description` to mention
      calendar, tasks, and mail tool families (outlook-tasks-todo
      verify-report SUGGESTION).
- [x] 4.4 Fix stale comment in `tests/test_mail_tools.py` calling
      `calendar_folder_id`/`tasks_folder_id` "dead" (no longer accurate).

## Phase 5: Full Suite

- [x] 5.1 Run full suite: `.venv/bin/python3.12 -m pytest -q` -> 165 + 9 new
      = 174 passed, zero regressions.

Note: no package rebuild in this change — a combined rebuild happens later
after the next change, per the orchestrator's instructions.
