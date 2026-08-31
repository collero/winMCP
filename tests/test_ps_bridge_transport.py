"""Tests for tools/ps_bridge_transport.py's `PsBridgeTransport` — the
use-case-agnostic PowerShell-bridge transport shared by every adapter that
talks to a pinned `powershell.exe` 5.1 child (design.md's "Extract shared
PS-bridge transport" decision, ahead of both `file_search_adapter.py`'s
refactor onto it and the new OneNote adapter built on it from day one).

Mirrors tests/test_file_search_adapter.py's `_FakeProcess`/`_LineStream`/
`_FixedReadStream`/`_patch_popen` doubles for `subprocess.Popen` — no real
PowerShell is ever invoked (none exists on this WSL2 host anyway). This
module's own `subprocess.Popen` is the one patched here (not
`tools.file_search_adapter.subprocess.Popen`), since after the refactor
this is where the actual spawn happens.
"""
import json
import threading

import pytest

from tools.ps_bridge_transport import (
    PsBridgeTransport,
    PsBridgeTransportError,
    _PS_EXE,
)


# --- Test doubles for subprocess.Popen (mirrors test_file_search_adapter.py) ---


class _FakeStdin:
    def __init__(self) -> None:
        self.written = ""
        self.closed = False

    def write(self, data: str) -> None:
        self.written += data

    def close(self) -> None:
        self.closed = True


class _LineStream:
    """Pops entries off `lines` one `readline()` call at a time. Once
    exhausted: `"eof"` returns `""` forever; `"hang"` blocks forever on an
    Event that is never set (only safe because the reader thread that
    calls this is a daemon thread the transport never joins indefinitely)."""

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
    def __init__(self, data: str = "") -> None:
        self._data = data

    def read(self) -> str:
        return self._data


class _FakeProcess:
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


def _row_lines(rows: list[dict], *, count: int | None = None, done: bool = True) -> list[str]:
    lines = [json.dumps(row) + "\n" for row in rows]
    if done:
        lines.append(
            json.dumps({"done": True, "count": count if count is not None else len(rows)}) + "\n"
        )
    return lines


def _patch_popen(mocker, stdout_lines=(), *, at_end="eof", stderr_data="", returncode=0):
    process = _FakeProcess(list(stdout_lines), at_end=at_end, stderr_data=stderr_data, returncode=returncode)
    popen_mock = mocker.patch("tools.ps_bridge_transport.subprocess.Popen", return_value=process)
    return popen_mock, process


SCRIPT_PATH = "/deploy/tools/ps_bridge_fake.ps1"


# --- Pinned exe / argv shape ---


def test_invoke_uses_pinned_absolute_powershell_with_file_flag(mocker):
    import subprocess

    popen_mock, _process = _patch_popen(mocker, stdout_lines=_row_lines([]))

    transport = PsBridgeTransport()
    transport.invoke(SCRIPT_PATH, {"op": "ping"}, timeout=5)

    argv = popen_mock.call_args.args[0]
    assert argv == [
        _PS_EXE,
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        SCRIPT_PATH,
    ]
    assert popen_mock.call_args.kwargs["text"] is True
    assert popen_mock.call_args.kwargs["stdin"] == subprocess.PIPE
    assert popen_mock.call_args.kwargs["stdout"] == subprocess.PIPE
    assert popen_mock.call_args.kwargs["stderr"] == subprocess.PIPE


def test_invoke_decodes_child_streams_as_utf8_with_replace(mocker):
    # Live-QA defect (add-onenote-adapter, 2026-08-27): with text=True and
    # no explicit encoding, the child's stdout was decoded with the
    # locale's preferred encoding — on the deployed Windows host that
    # made the reader thread die at the first non-ASCII byte the bridge
    # emitted (accented OneNote section names), silently TRUNCATING the
    # stream mid-run. The bridges now emit UTF-8 ([Console]::OutputEncoding)
    # and the transport must pin the matching decode; errors="replace"
    # degrades a rogue byte to U+FFFD instead of killing the stream.
    popen_mock, _process = _patch_popen(mocker, stdout_lines=_row_lines([]))

    transport = PsBridgeTransport()
    transport.invoke(SCRIPT_PATH, {"op": "ping"}, timeout=5)

    assert popen_mock.call_args.kwargs["encoding"] == "utf-8"
    assert popen_mock.call_args.kwargs["errors"] == "replace"


