# Proposal: Outlook Tasks / Microsoft To Do (Read-Only)

## Intent

Extend WinMCP to the Outlook Tasks folder, where To Do items land via
Exchange sync — same zero-auth, local-COM pattern as calendar.

## Scope

### In Scope
- `task_search`, `task_get_task` — read-only, default Tasks folder
  (`GetDefaultFolder(13)`, olFolderTasks)
- Fields: subject, body, due date, status/completion, dates, entryId
- `TaskPort` adapter seam (real + fake), lazy `win32com` import
- Unit tests against the fake adapter first (Strict TDD)

### Out of Scope (future work)
- Write operations: creating, completing, updating tasks
- To Do-only features with no COM equivalent: My Day, steps/subtasks
- Non-default/shared task folders

## Capabilities

### New Capabilities
- `task-search`: filter Tasks folder by due-date range, subject, status
- `task-get-detail`: full detail for one task by `entryId`
- `outlook-tasks-adapter`: `TaskPort` Protocol + `OutlookTaskAdapter`
  (mirrors `outlook-com-adapter`) + `FakeTaskAdapter`

### Modified Capabilities
- None — additive; calendar tools/specs untouched

## Approach

Mirror calendar's architecture: `tools/tasks.py` calls `TaskPort`
(`tools/task_adapter.py`), implemented by `OutlookTaskAdapter` (lazy
import) and `FakeTaskAdapter` (test-only). `errors.py` gains task
errors, reusing `OutlookUnavailableError`. `schemas.py` gains task
schemas; `server.py` registers both tools.

## Affected Areas

| Area | Impact |
|------|--------|
| `tools/tasks.py` | New — tool functions |
| `tools/task_adapter.py` | New — `TaskPort` + real adapter |
| `tools/fake_task_adapter.py` | New — in-memory test fake |
| `tools/errors.py` | Modified — task error(s) |
| `models/schemas.py` | Modified — task schemas |
| `server.py` | Modified — register 2 tools |
| `config/settings.yaml` | Modified — `tasks_folder_id: 13` |
| `tests/` | New — task unit tests |
| `README.md` | Modified — move out of extensions list |
| `make-deploy-package.sh` | Modified — exclude new fake |

## Risks

| Risk | Lik. | Mitigation |
|------|------|------------|
| Fake adapter omitted from packaging exclusion | Med | Task to update `grep -vx` list |
| COM `Status` mismatched vs. To Do's model | Med | Document mapping in design |
| No-due-date tasks break mandatory date-range search | Med | Optional-inclusive due-date filter |
| No real Windows/Outlook to validate | High | Manual verification |

## Rollback Plan

Purely additive; no change to calendar behavior. Rollback = delete the 3
new `tools/*.py` files + new tests; revert additive edits to `errors.py`,
`schemas.py`, `server.py`, `settings.yaml`, `README.md`,
`make-deploy-package.sh` (or `git revert`). No data migration; calendar
tools unaffected.

## Dependencies

- None beyond calendar MVP's `pywin32`, `pytest`, `pytest-mock`

## Success Criteria

- [ ] `task_search`/`task_get_task` registered and callable over stdio
- [ ] Full suite green via `python3.12 -m pytest -q`, only `FakeTaskAdapter`
- [ ] No `win32com` import at module load time in any new file
- [ ] Manual Windows smoke test confirms a real To Do item resolves
