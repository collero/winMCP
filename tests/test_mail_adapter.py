"""Tests for tools/mail_adapter.py's OutlookMailAdapter — the real,
win32com-backed MailPort implementation.

`win32com` is never installed on this WSL2 dev host (per project policy: it
MUST NOT be pip-installed here, and MUST NOT be imported at module load
time). Every test that exercises `OutlookMailAdapter` therefore injects a
fake `win32com.client` module into `sys.modules` via pytest-mock before
constructing/calling the adapter, so `import win32com.client` (which only
ever happens lazily, inside the adapter's own methods) resolves to a mock
instead of failing. Mirrors `tests/test_task_adapter.py`/
`tests/test_outlook_adapter.py`'s `_install_fake_win32com` technique.

Phase 5: Real Outlook Mail Adapter (outlook-mail-adapter spec)
"""
import importlib
import re
import sys
import types
from datetime import datetime, timedelta, timezone

import pytest

from models.schemas import MailFolder
from tools.errors import MailFolderNotFoundError, MessageNotFoundError, OutlookUnavailableError


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


class _FakeAttachments:
    """A minimal 1-indexed `Attachments` collection stand-in, per the
    outlook-mail-adapter spec's "Attachment Filename Enumeration"
    requirement (`Attachments.Item(i).FileName` for `i` in
    `1..Attachments.Count`)."""

    def __init__(self, filenames):
        self._filenames = list(filenames)
        self.Count = len(self._filenames)

    def Item(self, index):
        return types.SimpleNamespace(FileName=self._filenames[index - 1])


class _AssertingMailItem:
    """A real (non-Mock) mail item stand-in that raises if any mutating
    COM member is invoked, per the outlook-mail-adapter spec's "Read-Only
    Contract" requirement. A plain `mocker.Mock()` would silently accept
    `Save()`/`Move()`/`Delete()` calls and `UnRead =` assignment without
    ever failing, so a real object with raising methods/property is
    required to make this a meaningful test."""

    def __init__(self):
        self.Class = 43
        self.EntryID = "MSG-1"
        self.Subject = "Factura agosto"
        self.SenderName = "Ana Gomez"
        self.SenderEmailAddress = "ana.gomez@example.com"
        self.ReceivedTime = datetime(2026, 8, 10, 9, 0)
        self.SentOn = datetime(2026, 8, 10, 9, 0)
        self.To = "yo@example.com"
        self.Body = "Adjunto la factura."
        self.HTMLBody = "<p>Adjunto la factura.</p>"
        self.Attachments = _FakeAttachments(["factura.pdf"])
        self._unread = False

    def Save(self):
        raise AssertionError("Save() must never be called — read-only contract")

    def Move(self, *_args, **_kwargs):
        raise AssertionError("Move() must never be called — read-only contract")

    def Delete(self):
        raise AssertionError("Delete() must never be called — read-only contract")

    @property
    def UnRead(self):
        return self._unread

    @UnRead.setter
    def UnRead(self, _value):
        raise AssertionError("UnRead must never be assigned — read-only contract")


class _HTMLBodyGuardMailItem:
    """A mail item stand-in whose `HTMLBody` property raises if accessed,
    per the outlook-mail-adapter spec's "HTMLBody is not accessed by
    default" scenario. A plain `mocker.Mock()` would silently return an
    auto-generated attribute for `HTMLBody` without ever failing, so a real
    object with a raising property is required to make this a meaningful
    test."""

    def __init__(self):
        self.Class = 43
        self.EntryID = "MSG-5"
        self.Subject = "Aviso"
        self.SenderName = "Ana Gomez"
        self.SenderEmailAddress = "ana.gomez@example.com"
        self.ReceivedTime = datetime(2026, 8, 12, 9, 0, tzinfo=timezone.utc)
        self.SentOn = None
        self.To = ""
        self.Body = "Texto plano"
        self.Attachments = _FakeAttachments([])

    @property
    def HTMLBody(self):
        raise AssertionError(
            "HTMLBody must not be accessed unless include_html_body=True"
        )


def test_win32com_not_imported_at_module_level(mocker):
    mocker.patch.dict(sys.modules)
    sys.modules.pop("win32com", None)
    sys.modules.pop("win32com.client", None)

    import tools.mail_adapter as module

    importlib.reload(module)

    assert "win32com" not in sys.modules
    assert "win32com.client" not in sys.modules


def test_pythoncom_not_imported_at_module_level(mocker):
    mocker.patch.dict(sys.modules)
    sys.modules.pop("pythoncom", None)

    import tools.mail_adapter as module

    importlib.reload(module)

    assert "pythoncom" not in sys.modules


def test_search_calls_coinitialize_before_dispatch(mocker):
    """outlook-com-adapter spec's "Per-Thread COM Initialization"
    requirement: pythoncom.CoInitialize() MUST be called before
    win32com.client.Dispatch() on a search() call."""
    from tools.mail_adapter import OutlookMailAdapter

    coinitialize_mock = _install_fake_pythoncom(mocker)
    dispatch_mock = _install_fake_win32com(mocker)
    manager = mocker.Mock()
    manager.attach_mock(coinitialize_mock, "CoInitialize")
    manager.attach_mock(dispatch_mock, "Dispatch")

    outlook_app = mocker.Mock(name="OutlookApplication")
    dispatch_mock.return_value = outlook_app
    namespace = mocker.Mock(name="Namespace")
    outlook_app.GetNamespace.return_value = namespace
    folder = mocker.Mock(name="InboxFolder")
    namespace.GetDefaultFolder.return_value = folder
    items = mocker.Mock(name="Items")
    folder.Items = items
    restricted_items = mocker.Mock(name="RestrictedItems")
    items.Restrict.return_value = restricted_items
    restricted_items.__iter__ = mocker.Mock(return_value=iter([]))

    adapter = OutlookMailAdapter()
    date_from = datetime(2026, 8, 1, tzinfo=timezone.utc)
    date_to = datetime(2026, 8, 31, 23, 59, 59, tzinfo=timezone.utc)
    adapter.search(MailFolder.INBOX, date_from=date_from, date_to=date_to)

    call_names = [call[0] for call in manager.mock_calls]
    assert "CoInitialize" in call_names
    assert "Dispatch" in call_names
    assert call_names.index("CoInitialize") < call_names.index("Dispatch")


def test_get_message_calls_coinitialize_before_dispatch(mocker):
    """Mirrors test_search_calls_coinitialize_before_dispatch for the
    get_message() call path."""
    from tools.mail_adapter import OutlookMailAdapter

    coinitialize_mock = _install_fake_pythoncom(mocker)
    dispatch_mock = _install_fake_win32com(mocker)
    manager = mocker.Mock()
    manager.attach_mock(coinitialize_mock, "CoInitialize")
    manager.attach_mock(dispatch_mock, "Dispatch")

    outlook_app = mocker.Mock(name="OutlookApplication")
    dispatch_mock.return_value = outlook_app
    namespace = mocker.Mock(name="Namespace")
    outlook_app.GetNamespace.return_value = namespace
    mail_item = mocker.Mock(
        Class=43, EntryID="MSG-1", Subject="Factura agosto", SenderName="Ana Gomez",
        SenderEmailAddress="ana.gomez@example.com",
        ReceivedTime=datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc),
        SentOn=None, To="yo@example.com", Body="Adjunto la factura.",
        Attachments=mocker.Mock(
            Count=1, Item=mocker.Mock(return_value=types.SimpleNamespace(FileName="adjunto.pdf"))
        ),
    )
    namespace.GetItemFromID.return_value = mail_item

    adapter = OutlookMailAdapter()
    adapter.get_message("MSG-1")

    call_names = [call[0] for call in manager.mock_calls]
    assert "CoInitialize" in call_names
    assert "Dispatch" in call_names
    assert call_names.index("CoInitialize") < call_names.index("Dispatch")


def test_inbox_search_restricts_on_received_time(mocker):
    from tools.mail_adapter import OutlookMailAdapter

    dispatch_mock = _install_fake_win32com(mocker)
    outlook_app = mocker.Mock(name="OutlookApplication")
    dispatch_mock.return_value = outlook_app
    namespace = mocker.Mock(name="Namespace")
    outlook_app.GetNamespace.return_value = namespace
    folder = mocker.Mock(name="InboxFolder")
    namespace.GetDefaultFolder.return_value = folder
    items = mocker.Mock(name="Items")
    folder.Items = items
    restricted_items = mocker.Mock(name="RestrictedItems")
    items.Restrict.return_value = restricted_items

    fake_item = mocker.Mock(
        Class=43,
        EntryID="M1",
        Subject="Factura agosto",
        SenderName="Ana Gomez",
        SenderEmailAddress="ana.gomez@example.com",
        ReceivedTime=datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc),
        Attachments=mocker.Mock(Count=0),
    )
    restricted_items.__iter__ = mocker.Mock(return_value=iter([fake_item]))

    adapter = OutlookMailAdapter()
    date_from = datetime(2026, 8, 1, 0, 0, tzinfo=timezone.utc)
    date_to = datetime(2026, 8, 31, 23, 59, 59, tzinfo=timezone.utc)

    results = adapter.search(MailFolder.INBOX, date_from=date_from, date_to=date_to)

    dispatch_mock.assert_called_once_with("Outlook.Application")
    outlook_app.GetNamespace.assert_called_once_with("MAPI")
    namespace.GetDefaultFolder.assert_called_once_with(6)
    items.Restrict.assert_called_once()
    restrict_arg = items.Restrict.call_args.args[0]
    # BUG-004 hotfix: DASL `@SQL=` against a quoted property URN, not
    # Jet's bare bracket-property syntax — see
    # tests/test_outlook_adapter.py's identically-motivated assertion.
    assert restrict_arg.startswith('@SQL="urn:schemas:httpmail:datereceived" >=')
    assert '"urn:schemas:httpmail:datereceived" <=' in restrict_arg
    assert "2026-08-01" in restrict_arg
    assert "2026-08-31" in restrict_arg

    assert len(results) == 1
    assert results[0].entry_id == "M1"


