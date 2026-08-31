"""Tests for tools/outlook_adapter.py's OutlookCalendarAdapter — the real,
win32com-backed CalendarPort implementation.

`win32com` is never installed on this WSL2 dev host (per project policy: it
MUST NOT be pip-installed here, and MUST NOT be imported at module load
time). Every test that exercises `OutlookCalendarAdapter` therefore injects
a fake `win32com.client` module into `sys.modules` via pytest-mock before
constructing/calling the adapter, so `import win32com.client` (which only
ever happens lazily, inside the adapter's own methods) resolves to a mock
instead of failing.

Phase 7: Real Outlook Adapter (outlook-com-adapter spec)
"""
import importlib
import re
import sys
import types
from datetime import datetime, timedelta, timezone

import pytest

from tools.errors import EventNotFoundError, OutlookUnavailableError


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

    import tools.outlook_adapter as module

    importlib.reload(module)

    assert "win32com" not in sys.modules
    assert "win32com.client" not in sys.modules


def test_pythoncom_not_imported_at_module_level(mocker):
    mocker.patch.dict(sys.modules)
    sys.modules.pop("pythoncom", None)

    import tools.outlook_adapter as module

    importlib.reload(module)

    assert "pythoncom" not in sys.modules


def test_search_calls_coinitialize_before_dispatch(mocker):
    """outlook-com-adapter spec's "Per-Thread COM Initialization"
    requirement: pythoncom.CoInitialize() MUST be called before
    win32com.client.Dispatch() on a search() call."""
    from tools.outlook_adapter import OutlookCalendarAdapter

    coinitialize_mock = _install_fake_pythoncom(mocker)
    dispatch_mock = _install_fake_win32com(mocker)
    manager = mocker.Mock()
    manager.attach_mock(coinitialize_mock, "CoInitialize")
    manager.attach_mock(dispatch_mock, "Dispatch")

    outlook_app = mocker.Mock(name="OutlookApplication")
    dispatch_mock.return_value = outlook_app
    namespace = mocker.Mock(name="Namespace")
    outlook_app.GetNamespace.return_value = namespace
    folder = mocker.Mock(name="CalendarFolder")
    namespace.GetDefaultFolder.return_value = folder
    items = mocker.Mock(name="Items")
    folder.Items = items
    restricted_items = mocker.Mock(name="RestrictedItems")
    items.Restrict.return_value = restricted_items
    restricted_items.__iter__ = mocker.Mock(return_value=iter([]))

    adapter = OutlookCalendarAdapter()
    adapter.search(
        datetime(2026, 7, 27, tzinfo=timezone.utc),
        datetime(2026, 7, 28, tzinfo=timezone.utc),
    )

    call_names = [call[0] for call in manager.mock_calls]
    assert "CoInitialize" in call_names
    assert "Dispatch" in call_names
    assert call_names.index("CoInitialize") < call_names.index("Dispatch")


def test_get_event_calls_coinitialize_before_dispatch(mocker):
    """Mirrors test_search_calls_coinitialize_before_dispatch for the
    get_event() call path."""
    from tools.outlook_adapter import OutlookCalendarAdapter

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
        EntryID="ABC123",
        Subject="Tareas (bloque)",
        Start=datetime(2026, 7, 27, 9, 0),
        End=datetime(2026, 7, 27, 9, 30),
        Body="Politica ADN",
    )
    namespace.GetItemFromID.return_value = fake_item

    adapter = OutlookCalendarAdapter()
    adapter.get_event("ABC123")

    call_names = [call[0] for call in manager.mock_calls]
    assert "CoInitialize" in call_names
    assert "Dispatch" in call_names
    assert call_names.index("CoInitialize") < call_names.index("Dispatch")


def test_search_builds_dasl_restrict_and_converts_tz(mocker):
    from tools.outlook_adapter import OutlookCalendarAdapter

    dispatch_mock = _install_fake_win32com(mocker)
    outlook_app = mocker.Mock(name="OutlookApplication")
    dispatch_mock.return_value = outlook_app
    namespace = mocker.Mock(name="Namespace")
    outlook_app.GetNamespace.return_value = namespace
    folder = mocker.Mock(name="CalendarFolder")
    namespace.GetDefaultFolder.return_value = folder
    items = mocker.Mock(name="Items")
    folder.Items = items
    restricted_items = mocker.Mock(name="RestrictedItems")
    items.Restrict.return_value = restricted_items

    naive_start = datetime(2026, 7, 27, 9, 0)  # naive — simulates Outlook COM's local time
    naive_end = datetime(2026, 7, 27, 9, 30)
    fake_item = mocker.Mock(
        EntryID="ABC123",
        Subject="Tareas (bloque)",
        Start=naive_start,
        End=naive_end,
        Body="Politica ADN",
    )
    restricted_items.__iter__ = mocker.Mock(return_value=iter([fake_item]))

    adapter = OutlookCalendarAdapter()
    date_from = datetime(2026, 7, 27, 0, 0, tzinfo=timezone.utc)
    date_to = datetime(2026, 7, 27, 23, 59, 59, tzinfo=timezone.utc)

    results = adapter.search(date_from, date_to, subject="tareas")

    dispatch_mock.assert_called_once_with("Outlook.Application")
    outlook_app.GetNamespace.assert_called_once_with("MAPI")
    namespace.GetDefaultFolder.assert_called_once_with(9)
    assert items.IncludeRecurrences is True
    # date-dasl-and-recurrence hotfix (2026-08-26, BUG-005 part 2): Sort()
    # MUST be ascending (`Descending=False`) before Restrict() — Outlook
    # COM's IncludeRecurrences expansion silently stops expanding recurring
    # series when the source collection is sorted descending. Newest-first
    # output is now achieved by sorting the small, already Restrict()-bounded
    # match list in Python after collection (see the ordering test below).
    items.Sort.assert_called_once_with("[Start]", False)
    items.Restrict.assert_called_once()
    restrict_arg = items.Restrict.call_args.args[0]
    # BUG-004 hotfix: Jet's bracket-property Restrict() syntax (`[Start] >=
    # '...'`) parses even an ISO-ordered literal per the Outlook client's
    # locale under es-ES (day/month transposition on the lower bound) — see
    # design.md's "DASL @SQL= Restrict" decision. `@SQL=` DASL comparisons
    # against a quoted property URN are culture-invariant.
    assert restrict_arg.startswith('@SQL="urn:schemas:calendar:dtstart" >=')
    assert '"urn:schemas:calendar:dtend" <=' in restrict_arg
    assert "2026-07-27" in restrict_arg

    assert len(results) == 1
    result = results[0]
    assert result.entry_id == "ABC123"
    assert result.subject == "Tareas (bloque)"
    # naive Outlook COM datetime -> converted to tz-aware
    assert result.start.tzinfo is not None
    assert result.end.tzinfo is not None
    assert result.start.replace(tzinfo=None) == naive_start


