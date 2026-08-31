# Tasks: Search Result Caps (BUG-002)

## Phase 0: Sequencing Check

- [x] 0.1 Before touching `tools/mail_adapter.py` or `tools/outlook_adapter.py`, run `git status`/`git diff` on both files to check whether sibling change `outlook-date-locale-fix` has already landed edits to their `search()` bodies. If so, rebase this change's Sort/iteration/limit edits onto those changes rather than overwriting — the two changes touch disjoint statements in the same functions.

## Phase 1: Foundations (config + schemas + shared helper)

- [x] 1.1 RED: add failing tests in `tests/test_settings.py` for `resolve_search_limit()` — default 50 when `limit=None`, clamp to 200 when over max, `ValueError` when `<=0`, and reading `search_default_limit`/`search_max_limit` overrides from a fake `load_settings()`.
- [x] 1.2 GREEN: add `resolve_search_limit(limit: int | None) -> int` to `tools/settings.py` per design.md.
- [x] 1.3 Document `search_default_limit`/`search_max_limit` as optional keys (defaults 50/200) in `config/settings.yaml`.
- [x] 1.4 RED: add failing tests in `tests/test_schemas.py` for `limit` field on `MailSearchRequest`/`SearchRequest`/`TaskSearchRequest`, and for `_TruncatableResult`/`MailSearchResult`/`CalendarSearchResult`/`TaskSearchResult` serialization (aliases, `resultsTruncated`).
- [x] 1.5 GREEN: add the fields/models to `models/schemas.py` per design.md.

## Phase 2: Adapter Layer (limit, ordering, truncation)

- [x] 2.1 RED: extend `tests/test_mail_adapter.py` for mapped folders (inbox/sent/drafts) — descending `Sort()`, early-stop at `limit+1`, `results_truncated` semantics via mocked `win32com.client.Items`.
- [x] 2.2 GREEN: update `OutlookMailAdapter.search()` in `tools/mail_adapter.py` (mapped-folder path) to accept `limit`, sort descending, early-stop, return truncation info; leave `Restrict()` date-string construction untouched.
- [x] 2.3 RED: extend `tests/test_mail_adapter.py` for the `folderPath` path — full scan (unchanged cost), sort by resolved date descending, slice to `limit`.
- [x] 2.4 GREEN: implement the `folderPath` sort+slice in the same `search()`.
- [x] 2.5 RED: extend `tests/test_outlook_adapter.py` — `Sort("[Start]", True)` descending (was ascending), early-stop at `limit+1`, truncation.
- [x] 2.6 GREEN: update `OutlookCalendarAdapter.search()` in `tools/outlook_adapter.py` accordingly; leave `Restrict()` untouched.
- [x] 2.7 RED: extend `tests/test_task_adapter.py` — collect-all (unchanged), sort by `(due_date is None, due_date)` ascending, slice to `limit`, truncation.
- [x] 2.8 GREEN: update `OutlookTaskAdapter.search()` in `tools/task_adapter.py` accordingly.
- [x] 2.9 Update the `MailPort`/`CalendarPort`/`TaskPort` Protocol `search()` signatures to include `limit`.

## Phase 3: Fake Adapters (parity for Strict TDD)

- [x] 3.1 RED+GREEN together: update `tests/test_fake_mail_adapter.py` and `tools/fake_mail_adapter.py` to mirror limit/order/truncation exactly.
- [x] 3.2 RED+GREEN: update `tests/test_fake_adapter.py` and `tools/fake_adapter.py` (calendar) likewise.
- [x] 3.3 RED+GREEN: update `tests/test_fake_task_adapter.py` and `tools/fake_task_adapter.py` likewise.

## Phase 4: Tool Layer

- [x] 4.1 RED: extend `tests/test_mail_tools.py` for `resolve_search_limit()` call + `MailSearchResult` wrapping in `mail_search`.
- [x] 4.2 GREEN: update `tools/mail.py::mail_search`.
- [x] 4.3 RED: extend `tests/test_calendar_tools.py` likewise for `calendar_search`.
- [x] 4.4 GREEN: update `tools/calendar.py::calendar_search`.
- [x] 4.5 RED: extend `tests/test_tasks_tools.py` likewise for `task_search`, including the "filterless call under/over cap" scenarios.
- [x] 4.6 GREEN: update `tools/tasks.py::task_search`.

## Phase 5: MCP Server Wiring

- [x] 5.1 RED: extend `tests/test_server.py` for the 3 `@app.tool` functions — new `limit` param, return-type annotation changed to the envelope models.
- [x] 5.2 GREEN: update `server.py`'s `_mail_search`, `_calendar_search`, `_task_search` registrations.

## Phase 6: Regression Suite & Full Verification

- [x] 6.1 Add the 5 required regression tests end-to-end (tool+adapter combined, fakes only): oversized `subject="a"` mail search bounded+truncated; 3-month calendar window bounded; `task_search{}` returns all-under-cap / bounded-over-cap; `limit=10000` clamped not rejected (mail/calendar/task); `limit=0` rejected (mail/calendar/task).
- [x] 6.2 Add newest-first / due-date-priority ordering regression tests across all three domains (out-of-order seed data).
- [x] 6.3 Run `python3.12 -m pytest -q`; fix any fallout in unrelated tests caused by the envelope-return change.

Deferred (explicitly out of scope, no tasks here): `entryId` shortening, X500→SMTP sender resolution, offset/cursor paging.
