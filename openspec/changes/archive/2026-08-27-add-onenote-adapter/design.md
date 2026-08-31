# Design: OneNote Access via COM Bridge

## Technical Approach

Mirror `file_search`'s bridge seam, not Outlook's direct-Dispatch pattern
(spike-verified: SystemIndex has zero `onenote:` items, COM is the only
path) — but **extract the transport first**: a new,
use-case-agnostic `tools/ps_bridge_transport.py` owns everything about
talking to a pinned `powershell.exe` 5.1 child (spawn, stdin JSON write,
timeout, JSON-Lines streaming parse, the sentinel/truncation/corruption
distinction, stderr capture, the `(exit: ...; stderr: ...)` diagnostic
suffix, and the config-gated debug-log hook). `file_search_adapter.py`'s
`PowerShellSearchBridge` is refactored onto this transport (behavior
unchanged, existing test suite as the regression net). The new
`tools/onenote_adapter.py` builds on the same transport from day one.
`models/schemas.py` (aliased models) → `OneNotePort` Protocol
(`OneNoteAdapter`, on the shared transport, + `FakeOneNoteAdapter`) →
tool-layer `tools/onenote.py` (allowlist, section resolution, live-reads
`config/settings.yaml`) → `server.py` (`@app.tool`, injectable adapter,
`_resolve_real_onenote_adapter()`, `_map_error()` unchanged — new errors
subclass `CalendarToolError`).

## Architecture Decisions

