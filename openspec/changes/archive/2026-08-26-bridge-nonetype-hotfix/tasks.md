# Tasks: PowerShell Bridge NoneType Stdout Hotfix

## Phase 0: Baseline

- [x] 0.1 Confirm baseline: `.venv/bin/python3.12 -m pytest -q` → 486 passed

## Phase 1: Bridge-Layer RED — `None`/empty stdout, `None` stderr, blanket mapping

- [x] 1.1 RED `tests/test_file_search_adapter.py`: add
      `test_bridge_search_stdout_none_maps_to_windows_search_unavailable_not_crash`
      (the exact BUG-007 reproduction shape — `completed.stdout=None`,
      `returncode=0` — must raise the typed error, not a raw
      `AttributeError`).
- [x] 1.2 RED: add
      `test_bridge_search_stdout_empty_string_maps_to_windows_search_unavailable`
      (same shape with `stdout=""`).
- [x] 1.3 RED: add
      `test_bridge_search_stdout_none_raises_distinctly_worded_error`
      asserting the message names "no output", not "unparseable".
- [x] 1.4 RED: add
      `test_bridge_get_info_stdout_none_maps_to_windows_search_unavailable`
      (same guard on the `get_info()` leg).
- [x] 1.5 RED: add
      `test_bridge_search_solely_malformed_stdout_is_truncation_not_error`
      (a single wholly-malformed line with no sentinel — per
      `_parse_bridge_stdout`'s existing last-line rule this is already a
      truncation result, not an error; locked in as a regression guard
      alongside the new `None`/empty-stdout cases).
- [x] 1.6 RED: add
      `test_bridge_search_nonzero_exit_code_with_none_stderr_does_not_crash`
      (`returncode=1`, `stderr=None` — must not raise a fresh
      `AttributeError` from `.strip()` while building the typed error's
      own message).
- [x] 1.7 RED: add
      `test_bridge_search_timeout_expired_with_stdout_none_maps_to_unavailable`
      (triangulation: `TimeoutExpired`'s own `.stdout` defaults to `None`
      — confirms the existing timeout branch never touches it).
- [x] 1.8 RED: add
      `test_bridge_search_unexpected_exception_during_invoke_maps_to_unavailable_not_raw`
      and
      `test_bridge_get_info_unexpected_exception_during_invoke_maps_to_unavailable`
      (a bare `ValueError`/`RuntimeError` from `subprocess.run` — a type
      this method's specific `except` clauses do not enumerate — must
      still map to the typed error).
- [x] 1.9 Confirm all 9 new adapter-layer tests fail against the
      unmodified `_invoke()` (RED confirmed: `AttributeError`s and raw
      exception types observed).

## Phase 2: Bridge-Layer GREEN

- [x] 2.1 GREEN `tools/file_search_adapter.py::PowerShellSearchBridge._invoke()`:
      guard `completed.stderr` with `(completed.stderr or "").strip()` in
      the nonzero-exit branch.
- [x] 2.2 GREEN: add an explicit `if not stdout:` check (covers both
      `None` and `""`) BEFORE calling `_parse_bridge_stdout()`, raising
      `WindowsSearchUnavailableError("PowerShell search bridge produced
      no output")`.
- [x] 2.3 GREEN: wrap the entire method body in `try`/`except
      WindowsSearchUnavailableError: raise` / `except Exception as exc:
      raise WindowsSearchUnavailableError(...) from exc` — the blanket
      mapping requirement. Confirm all Phase 1 tests pass.

## Phase 3: Tool-Layer RED — hostile adapter contract property test

- [x] 3.1 RED `tests/test_file_search_tools.py`: add `_HostileAdapter`
      (raises an arbitrary exception, or returns `None`, from both
      `search()`/`get_info()`) and the `_HOSTILE_BEHAVIORS` matrix
      (`AttributeError`, `RuntimeError`, `KeyError`, `TypeError`,
      `None`-return).
- [x] 3.2 RED: add
      `test_search_phrase_only_hostile_adapter_never_raises_untyped_error`
      (parametrized) — asserts the outcome is either a `FileSearchResponse`
      or a `CalendarToolError` subclass, never anything else.
- [x] 3.3 RED: add
      `test_search_combined_hostile_adapter_never_raises_untyped_error`
      (same matrix, combined filename+phrase dispatch, walk mocked to
      return a nonempty candidate so the adapter leg actually runs).
- [x] 3.4 RED: add
      `test_search_filename_only_hostile_adapter_is_unaffected`
      (triangulation: filename-only never touches the adapter at all —
      always succeeds regardless of the hostile behavior).
- [x] 3.5 RED: add
      `test_get_info_hostile_adapter_enrichment_failure_never_surfaces`
      (strict, not either/or — per the file-get-info spec's existing
      "Index Enrichment Failure Never Surfaces" requirement, `file_get_info`
      must always return a `FileDetail` with `kind`/`snippet` left `None`,
      never raise, for any hostile adapter behavior including a `None`
      return).
- [x] 3.6 Confirm all new tool-layer tests fail against unmodified
      `tools/file_search.py` (RED confirmed: raw `AttributeError`/
      `RuntimeError`/`KeyError`/`TypeError` escaping `file_search()`, and
      a raw `AttributeError` from `detail.kind` on a `None` `detail`
      escaping `file_get_info()`).

## Phase 4: Tool-Layer GREEN

- [x] 4.1 GREEN `tools/file_search.py::_search_phrase_only`: add
      `except Exception as exc:` after the existing
      `WindowsSearchUnavailableError` branch, mapping to
      `WindowsSearchUnavailableError` + the filename-still-works hint;
      guard the adapter's return value with `results = results or []`.
- [x] 4.2 GREEN: apply the identical pattern to `_search_combined`'s
      `adapter.search()` call (`phrase_results`).
- [x] 4.3 GREEN `tools/file_search.py::file_get_info`: widen the
      enrichment `except` clause from `(WindowsSearchUnavailableError,
      FileNotFoundInIndexError)` to bare `Exception`, and move the
      `detail.kind`/`detail.snippet` reads inside the `try` block (so a
      `None` return, which does not raise inside `adapter.get_info()`
      itself, is still caught via the attribute access now happening
      inside the guarded block rather than in an unreachable `else`).
      Remove the now-unused `FileNotFoundInIndexError` import.
- [x] 4.4 Confirm all Phase 3 tests pass; confirm the full
      `tests/test_file_search_adapter.py` + `tests/test_file_search_tools.py`
      suite is green (114 passed).

## Phase 5: Full Suite + Spec/Archive

- [x] 5.1 Run full suite: `.venv/bin/python3.12 -m pytest -q` → 516 passed
      (486 baseline + 30 new), zero regressions.
- [x] 5.2 Update `openspec/specs/powershell-search-bridge/spec.md`:
      widen the "Timeout and Failure Mapping" requirement to cover
      `None`/empty stdout and the blanket exception-mapping obligation;
      add four new scenarios (`None` stdout, empty-string stdout, `None`
      stderr on nonzero exit, an unforeseen exception type).
- [x] 5.3 Record this hotfix's proposal/tasks/apply-progress under
      `openspec/changes/archive/2026-08-26-bridge-nonetype-hotfix/`.
