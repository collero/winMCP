"""RED tests for tools/fake_task_adapter.py — FakeTaskAdapter (test-only TaskPort).

Covers: search() with all filters optional (no-filter call returns the whole
seeded set, unlike calendar_search); subject substring match; status match;
due-date range filtering combined with `include_no_due_date` (default True);
get_task() returns a match or raises TaskNotFoundError; both methods can be
configured to raise OutlookUnavailableError instead (simulating COM Dispatch
failure) without ever touching real Outlook/win32com.
"""
from datetime import datetime, timezone

import pytest

from models.schemas import TaskDetail, TaskStatus
from tools.errors import OutlookUnavailableError, TaskNotFoundError
from tools.fake_task_adapter import FakeTaskAdapter


def _task(
    entry_id: str,
    subject: str,
    *,
    due_date: datetime | None,
    status: TaskStatus,
    is_complete: bool,
    body: str = "",
) -> TaskDetail:
    return TaskDetail(
        entry_id=entry_id,
        subject=subject,
        due_date=due_date,
        status=status,
        is_complete=is_complete,
        body=body,
    )


SEEDED_TASKS = [
    _task(
        "TASK-1",
        "Renovar licencia",
        due_date=datetime(2026, 8, 3, 9, 0, tzinfo=timezone.utc),
        status=TaskStatus.IN_PROGRESS,
        is_complete=False,
    ),
    _task(
        "TASK-2",
        "Sin fecha",
        due_date=None,
        status=TaskStatus.NOT_STARTED,
        is_complete=False,
    ),
    _task(
        "TASK-3",
        "Pagar factura",
        due_date=datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc),
        status=TaskStatus.COMPLETED,
        is_complete=True,
    ),
    _task(
        "TASK-4",
        "Reunion equipo",
        due_date=datetime(2026, 8, 15, 9, 0, tzinfo=timezone.utc),
        status=TaskStatus.WAITING,
        is_complete=False,
    ),
    _task(
        "TASK-5",
        "Backup notas",
        due_date=None,
        status=TaskStatus.DEFERRED,
        is_complete=False,
    ),
]


def test_search_with_all_filters_omitted_returns_the_whole_set():
    adapter = FakeTaskAdapter(tasks=SEEDED_TASKS)

    results = adapter.search()

    assert len(results) == 5
    assert {r.entry_id for r in results} == {t.entry_id for t in SEEDED_TASKS}


def test_search_filters_by_subject_case_insensitive_substring():
    adapter = FakeTaskAdapter(tasks=SEEDED_TASKS)

    results = adapter.search(subject="renovar")

    assert len(results) == 1
    assert results[0].entry_id == "TASK-1"


def test_search_filters_by_status_only():
    adapter = FakeTaskAdapter(tasks=SEEDED_TASKS)

    results = adapter.search(status=TaskStatus.COMPLETED)

    assert len(results) == 1
    assert results[0].entry_id == "TASK-3"


def test_search_default_include_no_due_date_passes_null_due_date_through_range():
    adapter = FakeTaskAdapter(tasks=SEEDED_TASKS[:2])  # TASK-1 (due) + TASK-2 (null)

    results = adapter.search(
        date_from=datetime(2026, 8, 1, 0, 0, tzinfo=timezone.utc),
        date_to=datetime(2026, 8, 31, 23, 59, tzinfo=timezone.utc),
    )

    assert {r.entry_id for r in results} == {"TASK-1", "TASK-2"}


def test_search_include_no_due_date_false_excludes_null_due_date_tasks():
    adapter = FakeTaskAdapter(tasks=SEEDED_TASKS[:2])

    results = adapter.search(
        date_from=datetime(2026, 8, 1, 0, 0, tzinfo=timezone.utc),
        date_to=datetime(2026, 8, 31, 23, 59, tzinfo=timezone.utc),
        include_no_due_date=False,
    )

    assert len(results) == 1
    assert results[0].entry_id == "TASK-1"


