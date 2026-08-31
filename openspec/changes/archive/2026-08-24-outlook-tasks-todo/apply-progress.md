# Apply Progress: outlook-tasks-todo

## Batch 1 of 4 — Phases 1 and 2 (COMPLETE)

Mode: **Strict TDD** (test runner: `.venv/bin/python3.12 -m pytest -q`).

### Completed Tasks

- [x] 1.1 RED `tests/test_schemas.py`: `TaskStatus` enum values, `TaskSummary`/`TaskDetail` construction with aliases (`entryId`/`dueDate`/`isComplete`), `TaskDetail` adds `body`
- [x] 1.2 GREEN `models/schemas.py`: added `TaskStatus` (str-enum), `TaskSummary`, `TaskDetail(TaskSummary)`, `TaskSearchRequest`, `GetTaskRequest`
- [x] 1.3 RED `tests/test_errors.py`: `TaskNotFoundError(CalendarToolError)` exists, carries `code = "task_not_found"`
- [x] 1.4 GREEN `tools/errors.py`: added `TaskNotFoundError` (reused `OutlookUnavailableError` as-is, no changes)
- [x] 2.1 RED `tests/test_fake_task_adapter.py`: `search()` all-filters-optional (no-filter → whole set; subject; status; due-date × `include_no_due_date`); `get_task()` returns/raises `TaskNotFoundError`; configurable `OutlookUnavailableError`
- [x] 2.2 GREEN `tools/task_adapter.py`: defined `TaskPort` Protocol (`search(date_from, date_to, subject, status, include_no_due_date=True)`, `get_task(entry_id)`)
- [x] 2.3 GREEN `tools/fake_task_adapter.py`: `FakeTaskAdapter` implementing `TaskPort`, in-memory seed via constructor, Python filter sequence (subject → status → due-date pass)

### Files Created / Modified

| File | Action | What Was Done |
|------|--------|----------------|
| `models/schemas.py` | Modified (additive) | Added `TaskStatus`, `TaskSummary`, `TaskDetail`, `TaskSearchRequest`, `GetTaskRequest`. No changes to existing `EventSummary`/`EventDetail`/etc. |
| `tools/errors.py` | Modified (additive) | Added `TaskNotFoundError(CalendarToolError)`, `code = "task_not_found"`. No changes to existing errors. |
| `tools/task_adapter.py` | Created | `TaskPort` Protocol — mirrors `tools/outlook_adapter.py::CalendarPort` but with all `search()` filters optional. |
| `tools/fake_task_adapter.py` | Created | `FakeTaskAdapter` — mirrors `tools/fake_adapter.py::FakeCalendarAdapter`; implements the subject → status → due-date filter sequence from design.md. |
| `tests/test_schemas.py` | Modified (additive) | Added 5 tests for `TaskStatus`/`TaskSummary`/`TaskDetail`. |
| `tests/test_errors.py` | Modified (additive) | Added 3 tests for `TaskNotFoundError`. |
| `tests/test_fake_task_adapter.py` | Created | 11 tests covering all-filters-optional search, subject/status/due-date filtering, `include_no_due_date` default and override, `get_task` hit/miss, `OutlookUnavailableError` configurability for both methods. |

### TDD Cycle Evidence

| Task | Test File | Layer | Safety Net | RED | GREEN | TRIANGULATE | REFACTOR |
|------|-----------|-------|------------|-----|-------|-------------|----------|
| 1.1/1.2 | `tests/test_schemas.py` | Unit | ✅ 9/9 (pre-existing schema tests) | ✅ Written — `ImportError: cannot import name 'TaskDetail'` | ✅ 10/10 passed | ✅ 5 cases (enum values, alias construction, snake_case defaults, body present, body empty) | ➖ None needed — matches `EventSummary`/`EventDetail` pattern exactly |
| 1.3/1.4 | `tests/test_errors.py` | Unit | ✅ 9/9 (pre-existing error tests, checked jointly with schemas) | ✅ Written — `ImportError: cannot import name 'TaskNotFoundError'` | ✅ 7/7 passed | ✅ 3 cases (carries code, is-a CalendarToolError, raisable/catchable) | ➖ None needed |
| 2.1/2.2/2.3 | `tests/test_fake_task_adapter.py` | Unit | ✅ N/A (new files) | ✅ Written — `ModuleNotFoundError: No module named 'tools.fake_task_adapter'` | ✅ 11/11 passed | ✅ 11 cases covering no-filter whole-set, subject match, status match, default `include_no_due_date=True`, `include_no_due_date=False`, narrow-range exclusion, subject-only-ignores-due-date-bounds, get_task hit/miss, unavailable for both methods | ➖ None needed — filter helper extracted as `_passes_due_date_filter` static method for clarity, tests re-run green after extraction |

