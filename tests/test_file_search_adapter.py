"""Tests for tools/file_search_adapter.py's WindowsSearchAdapter — the
real, ADODB (`Provider=Search.CollatorDSO`)-backed `FileSearchPort`
implementation (file-search change, Phase 3).

Mirrors tests/test_outlook_adapter.py's win32com/pythoncom `sys.modules`
injection pattern: `win32com`/`pythoncom` are never installed on this WSL2
dev host (project policy: MUST NOT be pip-installed, MUST NOT be imported
at module load time), so every test that exercises `WindowsSearchAdapter`
injects fake `win32com.client`/`pythoncom` modules into `sys.modules`
before constructing/calling the adapter.

`ADODB.Connection` and `ADODB.Recordset` are the two distinct COM objects
`win32com.client.Dispatch()` returns — per the windows-search-adapter
spec's own scenario wording ("the SQL text passed to `Recordset.Open`"):
the adapter opens a `Connection`, then opens a `Recordset` against it with
the built SQL, and reads rows via `Fields.Item(name).Value` + `MoveNext()`
until `EOF`. `_FakeConnection`/`_FakeRecordset` below are small hand-rolled
doubles (not `mocker.Mock`) so `.EOF`/`.Fields`/`.MoveNext()` behave like
real stateful COM objects across a loop, while `.Open()` still records
its call args for the escaping/TOP-n/failure assertions.

The bottom two sections (file-search-resilience change, Phases 3-4) add
`PowerShellSearchBridge` (a `subprocess.run`-backed fallback transport —
no COM/win32com involved, so no `sys.modules` injection needed there) and
`FallbackSearchAdapter` (a pure composition seam over two `FileSearchPort`
doubles — no subprocess/COM involved at all).
"""
import importlib
import json
import subprocess
import sys
import threading
import types
from datetime import datetime
from pathlib import Path

import pytest

from models.schemas import FileDetail, FileSummary
from tools.errors import FileNotFoundInIndexError, WindowsSearchUnavailableError


class _FakeField:
    def __init__(self, value):
        self.Value = value


class _FakeFields:
    def __init__(self, row: dict):
        self._row = row

    def Item(self, name):
        return _FakeField(self._row.get(name))


class _FakeRecordset:
    """`rows` is a list of `System.*` field-name -> value dicts, standing
    in for what a real query would already have fetched by the time
    `.Open()` returns. `.Open()` records the SQL text (`last_sql`) and the
    connection object passed to it, and optionally raises `open_error`
    (the "Recordset.Open fails" half of the Connection Failure
    requirement)."""

    def __init__(self, rows: list[dict] | None = None, open_error: Exception | None = None):
        self._rows = rows or []
        self._index = 0
        self._open_error = open_error
        self.last_sql = None
        self.last_connection = None

    def Open(self, sql, connection):
        self.last_sql = sql
        self.last_connection = connection
        if self._open_error is not None:
            raise self._open_error

    @property
    def EOF(self):
        return self._index >= len(self._rows)

    @property
    def Fields(self):
        return _FakeFields(self._rows[self._index])

    def MoveNext(self):
        self._index += 1


class _FakeConnection:
    def __init__(self, open_error: Exception | None = None):
        self._open_error = open_error
        self.last_conn_str = None

    def Open(self, conn_str):
        self.last_conn_str = conn_str
        if self._open_error is not None:
            raise self._open_error


def _install_fake_pythoncom(mocker):
    """Inject a fake `pythoncom` module with a mock `CoInitialize`
    callable, returned so the test can assert call order against
    `win32com.client.Dispatch`. Mirrors test_outlook_adapter.py's helper
    of the same name."""
    mocker.patch.dict(sys.modules)
    fake_pythoncom = types.ModuleType("pythoncom")
    coinitialize_mock = mocker.Mock(name="CoInitialize")
    fake_pythoncom.CoInitialize = coinitialize_mock
    sys.modules["pythoncom"] = fake_pythoncom
    return coinitialize_mock


def _install_fake_win32com(mocker, connection=None, recordset=None):
    """Inject a fake `win32com.client` module whose `Dispatch()` returns
    `connection` for ProgID `"ADODB.Connection"` and `recordset` for
    `"ADODB.Recordset"` (each defaults to a fresh, empty double). Also
    installs a fake `pythoncom` (unless already installed), mirroring
    `test_outlook_adapter.py::_install_fake_win32com`'s precedent.

    Returns `(dispatch_mock, connection, recordset)` so the test can
    assert on `Dispatch` call order/args and inspect the connection/
    recordset doubles' captured state."""
    if "pythoncom" not in sys.modules:
        _install_fake_pythoncom(mocker)
    mocker.patch.dict(sys.modules)
    connection = connection if connection is not None else _FakeConnection()
    recordset = recordset if recordset is not None else _FakeRecordset([])

    def dispatch_side_effect(prog_id):
        if prog_id == "ADODB.Connection":
            return connection
        if prog_id == "ADODB.Recordset":
            return recordset
        raise ValueError(f"Unexpected ProgID: {prog_id!r}")

    fake_win32com = types.ModuleType("win32com")
    fake_win32com_client = types.ModuleType("win32com.client")
    dispatch_mock = mocker.Mock(name="Dispatch", side_effect=dispatch_side_effect)
    fake_win32com_client.Dispatch = dispatch_mock
    fake_win32com.client = fake_win32com_client
    sys.modules["win32com"] = fake_win32com
    sys.modules["win32com.client"] = fake_win32com_client
    return dispatch_mock, connection, recordset


# --- 3.1: module import stays win32com/pythoncom-free at module scope ---


def test_win32com_not_imported_at_module_level(mocker):
    mocker.patch.dict(sys.modules)
    sys.modules.pop("win32com", None)
    sys.modules.pop("win32com.client", None)

    import tools.file_search_adapter as module

    importlib.reload(module)

    assert "win32com" not in sys.modules
    assert "win32com.client" not in sys.modules


def test_pythoncom_not_imported_at_module_level(mocker):
    mocker.patch.dict(sys.modules)
    sys.modules.pop("pythoncom", None)

    import tools.file_search_adapter as module

    importlib.reload(module)

    assert "pythoncom" not in sys.modules


# --- 3.2: CoInitialize() before Dispatch("ADODB.Connection") ---


def test_search_calls_coinitialize_before_dispatch(mocker):
    from tools.file_search_adapter import WindowsSearchAdapter

    coinitialize_mock = _install_fake_pythoncom(mocker)
    dispatch_mock, _connection, _recordset = _install_fake_win32com(mocker)
    manager = mocker.Mock()
    manager.attach_mock(coinitialize_mock, "CoInitialize")
    manager.attach_mock(dispatch_mock, "Dispatch")

    adapter = WindowsSearchAdapter()
    adapter.search(filename="report", phrase=None, roots=["C:\\Users\\ana"], top_n=50)

    call_names = [call[0] for call in manager.mock_calls]
    assert "CoInitialize" in call_names
    assert "Dispatch" in call_names
    assert call_names.index("CoInitialize") < call_names.index("Dispatch")


def test_get_info_calls_coinitialize_before_dispatch(mocker):
    from tools.file_search_adapter import WindowsSearchAdapter

    coinitialize_mock = _install_fake_pythoncom(mocker)
    row = {
        "System.ItemPathDisplay": "C:\\Users\\ana\\report.docx",
        "System.ItemName": "report.docx",
        "System.Size": 10,
        "System.DateModified": datetime(2026, 1, 1),
        "System.DateCreated": datetime(2026, 1, 1),
    }
    dispatch_mock, _connection, _recordset = _install_fake_win32com(
        mocker, recordset=_FakeRecordset([row])
    )
    manager = mocker.Mock()
    manager.attach_mock(coinitialize_mock, "CoInitialize")
    manager.attach_mock(dispatch_mock, "Dispatch")

    adapter = WindowsSearchAdapter()
    adapter.get_info("C:\\Users\\ana\\report.docx")

    call_names = [call[0] for call in manager.mock_calls]
    assert "CoInitialize" in call_names
    assert "Dispatch" in call_names
    assert call_names.index("CoInitialize") < call_names.index("Dispatch")


# --- 3.3: SQL value escaping ---


def test_search_escapes_single_quote_in_filename(mocker):
    from tools.file_search_adapter import WindowsSearchAdapter

    _dispatch_mock, _connection, recordset = _install_fake_win32com(mocker)

    adapter = WindowsSearchAdapter()
    adapter.search(filename="o'brien", phrase=None, roots=["C:\\Users\\ana"], top_n=10)

    assert "o''brien" in recordset.last_sql
    # clause wasn't truncated early by the raw quote: the FROM/WHERE
    # machinery around it is still intact
    assert "FROM SystemIndex" in recordset.last_sql
    assert "SCOPE=" in recordset.last_sql


def test_search_escapes_single_quote_in_phrase_contains(mocker):
    from tools.file_search_adapter import WindowsSearchAdapter

    _dispatch_mock, _connection, recordset = _install_fake_win32com(mocker)

    adapter = WindowsSearchAdapter()
    adapter.search(filename=None, phrase="user's report", roots=["C:\\Users\\ana"], top_n=10)

    assert "CONTAINS(" in recordset.last_sql
    assert "user''s report" in recordset.last_sql


# --- 3.4: TOP n reflects the requested cap exactly ---


def test_search_sql_reflects_requested_top_n(mocker):
    from tools.file_search_adapter import WindowsSearchAdapter

    _dispatch_mock, _connection, recordset = _install_fake_win32com(mocker)

    adapter = WindowsSearchAdapter()
    adapter.search(filename="x", phrase=None, roots=["C:\\Users\\ana"], top_n=50)

    assert "SELECT TOP 50" in recordset.last_sql


def test_build_search_sql_row_cap_is_shared_by_both_transports(mocker):
    """ps-bridge-jsonl-hotfix (requirement 1): `_build_search_sql` is the
    ONE place a row cap is applied, and both `WindowsSearchAdapter` and
    `PowerShellSearchBridge` call it verbatim -- so the bridge's `phrase`
    leg is never an uncapped `SELECT` relying on a byte-bound reader to
    stop it. Confirmed by construction (the bridge test suite's SQL-
    equality assertions against `_build_search_sql` already prove this),
    asserted directly here as a standalone regression guard."""
    from tools.file_search_adapter import _build_search_sql

    sql = _build_search_sql(None, "Informa", ["C:\\Users\\ana"], 200)
    assert "SELECT TOP 200" in sql


