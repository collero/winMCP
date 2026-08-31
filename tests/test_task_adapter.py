"""Tests for tools/task_adapter.py's OutlookTaskAdapter — the real,
win32com-backed TaskPort implementation.

`win32com` is never installed on this WSL2 dev host (per project policy: it
MUST NOT be pip-installed here, and MUST NOT be imported at module load
time). Every test that exercises `OutlookTaskAdapter` therefore injects a
fake `win32com.client` module into `sys.modules` via pytest-mock before
constructing/calling the adapter, so `import win32com.client` (which only
ever happens lazily, inside the adapter's own methods) resolves to a mock
instead of failing. Mirrors `tests/test_outlook_adapter.py`.

Phase 5: Real Outlook Task Adapter (outlook-tasks-adapter spec)
"""
import importlib
import sys
import types
from datetime import datetime, timedelta, timezone

import pytest

from tools.errors import OutlookUnavailableError, TaskNotFoundError


def _install_fake_pythoncom(mocker):
    """Inject a fake `pythoncom` module into `sys.modules` with a mock
    `CoInitialize` callable, and return that mock so the test can assert on
    it (e.g. call order relative to `win32com.client.Dispatch`)."""
    mocker.patch.dict(sys.modules)
    fake_pythoncom = types.ModuleType("pythoncom")
    coinitialize_mock = mocker.Mock(name="CoInitialize")
    fake_pythoncom.CoInitialize = coinitialize_mock
    sys.modules["pythoncom"] = fake_pythoncom
    return coinitialize_mock


def _install_fake_win32com(mocker):
    """Inject a fake `win32com.client` module into `sys.modules` with a
    mock `Dispatch` callable, and return that mock so the test can arrange
    return values / side effects on it.

    Also installs a fake `pythoncom` module (unless one is already
    installed by the caller via `_install_fake_pythoncom`) so every
    existing call site keeps working now that the adapter's
    `_dispatch_outlook` lazily imports `pythoncom` too."""
    if "pythoncom" not in sys.modules:
        _install_fake_pythoncom(mocker)
    mocker.patch.dict(sys.modules)
    fake_win32com = types.ModuleType("win32com")
    fake_win32com_client = types.ModuleType("win32com.client")
    dispatch_mock = mocker.Mock(name="Dispatch")
    fake_win32com_client.Dispatch = dispatch_mock
    fake_win32com.client = fake_win32com_client  # so `win32com.client.X` resolves
    sys.modules["win32com"] = fake_win32com
    sys.modules["win32com.client"] = fake_win32com_client
    return dispatch_mock


def test_win32com_not_imported_at_module_level(mocker):
    mocker.patch.dict(sys.modules)
    sys.modules.pop("win32com", None)
    sys.modules.pop("win32com.client", None)

    import tools.task_adapter as module

    importlib.reload(module)

    assert "win32com" not in sys.modules
    assert "win32com.client" not in sys.modules


def test_pythoncom_not_imported_at_module_level(mocker):
    mocker.patch.dict(sys.modules)
    sys.modules.pop("pythoncom", None)

    import tools.task_adapter as module

    importlib.reload(module)

    assert "pythoncom" not in sys.modules


def test_search_calls_coinitialize_before_dispatch(mocker):
    """outlook-com-adapter spec's "Per-Thread COM Initialization"
    requirement: pythoncom.CoInitialize() MUST be called before
    win32com.client.Dispatch() on a search() call."""
    from tools.task_adapter import OutlookTaskAdapter

    coinitialize_mock = _install_fake_pythoncom(mocker)
    dispatch_mock = _install_fake_win32com(mocker)
    manager = mocker.Mock()
    manager.attach_mock(coinitialize_mock, "CoInitialize")
    manager.attach_mock(dispatch_mock, "Dispatch")

    outlook_app = mocker.Mock(name="OutlookApplication")
    dispatch_mock.return_value = outlook_app
    namespace = mocker.Mock(name="Namespace")
    outlook_app.GetNamespace.return_value = namespace
    folder = mocker.Mock(name="TasksFolder")
    namespace.GetDefaultFolder.return_value = folder
    items = mocker.Mock(name="Items")
    folder.Items = items
    items.__iter__ = mocker.Mock(return_value=iter([]))

    adapter = OutlookTaskAdapter()
    adapter.search()

    call_names = [call[0] for call in manager.mock_calls]
    assert "CoInitialize" in call_names
    assert "Dispatch" in call_names
    assert call_names.index("CoInitialize") < call_names.index("Dispatch")