def test_sent_search_restricts_on_sent_on(mocker):
    from tools.mail_adapter import OutlookMailAdapter

    dispatch_mock = _install_fake_win32com(mocker)
    outlook_app = mocker.Mock(name="OutlookApplication")
    dispatch_mock.return_value = outlook_app
    namespace = mocker.Mock(name="Namespace")
    outlook_app.GetNamespace.return_value = namespace
    folder = mocker.Mock(name="SentFolder")
    namespace.GetDefaultFolder.return_value = folder
    items = mocker.Mock(name="Items")
    folder.Items = items
    restricted_items = mocker.Mock(name="RestrictedItems")
    items.Restrict.return_value = restricted_items

    fake_item = mocker.Mock(
        Class=43,
        EntryID="M10",
        Subject="RE: Factura agosto",
        SenderName="Yo",
        SenderEmailAddress="yo@example.com",
        SentOn=datetime(2026, 8, 11, 9, 0, tzinfo=timezone.utc),
        To="ana.gomez@example.com",
        Attachments=mocker.Mock(Count=0),
    )
    restricted_items.__iter__ = mocker.Mock(return_value=iter([fake_item]))

    adapter = OutlookMailAdapter()
    date_from = datetime(2026, 8, 1, 0, 0, tzinfo=timezone.utc)
    date_to = datetime(2026, 8, 31, 23, 59, 59, tzinfo=timezone.utc)

    results = adapter.search(MailFolder.SENT, date_from=date_from, date_to=date_to)

    namespace.GetDefaultFolder.assert_called_once_with(5)
    items.Restrict.assert_called_once()
    restrict_arg = items.Restrict.call_args.args[0]
    assert restrict_arg.startswith('@SQL="urn:schemas:httpmail:datesent" >=')
    assert '"urn:schemas:httpmail:datesent" <=' in restrict_arg

    assert len(results) == 1
    assert results[0].entry_id == "M10"


def test_dasl_datetime_emits_iso_ordered_literal():
    """outlook-mail-adapter spec's "Locale-Invariant Restrict Date
    Literals" requirement: the emitted literal must be ISO-ordered, 24-hour,
    and must never match the old ambiguous `MM/DD/YYYY` shape — BUG-003's
    root cause. Mirrors tests/test_outlook_adapter.py's identically-named
    test for the calendar adapter."""
    from tools.mail_adapter import _dasl_datetime

    literal = _dasl_datetime(datetime(2026, 3, 12, 0, 0))

    assert literal == "2026-03-12 00:00"
    assert not re.search(r"\d{2}/\d{2}/\d{4}", literal)


def test_search_transposition_prone_range_returns_only_bound_days(mocker):
    """Reproduces BUG-003's live-confirmed Case 1 for `folder="inbox"`
    (`[ReceivedTime]`), mirroring
    tests/test_outlook_adapter.py::test_search_transposition_prone_range_returns_only_bound_days."""
    from tools.mail_adapter import OutlookMailAdapter

    dispatch_mock = _install_fake_win32com(mocker)
    outlook_app = mocker.Mock(name="OutlookApplication")
    dispatch_mock.return_value = outlook_app
    namespace = mocker.Mock(name="Namespace")
    outlook_app.GetNamespace.return_value = namespace
    folder = mocker.Mock(name="InboxFolder")
    namespace.GetDefaultFolder.return_value = folder
    items = mocker.Mock(name="Items")
    folder.Items = items
    restricted_items = mocker.Mock(name="RestrictedItems")
    items.Restrict.return_value = restricted_items

    def _msg(entry_id, received):
        return mocker.Mock(
            Class=43, EntryID=entry_id, Subject=f"Mail {entry_id}",
            SenderName="Ana Gomez", SenderEmailAddress="ana.gomez@example.com",
            ReceivedTime=received, Attachments=mocker.Mock(Count=0),
        )

    in_bounds_06_08 = _msg("E1", datetime(2026, 6, 8, 9, 0))
    in_bounds_06_09 = _msg("E2", datetime(2026, 6, 9, 9, 0))
    transposed_09_04 = _msg("E3", datetime(2026, 9, 4, 9, 0))
    restricted_items.__iter__ = mocker.Mock(
        return_value=iter([in_bounds_06_08, in_bounds_06_09, transposed_09_04])
    )

    adapter = OutlookMailAdapter()
    date_from = datetime(2026, 6, 6, 0, 0, tzinfo=timezone.utc)
    date_to = datetime(2026, 6, 9, 23, 59, 59, tzinfo=timezone.utc)

    results = adapter.search(MailFolder.INBOX, date_from=date_from, date_to=date_to)

    assert {r.entry_id for r in results} == {"E1", "E2"}


def test_search_full_month_crossing_range_excludes_december(mocker):
    """Reproduces BUG-003's live-confirmed Case 4 for `folder="sent"`
    (`[SentOn]`), mirroring
    tests/test_outlook_adapter.py::test_search_full_month_crossing_range_excludes_december."""
    from tools.mail_adapter import OutlookMailAdapter

    dispatch_mock = _install_fake_win32com(mocker)
    outlook_app = mocker.Mock(name="OutlookApplication")
    dispatch_mock.return_value = outlook_app
    namespace = mocker.Mock(name="Namespace")
    outlook_app.GetNamespace.return_value = namespace
    folder = mocker.Mock(name="SentFolder")
    namespace.GetDefaultFolder.return_value = folder
    items = mocker.Mock(name="Items")
    folder.Items = items
    restricted_items = mocker.Mock(name="RestrictedItems")
    items.Restrict.return_value = restricted_items

    def _msg(entry_id, sent_on):
        return mocker.Mock(
            Class=43, EntryID=entry_id, Subject=f"Mail {entry_id}",
            SenderName="Yo", SenderEmailAddress="yo@example.com",
            SentOn=sent_on, To="ana.gomez@example.com",
            Attachments=mocker.Mock(Count=0),
        )

    march_msg = _msg("M1", datetime(2026, 3, 15, 9, 0))
    april_msg = _msg("M2", datetime(2026, 4, 5, 9, 0))
    transposed_december_msg = _msg("M3", datetime(2026, 12, 3, 9, 0))
    restricted_items.__iter__ = mocker.Mock(
        return_value=iter([march_msg, april_msg, transposed_december_msg])
    )

    adapter = OutlookMailAdapter()
    date_from = datetime(2026, 3, 12, 0, 0, tzinfo=timezone.utc)
    date_to = datetime(2026, 4, 12, 0, 0, tzinfo=timezone.utc)

    results = adapter.search(MailFolder.SENT, date_from=date_from, date_to=date_to)

    assert {r.entry_id for r in results} == {"M1", "M2"}


def test_search_control_range_day_ge_13_unchanged(mocker):
    """Control case: a range whose bound days are all >= 13 is unambiguous
    under either locale reading even pre-fix — must keep returning exactly
    the same messages post-fix (no regression from the new boundary
    re-check). Mirrors
    tests/test_outlook_adapter.py::test_search_control_range_day_ge_13_unchanged."""
    from tools.mail_adapter import OutlookMailAdapter

    dispatch_mock = _install_fake_win32com(mocker)
    outlook_app = mocker.Mock(name="OutlookApplication")
    dispatch_mock.return_value = outlook_app
    namespace = mocker.Mock(name="Namespace")
    outlook_app.GetNamespace.return_value = namespace
    folder = mocker.Mock(name="InboxFolder")
    namespace.GetDefaultFolder.return_value = folder
    items = mocker.Mock(name="Items")
    folder.Items = items
    restricted_items = mocker.Mock(name="RestrictedItems")
    items.Restrict.return_value = restricted_items

    seeded = [
        mocker.Mock(
            Class=43, EntryID=f"C{day}", Subject=f"Mail {day}",
            SenderName="Ana Gomez", SenderEmailAddress="ana.gomez@example.com",
            ReceivedTime=datetime(2026, 6, day, 9, 0), Attachments=mocker.Mock(Count=0),
        )
        for day in (22, 23, 24, 25)
    ]
    restricted_items.__iter__ = mocker.Mock(return_value=iter(seeded))

    adapter = OutlookMailAdapter()
    date_from = datetime(2026, 6, 20, 0, 0, tzinfo=timezone.utc)
    date_to = datetime(2026, 6, 25, 23, 59, 59, tzinfo=timezone.utc)

    results = adapter.search(MailFolder.INBOX, date_from=date_from, date_to=date_to)

    assert {r.entry_id for r in results} == {"C22", "C23", "C24", "C25"}


def _upper_bound_narrow_on_swap_case(
    mocker, folder, date_from, date_to, in_bounds, out_of_bounds
):
    """Shared body for the mail upper-bound sweep cases below — the mirror
    of `test_search_transposition_prone_range_returns_only_bound_days` /
    `test_search_full_month_crossing_range_excludes_december` (which sweep
    the LOWER bound's day across the <=12/>=13 boundary while the upper
    bound is held safely out of the ambiguous range), and identical in
    intent to
    tests/test_outlook_adapter.py::_upper_bound_narrow_on_swap_case. A
    `date_to` whose day is less than its month (e.g. `..2026-06-02`) is a
    "narrow-on-swap": a locale-transposed reading of the literal would
    produce an EARLIER date than requested, which would make real
    Outlook's Restrict() silently EXCLUDE valid in-window items before
    they ever reach the Python-side boundary re-check — a re-check can
    only drop over-included items, never rescue ones Restrict() wrongly
    dropped. Since Restrict() is mocked here, the return-value assertion
    is a behavioral safety net; the DASL-string assertion is what actually
    guards against the transposition regression.

    `in_bounds`/`out_of_bounds` are lists of (entry_id, date) tuples."""
    from tools.mail_adapter import OutlookMailAdapter, _dasl_datetime

    date_field = "ReceivedTime" if folder == MailFolder.INBOX else "SentOn"
    default_folder_id = 6 if folder == MailFolder.INBOX else 5
    dasl_prop = (
        '"urn:schemas:httpmail:datereceived"'
        if folder == MailFolder.INBOX
        else '"urn:schemas:httpmail:datesent"'
    )

    dispatch_mock = _install_fake_win32com(mocker)
    outlook_app = mocker.Mock(name="OutlookApplication")
    dispatch_mock.return_value = outlook_app
    namespace = mocker.Mock(name="Namespace")
    outlook_app.GetNamespace.return_value = namespace
    mail_folder = mocker.Mock(name="MailFolder")
    namespace.GetDefaultFolder.return_value = mail_folder
    items = mocker.Mock(name="Items")
    mail_folder.Items = items
    restricted_items = mocker.Mock(name="RestrictedItems")
    items.Restrict.return_value = restricted_items

    def _msg(entry_id, date_value):
        kwargs = {
            "Class": 43, "EntryID": entry_id, "Subject": entry_id,
            "SenderName": "Ana Gomez", "SenderEmailAddress": "ana.gomez@example.com",
            "To": "ana.gomez@example.com", "Attachments": mocker.Mock(Count=0),
            date_field: date_value,
        }
        return mocker.Mock(**kwargs)

    seeded = [_msg(entry_id, date_value) for entry_id, date_value in [*in_bounds, *out_of_bounds]]
    restricted_items.__iter__ = mocker.Mock(return_value=iter(seeded))

    adapter = OutlookMailAdapter()
    results = adapter.search(folder, date_from=date_from, date_to=date_to)

    namespace.GetDefaultFolder.assert_called_once_with(default_folder_id)
    items.Restrict.assert_called_once()
    restrict_arg = items.Restrict.call_args.args[0]
    assert restrict_arg.startswith(f"@SQL={dasl_prop} >=")
    assert f"{dasl_prop} <=" in restrict_arg
    assert _dasl_datetime(date_from) in restrict_arg
    assert _dasl_datetime(date_to) in restrict_arg
    # No Jet bracket-property date comparison must remain.
    assert not re.search(r"\[ReceivedTime\]|\[SentOn\]", restrict_arg)

    assert {r.entry_id for r in results} == {entry_id for entry_id, _ in in_bounds}