def test_search_sort_ascending_called_before_restrict_for_recurrence_expansion(mocker):
    """date-dasl-and-recurrence hotfix (BUG-005 part 2): assert the exact
    COM call sequence — `IncludeRecurrences = True` before `Sort()`, and
    `Sort("[Start]", False)` (ascending) strictly before `Restrict()`.
    Outlook COM only expands recurring series through `Restrict()`/`Find()`
    when the source collection was sorted ascending first; a descending
    sort silently drops every recurring occurrence."""
    from tools.outlook_adapter import OutlookCalendarAdapter

    dispatch_mock = _install_fake_win32com(mocker)
    outlook_app = mocker.Mock(name="OutlookApplication")
    dispatch_mock.return_value = outlook_app
    namespace = mocker.Mock(name="Namespace")
    outlook_app.GetNamespace.return_value = namespace
    folder = mocker.Mock(name="CalendarFolder")
    namespace.GetDefaultFolder.return_value = folder
    items = mocker.Mock(name="Items")
    folder.Items = items
    restricted_items = mocker.Mock(name="RestrictedItems")
    items.Restrict.return_value = restricted_items
    restricted_items.__iter__ = mocker.Mock(return_value=iter([]))

    adapter = OutlookCalendarAdapter()
    date_from = datetime(2026, 8, 1, tzinfo=timezone.utc)
    date_to = datetime(2026, 8, 31, tzinfo=timezone.utc)

    adapter.search(date_from, date_to)

    assert items.IncludeRecurrences is True
    call_names = [call[0] for call in items.mock_calls]
    assert call_names.index("Sort") < call_names.index("Restrict")
    sort_call = next(call for call in items.mock_calls if call[0] == "Sort")
    assert sort_call.args == ("[Start]", False)


def test_search_recurring_series_occurrences_returned_newest_first(mocker):
    """date-dasl-and-recurrence hotfix: even though the (now-ascending)
    Restrict()-sourced collection yields occurrences oldest-first, the
    adapter must still return them newest-first — achieved by sorting the
    small, already-bounded collected match list in Python after the
    boundary re-check/subject filter, per design.md's "Python-side
    newest-first re-sort" decision."""
    from tools.outlook_adapter import OutlookCalendarAdapter

    dispatch_mock = _install_fake_win32com(mocker)
    outlook_app = mocker.Mock(name="OutlookApplication")
    dispatch_mock.return_value = outlook_app
    namespace = mocker.Mock(name="Namespace")
    outlook_app.GetNamespace.return_value = namespace
    folder = mocker.Mock(name="CalendarFolder")
    namespace.GetDefaultFolder.return_value = folder
    items = mocker.Mock(name="Items")
    folder.Items = items
    restricted_items = mocker.Mock(name="RestrictedItems")
    items.Restrict.return_value = restricted_items

    # A recurring "BtS" series expanded by IncludeRecurrences into four
    # occurrences, plus one one-off event — all delivered ascending
    # (oldest-first), as Outlook COM does once Sort() is ascending.
    occurrences = [
        mocker.Mock(
            EntryID=f"BTS-{day}", Subject="BtS",
            Start=datetime(2026, 8, day, 8, 0), End=datetime(2026, 8, day, 9, 30), Body="",
        )
        for day in (24, 25, 26, 27)
    ]
    one_off = mocker.Mock(
        EntryID="AGC-COS", Subject="AGC-COS",
        Start=datetime(2026, 8, 27, 10, 0), End=datetime(2026, 8, 27, 10, 30), Body="",
    )
    restricted_items.__iter__ = mocker.Mock(return_value=iter([*occurrences, one_off]))

    adapter = OutlookCalendarAdapter()
    date_from = datetime(2026, 8, 24, tzinfo=timezone.utc)
    date_to = datetime(2026, 8, 28, tzinfo=timezone.utc)

    results = adapter.search(date_from, date_to)

    assert [r.entry_id for r in results] == [
        "AGC-COS", "BTS-27", "BTS-26", "BTS-25", "BTS-24",
    ]


