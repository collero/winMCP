# Apply Progress: Search Result Caps (BUG-002)

**Mode**: Strict TDD (RED-GREEN-REFACTOR enforced throughout)
**Status**: All 22 tasks complete (0.1, 1.1-1.5, 2.1-2.9, 3.1-3.3, 4.1-4.6, 5.1-5.2, 6.1-6.3)

## Phase 0: Sequencing Check

Confirmed by reading `tools/mail_adapter.py`/`tools/outlook_adapter.py` directly
(no git repo present in this environment, so `git status`/`git diff` were not
available — read-based confirmation substituted): the sibling
`outlook-date-locale-fix` change has already landed. `_dasl_datetime()` in
both files already emits the ISO-ordered `%Y-%m-%d %H:%M` literal, and
`OutlookMailAdapter.search()`/`OutlookCalendarAdapter.search()` already carry
the Python-side boundary re-check comments referencing that fix. This
change's edits (Sort() descending argument, iteration/early-stop loop,
limit/results_truncated bookkeeping) were made surgically around those
existing statements — the date-string construction itself was never touched.

## TDD Cycle Evidence

| Task | Test File | Layer | Safety Net | RED | GREEN | TRIANGULATE | REFACTOR |
|------|-----------|-------|------------|-----|-------|-------------|----------|
| 1.1/1.2 | `tests/test_settings.py` | Unit | N/A (new fn) | ✅ Written (ImportError) | ✅ 20/20 passed | ✅ 8 cases (default/configured/under-max/clamp-default/clamp-configured/reject-zero/reject-negative/both-keys) | ✅ Clean |
| 1.3 | `config/settings.yaml` | Config | N/A | — | — | ➖ Structural (docs-only, optional keys) | ➖ None needed |
| 1.4/1.5 | `tests/test_schemas.py` | Unit | ✅ 66/66 (pre-change baseline for the file) | ✅ Written (ImportError) | ✅ 66/66 passed | ✅ 6 request-limit cases + 6 envelope cases | ✅ Clean |
| 2.1/2.2 | `tests/test_mail_adapter.py` | Unit | ✅ 34/34 pre-existing | ✅ Written (7 failed) | ✅ 41/41 passed | ✅ 7 cases (Sort args ×3 folders, early-stop, under-limit, folderPath bound+sort, folderPath under-limit) | ✅ Clean |
| 2.3/2.4 | `tests/test_mail_adapter.py` | Unit | (same file/run as above) | ✅ Written | ✅ Passed | ✅ 2 folderPath cases | ✅ Clean |
| 2.5/2.6 | `tests/test_outlook_adapter.py` | Unit | ✅ 18/18 pre-existing (1 assertion updated for descending Sort) | ✅ Written (3 failed) | ✅ 21/21 passed | ✅ 2 cases (early-stop, under-limit) | ✅ Clean |
| 2.7/2.8 | `tests/test_task_adapter.py` | Unit | ✅ 16/16 pre-existing | ✅ Written (2 failed) | ✅ 18/18 passed | ✅ 2 cases (ascending+null-last+bound, null-last-within-limit) — required a bugfix (see Issues) | ✅ Clean |
| 2.9 | `tools/{mail,outlook,task}_adapter.py` Protocols | — | — | — | — | — | ➖ Structural (signature-only) |
| 3.1 | `tests/test_fake_mail_adapter.py` | Unit | ✅ 23/23 pre-existing | ✅ Written (4 failed) | ✅ 27/27 passed | ✅ 4 cases | ✅ Clean |
| 3.2 | `tests/test_fake_adapter.py` | Unit | ✅ 6/6 pre-existing | ✅ Written (3 failed) | ✅ 9/9 passed | ✅ 3 cases | ✅ Clean |
| 3.3 | `tests/test_fake_task_adapter.py` | Unit | ✅ 11/11 pre-existing | ✅ Written (4 failed) | ✅ 15/15 passed | ✅ 4 cases | ✅ Clean |
| 4.1/4.2 | `tests/test_mail_tools.py` | Unit | ✅ 15/15 pre-existing (10 updated for envelope shape) | ✅ Written (10 failed) | ✅ 26/26 passed | ✅ 5 new scenario tests (default-bound+flag, clamp, reject, under-cap, out-of-order) | ✅ Clean |
| 4.3/4.4 | `tests/test_calendar_tools.py` | Unit | ✅ 10/10 pre-existing (2 updated) | ✅ Written (5 failed) | ✅ 16/16 passed | ✅ 4 new scenario tests | ✅ Clean |
| 4.5/4.6 | `tests/test_tasks_tools.py` | Unit | ✅ 5/5 pre-existing (8 updated) | ✅ Written (13 failed) | ✅ 18/18 passed | ✅ 6 new scenario tests incl. filterless under/over cap | ✅ Clean |
| 5.1/5.2 | `tests/test_server.py` | Integration (FastMCP in-process Client) | ✅ 25/25 pre-existing (4 updated for envelope shape) | ✅ Written (8 failed) | ✅ 33/33 passed | ✅ 6 new end-to-end limit/truncation/reject tests | ✅ Clean |
| 6.1/6.2 | (spread across the 3 tool test files above) | Unit | — | — | ✅ All 5 required regression families + newest-first/due-date-priority tests present and passing | ✅ | ✅ |
| 6.3 | full suite | — | ✅ 339 passed (baseline) | — | ✅ 434 passed, 0 failed | — | — |

