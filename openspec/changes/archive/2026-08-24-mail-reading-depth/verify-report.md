# Verify Report: mail-reading-depth

**Change**: mail-reading-depth
**Version**: N/A (openspec delta specs, no version field)
**Mode**: Strict TDD (test runner: `.venv/bin/python3.12 -m pytest -q`)

---

## Completeness

| Metric | Value |
|--------|-------|
| Tasks total | 32 checklist lines (Phases 1-6: 45 subtasks incl. multi-name RED lines; Phase 7 amendment: 6 subtasks) |
| Tasks complete | 32/32 checklist lines `[x]`; 0 incomplete |
| Tasks incomplete | None |

Phase 7 (server.py wiring) is an orchestrator-directed amendment, not in design.md's original scope (design.md explicitly stated "`server.py` needs no change"). It is documented in tasks.md with its own preamble explaining why it was added, and is fully complete (7.1-7.6, all `[x]`). This is treated as a documentation-alignment item, not a deviation defect, per the verification brief.

---

## Build & Tests Execution

**Build**: N/A — no build/type-check step configured for this project (`openspec/config.yaml`'s `rules.verify.build_command` is empty; no linter/type-checker installed, matches `testing.quality_tools` in config).

**Tests**: ✅ 220 passed, 0 failed, 0 skipped

```
.venv/bin/python3.12 -m pytest -q
........................................................................ [ 32%]
........................................................................ [ 65%]
........................................................................ [ 98%]
....                                                                     [100%]
220 passed in 1.97s
```

Matches the expected count exactly (baseline 174 at change start -> 220 after all 3 batches, +46 net new tests, zero regressions).

**Coverage**: Not available — `pytest-cov` is not installed (`openspec/config.yaml`'s `testing.coverage.available: false`). Not flagged as a failure per Strict TDD rules (informational only).

---

## TDD Compliance

| Check | Result | Details |
|-------|--------|---------|
| TDD Evidence reported | ✅ | Full "TDD Cycle Evidence" tables present in all 3 apply-progress batches, per-task RED/GREEN/TRIANGULATE/REFACTOR columns |
| All tasks have tests | ✅ | Every implementation task (1.2, 1.4, 2.2/2.3, 3.4, 4.10, 5.2, 6.1, 7.5) is preceded by a RED task with a named test file/function |
| RED confirmed (tests exist) | ✅ | Spot-checked test functions named in tasks.md against actual test files — all found: `test_folder_path_traverses_default_store_root_via_per_segment_folders_item` (test_mail_adapter.py:833), `test_folder_path_unresolved_segment_raises_mail_folder_not_found_error` (:865), `test_folder_path_search_skips_restrict_and_filters_dates_in_python_via_fallback_chain` (:894), `test_attachment_names_enumerated_1_indexed` (:961), `test_html_body_not_accessed_unless_include_html_true` (:1018), `test_no_mutating_com_calls_across_search_traversal_and_get_message` (:1064), `test_inbox_sent_backward_compatible_no_regression` (:1098), `test_settings_yaml_declares_drafts_folder_id` (:405); server.py-layer tests at test_server.py:171/206/228/249/283 all present |
| GREEN confirmed (tests pass) | ✅ | Full suite (220/220) passes now, cross-referencing every test named above |
| Triangulation adequate | ✅ | Multi-case scenarios verified directly, e.g. the Restrict-skip/fallback-chain test asserts 4 distinct items (2 via ReceivedTime, 1 via LastModificationTime fallback, 1 excluded as out-of-range) resolving to a specific 3-element entry-id set — not a trivial pass |
| Safety Net for modified files | ✅ | Each batch reports a pre-batch full-suite baseline (174 -> 200 -> 211 -> 220) confirmed green before proceeding |

**TDD Compliance**: 6/6 checks passed

---

## Test Layer Distribution

| Layer | Tests | Files | Tools |
|-------|-------|-------|-------|
| Unit | 149 (this change's net-new + touched files) | 7 (`test_schemas.py`, `test_errors.py`, `test_fake_mail_adapter.py`, `test_mail_adapter.py`, `test_mail_tools.py`, `test_smoke_test.py`, `test_server.py`) | pytest, pytest-mock |
| Integration | 22 (a subset of `test_server.py`'s 22, incl. the 5 new Phase 7 tests) | 1 (`test_server.py`, via FastMCP's in-process `Client`) | FastMCP `Client` (in-process, no subprocess/stdio) |
| E2E | 0 | 0 | Not available in this environment (Windows/Outlook required) |
| **Total** | **220** (full suite) | 7 | |

`test_server.py`'s tests exercise real request/response wiring through FastMCP's ASGI-less in-memory transport (classified integration per the strict-tdd-verify.md indicators: no real subprocess, but does exercise tool registration + schema validation + `_map_error`, which is more than a pure unit test). All other files are pure unit tests against `FakeMailAdapter`, mocked `win32com.client`, or Pydantic schemas directly.

---

## Changed File Coverage

Coverage analysis skipped — no coverage tool detected (`pytest-cov` not installed, confirmed in `openspec/config.yaml`).

---

## Assertion Quality

Scanned all 7 test files touched/created by this change (3,202 total lines). No tautologies, ghost loops, or assertion-free tests found.

| File | Line | Assertion | Issue | Severity |
|------|------|-----------|-------|----------|
| — | — | — | None found | — |

**Assertion quality**: ✅ All assertions verify real behavior. Spot-checked tests use raising-property guards (`_HTMLBodyGuardMailItem`, `_AssertingMailItem`) rather than passive mocks to prove non-access, and multi-item fixtures with deliberately mixed pass/fail cases (e.g. the Restrict-skip test's 4-item fixture) rather than single trivially-true assertions.

---

## Quality Metrics

**Linter**: Not available (no ruff/flake8/pylint configured)
**Type Checker**: Not available (no mypy/pyright configured)

---

## Spec Compliance Matrix

### mail-search

| Requirement | Scenario | Test | Result |
|-------------|----------|------|--------|
| Search Input Parameters | Valid folder and date range provided | `test_mail_tools.py::test_search_valid_folder_and_date_range` | ✅ COMPLIANT |
| Search Input Parameters | All optional filters omitted is rejected | `test_mail_tools.py` (mandatory-filter test, pre-existing, unchanged) | ✅ COMPLIANT |
| Search Input Parameters | Neither or both of folder/folderPath is rejected | `test_schemas.py` (both-rejected / neither-rejected validator tests) | ✅ COMPLIANT |
| Search Input Parameters | folderPath alone satisfies the exclusivity rule | `test_mail_tools.py::test_search_folder_path_passed_through_to_adapter`; `test_server.py::test_mail_search_tool_folder_path_returns_results_via_fake_mail_adapter` | ✅ COMPLIANT |
| Search Input Parameters | Backward-compatible folder=inbox/sent calls are unchanged | `test_mail_tools.py::test_search_folder_inbox_and_sent_backward_compatible`; `test_mail_adapter.py::test_inbox_sent_backward_compatible_no_regression`; `test_server.py::test_mail_search_tool_returns_results_via_fake_mail_adapter` | ✅ COMPLIANT |
| Folder-Dependent Date Filtering | Sent-folder search filters on SentOn via mocked Restrict | `test_mail_adapter.py` (pre-existing sent-Restrict test, unchanged) | ✅ COMPLIANT |
| Folder-Dependent Date Filtering | Drafts-folder search filters on LastModificationTime | `test_mail_adapter.py::test_drafts_search_uses_get_default_folder_16_and_restricts_on_last_modification_time` | ✅ COMPLIANT |
| folderPath Resolution Failure | Unknown path segment yields a typed error | `test_mail_adapter.py::test_folder_path_unresolved_segment_raises_mail_folder_not_found_error`; `test_server.py::test_mail_search_tool_folder_path_unresolved_returns_mail_folder_not_found_error` | ✅ COMPLIANT |

### mail-get-detail

| Requirement | Scenario | Test | Result |
|-------------|----------|------|--------|
| Get Message Input/Output | Successful fetch (backward-compatible default) | `test_mail_tools.py::test_get_message_default_omits_html_body_backward_compatible`; `test_server.py::test_mail_get_message_tool_default_omits_html_body_backward_compatible` | ✅ COMPLIANT |
| Get Message Input/Output | includeHtmlBody=true returns the HTML body | `test_mail_tools.py::test_get_message_include_html_body_threaded_to_adapter`; `test_server.py::test_mail_get_message_tool_include_html_body_returns_html_body`; `test_mail_adapter.py::test_html_body_read_when_include_html_true_body_unaffected` | ✅ COMPLIANT |
| Get Message Input/Output | No attachments yields an empty attachmentNames list | `test_mail_adapter.py::test_attachment_names_empty_when_count_zero`; `test_fake_mail_adapter.py` (default attachment_names test) | ✅ COMPLIANT |

### outlook-mail-adapter

| Requirement | Scenario | Test | Result |
|-------------|----------|------|--------|
| Adapter Interface | Fake adapter satisfies the interface | `test_fake_mail_adapter.py` (drafts + folder_path + include_html tests, collectively) | ✅ COMPLIANT |
| Real Adapter COM Access Per Folder | Inbox search restricts on ReceivedTime | `test_mail_adapter.py` (pre-existing, unchanged) | ✅ COMPLIANT |
| Real Adapter COM Access Per Folder | Sent search restricts on SentOn | `test_mail_adapter.py` (pre-existing, unchanged) | ✅ COMPLIANT |
| Real Adapter COM Access Per Folder | Drafts resolves via GetDefaultFolder(drafts_folder_id) and restricts on LastModificationTime | `test_mail_adapter.py::test_drafts_search_uses_get_default_folder_16_and_restricts_on_last_modification_time` | ✅ COMPLIANT |
| Real Adapter COM Access Per Folder | folder_path traverses named subfolders within the default store | `test_mail_adapter.py::test_folder_path_traverses_default_store_root_via_per_segment_folders_item` | ✅ COMPLIANT |
| Real Adapter COM Access Per Folder | folder_path search skips Restrict() and filters dates via the fallback chain | `test_mail_adapter.py::test_folder_path_search_skips_restrict_and_filters_dates_in_python_via_fallback_chain` | ✅ COMPLIANT |
| Real Adapter COM Access Per Folder | Missing folder_path segment raises MailFolderNotFoundError | `test_mail_adapter.py::test_folder_path_unresolved_segment_raises_mail_folder_not_found_error` | ✅ COMPLIANT |
| COM Failure Mapping | Dispatch failure raises a typed error | `test_mail_adapter.py` (pre-existing, unchanged) | ✅ COMPLIANT |
| COM Failure Mapping | Unknown entryId raises MessageNotFoundError | `test_mail_adapter.py` (pre-existing, unchanged) | ✅ COMPLIANT |
| Read-Only Contract | get_message issues no mutating COM calls | `test_mail_adapter.py::test_no_mutating_com_calls_across_search_traversal_and_get_message` (extends pre-existing `test_no_mutating_com_calls_issued_on_get_message`) | ✅ COMPLIANT |
| Attachment Filename Enumeration | Enumerates filenames in 1-indexed order | `test_mail_adapter.py::test_attachment_names_enumerated_1_indexed` | ✅ COMPLIANT |
| Attachment Filename Enumeration | No attachments yields an empty list | `test_mail_adapter.py::test_attachment_names_empty_when_count_zero` | ✅ COMPLIANT |
| HTMLBody Read Only When Requested | HTMLBody is not accessed by default | `test_mail_adapter.py::test_html_body_not_accessed_unless_include_html_true` | ✅ COMPLIANT |
| HTMLBody Read Only When Requested | HTMLBody is read when requested | `test_mail_adapter.py::test_html_body_read_when_include_html_true_body_unaffected` | ✅ COMPLIANT |
| Date Resolution Fallback Chain | Draft with no ReceivedTime/SentOn falls back to LastModificationTime | `test_mail_adapter.py::test_resolve_date_falls_back_to_last_modification_time_when_received_and_sent_on_absent` | ✅ COMPLIANT |
| Date Resolution Fallback Chain | Custom folder item with ReceivedTime present uses it first | `test_mail_adapter.py::test_resolve_date_falls_back_to_last_modification_time_when_received_and_sent_on_absent` (same test, ReceivedTime-present half); reinforced by `test_folder_path_search_skips_restrict_and_filters_dates_in_python_via_fallback_chain`'s in-range-via-ReceivedTime items | ✅ COMPLIANT |

### smoke-test-coverage

| Requirement | Scenario | Test | Result |
|-------------|----------|------|--------|
| Per-Family Live Steps and Search-and-Chain | Search hit chains the detail call | `test_smoke_test.py` (generic `run_family` test, pre-existing, unchanged) | ✅ COMPLIANT |
| Per-Family Live Steps and Search-and-Chain | Empty search result passes without chaining | `test_smoke_test.py` (generic `run_family` test, pre-existing, unchanged) | ✅ COMPLIANT |
| Per-Family Live Steps and Search-and-Chain | Initialize failure short-circuits all families | `test_smoke_test.py` (pre-existing, unchanged) | ✅ COMPLIANT |
| Per-Family Live Steps and Search-and-Chain | mail-drafts family with zero hits passes without chaining | `test_smoke_test.py::test_mail_drafts_family_zero_hits_passes_without_chaining` | ✅ COMPLIANT |
| Per-Family Live Steps and Search-and-Chain | mail-drafts family with a hit chains mail_get_message | `test_smoke_test.py::test_mail_drafts_family_hit_chains_mail_get_message` | ✅ COMPLIANT |

**Compliance summary**: 29/29 scenarios compliant across all 4 delta specs. 0 FAILING, 0 UNTESTED, 0 PARTIAL.

---

## Correctness (Static — Structural Evidence)

| Requirement | Status | Notes |
|------------|--------|-------|
| `MailFolder.DRAFTS` | ✅ Implemented | `models/schemas.py:116` |
| `folder`/`folderPath` exclusivity validator | ✅ Implemented | `models/schemas.py:170-174`, `model_validator(mode="after")`, matches design.md's code sketch verbatim |
| `MailFolderNotFoundError` | ✅ Implemented | `tools/errors.py:80-97`, carries `path`/`failing_segment`, code `mail_folder_not_found` |
| `folder_path` traversal rooted at `DefaultStore.GetRootFolder()` | ✅ Implemented | `tools/mail_adapter.py:175-195` (`_resolve_folder_path`), never touches `namespace.Folders` directly |
| No `Restrict()` for folder_path, Python date filtering via fallback chain | ✅ Implemented | `tools/mail_adapter.py:282-298` (folder_path branch fetches `.Items` directly, skips Restrict); `_matches_date_bounds` (:154-172) applies bounds in Python |
| Mapped folders keep single-field Restrict (backward compat) | ✅ Implemented | `tools/mail_adapter.py:299-318` (else branch, byte-for-byte pre-existing `GetDefaultFolder`/`Restrict()` logic per apply-progress) |
| Attachment 1-indexed enumeration | ✅ Implemented | `tools/mail_adapter.py:376-379`, `range(1, item.Attachments.Count + 1)` |
| HTMLBody gating | ✅ Implemented | `tools/mail_adapter.py:383`, `item.HTMLBody if include_html else None` |
| `drafts_folder_id` settings key | ✅ Implemented | `config/settings.yaml:34`, value `16` |
| `mail-drafts` smoke family, EXPECTED_TOOLS unchanged | ✅ Implemented | `deploy/smoke_test.py:439-446` (family), `:50-58` (EXPECTED_TOOLS, still 7 entries, unchanged), verdict strings at `:89-93` unchanged |
| server.py wiring (Phase 7 amendment) | ✅ Implemented | `server.py:213-255`, `folder_path`/`include_html_body` exposed at the tool boundary; `MailSearchRequest(...)` construction moved inside `try:` |

---

## Coherence (Design)

| Decision | Followed? | Notes |
|----------|-----------|-------|
| Path root: `DefaultStore.GetRootFolder()` | ✅ Yes | `_resolve_folder_path` uses exactly this, never `namespace.Folders` |
| Segment resolution via `.Item(name)` per segment | ✅ Yes | `current.Folders.Item(segment)` inside per-segment try/except |
| folderPath date filtering skips Restrict(), Python-filters via fallback chain | ✅ Yes | Confirmed in code and by `items.Restrict.assert_not_called()` in tests |
| `search()` signature: `folder_path` alongside `folder`, exclusivity enforced once at schema | ✅ Yes | `MailPort.search()` signature matches design.md's Interfaces/Contracts verbatim |
| Exclusivity + errors via `model_validator` + `MailFolderNotFoundError` | ✅ Yes | Matches design.md's code sketch verbatim |
| Drafts date field: `[LastModificationTime]` | ✅ Yes | `_FOLDER_MAP[DRAFTS]` matches exactly |
| Attachment names: 1-indexed, `FileName` | ✅ Yes | Matches exactly |
| HTML body opt-in | ✅ Yes | Matches exactly |
| "server.py needs no change" (original design.md claim) | ⚠️ Superseded | Phase 7 amendment closed a real gap (folderPath/includeHtmlBody unreachable from an MCP client). This is an orchestrator-authorized amendment addressing a documented, previously-flagged gap — treated per the verification brief as a documentation-alignment SUGGESTION, not a deviation defect. `_map_error` itself was confirmed unchanged, so the narrower part of the original claim (no new error-mapping branch needed) held true. |

---

## Read-Only Contract & Import Safety

- `grep -n "\.Save(\|\.Move(\|\.Delete(\|UnRead" tools/mail_adapter.py` → no matches. No mutating COM member is called in `search()`, `get_message()`, or `_resolve_folder_path()`.
- `grep` for module-level `win32com`/`pythoncom` imports across `tools/mail_adapter.py`, `tools/fake_mail_adapter.py`, `tools/mail.py`, `server.py` → only lazy imports inside `OutlookMailAdapter._dispatch_outlook()` (pre-existing) and docstring prose in `server.py`. No module-level import.
- Confirmed via dedicated test: `test_no_mutating_com_calls_across_search_traversal_and_get_message` exercises both folder_path search and `get_message(include_html=True)` over `_AssertingMailItem`/`_HTMLBodyGuardMailItem` instances that raise on any mutating-member access.

---

## Backward Compatibility

- `folder="inbox"`/`folder="sent"` behavior unchanged: `test_inbox_sent_backward_compatible_no_regression` (adapter layer), `test_search_folder_inbox_and_sent_backward_compatible` (tools layer), `test_mail_search_tool_returns_results_via_fake_mail_adapter` (server layer, pre-existing test reused unchanged) — all pass.
- Default `mail_get_message` (no `includeHtmlBody`) omits `htmlBody`: `test_get_message_default_omits_html_body_backward_compatible` (tools layer), `test_mail_get_message_tool_default_omits_html_body_backward_compatible` (server layer) — both pass.
- Mapped-folder date extraction (`ReceivedTime`/`SentOn` direct field access, no fallback) is unchanged for inbox/sent — guarded explicitly by `test_inbox_sent_backward_compatible_no_regression`, which deliberately leaves the *other* folder's date field unset so an accidental switch to the fallback chain would surface as a wrong value rather than silently passing.
- Full suite: 220/220 passing, zero regressions from the 174-test pre-change baseline.

---

## Issues Found

**CRITICAL** (must fix before archive): None

**WARNING** (should fix): None

**SUGGESTION** (nice to have):
1. design.md's "Technical Approach" section still reads "`server.py` needs no change" — this is now superseded by the Phase 7 amendment and should be updated for future readers of design.md, even though tasks.md's Phase 7 preamble already documents the correction. Low priority; does not block archive.
2. The `LastModificationTime`-for-drafts assumption and the live `mail-drafts` smoke family are unverified against real Outlook — both are explicitly called out in tasks.md's closing note and apply-progress as pending manual validation at the upcoming combined deploy on the Windows host. This is a known, accepted residual item, not a defect.

---

## Verdict

**PASS**

All 29 spec scenarios across the 4 delta specs (mail-search, mail-get-detail, outlook-mail-adapter, smoke-test-coverage) are COMPLIANT with passing tests as evidence. Full suite is green at 220/220 (exact match to the expected count), zero regressions from the 174-test baseline. Strict TDD compliance is 6/6 — every implementation task has RED→GREEN evidence, adequate triangulation, and no trivial/tautological assertions were found across the 3,202 lines of test files touched. The read-only contract holds (no mutating COM members, no module-level win32com/pythoncom imports). Backward compatibility for folder=inbox/sent and default (no includeHtmlBody) detail calls is explicitly regression-tested and passing. The Phase 7 server-wiring amendment is a documented, orchestrator-authorized scope closure (not a deviation defect) that makes folderPath/includeHtmlBody actually reachable from an MCP client — its only fallout is a stale sentence in design.md, flagged above as a SUGGESTION. No CRITICAL or WARNING findings. Ready for archive once the two residual manual/documentation items are acknowledged by the orchestrator.
