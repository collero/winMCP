## Exploration: file-search (`file_search` + `file_get_info` via Windows Search index)

### Current State

WinMCP is a FastMCP stdio server (`server.py`) exposing three existing tool
families — calendar, tasks, mail — each built on the same seam:

1. **Pydantic schemas** (`models/schemas.py`): request models (aliased
   camelCase wire names via `_AliasedModel`/`populate_by_name=True`) and
   response models. Enums (`MailFolder`, `TaskStatus`) model closed value
   sets; `@model_validator(mode="after")` enforces cross-field invariants
   (e.g. `MailSearchRequest`'s "exactly one of folder/folder_path").
2. **Port protocol + adapters** (`tools/{name}_adapter.py`): a `Protocol`
   (`MailPort`, `CalendarPort`, `TaskPort`) defines the interface; a real
   `Outlook*Adapter` class implements it with `win32com`, always imported
   **lazily inside a `_dispatch_outlook()` method**, never at module scope.
   `_dispatch_outlook()` calls `pythoncom.CoInitialize()` (also lazily
   imported) before any `Dispatch()` call — added by the
   `com-coinitialize-hotfix` change because FastMCP runs tool calls on a
   worker-thread pool and COM apartments are thread-local. All COM failures
   are caught and re-raised as typed errors from `tools/errors.py`
   (`CalendarToolError` subclasses with a stable `code` attribute).
3. **Fake adapter** (`tools/fake_*_adapter.py`): an in-memory class
   satisfying the same Protocol, seeded via constructor args, used by every
   test and by `create_server(...)`'s injectable parameters — never
   `win32com`.
4. **Tool-layer function** (`tools/{name}.py`): pure functions
   `thing_search(request, adapter) -> list[Summary]` / `thing_get_x(request,
   adapter) -> Detail` that validate cross-field business rules not
   expressible in Pydantic alone (e.g. "at least one filter required"),
   apply defaults from `config/settings.yaml` (lookback windows), and
   delegate to the injected adapter. They raise/propagate the
   `CalendarToolError` taxonomy or `ValueError`; they never touch FastMCP.
5. **`server.py`**: builds the `FastMCP` app in `create_server(adapter=None,
   task_adapter=None, mail_adapter=None)`. Each `None` parameter is
   resolved lazily on first tool call via a module-level
   `_resolve_real_*_adapter()` cached singleton — importing the real
   adapter module is safe at import time (its own `win32com` import is
   further deferred), but *constructing* it is deferred until actual use.
   Each `@app.tool(...)` function builds the aliased Pydantic request,
   calls the tool-layer function, and maps typed errors via `_map_error()`
   to FastMCP's `ToolError` with a `[code]` prefix.
6. **Config** (`config/settings.yaml` + `tools/settings.py`): a flat YAML
   file loaded fresh on every read via `load_settings()` (never cached at
   import/construction time) — deliberately chosen so edits take effect
   without a restart-and-recompile step. Every adapter resolves its
   Outlook folder id from settings at COM-access time, falling back to a
   documented default (module constant) when the key is absent or the file
   is unreadable/corrupt (`config-live-folders` change, reversing an
   earlier "dead config" decision). `tools/settings.py` also exposes
   `local_timezone()` (reads `timezone_override`).
7. **Tests** (`tests/`): `tests/conftest.py` is nearly empty — no shared
   fixtures; each test module builds its own fakes/mocks inline. Real
   adapter tests (`tests/test_mail_adapter.py` etc.) inject fake
   `win32com`/`win32com.client`/`pythoncom` modules into `sys.modules` via
   `pytest-mock`'s `mocker.patch.dict(sys.modules)` + `types.ModuleType`,
   then assert call order/arguments on `Mock()` stand-ins for `Dispatch`,
   `GetNamespace`, `GetDefaultFolder`, `Restrict`, etc. Fake-adapter tests
   exercise the tool layer end-to-end via `Fake*Adapter` with zero COM
   involvement. `tests/test_server.py` covers tool registration/wiring.

No existing code touches the filesystem, Windows Search, ADODB, or any
notion of "allowed roots" — this is a wholly new capability, but the
seam/config patterns to mirror are well-established and consistent across
all three prior tool families (reinforced twice: `config-live-folders` and
`com-coinitialize-hotfix` both retrofitted cross-cutting fixes uniformly
across all three adapters).

### Affected Areas

- `models/schemas.py` — add `FileSearchRequest`/`GetFileInfoRequest`
  (input) and `FileSummary`/`FileDetail` (output) Pydantic models, mirroring
  `MailSearchRequest`/`MessageSummary`/`MessageDetail`'s alias conventions.
- `tools/file_search_adapter.py` (new) — `FileSearchPort` Protocol +
  `WindowsSearchAdapter` real implementation (ADODB/OLE DB via
  `win32com.client.Dispatch("ADODB.Connection")`, lazily imported, with
  `pythoncom.CoInitialize()` before any Dispatch call — mirrors
  `tools/mail_adapter.py::OutlookMailAdapter._dispatch_outlook`).
- `tools/fake_file_search_adapter.py` (new) — `FakeFileSearchAdapter`,
  in-memory, seeded via constructor, mirrors `FakeMailAdapter`.
- `tools/file_search.py` (new) — tool-layer `file_search()`/
  `file_get_info()` functions; owns the **allowed-roots enforcement**
  (validate the resolved query path/scope against configured roots before
  calling the adapter — see Approaches below for where exactly this check
  should live).
- `tools/errors.py` — add a new error, e.g. `SearchRootNotAllowedError` (or
  similarly named) to the `CalendarToolError` taxonomy (the taxonomy is
  explicitly reused across unrelated domains already — mail's
  `MailFolderNotFoundError` reuses the same base class per design.md's
  "Error taxonomy reuse" decision — so a file-search error naturally
  follows the same base rather than inventing a parallel hierarchy), plus
  a `FileNotFoundInIndexError`/`FileUnavailableError` pair mirroring
  `MessageNotFoundError`/`OutlookUnavailableError`.
- `tools/settings.py` / `config/settings.yaml` — add the allowed-roots key
  (e.g. `search_allowed_roots: [...]`) plus any file-search-specific
  lookback/limit defaults (e.g. `file_search_max_results`), read via
  `load_settings()` at call time, never cached — mirrors every existing
  settings key's live-read discipline.
- `server.py` — register `file_search`/`file_get_info` `@app.tool(...)`
  functions; extend `create_server(...)` with an injectable
  `file_search_adapter` parameter and a `_resolve_real_file_search_adapter()`
  lazy singleton, mirroring the three existing resolvers exactly; extend
  `_map_error()`'s taxonomy handling (already generic — no change needed
  if the new errors subclass `CalendarToolError`).