### Test Summary
- **Total new/modified tests**: ~95 (across `test_settings.py`, `test_schemas.py`, `test_mail_adapter.py`, `test_outlook_adapter.py`, `test_task_adapter.py`, `test_fake_mail_adapter.py`, `test_fake_adapter.py`, `test_fake_task_adapter.py`, `test_mail_tools.py`, `test_calendar_tools.py`, `test_tasks_tools.py`, `test_server.py`)
- **Total tests passing (full suite)**: 434 passed, 0 failed
- **Layers used**: Unit (majority), Integration (FastMCP in-process `Client` in `test_server.py`)
- **Approval tests**: None — no refactoring-of-existing-behavior tasks; all changes are additive/extending except the deliberate Sort-direction and return-type changes, which were driven RED-first by updated assertions.
- **Pure functions created**: `resolve_search_limit()` (tools/settings.py) — fully pure given `load_settings()`'s return value.

## Files Changed

| File | Action | What Was Done |
|------|--------|----------------|
| `tools/settings.py` | Modified | Added `resolve_search_limit(limit) -> int` |
| `config/settings.yaml` | Modified | Documented optional `search_default_limit`/`search_max_limit` keys (comments only, no literal keys — defaults live in code) |
| `models/schemas.py` | Modified | Added `_TruncatableResult` mixin; `MailSearchResult`/`CalendarSearchResult`/`TaskSearchResult`; `limit` field on `MailSearchRequest`/`SearchRequest`/`TaskSearchRequest` |
| `tools/mail_adapter.py` | Modified | `MailPort.search()`/`OutlookMailAdapter.search()` gain `limit: int = 200`; mapped-folder path Sorts descending on the folder's DASL field and early-stops at `limit + 1`; `folderPath` path sorts collected matches descending in Python and bounds to `limit + 1` |
| `tools/outlook_adapter.py` | Modified | `CalendarPort.search()`/`OutlookCalendarAdapter.search()` gain `limit: int = 200`; `Sort("[Start]")` changed to `Sort("[Start]", True)` (descending); early-stops at `limit + 1` |
| `tools/task_adapter.py` | Modified | `TaskPort.search()`/`OutlookTaskAdapter.search()` gain `limit: int = 200`; sorts by due date ascending (None last, via `_NO_DUE_DATE_SORT_KEY`) then bounds to `limit + 1` |
| `tools/fake_mail_adapter.py` | Modified | Mirrors real adapter's newest-first + `limit + 1` bounding exactly (both mapped-folder and folder_path paths) |
| `tools/fake_adapter.py` | Modified | Mirrors real calendar adapter's newest-first + `limit + 1` bounding exactly |
| `tools/fake_task_adapter.py` | Modified | Mirrors real task adapter's due-date-ascending (None last) + `limit + 1` bounding exactly |
| `tools/mail.py` | Modified | `mail_search()` now resolves `limit`, slices the adapter's up-to-`limit+1` result to `limit`, returns `MailSearchResult` |
| `tools/calendar.py` | Modified | `calendar_search()` likewise, returns `CalendarSearchResult` |
| `tools/tasks.py` | Modified | `task_search()` likewise, returns `TaskSearchResult` |
| `server.py` | Modified | `_mail_search`/`_calendar_search`/`_task_search` gain a `limit: int \| None = None` parameter and their return-type annotations changed to the 3 envelope models |
| `tests/test_settings.py` | Modified | +8 tests for `resolve_search_limit()` |
| `tests/test_schemas.py` | Modified | +12 tests for `limit` fields + envelope models |
| `tests/test_mail_adapter.py` | Modified | +7 tests for Sort()/early-stop/folderPath bounding |
| `tests/test_outlook_adapter.py` | Modified | +2 tests, 1 assertion updated (descending Sort) |
| `tests/test_task_adapter.py` | Modified | +2 tests for due-date ordering + bounding |
| `tests/test_fake_mail_adapter.py` | Modified | +4 parity tests |
| `tests/test_fake_adapter.py` | Modified | +3 parity tests |
| `tests/test_fake_task_adapter.py` | Modified | +4 parity tests |
| `tests/test_mail_tools.py` | Modified | Envelope-shape assertions updated on 10 existing tests; +6 new scenario tests |
| `tests/test_calendar_tools.py` | Modified | Envelope-shape assertions updated on 2 existing tests; +4 new scenario tests |
| `tests/test_tasks_tools.py` | Modified | Envelope-shape assertions updated on 8 existing tests; +6 new scenario tests |
| `tests/test_server.py` | Modified | Envelope-shape assertions updated on 4 existing tests; +6 new end-to-end tests |

