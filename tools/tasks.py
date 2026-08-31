"""Tool-layer functions for the Outlook Tasks / Microsoft To Do MCP tools.

Each function validates/normalizes its Pydantic request (see
`models/schemas.py`), delegates to a `TaskPort` adapter (the real
win32com-backed adapter or, in tests, `FakeTaskAdapter`), and lets the
adapter's typed errors (`tools/errors.py`) propagate to the caller. Mapping
those typed errors onto FastMCP's own tool-error wrapper is `server.py`'s
job — this module only needs to raise/propagate the stable
`CalendarToolError` taxonomy.

Design note (see design.md's "No-due-date search filtering" decision):
unlike `calendar_search`, `task_search` accepts a filterless call — Tasks
folders are bounded personal lists, not unbounded event streams, so there is
no "at least one filter required" rule and no lookback-window defaulting.
"""
from models.schemas import GetTaskRequest, TaskDetail, TaskSearchRequest, TaskSearchResult
from tools.settings import resolve_search_limit
from tools.task_adapter import TaskPort


def task_search(request: TaskSearchRequest, adapter: TaskPort) -> TaskSearchResult:
    """Search the default Outlook Tasks folder. All filters are optional; a
    filterless call MUST return every task in the folder (up to the
    effective `limit`).

    `limit` (search-result-caps change, BUG-002) is resolved via
    `resolve_search_limit()` (default 50, hard max 200, `ValueError` when
    `<= 0`) before any adapter call. The adapter is expected to return up
    to `limit + 1` rows (the "+1 peek" convention) — this function slices
    to `limit` and sets `results_truncated` when the adapter's response
    exceeded it."""
    limit = resolve_search_limit(request.limit)
    if (
        request.date_from is not None
        and request.date_to is not None
        and request.date_from > request.date_to
    ):
        # BUG-004 hotfix: an inverted range must never silently return an
        # empty result — echo both parsed bounds back to the caller.
        raise ValueError(
            f"task_search date range is inverted: dueFrom={request.date_from.isoformat()} "
            f"is after dueTo={request.date_to.isoformat()}"
        )
    results = adapter.search(
        request.date_from,
        request.date_to,
        subject=request.subject,
        status=request.status,
        include_no_due_date=request.include_no_due_date,
        limit=limit,
    )
    truncated = len(results) > limit
    return TaskSearchResult(results=results[:limit], results_truncated=truncated)


def task_get_task(request: GetTaskRequest, adapter: TaskPort) -> TaskDetail:
    """Fetch full detail for a single task by its Outlook entryId."""
    return adapter.get_task(request.entry_id)