def test_inbox_search_upper_bound_2026_06_02_day_lt_month_returns_window_items(mocker):
    """Upper-bound mirror of the lower-bound sweep for `folder="inbox"`:
    `date_to`'s day (2) is less than its month (6)."""
    date_from = datetime(2026, 5, 20, 0, 0, tzinfo=timezone.utc)
    date_to = datetime(2026, 6, 2, 23, 59, 59, tzinfo=timezone.utc)

    in_bounds = [
        ("IN-05-28", datetime(2026, 5, 28, 9, 0)),
        ("IN-06-02", datetime(2026, 6, 2, 9, 0)),  # right at the upper boundary day
    ]
    out_of_bounds = [("OUT-06-03", datetime(2026, 6, 3, 9, 0))]

    _upper_bound_narrow_on_swap_case(
        mocker, MailFolder.INBOX, date_from, date_to, in_bounds, out_of_bounds
    )


def test_sent_search_upper_bound_2026_11_05_day_lt_month_returns_window_items(mocker):
    """Upper-bound mirror for `folder="sent"`: `date_to`'s day (5) is less
    than its month (11)."""
    date_from = datetime(2026, 10, 20, 0, 0, tzinfo=timezone.utc)
    date_to = datetime(2026, 11, 5, 23, 59, 59, tzinfo=timezone.utc)

    in_bounds = [
        ("IN-10-25", datetime(2026, 10, 25, 9, 0)),
        ("IN-11-05", datetime(2026, 11, 5, 9, 0)),
    ]
    out_of_bounds = [("OUT-11-06", datetime(2026, 11, 6, 9, 0))]

    _upper_bound_narrow_on_swap_case(
        mocker, MailFolder.SENT, date_from, date_to, in_bounds, out_of_bounds
    )


def test_inbox_search_upper_bound_2026_12_03_day_lt_month_returns_window_items(mocker):
    """Upper-bound mirror for `folder="inbox"`: `date_to`'s day (3) is less
    than its month (12)."""
    date_from = datetime(2026, 11, 20, 0, 0, tzinfo=timezone.utc)
    date_to = datetime(2026, 12, 3, 23, 59, 59, tzinfo=timezone.utc)

    in_bounds = [
        ("IN-11-25", datetime(2026, 11, 25, 9, 0)),
        ("IN-12-03", datetime(2026, 12, 3, 9, 0)),
    ]
    out_of_bounds = [("OUT-12-04", datetime(2026, 12, 4, 9, 0))]

    _upper_bound_narrow_on_swap_case(
        mocker, MailFolder.INBOX, date_from, date_to, in_bounds, out_of_bounds
    )


def test_inbox_search_restrict_filter_exact_dasl_string_both_bounds_no_bracket_syntax(mocker):
    """Query-construction-layer assertion (inbox): the emitted `Restrict()`
    filter STRING must carry the exact DASL `@SQL=` URN syntax and the
    exact ISO literal for BOTH bounds — asserted with DIFFERENT day/month
    values on each bound so a day/month transposition on either side would
    be caught by an exact string comparison, not just a downstream Python
    re-check. Also asserts no Jet bracket-property date comparison
    (`[ReceivedTime] >=`) remains."""
    from tools.mail_adapter import OutlookMailAdapter

    dispatch_mock = _install_fake_win32com(mocker)
    outlook_app = mocker.Mock(name="OutlookApplication")
    dispatch_mock.return_value = outlook_app
    namespace = mocker.Mock(name="Namespace")
    outlook_app.GetNamespace.return_value = namespace
    folder = mocker.Mock(name="InboxFolder")
    namespace.GetDefaultFolder.return_value = folder
    items = mocker.Mock(name="Items")
    folder.Items = items
    restricted_items = mocker.Mock(name="RestrictedItems")
    items.Restrict.return_value = restricted_items
    restricted_items.__iter__ = mocker.Mock(return_value=iter([]))

    adapter = OutlookMailAdapter()
    date_from = datetime(2026, 6, 2, 8, 0, tzinfo=timezone.utc)  # day < month
    date_to = datetime(2026, 11, 5, 17, 30, tzinfo=timezone.utc)  # day < month, different month

    adapter.search(MailFolder.INBOX, date_from=date_from, date_to=date_to)

    items.Restrict.assert_called_once()
    restrict_arg = items.Restrict.call_args.args[0]
    assert restrict_arg == (
        '@SQL="urn:schemas:httpmail:datereceived" >= \'2026-06-02 08:00\' '
        'AND "urn:schemas:httpmail:datereceived" <= \'2026-11-05 17:30\''
    )
    assert not re.search(r"\[ReceivedTime\]", restrict_arg)


def test_sent_search_restrict_filter_exact_dasl_string_both_bounds_no_bracket_syntax(mocker):
    """Query-construction-layer assertion (sent): mirrors
    test_inbox_search_restrict_filter_exact_dasl_string_both_bounds_no_bracket_syntax
    for `folder="sent"` (`[SentOn]` / `urn:schemas:httpmail:datesent`)."""
    from tools.mail_adapter import OutlookMailAdapter

    dispatch_mock = _install_fake_win32com(mocker)
    outlook_app = mocker.Mock(name="OutlookApplication")
    dispatch_mock.return_value = outlook_app
    namespace = mocker.Mock(name="Namespace")
    outlook_app.GetNamespace.return_value = namespace
    folder = mocker.Mock(name="SentFolder")
    namespace.GetDefaultFolder.return_value = folder
    items = mocker.Mock(name="Items")
    folder.Items = items
    restricted_items = mocker.Mock(name="RestrictedItems")
    items.Restrict.return_value = restricted_items
    restricted_items.__iter__ = mocker.Mock(return_value=iter([]))

    adapter = OutlookMailAdapter()
    date_from = datetime(2026, 6, 2, 8, 0, tzinfo=timezone.utc)  # day < month
    date_to = datetime(2026, 11, 5, 17, 30, tzinfo=timezone.utc)  # day < month, different month

    adapter.search(MailFolder.SENT, date_from=date_from, date_to=date_to)

    items.Restrict.assert_called_once()
    restrict_arg = items.Restrict.call_args.args[0]
    assert restrict_arg == (
        '@SQL="urn:schemas:httpmail:datesent" >= \'2026-06-02 08:00\' '
        'AND "urn:schemas:httpmail:datesent" <= \'2026-11-05 17:30\''
    )
    assert not re.search(r"\[SentOn\]", restrict_arg)


def test_search_uses_configured_inbox_and_sent_folder_ids(mocker):
    """outlook-com-adapter spec's "Configurable Folder Ids" requirement:
    configured `inbox_folder_id`/`sent_folder_id` in settings.yaml are
    passed to GetDefaultFolder(), not the hardcoded defaults."""
    from tools.mail_adapter import OutlookMailAdapter

    mocker.patch(
        "tools.mail_adapter.load_settings",
        return_value={"inbox_folder_id": 61, "sent_folder_id": 51},
    )
    dispatch_mock = _install_fake_win32com(mocker)
    outlook_app = mocker.Mock(name="OutlookApplication")
    dispatch_mock.return_value = outlook_app
    namespace = mocker.Mock(name="Namespace")
    outlook_app.GetNamespace.return_value = namespace
    folder = mocker.Mock(name="Folder")
    namespace.GetDefaultFolder.return_value = folder
    items = mocker.Mock(name="Items")
    folder.Items = items
    restricted_items = mocker.Mock(name="RestrictedItems")
    items.Restrict.return_value = restricted_items
    restricted_items.__iter__ = mocker.Mock(return_value=iter([]))

    adapter = OutlookMailAdapter()
    date_from = datetime(2026, 8, 1, tzinfo=timezone.utc)
    date_to = datetime(2026, 8, 31, 23, 59, 59, tzinfo=timezone.utc)

    adapter.search(MailFolder.INBOX, date_from=date_from, date_to=date_to)
    namespace.GetDefaultFolder.assert_called_once_with(61)

    namespace.GetDefaultFolder.reset_mock()
    adapter.search(MailFolder.SENT, date_from=date_from, date_to=date_to)
    namespace.GetDefaultFolder.assert_called_once_with(51)


