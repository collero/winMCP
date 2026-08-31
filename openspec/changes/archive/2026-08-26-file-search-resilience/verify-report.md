# Verification Report

**Change**: file-search-resilience
**Version**: N/A (no version field in specs)
**Mode**: Strict TDD

---

### Completeness

| Metric | Value |
|--------|-------|
| Tasks total | 45 |
| Tasks complete | 45 |
| Tasks incomplete | 0 |

All checklist items across Phases 1-7 and the Final section are `[x]`, including task `3.7b` (added mid-flight during the live security review, itself checked off). No incomplete tasks.

---

### Build & Tests Execution

**Build**: ➖ Not applicable (no build/type-check tool configured for this Python project; `rules.verify.build_command` is empty in `openspec/config.yaml`)

**Tests**: ✅ 451 passed / 0 failed / 0 skipped
```
451 passed in 2.94s
```
Full suite run via `.venv/bin/python3.12 -m pytest -q`, matching the baseline stated by the orchestrator and by apply-progress.md's final batch (`443 passed` at that point; the difference is other sibling changes that landed after this change's own Batch 3 completed — none of the delta is a regression introduced by this change; a targeted re-run of only this change's test files confirms `124 passed` with 0 failures: `tests/test_file_search_walk.py`, `tests/test_file_search_adapter.py`, `tests/test_file_search_tools.py`, `tests/test_server.py`).

**Coverage**: Not available (`coverage.available: false` in `openspec/config.yaml` — `pytest-cov` not installed). Skipped cleanly, not flagged as a failure.

---

### TDD Compliance

| Check | Result | Details |
|-------|--------|---------|
| TDD Evidence reported | ✅ | Full "TDD Cycle Evidence" tables present for all 3 batches in apply-progress.md |
| All tasks have tests | ✅ | 45/45 tasks map to a test file or an explicit "not unit-testable, covered indirectly" note (task 3.11, the `.ps1` asset itself) |
| RED confirmed (tests exist) | ✅ | All listed test files exist in `tests/` and were independently read/verified this session |
| GREEN confirmed (tests pass) | ✅ | 451/451 pass on this session's own full-suite run |
| Triangulation adequate | ✅ | Escaper table alone carries 9 parametrized hostile/edge cases; walk/bridge/fallback scenarios each carry 2-4 distinct cases |
| Safety Net for modified files | ✅ | Each batch's pre-existing test files (settings/errors/schemas: 6/22/32; adapter: 17 pre-existing WindowsSearchAdapter tests; tool tests: 12 dispatch-agnostic tests) reported as still passing before/after |

**TDD Compliance**: 6/6 checks passed

---

### Test Layer Distribution