def test_build_get_info_sql_is_capped_at_top_1(mocker):
    """ps-bridge-jsonl-hotfix (requirement 1): `get_info`'s single-row
    lookup is always `TOP 1` -- never an uncapped `SELECT` -- for both
    the ADO adapter and the PowerShell bridge, which shares this exact
    builder."""
    from tools.file_search_adapter import _build_get_info_sql

    sql = _build_get_info_sql("C:\\Users\\ana\\report.docx")
    assert sql.startswith("SELECT TOP 1 ")


# --- 3.5: ItemUrl-only row is normalized to native path form ---


def test_search_maps_item_url_only_row_to_normalized_path(mocker):
    from tools.file_search_adapter import WindowsSearchAdapter

    row = {
        "System.ItemName": "My Report.docx",
        "System.ItemPathDisplay": None,
        "System.ItemUrl": "file:///C:/Users/ana/My%20Report.docx",
        "System.Size": 1024,
        "System.DateModified": datetime(2026, 1, 1),
        "System.Kind": ("link",),
        "System.FileExtension": ".docx",
    }
    _dispatch_mock, _connection, _recordset = _install_fake_win32com(
        mocker, recordset=_FakeRecordset([row])
    )

    adapter = WindowsSearchAdapter()
    results = adapter.search(filename=None, phrase=None, roots=["C:\\Users\\ana"], top_n=10)

    assert len(results) == 1
    assert results[0].path == "C:\\Users\\ana\\My Report.docx"
    assert results[0].name == "My Report.docx"
    assert results[0].kind == "link"


def test_search_happy_path_returns_mapped_summaries(mocker):
    """Triangulation: general round-trip with filename+phrase+roots all
    provided together and ItemPathDisplay present (the common case, as
    opposed to the ItemUrl-only fallback above)."""
    from tools.file_search_adapter import WindowsSearchAdapter

    rows = [
        {
            "System.ItemName": "report.docx",
            "System.ItemPathDisplay": "C:\\Users\\ana\\Documents\\report.docx",
            "System.ItemUrl": "file:///C:/Users/ana/Documents/report.docx",
            "System.Size": 4096,
            "System.DateModified": datetime(2026, 2, 1),
            "System.Kind": ("document", "picture"),
            "System.FileExtension": ".docx",
        },
    ]
    _dispatch_mock, connection, recordset = _install_fake_win32com(
        mocker, recordset=_FakeRecordset(rows)
    )

    adapter = WindowsSearchAdapter()
    results = adapter.search(
        filename="report", phrase="quarterly", roots=["C:\\Users\\ana"], top_n=25
    )

    assert connection.last_conn_str == (
        "Provider=Search.CollatorDSO;Extended Properties='Application=Windows'"
    )
    assert "SCOPE='file:C:\\Users\\ana'" in recordset.last_sql
    assert "SELECT TOP 25" in recordset.last_sql
    assert len(results) == 1
    assert results[0].name == "report.docx"
    assert results[0].size == 4096
    assert results[0].kind == "document; picture"
    assert results[0].extension == ".docx"


# --- alias-containment-hotfix: alt_url_path exposed alongside path ---


def test_search_row_with_display_and_url_both_present_exposes_alt_url_path(mocker):
    """alias-containment-hotfix: even when System.ItemPathDisplay is
    present (and thus still preferred for `path`, per "Path
    Representation Normalization"), the ItemUrl-derived native form MUST
    also be exposed via `alt_url_path` — Windows Search can report a
    redirected-library alias in ItemPathDisplay (e.g. a `Documents`
    library shortcut into a OneDrive-synced tree) while ItemUrl still
    carries the real, containable path underneath. The tool layer
    (tools/file_search.py) is what actually uses this for an
    allowed-roots fallback; this adapter-level test only pins the
    row-mapping half of the fix."""
    from tools.file_search_adapter import WindowsSearchAdapter

    row = {
        "System.ItemName": "notes.txt",
        "System.ItemPathDisplay": "C:\\Documents\\OneDrive - Informa\\notes.txt",
        "System.ItemUrl": "file:///C:/co/OneDrive%20-%20Informa/notes.txt",
        "System.Size": 10,
        "System.DateModified": datetime(2026, 1, 1),
        "System.Kind": None,
        "System.FileExtension": ".txt",
    }
    _install_fake_win32com(mocker, recordset=_FakeRecordset([row]))

    adapter = WindowsSearchAdapter()
    results = adapter.search(filename=None, phrase=None, roots=["C:\\co"], top_n=10)

    assert len(results) == 1
    assert results[0].path == "C:\\Documents\\OneDrive - Informa\\notes.txt"
    assert results[0].alt_url_path == "C:\\co\\OneDrive - Informa\\notes.txt"


def test_search_row_with_no_item_url_leaves_alt_url_path_none(mocker):
    from tools.file_search_adapter import WindowsSearchAdapter

    row = {
        "System.ItemName": "report.docx",
        "System.ItemPathDisplay": "C:\\Users\\ana\\Documents\\report.docx",
        "System.ItemUrl": None,
        "System.Size": 10,
        "System.DateModified": datetime(2026, 1, 1),
        "System.Kind": None,
        "System.FileExtension": ".docx",
    }
    _install_fake_win32com(mocker, recordset=_FakeRecordset([row]))

    adapter = WindowsSearchAdapter()
    results = adapter.search(filename=None, phrase=None, roots=["C:\\Users\\ana"], top_n=10)

    assert len(results) == 1
    assert results[0].alt_url_path is None


def test_get_info_detail_exposes_alt_url_path_when_display_and_url_both_present(mocker):
    from tools.file_search_adapter import WindowsSearchAdapter

    row = {
        "System.ItemName": "notes.txt",
        "System.ItemPathDisplay": "C:\\Documents\\OneDrive - Informa\\notes.txt",
        "System.ItemUrl": "file:///C:/co/OneDrive%20-%20Informa/notes.txt",
        "System.Size": 10,
        "System.DateModified": datetime(2026, 1, 1),
        "System.Kind": None,
        "System.FileExtension": ".txt",
        "System.DateCreated": datetime(2026, 1, 1),
        "System.Search.AutoSummary": None,
    }
    _install_fake_win32com(mocker, recordset=_FakeRecordset([row]))

    adapter = WindowsSearchAdapter()
    detail = adapter.get_info("C:\\Documents\\OneDrive - Informa\\notes.txt")

    assert detail.alt_url_path == "C:\\co\\OneDrive - Informa\\notes.txt"


# --- 3.6: connection/query failure maps to a typed error ---


def test_connection_open_failure_raises_windows_search_unavailable(mocker):
    from tools.file_search_adapter import WindowsSearchAdapter

    _dispatch_mock, _connection, _recordset = _install_fake_win32com(
        mocker, connection=_FakeConnection(open_error=Exception("COM error: 0x80040154"))
    )

    adapter = WindowsSearchAdapter()
    with pytest.raises(WindowsSearchUnavailableError):
        adapter.search(filename="x", phrase=None, roots=["C:\\Users\\ana"], top_n=10)

    with pytest.raises(WindowsSearchUnavailableError):
        adapter.get_info("C:\\Users\\ana\\report.docx")


def test_recordset_open_failure_raises_windows_search_unavailable(mocker):
    from tools.file_search_adapter import WindowsSearchAdapter

    _dispatch_mock, _connection, _recordset = _install_fake_win32com(
        mocker, recordset=_FakeRecordset(open_error=Exception("Recordset.Open failed"))
    )

    adapter = WindowsSearchAdapter()
    with pytest.raises(WindowsSearchUnavailableError):
        adapter.search(filename="x", phrase=None, roots=["C:\\Users\\ana"], top_n=10)


def test_win32com_import_error_raises_windows_search_unavailable(mocker):
    """Triangulation: when win32com genuinely isn't importable (this
    host's real state outside of test mocking), the adapter must map the
    ImportError to WindowsSearchUnavailableError."""
    from tools.file_search_adapter import WindowsSearchAdapter

    mocker.patch.dict(sys.modules)
    sys.modules.pop("win32com", None)
    sys.modules.pop("win32com.client", None)
    mocker.patch.dict(sys.modules, {"win32com.client": None})

    adapter = WindowsSearchAdapter()
    with pytest.raises(WindowsSearchUnavailableError):
        adapter.get_info("C:\\Users\\ana\\ghost.txt")


# --- 3.7: get_info() exact lookup, not-found, placeholder snippet=None ---


def test_get_info_returns_detail_for_matching_row(mocker):
    from tools.file_search_adapter import WindowsSearchAdapter

    row = {
        "System.ItemName": "report.docx",
        "System.ItemPathDisplay": "C:\\Users\\ana\\Documents\\report.docx",
        "System.ItemUrl": "file:///C:/Users/ana/Documents/report.docx",
        "System.Size": 2048,
        "System.DateModified": datetime(2026, 1, 2),
        "System.DateCreated": datetime(2025, 12, 1),
        "System.Kind": "document",
        "System.FileExtension": ".docx",
        "System.Search.AutoSummary": "Quarterly report summary",
    }
    _dispatch_mock, _connection, recordset = _install_fake_win32com(
        mocker, recordset=_FakeRecordset([row])
    )

    adapter = WindowsSearchAdapter()
    detail = adapter.get_info("C:\\Users\\ana\\Documents\\report.docx")

    assert "C:\\Users\\ana\\Documents\\report.docx" in recordset.last_sql
    assert detail.path == "C:\\Users\\ana\\Documents\\report.docx"
    assert detail.name == "report.docx"
    assert detail.size == 2048
    assert detail.created_time == datetime(2025, 12, 1)
    assert detail.snippet == "Quarterly report summary"
    # Defensive case: some providers/rows may still hand back System.Kind
    # as a plain string rather than a VT_VECTOR tuple — must pass through.
    assert detail.kind == "document"


def test_get_info_raises_file_not_found_when_no_row(mocker):
    from tools.file_search_adapter import WindowsSearchAdapter

    _dispatch_mock, _connection, _recordset = _install_fake_win32com(
        mocker, recordset=_FakeRecordset([])
    )

    adapter = WindowsSearchAdapter()
    with pytest.raises(FileNotFoundInIndexError):
        adapter.get_info("C:\\Users\\ana\\ghost.txt")


def test_get_info_snippet_none_when_absent(mocker):
    """Placeholder (unhydrated OneDrive Files-On-Demand) file: core
    metadata is present but there is no content-derived snippet."""
    from tools.file_search_adapter import WindowsSearchAdapter

    row = {
        "System.ItemName": "placeholder.pdf",
        "System.ItemPathDisplay": "C:\\Users\\ana\\OneDrive\\placeholder.pdf",
        "System.ItemUrl": None,
        "System.Size": 512,
        "System.DateModified": datetime(2026, 1, 3),
        "System.DateCreated": datetime(2026, 1, 3),
        "System.Kind": "document",
        "System.FileExtension": ".pdf",
        "System.Search.AutoSummary": None,
    }
    _dispatch_mock, _connection, _recordset = _install_fake_win32com(
        mocker, recordset=_FakeRecordset([row])
    )

    adapter = WindowsSearchAdapter()
    detail = adapter.get_info("C:\\Users\\ana\\OneDrive\\placeholder.pdf")

    assert detail.size == 512
    assert detail.snippet is None


