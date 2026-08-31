# Apply Progress: file-search-resilience

## Batch 1 (Phases 1-2) — Config/Errors/Schema foundations + filesystem walk

**Mode**: Strict TDD (per `.claude/CLAUDE.md` / `openspec/config.yaml`'s
`strict_tdd: true`). Test runner: `.venv/bin/python3.12 -m pytest -q`.

**Baseline going in**: `1 failed, 309 passed` (the 1 failure was in
`tests/test_mail_adapter.py::test_inbox_search_restricts_on_received_time`
— a sibling change in flight editing `tools/mail_adapter.py`/its tests
concurrently; not caused by, or fixed by, this batch's diff). By the end
of this batch the sibling's own work had also landed and that failure was
gone — full suite is green.

### TDD Cycle Evidence

| Task | Test File | Layer | Safety Net | RED | GREEN | TRIANGULATE | REFACTOR |
|------|-----------|-------|------------|-----|-------|-------------|----------|
| 1.1-1.2 | `tests/test_settings.py` | Unit | ✅ 6/6 pre-existing | ✅ Written (ImportError confirmed) | ✅ Passed | ✅ 6 cases (default + configured x3 keys) | ➖ None needed |
| 1.3-1.4 | `tests/test_errors.py` | Unit | ✅ 22/22 pre-existing | ✅ Written (ImportError confirmed) | ✅ Passed | ✅ 3 cases (code, taxonomy, raisable) | ➖ None needed |
| 1.5-1.6 | `tests/test_schemas.py` | Unit | ✅ 32/32 pre-existing | ✅ Written (class didn't exist) | ✅ Passed | ✅ 2 cases (default False, alias True) | ➖ None needed |
| 2.1-2.7 | `tests/test_file_search_walk.py` (new) | Unit | N/A (new file) | ✅ Written (ModuleNotFoundError confirmed via full-suite run) | ✅ Passed after 1 fix (see below) | ✅ 13 cases across all 6 scenario groups | ✅ Extracted `_is_reparse_point`/`_summary_from_entry`; renamed combined cap-check for clarity |

### Test Summary
- **Total tests written this batch**: 24 (6 settings + 3 errors + 2 schemas + 13 walk)
- **Total tests passing**: 339/339 (full suite)
- **Layers used**: Unit (24)
- **Approval tests** (refactoring): None — no refactoring of existing production code, only additive changes
- **Pure functions created**: `file_search_walk_time_budget_seconds`, `file_search_walk_max_dirs`,
  `file_search_ps_bridge_timeout_seconds` (all pure given a settings dict, though they call
  `load_settings()` internally per the existing `local_timezone()` precedent — never cached),
  `_is_reparse_point`, `_summary_from_entry` (pure given an entry), `walk_filename` (deterministic
  given its inputs and injected `os.scandir`/`time.monotonic`)

### Bug found and fixed during GREEN (walk_filename dir-count cap)

Initial implementation checked the `max_dirs` cap inside the per-entry loop
(alongside the results/time checks), which meant that with `max_dirs=1`, the
very last directory the budget allows would have its own entries cut off
immediately (since `dirs_visited` was already incremented to `1` before
iterating that directory's entries) — a triangulation test
(`test_walk_completes_within_all_caps_when_dir_budget_exactly_suffices`)
caught this as a false-truncation. Fixed by only checking `dirs_visited >=
max_dirs` at the top of the outer directory loop (gating whether to *start*
another directory), never inside the inner entry loop. Documented in the
module's inline comment.

## Files Changed

| File | Action | What Was Done |
|------|--------|----------------|
| `tests/test_settings.py` | Modified | Added 6 tests for the 3 new config readers |
| `tools/settings.py` | Modified | Added `file_search_walk_time_budget_seconds()` (default 5), `file_search_walk_max_dirs()` (default 5000), `file_search_ps_bridge_timeout_seconds()` (default 10) — each reads `load_settings()` live, never cached |
| `config/settings.yaml` | Modified | Added the 3 new keys with their defaults + doc comments |
| `tests/test_errors.py` | Modified | Added 3 tests for `PathNotFoundError` |
| `tools/errors.py` | Modified | Added `PathNotFoundError` (code `path_not_found`), reusing the `CalendarToolError` taxonomy |
| `tests/test_schemas.py` | Modified | Added 2 tests for `FileSearchResponse` |
| `models/schemas.py` | Modified | Added `FileSearchResponse` (`results: list[FileSummary]`, `results_truncated: bool = False`, alias `resultsTruncated`) — see deviation note below |
| `tests/test_file_search_walk.py` | Created | 13 tests covering all Phase 2 scenarios (substring match, recursion, size/mtime mapping, files-only matching, result/time/dir-count caps + truncation flagging, reparse-point skip incl. symlink variant, permission-error skip) |
| `tools/file_search_walk.py` | Created | `walk_filename(roots, filename, max_results, time_budget_s, max_dirs) -> tuple[list[FileSummary], bool]`, `_is_reparse_point()`, `_summary_from_entry()` |
| `openspec/changes/file-search-resilience/tasks.md` | Modified | Checked off 1.1-1.6, 2.1-2.7 |

## Deviations from Design

1. **`FileSearchResponse` model name/shape is this batch's own choice.**
   design.md/proposal.md/tasks.md all say "add `results_truncated` to
   `FileSummary`/response" without naming a concrete model — and
   `results_truncated` is semantically a per-*search-call* flag, not a
   per-*file* flag, so adding it onto `FileSummary` itself (each row
   repeating the same value) would be wrong. I introduced
   `FileSearchResponse(results: list[FileSummary], results_truncated:
   bool = False)` as the natural envelope, matching the file-search
   spec's MODIFIED "Search Output Shape" wording ("The response MUST
   additionally report `results_truncated`"). **This is NOT yet wired
   up** — `tools/file_search.py::file_search()` still returns a bare
   `list[FileSummary]` and `server.py`'s `_file_search` tool still
   declares `-> list[FileSummary]`; switching both to return/declare
   `FileSearchResponse` is Phase 5/6 work (a later batch). Whoever picks
   up Phase 5 should use this model rather than inventing another one.
2. **`walk_filename` matches files only, never directory names.** Neither
   spec text explicitly says whether a directory whose name matches
   `filename` should itself be a result. I chose files-only (a directory
   is only ever a traversal target, never a hit) since `FileSummary`/the
   existing `FakeFileSearchAdapter` model files, and "file search" reads
   as searching for files. Covered by a triangulation test
   (`test_walk_only_matches_files_not_directory_names`). If Phase 5's
   integration work reveals the real Windows Search index also returns
   folders for a `filename` query and parity is wanted, this is the
   single line to change (`if is_dir: ... continue` currently always
   skips matching for directories).
3. **`FileSummary.extension` is populated by the walk** (via
   `os.path.splitext`), even though the filesystem-walk-search spec only
   requires `path`/`name`/`size`/`last_modified`. Low-risk, cheap, and
   gives Phase 5's walk+adapter intersection consistent `extension`
   values on both legs. `kind` has no filesystem-level equivalent and is
   left `None`.

## Issues Found

None beyond the dir-count cap bug (caught and fixed during this batch's
own GREEN step, see above — never shipped).

## Remaining Tasks (Phases 3-7, later batches)

- [ ] Phase 3: PowerShell Bridge (`PowerShellSearchBridge`) — **note**: tasks.md's
  Phase 3 section changed underneath this batch (now specifies `-File <script>`
  + stdin JSON + LIKE-metacharacter escaping + hostile-input tests, superseding
  the design.md text this batch read, which described `-EncodedCommand`). This
  is expected per the orchestrator's note that specs/powershell-search-bridge is
  being amended concurrently — Phase 3's implementer should re-read the current
  `specs/powershell-search-bridge/spec.md` and `tasks.md`, not this doc's
  earlier design.md snapshot.
- [ ] Phase 4: Fallback Composing Adapter (`FallbackSearchAdapter`)
- [ ] Phase 5: Tool Layer Rewrite (dispatch split, combined-query intersection,
  `os.stat`-based `file_get_info`) — **must** wire `file_search()`/the
  `server.py` tool to actually return `FileSearchResponse` (see Deviation 1),
  and must call `tools.file_search_walk.walk_filename()` with
  `tools.settings.file_search_walk_time_budget_seconds()`/`file_search_walk_max_dirs()`
  as `time_budget_s`/`max_dirs`.
- [ ] Phase 6: Server Wiring (`_resolve_real_file_search_adapter()` →
  `FallbackSearchAdapter`)
- [ ] Phase 7: Verification (smoke test / no-forensic-code checks / integration test)
- [ ] 8.1 Final full-suite green check (already green as of this batch —
  re-verify after Phases 3-7 land)

## Status (superseded by Batch 2 below for overall progress)

10/8.1 tasks complete for Batch 1's scope (1.1-1.6, 2.1-2.7 = 13 checklist
items). Ready for Batch 2 (Phase 3-4) or Phase 5, once the PowerShell-bridge
spec/tasks amendment (noted above) has settled.

## Batch 2 (Phases 3-4) — PowerShell bridge (security-critical) + fallback composing adapter

**Mode**: Strict TDD. Test runner: `.venv/bin/python3.12 -m pytest -q`.

**Baseline going in**: full suite `359 passed` (sibling's search-result-caps
work had landed further since Batch 1's snapshot; unrelated to this batch).

**Amended spec read first, as instructed**: `specs/powershell-search-bridge/spec.md`
had changed since Batch 1's handoff note (now specifies `-File` + stdin
JSON + `LIKE`-metacharacter escaping + hostile-input tests, not
`-EncodedCommand`) — read the current version, not design.md's Batch-1
snapshot, per the orchestrator's instruction.

**Mid-batch orchestrator refinement (live security review), addressed
before completion**: after an initial implementation where the `.ps1`
script escaped/interpolated `filename`/`phrase`/`path` fields itself from
a `{"mode": ..., "filename": ..., ...}` stdin payload, the orchestrator
requested three changes, all applied:
1. **Escape in exactly one place**: refactored so Python builds the
   COMPLETE SQL text (via `_build_search_sql`/`_build_get_info_sql` —
   the exact same functions `WindowsSearchAdapter` already used) and
   sends it as `{"sql": "<text>"}`; the `.ps1` became a dumb executor
   that runs `.sql` verbatim via `OleDbCommand.CommandText`, with no
   escaping of its own. This also fixed a latent gap in the *existing*
   ADO adapter: `_build_search_sql`'s filename clause previously only
   quote-doubled (`_escape_sql`), never neutralized `LIKE` metacharacters
   — now both transports share a new `_escape_like_value` helper
   (`_escape_sql` composed with `_escape_like_metacharacters`) for the
   `filename LIKE` clause specifically.
2. **Table-driven escaper test**: added
   `test_escape_like_value_table` (parametrized: `o'brien`, `100%`,
   `a_b`, `[abc]`, `it''s`, a lone backslash, empty string, a 1000-char
   string, a metacharacters-only string) asserting the exact escaped SQL
   literal for each, plus `test_bridge_search_sql_reuses_build_search_sql_with_like_escaped_filename`
   proving the bridge's stdin `sql` is byte-for-byte identical to what
   `_build_search_sql` produces standalone (one code path, not two).
3. **Spawn-blocked vs timeout messaging**: `PowerShellSearchBridge._invoke()`
   now catches `subprocess.TimeoutExpired` and plain `OSError` separately,
   raising `WindowsSearchUnavailableError` with "...timed out" vs
   "PowerShell bridge blocked or unavailable: ..." respectively — same
   error TYPE, distinguishable message. New test
   `test_bridge_search_spawn_blocked_maps_to_distinctly_worded_unavailable_error`.

`design.md`, `specs/powershell-search-bridge/spec.md`, and `tasks.md`
were updated minimally to match (SQL-building-in-Python decision text,
new/revised requirement scenarios, task 3.4/3.11 wording, new task 3.7b).

### TDD Cycle Evidence

| Task | Test File | Layer | Safety Net | RED | GREEN | TRIANGULATE | REFACTOR |
|------|-----------|-------|------------|-----|-------|-------------|----------|
| 3.1-3.3 | `tests/test_file_search_adapter.py` | Unit | ✅ 17/17 pre-existing | ✅ Written (ImportError confirmed — `PowerShellSearchBridge` didn't exist) | ✅ Passed | ✅ argv-exact, values-absent-from-argv, stdin-present cases | ✅ Refactored once mid-batch (see above) |
| 3.4 | same | Unit | — | ✅ Written (helper didn't exist) | ✅ Passed | ✅ 9-case parametrized table + bridge-reuses-builder case | ➖ None needed |
| 3.5-3.6 | same | Unit | — | ✅ Written | ✅ Passed | ✅ single-quote filename + `$(Get-Date)` phrase, both via mocked subprocess | ➖ None needed |
| 3.7-3.9 (+3.7b) | same | Unit | — | ✅ Written | ✅ Passed | ✅ timeout / spawn-blocked / nonzero-exit / malformed-JSON — 4 distinct failure modes | ➖ None needed |
| 3.10 | same | Unit | — | ✅ Written | ✅ Passed | ✅ array + single-row-collapsed-to-object + get_info detail cases | ➖ None needed |
| 3.11 | `tools/ps_bridge_search.ps1` (new) | N/A (not unit-tested directly — no real PowerShell on WSL2) | N/A (new file) | N/A | N/A | N/A | N/A — covered indirectly per tasks.md 3.11; balanced-braces/parens sanity-checked only |
| 4.1-4.4 | `tests/test_file_search_adapter.py` | Unit | ✅ (Phase 3 tests still passing) | ✅ Written (ImportError confirmed — `FallbackSearchAdapter` didn't exist) | ✅ Passed | ✅ search+get_info pairs for skip/fallthrough/both-fail, plus `FileNotFoundInIndexError`-never-triggers-bridge triangulation, plus default-construction wiring | ➖ None needed |

### Test Summary
- **Total tests written this batch**: 34 net new in `tests/test_file_search_adapter.py`
  (file now collects 51 tests total: 17 pre-existing WindowsSearchAdapter
  tests + 34 new Phase 3/4 tests, the latter including the escaper
  table's 9 parametrized cases)
- **Total tests passing**: 415/415 (full suite). This batch's own file
  went from 17→51 (+34); the suite-wide baseline going in was 359 (see
  above) and the suite now totals 415 (+56) — the extra +22 beyond this
  batch's own +34 is the sibling's concurrently-landed
  search-result-caps work, not this batch's
- **Layers used**: Unit (all)
- **Approval tests** (refactoring): `_build_search_sql`'s pre-existing
  17 WindowsSearchAdapter tests served as the approval/safety-net suite
  while extending its `filename` clause to also call
  `_escape_like_value` instead of bare `_escape_sql` — all 17 still pass
  unchanged since none of their fixture filenames contain `%`/`_`/`[`.
- **Pure functions created**: `_escape_like_metacharacters`,
  `_escape_like_value`, `_row_from_mapping` (pure given a dict row)

## Files Changed (Batch 2)

| File | Action | What Was Done |
|------|--------|----------------|
| `tests/test_file_search_adapter.py` | Modified | Added Phase 3 (`PowerShellSearchBridge`, 51 total incl. pre-existing 17) and Phase 4 (`FallbackSearchAdapter`, `_StubPort` fixture) test sections |
| `tools/file_search_adapter.py` | Modified | Added `_escape_like_metacharacters`, `_escape_like_value` (extended `_build_search_sql`'s filename clause to use it — fixes a latent LIKE-metacharacter gap in the existing ADO adapter too), `_row_from_mapping`, `PowerShellSearchBridge`, `FallbackSearchAdapter`; new imports `json`, `subprocess`, `pathlib.Path`, `tools.settings.file_search_ps_bridge_timeout_seconds` |
| `tools/ps_bridge_search.ps1` | Created | Dumb-executor script: reads stdin JSON's `sql` field, runs it verbatim via `System.Data.OleDb.OleDbConnection`/`OleDbCommand`, prints row objects as JSON (ISO-8601 dates via `.ToString("o")`), handles get_info's extra `DateCreated`/`AutoSummary` columns conditionally by reader field-name presence |
| `openspec/changes/file-search-resilience/design.md` | Modified | Rewrote the PS-bridge decision to reflect Python-builds-SQL/dumb-executor design + spawn-blocked-vs-timeout messaging |
| `openspec/changes/file-search-resilience/specs/powershell-search-bridge/spec.md` | Modified | Updated "Subprocess Transport", "Values Passed as Data via Stdin", "SQL Value Escaping" (added escaper-table scenario), "Timeout and Failure Mapping" (added spawn-blocked scenario) requirements to match |
| `openspec/changes/file-search-resilience/tasks.md` | Modified | Checked off 3.1-3.11 (revised wording for 3.4/3.11), 4.1-4.4; added task 3.7b |

## Deviations from Design (Batch 2)

1. **`_build_search_sql`'s filename escaping was extended, not just
   reused.** The pre-existing (Batch 1-era, actually pre-dating this
   change entirely) `_build_search_sql` only quote-doubled `filename`
   via `_escape_sql` — never neutralized `LIKE` metacharacters. This was
   a real, silent gap in the ADO adapter (a filename like `100%` would
   have matched far more broadly than intended, or `[report]` would have
   been treated as a character-class). Fixing it was necessary to give
   the bridge and the ADO adapter one shared escaping code path (the
   orchestrator's explicit ask) — so this batch's change also
   strengthens `WindowsSearchAdapter.search()`'s own filename matching,
   beyond Phase 3/4's PowerShell-only scope. All 17 pre-existing
   `WindowsSearchAdapter` tests still pass unchanged (none of their
   fixture filenames contain a LIKE metacharacter), so this is verified
   as behavior-preserving for every previously-tested case while fixing
   the untested gap.
2. **`PowerShellSearchBridge.get_info()` raises `FileNotFoundInIndexError`
   directly on an empty row list**, mirroring `WindowsSearchAdapter.get_info()`'s
   own contract exactly (both satisfy the same `FileSearchPort.get_info()`
   docstring) — not spec'd verbatim anywhere but the only sensible choice
   given the Protocol both must satisfy identically for `FallbackSearchAdapter`
   to compose them.
3. **The "Both-Transports-Exhausted Messaging" requirement in
   `specs/powershell-search-bridge/spec.md`** (the raised error's message
   must state filename search still works) is NOT implemented in
   `FallbackSearchAdapter` (Phase 4) — per `windows-search-adapter/spec.md`'s
   own "Fallback Transport Ordering" requirement ("this seam stays
   config- and message-neutral... the tool layer... is responsible for
   adding the filename-still-works messaging") AND tasks.md's task 4.3
   ("propagates unchanged") AND task 5.3 ("phrase-only both-transports-fail
   message states filename search still works" — explicitly a Phase 5
   task). The two specs read as contradictory on WHERE this messaging
   belongs; I followed tasks.md (my authoritative work order for this
   batch) and the windows-search-adapter spec, both of which are
   internally consistent with each other and with Phase 5's task list.
   **Whoever implements Phase 5 must add this messaging in
   `tools/file_search.py`'s tool layer** when both transports raise
   `WindowsSearchUnavailableError` for a `phrase` query — do not assume
   it is already handled by `FallbackSearchAdapter`.
4. **`_row_from_mapping`'s date fields are passed through as raw
   strings/values to pydantic**, relying on pydantic v2's native
   ISO-8601 `datetime` coercion rather than manual `datetime.fromisoformat()`
   parsing in Python — simpler, and the `.ps1` script formats dates via
   `.ToString("o")` specifically to hand pydantic a format it accepts
   directly.

## Issues Found (Batch 2)

None beyond the mid-batch design refinement (addressed above, not a
latent bug — it was an improvement requested during implementation,
applied before this batch's completion).

## Remaining Tasks (Phases 5-7, later batches)

- [ ] Phase 5: Tool Layer Rewrite (dispatch split, combined-query
  intersection, `os.stat`-based `file_get_info`) — must wire
  `file_search()`/`server.py`'s tool to return `FileSearchResponse`
  (Batch 1's deviation note), call `tools.file_search_walk.walk_filename()`,
  AND (per this batch's deviation #3) add the "filename search still
  works" messaging when both `FallbackSearchAdapter` transports are
  exhausted for a `phrase` query — `FallbackSearchAdapter` currently
  propagates `WindowsSearchUnavailableError` UNCHANGED (no such text),
  by design; Phase 5's tool layer must add it, not assume it's already
  there.
- [ ] Phase 6: Server Wiring (`_resolve_real_file_search_adapter()` →
  `FallbackSearchAdapter` — the class now exists and is ready to
  construct with its zero-arg default constructor, which wires the real
  `WindowsSearchAdapter` + `PowerShellSearchBridge` automatically).
- [ ] Phase 7: Verification (smoke test / no-forensic-code checks /
  integration test).
- [ ] 8.1 Final full-suite green check — **this batch's own diff is
  fully green** (`tests/test_file_search_adapter.py`: 51/51 passed,
  isolated run). The full suite at completion shows 2 FAILED
  (`test_server.py::test_mail_search_tool_returns_results_via_fake_mail_adapter`,
  `test_server.py::test_mail_search_tool_folder_path_returns_results_via_fake_mail_adapter`)
  plus 417 passed — both failures are the sibling's concurrently-landing
  search-result-caps work (a `resultsTruncated`/`results` envelope change
  to mail search's response shape, touching `tools/mail.py`/`server.py`,
  files this batch was explicitly told not to touch) caught mid-edit,
  not caused by anything in this batch's diff (`tools/file_search_adapter.py`,
  its test file, the new `.ps1` asset, and this change's own openspec
  artifacts). Re-verify the full suite once the sibling's batch lands,
  and again after Phases 5-7 land.

## Status (superseded by Batch 3 below for overall progress)

24/8.1 tasks complete overall (1.1-1.6, 2.1-2.7, 3.1-3.11 incl. 3.7b,
4.1-4.4 = 25 checklist items across Batches 1-2). Ready for Batch 3
(Phase 5), and Phase 6 can follow immediately after since
`FallbackSearchAdapter()` with no arguments already does the right
thing.

## Batch 3 (Phases 5-7 + Final) — Tool layer rewrite, server wiring, verification

**Mode**: Strict TDD. Test runner: `.venv/bin/python3.12 -m pytest -q`.

**Baseline going in**: full suite `434 passed, 0 failed` (both sibling
changes — outlook-date-locale-fix and search-result-caps — had landed;
search tools already returned envelope models with `resultsTruncated`).

### TDD Cycle Evidence

| Task | Test File | Layer | Safety Net | RED | GREEN | TRIANGULATE | REFACTOR |
|------|-----------|-------|------------|-----|-------|-------------|----------|
| 5.1-5.2 | `tests/test_file_search_tools.py` | Unit | ✅ 12/12 dispatch-agnostic tests pre-existing (mandatory-filter/roots) still pass | ✅ Written (`walk_filename` not yet called from `file_search`, adapter still touched) | ✅ Passed | ✅ unavailable-adapter-never-called + unindexed-scope-via-mocked-walk cases | ➖ None needed |
| 5.3 | same | Unit | — | ✅ Written | ✅ Passed | ✅ exact "filename search still works" substring match | ➖ None needed |
| 5.4-5.6 | same | Unit | — | ✅ Written | ✅ Passed | ✅ intersect / short-circuit-no-adapter-call / propagate-with-hint cases | ➖ None needed |
| 5.7-5.9 | same | Unit | — | ✅ Written (mocked `os.stat`) | ✅ Passed | ✅ nonexistent / real-unindexed / real-indexed cases, plus an extra "index unavailable during enrichment" triangulation case | ➖ None needed |
| 5.10 | `tools/file_search.py` | GREEN target | — | — | ✅ dispatch split + combined-intersection + `os.stat`-first `file_get_info` | — | ✅ extracted `_walk`/`_search_filename_only`/`_search_phrase_only`/`_search_combined`/`_raise_unavailable_with_filename_hint`/`_resolve_native_path`/`_name_from_native_path` helpers |
| 6.1 | `tests/test_server.py` | Integration | ✅ pre-existing file_search/file_get_info server tests (4 of them) had to be UPDATED, not just added-to — see Deviations | ✅ Written (real `os.stat` on this host already raises `FileNotFoundError` for the synthetic path — no mock needed for RED) | ✅ Passed | — | ➖ None needed |
| 6.2 | `server.py` | GREEN target | — | — | ✅ `_resolve_real_file_search_adapter()` now constructs `FallbackSearchAdapter()`; confirmed `_map_error` needed no change (generic `CalendarToolError`/`.code` handling already covers `path_not_found`) | — | ➖ None needed |
| 7.1-7.2 | (verification only) | — | — | — | ✅ confirmed, no edit made | — | — |
| 7.3 | `tests/test_server.py` | Integration | — | ✅ Written (new test, real `tmp_path` tree + a fake adapter that raises `AssertionError` if ever called) | ✅ Passed | — | ➖ None needed |

### Test Summary
- **Total tests written/rewritten this batch**: 26 in `tests/test_file_search_tools.py`
  (full rewrite: 12 dispatch-agnostic tests carried over unchanged in spirit +
  14 new Phase-5-specific tests) + 1 new test in `tests/test_server.py`
  (task 7.3) + 4 pre-existing `tests/test_server.py` tests updated in place
  (not counted as "new", see Deviations) for the new dispatch/envelope/
  `os.stat`-first behavior.
- **Total tests passing**: 443/443 (full suite, exact line: `443 passed in 2.65s`).
- **Layers used**: Unit (`test_file_search_tools.py`), Integration
  (`test_server.py`, via FastMCP's in-process `Client`).
- **Approval tests** (refactoring): the 12 dispatch-agnostic tests in
  `test_file_search_tools.py` (mandatory-filter, roots-containment,
  default-roots-resolution) served as the safety net proving the roots/
  validation layering is unchanged by the Phase 5 rewrite underneath it.
- **Pure functions created**: `_raise_unavailable_with_filename_hint`
  (always raises — a control-flow helper, not pure, but isolated for
  reuse across the 2 call sites), `_walk` (thin wrapper over
  `walk_filename` + the two settings readers), `_resolve_native_path`,
  `_name_from_native_path` (both pure given their string input).

### Files Changed (Batch 3)

| File | Action | What Was Done |
|------|--------|----------------|
| `tools/file_search.py` | Modified | Implemented the Phase 5 dispatch split (`_search_filename_only`/`_search_phrase_only`/`_search_combined`), wired `FileSearchResponse` as `file_search()`'s return type, added the "filename search still works" message augmentation (`_raise_unavailable_with_filename_hint`), and rewrote `file_get_info` to be `os.stat`-first with index enrichment (`kind`/`snippet`) swallowed on any failure |
| `tests/test_file_search_tools.py` | Rewritten | Full rewrite covering tasks 5.1-5.9 plus the still-valid dispatch-agnostic Phase-4 scenarios (mandatory filter, roots containment, default-roots resolution) adapted to call through the new dispatch (mocked `walk_filename` for filename-only paths, `phrase=` for adapter-routed paths, mocked `os.stat` for `file_get_info`) |
| `server.py` | Modified | `_resolve_real_file_search_adapter()` now constructs `FallbackSearchAdapter()` instead of a bare `WindowsSearchAdapter()`; `_file_search` tool's return-type annotation changed `list[FileSummary]` → `FileSearchResponse`; import list updated accordingly |
| `tests/test_server.py` | Modified | Updated 4 pre-existing file_search/file_get_info tests whose assumptions the new dispatch/envelope broke (see Deviations below); added 1 new test for task 7.3 |
| `openspec/changes/file-search-resilience/tasks.md` | Modified | Checked off 5.1-5.10, 6.1-6.2, 7.1-7.3, 8.1 |

## Deviations from Design (Batch 3)

1. **Four pre-existing `tests/test_server.py` tests had to be UPDATED, not
   just left alone, because Phase 5's dispatch split changed their
   underlying assumptions — this goes beyond "add new tests for new
   tasks":
   - `test_file_search_tool_returns_results_via_fake_file_search_adapter`
     used a `filename` query against an injected `FakeFileSearchAdapter`;
     under the new dispatch a `filename`-only query never touches the
     adapter at all (it goes straight to the real filesystem walk, which
     would find nothing for a synthetic Windows path on this Linux test
     host). Changed the query to `phrase` so the test still exercises the
     injected adapter end-to-end, and updated the assertion to the
     `FileSearchResponse` envelope shape (`result.data.results[0]`, not
     `result.data[0]`).
   - `test_file_get_info_tool_returns_detail_via_fake_file_search_adapter`
     needed a mocked `os.stat` added (Phase 5 sources core facts from
     `os.stat`, never the index — a synthetic Windows path has no real
     stat on this host).
   - `test_file_get_info_tool_unknown_path_surfaces_file_not_found_in_index_error`
     tested behavior the file-get-info spec's REMOVED "File Not Found In
     Index" requirement explicitly retired: a nonexistent path now raises
     `PathNotFoundError`/`path_not_found`, never
     `FileNotFoundInIndexError`/`file_not_found_in_index`, since existence
     is an `os.stat` check now, not an index lookup. Replaced with
     `test_file_get_info_tool_nonexistent_path_surfaces_path_not_found_error`
     (this IS task 6.1's RED test) — no `os.stat` mock needed since the
     synthetic path genuinely doesn't exist on this host, so the real
     `os.stat` call already raises `FileNotFoundError` on its own.
   - `test_file_search_adapter_selection_deferred_when_win32com_unavailable`
     used `filename="x"` to prove a `file_search` call fails cleanly (not
     an import-time crash) when win32com is unavailable — but a
     `filename`-only query no longer reaches win32com at all (it would
     silently succeed with 0 results via the walk, since `os.scandir` on
     a nonexistent Windows-style path on Linux raises `OSError`, which the
     walk skips silently rather than propagating). Changed the query to
     `phrase="x"` so the call actually reaches the real
     `FallbackSearchAdapter` → `WindowsSearchAdapter` → win32com import
     chain and still fails as the test intends.

   All four changes are direct, spec-driven consequences of Phase 5's
   dispatch split and the file-get-info spec's REMOVED requirement — not
   scope creep — but are flagged here since "the design was incomplete
   without them" is exactly the kind of thing this section exists to
   surface.

2. **`file_get_info`'s `os.stat` failure is caught as a broad `except
   OSError`**, not narrowly `except FileNotFoundError` — the file-get-info
   spec's scenario only mocks `FileNotFoundError`, but `NotADirectoryError`/
   a generic `OSError` (e.g. an invalid path shape) reaching `os.stat` are
   just as much "this path does not resolve to an existing file or
   directory on disk" as a plain not-found, and there is no other defined
   error path for a stat failure at this point (before any index call).
   Narrowing to only `FileNotFoundError` would let those other cases crash
   as unhandled `OSError`s instead of the intended typed
   `path_not_found` error.

3. **`FileDetail.path` for `file_get_info` is now the `os.stat`-resolved,
   `file:///`-decoded NATIVE path** (`_resolve_native_path(request.path)`),
   not the adapter's own normalized path as in the pre-Phase-5
   implementation. This matches the file-get-info spec's MODIFIED "Get
   Info Output Shape" wording verbatim ("all sourced from `os.stat` on the
   resolved path") — not a deviation from spec, but flagged since it IS a
   behavior change from the pre-Batch-3 code for a `file:///`-URL input
   (previously the *adapter's* decoded path would have been echoed back;
   now this module's own decode is used, before the adapter is ever
   consulted for enrichment).

4. **`deploy/smoke_test.py` was NOT modified** (task 7.1, confirmed
   verification-only) despite a latent, PRE-EXISTING gap noticed while
   reviewing it: `_extract_list_result()` only recognizes a
   `structuredContent` shaped `{"result": [...]}` (singular key) or a
   bare JSON list in the text block — neither matches the ACTUAL
   structuredContent shape FastMCP produces for an enveloped Pydantic
   return type like `FileSearchResponse`/`CalendarSearchResult`/etc
   (`{"results": [...], "resultsTruncated": ...}`, plural key, object not
   list). This means the live smoke test's tolerant "0+ hits is fine"
   checks (for `calendar`/`tasks`/`mail-*`/`files` families alike) always
   fall through to the 0-hits branch in practice, even when the live
   server actually returned hits — masking a real result but never
   causing a false FAIL, since 0 hits is already a PASS for every family.
   This predates this batch entirely (the search-result-caps sibling
   change already wrapped calendar/mail/task in the same envelope shape
   without updating `smoke_test.py`), is not something file-search-
   resilience introduced, and Phase 7 explicitly scopes this task as
   verification-only ("no code expected") — so it is reported here as a
   non-blocking observation for a future change, not fixed in this batch.
   `tests/test_smoke_test.py`'s own unit tests are unaffected (they stub
   `structuredContent` directly with the old `{"result": [...]}` shape,
   so they never exercised the real mismatch either way) and still pass
   unmodified, confirming task 7.1's "still pass unmodified" literally.

5. **The "filename search still works" hint text is this batch's own
   wording** (`_FILENAME_STILL_WORKS_HINT` in `tools/file_search.py`:
   "filename search still works — retry the same call with only
   'filename' set (omit 'phrase')."), appended via
   `_raise_unavailable_with_filename_hint()` to WHATEVER message the
   exhausted adapter/bridge already raised. Neither the file-search spec
   nor the powershell-search-bridge spec pins exact wording, only that the
   message must state the fact — this satisfies that literally. Applied
   uniformly to both the phrase-only leg and the combined-query leg (the
   file-search spec's combined-query rule explicitly calls for the "same
   `WindowsSearchUnavailableError` (filename-still-works message)" on
   index-leg exhaustion there too).

## Issues Found (Batch 3)

None beyond the pre-existing `deploy/smoke_test.py` observation in
Deviation 4 above (not a regression introduced by this batch, not fixed
in this batch per Phase 7's verification-only scope).

## Status

**All tasks complete**: 1.1-1.6, 2.1-2.7, 3.1-3.11 incl. 3.7b, 4.1-4.4,
5.1-5.10, 6.1-6.2, 7.1-7.3, 8.1 — every checklist item in `tasks.md` is
now `[x]`. Full suite: `443 passed in 2.65s` (exact line from this
batch's final run). Change is ready for `/sdd-verify`.
