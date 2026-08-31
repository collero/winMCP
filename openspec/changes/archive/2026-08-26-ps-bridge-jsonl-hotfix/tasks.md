# Tasks: PowerShell Search Bridge JSON Lines Hotfix

## Phase 0: Baseline

- [x] 0.1 Confirm baseline: `.venv/bin/python3.12 -m pytest -q` → 456 passed

## Phase 1: Verify the Row Cap (requirement 1)

- [x] 1.1 Confirm `_build_search_sql`/`_build_get_info_sql` are the ONE
      place a row cap is applied, and that `PowerShellSearchBridge` calls
      them verbatim (already true by construction — no code change).
      `get_info` is always `SELECT TOP 1`; `search()`'s cap is whatever
      `top_n` the tool layer resolved (`file_search_max_results`, default
      200).
- [x] 1.2 Add regression tests locking this in:
      `test_build_search_sql_row_cap_is_shared_by_both_transports`,
      `test_build_get_info_sql_is_capped_at_top_1`.

## Phase 2: JSON Lines Output Contract (requirement 2)

- [x] 2.1 RED `tests/test_file_search_adapter.py`: add JSONL test helper
      (`_jsonl`) and rewrite every existing bridge stdout fixture
      (previously a single JSON document/array) to the new line-based
      shape. Existing tests fail against the still-array-parsing
      `_invoke()`.
- [x] 2.2 GREEN `tools/file_search_adapter.py`: add
      `_parse_bridge_stdout()` (line-by-line parser, returns
      `(rows, results_truncated)`) and `_BridgeUnparseableLineError`;
      rewrite `_invoke()` to call it instead of `json.loads()` on the
      whole document. Confirm rewritten fixtures pass.
- [x] 2.3 GREEN `tools/ps_bridge_search.ps1`: emit one compact JSON
      object per row (flushed immediately) instead of accumulating an
      array and serializing once at the end; write a final
      `{"done": true, "count": N}` sentinel line after the reader loop.
- [x] 2.4 Add truncation-as-result tests (must NOT raise):
      `test_bridge_search_missing_sentinel_returns_partial_rows_not_error`
      (sentinel never written),
      `test_bridge_search_partial_last_line_returns_earlier_rows_not_error`
      (last line is a cut-mid-object fragment),
      `test_parse_bridge_stdout_reports_results_truncated_true_when_sentinel_missing`,
      `test_parse_bridge_stdout_reports_results_truncated_false_when_sentinel_present`.
- [x] 2.5 Add genuine-corruption test (MUST raise, distinctly worded):
      `test_bridge_search_unparseable_line_raises_distinctly_worded_unavailable_error`
      (a non-last line that isn't JSON at all),
      `test_parse_bridge_stdout_raises_on_non_last_line_corruption`.
- [x] 2.6 Repurpose
      `test_bridge_search_single_row_collapsed_to_bare_object_still_parses`
      (the old PowerShell-5.1-array-collapse quirk, which cannot occur
      under JSON Lines) into
      `test_bridge_search_single_row_plus_sentinel_parses` — same basic
      single-row coverage, updated rationale.

## Phase 3: Message-Assembly Punctuation Fix (requirement 3)

- [x] 3.1 RED `tests/test_file_search_adapter.py`: add full-exact-message
      assertions to the existing timeout/spawn-blocked tests, plus a new
      `test_bridge_search_nonzero_exit_code_maps_to_windows_search_unavailable`
      exact-message assertion. (These messages were already correct in
      isolation — no join happens at this layer — so these are
      regression locks, not RED cases.)
- [x] 3.2 RED `tests/test_file_search_tools.py`: add
      `test_search_phrase_only_ado_then_bridge_failed_full_message_is_properly_punctuated`
      asserting the FULL combined message. Confirms the bare-space join
      bug (`f"{exc} {_FILENAME_STILL_WORKS_HINT}"`) before the fix:
      `"Windows Search index unreachable filename search still works — ..."`
      (no separator between "unreachable" and "filename").
- [x] 3.3 GREEN `tools/file_search.py`:
      `_raise_unavailable_with_filename_hint()` joins with `'. '` instead
      of a bare space. Confirm the new test passes with properly
      punctuated output: `"Windows Search index unreachable. filename
      search still works — ..."`.

## Phase 4: Full Suite + Spec/Archive

- [x] 4.1 Run full suite: `.venv/bin/python3.12 -m pytest -q` → 464 passed
      (456 baseline + 9 new − 1 repurposed-in-place, net +8), zero
      regressions
- [x] 4.2 Update `openspec/specs/powershell-search-bridge/spec.md`:
      rewrite "Subprocess Transport and Output Contract" for JSON Lines;
      add "Truncated Stream Is a Result, Not an Error" requirement;
      update the "Both-Transports-Exhausted Messaging" scenario for the
      punctuation fix.
- [x] 4.3 Record this hotfix's proposal/tasks/apply-progress under
      `openspec/changes/archive/2026-08-26-ps-bridge-jsonl-hotfix/`.
- [x] 4.4 Note (not implemented): distinguishing "capped at limit" vs.
      "walk gave up early" in the filesystem-walk leg's
      `results_truncated`, and plumbing the bridge's own truncation
      signal up through `FileSearchResponse.results_truncated` for
      phrase queries — both recorded as deferred future polish in
      `proposal.md`.