- `tests/test_file_search_adapter.py`, `tests/test_fake_file_search_adapter.py`,
  `tests/test_file_search_tools.py`, `tests/test_schemas.py`,
  `tests/test_server.py` — new/extended tests mirroring the mail suite's
  structure, including the `sys.modules` fake-`win32com`/`pythoncom`
  injection technique for ADODB.
- `README.md` "Configuration" section — document the new settings key(s),
  matching the existing per-key bullet-list style.
- `pyproject.toml` — description update mirrors the `config-live-folders`
  precedent (mentions all tool families); no new dependency needed (ADODB
  is accessed via the same `win32com.client` already a Windows-only
  optional dependency).

### Approaches

1. **Roots enforcement in the tool layer (`tools/file_search.py`), not the
   adapter** — the tool function loads `search_allowed_roots` from
   settings, normalizes/resolves the requested path or search scope, and
   raises before ever calling `WindowsSearchAdapter`. The adapter itself
   stays a thin ADODB/SQL executor with no config awareness, exactly
   mirroring how `tools/mail.py` (not `tools/mail_adapter.py`) owns the
   "at least one filter required" business rule while the adapter stays a
   pure COM-access layer.
   - Pros: keeps the adapter symmetric with the other three adapters
     (COM access + typed errors only); the security-relevant check is
     testable with zero COM/ADODB involvement via plain unit tests; matches
     the existing division of responsibility exactly (adapters never read
     `config/settings.yaml` for anything except folder ids, which are Outlook
     COM constants, not access-control policy).
   - Cons: `FakeFileSearchAdapter`-based tests of the tool layer must also
     seed/patch `search_allowed_roots`, adding one more thing every
     file-search tool test must configure.
   - Effort: Low.