### Test Summary

- **Total tests written this batch**: 19 (5 schema + 3 error + 11 fake adapter)
- **Total tests passing (full suite)**: 64/64 (baseline was 45/45 — zero regressions)
- **Layers used**: Unit (19)
- **Approval tests** (refactoring): None — no refactoring tasks, all additive
- **Pure functions created**: `FakeTaskAdapter._passes_due_date_filter` (static, pure)

### Deviations from Design

None — implementation matches design.md exactly:
- `TaskStatus` enum values, `TaskSummary`/`TaskDetail` field names and aliases match the "Interfaces / Contracts" section verbatim.
- `TaskPort.search()` signature matches verbatim, including `include_no_due_date: bool = True` default.
- Filter sequence (subject → status → due-date pass, with the exact OR-null-due-date semantics) matches the "task_search filter sequence" note verbatim.
- `TaskNotFoundError(CalendarToolError)` reuses the existing taxonomy per the "Error taxonomy reuse" decision — no new base class, no changes to `CalendarToolError`/`OutlookUnavailableError`/`EventNotFoundError`/`AmbiguousMatchError`.

### Issues Found

None.

### Constraints Honored

- `win32com` was not imported anywhere in this batch's files (Phase 5 is out of scope for this batch).
- `models/schemas.py` and `tools/errors.py` changes are purely additive — all pre-existing tests in `tests/test_schemas.py` and `tests/test_errors.py` still pass unchanged.
- No calendar file *behavior* was touched (only additive imports/tests in shared files).
- No `pip install pywin32` was run.

### Status

7/8 subtasks in Phases 1-2 batch scope complete — actually all 7 assigned tasks (1.1-1.4, 2.1-2.3) are complete. Full suite green (64/64). Ready for Batch 2 (Phases 3-4).

## Batch 2 of 4 — Phases 3 and 4 (COMPLETE)

Mode: **Strict TDD** (test runner: `.venv/bin/python3.12 -m pytest -q`).

### Completed Tasks

- [x] 3.1 RED `tests/test_tasks_tools.py::test_search_valid_range_and_subject`
- [x] 3.2 RED `::test_search_status_only_filter`
- [x] 3.3 RED `::test_search_all_filters_omitted_returns_whole_folder` — no-filter call not rejected (unlike `calendar_search`)
- [x] 3.4 RED `::test_search_default_include_no_due_date_passes_null_due_date_through_range`
- [x] 3.5 RED `::test_search_include_no_due_date_false_excludes_null_due_date`
- [x] 3.6 RED `::test_search_subject_only_unaffected_by_due_date_bounds`
- [x] 3.7 RED `::test_search_empty_result_returns_empty_list`
- [x] 3.8 RED `::test_search_outlook_unavailable_returns_tool_error`
- [x] 3.9 GREEN `tools/tasks.py`: implemented `task_search(request, adapter)` satisfying 3.1-3.8
- [x] 4.1 RED `tests/test_tasks_tools.py::test_get_task_success`
- [x] 4.2 RED `::test_get_task_not_found_raises_tool_error`
- [x] 4.3 RED `::test_get_task_empty_body_returns_empty_string`
- [x] 4.4 RED `::test_get_task_completed_and_in_progress_report_consistent_fields` — `isComplete`/`status` passed through unchanged, no re-derivation
- [x] 4.5 GREEN `tools/tasks.py`: implemented `task_get_task(request, adapter)` satisfying 4.1-4.4

### Files Created / Modified (Batch 2)

| File | Action | What Was Done |
|------|--------|----------------|
| `tools/tasks.py` | Created | `task_search(request, adapter)` and `task_get_task(request, adapter)` — thin pass-through to `TaskPort`, mirrors `tools/calendar.py::calendar_search`/`calendar_get_event`. No mandatory-filter rule (unlike `calendar_search`) and no lookback normalization, per design.md's "No-due-date search filtering" decision. |
| `tests/test_tasks_tools.py` | Created | 12 tests: 8 for `task_search` (valid range+subject, status-only, all-filters-omitted whole-folder, default/`include_no_due_date=False` due-date semantics, subject-only unaffected by due-date bounds, empty result, Outlook-unavailable) + 4 for `task_get_task` (success, not-found, empty body, completed/in-progress status-consistency). |

### TDD Cycle Evidence (Batch 2)

