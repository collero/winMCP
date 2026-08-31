# Apply Progress: File Search via Windows Search Index

## Batch 1 — Phase 1 + Phase 2 (Foundation: schemas, errors, settings, adapter port + fake)

**Mode**: Strict TDD (test runner: `python3.12 -m pytest -q` — on this
host, run via the venv: `/home/master/WinMCP/.venv/bin/python3.12 -m
pytest -q`; the bare system `python3.12` has no `pytest` installed).

### Completed Tasks

- [x] 1.1 RED `tests/test_schemas.py` — cases for `FileSearchRequest`,
  `GetFileInfoRequest`, `FileSummary`, `FileDetail`.
- [x] 1.2 GREEN `models/schemas.py` — added the 4 models.
- [x] 1.3 RED `tests/test_errors.py` — cases for `SearchRootNotAllowedError`,
  `FileNotFoundInIndexError`, `WindowsSearchUnavailableError`.
- [x] 1.4 GREEN `tools/errors.py` — added the 3 error classes.
- [x] 1.5/1.6 RED+GREEN `tools/settings.py` — `default_search_roots()`
  (new `tests/test_settings.py`).
- [x] 1.7 `config/settings.yaml` — added `file_search_allowed_roots: []`,
  `file_search_max_results: 200` with header comments (structural, no
  test cycle — matches strict-tdd.md's "config file" triangulation
  exemption).
- [x] 2.1 RED `tests/test_fake_file_search_adapter.py` (new) — seed-by-path
  `search()` filtering + `top_n` cap, `get_info()` hit/miss/placeholder.
- [x] 2.2 GREEN `tools/file_search_adapter.py` — `FileSearchPort` Protocol.
- [x] 2.3 GREEN `tools/fake_file_search_adapter.py` — `FakeFileSearchAdapter`.

### Remaining Tasks (next batches)

- [ ] Phase 3: Real Adapter (ADODB / win32com) — tasks 3.1–3.7.
- [ ] Phase 4: Tool Layer (`tools/file_search.py`) — tasks 4.1–4.6.
- [ ] Phase 5: Server Registration — tasks 5.1–5.2.
- [ ] Phase 6: Full Suite + Docs — tasks 6.1–6.3.

### Files Changed

| File | Action | What Was Done |
|------|--------|----------------|
| `models/schemas.py` | Modified | Added `FileSearchRequest`, `GetFileInfoRequest`, `FileSummary`, `FileDetail` |
| `tools/errors.py` | Modified | Added `SearchRootNotAllowedError`, `FileNotFoundInIndexError`, `WindowsSearchUnavailableError` |
| `tools/settings.py` | Modified | Added `default_search_roots()` + private `_casefold_normalized`/`_is_nested_under` helpers |
| `config/settings.yaml` | Modified | Added `file_search_allowed_roots: []`, `file_search_max_results: 200` |
| `tools/file_search_adapter.py` | Created | `FileSearchPort` Protocol (real `WindowsSearchAdapter` NOT yet implemented — Phase 3) |
| `tools/fake_file_search_adapter.py` | Created | `FakeFileSearchAdapter` (in-memory, satisfies the Protocol) |
| `tests/test_schemas.py` | Modified | +9 cases for the 4 new models |
| `tests/test_errors.py` | Modified | +9 cases for the 3 new error classes |
| `tests/test_settings.py` | Created | 6 cases for `default_search_roots()` |
| `tests/test_fake_file_search_adapter.py` | Created | 11 cases for `FakeFileSearchAdapter` |
| `openspec/changes/file-search/tasks.md` | Modified | Marked Phase 1 + Phase 2 tasks `[x]` |

### TDD Cycle Evidence

| Task | Test File | Layer | Safety Net | RED | GREEN | TRIANGULATE | REFACTOR |
|------|-----------|-------|------------|-----|-------|-------------|----------|
| 1.1/1.2 | `tests/test_schemas.py` | Unit | ✅ 220/220 (full suite baseline) | ✅ Written (ImportError on collection) | ✅ 32/32 passed | ✅ 9 cases (aliases, snake_case, defaults, inheritance) | ➖ None needed |
| 1.3/1.4 | `tests/test_errors.py` | Unit | ✅ 220/220 | ✅ Written (ImportError) | ✅ 22/22 passed | ✅ 9 cases (code, message, isinstance, raisable per error) | ➖ None needed |
| 1.5/1.6 | `tests/test_settings.py` (new) | Unit | N/A (new file); `tools/settings.py` pre-existing tests unaffected | ✅ Written (ImportError) | ✅ 6/6 passed | ✅ 6 cases (no-onedrive, empty-env, nested-dedupe, case/separator dedupe, KFM-redirect kept, commercial+consumer ordering) | ➖ Clean on first pass |
| 1.7 | — (config file) | — | N/A | Triangulation skipped: purely structural key/value addition, no branching logic, no test cycle applies | | | |
| 2.1/2.2/2.3 | `tests/test_fake_file_search_adapter.py` (new) | Unit | N/A (new files) | ✅ Written (ModuleNotFoundError) | ✅ 11/11 passed | ✅ 11 cases (filename/phrase/roots filters, cap, empty, sibling-prefix exclusion, get_info hit/miss/placeholder/URL-form) | ➖ Clean on first pass |

### Test Summary

- **Total tests written**: 35 (9 schemas + 9 errors + 6 settings + 11 fake adapter)
- **Total tests passing**: 35/35 new; 255/255 full suite (220 baseline + 35 net-new, exact)
- **Layers used**: Unit (37), Integration (0), E2E (0) — Phase 2 is fully COM-free by design
- **Approval tests** (refactoring): None — no refactoring tasks in this batch
- **Pure functions created**: `default_search_roots`, `_casefold_normalized`, `_is_nested_under` (tools/settings.py); `_normalize`, `_casefold_normalized`, `_is_contained`, `_to_summary` (tools/fake_file_search_adapter.py)

