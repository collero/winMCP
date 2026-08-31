# Apply Progress: Bridge Zero-Row Rule, Per-Column Salvage, and Invocation Debug Log

**Mode**: Strict TDD (runner: `.venv/bin/python3.12 -m pytest -q`; subprocess/COM always mocked on this WSL2 Linux dev host)

## Baseline

`527 passed` confirmed before any change (Phase 0).

## TDD Cycle Evidence

| Task | Test File | Layer | RED | GREEN | TRIANGULATE | REFACTOR |
|------|-----------|-------|-----|-------|-------------|----------|
| 1.1/1.2 Zero-row rule closes the script-error-line blind spot | `tests/test_file_search_adapter.py`, `tools/file_search_adapter.py` | Unit | ✅ Both new tests fail against the pre-fix `_invoke()`: `test_..._with_zero_real_rows_raises` and `test_..._after_real_rows_not_counted_as_row` both hit an unhandled `pydantic.ValidationError` inside `_row_from_mapping` (`last_modified` required, got `None` from the bogus `{"error": ...}` row) instead of the expected `WindowsSearchUnavailableError`/truncated-result behavior — confirmed via `pytest -k script_error_json_line`, 2 failed | ✅ After adding the `isinstance(parsed, dict) and "error" in parsed` branch (folds the message into `stderr_sink`, breaks without appending to `rows`), both tests pass; full bridge file re-run at 76 passed (74 baseline + 2) | ✅ Two angles: zero real rows (raises) and real-rows-then-error-line (truncated, error line dropped, not padded) | ➖ None needed |
| 2.1-2.3 Per-column/per-row salvage | `tools/ps_bridge_search.ps1` | N/A (not unit-tested — see Phase 2.4) | ➖ No RED possible: no real PowerShell on this WSL2 dev host, per this file's own long-standing precedent (same as every prior `.ps1`-touching hotfix) | ➖ Verified by manual review instead: `Read-FieldSafe` added, every `$reader["System.*"]` call site in the per-row hashtable replaced, per-row body wrapped in try/catch with `continue`, sentinel emission left untouched (still only reachable by exhausting `$reader.Read()` cleanly) | ➖ N/A | ➖ N/A |
| 3.1-3.3 Debug log plumbing | `tools/settings.py`, `config/settings.yaml`, `tools/file_search_adapter.py` | Unit | ➖ Implemented directly (settings getter + module constant + `_invoke`/`_invoke_impl` split are mechanical plumbing with no meaningful pre-existing behavior to break) | — | — | — |
| 3.4 Debug log behavior | `tests/test_file_search_adapter.py` | Unit | ✅ Written against the target design first; `pytest -k debug_log` initial run: 3 passed, 1 failed (`test_..._writes_expected_line_shape_when_enabled` asserted `"Informa" in record["sql_first_120"]`, but the SELECT column list alone exceeds 120 chars before the `CONTAINS()` clause — a test-assertion bug, not a production defect) | ✅ Removed the over-specific substring assertion; re-run: 4 passed | ✅ 4 cases: enabled (full shape incl. `sql_first_120`/`duration_seconds`/`utc`), disabled (no file), written-even-on-raise (captures exit code 1 + stderr "boom"), write-failure-never-raises (unwritable path, `search()` still returns normally) | ➖ None needed |

### Test Summary
- **Baseline**: 527 passed
- **Final**: 533 passed (net +6)
- **New test functions**:
  `test_bridge_search_script_error_json_line_with_zero_real_rows_raises`,
  `test_bridge_search_script_error_json_line_after_real_rows_not_counted_as_row`,
  `test_bridge_invocation_debug_log_writes_expected_line_shape_when_enabled`,
  `test_bridge_invocation_debug_log_writes_nothing_when_disabled`,
  `test_bridge_invocation_debug_log_written_even_when_search_raises`,
  `test_bridge_invocation_debug_log_never_raises_when_write_fails`
- **Layers used**: Unit only (subprocess/COM always mocked on this WSL2
  Linux dev host per project policy); `tools/ps_bridge_search.ps1`'s
  changes have no direct pytest coverage, same long-standing precedent as
  every prior hotfix touching that file — verified by manual review only.

## Root Cause (confirmed via a new RED test against the actual codebase, not a live Windows reproduction)

Auditing `PowerShellSearchBridge._invoke()`'s existing streaming loop
(already covering the documented zero-row matrix from
bridge-streaming-hotfix) found one uncovered shape:
`tools/ps_bridge_search.ps1`'s own top-level `catch` writes a single
valid-JSON `{"error": "..."}` line to STDOUT (not stderr) before exiting
nonzero. That line parses as valid JSON and is not the `{"done":
...}` sentinel, so the pre-fix loop appended it to `rows` as if it were
a genuine data row. Constructing this exact stdout shape in a new test
confirmed the failure mode directly: `_row_from_mapping` built a
`FileSummary` from the bogus dict (`path=""`, `name=""`,
`last_modified=None`), and pydantic's required-`datetime` validation on
`last_modified` raised `pydantic.ValidationError` — an untyped exception
escaping `PowerShellSearchBridge.search()`'s documented `FileSearchPort`
contract entirely. One layer up, `tools/file_search.py`'s BUG-007
blanket-exception guard (`except Exception as exc:` in
`_search_phrase_only`/`_search_combined`) does catch this and re-raises
as a typed `WindowsSearchUnavailableError`, so the tool-layer boundary
was never actually broken in the way BUG-007 was — but the operator-
facing message became a generic "file search adapter failed
unexpectedly: 1 validation error for FileSummary..." instead of the
bridge's own purpose-built exit-condition/stderr diagnostic, and if the
bogus row had happened to pass pydantic validation (e.g. a schema change
relaxing `last_modified` to optional in the future) it would instead
have silently reached `_drop_outside_allowed_roots` and been filtered
out as an empty-path row — reproducing exactly BUG-006's live-reported
symptom (`{"results": [], "resultsTruncated": true}`, no error at all).
Excluding the `{"error": ...}` line from `rows` at the source closes
both failure modes at once.

## Deviations From the Plan

None. All three pieces (zero-row rule fix, `.ps1` per-column/per-row
salvage, config-gated debug log) match the task brief exactly; the only
adjustment during implementation was a test-assertion correction (task
3.4's `sql_first_120` substring check), not a scope or design change.