def test_get_task_calls_coinitialize_before_dispatch(mocker):
    """Mirrors test_search_calls_coinitialize_before_dispatch for the
    get_task() call path."""
    from tools.task_adapter import OutlookTaskAdapter

    coinitialize_mock = _install_fake_pythoncom(mocker)
    dispatch_mock = _install_fake_win32com(mocker)
    manager = mocker.Mock()
    manager.attach_mock(coinitialize_mock, "CoInitialize")
    manager.attach_mock(dispatch_mock, "Dispatch")

    outlook_app = mocker.Mock(name="OutlookApplication")
    dispatch_mock.return_value = outlook_app
    namespace = mocker.Mock(name="Namespace")
    outlook_app.GetNamespace.return_value = namespace
    fake_item = mocker.Mock(
        EntryID="ABC123", Subject="Task A", Status=0, Complete=False,
        DueDate=datetime(2026, 7, 27, 9, 0), Body="Notes here",
    )
    namespace.GetItemFromID.return_value = fake_item

    adapter = OutlookTaskAdapter()
    adapter.get_task("ABC123")

    call_names = [call[0] for call in manager.mock_calls]
    assert "CoInitialize" in call_names
    assert "Dispatch" in call_names
    assert call_names.index("CoInitialize") < call_names.index("Dispatch")


def test_search_uses_get_default_folder_13_and_filters_in_python_no_restrict(mocker):
    from tools.task_adapter import OutlookTaskAdapter

    dispatch_mock = _install_fake_win32com(mocker)
    outlook_app = mocker.Mock(name="OutlookApplication")
    dispatch_mock.return_value = outlook_app
    namespace = mocker.Mock(name="Namespace")
    outlook_app.GetNamespace.return_value = namespace
    folder = mocker.Mock(name="TasksFolder")
    namespace.GetDefaultFolder.return_value = folder
    items = mocker.Mock(name="Items")
    folder.Items = items

    in_range = mocker.Mock(
        EntryID="T1", Subject="Task A", Status=0, Complete=False,
        DueDate=datetime(2026, 7, 27, 9, 0), Body="",
    )
    out_of_range_future = mocker.Mock(
        EntryID="T2", Subject="Task B", Status=1, Complete=False,
        DueDate=datetime(2026, 8, 15, 9, 0), Body="",
    )
    no_due_date = mocker.Mock(
        EntryID="T3", Subject="Task C", Status=2, Complete=True,
        DueDate=None, Body="",
    )
    out_of_range_past = mocker.Mock(
        EntryID="T4", Subject="Task D", Status=0, Complete=False,
        DueDate=datetime(2026, 7, 20, 9, 0), Body="",
    )
    items.__iter__ = mocker.Mock(
        return_value=iter([in_range, out_of_range_future, no_due_date, out_of_range_past])
    )

    adapter = OutlookTaskAdapter()
    date_from = datetime(2026, 7, 25, tzinfo=timezone.utc)
    date_to = datetime(2026, 7, 30, tzinfo=timezone.utc)

    results = adapter.search(date_from=date_from, date_to=date_to)

    dispatch_mock.assert_called_once_with("Outlook.Application")
    outlook_app.GetNamespace.assert_called_once_with("MAPI")
    namespace.GetDefaultFolder.assert_called_once_with(13)
    items.Restrict.assert_not_called()

    entry_ids = {result.entry_id for result in results}
    assert entry_ids == {"T1", "T3"}


