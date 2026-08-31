# Tasks: OneNote Access via COM Bridge

## Phase 1: Shared PS-Bridge Transport Extraction (before OneNote adapter)

- [x] 1.1 RED `tests/test_ps_bridge_transport.py` (mocked `Popen`, no real PowerShell): deadline kills child; sentinel -> `(rows, False)`; truncated-no-sentinel-with-rows -> `(rows, True)`; zero-rows-no-sentinel -> raises `PsBridgeTransportError`; corrupt non-last line -> raises; debug-log gated by callback
- [x] 1.2 GREEN `tools/ps_bridge_transport.py`: `PsBridgeTransport.invoke(script_path, request, *, timeout, debug_log_enabled, log_label) -> (rows, truncated)` — pinned `powershell.exe` 5.1 spawn, stdin JSON write, stdout/stderr pump threads, deadline loop, JSON-Lines parse (truncation-vs-corruption + sentinel), `_diagnostic_suffix`, debug-log line; raises `PsBridgeTransportError`
- [x] 1.3 REFACTOR `tools/file_search_adapter.py`: `PowerShellSearchBridge` delegates to `PsBridgeTransport.invoke()`, catches `PsBridgeTransportError` -> `WindowsSearchUnavailableError` (same message); `_build_search_sql`/`_build_get_info_sql`/row-mapping untouched
- [x] 1.4 VERIFY `tests/test_file_search_adapter.py` unmodified: `python3.12 -m pytest -q` stays green (regression net proving the refactor is behavior-preserving)

## Phase 2: Schemas & Errors

- [x] 2.1 RED `tests/test_schemas.py`: `PageSummary`/`PageDetail`/`OneNoteSearchRequest`/`GetPageRequest`/`CreatePageRequest`/`UpdatePageRequest`, camelCase aliases
- [x] 2.2 GREEN `models/schemas.py`: add 6 Pydantic models
- [x] 2.3 RED `tests/test_errors.py`: `OneNoteUnavailableError`, `OneNotePageNotFoundError`, `OneNoteSectionNotFoundError`, `OneNoteWriteNotAllowedError` (carries `notebook_name`/`allowed_notebooks`), `OneNotePageConflictError`
- [x] 2.4 GREEN `tools/errors.py`: 5 exceptions subclassing `CalendarToolError`

## Phase 3: OneNotePort + Fake Adapter

- [x] 3.1 RED `tests/test_fake_onenote_adapter.py`: `search` substring filter; `get_page`/`update_page` raise `OneNotePageNotFoundError` for unknown id; `get_hierarchy` returns seeded tree; all can raise `OneNoteUnavailableError`
- [x] 3.2 GREEN `tools/onenote_adapter.py`: `OneNotePort` Protocol — `search`/`get_hierarchy`/`get_page`/`create_page`/`update_page`
- [x] 3.3 GREEN `tools/fake_onenote_adapter.py`: `FakeOneNoteAdapter`, constructor-seeded

## Phase 4: OneNote Bridge Adapter (on `PsBridgeTransport`)

- [x] 4.1 RED `tests/test_onenote_adapter.py`: `search`/`get_page` call a mocked `PsBridgeTransport.invoke()` with the correct `{"op":...}` request; `PsBridgeTransportError` -> `OneNoteUnavailableError`; namespace read from document root, not hardcoded; title/body from nested CDATA; empty result -> `OneNotePageNotFoundError`
- [x] 4.2 GREEN `tools/onenote_adapter.py`: `search()`/`get_page()` via `self._transport.invoke(ps_bridge_onenote.ps1, ...)`, row mapping, XML/namespace extraction, error mapping
- [x] 4.3 RED `tests/test_onenote_adapter.py`: `get_hierarchy` parses notebook/section tree; `create_page` sends `section_id`/title/body; `update_page` passes `expected_last_modified` verbatim, never `MinValue`; conflict -> `OneNotePageConflictError` (best-effort match, per Open Question)
- [x] 4.4 GREEN `tools/onenote_adapter.py`: `get_hierarchy()`/`create_page()`/`update_page()` completing `OneNoteAdapter(transport)`
- [x] 4.5 CREATE `tools/ps_bridge_onenote.ps1`: self-contained `op` dispatch (`FindPages`/`GetHierarchy`/`GetPageContent`/`CreateNewPage`/`UpdatePageContent`) on `OneNote.Application`; no WSL2 COM, covered by 4.1/4.3 asserts only

