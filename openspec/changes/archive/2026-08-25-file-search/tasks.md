# Tasks: File Search via Windows Search Index

## Phase 1: Foundation — Schemas, Errors, Settings

- [x] 1.1 RED `tests/test_schemas.py`: cases for `FileSearchRequest`,
  `GetFileInfoRequest`, `FileSummary`, `FileDetail`.
- [x] 1.2 GREEN `models/schemas.py`: add the 4 models (aliased camelCase).
- [x] 1.3 RED `tests/test_errors.py`: cases for `SearchRootNotAllowedError`,
  `FileNotFoundInIndexError`, `WindowsSearchUnavailableError` (codes
  `search_root_not_allowed`/`file_not_found_in_index`/
  `windows_search_unavailable`), subclassing `CalendarToolError`.
- [x] 1.4 GREEN `tools/errors.py`: add the 3 error classes.
- [x] 1.5 RED+1.6 GREEN `tools/settings.py`: `default_search_roots()`
  resolves `USERPROFILE`+`OneDrive*` env vars, dedupes nested roots
  (new `tests/test_settings.py`).
- [x] 1.7 `config/settings.yaml`: add `file_search_allowed_roots: []`,
  `file_search_max_results: 200` with header comments.

## Phase 2: Adapter Port + Fake

- [x] 2.1 RED `tests/test_fake_file_search_adapter.py` (new): seed-by-path
  `search()` filtering + `top_n` cap, `get_info()` hit/miss/placeholder.
- [x] 2.2 GREEN `tools/file_search_adapter.py`: `FileSearchPort` Protocol —
  `search(filename, phrase, roots, top_n)` (split from the literal
  `search(query, roots, top_n)` above — see apply-progress.md's "Deviation"
  note), `get_info(path_or_url)`.
- [x] 2.3 GREEN `tools/fake_file_search_adapter.py`: `FakeFileSearchAdapter`
  implementing the Protocol in-memory.

## Phase 3: Real Adapter (ADODB / win32com)

- [x] 3.1 RED+GREEN `tests/test_file_search_adapter.py` (new): module
  imports on WSL2 with `win32com` absent from `sys.modules`; lazy
  `_dispatch_search()` imports `win32com.client`/`pythoncom` inside the
  function only.
- [x] 3.2 RED+GREEN: fake `pythoncom`/`win32com.client` — `CoInitialize()`
  called before `Dispatch("ADODB.Connection")` in `search()`/`get_info()`;
  no `CoUninitialize()`.
- [x] 3.3 RED+GREEN: captured SQL doubles embedded `'` in
  filename/phrase/scope/path, strips `"` in `CONTAINS()` phrase — via
  `_escape_sql()` on every interpolated value in the `SELECT TOP {n} ...
  FROM SystemIndex WHERE (SCOPE=...) AND CONTAINS(...)` query.
- [x] 3.4 RED+GREEN: `search(top_n=50)` → SQL contains `SELECT TOP 50`,
  `top_n` wired straight into `TOP` (no adapter-side default).
- [x] 3.5 RED+GREEN: row with only `ItemUrl=file:///.../My%20Report.docx`
  → `path == "...\My Report.docx"` via `_normalize_path()` (prefer
  `ItemPathDisplay`, else decode+`/`→`\`).
- [x] 3.6 RED+GREEN: fake `Connection.Open`/`Recordset.Open` raising a COM
  error → adapter raises `WindowsSearchUnavailableError`, not raw exception.
- [x] 3.7 GREEN: `get_info()` — exact path/URL lookup, raise
  `FileNotFoundInIndexError` on no match, `snippet=None` when absent.

## Phase 4: Tool Layer (`tools/file_search.py`)

- [x] 4.1 RED+GREEN `tests/test_file_search_tools.py` (new): both
  filename/phrase omitted → `ValueError` before any adapter call.
- [x] 4.2 RED+GREEN: out-of-root `scope` → `SearchRootNotAllowedError`
  pre-adapter; case/separator root variant accepted; sibling-prefix dir
  (`ana2` vs `ana`) refused — via `_normalize_path()`/`_is_contained()`.
- [x] 4.3 RED+GREEN: unconfigured roots + `USERPROFILE`/`OneDrive` env →
  scope under `OneDrive` allowed, via `default_search_roots()` fallback.
- [x] 4.4 RED+GREEN: unconfigured cap → adapter called with `TOP 200`;
  happy-path returns one `FileSummary`; empty results → `[]` not error;
  post-call drop any row outside allowed roots (defense-in-depth).
- [x] 4.5 RED: adapter's `WindowsSearchUnavailableError` propagates
  uncaught from the tool (mapped by `server.py` later).
- [x] 4.6 RED+GREEN: `file_get_info()` — out-of-root path refused
  pre-adapter; unknown path propagates `FileNotFoundInIndexError`;
  placeholder file → `FileDetail` with `snippet=None`, not an error.

## Phase 5: Server Registration

- [x] 5.1 RED `tests/test_server.py`: `create_server()` accepts
  `file_search_adapter`; injected fake used; both tools registered; typed
  errors surface as `ToolError` with matching `[code]`.
- [x] 5.2 GREEN `server.py`: add `file_search_adapter` param,
  `_resolve_real_file_search_adapter()` (lazy/cached), `@app.tool`
  registrations for `file_search`/`file_get_info`. `_map_error()`
  unchanged — already covers the new errors generically.

## Phase 6: Full Suite + Docs

- [x] 6.1 Run `python3.12 -m pytest -q` — full suite green, no regressions.
- [x] 6.2 `README.md`: document both tools and the new settings keys.
- [x] 6.3 `pyproject.toml`: confirm no new dependency needed (pywin32
  already present).