def test_search_absent_folder_ids_fall_back_to_defaults_6_and_5(mocker):
    """Absent `inbox_folder_id`/`sent_folder_id` keys -> the documented
    defaults (6 olFolderInbox / 5 olFolderSentMail)."""
    from tools.mail_adapter import OutlookMailAdapter

    mocker.patch("tools.mail_adapter.load_settings", return_value={})
    dispatch_mock = _install_fake_win32com(mocker)
    outlook_app = mocker.Mock(name="OutlookApplication")
    dispatch_mock.return_value = outlook_app
    namespace = mocker.Mock(name="Namespace")
    outlook_app.GetNamespace.return_value = namespace
    folder = mocker.Mock(name="Folder")
    namespace.GetDefaultFolder.return_value = folder
    items = mocker.Mock(name="Items")
    folder.Items = items
    restricted_items = mocker.Mock(name="RestrictedItems")
    items.Restrict.return_value = restricted_items
    restricted_items.__iter__ = mocker.Mock(return_value=iter([]))

    adapter = OutlookMailAdapter()
    date_from = datetime(2026, 8, 1, tzinfo=timezone.utc)
    date_to = datetime(2026, 8, 31, 23, 59, 59, tzinfo=timezone.utc)

    adapter.search(MailFolder.INBOX, date_from=date_from, date_to=date_to)
    namespace.GetDefaultFolder.assert_called_once_with(6)

    namespace.GetDefaultFolder.reset_mock()
    adapter.search(MailFolder.SENT, date_from=date_from, date_to=date_to)
    namespace.GetDefaultFolder.assert_called_once_with(5)


def test_settings_yaml_declares_inbox_and_sent_folder_ids():
    """Asserts the literal keys are present in the real, unmocked
    config/settings.yaml — mirrors tests/test_mail_tools.py's
    test_settings_yaml_declares_mail_lookback_days_90 precedent, for the
    new live mail folder-id keys (config-live-folders change)."""
    from tools.settings import load_settings

    settings = load_settings()

    assert "inbox_folder_id" in settings
    assert settings["inbox_folder_id"] == 6
    assert "sent_folder_id" in settings
    assert settings["sent_folder_id"] == 5


def test_settings_yaml_declares_drafts_folder_id():
    """mail-reading-depth Phase 6: `drafts_folder_id` must be declared in
    the real, unmocked config/settings.yaml, mirroring
    test_settings_yaml_declares_inbox_and_sent_folder_ids's precedent for
    the pre-existing `inbox_folder_id`/`sent_folder_id` keys."""
    from tools.settings import load_settings

    settings = load_settings()

    assert "drafts_folder_id" in settings
    assert settings["drafts_folder_id"] == 16


def test_mixed_class_items_collection_skips_non_mail_entries(mocker):
    from tools.mail_adapter import OutlookMailAdapter

    dispatch_mock = _install_fake_win32com(mocker)
    outlook_app = mocker.Mock()
    dispatch_mock.return_value = outlook_app
    namespace = mocker.Mock()
    outlook_app.GetNamespace.return_value = namespace
    folder = mocker.Mock(name="InboxFolder")
    namespace.GetDefaultFolder.return_value = folder
    items = mocker.Mock(name="Items")
    folder.Items = items
    restricted_items = mocker.Mock(name="RestrictedItems")
    items.Restrict.return_value = restricted_items

    def _mail_item(entry_id: str):
        return mocker.Mock(
            Class=43,
            EntryID=entry_id,
            Subject=f"Mail {entry_id}",
            SenderName="Ana Gomez",
            SenderEmailAddress="ana.gomez@example.com",
            ReceivedTime=datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc),
            Attachments=mocker.Mock(Count=0),
        )

    meeting_request = mocker.Mock(spec=["Class"], Class=53)

    mail_items = [_mail_item("M1"), _mail_item("M2"), _mail_item("M3")]
    restricted_items.__iter__ = mocker.Mock(
        return_value=iter([mail_items[0], mail_items[1], meeting_request, mail_items[2]])
    )

    adapter = OutlookMailAdapter()
    date_from = datetime(2026, 8, 1, 0, 0, tzinfo=timezone.utc)
    date_to = datetime(2026, 8, 31, 23, 59, 59, tzinfo=timezone.utc)

    results = adapter.search(MailFolder.INBOX, date_from=date_from, date_to=date_to)

    assert {r.entry_id for r in results} == {"M1", "M2", "M3"}


def test_sender_haystack_per_folder(mocker):
    from tools.mail_adapter import OutlookMailAdapter

    dispatch_mock = _install_fake_win32com(mocker)
    outlook_app = mocker.Mock()
    dispatch_mock.return_value = outlook_app
    namespace = mocker.Mock()
    outlook_app.GetNamespace.return_value = namespace

    # Inbox: sender filter matches SenderName / SenderEmailAddress.
    inbox_folder = mocker.Mock(name="InboxFolder")
    inbox_items = mocker.Mock(name="InboxItems")
    inbox_folder.Items = inbox_items
    inbox_restricted = mocker.Mock(name="InboxRestricted")
    inbox_items.Restrict.return_value = inbox_restricted
    matching_by_name = mocker.Mock(
        Class=43, EntryID="M1", Subject="Hola", SenderName="Ana Gomez",
        SenderEmailAddress="ana.gomez@example.com",
        ReceivedTime=datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc),
        Attachments=mocker.Mock(Count=0),
    )
    non_matching = mocker.Mock(
        Class=43, EntryID="M2", Subject="Otro", SenderName="Carlos Ruiz",
        SenderEmailAddress="carlos.ruiz@example.com",
        ReceivedTime=datetime(2026, 8, 9, 9, 0, tzinfo=timezone.utc),
        Attachments=mocker.Mock(Count=0),
    )
    inbox_restricted.__iter__ = mocker.Mock(
        return_value=iter([matching_by_name, non_matching])
    )
    namespace.GetDefaultFolder.return_value = inbox_folder

    adapter = OutlookMailAdapter()
    date_from = datetime(2026, 8, 1, tzinfo=timezone.utc)
    date_to = datetime(2026, 8, 31, 23, 59, 59, tzinfo=timezone.utc)

    inbox_results = adapter.search(
        MailFolder.INBOX, date_from=date_from, date_to=date_to, sender="ana"
    )
    assert {r.entry_id for r in inbox_results} == {"M1"}

    # Sent: sender filter matches To (recipients), not SenderName.
    sent_folder = mocker.Mock(name="SentFolder")
    sent_items = mocker.Mock(name="SentItems")
    sent_folder.Items = sent_items
    sent_restricted = mocker.Mock(name="SentRestricted")
    sent_items.Restrict.return_value = sent_restricted
    to_ana = mocker.Mock(
        Class=43, EntryID="M10", Subject="RE: Hola", SenderName="Yo",
        SenderEmailAddress="yo@example.com", To="ana.gomez@example.com",
        SentOn=datetime(2026, 8, 11, 9, 0, tzinfo=timezone.utc),
        Attachments=mocker.Mock(Count=0),
    )
    to_carlos = mocker.Mock(
        Class=43, EntryID="M11", Subject="Informe", SenderName="Yo",
        SenderEmailAddress="yo@example.com", To="carlos.ruiz@example.com",
        SentOn=datetime(2026, 8, 6, 9, 0, tzinfo=timezone.utc),
        Attachments=mocker.Mock(Count=0),
    )
    sent_restricted.__iter__ = mocker.Mock(return_value=iter([to_ana, to_carlos]))
    namespace.GetDefaultFolder.return_value = sent_folder

    sent_results = adapter.search(
        MailFolder.SENT, date_from=date_from, date_to=date_to, sender="ana.gomez"
    )
    assert {r.entry_id for r in sent_results} == {"M10"}


def test_naive_com_datetime_converted_to_aware_local_time(mocker):
    from tools.mail_adapter import OutlookMailAdapter

    dispatch_mock = _install_fake_win32com(mocker)
    outlook_app = mocker.Mock()
    dispatch_mock.return_value = outlook_app
    namespace = mocker.Mock()
    outlook_app.GetNamespace.return_value = namespace
    folder = mocker.Mock(name="InboxFolder")
    namespace.GetDefaultFolder.return_value = folder
    items = mocker.Mock(name="Items")
    folder.Items = items
    restricted_items = mocker.Mock(name="RestrictedItems")
    items.Restrict.return_value = restricted_items

    naive_received = datetime(2026, 8, 10, 9, 0)  # naive — simulates Outlook COM local time
    fake_item = mocker.Mock(
        Class=43, EntryID="M1", Subject="Factura", SenderName="Ana",
        SenderEmailAddress="ana@example.com", ReceivedTime=naive_received,
        Attachments=mocker.Mock(Count=0),
    )
    restricted_items.__iter__ = mocker.Mock(return_value=iter([fake_item]))

    adapter = OutlookMailAdapter()
    date_from = datetime(2026, 8, 1, tzinfo=timezone.utc)
    date_to = datetime(2026, 8, 31, 23, 59, 59, tzinfo=timezone.utc)

    results = adapter.search(MailFolder.INBOX, date_from=date_from, date_to=date_to)

    assert results[0].date.tzinfo is not None
    assert results[0].date.replace(tzinfo=None) == naive_received

    # get_message(): same normalization applies.
    naive_received_detail = datetime(2026, 8, 10, 10, 0)
    detail_item = mocker.Mock(
        Class=43, EntryID="M2", Subject="Factura", SenderName="Ana",
        SenderEmailAddress="ana@example.com", ReceivedTime=naive_received_detail,
        SentOn=None, To="", Body="hola",
        Attachments=mocker.Mock(Count=0),
    )
    namespace.GetItemFromID.return_value = detail_item

    detail = adapter.get_message("M2")

    assert detail.date.tzinfo is not None
    assert detail.date.replace(tzinfo=None) == naive_received_detail


def test_search_aware_com_received_time_vs_naive_request_bound_does_not_raise(mocker):
    """datetime-tz hotfix (2026-08-26): real Outlook QA regression, mail
    side. Real pywintypes.datetime `ReceivedTime` values come back
    timezone-AWARE (a fixed offset) on real Windows, unlike every other
    fake in this file which uses naive `datetime(...)` to simulate
    Outlook COM's local time. Meanwhile `MailSearchRequest.date_from`/
    `date_to` (models/schemas.py) have no tz-aware validator, so a naive
    bound can legitimately reach the adapter. Before the fix,
    `_matches_date_bounds`'s `aware < date_from` raised "can't compare
    offset-naive and offset-aware datetimes"."""
    from tools.mail_adapter import OutlookMailAdapter

    dispatch_mock = _install_fake_win32com(mocker)
    outlook_app = mocker.Mock(name="OutlookApplication")
    dispatch_mock.return_value = outlook_app
    namespace = mocker.Mock(name="Namespace")
    outlook_app.GetNamespace.return_value = namespace
    folder = mocker.Mock(name="InboxFolder")
    namespace.GetDefaultFolder.return_value = folder
    items = mocker.Mock(name="Items")
    folder.Items = items
    restricted_items = mocker.Mock(name="RestrictedItems")
    items.Restrict.return_value = restricted_items

    aware_offset = timezone(timedelta(hours=2))  # e.g. CEST, like real Outlook
    fake_item = mocker.Mock(
        Class=43, EntryID="M1", Subject="Factura agosto", SenderName="Ana Gomez",
        SenderEmailAddress="ana.gomez@example.com",
        ReceivedTime=datetime(2026, 8, 10, 9, 0, tzinfo=aware_offset),
        Attachments=mocker.Mock(Count=0),
    )
    restricted_items.__iter__ = mocker.Mock(return_value=iter([fake_item]))

    adapter = OutlookMailAdapter()
    # Naive request bounds — legal per MailSearchRequest's schema.
    date_from = datetime(2026, 8, 1, 0, 0)
    date_to = datetime(2026, 8, 31, 23, 59, 59)

    results = adapter.search(MailFolder.INBOX, date_from=date_from, date_to=date_to)

    assert [r.entry_id for r in results] == ["M1"]