def test_search_subject_only_default_window_skips_boundary_recheck(mocker):
    """date-dasl-and-recurrence hotfix (BUG-005 part 1, "Subject-only
    calendar queries must work"): when `enforce_date_bounds=False` (the
    tool layer passes this for a request with no explicit `from`/`to`),
    an item Restrict() over-included relative to the caller-visible window
    must not be dropped by the Python-side boundary re-check — only the
    subject filter still applies. This is the mirror image of
    `test_search_transposition_prone_range_returns_only_bound_days`, which
    covers the `enforce_date_bounds=True` (explicit bounds) case."""
    from tools.outlook_adapter import OutlookCalendarAdapter

    dispatch_mock = _install_fake_win32com(mocker)
    outlook_app = mocker.Mock(name="OutlookApplication")
    dispatch_mock.return_value = outlook_app
    namespace = mocker.Mock(name="Namespace")
    outlook_app.GetNamespace.return_value = namespace
    folder = mocker.Mock(name="CalendarFolder")
    namespace.GetDefaultFolder.return_value = folder
    items = mocker.Mock(name="Items")
    folder.Items = items
    restricted_items = mocker.Mock(name="RestrictedItems")
    items.Restrict.return_value = restricted_items

    outside_window = mocker.Mock(
        EntryID="AGC-COS", Subject="AGC-COS",
        Start=datetime(2026, 8, 27, 10, 0), End=datetime(2026, 8, 27, 10, 30), Body="",
    )
    restricted_items.__iter__ = mocker.Mock(return_value=iter([outside_window]))

    adapter = OutlookCalendarAdapter()
    # A window that does NOT contain the item's Start/End at all.
    date_from = datetime(2026, 8, 19, tzinfo=timezone.utc)
    date_to = datetime(2026, 8, 26, tzinfo=timezone.utc)

    results = adapter.search(
        date_from, date_to, subject="AGC-COS", enforce_date_bounds=False
    )

    assert [r.entry_id for r in results] == ["AGC-COS"]


def test_dasl_datetime_emits_iso_ordered_literal():
    """outlook-com-adapter spec's "Locale-Invariant Restrict Date Literals"
    requirement: the emitted literal must be ISO-ordered (year-month-day),
    24-hour, and must never match the old ambiguous `MM/DD/YYYY` shape —
    BUG-003's root cause (design.md's "ISO-ordered, year-first literal
    format" decision)."""
    from tools.outlook_adapter import _dasl_datetime

    literal = _dasl_datetime(datetime(2026, 3, 12, 0, 0))

    assert literal == "2026-03-12 00:00"
    assert not re.search(r"\d{2}/\d{2}/\d{4}", literal)


def test_search_transposition_prone_range_returns_only_bound_days(mocker):
    """Reproduces BUG-003's live-confirmed Case 1: a 4-day June request
    (day <= 12 on both bounds) must not silently include a transposed
    September event. Since the mocked win32com.client.Items.Restrict()
    cannot itself reproduce real Outlook's locale-sensitive DASL parsing,
    this proves the new Python-side boundary re-check (design.md's
    "Python-side post-filter as defense-in-depth" decision) drops any
    item Restrict() over-included."""
    from tools.outlook_adapter import OutlookCalendarAdapter

    dispatch_mock = _install_fake_win32com(mocker)
    outlook_app = mocker.Mock(name="OutlookApplication")
    dispatch_mock.return_value = outlook_app
    namespace = mocker.Mock(name="Namespace")
    outlook_app.GetNamespace.return_value = namespace
    folder = mocker.Mock(name="CalendarFolder")
    namespace.GetDefaultFolder.return_value = folder
    items = mocker.Mock(name="Items")
    folder.Items = items
    restricted_items = mocker.Mock(name="RestrictedItems")
    items.Restrict.return_value = restricted_items

    in_bounds_06_08 = mocker.Mock(
        EntryID="E1", Subject="Reunion 06-08",
        Start=datetime(2026, 6, 8, 9, 0), End=datetime(2026, 6, 8, 10, 0), Body="",
    )
    in_bounds_06_09 = mocker.Mock(
        EntryID="E2", Subject="Reunion 06-09",
        Start=datetime(2026, 6, 9, 9, 0), End=datetime(2026, 6, 9, 10, 0), Body="",
    )
    transposed_09_04 = mocker.Mock(
        EntryID="E3", Subject="Reunion 09-04",
        Start=datetime(2026, 9, 4, 9, 0), End=datetime(2026, 9, 4, 10, 0), Body="",
    )
    restricted_items.__iter__ = mocker.Mock(
        return_value=iter([in_bounds_06_08, in_bounds_06_09, transposed_09_04])
    )

    adapter = OutlookCalendarAdapter()
    date_from = datetime(2026, 6, 6, 0, 0, tzinfo=timezone.utc)
    date_to = datetime(2026, 6, 9, 23, 59, 59, tzinfo=timezone.utc)

    results = adapter.search(date_from, date_to)

    assert {r.entry_id for r in results} == {"E1", "E2"}


