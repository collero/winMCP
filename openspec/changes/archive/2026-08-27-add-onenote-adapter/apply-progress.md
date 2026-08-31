# Apply Progress: add-onenote-adapter

## Batch 1 — Phase 1: Shared PS-Bridge Transport Extraction

**Mode**: Strict TDD

### Completed Tasks

- [x] 1.1 RED `tests/test_ps_bridge_transport.py`
- [x] 1.2 GREEN `tools/ps_bridge_transport.py`
- [x] 1.3 REFACTOR `tools/file_search_adapter.py`'s `PowerShellSearchBridge` onto the transport
- [x] 1.4 VERIFY `tests/test_file_search_adapter.py` unmodified, full suite green

### Files Changed

| File | Action | What Was Done |
|------|--------|----------------|
| `tools/ps_bridge_transport.py` | Created | `PsBridgeTransport.invoke(script_path, request, *, timeout, debug_log_enabled=None, log_label="", logger=None, diagnostics=None) -> (rows, truncated)`. Ported near-verbatim from `PowerShellSearchBridge._invoke_impl`: pinned absolute `powershell.exe` 5.1 spawn (`_PS_EXE`), stdin JSON write via `Popen` (never `subprocess.run`), background stdout/stderr pump threads (`_pump_stdout`/`_pump_stderr`), a wall-clock deadline loop reading a `queue.Queue`, the JSON-Lines truncation-vs-corruption rule + `{"done": true}` sentinel, the `{"error": ...}` script-line handling, `_diagnostic_suffix`, and `_reap`. Raises the new domain-agnostic `PsBridgeTransportError`. |
| `tools/file_search_adapter.py` | Modified | Removed `_pump_stdout`, `_pump_stderr`, `_reap`, `_STREAM_EOF`, `_diagnostic_suffix` (moved into the transport, no longer duplicated). `PowerShellSearchBridge.__init__` now takes an optional injectable `transport: PsBridgeTransport | None` (defaults to a real one). `_invoke`/`_invoke_impl` refactored: `_invoke_impl` now delegates to `self._transport.invoke(_PS_BRIDGE_SCRIPT, {"sql": sql}, timeout=..., log_label="search", diagnostics=record)` and catches `PsBridgeTransportError` -> `WindowsSearchUnavailableError(str(exc))`. `_invoke`'s outer `_log_bridge_invocation` wiring, `_BRIDGE_DEBUG_LOG_PATH`, `file_search_bridge_debug_log`, `_build_search_sql`/`_build_get_info_sql`/`_row_from_mapping`/row-mapping, `_parse_bridge_stdout`/`_BridgeUnparseableLineError` (the standalone pure-function reference implementation), `WindowsSearchAdapter`, `FallbackSearchAdapter` — all left byte-for-byte untouched. `_PS_EXE` is now imported (re-exported) from `tools.ps_bridge_transport` instead of being defined locally, and `import subprocess`/`import queue`/`import threading` — the latter two dropped as no longer used directly; `subprocess` kept solely so `tools.file_search_adapter.subprocess.Popen` remains a valid patch target for the regression suite (the real spawn now happens inside `tools/ps_bridge_transport.py`, but `mocker.patch("tools.file_search_adapter.subprocess.Popen", ...)` still works because both modules' `subprocess` names point at the same real module object, and patching an attribute on it is global). |
| `tests/test_ps_bridge_transport.py` | Created | 20 tests against `PsBridgeTransport` directly: pinned exe/argv shape, stdin JSON write, sentinel -> `(rows, False)`, truncated-no-sentinel -> `(rows, True)`, deadline-kills-hung-child (partial + zero-row cases), zero-rows-no-sentinel raises with exit/stderr diagnostics, spawn-blocked distinct wording, corrupt-non-last-line raises / partial-last-line does not, `log_label` parametrizing message wording, script `{"error": ...}` line handling (zero-rows-raises and after-partial-success), the `diagnostics` output param on both success and failure, the generic `debug_log_enabled`/`logger` hook (fires when enabled, silent when disabled, fires even when `invoke()` raises, never propagates a broken logger's own exception), and the blanket unforeseen-exception mapping. |
| `openspec/changes/add-onenote-adapter/tasks.md` | Modified | Checked off 1.1–1.4 |

### TDD Cycle Evidence

| Task | Test File | Layer | Safety Net | RED | GREEN | TRIANGULATE | REFACTOR |
|------|-----------|-------|------------|-----|-------|-------------|----------|
| 1.1/1.2 | `tests/test_ps_bridge_transport.py` | Unit (mocked `subprocess.Popen`) | N/A (new module) | ✅ Written — confirmed genuine RED by temporarily removing the just-written implementation and re-running (`ModuleNotFoundError`), then restoring it | ✅ 20/20 passing after restoring the implementation | ✅ 20 cases across all listed scenarios (deadline, sentinel, truncation, corruption, spawn-block, script-error-line, diagnostics, debug-log hook) | ✅ Extracted `_bridge_phrase()` helper after discovering the naive `f"PowerShell {log_label} bridge"` template produced `"PowerShell bridge bridge ..."` for the default `log_label=""`; re-ran full transport suite green after the fix |
| 1.3 | `tests/test_file_search_adapter.py` (regression net, unmodified) | Approval test (existing suite as behavior baseline) | ✅ 543/543 passing at batch start (confirmed via `python3.12 -m pytest -q` before touching `file_search_adapter.py`) | N/A — refactor task, no new test written; approval-testing discipline applied instead (existing suite IS the "test written first") | ✅ 563/563 passing after the refactor (543 baseline + 20 new transport tests) | N/A — refactor preserves existing behavior, does not add new behavior | ✅ Removed 5 now-duplicated helper functions (`_pump_stdout`/`_pump_stderr`/`_reap`/`_STREAM_EOF`/`_diagnostic_suffix`) from `file_search_adapter.py`; `_invoke_impl` reduced from ~180 lines to ~15 |
| 1.4 | `tests/test_file_search_adapter.py` | N/A — verification task | — | — | ✅ 87/87 tests in this file passing (79 `def test_` functions + 8 extra from `@pytest.mark.parametrize`'s 9-case table = 87), file confirmed byte-for-byte unmodified (never opened with Edit/Write, only Read) | — | — |

### Test Summary

- **Total tests written**: 20 (all in `tests/test_ps_bridge_transport.py`)
- **Total tests passing**: 563/563 (full suite: `python3.12 -m pytest -q` inside `.venv`)
- **Layers used**: Unit (20, mocked `subprocess.Popen`) — no integration/E2E layer applicable to this batch (pure transport-mechanics extraction)
- **Approval tests** (refactoring): the entire pre-existing 87-test `tests/test_file_search_adapter.py` suite served as the approval-test baseline for the `PowerShellSearchBridge` refactor — confirmed green both before (543 total) and after (563 total) the refactor, unmodified
- **Pure functions created**: `_bridge_phrase`, `_diagnostic_suffix` (both pure, in `tools/ps_bridge_transport.py`)

### Deviations from Design

design.md's sketched signature is `PsBridgeTransport.invoke(script_path, request, *, timeout, debug_log_enabled, log_label) -> tuple[list[dict], bool]`, raising `PsBridgeTransportError` on failure, with each adapter's wrapper re-raising its own typed error with "the same message" (Decision 2). Two additions beyond that sketch, both backward-compatible (optional keyword params with safe defaults) and necessary to keep `tests/test_file_search_adapter.py` byte-for-byte unmodified and green:

1. **`diagnostics: dict[str, Any] | None = None` output param.** `file_search_adapter.py`'s existing, already-tested `_log_bridge_invocation()` writes a SQL-aware debug log line (`sql_first_120`, etc.) that only the file-search adapter can produce — the transport is deliberately domain-agnostic and cannot build that exact line itself. `diagnostics`, when given, is mutated in place with `rows_streamed`/`sentinel_seen`/`exit_condition`/`stderr_excerpt`/`error_line_first_200` regardless of success/failure, letting `PowerShellSearchBridge._invoke_impl` pass its own pre-existing `record` dict straight through and keep its `finally`-based `_log_bridge_invocation` call completely unchanged.
2. **`logger: Callable[[str, dict], None] | None = None`**, paired with `debug_log_enabled`/`log_label`. This is the transport's OWN generic debug-log hook (design.md's "config-gated debug-log hook" — mentioned but not fully specified), for a future adapter (OneNote) that has no richer domain-specific logger of its own. `file_search_adapter.py` does not use it at all (leaves both at their `None` defaults) to avoid double-logging, since it already has its own richer log via `diagnostics`.
3. **`log_label` default is `""` (not required, no fixed word like `"bridge"`).** A naive `f"PowerShell {log_label} bridge ..."` template with a placeholder default produced `"PowerShell bridge bridge ..."`; introduced a small `_bridge_phrase(log_label)` helper so the default renders as the bare `"PowerShell bridge ..."` and `log_label="search"` reproduces `PowerShellSearchBridge`'s exact, already-tested wording (`"PowerShell search bridge ..."`) byte-for-byte. `PowerShellSearchBridge` passes `log_label="search"` explicitly.
4. **`PowerShellSearchBridge.__init__` gained an optional `transport: PsBridgeTransport | None = None` parameter.** Not in design.md's file-changes table, but mirrors `FallbackSearchAdapter`'s existing primary/bridge injection pattern and required no changes to any existing call site (`FallbackSearchAdapter.__init__` and every test still construct `PowerShellSearchBridge()` with no args).

No other deviations. `_build_search_sql`, `_build_get_info_sql`, `_escape_sql`, `_escape_like_value`, `_escape_like_metacharacters`, `_escape_contains_phrase`, `_normalize_path`, `_decode_item_url`, `_normalize_multi_value`, `_field`, `_row_to_summary`, `_row_to_detail`, `_row_from_mapping`, `_parse_bridge_stdout`, `_BridgeUnparseableLineError`, `WindowsSearchAdapter`, `FallbackSearchAdapter`, `_log_bridge_invocation`, `_BRIDGE_DEBUG_LOG_PATH` are all unchanged in `tools/file_search_adapter.py`.

### Issues Found

None. One self-caught bug during TRIANGULATE (see TDD Cycle Evidence above): the initial `log_label` default produced doubled "bridge" wording in the generic-path error message; fixed with `_bridge_phrase()` before this batch's tests were considered green.

### Test Runner Note

`python3.12 -m pytest -q` (the configured `test_command`) fails on this host's bare `/usr/bin/python3.12` — pytest is only installed inside the project's `.venv`. All test runs in this batch used `source .venv/bin/activate && python3.12 -m pytest -q`, which resolves `python3.12` to `.venv/bin/python3.12`. Flagging this for `sdd-verify` and any future batch: the same activation step is needed, or the venv's `pytest` binary should be invoked directly.

### Remaining Tasks (as of end of Batch 1)

- [ ] Phase 2: Schemas & Errors
- [ ] Phase 3: OneNotePort + Fake Adapter
- [ ] Phase 4: OneNote Bridge Adapter (on `PsBridgeTransport`)
- [ ] Phase 5: `onenote_search` tool
- [ ] Phase 6: `onenote_get_page` tool
- [ ] Phase 7: Write-path allowlist + settings
- [ ] Phase 8: `onenote_create_page` / `onenote_update_page` tools
- [ ] Phase 9: Server Wiring
- [ ] Phase 10: Full Suite & Docs
- [ ] Phase 11: Manual Verification (Windows host, not CI)

### Status (as of end of Batch 1)

4/4 tasks in this batch (Phase 1) complete. Full suite: 563/563 passing. Ready for the next batch (Phase 2: Schemas & Errors).

---

## Batch 2 — Phase 2: Schemas & Errors; Phase 3: OneNotePort + Fake Adapter; Phase 4: OneNote Bridge Adapter

**Mode**: Strict TDD

### Completed Tasks

- [x] 2.1 RED `tests/test_schemas.py`: `PageSummary`/`PageDetail`/`OneNoteSearchRequest`/`GetPageRequest`/`CreatePageRequest`/`UpdatePageRequest`, camelCase aliases
- [x] 2.2 GREEN `models/schemas.py`: add 6 Pydantic models
- [x] 2.3 RED `tests/test_errors.py`: `OneNoteUnavailableError`, `OneNotePageNotFoundError`, `OneNoteSectionNotFoundError`, `OneNoteWriteNotAllowedError` (carries `notebook_name`/`allowed_notebooks`), `OneNotePageConflictError`
- [x] 2.4 GREEN `tools/errors.py`: 5 exceptions subclassing `CalendarToolError`
- [x] 3.1 RED `tests/test_fake_onenote_adapter.py`: `search` substring filter; `get_page`/`update_page` raise `OneNotePageNotFoundError` for unknown id; `get_hierarchy` returns seeded tree; all can raise `OneNoteUnavailableError`
- [x] 3.2 GREEN `tools/onenote_adapter.py`: `OneNotePort` Protocol — `search`/`get_hierarchy`/`get_page`/`create_page`/`update_page`
- [x] 3.3 GREEN `tools/fake_onenote_adapter.py`: `FakeOneNoteAdapter`, constructor-seeded
- [x] 4.1 RED `tests/test_onenote_adapter.py`: `search`/`get_page` call a mocked `PsBridgeTransport.invoke()` with the correct `{"op":...}` request; `PsBridgeTransportError` -> `OneNoteUnavailableError`; namespace read from document root, not hardcoded; title/body from nested CDATA; empty result -> `OneNotePageNotFoundError`
- [x] 4.2 GREEN `tools/onenote_adapter.py`: `search()`/`get_page()` via `self._transport.invoke(ps_bridge_onenote.ps1, ...)`, row mapping, XML/namespace extraction, error mapping
- [x] 4.3 RED `tests/test_onenote_adapter.py`: `get_hierarchy` parses notebook/section tree; `create_page` sends `section_id`/title/body; `update_page` passes `expected_last_modified` verbatim, never `MinValue`; conflict -> `OneNotePageConflictError` (best-effort match, per Open Question)
- [x] 4.4 GREEN `tools/onenote_adapter.py`: `get_hierarchy()`/`create_page()`/`update_page()` completing `OneNoteAdapter(transport)`
- [x] 4.5 CREATE `tools/ps_bridge_onenote.ps1`: self-contained `op` dispatch (`FindPages`/`GetHierarchy`/`GetPageContent`/`CreateNewPage`/`UpdatePageContent`) on `OneNote.Application`; no WSL2 COM, covered by 4.1/4.3 asserts only

### Files Changed

| File | Action | What Was Done |
|------|--------|----------------|
| `models/schemas.py` | Modified | Added `PageSummary` (`page_id`/`title`/`notebook_name`/`section_name`/optional `last_modified`), `PageDetail(PageSummary)` (+`body_text`), `OneNoteSearchRequest` (`query`, optional `limit` — no schema-level validation/clamping, mirrors `FileSearchRequest`), `GetPageRequest` (`page_id`), `CreatePageRequest` (`section_id`/`title`/`body_text`), `UpdatePageRequest` (`page_id`/`body_text`/required `expected_last_modified`). All 6 are `_AliasedModel`s with camelCase aliases (`pageId`, `notebookName`, `sectionName`, `lastModifiedDateTime`, `bodyText`, `sectionId`, `dateExpectedLastModified`). |
| `tools/errors.py` | Modified | Added `OneNoteUnavailableError` (`onenote_unavailable`), `OneNotePageNotFoundError` (`onenote_page_not_found`), `OneNoteSectionNotFoundError` (`onenote_section_not_found`), `OneNoteWriteNotAllowedError` (`onenote_notebook_not_allowed`, carries `notebook_name`/`allowed_notebooks`), `OneNotePageConflictError` (`onenote_page_conflict`) — all subclass `CalendarToolError`, matching the existing taxonomy-reuse precedent. |
| `tools/onenote_adapter.py` | Created | `SectionNode`/`NotebookNode` (frozen dataclasses, internal — not aliased pydantic models, since `get_hierarchy()` is "internal, not an MCP tool" per spec). `OneNotePort` Protocol (`search`/`get_hierarchy`/`get_page`/`create_page`/`update_page`). Real `OneNoteAdapter(transport: PsBridgeTransport | None = None)` built on `PsBridgeTransport` from day one: `_invoke(op, fields)` builds `{"op": op, **fields}` and delegates to `self._transport.invoke(_PS_BRIDGE_ONENOTE_SCRIPT, request, timeout=_DEFAULT_TIMEOUT_SECONDS, log_label="onenote")`. `search()` sends `{"op":"FindPages","query":...}`, maps rows via `_row_to_page_summary` (flat fields, no XML), truncates to `top_n` client-side. `get_hierarchy()` sends `{"op":"GetHierarchy"}`, groups flat `{notebookId,notebookName,sectionId,sectionName}` rows into `list[NotebookNode]`. `get_page()`/`create_page()`/`update_page()` send `GetPageContent`/`CreateNewPage`/`UpdatePageContent` requests and map the returned row via `_row_to_page_detail`, which calls `_extract_title_and_body(row["pageXml"])` — parses the raw page XML with `xml.etree.ElementTree`, reading the `one` namespace URI off the document's own root element (never hardcoded) and extracting title from `Title/OE/T` CDATA and body from each `Outline/OEChildren/OE`'s `T` CDATA, joined by `"\n"`. `PsBridgeTransportError` maps to `OneNoteUnavailableError` generically; `get_page()`/`update_page()` additionally check `_NOT_FOUND_MARKERS` ("not found") to raise `OneNotePageNotFoundError` instead, and `update_page()` checks `_CONFLICT_MARKERS` ("conflict", "modified since", "expectedlastmodified") first to raise `OneNotePageConflictError`. Zero rows on a successful `get_page()`/`update_page()` call also raises `OneNotePageNotFoundError`. `update_page()` passes `expected_last_modified.isoformat()` through verbatim, never a `MinValue`-equivalent default. |
| `tools/fake_onenote_adapter.py` | Created | `FakeOneNoteAdapter(pages, hierarchy, *, unavailable=False)` — in-memory `OneNotePort`. `search()`: case-insensitive substring match on seeded `title` OR `body_text`, capped at `top_n`. `get_page()`/`update_page()`: dict lookup by `page_id`, `OneNotePageNotFoundError` on miss. `get_hierarchy()`: returns the seeded `list[NotebookNode]` as-is. `create_page()`: resolves `section_id` against the seeded hierarchy (`OneNoteSectionNotFoundError` on miss), assigns a new `FAKE-PAGE-N` id. `update_page()`: enforces the same optimistic-concurrency rule as the real adapter — a seeded page with `last_modified=None` accepts any write; otherwise a `expected_last_modified` older than the seeded page's `last_modified` raises `OneNotePageConflictError` and leaves the seeded page untouched (uses `PageDetail.model_copy()` to apply the write). All methods raise `OneNoteUnavailableError` first when constructed with `unavailable=True`. |
| `tools/ps_bridge_onenote.ps1` | Created | Self-contained dumb-executor script, faithful to `/mnt/c/usr/WinMCP/_spike_onenote.ps1`/`_spike_onenote_write.ps1`'s already-validated COM calls. Reads one `{"op": ...}` JSON object from stdin, `switch`-dispatches to `FindPages`/`GetHierarchy`/`GetPageContent`/`CreateNewPage`/`UpdatePageContent` against a per-invocation `New-Object -ComObject OneNote.Application`. `FindPages`/`GetHierarchy` emit flat JSON rows read straight off hierarchy XML attributes (`name`/`ID`/`dateTime`) via `ancestor::one:Notebook[1]`/`ancestor::one:Section[1]` XPath lookups — no CDATA extraction. `GetPageContent`/`CreateNewPage`/`UpdatePageContent` instead emit the page's raw `pageXml` (title/body extraction happens in Python — see the `tools/onenote_adapter.py` deviation note below) plus `notebookName`/`sectionName` resolved the same ancestor-XPath way. `UpdatePageContent`'s op checks the hierarchy's own `dateTime` attribute against the caller's `expectedLastModified` BEFORE writing, and passes the caller's date through to the real COM `UpdatePageContent` call verbatim (never `[DateTime]::MinValue`) — `CreateNewPage`'s own internal title/body-setting write, on a page that cannot yet conflict with anything, legitimately still uses `MinValue` for that one initial write, per the spike. A stale-date rejection's thrown message contains the substring `"modified since expectedLastModified"`; an unresolved page/section id's thrown message contains `"not found"` — both deliberately chosen to match `tools/onenote_adapter.py`'s `_CONFLICT_MARKERS`/`_NOT_FOUND_MARKERS` substring checks. Same JSON-Lines-rows-then-`{"done":true}`-sentinel / single-`{"error":...}`-line-plus-nonzero-exit contract as `tools/ps_bridge_search.ps1`. Not unit-tested directly (no real PowerShell/COM on WSL2) — covered by `tests/test_onenote_adapter.py`'s request-shape/row-mapping assertions against a mocked `PsBridgeTransport.invoke()`, per tasks.md 4.5, plus the change's manual verification phase (tasks.md Phase 11). |
| `tests/test_schemas.py` | Modified | Added 10 new tests for the 6 new models (construction via aliases, optional-field defaults, `PageDetail IS-A PageSummary`, no schema-level query/limit validation on `OneNoteSearchRequest`, `UpdatePageRequest` requiring `expected_last_modified`). |
| `tests/test_errors.py` | Modified | Added 15 new tests (3 per new error class × 5 classes): carries `code`/message, `isinstance CalendarToolError`, raisable/catchable; `OneNoteWriteNotAllowedError`'s also asserts `notebook_name`/`allowed_notebooks`. |
| `tests/test_fake_onenote_adapter.py` | Created | 17 tests covering `search()` (title substring, body substring, no-match, `top_n` cap, unavailable), `get_page()` (hit, miss, unavailable), `get_hierarchy()` (seeded tree, unavailable), `create_page()` (new id + resolved names, unknown section, unavailable), `update_page()` (matching date succeeds, unknown id, stale date -> conflict + no silent write, unavailable). |
| `tests/test_onenote_adapter.py` | Created | 23 tests against `OneNoteAdapter` with a mocked `PsBridgeTransport` (never `subprocess`/real PowerShell): exact `{"op": ...}` request dict per method (`FindPages`/`GetHierarchy`/`GetPageContent`/`CreateNewPage`/`UpdatePageContent`), row-to-model mapping including a namespace-independence case (a page XML declaring a non-default `one` namespace URI still extracts correctly), title/body extraction from nested CDATA across multiple paragraphs, `top_n` client-side truncation, `PsBridgeTransportError` -> `OneNoteUnavailableError` generically and -> `OneNotePageNotFoundError`/`OneNotePageConflictError` on marker-matched messages, empty-result -> `OneNotePageNotFoundError` for `get_page`/`update_page`, `expected_last_modified` passed through verbatim (never `datetime.min`), and default construction wiring a real `PsBridgeTransport`. |
| `openspec/changes/add-onenote-adapter/tasks.md` | Modified | Checked off 2.1–2.4, 3.1–3.3, 4.1–4.5 |

### TDD Cycle Evidence

| Task | Test File | Layer | Safety Net | RED | GREEN | TRIANGULATE | REFACTOR |
|------|-----------|-------|------------|-----|-------|-------------|----------|
| 2.1/2.2 | `tests/test_schemas.py` | Unit (pure pydantic) | ✅ 563/563 passing at batch start | ✅ Written — confirmed genuine RED (`ImportError: cannot import name 'CreatePageRequest'`) before adding the models | ✅ 96/96 passing in `tests/test_schemas.py`+`tests/test_errors.py` together after adding both | ✅ 10 cases across all 6 models (alias construction, optional-default, IS-A inheritance, no-schema-validation, required-field enforcement) | ➖ None needed — straight pydantic field declarations, no logic to simplify |
| 2.3/2.4 | `tests/test_errors.py` | Unit (pure exception classes) | ✅ 563/563 passing at batch start | ✅ Written — confirmed genuine RED (`ImportError: cannot import name 'OneNotePageConflictError'`) before adding the exceptions | ✅ 96/96 passing (same combined run as above) | ✅ 15 cases across all 5 exception classes (code, message, isinstance, raisable, + context-carrying for `OneNoteWriteNotAllowedError`) | ➖ None needed |
| 3.1/3.2/3.3 | `tests/test_fake_onenote_adapter.py` | Unit (pure in-memory adapter, no I/O) | N/A (new modules) | ✅ Written — confirmed genuine RED (`ModuleNotFoundError: No module named 'tools.fake_onenote_adapter'`) before writing `tools/onenote_adapter.py`'s Protocol/dataclasses or `tools/fake_onenote_adapter.py` | ✅ 17/17 passing on the first implementation attempt (all 17 cases were already written at RED time, so GREEN and TRIANGULATE landed together) | ✅ 17 cases across `search`/`get_page`/`get_hierarchy`/`create_page`/`update_page` (hit/miss/cap/unavailable/conflict per method) | ➖ None needed — implementation was already the simplest correct form on first pass |
| 4.1/4.2 | `tests/test_onenote_adapter.py` | Unit (mocked `PsBridgeTransport.invoke()`, no real PowerShell) | N/A (new module — Protocol/dataclasses from 3.2 already existed and were extended, not modified) | ✅ Written — confirmed genuine RED (`ImportError: cannot import name '_PS_BRIDGE_ONENOTE_SCRIPT'`) before adding `OneNoteAdapter` | ✅ 23/23 passing on the first implementation attempt | ✅ 23 cases across `search`/`get_hierarchy`/`get_page`/`create_page`/`update_page` — including a deliberate non-default-namespace case for the "namespace read from document root, not hardcoded" requirement and a multi-paragraph CDATA case | ➖ None needed |
| 4.3/4.4/4.5 | `tests/test_onenote_adapter.py` (same file/run as 4.1/4.2 — the RED/GREEN split by task number was in the SAME edit pass, since `OneNoteAdapter`'s 5 methods share the same `_invoke`/row-mapping infrastructure) | Unit (mocked `PsBridgeTransport.invoke()`) | — (covered above) | ✅ Written (`get_hierarchy` tree-grouping, `create_page` request shape, `update_page` verbatim-date + conflict-marker cases) | ✅ Passing (same 23/23 run as above) | ✅ (included in the 23 cases above) | ✅ Removed a duplicate/dead `$titleT = ...` line in `ps_bridge_onenote.ps1`'s `CreateNewPage` case discovered on review (leftover from drafting, immediately overwritten — harmless but dead code) |

### Test Summary

- **Total tests written this batch**: 10 (schemas) + 15 (errors) + 17 (fake adapter) + 23 (real adapter) = 65
- **Total tests passing (full suite)**: 628/628 (`source .venv/bin/activate && python3.12 -m pytest -q`)
- **Layers used**: Unit (65 — pure pydantic/exception classes, in-memory fake adapter, mocked-transport real adapter) — no integration/E2E layer applicable to this batch
- **Approval tests** (refactoring): none — this batch is pure addition, no existing production code was modified (only `models/schemas.py`/`tools/errors.py` had NEW classes appended; every pre-existing class/test in those two files is untouched, confirmed by the combined 96/96 pass and the unchanged full-suite delta of exactly +65 from Batch 1's 563)
- **Pure functions created**: `_extract_title_and_body`, `_row_to_page_summary`, `_row_to_page_detail`, `_is_marked` (all pure, in `tools/onenote_adapter.py`)

### Deviations from Design

1. **Op vocabulary is the literal COM method names, not design.md's Decision 5 paraphrase.** design.md's Decision 5 writes the op values as `"search"`/`"get_page"`/`"get_hierarchy"`/`"create_page"`/`"update_page"`. The onenote-com-adapter spec's own scenarios are explicit and concrete that the wire values are the COM method names themselves — `"op": "FindPages"` for search, and the spec's "Dumb-Executor Bridge Transport" requirement lists `FindPages`/`GetHierarchy`/`GetPageContent`/`CreateNewPage`/`UpdatePageContent` — which tasks.md 4.5 also uses verbatim. Followed the spec/tasks.md wording (more concrete and directly asserted by a scenario) over design.md's looser paraphrase.
2. **XML title/body extraction moved from PowerShell to Python**, reversing design.md's Decision 7 ("the script ... Returns plain `{title, text}` JSON — Python never parses OneNote XML"). The onenote-com-adapter spec's own "Dynamic XML Namespace Detection"/"Page Content Extraction" scenarios both say "WHEN the adapter parses it" (not "the script"), and tasks.md 4.1 assigns "namespace read from document root, not hardcoded"/"title/body from nested CDATA" as RED tests in `tests/test_onenote_adapter.py` — a Python test file — which is only meaningful if `OneNoteAdapter` itself does this parsing (there is no way to unit-test a `.ps1` script's internal XML logic from this WSL2 host). Implemented `_extract_title_and_body()` in `tools/onenote_adapter.py` using `xml.etree.ElementTree`, with `ps_bridge_onenote.ps1` instead returning the page's raw `pageXml` string. This also follows this codebase's own established precedent ("escape/parse in exactly one place" — `_escape_like_value`/`_build_search_sql`'s SQL-construction rationale) applied to XML parsing instead of SQL escaping. `FindPages`/`GetHierarchy` are UNAFFECTED by this — those two ops' rows use flat attribute reads (`name`/`ID`/`dateTime`), never CDATA, so the script still parses THAT XML itself (there is no ambiguity/spec conflict there).
3. **`get_hierarchy()` has no `depth` parameter and returns `list[NotebookNode]`**, per design.md's Interfaces/Contracts code block (`def get_hierarchy(self) -> list[NotebookNode]`), rather than the onenote-com-adapter spec's prose ("`get_hierarchy(depth=4) -> HierarchyNode`"). Followed the more concrete, directly-implementable contract; nothing in tasks.md 3.x/4.x ever exercises a variable depth, and the real COM call always requests full depth (`4`) internally regardless of what (if anything) a Python-facing parameter would do.
4. **No separate `OneNoteSearchResult`/`CreatePageResult`/`UpdatePageResult` envelope models**, despite design.md's File Changes table mentioning `.../Result` suffixes. tasks.md 2.1/2.2 explicitly scope Phase 2 to exactly 6 named models (`PageSummary`/`PageDetail`/`OneNoteSearchRequest`/`GetPageRequest`/`CreatePageRequest`/`UpdatePageRequest`), and every onenote-search/-get-page/-write-page spec scenario has the tool returning a plain `list[PageSummary]` or a bare `PageDetail` directly (unlike `mail_search`/`calendar_search`/`task_search`'s `_TruncatableResult` envelopes) — no spec ever describes a `resultsTruncated`-style wrapper for OneNote. Treated design.md's `/Result` mentions as informal shorthand for "the tool's response shape," not a request for new wrapper types.
5. **`_DEFAULT_TIMEOUT_SECONDS = 20.0` is a local module constant in `tools/onenote_adapter.py`, not read from `tools/settings.py`.** tasks.md's Phase 7 (a later batch, explicitly out of THIS batch's scope) is where `tools/settings.py::onenote_ps_bridge_timeout_seconds()` (default 20) gets created — this batch does not touch `tools/settings.py`/`config/settings.yaml` at all, per the batch-scope boundary. `OneNoteAdapter._invoke()` still needs SOME timeout value to pass to `PsBridgeTransport.invoke()`'s required `timeout` kwarg today, so it uses a hardcoded constant (same numeric default Phase 7 will introduce) with a docstring flagging that Phase 7 should wire it to the new settings function instead — a small, contained future diff.
6. **`OneNoteWriteNotAllowedError`/`OneNoteSectionNotFoundError` are defined (Phase 2) but not yet raised by any adapter code in this batch** — `OneNoteWriteNotAllowedError` is entirely the tool layer's responsibility (Phase 7, allowlist check before any adapter call, per design.md's "Allowlist enforcement point" decision) and is only exercised by `FakeOneNoteAdapter`/tests in a later batch's tool tests. `OneNoteSectionNotFoundError` IS already raised by `FakeOneNoteAdapter.create_page()`/`_resolve_section()` for an unknown seeded `section_id` (test-covered in this batch), but the REAL `OneNoteAdapter.create_page()` does not raise it itself — an unresolved `sectionId` surfaces from `ps_bridge_onenote.ps1`'s own `"section not found: ..."` error text through the generic `PsBridgeTransportError` -> `OneNoteUnavailableError` path today, since `_NOT_FOUND_MARKERS`/`_CONFLICT_MARKERS` are scoped to PAGE-level messages only (no test in this batch asserts otherwise, and no spec requirement demands `OneNoteSectionNotFoundError` specifically from the ADAPTER as opposed to the tool-layer allowlist flow, where section resolution normally happens BEFORE any adapter call per the Sequence Diagram).