| Task | Test File | Layer | Safety Net | RED | GREEN | TRIANGULATE | REFACTOR |
|------|-----------|-------|------------|-----|-------|-------------|----------|
| 3.1-3.8 | `tests/test_tasks_tools.py` | Unit | ✅ 64/64 (full suite baseline before batch) | ✅ Written — `ModuleNotFoundError: No module named 'tools.tasks'` | ✅ 12/12 passed | ✅ 8 cases covering range+subject, status-only, all-omitted whole-folder, default `include_no_due_date=True` passes null through range, `include_no_due_date=False` excludes null, subject-only ignores due-date bounds, empty result, `OutlookUnavailableError` propagation | ➖ None needed — matches `tools/calendar.py::calendar_search` thin-pass-through pattern exactly |
| 3.9 | `tests/test_tasks_tools.py` | Unit | (same run) | (see above) | ✅ 12/12 passed | (see above) | ➖ None needed |
| 4.1-4.4 | `tests/test_tasks_tools.py` | Unit | ✅ 64/64 (joint run with Phase 3, same file) | ✅ Written — same `ModuleNotFoundError` (single new module covers both functions) | ✅ 12/12 passed | ✅ 4 cases covering success, not-found (`TaskNotFoundError`), empty-body, completed/in-progress field-consistency (no re-derivation) | ➖ None needed |
| 4.5 | `tests/test_tasks_tools.py` | Unit | (same run) | (see above) | ✅ 12/12 passed | (see above) | ➖ None needed |

### Test Summary (Batch 2)

- **Total tests written this batch**: 12 (8 `task_search` + 4 `task_get_task`)
- **Total tests passing (full suite)**: 76/76 (baseline was 64/64 — zero regressions)
- **Layers used**: Unit (12)
- **Approval tests** (refactoring): None — no refactoring tasks, all additive
- **Pure functions created**: None new this batch — `task_search`/`task_get_task` are thin adapter pass-throughs (no branching logic to extract); all filter logic already lives in `TaskPort` implementations per design.md

### Deviations from Design (Batch 2)