def test_search_aware_com_due_date_vs_naive_request_bound_does_not_raise(mocker):
    """datetime-tz hotfix (2026-08-26), defensive companion: task_adapter
    normalizes `item.DueDate` through the exact same `_to_aware` helper as
    outlook_adapter.py/mail_adapter.py, and `TaskSearchRequest.date_from`/
    `date_to` (models/schemas.py) also have no tz-aware validator — so a
    real, aware pywintypes.DueDate compared against a naive dueFrom/dueTo
    bound could raise the identical "can't compare offset-naive and
    offset-aware datetimes" TypeError, even though this wasn't the
    reported real-Windows failure (task_search wasn't exercised with an
    explicit date bound in that QA session)."""
    from tools.task_adapter import OutlookTaskAdapter

    dispatch_mock = _install_fake_win32com(mocker)
    outlook_app = mocker.Mock(name="OutlookApplication")
    dispatch_mock.return_value = outlook_app
    namespace = mocker.Mock(name="Namespace")
    outlook_app.GetNamespace.return_value = namespace
    folder = mocker.Mock(name="TasksFolder")
    namespace.GetDefaultFolder.return_value = folder
    items = mocker.Mock(name="Items")
    folder.Items = items

    aware_offset = timezone(timedelta(hours=2))  # e.g. CEST, like real Outlook
    fake_item = mocker.Mock(
        EntryID="T1", Subject="Revisar", Status=0, Complete=False,
        DueDate=datetime(2026, 8, 10, 9, 0, tzinfo=aware_offset), Body="",
    )
    items.__iter__ = mocker.Mock(return_value=iter([fake_item]))

    adapter = OutlookTaskAdapter()
    # Naive request bounds — legal per TaskSearchRequest's schema.
    date_from = datetime(2026, 8, 1, 0, 0)
    date_to = datetime(2026, 8, 31, 23, 59, 59)

    results = adapter.search(date_from=date_from, date_to=date_to)

    assert [r.entry_id for r in results] == ["T1"]


def test_search_uses_configured_tasks_folder_id(mocker):
    """outlook-com-adapter spec's "Configurable Folder Ids" requirement:
    a configured `tasks_folder_id` in settings.yaml is passed to
    GetDefaultFolder(), not the hardcoded default."""
    from tools.task_adapter import OutlookTaskAdapter

    mocker.patch(
        "tools.task_adapter.load_settings",
        return_value={"tasks_folder_id": 99},
    )
    dispatch_mock = _install_fake_win32com(mocker)
    outlook_app = mocker.Mock(name="OutlookApplication")
    dispatch_mock.return_value = outlook_app
    namespace = mocker.Mock(name="Namespace")
    outlook_app.GetNamespace.return_value = namespace
    folder = mocker.Mock(name="TasksFolder")
    namespace.GetDefaultFolder.return_value = folder
    items = mocker.Mock(name="Items")
    folder.Items = items
    items.__iter__ = mocker.Mock(return_value=iter([]))

    adapter = OutlookTaskAdapter()
    adapter.search()

    namespace.GetDefaultFolder.assert_called_once_with(99)


def test_search_absent_tasks_folder_id_falls_back_to_default_13(mocker):
    """Absent `tasks_folder_id` key -> the documented default (13,
    olFolderTasks)."""
    from tools.task_adapter import OutlookTaskAdapter

    mocker.patch("tools.task_adapter.load_settings", return_value={})
    dispatch_mock = _install_fake_win32com(mocker)
    outlook_app = mocker.Mock(name="OutlookApplication")
    dispatch_mock.return_value = outlook_app
    namespace = mocker.Mock(name="Namespace")
    outlook_app.GetNamespace.return_value = namespace
    folder = mocker.Mock(name="TasksFolder")
    namespace.GetDefaultFolder.return_value = folder
    items = mocker.Mock(name="Items")
    folder.Items = items
    items.__iter__ = mocker.Mock(return_value=iter([]))

    adapter = OutlookTaskAdapter()
    adapter.search()

    namespace.GetDefaultFolder.assert_called_once_with(13)


