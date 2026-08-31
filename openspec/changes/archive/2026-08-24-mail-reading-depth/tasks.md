# Tasks: Mail Reading Depth

## Phase 1: Schemas & Errors (Foundation)

- [x] 1.1 RED `tests/test_schemas.py`: `MailFolder.DRAFTS`; `folder` optional + `folderPath` alias; validator rejects both/neither, accepts folder-only and folderPath-only; `GetMessageRequest.include_html_body` default `False` alias `includeHtmlBody`; `MessageDetail.attachment_names`/`html_body` default `[]`/`None`
- [x] 1.2 GREEN `models/schemas.py`: add `DRAFTS`; make `folder: MailFolder | None`; add `folder_path` (alias `folderPath`) + `model_validator(mode="after")` exclusivity check; add `include_html_body` to `GetMessageRequest`; add `attachment_names`/`html_body` to `MessageDetail`
- [x] 1.3 RED `tests/test_errors.py`: `MailFolderNotFoundError(CalendarToolError)`, `code="mail_folder_not_found"`, carries `path`/`failing_segment`
- [x] 1.4 GREEN `tools/errors.py`: add `MailFolderNotFoundError`

## Phase 2: MailPort + FakeMailAdapter Mirror

- [x] 2.1 RED `tests/test_fake_mail_adapter.py`: drafts store dispatch; `folder_path` dict keyed by path string, hit and unresolved-path → `MailFolderNotFoundError`; seeded fixtures carry `attachment_names`/`html_body`; `get_message(include_html=True/False)` gates `html_body`
- [x] 2.2 GREEN `tools/mail_adapter.py`: extend `MailPort` Protocol — `search(folder=None, folder_path=None, ...)`, `get_message(entry_id, include_html=False)`
- [x] 2.3 GREEN `tools/fake_mail_adapter.py`: `FakeMailAdapter` — drafts folder, path-keyed store, `include_html` gating, `attachment_names` passthrough

## Phase 3: tools/mail.py Threading

- [x] 3.1 RED `tests/test_mail_tools.py::test_search_folder_path_passed_through_to_adapter` and `::test_search_mandatory_filter_rule_applies_to_folder_path_too`
- [x] 3.2 RED `::test_search_folder_inbox_and_sent_backward_compatible` (no-regression: same call/result shape as before)
- [x] 3.3 RED `::test_get_message_include_html_body_threaded_to_adapter` and `::test_get_message_default_omits_html_body_backward_compatible`
- [x] 3.4 GREEN `tools/mail.py`: thread `folder_path` into `mail_search`'s adapter call and `include_html_body` into `mail_get_message`'s adapter call; validation ordering unchanged

## Phase 4: Real OutlookMailAdapter

- [x] 4.1 RED `tests/test_mail_adapter.py::test_drafts_search_uses_get_default_folder_16_and_restricts_on_last_modification_time`
- [x] 4.2 RED `::test_resolve_date_falls_back_to_last_modification_time_when_received_and_sent_on_absent` (search and get_message)
- [x] 4.3 RED `::test_folder_path_traverses_default_store_root_via_per_segment_folders_item`
- [x] 4.4 RED `::test_folder_path_unresolved_segment_raises_mail_folder_not_found_error`
- [x] 4.5 RED `::test_folder_path_search_skips_restrict_and_filters_dates_in_python_via_fallback_chain` (Restrict configured to fail if called; mixed ReceivedTime/LastModificationTime items)
- [x] 4.6 RED `::test_attachment_names_enumerated_1_indexed` and `::test_attachment_names_empty_when_count_zero`
- [x] 4.7 RED `::test_html_body_not_accessed_unless_include_html_true` and `::test_html_body_read_when_include_html_true_body_unaffected`
- [x] 4.8 RED `::test_no_mutating_com_calls_across_search_traversal_and_get_message` — `Save`/`Move`/`Delete`/`UnRead` asserted absent
- [x] 4.9 RED `::test_inbox_sent_backward_compatible_no_regression` (existing `[ReceivedTime]`/`[SentOn]` Restrict paths unchanged)
- [x] 4.10 GREEN `tools/mail_adapter.py`: `_FOLDER_MAP` += `drafts: (16, "[LastModificationTime]", "drafts_folder_id")`; extend `_resolve_date()` fallback; add folder_path traversal helper (`DefaultStore.GetRootFolder()`, per-segment `Folders.Item(name)`, raise `MailFolderNotFoundError`); `search()` folder_path branch skips `Restrict()`, Python-filters via `_resolve_date()`; `get_message()` gains `include_html`, 1-indexed attachment loop, conditional `HTMLBody` read