# --- 3.8: System.Kind multi-value (VT_VECTOR) normalization ---
#
# Real ADODB/win32com returns `System.Kind` as a tuple of strings (Windows
# multi-value property), not a plain string — e.g. `('link',)` or
# `('document', 'picture')`. Constructing `FileSummary`/`FileDetail` with a
# raw tuple `kind` used to blow up pydantic validation
# (`Input should be a valid string [type=string_type, input_value=('link',)]`
# — the live-QA smoke-test failure this fixes). The three tests above
# (`test_search_maps_item_url_only_row_to_normalized_path`,
# `test_search_happy_path_returns_mapped_summaries`,
# `test_get_info_returns_detail_for_matching_row`) cover the single-element
# tuple, multi-element tuple, and defensive plain-string cases respectively
# for `kind`. The two tests below cover the remaining edge cases: an empty
# tuple and a `None` value must both still normalize to `None`.


def test_search_kind_empty_tuple_normalizes_to_none(mocker):
    from tools.file_search_adapter import WindowsSearchAdapter

    row = {
        "System.ItemName": "mystery.bin",
        "System.ItemPathDisplay": "C:\\Users\\ana\\mystery.bin",
        "System.ItemUrl": None,
        "System.Size": 1,
        "System.DateModified": datetime(2026, 1, 1),
        "System.Kind": (),
        "System.FileExtension": ".bin",
    }
    _dispatch_mock, _connection, _recordset = _install_fake_win32com(
        mocker, recordset=_FakeRecordset([row])
    )

    adapter = WindowsSearchAdapter()
    results = adapter.search(filename=None, phrase=None, roots=["C:\\Users\\ana"], top_n=10)

    assert results[0].kind is None


def test_search_kind_none_stays_none(mocker):
    from tools.file_search_adapter import WindowsSearchAdapter

    row = {
        "System.ItemName": "mystery.bin",
        "System.ItemPathDisplay": "C:\\Users\\ana\\mystery.bin",
        "System.ItemUrl": None,
        "System.Size": 1,
        "System.DateModified": datetime(2026, 1, 1),
        "System.Kind": None,
        "System.FileExtension": ".bin",
    }
    _dispatch_mock, _connection, _recordset = _install_fake_win32com(
        mocker, recordset=_FakeRecordset([row])
    )

    adapter = WindowsSearchAdapter()
    results = adapter.search(filename=None, phrase=None, roots=["C:\\Users\\ana"], top_n=10)

    assert results[0].kind is None


# --- END Phase 1-2/original file-search Phase 3 tests ---


# --- Phase 3: PowerShellSearchBridge (file-search-resilience change) ---
#
# Security-critical: caller-controlled values (filename/phrase/roots/path)
# must never appear on the subprocess.run argv. `subprocess.run` itself is
# mocked in every test below — no real `powershell.exe` is ever invoked
# (none exists on this WSL2 host anyway). Per the live security review,
# escaping/SQL-building happens in EXACTLY ONE place — Python, via
# `_build_search_sql`/`_build_get_info_sql` (the same functions
# `WindowsSearchAdapter` calls) — and the finished SQL text is the only
# thing written to the child's stdin, as `{"sql": "..."}`; the deployed
# `.ps1` is a dumb executor of that string. Tests below assert against
# the SQL text captured from stdin, not against per-field JSON keys.


def _row_lines(rows: list[dict], *, count: int | None = None, done: bool = True) -> list[str]:
    """Build the list of stdout lines (each already carrying its own
    trailing `"\\n"`) `tools/ps_bridge_search.ps1` would flush for `rows`
    -- one compact JSON object per row -- optionally followed by the
    `{"done": true, "count": N}` sentinel line. `done=False` omits the
    sentinel entirely, simulating a stream cut short before it was ever
    written. A list (not one joined string) because `_LineStream` below
    hands these back one at a time via `readline()`, matching how
    `PowerShellSearchBridge._invoke` (bridge-streaming-hotfix) now reads
    the bridge's stdout incrementally rather than all at once."""
    lines = [json.dumps(row) + "\n" for row in rows]
    if done:
        lines.append(
            json.dumps({"done": True, "count": count if count is not None else len(rows)}) + "\n"
        )
    return lines


class _FakeStdin:
    """Double for a `Popen(text=True)` child's stdin: records exactly what
    was written before `close()`, mirroring the dumb-executor contract
    (`PowerShellSearchBridge` writes the `{"sql": ...}` JSON payload, then
    closes stdin so the script's `[Console]::In.ReadToEnd()` returns)."""

    def __init__(self) -> None:
        self.written = ""
        self.closed = False

    def write(self, data: str) -> None:
        self.written += data

    def close(self) -> None:
        self.closed = True


class _LineStream:
    """Double for a `Popen(text=True)` pipe's `readline()`: pops entries
    off `lines` (each already carrying its own trailing `"\\n"`, except a
    deliberately-partial final entry with none) one call at a time. Once
    exhausted, behaves per `at_end`:

    - `"eof"` (default): every further call returns `""` — a clean,
      already-closed pipe, matching a child that exited normally.
    - `"hang"`: every further call blocks forever on a `threading.Event`
      that is never set — simulating a child that streamed some rows
      then stopped responding without closing its pipe. Only safe to use
      in a test because the caller (`_pump_stdout`'s reader thread) is a
      daemon thread `PowerShellSearchBridge._invoke` never joins
      indefinitely — see its own docstring."""

    def __init__(self, lines: list[str], at_end: str = "eof") -> None:
        self._lines = list(lines)
        self._at_end = at_end
        self._never = threading.Event()

    def readline(self) -> str:
        if self._lines:
            return self._lines.pop(0)
        if self._at_end == "hang":
            self._never.wait()
        return ""


class _FixedReadStream:
    """Double for a `Popen(text=True)` pipe's `.read()` (used for
    stderr) — returns a fixed string once, matching stderr already fully
    written and flushed by the time the parent reads it."""

    def __init__(self, data: str = "") -> None:
        self._data = data

    def read(self) -> str:
        return self._data


class _NoneReadStream:
    """Hostile stderr double: `.read()` returns `None` instead of a
    string — `_pump_stderr` must not crash on this."""

    def read(self):
        return None


class _FakeProcess:
    """Double for `subprocess.Popen(..., text=True)`'s return value —
    exactly the surface `PowerShellSearchBridge._invoke` touches:
    `.stdin` (write + close), `.stdout`/`.stderr` (`readline()`/`read()`),
    `.kill()`, `.wait(timeout=...)`, `.returncode`. `kill()` flips the
    stdout double to `"eof"` — a real kill closes the child's pipes, so a
    reader thread blocked on `readline()` (the non-"hang" case) sees a
    clean EOF shortly after."""

    def __init__(
        self,
        stdout_lines: list[str] = (),
        *,
        at_end: str = "eof",
        stderr_data: str = "",
        returncode: int = 0,
    ) -> None:
        self.stdin = _FakeStdin()
        self.stdout = _LineStream(list(stdout_lines), at_end=at_end)
        self.stderr = _FixedReadStream(stderr_data)
        self.returncode = returncode
        self.kill_calls = 0

    def kill(self) -> None:
        self.kill_calls += 1
        self.stdout._at_end = "eof"

    def wait(self, timeout=None):
        return self.returncode


def _patch_popen(mocker, stdout_lines=(), *, at_end="eof", stderr_data="", returncode=0):
    """Patch `subprocess.Popen` to return a `_FakeProcess` built from the
    given stdout lines/exit shape. Returns `(popen_mock, process)` so a
    test can assert on the captured argv/kwargs AND inspect the process
    double's `.stdin.written`/`.kill_calls`/etc."""
    process = _FakeProcess(list(stdout_lines), at_end=at_end, stderr_data=stderr_data, returncode=returncode)
    popen_mock = mocker.patch("tools.file_search_adapter.subprocess.Popen", return_value=process)
    return popen_mock, process


def _tiny_timeout(mocker, seconds: float = 0.05):
    """Patch the bridge's read deadline to something a test can actually
    wait out in real time — required by every scenario that relies on
    the deadline loop firing (a "hangs" child, never a real 30s wait)."""
    return mocker.patch(
        "tools.file_search_adapter.file_search_ps_bridge_timeout_seconds",
        return_value=seconds,
    )


def _stdin_sql(process: "_FakeProcess") -> str:
    return json.loads(process.stdin.written)["sql"]


# --- 3.1/3.2: pinned absolute exe + exact flags/-File argv ---


def test_bridge_search_invokes_pinned_absolute_powershell_with_file_flag(mocker):
    from tools.file_search_adapter import _PS_BRIDGE_SCRIPT, _PS_EXE, PowerShellSearchBridge

    popen_mock, _process = _patch_popen(mocker, stdout_lines=_row_lines([]))

    bridge = PowerShellSearchBridge()
    bridge.search(filename="report", phrase=None, roots=["C:\\Users\\ana"], top_n=10)

    popen_mock.assert_called_once()
    argv = popen_mock.call_args.args[0]
    assert argv[0] == _PS_EXE
    assert argv[0] == r"C:\WINDOWS\System32\WindowsPowerShell\v1.0\powershell.exe"
    assert "-File" in argv
    script_path = argv[argv.index("-File") + 1]
    assert script_path == str(_PS_BRIDGE_SCRIPT)
    assert Path(script_path).is_absolute()
    # bridge-streaming-hotfix: Popen (not subprocess.run), text mode,
    # with all three pipes wired for the streaming reader/writer.
    assert popen_mock.call_args.kwargs["text"] is True
    assert popen_mock.call_args.kwargs["stdin"] == subprocess.PIPE
    assert popen_mock.call_args.kwargs["stdout"] == subprocess.PIPE
    assert popen_mock.call_args.kwargs["stderr"] == subprocess.PIPE