## Phase 5: onenote_search tool

- [x] 5.1 RED `tests/test_onenote_tools.py`: matches returned; empty query rejected pre-adapter; zero matches -> `[]`; default limit 50; oversized limit clamped to 200; unavailable -> tool error
- [x] 5.2 GREEN `tools/onenote.py`: `onenote_search(request, adapter)`; add `onenote_search_max_results()` to `settings.py`

## Phase 6: onenote_get_page tool

- [x] 6.1 RED `tests/test_onenote_tools.py`: successful fetch; unknown id -> `onenote_page_not_found`; empty body -> `""` not error; unavailable -> tool error; repeated fetch non-mutating
- [x] 6.2 GREEN `tools/onenote.py`: implement `onenote_get_page`

## Phase 7: Write-path allowlist + settings

- [x] 7.1 RED `tests/test_settings.py`: `onenote_writable_notebooks()` defaults to `["z - Test Notebook"]` absent; reads configured list otherwise
- [x] 7.2 GREEN `tools/settings.py`: `onenote_writable_notebooks()`, `onenote_search_max_results()` (default 50), `onenote_ps_bridge_timeout_seconds()` (default 20); document keys in settings.yaml
- [x] 7.3 RED `tests/test_onenote_tools.py`: write to default test notebook succeeds; write to a live notebook refused pre-adapter; configured allowlist widens writable set
- [x] 7.4 GREEN `tools/onenote.py`: allowlist helper — `get_hierarchy()`, check notebook vs `onenote_writable_notebooks()`, raise `OneNoteWriteNotAllowedError` pre-write

## Phase 8: onenote_create_page / onenote_update_page tools

- [x] 8.1 RED `tests/test_onenote_tools.py`: create returns `PageDetail` with new `pageId`; create unavailable -> tool error; matching date update succeeds; stale date -> `onenote_page_conflict`, no write recorded
- [x] 8.2 GREEN `tools/onenote.py`: `onenote_create_page`/`onenote_update_page`, using Phase 7's allowlist check

## Phase 9: Server Wiring

- [x] 9.1 RED `tests/test_server.py`: import succeeds without win32com/powershell; 4 tools registered; bridge-unavailable -> clear error, no crash
- [x] 9.2 GREEN `server.py`: register 4 tools, `_resolve_real_onenote_adapter()` (lazy); `_map_error()` unchanged, new errors subclass `CalendarToolError`

## Phase 10: Full Suite & Docs

- [x] 10.1 Run `python3.12 -m pytest -q`, full suite green including unmodified `test_file_search_adapter.py`, fix regressions; update `README.md`: OneNote tools, allowlist, WSL2 fake-adapter notes

## Phase 11: Manual Verification (Windows host, not CI)

- [x] 11.1 **[MANUAL — user-run]** Deploy via `deploy-qa.sh`; verify search/get_page live, writes limited to `"z - Test Notebook"`, other-notebook writes refused; then `promote-pro.sh` — executed via a real MCP stdio driver run from WSL against the deployed QA instance (`C:\usr\WinMCP-qa`) on 2026-08-27: 8/8 PASS (handshake, 13-tool list, `onenote_search`, `onenote_get_page`, `onenote_create_page` in `"z - Test Notebook"`, `onenote_update_page` honest append, stale-timestamp -> `onenote_page_conflict`, allowlist refusal for `"Informa - Governance"` -> `onenote_notebook_not_allowed`). Surfaced and fixed 4 live-only defects along the way (see `apply-progress.md` Batch 5). Driver script preserved at this session's scratchpad and at `C:\usr\WinMCP-qa\_qa_onenote_live.py`.