def test_settings_yaml_declares_tasks_folder_id_13():
    """Asserts the literal key is present in the real, unmocked
    config/settings.yaml — mirrors tests/test_mail_tools.py's
    test_settings_yaml_declares_mail_lookback_days_90 precedent, now that
    tasks_folder_id is a live key (config-live-folders change)."""
    from tools.settings import load_settings

    settings = load_settings()

    assert "tasks_folder_id" in settings
    assert settings["tasks_folder_id"] == 13


def test_get_task_uses_get_item_from_id(mocker):
    from tools.task_adapter import OutlookTaskAdapter

    dispatch_mock = _install_fake_win32com(mocker)
    outlook_app = mocker.Mock()
    dispatch_mock.return_value = outlook_app
    namespace = mocker.Mock()
    outlook_app.GetNamespace.return_value = namespace
    fake_item = mocker.Mock(
        EntryID="ABC123", Subject="Task A", Status=0, Complete=False,
        DueDate=datetime(2026, 7, 27, 9, 0), Body="Notes here",
    )
    namespace.GetItemFromID.return_value = fake_item

    adapter = OutlookTaskAdapter()
    result = adapter.get_task("ABC123")

    namespace.GetItemFromID.assert_called_once_with("ABC123")
    namespace.GetDefaultFolder.assert_not_called()  # not a re-scan
    assert result.entry_id == "ABC123"
    assert result.body == "Notes here"


def test_dispatch_failure_raises_outlook_unavailable_error(mocker):
    from tools.task_adapter import OutlookTaskAdapter

    dispatch_mock = _install_fake_win32com(mocker)
    dispatch_mock.side_effect = Exception("Outlook is not running")

    adapter = OutlookTaskAdapter()

    with pytest.raises(OutlookUnavailableError):
        adapter.search()

    with pytest.raises(OutlookUnavailableError):
        adapter.get_task("ABC123")


def test_pythoncom_import_error_raises_outlook_unavailable_error(mocker):
    """Isolates the "pythoncom import fails" half of `_dispatch_outlook`'s
    shared `try: import pythoncom; import win32com.client / except
    ImportError` block — as opposed to a win32com-only or combined failure.
    Mirrors `tests/test_outlook_adapter.py`'s dedicated pythoncom-isolation
    test. A real fake `win32com.client` is installed directly (bypassing
    `_install_fake_win32com`'s own pythoncom auto-install) to prove it would
    have succeeded had `import pythoncom` not failed first."""
    from tools.task_adapter import OutlookTaskAdapter

    mocker.patch.dict(sys.modules)
    sys.modules.pop("pythoncom", None)
    mocker.patch.dict(sys.modules, {"pythoncom": None})
    fake_win32com = types.ModuleType("win32com")
    fake_win32com_client = types.ModuleType("win32com.client")
    fake_win32com_client.Dispatch = mocker.Mock(name="Dispatch")
    fake_win32com.client = fake_win32com_client
    sys.modules["win32com"] = fake_win32com
    sys.modules["win32com.client"] = fake_win32com_client

    adapter = OutlookTaskAdapter()

    with pytest.raises(OutlookUnavailableError):
        adapter.get_task("ABC123")


def test_get_task_unknown_entry_id_raises_not_found(mocker):
    from tools.task_adapter import OutlookTaskAdapter

    dispatch_mock = _install_fake_win32com(mocker)
    outlook_app = mocker.Mock()
    dispatch_mock.return_value = outlook_app
    namespace = mocker.Mock()
    outlook_app.GetNamespace.return_value = namespace
    namespace.GetItemFromID.side_effect = Exception("MK_E_INVALIDEXTENSION")

    adapter = OutlookTaskAdapter()

    with pytest.raises(TaskNotFoundError):
        adapter.get_task("BAD-ID")


def test_status_1_complete_false_maps_in_progress_no_override(mocker):
    from tools.task_adapter import OutlookTaskAdapter

    dispatch_mock = _install_fake_win32com(mocker)
    outlook_app = mocker.Mock()
    dispatch_mock.return_value = outlook_app
    namespace = mocker.Mock()
    outlook_app.GetNamespace.return_value = namespace
    fake_item = mocker.Mock(
        EntryID="T1", Subject="Task A", Status=1, Complete=False,
        DueDate=None, Body="",
    )
    namespace.GetItemFromID.return_value = fake_item

    adapter = OutlookTaskAdapter()
    result = adapter.get_task("T1")

    assert result.status == "in_progress"
    assert result.is_complete is False


