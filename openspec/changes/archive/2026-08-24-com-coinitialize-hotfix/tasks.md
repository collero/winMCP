# Tasks: CoInitialize Hotfix for Real Outlook Adapters

## Phase 0: Baseline

- [x] 0.1 Confirm baseline: `.venv/bin/python3.12 -m pytest -q` → 152 passed

## Phase 1: Calendar Adapter (Strict TDD)

- [x] 1.1 RED `tests/test_outlook_adapter.py`: add `_install_fake_pythoncom` helper; add
      `test_search_calls_coinitialize_before_dispatch` and
      `test_get_event_calls_coinitialize_before_dispatch` (order assertions via a
      `mocker.Mock()` manager with `attach_mock`); add
      `test_pythoncom_not_imported_at_module_level`. Confirm all 3 fail against current code.
- [x] 1.2 GREEN `tools/outlook_adapter.py`: in `_dispatch_outlook()`, lazily import
      `pythoncom` alongside `win32com.client` and call `pythoncom.CoInitialize()` before
      `Dispatch(...)`. Confirm the 3 new tests pass and no existing test in the file regresses.

## Phase 2: Task Adapter (Strict TDD)

- [x] 2.1 RED `tests/test_task_adapter.py`: mirror 1.1 (`_install_fake_pythoncom`,
      `test_search_calls_coinitialize_before_dispatch`,
      `test_get_task_calls_coinitialize_before_dispatch`,
      `test_pythoncom_not_imported_at_module_level`). Confirm RED.
- [x] 2.2 GREEN `tools/task_adapter.py`: same fix as 1.2, mirrored. Confirm GREEN, no regressions.

## Phase 3: Mail Adapter (Strict TDD)

- [x] 3.1 RED `tests/test_mail_adapter.py`: mirror 1.1 (`_install_fake_pythoncom`,
      `test_search_calls_coinitialize_before_dispatch`,
      `test_get_message_calls_coinitialize_before_dispatch`,
      `test_pythoncom_not_imported_at_module_level`). Confirm RED.
- [x] 3.2 GREEN `tools/mail_adapter.py`: same fix as 1.2, mirrored. Confirm GREEN, no regressions.

## Phase 4: Full Suite + Package Rebuild

- [x] 4.1 Run full suite: `.venv/bin/python3.12 -m pytest -q` → 152 + new tests, zero regressions
- [x] 4.2 Run `./make-deploy-package.sh` end-to-end; all gates pass
- [x] 4.3 Record new `dist/WinMCP-20260824.zip` sha256 in `apply-progress.md`
- [x] 4.4 Verify packaged zip: `unzip -l` shows adapter files; `unzip -p ... | grep -n CoInitialize`
      confirms all 3 adapters contain the fix inside the zip
