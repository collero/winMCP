# Verification Report: add-onenote-adapter

**Change**: add-onenote-adapter
**Version**: N/A (no spec version field)
**Mode**: Strict TDD (config.yaml `strict_tdd: true`, orchestrator-injected)

---

### Completeness

| Metric | Value |
|--------|-------|
| Tasks total | 48 (47 automated + 1 manual) |
| Tasks complete (automated) | 47/47 |
| Tasks incomplete | 1 — `11.1` **[MANUAL — user-run]**, explicitly out of scope for CI/verify |

No incomplete automated tasks. Task 11.1 (deploy-qa.sh live Windows verification) is correctly left unchecked and is out of scope per the change's own Phase 11 boundary.

---

### Build & Tests Execution

**Build**: ➖ No build/type-check command configured (`rules.verify.build_command` empty; no linter/type-checker in this greenfield project) — not a blocker per project context.

**Tests**: ✅ 671 passed, 0 failed, 0 skipped
```
$ source .venv/bin/activate && python3.12 -m pytest -q
........................................................................ [ 10%]
... (9 pages of dots) ...
671 passed in 6.23s
```
Isolated re-run of `tests/test_file_search_adapter.py`: ✅ 87/87 passed.
Isolated `-k onenote`: ✅ 100/100 passed.

**`tests/test_file_search_adapter.py` unmodified**: ✅ Confirmed. This is not a git repo, so byte-identity was checked via filesystem mtime evidence: the file's mtime is `2026-08-26 18:38:59`, strictly before every file this change touched (earliest onenote-change edit is `tools/ps_bridge_transport.py` at `2026-08-27 12:30:35`). No batch's "Files Changed" table lists this file, and every batch's "Deviations"/closing paragraph explicitly re-confirms the file was "never opened with Edit/Write, only Read" and stayed byte-for-byte unchanged while its own 87-test suite stayed green as the regression net for the `PowerShellSearchBridge` -> `PsBridgeTransport` refactor.

**Coverage**: ➖ Not available (`pytest-cov` not installed, `testing.coverage.available: false` in config.yaml). Not a failure — informational only per Strict TDD Verify rules.

---

### TDD Compliance