def test_bridge_argv_is_exactly_the_pinned_flag_set(mocker):
    from tools.file_search_adapter import _PS_BRIDGE_SCRIPT, _PS_EXE, PowerShellSearchBridge

    row = {
        "ItemPathDisplay": "C:\\Users\\ana\\report.docx",
        "ItemName": "report.docx",
        "Size": 10,
        "DateModified": "2026-01-01T00:00:00",
        "DateCreated": "2026-01-01T00:00:00",
    }
    popen_mock, _process = _patch_popen(mocker, stdout_lines=_row_lines([row]))

    bridge = PowerShellSearchBridge()
    bridge.get_info("C:\\Users\\ana\\report.docx")

    argv = popen_mock.call_args.args[0]
    assert argv == [
        _PS_EXE,
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(_PS_BRIDGE_SCRIPT),
    ]
    # never PATH-resolved "powershell"/"pwsh"
    assert "powershell" not in argv
    assert "pwsh" not in argv


# --- 3.3: caller-controlled values absent from argv, present on stdin ---


def test_bridge_caller_values_absent_from_argv_present_on_stdin(mocker):
    from tools.file_search_adapter import PowerShellSearchBridge

    popen_mock, process = _patch_popen(mocker, stdout_lines=_row_lines([]))

    bridge = PowerShellSearchBridge()
    bridge.search(
        filename="quarterly-report", phrase="user's confidential report", roots=["C:\\Users\\ana"], top_n=10
    )

    argv = popen_mock.call_args.args[0]
    argv_text = " ".join(str(item) for item in argv)
    assert "quarterly-report" not in argv_text
    assert "confidential" not in argv_text

    assert process.stdin.closed is True
    assert "quarterly-report" in process.stdin.written
    assert "confidential" in process.stdin.written
    payload = json.loads(process.stdin.written)
    assert "quarterly-report" in payload["sql"]
    assert "confidential" in payload["sql"]


# --- 3.4: escaper/builder table -- exact SQL literal per hostile input ---
#
# Table-driven per the live security review: assert the EXACT escaped
# literal `_escape_like_value` produces for a spread of inputs, not just
# the happy path. `_escape_like_value` is the single shared helper reused
# by both `_build_search_sql` (the ADO adapter's own LIKE clause) and,
# transitively, `PowerShellSearchBridge` (which calls `_build_search_sql`
# directly) -- so this table covers both transports' escaping at once.

_ESCAPE_LIKE_VALUE_CASES = [
    ("o'brien", "o''brien"),
    ("100%", "100[%]"),
    ("a_b", "a[_]b"),
    ("[abc]", "[[]abc]"),
    ("it''s", "it''''s"),
    ("\\", "\\"),
    ("", ""),
    ("%_[", "[%][_][[]"),
    ("a" * 1000, "a" * 1000),
]


@pytest.mark.parametrize("raw,expected", _ESCAPE_LIKE_VALUE_CASES)
def test_escape_like_value_table(raw, expected):
    from tools.file_search_adapter import _escape_like_value

    assert _escape_like_value(raw) == expected


def test_escape_like_value_is_quote_doubling_composed_with_bracket_escaping():
    """Sanity-check the composition order documented on `_escape_like_value`:
    quote-doubling first, then bracket-escaping -- verified via the two
    sub-helpers directly rather than relying only on the table above."""
    from tools.file_search_adapter import _escape_like_metacharacters, _escape_like_value, _escape_sql

    value = "100%_[done]"
    assert _escape_like_value(value) == _escape_like_metacharacters(_escape_sql(value))
    assert _escape_like_value(value) == "100[%][_][[]done]"


def test_bridge_search_sql_reuses_build_search_sql_with_like_escaped_filename(mocker):
    """The bridge's SQL is byte-for-byte what `_build_search_sql` (the
    ADO adapter's own builder) produces for the same inputs -- proving
    there is exactly one SQL-building/escaping code path, not two."""
    from tools.file_search_adapter import PowerShellSearchBridge, _build_search_sql

    _popen_mock, process = _patch_popen(mocker, stdout_lines=_row_lines([]))

    bridge = PowerShellSearchBridge()
    bridge.search(filename="100%_[done]", phrase=None, roots=["C:\\Users\\ana"], top_n=10)

    expected_sql = _build_search_sql("100%_[done]", None, ["C:\\Users\\ana"], 10)
    assert _stdin_sql(process) == expected_sql
    assert "100[%][_][[]done]" in expected_sql


def test_bridge_search_sql_has_quote_doubled_phrase(mocker):
    from tools.file_search_adapter import PowerShellSearchBridge

    _popen_mock, process = _patch_popen(mocker, stdout_lines=_row_lines([]))

    bridge = PowerShellSearchBridge()
    bridge.search(filename=None, phrase="user's report", roots=["C:\\Users\\ana"], top_n=10)

    sql = _stdin_sql(process)
    assert "CONTAINS(" in sql
    assert "user''s report" in sql


# --- 3.5/3.6: hostile input never evaluated, only escaped data ---


def test_bridge_search_hostile_single_quote_filename_returns_results_not_parse_error(mocker):
    from tools.file_search_adapter import PowerShellSearchBridge

    rows = [
        {
            "ItemName": "o'brien.txt",
            "ItemPathDisplay": "C:\\Users\\ana\\o'brien.txt",
            "ItemUrl": None,
            "Size": 10,
            "DateModified": "2026-01-01T00:00:00",
            "Kind": "document",
            "FileExtension": ".txt",
        }
    ]
    popen_mock, process = _patch_popen(mocker, stdout_lines=_row_lines(rows))

    bridge = PowerShellSearchBridge()
    results = bridge.search(filename="o'brien", phrase=None, roots=["C:\\Users\\ana"], top_n=10)

    sql = _stdin_sql(process)
    assert "o''brien" in sql
    argv_text = " ".join(str(a) for a in popen_mock.call_args.args[0])
    assert "o'brien" not in argv_text
    assert len(results) == 1
    assert isinstance(results[0], FileSummary)
    assert results[0].name == "o'brien.txt"


def test_bridge_search_command_substitution_phrase_never_reaches_argv_or_command_string(mocker):
    from tools.file_search_adapter import PowerShellSearchBridge

    popen_mock, process = _patch_popen(mocker, stdout_lines=_row_lines([]))

    bridge = PowerShellSearchBridge()
    results = bridge.search(filename=None, phrase="$(Get-Date)", roots=["C:\\Users\\ana"], top_n=10)

    argv = popen_mock.call_args.args[0]
    assert not any("$(Get-Date)" in str(a) for a in argv)
    assert not any(a in ("-Command", "-EncodedCommand") for a in argv)
    sql = _stdin_sql(process)
    assert "$(Get-Date)" in sql
    assert results == []


# --- 3.7/3.8/3.9: spawn-blocked / nonzero-exit / unparseable -> typed
# error, with exit-code+stderr diagnostics (bridge-streaming-hotfix
# requirement 4) ---


def test_bridge_search_spawn_blocked_maps_to_distinctly_worded_unavailable_error(mocker):
    """The child never STARTS (missing exe / AppLocker / CLM denial /
    access-denied) -- must raise the same error TYPE as a deadline/exit
    failure but with a message an operator can tell apart from "it was
    slow" or "it produced no output"."""
    from tools.file_search_adapter import PowerShellSearchBridge

    mocker.patch(
        "tools.file_search_adapter.subprocess.Popen",
        side_effect=FileNotFoundError("no such file: powershell.exe"),
    )

    bridge = PowerShellSearchBridge()
    with pytest.raises(WindowsSearchUnavailableError) as excinfo:
        bridge.search(filename="x", phrase=None, roots=["C:\\Users\\ana"], top_n=10)

    message = str(excinfo.value)
    assert "blocked" in message.lower() or "unavailable" in message.lower()
    assert "timed out" not in message.lower()
    assert message == "PowerShell bridge blocked or unavailable: no such file: powershell.exe"


def test_bridge_search_uses_configured_timeout_as_the_read_deadline(mocker):
    """bridge-streaming-hotfix: the bridge reads
    `file_search_ps_bridge_timeout_seconds()` (default 30) once per
    `_invoke()` call as the overall wall-clock deadline for its streaming
    read loop."""
    from tools.file_search_adapter import PowerShellSearchBridge

    timeout_mock = mocker.patch(
        "tools.file_search_adapter.file_search_ps_bridge_timeout_seconds",
        return_value=30,
    )
    _patch_popen(mocker, stdout_lines=_row_lines([]))

    bridge = PowerShellSearchBridge()
    bridge.search(filename="x", phrase=None, roots=["C:\\Users\\ana"], top_n=10)

    timeout_mock.assert_called_once()


def test_bridge_search_hangs_after_n_rows_returns_partial_truncated_results(mocker):
    """The core streaming requirement: a child that streams some rows
    then stops responding (never closes its pipe, never writes the
    sentinel) is killed once the deadline elapses, and the rows it
    already streamed are returned as a truncated RESULT, not an error --
    "a killed child that already streamed N lines yields N results."""
    from tools.file_search_adapter import PowerShellSearchBridge

    _tiny_timeout(mocker)
    rows = [
        {
            "ItemName": "one.txt",
            "ItemPathDisplay": "C:\\Users\\ana\\one.txt",
            "ItemUrl": None,
            "Size": 1,
            "DateModified": "2026-01-01T00:00:00",
            "Kind": None,
            "FileExtension": ".txt",
        },
        {
            "ItemName": "two.txt",
            "ItemPathDisplay": "C:\\Users\\ana\\two.txt",
            "ItemUrl": None,
            "Size": 2,
            "DateModified": "2026-01-01T00:00:00",
            "Kind": None,
            "FileExtension": ".txt",
        },
    ]
    _popen_mock, process = _patch_popen(
        mocker, stdout_lines=_row_lines(rows, done=False), at_end="hang"
    )

    bridge = PowerShellSearchBridge()
    results = bridge.search(filename="x", phrase=None, roots=["C:\\Users\\ana"], top_n=10)

    assert {r.name for r in results} == {"one.txt", "two.txt"}
    assert bridge.last_search_truncated is True
    assert process.kill_calls >= 1


def test_bridge_search_killed_by_deadline_zero_rows_message_names_killed_at_seconds(mocker):
    """Zero rows and no sentinel by the time the deadline itself triggers
    the kill -- an ambiguous/unusable read, so it MUST raise, and the
    message MUST say `killed@Ns` (bridge-streaming-hotfix requirement 4)
    rather than a bare exit code, since there IS no real exit code yet at
    the moment we gave up waiting."""
    from tools.file_search_adapter import PowerShellSearchBridge

    _tiny_timeout(mocker, seconds=0.05)
    _popen_mock, process = _patch_popen(mocker, stdout_lines=[], at_end="hang")

    bridge = PowerShellSearchBridge()
    with pytest.raises(WindowsSearchUnavailableError) as excinfo:
        bridge.search(filename="x", phrase=None, roots=["C:\\Users\\ana"], top_n=10)

    message = str(excinfo.value)
    assert "produced no usable output" in message
    assert "killed@0.05s" in message
    assert process.kill_calls == 1


