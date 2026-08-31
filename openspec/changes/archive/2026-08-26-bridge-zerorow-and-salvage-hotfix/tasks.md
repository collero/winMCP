# Tasks: Bridge Zero-Row Rule, Per-Column Salvage, and Invocation Debug Log

## Phase 0: Baseline

- [x] 0.1 Confirm baseline: `.venv/bin/python3.12 -m pytest -q` -> 527 passed

## Phase 1: Zero-Row Rule Closes the Script-Error-Line Blind Spot

- [x] 1.1 RED `tests/test_file_search_adapter.py`:
      `test_bridge_search_script_error_json_line_with_zero_real_rows_raises`
      (a lone `{"error": "..."}` stdout line, no sentinel, exit code 1)
      and
      `test_bridge_search_script_error_json_line_after_real_rows_not_counted_as_row`
      (one real row, then an `{"error": ...}` line, exit code 1). Both
      fail against the pre-fix `_invoke()`: the first raises an unhandled
      `pydantic.ValidationError` while mapping the bogus `{"error": ...}`
      row instead of `WindowsSearchUnavailableError`.
- [x] 1.2 GREEN `tools/file_search_adapter.py`: in `_invoke_impl()`'s
      streaming loop, a parsed dict containing `"error"` (and not
      `"done"`) is folded into `stderr_sink` and the loop breaks WITHOUT
      appending it to `rows` — the existing "zero rows parsed +
      (killed/died/no-sentinel) => raise" / "some rows + no sentinel =>
      truncated result" rule (unchanged) now handles both new cases
      correctly. Both tests pass.

## Phase 2: Per-Column/Per-Row Salvage (`tools/ps_bridge_search.ps1`)

- [x] 2.1 Add `Read-FieldSafe($reader, $columnName)`: wraps
      `$reader[$columnName]` in try/catch, returns `$null` on failure,
      and writes `column '<name>' unreadable: <message>` to stderr the
      FIRST time each column name fails (tracked via
      `$script:LoggedColumnFailures`), staying silent on repeats of the
      same column.
- [x] 2.2 Replace every direct `$reader["System.*"]` read inside the
      per-row hashtable construction (both the always-present summary
      columns and the get_info-only `DateCreated`/`AutoSummary` columns)
      with `Read-FieldSafe` calls.
- [x] 2.3 Wrap the per-row body (hashtable construction through
      `WriteLine`+`Flush`+`$count++`) in its own try/catch: on failure,
      write `row skipped: <message>` to stderr and `continue` to the next
      `$reader.Read()` iteration rather than letting the exception escape
      the `while` loop. Sentinel emission (after the loop) is unchanged —
      still reachable only by exhausting `$reader.Read()` cleanly.
- [x] 2.4 Not unit-tested directly (no real PowerShell on this WSL2 dev
      host, per this file's own long-standing precedent) — verified by
      manual review: braces balanced, `continue` inside a `while`'s
      try/catch behaves as the next-iteration skip PowerShell 5.1/7 both
      guarantee, `Read-FieldSafe`'s signature matches every call site.

## Phase 3: Permanent Bridge Invocation Debug Log

- [x] 3.1 `tools/settings.py`: add `file_search_bridge_debug_log() ->
      bool`, reading `file_search_bridge_debug_log` from
      `config/settings.yaml` (default `True`), live via `load_settings()`
      every call, matching every other settings reader's discipline.
      `config/settings.yaml`: add the key (`true`) plus an explanatory
      comment (default true for this diagnostic build; flip to false once
      BUG-006 closes).
- [x] 3.2 `tools/file_search_adapter.py`: add module constant
      `_BRIDGE_DEBUG_LOG_PATH = _PS_BRIDGE_SCRIPT.parent.parent /
      "bridge_invocations.log"` and `_log_bridge_invocation(...)` (checks
      the config flag first, wraps timestamp/json/file-write fully in
      `try/except`, never raises).
- [x] 3.3 Split `_invoke()` into a thin outer wrapper (starts a timer,
      builds a mutable `record` dict, calls `_invoke_impl()`, logs via a
      `finally` regardless of return/raise) and `_invoke_impl()` (the
      original body, now setting `record["rows_streamed"]` /
      `["sentinel_seen"]` / `["exit_condition"]` / `["stderr_excerpt"]` at
      every meaningful exit point: spawn-blocked, corrupt-line, the
      computed `exit_desc` shared by both the zero-row-raise and the
      success/truncated-return paths, and the blanket unforeseen-exception
      handler).
- [x] 3.4 RED then GREEN `tests/test_file_search_adapter.py`: four new
      tests —
      `test_bridge_invocation_debug_log_writes_expected_line_shape_when_enabled`,
      `test_bridge_invocation_debug_log_writes_nothing_when_disabled`,
      `test_bridge_invocation_debug_log_written_even_when_search_raises`,
      `test_bridge_invocation_debug_log_never_raises_when_write_fails` —
      patching `_BRIDGE_DEBUG_LOG_PATH` to a `tmp_path` file (or an
      unwritable path for the last case) and
      `file_search_bridge_debug_log` directly. All pass against the
      Phase 3.1-3.3 implementation (written and confirmed against the
      target design; the first run already passed 3/4 immediately, with
      one test assertion corrected — `sql_first_120`'s exact substring
      expectation, not a production-code defect).

## Phase 4: Full Suite + Spec/Archive

- [x] 4.1 Run full suite: `.venv/bin/python3.12 -m pytest -q` -> 533
      passed (527 baseline + 6 new: 2 zero-row-rule + 4 debug-log), zero
      regressions.
- [x] 4.2 Update `openspec/specs/powershell-search-bridge/spec.md`: add
      "Script-Reported Failure Line Is Never Counted As a Row" and
      "Bridge Invocation Debug Log" requirements with scenarios.
- [x] 4.3 Record this hotfix's proposal/tasks/apply-progress under
      `openspec/changes/archive/2026-08-26-bridge-zerorow-and-salvage-hotfix/`.