def test_search_full_month_crossing_range_excludes_december(mocker):
    """Reproduces BUG-003's live-confirmed Case 4: a March-to-April request
    (day == 12 on both bounds) must not silently collapse to a two-day
    December window."""
    from tools.outlook_adapter import OutlookCalendarAdapter

    dispatch_mock = _install_fake_win32com(mocker)
    outlook_app = mocker.Mock(name="OutlookApplication")
    dispatch_mock.return_value = outlook_app
    namespace = mocker.Mock(name="Namespace")
    outlook_app.GetNamespace.return_value = namespace
    folder = mocker.Mock(name="CalendarFolder")
    namespace.GetDefaultFolder.return_value = folder
    items = mocker.Mock(name="Items")
    folder.Items = items
    restricted_items = mocker.Mock(name="RestrictedItems")
    items.Restrict.return_value = restricted_items

    march_event = mocker.Mock(
        EntryID="M1", Subject="Marzo",
        Start=datetime(2026, 3, 15, 9, 0), End=datetime(2026, 3, 15, 10, 0), Body="",
    )
    april_event = mocker.Mock(
        EntryID="M2", Subject="Abril",
        Start=datetime(2026, 4, 5, 9, 0), End=datetime(2026, 4, 5, 10, 0), Body="",
    )
    transposed_december_event = mocker.Mock(
        EntryID="M3", Subject="Diciembre",
        Start=datetime(2026, 12, 3, 9, 0), End=datetime(2026, 12, 3, 10, 0), Body="",
    )
    restricted_items.__iter__ = mocker.Mock(
        return_value=iter([march_event, april_event, transposed_december_event])
    )

    adapter = OutlookCalendarAdapter()
    date_from = datetime(2026, 3, 12, 0, 0, tzinfo=timezone.utc)
    date_to = datetime(2026, 4, 12, 0, 0, tzinfo=timezone.utc)

    results = adapter.search(date_from, date_to)

    assert {r.entry_id for r in results} == {"M1", "M2"}


def test_search_control_range_day_ge_13_unchanged(mocker):
    """Control case: a range whose bound days are all >= 13 is unambiguous
    under either locale reading even pre-fix — this must keep returning
    exactly the same events post-fix (no regression from the new boundary
    re-check)."""
    from tools.outlook_adapter import OutlookCalendarAdapter

    dispatch_mock = _install_fake_win32com(mocker)
    outlook_app = mocker.Mock(name="OutlookApplication")
    dispatch_mock.return_value = outlook_app
    namespace = mocker.Mock(name="Namespace")
    outlook_app.GetNamespace.return_value = namespace
    folder = mocker.Mock(name="CalendarFolder")
    namespace.GetDefaultFolder.return_value = folder
    items = mocker.Mock(name="Items")
    folder.Items = items
    restricted_items = mocker.Mock(name="RestrictedItems")
    items.Restrict.return_value = restricted_items

    seeded = [
        mocker.Mock(
            EntryID=f"C{day}", Subject=f"Evento {day}",
            Start=datetime(2026, 6, day, 9, 0), End=datetime(2026, 6, day, 10, 0), Body="",
        )
        for day in (22, 23, 24, 25)
    ]
    restricted_items.__iter__ = mocker.Mock(return_value=iter(seeded))

    adapter = OutlookCalendarAdapter()
    date_from = datetime(2026, 6, 20, 0, 0, tzinfo=timezone.utc)
    date_to = datetime(2026, 6, 25, 23, 59, 59, tzinfo=timezone.utc)

    results = adapter.search(date_from, date_to)

    assert {r.entry_id for r in results} == {"C22", "C23", "C24", "C25"}


def _upper_bound_narrow_on_swap_case(mocker, date_from, date_to, in_bounds, out_of_bounds):
    """Shared body for the upper-bound sweep cases below: the mirror of
    `test_search_transposition_prone_range_returns_only_bound_days` /
    `test_search_full_month_crossing_range_excludes_december` (which sweep
    the LOWER bound's day across the <=12/>=13 boundary while the upper
    bound is held safely out of the ambiguous range). Live evidence for
    BUG-004's upper-bound case showed a `day < month` upper bound (e.g.
    `..2026-06-02`) is a "narrow-on-swap": a locale-transposed reading of
    the literal produces an EARLIER date than requested, which would make
    real Outlook's Restrict() silently EXCLUDE valid in-window items before
    they ever reach the Python-side boundary re-check — a re-check can only
    drop over-included items, never rescue ones Restrict() wrongly dropped.
    Since Restrict() is mocked here (returns whatever this test seeds
    regardless of the filter string), the return-value assertion is a
    behavioral safety net; the DASL-string assertion is what actually
    guards against the transposition regression."""
    from tools.outlook_adapter import OutlookCalendarAdapter

    dispatch_mock = _install_fake_win32com(mocker)
    outlook_app = mocker.Mock(name="OutlookApplication")
    dispatch_mock.return_value = outlook_app
    namespace = mocker.Mock(name="Namespace")
    outlook_app.GetNamespace.return_value = namespace
    folder = mocker.Mock(name="CalendarFolder")
    namespace.GetDefaultFolder.return_value = folder
    items = mocker.Mock(name="Items")
    folder.Items = items
    restricted_items = mocker.Mock(name="RestrictedItems")
    items.Restrict.return_value = restricted_items
    restricted_items.__iter__ = mocker.Mock(
        return_value=iter([*in_bounds, *out_of_bounds])
    )

    adapter = OutlookCalendarAdapter()
    results = adapter.search(date_from, date_to)

    items.Restrict.assert_called_once()
    restrict_arg = items.Restrict.call_args.args[0]
    assert restrict_arg.startswith('@SQL="urn:schemas:calendar:dtstart" >=')
    assert '"urn:schemas:calendar:dtend" <=' in restrict_arg
    from tools.outlook_adapter import _dasl_datetime

    assert _dasl_datetime(date_from) in restrict_arg
    assert _dasl_datetime(date_to) in restrict_arg
    # No Jet bracket-property date comparison must remain.
    assert not re.search(r"\[Start\]|\[End\]", restrict_arg)

    assert {r.entry_id for r in results} == {item.EntryID for item in in_bounds}