None — implementation matches design.md exactly:
- `task_search` forwards `request.date_from`/`date_to`/`subject`/`status`/`include_no_due_date` straight to `adapter.search()` with no mandatory-filter validation (unlike `calendar_search`'s `ValueError` on all-omitted) and no lookback-window normalization — matches the "No-due-date search filtering" decision (Tasks folders are bounded, full scans are safe).
- `task_get_task` forwards `request.entry_id` straight to `adapter.get_task()`, no re-derivation of `status`/`is_complete` — matches task-get-detail spec's "Status/Complete Consistency" requirement (adapter is the single source of truth; tool layer passes both fields through unchanged).
- Both functions let adapter errors (`OutlookUnavailableError`, `TaskNotFoundError`) propagate unmapped, same as `tools/calendar.py` — `server.py`'s `_map_error` (Phase 6) handles translation to MCP tool errors.

### Issues Found (Batch 2)

None.

### Constraints Honored (Batch 2)

- `win32com` was not imported anywhere in this batch's files (Phase 5 is out of scope for this batch).
- No existing file was modified this batch — `tools/tasks.py` and `tests/test_tasks_tools.py` are both new files; the pre-existing 64 tests all still pass unchanged.
- No calendar file behavior was touched.
- No `pip install pywin32` was run.

## Batch 3 of 4 — Phase 5 (COMPLETE)

Mode: **Strict TDD** (test runner: `.venv/bin/python3.12 -m pytest -q`).

### Completed Tasks

- [x] 5.1 RED `tests/test_task_adapter.py::test_win32com_not_imported_at_module_level`, mirroring `tests/test_outlook_adapter.py::_install_fake_win32com`
- [x] 5.2 RED `::test_search_uses_get_default_folder_13_and_filters_in_python_no_restrict` — mocked `win32com.client`, 4 mixed-due-date items (one `None`); asserts `GetDefaultFolder(13)` used, no due-date `Restrict()`
- [x] 5.3 RED `::test_get_task_uses_get_item_from_id` — asserts `GetItemFromID(entryId)`, not a re-scan (`GetDefaultFolder` not called)
- [x] 5.4 RED `::test_dispatch_failure_raises_outlook_unavailable_error` — covers both `search()` and `get_task()`
- [x] 5.5 RED `::test_status_1_complete_false_maps_in_progress_no_override`
- [x] 5.6 RED `::test_status_3_complete_true_overrides_to_completed`
- [x] 5.7 GREEN `tools/task_adapter.py`: implemented `OutlookTaskAdapter` satisfying 5.1-5.6

Also added (triangulation, not separately numbered but part of the same RED/GREEN cycle): `test_get_task_unknown_entry_id_raises_not_found` — mirrors `test_outlook_adapter.py::test_get_event_unknown_entry_id_raises_not_found`, asserting `GetItemFromID` failure maps to `TaskNotFoundError`.

### Files Created / Modified (Batch 3)

| File | Action | What Was Done |
|------|--------|----------------|
| `tools/task_adapter.py` | Modified (additive) | Added `OutlookTaskAdapter` class, plus module-level helpers `_to_aware`, `_map_status`, `_passes_due_date_filter`, and `_STATUS_MAP`/`_DEFAULT_TASKS_FOLDER_ID` constants. `TaskPort` Protocol (from Batch 1) untouched. |
| `tests/test_task_adapter.py` | Created | 7 tests: module-level-import guard, search (folder 13, no `Restrict()`, Python-side due-date/`include_no_due_date` filtering over 4 mixed items), `get_task` uses `GetItemFromID` not a re-scan, dispatch-failure → `OutlookUnavailableError` (both methods), unknown-entryId → `TaskNotFoundError`, and the two COM status-mapping scenarios (`Status=1`/`Complete=False` no override; `Status=3`/`Complete=True` override to `completed`). |

### TDD Cycle Evidence (Batch 3)

| Task | Test File | Layer | Safety Net | RED | GREEN | TRIANGULATE | REFACTOR |
|------|-----------|-------|------------|-----|-------|-------------|----------|
| 5.1 | `tests/test_task_adapter.py::test_win32com_not_imported_at_module_level` | Unit | ✅ 76/76 (full suite baseline before batch) | ✅ Passed immediately — `tools/task_adapter.py` already had zero module-level `win32com` import from Batch 1 (Protocol-only file); confirms the invariant holds before adding the real adapter | ✅ Stayed green after 5.7 | ➖ N/A (guard test, not new behavior) | ➖ None needed |
| 5.2-5.4 | `tests/test_task_adapter.py` | Unit | ✅ 76/76 | ✅ Written — `ImportError: cannot import name 'OutlookTaskAdapter' from 'tools.task_adapter'` (6 of 7 new tests failed on this import before 5.7; the 7th, 5.1, passed as noted above) | ✅ 7/7 passed after 5.7 | ✅ 4 mixed-due-date items (in-range, out-of-range-future, no-due-date, out-of-range-past) confirm Python-side filter parity with `FakeTaskAdapter`; explicit `items.Restrict.assert_not_called()` proves the negative (no DASL due-date filtering) | ➖ None needed — matches `tools/outlook_adapter.py::OutlookCalendarAdapter` dispatch/error-mapping pattern exactly |
| 5.5-5.6 | `tests/test_task_adapter.py::test_status_1_complete_false_maps_in_progress_no_override`, `::test_status_3_complete_true_overrides_to_completed` | Unit | (same run) | (see above, same `ImportError`) | ✅ 7/7 passed | ✅ 2 cases: raw `Status` passed straight through when `Complete=False`; `Complete=True` forces `status=completed` even though raw `Status=3` (`waiting`) would otherwise map differently — proves the override branch, not just the direct-mapping branch | ➖ None needed |
| 5.7 | `tools/task_adapter.py` | — | (same run) | (see above) | ✅ 7/7 passed | (see above) | ➖ None needed — `_map_status`/`_passes_due_date_filter`/`_to_aware` extracted as pure module-level functions from the start (mirroring `FakeTaskAdapter`'s and `OutlookCalendarAdapter`'s existing extraction pattern), no separate refactor pass required |

### Test Summary (Batch 3)

- **Total tests written this batch**: 7 (all in `tests/test_task_adapter.py`)
- **Total tests passing (full suite)**: 83/83 (baseline was 76/76 — zero regressions)
- **Layers used**: Unit (7)
- **Approval tests** (refactoring): None — no refactoring tasks, all additive
- **Pure functions created**: `_to_aware` (mirrors `tools/outlook_adapter.py::_to_aware`), `_map_status`, `_passes_due_date_filter` (mirrors `FakeTaskAdapter._passes_due_date_filter`) — all module-level, pure, in `tools/task_adapter.py`

### Deviations from Design (Batch 3)

None — implementation matches design.md exactly:
- `OutlookTaskAdapter` connects via `win32com.client.Dispatch("Outlook.Application")` → `GetNamespace("MAPI")` → `GetDefaultFolder(13)`, lazy import inside `_dispatch_outlook` only (never at module scope) — verified by `test_win32com_not_imported_at_module_level` and by direct interpreter check (`import tools.task_adapter` leaves `win32com` out of `sys.modules`).
- `search()` fetches `folder.Items` with **no due-date `Restrict()` call** — subject, status, and due-date/`include_no_due_date` filtering all happen in Python via `_passes_due_date_filter`, identical semantics to `FakeTaskAdapter._passes_due_date_filter` (subject → status → due-date order).
- `Status` → `TaskStatus` map matches the spec's COM `OlTaskStatus` values verbatim (`0/1/2/3/4` → `not_started/in_progress/completed/waiting/deferred`); `Complete=True` unconditionally overrides to `completed` regardless of raw `Status`, per the "Complete is the authoritative done flag" decision — both mapping and override are applied identically in `search()` and `get_task()` via the shared `_map_status` helper.
- Dispatch/namespace/lookup failures map to `OutlookUnavailableError`/`TaskNotFoundError` (never a bare COM exception), mirroring `OutlookCalendarAdapter`'s error-mapping structure exactly.

### Issues Found (Batch 3)

None. One implementation note (not a deviation): real Outlook COM returns a sentinel "no date" value for `TaskItem.DueDate` when unset (not Python `None`) on an actual Windows/Outlook host. Design.md and the spec's mocked-test scenarios both model "no due date" as `None` directly (matching `FakeTaskAdapter`'s in-memory model), so `OutlookTaskAdapter` checks `item.DueDate is not None` — this is correct against the spec and the fake adapter's contract, but if real-host smoke testing (design.md's "E2E — Manual only, on Windows host" row) surfaces a non-`None` sentinel instead, a follow-up fix translating that sentinel to `None` would be needed then. Flagging for awareness, not blocking — out of scope for this WSL2-only batch.