## Deviations from Design

None — implementation matches design.md. One interpretive decision was
required where design.md's Data Flow diagram was ambiguous about which layer
(adapter vs. tool) computes `results_truncated`: I implemented the "+1 peek"
convention uniformly across all four search paths (mail mapped-folder, mail
folderPath, calendar, tasks) — every adapter's `search(..., limit=N)` returns
**up to `N + 1`** rows (via COM-level early-stop where possible, or
sort+slice-to-`N+1` where the match set is already fully materialized), and
the **tool layer** (`mail_search`/`calendar_search`/`task_search`) is the
single place that slices the result down to `N` and sets
`results_truncated = len(adapter_result) > N`. This keeps the `MailPort`/
`CalendarPort`/`TaskPort` Protocol return type unchanged (`list[XSummary]`,
never a tuple or envelope), matches design.md's literal "stops collecting
once `limit + 1` post-filter matches are seen" language, and is consistent
with design.md's statement that only "Tool functions wrap the row list in a
small per-domain envelope" (adapters never construct envelope models).

## Issues Found

One implementation bug caught during Phase 2's task-adapter GREEN step: an
initial `results.sort(key=lambda t: (t.due_date is None, t.due_date))`
raised `TypeError: '<' not supported between instances of 'NoneType' and
'NoneType'` when two undated tasks were compared (Python tuple comparison
still evaluates the second element when first elements are equal). Fixed by
sorting on `task.due_date or _NO_DUE_DATE_SORT_KEY` (a `datetime.max`
sentinel) instead of a tuple — applied identically in both
`tools/task_adapter.py` and `tools/fake_task_adapter.py` for parity. Caught
by the RED test `test_search_no_due_date_tasks_sort_after_all_dated_tasks_within_limit`
before it could reach production.

## Out of Scope (per tasks.md's Deferred note)

`entryId` shortening, X500->SMTP sender resolution, offset/cursor paging —
no tasks exist for these; not touched.

## Known Unrelated Failure (transient, now resolved)

Mid-implementation, a full-suite run surfaced one failure in
`tests/test_file_search_adapter.py::test_bridge_argv_is_exactly_the_pinned_flag_set`
against `tools/file_search_adapter.py` — a file explicitly owned by a
concurrent sibling agent (file-search/ps_bridge work), never touched by this
change. Per the collision-boundary instruction, it was left alone. It had
resolved itself (sibling's own fix landed) by the final full-suite run, which
is clean at 434 passed / 0 failed.

## Final Test Result

```
434 passed in 20.51s
```

(Baseline going in was 339 passed; net +95 from this change's new/extended
tests. No pre-existing test was left broken.)