def test_invoke_writes_request_as_json_to_stdin_and_closes_it(mocker):
    _popen_mock, process = _patch_popen(mocker, stdout_lines=_row_lines([]))

    transport = PsBridgeTransport()
    transport.invoke(SCRIPT_PATH, {"op": "search", "query": "factura"}, timeout=5)

    assert process.stdin.closed is True
    payload = json.loads(process.stdin.written)
    assert payload == {"op": "search", "query": "factura"}


# --- Sentinel -> (rows, False) ---


def test_invoke_sentinel_returns_rows_not_truncated(mocker):
    rows = [{"id": "1", "title": "one"}, {"id": "2", "title": "two"}]
    _patch_popen(mocker, stdout_lines=_row_lines(rows))

    transport = PsBridgeTransport()
    result_rows, truncated = transport.invoke(SCRIPT_PATH, {"op": "search"}, timeout=5)

    assert result_rows == rows
    assert truncated is False


# --- Truncated-no-sentinel-with-rows -> (rows, True) ---


def test_invoke_child_dies_after_rows_no_sentinel_is_truncated_not_error(mocker):
    rows = [{"id": "1", "title": "one"}]
    _patch_popen(mocker, stdout_lines=_row_lines(rows, done=False))

    transport = PsBridgeTransport()
    result_rows, truncated = transport.invoke(SCRIPT_PATH, {"op": "search"}, timeout=5)

    assert result_rows == rows
    assert truncated is True


def test_invoke_deadline_kills_hung_child_after_streaming_rows_returns_partial(mocker):
    """The core streaming requirement: a child that streams some rows then
    stops responding (never closes its pipe, never writes the sentinel) is
    killed once the deadline elapses, and the rows already streamed come
    back as a truncated RESULT, not an error."""
    rows = [{"id": "1", "title": "one"}]
    _popen_mock, process = _patch_popen(
        mocker, stdout_lines=_row_lines(rows, done=False), at_end="hang"
    )

    transport = PsBridgeTransport()
    result_rows, truncated = transport.invoke(SCRIPT_PATH, {"op": "search"}, timeout=0.05)

    assert result_rows == rows
    assert truncated is True
    assert process.kill_calls >= 1


def test_invoke_deadline_kills_child_zero_rows_message_names_killed_at_seconds(mocker):
    _popen_mock, process = _patch_popen(mocker, stdout_lines=[], at_end="hang")

    transport = PsBridgeTransport()
    with pytest.raises(PsBridgeTransportError) as excinfo:
        transport.invoke(SCRIPT_PATH, {"op": "search"}, timeout=0.05)

    message = str(excinfo.value)
    assert "produced no usable output" in message
    assert "killed@0.05s" in message
    assert process.kill_calls == 1


# --- Zero-rows-no-sentinel -> raises PsBridgeTransportError ---


def test_invoke_zero_rows_no_sentinel_raises_with_exit_code_and_stderr(mocker):
    _patch_popen(mocker, stdout_lines=[], returncode=1, stderr_data="Exception: boom")

    transport = PsBridgeTransport()
    with pytest.raises(PsBridgeTransportError) as excinfo:
        transport.invoke(SCRIPT_PATH, {"op": "search"}, timeout=5)

    message = str(excinfo.value)
    assert "produced no usable output" in message
    assert "exit code 1" in message
    assert "Exception: boom" in message