def test_folder_path_search_aware_item_vs_naive_bound_sort_does_not_raise(mocker):
    """datetime-tz hotfix (2026-08-26): the `folder_path` search path runs
    the same `_matches_date_bounds` boundary check (no Restrict()) and then
    Python-sorts the surviving matches by resolved date (search-result-caps
    change). Must not raise when the source COM datetimes are aware and
    the request bounds are naive."""
    from tools.mail_adapter import OutlookMailAdapter

    dispatch_mock = _install_fake_win32com(mocker)
    outlook_app = mocker.Mock(name="OutlookApplication")
    dispatch_mock.return_value = outlook_app
    namespace = mocker.Mock(name="Namespace")
    outlook_app.GetNamespace.return_value = namespace

    default_store = mocker.Mock(name="DefaultStore")
    namespace.DefaultStore = default_store
    root_folder = mocker.Mock(name="RootFolder")
    default_store.GetRootFolder.return_value = root_folder
    proyectos_folder = mocker.Mock(name="ProyectosFolder")
    root_folder.Folders.Item.return_value = proyectos_folder
    target_folder = mocker.Mock(name="TargetFolder")
    proyectos_folder.Folders.Item.return_value = target_folder
    items = mocker.Mock(name="Items")
    target_folder.Items = items

    aware_offset = timezone(timedelta(hours=2))
    item_1 = mocker.Mock(
        Class=43, EntryID="P1", Subject="Uno", SenderName="Ana",
        SenderEmailAddress="ana@example.com",
        ReceivedTime=datetime(2026, 8, 10, 9, 0, tzinfo=aware_offset), SentOn=None,
        Attachments=mocker.Mock(Count=0),
    )
    item_2 = mocker.Mock(
        Class=43, EntryID="P2", Subject="Dos", SenderName="Ana",
        SenderEmailAddress="ana@example.com",
        ReceivedTime=datetime(2026, 8, 20, 9, 0, tzinfo=aware_offset), SentOn=None,
        Attachments=mocker.Mock(Count=0),
    )
    items.__iter__ = mocker.Mock(return_value=iter([item_1, item_2]))

    adapter = OutlookMailAdapter()
    # Naive request bounds.
    date_from = datetime(2026, 8, 1, 0, 0)
    date_to = datetime(2026, 8, 31, 23, 59, 59)

    results = adapter.search(folder_path="Proyectos/2026", date_from=date_from, date_to=date_to)

    assert [r.entry_id for r in results] == ["P2", "P1"]  # newest-first


def test_has_attachments_true_when_attachments_count_gt_0(mocker):
    from tools.mail_adapter import OutlookMailAdapter

    dispatch_mock = _install_fake_win32com(mocker)
    outlook_app = mocker.Mock()
    dispatch_mock.return_value = outlook_app
    namespace = mocker.Mock()
    outlook_app.GetNamespace.return_value = namespace
    folder = mocker.Mock(name="InboxFolder")
    namespace.GetDefaultFolder.return_value = folder
    items = mocker.Mock(name="Items")
    folder.Items = items
    restricted_items = mocker.Mock(name="RestrictedItems")
    items.Restrict.return_value = restricted_items

    with_attachment = mocker.Mock(
        Class=43, EntryID="M1", Subject="Con adjunto", SenderName="Ana",
        SenderEmailAddress="ana@example.com",
        ReceivedTime=datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc),
        Attachments=mocker.Mock(Count=2),
    )
    without_attachment = mocker.Mock(
        Class=43, EntryID="M2", Subject="Sin adjunto", SenderName="Carlos",
        SenderEmailAddress="carlos@example.com",
        ReceivedTime=datetime(2026, 8, 9, 9, 0, tzinfo=timezone.utc),
        Attachments=mocker.Mock(Count=0),
    )
    restricted_items.__iter__ = mocker.Mock(
        return_value=iter([with_attachment, without_attachment])
    )

    adapter = OutlookMailAdapter()
    date_from = datetime(2026, 8, 1, tzinfo=timezone.utc)
    date_to = datetime(2026, 8, 31, 23, 59, 59, tzinfo=timezone.utc)

    results = adapter.search(MailFolder.INBOX, date_from=date_from, date_to=date_to)

    by_id = {r.entry_id: r for r in results}
    assert by_id["M1"].has_attachments is True
    assert by_id["M2"].has_attachments is False


def test_get_message_uses_get_item_from_id_and_class_guard_raises_not_found(mocker):
    from tools.mail_adapter import OutlookMailAdapter

    dispatch_mock = _install_fake_win32com(mocker)
    outlook_app = mocker.Mock()
    dispatch_mock.return_value = outlook_app
    namespace = mocker.Mock()
    outlook_app.GetNamespace.return_value = namespace

    mail_item = mocker.Mock(
        Class=43, EntryID="MSG-1", Subject="Factura agosto", SenderName="Ana Gomez",
        SenderEmailAddress="ana.gomez@example.com",
        ReceivedTime=datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc),
        SentOn=None, To="yo@example.com", Body="Adjunto la factura.",
        Attachments=mocker.Mock(
            Count=1, Item=mocker.Mock(return_value=types.SimpleNamespace(FileName="adjunto.pdf"))
        ),
    )
    namespace.GetItemFromID.return_value = mail_item

    adapter = OutlookMailAdapter()
    result = adapter.get_message("MSG-1")

    namespace.GetItemFromID.assert_called_once_with("MSG-1")
    assert result.entry_id == "MSG-1"
    assert result.body == "Adjunto la factura."
    assert result.to == ["yo@example.com"]
    assert result.has_attachments is True

    # Non-mail item (e.g. a meeting request retrieved by entryId) must be
    # treated as not-found, not returned as a message.
    non_mail_item = mocker.Mock(spec=["Class"], Class=53)
    namespace.GetItemFromID.return_value = non_mail_item

    with pytest.raises(MessageNotFoundError):
        adapter.get_message("MEETING-1")


def test_get_message_falls_back_to_sent_on_when_received_time_is_falsy(mocker):
    """`get_message()` has no `folder` argument, so `_resolve_date()` must
    pick the date from whichever of `ReceivedTime`/`SentOn` is populated.
    Every other `get_message()` fixture in this file sets a truthy
    `ReceivedTime`, so this test exercises the fallback branch: a genuine
    Sent Items message, where `ReceivedTime` is falsy (`None`) and `SentOn`
    is populated — the returned date must come from `SentOn`."""
    from tools.mail_adapter import OutlookMailAdapter

    dispatch_mock = _install_fake_win32com(mocker)
    outlook_app = mocker.Mock()
    dispatch_mock.return_value = outlook_app
    namespace = mocker.Mock()
    outlook_app.GetNamespace.return_value = namespace

    sent_on = datetime(2026, 8, 11, 9, 0, tzinfo=timezone.utc)
    sent_item = mocker.Mock(
        Class=43, EntryID="M10", Subject="RE: Factura agosto", SenderName="Yo",
        SenderEmailAddress="yo@example.com", ReceivedTime=None, SentOn=sent_on,
        To="ana.gomez@example.com", Body="Enviado.",
        Attachments=mocker.Mock(Count=0),
    )
    namespace.GetItemFromID.return_value = sent_item

    adapter = OutlookMailAdapter()
    result = adapter.get_message("M10")

    assert result.date == sent_on


def test_dispatch_failure_raises_outlook_unavailable_error(mocker):
    from tools.mail_adapter import OutlookMailAdapter

    dispatch_mock = _install_fake_win32com(mocker)
    dispatch_mock.side_effect = Exception("Outlook is not running")

    adapter = OutlookMailAdapter()

    with pytest.raises(OutlookUnavailableError):
        adapter.search(MailFolder.INBOX, date_from=datetime(2026, 8, 1, tzinfo=timezone.utc),
                        date_to=datetime(2026, 8, 31, tzinfo=timezone.utc))

    with pytest.raises(OutlookUnavailableError):
        adapter.get_message("MSG-1")


def test_pythoncom_import_error_raises_outlook_unavailable_error(mocker):
    """Isolates the "pythoncom import fails" half of `_dispatch_outlook`'s
    shared `try: import pythoncom; import win32com.client / except
    ImportError` block — as opposed to a win32com-only or combined failure.
    Mirrors `tests/test_outlook_adapter.py`'s dedicated pythoncom-isolation
    test. A real fake `win32com.client` is installed directly (bypassing
    `_install_fake_win32com`'s own pythoncom auto-install) to prove it would
    have succeeded had `import pythoncom` not failed first."""
    from tools.mail_adapter import OutlookMailAdapter

    mocker.patch.dict(sys.modules)
    sys.modules.pop("pythoncom", None)
    mocker.patch.dict(sys.modules, {"pythoncom": None})
    fake_win32com = types.ModuleType("win32com")
    fake_win32com_client = types.ModuleType("win32com.client")
    fake_win32com_client.Dispatch = mocker.Mock(name="Dispatch")
    fake_win32com.client = fake_win32com_client
    sys.modules["win32com"] = fake_win32com
    sys.modules["win32com.client"] = fake_win32com_client

    adapter = OutlookMailAdapter()

    with pytest.raises(OutlookUnavailableError):
        adapter.get_message("MSG-1")