### Deviation from design.md (flag for next batch / orchestrator review)

**design.md's Interfaces/Contracts section** literally specifies:
```python
class FileSearchPort(Protocol):
    def search(self, query: str | None, roots: list[str], top_n: int) -> list[FileSummary]: ...
    def get_info(self, path_or_url: str) -> FileDetail: ...
```

I implemented `search(filename, phrase, roots, top_n)` instead of
`search(query, roots, top_n)` — splitting the single `query` string into
`filename`/`phrase`. Rationale:

1. The **file-search spec**'s "Search Input Parameters" requirement
   defines `filename` (substring match on `System.FileName`) and `phrase`
   (full-text `CONTAINS()` match) as two independently-optional,
   semantically different filters — not one merged string.
2. The **windows-search-adapter spec**'s own escaping scenarios reference
   `filename=` and `phrase=` as distinct adapter call arguments (e.g.
   "the real adapter's `search()` is called with `filename="o'brien"`" and
   "...with `phrase="user's report"`"), and task 3.3 explicitly requires
   escaping "filename/phrase/scope/path" as four distinct interpolated
   values — impossible if they were pre-merged into one `query` string
   before reaching the adapter.
3. `top_n` naming follows design.md/tasks.md (tasks.md's own task 2.2
   text and task 3.4 both say `top_n`), even though the
   windows-search-adapter spec prose says `top`.
4. `roots: list[str]` follows design.md/tasks.md literally (not `scope:
   str` singular) since the SQL builds `SCOPE='file:{root}' OR ...` for
   potentially multiple roots.

**Recommendation**: update design.md's Interfaces/Contracts section to
read `search(filename, phrase, roots, top_n)` before Phase 3 (real
adapter) is implemented, so the real `WindowsSearchAdapter`'s SQL-building
tests (3.1–3.7) are written against a signature that's already
reconciled across all artifacts. This is the single most important thing
the next batch should confirm/resolve first — everything else in this
batch has no known conflicts.

### Other Notes for Next Batch

- `FileSummary` carries `kind`/`extension` (beyond the file-search spec's
  literal minimum of `path`/`name`/`size`/`lastModified`) to match
  design.md's Interfaces/Contracts prose ("`FileSummary`: ... `kind`,
  `extension`") and because the adapter's `SELECT` fetches
  `System.Kind`/`System.FileExtension` for free. Not a conflict — spec
  states a MUST-include minimum, this is a superset.
- `FileSearchRequest` intentionally has NO `model_validator` enforcing
  "at least one of filename/phrase" — the file-search spec's own scenario
  calls for a plain `ValueError` raised by the tool layer
  (`tools/file_search.py`, task 4.1), not a pydantic `ValidationError` at
  schema-construction time. Phase 4 MUST implement that check itself.
- `tools/settings.py::default_search_roots()` and
  `tools/fake_file_search_adapter.py`'s `_casefold_normalized`/
  `_is_contained` are small, intentionally-duplicated private helpers
  (not shared) — each is scoped to its own module's narrow need. Phase 4's
  `tools/file_search.py` will need its own (more complete) `_normalize_path`/
  `_is_contained` per design.md's File Changes table, since it also has to
  handle `ItemUrl`/`ItemPathDisplay` normalization on real adapter output,
  not just plain root-path strings. Worth a light consolidation pass
  later if the duplication grows, but not blocking.
- `FakeFileSearchAdapter.search()`'s `phrase` filter matches against the
  seeded `snippet` field only (there is no modeled file "content" field —
  out of scope per the proposal). This is a reasonable stand-in but Phase
  4's own tool-layer tests should seed `snippet` explicitly whenever they
  exercise `phrase` filtering through the fake.
- Real adapter (`WindowsSearchAdapter`) does NOT exist yet in
  `tools/file_search_adapter.py` — only the Protocol. Phase 3 adds it to
  the same file per design.md's File Changes table.

### Test Result

`/home/master/WinMCP/.venv/bin/python3.12 -m pytest -q` → **255 passed**
(220 baseline + 35 new test functions across 4 files).

### Status

9/9 tasks in Phase 1 + Phase 2 complete. Ready for Phase 3 (Real Adapter),
contingent on resolving the `FileSearchPort` signature note above.

## Batch 2 — Phase 3 (Real Adapter: ADODB / win32com)

**Mode**: Strict TDD (test runner: `/home/master/WinMCP/.venv/bin/python3.12
-m pytest -q`).

**Signature note resolved**: design.md's Interfaces/Contracts section was
already reconciled to `search(filename, phrase, roots, top_n)` before this
batch started (confirmed by re-reading design.md) — no further action
needed; `tools/file_search_adapter.py`'s module docstring's "NOTE:
design.md ... literally spells ... `search(query, roots, top_n)`" caveat
was removed since it's no longer true.

### Completed Tasks

- [x] 3.1 RED+GREEN `tests/test_file_search_adapter.py` (new) —
  `test_win32com_not_imported_at_module_level` /
  `test_pythoncom_not_imported_at_module_level` confirm the module import
  stays COM-free at module scope; `WindowsSearchAdapter._dispatch_connection()`
  imports `pythoncom`/`win32com.client` lazily, inside the method only.
- [x] 3.2 RED+GREEN — `test_search_calls_coinitialize_before_dispatch` /
  `test_get_info_calls_coinitialize_before_dispatch` assert
  `pythoncom.CoInitialize()` precedes `win32com.client.Dispatch("ADODB.Connection")`
  via a `mocker.Mock()` call-order manager, mirroring
  `test_outlook_adapter.py`'s pattern exactly. No `CoUninitialize()` call
  anywhere in the adapter.
- [x] 3.3 RED+GREEN — `test_search_escapes_single_quote_in_filename` /
  `test_search_escapes_single_quote_in_phrase_contains` assert the
  captured SQL (via a hand-rolled `_FakeRecordset.Open(sql, connection)`
  double) contains `o''brien` / `user''s report`, and that the
  `FROM SystemIndex`/`SCOPE=`/`CONTAINS(` machinery around the escaped
  value is intact (clause not truncated early). `_escape_sql()` doubles
  `'`; `_escape_contains_phrase()` additionally strips `"` (no escape
  sequence exists for `"` inside a `CONTAINS()` phrase).
- [x] 3.4 RED+GREEN — `test_search_sql_reflects_requested_top_n` asserts
  `SELECT TOP 50` in the built SQL for `top_n=50`; `_build_search_sql`
  injects `top_n` directly into `TOP {int(top_n)}`, no adapter-side
  default/clamp.
- [x] 3.5 RED+GREEN — `test_search_maps_item_url_only_row_to_normalized_path`
  (a row with `System.ItemPathDisplay=None`, `System.ItemUrl=
  "file:///C:/Users/ana/My%20Report.docx"`) asserts
  `FileSummary.path == "C:\Users\ana\My Report.docx"` via
  `_normalize_path()` (prefer `ItemPathDisplay`, else decode `ItemUrl` +
  `/`→`\`). Triangulated with
  `test_search_happy_path_returns_mapped_summaries` (the common case:
  `ItemPathDisplay` present, filename+phrase+roots all provided together).
- [x] 3.6 RED+GREEN — `test_connection_open_failure_raises_windows_search_unavailable`
  (fake `Connection.Open` raises) and
  `test_recordset_open_failure_raises_windows_search_unavailable` (fake
  `Recordset.Open` raises) both assert `WindowsSearchUnavailableError`,
  not the raw exception, for both `search()` and `get_info()`.
  Triangulated with `test_win32com_import_error_raises_windows_search_unavailable`
  (genuine `ImportError` path, `win32com.client` not importable at all).
- [x] 3.7 RED+GREEN — `test_get_info_returns_detail_for_matching_row`
  (exact path lookup → populated `FileDetail` incl. `created_time`/
  `snippet`), `test_get_info_raises_file_not_found_when_no_row` (empty
  recordset → `FileNotFoundInIndexError`), `test_get_info_snippet_none_when_absent`
  (placeholder-style row with `System.Search.AutoSummary=None` →
  `snippet=None`, not an error).

### Files Changed

| File | Action | What Was Done |
|------|--------|----------------|
| `tools/file_search_adapter.py` | Modified | Added `WindowsSearchAdapter` (real `FileSearchPort` impl): `_dispatch_connection()` (lazy `pythoncom`/`win32com.client` import + `CoInitialize()` + `ADODB.Connection.Open()`), `_execute()` (`ADODB.Recordset.Open(sql, connection)`), `_build_search_sql()`/`_build_get_info_sql()`, `_escape_sql()`/`_escape_contains_phrase()`, `_normalize_path()`, `_field()`/`_row_to_summary()`/`_row_to_detail()`. Removed the now-stale design.md-deviation NOTE from the module docstring. |
| `tests/test_file_search_adapter.py` | Created | 15 cases across tasks 3.1–3.7, incl. 2 triangulation cases (`test_search_happy_path_returns_mapped_summaries`, `test_win32com_import_error_raises_windows_search_unavailable`). Hand-rolled `_FakeConnection`/`_FakeRecordset`/`_FakeFields`/`_FakeField` doubles (not `mocker.Mock`) so `.EOF`/`.Fields`/`.MoveNext()` behave statefully across a loop while `.Open()` still records call args and can be configured to raise. `_install_fake_pythoncom`/`_install_fake_win32com` mirror `tests/test_outlook_adapter.py`'s helpers of the same name, extended so `Dispatch()` returns different objects for `"ADODB.Connection"` vs `"ADODB.Recordset"` ProgIDs. |
| `openspec/changes/file-search/tasks.md` | Modified | Marked Phase 3 tasks 3.1–3.7 `[x]`. |

### Design decisions made in this batch (not pre-specified)

- **`Recordset.Open(sql, connection)` over `Connection.Execute(sql)`**:
  design.md's Data Flow prose says "`Connection.Execute(sql)` ─▶
  Recordset", but the windows-search-adapter spec's own scenario wording
  ("a fake `win32com.client` module capturing the SQL text passed to
  `Recordset.Open`") and the Connection-Failure requirement's
  "`ADODB.Connection.Open` (or `Recordset.Open`)" phrasing both name
  `Recordset.Open` specifically as the SQL-execution call. Since spec
  Scenario blocks are the acceptance criteria actually under test, this
  batch implemented via a separate `Dispatch("ADODB.Recordset")` +
  `recordset.Open(sql, connection)` — classic ADODB two-object usage —
  rather than `Connection.Execute()`. No behavioral difference visible to
  callers; flagging only because design.md's prose now describes the
  *shape* slightly differently than the code. Not a blocking
  inconsistency — no scenario tests `Connection.Execute` directly.
- **`get_info()`'s exact-match SQL** (`WHERE System.ItemPathDisplay = '...'
  OR System.ItemUrl = '...'`) and its extra `SELECT` fields
  (`System.DateCreated`, `System.Search.AutoSummary` for `snippet`) are
  this batch's own addition — neither design.md nor the specs fix
  `get_info()`'s exact SQL shape (design.md's ADODB-specifics decision
  only spells out `search()`'s SELECT list). `System.Search.AutoSummary`
  is Windows Search's standard content-preview/snippet property; picked
  as the closest fit for `FileDetail.snippet` per the file-get-info
  spec's "OneDrive Placeholder Metadata"/"Detail omits content when not
  indexed" requirements (both expect `snippet=None` to be a normal,
  non-error outcome, which this property naturally supports since it's
  empty/absent for unhydrated placeholders and unindexed content).

### TDD Cycle Evidence

| Task | Test File | Layer | Safety Net | RED | GREEN | TRIANGULATE | REFACTOR |
|------|-----------|-------|------------|-----|-------|-------------|----------|
| 3.1 | `tests/test_file_search_adapter.py` (new) | Unit | ✅ 255/255 (Batch 1 baseline) | ✅ Written first; ran to confirm 13/15 failed with `ImportError: cannot import name 'WindowsSearchAdapter'` (2 module-level-import tests passed immediately since the Protocol-only file already imported cleanly) | ✅ 15/15 passed after implementing `WindowsSearchAdapter` | ✅ both win32com- and pythoncom-absent variants | ➖ None needed |
| 3.2 | same | Unit | ✅ | ✅ (same RED run) | ✅ | ✅ both `search()` and `get_info()` call paths asserted independently | ➖ None needed |
| 3.3 | same | Unit | ✅ | ✅ (same RED run) | ✅ | ✅ filename quote + phrase quote as 2 distinct cases (LIKE clause vs. CONTAINS clause escaping) | ➖ None needed |
| 3.4 | same | Unit | ✅ | ✅ (same RED run) | ✅ | ➖ single-case requirement, no meaningful second case | ➖ None needed |
| 3.5 | same | Unit | ✅ | ✅ (same RED run) | ✅ | ✅ ItemUrl-only fallback case + happy-path ItemPathDisplay-present case | ➖ None needed |
| 3.6 | same | Unit | ✅ | ✅ (same RED run) | ✅ | ✅ Connection.Open failure + Recordset.Open failure + genuine ImportError, 3 distinct failure points | ➖ None needed |
| 3.7 | same | Unit | ✅ | ✅ (same RED run) | ✅ | ✅ found/not-found/placeholder-snippet-None, 3 cases | ➖ None needed |

### Test Summary

- **Total tests written this batch**: 15 (all in `tests/test_file_search_adapter.py`)
- **Total tests passing**: 15/15 new; 270/270 full suite (255 Batch-1
  baseline + 15 new, exact)
- **Layers used**: Unit (15), Integration (0 — this project's "Integration"
  testing-strategy row for the adapter is, in practice, the same
  `sys.modules`-fake-injection unit-test technique used throughout, not a
  separate harness), E2E (0)
- **Approval tests** (refactoring): None — no refactoring tasks in this batch
- **Pure functions created**: `_escape_sql`, `_escape_contains_phrase`,
  `_build_search_sql`, `_build_get_info_sql`, `_normalize_path`, `_field`,
  `_row_to_summary`, `_row_to_detail` (all in `tools/file_search_adapter.py`)

### Deviations from design.md

None blocking — see "Design decisions made in this batch" above for two
non-blocking clarifications (`Recordset.Open` vs. `Connection.Execute`
phrasing; `get_info()`'s SQL shape/fields, which design.md leaves
unspecified).

### Other Notes for Next Batch (Phase 4: Tool Layer)

- `WindowsSearchAdapter` is fully config-unaware, as required — it never
  reads `config/settings.yaml` itself. Phase 4's `tools/file_search.py`
  owns all roots-policy/default-resolution/cap-resolution and must pass
  already-validated `roots: list[str]` and `top_n: int` straight through.
- `WindowsSearchAdapter.search()`/`get_info()` never re-check roots
  containment on their own output — Phase 4's "post-call defense-in-depth"
  drop-non-conforming-rows step (task 4.4) is entirely the tool layer's
  responsibility; the adapter's `SCOPE=` clause is a best-effort filter,
  not a security boundary by itself.
- `FileSearchPort.get_info(path_or_url)` accepts the raw string as-is
  (either native path or `file:///` URL form) and matches it exactly
  against either indexed column — Phase 4 should NOT pre-normalize
  `path_or_url` before calling the adapter's `get_info()` (unlike the
  roots-containment check, which Phase 4 does need to normalize for, per
  design.md's Decision #4). Only the *containment check* needs
  `_normalize_path`/case-fold; the adapter call itself wants the original
  string.
- `tools/file_search_adapter.py`'s `_normalize_path` (adapter-internal,
  ItemUrl/ItemPathDisplay decode-only) and Batch 1's
  `tools/fake_file_search_adapter.py::_normalize` are intentionally
  similar/duplicated small helpers, each scoped to its own module — not
  shared, consistent with Batch 1's precedent of small scoped duplication
  over premature sharing.

### Test Result

`/home/master/WinMCP/.venv/bin/python3.12 -m pytest -q` → **270 passed**
(255 Batch 1 baseline + 15 new test functions in
`tests/test_file_search_adapter.py`).

### Status

16/16 tasks in Phase 1 + Phase 2 + Phase 3 complete (9 from Batch 1 + 7
from Batch 2). Ready for Phase 4 (Tool Layer, `tools/file_search.py`) —
tasks 4.1–4.6, per the notes above.

## Batch 3 — Phase 4 (Tool Layer: `tools/file_search.py`)

**Mode**: Strict TDD (test runner: `/home/master/WinMCP/.venv/bin/python3.12
-m pytest -q`).

### Completed Tasks

- [x] 4.1 RED+GREEN `tests/test_file_search_tools.py` (new) —
  `test_search_both_filename_and_phrase_omitted_raises_value_error` /
  `test_search_filename_and_phrase_both_absent_and_scope_absent_also_raises`
  assert a plain `ValueError` before any adapter call (spy
  `assert_not_called()`), checked FIRST in `file_search()` — before
  `load_settings()` even runs — matching `tools/mail.py::mail_search`'s
  precedent of the mandatory-filter check running before any adapter
  interaction.
- [x] 4.2 RED+GREEN —
  `test_search_out_of_root_scope_raises_before_adapter_call` /
  `test_search_case_separator_variant_of_allowed_root_accepted` /
  `test_search_sibling_directory_shared_prefix_refused` assert
  `SearchRootNotAllowedError` pre-adapter, a `c:/users/ana/Documents`
  variant of an allowed `C:\Users\ana` root accepted, and
  `C:\Users\ana2\Documents` (sibling, shared name prefix) refused — via
  `tools/file_search.py::_normalize_path()`/`_is_contained()` (new,
  module-scoped helpers, not shared with `tools/settings.py`'s or
  `tools/fake_file_search_adapter.py`'s near-identical ones, per Batch
  1/2's precedent).
- [x] 4.3 RED+GREEN —
  `test_search_default_roots_resolved_from_environment_when_unconfigured`
  (unconfigured `file_search_allowed_roots`, `USERPROFILE`/`OneDrive` env
  vars set, scope under `OneDrive` allowed via
  `default_search_roots()`'s fallback) and
  `test_search_unconfigured_roots_rejects_scope_outside_default_roots`
  (triangulation: the fallback still enforces containment) — via
  `tools/file_search.py::_allowed_roots()`.
- [x] 4.4 RED+GREEN —
  `test_search_unconfigured_cap_defaults_to_200` /
  `test_search_configured_cap_passed_through` (triangulation: a
  configured `file_search_max_results=5` overrides the default),
  `test_search_happy_path_returns_mapped_summaries`,
  `test_search_empty_result_returns_empty_list_not_error`, and
  `test_search_drops_result_row_outside_allowed_roots` (post-call
  defense-in-depth, exercised via a hand-rolled `_MisbehavingAdapter`
  stub whose `search()` ignores the `roots` it was given and always
  returns an out-of-root row — `FakeFileSearchAdapter` already filters
  correctly on its own, so it cannot exercise the tool layer's own
  independent drop step) — via
  `tools/file_search.py::_max_results()`/`_drop_outside_allowed_roots()`.
  The post-call drop checks every row against the full configured/
  default `allowed_roots`, never the narrower per-call `scope`, per
  task 4.4's literal wording and design.md decision #3(b).
- [x] 4.5 RED+GREEN — `test_search_windows_search_unavailable_propagates`
  asserts `WindowsSearchUnavailableError` propagates uncaught from
  `file_search()`, via a hand-rolled `_UnavailableAdapter` stub (not
  `FakeFileSearchAdapter`, which has no unavailable-mode — Batch 1/2
  scope did not add one, unlike `FakeMailAdapter`'s `unavailable=True`).
- [x] 4.6 RED+GREEN — `test_get_info_success_returns_full_detail`,
  `test_get_info_out_of_root_path_refused_before_adapter_call` (spy
  `assert_not_called()` on the adapter's `get_info`),
  `test_get_info_unknown_path_propagates_file_not_found_in_index_error`,
  `test_get_info_placeholder_file_returns_detail_with_snippet_none`, and
  (triangulation, beyond the task's literal 3 sub-items, mirroring 4.5
  for the file-get-info spec's own "Windows Search Unavailable"
  requirement) `test_get_info_windows_search_unavailable_propagates` — via
  `tools/file_search.py::file_get_info()`. `path` is NOT pre-normalized
  before the adapter call itself (only for the containment check), per
  Batch 2's handoff note.

### Files Changed

| File | Action | What Was Done |
|------|--------|----------------|
| `tools/file_search.py` | Created | `file_search()`/`file_get_info()`, `_allowed_roots()`, `_max_results()`, `_normalize_path()`, `_is_contained()`, `_check_contained()`, `_drop_outside_allowed_roots()` |
| `tests/test_file_search_tools.py` | Created | 18 cases across tasks 4.1–4.6, incl. 2 hand-rolled `FileSearchPort` stubs (`_UnavailableAdapter`, `_MisbehavingAdapter`) for scenarios `FakeFileSearchAdapter` cannot itself exercise |
| `openspec/changes/file-search/tasks.md` | Modified | Marked Phase 4 tasks 4.1–4.6 `[x]` |

### Design decisions made in this batch (not pre-specified)

- **Order of the two pre-adapter checks in `file_search()`**: the
  mandatory-filter `ValueError` (task 4.1) is checked FIRST, before
  `load_settings()`/`_allowed_roots()`/the scope-containment check even
  run — design.md's Data Flow numbered list only shows the roots check
  explicitly (step 2) and doesn't mention the mandatory-filter check at
  all. This batch resolved the ordering by mirroring `tools/mail.py::mail_search`'s
  existing precedent (mandatory-filter check runs first, before any
  settings/adapter interaction). No spec scenario tests the two failure
  modes together (both would-be errors triggered by one request), so
  this is unobservable either way from outside — flagging only for
  completeness, not a conflict.
- **`search_roots` passed to the adapter**: when `scope` is given (and
  passes containment), `roots=[request.scope]` (the narrower, literal
  scope string) is passed to `adapter.search()` — not the full
  `allowed_roots` list. When `scope` is omitted, `roots=allowed_roots`
  (the full configured/default list) is passed, matching the spec's
  "the unrestricted query" phrasing. Neither design.md nor the specs
  spell out which of these two shapes to send when `scope` is present;
  this reading is what makes the file-search spec's own "Filename and
  scope provided together" scenario ("the adapter's `search()` is
  invoked with the filename filter and scope") sensible — an adapter
  call scoped to the literal requested subtree, not the whole allowed
  root.

### TDD Cycle Evidence

| Task | Test File | Layer | Safety Net | RED | GREEN | TRIANGULATE | REFACTOR |
|------|-----------|-------|------------|-----|-------|-------------|----------|
| 4.1 | `tests/test_file_search_tools.py` (new) | Unit | ✅ 270/270 (Batch 1+2 baseline) | ✅ Written first; ran to confirm `ModuleNotFoundError: No module named 'tools.file_search'` (all 18 cases failed at collection) | ✅ 18/18 passed after implementing `tools/file_search.py` in full | ✅ 2 cases (scope-alone vs. bare-call) | ➖ None needed |
| 4.2 | same | Unit | ✅ | ✅ (same RED run) | ✅ | ✅ 3 cases (out-of-root / case-separator-variant-accepted / sibling-prefix-refused) | ➖ None needed |
| 4.3 | same | Unit | ✅ | ✅ (same RED run) | ✅ | ✅ 2 cases (default-allowed / default-still-enforces-containment) | ➖ None needed |
| 4.4 | same | Unit | ✅ | ✅ (same RED run) | ✅ | ✅ 5 cases (default cap / configured cap / happy path / empty / post-call drop) | ➖ None needed |
| 4.5 | same | Unit | ✅ | ✅ (same RED run) | ✅ | ➖ single scenario in spec, no meaningful second case for `file_search` itself | ➖ None needed |
| 4.6 | same | Unit | ✅ | ✅ (same RED run) | ✅ | ✅ 5 cases (success / out-of-root / not-found / placeholder-snippet-none / unavailable-propagates) | ➖ None needed |

### Test Summary

- **Total tests written this batch**: 18 (all in `tests/test_file_search_tools.py`)
- **Total tests passing**: 18/18 new; 288/288 full suite (270 Batch 1+2
  baseline + 18 new, exact)
- **Layers used**: Unit (18), Integration (0), E2E (0)
- **Approval tests** (refactoring): None — no refactoring tasks in this batch
- **Pure functions created**: `_allowed_roots`, `_max_results`,
  `_normalize_path`, `_is_contained`, `_check_contained` (pure aside from
  raising), `_drop_outside_allowed_roots` (all in `tools/file_search.py`)

### Deviations from design.md

None — both design decisions made in this batch (see above) fill gaps
design.md left open, they do not contradict anything design.md states.

### Other Notes for Next Batch (Phase 5: Server Registration)

- `tools/file_search.py::file_search`/`file_get_info` both have the
  signature `(request, adapter) -> ...`, exactly mirroring
  `tools/mail.py::mail_search`/`mail_get_message` — Phase 5's
  `server.py` registration can follow that same wiring pattern
  (`_resolve_real_file_search_adapter()` lazy/cached, `@app.tool`
  wrappers constructing the Pydantic request and calling the tool
  function with the adapter).
- Neither typed error (`SearchRootNotAllowedError`,
  `FileNotFoundInIndexError`, `WindowsSearchUnavailableError`) is caught
  anywhere in `tools/file_search.py` — all three propagate uncaught, to
  be mapped by `server.py::_map_error()` (already generic over the
  `CalendarToolError` taxonomy per Batch 1's note — task 5.2 says no
  change needed there).
- `FakeFileSearchAdapter` was NOT modified this batch (no
  `unavailable=True` constructor flag was added, unlike
  `FakeMailAdapter`) — the two scenarios needing an unavailable/
  misbehaving adapter used small hand-rolled stubs local to
  `tests/test_file_search_tools.py` instead. If Phase 5's
  `tests/test_server.py` needs the same unavailable-adapter behavior for
  its own `file_search`/`file_get_info` wiring tests, consider either
  reusing a similar local stub there or promoting an `unavailable=True`
  flag onto `FakeFileSearchAdapter` at that point — not done here since
  it wasn't required by any Phase 4 task/scenario.

### Test Result

`/home/master/WinMCP/.venv/bin/python3.12 -m pytest -q` → **288 passed**
(270 Batch 1+2 baseline + 18 new test functions in
`tests/test_file_search_tools.py`).

### Status

22/22 tasks in Phase 1 + Phase 2 + Phase 3 + Phase 4 complete (9 from
Batch 1 + 7 from Batch 2 + 6 from Batch 3). Ready for Phase 5 (Server
Registration) — tasks 5.1–5.2, per the notes above.

## Batch 4 (final) — Phase 5 (Server Registration) + Phase 6 (Full Suite + Docs)

**Mode**: Strict TDD for Phase 5 (test runner:
`/home/master/WinMCP/.venv/bin/python3.12 -m pytest -q`); Phase 6 is
docs/confirmation-only (structural, per strict-tdd.md's exemption — no
test cycle applies to README prose or a "no new dependency" check).

### Completed Tasks

- [x] 5.1 RED `tests/test_server.py` — extended
  `test_import_succeeds_without_win32com` with an
  `assert "tools.file_search_adapter" in sys.modules` check; widened the
  three exact-set tool-registration assertions
  (`test_all_three_tools_registered`, `test_task_tools_registered`,
  `test_mail_tools_registered`) to include `"file_search"`/
  `"file_get_info"`; added
  `test_file_search_tools_registered_via_fake_file_search_adapter` (mirrors
  `test_mail_tools_registered`), 4 end-to-end call tests (happy path,
  no-filters → `invalid_request`, out-of-root `scope` →
  `search_root_not_allowed`, `file_get_info` happy path,
  `file_get_info` unknown path → `file_not_found_in_index`), and
  `test_file_search_adapter_selection_deferred_when_win32com_unavailable`
  (mirrors `test_mail_adapter_selection_deferred_when_win32com_unavailable`).
  Confirmed RED first: 10 failures (`TypeError: create_server() got an
  unexpected keyword argument 'file_search_adapter'` / set-mismatch
  `AssertionError`s / missing `sys.modules` entry), 19 passed.
- [x] 5.2 GREEN `server.py` — added `FileSearchPort`-typed
  `_lazy_real_file_search_adapter` global + `_resolve_real_file_search_adapter()`
  (lazy/cached, mirrors `_resolve_real_mail_adapter()`; the concrete
  `WindowsSearchAdapter` is imported only inside this function, never at
  module scope — `tools.file_search_adapter` itself, imported at module
  level for the `FileSearchPort` type, stays win32com-free at import
  time). Added `file_search_adapter: FileSearchPort | None = None` param
  to `create_server()`, a `_file_search_adapter()` closure mirroring
  `_mail_adapter()`, and two new `@app.tool` registrations
  (`file_search`, `file_get_info`) constructing `FileSearchRequest`/
  `GetFileInfoRequest` and delegating to `tools.file_search.file_search`/
  `file_get_info`, catching `(CalendarToolError, ValueError)` /
  `CalendarToolError` respectively and re-raising via `_map_error()`
  (unchanged — confirmed it already covers `SearchRootNotAllowedError`/
  `FileNotFoundInIndexError`/`WindowsSearchUnavailableError` generically
  since all three subclass `CalendarToolError`, no edit needed per the
  task's own note). `tests/test_server.py` → 29/29 passed after
  implementation.
- [x] 6.1 Ran `/home/master/WinMCP/.venv/bin/python3.12 -m pytest -q` for
  the full suite after 5.2's GREEN — surfaced one pre-existing-test
  regression not anticipated by tasks.md/design.md:
  `tests/test_smoke_test.py::test_expected_tools_matches_server_registered_names`
  failed (`EXPECTED_TOOLS` in `deploy/smoke_test.py` — a fixed 7-tool set
  asserted to equal *exactly* `server.py`'s registered tool names, per the
  smoke-test-coverage change's "Expected Tool Set Matches Registered
  Tools" requirement — no longer matched now that `server.py` registers
  9 tools). Fixed by adding `"file_search"`/`"file_get_info"` to
  `EXPECTED_TOOLS` in `deploy/smoke_test.py` (this addition only affects
  the tools/list-name consistency check — `check_tools_list()`'s "extra"
  branch is a non-fatal note, not a failure, so no new smoke-test
  `Family`/live-call step was required or added), and updated
  `tests/test_smoke_test.py::test_expected_tools_matches_server_registered_names`
  to also inject a `FakeFileSearchAdapter` (for symmetry with the other
  three fakes already passed there) and its docstring's tool count
  (7 → 9). Full suite green after the fix: **295 passed** (288 Batch 1-3
  baseline + 7 new test functions in `tests/test_server.py`; no net-new
  test in `tests/test_smoke_test.py`, only an existing test's body
  updated).
- [x] 6.2 `README.md` — added `file_search`/`file_get_info` to the tool
  list (updated "seven tools" → "nine tools" throughout: intro, step 7 of
  the packaged install, the manual/dev install path, and the manual
  smoke-test's tool-list-count step); documented `file_search_allowed_roots`
  (default `[]`, env-var fallback order `%USERPROFILE%` →
  `%OneDrive%`/`%OneDriveCommercial%`/`%OneDriveConsumer%`, nested-root
  dedupe) and `file_search_max_results` (default `200`, `TOP n` bound) in
  "Configuration"; added `FakeFileSearchAdapter`/`tools/file_search.py`/
  `tests/test_file_search_adapter.py` to "Development (WSL2 / Linux)";
  added two new manual-smoke-test steps (9: `file_search`/`file_get_info`
  happy path + an out-of-root `scope` refusal check; 10: stop the
  Windows Search service → `windows_search_unavailable`) to "Manual
  smoke test"; added a "Known limitations" bullet covering index-dependency
  (no indexing ≠ a distinct error from "no matches"), content/snippet
  scope, and the current lack of `deploy/smoke_test.py` live coverage for
  these two tools (mirrors the existing `folderPath`/`includeHtmlBody`
  precedent bullet's phrasing).
- [x] 6.3 `pyproject.toml` — confirmed no edit needed: grepped every
  import in `tools/file_search.py`, `tools/file_search_adapter.py`,
  `tools/fake_file_search_adapter.py`, and their three test files;
  nothing beyond stdlib (`urllib.parse`, `typing`), this project's own
  `models`/`tools` packages, and the already-declared `pywin32`
  (`win32com.client`/`pythoncom`, lazily imported, ADODB accessed via
  `win32com.client.Dispatch("ADODB.Connection"/"ADODB.Recordset")` — no
  separate ADODB package exists or is needed). `pyproject.toml` left
  unchanged.

### Files Changed

| File | Action | What Was Done |
|------|--------|----------------|
| `server.py` | Modified | Added `FileSearchPort` import, `_lazy_real_file_search_adapter`, `_resolve_real_file_search_adapter()`, `file_search_adapter` param on `create_server()`, `_file_search_adapter()` closure, `@app.tool` registrations for `file_search`/`file_get_info`; updated module docstring |
| `tests/test_server.py` | Modified | +1 import line (`FileDetail`, `FakeFileSearchAdapter`); extended `test_import_succeeds_without_win32com`; widened 3 exact-set tool-list assertions; +7 new tests (registration-via-fake, happy path, invalid_request, search_root_not_allowed, get_info happy path, get_info file_not_found_in_index, win32com-unavailable-deferred) |
| `deploy/smoke_test.py` | Modified | Added `"file_search"`/`"file_get_info"` to `EXPECTED_TOOLS` (unplanned, discovered via task 6.1's full-suite run — see note above) |
| `tests/test_smoke_test.py` | Modified | `test_expected_tools_matches_server_registered_names` now also injects `FakeFileSearchAdapter`; docstring tool count 7 → 9 (unplanned, same cause) |
| `README.md` | Modified | Documented `file_search`/`file_get_info` tools, `file_search_allowed_roots`/`file_search_max_results` settings keys, dev/smoke-test/limitations sections |
| `openspec/changes/file-search/tasks.md` | Modified | Marked Phase 5 (5.1–5.2) and Phase 6 (6.1–6.3) tasks `[x]` |

### TDD Cycle Evidence

| Task | Test File | Layer | Safety Net | RED | GREEN | TRIANGULATE | REFACTOR |
|------|-----------|-------|------------|-----|-------|-------------|----------|
| 5.1/5.2 | `tests/test_server.py` | Server/wiring | ✅ 288/288 (Batch 1-3 baseline) | ✅ Written first; confirmed 10/29 file-search-related assertions failed (`TypeError` on the new kwarg + set-mismatch `AssertionError`s + missing `sys.modules` entry) before any `server.py` edit | ✅ 29/29 passed after implementing the `server.py` registration | ✅ 7 distinct scenarios (registration listing, happy-path search, missing-filter error, out-of-root error, happy-path get_info, not-found error, win32com-unavailable deferred) | ➖ None needed |
| 6.1 (regression fix) | `tests/test_smoke_test.py` | Unit | ✅ 295/295 target reached | N/A — this was an *existing* test regressing, not a new RED/GREEN cycle; fixed by widening `EXPECTED_TOOLS`, not by writing a new test | ✅ confirmed passing after the fix | N/A | ➖ None needed |
| 6.2/6.3 | — (docs / dependency-audit) | — | N/A | Triangulation skipped: purely structural prose/config-confirmation, no branching logic, no test cycle applies (strict-tdd.md's "config/docs file" exemption, same as Batch 1's 1.7) | | | |

### Test Summary

- **Total tests written this batch**: 7 (all in `tests/test_server.py`)
- **Total tests passing**: 295/295 full suite (288 Batch 1-3 baseline + 7
  new, exact) — includes the `tests/test_smoke_test.py` regression fix
  (an existing test's body updated, not a new test added)
- **Layers used**: Server/wiring (7, via FastMCP's in-process `Client`),
  Unit (0 new — Phase 5/6 added no new tool-layer/adapter-layer tests),
  E2E (0)
- **Approval tests** (refactoring): None — no refactoring tasks in this batch
- **Pure functions created**: None new in `server.py` beyond the
  established `_resolve_real_*`/`_*_adapter()` closure pattern (no new
  business logic — Phase 4 already owns all of it)

### Deviations from design.md / tasks.md

None from design.md — `server.py`'s registration follows the "mirror the
mail seam exactly" approach literally, and `_map_error()` needed no
change exactly as design.md/task 5.2 predicted.

One **unplanned but necessary fix**, not a deviation from design intent:
task 6.1 ("full suite green, no regressions") surfaced that
`deploy/smoke_test.py`'s `EXPECTED_TOOLS` constant (added by an earlier,
unrelated "smoke-test-coverage" change, which encodes an exact-match
invariant against `server.py`'s registered tool names) had not been
updated for the two new tools. This is not something tasks.md/design.md
for *this* change could have anticipated since `EXPECTED_TOOLS` lives
outside this change's File Changes table — fixed as the minimal edit
needed to keep that pre-existing invariant true, without adding a new
live-smoke-test `Family` for `file_search`/`file_get_info` (deliberately
out of scope here; flagged instead as a "no smoke-test coverage yet"
Known-limitations bullet in `README.md`, mirroring the existing
`folderPath`/`includeHtmlBody` precedent).

### Other Notes

- `file_search_adapter` (the `create_server()` param and the
  `FakeFileSearchAdapter` fixture) is now the 4th injectable adapter,
  following the exact same optionality/lazy-resolution shape as
  `adapter`/`task_adapter`/`mail_adapter` — no asymmetry introduced.
- Live smoke-test coverage (`deploy/smoke_test.py`'s `FAMILIES` +
  per-family live `tools/call`s) for `file_search`/`file_get_info` was
  intentionally NOT added in this batch — it wasn't part of tasks.md's
  Phase 5/6 scope, and doing it well would need a real, host-specific
  seed file/path to search for (unlike calendar/tasks/mail, which search
  arbitrary "any results or empty" ranges). Recommended as a natural
  follow-up change if/when live coverage is wanted.

### Test Result

`/home/master/WinMCP/.venv/bin/python3.12 -m pytest -q` → **295 passed**
(288 Batch 1+2+3 baseline + 7 new test functions in
`tests/test_server.py`; `tests/test_smoke_test.py`'s pre-existing
`EXPECTED_TOOLS`-consistency test updated in place, not net-new).

### Status

27/27 tasks across all 6 phases complete (9 Batch 1 + 7 Batch 2 + 6 Batch
3 + 5 Batch 4: 2 Phase 5 + 3 Phase 6). `openspec/changes/file-search/tasks.md`
now has 27 `[x]` and 0 `[ ]` checkboxes (confirmed via grep). The
**file-search** change is fully implemented and ready for `/sdd-verify`
(or direct archive review) — no known blockers.