def test_search_upper_bound_2026_06_02_day_lt_month_returns_window_items(mocker):
    """Upper-bound mirror of the lower-bound sweep: `date_to`'s day (2) is
    less than its month (6) — the narrow-on-swap shape live evidence
    identified for BUG-004's upper bound."""
    date_from = datetime(2026, 5, 20, 0, 0, tzinfo=timezone.utc)
    date_to = datetime(2026, 6, 2, 23, 59, 59, tzinfo=timezone.utc)

    def _event(entry_id, start):
        return mocker.Mock(
            EntryID=entry_id, Subject=entry_id,
            Start=start, End=start + timedelta(hours=1), Body="",
        )

    in_bounds = [
        _event("IN-05-28", datetime(2026, 5, 28, 9, 0)),
        _event("IN-06-02", datetime(2026, 6, 2, 9, 0)),  # right at the upper boundary day
    ]
    out_of_bounds = [_event("OUT-06-03", datetime(2026, 6, 3, 9, 0))]

    _upper_bound_narrow_on_swap_case(mocker, date_from, date_to, in_bounds, out_of_bounds)


def test_search_upper_bound_2026_11_05_day_lt_month_returns_window_items(mocker):
    """Upper-bound mirror: `date_to`'s day (5) is less than its month
    (11)."""
    date_from = datetime(2026, 10, 20, 0, 0, tzinfo=timezone.utc)
    date_to = datetime(2026, 11, 5, 23, 59, 59, tzinfo=timezone.utc)

    def _event(entry_id, start):
        return mocker.Mock(
            EntryID=entry_id, Subject=entry_id,
            Start=start, End=start + timedelta(hours=1), Body="",
        )

    in_bounds = [
        _event("IN-10-25", datetime(2026, 10, 25, 9, 0)),
        _event("IN-11-05", datetime(2026, 11, 5, 9, 0)),
    ]
    out_of_bounds = [_event("OUT-11-06", datetime(2026, 11, 6, 9, 0))]

    _upper_bound_narrow_on_swap_case(mocker, date_from, date_to, in_bounds, out_of_bounds)


def test_search_upper_bound_2026_12_03_day_lt_month_returns_window_items(mocker):
    """Upper-bound mirror: `date_to`'s day (3) is less than its month
    (12)."""
    date_from = datetime(2026, 11, 20, 0, 0, tzinfo=timezone.utc)
    date_to = datetime(2026, 12, 3, 23, 59, 59, tzinfo=timezone.utc)

    def _event(entry_id, start):
        return mocker.Mock(
            EntryID=entry_id, Subject=entry_id,
            Start=start, End=start + timedelta(hours=1), Body="",
        )

    in_bounds = [
        _event("IN-11-25", datetime(2026, 11, 25, 9, 0)),
        _event("IN-12-03", datetime(2026, 12, 3, 9, 0)),
    ]
    out_of_bounds = [_event("OUT-12-04", datetime(2026, 12, 4, 9, 0))]

    _upper_bound_narrow_on_swap_case(mocker, date_from, date_to, in_bounds, out_of_bounds)


def test_search_restrict_filter_exact_dasl_string_both_bounds_no_bracket_syntax(mocker):
    """Query-construction-layer assertion: the emitted `Restrict()` filter
    STRING must carry the exact DASL `@SQL=` URN syntax and the exact ISO
    literal for BOTH bounds — asserted with DIFFERENT day/month values on
    each bound so a day/month transposition on either side would be caught
    by an exact string comparison, not just a downstream Python re-check.
    Also asserts no Jet bracket-property date comparison (`[Start] >=`)
    remains, so a regression to the pre-hotfix syntax can never pass by
    surviving only because the boundary re-check happens to trim results
    to the right set."""
    from tools.outlook_adapter import OutlookCalendarAdapter

    dispatch_mock = _install_fake_win32com(mocker)
    outlook_app = mocker.Mock(name="OutlookApplication")
    dispatch_mock.return_value = outlook_app
    namespace = mocker.Mock(name="Namespace")
    outlook_app.GetNamespace.return_value = namespace
    folder = mocker.Mock(name="CalendarFolder")
    namespace.GetDefaultFolder.return_value = folder
    items = mocker.Mock(name="Items")
    folder.Items = items
    restricted_items = mocker.Mock(name="RestrictedItems")
    items.Restrict.return_value = restricted_items
    restricted_items.__iter__ = mocker.Mock(return_value=iter([]))

    adapter = OutlookCalendarAdapter()
    date_from = datetime(2026, 6, 2, 8, 0, tzinfo=timezone.utc)  # day < month
    date_to = datetime(2026, 11, 5, 17, 30, tzinfo=timezone.utc)  # day < month, different month

    adapter.search(date_from, date_to)

    items.Restrict.assert_called_once()
    restrict_arg = items.Restrict.call_args.args[0]
    assert restrict_arg == (
        '@SQL="urn:schemas:calendar:dtstart" >= \'2026-06-02 08:00\' '
        'AND "urn:schemas:calendar:dtend" <= \'2026-11-05 17:30\''
    )
    assert not re.search(r"\[Start\]|\[End\]", restrict_arg)


def test_search_filters_by_subject_case_insensitive(mocker):
    """Triangulation: the adapter's own subject filter (applied after
    Restrict()) must be case-insensitive, matching CalendarPort's contract."""
    from tools.outlook_adapter import OutlookCalendarAdapter

    dispatch_mock = _install_fake_win32com(mocker)
    outlook_app = mocker.Mock()
    dispatch_mock.return_value = outlook_app
    namespace = mocker.Mock()
    outlook_app.GetNamespace.return_value = namespace
    folder = mocker.Mock()
    namespace.GetDefaultFolder.return_value = folder
    items = mocker.Mock()
    folder.Items = items
    restricted_items = mocker.Mock()
    items.Restrict.return_value = restricted_items

    matching = mocker.Mock(
        EntryID="A1", Subject="TAREAS (bloque)",
        Start=datetime(2026, 7, 27, 9, 0), End=datetime(2026, 7, 27, 9, 30), Body="",
    )
    non_matching = mocker.Mock(
        EntryID="A2", Subject="Otra cosa",
        Start=datetime(2026, 7, 27, 11, 0), End=datetime(2026, 7, 27, 11, 30), Body="",
    )
    restricted_items.__iter__ = mocker.Mock(return_value=iter([matching, non_matching]))

    adapter = OutlookCalendarAdapter()
    results = adapter.search(
        datetime(2026, 7, 27, tzinfo=timezone.utc),
        datetime(2026, 7, 28, tzinfo=timezone.utc),
        subject="tareas",
    )

    assert len(results) == 1
    assert results[0].entry_id == "A1"


