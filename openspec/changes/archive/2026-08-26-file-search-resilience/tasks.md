# Tasks: File Search Resilience

## Phase 1: Config, Errors, Schema

- [x] 1.1 RED `tests/test_settings.py`: new readers for
  `file_search_walk_time_budget_seconds` (default 5),
  `file_search_walk_max_dirs` (default 5000),
  `file_search_ps_bridge_timeout_seconds` (default 10).
- [x] 1.2 GREEN `tools/settings.py` + `config/settings.yaml`: add the 3 keys.
- [x] 1.3 RED `tests/test_errors.py`: `PathNotFoundError` (code `path_not_found`).
- [x] 1.4 GREEN `tools/errors.py`: add `PathNotFoundError`.
- [x] 1.5 RED `tests/test_schemas.py`: `FileSummary`/response gains `results_truncated: bool`.
- [x] 1.6 GREEN `models/schemas.py`: add `results_truncated` (default `False`).

## Phase 2: Filesystem Walk

- [x] 2.1 RED+GREEN `tests/test_file_search_walk.py` (new): case-insensitive
  substring match via mocked `os.scandir`.
- [x] 2.2 RED+GREEN: result cap at `max_results` sets `results_truncated=True`.
- [x] 2.3 RED+GREEN: wall-clock budget stops walk early, `results_truncated=True`.
- [x] 2.4 RED+GREEN: dir-count budget stops walk early, `results_truncated=True`.
- [x] 2.5 RED+GREEN: `_is_reparse_point()` skips flagged mocked entries, no recurse.
- [x] 2.6 RED+GREEN: `PermissionError` on one subdir skipped, siblings still walked.
- [x] 2.7 GREEN `tools/file_search_walk.py`: implement `walk_filename(roots, filename, max_results, time_budget_s, max_dirs)`.

## Phase 3: PowerShell Bridge

- [x] 3.1 RED+GREEN `tests/test_file_search_adapter.py`: `PowerShellSearchBridge`
  invokes `subprocess.run` with absolute `-File <script path>`, mocked, never real `powershell.exe`.
- [x] 3.2 RED+GREEN: argv is exactly `["C:\WINDOWS\System32\WindowsPowerShell\v1.0\powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", <absolute path>]` — pinned, no `PATH` lookup, no `pwsh`.
- [x] 3.3 RED+GREEN: caller-controlled values (`filename`/`phrase`/`scope`) are absent from captured argv and present only in the captured stdin JSON payload's `sql` text.
- [x] 3.4 RED+GREEN (REVISED per live security review — SQL-building moved
  entirely into Python, shared by both transports): a table-driven test
  over the shared `_escape_like_value` helper (`_escape_sql` composed with
  `_escape_like_metacharacters`) asserting the exact escaped literal for
  `o'brien`, `100%`, `a_b`, `[abc]`, `it''s`, a lone backslash, empty
  string, a 1000-char string, and a metacharacters-only string; plus a
  test asserting the bridge's captured stdin `sql` is byte-for-byte what
  `_build_search_sql` produces for the same inputs.
- [x] 3.5 RED+GREEN hostile input: `filename="o'brien"` → matching results or a clean typed error, never a raw parse exception (values-as-data + escaping combined).
- [x] 3.6 RED+GREEN hostile input: `phrase="$(Get-Date)"` → the literal string travels only via the stdin JSON's `sql` text (never argv, never a `-Command` string); result is matching results or `WindowsSearchUnavailableError`, never evidence of PowerShell evaluating the substitution.
- [x] 3.7 RED+GREEN: `subprocess.TimeoutExpired` (mocked) → `WindowsSearchUnavailableError` with a "timed out" message.
- [x] 3.7b RED+GREEN (NEW per live security review): spawn failure
  (mocked `subprocess.run` raising `FileNotFoundError`/`OSError` — the
  child never started, e.g. AppLocker/CLM/missing exe) → same error TYPE
  as 3.7 but a distinctly-worded "blocked or unavailable" message.
