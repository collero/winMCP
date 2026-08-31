# Archive Report: mail-reading-depth

**Change**: mail-reading-depth  
**Archived to**: `openspec/changes/archive/2026-08-24-mail-reading-depth/`  
**Archive Date**: 2026-08-24  
**Verification Status**: PASS (220/220 tests, all scenarios compliant)

---

## Specs Synced and Merged

Four delta specs were merged into the main source-of-truth specs. All pre-existing requirements preserved; MODIFIED requirements replaced with delta versions (stripped of "(Previously: ...)" provenance notes); ADDED requirements appended to their respective domain sections.

| Domain | Action | Replaced | Added | Details |
|--------|--------|----------|-------|---------|
| `mail-search` | MERGED | 2 requirements | 1 requirement | "Search Input Parameters" (folder/folderPath exclusivity, drafts support) + "Folder-Dependent Date Filtering" (drafts, folderPath Python filtering) + NEW "folderPath Resolution Failure" |
| `mail-get-detail` | MERGED | 1 requirement | 0 requirements | "Get Message Input/Output" (added includeHtmlBody param, htmlBody/attachmentNames outputs) |
| `outlook-mail-adapter` | MERGED | 4 requirements | 3 requirements | "Adapter Interface" (folder_path, include_html_body) + "Real Adapter COM Access Per Folder" (drafts, folder_path traversal, Python fallback chain) + "COM Failure Mapping" (MailFolderNotFoundError) + "Read-Only Contract" (scope expanded) + NEW "Attachment Filename Enumeration" + NEW "HTMLBody Read Only When Requested" + NEW "Date Resolution Fallback Chain" |
| `smoke-test-coverage` | MERGED | 1 requirement | 0 requirements | "Per-Family Live Steps and Search-and-Chain" (added mail-drafts family: 5 families now instead of 4) |

**Merge Validation**:
- ✅ All pre-existing requirements in each main spec remain present and unchanged (except those in MODIFIED list)
- ✅ MODIFIED requirements replaced entirely; "(Previously: ...)" notes stripped per convention
- ✅ ADDED requirements appended to Requirements section in correct order
- ✅ Markdown formatting and heading hierarchy preserved
- ✅ No destructive changes; all prior content intact

**Merge Details by Domain**:

### mail-search/spec.md
- **MODIFIED "Search Input Parameters"**: Now accepts optional `folder` (inbox/sent/drafts) and `folderPath` (mutually exclusive), with exclusivity validation before adapter call. Added 5 new scenarios covering folder-only, folderPath-only, both-omitted, both-present, and backward-compatibility cases.
- **MODIFIED "Folder-Dependent Date Filtering"**: Extended DASL field selection to include `[LastModificationTime]` for drafts; added Python-side date filtering for folderPath folders via fallback chain (ReceivedTime → SentOn → LastModificationTime). Added 2 scenarios (drafts Restrict, folder_path fallback skip).
- **ADDED "folderPath Resolution Failure"**: New error handling requirement; tool must surface `mail_folder_not_found` error with code when folderPath segment unresolved. 1 scenario covering unknown path segment.
- **Preserved**: Purpose, Default Date Bounds, Sender Filter Is Folder-Dependent, Search Output Shape, Outlook Unavailable (all 5 untouched).

### mail-get-detail/spec.md
- **MODIFIED "Get Message Input/Output"**: Added `includeHtmlBody` input parameter (boolean, optional, default false). Added `htmlBody` output field (None unless includeHtmlBody=true), and `attachmentNames` output list (always present, empty if no attachments). Added 3 scenarios covering backward-compatible default, includeHtmlBody=true, and no-attachments cases.
- **Preserved**: Purpose, Message Not Found, Empty Body Handling, Outlook Unavailable, No Mutation on Fetch (all 5 untouched).

### outlook-mail-adapter/spec.md
- **MODIFIED "Adapter Interface"**: Signature now includes `folder_path` parameter and `include_html_body` parameter; `MessageDetail` carries `attachment_names` and `html_body`. 1 scenario updated to cover both folder and folder_path usage.
- **MODIFIED "Real Adapter COM Access Per Folder"**: Major expansion to cover drafts (GetDefaultFolder(drafts_folder_id, default 16)), folder_path traversal (walk `/`-delimited segments from store top), drafts DASL on LastModificationTime, and Python-side date filtering for folder_path via fallback chain. Added 4 scenarios (drafts Restrict, folder_path traversal, folder_path fallback filtering, folder_path error).
- **MODIFIED "COM Failure Mapping"**: Extended to include `MailFolderNotFoundError` (code `mail_folder_not_found`) for unresolved folder_path segments. Removed separate COM Failure Mapping scenario placeholder (error type exercised via folder_path scenario above, per delta convention).
- **MODIFIED "Read-Only Contract"**: Expanded scope to explicitly cover folder/path traversal and attachment/HTMLBody reads; assertion now covers `Attachments` collection and traversed folders, not just item access.
- **ADDED "Attachment Filename Enumeration"**: Enumerates attachment filenames using 1-indexed Outlook COM access (Item(1)..Item(Count)), returns [] when empty. Detail-only (MessageSummary unaffected). 2 scenarios.
- **ADDED "HTMLBody Read Only When Requested"**: HTMLBody accessed only when include_html_body=true; else html_body is None. Body always read independent of include_html_body flag. 2 scenarios.
- **ADDED "Date Resolution Fallback Chain"**: Defines date resolution order (ReceivedTime → SentOn → LastModificationTime) for drafts and folder_path folders; first non-null value used after timezone normalization; same order applied in search() and get_message(). Used as filtering criterion in Python-side date filtering for folder_path. 2 scenarios.
- **Preserved**: Purpose, Lazy COM Import, Non-MailItem Guard, COM Datetime Normalization, Adapter Selection at Runtime (all 5 untouched).