def test_status_3_complete_true_overrides_to_completed(mocker):
    from tools.task_adapter import OutlookTaskAdapter

    dispatch_mock = _install_fake_win32com(mocker)
    outlook_app = mocker.Mock()
    dispatch_mock.return_value = outlook_app
    namespace = mocker.Mock()
    outlook_app.GetNamespace.return_value = namespace
    fake_item = mocker.Mock(
        EntryID="T1", Subject="Task A", Status=3, Complete=True,
        DueDate=None, Body="",
    )
    namespace.GetItemFromID.return_value = fake_item

    adapter = OutlookTaskAdapter()
    result = adapter.get_task("T1")

    assert result.status == "completed"
    assert result.is_complete is True


def test_get_task_due_date_sentinel_year_4501_normalized_to_none(mocker):
    """Real Outlook COM returns a sentinel datetime (year 4501, the
    olNoDate convention) for an unset TaskItem.DueDate, not Python None —
    but design.md/the mocked test scenarios model "no due date" as None.
    OutlookTaskAdapter must normalize the sentinel to None so a caller
    (and get_task's `due_date` field) never sees the bogus year-4501 date."""
    from tools.task_adapter import OutlookTaskAdapter

    dispatch_mock = _install_fake_win32com(mocker)
    outlook_app = mocker.Mock()
    dispatch_mock.return_value = outlook_app
    namespace = mocker.Mock()
    outlook_app.GetNamespace.return_value = namespace
    fake_item = mocker.Mock(
        EntryID="T1", Subject="Task A", Status=0, Complete=False,
        DueDate=datetime(4501, 1, 1, 0, 0), Body="",
    )
    namespace.GetItemFromID.return_value = fake_item

    adapter = OutlookTaskAdapter()
    result = adapter.get_task("T1")

    assert result.due_date is None


def test_search_sorts_by_due_date_ascending_null_last_and_bounds_to_limit_plus_one(mocker):
    """search-result-caps (BUG-002): unlike mail/calendar's early-stop,
    the Tasks folder is already fully materialized in Python (no
    Restrict()) — so search() sorts the complete, already-scanned match
    list by `(due_date is None, due_date)` ascending (soonest-due-first,
    None last), then bounds it to `limit + 1` (the same "+1 peek"
    convention used by the early-stop paths), per design.md's ordering
    table."""
    from tools.task_adapter import OutlookTaskAdapter

    dispatch_mock = _install_fake_win32com(mocker)
    outlook_app = mocker.Mock(name="OutlookApplication")
    dispatch_mock.return_value = outlook_app
    namespace = mocker.Mock(name="Namespace")
    outlook_app.GetNamespace.return_value = namespace
    folder = mocker.Mock(name="TasksFolder")
    namespace.GetDefaultFolder.return_value = folder
    items = mocker.Mock(name="Items")
    folder.Items = items

    def _task(entry_id, due_date):
        return mocker.Mock(
            EntryID=entry_id, Subject=f"Task {entry_id}", Status=0, Complete=False,
            DueDate=due_date, Body="",
        )

    t_aug20 = _task("T20", datetime(2026, 8, 20, 9, 0))
    t_aug1 = _task("T1", datetime(2026, 8, 1, 9, 0))
    t_aug10 = _task("T10", datetime(2026, 8, 10, 9, 0))
    t_none = _task("TN", datetime(4501, 1, 1, 0, 0))  # olNoDate sentinel -> None
    items.__iter__ = mocker.Mock(return_value=iter([t_aug20, t_aug1, t_aug10, t_none]))

    adapter = OutlookTaskAdapter()

    results = adapter.search(limit=2)

    # limit=2 -> bounded to 3 (limit+1): the 3 soonest-due tasks, ascending,
    # with the no-due-date task dropped (it would sort last, 4th).
    assert [r.entry_id for r in results] == ["T1", "T10", "T20"]