2. **Roots enforcement in the adapter** (`WindowsSearchAdapter` reads
   settings and refuses out-of-root queries itself, before building SQL).
   - Pros: a single choke point close to the actual OLE DB `SCOPE=` clause
     construction, so it's harder to add a second call path that forgets
     the check.
   - Cons: breaks the established seam symmetry (no other adapter reads
     settings for access-control; `_resolve_folder_id()` reads settings only
     for a COM constant, not a security boundary) and would need the
     `FakeFileSearchAdapter` to duplicate the exact same enforcement logic
     to keep fake/real behavior identical for tests — doubling the
     surface that must stay in sync, and letting a security check silently
     diverge between fake and real if one is edited without the other.
   - Effort: Low-Medium.

3. **Roots enforcement in both layers (tool layer as the primary gate,
   adapter as defense-in-depth)** — tool layer refuses as in Approach 1;
   additionally the real adapter clamps/validates `SCOPE=` values it is
   about to place in SQL as a second line of defense against a future call
   site that bypasses the tool layer.
   - Pros: defense-in-depth against SQL-injection-flavored path/scope
     strings ending up in a `Restrict()`/OLE DB `WHERE SCOPE=` clause built
     via string interpolation (there is no parameterized-query API for
     `Search.CollatorDSO`); a second check is cheap insurance for a feature
     whose entire point is constraining filesystem access.
   - Cons: the fake adapter would still not need the second check (no real
     SQL there), so it's asymmetric with the fake either way; slightly more
     code than Approach 1.
   - Effort: Medium.

### Recommendation