def test_invoke_spawn_blocked_maps_to_distinctly_worded_error(mocker):
    mocker.patch(
        "tools.ps_bridge_transport.subprocess.Popen",
        side_effect=FileNotFoundError("no such file: powershell.exe"),
    )

    transport = PsBridgeTransport()
    with pytest.raises(PsBridgeTransportError) as excinfo:
        transport.invoke(SCRIPT_PATH, {"op": "search"}, timeout=5)

    message = str(excinfo.value)
    assert message == "PowerShell bridge blocked or unavailable: no such file: powershell.exe"


# --- Corrupt non-last line -> raises ---


def test_invoke_corrupt_non_last_line_raises_distinctly_worded_error(mocker):
    lines = ["not json at all\n", json.dumps({"done": True, "count": 0}) + "\n"]
    _popen_mock, process = _patch_popen(mocker, stdout_lines=lines)

    transport = PsBridgeTransport()
    with pytest.raises(PsBridgeTransportError) as excinfo:
        transport.invoke(SCRIPT_PATH, {"op": "search"}, timeout=5)

    message = str(excinfo.value)
    assert message.startswith(
        "PowerShell bridge returned unparseable output (not valid JSON Lines)"
    )
    assert "truncat" not in message.lower()
    assert process.kill_calls == 1


def test_invoke_partial_last_line_returns_earlier_rows_not_error(mocker):
    """A fragment cut mid-object on the LAST line (no trailing newline) is
    the expected shape of a truncated read, not corruption -- must not
    raise, and earlier complete rows are still returned."""
    row = {"id": "1", "title": "one"}
    lines = [json.dumps(row) + "\n", '{"id": "cut-off-mid-rec']
    _patch_popen(mocker, stdout_lines=lines)

    transport = PsBridgeTransport()
    rows, truncated = transport.invoke(SCRIPT_PATH, {"op": "search"}, timeout=5)

    assert rows == [row]
    assert truncated is True


# --- log_label parametrizes message wording ---


def test_invoke_log_label_parametrizes_no_usable_output_message(mocker):
    _patch_popen(mocker, stdout_lines=[], returncode=1)

    transport = PsBridgeTransport()
    with pytest.raises(PsBridgeTransportError) as excinfo:
        transport.invoke(SCRIPT_PATH, {"op": "search"}, timeout=5, log_label="onenote")

    assert "PowerShell onenote bridge produced no usable output" in str(excinfo.value)


# --- error JSON line from the script itself ---


def test_invoke_script_error_line_with_zero_real_rows_raises(mocker):
    lines = [json.dumps({"error": "Exception reading page"}) + "\n"]
    _patch_popen(mocker, stdout_lines=lines, returncode=1)

    transport = PsBridgeTransport()
    with pytest.raises(PsBridgeTransportError) as excinfo:
        transport.invoke(SCRIPT_PATH, {"op": "search"}, timeout=5)

    assert "produced no usable output" in str(excinfo.value)


def test_invoke_script_error_line_after_real_rows_not_counted_as_row(mocker):
    real_row = {"id": "1", "title": "one"}
    lines = [
        json.dumps(real_row) + "\n",
        json.dumps({"error": "Exception reading page"}) + "\n",
    ]
    _patch_popen(mocker, stdout_lines=lines, returncode=1)

    transport = PsBridgeTransport()
    rows, truncated = transport.invoke(SCRIPT_PATH, {"op": "search"}, timeout=5)

    assert rows == [real_row]
    assert truncated is True


# --- diagnostics output param ---


def test_invoke_diagnostics_dict_populated_on_success(mocker):
    rows = [{"id": "1", "title": "one"}]
    _patch_popen(mocker, stdout_lines=_row_lines(rows))

    transport = PsBridgeTransport()
    diagnostics: dict = {}
    transport.invoke(SCRIPT_PATH, {"op": "search"}, timeout=5, diagnostics=diagnostics)

    assert diagnostics["rows_streamed"] == 1
    assert diagnostics["sentinel_seen"] is True
    assert "exit code 0" in diagnostics["exit_condition"]
    assert diagnostics["stderr_excerpt"] == ""
    assert diagnostics["error_line_first_200"] == ""


