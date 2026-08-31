"""FakeTaskAdapter — in-memory TaskPort implementation used by tests.

Seeded via the constructor with a list of `TaskDetail` (summary fields +
body). Implements the same `TaskPort` Protocol as the real win32com-backed
adapter (added in a later batch), so tool code under test never knows the
difference — mirrors `tools/fake_adapter.py::FakeCalendarAdapter`, which is
what lets the full Strict TDD RED-GREEN-REFACTOR cycle run on WSL2 Linux
with zero `win32com` dependency (see design.md's "COM seam" decision).

Filter sequence (design.md's "task_search filter sequence", resolving open
Q2): for each seeded task, apply in order — (1) subject substring match if
given, (2) status enum match if given, (3) due-date pass: `date_from`/
`date_to` both `None` -> pass; else `due_date is None` -> pass iff
`include_no_due_date`; else `date_from <= due_date <= date_to` (open-ended
if one bound is `None`).
"""
from datetime import datetime, timezone

from models.schemas import TaskDetail, TaskStatus, TaskSummary
from tools.errors import OutlookUnavailableError, TaskNotFoundError

# Sort-key stand-in for a `None` due_date (search-result-caps change) —
# mirrors tools/task_adapter.py::_NO_DUE_DATE_SORT_KEY.
_NO_DUE_DATE_SORT_KEY = datetime.max.replace(tzinfo=timezone.utc)


class FakeTaskAdapter:
    """In-memory stand-in for `OutlookTaskAdapter`, satisfying `TaskPort`."""

    def __init__(
        self,
        tasks: list[TaskDetail] | None = None,
        *,
        unavailable: bool = False,
    ):
        self._tasks = list(tasks) if tasks else []
        self._unavailable = unavailable

    def search(
        self,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        subject: str | None = None,
        status: TaskStatus | None = None,
        include_no_due_date: bool = True,
        limit: int = 200,
    ) -> list[TaskSummary]:
        if self._unavailable:
            raise OutlookUnavailableError(
                "Outlook is not available (fake adapter configured to fail)"
            )

        subject_needle = subject.lower() if subject else None
        matches: list[TaskSummary] = []
        for task in self._tasks:
            if subject_needle is not None and subject_needle not in task.subject.lower():
                continue
            if status is not None and task.status != status:
                continue
            if not self._passes_due_date_filter(task, date_from, date_to, include_no_due_date):
                continue
            matches.append(
                TaskSummary(
                    entry_id=task.entry_id,
                    subject=task.subject,
                    due_date=task.due_date,
                    status=task.status,
                    is_complete=task.is_complete,
                )
            )
        # search-result-caps (BUG-002): mirrors OutlookTaskAdapter's
        # due-date-ascending (None last) ordering + `limit + 1` "+1 peek"
        # bounding exactly.
        matches.sort(key=lambda summary: summary.due_date or _NO_DUE_DATE_SORT_KEY)
        return matches[: limit + 1]

    @staticmethod
    def _passes_due_date_filter(
        task: TaskDetail,
        date_from: datetime | None,
        date_to: datetime | None,
        include_no_due_date: bool,
    ) -> bool:
        if date_from is None and date_to is None:
            return True
        if task.due_date is None:
            return include_no_due_date
        if date_from is not None and task.due_date < date_from:
            return False
        if date_to is not None and task.due_date > date_to:
            return False
        return True

    def get_task(self, entry_id: str) -> TaskDetail:
        if self._unavailable:
            raise OutlookUnavailableError(
                "Outlook is not available (fake adapter configured to fail)"
            )

        for task in self._tasks:
            if task.entry_id == entry_id:
                return task
        raise TaskNotFoundError(f"No task with entryId {entry_id!r}")
