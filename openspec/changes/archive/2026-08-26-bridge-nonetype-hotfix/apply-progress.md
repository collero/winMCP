# Apply Progress: PowerShell Bridge NoneType Stdout Hotfix

**Mode**: Strict TDD (runner: `.venv/bin/python3.12 -m pytest -q`)

## Baseline

`486 passed` confirmed before any change (Phase 0).

## TDD Cycle Evidence

| Task | Test File | Layer | RED | GREEN | TRIANGULATE | REFACTOR |
|------|-----------|-------|-----|-------|-------------|----------|
| Bridge `stdout`/`stderr` None-guard | `tests/test_file_search_adapter.py` | Unit | ✅ `stdout=None`/`stdout=""` fixtures against the unmodified `_invoke()` raised a raw `AttributeError` from `.splitlines()` inside `_parse_bridge_stdout` — the exact BUG-007 shape | ✅ Passes after the explicit `if not stdout:` pre-check raising `WindowsSearchUnavailableError("...produced no output")` before `_parse_bridge_stdout` is ever called | ✅ 4 cases: `stdout=None`/`stdout=""` on `search()`, `stdout=None` on `get_info()`, and a message-wording assertion distinguishing "no output" from "unparseable" | ➖ None needed |
| Bridge nonzero-exit `stderr=None` guard | `tests/test_file_search_adapter.py` | Unit | ✅ `returncode=1, stderr=None` against the unmodified code raised `AttributeError` from `completed.stderr.strip()` while building the error message itself | ✅ Passes after `(completed.stderr or "").strip()` | ➖ 1 case | ➖ None needed |
| Bridge blanket exception mapping | `tests/test_file_search_adapter.py` | Unit | ✅ A bare `ValueError`/`RuntimeError` from `subprocess.run` (a type none of the specific `except` clauses catch) propagated raw against the unmodified `_invoke()` | ✅ Passes after wrapping the whole method body in `except WindowsSearchUnavailableError: raise` / `except Exception as exc: raise WindowsSearchUnavailableError(...) from exc` | ✅ 2 cases (`search()`, `get_info()`) | ➖ None needed |
| Regression/triangulation locks | `tests/test_file_search_adapter.py` | Unit | ➖ Already true by construction against the fixed code — locking in existing correct behavior, not bug-driven | ✅ Both pass unchanged | ✅ 2 cases (solely-malformed-stdout-is-truncation, `TimeoutExpired` with `stdout=None`) | ➖ None needed |
| Tool-layer hostile-adapter contract (search) | `tests/test_file_search_tools.py` | Unit/Contract | ✅ `_HostileAdapter` raising `AttributeError`/`RuntimeError`/`KeyError`/`TypeError`, or returning `None`, against the unmodified `_search_phrase_only`/`_search_combined` let the raw exception (or, for `None`, a `TypeError` iterating `None` in `_drop_outside_allowed_roots`) escape `file_search()` untyped | ✅ Passes after adding `except Exception as exc:` (mapped to `WindowsSearchUnavailableError` + filename hint) alongside the existing `WindowsSearchUnavailableError` branch, and `results = results or []` | ✅ 2×5 = 10 cases (phrase-only, combined) across the 5-behavior matrix | ➖ None needed |
| Tool-layer hostile-adapter contract (get_info) | `tests/test_file_search_tools.py` | Unit/Contract | ✅ Same matrix against the unmodified `file_get_info`: a raising adapter was already swallowed by the narrower except, but a `None`-returning `get_info()` raised `AttributeError: 'NoneType' object has no attribute 'kind'` in the `else` clause, which the `try`'s `except` cannot catch | ✅ Passes after widening the `except` to bare `Exception` and moving `detail.kind`/`detail.snippet` reads inside the `try` | ✅ 5 cases across the matrix | ➖ None needed |
| Triangulation: filename-only unaffected | `tests/test_file_search_tools.py` | Unit | ➖ Already true by construction (filename-only never calls the adapter) | ✅ Passes unchanged | ✅ 5 cases across the matrix | ➖ None needed |

### Test Summary
- **Net new tests**: 30 (486 → 516)
- **New test functions (adapter layer, 9, unparametrized)**:
  `test_bridge_search_stdout_none_maps_to_windows_search_unavailable_not_crash`,
  `test_bridge_search_stdout_empty_string_maps_to_windows_search_unavailable`,
  `test_bridge_search_stdout_none_raises_distinctly_worded_error`,
  `test_bridge_get_info_stdout_none_maps_to_windows_search_unavailable`,
  `test_bridge_search_solely_malformed_stdout_is_truncation_not_error`,
  `test_bridge_search_nonzero_exit_code_with_none_stderr_does_not_crash`,
  `test_bridge_search_timeout_expired_with_stdout_none_maps_to_unavailable`,
  `test_bridge_search_unexpected_exception_during_invoke_maps_to_unavailable_not_raw`,
  `test_bridge_get_info_unexpected_exception_during_invoke_maps_to_unavailable`