- [x] 3.8 RED+GREEN: nonzero exit code (mocked) → `WindowsSearchUnavailableError`.
- [x] 3.9 RED+GREEN: malformed JSON stdout (mocked) → `WindowsSearchUnavailableError`.
- [x] 3.10 RED+GREEN: valid JSON stdout parsed via `_row_from_mapping()` into `FileSummary`/`FileDetail` (incl. a single-row/bare-JSON-object triangulation case).
- [x] 3.11 GREEN `tools/ps_bridge_search.ps1` (new asset): REVISED per live
  security review to be a dumb executor — reads stdin JSON's `sql` field
  and runs it VERBATIM via `System.Data.OleDb` (no escaping/interpolation
  on the PowerShell side at all; all SQL-building/escaping happens in
  Python, shared with the ADO adapter via `_build_search_sql`/
  `_build_get_info_sql`), prints JSON to stdout. Not unit-tested directly
  (no real PowerShell on WSL2) — covered indirectly by 3.1-3.10's
  mocked-subprocess contract tests.

## Phase 4: Fallback Composing Adapter

- [x] 4.1 RED+GREEN: `FallbackSearchAdapter.search()`/`get_info()` skip the
  bridge when fake ADO succeeds.
- [x] 4.2 RED+GREEN: ADO raises → bridge invoked, its result returned.
- [x] 4.3 RED+GREEN: both raise → `WindowsSearchUnavailableError` propagates unchanged (plus a triangulation case: `FileNotFoundInIndexError` from a reachable-but-unindexed primary lookup never falls through to the bridge).
- [x] 4.4 GREEN `tools/file_search_adapter.py`: implement `FallbackSearchAdapter(FileSearchPort)`.

## Phase 5: Tool Layer Rewrite

- [x] 5.1 RED+GREEN `tests/test_file_search_tools.py`: `filename`-only never
  calls the adapter, even if it would raise.
- [x] 5.2 RED+GREEN: `filename`-only succeeds under an unindexed scope (mocked walk).
- [x] 5.3 RED+GREEN: `phrase`-only both-transports-fail message states filename search still works.
- [x] 5.4 RED+GREEN: combined query intersects walk + adapter results by normalized path.
- [x] 5.5 RED+GREEN: combined query short-circuits (no adapter call) when walk finds 0 candidates.
- [x] 5.6 RED+GREEN: combined query propagates `WindowsSearchUnavailableError` when index leg exhausted.
- [x] 5.7 RED+GREEN `file_get_info`: nonexistent path (mocked `os.stat` → `FileNotFoundError`) raises `PathNotFoundError`.
- [x] 5.8 RED+GREEN: real unindexed file → `FileDetail` from `os.stat`, `kind=None`/`snippet=None`, no error.
- [x] 5.9 RED+GREEN: real indexed file → enrichment fields populated from the adapter.
- [x] 5.10 GREEN `tools/file_search.py`: implement the dispatch split, intersection, and rewritten `file_get_info`.

## Phase 6: Server Wiring

- [x] 6.1 RED `tests/test_server.py`: `path_not_found` surfaces as `ToolError` with matching `[code]`.
- [x] 6.2 GREEN `server.py`: `_resolve_real_file_search_adapter()` constructs `FallbackSearchAdapter`; confirm `_map_error` needs no change.

## Phase 7: Verification (no code expected)

- [x] 7.1 Confirm `deploy/smoke_test.py`'s files-family checks (roots-policy
  probe + tolerant live check) still pass unmodified — no edit needed.
- [x] 7.2 Confirm no diagnostic/forensic code in the repo's
  `tools/file_search_adapter.py` (PRO's deployed copy is out of repo scope).
- [x] 7.3 Add an integration test exercising `file_search
  {"filename": ".md", "scope": <unindexed dir>}` end-to-end via
  `create_server()` with a fake adapter — closest feasible stand-in for
  the live Windows acceptance scenario (not runnable on WSL2).

## Final

- [x] 8.1 `python3.12 -m pytest -q` green, full suite.
