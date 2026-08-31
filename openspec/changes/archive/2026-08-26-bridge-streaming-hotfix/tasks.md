# Tasks: PowerShell Search Bridge Streaming Hotfix

## Phase 0: Baseline

- [x] 0.1 Confirm baseline: `.venv/bin/python3.12 -m pytest -q` -> 516 passed

## Phase 1: Config Default Bump (requirement 5)

- [x] 1.1 RED `tests/test_settings.py`: update
      `test_ps_bridge_timeout_seconds_defaults_to_10_when_unconfigured`
      -> `..._defaults_to_30_when_unconfigured`, asserting `30`.
- [x] 1.2 GREEN `tools/settings.py`: `file_search_ps_bridge_timeout_seconds()`
      default `10` -> `30`. `config/settings.yaml`: value and comment
      updated to match.

## Phase 2: Streaming Popen Read + Partial Results on Kill (requirements 1-2)

- [x] 2.1 RED `tests/test_file_search_adapter.py`: replace the
      `subprocess.run`-mocking helpers (`_jsonl`/`_completed`/`_patch_run`/
      `_stdin_sql(run_mock)`) with `Popen`-mocking doubles (`_row_lines`,
      `_FakeStdin`, `_LineStream`, `_FixedReadStream`, `_NoneReadStream`,
      `_FakeProcess`, `_patch_popen`, `_tiny_timeout`,
      `_stdin_sql(process)`) and rewrite every existing bridge test to use
      them. Every test in the bridge section fails against the still-
      `subprocess.run`-based `_invoke()`.
- [x] 2.2 GREEN `tools/file_search_adapter.py`: add `_STREAM_EOF`,
      `_pump_stdout`, `_pump_stderr`, `_reap`, `_diagnostic_suffix`; rewrite
      `PowerShellSearchBridge._invoke()` around `subprocess.Popen` +
      reader-thread/queue streaming under a wall-clock deadline. Confirm
      every rewritten test passes.
- [x] 2.3 Add the core streaming matrix (new tests, not present before
      this hotfix):
      `test_bridge_search_hangs_after_n_rows_returns_partial_truncated_results`,
      `test_bridge_search_killed_by_deadline_zero_rows_message_names_killed_at_seconds`,
      `test_bridge_search_child_dies_after_n_rows_no_sentinel_is_truncated_not_error`,
      `test_bridge_search_child_dies_nonzero_exit_with_rows_and_no_sentinel_is_truncated`,
      `test_bridge_search_zero_rows_no_sentinel_raises_with_exit_code_and_stderr_excerpt`,
      `test_bridge_search_happy_path_sentinel_returns_rows_not_truncated`,
      `test_bridge_search_uses_configured_timeout_as_the_read_deadline`.
- [x] 2.4 Repurpose
      `test_bridge_search_solely_malformed_stdout_is_truncation_not_error`
      (an empty-truncated-result-not-error precedent from
      ps-bridge-jsonl-hotfix) into
      `test_bridge_search_solely_malformed_stdout_with_zero_rows_raises` —
      requirement 4's tightened "zero rows no sentinel always raises" rule
      supersedes the old "malformed last line + zero rows -> empty
      truncated result" behavior.

## Phase 3: Truncation Propagation (requirement 3)

- [x] 3.1 RED `tests/test_file_search_adapter.py`: `__init__` on
      `PowerShellSearchBridge`/`FallbackSearchAdapter` needs a
      `last_search_truncated` attribute; `_StubPort` needs a settable one
      too. New Phase 4.5 tests fail against the pre-hotfix classes (no
      such attribute exists).
- [x] 3.2 GREEN `tools/file_search_adapter.py`: add
      `last_search_truncated` to `PowerShellSearchBridge.__init__`
      (default `False`, set by `search()` after every call from
      `_invoke()`'s returned `truncated` flag), `FallbackSearchAdapter.__init__`
      (default `False`, set by `search()` by mirroring
      `getattr(transport, "last_search_truncated", False)` off whichever
      transport served the result), and a `last_search_truncated: bool =
      False` class attribute on `WindowsSearchAdapter` (documentation —
      ADO never truncates).
- [x] 3.3 RED `tests/test_file_search_tools.py`: add `_TruncatingAdapter`
      stub and truncation-propagation tests for the phrase-only leg
      (`test_search_phrase_only_truncated_adapter_result_is_flagged`,
      `test_search_phrase_only_fake_adapter_without_attribute_is_not_truncated`)
      and the combined leg's OR-semantics
      (`test_search_combined_or_semantics_true_when_only_phrase_leg_truncated`,
      `test_search_combined_or_semantics_true_when_only_walk_leg_truncated`).
      Fail against the pre-hotfix `_search_phrase_only`/`_search_combined`,
      which hardcode/ignore the phrase leg's truncation.
- [x] 3.4 GREEN `tools/file_search.py`: `_search_phrase_only` reads
      `getattr(adapter, "last_search_truncated", False)` instead of
      hardcoding `results_truncated=False`; `_search_combined` ORs the
      same read into its existing walk-truncated flag.

## Phase 4: Failure Diagnostics (requirement 4)

- [x] 4.1 RED/GREEN together with Phase 2 (the diagnostic suffix is part
      of `_invoke()`'s single rewrite): every failure-path test in
      `tests/test_file_search_adapter.py` asserts the exit-condition /
      stderr-excerpt substrings are present
      (`test_bridge_search_zero_rows_no_sentinel_raises_with_exit_code_and_stderr_excerpt`,
      `test_bridge_search_nonzero_exit_code_with_no_rows_maps_to_windows_search_unavailable`,
      `test_bridge_search_stderr_read_returning_none_does_not_crash`,
      `test_bridge_search_unparseable_line_raises_distinctly_worded_unavailable_error`,
      `test_bridge_search_unparseable_line_message_includes_stderr_excerpt_when_present`,
      `test_bridge_search_killed_by_deadline_zero_rows_message_names_killed_at_seconds`).

## Phase 5: Full Suite + Spec/Archive

- [x] 5.1 Run full suite: `.venv/bin/python3.12 -m pytest -q` -> 527
      passed (516 baseline + 11 new net), zero regressions.
- [x] 5.2 Update `openspec/specs/powershell-search-bridge/spec.md`:
      rename/rewrite "Subprocess Transport and Output Contract" ->
      "Subprocess Transport and Streaming Output Contract"; add
      "Wall-Clock Read Deadline and Partial Results on Kill" and "Exposes
      Whether Its Last Search Was Truncated" requirements; replace
      "Timeout and Failure Mapping" with "Failure Mapping and Diagnostic
      Detail".
- [x] 5.3 Update `openspec/specs/file-search/spec.md`: widen "Search
      Output Shape" to cover the phrase-leg's own truncation signal,
      OR'd with the walk's flag.
- [x] 5.4 Record this hotfix's proposal/tasks/apply-progress under
      `openspec/changes/archive/2026-08-26-bridge-streaming-hotfix/`.