def test_search_excludes_tasks_outside_due_date_range():
    adapter = FakeTaskAdapter(tasks=SEEDED_TASKS)

    results = adapter.search(
        date_from=datetime(2026, 8, 1, 0, 0, tzinfo=timezone.utc),
        date_to=datetime(2026, 8, 5, 23, 59, tzinfo=timezone.utc),
        include_no_due_date=False,
    )

    assert len(results) == 1
    assert results[0].entry_id == "TASK-1"


def test_search_subject_only_is_unaffected_by_due_date_bounds():
    adapter = FakeTaskAdapter(tasks=SEEDED_TASKS)

    results = adapter.search(subject="sin fecha")

    assert len(results) == 1
    assert results[0].entry_id == "TASK-2"


def test_get_task_returns_matching_detail():
    adapter = FakeTaskAdapter(tasks=SEEDED_TASKS)

    detail = adapter.get_task("TASK-1")

    assert detail.entry_id == "TASK-1"
    assert detail.subject == "Renovar licencia"
    assert detail.status == TaskStatus.IN_PROGRESS


def test_get_task_raises_task_not_found_for_unknown_entry_id():
    adapter = FakeTaskAdapter(tasks=SEEDED_TASKS)

    with pytest.raises(TaskNotFoundError):
        adapter.get_task("DOES-NOT-EXIST")


def test_search_raises_outlook_unavailable_when_configured():
    adapter = FakeTaskAdapter(tasks=SEEDED_TASKS, unavailable=True)

    with pytest.raises(OutlookUnavailableError):
        adapter.search()


def test_get_task_raises_outlook_unavailable_when_configured():
    adapter = FakeTaskAdapter(tasks=SEEDED_TASKS, unavailable=True)

    with pytest.raises(OutlookUnavailableError):
        adapter.get_task("TASK-1")


# ---------------------------------------------------------------------------
# search-result-caps (BUG-002): FakeTaskAdapter mirrors
# OutlookTaskAdapter's due-date-ascending (None last) ordering + `limit + 1`
# "+1 peek" bounding exactly.
# ---------------------------------------------------------------------------

_OUT_OF_ORDER_TASKS = [
    _task(
        "T-AUG20", "Tarea", due_date=datetime(2026, 8, 20, 9, 0, tzinfo=timezone.utc),
        status=TaskStatus.NOT_STARTED, is_complete=False,
    ),
    _task(
        "T-AUG1", "Tarea", due_date=datetime(2026, 8, 1, 9, 0, tzinfo=timezone.utc),
        status=TaskStatus.NOT_STARTED, is_complete=False,
    ),
    _task(
        "T-AUG10", "Tarea", due_date=datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc),
        status=TaskStatus.NOT_STARTED, is_complete=False,
    ),
]


def test_search_orders_by_due_date_ascending():
    adapter = FakeTaskAdapter(tasks=_OUT_OF_ORDER_TASKS)

    results = adapter.search(subject="tarea")

    assert [r.entry_id for r in results] == ["T-AUG1", "T-AUG10", "T-AUG20"]


def test_search_no_due_date_tasks_sort_after_all_dated_tasks():
    dated = _task(
        "D1", "Con fecha", due_date=datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc),
        status=TaskStatus.NOT_STARTED, is_complete=False,
    )
    undated = _task("U1", "Sin fecha", due_date=None, status=TaskStatus.NOT_STARTED, is_complete=False)
    adapter = FakeTaskAdapter(tasks=[undated, dated])

    results = adapter.search()

    assert [r.entry_id for r in results] == ["D1", "U1"]


def test_search_bounds_to_limit_plus_one():
    adapter = FakeTaskAdapter(tasks=_OUT_OF_ORDER_TASKS)

    results = adapter.search(subject="tarea", limit=1)

    assert [r.entry_id for r in results] == ["T-AUG1", "T-AUG10"]


def test_search_returns_all_when_under_limit_plus_one():
    adapter = FakeTaskAdapter(tasks=_OUT_OF_ORDER_TASKS)

    results = adapter.search(subject="tarea", limit=50)

    assert [r.entry_id for r in results] == ["T-AUG1", "T-AUG10", "T-AUG20"]