- **New test functions (tool layer, 4, each parametrized over 5 hostile
  behaviors)**:
  `test_search_phrase_only_hostile_adapter_never_raises_untyped_error`,
  `test_search_combined_hostile_adapter_never_raises_untyped_error`,
  `test_search_filename_only_hostile_adapter_is_unaffected`,
  `test_get_info_hostile_adapter_enrichment_failure_never_surfaces`
- **Layers used**: Unit (9), Unit/Contract property test (4 parametrized
  functions)
- **Test doubles added**: `_HostileAdapter` (`tests/test_file_search_tools.py`)
  — a `FileSearchPort` double whose `search()`/`get_info()` either raise
  an arbitrary non-taxonomy exception or return `None`, standing in for
  an adapter that violates its own contract (the exact class of bug
  BUG-007 was).

## Root Cause

1. `PowerShellSearchBridge._invoke()` (`tools/file_search_adapter.py`)
   called `_parse_bridge_stdout(completed.stdout)` unguarded.
   `completed.stdout` was `None` on the failing production path (a broad
   phrase, large result payload — the same volume dependency as BUG-006)
   despite `subprocess.run(..., capture_output=True, text=True)`;
   `_parse_bridge_stdout`'s `stdout.splitlines()` raised a raw
   `AttributeError` that propagated straight through `_invoke()`,
   `PowerShellSearchBridge.search()`, `FallbackSearchAdapter.search()`,
   and `tools/file_search.py::_search_phrase_only` — none of which had
   any handler for a bare `AttributeError` — reaching the MCP tool
   boundary as an untyped exception. The same nonzero-exit branch also
   called `completed.stderr.strip()` unguarded, a second latent `None`
   crash of the identical shape.
2. No blanket exception handler existed around `_invoke()`'s
   spawn/read/parse sequence, so ANY unforeseen exception — not just the
   `None`-stdout case actually observed in production — would have had
   the same untyped-escape outcome.
3. At the tool layer, `_search_phrase_only`/`_search_combined` only
   caught `WindowsSearchUnavailableError` around `adapter.search()`, and
   `file_get_info`'s enrichment leg only caught
   `(WindowsSearchUnavailableError, FileNotFoundInIndexError)` — with the
   `detail.kind`/`detail.snippet` reads placed in the `try`/`except`'s
   `else` clause, which is unreachable from that same `except` (a `None`
   return from `get_info()`, which itself does not raise, then crashes on
   `detail.kind` outside any handler). Both gaps meant even a fully-fixed
   bridge would still be one hostile/buggy `FileSearchPort` implementation
   away from leaking an untyped exception.

## Command Log (RED → GREEN)

```
$ .venv/bin/python3.12 -m pytest -q
486 passed  # Phase 0 baseline

$ .venv/bin/python3.12 -m pytest -q tests/test_file_search_adapter.py tests/test_file_search_tools.py
# after adding all new tests, before touching tools/file_search_adapter.py or tools/file_search.py:
FAILED tests/test_file_search_adapter.py::test_bridge_search_stdout_none_maps_to_windows_search_unavailable_not_crash
FAILED tests/test_file_search_adapter.py::test_bridge_search_stdout_empty_string_maps_to_windows_search_unavailable
FAILED tests/test_file_search_adapter.py::test_bridge_search_stdout_none_raises_distinctly_worded_error
FAILED tests/test_file_search_adapter.py::test_bridge_get_info_stdout_none_maps_to_windows_search_unavailable
FAILED tests/test_file_search_adapter.py::test_bridge_search_nonzero_exit_code_with_none_stderr_does_not_crash
FAILED tests/test_file_search_adapter.py::test_bridge_search_unexpected_exception_during_invoke_maps_to_unavailable_not_raw
FAILED tests/test_file_search_adapter.py::test_bridge_get_info_unexpected_exception_during_invoke_maps_to_unavailable
FAILED tests/test_file_search_tools.py::test_search_phrase_only_hostile_adapter_never_raises_untyped_error[AttributeError/RuntimeError/KeyError/TypeError/returns_None]  (5)
FAILED tests/test_file_search_tools.py::test_search_combined_hostile_adapter_never_raises_untyped_error[...]  (5)
FAILED tests/test_file_search_tools.py::test_get_info_hostile_adapter_enrichment_failure_never_surfaces[...]  (5)
22 failed, 92 passed in 1.97s

# after tools/file_search_adapter.py::PowerShellSearchBridge._invoke() and
# tools/file_search.py fixes:
$ .venv/bin/python3.12 -m pytest -q tests/test_file_search_adapter.py tests/test_file_search_tools.py
114 passed in 0.30s

$ .venv/bin/python3.12 -m pytest -q
516 passed in 2.65s
```