def test_get_event_uses_get_item_from_id(mocker):
    from tools.outlook_adapter import OutlookCalendarAdapter

    dispatch_mock = _install_fake_win32com(mocker)
    outlook_app = mocker.Mock()
    dispatch_mock.return_value = outlook_app
    namespace = mocker.Mock()
    outlook_app.GetNamespace.return_value = namespace
    fake_item = mocker.Mock(
        EntryID="ABC123",
        Subject="Tareas (bloque)",
        Start=datetime(2026, 7, 27, 9, 0),
        End=datetime(2026, 7, 27, 9, 30),
        Body="Politica ADN",
    )
    namespace.GetItemFromID.return_value = fake_item

    adapter = OutlookCalendarAdapter()
    result = adapter.get_event("ABC123")

    namespace.GetItemFromID.assert_called_once_with("ABC123")
    namespace.GetDefaultFolder.assert_not_called()  # not a re-Restrict scan
    assert result.entry_id == "ABC123"
    assert result.body == "Politica ADN"
    assert result.start.tzinfo is not None


def test_get_event_unknown_entry_id_raises_not_found(mocker):
    from tools.outlook_adapter import OutlookCalendarAdapter

    dispatch_mock = _install_fake_win32com(mocker)
    outlook_app = mocker.Mock()
    dispatch_mock.return_value = outlook_app
    namespace = mocker.Mock()
    outlook_app.GetNamespace.return_value = namespace
    namespace.GetItemFromID.side_effect = Exception("MK_E_INVALIDEXTENSION")

    adapter = OutlookCalendarAdapter()

    with pytest.raises(EventNotFoundError):
        adapter.get_event("BAD-ID")


def test_dispatch_failure_raises_outlook_unavailable_error(mocker):
    from tools.outlook_adapter import OutlookCalendarAdapter

    dispatch_mock = _install_fake_win32com(mocker)
    dispatch_mock.side_effect = Exception("Outlook is not running")

    adapter = OutlookCalendarAdapter()

    with pytest.raises(OutlookUnavailableError):
        adapter.search(
            datetime(2026, 7, 27, tzinfo=timezone.utc),
            datetime(2026, 7, 28, tzinfo=timezone.utc),
        )

    with pytest.raises(OutlookUnavailableError):
        adapter.get_event("ABC123")


def test_win32com_import_error_raises_outlook_unavailable_error(mocker):
    """Triangulation: when win32com genuinely isn't importable (this host's
    real state outside of test mocking), the adapter must map the
    ImportError to OutlookUnavailableError, not let it crash the caller —
    outlook-com-adapter spec's "Adapter Selection at Runtime" requirement."""
    from tools.outlook_adapter import OutlookCalendarAdapter

    mocker.patch.dict(sys.modules)
    sys.modules.pop("win32com", None)
    sys.modules.pop("win32com.client", None)
    mocker.patch.dict(sys.modules, {"win32com.client": None})

    adapter = OutlookCalendarAdapter()

    with pytest.raises(OutlookUnavailableError):
        adapter.get_event("ABC123")


def test_search_uses_configured_calendar_folder_id(mocker):
    """outlook-com-adapter spec's "Configurable Folder Ids" requirement:
    a configured `calendar_folder_id` in settings.yaml is passed to
    GetDefaultFolder(), not the hardcoded default."""
    from tools.outlook_adapter import OutlookCalendarAdapter

    mocker.patch(
        "tools.outlook_adapter.load_settings",
        return_value={"calendar_folder_id": 42},
    )
    dispatch_mock = _install_fake_win32com(mocker)
    outlook_app = mocker.Mock(name="OutlookApplication")
    dispatch_mock.return_value = outlook_app
    namespace = mocker.Mock(name="Namespace")
    outlook_app.GetNamespace.return_value = namespace
    folder = mocker.Mock(name="CalendarFolder")
    namespace.GetDefaultFolder.return_value = folder
    items = mocker.Mock(name="Items")
    folder.Items = items
    restricted_items = mocker.Mock(name="RestrictedItems")
    items.Restrict.return_value = restricted_items
    restricted_items.__iter__ = mocker.Mock(return_value=iter([]))

    adapter = OutlookCalendarAdapter()
    adapter.search(
        datetime(2026, 7, 27, tzinfo=timezone.utc),
        datetime(2026, 7, 28, tzinfo=timezone.utc),
    )

    namespace.GetDefaultFolder.assert_called_once_with(42)