No other deviations. `PsBridgeTransport`/`PsBridgeTransportError` (Batch 1) are used unchanged; `tools/file_search_adapter.py`/`tests/test_file_search_adapter.py` are untouched (confirmed: `tests/test_file_search_adapter.py` still 87/87 passing, byte-for-byte unmodified, never opened with Edit/Write this batch either).

### Issues Found

None.

### Remaining Tasks (this change)

- [ ] Phase 5: `onenote_search` tool
- [ ] Phase 6: `onenote_get_page` tool
- [ ] Phase 7: Write-path allowlist + settings
- [ ] Phase 8: `onenote_create_page` / `onenote_update_page` tools
- [ ] Phase 9: Server Wiring
- [ ] Phase 10: Full Suite & Docs
- [ ] Phase 11: Manual Verification (Windows host, not CI)

### Test Runner Note

Same as Batch 1: `python3.12 -m pytest -q` fails on this host's bare `/usr/bin/python3.12` (no pytest installed there) — every test run in this batch used `source .venv/bin/activate && python3.12 -m pytest -q`, which resolves `python3.12` to `.venv/bin/python3.12`.

### Status

14/14 tasks in this batch (Phases 2–4) complete. Full suite: 628/628 passing (563 Batch-1 baseline + 65 new). Ready for the next batch (Phase 5: `onenote_search` tool).