def test_bridge_search_child_dies_after_n_rows_no_sentinel_is_truncated_not_error(mocker):
    """The non-deadline half of the same requirement: the child exits
    (clean EOF on its stdout pipe) before writing the sentinel, having
    already streamed some rows -- same outcome as the deadline-kill case,
    a truncated RESULT, not an error, and no kill needed since it already
    died on its own."""
    from tools.file_search_adapter import PowerShellSearchBridge

    rows = [
        {
            "ItemName": "one.txt",
            "ItemPathDisplay": "C:\\Users\\ana\\one.txt",
            "ItemUrl": None,
            "Size": 1,
            "DateModified": "2026-01-01T00:00:00",
            "Kind": None,
            "FileExtension": ".txt",
        }
    ]
    _popen_mock, process = _patch_popen(mocker, stdout_lines=_row_lines(rows, done=False))

    bridge = PowerShellSearchBridge()
    results = bridge.search(filename="x", phrase=None, roots=["C:\\Users\\ana"], top_n=10)

    assert len(results) == 1
    assert results[0].name == "one.txt"
    assert bridge.last_search_truncated is True
    assert process.kill_calls == 0


def test_bridge_search_child_dies_nonzero_exit_with_rows_and_no_sentinel_is_truncated(mocker):
    """Same rule again, but the child's own exit code was nonzero (e.g. a
    crash after partially streaming) rather than a clean 0 -- still a
    truncated result, not an error, as long as at least one row parsed."""
    from tools.file_search_adapter import PowerShellSearchBridge

    rows = [
        {
            "ItemName": "one.txt",
            "ItemPathDisplay": "C:\\Users\\ana\\one.txt",
            "ItemUrl": None,
            "Size": 1,
            "DateModified": "2026-01-01T00:00:00",
            "Kind": None,
            "FileExtension": ".txt",
        }
    ]
    _popen_mock, process = _patch_popen(
        mocker, stdout_lines=_row_lines(rows, done=False), returncode=1
    )

    bridge = PowerShellSearchBridge()
    results = bridge.search(filename="x", phrase=None, roots=["C:\\Users\\ana"], top_n=10)

    assert len(results) == 1
    assert bridge.last_search_truncated is True


def test_bridge_search_zero_rows_no_sentinel_raises_with_exit_code_and_stderr_excerpt(mocker):
    """Zero rows AND no sentinel is never a legitimate "zero results"
    response -- even an empty result set still writes the sentinel line
    -- so it MUST raise, and the message MUST include the child's exit
    code and the stderr excerpt when present (requirement 4)."""
    from tools.file_search_adapter import PowerShellSearchBridge

    _popen_mock, process = _patch_popen(
        mocker,
        stdout_lines=[],
        returncode=1,
        stderr_data="Exception: Search.CollatorDSO unavailable",
    )

    bridge = PowerShellSearchBridge()
    with pytest.raises(WindowsSearchUnavailableError) as excinfo:
        bridge.search(filename="x", phrase=None, roots=["C:\\Users\\ana"], top_n=10)

    message = str(excinfo.value)
    assert "produced no usable output" in message
    assert "exit code 1" in message
    assert "Search.CollatorDSO unavailable" in message


def test_bridge_search_nonzero_exit_code_with_no_rows_maps_to_windows_search_unavailable(mocker):
    from tools.file_search_adapter import PowerShellSearchBridge

    _popen_mock, process = _patch_popen(mocker, stdout_lines=[], returncode=1, stderr_data="boom")

    bridge = PowerShellSearchBridge()
    with pytest.raises(WindowsSearchUnavailableError) as excinfo:
        bridge.search(filename="x", phrase=None, roots=["C:\\Users\\ana"], top_n=10)
    message = str(excinfo.value)
    assert "produced no usable output" in message
    assert "exit code 1" in message
    assert "boom" in message


def test_bridge_search_script_error_json_line_with_zero_real_rows_raises(mocker):
    """BUG-006 volume-theory-dead hotfix (0061-cowork-bug006-volume-theory-
    dead-any-row-kills.md): `tools/ps_bridge_search.ps1`'s own top-level
    catch writes a single valid-JSON `{"error": "..."}` line to STDOUT
    (not stderr) before exiting nonzero when materializing a row fails
    catastrophically. That line is syntactically valid JSON and is NOT
    the `{"done": ...}` sentinel, so a naive reader would append it to
    `rows` as if it were a real result -- exactly the "zero rows parsed"
    rule's blind spot: a script-reported failure line must never count as
    a parsed row. With zero REAL rows ever streamed, this must raise
    WindowsSearchUnavailableError (carrying the exit condition/stderr),
    never a silent empty/garbage result."""
    from tools.file_search_adapter import PowerShellSearchBridge

    lines = [json.dumps({"error": "Exception reading System.ItemName"}) + "\n"]
    _popen_mock, process = _patch_popen(
        mocker, stdout_lines=lines, returncode=1, stderr_data=""
    )

    bridge = PowerShellSearchBridge()
    with pytest.raises(WindowsSearchUnavailableError) as excinfo:
        bridge.search(filename=None, phrase="Informa", roots=["C:\\Users\\ana"], top_n=200)

    message = str(excinfo.value)
    assert "produced no usable output" in message
    assert "exit code 1" in message


def test_bridge_search_script_error_json_line_after_real_rows_not_counted_as_row(mocker):
    """Same script-error-line shape, but arriving AFTER some genuine rows
    already streamed: the error line still must not be counted as (or
    turned into a garbage) result row -- only the real rows streamed
    before it are returned, still marked truncated (the sentinel was
    never reached)."""
    from tools.file_search_adapter import PowerShellSearchBridge

    real_row = {
        "ItemName": "one.txt",
        "ItemPathDisplay": "C:\\Users\\ana\\one.txt",
        "ItemUrl": None,
        "Size": 1,
        "DateModified": "2026-01-01T00:00:00",
        "Kind": None,
        "FileExtension": ".txt",
    }
    lines = [
        json.dumps(real_row) + "\n",
        json.dumps({"error": "Exception reading System.ItemName"}) + "\n",
    ]
    _popen_mock, process = _patch_popen(mocker, stdout_lines=lines, returncode=1)

    bridge = PowerShellSearchBridge()
    results = bridge.search(filename=None, phrase="Informa", roots=["C:\\Users\\ana"], top_n=200)

    assert len(results) == 1
    assert results[0].name == "one.txt"
    assert bridge.last_search_truncated is True


def test_bridge_search_stderr_read_returning_none_does_not_crash(mocker):
    """`_pump_stderr` guarded against a hostile `.read()` returning
    `None` -- a nonzero exit with no usable stderr must still map to the
    typed error, not raise a fresh exception while building that error's
    own message."""
    from tools.file_search_adapter import PowerShellSearchBridge

    _popen_mock, process = _patch_popen(mocker, stdout_lines=[], returncode=1)
    process.stderr = _NoneReadStream()

    bridge = PowerShellSearchBridge()
    with pytest.raises(WindowsSearchUnavailableError) as excinfo:
        bridge.search(filename="x", phrase=None, roots=["C:\\Users\\ana"], top_n=10)
    assert "exit code 1" in str(excinfo.value)


# --- Truncation-as-result vs. genuine corruption (streaming version of
# the ps-bridge-jsonl-hotfix rule) ---


def test_bridge_search_unparseable_line_raises_distinctly_worded_unavailable_error(mocker):
    """A line that is NOT the last line and still isn't valid JSON is
    genuine corruption (the script emitting something unexpected), not a
    truncated read -- must raise, with a message an operator can tell
    apart from a plain-truncation result, and the child must be killed
    (untrustworthy output)."""
    from tools.file_search_adapter import PowerShellSearchBridge

    lines = ["not json at all\n", json.dumps({"done": True, "count": 0}) + "\n"]
    _popen_mock, process = _patch_popen(mocker, stdout_lines=lines)

    bridge = PowerShellSearchBridge()
    with pytest.raises(WindowsSearchUnavailableError) as excinfo:
        bridge.search(filename="x", phrase=None, roots=["C:\\Users\\ana"], top_n=10)

    message = str(excinfo.value)
    assert message.startswith(
        "PowerShell search bridge returned unparseable output (not valid JSON Lines)"
    )
    assert "truncat" not in message.lower()
    assert "exit:" in message
    assert process.kill_calls == 1


def test_bridge_search_unparseable_line_message_includes_stderr_excerpt_when_present(mocker):
    from tools.file_search_adapter import PowerShellSearchBridge

    lines = ["not json at all\n", json.dumps({"done": True, "count": 0}) + "\n"]
    _patch_popen(mocker, stdout_lines=lines, stderr_data="script printed something odd")

    bridge = PowerShellSearchBridge()
    with pytest.raises(WindowsSearchUnavailableError) as excinfo:
        bridge.search(filename="x", phrase=None, roots=["C:\\Users\\ana"], top_n=10)

    assert "script printed something odd" in str(excinfo.value)


def test_bridge_search_missing_sentinel_returns_partial_rows_not_error(mocker):
    """A stream cut short before the `{"done": true, ...}` sentinel was
    ever written -- e.g. the child was killed mid-response, or exited on
    its own -- must NOT raise. It is a RESULT (truncation), not an error:
    the rows that parsed cleanly are returned."""
    from tools.file_search_adapter import PowerShellSearchBridge

    rows = [
        {
            "ItemName": "one.txt",
            "ItemPathDisplay": "C:\\Users\\ana\\one.txt",
            "ItemUrl": None,
            "Size": 1,
            "DateModified": "2026-01-01T00:00:00",
            "Kind": None,
            "FileExtension": ".txt",
        }
    ]
    _patch_popen(mocker, stdout_lines=_row_lines(rows, done=False))

    bridge = PowerShellSearchBridge()
    results = bridge.search(filename="x", phrase=None, roots=["C:\\Users\\ana"], top_n=10)

    assert len(results) == 1
    assert results[0].name == "one.txt"


