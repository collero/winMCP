"""TaskPort — the seam between tool logic and Outlook Tasks/To Do COM access.

Defines the `TaskPort` Protocol satisfied by both the real, win32com-backed
`OutlookTaskAdapter` (added in a later batch) and the test-only
`FakeTaskAdapter` (tools/fake_task_adapter.py). Mirrors `CalendarPort`
(tools/outlook_adapter.py) — see design.md's "Mirror the calendar MVP's
seam exactly" approach.

Unlike `CalendarPort.search()`, every `TaskPort.search()` filter is
optional: Tasks folders are bounded personal lists, not unbounded event
streams, so a filterless call is valid and MUST return the whole folder
(see design.md's "No-due-date search filtering" decision).
"""
from datetime import datetime, timezone
from typing import Any, Protocol

from models.schemas import TaskDetail, TaskStatus, TaskSummary
from tools.errors import OutlookUnavailableError, TaskNotFoundError
from tools.settings import load_settings, local_timezone

# Sort-key stand-in for a `None` due_date (search-result-caps change) — a
# datetime far enough in the future that it always sorts after every real
# due_date, avoiding a `None`-vs-`None` TypeError from Python's `<` on the
# ascending-sort's second tuple element when two undated tasks are compared.
_NO_DUE_DATE_SORT_KEY = datetime.max.replace(tzinfo=timezone.utc)

_DEFAULT_TASKS_FOLDER_ID = 13  # olFolderTasks (synced with Microsoft To Do)

_SENTINEL_NO_DATE_YEAR = 4500  # real Outlook COM's "olNoDate" convention:
# an unset TaskItem.DueDate comes back as a sentinel datetime (year 4501),
# not Python None. design.md/the mocked test scenarios model "no due date"
# as None (matching FakeTaskAdapter's in-memory contract), so any year at
# or beyond this threshold is normalized to None at the COM boundary.

_STATUS_MAP = {
    0: TaskStatus.NOT_STARTED,
    1: TaskStatus.IN_PROGRESS,
    2: TaskStatus.COMPLETED,
    3: TaskStatus.WAITING,
    4: TaskStatus.DEFERRED,
}


class TaskPort(Protocol):
    """Interface both the real and fake Outlook task adapters satisfy."""

    def search(
        self,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        subject: str | None = None,
        status: TaskStatus | None = None,
        include_no_due_date: bool = True,
        limit: int = 200,
    ) -> list[TaskSummary]:
        """Return task items matching the given filters, all of which are
        optional. A task passes the due-date filter if `date_from`/`date_to`
        are both omitted (no filter applied), or its `due_date` falls within
        the given bound(s) (open-ended on any omitted bound), or its
        `due_date` is `None` and `include_no_due_date` is `True`. Results
        are ordered by due date ascending (soonest first), with `None`
        `due_date` tasks last, then bounded to at most `limit + 1` rows
        (search-result-caps change, BUG-002's "+1 peek" convention — the
        tool layer slices to `limit` and flags `results_truncated` when it
        receives `limit + 1` rows back)."""
        ...

    def get_task(self, entry_id: str) -> TaskDetail:
        """Return full detail for the task item identified by entry_id.

        Raises TaskNotFoundError if entry_id does not resolve to an item,
        OutlookUnavailableError if Outlook cannot be reached at all.
        """
        ...


def _to_aware(value: Any, tz: Any) -> datetime:
    """Attach a timezone to a naive datetime returned by Outlook COM.

    Mirrors `tools/outlook_adapter.py::_to_aware` — Outlook COM
    (`pywintypes.datetime`) returns times in the Outlook profile's local
    timezone with no explicit offset; already-aware values pass through
    unchanged.
    """
    if value.tzinfo is not None:
        return value
    return value.replace(tzinfo=tz)


def _normalize_due_date(raw_due_date: Any) -> Any:
    """Treat Outlook's olNoDate sentinel (a year-4501 datetime) the same as
    Python None, per the "Due-Date Sentinel Normalization" decision — real
    Outlook COM returns this sentinel for an unset TaskItem.DueDate. Applied
    before `_to_aware` so `include_no_due_date` filtering and the returned
    `due_date` field never see the bogus year-4501 value."""
    if raw_due_date is None:
        return None
    if getattr(raw_due_date, "year", 0) >= _SENTINEL_NO_DATE_YEAR:
        return None
    return raw_due_date


def _map_status(raw_status: int, complete: Any) -> tuple[TaskStatus, bool]:
    """Map COM's `Status`/`Complete` to (`TaskStatus`, `is_complete`), per
    design.md's "Status mapping" decision: `Complete` is the authoritative
    "done" flag and overrides a mismatched raw `Status` to `completed`."""
    is_complete = bool(complete)
    if is_complete:
        return TaskStatus.COMPLETED, True
    return _STATUS_MAP.get(raw_status, TaskStatus.NOT_STARTED), False


def _passes_due_date_filter(
    due_date: datetime | None,
    date_from: datetime | None,
    date_to: datetime | None,
    include_no_due_date: bool,
) -> bool:
    """Mirrors `FakeTaskAdapter._passes_due_date_filter` — pure Python-side
    filtering, no DASL `Restrict()` on due date (design.md's "Adapter-side
    filtering" decision)."""
    if date_from is None and date_to is None:
        return True
    if due_date is None:
        return include_no_due_date
    if date_from is not None and due_date < date_from:
        return False
    if date_to is not None and due_date > date_to:
        return False
    return True


