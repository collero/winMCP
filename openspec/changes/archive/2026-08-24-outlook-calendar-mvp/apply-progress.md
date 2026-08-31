# Apply Progress: Outlook Calendar MVP MCP Server

**Mode**: Strict TDD (red-green-refactor)
**Test runner**: `python3.12 -m pytest -q` (via project venv `.venv/`, source it or use `.venv/bin/python3.12`)
**Batch**: 3 of 3 (FINAL) — Phases 7-9. Change complete: 37/37 tasks done, 41/41 tests
passing. Batch 1 (Phases 1-3) and Batch 2 (Phases 4-6) records preserved below, unmodified.

## Completed Phases

### Phase 1: Bootstrap (Infrastructure) — done, no TDD (infra tasks)
- [x] 1.1 `pyproject.toml` created
- [x] 1.2 `tests/` + `tests/conftest.py` stub created
- [x] 1.3 `python3.12 -m pytest -q` run — exit code 5 ("no tests ran"), zero collection errors — confirms clean bootstrap
- [x] 1.4 `config/settings.yaml` created

### Phase 2: Schemas & Errors (Foundation) — done, Strict TDD
- [x] 2.1 RED `tests/test_schemas.py`
- [x] 2.2 GREEN `models/schemas.py`
- [x] 2.3 RED `tests/test_errors.py`
- [x] 2.4 GREEN `tools/errors.py`

### Phase 3: CalendarPort + Fake Adapter — done, Strict TDD
- [x] 3.1 RED `tests/test_fake_adapter.py`
- [x] 3.2 GREEN `tools/outlook_adapter.py` (`CalendarPort` Protocol)
- [x] 3.3 GREEN `tools/fake_adapter.py` (`FakeCalendarAdapter`)

### Phase 4: calendar_search — done, Strict TDD
- [x] 4.1 RED `tests/test_calendar_tools.py::test_search_valid_range_and_subject`
- [x] 4.2 RED `::test_search_rejects_no_filters`
- [x] 4.3 RED `::test_search_empty_result_returns_empty_list`
- [x] 4.4 RED `::test_search_outlook_unavailable_returns_tool_error`
- [x] 4.5 GREEN `tools/calendar.py::calendar_search`

### Phase 5: calendar_get_event — done, Strict TDD
- [x] 5.1 RED `::test_get_event_success`
- [x] 5.2 RED `::test_get_event_not_found_raises_tool_error`
- [x] 5.3 RED `::test_get_event_empty_body_returns_empty_string`
- [x] 5.4 GREEN `tools/calendar.py::calendar_get_event`

### Phase 6: calendar_get_notes — done, Strict TDD
- [x] 6.1 RED `::test_get_notes_expands_date_to_full_day_range_local_tz`
- [x] 6.2 RED `::test_get_notes_single_match_returns_subject_and_body`
- [x] 6.3 RED `::test_get_notes_zero_matches_raises_not_found`
- [x] 6.4 RED `::test_get_notes_multiple_matches_raises_ambiguous_lists_entry_ids_no_get_event_call`
- [x] 6.5 GREEN `tools/calendar.py::calendar_get_notes`

### Phase 7: Real Outlook Adapter — done, Strict TDD
- [x] 7.1 RED `tests/test_outlook_adapter.py::test_win32com_not_imported_at_module_level`
- [x] 7.2 RED `::test_search_builds_dasl_restrict_and_converts_tz`
- [x] 7.3 RED `::test_get_event_uses_get_item_from_id`
- [x] 7.4 RED `::test_dispatch_failure_raises_outlook_unavailable_error`
- [x] 7.5 GREEN `tools/outlook_adapter.py::OutlookCalendarAdapter`

### Phase 8: Server Wiring — done, Strict TDD
- [x] 8.1 RED `tests/test_server.py::test_import_succeeds_without_win32com`
- [x] 8.2 RED `::test_all_three_tools_registered`
- [x] 8.3 RED `::test_stdio_only_no_network_listener`
- [x] 8.4 RED `::test_adapter_selection_deferred_when_win32com_unavailable`
- [x] 8.5 GREEN `server.py` (FastMCP app, 3 tools registered, stdio entrypoint)

### Phase 9: Full Suite & Docs — done
- [x] 9.1 `.venv/bin/python3.12 -m pytest -q` — 41/41 passing, zero regressions
- [x] 9.2 `README.md` written (Windows install, Claude Desktop config, WSL2 dev notes, manual smoke test)