| Layer | Tests | Files | Tools |
|-------|-------|-------|-------|
| Unit | ~110 | `test_file_search_walk.py`, `test_file_search_adapter.py`, `test_file_search_tools.py`, `test_settings.py`, `test_errors.py`, `test_schemas.py` | pytest-mock (`mocker`) |
| Integration | ~14 | `test_server.py` (FastMCP in-process `Client`, incl. task 7.3's real-filesystem walk test) | pytest-asyncio / FastMCP `Client` |
| E2E | 0 | — | not available on WSL2 (documented, out of scope) |
| **Total (this change's files, isolated run)** | **124** | 4 files | |

---

### Changed File Coverage

Coverage analysis skipped — no coverage tool detected (`pytest-cov` not installed, `coverage.available: false`).

---

### Assertion Quality

Reviewed `tests/test_file_search_walk.py`, `tests/test_file_search_adapter.py`, `tests/test_file_search_tools.py`, and the file-search-resilience-related additions to `tests/test_server.py` line-by-line for the security-critical scenarios plus a scan of the rest.

- No tautologies (`assert True`, `expect(1)==1`) found.
- No ghost loops over possibly-empty collections found; every assertion follows a call into production code (`walk_filename`, `PowerShellSearchBridge`, `FallbackSearchAdapter`, `file_search`, `file_get_info`) with real preconditions set up per scenario.
- No smoke-test-only patterns (every test asserts a specific value/behavior, not just "did not crash").
- Escaper table (`test_escape_like_value_table`) asserts the *exact* expected escaped literal per case (not just "no exception") — strong triangulation, not trivial.
- `test_bridge_argv_is_exactly_the_pinned_flag_set` asserts the full argv list equals a literal expected list — the strongest possible bypass check (no room for an extra, unaccounted-for argv element).
- Hostile-input tests (`o'brien`, `$(Get-Date)`) assert BOTH that the value is absent from argv AND present (correctly escaped/verbatim) in the stdin `sql` — not a one-sided check.

**Assertion quality**: ✅ All assertions verify real behavior

---

### Quality Metrics

**Linter**: ➖ Not available (none configured)
**Type Checker**: ➖ Not available (none configured)

---

### Spec Compliance Matrix

| Requirement | Scenario | Test | Result |
|-------------|----------|------|--------|
| filesystem-walk-search: Walk Scope | Walk runs after the roots check | `test_file_search_tools.py::test_search_filename_only_succeeds_under_unindexed_scope` (walk called with the already-validated `search_roots`) | ✅ COMPLIANT |
| filesystem-walk-search: Case-Insensitive Substring Match | Substring match on entry name | `test_file_search_walk.py::test_walk_matches_filename_case_insensitive_substring`, `::test_walk_match_is_case_insensitive_on_the_query_too` | ✅ COMPLIANT |
| filesystem-walk-search: Result and Resource Caps | Row cap truncates and flags | `test_file_search_walk.py::test_walk_result_cap_truncates_and_flags_truncated` | ✅ COMPLIANT |
| filesystem-walk-search: Result and Resource Caps | Time or dir budget stops early | `::test_walk_time_budget_stops_early_and_flags_truncated`, `::test_walk_dir_count_budget_stops_early_and_flags_truncated` | ✅ COMPLIANT |
| filesystem-walk-search: Result and Resource Caps | Walk completes within all caps | `::test_walk_completes_within_all_caps_when_dir_budget_exactly_suffices`, `::test_walk_completes_within_all_caps_returns_not_truncated` | ✅ COMPLIANT |
| filesystem-walk-search: No Reparse Point Traversal | Reparse point dir not descended | `::test_walk_skips_reparse_point_directory_without_descending`, `::test_walk_skips_symlinked_directory_without_descending` | ✅ COMPLIANT |
| filesystem-walk-search: Unreadable Directories Skipped | PermissionError on one subdir | `::test_walk_permission_error_on_one_subdir_does_not_abort` | ✅ COMPLIANT |
| powershell-search-bridge: Invocation Only on ADO Failure | Bridge not invoked when ADO succeeds | `test_file_search_adapter.py::test_fallback_search_skips_bridge_when_primary_succeeds` | ✅ COMPLIANT |
| powershell-search-bridge: Invocation Only on ADO Failure | Bridge invoked after ADO raises | `::test_fallback_search_invokes_bridge_after_primary_raises_unavailable` | ✅ COMPLIANT |
| powershell-search-bridge: Subprocess Transport and Output Contract | Valid JSON stdout parsed | `::test_bridge_search_parses_valid_json_rows_into_file_summaries`, `::test_bridge_search_single_row_collapsed_to_bare_object_still_parses` | ✅ COMPLIANT |
| powershell-search-bridge: Values Passed as Data via Stdin | Caller values absent from argv, present on stdin | `::test_bridge_caller_values_absent_from_argv_present_on_stdin` | ✅ COMPLIANT |
| powershell-search-bridge: SQL Value Escaping | Phrase single quote escaped | `::test_bridge_search_sql_has_quote_doubled_phrase` | ✅ COMPLIANT |
| powershell-search-bridge: SQL Value Escaping | Filename LIKE metachars neutralized | `::test_bridge_search_sql_reuses_build_search_sql_with_like_escaped_filename` | ✅ COMPLIANT |
| powershell-search-bridge: SQL Value Escaping | Escaper table (9 hostile/edge cases) | `::test_escape_like_value_table` (parametrized ×9) | ✅ COMPLIANT |
| powershell-search-bridge: Hostile Input Never Reaches PowerShell Evaluation | Single quote → results/typed error, not parse error | `::test_bridge_search_hostile_single_quote_filename_returns_results_not_parse_error` | ✅ COMPLIANT |
| powershell-search-bridge: Hostile Input Never Reaches PowerShell Evaluation | `$(Get-Date)` never evaluated | `::test_bridge_search_command_substitution_phrase_never_reaches_argv_or_command_string` | ✅ COMPLIANT |
| powershell-search-bridge: Host Pinning | Pinned absolute path + exact flags | `::test_bridge_search_invokes_pinned_absolute_powershell_with_file_flag`, `::test_bridge_argv_is_exactly_the_pinned_flag_set` | ✅ COMPLIANT |
| powershell-search-bridge: Timeout and Failure Mapping | Timeout → typed error, "timed out" | `::test_bridge_search_timeout_maps_to_windows_search_unavailable` | ✅ COMPLIANT |
| powershell-search-bridge: Timeout and Failure Mapping | Spawn-blocked → distinctly-worded typed error | `::test_bridge_search_spawn_blocked_maps_to_distinctly_worded_unavailable_error` | ✅ COMPLIANT |
| powershell-search-bridge: Timeout and Failure Mapping | Nonzero exit / malformed JSON | `::test_bridge_search_nonzero_exit_code_maps_to_windows_search_unavailable`, `::test_bridge_search_malformed_json_stdout_maps_to_windows_search_unavailable` | ✅ COMPLIANT |
| powershell-search-bridge: Both-Transports-Exhausted Messaging | Combined failure names filename fallback | `test_file_search_tools.py::test_search_phrase_only_both_transports_fail_message_states_filename_still_works` (tool layer, not the adapter/bridge layer — see note below) | ⚠️ PARTIAL (see note) |
| file-search: Filename Queries Do Not Require the Index | Filename succeeds with index unavailable | `test_file_search_tools.py::test_search_filename_only_never_calls_adapter_even_if_it_would_raise` | ✅ COMPLIANT |
| file-search: Filename Queries Do Not Require the Index | Filename succeeds under unindexed root | `::test_search_filename_only_succeeds_under_unindexed_scope`; end-to-end via `test_server.py::test_file_search_tool_filename_only_walks_real_filesystem_under_unindexed_scope` (task 7.3) | ✅ COMPLIANT |
| file-search: Combined Filename and Phrase Query Rule | Intersects walk and index results | `test_file_search_tools.py::test_search_combined_intersects_walk_and_index_results` | ✅ COMPLIANT |
| file-search: Combined Filename and Phrase Query Rule | Fails when index leg exhausted | `::test_search_combined_propagates_unavailable_error_when_index_leg_exhausted` | ✅ COMPLIANT |
| file-search: Search Output Shape | Empty result set | `::test_search_filename_only_empty_result_returns_empty_list_not_error` | ✅ COMPLIANT |
| file-search: Search Output Shape | Truncated walk flagged | `::test_search_filename_only_truncated_walk_is_flagged` | ✅ COMPLIANT |
| file-search: Windows Search Unavailable | Both transports fail on phrase query | `::test_search_phrase_only_both_transports_fail_message_states_filename_still_works` | ✅ COMPLIANT |
| file-search: Windows Search Unavailable | Filename-only unaffected by index failure | `::test_search_filename_only_never_calls_adapter_even_if_it_would_raise` | ✅ COMPLIANT |
| file-get-info: Path Not Found On Disk | Nonexistent path → `path_not_found` | `test_file_search_tools.py::test_get_info_nonexistent_path_raises_path_not_found_error`; `test_server.py::test_file_get_info_tool_nonexistent_path_surfaces_path_not_found_error` | ✅ COMPLIANT |
| file-get-info: Index Enrichment Failure Never Surfaces | Index unavailable during enrichment | `::test_get_info_index_unavailable_during_enrichment_does_not_fail_call` | ✅ COMPLIANT |
| file-get-info: Get Info Output Shape | Real unindexed file → full stat metadata | `::test_get_info_real_unindexed_file_returns_stat_facts_no_error` | ✅ COMPLIANT |
| file-get-info: Get Info Output Shape | Indexed file → enrichment populated | `::test_get_info_indexed_file_gets_enrichment_fields_populated` | ✅ COMPLIANT |
| windows-search-adapter: Fallback Transport Ordering | ADO success skips bridge | `test_file_search_adapter.py::test_fallback_search_skips_bridge_when_primary_succeeds` | ✅ COMPLIANT |
| windows-search-adapter: Fallback Transport Ordering | ADO failure falls through to bridge | `::test_fallback_search_invokes_bridge_after_primary_raises_unavailable` | ✅ COMPLIANT |
| windows-search-adapter: Fallback Transport Ordering | Both exhausted propagates unchanged | `::test_fallback_search_both_transports_exhausted_propagates_unchanged` | ✅ COMPLIANT |
| windows-search-adapter: Enrichment Lookups Use the Same Fallback Ordering | Enrichment falls back to bridge | `::test_fallback_get_info_invokes_bridge_after_primary_raises_unavailable` | ✅ COMPLIANT |
| windows-search-adapter: Enrichment Lookups Use the Same Fallback Ordering | Exhausted raises unavailable, not not-found | `::test_fallback_get_info_both_transports_exhausted_propagates_unchanged`, `::test_fallback_get_info_file_not_found_never_tries_bridge` | ✅ COMPLIANT |

**Compliance summary**: 34/35 scenarios fully compliant, 1 PARTIAL (documented, functionally satisfied — see note below). No UNTESTED, no FAILING scenarios.

**Note on the one PARTIAL**: the powershell-search-bridge spec's "Both-Transports-Exhausted Messaging" requirement is worded as if it belongs to the bridge/adapter capability, but its own scenario ("WHEN a phrase query executes") is satisfied end-to-end at the tool layer, not inside `FallbackSearchAdapter`/`PowerShellSearchBridge` themselves. This is a deliberate, well-documented resolution of a real conflict between two spec deltas: `windows-search-adapter/spec.md`'s "Fallback Transport Ordering" requirement explicitly states the adapter seam "stays config- and message-neutral" and that "the tool layer... is responsible for adding the filename-still-works messaging," while `powershell-search-bridge/spec.md`'s own requirement reads as if the bridge/fallback layer should produce that message. Batch 2's apply-progress (Deviation #3) flags this explicitly and follows `tasks.md`'s authoritative task 4.3 ("propagates unchanged") + task 5.3 ("phrase-only both-transports-fail message states filename search still works" — a Phase 5/tool-layer task), which is internally consistent with `windows-search-adapter`'s spec. The behavior is correct and tested; only the spec's own internal cross-reference is slightly misleading about which capability owns the test.

---

### Correctness (Static — Structural Evidence)

| Requirement | Status | Notes |
|------------|--------|-------|
| `.ps1` is a dumb executor | ✅ Implemented | Reads only `.sql` from stdin JSON; runs it verbatim via `OleDbCommand.CommandText`; no other field read, no string interpolation, no escaping logic in the script at all |
| Argv is fully static/pinned | ✅ Implemented | `[_PS_EXE, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(_PS_BRIDGE_SCRIPT)]` — every element is a module-level constant or a fixed literal; no caller-controlled value ever appended |
| Shared escaper across both legs | ✅ Implemented | `PowerShellSearchBridge.search()/get_info()` call `_build_search_sql`/`_build_get_info_sql` directly — the exact same functions `WindowsSearchAdapter` calls; verified byte-for-byte via `test_bridge_search_sql_reuses_build_search_sql_with_like_escaped_filename` |
| Escaper table coverage | ✅ Implemented | All 9 spec-named cases present verbatim in `_ESCAPE_LIKE_VALUE_CASES` |
| Filename never touches the index | ✅ Implemented | `file_search()`'s dispatch: `if request.filename and not request.phrase: return _search_filename_only(...)` — no adapter reference in that branch |
| `file_get_info` stat-first | ✅ Implemented | `os.stat(native_path)` runs before any adapter call; `PathNotFoundError` raised on `OSError` before enrichment is attempted |
| Walk guard rails | ✅ Implemented | Result/time/dir caps in `walk_filename`; reparse-point skip via `_is_reparse_point`; `PermissionError`/`OSError` on `os.scandir` caught and skipped |
| No diagnostic/forensic code in repo adapter | ✅ Confirmed | `grep -rn -i "forensic\|diagnostic\|_diag_"` over `tools/`, `server.py` returns no matches |

---

### Coherence (Design)

| Decision | Followed? | Notes |
|----------|-----------|-------|
| Walk lives in `tools/file_search_walk.py` | ✅ Yes | New module, exact signature as designed |
| Composing `FallbackSearchAdapter` implements `FileSearchPort` | ✅ Yes | ADO-then-bridge ordering, `FileNotFoundInIndexError` never triggers fallback |
| PS bridge: pre-built SQL via stdin JSON, dumb executor | ✅ Yes | Matches the revised (post-security-review) design text exactly |
| New `PathNotFoundError`; `FileNotFoundInIndexError` stays adapter-internal | ✅ Yes | `file_get_info`'s enrichment `try/except` catches both `WindowsSearchUnavailableError` and `FileNotFoundInIndexError` |
| `FileSearchResponse` envelope (Batch 1's own naming choice) | ✅ Yes, wired in Batch 3 | Deviation is disclosed in apply-progress and is a reasonable interpretation of ambiguous spec/design wording |

---

### Issues Found

**CRITICAL** (must fix before archive):
None.

**WARNING** (should fix):
1. `deploy/smoke_test.py`'s `_extract_list_result()` does not recognize the actual `{"results": [...], "resultsTruncated": ...}` envelope shape FastMCP produces for `FileSearchResponse` (and the other enveloped response models) — it only matches a singular `{"result": [...]}` key or a bare list. This means the live smoke test's tolerant "0+ hits" checks for the files family (and calendar/mail/tasks, since they share the same envelope pattern) always fall through to the 0-hits branch, masking real hits without ever causing a false FAIL. This predates file-search-resilience (the sibling search-result-caps change introduced the envelope pattern without updating `smoke_test.py`) and Phase 7 explicitly scoped this task as verification-only — correctly not fixed here — but it remains a real, live gap worth a follow-up change since it silently reduces the smoke test's diagnostic value for every enveloped tool family, not just files.
2. The powershell-search-bridge spec's own "Both-Transports-Exhausted Messaging" requirement and scenario read as if that capability's own test suite (`test_file_search_adapter.py`) should cover it, but the (correct, deliberately chosen) implementation covers it only at the tool layer (`test_file_search_tools.py`). This is fully disclosed in apply-progress Batch 2 Deviation #3 and is the right call given `windows-search-adapter/spec.md`'s explicit "stays config- and message-neutral" charter — flagged only so a future spec-archive pass considers rewording the powershell-search-bridge requirement to point at the tool layer explicitly, avoiding the appearance of an untested capability-level requirement.

**SUGGESTION** (nice to have):
1. `walk_filename`'s files-only matching (never returning directories whose name matches `filename`) is a reasonable, tested, disclosed interpretation of an ambiguous spec — worth confirming against real Windows Search index behavior (does a `filename` query there return matching folders?) during a future live-Windows verification pass, per apply-progress Batch 1's own note.
2. `_escape_contains_phrase` silently drops embedded `"` characters (no escape sequence exists for a `CONTAINS()` phrase's literal quote) rather than raising or substituting — behaviorally safe (closes the injection route entirely) but could surprise a caller whose search phrase legitimately contains a quotation mark. Not a security issue; a UX nicety to consider later.

---

### Verdict

**PASS**

All 45 tasks complete, full suite green (451 passed), and every security-critical control the orchestrator asked to be verified hardest was independently confirmed by direct code read plus real test execution: the `.ps1` bridge is a genuine dumb executor with zero user-value interpolation and a fully static argv; the shared `_escape_like_value`/`_build_search_sql`/`_build_get_info_sql` functions are used verbatim by both transports and are covered by the full 9-case hostile/edge-case table; hostile-input and spawn-blocked-vs-timeout scenarios are tested with exact-value assertions, not tautologies; the filesystem walk enforces all three caps with correct truncation semantics and skips reparse points/unreadable directories without aborting; `filename` search never reaches the adapter; `file_get_info` is stat-first with a distinct `path_not_found` error; and no diagnostic/forensic code exists anywhere in the repo's adapter files. The only findings are two pre-existing/disclosed WARNINGS, neither of which is a regression introduced by this change nor a blocker to archiving it.