## Phase 5: Smoke Test Coverage

- [x] 5.1 RED `tests/test_smoke_test.py::test_mail_drafts_family_hit_chains_mail_get_message` and `::test_mail_drafts_family_zero_hits_passes_without_chaining`
- [x] 5.2 GREEN `deploy/smoke_test.py`: add `mail-drafts` `Family` tuple to `FAMILIES` (`folder="drafts"` search + date bound, same helper as other families)

## Phase 6: Config, Docs & Full Suite

- [x] 6.1 Update `config/settings.yaml`: add `drafts_folder_id: 16`, comment matching `inbox_folder_id`/`sent_folder_id` style
- [x] 6.2 Update `README.md`: limitations (shared/delegated mailboxes deferred, `folderPath` default-store-subtree only, no smoke coverage for `folderPath`/`includeHtmlBody`) and extensions (drafts, `folderPath`, `includeHtmlBody`, `attachmentNames`)
- [x] 6.3 Run `.venv/bin/python3.12 -m pytest -q` — full suite green (baseline 174 + new tests); confirm no regressions in `folder="inbox"`/`folder="sent"` and default (no `includeHtmlBody`) detail behaviors; fix any failures

## Phase 7 — server wiring (orchestrator-directed amendment)

Not in the original design.md scope (design.md's "Technical Approach"
explicitly stated "`server.py` needs no change"). Added by orchestrator
directive during Batch 3: `folderPath`/`includeHtmlBody` were fully
implemented end-to-end at the `tools/mail.py` → `MailPort` → adapter layer
since Batch 1/2, but never reachable from an actual MCP client call because
`server.py`'s `mail_search`/`mail_get_message` tool registrations still
declared the pre-mail-reading-depth wire signature (`folder` mandatory, no
`includeHtmlBody`). This phase closes that gap — see Batch 1/2's apply-
progress "Issues Found" sections, which first flagged it.

- [x] 7.1 RED `tests/test_server.py::test_mail_search_tool_folder_path_returns_results_via_fake_mail_adapter` — `mail_search` called with `folderPath` only (no `folder`) against a `FakeMailAdapter(folder_paths=...)`, end-to-end via FastMCP's in-process `Client`
- [x] 7.2 RED `::test_mail_search_tool_both_folder_and_folder_path_surfaces_clean_tool_error` — both selectors given at once must surface as a clean `ToolError` (not a crash), via the existing `_map_error` `ValueError`/`ValidationError` path
- [x] 7.3 RED `::test_mail_search_tool_folder_path_unresolved_returns_mail_folder_not_found_error` — an unresolved `folderPath` must surface the `mail_folder_not_found` code cleanly through `_map_error`'s existing `CalendarToolError` base-class catch (confirms no explicit `MailFolderNotFoundError` branch is needed)
- [x] 7.4 RED `::test_mail_get_message_tool_include_html_body_returns_html_body` — `mail_get_message` called with `includeHtmlBody=true` returns the seeded `htmlBody`
- [x] 7.5 GREEN `server.py`: `_mail_search` — `folder: MailFolder | None = None`, add `folder_path: Annotated[str | None, Field(default=None, alias="folderPath")] = None`; move `MailSearchRequest(...)` construction *inside* the existing `try` block (previously outside it — harmless only because `folder` was mandatory pre-amendment, so the exclusivity validator could never fire) so its `ValidationError` reaches `_map_error` via the existing `(CalendarToolError, ValueError)` catch. `_mail_get_message` — add `include_html_body: Annotated[bool, Field(default=False, alias="includeHtmlBody")] = False`, threaded into `GetMessageRequest(entry_id=entry_id, include_html_body=include_html_body)`; `_map_error` itself left unchanged, per instructions
- [x] 7.6 Backward-compat guard (no new production code — confirms existing behavior): `test_mail_search_tool_returns_results_via_fake_mail_adapter` (pre-existing, `folder="inbox"`) and `test_mail_get_message_tool_default_omits_html_body_backward_compatible` (new, asserts `htmlBody is None` when `includeHtmlBody` is omitted) both pass unchanged

**Closing note (not a task):** `LastModificationTime`-for-drafts reliability against real Outlook is unverified here — validate it manually as part of the combined rebuild + QA deploy that follows this change, on the Windows host.
