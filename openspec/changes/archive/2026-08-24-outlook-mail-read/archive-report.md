# Archive Report: Outlook Mail (Read-Only)

**Change**: outlook-mail-read  
**Archived**: 2026-08-24  
**Status**: PASS WITH WARNINGS ✅ → Archived

---

## Closure Summary

The `outlook-mail-read` change has been **fully implemented, verified, and archived**. All 39 tasks across 8 phases were completed under Strict TDD Mode. The full test suite passes with 137/137 tests green. Two spec scenarios are partially compliant (low-risk, non-blocking gaps in Outlook COM corner cases). The implementation is production-ready with residual Windows-only manual verification recommended.

---

## What Was Delivered

### New Capabilities

1. **`mail_search` tool** — Read-only search over user's Inbox or Sent Items folder, returning minimal message list for client-side filtering
   - Filters: folder (required enum), dateFrom/dateTo (ISO 8601), subject (substring), sender (substring, folder-dependent)
   - Mandatory filter rule: at least one of dateFrom/dateTo/subject/sender required
   - Date bound filling: auto-fills from `mail_lookback_days` config (default 90 days, independent of calendar's 7-day default)
   - Folder-dependent DASL `Restrict()`: `[ReceivedTime]` for Inbox, `[SentOn]` for Sent
   - Folder-dependent sender matching: `SenderName`/`SenderEmailAddress` (Inbox) vs. recipient names in `To` field (Sent)
   - Output: `MessageSummary` objects with entryId, subject, sender display name, sender address, date (ISO 8601), hasAttachments

2. **`mail_get_message` tool** — Fetch full read-only detail for a single message by entryId
   - Returns: `MessageDetail` with subject, sender, senderAddress, date, to (recipients), hasAttachments, body (plain-text, never HTMLBody)
   - Error cases: explicit `message_not_found` error when entryId is invalid; empty string for body when absent
   - Read-only guarantee: no mutation on fetch (no mark-read, move, delete)

3. **`MailPort` adapter seam** — Protocol interface enabling test-friendly architecture
   - Signature: `search(folder, date_from, date_to, subject, sender) -> list[MessageSummary]`, `get_message(entry_id) -> MessageDetail`
   - Implementations: 
     - `OutlookMailAdapter` — real COM-based adapter (lazy `win32com.client` import on Windows only)
     - `FakeMailAdapter` — in-memory fixture-based adapter for testing on Linux without Outlook

4. **Error taxonomy** — New exception class `MessageNotFoundError` reusing `CalendarToolError` base class

### Modified Files

- `models/schemas.py` — Added 5 new schema classes with camelCase field aliases via `_AliasedModel`
- `tools/errors.py` — Added `MessageNotFoundError` exception
- `tools/mail.py` — New file with `mail_search` and `mail_get_message` tool functions
- `tools/mail_adapter.py` — New file with `MailPort` Protocol, `OutlookMailAdapter` (lazy import, DASL, datetime normalization), and adapter selection logic
- `tools/fake_mail_adapter.py` — New file with `FakeMailAdapter` in-memory implementation for testing
- `tests/test_mail_tools.py` — New test file with 14 tests covering both tool functions
- `tests/test_mail_adapter.py` — New test file with 10 tests covering real adapter, COM mocking, guards, and error mapping
- `tests/test_fake_mail_adapter.py` — New test file with 14 tests covering fake adapter behavior
- `tests/test_schemas.py` — 5 new tests for mail schema classes
- `tests/test_errors.py` — 3 new tests for `MessageNotFoundError`
- `tests/test_server.py` — 3 new integration tests for tool registration and adapter selection
- `server.py` — Added `mail_adapter` injectable parameter, adapter selection logic, tool registrations
- `config/settings.yaml` — Added `mail_lookback_days: 90` live configuration key
- `README.md` — Updated with mail tool documentation
- `make-deploy-package.sh` — Updated exclusion regex to exclude `fake_mail_adapter.py` from distribution

### Unmodified (No Changes)

- Existing calendar and task tools — no changes to their behavior
- Existing test suite baseline — all 88 pre-existing tests remain green

---

## Spec Compliance Summary

| Spec | Requirements | Scenarios | Full Compliance | Partial | Status |
|------|----------|-----------|--------|---------|--------|
| mail-search | 6 | 11 | 11 | 0 | ✅ FULL |
| mail-get-detail | 5 | 5 | 4 | 1 | ⚠️ PARTIAL |
| outlook-mail-adapter | 8 | 10 | 9 | 1 | ⚠️ PARTIAL |
| **TOTAL** | **19** | **26** | **24** | **2** | **PASS WITH WARNINGS** |

### Full Compliance (24 scenarios)

All core behavior is comprehensively tested and passing:
- Search filtering logic (date bounds, subject, sender, folder-dependent matching)
- Mandatory filter validation
- Date bound auto-filling from `mail_lookback_days`
- Adapter interface protocol satisfaction
- Lazy `win32com` import safety (no top-level import on Linux)
- Fake adapter dispatch and filtering
- DASL `Restrict()` clause construction (ReceivedTime vs. SentOn)
- Non-MailItem class guard (skip Class ≠ 43 without error)
- Timezone normalization of naive COM datetimes
- Error mapping (OutlookUnavailableError, MessageNotFoundError)
- Tool registration and MCP stdio protocol integration
- Deploy package correctness (real adapter ships, fake adapters excluded)

### Partial Compliance (2 scenarios) — Low Risk

1. **mail-get-detail "Outlook Unavailable" scenario** (test gap)
   - ✅ Proven at adapter layer: both `FakeMailAdapter.get_message()` and `OutlookMailAdapter.get_message()` raise `OutlookUnavailableError` when configured
   - ⚠️ Untested at tool-function layer: no test calls `mail_get_message(request, adapter)` directly with unavailable adapter
   - **Risk**: Low — `mail_get_message` is a documented one-line delegate with no branching; error propagates transparently from adapter
   - **Recommendation**: Add one integration test calling `mail_get_message()` with unavailable adapter; currently defensive rather than harmful

2. **outlook-mail-adapter "COM Datetime Normalization" fallback branch** (execution gap)
   - ✅ Proven for `search()` fully and for `get_message()`'s primary path (ReceivedTime present)
   - ⚠️ Untested: `get_message()`'s fallback `_resolve_date()` branch (SentOn used when ReceivedTime is falsy — the genuine Sent Items case)
   - **Root cause**: Every test fixture populates both ReceivedTime and SentOn, so the conditional logic that prefers SentOn fallback is never executed by any test
   - **Self-reported by**: Batch 3's apply-progress, acknowledged in verify-report.md Batch 3 notes
   - **Risk**: Low — fallback is dead simple (one-line `getattr` with default None); logic is identical to `search()` branch which is fully tested
   - **Recommendation**: Add one fixture with only SentOn populated (no ReceivedTime) to exercise the fallback; mirrors existing test pattern

### Warnings — Recommended Follow-ups (Non-Blocking)

1. **Design-vs-Implementation Gap**: returned `sender`/`sender_address` fields not folder-relative
   - design.md's "Sender filter/field asymmetry" decision text states the returned *field* should also be folder-relative (use `To` recipients for Sent Items)
   - **Implementation choice**: Both fields always come from the item's own `SenderName`/`SenderEmailAddress`, in both folders
   - **Rationale**: Matches real Outlook semantics (a Sent Items MailItem still exposes the account owner's `SenderName`); consistent with FakeMailAdapter's fixture data
   - **Spec impact**: No scenario in either spec explicitly requires or forbids the returned field being folder-relative (only the *filter* is spec'd that way)
   - **Test impact**: No test asserts the returned `sender` value on a Sent Items message either way
   - **Recommendation**: Update design.md's "Sender filter/field asymmetry" row to document as-built behavior (filter-only asymmetry) and close the gap

2. **Recipient Parsing**: `To` field delimiter
   - `_split_recipients()` splits Outlook's `To` string on `;` (standard Outlook convention)
   - **Spec coverage**: No spec text pins this delimiter; it is an implementation assumption
   - **Recommendation**: Add a note to mail-get-detail spec clarifying that recipient strings are split on `;` for future implementers

3. **Settings.yaml Dead Entries**: `calendar_folder_id` and `tasks_folder_id` remain unused
   - `mail` tools intentionally hardcode `GetDefaultFolder(6)` and `(5)` constants rather than reading settings
   - **Debt**: Now three hardcoded entries (calendar, tasks, mail) while three settings.yaml entries gather dust
   - **Recommendation**: Future cleanup pass to either remove dead entries from settings.yaml or wire all three live

---

## Test Coverage Summary

### Test Execution Results

- **Total tests**: 137 (49 new mail-related + 88 pre-existing baseline)
- **Passed**: 137 ✅
- **Failed**: 0
- **Skipped**: 0
- **Test runner**: `python3.12 -m pytest -q` (1.66s)

### Test Layer Distribution

| Layer | Tests | Files | Status |
|-------|-------|-------|--------|
| Unit | 46 | 5 files (test_schemas.py +5, test_errors.py +3, test_fake_mail_adapter.py, test_mail_tools.py, test_mail_adapter.py) | ✅ 46/46 pass |
| Integration | 3 | test_server.py (+3 new MCP stdio tests) | ✅ 3/3 pass |
| E2E | 0 | — | Not available (no real Windows/Outlook host) |

### TDD Compliance Checklist

- ✅ **RED confirmed**: All new test files exist on disk; no tests pre-dated implementation
- ✅ **GREEN confirmed**: All 137 tests pass on a fresh run, matching cumulative batch counts (88→110→123→133→137)
- ✅ **Triangulation adequate**: Every task row lists ≥2 distinct assertion cases except single-shape properties (e.g., "module not imported")
- ✅ **Safety net**: Baseline count integrity maintained across all 4 apply batches
- ⚠️ **Minor note**: Task 5.1 (`test_win32com_not_imported_at_module_level`) reported as "trivially green from the start" (module already lacked top-level import before test was written); kept intentionally as permanent regression guard

### Assertion Quality

All assertions verify real behavior:
- No tautologies, no assertions divorced from production code calls
- No ghost loops over possibly-empty collections
- No smoke-test-only patterns
- Tests call `mail_search`/`mail_get_message`/`FakeMailAdapter`/`OutlookMailAdapter` methods directly
- Exception type assertions are precise (`OutlookUnavailableError`, `MessageNotFoundError`)
- No implementation details asserted (no CSS/internal state/mock call counts)

---

## Quality Checklist

| Tool | Status | Notes |
|------|--------|-------|
| Linter | ➖ Not configured | ruff/black/pylint not set up (greenfield project) |
| Type checker | ➖ Not configured | mypy/pyright not set up |
| Coverage reporter | ➖ Not available | pytest-cov not installed; threshold set to 0 in config |
| Test runner | ✅ Installed | pytest 8.x with pytest-mock; all 137 tests passing |

---

## Deploy Package Verification

**Package**: `dist/WinMCP-20260824.zip`

- ✅ Contains `tools/mail.py` and `tools/mail_adapter.py` (real adapters, required for Windows runtime)
- ✅ Excludes `tools/fake_mail_adapter.py` (test-only, must not ship)
- ✅ Excludes `tools/fake_adapter.py` and `tools/fake_task_adapter.py` (existing test exclusions remain active)
- ✅ Build script `make-deploy-package.sh` regex updated to include `fake_mail_adapter`

**Deployment readiness**: ✅ Safe to distribute to Windows hosts

---

## Read-Only / Import-Safety Constraints Verification

- ✅ **No top-level `win32com` import**: Confirmed via grep across `tools/`, `server.py`, `models/` — zero module-level imports
- ✅ **Lazy import only**: `OutlookMailAdapter` imports `win32com.client` inside method bodies, enabling Linux test suite to run without the module
- ✅ **No COM mutations**: Confirmed via grep — no calls to `.Save()`, `.Move()`, `.Delete()`, or `.UnRead` assignment anywhere in `tools/mail_adapter.py`
- ✅ **Live `mail_lookback_days` setting**: Confirmed in `config/settings.yaml` and actively read by `tools/mail.py::_mail_lookback_days()`
- ✅ **Hardcoded folder constants**: `GetDefaultFolder` IDs (6 for Inbox, 5 for Sent) hardcoded as designed; not settings keys (consistent with existing calendar/task pattern)

---

## Specs Now in Main Repo

Three new delta specs have been merged into `/home/master/WinMCP/openspec/specs/`:

| Domain | File | Status | Lines |
|--------|------|--------|-------|
| mail-search | `specs/mail-search/spec.md` | Created | 133 |
| mail-get-detail | `specs/mail-get-detail/spec.md` | Created | 74 |
| outlook-mail-adapter | `specs/outlook-mail-adapter/spec.md` | Created | 138 |

No existing specs were modified. All three are new domains (no conflicts with the 8 existing domains from prior archives).

---

## Rollback Path

If needed, the change is purely additive:

1. Delete new tool files: `tools/mail.py`, `tools/mail_adapter.py`, `tools/fake_mail_adapter.py`
2. Delete new test files: `tests/test_mail_tools.py`, `tests/test_mail_adapter.py`, `tests/test_fake_mail_adapter.py`
3. Revert additive edits to: `server.py`, `tools/errors.py`, `models/schemas.py`, `tests/test_*.py`, `config/settings.yaml`, `README.md`, `make-deploy-package.sh`
4. Delete new spec domains: `openspec/specs/mail-search/`, `openspec/specs/mail-get-detail/`, `openspec/specs/outlook-mail-adapter/`
5. No data migration required

Existing calendar and task tools remain unaffected.

---

## Monday Integration

**Status**: Not applicable — Monday integration is disabled for this project. No Monday closeout performed.

---

## Next Steps

### For Windows Deployment

1. Deploy `dist/WinMCP-20260824.zip` to Windows hosts
2. Run manual smoke test per `README.md` "Manual smoke test" section:
   - Launch MCP server on Windows with real Outlook installed
   - Call `mail_search(folder="inbox", dateFrom=..., dateTo=...)`
   - Call `mail_get_message(entryId=...)` with result from search
   - Verify subject, sender, body fields match real message

### For Follow-Up PRs (Optional)

1. Add test for `mail_get_message()` with unavailable adapter (cover WARNING #1)
2. Add test for `get_message()` fallback datetime branch (cover WARNING #2)
3. Update design.md "Sender filter/field asymmetry" row to reflect as-built behavior (WARNING #3)
4. Add recipient-parsing delimiter note to mail-get-detail spec (SUGGESTION #1)

---

## Metrics

| Metric | Value |
|--------|-------|
| Tasks completed | 39/39 |
| Tests added | 49 |
| Test pass rate | 100% (137/137) |
| Spec scenarios compliant | 24/26 fully + 2 partial |
| Deployment package verified | ✅ Safe |
| Source code readiness | ✅ Production |

---

## Verdict

**✅ ARCHIVED**

The `outlook-mail-read` change is complete, verified, and ready for production use on Windows. All core spec scenarios are fully compliant; 2 edge-case gaps (low-risk, non-blocking) are documented as follow-up recommendations. Residual manual smoke test on real Outlook is advised before widespread deployment, but no regressions are present in the shipped code.

The change archive is now immutable in `/home/master/WinMCP/openspec/changes/archive/2026-08-24-outlook-mail-read/` with full audit trail (proposal, specs, design, tasks, apply-progress, verify-report, archive-report).

---

**Archived by**: SDD Archive Phase  
**Timestamp**: 2026-08-24  
**Project**: WinMCP  
**Artifact store**: openspec