def test_bridge_search_partial_last_line_returns_earlier_rows_not_error(mocker):
    """The exact shape a bounded/truncated read produces: a fragment of
    JSON on the last line (cut mid-object, no trailing newline) rather
    than a missing sentinel line outright. Must be dropped silently, not
    raised, and the complete rows before it are still returned."""
    from tools.file_search_adapter import PowerShellSearchBridge

    row = {
        "ItemName": "one.txt",
        "ItemPathDisplay": "C:\\Users\\ana\\one.txt",
        "ItemUrl": None,
        "Size": 1,
        "DateModified": "2026-01-01T00:00:00",
        "Kind": None,
        "FileExtension": ".txt",
    }
    lines = [json.dumps(row) + "\n", '{"ItemName": "cut-off-mid-rec']
    _patch_popen(mocker, stdout_lines=lines)

    bridge = PowerShellSearchBridge()
    results = bridge.search(filename="x", phrase=None, roots=["C:\\Users\\ana"], top_n=10)

    assert len(results) == 1
    assert results[0].name == "one.txt"


def test_bridge_search_solely_malformed_stdout_with_zero_rows_raises(mocker):
    """bridge-streaming-hotfix: repurposed from the ps-bridge-jsonl-hotfix
    era's `..._is_truncation_not_error` version, which returned an empty,
    truncated (no exception) result for this exact shape. That precedent
    predates requirement 4's tightened rule -- "zero rows no sentinel
    still maps to the typed no-output/timeout errors" -- an empty,
    truncated `[]` is indistinguishable from a genuinely broken bridge
    with nothing to show for it, so it is no longer silently accepted: a
    single wholly-malformed, unterminated fragment (no valid rows, no
    sentinel) is dropped as the expected shape of a truncated read (not
    corruption -- see the partial-last-line test below), but zero
    surviving rows plus no sentinel still raises, carrying the exit/
    stderr diagnostics."""
    from tools.file_search_adapter import PowerShellSearchBridge

    _patch_popen(mocker, stdout_lines=["{malformed"])

    bridge = PowerShellSearchBridge()
    with pytest.raises(WindowsSearchUnavailableError) as excinfo:
        bridge.search(filename=None, phrase="Informa", roots=["C:\\Users\\ana"], top_n=200)

    assert "produced no usable output" in str(excinfo.value)


def test_parse_bridge_stdout_reports_results_truncated_true_when_sentinel_missing():
    from tools.file_search_adapter import _parse_bridge_stdout

    rows, truncated = _parse_bridge_stdout("".join(_row_lines([{"ItemName": "a.txt"}], done=False)))

    assert rows == [{"ItemName": "a.txt"}]
    assert truncated is True


def test_parse_bridge_stdout_reports_results_truncated_false_when_sentinel_present():
    from tools.file_search_adapter import _parse_bridge_stdout

    rows, truncated = _parse_bridge_stdout("".join(_row_lines([{"ItemName": "a.txt"}])))

    assert rows == [{"ItemName": "a.txt"}]
    assert truncated is False


def test_parse_bridge_stdout_raises_on_non_last_line_corruption():
    from tools.file_search_adapter import _BridgeUnparseableLineError, _parse_bridge_stdout

    with pytest.raises(_BridgeUnparseableLineError):
        _parse_bridge_stdout('garbage\n{"done": true, "count": 0}\n')


# --- Unforeseen failures still map to the typed error, never raw
# (BUG-007 hotfix precedent, requirement 2's blanket mapping) ---


def test_bridge_search_unexpected_exception_during_spawn_maps_to_unavailable_not_raw(mocker):
    """Requirement 2's blanket mapping: ANYTHING unexpected raised while
    spawning/reading/parsing -- not just the enumerated OSError/
    `_BridgeUnparseableLineError` cases -- must still surface as
    `WindowsSearchUnavailableError`, never the raw exception type."""
    from tools.file_search_adapter import PowerShellSearchBridge

    mocker.patch(
        "tools.file_search_adapter.subprocess.Popen",
        side_effect=ValueError("some completely unforeseen failure"),
    )

    bridge = PowerShellSearchBridge()
    with pytest.raises(WindowsSearchUnavailableError) as excinfo:
        bridge.search(filename=None, phrase="Informa", roots=["C:\\Users\\ana"], top_n=200)
    assert "some completely unforeseen failure" in str(excinfo.value)


def test_bridge_get_info_unexpected_exception_during_invoke_maps_to_unavailable(mocker):
    from tools.file_search_adapter import PowerShellSearchBridge

    mocker.patch(
        "tools.file_search_adapter.subprocess.Popen",
        side_effect=RuntimeError("boom"),
    )

    bridge = PowerShellSearchBridge()
    with pytest.raises(WindowsSearchUnavailableError):
        bridge.get_info("C:\\Users\\ana\\report.docx")


def test_bridge_get_info_immediate_eof_no_sentinel_raises_unavailable_not_file_not_found(mocker):
    """Zero bytes and no sentinel is an ambiguous/failed read, not a
    confirmed "no such item" -- must not be mistaken for
    `FileNotFoundInIndexError` (a healthy, reachable index simply not
    matching)."""
    from tools.file_search_adapter import PowerShellSearchBridge

    _patch_popen(mocker, stdout_lines=[])

    bridge = PowerShellSearchBridge()
    with pytest.raises(WindowsSearchUnavailableError):
        bridge.get_info("C:\\Users\\ana\\report.docx")


# --- 3.10: valid JSON stdout parsed via _row_from_mapping() ---


def test_bridge_search_happy_path_sentinel_returns_rows_not_truncated(mocker):
    from tools.file_search_adapter import PowerShellSearchBridge

    rows = [
        {
            "ItemName": "report.docx",
            "ItemPathDisplay": "C:\\Users\\ana\\Documents\\report.docx",
            "ItemUrl": None,
            "Size": 4096,
            "DateModified": "2026-02-01T00:00:00",
            "Kind": ["document", "picture"],
            "FileExtension": ".docx",
        }
    ]
    _popen_mock, process = _patch_popen(mocker, stdout_lines=_row_lines(rows))

    bridge = PowerShellSearchBridge()
    results = bridge.search(filename="report", phrase=None, roots=["C:\\Users\\ana"], top_n=10)

    assert len(results) == 1
    assert isinstance(results[0], FileSummary)
    assert results[0].path == "C:\\Users\\ana\\Documents\\report.docx"
    assert results[0].name == "report.docx"
    assert results[0].size == 4096
    assert results[0].last_modified == datetime(2026, 2, 1)
    assert results[0].kind == "document; picture"
    assert results[0].extension == ".docx"
    assert bridge.last_search_truncated is False
    assert process.kill_calls == 0


def test_bridge_search_single_row_plus_sentinel_parses(mocker):
    """A single-row response is just one JSON-object line plus the
    sentinel line under the JSON Lines contract -- no array-collapsing
    ambiguity exists any more (that was a quirk of the prior
    single-JSON-document contract's `ConvertTo-Json` pipeline
    behavior)."""
    from tools.file_search_adapter import PowerShellSearchBridge

    row = {
        "ItemName": "single.txt",
        "ItemPathDisplay": "C:\\Users\\ana\\single.txt",
        "ItemUrl": None,
        "Size": 1,
        "DateModified": "2026-01-01T00:00:00",
        "Kind": None,
        "FileExtension": ".txt",
    }
    _patch_popen(mocker, stdout_lines=_row_lines([row]))

    bridge = PowerShellSearchBridge()
    results = bridge.search(filename="single", phrase=None, roots=["C:\\Users\\ana"], top_n=10)

    assert len(results) == 1
    assert results[0].name == "single.txt"


def test_bridge_get_info_parses_valid_json_row_into_file_detail(mocker):
    from tools.file_search_adapter import PowerShellSearchBridge

    row = {
        "ItemName": "report.docx",
        "ItemPathDisplay": "C:\\Users\\ana\\Documents\\report.docx",
        "ItemUrl": None,
        "Size": 2048,
        "DateModified": "2026-01-02T00:00:00",
        "DateCreated": "2025-12-01T00:00:00",
        "Kind": "document",
        "FileExtension": ".docx",
        "AutoSummary": "Quarterly report summary",
    }
    _patch_popen(mocker, stdout_lines=_row_lines([row]))

    bridge = PowerShellSearchBridge()
    detail = bridge.get_info("C:\\Users\\ana\\Documents\\report.docx")

    assert isinstance(detail, FileDetail)
    assert detail.path == "C:\\Users\\ana\\Documents\\report.docx"
    assert detail.created_time == datetime(2025, 12, 1)
    assert detail.snippet == "Quarterly report summary"


def test_bridge_get_info_empty_rows_raises_file_not_found_in_index(mocker):
    from tools.file_search_adapter import PowerShellSearchBridge

    _patch_popen(mocker, stdout_lines=_row_lines([]))

    bridge = PowerShellSearchBridge()
    with pytest.raises(FileNotFoundInIndexError):
        bridge.get_info("C:\\Users\\ana\\ghost.txt")


def test_bridge_get_info_sql_reuses_build_get_info_sql_not_argv(mocker):
    from tools.file_search_adapter import PowerShellSearchBridge, _build_get_info_sql

    popen_mock, process = _patch_popen(mocker, stdout_lines=_row_lines([]))

    bridge = PowerShellSearchBridge()
    with pytest.raises(FileNotFoundInIndexError):
        bridge.get_info("C:\\Users\\o'brien\\report.docx")

    argv_text = " ".join(str(a) for a in popen_mock.call_args.args[0])
    assert "o'brien" not in argv_text
    assert _stdin_sql(process) == _build_get_info_sql("C:\\Users\\o'brien\\report.docx")


def test_bridge_search_row_with_display_and_url_both_present_exposes_alt_url_path(mocker):
    """alias-containment-hotfix: same alias-vs-real-path pair as the ADO
    adapter's equivalent test, but via `_row_from_mapping` (the bridge's
    JSON-Lines row mapping)."""
    from tools.file_search_adapter import PowerShellSearchBridge

    row = {
        "ItemName": "notes.txt",
        "ItemPathDisplay": "C:\\Documents\\OneDrive - Informa\\notes.txt",
        "ItemUrl": "file:///C:/co/OneDrive%20-%20Informa/notes.txt",
        "Size": 10,
        "DateModified": "2026-01-01T00:00:00",
        "Kind": None,
        "FileExtension": ".txt",
    }
    _patch_popen(mocker, stdout_lines=_row_lines([row]))

    bridge = PowerShellSearchBridge()
    results = bridge.search(filename=None, phrase="Informa", roots=["C:\\co"], top_n=200)

    assert len(results) == 1
    assert results[0].path == "C:\\Documents\\OneDrive - Informa\\notes.txt"
    assert results[0].alt_url_path == "C:\\co\\OneDrive - Informa\\notes.txt"