def test_search_no_due_date_tasks_sort_after_all_dated_tasks_within_limit(mocker):
    from tools.task_adapter import OutlookTaskAdapter

    dispatch_mock = _install_fake_win32com(mocker)
    outlook_app = mocker.Mock(name="OutlookApplication")
    dispatch_mock.return_value = outlook_app
    namespace = mocker.Mock(name="Namespace")
    outlook_app.GetNamespace.return_value = namespace
    folder = mocker.Mock(name="TasksFolder")
    namespace.GetDefaultFolder.return_value = folder
    items = mocker.Mock(name="Items")
    folder.Items = items

    def _task(entry_id, due_date):
        return mocker.Mock(
            EntryID=entry_id, Subject=f"Task {entry_id}", Status=0, Complete=False,
            DueDate=due_date, Body="",
        )

    dated = _task("D1", datetime(2026, 8, 10, 9, 0))
    undated = _task("U1", datetime(4501, 1, 1, 0, 0))
    items.__iter__ = mocker.Mock(return_value=iter([undated, dated]))

    adapter = OutlookTaskAdapter()

    results = adapter.search(limit=50)

    assert [r.entry_id for r in results] == ["D1", "U1"]


def test_search_due_date_sentinel_treated_as_no_due_date_by_filters(mocker):
    """The same sentinel, seen via search(), must be treated as undated by
    the include_no_due_date filter — not as an out-of-range due date around
    the year 4501, and not surfaced as a bogus due_date value."""
    from tools.task_adapter import OutlookTaskAdapter

    dispatch_mock = _install_fake_win32com(mocker)
    outlook_app = mocker.Mock()
    dispatch_mock.return_value = outlook_app
    namespace = mocker.Mock()
    outlook_app.GetNamespace.return_value = namespace
    folder = mocker.Mock(name="TasksFolder")
    namespace.GetDefaultFolder.return_value = folder
    items = mocker.Mock(name="Items")
    folder.Items = items
    sentinel_item = mocker.Mock(
        EntryID="T1", Subject="Task A", Status=0, Complete=False,
        DueDate=datetime(4501, 1, 1, 0, 0), Body="",
    )
    items.__iter__ = mocker.Mock(return_value=iter([sentinel_item]))

    adapter = OutlookTaskAdapter()

    included = adapter.search(
        date_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
        date_to=datetime(2026, 12, 31, tzinfo=timezone.utc),
        include_no_due_date=True,
    )
    assert len(included) == 1
    assert included[0].due_date is None

    excluded = adapter.search(
        date_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
        date_to=datetime(2026, 12, 31, tzinfo=timezone.utc),
        include_no_due_date=False,
    )
    assert excluded == []


# --- BUG-010 (mail/0001-0002): COM DueDate is LOCAL wall-clock mislabeled
# UTC — task reads pass through from_com_datetime (which also owns the
# year-4501 sentinel guard now).


def test_get_task_due_date_mislabeled_local_is_returned_as_true_utc(mocker):
    from datetime import timedelta as _td
    from zoneinfo import ZoneInfo
    from tools.task_adapter import OutlookTaskAdapter

    mocker.patch(
        "tools.task_adapter.local_timezone", return_value=ZoneInfo("Europe/Madrid")
    )
    mislabel = timezone(_td(0), "GMT Standard Time")
    dispatch_mock = _install_fake_win32com(mocker)
    outlook_app = mocker.Mock()
    dispatch_mock.return_value = outlook_app
    namespace = mocker.Mock()
    outlook_app.GetNamespace.return_value = namespace
    item = mocker.Mock(
        EntryID="T1",
        Subject="Entregar informe",
        DueDate=datetime(2026, 8, 31, 12, 0, tzinfo=mislabel),  # true 10:00Z
        Status=0,
        Complete=False,
        Body="",
    )
    namespace.GetItemFromID.return_value = item

    adapter = OutlookTaskAdapter()
    detail = adapter.get_task("T1")

    assert detail.due_date == datetime(2026, 8, 31, 10, 0, tzinfo=timezone.utc)
