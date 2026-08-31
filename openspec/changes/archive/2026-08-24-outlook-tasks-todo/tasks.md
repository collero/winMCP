# Tasks: Outlook Tasks / Microsoft To Do (Read-Only)

## Phase 1: Schemas & Errors (Foundation)

- [x] 1.1 RED `tests/test_schemas.py`: `TaskSummary`/`TaskDetail` construction (aliases `entryId`/`dueDate`/`isComplete`), `TaskStatus` enum values, `TaskDetail` adds `body`
- [x] 1.2 GREEN `models/schemas.py`: add `TaskStatus` (str-enum), `TaskSummary`, `TaskDetail(TaskSummary)`, `TaskSearchRequest`, `GetTaskRequest`
- [x] 1.3 RED `tests/test_errors.py`: `TaskNotFoundError(CalendarToolError)` exists, carries `code = "task_not_found"`
- [x] 1.4 GREEN `tools/errors.py`: add `TaskNotFoundError` (reuse `OutlookUnavailableError` as-is)

## Phase 2: TaskPort + Fake Adapter (outlook-tasks-adapter: Adapter Interface)

- [x] 2.1 RED `tests/test_fake_task_adapter.py`: `search()` all-filters-optional (no-filter → whole set; subject; status; due-date × `include_no_due_date` per spec); `get_task()` returns/raises `TaskNotFoundError`; configurable `OutlookUnavailableError`
- [x] 2.2 GREEN `tools/task_adapter.py`: define `TaskPort` Protocol (`search(date_from, date_to, subject, status, include_no_due_date=True)`, `get_task(entry_id)`)
- [x] 2.3 GREEN `tools/fake_task_adapter.py`: `FakeTaskAdapter` implementing `TaskPort`, in-memory seed via constructor, Python filter sequence (subject → status → due-date pass)

## Phase 3: task_search (task-search spec)

- [x] 3.1 RED `tests/test_tasks_tools.py::test_search_valid_range_and_subject`
- [x] 3.2 RED `::test_search_status_only_filter`
- [x] 3.3 RED `::test_search_all_filters_omitted_returns_whole_folder` — no-filter call not rejected (unlike `calendar_search`)
- [x] 3.4 RED `::test_search_default_include_no_due_date_passes_null_due_date_through_range`
- [x] 3.5 RED `::test_search_include_no_due_date_false_excludes_null_due_date`
- [x] 3.6 RED `::test_search_subject_only_unaffected_by_due_date_bounds`
- [x] 3.7 RED `::test_search_empty_result_returns_empty_list`
- [x] 3.8 RED `::test_search_outlook_unavailable_returns_tool_error`
- [x] 3.9 GREEN `tools/tasks.py`: implement `task_search(request, adapter)` satisfying 3.1-3.8

## Phase 4: task_get_task (task-get-detail spec)

- [x] 4.1 RED `tests/test_tasks_tools.py::test_get_task_success`
- [x] 4.2 RED `::test_get_task_not_found_raises_tool_error`
- [x] 4.3 RED `::test_get_task_empty_body_returns_empty_string`
- [x] 4.4 RED `::test_get_task_completed_and_in_progress_report_consistent_fields` — `isComplete`/`status` passed through unchanged, no re-derivation
- [x] 4.5 GREEN `tools/tasks.py`: implement `task_get_task(request, adapter)` satisfying 4.1-4.4

## Phase 5: Real Outlook Task Adapter (outlook-tasks-adapter: Lazy Import, COM Access, Status Mapping)

- [x] 5.1 RED `tests/test_task_adapter.py::test_win32com_not_imported_at_module_level`, mirroring `tests/test_outlook_adapter.py::_install_fake_win32com`
- [x] 5.2 RED `::test_search_uses_get_default_folder_13_and_filters_in_python_no_restrict` — mocked `win32com.client`, 4 mixed-due-date items (one `None`); assert `GetDefaultFolder(13)` used, no due-date `Restrict()`
- [x] 5.3 RED `::test_get_task_uses_get_item_from_id` — assert `GetItemFromID(entryId)`, not a re-scan
- [x] 5.4 RED `::test_dispatch_failure_raises_outlook_unavailable_error`
- [x] 5.5 RED `::test_status_1_complete_false_maps_in_progress_no_override`
- [x] 5.6 RED `::test_status_3_complete_true_overrides_to_completed`
- [x] 5.7 GREEN `tools/task_adapter.py`: `OutlookTaskAdapter` — lazy `win32com.client` import, `GetDefaultFolder(13)`, Python-side filtering, `Status`→`TaskStatus` map (`0/1/2/3/4`→`not_started/in_progress/completed/waiting/deferred`), `Complete=True` override, errors → `OutlookUnavailableError`/`TaskNotFoundError`

## Phase 6: Server Wiring (no `_map_error` changes needed)

- [x] 6.1 RED `tests/test_server.py::test_import_succeeds_without_win32com` (extend for task adapter path)
- [x] 6.2 RED `::test_task_tools_registered` — fake task adapter via `create_server(adapter=..., task_adapter=...)`; `list_tools()` includes all 5 tools
- [x] 6.3 RED `::test_task_adapter_selection_deferred_when_win32com_unavailable` — clear runtime error, not import-time crash
- [x] 6.4 GREEN `server.py`: add `task_adapter` param, `_resolve_real_task_adapter()` lazy resolver, register `task_search`/`task_get_task`; `_map_error` unchanged (already catches `CalendarToolError`)

## Phase 7: Config & Packaging

- [x] 7.1 Update `config/settings.yaml`: add `tasks_folder_id: 13`, comment matching `calendar_folder_id` style
- [x] 7.2 Update `make-deploy-package.sh`: exclusion regex → `grep -vxE 'tools/(fake_adapter|fake_task_adapter)\.py'` so both fakes stay out of the shipped package

## Phase 8: Full Suite & Docs

- [x] 8.1 Run `.venv/bin/python3.12 -m pytest -q` — full suite green; fix regressions
- [x] 8.2 Update `README.md`: add `task_search`/`task_get_task` to the tool list intro; move "Tasks / Microsoft To Do" out of the future-work list (~L238-242) into shipped tools
- [x] 8.3 Run `./make-deploy-package.sh` — succeeds; package excludes both `tools/fake_adapter.py` and `tools/fake_task_adapter.py`
