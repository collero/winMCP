# Tasks: Outlook Calendar MVP MCP Server

## Phase 1: Bootstrap (Infrastructure)

- [x] 1.1 Create `pyproject.toml`: `[project]` metadata; deps `fastmcp`; `pywin32; sys_platform == 'win32'`; dev deps `pytest`, `pytest-mock`; `[tool.pytest.ini_options]` `testpaths=["tests"]`
- [x] 1.2 Create `tests/` dir + `tests/conftest.py` stub
- [x] 1.3 Run `python3.12 -m pytest -q` — confirm empty suite collects with zero errors
- [x] 1.4 Create `config/settings.yaml`: default lookback window, folder id `9`, optional tz override

## Phase 2: Schemas & Errors (Foundation)

- [x] 2.1 RED `tests/test_schemas.py`: `EventSummary`/`EventDetail` construction, tz-aware `start`/`end`, `EventDetail` adds `body`
- [x] 2.2 GREEN `models/schemas.py`: `EventSummary`, `EventDetail`, `SearchRequest`, `GetEventRequest`, `GetNotesRequest` (Pydantic)
- [x] 2.3 RED `tests/test_errors.py`: `OutlookUnavailableError`, `EventNotFoundError`, `AmbiguousMatchError` exist, carry `code`
- [x] 2.4 GREEN `tools/errors.py`: implement the three typed exceptions

## Phase 3: CalendarPort + Fake Adapter (outlook-com-adapter: Adapter Interface)

- [x] 3.1 RED `tests/test_fake_adapter.py`: `search()` filters by range/subject substring (case-insensitive); `get_event()` returns/raises `EventNotFoundError`; configurable to raise `OutlookUnavailableError`
- [x] 3.2 GREEN `tools/outlook_adapter.py`: define `CalendarPort` Protocol (`search`, `get_event`)
- [x] 3.3 GREEN `tools/fake_adapter.py`: `FakeCalendarAdapter` implementing `CalendarPort`, seeded in-memory via constructor

## Phase 4: calendar_search (calendar-search spec)

- [x] 4.1 RED `tests/test_calendar_tools.py::test_search_valid_range_and_subject`
- [x] 4.2 RED `::test_search_rejects_no_filters` — all three omitted errors before adapter call
- [x] 4.3 RED `::test_search_empty_result_returns_empty_list`
- [x] 4.4 RED `::test_search_outlook_unavailable_returns_tool_error`
- [x] 4.5 GREEN `tools/calendar.py`: implement `calendar_search(request, adapter)` satisfying 4.1-4.4

## Phase 5: calendar_get_event (calendar-get-event spec)

- [x] 5.1 RED `::test_get_event_success`
- [x] 5.2 RED `::test_get_event_not_found_raises_tool_error`
- [x] 5.3 RED `::test_get_event_empty_body_returns_empty_string`
- [x] 5.4 GREEN `tools/calendar.py`: implement `calendar_get_event(request, adapter)`

## Phase 6: calendar_get_notes (calendar-get-notes spec)

- [x] 6.1 RED `::test_get_notes_expands_date_to_full_day_range_local_tz`
- [x] 6.2 RED `::test_get_notes_single_match_returns_subject_and_body`
- [x] 6.3 RED `::test_get_notes_zero_matches_raises_not_found`
- [x] 6.4 RED `::test_get_notes_multiple_matches_raises_ambiguous_lists_entry_ids_no_get_event_call`
- [x] 6.5 GREEN `tools/calendar.py`: implement `calendar_get_notes(request, adapter)` composing search + get_event

## Phase 7: Real Outlook Adapter (outlook-com-adapter: Lazy Import, COM Access, Dispatch failure)

- [x] 7.1 RED `tests/test_outlook_adapter.py::test_win32com_not_imported_at_module_level` (assert absent from `sys.modules` after import)
- [x] 7.2 RED `::test_search_builds_dasl_restrict_and_converts_tz` — mock `Dispatch` via pytest-mock; assert DASL `Restrict()` string, `IncludeRecurrences`+`Sort` pairing, naive→aware tz conversion
- [x] 7.3 RED `::test_get_event_uses_get_item_from_id` — assert `GetItemFromID(entryId)`, not a re-`Restrict` scan
- [x] 7.4 RED `::test_dispatch_failure_raises_outlook_unavailable_error`
- [x] 7.5 GREEN `tools/outlook_adapter.py`: `OutlookCalendarAdapter` — lazy `win32com.client` import inside methods, `GetDefaultFolder(9)`, error mapping

## Phase 8: Server Wiring (mcp-server-bootstrap spec)

- [x] 8.1 RED `tests/test_server.py::test_import_succeeds_without_win32com`
- [x] 8.2 RED `::test_all_three_tools_registered` — fake adapter injected, `list_tools()` includes all 3
- [x] 8.3 RED `::test_stdio_only_no_network_listener`
- [x] 8.4 RED `::test_adapter_selection_deferred_when_win32com_unavailable` — clear runtime error, not import-time crash
- [x] 8.5 GREEN `server.py`: FastMCP app, register 3 tools, defer adapter selection to first use, stdio transport entrypoint

## Phase 9: Full Suite & Docs

- [x] 9.1 Run `python3.12 -m pytest -q` — full suite green; fix any regressions
- [x] 9.2 Write `README.md`: Windows install (`uv sync`/`pip install .`) under Windows Python 3.12, `claude_desktop_config.json` `mcpServers` entry example, note WSL2 dev-only fake adapter, manual Windows smoke-test steps