def test_no_mutating_com_calls_issued_on_get_message(mocker):
    from tools.mail_adapter import OutlookMailAdapter

    dispatch_mock = _install_fake_win32com(mocker)
    outlook_app = mocker.Mock()
    dispatch_mock.return_value = outlook_app
    namespace = mocker.Mock()
    outlook_app.GetNamespace.return_value = namespace
    namespace.GetItemFromID.return_value = _AssertingMailItem()

    adapter = OutlookMailAdapter()

    result = adapter.get_message("MSG-1")

    assert result.entry_id == "MSG-1"
    assert result.body == "Adjunto la factura."


# --- Phase 4 (mail-reading-depth): real OutlookMailAdapter extensions ---


def test_drafts_search_uses_get_default_folder_16_and_restricts_on_last_modification_time(mocker):
    """outlook-mail-adapter spec's "Drafts resolves via
    GetDefaultFolder(drafts_folder_id) and restricts on
    LastModificationTime" scenario."""
    from tools.mail_adapter import OutlookMailAdapter

    dispatch_mock = _install_fake_win32com(mocker)
    outlook_app = mocker.Mock(name="OutlookApplication")
    dispatch_mock.return_value = outlook_app
    namespace = mocker.Mock(name="Namespace")
    outlook_app.GetNamespace.return_value = namespace
    folder = mocker.Mock(name="DraftsFolder")
    namespace.GetDefaultFolder.return_value = folder
    items = mocker.Mock(name="Items")
    folder.Items = items
    restricted_items = mocker.Mock(name="RestrictedItems")
    items.Restrict.return_value = restricted_items
    restricted_items.__iter__ = mocker.Mock(return_value=iter([]))

    adapter = OutlookMailAdapter()
    date_from = datetime(2026, 8, 1, tzinfo=timezone.utc)
    date_to = datetime(2026, 8, 31, 23, 59, 59, tzinfo=timezone.utc)

    adapter.search(MailFolder.DRAFTS, date_from=date_from, date_to=date_to)

    namespace.GetDefaultFolder.assert_called_once_with(16)
    items.Restrict.assert_called_once()
    restrict_arg = items.Restrict.call_args.args[0]
    assert restrict_arg.startswith(
        '@SQL="http://schemas.microsoft.com/mapi/proptag/0x30080040" >='
    )
    assert (
        '"http://schemas.microsoft.com/mapi/proptag/0x30080040" <='
        in restrict_arg
    )


def test_resolve_date_falls_back_to_last_modification_time_when_received_and_sent_on_absent(
    mocker,
):
    """outlook-mail-adapter spec's "Date Resolution Fallback Chain"
    requirement / "Draft with no ReceivedTime/SentOn falls back to
    LastModificationTime" scenario, for both search() and get_message()."""
    from tools.mail_adapter import OutlookMailAdapter

    dispatch_mock = _install_fake_win32com(mocker)
    outlook_app = mocker.Mock(name="OutlookApplication")
    dispatch_mock.return_value = outlook_app
    namespace = mocker.Mock(name="Namespace")
    outlook_app.GetNamespace.return_value = namespace

    # search(): a Drafts item lacking ReceivedTime/SentOn, only LastModificationTime.
    folder = mocker.Mock(name="DraftsFolder")
    namespace.GetDefaultFolder.return_value = folder
    items = mocker.Mock(name="Items")
    folder.Items = items
    restricted_items = mocker.Mock(name="RestrictedItems")
    items.Restrict.return_value = restricted_items
    last_modified = datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc)
    draft_item = mocker.Mock(
        Class=43, EntryID="D1", Subject="Borrador", SenderName="Yo",
        SenderEmailAddress="yo@example.com", ReceivedTime=None, SentOn=None,
        LastModificationTime=last_modified, Attachments=mocker.Mock(Count=0),
    )
    restricted_items.__iter__ = mocker.Mock(return_value=iter([draft_item]))

    adapter = OutlookMailAdapter()
    date_from = datetime(2026, 8, 1, tzinfo=timezone.utc)
    date_to = datetime(2026, 8, 31, 23, 59, 59, tzinfo=timezone.utc)

    results = adapter.search(MailFolder.DRAFTS, date_from=date_from, date_to=date_to)

    assert len(results) == 1
    assert results[0].date == last_modified

    # get_message(): same fallback chain applies.
    detail_item = mocker.Mock(
        Class=43, EntryID="D2", Subject="Borrador 2", SenderName="Yo",
        SenderEmailAddress="yo@example.com", ReceivedTime=None, SentOn=None,
        LastModificationTime=last_modified, To="", Body="Texto",
        Attachments=mocker.Mock(Count=0),
    )
    namespace.GetItemFromID.return_value = detail_item

    detail = adapter.get_message("D2")

    assert detail.date == last_modified


def test_folder_path_traverses_default_store_root_via_per_segment_folders_item(mocker):
    """outlook-mail-adapter spec's "folder_path traverses named subfolders
    within the default store" scenario."""
    from tools.mail_adapter import OutlookMailAdapter

    dispatch_mock = _install_fake_win32com(mocker)
    outlook_app = mocker.Mock(name="OutlookApplication")
    dispatch_mock.return_value = outlook_app
    namespace = mocker.Mock(name="Namespace")
    outlook_app.GetNamespace.return_value = namespace

    default_store = mocker.Mock(name="DefaultStore")
    namespace.DefaultStore = default_store
    root_folder = mocker.Mock(name="RootFolder")
    default_store.GetRootFolder.return_value = root_folder
    proyectos_folder = mocker.Mock(name="ProyectosFolder")
    year_folder = mocker.Mock(name="YearFolder")
    root_folder.Folders.Item.return_value = proyectos_folder
    proyectos_folder.Folders.Item.return_value = year_folder
    year_items = mocker.Mock(name="YearItems")
    year_folder.Items = year_items
    year_items.__iter__ = mocker.Mock(return_value=iter([]))

    adapter = OutlookMailAdapter()
    adapter.search(folder_path="Proyectos/2026")

    default_store.GetRootFolder.assert_called_once()
    root_folder.Folders.Item.assert_called_once_with("Proyectos")
    proyectos_folder.Folders.Item.assert_called_once_with("2026")
    namespace.GetDefaultFolder.assert_not_called()


def test_folder_path_unresolved_segment_raises_mail_folder_not_found_error(mocker):
    """outlook-mail-adapter spec's "Missing folder_path segment raises
    MailFolderNotFoundError" scenario."""
    from tools.mail_adapter import OutlookMailAdapter

    dispatch_mock = _install_fake_win32com(mocker)
    outlook_app = mocker.Mock(name="OutlookApplication")
    dispatch_mock.return_value = outlook_app
    namespace = mocker.Mock(name="Namespace")
    outlook_app.GetNamespace.return_value = namespace

    default_store = mocker.Mock(name="DefaultStore")
    namespace.DefaultStore = default_store
    root_folder = mocker.Mock(name="RootFolder")
    default_store.GetRootFolder.return_value = root_folder
    proyectos_folder = mocker.Mock(name="ProyectosFolder")
    root_folder.Folders.Item.return_value = proyectos_folder
    proyectos_folder.Folders.Item.side_effect = Exception("not found")

    adapter = OutlookMailAdapter()

    with pytest.raises(MailFolderNotFoundError) as exc_info:
        adapter.search(folder_path="Proyectos/NoExiste")

    assert exc_info.value.code == "mail_folder_not_found"
    assert exc_info.value.path == "Proyectos/NoExiste"
    assert exc_info.value.failing_segment == "NoExiste"


def test_folder_path_search_skips_restrict_and_filters_dates_in_python_via_fallback_chain(
    mocker,
):
    """outlook-mail-adapter spec's "folder_path search skips Restrict() and
    filters dates via the fallback chain" scenario. `Items.Restrict` is left
    unconfigured (not stubbed as callable-and-fail) so a call would simply
    return a Mock — `assert_not_called()` below is the actual proof."""
    from tools.mail_adapter import OutlookMailAdapter

    dispatch_mock = _install_fake_win32com(mocker)
    outlook_app = mocker.Mock(name="OutlookApplication")
    dispatch_mock.return_value = outlook_app
    namespace = mocker.Mock(name="Namespace")
    outlook_app.GetNamespace.return_value = namespace

    default_store = mocker.Mock(name="DefaultStore")
    namespace.DefaultStore = default_store
    root_folder = mocker.Mock(name="RootFolder")
    default_store.GetRootFolder.return_value = root_folder
    proyectos_folder = mocker.Mock(name="ProyectosFolder")
    root_folder.Folders.Item.return_value = proyectos_folder
    target_folder = mocker.Mock(name="TargetFolder")
    proyectos_folder.Folders.Item.return_value = target_folder
    items = mocker.Mock(name="Items")
    target_folder.Items = items

    date_from = datetime(2026, 8, 1, tzinfo=timezone.utc)
    date_to = datetime(2026, 8, 31, 23, 59, 59, tzinfo=timezone.utc)

    in_range_received_1 = mocker.Mock(
        Class=43, EntryID="P1", Subject="Uno", SenderName="Ana",
        SenderEmailAddress="ana@example.com",
        ReceivedTime=datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc), SentOn=None,
        Attachments=mocker.Mock(Count=0),
    )
    in_range_received_2 = mocker.Mock(
        Class=43, EntryID="P2", Subject="Dos", SenderName="Ana",
        SenderEmailAddress="ana@example.com",
        ReceivedTime=datetime(2026, 8, 20, 9, 0, tzinfo=timezone.utc), SentOn=None,
        Attachments=mocker.Mock(Count=0),
    )
    in_range_via_last_modified = mocker.Mock(
        Class=43, EntryID="P3", Subject="Tres", SenderName="Ana",
        SenderEmailAddress="ana@example.com",
        ReceivedTime=None, SentOn=None,
        LastModificationTime=datetime(2026, 8, 25, 9, 0, tzinfo=timezone.utc),
        Attachments=mocker.Mock(Count=0),
    )
    out_of_range = mocker.Mock(
        Class=43, EntryID="P4", Subject="Fuera", SenderName="Ana",
        SenderEmailAddress="ana@example.com",
        ReceivedTime=datetime(2026, 9, 5, 9, 0, tzinfo=timezone.utc), SentOn=None,
        Attachments=mocker.Mock(Count=0),
    )
    items.__iter__ = mocker.Mock(
        return_value=iter(
            [in_range_received_1, in_range_received_2, in_range_via_last_modified, out_of_range]
        )
    )

    adapter = OutlookMailAdapter()
    results = adapter.search(folder_path="Proyectos/2026", date_from=date_from, date_to=date_to)

    items.Restrict.assert_not_called()
    assert {r.entry_id for r in results} == {"P1", "P2", "P3"}