def test_bridge_search_zero_rows_no_sentinel_raises_even_with_clean_exit_code_zero(mocker):
    """Sentinel-keyed failure rule (alias-containment-hotfix, verifier's
    refinement): zero rows and no sentinel is a failure regardless of the
    child's exit code — even a clean `exit code 0` (e.g. the script's
    stdout pipe closed before the read loop ever ran) MUST still raise,
    never be treated as a legitimate empty result. Only zero rows WITH
    the sentinel reached is a legitimate empty result (see
    test_bridge_search_zero_rows_no_sentinel_raises_with_exit_code_and_stderr_excerpt
    for the nonzero-exit-code half of this same rule)."""
    from tools.file_search_adapter import PowerShellSearchBridge

    _popen_mock, _process = _patch_popen(mocker, stdout_lines=[], returncode=0)

    bridge = PowerShellSearchBridge()
    with pytest.raises(WindowsSearchUnavailableError) as excinfo:
        bridge.search(filename="x", phrase=None, roots=["C:\\Users\\ana"], top_n=10)

    message = str(excinfo.value)
    assert "produced no usable output" in message
    assert "exit code 0" in message


# --- BUG-006 volume-theory-dead hotfix: permanent, config-gated bridge
# invocation debug log (0061-cowork-bug006-volume-theory-dead-any-row-
# kills.md) ---


def test_bridge_invocation_debug_log_writes_expected_line_shape_when_enabled(mocker, tmp_path):
    from tools import file_search_adapter

    log_path = tmp_path / "bridge_invocations.log"
    mocker.patch.object(file_search_adapter, "_BRIDGE_DEBUG_LOG_PATH", log_path)
    mocker.patch.object(file_search_adapter, "file_search_bridge_debug_log", return_value=True)

    rows = [
        {
            "ItemName": "one.txt",
            "ItemPathDisplay": "C:\\Users\\ana\\one.txt",
            "ItemUrl": None,
            "Size": 1,
            "DateModified": "2026-01-01T00:00:00",
            "Kind": None,
            "FileExtension": ".txt",
        }
    ]
    _patch_popen(mocker, stdout_lines=_row_lines(rows), stderr_data="")

    bridge = file_search_adapter.PowerShellSearchBridge()
    bridge.search(filename=None, phrase="Informa", roots=["C:\\Users\\ana"], top_n=200)

    assert log_path.exists()
    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["rows_streamed"] == 1
    assert record["sentinel_seen"] is True
    assert "exit code 0" in record["exit_condition"]
    assert record["sql_first_120"].startswith("SELECT TOP 200")
    assert isinstance(record["duration_seconds"], (int, float))
    assert "T" in record["utc"]
    assert record["stderr_first_200"] == ""
    assert record["error_line_first_200"] == ""


def test_bridge_invocation_debug_log_records_error_line_first_200_when_zero_rows_raises(
    mocker, tmp_path
):
    """alias-containment-hotfix piece 3: a script-reported `{"error":
    ...}` line's text must be recorded into the debug log under its own
    `error_line_first_200` field (distinct from the general
    `stderr_first_200` excerpt) so an operator can find it directly."""
    from tools import file_search_adapter

    log_path = tmp_path / "bridge_invocations.log"
    mocker.patch.object(file_search_adapter, "_BRIDGE_DEBUG_LOG_PATH", log_path)
    mocker.patch.object(file_search_adapter, "file_search_bridge_debug_log", return_value=True)

    lines = [json.dumps({"error": "Exception reading System.ItemName"}) + "\n"]
    _patch_popen(mocker, stdout_lines=lines, returncode=1)

    bridge = file_search_adapter.PowerShellSearchBridge()
    with pytest.raises(WindowsSearchUnavailableError):
        bridge.search(filename=None, phrase="Informa", roots=["C:\\Users\\ana"], top_n=200)

    record = json.loads(log_path.read_text(encoding="utf-8").strip())
    assert record["error_line_first_200"] == "Exception reading System.ItemName"


def test_bridge_invocation_debug_log_records_error_line_first_200_after_partial_success(
    mocker, tmp_path
):
    """A script-error line arriving AFTER real rows already streamed does
    NOT raise (the rows are returned as a truncated result), but the
    error text must still land in the debug log so this partial-success
    failure stays diagnosable — this was the live evidence's exact shape
    (50 rows streamed, then the OleDb rowset's second chunk fetch died)."""
    from tools import file_search_adapter

    log_path = tmp_path / "bridge_invocations.log"
    mocker.patch.object(file_search_adapter, "_BRIDGE_DEBUG_LOG_PATH", log_path)
    mocker.patch.object(file_search_adapter, "file_search_bridge_debug_log", return_value=True)

    real_row = {
        "ItemName": "one.txt",
        "ItemPathDisplay": "C:\\Users\\ana\\one.txt",
        "ItemUrl": None,
        "Size": 1,
        "DateModified": "2026-01-01T00:00:00",
        "Kind": None,
        "FileExtension": ".txt",
    }
    lines = [
        json.dumps(real_row) + "\n",
        json.dumps({"error": "Exception reading System.ItemName"}) + "\n",
    ]
    _patch_popen(mocker, stdout_lines=lines, returncode=1)

    bridge = file_search_adapter.PowerShellSearchBridge()
    results = bridge.search(filename=None, phrase="Informa", roots=["C:\\Users\\ana"], top_n=200)

    assert len(results) == 1
    record = json.loads(log_path.read_text(encoding="utf-8").strip())
    assert record["rows_streamed"] == 1
    assert record["error_line_first_200"] == "Exception reading System.ItemName"


def test_bridge_invocation_debug_log_writes_nothing_when_disabled(mocker, tmp_path):
    from tools import file_search_adapter

    log_path = tmp_path / "bridge_invocations.log"
    mocker.patch.object(file_search_adapter, "_BRIDGE_DEBUG_LOG_PATH", log_path)
    mocker.patch.object(file_search_adapter, "file_search_bridge_debug_log", return_value=False)

    _patch_popen(mocker, stdout_lines=_row_lines([]))

    bridge = file_search_adapter.PowerShellSearchBridge()
    bridge.search(filename=None, phrase="Informa", roots=["C:\\Users\\ana"], top_n=200)

    assert not log_path.exists()


def test_bridge_invocation_debug_log_written_even_when_search_raises(mocker, tmp_path):
    """The log is a diagnostic aid independent of the call's outcome --
    it MUST still be written when the bridge itself raises
    WindowsSearchUnavailableError, capturing the exit condition/stderr
    that would otherwise only reach the caller as a wrapped message."""
    from tools import file_search_adapter

    log_path = tmp_path / "bridge_invocations.log"
    mocker.patch.object(file_search_adapter, "_BRIDGE_DEBUG_LOG_PATH", log_path)
    mocker.patch.object(file_search_adapter, "file_search_bridge_debug_log", return_value=True)

    _patch_popen(mocker, stdout_lines=[], returncode=1, stderr_data="boom")

    bridge = file_search_adapter.PowerShellSearchBridge()
    with pytest.raises(WindowsSearchUnavailableError):
        bridge.search(filename=None, phrase="Informa", roots=["C:\\Users\\ana"], top_n=200)

    record = json.loads(log_path.read_text(encoding="utf-8").strip())
    assert record["rows_streamed"] == 0
    assert record["sentinel_seen"] is False
    assert "exit code 1" in record["exit_condition"]
    assert record["stderr_first_200"] == "boom"


def test_bridge_invocation_debug_log_never_raises_when_write_fails(mocker):
    """Best-effort only: a broken log path must never surface as an
    exception from `search()` itself, regardless of the underlying
    call's own success/failure."""
    from tools import file_search_adapter

    unwritable = Path("/nonexistent-dir-for-test/bridge_invocations.log")
    mocker.patch.object(file_search_adapter, "_BRIDGE_DEBUG_LOG_PATH", unwritable)
    mocker.patch.object(file_search_adapter, "file_search_bridge_debug_log", return_value=True)

    _patch_popen(mocker, stdout_lines=_row_lines([]))

    bridge = file_search_adapter.PowerShellSearchBridge()
    bridge.search(filename=None, phrase="Informa", roots=["C:\\Users\\ana"], top_n=200)


# --- Phase 4: FallbackSearchAdapter (file-search-resilience change) ---
#
# Pure composition seam over two FileSearchPort doubles — no
# subprocess/COM access at all, so plain hand-rolled stubs suffice.


class _StubPort:
    """Minimal FileSearchPort double: returns a fixed result or raises a
    fixed exception, and records how many times each method was called
    so a test can assert the bridge was/was not invoked. `last_search_truncated`
    (bridge-streaming-hotfix) is a plain settable attribute — the same
    documented, duck-typed signal `PowerShellSearchBridge`/`FallbackSearchAdapter`
    expose — so a test can simulate "the bridge's search() call was
    truncated" without any subprocess mocking."""

    def __init__(self, *, search_result=None, search_error=None, info_result=None, info_error=None):
        self.search_calls = 0
        self.info_calls = 0
        self._search_result = search_result
        self._search_error = search_error
        self._info_result = info_result
        self._info_error = info_error
        self.last_search_truncated = False

    def search(self, filename, phrase, roots, top_n):
        self.search_calls += 1
        if self._search_error is not None:
            raise self._search_error
        return self._search_result

    def get_info(self, path_or_url):
        self.info_calls += 1
        if self._info_error is not None:
            raise self._info_error
        return self._info_result


def _summary(name="report.docx"):
    return FileSummary(
        path=f"C:\\Users\\ana\\{name}",
        name=name,
        size=10,
        last_modified=datetime(2026, 1, 1),
    )


def _detail(name="report.docx"):
    return FileDetail(
        path=f"C:\\Users\\ana\\{name}",
        name=name,
        size=10,
        last_modified=datetime(2026, 1, 1),
        created_time=datetime(2025, 12, 1),
    )


# --- 4.1: primary success skips the bridge entirely ---


def test_fallback_search_skips_bridge_when_primary_succeeds():
    from tools.file_search_adapter import FallbackSearchAdapter

    primary_results = [_summary()]
    primary = _StubPort(search_result=primary_results)
    bridge = _StubPort(search_error=WindowsSearchUnavailableError("should never be called"))

    adapter = FallbackSearchAdapter(primary=primary, bridge=bridge)
    results = adapter.search(filename="report", phrase=None, roots=["C:\\Users\\ana"], top_n=10)

    assert results == primary_results
    assert bridge.search_calls == 0
    assert primary.search_calls == 1


def test_fallback_get_info_skips_bridge_when_primary_succeeds():
    from tools.file_search_adapter import FallbackSearchAdapter

    detail = _detail()
    primary = _StubPort(info_result=detail)
    bridge = _StubPort(info_error=WindowsSearchUnavailableError("should never be called"))

    adapter = FallbackSearchAdapter(primary=primary, bridge=bridge)
    result = adapter.get_info("C:\\Users\\ana\\report.docx")

    assert result == detail
    assert bridge.info_calls == 0