### smoke-test-coverage/spec.md
- **MODIFIED "Per-Family Live Steps and Search-and-Chain"**: Expanded from 4 to 5 families by adding `mail_search folder="drafts"` with a date bound. All search results chain detail call per existing rule; 0 hits passes with note (unchanged for mail-drafts). Added 2 scenarios (mail-drafts zero-hit pass, mail-drafts hit chains mail_get_message).
- **Preserved**: Purpose, Expected Tool Set, Per-Family Verdict Classification, Pure Aggregate Verdict Function, Human-Eyeball-Friendly Output, Live Execution Is Manual-Verification-Only (all 6 untouched).

---

## Archive Contents

All SDD artifacts present and verified:

- **proposal.md** ✅ — defines scope (drafts folder support, custom folder paths, HTML body + attachment details) and risks
- **specs/** ✅ — 4 delta specs (mail-search, mail-get-detail, outlook-mail-adapter, smoke-test-coverage)
- **design.md** ✅ — technical design with sequence diagrams and rationale
- **tasks.md** ✅ — 32/32 checklist items completed (7 phases including Phase 7 server.py amendment)
- **apply-progress.md** ✅ — 3 batches with TDD Cycle Evidence tables (RED/GREEN/TRIANGULATE/REFACTOR per task), 46 new tests added (174→220 total)
- **verify-report.md** ✅ — PASS verdict, 220/220 tests, all 7 scenarios per spec compliant per verify-report, 6/6 TDD checks passed

---

## Source of Truth Updated

The following main specs now reflect the mail-reading-depth changes:

1. `/home/master/WinMCP/openspec/specs/mail-search/spec.md` — Updated with drafts folder, folderPath parameter, and error handling
2. `/home/master/WinMCP/openspec/specs/mail-get-detail/spec.md` — Updated with includeHtmlBody, htmlBody, attachmentNames outputs
3. `/home/master/WinMCP/openspec/specs/outlook-mail-adapter/spec.md` — Updated with drafts, folder_path, attachment enumeration, HTMLBody conditional reads, date resolution fallback chain
4. `/home/master/WinMCP/openspec/specs/smoke-test-coverage/spec.md` — Updated with mail-drafts family in smoke test

All specs are now the authoritative source for mail-reading-depth behavior.

---

## Verification Summary

**Result**: PASS (220/220 tests, all spec scenarios compliant, zero blockers)

| Metric | Value | Status |
|--------|-------|--------|
| Tests | 220 total (46 new), all passed | ✅ Suite green 220/220 |
| Tasks | 32/32 completed (7 phases) | ✅ Complete |
| Spec Compliance | All scenarios in all 4 deltas tested and passing | ✅ Full compliance |
| TDD Compliance | 6/6 checks (RED, GREEN, TRIANGULATE, REFACTOR, backward-compat) | ✅ Full compliance |
| Scenario Coverage | 18 spec scenarios verified across 4 domains | ✅ All 18 passing |

**Key Implementation Highlights**:
- Mail search now supports drafts folder via GetDefaultFolder(drafts_folder_id default 16)
- Custom folder paths (folderPath) resolved by walking segments from store root, with proper error handling (MailFolderNotFoundError)
- Python-side date filtering for custom folders via fallback chain (ReceivedTime → SentOn → LastModificationTime)
- get_message() now populates attachmentNames (1-indexed enumeration) always, and htmlBody conditionally when includeHtmlBody=true
- All reads are read-only (no mutating COM calls on items, attachments, or traversed folders)
- Smoke test expanded to 5 families, including mail-drafts search-and-chain
- Phase 7 server.py wiring added (orchestrator amendment for actual tool integration) with full TDD coverage

**Test Execution Evidence** (from verify-report):
- Baseline: 174 tests (from prior changes)
- New tests: 46 (all 3 batches)
- Final suite: 220/220 passing (zero regressions)
- TDD cycle evidence: RED/GREEN/TRIANGULATE confirmed per task; backward-compatibility tested

---

## Monday.com Integration

**Status**: SKIPPED — Monday integration disabled for this change per orchestrator settings. No item id provided; no closeout required.

---

## Archive Structure

```
openspec/changes/archive/2026-08-24-mail-reading-depth/
├── proposal.md
├── specs/
│   ├── mail-search/
│   │   └── spec.md (delta spec, 2 MODIFIED + 1 ADDED)
│   ├── mail-get-detail/
│   │   └── spec.md (delta spec, 1 MODIFIED)
│   ├── outlook-mail-adapter/
│   │   └── spec.md (delta spec, 4 MODIFIED + 3 ADDED)
│   └── smoke-test-coverage/
│       └── spec.md (delta spec, 1 MODIFIED)
├── design.md (technical design with rationale)
├── tasks.md (32/32 completed, Phase 7 amendment included)
├── apply-progress.md (3 batches, TDD evidence, 220/220 final)
├── verify-report.md (PASS, all scenarios compliant)
└── archive-report.md (this file)
```

---

## SDD Cycle Complete

✅ **Planned** (Proposal + Design + Risk Assessment)  
✅ **Implemented** (32 tasks across 7 phases, 46 new tests, strict TDD)  
✅ **Verified** (PASS, 220/220 tests, all scenarios compliant, zero blockers)  
✅ **Archived** (4 delta specs merged into 4 main specs, change folder moved, audit trail written)

The mail-reading-depth change is complete and production-ready. All four main specs are now authoritative for the new mail-reading features (drafts, custom folders, HTML bodies, attachment details).

**Archived by**: sdd-archive phase  
**SDD Mode**: openspec (file-based, committable)  
**SDD Version**: 1.0  
**Archive Date**: 2026-08-24 ISO format  