def test_attachment_names_enumerated_1_indexed(mocker):
    """outlook-mail-adapter spec's "Enumerates filenames in 1-indexed
    order" scenario."""
    from tools.mail_adapter import OutlookMailAdapter

    dispatch_mock = _install_fake_win32com(mocker)
    outlook_app = mocker.Mock(name="OutlookApplication")
    dispatch_mock.return_value = outlook_app
    namespace = mocker.Mock(name="Namespace")
    outlook_app.GetNamespace.return_value = namespace

    attachments = mocker.Mock(name="Attachments")
    attachments.Count = 2
    attachment_1 = types.SimpleNamespace(FileName="factura.pdf")
    attachment_2 = types.SimpleNamespace(FileName="anexo.docx")
    attachments.Item = mocker.Mock(side_effect=lambda i: {1: attachment_1, 2: attachment_2}[i])

    mail_item = mocker.Mock(
        Class=43, EntryID="MSG-3", Subject="Con adjuntos", SenderName="Ana",
        SenderEmailAddress="ana@example.com",
        ReceivedTime=datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc), SentOn=None,
        To="", Body="Cuerpo", Attachments=attachments,
    )
    namespace.GetItemFromID.return_value = mail_item

    adapter = OutlookMailAdapter()
    result = adapter.get_message("MSG-3")

    assert result.attachment_names == ["factura.pdf", "anexo.docx"]


def test_attachment_names_empty_when_count_zero(mocker):
    """outlook-mail-adapter spec's "No attachments yields an empty list"
    scenario."""
    from tools.mail_adapter import OutlookMailAdapter

    dispatch_mock = _install_fake_win32com(mocker)
    outlook_app = mocker.Mock(name="OutlookApplication")
    dispatch_mock.return_value = outlook_app
    namespace = mocker.Mock(name="Namespace")
    outlook_app.GetNamespace.return_value = namespace

    mail_item = mocker.Mock(
        Class=43, EntryID="MSG-4", Subject="Sin adjuntos", SenderName="Ana",
        SenderEmailAddress="ana@example.com",
        ReceivedTime=datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc), SentOn=None,
        To="", Body="Cuerpo", Attachments=mocker.Mock(Count=0),
    )
    namespace.GetItemFromID.return_value = mail_item

    adapter = OutlookMailAdapter()
    result = adapter.get_message("MSG-4")

    assert result.attachment_names == []
    assert result.has_attachments is False


def test_html_body_not_accessed_unless_include_html_true(mocker):
    """outlook-mail-adapter spec's "HTMLBody is not accessed by default"
    scenario."""
    from tools.mail_adapter import OutlookMailAdapter

    dispatch_mock = _install_fake_win32com(mocker)
    outlook_app = mocker.Mock(name="OutlookApplication")
    dispatch_mock.return_value = outlook_app
    namespace = mocker.Mock(name="Namespace")
    outlook_app.GetNamespace.return_value = namespace
    namespace.GetItemFromID.return_value = _HTMLBodyGuardMailItem()

    adapter = OutlookMailAdapter()
    result = adapter.get_message("MSG-5")

    assert result.html_body is None
    assert result.body == "Texto plano"


def test_html_body_read_when_include_html_true_body_unaffected(mocker):
    """outlook-mail-adapter spec's "HTMLBody is read when requested"
    scenario."""
    from tools.mail_adapter import OutlookMailAdapter

    dispatch_mock = _install_fake_win32com(mocker)
    outlook_app = mocker.Mock(name="OutlookApplication")
    dispatch_mock.return_value = outlook_app
    namespace = mocker.Mock(name="Namespace")
    outlook_app.GetNamespace.return_value = namespace

    mail_item = mocker.Mock(
        Class=43, EntryID="MSG-6", Subject="Con html", SenderName="Ana",
        SenderEmailAddress="ana@example.com",
        ReceivedTime=datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc), SentOn=None,
        To="", Body="Texto plano", HTMLBody="<p>Texto plano</p>",
        Attachments=mocker.Mock(Count=0),
    )
    namespace.GetItemFromID.return_value = mail_item

    adapter = OutlookMailAdapter()
    result = adapter.get_message("MSG-6", include_html=True)

    assert result.html_body == "<p>Texto plano</p>"
    assert result.body == "Texto plano"


def test_no_mutating_com_calls_across_search_traversal_and_get_message(mocker):
    """outlook-mail-adapter spec's "Read-Only Contract" requirement,
    extended to folder_path traversal + search, on top of the existing
    get_message()-only coverage (test_no_mutating_com_calls_issued_on_get_message)."""
    from tools.mail_adapter import OutlookMailAdapter

    dispatch_mock = _install_fake_win32com(mocker)
    outlook_app = mocker.Mock(name="OutlookApplication")
    dispatch_mock.return_value = outlook_app
    namespace = mocker.Mock(name="Namespace")
    outlook_app.GetNamespace.return_value = namespace

    default_store = mocker.Mock(name="DefaultStore")
    namespace.DefaultStore = default_store
    root_folder = mocker.Mock(name="RootFolder")
    default_store.GetRootFolder.return_value = root_folder
    target_folder = mocker.Mock(name="TargetFolder")
    root_folder.Folders.Item.return_value = target_folder
    items = mocker.Mock(name="Items")
    target_folder.Items = items
    items.__iter__ = mocker.Mock(return_value=iter([_AssertingMailItem()]))

    adapter = OutlookMailAdapter()
    results = adapter.search(folder_path="Proyectos")

    assert len(results) == 1

    namespace.GetItemFromID.return_value = _AssertingMailItem()
    detail = adapter.get_message("MSG-1", include_html=True)

    assert detail.attachment_names == ["factura.pdf"]
    assert detail.html_body == "<p>Adjunto la factura.</p>"


def test_inbox_sent_backward_compatible_no_regression(mocker):
    """Extends test_inbox_search_restricts_on_received_time /
    test_sent_search_restricts_on_sent_on: proves the mapped-folder
    per-item date extraction still reads ReceivedTime/SentOn directly
    rather than going through the drafts/folder_path fallback chain — if it
    mistakenly used the fallback chain, the un-stubbed SentOn attribute on
    the inbox mock (or ReceivedTime on the sent mock) would resolve to an
    auto-generated Mock instead of a real value, and the wrong field could
    silently win without a bare-attribute-access crash to reveal it."""
    from tools.mail_adapter import OutlookMailAdapter

    dispatch_mock = _install_fake_win32com(mocker)
    outlook_app = mocker.Mock(name="OutlookApplication")
    dispatch_mock.return_value = outlook_app
    namespace = mocker.Mock(name="Namespace")
    outlook_app.GetNamespace.return_value = namespace

    # Inbox: item has ReceivedTime populated; SentOn deliberately unset
    # (would auto-Mock if ever read).
    inbox_folder = mocker.Mock(name="InboxFolder")
    inbox_items = mocker.Mock(name="InboxItems")
    inbox_folder.Items = inbox_items
    inbox_restricted = mocker.Mock(name="InboxRestricted")
    inbox_items.Restrict.return_value = inbox_restricted
    received_time = datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc)
    inbox_item = mocker.Mock(
        Class=43, EntryID="I1", Subject="Hola", SenderName="Ana",
        SenderEmailAddress="ana@example.com", ReceivedTime=received_time,
        Attachments=mocker.Mock(Count=0),
    )
    inbox_restricted.__iter__ = mocker.Mock(return_value=iter([inbox_item]))
    namespace.GetDefaultFolder.return_value = inbox_folder

    adapter = OutlookMailAdapter()
    date_from = datetime(2026, 8, 1, tzinfo=timezone.utc)
    date_to = datetime(2026, 8, 31, 23, 59, 59, tzinfo=timezone.utc)

    inbox_results = adapter.search(MailFolder.INBOX, date_from=date_from, date_to=date_to)
    assert inbox_results[0].date == received_time

    # Sent: item has SentOn populated; ReceivedTime deliberately unset
    # (would auto-Mock if ever read).
    sent_folder = mocker.Mock(name="SentFolder")
    sent_items = mocker.Mock(name="SentItems")
    sent_folder.Items = sent_items
    sent_restricted = mocker.Mock(name="SentRestricted")
    sent_items.Restrict.return_value = sent_restricted
    sent_on = datetime(2026, 8, 11, 9, 0, tzinfo=timezone.utc)
    sent_item = mocker.Mock(
        Class=43, EntryID="S1", Subject="RE: Hola", SenderName="Yo",
        SenderEmailAddress="yo@example.com", To="ana@example.com", SentOn=sent_on,
        Attachments=mocker.Mock(Count=0),
    )
    sent_restricted.__iter__ = mocker.Mock(return_value=iter([sent_item]))
    namespace.GetDefaultFolder.return_value = sent_folder

    sent_results = adapter.search(MailFolder.SENT, date_from=date_from, date_to=date_to)
    assert sent_results[0].date == sent_on


# --- search-result-caps (BUG-002): limit, descending Sort(), early-stop,
# results_truncated "+1 peek" convention. ---


def test_inbox_search_sorts_descending_before_restrict(mocker):
    """outlook-mail-adapter's ordering decision: mapped-folder search()
    must Sort() the Items collection descending on the folder's DASL date
    field, before Restrict() is applied (mirrors
    tests/test_outlook_adapter.py's calendar precedent, now descending)."""
    from tools.mail_adapter import OutlookMailAdapter

    dispatch_mock = _install_fake_win32com(mocker)
    outlook_app = mocker.Mock(name="OutlookApplication")
    dispatch_mock.return_value = outlook_app
    namespace = mocker.Mock(name="Namespace")
    outlook_app.GetNamespace.return_value = namespace
    folder = mocker.Mock(name="InboxFolder")
    namespace.GetDefaultFolder.return_value = folder
    items = mocker.Mock(name="Items")
    folder.Items = items
    restricted_items = mocker.Mock(name="RestrictedItems")
    items.Restrict.return_value = restricted_items
    restricted_items.__iter__ = mocker.Mock(return_value=iter([]))

    adapter = OutlookMailAdapter()
    date_from = datetime(2026, 8, 1, tzinfo=timezone.utc)
    date_to = datetime(2026, 8, 31, 23, 59, 59, tzinfo=timezone.utc)

    adapter.search(MailFolder.INBOX, date_from=date_from, date_to=date_to)

    items.Sort.assert_called_once_with("[ReceivedTime]", True)
    call_names = [call[0] for call in items.mock_calls]
    assert call_names.index("Sort") < call_names.index("Restrict")


