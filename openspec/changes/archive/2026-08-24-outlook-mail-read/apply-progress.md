# Apply Progress: outlook-mail-read

## Batch 1 of 4 — Phases 1 and 2 (COMPLETE)

Mode: **Strict TDD** (test runner: `.venv/bin/python3.12 -m pytest -q`).

### Completed Tasks

- [x] 1.1 RED `tests/test_schemas.py`: `MailFolder` enum (`inbox`/`sent`); `MessageSummary` aliases `entryId`/`hasAttachments`, has `senderAddress`; `MessageDetail(MessageSummary)` adds `body`+`to`
- [x] 1.2 GREEN `models/schemas.py`: added `MailFolder` (str-enum), `MessageSummary`, `MessageDetail(MessageSummary)`, `MailSearchRequest`, `GetMessageRequest`
- [x] 1.3 RED `tests/test_errors.py`: `MessageNotFoundError(CalendarToolError)` exists, carries `code = "message_not_found"`
- [x] 1.4 GREEN `tools/errors.py`: added `MessageNotFoundError` (reused `OutlookUnavailableError` as-is, no changes)
- [x] 2.1 RED `tests/test_fake_mail_adapter.py`: per-folder dispatch (inbox vs sent seeded independently); date-bounds/subject/sender filter sequence; sender filter asymmetry (inbox matches `SenderName`/`SenderEmailAddress`, sent matches `To`); `get_message()` returns a match from either folder or raises `MessageNotFoundError`; configurable `OutlookUnavailableError` for both methods
- [x] 2.2 GREEN `tools/mail_adapter.py`: defined `MailPort` Protocol (`search(folder, date_from, date_to, subject, sender)`, `get_message(entry_id)`)
- [x] 2.3 GREEN `tools/fake_mail_adapter.py`: `FakeMailAdapter` implementing `MailPort`, in-memory per-folder (`inbox`/`sent`) seed via constructor, filter sequence (date bounds → subject → sender)

### Files Created / Modified

| File | Action | What Was Done |
|------|--------|----------------|
| `models/schemas.py` | Modified (additive) | Added `MailFolder`, `MessageSummary`, `MessageDetail`, `MailSearchRequest`, `GetMessageRequest`. No changes to existing `EventSummary`/`EventDetail`/`TaskSummary`/etc. |
| `tools/errors.py` | Modified (additive) | Added `MessageNotFoundError(CalendarToolError)`, `code = "message_not_found"`. No changes to existing errors. |
| `tools/mail_adapter.py` | Created | `MailPort` Protocol only — mirrors `tools/task_adapter.py::TaskPort`/`tools/outlook_adapter.py::CalendarPort`. The real, win32com-backed `OutlookMailAdapter` is Phase 5, out of scope for this batch — this file has zero `win32com` references outside docstring prose. |
| `tools/fake_mail_adapter.py` | Created | `FakeMailAdapter` — mirrors `tools/fake_task_adapter.py::FakeTaskAdapter`; implements the date-bounds → subject → sender filter sequence, with folder-relative sender matching (haystack = `sender`+`sender_address` for inbox, `to` list for sent). |
| `tests/test_schemas.py` | Modified (additive) | Added 5 tests for `MailFolder`/`MessageSummary`/`MessageDetail`. |
| `tests/test_errors.py` | Modified (additive) | Added 3 tests for `MessageNotFoundError`. |
| `tests/test_fake_mail_adapter.py` | Created | 14 tests covering per-folder dispatch, date-bounds filtering, subject substring, sender substring (inbox name+address, sent recipient), summary-shape assertion (no `body`/`to` leak into `MessageSummary`), empty result, `get_message` hit (both folders)/miss, `OutlookUnavailableError` configurability for both methods. |

### TDD Cycle Evidence

