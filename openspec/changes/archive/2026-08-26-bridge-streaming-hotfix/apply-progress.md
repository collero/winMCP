# Apply Progress: PowerShell Search Bridge Streaming Hotfix

**Mode**: Strict TDD (runner: `.venv/bin/python3.12 -m pytest -q`)

## Baseline

`516 passed` confirmed before any change (Phase 0).

## TDD Cycle Evidence

| Task | Test File | Layer | RED | GREEN | TRIANGULATE | REFACTOR |
|------|-----------|-------|-----|-------|-------------|----------|
| 1.1/1.2 Timeout default bump | `tests/test_settings.py`, `tools/settings.py`, `config/settings.yaml` | Unit | ✅ Updated assertion to `30` fails against the still-`10` default | ✅ Passes after bumping the default and the yaml value/comment | ➖ Single-value change, no triangulation needed | ➖ None needed |
| 2.1/2.2 Streaming `Popen` rewrite | `tests/test_file_search_adapter.py`, `tools/file_search_adapter.py` | Unit | ✅ Replacing every `subprocess.run` mock with `Popen`-mocking doubles broke all 23 pre-existing bridge tests against the still-`subprocess.run`-based `_invoke()` (`AttributeError`/`FileNotFoundError` reaching real `powershell.exe` path resolution) | ✅ All pass after the `_pump_stdout`/`_pump_stderr`/`_reap`/`_diagnostic_suffix` helpers + rewritten `_invoke()` streaming loop | ✅ Escaping/argv/stdin/hostile-input/happy-path/get_info coverage all re-exercised through the new doubles | ➖ None needed |
| 2.3 New streaming matrix | `tests/test_file_search_adapter.py` | Unit | ✅ Written against the target design first (a child that hangs after N rows, a child that exits early with N rows, zero rows + no sentinel) — all failed until the deadline/kill/diagnostic logic existed | ✅ All pass: hang -> kill -> N rows + `truncated=True`; early exit -> N rows + `truncated=True`, no kill; zero rows + no sentinel -> raises with exit descriptor | ✅ 7 new cases across the deadline-kill, early-exit, nonzero-exit, and happy-path shapes | ➖ None needed |
| 2.4 Repurposed truncation-vs-error test | `tests/test_file_search_adapter.py` | Unit | ➖ Old test asserted a behavior (`[]`, no exception) this hotfix deliberately supersedes per requirement 4 | ✅ Renamed/repurposed to assert `WindowsSearchUnavailableError` with "produced no usable output" instead | ➖ N/A | ➖ N/A |
| 3.1/3.2 `last_search_truncated` on the adapters | `tests/test_file_search_adapter.py`, `tools/file_search_adapter.py` | Unit | ✅ New Phase-4.5 tests (`test_fallback_search_last_search_truncated_*`, `test_bridge_last_search_truncated_starts_false_before_any_call`) fail — `AttributeError` — against the pre-hotfix classes | ✅ Pass after adding the attribute to `PowerShellSearchBridge.__init__`/`FallbackSearchAdapter.__init__` (mirroring `getattr(transport, ..., False)`) and the class-level `False` default on `WindowsSearchAdapter` | ✅ 5 cases (bridge default, fallback-mirrors-primary, fallback-mirrors-bridge-true, fallback-mirrors-bridge-false, ADO class-attribute default) | ➖ None needed |
| 3.3/3.4 Tool-layer propagation | `tests/test_file_search_tools.py`, `tools/file_search.py` | Unit | ✅ New `_TruncatingAdapter`-based tests fail against the pre-hotfix `_search_phrase_only` (hardcoded `results_truncated=False`) and `_search_combined` (ignored the phrase leg's flag entirely) | ✅ Pass after both functions read `getattr(adapter, "last_search_truncated", False)` and (for the combined leg) OR it with the walk's own flag | ✅ 4 cases: phrase-only truncated, phrase-only untruncated (FakeFileSearchAdapter, attribute absent), combined OR-true-via-phrase-leg, combined OR-true-via-walk-leg | ➖ None needed |
| 4.1 Diagnostic detail | `tests/test_file_search_adapter.py` | Unit | ✅ Folded into the Phase 2 RED cycle — every failure-path test asserts the exit-condition/stderr-excerpt substrings, which fail until `_diagnostic_suffix`/exit-descriptor logic exists | ✅ Pass once `_invoke()` builds `exit_desc` (`killed@Ns` or `exit code N`) and appends the stderr excerpt via `_diagnostic_suffix` to every raised message | ✅ Covered across zero-rows-nonzero-exit, killed-at-deadline, unparseable-line, and None-stderr cases | ➖ None needed |

### Test Summary
- **Baseline**: 516 passed
- **Final**: 527 passed (net +11)
- **Bridge test section**: fully rewritten around `Popen` mocking
  (`_row_lines`, `_FakeStdin`, `_LineStream`, `_FixedReadStream`,
  `_NoneReadStream`, `_FakeProcess`, `_patch_popen`, `_tiny_timeout`,
  `_stdin_sql(process)` replace `_jsonl`/`_completed`/`_patch_run`/
  `_stdin_sql(run_mock)`)
- **New test functions** (streaming/truncation/diagnostics, not present
  before this hotfix):
  `test_bridge_search_uses_configured_timeout_as_the_read_deadline`,
  `test_bridge_search_hangs_after_n_rows_returns_partial_truncated_results`,
  `test_bridge_search_killed_by_deadline_zero_rows_message_names_killed_at_seconds`,
  `test_bridge_search_child_dies_after_n_rows_no_sentinel_is_truncated_not_error`,
  `test_bridge_search_child_dies_nonzero_exit_with_rows_and_no_sentinel_is_truncated`,
  `test_bridge_search_zero_rows_no_sentinel_raises_with_exit_code_and_stderr_excerpt`,
  `test_bridge_search_nonzero_exit_code_with_no_rows_maps_to_windows_search_unavailable`,
  `test_bridge_search_stderr_read_returning_none_does_not_crash`,
  `test_bridge_search_unparseable_line_message_includes_stderr_excerpt_when_present`,
  `test_bridge_search_happy_path_sentinel_returns_rows_not_truncated`,
  `test_bridge_get_info_immediate_eof_no_sentinel_raises_unavailable_not_file_not_found`,
  `test_fallback_search_last_search_truncated_false_when_primary_succeeds`,
  `test_fallback_search_last_search_truncated_mirrors_bridge_when_bridge_serves_result`,
  `test_fallback_search_last_search_truncated_false_when_bridge_result_is_complete`,
  `test_fallback_search_last_search_truncated_defaults_false_for_plain_windows_search_adapter`,
  `test_bridge_last_search_truncated_starts_false_before_any_call`,
  `test_search_phrase_only_truncated_adapter_result_is_flagged`,
  `test_search_phrase_only_fake_adapter_without_attribute_is_not_truncated`,
  `test_search_combined_or_semantics_true_when_only_phrase_leg_truncated`,
  `test_search_combined_or_semantics_true_when_only_walk_leg_truncated`
- **Tests repurposed in place**: 1 —
  `test_bridge_search_solely_malformed_stdout_is_truncation_not_error` ->
  `test_bridge_search_solely_malformed_stdout_with_zero_rows_raises`
  (the old "empty truncated result, no error" premise is superseded by
  requirement 4's "zero rows no sentinel always raises" rule)
- **Layers used**: Unit only (subprocess/COM always mocked on this
  WSL2 Linux dev host per project policy)
- **Threading note**: the streaming reader's background daemon threads
  (`_pump_stdout`/`_pump_stderr`) are exercised directly by the new test
  doubles (`_LineStream` with `at_end="hang"` blocks on a
  `threading.Event` that is never set) — confirmed non-flaky across 5
  repeated runs of `tests/test_file_search_adapter.py` (`74 passed` each
  time, ~0.72-0.74s), since every timing-sensitive test patches
  `file_search_ps_bridge_timeout_seconds` down to `0.05`s via
  `_tiny_timeout()` rather than waiting out the real default.

## Root Cause (confirmed via reading the existing `_invoke()`, not a live reproduction — no real PowerShell/Windows host available)

`PowerShellSearchBridge._invoke()` called `subprocess.run(...,
timeout=...)`, which only ever returns (or raises) once the child has
fully exited (or `run()`'s own kill-then-communicate-once-more fallback
runs) — even though `tools/ps_bridge_search.ps1` already flushes each
row immediately via `WriteLine`+`Flush()` (ps-bridge-jsonl-hotfix), the
PARENT never read any of that until the whole call returned. A child
killed by the timeout, or one that otherwise died before writing its
final sentinel line, therefore surfaced to Python as though it had
produced nothing at all — exactly BUG-006's reported "PowerShell search
bridge produced no output" on a route where the identical query
succeeds from every other spawn context (the same slow, buffered read
shape, just triggered by a spawn-path-specific slowdown rather than a
universal one — which is why the row cap and a naive "shorten the
timeout" theory were both already ruled out before this investigation).

## Command Log (RED -> GREEN)

```
$ .venv/bin/python3.12 -m pytest -q
516 passed   # Phase 0 baseline

$ .venv/bin/python3.12 -m pytest -q tests/test_file_search_adapter.py
# after rewriting the bridge-mocking helpers to Popen doubles, before
# touching _invoke():
23 failed, 91 passed   # every subprocess.run-based mock/assertion broke

# after the _invoke() streaming rewrite:
1 failed, 68 passed   # test_bridge_search_solely_malformed_stdout_is_truncation_not_error
                       # (superseded premise -- repurposed, see task 2.4)

# after repurposing that test + adding the Phase 3/4 truncation and
# diagnostic tests:
74 passed   # full bridge adapter test file

$ .venv/bin/python3.12 -m pytest -q
527 passed   # full suite, zero regressions (516 baseline + 11 net new)
```

## Deferred (noted, not implemented in this hotfix)

- No further deferrals from the prior ps-bridge-jsonl-hotfix remain open
  for the PHRASE leg — its "plumb the bridge's own truncation signal up
  through `FileSearchResponse.results_truncated`" deferral is exactly
  what this hotfix implements (task 3).
- The filesystem-walk leg's own "capped at limit" vs. "walk gave up
  early" distinction within its own `results_truncated` flag remains a
  separate, still-open, pre-existing concern (unrelated to the bridge)
  — not touched here.
