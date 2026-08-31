# Proposal: File Search via Windows Search Index

## Intent

Add `file_search` and `file_get_info` MCP tools to locate files on the
local disk and locally-synced OneDrive folder via the Windows Search index
(ADODB, `Provider=Search.CollatorDSO`, SQL against `SystemIndex`). Mirrors
the calendar/task/mail seam. Access MUST be restricted to roots configured
in `config/settings.yaml`, refusing queries outside them.

## Scope

### In Scope
- `file_search` (filename/phrase/scope query, `TOP n` cap) and
  `file_get_info` (metadata for one indexed file).
- `FileSearchPort` Protocol + `WindowsSearchAdapter` (ADODB/win32com, lazy
  import, `CoInitialize()`) + `FakeFileSearchAdapter`.
- Tool-layer roots enforcement from `file_search_allowed_roots`; defaults
  (`%USERPROFILE%`, `%OneDrive%*`) when unconfigured.
- SQL-value escaping in the adapter (no parameterized queries available).
- New error types under the existing `CalendarToolError` taxonomy.

### Out of Scope
- Indexing/reindexing control, non-indexed locations, relevance tuning.
- Network/SharePoint-only OneDrive content (not locally-synced).

## Capabilities

### New Capabilities
- `file-search`: index query within allowed roots.
- `file-get-info`: single-file metadata detail.
- `windows-search-adapter`: `FileSearchPort` Protocol + real/fake adapters.

### Modified Capabilities
None.

## Approach

Mirror the established seam: schemas → `FileSearchPort`/adapters → tool
functions (own roots policy) → `server.py` (injectable adapter + lazy
resolver) → live `settings.yaml` reads. Roots enforcement lives in the tool
layer (testable without COM); the adapter stays config-unaware, always
escaping interpolated SQL values. Default-roots precedence and config shape
are open design decisions, not blockers.

## Affected Areas

| Area | Impact | Description |
|------|--------|--------------|
| `models/schemas.py`, `tools/errors.py` | Modified | Models, new error types |
| `tools/file_search_adapter.py`, `tools/fake_file_search_adapter.py` | New | Real + fake adapters |
| `tools/file_search.py` | New | Tool functions, roots enforcement |
| `tools/settings.py`, `config/settings.yaml` | Modified | Allowed roots, result cap |
| `server.py` | Modified | Register tools, resolver, error mapping |
| `tests/`, `README.md`, `pyproject.toml` | New/Modified | Test coverage, docs |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| SQL injection via unescaped ADODB values | Med | Adapter escapes every value |
| Unbounded result payload | Med | `TOP n` + result-count cap |
| Path-form mismatch bypasses roots check | Med | Normalize path before containment check |
| OneDrive placeholders incompletely indexed | Low | Document as known limitation |
| No real Search index on WSL2 dev/CI | High (known) | Mock ADODB/win32com in tests |

## Rollback Plan

Purely additive. Revert by removing the `server.py` registrations and
deleting new modules/tests; no existing behavior changes breakingly.

## Dependencies

- `win32com`/ADODB (Windows-only; already pywin32).

## Success Criteria

- [ ] Both tools registered and callable via FastMCP.
- [ ] Out-of-root queries refused with a typed error.
- [ ] New logic covered by fake ADODB/win32com tests.
- [ ] `python3.12 -m pytest -q` passes on WSL2 with no real COM access.