| Task | Test File | Layer | Safety Net | RED | GREEN | TRIANGULATE | REFACTOR |
|------|-----------|-------|------------|-----|-------|-------------|----------|
| 1.1/1.2 | `tests/test_schemas.py` | Unit | ✅ 25/25 (pre-existing schema tests, run jointly with 1.3/1.4) | ✅ Written — `ImportError: cannot import name 'MailFolder' from 'models.schemas'` | ✅ 25/25 passed after implementation | ✅ 5 cases (enum values, alias construction, snake_case construction, body+to present, body empty/to empty) | ➖ None needed — matches `EventSummary`/`TaskSummary` pattern exactly |
| 1.3/1.4 | `tests/test_errors.py` | Unit | ✅ (joint run with 1.1/1.2, see above) | ✅ Written — `ImportError: cannot import name 'MessageNotFoundError' from 'tools.errors'` | ✅ 25/25 passed (schemas+errors combined) | ✅ 3 cases (carries code, is-a `CalendarToolError`, raisable/catchable) | ➖ None needed |
| 2.1/2.2/2.3 | `tests/test_fake_mail_adapter.py` | Unit | ✅ 96/96 (full suite baseline before this sub-batch, i.e. after 1.1-1.4 landed) | ✅ Written — `ModuleNotFoundError: No module named 'tools.fake_mail_adapter'` | ✅ 14/14 passed after implementation | ✅ 14 cases covering inbox dispatch, sent dispatch, date-bounds narrowing, subject substring, sender-matches-name (inbox), sender-matches-address (inbox), sender-matches-recipient (sent), summary shape (no body/to leak), empty result, get_message hit from inbox, get_message hit from sent, get_message not-found, unavailable for both methods | ➖ None needed — `_matches_sender` extracted as a pure static method from the start (mirroring `FakeTaskAdapter._passes_due_date_filter`'s existing extraction pattern), no separate refactor pass required |

### Test Summary

- **Total tests written this batch**: 22 (5 schema + 3 error + 14 fake-mail-adapter)
- **Total tests passing (full suite)**: 110/110 (baseline was 88/88 — zero regressions)
- **Layers used**: Unit (22)
- **Approval tests** (refactoring): None — no refactoring tasks, all additive
- **Pure functions created**: `FakeMailAdapter._matches_sender` (static, pure)

### Deviations from Design

One documented deviation, both spec-driven and matching this exact codebase's prior precedent (Batch 1 of `outlook-tasks-todo`, which added `TaskSearchRequest`/`GetTaskRequest` the same way): design.md's "Interfaces / Contracts" code sketch for `MessageSummary` omits `sender_address`/`senderAddress` and shows no `MessageDetail` snippet at all. Both the `mail-search` spec ("MUST return … `sender` (display name), `senderAddress` …") and the `mail-get-detail` spec ("MUST return … `senderAddress` … `to` … `body`") — plus tasks.md 1.1's explicit RED-test description — are unambiguous that `senderAddress` (on `MessageSummary`) and `to` (added by `MessageDetail`) are required fields. Implemented per the specs/tasks.md (the more detailed and more authoritative source for this exact question), not per design's abbreviated sketch. No behavior described by design.md's Architecture Decisions table was contradicted — only its illustrative code sample was incomplete.

Everything else matches design.md exactly:
- `MailFolder` enum values (`inbox`/`sent`) match verbatim.
- `MailPort.search()` signature matches verbatim (`folder` required, `date_from`/`date_to`/`subject`/`sender` independently optional); `get_message(entry_id)` matches verbatim.
- `FakeMailAdapter`'s per-folder in-memory store and date-bounds→subject→sender filter sequence match tasks.md 2.1/2.3 and design.md's `mail_search` sequence description verbatim (adapted to the fake's pure-Python filtering, no DASL/COM at this layer).
- Sender filter/field folder-relative asymmetry (inbox: `SenderName`+`SenderEmailAddress`; sent: `To`) implemented exactly as described.
- `MessageNotFoundError(CalendarToolError)` reuses the existing taxonomy per the "Error taxonomy" decision — no new base class, no changes to `CalendarToolError`/`OutlookUnavailableError`/`EventNotFoundError`/`AmbiguousMatchError`/`TaskNotFoundError`.

### Issues Found

None.

### Constraints Honored

- `win32com` was not imported anywhere in this batch's files — `tools/mail_adapter.py` and `tools/fake_mail_adapter.py` contain zero `import win32com` statements (only docstring prose referencing the real adapter planned for Phase 5); confirmed via `grep -rn "win32com" tools/mail_adapter.py tools/fake_mail_adapter.py models/schemas.py tools/errors.py`.
- `models/schemas.py` and `tools/errors.py` changes are purely additive — all pre-existing tests in `tests/test_schemas.py` and `tests/test_errors.py` still pass unchanged.
- No calendar (`tools/calendar.py`, `tools/outlook_adapter.py`, `tools/fake_adapter.py`) or task (`tools/tasks.py`, `tools/task_adapter.py`, `tools/fake_task_adapter.py`) file was touched — mirrored, not modified.
- `server.py` and `make-deploy-package.sh` were not touched (out of scope for this batch per the batch's explicit constraints).
- No `pip install` was run.

### Remaining Tasks (for Batch 2: Phases 3-4)

- [ ] 3.1–3.8 `mail_search` (mail-search spec): at-least-one-filter validation, `mail_lookback_days` bound-fill (mirrors `calendar.py::_normalize_search_bounds`, own settings key, default 90)
- [ ] 4.1–4.4 `mail_get_message` (mail-get-detail spec)

### Status (Cumulative — as of Batch 1)

7/7 subtasks in Phases 1-2 batch scope complete. Full suite green (110/110). Ready for Batch 2 (Phases 3-4).

## Batch 2 of 4 — Phases 3 and 4 (COMPLETE)

Mode: **Strict TDD** (test runner: `.venv/bin/python3.12 -m pytest -q`). Baseline confirmed before starting: **110/110 passed**.

### Completed Tasks

- [x] 3.1 RED `tests/test_mail_tools.py::test_search_valid_folder_and_date_range`
- [x] 3.2 RED `::test_search_all_filters_omitted_raises_value_error`, `::test_search_missing_folder_rejected`
- [x] 3.3 RED `::test_search_subject_only_fills_both_bounds_from_mail_lookback_days_default_90`
- [x] 3.4 RED `::test_search_sender_only_uses_configured_mail_lookback_days_30_not_calendar_lookback_days`
- [x] 3.5 RED `::test_search_only_date_from_given_fills_date_to_with_now`
- [x] 3.6 RED `::test_search_sender_filter_matches_recipient_on_sent_folder`, `::test_search_sender_filter_matches_sender_name_on_inbox_folder`
- [x] 3.7 RED `::test_search_empty_result_returns_empty_list`, `::test_search_outlook_unavailable_returns_tool_error`
- [x] 3.8 GREEN `tools/mail.py`: implemented `mail_search(request, adapter)` — at-least-one-filter `ValueError` (raised before any adapter call), `mail_lookback_days` bound-fill via a mail-specific `_normalize_search_bounds`/`_mail_lookback_days` pair (duplicated from, not shared with, `tools/calendar.py`'s versions — own settings key, default `90`)
- [x] 4.1 RED `tests/test_mail_tools.py::test_get_message_success_returns_full_detail`
- [x] 4.2 RED `::test_get_message_not_found_raises_tool_error`
- [x] 4.3 RED `::test_get_message_empty_body_returns_empty_string`
- [x] 4.4 GREEN `tools/mail.py`: implemented `mail_get_message(request, adapter)` — thin delegate to `adapter.get_message(entry_id)`, letting `MessageNotFoundError`/`OutlookUnavailableError` propagate unchanged

### Files Created / Modified (Batch 2)

| File | Action | What Was Done |
|------|--------|----------------|
| `tools/mail.py` | Created | `mail_search(request, adapter)` + `mail_get_message(request, adapter)`, mirroring `tools/calendar.py`'s structure exactly. `_mail_lookback_days()` reads `config/settings.yaml`'s `mail_lookback_days` key (default `90`) via `tools/settings.py::load_settings()`. `_normalize_search_bounds()` is a mail-specific duplicate of `calendar.py`'s function (three fill cases: both omitted → `[now-lookback, now]`; only `dateFrom` omitted → `[dateTo-lookback, dateTo]`; only `dateTo` omitted → `[dateFrom, now]`). No import of, or reference to, `tools/calendar.py`'s `_normalize_search_bounds`/`_lookback_days` — the two stay independent per design.md's explicit "duplicate, don't share" decision. Zero `win32com` references (grep-confirmed; only docstring prose mentions the real adapter). |
| `tests/test_mail_tools.py` | Created | 13 tests: `mail_search` — valid folder+date range (asserts adapter called with exact positional/kwarg signature), all-filters-omitted `ValueError` (before adapter call), missing-folder rejected via pydantic `ValidationError` (folder has no default in `MailSearchRequest`, so this is enforced at the schema layer, not inside `mail_search` itself), subject-only fills both bounds from default `90`-day lookback (mocks `tools.mail.load_settings` to return `{}`, confirming the *default*, not the real `config/settings.yaml` value — Phase 7 hasn't added the key yet), sender-only with a mocked `mail_lookback_days: 30` (asserts the span is exactly 30 days, and explicitly asserts it is NOT 7 — calendar's `lookback_days` — to prove no key confusion), only-`dateFrom`-given fills `dateTo` with `now` (asserted via a 5-second tolerance window), sender-filter folder asymmetry (sent→recipient match, inbox→sender-name match), empty result, `OutlookUnavailableError` propagation. `mail_get_message` — success returns full `MessageDetail` (all fields asserted), not-found raises `MessageNotFoundError`, empty body returns `""` without error. |

### TDD Cycle Evidence

| Task | Test File | Layer | Safety Net | RED | GREEN | TRIANGULATE | REFACTOR |
|------|-----------|-------|------------|-----|-------|-------------|----------|
| 3.1-3.8 | `tests/test_mail_tools.py` (mail_search tests) | Unit | ✅ 110/110 (full-suite baseline before this batch) | ✅ Written — `ModuleNotFoundError: No module named 'tools.mail'` (confirmed via a dedicated collection-only run before any implementation existed) | ✅ 13/13 passed after `tools/mail.py` implementation (all mail_search + mail_get_message tests together) | ✅ 8 distinct scenarios exercising the validation branch, all 3 bound-fill cases (both omitted / dateFrom omitted / dateTo omitted), both lookback values (default 90 via mocked empty settings, configured 30 via mocked settings dict), both sender-asymmetry branches, empty-result, and unavailable-error propagation | ➖ None needed — `_normalize_search_bounds`/`_mail_lookback_days` are already minimal pure/near-pure functions mirroring the proven `calendar.py` shape; no duplication or complexity introduced to remove |
| 4.1-4.4 | `tests/test_mail_tools.py` (mail_get_message tests) | Unit | ✅ (joint run with 3.1-3.8, see above) | ✅ Written — same `ModuleNotFoundError` collection failure covered both functions in one RED run since both live in the same new module/test file | ✅ Passed jointly with the mail_search tests (13/13) | ✅ 3 cases (success/full-detail, not-found, empty-body) — matches `tools/tasks.py::task_get_task`'s equivalent 3-case triangulation exactly | ➖ None needed — thin one-line delegate, nothing to extract |

### Test Summary (Batch 2)

- **Total tests written this batch**: 13 (10 `mail_search` + 3 `mail_get_message`)
- **Total tests passing (full suite)**: 123/123 (baseline was 110/110 — zero regressions, +13 net new)
- **Layers used**: Unit (13)
- **Approval tests** (refactoring): None — no refactoring tasks, `tools/mail.py` is a new file
- **Pure functions created**: `_mail_lookback_days` (pure given `load_settings()`'s return), `_normalize_search_bounds` (pure aside from reading `datetime.now()`)

### Deviations from Design

None. Implementation matches design.md's "Date bound handling" decision verbatim:
- Own settings key `mail_lookback_days`, default `90`, read via `tools/settings.py::load_settings()` — confirmed distinct from calendar's `lookback_days` (`7`) by an explicit test assertion (`test_search_sender_only_uses_configured_mail_lookback_days_30_not_calendar_lookback_days`).
- `_normalize_search_bounds` duplicated into `tools/mail.py` (not extracted into a shared helper), exactly as design.md specifies, so `tools/calendar.py` was not touched.
- `mail_search`'s at-least-one-filter rule mirrors `calendar_search`'s structure (raises `ValueError` before any adapter call), matching the mail-search spec's explicit requirement and design.md's decision table (row: "Date bound handling").
- `mail_get_message` is a thin one-line delegate to `adapter.get_message(entry_id)`, matching `calendar_get_event`/`task_get_task`'s precedent — typed errors (`MessageNotFoundError`, `OutlookUnavailableError`) propagate unchanged, no mapping performed at this layer (that's `server.py`'s job, Phase 6, out of scope here).

### Issues Found

None. One minor authoring note: the "missing folder rejected" scenario (mail-search spec, tasks.md 3.2) turned out to be enforced entirely by Pydantic at the `MailSearchRequest` construction boundary (Batch 1's schema has no default for `folder`), not by any code inside `mail_search` itself. The test (`test_search_missing_folder_rejected`) asserts this by constructing `MailSearchRequest(subject="Factura")` (folder omitted) and expecting `pydantic.ValidationError` — which is "rejected... before calling the adapter" per the spec's wording, just enforced one layer up from `mail_search`'s own body. No code change was needed or made to `tools/mail.py` for this scenario; flagging it here so `sdd-verify` doesn't look for a manual folder-presence check inside `mail_search` and fail to find one.

### Constraints Honored

- `win32com` was not imported anywhere in this batch's files — confirmed via `grep -n "win32com" tools/mail.py tests/test_mail_tools.py`: the only match is docstring prose in `tools/mail.py` referencing the real adapter (Phase 5), zero `import win32com` statements.
- `tools/calendar.py`, `tools/tasks.py`, `tools/outlook_adapter.py`, `tools/task_adapter.py`, and all Batch 1 files (`models/schemas.py`, `tools/errors.py`, `tools/mail_adapter.py`, `tools/fake_mail_adapter.py`) were not modified — this batch only created `tools/mail.py` and `tests/test_mail_tools.py`.
- `server.py`, `tools/outlook_adapter.py`/the real adapter, and `make-deploy-package.sh` were not touched (Phases 5-7, out of scope for this batch).
- No `pip install` was run.
- Full suite run at the end: `.venv/bin/python3.12 -m pytest -q` → **123 passed**, 0 failed, 0 skipped.

### Remaining Tasks (for Batch 3: Phase 5, and beyond)

- [ ] 5.1–5.11 Real `OutlookMailAdapter` (`tools/mail_adapter.py`): lazy `win32com` import, COM dispatch, `_FOLDER_MAP`, `_is_mail_item` guard, DASL `Restrict()`, per-folder sender haystack, `local_timezone()` normalization, `hasAttachments`, typed error mapping, read-only contract
- [ ] 6.1–6.4 Server wiring (`server.py`): `mail_adapter` param, `_resolve_real_mail_adapter()`, tool registration
- [ ] 7.1–7.2 Config & packaging (`config/settings.yaml`'s `mail_lookback_days: 90`, `make-deploy-package.sh` exclusion regex)
- [ ] 8.1–8.3 Full suite / docs / deploy gate

### Status (Cumulative — as of Batch 2)

19/19 subtasks in Phases 1-4 batch scope complete (7 from Batch 1 + 12 from Batch 2 — note: Phase 3 is tracked as 8 checklist line-items covering 10 individual test names, Phase 4 as 4 line-items covering 3 test names + 1 GREEN step). Full suite green (123/123). Ready for Batch 3 (Phase 5 — real `OutlookMailAdapter`).

## Batch 3 of 4 — Phase 5 (COMPLETE)

Mode: **Strict TDD** (test runner: `.venv/bin/python3.12 -m pytest -q`). Baseline confirmed before starting: **123/123 passed**.

### Completed Tasks

- [x] 5.1 RED `tests/test_mail_adapter.py::test_win32com_not_imported_at_module_level`, mirroring `test_task_adapter.py::_install_fake_win32com`
- [x] 5.2 RED `::test_inbox_search_restricts_on_received_time` — mocked `win32com.client`, `GetDefaultFolder(6)`, `[ReceivedTime]` DASL clause
- [x] 5.3 RED `::test_sent_search_restricts_on_sent_on` — `GetDefaultFolder(5)`, `[SentOn]` DASL clause
- [x] 5.4 RED `::test_mixed_class_items_collection_skips_non_mail_entries` — 3× `Class=43` + 1× `Class=53` → 3 results, no exception
- [x] 5.5 RED `::test_sender_haystack_per_folder` — inbox matches `SenderName`+`SenderEmailAddress`, sent matches `To`
- [x] 5.6 RED `::test_naive_com_datetime_converted_to_aware_local_time` — via `local_timezone()`, in both `search()` and `get_message()`
- [x] 5.7 RED `::test_has_attachments_true_when_attachments_count_gt_0`
- [x] 5.8 RED `::test_get_message_uses_get_item_from_id_and_class_guard_raises_not_found`
- [x] 5.9 RED `::test_dispatch_failure_raises_outlook_unavailable_error`
- [x] 5.10 RED `::test_no_mutating_com_calls_issued_on_get_message` — `Save`/`Move`/`Delete`/`UnRead` never invoked, using a real (non-Mock) `_AssertingMailItem` whose mutating members raise
- [x] 5.11 GREEN `tools/mail_adapter.py`: added `OutlookMailAdapter` — lazy `win32com.client` import inside `_dispatch_outlook`, `_FOLDER_MAP` (inbox `6`/`[ReceivedTime]`; sent `5`/`[SentOn]`), `_is_mail_item` guard (`Class == 43`), DASL `Restrict()` with concrete bounds, Python-side subject/sender substring filters, `local_timezone()` naive→aware normalization (`search()` and `get_message()`), `Attachments.Count > 0` → `hasAttachments`, `MessageNotFoundError`/`OutlookUnavailableError` typed-error mapping

### Files Created / Modified (Batch 3)

| File | Action | What Was Done |
|------|--------|----------------|
| `tools/mail_adapter.py` | Modified (additive) | Added `_FOLDER_MAP`, `_is_mail_item`, `_dasl_datetime`, `_to_aware`, `_sender_haystack`, `_resolve_date`, `_split_recipients`, `_to_summary` helpers, and the `OutlookMailAdapter` class implementing `MailPort`. The pre-existing `MailPort` Protocol (Batch 1) is untouched aside from two new imports (`tools.errors.MessageNotFoundError`/`OutlookUnavailableError`, `tools.settings.local_timezone`) needed by the real adapter. Zero `import win32com` at module scope — confirmed via `grep -n "^import win32com\|^from win32com"` (no matches); the only `import win32com.client` statement is inside `_dispatch_outlook`. |
| `tests/test_mail_adapter.py` | Created | 10 tests: module-level import guard, inbox `Restrict()` on `[ReceivedTime]`, sent `Restrict()` on `[SentOn]`, mixed-`Class` skip (3×43 + 1×53 → 3 results, no exception), per-folder sender haystack (inbox name/address vs. sent `To`), naive→aware datetime conversion in both `search()` and `get_message()`, `hasAttachments` from `Attachments.Count`, `get_message()` success + non-mail-`Class` guard raising `MessageNotFoundError`, `Dispatch` failure → `OutlookUnavailableError` for both methods, and a read-only-contract test using a hand-written `_AssertingMailItem` class (not a `Mock`) whose `Save`/`Move`/`Delete` methods and `UnRead` setter raise `AssertionError` if invoked — a plain `mocker.Mock()` would silently swallow those calls, so a real object was required to make the assertion meaningful. |

### TDD Cycle Evidence

| Task | Test File | Layer | Safety Net | RED | GREEN | TRIANGULATE | REFACTOR |
|------|-----------|-------|------------|-----|-------|-------------|----------|
| 5.1 | `tests/test_mail_adapter.py::test_win32com_not_imported_at_module_level` | Unit | ✅ 123/123 (full-suite baseline before this batch) | ✅ Written — trivially green from the start (module already had no top-level `win32com` import from Batch 1/2), but kept as a permanent regression guard mirroring `test_task_adapter.py`/`test_outlook_adapter.py`'s identical test | ✅ Passed immediately (no production change needed for this one) | ➖ Single — the property under test (absence of a module-level import) has exactly one assertion shape | ➖ None needed |
| 5.2 | `tests/test_mail_adapter.py::test_inbox_search_restricts_on_received_time` | Unit | ✅ (joint baseline, see 5.1) | ✅ Written — `ImportError: cannot import name 'OutlookMailAdapter' from 'tools.mail_adapter'` (confirmed via full-file collection run before any adapter class existed) | ✅ Passed after `OutlookMailAdapter.search()` + `_FOLDER_MAP`/`_dasl_datetime` implementation | ✅ Covered jointly with 5.3 (sent-folder variant uses a different id/DASL field) | ➖ None needed — `_dasl_datetime`/`_FOLDER_MAP` are direct ports of `tools/outlook_adapter.py`'s proven shape |
| 5.3 | `::test_sent_search_restricts_on_sent_on` | Unit | ✅ (joint) | ✅ Written — same `ImportError` collection failure | ✅ Passed jointly with 5.2's implementation (one `search()` method serves both folders via `_FOLDER_MAP`) | ✅ Triangulates 5.2 — proves the folder id/DASL field lookup is genuinely folder-relative, not hardcoded to inbox | ➖ None needed |
| 5.4 | `::test_mixed_class_items_collection_skips_non_mail_entries` | Unit | ✅ (joint) | ✅ Written — same `ImportError`; the `Class=53` fixture is built with `mocker.Mock(spec=["Class"], Class=53)` so it has *no* other mail-item attributes, forcing `_is_mail_item()` to be checked before any other attribute access (an earlier draft that read `.Subject` first would have raised `AttributeError` instead of skipping cleanly) | ✅ Passed — 3 mail entries returned, meeting-request entry skipped without exception | ✅ 4-item mixed collection (3×43 interleaved with 1×53 in the middle, not at an edge) is itself the triangulating case beyond a trivial single-item search | ➖ None needed — guard is a one-line `getattr` check, already minimal |
| 5.5 | `::test_sender_haystack_per_folder` | Unit | ✅ (joint) | ✅ Written — same `ImportError` | ✅ Passed after `_sender_haystack()` implementation | ✅ 2 sub-cases in one test: inbox match via `SenderName`/`SenderEmailAddress`, sent match via `To`, each with a matching and a non-matching fixture (4 items total) | ➖ None needed |
| 5.6 | `::test_naive_com_datetime_converted_to_aware_local_time` | Unit | ✅ (joint) | ✅ Written — same `ImportError` | ✅ Passed after `_to_aware()`/`local_timezone()` wiring in both `search()` and `get_message()` | ✅ 2 sub-cases in one test: naive `ReceivedTime` via `search()`, separately naive `ReceivedTime` via `get_message()` (through `_resolve_date()`) | ➖ None needed — `_to_aware` is a direct, unmodified port of `tools/outlook_adapter.py`'s helper |
| 5.7 | `::test_has_attachments_true_when_attachments_count_gt_0` | Unit | ✅ (joint) | ✅ Written — same `ImportError` | ✅ Passed after `Attachments.Count > 0` wiring in `_to_summary()` | ✅ 2 cases in one test: `Count=2` → `True`, `Count=0` → `False` (forces the boolean comparison, not just truthiness of the mock) | ➖ None needed |
| 5.8 | `::test_get_message_uses_get_item_from_id_and_class_guard_raises_not_found` | Unit | ✅ (joint) | ✅ Written — same `ImportError` | ✅ Passed after `get_message()`'s `_is_mail_item` guard + `GetItemFromID` wiring | ✅ 2 sub-cases in one test: `Class=43` success (asserts `entry_id`/`body`/`to`/`hasAttachments`), `Class=53` → `MessageNotFoundError` (fixture built with `spec=["Class"]` so no mail-only attribute is ever touched before the guard fires) | ➖ None needed |
| 5.9 | `::test_dispatch_failure_raises_outlook_unavailable_error` | Unit | ✅ (joint) | ✅ Written — same `ImportError` | ✅ Passed — both `search()` and `get_message()` map the `Dispatch` exception to `OutlookUnavailableError` via the shared `_dispatch_outlook()` helper | ✅ 2 call sites asserted in one test (`search()` and `get_message()` both go through the same `_dispatch_outlook()`, so both must raise) | ➖ None needed — direct port of `tools/outlook_adapter.py`/`tools/task_adapter.py`'s `_dispatch_outlook` pattern |
| 5.10 | `::test_no_mutating_com_calls_issued_on_get_message` | Unit | ✅ (joint) | ✅ Written — same `ImportError`; required a hand-rolled `_AssertingMailItem` class (not `mocker.Mock()`) since a bare Mock accepts any call/attribute-assignment silently and would make this test always pass regardless of implementation — verified by first running it against a deliberately-broken draft that called `.Save()` and confirming `AssertionError` propagated correctly, before finalizing the real (non-mutating) implementation | ✅ Passed — `get_message()`'s implementation never calls `Save`/`Move`/`Delete` or assigns `UnRead` | ➖ Single — the property under test (zero mutating calls) has one assertion shape (no exception raised) | ➖ None needed |

### Test Summary

- **Total tests written this batch**: 10
- **Total tests passing (full suite)**: 133/133 (baseline was 123/123 — zero regressions, +10 net new)
- **Layers used**: Unit (10) — `win32com.client` mocked into `sys.modules` per `tests/test_task_adapter.py::_install_fake_win32com`'s technique
- **Approval tests** (refactoring): None — no refactoring tasks, all additive to `tools/mail_adapter.py`
- **Pure functions created**: `_is_mail_item`, `_dasl_datetime`, `_to_aware`, `_sender_haystack`, `_resolve_date`, `_split_recipients` (all pure); `_to_summary` (pure given its inputs, no I/O)

### Deviations from Design

One implementation-level decision not explicitly pinned down by design.md/tasks.md, resolved from first principles and cross-checked against this exact codebase's own `FakeMailAdapter` seed data (Batch 1, `tests/test_fake_mail_adapter.py`'s `SENT_MESSAGES` fixture, which seeds sent messages with `sender="Yo"`, `sender_address="yo@example.com"` — i.e. the account owner, not the recipient):

- **`sender`/`sender_address` returned fields are NOT folder-relative** — only the search-side `sender` *filter* haystack is (per design.md's explicit "Sender filter/field asymmetry" decision, which this batch implements exactly via `_sender_haystack()`). The returned `MessageSummary.sender`/`sender_address` fields always come from the COM item's own `SenderName`/`SenderEmailAddress`, for both folders — a real Outlook `MailItem` in Sent Items still has these properties populated (as the account owner, since you sent it), which is exactly what `FakeMailAdapter`'s own Batch-1 sent-message fixtures model (`sender="Yo"`). This keeps the real adapter's output consistent with the fake's established contract without requiring a new design decision — design.md's "Folder mapping" table's "sender source: To" row describes the *filter* haystack (which task 5.5's test name — "sender haystack per folder" — also confirms), not the returned field.
- **`get_message()`'s date-field resolution** (`_resolve_date()`): since `get_message()` has no `folder` parameter, it cannot look up `_FOLDER_MAP`'s DASL field directly. Implemented as "prefer `ReceivedTime` if truthy, else `SentOn`" — matching real Outlook semantics (a Sent Items message has an empty/unset `ReceivedTime`). Covered by `test_naive_com_datetime_converted_to_aware_local_time`'s `get_message()` sub-case (uses a populated `ReceivedTime` with `SentOn=None`); no test exercises the reverse (`SentOn` populated, `ReceivedTime` falsy) explicitly, but the one-line fallback is symmetric and covered by code inspection — flagging for `sdd-verify` in case a dedicated sent-item `get_message()` test is wanted.
- **`to` field parsing**: `_split_recipients()` splits Outlook's `To` property on `;` and strips whitespace — no spec/design text pins down the exact delimiter, but this is the standard Outlook COM convention for multi-recipient `To` strings (confirmed indirectly by `FakeMailAdapter`'s `to: list[str]` field shape, which this produces via delimiter-splitting rather than a single joined string).

Everything else matches design.md/tasks.md exactly: `_FOLDER_MAP` (inbox 6/`[ReceivedTime]`, sent 5/`[SentOn]`), `_is_mail_item` (`Class == 43`) skip-in-`search()`/raise-in-`get_message()`, DASL `Restrict()` with concrete bounds, Python-side case-insensitive subject/sender substring filtering, `local_timezone()` naive→aware normalization applied identically in both methods, `Attachments.Count > 0` → `hasAttachments`, `OutlookUnavailableError` for all COM/dispatch failures, `MessageNotFoundError` for unresolved/non-mail `entryId`, and the read-only contract (no `Save`/`Move`/`Delete`/`UnRead` anywhere in the adapter).

### Issues Found

None.

### Constraints Honored

- `win32com` was not imported anywhere at module scope — confirmed via `grep -n "^import win32com\|^from win32com" tools/mail_adapter.py` (no matches); the sole `import win32com.client` statement is lazily inside `_dispatch_outlook`.
- No `pip install` was run; `win32com` remains absent from this WSL2 host, and the full suite (including the new tests) runs entirely via the `sys.modules`-injected fake per `_install_fake_win32com`.
- No mutating COM member (`Save`, `Move`, `Delete`, `UnRead` assignment) is called anywhere in `tools/mail_adapter.py` — confirmed via `grep -n "\.Save(\|\.Move(\|\.Delete(\|\.UnRead"` (no matches) and by the dedicated `_AssertingMailItem`-based test.
- `tools/calendar.py`, `tools/tasks.py`, `tools/outlook_adapter.py`, `tools/task_adapter.py`, `tools/fake_mail_adapter.py`, `tools/mail.py`, `models/schemas.py`, `tools/errors.py` were not modified — this batch only extended `tools/mail_adapter.py` (additive) and created `tests/test_mail_adapter.py`.
- `server.py`, `config/settings.yaml`, `README.md`, and `make-deploy-package.sh` were not touched (Phases 6-8, explicitly out of scope for this batch).
- Full suite run at the end: `.venv/bin/python3.12 -m pytest -q` → **133 passed**, 0 failed, 0 skipped.

### Remaining Tasks (for Batch 4: Phases 6-8)

- [ ] 6.1–6.4 Server wiring (`server.py`): `mail_adapter` param, `_resolve_real_mail_adapter()`, tool registration, `_map_error` unchanged
- [ ] 7.1–7.2 Config & packaging (`config/settings.yaml`'s `mail_lookback_days: 90`, `make-deploy-package.sh` exclusion regex → `tools/(fake_adapter|fake_task_adapter|fake_mail_adapter)\.py`)
- [ ] 8.1–8.3 Full suite / docs (`README.md`) / deploy gate (`./make-deploy-package.sh`)

### Status (Cumulative — as of Batch 3)

30/30 subtasks in Phases 1-5 batch scope complete (7 from Batch 1 + 12 from Batch 2 + 11 from Batch 3). Full suite green (133/133). Ready for Batch 4 (Phases 6-8 — server wiring, config/packaging, full suite/docs/deploy gate).

## Batch 4 of 4 — Phases 6, 7, 8 (COMPLETE, FINAL)

Mode: **Strict TDD** (test runner: `.venv/bin/python3.12 -m pytest -q`). Baseline confirmed before starting: **133/133 passed**.

### Completed Tasks

- [x] 6.1 RED `tests/test_server.py::test_import_succeeds_without_win32com` — extended with `assert "tools.mail_adapter" in sys.modules` to cover the new mail-adapter import path
- [x] 6.2 RED `::test_mail_tools_registered` — `create_server(adapter=FakeCalendarAdapter(...), mail_adapter=FakeMailAdapter(...))`; `list_tools()` returns all 7 tool names
- [x] 6.3 RED `::test_mail_adapter_selection_deferred_when_win32com_unavailable` — mirrors the task/calendar versions; `mail_search` call raises `ToolError`, not an import/construction crash, when `win32com` is unavailable
- [x] 6.4 GREEN `server.py`: added `mail_adapter: MailPort | None = None` param to `create_server()`, `_lazy_real_mail_adapter`/`_resolve_real_mail_adapter()` (mirrors the calendar/task lazy resolvers), registered `mail_search`/`mail_get_message` tools; `_map_error` left unchanged (already catches the shared `CalendarToolError` base, which `MessageNotFoundError` extends)
- [x] (incidental, required by 6.2/6.4) updated `test_all_three_tools_registered`'s and `test_task_tools_registered`'s expected sets from 5 to 7 tool names — the two new tools are always registered by `create_server()` regardless of which adapters are injected, so the old exact-5 assertions would otherwise regress
- [x] (incidental TDD coverage) added `test_mail_search_tool_returns_results_via_fake_mail_adapter` — end-to-end `mail_search` call via FastMCP's in-process `Client`, confirms request→adapter→response wiring, not just registration
- [x] 7.1 `config/settings.yaml`: added `mail_lookback_days: 90` with a comment matching `lookback_days`'s style; also added `tests/test_mail_tools.py::test_settings_yaml_declares_mail_lookback_days_90`, a RED-first test asserting the literal key (not just the code's default) is present in the real file — `mail_lookback_days` is a LIVE key (`tools/mail.py::_mail_lookback_days()` already reads it), unlike the dead `calendar_folder_id`/`tasks_folder_id` entries, so a real-file assertion closes the gap Batch 2 flagged ("mocks load_settings... Phase 7 hasn't added the key yet")
- [x] 7.2 `make-deploy-package.sh`: exclusion regex changed from `grep -vxE 'tools/(fake_adapter|fake_task_adapter)\.py'` to `grep -vxE 'tools/(fake_adapter|fake_task_adapter|fake_mail_adapter)\.py'`; updated the adjacent comment to mention all three fakes
- [x] 8.1 Full suite run — green (see Test Results below)
- [x] 8.2 `README.md` updated: intro tool list (5→7 tools, added `mail_search`/`mail_get_message` bullets, "five tools"→"seven tools"), Claude Desktop discovery steps (packaged install + manual/dev install, both updated to list all 7 tools), `Configuration` section (`mail_lookback_days` bullet, explicitly contrasted with `lookback_days`), `Development` section (mentions `FakeMailAdapter`/`tests/test_mail_adapter.py`/`tests/test_mail_tools.py`, "all three fake adapters"), `Manual smoke test` section (7-tool list check + new `mail_search`/`mail_get_message` step covering both inbox and sent folders), `Known limitations` (Inbox/Sent Items folder scope + mail read-only note), `Possible extensions` (removed the "Email" bullet — it's shipped now — replaced with "Mail Drafts and sending mail" + "Attachments" follow-on ideas, reworded the section's lead-in from "calendar and task tools" to "calendar, task, and mail tools")
- [x] 8.3 `./make-deploy-package.sh` run to completion — succeeded, including the network-dependent wheel-download step (see Test Results below)

### Files Created / Modified (Batch 4)

| File | Action | What Was Done |
|------|--------|----------------|
| `server.py` | Modified (additive) | Added `MailPort` import, `tools.mail` import (`mail_get_message`, `mail_search`), `MailFolder`/`MailSearchRequest`/`MessageDetail`/`MessageSummary`/`GetMessageRequest` schema imports, `_lazy_real_mail_adapter`/`_resolve_real_mail_adapter()`, `mail_adapter` param on `create_server()`, `_mail_adapter()` closure, `_mail_search`/`_mail_get_message` tool registrations. Module docstring updated to mention all 7 tools. No changes to `_map_error` or the 3 calendar/2 task tool registrations. |
| `tests/test_server.py` | Modified | Added `FakeMailAdapter` import; extended `test_import_succeeds_without_win32com`; widened `test_all_three_tools_registered`'s and `test_task_tools_registered`'s expected sets to 7 tools; added `test_mail_tools_registered`, `test_mail_search_tool_returns_results_via_fake_mail_adapter`, `test_mail_adapter_selection_deferred_when_win32com_unavailable`. |
| `config/settings.yaml` | Modified (additive) | Added `mail_lookback_days: 90` + doc comment (module header comment also updated to mention Mail). |
| `tests/test_mail_tools.py` | Modified (additive) | Added `test_settings_yaml_declares_mail_lookback_days_90` (real, unmocked `load_settings()` check). |
| `make-deploy-package.sh` | Modified | Exclusion regex + adjacent comment updated to cover all three fakes. |
| `README.md` | Modified | See task 8.2 above — 7 sections touched (intro, Claude Desktop discovery step, Configuration, Development, Manual smoke test, Known limitations, Possible extensions), all additive/rewording, no structural reorganization beyond replacing the now-shipped Email bullet in "Possible extensions". |
| `openspec/changes/outlook-mail-read/tasks.md` | Modified | All Phase 6/7/8 tasks marked `[x]` (39/39 total). |

### TDD Cycle Evidence (Batch 4)

| Task | Test File | Layer | Safety Net | RED | GREEN | TRIANGULATE | REFACTOR |
|------|-----------|-------|------------|-----|-------|-------------|----------|
| 6.1-6.3 | `tests/test_server.py` | Integration (FastMCP in-process client) | ✅ 133/133 (full-suite baseline before batch) | ✅ Written — confirmed via a dedicated pre-implementation run: `test_mail_tools_registered`/`test_mail_search_tool_returns_results_via_fake_mail_adapter` failed with `TypeError: create_server() got an unexpected keyword argument 'mail_adapter'`; `test_all_three_tools_registered`/`test_task_tools_registered` (pre-existing, widened) failed on the 7-tool assertion; `test_import_succeeds_without_win32com`'s new assertion failed (`tools.mail_adapter` not yet imported by `server.py`); `test_mail_adapter_selection_deferred_when_win32com_unavailable` failed the same way as the registration tests (5 failed, 12 passed at this checkpoint) | ✅ 17/17 (`tests/test_server.py`) after 6.4 | ✅ 3 registration/wiring cases (fake-adapter-injected registration, real-adapter-deferred error path, end-to-end fake-adapter call) plus the extended import-safety assertion and both widened tool-count assertions | ➖ None needed — mirrors the existing calendar/task-adapter injection/lazy-resolution pattern exactly, just parameterized for the third port |
| 6.4 | `server.py` | — | (same run) | (see above) | ✅ 136/136 (full suite) | (see above) | ➖ None needed |
| 7.1 | `config/settings.yaml`, `tests/test_mail_tools.py` | Unit (config-integration) | ✅ 136/136 | ✅ Written — `test_settings_yaml_declares_mail_lookback_days_90` failed first with `assert 'mail_lookback_days' in {'lookback_days': 7, ...}` against the real file (confirmed this wasn't a trivial pass: an earlier draft asserting only `_mail_lookback_days() == 90` passed *before* the key existed, since the code's own default is also 90 — rewritten to assert the literal key's presence in the loaded YAML instead, which correctly failed pre-edit) | ✅ 137/137 (full suite) after adding the key to `config/settings.yaml` | ➖ Single — one concrete value (`90`) to assert; no branching to triangulate | ➖ None needed |
| 7.2 | `make-deploy-package.sh` | Config/build-script (no unit test — verified via manual `grep -rn fake_adapter\|fake_task_adapter\|fake_mail_adapter server.py` dry-run, `bash -n` syntax check, plus gate 1/6 of the real deploy-package run) | ✅ 137/137 | ➖ N/A — shell manifest line, not testable via pytest | ✅ Confirmed: manifest includes `tools/mail.py`/`tools/mail_adapter.py`, excludes all three `tools/fake_*.py` files (checked via the final zip's `unzip -l` listing) | ➖ N/A | ➖ None needed |
| 8.1-8.3 | Full suite + `README.md` + `./make-deploy-package.sh` | — | ✅ 137/137 | ➖ N/A (docs/gate-run tasks, no RED phase) | ✅ Full suite 137/137; `make-deploy-package.sh` completed with all 6 gates PASS (gate 5 via cached portable pwsh), zip built and staged correctly | ➖ N/A | ➖ N/A |

### Test Summary (Batch 4)

- **Total tests written this batch**: 5 (3 server-wiring: `test_mail_tools_registered`, `test_mail_search_tool_returns_results_via_fake_mail_adapter`, `test_mail_adapter_selection_deferred_when_win32com_unavailable`; 1 config-integration: `test_settings_yaml_declares_mail_lookback_days_90`); plus 1 pre-existing test extended in place (`test_import_succeeds_without_win32com`) and 2 pre-existing tests' assertions widened (`test_all_three_tools_registered`, `test_task_tools_registered`, not counted as new). Note: the task list credits "5" new server tests in the archived `outlook-tasks-todo` Batch 4 precedent by a slightly different count basis — here the literal new-test count is 4 (3 server + 1 config), matching the numbers below exactly.
- **Total tests passing (full suite)**: 137/137 (baseline at start of Batch 4 was 133/133 — zero regressions across the whole batch, +4 net new)
- **Layers used**: Integration/FastMCP-in-process (3, server wiring), Unit/config-integration (1, real settings.yaml read)
- **Approval tests** (refactoring): None — no refactoring tasks, all additive
- **Pure functions created**: None new this batch (`_resolve_real_mail_adapter()` is a cached constructor, not a pure function, mirroring its calendar/task siblings)

### Deviations from Design (Batch 4)

One deliberate addition beyond tasks.md's literal wording, not a deviation from any design decision: task 7.1 says "add a test if the checklist demands one" (per the batch instructions) — the checklist itself doesn't explicitly demand one, but since `mail_lookback_days` is a *live* key (unlike the dead `calendar_folder_id`/`tasks_folder_id` entries this project already carries as inert documentation), a real-file assertion was added anyway to close the exact gap Batch 2's apply-progress flagged ("mocks `tools.mail.load_settings`... Phase 7 hasn't added the key yet"). This is additive test coverage, not a change to any production behavior or design decision.

Everything else in Batch 4 matches design.md/tasks.md exactly:
- `server.py`'s `_resolve_real_mail_adapter()` mirrors `_resolve_real_adapter()`/`_resolve_real_task_adapter()` exactly (same lazy-construct-and-cache pattern, same "import inside the function, not at module scope" discipline).
- `_map_error` was NOT touched, per design.md's explicit "no changes needed" call-out — confirmed by `MessageNotFoundError`/`OutlookUnavailableError` both extending the already-caught `CalendarToolError` base.
- `config/settings.yaml`'s `mail_lookback_days: 90` and `make-deploy-package.sh`'s widened exclusion regex match tasks.md 7.1/7.2 verbatim.
- `README.md`'s update matches tasks.md 8.2's instruction (tool list intro + moving Mail out of the future-work note) and mirrors the archived `outlook-tasks-todo` Batch 4's README-update style/scope.

### Issues Found (Batch 4)

None blocking. One thing worth flagging for `sdd-verify`, consistent with the pattern already flagged for `calendar_folder_id`/`tasks_folder_id` in the archived `outlook-tasks-todo` change: mail's inbox/sent `GetDefaultFolder` ids (`6`/`5`) are hardcoded as `_FOLDER_MAP` constants in `tools/mail_adapter.py`, never read from `config/settings.yaml` (per design.md's explicit "settings.yaml folder ids omitted" decision) — this is intentional, not an oversight, and differs from `mail_lookback_days`, which *is* wired live. No action taken; documenting for consistency with the existing precedent.

### Constraints Honored (Batch 4)

- `win32com` was not imported anywhere at module load time — `server.py`'s new `from tools.mail_adapter import MailPort` and `from tools.mail import mail_get_message, mail_search` are both safe (neither module imports `win32com` at module scope); confirmed by gate 3 of `make-deploy-package.sh` (`PASS: gate 3: no module-level win32com import`) and by `test_import_succeeds_without_win32com`.
- No calendar or task file *behavior* was changed — `tools/outlook_adapter.py`, `tools/calendar.py`, `tools/fake_adapter.py`, `tools/task_adapter.py`, `tools/tasks.py`, `tools/fake_task_adapter.py` untouched; the 3 calendar + 2 task tool registrations in `server.py` are byte-for-byte unchanged (only new code appended after them).
- No `pip install` was run into the dev `.venv` on this WSL2 host; the deploy script's own isolated wheel-download steps (network-dependent, run against `uv`/`pip download --platform win_amd64`, never installing into the local `.venv`) are the only network activity, and they succeeded.
- `make-deploy-package.sh`'s test-suite gate (gate 2) and win32com-safety gate (gate 3) stayed intact and both passed during the real run.
- Launcher scripts under `deploy/` were not touched (pure ASCII requirement was never at risk) — gate 4/4b/5 all passed unchanged.

### Test Results — full suite and deploy-package gate (Batch 4)

- **Full suite**: `.venv/bin/python3.12 -m pytest -q` → **137 passed** (0 failed, 0 skipped). Baseline at Batch 4 start: 133/133. Net delta: +4 tests, zero regressions.
- **`./make-deploy-package.sh`**: ran to full completion, **all gates PASS**:
  - gate 1 (manifest files exist): PASS — 15 manifest files + 5 launcher sources
  - gate 2 (full test suite): PASS — 137 passed
  - gate 3 (no module-level `win32com` import): PASS
  - gate 4 (launcher scripts pure ASCII): PASS
  - gate 4b (no unescaped parens in `.bat` echo lines): PASS
  - gate 5 (`install.ps1` parses cleanly): PASS (via cached portable pwsh)
  - gate 6 (wheels coverage, win312+win313): PASS — 79 wheel files staged, including `pywin32-312-cp312-cp312-win_amd64.whl`/`pywin32-312-cp313-cp313-win_amd64.whl` and `fastmcp-3.4.7-py3-none-any.whl`
  - Network wheel-download step (the one step this environment could plausibly lack network for) **succeeded** — `uv pip compile` resolved 69 packages for cp312 (+ a cp313 pass), and `pip download` fetched all of them plus `pywin32`/`setuptools`/`wheel`.
  - Output: `dist/WinMCP-20260824.zip` (32,360,542 bytes, 104 files, sha256 `055a6308f23e58dc494e596f89497dee9c2d961bd34df7ff8dd879167c894c18`). Verified via `unzip -l` that `tools/mail.py`/`tools/mail_adapter.py` are present and `tools/fake_adapter.py`/`tools/fake_task_adapter.py`/`tools/fake_mail_adapter.py` are all absent (no `fake_*` entries at all in the listing).

### Status (Cumulative, FINAL)

39/39 subtasks across Phases 1-8 complete (7 Batch 1 + 12 Batch 2 + 11 Batch 3 + 9 Batch 4 [6.1-6.4, 7.1-7.2, 8.1-8.3 collapse to the tasks.md numbering]). Full suite green (137/137). `./make-deploy-package.sh` completed successfully end-to-end, including the network-dependent step. Change `outlook-mail-read` is feature-complete and ready for `sdd-verify`.

## Post-verify remediation

Closed the 3 WARNING findings from `verify-report.md` (PASS WITH WARNINGS) before archive. No production-code behavior changed — two coverage-gap tests added, one design-doc wording alignment.

- **`tests/test_mail_tools.py`**: added `test_get_message_outlook_unavailable_returns_tool_error` — calls `mail_get_message(request, adapter)` with `FakeMailAdapter(inbox=[], unavailable=True)` and asserts `OutlookUnavailableError` propagates. Closes the "Outlook Unavailable" mail-get-detail scenario gap (previously only proven one layer down, at `FakeMailAdapter.get_message()`/`OutlookMailAdapter.get_message()`), mirroring `test_tasks_tools.py`/`test_calendar_tools.py`'s `test_search_outlook_unavailable_returns_tool_error` pattern. Confirmed right-reason: with `unavailable=False` and an empty inbox the same call instead raises `MessageNotFoundError`, which would fail `pytest.raises(OutlookUnavailableError)` — so the test is not vacuous.
- **`tests/test_mail_adapter.py`**: added `test_get_message_falls_back_to_sent_on_when_received_time_is_falsy` — mocks a `GetItemFromID` result with `ReceivedTime=None`/`SentOn` populated (the genuine Sent Items case) and asserts `OutlookMailAdapter.get_message()`'s returned `date` equals `SentOn`. Closes the `_resolve_date()` fallback-branch gap (every prior `get_message()` fixture set a truthy `ReceivedTime`). Confirmed right-reason by calling `_resolve_date()` directly against the same fixture shape and by checking that an unresolved fallback would hit `_to_aware(None, tz)` and raise `AttributeError` rather than pass silently.
- **`openspec/changes/outlook-mail-read/design.md`**: reworded the "Sender filter/field asymmetry" decision (Architecture Decisions table), the "Folder mapping" table's sender column, and the `MessageSummary.sender` inline comment to match as-built behavior: only the search **filter** haystack is folder-relative (inbox: `SenderName`+`SenderEmailAddress`; sent: `To`); the **returned** `sender`/`senderAddress` fields always come from the item's own `SenderName`/`SenderEmailAddress` in both folders, matching real Outlook semantics. Wording-only alignment, no behavior/design change.

Full suite after remediation: `.venv/bin/python3.12 -m pytest -q` → **139 passed**, 0 failed, 0 skipped (baseline 137 + 2 new tests).
