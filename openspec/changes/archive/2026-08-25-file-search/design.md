# Design: File Search via Windows Search Index

## Technical Approach

Mirror the mail seam exactly: `models/schemas.py` (aliased request/response
models) → `FileSearchPort` Protocol (`tools/file_search_adapter.py`) with a
real ADODB-backed `WindowsSearchAdapter` (lazy `win32com`, `CoInitialize()`
per `com-coinitialize-hotfix`) and `FakeFileSearchAdapter` → tool-layer
`tools/file_search.py` (owns roots policy, live-reads
`config/settings.yaml`) → `server.py` (`@app.tool`, injectable adapter,
lazy `_resolve_real_file_search_adapter()`, `_map_error()` taxonomy — no
change needed since new errors subclass `CalendarToolError`). The adapter
stays config-unaware except for reading `file_search_max_results`'s already-
validated int; all roots policy and path decisions live in the tool layer.

## Architecture Decisions

| # | Decision | Choice | Rejected | Rationale |
|---|----------|--------|----------|-----------|
| 1 | Roots config shape | Flat keys `file_search_allowed_roots: []` + `file_search_max_results: 200` in `settings.yaml`, live-read via `load_settings()`, matching `mail_lookback_days`/`inbox_folder_id` | Nested `file_search:` mapping | Every existing key is flat; a nested block would be the sole exception for no benefit |
| 2 | Default roots when unconfigured | Ordered candidates `%USERPROFILE%`, `%OneDrive%`, `%OneDriveCommercial%`, `%OneDriveConsumer%`; resolve present env vars, normalize, dedupe by dropping any root nested inside an earlier one | Hardcoded `C:\Users\<name>` | Env vars vary per machine/tenant; OneDrive usually nests under the profile (collapses to just `%USERPROFILE%`), but a KFM-redirected OneDrive stays as an extra root |
| 3 | Roots-enforcement layering | Tool layer only: (a) pre-call — normalize + reject before any adapter call if outside all roots; (b) post-call — re-check every returned row, drop non-conforming ones (defense-in-depth vs. a crafted `SCOPE=`/`CONTAINS()` phrase). Adapter only uses the already-validated roots to build `SCOPE=` — enforces nothing itself | Enforcement inside adapter | Keeps adapter COM-access-only, symmetric with the other three; check is unit-testable with zero COM, mirrors `mail_search`'s tool-owned business rules |
| 4 | Path normalization | One helper (`_normalize_path`) for roots and results: prefer `System.ItemPathDisplay`; fall back to `System.ItemUrl` (`file:///`-strip + `unquote` + `/`→`\`) only if absent. Compare via `casefold()` + normalized separators, no trailing `\`; displayed `path` keeps `ItemPathDisplay`'s original casing | Comparing raw `ItemUrl` directly | NTFS is case-insensitive; mixing percent-encoded URI and native forms in one containment check is exactly the bypass explore.md flags |
| 5 | ADODB specifics | `Provider=Search.CollatorDSO;Extended Properties='Application=Windows'`; `SELECT TOP {n} System.ItemName, System.ItemPathDisplay, System.ItemUrl, System.Size, System.DateModified, System.Kind, System.FileExtension FROM SystemIndex WHERE (SCOPE='file:{root}' OR ...) AND CONTAINS(...)`. `{n}` is a validated int, needs no quoting; every string value passes through `_escape_sql` (doubles `'`); `CONTAINS('"..."')` phrase text also has embedded `"` stripped. `CoInitialize()` before first `Dispatch("ADODB.Connection")`, mirroring `_dispatch_outlook` | Parameterized query API | `Search.CollatorDSO` has none; escaping is mandatory |

## Data Flow

```
file_search(request) ──▶ tools/file_search.py
    │  1. load_settings(): allowed_roots (or compute defaults), max_results
    │  2. normalize+validate request.scope/path against allowed_roots
    │     └─ fails ⇒ raise SearchRootNotAllowedError (no adapter call)
    ▼
FileSearchPort.search(filename, phrase, roots, top_n) ──▶ WindowsSearchAdapter
    │  3. CoInitialize(); Dispatch("ADODB.Connection").Open(conn_str)
    │  4. build SQL: escape roots + filename + phrase (each separately), inject validated top_n
    │  5. Connection.Execute(sql) ──▶ Recordset ──▶ rows
    ▼
tools/file_search.py
    │  6. normalize each row's path; DROP any not contained in allowed_roots
    │  7. map to FileSummary list
    ▼
server.py  ──▶  FastMCP response / _map_error() on typed exception
```

`file_get_info(path)` follows the same normalize-then-check step before
calling `FileSearchPort.get_info(item_url_or_path)`.

## File Changes

| File | Action | Description |
|------|--------|--------------|
| `models/schemas.py` | Modify | `FileSearchRequest`, `GetFileInfoRequest`, `FileSummary`, `FileDetail` |
| `tools/file_search_adapter.py` | Create | `FileSearchPort` + `WindowsSearchAdapter` (ADODB, `_dispatch_search()`, `_escape_sql`) |
| `tools/fake_file_search_adapter.py` | Create | `FakeFileSearchAdapter`, seeded by path |
| `tools/file_search.py` | Create | `file_search()`/`file_get_info()`, roots containment, `_normalize_path` |
| `tools/errors.py` | Modify | `WindowsSearchUnavailableError`, `FileNotFoundInIndexError`, `SearchRootNotAllowedError` |
| `tools/settings.py` | Modify | `default_search_roots()` (env var precedence + dedupe) |
| `config/settings.yaml` | Modify | `file_search_allowed_roots: []`, `file_search_max_results: 200` |
| `server.py` | Modify | register tools, `_resolve_real_file_search_adapter()` |
| `tests/test_file_search_adapter.py`, `test_fake_file_search_adapter.py`, `test_file_search_tools.py` | Create | mirror mail suite; fake win32com/pythoncom/ADODB in `sys.modules` |
| `tests/test_schemas.py`, `tests/test_server.py` | Modify | extend with new models/tools |
| `README.md`, `pyproject.toml` | Modify | document new settings keys |

## Interfaces / Contracts

```python
class FileSearchPort(Protocol):
    def search(self, filename: str | None, phrase: str | None, roots: list[str], top_n: int) -> list[FileSummary]: ...
    def get_info(self, path_or_url: str) -> FileDetail: ...

class SearchRootNotAllowedError(CalendarToolError):
    code = "search_root_not_allowed"
    def __init__(self, message, *, requested_path: str, allowed_roots: list[str]): ...
```

`FileSummary`: `path` (native, `ItemPathDisplay`-sourced), `name`, `size`,
`date_modified`, `kind`, `extension`. `FileDetail` adds nothing new
(directory metadata is enough; content is out of scope per proposal).

## Testing Strategy

| Layer | What | Approach |
|-------|------|----------|
| Unit | roots containment, path normalization, default-root dedupe | plain pytest, no COM |
| Unit | SQL escaping (`'`, `"`, injected `TOP n`) | assert built SQL string on adapter |
| Integration | adapter search/get_info | fake `win32com.client`/`pythoncom` in `sys.modules`, mocked `ADODB.Connection`/`Recordset` |
| Integration | tool layer end-to-end | `FakeFileSearchAdapter`, seeded roots violating/matching cases |
| Server | tool registration/wiring | extend `tests/test_server.py` |

## Migration / Rollout

No migration required — purely additive, matches proposal's rollback plan.

## Open Questions

None — all five flagged decisions are resolved above.