### Constraints Honored (Batch 3)

- `win32com` was not imported anywhere at module load time — confirmed both by the RED/GREEN test suite and a direct interpreter check.
- No existing file's *behavior* was changed — `tools/task_adapter.py`'s Batch 1 `TaskPort` Protocol is untouched; only new class/functions were appended. `tests/test_task_adapter.py` is a new file.
- No calendar file (`tools/outlook_adapter.py`, `tests/test_outlook_adapter.py`) was modified — mirrored, not touched.
- No `pip install pywin32` was run; `pip list | grep -i win32` confirms pywin32 remains absent from this environment.

### Remaining Tasks (for Batch 4: Phases 6-8)

- [ ] 6.1–6.4 Server wiring (`server.py`: `task_adapter` param, `_resolve_real_task_adapter()`, register `task_search`/`task_get_task`)
- [ ] 7.1–7.2 Config & packaging (`config/settings.yaml` `tasks_folder_id: 13`, `make-deploy-package.sh` exclusion regex)
- [ ] 8.1–8.3 Full suite & docs (final full-suite run, `README.md` update, `./make-deploy-package.sh` run)

### Status (Cumulative)

26/26 subtasks across Phases 1-5 complete (7 from Batch 1 + 12 from Batch 2 + 7 from Batch 3). Full suite green (83/83). Ready for Batch 4 (Phases 6-8).

## Batch 4 of 4 — Phases 6, 7, 8 (COMPLETE, FINAL) + orchestrator-directed amendment

Mode: **Strict TDD** (test runner: `.venv/bin/python3.12 -m pytest -q`).

### Orchestrator-directed amendment: DueDate sentinel normalization (Phase 5 addendum)

Before starting Phase 6, the orchestrator flagged Batch 3's "Issues Found" note (real Outlook COM returns a sentinel datetime, year 4501/`olNoDate`, for an unset `TaskItem.DueDate`, not Python `None`) as needing a fix, not just a flag — on a real host this would break `include_no_due_date` filtering and surface a bogus year-4501 `due_date`. Implemented as a small additive change to `OutlookTaskAdapter`, under Strict TDD:

- [x] AMEND.1 RED `tests/test_task_adapter.py::test_get_task_due_date_sentinel_year_4501_normalized_to_none` — mocked `win32com`, `DueDate=datetime(4501, 1, 1)` → `TaskDetail.due_date` must be `None`
- [x] AMEND.2 RED `::test_search_due_date_sentinel_treated_as_no_due_date_by_filters` — same sentinel via `search()`: included with `due_date=None` when `include_no_due_date=True`, excluded when `False` (proves it is treated as undated by filtering, not just blanked on output)
- [x] AMEND.3 GREEN `tools/task_adapter.py`: added `_normalize_due_date()` (treats any `DueDate` with `year >= 4500` as `None`) and `_SENTINEL_NO_DATE_YEAR = 4500` constant; called from both `search()` and `get_task()` before `_to_aware()`

Documented per the orchestrator's instruction:
- `openspec/changes/outlook-tasks-todo/specs/outlook-tasks-adapter/spec.md` — added a new "Due-Date Sentinel Normalization" requirement with 2 scenarios (get_task normalization; search-filter treatment), inserted before "Adapter Selection at Runtime".
- `design.md` — added a new row to the Architecture Decisions table: "Due-date sentinel normalization (orchestrator-approved amendment, Batch 4)", contrasting with Batch 3's original `item.DueDate is not None` trust-as-is approach.
- This apply-progress record (here) is the amendment's audit trail.

