# Tasks: Outlook Mail (Read-Only)

## Phase 1: Schemas & Errors (Foundation)

- [x] 1.1 RED `tests/test_schemas.py`: `MailFolder` enum (`inbox`/`sent`); `MessageSummary` aliases `entryId`/`hasAttachments`, has `senderAddress`; `MessageDetail(MessageSummary)` adds `body`+`to`
- [x] 1.2 GREEN `models/schemas.py`: add `MailFolder`, `MessageSummary`, `MessageDetail`, `MailSearchRequest`, `GetMessageRequest`
- [x] 1.3 RED `tests/test_errors.py`: `MessageNotFoundError(CalendarToolError)` exists, carries `code = "message_not_found"`
- [x] 1.4 GREEN `tools/errors.py`: add `MessageNotFoundError` (reuse `OutlookUnavailableError` as-is)

## Phase 2: MailPort + FakeMailAdapter (outlook-mail-adapter: Adapter Interface)

- [x] 2.1 RED `tests/test_fake_mail_adapter.py`: per-folder dispatch, date/subject/sender filters (inbox `SenderName`/`SenderEmailAddress`; sent `To`); `get_message()` returns/raises `MessageNotFoundError`; configurable `OutlookUnavailableError`
- [x] 2.2 GREEN `tools/mail_adapter.py`: define `MailPort` Protocol (`search(folder, date_from, date_to, subject, sender)`, `get_message(entry_id)`)
- [x] 2.3 GREEN `tools/fake_mail_adapter.py`: `FakeMailAdapter` implementing `MailPort`, in-memory per-folder seed via constructor, filter sequence (date bounds → subject → sender)

## Phase 3: mail_search (mail-search spec)

- [x] 3.1 RED `tests/test_mail_tools.py::test_search_valid_folder_and_date_range`
- [x] 3.2 RED `::test_search_all_filters_omitted_raises_value_error`, `::test_search_missing_folder_rejected`
- [x] 3.3 RED `::test_search_subject_only_fills_both_bounds_from_mail_lookback_days_default_90`
- [x] 3.4 RED `::test_search_sender_only_uses_configured_mail_lookback_days_30_not_calendar_lookback_days`
- [x] 3.5 RED `::test_search_only_date_from_given_fills_date_to_with_now`
- [x] 3.6 RED `::test_search_sender_filter_matches_recipient_on_sent_folder`, `::test_search_sender_filter_matches_sender_name_on_inbox_folder`
- [x] 3.7 RED `::test_search_empty_result_returns_empty_list`, `::test_search_outlook_unavailable_returns_tool_error`
- [x] 3.8 GREEN `tools/mail.py`: implement `mail_search(request, adapter)` — at-least-one-filter validation, `mail_lookback_days` bound-fill (mirrors `calendar.py::_normalize_search_bounds`, own key, not `lookback_days`)

## Phase 4: mail_get_message (mail-get-detail spec)

- [x] 4.1 RED `tests/test_mail_tools.py::test_get_message_success_returns_full_detail`
- [x] 4.2 RED `::test_get_message_not_found_raises_tool_error`
- [x] 4.3 RED `::test_get_message_empty_body_returns_empty_string`
- [x] 4.4 GREEN `tools/mail.py`: implement `mail_get_message(request, adapter)`

## Phase 5: Real OutlookMailAdapter (outlook-mail-adapter: lazy import, COM, guards, datetime)

- [x] 5.1 RED `tests/test_mail_adapter.py::test_win32com_not_imported_at_module_level`, mirroring `test_task_adapter.py::_install_fake_win32com`
- [x] 5.2 RED `::test_inbox_search_restricts_on_received_time` — mocked `win32com.client`, `GetDefaultFolder(6)`, `[ReceivedTime]` DASL clause
- [x] 5.3 RED `::test_sent_search_restricts_on_sent_on` — `GetDefaultFolder(5)`, `[SentOn]` DASL clause
- [x] 5.4 RED `::test_mixed_class_items_collection_skips_non_mail_entries` — 3× `Class=43` + 1× `Class=53` → 3 results, no exception
- [x] 5.5 RED `::test_sender_haystack_per_folder` — inbox matches `SenderName`+`SenderEmailAddress`, sent matches `To`
- [x] 5.6 RED `::test_naive_com_datetime_converted_to_aware_local_time` — via `local_timezone()`, in both `search()` and `get_message()`
- [x] 5.7 RED `::test_has_attachments_true_when_attachments_count_gt_0`
- [x] 5.8 RED `::test_get_message_uses_get_item_from_id_and_class_guard_raises_not_found`
- [x] 5.9 RED `::test_dispatch_failure_raises_outlook_unavailable_error`
- [x] 5.10 RED `::test_no_mutating_com_calls_issued_on_get_message` — `Save`/`Move`/`Delete`/`UnRead` never invoked
- [x] 5.11 GREEN `tools/mail_adapter.py`: `OutlookMailAdapter` — lazy `win32com.client` import, `_FOLDER_MAP` (inbox `6`/`[ReceivedTime]`; sent `5`/`[SentOn]`), `_is_mail_item` guard, DASL `Restrict()`, substring filters, `local_timezone()` normalization, `hasAttachments`, typed errors

## Phase 6: Server Wiring (no `_map_error` changes needed)

- [x] 6.1 RED `tests/test_server.py::test_import_succeeds_without_win32com` (extend for mail path)
- [x] 6.2 RED `::test_mail_tools_registered` — `create_server(mail_adapter=...)`; `list_tools()` includes both mail tools
- [x] 6.3 RED `::test_mail_adapter_selection_deferred_when_win32com_unavailable` — runtime error, not import-time crash
- [x] 6.4 GREEN `server.py`: add `mail_adapter` param, `_resolve_real_mail_adapter()` lazy resolver, register both tools; `_map_error` unchanged

## Phase 7: Config & Packaging

- [x] 7.1 Update `config/settings.yaml`: add `mail_lookback_days: 90`, comment matching `lookback_days` style; folder ids stay omitted (mirrors calendar/tasks dead-entry precedent)
- [x] 7.2 Update `make-deploy-package.sh`: exclusion regex → `grep -vxE 'tools/(fake_adapter|fake_task_adapter|fake_mail_adapter)\.py'`

## Phase 8: Full Suite, Docs & Deploy Gate

- [x] 8.1 Run `.venv/bin/python3.12 -m pytest -q` — full suite green; fix regressions
- [x] 8.2 Update `README.md`: add `mail_search`/`mail_get_message` to the tool list intro; move Mail out of the future-work note (~L254-260) into shipped tools
- [x] 8.3 Run `./make-deploy-package.sh` — succeeds; package excludes all three `tools/fake_*.py` files