class OutlookTaskAdapter:
    """Real Outlook COM-backed `TaskPort` implementation.

    Connects via `win32com.client.Dispatch("Outlook.Application")` ->
    `GetNamespace("MAPI")` -> `GetDefaultFolder(id)`, per the
    outlook-tasks-adapter spec's "Real Adapter COM Access with Python-Side
    Filtering" requirement. `win32com.client` is imported lazily, inside
    `_dispatch_outlook`, never at module scope. The folder id is resolved
    from `config/settings.yaml`'s `tasks_folder_id` at COM-access time
    (default `13`, olFolderTasks, when absent) — see the outlook-com-adapter
    spec's "Configurable Folder Ids" requirement.
    """

    def _resolve_folder_id(self) -> int:
        """Read `tasks_folder_id` from settings at COM-access time (never
        cached), falling back to `_DEFAULT_TASKS_FOLDER_ID` when the key is
        absent or settings.yaml is unreadable."""
        try:
            settings = load_settings()
        except Exception:
            return _DEFAULT_TASKS_FOLDER_ID
        return int(settings.get("tasks_folder_id", _DEFAULT_TASKS_FOLDER_ID))

    def _dispatch_outlook(self) -> Any:
        """Lazily import win32com.client and connect to Outlook. Any
        failure here — missing win32com, or Outlook not installed/running —
        is mapped to OutlookUnavailableError so callers never see a raw
        ImportError or COM exception.

        Calls pythoncom.CoInitialize() on the current thread before
        Dispatch(), since COM apartments are thread-local and FastMCP
        dispatches tool calls across a worker-thread pool (outlook-com-adapter
        spec's "Per-Thread COM Initialization" requirement). CoInitialize()
        is idempotent per thread, so no CoUninitialize() pairing is used."""
        try:
            import pythoncom
            import win32com.client
        except ImportError as exc:
            raise OutlookUnavailableError(
                "win32com is not available on this platform"
            ) from exc
        try:
            pythoncom.CoInitialize()
            return win32com.client.Dispatch("Outlook.Application")
        except Exception as exc:
            raise OutlookUnavailableError(
                f"Could not connect to Outlook: {exc}"
            ) from exc

    def search(
        self,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        subject: str | None = None,
        status: TaskStatus | None = None,
        include_no_due_date: bool = True,
        limit: int = 200,
    ) -> list[TaskSummary]:
        outlook = self._dispatch_outlook()
        try:
            namespace = outlook.GetNamespace("MAPI")
            folder = namespace.GetDefaultFolder(self._resolve_folder_id())
            items = folder.Items
        except Exception as exc:
            raise OutlookUnavailableError(
                f"Outlook tasks search failed: {exc}"
            ) from exc

        tz = local_timezone()
        # datetime-tz hotfix (2026-08-26), defensive: normalize the request
        # bounds through the same `_to_aware` helper used for `item.DueDate`
        # below. `TaskSearchRequest.date_from`/`date_to` (models/schemas.py)
        # have no tz-aware validator either, so a naive bound could hit the
        # identical "can't compare offset-naive and offset-aware datetimes"
        # TypeError as calendar_search/mail_search once due_date is
        # normalized to aware — mirrors that fix even though task_search
        # wasn't the reported real-Windows failure.
        date_from = _to_aware(date_from, tz) if date_from is not None else None
        date_to = _to_aware(date_to, tz) if date_to is not None else None
        subject_needle = subject.lower() if subject else None
        results: list[TaskSummary] = []
        for item in items:
            item_subject = item.Subject
            if subject_needle is not None and subject_needle not in item_subject.lower():
                continue

            mapped_status, is_complete = _map_status(item.Status, item.Complete)
            if status is not None and mapped_status != status:
                continue

            raw_due_date = _normalize_due_date(item.DueDate)
            due_date = _to_aware(raw_due_date, tz) if raw_due_date is not None else None
            if not _passes_due_date_filter(due_date, date_from, date_to, include_no_due_date):
                continue

            results.append(
                TaskSummary(
                    entry_id=item.EntryID,
                    subject=item_subject,
                    due_date=due_date,
                    status=mapped_status,
                    is_complete=is_complete,
                )
            )
        # The Tasks folder is already fully materialized in Python (no
        # Restrict()/early-stop possible) — sort the complete match list by
        # due date ascending (soonest first), None last, then bound to
        # `limit + 1` (search-result-caps change's "+1 peek" convention),
        # per design.md's ordering table.
        results.sort(key=lambda task: task.due_date or _NO_DUE_DATE_SORT_KEY)
        return results[: limit + 1]

    def get_task(self, entry_id: str) -> TaskDetail:
        outlook = self._dispatch_outlook()
        try:
            namespace = outlook.GetNamespace("MAPI")
        except Exception as exc:
            raise OutlookUnavailableError(
                f"Could not access Outlook MAPI namespace: {exc}"
            ) from exc

        try:
            item = namespace.GetItemFromID(entry_id)
        except Exception as exc:
            raise TaskNotFoundError(
                f"No task with entryId {entry_id!r}: {exc}"
            ) from exc

        if item is None:
            raise TaskNotFoundError(f"No task with entryId {entry_id!r}")

        tz = local_timezone()
        mapped_status, is_complete = _map_status(item.Status, item.Complete)
        raw_due_date = _normalize_due_date(item.DueDate)
        due_date = _to_aware(raw_due_date, tz) if raw_due_date is not None else None
        return TaskDetail(
            entry_id=item.EntryID,
            subject=item.Subject,
            due_date=due_date,
            status=mapped_status,
            is_complete=is_complete,
            body=item.Body or "",
        )