Approach 1 for the *policy* decision (which roots are allowed), because it
preserves the existing seam discipline exactly (adapters are COM-access-only;
tool-layer functions own business/policy rules read from `config/settings.yaml`,
exactly like `mail_search`'s "at least one filter" and lookback-fill rules).
Layer Approach 3's SQL-safety idea in as a narrow adapter-level concern
distinct from roots policy: because `Search.CollatorDSO` SQL has no bind
parameters, the adapter MUST still defensively quote/escape any string value
(subject/path/scope) it interpolates into the `WHERE`/`SCOPE=` clause —
this is not roots policy, it's basic COM/SQL-injection hygiene the adapter
owns regardless of where roots are enforced, similar in spirit to how
`_dasl_datetime()` centralizes safe datetime formatting for
`Items.Restrict()` today. Recommend: tool layer loads
`search_allowed_roots` (default: user profile dir + OneDrive sync root when
unconfigured — both resolved via env vars, not hardcoded, since they vary
per machine/user), normalizes the requested path (case-insensitive,
separator-normalized, resolves `..`/symlink-like OneDrive placeholder
traversal) and checks containment before calling the adapter; the adapter
escapes single quotes (OLE DB SQL string literal delimiter) in every
interpolated value regardless.

### Risks

- **ADODB via win32com specifics**: `Search.CollatorDSO` is accessed as
  `win32com.client.Dispatch("ADODB.Connection")` /
  `win32com.client.Dispatch("ADODB.Recordset")` — ordinary IDispatch
  automation objects, so the existing `Dispatch(...)` mocking technique in
  `tests/test_mail_adapter.py` (fake `win32com.client` module injected into
  `sys.modules`) extends directly; no new COM machinery needed. The SQL
  dialect (`SystemIndex`, `SCOPE=`, `CONTAINS()`, `System.ItemUrl`,
  `System.ItemPathDisplay`, etc.) has no parameterization — all filter
  values are string-interpolated, so injection-safe quoting/escaping is a
  hard requirement, not a nice-to-have, since a filename or search phrase
  containing a single quote could otherwise break out of the intended
  `WHERE` clause.
- **CoInitialize handling**: must follow the exact `com-coinitialize-hotfix`
  precedent — lazy `pythoncom` import, `CoInitialize()` (idempotent, no
  `CoUninitialize()`) before the first `Dispatch()` call in the new
  adapter's dispatch helper. Skipping this reproduces the intermittent
  `CoInitialize has not been called` failure already fixed once for the
  other three adapters.
- **Result size limits**: an unfiltered or broad `file_search` query against
  a fully-indexed user profile can return an enormous row count. The SQL
  needs an explicit `SELECT TOP n ...` (or adapter-side truncation) with a
  configurable cap (e.g. `file_search_max_results`, mirroring the
  live-settings pattern), otherwise a single tool call could return an
  unbounded/huge payload to the MCP client.
- **Path normalization**: Windows Search returns `System.ItemUrl` as a
  `file:///C:/...`-style URI (percent-encoded) and/or `System.ItemPathDisplay`
  as a native `C:\...` path — the adapter must consistently pick one
  representation, URL-decode if using `ItemUrl`, and normalize separators,
  so `FileSummary.path`/`FileDetail.path` is stable and matches what a
  Windows user/LLM caller expects. The allowed-roots containment check
  must compare against this same normalized, case-insensitive form (NTFS
  paths are case-insensitive) to avoid a bypass via case or separator
  variation (`c:/users/...` vs `C:\Users\...`).
- **OneDrive Files-On-Demand placeholders**: the Windows Search index does
  cover the locally-synced OneDrive folder tree (per the task description),
  but a placeholder (not-yet-hydrated) file's *content* may not be fully
  indexed the same way a hydrated local file's is — `CONTAINS()` full-text
  matches against file body/properties can be incomplete or absent for
  unhydrated placeholders, while filename/metadata matches (`System.FileName`,
  `System.ItemName`, `System.Size`) remain reliable. This should be
  documented as a known limitation rather than something the adapter can
  fully work around; `file_get_info` on a placeholder should still return
  metadata even if content-derived properties are sparse.
- **Config defaults when unconfigured**: "sensible defaults" (user profile +
  OneDrive) must be resolved dynamically at COM-access/tool-call time, not
  hardcoded — Windows exposes the user profile via `%USERPROFILE%` and the
  OneDrive sync root via `%OneDrive%`/`%OneDriveConsumer%`/
  `%OneDriveCommercial%` environment variables (multiple possible OneDrive
  accounts/tenants can each set a different variable). The design phase
  needs to decide the exact precedence/fallback order and how absence of
  all of them is handled (e.g. fall back to `%USERPROFILE%` alone, or fail
  open/closed) — this is a design decision, not a blocking ambiguity, since
  a reasonable default ordering can be proposed and reviewed at the
  PRE-IMPLEMENTATION GATE.
- **No real Windows/Outlook/Search in this dev environment**: exactly like
  the other three adapters, `WindowsSearchAdapter` can only be exercised via
  mocked `win32com`/ADODB objects on this WSL2 host — end-to-end validation
  against a real Windows Search index remains manual, out of automated CI
  scope (consistent with existing `openspec/config.yaml` testing notes).

### Ready for Proposal

Yes. The pattern to follow is unambiguous (three prior tool families give a
consistent, well-documented template, reinforced by two cross-cutting
retrofits), and the one open design question (default-roots precedence
order, exact allowed-roots config key shape/validation, and where SQL-value
escaping lives) is a normal design-phase decision, not a blocking ambiguity
— propose/spec/design should proceed and can present the roots-config shape
and default precedence as an explicit design.md decision for review at the
PRE-IMPLEMENTATION GATE rather than halting exploration for it.