def test_search_absent_calendar_folder_id_falls_back_to_default_9(mocker):
    """Absent `calendar_folder_id` key -> the documented default (9,
    olFolderCalendar)."""
    from tools.outlook_adapter import OutlookCalendarAdapter

    mocker.patch("tools.outlook_adapter.load_settings", return_value={})
    dispatch_mock = _install_fake_win32com(mocker)
    outlook_app = mocker.Mock(name="OutlookApplication")
    dispatch_mock.return_value = outlook_app
    namespace = mocker.Mock(name="Namespace")
    outlook_app.GetNamespace.return_value = namespace
    folder = mocker.Mock(name="CalendarFolder")
    namespace.GetDefaultFolder.return_value = folder
    items = mocker.Mock(name="Items")
    folder.Items = items
    restricted_items = mocker.Mock(name="RestrictedItems")
    items.Restrict.return_value = restricted_items
    restricted_items.__iter__ = mocker.Mock(return_value=iter([]))

    adapter = OutlookCalendarAdapter()
    adapter.search(
        datetime(2026, 7, 27, tzinfo=timezone.utc),
        datetime(2026, 7, 28, tzinfo=timezone.utc),
    )

    namespace.GetDefaultFolder.assert_called_once_with(9)


def test_settings_yaml_declares_calendar_folder_id_9():
    """Asserts the literal key is present in the real, unmocked
    config/settings.yaml — mirrors tests/test_mail_tools.py's
    test_settings_yaml_declares_mail_lookback_days_90 precedent, now that
    calendar_folder_id is a live key (config-live-folders change)."""
    from tools.settings import load_settings

    settings = load_settings()

    assert "calendar_folder_id" in settings
    assert settings["calendar_folder_id"] == 9


def test_pythoncom_import_error_raises_outlook_unavailable_error(mocker):
    """Isolates the "pythoncom import fails" half of `_dispatch_outlook`'s
    shared `try: import pythoncom; import win32com.client / except
    ImportError` block — as opposed to a win32com-only or combined failure
    (see test_win32com_import_error_raises_outlook_unavailable_error above).
    A real fake `win32com.client` is installed directly (bypassing
    `_install_fake_win32com`'s own pythoncom auto-install) to prove it would
    have succeeded had `import pythoncom` not failed first."""
    from tools.outlook_adapter import OutlookCalendarAdapter

    mocker.patch.dict(sys.modules)
    sys.modules.pop("pythoncom", None)
    mocker.patch.dict(sys.modules, {"pythoncom": None})
    fake_win32com = types.ModuleType("win32com")
    fake_win32com_client = types.ModuleType("win32com.client")
    fake_win32com_client.Dispatch = mocker.Mock(name="Dispatch")
    fake_win32com.client = fake_win32com_client
    sys.modules["win32com"] = fake_win32com
    sys.modules["win32com.client"] = fake_win32com_client

    adapter = OutlookCalendarAdapter()

    with pytest.raises(OutlookUnavailableError):
        adapter.get_event("ABC123")


def test_search_bounds_result_to_limit_plus_one_no_early_stop_iteration(mocker):
    """search-result-caps (BUG-002) "+1 peek" convention still holds — the
    returned list is bounded to `limit + 1` rows, so the tool layer can
    flag `results_truncated` from the length alone — but the *mechanism*
    changed with the date-dasl-and-recurrence hotfix: `search()` no longer
    early-stops mid-iteration (that relied on a descending, newest-first
    Restrict()-sourced order, which broke `IncludeRecurrences` expansion —
    BUG-005 part 2). The full ascending-sourced, Restrict()-bounded
    collection is now consumed, then sorted newest-first and sliced in
    Python."""
    from tools.outlook_adapter import OutlookCalendarAdapter

    dispatch_mock = _install_fake_win32com(mocker)
    outlook_app = mocker.Mock(name="OutlookApplication")
    dispatch_mock.return_value = outlook_app
    namespace = mocker.Mock(name="Namespace")
    outlook_app.GetNamespace.return_value = namespace
    folder = mocker.Mock(name="CalendarFolder")
    namespace.GetDefaultFolder.return_value = folder
    items = mocker.Mock(name="Items")
    folder.Items = items
    restricted_items = mocker.Mock(name="RestrictedItems")
    items.Restrict.return_value = restricted_items

    # Seeded oldest-first (5 events), the ascending order Outlook COM now
    # delivers post-fix.
    seeded = [
        mocker.Mock(
            EntryID=f"E{i}", Subject="Reunion",
            Start=datetime(2026, 7, 23 + i, 9, 0, tzinfo=timezone.utc),
            End=datetime(2026, 7, 23 + i, 9, 30, tzinfo=timezone.utc), Body="",
        )
        for i in range(5)
    ]
    consumed: list[str] = []

    def _tracking_iter():
        for item in seeded:
            consumed.append(item.EntryID)
            yield item

    restricted_items.__iter__ = mocker.Mock(side_effect=lambda: _tracking_iter())

    adapter = OutlookCalendarAdapter()
    date_from = datetime(2026, 7, 1, tzinfo=timezone.utc)
    date_to = datetime(2026, 7, 31, 23, 59, 59, tzinfo=timezone.utc)

    results = adapter.search(date_from, date_to, limit=3)

    # No early stop: every seeded item is consumed regardless of `limit`.
    assert consumed == ["E0", "E1", "E2", "E3", "E4"]
    # But the *returned* list is still capped to limit + 1, newest-first.
    assert [r.entry_id for r in results] == ["E4", "E3", "E2", "E1"]