def test_sent_search_sorts_on_sent_on_descending(mocker):
    from tools.mail_adapter import OutlookMailAdapter

    dispatch_mock = _install_fake_win32com(mocker)
    outlook_app = mocker.Mock(name="OutlookApplication")
    dispatch_mock.return_value = outlook_app
    namespace = mocker.Mock(name="Namespace")
    outlook_app.GetNamespace.return_value = namespace
    folder = mocker.Mock(name="SentFolder")
    namespace.GetDefaultFolder.return_value = folder
    items = mocker.Mock(name="Items")
    folder.Items = items
    restricted_items = mocker.Mock(name="RestrictedItems")
    items.Restrict.return_value = restricted_items
    restricted_items.__iter__ = mocker.Mock(return_value=iter([]))

    adapter = OutlookMailAdapter()
    date_from = datetime(2026, 8, 1, tzinfo=timezone.utc)
    date_to = datetime(2026, 8, 31, 23, 59, 59, tzinfo=timezone.utc)

    adapter.search(MailFolder.SENT, date_from=date_from, date_to=date_to)

    items.Sort.assert_called_once_with("[SentOn]", True)


def test_drafts_search_sorts_on_last_modification_time_descending(mocker):
    from tools.mail_adapter import OutlookMailAdapter

    dispatch_mock = _install_fake_win32com(mocker)
    outlook_app = mocker.Mock(name="OutlookApplication")
    dispatch_mock.return_value = outlook_app
    namespace = mocker.Mock(name="Namespace")
    outlook_app.GetNamespace.return_value = namespace
    folder = mocker.Mock(name="DraftsFolder")
    namespace.GetDefaultFolder.return_value = folder
    items = mocker.Mock(name="Items")
    folder.Items = items
    restricted_items = mocker.Mock(name="RestrictedItems")
    items.Restrict.return_value = restricted_items
    restricted_items.__iter__ = mocker.Mock(return_value=iter([]))

    adapter = OutlookMailAdapter()
    date_from = datetime(2026, 8, 1, tzinfo=timezone.utc)
    date_to = datetime(2026, 8, 31, 23, 59, 59, tzinfo=timezone.utc)

    adapter.search(MailFolder.DRAFTS, date_from=date_from, date_to=date_to)

    items.Sort.assert_called_once_with("[LastModificationTime]", True)


def _inbox_message(mocker, entry_id: str, received: datetime):
    return mocker.Mock(
        Class=43, EntryID=entry_id, Subject="Factura", SenderName="Ana",
        SenderEmailAddress="ana@example.com", ReceivedTime=received,
        Attachments=mocker.Mock(Count=0),
    )


def test_inbox_search_early_stops_after_limit_plus_one_matches(mocker):
    """search-result-caps' "+1 peek" convention: mapped-folder search()
    must stop iterating once `limit + 1` post-filter matches are seen
    (never a full unbounded fetch), leaving the tool layer to slice to
    `limit` and flag `results_truncated`."""
    from tools.mail_adapter import OutlookMailAdapter

    dispatch_mock = _install_fake_win32com(mocker)
    outlook_app = mocker.Mock(name="OutlookApplication")
    dispatch_mock.return_value = outlook_app
    namespace = mocker.Mock(name="Namespace")
    outlook_app.GetNamespace.return_value = namespace
    folder = mocker.Mock(name="InboxFolder")
    namespace.GetDefaultFolder.return_value = folder
    items = mocker.Mock(name="Items")
    folder.Items = items
    restricted_items = mocker.Mock(name="RestrictedItems")
    items.Restrict.return_value = restricted_items

    # Seeded newest-first (5 messages) — with limit=3, early stop must occur
    # after exactly 4 (limit+1) are consumed, leaving the 5th untouched.
    seeded = [
        _inbox_message(mocker, f"M{i}", datetime(2026, 8, 10 - i, 9, 0, tzinfo=timezone.utc))
        for i in range(5)
    ]
    consumed: list[str] = []

    def _tracking_iter():
        for item in seeded:
            consumed.append(item.EntryID)
            yield item

    restricted_items.__iter__ = mocker.Mock(side_effect=lambda: _tracking_iter())

    adapter = OutlookMailAdapter()
    date_from = datetime(2026, 8, 1, tzinfo=timezone.utc)
    date_to = datetime(2026, 8, 31, 23, 59, 59, tzinfo=timezone.utc)

    results = adapter.search(
        MailFolder.INBOX, date_from=date_from, date_to=date_to, limit=3
    )

    assert consumed == ["M0", "M1", "M2", "M3"]
    assert [r.entry_id for r in results] == ["M0", "M1", "M2", "M3"]


def test_inbox_search_returns_all_when_under_limit_no_early_stop(mocker):
    from tools.mail_adapter import OutlookMailAdapter

    dispatch_mock = _install_fake_win32com(mocker)
    outlook_app = mocker.Mock(name="OutlookApplication")
    dispatch_mock.return_value = outlook_app
    namespace = mocker.Mock(name="Namespace")
    outlook_app.GetNamespace.return_value = namespace
    folder = mocker.Mock(name="InboxFolder")
    namespace.GetDefaultFolder.return_value = folder
    items = mocker.Mock(name="Items")
    folder.Items = items
    restricted_items = mocker.Mock(name="RestrictedItems")
    items.Restrict.return_value = restricted_items

    seeded = [
        _inbox_message(mocker, f"M{i}", datetime(2026, 8, 10 - i, 9, 0, tzinfo=timezone.utc))
        for i in range(2)
    ]
    restricted_items.__iter__ = mocker.Mock(return_value=iter(seeded))

    adapter = OutlookMailAdapter()
    date_from = datetime(2026, 8, 1, tzinfo=timezone.utc)
    date_to = datetime(2026, 8, 31, 23, 59, 59, tzinfo=timezone.utc)

    results = adapter.search(
        MailFolder.INBOX, date_from=date_from, date_to=date_to, limit=50
    )

    assert [r.entry_id for r in results] == ["M0", "M1"]


def test_folder_path_search_sorts_python_side_descending_and_bounds_to_limit_plus_one(
    mocker,
):
    """`folder_path` search() has no COM-level Sort() available (no
    reliable date field known ahead of time) — the full, already-scanned
    match list must be sorted descending by resolved date in Python, then
    bounded to `limit + 1` (same "+1 peek" convention as the mapped-folder
    early-stop path), per design.md's ordering table."""
    from tools.mail_adapter import OutlookMailAdapter

    dispatch_mock = _install_fake_win32com(mocker)
    outlook_app = mocker.Mock(name="OutlookApplication")
    dispatch_mock.return_value = outlook_app
    namespace = mocker.Mock(name="Namespace")
    outlook_app.GetNamespace.return_value = namespace

    default_store = mocker.Mock(name="DefaultStore")
    namespace.DefaultStore = default_store
    root_folder = mocker.Mock(name="RootFolder")
    default_store.GetRootFolder.return_value = root_folder
    target_folder = mocker.Mock(name="TargetFolder")
    root_folder.Folders.Item.return_value = target_folder
    items = mocker.Mock(name="Items")
    target_folder.Items = items

    # Seeded out of order — 4 messages, limit=2 -> bounded to 3 (limit+1),
    # newest-first.
    def _msg(entry_id, received):
        return mocker.Mock(
            Class=43, EntryID=entry_id, Subject="Uno", SenderName="Ana",
            SenderEmailAddress="ana@example.com",
            ReceivedTime=received, SentOn=None,
            Attachments=mocker.Mock(Count=0),
        )

    p1 = _msg("P1", datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc))
    p2 = _msg("P2", datetime(2026, 8, 20, 9, 0, tzinfo=timezone.utc))
    p3 = _msg("P3", datetime(2026, 8, 1, 9, 0, tzinfo=timezone.utc))
    p4 = _msg("P4", datetime(2026, 8, 15, 9, 0, tzinfo=timezone.utc))
    items.__iter__ = mocker.Mock(return_value=iter([p1, p2, p3, p4]))

    adapter = OutlookMailAdapter()
    results = adapter.search(folder_path="Proyectos", limit=2)

    assert [r.entry_id for r in results] == ["P2", "P4", "P1"]


def test_folder_path_search_returns_all_when_under_limit_plus_one(mocker):
    from tools.mail_adapter import OutlookMailAdapter

    dispatch_mock = _install_fake_win32com(mocker)
    outlook_app = mocker.Mock(name="OutlookApplication")
    dispatch_mock.return_value = outlook_app
    namespace = mocker.Mock(name="Namespace")
    outlook_app.GetNamespace.return_value = namespace

    default_store = mocker.Mock(name="DefaultStore")
    namespace.DefaultStore = default_store
    root_folder = mocker.Mock(name="RootFolder")
    default_store.GetRootFolder.return_value = root_folder
    target_folder = mocker.Mock(name="TargetFolder")
    root_folder.Folders.Item.return_value = target_folder
    items = mocker.Mock(name="Items")
    target_folder.Items = items

    def _msg(entry_id, received):
        return mocker.Mock(
            Class=43, EntryID=entry_id, Subject="Uno", SenderName="Ana",
            SenderEmailAddress="ana@example.com",
            ReceivedTime=received, SentOn=None,
            Attachments=mocker.Mock(Count=0),
        )

    p1 = _msg("P1", datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc))
    p2 = _msg("P2", datetime(2026, 8, 20, 9, 0, tzinfo=timezone.utc))
    items.__iter__ = mocker.Mock(return_value=iter([p1, p2]))

    adapter = OutlookMailAdapter()
    results = adapter.search(folder_path="Proyectos", limit=50)

    assert [r.entry_id for r in results] == ["P2", "P1"]