Zero regressions across the full suite.

## Files Changed

| File | Action | What Was Done |
|------|--------|----------------|
| `tools/file_search_adapter.py` | Modified | `PowerShellSearchBridge._invoke()`: guarded `completed.stderr` with `(completed.stderr or "").strip()`; added an explicit `if not stdout:` check (covers `None` and `""`) raising `WindowsSearchUnavailableError("PowerShell search bridge produced no output")` before `_parse_bridge_stdout` runs; wrapped the entire method body in `except WindowsSearchUnavailableError: raise` / `except Exception as exc: raise WindowsSearchUnavailableError(f"PowerShell search bridge failed unexpectedly: {exc}") from exc`; updated the method's docstring |
| `tools/file_search.py` | Modified | `_search_phrase_only`/`_search_combined`: added `except Exception as exc:` after the existing `WindowsSearchUnavailableError` branch on `adapter.search()`, mapping to `WindowsSearchUnavailableError` + the filename-still-works hint; added `results = results or []` (`phrase_results = phrase_results or []` in `_search_combined`) to guard a `None` return. `file_get_info`: widened the enrichment block's `except` from `(WindowsSearchUnavailableError, FileNotFoundInIndexError)` to bare `Exception`, moved `detail.kind`/`detail.snippet` assignment inside the `try`; removed the now-unused `FileNotFoundInIndexError` import |
| `tests/test_file_search_adapter.py` | Modified | Added 9 tests covering `None`/empty stdout (search + get_info), distinct message wording, solely-malformed-stdout-as-truncation, `None` stderr on nonzero exit, `TimeoutExpired` with `stdout=None`, and the blanket-mapping guarantee for an unforeseen exception type (search + get_info) |
| `tests/test_file_search_tools.py` | Modified | Added `_HostileAdapter` + `_HOSTILE_BEHAVIORS` matrix and 4 parametrized contract-level tests (phrase-only, combined, filename-only-unaffected, get_info-enrichment-never-surfaces) asserting no untyped exception ever escapes `file_search()`/`file_get_info()`; added `CalendarToolError` import |
| `openspec/specs/powershell-search-bridge/spec.md` | Modified | "Timeout and Failure Mapping" requirement widened to cover `None`/empty stdout and the blanket exception-mapping obligation; added 4 new scenarios |
| `openspec/changes/archive/2026-08-26-bridge-nonetype-hotfix/{proposal,tasks,apply-progress}.md` | Created | This hotfix's record |

## Deviations from Design

- The contract-level property test (item 4 of the reported fix) is scoped
  to `tools/file_search.py`'s two public functions only, per the bug
  report's own instruction ("Scope it to the file tools; note in the
  record that extending it to all tools is future work"). Mail/calendar/
  tasks tool layers are unaffected and untested by this hotfix.
- For the tool-layer hostile-adapter matrix, `search()`'s outcome
  contract is intentionally either/or (a `FileSearchResponse` OR a typed
  `CalendarToolError`, per the bug report's own wording) rather than
  mandating one specific branch — an arbitrary exception from the
  adapter is mapped to the typed unavailable error (consistent with the
  existing "both transports exhausted" behavior), while a `None` return
  degrades to an empty result list, both being valid, non-crashing
  outcomes. `get_info()`'s enrichment leg, by contrast, is tested
  strictly (always succeeds, never raises for ANY adapter misbehavior)
  because the file-get-info spec's pre-existing "Index Enrichment Failure
  Never Surfaces" requirement already commits to that specific behavior.
- No change to `FileSearchPort`, `FallbackSearchAdapter`, or
  `FakeFileSearchAdapter` — the fix is entirely within
  `PowerShellSearchBridge._invoke()` and the tool-layer call sites in
  `tools/file_search.py`.

## Issues Found

None beyond the reported defect and the tool-layer gap it implied (both
addressed above). The "not blocking, from the same family" item in
cowork's report (`calendar` events with `"subject": ""`) is out of scope
for this file-search hotfix — it belongs to the calendar tool layer,
owned by a different concurrent agent per this session's task
boundaries, and was not touched.

## Status

All phases (0-5) complete. Full suite green: 516 passed (486 baseline +
30 net new). Ready for sdd-verify / archive.