## TDD Cycle Evidence (Batch 1 — Phases 1-3)

| Task | Test File | Layer | Safety Net | RED | GREEN | TRIANGULATE | REFACTOR |
|------|-----------|-------|------------|-----|-------|-------------|----------|
| 2.1/2.2 | `tests/test_schemas.py` | Unit | N/A (new) | Yes — `ModuleNotFoundError: models.schemas` | Yes — 5/5 passed | Yes — 5 cases (tz-aware ok, naive start rejected, naive end rejected, body added, empty body allowed) | None needed — model already minimal |
| 2.3/2.4 | `tests/test_errors.py` | Unit | N/A (new) | Yes — `ModuleNotFoundError: tools.errors` | Yes — 9/9 passed (incl. prior schema tests) | Yes — 4 cases (3 error types + raisable/catchable) | None needed |
| 3.1/3.2/3.3 | `tests/test_fake_adapter.py` | Unit | N/A (new) | Yes — `ModuleNotFoundError: tools.fake_adapter` | Yes — 15/15 passed (full suite) | Yes — 6 cases (range+subject match, out-of-range exclusion, get_event success, not-found, search-unavailable, get_event-unavailable) | None needed — logic already simple |

### Test Summary (Batch 1)
- **Total tests written**: 15 (5 schemas + 4 errors + 6 fake adapter)
- **Total tests passing**: 15/15
- **Layers used**: Unit (15), Integration (0), E2E (0)
- **Approval tests**: None — no refactoring tasks, all new code
- **Pure functions created**: `FakeCalendarAdapter.search`/`get_event` are deterministic given constructor-seeded state (no I/O, no globals); Pydantic validators (`_require_tz_aware`) are pure

## TDD Cycle Evidence (Batch 2 — Phases 4-6)

All 12 new tests live in the single shared file `tests/test_calendar_tools.py`
(per tasks.md's `::test_name` node-id convention — phases 4/5/6 share one
test module). Because the module's import line names all three tool
functions, each phase's RED step is "file fails to collect" (ImportError for
the not-yet-defined name) rather than a per-function ModuleNotFoundError;
each phase's GREEN step is confirmed by running the full file (all previously
green tests re-pass, proving no regression, plus the new tests pass).

| Task | Test File | Layer | Safety Net | RED | GREEN | TRIANGULATE | REFACTOR |
|------|-----------|-------|------------|-----|-------|-------------|----------|
| 4.1-4.4/4.5 | `tests/test_calendar_tools.py` (search tests) | Unit | 15/15 (baseline) | Yes — `ModuleNotFoundError: tools.calendar` on full file collection | Yes — 4 named tests pass + 1 extra triangulation test (5 total), 19/19 full suite | Yes — added `test_search_defaults_missing_bounds_using_lookback_window` (subject-only, both bounds omitted) beyond the 4 named REDs, per design.md handoff note that `_normalize_search_bounds` needed real coverage, not just the explicit-range case | None needed — logic already minimal (single validation branch + 3-way bound normalization) |
| 5.1-5.3/5.4 | `tests/test_calendar_tools.py` (get_event tests) | Unit | 19/19 (after phase 4) | Yes — `ImportError: cannot import name 'calendar_get_event'` on full file collection | Yes — 3/3 new tests pass, 22/22 full suite | Yes — 3 cases (success w/ real body, not-found error, empty-body success) covers all 3 spec scenarios | None needed — pure delegation to `adapter.get_event` |
| 6.1-6.4/6.5 | `tests/test_calendar_tools.py` (get_notes tests) | Unit | 22/22 (after phase 5) | Yes — `ImportError: cannot import name 'calendar_get_notes'` on full file collection | Yes — 4/4 new tests pass, 27/27 full suite | Yes — 4 cases (full-day-range expansion w/ spy, single match, zero match, multi match w/ no get_event call) covers all 4 spec scenarios incl. the "MUST NOT call get_event" ambiguous-match assertion | None needed — logic already minimal (search → 0/1/N branch → get_event) |

### Test Summary (Batch 2)
- **Total tests written**: 12 (5 search incl. 1 triangulation + 3 get_event + 4 get_notes)
- **Total tests passing**: 12/12 new, 27/27 full suite (15 baseline + 12 new)
- **Test command**: `.venv/bin/python3.12 -m pytest -q` from `/home/master/WinMCP`
- **Layers used**: Unit (12), Integration (0), E2E (0)
- **Approval tests**: None — no refactoring tasks, all new code
- **Pure functions created**: `_normalize_search_bounds` (pure given `now`/`lookback_days` inputs — the one impure edge is reading the wall clock, isolated to a single `datetime.now()` call); `calendar_search`/`calendar_get_event`/`calendar_get_notes` are otherwise thin, deterministic delegations to the injected `adapter`