| # | Decision | Choice | Rejected | Rationale |
|---|----------|--------|----------|-----------|
| 1 | Extract shared PS-bridge transport | New `tools/ps_bridge_transport.py`: pinned absolute `powershell.exe` 5.1 path, `-NoProfile -NonInteractive -ExecutionPolicy Bypass -File`, stdin JSON write, background stdout/stderr pump threads, wall-clock-deadline read loop, JSON-Lines parse with the truncation-vs-corruption rule + `{"done": true}` sentinel, `_diagnostic_suffix`, config-gated debug-log line. `PowerShellSearchBridge` refactored onto it; `OneNoteAdapter` built on it from day one | Copy/adapt the bridge plumbing into `onenote_adapter.py` a second time (as the proposal originally sketched) | Two independent copies of deadline/JSON-Lines/truncation logic drift out of sync exactly like the two-SQL-escapers problem this codebase already rejected once (file-search-resilience's live security review) — one battle-hardened implementation (bridge-streaming-hotfix, ps-bridge-jsonl-hotfix) serving both bridges |
| 2 | Transport return/error shape | `PsBridgeTransport.invoke(script_path, request, *, timeout, debug_log_enabled, log_label) -> (rows: list[dict], truncated: bool)`; raises a generic `PsBridgeTransportError` (message includes the exit/stderr diagnostic suffix) on the zero-rows/corrupt-line cases | Transport raises `WindowsSearchUnavailableError` directly | Transport must stay domain-agnostic — it doesn't know about `CalendarToolError`. Each adapter's thin wrapper catches `PsBridgeTransportError` and re-raises its own typed error (`WindowsSearchUnavailableError` / `OneNoteUnavailableError`) with the same message, preserving `PowerShellSearchBridge`'s existing exception types/text exactly |
| 3 | No shared `.ps1` skeleton | `ps_bridge_search.ps1` and the new `ps_bridge_onenote.ps1` each stay fully self-contained scripts; only the Python-side transport is shared | A common PowerShell "read stdin, dispatch, emit JSON Lines" include/module | Deployment simplicity wins: one file copied per install (matches existing `tools/*.ps1` deployment), vs. two files that must ship and version together for ~40 lines of duplicated boilerplate. The truncation/streaming/escaping-relevant logic that actually needs one source of truth already lives in Python (Decision 1) |
| 4 | Bridge lifecycle | One `powershell.exe` child per bridge call — never a persistent daemon | Long-lived PS process reused across calls | COM instantiates in ~23ms (spike); a create-page flow costs 2 spawns (hierarchy + create), still sub-100ms. Matches `PowerShellSearchBridge`'s existing per-call pattern; a daemon adds process-lifecycle/health-check complexity for no measured benefit |
| 5 | Op dispatch shape | Single JSON object on stdin: `{"op": "search\|get_page\|get_hierarchy\|create_page\|update_page", ...op-specific fields}`; `ps_bridge_onenote.ps1` does a top-level `switch` on `op`, calling the matching COM method with the given fields verbatim | Five separate `.ps1` scripts | One script keeps the dumb-executor model in one place while letting each op differ in COM call shape, unlike search's uniform "run this SQL" contract |
| 6 | Allowlist enforcement point | Python resolves `section_id` via a `get_hierarchy` op, checks `notebook_name` against `onenote_writable_notebooks` **before** calling `create_page`/`update_page`. Bridge write ops receive only an opaque `section_id`/`page_id`, never a notebook name | Bridge resolves the notebook/section itself | Same "decide in exactly one place" precedent as `file_search`'s roots check — a bridge that is allowlist-aware is a second place policy can drift |
| 7 | XML→text extraction | **As shipped** (revised from the original plan below): `ps_bridge_onenote.ps1` returns the page's raw `pageXml` string verbatim from `GetPageContent`/`CreateNewPage`/`UpdatePageContent`; `tools/onenote_adapter.py::_extract_title_and_body()` (Python, using `xml.etree.ElementTree`) reads the namespace from the document's own root element (`DocumentElement.NamespaceURI`, never hardcoded), extracts title from `Title/OE/T` CDATA and body as each `Outline/OEChildren/OE`'s concatenated `T` CDATA, joined by `\n`. Originally planned the other way around — see "Originally planned" below | Originally planned: bridge parses `GetPageContent` XML itself and returns plain `{title, text}` JSON, Python never parses OneNote XML | The onenote-com-adapter spec's own scenarios ("Dynamic XML Namespace Detection", "Page Content Extraction") say "WHEN **the adapter** parses it" — only meaningful if `OneNoteAdapter` (Python) does the parsing, and it is also the only way to unit-test this requirement on WSL2 (no real COM to exercise a `.ps1` script's own XML logic). Implemented in Batch 2 (apply-progress.md); flagged as a documentation-drift WARNING by `sdd-verify` and corrected here in Batch 5. |
| 8 | Update semantics | Partial patch: `title` replaces the existing `Title/T` CDATA in place; `body` **appends** a new `Outline/OEChildren/OE/T` (never removes existing content) — the spike's own write pattern | Fetch+rewrite the full page XML for a true overwrite | Full-page rewrite risks destroying page structure sight-unseen; documented limitation: repeated `body` updates append rather than replace |
| 9 | Optimistic concurrency | `expected_last_modified` is **required** on `onenote_update_page`, passed to `UpdatePageContent(xml, dateExpectedLastModified)`; a mismatch maps to `OneNotePageConflictError`. **Wire format (resolved in Batch 5, live evidence 2026-08-27)**: the value MUST be sent as a `Z`-suffixed UTC string (`tools/onenote_adapter.py::_to_utc_z()`), never `.isoformat()`'s `+00:00` suffix — .NET's `DateTimeStyles.RoundtripKind` parser *adjusts* a `+00:00`-suffixed string to the parsing machine's local time zone but leaves a `Z`-suffixed string as unadjusted UTC, so `+00:00` caused every honest update to spuriously conflict on any non-UTC Windows host. **Known limitation (live-confirmed, Batch 5)**: OneNote stamps `lastModifiedTime` *lazily*, at its own background save, not synchronously with `UpdatePageContent` returning (the COM-visible timestamp was observed unchanged 15+ seconds after a write landed) — a second write issued within that save-latency window is undetectable by any timestamp-based check, including OneNote's own native COM check; the guard here is reliable for genuinely stale (seconds-to-minutes old) timestamps, not for true-concurrent writes inside the save window. | Optional, default `[DateTime]::MinValue` (skip check) | Closes the named "silent overwrite" risk by construction |
| 10 | Error taxonomy | New errors subclass `CalendarToolError`: `OneNoteUnavailableError`, `OneNotePageNotFoundError`, `OneNoteSectionNotFoundError`, `OneNoteWriteNotAllowedError`, `OneNotePageConflictError` | Separate `OneNoteToolError` base | One taxonomy, one `_map_error()` — no `server.py` logic change |

## Data Flow (read path)

```
onenote_search(query, top_n) ──▶ tools/onenote.py
    ▼
OneNotePort.search() ──▶ OneNoteAdapter ──▶ PsBridgeTransport.invoke(
        ps_bridge_onenote.ps1, {"op":"search",...})
    │ spawn powershell.exe; bridge: FindPages('', query, ...) COM call
    │ transport streams JSON Lines, applies truncation/corruption rule
    ▼
OneNoteAdapter maps rows → PageSummary ──▶ tools/onenote.py ──▶ server.py
```

## Sequence Diagram (write path: `onenote_create_page`)

```
Caller → tools/onenote.py: create_page(notebook_name, section_name, title, body)
tools/onenote.py → OneNoteAdapter: get_hierarchy()
OneNoteAdapter → PsBridgeTransport: invoke(..., {"op":"get_hierarchy"})   (spawn #1)
PsBridgeTransport → ps_bridge_onenote.ps1 → OneNote COM: GetHierarchy('', 4)
PsBridgeTransport → OneNoteAdapter → tools/onenote.py: notebook/section id+name tree
tools/onenote.py: find notebook_name in tree
alt notebook_name not in onenote_writable_notebooks
    tools/onenote.py → Caller: raise OneNoteWriteNotAllowedError  (no further COM call)
else allowed
    tools/onenote.py: resolve section_id for section_name
    tools/onenote.py → OneNoteAdapter → PsBridgeTransport: invoke(..., {"op":"create_page",...})  (spawn #2)
    PsBridgeTransport → ps_bridge_onenote.ps1 → OneNote COM: CreateNewPage + UpdatePageContent
    PsBridgeTransport → OneNoteAdapter → tools/onenote.py → Caller: CreatePageResult(page_id)
end
```

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `tools/ps_bridge_transport.py` | Create | `PsBridgeTransport` — extracted spawn/deadline/JSON-Lines/debug-log logic (Decision 1, 2) |
| `tools/ps_bridge_search.ps1`, `tools/ps_bridge_onenote.ps1` | Create/Unmodified | onenote script new; search script's own contents untouched (only its Python caller changes) |
| `tools/file_search_adapter.py` | Modify | `PowerShellSearchBridge` refactored to call `PsBridgeTransport.invoke()`; `_build_search_sql`/`_build_get_info_sql`/row-mapping unchanged |
| `tools/onenote_adapter.py` | Create | `OneNotePort` + `OneNoteAdapter` on `PsBridgeTransport` |
| `tools/fake_onenote_adapter.py` | Create | `FakeOneNoteAdapter`, seeded by `PageDetail` + hierarchy fixture |
| `tools/onenote.py` | Create | `onenote_search/get_page/create_page/update_page`, allowlist + section resolution |
| `models/schemas.py` | Modify | `PageSummary`, `PageDetail`, `OneNoteSearchRequest/Result`, `GetPageRequest`, `CreatePageRequest/Result`, `UpdatePageRequest/Result` |
| `tools/errors.py` | Modify | 5 new typed errors (Decision 10) |
| `tools/settings.py`, `config/settings.yaml` | Modify | `onenote_writable_notebooks` (default `["z - Test Notebook"]`), `onenote_search_max_results` (default 50), `onenote_ps_bridge_timeout_seconds` (default 20) |
| `server.py` | Modify | register 4 tools, `_resolve_real_onenote_adapter()` |
| `tests/test_ps_bridge_transport.py` | Create | mocked-`subprocess` unit tests: deadline, sentinel, truncation-vs-corruption, debug-log gating |
| `tests/test_file_search_adapter.py` | Unmodified (regression net) | must stay green unchanged — proves the refactor is behavior-preserving |
| `tests/`, `README.md` | New/Modify | fake-adapter coverage, docs |

## Interfaces / Contracts

```python
class PsBridgeTransport:
    def invoke(self, script_path: Path, request: dict, *, timeout: float,
               debug_log_enabled: Callable[[], bool], log_label: str
               ) -> tuple[list[dict], bool]: ...   # (rows, truncated); raises PsBridgeTransportError

class OneNotePort(Protocol):
    def search(self, query: str, top_n: int) -> list[PageSummary]: ...
    def get_page(self, page_id: str) -> PageDetail: ...
    def get_hierarchy(self) -> list[NotebookNode]: ...
    # As shipped: no `depth` parameter, always full-depth internally. The
    # onenote-com-adapter spec's own prose ("get_hierarchy(depth=4) -> HierarchyNode")
    # pre-dates this contract and was never reconciled to it; this Interfaces
    # block is what shipped (flagged by sdd-verify as a spec/design inconsistency
    # that predates this apply — recommend a small spec-wording fix at archive
    # time). Internal only, not an MCP tool.
    def create_page(self, section_id: str, title: str, body: str) -> str: ...
    def update_page(self, page_id: str, title: str | None, body: str | None,
                     expected_last_modified: datetime) -> datetime: ...
```

## Testing Strategy

| Layer | What | Approach |
|-------|------|----------|
| Unit | `PsBridgeTransport`: deadline, sentinel, truncation-vs-corruption, stderr/exit-code suffix, debug-log gating | mocked `subprocess.Popen`, no real PowerShell |
| Regression | `PowerShellSearchBridge` unchanged behavior post-refactor | existing `tests/test_file_search_adapter.py` suite must stay green, no test edits |
| Unit | allowlist check, section-name resolution over a fixture hierarchy | plain pytest, no COM |
| Unit | op-dispatch JSON shape sent to bridge stdin | assert on captured stdin, mirrors existing SQL-text assertions |
| Integration | adapter search/get_page/create/update | `FakeOneNoteAdapter`, no real PowerShell/COM |
| Server | tool registration/wiring, error mapping | extend `tests/test_server.py` |
| Manual (target machine only) | real COM bridge round-trip | not automatable on WSL2; verified via the spike scripts already |

## Migration / Rollout

No migration required — additive for OneNote; the `file_search` refactor
is purely internal (same public `PowerShellSearchBridge` class, same
method signatures, same exception types/messages) and ships alongside
the OneNote tools rather than as its own release.

**Spec impact of the `file_search` refactor**: no delta spec required.
`openspec/config.yaml`'s `rules.specs` govern new/changed *behavior*, not
internal refactors; the project's own precedent (`bridge-streaming-hotfix`,
`ps-bridge-jsonl-hotfix`, `bridge-nonetype-hotfix`,
`bridge-zerorow-and-salvage-hotfix` — all archived changes that touched
this exact bridge code, some changing real behavior to fix bugs) shipped
with `proposal.md`/`tasks.md` only, no `specs/` directory. This change's
refactor is strictly weaker (no intended behavior change at all, guarded
by the pre-existing regression suite), so design-level documentation here
is sufficient — the `windows-search-adapter`/file-search capability entry
in `openspec/specs/` is unaffected and needs no delta.

## Open Questions

- [x] **RESOLVED (Batch 5, live evidence 2026-08-27)**: the exact HRESULT
      `UpdatePageContent` raises on a genuinely stale `expected_last_modified`
      is **`0x80042010`** (`hrLastModifiedDateDidNotMatch`), confirmed against
      real COM via the live MCP driver. `tools/onenote_adapter.py`'s
      `_CONFLICT_MARKERS` includes the literal `"0x80042010"` substring
      (test: `test_update_page_com_hresult_0x80042010_raises_page_conflict`).
      Resolving this also surfaced and fixed a deeper root-cause bug — see
      Decision 9's wire-format note above (the `+00:00` vs `Z` suffix
      timezone bug) — without which *every* honest update conflicted on a
      non-UTC host, masking the real HRESULT behind a false-positive
      conflict on every call.
- [ ] `title`/`body` containing the literal sequence `]]>` will break
      CDATA construction (no chunk-splitting in v1) — accepted as a
      rare-edge-case limitation.