### Completed Tasks (Phase 6-8)

- [x] 6.1 RED `tests/test_server.py::test_import_succeeds_without_win32com` — extended with `assert "tools.task_adapter" in sys.modules` to cover the new task-adapter import path
- [x] 6.2 RED `::test_task_tools_registered` — `create_server(adapter=FakeCalendarAdapter(...), task_adapter=FakeTaskAdapter(...))`; `list_tools()` returns all 5 tool names
- [x] 6.3 RED `::test_task_adapter_selection_deferred_when_win32com_unavailable` — mirrors the calendar version; `task_search` call raises `ToolError`, not an import/construction crash, when `win32com` is unavailable
- [x] 6.4 GREEN `server.py`: added `task_adapter: TaskPort | None = None` param to `create_server()`, `_lazy_real_task_adapter`/`_resolve_real_task_adapter()` (mirrors the calendar lazy resolver), registered `task_search`/`task_get_task` tools; `_map_error` left unchanged (already catches the shared `CalendarToolError` base, which `TaskNotFoundError` extends)
- [x] (incidental, required by 6.2/6.4) updated `test_all_three_tools_registered`'s expected set from 3 to 5 tool names — the two new tools are always registered by `create_server()`, so the old exact-3 assertion would otherwise regress
- [x] (incidental TDD coverage) added `test_task_search_tool_returns_results_via_fake_task_adapter` — end-to-end `task_search` call via FastMCP's in-process `Client`, confirms request→adapter→response wiring, not just registration
- [x] 7.1 `config/settings.yaml`: added `tasks_folder_id: 13` with a comment matching `calendar_folder_id`'s style
- [x] 7.2 `make-deploy-package.sh`: exclusion regex changed from `grep -vx 'tools/fake_adapter.py'` to `grep -vxE 'tools/(fake_adapter|fake_task_adapter)\.py'`; updated the adjacent comment to mention both fakes
- [x] 8.1 Full suite run — green (see Test Summary below)
- [x] 8.2 `README.md` updated: intro tool list (3→5 tools, added `task_search`/`task_get_task` bullets), Claude Desktop discovery step (packaged install + manual/dev install), `Configuration` section (`tasks_folder_id` bullet), `Development` section (mentions `FakeTaskAdapter`/`test_task_adapter.py`/`test_tasks_tools.py`), `Manual smoke test` section (5-tool list check + new task_search/task_get_task step), `Known limitations` (Tasks folder scope + task read-only note), `Possible extensions` (removed the "Tasks / Microsoft To Do" bullet — it's shipped now, not a future extension — and reworded the section's lead-in from "calendar tools" to "calendar and task tools")
- [x] 8.3 `./make-deploy-package.sh` run to completion — succeeded, including the network-dependent wheel-download step (see Test Results below)

### Files Created / Modified (Batch 4)

| File | Action | What Was Done |
|------|--------|----------------|
| `tools/task_adapter.py` | Modified (additive) | Added `_SENTINEL_NO_DATE_YEAR`, `_normalize_due_date()`; wired into `search()` and `get_task()` in place of the bare `item.DueDate is not None` check. |
| `tests/test_task_adapter.py` | Modified (additive) | Added 2 tests for the sentinel-normalization amendment. |
| `server.py` | Modified (additive) | Added `TaskPort` import, `tools.tasks` import, `_lazy_real_task_adapter`/`_resolve_real_task_adapter()`, `task_adapter` param on `create_server()`, `_task_adapter()` closure, `_task_search`/`_task_get_task` tool registrations. Module docstring updated to mention 5 tools. No changes to `_map_error` or the 3 existing calendar tool registrations. |
| `tests/test_server.py` | Modified | Extended `test_import_succeeds_without_win32com`; updated `test_all_three_tools_registered`'s expected set to 5 tools; added `test_task_tools_registered`, `test_task_search_tool_returns_results_via_fake_task_adapter`, `test_task_adapter_selection_deferred_when_win32com_unavailable`. Added `FakeTaskAdapter` import. |
| `config/settings.yaml` | Modified (additive) | Added `tasks_folder_id: 13` + doc comment. |
| `make-deploy-package.sh` | Modified | Exclusion regex + adjacent comment updated to cover both fakes. |
| `README.md` | Modified | See task 8.2 above — 6 sections touched, all additive/rewording, no structural reorganization beyond removing the now-shipped Tasks bullet from "Possible extensions". |
| `openspec/changes/outlook-tasks-todo/specs/outlook-tasks-adapter/spec.md` | Modified (additive) | New "Due-Date Sentinel Normalization" requirement + 2 scenarios. |
| `openspec/changes/outlook-tasks-todo/design.md` | Modified (additive) | New Architecture Decisions row for the sentinel-normalization amendment. |
| `openspec/changes/outlook-tasks-todo/tasks.md` | Modified | All Phase 6/7/8 tasks marked `[x]`. |