def test_search_returns_all_when_under_limit_no_early_stop(mocker):
    from tools.outlook_adapter import OutlookCalendarAdapter

    dispatch_mock = _install_fake_win32com(mocker)
    outlook_app = mocker.Mock(name="OutlookApplication")
    dispatch_mock.return_value = outlook_app
    namespace = mocker.Mock(name="Namespace")
    outlook_app.GetNamespace.return_value = namespace
    folder = mocker.Mock(name="CalendarFolder")
    namespace.GetDefaultFolder.return_value = folder
    items = mocker.Mock(name="Items")
    folder.Items = items
    restricted_items = mocker.Mock(name="RestrictedItems")
    items.Restrict.return_value = restricted_items

    seeded = [
        mocker.Mock(
            EntryID=f"E{i}", Subject="Reunion",
            Start=datetime(2026, 7, 27 - i, 9, 0, tzinfo=timezone.utc),
            End=datetime(2026, 7, 27 - i, 9, 30, tzinfo=timezone.utc), Body="",
        )
        for i in range(2)
    ]
    restricted_items.__iter__ = mocker.Mock(return_value=iter(seeded))

    adapter = OutlookCalendarAdapter()
    date_from = datetime(2026, 7, 1, tzinfo=timezone.utc)
    date_to = datetime(2026, 7, 31, 23, 59, 59, tzinfo=timezone.utc)

    results = adapter.search(date_from, date_to, limit=50)

    assert [r.entry_id for r in results] == ["E0", "E1"]


def test_search_aware_com_datetime_vs_naive_request_bound_does_not_raise(mocker):
    """datetime-tz hotfix (2026-08-26): real Outlook QA regression. Real
    pywintypes.datetime `item.Start`/`item.End` values come back
    timezone-AWARE (a fixed offset), unlike every other fake in this file
    which uses naive `datetime(...)` to simulate Outlook COM's local time.
    Meanwhile `SearchRequest.date_from`/`date_to` (models/schemas.py) have
    no tz-aware validator, so a naive bound can legitimately reach the
    adapter. Before the fix, the boundary re-check's `start < date_from`
    raised "can't compare offset-naive and offset-aware datetimes"."""
    from tools.outlook_adapter import OutlookCalendarAdapter

    dispatch_mock = _install_fake_win32com(mocker)
    outlook_app = mocker.Mock(name="OutlookApplication")
    dispatch_mock.return_value = outlook_app
    namespace = mocker.Mock(name="Namespace")
    outlook_app.GetNamespace.return_value = namespace
    folder = mocker.Mock(name="CalendarFolder")
    namespace.GetDefaultFolder.return_value = folder
    items = mocker.Mock(name="Items")
    folder.Items = items
    restricted_items = mocker.Mock(name="RestrictedItems")
    items.Restrict.return_value = restricted_items

    aware_offset = timezone(timedelta(hours=2))  # e.g. CEST, like real Outlook
    fake_item = mocker.Mock(
        EntryID="ABC123", Subject="Tareas (bloque)",
        Start=datetime(2026, 7, 27, 9, 0, tzinfo=aware_offset),
        End=datetime(2026, 7, 27, 9, 30, tzinfo=aware_offset),
        Body="",
    )
    restricted_items.__iter__ = mocker.Mock(return_value=iter([fake_item]))

    adapter = OutlookCalendarAdapter()
    # Naive request bounds — legal per SearchRequest's schema, no tzinfo.
    date_from = datetime(2026, 7, 27, 0, 0)
    date_to = datetime(2026, 7, 27, 23, 59, 59)

    results = adapter.search(date_from, date_to, subject="tareas")

    assert [r.entry_id for r in results] == ["ABC123"]


def test_search_naive_all_day_item_vs_aware_request_bound_does_not_raise(mocker):
    """Defensive companion to the aware-item/naive-bound case above:
    Outlook all-day events can return naive Start/End even on real
    Windows. Naive item + aware request bound must not raise either."""
    from tools.outlook_adapter import OutlookCalendarAdapter

    dispatch_mock = _install_fake_win32com(mocker)
    outlook_app = mocker.Mock(name="OutlookApplication")
    dispatch_mock.return_value = outlook_app
    namespace = mocker.Mock(name="Namespace")
    outlook_app.GetNamespace.return_value = namespace
    folder = mocker.Mock(name="CalendarFolder")
    namespace.GetDefaultFolder.return_value = folder
    items = mocker.Mock(name="Items")
    folder.Items = items
    restricted_items = mocker.Mock(name="RestrictedItems")
    items.Restrict.return_value = restricted_items

    fake_item = mocker.Mock(
        EntryID="ALLDAY1", Subject="Vacaciones",
        Start=datetime(2026, 7, 27, 0, 0),
        End=datetime(2026, 7, 27, 23, 59, 59),
        Body="",
    )
    restricted_items.__iter__ = mocker.Mock(return_value=iter([fake_item]))

    adapter = OutlookCalendarAdapter()
    # Wide enough to tolerate the naive item's host-local-tz attachment
    # (local_timezone()) landing on either side of a UTC calendar-day
    # boundary — this test is about the naive/aware TypeError, not about
    # pinning an exact tz offset.
    date_from = datetime(2026, 7, 20, tzinfo=timezone.utc)
    date_to = datetime(2026, 8, 3, tzinfo=timezone.utc)

    results = adapter.search(date_from, date_to)

    assert [r.entry_id for r in results] == ["ALLDAY1"]


def test_calendar_and_mail_dasl_datetime_emit_identical_literal():
    """Cross-module consistency (design.md's "Duplicate the fix per
    module, not extract a shared helper" decision): both
    `tools/outlook_adapter.py::_dasl_datetime` and
    `tools/mail_adapter.py::_dasl_datetime` must emit the exact same
    literal for the same input, even though the fix was applied
    independently to each duplicate."""
    from tools.mail_adapter import _dasl_datetime as mail_dasl_datetime
    from tools.outlook_adapter import _dasl_datetime as calendar_dasl_datetime

    value = datetime(2026, 3, 12, 9, 5)

    calendar_literal = calendar_dasl_datetime(value)
    mail_literal = mail_dasl_datetime(value)

    assert calendar_literal == mail_literal == "2026-03-12 09:05"
