# Design: Outlook Tasks / Microsoft To Do (Read-Only)

## Technical Approach

Mirror the calendar MVP's seam exactly: `tools/tasks.py` validates input via
Pydantic schemas and calls a `TaskPort` Protocol (`tools/task_adapter.py`),
implemented by `OutlookTaskAdapter` (lazy `win32com` import, real COM) and
`FakeTaskAdapter` (`tools/fake_task_adapter.py`, in-memory, test-only).
`server.py` gains a second injectable adapter parameter and registers
`task_search` / `task_get_task`. Errors reuse the existing `CalendarToolError`
taxonomy (`tools/errors.py`) plus one new subclass, so `server.py`'s
`_map_error` needs **no changes** to handle task errors too.

## Architecture Decisions

| Decision | Choice | Alternatives considered | Rationale |
|---|---|---|---|
| **Status mapping (open Q1)** | `TaskStatus` str-enum mirrors COM's `OlTaskStatus` 1:1 (`not_started`, `in_progress`, `waiting`, `deferred`, `completed`). Separate `is_complete: bool` reads COM's `Complete` property directly; `Complete == True` forces `status = completed` regardless of raw `Status` (defensive normalization). | Expose raw `Status` int; drop enum, keep only `is_complete: bool` | To Do's UI only exposes a binary done/not-done toggle — `is_complete` is what most callers need — but Outlook desktop can still set richer states via COM, so the enum preserves them. `Complete` is the authoritative "done" flag (what the checkbox writes); trusting it over `Status` avoids surfacing a checked-off item as `waiting`. |
| **No-due-date search filtering (open Q2)** | `task_search` filters are **all optional**, unlike `calendar_search`'s "at least one required" rule. Due-date bounds are opt-in; when set, a task passes if `due_date` is in range **OR** (`due_date is None and include_no_due_date`, default `True`). No lookback-window defaulting. | Reuse calendar's mandatory-range + lookback-fill verbatim; default `include_no_due_date=False` | Tasks folders are bounded personal lists, not unbounded event streams — full scans are safe, so calendar's safety rail doesn't apply. Most To Do items never get a due date; defaulting the flag `False` would hide most of a user's list on any date search — the common case, not an edge case. |
| **Adapter-side filtering** | `OutlookTaskAdapter.search()` fetches `folder.Items` with **no DASL `Restrict()` on due date**; date/subject/status filtering happens in Python, same as `FakeTaskAdapter`. | Compound DASL string with `OR [DueDate] = 0` | DASL excludes null-`DueDate` items from a `>=`/`<=` range and can't cleanly express "OR no due date"; Python-side filtering is simple, already proven by the fake adapter, and safe since Tasks folders are small. |
| **Error taxonomy reuse** | New `TaskNotFoundError(CalendarToolError)` (`code = "task_not_found"`); `OutlookUnavailableError` reused as-is. | New `TaskToolError` base; rename `CalendarToolError` → generic `OutlookToolError` | Matches proposal's plan exactly; keeps calendar files untouched (hard constraint). Name is dated but accepted as debt — `server.py`'s `_map_error` already catches the shared base, so no server change needed. |
| **No `task_get_notes` analog** | Only `task_search` + `task_get_task` (per proposal scope). | Add a subject-disambiguation helper like `calendar_get_notes` | Proposal scopes to 2 tools; tasks are addressed by `entryId` from search results. |
| **Due-date sentinel normalization** (orchestrator-approved amendment, Batch 4) | `OutlookTaskAdapter` treats any `DueDate` with `year >= 4500` as `None`, in both `search()` and `get_task()`. | Trust `item.DueDate is not None` as-is (Batch 3's original approach) | Real Outlook COM returns a sentinel datetime (year 4501, `olNoDate`) for an unset `DueDate`, not Python `None`; the spec/fake-adapter model "no due date" as `None`, so without normalization `include_no_due_date` filtering and the returned `due_date` field would surface a bogus year-4501 date on a real Windows host. |

## Data Flow

    Claude Desktop (stdio) ─▶ server.py (FastMCP)
                                   │
                        ┌──────────┴──────────┐
                        ▼                     ▼
                  task_search           task_get_task
                        │                     │
                        └──────────┬──────────┘
                                   ▼
                          tools/tasks.py
                                   │
                                   ▼
                          TaskPort (Protocol)
                            /                \
              OutlookTaskAdapter          FakeTaskAdapter
          (real, win32com, lazy import)   (tests only)
                    │
                    ▼
       Outlook.Application → GetNamespace("MAPI")
         → GetDefaultFolder(13) → Items (fetched, filtered in Python)
                                   / GetItemFromID(entryId)

**`task_search` filter sequence** (resolves open Q2): for each item fetched
from `folder.Items`, apply in order — (1) subject substring match if given,
(2) status enum match if given, (3) due-date pass: `date_from`/`date_to` both
`None` → pass; else `due_date is None` → pass iff `include_no_due_date`; else
`date_from <= due_date <= date_to` (open-ended if one bound is `None`).

## File Changes

| File | Action | Description |
|---|---|---|
| `tools/tasks.py` | Create | `task_search`, `task_get_task` tool functions (mirrors `tools/calendar.py`) |
| `tools/task_adapter.py` | Create | `TaskPort` Protocol + `OutlookTaskAdapter` (lazy `win32com` import) |
| `tools/fake_task_adapter.py` | Create | `FakeTaskAdapter`, test-only |
| `tools/errors.py` | Modify | Add `TaskNotFoundError(CalendarToolError)` |
| `models/schemas.py` | Modify | Add `TaskStatus`, `TaskSummary`, `TaskDetail`, `TaskSearchRequest`, `GetTaskRequest` |
| `server.py` | Modify | `create_server()` gains `task_adapter` param; registers `task_search`/`task_get_task`; lazy `_resolve_real_task_adapter()` |
| `config/settings.yaml` | Modify | Add `tasks_folder_id: 13` (`olFolderTasks`) |
| `make-deploy-package.sh` | Modify | Manifest exclusion regex covers both fakes: `grep -vxE 'tools/(fake_adapter\|fake_task_adapter)\.py'` |
| `tests/test_tasks_tools.py` | Create | Unit tests against `FakeTaskAdapter` |
| `tests/test_task_adapter.py` | Create | Real-adapter tests, `win32com.client` mocked into `sys.modules` (same technique as `tests/test_outlook_adapter.py`) |
| `README.md` | Modify | Move Tasks out of the "future work" list |

## Interfaces / Contracts

```python
# tools/task_adapter.py
class TaskPort(Protocol):
    def search(
        self, date_from: datetime | None = None, date_to: datetime | None = None,
        subject: str | None = None, status: TaskStatus | None = None,
        include_no_due_date: bool = True,
    ) -> list[TaskSummary]: ...
    def get_task(self, entry_id: str) -> TaskDetail: ...

# models/schemas.py
class TaskStatus(str, Enum):
    NOT_STARTED = "not_started"; IN_PROGRESS = "in_progress"
    WAITING = "waiting"; DEFERRED = "deferred"; COMPLETED = "completed"

class TaskSummary(_AliasedModel):
    entry_id: str = Field(alias="entryId")
    subject: str
    due_date: datetime | None = Field(default=None, alias="dueDate")
    status: TaskStatus
    is_complete: bool = Field(alias="isComplete")

class TaskDetail(TaskSummary):
    body: str
```

## Testing Strategy

| Layer | What to Test | Approach |
|---|---|---|
| Unit (tools) | Filter logic (Q2 semantics), status defensive-normalization (Q1), error mapping | `FakeTaskAdapter` injected via `create_server(task_adapter=...)` |
| Unit (adapter) | `Status`/`Complete` → `TaskStatus`/`is_complete` mapping, Python-side due-date filter, `GetDefaultFolder(13)` call | `pytest-mock` injects fake `win32com.client` into `sys.modules`, mirrors `tests/test_outlook_adapter.py::_install_fake_win32com` |
| Integration | Both tools registered, callable via FastMCP in-process client | Extend existing `tests/test_server.py` pattern |
| E2E | Real To Do item resolves via COM | Manual only, on Windows host |

## Migration / Rollout

No migration — purely additive. Same rollout as calendar MVP (Windows Python
3.12 host); dev/CI stays on WSL2 with `FakeTaskAdapter`.

## Open Questions

- [ ] None blocking — both proposal-flagged questions (status mapping,
      no-due-date filtering) are resolved above with documented rationale.