---

## Batch 3 — Phase 5: `onenote_search` tool; Phase 6: `onenote_get_page` tool; Phase 7: Write-path allowlist + settings; Phase 8: `onenote_create_page` / `onenote_update_page` tools

**Mode**: Strict TDD

### Completed Tasks

- [x] 5.1 RED `tests/test_onenote_tools.py`: matches returned; empty query rejected pre-adapter; zero matches -> `[]`; default limit 50; oversized limit clamped to 200; unavailable -> tool error
- [x] 5.2 GREEN `tools/onenote.py`: `onenote_search(request, adapter)`; add `onenote_search_max_results()` to `settings.py`
- [x] 6.1 RED `tests/test_onenote_tools.py`: successful fetch; unknown id -> `onenote_page_not_found`; empty body -> `""` not error; unavailable -> tool error; repeated fetch non-mutating
- [x] 6.2 GREEN `tools/onenote.py`: implement `onenote_get_page`
- [x] 7.1 RED `tests/test_settings.py`: `onenote_writable_notebooks()` defaults to `["z - Test Notebook"]` absent; reads configured list otherwise
- [x] 7.2 GREEN `tools/settings.py`: `onenote_writable_notebooks()`, `onenote_search_max_results()` (default 50), `onenote_ps_bridge_timeout_seconds()` (default 20); document keys in settings.yaml
- [x] 7.3 RED `tests/test_onenote_tools.py`: write to default test notebook succeeds; write to a live notebook refused pre-adapter; configured allowlist widens writable set
- [x] 7.4 GREEN `tools/onenote.py`: allowlist helper — `get_hierarchy()`, check notebook vs `onenote_writable_notebooks()`, raise `OneNoteWriteNotAllowedError` pre-write
- [x] 8.1 RED `tests/test_onenote_tools.py`: create returns `PageDetail` with new `pageId`; create unavailable -> tool error; matching date update succeeds; stale date -> `onenote_page_conflict`, no write recorded
- [x] 8.2 GREEN `tools/onenote.py`: `onenote_create_page`/`onenote_update_page`, using Phase 7's allowlist check

