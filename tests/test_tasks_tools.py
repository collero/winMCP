"""Tests for tools/tasks.py — the tool-layer functions for the two Outlook
Tasks / Microsoft To Do MCP tools (task_search, task_get_task), exercised
against FakeTaskAdapter.

Phase 3: task_search (task-search spec)
Phase 4: task_get_task (task-get-detail spec)
"""
from datetime import datetime, timezone

import pytest

from models.schemas import GetTaskRequest, TaskDetail, TaskSearchRequest, TaskStatus
from tools.errors import OutlookUnavailableError, TaskNotFoundError
from tools.fake_task_adapter import FakeTaskAdapter
from tools.tasks import task_get_task, task_search


def _task(
    entry_id: str,
    subject: str,
    *,
    due_date: datetime | None = None,
    status: TaskStatus = TaskStatus.NOT_STARTED,
    is_complete: bool = False,
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


# ---------------------------------------------------------------------------
# Phase 3: task_search
# ---------------------------------------------------------------------------


def test_search_valid_range_and_subject(mocker):
    tasks = [
        _task("T1", "Renovar licencia", due_date=datetime(2026, 8, 3, 9, 0, tzinfo=timezone.utc)),
        _task("T2", "Renovar licencia", due_date=datetime(2026, 8, 3, 10, 0, tzinfo=timezone.utc)),
        _task("T3", "Otra cosa", due_date=datetime(2026, 8, 3, 11, 0, tzinfo=timezone.utc)),
    ]
    adapter = FakeTaskAdapter(tasks=[tasks[0]])
    spy = mocker.spy(adapter, "search")

    date_from = datetime(2026, 8, 3, 0, 0, tzinfo=timezone.utc)
    date_to = datetime(2026, 8, 3, 23, 59, 59, tzinfo=timezone.utc)
    request = TaskSearchRequest(date_from=date_from, date_to=date_to, subject="renovar")

    result = task_search(request, adapter)

    # search-result-caps: `limit` is now also threaded through, resolved
    # via `resolve_search_limit(None)` -> the default 50.
    spy.assert_called_once_with(
        date_from,
        date_to,
        subject="renovar",
        status=None,
        include_no_due_date=True,
        limit=50,
    )
    assert len(result.results) == 1
    assert result.results[0].entry_id == "T1"
    assert result.results_truncated is False


def test_search_inverted_range_raises_value_error_echoing_both_bounds():
    """BUG-004 hotfix ("calendar + mail + tasks" scope): an inverted
    explicit due-date range must raise, never silently return an empty
    result."""
    adapter = FakeTaskAdapter(tasks=[])
    request = TaskSearchRequest(
        date_from=datetime(2026, 6, 10, 0, 0, tzinfo=timezone.utc),
        date_to=datetime(2026, 6, 1, 0, 0, tzinfo=timezone.utc),
    )

    with pytest.raises(ValueError, match="inverted") as exc_info:
        task_search(request, adapter)

    assert "2026-06-10" in str(exc_info.value)
    assert "2026-06-01" in str(exc_info.value)


def test_search_status_only_filter(mocker):
    tasks = [_task("T1", "A", status=TaskStatus.COMPLETED, is_complete=True)]
    adapter = FakeTaskAdapter(tasks=tasks)
    spy = mocker.spy(adapter, "search")
    request = TaskSearchRequest(status=TaskStatus.COMPLETED)

    result = task_search(request, adapter)

    spy.assert_called_once_with(
        None,
        None,
        subject=None,
        status=TaskStatus.COMPLETED,
        include_no_due_date=True,
        limit=50,
    )
    assert len(result.results) == 1
    assert result.results[0].status == TaskStatus.COMPLETED


def test_search_all_filters_omitted_returns_whole_folder():
    tasks = [
        _task("T1", "A"),
        _task("T2", "B"),
        _task("T3", "C"),
        _task("T4", "D"),
        _task("T5", "E", due_date=None),
    ]
    adapter = FakeTaskAdapter(tasks=tasks)
    request = TaskSearchRequest()

    result = task_search(request, adapter)

    assert len(result.results) == 5
    assert result.results_truncated is False


def test_search_default_include_no_due_date_passes_null_due_date_through_range():
    tasks = [
        _task("T1", "With date", due_date=datetime(2026, 8, 3, tzinfo=timezone.utc)),
        _task("T2", "No date", due_date=None),
    ]
    adapter = FakeTaskAdapter(tasks=tasks)
    request = TaskSearchRequest(
        date_from=datetime(2026, 8, 1, tzinfo=timezone.utc),
        date_to=datetime(2026, 8, 31, 23, 59, 59, tzinfo=timezone.utc),
    )

    result = task_search(request, adapter)

    assert {r.entry_id for r in result.results} == {"T1", "T2"}


def test_search_include_no_due_date_false_excludes_null_due_date():
    tasks = [
        _task("T1", "With date", due_date=datetime(2026, 8, 3, tzinfo=timezone.utc)),
        _task("T2", "No date", due_date=None),
    ]
    adapter = FakeTaskAdapter(tasks=tasks)
    request = TaskSearchRequest(
        date_from=datetime(2026, 8, 1, tzinfo=timezone.utc),
        date_to=datetime(2026, 8, 31, 23, 59, 59, tzinfo=timezone.utc),
        include_no_due_date=False,
    )

    result = task_search(request, adapter)

    assert [r.entry_id for r in result.results] == ["T1"]


def test_search_subject_only_unaffected_by_due_date_bounds():
    tasks = [_task("T1", "Sin fecha", due_date=None)]
    adapter = FakeTaskAdapter(tasks=tasks)
    request = TaskSearchRequest(subject="sin fecha", include_no_due_date=False)

    result = task_search(request, adapter)

    assert len(result.results) == 1
    assert result.results[0].entry_id == "T1"


def test_search_empty_result_returns_empty_list():
    adapter = FakeTaskAdapter(tasks=[])
    request = TaskSearchRequest(subject="Nonexistent")

    result = task_search(request, adapter)

    assert result.results == []
    assert result.results_truncated is False


def test_search_outlook_unavailable_returns_tool_error():
    adapter = FakeTaskAdapter(tasks=[], unavailable=True)
    request = TaskSearchRequest(subject="Renovar")

    with pytest.raises(OutlookUnavailableError):
        task_search(request, adapter)


# ---------------------------------------------------------------------------
# search-result-caps (BUG-002): resolve_search_limit() + TaskSearchResult
# wrapping, including the "filterless call under/over cap" scenarios.
# ---------------------------------------------------------------------------


def test_search_filterless_call_default_limit_bounds_and_flags_oversized_result(mocker):
    """spec's "All filters omitted returns at most the default limit when
    over the cap" scenario."""
    mocker.patch("tools.settings.load_settings", return_value={})
    tasks = [_task(f"T{i}", f"Task {i}") for i in range(80)]
    adapter = FakeTaskAdapter(tasks=tasks)
    request = TaskSearchRequest()

    result = task_search(request, adapter)

    assert len(result.results) == 50
    assert result.results_truncated is True


def test_search_filterless_call_under_cap_not_marked_truncated(mocker):
    """spec's "All filters omitted returns the whole folder when under the
    cap" scenario."""
    mocker.patch("tools.settings.load_settings", return_value={})
    tasks = [_task(f"T{i}", f"Task {i}") for i in range(5)]
    adapter = FakeTaskAdapter(tasks=tasks)
    request = TaskSearchRequest()

    result = task_search(request, adapter)

    assert len(result.results) == 5
    assert result.results_truncated is False


def test_search_limit_above_hard_max_clamped_to_200_not_rejected(mocker):
    mocker.patch("tools.settings.load_settings", return_value={})
    tasks = [_task(f"T{i}", f"Task {i}") for i in range(40)]
    adapter = FakeTaskAdapter(tasks=tasks)
    spy = mocker.spy(adapter, "search")
    request = TaskSearchRequest(limit=1000)

    result = task_search(request, adapter)

    assert spy.call_args.kwargs["limit"] == 200
    assert len(result.results) == 40
    assert result.results_truncated is False


def test_search_non_positive_limit_rejected_before_adapter_call(mocker):
    adapter = FakeTaskAdapter(tasks=[])
    spy = mocker.spy(adapter, "search")
    request = TaskSearchRequest(limit=0)

    with pytest.raises(ValueError):
        task_search(request, adapter)

    spy.assert_not_called()


def test_search_returns_soonest_due_first_when_out_of_order():
    tasks = [
        _task("T-AUG20", "A", due_date=datetime(2026, 8, 20, tzinfo=timezone.utc)),
        _task("T-AUG1", "A", due_date=datetime(2026, 8, 1, tzinfo=timezone.utc)),
        _task("T-AUG10", "A", due_date=datetime(2026, 8, 10, tzinfo=timezone.utc)),
    ]
    adapter = FakeTaskAdapter(tasks=tasks)
    request = TaskSearchRequest()

    result = task_search(request, adapter)

    assert [r.entry_id for r in result.results] == ["T-AUG1", "T-AUG10", "T-AUG20"]


def test_search_no_due_date_tasks_sort_after_dated_tasks():
    dated = _task("D1", "Con fecha", due_date=datetime(2026, 8, 10, tzinfo=timezone.utc))
    undated = _task("U1", "Sin fecha", due_date=None)
    adapter = FakeTaskAdapter(tasks=[undated, dated])
    request = TaskSearchRequest()

    result = task_search(request, adapter)

    assert [r.entry_id for r in result.results] == ["D1", "U1"]


# ---------------------------------------------------------------------------
# Phase 4: task_get_task
# ---------------------------------------------------------------------------


def test_get_task_success():
    detail = _task(
        "TASK-1",
        "Renovar licencia",
        status=TaskStatus.IN_PROGRESS,
        is_complete=False,
        body="Contactar con proveedor",
    )
    adapter = FakeTaskAdapter(tasks=[detail])
    request = GetTaskRequest(entry_id="TASK-1")

    result = task_get_task(request, adapter)

    assert result.entry_id == "TASK-1"
    assert result.subject == "Renovar licencia"
    assert result.body == "Contactar con proveedor"
    assert result.status == TaskStatus.IN_PROGRESS
    assert result.is_complete is False


def test_get_task_not_found_raises_tool_error():
    adapter = FakeTaskAdapter(tasks=[])
    request = GetTaskRequest(entry_id="BAD-ID")

    with pytest.raises(TaskNotFoundError):
        task_get_task(request, adapter)


def test_get_task_empty_body_returns_empty_string():
    detail = _task("TASK-2", "No notes", body="")
    adapter = FakeTaskAdapter(tasks=[detail])
    request = GetTaskRequest(entry_id="TASK-2")

    result = task_get_task(request, adapter)

    assert result.body == ""
    assert result.subject == "No notes"


def test_get_task_completed_and_in_progress_report_consistent_fields():
    completed = _task(
        "TASK-3", "Done thing", status=TaskStatus.COMPLETED, is_complete=True
    )
    in_progress = _task(
        "TASK-1", "Ongoing thing", status=TaskStatus.IN_PROGRESS, is_complete=False
    )
    adapter = FakeTaskAdapter(tasks=[completed, in_progress])

    completed_result = task_get_task(GetTaskRequest(entry_id="TASK-3"), adapter)
    in_progress_result = task_get_task(GetTaskRequest(entry_id="TASK-1"), adapter)

    assert completed_result.status == TaskStatus.COMPLETED
    assert completed_result.is_complete is True
    assert in_progress_result.status == TaskStatus.IN_PROGRESS
    assert in_progress_result.is_complete is False