def test_invoke_diagnostics_dict_populated_when_raising(mocker):
    _patch_popen(mocker, stdout_lines=[], returncode=1, stderr_data="boom")

    transport = PsBridgeTransport()
    diagnostics: dict = {}
    with pytest.raises(PsBridgeTransportError):
        transport.invoke(SCRIPT_PATH, {"op": "search"}, timeout=5, diagnostics=diagnostics)

    assert diagnostics["rows_streamed"] == 0
    assert diagnostics["sentinel_seen"] is False
    assert "exit code 1" in diagnostics["exit_condition"]
    assert diagnostics["stderr_excerpt"] == "boom"


# --- debug-log gated by callback ---


def test_invoke_debug_log_hook_calls_logger_when_enabled(mocker):
    rows = [{"id": "1", "title": "one"}]
    _patch_popen(mocker, stdout_lines=_row_lines(rows))

    logger_calls = []

    def fake_logger(log_label, record):
        logger_calls.append((log_label, record))

    transport = PsBridgeTransport()
    transport.invoke(
        SCRIPT_PATH,
        {"op": "search"},
        timeout=5,
        debug_log_enabled=lambda: True,
        log_label="onenote",
        logger=fake_logger,
    )

    assert len(logger_calls) == 1
    label, record = logger_calls[0]
    assert label == "onenote"
    assert record["rows_streamed"] == 1
    assert record["sentinel_seen"] is True


def test_invoke_debug_log_hook_not_called_when_disabled(mocker):
    _patch_popen(mocker, stdout_lines=_row_lines([]))

    logger_calls = []

    transport = PsBridgeTransport()
    transport.invoke(
        SCRIPT_PATH,
        {"op": "search"},
        timeout=5,
        debug_log_enabled=lambda: False,
        log_label="onenote",
        logger=lambda label, record: logger_calls.append((label, record)),
    )

    assert logger_calls == []


def test_invoke_debug_log_hook_fires_even_when_invoke_raises(mocker):
    _patch_popen(mocker, stdout_lines=[], returncode=1, stderr_data="boom")

    logger_calls = []

    transport = PsBridgeTransport()
    with pytest.raises(PsBridgeTransportError):
        transport.invoke(
            SCRIPT_PATH,
            {"op": "search"},
            timeout=5,
            debug_log_enabled=lambda: True,
            log_label="onenote",
            logger=lambda label, record: logger_calls.append((label, record)),
        )

    assert len(logger_calls) == 1
    label, record = logger_calls[0]
    assert label == "onenote"
    assert "exit code 1" in record["exit_condition"]
    assert record["stderr_excerpt"] == "boom"


def test_invoke_debug_log_hook_never_raises_when_logger_itself_raises(mocker):
    """Best-effort: a broken logger callback must never surface as an
    exception from invoke() itself."""
    _patch_popen(mocker, stdout_lines=_row_lines([]))

    transport = PsBridgeTransport()
    transport.invoke(
        SCRIPT_PATH,
        {"op": "search"},
        timeout=5,
        debug_log_enabled=lambda: True,
        log_label="onenote",
        logger=lambda label, record: (_ for _ in ()).throw(RuntimeError("logger boom")),
    )


# --- unexpected exception maps to the typed error, never raw ---


def test_invoke_unexpected_exception_during_spawn_maps_to_transport_error(mocker):
    mocker.patch(
        "tools.ps_bridge_transport.subprocess.Popen",
        side_effect=ValueError("some completely unforeseen failure"),
    )

    transport = PsBridgeTransport()
    with pytest.raises(PsBridgeTransportError) as excinfo:
        transport.invoke(SCRIPT_PATH, {"op": "search"}, timeout=5)

    assert "some completely unforeseen failure" in str(excinfo.value)