| Check | Result | Details |
|-------|--------|---------|
| TDD Evidence reported | ✅ | All 4 batches carry a full "TDD Cycle Evidence" table in `apply-progress.md` |
| All tasks have tests | ✅ | 47/47 automated tasks map to a test file (4.5's `.ps1` script is explicitly covered by 4.1/4.3's adapter-level assertions, per tasks.md's own wording — no direct PS1 unit test possible on WSL2) |
| RED confirmed (tests exist) | ✅ | Every batch names the specific `ModuleNotFoundError`/`ImportError` observed before implementation; all named test files exist and were verified present |
| GREEN confirmed (tests pass) | ✅ | Cross-checked against this session's own `671 passed` run — matches Batch 4's final claimed total exactly |
| Triangulation adequate | ✅ | Multiple, materially-different cases per behavior confirmed by direct read (e.g. `test_get_page_extracts_correctly_with_a_non_default_namespace` uses a genuinely different `one` namespace URI and different text than the default-namespace CDATA test; `test_search_truncates_to_top_n_client_side` vs `test_search_maps_rows_to_page_summaries` differ in row count/assertions, not just labels) |
| Safety Net for modified files | ✅ | Batch 1: 543/543 passing baseline confirmed before touching `file_search_adapter.py`, 563/563 after. Batch 3: `tools/onenote_adapter.py`'s timeout-wiring change kept its own 23/23 tests green before/after |

**TDD Compliance**: 6/6 checks passed

---

### Test Layer Distribution

| Layer | Tests | Files | Tools |
|-------|-------|-------|-------|
| Unit | ~118 (new, this change) | `test_ps_bridge_transport.py` (20), `test_schemas.py`+`test_errors.py` (+25), `test_fake_onenote_adapter.py` (17), `test_onenote_adapter.py` (23), `test_onenote_tools.py` (23), `test_settings.py` (+10) | pytest, `pytest-mock` (mocked `subprocess.Popen`/`PsBridgeTransport`), `FakeOneNoteAdapter` |
| Integration | 10 (new) | `test_server.py` (FastMCP in-process `Client` end-to-end through `server.py` -> `tools/onenote.py` -> fake/real adapter) | `fastmcp.Client` |
| E2E | 0 | — | Not available on WSL2 — deferred to manual Phase 11 (`deploy-qa.sh`), correctly out of CI scope |
| **Total (new this change)** | **~128** | | |

Full-suite total: 671 (543 pre-existing baseline + 128 new).

---

### Changed File Coverage

Coverage analysis skipped — no coverage tool detected (`pytest-cov` not installed; consistent with `openspec/config.yaml`'s `testing.coverage.available: false`). Not flagged as a failure.

---

### Assertion Quality

Spot-checked all new/changed test files (`test_onenote_adapter.py`, `test_onenote_tools.py`, `test_fake_onenote_adapter.py`, `test_ps_bridge_transport.py`, `test_schemas.py`, `test_errors.py`, `test_server.py`'s onenote tests) for banned patterns (tautologies, ghost loops, orphan empty-checks, smoke-test-only, mock-heavy tests):

- No tautologies (`assert True`, `expect(1)==1`) found.
- Every `== []`/`== ""` empty-result assertion found (`test_onenote_tools.py:114`, `test_fake_onenote_adapter.py:99`, `test_ps_bridge_transport.py:388`) has a companion non-empty-result test in the same test suite (e.g. the zero-matches test sits alongside a matches-returned test with real row content).
- CDATA/namespace extraction tests assert real extracted string content (`"Reunión semanal"`, `"Primer párrafo.\nSegundo párrafo."`, a genuinely different `one` namespace URI with different sample text) — not smoke-test-only.
- `test_onenote_adapter_selection_deferred_when_bridge_unavailable` (`test_server.py`) exercises the REAL `OneNoteAdapter` with no mock, relying on this WSL2 host genuinely lacking `powershell.exe` — a real-condition test, not a mocked tautology.
- Allowlist-refusal tests assert both the raised error's `notebook_name` field AND that the write method was never called (`mocker.spy`), not just exception type.

**Assertion quality**: ✅ All assertions verify real behavior

---

### Quality Metrics

**Linter**: ➖ Not available (none configured, greenfield project)
**Type Checker**: ➖ Not available (none configured)

---

### Spec Compliance Matrix

| Requirement | Scenario | Test | Result |
|-------------|----------|------|--------|
| onenote-com-adapter: Adapter Interface | Fake adapter satisfies the interface | `test_fake_onenote_adapter.py` (17 tests) + `test_server.py::test_onenote_tools_registered_via_fake_onenote_adapter` | ✅ COMPLIANT |
| onenote-com-adapter: Dumb-Executor Bridge Transport | A search op is sent as one JSON line on stdin | `test_onenote_adapter.py::test_search_sends_findpages_request_with_query_only` | ✅ COMPLIANT |
| onenote-com-adapter: Dumb-Executor Bridge Transport | A script error maps to a typed error | `test_onenote_adapter.py::test_search_transport_error_raises_onenote_unavailable` (+ 3 sibling tests for other ops) | ✅ COMPLIANT |
| onenote-com-adapter: Dynamic XML Namespace Detection | A page's namespace differs from the spike-observed default | `test_onenote_adapter.py::test_get_page_extracts_correctly_with_a_non_default_namespace` | ✅ COMPLIANT |
| onenote-com-adapter: Page Content Extraction | Title and body extracted from nested CDATA nodes | `test_onenote_adapter.py::test_get_page_extracts_title_and_body_from_nested_cdata` | ✅ COMPLIANT |
| onenote-com-adapter: Failure Mapping | Unknown page_id raises OneNotePageNotFoundError | `test_onenote_adapter.py::test_get_page_transport_not_found_error_raises_page_not_found` + `test_get_page_empty_result_raises_not_found` | ✅ COMPLIANT |
| onenote-com-adapter: Adapter Selection at Runtime | Bridge unavailable on this platform | `test_server.py::test_onenote_adapter_selection_deferred_when_bridge_unavailable` + `test_import_succeeds_without_win32com` | ✅ COMPLIANT |
| onenote-search: Search Input/Output | Successful search returns matching pages | `test_onenote_tools.py` (matches-returned case) + `test_server.py::test_onenote_search_tool_returns_results_via_fake_onenote_adapter` | ✅ COMPLIANT |
| onenote-search: Search Input/Output | Empty query is rejected before any adapter call | `test_onenote_tools.py` (empty-query case, adapter-not-called spy) + `test_server.py::test_onenote_search_tool_empty_query_surfaces_invalid_request_tool_error` | ✅ COMPLIANT |
| onenote-search: Empty Result Is Not an Error | No matches | `test_onenote_tools.py` (zero-matches -> `[]` case) | ✅ COMPLIANT |
| onenote-search: Result Limit Parameter | Default limit applied when omitted | `test_onenote_tools.py` (80-seeded-pages, default-50 case) + `test_settings.py` (`onenote_search_max_results` default) | ✅ COMPLIANT |
| onenote-search: Result Limit Parameter | Oversized limit clamped, not rejected | `test_onenote_tools.py` (limit=10000 -> spy asserts adapter called with 200) + `test_settings.py` (clamp-to-200 case) | ✅ COMPLIANT |
| onenote-search: OneNote Unavailable | Bridge failure | `test_onenote_tools.py` (unavailable -> `OneNoteUnavailableError` case) | ✅ COMPLIANT |
| onenote-get-page: Get Page Input/Output | Successful fetch | `test_onenote_tools.py` (successful-fetch field-by-field case) + `test_server.py::test_onenote_get_page_tool_returns_detail_via_fake_onenote_adapter` | ✅ COMPLIANT |
| onenote-get-page: Page Not Found | Unknown pageId | `test_onenote_tools.py` (unknown-id case) + `test_server.py::test_onenote_get_page_tool_unknown_id_surfaces_page_not_found_error` | ✅ COMPLIANT |
| onenote-get-page: Empty Body Handling | Page with no body text | `test_onenote_tools.py` (empty-body -> `""` case) | ✅ COMPLIANT |
| onenote-get-page: OneNote Unavailable | Bridge failure | `test_onenote_tools.py` (unavailable case) | ✅ COMPLIANT |
| onenote-get-page: No Mutation on Fetch | Fetch does not alter the page | `test_onenote_tools.py` (two repeated fetches equal + create/update spy never called) | ✅ COMPLIANT |
| onenote-write-page: Writable Notebook Allowlist | Write to default test notebook succeeds | `test_onenote_tools.py` (default-notebook-succeeds, positional-args spy) | ✅ COMPLIANT |
| onenote-write-page: Writable Notebook Allowlist | Write to live notebook refused before adapter call | `test_onenote_tools.py` (live-notebook-refused, `update_page`/`create_page` spy never called + `notebook_name` asserted) + `test_server.py::test_onenote_create_page_tool_live_notebook_refused_surfaces_tool_error` | ✅ COMPLIANT |
| onenote-write-page: Writable Notebook Allowlist | Configured allowlist widens the writable set | `test_onenote_tools.py` (`mocker.patch` on `onenote_writable_notebooks`, "Sandbox" case) | ✅ COMPLIANT |
| onenote-write-page: Create Page Input/Output | Successful creation | `test_onenote_tools.py` (create returns real `PageDetail` with new pageId) + `test_server.py::test_onenote_create_page_tool_returns_new_page_via_fake_onenote_adapter` | ✅ COMPLIANT |
| onenote-write-page: Update Page Requires Optimistic Concurrency | Matching dateExpectedLastModified succeeds | `test_onenote_tools.py` (matching-date-succeeds) + `test_server.py::test_onenote_update_page_tool_matching_date_succeeds` | ✅ COMPLIANT |
| onenote-write-page: Conflicting Update Raises | Stale dateExpectedLastModified is rejected | `test_onenote_tools.py` (stale-date -> conflict + seeded page confirmed unchanged) + `test_server.py::test_onenote_update_page_tool_stale_date_surfaces_conflict_error` | ✅ COMPLIANT |
| onenote-write-page: OneNote Unavailable | Bridge failure on create | `test_onenote_tools.py` (create-unavailable case) | ✅ COMPLIANT |

**Compliance summary**: 24/24 scenarios compliant — zero UNTESTED, zero FAILING, zero PARTIAL.

---

### Correctness (Static — Structural Evidence)

| Requirement | Status | Notes |
|------------|--------|-------|
| OneNotePort Protocol + both adapters | ✅ Implemented | `tools/onenote_adapter.py` defines the Protocol; `OneNoteAdapter`/`FakeOneNoteAdapter` both satisfy it structurally (duck-typed, no explicit `Protocol` inheritance needed) |
| Shared `PsBridgeTransport` used by both bridges | ✅ Implemented | `tools/ps_bridge_transport.py` is imported by both `tools/file_search_adapter.py::PowerShellSearchBridge` and `tools/onenote_adapter.py::OneNoteAdapter`; the old spawn/pump/reap/diagnostic-suffix helpers were removed from `file_search_adapter.py` (confirmed absent via grep) — no duplicated plumbing |
| Python-only allowlist enforcement pre-adapter | ✅ Implemented | `tools/onenote.py::_check_writable` runs before `adapter.create_page()`/`adapter.update_page()`; `ps_bridge_onenote.ps1` receives only opaque `sectionId`/`pageId`, never a notebook name |
| Default allowlist exactly `["z - Test Notebook"]` | ✅ Implemented | `tools/settings.py::onenote_writable_notebooks()` + `config/settings.yaml`'s own seeded value both match exactly |
| `expected_last_modified` required, never MinValue-defaulted | ✅ Implemented | `UpdatePageRequest.expected_last_modified` has no default in `models/schemas.py`; `OneNoteAdapter.update_page()` passes `.isoformat()` verbatim; `ps_bridge_onenote.ps1`'s `UpdatePageContent` case passes `$expectedDate` (parsed from the caller's value) to the real COM call, never `[DateTime]::MinValue` (that literal appears only in `CreateNewPage`'s own initial-write path, correctly scoped to a page that cannot yet conflict) |
| Dynamic XML namespace detection | ✅ Implemented | Both `tools/onenote_adapter.py::_extract_title_and_body` (Python) and `ps_bridge_onenote.ps1`'s `Get-HierarchyXml`/`FindPages` (PowerShell) read `.../DocumentElement.NamespaceURI` at runtime; no hardcoded `.../2013/onenote` string found anywhere in either file |
| Self-contained `ps_bridge_onenote.ps1` | ✅ Implemented | No `#Requires`/dot-sourcing/module import of any shared PS file; COM call shapes (`GetHierarchy('',4,[ref])`, `FindPages('',query,[ref],$false,$false)`, `GetPageContent(id,[ref],0)`, `CreateNewPage(sectionId,[ref],0)`, `UpdatePageContent(xml,date)`) match `/mnt/c/usr/WinMCP/_spike_onenote.ps1`/`_spike_onenote_write.ps1`'s already-validated calls verbatim; JSON-Lines-rows + `{"done":true,"count":N}` sentinel / single `{"error":...}` + `exit 1` contract confirmed by direct read; file confirmed pure ASCII via `LC_ALL=C grep -n '[^ -~\t]'` (zero matches) |

---

### Coherence (Design)

| Decision | Followed? | Notes |
|----------|-----------|-------|
| 1. Extract shared PS-bridge transport | ✅ Yes | `PsBridgeTransport` created and used by both bridges from day one |
| 2. Transport return/error shape | ✅ Yes | `invoke() -> (rows, truncated)`, raises generic `PsBridgeTransportError`; each adapter re-raises its own typed error with the same message text |
| 3. No shared `.ps1` skeleton | ✅ Yes | `ps_bridge_onenote.ps1` is fully self-contained |
| 4. Bridge lifecycle (one process per call) | ✅ Yes | `New-Object -ComObject OneNote.Application` instantiated fresh inside the script on every invocation; no daemon |
| 5. Op dispatch shape | ⚠️ Deviated (justified) | Op values are the literal COM method names (`FindPages`, not `search`) — design.md's own paraphrase was looser than the spec's explicit scenario wording; apply-progress documents this and follows the more concrete spec/tasks.md text. Not a spec violation. |
| 6. Allowlist enforcement point | ✅ Yes | `tools/onenote.py` resolves + checks before any write adapter call; bridge never sees a notebook name |
| 7. XML→text extraction (script parses XML, returns `{title, text}`) | ⚠️ Deviated (justified, but design.md is now stale) | Extraction was moved to Python (`_extract_title_and_body`) — the onenote-com-adapter spec's own scenarios ("WHEN the adapter parses it") require this, and it is the only way to unit-test the requirement on WSL2 (no real COM). The `.ps1` script instead returns raw `pageXml`. See WARNING below — design.md's Decision 7 text should be corrected to match, since it currently describes the opposite of what shipped. |
| 8. Update semantics (partial patch, append body) | ✅ Yes | `ps_bridge_onenote.ps1`'s `UpdatePageContent` case appends a new `Outline/OEChildren/OE/T`, never removes existing content; documented as a known limitation in README |
| 9. Optimistic concurrency | ✅ Yes | Required field, verbatim pass-through, bridge checks hierarchy `dateTime` before writing and raises a conflict-marked error string |
| 10. Error taxonomy | ✅ Yes | All 5 new errors subclass `CalendarToolError`; `server.py::_map_error()` untouched, `onenote_search` additionally catches `ValueError` matching the existing precedent for tools with pre-adapter validation |

---

### Deployment Completeness

| Check | Status |
|-------|--------|
| `tools/ps_bridge_onenote.ps1` in `make-deploy-package.sh` MANIFEST | ✅ Present (line 53), alongside `ps_bridge_search.ps1` |
| ASCII-purity gate covers the new script | ✅ Gate 4 loops over both `.ps1` bridge scripts; file confirmed pure ASCII |
| `deploy/smoke_test.py::EXPECTED_TOOLS` matches the 13-tool set | ✅ 9 pre-existing + 4 new OneNote tools = 13, confirmed by direct read |
| OneNote deliberately excluded from `smoke_test.py`'s automated live `FAMILIES` | ✅ Documented in-line (write side effects on real content) and in README's "Known limitations" |
| README consistent with 13-tool set | ✅ "thirteen tools" (3 occurrences), tool bullets, config keys, manual verification steps 11-15, Known limitations all updated |
| `config/settings.yaml` documents the 3 new keys with the correct defaults | ✅ `onenote_writable_notebooks: ['z - Test Notebook']`, `onenote_search_max_results: 50`, `onenote_ps_bridge_timeout_seconds: 20` |

---

### Batch Deviation Review

All 4 batches' documented deviations were reviewed against the specs, design.md, and the shipped code. Verdict per batch:

**Batch 1** (4 deviations, all additive/backward-compatible transport kwargs + one bugfix caught during TRIANGULATE): **Acceptable.** No spec/design conflict; `diagnostics`/`logger` params are optional extensions needed to keep the regression suite byte-for-byte unmodified while still supporting both callers' logging needs.

**Batch 2** (6 deviations):
1. Op vocabulary uses COM method names, not design.md's paraphrase — **Acceptable**, spec is more concrete and was followed correctly.
2. XML parsing moved from PowerShell to Python, reversing design.md Decision 7 — **Acceptable as an implementation choice** (correctly follows the spec's own scenario wording and is the only testable approach on WSL2), **but flagged as a WARNING** below since design.md's text was never updated to match and now actively contradicts the shipped architecture.
3. `get_hierarchy()` has no `depth` param, following design.md's Interfaces contract over the spec's prose — **Acceptable**, though this exposes a pre-existing spec/design.md inconsistency not caused by this apply (see WARNING below).
4. No separate `.../Result` envelope models — **Acceptable**, every spec scenario returns a bare model, no wrapper needed.
5. Hardcoded timeout constant deferred to Phase 7 — **Acceptable**, explicitly closed out in Batch 3 as promised, confirmed by reading `tools/onenote_adapter.py` (constant is gone, `onenote_ps_bridge_timeout_seconds()` is called live).
6. `OneNoteSectionNotFoundError` not raised by the real adapter, only by `FakeOneNoteAdapter`/tool layer — **Acceptable**, tool-layer resolution always runs first in the only code path that reaches it; flagged as a minor SUGGESTION below for adapter-level defense-in-depth.

**Batch 3** (4 deviations): All **Acceptable** — each follows the spec's more concrete wording over design.md's shorthand, or reflects an implementation constraint (`UpdatePageRequest` has no `sectionId`) that has no other consistent resolution given the shipped schemas. Confirmed by reading `tools/onenote.py` and `models/schemas.py` directly.

**Batch 4** (3 deviations): All **Acceptable** — the smoke-test/deploy-manifest changes were outside tasks.md's literal wording but correctly identified as required to avoid shipping a broken/incomplete feature (missing `.ps1` in the deploy package would have been a real, silent production bug); the exception-handling split (`ValueError` for `onenote_search` only) correctly mirrors the established per-tool precedent already used by every other tool in `server.py`.

**No deviation constitutes a spec violation.** Every deviation either (a) correctly favors a more concrete spec/tasks.md requirement over a looser design.md paraphrase, or (b) is a necessary, backward-compatible implementation detail with no spec impact.

---

### Issues Found

**CRITICAL** (must fix before archive):
None.

**WARNING** (should fix):
1. **design.md Decision 7 is now inaccurate.** It states "the script... Returns plain `{title, text}` JSON — Python never parses OneNote XML," but the shipped implementation does the opposite (Python parses; the script returns raw `pageXml`) — correctly, per the spec's own scenarios, but design.md's text was never corrected. This will confuse a future reader who trusts design.md over the code. Recommend updating design.md's Decision 7 row (or adding an addendum) before/during archive.
2. **design.md's `get_hierarchy()` Interfaces/Contracts signature (`() -> list[NotebookNode]`) conflicts with the onenote-com-adapter spec's own prose (`get_hierarchy(depth=4) -> HierarchyNode`).** This inconsistency predates this apply (it exists between the spec and design as originally authored) and the implementation correctly picked one consistent option (design's), but the spec text itself was never reconciled. Recommend a small spec-wording fix at archive time so the merged main spec doesn't carry the stale `depth=4`/`HierarchyNode` phrasing forward.

**SUGGESTION** (nice to have):
1. `OneNoteSectionNotFoundError` is not raised by the real `OneNoteAdapter.create_page()` itself — only by `FakeOneNoteAdapter` and the tool-layer `_resolve_notebook_for_section()`. In practice this is unreachable dead code for any caller routed through `tools/onenote.py` (the only production path), but a future caller bypassing the tool layer would get a generic `OneNoteUnavailableError` instead of the more specific error. Low priority; no spec scenario requires the adapter itself to raise it.
2. The `]]>`-in-title/body edge case (breaks CDATA construction) and append-only (never true replace) update semantics are both accepted, documented limitations (design.md Open Questions, README "Known limitations") — no action needed, flagging only for completeness.

---

### Verdict

**PASS WITH WARNINGS**

All 47 automated tasks are complete, the full test suite is green (671/671, including the unmodified 87-test `test_file_search_adapter.py` regression net proving the shared-transport refactor is behavior-preserving), all 24 spec scenarios across the 4 domains are behaviorally COMPLIANT with passing tests, Strict TDD discipline was genuinely followed (RED/GREEN/TRIANGULATE evidence cross-checked against real test runs, no trivial assertions found), the shared `PsBridgeTransport` design is correctly realized with no duplicated plumbing, the Python-side-only allowlist/optimistic-concurrency/dynamic-namespace requirements are all correctly implemented and enforced before any COM call, and deployment packaging (manifest, ASCII gate, smoke-test tool list, README) is complete and consistent with the 13-tool set. The only findings are two documentation-drift WARNINGs (design.md text no longer matches the shipped — and spec-correct — architecture) and two low-priority SUGGESTIONs; none block archiving, but the design.md corrections are worth making during archive so the artifact trail stays accurate.

---

## Delta re-verify (post live-QA hotfixes)

**Date**: 2026-08-27
**Scope**: Batch 5 of `apply-progress.md` — the 4 live-only defects surfaced by a real MCP stdio driver run from WSL against the deployed QA instance, plus the doc-reconciliation the same batch performed. Per the launch instructions, this does **not** re-run the full 24-scenario traceability from the section above — that stands unchanged (no Batch-5 fix touches a spec scenario's behavior in a way that would flip a prior COMPLIANT verdict; see per-item analysis below).

### Full suite

```
$ source .venv/bin/activate && python3.12 -m pytest -q
........................................................................ [ 10%]
........................................................................ [ 21%]
........................................................................ [ 32%]
........................................................................ [ 42%]
........................................................................ [ 53%]
........................................................................ [ 64%]
........................................................................ [ 74%]
........................................................................ [ 85%]
........................................................................ [ 96%]
..........................                                               [100%]
674 passed in 4.80s
```
✅ 674/674, exit code 0 — matches apply-progress.md's claimed 671 → 674 (+3).

Isolated re-run: `tests/test_file_search_adapter.py` → ✅ 87/87 passed, unchanged. This file is not touched by any Batch 5 "Files Changed" entry, and its own suite staying green while `tools/ps_bridge_transport.py` (a file it depends on transitively via `PowerShellSearchBridge`) gained the `encoding="utf-8", errors="replace"` kwargs is direct evidence the encoding fix is additive/backward-compatible for the search bridge, not a silent behavior change.

### Defect-by-defect verification

| # | Defect (apply-progress.md) | Code fix present | Test coverage | Verdict |
|---|---|---|---|---|
| 1 | Stream-encoding truncation (`text=True`, locale-default decode) | `tools/ps_bridge_transport.py::_invoke_impl`'s `subprocess.Popen(...)` call now passes `encoding="utf-8", errors="replace"` explicitly (verified by direct read, lines ~276-289); both `.ps1` scripts pin `[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)` as the first executable statement after `$ErrorActionPreference` (before any `[Console]::Out`/`[Console]::In` access) | `tests/test_ps_bridge_transport.py::test_invoke_decodes_child_streams_as_utf8_with_replace` (present, asserts `popen_mock.call_args.kwargs["encoding"] == "utf-8"` and `["errors"] == "replace"`) — unit-testable and tested | ✅ COMPLIANT |
| 2 | `ConvertTo-IsoStringOrNull` called `.ToString("o")` on a raw string | `ps_bridge_onenote.ps1::ConvertTo-IsoStringOrNull` (lines 70-90) now branches: `$null` → `$null`; `[DateTime]` instance → `.ToString("o")` directly; otherwise cast to `[string]`, blank → `$null`, else `[DateTime]::Parse($text, [CultureInfo]::InvariantCulture, [DateTimeStyles]::RoundtripKind).ToString("o")` inside a `try/catch` returning `$null` on failure | Not unit-testable on WSL2 (no real PowerShell/COM host) — honestly documented as such in apply-progress.md and in this script's own inline comments (live-QA defect note at lines 70-76); no fabricated PS1 unit test claimed | ✅ COMPLIANT (documented limitation, not silently skipped) |
| 3 | Optimistic-concurrency timezone bug (`+00:00` vs `Z`, RoundtripKind local-adjustment) | `tools/onenote_adapter.py` gained `_to_utc_z(value: datetime) -> str` (lines 156-165): aware datetime → `astimezone(UTC)`, strip tzinfo, then `isoformat() + "Z"`; naive datetime → `isoformat() + "Z"` directly (treated as already-UTC, matching the bridge's own UTC-only `lastModified` outputs). `update_page()` now sends `_to_utc_z(expected_last_modified)` instead of `.isoformat()` (line 349). `_CONFLICT_MARKERS` gained the literal `"0x80042010"` substring (line 152). `ps_bridge_onenote.ps1`'s `UpdatePageContent` case additionally calls `.ToUniversalTime()` after the `RoundtripKind` parse on both the page's actual timestamp and the caller's expected timestamp (lines 342-345) as defense-in-depth | 3 tests in `tests/test_onenote_adapter.py`: `test_update_page_passes_expected_last_modified_as_utc_z` (UTC-aware input → `Z` suffix; same test name/slot as before, assertion updated to the new wire format rather than net-new), `test_update_page_converts_non_utc_expected_to_utc_z` (net-new: zoned `+02:00` input converts to the correct UTC instant), `test_update_page_com_hresult_0x80042010_raises_page_conflict` (net-new: raw HRESULT text maps to `OneNotePageConflictError`). Net-new-test count (2) plus the transport test (1) = 3, matching apply-progress.md's "Total tests written this batch: 3" and the 671→674 delta exactly | ✅ COMPLIANT |
| 4 | `UpdatePageContent` preserved a stale `lastModifiedTime` attribute on write | Both `CreateNewPage` and `UpdatePageContent` cases in `ps_bridge_onenote.ps1` call `$px.DocumentElement.RemoveAttribute("lastModifiedTime")` immediately before their respective `UpdatePageContent`/write COM calls (lines 288 and 376, one per op) | Not unit-testable on WSL2 (same reason as #2) — honestly documented in apply-progress.md and in the script's own inline comments at both sites; no fabricated PS1 unit test claimed | ✅ COMPLIANT (documented limitation, not silently skipped) |

**Summary**: 4/4 Batch 5 defects have a verified code fix in place; the 2 unit-testable ones (#1, #3) each have a real, passing, non-tautological test; the 2 PowerShell-only ones (#2, #4) are honestly documented as untestable on this WSL2 host rather than silently claimed-covered, consistent with every prior batch's own precedent for `.ps1`-only changes.

### Original WARNINGs — re-checked

1. **design.md Decision 7 (stale XML-parsing-location text)** — ✅ **FIXED**. Row 7 of the Architecture Decisions table now reads "As shipped (revised from the original plan below): `ps_bridge_onenote.ps1` returns the page's raw `pageXml` string verbatim... `tools/onenote_adapter.py::_extract_title_and_body()`... reads the namespace from the document's own root element... extracts title... and body...", explicitly correct against the shipped code, with the original plan preserved underneath for history and an explicit note that this was "flagged as a documentation-drift WARNING by `sdd-verify` and corrected here in Batch 5."
2. **design.md `get_hierarchy()` signature vs spec prose inconsistency** — ✅ **FIXED**. The Interfaces/Contracts code block's `get_hierarchy()` line now carries an inline comment: "As shipped: no `depth` parameter, always full-depth internally. The onenote-com-adapter spec's own prose... pre-dates this contract and was never reconciled to it; this Interfaces block is what shipped (flagged by sdd-verify as a spec/design inconsistency that predates this apply — recommend a small spec-wording fix at archive time)." This documents the resolution and correctly defers the spec-text fix to archive time (a spec-wording change is out of scope for an apply/verify cycle) rather than leaving the drift unacknowledged.

Both original WARNINGs are resolved as documentation fixes. No new documentation-drift issues were introduced by Batch 5's own edits (spot-checked: Decision 9's row and the Open Questions section were both updated consistently with each other and with the shipped code).

### Shared-transport design decisions — no regression

- `PowerShellSearchBridge` (in `tools/file_search_adapter.py`) still delegates to the same shared `PsBridgeTransport.invoke()` — confirmed unchanged this batch (not in Batch 5's "Files Changed" table, and its own 87/87 regression suite stayed green).
- The only behavior change to `PsBridgeTransport` itself is the `encoding`/`errors` kwargs on the `Popen` call — additive to the call signature (no parameter removed, no default that could break an existing caller), and both bridges benefit identically since both now emit UTF-8. This is exactly the intended fix, not a divergence between the two bridges' transport usage.
- No new duplicated plumbing was introduced: `_pump_stdout`/`_pump_stderr`/`_reap`/deadline-loop logic in `ps_bridge_transport.py` is untouched by Batch 5 apart from the two `Popen` kwargs.

### Optimistic-concurrency spec requirement — still satisfied given the lazy-timestamp limitation

The onenote-write-page spec's "Conflicting Update Raises, Never Silently Overwrites" requirement states: "When the page was modified after the caller's `dateExpectedLastModified`, the adapter/bridge MUST report a conflict... never silently apply the write." The live-discovered limitation (OneNote stamps `lastModifiedTime` **lazily**, at its own background save, observed unchanged 15+ seconds after a write actually landed) narrows this to genuinely stale timestamps (seconds-to-minutes old — the realistic collision case for an LLM-driven tool calling sequentially) rather than true-concurrent writes landing inside OneNote's own sub-15-second save-latency window. The spec's own scenario ("Stale `dateExpectedLastModified` is rejected") describes exactly the case the shipped guard correctly handles; it does not require detecting a write racing within the save-latency window, which is a physically-imposed limit of the underlying COM API itself (OneNote's own native COM check, HRESULT `0x80042010`, is equally blind to it — not a gap unique to this adapter's own guard). The limitation is honestly and specifically documented in `design.md`'s Decision 9 row and in `README.md`'s "Known limitations" section, not silently omitted. **Verdict: requirement still satisfied**, with an honestly-disclosed, COM-imposed edge case — no CRITICAL or WARNING raised for this.

### Deployment consistency — re-checked

`make-deploy-package.sh` Gate 4 (`for ps1 in "tools/ps_bridge_search.ps1" "tools/ps_bridge_onenote.ps1"`) still runs the ASCII-purity check over both files after Batch 5's edits. Direct re-check this session: an `LC_ALL=C grep` for any byte outside the printable-ASCII range plus tab, run against both files, returns zero matches for each — both scripts remain pure ASCII after adding the `[Console]::OutputEncoding` line and the `ConvertTo-IsoStringOrNull`/attribute-stripping changes. Gate 1's manifest inclusion of both files (lines 48 and 53 of `make-deploy-package.sh`) is unaffected by this batch.

### Issues Found (this delta)

**CRITICAL**: None.

**WARNING**: None new. (Both original WARNINGs are now resolved — see above.)

**SUGGESTION**: None new beyond the 2 already carried forward from the original report (both still low-priority and unaffected by Batch 5).

### Delta Verdict

**PASS**

All 4 Batch-5 live-only defects have a verified, in-place code fix; the 2 unit-testable fixes are covered by real, non-tautological, passing tests (674/674 full suite, up from 671, exactly as claimed); the 2 PowerShell-only fixes are honestly documented as untestable on this dev host rather than falsely claimed-covered; both original design.md-drift WARNINGs are now fixed; the shared-transport architecture shows no regression; the ASCII deployment gate still covers both `.ps1` scripts; and the onenote-write-page optimistic-concurrency requirement remains satisfied, with the newly-discovered OneNote save-latency edge case honestly disclosed rather than glossed over. This upgrades the change's overall status from the original **PASS WITH WARNINGS** to a clean **PASS** for archiving.