### TDD Cycle Evidence (Batch 4)

| Task | Test File | Layer | Safety Net | RED | GREEN | TRIANGULATE | REFACTOR |
|------|-----------|-------|------------|-----|-------|-------------|----------|
| AMEND.1/AMEND.2 | `tests/test_task_adapter.py` | Unit | ✅ 83/83 (full suite baseline before batch) | ✅ Written — both new tests failed: `get_task` returned the raw year-4501 datetime instead of `None`; `search` excluded/mishandled the sentinel item under both `include_no_due_date` values | ✅ 85/85 (full suite) after AMEND.3 | ✅ 2 cases: sentinel via `get_task` (direct output check), sentinel via `search` under both `include_no_due_date=True` (included, `due_date=None`) and `=False` (excluded) — proves normalization happens before filtering, not just before serialization | ➖ None needed — single pure helper (`_normalize_due_date`), called identically from both methods, mirrors the existing `_to_aware`/`_map_status`/`_passes_due_date_filter` extraction pattern |
| 6.1-6.3 | `tests/test_server.py` | Integration (FastMCP in-process client) | ✅ 85/85 (after amendment) | ✅ Written — `test_task_tools_registered`/`test_task_search_tool_returns_results_via_fake_task_adapter` failed with `TypeError: create_server() got an unexpected keyword argument 'task_adapter'`; `test_all_three_tools_registered` (pre-existing, updated) failed on the widened 5-tool assertion; `test_import_succeeds_without_win32com`'s new assertion failed (`tools.task_adapter` not yet imported by `server.py`) | ✅ 88/88 (full suite) after 6.4 | ✅ 3 registration/wiring cases (both-fakes-injected registration, real-adapter-deferred error path, end-to-end fake-adapter call) plus the extended import-safety assertion | ➖ None needed — mirrors the existing calendar-adapter injection/lazy-resolution pattern exactly, just parameterized for the second port |
| 6.4 | `server.py` | — | (same run) | (see above) | ✅ 88/88 | (see above) | ➖ None needed |
| 7.1/7.2 | `config/settings.yaml`, `make-deploy-package.sh` | Config/build-script (no unit test — verified via manual `ls`/`grep` dry-run of the manifest regex, plus gate 1/6 of the deploy-package run) | ✅ 88/88 | ➖ N/A — declarative config + shell manifest line, not testable via pytest; verified instead by the deploy-package gate run itself (see Test Results below) | ✅ Confirmed: manifest includes `tools/task_adapter.py`/`tools/tasks.py`, excludes `tools/fake_adapter.py`/`tools/fake_task_adapter.py` (checked via `ls | grep -vxE` dry-run and the final zip's file listing) | ➖ N/A | ➖ None needed |
| 8.1-8.3 | Full suite + `README.md` + `./make-deploy-package.sh` | — | ✅ 88/88 | ➖ N/A (docs/gate-run tasks, no RED phase) | ✅ Full suite 88/88; `make-deploy-package.sh` completed with all 6 gates PASS, zip built and staged correctly | ➖ N/A | ➖ N/A |

### Test Summary (Batch 4)

- **Total tests written this batch**: 5 (2 sentinel-normalization + 3 server-wiring: `test_task_tools_registered`, `test_task_search_tool_returns_results_via_fake_task_adapter`, `test_task_adapter_selection_deferred_when_win32com_unavailable`); plus 1 pre-existing test extended in place (`test_import_succeeds_without_win32com`) and 1 pre-existing test's assertion widened (`test_all_three_tools_registered`, not counted as new)
- **Total tests passing (full suite)**: 88/88 (baseline at start of Batch 4 was 83/83 — zero regressions across the whole batch)
- **Layers used**: Unit (2, adapter sentinel normalization), Integration/FastMCP-in-process (3, server wiring)
- **Approval tests** (refactoring): None — no refactoring tasks, all additive
- **Pure functions created**: `_normalize_due_date` (module-level, pure, in `tools/task_adapter.py`)

### Deviations from Design (Batch 4)

One intentional deviation, orchestrator-approved and documented above and in `design.md`/`spec.md`: `OutlookTaskAdapter` no longer trusts `item.DueDate is not None` as-is (Batch 3's original approach, which matched design.md verbatim at the time) — it now normalizes the real-COM year-4501 sentinel to `None` first. This is additive/defensive, does not change `FakeTaskAdapter`'s contract (in-memory tasks never carry the sentinel), and does not change any Phase 1-4 file.

Everything else in Batch 4 matches design.md/tasks.md exactly:
- `server.py`'s `_resolve_real_task_adapter()` mirrors `_resolve_real_adapter()` exactly (same lazy-construct-and-cache pattern, same "import inside the function, not at module scope" discipline).
- `_map_error` was NOT touched, per design.md's explicit "no changes needed" call-out — confirmed by `TaskNotFoundError`/`OutlookUnavailableError` both extending the already-caught `CalendarToolError` base.
- `config/settings.yaml`'s `tasks_folder_id: 13` and `make-deploy-package.sh`'s widened exclusion regex match tasks.md 7.1/7.2 verbatim.

### Issues Found (Batch 4)

None blocking. One thing worth flagging for `sdd-verify`: `config/settings.yaml`'s `tasks_folder_id` (like the pre-existing `calendar_folder_id`) is documentation-only — no code currently reads either setting from `settings.yaml`; both adapters hardcode their own `_DEFAULT_*_FOLDER_ID` module constant instead (confirmed via `grep -rn "calendar_folder_id\|tasks_folder_id" **/*.py` → no matches). This is a pre-existing pattern from the calendar MVP, not a regression introduced this batch, and matches tasks.md 7.1's literal instruction ("add `tasks_folder_id: 13`, comment matching `calendar_folder_id` style") — but it means the setting is currently inert. Not fixed here (out of scope for this batch; would be a design change, not a mechanical task).

### Constraints Honored (Batch 4)

- `win32com` was not imported anywhere at module load time — `server.py`'s new `from tools.task_adapter import TaskPort` and `from tools.tasks import task_get_task, task_search` are both safe (neither module imports `win32com` at module scope); confirmed by gate 3 of `make-deploy-package.sh` (`PASS: gate 3: no module-level win32com import`) and by `test_import_succeeds_without_win32com`.
- No calendar file *behavior* was changed — `tools/outlook_adapter.py`, `tools/calendar.py`, `tools/fake_adapter.py` untouched; the 3 calendar tool registrations in `server.py` are byte-for-byte unchanged (only new code appended after them).
- No `pip install pywin32` was run on this WSL2 host.
- `make-deploy-package.sh`'s test-suite gate (gate 2) and win32com-safety gate (gate 3) stayed intact and both passed during the real run.

### Test Results — full suite and deploy-package gate

- **Full suite**: `.venv/bin/python3.12 -m pytest -q` → **88 passed** (0 failed, 0 skipped). Baseline at Batch 4 start: 83/83. Net delta: +5 tests, zero regressions.
- **`./make-deploy-package.sh`**: ran to full completion, **all gates PASS**:
  - gate 1 (manifest files exist): PASS — 13 manifest files + 5 launcher sources
  - gate 2 (full test suite): PASS — 88 passed
  - gate 3 (no module-level `win32com` import): PASS
  - gate 4 (launcher scripts pure ASCII): PASS
  - gate 4b (no unescaped parens in `.bat` echo lines): PASS
  - gate 5 (`install.ps1` parses cleanly): PASS (via cached portable pwsh)
  - gate 6 (wheels coverage, win312+win313): PASS — 79 wheel files staged, including `pywin32-312-cp312-cp312-win_amd64.whl`/`pywin32-312-cp313-cp313-win_amd64.whl` and `fastmcp_slim-3.4.5-py3-none-any.whl`
  - Network wheel-download step (the one step this environment could plausibly lack network for) **succeeded** — `uv pip compile` resolved 69 packages for cp312 (+ a cp313 pass), and `pip download` fetched all of them plus `pywin32`/`setuptools`/`wheel`.
  - Output: `dist/WinMCP-20260731.zip` (32,384,170 bytes, 102 files, sha256 `a4b8cb106e2567b1bc119836af75f98b4a24d60b1e3a0a6678afccb2c94c613f`). Verified via `unzip -l` that `tools/task_adapter.py`/`tools/tasks.py` are present and `tools/fake_adapter.py`/`tools/fake_task_adapter.py` are absent.

### Status (Cumulative, FINAL)

31/31 subtasks across Phases 1-8 complete (7 Batch 1 + 12 Batch 2 + 7 Batch 3 + 5 Batch 4 [6.1-6.4, 7.1-7.2, 8.1-8.3 collapse to the tasks.md numbering] + 1 orchestrator-approved amendment [3 sub-steps]). Full suite green (88/88). `./make-deploy-package.sh` completed successfully end-to-end, including the network-dependent step. Change is feature-complete and ready for `sdd-verify`.