### Cumulative Test Summary (Batch 1 + Batch 2)
- **Total tests**: 27
- **Total passing**: 27/27
- **Layers used**: Unit (27), Integration (0), E2E (0)

## TDD Cycle Evidence (Batch 3 — Phases 7-9)

A preparatory REFACTOR preceded Phase 7's RED cycle: `_local_timezone`/
`_load_settings` were extracted out of `tools/calendar.py` into a new shared
module `tools/settings.py` (`load_settings()`/`local_timezone()`), so the
Phase 7 adapter could reuse the same timezone-resolution concept without
reimplementing it (per the Batch 2 handoff note) and without a circular
import (`tools/calendar.py` imports `CalendarPort` from
`tools/outlook_adapter.py`, so `outlook_adapter.py` cannot import from
`tools/calendar.py`). The pre-existing 27/27 tests were the safety net for
this refactor; they stayed green throughout (verified before starting any
new RED test).

| Task | Test File | Layer | Safety Net | RED | GREEN | TRIANGULATE | REFACTOR |
|------|-----------|-------|------------|-----|-------|-------------|----------|
| (prep) settings extraction | n/a (existing suite) | Refactor | 27/27 (baseline) | n/a | n/a | n/a | Moved `_local_timezone`/`_load_settings` to `tools/settings.py`; `tools/calendar.py` updated to import from it; 27/27 still green after |
| 7.1-7.4/7.5 | `tests/test_outlook_adapter.py` | Unit | 27/27 (baseline) | Yes — 6/7 tests failed with `ImportError: cannot import name 'OutlookCalendarAdapter'` (the 7th, module-import-safety, trivially passed pre-GREEN since only the Protocol existed) | Yes — first pass left 4/34 failing due to a fake-`win32com.client` test-fixture bug (parent module's `.client` attribute not set, so `win32com.client.Dispatch` resolved to an `AttributeError` masked as `OutlookUnavailableError`); fixed the shared `_install_fake_win32com` test helper, then 34/34 passed | Yes — added `test_search_filters_by_subject_case_insensitive` (adapter's own post-Restrict subject filter must be case-insensitive, matching `CalendarPort`'s contract), `test_get_event_unknown_entry_id_raises_not_found` (`GetItemFromID` raising maps to `EventNotFoundError`, not `OutlookUnavailableError`), and `test_win32com_import_error_raises_outlook_unavailable_error` (genuine `ImportError` — not just a failed `Dispatch()` call — also maps correctly) beyond the 4 named REDs | None needed — adapter logic is a thin, direct COM-shape mapping; no duplication to consolidate |
| 8.1-8.4/8.5 | `tests/test_server.py` | Unit + Integration (FastMCP in-process `Client`) | 34/34 (after Phase 7) | Yes — `ModuleNotFoundError: No module named 'server'` on all 7 new tests | Yes — first pass left 1/41 failing (`test_calendar_search_tool_returns_results_via_fake_adapter` asserted dict-style `result.data[0]["entry_id"]`; FastMCP's `Client.call_tool()` actually returns a dynamically-built model with attribute access using the wire alias, e.g. `.entryId` — confirmed via a scratch script against the real `fastmcp` package rather than guessing); fixed the assertion, then 41/41 passed | Yes — added `test_calendar_search_tool_returns_results_via_fake_adapter` (end-to-end: fake adapter → tool → FastMCP `Client` → wire-shaped JSON, confirming the `entryId` alias survives serialization), `test_calendar_search_no_filters_surfaces_as_tool_error`, and `test_calendar_get_notes_ambiguous_match_surfaces_as_tool_error` (confirms `AmbiguousMatchError`'s `code` — `ambiguous_match` — appears in the mapped `ToolError` message) beyond the 4 named REDs | None needed — `server.py`'s tool wrappers are thin, uniform (parse request → delegate → catch-and-map); no duplication to consolidate |

### Test Summary (Batch 3)
- **Total tests written**: 14 (7 adapter incl. 3 triangulation + 7 server incl. 3 triangulation)
- **Total tests passing**: 14/14 new, 41/41 full suite (27 baseline + 14 new)
- **Test command**: `.venv/bin/python3.12 -m pytest -q` from `/home/master/WinMCP`
- **Layers used**: Unit (10), Integration (4 — FastMCP in-process `Client` round-trips in `test_server.py`), E2E (0 — deferred to the manual Windows smoke test in `README.md`, out of CI scope per proposal/design)
- **Approval tests**: None
- **Pure functions created**: `_dasl_datetime`/`_to_aware` (`tools/outlook_adapter.py`) are pure given their inputs; `_map_error` (`server.py`) is a pure exception→`ToolError` mapping

### Cumulative Test Summary (Batch 1 + Batch 2 + Batch 3 — FINAL)
- **Total tests**: 41
- **Total passing**: 41/41
- **Layers used**: Unit (37), Integration (4), E2E (0, manual-only per design.md)

## Files Created
| File | Purpose |
|------|---------|
| `pyproject.toml` | Project metadata; deps `fastmcp`, `pydantic`, `pyyaml`, `pywin32` (win32-only marker); dev deps `pytest`, `pytest-mock`; pytest `testpaths=["tests"]` |
| `tests/conftest.py` | Empty fixture stub (extended in later phases) |
| `config/settings.yaml` | `lookback_days`, `calendar_folder_id: 9`, `timezone_override` |
| `models/__init__.py`, `models/schemas.py` | `EventSummary`, `EventDetail`, `SearchRequest`, `GetEventRequest`, `GetNotesRequest` (Pydantic, tz-aware enforced) |
| `tools/__init__.py`, `tools/errors.py` | `OutlookUnavailableError`, `EventNotFoundError`, `AmbiguousMatchError` (each with `.code`; `AmbiguousMatchError` also carries `entry_ids`) |
| `tools/outlook_adapter.py` | `CalendarPort` Protocol (`search`, `get_event`) — no win32com import yet (deferred to Phase 7) |
| `tools/fake_adapter.py` | `FakeCalendarAdapter` — in-memory, constructor-seeded, satisfies `CalendarPort` |
| `tests/test_schemas.py`, `tests/test_errors.py`, `tests/test_fake_adapter.py` | RED/GREEN test files for above |
| `.venv/` | Local dev venv (pytest, pytest-mock, pydantic, pyyaml installed; **no pywin32, no fastmcp** — not needed until later phases) |
| `tools/calendar.py` | Batch 2: `calendar_search`, `calendar_get_event`, `calendar_get_notes` tool functions + private helper `_lookback_days`, `_normalize_search_bounds` (Batch 3: `_load_settings`/`_local_timezone` moved out to `tools/settings.py`, see Batch 3 row below) |
| `tests/test_calendar_tools.py` | Batch 2: RED/GREEN tests for all three tool functions (12 tests) |
| `tools/settings.py` | Batch 3 (prep refactor): `load_settings()`, `local_timezone()` — extracted from `tools/calendar.py` so `tools/outlook_adapter.py` can reuse the same timezone-resolution concept without a circular import |
| `tools/outlook_adapter.py` | Batch 3: added `OutlookCalendarAdapter` (real, win32com-backed) + `_dasl_datetime`/`_to_aware` helpers, alongside the existing `CalendarPort` Protocol |
| `tests/test_outlook_adapter.py` | Batch 3: RED/GREEN tests for `OutlookCalendarAdapter` (7 tests), incl. shared `_install_fake_win32com(mocker)` test helper that injects a fake `win32com.client` into `sys.modules` |
| `server.py` | Batch 3: FastMCP app — `create_server(adapter=None)`, `main()` entrypoint; registers `calendar_search`/`calendar_get_event`/`calendar_get_notes`; maps `CalendarToolError`/`ValueError` to `fastmcp.exceptions.ToolError` |
| `tests/test_server.py` | Batch 3: RED/GREEN tests for server wiring, tool registration, stdio-only transport, deferred adapter selection, and end-to-end fake-adapter tool calls (7 tests) |
| `README.md` | Batch 3: Windows install steps, Claude Desktop `mcpServers` config example, WSL2 dev-only fake-adapter notes, manual Windows smoke-test checklist, known limitations |
| `.venv/` (updated) | Batch 3: `fastmcp` (3.4.5) and its transitive deps installed; **pywin32 still NOT installed** (never required on this Linux host, per policy) |

## Deviations from Design (Batch 1 — Phases 1-3)
None — implementation matches design.md's Interfaces/Contracts section
(`CalendarPort.search(date_from, date_to, subject=None)`, `EventSummary`/
`EventDetail` field shapes) and File Changes table for these phases.

## Deviations from Design (Batch 2 — Phases 4-6)
None — implementation matches design.md's Interfaces/Contracts and File
Changes table. One addition not spelled out file-by-file in design.md but
consistent with its "Datetime handling" decision and the Batch 1 handoff
note: `tools/calendar.py` reads `config/settings.yaml` (`lookback_days` for
`calendar_search`'s bound-normalization default, `timezone_override` for
`calendar_get_notes`'s full-day-range expansion) via small private helpers
in the same file — no new module was added, matching design's File Changes
table (which lists only `tools/calendar.py` as the file to create for this
logic). The `ValueError` used for `calendar_search`'s "no filter provided"
rejection is a genuinely new choice not in design.md's 3-item error
taxonomy (`OutlookUnavailableError`/`EventNotFoundError`/`AmbiguousMatchError`)
— it is a pure tool-*input* validation failure that never reaches the
adapter, distinct from the adapter-facing domain errors the taxonomy
covers; `server.py` (Phase 8) will decide how to surface it as a FastMCP
tool error alongside the typed exceptions.

## Deviations from Design (Batch 3 — Phases 7-9)
- **Shared `tools/settings.py` module (not in design.md's File Changes
  table).** Resolves the Batch 2 handoff note: Phase 7's adapter needed the
  same local-timezone resolution concept as `tools/calendar.py`'s
  (now-removed) `_local_timezone()`. Importing directly from
  `tools/calendar.py` would create a circular import
  (`tools/calendar.py` → `tools/outlook_adapter.py` for `CalendarPort`;
  `tools/outlook_adapter.py` → `tools/calendar.py` for the timezone helper
  would close the cycle), so the helper was extracted to a new small shared
  module instead. Both `tools/calendar.py` and `tools/outlook_adapter.py`
  now import `load_settings`/`local_timezone` from it. Behavior is
  unchanged — verified by the pre-existing 27 tests staying green
  throughout the extraction (REFACTOR step, safety net = 27/27).
- **`calendar_search`'s bare `ValueError`** (flagged as an open item in the
  Batch 2 handoff) is now resolved: `server.py`'s tool wrappers catch both
  `CalendarToolError` and `ValueError`, mapping each to
  `fastmcp.exceptions.ToolError` with a `[code]` prefix (`[invalid_request]`
  for the `ValueError` case, `[outlook_unavailable]` /
  `[event_not_found]` / `[ambiguous_match]` for the typed taxonomy —
  `AmbiguousMatchError` additionally appends its candidate `entry_ids`).
  This satisfies design.md's "Error taxonomy" decision ("re-raised as
  FastMCP tool errors with a stable code field") without needing any change
  to `tools/errors.py` or `tools/calendar.py`.
- **Wire parameter shape**: `server.py`'s tool functions use flat,
  individually-aliased parameters (`Annotated[..., Field(alias="from")]`,
  etc.) rather than a single nested Pydantic-model parameter, so the MCP
  JSON schema exposes top-level `from`/`to`/`subject`/`entryId`/`date`
  keys — matching the wire casing `models/schemas.py`'s docstring says is
  used in `specs.md` — instead of nesting them under a wrapper object key.
  Verified empirically against the installed `fastmcp` package (3.4.5) via
  a scratch script before committing to this pattern, since design.md
  doesn't specify FastMCP's exact parameter-flattening behavior.
- Everything else matches design.md's Interfaces/Contracts, Data Flow, and
  File Changes table for Phases 7-9 (lazy `win32com.client` import inside
  `OutlookCalendarAdapter`'s methods only; `Dispatch("Outlook.Application")`
  → `GetNamespace("MAPI")` → `GetDefaultFolder(9)`; `GetItemFromID` for
  `get_event`, not a re-`Restrict` scan; stdio-only transport, no auth;
  adapter selection deferred to first tool call).

## Change Status: COMPLETE
All 9 phases / 37 tasks are done. Full suite: **41/41 tests passing**
(`.venv/bin/python3.12 -m pytest -q` from `/home/master/WinMCP`). `pywin32`
was never installed on this Linux dev host, and no test or module import
touches it except through the `win32com`/`win32com.client` mocks/fakes
injected explicitly by `tests/test_outlook_adapter.py` and
`tests/test_server.py`. `README.md` documents the Windows install path,
Claude Desktop wiring, and the manual smoke-test procedure needed to
validate real Outlook COM behavior (out of scope for this Linux CI/dev
environment by design). Ready for `/sdd-verify`.
