# Archive Report: outlook-tasks-todo

**Change**: outlook-tasks-todo  
**Archived**: 2026-08-24  
**Artifact Store Mode**: openspec  
**Verification Result**: PASS_WITH_WARNINGS  

---

## Archive Completion Summary

This SDD change implements **Outlook Tasks / Microsoft To Do read-only support** for the WinMCP MCP server, adding a second tool domain alongside the calendar MVP.

### Scope
- **New Tools**: `task_search` (list tasks with optional filters), `task_get_task` (fetch full task detail by ID)
- **New Adapter**: `OutlookTaskAdapter` behind a `TaskPort` protocol, mirroring `outlook-com-adapter` for loose coupling to Windows COM
- **Supporting Code**: Task error types, schemas (status enum, summary/detail DTOs), fake adapter for testing
- **TDD Evidence**: 6 completed phases + 1 orchestrator-directed amendment (due-date sentinel normalization); 34/34 tasks complete

---

## Specs Synced to Main Specs Directory

| Domain | Action | File | Details |
|--------|--------|------|---------|
| outlook-tasks-adapter | Created | `/home/master/WinMCP/openspec/specs/outlook-tasks-adapter/spec.md` | 6.2 KB; defines TaskPort protocol, lazy COM import, status mapping, due-date sentinel normalization, adapter selection rules |
| task-search | Created | `/home/master/WinMCP/openspec/specs/task-search/spec.md` | 4.4 KB; specifies all-optional search filters (due-date range, subject, status), includeNoDueDate behavior, output shape |
| task-get-detail | Created | `/home/master/WinMCP/openspec/specs/task-get-detail/spec.md` | 2.6 KB; specifies task detail fetch by entryId, status/complete consistency, error cases |

**No destructive deltas**: All three specs are new domains. No modifications to existing specs (`mcp-server-bootstrap`, `outlook-com-adapter`, or calendar specs). Merge strategy: copy as-is (not merge).

---

## Archive Contents

```
2026-08-24-outlook-tasks-todo/
├── proposal.md              (intent, scope, rollback strategy)
├── design.md                (architecture, COM seams, test strategy, amendment notes)
├── tasks.md                 (34 tasks across 6 phases + 1 amendment: schemas, fake adapter, tools, real adapter, server wiring)
├── specs/
│   ├── outlook-tasks-adapter/
│   │   └── spec.md          (TaskPort protocol, COM access, status mapping, due-date sentinel handling)
│   ├── task-search/
│   │   └── spec.md          (search input/output, optional filters, includeNoDueDate semantics)
│   └── task-get-detail/
│       └── spec.md          (get-by-id, error handling, status/complete consistency)
├── apply-progress.md        (4 batches + 1 amendment; baseline progression: 9/9 → 45/45 → 64/64 → 76/76 → 83/83 → 85/85 → 88/88 tests)
├── verify-report.md         (PASS_WITH_WARNINGS; 88/88 tests pass; 21/21 spec scenarios compliant; 1 unrelated pre-existing calendar test now fails on full suite due to wall-clock date)
└── archive-report.md        (this file)
```

---

## Test Results at Archive Time

**Full Suite**: 88 tests total
- **Passed**: 87
- **Failed**: 1 (pre-existing, out-of-scope calendar fixture)
- **Task-feature-scoped run**: 43/43 passed ✅

**TDD Compliance**: ✅ All 21 spec scenarios across all three new specs pass under real execution.

**Coverage**: Not available (pytest-cov not installed; config threshold = 0).

---

## Source of Truth Updated

The following specs are now persisted in `/home/master/WinMCP/openspec/specs/` as the source of truth for task tool behavior:

1. **`outlook-tasks-adapter/spec.md`** — TaskPort protocol, COM adapter requirements, lazy import, status/due-date normalization
2. **`task-search/spec.md`** — Search tool interface, filter semantics, output schema
3. **`task-get-detail/spec.md`** — Get-detail tool interface, consistency invariants, error cases

All source code in `/home/master/WinMCP/` (server.py, tools/, models/, config/) is versioned via git and implements these specs. The delta specs from the change are now integrated into the main specs directory and serve as the permanent architectural reference.

---

## Verification Notes

**PASS_WITH_WARNINGS** verdict was issued in `verify-report.md` with the following findings:

### Warnings (non-blocking, pre-existing or out-of-scope)

1. **Unrelated calendar test now fails on full-suite run** — `tests/test_server.py::test_calendar_search_tool_returns_results_via_fake_adapter` fails with `IndexError: list index out of range` because its hardcoded fixture date (`2026-07-27`) has fallen outside the 7-day lookback window from today (`2026-08-24`). This is a latent, wall-clock-dependent bug in the **calendar MVP's test suite** (not touched by this change; confirmed: no calendar source files were modified). Recommend a separate fix (compute fixture date relative to `datetime.now()`, or freeze time in test).

2. **Inert config settings** — `config/settings.yaml` contains `tasks_folder_id` and `calendar_folder_id`, but these are not read by the adapter code (hardcoded defaults are used instead). This is a pre-existing pattern, not a regression, and was already noted in `apply-progress.md`.

### Suggestions (nice-to-have)

- Update `pyproject.toml`'s `[project].description` to mention `task_search`/`task_get_task` tools (currently only mentions calendar tools).
- Wire `tasks_folder_id`/`calendar_folder_id` from settings into adapter constructors in a future change (currently unused but documented).

---

## Monday.com Integration

**DISABLED** for this project — no Monday.com tracking performed. Archive is complete without Monday closeout steps.

---

## Archive Finalization

- ✅ All delta specs copied to main specs directory
- ✅ Change folder moved to archive with date prefix `2026-08-24-`
- ✅ Archive location verified: `/home/master/WinMCP/openspec/changes/archive/2026-08-24-outlook-tasks-todo/`
- ✅ Active changes directory no longer contains `outlook-tasks-todo` (confirmed via move)
- ✅ All artifacts preserved (proposal, design, tasks, specs, apply-progress, verify-report, archive-report)

**SDD Cycle Complete** — this change is fully planned, implemented, verified, and archived. The Outlook Tasks / Microsoft To Do functionality is now part of the permanent WinMCP specification and implementation.

---

**Archived by**: sdd-archive executor  
**Date**: 2026-08-24  
**Mode**: openspec (file-based)