# --- 4.2: ADO failure falls through to the bridge, whose result is used ---


def test_fallback_search_invokes_bridge_after_primary_raises_unavailable():
    from tools.file_search_adapter import FallbackSearchAdapter

    bridge_results = [_summary("bridged.docx")]
    primary = _StubPort(search_error=WindowsSearchUnavailableError("ADO unreachable"))
    bridge = _StubPort(search_result=bridge_results)

    adapter = FallbackSearchAdapter(primary=primary, bridge=bridge)
    results = adapter.search(filename="report", phrase=None, roots=["C:\\Users\\ana"], top_n=10)

    assert results == bridge_results
    assert primary.search_calls == 1
    assert bridge.search_calls == 1


def test_fallback_get_info_invokes_bridge_after_primary_raises_unavailable():
    from tools.file_search_adapter import FallbackSearchAdapter

    bridge_detail = _detail("bridged.docx")
    primary = _StubPort(info_error=WindowsSearchUnavailableError("ADO unreachable"))
    bridge = _StubPort(info_result=bridge_detail)

    adapter = FallbackSearchAdapter(primary=primary, bridge=bridge)
    result = adapter.get_info("C:\\Users\\ana\\report.docx")

    assert result == bridge_detail
    assert bridge.info_calls == 1


# --- 4.3: both transports exhausted propagates the typed error unchanged ---


def test_fallback_search_both_transports_exhausted_propagates_unchanged():
    from tools.file_search_adapter import FallbackSearchAdapter

    primary = _StubPort(search_error=WindowsSearchUnavailableError("ADO unreachable"))
    bridge_error = WindowsSearchUnavailableError("bridge also unreachable")
    bridge = _StubPort(search_error=bridge_error)

    adapter = FallbackSearchAdapter(primary=primary, bridge=bridge)
    with pytest.raises(WindowsSearchUnavailableError) as excinfo:
        adapter.search(filename="report", phrase=None, roots=["C:\\Users\\ana"], top_n=10)

    # unchanged: the tool layer (a later batch), not this seam, adds any
    # "filename search still works" messaging -- see windows-search-adapter
    # spec's "Fallback Transport Ordering" requirement.
    assert str(excinfo.value) == "bridge also unreachable"


def test_fallback_get_info_both_transports_exhausted_propagates_unchanged():
    from tools.file_search_adapter import FallbackSearchAdapter

    primary = _StubPort(info_error=WindowsSearchUnavailableError("ADO unreachable"))
    bridge_error = WindowsSearchUnavailableError("bridge also unreachable")
    bridge = _StubPort(info_error=bridge_error)

    adapter = FallbackSearchAdapter(primary=primary, bridge=bridge)
    with pytest.raises(WindowsSearchUnavailableError) as excinfo:
        adapter.get_info("C:\\Users\\ana\\report.docx")

    assert str(excinfo.value) == "bridge also unreachable"


def test_fallback_get_info_file_not_found_never_tries_bridge():
    """Triangulation: a reachable-but-not-indexed path (FileNotFoundInIndexError)
    is NOT a transport failure -- must not fall through to the bridge."""
    from tools.file_search_adapter import FallbackSearchAdapter

    primary = _StubPort(info_error=FileNotFoundInIndexError("not indexed"))
    bridge = _StubPort(info_error=WindowsSearchUnavailableError("should never be called"))

    adapter = FallbackSearchAdapter(primary=primary, bridge=bridge)
    with pytest.raises(FileNotFoundInIndexError):
        adapter.get_info("C:\\Users\\ana\\ghost.txt")

    assert bridge.info_calls == 0


# --- 4.4: default construction wires the real transports ---


def test_fallback_search_adapter_default_construction_wires_real_transports():
    from tools.file_search_adapter import (
        FallbackSearchAdapter,
        PowerShellSearchBridge,
        WindowsSearchAdapter,
    )

    adapter = FallbackSearchAdapter()

    assert isinstance(adapter._primary, WindowsSearchAdapter)
    assert isinstance(adapter._bridge, PowerShellSearchBridge)


# --- 4.5: last_search_truncated propagation (bridge-streaming-hotfix) ---


def test_fallback_search_last_search_truncated_false_when_primary_succeeds():
    from tools.file_search_adapter import FallbackSearchAdapter

    primary = _StubPort(search_result=[_summary()])
    bridge = _StubPort(search_error=WindowsSearchUnavailableError("should never be called"))

    adapter = FallbackSearchAdapter(primary=primary, bridge=bridge)
    adapter.search(filename="report", phrase=None, roots=["C:\\Users\\ana"], top_n=10)

    assert adapter.last_search_truncated is False


def test_fallback_search_last_search_truncated_mirrors_bridge_when_bridge_serves_result():
    """The bridge's own `last_search_truncated` (set by its `search()`)
    is what `FallbackSearchAdapter` mirrors once ADO has failed and the
    bridge served the result instead."""
    from tools.file_search_adapter import FallbackSearchAdapter

    primary = _StubPort(search_error=WindowsSearchUnavailableError("ADO unreachable"))
    bridge = _StubPort(search_result=[_summary("bridged.docx")])
    bridge.last_search_truncated = True

    adapter = FallbackSearchAdapter(primary=primary, bridge=bridge)
    adapter.search(filename="report", phrase=None, roots=["C:\\Users\\ana"], top_n=10)

    assert adapter.last_search_truncated is True


def test_fallback_search_last_search_truncated_false_when_bridge_result_is_complete():
    from tools.file_search_adapter import FallbackSearchAdapter

    primary = _StubPort(search_error=WindowsSearchUnavailableError("ADO unreachable"))
    bridge = _StubPort(search_result=[_summary("bridged.docx")])
    bridge.last_search_truncated = False

    adapter = FallbackSearchAdapter(primary=primary, bridge=bridge)
    adapter.search(filename="report", phrase=None, roots=["C:\\Users\\ana"], top_n=10)

    assert adapter.last_search_truncated is False


def test_fallback_search_last_search_truncated_defaults_false_for_plain_windows_search_adapter(mocker):
    """A real `WindowsSearchAdapter` (no `last_search_truncated` attribute
    of its own beyond the class-level `False` default) never leaves
    `FallbackSearchAdapter.last_search_truncated` stuck at a stale `True`
    from an earlier call."""
    from tools.file_search_adapter import FallbackSearchAdapter, WindowsSearchAdapter

    assert WindowsSearchAdapter.last_search_truncated is False


def test_bridge_last_search_truncated_starts_false_before_any_call():
    from tools.file_search_adapter import PowerShellSearchBridge

    bridge = PowerShellSearchBridge()

    assert bridge.last_search_truncated is False


# --- BUG-006 round 2 (file_write/0069, live-reproduced 2026-08-31): the
# index emits System.ItemUrl as `file:C:/...` — NO slashes after the
# colon — while _decode_item_url only stripped the `file:///` form. The
# residue kept the `file:` prefix glued to alt_url_path, containment
# rejected every row, and 200 streamed rows became a clean []. The URL
# form below is VERBATIM from the live PRO probe at 13:39Z.


def test_decode_item_url_handles_slashless_file_prefix():
    from tools.file_search_adapter import _decode_item_url

    assert (
        _decode_item_url("file:C:/co/OneDrive%20-%20Informa/notes.txt")
        == "C:\\co\\OneDrive - Informa\\notes.txt"
    )


def test_decode_item_url_still_handles_triple_slash_form():
    from tools.file_search_adapter import _decode_item_url

    assert (
        _decode_item_url("file:///C:/co/OneDrive%20-%20Informa/notes.txt")
        == "C:\\co\\OneDrive - Informa\\notes.txt"
    )


def test_bridge_row_with_slashless_file_url_gets_containable_alt_path(mocker):
    """The live defect end-to-end at the adapter seam: alias display path
    plus the slashless URL form must yield a NATIVE alt_url_path that
    containment can match — never a string still carrying `file:`."""
    from tools.file_search_adapter import PowerShellSearchBridge

    row = {
        "ItemName": "Powerpoint_Informa-ENG_v26.potx",
        "ItemPathDisplay": "C:\\Documents\\OneDrive - Informa\\Powerpoint_Informa-ENG_v26.potx",
        "ItemUrl": "file:C:/co/OneDrive%20-%20Informa/Powerpoint_Informa-ENG_v26.potx",
        "Size": 10,
        "DateModified": "2026-01-01T00:00:00",
        "Kind": None,
        "FileExtension": ".potx",
    }
    _patch_popen(mocker, stdout_lines=_row_lines([row]))

    bridge = PowerShellSearchBridge()
    results = bridge.search(filename=None, phrase="Informa", roots=["C:\\co"], top_n=200)

    assert results[0].alt_url_path == "C:\\co\\OneDrive - Informa\\Powerpoint_Informa-ENG_v26.potx"


# --- BUG-006 round 2, second defect (file_write/0069): a result set that
# FILLS the SQL TOP cap may have more matches behind it — both transports
# must report last_search_truncated, not just a broken bridge stream.


def test_bridge_search_filling_top_cap_sets_last_search_truncated(mocker):
    from tools.file_search_adapter import PowerShellSearchBridge

    rows = [
        {
            "ItemName": f"f{i}.txt",
            "ItemPathDisplay": f"C:\\co\\f{i}.txt",
            "ItemUrl": f"file:C:/co/f{i}.txt",
            "Size": 1,
            "DateModified": "2026-01-01T00:00:00",
            "Kind": None,
            "FileExtension": ".txt",
        }
        for i in range(3)
    ]
    _patch_popen(mocker, stdout_lines=_row_lines(rows))

    bridge = PowerShellSearchBridge()
    results = bridge.search(filename=None, phrase="x", roots=["C:\\co"], top_n=3)

    assert len(results) == 3
    assert bridge.last_search_truncated is True


def test_bridge_search_below_top_cap_stays_untruncated(mocker):
    from tools.file_search_adapter import PowerShellSearchBridge

    rows = [
        {
            "ItemName": "f.txt",
            "ItemPathDisplay": "C:\\co\\f.txt",
            "ItemUrl": "file:C:/co/f.txt",
            "Size": 1,
            "DateModified": "2026-01-01T00:00:00",
            "Kind": None,
            "FileExtension": ".txt",
        }
    ]
    _patch_popen(mocker, stdout_lines=_row_lines(rows))

    bridge = PowerShellSearchBridge()
    results = bridge.search(filename=None, phrase="x", roots=["C:\\co"], top_n=3)

    assert len(results) == 1
    assert bridge.last_search_truncated is False