### Files Changed

| File | Action | What Was Done |
|------|--------|----------------|
| `tools/onenote.py` | Created | `onenote_search(request, adapter)`: rejects empty `query` with `ValueError` before any adapter call, resolves `limit` via `onenote_search_max_results()`, delegates to `adapter.search(query, limit)`. `onenote_get_page(request, adapter)`: single read-only `adapter.get_page(page_id)` call, no extra logic. `_check_writable(notebook_name)`: raises `OneNoteWriteNotAllowedError` (carrying `notebook_name`/`allowed_notebooks`) when `notebook_name` is not in `onenote_writable_notebooks()`. `_resolve_notebook_for_section(adapter, section_id)`: walks `adapter.get_hierarchy()` to find `section_id`'s owning notebook name, raising `OneNoteSectionNotFoundError` on a miss — this is the tool-layer resolution design.md's "Allowlist enforcement point" decision calls for (a read call BEFORE the allowlist check/write). `onenote_create_page(request, adapter)`: resolves the target section's notebook via `_resolve_notebook_for_section`, checks it against the allowlist, THEN calls `adapter.create_page(section_id, title, body_text)`. `onenote_update_page(request, adapter)`: calls `adapter.get_page(page_id)` first (a read — this also naturally surfaces `OneNotePageNotFoundError` for an unresolved `pageId` before any write), checks the returned `PageDetail.notebook_name` against the allowlist, THEN calls `adapter.update_page(page_id, body_text, expected_last_modified)` with the caller's date passed through verbatim. |
| `tools/settings.py` | Modified | Added `onenote_writable_notebooks()` (reads `onenote_writable_notebooks` from `config/settings.yaml`, default exactly `["z - Test Notebook"]` when absent/empty), `onenote_search_max_results(limit)` (mirrors `resolve_search_limit()`'s default/clamp/reject contract: `limit=None` -> configured `onenote_search_max_results` key, default `50`; `limit > 200` clamped to the fixed `200` ceiling; `limit <= 0` raises `ValueError`), `onenote_ps_bridge_timeout_seconds()` (reads `onenote_ps_bridge_timeout_seconds`, default `20`). All three read live via `load_settings()` every call — never cached, matching every other reader in this module. |
| `tools/onenote_adapter.py` | Modified | Removed the Batch 2 `_DEFAULT_TIMEOUT_SECONDS = 20.0` module-constant placeholder and its docstring note; `OneNoteAdapter._invoke()` now calls `onenote_ps_bridge_timeout_seconds()` (imported from `tools.settings`) live on every invocation instead, closing out Batch 2's own deviation note. No other change to `onenote_adapter.py`. |
| `config/settings.yaml` | Modified | Added `onenote_writable_notebooks: ['z - Test Notebook']`, `onenote_search_max_results: 50`, `onenote_ps_bridge_timeout_seconds: 20`, each with a doc comment in the file's existing header-comment style. |
| `tests/test_onenote_tools.py` | Created | 23 tests: Phase 5 (7 — matching-pages search across two notebooks, empty-query rejection with adapter-not-called spy, no-matches empty list, default-limit-50 against 80 seeded pages, oversized-limit clamped-to-200 asserted via `mocker.spy(adapter, "search")`, zero-limit rejection, unavailable -> `OneNoteUnavailableError`); Phase 6 (5 — successful fetch field-by-field, unknown id -> `OneNotePageNotFoundError`, empty body -> `""` not an error, unavailable -> tool error, two repeated fetches equal + `create_page`/`update_page` spies never called); Phase 7/8 combined (11 — create to default test notebook succeeds with an exact positional-args spy assertion, create to a live notebook refused with `create_page` spy never called + `excinfo.value.notebook_name` asserted, configured allowlist widening via `mocker.patch("tools.onenote.onenote_writable_notebooks", ...)`, unknown `sectionId` -> `OneNoteSectionNotFoundError`, create returns a real `PageDetail` with matching title/body, create-unavailable -> tool error, update with matching date succeeds and returns the new body, update with a stale date raises `OneNotePageConflictError` AND the fake adapter's seeded page is confirmed unchanged afterward, update to a live notebook refused with `update_page` spy never called, update of an unknown `pageId` -> `OneNotePageNotFoundError`, update-unavailable -> tool error). |
| `tests/test_settings.py` | Modified | Added 10 new tests: `onenote_writable_notebooks()` (default, configured-list); `onenote_search_max_results()` (default-50-when-none, configured-default, clamp-to-200, pass-through-under-max, reject-zero, reject-negative — 6 tests, mirroring `resolve_search_limit()`'s existing test shape exactly); `onenote_ps_bridge_timeout_seconds()` (default-20, configured value). |
| `openspec/changes/add-onenote-adapter/tasks.md` | Modified | Checked off 5.1–5.2, 6.1–6.2, 7.1–7.4, 8.1–8.2 |

### TDD Cycle Evidence

| Task | Test File | Layer | Safety Net | RED | GREEN | TRIANGULATE | REFACTOR |
|------|-----------|-------|------------|-----|-------|-------------|----------|
| 5.1/5.2 | `tests/test_onenote_tools.py` (search tests) + `tests/test_settings.py` (`onenote_search_max_results` tests) | Unit (`FakeOneNoteAdapter`, no I/O; pure settings function) | ✅ 628/628 passing at batch start | ✅ Written — confirmed genuine RED (`ModuleNotFoundError: No module named 'tools.onenote'` / `ImportError: cannot import name 'onenote_ps_bridge_timeout_seconds'`) before writing `tools/onenote.py` or any new `tools/settings.py` function | ✅ All 7 search tests + all 6 `onenote_search_max_results` tests passing on the first implementation attempt | ✅ 7 search cases (matches/empty-query/no-match/default-limit/oversized-limit/zero-limit/unavailable) + 6 settings cases (default-none/configured-default/clamp/pass-through/reject-zero/reject-negative) | ➖ None needed — both implementations were already the simplest correct form on first pass |
| 6.1/6.2 | `tests/test_onenote_tools.py` (get_page tests) | Unit (`FakeOneNoteAdapter`) | ✅ (covered above — same batch-start baseline) | ✅ Written — same RED collection failure as 5.1 covered `onenote_get_page` too (single `ModuleNotFoundError` for the whole new module) | ✅ 5/5 get_page tests passing on the first implementation attempt | ✅ 5 cases (successful fetch, unknown id, empty body, unavailable, non-mutating repeat) | ➖ None needed — `onenote_get_page` is a single-line passthrough, nothing to simplify |
| 7.1/7.2 | `tests/test_settings.py` (`onenote_writable_notebooks` tests) | Unit (pure settings function) | ✅ (covered above) | ✅ Written — confirmed genuine RED (`ImportError: cannot import name 'onenote_writable_notebooks'`) before adding the function | ✅ 2/2 passing on the first implementation attempt | ✅ 2 cases (default-when-absent, configured-list) — the minimum the spec/tasks.md describe; no further branching exists to triangulate | ➖ None needed |
| 7.3/7.4 | `tests/test_onenote_tools.py` (allowlist tests within create_page/update_page) | Unit (`FakeOneNoteAdapter` + `mocker.spy`) | ✅ (covered above) | ✅ Written together with 8.1 in the same edit pass (the allowlist check and the create/update tools share one `tools/onenote.py` file and cannot be meaningfully split into separate RED commits) — confirmed genuine RED via the same `ModuleNotFoundError` | ✅ Passing (same run as 8.1/8.2 below) | ✅ 3 dedicated allowlist cases (default test notebook succeeds, live notebook refused pre-write with a not-called spy + `notebook_name` assertion, configured allowlist widened via a direct `mocker.patch` on `onenote_writable_notebooks`) plus the unknown-section case | ➖ None needed |
| 8.1/8.2 | `tests/test_onenote_tools.py` (create_page/update_page tests) | Unit (`FakeOneNoteAdapter` + `mocker.spy`) | ✅ (covered above) | ✅ Written — confirmed genuine RED (`ModuleNotFoundError`, same collection failure) before writing `onenote_create_page`/`onenote_update_page` | ✅ All 11 Phase-7/8 tests passing on the first implementation attempt (23/23 in the whole new test file, 93/93 across the four touched test files) | ✅ 11 cases across create (default-notebook, live-notebook-refused, allowlist-widened, unknown-section, returns-new-page, unavailable) and update (matching-date-succeeds, stale-date-conflict-with-unchanged-seed-assertion, live-notebook-refused, unknown-id, unavailable) | ➖ None needed — implementation was already the simplest correct form on first pass |

### Test Summary

- **Total tests written this batch**: 23 (`tests/test_onenote_tools.py`) + 10 (`tests/test_settings.py`) = 33
- **Total tests passing (full suite)**: 661/661 (`source .venv/bin/activate && python3.12 -m pytest -q`)
- **Layers used**: Unit (33 — `FakeOneNoteAdapter`-backed tool tests plus pure `tools/settings.py` function tests) — no integration/E2E layer applicable to this batch
- **Approval tests** (refactoring): none — this batch is pure addition to `tools/settings.py`/new `tools/onenote.py`, plus one small, test-covered change to `tools/onenote_adapter.py` (`_DEFAULT_TIMEOUT_SECONDS` constant -> live `onenote_ps_bridge_timeout_seconds()` read); `tests/test_onenote_adapter.py`'s existing 23/23 passed unmodified both before and after that change (its only timeout-related assertion, `"timeout" in kwargs`, does not pin an exact value)
- **Pure functions created**: `_check_writable`, `_resolve_notebook_for_section` (both pure given their `adapter`/settings-reader inputs, in `tools/onenote.py`); `onenote_writable_notebooks`, `onenote_search_max_results`, `onenote_ps_bridge_timeout_seconds` (all pure given `load_settings()`'s return value, in `tools/settings.py`)

### Deviations from Design

1. **`onenote_search_max_results(limit)` takes a `limit` argument and resolves BOTH the default (`50`) and the hard clamp (`200`), mirroring `resolve_search_limit()`'s full contract — not a bare no-arg config reader like `file_search_max_results()`.** design.md's File Changes table lists only one new onenote-search settings entry, `onenote_search_max_results (default 50)`, worded as if it were a single plain value the way `file_search_max_results` is (a bare `TOP n` cap, no default/max split, no function argument). But the onenote-search spec's own "Result Limit Parameter" requirement is explicit that BOTH a default (`50`, applied when `limit` is omitted) AND a separately-clamped hard maximum (`200`, applied when `limit` exceeds it) are required, "mirroring `mail_search`'s cap convention" — and `mail_search`'s convention (`resolve_search_limit()`) is exactly a `(limit: int | None) -> int` function, not a bare reader. tasks.md 5.2 also phrases it as `onenote_search_max_results()` used directly by `tools/onenote.py`'s `onenote_search`, with no separate "default" function ever introduced elsewhere. Followed the spec's two-number requirement (more concrete and directly tested by tasks.md 5.1's own RED-test description: "default limit 50; oversized limit clamped to 200") over design.md's single-entry File Changes shorthand: the function treats the ONE configured key (`onenote_search_max_results`, default `50`) as the *default-when-omitted* value, and treats `200` as a fixed, not-independently-configurable ceiling — i.e. the function's own config key controls the "50" half of the spec's contract, while the "200" half is a hardcoded constant matching `mail_search`'s own hard max. This is a deliberately narrower surface than a full `search_default_limit`/`search_max_limit` pair (no second onenote-specific yaml key for the ceiling) since neither design.md nor tasks.md ever asks for the ceiling itself to be configurable.
2. **The onenote-write-page spec's allowlist scenarios say "target section" for BOTH `onenote_create_page` and `onenote_update_page`, but `UpdatePageRequest` only carries `pageId` (Phase 2, already shipped) — never a `sectionId`.** `onenote_update_page`'s notebook resolution therefore cannot mirror `onenote_create_page`'s `get_hierarchy()`-based section lookup verbatim; it instead calls `adapter.get_page(request.page_id)` (a read, already needed to surface `OneNotePageNotFoundError` per the onenote-get-page spec's precedent) and reads `PageDetail.notebook_name` directly — a field that has existed since Phase 2 for exactly this reason (see `models/schemas.py::PageSummary.notebook_name`'s docstring). This is the only implementation consistent with the schemas actually shipped; test-covered by `test_update_page_to_live_notebook_refused_before_adapter_call`, which seeds a `PageDetail` with `notebook_name="Informa - Proyectos"` directly (no hierarchy fixture involved) and asserts `adapter.update_page` is never called.
3. **`onenote_create_page`'s own tool-layer section resolution (`_resolve_notebook_for_section`) raises `OneNoteSectionNotFoundError` for an unresolved `sectionId` BEFORE `FakeOneNoteAdapter.create_page()`'s own identical check (Batch 2) ever runs.** This was already flagged as an open deviation in Batch 2 (deviation note #6): the adapter-level check now never actually fires in practice for a request routed through `onenote_create_page`, since the tool layer's resolution (needed for the allowlist decision regardless) always runs first and raises first on a miss. Both checks are harmless to leave in place — the adapter-level one is still exercised directly by `tests/test_fake_onenote_adapter.py` (Batch 2, unmodified) for callers that bypass the tool layer entirely, e.g. a future direct-adapter test or a differently-shaped caller — but no test in this batch exercises the adapter's own check via the tool-layer path, since the tool-layer check always wins the race.
4. **No `tests/test_onenote_tools.py` "Phase 7" tests exist as a physically separate RED commit from "Phase 8"** — tasks.md numbers the allowlist scenarios (7.3/7.4) and the create/update scenarios (8.1/8.2) separately, but they live in the same `tools/onenote.py` functions (`onenote_create_page`/`onenote_update_page` ARE the allowlist enforcement point — there is no standalone "allowlist tool" to test in isolation) and were written/implemented together in one RED-then-GREEN pass. Both phases' task checkboxes are marked complete; the TDD Cycle Evidence table above documents 7.3/7.4 and 8.1/8.2 as a shared RED/GREEN cycle rather than fabricating an artificial separation.

No other deviations. `tools/onenote_adapter.py`'s five adapter methods (`search`/`get_hierarchy`/`get_page`/`create_page`/`update_page`), `tools/fake_onenote_adapter.py`, `models/schemas.py`, `tools/errors.py`, `tools/ps_bridge_transport.py`, `tools/file_search_adapter.py` are all unchanged this batch (confirmed: `tests/test_onenote_adapter.py` 23/23, `tests/test_fake_onenote_adapter.py` 17/17, `tests/test_file_search_adapter.py` 87/87 — all still passing, none of those three files edited).

### Issues Found

None.

### Remaining Tasks (this change)

- [ ] Phase 9: Server Wiring
- [ ] Phase 10: Full Suite & Docs
- [ ] Phase 11: Manual Verification (Windows host, not CI)

### Test Runner Note

Same as Batches 1/2: `python3.12 -m pytest -q` fails on this host's bare `/usr/bin/python3.12` (no pytest installed there) — every test run in this batch used `source .venv/bin/activate && python3.12 -m pytest -q`, which resolves `python3.12` to `.venv/bin/python3.12`.

### Status

10/10 tasks in this batch (Phases 5–8) complete. Full suite: 661/661 passing (628 Batch-1/2 baseline + 33 new). Ready for the next batch (Phase 9: Server Wiring).

---

## Batch 4 — Phase 9: Server Wiring; Phase 10: Full Suite & Docs

**Mode**: Strict TDD

### Completed Tasks

- [x] 9.1 RED `tests/test_server.py`: import succeeds without win32com/powershell; 4 tools registered; bridge-unavailable -> clear error, no crash
- [x] 9.2 GREEN `server.py`: register 4 tools, `_resolve_real_onenote_adapter()` (lazy); `_map_error()` unchanged, new errors subclass `CalendarToolError`
- [x] 10.1 Run `python3.12 -m pytest -q`, full suite green including unmodified `test_file_search_adapter.py`, fix regressions; update `README.md`: OneNote tools, allowlist, WSL2 fake-adapter notes

### Files Changed

| File | Action | What Was Done |
|------|--------|----------------|
| `server.py` | Modified | Added `CreatePageRequest`/`GetPageRequest`/`OneNoteSearchRequest`/`PageDetail`/`PageSummary`/`UpdatePageRequest` to the `models.schemas` import block (alphabetically merged); `from tools.onenote import (onenote_create_page, onenote_get_page, onenote_search, onenote_update_page)`; `from tools.onenote_adapter import OneNotePort`. Added `_lazy_real_onenote_adapter: OneNotePort \| None = None` alongside the other three lazy-adapter globals, and `_resolve_real_onenote_adapter()` mirroring `_resolve_real_file_search_adapter()`'s shape (builds/caches a real `OneNoteAdapter()` on first use, imported lazily inside the function — though `OneNoteAdapter` never imports `win32com` at all, unlike the other three real adapters). `create_server()` gained a fifth `onenote_adapter: OneNotePort \| None = None` parameter and a matching `_onenote_adapter()` closure. Registered four new `@app.tool`s at the end of `create_server()`, before `return app`: `onenote_search` (`query`/optional `limit` -> `list[PageSummary]`, catches `(CalendarToolError, ValueError)` since empty-query rejection raises a plain `ValueError`), `onenote_get_page` (`pageId` alias -> `PageDetail`, catches `CalendarToolError` only), `onenote_create_page` (`sectionId`/`title`/`bodyText` aliases -> `PageDetail`, `CalendarToolError` only), `onenote_update_page` (`pageId`/`bodyText`/`dateExpectedLastModified` aliases -> `PageDetail`, `CalendarToolError` only) — each builds its request model then delegates to the matching `tools.onenote` function via `_onenote_adapter()`, identical shape to every existing tool registration. Updated the module docstring to mention the four new tools and OneNote's win32com-free bridge. |
| `tests/test_server.py` | Modified | Added `_ALL_TOOL_NAMES` (13-name set) and replaced the four pre-existing exact-tool-set assertions (`test_all_three_tools_registered`, `test_task_tools_registered`, `test_mail_tools_registered`, `test_file_search_tools_registered_via_fake_file_search_adapter`) with `assert names == _ALL_TOOL_NAMES` — each of those tests registers every tool unconditionally regardless of which fakes are injected (registration doesn't call the adapter), so their old 9-name literal sets would have failed once 4 more tools existed; this is the same widening every prior tool-adding phase (task/mail/file-search) already needed and did to these same four tests. Added `test_import_succeeds_without_win32com`'s new assertion that `"tools.onenote_adapter" in sys.modules`. Added 10 new tests: `test_onenote_tools_registered_via_fake_onenote_adapter`, `test_onenote_search_tool_returns_results_via_fake_onenote_adapter`, `test_onenote_search_tool_empty_query_surfaces_invalid_request_tool_error`, `test_onenote_get_page_tool_returns_detail_via_fake_onenote_adapter`, `test_onenote_get_page_tool_unknown_id_surfaces_page_not_found_error`, `test_onenote_create_page_tool_returns_new_page_via_fake_onenote_adapter`, `test_onenote_create_page_tool_live_notebook_refused_surfaces_tool_error`, `test_onenote_update_page_tool_matching_date_succeeds`, `test_onenote_update_page_tool_stale_date_surfaces_conflict_error`, `test_onenote_adapter_selection_deferred_when_bridge_unavailable` (the last one calls `create_server()` with no `onenote_adapter` injected, letting the real `OneNoteAdapter`'s `PsBridgeTransport.invoke()` genuinely fail to spawn `powershell.exe` on this WSL2 host — the real-world "bridge unavailable" condition, no mocking needed, mirroring how the win32com-unavailable tests work for the other adapters but without needing to pop anything from `sys.modules` since `OneNoteAdapter` never imports `win32com`). |
| `tests/test_smoke_test.py` | Modified | `test_expected_tools_matches_server_registered_names` (a full-suite regression this batch's server.py change surfaced, unrelated to this change's own tasks.md but required to keep the suite green): added `FakeOneNoteAdapter` import and `onenote_adapter=FakeOneNoteAdapter(pages=[])` to the `create_server()` call, since `EXPECTED_TOOLS` (from `deploy/smoke_test.py`) must equal the server's full registered set. |
| `deploy/smoke_test.py` | Modified | Added the 4 OneNote tool names to `EXPECTED_TOOLS` (13 total), fixing the regression above at its source. Added a doc comment explaining that OneNote is deliberately NOT added as a live `FAMILIES` entry in this script — its write tools touch real notebook content, so live round-trip verification stays manual (tasks.md Phase 11), unlike the always-safe-to-read Outlook/file-search families this script already automates. |
| `make-deploy-package.sh` | Modified | Added `tools/ps_bridge_onenote.ps1` to `MANIFEST` (mirroring the existing `tools/ps_bridge_search.ps1` entry) — this runtime asset (spawned by `OneNoteAdapter` via the shared `PsBridgeTransport`) would otherwise be silently missing from the deployed package despite `tools/*.py` being discovered dynamically, since a bare `.ps1` isn't picked up by that glob. Extended gate 4's pure-ASCII check (Windows PowerShell 5.1 mis-parses non-ASCII under the ANSI/CP1252 fallback) to loop over both `.ps1` bridge scripts instead of hardcoding just the search one; verified `tools/ps_bridge_onenote.ps1` is already pure ASCII. Not in design.md's File Changes table or tasks.md, but required for the shipped feature to actually work — the design's own Decision 3 ("one file copied per install... matches existing `tools/*.ps1` deployment") implies this script must be staged the same way `ps_bridge_search.ps1` already is. |
| `README.md` | Modified | "nine tools"→"thirteen tools" (3 occurrences) plus 4 new tool bullets in the intro; new bullet in "Platform requirement" explaining OneNote's win32com-free PowerShell/COM bridge and the classic-desktop-OneNote-app requirement; tool list updated in the packaged-install step 7 and the manual-install closing line; 3 new `config/settings.yaml` keys documented in "Configuration" (`onenote_writable_notebooks`, `onenote_search_max_results`, `onenote_ps_bridge_timeout_seconds`) plus `tools/onenote_adapter.py`/`tools/onenote.py` added to the "every key is live" paragraph; `FakeOneNoteAdapter` and the new OneNote test files added to "Development (WSL2/Linux)"; "Manual smoke test" intro/step-3 tool list updated, plus 5 new manual verification steps (11-15: search/get_page live, create+update round-trip in the default test notebook, a live-notebook write refusal, a stale-date conflict, and a bridge-unavailable check) since `deploy/smoke_test.py` deliberately doesn't automate OneNote; new "Known limitations" bullet covering the COM/PowerShell dependency, the writable-notebook allowlist, the append-not-replace update semantics (design.md Decision 8), the plain-text-only/`]]>`-edge-case limitations (design.md's Open Questions), and the no-smoke-test-coverage note; "Possible extensions" gained OneNote-specific follow-on ideas and a corrected closing paragraph — OneNote was previously (inaccurately, now that it's implemented) grouped with "things that need the Microsoft Graph API"; it's now called out as reachable locally via COM, unlike Teams/OneDrive/full To-Do. |

### TDD Cycle Evidence

| Task | Test File | Layer | Safety Net | RED | GREEN | TRIANGULATE | REFACTOR |
|------|-----------|-------|------------|-----|-------|-------------|----------|
| 9.1/9.2 | `tests/test_server.py` | Integration (FastMCP in-process `Client` against `FakeOneNoteAdapter`/the real lazily-resolved adapter) | ✅ 661/661 passing at batch start (confirmed via full-suite run before touching `server.py`) | ✅ Written — confirmed genuine RED (14 failures: the 4 widened exact-set assertions plus all 10 new onenote tests, all failing on "Unknown tool"/`AssertionError` for the missing tools/param, none on a collection error) before touching `server.py` | ✅ 44/44 in `tests/test_server.py` passing after registering the 4 tools + `_resolve_real_onenote_adapter()`/`onenote_adapter` param | ✅ 10 new test cases across all 4 tools (registration, successful search/get/create/update, empty-query rejection, unknown-pageId, live-notebook-refused, stale-date-conflict, bridge-unavailable) — the full set of scenarios task 9.1 asks for (import safety, 4-tools-registered, bridge-unavailable) plus the per-tool wiring the design's Interfaces/Contracts and the four tool specs require | ✅ None needed beyond what GREEN already produced — each tool registration is a thin, uniform wrapper matching every existing tool's exact shape; no duplication to extract |

### Test Summary

- **Total tests written this batch**: 10 (`tests/test_server.py`) — plus 1 existing test modified (not counted as "written"), not counting the 4 widened assertions (pre-existing tests, not new)
- **Total tests passing (full suite)**: 671/671 (`source .venv/bin/activate && python3.12 -m pytest -q`)
- **Layers used**: Integration (10 — FastMCP in-process `Client` end-to-end through `server.py` -> `tools/onenote.py` -> `FakeOneNoteAdapter`/real lazily-resolved `OneNoteAdapter`) — no new unit-layer tests this batch (Phases 1-8 already covered every layer below `server.py`)
- **Approval tests** (refactoring): the 4 widened exact-tool-set assertions functioned as approval tests for the pre-existing registration tests — confirmed each still passes with the wider 13-name set, proving the OLD 9 tools are still registered unchanged, only the assertion's own expected set needed widening (same precedent as every prior tool-adding phase)
- **Pure functions created**: none this batch — `server.py`'s new code is entirely thin `@app.tool` wrappers + one lazy-resolver function, matching the file's existing style (no new pure logic; all real logic lives in `tools/onenote.py`, shipped in Batch 3)

### Deviations from Design

1. **`onenote_search`'s server-layer tool catches `(CalendarToolError, ValueError)`, while `onenote_get_page`/`onenote_create_page`/`onenote_update_page` catch `CalendarToolError` only.** design.md's File Changes table just says "register 4 tools" with no per-tool exception-handling detail. Followed the established precedent split already visible in every other tool registration in this file: a tool whose underlying `tools/*.py` function can raise a plain `ValueError` pre-adapter (here, `onenote_search`'s empty-query rejection, tools/onenote.py's `if not request.query: raise ValueError(...)`, shipped in Batch 3) catches `(CalendarToolError, ValueError)` (same as `calendar_search`/`task_search`/`mail_search`/`file_search`); a tool whose function only ever raises the typed `CalendarToolError` taxonomy (here, `onenote_get_page`/`onenote_create_page`/`onenote_update_page` — none of `tools/onenote.py`'s corresponding functions raise a bare `ValueError`) catches `CalendarToolError` only (same as `calendar_get_event`/`mail_get_message`/`file_get_info`).
2. **`tests/test_smoke_test.py`/`deploy/smoke_test.py` and `make-deploy-package.sh` changes are outside tasks.md's Phase 9/10 wording** (neither file is named in tasks.md, design.md's File Changes table, or the proposal's Affected Areas table). Made anyway because: (a) `EXPECTED_TOOLS`/`test_expected_tools_matches_server_registered_names` is a real regression task 10.1 explicitly says to "fix" (it's part of "the full suite"), and (b) `make-deploy-package.sh` not staging `tools/ps_bridge_onenote.ps1` would silently ship a broken OneNote feature to production (the real adapter would fail every call with a `FileNotFoundError`-derived `OneNoteUnavailableError`, invisible until Phase 11's manual Windows verification) — a correctness gap directly caused by this change's own Phase 4 deliverable, not a pre-existing issue. Neither change touches Phase 11 itself (no deploy script was *run*, only the packaging *manifest source* was corrected) and neither required Strict-TDD RED/GREEN cycling (a bash manifest array and a Python set literal, not testable production logic in the TDD sense) — the correctness of both was verified by direct inspection (`bash -n make-deploy-package.sh`, `LC_ALL=C grep` ASCII check, and the full pytest run going green) rather than a new unit test.
3. **`deploy/smoke_test.py`'s `FAMILIES` tuple/live verification is deliberately NOT extended with an OneNote entry** (documented in-line in that file and in README's "Known limitations"). tasks.md's Phase 11 already assigns OneNote's live verification to a separate, explicit manual step (`deploy-qa.sh` + hand-verification of search/get_page/writable-allowlist), distinct from this script's automated `tools/list` + read-only round-trip families — and unlike every existing family, OneNote's write tools have real side effects on live notebook content, so folding them into this script's unattended automated run was a deliberate scope call, not an oversight.

No other deviations. `tools/onenote.py`/`tools/onenote_adapter.py`/`tools/fake_onenote_adapter.py`/`models/schemas.py`/`tools/errors.py`/`tools/settings.py`/`config/settings.yaml` (Batches 1-3) are all unchanged this batch (confirmed: `tests/test_onenote_tools.py` 33/33, `tests/test_onenote_adapter.py` 23/23, `tests/test_fake_onenote_adapter.py` 17/17, `tests/test_file_search_adapter.py` 87/87 — all still passing, none of those files edited).

### Issues Found

None.

### Remaining Tasks (this change)

- [ ] Phase 11: Manual Verification (Windows host, not CI) — `11.1` **[MANUAL — user-run]**, explicitly out of scope for this batch and every prior one.

### Test Runner Note

Same as Batches 1-3: `python3.12 -m pytest -q` fails on this host's bare `/usr/bin/python3.12` (no pytest installed there) — every test run in this batch used `source .venv/bin/activate && python3.12 -m pytest -q`, which resolves `python3.12` to `.venv/bin/python3.12`.

### Status

All automated tasks for `add-onenote-adapter` complete: Phases 1-10, 47/47 tasks. Full suite: 671/671 passing (661 Batch-1/2/3 baseline + 10 new). Only Phase 11 (11.1, manual/user-run on a real Windows host) remains — not runnable from this WSL2 session.

---

## Batch 5 — Phase 11 Executed (Live MCP Driver from WSL) + Documentation Reconciliation

**Mode**: Strict TDD (for the 4 live-only defects fixed below, unit-testable); documentation-only for this batch's own file edits (`apply-progress.md`/`tasks.md`/`design.md`/`README.md` — no production code touched by this batch itself)

**Date**: 2026-08-27

### What Happened

Phase 11 (task 11.1) was executed — not by a human clicking through Claude
Desktop, but by a real MCP stdio driver script run from WSL against the
already-deployed QA instance at `C:\usr\WinMCP-qa` (the driver preserves
this session's own scratchpad path plus a copy at
`C:\usr\WinMCP-qa\_qa_onenote_live.py`). The driver speaks the real MCP
stdio protocol end-to-end (handshake, `tools/list`, `tools/call`) against
the live, deployed server process — not a fake adapter, not an in-process
`fastmcp.Client`.

This surfaced **4 live-only defects** — bugs invisible to every mocked/fake
unit and integration test in Batches 1-4, because each one depends on a
real `powershell.exe` child, real COM, real non-ASCII bytes on the wire, or
real wall-clock timestamp round-tripping, none of which any WSL2-side test
double can reproduce. All 4 were fixed strict-TDD where unit-testable (full
suite went 671 -> 674: 3 new tests), then the fixes were re-verified live.

**Final live QA run: 8/8 PASS** — handshake, the 13-tool `tools/list`,
`onenote_search`, `onenote_get_page`, `onenote_create_page` (in
`"z - Test Notebook"`), `onenote_update_page` (honest, non-`MinValue`
append), a deliberately stale timestamp correctly surfacing
`onenote_page_conflict`, and a write attempt against the live
`"Informa - Governance"` notebook correctly refused with
`onenote_notebook_not_allowed`.

Also run this batch: the full `deploy/smoke_test.py` PASSED post-refactor
(confirming the stream-encoding fix below didn't regress the pre-existing
Outlook/file-search families), and a dedicated accented-filename probe
confirmed `file_search`'s bridge now emits clean UTF-8 end-to-end (the
latent file-search mojibake bug fixed as a side effect of defect #1 below).

### The 4 Live-Only Defects and Fixes

1. **Stream-encoding truncation (both bridges).** Both `.ps1` bridge
   scripts emitted stdout in the Windows console's OEM codepage; the
   transport's child-process read used `text=True` with no explicit
   `encoding=`, so Python decoded the bytes using the *host's own locale*
   — which silently died (or truncated the JSON-Lines stream) at the first
   accented byte. **Fix**: both `tools/ps_bridge_search.ps1` and
   `tools/ps_bridge_onenote.ps1` now pin
   `[Console]::OutputEncoding` to a no-BOM UTF-8 encoding at startup;
   `tools/ps_bridge_transport.py`'s child-process invocation now passes
   `encoding="utf-8", errors="replace"` explicitly instead of relying on
   locale defaults (new test:
   `test_invoke_decodes_child_streams_as_utf8_with_replace`, in
   `tests/test_ps_bridge_transport.py`). This also fixed a latent
   `file_search` accent-mojibake bug as a side effect (same shared
   transport, same fix) — confirmed live this batch via the accented-
   filename probe above.
2. **`ConvertTo-IsoStringOrNull` called `.ToString("o")` on XML attribute
   *strings*, not `DateTime` objects** — every `FindPages`/`GetPageContent`
   row silently failed with "Cannot find an overload" and was skipped,
   so `onenote_search`/`onenote_get_page` returned incomplete or empty
   results live despite working against every mocked unit test. **Fix**:
   `ConvertTo-IsoStringOrNull` (both `.ps1` bridge scripts) now parses the
   incoming string with `[DateTime]::Parse($value, [CultureInfo]::InvariantCulture,
   [DateTimeStyles]::RoundtripKind)`, passing the resulting real `DateTime`
   through `.ToString("o")`; returns `$null` on an empty or unparseable
   value instead of throwing.
3. **Optimistic-concurrency timezone bug — design.md's Open Question now
   RESOLVED with live evidence.** The exact HRESULT a stale
   `dateExpectedLastModified` makes real COM's `UpdatePageContent` throw is
   **`0x80042010`** (`hrLastModifiedDateDidNotMatch`), confirmed live
   2026-08-27 (new test:
   `test_update_page_com_hresult_0x80042010_raises_page_conflict`, in
   `tests/test_onenote_adapter.py` — `tools/onenote_adapter.py`'s
   `_CONFLICT_MARKERS` now includes the literal `"0x80042010"` substring).
   The deeper root cause of *every* honest (non-`MinValue`) update
   conflicting live, even with a genuinely fresh timestamp: Python sent
   `expected_last_modified.isoformat()`, which renders a UTC-aware
   `datetime` as `"...+00:00"` — and .NET's own `RoundtripKind` parser
   *adjusts* a `+00:00`-suffixed string to the parsing machine's **local**
   time zone (unlike a bare `"Z"` suffix, which `RoundtripKind` leaves as
   unadjusted UTC per the DateTimeStyles contract). On any non-UTC Windows
   host this shifted the comparison value by the host's UTC offset,
   guaranteeing a spurious conflict on every single write. **Fix**:
   `tools/onenote_adapter.py` gained `_to_utc_z(value: datetime) -> str`,
   which always renders a `Z`-suffixed UTC string
   (`value.astimezone(timezone.utc).strftime(...) + "Z"`, never `+00:00`)
   and is now used for every wire-format date `OneNoteAdapter.update_page()`
   sends (2 new tests: the HRESULT test above plus
   `test_update_page_converts_non_utc_expected_to_utc_z`, covering a
   non-UTC-zone input converting correctly). `ps_bridge_onenote.ps1`'s own
   `ConvertTo-IsoStringOrNull`-based date parsing (defense in depth) now
   also explicitly calls `.ToUniversalTime()` after the `RoundtripKind`
   parse on both sides of its own comparison, so it no longer matters
   which of `Z`/`+00:00` a caller sends — but the Python-side fix is the
   one that actually closes the bug for this codebase's own adapter.
4. **`UpdatePageContent` preserved a stale `lastModifiedTime` attribute
   present in the XML being posted back**, because the fetched page XML
   (used as the basis for the write) still carried its own
   `lastModifiedTime` attribute from the READ — posting that unmodified
   attribute back froze the page's reported timestamp at its pre-update
   value, which defeated conflict detection for any *subsequent* write
   (a second stale-date test would have wrongly succeeded, since the
   "current" timestamp COM reported never advanced). **Fix**: both
   `CreateNewPage` and `UpdatePageContent` in `ps_bridge_onenote.ps1` now
   strip any `lastModifiedTime` attribute from the outgoing page XML
   before calling COM, letting OneNote stamp its own fresh value.

### Known Limitation Discovered (Live-Only, Now Documented)

OneNote stamps a page's `lastModifiedTime` **lazily**, at its own internal
background save, not synchronously with `UpdatePageContent` returning —
live-confirmed this batch: the COM-visible timestamp stayed unchanged for
15+ seconds after a write actually landed. **Consequence**: a second write
issued within that save-latency window is undetectable by *any*
timestamp-based conflict check, including OneNote's own native COM check
(HRESULT `0x80042010`) — the conflict guard implemented here is correctly
reliable for genuinely stale timestamps (seconds-to-minutes old, the
realistic collision case for an LLM-driven tool), but is blind to
true-concurrent writes landing within OneNote's own save latency. This is
now documented in `design.md` (Decision 9 addendum) and `README.md`
("Known limitations").

### Files Changed (production code — landed prior to this batch, verified present; recorded here for the trail)

| File | What Was Done |
|------|----------------|
| `tools/ps_bridge_search.ps1` | Pinned `[Console]::OutputEncoding` to no-BOM UTF-8 at script startup |
| `tools/ps_bridge_onenote.ps1` | Pinned `[Console]::OutputEncoding` to no-BOM UTF-8 at script startup; `ConvertTo-IsoStringOrNull` now parses strings with InvariantCulture+RoundtripKind instead of calling `.ToString("o")` on a raw string; both `CreateNewPage`/`UpdatePageContent` strip any incoming `lastModifiedTime` attribute before posting XML to COM; date comparisons additionally call `.ToUniversalTime()` after parsing |
| `tools/ps_bridge_transport.py` | Child-process invocation now passes `encoding="utf-8", errors="replace"` explicitly instead of relying on host-locale defaults |
| `tools/onenote_adapter.py` | Added `_to_utc_z()`; `update_page()` now sends `_to_utc_z(expected_last_modified)` instead of `.isoformat()`; `_CONFLICT_MARKERS` gained the `"0x80042010"` substring |
| `tests/test_ps_bridge_transport.py` | Added `test_invoke_decodes_child_streams_as_utf8_with_replace` |
| `tests/test_onenote_adapter.py` | Added `test_update_page_converts_non_utc_expected_to_utc_z`, `test_update_page_com_hresult_0x80042010_raises_page_conflict` |

### Test Summary

- **Total tests written this batch**: 3 (`test_invoke_decodes_child_streams_as_utf8_with_replace`, `test_update_page_converts_non_utc_expected_to_utc_z`, `test_update_page_com_hresult_0x80042010_raises_page_conflict`)
- **Total tests passing (full suite)**: 674/674 (671 Batch-1/2/3/4 baseline + 3 new), confirmed by `source .venv/bin/activate && python3.12 -m pytest -q` at the close of this batch
- **Live verification**: 8/8 PASS via the real MCP stdio driver against the deployed QA instance (`C:\usr\WinMCP-qa`) — not a fake/mocked layer
- **Approval tests**: `deploy/smoke_test.py`'s full run PASSED post-refactor, confirming the stream-encoding fix is behavior-preserving for the pre-existing Outlook/file-search families

### Documentation Fixed This Batch (this batch's own scope)

1. `tasks.md` — checked off 11.1, noting it was executed via the live MCP driver from WSL on 2026-08-27, 8/8 PASS.
2. `design.md` — corrected Decision 7's text to match shipped reality (bridge returns raw `pageXml`; Python parses); reconciled `get_hierarchy()`'s contract wording with the shipped no-`depth`-param `list[NotebookNode]` API; marked the "exact conflict HRESULT" Open Question RESOLVED (`0x80042010`, live evidence 2026-08-27); added the lazy-`lastModifiedTime`/save-latency limitation and the Z-suffix wire-format requirement to the relevant decisions.
3. `README.md` — added the save-latency concurrency-window limitation to "Known limitations"; confirmed manual-verification steps 11-15 against what the live driver actually validated (steps 11-14 map directly onto the 8/8 live-verified items above; step 15's bridge-unavailable check was not part of this batch's live driver run and remains a manual-only step, wording unchanged since it still accurately describes that untested-live path).

### Issues Found

None beyond the 4 defects above, all fixed and live-reverified.

### Remaining Tasks (this change)

None. Phase 11 (11.1) is now complete. All 48 tasks (47 automated + 1 manual) are done.

### Status

All tasks for `add-onenote-adapter` complete: Phases 1-11, 48/48. Full suite: 674/674 passing. Live QA: 8/8 PASS. Ready for `sdd-verify` re-run (recommended given the 4 live-only defects fixed post-original-verify) and archive.
